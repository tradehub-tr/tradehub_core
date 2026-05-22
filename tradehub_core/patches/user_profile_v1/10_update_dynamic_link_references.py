"""Patch 10: Frappe core tablolarında Buyer/Seller Profile reference_doctype
referanslarını User Profile'a güncelle. Frappe v15'te kolon adları farklı."""

import frappe


def execute():
	updates = [
		("tabComment", "reference_doctype"),
		("tabCommunication", "reference_doctype"),
		("tabActivity Log", "reference_doctype"),
		("tabVersion", "ref_doctype"),  # v15'te ref_doctype
		("tabFile", "attached_to_doctype"),  # v15'te farklı
		("tabToDo", "reference_type"),
		("tabTag Link", "document_type"),
		("tabDocShare", "share_doctype"),
		("tabAssignment Rule", "document_type"),
		("tabEmail Queue Recipient", "link_doctype"),
		("tabNotification Log", "document_type"),
	]

	results = {}
	for table, col in updates:
		try:
			# Önce tablo + kolon kontrolü
			frappe.db.sql(f"SELECT 1 FROM `{table}` LIMIT 1")
			# has_column tabname argümanı bekler değil DocType; SQL ile kontrol
			col_check = frappe.db.sql(f"""
				SELECT COUNT(*) FROM information_schema.columns
				WHERE table_schema = DATABASE()
				  AND table_name = '{table.replace("`", "")}'
				  AND column_name = '{col}'
			""")
			if not col_check or col_check[0][0] == 0:
				results[f"{table}.{col}"] = "NO COLUMN"
				continue

			frappe.db.sql(f"""
				UPDATE `{table}`
				SET `{col}` = 'User Profile'
				WHERE `{col}` IN ('Buyer Profile', 'Seller Profile')
			""")
			results[f"{table}.{col}"] = "OK"
		except Exception as exc:
			results[f"{table}.{col}"] = f"ERR: {exc}"

	frappe.db.commit()
	frappe.log_error(
		title="Patch 10: Dynamic Link references updated",
		message=str(results),
	)
