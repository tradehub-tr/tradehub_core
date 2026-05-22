"""
Social Proof admin endpoints + helper testleri.

Spec: tradehubfront/docs/superpowers/specs/2026-05-21-admin-panel-social-proof-settings-design.md
Plan: tradehubfront/docs/superpowers/plans/2026-05-21-admin-panel-social-proof-settings-plan.md
"""

from __future__ import annotations

import unittest

import frappe

from tradehub_core.api import social_proof


class TestValidatePayload(unittest.TestCase):
	"""_validate_payload kuralları — negatif/sıfır eşik blokla, TTL range."""

	def _valid_payload(self) -> dict:
		"""Sıkı validation'dan geçen baseline payload."""
		return {
			"enabled": True,
			"thresholds": {
				"sales": 100,
				"favorites": 10,
				"cart_now": 3,
				"views_24h": 30,
				"distinct_buyers": 5,
				"seller_orders": 50,
			},
			"cache_ttl_seconds": 600,
			"view_dedup_seconds": 1800,
		}

	def test_valid_payload_passes(self) -> None:
		"""Default değerli payload exception fırlatmamalı."""
		social_proof._validate_payload(self._valid_payload())

	def test_negative_threshold_rejected(self) -> None:
		payload = self._valid_payload()
		payload["thresholds"]["sales"] = -5
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)

	def test_zero_threshold_rejected(self) -> None:
		payload = self._valid_payload()
		payload["thresholds"]["favorites"] = 0
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)

	def test_huge_threshold_rejected(self) -> None:
		payload = self._valid_payload()
		payload["thresholds"]["sales"] = 999999
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)

	def test_cache_ttl_too_low_rejected(self) -> None:
		payload = self._valid_payload()
		payload["cache_ttl_seconds"] = 30  # 60sn altı
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)

	def test_cache_ttl_too_high_rejected(self) -> None:
		payload = self._valid_payload()
		payload["cache_ttl_seconds"] = 100000  # 86400 üstü
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)

	def test_view_dedup_out_of_range_rejected(self) -> None:
		payload = self._valid_payload()
		payload["view_dedup_seconds"] = 30
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)

	def test_bool_threshold_rejected(self) -> None:
		"""bool int subclass'ı; True/False threshold olarak kabul edilmemeli."""
		payload = self._valid_payload()
		payload["thresholds"]["sales"] = True
		with self.assertRaises(frappe.ValidationError):
			social_proof._validate_payload(payload)


class TestPickSampleListings(unittest.TestCase):
	"""_pick_sample_listings — hot/warm/cold seçimi + fallback + cache.

	Destruktif SQL (DELETE) içerdiği için her test savepoint ile sarılır;
	tearDown rollback yapar. unittest.TestCase otomatik rollback yapmaz —
	FrappeTestCase'in aksine bu izolasyonu elle sağlamak zorundayız.
	"""

	def setUp(self) -> None:
		frappe.cache().delete_value("social_proof:admin_samples")
		frappe.db.savepoint("test_pick_sample_listings")

	def tearDown(self) -> None:
		frappe.db.rollback(save_point="test_pick_sample_listings")
		frappe.cache().delete_value("social_proof:admin_samples")

	def test_returns_three_samples_when_counters_exist(self) -> None:
		# View counter datası varsa 3 tuple döner; fallback aktifse de aynı kontrak.
		samples = social_proof._pick_sample_listings()
		self.assertEqual(len(samples), 3)
		self.assertEqual([s[1] for s in samples], ["hot", "warm", "cold"])

	def test_cache_hit_skips_db(self) -> None:
		"""İki ardışık çağrı aynı listeyi döner; 2. çağrı cache'ten gelmeli."""
		first = social_proof._pick_sample_listings()
		cached = frappe.cache().get_value("social_proof:admin_samples")
		self.assertIsNotNone(cached)
		self.assertEqual(first, cached)
		second = social_proof._pick_sample_listings()
		self.assertEqual(first, second)

	def test_fallback_when_no_counters(self) -> None:
		"""View Counter boş → en son 3 Active Listing fallback."""
		frappe.db.sql("DELETE FROM `tabListing View Counter`")
		frappe.cache().delete_value("social_proof:admin_samples")
		samples = social_proof._pick_sample_listings()
		listing_count = frappe.db.count("Listing", {"status": "Active"})
		expected_len = min(3, listing_count)
		self.assertEqual(len(samples), expected_len)
		if samples:
			self.assertEqual([s[1] for s in samples][: len(samples)], ["hot", "warm", "cold"][: len(samples)])


class TestGetAdminSettings(unittest.TestCase):
	"""get_admin_settings auth + field completeness."""

	def setUp(self) -> None:
		self._original_user = frappe.session.user

	def tearDown(self) -> None:
		frappe.set_user(self._original_user)

	def test_guest_blocked(self) -> None:
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			social_proof.get_admin_settings()

	def test_admin_returns_all_11_fields(self) -> None:
		"""System Manager → tüm field'lar dönmeli."""
		frappe.set_user("Administrator")
		result = social_proof.get_admin_settings()
		self.assertIn("enabled", result)
		self.assertIn("thresholds", result)
		self.assertIn("cache_ttl_seconds", result)
		self.assertIn("view_dedup_seconds", result)
		# 6 threshold field
		for field in ("sales", "favorites", "cart_now", "views_24h", "distinct_buyers", "seller_orders"):
			self.assertIn(field, result["thresholds"])
			self.assertIsInstance(result["thresholds"][field], int)

	def test_admin_returns_correct_types(self) -> None:
		"""enabled bool, cache_ttl int, view_dedup int."""
		frappe.set_user("Administrator")
		result = social_proof.get_admin_settings()
		self.assertIsInstance(result["enabled"], bool)
		self.assertIsInstance(result["cache_ttl_seconds"], int)
		self.assertIsInstance(result["view_dedup_seconds"], int)


class TestUpdateAdminSettings(unittest.TestCase):
	"""update_admin_settings — auth + validation + cache temizleme.

	Destruktif doc.save() içerdiği için savepoint ile izole edilir;
	Single DocType'a yapılan mutasyonlar tearDown'da rollback olur.
	"""

	def setUp(self) -> None:
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.db.savepoint("test_update_admin_settings")

	def tearDown(self) -> None:
		frappe.db.rollback(save_point="test_update_admin_settings")
		frappe.cache().delete_value(social_proof._SETTINGS_CACHE_KEY)
		frappe.set_user(self._original_user)

	def _valid_payload(self) -> dict:
		return {
			"enabled": True,
			"thresholds": {
				"sales": 100,
				"favorites": 10,
				"cart_now": 3,
				"views_24h": 30,
				"distinct_buyers": 5,
				"seller_orders": 50,
			},
			"cache_ttl_seconds": 600,
			"view_dedup_seconds": 1800,
		}

	def test_negative_threshold_returns_validation_error(self) -> None:
		payload = self._valid_payload()
		payload["thresholds"]["sales"] = -5
		with self.assertRaises(frappe.ValidationError):
			social_proof.update_admin_settings(payload)

	def test_valid_update_persists(self) -> None:
		payload = self._valid_payload()
		payload["thresholds"]["sales"] = 250
		result = social_proof.update_admin_settings(payload)
		self.assertEqual(result, {"ok": True})
		doc = frappe.get_single("Social Proof Settings")
		self.assertEqual(int(doc.sales_threshold), 250)

	def test_update_clears_settings_cache(self) -> None:
		"""Save sonrası _SETTINGS_CACHE_KEY temizlenmiş olmalı."""
		# Önce cache'i doldur
		social_proof._get_settings()
		self.assertIsNotNone(frappe.cache().get_value(social_proof._SETTINGS_CACHE_KEY))

		payload = self._valid_payload()
		social_proof.update_admin_settings(payload)

		# Cache temiz olmalı (SocialProofSettings.on_update tarafından)
		self.assertIsNone(frappe.cache().get_value(social_proof._SETTINGS_CACHE_KEY))

	def test_string_payload_parsed_as_json(self) -> None:
		"""Frontend bazen JSON string gönderir (callMethod default)."""
		import json

		payload_str = json.dumps(self._valid_payload())
		result = social_proof.update_admin_settings(payload_str)
		self.assertEqual(result, {"ok": True})

	def test_enabled_string_does_not_enable(self) -> None:
		"""'enabled' field bool olmalı; truthy string False'a coerce edilmemeli."""
		payload = self._valid_payload()
		payload["enabled"] = "false"  # truthy non-empty string
		social_proof.update_admin_settings(payload)
		doc = frappe.get_single("Social Proof Settings")
		self.assertEqual(int(doc.enabled), 0)


class TestGetAdminPreviewSignals(unittest.TestCase):
	"""get_admin_preview_signals — 3 sample + override + filtered_out."""

	def setUp(self) -> None:
		self._original_user = frappe.session.user
		frappe.set_user("Administrator")
		frappe.cache().delete_value(social_proof._SAMPLE_CACHE_KEY)
		frappe.db.savepoint("test_get_admin_preview_signals")

	def tearDown(self) -> None:
		frappe.db.rollback(save_point="test_get_admin_preview_signals")
		frappe.cache().delete_value(social_proof._SAMPLE_CACHE_KEY)
		frappe.set_user(self._original_user)

	def test_returns_samples_array(self) -> None:
		result = social_proof.get_admin_preview_signals()
		self.assertIn("samples", result)
		self.assertIsInstance(result["samples"], list)

	def test_sample_shape(self) -> None:
		result = social_proof.get_admin_preview_signals()
		if result["samples"]:
			sample = result["samples"][0]
			self.assertIn("listing_id", sample)
			self.assertIn("label", sample)
			self.assertIn("title", sample)
			self.assertIn("signals", sample)
			self.assertIn("filtered_out", sample)
			self.assertIn(sample["label"], {"hot", "warm", "cold"})

	def test_overrides_dont_persist_to_settings(self) -> None:
		"""Override Settings doc'una yazılmamalı."""
		doc_before = frappe.get_single("Social Proof Settings")
		before_sales = int(doc_before.sales_threshold)

		social_proof.get_admin_preview_signals(threshold_overrides={"sales": 99999})

		doc_after = frappe.get_single("Social Proof Settings")
		self.assertEqual(int(doc_after.sales_threshold), before_sales)

	def test_high_threshold_populates_filtered_out(self) -> None:
		"""Çok yüksek eşik → tüm sinyaller filtered_out'a düşmeli."""
		result = social_proof.get_admin_preview_signals(
			threshold_overrides={
				"sales": 99999,
				"favorites": 99999,
				"cart_now": 99999,
				"views_24h": 99999,
				"distinct_buyers": 99999,
				"seller_orders": 99999,
			}
		)
		for sample in result["samples"]:
			# value > 0 olan sinyaller filtered_out'a düşmeli, signals boş kalmalı
			self.assertEqual(len(sample["signals"]), 0)

	def test_string_overrides_parsed_as_json(self) -> None:
		import json

		overrides_str = json.dumps({"sales": 99999})
		# Exception fırlatmamalı
		social_proof.get_admin_preview_signals(threshold_overrides=overrides_str)
