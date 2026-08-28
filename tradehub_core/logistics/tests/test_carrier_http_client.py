# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-110: CarrierHttpClient davranış testleri.

AĞ ÇAĞRISI YAPILMAZ — `requests.Session` yerine senaryo tabanlı bir sahte
oturum enjekte edilir. Devre kesici testleri gerçek Redis kullanır (durum
paylaşımlı olmak ZORUNDA, bkz. http_client modül yorumu); her test kendi
taşıyıcı koduyla izole çalışır.

SSRF kapısı çoğu testte `allow_private_hosts=True` ile kapalı: `kargo.test`
çözümlenemez ve kapı açıkken her istek DNS'te düşerdi. Kapının KENDİSİ
`TestUrlGuard` ve `TestRedirectHandling` altında ayrıca sınanıyor.
"""

from __future__ import annotations

import inspect
import time
import unittest
import uuid
from dataclasses import replace
from typing import Any
from unittest import mock

import frappe
import requests
from frappe.tests.utils import FrappeTestCase

from tradehub_core.logistics.adapters import http_client as hc
from tradehub_core.logistics.adapters.http_client import CarrierHttpClient, CarrierResponse
from tradehub_core.logistics.adapters.url_guard import URL_GUARD_CODES, UrlGuard, UrlNotAllowedError
from tradehub_core.logistics.exceptions import CarrierAPIError, CarrierTimeoutError, LogisticsError
from tradehub_core.logistics.integration.log import (
	INTEGRATION_LOG_DOCTYPE,
	IntegrationLogWriter,
	write_integration_log,
)
from tradehub_core.logistics.integration.secrets import collect_secret_values
from tradehub_core.logistics.resilience import Outcome, RetryPolicy, fault_report

_MODULE = "tradehub_core.logistics.adapters.http_client"

#: Seed'li bir `Logistics Provider` docname'i — log'un `carrier` Link alanı bunu ister.
SEEDED_PROVIDER = "AK"


# ---------------------------------------------------------------------------
# Sahte requests katmanı
# ---------------------------------------------------------------------------


class FakeResponse:
	"""`requests.Response` yerine geçen asgari yüzey (streaming dahil)."""

	def __init__(
		self,
		status_code: int,
		content: bytes = b"",
		headers: dict[str, str] | None = None,
		encoding: str | None = "utf-8",
	) -> None:
		self.status_code = status_code
		self.content = content
		self.headers = headers or {}
		self.encoding = encoding
		self.closed = False

	def iter_content(self, chunk_size: int = 8192) -> Any:
		for start in range(0, len(self.content), max(1, chunk_size)):
			yield self.content[start : start + chunk_size]

	def close(self) -> None:
		self.closed = True


class FakeSession:
	"""Senaryo listesini sırayla döndürür; liste biterse son öğeyi tekrarlar."""

	def __init__(self, script: list[Any]) -> None:
		self._script = list(script)
		self.calls: list[dict[str, Any]] = []
		self.closed = False

	def request(self, **kwargs: Any) -> FakeResponse:
		self.calls.append(kwargs)
		item = self._script.pop(0) if len(self._script) > 1 else self._script[0]
		if isinstance(item, Exception):
			raise item
		return item

	def close(self) -> None:
		self.closed = True

	@property
	def call_count(self) -> int:
		return len(self.calls)


def _log_failure_reports(log_error: Any) -> int:
	"""Yalnız "entegrasyon logu yazılamadı" raporlarını sayar.

	Aynı `frappe.log_error` yüzeyini `_iter_body`'nin `read1` düşüş raporu da
	kullanıyor (sahte yanıt nesnelerinde her koşuda bir kez); kısmayı ölçerken
	onu saymamak gerekir.
	"""
	return sum(1 for call in log_error.call_args_list if "Entegrasyon logu yazılamadı" in call.args[0])


class _Recorder:
	"""Log çağrılarını listeye yazan SÖZLEŞMEYE UYAN yazıcı.

	DÖNÜŞ DEĞERİ ÖNEMLİDİR: `IntegrationLogWriter` sözleşmesi "oluşan log
	kaydının adı; yazılamadıysa `None`" diyor ve `CarrierHttpClient._log` artık
	o kanalı OKUYOR. `None` dönen bir sahte yazıcı "satır yazılamadı" demektir;
	testlerdeki eski `lambda **kw: records.append(kw)` yazıcıları (append `None`
	döner) bu yüzden sözleşmeyi ihlal ediyordu.
	"""

	def __init__(self, sink: list[dict[str, Any]]) -> None:
		self._sink = sink

	def __call__(self, **kwargs: Any) -> str:
		self._sink.append(kwargs)
		return f"CIL-{len(self._sink):05d}"


class _PlaceholderDoc:
	"""Frappe `Password` alanının ÖLÇÜLMÜŞ hâli: sütunda `'*' * n`, `__Auth` boş.

	Yer tutucu kararı bileşiktir — "tamamı yıldız" TEK BAŞINA yetmez, kaynağın
	`get_password()` ile okuma yeteneği de olmalı. Düz bir `dict`'te o
	dolaylama YOKTUR, bu yüzden bu sınıf kullanılıyor.
	"""

	def __init__(self, extra: dict[str, Any] | None = None) -> None:
		self._fields: dict[str, Any] = {"api_key": "*" * 19, **(extra or {})}

	def get(self, field: str) -> Any:
		return self._fields.get(field)

	def get_password(self, field: str, raise_exception: bool = True) -> Any:
		return None  # `__Auth` satırı yok — plaintext okunamıyor.


def _client(session: FakeSession, **kwargs: Any) -> CarrierHttpClient:
	"""Varsayılan olarak devre kesici ve SSRF kapısı KAPALI — çoğu test onları ilgilendirmiyor."""
	kwargs.setdefault("circuit_breaker", False)
	kwargs.setdefault("allow_private_hosts", True)
	kwargs.setdefault("carrier_code", f"TEST-{uuid.uuid4().hex[:8]}")
	carrier_code = kwargs.pop("carrier_code")
	return CarrierHttpClient(carrier_code, session=session, **kwargs)


class _SleepRecorder:
	"""`_sleep` yerine geçer; gerçek beklemeyi atlar, süreleri kaydeder."""

	def __init__(self) -> None:
		self.durations: list[float] = []

	def __call__(self, seconds: float) -> None:
		self.durations.append(seconds)


class _NoSleep(unittest.TestCase):
	"""`_sleep`'i devre dışı bırakan ortak taban."""

	def setUp(self) -> None:
		self.sleeper = _SleepRecorder()
		patcher = mock.patch(f"{_MODULE}._sleep", self.sleeper)
		patcher.start()
		self.addCleanup(patcher.stop)


# ---------------------------------------------------------------------------
# Yeniden deneme politikası
# ---------------------------------------------------------------------------


class TestCircuitDefaults(unittest.TestCase):
	"""Devre kesici SABİTLERİ TESTSİZDİ — mutasyon (5→1, 60→0, 300→1) 0 test düşürüyordu.

	Bu üç değer koruma katmanının kalibrasyonudur: eşik düşerse tek bir geçici
	5xx canlı trafiği keser, cooldown 0'a düşerse devre hiç beklemeden yeniden
	denemeye açılır, pencere daralırsa "ardışık hata" şartı anlamını yitirir.
	Değerler BİLEREK sabitlenmiştir; değiştiren kişi bu testi de değiştirmek
	zorunda kalsın diye kilitlendi.
	"""

	def test_declared_defaults_are_the_calibrated_values(self) -> None:
		self.assertEqual(hc.CIRCUIT_FAILURE_THRESHOLD, 5)
		self.assertEqual(hc.CIRCUIT_COOLDOWN_SEC, 60)
		self.assertEqual(hc.CIRCUIT_FAILURE_WINDOW_SEC, 300)
		self.assertGreaterEqual(
			hc.CIRCUIT_FAILURE_WINDOW_SEC,
			hc.CIRCUIT_COOLDOWN_SEC,
			"Hata penceresi cooldown'dan kısa — sayaç devre kapanmadan sıfırlanır",
		)

	def test_client_actually_wires_the_defaults_into_the_breaker(self) -> None:
		"""Sabitler doğru ama bağlanmıyorsa hiçbir şey ifade etmezler."""
		breaker = CarrierHttpClient("wiring-test").breaker

		self.assertEqual(breaker.failure_threshold, hc.CIRCUIT_FAILURE_THRESHOLD)
		self.assertEqual(breaker.cooldown_sec, hc.CIRCUIT_COOLDOWN_SEC)
		self.assertEqual(breaker.failure_window_sec, hc.CIRCUIT_FAILURE_WINDOW_SEC)

	def test_default_timeout_is_finite_on_both_axes(self) -> None:
		"""Timeout'suz istek bir RQ işçisini SÜRESİZ kilitler."""
		connect, read = hc.DEFAULT_TIMEOUT
		self.assertEqual((connect, read), (5.0, 30.0))
		self.assertTrue(0 < connect < read, "Bağlantı payı okuma payından büyük ya da sıfır")
		self.assertEqual(CarrierHttpClient("timeout-test").timeout, hc.DEFAULT_TIMEOUT)


class TestRetryPolicyBehaviour(_NoSleep):
	def test_idempotent_call_retries_on_5xx_and_stops_at_max_attempts(self) -> None:
		"""Idempotent çağrı 5xx'te yeniden denenir ve 3. denemede durur."""
		session = FakeSession([FakeResponse(503, b"gecici hata")])
		client = _client(session, max_attempts=3)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/track", operation="track", idempotent=True)

		self.assertEqual(session.call_count, 3)
		self.assertEqual(ctx.exception.carrier_status, 503)
		self.assertEqual(ctx.exception.attempts, 3)
		self.assertEqual(len(self.sleeper.durations), 2)

	def test_non_idempotent_call_is_never_retried_double_shipment_trap(self) -> None:
		"""ÇİFT GÖNDERİ TUZAĞI: gönderi oluşturma 5xx'te yeniden DENENMEZ."""
		session = FakeSession([FakeResponse(500, b"sunucu hatasi")])
		client = _client(session, max_attempts=3)

		with self.assertRaises(CarrierAPIError):
			client.request(
				"POST",
				"https://kargo.test/shipments",
				operation="create_shipment",
				idempotent=False,
				body={"ref": "SHP-1"},
			)

		self.assertEqual(session.call_count, 1, "Gönderi oluşturma tekrarlandı — çift gönderi riski!")
		self.assertEqual(self.sleeper.durations, [])

	def test_client_errors_are_never_retried(self) -> None:
		"""400 ve 404 idempotent çağrıda bile tek denemede biter."""
		for status in (400, 404):
			with self.subTest(status=status):
				session = FakeSession([FakeResponse(status, b"hatali istek")])
				client = _client(session, max_attempts=3)

				with self.assertRaises(CarrierAPIError) as ctx:
					client.request("GET", "https://kargo.test/track", operation="track", idempotent=True)

				self.assertEqual(session.call_count, 1)
				self.assertEqual(ctx.exception.carrier_status, status)
				self.assertEqual(ctx.exception.attempts, 1, "attempts bütçeyi değil gerçeği saymalı")

	def test_429_honours_retry_after_header(self) -> None:
		"""429 yanıtındaki Retry-After başlığına uyulur, jitter'a düşülmez."""
		session = FakeSession(
			[
				FakeResponse(429, b"slow down", {"Retry-After": "2"}),
				FakeResponse(200, b'{"ok":true}', {"Content-Type": "application/json"}),
			]
		)
		client = _client(session, max_attempts=3)

		response = client.request("GET", "https://kargo.test/quote", operation="quote", idempotent=True)

		self.assertEqual(response.status_code, 200)
		self.assertEqual(session.call_count, 2)
		self.assertEqual(self.sleeper.durations, [2.0])

	def test_retry_after_beyond_cap_stops_retrying(self) -> None:
		"""Aşırı uzun Retry-After'da işçi bekletilmez, deneme bırakılır."""
		session = FakeSession([FakeResponse(429, b"", {"Retry-After": "3600"})])
		client = _client(session, max_attempts=3)

		with self.assertRaises(CarrierAPIError):
			client.request("GET", "https://kargo.test/quote", operation="quote", idempotent=True)

		self.assertEqual(session.call_count, 1)
		self.assertEqual(self.sleeper.durations, [])

	def test_timeout_maps_to_carrier_timeout_error(self) -> None:
		"""Zaman aşımı CarrierTimeoutError'a eşlenir (HTTP 504 sözleşmesi)."""
		session = FakeSession([requests.exceptions.ReadTimeout("okuma zaman asimi")])
		client = _client(session, max_attempts=2)

		with self.assertRaises(CarrierTimeoutError) as ctx:
			client.request("GET", "https://kargo.test/track", operation="track", idempotent=True)

		self.assertEqual(session.call_count, 2)
		self.assertEqual(ctx.exception.carrier_error_code, "TIMEOUT")
		self.assertEqual(ctx.exception.http_status_code, 504)
		self.assertIsInstance(ctx.exception, CarrierAPIError)

	def test_network_error_maps_to_carrier_api_error(self) -> None:
		"""Ağ hatası CarrierAPIError'a eşlenir ve yeniden denenebilir sayılır."""
		session = FakeSession([requests.exceptions.ConnectionError("baglanti reddedildi")])
		client = _client(session, max_attempts=2)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/track", operation="track", idempotent=True)

		self.assertEqual(session.call_count, 2)
		self.assertEqual(ctx.exception.carrier_error_code, "NETWORK_ERROR")

	def test_retry_policy_can_be_overridden_per_call(self) -> None:
		"""Taşıyıcıya özgü politika: 409 denenebilir hale getirilir."""
		policy = replace(RetryPolicy(max_attempts=2), retriable_statuses=frozenset({409}))
		session = FakeSession([FakeResponse(409, b"kilit cakismasi")])
		client = _client(session, max_attempts=1)

		with self.assertRaises(CarrierAPIError):
			client.request(
				"GET",
				"https://kargo.test/track",
				operation="track",
				idempotent=True,
				retry_policy=policy,
			)

		self.assertEqual(session.call_count, 2, "Çağrı bazlı politika devreye girmedi")

	def test_backoff_is_exponential_from_the_declared_base(self) -> None:
		"""TAM JITTER TABANI TESTSİZDİ: `backoff_base_sec` mutasyonu 0 test düşürüyordu.

		Sözleşme (AWS "Exponential Backoff and Jitter"): bekleme
		`[0, min(cap, base * 2**(n-1))]` aralığından seçilir. Taban ya da üs
		kayarsa çöken bir firmaya giden yeniden deneme temposu sessizce değişir.
		"""
		policy = RetryPolicy(backoff_base_sec=0.5, backoff_cap_sec=8.0)
		for attempt_no, ceiling in ((1, 0.5), (2, 1.0), (3, 2.0), (4, 4.0), (5, 8.0)):
			samples = [policy.delay_before_retry(attempt_no, None) for _ in range(200)]
			self.assertTrue(
				all(0.0 <= value <= ceiling for value in samples),
				f"{attempt_no}. deneme {ceiling} tavanının dışına çıktı: "
				f"[{min(samples):.3f}, {max(samples):.3f}]",
			)
			# Üs gerçekten uygulanıyor mu: 200 örnekte bir öncekinin tavanını aşan
			# en az bir değer olmalı (aksi halde tavan hiç büyümemiş demektir).
			if attempt_no > 1:
				self.assertGreater(max(samples), ceiling / 2, "Üstel büyüme uygulanmıyor")

	def test_backoff_is_capped(self) -> None:
		policy = RetryPolicy(backoff_base_sec=0.5, backoff_cap_sec=2.0)
		samples = [policy.delay_before_retry(10, None) for _ in range(100)]
		self.assertLessEqual(max(samples), 2.0, "Tavan uygulanmıyor — işçi uzun süre uyur")

	def test_backoff_carries_real_jitter(self) -> None:
		"""JITTER TESTSİZDİ: sabit bekleme, eşzamanlı işçileri firmaya AYNI ANDA gönderir."""
		policy = RetryPolicy(backoff_base_sec=0.5)
		samples = {policy.delay_before_retry(3, None) for _ in range(200)}

		self.assertGreater(len(samples), 50, f"Bekleme jitter taşımıyor ({len(samples)} farklı değer)")
		self.assertLess(min(samples), 0.5, "Alt uç 0'a yaklaşmıyor — tam jitter değil")

	def test_retry_after_beats_the_backoff_curve(self) -> None:
		"""Firma "N sn sonra gel" derse eğri DEĞİL, başlık uygulanır."""
		policy = RetryPolicy(backoff_base_sec=0.5, retry_after_cap_sec=60.0)
		self.assertEqual(policy.delay_before_retry(1, 12.0), 12.0)
		self.assertIsNone(policy.delay_before_retry(1, 61.0))

	def test_default_policy_leaves_503_retriable_and_409_permanent(self) -> None:
		"""Varsayılan politika bugünkü davranışı birebir korur."""
		policy = RetryPolicy()
		self.assertIs(policy.classify_status(503), Outcome.UNAVAILABLE)
		self.assertIs(policy.classify_status(409), Outcome.NEUTRAL)
		self.assertIs(policy.classify_status(204), Outcome.HEALTHY)
		self.assertEqual(policy.attempt_budget(idempotent=False), 1)
		self.assertEqual(policy.attempt_budget(idempotent=True), 3)


# ---------------------------------------------------------------------------
# Sonuç sınıflandırması (OCP seam)
# ---------------------------------------------------------------------------


class TestOutcomeClassification(_NoSleep):
	def test_custom_classify_turns_http_200_error_envelope_into_failure(self) -> None:
		"""TR SOAP senaryosu: HTTP 200 + gövdede ResultCode=-1 BAŞARI DEĞİLDİR."""
		body = b"<Response><ResultCode>-1</ResultCode></Response>"
		session = FakeSession([FakeResponse(200, body, {"Content-Type": "text/xml"})])
		client = _client(session, max_attempts=2)

		def classify(response: CarrierResponse) -> Outcome:
			return Outcome.UNAVAILABLE if "<ResultCode>-1<" in response.text else Outcome.HEALTHY

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request(
				"POST",
				"https://kargo.test/soap",
				operation="track",
				idempotent=True,
				classify=classify,
			)

		self.assertEqual(session.call_count, 2, "Gövde hatası yeniden denenmedi")
		self.assertEqual(ctx.exception.carrier_error_code, "CARRIER_REJECTED")
		self.assertEqual(ctx.exception.carrier_status, 200)

	def test_classify_exception_becomes_a_logistics_error(self) -> None:
		"""ÖLÇÜLDÜ: `classify=` fırlatınca istisna KORUMASIZ dışarı çıkıyordu.

		`KeyError` `LogisticsError` hiyerarşisinde olmadığı için `logistics_endpoint`
		zarfına takılmıyor ve API 500 dönüyordu. Modülün her yerde uyguladığı
		politika (`_prepare_body`, `_validate_operation`, `_validated_timeout`)
		hiyerarşiye çevirmek.
		"""

		def boom(_response: CarrierResponse) -> Outcome:
			raise KeyError("adapter sınıflandırıcısı çöktü")

		session = FakeSession([FakeResponse(200, b'{"x":1}')])
		client = _client(session)

		with self.assertRaises(LogisticsError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track", classify=boom)

		self.assertNotIsInstance(ctx.exception, CarrierAPIError, "Adapter hatası taşıyıcıya yazıldı")
		self.assertIsInstance(ctx.exception.__cause__, KeyError, "Kök neden zinciri koptu")

	def test_classify_exception_still_writes_a_log_row(self) -> None:
		"""Satır YAZILMALI: taşıyıcı yanıt VERDİ, çöken bizim sınıflandırıcımız."""

		def boom(_response: CarrierResponse) -> Outcome:
			raise ValueError("bozuk zarf")

		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(503, b"down")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=_Recorder(records))

		with self.assertRaises(LogisticsError):
			client.request("GET", "https://kargo.test/x", operation="track", classify=boom)

		self.assertEqual(len(records), 1, "Sınıflandırıcı çökünce log satırı KAYBOLDU")
		row = records[0]
		self.assertEqual(row["error_code"], "CLASSIFY_ERROR")
		self.assertEqual(row["http_status"], 503, "Taşıyıcının durumu satırda yok")
		self.assertFalse(row["succeeded"])
		self.assertFalse(row["is_retriable"])

	def test_classify_exception_does_not_touch_the_circuit_breaker(self) -> None:
		"""Adapter hatası taşıyıcı hakkında hiçbir şey KANITLAMAZ."""

		def boom(_response: CarrierResponse) -> Outcome:
			raise RuntimeError("çöktü")

		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, circuit_breaker=True, carrier_code=f"CLS-{uuid.uuid4().hex[:8]}")
		client.reset_circuit()
		self.addCleanup(client.reset_circuit)

		with mock.patch.object(client.breaker, "record") as record:
			for _index in range(5):
				with self.assertRaises(LogisticsError):
					client.request("GET", "https://kargo.test/x", operation="track", classify=boom)

		self.assertFalse(record.called, "Adapter hatası devre kesiciye kanıt olarak işlendi")

	def test_classify_exception_returns_the_half_open_probe(self) -> None:
		"""Kendi kodumuzdaki bir hata devreyi HALF_OPEN'da kilitlememeli."""

		def boom(_response: CarrierResponse) -> Outcome:
			raise RuntimeError("çöktü")

		carrier = f"CLSP-{uuid.uuid4().hex[:8]}"
		self.addCleanup(CarrierHttpClient(carrier).reset_circuit)
		down = FakeSession([FakeResponse(503, b"down")])
		first = CarrierHttpClient(
			carrier,
			session=down,
			circuit_breaker=True,
			failure_threshold=1,
			cooldown_sec=60,
			allow_private_hosts=True,
		)
		first.reset_circuit()
		with self.assertRaises(CarrierAPIError):
			first.request("POST", "https://kargo.test/x", operation="create_shipment")
		frappe.cache.delete(first.breaker._key("open"), first.breaker._key("probe"))  # noqa: SLF001

		crashing = FakeSession([FakeResponse(200, b"ok")])
		probe_client = CarrierHttpClient(
			carrier,
			session=crashing,
			circuit_breaker=True,
			failure_threshold=1,
			cooldown_sec=60,
			allow_private_hosts=True,
		)
		with self.assertRaises(LogisticsError):
			probe_client.request("GET", "https://kargo.test/x", operation="track", classify=boom)

		self.assertTrue(probe_client.breaker.acquire_probe(), "Adapter hatası probe anahtarını yaktı")

	def test_a_logistics_error_from_classify_is_not_rewrapped(self) -> None:
		"""Sözleşmeye uygun istisna ikinci kez sarmalanırsa nedeni gizlenir."""

		def strict(_response: CarrierResponse) -> Outcome:
			raise LogisticsError("adapter sözleşme ihlali")

		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=_Recorder(records))

		with self.assertRaises(LogisticsError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track", classify=strict)

		self.assertIn("adapter sözleşme ihlali", str(ctx.exception))
		self.assertEqual(len(records), 1, "Satır yazılmadı")

	def test_custom_classify_can_accept_a_4xx_as_healthy(self) -> None:
		"""404 = "takip kaydı yok" diyen adapter gövdeyi normal yoldan alır."""
		session = FakeSession([FakeResponse(404, b"kayit yok", {"Content-Type": "text/plain"})])
		client = _client(session)

		response = client.request(
			"GET",
			"https://kargo.test/track",
			operation="track",
			classify=lambda _resp: Outcome.HEALTHY,
		)

		self.assertEqual(response.status_code, 404)
		self.assertEqual(response.text, "kayit yok")


# ---------------------------------------------------------------------------
# Taşıma-bağımsızlık
# ---------------------------------------------------------------------------


class TestTransportNeutrality(unittest.TestCase):
	def test_raw_bytes_body_passes_through_untouched(self) -> None:
		"""SOAP senaryosu: ham bytes gövde JSON'a ÇEVRİLMEZ, birebir gider."""
		envelope = (
			b'<?xml version="1.0" encoding="utf-8"?>'
			b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
			b"<soap:Body><CreateShipment><Ref>SHP-1</Ref></CreateShipment></soap:Body>"
			b"</soap:Envelope>"
		)
		session = FakeSession([FakeResponse(200, b"<soap:Envelope/>", {"Content-Type": "text/xml"})])
		client = _client(session)

		client.request(
			"POST",
			"https://kargo.test/soap",
			operation="create_shipment",
			body=envelope,
			content_type="text/xml; charset=utf-8",
			headers={"SOAPAction": "CreateShipment"},
		)

		sent = session.calls[0]
		self.assertEqual(sent["data"], envelope)
		self.assertEqual(sent["headers"]["Content-Type"], "text/xml; charset=utf-8")
		self.assertEqual(sent["headers"]["SOAPAction"], "CreateShipment")
		self.assertFalse(sent["allow_redirects"], "Yönlendirme requests'e bırakılmamalı")
		self.assertTrue(sent["stream"], "Gövde tavansız okunuyor")

	def test_str_body_is_encoded_but_not_reserialized(self) -> None:
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		client.request("POST", "https://kargo.test/x", operation="cancel", body="ref=SHP-1")

		self.assertEqual(session.calls[0]["data"], b"ref=SHP-1")
		self.assertNotIn("Content-Type", session.calls[0]["headers"])

	def test_dict_body_is_json_encoded_as_convenience(self) -> None:
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		client.request("POST", "https://kargo.test/x", operation="quote", body={"desi": 3})

		self.assertEqual(session.calls[0]["data"], b'{"desi": 3}')
		self.assertIn("application/json", session.calls[0]["headers"]["Content-Type"])

	def test_unsupported_body_type_raises_logistics_error(self) -> None:
		"""Çıplak TypeError API zarfında 500'e dönüşürdü."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		with self.assertRaises(LogisticsError):
			client.request("POST", "https://kargo.test/x", operation="quote", body=object())

	def test_response_is_returned_raw(self) -> None:
		"""Yanıt ayrıştırılmaz: ham bytes + tembel text erişimi."""
		session = FakeSession(
			[FakeResponse(200, "gönderi oluşturuldu".encode(), {"Content-Type": "text/plain"})]
		)
		client = _client(session)

		response = client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		self.assertIsInstance(response.content, bytes)
		self.assertEqual(response.text, "gönderi oluşturuldu")
		self.assertEqual(response.attempts, 1)
		self.assertTrue(response.ok)
		self.assertGreaterEqual(response.elapsed_ms, 0)

	def test_timeout_is_always_sent_to_transport(self) -> None:
		session = FakeSession([FakeResponse(200)])
		client = _client(session, timeout=(1.0, 4.0))

		client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		self.assertEqual(session.calls[0]["timeout"], (1.0, 4.0))

	def test_timeout_none_falls_back_to_default_never_blocks_forever(self) -> None:
		"""`timeout=None` yazılırsa transporta None gider ve işçi SÜRESİZ kilitlenirdi."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)
		client.timeout = None  # type: ignore[assignment]

		client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(session.calls[0]["timeout"], hc.DEFAULT_TIMEOUT)

	def test_invalid_operation_is_rejected(self) -> None:
		"""operation Select sözleşmesinin dışına çıkamaz."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		with self.assertRaises(LogisticsError):
			client.request("GET", "https://kargo.test/x", operation="teleport")

		self.assertEqual(session.call_count, 0)

	def test_header_injection_is_rejected(self) -> None:
		"""Başlık adı/değerinde CRLF istek bölme (request splitting) yapardı."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		for headers in (
			{"X-Api-Key": "abc\r\nX-Injected: 1"},
			{"Bad Name": "ok"},
			{"X-Api-Key\n": "ok"},
		):
			with self.subTest(headers=headers), self.assertRaises(LogisticsError):
				client.request("GET", "https://kargo.test/x", operation="track", headers=headers)

		self.assertEqual(session.call_count, 0)

	def test_header_value_check_is_an_allowlist_not_a_denylist(self) -> None:
		"""U+0085 (NEL) latin-1'de 0x85 olarak TELE ÇIKAR; eski denylist onu geçiriyordu."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		# Kod noktaları KAÇIŞLA yazıldı: görünmez karakterler dosyada saklanamaz.
		for value in ("a\u0085b", "a\u2028b", "a\u2029b", "a\x7fb", "a\vb", "a\r\nb", "a\u00e7b"):
			with self.subTest(value=repr(value)), self.assertRaises(LogisticsError):
				client.request("GET", "https://kargo.test/x", operation="track", headers={"X-A": value})

		self.assertEqual(session.call_count, 0)

	def test_transport_owned_headers_cannot_be_supplied_by_the_caller(self) -> None:
		"""Content-Length/Transfer-Encoding çifti proxy arkasında request smuggling yüzeyi."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		for name in ("Host", "Content-Length", "Transfer-Encoding", "Connection", "Expect", "Upgrade"):
			with self.subTest(name=name), self.assertRaises(LogisticsError):
				client.request("GET", "https://kargo.test/x", operation="track", headers={name: "x"})

		self.assertEqual(session.call_count, 0)

	def test_ordinary_header_values_still_pass(self) -> None:
		"""Aşırı kısıtlama regresyonu: SOAPAction ve base64 jetonları geçmeli."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		client.request(
			"GET",
			"https://kargo.test/x",
			operation="track",
			headers={"SOAPAction": '"urn:CreateShipment"', "X-Api-Key": "YWJjZA==", "X-Tab": "a\tb"},
		)

		self.assertEqual(session.calls[0]["headers"]["X-Tab"], "a\tb")

	def test_invalid_timeout_is_a_logistics_error_not_a_500(self) -> None:
		"""ÖLÇÜLDÜ: `-1`/`(0,0)`/`'abc'` urllib3'te ValueError → 500, log YOK, devre kaydı YOK."""
		session = FakeSession([FakeResponse(200)])
		client = _client(session)

		for value in (0, -1, (0, 0), (1.0, 0), "abc", (1.0,), (1.0, 2.0, 3.0), float("nan")):
			with self.subTest(value=repr(value)), self.assertRaises(LogisticsError):
				client.timeout = value  # type: ignore[assignment]

		for value in (0, -1, "abc"):
			with self.subTest(per_call=repr(value)), self.assertRaises(LogisticsError):
				client.request(
					"GET",
					"https://kargo.test/x",
					operation="track",
					timeout=value,  # type: ignore[arg-type]
				)

		self.assertEqual(session.call_count, 0)

	def test_zero_timeout_is_no_longer_silently_replaced(self) -> None:
		"""`call.timeout or DEFAULT_TIMEOUT` çağıranın niyetini sessizce değiştiriyordu."""
		client = _client(FakeSession([FakeResponse(200)]))
		with self.assertRaises(LogisticsError):
			client.timeout = 0  # type: ignore[assignment]
		self.assertEqual(client.timeout, hc.DEFAULT_TIMEOUT, "Geçersiz atama etkin değeri bozdu")

	def test_valid_timeouts_are_accepted(self) -> None:
		client = _client(FakeSession([FakeResponse(200)]))
		client.timeout = 7
		self.assertEqual(client.timeout, 7.0)
		client.timeout = (1.5, 9.0)
		self.assertEqual(client.timeout, (1.5, 9.0))

	def test_transport_value_error_is_classified_not_leaked_as_500(self) -> None:
		"""Son çare dalı: log YAZILIR, devre kesici KAYDEDER, LogisticsError döner."""
		records: list[dict[str, Any]] = []
		session = FakeSession([ValueError("Invalid timeout value")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=_Recorder(records))

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(ctx.exception.carrier_error_code, "CONFIG_ERROR")
		self.assertEqual(records[0]["error_code"], "CONFIG_ERROR")

	def test_attacker_controlled_charset_cannot_break_text_access(self) -> None:
		"""`charset=` doğrudan taşıyıcıdan geliyor; LookupError 500'e dönüşüyordu."""
		for encoding in ("totally-not-a-codec", "base64", "zlib", ""):
			with self.subTest(encoding=encoding):
				response = CarrierResponse(200, {}, "ünlü".encode(), 1, 1, encoding=encoding)
				self.assertEqual(response.text, "ünlü", "utf-8'e düşülmedi")

	def test_declared_charset_is_still_honoured(self) -> None:
		response = CarrierResponse(200, {}, "ünlü".encode("iso-8859-9"), 1, 1, encoding="iso-8859-9")
		self.assertEqual(response.text, "ünlü")

	def test_close_does_not_touch_an_injected_session(self) -> None:
		"""Havuzu paylaşan çağıranın session'ı `with` bloğu bitince kapanmamalı."""
		session = FakeSession([FakeResponse(200)])
		with _client(session) as client:
			client.request("GET", "https://kargo.test/x", operation="track")

		self.assertFalse(session.closed, "Enjekte edilen session kapatıldı!")


# ---------------------------------------------------------------------------
# Yanıt boyutu tavanı
# ---------------------------------------------------------------------------


class TestResponseSizeCap(_NoSleep):
	def test_oversized_body_is_refused_without_buffering(self) -> None:
		"""Tavanı aşan gövde belleğe alınmaz; hata kalıcı ve tekrarsızdır."""
		session = FakeSession([FakeResponse(200, b"x" * 5000, {"Content-Type": "application/json"})])
		client = _client(session, max_response_bytes=1024, max_attempts=3)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		self.assertEqual(ctx.exception.carrier_error_code, "RESPONSE_TOO_LARGE")
		self.assertEqual(session.call_count, 1, "Boyut hatası yeniden denendi")

	def test_declared_content_length_over_cap_is_not_read(self) -> None:
		"""Beyan edilen Content-Length tavanı aşıyorsa tek bayt bile okunmaz."""
		response = FakeResponse(200, b"y" * 10, {"Content-Length": "999999999"})
		records: list[dict[str, Any]] = []
		client = _client(
			FakeSession([response]),
			max_response_bytes=2048,
			provider=SEEDED_PROVIDER,
			logger=_Recorder(records),
		)

		with self.assertRaises(CarrierAPIError):
			client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(records[0]["response_body"], "<truncated, >2048 bytes>")

	def test_body_at_cap_still_passes(self) -> None:
		session = FakeSession([FakeResponse(200, b"z" * 1024, {"Content-Type": "text/plain"})])
		client = _client(session, max_response_bytes=1024)

		response = client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(len(response.content), 1024)


# ---------------------------------------------------------------------------
# SSRF kapısı
# ---------------------------------------------------------------------------


class TestUrlGuard(unittest.TestCase):
	def test_guard_codes_stay_within_the_declared_contract(self) -> None:
		"""Kapının ürettiği her kod `URL_GUARD_CODES` içinde olmalı — log/telemetri buna dallanıyor."""
		seen = set()
		for url in ("ftp://x/y", "https://user:p@x.test/y", "https://127.0.0.1/y", "https:///y"):
			with self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard().validate(url)
			seen.add(ctx.exception.guard_code)

		self.assertTrue(seen <= URL_GUARD_CODES, f"Beyan dışı kod: {sorted(seen - URL_GUARD_CODES)}")

	def test_plain_http_is_blocked_by_default(self) -> None:
		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard().validate("http://kargo.example.com/x")
		self.assertEqual(ctx.exception.guard_code, "URL_SCHEME_BLOCKED")

	def test_non_http_scheme_is_blocked(self) -> None:
		for url in ("file:///etc/passwd", "gopher://x/1", "ftp://x/y"):
			with self.subTest(url=url), self.assertRaises(UrlNotAllowedError):
				UrlGuard(allow_http=True).validate(url)

	def test_userinfo_in_url_is_blocked(self) -> None:
		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard().validate("https://user:pass@kargo.example.com/x")
		self.assertEqual(ctx.exception.guard_code, "URL_INVALID")

	def test_internal_ip_literals_are_blocked(self) -> None:
		"""Bulut metadata servisi ve iç ağ — SSRF zincirinin hedefi."""
		for host in (
			"169.254.169.254",
			"127.0.0.1",
			"10.0.0.5",
			"192.168.1.1",
			"172.16.0.1",
			"0.0.0.0",
			"[::1]",
			"[::ffff:127.0.0.1]",
		):
			with self.subTest(host=host), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard().validate(f"https://{host}/latest/meta-data/")
			self.assertEqual(ctx.exception.guard_code, "URL_HOST_BLOCKED")

	def test_public_ip_literal_passes(self) -> None:
		self.assertEqual(
			UrlGuard().validate("https://93.184.216.34/x"),
			("https", "93.184.216.34", 443),
		)

	def test_non_standard_ports_are_rejected_by_default(self) -> None:
		"""Kapı port KISITLAMIYORDU — genel bir IP'nin 22/6379/9200'üne istek serbestti.

		`Carrier Account.base_url`'e yazabilen rol için ucuz bir dış port
		tarayıcısı: yanıt (ya da hata sınıfı) entegrasyon logundan okunuyor.
		TR kargo uçlarının tamamı standart portlarda.
		"""
		for port in (22, 6379, 8443, 9200, 11211):
			with self.subTest(port=port), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard().validate(f"https://93.184.216.34:{port}/x")
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")

	def test_explicit_port_allowlist_opens_a_single_port(self) -> None:
		"""Kısıt açık yapılandırmayla gevşetilebilir — kurum içi/test uçları için."""
		self.assertEqual(
			UrlGuard(allowed_ports={8443}).validate("https://93.184.216.34:8443/x"),
			("https", "93.184.216.34", 8443),
		)

	def test_sandbox_mode_does_not_restrict_ports(self) -> None:
		"""`allow_private_hosts=True` zaten IP doğrulamıyor; port kısıtı orada sürtünme."""
		self.assertEqual(
			UrlGuard(allow_private_hosts=True).validate("https://kargo.test:8080/x"),
			("https", "kargo.test", 8080),
		)

	def test_port_zero_is_rejected_instead_of_silently_becoming_443(self) -> None:
		"""`parts.port or DEFAULT` — port 0 FALSY, sessizce 443'e dönüşüyordu.

		Kapı 443 için karar veriyor ama `requests`'e giden URL hâlâ `:0`
		taşıyor: doğrulanan hedef ile bağlanılan hedef ayrışıyordu — modülün
		bütün tehdit modeli tam olarak bu ayrışmaya dayanıyor.
		"""
		for guard in (UrlGuard(), UrlGuard(allow_private_hosts=True)):
			with self.subTest(sandbox=guard.allow_private_hosts):
				with self.assertRaises(UrlNotAllowedError) as ctx:
					guard.validate("https://93.184.216.34:0/x")
				self.assertEqual(ctx.exception.guard_code, "URL_INVALID")

	def test_all_resolved_addresses_are_checked_not_just_the_first(self) -> None:
		"""Bir DNS kaydı hem genel hem 127.0.0.1 döndürebilir; sıra garanti değil."""

		def resolver(*_args: Any, **_kwargs: Any) -> list:
			return [
				(2, 1, 6, "", ("93.184.216.34", 443)),
				(2, 1, 6, "", ("127.0.0.1", 443)),
			]

		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard(resolver=resolver).validate("https://kargo.example.com/x")
		self.assertEqual(ctx.exception.guard_code, "URL_HOST_BLOCKED")

	def test_unresolvable_host_is_reported_separately(self) -> None:
		def resolver(*_args: Any, **_kwargs: Any) -> list:
			raise OSError("nodename nor servname provided")

		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard(resolver=resolver).validate("https://yok.example.com/x")
		self.assertEqual(ctx.exception.guard_code, "URL_UNRESOLVABLE")

	def test_client_refuses_internal_target_without_touching_transport(self) -> None:
		session = FakeSession([FakeResponse(200, b"secrets")])
		client = _client(session, allow_private_hosts=False)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://169.254.169.254/latest/meta-data/", operation="track")

		self.assertEqual(session.call_count, 0, "Engellenen URL transporta ulaştı!")
		self.assertEqual(ctx.exception.carrier_error_code, "URL_BLOCKED")


class TestUrlGuardIdna(unittest.TestCase):
	"""KRİTİK: kapı ile `requests` FARKLI A-label üretiyordu (deterministik atlatma)."""

	#: Kaynak metinler kasten kod noktalarıyla yazıldı: dosya kodlaması ya da
	#: bir formatter normalizasyonu testi sessizce anlamsızlaştırmasın.
	SHARP_S = "ß"  # ß — stdlib idna: "ss", idna paketi: "xn--zca"
	FINAL_SIGMA = "ς"  # ς — iki kütüphane FARKLI punycode üretiyor

	def test_the_two_encoders_still_disagree(self) -> None:
		"""Bulgunun ÖNKOŞULU: hizalamaya güvenilemeyeceğinin kanıtı."""
		import idna as idna_package

		host = self.SHARP_S + ".example.com"
		gate = host.encode("idna").decode("ascii")
		wire = idna_package.encode(host, uts46=True).decode("ascii")

		self.assertNotEqual(gate, wire, "Kütüphaneler hizalandıysa gerekçe yeniden değerlendirilmeli")

	def test_non_ascii_host_is_rejected_outright(self) -> None:
		"""ASCII olmayan host, ÇÖZÜMLEMEYE HİÇ GİTMEDEN reddedilir."""
		calls: list[str] = []

		def resolver(host: str, *_args: Any, **_kwargs: Any) -> list:
			calls.append(host)
			return [(2, 1, 6, "", ("93.184.216.34", 443))]

		for host in (
			self.SHARP_S + ".attacker.test",
			"fa" + self.SHARP_S + ".attacker.test",
			self.FINAL_SIGMA + "igma.attacker.test",
		):
			with self.subTest(host=host), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard(resolver=resolver).validate(f"https://{host}/x")
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")

		self.assertEqual(calls, [], "ASCII olmayan host çözümlemeye gitti")

	def test_rejection_applies_even_when_private_hosts_are_allowed(self) -> None:
		"""Sandbox modu bir URL GEÇERLİLİK kuralını gevşetmez."""
		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard(allow_private_hosts=True, allow_http=True).validate(
				"http://" + self.SHARP_S + ".attacker.test/x"
			)
		self.assertEqual(ctx.exception.guard_code, "URL_INVALID")

	def test_punycode_form_still_passes(self) -> None:
		"""IDN'li bir taşıyıcı çıkarsa operatörün yolu açık: xn-- biçimi ASCII'dir."""

		def resolver(*_args: Any, **_kwargs: Any) -> list:
			return [(2, 1, 6, "", ("93.184.216.34", 443))]

		self.assertEqual(
			UrlGuard(resolver=resolver).validate("https://xn--zca.example.com/x"),
			("https", "xn--zca.example.com", 443),
		)


class TestUrlGuardParserDivergence(unittest.TestCase):
	"""KRİTİK: kapı (`urlsplit`) ile transport (`requests`/`urllib3`) FARKLI host çıkarıyordu.

	`urlsplit` ters bölüyü host adının PARÇASI sayar, `requests` onu yol ayracına
	çevirip ÖNCEKİ kısmı host yapar. Kapı hedefi GENEL sanıp geçiriyor, transport
	İÇ adrese bağlanıyordu — pinlemenin devre dışı olduğu yollarda (enjekte
	edilmiş `session=`, `allow_private_hosts=True`) tek savunma kalmıyordu.
	Gerekçe ve ölçüm: `url_guard` modül docstring'i → "AYRIŞTIRICI FARKI".
	"""

	#: Denetimde uçtan uca (gerçek joker DNS ile) kanıtlanmış vektörler.
	SMUGGLING_URLS = (
		"https://169.254.169.254\\.attacker.com/x",
		"https://169.254.169.254\\attacker.com/x",
		"https://localhost\\x.1.2.3.4.sslip.io/api/ship",
	)

	#: Kapı/transport ayrışması taranan ayraç karakterleri (37).
	SEPARATORS = (
		"\\", "/", "?", "#", "@", ":", " ", "\t", "\n", "\r", "\x00", "\x0b", "\x0c",
		"%", "|", "^", "{", "}", "<", ">", '"', "'", "`", "[", "]", "(", ")", ",",
		";", "!", "$", "&", "*", "+", "=", "~", "_",
	)  # fmt: skip

	@staticmethod
	def _resolver_factory(calls: list[str]) -> Any:
		def resolver(host: str, port: int, *_args: Any, **_kwargs: Any) -> list:
			calls.append(host)
			# Saldırganın joker DNS'i: kapı GENEL bir adres görsün.
			return [(2, 1, 6, "", ("93.184.216.34", port))]

		return resolver

	@staticmethod
	def _transport_origin(url: str) -> tuple[str, str, int] | None:
		"""Transport'un GERÇEKTEN kullanacağı (şema, host, port); ayrıştıramazsa None."""
		import urllib3

		try:
			prepared = requests.models.PreparedRequest()
			prepared.prepare_url(url, None)
			parsed = urllib3.util.parse_url(prepared.url or "")
		except Exception:  # noqa: BLE001 — testte "ayrıştıramadı" da bir sonuçtur.
			return None
		scheme = (parsed.scheme or "").lower()
		port = parsed.port if parsed.port is not None else {"http": 80, "https": 443}.get(scheme, -1)
		return (scheme, (parsed.host or "").strip("[]").lower(), port)

	def test_the_two_parsers_still_disagree_on_backslash(self) -> None:
		"""Bulgunun ÖNKOŞULU: `isascii()`'nin neden yetmediğinin kanıtı."""
		from urllib.parse import urlsplit

		url = "https://169.254.169.254\\.attacker.com/x"
		self.assertTrue(url.isascii(), "Ters bölü ASCII değilse bulgunun gerekçesi değişti")
		self.assertEqual(urlsplit(url).hostname, "169.254.169.254\\.attacker.com")
		self.assertEqual(self._transport_origin(url), ("https", "169.254.169.254", 443))

	def test_backslash_smuggling_is_rejected_before_resolution(self) -> None:
		"""Ölçülmüş vektörler ÇÖZÜMLEMEYE HİÇ GİTMEDEN kapıda düşer."""
		calls: list[str] = []
		for url in self.SMUGGLING_URLS:
			with self.subTest(url=url), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard(resolver=self._resolver_factory(calls)).validate(url)
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")
		self.assertEqual(calls, [], "Ayrışmış host çözümlemeye gitti")

	def test_rejection_applies_in_sandbox_mode(self) -> None:
		"""`allow_private_hosts=True` pinlemeyi kapatır — kapı orada DAHA kritik."""
		for url in self.SMUGGLING_URLS:
			with self.subTest(url=url), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard(allow_private_hosts=True, allow_http=True).validate(url)
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")

	def test_redirect_hop_goes_through_the_same_check(self) -> None:
		"""İstemci her hop'ta `urljoin` + `validate_pinned` çağırıyor (http_client._send)."""
		from urllib.parse import urljoin

		calls: list[str] = []
		guard = UrlGuard(resolver=self._resolver_factory(calls))
		for location in ("//169.254.169.254\\.attacker.com/x", "https://localhost\\x.1.2.3.4.sslip.io/y"):
			hop = urljoin("https://api.example.com/a", location)
			with self.subTest(location=location), self.assertRaises(UrlNotAllowedError) as ctx:
				guard.validate_pinned(hop)
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")
		# Aynı kapı meşru bir hop'u hâlâ geçirmeli.
		self.assertEqual(
			guard.validate(urljoin("https://api.example.com/a", "/safe")),
			("https", "api.example.com", 443),
		)

	def test_no_separator_character_survives_the_gate(self) -> None:
		"""37 ayraç × 3 şablon taraması: kapıdan geçen ayrışmış vektör KALMAMALI.

		Düzeltmeden önce ölçüm: 111 üründen 61'i ayrıştı, 51'i kapıdan GEÇİYORDU.
		"""
		templates = (
			"https://169.254.169.254{sep}.attacker.com/x",
			"https://169.254.169.254{sep}attacker.com/x",
			"https://localhost{sep}x.1.2.3.4.sslip.io/api/ship",
		)
		survivors: list[str] = []
		for template in templates:
			for separator in self.SEPARATORS:
				url = template.format(sep=separator)
				calls: list[str] = []
				try:
					origin = UrlGuard(resolver=self._resolver_factory(calls)).validate(url)
				except UrlNotAllowedError:
					continue
				if origin != self._transport_origin(url):
					survivors.append(f"{separator!r} -> {url!r} kapı={origin!r}")
		self.assertEqual(survivors, [], "Kapı ile transport hâlâ ayrışıyor")

	def test_host_charset_is_an_allowlist_not_an_ascii_check(self) -> None:
		"""ASCII yeterli DEĞİL: kontrol karakterleri, `_`, `@`, tırnaklar da düşer."""
		for host in (
			"api\\evil.example.com",
			"api evil.example.com",
			"api\tevil.example.com",
			"api\x00evil.example.com",
			"api|evil.example.com",
			"api_internal.example.com",
			'api".example.com',
			"api'.example.com",
			"api{evil}.example.com",
			"api<evil>.example.com",
		):
			calls: list[str] = []
			with self.subTest(host=host), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard(resolver=self._resolver_factory(calls)).validate(f"https://{host}/x")
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")
			self.assertEqual(calls, [], "Allowlist dışı host çözümlemeye gitti")

	def test_gate_parse_failure_is_a_rejection_not_a_500(self) -> None:
		"""`urlsplit` KENDİSİ patlayabiliyor ve çıplak `ValueError` kapıdan sızıyordu."""
		calls: list[str] = []
		for url in (
			"https://169.254.169.254[.attacker.com/x",
			"https://169.254.169.254].attacker.com/x",
			"https://localhost[x.1.2.3.4.sslip.io/api/ship",
		):
			with self.subTest(url=url), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard(resolver=self._resolver_factory(calls)).validate(url)
			self.assertEqual(ctx.exception.guard_code, "URL_INVALID")
		self.assertEqual(calls, [], "Ayrıştırılamayan URL çözümlemeye gitti")

	def test_transport_parse_failure_fails_closed(self) -> None:
		"""Transport ayrıştırıcısı patlarsa kapı GEÇİRMEZ — belirsizlik = ret."""

		def boom(_self: Any, *_args: Any, **_kwargs: Any) -> None:
			raise requests.exceptions.InvalidURL("bozuk")

		calls: list[str] = []
		with mock.patch.object(requests.models.PreparedRequest, "prepare_url", boom):
			with self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard(resolver=self._resolver_factory(calls)).validate("https://api.example.com/x")
		self.assertEqual(ctx.exception.guard_code, "URL_INVALID")
		self.assertEqual(calls, [], "Ayrıştırılamayan URL çözümlemeye gitti")

	def test_rejection_message_leaks_no_topology(self) -> None:
		"""Mesaj entegrasyon loguna düşüyor: host/IP yazılmaz (bkz. `_assert_public_ip`)."""
		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard(allow_private_hosts=True).validate("https://169.254.169.254\\.attacker.com/x")
		self.assertNotIn("169.254", str(ctx.exception))
		self.assertNotIn("attacker", str(ctx.exception))

	def test_legitimate_urls_are_untouched(self) -> None:
		"""AŞIRI ENGELLEME REGRESYONU — gerçek taşıyıcı uçları kapanmamalı."""
		cases: tuple[tuple[str, tuple[str, str, int]], ...] = (
			("https://api.araskargo.com.tr/v1/ship", ("https", "api.araskargo.com.tr", 443)),
			("https://sub.domain.api.example.com/x", ("https", "sub.domain.api.example.com", 443)),
			("https://my-carrier-api.example.com/x", ("https", "my-carrier-api.example.com", 443)),
			("https://api.example.com:443/x", ("https", "api.example.com", 443)),
			("http://api.example.com:80/x", ("http", "api.example.com", 80)),
			("https://93.184.216.34/x", ("https", "93.184.216.34", 443)),
			("https://[2606:4700:4700::1111]/", ("https", "2606:4700:4700::1111", 443)),
			("https://[2606:4700:4700::1111]:443/x", ("https", "2606:4700:4700::1111", 443)),
			("https://api.example.com/a/b/c?q=1&r=2#frag", ("https", "api.example.com", 443)),
			("https://xn--zca.example.com/x", ("https", "xn--zca.example.com", 443)),
			("https://api.example.com./x", ("https", "api.example.com.", 443)),
			("https://API.Example.COM/x", ("https", "api.example.com", 443)),
			("https://api.example.com", ("https", "api.example.com", 443)),
		)
		calls: list[str] = []
		guard = UrlGuard(allow_http=True, resolver=self._resolver_factory(calls))
		for url, expected in cases:
			with self.subTest(url=url):
				self.assertEqual(guard.validate(url), expected)

	def test_gate_agrees_with_transport_on_every_accepted_url(self) -> None:
		"""Mutabakat kontrolünün KENDİSİ: kabul edilen her URL'de üçlüler eşit."""
		calls: list[str] = []
		guard = UrlGuard(allow_http=True, resolver=self._resolver_factory(calls))
		for url in (
			"https://api.araskargo.com.tr/v1/ship",
			"https://api.example.com:443/x",
			"http://api.example.com:80/x",
			"https://93.184.216.34/x",
			"https://[2606:4700:4700::1111]/x",
			"https://api.example.com./x",
			"https://xn--zca.example.com/x",
			"https://api.example.com/a/b/c?q=1&r=2#frag",
		):
			with self.subTest(url=url):
				self.assertEqual(guard.validate(url), self._transport_origin(url))


class TestUrlGuardBlockedNetworks(unittest.TestCase):
	"""stdlib yüklemleri RFC 6598'i KAPSAMIYOR ve sürüme göre değişiyor."""

	def test_carrier_grade_nat_and_tunnel_ranges_are_blocked(self) -> None:
		"""Hepsi ölçülerek eklendi — düzeltmeden önce kapıdan GEÇİYORLARDI."""
		for host in (
			"100.64.0.1",  # RFC 6598 CGNAT — AWS EKS pod CIDR, telekom NAT
			"100.100.100.200",  # Alibaba Cloud metadata servisi
			"[2002:7f00:1::1]",  # 6to4 gövdesinde 127.0.0.1
			"[2002:a9fe:a9fe::1]",  # 6to4 gövdesinde 169.254.169.254
			"192.31.196.1",  # AS112-v4
			"192.52.193.1",  # AMT
			"192.175.48.1",  # AS112 doğrudan delegasyon
			"192.88.99.1",  # 6to4 relay anycast
			"[64:ff9b::7f00:1]",  # NAT64 well-known
			"[2001::1]",  # Teredo
		):
			with self.subTest(host=host), self.assertRaises(UrlNotAllowedError) as ctx:
				UrlGuard().validate(f"https://{host}/x")
			self.assertEqual(ctx.exception.guard_code, "URL_HOST_BLOCKED")

	def test_resolved_addresses_go_through_the_same_list(self) -> None:
		"""Literal değil, ÇÖZÜMLENEN adres de listeden geçmeli."""

		def resolver(*_args: Any, **_kwargs: Any) -> list:
			return [(2, 1, 6, "", ("100.100.100.200", 443))]

		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard(resolver=resolver).validate("https://metadata.attacker.test/x")
		self.assertEqual(ctx.exception.guard_code, "URL_HOST_BLOCKED")

	def test_block_list_is_a_module_constant_not_a_stdlib_opinion(self) -> None:
		"""Güvenlik kararı Python sürümüne bırakılamaz (konteyner 3.11, prod 3.12)."""
		import ipaddress

		from tradehub_core.logistics.adapters.url_guard import BLOCKED_NETWORKS

		self.assertIn(ipaddress.ip_network("100.64.0.0/10"), BLOCKED_NETWORKS)
		self.assertIn(ipaddress.ip_network("2002::/16"), BLOCKED_NETWORKS)

	def test_public_addresses_are_still_allowed(self) -> None:
		"""Aşırı engelleme regresyonu: gerçek taşıyıcı uçları kapanmamalı."""
		for host in ("93.184.216.34", "8.8.8.8", "[2606:4700:4700::1111]"):
			with self.subTest(host=host):
				UrlGuard().validate(f"https://{host}/x")


class TestUrlGuardDoesNotLeakNetworkTopology(_NoSleep):
	"""`Carrier Integration Manager` hem base_url'e yazıyor hem logu okuyor."""

	@staticmethod
	def _resolver(*_args: Any, **_kwargs: Any) -> list:
		return [(2, 1, 6, "", ("10.2.3.4", 443))]

	def test_resolved_ip_is_absent_from_the_rejection_message(self) -> None:
		"""`internal-db.corp.local → 10.2.3.4` saldırganın BİLMEDİĞİ yeni bilgiydi."""
		with self.assertRaises(UrlNotAllowedError) as ctx:
			UrlGuard(resolver=self._resolver).validate("https://internal-db.corp.local/x")

		self.assertNotIn("10.2.3.4", str(ctx.exception))
		self.assertEqual(ctx.exception.guard_code, "URL_HOST_BLOCKED")

	def test_blocked_and_unresolvable_are_indistinguishable_in_the_log(self) -> None:
		"""İkinci oracle: "bu iç ad var mı?" sorusu logdan cevaplanamamalı."""

		def missing(*_args: Any, **_kwargs: Any) -> list:
			raise OSError("nodename nor servname provided")

		rows: list[dict[str, Any]] = []
		for resolver in (self._resolver, missing):
			session = FakeSession([FakeResponse(200, b"x")])
			client = _client(
				session,
				allow_private_hosts=False,
				provider=SEEDED_PROVIDER,
				logger=_Recorder(rows),
			)
			client._guard = UrlGuard(resolver=resolver)  # noqa: SLF001
			with self.assertRaises(CarrierAPIError):
				client.request("GET", "https://internal-db.corp.local/x", operation="track")

		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["error_code"], "URL_BLOCKED")
		self.assertEqual(rows[1]["error_code"], "URL_BLOCKED")
		self.assertEqual(rows[0]["error_message"], rows[1]["error_message"], "Mesaj ayrımı oracle bırakıyor")
		self.assertNotIn("10.2.3.4", rows[0]["error_message"])

	def test_collapsed_guard_rows_are_indistinguishable_in_every_column(self) -> None:
		"""DARALTMA KOMŞU SÜTUNA KAÇMIŞTI (2. turdan beri açık).

		`error_code`/`error_message` daraltılmıştı ama ayrım aynı satırın
		BAŞKA alanlarından okunabiliyordu:
		  * `is_retriable` = 1 ⟺ ad ÇÖZÜMLENEMEDİ, 0 ⟺ ad çözümlendi ama IP iç
		    ağa düştü (`Outcome.UNAVAILABLE` vs `NEUTRAL`);
		  * `attempt` — UNAVAILABLE retriable olduğu için `idempotent=True`
		    çağrılarda max_attempts'e çıkıyor, NEUTRAL'da 1 kalıyordu;
		  * `duration_ms` — DNS çözümlemesi ile literal IP reddi farklı süre;
		  * SATIR SAYISI — retriable kod N satır, diğeri 1 satır üretiyordu.

		`Carrier Integration Manager` hem `base_url`'e YAZIYOR hem logu
		OKUYOR; tehdit modeli kurulu.
		"""

		def missing(*_args: Any, **_kwargs: Any) -> list:
			raise OSError("nodename nor servname provided")

		fields = ("error_code", "error_message", "is_retriable", "attempt", "duration_ms")
		signatures: list[tuple] = []
		counts: list[int] = []
		for resolver in (self._resolver, missing):
			rows: list[dict[str, Any]] = []
			session = FakeSession([FakeResponse(200, b"x")])
			client = _client(
				session,
				allow_private_hosts=False,
				max_attempts=3,
				provider=SEEDED_PROVIDER,
				logger=_Recorder(rows),
			)
			client._guard = UrlGuard(resolver=resolver)  # noqa: SLF001
			with self.assertRaises(CarrierAPIError):
				# `idempotent=True` — UNAVAILABLE yolunda yeniden deneme açılır.
				client.request("GET", "https://internal-db.corp.local/x", operation="track", idempotent=True)
			counts.append(len(rows))
			signatures.append(tuple(rows[0][field] for field in fields))

		self.assertEqual(counts[0], counts[1], "Satır SAYISI ayrımı oracle bırakıyor")
		self.assertEqual(counts[0], 1, "Daraltılan kapı reddi çağrı başına TEK satır yazmalı")
		self.assertEqual(signatures[0], signatures[1], "Log satırı sütunlarından ayrım okunabiliyor")
		self.assertFalse(signatures[0][2], "`is_retriable` sabitlenmedi")

	@staticmethod
	def _missing(*_args: Any, **_kwargs: Any) -> list:
		raise OSError("nodename nor servname provided")

	def _drive_guard_branch(self, resolver: Any, *, calls: int) -> tuple[list[dict[str, Any]], list[str]]:
		"""Bir kapı reddi dalını N kez sürer; log satırlarını ve hata kodlarını döner.

		Devre kesici AÇIK (gerçek Redis) ve eşik varsayılan — oracle'ın 5. turda
		kaçtığı kanal tam olarak buydu.
		"""
		rows: list[dict[str, Any]] = []
		codes: list[str] = []
		carrier = f"TEST-{uuid.uuid4().hex[:8]}"
		for _ in range(calls):
			session = FakeSession([FakeResponse(200, b"x")])
			client = _client(
				session,
				carrier_code=carrier,
				circuit_breaker=True,
				allow_private_hosts=False,
				max_attempts=3,
				provider=SEEDED_PROVIDER,
				logger=_Recorder(rows),
			)
			client._guard = UrlGuard(resolver=resolver)  # noqa: SLF001
			with self.assertRaises(CarrierAPIError) as ctx:
				# `idempotent=True` — eski kodda UNAVAILABLE dalında yeniden deneme açılırdı.
				client.request("GET", "https://internal-db.corp.local/x", operation="track", idempotent=True)
			codes.append(ctx.exception.carrier_error_code)
		return rows, codes

	def test_circuit_breaker_state_is_not_an_internal_network_oracle(self) -> None:
		"""5. TUR KİLİDİ: devre kesici DURUMU ayrımı sızdırıyordu.

		Eskiden `URL_UNRESOLVABLE` → `Outcome.UNAVAILABLE` → `record_failure()`
		iken `URL_HOST_BLOCKED` → `NEUTRAL` → mutlak no-op idi. Eşikten (5) sonra
		çözümlenemeyen ad devreyi AÇIYOR, iç adrese düşen açmıyordu; 6. çağrı
		`carrier_error_code="CIRCUIT_OPEN"` ile dönüyordu. Log OKUMA yetkisi bile
		gerekmiyordu — `base_url`'e yazabilen rol ad başına temiz 1 bit alıyordu.

		Ayrım artık KAYNAKTA birleşti: eşik+1 çağrıdan sonra iki dal AYNI satır
		kümesini, AYNI satır sayısını ve AYNI `carrier_error_code`'u üretmeli.
		"""
		calls = hc.CIRCUIT_FAILURE_THRESHOLD + 1
		fields = ("error_code", "error_message", "is_retriable", "attempt", "duration_ms")

		blocked_rows, blocked_codes = self._drive_guard_branch(self._resolver, calls=calls)
		missing_rows, missing_codes = self._drive_guard_branch(self._missing, calls=calls)

		self.assertEqual(len(blocked_rows), len(missing_rows), "Satır SAYISI ayrımı oracle bırakıyor")
		self.assertEqual(len(blocked_rows), calls, "Kapı reddi çağrı başına TEK satır yazmalı")
		self.assertEqual(
			[tuple(row[f] for f in fields) for row in blocked_rows],
			[tuple(row[f] for f in fields) for row in missing_rows],
			"Log satır kümesi iki dalda ayrışıyor",
		)
		self.assertEqual(blocked_codes, missing_codes, "`carrier_error_code` ayrımı oracle bırakıyor")
		self.assertNotIn("CIRCUIT_OPEN", blocked_codes, "Kapı reddi devreyi AÇMAMALI")
		self.assertEqual(set(missing_codes), {"URL_BLOCKED"})

	def test_guard_rejection_never_retries_in_either_branch(self) -> None:
		"""Deneme SAYISI da bir kanaldı: `error.attempts` çağırana doğrudan dönüyor.

		Kapı reddi POLİTİKADAN BAĞIMSIZ olarak tek denemede biter — `idempotent`
		ve `max_attempts` ne olursa olsun.
		"""
		for label, resolver in (("blocked", self._resolver), ("unresolvable", self._missing)):
			with self.subTest(branch=label):
				session = FakeSession([FakeResponse(200, b"x")])
				client = _client(session, allow_private_hosts=False, max_attempts=3)
				client._guard = UrlGuard(resolver=resolver)  # noqa: SLF001

				with self.assertRaises(CarrierAPIError) as ctx:
					client.request(
						"GET", "https://internal-db.corp.local/x", operation="track", idempotent=True
					)

				self.assertEqual(ctx.exception.attempts, 1, "Kapı reddi yeniden denendi — oracle geri geldi")
				self.assertEqual(ctx.exception.carrier_error_code, "URL_BLOCKED")

	def test_internal_telemetry_keeps_the_distinction_in_both_branches(self) -> None:
		"""Ayrım KAYBOLMADI: gerçek `guard_code` iç telemetride durmalı."""
		for code, resolver in (
			("URL_HOST_BLOCKED", self._resolver),
			("URL_UNRESOLVABLE", self._missing),
		):
			with self.subTest(guard_code=code):
				session = FakeSession([FakeResponse(200, b"x")])
				client = _client(session, allow_private_hosts=False)
				client._guard = UrlGuard(resolver=resolver)  # noqa: SLF001

				with mock.patch(f"{_MODULE}._warn") as warn, self.assertRaises(CarrierAPIError):
					client.request("GET", "https://internal-db.corp.local/x", operation="track")

				messages = " ".join(str(call.args[0]) for call in warn.call_args_list)
				self.assertIn(code, messages)


class TestGuardRejectionAfterARealFailure(_NoSleep):
	"""KAPI REDDİ 1. DENEMEDEN SONRA GELİRSE DocType'a HİÇ YAZILMIYORDU (6. tur).

	Koşul `attempt_no == 1` idi. ÖLÇÜLEN akış: 1. deneme `ConnectionError`
	(retriable → yeniden denenir), 2. deneme `URL_HOST_BLOCKED`. Yazılan satır
	1 taneydi ve yalnız `NETWORK_ERROR`'ı anlatıyordu — ENGELLENEN SSRF DENEMESİ
	denetim izinde HİÇ görünmüyordu.

	İKİNCİ YAN ETKİ (aynı ölçüm): `if last is None or not last.collapsed_guard`
	nedeniyle `breaker.record` HİÇ çağrılmıyordu, yani GERÇEK olan 1. deneme
	arızası devre kesici sayacına İŞLENMİYORDU. DNS yanıtını değiştirebilen biri
	böylece gerçek arızaların SAYILMASINI bastırabilirdi.
	"""

	PUBLIC = [(2, 1, 6, "", ("93.184.216.34", 443))]
	INTERNAL = [(2, 1, 6, "", ("10.2.3.4", 443))]

	class _FlipResolver:
		"""1. çağrıda kapı GEÇER (gerçek ağ hatası olsun), 2. çağrıda REDDEDER."""

		def __init__(self, public: list, blocked: list | None) -> None:
			self.calls = 0
			self._public = public
			self._blocked = blocked

		def __call__(self, *_args: Any, **_kwargs: Any) -> list:
			self.calls += 1
			if self.calls == 1:
				return self._public
			if self._blocked is None:
				raise OSError("nodename nor servname provided")
			return self._blocked

	def _drive(self, *, unresolvable: bool, breaker: bool = False) -> tuple[list[dict[str, Any]], list[Any]]:
		rows: list[dict[str, Any]] = []
		session = FakeSession([requests.ConnectionError("boom"), FakeResponse(200, b"x")])
		client = _client(
			session,
			circuit_breaker=breaker,
			allow_private_hosts=False,
			max_attempts=3,
			provider=SEEDED_PROVIDER,
			logger=_Recorder(rows),
		)
		client._guard = UrlGuard(  # noqa: SLF001
			resolver=self._FlipResolver(self.PUBLIC, None if unresolvable else self.INTERNAL)
		)
		with mock.patch.object(client.breaker, "record") as record, self.assertRaises(CarrierAPIError):
			client.request("GET", "https://internal-db.corp.local/x", operation="track", idempotent=True)
		return rows, [call.args[0] for call in record.call_args_list]

	def test_guard_rejection_after_the_first_attempt_is_still_logged(self) -> None:
		"""Engellenen SSRF denemesi denetim izinde GÖRÜNMELİ."""
		for label, unresolvable in (("blocked", False), ("unresolvable", True)):
			with self.subTest(branch=label):
				rows, _ = self._drive(unresolvable=unresolvable)

				self.assertEqual([row["error_code"] for row in rows], ["NETWORK_ERROR", "URL_BLOCKED"])
				guard_row = rows[1]
				self.assertEqual(guard_row["attempt"], 1, "Kapı satırı `attempt_no`'dan bağımsız olmalı")
				self.assertEqual(guard_row["duration_ms"], 0)
				self.assertFalse(guard_row["is_retriable"])

	def test_guard_rejection_row_is_written_once_per_call(self) -> None:
		"""ÇAĞRI BAŞINA tek satır — deneme başına DEĞİL (oracle: satır sayısı)."""
		blocked_rows, _ = self._drive(unresolvable=False)
		missing_rows, _ = self._drive(unresolvable=True)

		self.assertEqual(len(blocked_rows), len(missing_rows), "Satır SAYISI ayrımı oracle bırakıyor")
		self.assertEqual(sum(1 for row in blocked_rows if row["error_code"] == "URL_BLOCKED"), 1)

	def test_real_failure_before_a_guard_rejection_is_recorded_on_the_breaker(self) -> None:
		"""GERÇEK arıza sayaca işlenmeli; kapı reddi onu BASTIRAMAMALI."""
		for label, unresolvable in (("blocked", False), ("unresolvable", True)):
			with self.subTest(branch=label):
				_, recorded = self._drive(unresolvable=unresolvable, breaker=True)

				self.assertEqual(
					[outcome.name for outcome in recorded],
					["UNAVAILABLE"],
					"1. denemenin GERÇEK arızası devre kesiciye işlenmedi",
				)

	def test_both_guard_branches_stay_indistinguishable(self) -> None:
		"""ORACLE EŞİTLİĞİ: kapı satırı iki dalda BİT BİT aynı olmalı."""
		fields = ("error_code", "error_message", "is_retriable", "attempt", "duration_ms")
		blocked_rows, blocked_record = self._drive(unresolvable=False, breaker=True)
		missing_rows, missing_record = self._drive(unresolvable=True, breaker=True)

		self.assertEqual(
			tuple(blocked_rows[1][field] for field in fields),
			tuple(missing_rows[1][field] for field in fields),
			"Kapı satırı sütunlarından ayrım okunabiliyor",
		)
		self.assertEqual(
			[outcome.name for outcome in blocked_record],
			[outcome.name for outcome in missing_record],
			"Devre kesici kayıt dizisi ayrım bırakıyor",
		)


class TestIpPinning(unittest.TestCase):
	"""Doğrulanan ad ≠ bağlanılan ad — rebinding'in ve IDNA farkının kök nedeni."""

	class _Request:
		def __init__(self, url: str) -> None:
			self.url = url
			self.headers: dict[str, str] = {}

	def test_pool_key_host_becomes_the_validated_ip(self) -> None:
		adapter = hc.GuardedHTTPAdapter()
		self.addCleanup(adapter.close)
		adapter.pin("kargo.example.com", "93.184.216.34")

		host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(
			self._Request("https://kargo.example.com/x"), True
		)

		self.assertEqual(host_params["host"], "93.184.216.34")
		self.assertEqual(pool_kwargs["assert_hostname"], "kargo.example.com", "Sertifika IP'ye doğrulanıyor")
		self.assertEqual(pool_kwargs["server_hostname"], "kargo.example.com", "SNI kayboldu")

	def test_without_a_pin_nothing_changes(self) -> None:
		adapter = hc.GuardedHTTPAdapter()
		self.addCleanup(adapter.close)

		host_params, pool_kwargs = adapter.build_connection_pool_key_attributes(
			self._Request("https://kargo.example.com/x"), True
		)

		self.assertEqual(host_params["host"], "kargo.example.com")
		self.assertNotIn("assert_hostname", pool_kwargs)
		self.assertNotIn("server_hostname", pool_kwargs)

	def test_a_rewritten_host_fails_closed(self) -> None:
		"""IDNA farkının imzası: kapı bir adı pinledi, transport BAŞKASINA gidiyor."""
		adapter = hc.GuardedHTTPAdapter()
		self.addCleanup(adapter.close)
		adapter.pin("ss.attacker.test", "93.184.216.34")

		with self.assertRaises(UrlNotAllowedError) as ctx:
			adapter.build_connection_pool_key_attributes(
				self._Request("https://xn--zca.attacker.test/x"), True
			)

		self.assertEqual(ctx.exception.guard_code, "URL_HOST_BLOCKED")

	def test_host_header_carries_the_original_name(self) -> None:
		"""urllib3 Host'u havuzun host'undan türetir; pinliyken o IP olurdu."""
		adapter = hc.GuardedHTTPAdapter()
		self.addCleanup(adapter.close)
		adapter.pin("kargo.example.com", "93.184.216.34")
		request = self._Request("https://kargo.example.com:8443/x")

		with mock.patch.object(requests.adapters.HTTPAdapter, "send", return_value="ok"):
			adapter.send(request)

		self.assertEqual(request.headers["Host"], "kargo.example.com:8443")

	def test_pins_are_thread_local(self) -> None:
		"""Session'ı paylaşan işçiler birbirinin pinini görmemeli."""
		import threading

		adapter = hc.GuardedHTTPAdapter()
		self.addCleanup(adapter.close)
		adapter.pin("kargo.example.com", "93.184.216.34")
		seen: list[Any] = []

		def worker() -> None:
			params, _kw = adapter.build_connection_pool_key_attributes(
				self._Request("https://kargo.example.com/x"), True
			)
			seen.append(params["host"])

		thread = threading.Thread(target=worker)
		thread.start()
		thread.join()

		self.assertEqual(seen, ["kargo.example.com"])

	def test_client_pins_the_address_the_guard_validated(self) -> None:
		"""Uçtan uca: kapının döndürdüğü IP transporta ULAŞIYOR."""

		def resolver(*_args: Any, **_kwargs: Any) -> list:
			return [(2, 1, 6, "", ("93.184.216.34", 443))]

		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, allow_private_hosts=False)
		client._guard = UrlGuard(resolver=resolver)  # noqa: SLF001
		adapter = hc.GuardedHTTPAdapter()
		self.addCleanup(adapter.close)
		client._pin_adapter = adapter  # noqa: SLF001
		captured: list[str | None] = []

		def spy(host: str, address: str | None) -> None:
			captured.append(address)

		with mock.patch.object(adapter, "pin", spy):
			client.request("GET", "https://kargo.example.com/x", operation="track")

		self.assertEqual(captured, ["93.184.216.34"])

	def test_sandbox_mode_does_not_pin(self) -> None:
		"""Hiçbir IP doğrulanmadığı için pinlemenin güvenlik değeri yok."""
		origin, pin = UrlGuard(allow_private_hosts=True).validate_pinned("https://kargo.test/x")
		self.assertEqual(origin, ("https", "kargo.test", 443))
		self.assertIsNone(pin)


class TestSessionHardening(unittest.TestCase):
	def test_own_session_ignores_the_environment(self) -> None:
		"""ÖLÇÜLDÜ: HTTPS_PROXY kapının IP kararını tamamen geçersiz kılıyordu."""
		client = CarrierHttpClient("hardening", allow_private_hosts=True, circuit_breaker=False)
		self.addCleanup(client.close)

		session = client._get_session()  # noqa: SLF001

		self.assertFalse(session.trust_env, "trust_env açık — proxy kapıyı atlatır")
		self.assertEqual(session.proxies, {})
		self.assertIs(session.verify, True)
		self.assertIsInstance(session.get_adapter("https://x.test/"), hc.GuardedHTTPAdapter)

	def test_unexpected_injected_session_is_reported(self) -> None:
		injected = requests.Session()
		self.addCleanup(injected.close)
		injected.trust_env = True
		injected.proxies = {"https": "http://127.0.0.1:8123"}

		with mock.patch(f"{_MODULE}._warn") as warn:
			CarrierHttpClient("hardening", session=injected, circuit_breaker=False)

		messages = " ".join(str(call.args[0]) for call in warn.call_args_list)
		self.assertIn("trust_env=True", messages)
		self.assertIn("proxies", messages)


class TestBodyReadDeadline(_NoSleep):
	"""Bayt tavanı slow-loris'i durdurmuyor — okuma timeout'u her chunk'ta sıfırlanıyor."""

	class _DripResponse:
		"""Her chunk'tan önce bekleyen sahte akış."""

		def __init__(self, chunks: int, delay: float) -> None:
			self.headers: dict[str, str] = {"Content-Type": "text/plain"}
			self.status_code = 200
			self.encoding = "utf-8"
			self._chunks = chunks
			self._delay = delay
			self.closed = False

		def iter_content(self, chunk_size: int = 8192) -> Any:
			for _i in range(self._chunks):
				time.sleep(self._delay)
				yield b"x"

		def close(self) -> None:
			self.closed = True

	class _EmptyChunkResponse:
		"""Yalnız BOŞ parça üreten akış — bütçe kontrolü buna da uygulanmalı."""

		def __init__(self, chunks: int, delay: float) -> None:
			self.headers: dict[str, str] = {"Content-Type": "text/plain"}
			self.status_code = 200
			self.encoding = "utf-8"
			self._chunks = chunks
			self._delay = delay
			self.closed = False

		def iter_content(self, chunk_size: int = 8192) -> Any:
			for _i in range(self._chunks):
				time.sleep(self._delay)
				yield b""

		def close(self) -> None:
			self.closed = True

	def test_read_capped_budget_applies_to_empty_chunks(self) -> None:
		"""`if not chunk: continue` son tarih kontrolünün ÜSTÜNDEYDİ.

		ÖLÇÜLDÜ: 1,0 sn boyunca yalnız `b''` üreten bir akışta `max_seconds=0.05`
		ile istisna ancak ilk DOLU parça geldiğinde, 1,0 sn sonra atılıyordu.
		Sürekli boş parça üreten bir akışta bütçe HİÇ ateşlenmezdi — `read1`
		geçişinin kapatmak istediği slow-loris yüzeyi `iter_content` düşüş
		yolunda açık kalmıştı.
		"""
		raw = self._EmptyChunkResponse(chunks=1000, delay=0.002)

		started = time.monotonic()
		with self.assertRaises(hc._BodyReadDeadline):  # noqa: SLF001
			hc._read_capped(raw, cap=1024, max_seconds=0.05)  # noqa: SLF001
		elapsed = time.monotonic() - started

		self.assertLess(elapsed, 0.5, f"Boş parçalarda süre bütçesi uygulanmadı ({elapsed:.2f} sn)")

	def test_read_capped_stops_at_the_absolute_deadline(self) -> None:
		raw = self._DripResponse(chunks=100, delay=0.01)

		started = time.monotonic()
		with self.assertRaises(hc._BodyReadDeadline):  # noqa: SLF001
			hc._read_capped(raw, cap=1024, max_seconds=0.05)  # noqa: SLF001
		elapsed = time.monotonic() - started

		self.assertLess(elapsed, 0.5, f"Süre bütçesi uygulanmadı ({elapsed:.2f} sn)")

	def test_slow_body_maps_to_a_timeout_and_closes_the_connection(self) -> None:
		raw = self._DripResponse(chunks=100, delay=0.01)
		session = FakeSession([raw])
		client = _client(session, max_body_read_sec=0.05)

		with self.assertRaises(CarrierTimeoutError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(ctx.exception.carrier_error_code, "BODY_READ_TIMEOUT")
		self.assertEqual(ctx.exception.http_status_code, 504)
		self.assertTrue(raw.closed, "Yavaş bağlantı açık bırakıldı")

	def test_reader_prefers_read1_so_the_budget_can_actually_fire(self) -> None:
		"""`iter_content(N)` N BAYT DOLANA KADAR bloke olur — bütçe hiç çalışmazdı.

		Süre bütçesi eklendikten SONRA bile gerçek soketle ölçüldüğünde istek
		kesilmiyordu: tek bir `iter_content` adımı 64 KiB'ı beklerken kontrol
		noktasına hiç dönülmüyordu. Okuma `urllib3.HTTPResponse.read1`'e taşındı.
		"""

		class _Urllib3Like:
			def __init__(self) -> None:
				self.calls: list[tuple[int, bool]] = []
				self._queue = [b"ab", b"cd", b""]

			def read1(self, amt: int, decode_content: bool = False) -> bytes:
				self.calls.append((amt, decode_content))
				# GERÇEK bir akış EOF'tan sonra `b''` DÖNMEYE DEVAM EDER, patlamaz.
				return self._queue.pop(0) if self._queue else b""

			def isclosed(self) -> bool:
				return not self._queue

		class _Response:
			def __init__(self, inner: Any) -> None:
				self.raw = inner
				self.headers: dict[str, str] = {}

			def iter_content(self, chunk_size: int = 8192) -> Any:
				raise AssertionError("read1 varken iter_content kullanıldı")

		inner = _Urllib3Like()
		content, truncated = hc._read_capped(_Response(inner), cap=1024, max_seconds=5.0)  # noqa: SLF001

		self.assertEqual(content, b"abcd")
		self.assertFalse(truncated)
		self.assertTrue(all(decode for _amt, decode in inner.calls), "decode_content kapalı — gzip bombası")

	def test_reader_falls_back_to_iter_content(self) -> None:
		"""`read1` sunmayan yanıt nesneleri (eski urllib3, sahteler) çalışmaya devam eder."""
		raw = FakeResponse(200, b"z" * 300, {"Content-Type": "text/plain"})

		content, truncated = hc._read_capped(raw, cap=1024, max_seconds=5.0)  # noqa: SLF001

		self.assertEqual(content, b"z" * 300)
		self.assertFalse(truncated)

	def test_read1_fallback_is_reported_not_silent(self) -> None:
		"""Düşüş SESSİZ kalırsa slow-loris savunmasının granülaritesi görünmez düşer.

		`GuardedHTTPAdapter` ve `_iter_body` `requests`/`urllib3` İÇ yüzeylerine
		bağlı; bir sürüm yükseltmesi ikisini de uyarısız kaldırabilir.
		"""
		fault_report.reset_throttle()
		self.addCleanup(fault_report.reset_throttle)
		raw = FakeResponse(200, b"z" * 300, {"Content-Type": "text/plain"})

		with mock.patch("frappe.log_error") as log_error:
			hc._read_capped(raw, cap=1024, max_seconds=5.0)  # noqa: SLF001
			hc._read_capped(raw, cap=1024, max_seconds=5.0)  # noqa: SLF001

		self.assertEqual(log_error.call_count, 1, "Düşüş ya sessiz ya da kısılmamış")
		self.assertIn("read1", log_error.call_args.args[0])

	def test_empty_read1_is_not_mistaken_for_eof(self) -> None:
		"""`decode_content=True` ile decoder boş dönebilir — gövde SESSİZCE kırpılıyordu.

		Sır sızdırmaz ama teşhis kaybettirir: yanıtın yarısı log'a hiç düşmez.
		"""

		class _LazyDecoder:
			def __init__(self) -> None:
				self._queue = [b"ab", b"", b"", b"cd", b""]

			def read1(self, amt: int, decode_content: bool = False) -> bytes:
				return self._queue.pop(0) if self._queue else b""

			def isclosed(self) -> bool:
				return not self._queue

		class _Response:
			def __init__(self, inner: Any) -> None:
				self.raw = inner
				self.headers: dict[str, str] = {}

			def iter_content(self, chunk_size: int = 8192) -> Any:
				raise AssertionError("read1 varken iter_content kullanıldı")

		content, truncated = hc._read_capped(_Response(_LazyDecoder()), cap=1024, max_seconds=5.0)  # noqa: SLF001

		self.assertEqual(content, b"abcd", "Boş parça EOF sanıldı — gövde kırpıldı")
		self.assertFalse(truncated)

	def test_empty_reads_still_honour_the_time_budget(self) -> None:
		"""Boş turlar tolere edilirken slow-loris bütçesi ATLANMAMALI."""

		class _AlwaysEmpty:
			def read1(self, amt: int, decode_content: bool = False) -> bytes:
				time.sleep(0.01)
				return b""

		class _Response:
			def __init__(self, inner: Any) -> None:
				self.raw = inner
				self.headers: dict[str, str] = {}

		with self.assertRaises(hc._BodyReadDeadline):  # noqa: SLF001
			hc._read_capped(_Response(_AlwaysEmpty()), cap=1024, max_seconds=0.02)  # noqa: SLF001


class TestTransportSurfaceSmoke(unittest.TestCase):
	"""İKİ GÜVENLİK KONTROLÜ `requests`/`urllib3` İÇ YÜZEYİNE BAĞLI.

	Sürüm yükseltmesi bu yüzeyleri uyarısız kaldırırsa IP pinlemesi ve
	slow-loris bütçesi SESSİZCE devre dışı kalır. Taban sürümler
	`pyproject.toml` + `requirements.txt`'te (`requests>=2.32`, `urllib3>=2`);
	bu test o tabanın gerçekten yeterli olduğunu doğrular.
	"""

	def test_requests_and_urllib3_baselines_are_met(self) -> None:
		import urllib3

		self.assertGreaterEqual(tuple(int(p) for p in requests.__version__.split(".")[:2]), (2, 32))
		self.assertGreaterEqual(int(urllib3.__version__.split(".")[0]), 2)

	def test_pinning_hook_exists_on_the_adapter_base(self) -> None:
		"""`GuardedHTTPAdapter` bu metodu override ediyor — kaybolursa pinleme düşer."""
		self.assertTrue(
			hasattr(requests.adapters.HTTPAdapter, "build_connection_pool_key_attributes"),
			"requests IP pinleme yüzeyini kaldırdı — GuardedHTTPAdapter sessizce no-op olur",
		)

	def test_urllib3_response_exposes_read1(self) -> None:
		"""`_iter_body` süre bütçesi bu imzaya bağlı."""
		import inspect as _inspect

		import urllib3

		read1 = getattr(urllib3.response.HTTPResponse, "read1", None)
		self.assertTrue(callable(read1), "urllib3 `read1`'i kaldırdı — bütçe iter_content'a düşer")
		self.assertIn("decode_content", _inspect.signature(read1).parameters)

	def test_fast_body_is_unaffected(self) -> None:
		session = FakeSession([FakeResponse(200, b"ok" * 100, {"Content-Type": "text/plain"})])
		client = _client(session, max_body_read_sec=5.0)

		self.assertEqual(client.request("GET", "https://kargo.test/x", operation="track").status_code, 200)


class TestRedirectHandling(_NoSleep):
	def test_redirect_target_passes_through_the_guard(self) -> None:
		"""Açık uçtan iç ağa yönlendirme — requests'in kendi takibi bunu kaçırırdı."""
		session = FakeSession(
			[
				FakeResponse(302, b"", {"Location": "https://127.0.0.1/admin"}),
				FakeResponse(200, b"ic ag"),
			]
		)
		client = _client(session, allow_private_hosts=False)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://93.184.216.34/x", operation="track")

		self.assertEqual(session.call_count, 1, "Yönlendirme hedefi doğrulanmadan istendi!")
		self.assertEqual(ctx.exception.carrier_error_code, "URL_BLOCKED")

	def test_cross_origin_redirect_drops_carrier_credentials(self) -> None:
		"""requests yalnız Authorization'ı düşürür; X-Api-Key saldırgana giderdi."""
		session = FakeSession(
			[
				FakeResponse(302, b"", {"Location": "https://evil.test/steal"}),
				FakeResponse(200, b"ok"),
			]
		)
		client = _client(session)

		client.request(
			"GET",
			"https://kargo.test/x",
			operation="track",
			headers={"X-Api-Key": "gizli", "Authorization": "Bearer t", "SOAPAction": "Track"},
		)

		second = session.calls[1]["headers"]
		self.assertNotIn("X-Api-Key", second)
		self.assertNotIn("Authorization", second)
		self.assertNotIn("SOAPAction", second)
		self.assertIn("User-Agent", second)

	def test_same_origin_redirect_keeps_headers(self) -> None:
		session = FakeSession(
			[
				FakeResponse(307, b"", {"Location": "https://kargo.test/v2"}),
				FakeResponse(200, b"ok"),
			]
		)
		client = _client(session)

		client.request(
			"POST",
			"https://kargo.test/x",
			operation="cancel",
			headers={"X-Api-Key": "gizli"},
			body=b"payload",
		)

		second = session.calls[1]
		self.assertEqual(second["headers"]["X-Api-Key"], "gizli")
		self.assertEqual(second["method"], "POST", "307 metodu korumalı")
		self.assertEqual(second["data"], b"payload")

	def test_302_downgrades_to_get_and_drops_body(self) -> None:
		session = FakeSession(
			[
				FakeResponse(302, b"", {"Location": "https://kargo.test/v2"}),
				FakeResponse(200, b"ok"),
			]
		)
		client = _client(session)

		client.request("POST", "https://kargo.test/x", operation="cancel", body=b"payload")

		self.assertEqual(session.calls[1]["method"], "GET")
		self.assertIsNone(session.calls[1]["data"])

	def test_redirect_loop_is_bounded(self) -> None:
		session = FakeSession([FakeResponse(302, b"", {"Location": "https://kargo.test/loop"})])
		client = _client(session, max_redirects=2)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(session.call_count, 3, "1 ilk istek + 2 yönlendirme")
		self.assertEqual(ctx.exception.carrier_error_code, "URL_INVALID")


# ---------------------------------------------------------------------------
# Hata sözleşmesi
# ---------------------------------------------------------------------------


class TestErrorContract(_NoSleep):
	def test_exception_carries_no_raw_carrier_response(self) -> None:
		"""Ham gövde + Set-Cookie istisnaya iliştirilirse traceback'le Error Log'a düşer."""
		session = FakeSession([FakeResponse(500, b"secret=abc", {"Set-Cookie": "session=xyz"})])
		client = _client(session)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertFalse(hasattr(ctx.exception, "response"))
		self.assertNotIn("secret", str(ctx.exception))
		self.assertNotIn("xyz", str(ctx.exception))

	def test_transport_exception_text_never_reaches_the_integration_log(self) -> None:
		"""requests hata metni credential + HOST + PORT taşır — DocType'a HAM geçmez.

		Ölçülmüştü: açık iç port `SSLError`, kapalı port `ConnectionError`
		metniyle dönüyor ve `Carrier Integration Log`'u okuyabilen rol için tam
		bir iç port tarayıcısı oluyordu. Loga yalnız istisna SINIFI yazılır;
		ham metin `logistics` logger'ında (iç telemetri) kalır.
		"""
		session = FakeSession(
			[requests.exceptions.ConnectionError("https://kargo.test:8123/x?api_key=GIZLI reddedildi")]
		)
		records: list[dict[str, Any]] = []
		client = _client(session, provider=SEEDED_PROVIDER, logger=_Recorder(records))

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track")

		logged = records[0]["error_message"]
		self.assertNotIn("GIZLI", str(ctx.exception))
		self.assertNotIn("GIZLI", logged, "Credential entegrasyon loguna sızdı")
		self.assertNotIn("8123", logged, "Port entegrasyon loguna sızdı — port tarama oracle'ı")
		self.assertIn("ConnectionError", logged, "Operatörün sınıflandırması kayboldu")
		self.assertEqual(records[0]["error_code"], "NETWORK_ERROR")

	def test_error_carries_structured_diagnostics_only(self) -> None:
		session = FakeSession([FakeResponse(503, b"down")])
		client = _client(session, max_attempts=2)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		error = ctx.exception
		self.assertEqual(error.carrier_status, 503)
		self.assertEqual(error.carrier_error_code, "HTTP_503")
		self.assertEqual(error.attempts, 2)
		self.assertGreaterEqual(error.elapsed_ms, 0)


# ---------------------------------------------------------------------------
# Log yazıcısı enjeksiyonu
# ---------------------------------------------------------------------------


class TestLogFailureThrottling(_NoSleep):
	"""Kardeş yol (`circuit_breaker._report_fault`) kısıyordu, bu yol KISMIYORDU."""

	def setUp(self) -> None:
		super().setUp()
		fault_report.reset_throttle()
		self.addCleanup(fault_report.reset_throttle)

	def test_repeated_log_failures_write_one_error_log(self) -> None:
		"""Kalıcı bir log arızasında istek başına `Error Log` satırı oluşuyordu."""

		def exploding_logger(**_kwargs: Any) -> str:
			raise RuntimeError("log DB'si çöktü")

		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=exploding_logger)

		with mock.patch("frappe.log_error") as log_error:
			for _index in range(20):
				client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(_log_failure_reports(log_error), 1, "Error Log fırtınası — kısma yok")

	def test_throttle_scope_separates_operations(self) -> None:
		"""Kapsam `carrier_code + operation`: farklı operasyonlar birbirini gizlememeli."""

		def exploding_logger(**_kwargs: Any) -> str:
			raise RuntimeError("log DB'si çöktü")

		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=exploding_logger)

		with mock.patch("frappe.log_error") as log_error:
			client.request("GET", "https://kargo.test/x", operation="track")
			client.request("GET", "https://kargo.test/x", operation="quote")

		self.assertEqual(_log_failure_reports(log_error), 2)

	def test_open_notice_key_release_is_also_throttled(self) -> None:
		"""`claim → düş → release → yeniden claim` çevrimi sınırsızdı.

		Devre AÇIKKEN etki katlanıyordu: her istek anahtarı yeniden talep edip
		yeniden düşürüyor, cooldown başına tek satır garantisi anlamını
		yitiriyordu.
		"""
		releases: list[int] = []

		class _AlwaysOpenBreaker:
			enabled = True

			def state(self) -> Any:
				return hc.CircuitState.OPEN

			def acquire_probe(self) -> bool:
				return False

			def claim_open_notice(self) -> bool:
				return True

			def release_open_notice(self) -> None:
				releases.append(1)

			def record(self, *_args: Any, **_kwargs: Any) -> None:
				return None

		def exploding_logger(**_kwargs: Any) -> str:
			raise RuntimeError("log DB'si çöktü")

		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=exploding_logger)
		client.breaker = _AlwaysOpenBreaker()  # type: ignore[assignment]

		with mock.patch("frappe.log_error"):
			for _index in range(20):
				with self.assertRaises(CarrierAPIError):
					client.request("GET", "https://kargo.test/x", operation="track")

		self.assertLess(len(releases), 20, "Anahtar her istekte geri veriliyor — çevrim kısılmadı")
		self.assertGreaterEqual(len(releases), 1, "Geçici arızada anahtar hiç geri verilmiyor")


class TestLoggerInjection(_NoSleep):
	def test_logger_arguments_match_write_integration_log_signature(self) -> None:
		"""İMZA SÖZLEŞMESİ: elle yazılmış anahtar listesi sözleşmenin 3. kopyası olurdu."""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(201, b'{"id":1}', {"Content-Type": "application/json"})])
		client = _client(
			session,
			carrier_code="aras",
			provider=SEEDED_PROVIDER,
			logger=_Recorder(records),
		)

		client.request(
			"POST",
			"https://kargo.test/shipments",
			operation="create_shipment",
			body={"ref": "SHP-1"},
			shipment="SHP-0001",
			carrier_account="CA-0001",
		)

		self.assertEqual(len(records), 1)
		record = records[0]
		accepted = set(inspect.signature(write_integration_log).parameters)
		self.assertTrue(
			set(record) <= accepted,
			f"write_integration_log bu anahtarları kabul etmiyor: {sorted(set(record) - accepted)}",
		)
		required = {
			name
			for name, param in inspect.signature(write_integration_log).parameters.items()
			if param.default is inspect.Parameter.empty
		}
		self.assertTrue(required <= set(record), f"Zorunlu alan eksik: {sorted(required - set(record))}")

		self.assertEqual(record["operation"], "create_shipment")
		self.assertEqual(record["direction"], "outbound")
		self.assertTrue(record["succeeded"])
		self.assertEqual(record["http_status"], 201)
		self.assertEqual(record["attempt"], 1)
		self.assertEqual(record["request_body"], '{"ref": "SHP-1"}')
		self.assertEqual(record["response_body"], '{"id":1}')
		self.assertEqual(record["shipment"], "SHP-0001")
		self.assertEqual(record["carrier_account"], "CA-0001")

	def test_log_carrier_field_is_the_provider_not_the_registry_code(self) -> None:
		"""KRİTİK: `carrier` bir `Logistics Provider` Link'i; registry kodu oraya YAZILAMAZ."""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(
			session,
			carrier_code="aras",
			provider=SEEDED_PROVIDER,
			logger=_Recorder(records),
		)

		client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(records[0]["carrier"], SEEDED_PROVIDER)
		self.assertNotEqual(records[0]["carrier"], "aras")

	def test_missing_provider_disables_logging_fail_safe(self) -> None:
		"""provider yoksa her satır LinkValidationError'da düşerdi — hiç yazmıyoruz."""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, carrier_code="aras", logger=_Recorder(records))

		client.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(records, [])

	def test_secret_values_reach_the_log_writer(self) -> None:
		"""Değer-tabanlı redaksiyonun BESLEME hattı.

		Anahtar denylist'i taşıyıcının alan ADINI tanımak zorunda; bilinmeyen bir
		şema (`<Xyz42>SECRET</Xyz42>`) onu atlatır. Log katmanı sır DEĞERLERİNİ
		birebir silebilsin diye credential dokümanındaki gizli alanlar ve
		adapter'ın eklediği kısa ömürlü sırlar yazıcıya İLETİLMELİ — bu bağ
		kopduğunda hiçbir test kırılmıyordu (denetim 2026-08-26).
		"""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(
			session,
			provider=SEEDED_PROVIDER,
			credential_doc={"api_key": "SUPERSECRET_APIKEY_9988", "base_url": "https://kargo.test"},
			extra_secret_values=["OTURUM_JETONU_777"],
			logger=_Recorder(records),
		)

		client.request("GET", "https://kargo.test/x", operation="track")

		secrets = set(records[0]["secret_values"]) | set(records[0].get("extra_secret_values") or ())
		self.assertIn("SUPERSECRET_APIKEY_9988", secrets)
		self.assertIn("OTURUM_JETONU_777", secrets)
		# `base_url` sır DEĞİL: redakte edilirse log okunamaz hale gelir.
		self.assertNotIn("https://kargo.test", secrets)

	def test_extra_secrets_survive_an_unresolved_credential_doc(self) -> None:
		"""İKİ AYRI KAYNAK, İKİ AYRI KANAL — ölçülmüş birlikte düşme.

		`credential_doc` çözülemeyince (Frappe `Password` yer tutucusu)
		`collect_secret_values` `None` döner ve `secret_values` HİÇ geçilmez —
		guardrail bilinçli. Ama `extra` FARKLI KAYNAKTIR: adapter'ın ürettiği
		kısa ömürlü jeton taşıyıcının YANITINDA geri döner ve denylist'in en
		kolay atladığı materyaldir. Eskiden o da credential'la birlikte düşüyordu.
		"""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(
			session,
			provider=SEEDED_PROVIDER,
			credential_doc=_PlaceholderDoc(),
			extra_secret_values=["OTURUM_JETONU_777"],
			logger=_Recorder(records),
		)

		client.request("GET", "https://kargo.test/x", operation="track")

		# Guardrail korunuyor: `secret_values` argümanı hiç geçilmedi.
		self.assertNotIn("secret_values", records[0])
		self.assertIn("OTURUM_JETONU_777", records[0]["extra_secret_values"])

	def test_logger_called_once_per_attempt(self) -> None:
		"""Her deneme ayrı satır — retry görünürlüğü kaybolmasın."""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(500, b"hata")])
		client = _client(session, max_attempts=3, provider=SEEDED_PROVIDER, logger=_Recorder(records))

		with self.assertRaises(CarrierAPIError):
			client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		self.assertEqual([r["attempt"] for r in records], [1, 2, 3])
		self.assertTrue(all(r["is_retriable"] for r in records))
		self.assertTrue(all(not r["succeeded"] for r in records))

	def test_logger_exception_does_not_break_main_flow(self) -> None:
		"""Log yazıcısı patlarsa ana akış KIRILMAZ."""

		def exploding_logger(**_kwargs: Any) -> None:
			raise RuntimeError("log DocType'i yok")

		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session, provider=SEEDED_PROVIDER, logger=exploding_logger)

		response = client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		self.assertEqual(response.status_code, 200)

	def test_no_logger_is_a_noop(self) -> None:
		"""logger verilmezse hiçbir şey loglanmaz ve hiçbir şey patlamaz."""
		session = FakeSession([FakeResponse(200, b"ok")])
		client = _client(session)

		response = client.request("GET", "https://kargo.test/x", operation="track", idempotent=True)

		self.assertEqual(response.status_code, 200)

	def test_binary_response_is_not_decoded_into_log(self) -> None:
		"""Etiket PDF'i log alanına ham metin olarak yazılmaz (masking ile hizalı biçim)."""
		records: list[dict[str, Any]] = []
		session = FakeSession(
			[FakeResponse(200, b"%PDF-1.4\x00\x01binary", {"Content-Type": "application/pdf"})]
		)
		client = _client(session, provider=SEEDED_PROVIDER, logger=_Recorder(records))

		client.request("GET", "https://kargo.test/label", operation="label", idempotent=True)

		self.assertEqual(records[0]["response_body"], "<binary 16 bytes, application/pdf>")


# ---------------------------------------------------------------------------
# Uçtan uca: gerçek write_integration_log
# ---------------------------------------------------------------------------


class TestEndToEndIntegrationLog(unittest.TestCase):
	"""Sahte logger'ın YAKALAYAMADIĞI tek şey: satırın gerçekten yazılıp yazılmadığı.

	`carrier` bir `Logistics Provider` Link'i ve `reqd:1`; registry kodu
	(`aras`) gönderildiğinde kayıt LinkValidationError'da düşüyor ve iki kat
	`except` tarafından yutuluyordu. Bu test o zinciri uçtan uca kapatır.
	"""

	def setUp(self) -> None:
		self.created: list[str] = []
		self.addCleanup(self._cleanup)

	def _cleanup(self) -> None:
		for name in self.created:
			frappe.delete_doc(INTEGRATION_LOG_DOCTYPE, name, force=True, ignore_permissions=True)
		frappe.db.commit()

	def test_row_is_actually_written_with_a_valid_provider_link(self) -> None:
		marker = f"E2E-{uuid.uuid4().hex[:8]}"
		session = FakeSession([FakeResponse(200, marker.encode(), {"Content-Type": "text/plain"})])
		client = _client(
			session,
			carrier_code="aras",
			provider=SEEDED_PROVIDER,
			logger=write_integration_log,
		)

		client.request("GET", "https://kargo.test/track", operation="track")
		frappe.db.commit()

		rows = frappe.get_all(
			INTEGRATION_LOG_DOCTYPE,
			filters={"carrier": SEEDED_PROVIDER, "operation": "track"},
			fields=["name", "carrier", "succeeded", "http_status", "response_body"],
			order_by="creation desc",
			limit=5,
		)
		self.created.extend(row["name"] for row in rows)
		match = [row for row in rows if marker in (row.get("response_body") or "")]
		self.assertTrue(match, "Entegrasyon log satırı YAZILMADI (carrier Link'i doldu mu?)")
		self.assertEqual(match[0]["carrier"], SEEDED_PROVIDER)
		self.assertEqual(match[0]["http_status"], 200)
		self.assertEqual(match[0]["succeeded"], 1)


# ---------------------------------------------------------------------------
# Devre kesici köprüsü (gerçek Redis)
# ---------------------------------------------------------------------------


class TestCircuitBreakerBridge(_NoSleep):
	def setUp(self) -> None:
		super().setUp()
		self.carrier = f"CB-{uuid.uuid4().hex[:10]}"
		self.addCleanup(self._cleanup)

	def _cleanup(self) -> None:
		CarrierHttpClient(self.carrier).reset_circuit()

	def _make(self, session: FakeSession, **kwargs: Any) -> CarrierHttpClient:
		kwargs.setdefault("failure_threshold", 2)
		kwargs.setdefault("cooldown_sec", 60)
		kwargs.setdefault("allow_private_hosts", True)
		return CarrierHttpClient(self.carrier, session=session, circuit_breaker=True, **kwargs)

	def _expire_cooldown(self, client: CarrierHttpClient) -> None:
		"""Cooldown'un dolmasını gerçek zamanda BEKLEMEDEN simüle eder.

		`open` anahtarı silinir, `failures` eşiğin üstünde kalır → HALF_OPEN.
		Eskiden burada `time.sleep(1.3)` vardı; testi Redis'in saniyelik TTL
		çözünürlüğüne bağlıyor ve süiti yavaşlatıyordu.
		"""
		breaker = client.breaker
		frappe.cache.delete(breaker._key("open"), breaker._key("probe"), breaker._key("notice"))  # noqa: SLF001

	def test_opens_after_consecutive_failures_and_rejects_without_http_call(self) -> None:
		"""Eşik aşılınca sonraki çağrı YENİ HTTP İSTEĞİ YAPMADAN reddedilir."""
		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session)
		client.reset_circuit()

		for _i in range(2):
			with self.assertRaises(CarrierAPIError):
				client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertEqual(session.call_count, 2)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertEqual(session.call_count, 2, "Devre açıkken yeni HTTP isteği yapıldı!")
		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN")
		self.assertEqual(ctx.exception.attempts, 0)

	def test_half_open_lets_single_probe_through_and_closes_on_success(self) -> None:
		"""Cooldown sonrası tek deneme geçer; başarılıysa devre kapanır."""
		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session, failure_threshold=1)
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		self.assertEqual(session.call_count, 1)

		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN")
		self.assertEqual(session.call_count, 1)

		self._expire_cooldown(client)

		healthy = FakeSession([FakeResponse(200, b"ok")])
		probe_client = self._make(healthy, failure_threshold=1)
		self.assertEqual(
			probe_client.request("GET", "https://kargo.test/x", operation="track").status_code, 200
		)
		self.assertEqual(healthy.call_count, 1)

		# Devre kapandı: sonraki çağrı da geçmeli.
		self.assertEqual(
			probe_client.request("GET", "https://kargo.test/x", operation="track").status_code, 200
		)
		self.assertEqual(healthy.call_count, 2)

	def test_permanent_4xx_is_neutral_neither_opens_nor_resets(self) -> None:
		"""400 sayacı SIFIRLAMAZ: karışık trafikte devre hiç açılmıyordu."""
		session = FakeSession(
			[FakeResponse(503, b"down"), FakeResponse(400, b"gecersiz"), FakeResponse(503, b"down")]
		)
		client = self._make(session, failure_threshold=2)
		client.reset_circuit()

		for _i in range(3):
			with self.assertRaises(CarrierAPIError):
				client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertEqual(session.call_count, 3)

		# İki 503 sayacı eşiğe taşıdı; aradaki 400 onu sıfırlamamış olmalı.
		with self.assertRaises(CarrierAPIError) as ctx:
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN")
		self.assertEqual(session.call_count, 3)

	def test_only_4xx_traffic_never_opens_the_circuit(self) -> None:
		"""400 bizim isteğimizin hatası — sağlıklı entegrasyonu kilitlememeli."""
		session = FakeSession([FakeResponse(400, b"gecersiz alan")])
		client = self._make(session, failure_threshold=2)
		client.reset_circuit()

		for _i in range(4):
			with self.assertRaises(CarrierAPIError):
				client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertEqual(session.call_count, 4)

	def test_success_resets_failure_counter(self) -> None:
		"""Araya giren başarı sayacı sıfırlar — ardışıklık şartı."""
		session = FakeSession(
			[FakeResponse(503, b"down"), FakeResponse(200, b"ok"), FakeResponse(503, b"down")]
		)
		client = self._make(session, failure_threshold=2)
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		client.request("GET", "https://kargo.test/x", operation="track")
		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		# Sayaç sıfırlandığı için devre hâlâ kapalı: 4. çağrı transporta ulaşmalı.
		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		self.assertEqual(session.call_count, 4)

	def test_circuit_state_is_shared_across_client_instances(self) -> None:
		"""Durum Redis'te: farklı işçi/örnek aynı devreyi görür."""
		session_a = FakeSession([FakeResponse(503, b"down")])
		client_a = self._make(session_a, failure_threshold=1)
		client_a.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client_a.request("POST", "https://kargo.test/x", operation="create_shipment")

		session_b = FakeSession([FakeResponse(200, b"ok")])
		client_b = self._make(session_b, failure_threshold=1)
		with self.assertRaises(CarrierAPIError) as ctx:
			client_b.request("GET", "https://kargo.test/x", operation="track")

		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN")
		self.assertEqual(session_b.call_count, 0)

	def test_open_circuit_writes_only_one_log_row_per_cooldown(self) -> None:
		"""Devre açıkken her ret bir DB insert'i olurdu — kesilen yük log tablosuna kayardı."""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(
			session,
			failure_threshold=1,
			provider=SEEDED_PROVIDER,
			logger=_Recorder(records),
		)
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		for _i in range(5):
			with self.assertRaises(CarrierAPIError):
				client.request("POST", "https://kargo.test/x", operation="create_shipment")

		rejected = [r for r in records if r["error_code"] == "CIRCUIT_OPEN"]
		self.assertEqual(len(rejected), 1, f"Cooldown boyunca {len(rejected)} ret satırı yazıldı")

	# -- BULGU 3: yarı-açık probe kilidi ---------------------------------

	def _drive_to_half_open(self, **kwargs: Any) -> None:
		"""Devreyi HALF_OPEN'a getirir (1 hata + cooldown'u simüle et)."""
		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session, failure_threshold=1, **kwargs)
		client.reset_circuit()
		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		self._expire_cooldown(client)

	def test_a_4xx_probe_does_not_lock_the_circuit(self) -> None:
		"""ÖLÇÜLDÜ: probe 400 alınca devre HALF_OPEN'da kilitleniyordu.

		4xx taşıyıcının AYAKTA olduğunun kanıtıdır; sonraki SAĞLIKLI çağrının
		`CIRCUIT_OPEN` yemesi için hiçbir sebep yok. Kilit `failures` penceresi
		(300 sn) ya da `probe` TTL'i dolana kadar sürüyordu.
		"""
		self._drive_to_half_open()

		rejecting = FakeSession([FakeResponse(400, b"gecersiz")])
		probe_client = self._make(rejecting, failure_threshold=1)
		with self.assertRaises(CarrierAPIError) as ctx:
			probe_client.request("POST", "https://kargo.test/x", operation="create_shipment")
		self.assertEqual(ctx.exception.carrier_error_code, "HTTP_400", "Probe isteği hiç gitmedi")

		healthy = FakeSession([FakeResponse(200, b"ok")])
		next_client = self._make(healthy, failure_threshold=1)
		self.assertEqual(
			next_client.request("GET", "https://kargo.test/x", operation="track").status_code,
			200,
			"Sağlıklı çağrı CIRCUIT_OPEN yedi — devre 4xx probe ile kilitlendi",
		)
		self.assertEqual(healthy.call_count, 1)

	def test_a_blocked_url_probe_does_not_lock_the_circuit(self) -> None:
		"""AYNI SINIF: `_enter_circuit` probe'u URL kapısından ÖNCE alıyor.

		Kapı reddi devre kesiciye HİÇ işlenmez ama probe anahtarı harcanıyordu:
		tek bir hatalı `base_url` cooldown boyunca sağlıklı taşıyıcıyı kesiyordu.
		"""
		self._drive_to_half_open()

		blocked = FakeSession([FakeResponse(200, b"ok")])
		probe_client = self._make(blocked, failure_threshold=1, allow_private_hosts=False)
		with self.assertRaises(CarrierAPIError) as ctx:
			# DARALTILAN kapı reddi (`URL_HOST_BLOCKED`): devre kesiciye HİÇ
			# işlenmeyen tek dal, yani probe iadesinin ayrı bir kolu var.
			probe_client.request("GET", "https://10.0.0.1/x", operation="track")
		self.assertEqual(ctx.exception.carrier_error_code, hc.URL_BLOCKED_LOG_CODE)
		self.assertEqual(blocked.call_count, 0, "Kapı reddi transporta ulaştı")

		healthy = FakeSession([FakeResponse(200, b"ok")])
		next_client = self._make(healthy, failure_threshold=1)
		self.assertEqual(
			next_client.request("GET", "https://kargo.test/x", operation="track").status_code,
			200,
			"Kapı reddi probe'u yaktı — sağlıklı çağrı kesildi",
		)

	def test_a_failing_probe_still_reopens_the_circuit(self) -> None:
		"""Karşı kilit: gerçek arıza (503) probe'u HÂLÂ yakıp cooldown'u başlatmalı."""
		self._drive_to_half_open()

		down = FakeSession([FakeResponse(503, b"down")])
		probe_client = self._make(down, failure_threshold=1)
		with self.assertRaises(CarrierAPIError):
			probe_client.request("POST", "https://kargo.test/x", operation="create_shipment")

		healthy = FakeSession([FakeResponse(200, b"ok")])
		with self.assertRaises(CarrierAPIError) as ctx:
			self._make(healthy, failure_threshold=1).request("GET", "https://kargo.test/x", operation="track")
		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN")
		self.assertEqual(healthy.call_count, 0)

	# -- BULGU 5: ortam izolasyonu ---------------------------------------

	def test_sandbox_failures_do_not_open_the_production_circuit(self) -> None:
		"""ÖLÇÜLDÜ: sandbox'ta 2 hata → production istemcisi `CIRCUIT_OPEN` alıyordu."""
		sandbox_session = FakeSession([FakeResponse(503, b"down")])
		sandbox = self._make(sandbox_session, failure_threshold=2, environment="sandbox")
		sandbox.reset_circuit()

		for _i in range(2):
			with self.assertRaises(CarrierAPIError):
				sandbox.request("POST", "https://kargo.test/x", operation="create_shipment")

		with self.assertRaises(CarrierAPIError) as ctx:
			sandbox.request("POST", "https://kargo.test/x", operation="create_shipment")
		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN", "Sandbox devresi açılmadı")

		production_session = FakeSession([FakeResponse(200, b"ok")])
		production = self._make(production_session, failure_threshold=2, environment="production")
		self.assertEqual(
			production.request("GET", "https://kargo.test/x", operation="track").status_code,
			200,
			"Sandbox arızası CANLI gönderiyi kesti",
		)

	# -- BULGU 2: yazım farkı --------------------------------------------

	def test_case_variants_share_one_circuit_end_to_end(self) -> None:
		"""`ARAS` ve `aras` AYNI adapter'a çözülür — devre sayacı da tek olmalı."""
		upper_session = FakeSession([FakeResponse(503, b"down")])
		upper = CarrierHttpClient(
			self.carrier.upper(),
			session=upper_session,
			circuit_breaker=True,
			failure_threshold=2,
			cooldown_sec=60,
			allow_private_hosts=True,
		)
		upper.reset_circuit()
		with self.assertRaises(CarrierAPIError):
			upper.request("POST", "https://kargo.test/x", operation="create_shipment")

		lower_session = FakeSession([FakeResponse(503, b"down")])
		lower = self._make(lower_session, failure_threshold=2)
		with self.assertRaises(CarrierAPIError):
			lower.request("POST", "https://kargo.test/x", operation="create_shipment")

		blocked = FakeSession([FakeResponse(200, b"ok")])
		with self.assertRaises(CarrierAPIError) as ctx:
			self._make(blocked, failure_threshold=2).request("GET", "https://kargo.test/x", operation="track")
		self.assertEqual(ctx.exception.carrier_error_code, "CIRCUIT_OPEN", "Arıza sayacı bölündü")

	def test_client_normalises_the_carrier_code(self) -> None:
		client = CarrierHttpClient("  ArAs  ", circuit_breaker=False)
		self.assertEqual(client.carrier_code, "aras")
		self.assertEqual(client.breaker.carrier_code, "aras")

	def test_notice_is_not_wasted_when_logging_is_impossible(self) -> None:
		"""logger/provider yokken anahtar harcanıyordu — kimse yazamıyor, hak da yanıyordu."""
		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session, failure_threshold=1)  # logger YOK
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertTrue(client.breaker.claim_open_notice(), "Notice anahtarı boşuna harcandı")

	def test_failed_notice_log_returns_the_claim(self) -> None:
		"""Kazananın logu düşerse cooldown boyunca HİÇ satır kalmıyordu.

		YAZICI SÖZLEŞMEYE UYAR: `write_integration_log` **asla fırlatmaz**,
		başarısızlığı YALNIZ `None` dönüşüyle bildirir (bkz. `IntegrationLogWriter`
		docstring'i). Bu test eskiden `RuntimeError` fırlatan bir yazıcı
		kullanıyordu — yani sözleşmeyi İHLAL EDEN bir yazıcıya özgü davranışı
		kilitliyordu ve üretimdeki tek gerçek başarısızlık kanalını (dönüş değeri)
		hiç sınamıyordu. Ölçüldü: `_log` o kanalı okumadığı için `written` daima
		True dönüyor, `release_open_notice()` dalı ERİŞİLEMEZ kalıyordu.

		İstisna dalı KORUNUR — `test_failed_notice_log_returns_the_claim_on_exception`.
		"""
		calls: list[int] = []

		def failing_logger(**_kwargs: Any) -> str | None:
			calls.append(1)
			return None  # Sözleşme: yazılamadı.

		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session, failure_threshold=1, provider=SEEDED_PROVIDER, logger=failing_logger)
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertTrue(calls, "Yazıcı hiç çağrılmadı — test yanlış şeyi ölçüyor")
		self.assertTrue(client.breaker.claim_open_notice(), "Yazamayan kazanan anahtarı geri vermedi")

	def test_failed_notice_log_returns_the_claim_on_exception(self) -> None:
		"""SÖZLEŞME DIŞI (fırlatan) yazıcı da anahtarı geri verdirmeli.

		`write_integration_log` fırlatmayacağını taahhüt ediyor ama enjeksiyon
		noktası herhangi bir callable kabul ediyor; savunma dalı korunuyor.
		"""

		def exploding_logger(**_kwargs: Any) -> None:
			raise RuntimeError("log DocType'i yok")

		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session, failure_threshold=1, provider=SEEDED_PROVIDER, logger=exploding_logger)
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		with mock.patch("frappe.log_error"), self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertTrue(client.breaker.claim_open_notice(), "Yazamayan kazanan anahtarı geri vermedi")

	def test_successful_notice_log_keeps_the_claim(self) -> None:
		"""Karşı kilit: yazıcı BAŞARILI olduğunda anahtar geri VERİLMEMELİ.

		`_log` her zaman False dönseydi (dönüş değeri okunurken kutuplar
		ters çevrilirse) cooldown başına tek satır garantisi çökerdi.
		"""
		records: list[dict[str, Any]] = []
		session = FakeSession([FakeResponse(503, b"down")])
		client = self._make(session, failure_threshold=1, provider=SEEDED_PROVIDER, logger=_Recorder(records))
		client.reset_circuit()

		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")
		with self.assertRaises(CarrierAPIError):
			client.request("POST", "https://kargo.test/x", operation="create_shipment")

		self.assertFalse(client.breaker.claim_open_notice(), "Yazan kazanan anahtarı boşuna geri verdi")

	def test_log_returns_false_when_the_writer_reports_failure(self) -> None:
		"""BİRİM KİLİDİ: `_log`, yazıcının `None` dönüşünü OKUMALI.

		Mutasyon `return written is not None` → `return True` bu testi düşürür;
		eski kodda hiçbir test düşmüyordu.
		"""
		call = hc._Call(
			method="GET",
			url="https://kargo.test/x",
			operation="track",
			headers={},
			payload=None,
			params=None,
			timeout=(1.0, 1.0),
			policy=RetryPolicy(),
			classify=None,
			request_body=None,
		)
		written: list[dict[str, Any]] = []
		client = CarrierHttpClient(
			self.carrier, provider=SEEDED_PROVIDER, circuit_breaker=False, logger=lambda **_kw: None
		)
		self.assertFalse(client._log(call, succeeded=True), "None dönüşü 'yazıldı' sayıldı")  # noqa: SLF001

		client_ok = CarrierHttpClient(
			self.carrier, provider=SEEDED_PROVIDER, circuit_breaker=False, logger=_Recorder(written)
		)
		self.assertTrue(client_ok._log(call, succeeded=True), "Docname dönüşü 'yazılamadı' sayıldı")  # noqa: SLF001


# ---------------------------------------------------------------------------
# Yardımcı fonksiyonlar
# ---------------------------------------------------------------------------


class TestRetryAfterParsing(unittest.TestCase):
	def test_delta_seconds(self) -> None:
		self.assertEqual(hc._parse_retry_after("12"), 12.0)

	def test_missing_header(self) -> None:
		self.assertIsNone(hc._parse_retry_after(None))
		self.assertIsNone(hc._parse_retry_after(""))

	def test_garbage_header(self) -> None:
		self.assertIsNone(hc._parse_retry_after("yakinda"))

	def test_http_date_in_the_past_is_clamped_to_zero(self) -> None:
		self.assertEqual(hc._parse_retry_after("Wed, 21 Oct 2015 07:28:00 GMT"), 0.0)


# ---------------------------------------------------------------------------
# Sır toplama — `Password` fieldtype'ı (3. tur güvenlik denetimi)
# ---------------------------------------------------------------------------


class TestSecretCollectionUnit(unittest.TestCase):
	"""`collect_secret_values` — Frappe DB'si gerekmeyen davranışlar."""

	def test_plain_mapping_yields_plaintext(self) -> None:
		values = collect_secret_values({"api_key": "PLAINTEXT_KEY_123456"}, ["OTURUM_777"])

		self.assertIn("PLAINTEXT_KEY_123456", values)
		self.assertIn("OTURUM_777", values)

	def test_placeholder_never_enters_the_set(self) -> None:
		"""`'*' * 19` geçerli bir redaksiyon varyantı olarak kullanılıyordu.

		Sonuç sessiz VERİ BOZULMASI: gövdedeki her 19 yıldızlık dizi `***` ile
		değiştiriliyordu. Yer tutucu artık hiçbir koşulda kümeye girmez.

		Yer tutucu ancak `get_password()` OKUYABİLEN bir dokümanda yer
		tutucudur — bkz. `test_all_star_value_in_a_plain_dict_is_a_real_secret`.
		"""
		values = collect_secret_values(_PlaceholderDoc())

		self.assertIsNone(values, "Yer tutucu 'çözülemedi' olarak raporlanmalı")

	def test_all_star_value_in_a_plain_dict_is_a_real_secret(self) -> None:
		"""Tamamı yıldız olan MEŞRU bir sır yer tutucu sanılıyordu.

		Düz bir `dict`'te `__Auth` dolaylaması YOKTUR: değer neyse odur. Eski
		kural (`set(value) == {'*'}`) tek başına karar veriyor ve o istemci için
		değer-tabanlı redaksiyonu TAMAMEN kapatıyordu (fail-closed ve gürültülü,
		sızıntı değil — ama birincil savunma düşüyordu).
		"""
		values = collect_secret_values({"api_key": "*" * 19})

		self.assertEqual(values, frozenset({"*" * 19}))

	def test_unresolved_returns_none_not_a_half_set(self) -> None:
		"""Yarım küme guardrail'i SUSTURUR — bu yüzden `None` döner.

		Küme BOŞ OLMADIĞI için `log.py`'nin 'secret_values unutuldu' uyarısı hiç
		tetiklenmiyordu; arızayı yakalayacak TEK guardrail susturulmuştu.
		"""
		values = collect_secret_values(_PlaceholderDoc(extra={"api_secret": "GERCEK_SIR_123456"}))

		self.assertIsNone(values)

	def test_non_string_secret_fields_are_not_treated_as_absent(self) -> None:
		"""`str` olmayan sır alanı "alan YOK" sayılıyordu — İKİ guardrail birden sustu.

		ÖLÇÜLDÜ: `{'api_key': b'REALKEY123456'}` ve `{'api_key': 123456789}`
		için dönüş UYARISIZ `frozenset()`'ti. Sözleşmede `frozenset()` "sır YOK
		— DOĞRULANMIŞ" demek; `http_client._log` o kümeyi AÇIKÇA geçiyor ve
		`log.py`'nin "unutuldu" nöbetçisi de tetiklenmiyordu. `credential_doc`
		sözleşmesi `dict[str, Any]` ve `masking.secret_texts` bu türleri ZATEN
		destekliyordu — toplayıcı sessizce atıyordu.
		"""
		binary = collect_secret_values({"api_key": b"X" * 16})
		numeric = collect_secret_values({"api_key": 123456789})

		self.assertNotEqual(binary, frozenset(), "bytes sır sessizce atıldı")
		self.assertNotEqual(numeric, frozenset(), "int sır sessizce atıldı")
		self.assertIn("X" * 16, binary)
		self.assertIn("123456789", numeric)

	def test_unsupported_secret_type_is_loud_not_silent(self) -> None:
		"""Sessiz ÜÇÜNCÜ YOL olmamalı: dönüştürülemeyen tür `None` üretir."""
		self.assertIsNone(collect_secret_values({"api_key": {"nested": "value"}}))

	def test_document_like_source_uses_get_password(self) -> None:
		"""`Document` benzeri girdide plaintext `get_password` ile gelir."""

		class _FakeDoc:
			def get(self, field: str) -> Any:
				return "*" * 19 if field == "api_key" else None

			def get_password(self, field: str, raise_exception: bool = True) -> Any:
				return "GERCEK_APIKEY_123456" if field == "api_key" else None

		values = collect_secret_values(_FakeDoc())

		self.assertEqual(values, frozenset({"GERCEK_APIKEY_123456"}))

	def test_empty_source_is_a_verified_empty_set(self) -> None:
		"""'Sır yok' ile 'okuyamadım' AYRI: boş doküman `frozenset()` döner."""
		self.assertEqual(collect_secret_values({}), frozenset())


class TestSecretCollectionEndToEnd(FrappeTestCase):
	"""Dört katmanı birden kilitler: DocType → toplayıcı → yazıcı → DB satırı."""

	def setUp(self) -> None:
		self.plaintext = "REALSECRETKEY123456"
		self.account = frappe.new_doc("Carrier Account")
		self.account.account_name = f"Secret Collect {uuid.uuid4().hex[:6]}"
		self.account.carrier = SEEDED_PROVIDER
		self.account.environment = "Sandbox"
		self.account.is_active = 0
		self.account.api_key = self.plaintext
		self.account.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(self._cleanup)

	def _cleanup(self) -> None:
		frappe.db.delete(INTEGRATION_LOG_DOCTYPE, {"carrier": SEEDED_PROVIDER})
		frappe.db.delete("Carrier Account", {"name": self.account.name})
		frappe.db.commit()

	def test_password_field_is_stored_as_a_placeholder(self) -> None:
		"""Arızanın KÖKÜ: Frappe sütuna `'*' * len(değer)` yazar.

		Bu assert olmadan diğer testler 'neden' sorusunu cevaplamıyor.
		"""
		fresh = frappe.get_doc("Carrier Account", self.account.name)

		self.assertNotEqual(fresh.api_key, self.plaintext)
		self.assertEqual(set(fresh.api_key), {"*"})

	def test_real_carrier_account_yields_plaintext(self) -> None:
		"""ÖLÇÜLDÜ: düz `Mapping.get` ile küme `{'*******************'}` oluyordu."""
		fresh = frappe.get_doc("Carrier Account", self.account.name)

		values = collect_secret_values(fresh)

		self.assertIsNotNone(values, "Gerçek doküman 'çözülemedi' saymamalı")
		self.assertIn(self.plaintext, values)

	def test_unknown_xml_tag_is_redacted_in_the_stored_row(self) -> None:
		"""Uçtan uca: bilinmeyen şema + gerçek credential → DB satırında MASK.

		`masking.py`'nin kendi docstring'indeki `<Xyz42>SECRET</Xyz42>` örneği
		kanonik yolda HAM loglanıyordu: `_collect_secret_values` `Password`
		alanlarına kör olduğu için birincil savunma no-op'tu.
		"""
		fresh = frappe.get_doc("Carrier Account", self.account.name)
		session = FakeSession([FakeResponse(200, f"<Xyz42>{self.plaintext}</Xyz42>".encode())])
		client = _client(
			session,
			provider=SEEDED_PROVIDER,
			credential_doc=fresh,
			logger=write_integration_log,
		)

		client.request("GET", "https://kargo.test/x", operation="track")

		row = frappe.get_all(
			INTEGRATION_LOG_DOCTYPE,
			filters={"carrier": SEEDED_PROVIDER},
			fields=["name", "response_body"],
			order_by="creation desc",
			limit=1,
		)
		self.assertTrue(row, "Log satırı yazılmadı")
		self.assertNotIn(self.plaintext, row[0]["response_body"] or "")
		self.assertIn("***", row[0]["response_body"] or "")


class TestLoggerIsTypeBound(unittest.TestCase):
	"""Protocol yazılmıştı ama bağımlılık ona ÇEVRİLMEMİŞTİ (2. turdan yarım kalan)."""

	def test_logger_parameter_is_annotated_with_the_protocol(self) -> None:
		annotation = inspect.signature(CarrierHttpClient.__init__).parameters["logger"].annotation

		self.assertEqual(annotation, "IntegrationLogWriter | None")

	def test_write_integration_log_satisfies_the_protocol(self) -> None:
		"""Protocol'ün tek referansı bir smoke testiydi; enjeksiyon noktası bağlanmalı."""
		protocol_params = set(inspect.signature(IntegrationLogWriter.__call__).parameters) - {"self"}
		writer_params = set(inspect.signature(write_integration_log).parameters)

		self.assertEqual(protocol_params, writer_params)


if __name__ == "__main__":
	unittest.main()
