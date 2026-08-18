"""T-123 doğrulaması — RUM şeması PII sızdırmıyor ve örneklem tutarlı.

`docs/reports/03-performans-taban-cizgisi.md` §6.2: alan (field) verisi
ÖLÇÜLEMEDİ. Bu modül o boşluğu kapatacak sözleşmedir; testin işi sözleşmenin
iki sert vaadini kanıtlamak:

  1. **PII geçmez.** Ne yasak alan adıyla, ne serbest URL ile, ne ham
     User-Agent ile. `docs/reports/08-canli-olcum.md` §6 aynı depoda gerçek
     veride PII sızıntısı ölçtü — bu şema aynı hatayı yapısal olarak
     imkânsız kılmalı.
  2. **Örneklem deterministik.** Aynı oturum tokeni hep aynı kararı alır;
     yoksa bir oturumun bazı metrikleri düşer ve p75 çarpıtılır.

Çalıştırma:

    cd /Users/ahmet/Desktop/istoc/tradehub_core
    python3 -m unittest tests.test_delivery_rum -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.delivery import rum as R  # noqa: E402

TOKEN = "0123456789abcdef" * 2


def gecerli(**kw) -> dict:
	temel = {
		"metric": "LCP",
		"value": 1899.4,
		"route": "/urun/:slug",
		"device_class": "phone",
		"viewport_width": 390,
		"dpr": 2,
		"connection": "4g",
		"sample_rate": 0.1,
		"session_token": TOKEN,
	}
	temel.update(kw)
	return temel


class PiiKorumasi(unittest.TestCase):
	def test_yasak_alanlarin_hepsi_reddedilir(self):
		for alan in R.FORBIDDEN_FIELDS:
			with self.assertRaises(R.RumError, msg=f"{alan} geçti!"):
				R.validate(gecerli(**{alan: "x"}))

	def test_sema_yasak_alanlarin_hicbirini_tanimlamiyor(self):
		"""Beyaz liste yaklaşımı: yasak alanların hiçbiri şemada olmamalı."""
		self.assertEqual(
			set(R.schema_forbids_pii()), set(R.FORBIDDEN_FIELDS),
			"bir PII alanı şemaya sızmış",
		)
		self.assertFalse(R.SCHEMA["additionalProperties"])

	def test_kullaniciya_ozel_yol_other_a_duser(self):
		for yol in (
			"/hesabim/siparis/SO-00042",
			"/hesabim",
			"/admin/user/turksab.yonetim@gmail.com",
			"/urun/a/b/c",
		):
			self.assertEqual(R.route_template(yol), "other", yol)

	def test_sorgu_dizgesi_silinir(self):
		self.assertEqual(
			R.route_template("/urun/bonny-kap?utm_source=mail&q=gizli+arama"), "/urun/:slug"
		)
		self.assertEqual(R.route_template("/urunler?arama=kirmizi+kutu#x"), "/urunler")

	def test_ham_token_saklanmaz(self):
		s = R.validate(gecerli())
		self.assertNotIn(TOKEN, str(s.to_dict()))
		self.assertEqual(len(s.session_bucket), 12)

	def test_token_ozeti_salt_ile_degisir(self):
		self.assertNotEqual(R.token_hash(TOKEN, salt="a"), R.token_hash(TOKEN, salt="b"))

	def test_ham_viewport_saklanmaz(self):
		"""Nadir bir genişlik tek başına parmak izi olabilir; kova saklanır."""
		s = R.validate(gecerli(viewport_width=397))
		self.assertEqual(s.viewport_bucket, 390)
		self.assertNotIn(397, s.to_dict().values())


class SemaDogrulama(unittest.TestCase):
	def test_bilinmeyen_metrik(self):
		with self.assertRaises(R.RumError):
			R.validate(gecerli(metric="FID"))

	def test_negatif_ve_nan_deger(self):
		for kotu in (-1, float("nan"), float("inf"), "abc"):
			with self.assertRaises(R.RumError):
				R.validate(gecerli(value=kotu))

	def test_cihaz_ve_baglanti_beyaz_liste(self):
		with self.assertRaises(R.RumError):
			R.validate(gecerli(device_class="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)"))
		with self.assertRaises(R.RumError):
			R.validate(gecerli(connection="wifi"))

	def test_dpr_makul_araligi(self):
		for kotu in (0.1, 12, "x"):
			with self.assertRaises(R.RumError):
				R.validate(gecerli(dpr=kotu))

	def test_lcp_bolgesi_ve_profili_bicimli(self):
		s = R.validate(gecerli(lcp_region="product_detail/main_image", lcp_profile="w1280"))
		self.assertEqual(s.lcp_region, "product_detail/main_image")
		with self.assertRaises(R.RumError):
			R.validate(gecerli(lcp_region="Ürün Detay Ana Görsel"))
		with self.assertRaises(R.RumError):
			R.validate(gecerli(lcp_profile="../../etc/passwd"))

	def test_sample_rate_sifir_reddedilir(self):
		"""Oran 0 ile gelen kayıt mantıksızdır: gönderilmemeliydi."""
		with self.assertRaises(R.RumError):
			R.validate(gecerli(sample_rate=0))


class Siniflandirma(unittest.TestCase):
	def test_web_dev_esikleri(self):
		self.assertEqual(R.rating("LCP", 2500), R.RATING_GOOD)
		self.assertEqual(R.rating("LCP", 2500.1), R.RATING_NEEDS_IMPROVEMENT)
		self.assertEqual(R.rating("LCP", 4000.1), R.RATING_POOR)
		self.assertEqual(R.rating("CLS", 0.1), R.RATING_GOOD)
		self.assertEqual(R.rating("CLS", 0.26), R.RATING_POOR)

	def test_olculen_taban_cizgisi_siniflari(self):
		"""Lab taban çizgisi: LCP dördü de iyi, ürün listeleme CLS'i kötü."""
		for rota, ms in R.LAB_BASELINE_MS.items():
			self.assertEqual(R.rating("LCP", ms), R.RATING_GOOD, rota)
		self.assertEqual(R.rating("CLS", R.LAB_BASELINE_CLS["/urunler"]), R.RATING_POOR)
		self.assertEqual(R.rating("CLS", R.LAB_BASELINE_CLS["/urun/:slug"]), R.RATING_GOOD)


class Orneklem(unittest.TestCase):
	def test_deterministik(self):
		self.assertEqual(
			[R.decide(TOKEN, 0.25) for _ in range(5)],
			[R.decide(TOKEN, 0.25)] * 5,
		)

	def test_sinir_oranlari(self):
		self.assertFalse(R.decide(TOKEN, 0.0))
		self.assertTrue(R.decide(TOKEN, 1.0))

	def test_oran_arttikca_kume_buyur(self):
		"""%10'a giren her oturum %50'ye de girmeli — aksi hâlde kohort kayar."""
		tokenlar = [f"{i:032x}" for i in range(2000)]
		kucuk = {t for t in tokenlar if R.decide(t, 0.1)}
		buyuk = {t for t in tokenlar if R.decide(t, 0.5)}
		self.assertTrue(kucuk.issubset(buyuk))

	def test_dagilim_orana_yakin(self):
		tokenlar = [f"{i:032x}" for i in range(5000)]
		oran = sum(1 for t in tokenlar if R.decide(t, 0.1)) / 5000
		self.assertAlmostEqual(oran, 0.1, delta=0.02)

	def test_gecersiz_token(self):
		for kotu in ("", "kısa", "ZZZZ" * 8):
			with self.assertRaises(R.RumError):
				R.decide(kotu, 0.5)


class Toplama(unittest.TestCase):
	def ornekler(self, degerler, **kw):
		return [R.validate(gecerli(value=v, **kw)) for v in degerler]

	def test_p75_interpolasyonsuz(self):
		self.assertEqual(R.percentile([1, 2, 3, 4], 0.75), 3)
		self.assertEqual(R.percentile([100], 0.75), 100)
		self.assertEqual(R.percentile([], 0.75), 0.0)

	def test_p75_gozlenmemis_deger_uretmez(self):
		degerler = [10.0, 20.0, 30.0, 1000.0]
		self.assertIn(R.percentile(degerler, 0.75), degerler)

	def test_orneklem_orani_geri_carpilir(self):
		"""%10 örneklemde 10 kayıt ≈ 100 gerçek olay demektir."""
		a = R.aggregate(self.ornekler([100.0] * 10))[0]
		self.assertEqual(a.count, 10)
		self.assertAlmostEqual(a.estimated_population, 100.0)

	def test_kovalama_rota_ve_cihaza_gore(self):
		ornekler = self.ornekler([100.0, 200.0]) + self.ornekler([300.0], device_class="desktop")
		sonuc = R.aggregate(ornekler)
		self.assertEqual(len(sonuc), 2)
		self.assertEqual({tuple(a.key) for a in sonuc},
						 {("/urun/:slug", "phone"), ("/urun/:slug", "desktop")})

	def test_deger_alani_gruplanamaz(self):
		with self.assertRaises(R.RumError):
			R.aggregate([], group_by=("value",))

	def test_lab_karsilastirmasi_farki_gizlemiyor(self):
		a = R.aggregate(self.ornekler([1200.0]))
		karsilastirma = R.compare_to_lab(a)[0]
		self.assertEqual(karsilastirma["lab_baseline"], R.LAB_BASELINE_MS["/urun/:slug"])
		self.assertAlmostEqual(karsilastirma["delta"], 1200.0 - 919.0, places=1)
		self.assertIn("eşitlenemez", karsilastirma["note"])


if __name__ == "__main__":  # pragma: no cover
	unittest.main(verbosity=2)
