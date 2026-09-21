"""Vitrin yükü dört dili taşıyor mu — 21 Eyl 2026'da eklendi.

NEDEN: Ölçüldü (17 Eyl 2026, alpha'da GERÇEK Suudi Arabistan IP'siyle, temiz
oturum): otomatik dil seçimi sayfayı Arapça ve RTL açıyordu ama vitrin bölümü
Türkçe kalıyordu. Kök neden çeviri hattında DEĞİL, ŞEMADAYDI — `Category
Showcase Tile` DocType'ı yalnız `_tr`/`_en` kolonu taşıyordu, `_ar`/`_ru` hiç
yoktu. Kanıt: `docs/ulke-turu-kanit/alpha/01-SA-anasayfa.png`.

Bu dosya, eksikliğin ŞEMA düzeyinde tekrar etmesini engeller: alan listesi ve
yük `DILLER` demetinden türer, yani beşinci bir dil eklendiğinde hiçbir alan
unutulamaz. Test o türetmeyi kilitler.
"""

import unittest

import frappe

from tradehub_core.api.category_showcase import (
	CEVRILEBILIR_ALANLAR,
	DILLER,
	get_active_tiles,
)

DOCTYPE_KUTU = "Category Showcase Tile"
DOCTYPE_AYAR = "Category Showcase Settings"


class TestVitrinDilleri(unittest.TestCase):
	def test_dort_dil_tanimli(self):
		self.assertEqual(set(DILLER), {"tr", "en", "ar", "ru"})

	def test_doctype_her_dil_icin_kolon_tasiyor(self):
		"""Şema boşluğu buradan yakalanır — kusurun ta kendisi buydu."""
		meta = frappe.get_meta(DOCTYPE_KUTU)
		mevcut = {f.fieldname for f in meta.fields}
		eksik = [
			f"{kok}_{dil}" for kok in CEVRILEBILIR_ALANLAR for dil in DILLER if f"{kok}_{dil}" not in mevcut
		]
		self.assertEqual(eksik, [], f"DocType'ta eksik dil kolonları: {eksik}")

	def test_ayarlar_her_dil_icin_bolum_basligi_tasiyor(self):
		mevcut = {f.fieldname for f in frappe.get_meta(DOCTYPE_AYAR).fields}
		eksik = [f"section_title_{dil}" for dil in DILLER if f"section_title_{dil}" not in mevcut]
		self.assertEqual(eksik, [], f"Ayarlarda eksik başlık dili: {eksik}")

	def test_yuk_her_kutuda_her_dili_dondurur(self):
		frappe.cache.delete_value("category_showcase_active")
		yuk = get_active_tiles()
		self.assertIn("section_title", yuk)
		for dil in DILLER:
			self.assertIn(dil, yuk["section_title"], f"bölüm başlığında {dil} yok")
		for kutu in yuk.get("tiles", []):
			for kok in CEVRILEBILIR_ALANLAR:
				for dil in DILLER:
					with self.subTest(kutu=kutu["name"], alan=f"{kok}_{dil}"):
						self.assertIn(f"{kok}_{dil}", kutu)

	def test_yuk_hicbir_dilde_None_dondurmez(self):
		"""Ön yüz `.trim()` çağırıyor; None gelirse ekran patlar."""
		frappe.cache.delete_value("category_showcase_active")
		yuk = get_active_tiles()
		for kutu in yuk.get("tiles", []):
			for kok in CEVRILEBILIR_ALANLAR:
				for dil in DILLER:
					self.assertIsInstance(kutu[f"{kok}_{dil}"], str)


if __name__ == "__main__":
	unittest.main()
