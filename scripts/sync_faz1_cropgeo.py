#!/usr/bin/env python3
"""T-010 kanonik cropgeo vektörünü tek doğruluk kaynağından senkronla.

Kullanım:
    python scripts/sync_faz1_cropgeo.py
    python scripts/sync_faz1_cropgeo.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "tradehub_core" / "tests" / "fixtures" / "crop_vectors.json"
TARGET = ROOT / "tests" / "vectors" / "crop-vectors.json"
MIN_VECTORS = 200


def sha256(path: Path) -> str:
	return hashlib.sha256(path.read_bytes()).hexdigest()


def validate(path: Path) -> dict:
	data = json.loads(path.read_text(encoding="utf-8"))
	vectors = data.get("vectors") or []
	if len(vectors) < MIN_VECTORS:
		raise ValueError(f"vektör sayısı {len(vectors)} < {MIN_VECTORS}")
	if int(data.get("vector_count") or 0) != len(vectors):
		raise ValueError("vector_count ile vectors uzunluğu ayrışmış")
	ids = [str(row.get("id") or "") for row in vectors]
	if not all(ids) or len(ids) != len(set(ids)):
		raise ValueError("vektör id'leri boş veya tekil değil")
	return data


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser()
	parser.add_argument("--check", action="store_true", help="dosya yazma; drift varsa başarısız ol")
	args = parser.parse_args(argv)

	data = validate(SOURCE)
	if args.check:
		if not TARGET.is_file():
			print(f"DRIFT: hedef yok: {TARGET}", file=sys.stderr)
			return 1
		validate(TARGET)
		if SOURCE.read_bytes() != TARGET.read_bytes():
			print(f"DRIFT: {TARGET} kaynakla aynı değil", file=sys.stderr)
			return 1
	else:
		TARGET.parent.mkdir(parents=True, exist_ok=True)
		shutil.copyfile(SOURCE, TARGET)

	print(
		json.dumps(
			{
				"ok": True,
				"vectors": len(data["vectors"]),
				"sha256": sha256(SOURCE),
				"source": str(SOURCE.relative_to(ROOT)),
				"target": str(TARGET.relative_to(ROOT)),
			},
			ensure_ascii=False,
			sort_keys=True,
		)
	)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
