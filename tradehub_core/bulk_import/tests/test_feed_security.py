"""feed_security.validate_feed_url SSRF korumasi testleri.

validate_feed_url frappe.throw cagirdigi icin Frappe context gerekir
(FrappeTestCase). Frappe yoksa modul atlanir. Testler ag erisimi yapmaz:
ozel/loopback/link-local IP'ler dogrudan gecerli adreslerdir, public host
(example.com) icin yalniz cozumleme yapilir, indirme denenmez.
"""

import socket
import unittest
from unittest import mock

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	import frappe

	from tradehub_core.bulk_import import feed_security


def _addrinfo(ip):
	"""socket.getaddrinfo donus formatini tek IP icin taklit eder."""
	return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", (ip, 80))]


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestValidateFeedUrl(FrappeTestCase):
	def test_non_http_scheme_throws(self):
		"""http/https disi semalar (file/ftp/gopher) reddedilir."""
		for url in ("file:///etc/passwd", "ftp://example.com/x", "gopher://example.com"):
			with self.assertRaises(frappe.ValidationError):
				feed_security.validate_feed_url(url)

	def test_empty_or_invalid_url_throws(self):
		with self.assertRaises(frappe.ValidationError):
			feed_security.validate_feed_url("")
		with self.assertRaises(frappe.ValidationError):
			feed_security.validate_feed_url(None)

	def test_missing_host_throws(self):
		with self.assertRaises(frappe.ValidationError):
			feed_security.validate_feed_url("http://")

	def test_ssrf_internal_ips_throw(self):
		"""localhost / ic ag / link-local / bulut metadata bloklu."""
		internal = [
			"127.0.0.1",
			"10.0.0.1",
			"192.168.1.1",
			"169.254.169.254",
			"::1",
		]
		for ip in internal:
			with mock.patch.object(socket, "getaddrinfo", return_value=_addrinfo(ip)):
				with self.assertRaises(frappe.ValidationError):
					feed_security.validate_feed_url("http://feed.example.test/products.xml")

	def test_localhost_hostname_throws(self):
		"""localhost adi loopback'e cozulur, bloklanir."""
		with mock.patch.object(socket, "getaddrinfo", return_value=_addrinfo("127.0.0.1")):
			with self.assertRaises(frappe.ValidationError):
				feed_security.validate_feed_url("http://localhost/feed.xml")

	def test_public_host_passes(self):
		"""Public IP'ye cozulen host SSRF kontrolunden gecer (throw etmez)."""
		with mock.patch.object(socket, "getaddrinfo", return_value=_addrinfo("93.184.216.34")):
			# example.com public bir IP'ye cozulur; throw beklenmez.
			feed_security.validate_feed_url("http://example.com/feed.xml")
