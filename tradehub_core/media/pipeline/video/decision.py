"""T-071 — video kararı: kural tablosu JSON'dan okunur, kod sabit kalır.

**Çözdüğü problem.** Bugün karar `tradehub_core/media/transcode.py:154`'te
tek satır:

    return genislik > NEEDS_TRANSCODE_MAX_WIDTH or bitrate > NEEDS_TRANSCODE_MAX_BITRATE

İki eşik koda gömülü ve karar iki DEĞERLİ: işle ya da işleme. Üçüncü bir
değişkeni (kare hızı, piksel formatı, kodek, kap, moov konumu, verimlilik)
hesaba katmak ya da "yalnız kabı düzelt" gibi ucuz bir aksiyon eklemek kod
değişikliği, kod incelemesi ve dağıtım gerektiriyor.

Bu modül kararı VERİYE taşır: `tradehub_core/media/pipeline/policy/video_decision.json`
içindeki sıralı kural listesi okunur, **ilk eşleşen kural kazanır**, eşleşme
yoksa `default` uygulanır. Yeni bir karar eklemek JSON'a bir nesne eklemektir;
bu dosya DEĞİŞMEZ. `tradehub_core/media/pipeline/policy/engine.py` ile aynı tasarım kuralı.

**Dört aksiyon.**

    PASSTHROUGH  dosyaya dokunma — zaten teslim edilebilir
    REMUX        yeniden kodlama YOK, yalnız kap/atom düzeni (-c copy +faststart)
    TRANSCODE    tam yeniden kodlama (H.264 High + AAC 128k + faststart)
    REJECT       hat bu dosyayı işlemez, kodlu hata döner

REMUX bugün YOK: moov'u sonda olan bir .mp4 ya da bir .mov için tek seçenek
dakikalar süren tam VP9 kodlamasıydı; oysa iş saniyeler süren bir akış
kopyalamasıydı.

**Yükleme anında doğrulama.** Tabloda geçen her değişken adı ve her operatör
`VideoFacts.variables()` ve `_OPS` ile karşılaştırılır. Bilinmeyen ad ya da
operatör `DecisionTableError` atar — yazım hatası sessizce "hiç eşleşmedi"ye
dönüşmez, çünkü öyle bir hata tabloyu bozar ama testleri geçirir.

**Karar yan etkisizdir.** Bu modül dosya açmaz, ffmpeg çalıştırmaz, frappe
import etmez. Girdisi bir künye (`VideoFacts` ya da düz sözlük), çıktısı bir
`VideoDecision`. Kararın uygulanması `transcode.py`'nin işidir.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.policy import POLICY_DIR
from tradehub_core.media.pipeline.video.probe import VideoFacts

#: Karar tablosunun yeri. Politika VERİSİ `policy/` altında durur (slot
#: politikalarıyla aynı yerde), KOD `video/` altında — ikisi karışmasın.
DECISION_TABLE_PATH: Path = POLICY_DIR / "video_decision.json"

ACTION_PASSTHROUGH: str = "PASSTHROUGH"
ACTION_REMUX: str = "REMUX"
ACTION_TRANSCODE: str = "TRANSCODE"
ACTION_REJECT: str = "REJECT"

ACTIONS: Tuple[str, ...] = (ACTION_PASSTHROUGH, ACTION_REMUX, ACTION_TRANSCODE, ACTION_REJECT)

#: Aksiyonun yeni dosya üretip üretmediği — çağıranın kuyruk kararı buna bakar.
WRITES_NEW_FILE: Dict[str, bool] = {
	ACTION_PASSTHROUGH: False,
	ACTION_REMUX: True,
	ACTION_TRANSCODE: True,
	ACTION_REJECT: False,
}


class DecisionTableError(ValueError):
	"""Karar tablosu bozuk — bilinmeyen değişken, operatör ya da aksiyon.

	Yükleme anında atılır. Kararı sessizce yanlış vermektense hiç vermemek
	tercih edilir: bozuk bir tablo, her dosyayı `default` aksiyona düşürerek
	testleri geçirir ama üretimde her videoyu dokunulmadan bırakırdı.
	"""


# ── Operatörler ─────────────────────────────────────────────────────────
#
# Kasten KÜÇÜK bir küme. Tabloya `eval` benzeri bir ifade dili koymak, veri
# dosyasını kod hâline getirir ve `safe_eval` tartışmasını açar (anti-patterns
# §15). Sekiz operatör bugünkü ve öngörülen kuralların hepsine yetiyor.


def _op_in(sol: Any, sag: Any) -> bool:
	return sol in (sag or ())


def _op_not_in(sol: Any, sag: Any) -> bool:
	return sol not in (sag or ())


_OPS = {
	"eq": lambda sol, sag: sol == sag,
	"ne": lambda sol, sag: sol != sag,
	"lt": lambda sol, sag: sol < sag,
	"lte": lambda sol, sag: sol <= sag,
	"gt": lambda sol, sag: sol > sag,
	"gte": lambda sol, sag: sol >= sag,
	"in": _op_in,
	"not_in": _op_not_in,
}


@dataclass(frozen=True)
class Rule:
	"""Tablodaki tek bir kural."""

	id: str
	action: str
	when: Mapping[str, Any]
	code: str = ""
	reason: str = ""
	meta: Mapping[str, Any] = field(default_factory=dict, repr=False)

	def matches(self, degiskenler: Mapping[str, Any]) -> bool:
		return _eval_condition(self.when, degiskenler, self.id)


@dataclass(frozen=True)
class VideoDecision:
	"""Kararın kendisi + NEDEN böyle karar verildiği.

	`trace` bilinçli olarak taşınıyor: "bu video neden transcode edildi"
	sorusunun cevabı, üretimde bir kullanıcı sorduğunda ancak kayıtlıysa
	verilebilir. Kural sırası anlamlı olduğu için hangi kuralların bakılıp
	eşleşmediği de bilgidir.
	"""

	action: str
	rule_id: str
	code: str
	reason: str
	variables: Mapping[str, Any] = field(default_factory=dict, repr=False)
	trace: Tuple[Tuple[str, bool], ...] = ()
	targets: Mapping[str, Any] = field(default_factory=dict, repr=False)

	@property
	def writes_new_file(self) -> bool:
		return WRITES_NEW_FILE.get(self.action, False)

	@property
	def rejected(self) -> bool:
		return self.action == ACTION_REJECT

	@property
	def needs_ffmpeg(self) -> bool:
		return self.action in (ACTION_REMUX, ACTION_TRANSCODE)

	def as_dict(self) -> Dict[str, Any]:
		return {
			"action": self.action,
			"rule_id": self.rule_id,
			"code": self.code,
			"reason": self.reason,
			"writes_new_file": self.writes_new_file,
		}


def _eval_condition(kosul: Mapping[str, Any], degiskenler: Mapping[str, Any], kural_id: str) -> bool:
	"""Koşul ağacını değerlendirir: `all` / `any` / `not` / yaprak."""
	if "all" in kosul:
		return all(_eval_condition(k, degiskenler, kural_id) for k in kosul["all"])
	if "any" in kosul:
		return any(_eval_condition(k, degiskenler, kural_id) for k in kosul["any"])
	if "not" in kosul:
		return not _eval_condition(kosul["not"], degiskenler, kural_id)

	ad = kosul["var"]
	op = kosul["op"]
	beklenen = kosul.get("value")
	if ad not in degiskenler:
		raise DecisionTableError(f"{kural_id}: bilinmeyen degisken {ad!r}")
	fonk = _OPS.get(op)
	if fonk is None:
		raise DecisionTableError(f"{kural_id}: bilinmeyen operator {op!r}")
	try:
		return bool(fonk(degiskenler[ad], beklenen))
	except TypeError as exc:
		# Tip uyuşmazlığı (metin < sayı gibi) bir tablo hatasıdır, çalışma
		# zamanı sürprizi değil — sessizce False dönmek kuralı ölü bırakırdı.
		raise DecisionTableError(f"{kural_id}: {ad} {op} karsilastirilamadi: {exc}") from exc


def _validate_condition(kosul: Any, bilinen_degiskenler: Sequence[str], kural_id: str) -> None:
	"""Koşul ağacını YÜKLEME ANINDA doğrular — çalışma zamanına hata bırakmaz."""
	if not isinstance(kosul, Mapping):
		raise DecisionTableError(f"{kural_id}: kosul bir nesne olmali, {type(kosul).__name__} geldi")
	for anahtar in ("all", "any"):
		if anahtar in kosul:
			alt = kosul[anahtar]
			if not isinstance(alt, list) or not alt:
				raise DecisionTableError(f"{kural_id}: {anahtar} bos olmayan bir liste olmali")
			for k in alt:
				_validate_condition(k, bilinen_degiskenler, kural_id)
			return
	if "not" in kosul:
		_validate_condition(kosul["not"], bilinen_degiskenler, kural_id)
		return
	if "var" not in kosul or "op" not in kosul:
		raise DecisionTableError(f"{kural_id}: yaprak kosulda 'var' ve 'op' zorunlu")
	if kosul["var"] not in bilinen_degiskenler:
		raise DecisionTableError(
			f"{kural_id}: bilinmeyen degisken {kosul['var']!r} "
			f"(VideoFacts.variables() disinda)"
		)
	if kosul["op"] not in _OPS:
		raise DecisionTableError(f"{kural_id}: bilinmeyen operator {kosul['op']!r}")


class DecisionTable:
	"""JSON'dan okunmuş kural tablosu. Kararı bu sınıf verir, kod değil.

	Örnek:

	    tablo = DecisionTable.load()
	    karar = tablo.evaluate(probe.probe("video.mp4"))
	    karar.action   # "TRANSCODE"
	    karar.rule_id  # "bitrate_over_cap"
	"""

	def __init__(self, veri: Mapping[str, Any], *, kaynak: str = "") -> None:
		self.raw: Mapping[str, Any] = veri
		self.kaynak = kaynak
		self.schema_version: str = str(veri.get("schema_version") or "")
		self.targets: Mapping[str, Any] = veri.get("targets") or {}
		self.poster: Mapping[str, Any] = veri.get("poster") or {}
		self.preview_clip: Mapping[str, Any] = veri.get("preview_clip") or {}
		self.hls: Mapping[str, Any] = veri.get("hls") or {}

		bilinen = tuple(_ORNEK_DEGISKENLER)
		self.rules: List[Rule] = []
		gorulen_id: set[str] = set()
		for ham in veri.get("rules") or []:
			kural_id = str(ham.get("id") or "")
			if not kural_id:
				raise DecisionTableError("kural 'id' alanini tasimali")
			if kural_id in gorulen_id:
				raise DecisionTableError(f"kural id'si tekrar ediyor: {kural_id}")
			gorulen_id.add(kural_id)
			aksiyon = str(ham.get("action") or "")
			if aksiyon not in ACTIONS:
				raise DecisionTableError(f"{kural_id}: bilinmeyen aksiyon {aksiyon!r}")
			kosul = ham.get("when")
			_validate_condition(kosul, bilinen, kural_id)
			self.rules.append(
				Rule(
					id=kural_id,
					action=aksiyon,
					when=kosul,
					code=str(ham.get("code") or ""),
					reason=str(ham.get("reason") or ""),
					meta={k: v for k, v in ham.items() if k not in ("id", "action", "when", "code", "reason")},
				)
			)

		varsayilan = veri.get("default") or {}
		self.default_action: str = str(varsayilan.get("action") or ACTION_PASSTHROUGH)
		if self.default_action not in ACTIONS:
			raise DecisionTableError(f"default: bilinmeyen aksiyon {self.default_action!r}")
		self.default_code: str = str(varsayilan.get("code") or "")
		self.default_reason: str = str(varsayilan.get("reason") or "")

		if not self.rules:
			raise DecisionTableError("karar tablosunda hic kural yok")

	# ── Yükleme ─────────────────────────────────────────────────────────

	@classmethod
	def load(cls, path: Optional[Path] = None) -> "DecisionTable":
		yol = Path(path) if path else DECISION_TABLE_PATH
		with open(yol, "r", encoding="utf-8") as f:
			return cls(json.load(f), kaynak=str(yol))

	# ── Karar ───────────────────────────────────────────────────────────

	def evaluate(self, facts: Any) -> VideoDecision:
		"""Künyeyi kural listesinden geçir. İLK EŞLEŞEN kural kazanır.

		`facts` ya `VideoFacts` ya da `variables()` biçiminde düz bir
		sözlüktür. İkincisi testler için: 10 MB'lık dosya üretmeden bir
		kuralı sınamak mümkün olmalı.
		"""
		degiskenler = facts.variables() if isinstance(facts, VideoFacts) else dict(facts)
		eksik = set(_ORNEK_DEGISKENLER) - set(degiskenler)
		if eksik:
			raise DecisionTableError(f"kunye eksik degisken tasiyor: {sorted(eksik)}")

		iz: List[Tuple[str, bool]] = []
		for kural in self.rules:
			eslesti = kural.matches(degiskenler)
			iz.append((kural.id, eslesti))
			if eslesti:
				return VideoDecision(
					action=kural.action,
					rule_id=kural.id,
					code=kural.code,
					reason=kural.reason,
					variables=degiskenler,
					trace=tuple(iz),
					targets=self.targets,
				)

		return VideoDecision(
			action=self.default_action,
			rule_id="default",
			code=self.default_code,
			reason=self.default_reason,
			variables=degiskenler,
			trace=tuple(iz),
			targets=self.targets,
		)

	def rule(self, rule_id: str) -> Rule:
		for k in self.rules:
			if k.id == rule_id:
				return k
		raise KeyError(rule_id)

	def __repr__(self) -> str:  # pragma: no cover — yalnız hata ayıklama
		return f"<DecisionTable {self.schema_version} {len(self.rules)} kural>"


#: `VideoFacts` alan adlarının tek kaynağı. Tablo doğrulaması buna bakar;
#: künye sınıfına yeni bir alan eklemek tabloda o adı kullanılabilir kılar.
_ORNEK_DEGISKENLER: Tuple[str, ...] = tuple(VideoFacts().variables().keys())

_VARSAYILAN_TABLO: Optional[DecisionTable] = None


def default_table() -> DecisionTable:
	"""Süreç ömrü boyunca tek kez okunan tablo.

	JSON her karar için yeniden ayrıştırılırsa, yükleme başına 15 kuralın
	doğrulanması boşuna tekrar eder. Test tarafı `DecisionTable.load(path)`
	ile kendi tablosunu kurabilir — önbellek paylaşılan durumu kirletmez.
	"""
	global _VARSAYILAN_TABLO
	if _VARSAYILAN_TABLO is None:
		_VARSAYILAN_TABLO = DecisionTable.load()
	return _VARSAYILAN_TABLO


def decide(facts: Any) -> VideoDecision:
	"""Kısayol: varsayılan tabloyla karar ver."""
	return default_table().evaluate(facts)


def decide_path(path: str) -> VideoDecision:
	"""Dosyayı ölç ve karar ver — künyeyi ayrıca almak istemeyen çağıran için."""
	from tradehub_core.media.pipeline.video import probe as probe_modulu

	return decide(probe_modulu.probe(path))


__all__ = [
	"ACTION_PASSTHROUGH",
	"ACTION_REMUX",
	"ACTION_TRANSCODE",
	"ACTION_REJECT",
	"ACTIONS",
	"DECISION_TABLE_PATH",
	"DecisionTable",
	"DecisionTableError",
	"Rule",
	"VideoDecision",
	"decide",
	"decide_path",
	"default_table",
]
