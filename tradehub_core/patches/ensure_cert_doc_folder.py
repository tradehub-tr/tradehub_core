"""Home/sertifikalar ana klasörünü oluştur.

Satıcı sertifika belgeleri buraya yüklenir (per-seller alt klasörlerle).
Frappe'nin Folder = File doctype'ında is_folder=1 olan kayıt yapısı kullanılır.

Bu patch yalnızca ana klasörü oluşturur. Per-seller alt klasörleri
(`Home/sertifikalar/<seller_code>/`) ilk yüklemede dinamik oluşturulur.

Idempotent: var olan klasörü tekrar oluşturmaya çalışmaz.
"""

import frappe


def execute():
	if frappe.db.exists("File", {"name": "Home/sertifikalar", "is_folder": 1}):
		print("[ensure_cert_doc_folder] Home/sertifikalar already exists")
		return

	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": "sertifikalar",
			"is_folder": 1,
			"folder": "Home",
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	print(f"[ensure_cert_doc_folder] Created Home/sertifikalar ({doc.name})")
