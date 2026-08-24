"""T-074 — HLS merdiveni (360p → 1080p), tek ffmpeg koşumunda.

**Bugünkü durum: HLS YOK.** Ne üretimde ne de vitrinde. Kanıt politika
dosyasında kayıtlı (`company-cover-video.json` `hls.current_state_evidence`):
`tradehubfront/src` ve `admin-panel/frontend/src` içinde `hls` araması 0
eşleşme veriyor. Bugün video tek bir dosya olarak `<video src>` ile
servis ediliyor; 3G'deki alıcı da fiber'deki alıcı da AYNI baytı indiriyor.

**Bu modülün yaptığı.** Karar tablosundaki (`video_decision.json` `hls`
bloğu) merdiveni okur, kaynağa göre budar ve TEK bir ffmpeg koşumuyla
çok-basamaklı bir VOD paketi üretir: her basamak için bir medya playlist'i,
hepsinin üstünde bir master playlist.

**Neden tek koşum.** Basamak başına ayrı ffmpeg çalıştırmak kaynağı N kez
ÇÖZER. Kod çözme, kodlamanın yanında ucuz değildir; 4 basamaklı bir merdivende
bu, işin görünmeyen dörtte birini boşa harcamak demektir. `split` filtresi
kaynağı bir kez çözüp N kola dağıtır.

**BÜYÜTME YOK (`no_upscale`).** Kaynak yüksekliğinin üstündeki basamaklar
ÜRETİLMEZ. 720p kaynaktan 1080p basamağı üretmek bikübik bir büyütmedir:
bayt harcar, görsel hiçbir şey kazandırmaz, üstelik master playlist'te
"1080p var" diye ilan edilir ve oynatıcıyı yanıltır.

**Basamak eşiği YÜKSEKLİK DEĞİL KISA KENARDIR.** Dikey video (9:16) düşey
yüksekliği 1280 olduğu için yüksekliğe bakan bir merdivende "1080p kaynak"
sayılır ve 360p basamağı 202 piksel genişliğe inerdi. Kısa kenar ölçüsü
her iki yönelimde de doğru sonucu verir; ölçek filtresi de yönelime göre
kurulur (künye zaten ölçüldüğü için ffmpeg ifadesine gerek yok).

**GOP hizası.** Segment sınırı ancak anahtar karede olabilir. Anahtar kare
aralığı (2 sn) segment süresini (4 sn) TAM BÖLMEZSE ffmpeg segmentleri
istenen sürede kesemez ve süreler dalgalanır; `check_gop_alignment` bunu
yükleme anında yakalar. `-sc_threshold 0` da bu yüzden: sahne kesiminde
kendiliğinden açılan anahtar kareler hizayı bozar.

`frappe` import edilmez; kuyruk ve durum makinesi bu modülün işi değildir.
"""

from __future__ import annotations

import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from tradehub_core.media.pipeline.contracts.errors import SEBEP_TRANSCODE_FAILED, ProbeUnavailable, TranscodeFailed
from tradehub_core.media.pipeline.contracts.video import FFMPEG_TIMEOUT_SECONDS
from tradehub_core.media.pipeline.video import probe as probe_modulu
from tradehub_core.media.pipeline.video.decision import default_table
from tradehub_core.media.pipeline.video.probe import VideoFacts
from tradehub_core.media.pipeline.video.transcode import NICE_PREFIX, H264Spec, run_ffmpeg

#: Master playlist'in dosya adı. Teslimde `<video>`/hls.js'in gördüğü tek adres.
MASTER_PLAYLIST_NAME: str = "master.m3u8"

#: Basamak dizinlerinin adlandırma kalıbı. ffmpeg `%v` yer tutucusunu
#: `var_stream_map` girdisindeki `name:` ile doldurur — **indisle DEĞİL**.
#: Bu, gerçek ffmpeg 5.1 koşumunda ölçüldü: `name:360p` verilince dizin `v0`
#: değil `v360p` oluyor. Yol hesabı için `variant_dir()` kullanılmalı; `%v`'yi
#: elle indisle doldurmak boş dizinlere bakmaya (segment sayısı 0, bayt 0)
#: yol açar — bu modülün ilk koşumundaki gerçek hata buydu.
VARIANT_DIR_PATTERN: str = "v%v"
MEDIA_PLAYLIST_NAME: str = "playlist.m3u8"


def variant_dir(out_dir: str, rung: "HlsRung") -> str:
	"""Basamağın ffmpeg'in GERÇEKTEN yazdığı dizini."""
	return os.path.join(out_dir, VARIANT_DIR_PATTERN.replace("%v", rung.name))


def variant_playlist(out_dir: str, rung: "HlsRung") -> str:
	"""Basamağın medya playlist yolu."""
	return os.path.join(variant_dir(out_dir, rung), MEDIA_PLAYLIST_NAME)


@dataclass(frozen=True)
class HlsRung:
	"""Merdivenin tek basamağı. Değerler `video_decision.json` `hls.ladder`'dan."""

	name: str
	width: int
	height: int
	bitrate_kbps: int
	maxrate_kbps: int
	bufsize_kbps: int
	audio_kbps: int

	@property
	def tier(self) -> int:
		"""Basamağın KISA KENARI — merdiven sıralaması ve budama ölçüsü.

		16:9 tanımlı bir merdivende bu yüksekliğe eşittir; ölçüyü kısa kenar
		üzerinden yazmak dikey kaynakta da doğru davranışı verir.
		"""
		return min(self.width, self.height)

	@classmethod
	def from_dict(cls, d: Mapping[str, Any]) -> "HlsRung":
		return cls(
			name=str(d.get("name") or ""),
			width=int(d.get("width") or 0),
			height=int(d.get("height") or 0),
			bitrate_kbps=int(d.get("bitrate_kbps") or 0),
			maxrate_kbps=int(d.get("maxrate_kbps") or 0),
			bufsize_kbps=int(d.get("bufsize_kbps") or 0),
			audio_kbps=int(d.get("audio_kbps") or 0),
		)


@dataclass(frozen=True)
class HlsSpec:
	"""HLS paketleme kuralı — tablonun `hls` bloğunun kod karşılığı."""

	ladder: Tuple[HlsRung, ...] = ()
	segment_duration_s: float = 4.0
	playlist_type: str = "vod"
	segment_type: str = "mpegts"
	no_upscale: bool = True
	rate_control: str = "capped_crf"
	crf: int = 23
	#: Mobil veri tavanı: oynatıcının ilk `startup_window_s` saniyeyi
	#: göstermek için indirdiği bayt bu sınırı aşmamalı.
	startup_window_s: float = 10.0
	startup_max_bytes: int = 1_280_000
	duration_s_gt: float = 60.0
	max_rendition_bytes_gt: int = 12_582_912
	distinct_resolution_tiers_gt: int = 2

	@classmethod
	def from_table(cls, blok: Optional[Mapping[str, Any]] = None) -> "HlsSpec":
		h = dict(blok if blok is not None else default_table().hls)
		kosul = dict(h.get("required_if_any") or {})
		butce = dict(h.get("startup_budget") or {})
		v = cls()
		merdiven = tuple(HlsRung.from_dict(r) for r in (h.get("ladder") or ()))
		return cls(
			ladder=merdiven,
			segment_duration_s=float(h.get("segment_duration_s", v.segment_duration_s)),
			playlist_type=str(h.get("playlist_type", v.playlist_type)),
			segment_type=str(h.get("segment_type", v.segment_type)),
			no_upscale=bool(h.get("no_upscale", v.no_upscale)),
			rate_control=str(h.get("rate_control", v.rate_control)),
			crf=int(h.get("crf", v.crf)),
			startup_window_s=float(butce.get("window_s", v.startup_window_s)),
			startup_max_bytes=int(butce.get("max_bytes", v.startup_max_bytes)),
			duration_s_gt=float(kosul.get("duration_s_gt", v.duration_s_gt)),
			max_rendition_bytes_gt=int(kosul.get("max_rendition_bytes_gt", v.max_rendition_bytes_gt)),
			distinct_resolution_tiers_gt=int(
				kosul.get("distinct_resolution_tiers_gt", v.distinct_resolution_tiers_gt)
			),
		)


@dataclass
class HlsRequirement:
	"""HLS gerekli mi — ve NEDEN.

	Gereklilik tek bir eşikten değil, üç ayrı olgudan çıkar (`required_if_any`);
	hangisinin tetiklediğini kaydetmek, "bu videoya neden HLS ürettik"
	sorusunun sonradan cevaplanabilmesi demektir.
	"""

	required: bool
	reasons: List[str] = field(default_factory=list)
	checked: Dict[str, Any] = field(default_factory=dict)

	def as_dict(self) -> Dict[str, Any]:
		return {"required": self.required, "reasons": list(self.reasons), "checked": dict(self.checked)}


@dataclass
class HlsVariantResult:
	"""Üretilmiş tek basamak."""

	name: str
	width: int
	height: int
	bitrate_kbps: int
	playlist_path: str
	segment_count: int = 0
	bytes_total: int = 0
	target_duration_s: float = 0.0
	#: T-074/3 — mobil veri tavanı. İlk `startup_window_s` saniyeyi göstermek
	#: için inen bayt; `startup_gate` tavanla karşılaştırmanın sonucu.
	startup_bytes: int = 0
	startup_segments: int = 0
	startup_covered_s: float = 0.0
	startup_gate: str = "OLCULMEDI"
	#: W7 — basamak başına fayda kapısı (`enforce_rung_benefit_gate`).
	#: `UYGULANMADI`: kapı hiç çağrılmadı (make_hls tek başına uygulamaz);
	#: `GECTI`/`DUSTU`: basamağın toplam baytı kaynakla karşılaştırıldı.
	#: `published=False` olan basamak master playlist'ten ÇIKARILMIŞTIR.
	benefit_gate: str = "UYGULANMADI"
	published: bool = True

	def as_dict(self) -> Dict[str, Any]:
		return {
			"name": self.name,
			"resolution": f"{self.width}x{self.height}",
			"bitrate_kbps": self.bitrate_kbps,
			"playlist": os.path.basename(self.playlist_path),
			"segments": self.segment_count,
			"bytes": self.bytes_total,
			"target_duration_s": self.target_duration_s,
			"startup_bytes": self.startup_bytes,
			"startup_segments": self.startup_segments,
			"startup_covered_s": self.startup_covered_s,
			"startup_gate": self.startup_gate,
			"benefit_gate": self.benefit_gate,
			"published": self.published,
		}


@dataclass
class HlsResult:
	"""Bir HLS paketinin tamamı."""

	master_path: str
	out_dir: str
	variants: List[HlsVariantResult] = field(default_factory=list)
	wall_s: float = 0.0
	cmd: Tuple[str, ...] = ()
	src_bytes: int = 0
	peak_rss_bytes: int = 0
	cpu_user_s: float = 0.0
	cpu_system_s: float = 0.0
	limits_applied: Tuple[str, ...] = ()
	notes: List[str] = field(default_factory=list)

	@property
	def bytes_total(self) -> int:
		return sum(v.bytes_total for v in self.variants)

	@property
	def lowest(self) -> Optional[HlsVariantResult]:
		"""3G'deki alıcının indireceği basamak — HLS'in asıl kazancı burada."""
		return min(self.variants, key=lambda v: v.bitrate_kbps) if self.variants else None

	@property
	def published_variants(self) -> List[HlsVariantResult]:
		"""Master playlist'te GERÇEKTEN ilan edilen basamaklar (W7 kapısı sonrası)."""
		return [v for v in self.variants if v.published]

	@property
	def published_bytes(self) -> int:
		return sum(v.bytes_total for v in self.published_variants)

	def as_dict(self) -> Dict[str, Any]:
		return {
			"master": os.path.basename(self.master_path),
			"out_dir": self.out_dir,
			"variants": [v.as_dict() for v in self.variants],
			"bytes_total": self.bytes_total,
			"src_bytes": self.src_bytes,
			"wall_s": round(self.wall_s, 2),
			"peak_rss_bytes": self.peak_rss_bytes,
			"cpu_user_s": round(self.cpu_user_s, 3),
			"cpu_system_s": round(self.cpu_system_s, 3),
			"limits_applied": list(self.limits_applied),
			"notes": list(self.notes),
		}


# ── Gereklilik ──────────────────────────────────────────────────────────


def hls_required(
	facts: VideoFacts,
	*,
	rendition_bytes: int = 0,
	distinct_tiers: int = 0,
	spec: Optional[HlsSpec] = None,
) -> HlsRequirement:
	"""`required_if_any` — üç koşuldan HERHANGİ BİRİ HLS'i gerektirir.

	`rendition_bytes` verilmezse kaynak dosyanın boyutu kullanılır ve bu not
	edilir: gerçek ölçü, teslim edilecek EN BÜYÜK rendition'ın boyutudur;
	kaynak onun üst sınırıdır, dolayısıyla vekil olarak kullanmak yanlış
	yönde hata yapmaz (gereksiz HLS üretebilir, gerekliyi atlamaz).
	"""
	spec = spec or HlsSpec.from_table()
	notlar: List[str] = []
	bayt = rendition_bytes or facts.size_bytes
	if not rendition_bytes:
		notlar.append("rendition boyutu verilmedi — kaynak boyutu vekil olarak kullanildi")

	sebepler: List[str] = []
	if facts.duration_s > spec.duration_s_gt:
		sebepler.append(f"sure {facts.duration_s:.1f} sn > {spec.duration_s_gt:.0f} sn")
	if bayt > spec.max_rendition_bytes_gt:
		sebepler.append(f"rendition {bayt} B > {spec.max_rendition_bytes_gt} B")
	if distinct_tiers > spec.distinct_resolution_tiers_gt:
		sebepler.append(f"cozunurluk basamagi {distinct_tiers} > {spec.distinct_resolution_tiers_gt}")

	return HlsRequirement(
		required=bool(sebepler),
		reasons=sebepler + notlar,
		checked={
			"duration_s": round(facts.duration_s, 3),
			"rendition_bytes": bayt,
			"distinct_tiers": distinct_tiers,
		},
	)


# ── Merdiven budama ─────────────────────────────────────────────────────


def select_ladder(facts: VideoFacts, spec: Optional[HlsSpec] = None) -> List[HlsRung]:
	"""Kaynağa uyan basamakları seç. **Büyütme yok.**

	Ölçü kısa kenardır (`HlsRung.tier` ↔ `VideoFacts.short_edge`): kaynağın
	kısa kenarından BÜYÜK basamaklar düşürülür.

	Kaynak en alt basamaktan da küçükse (ör. 352×352 ya da 320×240) merdiven
	boş kalır. O durumda tek bir "kaynak" basamağı üretilir: kaynağın kendi
	ölçüsünde, en alt basamağın bitrate kapısıyla. Boş bir merdiven döndürmek,
	çağıranı ffmpeg'e sıfır çıktıyla girmeye zorlardı.
	"""
	spec = spec or HlsSpec.from_table()
	merdiven = sorted(spec.ladder, key=lambda r: r.tier)
	if not merdiven:
		return []

	kisa = facts.short_edge
	if not kisa:
		return list(merdiven)

	secilen = [r for r in merdiven if not spec.no_upscale or r.tier <= kisa]
	if secilen:
		return secilen

	en_alt = merdiven[0]
	return [
		HlsRung(
			name=f"{kisa}p",
			width=facts.width,
			height=facts.height,
			bitrate_kbps=en_alt.bitrate_kbps,
			maxrate_kbps=en_alt.maxrate_kbps,
			bufsize_kbps=en_alt.bufsize_kbps,
			audio_kbps=en_alt.audio_kbps,
		)
	]


def rung_dimensions(rung: HlsRung, facts: VideoFacts) -> Tuple[int, int]:
	"""Basamağın kaynak yönelimindeki gerçek ölçüsü (çift sayıya yuvarlanmış).

	yuv420p tek sayılı kenar kabul etmez; ffmpeg tarafında `-2` bunu kendisi
	yapar, burada aynı hesabı raporlamak için yapıyoruz (master playlist'e
	`RESOLUTION` yazan ffmpeg'in kendisi, ama testin beklentisi bu hesaptan
	çıkar).
	"""
	if not facts.width or not facts.height:
		return (rung.width, rung.height)
	dikey = facts.height > facts.width
	hedef = rung.tier
	if dikey:
		g = hedef
		y = int(round(facts.height * hedef / facts.width / 2)) * 2
	else:
		y = hedef
		g = int(round(facts.width * hedef / facts.height / 2)) * 2
	return (max(g, 2), max(y, 2))


def _scale_expr(rung: HlsRung, facts: VideoFacts) -> str:
	"""Yönelime göre ölçek filtresi. Kısa kenar basamağa sabitlenir.

	Yönelim künyeden BİLİNDİĞİ için ffmpeg `if(gt(iw,ih),…)` ifadesine gerek
	yok — okunaksız bir filtergraph, ölçülmüş bir olgunun yerine geçmemeli.
	"""
	if facts.height > facts.width:
		return f"scale=w={rung.tier}:h=-2"
	return f"scale=w=-2:h={rung.tier}"


# ── GOP hizası ──────────────────────────────────────────────────────────


def check_gop_alignment(spec: HlsSpec, h264: H264Spec) -> Tuple[bool, str]:
	"""Anahtar kare aralığı segment süresini tam bölüyor mu?

	Bölmüyorsa segment sınırı anahtar kareye denk gelemez; ffmpeg segmenti
	bir sonraki anahtar kareye kadar UZATIR ve `#EXT-X-TARGETDURATION`
	istenenden büyük çıkar. Bu, bir hata değil bir yapılandırma kusurudur ve
	sessizce geçmemelidir.
	"""
	if h264.keyframe_interval_s <= 0:
		return (False, "keyframe_interval_s sifir ya da negatif")
	oran = spec.segment_duration_s / h264.keyframe_interval_s
	if abs(oran - round(oran)) > 1e-6:
		return (
			False,
			f"segment {spec.segment_duration_s} sn, anahtar kare araligi "
			f"{h264.keyframe_interval_s} sn tarafindan tam bolunmuyor",
		)
	return (True, "")


def gop_frames(facts: VideoFacts, h264: H264Spec) -> int:
	"""Anahtar kare aralığının KARE cinsinden karşılığı.

	Kaynak kare hızı tavanın üstündeyse çıktı tavanda olacağı için hesap
	tavandan yapılır — aksi halde 60 fps kaynakta GOP iki katına çıkar ve
	segment sınırı kayar.
	"""
	fps = min(facts.fps or float(h264.frame_rate_cap), float(h264.frame_rate_cap))
	return max(int(round(fps * h264.keyframe_interval_s)), 1)


# ── ffmpeg komutu ───────────────────────────────────────────────────────


def _rate_control_args(i: int, rung: HlsRung, spec: HlsSpec) -> List[str]:
	"""Basamağın hız denetimi argümanları. Varsayılan: **capped CRF**.

	İLK KOŞUM SABİT BİTRATE (`-b:v`) İLE YAPILDI VE MERDİVEN BAYT ŞİŞİRDİ —
	ölçülmüş sayılar (ffmpeg 5.1.9, `video_decision.json` `hls.rate_control_why`):

	    video_efficient_720p_750k.mp4   kaynak 1.092.127 B → 360p 1.155.673 B  (+%5,8)
	    video_square_352.mp4              kaynak   294.350 B → 352p   585.065 B  (+%98)
	    video_long_540s_320x240.mp4       kaynak 3.986.750 B → 240p 17.833.465 B (4,5 kat)

	Sebep basit ve kalıcıdır: `-b:v` bir HEDEFTİR, tavan değil. Doğal bitrate'i
	basamağın hedefinin altında kalan içerikte libx264 aradaki farkı DOLDURUR;
	kazanılacak bayt yokken bit harcar. Merdivenin varlık sebebi bant genişliği
	tasarrufuyken, sabit bitrate onu tersine çevirir.

	`capped_crf` kaliteyi `-crf` ile sürer, tavanı `-maxrate`/`-bufsize` ile
	korur — HLS oynatıcısının ihtiyacı olan tek garanti budur (bir basamağın
	bant genişliğini AŞMAMASI), bit HARCAMASI değil.

	`rate_control: "cbr"` eski davranışı geri getirir; tabloda tek satır.
	"""
	tavan = rung.maxrate_kbps or rung.bitrate_kbps
	tampon = rung.bufsize_kbps or rung.bitrate_kbps * 2
	if spec.rate_control == "cbr":
		return [
			f"-b:v:{i}", f"{rung.bitrate_kbps}k",
			f"-maxrate:v:{i}", f"{tavan}k",
			f"-bufsize:v:{i}", f"{tampon}k",
		]
	return [
		f"-crf:v:{i}", str(spec.crf),
		f"-maxrate:v:{i}", f"{tavan}k",
		f"-bufsize:v:{i}", f"{tampon}k",
	]


def build_hls_cmd(
	src: str,
	out_dir: str,
	rungs: Sequence[HlsRung],
	facts: VideoFacts,
	*,
	spec: Optional[HlsSpec] = None,
	h264: Optional[H264Spec] = None,
	nice: bool = True,
) -> List[str]:
	"""Tek koşumda N basamaklı HLS komutu.

	Kaynak `split=N` ile bir kez çözülüp N kola dağıtılır; her kol kendi
	ölçeğine iner ve kendi kodlayıcı ayarlarını alır. `var_stream_map`
	hangi video akışının hangi ses akışıyla eşleneceğini söyler.

	Ses akışı YOKSA ne `-map a` ne de `a:` eşlemesi yazılır: olmayan akışı
	istemek ffmpeg'i "Stream map matches no streams" ile düşürür.
	"""
	spec = spec or HlsSpec.from_table()
	h264 = h264 or H264Spec.from_table()
	if not rungs:
		raise TranscodeFailed("HLS icin basamak secilmedi", kod=f"media_{SEBEP_TRANSCODE_FAILED}")

	n = len(rungs)
	gop = gop_frames(facts, h264)
	sesli = facts.has_audio

	kollar = "".join(f"[v{i}]" for i in range(n))
	kaynak = "[0:v]"
	parcalar: List[str] = []
	if facts.is_hdr:
		parcalar.append(
			"[0:v]zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
			"tonemap=tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv,format=yuv420p[hdr]"
		)
		kaynak = "[hdr]"
	parcalar.append(f"{kaynak}split={n}{kollar}" if n > 1 else f"{kaynak}null[v0]")
	if n > 1:
		for i, rung in enumerate(rungs):
			parcalar.append(f"[v{i}]{_scale_expr(rung, facts)}[vo{i}]")
	else:
		# Son ``null[v0]`` kolunu ölçek koluna bağla; HDR ön filtresi varsa
		# zincir korunur, yoksa de gereksiz ikinci decode oluşmaz.
		parcalar.append(f"[v0]{_scale_expr(rungs[0], facts)}[vo0]")
	filtre = ";".join(parcalar)

	cmd: List[str] = list(NICE_PREFIX) if nice else []
	cmd += [
		"ffmpeg", "-y",
		"-filter_threads", str(h264.encoder_threads),
		"-filter_complex_threads", str(h264.encoder_threads),
		"-i", src, "-filter_complex", filtre,
	]

	for i, rung in enumerate(rungs):
		cmd += [
			"-map", f"[vo{i}]",
			f"-c:v:{i}", h264.video_codec,
			f"-threads:v:{i}", str(h264.encoder_threads),
			f"-profile:v:{i}", h264.profile,
			f"-preset:v:{i}", h264.preset,
		]
		cmd += _rate_control_args(i, rung, spec)
		cmd += [
			f"-g:v:{i}", str(gop),
			f"-keyint_min:v:{i}", str(gop),
			f"-sc_threshold:v:{i}", "0",
		]
		if facts.is_hdr:
			cmd += [
				f"-color_primaries:v:{i}", "bt709",
				f"-color_trc:v:{i}", "bt709",
				f"-colorspace:v:{i}", "bt709",
			]
	cmd += ["-pix_fmt", h264.pix_fmt]
	if facts.fps and facts.fps > h264.frame_rate_cap:
		cmd += ["-r", str(h264.frame_rate_cap)]

	if sesli:
		for i, rung in enumerate(rungs):
			cmd += [
				"-map", "0:a:0",
				f"-c:a:{i}", h264.audio_codec,
				f"-b:a:{i}", f"{rung.audio_kbps or h264.audio_bitrate_kbps}k",
				f"-ac:a:{i}", str(h264.audio_channels),
				f"-ar:a:{i}", str(h264.audio_sample_rate),
			]
		harita = " ".join(f"v:{i},a:{i},name:{r.name}" for i, r in enumerate(rungs))
	else:
		harita = " ".join(f"v:{i},name:{r.name}" for i, r in enumerate(rungs))

	cmd += [
		"-f", "hls",
		"-hls_time", str(spec.segment_duration_s),
		"-hls_playlist_type", spec.playlist_type,
		"-hls_segment_type", spec.segment_type,
		# `independent_segments`: her segment kendi başına çözülebilir. Bunu
		# ilan etmek oynatıcının basamak değiştirirken segment sınırında
		# geçiş yapmasına izin verir — merdivenin varlık sebebi bu.
		"-hls_flags", "independent_segments",
		"-hls_segment_filename",
		os.path.join(out_dir, VARIANT_DIR_PATTERN, "seg%03d." + ("m4s" if spec.segment_type == "fmp4" else "ts")),
		"-master_pl_name", MASTER_PLAYLIST_NAME,
		"-var_stream_map", harita,
		"-progress", "pipe:1", "-nostats",
		os.path.join(out_dir, VARIANT_DIR_PATTERN, MEDIA_PLAYLIST_NAME),
	]
	return cmd


# ── Playlist okuma ──────────────────────────────────────────────────────

_TARGETDUR_RE = re.compile(r"#EXT-X-TARGETDURATION:\s*([0-9]+)")
_EXTINF_RE = re.compile(r"#EXTINF:\s*([0-9.]+)")
_STREAMINF_RE = re.compile(r"#EXT-X-STREAM-INF:([^\n]*)")
_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')


def parse_master(path: str) -> List[Dict[str, Any]]:
	"""Master playlist'teki `EXT-X-STREAM-INF` girdilerini oku.

	Testin ffmpeg'in ne ürettiğini DOĞRULAYABİLMESİ için var: "1080p üretmedik"
	iddiası ancak master playlist'te 1080p satırının yokluğuyla kanıtlanır.
	"""
	try:
		with open(path, "r", encoding="utf-8") as f:
			metin = f.read()
	except OSError:
		return []
	satirlar = metin.splitlines()
	sonuc: List[Dict[str, Any]] = []
	for i, satir in enumerate(satirlar):
		m = _STREAMINF_RE.match(satir.strip())
		if not m:
			continue
		nitelikler: Dict[str, Any] = {}
		for anahtar, deger in _ATTR_RE.findall(m.group(1)):
			nitelikler[anahtar] = deger.strip('"')
		uri = ""
		for sonraki in satirlar[i + 1:]:
			if sonraki.strip() and not sonraki.startswith("#"):
				uri = sonraki.strip()
				break
		nitelikler["URI"] = uri
		sonuc.append(nitelikler)
	return sonuc


def playlist_stats(playlist_path: str) -> Tuple[int, int, float]:
	"""(segment sayısı, toplam bayt, TARGETDURATION) — medya playlist'inden."""
	dizin = os.path.dirname(playlist_path)
	try:
		with open(playlist_path, "r", encoding="utf-8") as f:
			metin = f.read()
	except OSError:
		return (0, 0, 0.0)
	segmentler = [s.strip() for s in metin.splitlines() if s.strip() and not s.startswith("#")]
	bayt = 0
	for s in segmentler:
		yol = os.path.join(dizin, s)
		try:
			bayt += os.path.getsize(yol)
		except OSError:
			pass
	m = _TARGETDUR_RE.search(metin)
	hedef = float(m.group(1)) if m else 0.0
	try:
		bayt += os.path.getsize(playlist_path)
	except OSError:
		pass
	return (len(segmentler), bayt, hedef)


def startup_bytes(playlist_path: str, window_s: float = 10.0) -> Tuple[int, int, float]:
	"""Oynatıcının ilk `window_s` saniyeyi göstermek için indireceği bayt.

	Döner: `(bayt, segment sayısı, kapsanan süre)`.

	**Neden toplam bayt bu soruyu cevaplamıyor.** 540 saniyelik bir kaynağın
	360p basamağı toplamda 700 KB olabilir; aynı basamağın ilk 10 saniyesi
	60 KB'dır. Mobil veri tavanı (T-074/3) toplamı değil AÇILIŞI sorar —
	kullanıcı videoya dokunduktan sonra ilk 10 saniyede ne iniyor.

	**Pencereyi aşan segment de sayılır.** Oynatıcı bir segmenti yarıda
	kesip kullanamaz; 4 saniyelik segmentlerle 10 saniyelik pencere üç
	segment (12 sn) indirmek demektir. Aşağı yuvarlamak baytı olduğundan
	küçük gösterirdi.

	**Playlist'in kendisi de sayılır.** Oynatıcı önce master'ı, sonra medya
	playlist'ini indirir; ilk bayt onlardır. Master burada YOK — çağıran
	basamak başına ölçüyor; master birkaç yüz bayttır ve `make_hls` notunda
	ayrıca kayıtlıdır.
	"""
	dizin = os.path.dirname(playlist_path)
	try:
		with open(playlist_path, "r", encoding="utf-8") as f:
			metin = f.read()
	except OSError:
		return (0, 0, 0.0)

	bayt = 0
	try:
		bayt += os.path.getsize(playlist_path)
	except OSError:
		pass

	sure = 0.0
	sayi = 0
	bekleyen: Optional[float] = None
	for satir in metin.splitlines():
		s = satir.strip()
		if not s:
			continue
		m = _EXTINF_RE.match(s)
		if m:
			try:
				bekleyen = float(m.group(1))
			except ValueError:
				bekleyen = None
			continue
		if s.startswith("#"):
			continue
		# Segment satırı.
		try:
			bayt += os.path.getsize(os.path.join(dizin, s))
		except OSError:
			pass
		sayi += 1
		sure += bekleyen or 0.0
		bekleyen = None
		if sure >= window_s:
			break
	return (bayt, sayi, round(sure, 3))


# ── Üretim ──────────────────────────────────────────────────────────────


def make_hls(
	src: str,
	out_dir: str,
	*,
	spec: Optional[HlsSpec] = None,
	h264: Optional[H264Spec] = None,
	facts: Optional[VideoFacts] = None,
	timeout: int = FFMPEG_TIMEOUT_SECONDS,
	nice: bool = True,
	progress_callback: Optional[Callable[[Mapping[str, str]], None]] = None,
	cancel_check: Optional[Callable[[], bool]] = None,
) -> HlsResult:
	"""Merdiveni üret. Çıktı `out_dir` altında: `master.m3u8` + basamak dizinleri.

	Kısmi başarı YOKTUR (sözleşme `transcode_all` ile aynı gerekçe): tek
	ffmpeg koşumu ya hepsini üretir ya hiçbirini. Yarım bir merdiven, master
	playlist'te ilan edilip 404 veren bir basamak demektir.
	"""
	spec = spec or HlsSpec.from_table()
	h264 = h264 or H264Spec.from_table()
	facts = facts or probe_modulu.probe(src)
	if not facts.measured:
		raise ProbeUnavailable(f"kunye okunamadi: {facts.error}", detay={"error": facts.error})

	rungs = select_ladder(facts, spec)
	notlar: List[str] = []
	hizali, sebep = check_gop_alignment(spec, h264)
	if not hizali:
		notlar.append(f"GOP hizasi UYARISI: {sebep}")

	ust = os.path.dirname(os.path.abspath(out_dir)) or os.curdir
	os.makedirs(ust, exist_ok=True)
	stage = tempfile.mkdtemp(prefix=f".{os.path.basename(out_dir)}.part-", dir=ust)
	# ffmpeg `%v` dizinlerini KENDİSİ oluşturmaz; `-hls_segment_filename` bir
	# alt dizin içeriyorsa dizin önceden var olmalıdır (aksi halde "No such
	# file or directory" ile düşer — gerçek ffmpeg 5.1 ile doğrulandı).
	for rung in rungs:
		os.makedirs(variant_dir(stage, rung), exist_ok=True)

	cmd = build_hls_cmd(src, stage, rungs, facts, spec=spec, h264=h264, nice=nice)
	basla = time.monotonic()
	try:
		kosum = run_ffmpeg(
			cmd,
			timeout=timeout,
			progress_callback=progress_callback,
			cancel_check=cancel_check,
		)
	except Exception:
		shutil.rmtree(stage, ignore_errors=True)
		raise
	sure = time.monotonic() - basla

	master = os.path.join(stage, MASTER_PLAYLIST_NAME)
	varyantlar: List[HlsVariantResult] = []
	for rung in rungs:
		playlist = variant_playlist(stage, rung)
		sayi, bayt, hedef = playlist_stats(playlist)
		g, y = rung_dimensions(rung, facts)
		acilis, acilis_seg, acilis_sure = startup_bytes(playlist, spec.startup_window_s)
		varyantlar.append(
			HlsVariantResult(
				name=rung.name,
				width=g,
				height=y,
				bitrate_kbps=rung.bitrate_kbps,
				playlist_path=playlist,
				segment_count=sayi,
				bytes_total=bayt,
				target_duration_s=hedef,
				startup_bytes=acilis,
				startup_segments=acilis_seg,
				startup_covered_s=acilis_sure,
				startup_gate=(
					"OLCULMEDI"
					if not acilis_seg
					else ("GECTI" if acilis <= spec.startup_max_bytes else "DUSTU")
				),
			)
		)

	if not os.path.exists(master) or any(not v.segment_count for v in varyantlar):
		shutil.rmtree(stage, ignore_errors=True)
		raise TranscodeFailed(
			"HLS merdiveni eksik uretildi",
			kod=f"media_{SEBEP_TRANSCODE_FAILED}",
			detay={"out_dir": out_dir, "segments": {v.name: v.segment_count for v in varyantlar}},
		)

	# Bütün merdiven doğrulandıktan sonra tek promote. Önceki tam paket varsa
	# yeni paket hazır olana dek yerinde kalır; promote hatasında geri alınır.
	yedek = f"{out_dir}.previous-{os.getpid()}-{time.monotonic_ns()}"
	eski_var = os.path.exists(out_dir)
	try:
		if eski_var:
			os.replace(out_dir, yedek)
		os.replace(stage, out_dir)
	except Exception:
		if eski_var and os.path.exists(yedek) and not os.path.exists(out_dir):
			os.replace(yedek, out_dir)
		shutil.rmtree(stage, ignore_errors=True)
		raise
	finally:
		if os.path.exists(yedek):
			shutil.rmtree(yedek, ignore_errors=True)

	master = os.path.join(out_dir, MASTER_PLAYLIST_NAME)
	for v, rung in zip(varyantlar, rungs):
		v.playlist_path = variant_playlist(out_dir, rung)

	return HlsResult(
		master_path=master,
		out_dir=out_dir,
		variants=varyantlar,
		wall_s=sure,
		cmd=tuple(cmd),
		src_bytes=facts.size_bytes,
		peak_rss_bytes=kosum.peak_rss_bytes,
		cpu_user_s=kosum.cpu_user_s,
		cpu_system_s=kosum.cpu_system_s,
		limits_applied=tuple(kosum.limits_applied),
		notes=notlar,
	)


def enforce_rung_benefit_gate(
	result: HlsResult,
	*,
	src_bytes: Optional[int] = None,
	delete_dropped: bool = True,
) -> HlsResult:
	"""Basamak başına fayda kapısı (W7): **kaynaktan büyük basamak İLAN EDİLMEZ**.

	ÖLÇÜLMÜŞ GEREKÇE (rapor 81 §4): 9,6 MB'lık gerçek DEV videosunda (142 kbps,
	çok verimli kaynak) capped-CRF merdiveni 720p basamağını kaynaktan %26 BÜYÜK
	üretti (9.622.536 → 12.095.893 B). Oynatıcı geniş bantta o basamağı seçer ve
	alıcı, tek dosyayı indirmekten DAHA FAZLA bayt öder — merdivenin varlık
	sebebinin tam tersi.

	Kapı `make_hls` İÇİNDE değil AYRI bir adımdır ve üretim yolu
	(`media/pipeline_bridge.py::_run_video_job`) tarafından çağrılır. Sebep:
	motorun mevcut sözleşmesi ("merdiveni üret, ölç, karar çağıranın") ve onun
	üstüne kurulmuş gerçek-koşum testleri merdivenin TAMAMINI görmeye devam
	etmeli — kapı bir TESLİM kararıdır, üretim kusuru değil.

	Kural: basamağın toplam baytı (playlist + segmentler) kaynaktan KÜÇÜK
	değilse basamak master playlist'ten çıkarılır ve (varsayılan) dosyaları
	silinir — ilan edilmeyen segmentleri diskte tutmak öksüz dosya üretmektir.
	HİÇBİR basamak kaynaktan küçük değilse paketin kendisi ilan edilmez:
	master silinir, `master_path` boşalır; teslim progresif mp4'te kalır
	(HLS'in o dosyaya verebileceği hiçbir şey yoktur).

	`src_bytes` verilmezse `result.src_bytes` (make_hls'e giren dosyanın
	boyutu) kullanılır; o da yoksa kapı UYGULANMAZ ve not düşülür — ölçüsüz
	karar verilmez.
	"""
	kaynak = int(src_bytes if src_bytes is not None else result.src_bytes or 0)
	if kaynak <= 0:
		result.notes.append("basamak fayda kapisi UYGULANMADI: kaynak boyutu olculemedi")
		return result

	dusen: List[HlsVariantResult] = []
	for v in result.variants:
		gecti = v.bytes_total < kaynak
		v.benefit_gate = "GECTI" if gecti else "DUSTU"
		v.published = gecti
		if not gecti:
			dusen.append(v)

	kalan = result.published_variants
	if not dusen:
		result.notes.append(
			f"basamak fayda kapisi: {len(kalan)}/{len(result.variants)} basamak kaynaktan kucuk, master degismedi"
		)
		return result

	if not kalan:
		# Paketin tamamı kaynaktan büyük: HLS bu dosyaya hiçbir şey kazandırmıyor.
		if delete_dropped:
			import shutil

			shutil.rmtree(result.out_dir, ignore_errors=True)
		result.master_path = ""
		result.notes.append(
			f"basamak fayda kapisi: {len(dusen)}/{len(result.variants)} basamagin HEPSI kaynaktan buyuk "
			f"-> HLS paketi ILAN EDILMEZ, teslim progresif mp4'te kalir"
		)
		return result

	_rewrite_master(
		result.master_path,
		kept_uris={_master_uri(result.out_dir, v.playlist_path) for v in kalan},
	)
	for v in dusen:
		if delete_dropped:
			import shutil

			shutil.rmtree(os.path.dirname(v.playlist_path), ignore_errors=True)
	result.notes.append(
		"basamak fayda kapisi: "
		+ ", ".join(f"{v.name} {v.bytes_total} B >= kaynak {kaynak} B -> ILAN EDILMEDI" for v in dusen)
	)
	return result


def _master_uri(out_dir: str, playlist_path: str) -> str:
	"""Basamağın master playlist'te görünen göreli URI'si (`v360p/playlist.m3u8`)."""
	return os.path.relpath(playlist_path, out_dir).replace(os.sep, "/")


def _rewrite_master(master_path: str, kept_uris: set) -> None:
	"""Master playlist'i yalnız tutulan basamaklarla yeniden yazar.

	ffmpeg'in ürettiği yapı satır çiftleridir: `#EXT-X-STREAM-INF:...` + URI.
	Düşen basamağın çifti atlanır; diğer tüm satırlar (başlık, sürüm,
	independent_segments) olduğu gibi korunur. Atomiklik `os.replace` ile —
	yarım master, 404 veren basamaktan da kötüdür (hiçbir oynatıcı açamaz).
	"""
	with open(master_path, "r", encoding="utf-8") as f:
		satirlar = f.read().splitlines()

	yeni: List[str] = []
	atla_uri = False
	for i, satir in enumerate(satirlar):
		s = satir.strip()
		if _STREAMINF_RE.match(s):
			# Bu STREAM-INF'in URI'si bir SONRAKİ yorum-olmayan satırdır.
			uri = ""
			for sonraki in satirlar[i + 1:]:
				t = sonraki.strip()
				if t and not t.startswith("#"):
					uri = t
					break
			if uri not in kept_uris:
				atla_uri = True
				continue
			yeni.append(satir)
			continue
		if atla_uri and s and not s.startswith("#"):
			atla_uri = False
			continue
		yeni.append(satir)

	gecici = master_path + ".part"
	with open(gecici, "w", encoding="utf-8") as f:
		f.write("\n".join(yeni) + "\n")
	os.replace(gecici, master_path)


def ffmpeg_has_hls_muxer() -> bool:
	"""ffmpeg `hls` muxer'ıyla derlenmiş mi — testlerin atlama kararı için."""
	try:
		sonuc = run_ffmpeg(["ffmpeg", "-hide_banner", "-muxers"], timeout=30)
		cikti = ((sonuc.stdout or b"") + b"\n" + (sonuc.stderr or b"")).decode("utf-8", "replace")
	except (ProbeUnavailable, TranscodeFailed):
		return False
	return bool(re.search(r"^\s*\S*E\s+hls\s", cikti, re.MULTILINE))


__all__ = [
	"MASTER_PLAYLIST_NAME",
	"MEDIA_PLAYLIST_NAME",
	"VARIANT_DIR_PATTERN",
	"variant_dir",
	"variant_playlist",
	"HlsRung",
	"HlsSpec",
	"HlsRequirement",
	"HlsVariantResult",
	"HlsResult",
	"hls_required",
	"select_ladder",
	"rung_dimensions",
	"check_gop_alignment",
	"gop_frames",
	"build_hls_cmd",
	"parse_master",
	"playlist_stats",
	"startup_bytes",
	"make_hls",
	"enforce_rung_benefit_gate",
	"ffmpeg_has_hls_muxer",
]
