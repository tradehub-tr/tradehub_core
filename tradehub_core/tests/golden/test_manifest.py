"""T-067 · Manifestteki 57 fixture için bütünlük, beklenti ve karar kapısı."""

from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path
from typing import Any

from tradehub_core.media.pipeline.core.probe import probe_file, probe_video_from_ffprobe
from tradehub_core.media.pipeline.policy.engine import PolicyEngine
from tradehub_core.media.pipeline.video import decision as video_decision
from tradehub_core.media.pipeline.video import probe as video_probe

ROOT = Path(__file__).resolve().parents[3]
MANIFEST_PATH = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
EXPECTED_FIXTURES = 57
EXPECTED_ACTIONS = frozenset({"process", "passthrough", "reject"})


def _manifest() -> dict[str, Any]:
	return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
	digest = hashlib.sha256()
	with path.open("rb") as handle:
		for chunk in iter(lambda: handle.read(1024 * 1024), b""):
			digest.update(chunk)
	return digest.hexdigest()


def _measure_image(path: Path, expected: dict[str, Any]) -> dict[str, Any]:
	from PIL import Image

	measured: dict[str, Any] = {
		"bytes": path.stat().st_size,
		"sha256": _sha256(path),
		"magic": path.read_bytes()[:8].hex(),
	}
	try:
		with Image.open(path) as image:
			if "pil_readable" in expected:
				try:
					image.load()
					measured["pil_readable"] = True
				except Exception:
					measured["pil_readable"] = False
			measured.update(
				format=image.format,
				mode=image.mode,
				width=image.width,
				height=image.height,
				megapixels=round(image.width * image.height / 1_000_000, 4),
				animated=bool(getattr(image, "is_animated", False)),
				n_frames=int(getattr(image, "n_frames", 1)),
				has_alpha=image.mode in {"RGBA", "LA", "PA"} or "transparency" in image.info,
				has_icc="icc_profile" in image.info,
				progressive=bool(image.info.get("progressive") or image.info.get("progression")),
			)
			dpi = image.info.get("dpi")
			if dpi:
				measured["dpi"] = [round(float(dpi[0])), round(float(dpi[1]))]
			try:
				exif = image.getexif()
				if exif:
					if 0x0112 in exif:
						measured["exif_orientation"] = int(exif[0x0112])
					measured["has_gps"] = bool(exif.get_ifd(0x8825))
			except Exception:
				pass
	except Exception:
		measured["pil_readable"] = False
	return measured


def _measure_video(path: Path) -> dict[str, Any]:
	facts = video_probe.probe(str(path))
	if not facts.measured:
		raise AssertionError(f"ffprobe ölçemedi: {path.name}: {facts.error}")
	decision = video_decision.decide(facts)
	return {
		"bytes": facts.size_bytes,
		"sha256": _sha256(path),
		"width": facts.width,
		"height": facts.height,
		"duration_s": facts.duration_s,
		"has_audio": facts.has_audio,
		"needs_transcode": decision.writes_new_file,
	}


def _recorded_video_facts(fixture: dict[str, Any], path: Path) -> video_probe.VideoFacts:
	"""ffprobe olmayan PR ortamında manifest ölçümünü karar tablosuna taşır."""
	measured = fixture.get("olculen") or {}
	duration = float(measured.get("duration_s") or 0.0)
	format_bitrate = int(measured.get("bitrate_kbps") or 0) * 1000
	video_bitrate = int(measured.get("video_bitrate_kbps") or 0) * 1000
	audio_bitrate = int(measured.get("audio_bitrate_kbps") or 0) * 1000
	container = str(measured.get("container") or "")
	return video_probe.VideoFacts(
		path=str(path),
		size_bytes=path.stat().st_size,
		measured=True,
		has_video=True,
		width=int(measured.get("width") or 0),
		height=int(measured.get("height") or 0),
		duration_s=duration,
		fps=video_probe.parse_frame_rate(str(measured.get("fps") or "")),
		video_codec=str(measured.get("video_codec") or ""),
		pix_fmt=str(measured.get("pix_fmt") or ""),
		video_bitrate_bps=video_bitrate,
		format_bitrate_bps=format_bitrate,
		container=container,
		container_family=video_probe.container_family_of(container),
		nb_streams=2 if measured.get("has_audio") else 1,
		moov_at_end=video_probe.moov_at_end_of(str(path)),
		has_audio=bool(measured.get("has_audio")),
		audio_codec=str(measured.get("audio_codec") or ""),
		audio_bitrate_bps=audio_bitrate,
	)


def _assert_expect(test: unittest.TestCase, expected: dict[str, Any], measured: dict[str, Any]) -> None:
	for field, wanted in expected.items():
		if field == "bytes_max":
			test.assertLessEqual(measured["bytes"], wanted)
		elif field == "magic":
			test.assertTrue(measured["magic"].startswith(str(wanted).lower()))
		elif field in {"megapixels", "duration_s"}:
			test.assertAlmostEqual(float(measured[field]), float(wanted), delta=0.02)
		else:
			test.assertIn(field, measured, f"{field} ölçülemedi")
			test.assertEqual(measured[field], wanted, field)


class ManifestGoldenAAA(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.manifest = _manifest()
		cls.engine = PolicyEngine()

	def _policy_action(self, fixture: dict[str, Any], path: Path) -> str:
		slot = fixture["slot"]
		roles = self.engine.registry.get(slot).get("roles") or ["admin"]
		probe = (
			probe_video_from_ffprobe(fixture.get("olculen") or {}, filename=path.name)
			if fixture["class"] == "video"
			else probe_file(path)
		)
		decision = self.engine.evaluate(slot, probe, role=roles[0])
		if not decision.allow:
			return "reject"
		if fixture["class"] != "video":
			return "process"
		facts = (
			video_probe.probe(str(path))
			if video_probe.ffprobe_available()
			else _recorded_video_facts(fixture, path)
		)
		video_result = video_decision.decide(facts)
		if video_result.rejected:
			return "reject"
		return "process" if video_result.writes_new_file else "passthrough"

	def test_manifest_summary_is_the_57_fixture_source_of_truth(self) -> None:
		# Arrange
		fixtures = self.manifest["fixtures"]

		# Act
		files = [fixture["file"] for fixture in fixtures]

		# Assert
		self.assertEqual(len(fixtures), EXPECTED_FIXTURES)
		self.assertEqual(self.manifest["ozet"]["fixture_sayisi"], EXPECTED_FIXTURES)
		self.assertEqual(self.manifest["ozet"]["gecti"], EXPECTED_FIXTURES)
		self.assertEqual(self.manifest["ozet"]["kaldi"], 0)
		self.assertEqual(len(files), len(set(files)), "manifestte aynı fixture iki kez kayıtlı")
		self.assertEqual({row["expected_action"] for row in fixtures}, EXPECTED_ACTIONS)

	def test_every_fixture_exists_and_matches_recorded_hash(self) -> None:
		for fixture in self.manifest["fixtures"]:
			# Arrange
			path = ROOT / fixture["file"]

			# Act
			digest = _sha256(path) if path.is_file() else None

			# Assert
			with self.subTest(fixture=path.name):
				self.assertTrue(path.is_file(), f"fixture yok: {path}")
				self.assertEqual(digest, fixture["olculen"]["sha256"])
				self.assertEqual(path.stat().st_size, fixture["olculen"]["bytes"])

	def test_every_image_fixture_matches_declared_constraints(self) -> None:
		for fixture in self.manifest["fixtures"]:
			if fixture["class"] == "video":
				continue
			# Arrange
			path = ROOT / fixture["file"]
			expected = fixture["expect"]

			# Act
			measured = _measure_image(path, expected)

			# Assert
			with self.subTest(fixture=path.name):
				_assert_expect(self, expected, measured)
				self.assertEqual(fixture["dogrulama"], "GEÇTİ")

	def test_every_video_fixture_matches_declared_constraints(self) -> None:
		for fixture in self.manifest["fixtures"]:
			if fixture["class"] != "video":
				continue
			# Arrange
			path = ROOT / fixture["file"]
			expected = fixture["expect"]

			# Act
			if video_probe.ffprobe_available():
				measured = _measure_video(path)
			else:
				facts = _recorded_video_facts(fixture, path)
				decision = video_decision.decide(facts)
				measured = {
					"bytes": path.stat().st_size,
					"sha256": _sha256(path),
					"width": facts.width,
					"height": facts.height,
					"duration_s": facts.duration_s,
					"has_audio": facts.has_audio,
					"needs_transcode": decision.writes_new_file,
				}

			# Assert
			with self.subTest(fixture=path.name):
				_assert_expect(self, expected, measured)
				self.assertEqual(fixture["dogrulama"], "GEÇTİ")

	def test_every_fixture_matches_exact_expected_action(self) -> None:
		mismatches: list[str] = []
		for fixture in self.manifest["fixtures"]:
			# Arrange
			path = ROOT / fixture["file"]
			expected = fixture["expected_action"]

			# Act
			actual = self._policy_action(fixture, path)

			# Assert
			if actual != expected:
				mismatches.append(f"{path.name}: expected={expected}, actual={actual}")
		self.assertEqual(mismatches, [])


if __name__ == "__main__":
	unittest.main(verbosity=2)
