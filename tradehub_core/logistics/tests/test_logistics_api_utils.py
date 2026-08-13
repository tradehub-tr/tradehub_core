# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-102 — API sözleşme katmanı testleri (Faz B.1 + B.3).

Çalıştırma:
	docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \\
	  bench --site dev.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_logistics_api_utils"

Bu testler sözleşmenin KENDİSİNİ kilitler. Yanıt zarfının şekli ve hata kodları
frontend'in dallanma noktasıdır; sessizce değişirlerse Faz D/E'de yazılmış her
ekran kırılır. Kod değeri değiştirmek kırıcı değişikliktir — bu testler o
değişikliği görünür kılar.
"""

from __future__ import annotations

import unittest.mock as mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.logistics.api_utils import error, logistics_endpoint, ok
from tradehub_core.logistics.exceptions import (
	CarrierNotFoundError,
	ShipmentStateError,
)


class TestResponseEnvelope(FrappeTestCase):
	"""Başarı ve hata zarfının sabit şekli."""

	def test_success_envelope_shape(self):
		self.assertEqual(ok({"x": 1}), {"ok": True, "data": {"x": 1}})

	def test_success_envelope_allows_none(self):
		self.assertEqual(ok(), {"ok": True, "data": None})

	def test_error_envelope_shape(self):
		self.assertEqual(
			error("SOME_CODE", "mesaj"),
			{"ok": False, "error": {"code": "SOME_CODE", "message": "mesaj"}},
		)

	def test_error_envelope_includes_details_when_given(self):
		result = error("SOME_CODE", "mesaj", {"field": "city"})
		self.assertEqual(result["error"]["details"], {"field": "city"})

	def test_error_envelope_omits_empty_details(self):
		"""Boş details anahtarı hiç eklenmemeli — istemci varlığına bakabilsin."""
		self.assertNotIn("details", error("SOME_CODE", "mesaj", {})["error"])


class TestDecoratorSuccessPath(FrappeTestCase):
	def test_plain_return_is_wrapped(self):
		@logistics_endpoint()
		def fn():
			return {"items": [1, 2]}

		self.assertEqual(fn(), {"ok": True, "data": {"items": [1, 2]}})

	def test_already_wrapped_result_is_not_double_wrapped(self):
		"""İş fonksiyonu ok() döndürdüyse ikinci kez sarılmamalı."""

		@logistics_endpoint()
		def fn():
			return ok({"items": []})

		self.assertEqual(fn(), {"ok": True, "data": {"items": []}})

	def test_function_metadata_preserved(self):
		"""functools.wraps olmadan Frappe whitelist adı bozulurdu."""

		@logistics_endpoint()
		def list_carrier_services():
			return None

		self.assertEqual(list_carrier_services.__name__, "list_carrier_services")


class TestDecoratorErrorMapping(FrappeTestCase):
	"""Her hata sınıfı doğru kod ve HTTP durumuna eşlenir."""

	def _status(self) -> int | None:
		return frappe.local.response.get("http_status_code")

	def setUp(self):
		frappe.local.response.pop("http_status_code", None)

	def test_logistics_error_uses_own_code_and_status(self):
		@logistics_endpoint()
		def fn():
			raise ShipmentStateError("Geçersiz geçiş")

		result = fn()
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "SHIPMENT_STATE_INVALID")
		self.assertEqual(self._status(), 409)

	def test_carrier_not_found_maps_to_404(self):
		@logistics_endpoint()
		def fn():
			raise CarrierNotFoundError("yok")

		self.assertEqual(fn()["error"]["code"], "CARRIER_NOT_FOUND")
		self.assertEqual(self._status(), 404)

	def test_permission_error_maps_to_403(self):
		@logistics_endpoint()
		def fn():
			raise frappe.PermissionError("yetkisiz")

		self.assertEqual(fn()["error"]["code"], "PERMISSION_DENIED")
		self.assertEqual(self._status(), 403)

	def test_does_not_exist_maps_to_404(self):
		@logistics_endpoint()
		def fn():
			raise frappe.DoesNotExistError("yok")

		self.assertEqual(fn()["error"]["code"], "NOT_FOUND")
		self.assertEqual(self._status(), 404)

	def test_plain_validation_error_maps_to_417(self):
		"""LogisticsError DEĞİL, düz ValidationError — genel koda düşmeli."""

		@logistics_endpoint()
		def fn():
			raise frappe.ValidationError("geçersiz")

		self.assertEqual(fn()["error"]["code"], "VALIDATION_ERROR")
		self.assertEqual(self._status(), 417)

	def test_unexpected_error_is_masked_and_logged(self):
		"""Beklenmeyen hatanın AYRINTISI istemciye sızmamalı."""

		@logistics_endpoint()
		def fn():
			raise RuntimeError("veritabanı parolası hatalı: hunter2")

		with mock.patch("frappe.log_error") as log_error:
			result = fn()

		self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
		self.assertEqual(self._status(), 500)
		self.assertNotIn("hunter2", result["error"]["message"])
		log_error.assert_called()

	def test_error_path_rolls_back_transaction(self):
		"""Exception yutulduğu için Frappe otomatik rollback yapmaz — biz yapmalıyız.

		Bu olmasaydı yarım kalmış bir yazma commit edilirdi.
		"""

		@logistics_endpoint()
		def fn():
			raise ShipmentStateError("hata")

		with mock.patch("frappe.db.rollback") as rollback:
			fn()

		rollback.assert_called_once()


class TestFeatureFlagGate(FrappeTestCase):
	"""Kapalı özellik iş mantığını HİÇ çalıştırmamalı."""

	def setUp(self):
		frappe.local.response.pop("http_status_code", None)

	def test_disabled_flag_blocks_before_business_logic(self):
		calls = []

		@logistics_endpoint(flag="carrier_api_enabled")
		def fn():
			calls.append(1)
			return None

		with mock.patch("tradehub_core.logistics.is_enabled", return_value=False):
			result = fn()

		self.assertEqual(result["error"]["code"], "FEATURE_DISABLED")
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)
		self.assertEqual(calls, [], "Bayrak kapalıyken iş mantığı çalışmamalı")

	def test_enabled_flag_allows_execution(self):
		@logistics_endpoint(flag="carrier_api_enabled")
		def fn():
			return {"done": True}

		with mock.patch("tradehub_core.logistics.is_enabled", return_value=True):
			self.assertEqual(fn(), {"ok": True, "data": {"done": True}})

	def test_feature_disabled_is_distinct_from_permission_denied(self):
		"""İstemci "özellik kapalı" ile "yetkin yok"u ayırt edebilmeli — farklı ekran."""

		@logistics_endpoint(flag="carrier_api_enabled")
		def fn():
			return None

		with mock.patch("tradehub_core.logistics.is_enabled", return_value=False):
			code = fn()["error"]["code"]

		self.assertEqual(code, "FEATURE_DISABLED")
		self.assertNotEqual(code, "PERMISSION_DENIED")


class TestCapabilityGate(FrappeTestCase):
	def setUp(self):
		frappe.local.response.pop("http_status_code", None)

	def test_missing_capability_blocks(self):
		calls = []

		@logistics_endpoint(capability="view.carrier_secret")
		def fn():
			calls.append(1)
			return None

		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			result = fn()

		self.assertEqual(result["error"]["code"], "CAPABILITY_REQUIRED")
		self.assertEqual(frappe.local.response.get("http_status_code"), 403)
		self.assertEqual(calls, [])

	def test_present_capability_allows(self):
		@logistics_endpoint(capability="view.carrier_secret")
		def fn():
			return {"secret": "***"}

		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=True
		):
			self.assertTrue(fn()["ok"])

	def test_flag_is_checked_before_capability(self):
		"""Kapalı bir özellik "yetkiniz yok" dememeli — önce bayrak sorulur."""

		@logistics_endpoint(flag="carrier_api_enabled", capability="view.carrier_secret")
		def fn():
			return None

		with (
			mock.patch("tradehub_core.logistics.is_enabled", return_value=False),
			mock.patch(
				"tradehub_core.utils.permission_resolver.has_capability", return_value=False
			),
		):
			self.assertEqual(fn()["error"]["code"], "FEATURE_DISABLED")


class TestMasterFlagGate(FrappeTestCase):
	"""logistics_enabled kapalıyken alt bayrakların değeri okunmaz."""

	def test_master_off_forces_all_flags_off(self):
		from tradehub_core.logistics import is_enabled

		with mock.patch(
			"tradehub_core.logistics._is_master_enabled", return_value=False
		):
			self.assertFalse(is_enabled("carrier_api_enabled"))
			self.assertFalse(is_enabled("cost_estimation_enabled"))

	def test_master_flag_itself_is_readable(self):
		from tradehub_core.logistics import MASTER_FLAG, is_enabled

		with mock.patch(
			"tradehub_core.logistics._is_master_enabled", return_value=True
		):
			self.assertTrue(is_enabled(MASTER_FLAG))

	def test_master_on_lets_sub_flag_decide(self):
		from tradehub_core.logistics import is_enabled

		with mock.patch("tradehub_core.logistics._is_master_enabled", return_value=True):
			# Varsayılanlar kapalı — ana bayrak açık olsa da alt bayrak False kalmalı
			self.assertFalse(is_enabled("multi_leg_enabled"))

	def test_empty_flag_name_rejected(self):
		from tradehub_core.logistics import is_enabled

		with self.assertRaises(frappe.ValidationError):
			is_enabled("")
