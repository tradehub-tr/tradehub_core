"""Video SEO şeması ve okuma kapısı — Dilim 4 (spec 2026-08-26)."""

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import seo

# Tarama kancası bu modülde nötrleniyor — gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


def _gorunur_ilan() -> dict | None:
	"""Vitrinde görünen ilk ilan — Görev 6 testlerinin ortak fixture bulucusu
	(`test_video_servis.py::_gorunur_ilan` ile aynı desen: seed demo veriyi
	kullanır, sıfırdan Listing kurmak yerine)."""
	satirlar = frappe.db.sql(
		"""
		SELECT l.name FROM `tabListing` l
		WHERE l.storefront_visible = 1 AND l.status = 'Active'
		ORDER BY l.name ASC LIMIT 1
		""",
		as_dict=True,
	)
	return satirlar[0] if satirlar else None


def _iki_gorunur_ilan() -> list[dict]:
	"""Vitrinde görünen İLK İKİ ilan — dedup testi için (aynı `video_url`'i iki
	ilanın paylaşması senaryosu tek ilanla kurulamaz)."""
	return frappe.db.sql(
		"""
		SELECT l.name FROM `tabListing` l
		WHERE l.storefront_visible = 1 AND l.status = 'Active'
		ORDER BY l.name ASC LIMIT 2
		""",
		as_dict=True,
	)


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

	def test_posteri_dolu_ama_url_siz_video_none(self):
		"""Poster var ama ne `content_url` ne `embed_url` verilmişse `VideoObject`
		yine üretilmez — Google'a oynatılamayan bir video işaret ettirmemek için
		`content_url or embed_url` şartı poster'dan BAĞIMSIZ ayrıca uygulanır."""
		from tradehub_core.seo.schema_builder import build_video_object

		self.assertIsNone(
			build_video_object(
				{"title": "x", "poster_url": "/files/p.jpg", "duration": 5},
				"https://istoc.localhost",
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

	def test_seek_to_action_url_template_doluysa_potential_action_eklenir(self):
		"""Task 3 — koordinatör ruling: `seek_to_action_url_template` verilirse
		`potentialAction` şu ŞEKİLDE eklenir (spec brief §2, birebir)."""
		from tradehub_core.seo.schema_builder import build_video_object

		obj = build_video_object(
			{"title": "Video", "poster_url": "/files/p.jpg"},
			"https://istoc.localhost",
			content_url="/files/v.mp4",
			seek_to_action_url_template="https://istoc.localhost/medya/v/ornek?t={seek_to_second_number}",
		)
		self.assertEqual(
			obj["potentialAction"],
			{
				"@type": "SeekToAction",
				"target": {
					"@type": "EntryPoint",
					"urlTemplate": "https://istoc.localhost/medya/v/ornek?t={seek_to_second_number}",
				},
				"startOffset-input": "required name=seek_to_second_number",
			},
		)

	def test_seek_to_action_url_template_bosken_anahtar_yok(self):
		"""Geriye uyumlu — kwarg verilmezse `potentialAction` hiç girmez, mevcut
		çağıranlar (ör. `compose_for_listing`) kırılmasın."""
		from tradehub_core.seo.schema_builder import build_video_object

		obj = build_video_object(
			{"title": "Video", "poster_url": "/files/p.jpg"},
			"https://istoc.localhost",
			content_url="/files/v.mp4",
		)
		self.assertNotIn("potentialAction", obj)


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


class TestListingVideoMeta(FrappeTestCase):
	"""Görev 6 — `_gorsel_kunyeleri` galerideki video dosyaları için poster/süre/altyazı basar."""

	def test_gorsel_kunyesi_video_anahtarlari(self):
		from tradehub_core.api.listing import _gorsel_kunyeleri

		ilan_satir = _gorunur_ilan()
		if not ilan_satir:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")
		listing = frappe.get_doc("Listing", ilan_satir["name"])

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "task6-imagemeta-video.webm",
				"is_private": 0,
				"content": b"task6-imagemeta-video-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_poster_url": "/files/task6-p.jpg", "th_media_duration": 30},
			update_modified=False,
		)

		kunyeler = _gorsel_kunyeleri(listing, [doc.file_url], "tr")
		self.assertEqual(kunyeler[0]["poster"], "/files/task6-p.jpg")
		self.assertEqual(kunyeler[0]["durationSec"], 30)

	def test_gorsel_dosyasinda_video_anahtarlari_yok(self):
		"""Normal görsel satırında `poster`/`durationSec` HİÇ eklenmez — video
		dosyasına özgü anahtarlar tüm görsellere sızmasın."""
		from tradehub_core.api.listing import _gorsel_kunyeleri

		ilan_satir = _gorunur_ilan()
		if not ilan_satir:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")
		listing = frappe.get_doc("Listing", ilan_satir["name"])

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "task6-imagemeta-image.txt",
				"is_private": 0,
				"content": b"task6-imagemeta-image-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)

		kunyeler = _gorsel_kunyeleri(listing, [doc.file_url], "tr")
		self.assertNotIn("poster", kunyeler[0])
		self.assertNotIn("durationSec", kunyeler[0])
		self.assertNotIn("captionsUrl", kunyeler[0])


class TestListingDetailVideoPosterFallback(FrappeTestCase):
	"""Görev 6 — `videoPoster` manifest boşken canlı yol üretimine
	(`th_media_poster_url`) düşer; `videoDurationSec`/`videoCaptionsUrl` yeni alanlar."""

	def test_manifest_bosken_th_media_poster_url_kullanilir(self):
		from tradehub_core.api import listing as listing_api

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "task6-detay-poster.webm",
				"is_private": 0,
				"content": b"task6-detay-poster-video-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		frappe.db.set_value(
			"File",
			doc.name,
			{
				"th_media_poster_url": "/files/task6-detay-poster.jpg",
				"th_media_duration": 30,
				"th_media_captions_url": "/files/task6-detay.vtt",
			},
			update_modified=False,
		)

		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		frappe.db.set_value("Listing", ilan["name"], "video_url", doc.file_url, update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "video_url", eski_video_url, update_modified=False
			)
		)
		frappe.cache.delete_value(f"{listing_api._LISTING_DETAIL_CACHE_PREFIX}{ilan['name']}:tr")

		# Manifest (bayraklı motor) boş dönsün — fallback yalnız canlı yoldan gelsin.
		with mock.patch.object(listing_api, "_video_manifest_blogu", return_value={}):
			data = listing_api.get_listing_detail(ilan["name"])["data"]

		self.assertEqual(data["videoPoster"], "/files/task6-detay-poster.jpg")
		self.assertEqual(data["videoDurationSec"], 30)
		self.assertEqual(data["videoCaptionsUrl"], "/files/task6-detay.vtt")

	def test_manifest_posteri_canli_yoldan_once_gelir(self):
		"""Manifest doluysa (bayraklı motor) canlı yol üretimi hiç devreye girmez."""
		from tradehub_core.api import listing as listing_api

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		frappe.db.set_value(
			"Listing", ilan["name"], "video_url", "/files/task6-manifest-video.mp4", update_modified=False
		)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "video_url", eski_video_url, update_modified=False
			)
		)
		frappe.cache.delete_value(f"{listing_api._LISTING_DETAIL_CACHE_PREFIX}{ilan['name']}:tr")

		with mock.patch.object(
			listing_api, "_video_manifest_blogu", return_value={"poster": "/files/manifest-poster.jpg"}
		):
			data = listing_api.get_listing_detail(ilan["name"])["data"]

		self.assertEqual(data["videoPoster"], "/files/manifest-poster.jpg")


class TestListingVideoObjectJsonLd(FrappeTestCase):
	"""Görev 6 — JSON-LD `Product` yanında video varsa `VideoObject`
	(`schema_builder.compose_for_listing` → `build_product_schema(media_videos=...)`)."""

	def test_video_url_varsa_product_schema_video_tasir(self):
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "task6-jsonld-video.webm",
				"is_private": 0,
				"content": b"task6-jsonld-video-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_poster_url": "/files/task6-poster.jpg", "th_media_duration": 42},
			update_modified=False,
		)

		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		frappe.db.set_value("Listing", ilan["name"], "video_url", doc.file_url, update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "video_url", eski_video_url, update_modified=False
			)
		)

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")
		self.assertIn("video", product)
		self.assertEqual(
			product["video"][0]["thumbnailUrl"], "https://istoc.localhost/files/task6-poster.jpg"
		)

	def test_videosuz_ilan_product_schema_video_tasimaz(self):
		from tradehub_core.seo.schema_builder import compose_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		frappe.db.set_value("Listing", ilan["name"], "video_url", "", update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "video_url", eski_video_url, update_modified=False
			)
		)

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		schemas = compose_for_listing(listing, {}, "https://istoc.localhost")
		product = next(s for s in schemas if s["@type"] == "Product")
		self.assertNotIn("video", product)


class TestListingVideoObjectIndexKapisi(FrappeTestCase):
	"""Final inceleme (2026-08-26) — JSON-LD `VideoObject` üretimi de görsel
	kardeşi `_listing_image_objects` ve site haritası kardeşi
	`_video_entries_for_listing` ile AYNI `seo_index.decide` kapısından
	geçmeli (spec §5 şartı). Öncesinde `_listing_video_objects` bu kapıyı hiç
	sormuyordu — noindex/private video'lu ilan yine de JSON-LD'ye giriyordu."""

	def test_private_video_hem_jsonld_hem_sitemapten_dusuyor(self):
		from tradehub_core.seo.schema_builder import _listing_video_objects
		from tradehub_core.seo.sitemap_generator import _video_entries_for_listing

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "final-inceleme-private-video.webm",
				"is_private": 1,
				"content": b"final-inceleme-private-video-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		# Poster + süre BİLEREK dolduruldu: aşağıdaki iki fonksiyon da normalde
		# bu alanlar yeterliyken nesne/girdi üretir — boş dönüş SADECE
		# indexability kapısından (is_private=1 → REASON_PRIVATE) kaynaklanmalı.
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_poster_url": "/files/final-inceleme-poster.jpg", "th_media_duration": 20},
			update_modified=False,
		)

		listing = frappe.get_doc("Listing", ilan["name"]).as_dict()
		listing["video_url"] = doc.file_url
		self.assertEqual(_listing_video_objects(listing, "https://istoc.localhost"), [])

		girdiler = _video_entries_for_listing(
			{"name": ilan["name"], "video_url": doc.file_url, "title": "Ürün"}, "https://s"
		)
		self.assertEqual(girdiler, [])


class TestValidateAssetValuesVeriSilmeDuzeltmesi(FrappeTestCase):
	"""Final inceleme (2026-08-26) — `_validate_asset_values` girdide olmayan
	`license_url`/`acquire_license_url`/`canonical` alanlarını boş dizeyle
	`clean`'e EKLEMEMELİ. Öncesinde her `set_asset_fields` çağrısı (ör. yalnız
	`transcript` yazan `upload_video_captions`) bu üç alanı sessizce sıfırlıyordu."""

	def test_yalniz_transcript_yazilinca_license_url_korunur(self):
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "final-inceleme-license-koru.webm",
				"is_private": 0,
				"content": b"final-inceleme-license-koru-icerigi",
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)

		seo.set_asset_fields(doc.file_url, {"license_url": "https://example.com/lisans"})
		self.assertEqual(
			frappe.db.get_value("File", doc.name, "th_media_license_url"),
			"https://example.com/lisans",
		)

		seo.set_asset_fields(doc.file_url, {"transcript": "x"})

		self.assertEqual(
			frappe.db.get_value("File", doc.name, "th_media_license_url"),
			"https://example.com/lisans",
			"transcript-only yazım license_url'ü sıfırlamamalı",
		)
		self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_transcript"), "x")


class TestVideoAuditVeUclar(FrappeTestCase):
	"""Görev 7 — video denetim kuralları + poster yeniden üretme/VTT yükleme uçları."""

	def test_video_denetim_kurallari(self):
		from tradehub_core.media.seo_audit import audit_fields

		bulgular = audit_fields(
			{"alt": "x", "title": "x", "poster_url": "", "transcript": "", "duration": 0},
			file_name="tanitim.webm",
		)
		kodlar = {b["code"] for b in bulgular}
		self.assertIn("missing_poster", kodlar)
		self.assertIn("missing_transcript", kodlar)
		self.assertIn("missing_duration", kodlar)

	def test_gorselde_video_kurali_calismaz(self):
		from tradehub_core.media.seo_audit import audit_fields

		bulgular = audit_fields({"alt": "x"}, file_name="foto.jpg")
		kodlar = {b["code"] for b in bulgular}
		self.assertNotIn("missing_poster", kodlar)

	def test_vtt_yukleme_dogrulama(self):
		from tradehub_core.api.media_admin import upload_video_captions

		frappe.set_user("Administrator")
		# `file_url` set edilmeden `content` verilir — Frappe diskten okumaya
		# çalışmaz (bu dosyanın başındaki `test_fields_for_video_alanlarini_dondurur`
		# ile aynı desen); asıl adres `doc.file_url`'den okunur, elle uydurulmaz.
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": "v-cap.webm", "is_private": 0, "content": b"vtt-test-video"}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		with self.assertRaises(frappe.ValidationError):
			upload_video_captions(doc.file_url, "bu vtt degil")
		sonuc = upload_video_captions(doc.file_url, "WEBVTT\n\n00:00.000 --> 00:02.000\nMerhaba")
		self.assertTrue(sonuc["captions_url"].endswith(".vtt"))

	def test_vtt_govdesinde_script_reddedilir(self):
		"""Düzeltme turu 1: `startswith("WEBVTT")` tek başına yetmiyor — gövdenin
		ortasına gömülü `<script>` de reddedilmeli (derin denetim yalnız
		IMAGE_KINDS'ta gövde tarıyor, VTT bundan sızıyordu)."""
		from tradehub_core.api.media_admin import upload_video_captions

		frappe.set_user("Administrator")
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": "v-cap-xss.webm", "is_private": 0, "content": b"vtt-xss-video"}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		zararli = "WEBVTT\n\n00:00.000 --> 00:02.000\n<script>alert(1)</script>"
		with self.assertRaises(frappe.ValidationError):
			upload_video_captions(doc.file_url, zararli)

	def test_vtt_bom_toleransli_kabul_edilir(self):
		"""Düzeltme turu 1: U+FEFF (UTF-8 BOM) ile başlayan geçerli WebVTT
		`str.strip()` tarafından temizlenmiyor — `lstrip('﻿')` ile ayrıca
		soyulmalı, yoksa geçerli dosya yanlışlıkla reddediliyordu."""
		from tradehub_core.api.media_admin import upload_video_captions

		frappe.set_user("Administrator")
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": "v-cap-bom.webm", "is_private": 0, "content": b"vtt-bom-video"}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		bomlu = "﻿WEBVTT\n\n00:00.000 --> 00:02.000\nMerhaba"
		sonuc = upload_video_captions(doc.file_url, bomlu)
		self.assertTrue(sonuc["captions_url"].endswith(".vtt"))

	def test_regenerate_video_poster_tum_kardes_kayitlari_temizler(self):
		"""Aynı `file_url`'e sahip iki `File` kaydından biri poster taşırken
		regenerate ikisini de boşaltmalı — yoksa `generate` idempotent dalı
		posteri kardeş kayıttan geri kopyalar ve yeniden üretim hiç koşmaz."""
		from tradehub_core.api.media_admin import regenerate_video_poster

		frappe.set_user("Administrator")
		icerik = b"paylasilan-video-icerigi"
		birinci = frappe.get_doc(
			{"doctype": "File", "file_name": "paylasilan-video.webm", "is_private": 0, "content": icerik}
		).insert(ignore_permissions=True)
		self.addCleanup(birinci.delete, ignore_permissions=True)
		ortak_url = birinci.file_url
		# İkinci kayıt AYNI içeriği taşıyor — Frappe'nin content-hash tekilleştirmesi
		# (`file.py::save_file`) bunu otomatik olarak aynı `file_url`'e bağlar; iki
		# `File` satırı, tek fiziksel dosya (video_poster.generate docstring'i).
		ikinci = frappe.get_doc(
			{"doctype": "File", "file_name": "paylasilan-video-2.webm", "is_private": 0, "content": icerik}
		).insert(ignore_permissions=True)
		self.addCleanup(ikinci.delete, ignore_permissions=True)
		self.assertEqual(ikinci.file_url, ortak_url)

		frappe.db.set_value(
			"File", birinci.name, "th_media_poster_url", "/files/eski-poster.jpg", update_modified=False
		)

		with mock.patch("frappe.enqueue") as sahte_kuyruk:
			sonuc = regenerate_video_poster(ortak_url)

		self.assertTrue(sonuc["queued"])
		sahte_kuyruk.assert_called_once()
		self.assertEqual(
			frappe.db.get_value("File", birinci.name, "th_media_poster_url"),
			"",
		)
		self.assertEqual(
			frappe.db.get_value("File", ikinci.name, "th_media_poster_url"),
			"",
		)


class TestSitemapWatchEntries(FrappeTestCase):
	"""Görev 5 — sitemap'e watch page'lerin (`/medya/v/<slug>`) KENDİ `<url>` girdileri.

	`_watch_entries_for_rows` (`_entries_for_rows`'un parçası), `watch_indexable`
	(W3 — SEO kararı + poster + görünür ilan, `api/media_public.py`) True VE
	`fields.slug` dolu olan her ilan videosu için EK bir girdi üretir; gövdesi
	`_video_entries_for_listing`'in ürettiği aynı `<video:video>` sözlüğü."""

	def _video_dosyasi(self, file_name: str, **ekstra) -> "frappe.Document":
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 0,
				"content": f"watch-sitemap-test-{file_name}".encode(),
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def test_indexable_slugli_video_watch_girdisi_uretir(self):
		from tradehub_core.seo import sitemap_generator as sg

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi(
			"watch-sitemap-indexable.mp4",
			th_media_duration=10,
			th_media_poster_url="/files/watch-sitemap-poster.jpg",
			th_media_slug="watch-sitemap-indexable-slug",
		)
		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		frappe.db.set_value("Listing", ilan["name"], "video_url", doc.file_url, update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "video_url", eski_video_url, update_modified=False
			)
		)

		row = {
			"name": ilan["name"],
			"slug": "ilgisiz-urun-slug",
			"modified": "2020-01-01",
			"video_url": doc.file_url,
			"title": "Ürün",
		}
		girdiler = sg._entries_for_rows([row], sg.DOCTYPE_CONFIG["Listing"], "https://s")

		watch_girdileri = [
			g for g in girdiler if g["loc"] == "https://s/medya/v/watch-sitemap-indexable-slug"
		]
		self.assertEqual(len(watch_girdileri), 1)
		self.assertTrue(watch_girdileri[0]["videos"])
		self.assertEqual(
			watch_girdileri[0]["videos"][0]["thumbnail_loc"],
			"https://s/files/watch-sitemap-poster.jpg",
		)

	def test_gorunmez_ilan_watch_girdisi_uretmez(self):
		"""İlan noindex/görünmez (storefront_visible=0) → watch W3'ün "görünür
		ilan" bacağı düşer, girdi hiç üretilmez."""
		from tradehub_core.seo import sitemap_generator as sg

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi(
			"watch-sitemap-noindex.mp4",
			th_media_duration=10,
			th_media_poster_url="/files/watch-sitemap-noindex-poster.jpg",
			th_media_slug="watch-sitemap-noindex-slug",
		)
		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		eski_gorunurluk = frappe.db.get_value("Listing", ilan["name"], "storefront_visible")
		frappe.db.set_value(
			"Listing",
			ilan["name"],
			{"video_url": doc.file_url, "storefront_visible": 0},
			update_modified=False,
		)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing",
				ilan["name"],
				{"video_url": eski_video_url, "storefront_visible": eski_gorunurluk},
				update_modified=False,
			)
		)

		row = {
			"name": ilan["name"],
			"slug": "ilgisiz-urun-slug-2",
			"modified": "2020-01-01",
			"video_url": doc.file_url,
			"title": "Ürün",
		}
		girdiler = sg._entries_for_rows([row], sg.DOCTYPE_CONFIG["Listing"], "https://s")

		watch_girdileri = [g for g in girdiler if g["loc"].startswith("https://s/medya/v/")]
		self.assertEqual(watch_girdileri, [])

	def test_slug_bosken_watch_girdisi_uretmez(self):
		"""Poster + görünür ilan tamam ama `th_media_slug` boş → girdi üretilmez
		(brief koşulu: `fields.slug` dolu şartı AYRIca aranır)."""
		from tradehub_core.seo import sitemap_generator as sg

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi(
			"watch-sitemap-slugsuz.mp4",
			th_media_duration=10,
			th_media_poster_url="/files/watch-sitemap-slugsuz-poster.jpg",
			# th_media_slug BİLEREK yok.
		)
		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		frappe.db.set_value("Listing", ilan["name"], "video_url", doc.file_url, update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing", ilan["name"], "video_url", eski_video_url, update_modified=False
			)
		)

		row = {
			"name": ilan["name"],
			"slug": "ilgisiz-urun-slug-3",
			"modified": "2020-01-01",
			"video_url": doc.file_url,
			"title": "Ürün",
		}
		girdiler = sg._entries_for_rows([row], sg.DOCTYPE_CONFIG["Listing"], "https://s")

		watch_girdileri = [g for g in girdiler if g["loc"].startswith("https://s/medya/v/")]
		self.assertEqual(watch_girdileri, [])


class TestSitemapWatchEntriesDedup(FrappeTestCase):
	"""Düzeltme turu 1 — Critical: aynı `video_url` birden çok görünür ilanda
	kullanılırsa `/medya/v/<slug>` girdisi TEK kez üretilmeli (ilk satır kazanır)."""

	def _video_dosyasi(self, file_name: str, **ekstra) -> "frappe.Document":
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": 0,
				"content": f"watch-sitemap-dedup-test-{file_name}".encode(),
			}
		)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def test_paylasilan_video_url_tek_watch_girdisi_uretir(self):
		from tradehub_core.seo import sitemap_generator as sg

		ilanlar = _iki_gorunur_ilan()
		if len(ilanlar) < 2:
			self.skipTest("Vitrinde görünen en az 2 ilan yok — dedup fixture'ı kurulamaz.")
		ilan_a, ilan_b = ilanlar[0]["name"], ilanlar[1]["name"]

		doc = self._video_dosyasi(
			"watch-sitemap-dedup.mp4",
			th_media_duration=10,
			th_media_poster_url="/files/watch-sitemap-dedup-poster.jpg",
			th_media_slug="watch-sitemap-dedup-slug",
		)
		eski_a = frappe.db.get_value("Listing", ilan_a, "video_url")
		eski_b = frappe.db.get_value("Listing", ilan_b, "video_url")
		frappe.db.set_value("Listing", ilan_a, "video_url", doc.file_url, update_modified=False)
		frappe.db.set_value("Listing", ilan_b, "video_url", doc.file_url, update_modified=False)
		self.addCleanup(
			lambda: frappe.db.set_value("Listing", ilan_a, "video_url", eski_a, update_modified=False)
		)
		self.addCleanup(
			lambda: frappe.db.set_value("Listing", ilan_b, "video_url", eski_b, update_modified=False)
		)

		rows = [
			{
				"name": ilan_a,
				"slug": "ilgisiz-urun-slug-a",
				"modified": "2020-01-01",
				"video_url": doc.file_url,
				"title": "Ürün A",
			},
			{
				"name": ilan_b,
				"slug": "ilgisiz-urun-slug-b",
				"modified": "2020-01-01",
				"video_url": doc.file_url,
				"title": "Ürün B",
			},
		]
		girdiler = sg._entries_for_rows(rows, sg.DOCTYPE_CONFIG["Listing"], "https://s")

		watch_girdileri = [g for g in girdiler if g["loc"] == "https://s/medya/v/watch-sitemap-dedup-slug"]
		self.assertEqual(len(watch_girdileri), 1, "aynı video_url İKİ kez watch girdisi üretmemeli")
