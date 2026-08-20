"""K-1 — 5 ölü alarm metriğinin toplayıcı/çağrı-yeri testleri.

`observability/metrics.py` beş seriyi TANIMLIYOR ama hiçbir yer yazmıyordu;
`docs/observability/media-alerts.yml`'deki beş alarm bu serilere bağlı ve seri
boş olduğu için ÖLÜYDÜ. Bu dosya yeni yazıcıların gerçekten yazdığını, ve
KRİTİK olarak, yazıcı ÇAĞRILMAZSA serinin boş kalıp alarmın tetiklenemez
olduğunu (VACUITY) kanıtlar.

Saf kısımlar (`classify_field_coverage`, `set_*`, `jobs.record_terminal`)
frappe GEREKTİRMEZ — metrik kayıt defteri bağımsızdır. IO toplayıcılar
(`count_orphan_files`, `count_unprotected_pii_files`, `discover_media_fields`)
bench/DB gerektirir ve bench ortamında `run_scan` ile elle kanıtlanır (rapora
bkz.), burada değil.

Çalıştırma:

    python3 -m unittest tradehub_core.tests.test_alarm_collectors -v
    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_alarm_collectors
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from tradehub_core.media.pipeline.observability import collectors  # noqa: E402
from tradehub_core.media.pipeline.observability import metrics as mm  # noqa: E402


# ── Saf sınıflandırıcı — frappe yok ─────────────────────────────────────


class SafKapsamSiniflandirma(unittest.TestCase):
	def test_haritali_alan_mapped_sayilir(self):
		k = collectors.classify_field_coverage(
			{"KYC Verification": ("identity_document",)},
			{"KYC Verification": ("identity_document",)},
		)
		self.assertEqual(k["mapped"], 1)
		self.assertEqual(k["unmapped"], 0)
		self.assertEqual(k["gaps"], [])

	def test_haritada_olmayan_alan_unmapped_ve_gap(self):
		"""Haritanın kaçırdığı bir Attach alanı = açık (T-132)."""
		k = collectors.classify_field_coverage(
			{"KYB Verification": ("identity_document",)},
			{"KYB Verification": ("identity_document", "vergi_levhasi")},
		)
		self.assertEqual(k["mapped"], 1)
		self.assertEqual(k["unmapped"], 1)
		self.assertEqual(k["gaps"], [("KYB Verification", "vergi_levhasi")])

	def test_bos_kesif_sifir_kapsam(self):
		k = collectors.classify_field_coverage({"X": ("a",)}, {})
		self.assertEqual((k["mapped"], k["unmapped"]), (0, 0))


# ── Saf yazıcılar — gerçek kayıt defterine yazar ────────────────────────


class SafYazicilar(unittest.TestCase):
	def setUp(self) -> None:
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)

	def test_orphan_gauge_yazilir(self):
		self.assertEqual(collectors.set_orphan_files(1166), 1166)
		self.assertEqual(mm.ORPHAN_FILES.deger(), 1166.0)

	def test_pii_kapsam_iki_seri_yazar(self):
		collectors.set_pii_field_coverage({"mapped": 9, "unmapped": 0})
		self.assertEqual(mm.PII_FIELD_COVERAGE.deger(status="mapped"), 9.0)
		# `unmapped` 0 OLSA BİLE seri yazılır — "0 kaçak" ile "ölçülmedi" ayrı.
		self.assertEqual(mm.PII_FIELD_COVERAGE.deger(status="unmapped"), 0.0)
		self.assertEqual(mm.PII_FIELD_COVERAGE.seri_sayisi(), 2)

	def test_unprotected_gauge_yazilir(self):
		self.assertEqual(collectors.set_pii_unprotected_files(3), 3)
		self.assertEqual(mm.PII_UNPROTECTED_FILES.deger(), 3.0)

	def test_yazicilar_sahte_registry_kabul_eder(self):
		"""`registry` enjeksiyonu — RUM köprüsüyle aynı sözleşme."""
		yerel = mm.Registry(mm.NAMESPACE)
		g = yerel.gauge("orphan_files", "test")
		collectors.set_orphan_files(7, registry=yerel)
		self.assertEqual(g.deger(), 7.0)


# ── VACUITY — toplayıcı çağrılmazsa alarm tetiklenemez ──────────────────


class Vacuity(unittest.TestCase):
	"""Kırmızı kanıt: yazıcı olmadan seri YOK → alarm expr'i boş → hiç ateşlenmez.

	Prometheus boş bir seride `> 0` / `> 1200` kıyasını değerlendiremez; kural
	sessizce hiç tetiklenmez. Bu testler o sessiz ölümü belgeler ve yazıcının
	onu kapattığını gösterir.
	"""

	def setUp(self) -> None:
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)

	def test_orphan_yazilmadan_seri_yok(self):
		# ÖNCE: hiç yazılmadı → seri yok → `media_orphan_files > 1200` boş.
		self.assertEqual(mm.ORPHAN_FILES.seri_sayisi(), 0)
		self.assertNotIn("media_orphan_files", mm.REGISTRY.render())
		# SONRA: yazıldı → seri render edilir, alarm değerlendirilebilir.
		collectors.set_orphan_files(1300)
		self.assertIn("media_orphan_files 1300", mm.REGISTRY.render())

	def test_pii_unmapped_yazilmadan_kapi_bosu(self):
		self.assertEqual(mm.PII_FIELD_COVERAGE.seri_sayisi(), 0)
		collectors.set_pii_field_coverage({"mapped": 9, "unmapped": 2})
		metin = mm.REGISTRY.render()
		# Alarm tam bu satır desenine bağlı: status="unmapped".
		self.assertIn('media_pii_field_coverage{status="unmapped"} 2', metin)

	def test_unprotected_yazilmadan_seri_yok(self):
		self.assertEqual(mm.PII_UNPROTECTED_FILES.seri_sayisi(), 0)
		collectors.set_pii_unprotected_files(3)
		self.assertIn("media_pii_unprotected_files 3", mm.REGISTRY.render())


# ── İş sayaçları — `jobs.record_terminal` (frappe importu gerekir) ──────


class IsSayaci(unittest.TestCase):
	"""`media_job_total` / `media_job_attempts` çağrı yerinde yazılır.

	`media.jobs` `frappe.utils` içe aktarır; bench dışında import edilemez, o
	yüzden frappe yoksa ATLANIR. Bench'te tam koşar.
	"""

	def setUp(self) -> None:
		try:
			from tradehub_core.media import jobs  # noqa: PLC0415
		except Exception as e:  # frappe yok — bench dışı
			self.skipTest(f"jobs importu bench gerektiriyor: {e}")
		self.jobs = jobs
		mm.REGISTRY.temizle()
		self.addCleanup(mm.REGISTRY.temizle)

	def test_terminal_error_job_total_artar(self):
		self.jobs.record_terminal("optimize", self.jobs.STATE_ERROR)
		self.assertEqual(mm.JOB_TOTAL.deger(job="optimize", state="error"), 1.0)

	def test_completed_ve_attempts_yazilir(self):
		self.jobs.record_terminal("optimize", self.jobs.STATE_COMPLETED, attempts=2)
		self.assertEqual(mm.JOB_TOTAL.deger(job="optimize", state="completed"), 1.0)
		ozet = mm.JOB_ATTEMPTS.ozet(job="optimize")
		self.assertEqual(ozet["count"], 1.0)
		self.assertEqual(ozet["sum"], 2.0)

	def test_running_yazilmaz(self):
		"""Terminal olmayan durum sayılmaz — sayaç yalnız sonuç sayar."""
		self.jobs.record_terminal("optimize", self.jobs.STATE_RUNNING)
		self.assertEqual(mm.JOB_TOTAL.seri_sayisi(), 0)
		self.assertEqual(mm.JOB_ATTEMPTS.seri_sayisi(), 0)


# ── Alarm-adı eşleşmesi — ölü alarm sigortası ──────────────────────────


class AlarmAdiEslesme(unittest.TestCase):
	"""Beş yazıcının hedef metrik adları, alarm expr'lerinin okuduğu adlarla
	birebir mi. Ad ayrışırsa alarm sessizce boşalır (metrics.py felsefesi)."""

	def test_bes_seri_tanimli(self):
		tanimli = {m.ad for m in mm.REGISTRY.metrikler()}
		for ad in (
			"media_orphan_files",
			"media_pii_field_coverage",
			"media_pii_unprotected_files",
			"media_job_total",
			"media_job_attempts",
		):
			self.assertIn(ad, tanimli, f"alarm bağlanacak seri tanımsız: {ad}")


if __name__ == "__main__":
	unittest.main(verbosity=2)
