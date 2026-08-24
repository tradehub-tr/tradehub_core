"""Regenerate T-067 expected rendition previews after an intentional golden change.

Run with the same pinned Pillow/runtime used by ``faz6-image-engine.yml``::

    python -m tradehub_core.tests.golden.generate_perceptual_images

The command refuses to bless a render change: current rendition metadata must
match and every dHash must remain inside the reviewed distance budget in
``perceptual-hashes.json``. The printed ZIP SHA-256 must then be reviewed and
recorded in that JSON file.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from tradehub_core.media.pipeline.image import render as image_render
from tradehub_core.tests.golden.perceptual_artifacts import (
	ARTIFACT_MANIFEST_MEMBER,
	PREVIEW_SIZE,
	canonical_json_bytes,
	deterministic_zip_bytes,
	golden_contract_sha256,
	preview_member,
	rendition_preview,
)
from tradehub_core.tests.golden.test_perceptual import _dhash

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
GOLDEN_PATH = Path(__file__).with_name("perceptual-hashes.json")
ARCHIVE_PATH = Path(__file__).with_name("perceptual-images.zip")


def _json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def generate(output_path: Path = ARCHIVE_PATH) -> tuple[str, int]:
	manifest = _json(MANIFEST_PATH)
	golden = _json(GOLDEN_PATH)
	manifest_rows = {Path(row["file"]).name: row for row in manifest["fixtures"]}
	entries: dict[str, bytes] = {}
	records: list[dict[str, Any]] = []

	for fixture in sorted(golden["fixtures"]):
		row = manifest_rows.get(fixture)
		if row is None:
			raise RuntimeError(f"golden fixture is absent from manifest: {fixture}")
		results = image_render.render_ladder((ROOT / row["file"]).read_bytes(), row["slot"])
		actual = [
			[result.profile.name, result.format, result.width, result.height, _dhash(result.content)]
			for result in results
		]
		expected = golden["fixtures"][fixture]
		if [row[:4] for row in actual] != [row[:4] for row in expected]:
			raise RuntimeError(f"refusing to bless changed rendition matrix: {fixture}")
		limit = int(golden["max_hamming_distance"])
	for expected_row, actual_row in zip(expected, actual, strict=True):
			distance = (int(expected_row[4], 16) ^ int(actual_row[4], 16)).bit_count()
			if distance > limit:
				raise RuntimeError(
					f"refusing to bless changed rendition: {fixture}/{expected_row[0]} "
					f"dHash distance {distance} > {limit}"
				)

	for expected_row, actual_row, result in zip(
		expected, actual, results, strict=True
	):
			member = preview_member(fixture, expected_row)
			if member in entries:
				raise RuntimeError(f"duplicate archive member: {member}")
			preview = rendition_preview(result.content)
			entries[member] = preview
			records.append(
				{
					"fixture": fixture,
					"profile": expected_row[0],
					"format": expected_row[1],
					"width": expected_row[2],
					"height": expected_row[3],
					"golden_dhash": expected_row[4],
					"generation_dhash": actual_row[4],
					"member": member,
					"preview_sha256": hashlib.sha256(preview).hexdigest(),
				}
			)

	artifact_manifest = {
		"schema_version": "1.0.0",
		"preview_codec": "WebP/Pillow-quality88-method6",
		"preview_size": list(PREVIEW_SIZE),
		"golden_contract_sha256": golden_contract_sha256(golden),
		"fixture_manifest_sha256": hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest(),
		"entry_count": len(records),
		"entries": sorted(records, key=lambda record: record["member"]),
	}
	entries[ARTIFACT_MANIFEST_MEMBER] = canonical_json_bytes(artifact_manifest)
	archive_bytes = deterministic_zip_bytes(entries)
	output_path.write_bytes(archive_bytes)
	return hashlib.sha256(archive_bytes).hexdigest(), len(records)


if __name__ == "__main__":
	digest, count = generate()
	print(f"{ARCHIVE_PATH}: {count} previews; sha256={digest}")
