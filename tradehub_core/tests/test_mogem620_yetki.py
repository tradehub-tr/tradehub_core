"""MOGEM-620 — yetki, rol ve çok kiracılı izolasyon testleri.

KRİTİK OKUMA — BU MODÜL NEDEN `gercek_yetki()` KULLANIYOR
---------------------------------------------------------
`frappe.only_for` TESTTE DEVRE DIŞI (`frappe/__init__.py:954`):

    if local.flags.in_test or local.session.user == "Administrator":
        return

Yani `FrappeTestCase` altında yazılmış her "bu rol reddedilmeli" iddiası
KENDİLİĞİNDEN GEÇER ve hiçbir şey ölçmez. Bu tuzak 6 Eylül 2026'da
neredeyse sahte bir güvenlik açığı raporuna yol açtı.

Bu modüldeki her rol reddi `gercek_yetki()` sarmalayıcısı içinde. Ve
`TestNobetci` sınıfı sarmalayıcının KENDİSİNİ sınıyor: biri onu kaldırırsa
grup sessizce boşalmasın diye.

KAPSAM
------
    1. Rol kapısı        — yönetici uçlarına satıcı erişemez
    2. Kiracı izolasyonu — satıcı başkasının dosyasına yazamaz/okuyamaz
    3. Kapsam sızıntısı  — benzerlik araması rakibin kütüphanesini göstermez
    4. Yükseltme         — toplu uçlar tekil uçtan DAHA GENİŞ yetki vermez

Koşum:
    docker exec istoc-backend bench --site tradehub.localhost \\
        run-tests --module tradehub_core.tests.test_mogem620_yetki
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import media_admin, seller_media
from tradehub_core.media import bulk_ops, ownership, similar
from tradehub_core.tests.mogem620_ortak import (
	TUZ,
	dosya_ac,
	gercek_yetki,
	kullanici,
	magaza_bul,
	png_uret,
	sil,
)


def _satici_kullanici() -> str | None:
	"""Mağazası olan gerçek bir satıcı kullanıcısı — yoksa None."""
	magaza = magaza_bul()
	if not magaza:
		return None
	kullanicilar = ownership.users_of(magaza)
	for u in kullanicilar:
		if u and u not in ("Administrator", "Guest"):
			return u
	return None


class TestNobetci(FrappeTestCase):
	"""Sarmalayıcının kendisini sınayan nöbetçi.

	Bu iki test olmadan gruptaki tüm rol testleri, biri `gercek_yetki()`
	çağrısını kaldırdığında SESSİZCE boşalır ve yeşil kalır. Nöbetçi,
	kapının test ortamında gerçekten kapandığını kanıtlar.
	"""

	def test_bayrak_acikken_kapi_calismiyor(self):
		"""`in_test` açıkken `only_for` HİÇBİR ŞEY yapmaz — belgelenen gerçek."""
		self.assertTrue(frappe.flags.in_test, "test bayrağı beklenmedik biçimde kapalı")
		with kullanici("Guest"):
			# İstisna ATILMAMASI bekleniyor: kapı devre dışı.
			frappe.only_for(["System Manager"])

	def test_bayrak_inince_kapi_calisiyor(self):
		with gercek_yetki(), kullanici("Guest"), self.assertRaises(frappe.PermissionError):
			frappe.only_for(["System Manager"])

	def test_sarmalayici_bayragi_geri_veriyor(self):
		"""`in_test` sızarsa e-posta ve arka plan işleri de etkilenir."""
		with gercek_yetki():
			self.assertFalse(frappe.flags.in_test)
		self.assertTrue(frappe.flags.in_test)


class TestYoneticiUclariRolKapisi(FrappeTestCase):
	"""§14/§16 — yeni yönetici uçları satıcıya kapalı mı."""

	def setUp(self):
		self.user = _satici_kullanici()
		if not self.user:
			self.skipTest("Mağazalı satıcı kullanıcısı yok.")
		self.doc = dosya_ac(f"yetki-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def _reddedilmeli(self, cagri):
		with gercek_yetki(), kullanici(self.user), self.assertRaises(frappe.PermissionError):
			cagri()

	def test_toplu_gorunurluk_satiiciya_kapali(self):
		"""Görünürlük bir YAYIN kararı; satıcı ucunda bilerek yok."""
		self._reddedilmeli(
			lambda: media_admin.bulk_set_indexability(
				file_urls=[self.doc.file_url], visibility="Unlisted"
			)
		)

	def test_toplu_seo_yonetici_ucu_satiiciya_kapali(self):
		self._reddedilmeli(
			lambda: media_admin.bulk_set_media_seo(
				file_urls=[self.doc.file_url], values={"copyright_notice": "x"}
			)
		)

	def test_toplu_yeniden_adlandirma_yonetici_ucu_kapali(self):
		self._reddedilmeli(
			lambda: media_admin.bulk_rename_media(file_urls=[self.doc.file_url], pattern="a-{sira}")
		)

	def test_katalog_geneli_benzerlik_satiiciya_kapali(self):
		"""Kapsamsız benzerlik araması tüm katalogu tarar — yalnız yönetici."""
		self._reddedilmeli(lambda: media_admin.find_similar_media(file_url=self.doc.file_url))

	def test_locale_ezmesi_yazma_satiiciya_kapali(self):
		self._reddedilmeli(
			lambda: media_admin.set_media_locale_variant(
				file_url=self.doc.file_url, locale="en", variant_url="/files/x.png"
			)
		)


class TestKiraciIzolasyonu(FrappeTestCase):
	"""Satıcı, kendisine ait OLMAYAN adrese yazamaz/okuyamaz."""

	def setUp(self):
		self.user = _satici_kullanici()
		self.magaza = magaza_bul()
		if not (self.user and self.magaza):
			self.skipTest("Mağazalı satıcı kullanıcısı yok.")
		# Administrator'ın açtığı dosya: satıcının mağazasına AİT DEĞİL.
		self.yabanci = dosya_ac(f"yabanci-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.yabanci.name)

	def test_yabanci_dosyada_benzerlik_aramasi_reddedilir(self):
		"""Rakibin görselini sorup kendi eşlerini öğrenmek sızıntıdır.

		Red `DoesNotExistError` ile geliyor, `PermissionError` ile değil ve bu
		`ownership.assert_owns`ın BİLİNÇLİ tercihi: "yetkin yok" cevabı
		dosyanın VAR OLDUĞUNU doğrular ve saldırgana adres numaralandırma
		imkânı verir. "Bulunamadı" hiçbir şey söylemez. Test bu sözleşmeyi
		sabitliyor — biri "daha doğru hata" diye değiştirmesin.
		"""
		with kullanici(self.user), self.assertRaises(frappe.DoesNotExistError):
			seller_media.find_similar_media(file_url=self.yabanci.file_url)

	def test_yabanci_dosya_reddi_varligi_dogrulamaz(self):
		"""Var olan yabancı dosya ile HİÇ olmayan dosya AYNI hatayı vermeli."""
		with kullanici(self.user):
			for adres in (self.yabanci.file_url, f"/files/hic-yok-{TUZ}.png"):
				with self.assertRaises(frappe.DoesNotExistError, msg=adres):
					seller_media.find_similar_media(file_url=adres)

	def test_yabanci_dosya_toplu_yazmada_skipped_sayilir(self):
		"""Sessizce yazılmamalı AMA hata da olmamalı — `skipped` doğru cevap."""
		sonuc = bulk_ops.set_fields_many(
			[self.yabanci.file_url], {"creator": "rakip"}, store=self.magaza
		)
		self.assertEqual(sonuc["applied"], 0)
		self.assertEqual(sonuc["skipped"], 1)
		self.assertEqual(sonuc["failed"], [])

	def test_yabanci_dosya_toplu_adlandirmada_da_atlanir(self):
		sonuc = bulk_ops.rename_many([self.yabanci.file_url], "x-{sira}", store=self.magaza)
		self.assertEqual(sonuc["applied"], 0)
		self.assertEqual(sonuc["skipped"], 1)
		self.assertNotEqual(
			frappe.db.get_value("File", self.yabanci.name, "file_name"), "x-1.png"
		)

	def test_magaza_kapsami_benzerlik_adaylarini_daraltir(self):
		"""`similar._aday_hashler` mağazasız çağrıda geniş, mağazalıda dar."""
		genis_hash, _, _ = similar._aday_hashler(None)
		dar_hash, _, _ = similar._aday_hashler(self.magaza)
		self.assertLessEqual(
			len(dar_hash), len(genis_hash), "mağaza kapsamı aday kümesini büyütemez"
		)


class TestToplumUcYetkiYukseltmesiYok(FrappeTestCase):
	"""Toplu uçlar tekil uçtan DAHA GENİŞ yetki vermemeli.

	Bu sınıfın varlık sebebi: yeni bir toplu uç eklerken en kolay hata,
	tekil uçtaki bir yasağı (ör. `Private` geçişi) toplu yolda unutmaktır.
	"""

	def setUp(self):
		self.doc = dosya_ac(f"yukselt-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_private_yasagi_iki_yolda_da_var(self):
		with self.assertRaises(frappe.ValidationError):
			media_admin.set_media_indexability(file_url=self.doc.file_url, visibility="Private")
		with self.assertRaises(frappe.ValidationError):
			media_admin.bulk_set_indexability(
				file_urls=[self.doc.file_url], visibility="Private"
			)

	def test_robots_beyaz_listesi_iki_yolda_da_ayni(self):
		for cagri in (
			lambda: media_admin.set_media_indexability(
				file_url=self.doc.file_url, visibility="Public", robots_override="kotu"
			),
			lambda: media_admin.bulk_set_indexability(
				file_urls=[self.doc.file_url], visibility="Public", robots_override="kotu"
			),
		):
			with self.assertRaises(frappe.ValidationError):
				cagri()

	def test_kanonik_alan_tekilde_serbest_topluda_yasak(self):
		"""Kasıtlı asimetri: `canonical` her dosyada BENZERSİZ olmalı.

		Tekil uçta yazılabilir (tek dosyaya tek değer), toplu uçta yasak
		(200 dosyaya aynı kanonik adres = çakışma). Bu testin işi, asimetrinin
		KASITLI olduğunu kayda geçirmek — birileri "tutarsız" diye toplu
		yasağı kaldırmasın.
		"""
		media_admin.set_media_seo(
			file_url=self.doc.file_url, values={"canonical": "/urun/tekil"}
		)
		with self.assertRaises(frappe.ValidationError):
			bulk_ops.set_fields_many([self.doc.file_url], {"canonical": "/urun/toplu"})


class TestGuestKapisi(FrappeTestCase):
	"""Oturumsuz erişim yeni uçların hiçbirine giremez."""

	def setUp(self):
		self.doc = dosya_ac(f"guest-{TUZ}.png", png_uret())
		self.addCleanup(sil, "File", self.doc.name)

	def test_guest_satici_ucuna_giremez(self):
		with gercek_yetki(), kullanici("Guest"), self.assertRaises(Exception):
			seller_media.find_similar_media(file_url=self.doc.file_url)

	def test_guest_yonetici_ucuna_giremez(self):
		with gercek_yetki(), kullanici("Guest"), self.assertRaises(frappe.PermissionError):
			media_admin.bulk_rename_media(file_urls=[self.doc.file_url], pattern="a-{sira}")
