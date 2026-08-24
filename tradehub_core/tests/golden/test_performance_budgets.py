"""T-067 · T-007'den türetilen süre/RSS bütçelerini CI'da uygular."""

from __future__ import annotations

import json
import math
import os
import resource
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
BUDGET_PATH = Path(__file__).with_name("performance-budgets.json")
MANIFEST_PATH = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
NIGHTLY = os.environ.get("FAZ6_NIGHTLY") == "1"
MEASURED_CLASSES = frozenset({"photo", "transparent", "graphic"})


def _peak_rss_mib() -> float:
	"""Return this executable's own peak RSS, not the pre-exec parent peak.

	Linux preserves ``getrusage(RUSAGE_SELF).ru_maxrss`` across ``execve``.
	Because the budget probe is spawned after perceptual tests, that value can
	start at the already-large parent's high-water mark and fabricate a leak.
	``VmHWM`` is reset for the new executable and measures the probe itself.
	"""
	if sys.platform.startswith("linux"):
		for line in Path("/proc/self/status").read_text(encoding="utf-8").splitlines():
			if not line.startswith("VmHWM:"):
				continue
			amount, unit = line.split(":", 1)[1].split()
			if unit.lower() != "kb":
				raise RuntimeError(f"unexpected VmHWM unit: {unit}")
			return int(amount) / 1024.0
		raise RuntimeError("VmHWM is absent from /proc/self/status")

	rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
	return rss / (1024.0 * 1024.0) if sys.platform == "darwin" else rss / 1024.0

_CHILD = textwrap.dedent(
	"""
	import json
	import sys
	import time
	from pathlib import Path

	from tradehub_core.media.pipeline.image.normalize import NormalizeSpec, normalize
	from tradehub_core.tests.golden.test_performance_budgets import _peak_rss_mib

	source = Path(sys.argv[1])
	slot = sys.argv[2]
	policy_dir = Path("tradehub_core/media/pipeline/policy/slots")
	policy = next(
		json.loads(path.read_text(encoding="utf-8"))
		for path in policy_dir.glob("*.json")
		if (
			json.loads(path.read_text(encoding="utf-8")).get("key")
			or json.loads(path.read_text(encoding="utf-8")).get("slot_key")
		) == slot
	)
	spec = NormalizeSpec.from_policy(policy["master"])
	started = time.perf_counter()
	result = normalize(source, spec, filename=source.name)
	elapsed_ms = (time.perf_counter() - started) * 1000.0
	print(json.dumps({"ok": result.ok, "reason": result.reason, "elapsed_ms": elapsed_ms, "peak_rss_mib": _peak_rss_mib()}))
	"""
)


def _json(path: Path) -> dict[str, Any]:
	return json.loads(path.read_text(encoding="utf-8"))


def _measure(path: Path, slot: str) -> dict[str, Any]:
	completed = subprocess.run(
		[sys.executable, "-c", _CHILD, str(path), slot],
		cwd=ROOT,
		check=True,
		capture_output=True,
		text=True,
		timeout=60,
	)
	return json.loads(completed.stdout.strip().splitlines()[-1])


class PerformanceBudgetAAA(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.budgets = _json(BUDGET_PATH)
		cls.manifest = _json(MANIFEST_PATH)

	def test_each_manifest_class_has_an_explicit_budget_or_exclusion(self) -> None:
		# Arrange
		manifest_classes = {row["class"] for row in self.manifest["fixtures"]}
		budget_classes = set(self.budgets["fixture_classes"])

		# Act / Assert
		self.assertEqual(budget_classes, manifest_classes)
		for name, budget in self.budgets["fixture_classes"].items():
			with self.subTest(fixture_class=name):
				if name in MEASURED_CLASSES:
					self.assertIn("normalize_budget_ms", budget)
					self.assertIn("peak_rss_budget_mib", budget)
				else:
					self.assertTrue(budget.get("not_applicable"))

	@unittest.skipUnless(sys.platform.startswith("linux"), "Linux exec RSS semantics only")
	def test_linux_probe_ignores_inherited_exec_high_water_mark(self) -> None:
		# Arrange: a small wrapper deliberately raises its own high-water mark,
		# then execs the same minimal RSS reader used by the real probe.
		script = textwrap.dedent(
			"""
			import json
			import resource
			import subprocess
			import sys

			balloon = bytearray(128 * 1024 * 1024)
			balloon[::4096] = b"x" * (len(balloon) // 4096)
			parent_mib = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
			child_code = (
			    "from tradehub_core.tests.golden.test_performance_budgets "
			    "import _peak_rss_mib; print(_peak_rss_mib())"
			)
			child_mib = float(subprocess.check_output([sys.executable, "-c", child_code], text=True))
			print(json.dumps({"parent_mib": parent_mib, "child_mib": child_mib}))
			"""
		)

		# Act
		completed = subprocess.run(
			[sys.executable, "-c", script],
			cwd=ROOT,
			check=True,
			capture_output=True,
			text=True,
			timeout=30,
		)
		measured = json.loads(completed.stdout.strip().splitlines()[-1])

		# Assert: resource.ru_maxrss would report the inflated parent peak here.
		self.assertGreater(measured["parent_mib"], 120)
		self.assertLess(measured["child_mib"], measured["parent_mib"] / 2)

	def test_t007_limits_are_exactly_baseline_plus_thirty_percent(self) -> None:
		# Arrange
		margin = 1.0 + self.budgets["margin_percent"] / 100.0

		for name in MEASURED_CLASSES:
			# Act
			budget = self.budgets["fixture_classes"][name]
			expected_ms = math.ceil(budget["normalize_baseline_ms"] * margin)
			expected_rss = math.ceil(budget["peak_rss_baseline_mib"] * margin)

			# Assert
			with self.subTest(fixture_class=name):
				self.assertEqual(budget["normalize_budget_ms"], expected_ms)
				self.assertEqual(budget["peak_rss_budget_mib"], expected_rss)

	def test_representative_fixture_in_each_process_class_stays_in_budget(self) -> None:
		# Arrange
		representatives = {
			"photo": "edge_72mp.jpg",
			"transparent": "mode_rgba_alpha.png",
			"graphic": "mode_palette_p.png",
		}
		rows = {Path(row["file"]).name: row for row in self.manifest["fixtures"]}

		for fixture_class, filename in representatives.items():
			row = rows[filename]
			path = ROOT / row["file"]

			# Act
			measured = _measure(path, row["slot"])

			# Assert
			with self.subTest(fixture_class=fixture_class, fixture=filename):
				self.assertTrue(measured["ok"], measured)
				budget = self.budgets["fixture_classes"][fixture_class]
				self.assertLessEqual(measured["elapsed_ms"], budget["normalize_budget_ms"])
				self.assertLessEqual(measured["peak_rss_mib"], budget["peak_rss_budget_mib"])

	if NIGHTLY:

		def test_every_process_image_stays_in_its_class_budget(self) -> None:
			"""Ağır matris yalnız nightly'de kaydolur; PR koşusunda sahte skip üretmez."""
			for row in self.manifest["fixtures"]:
				if row["expected_action"] != "process" or row["class"] not in MEASURED_CLASSES:
					continue
				path = ROOT / row["file"]

				# Act
				measured = _measure(path, row["slot"])

				# Assert
				with self.subTest(fixture=path.name):
					self.assertTrue(measured["ok"], measured)
					budget = self.budgets["fixture_classes"][row["class"]]
					self.assertLessEqual(measured["elapsed_ms"], budget["normalize_budget_ms"])
					self.assertLessEqual(measured["peak_rss_mib"], budget["peak_rss_budget_mib"])

	def test_global_rendition_and_pr_runtime_limits_are_literal(self) -> None:
		# Arrange / Act
		rendition = self.budgets["rendition_batch"]
		pr = self.budgets["pr_regression"]

		# Assert
		self.assertEqual(rendition["count"], 34)
		self.assertEqual(rendition["single_core_budget_ms"], 12_000)
		self.assertEqual(rendition["max_encodes_per_rendition"], 4)
		self.assertEqual(pr["wall_clock_budget_seconds"], 600)


if __name__ == "__main__":
	unittest.main(verbosity=2)
