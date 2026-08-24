"""T-067 · INV-01..INV-12 haritasının eksiksiz ve canlı olduğunu kanıtlar."""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
MAP_PATH = Path(__file__).with_name("invariants.json")
EXPECTED_IDS = {f"INV-{number:02d}" for number in range(1, 13)}


def _mapping() -> dict[str, Any]:
	return json.loads(MAP_PATH.read_text(encoding="utf-8"))


def _assert_node_exists(test: unittest.TestCase, node_id: str) -> None:
	parts = node_id.split("::")
	test.assertIn(len(parts), {2, 3}, f"geçersiz test kimliği: {node_id}")
	path = ROOT / parts[0]
	test.assertTrue(path.is_file(), f"test dosyası yok: {path}")
	tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
	if len(parts) == 2:
		functions = {node.name for node in tree.body if isinstance(node, ast.FunctionDef)}
		test.assertIn(parts[1], functions, node_id)
		return
	classes = {node.name: node for node in tree.body if isinstance(node, ast.ClassDef)}
	test.assertIn(parts[1], classes, node_id)
	methods = {node.name for node in classes[parts[1]].body if isinstance(node, ast.FunctionDef)}
	test.assertIn(parts[2], methods, node_id)


class InvariantMapAAA(unittest.TestCase):
	def test_exactly_twelve_normative_invariants_are_mapped(self) -> None:
		# Arrange
		mapping = _mapping()

		# Act
		rows = mapping["invariants"]
		ids = {row["id"] for row in rows}

		# Assert
		self.assertEqual(mapping["coverage"], "12/12")
		self.assertEqual(len(rows), 12)
		self.assertEqual(ids, EXPECTED_IDS)

	def test_every_mapping_points_to_a_real_test_symbol(self) -> None:
		for row in _mapping()["invariants"]:
			# Arrange
			node_ids = [row["primary_test"], *row.get("supporting_tests", [])]

			# Act / Assert
			with self.subTest(invariant=row["id"]):
				self.assertIn(row["tier"], {"pr", "site", "nightly"})
				for node_id in node_ids:
					_assert_node_exists(self, node_id)


if __name__ == "__main__":
	unittest.main(verbosity=2)
