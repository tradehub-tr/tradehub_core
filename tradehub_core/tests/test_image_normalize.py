"""T-061 — Normalleştirme testleri: yön, renk uzayı, DPI, piksel tavanı.

Ne doğrulanır
-------------
1. **EXIF yönü** fiziksel uygulanır (`exif_orientation6.jpg` → 1600×1200).
2. **CMYK → sRGB** dönüşümü yapılır (`mode_cmyk.jpg` → RGB).
3. **DPI çıktıya AÇIKÇA yazılır** (72) — bugünkü `engine.py`'nin yazmadığı.
4. **Piksel tavanı** uygulanır (`edge_72mp.jpg`), **upscale asla** yapılmaz.
5. **Alfa düşürülmez**, GPS her hâlükârda silinir.

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

import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.image.normalize import (  # noqa: E402
	DEFAULT_DPI_OUT,
	NormalizeSpec,
	normalize,
	target_size,
)
from tradehub_core.media.pipeline.image.probe import GuardConfig  # noqa: E402

IMAGES = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "images"
MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"

#: Fixture'ların hepsi geçsin diye gevşetilmiş kapı. Kapının kendisi
#: `test_image_probe.py`'de sınanıyor; burada sınanan normalleştirmedir.
GEVSEK = GuardConfig(max_megapixels=200.0, max_bytes=64 * 1024 * 1024, allow_animated=True)


def _ac(icerik: bytes):
	from PIL import Image

	return Image.open(io.BytesIO(icerik))


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

	def test_alfa_dusurulmez(self):
		"""FR-146: alfalı master alfasız biçime indirgenmez."""
		for ad in ("mode_rgba_alpha.png", "logo_alpha_512.png", "enc_webp_lossless.webp"):
			with self.subTest(dosya=ad):
				r = normalize(IMAGES / ad, NormalizeSpec(), guard=GEVSEK)
				self.assertTrue(r.ok, r.reason)
				self.assertIn(r.mode, ("RGBA", "LA", "PA"), f"{ad} alfasını kaybetti: {r.mode}")

	def test_alfali_gorsel_jpege_zorlanirsa_bicim_yukseltilir(self):
		"""JPEG alfa taşıyamaz; motor alfayı atmak yerine biçimi değiştirmeli."""
		r = normalize(IMAGES / "logo_alpha_512.png", NormalizeSpec(fmt="JPEG"), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertNotEqual(r.fmt, "JPEG")
		self.assertTrue(any("alpha:format_upgraded" in n for n in r.notes), r.notes)


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
		"""DPI düşürmek çözünürlüğü DÜŞÜRMEZ (docs/standards/dpi-ve-cozunurluk.md).

		YASAK olan: 3000×3000@300dpi → 720×720@72dpi (DPI oranı piksele uygulanmış).
		"""
		r = normalize(IMAGES / "dpi_3000x3000_300dpi.tif", NormalizeSpec(dpi_out=72), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertEqual(tuple(round(v) for v in r.dpi), (72, 72))
		self.assertEqual((r.width, r.height), (3000, 3000), "DPI oranı piksele uygulanmış!")

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

	def test_allow_upscale_sozlesme_ihlali(self):
		with self.assertRaises(ValueError):
			NormalizeSpec(allow_upscale=True)


class MetadataTest(unittest.TestCase):
	"""GPS her hâlükârda silinir; ICC bilinçli karar."""

	def test_gps_silinir(self):
		kaynak = IMAGES / "exif_gps.jpg"
		with _ac(kaynak.read_bytes()) as im:
			self.assertTrue(im.getexif().get(0x8825), "fixture'da GPS yok")

		r = normalize(kaynak, NormalizeSpec(), guard=GEVSEK)

		self.assertTrue(r.ok, r.reason)
		self.assertIn("metadata:gps_removed", r.notes)
		with _ac(r.content) as im:
			self.assertFalse(im.getexif().get(0x8825), "GPS çıktıda hâlâ var")

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
		json.dumps(r.to_dict())
		self.assertTrue(r.to_dict()["ok"])


if __name__ == "__main__":
	unittest.main(verbosity=2)
