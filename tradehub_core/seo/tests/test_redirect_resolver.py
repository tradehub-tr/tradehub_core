"""redirect_resolver pure-function testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_redirect_resolver
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.redirect_resolver import (  # noqa: E402
	find_matching_redirect,
	follow_redirect_chain,
)


def _r(source, target, *, match_type="exact", status="301"):
	return {
		"source_path": source,
		"target_path": target,
		"match_type": match_type,
		"status_code": status,
	}


class TestFindMatchingRedirect(unittest.TestCase):
	def test_exact_match(self):
		redirects = [_r("/eski", "/yeni")]
		result = find_matching_redirect("/eski", redirects)
		self.assertEqual(result["target_path"], "/yeni")

	def test_no_match_returns_none(self):
		redirects = [_r("/foo", "/bar")]
		self.assertIsNone(find_matching_redirect("/baz", redirects))

	def test_exact_takes_priority_over_prefix(self):
		redirects = [
			_r("/eski/", "/genel", match_type="prefix"),
			_r("/eski/spesifik", "/ozel", match_type="exact"),
		]
		result = find_matching_redirect("/eski/spesifik", redirects)
		self.assertEqual(result["target_path"], "/ozel")

	def test_prefix_match(self):
		redirects = [_r("/eski/*", "/yeni", match_type="prefix")]
		result = find_matching_redirect("/eski/alt", redirects)
		self.assertEqual(result["target_path"], "/yeni")

	def test_longest_prefix_wins(self):
		redirects = [
			_r("/eski/", "/genel", match_type="prefix"),
			_r("/eski/alt/", "/spesifik", match_type="prefix"),
		]
		result = find_matching_redirect("/eski/alt/foo", redirects)
		self.assertEqual(result["target_path"], "/spesifik")

	def test_regex_match(self):
		redirects = [_r(r"^/u/(\d+)$", "/urun/by-id", match_type="regex")]
		result = find_matching_redirect("/u/123", redirects)
		self.assertEqual(result["target_path"], "/urun/by-id")

	def test_invalid_regex_skipped(self):
		redirects = [_r("[invalid(", "/x", match_type="regex")]
		self.assertIsNone(find_matching_redirect("/anything", redirects))

	def test_empty_path_returns_none(self):
		self.assertIsNone(find_matching_redirect("", [_r("/a", "/b")]))

	def test_empty_redirects_returns_none(self):
		self.assertIsNone(find_matching_redirect("/a", []))


class TestFollowRedirectChain(unittest.TestCase):
	def test_single_hop(self):
		redirects = [_r("/a", "/b")]
		result = follow_redirect_chain("/a", redirects)
		self.assertEqual(result["final_path"], "/b")
		self.assertEqual(result["status_code"], "301")

	def test_transitive_two_hops(self):
		redirects = [_r("/a", "/b"), _r("/b", "/c")]
		result = follow_redirect_chain("/a", redirects)
		self.assertEqual(result["final_path"], "/c")

	def test_loop_detection_returns_none(self):
		redirects = [_r("/a", "/b"), _r("/b", "/a")]
		result = follow_redirect_chain("/a", redirects)
		self.assertIsNone(result)

	def test_self_loop_returns_none(self):
		redirects = [_r("/a", "/a")]
		result = follow_redirect_chain("/a", redirects)
		self.assertIsNone(result)

	def test_max_depth_reached_returns_final(self):
		redirects = [
			_r("/a", "/b"),
			_r("/b", "/c"),
			_r("/c", "/d"),
			_r("/d", "/e"),  # max_depth=3 → /e'ye ulaşmaz
		]
		result = follow_redirect_chain("/a", redirects, max_depth=3)
		# 3 hop sonra /d'de durmalı
		self.assertEqual(result["final_path"], "/d")

	def test_no_match_returns_none(self):
		redirects = [_r("/x", "/y")]
		result = follow_redirect_chain("/a", redirects)
		self.assertIsNone(result)

	def test_preserves_status_code(self):
		redirects = [_r("/a", "/b", status="302")]
		result = follow_redirect_chain("/a", redirects)
		self.assertEqual(result["status_code"], "302")


if __name__ == "__main__":
	unittest.main()
