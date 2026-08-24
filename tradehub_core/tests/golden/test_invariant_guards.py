"""T-067 · Entegrasyon invariantlarının üretim rotasına bağlılık kapıları."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def _function(path: Path, name: str) -> ast.FunctionDef:
	tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
	for node in tree.body:
		if isinstance(node, ast.FunctionDef) and node.name == name:
			return node
	raise AssertionError(f"{path}:{name} bulunamadı")


def _call_names(function: ast.FunctionDef) -> set[str]:
	names: set[str] = set()
	for node in ast.walk(function):
		if not isinstance(node, ast.Call):
			continue
		callee = node.func
		if isinstance(callee, ast.Name):
			names.add(callee.id)
		elif isinstance(callee, ast.Attribute) and isinstance(callee.value, ast.Name):
			names.add(f"{callee.value.id}.{callee.attr}")
	return names


class RetentionAuditContractAAA(unittest.TestCase):
	def test_retention_delete_routes_through_audited_trash(self) -> None:
		# Arrange
		retention_path = ROOT / "tradehub_core" / "media" / "pipeline" / "storage" / "retention.py"
		trash_path = ROOT / "tradehub_core" / "media" / "trash.py"

		# Act
		original_calls = _call_names(_function(retention_path, "_apply_original"))
		derivative_calls = _call_names(_function(retention_path, "_apply_derivative"))
		soft_delete_calls = _call_names(_function(trash_path, "move_to_trash"))
		permanent_delete_calls = _call_names(_function(trash_path, "delete_permanently"))

		# Assert
		self.assertIn("trash.move_to_trash", original_calls)
		self.assertIn("trash.move_to_trash", derivative_calls)
		self.assertIn("audit.log_media_event", soft_delete_calls)
		self.assertIn("audit.log_media_event", permanent_delete_calls)


if __name__ == "__main__":
	unittest.main(verbosity=2)
