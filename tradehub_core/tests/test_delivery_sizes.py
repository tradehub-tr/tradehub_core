"""T-121 doğrulaması — türetilen `sizes`, ELLE ÖLÇÜLEN piksel tablosuna uyuyor mu.

`docs/reports/03-render-envanteri.md` §3.1–§3.8'deki kutu genişlikleri storefront'un
Tailwind sınıflarından ELLE hesaplandı. `tradehub_core/media/pipeline/simulator/placements.json` aynı
kutuları VERİ olarak taşıyor ve `srcset.py` onlardan CSS ifadesi üretiyor. Bu iki yol
BAĞIMSIZDIR; test ikisini karşılaştırır.

Uyuşmazlık ne demektir:
  - türetilen yanlışsa → `sizes` üretimde yanlış basamak seçtirir (sessiz hata),
  - rapor yanlışsa → Faz 2'nin profil genişlikleri yanlış tabana oturmuştur.

İkisi de kabul edilemez; bu yüzden `verify()` açıklanmamış TEK sapmaya bile izin
vermez. Bilinen ve gerekçelendirilmiş sapmalar `sizes.KNOWN_DEVIATIONS`'tadır ve
burada tek tek sayılır.

Çalıştırma (bench/site/DB GEREKMEZ):

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tests.test_delivery_sizes -v
    PYTHONPATH=. python3 -m tradehub_core.media.pipeline.delivery.sizes   # tabloyu görmek için
"""

from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.delivery import sizes as SZ  # noqa: E402
from tradehub_core.media.pipeline.delivery.manifest import ManifestBuilder  # noqa: E402
from tradehub_core.media.pipeline.simulator import srcset as sim  # noqa: E402


class CssYorumlayici(unittest.TestCase):
	"""`evaluate` / `resolve` — üretilen ifadeleri gerçekten çözebiliyor mu."""

	def test_temel_birimler(self):
		self.assertEqual(SZ.evaluate("100px", 390), 100.0)
		self.assertEqual(SZ.evaluate("100vw", 390), 390.0)
		self.assertEqual(SZ.evaluate("50vw", 390), 195.0)
		self.assertEqual(SZ.evaluate("82vh", 390, viewport_height=900), 738.0)

	def test_calc_min_max(self):
		self.assertEqual(SZ.evaluate("min(100vw, 1840px)", 1920), 1840.0)
		self.assertEqual(SZ.evaluate("min(100vw, 1840px)", 1024), 1024.0)
		self.assertEqual(SZ.evaluate("max(10px, 2vw)", 1000), 20.0)
		self.assertAlmostEqual(SZ.evaluate("calc((min(100vw, 1840px) - 32px - 16px) / 2)", 360), 156.0)

	def test_islem_onceligi(self):
		self.assertEqual(SZ.evaluate("calc(100px + 10px * 2)", 390), 120.0)
		self.assertEqual(SZ.evaluate("calc((100px + 10px) * 2)", 390), 220.0)

	def test_vh_yuksekliksiz_hata(self):
		with self.assertRaises(SZ.SizesError):
			SZ.evaluate("82vh", 390)

	def test_desteklenmeyen_birim_sessizce_sifir_olmaz(self):
		for kotu in ("2rem", "10em", "clamp(1px, 2vw, 3px)"):
			with self.assertRaises(SZ.SizesError):
				SZ.evaluate(kotu, 390)

	def test_bozuk_parantez(self):
		for kotu in ("calc((100px)", "calc(100px))", "min(100vw"):
			with self.assertRaises(SZ.SizesError):
				SZ.evaluate(kotu, 390)

	def test_resolve_ilk_tutan_kosul_kazanir(self):
		s = "(min-width: 1024px) 300px, (min-width: 640px) 200px, 100px"
		self.assertEqual(SZ.resolve(s, 1280), 300.0)
		self.assertEqual(SZ.resolve(s, 1024), 300.0)
		self.assertEqual(SZ.resolve(s, 1023), 200.0)
		self.assertEqual(SZ.resolve(s, 400), 100.0)

	def test_resolve_min_icindeki_virgul_bolunmez(self):
		s = "(min-width: 640px) calc(min(100vw, 1840px) / 2), 100vw"
		self.assertEqual(SZ.resolve(s, 1920), 920.0)

	def test_bos_sizes_hata(self):
		"""Boş `sizes` bir EKSİKLİK bildirimidir; sessizce 0 dönmemeli."""
		with self.assertRaises(SZ.SizesError):
			SZ.resolve("", 390)


class RaporlaCaprazDogrulama(unittest.TestCase):
	"""Asıl sınav: 71 ölçüm satırı."""

	@classmethod
	def setUpClass(cls):
		cls.sonuc = SZ.verify()

	def test_aciklanmamis_sapma_yok(self):
		self.assertTrue(self.sonuc.ok, "\n" + self.sonuc.report())

	def test_yeterli_satir_dogrulandi(self):
		self.assertGreaterEqual(self.sonuc.checked, 70, "rapor tablosu eksik kopyalanmış")

	def test_bilinen_sapmalarin_hepsi_gercekten_olusuyor(self):
		"""`KNOWN_DEVIATIONS` bir bahane listesi değil; her satırı gerçek olmalı."""
		olusan = {(d.region_key, d.viewport) for d in self.sonuc.deviations}
		for anahtar in SZ.KNOWN_DEVIATIONS:
			self.assertIn(
				anahtar, olusan,
				f"{anahtar} artık sapmıyor — `KNOWN_DEVIATIONS`'tan silinmeli",
			)

	def test_atlanan_bolgelerin_hepsi_gerekceli(self):
		for anahtar, gerekce in self.sonuc.skipped.items():
			self.assertTrue(gerekce.strip(), f"{anahtar} gerekçesiz atlanmış")

	def test_monoton_olmayan_kutu_dogru_ifade_ediliyor(self):
		"""Raporun §3.1 anomalisi: 640→296px, 768→147px (kutu KÜÇÜLÜYOR).

		`Xvw` zinciriyle ifade edilemeyeceğinin kanıtı bu testtir; üretilen
		dizge kırılım başına ayrı değer taşıdığı için ikisini de tutturur.
		"""
		s = SZ.sizes_for("listing/card_grid")
		self.assertAlmostEqual(SZ.resolve(s, 640), 296.0, delta=0.6)
		self.assertAlmostEqual(SZ.resolve(s, 768), 146.7, delta=0.6)
		self.assertLess(SZ.resolve(s, 768), SZ.resolve(s, 640), "monotonluk varsayımı geri gelmiş")


class TabloVeKurulum(unittest.TestCase):
	"""`ManifestBuilder`'ın boş `SIZES_TABLE`'ı gerçekten doluyor mu."""

	def test_tum_bolgeler_sizes_uretiyor(self):
		tablo = SZ.sizes_table()
		self.assertEqual(len(tablo), len(SZ.region_keys()))
		for anahtar, deger in tablo.items():
			self.assertTrue(deger.strip(), f"{anahtar} boş `sizes` üretti")

	def test_install_manifest_builder_a_yukluyor(self):
		b = ManifestBuilder()
		self.assertEqual(b.sizes_attribute("product.image", context="product_detail/main_image"), "")
		sayi = SZ.install(b)
		self.assertGreater(sayi, 0)
		uretilen = b.sizes_attribute("product.image", context="product_detail/main_image")
		self.assertTrue(uretilen)
		self.assertIn("100vw", uretilen, "mobilde kutu = tam viewport (§3.6)")

	def test_manifest_sizes_source_artik_unmeasured_degil(self):
		"""Ölçülmemişlik bildirimi, ölçüm gelince kalkmalı."""
		from tradehub_core.media.pipeline.contracts.storage import ObjectKey, ObjectRef
		from tradehub_core.media.pipeline.delivery.manifest import SIZES_SOURCE_TABLE

		b = ManifestBuilder()
		SZ.install(b)
		ref = ObjectRef(key=ObjectKey(shard="ab", name="ab" + "c" * 30 + ".jpg"), scope="public")
		m = b.build_image(
			"product.image", ref, intrinsic=(2400, 2400),
			sizes=b.sizes_attribute("product.image", context="product_detail/main_image"),
		)
		self.assertTrue(m.sizes)
		self.assertNotEqual(m.extra["sizes_source"], "unmeasured")
		self.assertIn(m.extra["sizes_source"], ("caller", SIZES_SOURCE_TABLE))

	def test_yukseklige_bagli_bolgeler_isaretli(self):
		self.assertIn("product_detail/lightbox_main", SZ.height_bound_regions())


class SimulatorleTutarlilik(unittest.TestCase):
	"""`sizes` üzerinden hesaplanan talep, simülatörün kutusundan çıkanla AYNI olmalı.

	İki farklı yol: simülatör kutuyu doğrudan hesaplar; `required_px` ise ÜRETİLEN
	CSS dizgesini yorumlayıp çarpar. Ayrışırlarsa üretilen dizge tarayıcıya yanlış
	basamak seçtiriyor demektir.
	"""

	def test_65_kombinasyon_ayni_pikseli_veriyor(self):
		yerlesim = sim.load_layout()
		cihazlar = sim.load_devices()
		kontrol = 0
		for bolge in yerlesim.all_regions():
			dizge = SZ.sizes_for(bolge.key, yerlesim)
			for cihaz in cihazlar:
				kutu = sim.box_width(bolge, cihaz, yerlesim)
				if any("vh_pct" in adim for adim in bolge.box):
					continue  # `sizes` yüksekliği taşır; ayrı doğrulama (height_bound)
				cozulen = SZ.resolve(dizge, cihaz.css_width)
				self.assertAlmostEqual(
					cozulen, kutu, delta=0.05,
					msg=f"{bolge.key} @{cihaz.css_width}px: sizes {cozulen} ≠ kutu {kutu}",
				)
				self.assertEqual(
					SZ.required_px(bolge.key, cihaz.css_width, cihaz.dpr, layout=yerlesim),
					math.ceil(kutu * cihaz.dpr),
				)
				kontrol += 1
		self.assertGreater(kontrol, 100, "kombinasyon sayısı beklenenden az")


class OlculenTelefon(unittest.TestCase):
	"""390px iPhone / DPR 2 — görev metnindeki somut soru."""

	def test_pdp_ana_gorsel_780px_ister(self):
		self.assertEqual(SZ.required_px("product_detail/main_image", 390, 2.0), 780)

	def test_kart_izgarasi_ayni_telefonda_346px_ister(self):
		"""Aynı telefonda ürün KARTI 780px değil ~346px ister — ikisi farklı bölge."""
		self.assertEqual(SZ.required_px("home/tailored_grid", 390, 2.0), 346)
		self.assertEqual(SZ.required_px("home/hero_showcase_grid", 390, 2.0), 342)

	def test_780_hedefi_merdivende_basamak_bulamiyor(self):
		"""w768, 780'in 12px ALTINDA kalıyor → tarayıcı w1280'e sıçrıyor."""
		merdiven = sim.renditions_for("product.image")
		secilen = sim.select_rendition(merdiven, 780)
		self.assertEqual(secilen.width, 1280, "merdivende 768→1280 boşluğu kapanmış olmalı")
		self.assertAlmostEqual(secilen.width / 780, 1.641, places=2)


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
