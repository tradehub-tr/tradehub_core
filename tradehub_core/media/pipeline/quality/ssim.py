"""T-013 — SSIM hesabı ve hedef SSIM'e ikili arama ile kalite seçimi.

**Çözdüğü problem.** Bugün kalite SABİT: `tradehub_core/media/presets.py` üç preset
için `quality` 90/88/82 veriyor, `tradehub_core/media/pipeline.py::to_webp` ise
imzasında `quality: int = 80` taşıyor. Sabit kalite iki yönde de yanılır:

  * Düşük entropili görselde (düz zeminli ürün fotoğrafı, logo benzeri grafik)
    q88 gereğinden fazla bayt harcar — SSIM zaten q60'ta hedefin üstündedir.
  * Yüksek entropili görselde (doku, kumaş, kalabalık sahne) q88 bile hedefin
    ALTINDA kalabilir; sabit kalite bunu göremez çünkü çıktıyı hiç ölçmez.

Bu modül çıktıyı ÖLÇER: aday encode ile referans piksellerin SSIM'ini hesaplar ve
politikanın hedef SSIM'ine ulaşan **en düşük** kaliteyi ikili aramayla bulur.
Encode bütçesi varsayılan **4** denemedir (`DEFAULT_MAX_ENCODES`).

**Neden yeniden yazılmadı.** Encode yolu `tradehub_core/media/pipeline.py::optimize`
ile aynıdır — bu modül onu SARAR (`engine.optimize(content, max_dim, quality)`),
kendi encoder'ını kurmaz. Buradaki tek ek, encode ÖNCESİ referans pikselleri
üretmektir (`master_reference`): `exif_transpose` + `thumbnail`, yani `optimize`'ın
kaydetmeden hemen önceki hâli. `tests/test_quality_ssim.py::test_referans_geometrisi_
engine_ile_ayni` bu iki yolun geometrisinin ayrışmadığını kilitler.

**SSIM tanımı.** Wang et al. 2004, `scikit-image`'in varsayılanıyla aynı varyant:
7×7 **düzgün (uniform)** pencere, `data_range=255`, K1=0.01, K2=0.03, kovaryansta
yansız (unbiased) düzeltme `NP/(NP-1)`, kenarda taşan pencereler atılır ve kalan
SSIM haritasının ortalaması alınır. Gauss ağırlıklı varyant DEĞİLDİR; sayılar
`structural_similarity(..., gaussian_weights=False)` ile karşılaştırılabilir.

**İki arka uç.** numpy varsa `numpy` (üretim yolu), yoksa saf Python integral
görüntü (`pure`). İkisi de AYNI formülü kullanır; ölçülen uyum ve saf Python'un
maliyeti `docs/reports/11-faz1-arge.md` §T-013'te tablodadır. Saf Python yolu
`PURE_MAX_PIXELS` üstünde görseli küçültür — bu bir YAKLAŞIKLIKTIR ve sonuçta
`downscaled=True` ile işaretlenir; üretimde numpy zorunludur.

**Ölçek uyarısı.** SSIM ölçeğe duyarlıdır: aynı encode, küçültülmüş kopyada daha
yüksek SSIM verir (artefakt yeniden örneklemede silinir). Bu yüzden karşılaştırma
VARSAYILAN OLARAK master çözünürlükte yapılır; `max_pixels` yalnız bilinçli hız
takası için verilmelidir.
"""

from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

# --- Sabitler ---------------------------------------------------------------

WIN_SIZE: int = 7
"""Düzgün pencere kenarı. scikit-image varsayılanı (`win_size=7`) ile aynı."""

DATA_RANGE: float = 255.0
K1: float = 0.01
K2: float = 0.03

C1: float = (K1 * DATA_RANGE) ** 2
C2: float = (K2 * DATA_RANGE) ** 2

DEFAULT_QUALITY_RANGE: tuple[int, int] = (70, 95)
"""Aramanın tarandığı kapalı aralık — ÖLÇÜMLE seçildi, tahminle değil.

Üst sınır 95: q>95'te bayt patlar, SSIM kazancı ölçülemez. Alt sınır 70 ise 4
encode bütçesinin doğrudan sonucudur. 10 fixture × 56 kalite tam taramasıyla
(`scripts/measure_ssim_quality.py`) ölçülen: aralık (40,95) iken 4 adımlık ikili
aramanın gezebildiği kaliteler {67, 81, 88, 92}'dir; 92 üstü ERİŞİLEMEZ ve
hedefi q93-94'te tutan 2 fixture bütçe içinde çözülemez (8/10). Aralık (70,95)
ile aynı bütçede 10/10 çözülür, ortalama sapma 1,12 → 0,40 kalite basamağına
iner. Tablo: `docs/reports/11-faz1-arge.md` §T-013.4.

Gerçek minimum 70'in ALTINDA olan düşük entropili görsellerde arama 70'e dayanır
ve sonucu `reason="floor_reached"` ile işaretler: çıktı hedefi TUTAR (gereğinden
yüksek kalite), yalnız "en düşük" olduğu iddia edilmez. Çağıran bu işareti görüp
aralığı genişletebilir."""

DEFAULT_MAX_ENCODES: int = 4
"""Görev sözleşmesi: en fazla 4 encode denemesi."""

PURE_MAX_PIXELS: int = 512 * 512
"""Saf Python arka ucunun üst piksel sınırı. Üstünde görsel küçültülür."""

ALPHA_BACKGROUND: tuple[int, int, int] = (255, 255, 255)
"""Alfa kanalı bu zemine kompozit edilir — `tradehub_core/media/pipeline/policy/content_rules.json`
`preprocessing.alpha_handling` ile aynı kural."""

LOSSLESS_SENTINEL: str = "bit_exact"
"""Politikada `quality.metric` bu ise SSIM aranmaz; çıktı piksel-eş olmalıdır."""

_POLICY_DIR = Path(__file__).resolve().parents[1] / "policy" / "slots"


# --- Veri tipleri -----------------------------------------------------------


@dataclass(frozen=True)
class SsimResult:
	"""Tek bir SSIM ölçümünün künyesi."""

	value: float
	backend: str
	win_size: int
	width: int
	height: int
	downscaled: bool = False
	windows: int = 0

	def __float__(self) -> float:
		return self.value


@dataclass(frozen=True)
class EncodeAttempt:
	"""İkili aramanın tek adımı — hangi kalite denendi, ne çıktı."""

	quality: int
	ssim: float
	out_bytes: int
	passed: bool
	reason: str = ""


@dataclass
class QualitySearchResult:
	"""`search_quality` çıktısı.

	`ok=False` ise hedef SSIM bütçe içinde YAKALANAMADI: `quality` o durumda
	denenenler arasında en yüksek SSIM'i veren kalitedir, `content` ona aittir.
	Çağıran ya bütçeyi büyütmeli ya da orijinali passthrough bırakmalıdır —
	modül kendi başına sessizce hedefi düşürmez.
	"""

	ok: bool
	quality: int
	ssim: float
	content: bytes
	target_ssim: float
	attempts: list[EncodeAttempt] = field(default_factory=list)
	reason: str = ""
	reference_size: tuple[int, int] = (0, 0)
	source_bytes: int = 0

	@property
	def out_bytes(self) -> int:
		return len(self.content)

	@property
	def encodes(self) -> int:
		return len(self.attempts)

	@property
	def saving_ratio(self) -> float:
		"""Orijinale göre kazanç oranı. Kaynak boyutu bilinmiyorsa 0.0."""
		if not self.source_bytes:
			return 0.0
		return 1.0 - (self.out_bytes / self.source_bytes)


# --- Görsel yükleme / hazırlık ---------------------------------------------


def _open(src: bytes | str | Path) -> "object":
	"""bytes / yol → PIL Image. Zaten Image ise dokunmadan döner."""
	from PIL import Image

	if isinstance(src, Image.Image):
		return src
	if isinstance(src, (str, Path)):
		return Image.open(str(src))
	return Image.open(io.BytesIO(src))


def to_luma(src: bytes | str | Path) -> "object":
	"""Görseli `L` (BT.601 luma) moduna indirger; alfayı beyaza kompozit eder.

	`content_rules.json` `preprocessing` bloğuyla aynı sözleşme: EXIF rotasyonu
	burada UYGULANMAZ — karşılaştırılan iki görüntü de aynı boru hattından
	geçtiği için rotasyon zaten `master_reference` aşamasında piksele işlenmiştir.
	"""
	from PIL import Image

	im = _open(src)
	if im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info):
		rgba = im.convert("RGBA")
		zemin = Image.new("RGBA", rgba.size, (*ALPHA_BACKGROUND, 255))
		im = Image.alpha_composite(zemin, rgba)
	if im.mode != "L":
		im = im.convert("L")
	return im


def master_reference(content: bytes, max_dim: int):
	"""Encode ÖNCESİ referans pikseller — `engine.optimize`'ın kaydetmeden önceki hâli.

	`engine.optimize` sırası: `Image.open` → `exif_transpose` → `thumbnail((max_dim,
	max_dim))` → (JPEG ise) `convert("RGB")` → `save`. Burada yalnız son adım
	atlanır; kalan aynı Pillow çağrılarıdır. SSIM bu referansa göre ölçülür,
	orijinal tam çözünürlüğe göre DEĞİL: aksi hâlde ölçülen şey encode kaybı değil,
	küçültme kaybı olurdu.

	JPEG'in `convert("RGB")` adımı bilerek taklit edilir: engine CMYK JPEG'i RGB'ye
	çevirerek kaydeder, referans CMYK kalırsa SSIM encode kaybını değil renk uzayı
	dönüşümünü ölçer (canlıda 38 CMYK dosya var — `docs/reports/08-canli-olcum.md`).
	"""
	from PIL import ImageOps

	im = _open(content)
	fmt = (getattr(im, "format", "") or "").upper()
	im = ImageOps.exif_transpose(im)
	if max_dim and max_dim > 0:
		im.thumbnail((max_dim, max_dim))
	if fmt == "JPEG" and im.mode != "RGB":
		im = im.convert("RGB")
	return im


# --- SSIM çekirdeği ---------------------------------------------------------


def _numpy_varsa():
	try:
		import numpy  # noqa: F401

		return numpy
	except Exception:
		return None


def _ssim_numpy(np, a, b, win: int) -> tuple[float, int]:
	"""numpy arka ucu — integral görüntü ile düzgün pencere ortalamaları."""
	x = a.astype(np.float64)
	y = b.astype(np.float64)

	def pencere_ortalamasi(arr):
		h, w = arr.shape
		sat = np.zeros((h + 1, w + 1), dtype=np.float64)
		np.cumsum(np.cumsum(arr, axis=0), axis=1, out=sat[1:, 1:])
		toplam = sat[win:, win:] - sat[:-win, win:] - sat[win:, :-win] + sat[:-win, :-win]
		return toplam / float(win * win)

	ux = pencere_ortalamasi(x)
	uy = pencere_ortalamasi(y)
	uxx = pencere_ortalamasi(x * x)
	uyy = pencere_ortalamasi(y * y)
	uxy = pencere_ortalamasi(x * y)

	np_ = float(win * win)
	cov_norm = np_ / (np_ - 1.0)  # yansız (unbiased) düzeltme — skimage ile aynı
	vx = cov_norm * (uxx - ux * ux)
	vy = cov_norm * (uyy - uy * uy)
	vxy = cov_norm * (uxy - ux * uy)

	a1 = 2.0 * ux * uy + C1
	a2 = 2.0 * vxy + C2
	b1 = ux * ux + uy * uy + C1
	b2 = vx + vy + C2
	harita = (a1 * a2) / (b1 * b2)
	return float(harita.mean()), int(harita.size)


def _sat_pure(vals: list[float], w: int, h: int) -> list[float]:
	"""Saf Python integral görüntü (summed-area table), (h+1)×(w+1) düzleştirilmiş."""
	sat = [0.0] * ((w + 1) * (h + 1))
	for y in range(h):
		satir_toplami = 0.0
		ust = (y) * (w + 1)
		alt = (y + 1) * (w + 1)
		taban = y * w
		for x in range(w):
			satir_toplami += vals[taban + x]
			sat[alt + x + 1] = sat[ust + x + 1] + satir_toplami
	return sat


def _pencere_toplamlari_pure(sat: list[float], w: int, h: int, win: int) -> list[float]:
	"""Integral görüntüden tüm tam-içerdeki pencerelerin toplamı."""
	ow = w - win + 1
	oh = h - win + 1
	out = [0.0] * (ow * oh)
	stride = w + 1
	for y in range(oh):
		ust = y * stride
		alt = (y + win) * stride
		hedef = y * ow
		for x in range(ow):
			out[hedef + x] = sat[alt + x + win] - sat[ust + x + win] - sat[alt + x] + sat[ust + x]
	return out


def _ssim_pure(a: list[int], b: list[int], w: int, h: int, win: int) -> tuple[float, int]:
	"""Saf Python arka ucu. numpy yoksa kullanılır; formül numpy yoluyla AYNIdır."""
	xa = [float(v) for v in a]
	yb = [float(v) for v in b]
	xx = [v * v for v in xa]
	yy = [v * v for v in yb]
	xy = [xa[i] * yb[i] for i in range(len(xa))]

	n = float(win * win)
	sx = _pencere_toplamlari_pure(_sat_pure(xa, w, h), w, h, win)
	sy = _pencere_toplamlari_pure(_sat_pure(yb, w, h), w, h, win)
	sxx = _pencere_toplamlari_pure(_sat_pure(xx, w, h), w, h, win)
	syy = _pencere_toplamlari_pure(_sat_pure(yy, w, h), w, h, win)
	sxy = _pencere_toplamlari_pure(_sat_pure(xy, w, h), w, h, win)

	cov_norm = n / (n - 1.0)
	toplam = 0.0
	for i in range(len(sx)):
		ux = sx[i] / n
		uy = sy[i] / n
		vx = cov_norm * (sxx[i] / n - ux * ux)
		vy = cov_norm * (syy[i] / n - uy * uy)
		vxy = cov_norm * (sxy[i] / n - ux * uy)
		pay = (2.0 * ux * uy + C1) * (2.0 * vxy + C2)
		payda = (ux * ux + uy * uy + C1) * (vx + vy + C2)
		toplam += pay / payda
	return (toplam / len(sx)) if sx else 1.0, len(sx)


def compute_ssim(
	ref: bytes | str | Path,
	cand: bytes | str | Path,
	*,
	win_size: int = WIN_SIZE,
	max_pixels: int | None = None,
	backend: str | None = None,
) -> SsimResult:
	"""İki görselin ortalama SSIM'i (1.0 = piksel-eş).

	Boyutlar farklıysa aday, referansın boyutuna LANCZOS ile getirilir — yoksa
	karşılaştırma tanımsızdır. `max_pixels` verilirse İKİSİ birden küçültülür ve
	sonuç `downscaled=True` ile işaretlenir (SSIM ölçeğe duyarlıdır, sayı artık
	master çözünürlüğün değeri değildir).
	"""
	from PIL import Image

	a = to_luma(ref)
	b = to_luma(cand)
	if a.size != b.size:
		b = b.resize(a.size, Image.LANCZOS)

	kucultuldu = False
	np = None if backend == "pure" else _numpy_varsa()
	sinir = max_pixels
	if sinir is None and np is None:
		sinir = PURE_MAX_PIXELS
	if sinir and a.width * a.height > sinir:
		oran = math.sqrt(sinir / float(a.width * a.height))
		yeni = (max(win_size, int(a.width * oran)), max(win_size, int(a.height * oran)))
		a = a.resize(yeni, Image.LANCZOS)
		b = b.resize(yeni, Image.LANCZOS)
		kucultuldu = True

	w, h = a.size
	if w < win_size or h < win_size:
		# Pencere sığmıyor: tek global pencereye düş (kenar kırpması anlamsız).
		win_size = min(w, h)
		if win_size < 2:
			return SsimResult(
				value=1.0 if a.tobytes() == b.tobytes() else 0.0,
				backend="degenerate",
				win_size=win_size,
				width=w,
				height=h,
				downscaled=kucultuldu,
				windows=0,
			)

	if np is not None:
		arr_a = np.frombuffer(a.tobytes(), dtype=np.uint8).reshape(h, w)
		arr_b = np.frombuffer(b.tobytes(), dtype=np.uint8).reshape(h, w)
		deger, pencere = _ssim_numpy(np, arr_a, arr_b, win_size)
		ad = "numpy"
	else:
		deger, pencere = _ssim_pure(list(a.tobytes()), list(b.tobytes()), w, h, win_size)
		ad = "pure"

	return SsimResult(
		value=deger,
		backend=ad,
		win_size=win_size,
		width=w,
		height=h,
		downscaled=kucultuldu,
		windows=pencere,
	)


# --- Politika hedefleri -----------------------------------------------------


@lru_cache(maxsize=None)
def _slot_politikalari() -> dict:
	"""`tradehub_core/media/pipeline/policy/slots/*.json` → {slot_key: policy}. Bir kez okunur."""
	out: dict = {}
	if not _POLICY_DIR.is_dir():
		return out
	for p in sorted(_POLICY_DIR.glob("*.json")):
		try:
			d = json.loads(p.read_text(encoding="utf-8"))
		except Exception:
			continue
		anahtar = d.get("slot_key")
		if anahtar:
			out[anahtar] = d
	return out


def target_for(slot_key: str, content_class: str) -> float | None:
	"""Slot + içerik sınıfı için hedef SSIM.

	`None` dönerse o slotta SSIM ARANMAZ: politika `quality.metric = "bit_exact"`
	diyor (logo slotları), yani çıktı kayıpsız olmalıdır. Bilinmeyen slot ya da
	sınıf için de `None` döner — çağıran uydurmak yerine hata vermelidir.
	"""
	pol = _slot_politikalari().get(slot_key)
	if not pol:
		return None
	q = pol.get("quality") or {}
	if q.get("metric") == LOSSLESS_SENTINEL:
		return None
	hedefler = q.get("target_ssim_per_class") or {}
	deger = hedefler.get(content_class)
	return float(deger) if deger is not None else None


def guess_content_class(src: bytes | str | Path) -> str:
	"""Kaba içerik sınıflandırıcı: `photo` | `graphic`.

	SSIM hedefi sınıfa bağlıdır (`quality.target_ssim_per_class`), bu yüzden
	arama bir sınıf ister. Ayırt edici ölçüt **benzersiz luma seviyesi oranı**:
	grafik/logo az sayıda düz ton kullanır, fotoğraf sürekli tona yayılır.
	Eşik `docs/reports/11-faz1-arge.md` §T-013.6'da fixture etiketlerine karşı
	ölçüldü. `text` ve `fine_detail` sınıfları BU FONKSİYONDA ÜRETİLMEZ —
	ayırt edici ölçütleri kalibre edilmedi (bkz. aynı bölüm, "ÖLÇÜLMEDİ").
	"""
	from PIL import Image

	im = to_luma(src)
	if im.width * im.height > 256 * 256:
		im.thumbnail((256, 256), Image.LANCZOS)
	histogram = im.histogram()
	toplam = float(sum(histogram)) or 1.0
	dolu_seviye = sum(1 for h in histogram if h > 0)
	# Tepe yoğunlaşması: en kalabalık 8 seviyenin toplam paydaki ağırlığı.
	tepe = sum(sorted(histogram, reverse=True)[:8]) / toplam
	if dolu_seviye <= 96 or tepe >= 0.60:
		return "graphic"
	return "photo"


# --- İkili arama ------------------------------------------------------------


def encode_at(content: bytes, max_dim: int, quality: int) -> tuple[bytes, str]:
	"""Tek bir encode denemesi — `tradehub_core.media.pipeline.optimize` sarmalayıcısı.

	engine bulunamazsa (bu depo dışında import edilirse) `ImportError` yükseltmez;
	boş çıktı + sebep döner ve arama `reason` ile durur.
	"""
	try:
		from tradehub_core.media import engine
	except Exception:
		return b"", "engine_unavailable"
	sonuc = engine.optimize(content, max_dim, quality)
	if not sonuc.ok:
		return b"", sonuc.reason
	return sonuc.content, ""


def search_quality(
	content: bytes,
	*,
	target_ssim: float,
	max_dim: int,
	quality_range: tuple[int, int] = DEFAULT_QUALITY_RANGE,
	max_encodes: int = DEFAULT_MAX_ENCODES,
	win_size: int = WIN_SIZE,
	max_pixels: int | None = None,
	encoder=None,
	reference=None,
) -> QualitySearchResult:
	"""Hedef SSIM'i sağlayan **en düşük** kaliteyi en fazla `max_encodes` encode ile bul.

	Yöntem: `quality_range` üzerinde klasik ikili arama. Her adımda orta kalite
	encode edilir, SSIM ölçülür; hedefi tutuyorsa aday saklanır ve üst yarı atılır,
	tutmuyorsa alt yarı atılır. Bütçe bittiğinde saklanan en düşük geçen aday
	dönülür.

	**Dayanak — monotonluk.** İkili arama, SSIM'in kalitede artan olmasını
	varsayar. Bu varsayım uydurulmadı: `docs/reports/11-faz1-arge.md` §T-013.3'te
	10 fixture × 14 kalite adımıyla ölçüldü ve aramanın bulduğu kalite, tüketici
	taramanın bulduğu gerçek minimumla karşılaştırıldı.

	`encoder`: test/ölçüm için enjekte edilebilir `(content, max_dim, quality) ->
	(bytes, reason)` imzalı fonksiyon. Verilmezse `encode_at` kullanılır.

	`reference`: encoder değiştirildiğinde referans pikseller de değişmelidir
	(ör. WebP master yolunda P-modlu PNG, encode öncesi RGBA'ya çevrilir).
	Verilmezse `master_reference` — yani `engine.optimize` semantiği — kullanılır.
	"""
	enc = encoder or encode_at
	lo, hi = quality_range
	if lo > hi:
		lo, hi = hi, lo

	ref = reference if reference is not None else master_reference(content, max_dim)
	sonuc = QualitySearchResult(
		ok=False,
		quality=hi,
		ssim=0.0,
		content=b"",
		target_ssim=target_ssim,
		reference_size=ref.size,
		source_bytes=len(content),
	)

	en_iyi_gecen: tuple[int, float, bytes] | None = None
	en_yuksek: tuple[int, float, bytes] | None = None

	while sonuc.encodes < max_encodes and lo <= hi:
		q = (lo + hi) // 2
		cikti, neden = enc(content, max_dim, q)
		if neden:
			sonuc.attempts.append(EncodeAttempt(q, 0.0, 0, False, neden))
			sonuc.reason = neden
			return sonuc
		olcum = compute_ssim(ref, cikti, win_size=win_size, max_pixels=max_pixels)
		gecti = olcum.value >= target_ssim
		sonuc.attempts.append(EncodeAttempt(q, olcum.value, len(cikti), gecti))
		if en_yuksek is None or olcum.value > en_yuksek[1]:
			en_yuksek = (q, olcum.value, cikti)
		if gecti:
			en_iyi_gecen = (q, olcum.value, cikti)
			hi = q - 1
		else:
			lo = q + 1

	if en_iyi_gecen is not None:
		sonuc.ok = True
		sonuc.quality, sonuc.ssim, sonuc.content = en_iyi_gecen
		# Taban kaliteye dayandıysa gerçek minimum aralığın DIŞINDA olabilir;
		# çağıran bunu bilmeli (sessizce "en düşük kalite bu" denmez).
		sonuc.reason = "floor_reached" if sonuc.quality == quality_range[0] else ""
	elif en_yuksek is not None:
		sonuc.quality, sonuc.ssim, sonuc.content = en_yuksek
		sonuc.reason = "target_unreachable_within_budget"
	else:
		sonuc.reason = "no_attempt"
	return sonuc
