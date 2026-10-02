"""Mağaza görselleri: WebP master, oran + şeffaflık korunur (2026-09-30).

Taşıma (301, arşiv, referans, geri alma) `kare.py` ile ORTAK; burada mağaza
kuralı (`magaza_gorseli.KURAL`) ve mağazaya özgü kancalar sınanır.
"""

import hashlib
import io
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.api import media_manifest
from tradehub_core.media import archive, kare, magaza_gorseli, retro_rename
from tradehub_core.media.pipeline.image import dpi as dpi_mod
from tradehub_core.media.pipeline.image import facts as facts_mod

# AV bekletmesi dosyayı public ağaçtan çıkarmasın (bkz. tests/av_notr.py).
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


def _png_rgba(w, h, alfa=0, renk=(200, 30, 30)):
	im = Image.new("RGBA", (w, h), (*renk, alfa))
	# Ortada opak bir blok: görünür içerik + gerçek şeffaflık birlikte.
	im.paste(Image.new("RGBA", (w // 2, h // 2), (*renk, 255)), (w // 4, h // 4))
	buf = io.BytesIO()
	im.save(buf, "PNG")
	return buf.getvalue()


def _webp(w, h):
	buf = io.BytesIO()
	Image.new("RGB", (w, h), (10, 20, 30)).save(buf, "WEBP", quality=80)
	return buf.getvalue()


class TestWebpCevir(FrappeTestCase):
	def test_seffaflik_ve_oran_korunur_dolgu_yok(self):
		veri, (w, h) = magaza_gorseli.webp_cevir(_png_rgba(1046, 523))
		self.assertEqual((w, h), (1046, 523))
		im = Image.open(io.BytesIO(veri))
		self.assertEqual(im.format, "WEBP")
		self.assertEqual(im.mode, "RGBA")
		self.assertEqual(im.size, (1046, 523))
		# Köşe şeffaf kaldı (beyaz zemine düzlenmedi).
		self.assertEqual(im.getpixel((0, 0))[3], 0)

	def test_uzun_kenar_2000_buyutme_yok(self):
		_veri, olcu = magaza_gorseli.webp_cevir(_png_rgba(4000, 1000))
		self.assertEqual(olcu, (2000, 500))
		_veri, olcu = magaza_gorseli.webp_cevir(_png_rgba(300, 120))
		self.assertEqual(olcu, (300, 120))  # küçük logo büyütülmez

	def test_opak_alfa_rgbye_iner(self):
		veri, _olcu = magaza_gorseli.webp_cevir(_png_rgba(400, 400, alfa=255))
		self.assertEqual(Image.open(io.BytesIO(veri)).mode, "RGB")

	def test_kunye_dpi_ve_srgb(self):
		veri, _olcu = magaza_gorseli.webp_cevir(_png_rgba(600, 300))
		self.assertEqual(round(float(dpi_mod.read_dpi(veri).dpi[0])), 72)
		olcum = facts_mod.measure(veri)
		self.assertTrue(olcum.ok)
		self.assertIn("srgb", str(olcum.to_dict()).lower())

	def test_zaten_webp_ve_2000_alti_atlanir(self):
		with self.assertRaises(kare.Atla) as ctx:
			magaza_gorseli.webp_cevir(_webp(1200, 400))
		self.assertEqual(ctx.exception.reason, "already_webp")
		self.assertTrue(magaza_gorseli.hazir_mi(1200, 400, "WEBP"))
		self.assertFalse(magaza_gorseli.hazir_mi(2400, 400, "WEBP"))
		self.assertFalse(magaza_gorseli.hazir_mi(1200, 400, "PNG"))


class TestKapsam(FrappeTestCase):
	def _ref(self, kind, readonly=False):
		return {"kind": kind, "readonly": readonly}

	def test_yalniz_magaza_kaynaklari(self):
		with mock.patch.object(
			magaza_gorseli.refs, "find", return_value=[self._ref("seller_logo"), self._ref("storefront")]
		):
			self.assertEqual(magaza_gorseli.magaza_gorseli_mi("/files/x.png"), (True, False))

	def test_urunde_de_kullaniliyorsa_magaza_degil(self):
		with mock.patch.object(
			magaza_gorseli.refs,
			"find",
			return_value=[self._ref("seller_logo"), self._ref("listing_main")],
		):
			self.assertEqual(magaza_gorseli.magaza_gorseli_mi("/files/x.png")[0], False)

	def test_siparis_kopyasi_isaretlenir(self):
		with mock.patch.object(
			magaza_gorseli.refs,
			"find",
			return_value=[self._ref("seller_banner"), self._ref("order_item_image", readonly=True)],
		):
			self.assertEqual(magaza_gorseli.magaza_gorseli_mi("/files/x.png"), (True, True))


class TestTasimaVeGeriAlma(FrappeTestCase):
	"""Kare taşıma katmanı mağaza kuralıyla: yeni adres, 301, arşiv, geri alma."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.sfx = frappe.generate_hash(length=8)
		self.job = f"kare-test-mg-{self.sfx}"
		self.addCleanup(self._temizle)

	def _dosya(self):
		renk = tuple(hashlib.sha1(f"{self.id()}-{self.sfx}".encode()).digest()[:3])
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"magaza-{self.sfx}.png",
				"is_private": 0,
				"content": _png_rgba(900, 300, renk=renk),
			}
		).insert(ignore_permissions=True)
		self.url = doc.file_url
		return doc

	def _temizle(self):
		frappe.db.rollback()
		for row in frappe.get_all(
			"Media URL Redirect", filters={"job_key": self.job}, fields=["name", "source_url"]
		):
			frappe.delete_doc("Media URL Redirect", row.name, force=True, ignore_permissions=True)
			archive.drop(row.source_url)
		if getattr(self, "url", None):
			archive.drop(self.url)
		for ad in frappe.get_all(
			"File", filters={"file_name": ["like", f"magaza-{self.sfx}%"]}, pluck="name"
		):
			frappe.delete_doc("File", ad, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_cevirir_301_arsiv_ve_geri_alir(self):
		doc = self._dosya()
		eski = doc.file_url
		with (
			mock.patch.object(magaza_gorseli, "magaza_gorseli_mi", return_value=(True, False)),
			mock.patch.object(kare, "_turevleri_tetikle"),
		):
			out = kare.normalize_one(eski, self.job, None, kural=magaza_gorseli.KURAL)
		self.assertEqual(out["status"], "converted", out)
		yeni = out["target_url"]
		self.assertTrue(yeni.endswith(".webp"))
		satir = frappe.db.get_value(
			"File", doc.name, ["file_url", "th_media_width", "th_media_height"], as_dict=True
		)
		self.assertEqual(satir.file_url, yeni)
		# Oran korunur: kare DEĞİL.
		self.assertEqual((satir.th_media_width, satir.th_media_height), (900, 300))
		with Image.open(retro_rename._disk_path(yeni)) as im:
			self.assertEqual((im.format, im.mode, im.size), ("WEBP", "RGBA", (900, 300)))
		self.assertTrue(archive.exists(eski))
		self.assertFalse(os.path.isfile(retro_rename._disk_path(eski)))
		row = frappe.get_all(
			"Media URL Redirect",
			filters={"source_url": eski},
			fields=["name", "source_url", "target_url", "file_names", "ref_changes", "job_key"],
		)[0]
		self.assertEqual(row.job_key, self.job)

		sonuc = kare.rollback_one(row)
		self.assertTrue(sonuc["ok"], sonuc)
		self.assertEqual(frappe.db.get_value("File", doc.name, "file_url"), eski)
		self.assertTrue(os.path.isfile(retro_rename._disk_path(eski)))
		self.assertFalse(frappe.db.exists("Media URL Redirect", row.name))

	def test_magaza_disi_dosyaya_dokunmaz(self):
		doc = self._dosya()
		with mock.patch.object(magaza_gorseli, "magaza_gorseli_mi", return_value=(False, False)):
			out = kare.normalize_one(doc.file_url, self.job, None, kural=magaza_gorseli.KURAL)
		self.assertEqual((out["status"], out["reason"]), ("skipped", "not_store_image"))
		self.assertEqual(frappe.db.get_value("File", doc.name, "file_url"), doc.file_url)

	def test_prova_yazmaz(self):
		doc = self._dosya()
		with mock.patch.object(magaza_gorseli, "magaza_gorseli_mi", return_value=(True, False)):
			out = kare.normalize_one(doc.file_url, self.job, None, dry_run=True, kural=magaza_gorseli.KURAL)
		self.assertEqual((out["status"], out["reason"]), ("converted", "dry_run"))
		self.assertEqual(frappe.db.get_value("File", doc.name, "file_url"), doc.file_url)
		self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": doc.file_url}))


class TestKancalar(FrappeTestCase):
	def test_logo_degisince_kuyruga(self):
		doc = frappe.new_doc("Admin Seller Profile")
		doc.name = "SEL-TEST-MG"
		doc.logo = "/files/ab/abc.png"
		with mock.patch.object(magaza_gorseli, "enqueue_seller") as kuyruk:
			magaza_gorseli.on_seller_profile_update(doc)
		kuyruk.assert_called_once_with("SEL-TEST-MG")

	def test_degismeyince_kuyruga_girmez(self):
		doc = frappe.new_doc("Admin Seller Profile")
		doc.logo = "/files/ab/abc.png"
		onceki = frappe.new_doc("Admin Seller Profile")
		onceki.logo = "/files/ab/abc.png"
		with (
			mock.patch.object(doc, "get_doc_before_save", return_value=onceki),
			mock.patch.object(magaza_gorseli, "enqueue_seller") as kuyruk,
		):
			magaza_gorseli.on_seller_profile_update(doc)
		kuyruk.assert_not_called()

	def test_kill_switch_ve_test_bayragi(self):
		frappe.conf[magaza_gorseli.KILL_SWITCH] = 1
		self.addCleanup(lambda: frappe.conf.pop(magaza_gorseli.KILL_SWITCH, None))
		with mock.patch.object(frappe, "enqueue") as kuyruk:
			self.assertFalse(magaza_gorseli.enqueue_seller("SEL-X"))
		kuyruk.assert_not_called()

	def test_bayat_form_301_hedefine_cevrilir(self):
		kaynak = f"/files/zz/eski-{frappe.generate_hash(length=6)}.png"
		hedef = "/files/zz/yeni.webp"
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": kaynak,
				"target_url": hedef,
				"job_key": "kare-test-mg-hook",
				"expires_at": frappe.utils.add_days(frappe.utils.now_datetime(), 3),
			}
		).insert(ignore_permissions=True)
		doc = frappe.new_doc("Admin Seller Profile")
		doc.logo = kaynak
		doc.append("gallery_images", {"image": kaynak})
		magaza_gorseli.yonlendirilmis_gorselleri_esle(doc)
		self.assertEqual(doc.logo, hedef)
		self.assertEqual(doc.gallery_images[0].image, hedef)
		vitrin = frappe.new_doc("Storefront Layout")
		vitrin.sections = frappe.as_json([{"settings": {"slides": [{"image": kaynak}]}}])
		magaza_gorseli.vitrin_yonlendirmelerini_esle(vitrin)
		self.assertIn(hedef, vitrin.sections)
		self.assertNotIn(kaynak, vitrin.sections)
		frappe.db.rollback()

	def test_json_adresleri_ic_ice(self):
		adresler: set[str] = set()
		magaza_gorseli._json_adresleri(
			frappe.as_json([{"settings": {"slides": [{"image": "/files/a/b.jpg"}, {"image": "https://x"}]}}]),
			adresler,
		)
		self.assertEqual(adresler, {"/files/a/b.jpg"})


def _sahte_manifest(slot, url, turevler, **_kw):
	return {
		"src": turevler[-1]["file_url"],
		"width": turevler[-1]["width"],
		"height": turevler[-1]["height"],
		"sources": [
			{
				"type": f"image/{turevler[0]['format']}",
				"srcset": ", ".join(f"{t['file_url']} {t['width']}w" for t in turevler),
			}
		],
	}


class TestVitrinMedyasi(FrappeTestCase):
	def test_bayrak_kapaliyken_bos(self):
		with mock.patch.object(media_manifest, "_bayrak_acik", return_value=False):
			self.assertEqual(media_manifest.magaza_gorsel_medyasi([("/files/a.png", "seller.logo", "S")]), {})

	def test_yalniz_webp_turev_ve_ozel_dosya_yok(self):
		turevler = [
			{
				"profile": "w64",
				"format": "webp",
				"file_url": "/files/media/a/v/w64-64.webp",
				"width": 64,
				"height": 32,
				"benefit_gate_passed": 1,
			},
			{
				"profile": "w64",
				"format": "avif",
				"file_url": "/files/media/a/v/w64-64.avif",
				"width": 64,
				"height": 32,
				"benefit_gate_passed": 1,
			},
		]
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=True),
			mock.patch.object(
				media_manifest,
				"_varliklari_getir",
				return_value={"/files/a.png": {"S": {"name": "A1", "active_version": "v"}}},
			),
			mock.patch.object(media_manifest, "_turevleri_getir", return_value={"A1": turevler}),
			mock.patch.object(media_manifest, "_render_manifest", side_effect=_sahte_manifest) as rm,
		):
			sonuc = media_manifest.magaza_gorsel_medyasi(
				[("/files/a.png", "seller.logo", "S"), ("/private/files/b.png", "seller.logo", "S")]
			)
		self.assertEqual(set(sonuc), {("/files/a.png", "seller.logo")})
		govde = sonuc[("/files/a.png", "seller.logo")]
		self.assertIn("w64-64.webp 64w", govde["srcset"])
		self.assertNotIn("avif", govde["srcset"])
		# Manifest kurucusuna yalnız WebP türevler gider.
		self.assertEqual({t["format"] for t in rm.call_args.args[2]}, {"webp"})

	def test_ekle_turev_yoksa_none(self):
		kayit = {"logo": "/files/a.png", "name": "S"}
		with mock.patch.object(media_manifest, "magaza_gorsel_medyasi", return_value={}):
			media_manifest.magaza_medyasi_ekle([kayit], {"logo": "seller.logo"}, "name")
		self.assertIsNone(kayit["logo_media"])
