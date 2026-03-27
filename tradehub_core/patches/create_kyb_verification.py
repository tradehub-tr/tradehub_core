import frappe


SELLER_TYPE_MAP = {
	"Individual": "Şahıs",
	"Business": "Limited Şirket",
	"Enterprise": "Anonim Şirket",
}


def execute():
	"""Create KYB Verification doctype, add kyb_status to Seller Profile,
	and auto-create KYB records for existing approved sellers."""
	frappe.reload_doc("tradehub_core", "doctype", "kyb_verification", force=True)
	frappe.reload_doc("tradehub_core", "doctype", "seller_profile", force=True)

	# Auto-create KYB records for existing sellers
	sellers = frappe.get_all(
		"Seller Profile",
		filters={"status": "Active"},
		fields=["user", "seller_name", "seller_type", "business_name",
		        "tax_id_type", "tax_id", "tax_office"],
	)

	for sp in sellers:
		if frappe.db.exists("KYB Verification", {"user": sp.user}):
			continue
		# Skip if user doesn't exist in User doctype
		if not frappe.db.exists("User", sp.user):
			continue

		kyb = frappe.new_doc("KYB Verification")
		kyb.user = sp.user
		kyb.owner = sp.user
		kyb.status = "Pending"
		kyb.company_title = sp.business_name or sp.seller_name or ""
		kyb.business_type = SELLER_TYPE_MAP.get(sp.seller_type, "") or sp.seller_type or ""
		kyb.authorized_person = sp.seller_name or ""
		kyb.tax_id_type = sp.tax_id_type or "TCKN"
		kyb.tax_id = sp.tax_id or ""
		kyb.tax_office = sp.tax_office or ""
		kyb.flags.ignore_permissions = True
		kyb.insert(ignore_permissions=True)

		frappe.db.set_value("Seller Profile", {"user": sp.user}, "kyb_status", "Pending")

	frappe.db.commit()
