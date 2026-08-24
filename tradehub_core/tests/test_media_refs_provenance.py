"""`refs.retarget()` provenance ve karşılaştırmalı geri alma güvenlik testleri.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_refs_provenance
"""

from __future__ import annotations

import json

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import refs


class TestRetargetProvenance(FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.old = f"/files/provenance-{frappe.generate_hash(length=8)}.jpg"
		self.new = "/files/ab/" + "c" * 32 + ".jpg"
		self.listing = self._make_listing(self.old)
		self.addCleanup(
			lambda: frappe.delete_doc("Listing", self.listing, force=True, ignore_permissions=True)
		)

	def _make_listing(self, primary_image: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Listing",
				"listing_code": f"PROV-{frappe.generate_hash(length=8)}",
				"title": "Referans provenance testi",
				"status": "Active",
				"currency": "TRY",
				"base_price": 100,
				"selling_price": 100,
				"primary_image": primary_image,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		return doc.name

	def test_retarget_json_uyumlu_provenance_ve_geri_alma_yazar(self):
		out = refs.retarget(self.old, self.new)

		self.assertEqual(out["total"], 1)
		self.assertEqual(out["updated"], [f"Listing:{self.listing}·primary_image"])
		self.assertEqual(
			out["changes"],
			[
				{
					"doctype": "Listing",
					"table": "tabListing",
					"row": self.listing,
					"field": "primary_image",
					"column": "primary_image",
					"before": self.old,
					"after": self.new,
				}
			],
		)
		self.assertEqual(json.loads(json.dumps(out["changes"])), out["changes"])

		restored = refs.restore_retarget_changes(out["changes"])
		self.assertEqual(restored["total"], 1)
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), self.old)

	def test_geri_alma_sonradan_kullanici_degisikligini_ezmez(self):
		out = refs.retarget(self.old, self.new)
		user_value = "/files/user-choice.jpg"
		frappe.db.set_value("Listing", self.listing, "primary_image", user_value, update_modified=False)

		restored = refs.restore_retarget_changes(out["changes"])
		self.assertEqual(restored["total"], 0)
		self.assertTrue(any("sonradan değişti" in item for item in restored["skipped"]))
		self.assertEqual(frappe.db.get_value("Listing", self.listing, "primary_image"), user_value)

	def test_izin_listesi_disindaki_hedef_reddedilir(self):
		change = {
			"doctype": "User",
			"table": "tabUser",
			"row": "Administrator",
			"field": "email",
			"column": "email",
			"before": "old@example.test",
			"after": "new@example.test",
		}
		with self.assertRaises(frappe.ValidationError):
			refs.restore_retarget_changes([change])

	def test_izin_listeli_tabloda_izin_listesi_disindaki_alan_reddedilir(self):
		change = {
			"doctype": "Listing",
			"table": "tabListing",
			"row": self.listing,
			"field": "title",
			"column": "title",
			"before": "önce",
			"after": "sonra",
		}
		with self.assertRaises(frappe.ValidationError):
			refs.restore_retarget_changes([change])
