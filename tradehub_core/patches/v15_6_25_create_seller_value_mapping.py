# Copyright (c) 2026, TradeHub Team and contributors

"""Değer Eslestirmelerim — Seller Value Mapping + Row DocType kurulumu.

post_model_sync asamasinda calisir: bench migrate DocType JSON'larini zaten
sync eder; bu patch idempotent reload-doc + seller_profile/target_field index'i
garanti eder.
"""

import frappe


def execute():
	# DocType JSON'lari migrate sirasinda yuklenir; reload-doc tekrar cagrisi
	# idempotent (var olan schema'yi yeniden uygular, kirilmaz).
	frappe.reload_doc("tradehub_core", "doctype", "seller_value_mapping_row")
	frappe.reload_doc("tradehub_core", "doctype", "seller_value_mapping")

	# seller_profile + target_field uzerinde sik filtre (runner value_map kurarken
	# ve list_value_mappings'te) — composite index ekle (idempotent).
	if frappe.db.table_exists("Seller Value Mapping"):
		try:
			frappe.db.add_index("Seller Value Mapping", ["seller_profile", "target_field"])
		except Exception as exc:
			# Index zaten varsa MariaDB hata verir; idempotent olsun diye yut + logla.
			frappe.log_error(
				f"Seller Value Mapping index skip: {exc}",
				"v15_6_25_create_seller_value_mapping",
			)

	frappe.db.commit()
