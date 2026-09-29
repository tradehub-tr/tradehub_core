# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""MOGEM-685 Bulgu 1 / Adim B — tasiyici webhook'unun iki olculmus kusuru.

1. JSON KUSURU (olculdu 28 Eyl 2026, gercek HTTP): Frappe v15 JSON gövdede URL
   parametrelerini form_dict'e katmiyor (`frappe/app.py::make_form_dict`) →
   `?account=` kayboluyordu; dogru imzali her `application/json` istegi 401
   aliyordu. `test_logistics_webhook._post` hesabi uca DOGRUDAN argüman olarak
   verdigi icin bu yolu hic görmüyordu — buradaki `_http_post` istegi Frappe'nin
   kendi yolundan (make_form_dict + frappe.call) gecirir.
2. LOG SISIRME (olculdu): her imza reddi gövdenin 65.520 baytini loga yaziyordu.
   Artik hesap basina dakikada en fazla 20 satir, satirda en fazla 2 KB gövde.

    bench --site dev.localhost run-tests --module tradehub_core.logistics.tests.test_webhook_mogem685
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

import frappe

from tradehub_core.api.v1 import logistics_webhook as webhook_module
from tradehub_core.logistics.constants import CACHE_PREFIX, WEBHOOK_SIGNATURE_HEADER
from tradehub_core.logistics.tests.test_logistics_webhook import _sign, _WebhookTestBase


class TestWebhookMogem685(_WebhookTestBase):
	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		# Registry'de OLMAYAN saglayici: imza saf fallback-HMAC ile dogrulanir.
		cls.provider: str = cls._create_provider(f"m685wh{cls.suffix}")
		cls.account: str = cls._create_account(cls.provider, label="M685 Hesap", secret=cls.secret)
		# Tasiyici basina tek aktif platform hesabi kurali → ikinci hesap ayri saglayicida.
		cls.provider_b: str = cls._create_provider(f"m685wb{cls.suffix}")
		cls.account_b: str = cls._create_account(
			cls.provider_b, label="M685 Ikinci Hesap", secret=f"{cls.secret}-b"
		)

	def setUp(self) -> None:
		super().setUp()
		self._tavan_sifirla()

	def tearDown(self) -> None:
		self._tavan_sifirla()
		super().tearDown()

	def _tavan_sifirla(self) -> None:
		frappe.cache.delete_keys(f"{CACHE_PREFIX}webhook:failed_log:")

	def _json(self, **ek: Any) -> bytes:
		return json.dumps(
			{"tracking_number": f"TRK{frappe.generate_hash(length=10).upper()}", "status_code": "DLV", **ek}
		).encode("utf-8")

	def _http_post(self, account: str, body: bytes, signature: str | None, content_type: str) -> Any:
		"""Gercek HTTP yolu: URL parametresi + gövde → make_form_dict → frappe.call."""
		from frappe.app import make_form_dict
		from frappe.utils import set_request

		basliklar = {"Content-Type": content_type}
		if signature is not None:
			basliklar[WEBHOOK_SIGNATURE_HEADER] = signature
		onceki = (
			getattr(frappe.local, "request", None),
			frappe.local.response,
			frappe.local.form_dict,
			getattr(frappe.local, "request_ip", None),
		)
		try:
			set_request(
				method="POST",
				path="/api/method/tradehub_core.api.v1.logistics_webhook.receive_carrier_webhook",
				query_string={"account": account},
				data=body,
				headers=basliklar,
			)
			frappe.local.request_ip = self.IP
			make_form_dict(frappe.local.request)
			frappe.local.form_dict.cmd = f"m685-{self.suffix}"
			frappe.local.response = frappe._dict()
			sonuc = frappe.call(webhook_module.receive_carrier_webhook, **frappe.local.form_dict)
			durum = frappe.local.response.get("http_status_code", 200)
		finally:
			(
				frappe.local.request,
				frappe.local.response,
				frappe.local.form_dict,
				frappe.local.request_ip,
			) = onceki
		return frappe._dict(status=durum, result=sonuc)

	# ── 1 · JSON kusuru ──────────────────────────────────────────────────

	def test_json_icerik_tipi_gercek_http_yolundan_kabul_edilir(self) -> None:
		body = self._json()
		with self._flag(True), self._spy_enqueue() as kuyruk:
			out = self._http_post(self.account, body, _sign(body, self.secret), "application/json")
		self.assertEqual((out.status, out.result), (200, {"ok": True}))
		kuyruk.assert_called_once()
		self.assertEqual(kuyruk.call_args.kwargs.get("account"), self.account)

	def test_duz_metin_icerik_tipi_de_kabul_edilir(self) -> None:
		# Pozitif kontrol: düzeltmeden önce de calisan yol bozulmadi.
		body = self._json()
		with self._flag(True), self._spy_enqueue():
			out = self._http_post(self.account, body, _sign(body, self.secret), "text/plain")
		self.assertEqual((out.status, out.result), (200, {"ok": True}))

	def test_govdedeki_account_alani_adres_satirini_ezmez(self) -> None:
		# Gövde B hesabini söylüyor, adres A'yi; imza A'nin sirriyla → A olarak kabul.
		body = self._json(account=self.account_b)
		with self._flag(True), self._spy_enqueue() as kuyruk:
			out = self._http_post(self.account, body, _sign(body, self.secret), "application/json")
		self.assertEqual(out.status, 200)
		self.assertEqual(kuyruk.call_args.kwargs.get("account"), self.account)

		# Ters yön: adres bilinmeyen hesap, gövde gecerli hesap + onun imzasi → 401.
		body = self._json(account=self.account)
		with self._flag(True), self._spy_enqueue() as kuyruk:
			out = self._http_post("YOK-BOYLE-HESAP", body, _sign(body, self.secret), "application/json")
		self.assertEqual((out.status, out.result), (401, {"ok": False}))
		kuyruk.assert_not_called()

	# ── 2 · Log sisirme ──────────────────────────────────────────────────

	def test_imza_reddi_logu_hesap_basina_dakikada_20_ile_sinirli(self) -> None:
		once = self._log_names(self.account)
		with self._flag(True), self._spy_enqueue():
			durumlar = {self._post(self.account, self._json(), signature=None).status for _ in range(25)}
		self.assertEqual(durumlar, {401}, "tavan asilsa da yanit ayni 401 kalmali")
		self.assertEqual(len(self._new_logs(self.account, once)), webhook_module._FAILED_LOG_PER_MINUTE)

	def test_tavan_hesaplar_arasinda_paylasilmaz(self) -> None:
		with self._flag(True), self._spy_enqueue():
			for _ in range(webhook_module._FAILED_LOG_PER_MINUTE):
				self._post(self.account, self._json(), signature=None)
			once_b = self._log_names(self.account_b)
			self._post(self.account_b, self._json(), signature=None)
		self.assertEqual(len(self._new_logs(self.account_b, once_b)), 1)

	def test_imza_reddi_logu_govdeyi_2kb_ile_kirpar_ve_yarim_sirri_birakmaz(self) -> None:
		# Sir tam kirpma sinirina denk getirilir: sinirin önündeki ön ek maskelenemez,
		# log katmaninin kuyruk temizligi onu kesmeli (log.py strip_partial_secret_tail).
		dolgu = "x" * (webhook_module._FAILED_LOG_BODY_BYTES - 40)
		body = self._json(note=dolgu + self.secret + "y" * 8000)
		self.assertGreater(len(body), 10_000)
		once = self._log_names(self.account)
		with self._flag(True), self._spy_enqueue():
			self._post(self.account, body, signature=None)
		(log,) = self._new_logs(self.account, once)
		saklanan: str = log.request_body or ""
		self.assertLess(len(saklanan.encode("utf-8")), 4096, "gövde 2 KB ile kirpilmadi")
		self.assertIn(str(len(body)), saklanan, "orijinal boyut kayda gecmeli")
		self.assertIn("tracking_number", saklanan)  # AC-2: gövde maskeli olarak duruyor
		self.assertNotIn(self.secret[:12], saklanan, "kirpma sinirinda yarim sir ham kaldi")

	def test_kabul_edilen_istekte_govde_kirpilmaz(self) -> None:
		body = self._json(note="z" * 10_000)
		once = self._log_names(self.account)
		with self._flag(True), self._spy_enqueue():
			self._post(self.account, body, signature=_sign(body, self.secret))
		(log,) = self._new_logs(self.account, once)
		self.assertEqual(int(log.succeeded), 1)
		self.assertNotIn("_truncated", log.request_body or "")

	def test_redis_yoksa_log_yine_yazilir(self) -> None:
		once = self._log_names(self.account)
		with (
			self._flag(True),
			self._spy_enqueue(),
			mock.patch.object(frappe.cache, "incr", side_effect=ConnectionError("redis yok")),
		):
			out = self._post(self.account, self._json(), signature=None)
		self.assertEqual(out.status, 401)
		self.assertEqual(len(self._new_logs(self.account, once)), 1)
