import frappe
from frappe import _


SELLER_TYPE_MAP = {
	"Individual": "Şahıs",
	"Business": "Limited Şirket",
	"Enterprise": "Anonim Şirket",
}


def _get_seller_data(user: str) -> dict:
	"""Fetch existing seller data to pre-fill KYB form."""
	sp = frappe.db.get_value(
		"Seller Profile", {"user": user},
		["seller_name", "seller_type", "business_name", "tax_id",
		 "tax_id_type", "tax_office"],
		as_dict=True,
	)
	if not sp:
		return {}
	return {
		"company_title": sp.business_name or "",
		"business_type": SELLER_TYPE_MAP.get(sp.seller_type, "") or sp.seller_type or "",
		"authorized_person": sp.seller_name or "",
		"tax_id_type": sp.tax_id_type or "TCKN",
		"tax_id": sp.tax_id or "",
		"tax_office": sp.tax_office or "",
	}


@frappe.whitelist(methods=["GET"])
def get_kyb_status():
	"""Return KYB verification status and data for the current user.

	If no KYB record exists, auto-creates one pre-filled from Seller Profile.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	# Check if seller
	if not frappe.db.exists("Seller Profile", {"user": user}):
		return {"exists": False, "status": None, "message": "Not a seller"}

	existing = frappe.db.get_value("KYB Verification", {"user": user}, "name")

	if not existing:
		# Auto-create KYB record pre-filled from Seller Profile
		seller_data = _get_seller_data(user)
		doc = frappe.new_doc("KYB Verification")
		doc.user = user
		doc.owner = user
		doc.status = "Pending"
		for field, value in seller_data.items():
			doc.set(field, value)
		doc.flags.ignore_permissions = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		existing = doc.name

	kyb = frappe.db.get_value(
		"KYB Verification",
		existing,
		["name", "status", "company_title", "business_type", "authorized_person",
		 "tax_id_type", "tax_id", "tax_office", "trade_registry_number",
		 "rejection_reason", "verified_at"],
		as_dict=True,
	)

	return {
		"exists": True,
		"name": kyb.name,
		"status": kyb.status,
		"company_title": kyb.company_title or "",
		"business_type": kyb.business_type or "",
		"authorized_person": kyb.authorized_person or "",
		"tax_id_type": kyb.tax_id_type or "",
		"tax_id": kyb.tax_id or "",
		"tax_office": kyb.tax_office or "",
		"trade_registry_number": kyb.trade_registry_number or "",
		"rejection_reason": kyb.rejection_reason if kyb.status == "Rejected" else None,
		"verified_at": kyb.verified_at,
	}


@frappe.whitelist(methods=["POST"])
def submit_kyb_documents(
	company_title: str,
	business_type: str = "",
	authorized_person: str = "",
	tax_id_type: str = "",
	tax_id: str = "",
	tax_office: str = "",
	trade_registry_number: str = "",
	identity_document: str = "",
	imza_sirkuleri: str = "",
	ticaret_sicil_gazetesi: str = "",
	faaliyet_belgesi: str = "",
	vergi_levhasi: str = "",
	document_expiry_date: str = "",
):
	"""Update KYB documents. Auto-creates if not exists."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	if not company_title:
		frappe.throw(_("Company title is required."), frappe.ValidationError)

	existing = frappe.db.get_value("KYB Verification", {"user": user}, "name")

	# permlevel 1 fields (tax_id_type, tax_id, tax_office, business_type)
	# are NOT accepted from seller — they come from Seller Profile at creation.
	# Only admin can change them via Frappe Desk.
	field_data = {
		"company_title": company_title,
		"authorized_person": authorized_person,
		"trade_registry_number": trade_registry_number,
		"identity_document": identity_document,
		"imza_sirkuleri": imza_sirkuleri,
		"ticaret_sicil_gazetesi": ticaret_sicil_gazetesi,
		"faaliyet_belgesi": faaliyet_belgesi,
		"vergi_levhasi": vergi_levhasi,
		"document_expiry_date": document_expiry_date or None,
	}

	if existing:
		# Update via doc.save to trigger validations
		doc = frappe.get_doc("KYB Verification", existing)
		for field, value in field_data.items():
			doc.set(field, value)
		doc.status = "Pending"
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return {"success": True, "name": existing, "status": "Pending", "updated": True}
	else:
		doc = frappe.new_doc("KYB Verification")
		doc.user = user
		doc.owner = user
		doc.status = "Pending"
		for field, value in field_data.items():
			doc.set(field, value)
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		return {"success": True, "name": doc.name, "status": "Pending", "updated": False}


@frappe.whitelist(methods=["POST"])
def review_kyb(kyb_name: str, action: str, rejection_reason: str = ""):
	"""Admin action: approve or reject KYB verification."""
	user = frappe.session.user
	roles = frappe.get_roles(user)

	if "System Manager" not in roles and "Marketplace Admin" not in roles:
		frappe.throw(_("Not authorized."), frappe.PermissionError)

	if action not in ("Verified", "Rejected", "Under Review"):
		frappe.throw(_("Invalid action."), frappe.ValidationError)

	doc = frappe.get_doc("KYB Verification", kyb_name)
	doc.status = action
	if action == "Rejected":
		doc.rejection_reason = rejection_reason
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True, "status": doc.status}
