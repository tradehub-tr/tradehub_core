"""TUR-126 — medya erişim-seviyesi toggle testleri (public ↔ private).

`tradehub_core/api/media_admin.py:set_access_level` süper-admin'in bir dosyanın
public/private seviyesini değiştirmesini sağlar (`docs/MEDYA-ERISIM-MODELI.md`
§4). Kritik güvenlik kuralı: KYB/KYC gibi `presets.EXCLUDED_DOCTYPES`'e bağlı
belgeler ASLA public yapılamaz (PII sızıntısı koruması) — bu `force` ile de,
rol seviyesiyle de aşılamaz.

Fiziksel dosya gerçekten taşınır (`private/files/<ab>/` ↔ `public/files/<ab>/`),
`File.file_url` + `File.is_private` güncellenir, dosyayı kullanan referanslar
(`Listing.primary_image` vb., `media/refs.py`) yeni URL'e çevrilir — hepsi
`test_media_pipeline_integration.py` ile aynı desende gerçek DB üzerinde.

`_guard()` `frappe.only_for` kullanıyor; bu fonksiyon `frappe.flags.in_test`
True iken (bench test runner'ın varsayılanı) rol kontrolünü BAYPAS EDER
(`frappe/__init__.py:only_for`). Yetkisiz-kullanıcı testi bu yüzden çağrı
etrafında `frappe.flags.in_test = False` ile geçici olarak gerçek rol
kontrolünü açar — Frappe çekirdeğinin kendi testlerinde de kullanılan desen
(`frappe/core/doctype/user/test_user.py`).

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_media_access_level
"""

from __future__ import annotations

import contextlib
import json
import os
from unittest import mock

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import get_files_path

from tradehub_core.api import media_admin
from tradehub_core.media import access_level, audit


@contextlib.contextmanager
def mock_log_media_event():
	with mock.patch.object(access_level.audit, "log_media_event") as m:
		yield m


def _write_public_file(name: str, content: bytes) -> str:
	"""Public bir dosyayı gerçek diske yazar, `/files/<ab>/<name>` döner."""
	shard = name[:2]
	base = get_files_path(is_private=0)
	frappe.create_folder(os.path.join(base, shard))
	with open(os.path.join(base, shard, name), "wb") as f:
		f.write(content)
	return f"/files/{shard}/{name}"


def _write_private_file(name: str, content: bytes) -> str:
	shard = name[:2]
	base = get_files_path(is_private=1)
	frappe.create_folder(os.path.join(base, shard))
	with open(os.path.join(base, shard, name), "wb") as f:
		f.write(content)
	return f"/private/files/{shard}/{name}"


class MediaAccessLevelTestBase(FrappeTestCase):
	"""Ortak fixture: gerçek `File` kaydı + gerçek disk dosyası."""

	def _delete_and_commit(self, doctype: str, name: str) -> None:
		if frappe.db.exists(doctype, name):
			frappe.delete_doc(doctype, name, ignore_permissions=True, force=True)
			frappe.db.commit()

	def _remove_path_if_exists(self, path: str) -> None:
		if os.path.isfile(path):
			os.remove(path)

	def _cleanup_both_locations(self, name: str) -> None:
		"""Testler dosyayı taşıyabildiği için hem public hem private konumu
		siler — hangi konumda kaldığı testin sonucuna bağlı."""
		shard = name[:2]
		self.addCleanup(
			lambda: self._remove_path_if_exists(os.path.join(get_files_path(is_private=0), shard, name))
		)
		self.addCleanup(
			lambda: self._remove_path_if_exists(os.path.join(get_files_path(is_private=1), shard, name))
		)

	def setUp(self):
		super().setUp()
		self._orig_user = frappe.session.user
		self.addCleanup(lambda: frappe.set_user(self._orig_user))
		frappe.set_user("Administrator")

	def _make_public_file(self, tag: str, *, attached_to_doctype: str | None = None) -> "frappe._dict":
		suffix = frappe.generate_hash(length=10)
		name = f"{suffix}.txt"
		content = f"erisim-seviyesi-{tag}-{suffix}".encode()
		url = _write_public_file(name, content)
		self._cleanup_both_locations(name)

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": name,
				"file_url": url,
				"is_private": 0,
				"attached_to_doctype": attached_to_doctype,
				"attached_to_name": "FIXTURE-YOK" if attached_to_doctype else None,
			}
		)
		doc.flags.ignore_mandatory = True
		# Tarama kancasını NÖTRLE: makinede ClamAV kuruluysa `after_insert`
		# dosyayı anında `media_scan_hold`'a taşıyor ve test "diskte yok" diyor.
		# Testin sınadığı şey seviye değişimi, tarama değil (test_media_av deseni).
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", doc.name))
		return doc

	def _make_private_file(self, tag: str) -> "frappe._dict":
		suffix = frappe.generate_hash(length=10)
		name = f"{suffix}.txt"
		content = f"erisim-seviyesi-{tag}-{suffix}".encode()
		url = _write_private_file(name, content)
		self._cleanup_both_locations(name)

		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": name,
				"file_url": url,
				"is_private": 1,
			}
		)
		doc.flags.ignore_mandatory = True
		# Tarama kancasını NÖTRLE: makinede ClamAV kuruluysa `after_insert`
		# dosyayı anında `media_scan_hold`'a taşıyor ve test "diskte yok" diyor.
		# Testin sınadığı şey seviye değişimi, tarama değil (test_media_av deseni).
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", doc.name))
		return doc

	def _make_seller(self, tag: str) -> str:
		suffix = frappe.generate_hash(length=8)
		store = frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": f"Erisim Seviyesi Satici {tag}",
				"seller_code": frappe.generate_hash(length=10),
				"status": "Active",
			}
		)
		store.flags.ignore_mandatory = True
		store.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Admin Seller Profile", store.name))
		return store.name

	def _make_listing(self, seller: str, primary_image: str, tag: str) -> str:
		listing = frappe.get_doc(
			{
				"doctype": "Listing",
				"listing_code": f"ERISIM-{tag}-{frappe.generate_hash(length=6)}",
				"title": f"Erisim Seviyesi Test Ürünü {tag}",
				"seller_profile": seller,
				"status": "Active",
				"currency": "TRY",
				"base_price": 100,
				"selling_price": 100,
				"primary_image": primary_image,
			}
		)
		listing.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Listing", listing.name))
		return listing.name


class PublicToPrivateTests(MediaAccessLevelTestBase):
	def test_public_dosya_private_yapilinca_disk_url_ve_referans_guncellenir(self):
		file_doc = self._make_public_file("p2v")
		seller = self._make_seller("p2v")
		listing_name = self._make_listing(seller, file_doc.file_url, "p2v")

		old_url = file_doc.file_url
		old_path = os.path.join(get_files_path(is_private=0), *old_url[len("/files/") :].split("/"))

		result = access_level.set_level(old_url, make_private=True)

		self.assertTrue(result["changed"])
		self.assertTrue(result["is_private"])
		new_url = result["file_url"]
		self.assertTrue(new_url.startswith("/private/files/"))
		# Shard + dosya adı korunur, yalnız prefix değişir.
		self.assertEqual(new_url[len("/private/files/") :], old_url[len("/files/") :])

		new_path = os.path.join(get_files_path(is_private=1), *new_url[len("/private/files/") :].split("/"))
		self.assertFalse(os.path.isfile(old_path), "eski konumda dosya hâlâ duruyor")
		self.assertTrue(os.path.isfile(new_path), "yeni konumda dosya yok")

		file_doc.reload()
		self.assertEqual(file_doc.file_url, new_url)
		self.assertEqual(int(file_doc.is_private), 1)

		self.assertEqual(frappe.db.get_value("Listing", listing_name, "primary_image"), new_url)
		self.assertGreaterEqual(result["refs_updated"], 1)


class PrivateToPublicTests(MediaAccessLevelTestBase):
	def test_private_dosya_public_yapilinca_disk_url_ve_referans_guncellenir(self):
		file_doc = self._make_private_file("v2p")
		seller = self._make_seller("v2p")
		listing_name = self._make_listing(seller, file_doc.file_url, "v2p")

		old_url = file_doc.file_url
		old_path = os.path.join(get_files_path(is_private=1), *old_url[len("/private/files/") :].split("/"))

		result = access_level.set_level(old_url, make_private=False)

		self.assertTrue(result["changed"])
		self.assertFalse(result["is_private"])
		new_url = result["file_url"]
		self.assertTrue(new_url.startswith("/files/"))
		self.assertEqual(new_url[len("/files/") :], old_url[len("/private/files/") :])

		new_path = os.path.join(get_files_path(is_private=0), *new_url[len("/files/") :].split("/"))
		self.assertFalse(os.path.isfile(old_path))
		self.assertTrue(os.path.isfile(new_path))

		file_doc.reload()
		self.assertEqual(file_doc.file_url, new_url)
		self.assertEqual(int(file_doc.is_private), 0)

		self.assertEqual(frappe.db.get_value("Listing", listing_name, "primary_image"), new_url)


class KybProtectionTests(MediaAccessLevelTestBase):
	def test_kyb_belgesi_public_yapilamaz(self):
		"""KRİTİK güvenlik testi: KYB Verification'a bağlı dosya asla public
		yapılamaz — PII sızıntısı koruması, `frappe.throw` beklenir."""
		file_doc = self._make_public_file("kyb", attached_to_doctype="KYB Verification")
		# Zaten public — private->public "geçişini" tetiklemek için önce
		# private yapıyoruz (fiziksel taşıma dahil), sonra tekrar public'e
		# çevirmeyi deneyip reddedildiğini doğruluyoruz.
		moved = access_level.set_level(file_doc.file_url, make_private=True)

		with self.assertRaises(frappe.ValidationError):
			access_level.set_level(moved["file_url"], make_private=False)

		# Reddedilen istek dosyayı private'ta bırakmalı (değişmemeli).
		file_doc.reload()
		self.assertEqual(int(file_doc.is_private), 1)

	def test_kyb_belgesi_private_yapilabilir(self):
		"""Private yapmak serbest — yalnız PUBLIC yapmak yasak."""
		file_doc = self._make_public_file("kyb-priv", attached_to_doctype="KYB Verification")

		result = access_level.set_level(file_doc.file_url, make_private=True)

		self.assertTrue(result["changed"])
		self.assertTrue(result["is_private"])


class ReverseReferencePiiTests(MediaAccessLevelTestBase):
	"""CRITICAL güvenlik testi (canlı DB review bulgusu): bazı PII belgeleri
	`File.attached_to_doctype` set edilmeden yükleniyor, yalnız EXCLUDED bir
	doctype'ın kendi alanından (`Seller Application.identity_document`)
	string olarak referanslanıyor. `attached_to_doctype in EXCLUDED_DOCTYPES`
	kontrolü TEK BAŞINA bunu kaçırıyordu — canlı DB'de 144+2 = 146 dosya bu
	deseni kullanıyor."""

	def _make_applicant_user(self, tag: str) -> str:
		suffix = frappe.generate_hash(length=8)
		email = f"erisim-seviyesi-basvuru-{tag}-{suffix}@test.local"
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Basvuru",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("User", email))
		return email

	def _make_seller_application(self, applicant: str, tag: str) -> str:
		application = frappe.get_doc({"doctype": "Seller Application", "applicant_user": applicant})
		application.flags.ignore_mandatory = True
		application.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Seller Application", application.name))
		return application.name

	def _attach_via_db(self, application_name: str, field: str, url: str) -> None:
		"""`identity_document`'i doc controller'ı ATLAYARAK doğrudan SQL ile
		set eder — canlı DB'deki 146 dosyanın gerçek deseni bu.

		`frappe.get_doc({...}).insert()` ile Attach alanını KURULUŞ ANINDA
		set edersek, Frappe'nin kendi doc-save akışı var olan `file_url`'e
		işaret eden İKİNCİ bir `File` kaydı oluşturup onu bu doküman'a
		otomatik LİNKLİYOR (`attached_to_doctype` dolduruluyor) — bu da
		mevcut (henüz düzeltilmemiş) `attached_to_doctype` kontrolünü
		yanlışlıkla tetikleyip testi anlamsız kılıyor (doğrulandı: canlı
		debug'da `doc.insert()` yolu attached_to_doctype='Seller
		Application' ile YENİ bir File satırı yaratıyor). Production'daki
		146 dosya ise migration/toplu-yükleme gibi bu doc-save akışını
		ATLAYAN bir yoldan geldiği için `attached_to_doctype` hâlâ BOŞ —
		`db.set_value` bunu birebir simüle eder.
		"""
		frappe.db.set_value("Seller Application", application_name, field, url, update_modified=False)
		frappe.db.commit()

	def test_attached_to_doctype_bos_ama_seller_application_referansli_dosya_public_yapilamaz(self):
		"""Tam olarak kaçan senaryo: `attached_to_doctype` YOK, yalnız
		`Seller Application.identity_document` bu dosyayı gösteriyor."""
		file_doc = self._make_private_file("sa-ref")
		applicant = self._make_applicant_user("sa-ref")
		application_name = self._make_seller_application(applicant, "sa-ref")
		self._attach_via_db(application_name, "identity_document", file_doc.file_url)

		# Bypass'ın gerçekten tetiklendiğini doğrula: attached_to_doctype BOŞ.
		self.assertIsNone(frappe.db.get_value("File", file_doc.name, "attached_to_doctype"))

		with self.assertRaisesRegex(frappe.ValidationError, "KVKK/PII"):
			access_level.set_level(file_doc.file_url, make_private=False)

		# Reddedilen istek dosyayı private'ta bırakmalı (değişmemeli).
		file_doc.reload()
		self.assertEqual(int(file_doc.is_private), 1)

	def test_ayni_dosya_private_yapmak_icin_serbest(self):
		"""Ters referanslı PII dosyayı private yapmak serbest — yalnız
		PUBLIC yapmak yasak (KybProtectionTests ile aynı asimetri)."""
		file_doc = self._make_public_file("sa-ref-priv")
		applicant = self._make_applicant_user("sa-ref-priv")
		application_name = self._make_seller_application(applicant, "sa-ref-priv")
		self._attach_via_db(application_name, "identity_document", file_doc.file_url)

		result = access_level.set_level(file_doc.file_url, make_private=True)

		self.assertTrue(result["changed"])
		self.assertTrue(result["is_private"])


class RefsSkippedTests(MediaAccessLevelTestBase):
	def test_gomulu_referans_atlanir_ve_donuste_gorunur(self):
		"""Important fix: `retarget`'ın atladığı (JSON gömülü) referanslar API
		cevabından kaybolmamalı — operatör kırık referans riskinden haberdar
		olmalı. `Storefront Layout.sections` JSON içine gömülü URL tam eşleşme
		OLMADIĞI için güncellenmez, atlanmış olarak raporlanmalı."""
		file_doc = self._make_public_file("refs-skipped")
		seller = self._make_seller("refs-skipped")

		sections = [
			{
				"type": "gallery",
				"order": 1,
				"enabled": True,
				"settings": {"columns": 4, "lightbox": True, "cover_image": file_doc.file_url},
			}
		]
		layout = frappe.get_doc(
			{
				"doctype": "Storefront Layout",
				"seller_profile": seller,
				"sections": json.dumps(sections),
			}
		)
		layout.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("Storefront Layout", layout.name))

		result = access_level.set_level(file_doc.file_url, make_private=True)

		self.assertIn("refs_skipped", result)
		self.assertGreaterEqual(result["refs_skipped"], 1)
		self.assertIn("refs_skipped_detail", result)
		self.assertTrue(result["refs_skipped_detail"])


class IdempotentTests(MediaAccessLevelTestBase):
	def test_zaten_hedef_seviyedeyse_no_op(self):
		file_doc = self._make_public_file("idem")

		result = access_level.set_level(file_doc.file_url, make_private=False)

		self.assertFalse(result["changed"])
		self.assertEqual(result["file_url"], file_doc.file_url)
		self.assertFalse(result["is_private"])

		# Disk hâlâ eski konumda — dokunulmamış.
		path = os.path.join(get_files_path(is_private=0), *file_doc.file_url[len("/files/") :].split("/"))
		self.assertTrue(os.path.isfile(path))


class AuditTests(MediaAccessLevelTestBase):
	def test_basarili_degisim_media_level_changed_yazar(self):
		file_doc = self._make_public_file("audit")

		with mock_log_media_event() as m:
			result = access_level.set_level(file_doc.file_url, make_private=True)

		m.assert_called_once()
		_, kwargs = m.call_args
		self.assertEqual(kwargs["action"], audit.ACTION_LEVEL_CHANGED)
		self.assertEqual(kwargs["file_url"], result["file_url"])
		self.assertTrue(kwargs["context"]["new_private"])
		self.assertFalse(kwargs["context"]["old_private"])

	def test_gecis_hassas_isaretlenir_ve_ham_url_context_e_yazilmaz(self):
		"""Important fix: her geçiş kaynak ya da hedefte bir private durumu
		içerir (ikisi asla aynı olamaz — idempotent kontrolü zaten farklı
		olmasını garanti eder). `log_media_event`'e `sensitive=True`
		geçilmeli VE context'e KENDİ eklediğimiz ham yol alanları (`old_url`
		gibi) düz metin sızdırmamalı — `log_media_event` yalnız sabit üç
		anahtarı ("file_name"/"file_url"/"attached_to_doctype") otomatik
		siliyor, bizim özel anahtarımızı silmiyor."""
		file_doc = self._make_public_file("audit-mask")

		with mock_log_media_event() as m:
			access_level.set_level(file_doc.file_url, make_private=True)

		_, kwargs = m.call_args
		self.assertTrue(kwargs["sensitive"])
		self.assertNotIn(file_doc.file_url, str(kwargs["context"]))

	def test_gercek_adl_kaydinda_object_name_maskeli(self):
		"""Mock değil — gerçek DB'ye yazılan ADL satırı kontrol edilir:
		maskeleme sahiden kalıcı kayda yansıyor mu."""
		file_doc = self._make_public_file("audit-real")

		access_level.set_level(file_doc.file_url, make_private=True)

		rows = frappe.get_all(
			"Authorization Decision Log",
			filters={"action": audit.ACTION_LEVEL_CHANGED},
			fields=["object_name", "context"],
			order_by="creation desc",
			limit_page_length=1,
		)
		self.assertTrue(rows)
		self.assertTrue(rows[0]["object_name"].startswith("masked:"))
		self.assertNotIn(file_doc.file_url, rows[0]["context"] or "")


class GuardTests(MediaAccessLevelTestBase):
	"""`_guard()` yalnız System Manager / Marketplace Admin'e izin verir.

	`frappe.only_for`, `frappe.flags.in_test=True` iken (bench test runner
	varsayılanı) rol kontrolünü baypas ediyor — burada geçici olarak kapatıp
	gerçek rol denetimini test ediyoruz.
	"""

	def test_yetkisiz_kullanici_reddedilir(self):
		suffix = frappe.generate_hash(length=8)
		email = f"erisim-seviyesi-yetkisiz-{suffix}@test.local"
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
				media_admin.set_access_level(file_url="/files/aa/does-not-matter.jpg", make_private=1)
		finally:
			frappe.flags.in_test = prev
			frappe.set_user("Administrator")


class PrivateFilesListTest(MediaAccessLevelTestBase):
	"""`get_private_files` — panelin 'Özel dosyalar' görünümü (TUR-126 §4.2).

	Public envanter (`inventory.list_files`) bilinçli olarak private dosyaları
	dışlıyor; özele taşınan dosyanın panelden geri alınabilmesi ve imzalı link
	üretilebilmesi için ayrı, süper-admin'e kapılı bir liste gerekir.
	"""

	def test_private_dosya_listelenir_public_listelenmez(self):
		priv = self._make_private_file("ozel-liste")
		pub = self._make_public_file("ozel-liste")

		out = media_admin.get_private_files(search=priv.file_name)
		self.assertEqual(out["total"], 1)
		self.assertEqual(out["items"][0]["file_url"], priv.file_url)

		out_pub = media_admin.get_private_files(search=pub.file_name)
		self.assertEqual(out_pub["total"], 0)

	def test_pii_bagli_dosya_bayraklanir(self):
		suffix = frappe.generate_hash(length=10)
		name = f"{suffix}.txt"
		url = _write_private_file(name, b"pii-liste-fixture")
		self._cleanup_both_locations(name)
		doc = frappe.get_doc(
			{
				"doctype": "File",
				"file_name": name,
				"file_url": url,
				"is_private": 1,
				"attached_to_doctype": "KYB Verification",
				"attached_to_name": "FIXTURE-YOK",
			}
		)
		doc.flags.ignore_mandatory = True
		# Tarama kancasını NÖTRLE: makinede ClamAV kuruluysa `after_insert`
		# dosyayı anında `media_scan_hold`'a taşıyor ve test "diskte yok" diyor.
		# Testin sınadığı şey seviye değişimi, tarama değil (test_media_av deseni).
		with mock.patch("tradehub_core.media.av.enqueue_scan"):
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._delete_and_commit("File", doc.name))

		out = media_admin.get_private_files(search=name)
		self.assertEqual(out["total"], 1)
		self.assertTrue(out["items"][0]["pii"])

		normal = self._make_private_file("pii-degil")
		out2 = media_admin.get_private_files(search=normal.file_name)
		self.assertFalse(out2["items"][0]["pii"])

	def test_yetkisiz_kullanici_liste_alamaz(self):
		suffix = frappe.generate_hash(length=8)
		email = f"ozel-liste-yetkisiz-{suffix}@test.local"
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
				media_admin.get_private_files()
		finally:
			frappe.flags.in_test = prev
			frappe.set_user("Administrator")


if __name__ == "__main__":
	import unittest

	unittest.main()
