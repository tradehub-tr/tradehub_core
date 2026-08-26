"""Poster üretimi — kare seçimi, luma kapısı, idempotens (Dilim 4 spec §4)."""

import subprocess
import tempfile
from pathlib import Path
from unittest import mock

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

	def test_ayni_file_url_birden_cok_kayitta_hepsine_yazilir(self):
		"""İçerik-hash adlandırma (WP4) aynı fiziksel dosyayı birden çok `File`
		kaydına eşleyebiliyor (media/inventory.py:124 — 39 kayda kadar).
		`generate` yalnız "ilk bulunan" kayda değil, aynı `file_url`'i taşıyan
		TÜM kayıtlara yazmalı — aksi halde eksik kayıt `backfill_pending`
		tarafından sonsuza dek yeniden seçilir (düzeltme turu 1, Important).
		"""
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "coklu.mp4"
			_yap_video(v)
			ilk = self._file_kaydi(v)
			ikinci = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": "coklu-kopya.mp4",
					"is_private": 0,
					"file_url": ilk.file_url,
				}
			).insert(ignore_permissions=True)
			self.addCleanup(ikinci.delete, ignore_permissions=True)
			# Kurulum varsayımı: content vermeden file_url ile insert, ikinci
			# kaydı BİRİNCİYLE AYNI adrese işaret ettiriyor (gerçek dünyadaki
			# içerik-hash çakışmasını taklit ediyor).
			self.assertEqual(ikinci.file_url, ilk.file_url)

			url = video_poster.generate(ilk.file_url)
			self.assertTrue(url)
			self.assertEqual(frappe.db.get_value("File", ilk.name, "th_media_poster_url"), url)
			self.assertEqual(frappe.db.get_value("File", ikinci.name, "th_media_poster_url"), url)

			# Her iki kayıt da dolu olduğu için aday sorgusuna hiç girmez. Bu
			# ortam prod'dan restore edilmiş gerçek veri taşıyor (106-video-seo-
			# olcum.md — 100+ posteri hâlâ boş video satırı), o yüzden mutlak
			# `backfill_pending(...) == 0` KIRILGAN: WHERE filtresi bu iki
			# kardeşi zaten hiç seçmeyeceği için doğrulama "aday-seçimi
			# düzeyinde" yapılır — spesifik `file_url` enqueue edilenler
			# arasında YOK (final inceleme, madde 3).
			with mock.patch("frappe.enqueue") as sahte_kuyruk:
				video_poster.backfill_pending(limit=10)
			enqueue_edilen_urller = {c.kwargs.get("file_url") for c in sahte_kuyruk.call_args_list}
			self.assertNotIn(ilk.file_url, enqueue_edilen_urller)

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
	def _bf_dosyasi(self, file_name: str, **ekstra) -> "frappe.model.document.Document":
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": file_name, "is_private": 0, "content": b"bf-test-icerigi"}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def test_backfill_yalniz_postersiz_videolari_alir(self):
		"""Final inceleme: `backfill_pending` artık SENKRON `generate` çağırmaz,
		aday videoyu `frappe.enqueue` ile kuyruğa atar (scheduler'ı ffmpeg
		timeout riskine sokmama — spec §4). Dönüş değeri kuyruğa atılan aday
		sayısı; senkron üretim etkisi test edilemez, `frappe.enqueue` yakalanır.

		Ortamda (prod restore) zaten postersiz başka video satırları var, o
		yüzden dönen toplam sayı KESİN `1` olmayabilir (`>= 1` yeterli) —
		asıl doğrulanan, TAZE eklenen adayın `ORDER BY creation DESC` sayesinde
		sonuç kümesine girip doğru kuyruk/parametrelerle enqueue edilmesi.
		"""
		doc = self._bf_dosyasi("bf.mp4")
		with mock.patch("frappe.enqueue") as sahte_kuyruk:
			kuyruga_konan = video_poster.backfill_pending(limit=10)
		self.assertGreaterEqual(kuyruga_konan, 1)
		bizim_cagri = next(
			(c for c in sahte_kuyruk.call_args_list if c.kwargs.get("file_url") == doc.file_url),
			None,
		)
		self.assertIsNotNone(bizim_cagri, "taze eklenen aday enqueue edilenler arasında değil")
		self.assertEqual(bizim_cagri.args, ("tradehub_core.media.video_poster.generate",))
		self.assertEqual(bizim_cagri.kwargs.get("queue"), "media-maint")
		self.assertEqual(bizim_cagri.kwargs.get("timeout"), 300)
		self.assertTrue(bizim_cagri.kwargs.get("enqueue_after_commit"))
		# Poster'sız/duration'sız çağrı gerçekten kuyruğa atıldığı için dosya
		# henüz posterlenmedi (senkron etki yok).
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_poster_url"))

	def test_backfill_posterli_adayi_atlamak_enqueue_etmez(self):
		"""İdempotens: poster'ı ya da duration'ı zaten dolu olan kayıt aday
		sorgusuna hiç girmez — `frappe.enqueue` o kayıt için ÇAĞRILMAZ. Global
		çağrı sayısı ortamdaki başka gerçek adaylardan etkilenebileceği için
		(prod restore verisi) bu test yalnız KENDİ `file_url`'inin enqueue
		edilmediğini doğrular."""
		doc = self._bf_dosyasi(
			"bf-posterli.mp4",
			th_media_poster_url="/files/bf-posterli-poster.jpg",
			th_media_duration=12,
		)
		with mock.patch("frappe.enqueue") as sahte_kuyruk:
			video_poster.backfill_pending(limit=10)
		enqueue_edilen_urller = {c.kwargs.get("file_url") for c in sahte_kuyruk.call_args_list}
		self.assertNotIn(doc.file_url, enqueue_edilen_urller)
