"""Repository-level closure guards for G-16 Phase 4 (T-040…T-044)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOCTYPE_ROOT = ROOT / "tradehub_core" / "tradehub_core" / "doctype"

REQUIRED_DOCTYPES = {
	"media_asset",
	"media_source",
	"media_version",
	"media_rendition",
	"media_crop_intent",
	"media_crop_override",
	"media_profile",
	"media_policy",
	"media_policy_profile",
	"media_content_rule",
	"media_processing_job",
	"media_usage",
	"media_quality_report",
	"media_engine_settings",
	"media_storage_settings",
}


def schema(slug: str) -> dict:
	return json.loads((DOCTYPE_ROOT / slug / f"{slug}.json").read_text(encoding="utf-8"))


def fields(slug: str) -> dict[str, dict]:
	return {field["fieldname"]: field for field in schema(slug)["fields"]}


class Phase4SchemaClosureTest(unittest.TestCase):
	def test_official_fifteen_doctypes_are_installed(self) -> None:
		missing = [slug for slug in REQUIRED_DOCTYPES if not (DOCTYPE_ROOT / slug / f"{slug}.json").is_file()]
		self.assertEqual(missing, [])

	def test_policy_children_and_source_constraints(self) -> None:
		self.assertEqual(schema("media_policy_profile").get("istable"), 1)
		self.assertEqual(schema("media_content_rule").get("istable"), 1)
		self.assertEqual(fields("media_source")["asset"].get("unique"), 1)
		self.assertEqual(fields("media_source")["asset"].get("reqd"), 1)
		self.assertEqual(fields("media_asset")["slot_key"].get("options"), "Media Policy")
		self.assertEqual(fields("media_asset")["source"].get("options"), "Media Source")

	def test_source_immutability_ignores_framework_audit_columns(self) -> None:
		controller = (DOCTYPE_ROOT / "media_source" / "media_source.py").read_text(encoding="utf-8")
		self.assertIn("IMMUTABLE_FIELDS", controller)
		self.assertNotIn("self.meta.get_valid_columns()", controller)

	def test_tenant_scoped_sha_uniqueness_is_explicit(self) -> None:
		asset_fields = fields("media_asset")
		self.assertNotEqual(asset_fields["content_sha256"].get("unique"), 1)
		self.assertEqual(asset_fields["asset_key"].get("unique"), 1)
		self.assertIn("owner_seller", asset_fields["asset_key"]["description"])

	def test_both_settings_are_media_superadmin_only(self) -> None:
		for slug in ("media_engine_settings", "media_storage_settings"):
			with self.subTest(slug=slug):
				self.assertEqual({row["role"] for row in schema(slug)["permissions"]}, {"Media Superadmin"})

	def test_hooks_cover_source_and_both_settings(self) -> None:
		hooks = (ROOT / "tradehub_core" / "hooks.py").read_text(encoding="utf-8")
		self.assertIn('"Media Source": "tradehub_core.permissions.media_source_query_conditions"', hooks)
		self.assertIn('"Media Source": "tradehub_core.permissions.media_source_has_permission"', hooks)
		self.assertIn(
			'"Media Engine Settings": "tradehub_core.permissions.media_engine_settings_has_permission"', hooks
		)
		self.assertIn(
			'"Media Storage Settings": "tradehub_core.permissions.media_storage_settings_has_permission"',
			hooks,
		)


class Phase4MigrationClosureTest(unittest.TestCase):
	def test_schema_seed_and_index_patches_are_ordered(self) -> None:
		patches = (ROOT / "tradehub_core" / "patches.txt").read_text(encoding="utf-8")
		seed = "tradehub_core.patches.v15_9_43_media_phase4_schema"
		indexes = "tradehub_core.patches.v15_9_44_media_phase4_indexes"
		self.assertIn(seed, patches)
		self.assertIn(indexes, patches)
		self.assertLess(patches.index(seed), patches.index(indexes))

	def test_clean_install_path_invokes_same_projector(self) -> None:
		install = (ROOT / "tradehub_core" / "setup" / "install.py").read_text(encoding="utf-8")
		self.assertIn("_seed_media_phase4_catalog()", install)
		self.assertIn("v15_9_43_media_phase4_schema", install)
		self.assertIn("v15_9_44_media_phase4_indexes", install)

	def test_critical_index_set_is_declared(self) -> None:
		patch = (ROOT / "tradehub_core" / "patches" / "v15_9_44_media_phase4_indexes.py").read_text(
			encoding="utf-8"
		)
		for index in (
			"ix_seller_state_modified",
			"ix_state_lastaccess",
			"ix_state_hold_creation",
			"uk_rendition_quad",
			"ix_rendition_asset_version",
			"ix_queue_status_modified",
			"ix_job_asset_status",
		):
			self.assertIn(index, patch)
		self.assertIn('("version_hash", "profile", "width", "format")', patch)
		self.assertIn("unique=True", patch)

	def test_seed_covers_every_canonical_policy_file(self) -> None:
		slots = sorted((ROOT / "tradehub_core" / "media" / "pipeline" / "policy" / "slots").glob("*.json"))
		self.assertEqual(len(slots), 10)
		seed_patch = (ROOT / "tradehub_core" / "patches" / "v15_9_43_media_phase4_schema.py").read_text(
			encoding="utf-8"
		)
		self.assertIn('SLOT_DIR.glob("*.json")', seed_patch)


class Phase4EvidenceClosureTest(unittest.TestCase):
	def test_scale_evidence_hits_exact_acceptance_volume(self) -> None:
		evidence = json.loads(
			(ROOT / "docs" / "data" / "faz4-scale-benchmark-2026-08-23.json").read_text(encoding="utf-8")
		)
		self.assertEqual(evidence["exact_counts"]["media_asset"], 1_000_000)
		self.assertEqual(evidence["exact_counts"]["media_rendition"], 30_000_000)
		self.assertEqual(len(evidence["explain_summary"]), 7)
		self.assertTrue(all(plan.get("key") for plan in evidence["explain_summary"].values()))

	def test_benchmark_drop_requires_exact_confirmation(self) -> None:
		script = (ROOT / "scripts" / "seed_synthetic.py").read_text(encoding="utf-8")
		self.assertIn("media_phase4_bench_", script)
		self.assertIn("--confirm-drop", script)
		self.assertIn("confirmation != runner.database", script)

	def test_rollback_plan_records_loss_and_restore_proof(self) -> None:
		plan = (ROOT / "docs" / "plans" / "rollback-doctypes.md").read_text(encoding="utf-8")
		self.assertIn("0 tablo / 0 kolon / 0 indeks", plan)
		self.assertIn("4 tablo / 1 kolon / 7 indeks", plan)
		self.assertIn("6,255 sn", plan)


if __name__ == "__main__":
	unittest.main()
