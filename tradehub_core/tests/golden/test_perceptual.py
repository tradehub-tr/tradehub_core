"""T-067 · Rendition perceptual golden'ları ve yan-yana fark artefaktı."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any

from tradehub_core.media.pipeline.image import render as image_render
from tradehub_core.tests.golden.perceptual_artifacts import (
	ARTIFACT_MANIFEST_MEMBER,
	FIXED_ZIP_TIMESTAMP,
	PREVIEW_SIZE,
	deterministic_zip_bytes,
	golden_contract_sha256,
	preview_member,
	rendition_preview,
)

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
GOLDEN_PATH = Path(__file__).with_name("perceptual-hashes.json")
ARCHIVE_PATH = Path(__file__).with_name("perceptual-images.zip")
NIGHTLY = os.environ.get("FAZ6_NIGHTLY") == "1"
PR_REPRESENTATIVES = frozenset({"bound_short1000.jpg", "logo_alpha_512.png", "ok_avatar_96.png"})


def _json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def _dhash(content: bytes) -> str:
	from PIL import Image

	with Image.open(io.BytesIO(content)) as image:
		gray = image.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
		pixels = list(gray.getdata())
	bits = "".join(
		"1" if pixels[y * 9 + x] > pixels[y * 9 + x + 1] else "0" for y in range(8) for x in range(8)
	)
	return f"{int(bits, 2):016x}"


def _distance(left: str, right: str) -> int:
	return bin(int(left, 16) ^ int(right, 16)).count("1")


def _write_diff(
	output_dir: Path,
	fixture: str,
	profile: str,
	expected_preview: bytes,
	actual_preview: bytes,
) -> Path:
	from PIL import Image, ImageDraw

	output_dir.mkdir(parents=True, exist_ok=True)
	with Image.open(io.BytesIO(expected_preview)) as expected_image:
		left = expected_image.convert("RGB")
	with Image.open(io.BytesIO(actual_preview)) as actual_image:
		right = actual_image.convert("RGB")
	header = 28
	gap = 12
	canvas = Image.new("RGB", (left.width + gap + right.width, header + max(left.height, right.height)), "#d1d5db")
	draw = ImageDraw.Draw(canvas)
	draw.text((4, 7), "EXPECTED RENDITION", fill="black")
	draw.text((left.width + gap + 4, 7), "CURRENT RENDITION", fill="black")
	canvas.paste(left, (0, header))
	canvas.paste(right, (left.width + gap, header))
	path = output_dir / f"{Path(fixture).stem}-{profile}-diff.png"
	canvas.save(path, "PNG")
	return path


def _actual_rows(row: dict[str, Any]) -> list[list[Any]]:
	path = ROOT / row["file"]
	results = image_render.render_ladder(path.read_bytes(), row["slot"])
	return [
		[
			result.profile.name,
			result.format,
			result.width,
			result.height,
			_dhash(result.content),
			result.content,
		]
		for result in results
	]


class PerceptualGoldenAAA(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.manifest = _json(MANIFEST_PATH)
		cls.golden = _json(GOLDEN_PATH)
		cls.rows = {Path(row["file"]).name: row for row in cls.manifest["fixtures"]}
		cls.archive = zipfile.ZipFile(ARCHIVE_PATH)

	@classmethod
	def tearDownClass(cls) -> None:
		cls.archive.close()

	def _assert_fixtures(self, fixtures: set[str]) -> None:
		limit = int(self.golden["max_hamming_distance"])
		failures: list[str] = []
		artifacts: list[Path] = []
		output_dir = Path(
			os.environ.get("FAZ6_DIFF_DIR") or Path(tempfile.gettempdir()) / "tradehub-faz6-perceptual-diffs"
		)
		for fixture in sorted(fixtures):
			# Arrange
			expected_rows = self.golden["fixtures"][fixture]

			# Act
			actual_rows = _actual_rows(self.rows[fixture])

			# Assert
			expected_meta = [row[:4] for row in expected_rows]
			actual_meta = [row[:4] for row in actual_rows]
			if actual_meta != expected_meta:
				failures.append(f"{fixture}: rendition matrisi değişti")
				continue
			# Matris eşitliği yukarıda uzunluğu da doğrular; indeksleme Python 3.9
			# test ortamında `zip(strict=True)` gerektirmeden birebir eşler.
			for index, expected in enumerate(expected_rows):
				actual = actual_rows[index]
				distance = _distance(expected[4], actual[4])
				if distance <= limit:
					continue
				failures.append(f"{fixture}/{expected[0]}: dHash mesafesi {distance} > {limit}")
				expected_preview = self.archive.read(preview_member(fixture, expected))
				actual_preview = rendition_preview(actual[5])
				artifacts.append(_write_diff(output_dir, fixture, expected[0], expected_preview, actual_preview))
		if failures:
			report = output_dir / "diff-report.md"
			lines = ["# Faz 6 perceptual fark raporu", "", *[f"- {item}" for item in failures]]
			if artifacts:
				lines.extend(["", "## Yan yana beklenen/güncel rendition görselleri", ""])
				lines.extend(f"- [{path.name}]({path.name})" for path in artifacts)
			report.write_text("\n".join(lines) + "\n", encoding="utf-8")
		self.assertEqual(failures, [], f"Fark artefaktları: {output_dir}")

	def test_golden_covers_every_fixture_that_produces_image_renditions(self) -> None:
		# Arrange
		processable = {
			Path(row["file"]).name
			for row in self.manifest["fixtures"]
			if row["expected_action"] == "process" and row["class"] != "video"
		}

		# Act
		golden_fixtures = set(self.golden["fixtures"])

		# Assert
		self.assertEqual(self.golden["manifest_fixture_count"], 57)
		self.assertEqual(self.golden["generated_fixture_count"], len(processable))
		self.assertEqual(golden_fixtures, processable)
		self.assertTrue(all(self.golden["fixtures"].values()))

	def test_golden_is_bound_to_the_current_render_engine(self) -> None:
		# Arrange / Act / Assert
		self.assertEqual(self.golden["engine_id"], image_render.ENGINE_ID)
		self.assertEqual(self.golden["engine_version"], image_render.ENGINE_VERSION)

	def test_expected_image_archive_is_deterministic_and_bound_to_both_manifests(self) -> None:
		archive_contract = self.golden["preview_archive"]
		self.assertEqual(hashlib.sha256(ARCHIVE_PATH.read_bytes()).hexdigest(), archive_contract["sha256"])

		infos = self.archive.infolist()
		names = [info.filename for info in infos]
		self.assertEqual(names, sorted(names))
		self.assertEqual(len(names), len(set(names)))
		self.assertTrue(all(info.date_time == FIXED_ZIP_TIMESTAMP for info in infos))
		self.assertTrue(all(info.compress_type == zipfile.ZIP_STORED for info in infos))

		artifact = json.loads(self.archive.read(ARTIFACT_MANIFEST_MEMBER))
		self.assertEqual(artifact["golden_contract_sha256"], golden_contract_sha256(self.golden))
		self.assertEqual(artifact["fixture_manifest_sha256"], hashlib.sha256(MANIFEST_PATH.read_bytes()).hexdigest())
		expected_members = {
			preview_member(fixture, row)
			for fixture, rows in self.golden["fixtures"].items()
			for row in rows
		}
		self.assertEqual({record["member"] for record in artifact["entries"]}, expected_members)
		self.assertEqual(set(names), expected_members | {ARTIFACT_MANIFEST_MEMBER})
		golden_by_member = {
			preview_member(fixture, row): row
			for fixture, rows in self.golden["fixtures"].items()
			for row in rows
		}
		for record in artifact["entries"]:
			expected_row = golden_by_member[record["member"]]
			self.assertEqual(record["golden_dhash"], expected_row[4])
			self.assertLessEqual(
				_distance(record["golden_dhash"], record["generation_dhash"]),
				int(self.golden["max_hamming_distance"]),
			)
			content = self.archive.read(record["member"])
			self.assertEqual(hashlib.sha256(content).hexdigest(), record["preview_sha256"])
			from PIL import Image

			with Image.open(io.BytesIO(content)) as image:
				self.assertEqual(image.size, PREVIEW_SIZE)

	def test_zip_writer_is_byte_for_byte_deterministic(self) -> None:
		entries = {"z.webp": b"last", "a.webp": b"first"}
		first = deterministic_zip_bytes(entries)
		second = deterministic_zip_bytes(dict(reversed(list(entries.items()))))
		self.assertEqual(first, second)
		with zipfile.ZipFile(io.BytesIO(first)) as archive:
			self.assertEqual(archive.namelist(), ["a.webp", "z.webp"])

	def test_pr_representatives_match_perceptual_golden(self) -> None:
		self._assert_fixtures(set(PR_REPRESENTATIVES))

	if NIGHTLY:

		def test_every_generated_rendition_matches_perceptual_golden(self) -> None:
			"""Ağır matris yalnız nightly'de kaydolur; PR koşusunda sahte skip üretmez."""
			self._assert_fixtures(set(self.golden["fixtures"]))

	def test_mismatch_writer_creates_a_side_by_side_png(self) -> None:
		# Arrange
		with tempfile.TemporaryDirectory() as temp_dir:
			from PIL import Image

			expected = io.BytesIO()
			actual = io.BytesIO()
			Image.new("RGB", (64, 64), "#ef4444").save(expected, "PNG")
			Image.new("RGB", (64, 64), "#2563eb").save(actual, "PNG")
			# Act
			path = _write_diff(
				Path(temp_dir),
				"fixture.jpg",
				"w640",
				rendition_preview(expected.getvalue()),
				rendition_preview(actual.getvalue()),
			)

			# Assert
			with Image.open(path) as image:
				self.assertGreater(image.width, image.height)
				self.assertEqual(image.format, "PNG")
				left = image.getpixel((PREVIEW_SIZE[0] // 2, 28 + PREVIEW_SIZE[1] // 2))
				right = image.getpixel((PREVIEW_SIZE[0] + 12 + PREVIEW_SIZE[0] // 2, 28 + PREVIEW_SIZE[1] // 2))
				self.assertGreater(left[0], left[2], "expected panel must contain the red rendition")
				self.assertGreater(right[2], right[0], "current panel must contain the blue rendition")


if __name__ == "__main__":
	unittest.main(verbosity=2)
