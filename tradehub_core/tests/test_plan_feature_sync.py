"""Plan-özellik senkronu — pricing_features (admin matris) → capability_flags/
quota_limits MERGE mantığı (saf) testleri.

frappe stub'lanır → controller modülü frappe'siz import edilir; CI gate'inde koşar.
Amaç: "matriste işaretleyince özellik pakete gelir; kaldırınca gider" garantisi.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

# --- frappe stub (controller import'u için) ---
_f = sys.modules.get("frappe") or types.ModuleType("frappe")
_f.__path__ = []
_f._ = lambda s: s
_model = types.ModuleType("frappe.model")
_model.__path__ = []
_docmod = types.ModuleType("frappe.model.document")


class _Document:
	pass


_docmod.Document = _Document
sys.modules["frappe"] = _f
sys.modules["frappe.model"] = _model
sys.modules["frappe.model.document"] = _docmod

from tradehub_core.tradehub_core.doctype.subscription_plan.subscription_plan import (  # noqa: E402
	_quota_value_from_row,
	merge_matrix_into_entitlement,
)

_VALID = {"feature.x", "feature.role.keep", "quota.max_products"}


def _row(fkey, included, text=""):
	return {"feature_key": fkey, "is_included": included, "text_value": text}


class MergeMatrixTests(unittest.TestCase):
	def test_checked_feature_reaches_caps(self):
		caps, _, changed = merge_matrix_into_entitlement([_row("feature.x", 1)], {}, {}, _VALID)
		self.assertIs(caps["feature.x"], True)
		self.assertTrue(changed)

	def test_unchecked_feature_sets_false(self):
		caps, _, _ = merge_matrix_into_entitlement(
			[_row("feature.x", 0)], {"feature.x": True}, {}, _VALID
		)
		self.assertIs(caps["feature.x"], False)

	def test_non_matrix_caps_preserved(self):
		# Matriste satırı OLMAYAN mevcut key korunur (veri kaybı yok)
		caps, _, _ = merge_matrix_into_entitlement(
			[_row("feature.x", 1)], {"feature.role.keep": True}, {}, _VALID
		)
		self.assertIs(caps["feature.role.keep"], True)
		self.assertIs(caps["feature.x"], True)

	def test_invalid_key_skipped(self):
		caps, _, changed = merge_matrix_into_entitlement([_row("feature.unknown", 1)], {}, {}, _VALID)
		self.assertNotIn("feature.unknown", caps)
		self.assertFalse(changed)

	def test_quota_numeric_parsed(self):
		_, q, _ = merge_matrix_into_entitlement(
			[_row("quota.max_products", 1, "2.500")], {}, {}, _VALID
		)
		self.assertEqual(q["quota.max_products"], 2500)

	def test_quota_unlimited(self):
		_, q, _ = merge_matrix_into_entitlement(
			[_row("quota.max_products", 1, "Sınırsız")], {}, {}, _VALID
		)
		self.assertEqual(q["quota.max_products"], -1)

	def test_quota_disabled_when_unincluded(self):
		_, q, _ = merge_matrix_into_entitlement(
			[_row("quota.max_products", 0, "5")], {}, {}, _VALID
		)
		self.assertEqual(q["quota.max_products"], 0)

	def test_quota_unparseable_preserves_existing(self):
		# 'Özel' gibi parse edilemez metin → mevcut değer korunur (bozulmaz)
		_, q, _ = merge_matrix_into_entitlement(
			[_row("quota.max_products", 1, "Özel")], {}, {"quota.max_products": 42}, _VALID
		)
		self.assertEqual(q["quota.max_products"], 42)


class QuotaValueTests(unittest.TestCase):
	def test_included_empty_returns_none(self):
		self.assertIsNone(_quota_value_from_row(_row("quota.x", 1, "")))

	def test_percent_stripped(self):
		self.assertEqual(_quota_value_from_row(_row("quota.x", 1, "%4")), 4)


if __name__ == "__main__":
	unittest.main()
