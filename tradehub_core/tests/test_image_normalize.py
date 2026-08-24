"""T-061 — Normalleştirme testleri: yön, renk uzayı, DPI, piksel tavanı.

Ne doğrulanır
-------------
1. **EXIF yönü** fiziksel uygulanır ve etiket temizlenir.
2. ICC'li **CMYK/AdobeRGB → sRGB**, örneklenmiş CIEDE2000 ile ölçülür.
3. **3000×3000@300 → 2400×2400@72** tek kabul testinde doğrulanır.
4. **Alfa düşürülmez**, GPS EXIF korunsa bile temizlenir.
5. 30 MB yol girdisinin üç ardışık işleminde mutlak peak RSS <500 MB'dir.

DPI regresyonunun gerekçesi
---------------------------
ÖLÇÜLDÜ (2026-08-18, yerel Pillow 11.3.0) — `tradehub_core/media/pipeline.py`:

    mode_cmyk.jpg             kaynak dpi=None        → çıktı dpi=None
    dpi_3000x3000_300dpi.tif  kaynak dpi=(300,300)   → çıktı dpi=(1,1)
    fmt_tiff_lzw.tif          kaynak dpi=(1,1)       → çıktı dpi=(1,1)

Yani mevcut motor DPI'yi hiç yazmıyor; TIFF'te Pillow varsayılanı olan (1,1)
düşüyor. (1,1) DPI, görseli baskıya alan her araçta 3000 inç genişliğinde bir
sayfa demektir. `normalize.py` bunu 72'ye sabitler; aşağıdaki test iki
davranışı YAN YANA sabitler ki fark belgesiz kapanmasın.

Çalıştırma:

    python3 -m unittest tests.test_image_normalize -v
"""

from __future__ import annotations

import base64
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image import normalize as normalize_module  # noqa: E402
from tradehub_core.media.pipeline.image.normalize import (  # noqa: E402
	DEFAULT_DPI_OUT,
	NORMALIZE_SPOOL_MAX_BYTES,
	NormalizeSpec,
	delta_e_2000,
	normalize,
	target_size,
)
from tradehub_core.media.pipeline.image.probe import GuardConfig, HeaderProbe  # noqa: E402

IMAGES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
ICC_FIXTURES = ROOT / "tradehub_core" / "tests" / "fixtures" / "image_t061"

#: Fixture'ların hepsi geçsin diye gevşetilmiş kapı. Kapının kendisi
#: `test_image_probe.py`'de sınanıyor; burada sınanan normalleştirmedir.
GEVSEK = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)


def _vips_available() -> bool:
	try:
		import pyvips

		pyvips.version(0)
		return True
	except Exception:
		return False


def _ac(icerik: bytes):
	from PIL import Image

	return Image.open(io.BytesIO(icerik))


def _ornek_noktalar(size: tuple[int, int]) -> tuple[tuple[int, int], ...]:
	"""Kenarlar dahil 5×5 deterministik renk örnekleme ızgarası."""
	w, h = size
	xs = tuple(round(i * (w - 1) / 4) for i in range(5))
	ys = tuple(round(i * (h - 1) / 4) for i in range(5))
	return tuple((x, y) for y in ys for x in xs)


def _srgb_ornekleri(im, kaynak_icc: bytes) -> tuple[tuple[int, int, int], ...]:
	"""Kaynak ICC'yi doğrudan sRGB'ye taşıyıp 25 referans pikseli oku."""
	from PIL import ImageCms

	kaynak = ImageCms.ImageCmsProfile(io.BytesIO(kaynak_icc))
	hedef = ImageCms.createProfile("sRGB")
	rgb = ImageCms.profileToProfile(im, kaynak, hedef, outputMode="RGB")
	try:
		return tuple(rgb.getpixel(p) for p in _ornek_noktalar(rgb.size))
	finally:
		rgb.close()


def _lab_ornekleri(rgb: tuple[tuple[int, int, int], ...]) -> tuple[tuple[float, float, float], ...]:
	"""sRGB 8-bit örneklerini CIE Lab değerlerine çevir."""
	from PIL import Image, ImageCms

	im = Image.new("RGB", (len(rgb), 1))
	im.putdata(rgb)
	lab = ImageCms.profileToProfile(
		im, ImageCms.createProfile("sRGB"), ImageCms.createProfile("LAB"), outputMode="LAB"
	)
	try:
		return tuple((l * 100.0 / 255.0, a - 128.0, b - 128.0) for l, a, b in lab.getdata())
	finally:
		im.close()
		lab.close()


def _delta_e_ozeti(
	referans: tuple[tuple[int, int, int], ...],
	gercek: tuple[tuple[int, int, int], ...],
) -> tuple[float, float]:
	referans_lab = _lab_ornekleri(referans)
	gercek_lab = _lab_ornekleri(gercek)
	if len(referans_lab) != len(gercek_lab):
		raise AssertionError("ΔE örnek sayıları eşit değil")
	farklar = tuple(delta_e_2000(a, gercek_lab[i]) for i, a in enumerate(referans_lab))
	return (sum(farklar) / len(farklar), max(farklar))


def _icc_cmyk_tiff() -> bytes:
	"""CC0 CMYK profilli deterministik renk yaması fixture'ı."""
	from PIL import Image

	profil = base64.b64decode((ICC_FIXTURES / "CGATS001Compat-v2-micro.icc.b64").read_text())
	im = Image.new("CMYK", (160, 120))
	px = im.load()
	for y in range(im.height):
		for x in range(im.width):
			px[x, y] = ((x * 191) // 159, (y * 173) // 119, ((x + y) * 149) // 278, ((x // 20) * 11) % 80)
	buf = io.BytesIO()
	im.save(buf, "TIFF", compression="raw", icc_profile=profil, dpi=(300, 300))
	im.close()
	return buf.getvalue()


_MEMORY_PROBE_CODE = """
import gc
import json
import resource
import sys
import time
from tradehub_core.media.pipeline.image.normalize import NormalizeSpec, normalize
from tradehub_core.media.pipeline.image.probe import GuardConfig

path = sys.argv[1]
runs = int(sys.argv[2])
guard = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)
start = time.perf_counter()
notes = ()
sizes = []
for _ in range(runs):
    result = normalize(
        path,
        NormalizeSpec(max_long_edge=2400, min_long_edge=2000, fmt="JPEG"),
        guard=guard,
    )
    if not result.ok:
        raise SystemExit(result.reason)
    notes = result.notes
    sizes.append(result.size_bytes)
    del result
    gc.collect()
raw_peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
peak_bytes = int(raw_peak if sys.platform == "darwin" else raw_peak * 1024)
print(json.dumps({
    "input_bytes": __import__("os").path.getsize(path),
    "runs": len(sizes),
    "output_bytes": sizes,
    "peak_rss_bytes": peak_bytes,
    "elapsed_ms": round((time.perf_counter() - start) * 1000, 1),
    "path_streamed": "io:path_streamed" in notes,
    "output_spooled": any(n.startswith("io:output_spool_max=") for n in notes),
    "jpeg_decoder_draft": any(n.startswith("io:jpeg_decoder_draft:") for n in notes),
    "vips_sequential_predecode": "io:vips_sequential_predecode" in notes,
}))
"""


def _measure_peak_memory(path: Path, *, runs: int = 3) -> dict:
	"""Temiz alt süreçte sıralı peak RSS ölç; platform birimini byte'a çevir."""
	proc = subprocess.run(
		[sys.executable, "-c", _MEMORY_PROBE_CODE, str(path), str(runs)],
		cwd=ROOT,
		capture_output=True,
		text=True,
		timeout=120,
		check=False,
	)
	if proc.returncode:
		raise AssertionError(proc.stderr or proc.stdout)
	return json.loads(proc.stdout.strip().splitlines()[-1])


class YonTest(unittest.TestCase):
	"""EXIF yönü piksellere fiziksel uygulanmalı."""

	def test_orientation6_boyutlari_takas_eder(self):
		"""Saklanan 1200×1600, gösterilecek 1600×1200. Transpose YAPILMAZSA test kırılır."""
		kaynak = IMAGES / "exif_orientation6.jpg"
		with _ac(kaynak.read_bytes()) as im:
			self.assertEqual(im.size, (1200, 1600), "fixture beklenen saklanan ölçüde değil")

		r = normalize(kaynak, NormalizeSpec(max_long_edge=4000), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (1600, 1200))
		self.assertIn("orientation:exif_applied", r.notes)

	def test_orientation_preserve_takas_etmez(self):
		r = normalize(
			IMAGES / "exif_orientation6.jpg",
			NormalizeSpec(max_long_edge=4000, orientation="preserve"),
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (1200, 1600))

	def test_orientation_uygulanan_dosyada_exif_yon_etiketi_kalmaz(self):
		"""Pikseller döndürüldüyse etiket de düşmeli — yoksa görüntü İKİ KEZ döner."""
		r = normalize(IMAGES / "exif_orientation6.jpg", NormalizeSpec(), guard=GEVSEK)
		with _ac(r.content) as im:
			exif = im.getexif()
			self.assertIn(exif.get(0x0112, 1), (1, None), "orientation etiketi hâlâ 1 değil")

	def test_orientation3_karede_de_uygulanir_ve_etiket_silinir(self):
		"""Boyut değişmeyen 180° yön de uygulanmış sayılmalı (sınır durumu)."""
		from PIL import Image

		im = Image.new("RGB", (40, 40), (230, 20, 20))
		for y in range(20, 40):
			for x in range(20, 40):
				im.putpixel((x, y), (20, 20, 230))
		exif = Image.Exif()
		exif[0x0112] = 3
		buf = io.BytesIO()
		im.save(buf, "JPEG", quality=100, subsampling=0, exif=exif)
		im.close()

		r = normalize(
			buf.getvalue(),
			NormalizeSpec(fmt="PNG", strip_metadata={"exif": False, "gps": True, "xmp": True, "icc": False}),
			filename="orientation3.jpg",
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("orientation:exif_applied", r.notes)
		with _ac(r.content) as out:
			self.assertNotIn(0x0112, out.getexif())
			# 180° dönüşte kaynak sağ-alt mavi alan sol-üste gelir.
			self.assertGreater(out.getpixel((3, 3))[2], out.getpixel((3, 3))[0])

	def test_orientation6_jpeg_decoder_draft_eksenleri_dogru_takas_eder(self):
		"""Decode-time küçültme EXIF 6'nın saklanan/görünen eksenini karıştırmaz."""
		from PIL import Image

		im = Image.new("RGB", (800, 400), (20, 40, 180))
		exif = Image.Exif()
		exif[0x0112] = 6
		buf = io.BytesIO()
		im.save(buf, "JPEG", quality=95, exif=exif)
		im.close()

		r = normalize(
			buf.getvalue(),
			NormalizeSpec(max_long_edge=100, fmt="JPEG"),
			filename="orientation6-large.jpg",
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (50, 100))
		self.assertTrue(any(n.startswith("io:jpeg_decoder_draft:") for n in r.notes), r.notes)
		self.assertIn("orientation:exif_applied", r.notes)


class RenkUzayiTest(unittest.TestCase):
	"""CMYK / paletli / gri girdiler sRGB'ye taşınmalı."""

	def test_cmyk_srgbye_donusur(self):
		kaynak = IMAGES / "mode_cmyk.jpg"
		with _ac(kaynak.read_bytes()) as im:
			self.assertEqual(im.mode, "CMYK", "fixture CMYK değil")

		r = normalize(kaynak, NormalizeSpec(), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual(r.mode, "RGB")
		self.assertTrue(any(n.startswith("colorspace:cmyk") for n in r.notes), r.notes)
		self.assertEqual(r.colorspace, "sRGB")
		self.assertIn("sRGB", r.icc_profile)

	def test_delta_e_2000_sharma_referans_ciftleri(self):
		"""ΔE uygulaması yayımlanmış CIEDE2000 referans çiftlerini tutturur."""
		ciftler = (
			((50.0000, 2.6772, -79.7751), (50.0000, 0.0000, -82.7485), 2.0425),
			((50.0000, 3.1571, -77.2803), (50.0000, 0.0000, -82.7485), 2.8615),
			((50.0000, 2.8361, -74.0200), (50.0000, 0.0000, -82.7485), 3.4412),
		)
		for a, b, beklenen in ciftler:
			with self.subTest(beklenen=beklenen):
				self.assertAlmostEqual(delta_e_2000(a, b), beklenen, places=4)

	def test_icc_cmyk_srgb_delta_e_kaniti(self):
		"""ICC'li CMYK → sRGB; ΔE00, doğrudan lcms referansına göre ölçülür."""
		kaynak = _icc_cmyk_tiff()
		with _ac(kaynak) as im:
			profil = im.info["icc_profile"]
			referans = _srgb_ornekleri(im, profil)
			ham_rgb = im.convert("RGB")
			ham = tuple(ham_rgb.getpixel(p) for p in _ornek_noktalar(im.size))
			ham_rgb.close()

		r = normalize(kaynak, NormalizeSpec(fmt="PNG"), filename="icc-cmyk.tif", guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.mode, r.colorspace), ("RGB", "sRGB"))
		self.assertIn("colorspace:icc_transform", r.notes)
		self.assertIn("sRGB", r.icc_profile)
		with _ac(r.content) as out:
			rgb = out.convert("RGB")
			gercek = tuple(rgb.getpixel(p) for p in _ornek_noktalar(out.size))
			rgb.close()
		ortalama, en_kotu = _delta_e_ozeti(referans, gercek)
		_ham_ortalama, ham_en_kotu = _delta_e_ozeti(referans, ham)
		self.assertLessEqual(ortalama, 0.20, f"ortalama ΔE00={ortalama:.4f}")
		self.assertLessEqual(en_kotu, 0.50, f"maksimum ΔE00={en_kotu:.4f}")
		self.assertGreater(ham_en_kotu, 5.0, "fixture ICC dönüşümünü ayırt etmiyor")

	@unittest.skipUnless(_vips_available(), "pyvips/libvips yok — production image CI'da koşulur")
	def test_vips_sequential_icc_perceptual_delta_e_paritesi(self):
		"""Büyük-raster yolunda libvips relative varsayılanına geri dönülmemeli."""
		from PIL import Image, ImageCms

		kaynak = _icc_cmyk_tiff()
		with _ac(kaynak) as im:
			profil = ImageCms.ImageCmsProfile(io.BytesIO(im.info["icc_profile"]))
			referans = ImageCms.profileToProfile(
				im,
				profil,
				ImageCms.createProfile("sRGB"),
				outputMode="RGB",
			)
			kucuk_referans = referans.resize((80, 60), Image.Resampling.LANCZOS)
			referans.close()
		try:
			noktalar = _ornek_noktalar(kucuk_referans.size)
			beklenen = tuple(kucuk_referans.getpixel(p) for p in noktalar)
		finally:
			kucuk_referans.close()

		# Küçük fixture'da eşiği yalnız bu test için indirerek aynı public normalize
		# akışını ve sequential predecode dalını deterministik biçimde çalıştır.
		with mock.patch.object(normalize_module, "BOUNDED_PREDECODE_MIN_MEGAPIXELS", 0.0):
			r = normalize(
				kaynak,
				NormalizeSpec(max_long_edge=80, fmt="PNG"),
				filename="icc-vips.tif",
				guard=GEVSEK,
			)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("io:vips_sequential_predecode", r.notes)
		self.assertIn("colorspace:icc_transform", r.notes)
		with _ac(r.content) as out:
			rgb = out.convert("RGB")
			try:
				gercek = tuple(rgb.getpixel(p) for p in noktalar)
			finally:
				rgb.close()
		ortalama, en_kotu = _delta_e_ozeti(beklenen, gercek)
		self.assertLessEqual(ortalama, 0.50, f"ortalama ΔE00={ortalama:.4f}")
		self.assertLessEqual(en_kotu, 1.50, f"maksimum ΔE00={en_kotu:.4f}")

	def test_adobergb_srgb_delta_e_ve_alfa_kaniti(self):
		"""Gerçek AdobeRGB fixture ICC ile sRGB'ye taşınır; alfa aynı kalır."""
		kaynak = IMAGES / "real_adobergb_3780x2717.png"
		with _ac(kaynak.read_bytes()) as im:
			profil = im.info["icc_profile"]
			noktalar = _ornek_noktalar(im.size)
			referans = _srgb_ornekleri(im, profil)
			ham_rgb = im.convert("RGB")
			ham = tuple(ham_rgb.getpixel(p) for p in noktalar)
			ham_rgb.close()
			rgba = im.convert("RGBA")
			referans_alfa = tuple(rgba.getpixel(p)[3] for p in noktalar)
			rgba.close()

		r = normalize(kaynak, NormalizeSpec(fmt="PNG"), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.mode, r.colorspace), ("RGBA", "sRGB"))
		self.assertIn("colorspace:icc_transform", r.notes)
		self.assertIn("sRGB", r.icc_profile)
		with _ac(r.content) as out:
			rgb = out.convert("RGB")
			rgba = out.convert("RGBA")
			gercek = tuple(rgb.getpixel(p) for p in noktalar)
			gercek_alfa = tuple(rgba.getpixel(p)[3] for p in noktalar)
			rgb.close()
			rgba.close()
		ortalama, en_kotu = _delta_e_ozeti(referans, gercek)
		_ham_ortalama, ham_en_kotu = _delta_e_ozeti(referans, ham)
		self.assertLessEqual(ortalama, 0.20, f"ortalama ΔE00={ortalama:.4f}")
		self.assertLessEqual(en_kotu, 0.50, f"maksimum ΔE00={en_kotu:.4f}")
		self.assertGreater(ham_en_kotu, 0.50, "fixture AdobeRGB dönüşümünü ayırt etmiyor")
		self.assertEqual(gercek_alfa, referans_alfa)

	def test_palet_rgbye_donusur(self):
		r = normalize(IMAGES / "mode_palette_p.png", NormalizeSpec(), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual(r.mode, "RGB")
		self.assertIn("colorspace:palette_to_rgb", r.notes)

	def test_colorspace_preserve_cmyki_birakir(self):
		r = normalize(
			IMAGES / "mode_cmyk.jpg",
			NormalizeSpec(colorspace="preserve"),
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("colorspace:preserved", r.notes)

	def test_bozuk_icc_srgb_diye_yanlis_etiketlenmez(self):
		"""Bozuk profil sessizce sRGB etiketiyle yayınlanmak yerine güvenli düşer."""
		from PIL import Image

		im = Image.new("RGB", (32, 24), (40, 90, 150))
		buf = io.BytesIO()
		im.save(buf, "JPEG", icc_profile=b"not-an-icc-profile")
		im.close()

		r = normalize(buf.getvalue(), NormalizeSpec(), filename="bad-icc.jpg", guard=GEVSEK)

		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "icc_transform_failed")
		self.assertEqual(r.content, b"")
		self.assertIn("colorspace:profile_unreadable", r.notes)

	def test_alfa_dusurulmez(self):
		"""INV-07/FR-146: alfalı master alfasız biçime indirgenmez."""
		for ad in ("mode_rgba_alpha.png", "logo_alpha_512.png", "enc_webp_lossless.webp"):
			with self.subTest(dosya=ad):
				r = normalize(IMAGES / ad, NormalizeSpec(), guard=GEVSEK)
				self.assertTrue(r.ok, r.reason)
				self.assertIn(r.mode, ("RGBA", "LA", "PA"), f"{ad} alfasını kaybetti: {r.mode}")
				self.assertTrue(r.has_alpha)

	def test_alfali_gorsel_jpege_zorlanirsa_bicim_yukseltilir(self):
		"""JPEG alfa taşıyamaz; motor alfayı atmak yerine biçimi değiştirmeli."""
		r = normalize(IMAGES / "logo_alpha_512.png", NormalizeSpec(fmt="JPEG"), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertNotEqual(r.fmt, "JPEG")
		self.assertTrue(any("alpha:format_upgraded" in n for n in r.notes), r.notes)

	def test_inv07_resize_premultiply_gizli_rengi_kenara_sizdirmaz(self):
		"""Saydam kırmızının görünmez RGB'si opak mavi kenara karışmamalı."""
		from PIL import Image

		im = Image.new("RGBA", (100, 100), (255, 0, 0, 0))
		for y in range(25, 75):
			for x in range(25, 75):
				im.putpixel((x, y), (0, 0, 255, 255))
		buf = io.BytesIO()
		im.save(buf, "PNG")
		im.close()

		r = normalize(
			buf.getvalue(),
			NormalizeSpec(max_long_edge=20, fmt="PNG"),
			filename="alpha-edge.png",
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("alpha:premultiply_resize_unpremultiply", r.notes)
		with _ac(r.content) as out:
			yari = [p for p in out.getdata() if 0 < p[3] < 255]
		self.assertTrue(yari, "yeniden örneklenmiş alfa kenarı oluşmadı")
		self.assertLessEqual(max(p[0] for p in yari), 1, "gizli kırmızı kenara sızdı")
		self.assertGreaterEqual(min(p[2] for p in yari), 254)


class DpiTest(unittest.TestCase):
	"""DPI çıktıya AÇIKÇA yazılmalı — kaynaktan miras alınmamalı."""

	def test_dpi_72_olarak_yazilir(self):
		for ad in ("mode_cmyk.jpg", "dpi_3000x3000_300dpi.tif", "fmt_tiff_lzw.tif", "mode_rgba_alpha.png"):
			with self.subTest(dosya=ad):
				r = normalize(IMAGES / ad, NormalizeSpec(dpi_out=72), guard=GEVSEK)
				self.assertTrue(r.ok, r.reason)
				self.assertTrue(r.dpi_written, f"{ad}: DPI yazılmadı")
				self.assertEqual(tuple(round(v) for v in r.dpi), (72, 72))

	def test_varsayilan_dpi_72(self):
		self.assertEqual(DEFAULT_DPI_OUT, 72)

	def test_300dpi_kaynak_72ye_iner_piksel_korunur(self):
		"""INV-02: DPI düşürmek piksel çözünürlüğünü DÜŞÜRMEZ.

		YASAK olan: 3000×3000@300dpi → 720×720@72dpi (DPI oranı piksele uygulanmış).
		"""
		r = normalize(IMAGES / "dpi_3000x3000_300dpi.tif", NormalizeSpec(dpi_out=72), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual(tuple(round(v) for v in r.dpi), (72, 72))
		self.assertEqual((r.width, r.height), (3000, 3000), "DPI oranı piksele uygulanmış!")

	def test_kabul_3000x3000_300dpi_2400x2400_72dpi(self):
		"""INV-02/03: T-061 kabul örneği; alt sınır 2000 de sözleşmededir."""
		r = normalize(
			IMAGES / "dpi_3000x3000_300dpi.tif",
			NormalizeSpec(max_long_edge=2400, min_long_edge=2000, dpi_out=72),
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (2400, 2400))
		self.assertGreaterEqual(max(r.width, r.height), 2000)
		self.assertEqual(tuple(round(v) for v in r.dpi), (72, 72))
		self.assertTrue(r.resized)

	def test_webp_dpi_tasimadigini_soyler(self):
		"""Sessizce yutmak yasak: biçim DPI taşımıyorsa bu NOT edilmeli."""
		r = normalize(IMAGES / "mode_cmyk.jpg", NormalizeSpec(fmt="WEBP", dpi_out=72), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertFalse(r.dpi_written)
		self.assertIn("dpi_not_supported_by_format:WEBP", r.notes)

	def test_mevcut_engine_dpi_yazmiyor_regresyonu(self):
		"""Bu testin varlığı bir HATA'yı sabitler, doğru davranışı değil.

		`tradehub_core/media/pipeline.py` DPI yazmıyor: TIFF'te Pillow'un (1,1)
		varsayılanı düşüyor. `normalize.py` bunu düzeltir. İkisi yan yana
		sabitlendi ki `engine.py` bir gün düzeltilirse bu test kırılsın ve
		iki yolun ayrıştığı görülsün.
		"""
		from tradehub_core.media import engine

		ham = (IMAGES / "dpi_3000x3000_300dpi.tif").read_bytes()
		eski = engine.optimize(ham, 2400, 85)
		self.assertTrue(eski.ok, eski.reason)
		with _ac(eski.content) as im:
			eski_dpi = im.info.get("dpi")

		yeni = normalize(IMAGES / "dpi_3000x3000_300dpi.tif", NormalizeSpec(max_long_edge=2400), guard=GEVSEK)

		self.assertEqual(tuple(round(v) for v in eski_dpi), (1, 1), "engine.py düzelmiş — bu testi güncelle")
		self.assertEqual(tuple(round(v) for v in yeni.dpi), (72, 72))


class PikselTavaniTest(unittest.TestCase):
	"""Yalnız küçültme — upscale FR-028 gereği yasak."""

	def test_72mp_tavana_iner(self):
		kaynak = IMAGES / "edge_72mp.jpg"
		with _ac(kaynak.read_bytes()) as im:
			self.assertGreater(im.width * im.height / 1e6, 70.0, "fixture 72 MP değil")

		r = normalize(kaynak, NormalizeSpec(max_long_edge=2400), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual(max(r.width, r.height), 2400)
		self.assertTrue(r.resized)

	def test_megapiksel_tavani_uygulanir(self):
		r = normalize(IMAGES / "edge_72mp.jpg", NormalizeSpec(max_megapixels=4.0), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertLessEqual(r.width * r.height / 1e6, 4.0 + 0.01)

	def test_kucuk_gorsel_buyutulmez(self):
		"""96×96 avatar, tavan 2400 olsa bile 96×96 kalmalı."""
		r = normalize(IMAGES / "ok_avatar_96.png", NormalizeSpec(max_long_edge=2400), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (96, 96))
		self.assertFalse(r.resized)

	def test_target_size_asla_buyutmez(self):
		"""INV-01: ölçek faktörü hiçbir sınır birleşiminde 1'i aşmaz."""
		spec = NormalizeSpec(max_long_edge=4000)
		for w, h in ((100, 50), (1, 1), (3999, 10), (32, 48)):
			with self.subTest(olcu=(w, h)):
				tw, th = target_size(w, h, spec)
				self.assertLessEqual(tw, w)
				self.assertLessEqual(th, h)

	def test_target_size_orani_korur(self):
		spec = NormalizeSpec(max_long_edge=1000)
		tw, th = target_size(4000, 2000, spec)
		self.assertEqual((tw, th), (1000, 500))

	def test_min_long_edge_kucuk_kaynagi_buyutmez(self):
		"""Alt sınır kalite tabanıdır; INV-01'i geçersiz kılan upscale izni değildir."""
		spec = NormalizeSpec(max_long_edge=2400, min_long_edge=2000)
		self.assertEqual(target_size(1800, 900, spec), (1800, 900))
		self.assertEqual(target_size(3000, 1500, spec), (2400, 1200))

	def test_min_long_edge_maxtan_buyuk_olamaz(self):
		with self.assertRaises(ValueError):
			NormalizeSpec(max_long_edge=1000, min_long_edge=2000)

	def test_policy_min_pixel_edge_takma_adi_ve_metadata_varsayilani(self):
		spec = NormalizeSpec.from_policy({"max_long_edge": 2400, "min_pixel_edge": 2000})

		self.assertEqual((spec.min_long_edge, spec.max_long_edge), (2000, 2400))
		self.assertTrue(spec.strip_metadata["exif"])
		self.assertTrue(spec.strip_metadata["gps"])
		self.assertFalse(spec.strip_metadata["icc"])

	def test_allow_upscale_sozlesme_ihlali(self):
		with self.assertRaises(ValueError):
			NormalizeSpec(allow_upscale=True)


class BellekButcesiTest(unittest.TestCase):
	"""30 MB path girdisi bounded I/O ile üç kez sıralı işlenir."""

	def test_path_girdisi_read_bytes_kullanmaz(self):
		"""Dosya kaynağı tek parça Python bytes kopyasına alınmamalı."""
		with mock.patch.object(Path, "read_bytes", side_effect=AssertionError("tam dosya okundu")):
			r = normalize(IMAGES / "ok_product_4x5.jpg", NormalizeSpec(fmt="PNG"), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("io:path_streamed", r.notes)
		self.assertIn(f"io:output_spool_max={NORMALIZE_SPOOL_MAX_BYTES}", r.notes)

	def test_30mb_uc_ardisik_islem_peak_bellek_500mb_altinda(self):
		"""AAA: 30 MB raw TIFF → 2400 JPEG, üç sıralı koşum, mutlak peak RSS."""
		from PIL import Image

		with tempfile.TemporaryDirectory(prefix="t061-memory-") as gecici:
			kaynak = Path(gecici) / "raw-30mb.tif"
			im = Image.new("RGB", (3200, 3200), (71, 129, 203))
			im.save(kaynak, "TIFF", compression="raw", dpi=(300, 300))
			im.close()
			self.assertGreaterEqual(kaynak.stat().st_size, 30_000_000)
			self.assertLess(kaynak.stat().st_size, 32 * 1024 * 1024)

			olcum = _measure_peak_memory(kaynak)

		self.assertEqual(olcum["runs"], 3)
		self.assertTrue(olcum["path_streamed"])
		self.assertTrue(olcum["output_spooled"])
		self.assertLess(olcum["peak_rss_bytes"], 500 * 1024 * 1024, olcum)

	def test_72mp_jpeg_decode_asamasinda_kuculur_peak_bellek_500mb_altinda(self):
		"""AAA: gerçek stres fixture'ı full RGB decode edilmeden üç kez işlenir."""
		olcum = _measure_peak_memory(IMAGES / "edge_72mp.jpg")

		self.assertEqual(olcum["runs"], 3)
		self.assertTrue(olcum["path_streamed"])
		self.assertTrue(olcum["jpeg_decoder_draft"], olcum)
		self.assertLess(olcum["peak_rss_bytes"], 500 * 1024 * 1024, olcum)

	def test_large_non_jpeg_pyvips_yoksa_pillow_oom_yoluna_dusmez(self):
		"""Bounded decoder yokluğu makine kodlu fail-closed olmalı, tam decode değil."""
		probe = HeaderProbe(
			filename="large.png",
			detected="png",
			fmt="PNG",
			width=6000,
			height=5000,
			mode="RGBA",
			has_alpha=True,
			readable=True,
		)
		with (
			mock.patch.object(normalize_module, "_assert", return_value=probe),
			mock.patch.object(normalize_module, "_load_pyvips", return_value=None, create=True),
			mock.patch.object(normalize_module, "_open_source", side_effect=AssertionError("full decode")),
		):
			r = normalize(b"encoded-png", NormalizeSpec(max_long_edge=2400), guard=GEVSEK)

		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "bounded_decoder_unavailable")
		self.assertIn("io:bounded_decode_required", r.notes)

	@unittest.skipUnless(_vips_available(), "pyvips/libvips yok — production image CI'da koşulur")
	def test_72mp_rgba_sequential_predecode_peak_bellek_500mb_altinda(self):
		"""Kabul sınırındaki RGBA PNG tam ikinci raster tamponu kurmadan küçülür."""
		with tempfile.TemporaryDirectory(prefix="t061-rgba-memory-") as gecici:
			kaynak = Path(gecici) / "alpha-72mp.png"
			uret = (
				"from PIL import Image; import sys; "
				"im=Image.new('RGBA',(8527,8527),(10,20,30,128)); "
				"im.save(sys.argv[1],'PNG',compress_level=9); im.close()"
			)
			subprocess.run([sys.executable, "-c", uret, str(kaynak)], check=True, timeout=120)

			olcum = _measure_peak_memory(kaynak, runs=1)

		self.assertTrue(olcum["vips_sequential_predecode"], olcum)
		self.assertLess(olcum["peak_rss_bytes"], 500 * 1024 * 1024, olcum)


class MetadataTest(unittest.TestCase):
	"""GPS her hâlükârda silinir; ICC bilinçli karar."""

	def test_gps_silinir(self):
		"""INV-04: yayınlanan çıktıda GPS bulunmaz."""
		kaynak = IMAGES / "exif_gps.jpg"
		with _ac(kaynak.read_bytes()) as im:
			self.assertTrue(im.getexif().get(0x8825), "fixture'da GPS yok")

		r = normalize(kaynak, NormalizeSpec(), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("metadata:gps_removed", r.notes)
		with _ac(r.content) as im:
			self.assertFalse(im.getexif().get(0x8825), "GPS çıktıda hâlâ var")

	def test_inv04_varsayilan_exif_ve_xmp_bloklarini_siler(self):
		"""Kişisel EXIF ve XMP kaynakta mevcutken çıktıdan bütünüyle düşer."""
		from PIL import Image

		im = Image.new("RGB", (32, 24), (20, 80, 160))
		exif = Image.Exif()
		exif[0x013B] = "private-author"
		buf = io.BytesIO()
		im.save(buf, "JPEG", exif=exif, xmp=b"<x:xmpmeta>private</x:xmpmeta>")
		im.close()
		with _ac(buf.getvalue()) as source:
			self.assertTrue(source.getexif())
			self.assertIn("xmp", source.info)

		r = normalize(buf.getvalue(), NormalizeSpec(), filename="private.jpg", guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		with _ac(r.content) as out:
			self.assertFalse(out.getexif())
			self.assertNotIn("xmp", out.info)

	def test_exif_korunsa_bile_gps_ifd_kaldirilir(self):
		"""GPS temizliği `strip.exif` kararından bağımsız güvenlik kuralıdır."""
		r = normalize(
			IMAGES / "exif_gps.jpg",
			NormalizeSpec(strip_metadata={"exif": False, "gps": True, "xmp": True, "icc": False}),
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		with _ac(r.content) as im:
			exif = im.getexif()
			self.assertFalse(exif.get(0x8825), "GPS işaretçisi çıktıda kaldı")
			self.assertFalse(exif.get_ifd(0x8825), "GPS koordinat IFD'si çıktıda kaldı")

	def test_inv04_eski_politika_gps_false_dese_de_koordinat_yayinlanmaz(self):
		"""GPS zorunlu güvenlik temizliğidir; eski politika onu geri açamaz."""
		r = normalize(
			IMAGES / "exif_gps.jpg",
			NormalizeSpec(strip_metadata={"exif": False, "gps": False, "icc": False}),
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		with _ac(r.content) as im:
			self.assertFalse(im.getexif().get(0x8825))
			self.assertFalse(im.getexif().get_ifd(0x8825))

	def test_icc_strip_istenirse_dusurulur(self):
		r = normalize(
			IMAGES / "icc_srgb_embedded.jpg",
			NormalizeSpec(strip_metadata={"exif": True, "gps": True, "icc": True}),
			guard=GEVSEK,
		)

		self.assertTrue(r.ok, r.reason)
		self.assertFalse(r.icc_embedded)
		self.assertIn("metadata:icc_stripped", r.notes)


class SozlesmeTest(unittest.TestCase):
	"""Motor istisna atmaz; başarısızlıkta yarım çıktı dönmez."""

	def test_kapi_reddi_normalize_edilmez(self):
		r = normalize(
			ROOT / "tradehub_core" / "tests" / "fixtures" / "malicious" / "bomb_100mp.png",
			NormalizeSpec(),
		)

		self.assertFalse(r.ok)
		self.assertEqual(r.content, b"")
		self.assertIn("gate_reject", r.notes)

	def test_bozuk_girdi_istisna_atmaz(self):
		for girdi in (b"", b"\x00\x01", b"garbage"):
			with self.subTest(girdi=girdi[:6]):
				r = normalize(girdi, NormalizeSpec())
				self.assertFalse(r.ok)
				self.assertEqual(r.content, b"")

	def test_cikti_geri_acilabilir(self):
		"""Bozuk dosya diske YAZILMAMALI — motor kendi çıktısını doğrular."""
		kayitlar = json.loads(MANIFEST.read_text(encoding="utf-8"))["fixtures"]
		for f in kayitlar:
			if f["class"] in ("malicious", "video"):
				continue
			yol = ROOT / f["file"]
			with self.subTest(dosya=yol.name):
				r = normalize(yol, NormalizeSpec(max_long_edge=2400), guard=GEVSEK)
				self.assertTrue(r.ok, f"{yol.name}: {r.reason}")
				with _ac(r.content) as im:
					im.verify()

	def test_to_dict_serilestirilebilir(self):
		r = normalize(IMAGES / "ok_product_4x5.jpg", NormalizeSpec(), guard=GEVSEK)
		sozluk = r.to_dict()
		json.dumps(sozluk)
		self.assertTrue(sozluk["ok"])
		self.assertEqual(sozluk["has_alpha"], r.has_alpha)
		self.assertEqual(sozluk["applied_steps"], list(r.notes))


if __name__ == "__main__":
	unittest.main(verbosity=2)
