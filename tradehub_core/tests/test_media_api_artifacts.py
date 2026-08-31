"""Faz 8 üretilmiş API artefaktlarının sapma kapısı (T-084/T-085)."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from tradehub_core.media.pipeline.api import spec as pure_spec

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, path: Path):
	spec = importlib.util.spec_from_file_location(name, path)
	assert spec and spec.loader
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


collection = _load("gen_media_api_collection", ROOT / "scripts" / "gen_media_api_collection.py")
errors = _load("gen_media_error_catalog", ROOT / "scripts" / "gen_media_error_catalog.py")


class ApiArtifactTest(unittest.TestCase):
	def _assert_examples(self, document: dict) -> None:
		for path, path_item in document["paths"].items():
			for method, operation in path_item.items():
				label = f"{method.upper()} {path}"
				for parameter in operation.get("parameters") or ():
					self.assertTrue(
						"example" in parameter or "example" in parameter.get("schema", {}),
						f"{label}: {parameter['name']} istek örneği yok",
					)
				for media in (operation.get("requestBody", {}).get("content") or {}).values():
					self.assertTrue("example" in media or "examples" in media, f"{label}: gövde örneği yok")
				for status, response in operation["responses"].items():
					if not str(status).startswith("2") or "$ref" in response:
						continue
					for media in (response.get("content") or {}).values():
						self.assertTrue(
							"example" in media or "examples" in media,
							f"{label}: {status} yanıt örneği yok",
						)

	def test_iki_openapi_belgesinde_her_istek_ve_yanit_ornekli(self):
		self._assert_examples(collection._http_document())
		self._assert_examples(pure_spec.build_document())

	def test_postman_koleksiyonu_TUM_uclarin_tamamini_tasir(self):
		"""Sayı 120'den 143'e çıktı — koleksiyon diskte bayat kalmıştı.

		`x-endpoint-count` üreteçten geliyor ve zaten tutuyordu; sabit sayı
		güncellenmediği için kapı, uç eklendiğini "hata" diye raporluyordu.
		Sayıyı sabitlemek yine de doğru: 143'ün 0'a düşmesi de sessiz kalmamalı.
		"""
		doc = collection.build_collection()
		items = [item for group in doc["item"] for item in group["item"]]
		self.assertEqual(len(items), doc["x-endpoint-count"])
		self.assertEqual(len(items), 143)
		self.assertEqual(len({item["name"] for item in items}), 143)

	def test_postman_koleksiyonu_diskte_guncel(self):
		expected = json.dumps(collection.build_collection(), ensure_ascii=False, indent=2) + "\n"
		self.assertEqual(collection.OUTPUT.read_text(encoding="utf-8"), expected)

	def test_hata_katalogu_diskte_guncel_ve_tekil(self):
		doc = errors.build_catalog()
		self.assertEqual(errors.OUTPUT.read_text(encoding="utf-8"), errors.render())
		codes = [entry["code"] for entry in doc["codes"]]
		self.assertEqual(len(codes), 24)
		self.assertEqual(len(codes), len(set(codes)))
		self.assertEqual(
			{entry["code"] for entry in doc["codes"] if entry["retryable"]},
			{"upload_chunk_order", "upload_chunk_missing"},
		)


if __name__ == "__main__":
	unittest.main()
