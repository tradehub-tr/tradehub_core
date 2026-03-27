import frappe


def execute():
	"""Fix owner field on all user-facing DocType records.

	Records created by system (ignore_permissions) or admin had owner set to
	Administrator/Guest instead of the actual user. This breaks if_owner
	permission filtering.
	"""
	# Fix Seller Profiles — owner should match user field, backfill member_id
	for p in frappe.get_all("Seller Profile", fields=["name", "user", "owner", "member_id"]):
		if p.owner != p.user:
			frappe.db.set_value("Seller Profile", p.name, "owner", p.user)
		if not p.member_id:
			# Try to get member_id from Buyer Profile or Seller Application
			mid = (
				frappe.db.get_value("Buyer Profile", {"user": p.user}, "member_id")
				or frappe.db.get_value("Seller Application", {"applicant_user": p.user}, "member_id")
			)
			if mid:
				frappe.db.set_value("Seller Profile", p.name, "member_id", mid)

	# Fix Buyer Profiles — owner should match user field
	for p in frappe.get_all("Buyer Profile", fields=["name", "user", "owner"]):
		if p.owner != p.user:
			frappe.db.set_value("Buyer Profile", p.name, "owner", p.user)

	# Fix Seller Applications — owner should match applicant_user field
	for p in frappe.get_all("Seller Application", fields=["name", "applicant_user", "owner"]):
		if p.owner != p.applicant_user:
			frappe.db.set_value("Seller Application", p.name, "owner", p.applicant_user)

	# Build seller code → user email mapping from Admin Seller Profile
	seller_map = {}
	for asp in frappe.get_all("Admin Seller Profile", fields=["name", "user"]):
		seller_map[asp.name] = asp.user

	# Fix Seller Category, Seller Inquiry, Seller Product, Seller Review, Seller Balance
	# These have a "seller" field pointing to Admin Seller Profile name
	for doctype in ["Seller Category", "Seller Inquiry", "Seller Product",
	                "Seller Review", "Seller Balance"]:
		try:
			records = frappe.get_all(doctype, fields=["name", "seller", "owner"])
		except Exception:
			continue

		for r in records:
			expected_owner = seller_map.get(r.seller, r.owner)
			if r.owner != expected_owner:
				frappe.db.set_value(doctype, r.name, "owner", expected_owner)

	frappe.db.commit()
