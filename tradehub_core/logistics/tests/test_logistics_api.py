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


# ---------------------------------------------------------------------------
# Kimlik bilgisi denetimi (denetim 2026-08-28) — BULGU 1/2/4/5/7
#
# Her sınıf ölçülmüş bir açığı kilitler; gerekçeler ilgili docstring'lerde.
# ---------------------------------------------------------------------------


def _allowed_http_methods(fn) -> list[str] | None:
	"""Frappe'nin bu whitelist fonksiyonu için kabul ettiği HTTP metotları.

	`@frappe.whitelist()` metot listesini fonksiyonun ÜZERİNDE değil, global bir
	sözlükte tutuyor (`frappe.allowed_http_methods_for_whitelisted_func`);
	`fn.methods` diye bir öznitelik YOK — ona bakan bir test her zaman `None`
	görür ve sessizce hiçbir şey doğrulamaz.
	"""
	return frappe.allowed_http_methods_for_whitelisted_func.get(fn)


class TestWriteEndpointsArePostOnly(FrappeTestCase):
	"""Yazan/sır döndüren uçlar GET kabul ETMEMELİ.

	NEDEN: Frappe GET isteğinin sonunda transaction'ı ROLLBACK eder —
	`frappe.app.UNSAFE_HTTP_METHODS` yalnız POST/PUT/DELETE/PATCH içerir, GET
	YOK. ÖLÇÜLDÜ (2026-08-28): dört uç da `['GET','POST','PUT','DELETE']` ile
	kayıtlıydı; `GET .../reveal_carrier_secret` düz metin sırrı döndürüyor ve
	denetim satırını geri alıyordu (izsiz ifşa), üç yazma ucu ise `ok: true`
	dönüp yazmayı sessizce geri alıyordu.
	"""

	WRITE_ENDPOINTS = (
		"reveal_carrier_secret",
		"save_carrier_account",
		"update_logistics_settings",
		"set_feature_flag",
	)

	def test_write_endpoints_reject_get(self):
		for fname in self.WRITE_ENDPOINTS:
			with self.subTest(endpoint=fname):
				methods = _allowed_http_methods(getattr(admin, fname))
				self.assertIsNotNone(methods, f"{fname} whitelist kaydı bulunamadı")
				self.assertEqual(methods, ["POST"], f"{fname} yalnız POST kabul etmeli")

	def test_read_only_endpoints_remain_get_capable(self):
		"""Salt-okunur uçlar KIRILMAMALI — panel onları GET ile çağırıyor."""
		for fname in ("list_carrier_accounts", "get_carrier_account", "get_logistics_settings"):
			with self.subTest(endpoint=fname):
				self.assertIn("GET", _allowed_http_methods(getattr(admin, fname)) or [])


class TestCredentialAuditIsFailClosed(FrappeTestCase):
	"""Denetim satırı yazılamıyorsa sır ne DÖNER ne de YAZILIR.

	ÖLÇÜLDÜ (2026-08-28): `audit.log_decision` best-effort — istisnayı KENDİSİ
	yutup `None` dönüyor. `reveal_carrier_secret`'ın try/except'i bu yüzden hiç
	tetiklenmiyordu ve ADL insert'i kırıkken uç
	`{'ok': True, ... 'value': 'REALSECRETKEY123456'}` döndü, ADL sayacı artmadı.
	Düzeltme dönüş değerini kontrol ediyor.
	"""

	SECRET = "fail-closed-anahtar-77"

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.account = admin.save_carrier_account(
			values={
				"account_name": "Fail-closed denetim testi",
				"carrier": self.carrier,
				"environment": "Sandbox",
				"is_active": 0,
				"api_key": self.SECRET,
			}
		)["data"]["name"]
		# COMMIT ŞART: fail-closed yollar `logistics_endpoint._fail` üzerinden
		# `frappe.db.rollback()` çağırıyor — commit edilmemiş bir fixture o
		# noktada kaybolur ve test kendi kurulumunu yiyerek hata verir.
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("Carrier Account", {"name": self.account})
		frappe.db.commit()

	def test_reveal_denied_when_audit_row_cannot_be_written(self):
		import json

		with (
			mock.patch("tradehub_core.audit.log.log_decision", return_value=None),
			mock.patch("frappe.log_error"),
		):
			result = admin.reveal_carrier_secret(self.account, "api_key")

		self.assertFalse(result["ok"], "Denetim yazılamadıysa sır DÖNMEMELİ")
		self.assertNotIn(self.SECRET, json.dumps(result, default=str))

	def test_secret_write_rolled_back_when_audit_row_cannot_be_written(self):
		"""Yazma da fail-closed: denetim satırı yoksa yeni sır kalıcı olmaz."""
		with (
			mock.patch("tradehub_core.audit.log.log_decision", return_value=None),
			mock.patch("frappe.log_error"),
		):
			result = admin.save_carrier_account(
				name=self.account, values={"api_key": "izsiz-yazilmamali"}
			)
		self.assertFalse(result["ok"])

		# `logistics_endpoint._fail` rollback ettiği için eski sır yerinde
		doc = frappe.get_doc("Carrier Account", self.account)
		self.assertEqual(doc.get_password("api_key", raise_exception=False), self.SECRET)


class TestSecretWriteGate(FrappeTestCase):
	"""Gizli alan YAZMAK okumak kadar korunuyor mu — capability + denetim.

	ÖLÇÜLDÜ (2026-08-28): `save_carrier_account` `@logistics_endpoint()` idi —
	capability kapısı YOK, ADL satırı YOK. `carrier_credential.manage`
	capability'si ilan ediliyordu ama hiçbir yerde zorlanmıyordu.
	"""

	SECRET = "yazma-kapisi-anahtari-11"

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.account = admin.save_carrier_account(
			values={
				"account_name": "Yazma kapısı testi",
				"carrier": self.carrier,
				"environment": "Sandbox",
				"is_active": 0,
				"api_key": self.SECRET,
			}
		)["data"]["name"]
		# COMMIT ŞART: fail-closed yollar `logistics_endpoint._fail` üzerinden
		# `frappe.db.rollback()` çağırıyor — commit edilmemiş bir fixture o
		# noktada kaybolur ve test kendi kurulumunu yiyerek hata verir.
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("Carrier Account", {"name": self.account})
		frappe.db.commit()

	def test_secret_write_requires_capability(self):
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			result = admin.save_carrier_account(
				name=self.account, values={"api_key": "yetkisiz-yeni-sir"}
			)
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "CAPABILITY_REQUIRED")

	def test_non_secret_write_does_not_require_capability(self):
		"""Secret'a dokunmayan kayıt eski davranışta kalmalı — panel akışı kırılmasın."""
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			result = admin.save_carrier_account(
				name=self.account, values={"account_name": "Yalnız ad değişti"}
			)
		self.assertTrue(result["ok"], result)

	def test_secret_write_records_high_severity_audit_row(self):
		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			admin.save_carrier_account(name=self.account, values={"api_key": "yeni-sir-99"})

		log_decision.assert_called_once()
		_, kwargs = log_decision.call_args
		self.assertEqual(kwargs["action"], "carrier_account.write_secret")
		self.assertEqual(kwargs["severity"], "HIGH")
		self.assertEqual(kwargs["context"], {"fields": ["api_key"]})

	def test_audit_row_carries_field_name_not_value(self):
		"""ADL `context` maskesiz saklanıyor — sır oraya ASLA yazılmamalı."""
		import json

		with mock.patch("tradehub_core.audit.log.log_decision") as log_decision:
			admin.save_carrier_account(name=self.account, values={"api_key": "gizli-deger-abc"})

		_, kwargs = log_decision.call_args
		self.assertNotIn("gizli-deger-abc", json.dumps(kwargs, default=str))


class TestMaskedSecretIsNotWrittenBack(FrappeTestCase):
	"""Panelin gösterdiği maske geri geldiğinde gerçek sır KORUNMALI.

	ÖLÇÜLDÜ (2026-08-28): `values={'api_key': '•'*8}` sonrası `get_password()`
	`'••••••••'` döndü — gerçek sır yok oldu. `'*'*8` yalnız Frappe'nin kendi
	`is_dummy_password` (tamamı-yıldız) koruması sayesinde kurtuluyordu; `'…'`
	de sızıyordu.
	"""

	SECRET = "maske-testi-anahtari-33"

	def setUp(self):
		self.carrier = frappe.db.get_value("Logistics Provider", {"is_active": 1}, "name")
		self.account = admin.save_carrier_account(
			values={
				"account_name": "Maske geri yazma testi",
				"carrier": self.carrier,
				"environment": "Sandbox",
				"is_active": 0,
				"api_key": self.SECRET,
			}
		)["data"]["name"]
		# COMMIT ŞART: fail-closed yollar `logistics_endpoint._fail` üzerinden
		# `frappe.db.rollback()` çağırıyor — commit edilmemiş bir fixture o
		# noktada kaybolur ve test kendi kurulumunu yiyerek hata verir.
		frappe.db.commit()

	def tearDown(self):
		frappe.db.delete("Carrier Account", {"name": self.account})
		frappe.db.commit()

	def _stored_secret(self) -> str | None:
		return frappe.get_doc("Carrier Account", self.account).get_password(
			"api_key", raise_exception=False
		)

	def test_mask_characters_are_treated_as_no_op(self):
		for mask in ("•" * 8, "*" * 8, "●●●●", "···", "…", "-" * 6, "*•●"):
			with self.subTest(mask=mask):
				result = admin.save_carrier_account(name=self.account, values={"api_key": mask})
				self.assertTrue(result["ok"], result)
				self.assertEqual(self._stored_secret(), self.SECRET)

	def test_real_value_still_overwrites(self):
		"""Maske koruması gerçek bir güncellemeyi engellememeli."""
		admin.save_carrier_account(name=self.account, values={"api_key": "gercek-yeni-anahtar"})
		self.assertEqual(self._stored_secret(), "gercek-yeni-anahtar")

	def test_masked_write_needs_no_capability(self):
		"""No-op olduğu için capability de sorulmamalı."""
		with mock.patch(
			"tradehub_core.utils.permission_resolver.has_capability", return_value=False
		):
			result = admin.save_carrier_account(name=self.account, values={"api_key": "•••••"})
		self.assertTrue(result["ok"], result)


class TestIntegrationLogRetentionFloor(FrappeTestCase):
	"""Saklama süresine alt sınır — denetim izi ertesi gün imha edilemesin.

	ÖLÇÜLDÜ (2026-08-28): `validate` yalnız desi bölenini doğruluyordu;
	`integration_log_retention_days` `1` ve `-5` olarak KABUL edildi ve DB'ye
	yazıldı.
	"""

	def tearDown(self):
		frappe.db.rollback()
		frappe.clear_document_cache("Logistics Settings", "Logistics Settings")

	def _save(self, value) -> None:
		doc = frappe.get_doc("Logistics Settings")
		doc.integration_log_retention_days = value
		doc.save(ignore_permissions=True)

	def test_below_floor_rejected(self):
		from tradehub_core.logistics.constants import MIN_INTEGRATION_LOG_RETENTION_DAYS

		for value in (1, MIN_INTEGRATION_LOG_RETENTION_DAYS - 1):
			with self.subTest(value=value), self.assertRaises(frappe.ValidationError):
				self._save(value)

	def test_negative_rejected(self):
		"""Negatif "kapalı" anlamına gelmemeli — onu `0` ifade ediyor."""
		with self.assertRaises(frappe.ValidationError):
			self._save(-5)

	def test_zero_means_retention_disabled_and_is_allowed(self):
		self._save(0)
		self.assertEqual(
			frappe.db.get_single_value("Logistics Settings", "integration_log_retention_days"), 0
		)

	def test_floor_and_above_allowed(self):
		from tradehub_core.logistics.constants import MIN_INTEGRATION_LOG_RETENTION_DAYS

		for value in (MIN_INTEGRATION_LOG_RETENTION_DAYS, 90, 365):
			with self.subTest(value=value):
				self._save(value)
				self.assertEqual(
					frappe.db.get_single_value(
						"Logistics Settings", "integration_log_retention_days"
					),
					value,
				)
