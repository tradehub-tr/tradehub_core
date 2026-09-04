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


class TestRollbackLogOrdering(FrappeTestCase):
	"""Denetim 2026-09-04 madde 1-2: rollback → log sıra sözleşmesi.

	Eski sıra `frappe.log_error`'u rollback'ten ÖNCE aynı transaksiyonda
	çağırıyordu; rollback log satırını da siliyor, kullanıcıya "kayıt altına
	alındı" denip iz bırakılmıyordu.
	"""

	def setUp(self):
		frappe.local.response.pop("http_status_code", None)
		frappe.local.flags.commit = False
		frappe.local.tc_pending_deny_audits = []
		self.addCleanup(frappe.local.flags.pop, "commit", None)

	def test_unexpected_error_logs_after_rollback(self):
		"""Error Log yazımı rollback'ten SONRA gelir — satır transaksiyonla silinmez."""

		@logistics_endpoint()
		def fn():
			raise RuntimeError("patladı")

		manager = mock.Mock()
		with (
			mock.patch("frappe.db.rollback", manager.rollback),
			mock.patch("frappe.log_error", manager.log_error),
		):
			result = fn()

		self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
		names = [c[0] for c in manager.mock_calls]
		self.assertIn("rollback", names)
		self.assertIn("log_error", names)
		self.assertLess(
			names.index("rollback"),
			names.index("log_error"),
			"log_error rollback'ten ÖNCE çağrılırsa satır rollback ile silinir",
		)

	def test_unexpected_error_requests_commit_for_log_row(self):
		"""GET yolunda request-sonu sync_database rollback'i log satırını silmesin."""

		@logistics_endpoint()
		def fn():
			raise RuntimeError("patladı")

		with mock.patch("frappe.db.rollback"), mock.patch("frappe.log_error"):
			fn()

		self.assertTrue(frappe.local.flags.commit)

	def test_fail_flushes_pending_deny_audits_after_rollback(self):
		"""Madde 2b: zarf rollback'i bekleyen DENY satırlarını flush ile geri yazar."""

		@logistics_endpoint()
		def fn():
			raise frappe.PermissionError("yetkisiz")

		manager = mock.Mock()
		manager.flush.return_value = 1
		with (
			mock.patch("frappe.db.rollback", manager.rollback),
			mock.patch(
				"tradehub_core.logistics.permissions.flush_pending_deny_audits",
				manager.flush,
			),
		):
			result = fn()

		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
		names = [c[0] for c in manager.mock_calls]
		self.assertLess(
			names.index("rollback"),
			names.index("flush"),
			"Flush rollback'ten SONRA çalışmalı — yoksa yazılan satır da silinir",
		)
		self.assertTrue(
			frappe.local.flags.commit, "Flush edilen satır request-sonu commit'ine bağlanmalı"
		)

	def test_fail_without_pending_audit_does_not_force_commit(self):
		"""Bekleyen audit satırı yoksa flags.commit gereksiz yere set edilmez."""

		@logistics_endpoint()
		def fn():
			raise ShipmentStateError("hata")

		with mock.patch("frappe.db.rollback"):
			fn()

		self.assertFalse(frappe.local.flags.commit)


class TestErrorBodyLeakScrubbing(FrappeTestCase):
	"""Doğrulama turu 2026-09-04 Major 1: zarf hata yanıtı mesaj kanallarını sızdırmaz.

	`doc.check_permission` deny mesajını `frappe.local.message_log` +
	`frappe.flags.error_message`'a yazar; zarf istisnayı yutsa da
	frappe/utils/response.py bu kanalları gövdeye `_server_messages` /
	`_error_message` olarak ekler — 404 anti-enumeration gövdeden deliniyordu
	("... does not have access to this document: Shipment - SHP-..."). `_fail`
	artık HER zarf hata yanıtında iki kanalı da temizler.
	"""

	def setUp(self):
		frappe.local.response.pop("http_status_code", None)
		frappe.clear_messages()
		frappe.local.flags.error_message = None

	def _leak(self) -> None:
		"""check_permission'ın bıraktığı kalıntıyı birebir simüle eder."""
		frappe.local.message_log.append(
			{"message": "User does not have access to this document: Shipment - SHP-GIZLI"}
		)
		frappe.local.flags.error_message = "No permission for Shipment SHP-GIZLI"

	def test_permission_error_scrubs_message_log_and_error_flag(self):
		"""404/403 zarfı dönerken message_log ve flags.error_message BOŞALMALI."""

		@logistics_endpoint()
		def fn():
			self._leak()
			raise frappe.PermissionError("yetkisiz")

		result = fn()

		self.assertEqual(result["error"]["code"], "PERMISSION_DENIED")
		self.assertFalse(
			frappe.local.message_log,
			"message_log temizlenmezse response.py gövdeye _server_messages ekler",
		)
		self.assertFalse(
			frappe.local.flags.error_message,
			"flags.error_message temizlenmezse gövdeye _error_message eklenir",
		)

	def test_does_not_exist_scrubs_channels(self):
		"""Anti-enumeration'ın asıl yolu: 404 zarfı da temiz kanal bırakmalı."""

		@logistics_endpoint()
		def fn():
			self._leak()
			raise frappe.DoesNotExistError("Shipment SHP-GIZLI not found")

		result = fn()

		self.assertEqual(result["error"]["code"], "NOT_FOUND")
		self.assertFalse(frappe.local.message_log)
		self.assertFalse(frappe.local.flags.error_message)

	def test_logistics_error_scrubs_channels(self):
		@logistics_endpoint()
		def fn():
			self._leak()
			raise ShipmentStateError("Geçersiz geçiş")

		fn()
		self.assertFalse(frappe.local.message_log)
		self.assertFalse(frappe.local.flags.error_message)

	def test_internal_error_scrubs_msgprint_leak(self):
		"""500 yolu da kapsanır — beklenmeyen hata öncesi msgprint kalıntısı sızmaz."""

		@logistics_endpoint()
		def fn():
			frappe.local.message_log.append({"message": "iç detay: hunter2"})
			raise RuntimeError("patladı")

		with mock.patch("frappe.log_error"):
			result = fn()

		self.assertEqual(result["error"]["code"], "INTERNAL_ERROR")
		self.assertFalse(frappe.local.message_log)

	def test_extract_message_fallback_reads_before_scrub(self):
		"""str(exc) boşken mesaj message_log'dan alınır — temizlik SONRA yapılır.

		Temizlik erken yapılsaydı meşru mesaj çıkarımı bozulur, kullanıcı
		"İşlem tamamlanamadı." jenerik mesajına düşerdi.
		"""

		@logistics_endpoint()
		def fn():
			frappe.local.message_log.append({"message": "Gerçek doğrulama mesajı"})
			raise frappe.ValidationError()  # str(exc) == ""

		result = fn()

		self.assertEqual(result["error"]["message"], "Gerçek doğrulama mesajı")
		self.assertFalse(frappe.local.message_log, "Mesaj alındıktan sonra kanal boşalmalı")


class TestEnvelopeContextFlag(FrappeTestCase):
	"""Doğrulama turu 2026-09-04 Major 2: zarf bağlam bayrağı.

	permissions._log_deny dedup anahtarını yalnız bu bayrak set'liyken yazar;
	bayrağın iş mantığı SÜRESİNCE açık, request'in zarf-dışı devamında kapalı
	olması sözleşmedir.
	"""

	def setUp(self):
		frappe.local.response.pop("http_status_code", None)
		frappe.local.tc_logistics_envelope = False

	def test_flag_set_during_business_logic(self):
		seen: list[bool] = []

		@logistics_endpoint()
		def fn():
			seen.append(bool(getattr(frappe.local, "tc_logistics_envelope", False)))
			return None

		self.assertFalse(getattr(frappe.local, "tc_logistics_envelope", False))
		fn()
		self.assertEqual(seen, [True], "İş mantığı zarf bayrağı AÇIKKEN koşmalı")
		self.assertFalse(
			getattr(frappe.local, "tc_logistics_envelope", False),
			"Bayrak zarf dönüşünde kapanmalı — request'in devamı dedup'ı zehirlememeli",
		)

	def test_flag_cleared_after_error_path(self):
		@logistics_endpoint()
		def fn():
			raise frappe.PermissionError("yetkisiz")

		fn()
		self.assertFalse(getattr(frappe.local, "tc_logistics_envelope", False))


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
