"""ImageEngine sözleşmesi — künye okuma, master üretimi, türev merdiveni.

Bugünkü uygulama `tradehub_core/media/pipeline.py` (saf Pillow, `import frappe`
YOK). Bu sözleşme onun yerine geçmez; **etrafını sarar ve genişletir**:

  var olan              sözleşmedeki karşılığı
  ────────────────────  ─────────────────────────────────────────────
  `engine.probe()`      `ImageEngine.probe()` (mode/alfa/DPI/ICC eklendi)
  `engine.optimize()`   `ImageEngine.make_master()` (biçim koruma yerine
                        slot politikasının `master.format`'ı)
  `engine.to_webp()`    `make_master()`'ın `format="webp"` hâli
  (yok)                 `make_rendition()` — türev merdiveni (FR-035)
  (yok)                 `quality_score()` — SSIM kapısı (politikadaki
                        `quality.target_ssim_per_class`)

T-007 benchmark kararı (docs/reports/05-kutuphane-benchmark.md): **Pillow'da
kalınıyor.** pyvips kutudan çıktığı hâliyle 0,94× yavaş ve CMYK'de rengi
bozuyor; yalnız >20MP dosyalarda (korpusun %3,7'si) kazanıyor. Sözleşme
kütüphane adı geçirmez — ileride >20MP dalını pyvips'e vermek isteyen bir
uygulama aynı `Protocol`'ü karşılayarak bunu yapabilir.

İDEMPOTENSİ
-----------
`make_master()` **deterministik ve sabit noktalıdır**: aynı (içerik, spec)
her zaman aynı baytları verir; bir master'ı kendi spec'iyle yeniden işlemek
BAYT DÜZEYİNDE aynı sonucu döndürür. Bu, `gates.check_before`'daki
`already_optimized` kapısının sözleşme karşılığıdır (nesil kaybı yok) ve
kuyruk işinin iki kez koşmasını zararsız kılar.

`make_rendition()` aynı garantiyi taşır. `probe()` yan etkisizdir.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Protocol, Sequence, Tuple, runtime_checkable

# `master.fit` değerleri — slot politikası şemasındaki kümeyle aynı.
FIT_CONTAIN: str = "contain"
FIT_PAD: str = "pad"
FIT_COVER: str = "cover"
FITS: Tuple[str, ...] = (FIT_CONTAIN, FIT_PAD, FIT_COVER)

# `quality.metric` — bugün tek metrik var; sabit olarak taşınıyor ki
# politikadaki dizge ile kod arasındaki bağ tek yerden kurulsun.
METRIC_SSIM: str = "ssim"

# İçerik sınıfları — `quality.target_ssim_per_class` anahtarları.
CLASS_PHOTO: str = "photo"
CLASS_GRAPHIC: str = "graphic"
CLASS_TEXT: str = "text"
CLASS_FINE_DETAIL: str = "fine_detail"
CONTENT_CLASSES: Tuple[str, ...] = (CLASS_PHOTO, CLASS_GRAPHIC, CLASS_TEXT, CLASS_FINE_DETAIL)

# Alfa taşıyabilen Pillow mod'ları. Canlı ölçüm: 597 dosya RGBA (docs/reports/
# 02-medya-istatistigi.md). FR-146: alfalı master alfasız biçime düşürülemez.
ALPHA_MODES: Tuple[str, ...] = ("RGBA", "LA", "PA")


@dataclass(frozen=True)
class ImageProbe:
	"""Görselin künyesi — dosyanın TAMAMI açılmadan okunabilen bilgiler.

	`engine.Probe`'un üst kümesi. Eklenen alanların hepsinin canlı ölçümde
	karşılığı var: `mode` (CMYK 38, P 74, L 7 dosya → FR-145), `has_alpha`
	(597 dosya → FR-146), `dpi` (FR-029/FR-030), `icc_profile` (renk
	yönetimi), `megapixels` (179 dosya >20MP → FR-011/FR-143).
	"""

	fmt: str
	width: int
	height: int
	mode: str = ""
	animated: bool = False
	readable: bool = True
	has_alpha: bool = False
	icc_profile: bool = False
	dpi: Optional[Tuple[float, float]] = None
	exif_orientation: int = 1
	frame_count: int = 1

	@property
	def long_edge(self) -> int:
		return max(self.width, self.height)

	@property
	def short_edge(self) -> int:
		return min(self.width, self.height)

	@property
	def megapixels(self) -> float:
		return (self.width * self.height) / 1_000_000.0

	@property
	def area(self) -> int:
		return self.width * self.height

	@property
	def aspect_ratio(self) -> float:
		"""Genişlik / yükseklik. Yükseklik 0 ise 0.0 — bölme hatası yerine
		ölçülemez değer döner, çağıran `readable`'a bakar."""
		return (self.width / self.height) if self.height else 0.0


@dataclass(frozen=True)
class MasterSpec:
	"""Master üretim parametreleri — slot politikasının `master` bloğu.

	Alan adları `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` içindeki
	`master` özellikleriyle BİREBİR aynı; politika JSON'undan doğrudan
	kurulabilsin diye. `allow_upscale` varsayılan `False` (FR-028: sistem
	asla upscale yapmaz) ve `True` verilmesi sözleşme ihlali sayılır.
	"""

	max_long_edge: int
	format: str
	min_long_edge: int = 0
	max_megapixels: float = 0.0
	dpi_out: int = 72
	colorspace: str = "srgb"
	orientation: str = "apply_exif"
	fit: str = FIT_CONTAIN
	target_ratio: str = ""
	pad_color: str = ""
	allow_crop: bool = False
	allow_upscale: bool = False
	quality: int = 0
	lossless: bool = False
	strip_metadata: Dict[str, bool] = field(default_factory=dict)

	def __post_init__(self) -> None:
		if self.allow_upscale:
			raise ValueError("FR-028: master üretiminde upscale yasak")
		if self.fit not in FITS:
			raise ValueError(f"Bilinmeyen fit: {self.fit!r}")
		if self.min_long_edge and self.min_long_edge > self.max_long_edge:
			raise ValueError("min_long_edge > max_long_edge")


@dataclass(frozen=True)
class RenditionSpec:
	"""Tek bir türev profili — politikanın `profiles[]` girdisi.

	`derived_from` politikada ZORUNLU (FR-034: her profil somut bir CSS
	kutusu × DPR hesabından türetilir). Sözleşme onu taşır ama doğrulamaz;
	doğrulama PolicyEngine'in işidir.
	"""

	name: str
	width: int
	format: str
	quality: int = 0
	fit: str = FIT_CONTAIN
	target_ratio: str = ""
	pad_color: str = ""
	lossless: bool = False
	derived_from: str = ""

	def __post_init__(self) -> None:
		if self.width <= 0:
			raise ValueError("RenditionSpec.width pozitif olmalı")
		if self.fit not in FITS:
			raise ValueError(f"Bilinmeyen fit: {self.fit!r}")


@dataclass(frozen=True)
class EncodedImage:
	"""Üretilmiş görsel — baytlar + ölçülen künye.

	`notes` insan-okunur gerekçe listesi taşır ("alfa korundu", "CMYK→sRGB").
	Kullanıcıya gösterilen optimizasyon özeti (FR-064) bundan üretilir.
	"""

	content: bytes
	fmt: str
	width: int
	height: int
	quality: int = 0
	dpi: int = 72
	notes: Tuple[str, ...] = ()

	@property
	def size_bytes(self) -> int:
		return len(self.content)


@dataclass(frozen=True)
class QualityReport:
	"""Kalite ölçüm sonucu.

	`measured=False` ölçüm YAPILAMADIĞINI söyler (metrik kütüphanesi yok,
	boyutlar uyuşmuyor). O durumda `score` anlamsızdır ve çağıran sayı
	uydurmamalıdır (FR-066).
	"""

	metric: str
	score: float
	threshold: float
	measured: bool = True

	@property
	def passed(self) -> bool:
		"""Ölçülemeyen kalite kapıyı DÜŞÜRMEZ — fail-open, ama `measured`
		alanı raporda görünür kalır."""
		return True if not self.measured else self.score >= self.threshold


@runtime_checkable
class ImageEngine(Protocol):
	"""Görsel işleme motoru.

	Hiçbir metot depoya yazmaz, `File` kaydı oluşturmaz, `frappe`'ye dokunmaz.
	Girdi bayt, çıktı bayt. Bu ayrım `engine.py`'nin bugünkü bilinçli
	kısıtıdır ve sözleşmede korunur: site kurmadan test edilebilirlik.
	"""

	def supported_formats(self) -> Tuple[str, ...]:
		"""Motorun okuyup yazabildiği biçimler (büyük harf: `JPEG`, `WEBP`...)."""
		...

	def probe(self, content: bytes, *, max_megapixels: float = 0.0) -> ImageProbe:
		"""Künyeyi oku — görselin TAMAMINI açmadan.

		`max_megapixels > 0` verilirse ve başlıktaki piksel sayısı bu tavanı
		aşarsa `OversizedImage` atılır ve **piksel verisi hiç açılmaz**
		(FR-011 decompression bomb koruması).

		Açılamayan içerik için hata atmaz: `readable=False` taşıyan bir
		`ImageProbe` döner — `engine.probe()`'un bugünkü davranışı.
		Yan etkisizdir.
		"""
		...

	def make_master(self, content: bytes, spec: MasterSpec) -> EncodedImage:
		"""Politikaya uygun master üret.

		Garantiler:
		  - Yalnız küçültme (FR-028). Kaynak zaten `max_long_edge` altındaysa
		    ölçü DEĞİŞMEZ; yalnız biçim/renk uzayı/metadata normalleştirilir.
		  - DPI metadata'sı `spec.dpi_out` olarak YAZILIR ama piksel sayısına
		    ASLA uygulanmaz (FR-029/FR-030).
		  - `spec.colorspace` sRGB ise CMYK/L/P girdiler sRGB'ye çevrilir
		    (FR-145); alfa taşıyan girdi alfasız biçime düşürülmez (FR-146).
		  - `spec.strip_metadata` içindeki `gps` her zaman uygulanır (FR-039).

		Determinist ve sabit noktalı: `make_master(make_master(x, s).content, s)`
		bayt düzeyinde `make_master(x, s)` ile aynıdır.

		Hatalar: `DecodeError`, `UnsupportedFormat`, `OversizedImage`,
		`EncodeError`. Hata atıldığında hiçbir çıktı üretilmemiş sayılır —
		yarım bayt dizisi dönmez (NFR-041).
		"""
		...

	def make_rendition(self, master: bytes, spec: RenditionSpec) -> EncodedImage:
		"""Master'dan tek bir türev üret.

		Kaynak master'dır, orijinal DEĞİL — merdivenin her basamağı aynı
		normalleştirilmiş kaynaktan doğar, yoksa profiller arasında renk ve
		keskinlik farkı oluşur.

		`spec.width` master'ın genişliğinden büyükse **upscale yapılmaz**:
		üretilebilen en büyük ölçü döndürülür ve `notes` içine `under_spec`
		düşülür (FR-033 — dosya reddedilmez, eksik profil işaretlenir).

		Determinist ve idempotent (aynı master + aynı spec → aynı baytlar).
		"""
		...

	def make_ladder(self, master: bytes, specs: Sequence[RenditionSpec]) -> Dict[str, EncodedImage]:
		"""Türev merdiveninin tamamını üret — anahtar `RenditionSpec.name`.

		Tek tek `make_rendition` çağırmakla aynı sonucu verir; ayrı metot
		olmasının nedeni uygulamanın master'ı bir kez açıp bellekte tutabilmesi
		(4.812 görsellik migration'da tek tek açmak ölçülebilir maliyet).

		Kısmi başarı YOKTUR: bir profil üretilemezse hata atılır ve hiçbiri
		yazılmamış sayılır. Kısmi merdiven, `srcset` içinde 404 veren bir URL
		demektir.
		"""
		...

	def quality_score(
		self, reference: bytes, candidate: bytes, *, metric: str = METRIC_SSIM
	) -> QualityReport:
		"""İki görsel arasındaki kalite benzerliği.

		Metrik ölçülemiyorsa (kütüphane yok, boyutlar uyuşmuyor) hata ATMAZ:
		`measured=False` taşıyan rapor döner. Kalite kapısı ölçülemediğinde
		dosyayı reddetmek, ölçüm altyapısı eksikliğini kullanıcı hatasına
		çevirirdi (FR-047 ile aynı ilke).

		`threshold` alanını çağıran politikadan doldurur; motor eşiği bilmez.
		"""
		...


__all__ = [
	"FIT_CONTAIN",
	"FIT_PAD",
	"FIT_COVER",
	"FITS",
	"METRIC_SSIM",
	"CONTENT_CLASSES",
	"ALPHA_MODES",
	"ImageProbe",
	"MasterSpec",
	"RenditionSpec",
	"EncodedImage",
	"QualityReport",
	"ImageEngine",
]
