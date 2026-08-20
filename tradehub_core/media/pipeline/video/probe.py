"""T-070 — video künyesi: karar tablosunun okuduğu TÜM değişkenler tek yerde.

**Çözdüğü problem.** Bugün üretimde ffprobe tek yerde ve tek soru için
çağrılıyor: `tradehub_core/media/transcode.py::needs_transcode` yalnız
`stream=width,bit_rate` istiyor (transcode.py:127). Kararın dayandığı diğer
her şey — kare hızı, piksel formatı, kodek, kap, ses akışı, moov atomunun
konumu, kodlama verimliliği — HİÇ ÖLÇÜLMÜYOR. Ölçülmeyen bir değişken üstüne
kural yazılamaz; bu yüzden karar iki eşiğe hapsolmuş durumda.

Bu modül tek bir ffprobe koşumunda karar için gereken her şeyi çıkarır ve
`VideoFacts` içinde donmuş (frozen) bir kayıt olarak döndürür.

**Yeniden yazılmayan.** `transcode.py`'nin ffprobe çağrısı, zaman aşımı
merdiveni ve güvenli-taraf davranışı KORUNUR:

    ffprobe 20 sn  <  ffmpeg 1700 sn  <  kuyruk 1800 sn  <  kayıp eşiği 2700 sn

`FFPROBE_TIMEOUT_SECONDS` doğrudan `media_engine.contracts.video`'dan alınır —
sayı ikinci kez yazılmaz.

**Hata sözleşmesi.** `probe()` HİÇBİR KOŞULDA istisna atmaz. ffprobe yoksa,
dosya bozuksa, kap tanınmıyorsa `measured=False` ve `error` dolu bir kayıt
döner. Kararı `decision.py` verir: karar tablosunda `probe_unavailable`
kuralı bu duruma REJECT diyor, `transcode.py` ise güvenli taraf olarak
TRANSCODE diyordu — fark tabloda `diverges_from_today` alanında yazılı.

**ffprobe'suz ölçülen tek değişken: `moov_at_end`.** ISOBMFF üst düzey atom
sırası saf Python ile okunur (`moov_at_end_of`). Sebep: ffprobe atom sırasını
normal çıktısında vermiyor (`-v trace` gerekiyor, ayrıştırması kırılgan), oysa
soru basit — dosyanın ilk birkaç yüz baytında `moov` mu `mdat` mı önce geliyor.
"""

from __future__ import annotations

import json
import os
import struct
import subprocess
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Tuple

from tradehub_core.media.pipeline.contracts.video import FFPROBE_TIMEOUT_SECONDS, VideoProbe

# ── Kap ailesi eşlemesi ─────────────────────────────────────────────────
#
# ffprobe `format_name` alanında kapı TEK BAŞINA vermiyor; virgülle ayrılmış
# bir aile listesi veriyor ("mov,mp4,m4a,3gp,3g2,mj2"). Karar tablosu tek bir
# değer üstünden kural yazabilsin diye bu liste tek bir aileye indiriliyor.
CONTAINER_FAMILIES: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
	("mp4", ("mp4", "mov", "m4a", "3gp", "3g2", "mj2", "m4v")),
	("webm", ("webm",)),
	("matroska", ("matroska",)),
	("avi", ("avi",)),
	("mpegts", ("mpegts",)),
	("flv", ("flv",)),
	("ogg", ("ogg",)),
)

#: ISOBMFF üst düzey atom taramasında okunacak azami bayt. moov ya da mdat
#: bu sınırdan önce görünmezse karar verilemez (`None`). 64 KB, ftyp+free+moov
#: başlığı için fazlasıyla yeterli; tüm dosyayı okumak 10 MB'lık videoda
#: gereksiz I/O olurdu.
_ATOM_SCAN_MAX_BYTES: int = 64 * 1024


@dataclass(frozen=True)
class VideoFacts:
	"""Karar için gereken ölçülmüş gerçekler. Yorum YOK, karar YOK — yalnız ölçü.

	`measured=False` ise diğer bütün alanlar varsayılan değerindedir ve
	OKUNMAMALIDIR; `error` neyin düştüğünü söyler.
	"""

	path: str = ""
	size_bytes: int = 0
	measured: bool = False
	error: str = ""

	has_video: bool = False
	width: int = 0
	height: int = 0
	duration_s: float = 0.0
	fps: float = 0.0
	video_codec: str = ""
	video_profile: str = ""
	pix_fmt: str = ""
	video_bitrate_bps: int = 0
	format_bitrate_bps: int = 0
	rotation: int = 0
	nb_frames: int = 0

	container: str = ""
	container_family: str = "other"
	nb_streams: int = 0
	moov_at_end: bool = False

	has_audio: bool = False
	audio_codec: str = ""
	audio_bitrate_bps: int = 0
	audio_channels: int = 0
	audio_sample_rate: int = 0

	raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

	# ── Türetilmiş ölçüler ──────────────────────────────────────────────

	@property
	def pixels(self) -> int:
		return self.width * self.height

	@property
	def long_edge(self) -> int:
		return max(self.width, self.height)

	@property
	def short_edge(self) -> int:
		return min(self.width, self.height) if self.width and self.height else 0

	@property
	def bpp(self) -> float:
		"""Piksel başına bit — çözünürlükten ve kare hızından bağımsız verimlilik.

		Ham bitrate 8 Mbps'in verimli mi israf mı olduğunu söyleyemez: 4K'da
		verimli, 720p'de israftır. `bitrate / (genişlik × yükseklik × fps)` bu
		iki boyutu normalleştirir.

		Bölen sıfırsa (ölçülemeyen kare hızı ya da çözünürlük) 0,0 döner —
		karar tablosundaki `bpp > 0,08` kuralı bu durumda TETİKLENMEZ, yani
		ölçülemeyen verimlilik "kötü" sayılmaz. Ölçülemeyen kaynağı zaten
		`probe_unavailable` kuralı yakalar.
		"""
		bolen = self.width * self.height * self.fps
		if bolen <= 0:
			return 0.0
		return self.video_bitrate_bps / bolen

	@property
	def aspect_ratio(self) -> float:
		return (self.width / self.height) if self.height else 0.0

	def variables(self) -> Dict[str, Any]:
		"""Karar tablosunun okuduğu düz değişken sözlüğü.

		`decision.py` YALNIZ bu sözlüğü görür. Tabloda geçen her değişken adı
		burada bir anahtar olmak zorundadır; olmayan ad yükleme anında hata
		verir (yazım hatası sessizce "eşleşmedi"ye dönüşmesin).
		"""
		return {
			"measured": self.measured,
			"has_video": self.has_video,
			"width": self.width,
			"height": self.height,
			"pixels": self.pixels,
			"long_edge": self.long_edge,
			"short_edge": self.short_edge,
			"duration_s": self.duration_s,
			"fps": self.fps,
			"video_codec": self.video_codec,
			"video_profile": self.video_profile,
			"pix_fmt": self.pix_fmt,
			"video_bitrate_bps": self.video_bitrate_bps,
			"format_bitrate_bps": self.format_bitrate_bps,
			"bpp": self.bpp,
			"container": self.container,
			"container_family": self.container_family,
			"has_audio": self.has_audio,
			"audio_codec": self.audio_codec,
			"audio_bitrate_bps": self.audio_bitrate_bps,
			"audio_channels": self.audio_channels,
			"moov_at_end": self.moov_at_end,
			"size_bytes": self.size_bytes,
			"rotation": self.rotation,
			"nb_streams": self.nb_streams,
		}

	def to_contract(self) -> VideoProbe:
		"""`contracts.video.VideoProbe`'a indirge — sözleşme uyumu için.

		Sözleşmedeki tip bilinçli olarak DAR: motorun dış yüzeyi yalnız
		sözleşmedeki alanları vaat eder. Karar tablosunun ihtiyaç duyduğu
		fazladan alanlar (pix_fmt, moov_at_end, profil…) bu katmanda kalır.
		"""
		return VideoProbe(
			width=self.width,
			height=self.height,
			duration_s=self.duration_s,
			bitrate_bps=self.video_bitrate_bps or self.format_bitrate_bps,
			frame_rate=self.fps,
			container=self.container_family,
			video_codec=self.video_codec,
			audio_codec=self.audio_codec,
			has_audio=self.has_audio,
			measured=self.measured,
		)

	def as_dict(self) -> Dict[str, Any]:
		"""Raporlanabilir sözlük — `raw` hariç, türetilmiş ölçüler dahil."""
		d = asdict(self)
		d.pop("raw", None)
		d.update({"pixels": self.pixels, "bpp": round(self.bpp, 6), "aspect_ratio": round(self.aspect_ratio, 4)})
		return d


# ── Yardımcılar ─────────────────────────────────────────────────────────


def parse_frame_rate(text: str) -> float:
	"""ffprobe kesirli kare hızını (`"30000/1001"`) ondalığa çevirir.

	ffprobe kare hızını KESİR verir çünkü NTSC hızları (29,97 = 30000/1001)
	ondalıkta tam gösterilemez. Bölen 0 ya da metin ayrıştırılamıyorsa 0,0
	döner — uydurma yapılmaz.
	"""
	if not text:
		return 0.0
	try:
		if "/" in text:
			pay, bolen = text.split("/", 1)
			bolen_f = float(bolen)
			if bolen_f == 0:
				return 0.0
			return float(pay) / bolen_f
		return float(text)
	except (TypeError, ValueError):
		return 0.0


def container_family_of(format_name: str) -> str:
	"""ffprobe'un virgüllü kap listesini tek bir aileye indirger."""
	parcalar = {p.strip().lower() for p in (format_name or "").split(",") if p.strip()}
	for aile, uyeler in CONTAINER_FAMILIES:
		if parcalar & set(uyeler):
			return aile
	return "other"


def moov_at_end_of(path: str) -> bool:
	"""ISOBMFF üst düzey atom sırasını okur: `mdat`, `moov`'dan önce mi?

	True → aşamalı indirmede oynatıcı ilk kareyi göstermeden önce dosyanın
	sonunu indirmek zorunda kalır (`-movflags +faststart` bunu düzeltir).

	mp4 ailesinden OLMAYAN kaplarda soru anlamsızdır ve **False** döner:
	`container_not_mp4` kuralı zaten o dosyayı REMUX'a yollar, `moov_at_end`
	kuralının ikinci kez tetiklenmesi kararı değiştirmez ama raporu kirletir.

	Dosya okunamıyorsa da False döner — okunamayan dosyayı `probe()` zaten
	`measured=False` ile işaretler.
	"""
	try:
		boyut = os.path.getsize(path)
		with open(path, "rb") as f:
			pos = 0
			while pos < boyut and pos < _ATOM_SCAN_MAX_BYTES:
				f.seek(pos)
				baslik = f.read(8)
				if len(baslik) < 8:
					return False
				kutu_boyu = struct.unpack(">I", baslik[:4])[0]
				tip = baslik[4:8].decode("latin-1")
				if kutu_boyu == 1:
					# 64-bit uzunluk: 'largesize' başlığın hemen ardından gelir.
					uzun = f.read(8)
					if len(uzun) < 8:
						return False
					kutu_boyu = struct.unpack(">Q", uzun)[0]
				elif kutu_boyu == 0:
					# Son kutu — dosyanın sonuna kadar uzanır.
					kutu_boyu = boyut - pos
				if tip == "moov":
					return False
				if tip == "mdat":
					return True
				if kutu_boyu < 8:
					return False
				pos += kutu_boyu
	except (OSError, struct.error, UnicodeDecodeError):
		return False
	return False


def ffprobe_json(path: str, *, timeout: int = FFPROBE_TIMEOUT_SECONDS) -> Dict[str, Any]:
	"""Tek ffprobe koşumu — akışlar + kap künyesi.

	`transcode.py:124-130`'daki çağrının GENİŞLETİLMİŞ hâli: orada
	`stream=width,bit_rate` isteniyordu, burada tüm akış ve kap alanları.
	İkinci bir koşum eklenmiyor — ffprobe süreç başlatma maliyeti, istenen
	alan sayısından çok daha pahalı.

	Hata durumunda istisna ATAR; sarmalayan `probe()` yakalar.
	"""
	cmd = [
		"ffprobe", "-v", "error",
		"-show_streams", "-show_format",
		"-of", "json",
		path,
	]
	sonuc = subprocess.run(cmd, check=True, capture_output=True, timeout=timeout)
	return json.loads(sonuc.stdout or b"{}")


def _int(value: Any, default: int = 0) -> int:
	try:
		return int(value)
	except (TypeError, ValueError):
		return default


def _float(value: Any, default: float = 0.0) -> float:
	try:
		return float(value)
	except (TypeError, ValueError):
		return default


def _rotation_of(stream: Dict[str, Any]) -> int:
	"""Döndürme açısı — iki ayrı yerde saklanabiliyor.

	Modern ffprobe `side_data_list[].rotation` (negatif dereceler) yazıyor;
	eski dosyalarda `tags.rotate` (pozitif metin) var. İkisi de yoksa 0.
	"""
	for sd in stream.get("side_data_list") or []:
		if "rotation" in sd:
			return _int(sd.get("rotation"))
	return _int((stream.get("tags") or {}).get("rotate"))


def probe(path: str, *, timeout: int = FFPROBE_TIMEOUT_SECONDS) -> VideoFacts:
	"""Videonun künyesini çıkar. **Hiçbir koşulda istisna atmaz.**

	ffprobe yok / dosya yok / kap tanınmıyor / video akışı yok durumlarının
	hepsinde `measured=False` ve `error` dolu bir `VideoFacts` döner.
	"""
	try:
		size_bytes = os.path.getsize(path)
	except OSError as exc:
		return VideoFacts(path=path, error=f"dosya okunamadi: {exc}")

	try:
		veri = ffprobe_json(path, timeout=timeout)
	except FileNotFoundError:
		return VideoFacts(path=path, size_bytes=size_bytes, error="ffprobe yok")
	except subprocess.TimeoutExpired:
		return VideoFacts(path=path, size_bytes=size_bytes, error=f"ffprobe zaman asimi ({timeout} sn)")
	except subprocess.CalledProcessError as exc:
		ayrinti = (exc.stderr or b"").decode("utf-8", "replace").strip()[:300]
		return VideoFacts(path=path, size_bytes=size_bytes, error=f"ffprobe hata: {ayrinti}")
	except (ValueError, json.JSONDecodeError) as exc:
		return VideoFacts(path=path, size_bytes=size_bytes, error=f"ffprobe ciktisi ayristirilamadi: {exc}")

	streams = veri.get("streams") or []
	fmt = veri.get("format") or {}
	videolar = [s for s in streams if s.get("codec_type") == "video"]
	sesler = [s for s in streams if s.get("codec_type") == "audio"]

	# "Kapak görseli" tuzağı: mp3/mp4 içindeki gömülü albüm kapağı ffprobe'da
	# codec_type=video görünür (png/mjpeg, disposition.attached_pic=1). Onu
	# video akışı saymak, ses dosyasını videoymuş gibi işletirdi.
	videolar = [s for s in videolar if not (s.get("disposition") or {}).get("attached_pic")]

	if not videolar:
		return VideoFacts(
			path=path,
			size_bytes=size_bytes,
			measured=False,
			has_video=False,
			container=str(fmt.get("format_name") or ""),
			container_family=container_family_of(str(fmt.get("format_name") or "")),
			nb_streams=_int(fmt.get("nb_streams")),
			error="video akisi yok",
			raw=veri,
		)

	v = videolar[0]
	a = sesler[0] if sesler else {}

	format_bitrate = _int(fmt.get("bit_rate"))
	audio_bitrate = _int(a.get("bit_rate"))
	video_bitrate = _int(v.get("bit_rate"))
	if not video_bitrate:
		# Bazı kaplar (matroska, kimi mp4 yazıcıları) akış başına bitrate
		# yazmaz. Kap bitrate'inden ses payını düşmek, hiç ölçmemekten iyidir —
		# ama uydurma da değildir: iki ölçülmüş sayının farkıdır.
		video_bitrate = max(format_bitrate - audio_bitrate, 0)

	fps = parse_frame_rate(str(v.get("avg_frame_rate") or "")) or parse_frame_rate(
		str(v.get("r_frame_rate") or "")
	)
	format_name = str(fmt.get("format_name") or "")
	aile = container_family_of(format_name)

	return VideoFacts(
		path=path,
		size_bytes=size_bytes,
		measured=True,
		has_video=True,
		width=_int(v.get("width")),
		height=_int(v.get("height")),
		duration_s=_float(fmt.get("duration")) or _float(v.get("duration")),
		fps=fps,
		video_codec=str(v.get("codec_name") or ""),
		video_profile=str(v.get("profile") or ""),
		pix_fmt=str(v.get("pix_fmt") or ""),
		video_bitrate_bps=video_bitrate,
		format_bitrate_bps=format_bitrate,
		rotation=_rotation_of(v),
		nb_frames=_int(v.get("nb_frames")),
		container=format_name,
		container_family=aile,
		nb_streams=_int(fmt.get("nb_streams"), len(streams)),
		moov_at_end=moov_at_end_of(path) if aile == "mp4" else False,
		has_audio=bool(sesler),
		audio_codec=str(a.get("codec_name") or ""),
		audio_bitrate_bps=audio_bitrate,
		audio_channels=_int(a.get("channels")),
		audio_sample_rate=_int(a.get("sample_rate")),
		raw=veri,
	)


def ffprobe_available() -> bool:
	"""ffprobe çalıştırılabiliyor mu — testlerin atlama kararı için."""
	try:
		subprocess.run(["ffprobe", "-version"], capture_output=True, timeout=10, check=True)
		return True
	except (OSError, subprocess.SubprocessError):
		return False


__all__ = [
	"VideoFacts",
	"CONTAINER_FAMILIES",
	"probe",
	"ffprobe_json",
	"ffprobe_available",
	"parse_frame_rate",
	"container_family_of",
	"moov_at_end_of",
]
