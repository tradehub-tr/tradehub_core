"""G-16 T-030…T-035 Phase 3 architecture closure gates."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tradehub_core.media.pipeline.contracts import ImageEngine, VideoEngine, signatures
from tradehub_core.media.pipeline.core import queues
from tradehub_core.media.pipeline.image.engine import PillowImageEngine
from tradehub_core.media.pipeline.policy import CANONICAL_POLICY_SET, SLOT_DIR
from tradehub_core.media.pipeline.video.engine import FfmpegVideoEngine

ROOT = Path(__file__).resolve().parents[2]
SAD = ROOT / "docs/sad/SAD-v1.0.md"
INTERFACES = ROOT / "docs/sad/interfaces.md"
CLOSURE = ROOT / "docs/closure/faz3-kapanis.md"
ADR3 = ROOT / "docs/adr/0003-ayri-app-degil-tek-monolit.md"
ADR4 = ROOT / "docs/adr/0004-saf-cekirdek-frappe-kabugu.md"
WORKFLOW = ROOT / ".github/workflows/faz3-architecture.yml"
DEPLOY = ROOT / "deploy/media-workers.compose.yml"


class Faz3ClosureTest(unittest.TestCase):
	def test_t030_sad_tum_mimari_ciktilarini_tasir(self):
		text = SAD.read_text(encoding="utf-8")
		for section in (
			"## 3. C4 diyagramları",
			"## 4. Bileşen sorumluluk tablosu",
			"## 5. Akış diyagramları",
			"## 6. Durum makinesi",
			"## 8. SPOF analizi",
			"### 14.7 Teknik kapanış — 2026-08-23",
		):
			self.assertIn(section, text)
		self.assertIn("ADR-0003, ADR-0004", text)
		self.assertIn("PillowImageEngine", text)
		self.assertIn("FfmpegVideoEngine", text)

	def test_t031_bes_protokolun_golden_imzasi_guncel(self):
		self.assertTrue(signatures.golden_guncel_mi())
		self.assertEqual(
			set(signatures.oku_golden()["protocols"]),
			{"DeliveryManifest", "ImageEngine", "PolicyEngine", "StorageAdapter", "VideoEngine"},
		)
		self.assertIn("DONDURULMUŞ (v1.0)", INTERFACES.read_text(encoding="utf-8"))

	def test_t031_uretim_image_video_adaptorleri_protokole_uyar(self):
		self.assertIsInstance(PillowImageEngine(), ImageEngine)
		self.assertIsInstance(FfmpegVideoEngine(), VideoEngine)

	def test_t032_ayri_app_sapmasi_adr_ile_kabul_edilmis(self):
		adr = ADR3.read_text(encoding="utf-8")
		self.assertIn("Kabul edildi · uygulamayla hizalı", adr)
		self.assertIn("app içi saf alt paket", adr)
		self.assertNotIn("uygulaması karardan saptı", adr)
		self.assertIn("testle kilitli", ADR4.read_text(encoding="utf-8"))

	def test_t032_ci_kapisi_gercek_test_ve_araclari_kosar(self):
		workflow = WORKFLOW.read_text(encoding="utf-8")
		for marker in (
			'python-version: "3.12"',
			"ffmpeg",
			"mypy tradehub_core/media/pipeline/contracts",
			"contracts.signatures --check",
			"test_faz3_closure",
			'test "$elapsed" -lt 600',
		):
			self.assertIn(marker, workflow)

	def test_t033_kanonik_dokuz_politika_acikca_sahipli(self):
		self.assertEqual(CANONICAL_POLICY_SET, "tradehub_core.media.pipeline.policy.slots")
		policies = [json.loads(path.read_text(encoding="utf-8")) for path in sorted(SLOT_DIR.glob("*.json"))]
		self.assertEqual(len(policies), 9)
		self.assertEqual(len({policy["slot_key"] for policy in policies}), 9)
		self.assertTrue(all(not policy.get("open_questions") for policy in policies))

	def test_t034_bes_kuyruk_ve_deploy_projeksiyonu(self):
		self.assertEqual(queues.validate_topology(), ())
		deploy = DEPLOY.read_text(encoding="utf-8")
		for queue_name in queues.QUEUE_NAMES:
			self.assertIn(f"queue-{queue_name}:", deploy)

	def test_t035_insan_imzasi_bos_kalir(self):
		closure = CLOSURE.read_text(encoding="utf-8")
		self.assertIn("T-030…T-034 teknik olarak tamamdır", closure)
		self.assertIn("| T-035 | Bağımsız mimari inceleme | ◐ İnsan kapısı |", closure)
		self.assertIn(
			"Onaylayan (Bağımsız gözden geçiren): ______________________",
			closure,
		)
		self.assertNotIn("Onaylayan (Bağımsız gözden geçiren): Ahmet", closure)


if __name__ == "__main__":
	unittest.main()
