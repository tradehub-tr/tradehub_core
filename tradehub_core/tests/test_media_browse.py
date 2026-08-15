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


class PrivateStoreSplitTests(MediaBrowseTestBase):
	"""KYB/KYC klasörleri mağazaya göre alt klasörlenir — 489 belgeyi tek düz
	listede vermek kullanılamazdı. Bağ: dosya → doğrulama belgesi (`attached_
	to_name`) → belgenin kullanıcısı → kullanıcının mağazası."""

	def _make_store_user(self, seller: str, tag: str) -> str:
		suffix = frappe.generate_hash(length=8)
		email = f"gezgin-{tag}-{suffix}@test.local"
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
		return email

	def test_kyb_dosyalari_magazaya_gore_alt_klasorlenir(self):
		seller = self._make_seller("kyb-split")
		email = self._make_store_user(seller, "kyb-split")

		kyb = frappe.get_doc(
			{
				"doctype": "KYB Verification",
				"user": email,
				"company_title": f"Gezgin KYB Test {frappe.generate_hash(length=6)}",
			}
		)
		kyb.flags.ignore_mandatory = True
		kyb.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("KYB Verification", kyb.name))

		file_doc = self._make_private_file("kyb-split")
		frappe.db.set_value(
			"File",
			file_doc.name,
			{"attached_to_doctype": "KYB Verification", "attached_to_name": kyb.name},
			update_modified=False,
		)
		frappe.db.commit()

		out = browse.private_group_stores("KYB Verification")
		self.assertIn(seller, {f["id"] for f in out["folders"]})

		files = browse.files(scope="private", group="KYB Verification", sub=seller)
		urls = {r["file_url"] for r in files["items"]}
		self.assertIn(file_doc.file_url, urls)

	def test_endpoint_kyb_grubunda_once_magaza_klasorleri_doner(self):
		out = media_admin.browse_media(scope="private", group="KYB Verification")
		self.assertIn("folders", out)
		self.assertNotIn("items", out)

	def test_magaza_altinda_belge_alani_klasorleri(self):
		"""Mağaza klasörünün içi de belge türüne ayrılır: vergi levhası, imza
		sirküleri... Alan bilgisi olmayan ekler 'serbest ekler' klasöründe."""
		seller = self._make_seller("alan-split")
		email = self._make_store_user(seller, "alan-split")
		kyb = frappe.get_doc(
			{
				"doctype": "KYB Verification",
				"user": email,
				"company_title": f"Gezgin Alan Test {frappe.generate_hash(length=6)}",
			}
		)
		kyb.flags.ignore_mandatory = True
		kyb.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("KYB Verification", kyb.name))

		alanli = self._make_private_file("alanli")
		frappe.db.set_value(
			"File",
			alanli.name,
			{
				"attached_to_doctype": "KYB Verification",
				"attached_to_name": kyb.name,
				"attached_to_field": "vergi_levhasi",
			},
			update_modified=False,
		)
		serbest = self._make_private_file("serbest")
		frappe.db.set_value(
			"File",
			serbest.name,
			{"attached_to_doctype": "KYB Verification", "attached_to_name": kyb.name},
			update_modified=False,
		)
		frappe.db.commit()

		out = media_admin.browse_media(scope="private", group="KYB Verification", sub=seller)
		ids = {f["id"] for f in out["folders"]}
		self.assertIn("vergi_levhasi", ids)
		self.assertIn(browse.OTHER_GROUP, ids)
		self.assertNotIn("items", out)

		vergili = browse.files(
			scope="private", group="KYB Verification", sub=seller, doc_field="vergi_levhasi"
		)
		self.assertEqual({r["file_url"] for r in vergili["items"]}, {alanli.file_url})

		serbestler = browse.files(
			scope="private", group="KYB Verification", sub=seller, doc_field=browse.OTHER_GROUP
		)
		self.assertEqual({r["file_url"] for r in serbestler["items"]}, {serbest.file_url})


class ChatAttachmentBrowseTests(MediaBrowseTestBase):
	"""Sohbet ekleri: dosyalar teamslike'ta (dış chat servisi) durur, bizde
	yalnız KÜNYE tutulur (Chat Attachment) — gezgin bu künyeden 'Sohbet
	ekleri → mağaza → dosyalar' ağacını kurar. Dosya kopyalanmaz."""

	def _make_chat_attachment(self, seller: str | None, tag: str) -> frappe._dict:
		doc = frappe.get_doc(
			{
				"doctype": "Chat Attachment",
				"conversation_id": f"conv-{tag}-{frappe.generate_hash(length=6)}",
				"seller": seller,
				"sender": "Administrator",
				"file_name": f"gezgin-{tag}-{frappe.generate_hash(length=6)}.pdf",
				"file_size": 1234,
				"mime": "application/pdf",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Chat Attachment", doc.name))
		return doc

	def test_kokte_sohbet_ekleri_klasoru_var(self):
		self._make_chat_attachment(None, "kok")
		out = browse.root()
		ids = {f["id"]: f for f in out["folders"]}
		self.assertIn("chat", ids)
		self.assertGreaterEqual(ids["chat"]["count"], 1)

	def test_sohbet_ekleri_magazaya_gore_klasorlenir(self):
		seller = self._make_seller("chat")
		att = self._make_chat_attachment(seller, "magaza")
		sahipsiz = self._make_chat_attachment(None, "sahipsiz")

		out = browse.chat_stores()
		ids = {f["id"] for f in out["folders"]}
		self.assertIn(seller, ids)
		self.assertIn(browse.OTHER_GROUP, ids)

		files = browse.files(scope="chat", store=seller)
		names = {r["file_name"] for r in files["items"]}
		self.assertIn(att.file_name, names)
		self.assertNotIn(sahipsiz.file_name, names)
		self.assertTrue(all(r.get("chat") for r in files["items"]))

	def test_endpoint_chat_kapsamini_yonlendirir(self):
		out = media_admin.browse_media(scope="chat")
		self.assertIn("folders", out)


class ChatAttachmentLogTests(MediaBrowseTestBase):
	def test_kayit_yardimcisi_kunye_yazar(self):
		"""`chat._record_attachment` teamslike'a iletilen eki künyeler —
		chat akışını asla kırmamalı, o yüzden ayrı ve savunmacı."""
		from tradehub_core.api import chat

		seller = self._make_seller("chat-log")
		conv = f"conv-log-{frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{"doctype": "Chat Thread Map", "conversation_id": conv, "seller": seller}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(
			lambda: frappe.db.delete("Chat Thread Map", {"conversation_id": conv}) or frappe.db.commit()
		)

		chat._record_attachment(conv, "Administrator", "dekont.pdf", 2048, "application/pdf", "", {})
		frappe.db.commit()
		row = frappe.db.get_value(
			"Chat Attachment",
			{"conversation_id": conv},
			["file_name", "seller"],
			as_dict=True,
		)
		self.addCleanup(
			lambda: frappe.db.delete("Chat Attachment", {"conversation_id": conv}) or frappe.db.commit()
		)
		self.assertEqual(row.file_name, "dekont.pdf")
		self.assertEqual(row.seller, seller)


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
