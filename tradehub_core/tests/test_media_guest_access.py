"""MOGEM-685 Bulgu 1 — medya misafir uçları erişilemez dosyayı GÖSTERMEZ.

ÖLÇÜLDÜ (28 Eyl 2026, gerçek HTTP, misafir): `get_watch_page` yalnız `is_private`
bakıyordu — çöpteki, virüslü, Protected ve Deleted dosyanın başlığını ve kaynak
adresini 200 ile veriyordu; `asset_landing` çöpteki ve virüslü dosyada 200 sayfa
basıyordu. `seo_index.BLOCKED_LIFECYCLE_STATES` başlığı ise tersini söylüyor:
"bu durumdaki dosyanın METADATA'sı bile guest yüzeylere sızmamalı".

Karar tek yerde (`seo_index.decide` → `http_status`); iki uç da onu okur:
  * asset_landing: 401 / 404 / 410 olduğu gibi döner.
  * get_watch_page (+ `/medya/v/<slug>` render'ı): erişilemeyen her dosya
    "Video bulunamadı" (404) — private için zaten böyleydi.
Sınır: Unlisted "bağlantıyı bilen görür" demektir — erişilebilir kalır (noindex).

    bench --site dev.localhost run-tests --module tradehub_core.tests.test_media_guest_access
"""

from __future__ import annotations

from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase

# Tarama kancası bu modülde nötrleniyor — gerekçe `tests/av_notr.py` başlığında.
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401

SLUG = "mogem685-misafir-erisim"

#: (açıklama, File alanları, asset_landing beklenen durum)
ENGELLI = (
	("çöpte", {"th_media_state": "Trashed"}, 404),
	("kalıcı silinmiş durum", {"th_media_state": "Deleted"}, 410),
	("virüslü tarama", {"th_media_scan_status": "infected"}, 404),
	("korumalı", {"th_media_visibility": "Protected"}, 401),
	("silinmiş görünürlük", {"th_media_visibility": "Deleted"}, 410),
	("süresi dolmuş görünürlük", {"th_media_visibility": "Expired"}, 410),
)


class TestMedyaMisafirErisimi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Guest")
		self.addCleanup(frappe.set_user, "Administrator")
		self.doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": "mogem685-misafir.webm",
				"is_private": 0,
				"content": b"mogem685-misafir",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(self.doc.delete, ignore_permissions=True)
		frappe.db.set_value(
			"File",
			self.doc.name,
			{"th_media_slug": SLUG, "th_media_title": "Gizli Kalmalı Başlık"},
			update_modified=False,
		)

	def _durum(self, alanlar: dict) -> None:
		frappe.db.set_value("File", self.doc.name, alanlar, update_modified=False)

	def _landing(self):
		from tradehub_core.api import media_public

		return media_public.asset_landing(self.doc.name)

	def _watch(self):
		from tradehub_core.api import media_public

		return media_public.get_watch_page(SLUG)

	# ── pozitif: normal dosya görünür (test kör değil) ──

	def test_aktif_public_dosya_iki_uctan_gorunur(self):
		self.assertEqual(self._landing().status_code, 200)
		self.assertEqual(self._watch()["title"], "Gizli Kalmalı Başlık")

	def test_unlisted_erisilebilir_kalir(self):
		self._durum({"th_media_visibility": "Unlisted"})
		self.assertEqual(self._landing().status_code, 200)
		veri = self._watch()
		self.assertEqual(veri["title"], "Gizli Kalmalı Başlık")
		self.assertIn("noindex", veri["robots"])

	# ── negatif: erişilemeyen dosya hiçbir uçtan görünmez ──

	def test_erisilemeyen_dosya_asset_landing_reddeder(self):
		for ad, alanlar, beklenen in ENGELLI:
			with self.subTest(ad):
				self._durum(alanlar)
				yanit = self._landing()
				self.assertEqual(yanit.status_code, beklenen, ad)
				self.assertNotIn(b"Gizli Kalmal", yanit.get_data())
				self._durum({k: None for k in alanlar} | {"th_media_state": "Active"})

	def test_erisilemeyen_dosya_watch_page_bulunamadi(self):
		for ad, alanlar, _beklenen in ENGELLI:
			with self.subTest(ad):
				self._durum(alanlar)
				with self.assertRaises(frappe.DoesNotExistError, msg=ad):
					self._watch()
				self._durum({k: None for k in alanlar} | {"th_media_state": "Active"})

	def test_karantina_dizinindeki_dosya_iki_uctan_gorunmez(self):
		# Gerçek karantina dosyayı nginx kökünün dışına taşır; `av.in_quarantine`
		# o yolun varlığına bakar — burada o karar taklit ediliyor.
		with mock.patch("tradehub_core.media.av.in_quarantine", return_value=True):
			self.assertEqual(self._landing().status_code, 404)
			with self.assertRaises(frappe.DoesNotExistError):
				self._watch()

	def test_unlisted_ama_copteki_dosya_yine_gorunmez(self):
		# Engel görünürlükten ÖNCE gelir: Unlisted'in "erişilebilir" dalı çöpü kurtarmaz.
		self._durum({"th_media_visibility": "Unlisted", "th_media_state": "Trashed"})
		self.assertEqual(self._landing().status_code, 404)
		with self.assertRaises(frappe.DoesNotExistError):
			self._watch()

	def test_izleme_sayfasi_html_render_404(self):
		from tradehub_core.seo import page_resolver

		self._durum({"th_media_state": "Trashed"})
		yanit = page_resolver.render_media_watch(SLUG)
		self.assertEqual(yanit.status_code, 404)
		self.assertNotIn(b"Gizli Kalmal", yanit.get_data())

	def test_engelli_dosya_indexlenemez_kalir(self):
		# Site haritası/JSON-LD yalnız `indexable` okur — davranışı değişmemeli.
		from tradehub_core.media import seo_index

		for ad, alanlar, _beklenen in ENGELLI:
			with self.subTest(ad):
				self._durum(alanlar)
				self.assertFalse(seo_index.decide(self.doc.file_url, check_usage=False)["indexable"])
				self._durum({k: None for k in alanlar} | {"th_media_state": "Active"})
