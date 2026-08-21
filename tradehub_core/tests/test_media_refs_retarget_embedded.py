"""`refs.retarget` gömülü referans desteği (retro-rename için).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_refs_retarget_embedded
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import refs


class TestRetargetEmbedded(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.old = f"/files/rr-emb-{frappe.generate_hash(length=8)}.jpg"
		self.new = "/files/ab/" + "c" * 32 + ".jpg"
		self.seller = self._make_seller()

	def _make_seller(self) -> str:
		store = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": f"Retarget Embedded Satici {frappe.generate_hash(length=8)}",
				"seller_code": frappe.generate_hash(length=10),
				"status": "Active",
			}
		)
		store.flags.ignore_mandatory = True
		store.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("Admin Seller Profile", store.name, force=True, ignore_permissions=True)
		)
		return store.name

	def _layout(self, sections) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Storefront Layout",
				"seller_profile": self.seller,
				"sections": json.dumps(sections, ensure_ascii=True),
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("Storefront Layout", doc.name, force=True, ignore_permissions=True)
		)
		return doc.name

	def test_json_icindeki_adres_degistirilir(self):
		name = self._layout([{"type": "gallery", "image": self.old}, {"type": "company_info", "body": "x"}])
		out = refs.retarget(self.old, self.new)
		data = json.loads(frappe.db.get_value("Storefront Layout", name, "sections"))
		self.assertEqual(data[0]["image"], self.new)
		self.assertEqual(out["total"], 1)
		self.assertFalse(out["skipped"])

	def test_json_kacisli_yazim_da_degistirilir(self):
		old_tr = "/files/rr-ı-" + frappe.generate_hash(length=6) + ".jpg"
		name = self._layout([{"type": "gallery", "image": old_tr}])  # ensure_ascii → ı
		refs.retarget(old_tr, self.new)
		self.assertEqual(
			json.loads(frappe.db.get_value("Storefront Layout", name, "sections"))[0]["image"], self.new
		)

	def test_bozuk_json_atlanir(self):
		doc = frappe.get_doc({"doctype": "Storefront Layout", "seller_profile": self.seller})
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("Storefront Layout", doc.name, force=True, ignore_permissions=True)
		)
		# `sections` MariaDB'de `longtext ... CHECK (json_valid(...))` — bozuk
		# JSON'u yazabilmek için CHECK constraint'i bu oturumda geçici kapatılır.
		# Prod'da bu satır asla bozulamaz; test yalnız `_replace_embedded`'in
		# beklenmedik biçimde bozuk bir metinle karşılaşırsa çökmediğini kanıtlar.
		frappe.db.sql("SET SESSION check_constraint_checks=OFF")
		frappe.db.set_value(
			"Storefront Layout", doc.name, "sections", '{"image": "' + self.old + '"', update_modified=False
		)
		frappe.db.sql("SET SESSION check_constraint_checks=ON")
		out = refs.retarget(self.old, self.new)
		self.assertEqual(out["total"], 0)
		self.assertTrue(any("gömülü" in s for s in out["skipped"]))
		self.assertIn(self.old, frappe.db.get_value("Storefront Layout", doc.name, "sections"))


class TestReplaceEmbeddedText(FrappeTestCase):
	"""`_replace_embedded`'in düz-metin (JSON olmayan) dalı — saf fonksiyon,
	DB'ye dokunmaz. Sınır-farkında değiştirme: bir URL yalnızca URL-gövdesi
	OLMAYAN bir karakterle (tırnak, boşluk, `)`, `>`, dize sonu...) bitiyorsa
	değiştirilir; `/files/old.jpg.webp` gibi daha uzun bir adın öneki olarak
	geçiyorsa dokunulmaz."""

	def test_html_ozniteligi_icinde_degistirilir(self):
		value = '<img src="/files/old.jpg">'
		out = refs._replace_embedded(value, "/files/old.jpg", "/files/new.jpg")
		self.assertEqual(out, '<img src="/files/new.jpg">')

	def test_daha_uzun_adin_oneki_olarak_gecen_url_degismez(self):
		value = "gör: /files/old.jpg.webp ayrıca /files/old.jpg2 ve son olarak /files/old.jpg"
		out = refs._replace_embedded(value, "/files/old.jpg", "/files/new.jpg")
		self.assertEqual(out, "gör: /files/old.jpg.webp ayrıca /files/old.jpg2 ve son olarak /files/new.jpg")

	def test_hic_gecmiyorsa_none(self):
		self.assertIsNone(
			refs._replace_embedded("burada hiçbir adres yok", "/files/old.jpg", "/files/new.jpg")
		)

	def test_json_kacisli_yazim_duz_metinde_de_degistirilir(self):
		old = "/files/rr-ı-abcdef.jpg"
		kacisli = json.dumps(old, ensure_ascii=True)[1:-1]  # ı kaçışlı yazım
		value = f"log satırı: gördü {kacisli} orada"
		out = refs._replace_embedded(value, old, "/files/new.jpg")
		self.assertEqual(out, "log satırı: gördü /files/new.jpg orada")
