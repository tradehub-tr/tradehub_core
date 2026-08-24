"""T-018 CDN purge batch/provider/sır güvenliği testleri."""

from __future__ import annotations

import json
import unittest

from tradehub_core.media.pipeline.delivery.cdn import (
	CdnPurgeClient,
	CdnPurgeConfig,
	CdnPurgeError,
	HttpResponse,
	should_purge,
)

TOKEN = "probe-token-that-must-never-leak"


class FakeTransport:
	def __init__(self, status: int = 204, error: bool = False):
		self.status = status
		self.error = error
		self.calls = []

	def __call__(self, method, url, headers, body, timeout):
		self.calls.append((method, url, dict(headers), body, timeout))
		if self.error:
			raise RuntimeError(f"provider echoed {TOKEN}")
		return HttpResponse(self.status)


class CdnDeliveryTest(unittest.TestCase):
	def test_surumlu_url_purge_istemez(self):
		self.assertFalse(should_purge(old_url="https://cdn/a.v1.jpg", new_url="https://cdn/a.v2.jpg"))
		self.assertTrue(should_purge(old_url="https://cdn/a.jpg", new_url="https://cdn/a.jpg"))

	def test_generic_batch_dedup(self):
		transport = FakeTransport()
		config = CdnPurgeConfig("generic", "https://purge.example.test/v1", TOKEN, max_batch=2)
		result = CdnPurgeClient(config, transport=transport).purge(
			["https://cdn.example.test/a", "https://cdn.example.test/a", "https://cdn.example.test/b"]
		)
		self.assertTrue(result.ok)
		self.assertEqual(result.requested, 2)
		self.assertEqual(len(transport.calls), 1)
		self.assertEqual(json.loads(transport.calls[0][3]), {"urls": ["https://cdn.example.test/a", "https://cdn.example.test/b"]})

	def test_cloudflare_endpoint_ve_body(self):
		transport = FakeTransport()
		config = CdnPurgeConfig("cloudflare", "https://api.cloudflare.test/client/v4", TOKEN, zone_id="zone 1")
		CdnPurgeClient(config, transport=transport).purge(["https://cdn.example.test/a"])
		method, url, headers, body, _timeout = transport.calls[0]
		self.assertEqual(method, "POST")
		self.assertTrue(url.endswith("/zones/zone%201/purge_cache"))
		self.assertEqual(headers["Authorization"], f"Bearer {TOKEN}")
		self.assertEqual(json.loads(body), {"files": ["https://cdn.example.test/a"]})

	def test_bunny_tekli_istekler(self):
		transport = FakeTransport()
		config = CdnPurgeConfig("bunny", "https://api.bunny.test/purge", TOKEN, max_batch=30)
		result = CdnPurgeClient(config, transport=transport).purge(
			["https://cdn.example.test/a", "https://cdn.example.test/b"]
		)
		self.assertEqual(len(transport.calls), 2)
		self.assertEqual(result.purged, 2)
		self.assertEqual(transport.calls[0][2]["AccessKey"], TOKEN)

	def test_token_hata_metnine_sizmaz(self):
		transport = FakeTransport(error=True)
		config = CdnPurgeConfig("generic", "https://purge.example.test/v1", TOKEN)
		with self.assertRaises(CdnPurgeError) as ctx:
			CdnPurgeClient(config, transport=transport).purge(["https://cdn.example.test/a"])
		self.assertNotIn(TOKEN, str(ctx.exception))

	def test_https_api_ve_guvenli_purge_url_zorunlu(self):
		with self.assertRaises(CdnPurgeError):
			CdnPurgeConfig("generic", "http://purge.example.test", TOKEN)
		config = CdnPurgeConfig("generic", "https://purge.example.test", TOKEN)
		with self.assertRaises(CdnPurgeError):
			CdnPurgeClient(config, transport=FakeTransport()).purge(["file:///etc/passwd"])


if __name__ == "__main__":
	unittest.main()
