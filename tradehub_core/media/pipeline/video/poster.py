"""T-073 — poster (ilk ANLAMLI kare) + sessiz önizleme klibi.

**Bugünkü durum: ikisi de YOK.** Bir yükleme → bir dosya; `<video>` etiketine
`poster` verilmiyor (`docs/reports/03-render-envanteri.md` §6.3). Galeri video
karosunda duran kare, tarayıcının kendi seçtiği ilk karedir — ki o kare
çoğunlukla siyah bir açılıştır. Bedeli iki katmanda ödeniyor: kullanıcı boş
siyah kutu görüyor, tarayıcı da poster yerine videonun metadata'sını (ve çoğu
zaman ilk segmentini) indiriyor.

**"İlk anlamlı kare" nasıl tanımlanır.** "İlk kare" kötü bir tanımdır: açılış
karesi genelde siyah ya da beyaz bir geçiştir. Uygulanabilir tanım politika
dosyasında yazılı (`company-cover-video.json` `video.poster.selection_rule`) ve
burada aynen uygulanıyor:

    1. Pencere: [0,5 sn, min(5 sn, süre × 0,25)]
       — açılış siyahlığını atlar, videonun ilk çeyreğinden çıkmaz.
    2. Seçim: ffmpeg `thumbnail=n=120` filtresi — 120 karelik pencerede
       histogram uzaklığına göre EN TEMSİLİ kareyi seçer.
    3. Parlaklık kapısı: ortalama luma %6-%94 arasında olmalı. Siyah açılış ya
       da beyaz patlama kareyi geçersiz kılar.
    4. Kapıdan geçmezse [süre × 0,25, süre × 0,50] penceresinde BİR KEZ
       yeniden denenir. O da düşerse `video_poster_unresolved`.

**Önizleme klibi.** Sessiz, kısa, döngülenebilir. Başlangıcı poster'ın
seçildiği zaman damgasıdır — kullanıcı hover ettiğinde gördüğü ilk kare,
poster'da gördüğü karedir (görsel süreklilik). Bayt kapısı iki katmanlı:
görev tanımının ZORUNLU kapısı 1 MB, `company-cover-video.json`'un HEDEF kapısı
400 KB. Kapıyı tutturmak için önce CRF merdiveni (28 → 32 → 36), sonra süre
merdiveni (6 → 4 → 3 sn) denenir; süre 3 sn'nin altına İNDİRİLMEZ — daha kısası
önizleme değil, titreşimdir.

`frappe` import edilmez; kuyruk bu modülün işi değildir.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Tuple

from tradehub_core.media.pipeline.contracts.errors import ProbeUnavailable, TranscodeFailed
from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS
from tradehub_core.media.pipeline.video import probe as probe_modulu
from tradehub_core.media.pipeline.video.decision import default_table
from tradehub_core.media.pipeline.video.probe import VideoFacts
from tradehub_core.media.pipeline.video.transcode import run_ffmpeg

#: Poster çözülemedi hatası — politika dosyasındaki `on_final_failure` ile aynı ad.
CODE_POSTER_UNRESOLVED: str = "video_poster_unresolved"

_PTS_RE = re.compile(r"pts_time:([0-9.]+)")
_YAVG_RE = re.compile(r"YAVG:([0-9.]+)")


@dataclass(frozen=True)
class PosterSpec:
	"""Poster üretim kuralı — değerler `video_decision.json` `poster` bloğundan."""

	window_start_s: float = 0.5
	thumbnail_frames: int = 120
	format: str = "webp"
	quality_ladder: Tuple[int, ...] = (78, 70, 62)
	width: int = 1280
	max_bytes: int = 122_880
	min_luma_pct: float = 6.0
	max_luma_pct: float = 94.0
	min_edge_density_pct: float = 1.0
	max_retries: int = 1

	@classmethod
	def from_table(cls, blok: Optional[Mapping[str, Any]] = None) -> "PosterSpec":
		p = dict(blok if blok is not None else default_table().poster)
		kapi = dict(p.get("brightness_gate") or {})
		detay = dict(p.get("detail_gate") or {})
		v = cls()
		return cls(
			window_start_s=float(p.get("window_start_s", v.window_start_s)),
			thumbnail_frames=int(p.get("thumbnail_frames", v.thumbnail_frames)),
			format=str(p.get("format", v.format)),
			quality_ladder=tuple(p.get("quality_ladder") or v.quality_ladder),
			width=int(p.get("width", v.width)),
			max_bytes=int(p.get("max_bytes", v.max_bytes)),
			min_luma_pct=float(kapi.get("min_luma_pct", v.min_luma_pct)),
			max_luma_pct=float(kapi.get("max_luma_pct", v.max_luma_pct)),
			min_edge_density_pct=float(detay.get("min_edge_density_pct", v.min_edge_density_pct)),
			max_retries=int(p.get("max_retries", v.max_retries)),
		)


@dataclass(frozen=True)
class PreviewClipSpec:
	"""Sessiz önizleme klibi kuralı."""

	duration_ladder: Tuple[float, ...] = (6.0, 4.0, 3.0)
	width: int = 854
	height: int = 480
	max_bytes: int = 1_048_576
	policy_max_bytes: int = 409_600
	crf_ladder: Tuple[int, ...] = (28, 32, 36)
	video_codec: str = "libx264"
	container: str = "mp4"

	@classmethod
	def from_table(cls, blok: Optional[Mapping[str, Any]] = None) -> "PreviewClipSpec":
		p = dict(blok if blok is not None else default_table().preview_clip)
		v = cls()
		return cls(
			duration_ladder=tuple(float(x) for x in (p.get("duration_fallback_s") or v.duration_ladder)),
			width=int(p.get("width", v.width)),
			height=int(p.get("height", v.height)),
			max_bytes=int(p.get("max_bytes", v.max_bytes)),
			policy_max_bytes=int(p.get("policy_max_bytes", v.policy_max_bytes)),
			crf_ladder=tuple(int(x) for x in (p.get("crf_ladder") or v.crf_ladder)),
			video_codec=str(p.get("video_codec", v.video_codec)),
			container=str(p.get("container", v.container)),
		)


@dataclass
class PosterResult:
	"""Üretilmiş poster + NEDEN o kare seçildi."""

	path: str
	timestamp_s: float
	size_bytes: int
	luma_pct: float
	edge_density_pct: float
	quality: int
	window: Tuple[float, float]
	retried: bool = False
	attempts: List[Dict[str, Any]] = field(default_factory=list)
	notes: List[str] = field(default_factory=list)

	def as_dict(self) -> Dict[str, Any]:
		return {
			"path": self.path,
			"timestamp_s": round(self.timestamp_s, 3),
			"size_bytes": self.size_bytes,
			"luma_pct": round(self.luma_pct, 2),
			"edge_density_pct": round(self.edge_density_pct, 2),
			"quality": self.quality,
			"window": [round(self.window[0], 3), round(self.window[1], 3)],
			"retried": self.retried,
			"attempts": self.attempts,
			"notes": self.notes,
		}


@dataclass
class PreviewClipResult:
	"""Üretilmiş önizleme klibi."""

	path: str
	start_s: float
	duration_s: float
	size_bytes: int
	crf: int
	within_task_gate: bool
	within_policy_gate: bool
	attempts: List[Dict[str, Any]] = field(default_factory=list)
	notes: List[str] = field(default_factory=list)

	def as_dict(self) -> Dict[str, Any]:
		return {
			"path": self.path,
			"start_s": round(self.start_s, 3),
			"duration_s": self.duration_s,
			"size_bytes": self.size_bytes,
			"crf": self.crf,
			"within_task_gate": self.within_task_gate,
			"within_policy_gate": self.within_policy_gate,
			"attempts": self.attempts,
			"notes": self.notes,
		}


# ── Pencere hesabı ──────────────────────────────────────────────────────


def poster_window(duration_s: float, spec: Optional[PosterSpec] = None) -> Tuple[float, float]:
	"""Birincil arama penceresi: `[0,5 , min(5, süre × 0,25)]`.

	Kısa videoda (süre < 2 sn) formül kendi kendini yer: `süre × 0,25` 0,5'in
	altına düşer ve pencere ters döner. Bu durumda pencere `[0, süre]`'ye
	genişletilir — 1,5 saniyelik bir videoda "açılış siyahlığını atla" lüksü
	yoktur, önemli olan bir kare bulmaktır.
	"""
	spec = spec or PosterSpec()
	bas = spec.window_start_s
	son = min(5.0, duration_s * 0.25)
	if son <= bas:
		return (0.0, max(duration_s, 0.1))
	return (bas, son)


def poster_retry_window(duration_s: float) -> Tuple[float, float]:
	"""İkincil pencere: `[süre × 0,25 , süre × 0,50]` — videonun ikinci çeyreği."""
	bas = duration_s * 0.25
	son = duration_s * 0.50
	if son <= bas:
		return (0.0, max(duration_s, 0.1))
	return (bas, son)


# ── Parlaklık ölçümü ────────────────────────────────────────────────────


def mean_luma_pct(image_path: str) -> float:
	"""Görselin ortalama parlaklığı (%0-100). Ölçülemezse -1.

	Önce Pillow (`convert("L")` ortalaması) denenir — üretimde zaten kurulu ve
	alt süreç maliyeti yok. Pillow WebP okuyamıyorsa (nadiren, derleme
	seçeneğine bağlı) ffmpeg `signalstats` YAVG'ına düşülür.

	`-1` "ölçülemedi" demektir ve parlaklık kapısı bu değerde TETİKLENMEZ:
	ölçemediğimiz bir kareyi "çok karanlık" ilan etmek uydurma olurdu.
	"""
	try:
		from PIL import Image, ImageStat

		with Image.open(image_path) as im:
			gri = im.convert("L")
			return float(ImageStat.Stat(gri).mean[0]) / 255.0 * 100.0
	except Exception:  # noqa: BLE001 — Pillow yoksa/okuyamıyorsa ffmpeg yolu denenir
		pass

	try:
		p = run_ffmpeg(
			["ffmpeg", "-hide_banner", "-i", image_path, "-vf", "signalstats,metadata=mode=print",
				"-frames:v", "1", "-f", "null", "-"],
			timeout=60,
		)
		metin = (p.stderr or b"").decode("utf-8", "replace") + (p.stdout or b"").decode("utf-8", "replace")
		m = _YAVG_RE.search(metin)
		if m:
			return float(m.group(1)) / 255.0 * 100.0
	except (ProbeUnavailable, TranscodeFailed):
		pass
	return -1.0


def edge_density_pct(image_path: str) -> float:
	"""Karedeki belirgin kenar oranı; düz/bulanık kareleri elemek için.

	Parlaklık tek başına gri, tamamen ayrıntısız bir kareyi "anlamlı" sayar.
	FIND_EDGES çıktısının iç bölgesinde 20/255 üstü piksel oranı, içerik
	bağımsız ve ucuz bir ayrıntı sinyalidir. Ölçülemezse ``-1`` döner.
	"""
	try:
		from PIL import Image, ImageFilter

		with Image.open(image_path) as im:
			gri = im.convert("L")
			kenar = gri.filter(ImageFilter.FIND_EDGES)
			if kenar.width > 2 and kenar.height > 2:
				kenar = kenar.crop((1, 1, kenar.width - 1, kenar.height - 1))
			histogram = kenar.histogram()
			toplam = sum(histogram)
			if not toplam:
				return 0.0
			return sum(histogram[20:]) / toplam * 100.0
	except Exception:  # noqa: BLE001 — poster yine parlaklık kapısıyla değerlendirilebilir
		return -1.0


def frame_is_meaningful(luma_pct: float, edge_pct: float, spec: PosterSpec) -> bool:
	"""Parlaklık ve ayrıntı kapılarının bileşkesi."""
	parlaklik_ok = luma_pct < 0 or spec.min_luma_pct <= luma_pct <= spec.max_luma_pct
	detay_ok = edge_pct < 0 or edge_pct >= spec.min_edge_density_pct
	return parlaklik_ok and detay_ok


# ── Poster üretimi ──────────────────────────────────────────────────────


def build_poster_cmd(
	src: str,
	dst: str,
	window: Tuple[float, float],
	spec: PosterSpec,
	quality: int,
	*,
	width: Optional[int] = None,
) -> List[str]:
	"""`thumbnail` + `showinfo` — seçilen karenin zaman damgası da okunur.

	`showinfo` filtresi zincire `thumbnail`'dan SONRA konuyor: böylece stderr'e
	yalnız SEÇİLEN karenin `pts_time` değeri düşer. Bu değer önizleme klibinin
	başlangıç noktası olur (görsel süreklilik).

	`-ss` girdiden ÖNCE: ffmpeg anahtar kareye kadar hızlı atlar (input seeking).
	Bedeli, raporlanan `pts_time`'ın arama noktasına GÖRECELİ olmasıdır; mutlak
	damga için pencere başlangıcı eklenir (`_poster_timestamp`).
	"""
	bas, son = window
	sure = max(son - bas, 0.1)
	genislik = width or spec.width
	return [
		"ffmpeg", "-y",
		"-filter_threads", "2",
		"-ss", f"{bas:.3f}",
		"-t", f"{sure:.3f}",
		"-i", src,
		"-vf", f"thumbnail=n={spec.thumbnail_frames},scale='min({genislik},iw)':-2,showinfo",
		"-frames:v", "1",
		"-c:v", "libwebp" if spec.format == "webp" else "mjpeg",
		"-quality", str(quality),
		"-progress", "pipe:1", "-nostats",
		dst,
	]


def _poster_timestamp(stderr_text: str, window_start: float) -> float:
	"""`showinfo` çıktısındaki `pts_time`'ı mutlak saniyeye çevir."""
	m = _PTS_RE.search(stderr_text)
	if not m:
		return window_start
	try:
		return window_start + float(m.group(1))
	except ValueError:
		return window_start


def _poster_denemesi(
	src: str,
	dst: str,
	window: Tuple[float, float],
	spec: PosterSpec,
	timeout: int,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> Tuple[float, int, int, str]:
	"""Tek pencerede poster üret; kalite merdivenini bayt kapısı için tüket.

	Döner: (zaman damgası, bayt, kullanılan kalite, ffmpeg stderr).
	"""
	son_hata = ""
	for kalite in spec.quality_ladder:
		cmd = build_poster_cmd(src, dst, window, spec, kalite)
		try:
			p = run_ffmpeg(
				cmd,
				timeout=timeout,
				progress_callback=progress_callback,
				cancel_check=cancel_check,
			)
		except ProbeUnavailable as exc:
			raise TranscodeFailed("ffmpeg bulunamadi", kod=CODE_POSTER_UNRESOLVED) from exc
		except TranscodeFailed as exc:
			son_hata = str((exc.detay or {}).get("stderr_tail") or exc.mesaj)[-500:]
			# Kaynak limiti/iptal aynı komutu başka kaliteyle çalıştırınca düzelmez.
			if (exc.detay or {}).get("isolation_reason") not in ("isolation_exit", None):
				raise
			continue
		boyut = os.path.getsize(dst) if os.path.exists(dst) else 0
		damga = _poster_timestamp((p.stderr or b"").decode("utf-8", "replace"), window[0])
		if boyut and boyut <= spec.max_bytes:
			return damga, boyut, kalite, ""
		# Bayt kapısını geçemedi — merdivenin bir alt basamağıyla yeniden dene.
		# Son basamakta da geçemezse üretilen dosya KORUNUR ve not düşülür:
		# poster yokluğu, biraz büyük bir posterden kötüdür.
		if kalite == spec.quality_ladder[-1]:
			return damga, boyut, kalite, ""
	raise TranscodeFailed(
		"poster karesi uretilemedi",
		kod=CODE_POSTER_UNRESOLVED,
		detay={"stderr_tail": son_hata},
	)


def make_poster(
	src: str,
	dst: str,
	*,
	spec: Optional[PosterSpec] = None,
	facts: Optional[VideoFacts] = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> PosterResult:
	"""İlk ANLAMLI kareyi seç, kodla, parlaklık kapısından geçir.

	Kapıdan geçemezse ikinci pencerede bir kez yeniden dener; o da düşerse
	`TranscodeFailed(kod="video_poster_unresolved")`.
	"""
	spec = spec or PosterSpec.from_table()
	facts = facts or probe_modulu.probe(src)
	if not facts.measured:
		raise TranscodeFailed(
			f"kunye okunamadi: {facts.error}", kod=CODE_POSTER_UNRESOLVED, detay={"error": facts.error}
		)

	pencereler = [poster_window(facts.duration_s, spec)]
	if spec.max_retries > 0:
		pencereler.append(poster_retry_window(facts.duration_s))

	denemeler: List[Dict[str, Any]] = []
	for sira, pencere in enumerate(pencereler):
		damga, boyut, kalite, _ = _poster_denemesi(
			src, dst, pencere, spec, timeout,
			progress_callback=progress_callback, cancel_check=cancel_check,
		)
		luma = mean_luma_pct(dst)
		edge = edge_density_pct(dst)
		gecti = frame_is_meaningful(luma, edge, spec)
		denemeler.append(
			{
				"window": [round(pencere[0], 3), round(pencere[1], 3)],
				"timestamp_s": round(damga, 3),
				"bytes": boyut,
				"quality": kalite,
				"luma_pct": round(luma, 2),
				"edge_density_pct": round(edge, 2),
				"brightness_gate": (
					"OLCULEMEDI" if luma < 0 else (
						"GECTI" if spec.min_luma_pct <= luma <= spec.max_luma_pct else "DUSTU"
					)
				),
				"detail_gate": "OLCULEMEDI" if edge < 0 else (
					"GECTI" if edge >= spec.min_edge_density_pct else "DUSTU"
				),
			}
		)
		if gecti:
			notlar: List[str] = []
			if luma < 0:
				notlar.append("parlaklik OLCULEMEDI — kapi uygulanmadi")
			if edge < 0:
				notlar.append("kenar yogunlugu OLCULEMEDI — detay kapisi uygulanmadi")
			if boyut > spec.max_bytes:
				notlar.append(
					f"bayt kapisi asildi: {boyut} > {spec.max_bytes} (kalite merdiveni tukendi)"
				)
			if sira > 0:
				notlar.append("birincil pencere parlaklik kapisindan dustu, ikincil pencere kullanildi")
			return PosterResult(
				path=dst,
				timestamp_s=damga,
				size_bytes=boyut,
				luma_pct=luma,
				edge_density_pct=edge,
				quality=kalite,
				window=pencere,
				retried=sira > 0,
				attempts=denemeler,
				notes=notlar,
			)

	raise TranscodeFailed(
		"poster parlaklik kapisindan gecemedi (iki pencere de dustu)",
		kod=CODE_POSTER_UNRESOLVED,
		detay={"attempts": denemeler},
	)


# ── Önizleme klibi ──────────────────────────────────────────────────────


def preview_scale_filter(spec: PreviewClipSpec, facts: Optional[VideoFacts] = None) -> str:
	"""Klip ölçek filtresi — kısa kenar bütçesine göre, YÖNELİME duyarlı.

	`PreviewClipSpec` 854×480 diyor; bunun ANLAMI bir kare bütçesidir
	(≈410 bin piksel), "genişlik 854" değil. Yalnız genişliği kısıtlamak
	dikey videoda bütçeyi patlatır ve bu ÖLÇÜLDÜ: `video_vertical_9x16.mp4`
	(720×1280) genişlik kapısından etkilenmiyor, klip 720×1280 olarak
	kodlanıyor ve 842.115 bayt çıkıyordu — 400 KB politika hedefinin İKİ
	KATINDAN fazla. HLS merdivenindeki `select_ladder` ile aynı hata sınıfı.

	Doğrusu kısa kenarı (480) sabitlemek: yatay kaynakta 854×480, dikey
	kaynakta 480×854 — iki durumda da aynı piksel bütçesi.

	Künye yoksa eski davranışa (genişlik kapısı) düşülür: yönelim
	bilinmiyorken tahmin etmektense kaynağı olduğu gibi bırakmak yeğdir.
	"""
	kisa_kenar = min(spec.width, spec.height) or spec.width
	if facts is None or not facts.width or not facts.height:
		return f"scale='min({spec.width},iw)':-2"
	if facts.height > facts.width:
		return f"scale='min({kisa_kenar},iw)':-2"
	return f"scale=-2:'min({kisa_kenar},ih)'"


def build_preview_cmd(
	src: str,
	dst: str,
	start_s: float,
	duration_s: float,
	spec: PreviewClipSpec,
	crf: int,
	facts: Optional[VideoFacts] = None,
) -> List[str]:
	"""Sessiz klip komutu. `-an` ZORUNLU: klip hover'da oynar, ses saldırgan olur."""
	return [
		"ffmpeg", "-y",
		"-filter_threads", "2",
		"-ss", f"{start_s:.3f}",
		"-t", f"{duration_s:.3f}",
		"-i", src,
		"-an",
		"-vf", preview_scale_filter(spec, facts),
		"-c:v", spec.video_codec,
		"-threads:v", "2",
		"-profile:v", "high",
		"-preset", "medium",
		"-crf", str(crf),
		"-pix_fmt", "yuv420p",
		"-movflags", "+faststart",
		"-progress", "pipe:1", "-nostats",
		dst,
	]


def make_preview_clip(
	src: str,
	dst: str,
	*,
	start_s: float = 0.0,
	spec: Optional[PreviewClipSpec] = None,
	facts: Optional[VideoFacts] = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> PreviewClipResult:
	"""3-6 sn sessiz klip üret; bayt kapısını CRF ve süre merdiveniyle tuttur.

	Merdiven sırası ANLAMLI: önce kalite düşürülür (CRF 28 → 32 → 36), süre
	ancak kalite merdiveni tükenince kısaltılır. Sebep: 6 saniyelik biraz daha
	bulanık bir klip, 3 saniyelik keskin bir klipten daha çok bilgi taşır.

	Kaynak klibi taşıyamayacak kadar kısaysa (`süre - başlangıç < 3 sn`)
	başlangıç öne çekilir; video 3 sn'den kısaysa klip videonun tamamıdır.
	"""
	spec = spec or PreviewClipSpec.from_table()
	facts = facts or probe_modulu.probe(src)
	if not facts.measured:
		raise TranscodeFailed(f"kunye okunamadi: {facts.error}", detay={"error": facts.error})

	en_kisa = min(spec.duration_ladder)
	notlar: List[str] = []
	if facts.duration_s and start_s + en_kisa > facts.duration_s:
		yeni = max(facts.duration_s - en_kisa, 0.0)
		notlar.append(f"baslangic {start_s:.2f} sn -> {yeni:.2f} sn (kaynak {facts.duration_s:.2f} sn)")
		start_s = yeni

	denemeler: List[Dict[str, Any]] = []
	son: Optional[Tuple[float, int, int]] = None
	for sure in spec.duration_ladder:
		gercek_sure = min(sure, facts.duration_s - start_s) if facts.duration_s else sure
		if gercek_sure <= 0:
			continue
		for crf in spec.crf_ladder:
			cmd = build_preview_cmd(src, dst, start_s, gercek_sure, spec, crf, facts)
			try:
				run_ffmpeg(
					cmd,
					timeout=timeout,
					progress_callback=progress_callback,
					cancel_check=cancel_check,
				)
			except ProbeUnavailable as exc:
				raise TranscodeFailed("ffmpeg bulunamadi") from exc
			except TranscodeFailed as exc:
				denemeler.append({"duration_s": gercek_sure, "crf": crf, "error": "ffmpeg dustu"})
				raise
			boyut = os.path.getsize(dst) if os.path.exists(dst) else 0
			denemeler.append({"duration_s": round(gercek_sure, 2), "crf": crf, "bytes": boyut})
			son = (gercek_sure, crf, boyut)
			if boyut <= spec.max_bytes:
				return PreviewClipResult(
					path=dst,
					start_s=start_s,
					duration_s=gercek_sure,
					size_bytes=boyut,
					crf=crf,
					within_task_gate=True,
					within_policy_gate=boyut <= spec.policy_max_bytes,
					attempts=denemeler,
					notes=notlar
					+ (
						[]
						if boyut <= spec.policy_max_bytes
						else [f"politika hedefi {spec.policy_max_bytes} B asildi (zorunlu kapi 1 MB geçildi)"]
					),
				)

	# Merdiven tükendi: dosya duruyor ama kapıyı geçemedi. Hata ATILMAZ —
	# kararı çağıran verir (sözleşme: motor politika kararı vermez).
	gercek_sure, crf, boyut = son or (0.0, spec.crf_ladder[-1], 0)
	return PreviewClipResult(
		path=dst,
		start_s=start_s,
		duration_s=gercek_sure,
		size_bytes=boyut,
		crf=crf,
		within_task_gate=False,
		within_policy_gate=False,
		attempts=denemeler,
		notes=notlar + [f"merdiven tukendi: {boyut} B > {spec.max_bytes} B"],
	)


__all__ = [
	"CODE_POSTER_UNRESOLVED",
	"PosterSpec",
	"PosterResult",
	"PreviewClipSpec",
	"PreviewClipResult",
	"poster_window",
	"poster_retry_window",
	"mean_luma_pct",
	"edge_density_pct",
	"frame_is_meaningful",
	"build_poster_cmd",
	"build_preview_cmd",
	"preview_scale_filter",
	"make_poster",
	"make_preview_clip",
]
