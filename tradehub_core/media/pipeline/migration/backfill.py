"""T-143 — toplu yeniden işleme (backfill) orkestratörü.

NE YAPAR
--------
`docs/plans/migration.md` planını KODA çevirir. Plandaki dört karar bire bir
buraya taşındı; hiçbiri yeniden tasarlanmadı:

    §4.2  batch boyutu 200          → `BackfillConfig.batch_size`
    §5.2  ayrı, DÜŞÜK öncelikli kuyruk → `BackfillConfig.queue`
    §5.3  canlı kuyruk derinliği 0 değilse enqueue ETME → `LiveTrafficGuard`
    §7.1  hata oranı > %2 → DUR      → `StopPolicy.error_rate_max`
    §7.3  ikincil eşikler (file_missing / decode_failed > %1) ve
          `state="not_found"`'un "geçti" SAYILMAMASI → `StopPolicy`

NE YAPMAZ
---------
- Dosya seçmez, sınıflandırmaz, ölçmez. Onu `scripts/plan_backfill.py`
  (T-028 çıktısı, SALT OKUNUR) yapar ve JSON plan üretir. Orkestratör o planı
  girdi olarak alır (`BackfillPlan.from_plan_json`).
- `engine.optimize`, `archive.store`, `runner.run_batch` YAZMAZ — çağırır.
- Frappe'ye modül düzeyinde bağlanmaz. Üretim adaptörü (`FrappeBatchRunner`)
  `frappe`'yi çağrı anında import eder.

DURDURMA KRİTERİ — NEDEN BATCH GRANÜLARİTESİNDE
-----------------------------------------------
`migration.md` §7.2 ölçtü: `runner.run_batch` hata oranını izliyor ama batch
ORTASINDA abort etmiyor. Yani en kötü durumda eşik aşılsa bile bir batch
dolusu (N=200) dosya işlenir. Bu bir kabul değil, ölçülmüş bir sınırdır ve
N'in küçük tutulmasının ikinci gerekçesidir. Orkestratör bu sınırı gizlemez:
`StopDecision.already_processed` alanı, durdurma anında kaç dosyanın işlenmiş
olduğunu taşır.

ATOMİK GEÇİŞ
------------
Kaynak doküman T-143 "yeni türevlere geçiş atomik" istiyor; `migration.md`
§4.6.1 ise M-A (içerik standardizasyonu) için ayrı dizin + atomik geçiş
desenini GEREKÇESİYLE reddediyor: `file_url` değişirse ~2.400 referans kırılır.
Çelişki şöyle çözülür ve `AtomicSwitch` tam olarak bunu uygular:

    ORİJİNAL dosya   → yerinde güncellenir, adres DEĞİŞMEZ (mevcut `archive` +
                       `runner` yolu; orkestratör buna dokunmaz)
    TÜREVLER         → yeni adreslerde (`version_hash` taşıyan) hazırlanır ve
                       hepsi hazır olana kadar YAYINA GİRMEZ. Geçiş tek bir
                       işaretçi atamasıdır.

`AtomicSwitch` okuma tarafına ASLA yarım küme göstermez: `active(asset)` ya
tamamen eski kümeyi ya tamamen yeni kümeyi döndürür. Testi eş zamanlı okuma
ile yapılır (`tests/test_migration_backfill.py::AtomikGecisTesti`).

KOŞUM (kuru)
------------
    from tradehub_core.media.pipeline.migration import backfill
    plan = backfill.BackfillPlan.from_plan_json(json.load(open("plan.json")))
    orch = backfill.BackfillOrchestrator(runner=..., config=backfill.BackfillConfig())
    rapor = orch.run(plan, dry_run=True)
    print(rapor.to_dict())
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple

# ── Sabitler: KAYNAK docs/plans/migration.md ────────────────────────────

#: §4.2 — 3600 s'lik iş timeout'unda dosya başına 18 s bütçe bırakır.
DEFAULT_BATCH_SIZE: int = 200

#: §7.1 — `errors / processed`. `skipped` HATA DEĞİLDİR (runner.py:76-79).
DEFAULT_ERROR_RATE_MAX: float = 0.02

#: §7.3 — ikincil eşikler. Aşılırsa sebep hata değil, ORTAM bozukluğudur.
DEFAULT_SKIP_REASON_MAX: float = 0.01
WATCHED_SKIP_REASONS: Tuple[str, ...] = ("file_missing", "decode_failed")

#: §5.2 — canlı yollar `long` kuyruğunda; backfill AYRI kuyruğa alınır.
DEFAULT_QUEUE: str = "media_backfill"
DEFAULT_LIVE_QUEUE: str = "long"

#: §5.3 — canlı kuyrukta bekleyen iş varsa backfill batch'i enqueue EDİLMEZ.
DEFAULT_LIVE_DEPTH_MAX: int = 0

#: `presets.py:28` PROGRESS_TTL. Bu süre içinde okunmayan ilerleme kaydı
#: kaybolur ve hata oranı ÖLÇÜLEMEZ hâle gelir → §7.3 gereği durulur.
PROGRESS_TTL_SECONDS: int = 3600

# ── Durumlar ────────────────────────────────────────────────────────────

RUN_PENDING: str = "pending"
RUN_RUNNING: str = "running"
RUN_PAUSED: str = "paused"
RUN_HALTED: str = "halted"
RUN_COMPLETED: str = "completed"

#: `runner.read_progress` sözlüğünün terminal değerleri.
JOB_COMPLETED: str = "completed"
JOB_PARTIAL: str = "partial"
JOB_RUNNING: str = "running"
JOB_NOT_FOUND: str = "not_found"
JOB_TERMINAL: frozenset = frozenset({JOB_COMPLETED, JOB_PARTIAL})

# ── Durdurma kodları ────────────────────────────────────────────────────

STOP_ERROR_RATE: str = "error_rate_exceeded"
STOP_SKIP_REASON: str = "skip_reason_anomaly"
STOP_PROGRESS_LOST: str = "progress_not_found"
STOP_JOB_STUCK: str = "job_not_terminal"
STOP_NONE: str = ""


class BackfillError(RuntimeError):
	"""Orkestratörün kendi hatası (plan bozuk, port sözleşmesi ihlali)."""


# ═══════════════════════════════════════════════════════════════════════
# 1. Portlar
# ═══════════════════════════════════════════════════════════════════════


class BatchRunner(Protocol):
	"""Toplu işleyici. Üretimde `tradehub_core/media/runner.run_batch`'e bakar."""

	def enqueue(self, file_names: Sequence[str], *, job_key: str, queue: str, dry_run: bool) -> str:
		"""İşi kuyruğa koy, `job_key` döndür."""
		...

	def progress(self, job_key: str) -> Mapping[str, Any]:
		"""`runner.read_progress(job_key)` sözlüğü.

		Beklenen alanlar: `state`, `processed`, `optimized`, `skipped`,
		`errors`, `skip_reasons`. TTL dolmuşsa `state="not_found"`.
		"""
		...


class QueueDepthProbe(Protocol):
	"""Canlı kuyruk derinliği okuyucu (`§5.3` ön kontrolü)."""

	def depth(self, queue: str) -> int: ...


class NotificationSink(Protocol):
	"""Satıcı bildirimi hedefi (panel bildirimi / e-posta kuyruğu)."""

	def notify(self, notice: "SellerNotice") -> None: ...


# ═══════════════════════════════════════════════════════════════════════
# 2. Plan
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class Batch:
	"""Tek bir kuyruk işi. `index` 1'den başlar (operatör runbook'u okunabilsin)."""

	index: int
	file_names: Tuple[str, ...]

	@property
	def size(self) -> int:
		return len(self.file_names)

	@property
	def job_key(self) -> str:
		return f"backfill-{self.index:04d}"


@dataclass
class BackfillPlan:
	"""`scripts/plan_backfill.py` çıktısının orkestratörün anladığı hâli.

	`a_class` = otomatik düzeltilebilir (işlenecek) dosyalar.
	`b_class` = satıcı eylemi gerekenler; İŞLENMEZ, yalnız bildirilir.
	`slot_of` = dosya → slot eşlemesi (pano kırılımı için; eksik olabilir).
	"""

	a_class: Tuple[str, ...] = ()
	b_class: Tuple[Mapping[str, Any], ...] = ()
	slot_of: Mapping[str, str] = field(default_factory=dict)
	source: str = ""

	@classmethod
	def from_plan_json(cls, data: Mapping[str, Any]) -> "BackfillPlan":
		"""`plan_backfill.py`'nin JSON çıktısını oku. Eksik alan HATA verir."""
		if not isinstance(data, Mapping):
			raise BackfillError("plan JSON'u sözlük değil")
		kayitlar = data.get("kayitlar") or data.get("records") or []
		a: List[str] = []
		b: List[Mapping[str, Any]] = []
		slot: Dict[str, str] = {}
		for satir in kayitlar:
			ad = str(satir.get("file_name") or satir.get("name") or "").strip()
			if not ad:
				continue
			sinif = str(satir.get("sinif") or satir.get("class") or "").upper()
			slotlar = satir.get("slots") or []
			if slotlar:
				slot[ad] = str(slotlar[0])
			if sinif.startswith("A"):
				a.append(ad)
			elif sinif.startswith("B"):
				b.append(dict(satir))
		return cls(
			a_class=tuple(a),
			b_class=tuple(b),
			slot_of=slot,
			source=str(data.get("kaynak") or data.get("source") or ""),
		)

	def batches(self, size: int = DEFAULT_BATCH_SIZE) -> Tuple[Batch, ...]:
		if size <= 0:
			raise BackfillError(f"batch boyutu pozitif olmalı: {size}")
		out: List[Batch] = []
		for i in range(0, len(self.a_class), size):
			out.append(Batch(index=len(out) + 1, file_names=tuple(self.a_class[i : i + size])))
		return tuple(out)


# ═══════════════════════════════════════════════════════════════════════
# 3. Yapılandırma ve durdurma politikası
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class StopPolicy:
	"""§7 — durdurma kriterleri. Hepsi ORANDIR, mutlak sayı değil."""

	error_rate_max: float = DEFAULT_ERROR_RATE_MAX
	skip_reason_max: float = DEFAULT_SKIP_REASON_MAX
	watched_skip_reasons: Tuple[str, ...] = WATCHED_SKIP_REASONS
	#: `state="not_found"` (TTL doldu) durdurma sebebidir. Kapatılabilir ama
	#: kapatmak "hata oranını ölçemedim ama devam ediyorum" demektir.
	halt_on_progress_lost: bool = True

	def __post_init__(self) -> None:
		if not 0.0 < self.error_rate_max <= 1.0:
			raise BackfillError(f"error_rate_max (0,1] aralığında olmalı: {self.error_rate_max}")
		if not 0.0 < self.skip_reason_max <= 1.0:
			raise BackfillError(f"skip_reason_max (0,1] aralığında olmalı: {self.skip_reason_max}")


@dataclass(frozen=True)
class BackfillConfig:
	batch_size: int = DEFAULT_BATCH_SIZE
	queue: str = DEFAULT_QUEUE
	live_queue: str = DEFAULT_LIVE_QUEUE
	live_depth_max: int = DEFAULT_LIVE_DEPTH_MAX
	stop: StopPolicy = field(default_factory=StopPolicy)
	#: İş bitmesi için en çok kaç yoklama yapılır (yoklama aralığı × bu sayı).
	poll_limit: int = 720
	poll_seconds: float = 5.0
	#: Canlı kuyruk doluyken kaç kez beklenir; aşılırsa koşum DURAKLAR (halt değil).
	pause_limit: int = 60

	def __post_init__(self) -> None:
		if self.batch_size <= 0:
			raise BackfillError("batch_size pozitif olmalı")
		if self.queue == self.live_queue:
			raise BackfillError(
				"backfill kuyruğu canlı kuyrukla AYNI olamaz (§5.2): "
				f"{self.queue!r}. Aynı kuyrukta öncelik ayrımı YOKTUR."
			)


@dataclass(frozen=True)
class StopDecision:
	"""Bir batch sonrası durdurma kararı + gerekçe + ölçülen sayılar."""

	halt: bool
	code: str = STOP_NONE
	reason: str = ""
	measured: Mapping[str, Any] = field(default_factory=dict)
	already_processed: int = 0

	def to_dict(self) -> Dict[str, Any]:
		return {
			"halt": self.halt,
			"code": self.code,
			"reason": self.reason,
			"measured": dict(self.measured),
			"already_processed": self.already_processed,
		}


def error_rate(progress: Mapping[str, Any]) -> float:
	"""§7.1 tanımı: `errors / processed`. `processed=0` → 0,0 (bölme yok)."""
	islenen = int(progress.get("processed") or 0)
	hatali = int(progress.get("errors") or 0)
	return (hatali / islenen) if islenen > 0 else 0.0


def evaluate_stop(progress: Mapping[str, Any], policy: Optional[StopPolicy] = None) -> StopDecision:
	"""Tek bir işin ilerleme kaydına bakıp durup durmayacağına karar ver.

	SIRA ANLAMLIDIR ve §7.3'ten alınmıştır:
	  1. İş terminal mi (`completed`/`partial`)? `not_found` GEÇTİ SAYILMAZ.
	  2. Hata oranı eşiği.
	  3. İkincil skip-sebebi anomalileri.
	"""
	p = policy or StopPolicy()
	durum = str(progress.get("state") or "")
	islenen = int(progress.get("processed") or 0)

	if durum == JOB_NOT_FOUND:
		if p.halt_on_progress_lost:
			return StopDecision(
				halt=True,
				code=STOP_PROGRESS_LOST,
				reason=(
					"İlerleme kaydı yok (TTL doldu). Hata oranı ÖLÇÜLEMEDİ; "
					"§7.3 gereği 'geçti' sayılmaz."
				),
				measured={"state": durum},
			)
		return StopDecision(halt=False, measured={"state": durum})

	if durum not in JOB_TERMINAL:
		return StopDecision(
			halt=True,
			code=STOP_JOB_STUCK,
			reason=f"İş hâlâ terminal değil: state={durum!r}. Sonraki batch enqueue edilmez.",
			measured={"state": durum},
			already_processed=islenen,
		)

	oran = error_rate(progress)
	if oran > p.error_rate_max:
		return StopDecision(
			halt=True,
			code=STOP_ERROR_RATE,
			reason=(
				f"Hata oranı %{oran * 100:.2f} > %{p.error_rate_max * 100:.2f} — "
				"kalan batch'ler enqueue EDİLMEZ."
			),
			measured={"error_rate": oran, "errors": int(progress.get("errors") or 0), "processed": islenen},
			already_processed=islenen,
		)

	sebepler = dict(progress.get("skip_reasons") or {})
	for ad in p.watched_skip_reasons:
		sayi = int(sebepler.get(ad) or 0)
		if islenen > 0 and sayi / islenen > p.skip_reason_max:
			return StopDecision(
				halt=True,
				code=STOP_SKIP_REASON,
				reason=(
					f"{ad} oranı %{sayi / islenen * 100:.2f} > "
					f"%{p.skip_reason_max * 100:.2f} — disk/DB ayrışması ya da bozulma."
				),
				measured={"skip_reason": ad, "count": sayi, "processed": islenen},
				already_processed=islenen,
			)

	return StopDecision(
		halt=False,
		measured={"error_rate": oran, "processed": islenen},
		already_processed=islenen,
	)


# ═══════════════════════════════════════════════════════════════════════
# 4. Canlı trafik koruması
# ═══════════════════════════════════════════════════════════════════════


class LiveTrafficGuard:
	"""§5.3 — canlı kuyrukta iş varken backfill batch'i enqueue EDİLMEZ.

	Prob verilmezse kapı AÇIK sayılır ve bu durum raporda `unmeasured` olarak
	işaretlenir — "ölçemedim" ile "temiz" karıştırılmaz.
	"""

	def __init__(self, probe: Optional[QueueDepthProbe], queue: str, max_depth: int) -> None:
		self._probe = probe
		self._queue = queue
		self._max = max_depth
		self.checks: List[Dict[str, Any]] = []

	@property
	def measurable(self) -> bool:
		return self._probe is not None

	def clear(self) -> bool:
		"""Şu an enqueue edilebilir mi?"""
		if self._probe is None:
			self.checks.append({"queue": self._queue, "depth": None, "clear": True, "measured": False})
			return True
		try:
			derinlik = int(self._probe.depth(self._queue))
		except Exception as hata:  # noqa: BLE001 — ölçüm patlarsa DURAKLA, devam etme
			self.checks.append(
				{"queue": self._queue, "depth": None, "clear": False, "error": repr(hata)}
			)
			return False
		acik = derinlik <= self._max
		self.checks.append(
			{"queue": self._queue, "depth": derinlik, "clear": acik, "measured": True}
		)
		return acik


# ═══════════════════════════════════════════════════════════════════════
# 5. Atomik geçiş
# ═══════════════════════════════════════════════════════════════════════


class AtomicSwitch:
	"""Türev kümesinin yayına alınması: ya hepsi ya hiçbiri.

	Okuma tarafı yalnız `active(asset)` görür. `stage()` yeni kümeyi HAZIRLIK
	rafına koyar — yayına hiçbir etkisi yoktur. `commit()` tek bir sözlük
	ataması yapar; o atamadan önce okuyan eski kümenin TAMAMINI, sonra okuyan
	yeni kümenin TAMAMINI görür. Yarım küme hiçbir anda görünmez ve bu 404'ün
	tek yapısal sebebidir.

	CPython'da `dict.__setitem__` GIL altında atomiktir; küme değiştirmek
	yerine YENİ bir demet atamak bilinçli tercihtir (yerinde mutasyon yarım
	durum üretirdi).
	"""

	def __init__(self) -> None:
		self._live: Dict[str, Tuple[str, ...]] = {}
		self._staged: Dict[str, Tuple[str, ...]] = {}
		self.commits: int = 0
		self.rollbacks: int = 0

	def publish_initial(self, asset: str, urls: Iterable[str]) -> None:
		"""Geçiş öncesi mevcut (eski) türev kümesi."""
		self._live[asset] = tuple(urls)

	def stage(self, asset: str, urls: Iterable[str]) -> None:
		yeni = tuple(urls)
		if not yeni:
			raise BackfillError(f"{asset}: boş türev kümesi rafa konamaz (kısmi merdiven = 404)")
		self._staged[asset] = yeni

	def staged(self, asset: str) -> Tuple[str, ...]:
		return self._staged.get(asset, ())

	def active(self, asset: str) -> Tuple[str, ...]:
		"""Okuma tarafının gördüğü küme. Her zaman TAM."""
		return self._live.get(asset, ())

	def ready(self, asset: str, expected: int) -> bool:
		"""Beklenen basamak sayısı hazırlandı mı — commit ön koşulu."""
		return len(self._staged.get(asset, ())) == expected

	def commit(self, asset: str, *, expected: Optional[int] = None) -> Tuple[str, ...]:
		yeni = self._staged.get(asset)
		if not yeni:
			raise BackfillError(f"{asset}: rafta küme yok, commit edilemez")
		if expected is not None and len(yeni) != expected:
			raise BackfillError(
				f"{asset}: rafta {len(yeni)} türev var, {expected} bekleniyordu — "
				"eksik merdiven yayına alınmaz"
			)
		self._live[asset] = yeni          # ← tek atama: geçiş anı
		del self._staged[asset]
		self.commits += 1
		return yeni

	def rollback(self, asset: str) -> None:
		"""Rafı boşalt. Yayındaki kümeye DOKUNMAZ — zaten hiç değişmedi."""
		if self._staged.pop(asset, None) is not None:
			self.rollbacks += 1


# ═══════════════════════════════════════════════════════════════════════
# 6. Satıcı bildirimi
# ═══════════════════════════════════════════════════════════════════════

#: `migration.md` §6.2 — B alt sınıfı → satıcıya gösterilen sebep.
B_CLASS_MESSAGES: Dict[str, str] = {
	"B1": "Çözünürlük yetersiz — büyütme görüntüyü bozar",
	"B2": "Görsel daha önce küçültüldü, orijinali artık yok",
	"B3": "Kare olmayan görsel kenarlardan kırpılıyor",
	"B4": "Bu alan için iki ayrı görsel gerekiyor (geniş + dar)",
	"B5": "Dosya açılamıyor / bozuk",
	"B6": "Dosya boş (0 bayt)",
}

#: §6.4 — rozet penceresi, arşiv retention'ıyla aynı: 30 gün.
DEFAULT_NOTICE_DAYS: int = 30


@dataclass(frozen=True)
class SellerNotice:
	store: str
	file_name: str
	slot: str
	subclass: str
	message: str
	deadline_days: int = DEFAULT_NOTICE_DAYS

	def to_dict(self) -> Dict[str, Any]:
		return {
			"store": self.store,
			"file_name": self.file_name,
			"slot": self.slot,
			"subclass": self.subclass,
			"message": self.message,
			"deadline_days": self.deadline_days,
		}


def build_notices(
	plan: BackfillPlan, *, deadline_days: int = DEFAULT_NOTICE_DAYS
) -> Tuple[SellerNotice, ...]:
	"""B sınıfı dosyalardan satıcı bildirimleri üret.

	A sınıfı için bildirim YAPILMAZ (§6.1): dosya sunucuda düzelir, `file_url`
	değişmez, satıcının yapacağı bir şey yoktur. Sahibi çözülemeyen dosya
	bildirilmez ama SAYILIR — sessizce düşmesin diye `store=""` ile döner.
	"""
	out: List[SellerNotice] = []
	for satir in plan.b_class:
		ad = str(satir.get("file_name") or satir.get("name") or "")
		alt = str(satir.get("alt_sinif") or satir.get("subclass") or "").upper()
		out.append(
			SellerNotice(
				store=str(satir.get("store") or ""),
				file_name=ad,
				slot=str(plan.slot_of.get(ad, "") or satir.get("slot") or ""),
				subclass=alt,
				message=B_CLASS_MESSAGES.get(alt, "Bu görsel yeni görüntü standardını karşılamıyor"),
				deadline_days=deadline_days,
			)
		)
	return tuple(out)


# ═══════════════════════════════════════════════════════════════════════
# 7. Pano ve rapor
# ═══════════════════════════════════════════════════════════════════════


@dataclass
class BatchOutcome:
	batch: Batch
	job_key: str
	progress: Mapping[str, Any]
	decision: StopDecision
	seconds: float
	enqueued: bool = True

	def to_dict(self) -> Dict[str, Any]:
		return {
			"batch": self.batch.index,
			"size": self.batch.size,
			"job_key": self.job_key,
			"enqueued": self.enqueued,
			"seconds": round(self.seconds, 3),
			"progress": dict(self.progress),
			"decision": self.decision.to_dict(),
		}


@dataclass
class BackfillReport:
	"""Koşumun tamamı. Pano bu sözlükten beslenir."""

	state: str = RUN_PENDING
	planned_files: int = 0
	planned_batches: int = 0
	outcomes: List[BatchOutcome] = field(default_factory=list)
	stop: Optional[StopDecision] = None
	notices: Tuple[SellerNotice, ...] = ()
	dry_run: bool = True
	live_checks: List[Dict[str, Any]] = field(default_factory=list)
	started_at: float = 0.0
	finished_at: float = 0.0

	# ── türetilmiş sayılar ─────────────────────────────────────────────

	@property
	def processed(self) -> int:
		return sum(int(o.progress.get("processed") or 0) for o in self.outcomes)

	@property
	def optimized(self) -> int:
		return sum(int(o.progress.get("optimized") or 0) for o in self.outcomes)

	@property
	def skipped(self) -> int:
		return sum(int(o.progress.get("skipped") or 0) for o in self.outcomes)

	@property
	def errors(self) -> int:
		return sum(int(o.progress.get("errors") or 0) for o in self.outcomes)

	@property
	def error_rate(self) -> float:
		return (self.errors / self.processed) if self.processed else 0.0

	@property
	def batches_done(self) -> int:
		return sum(1 for o in self.outcomes if o.enqueued)

	@property
	def avg_seconds_per_file(self) -> Optional[float]:
		"""ÖLÇÜLMEDİYSE `None` döner — sıfır DEĞİL."""
		sure = sum(o.seconds for o in self.outcomes if o.enqueued)
		return (sure / self.processed) if (self.processed and sure > 0) else None

	def eta_seconds(self) -> Optional[float]:
		"""Kalan süre tahmini. Ölçüm yoksa `None`."""
		hiz = self.avg_seconds_per_file
		if hiz is None:
			return None
		kalan = max(self.planned_files - self.processed, 0)
		return kalan * hiz

	def per_slot(self, plan: BackfillPlan) -> Dict[str, int]:
		"""Pano kırılımı: işlenen dosyaların slot dağılımı."""
		sayac: Dict[str, int] = {}
		for o in self.outcomes:
			if not o.enqueued:
				continue
			for ad in o.batch.file_names:
				anahtar = plan.slot_of.get(ad, "slotsuz")
				sayac[anahtar] = sayac.get(anahtar, 0) + 1
		return sayac

	def to_dict(self) -> Dict[str, Any]:
		return {
			"state": self.state,
			"dry_run": self.dry_run,
			"planned_files": self.planned_files,
			"planned_batches": self.planned_batches,
			"batches_done": self.batches_done,
			"processed": self.processed,
			"optimized": self.optimized,
			"skipped": self.skipped,
			"errors": self.errors,
			"error_rate": round(self.error_rate, 6),
			"avg_seconds_per_file": self.avg_seconds_per_file,
			"eta_seconds": self.eta_seconds(),
			"stop": self.stop.to_dict() if self.stop else None,
			"notices": len(self.notices),
			"live_checks": list(self.live_checks),
			"batches": [o.to_dict() for o in self.outcomes],
			"elapsed_seconds": round(max(self.finished_at - self.started_at, 0.0), 3),
		}


# ═══════════════════════════════════════════════════════════════════════
# 8. Orkestratör
# ═══════════════════════════════════════════════════════════════════════


class BackfillOrchestrator:
	"""Batch'leri kesen, aralarda ölçen, eşik aşılınca DURAN katman."""

	def __init__(
		self,
		runner: BatchRunner,
		*,
		config: Optional[BackfillConfig] = None,
		queue_probe: Optional[QueueDepthProbe] = None,
		notifier: Optional[NotificationSink] = None,
		clock: Optional[Callable[[], float]] = None,
		sleep: Optional[Callable[[float], None]] = None,
	) -> None:
		self.runner = runner
		self.config = config or BackfillConfig()
		self.notifier = notifier
		self._clock = clock or time.time
		self._sleep = sleep or time.sleep
		self.guard = LiveTrafficGuard(
			queue_probe, self.config.live_queue, self.config.live_depth_max
		)

	# ── tek batch ──────────────────────────────────────────────────────

	def _await_job(self, job_key: str) -> Mapping[str, Any]:
		"""İş terminal olana kadar yokla. Limit aşılırsa SON okumayı döndür.

		Son okumayı döndürmek bilinçli: `evaluate_stop` `state != terminal`
		durumunu zaten `STOP_JOB_STUCK` ile durduruyor. Burada istisna atmak
		aynı bilgiyi kaybettirirdi.
		"""
		son: Mapping[str, Any] = {"state": JOB_RUNNING}
		for _ in range(max(self.config.poll_limit, 1)):
			son = self.runner.progress(job_key)
			if str(son.get("state") or "") in JOB_TERMINAL or str(son.get("state")) == JOB_NOT_FOUND:
				return son
			self._sleep(self.config.poll_seconds)
		return son

	def run_batch(self, batch: Batch, *, dry_run: bool) -> BatchOutcome:
		"""Tek batch: enqueue → bekle → ölç → karar."""
		basla = self._clock()
		job_key = self.runner.enqueue(
			batch.file_names, job_key=batch.job_key, queue=self.config.queue, dry_run=dry_run
		)
		ilerleme = self._await_job(job_key or batch.job_key)
		karar = evaluate_stop(ilerleme, self.config.stop)
		return BatchOutcome(
			batch=batch,
			job_key=job_key or batch.job_key,
			progress=dict(ilerleme),
			decision=karar,
			seconds=self._clock() - basla,
		)

	# ── tam koşum ──────────────────────────────────────────────────────

	def run(
		self,
		plan: BackfillPlan,
		*,
		dry_run: bool = True,
		max_batches: Optional[int] = None,
		notify: bool = False,
	) -> BackfillReport:
		"""Planı batch batch koştur.

		`dry_run=True` VARSAYILANDIR: yanlışlıkla üretim koşumu başlatmak,
		yanlışlıkla kuru koşum yapmaktan pahalıdır.
		"""
		batchler = plan.batches(self.config.batch_size)
		if max_batches is not None:
			batchler = batchler[: max(max_batches, 0)]

		rapor = BackfillReport(
			state=RUN_RUNNING,
			planned_files=len(plan.a_class),
			planned_batches=len(plan.batches(self.config.batch_size)),
			dry_run=dry_run,
			notices=build_notices(plan),
			started_at=self._clock(),
		)

		for batch in batchler:
			if not self._wait_for_live_queue(rapor):
				rapor.state = RUN_PAUSED
				rapor.finished_at = self._clock()
				return rapor

			sonuc = self.run_batch(batch, dry_run=dry_run)
			rapor.outcomes.append(sonuc)

			if sonuc.decision.halt:
				rapor.state = RUN_HALTED
				rapor.stop = sonuc.decision
				break
		else:
			rapor.state = RUN_COMPLETED

		rapor.live_checks = list(self.guard.checks)
		rapor.finished_at = self._clock()

		if notify and rapor.notices:
			self._send(rapor.notices)
		return rapor

	def _wait_for_live_queue(self, rapor: BackfillReport) -> bool:
		"""Canlı kuyruk boşalana kadar bekle. Limit aşılırsa `False`."""
		for _ in range(max(self.config.pause_limit, 1)):
			if self.guard.clear():
				return True
			self._sleep(self.config.poll_seconds)
		rapor.live_checks = list(self.guard.checks)
		return False

	def _send(self, notices: Sequence[SellerNotice]) -> None:
		if self.notifier is None:
			return
		for n in notices:
			self.notifier.notify(n)

	# ── pano ───────────────────────────────────────────────────────────

	def dashboard(self, rapor: BackfillReport, plan: BackfillPlan) -> Dict[str, Any]:
		"""T-143 kabul kriterinin panosu: ilerleme, hata oranı, tahmini bitiş."""
		gorunum = rapor.to_dict()
		gorunum["per_slot"] = rapor.per_slot(plan)
		gorunum["remaining_files"] = max(rapor.planned_files - rapor.processed, 0)
		gorunum["percent_done"] = (
			round(100.0 * rapor.processed / rapor.planned_files, 2) if rapor.planned_files else 0.0
		)
		gorunum["error_rate_threshold"] = self.config.stop.error_rate_max
		gorunum["live_queue_measured"] = self.guard.measurable
		gorunum["b_class_files"] = len(plan.b_class)
		return gorunum


# ═══════════════════════════════════════════════════════════════════════
# 9. Üretim adaptörü — `frappe` YALNIZ çağrı anında import edilir
# ═══════════════════════════════════════════════════════════════════════


class FrappeBatchRunner:
	"""`tradehub_core/media/runner.py` üzerine ince adaptör.

	Bu sınıf ÇALIŞTIRILMADI: bench/site olmadan koşulamaz ve bu oturumda
	backfill üretimde başlatılmadı. Kod yolları `runner.run_batch` ve
	`runner.read_progress` imzalarına göre yazıldı (`migration.md` §4.1'de
	dosya:satır ile kayıtlı). İlk gerçek koşumdan önce `dry_run=True` ile
	doğrulanmalıdır.
	"""

	def __init__(self, preset: str = "balanced", enqueue_fn: Optional[Callable[..., Any]] = None) -> None:
		self.preset = preset
		self._enqueue_fn = enqueue_fn

	def enqueue(self, file_names: Sequence[str], *, job_key: str, queue: str, dry_run: bool) -> str:
		import frappe  # noqa: PLC0415 — bilinçli geç import

		enqueue_fn = self._enqueue_fn or frappe.enqueue
		enqueue_fn(
			"tradehub_core.media.runner.run_batch",
			queue=queue,
			timeout=PROGRESS_TTL_SECONDS,
			file_names=list(file_names),
			preset=self.preset,
			job_key=job_key,
			dry_run=1 if dry_run else 0,
		)
		return job_key

	def progress(self, job_key: str) -> Mapping[str, Any]:
		from tradehub_core.media import runner  # noqa: PLC0415 — bilinçli geç import

		return runner.read_progress(job_key)


class FrappeQueueDepth:
	"""`long` kuyruğunun derinliği. `frappe` çağrı anında import edilir."""

	def depth(self, queue: str) -> int:
		from frappe.utils.background_jobs import get_queue  # noqa: PLC0415

		return int(get_queue(queue).count)


#: B alt sınıfı bildiriminin panel başlığı. `_()` ile SARILAMAZ: bu modül
#: bench/site olmadan import edilebilir kalmalı (KatmanDisiplinTesti) ve `frappe`
#: modül düzeyinde import edilemez. `B_CLASS_MESSAGES` ile aynı gerekçeyle düz
#: Türkçe; Platform Notification/e-posta yerelleştirmesi `notify()` katmanının işi.
NOTICE_TITLE: str = "Medya standardı güncellendi: {0}"

#: Platform Notification `type` alanının izinli değeri (system/listing/…). Medya
#: standardı bildirimi ürün/sipariş değil, sistemsel bir uyarı.
NOTICE_TYPE: str = "system"


class PlatformNotificationSink:
	"""`SellerNotice` → Platform Notification (+ opsiyonel e-posta).

	`backfill.run(..., notify=True)` üretilen B sınıfı bildirimlerini bu sink'e
	verir; sink her birini `utils/notify.py::notify` çağrısına sarar. Böylece
	backfill bir satıcının medyasını standarda uyarladığında satıcı HABER ALIR
	(rapor 98: eskiden somut adaptör yoktu, bildirim sessizce düşüyordu).

	`notice.store` Admin Seller Profile'ın adıdır (`media/ownership.py:79` ile
	AYNI eşleme); sahibi `Admin Seller Profile.user`. Sahibi çözülemeyen bildirim
	(store boş ya da profilsiz) sessizce düşmez, `skipped` olarak SAYILIR.

	`frappe`/`notify` YALNIZ çağrı anında import edilir (FrappeBatchRunner ile
	aynı gerekçe: modül düzeyinde frappe bağı yok). Test için `notify_fn` /
	`resolve_user_fn` enjekte edilebilir — canlı site olmadan doğrulanabilsin.
	"""

	def __init__(
		self,
		*,
		send_email: bool = False,
		notification_type: str = NOTICE_TYPE,
		notify_fn: Optional[Callable[..., Any]] = None,
		resolve_user_fn: Optional[Callable[[str], Optional[str]]] = None,
	) -> None:
		self.send_email = send_email
		self.type = notification_type
		self._notify_fn = notify_fn
		self._resolve_user_fn = resolve_user_fn
		self.sent: int = 0
		self.skipped: int = 0

	def _resolve_user(self, store: str) -> Optional[str]:
		if self._resolve_user_fn is not None:
			return self._resolve_user_fn(store)
		if not store:
			return None
		import frappe  # noqa: PLC0415 — bilinçli geç import

		return frappe.db.get_value("Admin Seller Profile", store, "user")

	def _deliver(self, **kwargs: Any) -> str:
		notify_fn = self._notify_fn
		if notify_fn is None:
			from tradehub_core.utils.notify import notify as notify_fn  # noqa: PLC0415

		return notify_fn(**kwargs) or ""

	def notify(self, notice: "SellerNotice") -> None:
		user = self._resolve_user(notice.store)
		if not user:
			self.skipped += 1
			return
		name = self._deliver(
			recipient_user=user,
			recipient_role="seller",
			type=self.type,
			title=NOTICE_TITLE.format(notice.file_name or notice.store),
			message=notice.message,
			reference_doctype="Admin Seller Profile",
			reference_name=notice.store,
			send_email=self.send_email,
		)
		if name:
			self.sent += 1
		else:
			self.skipped += 1


# ═══════════════════════════════════════════════════════════════════════
# 10. Kapasite aritmetiği (§4.2, §4.4) — ölçümden TAHMİN üretir
# ═══════════════════════════════════════════════════════════════════════


def safe_batch_size(seconds_per_file: float, *, job_timeout: int = PROGRESS_TTL_SECONDS,
                    safety: float = 3.0, cap: int = 2000) -> int:
	"""§10-D1'in formülü: `job_timeout / (dosya_başına_sn × güvenlik)`.

	`safety=3` kuru koşumun `t_arşiv_yaz` ve `t_disk_yaz`'ı ÖLÇMEMESİNDEN
	gelir (plan §10-D1 notu) — ölçüm değil, bilinçli pay.
	"""
	if seconds_per_file <= 0:
		raise BackfillError("dosya başına süre pozitif olmalı — ölçülmediyse batch boyutu türetilemez")
	n = int(math.floor(job_timeout / (seconds_per_file * safety)))
	return max(1, min(n, cap))


def estimate_duration(file_count: int, seconds_per_file: float, *, workers: int = 1) -> float:
	"""Toplam süre tahmini (saniye). `workers` bugün 1'dir (§4.3)."""
	if workers <= 0:
		raise BackfillError("worker sayısı pozitif olmalı")
	return (file_count * seconds_per_file) / workers
