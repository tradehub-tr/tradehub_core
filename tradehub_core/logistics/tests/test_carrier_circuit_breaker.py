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

from tradehub_core.logistics.adapters.registry import normalize_carrier_code
from tradehub_core.logistics.resilience import CarrierCircuitBreaker, CircuitState, Outcome, fault_report
from tradehub_core.logistics.resilience.circuit_breaker import (
	CIRCUIT_KEY_PREFIX,
	_coerce_counter,
	_key_segment,
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
		expected = frappe.cache.make_key(
			f"{CIRCUIT_KEY_PREFIX}{_sanitize_key_code(self.code)}:{_key_segment('production')}:open"
		)

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

	# -- BULGU 2: yazım farkı devreyi bölüyordu ---------------------------

	def test_case_and_whitespace_variants_share_one_circuit(self) -> None:
		"""ÖLÇÜLDÜ: `ARAS` ile `aras` AYRI devre anahtarı alıyordu.

		`registry.get_adapter` ikisini de AYNI adapter'a çözerken devre kesici
		ayrı sayaç tutuyor, arıza sayacı bölünüyor ve eşik hiç dolmuyordu —
		çöken taşıyıcıya karşı devre HİÇ AÇILMIYORDU. `strip()` yalnız okunabilir
		öneke uygulanıyor, sha256 HAM dizeden alınıyordu:
			'ARAS'   -> ARAS-5d6f8c3b533da979
			'aras'   -> aras-91c067132b137529
			' aras ' -> aras-904d2d4d1225168e
		"""
		self.assertEqual(
			CarrierCircuitBreaker("ARAS")._key("x"),  # noqa: SLF001
			CarrierCircuitBreaker("aras")._key("x"),  # noqa: SLF001
		)
		self.assertEqual(
			CarrierCircuitBreaker(" ArAs ")._key("x"),  # noqa: SLF001
			CarrierCircuitBreaker("aras")._key("x"),  # noqa: SLF001
		)

	def test_normalisation_does_not_weaken_collision_protection(self) -> None:
		"""Normalizasyon `strip().lower()`'dan İBARET — `a:b` ile `a_b` AYRI kalmalı."""
		self.assertNotEqual(
			CarrierCircuitBreaker("a:b")._key("x"),  # noqa: SLF001
			CarrierCircuitBreaker("a_b")._key("x"),  # noqa: SLF001
		)

	def test_key_normalisation_comes_from_the_registry(self) -> None:
		"""TEK OTORİTE: iki katman ayrı normalizasyon uygularsa yeniden ayrışırlar."""
		for code in ("ARAS", " Yurtici ", "MnG-KaRgO"):
			self.assertEqual(
				CarrierCircuitBreaker(code)._key("x"),  # noqa: SLF001
				CarrierCircuitBreaker(normalize_carrier_code(code))._key("x"),  # noqa: SLF001
				f"{code!r} registry normalizasyonuyla aynı anahtara düşmüyor",
			)
			self.assertEqual(CarrierCircuitBreaker(code).carrier_code, normalize_carrier_code(code))

	def test_case_variants_share_one_failure_counter_end_to_end(self) -> None:
		"""Uçtan uca: iki yazımdan gelen hatalar TEK sayaçta toplanıp devreyi açar."""
		suffix = uuid.uuid4().hex[:8]
		upper = CarrierCircuitBreaker(f"ARAS-{suffix}", failure_threshold=2, cooldown_sec=30)
		lower = CarrierCircuitBreaker(f"aras-{suffix}", failure_threshold=2, cooldown_sec=30)
		self.addCleanup(lower.reset)
		lower.reset()

		upper.record_failure()
		lower.record_failure()

		self.assertIs(lower.state(), CircuitState.OPEN, "Sayaç hâlâ bölünüyor — eşik dolmadı")
		self.assertIs(upper.state(), CircuitState.OPEN)

	# -- BULGU 5: ortam anahtarda -----------------------------------------

	def test_environment_is_part_of_the_key(self) -> None:
		"""ÖLÇÜLDÜ: sandbox'ta 2 hata → production istemcisi `CIRCUIT_OPEN` alıyordu."""
		self.assertNotEqual(
			CarrierCircuitBreaker(self.code, environment="sandbox")._key("x"),  # noqa: SLF001
			CarrierCircuitBreaker(self.code, environment="production")._key("x"),  # noqa: SLF001
		)

	def test_sandbox_failures_do_not_open_the_production_circuit(self) -> None:
		sandbox = CarrierCircuitBreaker(
			self.code, environment="sandbox", failure_threshold=2, cooldown_sec=30
		)
		production = CarrierCircuitBreaker(
			self.code, environment="production", failure_threshold=2, cooldown_sec=30
		)
		self.addCleanup(sandbox.reset)
		sandbox.reset()
		production.reset()

		sandbox.record_failure()
		sandbox.record_failure()

		self.assertIs(sandbox.state(), CircuitState.OPEN)
		self.assertIs(production.state(), CircuitState.CLOSED, "Sandbox arızası canlıyı kesti")

	def test_environment_is_normalised_like_the_carrier_code(self) -> None:
		self.assertEqual(
			CarrierCircuitBreaker(self.code, environment=" SandBox ")._key("x"),  # noqa: SLF001
			CarrierCircuitBreaker(self.code, environment="sandbox")._key("x"),  # noqa: SLF001
		)
		self.assertEqual(CarrierCircuitBreaker(self.code, environment="").environment, "production")

	def test_key_segments_cannot_be_confused_across_the_separator(self) -> None:
		"""Her segment KENDİ digest'ini taşır: `a` + `b:c` ile `a:b` + `c` ayrışır."""
		self.assertNotEqual(
			CarrierCircuitBreaker("a", environment="b:c")._key("x"),  # noqa: SLF001
			CarrierCircuitBreaker("a:b", environment="c")._key("x"),  # noqa: SLF001
		)


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
# Yarı-açık probe kilidi (BULGU 3)
# ---------------------------------------------------------------------------


class TestHalfOpenProbeRelease(_BreakerCase):
	"""ÖLÇÜLDÜ: probe HTTP 400 (NEUTRAL) alınca devre HALF_OPEN'da KİLİTLENİYORDU.

	Anahtar geri verilmiyor, sonraki SAĞLIKLI çağrı `CIRCUIT_OPEN` yiyor ve kilit
	`probe` anahtarının TTL'i (= cooldown) dolana kadar sürüyordu. Oysa 4xx
	taşıyıcının AYAKTA olduğunun kanıtıdır.
	"""

	def _half_open(self, **kwargs: Any) -> CarrierCircuitBreaker:
		breaker = self._breaker(failure_threshold=1, **kwargs)
		breaker.reset()
		breaker.record_failure()
		self._expire_open_key(breaker)
		return breaker

	def test_neutral_probe_gives_the_probe_key_back(self) -> None:
		breaker = self._half_open()
		self.assertTrue(breaker.acquire_probe())

		breaker.record(Outcome.NEUTRAL, is_probe=True)

		self.assertIs(breaker.state(), CircuitState.HALF_OPEN, "NEUTRAL devre DURUMUNU değiştirdi")
		self.assertTrue(breaker.acquire_probe(), "Probe anahtarı geri verilmedi — devre kilitlendi")

	def test_neutral_probe_does_not_touch_the_failure_counter(self) -> None:
		"""DEĞİŞMEZ: NEUTRAL sayacı ne ARTIRIR ne SIFIRLAR — sadece probe iade edilir."""
		breaker = self._half_open(failure_window_sec=120)
		before = _coerce_counter(frappe.cache.get(breaker._key("failures")))  # noqa: SLF001
		breaker.acquire_probe()

		breaker.record(Outcome.NEUTRAL, is_probe=True)

		after = _coerce_counter(frappe.cache.get(breaker._key("failures")))  # noqa: SLF001
		self.assertEqual(before, after, "NEUTRAL sayacı değiştirdi")
		self.assertIsNone(frappe.cache.get(breaker._key("open")), "NEUTRAL devreyi açtı")  # noqa: SLF001

	def test_neutral_outside_a_probe_stays_a_pure_noop(self) -> None:
		"""Probe DIŞINDAKİ NEUTRAL başkasının probe anahtarını SİLMEMELİ."""
		breaker = self._half_open()
		self.assertTrue(breaker.acquire_probe())

		CarrierCircuitBreaker(self.code, failure_threshold=1, cooldown_sec=30).record_neutral()

		self.assertFalse(breaker.acquire_probe(), "Probe'suz NEUTRAL komşunun anahtarını yaktı")

	def test_release_probe_is_a_noop_when_disabled(self) -> None:
		breaker = self._breaker(enabled=False)
		with mock.patch("frappe.cache", _ExplodingCache()):
			breaker.release_probe()

	def test_release_probe_fails_open_on_cache_fault(self) -> None:
		breaker = self._breaker()
		with (
			mock.patch("frappe.cache", _ExplodingCache()),
			mock.patch("tradehub_core.logistics.resilience.fault_report._LAST_WARNING", {}),
			mock.patch("frappe.log_error") as log_error,
		):
			breaker.release_probe()
		self.assertTrue(log_error.called, "Yutulan cache arızası raporlanmadı")

	def test_failed_probe_still_reopens_the_circuit(self) -> None:
		"""Karşı kilit: UNAVAILABLE probe HÂLÂ cooldown'u yeniden başlatmalı."""
		breaker = self._half_open()
		breaker.acquire_probe()

		breaker.record(Outcome.UNAVAILABLE, is_probe=True)

		self.assertIs(breaker.state(), CircuitState.OPEN)


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
# open / probe / notice TTL'i — `ex=` düşerse devre KALICI AÇIK kalır
# ---------------------------------------------------------------------------


class TestControlKeyTtl(_BreakerCase):
	"""Denetim ölçtü: `open` ve `probe` anahtarlarının TTL'i TESTSİZDİ.

	`ex=self.cooldown_sec` argümanı düşerse anahtar SÜRESİZ yaşar: devre bir kez
	açıldığında `reset()` çağrılana kadar KALICI AÇIK kalır ve o taşıyıcıya giden
	her çağrı sonsuza dek `CIRCUIT_OPEN` alır. Mutasyon (ex kaldırma) eskiden
	HİÇBİR testi düşürmüyordu.
	"""

	COOLDOWN = 45

	def _opened(self) -> CarrierCircuitBreaker:
		breaker = self._breaker(failure_threshold=1, cooldown_sec=self.COOLDOWN)
		breaker.reset()
		breaker.record_failure()
		return breaker

	def _assert_bounded_ttl(self, key: bytes | str, label: str) -> None:
		ttl = frappe.cache.ttl(key)
		self.assertIsNotNone(ttl, f"{label}: TTL okunamadı")
		self.assertGreater(ttl, 0, f"{label} anahtarı TTL'SİZ — devre kalıcı açık kalır")
		self.assertLessEqual(ttl, self.COOLDOWN, f"{label} TTL'i cooldown'u aşıyor")

	def test_open_key_expires_with_the_cooldown(self) -> None:
		breaker = self._opened()
		self._assert_bounded_ttl(breaker._key("open"), "open")  # noqa: SLF001

	def test_probe_key_expires_with_the_cooldown(self) -> None:
		"""TTL'siz `probe`: cooldown bitse bile hiçbir işçi bir daha probe ALAMAZ."""
		breaker = self._opened()
		self._expire_open_key(breaker)
		self.assertTrue(breaker.acquire_probe())
		self._assert_bounded_ttl(breaker._key("probe"), "probe")  # noqa: SLF001

	def test_notice_key_expires_with_the_cooldown(self) -> None:
		breaker = self._breaker(cooldown_sec=self.COOLDOWN)
		breaker.reset()
		self.assertTrue(breaker.claim_open_notice())
		self._assert_bounded_ttl(breaker._key("notice"), "notice")  # noqa: SLF001

	def test_reopened_probe_failure_keys_also_carry_a_ttl(self) -> None:
		"""Başarısız probe yolu `open` + `failures`'ı YENİDEN yazar — o dal da TTL'li olmalı."""
		breaker = self._breaker(failure_threshold=1, cooldown_sec=self.COOLDOWN, failure_window_sec=120)
		breaker.reset()
		breaker.record_failure()
		self._expire_open_key(breaker)
		breaker.acquire_probe()

		breaker.record_failure(is_probe=True)

		self._assert_bounded_ttl(breaker._key("open"), "open (probe sonrası)")  # noqa: SLF001
		failures_ttl = frappe.cache.ttl(breaker._key("failures"))  # noqa: SLF001
		self.assertGreater(failures_ttl, 0, "failures TTL'siz — sayaç bir daha sıfırlanmaz")
		self.assertLessEqual(failures_ttl, 120)


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

	def test_throttle_scope_is_per_circuit_not_global(self) -> None:
		"""Kapsam sabit metot adıydı: TÜM taşıyıcılar tek kısma kovasını paylaşıyordu.

		Bir taşıyıcının Redis arızası, diğerlerinin arızasını 60 sn boyunca
		SUSTURUYORDU — en çok ihtiyaç duyulan ilk satır kayboluyordu.
		"""
		other = CarrierCircuitBreaker(f"CBU-{uuid.uuid4().hex[:10]}")
		sandbox = CarrierCircuitBreaker(self.code, environment="sandbox")
		with (
			mock.patch("frappe.cache", _ExplodingCache()),
			mock.patch("tradehub_core.logistics.resilience.fault_report._LAST_WARNING", {}),
			mock.patch("frappe.log_error") as log_error,
		):
			self._breaker().state()
			other.state()
			sandbox.state()

		self.assertEqual(log_error.call_count, 3, "Devreler tek kısma kovasını paylaşıyor")

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


# ---------------------------------------------------------------------------
# Kısma penceresi (BULGU 4) — `fault_report.report_throttled`
# ---------------------------------------------------------------------------


class TestFaultReportThrottleWindow(unittest.TestCase):
	"""ÖLÇÜLDÜ: pencere "son RAPOR"dan değil "son OLAY"dan ölçülüyordu.

	Zaman damgası HER çağrıda tazelendiği için sonuç docstring'in vaadinin
	TERSİYDİ:

		200 sn kesintisiz arıza, sn'de 1 → TOPLAM 1 rapor  (arıza sürerken SESSİZ)
		90 sn arayla 5 seyrek arıza      → TOPLAM 5 rapor  (seyrekken GÜRÜLTÜLÜ)

	Yani kalıcı bir Redis çöküşünde ilk saniyeden sonra hiçbir yere hiçbir şey
	yazılmıyordu. Kardeş yüklem `should_report` pencereyi zaten doğru kuruyordu.
	"""

	def setUp(self) -> None:
		fault_report.reset_throttle()
		self.addCleanup(fault_report.reset_throttle)
		self.clock = [1000.0]
		patcher = mock.patch.object(fault_report.time, "monotonic", lambda: self.clock[0])
		patcher.start()
		self.addCleanup(patcher.stop)

	def _drive(self, offsets: list[float]) -> tuple[int, int]:
		"""Verilen zaman damgalarında raporlar; (error_log, warning) sayısını döner."""
		warnings: list[str] = []

		class _Logger:
			def warning(self, message: str) -> None:
				warnings.append(message)

		with (
			mock.patch("frappe.log_error") as log_error,
			mock.patch("frappe.logger", return_value=_Logger()),
		):
			for offset in offsets:
				self.clock[0] = 1000.0 + offset
				fault_report.report_throttled("scope", "arıza", "başlık")
		return log_error.call_count, len(warnings)

	def test_continuous_fault_keeps_reporting_once_per_window(self) -> None:
		"""200 sn kesintisiz arıza (sn'de 1) artık pencere başına bir rapor üretir."""
		errors, warnings = self._drive([float(i) for i in range(200)])

		self.assertEqual(errors, 1, "İlk görülüş kalıcı Error Log satırı olmalı")
		expected = int(200 // fault_report.FAULT_WARN_WINDOW_SEC)
		self.assertEqual(
			warnings, expected, f"Kesintisiz arıza {warnings} uyarı üretti, {expected} bekleniyordu"
		)
		self.assertGreater(errors + warnings, 1, "Arıza sürerken kısma tamamen SUSTURUYOR")

	def test_sparse_faults_are_unchanged(self) -> None:
		"""Karşı kilit: 90 sn arayla gelen 5 seyrek arıza hâlâ 5 rapor."""
		errors, warnings = self._drive([0.0, 90.0, 180.0, 270.0, 360.0])

		self.assertEqual((errors, warnings), (1, 4))

	def test_bursts_inside_one_window_are_still_collapsed(self) -> None:
		"""Kısmanın ASIL işi: pencere içindeki fırtına tek satıra iner."""
		errors, warnings = self._drive([0.0, 0.1, 0.2, 1.0, 30.0, 59.9])

		self.assertEqual((errors, warnings), (1, 0))

	def test_timestamp_advances_only_when_a_report_is_written(self) -> None:
		"""Damga yazılmayan çağrıda tazelenirse pencere hiç dolmaz — doğrudan kilit."""
		self.clock[0] = 1000.0
		with mock.patch("frappe.log_error"):
			fault_report.report_throttled("s2", "a", "t")
		first = fault_report._LAST_WARNING["s2"]  # noqa: SLF001

		for offset in (10.0, 20.0, 50.0):
			self.clock[0] = 1000.0 + offset
			with mock.patch("frappe.log_error"):
				fault_report.report_throttled("s2", "a", "t")

		self.assertEqual(fault_report._LAST_WARNING["s2"], first, "Damga rapor yazılmadan tazelendi")  # noqa: SLF001

	def test_should_report_window_is_the_reference_and_still_holds(self) -> None:
		"""Kardeş yüklem: pencere başına `limit` kez True, sonra False."""
		self.clock[0] = 2000.0
		self.assertTrue(fault_report.should_report("s3", 2))
		self.assertTrue(fault_report.should_report("s3", 2))
		self.assertFalse(fault_report.should_report("s3", 2))

		self.clock[0] = 2000.0 + fault_report.FAULT_WARN_WINDOW_SEC
		self.assertTrue(fault_report.should_report("s3", 2), "Pencere dolunca sayaç sıfırlanmadı")


if __name__ == "__main__":
	unittest.main()
