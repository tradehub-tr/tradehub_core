#!/usr/bin/env python3
"""120 gerçek medya HTTP ucunun deterministik Postman koleksiyonu (T-085).

Kaynak ``openapi-http.yaml``ın ELLE ayrıştırılmış bir kopyası değildir. Aynı
üreticinin ``build_document()`` çıktısını okur; böylece yeni whitelist ucu
eklendiğinde koleksiyonun ``--check`` kapısı da kırılır.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "api" / "collection" / "media-engine.postman_collection.json"
GENERATOR = ROOT / "scripts" / "gen_http_openapi.py"


def _http_document() -> dict[str, Any]:
	spec = importlib.util.spec_from_file_location("tradehub_http_openapi", GENERATOR)
	if not spec or not spec.loader:
		raise RuntimeError(f"üretici yüklenemedi: {GENERATOR}")
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module.build_document()


def _example(param: dict[str, Any]) -> Any:
	name = str(param.get("name") or "")
	schema = param.get("schema") or {}
	if "example" in schema:
		return schema["example"]
	if schema.get("examples"):
		return schema["examples"][0]
	if "default" in schema:
		return schema["default"]
	variables = {
		"listing": "{{listing}}",
		"listings": '["{{listing}}"]',
		"asset": "{{asset}}",
		"file_url": "{{fileUrl}}",
		"file_urls": '["{{fileUrl}}"]',
		"upload_id": "{{uploadId}}",
		"idempotency_key": "{{$guid}}",
		"content_sha256": "{{contentSha256}}",
		"sha256": "{{contentSha256}}",
		"file_name": "example.jpg",
		"content": "{{base64Content}}",
		"slot": "product.image",
		"slot_key": "product.image",
		"folder": "{{folder}}",
	}
	if name in variables:
		return variables[name]
	type_name = schema.get("type")
	if type_name == "integer":
		return int(schema.get("minimum") or 1)
	if type_name == "number":
		return float(schema.get("minimum") or 0.5)
	if type_name == "boolean":
		return False
	if type_name == "object":
		return {}
	return f"{{{{{name}}}}}"


def _request(path: str, method: str, operation: dict[str, Any], guest: bool) -> dict[str, Any]:
	query: list[dict[str, Any]] = []
	body: dict[str, Any] = {}
	headers = [{"key": "Accept", "value": "application/json", "type": "text"}]
	for param in operation.get("parameters") or ():
		location = param.get("in")
		name = str(param.get("name") or "")
		value = _example(param)
		if location == "header":
			headers.append({"key": name, "value": str(value), "type": "text"})
		elif method == "post":
			body[name] = value
		else:
			query.append(
				{
					"key": name,
					"value": str(value).lower() if isinstance(value, bool) else str(value),
					"disabled": not bool(param.get("required")),
				}
			)
	if not guest:
		headers.append(
			{
				"key": "Authorization",
				"value": "token {{apiKey}}:{{apiSecret}}",
				"type": "text",
			}
		)
	url: dict[str, Any] = {
		"raw": f"{{{{baseUrl}}}}{path}",
		"host": ["{{baseUrl}}"],
		"path": path.lstrip("/").split("/"),
	}
	if query:
		url["query"] = query
	request: dict[str, Any] = {
		"method": method.upper(),
		"header": headers,
		"url": url,
		"description": (
			f"{operation.get('description') or operation.get('summary')}\n\n"
			f"Yetki: {operation.get('x-authorization', '')}\n"
			f"Kaynak: {operation.get('x-source', '')}"
		),
	}
	if method == "post":
		request["header"].append({"key": "Content-Type", "value": "application/json", "type": "text"})
		request["body"] = {
			"mode": "raw",
			"raw": json.dumps(body, ensure_ascii=False, indent=2),
			"options": {"raw": {"language": "json"}},
		}
	return {
		"name": f"{method.upper()} · {operation['operationId']}",
		"request": request,
		"event": [
			{
				"listen": "test",
				"script": {
					"type": "text/javascript",
					"exec": [
						"pm.test('5xx yok', function () {",
						"  pm.expect(pm.response.code).to.be.below(500);",
						"});",
					],
				},
			}
		],
	}


def build_collection() -> dict[str, Any]:
	doc = _http_document()
	guest_endpoints = set(doc.get("x-guest-endpoints") or ())
	by_tag: dict[str, list[dict[str, Any]]] = {}
	for path, path_item in sorted(doc["paths"].items()):
		for method, operation in sorted(path_item.items()):
			tag = str((operation.get("tags") or ["other"])[0])
			by_tag.setdefault(tag, []).append(
				_request(path, method, operation, operation["x-python"] in guest_endpoints)
			)
	items = [{"name": tag, "item": by_tag[tag]} for tag in sorted(by_tag)]
	return {
		"info": {
			"name": "İstoç Media Engine API",
			"description": (
				"OpenAPI'den deterministik üretilmiştir. Yıkıcı/admin isteklerde değişkenleri "
				"gerçek hedefe ayarlamadan Send'e basmayın. Her test 5xx yanıtı reddeder."
			),
			"schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
			"version": doc["info"]["version"],
		},
		"variable": [
			{"key": "baseUrl", "value": "http://istoc.localhost"},
			{"key": "apiKey", "value": ""},
			{"key": "apiSecret", "value": ""},
			{"key": "listing", "value": "LST-00560"},
			{"key": "asset", "value": ""},
			{"key": "fileUrl", "value": ""},
			{"key": "folder", "value": ""},
			{"key": "uploadId", "value": ""},
			{"key": "contentSha256", "value": ""},
			{"key": "base64Content", "value": ""},
		],
		"item": items,
		"x-endpoint-count": doc["x-endpoint-count"],
	}


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--check", action="store_true")
	args = parser.parse_args()
	collection = build_collection()
	content = json.dumps(collection, ensure_ascii=False, indent=2, sort_keys=False) + "\n"
	if args.check:
		if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
			print(f"bayat: {OUTPUT}")
			return 1
		print("temiz")
		return 0
	OUTPUT.parent.mkdir(parents=True, exist_ok=True)
	OUTPUT.write_text(content, encoding="utf-8")
	print(f"yazıldı: {OUTPUT} ({collection['x-endpoint-count']} uç)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
