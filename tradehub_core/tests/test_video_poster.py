"""Poster üretimi — kare seçimi, luma kapısı, idempotens (Dilim 4 spec §4)."""

import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase
from PIL import Image

from tradehub_core.media import video_poster


def _yap_video(yol: Path, *, sure: int = 4, siyah_giris: bool = False) -> None:
	"""Küçük test videosu: renkli test deseni; istenirse ilk 1 sn siyah."""
	if siyah_giris:
		filtre = f"color=black:s=320x240:d=1[a];testsrc=s=320x240:d={sure - 1}[b];[a][b]concat"
		cmd = [
			"ffmpeg",
			"-y",
			"-f",
			"lavfi",
			"-i",
			"nullsrc=s=320x240:d=0.1",
			"-filter_complex",
			filtre,
			"-r",
			"10",
			str(yol),
		]
	else:
		cmd = ["ffmpeg", "-y", "-f", "lavfi", "-i", f"testsrc=s=320x240:d={sure}", "-r", "10", str(yol)]
	subprocess.run(cmd, check=True, capture_output=True)


class TestVideoPoster(FrappeTestCase):
	def _file_kaydi(self, yol: Path) -> "frappe.model.document.Document":
		with open(yol, "rb") as f:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": yol.name,
					"is_private": 0,
					"content": f.read(),
				}
			).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		return doc

	def test_normal_videoda_poster_uretilir(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "renkli.mp4"
			_yap_video(v)
			doc = self._file_kaydi(v)
			url = video_poster.generate(doc.file_url)
			self.assertTrue(url and url.endswith(".jpg"))
			self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_poster_url"), url)
			self.assertGreater(float(frappe.db.get_value("File", doc.name, "th_media_duration")), 3.0)
			# Poster dosyası gerçekten var ve public File kaydı açılmış
			self.assertTrue(frappe.db.exists("File", {"file_url": url}))

	def test_siyah_giriste_kare_penceresi_atlar(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "siyah.mp4"
			_yap_video(v, siyah_giris=True)
			doc = self._file_kaydi(v)
			url = video_poster.generate(doc.file_url)
			self.assertTrue(url)  # luma kapısı siyah kareyi elemeli, retry penceresi tutmalı

	def test_dikey_videoda_uzun_kenar_sinirlanir(self):
		"""Dikey kaynakta (1080×1920) uzun kenar YÜKSEKLİKTİR — eski
		`scale='min(1280,iw)':-2` filtresi yalnız genişliği (kısa kenarı)
		sınırlıyordu, yükseklik sınırsız kalıyordu (Important-1, denetim
		bulgusu). Yönelime duyarlı filtreyle poster yüksekliği ≤1280 olmalı
		ve kaynağın en-boy oranı korunmalı.
		"""
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "dikey.mp4"
			cmd = [
				"ffmpeg",
				"-y",
				"-f",
				"lavfi",
				"-i",
				"testsrc=s=1080x1920:d=3",
				"-r",
				"5",
				str(v),
			]
			subprocess.run(cmd, check=True, capture_output=True)
			doc = self._file_kaydi(v)
			url = video_poster.generate(doc.file_url)
			self.assertTrue(url)
			poster_name = frappe.db.get_value("File", {"file_url": url}, "name")
			poster_doc = frappe.get_doc("File", poster_name)
			self.addCleanup(poster_doc.delete, ignore_permissions=True)
			with Image.open(poster_doc.get_full_path()) as img:
				genislik, yukseklik = img.size
			self.assertLessEqual(yukseklik, 1280)  # uzun kenar (yükseklik) bütçelendi
			self.assertLess(genislik, yukseklik)  # dikey oran korundu
			# Kaynak oranı (1080/1920) korunmalı — eski hatalı filtrede genişlik
			# sınırlanmadığı için oran bozulmuyordu ama yükseklik 1920'de kalıyordu.
			self.assertAlmostEqual(genislik / yukseklik, 1080 / 1920, delta=0.02)

	def test_idempotent(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "idem.mp4"
			_yap_video(v)
			doc = self._file_kaydi(v)
			ilk = video_poster.generate(doc.file_url)
			ikinci = video_poster.generate(doc.file_url)
			self.assertEqual(ilk, ikinci)  # yeniden üretmez, mevcut URL döner

	def test_bozuk_dosya_none_doner_ve_yayini_dusurmez(self):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "bozuk.mp4",
				"is_private": 0,
				"content": b"bu bir video degil",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		self.assertIsNone(video_poster.generate(doc.file_url))


class TestVideoPosterBackfill(FrappeTestCase):
	def test_backfill_yalniz_postersiz_videolari_alir(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "bf.mp4"
			_yap_video(v)
			with open(v, "rb") as f:
				doc = frappe.get_doc(
					{"doctype": "File", "file_name": "bf.mp4", "is_private": 0, "content": f.read()}
				).insert(ignore_permissions=True)
			self.addCleanup(doc.delete, ignore_permissions=True)
			islenen = video_poster.backfill_pending(limit=10)
			self.assertGreaterEqual(islenen, 1)
			self.assertTrue(frappe.db.get_value("File", doc.name, "th_media_poster_url"))
			# İkinci tur: aynı dosya tekrar işlenmez
			self.assertEqual(video_poster.backfill_pending(limit=10), 0)
