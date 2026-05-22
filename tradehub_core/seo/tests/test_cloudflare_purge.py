"""
Cloudflare purge pure-function testleri.

	cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_cloudflare_purge
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.cloudflare_api import _call_cloudflare_purge  # noqa: E402


class FakeResponse:
	def __init__(self, status_code: int = 200, text: str = "OK"):
		self.status_code = status_code
		self.text = text


class TestCallCloudflarePurge(unittest.TestCase):
	def test_posts_to_correct_endpoint(self):
		captured = {}

		def fake_post(url, **kwargs):
			captured["url"] = url
			captured["json"] = kwargs.get("json")
			captured["headers"] = kwargs.get("headers")
			return FakeResponse(200)

		_call_cloudflare_purge(
			zone_id="ZONE123",
			api_token="TOK456",
			urls=["https://istoc.com/urun/x"],
			http_post=fake_post,
		)

		self.assertEqual(
			captured["url"],
			"https://api.cloudflare.com/client/v4/zones/ZONE123/purge_cache",
		)

	def test_sends_urls_in_files_payload(self):
		captured = {}

		def fake_post(url, **kwargs):
			captured["json"] = kwargs.get("json")
			return FakeResponse(200)

		_call_cloudflare_purge(
			zone_id="Z",
			api_token="T",
			urls=["https://istoc.com/urun/a", "https://istoc.com/urun/b"],
			http_post=fake_post,
		)

		self.assertEqual(captured["json"], {
			"files": ["https://istoc.com/urun/a", "https://istoc.com/urun/b"],
		})

	def test_sends_bearer_token_header(self):
		captured = {}

		def fake_post(url, **kwargs):
			captured["headers"] = kwargs.get("headers")
			return FakeResponse(200)

		_call_cloudflare_purge(
			zone_id="Z",
			api_token="my-secret-token",
			urls=["https://x"],
			http_post=fake_post,
		)

		self.assertEqual(captured["headers"]["Authorization"], "Bearer my-secret-token")
		self.assertEqual(captured["headers"]["Content-Type"], "application/json")

	def test_returns_http_response(self):
		response = _call_cloudflare_purge(
			zone_id="Z",
			api_token="T",
			urls=["https://x"],
			http_post=lambda url, **kw: FakeResponse(429, "rate limited"),
		)
		self.assertEqual(response.status_code, 429)
		self.assertEqual(response.text, "rate limited")


if __name__ == "__main__":
	unittest.main()
