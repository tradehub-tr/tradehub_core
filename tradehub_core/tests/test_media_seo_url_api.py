"""SEO'lu görsel adresi — vitrin API/SEO çıktıları (spec 2026-09-28-seo-gorsel-adresi-design.md §5.3).

Her uçta içerik-kodlu (`/files/xx/<hash32>.jpg`) görselin okunur adresle
(`/files/<ilan-başlığı-slug>-<kod>.jpg`) çıktığı; üretilemediğinde (eski ad)
adresin aynen kaldığı doğrulanır. DB değerleri değişmez, yalnız çıktı.

	docker exec istoc-dev-backend-1 bench --site istoc.localhost \
		run-tests --module tradehub_core.tests.test_media_seo_url_api
"""

from __future__ import annotations

import hashlib
import os

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_files_path, nowdate

from tradehub_core.media import seo_url
from tradehub_core.tests import av_notr

_DISK: set[str] = set()


_ESKI_BAYRAK = None


def setUpModule():
	global _ESKI_BAYRAK
	# Tarama kancası nötr: dosya insert anında karantinaya taşınmasın (av_notr başlığı).
	av_notr.basla()
	# Final review I-2: okunur adres `seo_image_urls` bayrağına bağlı; bu modül açık hâli ölçer.
	_ESKI_BAYRAK = frappe.local.conf.get(seo_url.BAYRAK)
	frappe.local.conf[seo_url.BAYRAK] = 1


def tearDownModule():
	av_notr.bitir()
	if _ESKI_BAYRAK is None:
		frappe.local.conf.pop(seo_url.BAYRAK, None)
	else:
		frappe.local.conf[seo_url.BAYRAK] = _ESKI_BAYRAK
	for yol in _DISK:
		if os.path.exists(yol):
			os.remove(yol)


def _icerik_kodlu(icerik: bytes, uzanti: str = ".jpg") -> str:
	"""Diskte içerik-kodlu dosya + `File` satırı + kısa kod. Adresi döndürür."""
	h = hashlib.sha256(icerik).hexdigest()[:32]
	url = f"/files/{h[:2]}/{h}{uzanti}"
	yol = os.path.join(get_files_path(is_private=0), h[:2], f"{h}{uzanti}")
	os.makedirs(os.path.dirname(yol), exist_ok=True)
	with open(yol, "wb") as f:
		f.write(icerik)
	_DISK.add(yol)
	d = frappe.get_doc({"doctype": "File", "file_name": f"{h}{uzanti}", "file_url": url, "is_private": 0})
	d.flags.copy_from_existing_file = True
	d.flags.ignore_mandatory = True
	d.insert(ignore_permissions=True)
	seo_url.assign_code(url)
	return url


def _beklenen(url: str, baslik: str, turev: str = "", uzanti: str = ".jpg") -> str:
	kod = frappe.db.get_value("File", {"file_url": url}, "seo_code")
	return f"/files/{seo_url.make_slug(baslik)}-{kod}{turev}{uzanti}"


class _SeoApiBase(FrappeTestCase):
	"""İçerik-kodlu ana + galeri + varyant görselli, satıcılı tek ilan."""

	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		# setUp commit ediyor (ve detay ucu görüntülenme sayacını commit ediyor);
		# silmeler de kalıcı olsun diye ilk kaydedilen temizlik commit — en son koşar.
		self.addCleanup(frappe.db.commit)
		self.addCleanup(frappe.set_user, "Administrator")
		self.sfx = frappe.generate_hash(length=8)
		self.baslik = f"Çelik Termos {self.sfx}"
		self.ana = _icerik_kodlu(f"ana-{self.sfx}".encode())
		self.galeri = _icerik_kodlu(f"galeri-{self.sfx}".encode())
		self.varyant = _icerik_kodlu(f"varyant-{self.sfx}".encode())
		self.addCleanup(self._dosyalari_sil)
		self.satici = frappe.db.get_value("Admin Seller Profile", {}, "name")
		self.ilan = self._ilan_kur(self.baslik, self.ana)
		frappe.db.commit()

	def _ilan_kur(self, baslik: str, ana: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Listing",
				"listing_code": f"SEOAPI-{frappe.generate_hash(length=8)}",
				"title": baslik,
				"status": "Active",
				"currency": "TRY",
				"base_price": 100,
				"selling_price": 100,
				"primary_image": ana,
				"listing_images": [{"image": self.galeri}],
				"variant_items": [
					{"attribute_type": "Renk", "attribute_value": "Kırmızı", "variant_image": self.varyant}
				],
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		self.addCleanup(
			lambda n=doc.name: frappe.delete_doc("Listing", n, force=True, ignore_permissions=True)
		)
		if self.satici:
			# Doğrulamayı atlayarak satıcı bağla — sepet satırı satıcısız gösterilmiyor.
			frappe.db.set_value("Listing", doc.name, "seller_profile", self.satici, update_modified=False)
		return doc.name

	def _dosyalari_sil(self):
		for url in (self.ana, self.galeri, self.varyant):
			frappe.db.delete("File", {"file_url": url})

	def assertOkunur(self, gercek: str, url: str, baslik: str | None = None, **kw):
		yol = gercek[gercek.find("/files/") :] if "/files/" in gercek else gercek
		self.assertRegex(yol, seo_url.SEO_RE)
		self.assertTrue(gercek.endswith(_beklenen(url, baslik or self.baslik, **kw)), gercek)


class TestKartVeDetay(_SeoApiBase):
	def test_get_listings_karti(self):
		from tradehub_core.api.listing import get_listings

		sonuc = get_listings(query=self.sfx)
		kart = next(k for k in sonuc["data"] if k["id"] == self.ilan)
		self.assertOkunur(kart["imageSrc"], self.ana)
		self.assertOkunur(kart["images"][0], self.ana)
		self.assertOkunur(kart["images"][1], self.galeri)
		# ItemList JSON-LD kartın adresini mutlak olarak taşır.
		oge = next(
			e["item"] for e in sonuc["seo"]["json_ld"][0]["itemListElement"] if self.sfx in e["item"]["name"]
		)
		self.assertOkunur(oge["image"], self.ana)

	def test_get_listing_detail_tum_gorseller(self):
		from tradehub_core.api.listing import get_listing_detail

		veri = get_listing_detail(self.ilan)["data"]
		self.assertOkunur(veri["images"][0], self.ana)
		self.assertOkunur(veri["images"][1], self.galeri)
		for kunye, url in zip(veri["imageMeta"], (self.ana, self.galeri), strict=False):
			if kunye.get("url"):
				self.assertOkunur(kunye["url"], url)
		secenekler = [o for eksen in veri["variants"] for o in eksen.get("options") or []]
		self.assertTrue(secenekler)
		self.assertOkunur(secenekler[0]["image"], self.varyant)
		self.assertOkunur(secenekler[0]["images"][0], self.varyant)

	def test_eski_adli_gorsel_aynen_doner(self):
		from tradehub_core.api.listing import get_listings

		eski = f"/files/seo-api-eski-{self.sfx}.jpg"
		baslik = f"Eski Adli {self.sfx}"
		ilan = self._ilan_kur(baslik, eski)
		frappe.db.commit()
		kart = next(k for k in get_listings(query=f"Eski Adli {self.sfx}")["data"] if k["id"] == ilan)
		self.assertEqual(kart["imageSrc"], eski)

	def test_arama_ve_satici_urunleri(self):
		from tradehub_core.api.search import _search_products
		from tradehub_core.api.seller import get_seller_products

		oneri = next(p for p in _search_products(self.sfx, 5) if p["id"] == self.ilan)
		self.assertOkunur(oneri["image"], self.ana)
		if self.satici:
			urun = next(p for p in get_seller_products(self.satici)["products"] if p["id"] == self.ilan)
			self.assertOkunur(urun["image"], self.ana)
			self.assertOkunur(urun["primary_image"], self.ana)


class TestSepetFavoriSiparis(_SeoApiBase):
	def _sepet(self) -> str:
		"""Administrator'ın aktif sepeti; test açtıysa temizlikte silinir (review M-6)."""
		from tradehub_core.api import cart

		vardi = frappe.db.get_value("Cart", {"buyer": "Administrator", "status": "Active"}, "name")
		sepet = cart._get_or_create_cart("Administrator")
		if not vardi:
			self.addCleanup(lambda: frappe.db.delete("Cart", {"name": sepet}))
		return sepet

	def test_get_cart_sku_gorseli(self):
		from tradehub_core.api import cart

		if not self.satici:
			self.skipTest("satıcı yok")
		sepet = self._sepet()
		satir = frappe.get_doc(
			{
				"doctype": "Cart Item",
				"name": frappe.generate_hash(length=10),
				"parent": sepet,
				"parenttype": "Cart",
				"parentfield": "items",
				"listing": self.ilan,
				"quantity": 1,
				"seller": self.satici,
				"snapshot_title": "Saklı ad",
				"snapshot_image": self.ana,
			}
		)
		satir.db_insert()
		self.addCleanup(lambda: frappe.db.delete("Cart Item", {"name": satir.name}))
		skular = [
			s
			for sup in cart.get_cart()["suppliers"]
			for p in sup["products"]
			for s in p["skus"]
			if s["id"] == satir.name
		]
		self.assertEqual(len(skular), 1)
		self.assertOkunur(skular[0]["skuImage"], self.ana)
		# DB aynen kaldı.
		self.assertEqual(frappe.db.get_value("Cart Item", satir.name, "snapshot_image"), self.ana)

	def test_get_my_favorites(self):
		from tradehub_core.api.favorites import get_my_favorites

		fav = frappe.get_doc(
			{
				"doctype": "Buyer Favorite Item",
				"user": "Administrator",
				"listing": self.ilan,
				"snapshot_image": self.ana,
				"snapshot_title": "Saklı ad",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("Buyer Favorite Item", {"name": fav.name}))
		oge = next(i for i in get_my_favorites()["items"] if i["id"] == self.ilan)
		self.assertOkunur(oge["image"], self.ana)
		self.assertEqual(frappe.db.get_value("Buyer Favorite Item", fav.name, "snapshot_image"), self.ana)

	def _siparis_kur(self) -> tuple[str, str]:
		ad = f"SEOAPI-ORD-{self.sfx}"
		frappe.get_doc(
			{
				"doctype": "Order",
				"name": ad,
				"buyer": "Administrator",
				"status": "Tamamlandı",
				"order_date": nowdate(),
				"currency": "TRY",
			}
		).db_insert()
		self.addCleanup(lambda: frappe.db.delete("Order", {"name": ad}))
		self.addCleanup(lambda: frappe.db.delete("Order Item", {"parent": ad}))
		eski = f"/files/seo-api-siparis-{self.sfx}.jpg"
		for idx, (ilan, gorsel) in enumerate(
			((self.ilan, eski), ("YOK-ILAN-SEOAPI", eski), (self.ilan, self.galeri)), 1
		):
			frappe.get_doc(
				{
					"doctype": "Order Item",
					"parent": ad,
					"parenttype": "Order",
					"parentfield": "items",
					"idx": idx,
					"listing": ilan,
					"listing_title": f"Saklı {self.sfx}",
					"quantity": 1,
					"image": gorsel,
				}
			).db_insert()
		return ad, eski

	def _siparis_gorsellerini_dogrula(self, kalemler: list, eski: str):
		gorseller = [k["image"] for k in kalemler]
		# 1) eski ad + ilan var → ilanın güncel ana görseli, okunur
		self.assertOkunur(gorseller[0], self.ana)
		# 2) eski ad + ilan silinmiş → saklı adres aynen
		self.assertEqual(gorseller[1], eski)
		# 3) içerik-kodlu saklı adres → okunur, slug ilandan
		self.assertOkunur(gorseller[2], self.galeri)

	def test_get_my_orders(self):
		from tradehub_core.api.order import get_my_orders

		ad, eski = self._siparis_kur()
		siparis = next(o for o in get_my_orders(search=self.sfx, page_size=50)["orders"] if o["name"] == ad)
		self._siparis_gorsellerini_dogrula(siparis["items"], eski)

	def test_get_order_detail(self):
		from tradehub_core.api.order import get_order_detail

		ad, eski = self._siparis_kur()
		kalemler = get_order_detail(ad)["order"]["items"]
		self.assertNotIn("listing", kalemler[0])
		self._siparis_gorsellerini_dogrula(kalemler, eski)
		self.assertEqual(frappe.db.get_value("Order Item", {"parent": ad, "idx": 1}, "image"), eski)


class TestManifestSemaHarita(_SeoApiBase):
	def test_get_manifest_images_ve_fallback(self):
		from tradehub_core.api import media_manifest

		govde = media_manifest.get_manifest(listing=self.ilan)
		self.assertOkunur(govde["fallback"], self.ana)
		self.assertOkunur(govde["images"][0]["file_url"], self.ana)

	def test_manifest_turevleri_okunur(self):
		from tradehub_core.api import media_manifest

		h = self.ana.rsplit("/", 1)[-1].split(".")[0]
		turev = f"/files/{h[:2]}/{h}__w96.avif"
		ilan = {"name": self.ilan, "seller_profile": "", "title": self.baslik}
		gorseller = [{"file_url": self.ana, "alt_text": "", "primary": True}]
		varliklar = {self.ana: {"": {"name": "SEOAPI-ASSET"}}}
		turevler = {
			"SEOAPI-ASSET": [
				{
					"profile": "w96",
					"format": "avif",
					"width": 64,
					"height": 64,
					"file_url": turev,
					"benefit_gate_passed": 1,
				}
			]
		}
		govde = media_manifest._tek_ilan_govdesi(ilan, gorseller, "product.image", varliklar, turevler, True)
		beklenen_turev = _beklenen(self.ana, self.baslik, turev="__w96", uzanti=".avif")
		self.assertEqual(govde["renditions"][0]["url"], beklenen_turev)
		self.assertOkunur(govde["renditions"][0]["source"], self.ana)
		man = govde["images"][0]["manifest"]
		self.assertEqual(man["src"], beklenen_turev)
		self.assertIn(beklenen_turev, man["sources"][0]["srcset"])
		self.assertEqual(govde["fallback"], beklenen_turev)

	def test_product_json_ld_image(self):
		from tradehub_core.seo import schema_builder

		ld = schema_builder.compose_for_listing(
			frappe.get_doc("Listing", self.ilan).as_dict(), {}, "https://ornek.test"
		)
		urun = next(n for n in ld if n.get("@type") in ("Product", "ProductGroup") and n.get("image"))
		adresler = [g if isinstance(g, str) else g.get("contentUrl") for g in urun["image"]]
		self.assertTrue(adresler)
		self.assertOkunur(adresler[0], self.ana)
		self.assertTrue(adresler[0].startswith("https://ornek.test/files/"))

	def test_sitemap_image_loc(self):
		from tradehub_core.seo import sitemap_generator

		girdiler = sitemap_generator._image_entries_for_listing(
			{"name": self.ilan, "title": self.baslik, "primary_image": self.ana}, "https://ornek.test"
		)
		self.assertTrue(girdiler)
		self.assertEqual(girdiler[0]["loc"], "https://ornek.test" + _beklenen(self.ana, self.baslik))


class TestYazmaYollariSaklamaAdresi(_SeoApiBase):
	"""Review I-1: vitrin okunur adresi geri gönderdiğinde DB içerik-kodlu adresi saklar."""

	def _okunur(self, url: str) -> str:
		return seo_url.seo_image_url(url, self.baslik)

	def _fav_gorseli(self) -> str | None:
		return frappe.db.get_value(
			"Buyer Favorite Item", {"user": "Administrator", "listing": self.ilan}, "snapshot_image"
		)

	def _fav_temizle(self):
		self.addCleanup(
			lambda: frappe.db.delete("Buyer Favorite Item", {"user": "Administrator", "listing": self.ilan})
		)

	def test_to_storage_url(self):
		from tradehub_core.media import seo_cikti

		okunur = self._okunur(self.ana)
		self.assertRegex(okunur, seo_url.SEO_RE)
		self.assertEqual(seo_cikti.to_storage_url(okunur), self.ana)
		# Türev son eki ve istenen uzantı korunur.
		h = self.ana.rsplit("/", 1)[-1].split(".")[0]
		self.assertEqual(
			seo_cikti.to_storage_url(okunur.replace(".jpg", "__w384.webp")), f"/files/{h[:2]}/{h}__w384.webp"
		)
		# Aynı sitenin mutlak adresi yola indirilir; yabancı alan adı ve tanınmayan kod aynen.
		self.assertEqual(seo_cikti.to_storage_url(frappe.utils.get_url() + okunur), self.ana)
		self.assertEqual(
			seo_cikti.to_storage_url("https://baska.example" + okunur), "https://baska.example" + okunur
		)
		self.assertEqual(seo_cikti.to_storage_url("/files/urun-00000000.jpg"), "/files/urun-00000000.jpg")
		self.assertEqual(seo_cikti.to_storage_url(self.ana), self.ana)
		self.assertEqual(seo_cikti.to_storage_url(""), "")

	def test_upsert_favorite_saklama_adresi(self):
		from tradehub_core.api.favorites import upsert_favorite

		self._fav_temizle()
		upsert_favorite(self.ilan, image=self._okunur(self.ana), title="x")
		self.assertEqual(self._fav_gorseli(), self.ana)
		upsert_favorite(self.ilan, image=self._okunur(self.galeri))
		self.assertEqual(self._fav_gorseli(), self.galeri)

	def test_toggle_favorite_saklama_adresi(self):
		from tradehub_core.api.favorites import toggle_favorite_in_list

		self._fav_temizle()
		toggle_favorite_in_list(self.ilan, "default", image=self._okunur(self.ana))
		self.assertEqual(self._fav_gorseli(), self.ana)

	def test_sync_favorites_saklama_adresi(self):
		from tradehub_core.api.favorites import sync_favorites

		self._fav_temizle()
		durum = {
			"lists": [],
			"items": [{"id": self.ilan, "image": self._okunur(self.ana), "listIds": ["default"]}],
		}
		sync_favorites(frappe.as_json(durum))
		self.assertEqual(self._fav_gorseli(), self.ana)
		# Mevcut satırın güncellenme dalı.
		durum["items"][0]["image"] = self._okunur(self.galeri)
		sync_favorites(frappe.as_json(durum))
		self.assertEqual(self._fav_gorseli(), self.galeri)

	def test_get_my_favorites_eski_ad_ilandan(self):
		"""Retro-rename öncesi ad saklıysa çıktı ilanın güncel görselinden okunur adres verir."""
		from tradehub_core.api.favorites import get_my_favorites

		self._fav_temizle()
		fav = frappe.get_doc(
			{
				"doctype": "Buyer Favorite Item",
				"user": "Administrator",
				"listing": self.ilan,
				"snapshot_image": "/files/8697464042954.jpeg",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("Buyer Favorite Item", {"name": fav.name}))
		oge = next(i for i in get_my_favorites()["items"] if i["id"] == self.ilan)
		self.assertOkunur(oge["image"], self.ana)

	def test_sync_favorites_eski_ad_ustune_yazmaz(self):
		"""Tarayıcıda kalmış eski ad, DB'deki içerik-kodlu görselin üzerine yazılmaz."""
		from tradehub_core.api.favorites import sync_favorites

		self._fav_temizle()
		ilk = {"lists": [], "items": [{"id": self.ilan, "image": self.ana, "listIds": ["default"]}]}
		sync_favorites(frappe.as_json(ilk))
		eski = {
			"lists": [],
			"items": [{"id": self.ilan, "image": "/files/8697464042954.jpeg", "listIds": ["default"]}],
		}
		sync_favorites(frappe.as_json(eski))
		self.assertEqual(self._fav_gorseli(), self.ana)

	def test_create_order_gorsel_cozumu(self):
		from tradehub_core.api import cart

		# Sepette sunucu snapshot'ı varsa istemci adresi yok sayılır.
		self.assertEqual(
			cart._siparis_kalemi_gorseli(
				{"listing": self.ilan, "image": self._okunur(self.galeri)}, {(self.ilan, ""): self.varyant}
			),
			self.varyant,
		)
		# Snapshot yoksa istemcinin okunur adresi içerik-kodlu biçime çevrilir.
		self.assertEqual(
			cart._siparis_kalemi_gorseli({"listing": self.ilan, "image": self._okunur(self.ana)}, {}),
			self.ana,
		)
		# `_sepet_gorselleri` aktif sepetin (ilan, varyant) → snapshot haritasını kurar.
		sepet = TestSepetFavoriSiparis._sepet(self)
		satir = frappe.get_doc(
			{
				"doctype": "Cart Item",
				"name": frappe.generate_hash(length=10),
				"parent": sepet,
				"parenttype": "Cart",
				"parentfield": "items",
				"listing": self.ilan,
				"quantity": 1,
				"snapshot_title": "Saklı ad",
				"snapshot_image": self.varyant,
			}
		)
		satir.db_insert()
		self.addCleanup(lambda: frappe.db.delete("Cart Item", {"name": satir.name}))
		self.assertEqual(cart._sepet_gorselleri("Administrator").get((self.ilan, "")), self.varyant)


class TestIzlemeSayfasiVeVaryantSemasi(_SeoApiBase):
	def test_izleme_sayfasi_ilan_gorseli(self):
		from tradehub_core.api.media_public import _vitrin_ilan_kartlari

		kartlar = _vitrin_ilan_kartlari(
			[{"slug": "s", "title": self.baslik, "primary_image": self.ana}, {"slug": "b", "title": "B"}]
		)
		self.assertOkunur(kartlar[0]["image"], self.ana)
		self.assertEqual(kartlar[1]["image"], "")

	def test_has_variant_gorseli_mutlak(self):
		from tradehub_core.seo import schema_builder

		ilan = frappe.get_doc("Listing", self.ilan).as_dict()
		ilan["has_variants"] = 1
		ilan["variants"] = [
			{
				"attribute_type": "Renk",
				"attribute_value": "Kırmızı",
				"variant_sku": "SKU-1",
				"variant_image": self.varyant,
			}
		]
		ld = schema_builder.compose_for_listing(ilan, {}, "https://ornek.test")
		grup = next(n for n in ld if n.get("hasVariant"))
		self.assertEqual(
			grup["hasVariant"][0]["image"], "https://ornek.test" + _beklenen(self.varyant, self.baslik)
		)
