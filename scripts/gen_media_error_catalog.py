#!/usr/bin/env python3
"""Yükleme hata kodu kataloğunu Python kaynağından deterministik üretir.

`upload_policy.py` Frappe içe aktarır; belge üretimi ve CI ise çalışan siteye
bağlanmamalıdır. Bu yüzden dosya AST ile okunur. Kod, yeniden-denenebilirlik ve
`ALL_CODES` sırası yalnız kaynaktan çıkarılır; ikinci bir elle yazılmış liste
yoktur (Faz 8 / T-084).
"""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tradehub_core" / "media" / "upload_policy.py"
OUTPUT = ROOT / "docs" / "api" / "error-catalog.json"


def build_catalog() -> dict[str, Any]:
	tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
	definitions: dict[str, tuple[str, bool]] = {}
	order: list[str] | None = None

	for node in tree.body:
		if not isinstance(node, (ast.Assign, ast.AnnAssign)):
			continue
		targets = node.targets if isinstance(node, ast.Assign) else [node.target]
		value = node.value
		for target in targets:
			if not isinstance(target, ast.Name):
				continue
			if target.id == "ALL_CODES" and isinstance(value, (ast.Tuple, ast.List)):
				order = [item.id for item in value.elts if isinstance(item, ast.Name)]
			elif (
				isinstance(value, ast.Call)
				and isinstance(value.func, ast.Name)
				and value.func.id == "Kod"
				and len(value.args) == 2
			):
				code = ast.literal_eval(value.args[0])
				retryable = ast.literal_eval(value.args[1])
				if isinstance(code, str) and isinstance(retryable, bool):
					definitions[target.id] = (code, retryable)

	if not order:
		raise RuntimeError("ALL_CODES bulunamadı ya da boş")
	missing = [name for name in order if name not in definitions]
	if missing:
		raise RuntimeError(f"Kod tanımı bulunamadı: {missing}")

	codes = [
		{
			"code": definitions[name][0],
			"retryable": definitions[name][1],
			"http_status": 417,
			"i18n_key": f"media.upload.err.{definitions[name][0]}",
		}
		for name in order
	]
	values = [entry["code"] for entry in codes]
	if len(values) != len(set(values)):
		raise RuntimeError("Tekrarlı hata kodu var")

	return {
		"schema_version": "1.0.0",
		"generated_from": "tradehub_core/media/upload_policy.py::ALL_CODES",
		"error_envelope": {
			"field": "upload_error",
			"fallback_marker": "[<code>]",
			"note": "Karar metne değil koda bakar; bilinmeyen kod otomatik yeniden denenmez.",
		},
		"codes": codes,
	}


def render() -> str:
	return json.dumps(build_catalog(), ensure_ascii=False, indent=2) + "\n"


def main() -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--check", action="store_true")
	args = parser.parse_args()
	content = render()
	if args.check:
		if not OUTPUT.is_file() or OUTPUT.read_text(encoding="utf-8") != content:
			print(f"bayat: {OUTPUT}")
			return 1
		print(f"temiz: {len(build_catalog()['codes'])} kod")
		return 0
	OUTPUT.parent.mkdir(parents=True, exist_ok=True)
	OUTPUT.write_text(content, encoding="utf-8")
	print(f"yazıldı: {OUTPUT} ({len(build_catalog()['codes'])} kod)")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
