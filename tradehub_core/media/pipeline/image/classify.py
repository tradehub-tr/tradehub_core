"""T-062 — İçerik sınıflandırma: 5 sınıf → biçim zinciri.

Bu modül ne yapar
-----------------
Görselin **içeriğini** beş sınıftan birine koyar ve o sınıf için denenecek
kodlayıcı **zincirini** verir. Sınıf, `normalize.py` çıktısı olan master'ın
türevlere hangi biçimle kodlanacağını belirler.

    animation    çok kareli
    transparent  anlamlı alfa taşıyor (kesim/logo)
    text         metin/belge baskın (keskin harf kenarları)
    graphic      düz alanlı sentetik görsel (logo, illüstrasyon)
    photo        sürekli tonlu fotoğraf  ← VARSAYILAN

Sıra ANLAMLIDIR ve yukarıdan aşağıya "kesin ölçülebilirden tahminiye" gider:
`animation` başlıktan **kesin** okunur, `transparent` alfa kanalından **kesin**
ölçülür; `graphic`/`text` ise sezgiseldir ve bilerek **yüksek kesinlik / düşük
duyarlılık** ayarındadır. Kanıt yetmiyorsa sınıf `photo` olur.

Neden varsayılan `photo` — ÖLÇÜLDÜ
----------------------------------
Yanlış sınıflandırmanın iki yönü aynı maliyette DEĞİL. Canlı korpustan çekilen
48 görselin 1280px türevi iki kez kodlandı (yerel, Pillow 11.3.0, WebP method=4):

    44 fotoğraf:  kayıplı q80  1.752 KB  ·  kayıpsız  13.770 KB  → **7,86x**
     4 grafik:    kayıplı q80     73 KB  ·  kayıpsız     469 KB  → **6,40x**

Yani bir fotoğrafı "grafik" sanıp kayıpsız kodlamak dosyayı 7,86 kat büyütür;
bir grafiği "fotoğraf" sanıp kayıplı kodlamak ise yalnız düz alanlarda hafif
halkalanma bırakır. Maliyet asimetrik olduğu için kapı asimetrik kuruldu:
**`graphic` demek için güçlü kanıt aranır, `photo` demek için kanıt aranmaz.**

Aynı ölçüm ikinci bir sonuç daha verdi: kayıpsız kodlama bu korpusta grafikler
için bile 6,4 kat pahalı. Bu yüzden `graphic`/`text` zincirleri kayıpsıza
DALLANMAZ; aynı kayıplı zincirde **kalite yükseltmesi** (`quality_bump`)
uygular. Kayıpsız yalnız alfa/animasyon zincirlerinin son çaresidir.

Neden bazı ölçütler ölçülmedi — DÜRÜST SINIR
--------------------------------------------
`tradehub_core/tests/fixtures/media/` içindeki 34 görsel fixture'ın `class` alanı bir
**içerik sınıfı değil, fixture ailesi** etiketidir: `ok_product_1x1_2400.jpg`
("photo") ile `geom_strip_400x4000.png` ("graphic") piksel istatistiği olarak
AYNI şeydir — ikisi de rastgele gürültü. Bu korpus üzerinde içerik sınıflandırma
doğruluğu ÖLÇÜLEMEZ. Ölçüm bu yüzden canlı korpustan çekilen ve elle etiketlenen
48 görsel üzerinde yapıldı; sonuçlar `tests/test_image_classify.py` içinde
sabitlenmiştir.

`text` sınıfı için ne fixture korpusunda ne canlı örneklemde tek bir örnek
çıktı: eşikleri literatürdeki bilinen ayraçlardan kuruldu ve **ÖLÇÜLMEDİ**.
`TEXT_OLCULDU = False` bunu kodda da beyan eder.

`import frappe` YOKTUR.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from tradehub_core.media.pipeline.image.probe import DEFAULT_GUARD, GuardConfig, HeaderProbe, probe_header

# ── Sınıflar ────────────────────────────────────────────────────────────

SINIF_PHOTO: str = "photo"
SINIF_GRAPHIC: str = "graphic"
SINIF_TRANSPARENT: str = "transparent"
SINIF_ANIMATION: str = "animation"
SINIF_TEXT: str = "text"

SINIFLAR: tuple[str, ...] = (
	SINIF_PHOTO,
	SINIF_GRAPHIC,
	SINIF_TRANSPARENT,
	SINIF_ANIMATION,
	SINIF_TEXT,
)

#: `text` sınıfının eşikleri hiçbir korpusta doğrulanamadı (örnek yok).
#: Bu bayrak rapor üreten katmanın "ölçülmedi" demesini sağlar (kural 4).
TEXT_OLCULDU: bool = False

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

#: Metin sınıfı eşikleri — **ÖLÇÜLMEDİ**, örnek bulunamadı.
TEXT_BILEVEL_MIN: float = 0.90
TEXT_EDGE_DENSITY_MIN: float = 0.12
TEXT_QUANT_COLORS_MAX: int = 24
TEXT_SATURATION_MAX: float = 32.0

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

	def to_dict(self) -> dict:
		return {
			"fmt": self.fmt,
			"lossless": self.lossless,
			"quality_bump": self.quality_bump,
			"requires": list(self.requires),
		}


#: Sınıf → zincir. Sıra tercih sırasıdır; çağıran ilk **desteklenen** adımı alır.
#:
#: Zincirlerin hiçbiri `graphic`/`text` için kayıpsıza dallanmaz — yukarıdaki
#: 6,40x ölçümü bunu haksız çıkardı. Bunun yerine `quality_bump` uygulanır:
#: düz alan ve harf kenarlarındaki halkalanma kaliteyi yükselterek çözülür,
#: dosyayı 6 kat büyüterek değil.
FORMAT_CHAINS: dict[str, tuple[FormatStep, ...]] = {
	SINIF_PHOTO: (
		FormatStep("AVIF"),
		FormatStep("WEBP"),
		FormatStep("JPEG"),
	),
	SINIF_GRAPHIC: (
		FormatStep("AVIF", quality_bump=8),
		FormatStep("WEBP", quality_bump=8),
		# JPEG DEĞİL: keskin kenarlarda 4:2:0 renk altörneklemesi görünür
		# renk kaçağı bırakır. Grafiğin son çaresi kayıpsız PNG'dir.
		FormatStep("PNG", lossless=True),
	),
	SINIF_TRANSPARENT: (
		FormatStep("AVIF", requires=("alpha",)),
		FormatStep("WEBP", requires=("alpha",)),
		FormatStep("PNG", lossless=True, requires=("alpha",)),
	),
	SINIF_ANIMATION: (
		FormatStep("WEBP", requires=("animation",)),
		FormatStep("GIF", lossless=True, requires=("animation",)),
	),
	SINIF_TEXT: (
		FormatStep("AVIF", quality_bump=10),
		FormatStep("WEBP", quality_bump=10),
		FormatStep("PNG", lossless=True),
	),
}


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
	zincir = FORMAT_CHAINS.get(sinif) or FORMAT_CHAINS[SINIF_PHOTO]
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


def extract_features(
	src: bytes | bytearray | str | Path,
	*,
	probe: HeaderProbe | None = None,
) -> Features:
	"""Görselden sınıflandırma ölçümlerini çıkar. İstisna ATMAZ.

	Maliyet sınırı: JPEG'de `draft()` ile kodlayıcı zaten küçültülmüş çözer,
	diğer biçimlerde `thumbnail` uygulanır. Düzlük/kenar ölçümü ise **ayrı**
	ve native çözünürlükte yapılır (bkz. `_tiles`).
	"""
	from PIL import Image, ImageFilter, ImageStat

	# Görsel İKİ KEZ açılır ve ikisi de kapatılır. İki açılışın sebebi:
	# düzlük ölçümü native çözünürlük ister, renk ölçümü ise `draft()` ile
	# küçültülmüş çözüm ister — `draft()` geri alınamaz, aynı nesnede ikisi
	# birden yapılamaz. Kapatma `with` ile garanti: uzun ömürlü işçi
	# süreçte kapatılmayan her açılış bir dosya tanıtıcısı sızdırır.
	with _open(src) as im:
		kaynak_fmt = (im.format or "").upper()
		kare = int(getattr(im, "n_frames", 1) or 1)
		W, H = im.size
		mod = im.mode
		alfa_var = mod in ("RGBA", "LA", "PA") or (mod == "P" and "transparency" in im.info)
		kayipli = _kayipli_mi(kaynak_fmt, im)

		# — düzlük/kenar: NATIVE çözünürlük, yeniden örnekleme YOK —
		duz, yumusak, sert = _gradient_profile(_to_gray_on_white(im))

	# — renk/doygunluk: küçültülmüş kopya —
	with _open(src) as kucuk:
		if kaynak_fmt == "JPEG":
			kucuk.draft("RGB", (THUMB_BOX * 2, THUMB_BOX * 2))
		alfa_oran = 0.0
		if alfa_var:
			kanal = kucuk.convert("RGBA").getchannel("A")
			kanal.thumbnail((THUMB_BOX, THUMB_BOX), Image.BOX)
			h = kanal.histogram()
			t = sum(h) or 1
			alfa_oran = sum(h[:250]) / t
		rgb = _to_gray_on_white(kucuk, gri=False)
		rgb.thumbnail((THUMB_BOX, THUMB_BOX), Image.BOX)

	n = rgb.width * rgb.height or 1
	renkler = rgb.getcolors(maxcolors=n + 1) or []
	benzersiz = len(renkler)
	en_cok = max((c for c, _ in renkler), default=0) / n
	nicel = rgb.point(lambda v: (v // 16) * 16)
	nicel_sayi = len(nicel.getcolors(maxcolors=n + 1) or [])

	gri = rgb.convert("L")
	gh = gri.histogram()
	gt = sum(gh) or 1
	bilevel = (sum(gh[:24]) + sum(gh[232:])) / gt
	kenar = gri.filter(ImageFilter.FIND_EDGES).histogram()
	kt = sum(kenar) or 1
	kenar_yogunluk = sum(kenar[64:]) / kt
	doygunluk = ImageStat.Stat(rgb.convert("HSV").getchannel("S")).mean[0]

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

	if isinstance(src, (bytes, bytearray)):
		return Image.open(io.BytesIO(bytes(src)))
	return Image.open(str(src))


def _as_bytes(src) -> bytes:
	if isinstance(src, (bytes, bytearray)):
		return bytes(src)
	return Path(src).read_bytes()


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

	@property
	def ok(self) -> bool:
		return not self.error

	def to_dict(self) -> dict:
		return {
			"klass": self.klass,
			"confidence": self.confidence,
			"reasons": list(self.reasons),
			"features": self.features.to_dict() if self.features else None,
			"chain": [a.to_dict() for a in self.chain],
			"measured": self.measured,
			"error": self.error,
		}


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

	# 3 — metin/belge. ÖLÇÜLMEDİ: korpusta örnek yok, eşikler doğrulanmadı.
	if (
		f.bilevel_ratio >= TEXT_BILEVEL_MIN
		and f.edge_density >= TEXT_EDGE_DENSITY_MIN
		and f.quantized_colors <= TEXT_QUANT_COLORS_MAX
		and f.saturation_mean <= TEXT_SATURATION_MAX
	):
		return (
			SINIF_TEXT,
			"low",
			(
				*gerekce,
				f"bilevel_ratio={f.bilevel_ratio:.3f}>={TEXT_BILEVEL_MIN}",
				f"edge_density={f.edge_density:.3f}>={TEXT_EDGE_DENSITY_MIN}",
				"UNVALIDATED_THRESHOLDS",
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

	# 5 — varsayılan. Kanıt yoksa fotoğraf: yanılmanın ucuz yönü budur (7,86x).
	return SINIF_PHOTO, "low", (*gerekce, "default_photo")


def classify(
	src: bytes | bytearray | str | Path,
	*,
	filename: str = "",
	guard: GuardConfig = DEFAULT_GUARD,
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
	return Classification(
		klass=sinif,
		confidence=guven,
		reasons=gerekce,
		features=f,
		chain=format_chain(sinif, capabilities),
		probe=p,
		measured=(sinif != SINIF_TEXT or TEXT_OLCULDU),
	)
