"""Video SEO şeması ve okuma kapısı — Dilim 4 (spec 2026-08-26)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo


class TestVideoSeoSchema(FrappeTestCase):
	def test_video_kolonlari_var(self):
		for kolon in (
			"th_media_duration",
			"th_media_poster_url",
			"th_media_transcript",
			"th_media_captions_url",
		):
			self.assertTrue(frappe.db.has_column("File", kolon), kolon)

	def test_fields_for_video_alanlarini_dondurur(self):
		# `content` verilmeden `file_url` set edilirse Frappe diskten okumaya
		# çalışır (bu ortamda fiziksel dosya yok) — `test_media_seo.py::_dosya`
		# deseniyle aynı: gerçek küçük içerik ver, üretilen `file_url`'i kullan.
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-video-seo.webm",
				"is_private": 0,
				"content": b"video-seo-test-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		frappe.db.set_value(
			"File",
			doc.name,
			{
				"th_media_duration": 12.5,
				"th_media_poster_url": "/files/poster-abc.jpg",
				"th_media_transcript": "merhaba",
				"th_media_captions_url": "/files/cap.vtt",
			},
			update_modified=False,
		)
		alanlar = seo.fields_for(doc.file_url)
		self.assertEqual(alanlar["duration"], 12.5)
		self.assertEqual(alanlar["poster_url"], "/files/poster-abc.jpg")
		self.assertEqual(alanlar["transcript"], "merhaba")
		self.assertEqual(alanlar["captions_url"], "/files/cap.vtt")

	def test_duration_ve_poster_disaridan_yazilamaz(self):
		# set_asset_fields beyaz listesi: sistem alanları istekten geçmez.
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "test-video-seo2.webm",
				"is_private": 0,
				"content": b"video-seo-test-icerigi-2",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		n = seo.set_asset_fields(
			doc.file_url,
			{"duration": 99, "poster_url": "/files/x.jpg", "transcript": "t1"},
		)
		self.assertEqual(n, 1)  # transcript yazıldı, diğer ikisi elendi
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_duration"))
		self.assertFalse(frappe.db.get_value("File", doc.name, "th_media_poster_url"))
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_transcript"), "t1")


class TestVideoObject(FrappeTestCase):
	def test_tam_alanli_video_object(self):
		from tradehub_core.seo.schema_builder import build_video_object

		alanlar = {
			"title": "Ürün tanıtımı",
			"alt": "",
			"caption": "Kısa tanıtım",
			"description": "",
			"poster_url": "/files/poster.jpg",
			"duration": 65.0,
			"transcript": "merhaba dünya",
			"rights_expires_on": "",
		}
		obj = build_video_object(
			alanlar, "https://istoc.localhost",
			content_url="/files/video.webm", upload_date="2026-08-01 10:00:00",
		)
		self.assertEqual(obj["@type"], "VideoObject")
		self.assertEqual(obj["name"], "Ürün tanıtımı")
		self.assertEqual(obj["thumbnailUrl"], "https://istoc.localhost/files/poster.jpg")
		self.assertEqual(obj["contentUrl"], "https://istoc.localhost/files/video.webm")
		self.assertEqual(obj["duration"], "PT1M5S")
		self.assertEqual(obj["transcript"], "merhaba dünya")
		self.assertEqual(obj["uploadDate"], "2026-08-01")
		self.assertNotIn("embedUrl", obj)

	def test_postersiz_video_none(self):
		from tradehub_core.seo.schema_builder import build_video_object

		self.assertIsNone(
			build_video_object(
				{"title": "x", "poster_url": "", "duration": 5},
				"https://istoc.localhost", content_url="/files/v.mp4",
			)
		)

	def test_embed_video(self):
		from tradehub_core.seo.schema_builder import build_video_object

		obj = build_video_object(
			{"title": "Promo", "poster_url": "/files/p.jpg", "duration": 0},
			"https://istoc.localhost", embed_url="https://www.youtube.com/embed/abc",
		)
		self.assertEqual(obj["embedUrl"], "https://www.youtube.com/embed/abc")
		self.assertNotIn("contentUrl", obj)
		self.assertNotIn("duration", obj)  # 0 süre basılmaz
