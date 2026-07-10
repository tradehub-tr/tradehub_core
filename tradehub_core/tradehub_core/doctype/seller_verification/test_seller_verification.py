import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from tradehub_core.api.seller import list_pending_seller_verifications, update_seller_verification


class TestSellerVerification(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Verification Source", {"source_name": "_Test Kaynak"}):
			frappe.get_doc(
				{
					"doctype": "Verification Source",
					"source_name": "_Test Kaynak",
					"is_active": 1,
				}
			).insert(ignore_permissions=True, ignore_mandatory=True)
		cls.source = frappe.db.get_value(
			"Verification Source", {"source_name": "_Test Kaynak"}, "name"
		)
		if not frappe.db.exists("Admin Seller Profile", {"seller_code": "_test_seller_34551_728"}):
			profile = frappe.get_doc(
				{
					"doctype": "Admin Seller Profile",
					"seller_name": "_Test Doğrulama Satıcısı",
					"seller_code": "_test_seller_34551_728",
				}
			).insert(ignore_permissions=True, ignore_mandatory=True)
			cls.seller = profile.name
		else:
			cls.seller = frappe.db.get_value("Admin Seller Profile", {"seller_code": "_test_seller_34551_728"}, "name")
			frappe.db.delete("Seller Verification", {"seller": cls.seller})

	def tearDown(self):
		frappe.db.delete("Seller Verification", {"seller": self.seller})

	def _make(self, status: str, expiry_date=None):
		return frappe.get_doc(
			{
				"doctype": "Seller Verification",
				"seller": self.seller,
				"source": self.source,
				"status": status,
				"document": None if status == "Requested" else "/files/_test_denetim.pdf",
				"expiry_date": expiry_date,
			}
		).insert(ignore_permissions=True)

	# ── Duplicate kuralı ──────────────────────────────────────────────

	def test_rejected_does_not_block_new_application(self):
		self._make("Rejected")
		doc = self._make("Pending")  # red sonrası yeniden başvuru
		self.assertEqual(doc.status, "Pending")

	def test_pending_blocks_second_application(self):
		self._make("Pending")
		with self.assertRaises(frappe.DuplicateEntryError):
			self._make("Pending")

	def test_requested_blocks_second_application(self):
		self._make("Requested")
		with self.assertRaises(frappe.DuplicateEntryError):
			self._make("Requested")

	def test_expired_verified_does_not_block(self):
		self._make("Verified", expiry_date=add_days(today(), -1))
		doc = self._make("Pending")  # süre dolunca yenileme
		self.assertEqual(doc.status, "Pending")

	def test_active_verified_blocks(self):
		self._make("Verified", expiry_date=add_days(today(), 30))
		with self.assertRaises(frappe.DuplicateEntryError):
			self._make("Pending")

	def test_verified_without_expiry_blocks(self):
		self._make("Verified")
		with self.assertRaises(frappe.DuplicateEntryError):
			self._make("Pending")

	# ── update_seller_verification ────────────────────────────────────

	def test_update_endpoint_admin_only(self):
		doc = self._make("Pending")
		frappe.set_user("Guest")
		try:
			with self.assertRaises(frappe.PermissionError):
				update_seller_verification(name=doc.name, admin_note="x")
		finally:
			frappe.set_user("Administrator")

	def test_update_endpoint_updates_fields(self):
		doc = self._make("Verified", expiry_date=add_days(today(), 10))
		yeni_tarih = add_days(today(), 365)
		res = update_seller_verification(
			name=doc.name, expiry_date=yeni_tarih, admin_note="tarih düzeltildi"
		)
		self.assertTrue(res["ok"])
		doc.reload()
		self.assertEqual(str(doc.expiry_date), yeni_tarih)
		self.assertEqual(doc.admin_note, "tarih düzeltildi")

	def test_update_endpoint_rejects_invalid_status(self):
		doc = self._make("Pending")
		with self.assertRaises(frappe.ValidationError):
			update_seller_verification(name=doc.name, status="Bogus")
	# ── list_pending_seller_verifications status filtresi ─────────────

	def test_list_status_filter(self):
		rec = self._make("Rejected")
		rec.admin_note = "_test admin notu"
		rec.save(ignore_permissions=True)
		all_rows = list_pending_seller_verifications(status="all")["data"]
		self.assertTrue(any(r["seller"] == self.seller for r in all_rows))
		bizim = next(r for r in all_rows if r["seller"] == self.seller)
		self.assertEqual(bizim["admin_note"], "_test admin notu")
		pending_rows = list_pending_seller_verifications()["data"]
		self.assertFalse(any(r["seller"] == self.seller for r in pending_rows))
		rejected_rows = list_pending_seller_verifications(status="Rejected")["data"]
		self.assertTrue(any(r["seller"] == self.seller for r in rejected_rows))
		with self.assertRaises(frappe.ValidationError):
			list_pending_seller_verifications(status="Bogus")

