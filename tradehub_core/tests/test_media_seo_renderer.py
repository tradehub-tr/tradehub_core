"""SEO görsel adresi — çözümleme + `SeoImageRenderer` (spec 2026-09-28-seo-gorsel-adresi §5.4, §6).

	docker exec istoc-dev-backend-1 bench --site istoc.localhost \
		run-tests --module tradehub_core.tests.test_media_seo_renderer
"""

from __future__ import annotations

import hashlib
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_files_path, now_datetime

from tradehub_core.media import seo_url
from tradehub_core.media.seo_renderer import SeoImageRenderer
from tradehub_core.tests.av_notr import setUpModule, tearDownModule  # noqa: F401


def _istek(x_accel: bool):
	"""Gerçek werkzeug isteği; `x_accel` → backend nginx'in bastığı başlık."""
	from werkzeug.test import EnvironBuilder
	from werkzeug.wrappers import Request

	basliklar = {"X-Use-X-Accel-Redirect": "True"} if x_accel else {}
	return Request(EnvironBuilder(path="/files/x.jpg", headers=basliklar).get_environ())


def _disk(h32: str, ad: str) -> str:
	return os.path.join(get_files_path(is_private=0), h32[:2], ad)


class _SeoBase(FrappeTestCase):
	"""Diske gerçek küçük dosya + kodlu `File` satırı. Temizlik: sil + commit."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.db.commit)  # en son çalışır: silmeleri kalıcılaştırır
		self.suffix = frappe.generate_hash(length=10)
		self.h32 = hashlib.sha256(f"seo-renderer-{self.suffix}".encode()).hexdigest()[:32]
		self.kod = self.h32[:8]
		self.u = f"/files/{self.h32[:2]}/{self.h32}.jpg"
		self.diskler: list[str] = []
		self._yaz(f"{self.h32}.jpg")
		self.dosyalar: list[str] = []
		self.ilanlar: list[str] = []
		frappe.cache.delete_value(seo_url._hassas_cache_key(self.h32))
		self.addCleanup(self._temizle)
		d = frappe.get_doc(
			{"doctype": "File", "file_name": f"rr-seo-{self.suffix}.jpg", "file_url": self.u, "is_private": 0}
		)
		d.flags.copy_from_existing_file = True
		d.flags.ignore_seo_code = True
		d.insert(ignore_permissions=True)
		self.dosyalar.append(d.name)
		frappe.db.set_value("File", d.name, "seo_code", self.kod, update_modified=False)

	def _yaz(self, ad: str) -> None:
		p = _disk(self.h32, ad)
		os.makedirs(os.path.dirname(p), exist_ok=True)
		with open(p, "wb") as f:
			f.write(b"seo-renderer-test")
		self.diskler.append(p)

	def _temizle(self) -> None:
		frappe.db.rollback()
		frappe.cache.delete_value(seo_url._owner_cache_key(self.u))
		frappe.cache.delete_value(seo_url._hassas_cache_key(self.h32))
		for n in self.ilanlar:
			if frappe.db.exists("Listing", n):
				frappe.delete_doc("Listing", n, force=True, ignore_permissions=True)
		for n in self.dosyalar:
			if frappe.db.exists("File", n):
				frappe.delete_doc("File", n, force=True, ignore_permissions=True)
		for p in self.diskler:
			if os.path.isfile(p):
				os.remove(p)

	def _sahipler(self, *sluglar: str):
		return mock.patch.object(seo_url, "owner_slugs", return_value=list(sluglar))


class TestResolve(_SeoBase):
	def test_ok(self):
		with self._sahipler("ahsap-raf"):
			r = seo_url.resolve(f"files/ahsap-raf-{self.kod}.jpg")
		self.assertEqual(r["status"], "ok")
		self.assertEqual(r["disk_url"], self.u)
		self.assertIsNone(r["canonical"])

	def test_bastaki_egik_cizgi_ve_sorgu_dizgesi(self):
		with self._sahipler("ahsap-raf"):
			r = seo_url.resolve(f"/files/ahsap-raf-{self.kod}.jpg?v=3")
		self.assertEqual((r["status"], r["disk_url"]), ("ok", self.u))

	def test_ikinci_urunun_slugi_da_ok(self):
		with self._sahipler("ahsap-raf", "mese-kitaplik"):
			r = seo_url.resolve(f"files/mese-kitaplik-{self.kod}.jpg")
		self.assertEqual(r["status"], "ok")

	def test_slug_eski_301(self):
		with self._sahipler("ahsap-raf", "mese-kitaplik"):
			r = seo_url.resolve(f"files/eski-ad-{self.kod}.jpg")
		self.assertEqual(r["status"], "slug_eski")
		self.assertEqual(r["canonical"], f"/files/ahsap-raf-{self.kod}.jpg")

	def test_sahipsiz_dosya_her_slugla_ok(self):
		with self._sahipler():
			r = seo_url.resolve(f"files/ne-olursa-{self.kod}.jpg")
		self.assertEqual(r["status"], "ok")

	def test_bilinmeyen_kod_yok(self):
		r = seo_url.resolve("files/x-00000000.jpg")
		self.assertEqual(r, {"status": "yok", "disk_url": None, "canonical": None})

	def test_uzanti_uyusmazsa_yok(self):
		with self._sahipler():
			r = seo_url.resolve(f"files/ahsap-raf-{self.kod}.png")
		self.assertEqual(r["status"], "yok")

	def test_diskte_yoksa_yok(self):
		os.remove(_disk(self.h32, f"{self.h32}.jpg"))
		with self._sahipler():
			r = seo_url.resolve(f"files/ahsap-raf-{self.kod}.jpg")
		self.assertEqual(r["status"], "yok")

	def test_turev(self):
		self._yaz(f"{self.h32}__w384.webp")
		with self._sahipler("ahsap-raf"):
			r = seo_url.resolve(f"files/ahsap-raf-{self.kod}__w384.webp")
			eski = seo_url.resolve(f"files/eski-{self.kod}__w384.webp")
		self.assertEqual(r["status"], "ok")
		self.assertEqual(r["disk_url"], f"/files/{self.h32[:2]}/{self.h32}__w384.webp")
		self.assertEqual(eski["canonical"], f"/files/ahsap-raf-{self.kod}__w384.webp")

	def test_turev_diskte_yoksa_yok(self):
		with self._sahipler():
			r = seo_url.resolve(f"files/ahsap-raf-{self.kod}__w999.webp")
		self.assertEqual(r["status"], "yok")

	def test_sondaki_satir_sonu_eslesmez(self):
		"""Review M-1: `$` sondaki `\n`'den önce de eşleşirdi."""
		with self._sahipler():
			self.assertEqual(seo_url.resolve(f"files/ahsap-raf-{self.kod}.jpg\n")["status"], "yok")
		self.assertIsNone(seo_url.HASHED_RE.match(self.u + "\n"))

	def test_yol_gecisi_denemesi_eslesmez(self):
		for kotu in (
			f"files/../../etc-{self.kod}.jpg",
			f"files/a/b-{self.kod}.jpg",
			f"files/ahsap-raf-{self.kod}__../x.jpg",
			f"files/Ahsap-{self.kod}.jpg",
		):
			self.assertEqual(seo_url.resolve(kotu)["status"], "yok", kotu)


class TestKapsam(_SeoBase):
	"""Final review I-1: okunur adres yalnız hassas olmayan GÖRSELLER için çözülür."""

	def _hassas_ikiz(self, **alanlar) -> None:
		d = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": f"rr-seo-dekont-{self.suffix}.jpg",
				"file_url": self.u,
				"is_private": 0,
				**alanlar,
			}
		)
		d.flags.copy_from_existing_file = True
		d.flags.ignore_seo_code = True
		d.flags.ignore_links = True
		d.insert(ignore_permissions=True)
		self.dosyalar.append(d.name)
		frappe.db.set_value("File", d.name, alanlar, update_modified=False)
		frappe.cache.delete_value(seo_url._hassas_cache_key(self.h32))

	def test_dekont_404(self):
		self._hassas_ikiz(attached_to_doctype="Payment Transaction", attached_to_name="TEST-SEO-PT")
		with self._sahipler():
			self.assertEqual(seo_url.resolve(f"files/x-{self.kod}.jpg")["status"], "yok")
			rr = SeoImageRenderer(f"files/x-{self.kod}.jpg")
			self.assertTrue(rr.can_render())
			self.assertEqual(rr.render().status_code, 404)

	def test_siparis_ekine_bagliysa_404(self):
		self._hassas_ikiz(attached_to_doctype="Order", attached_to_name="TEST-SEO-ORD")
		with self._sahipler():
			self.assertEqual(seo_url.resolve(f"files/x-{self.kod}.jpg")["status"], "yok")

	def test_ters_referans_receipt_url_404(self):
		"""`attached_to_*` boş yüklenmiş dekont: yalnız `Order.receipt_url`'de geçiyor."""
		gercek = frappe.db.exists

		def sahte(doctype, filtre=None, *a, **k):
			if doctype == "Order" and isinstance(filtre, dict) and "receipt_url" in filtre:
				return self.u in filtre["receipt_url"][1]
			return gercek(doctype, filtre, *a, **k)

		with self._sahipler(), mock.patch.object(frappe.db, "exists", side_effect=sahte):
			self.assertEqual(seo_url.resolve(f"files/x-{self.kod}.jpg")["status"], "yok")

	def test_hassas_sonuc_onbellekte(self):
		self.assertFalse(seo_url.hassas_mi(self.h32))
		with mock.patch.object(seo_url, "_hassas_hesapla", side_effect=AssertionError("önbellek yok")):
			self.assertFalse(seo_url.hassas_mi(self.h32))

	def test_mp4_kodlu_olsa_da_404(self):
		self._yaz(f"{self.h32}.mp4")
		mp4 = f"/files/{self.h32[:2]}/{self.h32}.mp4"
		d = frappe.get_doc(
			{"doctype": "File", "file_name": f"rr-seo-{self.suffix}.mp4", "file_url": mp4, "is_private": 0}
		)
		d.flags.copy_from_existing_file = True
		d.flags.ignore_seo_code = True
		d.flags.th_skip_transcode = True
		d.insert(ignore_permissions=True)
		self.dosyalar.append(d.name)
		frappe.db.set_value("File", d.name, "seo_code", self.kod, update_modified=False)
		with self._sahipler():
			self.assertEqual(seo_url.resolve(f"files/video-{self.kod}.mp4")["status"], "yok")
			rr = SeoImageRenderer(f"files/video-{self.kod}.mp4")
			self.assertTrue(rr.can_render())
			self.assertEqual(rr.render().status_code, 404)
		# Aynı kodun görseli etkilenmez.
		with self._sahipler():
			self.assertEqual(seo_url.resolve(f"files/x-{self.kod}.jpg")["status"], "ok")


class TestOwnerSlugs(_SeoBase):
	def _ilan(self, baslik: str, **alanlar) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Listing",
				"listing_code": f"RRSEO-{frappe.generate_hash(length=8)}",
				"title": baslik,
				"status": "Active",
				"currency": "TRY",
				"base_price": 100,
				"selling_price": 100,
				**alanlar,
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.ilanlar.append(doc.name)
		return doc.name

	def test_birincil_galeri_varyant_sirasiyla(self):
		# Listing controller'ı boş `primary_image`'ı ilk galeri görseliyle dolduruyor;
		# galeri/varyant sahibini ayrı ölçmek için birincil başka bir adres.
		baska = f"/files/rr-seo-baska-{self.suffix}.jpg"
		self._ilan(
			f"RR Varyant {self.suffix}",
			primary_image=baska,
			variant_items=[{"attribute_type": "Renk", "attribute_value": "Kırmızı", "variant_image": self.u}],
		)
		self._ilan(f"RR Galeri {self.suffix}", primary_image=baska, listing_images=[{"image": self.u}])
		self._ilan(f"RR Ana {self.suffix}", primary_image=self.u)
		s = self.suffix.lower()
		self.assertEqual(
			seo_url.owner_slugs(self.u),
			[f"rr-ana-{s}", f"rr-galeri-{s}", f"rr-varyant-{s}"],
		)

	def test_yayindaki_ilan_kanonik_once_gelir(self):
		"""Review M-4: taslak ilan eski olsa da kanonik slug yayındakinden; taslağın slug'ı yine kabul."""
		self._ilan(f"RR Taslak {self.suffix}", primary_image=self.u, status="Draft")
		self._ilan(f"RR Yayinda {self.suffix}", primary_image=self.u)
		s = self.suffix.lower()
		self.assertEqual(seo_url.owner_slugs(self.u), [f"rr-yayinda-{s}", f"rr-taslak-{s}"])
		self.assertEqual(seo_url.resolve(f"files/rr-taslak-{s}-{self.kod}.jpg")["status"], "ok")

	def test_onbellek_ve_ilan_kaydinda_dusurulmesi(self):
		"""Review I-1: ikinci çağrı DB'ye gitmez; ilan başlığı/görseli değişince önbellek düşer."""
		ad = self._ilan(f"RR Ilk {self.suffix}", primary_image=self.u)
		s = self.suffix.lower()
		self.assertEqual(seo_url.owner_slugs(self.u), [f"rr-ilk-{s}"])
		with mock.patch.object(frappe.db, "sql", side_effect=AssertionError("önbellek kullanılmadı")):
			self.assertEqual(seo_url.owner_slugs(self.u), [f"rr-ilk-{s}"])
		# Kaydetme (ör. başlık düzenleme) anahtarı düşürür. Not: `title` alanı bu sürümde
		# kayıtta başka bir kanca tarafından korunuyor; ölçülen şey önbelleğin düşmesi.
		doc = frappe.get_doc("Listing", ad)
		doc.flags.ignore_mandatory = True
		doc.save(ignore_permissions=True)
		self.assertIsNone(frappe.cache.get_value(seo_url._owner_cache_key(self.u), expires=True))
		self.assertEqual(seo_url.owner_slugs(self.u), [f"rr-ilk-{s}"])
		# Görsel ilandan çıkarıldı → eski görselin sahip listesi de düşmeli (kayıt öncesi hâl).
		doc.primary_image = f"/files/rr-seo-baska-{self.suffix}.jpg"
		doc.save(ignore_permissions=True)
		self.assertEqual(seo_url.owner_slugs(self.u), [])
		self.assertEqual(frappe.cache.get_value(seo_url._owner_cache_key(self.u), expires=True), [])

	def test_ilan_silinince_onbellek_duser(self):
		ad = self._ilan(f"RR Silinecek {self.suffix}", primary_image=self.u)
		self.assertEqual(seo_url.owner_slugs(self.u), [f"rr-silinecek-{self.suffix.lower()}"])
		frappe.delete_doc("Listing", ad, force=True, ignore_permissions=True)
		self.assertIsNone(frappe.cache.get_value(seo_url._owner_cache_key(self.u), expires=True))
		self.assertEqual(seo_url.owner_slugs(self.u), [])

	def test_sahipsiz_bos(self):
		self.assertEqual(seo_url.owner_slugs(self.u), [])

	def test_resolve_gercek_sahiplerle(self):
		self._ilan(f"RR Ana {self.suffix}", primary_image=self.u)
		s = self.suffix.lower()
		self.assertEqual(seo_url.resolve(f"files/rr-ana-{s}-{self.kod}.jpg")["status"], "ok")
		r = seo_url.resolve(f"files/baska-{self.kod}.jpg")
		self.assertEqual((r["status"], r["canonical"]), ("slug_eski", f"/files/rr-ana-{s}-{self.kod}.jpg"))


class TestStubIleIceAktarma(FrappeTestCase):
	def test_minimal_frappe_stubiyla_yuklenir(self):
		"""api/* sözleşme testleri `frappe`'yi minimal stub'la değiştiriyor; seo_url modül
		düzeyinde `frappe.utils` gibi alt modül içe aktarmamalı."""
		import subprocess
		import sys

		kod = (
			"import sys, types; sys.modules['frappe'] = types.ModuleType('frappe'); "
			"from tradehub_core.media import seo_url; "
			"assert seo_url.make_slug('Ahşap Raf') == 'ahsap-raf'"
		)
		sonuc = subprocess.run([sys.executable, "-c", kod], capture_output=True, text=True, timeout=60)
		self.assertEqual(sonuc.returncode, 0, sonuc.stderr[-2000:])


class TestRenderer(_SeoBase):
	def test_renderer_basliklari(self):
		with (
			self._sahipler("ahsap-raf"),
			mock.patch.object(frappe.local, "request", _istek(x_accel=True), create=True),
		):
			rr = SeoImageRenderer(f"files/ahsap-raf-{self.kod}.jpg")
			self.assertTrue(rr.can_render())
			yanit = rr.render()
		self.assertEqual(yanit.status_code, 200)
		self.assertEqual(
			yanit.headers["X-Accel-Redirect"], f"/protected/public/files/{self.h32[:2]}/{self.h32}.jpg"
		)
		self.assertEqual(yanit.get_data(), b"")
		self.assertEqual(yanit.headers["Cache-Control"], "public, max-age=31536000, immutable")
		self.assertEqual(yanit.headers["Content-Type"], "image/jpeg")
		self.assertNotIn("X-Robots-Tag", yanit.headers)

	def test_renderer_cerez_basmaz(self):
		"""Çerezli yanıtı CDN önbelleğe almaz — renderer bekleyen çerezleri düşürür."""
		from frappe.auth import CookieManager

		yonetici = CookieManager()
		yonetici.set_cookie("full_name", "Guest")
		with (
			mock.patch.object(frappe.local, "cookie_manager", yonetici, create=True),
			self._sahipler("ahsap-raf"),
		):
			rr = SeoImageRenderer(f"files/ahsap-raf-{self.kod}.jpg")
			self.assertTrue(rr.can_render())
			rr.render()
			self.assertEqual(frappe.local.cookie_manager.cookies, {})

	def test_x_accel_basligi_yoksa_baytlari_akitir(self):
		"""Final review I-2: X-Accel'i işlemeyen bir yolda boş gövdeli 200 dönmemeli."""
		with (
			self._sahipler("ahsap-raf"),
			mock.patch.object(frappe.local, "request", _istek(x_accel=False), create=True),
		):
			rr = SeoImageRenderer(f"files/ahsap-raf-{self.kod}.jpg")
			self.assertTrue(rr.can_render())
			yanit = rr.render()
			yanit.direct_passthrough = False
			govde = yanit.get_data()
		self.assertEqual(yanit.status_code, 200)
		self.assertNotIn("X-Accel-Redirect", yanit.headers)
		self.assertEqual(govde, b"seo-renderer-test")
		self.assertEqual(yanit.headers["Cache-Control"], "public, max-age=31536000, immutable")
		self.assertEqual(yanit.headers["Content-Type"], "image/jpeg")
		self.assertNotIn("X-Robots-Tag", yanit.headers)

	def test_bayrak_kapaliyken_renderer_calismaya_devam_eder(self):
		"""Review M-8: kill switch yalnız ÜRETİMİ keser; dışarıdaki okunur adres 200 kalır."""
		with (
			mock.patch.dict(frappe.local.conf, {seo_url.BAYRAK: 0}),
			self._sahipler("ahsap-raf"),
			mock.patch.object(frappe.local, "request", _istek(x_accel=True), create=True),
		):
			self.assertEqual(seo_url.seo_image_url(self.u, "Ahşap Raf"), self.u)
			rr = SeoImageRenderer(f"files/ahsap-raf-{self.kod}.jpg")
			self.assertTrue(rr.can_render())
			self.assertEqual(rr.render().status_code, 200)

	def test_renderer_turev_webp(self):
		self._yaz(f"{self.h32}__w384.webp")
		with (
			self._sahipler(),
			mock.patch.object(frappe.local, "request", _istek(x_accel=True), create=True),
		):
			rr = SeoImageRenderer(f"files/x-{self.kod}__w384.webp")
			self.assertTrue(rr.can_render())
			yanit = rr.render()
		self.assertEqual(yanit.headers["Content-Type"], "image/webp")
		self.assertTrue(yanit.headers["X-Accel-Redirect"].endswith(f"{self.h32}__w384.webp"))

	def test_renderer_301(self):
		with self._sahipler("ahsap-raf"):
			rr = SeoImageRenderer(f"files/eski-ad-{self.kod}.jpg")
			self.assertTrue(rr.can_render())
			yanit = rr.render()
		self.assertEqual(yanit.status_code, 301)
		self.assertTrue(yanit.headers["Location"].endswith(f"/files/ahsap-raf-{self.kod}.jpg"))
		self.assertEqual(yanit.headers["Cache-Control"], "public, max-age=300")

	def test_renderer_bilinmeyen_kod_404_onbellege_yazilmaz(self):
		"""`NotFoundPage` `website_404`'e yazar ve Frappe o önbelleğe renderer'lardan önce
		bakar: türev sonradan üretilse bile adres kalıcı 404 kalırdı. Kendi 404'ümüz yazmaz."""
		yol = f"files/x-{self.kod}__w999.webp"
		url = f"http://istoc.localhost/{yol}"
		frappe.cache.hdel("website_404", url)
		self.addCleanup(lambda: frappe.cache.hdel("website_404", url))
		frappe.flags.force_website_cache = True  # lokalde developer_mode önbelleği kapatıyor
		self.addCleanup(lambda: setattr(frappe.flags, "force_website_cache", False))
		rr = SeoImageRenderer(yol)
		with mock.patch.object(frappe.local, "request", mock.Mock(url=url), create=True):
			self.assertTrue(rr.can_render())
			yanit = rr.render()
		self.assertEqual(yanit.status_code, 404)
		self.assertEqual(yanit.headers["Cache-Control"], "public, max-age=60")
		self.assertFalse(frappe.cache.hget("website_404", url))
		# Türev şimdi üretildi → aynı adres hemen 200.
		self._yaz(f"{self.h32}__w999.webp")
		rr2 = SeoImageRenderer(yol)
		self.assertTrue(rr2.can_render())
		self.assertEqual(rr2.render().status_code, 200)

	def test_okunur_desene_uyan_eski_ad_301_koprusunu_kaybetmez(self):
		"""`urun-20240101.jpg` gibi eski ad SEO_RE'ye uyar; kod tanınmazsa eski-ad
		köprüsü (Media URL Redirect) yine çalışmalı."""
		kaynak = f"/files/rr-eski-{self.suffix[:8].lower()}ab.jpg"
		frappe.get_doc(
			{
				"doctype": "Media URL Redirect",
				"source_url": kaynak,
				"target_url": self.u,
				"job_key": "TEST-SEO-RR",
				"expires_at": add_days(now_datetime(), 90),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("Media URL Redirect", {"job_key": "TEST-SEO-RR"}))
		with mock.patch.object(
			seo_url, "resolve", return_value={"status": "yok", "disk_url": None, "canonical": None}
		):
			rr = SeoImageRenderer(kaynak.lstrip("/"))
			self.assertTrue(rr.can_render())
			yanit = rr.render()
		self.assertEqual(yanit.status_code, 301)
		self.assertTrue(yanit.headers["Location"].endswith(self.u))

	def test_renderer_baska_yol_ilgilenmez(self):
		for yol in (
			"urun/abc",
			"files/0585.jpg",
			f"files/{self.h32[:2]}/{self.h32}.jpg",
			"private/files/a-12345678.jpg",
		):
			self.assertFalse(SeoImageRenderer(yol).can_render(), yol)

	def test_hooks_sirasi(self):
		sira = frappe.get_hooks("page_renderer")
		self.assertLess(
			sira.index("tradehub_core.media.seo_renderer.SeoImageRenderer"),
			sira.index("tradehub_core.media.redirect_renderer.MediaRedirectRenderer"),
		)
