"""robots_generator pure-function testleri.

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_robots_generator
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.robots_generator import (  # noqa: E402
	BLOCK_ALL_TEMPLATE,
	build_prod_robots,
	build_robots_txt,
)


class TestBuildProdRobots(unittest.TestCase):
	def test_includes_useragent_star(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("User-agent: *", out)

	def test_disallows_api(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Disallow: /api/", out)

	def test_disallows_dashboard(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Disallow: /pages/dashboard/", out)

	def test_disallows_cart_checkout(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Disallow: /cart.html", out)
		self.assertIn("Disallow: /checkout.html", out)

	def test_disallows_search_params(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Disallow: /*?q=", out)
		self.assertIn("Disallow: /*?utm_*", out)

	def test_includes_sitemap_url(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Sitemap: https://istoc.com/sitemap.xml", out)

	def test_allow_root(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Allow: /", out)


class TestBlockAllTemplate(unittest.TestCase):
	def test_block_all_format(self):
		self.assertEqual(BLOCK_ALL_TEMPLATE.strip(), "User-agent: *\nDisallow: /")


class TestBuildRobotsTxt(unittest.TestCase):
	def test_beta_returns_block_all(self):
		out = build_robots_txt(env="beta", site_url="https://betaistoc.cronbi.com")
		self.assertEqual(out.strip(), BLOCK_ALL_TEMPLATE.strip())

	def test_rc_returns_block_all(self):
		out = build_robots_txt(env="rc", site_url="https://rcistoc.cronbi.com")
		self.assertEqual(out.strip(), BLOCK_ALL_TEMPLATE.strip())

	def test_prod_returns_full_ruleset(self):
		out = build_robots_txt(env="prod", site_url="https://istoc.com")
		self.assertIn("Allow: /", out)
		self.assertIn("Sitemap:", out)
		self.assertNotEqual(out.strip(), BLOCK_ALL_TEMPLATE.strip())

	def test_unknown_env_safe_default(self):
		out = build_robots_txt(env="staging", site_url="https://x.com")
		self.assertEqual(out.strip(), BLOCK_ALL_TEMPLATE.strip())

	def test_manual_override_takes_precedence(self):
		out = build_robots_txt(
			env="prod",
			site_url="https://istoc.com",
			manual_override="User-agent: *\nDisallow: /test",
		)
		self.assertEqual(out, "User-agent: *\nDisallow: /test")


if __name__ == "__main__":
	unittest.main()
