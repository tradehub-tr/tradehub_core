"""T-085 OpenAPI v1 kırıcı-değişiklik kapısının saf testleri."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
	"check_openapi_breaking", ROOT / "scripts" / "check_openapi_breaking.py"
)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def document() -> dict:
	return {
		"info": {"version": "1.0.0"},
		"paths": {
			"/x": {
				"get": {
					"operationId": "getX",
					"parameters": [
						{"name": "q", "in": "query", "required": False, "schema": {"type": "string"}}
					],
					"responses": {"200": {}, "403": {}},
					"security": [{"cookieAuth": []}],
				}
			}
		},
		"components": {
			"schemas": {
				"X": {
					"type": "object",
					"required": ["id"],
					"properties": {
						"id": {"type": "string"},
						"state": {"type": "string", "enum": ["a", "b"]},
					},
				}
			}
		},
	}


class BreakingChangeTest(unittest.TestCase):
	def test_geriye_uyumlu_ekleme_gecer(self):
		old, new = document(), document()
		new["paths"]["/y"] = {"get": {"operationId": "getY", "responses": {"200": {}}}}
		new["components"]["schemas"]["X"]["properties"]["optional"] = {"type": "number"}
		self.assertEqual(checker.breaking_changes(old, new), [])

	def test_uc_kaldirma_yakalanir(self):
		old, new = document(), document()
		del new["paths"]["/x"]
		self.assertIn("uç kaldırıldı: /x", checker.breaking_changes(old, new))

	def test_zorunlu_parametre_ekleme_yakalanir(self):
		old, new = document(), document()
		new["paths"]["/x"]["get"]["parameters"].append(
			{"name": "n", "in": "query", "required": True, "schema": {"type": "integer"}}
		)
		self.assertTrue(any("yeni zorunlu parametre" in x for x in checker.breaking_changes(old, new)))

	def test_alan_kaldirma_ve_enum_daraltma_yakalanir(self):
		old, new = document(), document()
		del new["components"]["schemas"]["X"]["properties"]["id"]
		new["components"]["schemas"]["X"]["properties"]["state"]["enum"] = ["a"]
		findings = checker.breaking_changes(old, new)
		self.assertTrue(any("yanıt alanı kaldırıldı" in x for x in findings))
		self.assertTrue(any("enum daraltıldı" in x for x in findings))

	def test_kimlik_dogrulama_gevsetme_yakalanir(self):
		old, new = document(), document()
		new["paths"]["/x"]["get"]["security"] = []
		self.assertTrue(any("kimlik doğrulama kaldırıldı" in x for x in checker.breaking_changes(old, new)))


if __name__ == "__main__":
	unittest.main()
