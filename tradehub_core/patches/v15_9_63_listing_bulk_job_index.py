"""`Listing.created_by_bulk_job`'a indeks (MOGEM-981).

Job temizliği her job için "bağlı ilan var mı" diye, panelin kaynak süzgeci de her listede bu
kolonla arar. İndeks yokken her arama ilan tablosunun tamamını okur; ilan sayısı büyüdükçe
temizlik görevi süresine sığmaz. Alan Custom Field olduğu için ayar oradan verilir ki sonraki
migrate'ler indeksi korusun. İdempotent.
"""

import frappe

FIELD = "Listing-created_by_bulk_job"


def execute() -> None:
	if not frappe.db.exists("Custom Field", FIELD):
		return
	field = frappe.get_doc("Custom Field", FIELD)
	if not field.search_index:
		field.search_index = 1
		field.save(ignore_permissions=True)
	if not frappe.db.sql("show index from `tabListing` where Column_name = 'created_by_bulk_job'"):
		frappe.db.add_index("Listing", ["created_by_bulk_job"])
