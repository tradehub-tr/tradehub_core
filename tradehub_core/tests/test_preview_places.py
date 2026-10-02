"""Önizleme yer kaydı (`placements.json → preview_places`) ve üreteçleri — 2026-10-01.

Çalıştırma (bench/site/DB GEREKMEZ):

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tradehub_core.tests.test_preview_places -v
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.delivery import sizes as SZ  # noqa: E402
from tradehub_core.media.pipeline.simulator import PLACEMENTS_PATH  # noqa: E402
from tradehub_core.media.pipeline.simulator import srcset as sim  # noqa: E402

SLOTS = ("company.cover_image", "seller.logo", "product.image")


class YerKaydi(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		cls.yerler = SZ.preview_places()

	def test_her_slot_her_cihazda_en_az_bir_yer(self):
		for slot in SLOTS:
			for cihaz in ("desktop", "mobile"):
				with self.subTest(slot=slot, cihaz=cihaz):
					self.assertTrue([y for y in self.yerler[slot] if y["device"] == cihaz])

	def test_alanlar_ve_sozluk(self):
		for slot, yerler in self.yerler.items():
			for y in yerler:
				with self.subTest(slot=slot, key=y["key"], device=y["device"]):
					self.assertIn(y["fit"], SZ.PREVIEW_FITS)
					self.assertIn(y["context"], SZ.PREVIEW_CONTEXTS)
					self.assertGreater(y["ratio"], 0)
					self.assertTrue(y["labelKey"].startswith("imagePlacement.place."))
					self.assertTrue(y["derivedFrom"])

	def test_bolge_turetilen_olcu_box_width_ile_ayni(self):
		yerlesim = sim.load_layout()
		cihaz = {d.id: d for d in sim.load_devices()}["macbook-air-13"]
		kart = next(
			y for y in self.yerler["product.image"] if y["key"] == "product_card" and y["device"] == "desktop"
		)
		bolge = yerlesim.region_of("listing", "card_grid")
		self.assertEqual(kart["cssW"], round(sim.box_width(bolge, cihaz, yerlesim)))
		self.assertEqual(kart["cssW"], 213)

	def test_magaza_basligi_telefonda_390x180(self):
		yer = next(
			y for y in self.yerler["company.cover_image"] if y["key"] == "store_hero" and y["device"] == "mobile"
		)
		self.assertEqual((yer["cssW"], yer["cssH"]), (390, 180))
		self.assertAlmostEqual(yer["ratio"], 390 / 180, places=4)

	def test_bolgeler_degismedi(self):
		# preview_places sayfa/bölge listesine KARIŞMAZ — sizes/srcset paritesi aynı kalır.
		self.assertEqual(len(SZ.region_keys()), 15)


class Ureticiler(unittest.TestCase):
	def test_admin_ciktisi_sha_ve_json_tasir(self):
		cikti = SZ.emit_placements_admin()
		sha = hashlib.sha256(Path(PLACEMENTS_PATH).read_bytes()).hexdigest()
		self.assertIn(f'export const SOURCE_SHA256 = "{sha}";', cikti)
		eslesme = re.search(r"export const PLACES = Object\.freeze\((\{.*\})\);\n", cikti, re.S)
		self.assertIsNotNone(eslesme)
		veri = json.loads(eslesme.group(1))
		self.assertEqual(set(veri), set(SLOTS))
		self.assertIn("export const FULLY_VISIBLE_MIN = 0.98;", cikti)

	def test_storefront_ciktisi_bes_anahtar(self):
		cikti = SZ.emit_placements_storefront()
		for anahtar, deger in {
			"galleryMain": "(min-width: 768px) 500px, 100vw",
			"galleryThumb": "120px",
			"manufacturerGallery": "(min-width: 1024px) 220px, 165px",
			"shopHeaderLogoDesktop": "140px",
			"shopHeaderLogoMobile": "48px",
		}.items():
			self.assertIn(f'  {anahtar}: "{deger}",', cikti)
		self.assertIn("} as const;", cikti)

	def test_cli_bilinmeyen_hedef_2_doner(self):
		self.assertEqual(SZ.main(["--emit-placements", "nope"]), 2)


if __name__ == "__main__":
	unittest.main()
