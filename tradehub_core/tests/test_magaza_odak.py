"""Mağaza `*_media` gövdelerinde `focal` (2026-10-01).

    docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
        bench --site istoc.localhost run-tests --module tradehub_core.tests.test_magaza_odak"
"""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_manifest
from tradehub_core.media import odak

URL = "/files/c2/odak-test.webp"
SLOT = "company.cover_image"
ODAK = {"x": 0.78, "y": 0.45}


def _govde(url, slot, turevler):
	return {"src": url, "srcset": f"{url} 640w", "width": 640, "height": 131}


class MagazaOdakTests(FrappeTestCase):
	def test_turevli_govdeye_focal_eklenir(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=True),
			mock.patch.object(
				media_manifest,
				"_varliklari_getir",
				return_value={URL: {"S": {"name": "A1", "active_version": "v"}}},
			),
			mock.patch.object(media_manifest, "_turevleri_getir", return_value={"A1": [{}]}),
			mock.patch.object(media_manifest, "_magaza_govdesi", side_effect=_govde),
			mock.patch.object(odak, "odaklar", return_value={(URL, "S"): ODAK}),
		):
			sonuc = media_manifest.magaza_gorsel_medyasi([(URL, SLOT, "S")])
		self.assertEqual(sonuc[(URL, SLOT)]["focal"], ODAK)
		self.assertEqual(sonuc[(URL, SLOT)]["srcset"], f"{URL} 640w")

	def test_bayrak_kapaliyken_yalniz_odak_govdesi(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={(URL, "S"): ODAK}),
		):
			sonuc = media_manifest.magaza_gorsel_medyasi([(URL, SLOT, "S")])
		self.assertEqual(
			sonuc[(URL, SLOT)], {"src": URL, "srcset": "", "width": 0, "height": 0, "focal": ODAK}
		)

	def test_odak_yoksa_bugunku_davranis(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={}),
		):
			self.assertEqual(media_manifest.magaza_gorsel_medyasi([(URL, SLOT, "S")]), {})

	def test_ozel_dosyanin_odagi_vitrine_gomulmez(self):
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={("/private/files/x.png", "S"): ODAK}) as cagri,
		):
			sonuc = media_manifest.magaza_gorsel_medyasi([("/private/files/x.png", SLOT, "S")])
		self.assertEqual(sonuc, {})
		self.assertEqual(list(cagri.call_args.args[0]), [])

	def test_ekle_alana_focal_tasir(self):
		kayit = {"banner_image": URL, "name": "S"}
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={(URL, "S"): ODAK}),
		):
			media_manifest.magaza_medyasi_ekle([kayit], {"banner_image": SLOT}, "name")
		self.assertEqual(kayit["banner_image_media"]["focal"], ODAK)

	def test_cok_saticili_cagri_dogru_cifleri_gecirir(self):
		kayitlar = [{"banner_image": URL, "name": "A"}, {"banner_image": URL, "name": "B"}]
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={}) as cagri,
		):
			media_manifest.magaza_medyasi_ekle(kayitlar, {"banner_image": SLOT}, "name")
		self.assertEqual(sorted(cagri.call_args.args[0]), [(URL, "A"), (URL, "B")])

	def test_ayni_url_slot_iki_satici_odak_baskasina_sizmaz(self):
		kayitlar = [{"banner_image": URL, "name": "A"}, {"banner_image": URL, "name": "B"}]
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={(URL, "A"): ODAK}),
		):
			media_manifest.magaza_medyasi_ekle(kayitlar, {"banner_image": SLOT}, "name")
		self.assertEqual(kayitlar[0]["banner_image_media"]["focal"], ODAK)
		self.assertIsNone(kayitlar[1]["banner_image_media"])

	def test_ayni_url_turevli_govde_ortak_dict_degil(self):
		kayitlar = [{"banner_image": URL, "name": "A"}, {"banner_image": URL, "name": "B"}]
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=True),
			mock.patch.object(
				media_manifest,
				"_varliklari_getir",
				return_value={URL: {"A": {"name": "A1", "active_version": "v"}}},
			),
			mock.patch.object(media_manifest, "_turevleri_getir", return_value={"A1": [{}]}),
			mock.patch.object(media_manifest, "_magaza_govdesi", side_effect=_govde),
			mock.patch.object(odak, "odaklar", return_value={(URL, "A"): ODAK}),
		):
			media_manifest.magaza_medyasi_ekle(kayitlar, {"banner_image": SLOT}, "name")
		self.assertEqual(kayitlar[0]["banner_image_media"]["focal"], ODAK)
		self.assertNotIn("focal", kayitlar[1]["banner_image_media"])

	def test_gercek_db_b_saticinin_odagi_a_kaydina_donmez(self):
		url = "/files/c2/odak-gercek-db.webp"
		# Test verisi: diskte dosya yok; `db_insert` File denetimlerini atlar, tearDown rollback eder.
		dosya = frappe.get_doc(
			{"doctype": "File", "name": "odak-gercek-db", "file_name": "odak-gercek-db.webp", "file_url": url}
		)
		dosya.db_insert()
		varlik = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": SLOT,
				"media_type": "image",
				"state": "ready",
				"owner_seller": "SELLER-B-ODAK",
				"source_file": dosya.name,
			}
		)
		varlik.insert(ignore_permissions=True, ignore_links=True)
		frappe.get_doc(
			{"doctype": "Media Crop Intent", "asset": varlik.name, "focal_x": 0.2, "focal_y": 0.9}
		).insert(ignore_permissions=True, ignore_links=True)
		sonuc = odak.odaklar([(url, "SELLER-A-ODAK"), (url, "SELLER-B-ODAK")])
		self.assertNotIn((url, "SELLER-A-ODAK"), sonuc)
		self.assertEqual(sonuc[(url, "SELLER-B-ODAK")], {"x": 0.2, "y": 0.9})
		with mock.patch.object(media_manifest, "_bayrak_acik", return_value=False):
			a = media_manifest.magaza_gorsel_medyasi_saticili([(url, SLOT, "SELLER-A-ODAK")])
			b = media_manifest.magaza_gorsel_medyasi_saticili([(url, SLOT, "SELLER-B-ODAK")])
		self.assertEqual(a, {})
		self.assertEqual(b[(url, SLOT, "SELLER-B-ODAK")]["focal"], {"x": 0.2, "y": 0.9})

	def test_satici_karti_iki_satici_ayni_url_kendi_odagini_alir(self):
		from tradehub_core.api import seller

		diger = {"x": 0.1, "y": 0.2}
		saticilar = [
			{"name": "A", "logo": URL, "gallery_images": [URL]},
			{"name": "B", "logo": URL, "gallery_images": [URL]},
			{"name": "C", "logo": URL, "gallery_images": []},
		]
		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=False),
			mock.patch.object(odak, "odaklar", return_value={(URL, "A"): ODAK, (URL, "B"): diger}) as cagri,
		):
			seller._satici_kart_medyasi(saticilar)
		a, b, c = saticilar
		self.assertEqual(a["logo_media"]["focal"], ODAK)
		self.assertEqual(b["logo_media"]["focal"], diger)
		self.assertIsNone(c["logo_media"])
		self.assertEqual(a["gallery_images_media"][0]["focal"], ODAK)
		self.assertEqual(b["gallery_images_media"][0]["focal"], diger)
		self.assertEqual(sorted(cagri.call_args.args[0]), [(URL, "A"), (URL, "B"), (URL, "C")])

	def test_vitrin_kucuk_harfli_slug_kendi_varligini_ve_odagini_alir(self):
		"""Vitrin URL'si küçük harfli slug gönderir (`sel-00020`); kayıt kodu büyük harfli.

		MariaDB `exists`'i büyük/küçük harf duyarsız eşleştiriyor, ama Python
		sözlükleri duyarlı: ham slug ile satıcının kendi varlığı/odağı bulunamaz
		ve başka satıcının türevi basılırdı (final review C-1).
		"""
		from tradehub_core.api import seller

		kod = "ODAK-SLUG-01"
		url = "/files/c2/odak-slug-test.webp"
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"name": kod,
				"seller_code": kod,
				"seller_name": "Odak Slug Mağazası",
				"user": "odak-slug@example.com",
				"email": "odak-slug@example.com",
			}
		).db_insert()
		bolumler = [{"type": "hero_banner", "config": {"slides": [{"image": url}]}}]
		frappe.get_doc(
			{
				"doctype": "Storefront Layout",
				"name": kod,
				"seller_profile": kod,
				"is_published": 1,
				"sections": frappe.as_json(bolumler),
			}
		).db_insert()
		dosya = frappe.get_doc(
			{"doctype": "File", "name": "odak-slug-test", "file_name": "odak-slug-test.webp", "file_url": url}
		)
		dosya.db_insert()

		def _varlik(sahip):
			v = frappe.get_doc(
				{
					"doctype": "Media Asset",
					"slot_key": SLOT,
					"media_type": "image",
					"state": "ready",
					"owner_seller": sahip,
					"source_file": dosya.name,
				}
			)
			v.insert(ignore_permissions=True, ignore_links=True)
			return v.name

		yabanci = _varlik("ODAK-YABANCI-01")
		kendi = _varlik(kod)
		frappe.get_doc(
			{"doctype": "Media Crop Intent", "asset": kendi, "focal_x": 0.78, "focal_y": 0.45}
		).insert(ignore_permissions=True, ignore_links=True)

		def _govde_varlikli(u, slot, turevler):
			return {
				"src": u,
				"srcset": f"/files/media/{turevler[0]['asset']}/640.webp 640w",
				"width": 640,
				"height": 131,
			}

		with (
			mock.patch.object(media_manifest, "_bayrak_acik", return_value=True),
			mock.patch.object(
				media_manifest,
				"_turevleri_getir",
				side_effect=lambda adlar, _s: {a: [{"asset": a}] for a in adlar},
			),
			mock.patch.object(media_manifest, "_magaza_govdesi", side_effect=_govde_varlikli),
		):
			kucuk = seller.get_storefront_layout(seller_code=kod.lower())
			buyuk = seller.get_storefront_layout(seller_code=kod)
		self.assertEqual(kucuk["image_media"], buyuk["image_media"])
		govde = kucuk["image_media"][url]
		self.assertEqual(govde["focal"], {"x": 0.78, "y": 0.45})
		self.assertIn(kendi, govde["srcset"])
		self.assertNotIn(yabanci, govde["srcset"])

	def tearDown(self):
		frappe.db.rollback()
