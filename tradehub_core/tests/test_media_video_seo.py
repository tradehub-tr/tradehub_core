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
			alanlar,
			"https://istoc.localhost",
			content_url="/files/video.webm",
			upload_date="2026-08-01 10:00:00",
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
				"https://istoc.localhost",
				content_url="/files/v.mp4",
			)
		)

	def test_embed_video(self):
		from tradehub_core.seo.schema_builder import build_video_object

		obj = build_video_object(
			{"title": "Promo", "poster_url": "/files/p.jpg", "duration": 0},
			"https://istoc.localhost",
			embed_url="https://www.youtube.com/embed/abc",
		)
		self.assertEqual(obj["embedUrl"], "https://www.youtube.com/embed/abc")
		self.assertNotIn("contentUrl", obj)
		self.assertNotIn("duration", obj)  # 0 süre basılmaz


class TestVideoSitemap(FrappeTestCase):
	def test_urlset_video_girdisi(self):
		from tradehub_core.seo.sitemap_generator import build_urlset_xml

		xml = build_urlset_xml(
			[
				{
					"loc": "https://s/urun/x",
					"lastmod": "2026-08-26",
					"videos": [
						{
							"thumbnail_loc": "https://s/files/p.jpg",
							"title": "Tanıtım",
							"description": "Kısa",
							"content_loc": "https://s/files/v.webm",
							"duration": 65,
							"publication_date": "2026-08-01",
						}
					],
				}
			]
		)
		self.assertIn('xmlns:video="http://www.google.com/schemas/sitemap-video/1.1"', xml)
		self.assertIn("<video:video>", xml)
		self.assertIn("<video:thumbnail_loc>https://s/files/p.jpg</video:thumbnail_loc>", xml)
		self.assertIn("<video:duration>65</video:duration>", xml)

	def test_videosuz_urlset_namespace_almaz(self):
		from tradehub_core.seo.sitemap_generator import build_urlset_xml

		xml = build_urlset_xml([{"loc": "https://s/", "lastmod": "2026-08-26"}])
		self.assertNotIn("xmlns:video", xml)


class TestVideoEntriesForListing(FrappeTestCase):
	"""`_video_entries_for_listing` — `_image_entries_for_listing`'in kardeşi."""

	def _video_dosyasi(self, file_name: str, **ekstra) -> "frappe.Document":
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 0,
				"content": b"video-sitemap-test-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def test_postersiz_video_haritaya_girmez(self):
		from tradehub_core.seo.sitemap_generator import _video_entries_for_listing

		doc = self._video_dosyasi("sitemap-postersiz.mp4", th_media_duration=42)
		girdiler = _video_entries_for_listing(
			{"name": "TEST-LISTING", "video_url": doc.file_url, "title": "Ürün"},
			"https://s",
		)
		self.assertEqual(girdiler, [])

	def test_posterli_video_girdisi_uretir(self):
		from tradehub_core.seo.sitemap_generator import _video_entries_for_listing

		doc = self._video_dosyasi(
			"sitemap-posterli.mp4",
			th_media_duration=65,
			th_media_poster_url="/files/sitemap-poster.jpg",
		)
		girdiler = _video_entries_for_listing(
			{"name": "TEST-LISTING", "video_url": doc.file_url, "title": "Ürün Videosu"},
			"https://s",
		)
		self.assertEqual(len(girdiler), 1)
		video = girdiler[0]
		self.assertEqual(video["thumbnail_loc"], "https://s/files/sitemap-poster.jpg")
		self.assertEqual(video["content_loc"], f"https://s{doc.file_url}")
		self.assertEqual(video["title"], "Ürün Videosu")
		self.assertEqual(video["duration"], 65)

	def test_videosuz_ilan_bos_liste_doner(self):
		from tradehub_core.seo.sitemap_generator import _video_entries_for_listing

		self.assertEqual(
			_video_entries_for_listing({"name": "TEST-LISTING", "video_url": ""}, "https://s"), []
		)


class TestVideoAlanlarToplu(FrappeTestCase):
	"""Düzeltme turu 1 — N+1 giderildi: parça başına TEK `fields_for_many` çağrısı.

	`_video_entries_for_listing` doğrudan çağrıldığında (map verilmeden) kendi
	sorgusunu açar; site haritası üretim akışı (`_entries_for_rows` →
	`_preload_video_alanlar`) parçadaki TÜM video URL'lerini tek seferde çeker.
	"""

	def _video_dosyasi(self, file_name: str, **ekstra) -> "frappe.Document":
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 0,
				"content": f"video-toplu-test-{file_name}".encode(),
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def test_parca_basina_tek_fields_for_many_cagrisi(self):
		from unittest import mock

		from tradehub_core.media import seo as media_seo
		from tradehub_core.seo import sitemap_generator as sg

		belgeler = [
			self._video_dosyasi(
				f"sitemap-toplu-{i}.mp4",
				th_media_duration=10 + i,
				th_media_poster_url=f"/files/sitemap-toplu-poster-{i}.jpg",
			)
			for i in range(3)
		]
		rows = [
			{
				"name": f"TOPLU-LISTING-{i}",
				"slug": f"toplu-{i}",
				"modified": "2026-08-26",
				"video_url": doc.file_url,
				"title": f"Ürün {i}",
			}
			for i, doc in enumerate(belgeler)
		]

		with mock.patch.object(media_seo, "fields_for_many", wraps=media_seo.fields_for_many) as sayac:
			girdiler = sg._entries_for_rows(rows, sg.DOCTYPE_CONFIG["Listing"], "https://s")

		self.assertEqual(sayac.call_count, 1, "video alanları parça başına TEK sorguyla çekilmeli")
		for i, entry in enumerate(girdiler):
			self.assertEqual(len(entry["videos"]), 1, f"satır {i} video girdisi üretmeli")
			self.assertEqual(
				entry["videos"][0]["thumbnail_loc"], f"https://s/files/sitemap-toplu-poster-{i}.jpg"
			)
