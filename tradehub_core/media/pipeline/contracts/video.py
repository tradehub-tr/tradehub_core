"""VideoEngine sözleşmesi — künye, rendition, poster, önizleme klibi.

Bugünkü uygulama `tradehub_core/media/transcode.py`: ffmpeg ile VP9/Opus WebM,
`frappe.enqueue(queue="long")`, `jobs.py` retry politikası (3 deneme, 300/900 sn
backoff), süpürücü (5 dk). Bu sözleşme kuyruğu ve durum makinesini KAPSAMAZ —
onlar `media/jobs.py` + `media/states.py` işidir. Buradaki sözleşme yalnız
**saf dönüşümdür**: girdi video, çıktı rendition.

Neden kuyruk dışarıda: bugünkü hattın en değerli parçası (retry + dead-letter +
stale süpürme) zaten çalışıyor ve `File` alanlarına bağlı. Motor sözleşmesini
ona bağlamak, motoru site olmadan test edilemez hâle getirirdi.

Zaman aşımı merdiveni (transcode.py'den KORUNUR — her katman bir üstünden kısa):

    ffprobe 20 sn  <  ffmpeg 1700 sn  <  kuyruk 1800 sn  <  kayıp eşiği 2700 sn

İDEMPOTENSİ (NFR-040)
---------------------
ffmpeg çıktısı sürümler arasında bayt düzeyinde AYNI OLMAYABİLİR; bu yüzden
sözleşme bayt-determinizmi VAAT ETMEZ. Vaat edilen **etki idempotensidir**:
aynı kaynak + aynı `RenditionSpec` ile ikinci koşum sistemi aynı durumda
bırakır. Uygulama `already(source_hash, spec.id)` ile ikinci koşumu no-op'a
çevirebilir; çeviremiyorsa çıktı atomik olarak yerine yazılır (geçici dosya +
`os.replace`) ve yarım dosya asla görünmez (NFR-041).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

from tradehub_core.media.pipeline.contracts.image import EncodedImage

# `transcode.py:66-67, :75-76` — client'ın sıkıştıramadığı videoyu ayıran
# eşikler. Sözleşmede sabit olarak duruyor ki "genel kütüphane eşikleri
# KORUNUYOR" ifadesi (company-cover-video.json `transcode.
# general_library_thresholds_kept`) tek bir sayıya bağlansın (NFR-045).
NEEDS_TRANSCODE_MAX_WIDTH: int = 1280
NEEDS_TRANSCODE_MAX_BITRATE_BPS: int = 2_500_000

# Süreç zaman aşımları — merdiven yukarıda açıklandı.
FFPROBE_TIMEOUT_SECONDS: int = 20
FFMPEG_TIMEOUT_SECONDS: int = 1700

# Ses işleme kipleri — `video.modes.*.audio_track` değerleriyle aynı.
AUDIO_ALLOWED: str = "allowed"
AUDIO_STRIPPED: str = "stripped"
AUDIO_MODES: Tuple[str, ...] = (AUDIO_ALLOWED, AUDIO_STRIPPED)

# Rendition rolleri — `video.renditions[].role`.
ROLE_PRIMARY: str = "primary"
ROLE_FALLBACK: str = "fallback"
ROLE_MOBILE: str = "mobile"
ROLE_PREVIEW: str = "preview"


@dataclass(frozen=True)
class VideoSource:
	"""Video girdisi — ya bellekteki baytlar ya diskteki yol.

	İki biçimin de olması zorunlu: ffmpeg bir ALT SÜREÇTİR ve aranabilir
	(seekable) bir dosya ister, bu yüzden üretim uygulaması `path` ile
	çalışır. Testler ve sahte uygulama `content` ile çalışır. Sözleşmenin
	tek girdi tipi olması, iki dünyanın aynı `Protocol`'ü karşılamasını
	sağlar.
	"""

	content: Optional[bytes] = None
	path: str = ""

	def __post_init__(self) -> None:
		if bool(self.content is not None) == bool(self.path):
			raise ValueError("VideoSource: `content` VEYA `path` — tam olarak biri verilmeli")


@dataclass(frozen=True)
class VideoProbe:
	"""ffprobe künyesi.

	`measured=False` ffprobe'un YOK ya da başarısız olduğunu söyler. NFR-043:
	bu durumda çağıran güvenli tarafa düşer — ölçülemeyen video "kurallara
	uygun" sayılmaz. Bugün `th_media_width` 2.853 kaydın 0'ında dolu (%0);
	FR-133 bu alanların yazılmasını istiyor, sözleşme onların kaynağıdır.
	"""

	width: int = 0
	height: int = 0
	duration_s: float = 0.0
	bitrate_bps: int = 0
	frame_rate: float = 0.0
	container: str = ""
	video_codec: str = ""
	audio_codec: str = ""
	has_audio: bool = False
	measured: bool = True

	@property
	def aspect_ratio(self) -> float:
		return (self.width / self.height) if self.height else 0.0

	@property
	def megapixels(self) -> float:
		return (self.width * self.height) / 1_000_000.0


@dataclass(frozen=True)
class VideoRenditionSpec:
	"""Tek bir video rendition'ı — politikanın `video.renditions[]` girdisi.

	Alan adları politikadaki anahtarlarla birebir; `max_bytes` teslim dosya
	kapısıdır (NFR-003) ve aşılırsa `size_gate_retry` politikası devreye
	girer — o karar PolicyEngine'e aittir, motor yalnız ölçüyü raporlar.
	"""

	id: str
	width: int
	height: int
	container: str
	video_codec: str
	crf: int = 32
	maxrate_kbps: int = 0
	bufsize_kbps: int = 0
	frame_rate_cap: int = 30
	audio: str = AUDIO_ALLOWED
	audio_codec: str = "libopus"
	audio_bitrate_kbps: int = 96
	audio_channels: int = 2
	loudness_filter: str = ""
	max_bytes: int = 0
	role: str = ROLE_PRIMARY
	keyframe_interval_s: float = 0.0

	def __post_init__(self) -> None:
		if self.audio not in AUDIO_MODES:
			raise ValueError(f"Bilinmeyen ses kipi: {self.audio!r}")
		if self.width <= 0 or self.height <= 0:
			raise ValueError("VideoRenditionSpec ölçüleri pozitif olmalı")


@dataclass(frozen=True)
class PosterSpec:
	"""Poster (kapak karesi) üretim kuralı.

	Seçim penceresi politikadan gelir: `[0,5 s, min(5 s, süre×0,25)]`, ffmpeg
	`thumbnail` filtresi n=120 ile en temsili kare. Parlaklık kapısından
	geçmezse `[süre×0,25, süre×0,50]` penceresinde BİR KEZ yeniden denenir
	(FR-042). Motor iki pencereyi de dener; ikisi de düşerse `ProbeUnavailable`
	değil `TranscodeFailed` atar — kaynak okunabiliyordu ama kare seçilemedi.
	"""

	width: int
	height: int = 0
	format: str = "webp"
	quality: int = 80
	window_start_s: float = 0.5
	window_end_s: float = 5.0
	retry_window_start_s: float = 0.0
	retry_window_end_s: float = 0.0
	frames: int = 120
	min_brightness: float = 0.0


@dataclass(frozen=True)
class PreviewClipSpec:
	"""Sessiz, döngülü önizleme klibi (FR-043).

	Politika değerleri: 6 sn, 854×480, ≤400 KB (409.600 bayt), ses YOK,
	başlangıç poster'ın seçildiği zaman damgası (görsel süreklilik).
	"""

	duration_s: float = 6.0
	width: int = 854
	height: int = 480
	max_bytes: int = 409_600
	video_codec: str = "libvpx-vp9"
	container: str = "webm"
	start_offset_s: float = 0.0
	silent: bool = True
	loop: bool = True


@dataclass(frozen=True)
class VideoArtifact:
	"""Üretilmiş video çıktısı.

	`content` ve `path` ikisinden biri doludur — hangisinin dolu olduğu
	çağıranın `target_path` verip vermediğine bağlıdır. `notes` kullanıcıya
	gösterilecek özet satırlarını taşır (FR-064).
	"""

	rendition_id: str
	width: int
	height: int
	duration_s: float
	size_bytes: int
	container: str
	content: Optional[bytes] = None
	path: str = ""
	bitrate_bps: int = 0
	has_audio: bool = False
	notes: Tuple[str, ...] = ()
	extra: Dict[str, str] = field(default_factory=dict)

	def fits(self, spec: VideoRenditionSpec) -> bool:
		"""Teslim dosya kapısını geçti mi (NFR-003). `max_bytes=0` → kapı yok."""
		return not spec.max_bytes or self.size_bytes <= spec.max_bytes


@runtime_checkable
class VideoEngine(Protocol):
	"""Video işleme motoru — kuyruk ve durum makinesi HARİÇ.

	Tüm metotlar `contracts.errors` hiyerarşisinden atar. `subprocess`
	hatalarını (`FileNotFoundError`, `CalledProcessError`, `TimeoutExpired`)
	sızdırmak sözleşme ihlalidir: ffmpeg'in imajdan kalkması `ProbeUnavailable`
	ya da `TranscodeFailed` olarak görünmelidir, worker'ı çökertmemelidir.
	"""

	def probe(self, source: VideoSource) -> VideoProbe:
		"""Künyeyi oku. ffprobe yoksa/okunamıyorsa HATA ATMAZ:
		`measured=False` taşıyan `VideoProbe` döner (NFR-043 güvenli taraf).
		Yan etkisizdir; `FFPROBE_TIMEOUT_SECONDS` içinde dönmelidir."""
		...

	def needs_transcode(
		self,
		probe: VideoProbe,
		*,
		max_width: int = NEEDS_TRANSCODE_MAX_WIDTH,
		max_bitrate_bps: int = NEEDS_TRANSCODE_MAX_BITRATE_BPS,
	) -> bool:
		"""Video zaten küçük/sıkışmış mı — koşullu atlama kararı.

		`transcode.needs_transcode()` ile aynı anlam: eşiklerin ÜSTÜNDEKİ video
		"client sıkıştıramamış" sayılır → sunucu işler. `probe.measured=False`
		ise **True** döner: ölçemediğin videoyu atlamak güvenli taraf değildir.

		Bazı slotlar (`company.cover_video`) bu kararı ATLAR ve koşulsuz
		transcode eder — o karar politikadadır, motorda değil.
		"""
		...

	def transcode(
		self, source: VideoSource, spec: VideoRenditionSpec, *, target_path: str = ""
	) -> VideoArtifact:
		"""Kaynağı tek bir rendition'a dönüştür.

		`target_path` verilirse çıktı ATOMİK yazılır (geçici dosya +
		`os.replace`) ve `VideoArtifact.path` dolar; verilmezse baytlar
		`content` alanında döner.

		Etki-idempotent (NFR-040): aynı kaynak + aynı spec ile ikinci koşum
		sistemi aynı durumda bırakır. Bayt-determinizmi VAAT EDİLMEZ (ffmpeg
		sürümü değişebilir).

		Yerinde değiştirme (in-place replace) bu sözleşmenin dışındadır ve
		bazı slotlarda YASAKTIR (FR-041, `company.cover_video`): kaynağı ezmek
		poster ve önizleme klibinin kaynağını yok eder.

		Hatalar: `ProbeUnavailable` (ffmpeg yok), `TranscodeFailed`
		(`detay["attempts"]` ile), `TranscodeFailed` (zaman aşımı).
		"""
		...

	def transcode_all(
		self, source: VideoSource, specs: Sequence[VideoRenditionSpec]
	) -> Dict[str, VideoArtifact]:
		"""Tüm rendition'ları üret — anahtar `VideoRenditionSpec.id`.

		Kısmi başarı YOKTUR: biri düşerse hepsi düşer. Yarım rendition seti,
		`<source>` etiketleri arasında 404 veren bir tanesi demektir.
		"""
		...

	def make_poster(self, source: VideoSource, spec: PosterSpec) -> EncodedImage:
		"""Poster karesini seç ve kodla (FR-042).

		Çıktı `image.EncodedImage`'dir — poster bir GÖRSELDİR ve teslimde
		görsel merdiveninin kurallarına tabidir. İki metnin aynı tipi
		paylaşması, poster'ın `srcset`'e girmesini bedavaya getirir.

		Deterministik: aynı kaynak + aynı spec aynı kareyi seçer (`thumbnail`
		filtresi girdiye göre çalışır, rastgelelik yoktur).
		"""
		...

	def make_preview_clip(
		self, source: VideoSource, spec: PreviewClipSpec, *, target_path: str = ""
	) -> VideoArtifact:
		"""Sessiz, döngülü önizleme klibi üret (FR-043).

		`spec.max_bytes` aşılırsa hata ATILMAZ: üretilen klip döner ve çağıran
		`fits()` ile kapıyı uygular — politika `size_gate_retry` ile CRF
		artırarak yeniden deneyebilir. Motorun politika kararı vermemesi
		bilinçli.
		"""
		...


__all__ = [
	"NEEDS_TRANSCODE_MAX_WIDTH",
	"NEEDS_TRANSCODE_MAX_BITRATE_BPS",
	"FFPROBE_TIMEOUT_SECONDS",
	"FFMPEG_TIMEOUT_SECONDS",
	"AUDIO_ALLOWED",
	"AUDIO_STRIPPED",
	"ROLE_PRIMARY",
	"ROLE_FALLBACK",
	"ROLE_MOBILE",
	"ROLE_PREVIEW",
	"VideoSource",
	"VideoProbe",
	"VideoRenditionSpec",
	"PosterSpec",
	"PreviewClipSpec",
	"VideoArtifact",
	"VideoEngine",
]
