"""Poster üretimi — kare seçimi, luma kapısı, idempotens (Dilim 4 spec §4)."""

import subprocess
import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

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
