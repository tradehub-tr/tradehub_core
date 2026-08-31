"""KD-02 — Normalleştirme sözleşmesi (`media/pipeline/image/normalize.py`, 1133 satır).

Denetlenen davranış sözleşmesi (kaynaktan okundu, docstring'den değil):
  1. Kapı reddi normalleştirmeyi durdurur ve YARIM ÇIKTI DÖNMEZ.
  2. Asla büyütmez (FR-028) — `allow_upscale=True` sözleşme ihlali.
  3. DPI metadata'dır: `dpi_out` yazılır, piksel ölçüsü DEĞİŞMEZ.
  4. EXIF yönü piksele uygulanır ve etiket çıktıdan silinir (çift dönme yok).
  5. GPS her koşulda gider (INV-04) — `strip` sözlüğü kapalı olsa bile.
  6. Alfa asla düşürülmez (FR-146) — biçim gerekirse WebP'ye yükseltilir.
  7. Çıktı geri açılabilir olmalı; açılamıyorsa `ok=False`.
  8. Fonksiyon HİÇBİR girdide istisna atmaz.
"""

from __future__ import annotations

import unittest
from unittest import mock

from tradehub_core.media.pipeline.image import normalize as nrm
from tradehub_core.media.pipeline.image.probe import GuardConfig
from tradehub_core.tests.kapsamli import _yardim as y


def _spec(**kw) -> nrm.NormalizeSpec:
	return nrm.NormalizeSpec(**kw)


def _ac(icerik: bytes):
	import io

	from PIL import Image

	return Image.open(io.BytesIO(icerik))


# ══════════════════════════════════════════════════════════════════════
# 1. NormalizeSpec doğrulaması
# ══════════════════════════════════════════════════════════════════════


class TestSpecDogrulama(unittest.TestCase):
	def test_bi_upscale_sozlesme_ihlali(self):
		with self.assertRaises(ValueError) as c:
			_spec(allow_upscale=True)
		self.assertIn("FR-028", str(c.exception))

	def test_sn_negatif_sinirlar_reddedilir(self):
		for kw in ({"max_long_edge": -1}, {"min_long_edge": -1}, {"max_megapixels": -0.5}):
			with self.subTest(kw=kw):
				with self.assertRaises(ValueError):
					_spec(**kw)

	def test_sn_min_max_tutarsizligi(self):
		with self.assertRaises(ValueError):
			_spec(max_long_edge=100, min_long_edge=200)

	def test_sn_min_max_sifir_max_ile_serbest(self):
		"""`max_long_edge=0` (sınırsız) iken min kontrolü uygulanmaz."""
		s = _spec(max_long_edge=0, min_long_edge=5000)
		self.assertEqual(s.min_long_edge, 5000)

	def test_bi_bilinmeyen_colorspace_ve_orientation(self):
		with self.assertRaises(ValueError):
			_spec(colorspace="cmyk")
		with self.assertRaises(ValueError):
			_spec(orientation="dondurme")

	def test_bi_target_format_normalizasyonu(self):
		self.assertEqual(_spec(fmt="jpg").target_format, "JPEG")
		self.assertEqual(_spec(fmt="webp").target_format, "WEBP")
		self.assertEqual(_spec(fmt="preserve").target_format, "")
		self.assertEqual(_spec(fmt="").target_format, "")

	def test_bi_from_policy_alanlari(self):
		s = nrm.NormalizeSpec.from_policy(
			{
				"max_long_edge": 1600,
				"min_long_edge": 800,
				"max_megapixels": 12,
				"dpi_out": 72,
				"colorspace": "srgb",
				"orientation": "apply_exif",
				"format": "webp",
				"strip_metadata": {"icc": True},
			}
		)
		self.assertEqual(s.max_long_edge, 1600)
		self.assertEqual(s.min_long_edge, 800)
		self.assertEqual(s.max_megapixels, 12.0)
		self.assertEqual(s.target_format, "WEBP")
		self.assertTrue(s.strip_metadata["icc"])
		# Varsayılanlar korunmalı — kısmi sözlük tamamını EZMEMELİ
		self.assertTrue(s.strip_metadata["gps"])
		self.assertTrue(s.strip_metadata["exif"])

	def test_bi_from_policy_min_pixel_edge_takma_adi(self):
		s = nrm.NormalizeSpec.from_policy({"min_pixel_edge": 640})
		self.assertEqual(s.min_long_edge, 640)


# ══════════════════════════════════════════════════════════════════════
# 2. target_size — saf geometri
# ══════════════════════════════════════════════════════════════════════


class TestHedefOlcu(unittest.TestCase):
	def test_bi_tavanin_altinda_degismez(self):
		self.assertEqual(nrm.target_size(800, 600, _spec(max_long_edge=1600)), (800, 600))

	def test_bi_uzun_kenar_tavani(self):
		self.assertEqual(nrm.target_size(3200, 1600, _spec(max_long_edge=1600)), (1600, 800))

	def test_bi_megapiksel_tavani(self):
		# 4000×3000 = 12 MP → 3 MP tavanı → ölçek 0,5
		self.assertEqual(nrm.target_size(4000, 3000, _spec(max_megapixels=3.0)), (2000, 1500))

	def test_bi_iki_tavandan_kucuk_olan_kazanir(self):
		olcu = nrm.target_size(4000, 3000, _spec(max_long_edge=2000, max_megapixels=3.0))
		self.assertEqual(olcu, (2000, 1500))
		olcu2 = nrm.target_size(4000, 3000, _spec(max_long_edge=1000, max_megapixels=12.0))
		self.assertEqual(olcu2, (1000, 750))

	def test_bi_asla_buyutmez(self):
		self.assertEqual(nrm.target_size(100, 50, _spec(max_long_edge=4000, min_long_edge=2000)), (100, 50))

	def test_sn_sifir_ve_negatif_olcu_oldugu_gibi_doner(self):
		self.assertEqual(nrm.target_size(0, 0, _spec(max_long_edge=100)), (0, 0))
		self.assertEqual(nrm.target_size(-5, 10, _spec(max_long_edge=100)), (-5, 10))

	def test_sn_kenar_en_az_1_piksel(self):
		olcu = nrm.target_size(10000, 1, _spec(max_long_edge=10))
		self.assertEqual(olcu, (10, 1))
		self.assertGreaterEqual(min(olcu), 1)

	def test_bi_min_long_edge_alt_siniri_korur_AMA_MP_TAVANI_KAZANIR(self):
		"""F-06 düzeltildi: alt sınır uygulanır, MP tavanını AŞAMAZ.

		Çakışmada MP tavanı kazanır — alt sınır bir kalite tercihi, MP tavanı
		bellek/encode maliyetinin sert sınırı.
		"""
		s = _spec(max_long_edge=2000, min_long_edge=1000, max_megapixels=0.3)
		w, h = nrm.target_size(4000, 3000, s)
		self.assertLessEqual((w * h) / 1_000_000, 0.3 + 1e-9, "MP tavanı aşıldı")
		self.assertLess(w, 1000, "alt sınır MP tavanını ezmiş")

	def test_bi_min_long_edge_MP_tavani_ile_CAKISMIYORSA_uygulanir(self):
		"""Çakışma yoksa alt sınır normal şekilde çalışır."""
		s = _spec(max_long_edge=2000, min_long_edge=1000, max_megapixels=5.0)
		w, h = nrm.target_size(4000, 3000, s)
		self.assertGreaterEqual(max(w, h), 1000)
		self.assertLessEqual((w * h) / 1_000_000, 5.0 + 1e-9)

	def test_sn_min_long_edge_MEGAPIKSEL_TAVANINI_DELEMIYOR(self):
		"""F-06 düzeltildi — alt sınır artık MP tavanına kelepçeleniyor.

		Ölçüm (aynı girdi): 20000×1000, max_megapixels=5, min_long_edge=15000
		  önce: (15000, 750) = 11,25 MP  ← tavan aşılıyordu
		  şimdi: (10000, 500) =  5,00 MP  ← tavan tam uygulanıyor
		"""
		s = _spec(max_megapixels=5.0, min_long_edge=15000)
		w, h = nrm.target_size(20000, 1000, s)
		mp = (w * h) / 1_000_000.0
		self.assertLessEqual(mp, s.max_megapixels + 1e-9, f"F-06 geri geldi: {mp} MP")
		self.assertEqual((w, h), (10000, 500))

	def test_bi_kare_oran_korunur(self):
		for w, h in ((4000, 3000), (3000, 4000), (1920, 1080), (1000, 1000)):
			with self.subTest(w=w, h=h):
				nw, nh = nrm.target_size(w, h, _spec(max_long_edge=800))
				self.assertAlmostEqual(nw / nh, w / h, delta=0.02)


# ══════════════════════════════════════════════════════════════════════
# 3. Kapı entegrasyonu
# ══════════════════════════════════════════════════════════════════════


class TestKapiEntegrasyonu(unittest.TestCase):
	def test_bi_kapi_reddi_yarim_cikti_uretmez(self):
		r = nrm.normalize(y.jpeg_kuyrukta_script(dolgu=512), _spec(), filename="a.jpg")
		self.assertFalse(r.ok)
		self.assertEqual(r.content, b"")
		self.assertEqual(r.size_bytes, 0)
		self.assertIn("gate_reject", r.notes)
		self.assertTrue(r.reason)

	def test_bi_bos_girdi(self):
		r = nrm.normalize(b"", _spec(), filename="a.jpg")
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "empty")

	def test_bi_skip_guard_kapiyi_atlar(self):
		"""`skip_guard=True` reddi uygulamaz ama künyeyi yine ölçer."""
		r = nrm.normalize(y.gif_animated(16, 16), _spec(), filename="a.gif", skip_guard=True)
		self.assertTrue(r.ok, r.reason)
		self.assertTrue(any(n.startswith("animation:flattened_first_frame_of_") for n in r.notes), r.notes)

	def test_bi_animasyon_kapida_reddedilir(self):
		r = nrm.normalize(y.gif_animated(16, 16), _spec(), filename="a.gif")
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "animated_not_allowed")

	def test_bi_dar_kapi_gecirilebiliyor(self):
		r = nrm.normalize(
			y.jpeg(2000, 2000), _spec(), filename="a.jpg", guard=GuardConfig(max_megapixels=1.0)
		)
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "megapixel_bomb")


# ══════════════════════════════════════════════════════════════════════
# 4. DPI kuralı — "DPI metadata'dır, piksel değildir"
# ══════════════════════════════════════════════════════════════════════


class TestDpiKurali(unittest.TestCase):
	def test_bi_300dpi_girdi_72ye_yazilir_piksel_degismez(self):
		icerik = y.jpeg(1200, 900, dpi=(300, 300))
		r = nrm.normalize(icerik, _spec(fmt="jpeg", dpi_out=72), filename="mockup.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (1200, 900), "DPI değişimi piksele dokunmamalı")
		self.assertTrue(r.dpi_written)
		self.assertEqual(r.dpi, (72.0, 72.0))
		self.assertFalse(r.resized)
		with _ac(r.content) as im:
			self.assertEqual(im.size, (1200, 900))
			self.assertEqual(tuple(round(x) for x in im.info.get("dpi", (0, 0))), (72, 72))

	def test_bi_png_de_dpi_yazilir(self):
		r = nrm.normalize(y.png(100, 100), _spec(fmt="png", dpi_out=72), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertTrue(r.dpi_written)

	def test_bi_webp_dpi_tasiyamaz_ve_bunu_soyler(self):
		"""WebP konteynerinde çözünürlük alanı yok — sonuç UYDURULMAMALI."""
		r = nrm.normalize(y.png(100, 100), _spec(fmt="webp", dpi_out=72), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertFalse(r.dpi_written)
		self.assertIn("dpi_not_supported_by_format:WEBP", r.notes)

	def test_sn_dpi_out_sifir_yazilmaz(self):
		r = nrm.normalize(y.jpeg(64, 64), _spec(fmt="jpeg", dpi_out=0), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertFalse(r.dpi_written)
		self.assertNotIn("dpi_not_supported_by_format:JPEG", r.notes)

	def test_bi_dpi_yetenegi_tablosu(self):
		self.assertEqual(nrm.DPI_CAPABLE_FORMATS, frozenset({"JPEG", "PNG", "TIFF"}))


# ══════════════════════════════════════════════════════════════════════
# 5. EXIF yönü ve metadata
# ══════════════════════════════════════════════════════════════════════


class TestYonVeMetadata(unittest.TestCase):
	def test_bi_yon_6_piksele_uygulanir(self):
		icerik = y.jpeg(1200, 800, orientation=6)
		r = nrm.normalize(icerik, _spec(fmt="jpeg"), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (800, 1200), "görünen ölçü çıktı ölçüsü olmalı")
		self.assertIn("orientation:exif_applied", r.notes)

	def test_bi_yon_etiketi_ciktida_kalmaz(self):
		"""Çift dönme koruması: pikseller döndüyse etiket silinmeli."""
		r = nrm.normalize(
			y.jpeg(1200, 800, orientation=6),
			_spec(fmt="jpeg", strip_metadata={"exif": False, "gps": False, "xmp": False, "icc": False}),
			filename="a.jpg",
		)
		self.assertTrue(r.ok, r.reason)
		with _ac(r.content) as im:
			exif = im.getexif()
			self.assertIsNone(exif.get(0x0112), "orientation etiketi çıktıda kalmış")

	def test_bi_yon_preserve_secilirse_donmez(self):
		r = nrm.normalize(y.jpeg(1200, 800, orientation=6), _spec(fmt="jpeg", orientation="preserve"), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (1200, 800))
		self.assertNotIn("orientation:exif_applied", r.notes)

	def test_bi_yon_1_transpose_cagrilmaz(self):
		r = nrm.normalize(y.jpeg(120, 80, orientation=1), _spec(fmt="jpeg"), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertNotIn("orientation:exif_applied", r.notes)

	def test_gv_gps_strip_kapaliyken_bile_silinir(self):
		"""INV-04 — GPS koordinatı yayın çıktısına ASLA taşınmaz."""
		icerik = y.jpeg_gps(200, 200)
		with _ac(icerik) as im:
			self.assertTrue(im.getexif().get_ifd(0x8825), "kurgu: kaynakta GPS olmalı")

		r = nrm.normalize(
			icerik,
			_spec(fmt="jpeg", strip_metadata={"exif": False, "gps": False, "xmp": False, "icc": False}),
			filename="a.jpg",
		)
		self.assertTrue(r.ok, r.reason)
		with _ac(r.content) as im:
			exif = im.getexif()
			self.assertFalse(exif.get_ifd(0x8825), "GPS IFD çıktıda")
			self.assertIsNone(exif.get(0x8825), "GPS işaretçi etiketi çıktıda")
		self.assertIn("metadata:gps_removed", r.notes)

	def test_bi_varsayilan_exif_tamamen_silinir(self):
		r = nrm.normalize(y.jpeg_gps(120, 120), _spec(fmt="jpeg"), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertIn("metadata:exif_stripped", r.notes)
		with _ac(r.content) as im:
			self.assertFalse(dict(im.getexif()), "EXIF tamamen silinmeliydi")

	def test_bi_strip_metadata_varsayilanlari(self):
		self.assertEqual(
			nrm.DEFAULT_STRIP_METADATA, {"exif": True, "gps": True, "xmp": True, "icc": False}
		)

	def test_bi_xmp_notu_her_zaman_dusuluyor(self):
		r = nrm.normalize(y.jpeg(64, 64), _spec(fmt="jpeg"), filename="a.jpg")
		self.assertIn("metadata:xmp_stripped", r.notes)


# ══════════════════════════════════════════════════════════════════════
# 6. Alfa ve biçim yükseltme
# ══════════════════════════════════════════════════════════════════════


class TestAlfaVeBicim(unittest.TestCase):
	def test_bi_alfa_jpege_dusurulmez_webpe_yukseltilir(self):
		"""FR-146 — alfalı master alfasız biçime düşürülemez."""
		r = nrm.normalize(y.png(64, 64, alpha=True), _spec(fmt="jpeg"), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual(r.fmt, "WEBP")
		self.assertTrue(r.has_alpha)
		self.assertIn("alpha:format_upgraded_jpeg_to_webp", r.notes)

	def test_bi_alfasiz_jpeg_kalir(self):
		r = nrm.normalize(y.png(64, 64), _spec(fmt="jpeg"), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual(r.fmt, "JPEG")
		self.assertFalse(r.has_alpha)

	def test_bi_gif_master_webpe_tasinir(self):
		r = nrm.normalize(y.gif_animated(16, 16), _spec(), filename="a.gif", skip_guard=True)
		self.assertTrue(r.ok, r.reason)
		self.assertEqual(r.fmt, "WEBP")
		self.assertTrue(any(n.startswith("format:") and n.endswith("_to_webp") for n in r.notes), r.notes)

	def test_bi_palet_rgbye_cevrilir_kucultmeden_once(self):
		r = nrm.normalize(y.png(200, 200, palette=True), _spec(fmt="png", max_long_edge=100), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertTrue(any(n.startswith("colorspace:palette_to_") for n in r.notes), r.notes)
		self.assertEqual((r.width, r.height), (100, 100))

	def test_bi_srgb_profili_gomulur(self):
		r = nrm.normalize(y.jpeg(64, 64), _spec(fmt="jpeg"), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual(r.colorspace, "sRGB")

	def test_bi_icc_strip_edilirse_gomulmez(self):
		r = nrm.normalize(
			y.jpeg(64, 64),
			_spec(fmt="jpeg", strip_metadata={"exif": True, "gps": True, "xmp": True, "icc": True}),
			filename="a.jpg",
		)
		self.assertTrue(r.ok, r.reason)
		self.assertIn("metadata:icc_stripped", r.notes)
		self.assertFalse(r.icc_embedded)

	def test_bi_preserve_colorspace_notu(self):
		r = nrm.normalize(y.jpeg(64, 64), _spec(fmt="jpeg", colorspace="preserve"), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertIn("colorspace:preserved", r.notes)
		self.assertEqual(r.colorspace, "preserve")


# ══════════════════════════════════════════════════════════════════════
# 7. Ölçü ve upscale yasağı — uçtan uca
# ══════════════════════════════════════════════════════════════════════


class TestOlcuUctanUca(unittest.TestCase):
	def test_bi_kucultme_uygulanir_png(self):
		r = nrm.normalize(y.png(2000, 1000), _spec(fmt="png", max_long_edge=500), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (500, 250))
		self.assertTrue(r.resized)
		self.assertIn("resize:500x250", r.notes)

	def test_bi_jpeg_draft_yolunda_NOT_ile_BAYRAK_artik_tutarli(self):
		"""F-07 düzeltildi — küçültme gerçekten olduysa not da onu söylüyor.

		Önce: `resized=True` ama not `resize:none` (telemetri "küçültme yok"
		diye sayıyordu). Şimdi ikisi aynı şeyi söylüyor.
		"""
		r = nrm.normalize(y.jpeg(2000, 1000), _spec(fmt="jpeg", max_long_edge=500), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (500, 250))
		self.assertTrue(r.resized)
		self.assertIn("resize:500x250", r.notes, "F-07 geri geldi")
		self.assertNotIn("resize:none", r.notes)
		self.assertTrue(any(n.startswith("io:jpeg_decoder_draft:") for n in r.notes), r.notes)

	def test_bi_gercekten_kucultulmeyende_resize_none_kalir(self):
		"""Kontrast: küçültme yoksa not hâlâ `resize:none`."""
		r = nrm.normalize(y.jpeg(300, 200), _spec(fmt="jpeg", max_long_edge=4000), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertFalse(r.resized)
		self.assertIn("resize:none", r.notes)

	def test_bi_kucuk_kaynak_buyutulmez(self):
		r = nrm.normalize(y.jpeg(120, 90), _spec(fmt="jpeg", max_long_edge=4000, min_long_edge=2000), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertEqual((r.width, r.height), (120, 90))
		self.assertFalse(r.resized)
		self.assertIn("resize:none", r.notes)

	def test_bi_cikti_geri_acilabilir(self):
		for fmt in ("jpeg", "png", "webp"):
			with self.subTest(fmt=fmt):
				r = nrm.normalize(y.jpeg(300, 200), _spec(fmt=fmt), filename="a.jpg")
				self.assertTrue(r.ok, r.reason)
				with _ac(r.content) as im:
					self.assertEqual(im.size, (r.width, r.height))
					self.assertEqual((im.format or "").upper(), r.fmt)

	def test_bi_to_dict_sozlesmesi(self):
		d = nrm.normalize(y.jpeg(64, 64), _spec(fmt="jpeg"), filename="a.jpg").to_dict()
		for alan in ("ok", "fmt", "width", "height", "mode", "has_alpha", "colorspace",
					 "dpi", "dpi_written", "icc_embedded", "resized", "reason",
					 "notes", "applied_steps", "size_bytes"):
			self.assertIn(alan, d)

	def test_bi_applied_steps_notes_ile_ayni(self):
		r = nrm.normalize(y.jpeg(64, 64), _spec(fmt="jpeg"), filename="a.jpg")
		self.assertEqual(r.applied_steps, r.notes)


# ══════════════════════════════════════════════════════════════════════
# 8. Sınırlı ön-decode (libvips) — ortam bağımlı yol
# ══════════════════════════════════════════════════════════════════════


class TestSinirliOnDecode(unittest.TestCase):
	"""20 MP üstü non-JPEG kaynaklar libvips yoluna zorlanır.

	Bu ortamda `pyvips` KURULU DEĞİL (pyproject'te zorunlu beyan edilmiş
	olmasına rağmen). Testler eşiği düşürerek yolu küçük dosyayla tetikler;
	böylece 20 MP'lik gerçek raster üretmeye gerek kalmaz.
	"""

	def test_bi_esik_altinda_yol_tetiklenmez(self):
		r = nrm.normalize(y.png(400, 400), _spec(fmt="png", max_long_edge=100), filename="a.png")
		self.assertTrue(r.ok, r.reason)
		self.assertNotIn("io:bounded_decode_required", r.notes)

	def test_bi_jpeg_asla_bu_yola_girmez(self):
		with mock.patch.object(nrm, "BOUNDED_PREDECODE_MIN_MEGAPIXELS", 0.001):
			r = nrm.normalize(y.jpeg(800, 600), _spec(fmt="jpeg", max_long_edge=200), filename="a.jpg")
		self.assertTrue(r.ok, r.reason)
		self.assertNotIn("io:bounded_decode_required", r.notes)

	def test_gv_pyvips_yoksa_pillow_yoluna_SESSIZCE_dusmez(self):
		"""Sözleşme: libvips yoksa OOM riskli Pillow yoluna düşülmez, HATA döner."""
		with mock.patch.object(nrm, "BOUNDED_PREDECODE_MIN_MEGAPIXELS", 0.001), \
			mock.patch.object(nrm, "_load_pyvips", return_value=None):
			r = nrm.normalize(y.png(400, 400), _spec(fmt="png", max_long_edge=100), filename="a.png")
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, nrm.BOUNDED_DECODER_UNAVAILABLE)
		self.assertIn("io:pyvips_or_libvips_unavailable", r.notes)
		self.assertEqual(r.content, b"")

	def test_gv_preserve_colorspace_bounded_yolunda_desteklenmez(self):
		"""libvips VARMIŞ gibi davranıp sonraki kapıyı sınıyoruz.

		`_bounded_predecode` sırası: pyvips yokluğu → colorspace → hedef.
		Bu ortamda pyvips olmadığı için sonraki iki kapı ancak sahte bir
		decoder ile görülebilir; test o yüzden `_load_pyvips`'i sahteliyor.
		"""
		with mock.patch.object(nrm, "BOUNDED_PREDECODE_MIN_MEGAPIXELS", 0.001), \
			mock.patch.object(nrm, "_load_pyvips", return_value=mock.MagicMock()):
			r = nrm.normalize(
				y.png(400, 400), _spec(fmt="png", max_long_edge=100, colorspace="preserve"), filename="a.png"
			)
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, nrm.BOUNDED_COLORSPACE_UNSUPPORTED)

	def test_gv_hedef_kucultmuyorsa_bounded_reddedilir(self):
		"""Ara PNG tam ölçüde olursa Pillow yine tam raster kurar — yasak."""
		with mock.patch.object(nrm, "BOUNDED_PREDECODE_MIN_MEGAPIXELS", 0.001), \
			mock.patch.object(nrm, "_load_pyvips", return_value=mock.MagicMock()):
			r = nrm.normalize(y.png(400, 400), _spec(fmt="png"), filename="a.png")
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, nrm.BOUNDED_TARGET_NOT_REDUCED)

	def test_orm_pyvips_kurulu_mu(self):
		"""ORTAM KAYDI — `pyproject.toml` pyvips'i ZORUNLU bağımlılık sayıyor.

		Bu test ortamı kırmızıya çevirmez; kurulu değilse `skipTest` ile
		durumu rapora yazar. Üretimde kurulu olmalı: değilse 20 MP üstü her
		non-JPEG yükleme `bounded_decoder_unavailable` ile REDDEDİLİR.
		"""
		if nrm._load_pyvips() is None:
			self.skipTest(
				"pyvips/libvips bu ortamda YOK — 20 MP üstü non-JPEG normalizasyonu "
				"bu ortamda çalışmaz (pyproject.toml zorunlu beyan ediyor)"
			)


# ══════════════════════════════════════════════════════════════════════
# 9. Dayanıklılık — istisna sözleşmesi
# ══════════════════════════════════════════════════════════════════════


class TestDayaniklilik(unittest.TestCase):
	def test_gv_hicbir_girdide_istisna_atmaz(self):
		girdiler = [
			b"", b"\x00" * 10, y.elf(), y.svg(), y.svg(bom=True), y.sahte_docx(),
			y.jpeg_kesik(0.3), y.data_uri_metni(), y.pdf_ftyp_polyglot(),
			b"\x89PNG\r\n\x1a\n" + b"\xff" * 100,
		]
		for i, g in enumerate(girdiler):
			for skip in (False, True):
				with self.subTest(i=i, skip_guard=skip):
					r = nrm.normalize(g, _spec(), filename="x.bin", skip_guard=skip)
					self.assertIsInstance(r, nrm.NormalizeResult)
					if not r.ok:
						self.assertEqual(r.content, b"")
						self.assertTrue(r.reason)

	def test_gv_olmayan_yol_patlamaz(self):
		r = nrm.normalize("/olmayan/dizin/x.jpg", _spec(), filename="x.jpg")
		self.assertFalse(r.ok)
		self.assertEqual(r.reason, "empty")

	def test_bi_yol_ve_bayt_girdisi_ayni_sonucu_verir(self):
		import tempfile
		from pathlib import Path

		icerik = y.jpeg(600, 400, dpi=(300, 300))
		with tempfile.TemporaryDirectory() as d:
			yol = Path(d) / "a.jpg"
			yol.write_bytes(icerik)
			rb = nrm.normalize(icerik, _spec(fmt="jpeg"), filename="a.jpg")
			ry = nrm.normalize(yol, _spec(fmt="jpeg"))
		self.assertTrue(rb.ok and ry.ok, (rb.reason, ry.reason))
		self.assertEqual((rb.width, rb.height), (ry.width, ry.height))
		self.assertEqual(rb.fmt, ry.fmt)
		self.assertEqual(rb.dpi, ry.dpi)
		self.assertIn("io:bytes_source", rb.notes)
		self.assertIn("io:path_streamed", ry.notes)

	def test_bi_ayni_girdi_ayni_cikti_deterministik(self):
		"""Regresyon tabanı: aynı girdi + aynı spec → aynı bayt."""
		icerik = y.jpeg(320, 240)
		a = nrm.normalize(icerik, _spec(fmt="jpeg", quality=80), filename="a.jpg")
		b = nrm.normalize(icerik, _spec(fmt="jpeg", quality=80), filename="a.jpg")
		self.assertTrue(a.ok and b.ok)
		self.assertEqual(a.content, b.content, "normalize deterministik olmalı")


if __name__ == "__main__":
	unittest.main()
