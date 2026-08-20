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
import subprocess
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.errors import (
	SEBEP_TRANSCODE_FAILED,
	ProbeUnavailable,
	TranscodeFailed,
)
from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS
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

	filtreler = [_scale_filter(spec.max_width)]
	if kaynak_fps > spec.frame_rate_cap:
		filtreler.append(f"fps={spec.frame_rate_cap}")

	gop = max(int(round(hedef_fps * spec.keyframe_interval_s)), 1)

	cmd: List[str] = list(NICE_PREFIX) if nice else []
	cmd += ["ffmpeg", "-y", "-i", src]
	# İlk video + (varsa) ilk ses. `0:a:0?` sondaki soru işareti "yoksa sorun
	# değil" demek; fazladan akışlar (ikinci dil, altyazı, veri) düşürülür.
	cmd += ["-map", "0:v:0"]
	if facts is None or facts.has_audio:
		cmd += ["-map", "0:a:0?"]
	cmd += ["-vf", ",".join(filtreler)]
	cmd += [
		"-c:v", spec.video_codec,
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
		dst,
	]
	return cmd


# ── Koşum ───────────────────────────────────────────────────────────────


def _run(cmd: Sequence[str], *, timeout: int) -> subprocess.CompletedProcess:
	"""ffmpeg'i çalıştır; `subprocess` istisnalarını sözleşme hatalarına çevir.

	Sözleşme (contracts/video.py) `subprocess` hatalarının SIZMASINI ihlal
	sayıyor: ffmpeg'in imajdan kalkması worker'ı çökertmemeli, kodlu bir hata
	olarak görünmelidir.
	"""
	try:
		return subprocess.run(list(cmd), check=True, capture_output=True, timeout=timeout)
	except FileNotFoundError as exc:
		raise ProbeUnavailable("ffmpeg bulunamadi", detay={"cmd": cmd[0] if cmd else ""}) from exc
	except subprocess.TimeoutExpired as exc:
		raise TranscodeFailed(
			f"ffmpeg zaman asimi ({timeout} sn)",
			kod=f"media_{SEBEP_TRANSCODE_FAILED}",
			detay={"timeout_s": timeout},
		) from exc
	except subprocess.CalledProcessError as exc:
		ayrinti = (exc.stderr or b"").decode("utf-8", "replace").strip()
		raise TranscodeFailed(
			"ffmpeg basarisiz oldu",
			kod=f"media_{SEBEP_TRANSCODE_FAILED}",
			detay={"returncode": exc.returncode, "stderr_tail": ayrinti[-800:]},
		) from exc


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


def transcode(
	src: str,
	dst: str,
	*,
	spec: Optional[H264Spec] = None,
	facts: Optional[VideoFacts] = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	enforce_benefit_gate: bool = True,
	enforce_quality_gate: Optional[bool] = None,
	nice: bool = True,
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
		_run(cmd, timeout=timeout)
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

	# Süre kapısı ÖLÇÜLÜR ama çıktıyı ATMAZ (tablo `quality_gate.duration_note`):
	# süresi sapmış bir dosya, hiç dosya olmamasından iyidir. Ölçüm geçici dosya
	# üzerinde yapılır — taşımadan sonra ölçmek aynı sonucu verir ama başarısız
	# ölçümde hedefi çoktan değiştirmiş oluruz.
	fark = duration_delta_s(src, gecici)
	tavan = max_duration_delta_s()
	sonuc.quality["duration_delta_s"] = None if fark is None else round(fark, 4)
	sonuc.quality["max_duration_delta_s"] = tavan
	if fark is None:
		sonuc.quality["duration_gate"] = "OLCULEMEDI"
		sonuc.notes.append("sure farki OLCULEMEDI — kapi uygulanmadi")
	elif fark > tavan:
		sonuc.quality["duration_gate"] = "DUSTU"
		sonuc.notes.append(f"sure farki {fark * 1000:.0f} ms > {tavan * 1000:.0f} ms tavani")
	else:
		sonuc.quality["duration_gate"] = "GECTI"

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
		_run(cmd, timeout=timeout)
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
		return remux(src, dst, timeout=timeout, nice=nice)

	facts = facts or probe_modulu.probe(src)
	sonuc = transcode(src, dst, facts=facts, timeout=timeout, nice=nice)
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
	geri = remux(src, dst, timeout=timeout, nice=nice)
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
	try:
		cikti = subprocess.run(
			["ffmpeg", "-hide_banner", "-filters"], capture_output=True, timeout=30
		).stdout.decode("utf-8", "replace")
	except (OSError, subprocess.SubprocessError):
		return False
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
		filtre = (
			f"[1:v]scale={ref.width}:{ref.height}:flags=bicubic[dist];"
			f"[dist][0:v]libvmaf=log_fmt=json:log_path=-"
		)
		cmd = ["ffmpeg", "-hide_banner", "-i", reference, "-i", distorted,
			"-filter_complex", filtre, "-f", "null", "-"]
		try:
			p = subprocess.run(cmd, capture_output=True, timeout=timeout)
			metin = (p.stderr or b"").decode("utf-8", "replace")
			m = re.search(r"VMAF score:\s*([0-9.]+)", metin)
			if m:
				return {"measured": True, "metric": "vmaf", "vmaf": float(m.group(1))}
		except (OSError, subprocess.SubprocessError):
			pass

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
		try:
			p = subprocess.run(cmd, capture_output=True, timeout=timeout)
			metin = (p.stderr or b"").decode("utf-8", "replace")
			m = desen.search(metin)
			if m:
				sonuc[ad] = float(m.group(1)) if m.group(1) not in ("inf",) else float("inf")
				sonuc["measured"] = True
		except (OSError, subprocess.SubprocessError) as exc:
			sonuc[f"{ad}_error"] = str(exc)
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
	"max_duration_delta_s",
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
