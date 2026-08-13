# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik API sözleşmesi testleri (Faz B.6 + B.7).

Çalıştırma:
	docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \\
	  bench --site dev.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_logistics_api"

Bu süit **sözleşmeyi** kilitler, implementasyonu değil. Yanıt anahtarları,
sayfalama alanları, hata kodları ve gizli bilgi sınırı burada sabitlenir; Faz D
ve E'de yazılacak her ekran bunlara güvenecek.
"""

from __future__ import annotations

import unittest.mock as mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.v1 import logistics_admin as admin
from tradehub_core.api.v1 import logistics_catalog as catalog


class TestCatalogListContract(FrappeTestCase):
	"""Liste yanıtının şekli — panelin tablo bileşeni buna bağlanacak."""

	def test_list_returns_pagination_envelope(self):
		result = catalog.list_catalog("logistics_provider", page_size=3)
		self.assertTrue(result["ok"])
		data = result["data"]
		for key in ("items", "total", "page", "page_size"):
			self.assertIn(key, data, f"Sayfalama zarfında {key} olmalı")
		self.assertLessEqual(len(data["items"]), 3)
		self.assertEqual(data["total"], 8, "Seed edilmiş 8 sağlayıcı")

	def test_list_fields_match_contract(self):
		"""Liste yalnız sözleşmedeki alanları döndürür — DocType şeması sızmaz."""
		spec = catalog.CATALOGS["logistics_provider"]
		row = catalog.list_catalog("logistics_provider", page_size=1)["data"]["items"][0]
		self.assertEqual(set(row.keys()), set(spec.list_fields))

	def test_page_size_is_clamped(self):
		"""İstemci ne isterse istesin üst sınır aşılmaz."""
		data = catalog.list_catalog("logistics_provider", page_size=99999)["data"]
		self.assertEqual(data["page_size"], catalog.MAX_PAGE_SIZE)

	def test_search_narrows_results(self):
		data = catalog.list_catalog("shipment_exception_code", search="hasar")["data"]
		self.assertEqual([i["exception_code"] for i in data["items"]], ["DAMAGED"])

	def test_is_active_filter(self):
		passive = catalog.list_catalog("shipping_method", is_active=0)["data"]
		self.assertGreaterEqual(passive["total"], 5, "LOG-040 beş yöntemi pasifleştirdi")

	def test_unknown_catalog_rejected(self):
		result = catalog.list_catalog("tabUser")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")

	def test_undefined_filter_field_rejected(self):
		"""Sözleşmede olmayan alanla filtrelemek sessizce boş sonuç dönmemeli."""
		result = catalog.list_catalog("logistics_provider", filters={"support_email": "x"})
		self.assertFalse(result["ok"])
		self.assertIn("support_email", result["error"]["message"])


class TestCatalogDetailContract(FrappeTestCase):
	def test_detail_includes_child_tables(self):
		data = catalog.get_catalog_item("logistics_provider", "YK")["data"]
		self.assertIn("operating_channels", data)
		self.assertEqual(data["operating_channels"][0]["shipping_channel"], "CARGO")

	def test_child_rows_expose_only_contract_fields(self):
		"""Frappe iç alanları (owner, creation, parent, docstatus) SIZMAMALI."""
		data = catalog.get_catalog_item("logistics_provider", "YK")["data"]
		row = data["operating_channels"][0]
		self.assertEqual(set(row.keys()), {"shipping_channel", "channel_name"})

	def test_detail_is_json_serializable(self):
		"""Yanıt doğrudan HTTP'ye gidebilmeli — datetime/Document kalıntısı olmamalı."""
		import json

		data = catalog.get_catalog_item("package_type", "BOX")["data"]
		json.dumps(data)  # hata fırlatmamalı


class TestCatalogWriteContract(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_create_and_update_roundtrip(self):
		created = catalog.create_catalog_item(
			"vehicle_type",
			{"vehicle_name": "Test Araç", "vehicle_code": "ZZTEST", "max_weight_kg": 100},
		)
		self.assertTrue(created["ok"])
		name = created["data"]["name"]

		updated = catalog.update_catalog_item("vehicle_type", name, {"max_weight_kg": 250})
		self.assertTrue(updated["ok"])
		self.assertEqual(frappe.db.get_value("Vehicle Type", name, "max_weight_kg"), 250)

	def test_undefined_write_field_rejected(self):
		"""Sözleşmede olmayan alan sessizce yok sayılmaz — açık hata verir."""
		result = catalog.create_catalog_item(
			"vehicle_type",
			{"vehicle_name": "X", "vehicle_code": "ZZX", "gizli_alan": 1},
		)
		self.assertFalse(result["ok"])
		self.assertIn("gizli_alan", result["error"]["message"])

	def test_toggle_active_instead_of_delete(self):
		created = catalog.create_catalog_item(
			"vehicle_type", {"vehicle_name": "Kapatılacak", "vehicle_code": "ZZOFF"}
		)
		name = created["data"]["name"]
		result = catalog.set_catalog_item_active("vehicle_type", name, 0)
		self.assertEqual(result["data"]["is_active"], 0)

	def test_controller_validation_surfaces_as_error_code(self):
		"""DocType validate'i zarf üzerinden anlaşılır kodla dönmeli."""
		result = catalog.create_catalog_item(
			"shipping_method",
			{"method_name": "ZZ Ters Aralık", "min_days": 9, "max_days": 2},
		)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "VALIDATION_ERROR")


class TestCarrierAccountSecretBoundary(FrappeTestCase):
	"""Gizli kimlik bilgisi liste/detay yanıtında ASLA dönmez."""

	SECRET = "cok-gizli-anahtar-42"

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		created = admin.save_carrier_account(
			values={
				"account_name": "Secret Sınır Testi",
				"carrier": self.carrier,
				"environment": "Sandbox",
				"is_active": 1,
				"api_key": self.SECRET,
			}
		)
		self.account = created["data"]["name"]

	def tearDown(self):
		frappe.db.delete("Carrier Account", {"name": self.account})
		frappe.db.commit()

	def test_detail_reports_presence_not_value(self):
		data = admin.get_carrier_account(self.account)["data"]
		self.assertNotIn("api_key", data)
		self.assertTrue(data["has_api_key"])

	def test_secret_never_appears_in_serialized_response(self):
		import json

		data = admin.get_carrier_account(self.account)["data"]
		self.assertNotIn(self.SECRET, json.dumps(data, default=str))

	def test_list_response_carries_no_secret(self):
		import json

		data = admin.list_carrier_accounts(carrier=self.carrier)["data"]
		self.assertNotIn(self.SECRET, json.dumps(data, default=str))

	def test_reveal_requires_capability(self):
		"""NEGATİF: capability olmadan gizli değer alınamaz."""
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			result = admin.reveal_carrier_secret(self.account, "api_key")
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "CAPABILITY_REQUIRED")

	def test_reveal_returns_value_with_capability(self):
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=True
		):
			result = admin.reveal_carrier_secret(self.account, "api_key")
		self.assertEqual(result["data"]["value"], self.SECRET)

	def test_reveal_writes_audit_record(self):
		"""Credential görüntüleme izlenebilir olmalı."""
		with (
			mock.patch(
				"tradehub_core.utils.permission_resolver.has_capability", return_value=True
			),
			mock.patch("tradehub_core.audit.log.log_decision") as log_decision,
		):
			admin.reveal_carrier_secret(self.account, "api_key")

		log_decision.assert_called_once()
		_, kwargs = log_decision.call_args
		self.assertEqual(kwargs["action"], "carrier_account.reveal_secret")
		self.assertEqual(kwargs["severity"], "HIGH")

	def test_reveal_rejects_non_secret_field(self):
		"""Rastgele alan okuma yolu açılmamalı."""
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=True
		):
			result = admin.reveal_carrier_secret(self.account, "account_name")
		self.assertFalse(result["ok"])

	def test_blank_secret_does_not_erase_stored_value(self):
		"""Panel formu her kaydettiğinde secret'ı silmemeli."""
		admin.save_carrier_account(
			name=self.account, values={"account_name": "Yeni Ad", "api_key": ""}
		)
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=True
		):
			value = admin.reveal_carrier_secret(self.account, "api_key")["data"]["value"]
		self.assertEqual(value, self.SECRET)


class TestSettingsAndFlags(FrappeTestCase):
	def tearDown(self):
		frappe.db.rollback()

	def test_settings_response_lists_all_known_flags(self):
		"""Panel bayrak listesini kendi kodunda tutmak zorunda kalmamalı."""
		from tradehub_core.logistics.constants import LOGISTICS_FEATURE_FLAGS

		flags = admin.get_logistics_settings()["data"]["feature_flags"]
		self.assertEqual(set(flags), set(LOGISTICS_FEATURE_FLAGS))

	def test_set_feature_flag_toggles_single_key(self):
		before = admin.get_logistics_settings()["data"]["feature_flags"]
		admin.set_feature_flag("multi_leg_enabled", 1)
		after = admin.get_logistics_settings()["data"]["feature_flags"]

		self.assertTrue(after["multi_leg_enabled"])
		# Diğer bayraklar değişmemeli — tüm sözlüğü göndermek ezme yaratırdı
		for flag in before:
			if flag != "multi_leg_enabled":
				self.assertEqual(before[flag], after[flag])

	def test_unknown_flag_rejected(self):
		result = admin.set_feature_flag("uydurma_bayrak", 1)
		self.assertFalse(result["ok"])

	def test_unknown_settings_field_rejected(self):
		result = admin.update_logistics_settings({"gizli_ayar": 1})
		self.assertFalse(result["ok"])


class TestPermissionsEndpoint(FrappeTestCase):
	"""Panelin aksiyon görünürlüğünü kuracağı yanıt."""

	def test_reports_all_logistics_capabilities(self):
		data = admin.get_logistics_permissions()["data"]
		self.assertEqual(
			set(data["capabilities"]), set(admin.LOGISTICS_CAPABILITIES)
		)

	def test_reports_catalog_doctype_permissions(self):
		data = admin.get_logistics_permissions()["data"]
		self.assertEqual(set(data["doctype_permissions"]), set(catalog.CATALOGS))
		for perms in data["doctype_permissions"].values():
			self.assertEqual(set(perms), {"read", "write", "create", "delete"})

	def test_reports_module_enabled_state(self):
		data = admin.get_logistics_permissions()["data"]
		self.assertIn("module_enabled", data)
		self.assertIsInstance(data["module_enabled"], bool)
