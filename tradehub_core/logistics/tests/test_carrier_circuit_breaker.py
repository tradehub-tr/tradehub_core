# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-110: `CarrierCircuitBreaker` birim testleri (gerçek Redis).

Devre kesici bu dilime kadar TESTSİZDİ; oysa iki tuzağı ÖLÇÜLEREK bulundu ve
ikisi de sessizdi:

1. **Çifte ön ek.** Frappe `RedisWrapper.exists()` kendi `make_key`'ini bir kez
   DAHA uyguluyor. Ön-ekli anahtarımız çifte ön ek alıp hep 0 dönüyor, yani
   devre HİÇ açılmıyordu. `get/set/incr/expire/delete` override edilmemiş.
2. **Sessiz fail-open.** Yutulan hata kümesi `AttributeError` içerdiği sürece
   try bloğundaki bir yazım hatası devre kesiciyi kalıcı ve GÖRÜNMEZ şekilde
   devre dışı bırakıyordu.

Her test kendi rastgele anahtarıyla izole çalışır.
"""

from __future__ import annotations

import unittest
import uuid
from typing import Any
from unittest import mock

import frappe
from redis.exceptions import ConnectionError as RedisConnectionError

from tradehub_core.logistics.resilience import CarrierCircuitBreaker, CircuitState, Outcome
from tradehub_core.logistics.resilience.circuit_breaker import (
	CIRCUIT_KEY_PREFIX,
	_coerce_counter,
	_sanitize_key_code,
)


class _BreakerCase(unittest.TestCase):
	def setUp(self) -> None:
		self.code = f"CBU-{uuid.uuid4().hex[:10]}"
		self.addCleanup(self._cleanup)

	def _cleanup(self) -> None:
		CarrierCircuitBreaker(self.code).reset()

	def _breaker(self, **kwargs: Any) -> CarrierCircuitBreaker:
		kwargs.setdefault("failure_threshold", 3)
		kwargs.setdefault("cooldown_sec", 30)
		return CarrierCircuitBreaker(self.code, **kwargs)

	def _expire_open_key(self, breaker: CarrierCircuitBreaker) -> None:
		"""Cooldown'un dolmasını gerçek zamanda beklemeden simüle eder."""
		frappe.cache.delete(breaker._key("open"), breaker._key("probe"))  # noqa: SLF001


# ---------------------------------------------------------------------------
# Anahtar uzayı
# ---------------------------------------------------------------------------


class TestKeyNamespace(_BreakerCase):
	def test_prefix_is_applied_exactly_once(self) -> None:
		"""Çifte ön ek devreyi sessizce işlevsiz bırakıyordu — regresyon kilidi."""
		breaker = self._breaker()
		key = breaker._key("open")  # noqa: SLF001
		expected = frappe.cache.make_key(f"{CIRCUIT_KEY_PREFIX}{_sanitize_key_code(self.code)}:open")

		self.assertEqual(key, expected)
		self.assertNotEqual(key, frappe.cache.make_key(key), "make_key idempotent değil — kontrol geçerli")

		frappe.cache.set(key, b"1", ex=30)
		self.addCleanup(frappe.cache.delete, key)
		self.assertIsNotNone(frappe.cache.get(key), "Kendi ön ekimizle yazılan anahtar okunamadı")
		# TUZAĞIN KENDİSİ: exists() make_key'i bir kez daha uyguladığı için 0 döner.
		self.assertFalse(frappe.cache.exists(key), "RedisWrapper.exists() artık çifte ön ek uygulamıyor")

	def test_unsafe_carrier_code_is_sanitised(self) -> None:
		"""Doğrulanmamış kod anahtar uzayını kirletir ve komşu devrelerle çakışır."""
		breaker = CarrierCircuitBreaker("aras kargo:*/prod")
		key = breaker._key("open")  # noqa: SLF001
		text = key.decode() if isinstance(key, bytes) else str(key)

		self.assertIn("aras_kargo___prod", text)
		self.assertNotIn(" ", text.rsplit("circuit:", 1)[-1])
		self.assertNotIn("*", text)

	def test_long_carrier_code_is_truncated_but_stays_unique(self) -> None:
		breaker = CarrierCircuitBreaker("x" * 500)
		key = breaker._key("open")  # noqa: SLF001
		text = key.decode() if isinstance(key, bytes) else str(key)
		self.assertIn("x" * 32 + "-", text)
		self.assertNotIn("x" * 33, text)
		# Kırpma KAYIPSIZ olmalı: 32 karakterden sonrası farklı olan iki kod
		# eskiden aynı anahtara düşüyordu.
		self.assertNotEqual(
			_sanitize_key_code("x" * 500),
			_sanitize_key_code("x" * 499),
			"Uzun kodlar hâlâ çakışıyor",
		)

	def test_sanitised_codes_do_not_collide(self) -> None:
		"""KANITLANMIŞTI: `a:b`'ye 2 hata, `a_b`'nin devresini de açıyordu.

		Yani BİR taşıyıcının çökmesi BAŞKA bir taşıyıcının gönderilerini
		durduruyordu — kayıplı `sub()` altı ayrı kodu tek anahtara indiriyordu.
		"""
		codes = ("a:b", "a_b", "a b", "a.b", "a/b", "a*b")
		keys = {_sanitize_key_code(code) for code in codes}

		self.assertEqual(len(keys), len(codes), f"Anahtar çakışması sürüyor: {sorted(keys)}")
		for code in codes:
			self.assertTrue(_sanitize_key_code(code).startswith("a_b-"), "Okunabilir önek kayboldu")

	def test_collision_no_longer_leaks_across_circuits(self) -> None:
		"""Uçtan uca: `a:b` devresini açmak `a_b`'yi ETKİLEMEMELİ."""
		suffix = uuid.uuid4().hex[:8]
		noisy = CarrierCircuitBreaker(f"a:b-{suffix}", failure_threshold=1, cooldown_sec=30)
		quiet = CarrierCircuitBreaker(f"a_b-{suffix}", failure_threshold=1, cooldown_sec=30)
		self.addCleanup(noisy.reset)
		self.addCleanup(quiet.reset)
		noisy.reset()
		quiet.reset()

		noisy.record_failure()

		self.assertIs(noisy.state(), CircuitState.OPEN)
		self.assertIs(quiet.state(), CircuitState.CLOSED, "Komşu taşıyıcının devresi açıldı")


# ---------------------------------------------------------------------------
# Durum geçişleri
# ---------------------------------------------------------------------------


class TestStateTransitions(_BreakerCase):
	def test_starts_closed(self) -> None:
		self.assertIs(self._breaker().state(), CircuitState.CLOSED)

	def test_opens_exactly_at_threshold(self) -> None:
		breaker = self._breaker(failure_threshold=3)
		breaker.reset()

		breaker.record_failure()
		breaker.record_failure()
		self.assertIs(breaker.state(), CircuitState.CLOSED, "Eşiğin altında devre açılmamalı")

		breaker.record_failure()
		self.assertIs(breaker.state(), CircuitState.OPEN)

	def test_cooldown_expiry_moves_to_half_open(self) -> None:
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()
		breaker.record_failure()
		self.assertIs(breaker.state(), CircuitState.OPEN)

		self._expire_open_key(breaker)
		self.assertIs(breaker.state(), CircuitState.HALF_OPEN)

	def test_only_one_probe_is_granted_in_half_open(self) -> None:
		"""Atomik olmasa cooldown biter bitmez tüm işçiler çöken firmayı yere serer."""
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()
		breaker.record_failure()
		self._expire_open_key(breaker)

		self.assertTrue(breaker.acquire_probe())
		self.assertFalse(breaker.acquire_probe())
		self.assertFalse(CarrierCircuitBreaker(self.code).acquire_probe(), "Başka işçi de probe aldı")

	def test_failed_probe_reopens_the_circuit(self) -> None:
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()
		breaker.record_failure()
		self._expire_open_key(breaker)
		breaker.acquire_probe()

		breaker.record_failure(is_probe=True)

		self.assertIs(breaker.state(), CircuitState.OPEN)

	def test_success_closes_the_circuit(self) -> None:
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()
		breaker.record_failure()

		breaker.record_success()

		self.assertIs(breaker.state(), CircuitState.CLOSED)

	def test_state_is_shared_across_instances(self) -> None:
		"""Süreç-içi sayaç işe yaramaz: gunicorn + N RQ worker."""
		self._breaker(failure_threshold=1).record_failure()
		self.assertIs(self._breaker(failure_threshold=1).state(), CircuitState.OPEN)


# ---------------------------------------------------------------------------
# Outcome sözleşmesi
# ---------------------------------------------------------------------------


class TestOutcomeRecording(_BreakerCase):
	def test_neutral_neither_increments_nor_resets(self) -> None:
		"""Kalıcı 4xx'i başarı saymak karışık trafikte devreyi HİÇ açtırmıyordu."""
		breaker = self._breaker(failure_threshold=2)
		breaker.reset()

		breaker.record(Outcome.UNAVAILABLE)
		breaker.record(Outcome.NEUTRAL)
		breaker.record(Outcome.NEUTRAL)
		self.assertIs(breaker.state(), CircuitState.CLOSED, "NEUTRAL sayacı artırdı")

		breaker.record(Outcome.UNAVAILABLE)
		self.assertIs(breaker.state(), CircuitState.OPEN, "NEUTRAL sayacı sıfırladı")

	def test_healthy_resets(self) -> None:
		breaker = self._breaker(failure_threshold=2)
		breaker.reset()
		breaker.record(Outcome.UNAVAILABLE)
		breaker.record(Outcome.HEALTHY)
		breaker.record(Outcome.UNAVAILABLE)

		self.assertIs(breaker.state(), CircuitState.CLOSED)

	def test_record_neutral_is_an_explicit_noop(self) -> None:
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()
		breaker.record_neutral()
		self.assertIs(breaker.state(), CircuitState.CLOSED)


# ---------------------------------------------------------------------------
# Sayaç TTL'i
# ---------------------------------------------------------------------------


class TestFailureCounterTtl(_BreakerCase):
	def test_counter_always_carries_a_ttl(self) -> None:
		"""`incr` + ayrı `expire` arasında süreç ölürse anahtar TTL'SİZ kalırdı."""
		breaker = self._breaker(failure_threshold=5, cooldown_sec=30, failure_window_sec=120)
		breaker.reset()
		breaker.record_failure()

		ttl = frappe.cache.ttl(breaker._key("failures"))  # noqa: SLF001
		self.assertGreater(ttl, 0, "Hata sayacı TTL'siz — bir daha asla sıfırlanmaz")
		self.assertLessEqual(ttl, 120)

	def test_window_is_fixed_not_a_sliding_idle_window(self) -> None:
		"""Docstring "saatler arayla gelen 5 münferit hata devreyi açmamalı" diyor.

		TTL her artışta TAZELENİYORDU (ölçüldü: window=17, 1. hata ttl=17,
		1 sn sonra 2. hata yine ttl=17). Bu SABİT pencere değil, KAYAN bir
		boşta-kalma penceresidir: 4 dakikada bir gelen hatalar devreyi sonunda
		açardı. TTL artık yalnız anahtar YENİYKEN kurulur.
		"""
		breaker = self._breaker(failure_threshold=5, cooldown_sec=30, failure_window_sec=120)
		breaker.reset()
		key = breaker._key("failures")  # noqa: SLF001

		breaker.record_failure()
		first = frappe.cache.ttl(key)
		frappe.cache.expire(key, 60)  # Pencerenin ilerlemesini gerçek zamanda beklemeden simüle et.
		breaker.record_failure()
		second = frappe.cache.ttl(key)

		self.assertGreater(first, 0)
		self.assertLessEqual(second, 60, f"TTL tazelendi ({first} → {second}) — pencere kayıyor")
		self.assertEqual(_coerce_counter(frappe.cache.get(key)), 2, "Sayaç sıfırlandı")

	def test_corrupt_counter_value_is_treated_as_zero(self) -> None:
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()
		frappe.cache.set(breaker._key("failures"), b"bozuk", ex=30)  # noqa: SLF001

		self.assertIs(breaker.state(), CircuitState.CLOSED)


# ---------------------------------------------------------------------------
# Devre-açık log kısması
# ---------------------------------------------------------------------------


class TestOpenNotice(_BreakerCase):
	def test_notice_is_claimed_once_per_cooldown(self) -> None:
		breaker = self._breaker(failure_threshold=1)
		breaker.reset()

		self.assertTrue(breaker.claim_open_notice())
		self.assertFalse(breaker.claim_open_notice())
		self.assertFalse(CarrierCircuitBreaker(self.code, cooldown_sec=30).claim_open_notice())

	def test_reset_clears_the_notice(self) -> None:
		breaker = self._breaker()
		breaker.claim_open_notice()
		breaker.reset()
		self.assertTrue(breaker.claim_open_notice())

	def test_release_gives_the_claim_back(self) -> None:
		"""Kazananın logu düşerse cooldown boyunca HİÇ satır kalmıyordu."""
		breaker = self._breaker()
		breaker.reset()

		self.assertTrue(breaker.claim_open_notice())
		breaker.release_open_notice()

		self.assertTrue(breaker.claim_open_notice(), "Hak geri verilmedi — cooldown boyunca satır yok")

	def test_release_is_a_noop_when_disabled(self) -> None:
		breaker = self._breaker(enabled=False)
		with mock.patch("frappe.cache", _ExplodingCache()):
			breaker.release_open_notice()


# ---------------------------------------------------------------------------
# Arıza davranışı
# ---------------------------------------------------------------------------


class _ExplodingCache:
	"""Her çağrıda Redis bağlantı hatası veren sahte cache."""

	def __getattr__(self, _name: str) -> Any:
		def _boom(*_args: Any, **_kwargs: Any) -> Any:
			raise RedisConnectionError("redis erişilemiyor")

		return _boom


class TestCacheFaultBehaviour(_BreakerCase):
	def test_cache_fault_fails_open_and_is_reported(self) -> None:
		"""Fail-open evet, SESSİZ fail-open hayır."""
		breaker = self._breaker()
		with (
			mock.patch("frappe.cache", _ExplodingCache()),
			mock.patch("tradehub_core.logistics.resilience.fault_report._LAST_WARNING", {}),
			mock.patch("frappe.log_error") as log_error,
		):
			self.assertIs(breaker.state(), CircuitState.CLOSED)
			breaker.record_failure()
			breaker.reset()

		self.assertTrue(log_error.called, "Yutulan cache arızası hiçbir yere raporlanmadı")

	def test_repeated_faults_are_throttled(self) -> None:
		"""Redis çökünce saniyede yüzlerce Error Log satırı arızayı teşhis edilemez yapardı."""
		breaker = self._breaker()
		with (
			mock.patch("frappe.cache", _ExplodingCache()),
			mock.patch("tradehub_core.logistics.resilience.fault_report._LAST_WARNING", {}),
			mock.patch("frappe.log_error") as log_error,
		):
			for _i in range(20):
				breaker.state()

		self.assertEqual(log_error.call_count, 1, "Kısma çalışmadı")

	def test_socket_level_faults_also_fail_open(self) -> None:
		"""`OSError` devre kesiciden KAÇIYORDU: `state()` → `request()` → 500.

		Belgelenmiş fail-open değişmezi kırılıyor ve gönderi akışı DURUYORDU;
		`ConnectionResetError` bir altyapı arızasıdır, programlama hatası değil.
		"""

		class _SocketFaultCache:
			def make_key(self, key: str) -> str:
				return key

			def get(self, *_args: Any, **_kwargs: Any) -> Any:
				raise ConnectionResetError(104, "Connection reset by peer")

			def set(self, *_args: Any, **_kwargs: Any) -> Any:
				raise OSError("broken pipe")

			def delete(self, *_args: Any, **_kwargs: Any) -> Any:
				raise OSError("broken pipe")

			def pipeline(self, *_args: Any, **_kwargs: Any) -> Any:
				raise OSError("broken pipe")

		breaker = self._breaker()
		with (
			mock.patch("frappe.cache", _SocketFaultCache()),
			mock.patch("tradehub_core.logistics.resilience.fault_report._LAST_WARNING", {}),
			mock.patch("frappe.log_error") as log_error,
		):
			self.assertIs(breaker.state(), CircuitState.CLOSED)
			breaker.record_failure()
			breaker.reset()
			self.assertTrue(breaker.acquire_probe())
			self.assertTrue(breaker.claim_open_notice())
			breaker.release_open_notice()

		self.assertTrue(log_error.called, "Yutulan soket arızası raporlanmadı")

	def test_programming_errors_are_not_swallowed(self) -> None:
		"""`AttributeError`/`TypeError` cache arızası değil, BİZİM hatamızdır."""

		class _BadCache:
			def get(self, *_args: Any, **_kwargs: Any) -> Any:
				raise AttributeError("yazım hatası")

			def make_key(self, key: str) -> str:
				return key

		with mock.patch("frappe.cache", _BadCache()), self.assertRaises(AttributeError):
			self._breaker().state()


# ---------------------------------------------------------------------------
# enabled kapısı
# ---------------------------------------------------------------------------


class TestDisabledBreaker(_BreakerCase):
	def test_every_method_is_a_noop_when_disabled(self) -> None:
		"""Docstring "False ise tüm metotlar no-op" diyordu; iki metot kapıyı taşımıyordu."""
		breaker = self._breaker(enabled=False, failure_threshold=1)

		with mock.patch("frappe.cache", _ExplodingCache()):
			self.assertIs(breaker.state(), CircuitState.CLOSED)
			self.assertFalse(breaker.acquire_probe())
			breaker.record_failure()
			breaker.record_success()
			breaker.record(Outcome.UNAVAILABLE)
			breaker.reset()

	def test_disabled_breaker_does_not_touch_shared_state(self) -> None:
		enabled = self._breaker(failure_threshold=1)
		enabled.reset()
		enabled.record_failure()

		disabled = self._breaker(failure_threshold=1, enabled=False)
		disabled.reset()  # kapı yoksa paylaşılan durumu SİLERDİ

		self.assertIs(enabled.state(), CircuitState.OPEN)


if __name__ == "__main__":
	unittest.main()
