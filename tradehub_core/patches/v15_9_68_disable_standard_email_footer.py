"""Platform e-postalarında ERPNext'in "Sent via ERPNext" standart altbilgisini kapatır.

iStoc e-postaları kendi altbilgisini (tercih bağlantısı, zorunlu/seçmeli bilgisi) taşır; ERPNext
altbilgisi marka dışıdır. Patch bir kez çalışır: yönetici sonradan System Settings > "Disable Standard
Email Footer" kutusunu kaldırırsa tercih ezilmez. Aynı değer System Settings alanına ve Frappe'nin
okuduğu varsayılana (`frappe.db.get_default`) birlikte yazılır.
"""

import frappe


def execute():
	if str(frappe.db.get_default("disable_standard_email_footer") or "0") == "1":
		return
	frappe.db.set_single_value("System Settings", "disable_standard_email_footer", 1)
	frappe.db.set_default("disable_standard_email_footer", "1")
