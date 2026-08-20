"""T-133/T-124 — RUM toplama koşucusu testleri (`tradehub_core.api.rum.aggregate_samples`).

`tests/test_rum_metrics.py` `rum.aggregate()→to_metrics()` köprüsünü bellek
içinde sınıyor; bu dosya o köprüyü GERÇEK tablodan besleyen koşucuyu sınar:

1. Boş pencere → sıfır iş: hiçbir metrik yazılmaz, damga İLERLEMEZ.
2. Örnekli pencere → doğru sayım: p75, sayaç ve tahmini popülasyon satırlardan.
3. Çift koşu → sayaç ŞİŞMEZ (idempotens): aynı pencere de, satırsız yeni
   pencere de sayaca ikinci kez yazamaz.
4. Sonraki pencere yalnız YENİ satırları işler (pencereler ayrık).

Testler `parcayi_yaz=False` ile koşar: test sürecinin kayıt defteri paylaşılan
parça dizinine yazılıp gerçek `/metrics` çıktısını kirletmesin.

Koşturma:
	docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
		run-tests --module tradehub_core.tests.test_rum_aggregate
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from tradehub_core.api import rum as rum_api
from tradehub_core.media.pipeline.delivery import rum
from tradehub_core.media.pipeline.observability import metrics as mm

#: Testlerin yazdığı kova — `rum.METRIC_GROUP_BY` etiketleriyle okunur.
ROUTE = "/urun/:slug"
DEVICE = "phone"


def _ornek_yaz(value: float, *, metric: str = "LCP", sample_rate: float = 1.0) -> None:
	"""Uçla aynı yoldan tek örnek yaz: `rum.validate()` → DocType insert.

	`ignore_permissions` gerekçesi uçtakiyle aynı: DocType'ta hiçbir role
	create izni yok, gövde `validate()`in kapalı şemasından geçiyor.
	"""
	sample = rum.validate(
		{
			"metric": metric,
			"value": value,
			"route": ROUTE,
			"device_class": DEVICE,
			"viewport_width": 390,
			"sample_rate": sample_rate,
			"connection": "4g",
		}
	)
	frappe.get_doc({"doctype": rum_api.DOCTYPE, **sample.to_dict()}).insert(ignore_permissions=True)


def _kos(son: str) -> dict[str, Any]:
	return rum_api.aggregate_samples(pencere_sonu=son, parcayi_yaz=False)


def _sayac(rating: str = "good") -> float:
	return mm.RUM_SAMPLES_TOTAL.deger(metric="LCP", route=ROUTE, device_class=DEVICE, rating=rating)


def _p75() -> float:
	return mm.RUM_P75_MS.deger(metric="LCP", route=ROUTE, device_class=DEVICE)


class ToplamaKosucusu(FrappeTestCase):
	def setUp(self) -> None:
		super().setUp()
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)
		# Damgayı ŞİMDİYE sabitle: tabloda önceki koşulardan/elle denemelerden
		# kalan satırlar pencere DIŞINDA kalsın — test yalnız kendi yazdığını
		# görsün. FrappeTestCase işlemi geri sardığı için kalıcı iz kalmaz.
		self.baslangic = str(now_datetime())
		frappe.db.set_global(rum_api.AGGREGATE_HIGH_WATER_KEY, self.baslangic)

	def test_bos_pencere_sifir_is(self) -> None:
		sonuc = _kos(str(now_datetime()))
		self.assertEqual(sonuc["okunan"], 0)
		self.assertEqual(sonuc["seri"], 0)
		self.assertEqual(sonuc["atlanan"], 0)
		self.assertEqual(mm.RUM_SAMPLES_TOTAL.seri_sayisi(), 0)
		self.assertEqual(mm.RUM_P75_MS.seri_sayisi(), 0)
		# Boş pencerede damga İLERLEMEZ.
		self.assertEqual(str(frappe.db.get_global(rum_api.AGGREGATE_HIGH_WATER_KEY)), self.baslangic)

	def test_ornekli_pencere_dogru_sayim(self) -> None:
		for deger in (800.0, 900.0, 1000.0, 1200.0):  # p75 = 1000 → good
			_ornek_yaz(deger)
		son = str(now_datetime())
		sonuc = _kos(son)
		self.assertEqual(sonuc["okunan"], 4)
		self.assertEqual(sonuc["atlanan"], 0)
		self.assertEqual(sonuc["seri"], 1)
		self.assertEqual(_p75(), 1000.0)
		self.assertEqual(_sayac("good"), 4.0)
		self.assertEqual(
			mm.RUM_ESTIMATED_POPULATION.deger(metric="LCP", route=ROUTE, device_class=DEVICE),
			4.0,
		)
		# Damga pencere sonuna İLERLEDİ.
		self.assertEqual(str(frappe.db.get_global(rum_api.AGGREGATE_HIGH_WATER_KEY)), son)

	def test_ornekleme_orani_populasyona_yansir(self) -> None:
		"""%10 örneklemde ham sayı 2, tahmini popülasyon 20 (1/oran toplamı)."""
		_ornek_yaz(1000.0, sample_rate=0.1)
		_ornek_yaz(900.0, sample_rate=0.1)
		_kos(str(now_datetime()))
		self.assertEqual(_sayac("good"), 2.0)
		self.assertEqual(
			mm.RUM_ESTIMATED_POPULATION.deger(metric="LCP", route=ROUTE, device_class=DEVICE),
			20.0,
		)

	def test_cift_kosu_sisirmiyor(self) -> None:
		"""İdempotens: aynı pencere de, satırsız yeni pencere de sayacı katlamaz."""
		_ornek_yaz(800.0)
		_ornek_yaz(900.0)
		son1 = str(now_datetime())
		self.assertEqual(_kos(son1)["okunan"], 2)
		self.assertEqual(_sayac("good"), 2.0)
		self.assertEqual(_p75(), 900.0)

		# Aynı pencere ikinci kez → İŞ YOK.
		tekrar = _kos(son1)
		self.assertEqual(tekrar["okunan"], 0)
		self.assertEqual(tekrar["seri"], 0)
		self.assertEqual(_sayac("good"), 2.0)

		# Satırsız YENİ pencere → yine iş yok, sayaç aynı.
		self.assertEqual(_kos(str(now_datetime()))["okunan"], 0)
		self.assertEqual(_sayac("good"), 2.0)
		self.assertEqual(_p75(), 900.0)

	def test_sonraki_pencere_yalniz_yenileri_isler(self) -> None:
		_ornek_yaz(800.0)
		self.assertEqual(_kos(str(now_datetime()))["okunan"], 1)
		self.assertEqual(_sayac("good"), 1.0)

		_ornek_yaz(1200.0)
		sonuc = _kos(str(now_datetime()))
		self.assertEqual(sonuc["okunan"], 1)  # yalnız yeni satır
		self.assertEqual(_sayac("good"), 2.0)  # sayaç birikir: 1 + 1
		self.assertEqual(_p75(), 1200.0)  # gösterge SON pencerenin p75'i
