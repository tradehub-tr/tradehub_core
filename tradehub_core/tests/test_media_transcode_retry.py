"""Video transcode retry + dead-letter + görünürlük testleri (TUR-296).

Kapsam — istenen test eksenlerine göre:

  Unit          : sayaç artışı, retry kuyruklama, dead-letter eşiği,
                  `retry_failed` durum kuralları, `enqueue_transcode` sıfırlama
  Integration   : `inventory.list_files` çıktısında `video_status`
  API           : `seller_media.retry_video`, `media_admin.retry_transcode`
  Database      : sayaç kalıcılığı, patch idempotency
  Auth          : uçlar `@frappe.whitelist` — Guest'e kapalı (varsayılan)
  Authorization : sahiplik (satıcı) ve rol (yönetici) reddi
  Validation    : failed olmayan durumda ret, olmayan/bozuk dosya adresi (monkey)
  E2E           : upload → processing → 3 hata → failed → elle retry → ready
  Error/recovery: ffmpeg yokluğu, geçici dosya temizliği, kuyruktayken silinen dosya

`subprocess.run` ve `frappe.enqueue` HER ZAMAN mock'lanır: gerçek ffmpeg
çağrılmaz, gerçek RQ kuyruğuna iş atılmaz (dev konteynerdeki worker'lar test
dosyasını gerçekten işlemeye kalkardı).

    docker exec -w /home/frappe/frappe-bench istoc-backend bench \
        --site tradehub.localhost run-tests \
        --module tradehub_core.tests.test_media_transcode_retry
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin, seller_media
from tradehub_core.media import inventory, transcode


def _yeni_video_dosyasi(file_name: str, content: bytes | None = None):
	# İçerik dosya adından türetiliyor — SABİT içerik kullanılamaz: içerik-adresli
	# adlandırma (WP4, `media/naming.py`) aynı baytları aynı `file_url`'e eşler ve
	# testlerin dosyaları birbirinin kaydına yazmaya başlar (yaşandı: sayaç
	# başka testin kaydında artıyordu).
	icerik = content if content is not None else f"sahte video icerigi {file_name}".encode()
	doc = frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "is_private": 0, "content": icerik}
	)
	doc.insert(ignore_permissions=True)
	return doc


def _durum(name: str) -> str | None:
	return frappe.db.get_value("File", name, "th_media_video_status")


def _deneme(name: str) -> int:
	return int(frappe.db.get_value("File", name, "th_media_transcode_attempts") or 0)


class TestRetrySayaci(FrappeTestCase):
	"""Unit — başarısız denemeler sayılır, hak bitince dead-letter."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("retry-sayac-1.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def _basarisiz_calistir(self):
		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode._run_transcode(self.doc.file_url)
		return mock_enqueue

	def test_ilk_hata_sayaci_bir_yapar_ve_processing_tutar(self):
		mock_enqueue = self._basarisiz_calistir()
		self.assertEqual(_deneme(self.doc.name), 1)
		self.assertNotEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)
		mock_enqueue.assert_called_once()
		_args, kwargs = mock_enqueue.call_args
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertEqual(kwargs.get("file_url"), self.doc.file_url)

	def test_hak_bitince_failed_yazilir_ve_kuyruga_geri_konmaz(self):
		# Son deneme: sayaç MAX-1'de → bu hata dead-letter'a düşürmeli.
		frappe.db.set_value(
			"File",
			self.doc.name,
			"th_media_transcode_attempts",
			transcode.MAX_TRANSCODE_ATTEMPTS - 1,
		)
		mock_enqueue = self._basarisiz_calistir()
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)
		self.assertEqual(_deneme(self.doc.name), transcode.MAX_TRANSCODE_ATTEMPTS)
		mock_enqueue.assert_not_called()

	def test_dead_letter_audit_kaydinda_deneme_sayisi_var(self):
		frappe.db.set_value(
			"File",
			self.doc.name,
			"th_media_transcode_attempts",
			transcode.MAX_TRANSCODE_ATTEMPTS - 1,
		)
		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
			mock.patch("tradehub_core.media.transcode.audit.log_media_event") as mock_audit,
		):
			transcode._run_transcode(self.doc.file_url)

		mock_audit.assert_called_once()
		_args, kwargs = mock_audit.call_args
		self.assertIn("video_transcode_failed", kwargs.get("reason") or "")
		self.assertEqual(
			(kwargs.get("context") or {}).get("attempts"), transcode.MAX_TRANSCODE_ATTEMPTS
		)

	def test_enqueue_transcode_sayaci_sifirlar(self):
		# Önceki işten sayaç kalmış olsun — yeni yükleme temiz başlamalı.
		frappe.db.set_value("File", self.doc.name, "th_media_transcode_attempts", 2)
		with (
			mock.patch("tradehub_core.media.transcode.needs_transcode", return_value=True),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode.enqueue_transcode(self.doc.file_url)
		self.assertEqual(_deneme(self.doc.name), 0)

	def test_basarili_calistirma_sayaca_dokunmaz_ready_yazar(self):
		# Regresyon: başarı yolu retry eklendikten sonra da aynı.
		def _sahte_ffmpeg(cmd, **kwargs):
			dst = cmd[-1]
			with open(dst, "wb") as f:
				f.write(b"sahte transcode edilmis veri")
			return mock.Mock(returncode=0)

		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run", side_effect=_sahte_ffmpeg
		):
			transcode._run_transcode(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_READY)


class TestRetryFailedElleTetikleme(FrappeTestCase):
	"""Unit + validation — `retry_failed` yalnız dead-letter'ı kabul eder."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("retry-elle-1.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_failed_dosya_sifirlanip_kuyruga_konur(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)
		frappe.db.set_value(
			"File",
			self.doc.name,
			"th_media_transcode_attempts",
			transcode.MAX_TRANSCODE_ATTEMPTS,
		)
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			sonuc = transcode.retry_failed(self.doc.file_url)

		self.assertEqual(sonuc["status"], transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_deneme(self.doc.name), 0)
		mock_enqueue.assert_called_once()

	def test_processing_dosya_reddedilir(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_PROCESSING
		)
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed(self.doc.file_url)

	def test_ready_dosya_reddedilir(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_READY
		)
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed(self.doc.file_url)

	def test_durumu_bos_dosya_reddedilir(self):
		# Video değil ya da hiç kuyruğa girmemiş — "yeniden dene" anlamsız.
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed(self.doc.file_url)

	def test_olmayan_dosya_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			transcode.retry_failed("/files/boyle-bir-dosya-yok.mp4")

	def test_monkey_bozuk_adresler_kontrollu_hata_verir(self):
		# Monkey: anlamsız girdiler sessizce yutulmamalı, kontrolsüz de
		# patlamamalı — hepsi frappe.ValidationError ile reddedilmeli.
		for bozuk in ("", "   ", "../../etc/passwd", "/files/", "%00", "/files/😀.mp4"):
			with self.assertRaises(frappe.ValidationError, msg=f"girdi: {bozuk!r}"):
				transcode.retry_failed(bozuk)


class TestInventoryVideoStatus(FrappeTestCase):
	"""Integration + database — durum alanı envanter çıktısına akar."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("inv-video-status.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_list_files_video_status_dondurur(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)
		sonuc = inventory.list_files(page=1, page_size=10, search="inv-video-status")
		satirlar = [r for r in sonuc["items"] if r["file_url"] == self.doc.file_url]
		self.assertEqual(len(satirlar), 1)
		self.assertEqual(satirlar[0].get("video_status"), transcode.VIDEO_STATUS_FAILED)

	def test_sayac_db_de_kalici(self):
		frappe.db.set_value("File", self.doc.name, "th_media_transcode_attempts", 2)
		# Doc yeniden yüklendiğinde de aynı değer okunmalı (alan gerçekten
		# şemada, bellekte değil).
		yeniden = frappe.get_doc("File", self.doc.name)
		self.assertEqual(int(yeniden.get("th_media_transcode_attempts") or 0), 2)

	def test_patch_iki_kez_calisinca_kirilmaz(self):
		# Idempotency: alan zaten var — patch yeniden koşulduğunda hata yok ve
		# "created" boş dönmeli.
		from tradehub_core.patches import v15_9_18_media_transcode_attempts as patch

		sonuc = patch.execute()
		self.assertEqual(sonuc.get("created"), [])


class TestSellerRetryVideoAPI(FrappeTestCase):
	"""API + authorization — satıcı ucu sahiplik ister."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("api-satici-video.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)

	def test_kendi_dosyasinda_retry_calisir_ve_audit_yazar(self):
		with (
			mock.patch(
				"tradehub_core.api.seller_media.ownership.current_store",
				return_value="MAGAZA-001",
			),
			mock.patch("tradehub_core.api.seller_media.ownership.assert_owns"),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
			mock.patch("tradehub_core.api.seller_media.audit.log_media_event") as mock_audit,
		):
			sonuc = seller_media.retry_video(self.doc.file_url)

		self.assertEqual(sonuc["status"], transcode.VIDEO_STATUS_PROCESSING)
		mock_audit.assert_called_once()
		_args, kwargs = mock_audit.call_args
		self.assertEqual(kwargs.get("tenant"), "MAGAZA-001")
		self.assertTrue((kwargs.get("context") or {}).get("manual_retry"))

	def test_baskasinin_dosyasinda_sahiplik_reddi(self):
		with (
			mock.patch(
				"tradehub_core.api.seller_media.ownership.current_store",
				return_value="MAGAZA-001",
			),
			mock.patch(
				"tradehub_core.api.seller_media.ownership.assert_owns",
				side_effect=frappe.PermissionError("dosya bu mağazanın değil"),
			),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			with self.assertRaises(frappe.PermissionError):
				seller_media.retry_video(self.doc.file_url)
		# Yetki düşerken kuyruğa hiçbir şey gitmemeli.
		mock_enqueue.assert_not_called()

	def test_magazasiz_oturum_reddedilir(self):
		# Auth: mağazası olmayan oturum satıcı ucuna giremez (`_store` reddi).
		with mock.patch(
			"tradehub_core.api.seller_media.ownership.current_store",
			side_effect=frappe.PermissionError("mağaza yok"),
		):
			with self.assertRaises(frappe.PermissionError):
				seller_media.retry_video(self.doc.file_url)


class TestAdminRetryTranscodeAPI(FrappeTestCase):
	"""API + authorization — yönetici ucu rol ister."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("api-yonetici-video.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_FAILED
		)

	def test_rolu_olmayan_kullanici_reddedilir(self):
		# `frappe.only_for` hem Administrator'ı hem `flags.in_test`'i atlar
		# (frappe/__init__.py:953) — rol reddini gerçekten sınamak için ikisi de
		# geçici olarak kapatılır.
		frappe.set_user("Guest")
		self.addCleanup(lambda: frappe.set_user("Administrator"))
		onceki = frappe.flags.in_test
		frappe.flags.in_test = False
		self.addCleanup(lambda: setattr(frappe.flags, "in_test", onceki))
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			with self.assertRaises(frappe.PermissionError):
				media_admin.retry_transcode(self.doc.file_url)
		mock_enqueue.assert_not_called()

	def test_bos_adres_reddedilir(self):
		with self.assertRaises(frappe.ValidationError):
			media_admin.retry_transcode("")

	def test_yonetici_retry_calisir(self):
		with (
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
			mock.patch("tradehub_core.api.media_admin.audit.log_media_event") as mock_audit,
		):
			sonuc = media_admin.retry_transcode(self.doc.file_url)
		self.assertEqual(sonuc["status"], transcode.VIDEO_STATUS_PROCESSING)
		mock_enqueue.assert_called_once()
		mock_audit.assert_called_once()


class TestUctanUcaVeToparlanma(FrappeTestCase):
	"""E2E + error/recovery — yaşam döngüsünün tamamı tek senaryoda.

	upload sonrası: processing → 3 ardışık hata → failed (dead-letter) →
	elle retry → başarılı çalıştırma → ready. Her adımda durum ve sayaç
	doğrulanır; geçici dosya hata dallarında diskte kalmamalı.
	"""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("e2e-video.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def _hata_turu(self, exc):
		with (
			mock.patch("tradehub_core.media.transcode.subprocess.run", side_effect=exc),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode._run_transcode(self.doc.file_url)

	def test_tam_dongu(self):
		# 1) Yükleme sonrası kuyruğa giriş.
		with (
			mock.patch("tradehub_core.media.transcode.needs_transcode", return_value=True),
			mock.patch("tradehub_core.media.transcode.frappe.enqueue"),
		):
			transcode.enqueue_transcode(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_deneme(self.doc.name), 0)

		# 2) Üç farklı hata türü — recovery davranışı hepsinde aynı olmalı:
		#    ffmpeg imajdan kalkmış, ffmpeg çökmüş, zaman aşımı.
		import subprocess as sp

		self._hata_turu(FileNotFoundError("ffmpeg yok"))
		self.assertEqual(_deneme(self.doc.name), 1)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)

		self._hata_turu(sp.CalledProcessError(1, ["ffmpeg"]))
		self.assertEqual(_deneme(self.doc.name), 2)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)

		self._hata_turu(sp.TimeoutExpired(["ffmpeg"], 1700))
		self.assertEqual(_deneme(self.doc.name), 3)
		# 3) Hak bitti — dead-letter.
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_FAILED)

		# 4) Geçici dosya hata dallarından artakalmamış olmalı.
		import os

		src = frappe.get_doc("File", self.doc.name).get_full_path()
		self.assertFalse(os.path.exists(f"{src}.transcoding.webm"))

		# 5) İnsan devreye girer: elle retry → tekrar processing, sayaç 0.
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue"):
			transcode.retry_failed(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_PROCESSING)
		self.assertEqual(_deneme(self.doc.name), 0)

		# 6) Bu kez ffmpeg çalışır → ready.
		def _sahte_ffmpeg(cmd, **kwargs):
			dst = cmd[-1]
			with open(dst, "wb") as f:
				f.write(b"sahte transcode edilmis veri")
			return mock.Mock(returncode=0)

		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run", side_effect=_sahte_ffmpeg
		):
			transcode._run_transcode(self.doc.file_url)
		self.assertEqual(_durum(self.doc.name), transcode.VIDEO_STATUS_READY)

	def test_kuyruktayken_silinen_dosya_worker_i_dusurmez(self):
		# Recovery: iş kuyruğa girdikten sonra satıcı dosyayı bırakabilir.
		frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		with mock.patch("tradehub_core.media.transcode.subprocess.run") as mock_run:
			transcode._run_transcode(self.doc.file_url)  # patlamamalı
		mock_run.assert_not_called()


if __name__ == "__main__":
	import unittest

	unittest.main()
