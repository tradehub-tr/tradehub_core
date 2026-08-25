from __future__ import annotations

import csv
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("summarize_media_uat", ROOT / "scripts/summarize_media_uat.py")
assert SPEC and SPEC.loader
uat = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = uat
SPEC.loader.exec_module(uat)


class TestMediaUatSummary(unittest.TestCase):
	def setUp(self) -> None:
		self.tempdir = tempfile.TemporaryDirectory()
		self.root = Path(self.tempdir.name)

	def tearDown(self) -> None:
		self.tempdir.cleanup()

	def _sessions(self, participants: int = 10, *, score: str = "1") -> Path:
		path = self.root / "sessions.csv"
		with path.open("w", encoding="utf-8", newline="") as handle:
			writer = csv.DictWriter(handle, fieldnames=uat.SESSION_COLUMNS)
			writer.writeheader()
			for participant in range(1, participants + 1):
				for task_index, task_id in enumerate(uat.TASKS, start=1):
					writer.writerow(
						{
							"participant_code": f"S{participant:02d}",
							"real_seller": "1",
							"consent_recorded": "1",
							"product_count": "5",
							"task_id": task_id,
							"started_at": f"2026-08-24T10:{task_index:02d}:00+03:00",
							"finished_at": f"2026-08-24T10:{task_index:02d}:30+03:00",
							"completed": "1",
							"help_count": "0",
							"rejection_score": score if task_id == "G6" else "",
							"evidence_ref": f"E-{participant:02d}-{task_id}",
							"confusion_note": "",
						}
					)
		return path

	def _findings(self, *, status: str = "closed") -> Path:
		path = self.root / "findings.csv"
		with path.open("w", encoding="utf-8", newline="") as handle:
			writer = csv.DictWriter(handle, fieldnames=uat.FINDING_COLUMNS)
			writer.writeheader()
			writer.writerow(
				{
					"finding_id": "UAT-001",
					"severity": "critical",
					"status": status,
					"owner_code": "TEAM-MEDIA",
					"due_date": "2026-08-31",
					"evidence_ref": "FIX-001" if status == "closed" else "",
					"summary": "Örnek bulgu",
				}
			)
		return path

	def test_on_satici_tam_anlama_ve_kapali_kritik_bulgu_kapiyi_gecer(self) -> None:
		summary = uat.summarize(
			uat.read_sessions(self._sessions()),
			uat.read_findings(self._findings()),
		)

		self.assertTrue(summary["passed"])
		self.assertEqual(summary["participant_count"], 10)
		self.assertEqual(summary["understanding"]["rate"], 1.0)
		self.assertEqual(summary["task_metrics"][0]["median_seconds"], 30.0)

	def test_dokuz_satici_kapiyi_gecemez(self) -> None:
		summary = uat.summarize(
			uat.read_sessions(self._sessions(participants=9)),
			uat.read_findings(self._findings()),
		)

		self.assertFalse(summary["passed"])
		self.assertFalse(summary["gates"]["at_least_10_real_consented_sellers"])

	def test_acik_kritik_bulgu_kapiyi_gecemez(self) -> None:
		summary = uat.summarize(
			uat.read_sessions(self._sessions()),
			uat.read_findings(self._findings(status="open")),
		)

		self.assertFalse(summary["passed"])
		self.assertEqual(summary["findings"]["critical_open"], ["UAT-001"])

	def test_yinelenen_katilimci_gorevi_reddedilir(self) -> None:
		path = self._sessions(participants=1)
		with path.open("a", encoding="utf-8", newline="") as handle:
			writer = csv.DictWriter(handle, fieldnames=uat.SESSION_COLUMNS)
			writer.writerow(
				{
					"participant_code": "S01",
					"real_seller": "1",
					"consent_recorded": "1",
					"product_count": "5",
					"task_id": "G1",
					"started_at": "2026-08-24T11:00:00+03:00",
					"finished_at": "2026-08-24T11:01:00+03:00",
					"completed": "1",
					"help_count": "0",
					"rejection_score": "",
					"evidence_ref": "E-DUP",
					"confusion_note": "",
				}
			)

		with self.assertRaisesRegex(uat.ContractError, "yinelenen"):
			uat.read_sessions(path)

	def test_saat_dilimsiz_zaman_reddedilir(self) -> None:
		path = self._sessions(participants=1)
		text = path.read_text(encoding="utf-8").replace("2026-08-24T10:01:00+03:00", "2026-08-24T10:01:00", 1)
		path.write_text(text, encoding="utf-8")

		with self.assertRaisesRegex(uat.ContractError, "saat dilimi zorunlu"):
			uat.read_sessions(path)


if __name__ == "__main__":
	unittest.main()
