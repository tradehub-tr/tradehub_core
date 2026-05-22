"""FAZ 2.4 — Organization hiyerarşi helper testleri.

tradehub_core.utils.organization_hierarchy içindeki:
  - validate_no_cycle (self-loop, 2-cycle, 3-cycle)
  - get_ancestors
  - get_descendants
  - get_depth / get_root

için unit testler.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_organization_hierarchy
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DB: dict = {}


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	def db_get_value(doctype, name, fieldname=None, **kwargs):
		"""organization_hierarchy db.get_value: (doctype, name, field)."""
		# Mock: parent map _DB içinde
		return _DB.get(("parent", name))

	def get_all(doctype, filters=None, pluck=None, **kwargs):
		"""organization_hierarchy.get_descendants kullanıyor."""
		# filters={"tradehub_parent_org": current}
		if not filters or "tradehub_parent_org" not in filters:
			return []
		parent = filters["tradehub_parent_org"]
		# _DB içindeki tüm "parent" key'lerini tarayıp parent'ı eşleşenleri döner
		children = [child for (key_type, child), val in _DB.items() if key_type == "parent" and val == parent]
		return children

	frappe.db = SimpleNamespace(get_value=db_get_value)
	frappe.get_all = get_all

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise (exc(msg) if isinstance(exc, type) else Exception(msg))

		frappe.throw = _throw


_install_frappe_stub()


def _reset_state():
	_DB.clear()
	_install_frappe_stub()


def _set_parent(org: str, parent: str | None):
	"""_DB'ye parent ilişkisi yaz."""
	if parent is None:
		_DB.pop(("parent", org), None)
	else:
		_DB[("parent", org)] = parent


from tradehub_core.utils import organization_hierarchy as oh  # noqa: E402


def _make_doc(name, parent=None):
	doc = SimpleNamespace(name=name, tradehub_parent_org=parent)
	doc.get = lambda field, default=None: getattr(doc, field, default)
	return doc


# ---------------------------------------------------------------------------
# Cycle validation
# ---------------------------------------------------------------------------


class ValidateNoCycleTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_root_org_no_parent_ok(self):
		"""Parent yoksa cycle olamaz."""
		doc = _make_doc("acme-root", parent=None)
		oh.validate_no_cycle(doc)  # hata yok

	def test_self_loop_rejected(self):
		"""A.parent = A → ValidationError."""
		doc = _make_doc("acme", parent="acme")
		with self.assertRaises(Exception) as ctx:
			oh.validate_no_cycle(doc)
		self.assertIn("kendisini", str(ctx.exception))

	def test_two_cycle_rejected(self):
		"""A.parent = B, B.parent = A → cycle."""
		# DB: B'nin parent'ı A
		_set_parent("acme-b", "acme-a")
		# Şimdi A'nın parent'ını B yapmaya çalış
		doc = _make_doc("acme-a", parent="acme-b")
		with self.assertRaises(Exception) as ctx:
			oh.validate_no_cycle(doc)
		self.assertIn("döngü", str(ctx.exception))

	def test_three_cycle_rejected(self):
		"""A → B → C → A cycle."""
		_set_parent("acme-c", "acme-b")
		_set_parent("acme-b", "acme-a")
		doc = _make_doc("acme-a", parent="acme-c")
		with self.assertRaises(Exception) as ctx:
			oh.validate_no_cycle(doc)
		self.assertIn("döngü", str(ctx.exception))

	def test_valid_hierarchy_passes(self):
		"""A → B → C zinciri, A yeni parent → D (cycle yok)."""
		_set_parent("acme-b", "acme-a")
		_set_parent("acme-c", "acme-b")
		_set_parent("acme-d", None)  # D root
		doc = _make_doc("acme-a", parent="acme-d")
		oh.validate_no_cycle(doc)  # hata yok


# ---------------------------------------------------------------------------
# get_ancestors / get_descendants / get_depth
# ---------------------------------------------------------------------------


class HierarchyHelperTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		# Yapı: root → istanbul → pazarlama
		_set_parent("acme-pazarlama", "acme-istanbul")
		_set_parent("acme-istanbul", "acme-root")
		_set_parent("acme-root", None)

	def test_get_ancestors_3_levels(self):
		ancestors = oh.get_ancestors("acme-pazarlama")
		self.assertEqual(ancestors, ["acme-istanbul", "acme-root"])

	def test_get_ancestors_root_empty(self):
		self.assertEqual(oh.get_ancestors("acme-root"), [])

	def test_get_descendants_from_root(self):
		desc = oh.get_descendants("acme-root")
		self.assertIn("acme-istanbul", desc)
		self.assertIn("acme-pazarlama", desc)
		self.assertEqual(len(desc), 2)

	def test_get_descendants_leaf(self):
		"""Yaprak → boş liste."""
		self.assertEqual(oh.get_descendants("acme-pazarlama"), [])

	def test_get_depth(self):
		self.assertEqual(oh.get_depth("acme-root"), 0)
		self.assertEqual(oh.get_depth("acme-istanbul"), 1)
		self.assertEqual(oh.get_depth("acme-pazarlama"), 2)

	def test_get_root(self):
		self.assertEqual(oh.get_root("acme-pazarlama"), "acme-root")
		self.assertEqual(oh.get_root("acme-root"), "acme-root")


if __name__ == "__main__":
	unittest.main()
