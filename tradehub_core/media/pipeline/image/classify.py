"""T-062 — İçerik sınıflandırma: 5 sınıf → biçim zinciri.

Bu modül ne yapar
-----------------
Görselin **içeriğini** beş sınıftan birine koyar ve o sınıf için denenecek
kodlayıcı **zincirini** verir. Sınıf, `normalize.py` çıktısı olan master'ın
türevlere hangi biçimle kodlanacağını belirler.

    animation    çok kareli
    transparent  anlamlı alfa taşıyor (kesim/logo)
    document     taranmış/metin baskın belge (keskin harf kenarları)
    graphic      düz alanlı sentetik görsel (logo, illüstrasyon)
    photo        sürekli tonlu fotoğraf  ← VARSAYILAN

Sıra ANLAMLIDIR ve yukarıdan aşağıya "kesin ölçülebilirden tahminiye" gider:
`animation` başlıktan **kesin** okunur, `transparent` alfa kanalından **kesin**
ölçülür; `graphic`/`document` ise sezgiseldir ve bilerek **yüksek kesinlik / düşük
duyarlılık** ayarındadır. Kanıt yetmiyorsa sınıf `photo` olur.

Teslim biçimi bütün statik sınıflarda AVIF'tir. Fotoğrafta q88, grafik,
raster belge ve belirsiz içerikte q100 başlangıcı kullanılır. q100 kayıpsızlık
iddiası değildir; kalite raporunda gerçek çıktı karşılaştırılır. Saydam
kaynak AVIF alfa desteği ister. Encoder yoksa başka biçime sessizce dönülmez.

Neden bazı ölçütler ölçülmedi — DÜRÜST SINIR
--------------------------------------------
`tradehub_core/tests/fixtures/media/` içindeki 34 görsel fixture'ın `class` alanı bir
**içerik sınıfı değil, fixture ailesi** etiketidir: `ok_product_1x1_2400.jpg`
("photo") ile `geom_strip_400x4000.png` ("graphic") piksel istatistiği olarak
AYNI şeydir — ikisi de rastgele gürültü. Bu korpus üzerinde içerik sınıflandırma
doğruluğu ÖLÇÜLEMEZ. Ölçüm bu yüzden canlı korpustan çekilen ve elle etiketlenen
48 görsel üzerinde yapıldı; sonuçlar `tests/test_image_classify.py` içinde
sabitlenmiştir.

Beş sınıfın her biri, 20'şer deterministik ve dengeli örnekten oluşan yeniden
üretilebilir AAA korpusunda ölçülür. Canlı 48'lik örneklem ayrıca korunur;
dengeli korpus sınıf adlarının hiçbirini çoğunluk sınıfıyla geçiştirmez.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, replace
from pathlib import Path

from tradehub_core.media.pipeline.image.probe import DEFAULT_GUARD, GuardConfig, HeaderProbe, probe_header

#: Sınıflandırma kapısı animasyonu reddetmez: amacı çok-kareli girdiyi decode
#: edip görsel olarak düzleştirmek değil, başlıktan tanıyıp video hattına
#: yönlendirmektir. Boyut/tür/kesiklik/güvenlik eşikleri aynen korunur.
CLASSIFY_GUARD: GuardConfig = replace(DEFAULT_GUARD, allow_animated=True)

# ── Sınıflar ────────────────────────────────────────────────────────────

SINIF_PHOTO: str = "photo"
SINIF_GRAPHIC: str = "graphic"
SINIF_TRANSPARENT: str = "transparent"
SINIF_ANIMATION: str = "animation"
SINIF_DOCUMENT: str = "document"
#: Kaynak kod uyumluluğu; dışarı verilen değer artık kanonik ``document``.
SINIF_TEXT: str = SINIF_DOCUMENT
#: Kalıcı eski kayıtları okuyan çağıranlar için giriş takma adı.
LEGACY_SINIF_TEXT: str = "text"

SINIFLAR: tuple[str, ...] = (
	SINIF_PHOTO,
	SINIF_GRAPHIC,
	SINIF_TRANSPARENT,
	SINIF_ANIMATION,
	SINIF_DOCUMENT,
)

#: 5×20 dengeli, deterministik korpus testinde belge sınıfı ölçülür.
DOCUMENT_OLCULDU: bool = True
#: Eski ithalat adı kanonik ölçüm bayrağına bağlıdır.
TEXT_OLCULDU: bool = DOCUMENT_OLCULDU

# ── Hat yönlendirme sözleşmesi ─────────────────────────────────────────

PIPELINE_IMAGE: str = "image"
PIPELINE_VIDEO: str = "video"
JOB_TYPE_IMAGE_RENDITION: str = "rendition"
JOB_TYPE_VIDEO_FROM_ANIMATION: str = "video_from_animation"
#: Faz 2 animasyon master sözleşmesi; bridge bu iki video türevini ve ayrıca
#: statik posteri üretir. Görsel encoder zincirine çok-kareli kaynak verilmez.
ANIMATION_VIDEO_TARGETS: tuple[tuple[str, str], ...] = (("MP4", "H264"), ("WEBM", "VP9"))

# ── Eşikler ─────────────────────────────────────────────────────────────
#
# Her eşiğin yanında onu belirleyen ÖLÇÜM var. Ölçüm kaynağı:
#   F = tradehub_core/tests/fixtures/media (34 görsel, sentetik)
#   C = canlı korpustan rastgele 48 görsel (seed 4242), elle etiketli
#
# Eşikler 48 örnekte 4 pozitif (grafik) üzerinde kalibre edildi. DÖRT POZİTİF
# İSTATİSTİKSEL OLARAK AZDIR: buradaki kesinlik/duyarlılık tahminlerinin güven
# aralığı geniştir. Korpus büyüdükçe yeniden kalibre edilmelidir.

#: Alfa "anlamlı" sayılması için saydam/yarı-saydam piksel oranı.
#: ÖLÇÜLDÜ (F): gerçek kesim görsellerinde 0,66–0,89; alfa kanalı olup tamamen
#: opak olan dosyalarda (C: 3 adet PNG/P) 0,000. Aradaki boşluk çok geniş,
#: eşik boşluğun tabanına yakın konuldu.
ALPHA_TRANSLUCENT_MIN: float = 0.02

#: Sert kenar oranı — komşu piksel farkı >8 olanların, sıfır olmayanlara oranı.
#: ÖLÇÜLDÜ (C): kayıpsız grafik #21 = 1,000; fotoğrafların tavanı 0,594.
GRAPHIC_HARD_EDGE_MIN: float = 0.55

#: 4 bitlik nicelenmiş benzersiz renk sayısı tavanı.
#: ÖLÇÜLDÜ (C): grafik #21 = 13; sert kenarlı ama fotoğraf olan #23 = 49.
GRAPHIC_QUANT_COLORS_MAX: int = 40

#: Doygun düz grafik yolu (kurumsal renk + tipografi).
#: ÖLÇÜLDÜ (C): grafik #13 (düz lacivert + sarı yazı) doygunluk ortalaması
#: 187,1; 44 fotoğrafın tavanı 103,3. Aradaki boşluk 80 puandan geniş.
GRAPHIC_SATURATION_MIN: float = 150.0

#: Doygun düz grafik yolunda ayrıca aranan tek-renk hakimiyeti.
#: ÖLÇÜLDÜ (C): #13 = 0,481.
GRAPHIC_TOP_COLOR_MIN: float = 0.30

#: Raster belge eşikleri — dengeli sentetik korpus + eşik sınır testleri.
DOCUMENT_BILEVEL_MIN: float = 0.90
DOCUMENT_EDGE_DENSITY_MIN: float = 0.12
DOCUMENT_QUANT_COLORS_MAX: int = 24
DOCUMENT_SATURATION_MAX: float = 32.0
#: Kaynak uyumluluğu: eski sabit adları aynı eşiklere işaret eder.
TEXT_BILEVEL_MIN: float = DOCUMENT_BILEVEL_MIN
TEXT_EDGE_DENSITY_MIN: float = DOCUMENT_EDGE_DENSITY_MIN
TEXT_QUANT_COLORS_MAX: int = DOCUMENT_QUANT_COLORS_MAX
TEXT_SATURATION_MAX: float = DOCUMENT_SATURATION_MAX

#: Sürekli ton kanıtı. 5×20 kabul korpusunda photo aralıkları sırasıyla
#: 18.992–19.047 ve 2.663–2.721; grafik/belge tavanı 6 ve 6'dır. Eşikler iki
#: kümenin geniş boşluğunda, fixture gürültüsüne toleranslı seçildi.
PHOTO_UNIQUE_COLORS_MIN: int = 256
PHOTO_QUANT_COLORS_MIN: int = 64

#: Kayıplı kodlanmış kaynaklarda düz alan kanıtı kodlayıcı gürültüsüyle
#: SİLİNİR. ÖLÇÜLDÜ (C): JPEG'e gömülü düz lacivert grafik #13'ün yumuşak
#: geçiş oranı 0,869 — yani fotoğraflardan ayırt edilemiyor. Bu yüzden sert
#: kenar yolu yalnız kayıpsız kaynaklarda çalışır.
LOSSY_SOURCE_FORMATS: frozenset[str] = frozenset({"JPEG", "MPO"})
LOSSLESS_SOURCE_FORMATS: frozenset[str] = frozenset({"PNG", "GIF", "BMP", "TIFF"})

#: Özellik çıkarımının çalıştığı ölçüler. Küçültme kodlayıcı gürültüsünü
#: ortalayarak siler; `BOX` (kutu ortalama) bilerek seçildi — LANCZOS keskinleştirme
#: yaparak yapay sert kenar üretir ve `hard_edge_ratio`'yu bozar.
THUMB_BOX: int = 160
#: Bu tavanın üstünde tam-frame RGBA/RGB/gri kopyaları kurulmaz. Kaynak
#: raster bir kez açılır; sınıflandırma ölçüleri küçük native karolardan
#: çıkarılır. 72 MP RGBA kabul sınırında bu ayrım OOM'u önler.
BOUNDED_SAMPLE_MIN_MEGAPIXELS: float = 20.0
#: Düzlük/kenar ölçümü küçültülmüş kopyada YAPILMAZ; yeniden örnekleme düz
#: alan kanıtını yok eder. Native çözünürlükte ızgara karoları kullanılır.
TILE_GRID: int = 4
TILE_SIZE: int = 96


# ── Biçim zincirleri ────────────────────────────────────────────────────


@dataclass(frozen=True)
class FormatStep:
	"""Zincirin tek adımı: biçim + kodlayıcı parametreleri."""

	fmt: str
	lossless: bool = False
	#: Sınıfa özgü kalite yükseltmesi (puan). Çağıran taban kaliteye ekler.
	quality_bump: int = 0
	#: Bu adımın çalışabilmesi için gereken kodlayıcı yeteneği.
	requires: tuple[str, ...] = ()
	#: Faz 2 hedefi. Kayıplı foto/ürün adımlarında q88; kayıpsız adımlarda
	#: ``"lossless"``. Eski konumsal kurucuları bozmamak için son alandır.
	quality_target: int | str = 88

	def to_dict(self) -> dict:
		return {
			"fmt": self.fmt,
			"lossless": self.lossless,
			"quality_bump": self.quality_bump,
			"quality_target": self.quality_target,
			"requires": list(self.requires),
		}


#: Her statik sınıfın teslim biçimi AVIF. Animasyon video hattına gider.
FORMAT_CHAINS: dict[str, tuple[FormatStep, ...]] = {
	SINIF_PHOTO: (FormatStep("AVIF"),),
	SINIF_GRAPHIC: (FormatStep("AVIF", quality_target=100),),
	SINIF_TRANSPARENT: (FormatStep("AVIF", requires=("alpha",)),),
	SINIF_ANIMATION: (),
	SINIF_DOCUMENT: (FormatStep("AVIF", quality_target=100),),
}

SAFE_HIGH_QUALITY_CHAIN: tuple[FormatStep, ...] = FORMAT_CHAINS[SINIF_GRAPHIC]
# Eski ithalat adı korunur; AVIF q100 için piksel-eş kayıpsızlık vaat edilmez.
SAFE_LOSSLESS_CHAIN = SAFE_HIGH_QUALITY_CHAIN


def encoder_capabilities() -> dict[str, bool]:
	"""Çalışma anında **gerçekten** kodlanabilen biçimler.

	Sabit liste tutulmuyor çünkü ortamlar ayrışıyor: ÖLÇÜLDÜ — yerelde Pillow
	11.3.0 `webp_anim` özelliğini tanıyor, konteynerdeki Pillow 12.2.0 aynı
	adı "Unknown feature" diye reddediyor. Bu yüzden özellik adı sorgulanmaz,
	**deneme kodlaması** yapılır: tek doğru cevabı kodlayıcının kendisi verir.
	"""
	yetenek: dict[str, bool] = {}
	try:
		from PIL import Image
	except Exception:
		return dict.fromkeys(("AVIF", "WEBP", "JPEG", "PNG", "GIF"), False)

	tek = Image.new("RGB", (4, 4), (128, 128, 128))
	alfali = Image.new("RGBA", (4, 4), (128, 128, 128, 128))
	for fmt in ("AVIF", "WEBP", "JPEG", "PNG", "GIF"):
		yetenek[fmt] = _deneme_kodla(tek, fmt)
		yetenek[f"{fmt}:alpha"] = _deneme_kodla(alfali, fmt) if yetenek[fmt] else False
	# Kayıpsızlık yalnız biçim adından varsayılmaz: WebP için gerçek deneme,
	# PNG/GIF için konteyner özelliği, JPEG için açıkça False.
	yetenek["WEBP:lossless"] = _deneme_kodla(tek, "WEBP", lossless=True, quality=100)
	yetenek["PNG:lossless"] = yetenek["PNG"]
	yetenek["GIF:lossless"] = yetenek["GIF"]
	yetenek["JPEG:lossless"] = False
	yetenek["AVIF:lossless"] = False
	yetenek["WEBP:animation"] = _deneme_kodla(tek, "WEBP", save_all=True, append_images=[tek])
	yetenek["GIF:animation"] = _deneme_kodla(tek, "GIF", save_all=True, append_images=[tek])
	yetenek["AVIF:animation"] = _deneme_kodla(tek, "AVIF", save_all=True, append_images=[tek])
	return yetenek


def _deneme_kodla(im, fmt: str, **kw) -> bool:
	"""Gerçekten kodlanıyor mu — istisna yutulur, cevap ikili."""
	try:
		buf = io.BytesIO()
		im.save(buf, fmt, **kw)
		return bool(buf.getvalue())
	except Exception:
		return False


def format_chain(sinif: str, capabilities: dict[str, bool] | None = None) -> tuple[FormatStep, ...]:
	"""Sınıfın zincirinden, bu ortamda **kodlanabilen** adımları döndür.

	Yetenek tablosu verilmezse çalışma anında ölçülür. Hiçbir adım
	desteklenmiyorsa boş demet döner — çağıran orijinali korumalıdır.
	"""
	if sinif == LEGACY_SINIF_TEXT:
		sinif = SINIF_DOCUMENT
	# Boş animation zinciri geçerli bir sonuçtur; `or` kullanmak onu yanlışlıkla
	# photo zincirine düşürürdü.
	zincir = FORMAT_CHAINS.get(sinif, FORMAT_CHAINS[SINIF_PHOTO])
	if not zincir:
		return ()
	return _supported_chain(zincir, capabilities)


def safe_lossless_chain(capabilities: dict[str, bool] | None = None) -> tuple[FormatStep, ...]:
	"""Eski API adı: belirsiz içerik için yüksek kaliteli AVIF zinciri."""
	return _supported_chain(SAFE_HIGH_QUALITY_CHAIN, capabilities)


def _supported_chain(
	zincir: tuple[FormatStep, ...],
	capabilities: dict[str, bool] | None,
) -> tuple[FormatStep, ...]:
	"""Bir zinciri çalışma anındaki gerçek encoder yetenekleriyle süz."""
	yet = capabilities if capabilities is not None else encoder_capabilities()
	uygun: list[FormatStep] = []
	for adim in zincir:
		if not yet.get(adim.fmt, False):
			continue
		if any(not yet.get(f"{adim.fmt}:{g}", False) for g in adim.requires):
			continue
		uygun.append(adim)
	return tuple(uygun)


# ── Özellikler ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Features:
	"""Sınıflandırmayı besleyen ölçümler. Hepsi TEK bir decode'dan çıkar."""

	frame_count: int = 1
	has_alpha_channel: bool = False
	alpha_translucent_ratio: float = 0.0
	unique_colors: int = 0
	quantized_colors: int = 0
	top_color_share: float = 0.0
	flat_ratio: float = 0.0
	soft_edge_ratio: float = 0.0
	hard_edge_ratio: float = 0.0
	edge_density: float = 0.0
	bilevel_ratio: float = 0.0
	saturation_mean: float = 0.0
	source_format: str = ""
	lossy_source: bool = False
	width: int = 0
	height: int = 0
	mode: str = ""

	def to_dict(self) -> dict:
		return {
			"frame_count": self.frame_count,
			"has_alpha_channel": self.has_alpha_channel,
			"alpha_translucent_ratio": round(self.alpha_translucent_ratio, 4),
			"unique_colors": self.unique_colors,
			"quantized_colors": self.quantized_colors,
			"top_color_share": round(self.top_color_share, 4),
			"flat_ratio": round(self.flat_ratio, 4),
			"soft_edge_ratio": round(self.soft_edge_ratio, 4),
			"hard_edge_ratio": round(self.hard_edge_ratio, 4),
			"edge_density": round(self.edge_density, 4),
			"bilevel_ratio": round(self.bilevel_ratio, 4),
			"saturation_mean": round(self.saturation_mean, 2),
			"source_format": self.source_format,
			"lossy_source": self.lossy_source,
			"width": self.width,
			"height": self.height,
			"mode": self.mode,
		}


def _tiles(im, grid: int = TILE_GRID, size: int = TILE_SIZE) -> list:
	"""Native çözünürlükte ızgara karoları.

	Merkez kırpma YETMEZ: stüdyo ürün fotoğraflarında merkez çoğu zaman düz
	beyaz fondur ve tek başına bakıldığında her fotoğraf "grafik" görünür
	(ÖLÇÜLDÜ, C: fotoğrafların düzlük oranı 0,05–0,98 aralığında saçılıyor).
	Izgara, konuyu ve fonu birlikte örnekler.
	"""
	W, H = im.size
	if W < size or H < size:
		return [im]
	karolar = []
	for gy in range(grid):
		for gx in range(grid):
			cx = int((gx + 0.5) * W / grid)
			cy = int((gy + 0.5) * H / grid)
			x = max(0, min(W - size, cx - size // 2))
			y = max(0, min(H - size, cy - size // 2))
			karolar.append(im.crop((x, y, x + size, y + size)))
	return karolar


def _gradient_profile(gri) -> tuple[float, float, float]:
	"""(düz, yumuşak, sert) oranları — yatay komşu farkından.

	`flat`  fark == 0  → tüm örneklere oranla
	`soft`  1..8       → sıfır olmayanlara oranla
	`hard`  >8         → sıfır olmayanlara oranla

	`soft`/`hard`'ın paydası bilerek "sıfır olmayanlar": düz fon oranı
	görselden görsele 20 kat değişiyor (ÖLÇÜLDÜ, C) ve payda olarak
	kullanılırsa ölçüt fon miktarını ölçer, içerik türünü değil.
	"""
	duz = yumusak = sert = 0
	for karo in _tiles(gri):
		px = list(karo.getdata())
		w, h = karo.width, karo.height
		for y in range(h):
			satir = px[y * w : (y + 1) * w]
			for i in range(w - 1):
				d = satir[i] - satir[i + 1]
				if d < 0:
					d = -d
				if d == 0:
					duz += 1
				elif d <= 8:
					yumusak += 1
				else:
					sert += 1
	sifirsiz = yumusak + sert
	toplam = duz + sifirsiz
	return (
		duz / toplam if toplam else 0.0,
		yumusak / sifirsiz if sifirsiz else 0.0,
		sert / sifirsiz if sifirsiz else 0.0,
	)


def _bounded_native_sample(im, *, alpha: bool):
	"""Büyük rasterdan tam-frame kopya kurmadan renk ve kenar örneği al.

	`crop()` kaynak decoder'ı bir kez açabilir, fakat dönen karolar küçüktür;
	RGBA→RGB/L dönüşümleri yalnız bu karolarda yapılır. Böylece 72 MP RGBA için
	kaynağın yanında ikinci/üçüncü 291 MB raster tamponu oluşmaz.
	"""
	from PIL import Image

	# `_tiles()` küçük bir eksen TILE_SIZE'dan darsa tüm görüntüyü döndürür;
	# bu küçük görseller için doğrudur, fakat 32×2.250.000 gibi 72 MP ince bir
	# rasterda yeniden tam-frame RGBA/RGB kopyasına yol açardı. Bounded yolda
	# her iki eksenin karo boyutu ayrı sınırlandırılır.
	W, H = im.size
	karo_w = min(TILE_SIZE, W)
	karo_h = min(TILE_SIZE, H)
	karolar = []
	for gy in range(TILE_GRID):
		for gx in range(TILE_GRID):
			cx = int((gx + 0.5) * W / TILE_GRID)
			cy = int((gy + 0.5) * H / TILE_GRID)
			x = max(0, min(W - karo_w, cx - karo_w // 2))
			y = max(0, min(H - karo_h, cy - karo_h // 2))
			karolar.append(im.crop((x, y, x + karo_w, y + karo_h)))
	hucre = max(1, THUMB_BOX // TILE_GRID)
	ornek = Image.new("RGB", (hucre * TILE_GRID, hucre * TILE_GRID), (255, 255, 255))
	duz = yumusak = sert = 0
	alfa_hist = [0] * 256 if alpha else None
	try:
		for i, karo in enumerate(karolar):
			gri = _to_gray_on_white(karo)
			try:
				px = list(gri.getdata())
				for y in range(gri.height):
					satir = px[y * gri.width : (y + 1) * gri.width]
					for x in range(len(satir) - 1):
						fark = abs(satir[x] - satir[x + 1])
						if fark == 0:
							duz += 1
						elif fark <= 8:
							yumusak += 1
						else:
							sert += 1
			finally:
				if gri is not karo:
					gri.close()

			if alfa_hist is not None:
				rgba = karo.convert("RGBA")
				kanal = rgba.getchannel("A")
				try:
					for deger, adet in enumerate(kanal.histogram()):
						alfa_hist[deger] += adet
				finally:
					kanal.close()
					rgba.close()

			rgb = _to_gray_on_white(karo, gri=False)
			try:
				rgb.thumbnail((hucre, hucre), Image.Resampling.BOX)
				x = (i % TILE_GRID) * hucre + (hucre - rgb.width) // 2
				y = (i // TILE_GRID) * hucre + (hucre - rgb.height) // 2
				ornek.paste(rgb, (x, y))
			finally:
				if rgb is not karo:
					rgb.close()
	finally:
		for karo in karolar:
			if karo is not im:
				karo.close()

	sifirsiz = yumusak + sert
	toplam = duz + sifirsiz
	gradient = (
		duz / toplam if toplam else 0.0,
		yumusak / sifirsiz if sifirsiz else 0.0,
		sert / sifirsiz if sifirsiz else 0.0,
	)
	alfa_oran = 0.0
	if alfa_hist is not None:
		t = sum(alfa_hist) or 1
		alfa_oran = sum(alfa_hist[:250]) / t
	return ornek, gradient, alfa_oran


def extract_features(
	src: bytes | bytearray | str | Path,
	*,
	probe: HeaderProbe | None = None,
) -> Features:
	"""Görselden sınıflandırma ölçümlerini çıkar. İstisna ATMAZ.

	Maliyet sınırı: JPEG'de `draft()` ile kodlayıcı zaten küçültülmüş çözer,
	diğer küçük biçimlerde `thumbnail` uygulanır. 20 MP üstünde renk, alfa ve
	kenar ölçümleri native küçük karolardan alınır; tam-frame renk kopyası yoktur.
	"""
	from PIL import Image, ImageFilter, ImageStat

	bounded_rgb = None
	bounded_alpha_oran = 0.0
	with _open(src) as im:
		kaynak_fmt = (im.format or "").upper()
		kare = int(getattr(im, "n_frames", 1) or 1)
		W, H = im.size
		mod = im.mode
		alfa_var = mod in ("RGBA", "LA", "PA") or (mod == "P" and "transparency" in im.info)
		kayipli = _kayipli_mi(kaynak_fmt, im)

		# Animation başlıktan kesindir. `skip_guard=True` çağrısında da pikselleri
		# açmadan video yönlendirme kararına yetecek ölçüyü döndür.
		if kare > 1:
			return Features(
				frame_count=kare,
				has_alpha_channel=alfa_var,
				source_format=kaynak_fmt or (probe.fmt if probe else ""),
				lossy_source=kayipli,
				width=W,
				height=H,
				mode=mod,
			)

		if (W * H) / 1_000_000.0 > BOUNDED_SAMPLE_MIN_MEGAPIXELS:
			bounded_rgb, (duz, yumusak, sert), bounded_alpha_oran = _bounded_native_sample(im, alpha=alfa_var)
		else:
			# — düzlük/kenar: NATIVE çözünürlük, yeniden örnekleme YOK —
			gri_native = _to_gray_on_white(im)
			try:
				duz, yumusak, sert = _gradient_profile(gri_native)
			finally:
				if gri_native is not im:
					gri_native.close()

	# — renk/doygunluk: küçültülmüş kopya —
	if bounded_rgb is not None:
		rgb = bounded_rgb
		alfa_oran = bounded_alpha_oran
	else:
		with _open(src) as kucuk:
			if kaynak_fmt == "JPEG":
				kucuk.draft("RGB", (THUMB_BOX * 2, THUMB_BOX * 2))
			alfa_oran = 0.0
			if alfa_var:
				rgba = kucuk.convert("RGBA")
				kanal = rgba.getchannel("A")
				try:
					kanal.thumbnail((THUMB_BOX, THUMB_BOX), Image.Resampling.BOX)
					h = kanal.histogram()
					t = sum(h) or 1
					alfa_oran = sum(h[:250]) / t
				finally:
					kanal.close()
					rgba.close()
			rgb = _to_gray_on_white(kucuk, gri=False)
			rgb.thumbnail((THUMB_BOX, THUMB_BOX), Image.Resampling.BOX)

	try:
		n = rgb.width * rgb.height or 1
		renkler = rgb.getcolors(maxcolors=n + 1) or []
		benzersiz = len(renkler)
		en_cok = max((c for c, _ in renkler), default=0) / n
		nicel = rgb.point(lambda v: (v // 16) * 16)
		try:
			nicel_sayi = len(nicel.getcolors(maxcolors=n + 1) or [])
		finally:
			nicel.close()

		gri = rgb.convert("L")
		try:
			gh = gri.histogram()
			gt = sum(gh) or 1
			bilevel = (sum(gh[:24]) + sum(gh[232:])) / gt
			kenar_im = gri.filter(ImageFilter.FIND_EDGES)
			try:
				kenar = kenar_im.histogram()
			finally:
				kenar_im.close()
		finally:
			gri.close()
		kt = sum(kenar) or 1
		kenar_yogunluk = sum(kenar[64:]) / kt
		hsv = rgb.convert("HSV")
		saturation = hsv.getchannel("S")
		try:
			doygunluk = ImageStat.Stat(saturation).mean[0]
		finally:
			saturation.close()
			hsv.close()

		return Features(
			frame_count=kare if kare > 0 else 1,
			has_alpha_channel=alfa_var,
			alpha_translucent_ratio=alfa_oran,
			unique_colors=benzersiz,
			quantized_colors=nicel_sayi,
			top_color_share=en_cok,
			flat_ratio=duz,
			soft_edge_ratio=yumusak,
			hard_edge_ratio=sert,
			edge_density=kenar_yogunluk,
			bilevel_ratio=bilevel,
			saturation_mean=doygunluk,
			source_format=kaynak_fmt or (probe.fmt if probe else ""),
			lossy_source=kayipli,
			width=W,
			height=H,
			mode=mod,
		)
	finally:
		rgb.close()


def _kayipli_mi(fmt: str, im) -> bool:
	"""Kaynak kayıplı kodlanmış mı — düz alan kanıtına güvenilir mi.

	WebP her iki modu da taşır; Pillow açtığı dosyanın kayıpsız olduğunu
	`info["lossless"]` ile bildirir (yoksa kayıplı varsayılır).
	"""
	if fmt in LOSSY_SOURCE_FORMATS:
		return True
	if fmt == "WEBP":
		return not bool(im.info.get("lossless", False))
	if fmt == "AVIF":
		return True
	return False


def _to_gray_on_white(im, gri: bool = True):
	"""Alfayı beyaz fonla düzleştir, sonra istenirse griye çevir.

	Alfa düzleştirilmeden gri ölçüm yapmak yanıltır: tamamen saydam bölgeler
	RGB kanalında rastgele değer taşıyabilir ve sahte "sert kenar" üretir.
	"""
	if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
		from PIL import Image

		rgba = im.convert("RGBA")
		fon = Image.new("RGB", rgba.size, (255, 255, 255))
		fon.paste(rgba, mask=rgba.getchannel("A"))
		im = fon
	return im.convert("L") if gri else im.convert("RGB")


def _open(src):
	"""Girdiyi Pillow ile aç — `with` ile kapatılabilir tek giriş noktası."""
	from PIL import Image

	if isinstance(src, bytes):
		return Image.open(io.BytesIO(src))
	if isinstance(src, bytearray):
		return Image.open(io.BytesIO(bytes(src)))
	return Image.open(str(src))


# ── Karar ───────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Classification:
	"""Sınıflandırma sonucu — sınıf + gerekçe + zincir."""

	klass: str = SINIF_PHOTO
	confidence: str = "low"  # "exact" | "high" | "low"
	reasons: tuple[str, ...] = ()
	features: Features | None = None
	chain: tuple[FormatStep, ...] = ()
	probe: HeaderProbe | None = None
	measured: bool = True
	error: str = ""
	#: Köprünün işi hangi motora teslim edeceği. Animation için ``video``.
	target_pipeline: str = PIPELINE_IMAGE
	#: Köprü/idempotency sözleşmesi. Animation için ``video_from_animation``.
	job_type: str = JOB_TYPE_IMAGE_RENDITION

	@property
	def ok(self) -> bool:
		return not self.error

	@property
	def route_to_video(self) -> bool:
		return self.target_pipeline == PIPELINE_VIDEO

	@property
	def safe_fallback(self) -> bool:
		"""Düşük güven nedeniyle kayıpsız güvenli zincir seçildi mi."""
		return self.ok and self.confidence == "low"

	@property
	def video_targets(self) -> tuple[tuple[str, str], ...]:
		return ANIMATION_VIDEO_TARGETS if self.route_to_video else ()

	@property
	def poster_required(self) -> bool:
		return self.route_to_video

	def to_dict(self) -> dict:
		return {
			"klass": self.klass,
			"confidence": self.confidence,
			"reasons": list(self.reasons),
			"features": self.features.to_dict() if self.features else None,
			"chain": [a.to_dict() for a in self.chain],
			"measured": self.measured,
			"error": self.error,
			"target_pipeline": self.target_pipeline,
			"job_type": self.job_type,
			"safe_fallback": self.safe_fallback,
			"video_targets": [{"fmt": fmt, "codec": codec} for fmt, codec in self.video_targets],
			"poster_required": self.poster_required,
		}


def routing_for_class(sinif: str) -> tuple[str, str]:
	"""Köprü sözleşmesi: sınıf → (hedef hat, iş tipi).

	Animasyonun görsel zinciri boş bırakılır ve kaynağın çok-kareli yapısı
	bozulmadan video hattına teslim edilir. Diğer dört sınıf görsel rendition
	işidir.
	"""
	if sinif == SINIF_ANIMATION:
		return PIPELINE_VIDEO, JOB_TYPE_VIDEO_FROM_ANIMATION
	return PIPELINE_IMAGE, JOB_TYPE_IMAGE_RENDITION


def classify_features(f: Features) -> tuple[str, str, tuple[str, ...]]:
	"""Ölçümlerden sınıf çıkar → (sınıf, güven, gerekçeler).

	Bu fonksiyon SAFTIR: dosya okumaz, Pillow çağırmaz. Testler eşik
	davranışını burada, sentetik `Features` üreterek doğrular.
	"""
	gerekce: list[str] = []

	# 1 — animasyon: başlıktan KESİN.
	if f.frame_count > 1:
		return SINIF_ANIMATION, "exact", (f"frame_count={f.frame_count}",)

	# 2 — saydamlık: alfa kanalından KESİN.
	if f.has_alpha_channel and f.alpha_translucent_ratio >= ALPHA_TRANSLUCENT_MIN:
		return (
			SINIF_TRANSPARENT,
			"exact",
			(f"alpha_translucent_ratio={f.alpha_translucent_ratio:.3f}>={ALPHA_TRANSLUCENT_MIN}",),
		)
	if f.has_alpha_channel:
		# Alfa kanalı VAR ama tamamı opak — kesim değil. Sınıf düşmez, not düşülür.
		gerekce.append("alpha_channel_present_but_opaque")

	# 3 — raster belge: iki-tonlu ve yoğun yazı/çizgi kenarı.
	if (
		f.bilevel_ratio >= DOCUMENT_BILEVEL_MIN
		and f.edge_density >= DOCUMENT_EDGE_DENSITY_MIN
		and f.quantized_colors <= DOCUMENT_QUANT_COLORS_MAX
		and f.saturation_mean <= DOCUMENT_SATURATION_MAX
	):
		return (
			SINIF_DOCUMENT,
			"high",
			(
				*gerekce,
				f"bilevel_ratio={f.bilevel_ratio:.3f}>={DOCUMENT_BILEVEL_MIN}",
				f"edge_density={f.edge_density:.3f}>={DOCUMENT_EDGE_DENSITY_MIN}",
				f"quantized_colors={f.quantized_colors}<={DOCUMENT_QUANT_COLORS_MAX}",
			),
		)

	# 4a — sert kenarlı sentetik grafik. Yalnız KAYIPSIZ kaynakta güvenilir:
	# JPEG'in halkalanması düz alanı sürekli tona çevirir (ÖLÇÜLDÜ, C: #13).
	if (
		not f.lossy_source
		and f.hard_edge_ratio >= GRAPHIC_HARD_EDGE_MIN
		and f.quantized_colors <= GRAPHIC_QUANT_COLORS_MAX
	):
		return (
			SINIF_GRAPHIC,
			"high",
			(
				*gerekce,
				"lossless_source",
				f"hard_edge_ratio={f.hard_edge_ratio:.3f}>={GRAPHIC_HARD_EDGE_MIN}",
				f"quantized_colors={f.quantized_colors}<={GRAPHIC_QUANT_COLORS_MAX}",
			),
		)

	# 4b — doygun düz grafik (kurumsal renk + tipografi). Kaynak kayıplı olsa
	# da çalışır: doygunluk kodlayıcıdan ETKİLENMEZ.
	if f.saturation_mean >= GRAPHIC_SATURATION_MIN and f.top_color_share >= GRAPHIC_TOP_COLOR_MIN:
		return (
			SINIF_GRAPHIC,
			"high",
			(
				*gerekce,
				f"saturation_mean={f.saturation_mean:.1f}>={GRAPHIC_SATURATION_MIN}",
				f"top_color_share={f.top_color_share:.3f}>={GRAPHIC_TOP_COLOR_MIN}",
			),
		)

	# 5 — sürekli ton: çok ve nicelenmiş renk, fotoğraf için güçlü kanıt.
	if f.unique_colors >= PHOTO_UNIQUE_COLORS_MIN and f.quantized_colors >= PHOTO_QUANT_COLORS_MIN:
		return (
			SINIF_PHOTO,
			"high",
			(
				*gerekce,
				f"unique_colors={f.unique_colors}>={PHOTO_UNIQUE_COLORS_MIN}",
				f"quantized_colors={f.quantized_colors}>={PHOTO_QUANT_COLORS_MIN}",
			),
		)

	# 6 — sınıf etiketi varsayılan photo kalır; düşük güvenli çıktı zinciri
	# aşağıda kayıpsız tarafa çevrilir (Faz 6 güvenli belirsizlik kuralı).
	return SINIF_PHOTO, "low", (*gerekce, "default_photo")


def classify(
	src: bytes | bytearray | str | Path,
	*,
	filename: str = "",
	guard: GuardConfig = CLASSIFY_GUARD,
	skip_guard: bool = False,
	capabilities: dict[str, bool] | None = None,
) -> Classification:
	"""Görseli sınıflandır ve biçim zincirini seç. İstisna ATMAZ.

	Kapı (T-060) varsayılan olarak ÖNCE çalışır: bomba/kesik/tehlikeli dosya
	sınıflandırma için bile decode edilmez.
	"""
	p: HeaderProbe | None = None
	if not skip_guard:
		p = probe_header(src, filename=filename, config=guard)
		if not p.ok:
			return Classification(
				klass=SINIF_PHOTO,
				confidence="low",
				reasons=("gate_reject",),
				probe=p,
				measured=False,
				error=p.codes[0],
			)
		if p.animated or p.frame_count > 1:
			hedef_hat, is_tipi = routing_for_class(SINIF_ANIMATION)
			return Classification(
				klass=SINIF_ANIMATION,
				confidence="exact",
				reasons=(f"frame_count={p.frame_count}", "header_only_route"),
				probe=p,
				measured=True,
				target_pipeline=hedef_hat,
				job_type=is_tipi,
			)

	try:
		f = extract_features(src, probe=p)
	except Exception as exc:  # noqa: BLE001 — sınıflandırıcı çağıranı patlatmaz
		return Classification(
			klass=SINIF_PHOTO,
			confidence="low",
			reasons=("feature_extraction_failed",),
			probe=p,
			measured=False,
			error=f"error:{type(exc).__name__}: {exc}",
		)

	sinif, guven, gerekce = classify_features(f)
	hedef_hat, is_tipi = routing_for_class(sinif)
	zincir = safe_lossless_chain(capabilities) if guven == "low" else format_chain(sinif, capabilities)
	return Classification(
		klass=sinif,
		confidence=guven,
		reasons=gerekce,
		features=f,
		chain=zincir,
		probe=p,
		measured=(sinif != SINIF_DOCUMENT or DOCUMENT_OLCULDU),
		target_pipeline=hedef_hat,
		job_type=is_tipi,
	)
