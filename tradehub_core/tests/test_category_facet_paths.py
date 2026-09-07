"""Kategori filtre ağacı — facet kategorilerine ata zinciri (path) eklenmesi.

Storefront listeleme sayfasındaki "Kategoriler" filtresi düz listeden ağaca
dönüşüyor. Mega menü 3 seviyede kesildiği, DB ağacı ise daha derine indiği
için (Ev & Bahçe > Mutfak > Saklama > Kavanoz > Baharatlık) ağaç, facet'in
kendisinin döndürdüğü ata zincirinden kurulur. Bu test o çözücüyü sabitler.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.listing import _category_ancestor_paths

_TUZ = "cfp"


def _mk(external_id, name, parent=None, slug=None, is_active=1):
	doc = frappe.get_doc(
		{
			"doctype": "Product Category",
			"external_id": external_id,
			"category_name": name,
			"parent_product_category": parent,
			"url_slug": slug,
			"is_active": is_active,
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


class TestCategoryAncestorPaths(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.root = _mk(f"{_TUZ}-root", f"{_TUZ} Kök", slug=f"{_TUZ}-kok")
		cls.mid = _mk(f"{_TUZ}-mid", f"{_TUZ} Orta", parent=cls.root, slug=f"{_TUZ}-orta")
		cls.leaf = _mk(f"{_TUZ}-leaf", f"{_TUZ} Yaprak", parent=cls.mid, slug=f"{_TUZ}-yaprak")
		cls.other_root = _mk(f"{_TUZ}-other", f"{_TUZ} Diğer", slug=f"{_TUZ}-diger")

	def test_leaf_gets_root_to_parent_chain_in_order(self):
		result = _category_ancestor_paths([self.leaf])
		self.assertEqual(
			result[self.leaf]["path"],
			[
				{"id": self.root, "name": f"{_TUZ} Kök", "slug": f"{_TUZ}-kok"},
				{"id": self.mid, "name": f"{_TUZ} Orta", "slug": f"{_TUZ}-orta"},
			],
		)

	def test_root_has_empty_path_and_own_name_slug(self):
		result = _category_ancestor_paths([self.root])
		self.assertEqual(result[self.root]["path"], [])
		self.assertEqual(result[self.root]["name"], f"{_TUZ} Kök")
		self.assertEqual(result[self.root]["slug"], f"{_TUZ}-kok")

	def test_mixed_input_resolves_every_requested_category(self):
		result = _category_ancestor_paths([self.leaf, self.other_root, self.mid])
		self.assertEqual(set(result.keys()), {self.leaf, self.other_root, self.mid})
		self.assertEqual([p["id"] for p in result[self.mid]["path"]], [self.root])
		self.assertEqual(result[self.other_root]["path"], [])

	def test_unknown_id_falls_back_to_id_as_name(self):
		result = _category_ancestor_paths(["cfp-does-not-exist"])
		self.assertEqual(
			result["cfp-does-not-exist"],
			{"name": "cfp-does-not-exist", "slug": "", "path": []},
		)

	def test_empty_input_returns_empty_map(self):
		self.assertEqual(_category_ancestor_paths([]), {})
