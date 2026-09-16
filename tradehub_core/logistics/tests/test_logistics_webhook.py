# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""09-BE webhook dilimi / BE-5: guest carrier webhook ucu test paketi (AC-1..11 + W2/W3/W4).

Calistirma:
	docker exec istoccom-backend-1 bash -lc "cd /home/frappe/frappe-bench && \\
	  bench --site tradehub.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_logistics_webhook"

Bloklar:

	TestWebhookEndpointContract   AC-1 kabul+log+enqueue, AC-2 maskeli ret, AC-3 imza
	                              delegasyonu, AC-4+W2 BES ret yolunun bayt-esitligi ve
	                              sizinti yoklugu, AC-5 413, AC-7 katman-1 dedupe + W4 TTL
	TestWebhookRateLimit          AC-6 dusuk limitli davranis + W3 key'siz IP kovasi
	TestWebhookEndToEnd           AC-7 katman-2/3, AC-8 uctan uca gecis + denorm,
	                              AC-9 STATUS_UNMAPPED, AC-10 tenant guard, AC-11 adapter'siz

TASARIM NOTLARI:
- `frappe.enqueue` testlerde ASLA gercek RQ kuyruğuna gitmez: ret/dedupe testlerinde spy
  (job'suzluk KANITI icin), e2e testlerde `frappe.call` ile SENKRON kosulur. Boylece
  "run-tests icinde enqueue'nin senkron/asenkron davranisi" tuzagina (spec riski)
  hicbir test bagimli degildir.
- Zaman-bombasi YOK: event_time degerleri `now_datetime`'dan uretilir, W4 TTL assert'i
  sabit bir gelecek tarihe degil goreli pencereye bakar.
- Redis dedupe isaretleri transaction'a tabi DEGILDIR — her tearDown'da temizlenir.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import re
import unittest
import unittest.mock as mock
from typing import Any

import frappe
from frappe.rate_limiter import rate_limit
from frappe.tests.utils import FrappeTestCase

import tradehub_core.api.v1.logistics_webhook as webhook_module
import tradehub_core.logistics.adapters.signature as signature_module
from tradehub_core.logistics.adapters.carriers.mock_carrier import MockCarrierAdapter
from tradehub_core.logistics.adapters.registry import _CARRIER_REGISTRY, register_carrier
from tradehub_core.logistics.adapters.signature import verify_hmac_signature
from tradehub_core.logistics.constants import (
	CACHE_PREFIX,
	MAX_WEBHOOK_BODY_BYTES,
	WEBHOOK_DEDUPE_TTL_SECONDS,
	WEBHOOK_SIGNATURE_HEADER,
	WEBHOOK_SIGNATURE_PREFIX,
	ShipmentStatus,
)
from tradehub_core.logistics.integration.masking import MASK
from tradehub_core.logistics.services.shipment_service import transition_status
from tradehub_core.logistics.services.split_engine import create_shipment_draft_from_order

#: AC-1 enqueue sozlesmesi — job yolu degisirse test KIRILMALI (endpoint sabitiyle ayni).
_JOB_METHOD: str = "tradehub_core.logistics.services.tracking_service.process_webhook_event"


def _sign(body: bytes, secret: str, prefix: str = WEBHOOK_SIGNATURE_PREFIX) -> str:
	"""Beklenen imza basligini uretir: <prefix><hex(HMAC-SHA256(secret, body))>."""
	return prefix + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def _ensure_role(role_name: str) -> None:
	"""Rol yoksa olustur (idempotent — FrappeTestCase class-sonu rollback'iyle temiz)."""
	if frappe.db.exists("Role", role_name):
		return
	role = frappe.new_doc("Role")
	role.role_name = role_name
	role.desk_access = 0
	role.is_custom = 1
	role.insert(ignore_permissions=True)


def _make_user(email: str, roles: tuple[str, ...] = ()) -> str:
	"""Test kullanicisi olusturur ve rollerini baglar (test_shipment_core deseni)."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Webhook",
				"last_name": "Test",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	if roles:
		frappe.get_doc("User", email).add_roles(*roles)
	return email


def _make_seller_profile(user: str, label: str) -> str:
	"""Admin Seller Profile fixture'i (autoname=field:seller_code)."""
	return (
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": f"Webhook Test {label}",
				"seller_code": f"WHKTEST-{frappe.generate_hash(length=8)}",
				"company_name": f"Webhook Test {label} A.S.",
				"user": user,
				"email": user,
			}
		)
		.insert(ignore_permissions=True, ignore_mandatory=True)
		.name
	)


class _WebhookTestBase(FrappeTestCase):
	"""Ortak fixture uretimi + endpoint cagri/log yardimcilari."""

	#: Testlerin varsayilan istemci IP'si (TEST-NET-3 — gercek trafikle cakismaz).
	IP: str = "203.0.113.77"

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.suffix: str = frappe.generate_hash(length=8).lower()
		# Deger-tabanli redaksiyon testi icin yeterince uzun, calisma basina benzersiz sir.
		cls.secret: str = f"whsec-{cls.suffix}-{frappe.generate_hash(length=12)}"

	def setUp(self) -> None:
		frappe.set_user("Administrator")

	def tearDown(self) -> None:
		frappe.set_user("Administrator")
		# Dedupe isaretleri Redis'te yasar, DB rollback'i onlari temizlemez —
		# birikirse sonraki kosumun ayni-govde testleri yanlis "duplicate" gorur.
		frappe.cache.delete_keys(f"{CACHE_PREFIX}webhook:seen:")

	# -------------------------------------------------------------------
	# Fixture yardimcilari
	# -------------------------------------------------------------------

	@classmethod
	def _create_provider(cls, code: str) -> str:
		"""Logistics Provider fixture'i — docname == provider_code (autoname)."""
		return (
			frappe.get_doc(
				{
					"doctype": "Logistics Provider",
					"provider_name": f"Webhook Test {code}",
					"provider_code": code,
					"is_active": 1,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)

	@classmethod
	def _create_account(
		cls,
		carrier: str,
		*,
		label: str,
		seller_profile: str | None = None,
		secret: str | None = None,
		active: bool = True,
	) -> str:
		"""Carrier Account fixture'i (webhook_secret Password alani insert'te sifrelenir)."""
		doc = frappe.get_doc(
			{
				"doctype": "Carrier Account",
				"account_name": label,
				"carrier": carrier,
				"seller_profile": seller_profile,
				"environment": "Sandbox",
				"is_active": 1 if active else 0,
				"webhook_secret": secret,
			}
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	# -------------------------------------------------------------------
	# Endpoint cagrisi + enqueue kontrolu
	# -------------------------------------------------------------------

	def _post(
		self,
		account: str | None,
		body: bytes,
		signature: str | None = None,
		headers: dict[str, str] | None = None,
	) -> Any:
		"""Endpoint'i GERCEK bir werkzeug request'iyle cagirir ve zarfi dondurur.

		Donen frappe._dict: status (int), result (dict), payload (sort_keys'li
		JSON bayt dizisi — bayt-esitlik karsilastirmalari icin) ve response
		(frappe.local.response anlik goruntusu — sizinti denetimi icin).
		"""
		from frappe.utils import set_request

		header_map: dict[str, str] = dict(headers or {})
		if signature is not None:
			header_map[WEBHOOK_SIGNATURE_HEADER] = signature

		previous_request = getattr(frappe.local, "request", None)
		previous_response = frappe.local.response
		previous_form_dict = frappe.local.form_dict
		previous_ip = getattr(frappe.local, "request_ip", None)
		try:
			set_request(
				method="POST",
				path="/api/method/tradehub_core.api.v1.logistics_webhook.receive_carrier_webhook",
				data=body,
				headers=header_map,
			)
			frappe.local.request_ip = self.IP
			# Rate limiter anahtari `rl:{cmd}:{ip}` — calisma basina benzersiz cmd,
			# ardisik bench kosumlarinin ayni 60sn penceresinde sayac paylasmasini onler.
			frappe.local.form_dict = frappe._dict(cmd=f"whtest-{self.suffix}")
			frappe.local.response = frappe._dict()
			result = webhook_module.receive_carrier_webhook(account=account)
			response_snapshot = dict(frappe.local.response)
		finally:
			frappe.local.request = previous_request
			frappe.local.response = previous_response
			frappe.local.form_dict = previous_form_dict
			frappe.local.request_ip = previous_ip

		return frappe._dict(
			status=response_snapshot.get("http_status_code", 200),
			result=result,
			payload=json.dumps(result, sort_keys=True, ensure_ascii=False).encode("utf-8"),
			response=response_snapshot,
		)

	def _spy_enqueue(self) -> Any:
		"""frappe.enqueue'yu job KOSMADAN kaydeden yama (job'suzluk kaniti icin)."""
		return mock.patch("frappe.enqueue")

	def _sync_enqueue(self) -> Any:
		"""Job'u worker gibi SENKRON kosan enqueue yamasi (e2e testler).

		`frappe.call` cagriyi imza farkindaligiyla yapar: endpoint'in gecirdigi
		fazladan `environment` kwarg'ini eler. NOT — gercek worker (`execute_job`)
		`method(**kwargs)` cagirir ve `process_webhook_event` imzasinda
		`environment` OLMADIGI icin orada TypeError uretir; bu BE-3/BE-4 imza
		uyusmazligi ayri bulgu olarak raporlandi, BE-5 kapsami geregi burada
		DUZELTILMEZ (test frappe.call semantigiyle isler mantigini dogrular).
		"""

		def run(method: str, queue: str | None = None, **kwargs: Any) -> None:
			self.assertEqual(queue, "short", "webhook job'u 'short' kuyruguna gitmeli")
			frappe.call(method, **kwargs)

		return mock.patch("frappe.enqueue", side_effect=run)

	def _flag(self, enabled: bool) -> Any:
		"""Endpoint'in feature-flag kapisini deterministik hale getirir."""
		return mock.patch.object(webhook_module, "is_enabled", return_value=enabled)

	# -------------------------------------------------------------------
	# Inbound log yardimcilari
	# -------------------------------------------------------------------

	def _log_names(self, account: str) -> set[str]:
		# get_all GEREKCESI: test kodu Administrator ile kosuyor, sistem okumasi.
		return {
			row.name
			for row in frappe.get_all("Carrier Integration Log", filters={"carrier_account": account})
		}

	def _new_logs(self, account: str, before: set[str]) -> list[Any]:
		return [frappe.get_doc("Carrier Integration Log", name) for name in self._log_names(account) - before]

	def _single_new_log(self, account: str, before: set[str]) -> Any:
		logs = self._new_logs(account, before)
		self.assertEqual(len(logs), 1, "tam olarak BIR yeni inbound log bekleniyordu")
		return logs[0]


class TestWebhookEndpointContract(_WebhookTestBase):
	"""Endpoint sozlesmesi: kabul, ret tekduzeligi, boyut, imza delegasyonu, dedupe."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		cls.code_mock: str = f"mockwh{cls.suffix}"
		register_carrier(cls.code_mock, MockCarrierAdapter)
		cls.addClassCleanup(_CARRIER_REGISTRY.pop, cls.code_mock, None)

		cls.provider_mock: str = cls._create_provider(cls.code_mock)
		# Registry'de OLMAYAN saglayicilar: saf fallback (W1) ve ozel ret vakalari.
		cls.provider_plain: str = cls._create_provider(f"plainwh{cls.suffix}")
		cls.provider_idle: str = cls._create_provider(f"idlewh{cls.suffix}")
		cls.provider_nosecret: str = cls._create_provider(f"nosecwh{cls.suffix}")

		cls.account: str = cls._create_account(cls.provider_mock, label="WH Ana Hesap", secret=cls.secret)
		cls.account_plain: str = cls._create_account(
			cls.provider_plain, label="WH Adaptersiz Hesap", secret=cls.secret
		)
		cls.account_idle: str = cls._create_account(
			cls.provider_idle, label="WH Pasif Hesap", secret=cls.secret, active=False
		)
		cls.account_nosecret: str = cls._create_account(
			cls.provider_nosecret, label="WH Sirsiz Hesap", secret=None
		)

	def _body(self, note: str | None = None) -> bytes:
		"""Benzersiz mock webhook govdesi (dedupe katmanlari testler arasi cakismasin)."""
		payload: dict[str, Any] = {
			"tracking_number": f"TRK{frappe.generate_hash(length=10).upper()}",
			"status_code": "DLV",
			"status_text": "Teslim edildi.",
			"event_time": frappe.utils.now_datetime().isoformat(),
		}
		if note is not None:
			payload["note"] = note
		return json.dumps(payload).encode("utf-8")

	# -------------------------------------------------------------- AC-1
	def test_ac1_valid_signature_accepted_logged_and_enqueued(self) -> None:
		"""Gecerli imza: 200 {ok:true} + succeeded=1 inbound log + short-queue enqueue."""
		body = self._body()
		before = self._log_names(self.account)

		with self._flag(True), self._spy_enqueue() as enqueue_spy:
			out = self._post(self.account, body, signature=_sign(body, self.secret))

		self.assertEqual(out.status, 200)
		self.assertEqual(out.result, {"ok": True})

		enqueue_spy.assert_called_once()
		args, kwargs = enqueue_spy.call_args
		self.assertEqual(args[0], _JOB_METHOD)
		self.assertEqual(kwargs.get("queue"), "short")
		self.assertEqual(kwargs.get("account"), self.account)
		self.assertEqual(bytes(kwargs.get("raw_body")), body)
		self.assertIn(WEBHOOK_SIGNATURE_HEADER, dict(kwargs.get("headers") or {}))

		log = self._single_new_log(self.account, before)
		self.assertEqual(log.direction, "inbound")
		self.assertEqual(log.operation, "webhook")
		self.assertEqual(int(log.succeeded), 1)
		self.assertEqual(int(log.http_status), 200)
		self.assertFalse(log.error_code)

	# -------------------------------------------------------------- AC-2
	def test_ac2_bad_or_missing_signature_rejected_with_masked_log(self) -> None:
		"""Imza yanlis/eksik: 401, job YOK, SIGNATURE_INVALID log, govde MASKELI."""
		cases: tuple[tuple[str, str | None], ...] = (
			("imza-yanlis", "WRONG"),  # yer tutucu — asagida govdeye gore uretilir
			("imza-eksik", None),
		)
		for label, marker in cases:
			with self.subTest(case=label):
				# Govdeye BILEREK sizdirilmis webhook_secret: log katmani deger-tabanli
				# redaksiyonla maskelemek zorunda (AC-2'nin "yalniz maskeli" kosulu).
				body = self._body(note=self.secret)
				signature = _sign(body, f"kotu-{self.suffix}") if marker else None
				before = self._log_names(self.account)

				with self._flag(True), self._spy_enqueue() as enqueue_spy:
					out = self._post(self.account, body, signature=signature)

				self.assertEqual(out.status, 401)
				self.assertEqual(out.result, {"ok": False})
				enqueue_spy.assert_not_called()

				log = self._single_new_log(self.account, before)
				self.assertEqual(int(log.succeeded), 0)
				self.assertEqual(log.error_code, "SIGNATURE_INVALID")
				self.assertEqual(int(log.http_status), 401)
				stored: str = log.request_body or ""
				self.assertNotIn(self.secret, stored, "webhook_secret inbound log'a DUZ yazildi")
				self.assertIn(MASK, stored)
				self.assertIn("tracking_number", stored)  # govde kirpilmis degil, maskelenmis

	# -------------------------------------------------------------- AC-3
	def test_ac3_endpoint_delegates_to_adapter_when_resolvable(self) -> None:
		"""W1: adapter cozulebiliyorsa imza adapter'a delege edilir (compare_digest'e iner)."""
		body = self._body()
		with (
			self._flag(True),
			self._spy_enqueue(),
			mock.patch.object(
				MockCarrierAdapter,
				"verify_webhook_signature",
				autospec=True,
				side_effect=MockCarrierAdapter.verify_webhook_signature,
			) as adapter_spy,
			mock.patch.object(
				webhook_module, "verify_hmac_signature", wraps=verify_hmac_signature
			) as fallback_spy,
			mock.patch.object(
				signature_module.hmac, "compare_digest", wraps=hmac.compare_digest
			) as digest_spy,
		):
			out = self._post(self.account, body, signature=_sign(body, self.secret))

		self.assertEqual(out.status, 200)
		adapter_spy.assert_called_once()
		fallback_spy.assert_not_called()  # adapter yolu secildi, fallback devrede degil
		digest_spy.assert_called_once()  # AC-3 kilidi: karsilastirma '==' degil compare_digest

	def test_ac3_endpoint_falls_back_to_pure_hmac_without_adapter(self) -> None:
		"""W1: adapter'siz hesapta AYNI saf fonksiyon (verify_hmac_signature) kosar."""
		body = self._body()
		with (
			self._flag(True),
			self._spy_enqueue() as enqueue_spy,
			mock.patch.object(
				webhook_module, "verify_hmac_signature", wraps=verify_hmac_signature
			) as fallback_spy,
			mock.patch.object(
				signature_module.hmac, "compare_digest", wraps=hmac.compare_digest
			) as digest_spy,
		):
			out = self._post(self.account_plain, body, signature=_sign(body, self.secret))

		self.assertEqual(out.status, 200)  # AC-11'in endpoint kolu: adapter'siz + gecerli imza = 200
		fallback_spy.assert_called_once()
		digest_spy.assert_called_once()
		enqueue_spy.assert_called_once()

	# -------------------------------------------------------- AC-4 + W2
	def test_ac4_w2_all_reject_paths_are_byte_identical(self) -> None:
		"""BES ret yolu bayt-bayt AYNI 401; icteki exception istemciye SIZMAZ (W2)."""
		body = self._body()
		canary = f"W2-KANARYA-{self.suffix}"
		observed: list[tuple[str, int, bytes]] = []

		def capture(label: str, out: Any) -> None:
			observed.append((label, out.status, out.payload))
			self.assertEqual(
				dict(out.response),
				{"http_status_code": 401},
				f"{label}: yanit zarfina status disinda anahtar sizdi",
			)

		with self._spy_enqueue() as enqueue_spy:
			with self._flag(True):
				capture(
					"imza-yanlis",
					self._post(self.account, body, signature=_sign(body, f"kotu-{self.suffix}")),
				)
				capture(
					"hesap-yok",
					self._post(f"CA-YOK-{self.suffix}", body, signature=_sign(body, self.secret)),
				)
				capture(
					"hesap-pasif",
					self._post(self.account_idle, body, signature=_sign(body, self.secret)),
				)
				capture(
					"secret-bos",
					self._post(self.account_nosecret, body, signature=_sign(body, self.secret)),
				)
			with self._flag(False):
				# Flag kapaliyken GECERLI imza bile ayni jenerik 401 almali.
				capture(
					"flag-kapali",
					self._post(self.account, body, signature=_sign(body, self.secret)),
				)
			with (
				self._flag(True),
				mock.patch.object(webhook_module, "safe_log_error") as error_spy,
				mock.patch(
					"frappe.model.base_document.BaseDocument.get_password",
					side_effect=RuntimeError(canary),
				),
			):
				# W2: beklenmedik ic hata (get_password patladi) — istemciye ayni 401.
				w2 = self._post(self.account, body, signature=_sign(body, self.secret))
				capture("w2-ic-exception", w2)

		enqueue_spy.assert_not_called()

		base_label, base_status, base_payload = observed[0]
		self.assertEqual(base_status, 401)
		self.assertEqual(base_payload, b'{"ok": false}')
		for label, status, payload in observed[1:]:
			self.assertEqual(
				(status, payload),
				(base_status, base_payload),
				f"'{label}' ret yolu '{base_label}' ile bayt-esit degil (enumeration yuzeyi)",
			)

		# W2 sizinti denetimi: exc tipi/mesaji/traceback yanitta YOK, iz LOG'da VAR.
		self.assertNotIn(canary.encode("utf-8"), w2.payload)
		self.assertNotIn(b"RuntimeError", w2.payload)
		self.assertNotIn(b"Traceback", w2.payload)
		error_spy.assert_called_once()
		logged_text, logged_title = error_spy.call_args[0]
		self.assertEqual(logged_title, "logistics.webhook.unexpected")
		self.assertIn(canary, logged_text)  # hata yutulmadi — istemciye degil Error Log'a gitti

	# -------------------------------------------------------------- AC-5
	def test_ac5_oversize_body_returns_413_without_signature_work(self) -> None:
		"""128 KB ustu govde: hesap COZULMEDEN ve imza HESAPLANMADAN 413."""
		body = b"x" * (MAX_WEBHOOK_BODY_BYTES + 1)
		with (
			self._flag(True),
			self._spy_enqueue() as enqueue_spy,
			mock.patch.object(webhook_module, "_resolve_account") as resolve_spy,
			mock.patch.object(webhook_module, "_verify_signature") as verify_spy,
		):
			out = self._post(self.account, body, signature="sha256=" + "0" * 64)

		self.assertEqual(out.status, 413)
		self.assertEqual(out.result, {"ok": False})
		enqueue_spy.assert_not_called()
		resolve_spy.assert_not_called()  # saldirgana bedava DB/HMAC isi yaptirilmaz
		verify_spy.assert_not_called()

	# ------------------------------------------------ AC-7 katman-1 + W4
	def test_ac7_layer1_duplicate_body_no_second_job_and_48h_ttl(self) -> None:
		"""Ayni govde ikinci POST'ta 200 doner ama IKINCI job yok; TTL 48 SAATTIR (W4)."""
		self.assertEqual(WEBHOOK_DEDUPE_TTL_SECONDS, 172800)  # W4: 48 saat = 172800 sn
		self.assertEqual(WEBHOOK_DEDUPE_TTL_SECONDS, 48 * 60 * 60)

		body = self._body()
		signature = _sign(body, self.secret)
		with self._flag(True), self._spy_enqueue() as enqueue_spy:
			first = self._post(self.account, body, signature=signature)
			self.assertEqual(first.status, 200)
			self.assertEqual(enqueue_spy.call_count, 1)

			# W4 TTL assert'i: Redis'teki GERCEK anahtarin kalan omru 48 saate kurulu.
			digest = hashlib.sha256(body).hexdigest()
			cache_key = f"{CACHE_PREFIX}webhook:seen:{self.account}:{digest}"
			ttl = frappe.cache.ttl(frappe.cache.make_key(cache_key))
			self.assertLessEqual(ttl, WEBHOOK_DEDUPE_TTL_SECONDS)
			self.assertGreater(
				ttl,
				WEBHOOK_DEDUPE_TTL_SECONDS - 600,
				"dedupe TTL'i 48 saatlik pencerenin belirgin altinda kurulmus",
			)

			second = self._post(self.account, body, signature=signature)
			self.assertEqual(second.status, 200)  # duplicate 401 alsaydi tasiyici retry firtinasi baslardi
			self.assertEqual(second.result, {"ok": True})
			self.assertEqual(enqueue_spy.call_count, 1, "duplicate govde IKINCI job uretti")

			# Anahtar govde SHA'siyla kurulur: tek bayt farkli govde duplicate DEGILDIR.
			altered = body + b" "
			third = self._post(self.account, altered, signature=_sign(altered, self.secret))
			self.assertEqual(third.status, 200)
			self.assertEqual(enqueue_spy.call_count, 2)

	def test_ac7_layer1_failed_enqueue_does_not_mark_seen(self) -> None:
		"""Dedupe isareti enqueue SONRASI atilir: enqueue patlarsa retry duplicate SAYILMAZ."""
		body = self._body()
		signature = _sign(body, self.secret)

		with (
			self._flag(True),
			mock.patch.object(webhook_module, "safe_log_error"),
			mock.patch("frappe.enqueue", side_effect=RuntimeError("redis-koptu")),
		):
			out = self._post(self.account, body, signature=signature)
		self.assertEqual(out.status, 401)  # W2 catch-all — istemci retry etmeli

		with self._flag(True), self._spy_enqueue() as enqueue_spy:
			retry = self._post(self.account, body, signature=signature)
		self.assertEqual(retry.status, 200)
		enqueue_spy.assert_called_once()  # event SESSIZCE kaybolmadi


class TestWebhookRateLimit(_WebhookTestBase):
	"""AC-6 + W3: IP-kovali, key parametresiz rate limit."""

	def test_w3_decorator_is_keyless_600_per_minute(self) -> None:
		"""W3 kilidi: dekorator limit=600/60sn ve KEY PARAMETRESIZ (kova = istek IP'si)."""
		source = inspect.getsource(webhook_module)
		match = re.search(r"^@rate_limit\((?P<args>[^)]*)\)$", source, flags=re.MULTILINE)
		self.assertIsNotNone(match, "endpoint @rate_limit dekoratoru bulunamadi")
		args = match.group("args")
		self.assertIn("limit=600", args)
		self.assertIn("seconds=60", args)
		self.assertNotIn("key", args, "W3 ihlali: key parametresi IP kovasini bozar")
		self.assertNotIn("ip_based", args, "W3: v15 default'u (ip_based=True) degistirilmemeli")

	def test_ac6_low_limit_blocks_third_call_and_buckets_by_ip(self) -> None:
		"""Dusuk limitle (2/60sn) 3. istek 429'a duser; FARKLI IP kendi kovasini kullanir."""
		from frappe.utils import set_request

		# inspect.unwrap: whitelist type-validation + uretim limiter sargilarini soyar;
		# ayni GERCEK endpoint govdesi dusuk limitli limiter ile yeniden sarilir.
		raw_endpoint = inspect.unwrap(webhook_module.receive_carrier_webhook)
		self.assertFalse(hasattr(raw_endpoint, "__wrapped__"))
		limited = rate_limit(limit=2, seconds=60)(raw_endpoint)

		previous_request = getattr(frappe.local, "request", None)
		previous_form_dict = frappe.local.form_dict
		previous_ip = getattr(frappe.local, "request_ip", None)
		previous_response = frappe.local.response
		try:
			set_request(method="POST", path="/api/method/webhook-rl-test", data=b"{}")
			# Sayac anahtari rl:{cmd}:{ip} — calisma basina benzersiz cmd ile izole pencere.
			frappe.local.form_dict = frappe._dict(cmd=f"whrl-{self.suffix}")
			frappe.local.response = frappe._dict()
			with self._flag(False):  # akis onemsiz — jenerik 401'e dusen en ucuz yol
				frappe.local.request_ip = "203.0.113.201"
				limited(account=None)
				limited(account=None)
				with self.assertRaises(frappe.RateLimitExceededError):
					limited(account=None)

				# AYNI pencere, FARKLI IP: kova IP-anahtarli oldugu icin gecer (W3).
				frappe.local.request_ip = "203.0.113.202"
				limited(account=None)

				# Ilk IP hala blokta — kovalar birbirine karismiyor.
				frappe.local.request_ip = "203.0.113.201"
				with self.assertRaises(frappe.RateLimitExceededError):
					limited(account=None)
		finally:
			frappe.local.request = previous_request
			frappe.local.form_dict = previous_form_dict
			frappe.local.request_ip = previous_ip
			frappe.local.response = previous_response

		# Limit asimi HTTP katmaninda 429'a cevrilir (shared_contracts).
		self.assertEqual(getattr(frappe.RateLimitExceededError, "http_status_code", None), 429)


class TestWebhookEndToEnd(_WebhookTestBase):
	"""AC-7 katman-2/3 + AC-8/9/10/11 — mock adapter + gercek Shipment akisi."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		# Order kalemi icin herhangi bir Listing yeterli; bos sitede fixture uretilir
		# (test_media_refs_provenance deseni — SEO/gorsel kurallari test baglaminda atlanir).
		listings = frappe.get_all("Listing", fields=["name"], limit=1)
		if listings:
			cls.listing: str = listings[0].name
		else:
			listing_doc = frappe.get_doc(
				{
					"doctype": "Listing",
					"listing_code": f"WHK-{frappe.generate_hash(length=8)}",
					"title": "Webhook Test Urunu",
					"status": "Active",
					"currency": "TRY",
					"base_price": 100,
					"selling_price": 100,
					"stock_qty": 1000,
				}
			)
			listing_doc.flags.ignore_mandatory = True
			listing_doc.insert(ignore_permissions=True)
			cls.listing = listing_doc.name

		# Order.validate KYB gate'i satici kullanicisinda bu rolu arar.
		_ensure_role("Verified Seller")
		cls.seller1_user: str = _make_user(f"whk-s1-{cls.suffix}@test.local", ("Verified Seller",))
		cls.seller1: str = _make_seller_profile(cls.seller1_user, "SaticiA")
		cls.seller2_user: str = _make_user(f"whk-s2-{cls.suffix}@test.local", ("Verified Seller",))
		cls.seller2: str = _make_seller_profile(cls.seller2_user, "SaticiB")
		cls.buyer: str = _make_user(f"whk-buyer-{cls.suffix}@test.local")

		cls.code_mock: str = f"mocke2e{cls.suffix}"
		register_carrier(cls.code_mock, MockCarrierAdapter)
		cls.addClassCleanup(_CARRIER_REGISTRY.pop, cls.code_mock, None)
		cls.provider_mock: str = cls._create_provider(cls.code_mock)
		cls.provider_plain: str = cls._create_provider(f"plaine2e{cls.suffix}")

		# Carrier Status Mapping fixture'i (spec riski: katalog bossa her sey UNMAPPED).
		for code, internal in (
			("DLV", ShipmentStatus.DELIVERED),
			("TRANSIT", ShipmentStatus.IN_TRANSIT),
		):
			frappe.get_doc(
				{
					"doctype": "Carrier Status Mapping",
					"carrier": cls.provider_mock,
					"carrier_status_code": code,
					"carrier_status_text": code,
					"internal_status": internal,
				}
			).insert(ignore_permissions=True)

		cls.account_a: str = cls._create_account(
			cls.provider_mock, label="WH E2E Satici-A", seller_profile=cls.seller1, secret=cls.secret
		)
		cls.account_plain: str = cls._create_account(
			cls.provider_plain, label="WH E2E Adaptersiz", secret=cls.secret
		)

	# -------------------------------------------------------------------
	# Fixture yardimcilari
	# -------------------------------------------------------------------

	def _make_order(self, seller: str) -> Any:
		"""Tek kalemli taze Order (test_shipment_core deseni)."""
		return frappe.get_doc(
			{
				"doctype": "Order",
				"buyer": self.buyer,
				"seller": seller,
				"status": "Onaylanıyor",
				"order_date": frappe.utils.now_datetime(),
				"items": [
					{
						"listing": self.listing,
						"listing_title": "Webhook Test Kalemi",
						"quantity": 5,
						"unit_price": 10,
					}
				],
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)

	def _shipment_in_transit(self, seller: str) -> tuple[str, str]:
		"""In Transit durumunda, tracking_number'li Shipment fixture'i uretir."""
		order = self._make_order(seller)
		shipment = create_shipment_draft_from_order(order.name)
		for status in (
			ShipmentStatus.PENDING,
			ShipmentStatus.READY_FOR_PICKUP,
			ShipmentStatus.PICKED_UP,
			ShipmentStatus.IN_TRANSIT,
		):
			transition_status(shipment.name, status, source="System")
		tracking = f"TRKWH{frappe.generate_hash(length=10).upper()}"
		# db.set_value GEREKCESI: tracking atamasi fixture kurulumudur, is kurali
		# tetiklemek istemiyoruz; alan denormsuz duz Data.
		frappe.db.set_value("Shipment", shipment.name, "tracking_number", tracking, update_modified=False)
		return shipment.name, tracking

	def _event_body(self, tracking: str, code: str) -> bytes:
		return json.dumps(
			{
				"tracking_number": tracking,
				"status_code": code,
				"status_text": f"Test durumu: {code}",
				"event_time": frappe.utils.now_datetime().isoformat(),
			}
		).encode("utf-8")

	def _deliver(self, account: str, body: bytes) -> Any:
		"""Imzali POST + job'un senkron kosumu (worker simulasyonu)."""
		with self._flag(True), self._sync_enqueue():
			return self._post(account, body, signature=_sign(body, self.secret))

	def _event_count(self, shipment: str) -> int:
		return frappe.db.count("Shipment Event", {"shipment": shipment})

	# -------------------------------------------------------------- AC-8
	def test_ac8_end_to_end_transition_with_carrier_code_denorm(self) -> None:
		"""Mock event → katalog eslemesi → transition + event'te ham kod + tenant denormu."""
		shipment, tracking = self._shipment_in_transit(self.seller1)
		before = self._log_names(self.account_a)

		out = self._deliver(self.account_a, self._event_body(tracking, "DLV"))

		self.assertEqual(out.status, 200)
		self.assertEqual(out.result, {"ok": True})
		self.assertEqual(frappe.db.get_value("Shipment", shipment, "status"), ShipmentStatus.DELIVERED)

		events = frappe.get_all(
			"Shipment Event",
			filters={"shipment": shipment, "source": "Webhook"},
			fields=["internal_status", "carrier_status_code", "seller_profile"],
		)
		self.assertEqual(len(events), 1)
		self.assertEqual(events[0].internal_status, ShipmentStatus.DELIVERED)
		self.assertEqual(events[0].carrier_status_code, "DLV")  # AC-8: ham tasiyici kodu denormu
		self.assertEqual(events[0].seller_profile, self.seller1)  # AC-8: tenant denormu

		logs = self._new_logs(self.account_a, before)
		self.assertEqual(len(logs), 2)  # endpoint kabul logu + job isleme logu
		job_logs = [log for log in logs if log.shipment == shipment]
		self.assertEqual(len(job_logs), 1)
		self.assertEqual(int(job_logs[0].succeeded), 1)
		self.assertFalse(job_logs[0].error_code)
		self.assertIn(ShipmentStatus.DELIVERED, job_logs[0].response_body or "")

	# -------------------------------------------------------------- AC-9
	def test_ac9_unmapped_status_code_keeps_status_and_logs_succeeded(self) -> None:
		"""Eslesmeyen kod: durum DEGISMEZ, STATUS_UNMAPPED ama succeeded=1 (alim basarili)."""
		shipment, tracking = self._shipment_in_transit(self.seller1)
		events_before = self._event_count(shipment)
		before = self._log_names(self.account_a)

		out = self._deliver(self.account_a, self._event_body(tracking, f"ESLESMEYEN-{self.suffix}"))

		self.assertEqual(out.status, 200)  # tasiyiciya HATA donulmez (retry firtinasi onleme)
		self.assertEqual(frappe.db.get_value("Shipment", shipment, "status"), ShipmentStatus.IN_TRANSIT)
		self.assertEqual(self._event_count(shipment), events_before)

		job_logs = [log for log in self._new_logs(self.account_a, before) if log.shipment == shipment]
		self.assertEqual(len(job_logs), 1)
		self.assertEqual(job_logs[0].error_code, "STATUS_UNMAPPED")
		self.assertEqual(int(job_logs[0].succeeded), 1)

	# ---------------------------------------------------- AC-7 katman-2
	def test_ac7_layer2_same_status_transition_is_noop(self) -> None:
		"""In Transit'e esleyen event, zaten In Transit sevkiyatta sessiz no-op'tur."""
		shipment, tracking = self._shipment_in_transit(self.seller1)
		events_before = self._event_count(shipment)
		before = self._log_names(self.account_a)

		out = self._deliver(self.account_a, self._event_body(tracking, "TRANSIT"))

		self.assertEqual(out.status, 200)
		self.assertEqual(frappe.db.get_value("Shipment", shipment, "status"), ShipmentStatus.IN_TRANSIT)
		self.assertEqual(self._event_count(shipment), events_before, "no-op gecis event uretti")

		job_logs = [log for log in self._new_logs(self.account_a, before) if log.shipment == shipment]
		self.assertEqual(len(job_logs), 1)
		self.assertEqual(int(job_logs[0].succeeded), 1)  # no-op gorunur kalir ama basaridir
		self.assertFalse(job_logs[0].error_code)
		self.assertIn("no_op", job_logs[0].response_body or "")

	# ---------------------------------------------------- AC-7 katman-3
	def test_ac7_layer3_event_hash_unique_constraint(self) -> None:
		"""Ayni event_hash ile ikinci Shipment Event DB katmaninda reddedilir."""
		shipment, _tracking = self._shipment_in_transit(self.seller1)
		event_hash = hashlib.sha256(f"whk-katman3-{self.suffix}".encode()).hexdigest()

		def make_event() -> None:
			frappe.get_doc(
				{
					"doctype": "Shipment Event",
					"shipment": shipment,
					"seller_profile": self.seller1,
					"event_hash": event_hash,
					"event_time": frappe.utils.now_datetime(),
					"internal_status": ShipmentStatus.IN_TRANSIT,
					"source": "Webhook",
				}
			).insert(ignore_permissions=True)

		make_event()
		with self.assertRaises((frappe.UniqueValidationError, frappe.DuplicateEntryError)):
			make_event()

	# ------------------------------------------------------------- AC-10
	def test_ac10_cross_tenant_signature_cannot_touch_other_tenants_shipment(self) -> None:
		"""A hesabinin imzasiyla B'nin sevkiyati GUNCELLENMEZ; yok-tracking ayni yol."""
		shipment_b, tracking_b = self._shipment_in_transit(self.seller2)
		events_before = self._event_count(shipment_b)
		before = self._log_names(self.account_a)

		out = self._deliver(self.account_a, self._event_body(tracking_b, "DLV"))

		self.assertEqual(out.status, 200)  # dis yanit ayrim vermez (anti-enumeration)
		self.assertEqual(
			frappe.db.get_value("Shipment", shipment_b, "status"),
			ShipmentStatus.IN_TRANSIT,
			"cross-tenant webhook baska tenant'in sevkiyatini guncelledi",
		)
		self.assertEqual(self._event_count(shipment_b), events_before)

		cross_logs = [log for log in self._new_logs(self.account_a, before) if not int(log.succeeded)]
		self.assertEqual(len(cross_logs), 1)
		self.assertEqual(cross_logs[0].error_code, "SHIPMENT_NOT_FOUND")

		# Hic var olmayan tracking_number AYNI koddan ayirt EDILEMEZ olmali.
		before_missing = self._log_names(self.account_a)
		out_missing = self._deliver(self.account_a, self._event_body(f"TRKYOK{self.suffix.upper()}", "DLV"))
		self.assertEqual(out_missing.status, 200)
		missing_logs = [
			log for log in self._new_logs(self.account_a, before_missing) if not int(log.succeeded)
		]
		self.assertEqual(len(missing_logs), 1)
		self.assertEqual(missing_logs[0].error_code, cross_logs[0].error_code)

	# ------------------------------------------------------------- AC-11
	def test_ac11_adapterless_carrier_gets_200_and_capability_failed_log(self) -> None:
		"""Registry'de olmayan tasiyicinin imzali istegi: 200 + job'da CAPABILITY failed log."""
		body = self._event_body(f"TRKX{self.suffix.upper()}", "DLV")
		before = self._log_names(self.account_plain)

		with (
			self._flag(True),
			self._sync_enqueue(),
			mock.patch("tradehub_core.logistics.services.tracking_service.safe_log_error") as error_spy,
		):
			out = self._post(self.account_plain, body, signature=_sign(body, self.secret))

		self.assertEqual(out.status, 200)  # kimlik kanitli — isleyememe karari job'un
		self.assertEqual(out.result, {"ok": True})

		logs = self._new_logs(self.account_plain, before)
		failed = [log for log in logs if not int(log.succeeded)]
		self.assertEqual(len(failed), 1)
		self.assertEqual(failed[0].error_code, "CAPABILITY_UNSUPPORTED")
		self.assertEqual(failed[0].direction, "inbound")
		error_spy.assert_called_once()  # AC-11: failed log'a ek olarak frappe.log_error izi


if __name__ == "__main__":
	unittest.main()
