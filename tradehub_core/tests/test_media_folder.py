"""T-094 — gerçek satıcı klasörleri: CRUD, benzersizlik, derinlik tavanı,
dolu klasör silme ve KİRACI İZOLASYONU.

İzolasyonun iki katmanı ayrı ayrı sınanır:

  1. Uç-içi: her klasör ucu mağazayı oturumdan çözer ve `_my_folder` ile
     karşılaştırır. hooks.py kaydı OLMADAN geçerli olan tek katman budur —
     "vacuity" testi (`test_kontrol_gevsetilince_sizinti_gercekten_olur`)
     kontrolü bilerek gevşetip sızıntının GERÇEKTEN oluştuğunu gösterir; yani
     yeşil geçen çapraz-kiracı testleri boş yere geçmiyor.
  2. Çerçeve: `media_folder.py` içindeki `get_permission_query_conditions` +
     `has_permission` fonksiyonları doğrudan çağrılarak sınanır. Bunlar
     hooks.py'a bu görevde KAYITLI DEĞİL (rapora bakın); kayıt yapılana kadar
     genel uçların kapalı olduğu da ayrıca sınanır (satıcı rollerinde DocPerm
     yok → `frappe.get_list` PermissionError).

Desen `test_file_multirow_isolation.py` ile aynı: gerçek DB (FrappeTestCase),
`ignore_permissions=True` + `addCleanup` ile LIFO temizlik.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \\
        run-tests --module tradehub_core.tests.test_media_folder
"""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import seller_media as api
from tradehub_core.tradehub_core.doctype.media_folder import media_folder as mf
from tradehub_core.utils.tenant import clear_seller_cache_for_user


def _blob(suffix: str) -> bytes:
	return f"klasor testi icerigi {suffix}".encode()


class MediaFolderTests(FrappeTestCase):
	# -- fixture yardımcıları ------------------------------------------------

	def _drop(self, doctype: str, name: str) -> None:
		onceki = frappe.session.user
		frappe.set_user("Administrator")
		try:
			if doctype == "Media Folder":
				# `on_trash` dolu klasörü reddediyor — temizlik o kuralın
				# sınandığı yer değil, önce bağlar düşürülür.
				for item in frappe.get_all(
					"Media Folder Item", filters={"folder": name}, pluck="name"
				):
					frappe.delete_doc(
						"Media Folder Item", item, ignore_permissions=True, force=True
					)
			if frappe.db.exists(doctype, name):
				frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()
		finally:
			frappe.set_user(onceki)

	def _user(self, tag: str) -> str:
		email = f"t094-{tag}-{self.suffix}@test.local"
		doc = frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": tag,
				"send_welcome_email": 0,
				"enabled": 1,
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
				"seller_code": f"T94{tag}{self.suffix}",
				"seller_name": f"T94 {tag} {self.suffix}",
				"user": user,
				"email": user,
				"status": "Active",
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Admin Seller Profile", doc.name))
		return doc.name

	def _file(self, tag: str, as_user: str) -> str:
		"""`as_user` olarak dosya yükle, `file_url` dön."""
		onceki = frappe.session.user
		frappe.set_user(as_user)
		try:
			doc = frappe.get_doc(
				{
					"doctype": "File",
					"file_name": f"t094-{tag}-{self.suffix}.txt",
					"is_private": 0,
					"content": _blob(f"{tag}-{self.suffix}"),
				}
			).insert(ignore_permissions=True)
			frappe.db.commit()
		finally:
			frappe.set_user(onceki)
		self.addCleanup(lambda: self._drop("File", doc.name))
		return doc.file_url

	def _folder(self, name: str, parent: str = "", as_user: str | None = None) -> str:
		"""Ucun kendisiyle klasör aç — dönen docname."""
		if as_user:
			frappe.set_user(as_user)
		sonuc = api.create_folder(folder_name=name, parent_folder=parent)
		self.addCleanup(lambda: self._drop("Media Folder", sonuc["name"]))
		return sonuc["name"]

	def _names(self) -> set[str]:
		return {f["folder_name"] for f in api.list_folders()["folders"]}

	# -- kurulum -------------------------------------------------------------

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")
		self.suffix = frappe.generate_hash(length=6)

		self.a_owner = self._user("a")
		self.store_a = self._seller("A", self.a_owner)
		self.b_owner = self._user("b")
		self.store_b = self._seller("B", self.b_owner)

		# Taşıma testleri için A'ya ait gerçek bir dosya.
		self.a_url = self._file("dosya", self.a_owner)
		frappe.set_user("Administrator")

	# -- CRUD ----------------------------------------------------------------

	def test_crud_klasor_acilir_listelenir_adi_degisir_silinir(self):
		frappe.set_user(self.a_owner)
		ad = f"Kampanya {self.suffix}"
		k = api.create_folder(folder_name=ad)
		self.addCleanup(lambda: self._drop("Media Folder", k["name"]))

		liste = api.list_folders()
		self.assertIn(ad, {f["folder_name"] for f in liste["folders"]})
		self.assertEqual(liste["max_depth"], mf.MAX_DEPTH)

		api.rename_folder(folder=k["name"], new_name=f"Arşiv {self.suffix}")
		self.assertEqual(
			frappe.db.get_value("Media Folder", k["name"], "folder_name"),
			f"Arşiv {self.suffix}",
		)

		api.delete_folder(folder=k["name"])
		self.assertFalse(frappe.db.exists("Media Folder", k["name"]))

	def test_bos_ad_reddedilir(self):
		frappe.set_user(self.a_owner)
		with self.assertRaises(frappe.ValidationError):
			api.create_folder(folder_name="   ")

	def test_alt_klasor_ebeveyne_baglanir(self):
		frappe.set_user(self.a_owner)
		ust = self._folder(f"Üst {self.suffix}")
		alt = self._folder(f"Alt {self.suffix}", parent=ust)
		self.assertEqual(
			frappe.db.get_value("Media Folder", alt, "parent_folder"), ust
		)

	# -- benzersizlik ----------------------------------------------------------

	def test_ayni_ebeveyn_altinda_ayni_ad_reddedilir(self):
		frappe.set_user(self.a_owner)
		ad = f"Tekrar {self.suffix}"
		self._folder(ad)
		with self.assertRaises(frappe.DuplicateEntryError):
			api.create_folder(folder_name=ad)

	def test_farkli_ebeveyn_altinda_ayni_ad_serbesttir(self):
		frappe.set_user(self.a_owner)
		ad = f"Ayni Ad {self.suffix}"
		ust = self._folder(f"Cati {self.suffix}")
		self._folder(ad)  # kökte
		alt = self._folder(ad, parent=ust)  # klasör içinde — çakışma değil
		self.assertTrue(frappe.db.exists("Media Folder", alt))

	def test_yeniden_adlandirma_da_benzersizlige_takilir(self):
		frappe.set_user(self.a_owner)
		self._folder(f"Bir {self.suffix}")
		iki = self._folder(f"Iki {self.suffix}")
		with self.assertRaises(frappe.DuplicateEntryError):
			api.rename_folder(folder=iki, new_name=f"Bir {self.suffix}")

	def test_baska_maganin_ayni_adi_engel_degildir(self):
		ad = f"Ortak Ad {self.suffix}"
		frappe.set_user(self.a_owner)
		self._folder(ad)
		frappe.set_user(self.b_owner)
		b_k = self._folder(ad)  # B kendi kökünde aynı adı kullanabilir
		self.assertTrue(frappe.db.exists("Media Folder", b_k))

	# -- derinlik tavanı -------------------------------------------------------

	def test_derinlik_tavani_besinci_seviye_gecer_altinci_reddedilir(self):
		frappe.set_user(self.a_owner)
		parent = ""
		for i in range(mf.MAX_DEPTH):  # 1..5 açılabilmeli
			parent = self._folder(f"Seviye{i + 1} {self.suffix}", parent=parent)
		with self.assertRaises(frappe.ValidationError):
			api.create_folder(
				folder_name=f"Seviye{mf.MAX_DEPTH + 1} {self.suffix}", parent_folder=parent
			)

	def test_alt_agacli_klasor_tasinirken_tavan_asilamaz(self):
		"""3 seviyelik alt ağacı olan klasörü 3. seviyeye taşımak 6 eder."""
		frappe.set_user(self.a_owner)
		d1 = self._folder(f"D1 {self.suffix}")
		d2 = self._folder(f"D2 {self.suffix}", parent=d1)
		d3 = self._folder(f"D3 {self.suffix}", parent=d2)  # hedef: 3. seviye

		t1 = self._folder(f"T1 {self.suffix}")
		t2 = self._folder(f"T2 {self.suffix}", parent=t1)
		self._folder(f"T3 {self.suffix}", parent=t2)  # t1'in yüksekliği 3

		doc = frappe.get_doc("Media Folder", t1)
		doc.parent_folder = d3
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_dongu_reddedilir(self):
		frappe.set_user(self.a_owner)
		ust = self._folder(f"Dongu Ust {self.suffix}")
		alt = self._folder(f"Dongu Alt {self.suffix}", parent=ust)
		doc = frappe.get_doc("Media Folder", ust)
		doc.parent_folder = alt  # A → B → A
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	# -- taşıma ----------------------------------------------------------------

	def test_tasima_dosya_klasore_girer_ve_tek_klasorde_durur(self):
		frappe.set_user(self.a_owner)
		k1 = self._folder(f"Tasima1 {self.suffix}")
		k2 = self._folder(f"Tasima2 {self.suffix}")

		sonuc = api.move_media(file_urls=[self.a_url], folder=k1)
		self.assertEqual(sonuc["moved"], 1)
		self.assertEqual(sonuc["skipped"], 0)

		# İkinci klasöre taşı — bağ TAŞINIR, çoğalmaz.
		api.move_media(file_urls=[self.a_url], folder=k2)
		baglar = frappe.get_all(
			"Media Folder Item",
			filters={"store": self.store_a, "file_url": self.a_url},
			fields=["folder"],
		)
		self.assertEqual(len(baglar), 1)
		self.assertEqual(baglar[0]["folder"], k2)

		# Listeleme dosyayı görür.
		icerik = api.list_folder_media(folder=k2)
		self.assertEqual(icerik["total"], 1)
		self.assertEqual(icerik["items"][0]["file_url"], self.a_url)

		# Köke taşı — bağ silinir.
		api.move_media(file_urls=[self.a_url], folder="")
		self.assertFalse(
			frappe.db.exists(
				"Media Folder Item", {"store": self.store_a, "file_url": self.a_url}
			)
		)

	def test_tasima_sahip_olunmayan_dosyayi_atlar(self):
		frappe.set_user(self.b_owner)
		b_k = self._folder(f"B Klasor {self.suffix}")
		sonuc = api.move_media(file_urls=[self.a_url], folder=b_k)
		self.assertEqual(sonuc["moved"], 0)
		self.assertEqual(sonuc["skipped"], 1)
		self.assertFalse(
			frappe.db.exists("Media Folder Item", {"file_url": self.a_url})
		)

	# -- dolu klasör silme -------------------------------------------------------

	def test_dolu_klasor_silinemez_bosaltilinca_silinir(self):
		frappe.set_user(self.a_owner)
		k = self._folder(f"Dolu {self.suffix}")
		api.move_media(file_urls=[self.a_url], folder=k)

		with self.assertRaises(frappe.ValidationError):
			api.delete_folder(folder=k)
		self.assertTrue(frappe.db.exists("Media Folder", k))

		api.move_media(file_urls=[self.a_url], folder="")
		api.delete_folder(folder=k)
		self.assertFalse(frappe.db.exists("Media Folder", k))

	def test_alt_klasorlu_klasor_silinemez(self):
		frappe.set_user(self.a_owner)
		ust = self._folder(f"Silinmez Ust {self.suffix}")
		self._folder(f"Silinmez Alt {self.suffix}", parent=ust)
		with self.assertRaises(frappe.ValidationError):
			api.delete_folder(folder=ust)

	# -- kiracı izolasyonu (uç-içi katman) ----------------------------------------

	def test_capraz_kiraci_b_a_nin_klasorunu_listede_goremez(self):
		frappe.set_user(self.a_owner)
		ad = f"A Gizli {self.suffix}"
		self._folder(ad)
		frappe.set_user(self.b_owner)
		self.assertNotIn(ad, self._names())

	def test_capraz_kiraci_b_a_nin_klasorune_dokunamaz(self):
		frappe.set_user(self.a_owner)
		a_k = self._folder(f"A Kale {self.suffix}")
		api.move_media(file_urls=[self.a_url], folder=a_k)

		frappe.set_user(self.b_owner)
		# Hata "bulunamadı" olmalı, "yetkin yok" değil — varlık doğrulanmaz.
		with self.assertRaises(frappe.DoesNotExistError):
			api.rename_folder(folder=a_k, new_name="ele gecirildi")
		with self.assertRaises(frappe.DoesNotExistError):
			api.delete_folder(folder=a_k)
		with self.assertRaises(frappe.DoesNotExistError):
			api.list_folder_media(folder=a_k)
		with self.assertRaises(frappe.DoesNotExistError):
			api.create_folder(folder_name="sizinti", parent_folder=a_k)
		with self.assertRaises(frappe.DoesNotExistError):
			api.move_media(file_urls=[self.a_url], folder=a_k)

		# Hiçbir şey değişmemiş olmalı.
		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Media Folder", a_k, "folder_name"),
			f"A Kale {self.suffix}",
		)

	def test_kontrol_gevsetilince_sizinti_gercekten_olur(self):
		"""VACUITY KANITI — üstteki testler boş yere geçmiyor.

		`_my_folder`'daki mağaza karşılaştırması gevşetilirse (her klasörü
		'benim' sayan sahte), B'nin A'nın klasörünü yeniden adlandırması
		BAŞARILI olur. Yani çapraz-kiracı testlerini yeşil tutan şey tam da o
		kontrol; kontrol silinirse bu test düzeni sızıntıyı yakalar.
		"""
		frappe.set_user(self.a_owner)
		a_k = self._folder(f"A Vacuity {self.suffix}")

		def gevsek(folder: str, store: str) -> dict:
			satir = frappe.db.get_value(
				"Media Folder",
				folder,
				["name", "folder_name", "parent_folder", "store"],
				as_dict=True,
			)
			return satir  # mağaza karşılaştırması YOK

		frappe.set_user(self.b_owner)
		with patch.object(api, "_my_folder", side_effect=gevsek):
			api.rename_folder(folder=a_k, new_name=f"sizdirildi {self.suffix}")

		frappe.set_user("Administrator")
		self.assertEqual(
			frappe.db.get_value("Media Folder", a_k, "folder_name"),
			f"sizdirildi {self.suffix}",
			"Kontrol gevşekken sızıntı OLUŞMADIYSA testler başka bir şeye yaslanıyor demektir",
		)

	# -- kiracı izolasyonu (çerçeve katmanı — hooks kaydı raporda) -----------------

	def test_permission_query_conditions_magazaya_daraltir(self):
		frappe.set_user(self.a_owner)
		a_k = self._folder(f"A Sorgu {self.suffix}")

		kosul = mf.get_permission_query_conditions(self.b_owner)
		self.assertIn("`tabMedia Folder`.`store`", kosul)
		adlar = {
			r[0]
			for r in frappe.db.sql(f"select name from `tabMedia Folder` where {kosul}")
		}
		self.assertNotIn(a_k, adlar)

		# Mağazasız kullanıcı ve Guest hiçbir şey görmez.
		magazasiz = self._user("nostore")
		self.assertEqual(mf.get_permission_query_conditions(magazasiz), "1=0")
		self.assertEqual(mf.get_permission_query_conditions("Guest"), "1=0")
		# Yönetici daraltılmaz.
		self.assertEqual(mf.get_permission_query_conditions("Administrator"), "")

	def test_has_permission_yalniz_kendi_magazasina_true_doner(self):
		frappe.set_user(self.a_owner)
		a_k = self._folder(f"A Tekil {self.suffix}")
		doc = frappe.get_doc("Media Folder", a_k)

		self.assertTrue(mf.has_permission(doc, user=self.a_owner))
		self.assertFalse(mf.has_permission(doc, user=self.b_owner))
		self.assertFalse(mf.has_permission(doc, user="Guest"))
		self.assertTrue(mf.has_permission(doc, user="Administrator"))

	def test_genel_uc_kayit_oncesi_saticilara_kapali(self):
		"""hooks.py kaydı yapılana kadar tek koruma DocPerm tablosu: satıcı
		rollerinde satır yok, dolayısıyla `frappe.get_list` (genel uçların
		kullandığı yol) satıcıya PermissionError verir. Bu test, kayıt
		gecikirse arada sessiz bir sızıntı penceresi OLMADIĞINI sabitler."""
		frappe.set_user(self.b_owner)
		with self.assertRaises(frappe.PermissionError):
			frappe.get_list("Media Folder", filters={}, fields=["name"])
