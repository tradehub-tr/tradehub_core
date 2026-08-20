"""Satıcı Medya Gezgini — izolasyon testleri (`api/seller_media.browse_my_media`).

Bu dosyanın ASIL konusu klasör ağacı değil, İZOLASYON. Depoda daha önce
`Payment Transaction` üzerinde her satıcının tüm platformun kayıtlarını
okuyabildiği gerçek bir açık bulundu; oradaki hata "mağaza istemciden geldi ve
sunucuda doğrulanmadı" idi. Bu uçta mağaza HİÇ parametre değil: her çağrıda
oturumdan (`_store()`) türetiliyor. Testler bunun gerçekten böyle olduğunu iki
satıcı + iki mağaza kurarak kanıtlıyor.

Kurulum her satıcı için aynı: kendi kullanıcısı, kendi kategorisi, kendi ürünü,
o üründe duran bir public dosya, kendi yüklediği bir özel dosya ve kendi
mağazasına yazılmış bir sohbet eki.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_seller_media_browse
"""

from __future__ import annotations

from unittest import mock

import frappe

from tradehub_core.api import media_admin, seller_media
from tradehub_core.media import browse, ownership
from tradehub_core.tests.test_media_browse import MediaBrowseTestBase


class SellerBrowseTestBase(MediaBrowseTestBase):
	"""İki bağımsız satıcı kuran ortak fixture."""

	def _make_store_user(self, store: str, tag: str) -> str:
		suffix = frappe.generate_hash(length=8)
		email = f"satici-gezgin-{tag}-{suffix}@test.local"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Satici Gezgin",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", user.name))
		frappe.db.set_value("Admin Seller Profile", store, "user", email, update_modified=False)
		frappe.db.commit()
		ownership.clear_cache(store)
		self.addCleanup(lambda: ownership.clear_cache(store))
		self.addCleanup(lambda: frappe.cache().delete_value(f"tradehub:seller_for_user:{email}"))
		return email

	def _make_chat_attachment(self, store: str, tag: str) -> "frappe._dict":
		doc = frappe.get_doc(
			{
				"doctype": "Chat Attachment",
				"conversation_id": f"satici-gezgin-{tag}-{frappe.generate_hash(length=6)}",
				"seller": store,
				"sender": "Administrator",
				"file_name": f"satici-gezgin-{tag}-{frappe.generate_hash(length=6)}.pdf",
				"file_size": 4096,
				"mime": "application/pdf",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Chat Attachment", doc.name))
		return doc

	def _kur_satici(self, tag: str) -> "frappe._dict":
		"""Tek satıcının tüm medya izleri — public, private ve sohbet."""
		store = self._make_seller(tag)
		email = self._make_store_user(store, tag)
		category = self._make_category(tag)

		public_file = self._make_public_file(tag)
		frappe.db.set_value("File", public_file.name, "owner", email, update_modified=False)
		private_file = self._make_private_file(tag)
		frappe.db.set_value("File", private_file.name, "owner", email, update_modified=False)
		frappe.db.commit()

		listing = self._make_listing_in_category(store, public_file.file_url, category, tag)
		chat = self._make_chat_attachment(store, tag)

		browse.clear_seller_cache(store)
		self.addCleanup(lambda: browse.clear_seller_cache(store))
		return frappe._dict(
			store=store,
			email=email,
			category=category,
			listing=listing,
			public_url=public_file.file_url,
			private_url=private_file.file_url,
			chat_name=chat.file_name,
		)

	def setUp(self):
		super().setUp()
		self.a = self._kur_satici("izo-a")
		self.b = self._kur_satici("izo-b")

	def _as_seller(self, satici: "frappe._dict") -> None:
		frappe.set_user(satici.email)


class SellerBrowseIsolationTests(SellerBrowseTestBase):
	def test_kok_yalniz_kendi_dosyalarini_sayar(self):
		"""1. Satıcı A'nın kökü B'nin hiçbir dosyasını saymıyor.

		Sayılar TAM eşitlikle kontrol ediliyor, `>=` ile değil: `>=` ile bir
		sızıntı testi sessizce yeşil kalır.
		"""
		self._as_seller(self.a)
		kok = {f["id"]: f["count"] for f in seller_media.browse_my_media()["folders"]}
		self.assertEqual(kok["public"], 1)
		self.assertEqual(kok["private"], 1)
		self.assertEqual(kok["chat"], 1)

	def test_kok_kendi_dosyalarini_listeler_ve_baskasininkini_listelemez(self):
		"""1. (devam) Sayı değil, İÇERİK de yalnız kendisine ait."""
		self._as_seller(self.a)

		kategoriler = seller_media.browse_my_media(scope="public")["folders"]
		kategori_ids = {f["id"] for f in kategoriler}
		self.assertEqual(kategori_ids, {self.a.category})
		self.assertNotIn(self.b.category, kategori_ids)

		urunler = seller_media.browse_my_media(scope="public", category=self.a.category)["folders"]
		urun_ids = {f["id"] for f in urunler}
		self.assertEqual(urun_ids, {self.a.listing})
		self.assertNotIn(self.b.listing, urun_ids)

		dosyalar = seller_media.browse_my_media(
			scope="public", category=self.a.category, listing=self.a.listing
		)
		urls = {r["file_url"] for r in dosyalar["items"]}
		self.assertEqual(urls, {self.a.public_url})
		self.assertNotIn(self.b.public_url, urls)

		ozel = seller_media.browse_my_media(scope="private")
		ozel_urls = {r["file_url"] for r in ozel["items"]}
		self.assertEqual(ozel_urls, {self.a.private_url})
		self.assertNotIn(self.b.private_url, ozel_urls)
		self.assertEqual(ozel["total"], 1)

		sohbet = seller_media.browse_my_media(scope="chat")
		sohbet_adlari = {r["file_name"] for r in sohbet["items"]}
		self.assertEqual(sohbet_adlari, {self.a.chat_name})
		self.assertNotIn(self.b.chat_name, sohbet_adlari)

	def test_baskasinin_ilan_kimligi_bos_doner(self):
		"""2. A, `listing` parametresine B'nin ilanını yazarsa boş dönüyor."""
		self._as_seller(self.a)

		# Kendi kategorisiyle birlikte denenen yabancı ilan
		out = seller_media.browse_my_media(
			scope="public", category=self.a.category, listing=self.b.listing
		)
		self.assertEqual(out, {"items": [], "total": 0})

		# Yabancı kategori + yabancı ilan
		out = seller_media.browse_my_media(
			scope="public", category=self.b.category, listing=self.b.listing
		)
		self.assertEqual(out, {"items": [], "total": 0})

	def test_baskasinin_kategorisi_bos_doner(self):
		"""3. A, B'de olan ama A'da olmayan bir kategori yazarsa boş dönüyor."""
		self._as_seller(self.a)
		out = seller_media.browse_my_media(scope="public", category=self.b.category)
		self.assertEqual(out, {"folders": []})

	def test_gecersiz_kapsam_reddedilir(self):
		self._as_seller(self.a)
		with self.assertRaises(frappe.ValidationError):
			seller_media.browse_my_media(scope="platform")

	def test_arama_kendi_kapsaminin_disina_cikmaz(self):
		"""Arama süzgeci kapsamı GENİŞLETEMEZ — B'nin dosya adı aransa bile."""
		self._as_seller(self.a)
		ad = self.b.public_url.rsplit("/", 1)[-1]
		out = seller_media.browse_my_media(
			scope="public", category=self.a.category, listing=self.a.listing, search=ad
		)
		self.assertEqual(out["total"], 0)

		ozel_ad = self.b.private_url.rsplit("/", 1)[-1]
		out = seller_media.browse_my_media(scope="private", search=ozel_ad)
		self.assertEqual(out["total"], 0)


class SellerBrowseAuthTests(SellerBrowseTestBase):
	def test_misafir_reddedilir(self):
		"""4. Guest çağırırsa `PermissionError`."""
		frappe.set_user("Guest")
		with mock.patch.object(seller_media.audit, "log_media_event"):
			with self.assertRaises(frappe.PermissionError):
				seller_media.browse_my_media()
			with self.assertRaises(frappe.PermissionError):
				seller_media.browse_my_media(scope="private")

	def test_magazasi_olmayan_kullanici_reddedilir(self):
		"""5. Mağazası olmayan giriş yapmış kullanıcı REDDEDİLİR (boş dönmez).

		Seçim `ownership.current_store()` ile aynı: sessiz boş liste "hiç dosyam
		yok" diye okunur ve gerçek bir yetki sorununu gizler.
		"""
		suffix = frappe.generate_hash(length=8)
		email = f"satici-gezgin-magazasiz-{suffix}@test.local"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Magazasiz",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", user.name))
		self.addCleanup(lambda: frappe.cache().delete_value(f"tradehub:seller_for_user:{email}"))

		frappe.set_user(email)
		with mock.patch.object(seller_media.audit, "log_media_event"):
			with self.assertRaises(frappe.PermissionError):
				seller_media.browse_my_media()

	def test_baska_saticinin_oturumunda_baska_agac_doner(self):
		"""Aynı çağrı, iki oturum, kesişmeyen iki sonuç — mağaza gerçekten
		oturumdan geliyor, parametreden değil."""
		self._as_seller(self.a)
		a_kategori = {f["id"] for f in seller_media.browse_my_media(scope="public")["folders"]}
		self._as_seller(self.b)
		b_kategori = {f["id"] for f in seller_media.browse_my_media(scope="public")["folders"]}

		self.assertEqual(a_kategori, {self.a.category})
		self.assertEqual(b_kategori, {self.b.category})
		self.assertEqual(a_kategori & b_kategori, set())


class AdminBrowseUnchangedTests(SellerBrowseTestBase):
	"""6. Yönetici ucunun davranışı DEĞİŞMEDİ — satıcı ucu ona dokunmuyor."""

	def test_yonetici_her_iki_magazayi_da_gorur(self):
		magazalar = browse.public_stores(refresh=True)
		ids = {f["id"] for f in magazalar["folders"]}
		self.assertIn(self.a.store, ids)
		self.assertIn(self.b.store, ids)

		out = media_admin.browse_media(scope="public")
		endpoint_ids = {f["id"] for f in out["folders"]}
		self.assertIn(self.a.store, endpoint_ids)
		self.assertIn(self.b.store, endpoint_ids)

	def test_yonetici_kokte_hala_uc_klasor_verir(self):
		out = media_admin.browse_media()
		ids = {f["id"] for f in out["folders"]}
		self.assertEqual(ids, {"public", "private", "chat"})

	def test_yonetici_public_agacinda_magaza_kategori_dosya_sirasi_korunur(self):
		browse.public_stores(refresh=True)
		kategoriler = media_admin.browse_media(scope="public", store=self.b.store)
		self.assertIn(self.b.category, {f["id"] for f in kategoriler["folders"]})

		dosyalar = media_admin.browse_media(
			scope="public", store=self.b.store, category=self.b.category
		)
		self.assertIn(self.b.public_url, {r["file_url"] for r in dosyalar["items"]})


if __name__ == "__main__":
	import unittest

	unittest.main()
