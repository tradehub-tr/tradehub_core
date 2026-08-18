"""Kuyruk zarfı + idempotency muhafızı. Retry politikasını TEKRARLAMAZ.

MEVCUT DURUM (OKUNDU, DEĞİŞTİRİLMEDİ)
-------------------------------------
`tradehub_core/media/jobs.py` ortak kuyruk sözleşmesini ZATEN tanımlıyor:

    STATE_RUNNING/COMPLETED/PARTIAL/ERROR   ortak durum sözlüğü
    MAX_ATTEMPTS = 3                        deneme hakkı
    BACKOFF_SECONDS = (300, 900)            deneme başına bekleme
    STALE_AFTER_SECONDS = 2700              takılı iş eşiği
    backoff_seconds() / next_attempt_at() / is_due() / is_stale()

Bunların HİÇBİRİ burada yeniden yazılmadı. Sayısal politika o dosyanın malı;
bu modül onu içeri alır (frappe yoksa aynasına düşer) ve testi ayrışmayı
yakalar (`tests/test_state_machine.py`).

BU MODÜLÜN EKLEDİĞİ: İDEMPOTENCY
--------------------------------
Üretimde iki ayrı ad-hoc çözüm var, ikisi de kendi işine özel:

    transcode.py:178  `if mevcut_durum in (processing, ready): return`
                      — durum alanına bakarak tekrarı engelliyor. Yalnız video
                      için ve yalnız `File` kaydı varsa çalışır.
    runner.py         Redis ilerleme sözlüğü — iş başına, dosya başına değil.

Ortak bir anahtar yok. Sonuç: aynı içeriği iki kez yükleyen kullanıcı iki tam
işlem ödüyor ve süpürücü "takılı" saydığı bir işi ikinci kez kuyruğa
verdiğinde aynı dosyayı iki worker yazabiliyor (`STALE_AFTER_SECONDS`
yorumunda bu risk açıkça anlatılmış ama korunan tek şey süre; çakışma anında
durduran bir kilit yok).

`IdempotencyGuard` o kilidi tanımlar:

    key = idempotency_key(kind, target, content_hash, params)

Anahtar İÇERİKTEN türer (`sha256`), dosya adından değil — `naming.py` zaten
içerik-adresli adlandırma yapıyor, aynı içerik aynı anahtarı üretir. `params`
da anahtara girer: aynı görselin `w96` ve `w1920` türevi AYRI işlerdir.

Muhafız üç şey yapar:
    claim()    anahtarı kilitle; zaten kilitliyse çalışan/biten sonucu döndür
    complete() sonucu kaydet, kilidi bırak (sonuç TTL boyunca yeniden kullanılır)
    fail()     kilidi bırak, denemeyi say (yeniden deneme mümkün kalsın)

`InMemoryGuard` referans uygulamadır ve testlerde kullanılır; üretimde aynı
arayüzün Redis karşılığı yazılacaktır (`api/` katmanı ile birlikte, FAZ 3'TE
UYGULANMADI). Arayüz `Protocol` olarak ilan edildiği için taşıma katmanı
değişince bu dosya değişmez.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

# ── Retry politikası: KAYNAK tradehub_core/media/jobs.py ────────────────
#
# Frappe varsa oradan alınır. Yoksa aşağıdaki ayna kullanılır ve test
# ayrışmayı düşürür. Ayna değerleri kaynak dosyanın 60-88. satırlarından.
_MIRROR = {
	"STATE_RUNNING": "running",
	"STATE_COMPLETED": "completed",
	"STATE_PARTIAL": "partial",
	"STATE_ERROR": "error",
	"MAX_ATTEMPTS": 3,
	"BACKOFF_SECONDS": (300, 900),
	"STALE_AFTER_SECONDS": 2700,
	"SWEEP_EVERY_SECONDS": 300,
}

try:  # pragma: no cover - bench içinde bu dal çalışır
	from tradehub_core.media import jobs as _upstream

	STATE_RUNNING = _upstream.STATE_RUNNING
	STATE_COMPLETED = _upstream.STATE_COMPLETED
	STATE_PARTIAL = _upstream.STATE_PARTIAL
	STATE_ERROR = _upstream.STATE_ERROR
	MAX_ATTEMPTS = _upstream.MAX_ATTEMPTS
	BACKOFF_SECONDS = _upstream.BACKOFF_SECONDS
	STALE_AFTER_SECONDS = _upstream.STALE_AFTER_SECONDS
	SWEEP_EVERY_SECONDS = _upstream.SWEEP_EVERY_SECONDS
	UPSTREAM_AVAILABLE = True
except Exception:  # frappe yok — test/CI yolu
	_upstream = None
	STATE_RUNNING = _MIRROR["STATE_RUNNING"]
	STATE_COMPLETED = _MIRROR["STATE_COMPLETED"]
	STATE_PARTIAL = _MIRROR["STATE_PARTIAL"]
	STATE_ERROR = _MIRROR["STATE_ERROR"]
	MAX_ATTEMPTS = _MIRROR["MAX_ATTEMPTS"]
	BACKOFF_SECONDS = _MIRROR["BACKOFF_SECONDS"]
	STALE_AFTER_SECONDS = _MIRROR["STALE_AFTER_SECONDS"]
	SWEEP_EVERY_SECONDS = _MIRROR["SWEEP_EVERY_SECONDS"]
	UPSTREAM_AVAILABLE = False

TERMINAL_STATES: frozenset[str] = frozenset({STATE_COMPLETED, STATE_PARTIAL, STATE_ERROR})


def backoff_seconds(attempt: int) -> int:
	"""`attempt` numaralı başarısız denemeden sonra beklenecek süre.

	Üretim modülü varsa ONA delege eder; politika iki yerde durmaz.
	"""
	if _upstream is not None:
		return int(_upstream.backoff_seconds(attempt))
	if attempt < 1:
		return BACKOFF_SECONDS[0]
	return BACKOFF_SECONDS[min(attempt, len(BACKOFF_SECONDS)) - 1]


# ── İş türleri ──────────────────────────────────────────────────────────
#
# Alım hattının adımlarıyla birebir: her adım ayrı kuyruk işi, ayrı idempotency
# anahtarı. `core/state.py` INGEST_* geçişleri bu işlerin tamamlanmasıyla olur.
JOB_SCAN: str = "media.scan"
JOB_EVALUATE: str = "media.evaluate"
JOB_MASTER: str = "media.master"
JOB_DERIVE: str = "media.derive"
JOB_TRANSCODE: str = "media.transcode"

JOB_KINDS: tuple[str, ...] = (JOB_SCAN, JOB_EVALUATE, JOB_MASTER, JOB_DERIVE, JOB_TRANSCODE)


def idempotency_key(kind: str, target: str, content_hash: str = "", params: dict | None = None) -> str:
	"""İşin kimliği — aynı iş iki kez kuyruğa girerse aynı anahtarı üretir.

	`content_hash` verilirse `target` (dosya yolu / File adı) anahtara GİRMEZ:
	aynı içerik farklı adla iki kez yüklenirse iş bir kez yapılmalıdır.
	`naming.py` zaten sha256 içerik-adresli adlandırma yaptığı için bu, disk
	yerleşimiyle de tutarlıdır. `content_hash` yoksa `target`e düşülür.
	"""
	if kind not in JOB_KINDS:
		raise ValueError(f"Bilinmeyen iş türü: {kind!r}")
	kimlik = content_hash or target
	if not kimlik:
		raise ValueError("idempotency_key: content_hash ya da target zorunlu")
	gövde = json.dumps(params or {}, sort_keys=True, ensure_ascii=False, default=str)
	ham = f"{kind}\x1f{kimlik}\x1f{gövde}".encode()
	return hashlib.sha256(ham).hexdigest()[:32]


@dataclass(frozen=True)
class JobEnvelope:
	"""Kuyruğa giren işin zarfı — taşıma katmanından bağımsız.

	`payload` işin girdisidir; `key` ondan türer ve zarf oluşturulurken
	hesaplanır, çağıranın elle vermesi gerekmez.
	"""

	kind: str
	target: str
	key: str
	content_hash: str = ""
	params: dict = field(default_factory=dict)
	slot: str = ""
	attempt: int = 0
	state: str = STATE_RUNNING
	created_at: float = 0.0

	@classmethod
	def build(
		cls,
		kind: str,
		target: str,
		*,
		content_hash: str = "",
		params: dict | None = None,
		slot: str = "",
		attempt: int = 0,
	) -> "JobEnvelope":
		params = dict(params or {})
		return cls(
			kind=kind,
			target=target,
			key=idempotency_key(kind, target, content_hash, params),
			content_hash=content_hash,
			params=params,
			slot=slot,
			attempt=attempt,
			created_at=time.time(),
		)

	@property
	def exhausted(self) -> bool:
		"""Deneme hakkı bitti mi — politika `MAX_ATTEMPTS`'ten gelir."""
		return self.attempt >= MAX_ATTEMPTS

	def next_attempt_after(self) -> int:
		"""Bu başarısızlıktan sonra kaç saniye beklenecek."""
		return backoff_seconds(self.attempt)

	def retry(self) -> "JobEnvelope":
		"""Bir sonraki denemenin zarfı. Anahtar AYNI kalır — kilit de aynı."""
		from dataclasses import replace

		return replace(self, attempt=self.attempt + 1, state=STATE_RUNNING)

	def to_dict(self) -> dict:
		return {
			"kind": self.kind,
			"target": self.target,
			"key": self.key,
			"content_hash": self.content_hash,
			"params": self.params,
			"slot": self.slot,
			"attempt": self.attempt,
			"state": self.state,
			"created_at": self.created_at,
		}


@dataclass(frozen=True)
class ClaimResult:
	"""`claim()` çıktısı.

	    granted=True                işi SEN yapacaksın
	    granted=False, running=True  başkası yapıyor — bekle, kuyruğa ekleme
	    granted=False, result!=None  zaten yapıldı — sonucu kullan
	"""

	granted: bool
	key: str
	running: bool = False
	result: Any = None
	state: str = ""

	def to_dict(self) -> dict:
		return {
			"granted": self.granted,
			"key": self.key,
			"running": self.running,
			"result": self.result,
			"state": self.state,
		}


class IdempotencyGuard(Protocol):
	"""Taşıma katmanından bağımsız arayüz — Redis karşılığı bunu uygular."""

	def claim(self, envelope: JobEnvelope) -> ClaimResult: ...

	def complete(self, envelope: JobEnvelope, result: Any = None, state: str = STATE_COMPLETED) -> None: ...

	def fail(self, envelope: JobEnvelope, reason: str = "") -> None: ...

	def forget(self, key: str) -> None: ...


@dataclass
class _Entry:
	state: str
	expires_at: float
	result: Any = None
	attempt: int = 0
	reason: str = ""


class InMemoryGuard:
	"""Referans uygulama — süreç içi. Testler ve tek-worker koşum için.

	İki ayrı TTL var ve ikisi farklı soruyu cevaplıyor:

	    lock_ttl    "çalışıyor" kilidinin ömrü. `STALE_AFTER_SECONDS` ile aynı
	                varsayılan: worker düşerse kilit o süre sonunda kendiliğinden
	                açılır, yoksa dosya sonsuza kadar kilitli kalır.
	    result_ttl  biten sonucun saklanma süresi. Bunun içinde aynı anahtarla
	                gelen ikinci istek işi tekrarlamaz, sonucu alır.

	Kilidin süresi dolmuşsa `claim()` YENİDEN VERİR — bu, süpürücünün
	(`jobs.is_stale`) yaptığı işin kilit tarafındaki karşılığıdır.
	"""

	def __init__(
		self,
		*,
		lock_ttl: int = STALE_AFTER_SECONDS,
		result_ttl: int = 24 * 3600,
		clock=time.time,
	) -> None:
		self.lock_ttl = lock_ttl
		self.result_ttl = result_ttl
		self._clock = clock
		self._store: dict[str, _Entry] = {}

	def _now(self) -> float:
		return float(self._clock())

	def _purge(self) -> None:
		simdi = self._now()
		for k in [k for k, v in self._store.items() if v.expires_at <= simdi]:
			del self._store[k]

	def claim(self, envelope: JobEnvelope) -> ClaimResult:
		self._purge()
		mevcut = self._store.get(envelope.key)
		if mevcut is not None:
			if mevcut.state == STATE_RUNNING:
				return ClaimResult(False, envelope.key, running=True, state=STATE_RUNNING)
			if mevcut.state in TERMINAL_STATES:
				# `error` sonucu KİLİT DEĞİLDİR: hata tekrar denenebilir olmalı.
				if mevcut.state == STATE_ERROR and envelope.attempt < MAX_ATTEMPTS:
					self._store[envelope.key] = _Entry(
						STATE_RUNNING, self._now() + self.lock_ttl, attempt=envelope.attempt
					)
					return ClaimResult(True, envelope.key, state=STATE_RUNNING)
				return ClaimResult(
					False, envelope.key, running=False, result=mevcut.result, state=mevcut.state
				)
		self._store[envelope.key] = _Entry(
			STATE_RUNNING, self._now() + self.lock_ttl, attempt=envelope.attempt
		)
		return ClaimResult(True, envelope.key, state=STATE_RUNNING)

	def complete(
		self, envelope: JobEnvelope, result: Any = None, state: str = STATE_COMPLETED
	) -> None:
		if state not in TERMINAL_STATES:
			raise ValueError(f"complete() terminal durum ister, verilen: {state!r}")
		self._store[envelope.key] = _Entry(
			state, self._now() + self.result_ttl, result=result, attempt=envelope.attempt
		)

	def fail(self, envelope: JobEnvelope, reason: str = "") -> None:
		"""Kilidi bırak, denemeyi kaydet.

		Sonuç TTL'i DEĞİL kilit TTL'i kullanılır: başarısız bir iş sonucu 24
		saat saklanacak bir şey değil; backoff dolunca yeniden denenmeli.
		"""
		self._store[envelope.key] = _Entry(
			STATE_ERROR,
			self._now() + backoff_seconds(max(1, envelope.attempt)),
			attempt=envelope.attempt,
			reason=reason,
		)

	def forget(self, key: str) -> None:
		self._store.pop(key, None)

	def state_of(self, key: str) -> str:
		self._purge()
		e = self._store.get(key)
		return e.state if e else ""

	def __len__(self) -> int:
		self._purge()
		return len(self._store)
