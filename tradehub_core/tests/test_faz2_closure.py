"""Faz 2 (T-020…T-029) otomatik kapanış kapıları.

İnsan işi olan iki sonucu bilerek başarı saymaz:

* T-025 yanlış-pozitif oranı insan etiketleri olmadan ölçülmüş değildir.
* T-029 onay/imza alanlarını bir test dolduramaz.

Diğer şartname çıktıları burada tek komutla doğrulanır.
"""

from __future__ import annotations

import inspect
import json
import re
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator

from tradehub_core.media import engine
from tradehub_core.media.pipeline import policy

ROOT = Path(__file__).resolve().parents[2]
POLICY_ROOT = ROOT / "tradehub_core" / "media" / "pipeline" / "policy"
SLOT_ROOT = POLICY_ROOT / "slots"
STANDARDS = ROOT / "docs" / "standards"


def _load(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


def _null_encoder_qualities(value: object, path: str = "$") -> list[str]:
	"""Yalnız `encoder_quality` altındaki null değerleri bul."""
	bulgular: list[str] = []
	if isinstance(value, dict):
		for key, child in value.items():
			yol = f"{path}.{key}"
			if key == "encoder_quality" and isinstance(child, dict):
				bulgular.extend(f"{yol}.{fmt}" for fmt, quality in child.items() if quality is None)
			bulgular.extend(_null_encoder_qualities(child, yol))
	elif isinstance(value, list):
		for index, child in enumerate(value):
			bulgular.extend(_null_encoder_qualities(child, f"{path}[{index}]") )
	return bulgular


class Faz2PolitikaKapisiTesti(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		cls.schema = _load(POLICY_ROOT / "schema" / "slot-policy.schema.json")
		Draft202012Validator.check_schema(cls.schema)
		cls.validator = Draft202012Validator(cls.schema)
		cls.files = sorted(SLOT_ROOT.glob("*.json"))
		cls.policies = [_load(path) for path in cls.files]

	def test_dokuz_kanonik_slot_var(self):
		self.assertEqual(len(self.files), 9)
		self.assertEqual(len({item["slot_key"] for item in self.policies}), 9)
		self.assertEqual(policy.SLOT_DIR, SLOT_ROOT)
		self.assertEqual(
			policy.CANONICAL_POLICY_SET,
			"tradehub_core.media.pipeline.policy.slots",
		)
		self.assertIn("docs/standards/policies", policy.DOCUMENTATION_PROJECTION_GLOB)

	def test_tum_politikalar_draft_2020_12_semasina_uyar(self):
		hatalar: list[str] = []
		for path, item in zip(self.files, self.policies):  # noqa: B905 — Python 3.9 yerel koşum uyumu
			for error in self.validator.iter_errors(item):
				hatalar.append(f"{path.name}:{list(error.path)}: {error.message}")
		self.assertEqual(hatalar, [])

	def test_standartlar_sabit_ve_acik_sorusuz(self):
		for item in self.policies:
			with self.subTest(slot=item["slot_key"]):
				self.assertEqual(item["standard_status"], "fixed")
				self.assertEqual(item.get("open_questions"), [])
				self.assertIn(item.get("status"), {"draft", "active", "deprecated"})

	def test_her_slot_gercek_uyum_olcumu_tasir(self):
		for item in self.policies:
			with self.subTest(slot=item["slot_key"]):
				m = item["compliance_measured"]
				toplam = m["compatible_count"] + m["incompatible_count"] + m["unmeasured_count"]
				self.assertEqual(toplam, m["sample_size"])
				beklenen = m["incompatible_count"] / m["sample_size"] if m["sample_size"] else 0.0
				self.assertAlmostEqual(m["violation_rate"], beklenen, delta=0.001)
				self.assertIn(m["enforcement_mode"], {"legacy_and_new", "new_uploads_only", "shadow"})

	def test_encoder_quality_null_degil(self):
		bulgular: list[str] = []
		for item in self.policies:
			bulgular.extend(
				f"{item['slot_key']}:{path}" for path in _null_encoder_qualities(item)
			)
		self.assertEqual(bulgular, [])

	def test_urun_master_ve_garanti_webp_tavani_tutarli(self):
		urun = next(item for item in self.policies if item["slot_key"] == "product.image")
		self.assertGreaterEqual(urun["master"]["min_long_edge"], 2000)
		self.assertEqual(urun["master"]["max_long_edge"], 2400)
		self.assertEqual(inspect.signature(engine.to_webp).parameters["max_dim"].default, 2400)


class Faz2BelgeVeInsanKapisiTesti(unittest.TestCase):
	def test_standartlarda_baglayici_tbd_yok(self):
		bulgular: list[str] = []
		for path in sorted(STANDARDS.rglob("*")):
			if path.suffix.lower() not in {".md", ".json"}:
				continue
			for no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
				if re.search(r"\bTBD\b|BELİRLENECEK", line, flags=re.IGNORECASE):
					bulgular.append(f"{path.relative_to(ROOT)}:{no}")
		self.assertEqual(bulgular, [])

	def test_t025_insan_etiketi_olmadan_kalibre_edildi_demez(self):
		doc = _load(POLICY_ROOT / "content_rules.json")
		self.assertEqual(doc["calibration_status"], "TRIGGER_RATE_MEASURED_UNLABELED")
		self.assertIsNone(doc.get("calibration"))
		red_kurallari = {rule["id"] for rule in doc["rules"] if rule["action"] == "reject"}
		self.assertEqual(red_kurallari, {"nsfw_content", "extreme_blur"})
		self.assertEqual(
			set(doc["decision_model"]["reject_allowed_rules"]),
			{"nsfw_content", "extreme_blur"},
		)

	def test_retention_ve_kota_semalari_gecerli(self):
		for name in ("retention.schema.json", "quota.schema.json"):
			with self.subTest(schema=name):
				Draft202012Validator.check_schema(_load(POLICY_ROOT / name))

	def test_migration_ciktilari_var(self):
		for rel in (
			"docs/plans/migration.md",
			"scripts/plan_backfill.py",
			"tradehub_core/tests/test_migration_backfill.py",
		):
			with self.subTest(path=rel):
				self.assertTrue((ROOT / rel).is_file())

	def test_srs_guncel_ama_imzasizdir(self):
		metin = (ROOT / "docs" / "srs" / "SRS-v1.0.md").read_text(encoding="utf-8")
		self.assertIn("Revizyon 4 — 2026-08-23", metin)
		self.assertIn("TASLAK — yalnız iki insan kapısı açık", metin)
		self.assertIn("☐", metin, "gerçek kişi onayları hâlâ boş görünmeli")

	def test_kapanis_tablosu_insan_kapilarini_done_gostermez(self):
		metin = (ROOT / "docs" / "closure" / "faz2-kapanis.md").read_text(encoding="utf-8")
		self.assertRegex(metin, r"\| T-025 .*\| ◐ \| Hayır \|")
		self.assertRegex(metin, r"\| T-029 .*\| ◐ \| Hayır \|")


if __name__ == "__main__":
	unittest.main()
