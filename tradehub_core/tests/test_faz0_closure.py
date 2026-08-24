"""Faz 0 keşif çıktılarının kendi kendini doğrulayan kapanış kapısı.

Testler Frappe veritabanına bağlanmaz; repoya alınmış aggregate ölçümleri,
raporları ve fixture baytlarını doğrular. Hem ``unittest`` hem de
``pytest -m fixtures`` ile çalışır.
"""

from __future__ import annotations

import csv
import hashlib
import json
import unittest
from pathlib import Path

try:
	import pytest

	pytestmark = pytest.mark.fixtures
except ModuleNotFoundError:  # unittest/Frappe koşusunda pytest zorunlu değil
	pytestmark = ()


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "tradehub_core" / "tests" / "fixtures" / "media" / "manifest.json"
MEDIA_STATS_CSV = ROOT / "tradehub_core" / "tests" / "fixtures" / "media-stats.csv"
GLOBAL_STATS = ROOT / "docs" / "data" / "faz0-media-stats-2026-08-23.json"
SLOT_STATS = ROOT / "docs" / "data" / "faz0-slot-stats-2026-08-23.json"
LIGHTHOUSE = ROOT / "docs" / "data" / "faz0-lighthouse-baseline-2026-08-23.json"
WORST10_LIGHTHOUSE = ROOT / "docs" / "data" / "faz0-worst10-product-lighthouse-2026-08-23.json"
CLOSURE = ROOT / "docs" / "closure" / "faz0-kapanis.md"

DISCOVERY_REPORTS = (
	"docs/reports/00-ortam-envanteri.md",
	"docs/reports/00-upload-slot-envanteri.md",
	"docs/reports/01-dosya-akisi.md",
	"docs/reports/02-medya-istatistigi.md",
	"docs/reports/03-performans-taban-cizgisi.md",
	"docs/reports/04-yetki-modeli.md",
	"docs/reports/06-depolama-maliyet.md",
)


def _json(path: Path) -> dict:
	return json.loads(path.read_text())


class Faz0RaporKapisiTesti(unittest.TestCase):
	def test_yedi_kesif_raporu_var_ve_bos_degil(self):
		self.assertEqual(len(DISCOVERY_REPORTS), 7)
		for relative in DISCOVERY_REPORTS:
			path = ROOT / relative
			with self.subTest(report=relative):
				self.assertTrue(path.is_file())
				self.assertGreater(path.stat().st_size, 1000)

	def test_kapanis_on_gorevi_ve_insan_onayini_acikca_ayiriyor(self):
		text = CLOSURE.read_text()
		for task in range(10):
			self.assertIn(f"T-{task:03d}", text)
		self.assertIn("Platform yöneticisi", text)
		self.assertIn("insan onayı", text.lower())

	def test_guncel_upload_yuzeyleri_envanterde(self):
		text = (ROOT / "docs/reports/00-upload-slot-envanteri.md").read_text()
		self.assertIn("MediaUploader.vue", text)
		self.assertIn("UploadDropzone.vue", text)
		self.assertIn("SellerVerificationQueueView.vue", text)


class Faz0FixtureKapisiTesti(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.manifest = _json(MANIFEST)
		cls.entries = cls.manifest["fixtures"]

	def test_korpus_sayisal_esikleri_ve_izolasyonu_geciyor(self):
		groups = {"images": 0, "video": 0, "malicious": 0}
		for entry in self.entries:
			path = entry["file"]
			if "/media/images/" in path:
				groups["images"] += 1
			elif "/media/video/" in path:
				groups["video"] += 1
			elif "/fixtures/malicious/" in path:
				groups["malicious"] += 1
		self.assertGreaterEqual(groups["images"], 30)
		self.assertGreaterEqual(groups["video"], 8)
		self.assertGreaterEqual(groups["malicious"], 1)
		self.assertEqual(groups["malicious"], self.manifest["ozet"]["sinif_dagilimi"]["malicious"])

	def test_manifest_bayt_birebir_ve_bir_gb_altinda(self):
		seen: set[str] = set()
		total = 0
		for entry in self.entries:
			path = ROOT / entry["file"]
			with self.subTest(fixture=entry["file"]):
				self.assertNotIn(entry["file"], seen)
				seen.add(entry["file"])
				self.assertTrue(path.is_file())
				payload = path.read_bytes()
				total += len(payload)
				self.assertEqual(hashlib.sha256(payload).hexdigest(), entry["olculen"]["sha256"])
				self.assertEqual(entry["dogrulama"], "GEÇTİ")
		self.assertLess(total, 1024**3)
		self.assertEqual(total, self.manifest["ozet"]["toplam_bayt"])

	def test_korpus_gercek_dunya_ornekleri_de_tasiyor(self):
		real = [entry for entry in self.entries if str(entry.get("kaynak", "")).startswith("gerçek")]
		self.assertGreaterEqual(len(real), 2)
		self.assertTrue(any("/video/" in entry["file"] for entry in real))
		self.assertTrue(any("/images/" in entry["file"] for entry in real))


class Faz0OlcumKapisiTesti(unittest.TestCase):
	def test_global_istatistik_anomali_esigini_geciyor(self):
		data = _json(GLOBAL_STATS)
		self.assertGreater(data["reconcile"]["rows_all"], 0)
		self.assertGreater(data["probe"]["examined"], 0)
		self.assertGreaterEqual(sum(data["probe"]["anomaly_counts"].values()), 20)
		self.assertEqual(sum(data["privacy"]["reverse_ref_public_pii"].values()), 0)

	def test_dokuz_slot_ayni_persentil_semasinda(self):
		data = _json(SLOT_STATS)
		policy_names = {
			_json(path)["slot_key"]
			for path in (ROOT / "tradehub_core/media/pipeline/policy/slots").glob("*.json")
		}
		measured_names = {slot["slot_key"] for slot in data["slots"]}
		self.assertEqual(measured_names, policy_names)
		for slot in data["slots"]:
			for metric in ("bytes", "width_px", "height_px", "short_edge_px", "megapixels"):
				with self.subTest(slot=slot["slot_key"], metric=metric):
					distribution = slot[metric]
					if distribution["count"]:
						self.assertLessEqual(distribution["p50"], distribution["p90"])
						self.assertLessEqual(distribution["p90"], distribution["p99"])
						self.assertLessEqual(distribution["p99"], distribution["max"])
					else:
						self.assertTrue(all(distribution[key] is None for key in ("p50", "p90", "p99", "max")))

	def test_media_stats_csv_global_ve_tum_slotlari_tasiyor(self):
		with MEDIA_STATS_CSV.open(newline="") as handle:
			rows = list(csv.DictReader(handle))
		scopes = {row["scope"] for row in rows}
		self.assertIn("global.public", scopes)
		for slot in _json(SLOT_STATS)["slots"]:
			self.assertIn(f"slot.{slot['slot_key']}", scopes)

	def test_dort_sayfa_iki_cihaz_lighthouse_taban_cizgisi(self):
		data = _json(LIGHTHOUSE)
		runs = data["runs"]
		self.assertEqual(len(runs), 8)
		self.assertEqual({run["page_type"] for run in runs}, {"home", "listing", "product", "store"})
		for page in {run["page_type"] for run in runs}:
			self.assertEqual({run["profile"] for run in runs if run["page_type"] == page}, {"desktop", "mobile"})
		for run in runs:
			self.assertGreater(run["lcp_ms"], 0)
			self.assertGreaterEqual(run["image_transfer_bytes"], 0)

	def test_en_agir_on_urun_iki_profille_olculdu(self):
		data = _json(WORST10_LIGHTHOUSE)
		self.assertGreaterEqual(data["selection"]["measured_catalog_products"], 10)
		self.assertEqual(data["selection"]["selected"], 10)
		self.assertEqual(len(data["products"]), 10)
		self.assertEqual(data["run_window"]["isolated_sequential_runs"], 20)
		for product in data["products"]:
			self.assertEqual({run["profile"] for run in product["runs"]}, {"desktop", "mobile"})
			self.assertGreater(product["catalog_local_image_bytes"], 0)


if __name__ == "__main__":
	unittest.main()
