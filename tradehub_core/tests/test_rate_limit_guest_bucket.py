"""T9 — hız sınırlayıcı misafir kovası (DoS).

Sızma testi (docs/reports/28-faz13-pentest.md §2 T9) ölçtü: `_bucket_key`
kovayı `frappe.session.user`a bağlıyordu ve misafirde bu değer HER ZAMAN
"Guest". Yani TÜM anonim ziyaretçiler tek kova paylaşıyordu; bir saldırgan
`sf_submit_review`'in 5 çağrılık penceresini doldurunca bütün anonim trafik
o pencerede kilitleniyordu.

Düzeltme: misafir kovası istemci IP'sine bağlanır. IP'nin NASIL bulunduğu
kritik — bu modül tam olarak onu sınar:

  * `frappe.local.request_ip` `X-Forwarded-For`un EN SOLDAKİ değeridir
    (frappe/auth.py:64) ve en sol değer İSTEMCİ tarafından yazılabilir.
    Ona güvenmek limiti atlatılabilir (rastgele IP) ya da silah hâline
    getirilebilir (kurbanın IP'sini yazıp onu kilitlemek) yapar.
  * Doğrusu zinciri SAĞDAN SOLA yürüyüp güvenilir vekil OLMAYAN ilk adresi
    almaktır: sağdaki adresleri bizim kendi ters-vekillerimiz yazar.

Bilinen sınır (ölçüldü, 2026-08-19): bu kurulumda `frappe-frontend` nginx'i
`proxy_set_header X-Forwarded-For $remote_addr` ile zinciri eziyor, yani
gunicorn'a ulaşan tek adres bir KONTEYNER IP'si. O durumda çözümleyici
`None` döner ve kimlik `Guest:_unresolved` olur — misafir DoS'u uygulama
katmanından tam kapanmaz. Altyapı düzeltmesi:
docs/reports/29-pentest-duzeltmeleri.md §T9.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_rate_limit_guest_bucket
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import rate_limit as rl


class _FakeRequest:
	"""`frappe.get_request_header` yalnız `frappe.local.request.headers`e bakar."""

	def __init__(self, headers: dict[str, str]):
		self.headers = headers


class GuestBucketIdentityTests(FrappeTestCase):
	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self._orig_request = getattr(frappe.local, "request", None)
		self._orig_request_ip = getattr(frappe.local, "request_ip", None)
		self.addCleanup(self._restore)

	def _restore(self):
		frappe.set_user(self._orig_user)
		frappe.local.request = self._orig_request
		frappe.local.request_ip = self._orig_request_ip
		frappe.local.cache = {}

	def _request(self, headers: dict[str, str], request_ip: str | None = None):
		frappe.local.request = _FakeRequest(headers)
		frappe.local.request_ip = request_ip
		# `_trusted_proxy_networks` istek kapsamında önbellekli — testler arası sızmasın.
		frappe.local.cache = {}

	# -- kimlik ---------------------------------------------------------------

	def test_logged_in_user_keeps_user_bucket(self):
		"""Oturum açmış kullanıcı için kimlik DEĞİŞMEDİ (regresyon koruması)."""
		self._request({"X-Forwarded-For": "203.0.113.10"})
		frappe.set_user("Administrator")
		self.assertEqual(rl._bucket_identity(), "Administrator")

	def test_two_guests_from_different_ips_get_different_buckets(self):
		"""Bulgunun ta kendisi: iki farklı misafir birbirini kilitlememeli."""
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "203.0.113.10"})
		first = rl._bucket_identity()
		self._request({"X-Forwarded-For": "198.51.100.20"})
		second = rl._bucket_identity()
		self.assertEqual(first, "Guest:203.0.113.10")
		self.assertEqual(second, "Guest:198.51.100.20")
		self.assertNotEqual(rl._bucket_key("sf_submit_review", first), rl._bucket_key("sf_submit_review", second))

	def test_same_guest_ip_shares_one_bucket(self):
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "203.0.113.10"})
		first = rl._bucket_identity()
		self._request({"X-Forwarded-For": "203.0.113.10"})
		self.assertEqual(first, rl._bucket_identity())

	# -- sahtecilik -----------------------------------------------------------

	def test_client_supplied_leftmost_xff_is_ignored(self):
		"""İstemci sol tarafa yazarsa dikkate ALINMAZ — vekilin eklediği alınır.

		`frappe.local.request_ip` burada 9.9.9.9 (uydurma) olur; çözümleyici
		zincirin sağındaki gerçek adresi seçmelidir. Sızma raporunun Ö-E önerisi
		(`frappe.local.request_ip` kullan) tam da bu yüzden yetersizdi.
		"""
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "9.9.9.9, 203.0.113.99"}, request_ip="9.9.9.9")
		self.assertEqual(rl._client_ip(), "203.0.113.99")
		self.assertEqual(rl._bucket_identity(), "Guest:203.0.113.99")

	def test_garbage_xff_entry_is_not_used_as_identity(self):
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "not-an-ip"}, request_ip="not-an-ip")
		self.assertIsNone(rl._client_ip())
		self.assertEqual(rl._bucket_identity(), "Guest:_unresolved")

	# -- güvenilir vekil kümesi ------------------------------------------------

	def test_private_proxy_addresses_are_skipped(self):
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "203.0.113.7, 10.0.0.5, 192.168.97.8"})
		self.assertEqual(rl._client_ip(), "203.0.113.7")

	def test_all_private_chain_yields_unresolved(self):
		"""Bugünkü gerçek topoloji: zincirde yalnız konteyner IP'si var."""
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "192.168.97.9", "X-Real-IP": "192.168.97.8"}, request_ip="192.168.97.9")
		self.assertIsNone(rl._client_ip())
		self.assertEqual(rl._bucket_identity(), "Guest:_unresolved")

	def test_x_real_ip_used_when_xff_has_no_client(self):
		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "10.0.0.5", "X-Real-IP": "203.0.113.44"})
		self.assertEqual(rl._client_ip(), "203.0.113.44")

	def test_request_ip_is_last_resort(self):
		frappe.set_user("Guest")
		self._request({}, request_ip="203.0.113.55")
		self.assertEqual(rl._client_ip(), "203.0.113.55")

	def test_no_request_context_yields_unresolved(self):
		"""Arka plan işi / bench console — istek yok, IP de yok."""
		frappe.set_user("Guest")
		frappe.local.request = None
		self.assertIsNone(rl._client_ip())

	# -- dekoratör davranışı ---------------------------------------------------

	def test_decorator_isolates_guests_by_ip(self):
		"""Uçtan uca: bir misafir kovayı doldurunca diğeri ETKİLENMEZ."""
		scope = f"t9_test_{frappe.generate_hash(length=6)}"
		calls = []

		@rl.rate_limit(max_calls=2, window_seconds=60, per_user=True, scope=scope)
		def endpoint():
			calls.append(1)
			return "ok"

		frappe.set_user("Guest")

		def run(ip):
			self._request({"X-Forwarded-For": ip})
			try:
				return endpoint()
			except rl.TooManyRequestsError:
				return "429"

		attacker = [run("203.0.113.10") for _ in range(4)]
		victim = [run("198.51.100.20") for _ in range(2)]

		self.addCleanup(lambda: self._cleanup_bucket(scope))
		self.assertEqual(attacker, ["ok", "ok", "429", "429"], "saldırganın kovası doğru davranmadı")
		self.assertEqual(victim, ["ok", "ok"], "ikinci misafir saldırganın kovasından etkilendi (DoS)")

	def _cleanup_bucket(self, scope: str):
		for ip in ("203.0.113.10", "198.51.100.20"):
			frappe.cache().delete_value(rl._bucket_key(scope, f"Guest:{ip}"))

	def test_global_scope_unchanged(self):
		"""`per_user=False` kapsamları bilinçli global — davranış değişmemeli."""
		scope = f"t9_global_{frappe.generate_hash(length=6)}"

		@rl.rate_limit(max_calls=1, window_seconds=60, per_user=False, scope=scope)
		def endpoint():
			return "ok"

		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "203.0.113.10"})
		self.assertEqual(endpoint(), "ok")
		self._request({"X-Forwarded-For": "198.51.100.20"})
		with self.assertRaises(rl.TooManyRequestsError):
			endpoint()
		frappe.cache().delete_value(rl._bucket_key(scope, "_global"))

	def test_helpers_target_the_same_bucket_as_decorator(self):
		"""`get_remaining` / `reset_bucket` dekoratörle AYNI kovayı hedeflemeli."""
		scope = f"t9_helper_{frappe.generate_hash(length=6)}"

		@rl.rate_limit(max_calls=3, window_seconds=60, per_user=True, scope=scope)
		def endpoint():
			return "ok"

		frappe.set_user("Guest")
		self._request({"X-Forwarded-For": "203.0.113.77"})
		endpoint()
		self.assertEqual(rl.get_remaining(scope, max_calls=3), 2)
		rl.reset_bucket(scope)
		self.assertEqual(rl.get_remaining(scope, max_calls=3), 3)


class TrustedProxyConfigTests(FrappeTestCase):
	def test_defaults_cover_container_and_loopback_ranges(self):
		nets = {str(n) for n in rl._trusted_proxy_networks()}
		for expected in ("127.0.0.0/8", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
			self.assertIn(expected, nets)

	def test_public_address_is_not_trusted(self):
		self.assertFalse(rl._is_trusted_proxy("203.0.113.1"))
		self.assertTrue(rl._is_trusted_proxy("192.168.97.9"))
		self.assertTrue(rl._is_trusted_proxy("127.0.0.1"))
		self.assertTrue(rl._is_trusted_proxy(""))
