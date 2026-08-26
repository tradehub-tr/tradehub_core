"""Medya izleme sayfası — slug/canonical üretimi + 301 köprüsü (Task 1, TDD)."""

import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import watch_slug
from tradehub_core.tests.test_video_poster import _yap_video


def _gorunur_ilan() -> dict | None:
	"""Vitrinde görünen ilk ilan — `test_media_video_seo.py::_gorunur_ilan` ile
	aynı desen: seed demo veriyi kullanır, sıfırdan Listing kurmak yerine."""
	satirlar = frappe.db.sql(
		"""
		SELECT l.name FROM `tabListing` l
		WHERE l.storefront_visible = 1 AND l.status = 'Active'
		ORDER BY l.name ASC LIMIT 1
		""",
		as_dict=True,
	)
	return satirlar[0] if satirlar else None


class TestWatchSlug(FrappeTestCase):
	def _video_dosyasi(
		self, yol: Path, *, title: str = "", file_url: str | None = None
	) -> "frappe.model.document.Document":
		payload = {"doctype": "File", "file_name": yol.name, "is_private": 0}
		if title:
			payload["th_media_title"] = title
		if file_url:
			# Kardeş kayıt deseni: içerik göndermeden mevcut bir adrese işaret
			# ettir (video_poster.generate testindeki desenle aynı).
			payload["file_url"] = file_url
		else:
			with open(yol, "rb") as f:
				payload["content"] = f.read()
		doc = frappe.get_doc(payload).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		return doc

	def test_basliktan_slug_uretir_ve_canonical_yazar(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "tanitim.mp4"
			_yap_video(v)
			doc = self._video_dosyasi(v, title="Yeni Ürün Tanıtımı")
			slug = watch_slug.ensure_slug(doc.file_url)
			self.assertEqual(slug, "yeni-urun-tanitimi")
			self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_slug"), "yeni-urun-tanitimi")
			self.assertEqual(
				frappe.db.get_value("File", doc.name, "th_media_canonical"),
				"/medya/v/yeni-urun-tanitimi",
			)

	def test_ayni_baslikli_ikinci_videoda_hash_eki(self):
		with tempfile.TemporaryDirectory() as tmp:
			v1 = Path(tmp) / "birinci.mp4"
			v2 = Path(tmp) / "ikinci.mp4"
			_yap_video(v1, sure=3)
			_yap_video(v2, sure=5)  # farklı süre → farklı içerik/content_hash
			doc1 = self._video_dosyasi(v1, title="Kampanya Videosu")
			doc2 = self._video_dosyasi(v2, title="Kampanya Videosu")
			slug1 = watch_slug.ensure_slug(doc1.file_url)
			slug2 = watch_slug.ensure_slug(doc2.file_url)
			self.assertEqual(slug1, "kampanya-videosu")
			self.assertNotEqual(slug2, slug1)
			self.assertTrue(slug2.startswith("kampanya-videosu-"), slug2)
			hash6 = slug2.rsplit("-", 1)[-1]
			self.assertEqual(len(hash6), 6)

	def test_change_slug_301_kopru_acar(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "koseli.mp4"
			_yap_video(v)
			doc = self._video_dosyasi(v, title="Eski Başlık")
			eski_slug = watch_slug.ensure_slug(doc.file_url)
			self.assertTrue(eski_slug)

			yeni_slug = watch_slug.change_slug(doc.file_url, "yeni-baslik")
			self.assertEqual(yeni_slug, "yeni-baslik")
			self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_slug"), "yeni-baslik")
			self.assertEqual(
				frappe.db.get_value("File", doc.name, "th_media_canonical"), "/medya/v/yeni-baslik"
			)

			redirect = frappe.db.get_value(
				"Media URL Redirect",
				{
					"source_url": watch_slug.watch_url(eski_slug),
					"target_url": watch_slug.watch_url("yeni-baslik"),
				},
				["name", "job_key"],
				as_dict=True,
			)
			self.assertIsNotNone(redirect)
			self.assertEqual(redirect.job_key, "watch-slug")
			self.addCleanup(
				lambda: frappe.delete_doc(
					"Media URL Redirect", redirect.name, ignore_permissions=True, force=True
				)
			)

	def test_yerel_olmayan_adres_bos_doner_ve_yazmaz(self):
		slug = watch_slug.ensure_slug("https://youtu.be/dQw4w9WgXcQ")
		self.assertEqual(slug, "")

	def test_kardes_kayitlara_ayni_slug_yazilir(self):
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "coklu.mp4"
			_yap_video(v)
			ilk = self._video_dosyasi(v, title="Paylaşılan Video")
			ikinci = self._video_dosyasi(v, title="Paylaşılan Video", file_url=ilk.file_url)
			self.assertEqual(ikinci.file_url, ilk.file_url)

			slug = watch_slug.ensure_slug(ilk.file_url)
			self.assertTrue(slug)
			self.assertEqual(frappe.db.get_value("File", ilk.name, "th_media_slug"), slug)
			self.assertEqual(frappe.db.get_value("File", ikinci.name, "th_media_slug"), slug)

	# ── Düzeltme turu 1 (denetim bulguları 1-3) ─────────────────────────────

	def test_change_slug_gecersiz_deger_reddedilir(self):
		"""Düzeltme 1: `slugify_tr` boş dönerse ham değere düşülmez — throw."""
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "gecersiz.mp4"
			_yap_video(v)
			doc = self._video_dosyasi(v, title="Geçerli Başlık")
			eski_slug = watch_slug.ensure_slug(doc.file_url)
			self.assertTrue(eski_slug)

			self.assertRaises(frappe.ValidationError, watch_slug.change_slug, doc.file_url, "!!!")
			self.assertEqual(frappe.db.get_value("File", doc.name, "th_media_slug"), eski_slug)

	def test_change_slug_zincir_cokertir(self):
		"""Düzeltme 2a: A→B iken B→C yazılırsa A'nın hedefi de C'ye çevrilir."""
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "zincir.mp4"
			_yap_video(v)
			doc = self._video_dosyasi(v, title="Zincir Videosu")
			a = watch_slug.ensure_slug(doc.file_url)
			b = watch_slug.change_slug(doc.file_url, "b-slug")
			c = watch_slug.change_slug(doc.file_url, "c-slug")
			self.assertEqual(b, "b-slug")
			self.assertEqual(c, "c-slug")

			a_hedefi = frappe.db.get_value(
				"Media URL Redirect", {"source_url": watch_slug.watch_url(a)}, "target_url"
			)
			self.assertEqual(a_hedefi, watch_slug.watch_url("c-slug"))
			b_hedefi = frappe.db.get_value(
				"Media URL Redirect", {"source_url": watch_slug.watch_url("b-slug")}, "target_url"
			)
			self.assertEqual(b_hedefi, watch_slug.watch_url("c-slug"))
			self.addCleanup(
				lambda: frappe.db.delete(
					"Media URL Redirect",
					{"source_url": ("in", [watch_slug.watch_url(a), watch_slug.watch_url("b-slug")])},
				)
			)

	def test_change_slug_geri_donuste_dongu_olusmaz(self):
		"""Düzeltme 2b: A→B sonra tekrar A'ya dönülürse source=A satırı silinir,
		source=B→target=A satırı kalır — döngü oluşmaz."""
		with tempfile.TemporaryDirectory() as tmp:
			v = Path(tmp) / "geridonus.mp4"
			_yap_video(v)
			doc = self._video_dosyasi(v, title="Geri Dönüş Videosu")
			a = watch_slug.ensure_slug(doc.file_url)
			watch_slug.change_slug(doc.file_url, "gecici-slug")
			geri = watch_slug.change_slug(doc.file_url, a)
			self.assertEqual(geri, a)

			self.assertFalse(frappe.db.exists("Media URL Redirect", {"source_url": watch_slug.watch_url(a)}))
			gecici_hedefi = frappe.db.get_value(
				"Media URL Redirect", {"source_url": watch_slug.watch_url("gecici-slug")}, "target_url"
			)
			self.assertEqual(gecici_hedefi, watch_slug.watch_url(a))
			self.addCleanup(
				lambda: frappe.db.delete(
					"Media URL Redirect", {"source_url": watch_slug.watch_url("gecici-slug")}
				)
			)

	def test_ensure_slug_yaris_sonrasi_ayrisir(self):
		"""Düzeltme 3: TOCTOU — iki farklı içerikli dosyaya elle AYNI slug
		basılmış olsun (yarışı simüle eder); `ensure_slug` ikinciye çağrılınca
		yalnız o hash ekli slug'a ayrışır, ilk kayda dokunulmaz."""
		with tempfile.TemporaryDirectory() as tmp:
			v1 = Path(tmp) / "yaris1.mp4"
			v2 = Path(tmp) / "yaris2.mp4"
			_yap_video(v1, sure=3)
			_yap_video(v2, sure=6)
			doc1 = self._video_dosyasi(v1, title="Yarış Videosu Bir")
			doc2 = self._video_dosyasi(v2, title="Yarış Videosu İki")
			frappe.db.set_value("File", doc1.name, "th_media_slug", "cakisan-slug", update_modified=False)
			frappe.db.set_value("File", doc2.name, "th_media_slug", "cakisan-slug", update_modified=False)

			sonuc = watch_slug.ensure_slug(doc2.file_url)
			self.assertNotEqual(sonuc, "cakisan-slug")
			self.assertTrue(sonuc.startswith("cakisan-slug-"), sonuc)
			self.assertEqual(frappe.db.get_value("File", doc2.name, "th_media_slug"), sonuc)
			self.assertEqual(
				frappe.db.get_value("File", doc2.name, "th_media_canonical"), watch_slug.watch_url(sonuc)
			)
			# İlk kayda dokunulmadı — yarışta kaybeden taraf değişmez.
			self.assertEqual(frappe.db.get_value("File", doc1.name, "th_media_slug"), "cakisan-slug")


class TestGetWatchPage(FrappeTestCase):
	"""Task 2 — `get_watch_page` sözleşmesi + `watch_indexable` W3 üçlüsü."""

	def _video_dosyasi(self, file_name: str, *, is_private: int = 0, **ekstra) -> "frappe.model.document.Document":
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": file_name,
				"is_private": is_private,
				"content": f"watch-page-test-{file_name}".encode(),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def _slug_ver(self, doc, slug: str) -> None:
		frappe.db.set_value(
			"File",
			doc.name,
			{"th_media_slug": slug, "th_media_canonical": watch_slug.watch_url(slug)},
			update_modified=False,
		)

	def _ilan_video_baglar(self, ilan_adi: str, file_url: str, *, storefront_visible: int = 1):
		eski_video_url = frappe.db.get_value("Listing", ilan_adi, "video_url")
		eski_gorunurluk = frappe.db.get_value("Listing", ilan_adi, "storefront_visible")
		frappe.db.set_value(
			"Listing",
			ilan_adi,
			{"video_url": file_url, "storefront_visible": storefront_visible},
			update_modified=False,
		)

		def _geri_al():
			frappe.db.set_value(
				"Listing",
				ilan_adi,
				{"video_url": eski_video_url, "storefront_visible": eski_gorunurluk},
				update_modified=False,
			)

		self.addCleanup(_geri_al)

	def test_tam_alanli_video_sozlesme_anahtarlari_eksiksiz(self):
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi(
			"watch-tam-alanli.webm",
			th_media_title="Tam Alanlı Video",
			th_media_caption="Kısa altyazı",
			th_media_description="Uzun açıklama",
			th_media_transcript="merhaba dünya",
			th_media_poster_url="/files/watch-poster.jpg",
			th_media_captions_url="/files/watch-cap.vtt",
			th_media_duration=42.5,
			th_media_creator="İstoç",
			th_media_credit_text="İstoç Medya",
			th_media_copyright_notice="© İstoç",
			th_media_license_url="https://example.com/lisans",
			th_media_acquire_license_url="https://example.com/lisans-al",
		)
		self._slug_ver(doc, "watch-tam-alanli-slug")
		self._ilan_video_baglar(ilan["name"], doc.file_url, storefront_visible=1)

		data = media_public.get_watch_page("watch-tam-alanli-slug")

		self.assertEqual(data["title"], "Tam Alanlı Video")
		self.assertEqual(data["caption"], "Kısa altyazı")
		self.assertEqual(data["description"], "Uzun açıklama")
		self.assertEqual(data["transcript"], "merhaba dünya")
		self.assertEqual(data["posterUrl"], "/files/watch-poster.jpg")
		self.assertEqual(data["captionsUrl"], "/files/watch-cap.vtt")
		self.assertEqual(data["durationSec"], 42.5)
		self.assertTrue(data["uploadDate"])

		self.assertEqual(len(data["sources"]), 1)
		self.assertEqual(data["sources"][0]["src"], doc.file_url)
		self.assertTrue(data["sources"][0]["type"])

		license_ = data["license"]
		self.assertEqual(
			set(license_.keys()),
			{"creator", "creditText", "copyrightNotice", "licenseUrl", "acquireLicensePageUrl"},
			"license sözleşmesi TAM 5 anahtar taşımalı — spec fazlasını istemiyor",
		)
		self.assertEqual(license_["creator"], "İstoç")
		self.assertEqual(license_["creditText"], "İstoç Medya")
		self.assertEqual(license_["copyrightNotice"], "© İstoç")
		self.assertEqual(license_["licenseUrl"], "https://example.com/lisans")
		self.assertEqual(license_["acquireLicensePageUrl"], "https://example.com/lisans-al")

		self.assertEqual(len(data["listings"]), 1)
		self.assertEqual(data["listings"][0]["slug"], frappe.db.get_value("Listing", ilan["name"], "slug"))

		self.assertTrue(data["indexable"])
		self.assertIn("/medya/v/watch-tam-alanli-slug", data["canonical"])
		self.assertNotIn("noindex", data["robots"])

	def test_storefront_visible_sifir_indexable_false_ve_noindex(self):
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi(
			"watch-gizli-ilan.webm",
			th_media_title="Gizli İlan Videosu",
			th_media_poster_url="/files/watch-gizli-poster.jpg",
		)
		self._slug_ver(doc, "watch-gizli-ilan-slug")
		self._ilan_video_baglar(ilan["name"], doc.file_url, storefront_visible=0)

		data = media_public.get_watch_page("watch-gizli-ilan-slug")

		self.assertFalse(data["indexable"])
		self.assertIn("noindex", data["robots"])
		self.assertEqual(data["listings"], [])

	def test_postersiz_video_indexable_false(self):
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi("watch-postersiz.webm", th_media_title="Postersiz Video")
		self._slug_ver(doc, "watch-postersiz-slug")
		self._ilan_video_baglar(ilan["name"], doc.file_url, storefront_visible=1)

		data = media_public.get_watch_page("watch-postersiz-slug")

		self.assertFalse(data["indexable"])
		self.assertIn("noindex", data["robots"])

	def test_bilinmeyen_slug_docs_not_exist(self):
		from tradehub_core.api import media_public

		with self.assertRaises(frappe.DoesNotExistError):
			media_public.get_watch_page("hic-boyle-bir-slug-yok")

	def test_private_dosya_docs_not_exist(self):
		from tradehub_core.api import media_public

		doc = self._video_dosyasi("watch-private.webm", is_private=1, th_media_poster_url="/files/x.jpg")
		self._slug_ver(doc, "watch-private-slug")

		with self.assertRaises(frappe.DoesNotExistError):
			media_public.get_watch_page("watch-private-slug")

	def test_sources_poster_webp_sizmaz(self):
		"""Düzeltme turu 1, bulgu 4 — `_sources`'ın poster (webp) girdisi `sources`'a
		SIZMAMALI, yalnız video MIME'ları geçmeli. Gerçek `Media Rendition` fixture'ı
		ağır (Media Version + birden çok rendition satırı); `_sources`'ı monkeypatch'leyip
		yalnız `_video_sources`'ın filtre davranışını birim düzeyinde doğruluyoruz —
		`_sources`'ın kendisi zaten görsel format haritasıyla (avif/webp/jpeg/png)
		çalıştığı için gerçek video render'ında da `webp` (poster) HER ZAMAN bu yoldan
		geçer, `mp4`/`m3u8` asla `_sources`'ın type haritasına girmez (bilinçli sınır,
		rapor: `task-2-report.md`)."""
		from unittest import mock

		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi(
			"watch-source-filtre.webm",
			th_media_title="Kaynak Filtresi",
			th_media_poster_url="/files/watch-source-poster.jpg",
		)
		self._slug_ver(doc, "watch-source-filtre-slug")
		self._ilan_video_baglar(ilan["name"], doc.file_url, storefront_visible=1)

		asset = frappe.get_doc(
			{
				"doctype": "Media Asset",
				"slot_key": "product.video",
				"media_type": "video",
				"state": "ready",
				"source_file": doc.name,
				"content_sha256": frappe.generate_hash(length=32),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(asset.delete, ignore_permissions=True)

		sahte_items = [
			{"type": "image/webp", "srcset": "/files/watch-source-poster-1280.webp 1280w"},
			{"type": "video/mp4", "srcset": "/files/watch-source-video-1280.mp4 1280w"},
		]
		with mock.patch.object(
			media_public, "_sources", return_value=(sahte_items, "/files/watch-source-poster-1280.webp")
		):
			data = media_public.get_watch_page("watch-source-filtre-slug")

		tipler = {s["type"] for s in data["sources"]}
		self.assertNotIn("image/webp", tipler, "poster profilinin webp rendition'ı sources'a sızmamalı")
		self.assertEqual(
			data["sources"], [{"src": "/files/watch-source-video-1280.mp4", "type": "video/mp4"}]
		)


class TestWatchIndexable(FrappeTestCase):
	"""`watch_indexable` — W3 üçlüsü doğrudan test edilir (Task 3'ün resolver'ı bunu kullanacak)."""

	def _video_dosyasi(self, file_name: str, **ekstra) -> "frappe.model.document.Document":
		doc = frappe.get_doc(
			{"doctype": "File", "file_name": file_name, "is_private": 0, "content": f"wi-{file_name}".encode()}
		).insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True)
		if ekstra:
			frappe.db.set_value("File", doc.name, ekstra, update_modified=False)
		return doc

	def test_uc_kosul_da_saglaninca_true(self):
		from tradehub_core.api import media_public

		ilan = _gorunur_ilan()
		if not ilan:
			self.skipTest("Vitrinde görünen ilan yok — fixture kurulamaz.")

		doc = self._video_dosyasi("wi-tam.webm", th_media_poster_url="/files/wi-poster.jpg")
		eski_video_url = frappe.db.get_value("Listing", ilan["name"], "video_url")
		eski_gorunurluk = frappe.db.get_value("Listing", ilan["name"], "storefront_visible")
		frappe.db.set_value(
			"Listing", ilan["name"], {"video_url": doc.file_url, "storefront_visible": 1}, update_modified=False
		)
		self.addCleanup(
			lambda: frappe.db.set_value(
				"Listing",
				ilan["name"],
				{"video_url": eski_video_url, "storefront_visible": eski_gorunurluk},
				update_modified=False,
			)
		)

		self.assertTrue(media_public.watch_indexable(doc.file_url))

	def test_ilana_baglanmamis_video_false(self):
		from tradehub_core.api import media_public

		doc = self._video_dosyasi("wi-baglanmamis.webm", th_media_poster_url="/files/wi-poster2.jpg")
		self.assertFalse(media_public.watch_indexable(doc.file_url))

	def test_disaridan_verilen_fields_ve_listings_tekrar_hesaplanmaz(self):
		"""Düzeltme turu 1, bulgu 3 — `_watch_data` çağırırken önceden hesaplanmış
		`fields`/`listings` geçirilirse `watch_indexable` bu ikisini YENİDEN
		sorgulamaz. `seo.fields_for` yine de `seo_index.decide()`'ın kendi
		`rights_expires_on` kontrolü için çağrılır (buna dokunmuyoruz — TEK karar
		noktasının kapsamı `watch_indexable`'ın KENDİ mantığı, `decide()`'ın içi
		değil); mock `{}` döndürecek şekilde zararsız bırakılıp asıl iddia şuna
		daralıyor: dış poster kontrolü verilen `fields` dict'inden okunuyor, mock'un
		boş dönüşünden ETKİLENMİYOR. `_storefront_listings` ise hiç çağrılmamalı —
		`listings` verildiği için o dal hiç girilmiyor."""
		from unittest import mock

		from tradehub_core.api import media_public

		doc = self._video_dosyasi("wi-parametre.webm")

		with (
			mock.patch.object(media_public.seo, "fields_for", return_value={}),
			mock.patch.object(media_public, "_storefront_listings") as sahte_listings,
		):
			sonuc = media_public.watch_indexable(
				doc.file_url,
				fields={"poster_url": "/files/wi-poster3.jpg"},
				listings=[{"slug": "x", "title": "y", "primary_image": "/files/z.jpg"}],
			)

		sahte_listings.assert_not_called()
		self.assertTrue(
			sonuc, "verilen `fields`/`listings` kullanılmalı, mock'un boş dönüşü sonucu etkilememeli"
		)
