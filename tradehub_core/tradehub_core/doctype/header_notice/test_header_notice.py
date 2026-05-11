import unittest

import frappe

from tradehub_core.api.header_notice import get_active_notices


class TestHeaderNotice(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		frappe.db.delete("Header Notice")
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("Header Notice")
		frappe.db.commit()

	def _make(self, **kwargs):
		defaults = {
			"doctype": "Header Notice",
			"message_tr": kwargs.pop("message_tr", "Test"),
			"is_active": 1,
			"icon": "none",
			"background_color": "#1a1a1a",
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

	def test_response_includes_display_mode(self):
		# Settings'i marquee yap, 1 notice ekle — API admin'in seçtiği modu döndürür (auto-downgrade yok)
		frappe.db.set_single_value("Header Notice Settings", "display_mode", "marquee")
		self._make(message_tr="One")
		res = get_active_notices()
		self.assertIn("display_mode", res)
		self.assertEqual(res["display_mode"], "marquee")

	def test_display_mode_with_two_notices(self):
		# 2+ notice'ta da admin'in seçtiği mod aynen döner
		frappe.db.set_single_value("Header Notice Settings", "display_mode", "slide")
		self._make(message_tr="A")
		self._make(message_tr="B")
		res = get_active_notices()
		self.assertEqual(res["display_mode"], "slide")

	def test_invalidate_cache_hook_registered(self):
		hooks = frappe.get_hooks("doc_events", default={})
		hn_hooks = hooks.get("Header Notice", {})
		self.assertTrue(hn_hooks, "Header Notice doc_events kaydı bulunamadı")
		expected_handler = "tradehub_core.api.header_notice.invalidate_cache"
		for event in ("after_insert", "on_update", "on_trash"):
			handlers = hn_hooks.get(event, [])
			if isinstance(handlers, str):
				handlers = [handlers]
			self.assertIn(expected_handler, handlers, f"'{event}' kaydı eksik")
