#!/usr/bin/env python3
"""İki OpenAPI belgesi arasında v1 istemcisini kıran değişiklikleri bulur.

Kapsam bilinçli olarak muhafazakârdır: uç/yöntem/yanıt/alan kaldırma, yeni
zorunlu istek veya yanıt alanı, tip/$ref/oneOf değişimi, enum daraltma ve
kimlik doğrulamayı gevşetme kırıcı sayılır. Aynı MAJOR içinde bulgu CI'ı
kırar; yeni MAJOR öneki/sürümüyle bilinçli geçişe izin verir (T-085).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "options", "head"})


def _major(document: dict[str, Any]) -> int:
	version = str(document.get("info", {}).get("version") or "0")
	try:
		return int(version.split(".", 1)[0])
	except ValueError:
		return 0


def _parameters(path_item: dict[str, Any], operation: dict[str, Any]) -> dict[tuple[str, str], dict]:
	result: dict[tuple[str, str], dict] = {}
	for parameter in [*(path_item.get("parameters") or []), *(operation.get("parameters") or [])]:
		if "$ref" in parameter:
			continue
		result[(str(parameter.get("in")), str(parameter.get("name")))] = parameter
	return result


def _shape(schema: Any) -> str:
	if not isinstance(schema, dict):
		return json.dumps(schema, sort_keys=True)
	interesting = {
		key: schema[key]
		for key in ("$ref", "type", "format", "nullable", "oneOf", "anyOf", "allOf", "items")
		if key in schema
	}
	return json.dumps(interesting, sort_keys=True, separators=(",", ":"))


def _schema_breaks(name: str, old: dict[str, Any], new: dict[str, Any]) -> list[str]:
	findings: list[str] = []
	if _shape(old) != _shape(new):
		findings.append(f"schema tipi değişti: {name}")
	old_props = old.get("properties") or {}
	new_props = new.get("properties") or {}
	for prop in sorted(set(old_props) - set(new_props)):
		findings.append(f"yanıt alanı kaldırıldı: {name}.{prop}")
	for prop in sorted(set(old_props) & set(new_props)):
		if _shape(old_props[prop]) != _shape(new_props[prop]):
			findings.append(f"alan tipi değişti: {name}.{prop}")
		old_enum = set(old_props[prop].get("enum") or [])
		new_enum = set(new_props[prop].get("enum") or [])
		if old_enum - new_enum:
			findings.append(f"enum daraltıldı: {name}.{prop} ({sorted(old_enum - new_enum)!r})")
	for prop in sorted(set(new.get("required") or []) - set(old.get("required") or [])):
		findings.append(f"yeni zorunlu yanıt alanı: {name}.{prop}")
	return findings


def breaking_changes(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
	findings: list[str] = []
	old_paths = old.get("paths") or {}
	new_paths = new.get("paths") or {}
	for path in sorted(set(old_paths) - set(new_paths)):
		findings.append(f"uç kaldırıldı: {path}")
	for path in sorted(set(old_paths) & set(new_paths)):
		old_item, new_item = old_paths[path], new_paths[path]
		old_methods = set(old_item) & HTTP_METHODS
		new_methods = set(new_item) & HTTP_METHODS
		for method in sorted(old_methods - new_methods):
			findings.append(f"yöntem kaldırıldı: {method.upper()} {path}")
		for method in sorted(old_methods & new_methods):
			old_op, new_op = old_item[method], new_item[method]
			label = f"{method.upper()} {path}"
			if old_op.get("operationId") != new_op.get("operationId"):
				findings.append(f"operationId değişti: {label}")
			old_params = _parameters(old_item, old_op)
			new_params = _parameters(new_item, new_op)
			for key in sorted(set(old_params) - set(new_params)):
				findings.append(f"parametre kaldırıldı: {label} {key[0]}:{key[1]}")
			for key in sorted(set(new_params) - set(old_params)):
				if new_params[key].get("required"):
					findings.append(f"yeni zorunlu parametre: {label} {key[0]}:{key[1]}")
			for key in sorted(set(old_params) & set(new_params)):
				if not old_params[key].get("required") and new_params[key].get("required"):
					findings.append(f"parametre zorunlu oldu: {label} {key[0]}:{key[1]}")
				if _shape(old_params[key].get("schema")) != _shape(new_params[key].get("schema")):
					findings.append(f"parametre tipi değişti: {label} {key[0]}:{key[1]}")
			for status in sorted(set(old_op.get("responses") or {}) - set(new_op.get("responses") or {})):
				findings.append(f"yanıt durumu kaldırıldı: {label} {status}")
			if old_op.get("security") and not new_op.get("security"):
				findings.append(f"kimlik doğrulama kaldırıldı: {label}")

	old_schemas = old.get("components", {}).get("schemas", {})
	new_schemas = new.get("components", {}).get("schemas", {})
	for name in sorted(set(old_schemas) - set(new_schemas)):
		findings.append(f"schema kaldırıldı: {name}")
	for name in sorted(set(old_schemas) & set(new_schemas)):
		findings.extend(_schema_breaks(name, old_schemas[name], new_schemas[name]))
	return findings


def _read(path: Path) -> dict[str, Any]:
	try:
		import yaml
	except ImportError as exc:  # pragma: no cover - yalnız CLI bağımlılık ile koşar
		raise SystemExit("PyYAML gerekli: `python -m pip install pyyaml`") from exc
	with path.open(encoding="utf-8") as handle:
		return yaml.safe_load(handle)


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("base", type=Path)
	parser.add_argument("current", type=Path)
	args = parser.parse_args()
	base, current = _read(args.base), _read(args.current)
	findings = breaking_changes(base, current)
	if not findings:
		print("kırıcı değişiklik yok")
		return 0
	for finding in findings:
		print(f"BREAKING: {finding}")
	if _major(current) > _major(base):
		print("Yeni MAJOR sürüm: kırıcı değişiklikler bilinçli geçiş olarak kabul edildi.")
		return 0
	print("Aynı MAJOR sürümde kırıcı değişiklik var.")
	return 1


if __name__ == "__main__":
	raise SystemExit(main())
