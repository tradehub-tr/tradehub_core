# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""Görsel künyesi (DPI · renk uzayı · alfa) — ölçüm, kodlayıcılar ve panel ucu.

Kalite sekmesi bu üç satırı "—" ile gösteriyordu. Artık:
  * kaynak dosya `File.th_media_*` alanlarında (ölçüm: `media/image_facts.py`),
  * türev `Media Rendition.output_*` alanlarında,
  * ikisi de `manifest_batch` yanıtında (`source` ve türev satırı) taşınır.

Sınanan sözleşme: değerler DOSYADAN okunur, varsayılan ölçüm gibi yazılmaz
(DPI'sız dosya 0 döner, etiketsiz RGB "RGB" döner — "72"/"sRGB" değil) ve
yeni kodlayıcılar (kare master + türev) DPI'yı ve sRGB profilini dosyaya
GERÇEKTEN yazar.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_image_facts
"""

from __future__ import annotations

import io
from fractions import Fraction

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image, ImageCms

from tradehub_core.api import media_manifest
from tradehub_core.media import image_facts, kare
from tradehub_core.media.pipeline.image import facts as facts_mod
from tradehub_core.media.pipeline.image import render

# AV kancası nötr (bkz. tests/av_notr.py) — ManifestBatch fixture'ları diske yazar.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401
from tradehub_core.tests.test_manifest_batch import ManifestBatchTestBase
from tradehub_core.tests.test_media_access_level import _write_public_file

SRGB_ICC = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def _resolution_exif(dpi: int) -> bytes:
	exif = Image.Exif()
	exif[0x011A] = Fraction(dpi, 1)
	exif[0x011B] = Fraction(dpi, 1)
	exif[0x0128] = 2
	return exif.tobytes()


def _img(mode: str = "RGB", fmt: str = "PNG", size=(40, 30), **save_kw) -> bytes:
	renk = {"RGB": (200, 20, 20), "RGBA": (200, 20, 20, 128), "CMYK": (0, 200, 200, 0), "L": 128}
	im = Image.new(mode, size, renk.get(mode, 0))
	buf = io.BytesIO()
	im.save(buf, fmt, **save_kw)
	return buf.getvalue()


class ImageFactsMeasureTests(FrappeTestCase):
	"""Saf ölçüm — `facts.measure` dosyanın SÖYLEDİĞİNİ döner, fazlasını değil."""

	def test_webp_exif_dpi_ve_srgb_profili_okunur(self):
		veri = _img(fmt="WEBP", exif=_resolution_exif(300), icc_profile=SRGB_ICC)
		olcum = facts_mod.measure(veri)
		self.assertTrue(olcum.ok)
		self.assertEqual(olcum.dpi, 300)
		self.assertEqual(olcum.colorspace, "sRGB")
		self.assertFalse(olcum.has_alpha)

	def test_etiketsiz_dpisiz_dosyaya_varsayilan_yazilmaz(self):
		"""Bugünkü kare WebP master'ların hâli: ne DPI ne ICC — 0 ve "RGB" döner."""
		olcum = facts_mod.measure(_img(fmt="WEBP"))
		self.assertTrue(olcum.ok)
		self.assertEqual(olcum.dpi, 0)
		self.assertEqual(olcum.colorspace, "RGB")
		self.assertFalse(olcum.icc)

	def test_jpeg_konteyner_dpi_ve_cmyk(self):
		olcum = facts_mod.measure(_img("CMYK", "JPEG", dpi=(150, 150)))
		self.assertEqual((olcum.dpi, olcum.colorspace), (150, "CMYK"))

	def test_gri_ve_alfa(self):
		self.assertEqual(facts_mod.measure(_img("L")).colorspace, "Gray")
		self.assertTrue(facts_mod.measure(_img("RGBA")).has_alpha)
		p = Image.new("P", (10, 10))
		p.info["transparency"] = 0
		buf = io.BytesIO()
		p.save(buf, "PNG", transparency=0)
		self.assertTrue(facts_mod.measure(buf.getvalue()).has_alpha)

	def test_okunamayan_dosya_ok_false(self):
		olcum = facts_mod.measure(b"bu bir gorsel degil")
		self.assertFalse(olcum.ok)
		self.assertTrue(olcum.reason)

	def test_icc_adlari_kanonik(self):
		self.assertEqual(facts_mod.icc_name(SRGB_ICC), "sRGB")
		self.assertEqual(facts_mod.icc_name(b"bozuk"), "")


class EncoderWritesFactsTests(FrappeTestCase):
	"""Yeni kodlayıcılar künyeyi dosyaya GERÇEKTEN yazar (geri okunarak sınanır)."""

	def test_kare_webp_kaynak_dpisini_ve_srgb_profilini_tasir(self):
		kaynak = _img(fmt="JPEG", size=(1200, 800), dpi=(300, 300))
		webp, kenar = kare.kareye_cevir(kaynak)
		olcum = facts_mod.measure(webp)
		self.assertEqual(kenar, 1200)
		self.assertEqual((olcum.dpi, olcum.colorspace, olcum.has_alpha), (300, "sRGB", False))

	def test_kare_dpisiz_kaynakta_72_yazar(self):
		webp, _ = kare.kareye_cevir(_img(fmt="PNG", size=(1100, 900)))
		self.assertEqual(facts_mod.measure(webp).dpi, 72)

	def test_render_encode_dpi_ve_profil(self):
		im = Image.new("RGB", (64, 64), (10, 120, 200))
		for fmt in ("webp", "jpeg", "png"):
			veri, _ = render.encode(im, fmt, 80 if fmt != "png" else 100, dpi=96)
			olcum = facts_mod.measure(veri)
			self.assertEqual((olcum.dpi, olcum.colorspace), (96, "sRGB"), fmt)

	def test_render_politika_icc_silerse_srgb_gomulmez(self):
		im = Image.new("RGB", (32, 32), (10, 120, 200))
		veri, _ = render.encode(im, "webp", 80, icc=b"", dpi=72)
		olcum = facts_mod.measure(veri)
		self.assertFalse(olcum.icc)
		self.assertEqual(olcum.dpi, 72)

	def test_render_rendition_kaynak_dpisini_kopyalar(self):
		kaynak = _img(fmt="JPEG", size=(900, 900), dpi=(200, 200))
		profil = render.profile_for("product.image", "w384")
		sonuc = render.render_rendition(
			kaynak, profil, fmt="webp", require_format=True, allow_passthrough=False
		)
		olcum = facts_mod.measure(sonuc.content)
		self.assertEqual((olcum.dpi, olcum.colorspace), (200, "sRGB"))


class ManifestBatchFactsTests(ManifestBatchTestBase):
	"""`manifest_batch` kaynak ve türev künyesini taşır; yoksa uydurmaz."""

	def _gorsel_dosya(self, email: str, veri: bytes) -> frappe._dict:
		ad = f"{frappe.generate_hash(length=10)}.webp"
		url = _write_public_file(ad, veri)
		self._cleanup_both_locations(ad)
		doc = frappe.get_doc({"doctype": "File", "file_name": ad, "file_url": url, "is_private": 0})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.set_value("File", doc.name, "owner", email, update_modified=False)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", doc.name))
		return doc

	def test_kaynak_kunyesi_dosyadan_olculur_ve_saklanir(self):
		veri = _img(fmt="WEBP", exif=_resolution_exif(300), icc_profile=SRGB_ICC)
		dosya = self._gorsel_dosya(self.a.email, veri)
		self._as_seller(self.a)

		man = media_manifest.manifest_batch([dosya.name])["manifests"][dosya.name]

		self.assertEqual(
			man["source"], {"status": "ok", "dpi": 300, "colorspace": "sRGB", "has_alpha": False}
		)
		sakli = frappe.db.get_value("File", dosya.name, list(image_facts.FILE_FIELDS), as_dict=True)
		self.assertEqual(sakli.th_media_facts, "ok")
		self.assertEqual((sakli.th_media_dpi, sakli.th_media_colorspace), (300, "sRGB"))

	def test_gorsel_olmayan_dosyada_source_none(self):
		self._as_seller(self.a)
		man = media_manifest.manifest_batch([self.a.public_file])["manifests"][self.a.public_file]
		self.assertIn("source", man)
		self.assertIsNone(man["source"])  # fixture .txt — ölçülecek görsel yok

	def test_turev_satiri_cikti_kunyesini_tasir(self):
		"""Diskte olan türev ölçülür; diskte olmayan boş kalır (değer uydurulmaz)."""
		veri = _img(fmt="WEBP", size=(64, 64), exif=_resolution_exif(72), icc_profile=SRGB_ICC)
		ad = f"{frappe.generate_hash(length=10)}.webp"
		url = _write_public_file(ad, veri)
		self._cleanup_both_locations(ad)
		turev = frappe.get_doc(
			{
				"doctype": "Media Rendition",
				"asset": self.a.public_asset,
				"profile": "w1280",
				"width": 1280,
				"height": 1280,
				"format": "webp",
				"file_url": url,
				"bytes": len(veri),
				"benefit_gate_passed": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Media Rendition", turev.name))
		self._as_seller(self.a)

		man = media_manifest.manifest_batch([self.a.public_file])["manifests"][self.a.public_file]
		satirlar = {t["file_url"]: t for t in man["renditions"]}

		olculen = satirlar[url]
		self.assertEqual(
			(olculen["output_dpi"], olculen["output_colorspace"], olculen["output_has_alpha"]),
			(72, "sRGB", 0),
		)
		# Fixture'ın diğer türevleri diskte YOK → ölçüm yok, alan boş.
		for kayip in self.a.public_rendition_urls:
			self.assertFalse(satirlar[kayip]["output_colorspace"])
