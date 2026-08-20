"""T-133 — alarm kuralı ve pano üreticisi (alerts.py) testleri.

Bu dosyanın var oluş sebebi tek bir arıza sınıfı: **sessiz kopma**. Bir metrik
adı değiştiğinde ya da bir alarm var olmayan bir metriğe atıf yaptığında,
Prometheus hata vermez — kural hiç ateşlenmez ve panel boş kalır. "Alarm var"
denir, gerçekte hiçbir şey izlenmiyordur.

`test_hicbir_alarm_tanimsiz_metrige_atif_yapmaz` tam olarak bu kopmayı
düşürür ve metrik adı değiştiren bir sonraki commit'te KIRMIZI olur.

Runbook testleri bir EKSİĞİ kayıt altına alır: bugün 16 runbook dosyasının
16'sı da yok. Test bunu "geçti" diye örtmez; sayıyı ölçer ve dosyalar
yazıldığında güncellenmesi gerektiğini söyler.

Çalıştırma:

    python3 -m unittest tradehub_core.tests.test_observability_alerts -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.observability import alerts as al  # noqa: E402
from tradehub_core.media.pipeline.observability import metrics as mm  # noqa: E402


class KuralTutarliligi(unittest.TestCase):
	def test_hicbir_alarm_tanimsiz_metrige_atif_yapmaz(self):
		sonuc = al.dogrula()
		self.assertEqual(sonuc["unknown_metrics"], [], f"kopuk kural: {sonuc['unknown_metrics']}")

	def test_alarm_adlari_tekil(self):
		self.assertEqual(al.dogrula()["duplicate_names"], [])

	def test_her_alarmin_runbooku_var(self):
		for a in al.ALARMLAR:
			self.assertTrue(a.runbook, f"{a.ad} runbook'suz")
			self.assertNotIn(" ", a.runbook, f"{a.ad} runbook slug'inda bosluk var")

	def test_her_alarmin_esik_kaynagi_yazili(self):
		"""Gerekçesiz eşik, altı ay sonra dokunulamayan bir sayıdır."""
		for a in al.ALARMLAR:
			self.assertTrue(a.kaynak.strip(), f"{a.ad} esik kaynagi bos")

	def test_dis_standart_esikler_isaretli(self):
		"""CWV eşikleri bu projede ÖLÇÜLMEDİ; kaynak alanı bunu söylemeli."""
		for ad in ("RumLcpRegression", "RumClsRegression", "RumInpRegression"):
			alarm = next(a for a in al.ALARMLAR if a.ad == ad)
			self.assertIn("DIŞ STANDART", alarm.kaynak)

	def test_severity_bilinen_iki_degerden_biri(self):
		for a in al.ALARMLAR:
			self.assertIn(a.severity, (al.SEVERITY_CRITICAL, al.SEVERITY_WARNING))

	def test_metrik_adlari_gercekten_kayit_defterinde(self):
		tanimli = {m.ad for m in mm.REGISTRY.metrikler()}
		for a in al.ALARMLAR:
			for metrik in a.metrikler:
				self.assertIn(metrik, tanimli)

	def test_ifade_atif_yapilan_metrigi_gercekten_iceriyor(self):
		"""`metrikler` alanı elle yazılıyor; ifadeyle uyuşmazsa doğrulama yalan söyler."""
		for a in al.ALARMLAR:
			for metrik in a.metrikler:
				self.assertIn(metrik, a.ifade, f"{a.ad}: {metrik} ifadede geçmiyor")


class PrometheusKurallari(unittest.TestCase):
	def test_yaml_deterministik(self):
		self.assertEqual(al.to_prometheus_rules(), al.to_prometheus_rules())

	def test_yaml_tirnak_kacirir(self):
		"""PromQL `{outcome="rejected"}` içerir; kaçırılmazsa YAML bozulur."""
		metin = al.to_prometheus_rules()
		self.assertIn('outcome=\\"rejected\\"', metin)
		self.assertNotIn('expr: "sum(rate(media_upload_total{outcome="', metin)

	def test_her_alarm_yamlde_gorunur(self):
		metin = al.to_prometheus_rules()
		for a in al.ALARMLAR:
			self.assertIn(f'- alert: "{a.ad}"', metin)

	def test_runbook_url_annotasyonu_var(self):
		metin = al.to_prometheus_rules()
		self.assertEqual(metin.count("runbook_url:"), len(al.ALARMLAR))

	def test_uretilmis_dosya_uyarisi_basta(self):
		self.assertTrue(al.to_prometheus_rules().startswith("# ÜRETİLMİŞ DOSYA"))

	def test_ozel_karakterli_alarm_kacirilir(self):
		alarm = al.Alarm(
			ad="Test",
			ifade='x{a="b"} > 0',
			sure="5m",
			severity=al.SEVERITY_WARNING,
			ozet='tirnak " ve ters bolu \\ var',
			aciklama="satir\nsonu",
			runbook="test",
			metrikler=(),
			kaynak="test",
		)
		metin = al.to_prometheus_rules([alarm])
		self.assertIn('\\"', metin)
		self.assertIn("\\\\", metin)
		# Gerçek yeni satır kural gövdesini ikiye bölerdi.
		self.assertNotIn("satir\nsonu", metin)


class GrafanaPanosu(unittest.TestCase):
	def test_uid_sabit(self):
		self.assertEqual(al.grafana_dashboard()["uid"], "media-engine-t133")

	def test_panel_sayisi_tabloyla_ayni(self):
		self.assertEqual(len(al.grafana_dashboard()["panels"]), len(al.PANELLER))

	def test_json_deterministik_ve_gecerli(self):
		metin = al.grafana_dashboard_json()
		self.assertEqual(metin, al.grafana_dashboard_json())
		json.loads(metin)

	def test_panel_ifadeleri_tanimli_metrik_kullanir(self):
		"""Pano da kural gibi metrik adına bağlı; boş panel sessiz arızadır."""
		tanimli = {m.ad for m in mm.REGISTRY.metrikler()}
		for _ad, ifade, _birim in al.PANELLER:
			eslesen = [m for m in tanimli if m in ifade or f"{m}_bucket" in ifade]
			self.assertTrue(eslesen, f"panel tanimsiz metrige bakiyor: {ifade}")


class Runbooklar(unittest.TestCase):
	def test_bugun_hicbir_runbook_dosyasi_yok(self):
		"""ÖLÇÜM: `docs/ops/runbooks/` dizini yok — 16/16 eksik.

		Bu test bir eksiği kayıt altına alır. Runbook'lar yazıldığında KIRMIZI
		olacak ve güncellenmesi gerekecek; kasıtlı bir hatırlatıcıdır.
		"""
		eksik = al.runbook_gaps(str(ROOT))
		self.assertEqual(len(eksik), len(al.runbook_paths()))
		self.assertEqual(len(eksik), 16)

	def test_runbook_yollari_tekrarsiz_ve_sirali(self):
		yollar = al.runbook_paths()
		self.assertEqual(list(yollar), sorted(set(yollar)))


if __name__ == "__main__":
	unittest.main(verbosity=2)
