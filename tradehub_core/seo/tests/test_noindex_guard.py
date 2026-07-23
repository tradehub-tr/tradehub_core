"""noindex_guard pure-function testleri (a-h seti).

cd apps/tradehub_core && python -m unittest tradehub_core.seo.tests.test_noindex_guard
"""

import sys
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[3]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


from tradehub_core.seo.noindex_guard import (  # noqa: E402
	NOINDEX_VALUE,
	should_add_noindex_header,
)
from tradehub_core.seo.robots_generator import resolve_env_for_site  # noqa: E402


class TestGuardFlagContract(unittest.TestCase):
	"""SÖZLEŞME: bayrak yokken/0 iken hiçbir header eklenmez."""

	def test_a_flag_off_never_adds_header_on_staging(self):
		self.assertFalse(
			should_add_noindex_header(guard_enabled=False, env="rc", storefront_marker=False)
		)

	def test_b_flag_off_never_adds_header_on_beta(self):
		self.assertFalse(
			should_add_noindex_header(guard_enabled=False, env="beta", storefront_marker=False)
		)

	def test_c_flag_on_staging_adds_header(self):
		self.assertTrue(
			should_add_noindex_header(guard_enabled=True, env="rc", storefront_marker=False)
		)
		self.assertTrue(
			should_add_noindex_header(guard_enabled=True, env="beta", storefront_marker=False)
		)

	def test_d_flag_on_prod_never_adds_header(self):
		"""Prod sitesi bot-proxy Host'u backend görünse bile noindex ALMAZ."""
		self.assertFalse(
			should_add_noindex_header(guard_enabled=True, env="prod", storefront_marker=False)
		)

	def test_e_storefront_marker_exempts(self):
		self.assertFalse(
			should_add_noindex_header(guard_enabled=True, env="rc", storefront_marker=True)
		)

	def test_f_header_value_format(self):
		self.assertEqual(NOINDEX_VALUE, "noindex, nofollow")


class TestEnvResolutionForGuard(unittest.TestCase):
	"""Guard'ın ortam kararı site adından gelir (eşleme-önce)."""

	def test_g_prod_site_resolves_prod_despite_config(self):
		"""Restore artığı config guard'ı yanıltamaz: eşleme kazanır."""
		self.assertEqual(resolve_env_for_site("istoc.cronbi.com", "beta"), "prod")

	def test_h_staging_site_resolves_staging_despite_prod_config(self):
		"""Prod DB'si rc'ye restore edilse bile rc sitesi rc kalır."""
		self.assertEqual(resolve_env_for_site("rcistoc.cronbi.com", "prod"), "rc")


if __name__ == "__main__":
	unittest.main()
