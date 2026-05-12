"""Faz 2 — yeni alanların default değerlerini güvenli şekilde initialize eder.

Migrate sonrası schema sync ile alanlar oluşur, ama eski kayıtlarda null/0
olmayan değerler bulunabilir. Bu patch idempotent olarak baseline'ı sağlar.
"""

import frappe


def execute():
	cols = frappe.db.get_table_columns("Listing")
	zero_cols = [
		"quality_avg",
		"service_avg",
		"shipping_avg",
		"spec_match_avg",
		"documentation_avg",
	]
	updates = []
	for c in zero_cols:
		if c in cols:
			updates.append(f"{c} = COALESCE({c}, 0)")
	if updates:
		frappe.db.sql("UPDATE `tabListing` SET " + ", ".join(updates))

	# Listing Review cache field'ları
	lr_cols = frappe.db.get_table_columns("Listing Review")
	lr_updates = []
	for c in ["helpful_count", "not_helpful_count", "abuse_report_count"]:
		if c in lr_cols:
			lr_updates.append(f"{c} = COALESCE({c}, 0)")
	if lr_updates:
		frappe.db.sql("UPDATE `tabListing Review` SET " + ", ".join(lr_updates))

	# Approved review'ları yeniden hesaplattır → 5 boyut ortalaması güncellenir
	if frappe.db.table_exists("tabListing Review"):
		from tradehub_core.api.review import recompute_listing_rating

		listings = frappe.db.sql_list(
			"SELECT DISTINCT listing FROM `tabListing Review` WHERE status='Approved' AND listing IS NOT NULL"
		)
		for ln in listings:
			try:
				recompute_listing_rating(ln)
			except Exception:
				frappe.log_error(
					title="init_review_phase2_fields",
					message=f"Listing {ln} aspect recompute failed",
				)

	frappe.db.commit()
