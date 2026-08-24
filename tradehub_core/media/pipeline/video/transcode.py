"""T-072 — H.264 High + AAC 128k + faststart üretimi, fayda kapısıyla (INV-05).

**Dokümanla bugünkü kod arasındaki FARK — ve gerekçesi.**
Bugünkü hat VP9/Opus/WebM üretiyor (`tradehub_core/media/transcode.py:357-360`:
`libvpx-vp9`, `-crf 32`, `libopus`). Bu modül H.264 High + AAC 128k + mp4
üretiyor. Fark bilinçlidir, üç gerekçesi var:

1. **UYUMLULUK.** VP9/WebM Safari'de `<video>` ile güvenilir oynamıyor (macOS'ta
   kısmi, iOS'ta yok). Oynamayan bir video, %25 daha küçük olmasının hiçbir
   değeri olmadan sıfır izlenir.
2. **YANLIŞ ETİKET.** Bugünkü hat WebM baytlarını `.mp4` uzantılı ADRESE yazıyor
   (`transcode.py:344` `dst_path = src_path + ".transcoding.webm"` → `:366`
   `os.replace(dst_path, src_path)`). nginx Content-Type'ı uzantıdan türettiği
   için `video/mp4` başlığıyla WebM baytı servis ediliyor. H.264/mp4 hedefi bu
   uyuşmazlığı kaynağında bitirir.
3. **DONANIM.** H.264 kod çözme her telefonda donanımda; VP9 orta segment
   Android'de yazılımda — pil ve ısı maliyeti alıcıda.

**BEDELİ ödeniyor:** aynı kalitede H.264, VP9'dan ~%20-30 daha büyük dosya
üretir. Ölçülen değerler bu modülün altındaki ölçüm tablosunda. İleride iki
çıktı birden (mp4 birincil + webm ikincil `<source>`) üretilebilir; karar
tablosunda `targets.webm_fallback` yer tutucu olarak duruyor, FAZ 7'de
ÜRETİLMİYOR.

**FAYDA KAPISI (INV-05) — bugünkü hattaki en somut açık.**
`_run_transcode` çıktıyı KOŞULSUZ yerine yazıyor (`transcode.py:366`
`os.replace`). Boyut kapısı yok: zaten iyi sıkıştırılmış bir kaynağı yeniden
kodlamak dosyayı BÜYÜTEBİLİR ve her hâlükârda nesil kaybı yaratır — bu bugün
sessizce oluyor (`product-video.json` `video.transcode.size_gate_missing_today`
bunu kayda geçirmiş). Bu modülde çıktı, kaynağın en fazla %90'ı değilse ATILIR
ve kaynak korunur (`TranscodeResult.accepted=False`). REMUX bu kapıdan MUAFTIR:
onun amacı bayt kazanmak değil ilk kareyi hızlandırmaktır ve `+faststart`
dosyayı birkaç KB büyütebilir.

**ATOMİKLİK.** Çıktı önce geçici dosyaya yazılır, yalnız fayda kapısını
geçtiyse `os.replace` ile hedefe taşınır (NFR-041). Yarım dosya asla
görünmez. Bu davranış bugünkü hattan ALINDI, yeniden icat edilmedi.

**KUYRUK BU MODÜLÜN İŞİ DEĞİL.** Retry, backoff, dead-letter ve takılı iş
süpürücüsü `tradehub_core/media/transcode.py` + `media/jobs.py` içinde ÇALIŞIYOR
ve yeniden yazılmıyor. Buradaki her şey saf dönüşümdür: girdi dosya, çıktı
dosya. `frappe` import edilmez.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.errors import (
	SEBEP_TRANSCODE_FAILED,
	ProbeUnavailable,
	TranscodeFailed,
)
from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS
from tradehub_core.media.pipeline.security import isolation
from tradehub_core.media.pipeline.video import probe as probe_modulu
from tradehub_core.media.pipeline.video.decision import (
	ACTION_PASSTHROUGH,
	ACTION_REJECT,
	ACTION_REMUX,
	ACTION_TRANSCODE,
	VideoDecision,
	default_table,
)
from tradehub_core.media.pipeline.video.probe import VideoFacts

#: `nice -n 10` bugünkü hattan korunuyor (transcode.py:349): transcode
#: CPU-yoğun; sipariş/ödeme gibi kullanıcı-görünür kuyrukları aç bırakmamalı.
NICE_PREFIX: Tuple[str, ...] = ("nice", "-n", "10")


@dataclass(frozen=True)
class H264Spec:
	"""Karar tablosundaki `targets.h264_primary` bloğunun kod karşılığı.

	Değerler JSON'dan gelir; bu sınıf yalnız varsayılan taşır ki tablo
	okunamadığında bile modül import edilebilsin (testler bunu kullanır).
	"""

	id: str = "video_1280_h264"
	max_width: int = 1280
	container: str = "mp4"
	video_codec: str = "libx264"
	profile: str = "high"
	level: str = "4.0"
	crf: int = 23
	preset: str = "medium"
	#: Hız denetimi. `capped_crf` = CRF + `-maxrate`/`-bufsize` tavanı.
	#: `crf` = tavansız (ölçülen kusurlu davranış; vacuity kontrolü için tutuluyor).
	rate_control: str = "capped_crf"
	maxrate_kbps: int = 2500
	min_maxrate_kbps: int = 300
	#: Tavan INV-05 fayda kapısından TÜRETİLİR (bkz. `rate_ceiling_kbps`).
	#: False yapılırsa yalnız mutlak tavan (`maxrate_kbps`) uygulanır.
	budget_from_benefit_gate: bool = True
	bufsize_multiplier: float = 2.0
	pix_fmt: str = "yuv420p"
	frame_rate_cap: int = 30
	keyframe_interval_s: float = 2.0
	faststart: bool = True
	audio_codec: str = "aac"
	audio_bitrate_kbps: int = 128
	audio_channels: int = 2
	audio_sample_rate: int = 48000
	#: Ayrık video worker'ı 2 CPU ile sınırlı; daha çok x264 thread'i sanal
	#: bellek ve scheduler maliyeti üretir, gerçek throughput kazandırmaz.
	encoder_threads: int = 2

	@classmethod
	def from_targets(cls, targets: Mapping[str, Any]) -> "H264Spec":
		t = dict((targets or {}).get("h264_primary") or {})
		v = cls()
		return cls(
			id=str(t.get("id", v.id)),
			max_width=int(t.get("max_width", v.max_width)),
			container=str(t.get("container", v.container)),
			video_codec=str(t.get("video_codec", v.video_codec)),
			profile=str(t.get("profile", v.profile)),
			level=str(t.get("level", v.level)),
			crf=int(t.get("crf", v.crf)),
			preset=str(t.get("preset", v.preset)),
			rate_control=str(t.get("rate_control", v.rate_control)),
			maxrate_kbps=int(t.get("maxrate_kbps", v.maxrate_kbps)),
			min_maxrate_kbps=int(t.get("min_maxrate_kbps", v.min_maxrate_kbps)),
			budget_from_benefit_gate=bool(
				t.get("budget_from_benefit_gate", v.budget_from_benefit_gate)
			),
			bufsize_multiplier=float(t.get("bufsize_multiplier", v.bufsize_multiplier)),
			pix_fmt=str(t.get("pix_fmt", v.pix_fmt)),
			frame_rate_cap=int(t.get("frame_rate_cap", v.frame_rate_cap)),
			keyframe_interval_s=float(t.get("keyframe_interval_s", v.keyframe_interval_s)),
			faststart=bool(t.get("faststart", v.faststart)),
			audio_codec=str(t.get("audio_codec", v.audio_codec)),
			audio_bitrate_kbps=int(t.get("audio_bitrate_kbps", v.audio_bitrate_kbps)),
			audio_channels=int(t.get("audio_channels", v.audio_channels)),
			audio_sample_rate=int(t.get("audio_sample_rate", v.audio_sample_rate)),
			encoder_threads=max(1, int(t.get("encoder_threads", v.encoder_threads))),
		)

	@classmethod
	def from_table(cls) -> "H264Spec":
		return cls.from_targets(default_table().targets)


@dataclass
class TranscodeResult:
	"""Bir dönüşümün sonucu — ölçülen her şey, karar dahil.

	`accepted=False` "hata" DEĞİLDİR: ffmpeg başarıyla çalıştı ama çıktı fayda
	kapısını geçemedi, dolayısıyla kaynak korundu. Bu ayrım denetim için
	önemli: "transcode başarısız" ile "transcode gereksizdi" aynı şey değil.
	"""

	action: str
	src_path: str
	out_path: str = ""
	src_bytes: int = 0
	out_bytes: int = 0
	accepted: bool = False
	kept_source: bool = False
	wall_s: float = 0.0
	cmd: Tuple[str, ...] = ()
	quality: Dict[str, Any] = field(default_factory=dict)
	notes: List[str] = field(default_factory=list)
	peak_rss_bytes: int = 0
	cpu_user_s: float = 0.0
	cpu_system_s: float = 0.0
	limits_applied: Tuple[str, ...] = ()
	#: Bu sonuç bir geri çekilmenin ürünüyse, düşen ilk aksiyonun adı
	#: (bugün yalnız `TRANSCODE`). Boş string = geri çekilme olmadı.
	fallback_from: str = ""

	@property
	def saving_ratio(self) -> float:
		"""Kazanılan bayt oranı. Negatif = çıktı kaynaktan BÜYÜK."""
		if not self.src_bytes:
			return 0.0
		return (self.src_bytes - self.out_bytes) / self.src_bytes

	def as_dict(self) -> Dict[str, Any]:
		return {
			"action": self.action,
			"accepted": self.accepted,
			"kept_source": self.kept_source,
			"fallback_from": self.fallback_from,
			"src_bytes": self.src_bytes,
			"out_bytes": self.out_bytes,
			"saving_ratio": round(self.saving_ratio, 4),
			"wall_s": round(self.wall_s, 2),
			"peak_rss_bytes": self.peak_rss_bytes,
			"cpu_user_s": round(self.cpu_user_s, 3),
			"cpu_system_s": round(self.cpu_system_s, 3),
			"limits_applied": list(self.limits_applied),
			"quality": dict(self.quality),
			"notes": list(self.notes),
		}


# ── ffmpeg komut kurulumu ───────────────────────────────────────────────


def _scale_filter(max_width: int) -> str:
	"""`scale='min(1280,iw)':-2` — büyütme YAPMAZ, tek sayıya yuvarlamaz.

	Tek tırnak KASITLI ve bugünkü hattan alınmış: `min(1280,iw)` içindeki
	virgül ffmpeg filtergraph'ta zincir ayracıdır; tırnaklanmazsa filtre
	"min(1280" olarak kesilip patlar (transcode.py:353-355 bu hatayı gerçek
	ffmpeg ile yaşamış ve yorumla kayda geçirmiş).

	`-2`: yükseklik en-boy oranından hesaplanır ve 2'nin katına yuvarlanır —
	yuv420p tek sayılı boyut kabul etmez.
	"""
	return f"scale='min({max_width},iw)':-2"


def _video_filters(spec: H264Spec, facts: Optional[VideoFacts]) -> List[str]:
	"""Teslim filtre zinciri; HDR kaynakları SDR/BT.709'a tonemap eder.

	PQ/HLG etiketi taşıyan 10-bit görüntüyü yalnız ``yuv420p``'ye çevirmek
	parlaklıkları kırpar ve renkleri soldurur. Lineer ışıkta tonemap yapıp
	çıktıyı açık BT.709 etiketleriyle teslim etmek, bu sessiz bozulmayı önler.
	"""
	filtreler: List[str] = []
	if facts and facts.is_hdr:
		filtreler.extend(
			[
				"zscale=t=linear:npl=100",
				"format=gbrpf32le",
				"zscale=p=bt709",
				"tonemap=tonemap=hable:desat=0",
				"zscale=t=bt709:m=bt709:r=tv",
				"format=yuv420p",
			]
		)
	filtreler.append(_scale_filter(spec.max_width))
	if facts and facts.fps > spec.frame_rate_cap:
		filtreler.append(f"fps={spec.frame_rate_cap}")
	return filtreler


def rate_ceiling_kbps(
	spec: H264Spec,
	facts: Optional[VideoFacts] = None,
	*,
	min_saving: Optional[float] = None,
) -> int:
	"""Çıktının bitrate TAVANI — **INV-05 fayda kapısından türetilir**.

	**Neden bir tavan gerekiyor.** CRF bir KALİTE hedefidir, bayt tavanı değil.
	Kaynak zaten hedef kaliteden düşük bir bitrate'te kodlanmışsa CRF 23
	kaynaktan çok daha fazla bit harcar. Ölçüldü (gerçek kütüphane, 2026-08-19):
	1.152,7 kbps'lik gerçek bir 1080p dosya CRF 23 ile kaynağın **1,704 katına**
	çıktı ve fayda kapısından düştü — hat hiçbir şey teslim etmedi.

	**Neden tavan kapıdan TÜRETİLİYOR, sabit bir çarpandan değil.** Kapının
	istediği tek şey belli: dosya kaynağın en fazla `(1 − min_saving_ratio)`
	katı olacak. Bu bir BAYT BÜTÇESİDİR ve doğrudan bir bitrate bütçesine
	çevrilebilir. Sabit bir çarpan (ör. "kaynağın 0,75 katı") aynı işi yapar
	görünür ama iki yerde yanlıştır:

	  * **Ses payını görmez.** 320 kbps sesli bir kaynakta çıktı sesi 128 kbps'e
	    inecektir; kazancın 192 kbps'i sesten gelir ve video o kadar daha
	    rahat nefes alabilir. Sabit çarpan bu payı videodan da kısar —
	    kazanılmış baytı ikinci kez keser, karşılığında görüntü kalitesi verir.
	  * **Sessiz kaynakta bütçeyi boşa harcar.** Ses yoksa çıkarılacak bir şey
	    de yoktur; bütçenin tamamı videonundur.

	Bu yüzden: `tavan = kaynak_toplam_kbps × (1 − min_saving_ratio) − çıktı_ses_kbps`.
	Kapının izin verdiği en YÜKSEK kalite budur; daha aşağısı gereksiz kalite
	kaybı, daha yukarısı kapıdan düşmek demektir.

	**Mutlak tavan (`maxrate_kbps`) neden hâlâ var.** 8 Mbps'lik şişirilmiş bir
	kaynağın kapı bütçesi 7,2 Mbps'tir; 1280 genişlikte bu hâlâ israftır.

	**Taban (`min_maxrate_kbps`) neden var.** 200 kbps'lik bir kaynağı 150 kbps
	tavana sıkıştırmak bloklaşma üretir. Taban yüzünden kapıyı geçemeyen dosya
	ATILIR ve kaynak korunur — bu doğru sonuçtur, kazanılacak bayt yoktur.

	Kaynak bitrate'i ölçülemediyse mutlak tavan kullanılır; tahmin edilmez.
	"""
	tavan = max(int(spec.maxrate_kbps), 1)
	if not spec.budget_from_benefit_gate or facts is None:
		return tavan

	toplam_kbps = int(facts.format_bitrate_bps or 0) // 1000
	if toplam_kbps <= 0:
		toplam_kbps = (int(facts.video_bitrate_bps or 0) + int(facts.audio_bitrate_bps or 0)) // 1000
	if toplam_kbps <= 0:
		return tavan

	oran = min_saving_ratio() if min_saving is None else float(min_saving)
	cikti_ses = spec.audio_bitrate_kbps if facts.has_audio else 0
	butce = int(round(toplam_kbps * (1.0 - oran))) - cikti_ses
	return max(min(tavan, butce), int(spec.min_maxrate_kbps))


def _rate_control_args(spec: H264Spec, facts: Optional[VideoFacts] = None) -> List[str]:
	"""Hız denetimi argümanları. Varsayılan **capped CRF** (`hls.py` ile aynı desen).

	`rate_control: "crf"` tavansız eski davranışı geri getirir — düzeltmeyi
	geri alıp KIRMIZI göstermek için tabloda tek satır yeter.
	"""
	if spec.rate_control == "crf":
		return ["-crf", str(spec.crf)]
	tavan = rate_ceiling_kbps(spec, facts)
	tampon = max(int(round(tavan * spec.bufsize_multiplier)), tavan)
	return [
		"-crf", str(spec.crf),
		"-maxrate", f"{tavan}k",
		"-bufsize", f"{tampon}k",
	]


def build_transcode_cmd(
	src: str,
	dst: str,
	spec: H264Spec,
	facts: Optional[VideoFacts] = None,
	*,
	nice: bool = True,
) -> List[str]:
	"""H.264 komutunu kur. Kaynak künyesi verilirse komut ona göre daralır.

	Künye neden gerekiyor:
	  * ses akışı YOKSA `-an` yazılır. Ses akışı olmayan dosyaya `-c:a aac`
	    vermek bazı ffmpeg sürümlerinde "Stream map matches no streams" ile
	    düşer; fixture `video_silent_noaudio_720p.mp4` tam olarak bu durum.
	  * kare hızı tavanın ALTINDAYSA `fps` filtresi hiç eklenmez — 25 fps
	    kaynağı 30'a çıkarmak kare çoğaltır, bayt harcar, hiçbir şey kazandırmaz.
	  * GOP uzunluğu gerçek kare hızından hesaplanır (2 sn × fps).
	"""
	kaynak_fps = facts.fps if facts and facts.fps else float(spec.frame_rate_cap)
	hedef_fps = min(kaynak_fps, float(spec.frame_rate_cap)) or float(spec.frame_rate_cap)

	filtreler = _video_filters(spec, facts)

	gop = max(int(round(hedef_fps * spec.keyframe_interval_s)), 1)

	cmd: List[str] = list(NICE_PREFIX) if nice else []
	cmd += [
		"ffmpeg", "-y",
		"-filter_threads", str(spec.encoder_threads),
		"-filter_complex_threads", str(spec.encoder_threads),
		"-i", src,
	]
	# İlk video + (varsa) ilk ses. `0:a:0?` sondaki soru işareti "yoksa sorun
	# değil" demek; fazladan akışlar (ikinci dil, altyazı, veri) düşürülür.
	cmd += ["-map", "0:v:0"]
	if facts is None or facts.has_audio:
		cmd += ["-map", "0:a:0?"]
	cmd += ["-vf", ",".join(filtreler)]
	cmd += [
		"-c:v", spec.video_codec,
		"-threads:v", str(spec.encoder_threads),
		"-profile:v", spec.profile,
		"-level:v", spec.level,
		"-preset", spec.preset,
	]
	# Hız denetimi: CRF tek başına bayt TAVANI vermez. Ölçülen kusur ve
	# gerekçesi `rate_ceiling_kbps` docstring'inde + tablonun
	# `targets.h264_primary.rate_control_why` bloğunda.
	cmd += _rate_control_args(spec, facts)
	cmd += [
		"-pix_fmt", spec.pix_fmt,
		"-g", str(gop),
		"-keyint_min", str(gop),
		# `-sc_threshold 0`: sahne kesiminde ekstra anahtar kare açmayı kapatır.
		# HLS'te segment sınırlarının anahtar kareye denk gelmesi buna bağlı
		# (hls.py aynı GOP'u kullanır); tek dosyada da bitrate'i öngörülebilir
		# kılar.
		"-sc_threshold", "0",
	]
	if facts and facts.is_hdr:
		cmd += [
			"-color_primaries", "bt709",
			"-color_trc", "bt709",
			"-colorspace", "bt709",
		]
	if facts is None or facts.has_audio:
		cmd += [
			"-c:a", spec.audio_codec,
			"-b:a", f"{spec.audio_bitrate_kbps}k",
			"-ac", str(spec.audio_channels),
			"-ar", str(spec.audio_sample_rate),
		]
	else:
		# Ses akışı yok: `-an` açıkça yazılır. Bugünkü hat bunu yapmıyor ve
		# yalnız `-c:a libopus` veriyor (transcode.py:359-360) — sessiz
		# dosyada bu şansa kalmış bir davranıştır.
		cmd += ["-an"]
	if spec.faststart:
		cmd += ["-movflags", "+faststart"]
	cmd += ["-progress", "pipe:1", "-nostats"]
	cmd += [dst]
	return cmd


def build_remux_cmd(src: str, dst: str, *, nice: bool = True) -> List[str]:
	"""Akış kopyası + faststart. Yeniden kodlama YOK.

	Maliyet farkı gerçek: kopyalama I/O sınırlı (saniyeler), kodlama CPU
	sınırlı (dakikalar). Bugünkü hatta bu aksiyon HİÇ YOK.
	"""
	cmd: List[str] = list(NICE_PREFIX) if nice else []
	cmd += [
		"ffmpeg", "-y", "-i", src,
		"-map", "0:v:0", "-map", "0:a:0?",
		"-c", "copy",
		"-movflags", "+faststart",
		"-progress", "pipe:1", "-nostats",
		dst,
	]
	return cmd


# ── Koşum ───────────────────────────────────────────────────────────────


def _run(
	cmd: Sequence[str],
	*,
	timeout: int,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> isolation.IsolationResult:
	"""ffmpeg'i rlimit altında çalıştır ve sözleşme hatalarına çevir.

	Sözleşme (contracts/video.py) `subprocess` hatalarının SIZMASINI ihlal
	sayıyor: ffmpeg'in imajdan kalkması worker'ı çökertmemeli, kodlu bir hata
	olarak görünmelidir.
	"""
	limitler = isolation.VIDEO_LIMITS.with_(wall_timeout_s=float(timeout), nice=None)
	sonuc = isolation.run_command(
		list(cmd),
		limits=limitler,
		progress_callback=progress_callback,
		cancel_check=cancel_check,
	)
	if sonuc.ok:
		return sonuc
	if sonuc.sebep == isolation.SEBEP_SPAWN_FAILED:
		raise ProbeUnavailable(
			"ffmpeg bulunamadi veya baslatilamadi",
			detay={"isolation_reason": sonuc.sebep, "exception": sonuc.exception or {}},
		)
	ayrinti = (sonuc.stderr or b"").decode("utf-8", "replace").strip()
	mesajlar = {
		isolation.SEBEP_TIMEOUT: f"ffmpeg zaman asimi ({timeout} sn)",
		isolation.SEBEP_MEMORY: "ffmpeg bellek limiti asildi",
		isolation.SEBEP_CPU: "ffmpeg CPU limiti asildi",
		isolation.SEBEP_CANCELLED: "ffmpeg isi iptal edildi",
		isolation.SEBEP_KILLED: "ffmpeg izole sureci olduruldu",
	}
	throw = TranscodeFailed(
		mesajlar.get(sonuc.sebep, "ffmpeg basarisiz oldu"),
		kod=f"media_{SEBEP_TRANSCODE_FAILED}",
		retryable=sonuc.sebep in isolation.RETRYABLE_SEBEPLER,
		detay={
			"isolation_reason": sonuc.sebep,
			"returncode": sonuc.exit_code,
			"signal": sonuc.signal_no,
			"stderr_tail": ayrinti[-800:],
			"duration_ms": sonuc.duration_ms,
			"peak_rss_bytes": sonuc.peak_rss_bytes,
			"cpu_s": round(sonuc.cpu_user_s + sonuc.cpu_system_s, 3),
		},
	)
	raise throw


#: `_run`'in genel adı. `hls.py` de ffmpeg'i aynı hata sözleşmesiyle
#: çalıştırmalı; alt çizgili adı dışarıdan çağırmak yerine tek bir genel ad
#: veriliyor (iki modül iki ayrı `subprocess.run` sarmalayıcısı taşımasın).
run_ffmpeg = _run


def _temp_path(dst: str) -> str:
	"""Geçici çıktı yolu — hedefle AYNI dizinde olmalı.

	`os.replace` yalnız aynı dosya sisteminde atomiktir; `/tmp` ayrı bir
	bağlama noktasıysa taşıma atomikliğini kaybeder.
	"""
	return f"{dst}.part{os.path.splitext(dst)[1] or '.mp4'}"


def min_saving_ratio(targets: Optional[Mapping[str, Any]] = None) -> float:
	"""INV-05 fayda kapısı oranı — tablodan okunur, koda gömülmez."""
	t = targets if targets is not None else default_table().targets
	return float(((t or {}).get("benefit_gate") or {}).get("min_saving_ratio", 0.1))


def max_duration_delta_s(targets: Optional[Mapping[str, Any]] = None) -> float:
	"""Kaynak ↔ çıktı süre farkı tavanı (saniye) — tablodan okunur."""
	t = targets if targets is not None else default_table().targets
	return float(((t or {}).get("quality_gate") or {}).get("max_duration_delta_s", 0.1))


def max_av_sync_delta_s(targets: Optional[Mapping[str, Any]] = None) -> float:
	"""Kaynak ↔ çıktı A/V ofset değişimi tavanı — tablodan okunur."""
	t = targets if targets is not None else default_table().targets
	return float(((t or {}).get("quality_gate") or {}).get("max_av_sync_delta_s", 0.1))


def first_frame_luma_range(targets: Optional[Mapping[str, Any]] = None) -> Tuple[float, float]:
	"""Teslimin ilk karesi için siyah/beyaz luma sınırları — tablodan."""
	t = targets if targets is not None else default_table().targets
	k = (t or {}).get("quality_gate") or {}
	return (float(k.get("first_frame_luma_min_pct", 1.0)), float(k.get("first_frame_luma_max_pct", 99.0)))


def vmaf_min(targets: Optional[Mapping[str, Any]] = None) -> float:
	"""Hedef VMAF eşiği — tablodan okunur, koda gömülmez.

	2026-08-19'a kadar imajdaki ffmpeg libvmaf'sızdı ve eşik yalnız kâğıt
	üstündeydi. Yeni imaj (ffmpeg n8.1.2) libvmaf'lı — ÖLÇÜLDÜ:
	`vmaf_available()` True, ilk gerçek ölçüm 89,34 (rapor 81 §3/4). Eşik
	artık `transcode()` içindeki kalite kapısında UYGULANIYOR (W7): kapının
	altında kalan çıktı ATILIR ve kaynak korunur. Eşik DEĞERİ tablonundur;
	buradan değiştirilmez.
	"""
	t = targets if targets is not None else default_table().targets
	return float(((t or {}).get("quality_gate") or {}).get("vmaf_min", 93))


def _fallback_kurali(targets: Optional[Mapping[str, Any]] = None) -> Mapping[str, Any]:
	t = targets if targets is not None else default_table().targets
	return ((t or {}).get("benefit_gate") or {}).get("fallback") or {}


def remux_fallback_applies(
	facts: Optional[VideoFacts],
	targets: Optional[Mapping[str, Any]] = None,
) -> Tuple[bool, str]:
	"""Kapıdan düşen TRANSCODE'dan sonra REMUX'a geri çekilmeli mi — ve NEDEN.

	İki koşul birlikte aranır:

	1. **Kap/moov kusuru DURUYOR mu.** Kaynak mp4 değilse ya da moov atomu
	   sondaysa, TRANSCODE atıldığında bu kusur DÜZELMEDEN kalır. Ölçülen kusur
	   bu (B-2): kapıdan düşen çıktı, aynı dosyanın REMUX ihtiyacını öldürüyordu.
	2. **Akışlar zaten teslim edilebilir mi.** VP9/Opus bir kaynağı `-c copy`
	   ile mp4'e taşımak kabı düzeltir ama tarayıcıda oynamayan bir dosya
	   üretir. Böyle bir kaynakta geri çekilme YAPILMAZ; kaynak dokunulmadan
	   korunur.
	"""
	kural = _fallback_kurali(targets)
	if not facts or not facts.measured:
		return (False, "kunye olculemedi")
	if not kural.get("enabled", True):
		return (False, "tabloda kapali (benefit_gate.fallback.enabled=false)")

	kusurlar: List[str] = []
	if facts.container_family != "mp4":
		kusurlar.append(f"kap mp4 degil ({facts.container_family})")
	if facts.moov_at_end:
		kusurlar.append("moov atomu SONDA")
	if not kusurlar:
		return (False, "kaynakta kap/moov kusuru yok — REMUX bir sey duzeltmez")

	video_ok = list(kural.get("deliverable_video_codecs") or ["h264"])
	audio_ok = list(kural.get("deliverable_audio_codecs") or ["aac", "mp3", ""])
	if facts.video_codec not in video_ok:
		return (False, f"video kodegi teslim edilebilir degil ({facts.video_codec}) — -c copy oynatmayi bozar")
	if facts.has_audio and facts.audio_codec not in audio_ok:
		return (False, f"ses kodegi teslim edilebilir degil ({facts.audio_codec}) — -c copy oynatmayi bozar")
	return (True, " + ".join(kusurlar))


def duration_delta_s(reference: str, distorted: str) -> Optional[float]:
	"""Kaynak ile çıktının süre farkı (saniye). Ölçülemezse `None`.

	`None` "fark yok" DEĞİLDİR — "ölçemedim" demektir; çağıran ikisini
	karıştırmamalıdır.
	"""
	a = probe_modulu.probe(reference)
	b = probe_modulu.probe(distorted)
	if not (a.measured and b.measured) or not a.duration_s or not b.duration_s:
		return None
	return abs(a.duration_s - b.duration_s)


def av_sync_from_facts(reference: VideoFacts, distorted: VideoFacts) -> Dict[str, Any]:
	"""Kaynak/çıktı A/V başlangıç ve bitiş ofsetlerindeki değişimi ölç.

	Mutlak ses başlangıcına bakmak tek başına yeterli değildir; kaynakta ses
	zaten videodan 20 ms sonra başlıyor olabilir. Teslim kapısının koruması
	gereken, bu ofsetin transcode sırasında ne kadar *değiştiğidir*.
	"""
	if not (reference.measured and distorted.measured):
		return {"measured": False, "reason": "kaynak veya cikti kunyesi olculemedi"}
	if not reference.has_audio:
		return {"measured": False, "not_applicable": True, "reason": "kaynak sessiz"}
	if not distorted.has_audio:
		return {"measured": True, "audio_missing": True, "start_delta_s": None, "end_delta_s": None,
			"max_delta_s": float("inf")}

	ref_start = reference.audio_start_time_s - reference.video_start_time_s
	out_start = distorted.audio_start_time_s - distorted.video_start_time_s
	ref_end = (
		reference.audio_start_time_s + reference.audio_duration_s
		- reference.video_start_time_s - reference.video_duration_s
	)
	out_end = (
		distorted.audio_start_time_s + distorted.audio_duration_s
		- distorted.video_start_time_s - distorted.video_duration_s
	)
	start_delta = abs(out_start - ref_start)
	end_delta = abs(out_end - ref_end)
	return {
		"measured": True,
		"reference_start_offset_s": round(ref_start, 6),
		"output_start_offset_s": round(out_start, 6),
		"reference_end_offset_s": round(ref_end, 6),
		"output_end_offset_s": round(out_end, 6),
		"start_delta_s": round(start_delta, 6),
		"end_delta_s": round(end_delta, 6),
		"max_delta_s": round(max(start_delta, end_delta), 6),
	}


def av_sync_delta_s(reference: str, distorted: str) -> Optional[float]:
	"""İki dosyanın en kötü A/V ofset değişimi; ölçülemezse ``None``."""
	olcum = av_sync_from_facts(probe_modulu.probe(reference), probe_modulu.probe(distorted))
	if olcum.get("not_applicable"):
		return 0.0
	if not olcum.get("measured"):
		return None
	try:
		return float(olcum["max_delta_s"])
	except (KeyError, TypeError, ValueError):
		return None


_YAVG_RE = re.compile(r"YAVG[=:]([0-9.]+)")


def first_frame_luma_pct(path: str, *, timeout: int = 60) -> Optional[float]:
	"""İlk teslim karesinin lumasını ölç; siyah/beyaz açılışı yakalar."""
	cmd = [
		"ffmpeg", "-hide_banner", "-i", path,
		"-vf", "signalstats,metadata=mode=print",
		"-frames:v", "1", "-f", "null", "-",
	]
	try:
		sonuc = run_ffmpeg(cmd, timeout=min(int(timeout), 60))
	except (ProbeUnavailable, TranscodeFailed):
		return None
	metin = ((sonuc.stderr or b"") + b"\n" + (sonuc.stdout or b"")).decode("utf-8", "replace")
	m = _YAVG_RE.search(metin)
	if not m:
		return None
	try:
		return float(m.group(1)) / 255.0 * 100.0
	except ValueError:
		return None


def validate_delivery_metrics(
	*,
	duration_delta: Optional[float],
	av_sync_delta: Optional[float],
	first_frame_luma: Optional[float],
	has_audio: bool,
	max_duration_delta: Optional[float] = None,
	max_av_sync_delta: Optional[float] = None,
	min_first_frame_luma: Optional[float] = None,
	max_first_frame_luma: Optional[float] = None,
	require_measured: bool = True,
) -> Tuple[bool, Dict[str, Any]]:
	"""Süre, A/V senkronu ve ilk kareyi tek atomik teslim kapısında değerlendir."""
	duration_limit = max_duration_delta_s() if max_duration_delta is None else float(max_duration_delta)
	av_limit = max_av_sync_delta_s() if max_av_sync_delta is None else float(max_av_sync_delta)
	luma_min, luma_max = first_frame_luma_range()
	if min_first_frame_luma is not None:
		luma_min = float(min_first_frame_luma)
	if max_first_frame_luma is not None:
		luma_max = float(max_first_frame_luma)
	report: Dict[str, Any] = {
		"duration_delta_s": duration_delta,
		"max_duration_delta_s": duration_limit,
		"av_sync_delta_s": av_sync_delta,
		"max_av_sync_delta_s": av_limit,
		"first_frame_luma_pct": first_frame_luma,
		"first_frame_luma_range_pct": [luma_min, luma_max],
	}

	def kapi(value: Optional[float], predicate: Callable[[float], bool]) -> str:
		if value is None:
			return "OLCULEMEDI"
		return "GECTI" if predicate(float(value)) else "DUSTU"

	report["duration_gate"] = kapi(duration_delta, lambda x: x <= duration_limit)
	report["av_sync_gate"] = (
		"UYGULANMAZ" if not has_audio else kapi(av_sync_delta, lambda x: x <= av_limit)
	)
	report["first_frame_gate"] = kapi(
		first_frame_luma, lambda x: luma_min <= x <= luma_max
	)
	basarisiz = any(v == "DUSTU" for v in (
		report["duration_gate"], report["av_sync_gate"], report["first_frame_gate"]
	))
	olculemeyen = any(v == "OLCULEMEDI" for v in (
		report["duration_gate"], report["av_sync_gate"], report["first_frame_gate"]
	))
	return (not basarisiz and not (require_measured and olculemeyen), report)


def transcode(
	src: str,
	dst: str,
	*,
	spec: Optional[H264Spec] = None,
	facts: Optional[VideoFacts] = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	enforce_benefit_gate: bool = True,
	enforce_quality_gate: Optional[bool] = None,
	enforce_delivery_gate: Optional[bool] = None,
	nice: bool = True,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> TranscodeResult:
	"""Kaynağı H.264 High + AAC 128k + faststart mp4'e dönüştür.

	Fayda kapısını (INV-05) geçemeyen çıktı SİLİNİR ve hedefe hiçbir şey
	yazılmaz: `accepted=False`, `kept_source=True`.

	**Kalite kapısı (`vmaf_min`, W7).** Fayda kapısını geçen çıktı, tablodaki
	`quality_gate.vmaf_min` eşiğiyle DOĞRULANIR: VMAF ölçülebiliyorsa ve
	eşiğin altındaysa çıktı ATILIR (`accepted=False`, `kept_source=True`).
	VMAF ölçülemiyorsa (libvmaf'sız ffmpeg) kapı UYGULANMAZ ve bu açıkça
	nota yazılır — uydurma bir sayıyla ret de kabul de üretilmez.

	`enforce_quality_gate=None` (varsayılan) `enforce_benefit_gate`i izler.
	Ayrık bir bayrak olması bilinçli: sonda/ölçüm koşumları (kapısız çıktının
	kendisini incelemek isteyen çağıranlar) `enforce_benefit_gate=False` ile
	geliyor ve o yolda dosyanın DİSKTE KALMASI sözleşmedir — ölçüldü: sessiz
	720p fixture'ının kapısız çıktısı VMAF 90,99 < 93, kapı orada da çalışsaydı
	inceleme çıktısını yok ederdi. Üretim yolu iki kapıyı birden açık tutar.
	"""
	spec = spec or H264Spec.from_table()
	facts = facts or probe_modulu.probe(src)
	if not facts.measured:
		raise ProbeUnavailable(f"kunye okunamadi: {facts.error}", detay={"error": facts.error})

	gecici = _temp_path(dst)
	cmd = build_transcode_cmd(src, gecici, spec, facts, nice=nice)
	basla = time.monotonic()
	try:
		kosum = _run(
			cmd,
			timeout=timeout,
			progress_callback=progress_callback,
			cancel_check=cancel_check,
		)
	except Exception:
		_sessiz_sil(gecici)
		raise
	sure = time.monotonic() - basla

	sonuc = TranscodeResult(
		action=ACTION_TRANSCODE,
		src_path=src,
		src_bytes=facts.size_bytes or _boyut(src),
		out_bytes=_boyut(gecici),
		wall_s=sure,
		cmd=tuple(cmd),
		peak_rss_bytes=kosum.peak_rss_bytes,
		cpu_user_s=kosum.cpu_user_s,
		cpu_system_s=kosum.cpu_system_s,
		limits_applied=tuple(kosum.limits_applied),
	)

	esik = min_saving_ratio()
	if enforce_benefit_gate and sonuc.saving_ratio < esik:
		_sessiz_sil(gecici)
		sonuc.accepted = False
		sonuc.kept_source = True
		sonuc.notes.append(
			f"INV-05 fayda kapisi: kazanc %{sonuc.saving_ratio * 100:.1f} < %{esik * 100:.0f} "
			f"-> cikti atildi, kaynak korundu"
		)
		return sonuc

	# ── Kalite kapısı (vmaf_min, T-072/5 — W7'de bağlandı) ─────────────
	# Fayda kapısından SONRA: zaten atılacak çıktı için VMAF ölçmek (saniyeler
	# süren ikinci bir kod çözme) boşa iştir. Ölçüm geçici dosya üzerinde —
	# süre kapısıyla aynı gerekçe.
	kalite_kapisi = enforce_benefit_gate if enforce_quality_gate is None else enforce_quality_gate
	if kalite_kapisi:
		kalite = measure_quality(src, gecici, timeout=timeout)
		vmaf_esigi = vmaf_min()
		sonuc.quality["vmaf_min"] = vmaf_esigi
		if kalite.get("measured") and kalite.get("metric") == "vmaf":
			puan = float(kalite.get("vmaf") or 0.0)
			sonuc.quality["vmaf"] = puan
			if puan < vmaf_esigi:
				_sessiz_sil(gecici)
				sonuc.quality["vmaf_gate"] = "DUSTU"
				sonuc.accepted = False
				sonuc.kept_source = True
				sonuc.notes.append(
					f"kalite kapisi (vmaf_min): VMAF {puan:.2f} < {vmaf_esigi:.0f} "
					f"-> cikti atildi, kaynak korundu"
				)
				return sonuc
			sonuc.quality["vmaf_gate"] = "GECTI"
		else:
			# VMAF yoksa SSIM/PSNR kayda geçer ama kapı UYGULANMAZ: eşik VMAF
			# cinsinden tanımlı, başka metrikten VMAF'a çeviri uydurmaktır.
			sonuc.quality["vmaf"] = None
			sonuc.quality["vmaf_gate"] = "OLCULEMEDI"
			for anahtar in ("ssim", "psnr", "vmaf_note"):
				if anahtar in kalite:
					sonuc.quality[anahtar] = kalite[anahtar]
			sonuc.notes.append("VMAF OLCULEMEDI -> kalite kapisi uygulanmadi (sayi uydurulmaz)")

	# ── Teslim bütünlüğü: süre + A/V sync + ilk kare ────────────────────
	# Üç ölçüm aynı geçici çıktı üstünde ve promote ÖNCESİNDE yapılır. Biri
	# düşerse yarım/bozuk teslim yayınlanmaz; kaynak atomik olarak korunur.
	cikti_facts = probe_modulu.probe(gecici)
	fark = (
		abs(facts.duration_s - cikti_facts.duration_s)
		if facts.measured and cikti_facts.measured and facts.duration_s and cikti_facts.duration_s
		else None
	)
	sync = av_sync_from_facts(facts, cikti_facts)
	sync_delta = (
		0.0 if sync.get("not_applicable") else (
			float(sync["max_delta_s"]) if sync.get("measured") and sync.get("max_delta_s") is not None else None
		)
	)
	luma = first_frame_luma_pct(gecici, timeout=timeout)
	teslim_ok, teslim = validate_delivery_metrics(
		duration_delta=fark,
		av_sync_delta=sync_delta,
		first_frame_luma=luma,
		has_audio=facts.has_audio,
	)
	teslim["av_sync"] = sync
	sonuc.quality.update(teslim)
	teslim_kapisi = enforce_benefit_gate if enforce_delivery_gate is None else enforce_delivery_gate
	if teslim_kapisi and not teslim_ok:
		_sessiz_sil(gecici)
		sonuc.accepted = False
		sonuc.kept_source = True
		dusenler = [k for k in ("duration_gate", "av_sync_gate", "first_frame_gate") if teslim.get(k) != "GECTI" and teslim.get(k) != "UYGULANMAZ"]
		sonuc.notes.append(f"teslim butunlugu kapisi dustu: {', '.join(dusenler)} -> cikti atildi, kaynak korundu")
		return sonuc

	os.replace(gecici, dst)
	sonuc.out_path = dst
	sonuc.accepted = True
	return sonuc


def remux(
	src: str,
	dst: str,
	*,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	nice: bool = True,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> TranscodeResult:
	"""Akışları kopyalayarak mp4'e taşı ve moov'u başa al.

	Fayda kapısı UYGULANMAZ: amaç bayt kazanmak değil ilk kareyi
	hızlandırmak; `+faststart` dosyayı birkaç KB büyütebilir ve bu doğru
	sonuçtur (karar tablosu `benefit_gate.exempt_actions`).
	"""
	gecici = _temp_path(dst)
	cmd = build_remux_cmd(src, gecici, nice=nice)
	basla = time.monotonic()
	try:
		kosum = _run(
			cmd,
			timeout=timeout,
			progress_callback=progress_callback,
			cancel_check=cancel_check,
		)
	except Exception:
		_sessiz_sil(gecici)
		raise
	sure = time.monotonic() - basla

	sonuc = TranscodeResult(
		action=ACTION_REMUX,
		src_path=src,
		src_bytes=_boyut(src),
		out_bytes=_boyut(gecici),
		wall_s=sure,
		cmd=tuple(cmd),
		notes=["fayda kapisindan MUAF (benefit_gate.exempt_actions)"],
		peak_rss_bytes=kosum.peak_rss_bytes,
		cpu_user_s=kosum.cpu_user_s,
		cpu_system_s=kosum.cpu_system_s,
		limits_applied=tuple(kosum.limits_applied),
	)
	os.replace(gecici, dst)
	sonuc.out_path = dst
	sonuc.accepted = True
	return sonuc


def apply_decision(
	src: str,
	dst: str,
	decision: VideoDecision,
	*,
	facts: Optional[VideoFacts] = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	nice: bool = True,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> TranscodeResult:
	"""Karar tablosunun verdiği aksiyonu uygula.

	PASSTHROUGH ve REJECT ffmpeg ÇALIŞTIRMAZ; ikisi de sonuç nesnesi döner
	(REJECT hata atmaz, çünkü ret bir hatadan çok bir karardır ve çağıran onu
	kullanıcıya kodlu mesajla göstermelidir).
	"""
	if decision.action == ACTION_PASSTHROUGH:
		return TranscodeResult(
			action=ACTION_PASSTHROUGH,
			src_path=src,
			src_bytes=_boyut(src),
			out_bytes=_boyut(src),
			accepted=True,
			kept_source=True,
			notes=[decision.reason or "dokunulmadi"],
		)
	if decision.action == ACTION_REJECT:
		return TranscodeResult(
			action=ACTION_REJECT,
			src_path=src,
			src_bytes=_boyut(src),
			accepted=False,
			kept_source=True,
			notes=[f"{decision.code}: {decision.reason}"],
		)
	if decision.action == ACTION_REMUX:
		return remux(
			src, dst, timeout=timeout, nice=nice,
			progress_callback=progress_callback, cancel_check=cancel_check,
		)

	facts = facts or probe_modulu.probe(src)
	sonuc = transcode(
		src, dst, facts=facts, timeout=timeout, nice=nice,
		progress_callback=progress_callback, cancel_check=cancel_check,
	)
	if sonuc.accepted:
		return sonuc

	# ── B-2 geri çekilme yolu ───────────────────────────────────────────
	# Kapıdan düşen TRANSCODE, aynı dosyanın REMUX ihtiyacını ÖLDÜRÜYORDU:
	# moov sonda kalıyordu ve geri çekilme yolu yoktu. Gerekçe ve koşullar
	# `remux_fallback_applies` + tablonun `benefit_gate.fallback` bloğunda.
	uygulanir, gerekce = remux_fallback_applies(facts)
	if not uygulanir:
		sonuc.notes.append(f"REMUX'a geri cekilme YAPILMADI: {gerekce}")
		return sonuc

	dusen_kapi = (
		"kalite kapisindan (vmaf_min)"
		if sonuc.quality.get("vmaf_gate") == "DUSTU"
		else "fayda kapisindan (INV-05)"
	)
	geri = remux(
		src, dst, timeout=timeout, nice=nice,
		progress_callback=progress_callback, cancel_check=cancel_check,
	)
	geri.fallback_from = ACTION_TRANSCODE
	geri.notes = list(sonuc.notes) + [
		f"TRANSCODE {dusen_kapi} dustu -> REMUX'a geri cekildi ({gerekce})"
	] + list(geri.notes)
	geri.quality = dict(sonuc.quality)
	return geri


# ── Kalite ölçümü ───────────────────────────────────────────────────────


def vmaf_available() -> bool:
	"""ffmpeg `libvmaf` filtresiyle mi derlenmiş?

	Debian'ın paketlediği ffmpeg'de genelde DEĞİL. Ölçülmüş durum bu modülün
	altındaki tabloda; ölçüm yapılamıyorsa `measure_quality` "VMAF YOK" der ve
	uydurma bir sayı üretmez.
	"""
	sonuc = isolation.run_command(
		["ffmpeg", "-hide_banner", "-filters"],
		limits=isolation.VIDEO_LIMITS.with_(wall_timeout_s=30.0, cpu_seconds=25, nice=None),
	)
	if not sonuc.ok:
		return False
	cikti = ((sonuc.stdout or b"") + b"\n" + (sonuc.stderr or b"")).decode("utf-8", "replace")
	return " libvmaf " in cikti


_SSIM_RE = re.compile(r"All:\s*([0-9.]+)")
_PSNR_RE = re.compile(r"average:\s*([0-9.inf]+)")


def measure_quality(
	reference: str,
	distorted: str,
	*,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
) -> Dict[str, Any]:
	"""Kaynak ile çıktı arasındaki kalite farkını ÖLÇ.

	VMAF varsa VMAF; yoksa ffmpeg'in yerleşik `ssim` ve `psnr` filtreleri.
	İkisi de yoksa `{"measured": False}`.

	Çözünürlük farkı: çıktı 1280'e indirilmiş olabilir, referans 1920 olabilir.
	Karşılaştırma REFERANS çözünürlüğünde yapılır — çıktı bikübik büyütülüp
	kaynakla hizalanır. Bu, ölçülen SSIM'in hem yeniden kodlama hem de
	küçültme kaybını birlikte içerdiği anlamına gelir; küçültme kararı
	bilinçli olduğu için bu doğru ölçüdür ("kullanıcı 1080p ekranda ne
	görüyor").
	"""
	ref = probe_modulu.probe(reference)
	if not ref.measured:
		return {"measured": False, "reason": f"referans kunyesi okunamadi: {ref.error}"}

	if vmaf_available():
		# libvmaf son puanı zaten ffmpeg stderr'ine yazar. ``log_path=-`` bazı
		# sürümlerde stdout anlamına gelmeyip çalışma dizininde gerçekten ``-``
		# adlı 200 KiB civarı JSON dosyası oluşturur; kalite ölçümü kalıcı/geçici
		# yan ürün bırakmamalıdır.
		filtre = (
			f"[1:v]scale={ref.width}:{ref.height}:flags=bicubic[dist];"
			f"[dist][0:v]libvmaf"
		)
		cmd = ["ffmpeg", "-hide_banner", "-i", reference, "-i", distorted,
			"-filter_complex", filtre, "-f", "null", "-"]
		sonuc = isolation.run_command(
			cmd,
			limits=isolation.VIDEO_LIMITS.with_(wall_timeout_s=float(timeout), nice=None),
		)
		if sonuc.ok:
			metin = ((sonuc.stderr or b"") + b"\n" + (sonuc.stdout or b"")).decode("utf-8", "replace")
			m = re.search(r"VMAF score:\s*([0-9.]+)", metin)
			if m:
				return {
					"measured": True,
					"metric": "vmaf",
					"vmaf": float(m.group(1)),
					"peak_rss_bytes": sonuc.peak_rss_bytes,
					"cpu_s": round(sonuc.cpu_user_s + sonuc.cpu_system_s, 3),
				}

	# ssim ve psnr filtreleri aynı girdiyi iki kez tüketemez; bu yüzden iki
	# ayrı koşum yapılır. İkisi de saniyeler sürer (kod çözme sınırlı).
	sonuc: Dict[str, Any] = {"measured": False, "metric": "ssim", "vmaf": None,
		"vmaf_note": "VMAF YOK — ffmpeg libvmaf olmadan derlenmis"}
	for ad, ifade, desen in (
		("ssim", "ssim", _SSIM_RE),
		("psnr", "psnr", _PSNR_RE),
	):
		cmd = [
			"ffmpeg", "-hide_banner", "-i", reference, "-i", distorted,
			"-filter_complex",
			f"[1:v]scale={ref.width}:{ref.height}:flags=bicubic[dist];[dist][0:v]{ifade}",
			"-f", "null", "-",
		]
		kosum = isolation.run_command(
			cmd,
			limits=isolation.VIDEO_LIMITS.with_(wall_timeout_s=float(timeout), nice=None),
		)
		if not kosum.ok:
			sonuc[f"{ad}_error"] = kosum.sebep
			continue
		metin = ((kosum.stderr or b"") + b"\n" + (kosum.stdout or b"")).decode("utf-8", "replace")
		m = desen.search(metin)
		if m:
			sonuc[ad] = float(m.group(1)) if m.group(1) not in ("inf",) else float("inf")
			sonuc["measured"] = True
	return sonuc


# ── Küçük yardımcılar ───────────────────────────────────────────────────


def _boyut(path: str) -> int:
	try:
		return os.path.getsize(path)
	except OSError:
		return 0


def _sessiz_sil(path: str) -> None:
	"""Geçici dosyayı temizle. Silinemezse SUS: asıl hata bu değil.

	Bugünkü hattaki desenle aynı (transcode.py:381-385): temizlik hatası,
	transcode hatasının üstünü örtmemeli.
	"""
	try:
		if os.path.exists(path):
			os.remove(path)
	except OSError:
		pass


def ffmpeg_available() -> bool:
	return shutil.which("ffmpeg") is not None


__all__ = [
	"H264Spec",
	"TranscodeResult",
	"NICE_PREFIX",
	"build_transcode_cmd",
	"build_remux_cmd",
	"rate_ceiling_kbps",
	"remux_fallback_applies",
	"duration_delta_s",
	"av_sync_from_facts",
	"av_sync_delta_s",
	"first_frame_luma_pct",
	"validate_delivery_metrics",
	"max_duration_delta_s",
	"max_av_sync_delta_s",
	"first_frame_luma_range",
	"vmaf_min",
	"transcode",
	"remux",
	"apply_decision",
	"measure_quality",
	"vmaf_available",
	"ffmpeg_available",
	"min_saving_ratio",
	"run_ffmpeg",
]
