"""Canonical Phase 3 media queue topology.

Queue names used to be repeated in DocType JSON, the Frappe bridge and Docker
Compose.  A missing worker therefore looked valid to application code while
jobs accumulated forever.  This module is the code-side source of truth; the
closure test checks every deployment projection against it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueueSpec:
	name: str
	purpose: str
	timeout_seconds: int
	max_attempts: int
	backoff_seconds: tuple[int, ...]
	concurrency: int
	backlog_alarm: int

	def __post_init__(self) -> None:
		if not self.name.startswith("media-"):
			raise ValueError(f"Medya kuyruğu adı `media-` ile başlamalı: {self.name!r}")
		if self.timeout_seconds <= 0 or self.max_attempts <= 0 or self.concurrency <= 0:
			raise ValueError(f"Kuyruk sınırları pozitif olmalı: {self.name}")
		if len(self.backoff_seconds) != max(0, self.max_attempts - 1):
			raise ValueError(f"Backoff sayısı deneme tavanıyla uyuşmuyor: {self.name}")
		if tuple(sorted(self.backoff_seconds)) != self.backoff_seconds:
			raise ValueError(f"Backoff süreleri artan olmalı: {self.name}")


IMAGE_LIVE = QueueSpec(
	name="media-image-live",
	purpose="Kullanıcının beklediği normalize ve türev üretimi",
	timeout_seconds=60,
	max_attempts=3,
	backoff_seconds=(300, 900),
	concurrency=1,
	backlog_alarm=25,
)
IMAGE_BULK = QueueSpec(
	name="media-image-bulk",
	purpose="Backfill, politika yeniden işleme ve kontrollü toplu akış",
	timeout_seconds=1800,
	max_attempts=2,
	backoff_seconds=(900,),
	concurrency=1,
	backlog_alarm=500,
)
VIDEO = QueueSpec(
	name="media-video",
	purpose="Video probe, transcode, poster, preview ve HLS",
	timeout_seconds=1800,
	max_attempts=2,
	backoff_seconds=(900,),
	concurrency=1,
	backlog_alarm=20,
)
AI = QueueSpec(
	name="media-ai",
	purpose="İçerik sınıflandırma ve moderasyon",
	timeout_seconds=120,
	max_attempts=1,
	backoff_seconds=(),
	concurrency=1,
	backlog_alarm=100,
)
MAINT = QueueSpec(
	name="media-maint",
	purpose="GC, retention, uzlaştırma ve rapor işleri",
	timeout_seconds=1800,
	max_attempts=1,
	backoff_seconds=(),
	concurrency=1,
	backlog_alarm=250,
)

QUEUE_SPECS: tuple[QueueSpec, ...] = (IMAGE_LIVE, IMAGE_BULK, VIDEO, AI, MAINT)
QUEUE_NAMES: tuple[str, ...] = tuple(spec.name for spec in QUEUE_SPECS)
BY_NAME: dict[str, QueueSpec] = {spec.name: spec for spec in QUEUE_SPECS}

JOB_QUEUE: dict[str, str] = {
	"normalize": IMAGE_LIVE.name,
	"rendition": IMAGE_LIVE.name,
	"video_from_animation": VIDEO.name,
	"transcode": VIDEO.name,
	"poster": VIDEO.name,
	"preview": VIDEO.name,
	"ai": AI.name,
	"gc": MAINT.name,
	"retention": MAINT.name,
	"report": MAINT.name,
	"backfill": IMAGE_BULK.name,
	"reprocess": IMAGE_BULK.name,
}


def for_job(job_type: str, *, bulk: bool = False) -> QueueSpec:
	"""Resolve a job without silently falling back to a general queue."""
	if bulk and job_type in ("normalize", "rendition"):
		return IMAGE_BULK
	try:
		return BY_NAME[JOB_QUEUE[job_type]]
	except KeyError as exc:
		raise ValueError(f"Bilinmeyen medya iş tipi: {job_type!r}") from exc


def validate_topology() -> tuple[str, ...]:
	"""Return invariant violations; an empty tuple is the deployment gate."""
	errors: list[str] = []
	if len(QUEUE_NAMES) != len(set(QUEUE_NAMES)):
		errors.append("duplicate_queue_name")
	if set(JOB_QUEUE.values()) - set(QUEUE_NAMES):
		errors.append("job_maps_to_unknown_queue")
	if IMAGE_LIVE.name == IMAGE_BULK.name:
		errors.append("live_bulk_not_isolated")
	if VIDEO.timeout_seconds >= 2700:
		errors.append("video_timeout_not_below_stale_threshold")
	return tuple(errors)


__all__ = [
	"AI",
	"BY_NAME",
	"IMAGE_BULK",
	"IMAGE_LIVE",
	"JOB_QUEUE",
	"MAINT",
	"QUEUE_NAMES",
	"QUEUE_SPECS",
	"VIDEO",
	"QueueSpec",
	"for_job",
	"validate_topology",
]
