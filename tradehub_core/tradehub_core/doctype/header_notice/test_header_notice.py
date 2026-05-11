import unittest

import frappe

from tradehub_core.api.header_notice import CACHE_KEY, get_active_notices


class TestHeaderNotice(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		# Tüm test notice'ları sil
		frappe.db.delete("Header Notice")
		frappe.cache.delete_value(CACHE_KEY)
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("Header Notice")
		frappe.cache.delete_value(CACHE_KEY)
		frappe.db.commit()

	def _make(self, **kwargs):
		defaults = {
			"doctype": "Header Notice",
			"message_tr": kwargs.pop("message_tr", "Test"),
			"is_active": 1,
			"icon": "none",
			"sort_order": 0,
		}
		defaults.update(kwargs)
		return frappe.get_doc(defaults).insert(ignore_permissions=True)

	def test_active_filter_excludes_inactive(self):
		self._make(message_tr="Aktif")
		self._make(message_tr="Pasif", is_active=0)
		res = get_active_notices()
		messages = [n["message_tr"] for n in res["notices"]]
		self.assertIn("Aktif", messages)
		self.assertNotIn("Pasif", messages)

	def test_date_window_filters_future_and_past(self):
		from frappe.utils import add_days, now_datetime

		self._make(message_tr="Şimdi")
		self._make(message_tr="Gelecek", start_at=add_days(now_datetime(), 1))
		self._make(message_tr="Geçmiş", end_at=add_days(now_datetime(), -1))
		res = get_active_notices()
		messages = [n["message_tr"] for n in res["notices"]]
		self.assertIn("Şimdi", messages)
		self.assertNotIn("Gelecek", messages)
		self.assertNotIn("Geçmiş", messages)

	def test_sort_order_ascending(self):
		self._make(message_tr="C", sort_order=2)
		self._make(message_tr="A", sort_order=0)
		self._make(message_tr="B", sort_order=1)
		res = get_active_notices()
		messages = [n["message_tr"] for n in res["notices"]]
		self.assertEqual(messages, ["A", "B", "C"])

	def test_guest_access_allowed(self):
		self._make(message_tr="Public")
		frappe.set_user("Guest")
		try:
			res = get_active_notices()
			self.assertTrue(res["success"])
			self.assertEqual(len(res["notices"]), 1)
		finally:
			frappe.set_user("Administrator")

	def test_cache_invalidated_on_update(self):
		doc = self._make(message_tr="Cache testi")
		get_active_notices()  # cache populate
		self.assertIsNotNone(frappe.cache.get_value(CACHE_KEY))
		doc.message_tr = "Güncellendi"
		doc.save(ignore_permissions=True)
		self.assertIsNone(frappe.cache.get_value(CACHE_KEY))
