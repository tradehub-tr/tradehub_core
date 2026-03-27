import frappe


def execute():
	"""Copy tax, address, and bank fields from Seller Application to Seller Profile.

	Needed because these fields were previously only stored on the application.
	"""
	frappe.reload_doc("tradehub_core", "doctype", "seller_profile", force=True)

	# Verify columns exist before proceeding
	table_columns = frappe.db.get_table_columns("Seller Profile")
	if "account_holder_name" not in table_columns:
		# reload_doc didn't create the columns — skip, they'll be created by migrate
		return

	profiles = frappe.get_all(
		"Seller Profile",
		filters={"application": ["is", "set"]},
		fields=["name", "application"],
	)

	new_fields = [
		"tax_id_type", "tax_office", "address_line_1",
		"city", "bank_name", "iban", "account_holder_name",
	]

	for profile in profiles:
		app_data = frappe.db.get_value(
			"Seller Application", profile.application,
			new_fields, as_dict=True,
		)
		if not app_data:
			continue

		for field in new_fields:
			value = app_data.get(field)
			if value:
				frappe.db.set_value("Seller Profile", profile.name, field, value)

	frappe.db.commit()
