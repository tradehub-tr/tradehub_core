"""Video async transcode kuyruğu testleri (TUR-296/297, WP2).

`enqueue_transcode` gerçek ffmpeg'i ÇAĞIRMAZ — `subprocess.run` mock'lanır
(dev backend imajında ffmpeg yok, bkz. WP2 raporu). İki eksen test edilir:

  1. `enqueue_transcode`: `File.th_media_video_status` hemen `processing`
     olur, iş `frappe.enqueue(..., queue="long")` ile kuyruğa düşer.
  2. `_run_transcode`: ffmpeg komutu doğru argümanlarla kurulur (VP9/Opus,
     `scale=min(1280,iw)`), başarıda `ready`, hatada `failed` yazar.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_transcode
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import transcode


def _yeni_video_dosyasi(
	file_name: str, content: bytes = b"sahte video icerigi"
) -> "frappe.model.document.Document":
	doc = frappe.get_doc(
		{"doctype": "File", "file_name": file_name, "is_private": 0, "content": content}
	)
	doc.insert(ignore_permissions=True)
	return doc


class TestEnqueueTranscode(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_video_dosyasi("kisa-video-1.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_enqueue_transcode_processing_isaretler_ve_long_kuyruga_atar(self):
		with mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue:
			transcode.enqueue_transcode(self.doc.file_url)

		mock_enqueue.assert_called_once()
		_args, kwargs = mock_enqueue.call_args
		self.assertEqual(kwargs.get("queue"), "long")
		self.assertEqual(kwargs.get("file_url"), self.doc.file_url)
		self.assertEqual(kwargs.get("timeout"), 1800)
		self.assertTrue(kwargs.get("enqueue_after_commit"))

		durum = frappe.db.get_value("File", self.doc.name, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_PROCESSING)


class TestRunTranscode(FrappeTestCase):
	def setUp(self):
		self.doc = _yeni_video_dosyasi("kisa-video-2.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_run_transcode_ffmpeg_komutunu_dogru_argumanlarla_kurar_ve_ready_isaretler(self):
		def _sahte_ffmpeg(cmd, **kwargs):
			# Gerçek ffmpeg diski değiştirir — mock aynı yan etkiyi taklit
			# etmeli, aksi halde os.replace() kaynak dosyayı bulamaz.
			dst = cmd[-1]
			with open(dst, "wb") as f:
				f.write(b"sahte transcode edilmis veri")
			return mock.Mock(returncode=0)

		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run", side_effect=_sahte_ffmpeg
		) as mock_run:
			transcode._run_transcode(self.doc.file_url)

		mock_run.assert_called_once()
		cmd = mock_run.call_args[0][0]
		self.assertIn("ffmpeg", cmd)
		self.assertIn("-c:v", cmd)
		self.assertIn("libvpx-vp9", cmd)
		self.assertIn("-c:a", cmd)
		self.assertIn("libopus", cmd)
		self.assertTrue(
			any("scale=min(1280,iw)" in str(parca) for parca in cmd),
			f"scale filtresi bulunamadı: {cmd}",
		)

		durum = frappe.db.get_value("File", self.doc.name, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_READY)

	def test_run_transcode_hata_durumunda_failed_isaretler(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run", side_effect=Exception("ffmpeg patladı")
		):
			transcode._run_transcode(self.doc.file_url)

		durum = frappe.db.get_value("File", self.doc.name, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_FAILED)

	def test_run_transcode_hata_durumunda_audit_log_yazar(self):
		"""Fix round 1, Bulgu 2: hata dalı yalnız `frappe.log_error` çağırıyordu —
		transcode başarısızlığı medya denetim ekranında (ADL) hiç görünmüyordu.
		Brief Step 8: "hatada `failed` + audit" — başarı dalıyla aynı desen.
		"""
		with (
			mock.patch(
				"tradehub_core.media.transcode.subprocess.run",
				side_effect=Exception("ffmpeg patladı"),
			),
			mock.patch("tradehub_core.media.transcode.audit.log_media_event") as mock_audit,
		):
			transcode._run_transcode(self.doc.file_url)

		mock_audit.assert_called_once()
		_args, kwargs = mock_audit.call_args
		self.assertEqual(kwargs.get("file_url"), self.doc.file_url)
		self.assertFalse(kwargs.get("allowed"))

		durum = frappe.db.get_value("File", self.doc.name, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_FAILED)

	def test_run_transcode_dosya_bulunamazsa_sessizce_cikar(self):
		# Kuyruğa alındıktan sonra dosya silinmiş olabilir (satıcı bırakmış) —
		# worker patlamamalı.
		with mock.patch("tradehub_core.media.transcode.subprocess.run") as mock_run:
			transcode._run_transcode("/files/olmayan-dosya.mp4")
		mock_run.assert_not_called()


if __name__ == "__main__":
	import unittest

	unittest.main()
