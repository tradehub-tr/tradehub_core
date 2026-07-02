"""Product Type Required Attribute child DocType'ını kaldır (Mini-PIM Faz 0).

ARGE kararı (Mini-PIM-ARGE-Raporu §3.2 / Karar #5): Product Type ikinci bir
zorunlu-attribute ekseni olmasın. Zorunluluk tek kaynaktan (kategori → Attribute
Set Category Map) gelecek. `required_attributes` child'ı Product Type JSON'dan
kaldırıldı; bu patch orphan child DocType + tablosunu temizler.

İdempotent: DocType yoksa no-op.
"""

import frappe


def execute():
	dt = "Product Type Required Attribute"
	if not frappe.db.exists("DocType", dt):
		return

	# Önce DocType'ı sil (on_trash tabloyu drop eder ama boş tabloyu yeniden
	# oluşturabiliyor), sonra DROP TABLE'ı son güvenlik ağı olarak çalıştır.
	frappe.delete_doc("DocType", dt, force=1, ignore_missing=True)

	try:
		frappe.db.sql(f"DROP TABLE IF EXISTS `tab{dt}`")
	except Exception as e:
		frappe.log_error(f"tablo drop edilemedi: {e}", "drop_product_type_required_attribute")

	frappe.db.commit()
