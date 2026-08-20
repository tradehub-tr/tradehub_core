"""W9 (rapor 87 W7-4 devri) — rol yükseltme / yetki tırmanma testleri.

NEDEN BU DOSYA VAR
==================
Rapor 87 §"Kalan açık — rol yükseltme (bench-bağımlı, YAZILMADI)" şunu bıraktı:
aynı-kiracı düşük-rol → yüksek-rol yükseltme senaryoları gerçek site/fixture
(FrappeTestCase) gerektirir, frappe-siz CI kapısına GİRMEZ. Rapor 87'nin somut
önerisi buydu: "Seller rolüyle Media Asset moderasyon alanını yazmayı dene →
permlevel korumasının API/model katmanında da tuttuğunu ölç (B-03'ün Payment
Transaction karşılığı da aynı dosyaya)."

Bu modül o boşluğu kapatır. Statik JSON kontrolü (`test_payment_iban_permlevel`,
`test_faz13_guest_surface`) permlevel'in ŞEMADA olduğunu pinler; buradaki testler
Frappe'nin izin MOTORUNUN gerçekten uyguladığını — düşük yetkili kullanıcı
kaydeder ama tırmanma yazımı DÜŞER — canlı DB üzerinde ölçer.

ÖLÇÜLEN YÜKSELTME MEKANİZMASI (frappe/model/document.py:783)
------------------------------------------------------------
`validate_higher_perm_levels` permlevel>0 alanına yazma yetkisi olmayan
kullanıcının o alanlardaki değişikliğini SESSİZCE eski değere geri alır
(exception ATMAZ). Administrator ve `ignore_permissions` bundan muaftır — bu
yüzden fixture'lar admin/`ignore_permissions` ile kurulur ama tırmanma denemesi
DÜŞÜK yetkili kullanıcıya `set_user` edilip DÜZ `save()` (ignore_permissions
YOK) ile yapılır. Bu, üretimdeki API yollarının davranışıdır.

VACUITY
-------
Her tırmanma testinin yanında bir KONTROL yolu vardır: aynı yazımı yetkili
kullanıcı (Administrator / platform rolü / ignore_permissions) yapınca DEĞİŞİM
GERÇEKLEŞİR. Kontrol yeşilse ve tırmanma "değişmedi" diyorsa, "değişmedi"
gerçekten korumadan gelir — alanın zaten yazılamaz/yok olmasından değil. Kapı
gevşetilse (permlevel düşürülse) tırmanma kontrol yolu gibi BAŞARIR ve test
kırmızıya döner.

KOŞUM
-----
    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_role_escalation
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.utils.tenant import clear_seller_cache_for_user

#: Media Asset üzerinde satıcının OKUduğu ama YAZAMADIĞI moderasyon/kimlik
#: alanları (permlevel-1). Kaynak: media_asset.json (B-2 düzeltmesi).
ASSET_PL1_FIELDS: frozenset = frozenset(
	{"state", "owner_seller", "source_file", "legal_hold", "content_sha256",
	 "active_version", "rejection_code", "rejection_note"}
)


class _EscalationBase(FrappeTestCase):
	"""Ortak fixture: iki satıcı (kiracı), mağazaları, bir alıcı, bir admin.

	`File.insert()` / `Admin Seller Profile.insert()` gerçek commit yapar;
	FrappeTestCase teardown rollback'i bunu geri alamaz — her fixture kendi
	silme+commit'ini `addCleanup` ile taşır (repo deseni: test_file_multirow).
	"""

	def _drop(self, doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _user(self, tag: str, roles: tuple[str, ...]) -> str:
		email = f"w9esc-{tag}-{self.suffix}@test.local"
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

	def _store(self, tag: str, user: str) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_code": f"W9E{tag}{self.suffix}",
				"seller_name": f"W9E {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def setUp(self) -> None:
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		# Kiracı A: tırmanmayı deneyen satıcı ve mağazası.
		self.seller = self._user("seller", ("Marketplace Seller", "Seller"))
		self.store = self._store("A", self.seller)
		clear_seller_cache_for_user(self.seller)

		# Kiracı B: devir/çapraz-yazma hedefi.
		self.other_seller = self._user("other", ("Marketplace Seller", "Seller"))
		self.other_store = self._store("B", self.other_seller)
		clear_seller_cache_for_user(self.other_seller)

		self.buyer = self._user("buyer", ("Buyer",))
		self.admin = self._user("admin", ("Marketplace Admin",))


class MediaAssetPermlevelEscalationTests(_EscalationBase):
	"""Satıcı, KENDİ Media Asset'inde permlevel-1 moderasyon alanını yazamaz."""

	def _asset(self, store: str, **over) -> str:
		base = {
			"doctype": "Media Asset",
			"slot_key": "product.image",
			"media_type": "image",
			"state": "draft",
			"owner_seller": store,
			"legal_hold": 1,
			"content_sha256": (self.suffix + "0" * 64)[:64],
		}
		base.update(over)
		doc = frappe.get_doc(base).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Media Asset", doc.name))
		return doc.name

	def test_satici_state_i_ready_yapip_moderasyonu_atlayamaz(self) -> None:
		name = self._asset(self.store)
		frappe.set_user(self.seller)
		doc = frappe.get_doc("Media Asset", name)
		doc.state = "ready"  # yayına al = moderasyonu atla
		doc.save()  # ignore_permissions YOK → gerçek izin yolu
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Media Asset", name, "state"), "draft",
			"Satıcı state'i 'ready' yaptı — permlevel-1 koruması API/model katmanında delindi.",
		)

	def test_satici_legal_hold_kaldiramaz(self) -> None:
		name = self._asset(self.store)
		frappe.set_user(self.seller)
		doc = frappe.get_doc("Media Asset", name)
		doc.legal_hold = 0
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(
			int(frappe.db.get_value("Media Asset", name, "legal_hold")), 1,
			"Satıcı legal_hold'u kaldırdı — yasal saklama satıcı eliyle sökülebiliyor.",
		)

	def test_satici_rejection_kodunu_silemez(self) -> None:
		name = self._asset(self.store, state="rejected", rejection_code="B5")
		frappe.set_user(self.seller)
		doc = frappe.get_doc("Media Asset", name)
		doc.rejection_code = ""
		# rejection boşsa controller (state=rejected iken) throw eder; bu da
		# yazımın geçmediğinin ikinci kanıtı. Her iki sonuç da tırmanmayı reddeder.
		try:
			doc.save()
		except frappe.ValidationError:
			pass
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Media Asset", name, "rejection_code"), "B5",
			"Satıcı red kodunu sildi — reddin gerekçesi satıcı eliyle kaybediliyor.",
		)

	def test_satici_varligi_baska_magazaya_devredemez(self) -> None:
		name = self._asset(self.store)
		frappe.set_user(self.seller)
		doc = frappe.get_doc("Media Asset", name)
		doc.owner_seller = self.other_store
		# owner_seller hem permlevel-1 hem sahiplik kancasının dayanağı; devir
		# ya sessizce geri alınır ya PermissionError olur — ikisi de kabul.
		try:
			doc.save()
		except frappe.PermissionError:
			pass
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Media Asset", name, "owner_seller"), self.store,
			"Varlık başka mağazaya devredildi — sahiplik satıcı eliyle değiştirilebiliyor.",
		)

	def test_VACUITY_yetkili_ayni_yazimi_yapinca_degisir(self) -> None:
		# Kontrol: aynı state yazımını Administrator yapınca GERÇEKLEŞİR. Bu yeşilse
		# yukarıdaki 'değişmedi' iddiaları korumadan gelir, alanın yazılamazlığından
		# değil. Kapı (permlevel) gevşetilse satıcı yolu da bunun gibi başarırdı.
		name = self._asset(self.store)
		doc = frappe.get_doc("Media Asset", name)
		doc.state = "ready"
		doc.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("Media Asset", name, "state"), "ready",
			"Vacuity: yetkili yol da yazamıyorsa test kör — koruma değil, yazılamaz alan ölçülüyor.",
		)


class MediaFolderEscalationTests(_EscalationBase):
	"""Media Folder — satıcı için tırmanma YÜZEYİ YOKTUR (ölçüldü).

	İKİ AYRI ÖLÇÜM tırmanmayı kapatır ve buradaki testler ikisini de pinler:
	  (1) ALAN düzeyi: media_folder.json'daki hiçbir alan permlevel-1 değil →
	      'moderasyon alanını yaz' ekseni Media Folder için TANIMSIZ.
	  (2) SATIR/DocType düzeyi: DocPerm matrisinde `create` YALNIZ System
	      Manager'da; Marketplace Admin salt-OKUR; Marketplace Seller matriste
	      HİÇ YOK. Yani satıcı KENDİ mağazası için bile klasör oluşturamaz —
	      klasörler yönetim tarafından açılır. Tırmanma için yazılabilir bir
	      alan da, oluşturulabilir bir kayıt da yoktur.

	Not: satıcının başka kiracının klasörünü GÖRMESİ ayrı bir eksendir (browse
	API'si `ignore_permissions` + query filtresiyle çalışır) ve kiracı izolasyon
	süitinde (test_media_folder / permissions.py) kapatılır — bu dosyanın konusu
	rol/yetki TIRMANMASI, kiracı sızıntısı değil.
	"""

	def test_media_folder_pl1_alani_yok_olcum(self) -> None:
		import json
		from pathlib import Path

		root = Path(frappe.get_app_path("tradehub_core")) / "tradehub_core" / "doctype" / "media_folder"
		schema = json.loads((root / "media_folder.json").read_text(encoding="utf-8"))
		pls = {int(f.get("permlevel", 0)) for f in schema.get("fields", [])}
		self.assertEqual(
			pls, {0},
			"Media Folder'a permlevel-1 alan eklenmiş — alan-düzeyi tırmanma ekseni açıldı, "
			"o eksen için ayrıca test yazılmalı.",
		)

	def test_satici_media_folder_create_perm_i_yok_olcum(self) -> None:
		import json
		from pathlib import Path

		root = Path(frappe.get_app_path("tradehub_core")) / "tradehub_core" / "doctype" / "media_folder"
		schema = json.loads((root / "media_folder.json").read_text(encoding="utf-8"))
		create_roles = {p.get("role") for p in schema.get("permissions", []) if p.get("create")}
		self.assertEqual(
			create_roles, {"System Manager"},
			"Media Folder create yetkisi genişledi — satıcı/başka rol klasör açabilir hâle geldi.",
		)
		seller_roller = frappe.get_roles(self.seller)
		self.assertNotIn(
			"System Manager", seller_roller,
			"Fixture bozuk: tırmanmayı deneyen satıcıya System Manager verilmiş.",
		)

	def test_satici_kendi_magaza_klasoru_bile_olusturamaz(self) -> None:
		# Satıcının create DocPerm'i yok: KENDİ mağazası için bile insert
		# DocType düzeyinde reddedilir. Tırmanma yüzeyi hiç açılmaz.
		frappe.set_user(self.seller)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_doc(
				{"doctype": "Media Folder", "folder_name": f"esc-{self.suffix}", "store": self.store}
			).insert()
		frappe.set_user("Administrator")

	def test_VACUITY_folder_yapisal_olarak_olusturulabilir(self) -> None:
		# Kontrol: reddin sebebi 'klasör kaydı bozuk/oluşturulamaz' DEĞİL, izin.
		# ignore_permissions ile aynı kayıt oluşuyorsa satıcı reddi gerçek koruma.
		folder = frappe.get_doc(
			{"doctype": "Media Folder", "folder_name": f"kontrol-{self.suffix}", "store": self.store}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Media Folder", folder.name))
		self.assertTrue(
			frappe.db.exists("Media Folder", folder.name),
			"Vacuity: yapısal insert de başarısızsa test kör — koruma değil, bozuk kayıt ölçülüyor.",
		)


class PaymentIbanPermlevelEscalationTests(_EscalationBase):
	"""Payment Transaction IBAN (permlevel-1) yazma tırmanması.

	Marketplace Admin permlevel-0'da YAZAR (satır düzeyinde ödeme düzenleyebilir)
	ama permlevel-1'de yalnız OKUR (media_asset ile aynı desen, B-03). Yani IBAN'ı
	DEĞİŞTİREMEZ — finansal PII yönetici eliyle bile satır düzenlemesiyle
	oynanamaz. Bu, satıcı-yazamaz'dan daha keskin bir sınır: pl0-yazma yetkisi
	OLAN bir rolün pl1 alanında düşmesi.
	"""

	ORIG_IBAN = "TR710004600640888000110422"

	def _payment(self) -> str:
		doc = frappe.get_doc(
			{
				"doctype": "Payment Transaction",
				"transaction_type": "Ödeme",
				"order": f"W9E-ORD-{self.suffix}",
				"buyer": self.buyer,
				"seller": self.store,
				"amount": 100,
				"currency": "TRY",
				"seller_iban": self.ORIG_IBAN,
				"seller_bank_name": "Orijinal Banka",
				"status": "Gönderildi",
			}
		)
		doc.flags.ignore_mandatory = True
		doc.flags.ignore_links = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Payment Transaction", doc.name))
		return doc.name

	def test_marketplace_admin_iban_yazamaz(self) -> None:
		name = self._payment()
		frappe.set_user(self.admin)
		doc = frappe.get_doc("Payment Transaction", name)
		doc.seller_iban = "TR000000000000000000000000"
		doc.flags.ignore_links = True  # sentetik order link'i tekrar doğrulanmasın
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Payment Transaction", name, "seller_iban"), self.ORIG_IBAN,
			"Marketplace Admin IBAN'ı değiştirdi — permlevel-1 finansal PII yazma koruması delindi.",
		)

	def test_pl1_yazma_yetkisi_yalniz_platform_rollerinde(self) -> None:
		# Model motoruna sormadan: admin'in permlevel-1 yazma kümesinde 1 YOK.
		name = self._payment()
		frappe.set_user(self.admin)
		doc = frappe.get_doc("Payment Transaction", name)
		self.assertNotIn(
			1, doc.get_permlevel_access("write"),
			"Marketplace Admin permlevel-1 yazabiliyor — IBAN koruması yetkiden düşmüş.",
		)
		frappe.set_user("Administrator")

	def test_VACUITY_admin_pl0_alanini_yazabilir(self) -> None:
		# Kontrol: admin'in yazımı büsbütün düşmüyor — permlevel-0 alanı (status)
		# GERÇEKTEN değişiyor. Yani IBAN'ın değişmemesi permlevel-1'e ÖZGÜ.
		name = self._payment()
		frappe.set_user(self.admin)
		doc = frappe.get_doc("Payment Transaction", name)
		doc.status = "Beklemede"  # Gönderildi → Beklemede (geçerli pl0 select)
		doc.flags.ignore_links = True
		doc.save()
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Payment Transaction", name, "status"), "Beklemede",
			"Vacuity: admin permlevel-0'ı da yazamıyorsa test kör — save büsbütün düşüyor.",
		)


class RoleJumpEscalationTests(_EscalationBase):
	"""Satıcı, kendi User kaydına yüksek rol EKLEYEMEZ (rol atlama)."""

	def _seller_adds_role(self, role: str) -> None:
		frappe.set_user(self.seller)
		try:
			doc = frappe.get_doc("User", self.seller)
			doc.append("roles", {"role": role})
			# Rol eklenmesi ya sessizce düşer ya PermissionError olur; ikisi de red.
			try:
				doc.save()
			except frappe.PermissionError:
				pass
		finally:
			frappe.set_user("Administrator")

	def test_satici_kendine_system_manager_ekleyemez(self) -> None:
		self._seller_adds_role("System Manager")
		roller = {r.role for r in frappe.get_doc("User", self.seller).roles}
		self.assertNotIn(
			"System Manager", roller,
			"Satıcı kendine System Manager taktı — rol atlama açık, tam yetki tırmanması.",
		)

	def test_satici_kendine_marketplace_admin_ekleyemez(self) -> None:
		self._seller_adds_role("Marketplace Admin")
		roller = {r.role for r in frappe.get_doc("User", self.seller).roles}
		self.assertNotIn(
			"Marketplace Admin", roller,
			"Satıcı kendine Marketplace Admin taktı — platform yönetim rolüne tırmandı.",
		)

	def test_VACUITY_yetkili_ekleme_kaliyor(self) -> None:
		# Kontrol: rol ekleme mekanizması ÇALIŞIYOR — ignore_permissions ile
		# eklenen rol kalıyor. Demek ki satıcı yolundaki düşüş izin sisteminden,
		# 'roller hiç yazılamıyor'dan değil. Throwaway user cleanup'ta siliniyor.
		doc = frappe.get_doc("User", self.seller)
		doc.append("roles", {"role": "System Manager"})
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		roller = {r.role for r in frappe.get_doc("User", self.seller).roles}
		self.assertIn(
			"System Manager", roller,
			"Vacuity: yetkili ekleme de tutmuyorsa test kör — roller büsbütün yazılamıyor.",
		)


if __name__ == "__main__":
	import unittest

	unittest.main()
