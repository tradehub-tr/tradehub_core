"""Video async transcode kuyruğu testleri (TUR-296/297, WP2 + WP5).

`enqueue_transcode` gerçek ffmpeg'i ÇAĞIRMAZ — `subprocess.run` mock'lanır.
Eksenler:

  1. `enqueue_transcode`: video zaten küçük/sıkışmışsa (`needs_transcode`
     False) kuyruğa HİÇ girmez, `ready` yazar; büyükse eski davranış
     (`processing` + `frappe.enqueue(..., queue="long")`). İkinci kez
     çağrılırsa (durum zaten `processing`/`ready`) idempotent — no-op.
  2. `_run_transcode`: ffmpeg komutu doğru argümanlarla kurulur (VP9/Opus,
     `scale=min(1280,iw)`), başarıda `ready`, hatada `failed` yazar.
  3. `needs_transcode` (WP5): `ffprobe` ile gerçek video parametreleri
     (genişlik + bitrate) okunur — eşiğin üstündeyse VEYA ffprobe
     okuyamıyorsa (güvenli taraf) True; client zaten sıkıştırmışsa False.
  4. `maybe_transcode_on_insert` (WP5): `File.after_insert` GLOBAL kancası —
     satıcının public videosu VEYA `Listing`e eklenmiş video güvenlik ağına
     girer; chat/KYB/private videolar muaf.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_transcode
"""

from __future__ import annotations

import json
import subprocess
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


class TestNeedsTranscode(FrappeTestCase):
	"""`needs_transcode` — WP5: genişlik > 1280 VEYA bitrate > 2.5 Mbps ise True.

	`ffprobe` her zaman mock'lanır (constraint: testte gerçek ffprobe çağrılmaz).
	"""

	@staticmethod
	def _ffprobe_stdout(width: int | None = None, bit_rate: int | None = None) -> bytes:
		stream: dict = {}
		if width is not None:
			stream["width"] = width
		if bit_rate is not None:
			stream["bit_rate"] = str(bit_rate)
		return json.dumps({"streams": [stream]}).encode()

	def test_genislik_esigini_asan_video_true_doner(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run",
			return_value=mock.Mock(stdout=self._ffprobe_stdout(width=1920, bit_rate=500_000)),
		):
			self.assertTrue(transcode.needs_transcode("/tmp/genis-video.mp4"))

	def test_bitrate_esigini_asan_video_true_doner(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run",
			return_value=mock.Mock(stdout=self._ffprobe_stdout(width=640, bit_rate=3_000_000)),
		):
			self.assertTrue(transcode.needs_transcode("/tmp/yuksek-bitrate.mp4"))

	def test_kucuk_ve_dusuk_bitrate_video_false_doner(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run",
			return_value=mock.Mock(stdout=self._ffprobe_stdout(width=640, bit_rate=800_000)),
		):
			self.assertFalse(transcode.needs_transcode("/tmp/kucuk-video.mp4"))

	def test_ffprobe_bulunamazsa_guvenli_taraf_true_doner(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run",
			side_effect=FileNotFoundError("ffprobe yok"),
		):
			self.assertTrue(transcode.needs_transcode("/tmp/herhangi.mp4"))

	def test_ffprobe_hata_verirse_guvenli_taraf_true_doner(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run",
			side_effect=subprocess.CalledProcessError(1, ["ffprobe"]),
		):
			self.assertTrue(transcode.needs_transcode("/tmp/bozuk-video.mp4"))

	def test_ffprobe_stream_bulamazsa_guvenli_taraf_true_doner(self):
		with mock.patch(
			"tradehub_core.media.transcode.subprocess.run",
			return_value=mock.Mock(stdout=json.dumps({"streams": []}).encode()),
		):
			self.assertTrue(transcode.needs_transcode("/tmp/stream-yok.mp4"))


class TestEnqueueTranscodeKosullu(FrappeTestCase):
	"""`enqueue_transcode` — WP5: `needs_transcode` sonucuna göre koşullu davranış."""

	def setUp(self):
		self.doc = _yeni_video_dosyasi("kosullu-video-1.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc("File", self.doc.name, ignore_permissions=True, force=True)
		)

	def test_kucuk_video_enqueue_edilmez_ready_isaretlenir(self):
		with (
			mock.patch(
				"tradehub_core.media.transcode.needs_transcode", return_value=False
			) as mock_needs,
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode.enqueue_transcode(self.doc.file_url)

		mock_needs.assert_called_once()
		mock_enqueue.assert_not_called()
		durum = frappe.db.get_value("File", self.doc.name, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_READY)

	def test_buyuk_video_enqueue_edilir_processing_isaretlenir(self):
		with (
			mock.patch(
				"tradehub_core.media.transcode.needs_transcode", return_value=True
			) as mock_needs,
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode.enqueue_transcode(self.doc.file_url)

		mock_needs.assert_called_once()
		mock_enqueue.assert_called_once()
		durum = frappe.db.get_value("File", self.doc.name, "th_media_video_status")
		self.assertEqual(durum, transcode.VIDEO_STATUS_PROCESSING)

	def test_zaten_processing_ise_tekrar_enqueue_edilmez(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_PROCESSING
		)
		with (
			mock.patch("tradehub_core.media.transcode.needs_transcode") as mock_needs,
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode.enqueue_transcode(self.doc.file_url)

		mock_needs.assert_not_called()
		mock_enqueue.assert_not_called()

	def test_zaten_ready_ise_tekrar_enqueue_edilmez(self):
		frappe.db.set_value(
			"File", self.doc.name, "th_media_video_status", transcode.VIDEO_STATUS_READY
		)
		with (
			mock.patch("tradehub_core.media.transcode.needs_transcode") as mock_needs,
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode.enqueue_transcode(self.doc.file_url)

		mock_needs.assert_not_called()
		mock_enqueue.assert_not_called()


class TestMaybeTranscodeOnInsert(FrappeTestCase):
	"""`maybe_transcode_on_insert` — WP5: GLOBAL `File.after_insert` kancası.

	Test ortamında dosyalar `Administrator` olarak eklenir (`ownership.store_of`
	bunu bilerek `None` döner) — bu yüzden satıcı senaryosu `ownership.store_of`
	mock'lanarak simüle edilir.
	"""

	def setUp(self):
		self.public_video = _yeni_video_dosyasi("global-hook-public.mp4")
		self.addCleanup(
			lambda: frappe.delete_doc(
				"File", self.public_video.name, ignore_permissions=True, force=True
			)
		)

	def test_saticiya_ait_public_video_enqueue_edilir(self):
		with (
			mock.patch(
				"tradehub_core.media.transcode.ownership.store_of", return_value="MAGAZA-001"
			),
			mock.patch("tradehub_core.media.transcode.enqueue_transcode") as mock_enqueue_transcode,
		):
			transcode.maybe_transcode_on_insert(self.public_video)

		mock_enqueue_transcode.assert_called_once_with(self.public_video.file_url)

	def test_private_video_muaf(self):
		frappe.db.set_value("File", self.public_video.name, "is_private", 1)
		self.public_video.reload()
		with (
			mock.patch(
				"tradehub_core.media.transcode.ownership.store_of", return_value="MAGAZA-001"
			),
			mock.patch("tradehub_core.media.transcode.enqueue_transcode") as mock_enqueue_transcode,
		):
			transcode.maybe_transcode_on_insert(self.public_video)

		mock_enqueue_transcode.assert_not_called()

	def test_satici_olmayan_ve_listing_eki_olmayan_muaf(self):
		# Chat/KYB gibi — owner satıcı değil, attached_to_doctype Listing değil.
		with (
			mock.patch("tradehub_core.media.transcode.ownership.store_of", return_value=None),
			mock.patch("tradehub_core.media.transcode.enqueue_transcode") as mock_enqueue_transcode,
		):
			transcode.maybe_transcode_on_insert(self.public_video)

		mock_enqueue_transcode.assert_not_called()

	def test_listing_ekindeki_video_satici_olmasa_bile_enqueue_edilir(self):
		frappe.db.set_value("File", self.public_video.name, "attached_to_doctype", "Listing")
		self.public_video.reload()
		with (
			mock.patch("tradehub_core.media.transcode.ownership.store_of", return_value=None),
			mock.patch("tradehub_core.media.transcode.enqueue_transcode") as mock_enqueue_transcode,
		):
			transcode.maybe_transcode_on_insert(self.public_video)

		mock_enqueue_transcode.assert_called_once_with(self.public_video.file_url)

	def test_video_olmayan_dosya_muaf(self):
		import io

		from PIL import Image

		buf = io.BytesIO()
		Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "JPEG")
		img = frappe.get_doc(
			{"doctype": "File", "file_name": "gorsel.jpg", "is_private": 0, "content": buf.getvalue()}
		)
		img.insert(ignore_permissions=True)
		self.addCleanup(
			lambda: frappe.delete_doc("File", img.name, ignore_permissions=True, force=True)
		)

		with (
			mock.patch(
				"tradehub_core.media.transcode.ownership.store_of", return_value="MAGAZA-001"
			),
			mock.patch("tradehub_core.media.transcode.enqueue_transcode") as mock_enqueue_transcode,
		):
			transcode.maybe_transcode_on_insert(img)

		mock_enqueue_transcode.assert_not_called()

	def test_zaten_kuyruklanmis_dosyada_ikinci_kez_enqueue_cagrilmiyor(self):
		"""İdempotentlik `enqueue_transcode` İÇİNDE sağlanıyor — kanca `mock`suz
		gerçek `enqueue_transcode`'u çağırıyor, durum zaten `processing` olduğu
		için `needs_transcode`/`frappe.enqueue` hiç tetiklenmemeli."""
		frappe.db.set_value(
			"File", self.public_video.name, "th_media_video_status", transcode.VIDEO_STATUS_PROCESSING
		)
		with (
			mock.patch(
				"tradehub_core.media.transcode.ownership.store_of", return_value="MAGAZA-001"
			),
			mock.patch("tradehub_core.media.transcode.needs_transcode") as mock_needs,
			mock.patch("tradehub_core.media.transcode.frappe.enqueue") as mock_enqueue,
		):
			transcode.maybe_transcode_on_insert(self.public_video)

		mock_needs.assert_not_called()
		mock_enqueue.assert_not_called()


if __name__ == "__main__":
	import unittest

	unittest.main()
