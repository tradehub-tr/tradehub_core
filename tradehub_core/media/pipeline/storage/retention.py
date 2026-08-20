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


# ── Frappe tarafı: çöp toplama (GC) işleri ──────────────────────────────
#
# Yukarısı frappe'siz çalışır ve `StorageAdapter` üzerinde gezer. Aşağısı
# ÜRETİM envanterine bakar: `File`, `Media Asset`, `Media Rendition`. İkisi
# ayrı tutuldu çünkü üretimdeki adların çoğu içerik-adresli DEĞİL
# (ölçüm 2026-08-19: `/files/ChatGPT Image 26 Haz 2026 09_34_02.png` gibi
# shard'sız 4.393 public dosya var) ve `ObjectKey` bunları temsil edemiyor.
# `RetentionPolicy` / `OriginalRetention` / `DerivativeRetention` karar
# mantığı burada AYNEN kullanılır; kopyalanmaz.

MEDIA_ASSET: str = "Media Asset"
MEDIA_RENDITION: str = "Media Rendition"

#: Legal hold'un GERÇEK yeri. `retention.md` §5.2 "legal_hold diye bir şey yok"
#: diyordu; o gün `File.th_legal_hold` önerilmişti. Bugün ölçüldü
#: (2026-08-19, istoc.localhost): `File` üzerinde `th_legal_hold` YOK,
#: `Media Asset` üzerinde `legal_hold` VAR (Check, permlevel 1 — satıcı
#: yazamaz). Kapı bu yüzden `File`'a değil `Media Asset`'e bakar.
LEGAL_HOLD_DOCFIELD: str = "legal_hold"

REASON_BLIND_SPOT: str = "usage_blind_spot"
REASON_MISSING_ON_DISK: str = "missing_on_disk"
REASON_NOT_A_FILE_URL: str = "not_a_file_url"
REASON_GATE_UNENFORCEABLE: str = "legal_hold_unenforceable"
REASON_NO_REGENERATION: str = "regeneration_path_unavailable"

#: `usage.LIVE_SOURCES` KAPSAMAYAN ama diskte dosya adresi TAŞIYAN alanlar.
#:
#: Ölçüm (2026-08-19, istoc.localhost, `information_schema` taraması):
#: '/files/' geçen 42 (tablo, kolon) çifti var; bunların 25'i `usage.py`'nin
#: üç kaynak listesinin HİÇBİRİNDE yok. En kritiği `tabBrand.logo` — T-029
#: raporunun işaret ettiği tuzak: marka logoları `usage.verdicts_for` gözünde
#: "unused" görünür ve saf bir GC onları siler.
#:
#: Bu liste `usage.py`'yi DÜZELTMEZ (o dosya bu görevin kapsamı dışı). Yaptığı
#: tek şey: burada geçen bir adres için kullanım kararı ne olursa olsun
#: `REASON_BLIND_SPOT` ile KORUMAYA çevirmek. Yanlış yön bilinçli seçildi —
#: fazla korumak boş disk, eksik korumak kırık site demek.
BLIND_SPOT_SOURCES: Tuple[Tuple[str, str], ...] = (
	("tabBrand", "logo"),
	("tabBrand", "hero_banner"),
	("tabBrand", "og_image"),
	("tabBrand", "video_url"),
	("tabProduct Category", "image"),
	("tabSeller Category", "image"),
	("tabAdmin Seller Profile", "banner_image"),
	("tabSeller Gallery Image", "poster_image"),
	("tabSeller Gallery Image", "video_url"),
	("tabSeller Certification", "document"),
	("tabSeller Verification", "document"),
	("tabSeller Application", "identity_document"),
	("tabBuyer Favorite Item", "snapshot_image"),
	("tabOrder Item", "image"),
	("tabPayment Transaction", "receipt_url"),
	("tabStatic Page SEO", "og_image"),
	("tabVerification Source", "icon"),
)

#: `usage.py` tarafından "kullanılmıyor" denilse bile ASLA aday olmayacak
#: doctype'lar — belge saklama yükümlülüğü olanlar. KYC/KYB alanları bu
#: görevin dokunma yasağı listesinde; buraya YALNIZ okunmak üzere, koruma
#: yönünde giriyorlar (silinmesinler diye).
PROTECTED_SOURCES: Tuple[Tuple[str, str], ...] = (
	("tabKYB Verification", "bank_account_document"),
	("tabKYB Verification", "faaliyet_belgesi"),
	("tabKYB Verification", "identity_document"),
	("tabKYB Verification", "imza_sirkuleri"),
	("tabKYB Verification", "ticaret_sicil_gazetesi"),
	("tabKYB Verification", "vergi_levhasi"),
	("tabKYC Verification", "identity_document"),
)

#: Aday listesinde rapor edilecek örnek sayısı — `trash.py:329` ve
#: `RetentionReport` ile AYNI sınır (denetim bağlamı 5 KB).
SAMPLE_LIMIT: int = 50


def _frappe() -> Any:
	"""`frappe`'yi tembel import et. Modül frappe'siz de import edilebilmeli."""
	import frappe  # noqa: PLC0415 - bilinçli tembel import

	return frappe


def _column_exists(table: str, column: str) -> bool:
	"""Tabloda kolon var mı. Yoksa/ölçülemezse `False` — sessiz varsayım yok."""
	try:
		frappe = _frappe()
		satirlar = frappe.db.sql(f"desc `{table}`", as_dict=True)
	except Exception:
		return False
	return column in {s.get("Field") or s.get("column_name") for s in satirlar}


def _referenced_urls(sources: Iterable[Tuple[str, str]]) -> set:
	"""Verilen (tablo, kolon) çiftlerinde geçen TÜM dosya adresleri.

	`usage._referenced_urls` ile aynı desen ve aynı gerekçe: alan başına tek
	`locate` sorgusu, sonra `usage.extract_file_urls` ile ayrıştırma. LIKE
	değil LOCATE, çünkü LIKE utf8mb4'te 4 baytlık karakterli satırlarda
	eşleşmiyor (`usage.py` notu).

	Olmayan tablo/kolon sessizce ATLANIR: bu liste ölçümle yazıldı ama şema
	değişebilir ve eksik bir kaynak yüzünden GC'nin çökmesi, korumanın
	tamamen kalkmasından daha kötü bir başarısızlık biçimi olurdu.
	"""
	from tradehub_core.media.usage import extract_file_urls  # noqa: PLC0415

	frappe = _frappe()
	bulunan: set = set()
	for tablo, kolon in sources:
		try:
			satirlar = frappe.db.sql(
				f"select `{kolon}` from `{tablo}` where locate('/files/', `{kolon}`) > 0"
			)
		except Exception:
			continue
		for (deger,) in satirlar:
			bulunan |= extract_file_urls(deger)
	return bulunan


def blind_spot_urls() -> set:
	"""`usage.py`'nin göremediği + korunması zorunlu kaynaklarda geçen adresler."""
	return _referenced_urls(BLIND_SPOT_SOURCES) | _referenced_urls(PROTECTED_SOURCES)


def live_usage_urls() -> Tuple[set, bool]:
	"""Canlı ya da sipariş kaydında GEÇEN tüm adresler + **ölçüm başarılı mı**.

	Dönüşün ikinci elemanı olmadan bu fonksiyon tehlikeli olurdu: tarama
	patladığında boş küme dönmek "hiçbir dosya kullanılmıyor" demekle aynı
	şey ve çağıran onu silme izni sanır. İkinci eleman `False` geldiğinde
	`_original_candidate` her satırı `keep / usage_unknown` yapar.

	**`usage.verdict_map_all` BİLEREK kullanılmıyor** — ilk gerçekleme onu
	kullanıyordu ve test canlı envanterde kırmızı verdi (ölçüm 2026-08-19:
	`tabListing.primary_image` adresi koruma kümesinde ÇIKMADI). Sebep:
	`verdict_map_all` yalnız kendi ADAY kümesine karar üretiyor ve o küme
	`is_private=0`, `left(file_url,7)='/files/'` ile daraltılmış, ayrıca
	hassas doctype'larla aynı `content_hash`'i taşıyanlar da çıkarılmış.
	Karar haritasında OLMAYAN bir adres "kullanılmıyor" ile aynı sonucu
	veriyordu — yani tam olarak korunması gereken private dosyalar korumasız
	kalıyordu.

	Burada kaynak alanların HAM taraması yapılıyor (`_referenced_urls`,
	alan başına tek `locate` sorgusu): aday kümesi süzgeci yok, `tabFile`
	kaydı olup olmaması önemli değil, adres bir yerde geçiyorsa korunuyor.
	Geçmiş kaynakları (`HISTORY_SOURCES`) taranmıyor — `history_only` zaten
	silinebilir sayılan bir karar, korumaya girmemesi gereken tek grup o.
	"""
	from tradehub_core.media.usage import LIVE_SOURCES, ORDER_SOURCES  # noqa: PLC0415

	ciftler = [(t, c) for t, c, _k, _l in LIVE_SOURCES + ORDER_SOURCES]
	try:
		return _referenced_urls(ciftler), True
	except Exception:
		frappe = _frappe()
		frappe.log_error(
			title="retention: live usage scan failed",
			message=frappe.get_traceback(with_context=True),
		)
		return set(), False


class MediaAssetLegalHold:
	"""`Media Asset.legal_hold` alanını okuyan üretim kapısı.

	`FrappeLegalHold` `File.<field>` okur ve o alan üretimde YOK (ölçüldü);
	bu sınıf gerçek alana bakar. İki yoldan URL'ye çevirir:

	    Media Asset.source_file  → File.file_url      (orijinal)
	    Media Rendition.asset    → Rendition.file_url (türev)

	Yani bir varlık tutulduğunda ONUN TÜREVLERİ DE tutulur. Ters durum
	(türev tutulu, orijinal serbest) mümkün değil — hold varlık düzeyinde.

	`enforceable` yalnız doctype + kolon gerçekten varsa `True`. Kapı
	uygulanamıyorsa çağıran yıkıcı işlemi REDDEDER; "alan yok → kimse tutulu
	değil" varsaymak legal hold'un tek işini sessizce iptal ederdi.
	"""

	def __init__(self) -> None:
		self._enforceable: Optional[bool] = None
		self._held: Optional[set] = None

	def probe(self) -> bool:
		if self._enforceable is None:
			self._enforceable = _column_exists(f"tab{MEDIA_ASSET}", LEGAL_HOLD_DOCFIELD)
		return bool(self._enforceable)

	@property
	def enforceable(self) -> bool:
		return self.probe()

	def held_asset_names(self) -> List[str]:
		if not self.probe():
			return []
		frappe = _frappe()
		return frappe.get_all(MEDIA_ASSET, filters={LEGAL_HOLD_DOCFIELD: 1}, pluck="name")

	def held_urls(self) -> set:
		"""Tutulan varlıkların TÜM adresleri — tek toplu yükleme, N+1 yok."""
		if self._held is not None:
			return self._held
		if not self.probe():
			self._held = set()
			return self._held
		self._held = self._load_held_urls()
		return self._held

	def _load_held_urls(self) -> set:
		frappe = _frappe()
		adlar = self.held_asset_names()
		if not adlar:
			return set()
		dosyalar = frappe.get_all(
			MEDIA_ASSET, filters={"name": ["in", adlar]}, fields=["source_file"], pluck="source_file"
		)
		dosyalar = [d for d in dosyalar if d]
		adresler: set = set()
		if dosyalar:
			adresler |= {
				u
				for u in frappe.get_all(
					"File", filters={"name": ["in", dosyalar]}, pluck="file_url"
				)
				if u
			}
		if frappe.db.exists("DocType", MEDIA_RENDITION):
			adresler |= {
				u
				for u in frappe.get_all(
					MEDIA_RENDITION, filters={"asset": ["in", adlar]}, pluck="file_url"
				)
				if u
			}
		return adresler

	def is_held_url(self, url: str) -> bool:
		return str(url or "").split("?")[0] in self.held_urls()

	def is_held(self, ref: ObjectRef) -> bool:
		"""`LegalHoldGate` uyumu — `RetentionSweeper` bu imzayı çağırır."""
		return self.is_held_url(ref.url)

	def invalidate(self) -> None:
		"""Önbelleği düşür. Test legal_hold'u değiştirdiğinde gerekir."""
		self._held = None
		self._enforceable = None


# ── Envanter satırı ────────────────────────────────────────────────────


@dataclass(frozen=True)
class GcCandidate:
	"""Tek envanter satırı için karar. `RetentionDecision` ile aynı rol.

	Ayrı sınıf çünkü üretimdeki adresler `ObjectKey` sözleşmesine (shard +
	32 hex) uymuyor; `RetentionDecision` bir `ObjectRef` istiyor ve onu
	uyduramayız.
	"""

	url: str
	policy: str
	action: str
	reason: str
	age_days: float = 0.0
	size_bytes: int = 0
	held: bool = False
	extra: Dict[str, Any] = field(default_factory=dict)

	@property
	def destructive(self) -> bool:
		return self.action in (ACTION_DELETE, ACTION_DEMOTE)

	def to_dict(self) -> Dict[str, Any]:
		cikti = {
			"url": self.url,
			"policy": self.policy,
			"action": self.action,
			"reason": self.reason,
			"age_days": round(self.age_days, 2),
			"size_bytes": self.size_bytes,
			"held": self.held,
		}
		cikti.update(self.extra)
		return cikti


@dataclass
class GcSection:
	"""Bir politikanın (orijinal / türev) bakım özeti.

	`skips` sebep→sayı haritasıdır: "kaç dosya atlandı" yetmez, "NİYE
	atlandı" bakım raporunun asıl bilgisidir (görev şartı 5).
	"""

	name: str
	scanned: int = 0
	kept: int = 0
	candidates: int = 0
	deleted: int = 0
	demoted: int = 0
	notified: int = 0
	blocked: int = 0
	failed: int = 0
	bytes_candidate: int = 0
	bytes_freed: int = 0
	skips: Dict[str, int] = field(default_factory=dict)
	samples: List[Dict[str, Any]] = field(default_factory=list)

	def note(self, reason: str) -> None:
		self.skips[reason] = self.skips.get(reason, 0) + 1

	def to_dict(self) -> Dict[str, Any]:
		return {
			"policy": self.name,
			"scanned": self.scanned,
			"kept": self.kept,
			"candidates": self.candidates,
			"deleted": self.deleted,
			"demoted": self.demoted,
			"notified": self.notified,
			"blocked": self.blocked,
			"failed": self.failed,
			"bytes_candidate": self.bytes_candidate,
			"bytes_freed": self.bytes_freed,
			"skipped_by_reason": dict(sorted(self.skips.items())),
			"samples": self.samples[:SAMPLE_LIMIT],
			"samples_truncated": max(0, len(self.samples) - SAMPLE_LIMIT),
		}


# ── Disk çözümleme ─────────────────────────────────────────────────────


def disk_path_for(file_url: str) -> Optional[str]:
	"""`file_url` → mutlak disk yolu. Adres tanınmıyorsa `None`.

	Yol geçişi burada da reddedilir: `trash._relative` ile AYNI ölçüt
	(segment bazlı `..`). Düz altdizge araması meşru dosya adlarını da
	reddediyordu (bkz. `tests/test_media_trash_path.py`), bu yüzden aynı
	hatayı burada tekrarlamıyoruz.
	"""
	temiz = str(file_url or "").split("?")[0]
	if not temiz:
		return None
	frappe = _frappe()
	if temiz.startswith("/files/"):
		kok, rel = os.path.join(frappe.get_site_path(), "public", "files"), temiz[len("/files/") :]
	elif temiz.startswith("/private/files/"):
		kok, rel = os.path.join(frappe.get_site_path(), "private", "files"), temiz[len("/private/files/") :]
	else:
		return None
	if any(p == ".." for p in rel.split("/")):
		return None
	tam = os.path.realpath(os.path.join(kok, rel))
	return tam if tam.startswith(os.path.realpath(kok) + os.sep) else None


def _mtime_or_none(path: Optional[str]) -> Optional[float]:
	"""Dosyanın mtime'ı; dosya yoksa `None`. ASLA yükselmez.

	Ölçüldü (2026-08-19): 5.008 `File` kaydının 14'ünün diskte karşılığı yok.
	Bu satırlar GC'yi düşürmemeli; `REASON_MISSING_ON_DISK` ile atlanırlar.
	"""
	if not path:
		return None
	try:
		return os.path.getmtime(path)
	except OSError:
		return None


# ── Orijinal politikası: `File` envanteri ──────────────────────────────


def _file_rows(limit: int = 0) -> List[Dict[str, Any]]:
	"""GC'nin bakacağı `File` satırları — hassas doctype ekleri HARİÇ.

	`presets.EXCLUDED_DOCTYPES` yalnız OKUNUR (o dosya bu görevin kapsamı
	dışı): KYC/KYB/sipariş belgeleri hiç aday listesine girmesin diye.
	Sorgu parametreli — tablo/kolon adları sabit, kullanıcı girdisi yok.
	"""
	from tradehub_core.media.presets import EXCLUDED_DOCTYPES  # noqa: PLC0415

	frappe = _frappe()
	yer_tutucu = ", ".join(["%s"] * len(EXCLUDED_DOCTYPES))
	sinir = f" limit {int(limit)}" if limit else ""
	return frappe.db.sql(
		f"""select name, file_url, file_size, attached_to_doctype
		from `tabFile`
		where is_folder = 0 and ifnull(file_url, '') <> ''
		  and ifnull(attached_to_doctype, '') not in ({yer_tutucu})
		order by name{sinir}""",
		tuple(EXCLUDED_DOCTYPES),
		as_dict=True,
	)


def _original_candidate(
	satir: Mapping[str, Any],
	policy: RetentionPolicy,
	held: set,
	now: float,
	guard: Optional[set] = None,
	in_use: Optional[set] = None,
	usage_known: bool = True,
) -> GcCandidate:
	"""Tek `File` satırı için karar. SAF — hiçbir şeye dokunmaz.

	Sıra kritik ve `RetentionSweeper.decide` ile AYNI: legal hold her şeyden
	önce gelir; yaş ancak kapı açıksa hesaplanır.

	**2026-08-19 eklenen iki kapı (T-043/T-053).** Bu fonksiyon önceden YALNIZ
	yaşa bakıyordu: `keep_forever=false` yazılan an, kullanımda olup olmadığına
	bakılmaksızın envanterin tamamı silme adayı oluyordu (ölçüm: agresif
	politikayla 4.429 aday). Kör nokta koruması yalnız TÜREV tarafında vardı;
	orijinal tarafta hiç yoktu — yani marka logosu, kategori görseli ve canlı
	ürün görseli aynı kefedeydi. Sıra:

	    1. legal hold           → blocked
	    2. `guard` (kör nokta + KVKK kaynakları) → keep / usage_blind_spot
	    3. kullanım ölçülemedi  → keep / usage_unknown   ← fail-safe
	    4. `in_use` (canlı ya da sipariş kaydı)  → keep / in_use
	    5. adres çözülmüyor / diskte yok / yaş + politika

	3. madde bilinçli: kullanım taraması patlarsa "hiçbir şey kullanılmıyor"
	varsaymak envanteri silmek olurdu.
	"""
	url = str(satir.get("file_url") or "")
	if policy.legal_hold_enabled and url.split("?")[0] in held:
		return GcCandidate(url, POLICY_ORIGINAL, ACTION_BLOCKED, REASON_LEGAL_HOLD, held=True)

	temiz = url.split("?")[0]
	if guard and temiz in guard:
		return GcCandidate(url, POLICY_ORIGINAL, ACTION_KEEP, REASON_BLIND_SPOT)
	if not usage_known:
		return GcCandidate(url, POLICY_ORIGINAL, ACTION_KEEP, REASON_USAGE_UNKNOWN)
	if in_use and temiz in in_use:
		return GcCandidate(url, POLICY_ORIGINAL, ACTION_KEEP, REASON_IN_USE)

	yol = disk_path_for(url)
	if yol is None:
		return GcCandidate(url, POLICY_ORIGINAL, ACTION_KEEP, REASON_NOT_A_FILE_URL)
	mtime = _mtime_or_none(yol)
	if mtime is None:
		# Ölçüldü: 14 `File` kaydının diskte karşılığı yok. Bunları "yaşı
		# sonsuz" sayıp silmek, zaten olmayan dosyanın `File` kaydını da
		# götürür ve geri dönüşü olmayan bir referans kaybı olur.
		return GcCandidate(url, POLICY_ORIGINAL, ACTION_KEEP, REASON_MISSING_ON_DISK)

	yas = max(0.0, (now - mtime) / 86400.0)
	eylem, sebep = policy.original.decide(yas)
	boyut = int(satir.get("file_size") or 0) or _size_or_zero(yol)
	return GcCandidate(url, POLICY_ORIGINAL, eylem, sebep, age_days=yas, size_bytes=boyut)


def _size_or_zero(path: str) -> int:
	try:
		return os.path.getsize(path)
	except OSError:
		return 0


def sweep_originals(
	*,
	policy: Optional[RetentionPolicy] = None,
	gate: Optional[MediaAssetLegalHold] = None,
	dry_run: bool = True,
	limit: int = 0,
	now: Optional[float] = None,
) -> GcSection:
	"""Orijinal saklama politikasını `File` envanterine uygula.

	Varsayılan politika `keep_forever=True` olduğu için varsayılan sonuç
	"hepsi korundu"dur — bu bir eksiklik değil, şemadaki bilinçli varsayılan
	(`retention.md` §6.1). Silme ancak politika açıkça değiştirilirse
	gündeme gelir ve o zaman da `dry_run=False` şart.
	"""
	pol = policy if policy is not None else RetentionPolicy.defaults()
	kapi = gate if gate is not None else MediaAssetLegalHold()
	tutulanlar = kapi.held_urls() if pol.legal_hold_enabled else set()
	an = float(time.time() if now is None else now)
	bolum = GcSection(POLICY_ORIGINAL)
	kapi_saglam = (not pol.legal_hold_enabled) or kapi.enforceable
	koruma = blind_spot_urls()
	kullanilan, kullanim_olculdu = live_usage_urls()

	for satir in _file_rows(limit):
		bolum.scanned += 1
		aday = _original_candidate(
			satir, pol, tutulanlar, an,
			guard=koruma, in_use=kullanilan, usage_known=kullanim_olculdu,
		)
		_record(bolum, aday, dry_run=dry_run, gate_ok=kapi_saglam, apply=_apply_original)
	return bolum


# ── Türev politikası: `Media Rendition` envanteri ──────────────────────


def _rendition_rows(limit: int = 0) -> List[Dict[str, Any]]:
	"""`Media Rendition` satırları. Doctype/tablo yoksa boş liste.

	Ölçüldü (2026-08-19): tablo BOŞ — bayraklar kapalı, türev üretilmiyor.
	İş bugün 0 satırla koşar; bu doğru davranıştır, eksiklik değil.
	"""
	frappe = _frappe()
	if not frappe.db.exists("DocType", MEDIA_RENDITION):
		return []
	return frappe.get_all(
		MEDIA_RENDITION,
		fields=["name", "asset", "profile", "file_url", "bytes", "storage_backend",
			"generated_at", "last_access_at"],
		limit_page_length=int(limit) or 0,
		order_by="name",
	)


def _rendition_age_days(satir: Mapping[str, Any], now: float) -> Optional[float]:
	"""Türevin "kullanılmama" yaşı — son erişim, yoksa üretim damgası.

	`unused_after_days` son ERİŞİMDEN sayılır (`retention.schema.json`
	`unused_definition`). `last_access_at` boşsa türev hiç istenmemiş
	demektir ve saat `generated_at`'ten işler.
	"""
	from frappe.utils import get_datetime  # noqa: PLC0415

	damga = satir.get("last_access_at") or satir.get("generated_at")
	if not damga:
		return None
	try:
		return max(0.0, (now - get_datetime(damga).timestamp()) / 86400.0)
	except (ValueError, TypeError):
		return None


def _derivative_candidate(
	satir: Mapping[str, Any],
	policy: RetentionPolicy,
	held: set,
	verdicts: Mapping[str, str],
	guard: set,
	now: float,
	can_regenerate: bool = True,
) -> GcCandidate:
	"""Tek `Media Rendition` satırı için karar. SAF."""
	url = str(satir.get("file_url") or "")
	ek = {"rendition": satir.get("name"), "asset": satir.get("asset"),
		"backend": satir.get("storage_backend")}
	if policy.legal_hold_enabled and url.split("?")[0] in held:
		return GcCandidate(url, POLICY_DERIVATIVE, ACTION_BLOCKED, REASON_LEGAL_HOLD,
			held=True, extra=ek)
	if url in guard:
		return GcCandidate(url, POLICY_DERIVATIVE, ACTION_KEEP, REASON_BLIND_SPOT, extra=ek)

	yas = _rendition_age_days(satir, now)
	if yas is None:
		return GcCandidate(url, POLICY_DERIVATIVE, ACTION_KEEP, REASON_USAGE_UNKNOWN, extra=ek)

	eylem, sebep = policy.derivative.decide(
		yas, verdicts.get(url, VERDICT_UNKNOWN), str(satir.get("profile") or "")
	)
	if eylem == ACTION_DEMOTE:
		# Soğuk katman bu kurulumda YOK (S3 adaptörü var ama bağlı değil).
		# `RetentionSweeper` ile aynı düşüş: yaslandırma bildirime iner.
		eylem, sebep = ACTION_NOTIFY, REASON_NO_COLD_TIER
	if eylem == ACTION_DELETE and not can_regenerate:
		# `DerivativeRetention.warnings()` yalnız `regenerate_on_demand=False`
		# yazılmış olmasını yakalar. Asıl tehlike tersi: bayrak `True` ama
		# ÜRETİMDE yeniden üretecek yol yok.
		#
		# Ölçüm 2026-08-19 (yeniden doğrulandı): `Media Rendition.generation`
		# alanına YAZAN tek yer `media/pipeline_bridge.py:628` ve orada değer
		# profilden geliyor (`profil.generation or "eager"`) — yani alan
		# türev ÜRETİLİRKEN dolduruluyor. OKUYAN, yani "türev yok, şimdi üret"
		# diyen hiçbir kod yok: `regenerate` / `on_demand` araması boru hattı
		# ve API katmanında tek bir üretim yolu getirmiyor. Silinen bir türev
		# bugün geri gelmez. Politikanın verdiği söz tutulamıyorsa silme
		# bildirime iner.
		eylem, sebep = ACTION_NOTIFY, REASON_NO_REGENERATION
	return GcCandidate(url, POLICY_DERIVATIVE, eylem, sebep, age_days=yas,
		size_bytes=int(satir.get("bytes") or 0), extra=ek)


def _derivative_verdicts(urls: List[str]) -> Dict[str, str]:
	"""`usage.verdicts_for` ile toplu kullanım kararı — KENDİ tespitimiz YOK.

	`deep=True`: `unused` ile `history_only` ayrımı olmadan
	`DerivativeRetention.decide` hiçbir şeyi silinebilir saymaz
	(`UNUSED_VERDICTS` bu ikisi). Sığ tarama `not_in_use` döndürür ve o
	etiket listede olmadığı için her şey `usage_unknown` ile korunurdu —
	yani sığ tarama sessizce "hiçbir şey yapma"ya dönerdi.
	"""
	if not urls:
		return {}
	from tradehub_core.media.usage import verdicts_for  # noqa: PLC0415

	try:
		ham = verdicts_for(urls, deep=True)
	except Exception:
		_frappe().log_error(title="retention: usage verdicts failed",
			message=_frappe().get_traceback(with_context=True))
		return {}
	return {u: str(v.get("verdict") or VERDICT_UNKNOWN) for u, v in ham.items()}


def sweep_derivatives(
	*,
	policy: Optional[RetentionPolicy] = None,
	gate: Optional[MediaAssetLegalHold] = None,
	dry_run: bool = True,
	limit: int = 0,
	now: Optional[float] = None,
) -> GcSection:
	"""Kullanılmayan türevleri temizle. Varsayılan eylem `notify_only`.

	"İstendiğinde yeniden üret" bedava değil: T-028 ölçümü görsel başına
	**10,45 sn** (SSIM %52, encode %37). Şema bu yüzden varsayılanı silme
	değil bildirim yapıyor — silinen her türev, ilk isteyen kullanıcıya
	10 saniyelik bekleme olarak geri döner.
	"""
	pol = policy if policy is not None else RetentionPolicy.defaults()
	kapi = gate if gate is not None else MediaAssetLegalHold()
	satirlar = _rendition_rows(limit)
	bolum = GcSection(POLICY_DERIVATIVE)
	if not satirlar:
		return bolum

	tutulanlar = kapi.held_urls() if pol.legal_hold_enabled else set()
	kararlar = _derivative_verdicts([str(s.get("file_url") or "") for s in satirlar if s.get("file_url")])
	koruma = blind_spot_urls()
	an = float(time.time() if now is None else now)
	kapi_saglam = (not pol.legal_hold_enabled) or kapi.enforceable
	uretilebilir = pol.derivative.regenerate_on_demand and regeneration_available()

	for satir in satirlar:
		bolum.scanned += 1
		aday = _derivative_candidate(satir, pol, tutulanlar, kararlar, koruma, an, uretilebilir)
		_record(bolum, aday, dry_run=dry_run, gate_ok=kapi_saglam, apply=_apply_derivative)
	return bolum


def regeneration_available() -> bool:
	"""Silinen bir türev gerçekten geri getirilebilir mi.

	`regenerate_on_demand=True` bir SÖZ; bu fonksiyon sözün tutulup
	tutulamayacağını ölçer. Boru hattı bayrağı kapalıyken hiçbir türev
	üretilmiyor — o hâlde silinen türev geri gelmez ve "istendiğinde yeniden
	üret" cümlesi kâğıt üstünde kalır.

	Maliyet tarafı da burada: T-028 ölçümü görsel başına **10,45 sn**
	(SSIM %52, encode %37). Bayrak açık olsa bile silinen her türev, ilk
	isteyen kullanıcıya 10 saniyelik bekleme olarak geri döner — bu yüzden
	şema varsayılanı `notify_only`.
	"""
	try:
		from tradehub_core.media.pipeline_flags import is_enabled  # noqa: PLC0415

		return bool(is_enabled())
	except Exception:
		# Ölçemedik → güvenli taraf: yeniden üretilemez say, silme.
		return False


# ── Kayıt + uygulama ───────────────────────────────────────────────────


def _record(
	bolum: GcSection,
	aday: GcCandidate,
	*,
	dry_run: bool,
	gate_ok: bool,
	apply: Callable[[GcCandidate], bool],
) -> None:
	"""Kararı sayaçlara işle ve (yalnız ıslak koşumda) uygula.

	`RetentionSweeper.sweep` gövdesiyle AYNI sıra ve aynı gerekçe. Kuru
	koşumda `apply` HİÇ çağrılmaz — "önce sil sonra geri al" diye bir yol
	yok, tek koruma çağrının hiç yapılmaması.
	"""
	if aday.action == ACTION_BLOCKED:
		bolum.blocked += 1
		bolum.note(aday.reason)
		bolum.samples.append(aday.to_dict())
		return
	if aday.action == ACTION_KEEP:
		bolum.kept += 1
		bolum.note(aday.reason)
		return
	if aday.action == ACTION_NOTIFY:
		bolum.notified += 1
		bolum.note(aday.reason)
		bolum.samples.append(aday.to_dict())
		return

	bolum.candidates += 1
	bolum.bytes_candidate += aday.size_bytes
	bolum.samples.append(aday.to_dict())
	if not gate_ok:
		# Legal hold açık ama kapı uygulanamıyor → yıkıcı işlem YAPILMAZ.
		bolum.blocked += 1
		bolum.note(REASON_GATE_UNENFORCEABLE)
		return
	if dry_run:
		return
	_apply_and_count(bolum, aday, apply)


def _apply_and_count(bolum: GcSection, aday: GcCandidate, apply: Callable[[GcCandidate], bool]) -> None:
	try:
		uygulandi = apply(aday)
	except Exception:
		_frappe().log_error(title="retention gc apply failed",
			message=_frappe().get_traceback(with_context=True))
		bolum.failed += 1
		return
	if not uygulandi:
		bolum.failed += 1
		return
	if aday.action == ACTION_DELETE:
		bolum.deleted += 1
	else:
		bolum.demoted += 1
	bolum.bytes_freed += aday.size_bytes


def _apply_original(aday: GcCandidate) -> bool:
	"""Orijinali ÇÖPE taşı — kalıcı silme DEĞİL.

	Repo'nun silme semantiği iki adımlı (`retention.md` §2.1): çöp + 30 gün
	bekleme + audit. `trash.move_to_trash` o yolun tamamını çalıştırır
	(kullanım kapısı, referans zinciri, denetim kaydı). Kalıcı silmeyi
	zaten `trash.purge_expired` günlük işi yapıyor; burada ikinci bir
	kalıcı silme yolu açmak, iki farklı silme davranışı demekti.
	"""
	from tradehub_core.media import trash  # noqa: PLC0415

	return bool(trash.move_to_trash(aday.url).get("ok", True))


def _apply_derivative(aday: GcCandidate) -> bool:
	"""Türevi sil: önce dosya çöpe, sonra `Media Rendition` kaydı.

	Sıra bilinçli — kayıt önce silinirse dosya öksüz kalır ve onu bulan
	hiçbir sorgu kalmaz (`retention.md` §5.5 "önce DB sonra disk" penceresi).
	"""
	from tradehub_core.media import trash  # noqa: PLC0415

	frappe = _frappe()
	if aday.url:
		trash.move_to_trash(aday.url, force=True)
	ad = aday.extra.get("rendition")
	if ad:
		# Sistem işi: scheduler bağlamında kullanıcı yok, permission kontrolü
		# uygulanamaz (anti-pattern 13'ün "sistem yolları" istisnası).
		frappe.delete_doc(MEDIA_RENDITION, ad, force=True, ignore_permissions=True)
	return True


# ── Bakım raporu ───────────────────────────────────────────────────────


def _tier_snapshot() -> Dict[str, int]:
	"""Türevlerin katman dağılımı: `local` / `s3` / `mirror` başına sayı."""
	frappe = _frappe()
	if not frappe.db.exists("DocType", MEDIA_RENDITION):
		return {}
	satirlar = frappe.db.sql(
		f"select ifnull(storage_backend, 'local') as k, count(*) as n "
		f"from `tab{MEDIA_RENDITION}` group by k",
		as_dict=True,
	)
	return {str(s["k"]): int(s["n"]) for s in satirlar}


def _legal_hold_summary(gate: MediaAssetLegalHold) -> Dict[str, Any]:
	return {
		"source": f"{MEDIA_ASSET}.{LEGAL_HOLD_DOCFIELD}",
		"enforceable": gate.enforceable,
		"held_assets": len(gate.held_asset_names()),
		"held_urls": len(gate.held_urls()),
	}


def run_maintenance(
	*,
	policy: Optional[RetentionPolicy] = None,
	dry_run: bool = True,
	limit: int = 0,
	now: Optional[float] = None,
) -> Dict[str, Any]:
	"""Bakım raporu: dosya sayıları, katman geçişleri, atlananlar + sebepleri.

	`dry_run` VARSAYILAN OLARAK `True`. Islak koşum yalnız çağıran açıkça
	`dry_run=False` derse olur; zamanlanmış iş bunu kendiliğinden yapmaz
	(bkz. `run_scheduled_gc`).
	"""
	baslangic = time.time()
	pol = policy if policy is not None else RetentionPolicy.defaults()
	kapi = MediaAssetLegalHold()
	oncesi = _tier_snapshot()
	orijinal = sweep_originals(policy=pol, gate=kapi, dry_run=dry_run, limit=limit, now=now)
	turev = sweep_derivatives(policy=pol, gate=kapi, dry_run=dry_run, limit=limit, now=now)
	sonrasi = _tier_snapshot()
	return {
		"generated_at": _frappe().utils.now(),
		"dry_run": dry_run,
		"policy": pol.to_dict(),
		"policy_warnings": pol.warnings(),
		"legal_hold": _legal_hold_summary(kapi),
		"sections": [orijinal.to_dict(), turev.to_dict()],
		"tiers": {"before": oncesi, "after": sonrasi,
			"transitions": _tier_diff(oncesi, sonrasi), "demoted": turev.demoted + orijinal.demoted},
		"totals": _totals(orijinal, turev),
		"duration_ms": int((time.time() - baslangic) * 1000),
	}


def _tier_diff(before: Mapping[str, int], after: Mapping[str, int]) -> Dict[str, int]:
	"""Katman başına net değişim. Boş kümede boş sözlük — sıfır satır yazılmaz."""
	anahtarlar = set(before) | set(after)
	fark = {k: int(after.get(k, 0)) - int(before.get(k, 0)) for k in sorted(anahtarlar)}
	return {k: v for k, v in fark.items() if v}


def _totals(*bolumler: GcSection) -> Dict[str, Any]:
	toplam_atlama: Dict[str, int] = {}
	for b in bolumler:
		for sebep, sayi in b.skips.items():
			toplam_atlama[sebep] = toplam_atlama.get(sebep, 0) + sayi
	return {
		"scanned": sum(b.scanned for b in bolumler),
		"kept": sum(b.kept for b in bolumler),
		"candidates": sum(b.candidates for b in bolumler),
		"deleted": sum(b.deleted for b in bolumler),
		"demoted": sum(b.demoted for b in bolumler),
		"notified": sum(b.notified for b in bolumler),
		"blocked": sum(b.blocked for b in bolumler),
		"failed": sum(b.failed for b in bolumler),
		"bytes_candidate": sum(b.bytes_candidate for b in bolumler),
		"bytes_freed": sum(b.bytes_freed for b in bolumler),
		"skipped_by_reason": dict(sorted(toplam_atlama.items())),
	}


# ── Zamanlanmış giriş noktası ──────────────────────────────────────────

#: Islak koşumu açan site_config anahtarı. YOKSA ya da 0 ise iş KURU koşar.
#: Anahtar adı bilinçli olarak uzun ve tek amaçlı: yanlışlıkla açılmasın.
ENFORCE_FLAG: str = "media_retention_gc_enforce"

#: T-053 kriter 1: "orijinaller ve türevler için AYRI zamanlanmış işler,
#: ayardan sürülen". Ayrı iş demek ayrı ANAHTAR demek — tek bayrakla iki
#: politikayı birden açmak, "iki politika birbirini etkilemez" (retention.md
#: §6) kuralını zamanlama düzeyinde bozardı. Bir bayrak diğerini AÇMAZ:
#: türev silmeyi açmak orijinal silmeyi açmıyor, tersi de öyle.
ENFORCE_FLAG_ORIGINALS: str = "media_retention_gc_originals_enforce"
ENFORCE_FLAG_DERIVATIVES: str = "media_retention_gc_derivatives_enforce"

#: Ayrı iş = ayrı kilit. Ortak kilit, iki iş ayrı saatlerde koşsa bile
#: birinin diğerini "locked" diye atlatmasına yol açardı.
LOCK_ALL: str = "media_retention_gc_lock"
LOCK_ORIGINALS: str = "media_retention_gc_originals_lock"
LOCK_DERIVATIVES: str = "media_retention_gc_derivatives_lock"

#: Kilit ömrü (sn) — `tasks.py:calculate_customer_grades` deseniyle aynı.
LOCK_TTL: int = 3600


def _gc_job(
	*,
	lock: str,
	flag: str,
	title: str,
	sweep: Callable[..., GcSection],
	policy_name: str,
) -> Dict[str, Any]:
	"""Tek politikalı zamanlanmış GC işinin ortak gövdesi.

	`run_scheduled_gc` ile aynı üç güvenlik: Redis kilidi, varsayılan kuru
	koşum, `Error Log`'a rapor. Fark, tek bir `GcSection` üretmesi — bölüm
	sözlüğü `run_maintenance` çıktısının aynısı biçimde, ama tek politika.
	"""
	frappe = _frappe()
	if frappe.cache().get_value(lock):
		frappe.log_error(f"{title} zaten çalışıyor", "Scheduler Lock")
		return {"skipped": "locked", "policy": policy_name}

	frappe.cache().set_value(lock, 1, expires_in_sec=LOCK_TTL)
	baslangic = time.time()
	try:
		pol = RetentionPolicy.defaults()
		kapi = MediaAssetLegalHold()
		zorla = bool(frappe.conf.get(flag))
		bolum = sweep(policy=pol, gate=kapi, dry_run=not zorla)
	finally:
		frappe.cache().delete_value(lock)

	rapor = {
		"generated_at": frappe.utils.now(),
		"policy_name": policy_name,
		"dry_run": not zorla,
		"enforce_flag": flag,
		"policy": pol.to_dict(),
		"policy_warnings": pol.warnings(),
		"legal_hold": _legal_hold_summary(kapi),
		"sections": [bolum.to_dict()],
		"totals": _totals(bolum),
		"duration_ms": int((time.time() - baslangic) * 1000),
	}
	frappe.log_error(
		title=title,
		message=json.dumps(rapor, ensure_ascii=False, indent=2, default=str)[:100000],
	)
	return rapor


def run_scheduled_gc_originals() -> Dict[str, Any]:
	"""**Orijinal** saklama işi — `hooks.py` `scheduler_events` kaydı bekliyor.

	`hooks.py` bu görevin dokunma yasağı listesinde; kaydı Şerit A yapacak.
	Kayıt satırı (yalnız EKLEME):

	    "tradehub_core.media.pipeline.storage.retention.run_scheduled_gc_originals",

	Islak koşum `site_config.media_retention_gc_originals_enforce = 1`
	olmadan OLMAZ. Bugün anahtar yok → kuru koşum.
	"""
	return _gc_job(
		lock=LOCK_ORIGINALS,
		flag=ENFORCE_FLAG_ORIGINALS,
		title="media.retention_gc.originals",
		sweep=sweep_originals,
		policy_name=POLICY_ORIGINAL,
	)


def run_scheduled_gc_derivatives() -> Dict[str, Any]:
	"""**Türev** saklama işi — `hooks.py` `scheduler_events` kaydı bekliyor.

	Kayıt satırı (yalnız EKLEME):

	    "tradehub_core.media.pipeline.storage.retention.run_scheduled_gc_derivatives",

	Islak koşum `site_config.media_retention_gc_derivatives_enforce = 1`
	istiyor. Bayrak açılsa bile silme bugün gerçekleşmez:
	`regeneration_available()` `False` olduğu sürece `delete` kararı
	`notify_only / regeneration_path_unavailable`'a düşüyor.
	"""
	return _gc_job(
		lock=LOCK_DERIVATIVES,
		flag=ENFORCE_FLAG_DERIVATIVES,
		title="media.retention_gc.derivatives",
		sweep=sweep_derivatives,
		policy_name=POLICY_DERIVATIVE,
	)


def run_scheduled_gc() -> Dict[str, Any]:
	"""Günlük bakım işi — `hooks.py` `scheduler_events["daily"]`.

	**Varsayılanı kuru koşumdur ve site_config'te `media_retention_gc_enforce`
	açıkça 1 yapılmadıkça hiçbir şey silmez.** Gerekçe repo genelindeki
	fail-safe kuralıyla aynı: yanlış yapılandırılmış tek bir politika alanı
	(`keep_forever=false` + `local_days=1`) tüm envanteri tek turda çöpe
	atabilir; varsayılan olarak silen bir zamanlanmış iş bunu gece yarısı,
	kimse bakmadan yapardı.

	Raporu `Error Log`'a yazar — `media/audit.py` eylem sözlüğü kapalı bir
	küme ve ona yeni eylem eklemek bu görevin kapsamı dışı.
	"""
	frappe = _frappe()
	if frappe.cache().get_value(LOCK_ALL):
		frappe.log_error("media retention GC zaten çalışıyor", "Scheduler Lock")
		return {"skipped": "locked"}

	frappe.cache().set_value(LOCK_ALL, 1, expires_in_sec=LOCK_TTL)
	try:
		zorla = bool(frappe.conf.get(ENFORCE_FLAG))
		rapor = run_maintenance(dry_run=not zorla)
	finally:
		frappe.cache().delete_value("media_retention_gc_lock")

	frappe.log_error(
		title="media.retention_gc",
		message=json.dumps(rapor, ensure_ascii=False, indent=2, default=str)[:100000],
	)
	return rapor


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
	# T-053 çöp toplama (frappe tarafı)
	"MEDIA_ASSET",
	"MEDIA_RENDITION",
	"LEGAL_HOLD_DOCFIELD",
	"BLIND_SPOT_SOURCES",
	"PROTECTED_SOURCES",
	"ENFORCE_FLAG",
	"ENFORCE_FLAG_ORIGINALS",
	"ENFORCE_FLAG_DERIVATIVES",
	"LOCK_ALL",
	"LOCK_ORIGINALS",
	"LOCK_DERIVATIVES",
	"live_usage_urls",
	"REASON_BLIND_SPOT",
	"REASON_MISSING_ON_DISK",
	"REASON_NOT_A_FILE_URL",
	"REASON_GATE_UNENFORCEABLE",
	"REASON_NO_REGENERATION",
	"regeneration_available",
	"MediaAssetLegalHold",
	"GcCandidate",
	"GcSection",
	"blind_spot_urls",
	"disk_path_for",
	"sweep_originals",
	"sweep_derivatives",
	"run_maintenance",
	"run_scheduled_gc",
	"run_scheduled_gc_originals",
	"run_scheduled_gc_derivatives",
]
