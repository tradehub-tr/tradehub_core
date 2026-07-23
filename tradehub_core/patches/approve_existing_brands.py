import frappe


def execute():
	if not frappe.db.table_exists("tabBrand"):
		return
	columns = frappe.db.get_table_columns("Brand")
	if "status" not in columns:
		return

	rows = frappe.db.sql(
		"""
		SELECT name FROM `tabBrand`
		WHERE status = 'Pending Approval'
		  AND creation < %(cutoff)s
		""",
		{"cutoff": "2026-04-14 00:00:00"},
		as_dict=True,
	)
	if not rows:
		return

	for r in rows:
		frappe.db.set_value(
			"Brand",
			r["name"],
			{
				"status": "Approved",
				"reviewed_by": "Administrator",
				"reviewed_at": frappe.utils.now_datetime(),
			},
			update_modified=False,
		)
	frappe.db.commit()
	frappe.logger("patches").info(f"[approve_existing_brands] {len(rows)} mevcut marka Approved olarak işaretlendi.")
