"""T-123 — RUM ↔ metrik köprüsü ve `Media RUM Sample` şema tasarımı testleri.

`tests/test_delivery_rum.py` çekirdeği (doğrulama, PII reddi, p75) test
ediyor. Bu dosya onun BIRAKTIĞI yeri alır: toplanan p75 gerçekten Prometheus'a
çıkıyor mu, birimler ayrışıyor mu, ret sebepleri kararlı bir kod olarak mı
sayılıyor, ve kurulacak DocType şeması hâlâ PII geçirmiyor mu.

Birim ayrımı (`rum_p75_milliseconds` ile `rum_cls_p75`) burada test ediliyor
çünkü tek metrik altında toplanmış bir LCP+CLS karışımı, panelde makul
görünen ama anlamsız bir çizgi üretir — ve kimse fark etmez.

Çalıştırma:

    python3 -m unittest tradehub_core.tests.test_rum_metrics -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.delivery import rum  # noqa: E402
from tradehub_core.media.pipeline.observability import metrics as mm  # noqa: E402


def ornek(metric: str, value: float, **ek) -> rum.RumSample:
	govde = {
		"metric": metric,
		"value": value,
		"route": "/urun/:slug",
		"device_class": "phone",
		"viewport_width": 390,
		"sample_rate": 1.0,
	}
	govde.update(ek)
	return rum.validate(govde)


class MetrikKoprusu(unittest.TestCase):
	def setUp(self) -> None:
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)

	def test_lcp_p75_milisaniye_metrigine_yazilir(self):
		toplam = rum.aggregate([ornek("LCP", v) for v in (800, 900, 3000, 2600)])
		self.assertEqual(rum.to_metrics(toplam), 1)
		self.assertEqual(
			mm.RUM_P75_MS.deger(metric="LCP", route="/urun/:slug", device_class="phone"), 2600.0
		)

	def test_cls_ayri_birimsiz_metrige_yazilir(self):
		toplam = rum.aggregate([ornek("CLS", 0.4)])
		rum.to_metrics(toplam)
		self.assertEqual(mm.RUM_CLS_P75.deger(route="/urun/:slug", device_class="phone"), 0.4)
		# Birimsiz değer milisaniye metriğine SIZMAMALI.
		self.assertEqual(mm.RUM_P75_MS.seri_sayisi(), 0)

	def test_ornek_sayisi_ve_tahmini_populasyon_ayri(self):
		"""%10 örneklemde ham sayı 2, tahmini popülasyon 20 olmalı."""
		toplam = rum.aggregate([ornek("LCP", 1000, sample_rate=0.1) for _ in range(2)])
		rum.to_metrics(toplam)
		self.assertEqual(
			mm.RUM_SAMPLES_TOTAL.deger(
				metric="LCP", route="/urun/:slug", device_class="phone", rating="good"
			),
			2.0,
		)
		self.assertEqual(
			mm.RUM_ESTIMATED_POPULATION.deger(
				metric="LCP", route="/urun/:slug", device_class="phone"
			),
			20.0,
		)

	def test_rating_etiketi_esikten_gelir(self):
		toplam = rum.aggregate([ornek("LCP", 5000)])
		rum.to_metrics(toplam)
		self.assertEqual(
			mm.RUM_SAMPLES_TOTAL.deger(
				metric="LCP", route="/urun/:slug", device_class="phone", rating="poor"
			),
			1.0,
		)

	def test_yanlis_kovalama_acik_hata_verir(self):
		"""Etiket kümesi tutmayınca anlaşılır bir `RumError` gelmeli."""
		toplam = rum.aggregate([ornek("LCP", 1000)], group_by=("route",))
		with self.assertRaises(rum.RumError):
			rum.to_metrics(toplam)

	def test_gosterge_uzerine_yazilir_sayac_birikir(self):
		"""İki pencere art arda geçilince p75 GÜNCELLENİR, sayaç TOPLANIR."""
		rum.to_metrics(rum.aggregate([ornek("LCP", 1000)]))
		rum.to_metrics(rum.aggregate([ornek("LCP", 4000)]))
		self.assertEqual(
			mm.RUM_P75_MS.deger(metric="LCP", route="/urun/:slug", device_class="phone"), 4000.0
		)
		toplam = sum(
			s.deger for s in mm.RUM_SAMPLES_TOTAL._seriler.values()  # noqa: SLF001 - test
		)
		self.assertEqual(toplam, 2.0)

	def test_metrik_metni_prometheus_biciminde(self):
		rum.to_metrics(rum.aggregate([ornek("INP", 350)]))
		metin = mm.RUM_P75_MS.render()
		self.assertIn("# TYPE media_rum_p75_milliseconds gauge", metin)
		self.assertIn('metric="INP"', metin)


class RetSebepleri(unittest.TestCase):
	def setUp(self) -> None:
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)

	def _red(self, govde: dict) -> str:
		with self.assertRaises(rum.RumError) as tutamac:
			rum.validate(govde)
		return rum.record_rejection(tutamac.exception)

	def test_pii_alani_kendi_koduyla_sayilir(self):
		kod = self._red(
			{
				"metric": "LCP",
				"value": 1,
				"route": "/",
				"device_class": "phone",
				"viewport_width": 390,
				"sample_rate": 1.0,
				"email": "biri@example.com",
			}
		)
		self.assertEqual(kod, rum.SEBEP_PII_ALAN)
		self.assertEqual(mm.RUM_REJECTED_TOTAL.deger(reason=rum.SEBEP_PII_ALAN), 1.0)

	def test_bilinmeyen_metrik_ayri_kovaya_duser(self):
		kod = self._red(
			{
				"metric": "TTI",
				"value": 1,
				"route": "/",
				"device_class": "phone",
				"viewport_width": 390,
				"sample_rate": 1.0,
			}
		)
		self.assertEqual(kod, rum.SEBEP_METRIK)

	def test_gecersiz_cihaz_kendi_kodunu_alir(self):
		kod = self._red(
			{
				"metric": "LCP",
				"value": 1,
				"route": "/",
				"device_class": "buzdolabi",
				"viewport_width": 390,
				"sample_rate": 1.0,
			}
		)
		self.assertEqual(kod, rum.SEBEP_CIHAZ)

	def test_rum_disi_istisna_malformed_body_sayilir(self):
		"""Beklenmeyen hata sessizce düşmemeli — bir kovaya girmeli."""
		self.assertEqual(rum.record_rejection(RuntimeError("beklenmedik")), rum.SEBEP_GOVDE)
		self.assertEqual(mm.RUM_REJECTED_TOTAL.deger(reason=rum.SEBEP_GOVDE), 1.0)

	def test_tum_sebep_kodlari_kararli_listede(self):
		"""Metrik etiketi bir API'dir; liste dışında bir kod üretilmemeli."""
		for kod in rum.REJECT_REASONS:
			self.assertRegex(kod, r"^[a-z_]+$")

	def test_hata_mesaji_ile_kod_ayri(self):
		with self.assertRaises(rum.RumError) as t:
			rum.validate({"metric": "LCP", "value": "abc", "route": "/", "device_class": "phone",
						"viewport_width": 390, "sample_rate": 1.0})
		self.assertEqual(t.exception.kod, rum.SEBEP_DEGER)
		self.assertNotEqual(str(t.exception), t.exception.kod)


class DoctypeTasarimi(unittest.TestCase):
	def test_alanlar_rumsample_ile_birebir(self):
		self.assertEqual(rum.doctype_matches_sample(), ())

	def test_hicbir_yasak_alan_semada_yok(self):
		adlar = set(rum.doctype_field_names())
		for yasak in rum.FORBIDDEN_FIELDS:
			self.assertNotIn(yasak, adlar)

	def test_link_alani_yok(self):
		"""Kayıt hiçbir kullanıcıya/belgeye bağlanamamalı — şemayla, disiplinle değil."""
		for _ad, tur, _not, _idx in rum.DOCTYPE_FIELDS:
			self.assertNotIn(tur, ("Link", "Dynamic Link"))

	def test_indeksler_sorgulanan_alanlarda(self):
		indeksler = set(rum.DOCTYPE_DESIGN["indexes"])
		self.assertTrue({"metric", "route", "device_class", "creation"} <= indeksler)

	def test_saklama_suresi_sinirli(self):
		"""KVKK m.4/2-d: süresiz saklamanın analitik karşılığı yok."""
		self.assertEqual(rum.DOCTYPE_DESIGN["retention_days"], 30)

	def test_izin_matrisi_dar(self):
		roller = {p["role"] for p in rum.DOCTYPE_DESIGN["permissions"]}
		self.assertEqual(roller, {"System Manager"})
		for p in rum.DOCTYPE_DESIGN["permissions"]:
			self.assertNotIn("write", p)

	def test_select_secenekleri_kod_sabitleriyle_ayni(self):
		"""Şema kopyası sürüklenirse rota/cihaz listeleri sessizce ayrışır."""
		harita = {ad: secenek for ad, _tur, secenek, _idx in rum.DOCTYPE_FIELDS}
		self.assertEqual(harita["metric"].split("\n"), list(rum.METRICS))
		self.assertEqual(harita["route"].split("\n"), list(rum.ROUTE_TEMPLATES))
		self.assertEqual(harita["device_class"].split("\n"), list(rum.DEVICE_CLASSES))


if __name__ == "__main__":
	unittest.main(verbosity=2)
