"""Medya izleme sayfası — slug/canonical üretimi + 301 köprüsü (Task 1, TDD)."""

import tempfile
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import watch_slug
from tradehub_core.tests.test_video_poster import _yap_video


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
