"""
Social Proof — module skeleton tests.

`tradehub_core.api.social_proof._get_settings()` ve `_serialize_signal()` için
happy + edge path testleri. Frappe runtime gerekli (cache + get_single çağrıları),
bu yüzden `FrappeTestCase` kullanılır:

    bench --site dev.localhost run-tests --module tradehub_core.tests.test_social_proof
"""

import unittest.mock as mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tradehub_core.api import social_proof as sp


class TestSocialProofSettings(FrappeTestCase):
	def test_get_settings_returns_thresholds(self):
		frappe.cache().delete_value(sp._SETTINGS_CACHE_KEY)
		s = sp._get_settings()
		for k in (
			"sales_threshold",
			"favorites_threshold",
			"cart_now_threshold",
			"views_24h_threshold",
			"distinct_buyers_threshold",
			"seller_orders_threshold",
		):
			self.assertIn(k, s)
			self.assertGreater(s[k], 0)
		self.assertIn("cache_ttl_seconds", s)
		self.assertIn("view_dedup_seconds", s)
		self.assertIn("enabled", s)

	def test_get_settings_uses_cache_on_second_call(self):
		frappe.cache().delete_value(sp._SETTINGS_CACHE_KEY)
		s1 = sp._get_settings()
		s2 = sp._get_settings()
		# Aynı dict referansı dönmeli (cache hit)
		self.assertEqual(s1, s2)
		# Cache key gerçekten yazılmış olmalı
		cached = frappe.cache().get_value(sp._SETTINGS_CACHE_KEY)
		self.assertIsNotNone(cached)


class TestSocialProofSerialize(FrappeTestCase):
	def test_serialize_signal_with_window(self):
		result = sp._serialize_signal("sales", 2073, window_days=3)
		self.assertEqual(result, {"type": "sales", "value": 2073, "window_days": 3})

	def test_serialize_signal_without_window(self):
		result = sp._serialize_signal("favorites", 14)
		self.assertEqual(result, {"type": "favorites", "value": 14})
		self.assertNotIn("window_days", result)

	def test_serialize_signal_casts_value_to_int(self):
		result = sp._serialize_signal("favorites", 14.7)
		self.assertEqual(result["value"], 14)
		self.assertIsInstance(result["value"], int)


class TestSocialProofComputes(FrappeTestCase):
	def setUp(self):
		# Mevcut bir Listing varsa onu kullan — test DB'sini kirletmemek için fixture açmıyoruz
		self.listing = frappe.db.get_value("Listing", {}, "name")
		self.settings = sp._get_settings()

	def test_compute_sales_returns_dict_with_30day_window(self):
		"""B5 refactor: auto-window kaldırıldı, sabit 30 gün; her zaman dict döner."""
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		result = sp._compute_sales(self.listing, None, self.settings)
		self.assertIsInstance(result, dict)
		self.assertEqual(result["type"], "sales")
		self.assertEqual(result["window_days"], 30)
		self.assertIn("threshold", result)
		self.assertGreaterEqual(result["value"], 0)

	def test_compute_favorites_returns_dict_unconditionally(self):
		"""B5 refactor: threshold altında bile dict döner (filtering caller'da)."""
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		result = sp._compute_favorites(self.listing, None, self.settings)
		self.assertIsInstance(result, dict)
		self.assertEqual(result["type"], "favorites")
		self.assertIn("threshold", result)
		self.assertGreaterEqual(result["value"], 0)

	def test_compute_cart_now_returns_dict_unconditionally(self):
		"""B5 refactor: threshold altında bile dict döner."""
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		result = sp._compute_cart_now(self.listing, None, self.settings)
		self.assertIsInstance(result, dict)
		self.assertEqual(result["type"], "cart_now")
		self.assertIn("threshold", result)
		self.assertGreaterEqual(result["value"], 0)

	def test_compute_views_24h_missing_counter_returns_zero_value(self):
		"""B5 refactor: counter yokken value=0 ile dict döner."""
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		# Counter doc'u silip 0 değerinde olduğunu garantile
		if frappe.db.exists("Listing View Counter", self.listing):
			frappe.db.delete("Listing View Counter", {"listing": self.listing})
			frappe.db.commit()
		result = sp._compute_views_24h(self.listing, None, self.settings)
		self.assertIsInstance(result, dict)
		self.assertEqual(result["type"], "views_24h")
		self.assertEqual(result["value"], 0)

	def test_compute_views_24h_counter_above_threshold(self):
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		threshold = self.settings["views_24h_threshold"]
		# Counter'ı threshold'un hemen üstüne yaz
		if frappe.db.exists("Listing View Counter", self.listing):
			frappe.db.set_value("Listing View Counter", self.listing, "view_count_24h", threshold + 5)
		else:
			frappe.get_doc(
				{
					"doctype": "Listing View Counter",
					"listing": self.listing,
					"view_count_24h": threshold + 5,
					"last_event": now_datetime(),
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()
		try:
			result = sp._compute_views_24h(self.listing, None, self.settings)
			self.assertIsNotNone(result)
			self.assertEqual(result["type"], "views_24h")
			self.assertGreaterEqual(result["value"], threshold)
		finally:
			# Temizlik
			if frappe.db.exists("Listing View Counter", self.listing):
				frappe.db.delete("Listing View Counter", {"listing": self.listing})
				frappe.db.commit()

	def test_compute_distinct_buyers_returns_dict_with_window(self):
		"""B5 refactor: her zaman dict döner; window_days=30 garantili."""
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		result = sp._compute_distinct_buyers(self.listing, None, self.settings)
		self.assertIsInstance(result, dict)
		self.assertEqual(result["type"], "distinct_buyers")
		self.assertEqual(result["window_days"], 30)
		self.assertIn("threshold", result)
		self.assertGreaterEqual(result["value"], 0)

	def test_compute_seller_orders_returns_dict_when_supplier_resolves(self):
		"""B5 refactor: supplier_id çözüldüğünde threshold altı bile dict döner."""
		if not self.listing:
			self.skipTest("No existing Listing in test DB")
		# Listing'in seller_profile'ı varsa dict, yoksa None döner
		result = sp._compute_seller_orders(self.listing, None, self.settings)
		if result is not None:
			# seller_profile çözüldü
			self.assertEqual(result["type"], "seller_orders")
			self.assertIn("threshold", result)
			self.assertGreaterEqual(result["value"], 0)

	def test_compute_seller_orders_with_unknown_supplier_returns_none(self):
		result = sp._compute_seller_orders("nonexistent-listing", "FAKE-SELLER-ID", self.settings)
		# B5: seller_orders explicit supplier_id verildiğinde dict döner;
		# çünkü resolve adımı atlanır ve count 0 ile dict döner.
		self.assertIsInstance(result, dict)
		self.assertEqual(result["type"], "seller_orders")
		self.assertEqual(result["value"], 0)


class TestSocialProofEndpoint(FrappeTestCase):
	def setUp(self):
		self.listing = frappe.db.get_value("Listing", {}, "name")
		if self.listing:
			frappe.cache().delete_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}")

	def test_get_signals_empty_listing_id_throws(self):
		with self.assertRaises(Exception):
			sp.get_signals("")

	def test_get_signals_settings_disabled_returns_empty(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		# Temporarily disable via cache (override doc-based fetch)
		frappe.cache().set_value(
			sp._SETTINGS_CACHE_KEY,
			{**sp._get_settings(), "enabled": False},
			expires_in_sec=60,
		)
		try:
			result = sp.get_signals(self.listing)
			self.assertEqual(result, {"signals": []})
		finally:
			frappe.cache().delete_value(sp._SETTINGS_CACHE_KEY)

	def test_get_signals_archived_listing_returns_empty(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		original = frappe.db.get_value("Listing", self.listing, "status")
		try:
			frappe.db.set_value("Listing", self.listing, "status", "Archived")
			frappe.db.commit()
			result = sp.get_signals(self.listing)
			self.assertEqual(result["signals"], [])
		finally:
			if original:
				frappe.db.set_value("Listing", self.listing, "status", original)
				frappe.db.commit()

	def test_get_signals_caches_response(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		sp.get_signals(self.listing)
		cached = frappe.cache().get_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}")
		self.assertIsNotNone(cached)
		self.assertIn("signals", cached)

	def test_get_signals_returns_dict_with_signals_key(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		result = sp.get_signals(self.listing)
		self.assertIsInstance(result, dict)
		self.assertIn("signals", result)
		self.assertIsInstance(result["signals"], list)
		# Each signal has required shape
		for sig in result["signals"]:
			self.assertIn("type", sig)
			self.assertIn("value", sig)
			self.assertIsInstance(sig["value"], int)


class TestSocialProofRecordView(FrappeTestCase):
	def setUp(self):
		self.listing = frappe.db.get_value("Listing", {}, "name")
		if self.listing:
			# Clean dedup keys + counter
			frappe.cache().delete_keys(sp._VIEW_DEDUP_PREFIX)
			frappe.db.delete("Listing View Counter", {"listing": self.listing})
			frappe.db.commit()

	def tearDown(self):
		if self.listing:
			frappe.cache().delete_keys(sp._VIEW_DEDUP_PREFIX)
			frappe.db.delete("Listing View Counter", {"listing": self.listing})
			frappe.db.commit()

	def test_record_view_no_listing_id_is_noop(self):
		# Should not throw
		sp.record_view("")
		# No counter created
		self.assertEqual(frappe.db.count("Listing View Counter"), 0)

	def test_record_view_creates_counter(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		frappe.local.request_ip = "10.0.0.1"
		sp.record_view(self.listing)
		v = frappe.db.get_value("Listing View Counter", self.listing, "view_count_24h")
		self.assertEqual(v, 1)

	def test_record_view_dedup_same_ip(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		frappe.local.request_ip = "10.0.0.2"
		sp.record_view(self.listing)
		sp.record_view(self.listing)  # 2nd call dedup
		v = frappe.db.get_value("Listing View Counter", self.listing, "view_count_24h")
		self.assertEqual(v, 1)

	def test_record_view_different_ips_both_increment(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		frappe.local.request_ip = "10.0.0.3"
		sp.record_view(self.listing)
		frappe.local.request_ip = "10.0.0.4"
		sp.record_view(self.listing)
		v = frappe.db.get_value("Listing View Counter", self.listing, "view_count_24h")
		self.assertEqual(v, 2)

	def test_record_view_disabled_settings_is_noop(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		frappe.cache().set_value(
			sp._SETTINGS_CACHE_KEY,
			{**sp._get_settings(), "enabled": False},
			expires_in_sec=60,
		)
		try:
			frappe.local.request_ip = "10.0.0.5"
			sp.record_view(self.listing)
			self.assertEqual(frappe.db.count("Listing View Counter", {"listing": self.listing}), 0)
		finally:
			frappe.cache().delete_value(sp._SETTINGS_CACHE_KEY)


class TestSocialProofScheduler(FrappeTestCase):
	def setUp(self):
		self.listing = frappe.db.get_value("Listing", {}, "name")
		if self.listing:
			frappe.db.delete("Listing View Counter", {"listing": self.listing})
			frappe.db.commit()

	def tearDown(self):
		if self.listing:
			frappe.db.delete("Listing View Counter", {"listing": self.listing})
			frappe.db.commit()

	def _make_counter(self, view_count: int, hours_ago: int) -> None:
		frappe.get_doc(
			{
				"doctype": "Listing View Counter",
				"listing": self.listing,
				"view_count_24h": view_count,
				"last_event": add_to_date(now_datetime(), hours=-hours_ago),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	def test_reset_clears_stale_counter(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		self._make_counter(view_count=50, hours_ago=25)

		sp.reset_view_counters_rolling_24h()

		v = frappe.db.get_value("Listing View Counter", self.listing, "view_count_24h")
		self.assertEqual(v, 0)

	def test_reset_preserves_fresh_counter(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		self._make_counter(view_count=50, hours_ago=1)

		sp.reset_view_counters_rolling_24h()

		v = frappe.db.get_value("Listing View Counter", self.listing, "view_count_24h")
		self.assertEqual(v, 50)

	def test_reset_idempotent_on_already_zero(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		self._make_counter(view_count=0, hours_ago=48)

		# UPDATE filter has `AND view_count_24h > 0` → no-op
		sp.reset_view_counters_rolling_24h()

		v = frappe.db.get_value("Listing View Counter", self.listing, "view_count_24h")
		self.assertEqual(v, 0)


class TestSocialProofInvalidation(FrappeTestCase):
	def setUp(self):
		self.listing = frappe.db.get_value("Listing", {}, "name")
		if self.listing:
			frappe.cache().delete_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}")

	def _seed_cache(self) -> None:
		frappe.cache().set_value(
			f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}",
			{"signals": []},
			expires_in_sec=600,
		)

	def _fake_doc(self, status: str, listing_id: str):
		class FakeItem:
			def __init__(self, listing):
				self.listing = listing

		class FakeDoc:
			def __init__(s, name, status, items):
				s.name = name
				s.status = status
				s.items = items

			def is_new(s):
				return False

		return FakeDoc("ORD-TEST-1", status, [FakeItem(listing_id)])

	def test_status_change_into_sold_state_invalidates(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		self._seed_cache()
		doc = self._fake_doc("Tamamlandı", self.listing)
		with mock.patch.object(frappe.db, "get_value", return_value="Onaylanıyor"):
			sp.invalidate_for_order(doc)
		self.assertIsNone(frappe.cache().get_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}"))

	def test_status_change_out_of_sold_state_invalidates(self):
		"""İptal: 'Kargoda' → 'İptal Edildi' geçişi sales sayımını etkiler."""
		if not self.listing:
			self.skipTest("No existing Listing")
		self._seed_cache()
		doc = self._fake_doc("İptal Edildi", self.listing)
		with mock.patch.object(frappe.db, "get_value", return_value="Kargoda"):
			sp.invalidate_for_order(doc)
		self.assertIsNone(frappe.cache().get_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}"))

	def test_no_status_change_keeps_cache(self):
		if not self.listing:
			self.skipTest("No existing Listing")
		self._seed_cache()
		doc = self._fake_doc("Onaylanıyor", self.listing)
		with mock.patch.object(frappe.db, "get_value", return_value="Onaylanıyor"):
			sp.invalidate_for_order(doc)
		self.assertIsNotNone(frappe.cache().get_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}"))

	def test_transition_between_unrelated_states_keeps_cache(self):
		"""Ödeme Bekleniyor → Onaylanıyor: hiçbiri _INVALIDATING_STATES'te değil."""
		if not self.listing:
			self.skipTest("No existing Listing")
		self._seed_cache()
		doc = self._fake_doc("Onaylanıyor", self.listing)
		with mock.patch.object(frappe.db, "get_value", return_value="Ödeme Bekleniyor"):
			sp.invalidate_for_order(doc)
		self.assertIsNotNone(frappe.cache().get_value(f"{sp._RESPONSE_CACHE_PREFIX}{self.listing}"))

	def test_invalidate_handles_missing_items_gracefully(self):
		"""doc.items None ise crash etmemeli."""

		class EmptyDoc:
			name = "ORD-EMPTY"
			status = "Tamamlandı"
			items = None

			def is_new(self):
				return False

		with mock.patch.object(frappe.db, "get_value", return_value="Onaylanıyor"):
			# Should not raise
			sp.invalidate_for_order(EmptyDoc())
