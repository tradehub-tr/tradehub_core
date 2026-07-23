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
	resolve_env_for_site,
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
		self.assertIn("Disallow: /hesabim$", out)
		self.assertIn("Disallow: /hesabim/", out)

	def test_disallows_cart_checkout_pretty_urls(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Disallow: /sepet$", out)
		self.assertIn("Disallow: /odeme$", out)
		self.assertIn("Disallow: /odeme/", out)
		self.assertIn("Disallow: /pages/cart.html$", out)
		self.assertIn("Disallow: /pages/order/", out)

	def test_anchored_odeme_does_not_shadow_info_page(self):
		"""`/odeme$` ankrajı `/odeme-secenekleri` info sayfasını engellememeli."""
		out = build_prod_robots("https://istoc.com")
		self.assertNotIn("Disallow: /odeme\n", out.replace("Disallow: /odeme$\n", ""))
		self.assertNotIn("Disallow: /odeme-secenekleri", out)

	def test_disallows_search_params(self):
		out = build_prod_robots("https://istoc.com")
		self.assertIn("Disallow: /*?q=", out)
		self.assertIn("Disallow: /*?utm_", out)
		self.assertIn("Disallow: /*?lng=", out)

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


class TestSiteToEnvMapping(unittest.TestCase):
	"""Ç1 kararı: eşleme-önce; config yalnız eşleme-dışı fallback (restore-proof)."""

	def test_prod_site_maps_to_prod(self):
		self.assertEqual(resolve_env_for_site("istoc.cronbi.com"), "prod")

	def test_rc_site_maps_to_rc(self):
		self.assertEqual(resolve_env_for_site("rcistoc.cronbi.com"), "rc")

	def test_beta_site_maps_to_beta(self):
		self.assertEqual(resolve_env_for_site("betaistoc.cronbi.com"), "beta")

	def test_alpha_site_maps_to_beta(self):
		self.assertEqual(resolve_env_for_site("alphaistoc.cronbi.com"), "beta")

	def test_mapping_wins_over_config(self):
		"""Restore artığı `seo_environment=prod` staging'i indexe açamaz."""
		self.assertEqual(resolve_env_for_site("rcistoc.cronbi.com", "prod"), "rc")
		self.assertEqual(resolve_env_for_site("betaistoc.cronbi.com", "prod"), "beta")

	def test_unmapped_site_falls_back_to_config(self):
		self.assertEqual(resolve_env_for_site("tradehub.localhost", "prod"), "prod")

	def test_unmapped_site_without_config_defaults_to_beta(self):
		"""Güvenli default: bilinmeyen site + config yok → beta (noindex tarafı)."""
		self.assertEqual(resolve_env_for_site("tradehub.localhost"), "beta")
		self.assertEqual(resolve_env_for_site(None), "beta")

	def test_site_name_normalized(self):
		self.assertEqual(resolve_env_for_site(" ISTOC.CRONBI.COM "), "prod")


if __name__ == "__main__":
	unittest.main()
