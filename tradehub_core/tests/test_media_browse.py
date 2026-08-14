"""Medya Gezgini — sanal klasör ağacı testleri (TUR-126 devamı, panel isteği).

Klasörler SANALDIR: disk hash-shard'lı kalır (TUR-130), ağaç metadata'dan
türetilir. Public tarafı mağaza → ürün kategorisi (Product Category), private
tarafı bağlı belge türü gruplarıyla klasörlenir:

    public/                        private/
      <mağaza>/                      KYB Verification/
        <kategori>/                  KYC Verification/
        __none__  (ürüne bağsız)     __other__ (bağsız/diğer)
      __platform__ (sahipsiz)

Sahiplik `media/ownership.py` kuralıyla aynı: yükleyen VEYA kullanan mağaza.
Kategori, dosyayı kullanan ürünün `product_category` alanından gelir.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_browse
"""

from __future__ import annotations

import frappe

from tradehub_core.api import media_admin
from tradehub_core.media import browse
from tradehub_core.tests.test_media_access_level import MediaAccessLevelTestBase


class MediaBrowseTestBase(MediaAccessLevelTestBase):
	def _make_category(self, tag: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Product Category",
				"category_name": f"Gezgin Kategori {tag} {frappe.generate_hash(length=6)}",
				"external_id": f"gezgin-{tag}-{frappe.generate_hash(length=8)}",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Product Category", doc.name))
		return doc.name

	def _make_listing_in_category(self, seller: str, image_url: str, category: str, tag: str) -> str:
		name = self._make_listing(seller, image_url, tag)
		# Fixture yardımcısı product_category almıyor; şema doğrulamasını
		# tetiklemeden tek alanı yaz.
		frappe.db.set_value("Listing", name, "product_category", category, update_modified=False)
		frappe.db.commit()
		return name


class BrowseTreeTests(MediaBrowseTestBase):
	def test_kok_public_ve_private_klasorlerini_sayilariyla_verir(self):
		self._make_public_file("kok")
		self._make_private_file("kok")

		out = browse.root()
		ids = {f["id"]: f for f in out["folders"]}
		self.assertIn("public", ids)
		self.assertIn("private", ids)
		self.assertGreaterEqual(ids["public"]["count"], 1)
		self.assertGreaterEqual(ids["private"]["count"], 1)

	def test_kullanilan_dosya_magaza_ve_kategori_klasorune_duser(self):
		file_doc = self._make_public_file("kategori")
		seller = self._make_seller("kategori")
		category = self._make_category("kategori")
		self._make_listing_in_category(seller, file_doc.file_url, category, "kategori")

		stores = browse.public_stores(refresh=True)
		store_ids = {f["id"] for f in stores["folders"]}
		self.assertIn(seller, store_ids)

		cats = browse.public_categories(seller)
		cat_ids = {f["id"] for f in cats["folders"]}
		self.assertIn(category, cat_ids)

		files = browse.files(scope="public", store=seller, category=category)
		urls = {r["file_url"] for r in files["items"]}
		self.assertIn(file_doc.file_url, urls)

	def test_hic_kullanilmayan_sahipsiz_dosya_platform_klasorune_duser(self):
		file_doc = self._make_public_file("platform")
		# Test Administrator olarak koşuyor ve seed veride Administrator bir
		# mağazaya bağlı olabilir — sahipsizliği garantiye almak için yükleyeni
		# hiçbir mağazası olmayan bir kullanıcıya çevir.
		frappe.db.set_value(
			"File", file_doc.name, "owner", "gezgin-sahipsiz@test.local", update_modified=False
		)
		frappe.db.commit()

		browse.public_stores(refresh=True)
		files = browse.files(
			scope="public",
			store=browse.PLATFORM_STORE,
			search=file_doc.file_url.rsplit("/", 1)[-1],
		)
		urls = {r["file_url"] for r in files["items"]}
		self.assertIn(file_doc.file_url, urls)

	def test_kategorisiz_urunun_gorseli_none_klasorune_duser(self):
		"""Kullanılan-ama-kategorisiz ile hiç-kullanılmayan AYRI şeyler: seed
		veride koca mağazalar kategorisiz ürünlerle dolu — hepsini 'ürüne bağlı
		değil' diye etiketlemek yanlış rapor olur."""
		file_doc = self._make_public_file("kategorisiz")
		seller = self._make_seller("kategorisiz")
		self._make_listing(seller, file_doc.file_url, "kategorisiz")  # kategori YOK

		browse.public_stores(refresh=True)
		cats = browse.public_categories(seller)
		by_id = {f["id"]: f for f in cats["folders"]}
		self.assertIn(browse.NO_CATEGORY, by_id)
		self.assertEqual(by_id[browse.NO_CATEGORY]["count"], 1)

		files = browse.files(scope="public", store=seller, category=browse.NO_CATEGORY)
		self.assertIn(file_doc.file_url, {r["file_url"] for r in files["items"]})

	def test_kullanilmayan_yukleme_unused_klasorune_duser(self):
		"""Mağaza kullanıcısının yüklediği ama hiçbir üründe durmayan dosya
		'Ürüne bağlı değil' (UNUSED) klasörüne düşer — kategorisiz ürün
		görseliyle karışmaz."""
		from tradehub_core.media import ownership

		seller = self._make_seller("unused")
		suffix = frappe.generate_hash(length=8)
		email = f"gezgin-unused-{suffix}@test.local"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Gezgin",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", user.name))
		frappe.db.set_value("Admin Seller Profile", seller, "user", email, update_modified=False)
		frappe.db.commit()
		ownership.clear_cache(seller)
		self.addCleanup(lambda: ownership.clear_cache(seller))

		file_doc = self._make_public_file("unused")
		frappe.db.set_value("File", file_doc.name, "owner", email, update_modified=False)
		frappe.db.commit()

		browse.public_stores(refresh=True)
		cats = browse.public_categories(seller)
		self.assertIn(browse.UNUSED, {f["id"] for f in cats["folders"]})

		files = browse.files(scope="public", store=seller, category=browse.UNUSED)
		self.assertIn(file_doc.file_url, {r["file_url"] for r in files["items"]})

	def test_private_dosyalar_belge_turune_gore_gruplanir(self):
		self._make_private_file("grup")  # bağsız → __other__

		groups = browse.private_groups()
		ids = {f["id"] for f in groups["folders"]}
		self.assertIn(browse.OTHER_GROUP, ids)

		files = browse.files(scope="private", group=browse.OTHER_GROUP)
		self.assertGreaterEqual(files["total"], 1)


class BrowseEndpointTests(MediaBrowseTestBase):
	def test_endpoint_kok_ve_yetki(self):
		out = media_admin.browse_media()
		self.assertIn("folders", out)

		suffix = frappe.generate_hash(length=8)
		email = f"gezgin-yetkisiz-{suffix}@test.local"
		user = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Yetkisiz",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", user.name))

		frappe.set_user(email)
		prev = frappe.flags.in_test
		frappe.flags.in_test = False
		try:
			with self.assertRaises(frappe.PermissionError):
				media_admin.browse_media()
		finally:
			frappe.flags.in_test = prev
			frappe.set_user("Administrator")


if __name__ == "__main__":
	import unittest

	unittest.main()
