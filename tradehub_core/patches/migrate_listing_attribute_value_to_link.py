"""
Listing Attribute Value child tablosundaki attribute_name alanını
Data'dan Link'e (Product Attribute) migrate eder. Var olmayan
attribute isimleri için Product Attribute kayıtlarını otomatik
oluşturur. Idempotent.
"""

import frappe


def execute():
	if not frappe.db.table_exists("Product Attribute"):
		return
	if not frappe.db.table_exists("Listing Attribute Value"):
		return

	columns = frappe.db.sql("DESC `tabListing Attribute Value`", as_dict=True)
	col_names = {c["Field"] for c in columns}
	if "attribute" not in col_names:
		return

	legacy_col = "attribute_name" if "attribute_name" in col_names else None

	if legacy_col:
		rows = frappe.db.sql(
			f"""
			SELECT name, `{legacy_col}` AS legacy_name, attribute
			FROM `tabListing Attribute Value`
			WHERE `{legacy_col}` IS NOT NULL AND `{legacy_col}` != ''
			""",
			as_dict=True,
		)
	else:
		rows = []

	existing_attrs = {
		a.name: a
		for a in frappe.db.get_all(
			"Product Attribute",
			fields=["name", "attribute_label", "attribute_code"],
		)
	}
	label_to_code = {(a.attribute_label or "").strip().lower(): a.name for a in existing_attrs.values()}

	migrated = 0
	auto_created = 0
	for row in rows:
		if row.attribute:
			continue
		legacy = (row.legacy_name or "").strip()
		if not legacy:
			continue

		key = legacy.lower()
		target = label_to_code.get(key)
		if not target:
			code = _slugify_attr_code(legacy)
			if not code:
				continue
			if frappe.db.exists("Product Attribute", code):
				target = code
			else:
				try:
					doc = frappe.new_doc("Product Attribute")
					doc.attribute_code = code
					doc.attribute_label = legacy
					doc.data_type = "Text"
					doc.is_active = 1
					doc.flags.ignore_permissions = True
					doc.flags.ignore_mandatory = True
					doc.insert(ignore_if_duplicate=True)
					target = code
					label_to_code[key] = code
					auto_created += 1
				except Exception:
					frappe.log_error(
						title="migrate_listing_attribute_value_to_link",
						message=frappe.get_traceback(),
					)
					continue

		frappe.db.set_value(
			"Listing Attribute Value",
			row.name,
			"attribute",
			target,
			update_modified=False,
		)
		migrated += 1

	frappe.db.commit()
	print(
		f"[migrate_listing_attribute_value_to_link] Migrated {migrated} rows, "
		f"auto-created {auto_created} Product Attribute records."
	)


def _slugify_attr_code(name: str) -> str:
	base = frappe.scrub(name).upper().replace("_", "-")
	base = "".join(ch for ch in base if ch.isalnum() or ch == "-")
	return base[:140]
