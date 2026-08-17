"""Medya kuyruk işleri ortak sözleşmesi — durum, backoff, kayıp iş (TUR-296).

`media/jobs.py` politika modülü ve onu kullanan toplu işlerin (`media/runner.py`)
iş SEVİYESİNDEKİ başarısızlık davranışı. Dosya seviyesindeki hatalar (bir
görselin bozuk çıkması) burada değil — onlar zaten `partial` ile raporlanıyor
ve kendi testleri var.

Buradaki asıl soru: iş bir bütün olarak yürüyemediğinde ekran ne görüyor?
Önceden "çalışıyor"da asılı kalıyordu (Redis TTL'i dolana kadar bir saat),
oysa çalışan bir şey yoktu.

    docker exec -w /home/frappe/frappe-bench istoc-backend bench \
        --site tradehub.localhost run-tests \
        --module tradehub_core.tests.test_media_jobs
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, now_datetime

from tradehub_core.media import jobs, runner


class TestPolitika(FrappeTestCase):
	"""Unit — politika sayıları kendi içinde tutarlı mı."""

	def test_backoff_listesi_deneme_hakkiyla_uyumlu(self):
		# Son denemeden sonra beklenecek bir şey yok: liste tam bir kısa olmalı.
		# Uyuşmazsa ya boşuna bekleriz ya da son bekleme hiç uygulanmaz.
		self.assertEqual(len(jobs.BACKOFF_SECONDS), jobs.MAX_ATTEMPTS - 1)

	def test_backoff_artan(self):
		degerler = [jobs.backoff_seconds(i) for i in range(1, jobs.MAX_ATTEMPTS)]
		self.assertEqual(degerler, sorted(degerler))

	def test_backoff_sifir_ve_negatif_denemede_patlamaz(self):
		# Monkey: sayaç bozulursa politika çökmemeli, ilk beklemeye düşmeli.
		self.assertEqual(jobs.backoff_seconds(0), jobs.BACKOFF_SECONDS[0])
		self.assertEqual(jobs.backoff_seconds(-5), jobs.BACKOFF_SECONDS[0])

	def test_bos_damga_hemen_demek(self):
		# Planı olmayan iş bekletilmez.
		self.assertTrue(jobs.is_due(None))
		self.assertTrue(jobs.is_due(""))

	def test_gelecekteki_damga_beklemede(self):
		self.assertFalse(jobs.is_due(add_to_date(now_datetime(), seconds=120)))

	def test_damgasiz_is_kayip_sayilir(self):
		# Kör nokta olmasın: damga yazılamadan düşen worker da yakalanmalı.
		self.assertTrue(jobs.is_stale(None))

	def test_taze_is_kayip_sayilmaz(self):
		self.assertFalse(jobs.is_stale(now_datetime()))

	def test_supurme_periyodu_backoff_tan_kisa(self):
		# Backoff çözünürlüğü süpürme periyodundan ince olamaz; ince yazarsak
		# belgede yazan süre ile gerçekte beklenen süre ayrışır.
		self.assertLessEqual(jobs.SWEEP_EVERY_SECONDS, min(jobs.BACKOFF_SECONDS))

	def test_terminal_durumlar_running_i_icermez(self):
		self.assertNotIn(jobs.STATE_RUNNING, jobs.TERMINAL_STATES)
		self.assertIn(jobs.STATE_ERROR, jobs.TERMINAL_STATES)


class TestTopluIsSeviyeHatasi(FrappeTestCase):
	"""Integration — iş yürüyemezse ekran "çalışıyor"da asılı kalmaz."""

	def setUp(self):
		self.job_key = frappe.generate_hash(length=10)
		self.addCleanup(lambda: frappe.cache.delete_value(runner.progress_key(self.job_key)))

	def _oku(self) -> dict:
		"""İlerlemeyi Redis'ten oku — istek-içi cache'i atlayarak.

		Frappe tuzağı: `cache.get_value` bir MISS'i de `frappe.local.cache`'e
		yazıyor, `set_value` ise `expires_in_sec` verildiğinde orayı
		TAZELEMİYOR. Aynı süreçte önce "yok" okuyup sonra yazarsak, kendi
		yazdığımızı geri okuyamıyoruz (değer Redis'te doğru duruyor).
		Sahada sorun değil — yoklama ayrı bir istekte çalışıyor ve orada
		local cache tertemiz. Testte ise ikisi aynı süreçte.
		"""
		frappe.local.cache.clear()
		return runner.read_progress(self.job_key)

	def test_optimize_isi_cokerse_error_yazilir_ve_hata_yutulmaz(self):
		with mock.patch(
			"tradehub_core.media.runner.presets.resolve",
			side_effect=RuntimeError("preset çözülemedi"),
		):
			with self.assertRaises(RuntimeError):
				runner.run_batch(["FILE-YOK"], job_key=self.job_key)

		durum = self._oku()
		self.assertEqual(durum["state"], jobs.STATE_ERROR)
		# Ön yüz `error`'ı zaten terminal sayıyor — yoklama durur.
		self.assertIn(durum["state"], jobs.TERMINAL_STATES)

	def test_geri_alma_isi_cokerse_error_yazilir(self):
		# Çökme işin SONUNDA (denetim yazımında) — o ana kadar ilerleme
		# "completed" yazılmıştı; sarmalayıcı bunu `error`'a çevirmeli, yoksa
		# ekran başarısız biten işi başarılı gösterir.
		with mock.patch(
			"tradehub_core.media.runner.audit.log_media_batch",
			side_effect=RuntimeError("denetim yazılamadı"),
		):
			with self.assertRaises(RuntimeError):
				runner.restore_batch([], job_key=self.job_key)

		durum = self._oku()
		self.assertEqual(durum["state"], jobs.STATE_ERROR)

	def test_normal_is_completed_yazar(self):
		# Regresyon: sarmalayıcı başarı yolunu değiştirmemeli.
		with mock.patch("tradehub_core.media.runner.audit.log_media_batch"):
			sonuc = runner.run_batch([], job_key=self.job_key)
		self.assertEqual(sonuc["state"], jobs.STATE_COMPLETED)
		self.assertEqual(self._oku()["state"], jobs.STATE_COMPLETED)


if __name__ == "__main__":
	import unittest

	unittest.main()
