"""Duyuru şeridi yükü dört dili taşıyor mu — 21 Eyl 2026'da eklendi.

NEDEN: Vitrin dört dile açılırken yapılan kırma turunda bulundu
("aynı kusur kardeş modüllerde de var mı?"). `Header Notice` DocType'ı yalnız
`message_tr/_en` ve `link_text_tr/_en` taşıyordu; ön yüz de `lang === "en"`
diye soruyordu. Sonuç: Arapça/Rusça ziyaretçi duyuru şeridini Türkçe görüyordu
ve o şerit sitenin HER sayfasında çiziliyor.

Kusur o gün GİZLİYDİ — canlıda aktif duyuru yoktu (`notices: []`, ölçüldü
21 Eyl) ve LOCAL'de hiç kayıt yoktu. Biri duyuru yayınladığı gün görünür
olurdu. Bu dosya, eksikliğin ŞEMA düzeyinde tekrar etmesini engeller.

Kardeşi: `test_category_showcase_diller.py` (aynı desen, vitrin tarafı).
"""

import unittest

import frappe

from tradehub_core.api.header_notice import (
	CEVRILEBILIR_ALANLAR,
	DILLER,
	get_active_notices,
)

DOCTYPE = "Header Notice"


class TestDuyuruDilleri(unittest.TestCase):
	def test_dort_dil_tanimli(self):
		self.assertEqual(set(DILLER), {"tr", "en", "ar", "ru"})

	def test_doctype_her_dil_icin_kolon_tasiyor(self):
		"""Şema boşluğu buradan yakalanır — kusurun ta kendisi buydu."""
		mevcut = {f.fieldname for f in frappe.get_meta(DOCTYPE).fields}
		eksik = [
			f"{kok}_{dil}" for kok in CEVRILEBILIR_ALANLAR for dil in DILLER if f"{kok}_{dil}" not in mevcut
		]
		self.assertEqual(eksik, [], f"DocType'ta eksik dil kolonları: {eksik}")

	def test_yalniz_kaynak_dil_zorunlu(self):
		"""`message_tr` zorunlu kalmalı; diğer diller boş bırakılabilmeli.

		Aksi hâlde admin tek bir duyuruyu dört dilde yazmadan kaydedemez ve
		özellik kullanılmaz hâle gelir — eksik dil TR'ye düşsün diye tasarlandı.
		"""
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.get_field("message_tr").reqd, "message_tr zorunlu olmalı")
		for dil in ("en", "ar", "ru"):
			with self.subTest(dil=dil):
				self.assertFalse(
					bool(meta.get_field(f"message_{dil}").reqd),
					f"message_{dil} zorunlu OLMAMALI",
				)

	def test_yuk_her_duyuruda_her_dili_dondurur(self):
		frappe.cache.delete_value("header_notices_active")
		yuk = get_active_notices()
		self.assertIn("notices", yuk)
		for duyuru in yuk["notices"]:
			for kok in CEVRILEBILIR_ALANLAR:
				for dil in DILLER:
					with self.subTest(duyuru=duyuru["name"], alan=f"{kok}_{dil}"):
						self.assertIn(f"{kok}_{dil}", duyuru)
						self.assertIsInstance(duyuru[f"{kok}_{dil}"], str)

	def test_yeni_kayit_dort_dilde_yazilip_okunabiliyor(self):
		"""Uçtan uca: dört dilde yazılan bir duyuru yükte aynen dönüyor mu."""
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"message_tr": "Test duyurusu",
				"message_en": "Test notice",
				"message_ar": "إشعار تجريبي",
				"message_ru": "Тестовое уведомление",
				"link_text_ar": "التفاصيل",
				"is_active": 1,
				"sort_order": 999,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		try:
			frappe.cache.delete_value("header_notices_active")
			yuk = get_active_notices()
			kayit = next((n for n in yuk["notices"] if n["name"] == doc.name), None)
			self.assertIsNotNone(kayit, "eklenen duyuru yükte yok")
			self.assertEqual(kayit["message_ar"], "إشعار تجريبي")
			self.assertEqual(kayit["message_ru"], "Тестовое уведомление")
			self.assertEqual(kayit["link_text_ar"], "التفاصيل")
			# Doldurulmayan dil boş dize dönmeli, None değil — ön yüz .trim() çağırıyor.
			self.assertEqual(kayit["link_text_ru"], "")
		finally:
			frappe.delete_doc(DOCTYPE, doc.name, ignore_permissions=True, force=True)
			frappe.cache.delete_value("header_notices_active")


if __name__ == "__main__":
	unittest.main()
