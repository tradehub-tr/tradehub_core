"""Supplier Profile DocType'ını kaldır (Faz 2): tablo + DocType + Property Setter.

Verisi Admin Seller Profile'a taşınmıştı (migrate_supplier_profile_to_admin_seller_profile).
ASP'siz orphan satır varsa sessiz veri kaybı yerine migrate'i durdurur. Idempotent.
"""

import frappe
from frappe import _


def execute():
	dt = "Supplier Profile"
	if not frappe.db.exists("DocType", dt):
		return

	# Veri kaybı koruması: ASP'ye taşınmamış (orphan) satır varsa drop'u durdur.
	if frappe.db.table_exists("tabSupplier Profile"):
		orphan = frappe.db.sql(
			"""SELECT COUNT(*) FROM `tabSupplier Profile` sp
			   WHERE sp.user NOT IN
			   (SELECT user FROM `tabAdmin Seller Profile` WHERE user IS NOT NULL)"""
		)[0][0]
		if orphan:
			frappe.throw(
				_(
					"{0} adet Admin Seller Profile'ı olmayan Supplier Profile var. "
					"Drop iptal edildi — önce bu veriyi taşı."
				).format(orphan)
			)

	# Faz 1 Property Setter'larını temizle (delete_doc cascade'ine güvenme — explicit).
	frappe.db.delete("Property Setter", {"doc_type": dt})

	# Önce DocType'ı sil (on_trash tabloyu drop eder ama boş tabloyu yeniden de
	# oluşturabiliyor), sonra DROP TABLE'ı SON güvenlik ağı olarak çalıştır —
	# sıra ters olursa orphan boş `tabSupplier Profile` tablosu kalıyor.
	frappe.delete_doc("DocType", dt, force=1, ignore_missing=True)

	try:
		frappe.db.sql("DROP TABLE IF EXISTS `tabSupplier Profile`")
	except Exception as e:
		frappe.log_error(f"tablo drop edilemedi: {e}", "drop_supplier_profile")

	frappe.db.commit()
