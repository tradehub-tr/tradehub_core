"""Ö-2 — aynı `file_url`'i paylaşan `File` satırları üzerinden kiracı sızıntısı.

Frappe `find_file_by_url` bir URL'e ait TÜM `File` satırlarını gezer ve
**herhangi biri** okunabilirse dosyayı verir; `download_private_file` ise
satırın içeriğini değil URL'in kendisini serve eder. İki gerçek sonucu var:

  V1 — Çağıran, BAŞKA bir kiracının satırı üzerinden URL'e ulaşır.
  V2 — Çağıran KENDİ satırı üzerinden ulaşır ama URL'deki blob başka bir
       kiracıya aittir (canlıda 5 özel URL'de iki ayrı `content_hash` ölçüldü).

`tradehub_core/media/file_isolation.py` her ikisini de kapatır. Bu modül
düzeltmeyi hem kural seviyesinde (`is_tenant_readable`, `blob_matches_row`)
hem uçtan uca (`File.is_downloadable`, `find_file_by_url`) sınar ve meşru
erişimin (sahip, aynı mağazanın başka kullanıcısı, siparişin alıcısı,
Marketplace Admin) korunduğunu doğrular.

Gerçek DB kullanılır (`FrappeTestCase`): `File.has_permission` çekirdek
davranışı (owner / DocShare / bağlı-doc delegasyonu) stub'lanamaz.
`File.insert()` diske yazıyor ve commit ediyor; `test_media_access.py` ile
aynı desen: `ignore_permissions=True` + `addCleanup` ile LIFO temizlik.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_file_multirow_isolation
"""

from __future__ import annotations

import frappe
from frappe.core.doctype.file.file import has_permission as core_file_has_permission
from frappe.core.doctype.file.utils import find_file_by_url
from frappe.tests.utils import FrappeTestCase

from tradehub_core.media import file_isolation
from tradehub_core.utils.tenant import clear_seller_cache_for_user


# Diskte gerçekten duran içerik; her koşuda benzersiz olsun ki içerik-adresli
# URL de benzersiz olsun (önceki koşudan kalan blob/cache karışmasın).
def _blob(suffix: str) -> bytes:
	return f"A kiracisinin gizli kimlik belgesi {suffix}".encode()


class FileMultiRowIsolationTests(FrappeTestCase):
	# -- fixture yardımcıları ------------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		"""`File.insert()` gerçek commit yapıyor; teardown rollback'i geri
		alamaz — silme de kendi commit'ini taşımalı."""
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...] = ()) -> str:
		email = f"o2-{tag}-{self.suffix}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
				"roles": [{"role": r} for r in roles],
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("User", doc.name))
		self.addCleanup(lambda: clear_seller_cache_for_user(doc.name))
		return doc.name

	def _seller(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"O2{tag}{self.suffix}",
				"seller_name": f"O2 {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def _file(self, **kwargs) -> frappe.Document:
		doc = frappe.get_doc({"doctype": "File", **kwargs}).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("File", doc.name))
		return doc

	# -- kurulum -------------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		# Kiracı A: sahip + aynı mağazanın ikinci kullanıcısı (alt kullanıcı)
		# `Verified Seller`: Order.validate satıcının KYB onayını şart koşuyor.
		self.a_owner = self._user("aowner", ("Marketplace Seller", "Verified Seller"))
		self.a_staff = self._user("astaff", ("Marketplace Seller",))
		self.tenant_a = self._seller("A", self.a_owner)
		frappe.db.set_value("User", self.a_staff, "tradehub_tenant", self.tenant_a)
		frappe.db.commit()
		clear_seller_cache_for_user(self.a_staff)

		# Kiracı B: saldırgan
		self.b_owner = self._user("bowner", ("Marketplace Seller",))
		self.tenant_b = self._seller("B", self.b_owner)

		# Mağazası olmayan alıcı + platform yöneticisi
		# `Buyer Viewer`: Order üzerinde read veren Custom DocPerm rolü — alıcının
		# kendi siparişini Frappe katmanında da okuyabilmesi için gerekli.
		self.buyer = self._user("buyer", ("Buyer", "Buyer Viewer"))
		self.admin = self._user("admin", ("Marketplace Admin",))

		# A'nın kimlik doğrulaması (PII referansı)
		self.kyc_a = frappe.get_doc(
			{
				"doctype": "KYC Verification",
				"user": self.a_owner,
				"account_type": "Individual",
				"tax_id": "10000000146",  # geçerli TCKN sağlaması
				"phone": "+905550000000",
				"email_field": self.a_owner,
				"address": "Test adres",
				"billing_address": "Test fatura adresi",
				"identity_document": "/private/files/o2-placeholder.pdf",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("KYC Verification", self.kyc_a.name))

		# A'nın siparişi — alıcısı mağazasız `self.buyer`
		self.order_a = frappe.get_doc(
			{"doctype": "Order", "buyer": self.buyer, "seller": self.tenant_a}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Order", self.order_a.name))

		# A'nın özel kimlik belgesi — diskteki gerçek blob
		frappe.set_user(self.a_owner)
		self.file_a = self._file(
			file_name=f"o2-kimlik-{self.suffix}.txt",
			is_private=1,
			content=_blob(self.suffix),
			attached_to_doctype="KYC Verification",
			attached_to_name=self.kyc_a.name,
		)
		# A'nın sipariş dekontu — alıcı ve mağaza personeli okuyabilmeli
		self.file_order = self._file(
			file_name=f"o2-dekont-{self.suffix}.txt",
			is_private=1,
			content=b"A kiracisinin siparis dekontu",
			attached_to_doctype="Order",
			attached_to_name=self.order_a.name,
		)
		# Public dosya — kural hiç uygulanmamalı
		self.file_public = self._file(
			file_name=f"o2-acik-{self.suffix}.txt",
			is_private=0,
			content=b"herkese acik",
		)

		# V2 kurgusu: B, A'nın URL'inde KENDİ satırına sahip; ama satırın
		# `content_hash`'i diskteki blob'la UYUŞMUYOR — yani B'nin yüklediği
		# içerik o URL'de değil, A'nınki var.
		frappe.set_user(self.b_owner)
		self.file_b_stale = self._file(
			file_name=f"o2-kimlik-{self.suffix}.txt",
			is_private=1,
			file_url=self.file_a.file_url,
		)
		# `File.before_insert` her zaman blob'u okuyup `content_hash`'i yeniden
		# hesaplıyor; ayrışmayı insert sırasında kurmak mümkün değil. Canlıda da
		# ayrışma insert'te değil SONRADAN oluşuyor (blob üzerine yazılıyor,
		# satırlar eski hash'le kalıyor — ölçümde 5 URL). Aynı son durumu
		# doğrudan yazarak kuruyoruz; `update_modified=False` çünkü bu bir
		# kullanıcı düzenlemesi değil, veri bozulmasının simülasyonu.
		frappe.db.set_value("File", self.file_b_stale.name, "content_hash", "0" * 32, update_modified=False)
		frappe.db.commit()
		self.file_b_stale.reload()
		frappe.cache().delete_value(f"tradehub:file_url_ambiguous:{self.file_a.file_url}")
		frappe.set_user("Administrator")

	# -- 1) SIZINTI: çapraz kiracı satırı ------------------------------------

	def test_v1_capraz_kiraci_satiri_okunamaz(self):
		"""B, A'nın kimlik belgesi satırına kiracı kuralıyla ulaşamaz."""
		self.assertFalse(file_isolation.is_tenant_readable(self.file_a, self.b_owner))

	def test_v1_capraz_kiraci_siparis_dekontu_okunamaz(self):
		"""B, A'nın sipariş dekontuna ulaşamaz (satırın kiracısı A)."""
		self.assertFalse(file_isolation.is_tenant_readable(self.file_order, self.b_owner))

	def test_v1_has_permission_kancasi_asla_true_donmez(self):
		"""Kanca ters sıralı zincirde önce çağrılıyor; True dönerse Frappe'nin
		kendi File kontrolü tamamen atlanır. Yalnız False ya da None üretmeli."""
		self.assertIsNone(file_isolation.file_has_permission(self.file_a, "read", self.a_owner))
		self.assertIs(file_isolation.file_has_permission(self.file_a, "read", self.b_owner), False)
		# Yazma yüzeyi kapsam dışı — devredilir.
		self.assertIsNone(file_isolation.file_has_permission(self.file_a, "write", self.b_owner))

	# -- 2) SIZINTI: kendi satırı, başkasının blob'u (V2) ---------------------

	def test_v2_sizinti_duzeltme_oncesi_gercekten_vardi(self):
		"""Ön koşul: Frappe çekirdeği B'nin KENDİ satırına okuma veriyor —
		yani düzeltme olmasa `find_file_by_url` A'nın blob'unu B'ye açardı."""
		self.assertTrue(core_file_has_permission(self.file_b_stale, "read", self.b_owner))
		self.assertEqual(self.file_b_stale.file_url, self.file_a.file_url)

	def test_v2_uyusmayan_icerik_hashli_satir_reddedilir(self):
		"""B'nin satırının içeriği diskteki blob değil → satır geçersiz."""
		self.assertFalse(file_isolation.blob_matches_row(self.file_b_stale))
		self.assertTrue(file_isolation.blob_matches_row(self.file_a))

	def test_v2_eskimis_satir_uctan_uca_indirilemez(self):
		"""B'nin KENDİ satırı bile URL'i açmıyor: satırın içeriği o URL'de değil."""
		frappe.set_user(self.b_owner)
		self.assertFalse(frappe.get_doc("File", self.file_b_stale.name).is_downloadable())

	def test_v1_paylasilan_referans_capraz_kiraciya_kimlik_belgesi_acmaz(self):
		"""Uçtan uca V1: KYC kaydı B ile PAYLAŞILSA bile ek indirilemez.

		DocShare, Frappe'nin `File.has_permission` zincirinde bağlı belge
		üzerinden erişim verir; kimlik belgeleri için bu kasıtlı olarak
		geçersiz kılınır — B ne belgenin öznesi ne de öznenin mağazasında.
		Bu senaryo sitedeki DocPerm verisinden BAĞIMSIZ (deterministik) ve
		gerçek ölçümdeki desenin aynısı: Frappe "evet" der, biz "hayır".
		"""
		frappe.share.add("KYC Verification", self.kyc_a.name, self.b_owner, read=1)
		frappe.db.commit()

		def _unshare() -> None:
			# Temizlik LIFO çalışıyor; bu noktada oturum hâlâ B olabilir ve
			# DocShare silme yetkisi yoktur.
			frappe.set_user("Administrator")
			frappe.share.remove("KYC Verification", self.kyc_a.name, self.b_owner)
			frappe.db.commit()

		self.addCleanup(_unshare)
		# Ön koşul: düzeltme olmasa Frappe bu satıra okuma verirdi.
		self.assertTrue(core_file_has_permission(self.file_a, "read", self.b_owner))

		frappe.set_user(self.b_owner)
		self.assertFalse(frappe.get_doc("File", self.file_a.name).is_downloadable())

	def test_v2_find_file_by_url_b_icin_bos_doner(self):
		"""Uçtan uca: B, A'nın URL'ini indiremez (ne kendi ne A'nın satırıyla)."""
		frappe.set_user(self.b_owner)
		self.assertIsNone(find_file_by_url(self.file_a.file_url))

	def test_v2_find_file_by_url_sahibi_icin_calisir(self):
		"""Aynı URL sahibinde çalışmaya devam ediyor (kural yalnız daraltıyor)."""
		frappe.set_user(self.a_owner)
		found = find_file_by_url(self.file_a.file_url)
		self.assertIsNotNone(found)
		self.assertEqual(found.name, self.file_a.name)

	# -- 3) MEŞRU ERİŞİM KIRILMADI -------------------------------------------

	def test_mesru_i_dosyanin_sahibi_erisebilir(self):
		frappe.set_user(self.a_owner)
		self.assertTrue(frappe.get_doc("File", self.file_a.name).is_downloadable())

	def test_mesru_ii_ayni_magazanin_baska_kullanicisi_erisebilir(self):
		"""`User.tradehub_tenant` ile A'ya bağlı alt kullanıcı, A'nın yüklediği
		sipariş dekontunu okuyabilmeli — ölçüt kullanıcı değil mağaza."""
		self.assertEqual(file_isolation._seller_profile_of(self.a_staff), self.tenant_a)
		frappe.set_user(self.a_staff)
		self.assertTrue(frappe.get_doc("File", self.file_order.name).is_downloadable())

	def test_mesru_iii_siparisin_alicisi_erisebilir(self):
		"""Alıcının mağazası yok; karşı-taraf kuralı kendi dekontunu açık tutar."""
		frappe.set_user(self.buyer)
		self.assertTrue(frappe.get_doc("File", self.file_order.name).is_downloadable())

	def test_mesru_iv_marketplace_admin_her_seyi_gorur(self):
		"""Marketplace Admin A'nın kimlik belgesini indirebilmeli.

		`file_order` üzerinde sınanmıyor: `Order` DocPerm setinde Marketplace
		Admin YOK (System Manager / Platform Admin var) — bu, bu görevden
		bağımsız mevcut bir yetki boşluğu; Frappe zaten reddediyor.
		"""
		frappe.set_user(self.admin)
		self.assertTrue(frappe.get_doc("File", self.file_a.name).is_downloadable())
		self.assertTrue(file_isolation.is_tenant_readable(self.file_order, self.admin))

	def test_mesru_alici_ayni_zamanda_baska_magazanin_saticisi_olabilir(self):
		"""Alıcı aynı zamanda B mağazasının sahibiyse bile KENDİ dekontunu okur —
		mağaza karşılaştırması karşı-taraf kuralının önüne geçmemeli."""
		order = frappe.get_doc({"doctype": "Order", "buyer": self.b_owner, "seller": self.tenant_a}).insert(
			ignore_permissions=True
		)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Order", order.name))

		frappe.set_user(self.a_owner)
		receipt = self._file(
			file_name=f"o2-dekont2-{self.suffix}.txt",
			is_private=1,
			content=b"B nin alici olarak dekontu",
			attached_to_doctype="Order",
			attached_to_name=order.name,
		)
		self.assertTrue(file_isolation.is_tenant_readable(receipt, self.b_owner))

	def test_public_dosyada_kural_uygulanmaz(self):
		self.assertTrue(file_isolation.is_tenant_readable(self.file_public, self.b_owner))
