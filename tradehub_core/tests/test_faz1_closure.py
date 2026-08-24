"""Faz 1 AR-GE artefaktlarının makineyle doğrulanan kapanış kapısı.

İnsan etiketi/cihaz laboratuvarını yeşil göstermeyi özellikle engeller: bu iki
alan dolana kadar test onların açık ve açıkça raporlanmış olduğunu doğrular.
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORTS = tuple(ROOT / f"docs/reports/{task:02d}-{name}.md" for task, name in (
	(10, "algoritma-dogrulama"),
	(11, "rakip-analizi"),
	(12, "dpi-prototip"),
	(13, "kalite-prototip"),
	(14, "smartcrop-karsilastirma"),
	(15, "client-butce"),
	(16, "video-karar"),
	(17, "guvenlik-arge"),
	(18, "depolama-arge"),
))


def load(path: Path) -> dict:
	return json.loads(path.read_text(encoding="utf-8"))


class Faz1ArtefaktKapisi(unittest.TestCase):
	def test_dokuz_kanonik_rapor_var(self):
		self.assertEqual(len(REPORTS), 9)
		for report in REPORTS:
			with self.subTest(report=report.name):
				self.assertTrue(report.is_file())
				self.assertGreater(report.stat().st_size, 700)

	def test_resmi_prototip_yollari_var(self):
		for relative in (
			"prototypes/cropgeo/README.md",
			"prototypes/client-budget/index.ts",
			"prototypes/smartcrop/annotate.html",
			"prototypes/storage/README.md",
			"docs/simulator.html",
		):
			with self.subTest(path=relative):
				self.assertTrue((ROOT / relative).is_file())

	def test_p01_p16_izlenebilirligi_eksiksiz(self):
		text = (ROOT / "docs/reports/10-algoritma-dogrulama.md").read_text(encoding="utf-8")
		self.assertEqual(set(re.findall(r"P-(\d{2})", text)), {f"{i:02d}" for i in range(1, 17)})


class Faz1CropKapisi(unittest.TestCase):
	def test_vektor_sayisi_hatalar_ve_tolerans(self):
		data = load(ROOT / "tests/vectors/crop-vectors.json")
		self.assertEqual(data["vector_count"], len(data["vectors"]))
		self.assertGreaterEqual(data["vector_count"], 200)
		self.assertLessEqual(data["tolerance_px"], 0.5)
		self.assertEqual(sum(bool(row.get("error")) for row in data["vectors"]), 8)

	def test_simulator_test_edilen_fonksiyon_isaretlerini_tasir(self):
		text = (ROOT / "docs/simulator.html").read_text(encoding="utf-8")
		self.assertEqual(text.count("T010-CROPWINDOW-BEGIN"), 1)
		self.assertEqual(text.count("T010-CROPWINDOW-END"), 1)
		self.assertIn("function cropWindow", text)


class Faz1OlcumKapisi(unittest.TestCase):
	def test_adaptif_kalite_dort_encode_ve_lossless_kapisi(self):
		data = load(ROOT / "docs/data/t013-adaptive-vs-q85.json")
		self.assertEqual(set(data["summary"]), {"jpeg", "webp", "avif"})
		for codec, row in data["summary"].items():
			with self.subTest(codec=codec):
				self.assertEqual(row["samples"], 10)
				self.assertEqual(row["adaptive_target_met"], 10)
				self.assertLessEqual(row["max_encodes"], 4)
				self.assertGreaterEqual(row["lossless_required_samples"], 1)

	def test_smartcrop_elli_gorselde_uc_yontemi_kosuyor_ama_insan_kapisi_acik(self):
		data = load(ROOT / "docs/data/t014-smartcrop-benchmark.json")
		self.assertEqual(data["images"], 50)
		self.assertEqual(data["human_labels"], 0)
		self.assertFalse(data["threshold_calibrated"])
		self.assertEqual(set(data["methods"]), {"entropy_edge", "background_segmentation", "onnx_u2netp"})
		for method, row in data["methods"].items():
			with self.subTest(method=method):
				self.assertEqual(row["attempted"], 50)
				self.assertEqual(row["successful"], 50)

	def test_insan_kapilari_kapanista_acik_yaziyor(self):
		closure = (ROOT / "docs/closure/faz1-kapanis.md").read_text(encoding="utf-8").lower()
		self.assertIn("insan etiketi", closure)
		self.assertIn("gerçek cihaz", closure)
		self.assertIn("imza", closure)


class Faz1AdrKapisi(unittest.TestCase):
	def test_her_adr_geri_donus_yolu_tasir(self):
		adrs = sorted((ROOT / "docs/adr").glob("0*.md"))
		self.assertGreaterEqual(len(adrs), 28)
		for adr in adrs:
			with self.subTest(adr=adr.name):
				self.assertEqual(adr.read_text(encoding="utf-8").count("## Geri dönüş yolu"), 1)

	def test_on_zorunlu_tema_indekste(self):
		index = (ROOT / "docs/adr/README.md").read_text(encoding="utf-8")
		for theme in (
			"Image engine", "Video engine", "İstemci kütüphane seti", "Birincil depolama",
			"CDN", "Smartcrop", "Uyarlanabilir kalite", "Video karar tablosu biçimi",
			"DPI/piksel politikası", "Güvenlik izolasyonu",
		):
			with self.subTest(theme=theme):
				self.assertIn(theme, index)


if __name__ == "__main__":
	unittest.main()

