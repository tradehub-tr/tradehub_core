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
import subprocess
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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
	duration_s_gt: float = 60.0
	max_rendition_bytes_gt: int = 12_582_912
	distinct_resolution_tiers_gt: int = 2

	@classmethod
	def from_table(cls, blok: Optional[Mapping[str, Any]] = None) -> "HlsSpec":
		h = dict(blok if blok is not None else default_table().hls)
		kosul = dict(h.get("required_if_any") or {})
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

	def as_dict(self) -> Dict[str, Any]:
		return {
			"name": self.name,
			"resolution": f"{self.width}x{self.height}",
			"bitrate_kbps": self.bitrate_kbps,
			"playlist": os.path.basename(self.playlist_path),
			"segments": self.segment_count,
			"bytes": self.bytes_total,
			"target_duration_s": self.target_duration_s,
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
	notes: List[str] = field(default_factory=list)

	@property
	def bytes_total(self) -> int:
		return sum(v.bytes_total for v in self.variants)

	@property
	def lowest(self) -> Optional[HlsVariantResult]:
		"""3G'deki alıcının indireceği basamak — HLS'in asıl kazancı burada."""
		return min(self.variants, key=lambda v: v.bitrate_kbps) if self.variants else None

	def as_dict(self) -> Dict[str, Any]:
		return {
			"master": os.path.basename(self.master_path),
			"out_dir": self.out_dir,
			"variants": [v.as_dict() for v in self.variants],
			"bytes_total": self.bytes_total,
			"src_bytes": self.src_bytes,
			"wall_s": round(self.wall_s, 2),
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
	parcalar = [f"[0:v]split={n}{kollar}"] if n > 1 else ["[0:v]null[v0]"]
	if n > 1:
		for i, rung in enumerate(rungs):
			parcalar.append(f"[v{i}]{_scale_expr(rung, facts)}[vo{i}]")
	else:
		parcalar = [f"[0:v]{_scale_expr(rungs[0], facts)}[vo0]"]
	filtre = ";".join(parcalar)

	cmd: List[str] = list(NICE_PREFIX) if nice else []
	cmd += ["ffmpeg", "-y", "-i", src, "-filter_complex", filtre]

	for i, rung in enumerate(rungs):
		cmd += [
			"-map", f"[vo{i}]",
			f"-c:v:{i}", h264.video_codec,
			f"-profile:v:{i}", h264.profile,
			f"-preset:v:{i}", h264.preset,
		]
		cmd += _rate_control_args(i, rung, spec)
		cmd += [
			f"-g:v:{i}", str(gop),
			f"-keyint_min:v:{i}", str(gop),
			f"-sc_threshold:v:{i}", "0",
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
		os.path.join(out_dir, VARIANT_DIR_PATTERN, MEDIA_PLAYLIST_NAME),
	]
	return cmd


# ── Playlist okuma ──────────────────────────────────────────────────────

_TARGETDUR_RE = re.compile(r"#EXT-X-TARGETDURATION:\s*([0-9]+)")
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
) -> HlsResult:
	"""Merdiveni üret. Çıktı `out_dir` altında: `master.m3u8` + basamak dizinleri.

	Kısmi başarı YOKTUR (sözleşme `transcode_all` ile aynı gerekçe): tek
	ffmpeg koşumu ya hepsini üretir ya hiçbirini. Yarım bir merdiven, master
	playlist'te ilan edilip 404 veren bir basamak demektir.
	"""
	import time

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

	os.makedirs(out_dir, exist_ok=True)
	# ffmpeg `%v` dizinlerini KENDİSİ oluşturmaz; `-hls_segment_filename` bir
	# alt dizin içeriyorsa dizin önceden var olmalıdır (aksi halde "No such
	# file or directory" ile düşer — gerçek ffmpeg 5.1 ile doğrulandı).
	for rung in rungs:
		os.makedirs(variant_dir(out_dir, rung), exist_ok=True)

	cmd = build_hls_cmd(src, out_dir, rungs, facts, spec=spec, h264=h264, nice=nice)
	basla = time.monotonic()
	run_ffmpeg(cmd, timeout=timeout)
	sure = time.monotonic() - basla

	master = os.path.join(out_dir, MASTER_PLAYLIST_NAME)
	varyantlar: List[HlsVariantResult] = []
	for rung in rungs:
		playlist = variant_playlist(out_dir, rung)
		sayi, bayt, hedef = playlist_stats(playlist)
		g, y = rung_dimensions(rung, facts)
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
			)
		)

	if not os.path.exists(master):
		raise TranscodeFailed(
			"master playlist uretilmedi",
			kod=f"media_{SEBEP_TRANSCODE_FAILED}",
			detay={"out_dir": out_dir},
		)

	return HlsResult(
		master_path=master,
		out_dir=out_dir,
		variants=varyantlar,
		wall_s=sure,
		cmd=tuple(cmd),
		src_bytes=facts.size_bytes,
		notes=notlar,
	)


def ffmpeg_has_hls_muxer() -> bool:
	"""ffmpeg `hls` muxer'ıyla derlenmiş mi — testlerin atlama kararı için."""
	try:
		cikti = subprocess.run(
			["ffmpeg", "-hide_banner", "-muxers"], capture_output=True, timeout=30
		).stdout.decode("utf-8", "replace")
	except (OSError, subprocess.SubprocessError):
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
	"make_hls",
	"ffmpeg_has_hls_muxer",
]
