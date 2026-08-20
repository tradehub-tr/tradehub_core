"""T-133 — çok süreçli metrik toplayıcı (exporter.py) testleri.

En önemli test `TekSurecIleAyni`: çok süreçli render, tek süreçli
`Registry.render()` ile BİREBİR aynı metni üretmelidir. İki ayrı renderleyici
olduğu için bu ayrışma sessizce olur — çıktı hâlâ geçerli Prometheus metni
olur, yalnız sayılar ya da kaçırma farklı olur ve kimse fark etmez.

İkinci omurga: birleştirme SEMANTİĞİ. Sayaç toplanır, histogram kova kova
toplanır, gösterge `latest` ile birleşir. Üçü de yanlış yapılabilir ve üçü de
"makul görünen yanlış sayı" üretir.

Çalıştırma:

    python3 -m unittest tradehub_core.tests.test_observability_exporter -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.observability import exporter as ex  # noqa: E402
from tradehub_core.media.pipeline.observability import metrics as mm  # noqa: E402


def yeni_kayit(ad: str = "test") -> mm.Registry:
	"""Testlik kayıt defteri — global `REGISTRY` kirletilmez."""
	return mm.Registry(ad)


class ExporterTestCase(unittest.TestCase):
	def setUp(self) -> None:
		self.dizin = tempfile.mkdtemp(prefix="metrics-test-")
		self.addCleanup(self._temizle)
		# Ortam değişkeni sızmasın: başka bir testin ya da geliştiricinin
		# kabuğundaki `MEDIA_METRICS_DIR`, testin yazdığı dizini gölgeler.
		self._eski = os.environ.pop(ex.DIZIN_DEGISKENI, None)
		if self._eski is not None:
			self.addCleanup(os.environ.__setitem__, ex.DIZIN_DEGISKENI, self._eski)

	def _temizle(self) -> None:
		import shutil

		shutil.rmtree(self.dizin, ignore_errors=True)


class TekSurecIleAyni(ExporterTestCase):
	def test_tek_parca_render_registry_ile_bire_bir(self):
		r = yeni_kayit("t")
		c = r.counter("upload", "Yukleme", etiketler=("slot", "outcome"))
		h = r.histogram("dur", "Sure", etiketler=("op",), buckets=(0.1, 1.0))
		g = r.gauge("live", "Anlik")
		c.inc(slot="product.image", outcome="accepted")
		c.inc(3, slot="brand.logo", outcome="rejected")
		h.observe(0.05, op="probe")
		h.observe(5.0, op="probe")
		g.set(42)

		beklenen = r.render()
		uretilen = ex.render(ex.merge([json.loads(r.dump_json())]))
		self.assertEqual(uretilen, beklenen)

	def test_kacirma_ayni_kalir(self):
		"""Etiket değerindeki tırnak ve ters bölü iki yolda da aynı kaçırılmalı."""
		r = yeni_kayit("t")
		c = r.counter("olay", "x", etiketler=("reason",))
		c.inc(reason='bozuk"deger\\yol')
		self.assertEqual(ex.render(ex.merge([json.loads(r.dump_json())])), r.render())


class Birlestirme(ExporterTestCase):
	def _iki_parca(self) -> None:
		r1 = yeni_kayit("t")
		r1.counter("upload", "x", etiketler=("slot",)).inc(2, slot="a")
		r1.histogram("dur", "y", etiketler=("op",), buckets=(1.0,)).observe(0.5, op="probe")
		r1.gauge("live", "z").set(10)
		ex.write_shard(r1, hedef_dizin=self.dizin, pid=1)

		# `latest` politikası mtime sırasına bakar; aynı saniyede yazılan iki
		# dosyada sıra belirsizleşmesin diye araya ölçülebilir bir fark konur.
		time.sleep(0.02)

		r2 = yeni_kayit("t")
		r2.counter("upload", "x", etiketler=("slot",)).inc(5, slot="a")
		r2.histogram("dur", "y", etiketler=("op",), buckets=(1.0,)).observe(3.0, op="probe")
		r2.gauge("live", "z").set(99)
		ex.write_shard(r2, hedef_dizin=self.dizin, pid=2)

	def test_sayac_toplanir(self):
		self._iki_parca()
		self.assertIn("t_upload_total{slot=\"a\"} 7", ex.collect(self.dizin))

	def test_histogram_kovalari_toplanir_ve_kumulatiftir(self):
		self._iki_parca()
		metin = ex.collect(self.dizin)
		self.assertIn('t_dur_bucket{op="probe",le="1"} 1', metin)
		self.assertIn('t_dur_bucket{op="probe",le="+Inf"} 2', metin)
		self.assertIn('t_dur_count{op="probe"} 2', metin)
		self.assertIn('t_dur_sum{op="probe"} 3.5', metin)

	def test_gosterge_varsayilan_latest(self):
		"""Depolama göstergesini toplamak depoyu iki katı gösterirdi."""
		self._iki_parca()
		self.assertIn("t_live 99", ex.collect(self.dizin))
		self.assertNotIn("t_live 109", ex.collect(self.dizin))

	def test_gosterge_politikasi_sum_secilebilir(self):
		self._iki_parca()
		ex.GAUGE_POLITIKA["t_live"] = "sum"
		self.addCleanup(ex.GAUGE_POLITIKA.pop, "t_live", None)
		self.assertIn("t_live 109", ex.collect(self.dizin))

	def test_farkli_kova_sayisi_kesilmez_uzatilir(self):
		"""Sürüm farkıyla kova sayısı değişirse üst kovalar KAYBOLMAMALI."""
		kisa = {
			"metrics": [
				{
					"name": "t_dur",
					"type": mm.TYPE_HISTOGRAM,
					"help": "y",
					"labels": ["op"],
					"buckets": [1.0, "+Inf"],
					"series": {"probe": {"buckets": [1.0, 0.0], "sum": 0.5, "count": 1.0}},
				}
			]
		}
		uzun = {
			"metrics": [
				{
					"name": "t_dur",
					"type": mm.TYPE_HISTOGRAM,
					"help": "y",
					"labels": ["op"],
					"buckets": [1.0, 5.0, "+Inf"],
					"series": {"probe": {"buckets": [0.0, 1.0, 2.0], "sum": 20.0, "count": 3.0}},
				}
			]
		}
		birlesik = ex.merge([kisa, uzun])
		self.assertEqual(birlesik["t_dur"]["series"]["probe"]["buckets"], [1.0, 1.0, 2.0])
		self.assertEqual(birlesik["t_dur"]["series"]["probe"]["count"], 4.0)


class ParcaDosyalari(ExporterTestCase):
	def test_yazim_atomiktir_gecici_dosya_kalmaz(self):
		r = yeni_kayit("t")
		r.counter("a", "x").inc()
		ex.write_shard(r, hedef_dizin=self.dizin, pid=7)
		kalanlar = [a for a in os.listdir(self.dizin) if a.endswith(".tmp")]
		self.assertEqual(kalanlar, [])

	def test_parca_adi_pid_tasir(self):
		yol = ex.shard_path(self.dizin, namespace="media", pid=1234)
		self.assertTrue(yol.endswith(f"media-1234{ex.UZANTI}"))

	def test_dizin_yoksa_export_error(self):
		r = yeni_kayit("t")
		with self.assertRaises(ex.ExportError):
			ex.write_shard(r, hedef_dizin="")

	def test_bozuk_parca_atlanir_kosum_dusmez(self):
		r = yeni_kayit("t")
		r.counter("upload", "x", etiketler=("slot",)).inc(4, slot="a")
		ex.write_shard(r, hedef_dizin=self.dizin, pid=1)
		with open(os.path.join(self.dizin, f"media-9{ex.UZANTI}"), "w", encoding="utf-8") as f:
			f.write("{ yarim json")
		metin = ex.collect(self.dizin)
		self.assertIn('t_upload_total{slot="a"} 4', metin)

	def test_yas_siniri_eski_parcayi_dusurur(self):
		r = yeni_kayit("t")
		r.counter("upload", "x", etiketler=("slot",)).inc(4, slot="a")
		yol = ex.write_shard(r, hedef_dizin=self.dizin, pid=1)
		eski = time.time() - 7200
		os.utime(yol, (eski, eski))
		self.assertEqual(ex.collect(self.dizin, max_age_s=3600), "")
		self.assertNotEqual(ex.collect(self.dizin), "")

	def test_prune_olu_parcayi_siler(self):
		r = yeni_kayit("t")
		r.counter("a", "x").inc()
		yol = ex.write_shard(r, hedef_dizin=self.dizin, pid=1)
		eski = time.time() - 200000
		os.utime(yol, (eski, eski))
		silinen = ex.prune(self.dizin, max_age_s=86400)
		self.assertEqual(len(silinen), 1)
		self.assertFalse(os.path.exists(yol))

	def test_prune_canli_parcaya_dokunmaz(self):
		r = yeni_kayit("t")
		r.counter("a", "x").inc()
		yol = ex.write_shard(r, hedef_dizin=self.dizin, pid=1)
		self.assertEqual(ex.prune(self.dizin, max_age_s=86400), ())
		self.assertTrue(os.path.exists(yol))


class DizinCozumu(ExporterTestCase):
	def test_ortam_degiskeni_okunur(self):
		os.environ[ex.DIZIN_DEGISKENI] = self.dizin
		self.addCleanup(os.environ.pop, ex.DIZIN_DEGISKENI, None)
		self.assertEqual(ex.dizin(), self.dizin)

	def test_dizin_yoksa_tek_surec_kayit_defterine_duser(self):
		"""Eksik yapılandırma, gözlemlenebilirliği tamamen kaybettirmemeli."""
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)
		mm.UPLOAD_TOTAL.inc(slot="s", kind="image", outcome="accepted", reason="ok")
		metin = ex.collect(None)
		self.assertIn("media_upload_total", metin)
		self.assertFalse(ex.durum(None)["sharded"])

	def test_durum_parca_ve_seri_sayar(self):
		r = yeni_kayit("t")
		r.counter("upload", "x", etiketler=("slot",)).inc(slot="a")
		ex.write_shard(r, hedef_dizin=self.dizin, pid=1)
		d = ex.durum(self.dizin)
		self.assertTrue(d["sharded"])
		self.assertEqual(d["shards"], 1)
		self.assertEqual(d["series"], 1)


class HttpYaniti(ExporterTestCase):
	def test_content_type_prometheus_0_0_4(self):
		_govde, ct = ex.metrics_response(self.dizin)
		self.assertEqual(ct, "text/plain; version=0.0.4; charset=utf-8")

	def test_bos_dizin_bos_govde(self):
		govde, _ct = ex.metrics_response(self.dizin)
		self.assertEqual(govde, "")


if __name__ == "__main__":
	unittest.main(verbosity=2)
