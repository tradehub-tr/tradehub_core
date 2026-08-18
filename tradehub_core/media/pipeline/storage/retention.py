"""T-053 — Saklama (retention): iki bağımsız politika, legal hold hepsini bloke eder.

MEVCUT KOD OKUNDU, YENİDEN YAZILMADI
------------------------------------
Üretimde saklama ZATEN dört ayrı pencerede çalışıyor ve bu modül onların
hiçbirini yeniden yazmıyor:

    tradehub_core/media/trash.py      çöp: 30 gün (TRASH_RETENTION_DAYS),
                                      `purge_expired` mtime'a bakar
    tradehub_core/media/archive.py    optimizasyon arşivi: 30 gün
                                      (ARCHIVE_RETENTION_DAYS)
    tradehub_core/media/backup.py     yedek: 14 set (KEEP_SETS), içerik-adresli
                                      havuz + `prune`
    tradehub_core/media/usage.py      "kullanılıyor mu" kararı (verdict)

Bu modülün eklediği üç şey:

  1. **İki bağımsız politikanın tek yerde ifadesi.** `original_retention` ve
     `derivative_retention` birbirini ETKİLEMEZ (`docs/standards/retention.md`
     §6). Bugün türev diye bir varlık yok (§5.4), dolayısıyla türev politikası
     bugün boş kümeye uygulanıyor — ama şema ve karar mekanizması hazır.
  2. **`legal_hold` — koşulsuz üstünlük.** Bugün YOK (§5.2: "legal_hold diye
     bir şey yok"). Kapı burada tanımlanıyor ve **her** karar noktasından
     geçiyor: tutulan bir nesne silinmez, yaslanmaz, çöpe atılmaz.
  3. **Kuru koşum (dry-run).** `trash.purge_expired` / `archive.purge_expired`
     kuru koşumu DESTEKLEMİYOR — çağrıldıklarında siliyorlar. Bu modülün
     varsayılanı `dry_run=True` ve kuru koşumda upstream fonksiyonlar
     ÇAĞRILMAZ (bkz. `UpstreamPurge`).

SAYILAR NEREDEN GELİYOR
-----------------------
Politika varsayılanları `tradehub_core/media/pipeline/policy/retention.schema.json`
dosyasından OKUNUR (`schema_defaults()`), burada tekrar yazılmaz. Şema
değerleri de mevcut koddaki sabitlerden alınmıştı (30/30/14/48). Böylece tek
kaynak vardır ve `tests/test_retention.py` şema ile kod arasındaki ayrışmayı
düşürür.

`derivative_retention.unused_after_days = 90` bir ÖLÇÜM DEĞİL, görev
tanımından gelen bir varsayılandır (şemada `x-provenance` ile işaretli).

GÜVENLİ TARAF (NFR-043)
-----------------------
"Kullanılıyor mu" sorusunun cevabı bilinmiyorsa nesne KORUNUR. `usage_lookup`
verilmediğinde her nesne `unknown` sayılır ve hiçbir türev silinmez. Ölçemediğin
şeyi "kullanılmıyor" saymak, `usage.py`'nin bilinen üç boşluğuyla
(`docs/standards/retention.md` §3.3) birleşince sitede kırık görsel demektir.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Tuple

from tradehub_core.media.pipeline.contracts.delivery import VARIANT_SEPARATOR
from tradehub_core.media.pipeline.contracts.errors import MediaEngineError, ObjectNotFound
from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PUBLIC,
	SCOPES,
	ObjectKey,
	ObjectRef,
	StorageAdapter,
)

# ── Şema varsayılanları: TEK KAYNAK ─────────────────────────────────────

SCHEMA_PATH: str = os.path.join(
	os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "policy", "retention.schema.json"
)

#: Şema dosyası okunamazsa kullanılacak ayna. Değerler
#: `retention.schema.json` ile aynı; test ikisini karşılaştırır ve ayrışırsa
#: DÜŞER. Ayna var çünkü paket dosyasız (zip/wheel) kurulduğunda modül
#: import edilemez hâle gelmemeli.
_MIRROR_DEFAULTS: Dict[str, Any] = {
	"original_retention": {"keep_forever": True, "local_days": None, "then": "delete"},
	"derivative_retention": {
		"unused_after_days": 90,
		"action": "notify_only",
		"regenerate_on_demand": True,
		"always_keep_profiles": [],
	},
	"legal_hold": {"enabled": False, "field": "th_legal_hold"},
	"soft_delete": {"trash_retention_days": 30, "archive_retention_days": 30},
	"backup": {"keep_sets": 14, "export_keep_hours": 48},
}


def schema_defaults() -> Dict[str, Any]:
	"""`retention.schema.json` içindeki `default` değerlerini düz sözlüğe çıkar.

	Yalnız iki düzey gezilir (üst nesne → alan); şemadaki daha derin
	nesneler (`unused_definition`, `scope_gates`) karar mantığında
	kullanılmıyor, dolayısıyla yüzeysel gezme yeterli ve niyetlidir.

	Dosya yoksa/bozuksa `_MIRROR_DEFAULTS` döner — modül import edilemez
	hâle gelmez.
	"""
	try:
		with open(SCHEMA_PATH, encoding="utf-8") as fh:
			sema = json.load(fh)
	except (OSError, ValueError):  # pragma: no cover - paket dosyasız kurulum
		return json.loads(json.dumps(_MIRROR_DEFAULTS))

	cikti: Dict[str, Any] = {}
	for ust_ad, ust in (sema.get("properties") or {}).items():
		if ust.get("type") != "object":
			continue
		alanlar: Dict[str, Any] = {}
		for ad, tanim in (ust.get("properties") or {}).items():
			if "default" in tanim:
				alanlar[ad] = tanim["default"]
			elif "const" in tanim:
				alanlar[ad] = tanim["const"]
		if alanlar:
			cikti[ust_ad] = alanlar
	return cikti


# ── Kararlar ────────────────────────────────────────────────────────────

ACTION_KEEP: str = "keep"
ACTION_DELETE: str = "delete"
ACTION_DEMOTE: str = "demote"
ACTION_NOTIFY: str = "notify_only"
ACTION_BLOCKED: str = "blocked"

POLICY_ORIGINAL: str = "original"
POLICY_DERIVATIVE: str = "derivative"

#: `then` / `action` alanlarındaki hedeflerin karar karşılığı.
_TARGET_TO_ACTION: Dict[str, str] = {
	"delete": ACTION_DELETE,
	"s3_cold": ACTION_DEMOTE,
	"s3_standard": ACTION_DEMOTE,
	"notify_only": ACTION_NOTIFY,
}

# Kullanım kararı etiketleri — KAYNAK `tradehub_core/media/usage.py`.
VERDICT_IN_USE: str = "in_use"
VERDICT_UNUSED: str = "unused"
VERDICT_HISTORY_ONLY: str = "history_only"
VERDICT_UNKNOWN: str = "unknown"

#: Silinebilir sayılan kararlar — `trash.TRASHABLE_VERDICTS` ile AYNI küme.
UNUSED_VERDICTS: Tuple[str, ...] = (VERDICT_UNUSED, VERDICT_HISTORY_ONLY)

REASON_LEGAL_HOLD: str = "legal_hold"
REASON_KEEP_FOREVER: str = "keep_forever"
REASON_TOO_YOUNG: str = "too_young"
REASON_IN_USE: str = "in_use"
REASON_USAGE_UNKNOWN: str = "usage_unknown"
REASON_ALWAYS_KEEP: str = "always_keep_profile"
REASON_NOT_FOUND: str = "not_found"
REASON_SCOPE_GATE: str = "scope_gate"
REASON_NO_COLD_TIER: str = "no_cold_tier"
REASON_REGENERATE_OFF: str = "regenerate_on_demand_false"


def is_derivative(key: ObjectKey) -> bool:
	"""Anahtar bir türev mi — `contracts/delivery.derivative_key` ile aynı ölçüt.

	Türev adı `<hash>__<profil>.<ext>` biçiminde; `__` içerik-hash'li adlarda
	(yalnız `[0-9a-f]`) hiç geçmez, dolayısıyla ayrım tersine çevrilebilir ve
	tahmine dayanmaz.
	"""
	return VARIANT_SEPARATOR in key.name


def profile_of(key: ObjectKey) -> str:
	"""Türevin profil adı (`w96`, `card_640`); türev değilse boş dizge."""
	if not is_derivative(key):
		return ""
	govde = os.path.splitext(key.name)[0]
	return govde.split(VARIANT_SEPARATOR, 1)[1]


@dataclass(frozen=True)
class RetentionDecision:
	"""Tek nesne için verilen karar. Uygulanmadan ÖNCE üretilir.

	Karar ile uygulama ayrı: `decide()` saf ve yan etkisizdir, `sweep()` onu
	uygular. Kuru koşumun anlamlı olabilmesinin tek yolu bu ayrım.
	"""

	ref: ObjectRef
	policy: str
	action: str
	reason: str = ""
	age_days: float = 0.0
	size_bytes: int = 0
	held: bool = False

	@property
	def destructive(self) -> bool:
		return self.action in (ACTION_DELETE, ACTION_DEMOTE)

	def to_dict(self) -> Dict[str, Any]:
		return {
			"url": self.ref.url,
			"policy": self.policy,
			"action": self.action,
			"reason": self.reason,
			"age_days": round(self.age_days, 2),
			"size_bytes": self.size_bytes,
			"held": self.held,
		}


@dataclass
class RetentionReport:
	"""Süpürme özeti. `dry_run` raporun İÇİNDE durur — sonradan sorulmaz."""

	scope: str
	dry_run: bool
	scanned: int = 0
	kept: int = 0
	deleted: int = 0
	demoted: int = 0
	notified: int = 0
	blocked: int = 0
	failed: int = 0
	bytes_freed: int = 0
	decisions: List[Dict[str, Any]] = field(default_factory=list)

	def to_dict(self) -> Dict[str, Any]:
		return {
			"scope": self.scope,
			"dry_run": self.dry_run,
			"scanned": self.scanned,
			"kept": self.kept,
			"deleted": self.deleted,
			"demoted": self.demoted,
			"notified": self.notified,
			"blocked": self.blocked,
			"failed": self.failed,
			"bytes_freed": self.bytes_freed,
			# İlk 50 satır — `trash.py:329` ve `tiered.SweepReport` ile aynı
			# sınır ve aynı gerekçe (denetim bağlamı 5 KB).
			"decisions": self.decisions[:50],
			"decisions_truncated": max(0, len(self.decisions) - 50),
		}


# ── Legal hold ──────────────────────────────────────────────────────────


class LegalHoldGate(Protocol):
	"""Yasal saklama kapısı. `True` → bu nesneye HİÇBİR politika dokunamaz."""

	def is_held(self, ref: ObjectRef) -> bool:
		...

	@property
	def enforceable(self) -> bool:
		"""Kapı gerçekten uygulanabiliyor mu (veri kaynağı var mı)."""
		...


class NoLegalHold:
	"""Hiçbir şey tutulmuyor. Bugünkü üretim gerçeği (§5.2: legal_hold YOK)."""

	def is_held(self, ref: ObjectRef) -> bool:
		return False

	@property
	def enforceable(self) -> bool:
		return True


class StaticLegalHold:
	"""Sabit URL kümesi — test ve tek seferlik operasyon için."""

	def __init__(self, urls: Iterable[str]) -> None:
		self._urls = {str(u).split("?")[0] for u in urls}

	def is_held(self, ref: ObjectRef) -> bool:
		return ref.url in self._urls

	def add(self, url: str) -> None:
		self._urls.add(str(url).split("?")[0])

	@property
	def enforceable(self) -> bool:
		return True


class FrappeLegalHold:
	"""`File.<field>` alanını okuyan üretim kapısı. `frappe` TEMBEL import.

	Alan henüz YOK (`docs/standards/retention.md` §5.2). Bu yüzden `probe()`
	alanın varlığını ölçer ve yoksa `enforceable=False` döner: kapı
	uygulanamıyorsa `RetentionSweeper` yıkıcı işlemleri REDDEDER. "Alan yok →
	kimse tutulmuyor" varsaymak, legal hold'un tek işini (silmeyi durdurmak)
	sessizce iptal ederdi.
	"""

	def __init__(self, field_name: str = "th_legal_hold") -> None:
		self._field = field_name
		self._enforceable: Optional[bool] = None
		self._cache: Dict[str, bool] = {}

	def probe(self) -> bool:
		"""Alan `File` üzerinde var mı — bir kez ölçülür, sonuç önbelleklenir."""
		if self._enforceable is not None:
			return self._enforceable
		try:
			import frappe  # noqa: PLC0415 - bilinçli tembel import

			sutunlar = {s.get("Field") or s.get("column_name") for s in frappe.db.sql("desc `tabFile`", as_dict=True)}
			self._enforceable = self._field in sutunlar
		except Exception:
			self._enforceable = False
		return bool(self._enforceable)

	def is_held(self, ref: ObjectRef) -> bool:
		if not self.probe():
			# Uygulanamaz kapı "tutulmuyor" cevabı vermemeli; çağıran zaten
			# `enforceable` üzerinden yıkıcı işlemi durduruyor. Yine de
			# muhafazakâr davranıp True dönmek, hiçbir şeyin silinememesi
			# demek olurdu — karar `RetentionSweeper`'da, tek yerde verilsin.
			return False
		if ref.url in self._cache:
			return self._cache[ref.url]
		try:
			import frappe  # noqa: PLC0415

			deger = frappe.db.get_value("File", {"file_url": ref.url}, self._field)
			sonuc = bool(deger)
		except Exception:
			# Ölçemedik → güvenli taraf: tutuluyor say, silme.
			sonuc = True
		self._cache[ref.url] = sonuc
		return sonuc

	@property
	def enforceable(self) -> bool:
		return self.probe()


# ── Politikalar ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OriginalRetention:
	"""Orijinal varlık politikası — VARSAYILAN SÜRESİZ.

	`keep_forever=False` yapmak bilinçli bir veri kaybı kararıdır; şema bunu
	`local_days` + `then` zorunluluğuyla bağlıyor, burada da aynı doğrulama
	`validate()` içinde yapılır.
	"""

	keep_forever: bool = True
	local_days: Optional[int] = None
	then: str = "delete"

	@classmethod
	def from_mapping(cls, conf: Mapping[str, Any]) -> "OriginalRetention":
		gunler = conf.get("local_days")
		return cls(
			keep_forever=bool(conf.get("keep_forever", True)),
			local_days=None if gunler in (None, "") else int(gunler),
			then=str(conf.get("then", "delete") or "delete"),
		)

	def validate(self) -> List[str]:
		hatalar: List[str] = []
		if not self.keep_forever:
			if self.local_days is None or self.local_days < 1:
				hatalar.append("keep_forever=false iken local_days >= 1 zorunlu")
			if self.then not in _TARGET_TO_ACTION:
				hatalar.append(f"bilinmeyen `then` hedefi: {self.then!r}")
		return hatalar

	def decide(self, age_days: float) -> Tuple[str, str]:
		"""(eylem, sebep). Saf: yalnız yaşa bakar."""
		if self.keep_forever:
			return ACTION_KEEP, REASON_KEEP_FOREVER
		if self.local_days is None or age_days < self.local_days:
			return ACTION_KEEP, REASON_TOO_YOUNG
		return _TARGET_TO_ACTION.get(self.then, ACTION_KEEP), self.then


@dataclass(frozen=True)
class DerivativeRetention:
	"""Türev varlık politikası — `original_retention`'dan BAĞIMSIZ.

	İki politikanın bağımsızlığı testle sabitlenir: orijinali süresiz tutup
	türevi 90 günde silmek ya da tersi, birbirini etkilemeden mümkün olmalı.
	"""

	unused_after_days: int = 90
	action: str = "notify_only"
	regenerate_on_demand: bool = True
	always_keep_profiles: Tuple[str, ...] = ()

	@classmethod
	def from_mapping(cls, conf: Mapping[str, Any]) -> "DerivativeRetention":
		return cls(
			unused_after_days=int(conf.get("unused_after_days", 90) or 90),
			action=str(conf.get("action", "notify_only") or "notify_only"),
			regenerate_on_demand=bool(conf.get("regenerate_on_demand", True)),
			always_keep_profiles=tuple(conf.get("always_keep_profiles") or ()),
		)

	def validate(self) -> List[str]:
		hatalar: List[str] = []
		if self.action not in _TARGET_TO_ACTION:
			hatalar.append(f"bilinmeyen `action`: {self.action!r}")
		if self.unused_after_days < 0:
			hatalar.append("unused_after_days negatif olamaz")
		return hatalar

	def warnings(self) -> List[str]:
		"""Şemadaki `x-requires-review` durumu: silme + yeniden üretilemezlik."""
		if self.action == "delete" and not self.regenerate_on_demand:
			return [
				"action=delete + regenerate_on_demand=false → türev silmek VERİ KAYBIDIR "
				"(retention.schema.json x-requires-review)"
			]
		return []

	def decide(self, age_days: float, verdict: str, profile: str) -> Tuple[str, str]:
		"""(eylem, sebep). Kullanım kararı bilinmiyorsa KORUR."""
		if profile and profile in self.always_keep_profiles:
			return ACTION_KEEP, REASON_ALWAYS_KEEP
		if verdict == VERDICT_IN_USE:
			return ACTION_KEEP, REASON_IN_USE
		if verdict not in UNUSED_VERDICTS:
			return ACTION_KEEP, REASON_USAGE_UNKNOWN
		if age_days < self.unused_after_days:
			return ACTION_KEEP, REASON_TOO_YOUNG
		if self.action == "delete" and not self.regenerate_on_demand:
			return ACTION_NOTIFY, REASON_REGENERATE_OFF
		return _TARGET_TO_ACTION.get(self.action, ACTION_KEEP), self.action


@dataclass(frozen=True)
class RetentionPolicy:
	"""İki bağımsız politika + legal hold ayarı + soft-delete pencereleri."""

	original: OriginalRetention = field(default_factory=OriginalRetention)
	derivative: DerivativeRetention = field(default_factory=DerivativeRetention)
	legal_hold_enabled: bool = False
	legal_hold_field: str = "th_legal_hold"
	trash_retention_days: int = 30
	archive_retention_days: int = 30
	backup_keep_sets: int = 14
	policy_version: str = "1.0.0"

	@classmethod
	def defaults(cls) -> "RetentionPolicy":
		"""Şema varsayılanlarından politika üret — sayı burada yazılmaz."""
		return cls.from_mapping(schema_defaults())

	@classmethod
	def from_mapping(cls, conf: Mapping[str, Any]) -> "RetentionPolicy":
		varsayilan = schema_defaults()

		def _blok(ad: str) -> Dict[str, Any]:
			temel = dict(varsayilan.get(ad) or {})
			temel.update(dict(conf.get(ad) or {}))
			return temel

		orijinal = _blok("original_retention")
		turev = _blok("derivative_retention")
		hold = _blok("legal_hold")
		soft = _blok("soft_delete")
		yedek = _blok("backup")
		return cls(
			original=OriginalRetention.from_mapping(orijinal),
			derivative=DerivativeRetention.from_mapping(turev),
			legal_hold_enabled=bool(hold.get("enabled", False)),
			legal_hold_field=str(hold.get("field", "th_legal_hold") or "th_legal_hold"),
			trash_retention_days=int(soft.get("trash_retention_days", 30) or 30),
			archive_retention_days=int(soft.get("archive_retention_days", 30) or 30),
			backup_keep_sets=int(yedek.get("keep_sets", 14) or 14),
			policy_version=str(conf.get("policy_version", "1.0.0") or "1.0.0"),
		)

	def validate(self) -> List[str]:
		"""Politika iç tutarlılığı. Boş liste = geçerli."""
		return self.original.validate() + self.derivative.validate()

	def warnings(self) -> List[str]:
		return self.derivative.warnings()

	def to_dict(self) -> Dict[str, Any]:
		return {
			"policy_version": self.policy_version,
			"original_retention": {
				"keep_forever": self.original.keep_forever,
				"local_days": self.original.local_days,
				"then": self.original.then,
			},
			"derivative_retention": {
				"unused_after_days": self.derivative.unused_after_days,
				"action": self.derivative.action,
				"regenerate_on_demand": self.derivative.regenerate_on_demand,
				"always_keep_profiles": list(self.derivative.always_keep_profiles),
			},
			"legal_hold": {"enabled": self.legal_hold_enabled, "field": self.legal_hold_field},
			"soft_delete": {
				"trash_retention_days": self.trash_retention_days,
				"archive_retention_days": self.archive_retention_days,
			},
			"backup": {"keep_sets": self.backup_keep_sets},
		}


class PolicyInvalid(MediaEngineError):
	"""Politika kendi içinde tutarsız — süpürücü kurulamaz."""

	varsayilan_retryable = False


# ── Süpürücü ────────────────────────────────────────────────────────────


class RetentionSweeper:
	"""Politikayı bir depoya uygular. **Varsayılan kuru koşum.**

	Args:
	    storage: Üzerinde çalışılacak depo (`StorageAdapter`).
	    policy: Saklama politikası. Geçersizse `PolicyInvalid`.
	    legal_hold: Yasal saklama kapısı. `None` ise politika `legal_hold_
	        enabled=True` diyorsa kurulum REDDEDİLİR — "açık ama kapısız"
	        bir legal hold, olmayandan daha tehlikelidir (açık sanılır).
	    usage_lookup: `ObjectRef` → kullanım kararı (`in_use` / `unused` /
	        `history_only`). `None` ise her nesne `unknown` sayılır ve hiçbir
	        türev silinmez (güvenli taraf).
	    cold: Yaslandırma hedefi (`TieredStorage` benzeri, `demote(ref)`
	        metodu olan nesne). Yoksa `demote` kararları `notify` olur ve
	        sebebi raporlanır.
	    clock: Zaman kaynağı; testte enjekte edilir.
	"""

	def __init__(
		self,
		storage: StorageAdapter,
		policy: Optional[RetentionPolicy] = None,
		*,
		legal_hold: Optional[LegalHoldGate] = None,
		usage_lookup: Optional[Callable[[ObjectRef], str]] = None,
		cold: Optional[Any] = None,
		clock: Optional[Callable[[], float]] = None,
	) -> None:
		self._storage = storage
		self._policy = policy if policy is not None else RetentionPolicy.defaults()
		hatalar = self._policy.validate()
		if hatalar:
			raise PolicyInvalid("Saklama politikası geçersiz", detay={"errors": hatalar})
		if self._policy.legal_hold_enabled and legal_hold is None:
			raise PolicyInvalid(
				"legal_hold açık ama kapı (LegalHoldGate) verilmedi.",
				detay={"field": self._policy.legal_hold_field},
			)
		self._hold: LegalHoldGate = legal_hold if legal_hold is not None else NoLegalHold()
		self._usage = usage_lookup
		self._cold = cold
		self._clock = clock if clock is not None else time.time

	# ── karar ──────────────────────────────────────────────────────────

	@property
	def policy(self) -> RetentionPolicy:
		return self._policy

	def verdict_for(self, ref: ObjectRef) -> str:
		"""Kullanım kararı; ölçüm yoksa `unknown`."""
		if self._usage is None:
			return VERDICT_UNKNOWN
		try:
			return str(self._usage(ref) or VERDICT_UNKNOWN)
		except Exception:
			# Kullanım sorgusu patladı → ölçemedik → koru.
			return VERDICT_UNKNOWN

	def decide(self, ref: ObjectRef, *, now: Optional[float] = None) -> RetentionDecision:
		"""Tek nesne için karar üret. SAF: hiçbir şeye dokunmaz.

		Sıra kritik: **legal hold her şeyden önce gelir.** Yaş, kullanım ve
		politika ancak kapı açıksa hesaplanır.
		"""
		turev = is_derivative(ref.key)
		politika_adi = POLICY_DERIVATIVE if turev else POLICY_ORIGINAL

		if self._policy.legal_hold_enabled and self._hold.is_held(ref):
			return RetentionDecision(
				ref, politika_adi, ACTION_BLOCKED, REASON_LEGAL_HOLD, held=True
			)

		try:
			kunye = self._storage.stat(ref)
		except ObjectNotFound:
			return RetentionDecision(ref, politika_adi, ACTION_KEEP, REASON_NOT_FOUND)

		simdi = float(self._clock() if now is None else now)
		yas_gun = max(0.0, (simdi - float(kunye.modified_at)) / 86400.0)

		if turev:
			eylem, sebep = self._policy.derivative.decide(
				yas_gun, self.verdict_for(ref), profile_of(ref.key)
			)
		else:
			eylem, sebep = self._policy.original.decide(yas_gun)

		if eylem == ACTION_DEMOTE and self._cold is None:
			eylem, sebep = ACTION_NOTIFY, REASON_NO_COLD_TIER

		return RetentionDecision(
			ref,
			politika_adi,
			eylem,
			sebep,
			age_days=yas_gun,
			size_bytes=kunye.size_bytes,
		)

	# ── uygulama ───────────────────────────────────────────────────────

	def apply(self, decision: RetentionDecision, *, dry_run: bool = True) -> bool:
		"""Kararı uygula. `dry_run=True` iken HİÇBİR ŞEY yapmaz.

		Returns:
		    Uygulandı mı. Kuru koşumda her zaman `False`.
		"""
		if dry_run or not decision.destructive:
			return False
		if self._policy.legal_hold_enabled and not self._hold.enforceable:
			# Kapı açık ama uygulanamıyor (alan yok, sorgu çalışmıyor):
			# yıkıcı işlem YAPILMAZ.
			return False
		if decision.action == ACTION_DELETE:
			return bool(self._storage.delete(decision.ref))
		if decision.action == ACTION_DEMOTE and self._cold is not None:
			sonuc = self._cold.demote(decision.ref)
			return bool(getattr(sonuc, "moved", False))
		return False

	def sweep(
		self,
		*,
		scope: str = SCOPE_PUBLIC,
		dry_run: bool = True,
		limit: int = 0,
		now: Optional[float] = None,
	) -> RetentionReport:
		"""Kapsamı gez, karar ver, (kuru değilse) uygula.

		**Varsayılan `dry_run=True`** — `tiered.sweep()` ile aynı gerekçe:
		yanlış yapılandırılmış tek bir alan (ör. `keep_forever=false` +
		`local_days=1`) tüm depoyu tek turda silebilir. Varsayılan olarak
		silen bir API, ilk yanlış çağrıda geri alınamaz sonuç doğurur.
		"""
		if scope not in SCOPES:
			raise ValueError(f"Bilinmeyen kapsam: {scope!r}")
		rapor = RetentionReport(scope=scope, dry_run=dry_run)

		# Legal hold açık ve kapı uygulanamıyorsa: gez, karar ver, ama
		# HİÇBİR ŞEY uygulama. Rapor bunu `blocked` olarak gösterir.
		kapi_saglam = (not self._policy.legal_hold_enabled) or self._hold.enforceable

		for key in self._storage.iter_keys(scope=scope):
			rapor.scanned += 1
			ref = ObjectRef(key=key, scope=scope)
			karar = self.decide(ref, now=now)
			rapor.decisions.append(karar.to_dict())

			if karar.action == ACTION_BLOCKED:
				rapor.blocked += 1
			elif karar.action == ACTION_KEEP:
				rapor.kept += 1
			elif karar.action == ACTION_NOTIFY:
				rapor.notified += 1
			elif not kapi_saglam:
				rapor.blocked += 1
			elif dry_run:
				# Kuru koşumda kazanç ÖLÇÜLÜR, uygulanmaz.
				rapor.bytes_freed += karar.size_bytes
			else:
				try:
					uygulandi = self.apply(karar, dry_run=False)
				except MediaEngineError:
					rapor.failed += 1
					continue
				if not uygulandi:
					rapor.failed += 1
					continue
				if karar.action == ACTION_DELETE:
					rapor.deleted += 1
				else:
					rapor.demoted += 1
				rapor.bytes_freed += karar.size_bytes

			if limit and rapor.scanned >= limit:
				break
		return rapor

	def sweep_all(self, **kwargs: Any) -> List[RetentionReport]:
		return [self.sweep(scope=s, **kwargs) for s in SCOPES]


# ── Mevcut motorun saklama işlerini SARAN katman ────────────────────────


class UpstreamPurge:
	"""`trash` / `archive` / `backup` purge'lerinin kuru-koşum + legal-hold zarfı.

	Neden zarf, neden yeniden yazım DEĞİL: bu üç fonksiyon üretimde çalışıyor,
	denetim kaydı yazıyor, referans zincirini temizliyor. Kopyalamak iki farklı
	silme yolu demekti.

	Zarfın eklediği iki kapı:

	  1. **Kuru koşum.** Upstream `dry_run` DESTEKLEMİYOR (`trash.purge_expired`
	     çağrıldığında siler). Bu yüzden kuru koşumda fonksiyon HİÇ çağrılmaz;
	     dönen sözlük `called=False` + `supported=False` taşır. "Kuru koşumda
	     ne silinecekti" sorusunun cevabı bu katmandan ÖLÇÜLEMEZ — cevabı
	     bilmek `frappe` + disk taraması ister ve o `RetentionSweeper`'ın işi.
	  2. **Legal hold.** `trash.purge_expired` diskte mtime'a bakar, hiçbir
	     `File` alanını OKUMAZ (`retention.md` §6.3). Yani legal hold açıkken
	     onu çağırmak, tutulan bir dosyayı silebilir. Bu durumda zarf çağrıyı
	     REDDEDER; `allow_unenforced=True` ile bilinçli olarak aşılabilir ve
	     o zaman sonuç `unenforced_legal_hold=True` ile işaretlenir.
	"""

	def __init__(self, policy: Optional[RetentionPolicy] = None) -> None:
		self._policy = policy if policy is not None else RetentionPolicy.defaults()

	@property
	def policy(self) -> RetentionPolicy:
		return self._policy

	def _gate(self, ad: str, dry_run: bool, allow_unenforced: bool) -> Optional[Dict[str, Any]]:
		"""Çağrıyı engelleyen bir sebep varsa hazır sonuç sözlüğü döndür."""
		if dry_run:
			return {
				"target": ad,
				"called": False,
				"dry_run": True,
				"supported": False,
				"note": "upstream fonksiyon dry-run desteklemiyor; çağrılmadı",
			}
		if self._policy.legal_hold_enabled and not allow_unenforced:
			return {
				"target": ad,
				"called": False,
				"dry_run": False,
				"blocked_by": REASON_LEGAL_HOLD,
				"note": (
					"legal_hold açık; upstream purge `File` alanlarını okumadığı için "
					"tutulan dosyayı silebilir. allow_unenforced=True ile bilinçli aşın."
				),
			}
		return None

	def purge_trash(
		self, *, dry_run: bool = True, retention_days: Optional[int] = None, allow_unenforced: bool = False
	) -> Dict[str, Any]:
		"""`tradehub_core.media.trash.purge_expired` zarfı."""
		engel = self._gate("trash.purge_expired", dry_run, allow_unenforced)
		if engel is not None:
			return engel
		from tradehub_core.media import trash  # noqa: PLC0415 - frappe gerektirir

		gun = self._policy.trash_retention_days if retention_days is None else int(retention_days)
		sonuc = dict(trash.purge_expired(retention_days=gun, trigger="retention_policy"))
		sonuc.update({"target": "trash.purge_expired", "called": True, "dry_run": False,
			"retention_days": gun, "unenforced_legal_hold": self._policy.legal_hold_enabled})
		return sonuc

	def purge_archive(
		self, *, dry_run: bool = True, retention_days: Optional[int] = None, allow_unenforced: bool = False
	) -> Dict[str, Any]:
		"""`tradehub_core.media.archive.purge_expired` zarfı."""
		engel = self._gate("archive.purge_expired", dry_run, allow_unenforced)
		if engel is not None:
			return engel
		from tradehub_core.media import archive  # noqa: PLC0415

		gun = self._policy.archive_retention_days if retention_days is None else int(retention_days)
		sonuc = dict(archive.purge_expired(retention_days=gun, trigger="retention_policy"))
		sonuc.update({"target": "archive.purge_expired", "called": True, "dry_run": False,
			"retention_days": gun, "unenforced_legal_hold": self._policy.legal_hold_enabled})
		return sonuc

	def prune_backups(
		self, *, dry_run: bool = True, keep: Optional[int] = None, allow_unenforced: bool = False
	) -> Dict[str, Any]:
		"""`tradehub_core.media.backup.prune` zarfı — 14 set (KEEP_SETS)."""
		engel = self._gate("backup.prune", dry_run, allow_unenforced)
		if engel is not None:
			return engel
		from tradehub_core.media import backup  # noqa: PLC0415

		sayi = self._policy.backup_keep_sets if keep is None else int(keep)
		sonuc = dict(backup.prune(keep=sayi))
		sonuc.update({"target": "backup.prune", "called": True, "dry_run": False, "keep": sayi})
		return sonuc

	def run_all(self, *, dry_run: bool = True, allow_unenforced: bool = False) -> List[Dict[str, Any]]:
		"""Üç purge'ü sırayla — `hooks.py` günlük bloğunun karşılığı.

		Sıra `hooks.py:127+` ile AYNI: arşiv → çöp → yedek. Yedek en sonda
		çünkü `backup.run_scheduled` içindeki karar (`retention.md` §4.4)
		yedek başarısızsa purge'ü atlamak yönünde; ters sırada silinen dosya
		hiçbir yedeğe girmemiş olurdu.
		"""
		return [
			self.purge_archive(dry_run=dry_run, allow_unenforced=allow_unenforced),
			self.purge_trash(dry_run=dry_run, allow_unenforced=allow_unenforced),
			self.prune_backups(dry_run=dry_run, allow_unenforced=allow_unenforced),
		]


__all__ = [
	"SCHEMA_PATH",
	"schema_defaults",
	"ACTION_KEEP",
	"ACTION_DELETE",
	"ACTION_DEMOTE",
	"ACTION_NOTIFY",
	"ACTION_BLOCKED",
	"POLICY_ORIGINAL",
	"POLICY_DERIVATIVE",
	"VERDICT_IN_USE",
	"VERDICT_UNUSED",
	"VERDICT_HISTORY_ONLY",
	"VERDICT_UNKNOWN",
	"UNUSED_VERDICTS",
	"REASON_LEGAL_HOLD",
	"REASON_KEEP_FOREVER",
	"REASON_TOO_YOUNG",
	"REASON_IN_USE",
	"REASON_USAGE_UNKNOWN",
	"REASON_ALWAYS_KEEP",
	"REASON_NOT_FOUND",
	"REASON_NO_COLD_TIER",
	"REASON_REGENERATE_OFF",
	"is_derivative",
	"profile_of",
	"RetentionDecision",
	"RetentionReport",
	"LegalHoldGate",
	"NoLegalHold",
	"StaticLegalHold",
	"FrappeLegalHold",
	"OriginalRetention",
	"DerivativeRetention",
	"RetentionPolicy",
	"PolicyInvalid",
	"RetentionSweeper",
	"UpstreamPurge",
]
