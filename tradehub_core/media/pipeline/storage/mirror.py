"""T-051 — Aynalı depo: yerel BİRİNCİL + S3 asenkron ikincil.

NEDEN AYNA, NEDEN ASENKRON
--------------------------
Ölçülen durum (`docs/standards/retention.md` §5.3): medya dosyalarının tek
kopyası yerel diskte. `tradehub_core/media/backup.py` modül dokümanı bunun
bedelini yazıyor: "Bu oturumda üç kez yaşandı, ikisi kalıcı kayıpla
sonuçlandı."

Ayna, ikinci bir fiziksel kopya ekler. **Asenkron** olması bir tasarım
kararıdır, kolaycılık değil:

  * Yükleme yolu senkron S3'e bağlanırsa, S3'ün gecikmesi (ya da kesintisi)
    kullanıcının yükleme isteğinin gecikmesi olur. Bugün yükleme yerel diske
    yazıyor ve milisaniyeler sürüyor; bunu ağa bağlamak ölçülebilir bir
    gerileme olurdu.
  * Yerel yazma zaten atomiktir ve BİRİNCİL kaynaktır. Ayna gecikirse veri
    kaybı olmaz, yalnız ikinci kopya geç oluşur.

Bunun bedeli açıkça yazılmalı: **ayna kuyruğu boşalana kadar RPO yerel
diskin kendisidir.** Yerel disk aynalama tamamlanmadan ölürse o pencerede
yüklenen dosyalar kaybolur. Sayısal karşılığı `docs/plans/backup-dr.md`.

KUYRUK NE TAŞIR
---------------
Görev nesnesi baytları TAŞIMAZ, yalnız `ObjectRef` taşır; işçi içeriği
birincilden okur. Gerekçe: 500 MB'lık bir videonun baytlarını kuyrukta
tutmak bellek/Redis maliyeti demek ve içerik-adresli depoda gereksiz —
anahtar zaten içeriğin kimliği.

Sonucu: birincilde artık olmayan bir nesnenin ayna görevi "kaynak yok"
diye düşer. Bu doğru davranış (silinen dosya aynalanmaz) ve
`TASK_DROPPED` olarak sayılır, hata olarak değil.

BAŞARISIZLIK ASLA BİRİNCİLİ DÜŞÜRMEZ
------------------------------------
`put()` birincil yazmayı yaptıktan sonra kuyruğa görev bırakır. Kuyruk
dolu, iş parçacığı ölü ya da S3 kapalı olsa bile `put()` BAŞARILI döner.
Aksi hâlde ikincil bir depo, birincil bir tek hata noktası hâline gelirdi.
Düşen görevler `failed_tasks()` ile görünür ve `reconcile()` ile telafi
edilir — sessiz kayıp yok.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Protocol

from tradehub_core.media.pipeline.contracts.errors import MediaEngineError, ObjectNotFound, StorageError
from tradehub_core.media.pipeline.contracts.storage import (
	SCOPE_PUBLIC,
	SCOPES,
	ObjectKey,
	ObjectRef,
	ObjectStat,
	PutResult,
	StorageAdapter,
)
from tradehub_core.media.pipeline.core import jobs as core_jobs

OP_PUT: str = "put"
OP_DELETE: str = "delete"
OP_MOVE: str = "move"

TASK_OK: str = "ok"
TASK_FAILED: str = "failed"
TASK_DROPPED: str = "dropped"

#: Kuyruk üst sınırı. Sınırsız kuyruk, S3 kesintisinde belleği yiyip
#: birincil süreci öldürür — yani tam da korumaya çalıştığımız şeyi bozar.
DEFAULT_QUEUE_SIZE: int = 10_000


@dataclass(frozen=True)
class MirrorTask:
	"""Aynalanacak tek işlem. Baytları TAŞIMAZ."""

	op: str
	ref: ObjectRef
	target_scope: str = ""
	attempt: int = 0
	created_at: float = field(default_factory=time.time)

	def next_attempt(self) -> "MirrorTask":
		return MirrorTask(
			op=self.op,
			ref=self.ref,
			target_scope=self.target_scope,
			attempt=self.attempt + 1,
			created_at=self.created_at,
		)

	def to_dict(self) -> Dict[str, Any]:
		return {
			"op": self.op,
			"url": self.ref.url,
			"scope": self.ref.scope,
			"shard": self.ref.key.shard,
			"name": self.ref.key.name,
			"target_scope": self.target_scope,
			"attempt": self.attempt,
		}


class MirrorQueue(Protocol):
	"""Ayna görevlerini taşıyan kuyruk."""

	def submit(self, task: MirrorTask) -> bool:
		"""Görevi kuyruğa bırak. Kuyruk doluysa `False` — istisna ATMAZ."""
		...

	def drain(self, timeout: Optional[float] = None) -> None:
		"""Kuyruk boşalana kadar bekle (test ve kapanış için)."""
		...

	def close(self) -> None:
		"""Kaynakları bırak."""
		...


class InlineMirrorQueue:
	"""Görevi ANINDA, çağıran iş parçacığında yürütür.

	Testler ve tek seferlik migrasyon betikleri için. Üretimde kullanmak
	`put()`'u S3'e bağlar — modül dokümanındaki gecikme gerekçesini iptal
	eder. Adı bilinçli olarak "inline": "sync" demek, asenkron olanın da
	güvenilir olmadığı izlenimi verirdi.
	"""

	def __init__(self, worker: "MirrorWorker") -> None:
		self._worker = worker

	def submit(self, task: MirrorTask) -> bool:
		self._worker.execute(task)
		return True

	def drain(self, timeout: Optional[float] = None) -> None:
		return None

	def close(self) -> None:
		return None


class ThreadMirrorQueue:
	"""Arka plan iş parçacığı + sınırlı kuyruk.

	Yeniden deneme politikası TEKRARLANMAZ: `tradehub_core/media/pipeline/core/jobs.py`
	üzerinden `tradehub_core/media/jobs.py`'nin `MAX_ATTEMPTS` /
	`BACKOFF_SECONDS` değerleri kullanılır. Testte beklenmesin diye
	`backoff_scale` ile ölçeklenebilir.
	"""

	def __init__(
		self,
		worker: "MirrorWorker",
		*,
		max_size: int = DEFAULT_QUEUE_SIZE,
		backoff_scale: float = 1.0,
		max_attempts: Optional[int] = None,
	) -> None:
		self._worker = worker
		self._queue: "Queue[Optional[MirrorTask]]" = Queue(maxsize=max_size)
		self._backoff_scale = float(backoff_scale)
		self._max_attempts = int(core_jobs.MAX_ATTEMPTS if max_attempts is None else max_attempts)
		self._stop = threading.Event()
		self._thread = threading.Thread(
			target=self._run, name="media-engine-mirror", daemon=True
		)
		self._thread.start()

	def submit(self, task: MirrorTask) -> bool:
		try:
			self._queue.put_nowait(task)
			return True
		except Full:
			# Kuyruk dolu: görev DÜŞER ama birincil yazma etkilenmez.
			# `reconcile()` bu boşluğu kapatmak için var.
			self._worker.record(task, TASK_DROPPED, "queue_full")
			return False

	def _run(self) -> None:  # pragma: no cover - iş parçacığı gövdesi
		while not self._stop.is_set():
			try:
				gorev = self._queue.get(timeout=0.2)
			except Empty:
				continue
			if gorev is None:
				self._queue.task_done()
				break
			try:
				basarili = self._worker.execute(gorev)
				if not basarili and gorev.attempt + 1 < self._max_attempts:
					bekleme = core_jobs.backoff_seconds(gorev.attempt) * self._backoff_scale
					if bekleme > 0:
						self._stop.wait(bekleme)
					self._queue.put(gorev.next_attempt())
			finally:
				self._queue.task_done()

	def drain(self, timeout: Optional[float] = None) -> None:
		"""Kuyruk boşalana kadar bekle. `timeout` saniye sonra vazgeçer."""
		son = None if timeout is None else time.time() + float(timeout)
		while not self._queue.empty():
			if son is not None and time.time() > son:
				return
			time.sleep(0.005)
		# `unfinished_tasks` sıfırlanana kadar da bekle: kuyruk boş ama işçi
		# hâlâ son görevi yürütüyor olabilir.
		while getattr(self._queue, "unfinished_tasks", 0) > 0:
			if son is not None and time.time() > son:
				return
			time.sleep(0.005)

	def close(self) -> None:
		self._stop.set()
		try:
			self._queue.put_nowait(None)
		except Full:
			pass
		self._thread.join(timeout=2.0)


class FrappeEnqueueMirrorQueue:
	"""Üretim kuyruğu — `frappe.enqueue` ile arka plan işçisine bırakır.

	`frappe` import'u fonksiyon içinde ve tembeldir. Görev yükü düz sözlük
	olmak zorunda (RQ serileştirmesi): `MirrorTask.to_dict()`. Yükü alıp
	adaptörleri yeniden kuran fonksiyon `api/` katmanının işidir —
	`method_path` ile verilir. Bu paket `frappe` yolunu bilmez ve bilmemeli.
	"""

	def __init__(self, method_path: str, *, queue: str = "long") -> None:
		self._method = method_path
		self._queue = queue

	def submit(self, task: MirrorTask) -> bool:
		try:
			import frappe  # noqa: PLC0415 - bilinçli tembel import

			# Aynı içerik bir istekte birden çok File satırına bağlanabilir.
			# URL+operasyon+hedef aynıysa ikinci RQ işi yalnız S3 maliyetidir;
			# içerik-adresli anahtar zaten idempotent. Frappe job_id'si site adıyla
			# ayrıca namespace edilir, bu kısa özet yalnız site içindeki tekrarı
			# bastırır.
			kimlik = hashlib.sha256(
				f"{task.op}\x1f{task.ref.url}\x1f{task.target_scope}".encode()
			).hexdigest()[:32]
			frappe.enqueue(
				self._method,
				queue=self._queue,
				enqueue_after_commit=True,
				job_id=f"media-mirror::{kimlik}",
				deduplicate=True,
				**task.to_dict(),
			)
			return True
		except Exception:
			# Kuyruk hatası birincili DÜŞÜRMEZ (modül dokümanı, son bölüm).
			return False

	def drain(self, timeout: Optional[float] = None) -> None:
		return None

	def close(self) -> None:
		return None


class MirrorWorker:
	"""Ayna görevlerini ikincil depoda yürütür ve sonuçları sayar."""

	def __init__(
		self,
		primary: StorageAdapter,
		secondary: StorageAdapter,
		*,
		alarm: Optional[Callable[[Dict[str, Any]], None]] = None,
	) -> None:
		self._primary = primary
		self._secondary = secondary
		self._lock = threading.Lock()
		self._alarm = alarm
		self.counters: Dict[str, int] = {TASK_OK: 0, TASK_FAILED: 0, TASK_DROPPED: 0}
		self.failures: List[Dict[str, Any]] = []

	def record(self, task: MirrorTask, sonuc: str, sebep: str = "") -> None:
		with self._lock:
			self.counters[sonuc] = self.counters.get(sonuc, 0) + 1
			if sonuc in (TASK_FAILED, TASK_DROPPED):
				kayit = task.to_dict()
				kayit["result"] = sonuc
				kayit["reason"] = sebep
				# Son 500 hata yeter; sınırsız liste bellek sızıntısıdır.
				self.failures.append(kayit)
				del self.failures[:-500]
				if self._alarm is not None:
					try:
						self._alarm(dict(kayit))
					except Exception:
						pass

	def execute(self, task: MirrorTask) -> bool:
		"""Tek görevi yürüt. `True` = tamam, `False` = yeniden denenebilir."""
		try:
			if task.op == OP_PUT:
				return self._mirror_put(task)
			if task.op == OP_DELETE:
				self._secondary.delete(task.ref)
				self.record(task, TASK_OK)
				return True
			if task.op == OP_MOVE:
				try:
					self._secondary.move(task.ref, task.target_scope)
				except ObjectNotFound:
					# İkincilde hiç yoktu: taşınacak bir şey yok, tam kopya
					# `reconcile()` ile gelir. Hata değil.
					self.record(task, TASK_DROPPED, "secondary_missing")
					return True
				self.record(task, TASK_OK)
				return True
			self.record(task, TASK_FAILED, f"unknown_op:{task.op}")
			return False
		except MediaEngineError as hata:
			self.record(task, TASK_FAILED, f"{type(hata).__name__}:{hata.kod}")
			# Queue gövdesinde False = yeniden dene. Önceki ifade tersiydi ve
			# tam da geçici S3 hatalarını ilk denemeden sonra bırakıyordu.
			return not bool(getattr(hata, "retryable", False))
		except Exception as hata:  # ağ/istemci hatası — yeniden denenebilir
			self.record(task, TASK_FAILED, f"{type(hata).__name__}")
			return False

	def _mirror_put(self, task: MirrorTask) -> bool:
		stream_reader = getattr(self._primary, "iter_bytes", None)
		stream_writer = getattr(self._secondary, "put_stream", None)
		if callable(stream_reader) and callable(stream_writer):
			try:
				if self._secondary.exists(task.ref):
					self.record(task, TASK_OK)
					return True
				sonuc = stream_writer(
					stream_reader(task.ref),
					task.ref.key.extension,
					scope=task.ref.scope,
				)
				# Birincildeki baytlar URL'in içerik hash'iyle uyuşmuyorsa S3
				# adaptörü farklı bir anahtar üretir. Bunu "başarılı" saymak,
				# beklenen URL'in S3'te olmadığını gizlerdi.
				if sonuc.ref != task.ref:
					raise StorageError(
						"Birincil nesnenin içeriği adresiyle uyuşmuyor",
						detay={"expected": task.ref.url, "actual": sonuc.ref.url},
						retryable=False,
					)
			except ObjectNotFound:
				self.record(task, TASK_DROPPED, "primary_missing")
				return True
			self.record(task, TASK_OK)
			return True

		try:
			icerik = self._primary.get(task.ref)
		except ObjectNotFound:
			# Birincilde artık yok (silinmiş). Aynalanacak bir şey yok.
			self.record(task, TASK_DROPPED, "primary_missing")
			return True
		if self._secondary.exists(task.ref):
			self.record(task, TASK_OK)
			return True
		uzanti = task.ref.key.extension
		sonuc = self._secondary.put(icerik, uzanti, scope=task.ref.scope)
		if sonuc.ref != task.ref:
			raise StorageError(
				"Birincil nesnenin içeriği adresiyle uyuşmuyor",
				detay={"expected": task.ref.url, "actual": sonuc.ref.url},
				retryable=False,
			)
		self.record(task, TASK_OK)
		return True


class MirrorStorage:
	"""Yerel birincil + asenkron ikincil ayna.

	Okuma birincilden; birincil ıskalarsa ikincilden (okuma yedeği). Yazma
	birincile senkron, ikincile asenkron. İkincil hiçbir koşulda birincili
	düşürmez.

	Args:
	    primary: Birincil depo (yerel disk).
	    secondary: İkincil depo (S3). `None` verilemez — aynasız ayna yok.
	    queue_factory: `MirrorWorker` alıp kuyruk döndüren fabrika. `None`
	        ise `ThreadMirrorQueue`. İşçi kuyruktan ÖNCE kurulmak zorunda
	        (kuyruk işçiye referans tutar), bu yüzden hazır bir kuyruk
	        nesnesi değil fabrika alınıyor.
	    read_repair: Birincilde olmayıp ikincilde bulunan nesne okunduğunda
	        birincile geri yazılsın mı. Varsayılan `True`; kapatmak, aynı
	        nesnenin her okumasında ağ maliyetini ödemek demektir.
	"""

	def __init__(
		self,
		primary: StorageAdapter,
		secondary: StorageAdapter,
		*,
		queue_factory: Optional[Callable[["MirrorWorker"], MirrorQueue]] = None,
		read_repair: bool = True,
		alarm: Optional[Callable[[Dict[str, Any]], None]] = None,
	) -> None:
		self._primary = primary
		self._secondary = secondary
		self.worker = MirrorWorker(primary, secondary, alarm=alarm)
		fabrika = queue_factory if queue_factory is not None else ThreadMirrorQueue
		self._queue: MirrorQueue = fabrika(self.worker)
		self._read_repair = bool(read_repair)

	# ── StorageAdapter ─────────────────────────────────────────────────

	def put(self, content: bytes, extension: str, *, scope: str = SCOPE_PUBLIC) -> PutResult:
		sonuc = self._primary.put(content, extension, scope=scope)
		self._queue.submit(MirrorTask(op=OP_PUT, ref=sonuc.ref))
		return sonuc

	def put_stream(
		self,
		chunks: Iterable[bytes],
		extension: str,
		*,
		scope: str = SCOPE_PUBLIC,
	) -> PutResult:
		writer = getattr(self._primary, "put_stream", None)
		if not callable(writer):
			raise StorageError("Birincil depo akışlı yazmayı desteklemiyor", retryable=False)
		sonuc = writer(chunks, extension, scope=scope)
		self._queue.submit(MirrorTask(op=OP_PUT, ref=sonuc.ref))
		return sonuc

	def get(self, ref: ObjectRef) -> bytes:
		try:
			return self._primary.get(ref)
		except ObjectNotFound:
			icerik = self._secondary.get(ref)  # yoksa ObjectNotFound yine yükselir
			if self._read_repair:
				try:
					self._primary.put(icerik, ref.key.extension, scope=ref.scope)
				except StorageError:
					# Onarım başarısızsa okuma yine de başarılıdır —
					# çağıranın istediği baytlar elimizde.
					pass
			return icerik

	def iter_bytes(self, ref: ObjectRef, *, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
		primary_reader = getattr(self._primary, "iter_bytes", None)
		secondary_reader = getattr(self._secondary, "iter_bytes", None)
		if self._primary.exists(ref) and callable(primary_reader):
			yield from primary_reader(ref, chunk_size=chunk_size)
			return
		if callable(secondary_reader):
			yield from secondary_reader(ref, chunk_size=chunk_size)
			return
		raise ObjectNotFound("Nesne bulunamadı", detay={"url": ref.url})

	def exists(self, ref: ObjectRef) -> bool:
		return self._primary.exists(ref) or self._secondary.exists(ref)

	def stat(self, ref: ObjectRef) -> ObjectStat:
		try:
			return self._primary.stat(ref)
		except ObjectNotFound:
			return self._secondary.stat(ref)

	def delete(self, ref: ObjectRef) -> bool:
		silindi = self._primary.delete(ref)
		self._queue.submit(MirrorTask(op=OP_DELETE, ref=ref))
		return silindi

	def move(self, source: ObjectRef, target_scope: str) -> ObjectRef:
		hedef = self._primary.move(source, target_scope)
		self._queue.submit(MirrorTask(op=OP_MOVE, ref=source, target_scope=target_scope))
		return hedef

	def iter_keys(self, *, scope: str = SCOPE_PUBLIC, prefix: str = "") -> Iterator[ObjectKey]:
		"""Birincili dolaşır. İkincil ancak `reconcile()` ile karşılaştırılır —
		iki kaynağı burada birleştirmek, yetim taramasını yanıltırdı."""
		return self._primary.iter_keys(scope=scope, prefix=prefix)

	def url_for(self, ref: ObjectRef, *, ttl_seconds: Optional[int] = None) -> str:
		return self._primary.url_for(ref, ttl_seconds=ttl_seconds)

	# ── ayna yönetimi ──────────────────────────────────────────────────

	def drain(self, timeout: Optional[float] = 5.0) -> None:
		"""Kuyruğu boşalt — kapanış ve test için."""
		self._queue.drain(timeout)

	def close(self) -> None:
		self._queue.close()

	def counters(self) -> Dict[str, int]:
		return dict(self.worker.counters)

	def failed_tasks(self) -> List[Dict[str, Any]]:
		return list(self.worker.failures)

	def replication_status(self, ref: ObjectRef) -> Dict[str, Any]:
		"""Tek nesnenin birincil/ikincil varlığını içerik sızdırmadan ölç."""
		primary = bool(self._primary.exists(ref))
		secondary = bool(self._secondary.exists(ref))
		return {
			"url": ref.url,
			"primary": primary,
			"secondary": secondary,
			"replicated": primary and secondary,
		}

	def reconcile(self, *, scope: str = SCOPE_PUBLIC, limit: int = 0) -> Dict[str, Any]:
		"""Birincilde olup ikincilde olmayanı yeniden kuyruğa al.

		Kuyruk dolduğunda düşen görevlerin, süreç yeniden başladığında
		kaybolan görevlerin ve S3 kesintisinde başarısız olanların TEK
		telafi yolu budur. `weekly_long` bloğuna bağlanması gerekir
		(`retention.schema.json` `orphan_reconciliation` ile aynı gerekçe).
		"""
		eksik = 0
		kuyruga = 0
		bakilan = 0
		for key in self._primary.iter_keys(scope=scope):
			bakilan += 1
			ref = ObjectRef(key=key, scope=scope)
			if self._secondary.exists(ref):
				continue
			eksik += 1
			if self._queue.submit(MirrorTask(op=OP_PUT, ref=ref)):
				kuyruga += 1
			if limit and eksik >= limit:
				break
		return {"scope": scope, "scanned": bakilan, "missing": eksik, "queued": kuyruga}

	def reconcile_all(self, *, limit: int = 0) -> List[Dict[str, Any]]:
		return [self.reconcile(scope=s, limit=limit) for s in SCOPES]

	def __len__(self) -> int:
		return sum(1 for scope in SCOPES for _ in self.iter_keys(scope=scope))


def inline_mirror(primary: StorageAdapter, secondary: StorageAdapter, **kwargs: Any) -> MirrorStorage:
	"""Satır içi (senkron) ayna — testler ve tek seferlik migrasyon için."""
	return MirrorStorage(primary, secondary, queue_factory=InlineMirrorQueue, **kwargs)


__all__ = [
	"MirrorStorage",
	"MirrorTask",
	"MirrorQueue",
	"MirrorWorker",
	"InlineMirrorQueue",
	"ThreadMirrorQueue",
	"FrappeEnqueueMirrorQueue",
	"inline_mirror",
	"OP_PUT",
	"OP_DELETE",
	"OP_MOVE",
	"TASK_OK",
	"TASK_FAILED",
	"TASK_DROPPED",
	"DEFAULT_QUEUE_SIZE",
]
