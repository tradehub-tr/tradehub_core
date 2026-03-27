import hashlib
import re

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit


def _generate_member_id(email: str, creation) -> str:
	"""Generate a deterministic, unique member ID from email + creation timestamp."""
	raw = f"{email}:{creation}"
	digest = hashlib.sha256(raw.encode()).hexdigest()[:8].upper()
	return f"TH-{digest}"


@frappe.whitelist(methods=["GET"])
def get_select_options(doctype: str):
	"""Return all Select field options for a given DocType.

	Used by frontend to dynamically populate dropdowns.
	"""
	allowed = {"Buyer Profile", "Seller Profile", "KYB Verification"}
	if doctype not in allowed:
		frappe.throw(_("Not allowed."), frappe.PermissionError)

	meta = frappe.get_meta(doctype)
	result = {}
	for f in meta.fields:
		if f.fieldtype == "Select" and f.options:
			result[f.fieldname] = [o for o in f.options.split("\n") if o]
	return result


@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=30, seconds=300)
def check_email_exists(email: str):
	"""Check whether an email is already registered as a User.

	Returns exists=True and disabled=True if the user account was deactivated.
	"""
	email = (email or "").strip().lower()
	user_data = frappe.db.get_value("User", email, ["name", "enabled"], as_dict=True)
	if not user_data:
		return {"success": True, "exists": False, "disabled": False}

	disabled = not user_data.enabled
	return {"success": True, "exists": True, "disabled": disabled}


@frappe.whitelist(allow_guest=True, methods=["GET"])
def get_session_user():
	"""Return current session user info with role flags.

	Returns logged_in: false for guests instead of throwing 403.
	"""
	if frappe.session.user == "Guest":
		return {"logged_in": False, "user": None}

	user_data = frappe.db.get_value(
		"User",
		frappe.session.user,
		["email", "full_name", "first_name", "last_name", "creation"],
		as_dict=True,
	)

	if not user_data:
		return {"logged_in": False, "user": None}

	roles = frappe.get_roles(frappe.session.user)

	is_admin = "System Manager" in roles or "Administrator" in roles
	is_buyer = "Buyer" in roles
	is_seller = "Seller" in roles or bool(
		frappe.db.exists("Seller Profile", {"user": frappe.session.user})
	)

	has_seller_profile = bool(
		frappe.db.exists(
			"Seller Profile",
			{"user": frappe.session.user, "status": "Active"},
		)
	)

	# Seller Application status (exact value for frontend routing)
	seller_application_status = (
		frappe.db.get_value(
			"Seller Application",
			{"applicant_user": frappe.session.user},
			"status",
		)
		or None
	)

	pending_seller_application = seller_application_status in (
		"Draft", "Submitted", "Under Review",
	)

	rejected_seller_application = seller_application_status == "Rejected"

	seller_profile = (
		frappe.db.get_value(
			"Seller Profile", {"user": frappe.session.user}, "name"
		)
		or None
	)

	# Admin Seller Profile — satıcının mağaza profili (filtreleme için seller_code gerekli)
	admin_seller_profile = None
	if is_seller:
		try:
			asp = frappe.db.get_value(
				"Admin Seller Profile",
				{"seller_profile": frappe.session.user},
				["name", "seller_code"],
				as_dict=True,
			)
			if asp:
				admin_seller_profile = {
					"name": asp.name,
					"seller_code": asp.seller_code or asp.name,
				}
		except Exception:
			pass

	member_id = _generate_member_id(user_data.email, user_data.creation)

	# KYB verification status
	kyb_status = (
		frappe.db.get_value(
			"KYB Verification",
			{"user": frappe.session.user},
			"status",
		)
		or None
	)

	return {
		"logged_in": True,
		"user": {
			"email": user_data.email,
			"full_name": user_data.full_name,
			"first_name": user_data.first_name or "",
			"last_name": user_data.last_name or "",
			"member_id": member_id,
			"roles": roles,
			"is_admin": is_admin,
			"is_seller": is_seller,
			"is_buyer": is_buyer,
			"has_seller_profile": has_seller_profile,
			"pending_seller_application": pending_seller_application,
			"rejected_seller_application": rejected_seller_application,
			"seller_application_status": seller_application_status,
			"seller_profile": seller_profile,
			"admin_seller_profile": admin_seller_profile,
			"kyb_status": kyb_status,
		},
	}


@frappe.whitelist(methods=["GET"])
def get_user_profile():
	"""Return detailed profile data for the currently logged-in user.

	Detects account type (buyer/seller) and returns role-specific fields.
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	user_data = frappe.db.get_value(
		"User",
		user,
		["email", "full_name", "first_name", "last_name", "creation", "phone"],
		as_dict=True,
	)

	if not user_data:
		frappe.throw(_("User not found."), frappe.DoesNotExistError)

	roles = frappe.get_roles(user)

	# Detect approved seller: has Seller role AND active Seller Profile
	# Pending applications don't make a user a "seller" for profile purposes
	is_seller = (
		"Seller" in roles
		and frappe.db.exists("Seller Profile", {"user": user})
	)

	# Read member_id from DB; fallback to computed value for legacy users
	member_id = (
		frappe.db.get_value("Buyer Profile", {"user": user}, "member_id")
		or frappe.db.get_value("Seller Profile", {"user": user}, "member_id")
		or frappe.db.get_value("Seller Application", {"applicant_user": user}, "member_id")
		or _generate_member_id(user_data.email, user_data.creation)
	)

	base = {
		"member_id": member_id,
		"first_name": user_data.first_name or "",
		"last_name": user_data.last_name or "",
		"full_name": user_data.full_name or "",
		"email": user_data.email,
		"phone": user_data.phone or "",
	}

	# ── Seller ──
	if is_seller:
		base["account_type"] = "seller"

		# Try Seller Profile first (approved sellers)
		sp = frappe.db.get_value(
			"Seller Profile", {"user": user},
			["seller_name", "seller_type", "business_name", "tax_id",
			 "contact_phone", "country", "status",
			 "tax_id_type", "tax_office", "address_line_1", "city",
			 "bank_name", "iban", "account_holder_name",
			 "avatar", "website", "job_title", "year_established",
			 "employee_count", "about_us", "selling_platforms", "postal_code",
			 "industry_preferences", "sourcing_frequency", "annual_spending"],
			as_dict=True,
		)
		if sp:
			base.update({
				"seller_type": sp.seller_type or "",
				"business_name": sp.business_name or "",
				"tax_id": sp.tax_id or "",
				"phone": sp.contact_phone or user_data.phone or "",
				"country": sp.country or "",
				"seller_status": sp.status or "",
				"tax_id_type": sp.tax_id_type or "",
				"tax_office": sp.tax_office or "",
				"address": sp.address_line_1 or "",
				"city": sp.city or "",
				"bank_name": sp.bank_name or "",
				"iban": sp.iban or "",
				"account_holder_name": sp.account_holder_name or "",
				"avatar": sp.avatar or "",
				"website": sp.website or "",
				"job_title": sp.job_title or "",
				"year_established": sp.year_established or "",
				"employee_count": sp.employee_count or "",
				"about_us": sp.about_us or "",
				"selling_platforms": sp.selling_platforms or "",
				"postal_code": sp.postal_code or "",
				"industry_preferences": sp.industry_preferences or "",
				"sourcing_frequency": sp.sourcing_frequency or "",
				"annual_spending": sp.annual_spending or "",
			})
			return base

		# Fallback: Seller Application only (pending sellers)
		sa = frappe.db.get_value(
			"Seller Application", {"applicant_user": user},
			["seller_type", "business_name", "contact_phone", "tax_id",
			 "tax_id_type", "tax_office", "address_line_1", "city",
			 "country", "bank_name", "iban", "account_holder_name", "status"],
			as_dict=True,
		)
		if sa:
			base.update({
				"seller_type": sa.seller_type or "",
				"business_name": sa.business_name or "",
				"tax_id": sa.tax_id or "",
				"tax_id_type": sa.tax_id_type or "",
				"tax_office": sa.tax_office or "",
				"address": sa.address_line_1 or "",
				"city": sa.city or "",
				"phone": sa.contact_phone or user_data.phone or "",
				"country": sa.country or "",
				"bank_name": sa.bank_name or "",
				"iban": sa.iban or "",
				"account_holder_name": sa.account_holder_name or "",
				"application_status": sa.status or "",
			})
		return base

	# ── Buyer (default) ──
	base["account_type"] = "buyer"
	buyer_data = frappe.db.get_value(
		"Buyer Profile", {"user": user},
		["country", "phone", "email_verified", "avatar",
		 "business_type", "company_name", "address", "job_title", "website",
		 "selling_platforms", "year_established", "employee_count", "about_us",
		 "industry_preferences", "sourcing_frequency", "annual_spending",
		 "city", "postal_code"],
		as_dict=True,
	) or {}
	base.update({
		"email_verified": bool(buyer_data.get("email_verified")),
		"phone": user_data.phone or buyer_data.get("phone", "") or "",
		"country": buyer_data.get("country", "") or "",
		"avatar": buyer_data.get("avatar", "") or "",
		"business_type": buyer_data.get("business_type", "") or "",
		"company_name": buyer_data.get("company_name", "") or "",
		"address": buyer_data.get("address", "") or "",
		"job_title": buyer_data.get("job_title", "") or "",
		"website": buyer_data.get("website", "") or "",
		"selling_platforms": buyer_data.get("selling_platforms", "") or "",
		"year_established": buyer_data.get("year_established", "") or "",
		"employee_count": buyer_data.get("employee_count", "") or "",
		"about_us": buyer_data.get("about_us", "") or "",
		"industry_preferences": buyer_data.get("industry_preferences", "") or "",
		"sourcing_frequency": buyer_data.get("sourcing_frequency", "") or "",
		"annual_spending": buyer_data.get("annual_spending", "") or "",
		"city": buyer_data.get("city", "") or "",
		"postal_code": buyer_data.get("postal_code", "") or "",
	})
	return base


@frappe.whitelist(methods=["POST"])
def update_user_profile(
	first_name: str = None,
	last_name: str = None,
	phone: str = None,
	country: str = None,
	business_name: str = None,
	address: str = None,
	city: str = None,
	tax_id_type: str = None,
	tax_office: str = None,
	bank_name: str = None,
	iban: str = None,
	account_holder_name: str = None,
	avatar: str = None,
	business_type: str = None,
	company_name: str = None,
	job_title: str = None,
	website: str = None,
	selling_platforms: str = None,
	year_established: str = None,
	employee_count: str = None,
	about_us: str = None,
	industry_preferences: str = None,
	sourcing_frequency: str = None,
	annual_spending: str = None,
	postal_code: str = None,
):
	"""Update profile fields for the currently logged-in user.

	Updates User doc + all related profiles (Buyer, Seller, Application).
	"""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Not logged in."), frappe.AuthenticationError)

	doc = frappe.get_doc("User", user)

	# ── Validate phone format (if provided) ──
	if phone is not None:
		phone = phone.strip()
		if phone:
			cleaned = re.sub(r"[\s\-\(\)]", "", phone)
			if not re.match(r"^(\+90|0)?5\d{9}$", cleaned):
				frappe.local.response["http_status_code"] = 400
				frappe.throw(
					_("Please enter a valid Turkish phone number."),
					frappe.ValidationError,
				)

	if first_name is not None:
		doc.first_name = first_name
	if last_name is not None:
		doc.last_name = last_name
	if phone is not None:
		doc.phone = phone

	doc.save(ignore_permissions=True)

	# ── Update ALL related profiles independently ──
	fn = first_name if first_name is not None else doc.first_name
	ln = last_name if last_name is not None else doc.last_name
	full_name = f"{fn} {ln}".strip()

	# Buyer Profile
	buyer_profile = frappe.db.get_value("Buyer Profile", {"user": user}, "name")
	if buyer_profile:
		updates = {}
		if first_name is not None or last_name is not None:
			updates["buyer_name"] = full_name
		if phone is not None:
			updates["phone"] = phone
		if country is not None:
			updates["country"] = country
		if avatar is not None:
			updates["avatar"] = avatar
		if business_type is not None:
			updates["business_type"] = business_type
		if company_name is not None:
			updates["company_name"] = company_name
		if address is not None:
			updates["address"] = address
		if job_title is not None:
			updates["job_title"] = job_title
		if website is not None:
			updates["website"] = website
		if selling_platforms is not None:
			updates["selling_platforms"] = selling_platforms
		if year_established is not None:
			updates["year_established"] = year_established
		if employee_count is not None:
			updates["employee_count"] = employee_count
		if about_us is not None:
			updates["about_us"] = about_us
		if industry_preferences is not None:
			updates["industry_preferences"] = industry_preferences
		if sourcing_frequency is not None:
			updates["sourcing_frequency"] = sourcing_frequency
		if annual_spending is not None:
			updates["annual_spending"] = annual_spending
		if city is not None:
			updates["city"] = city
		if postal_code is not None:
			updates["postal_code"] = postal_code
		for field, value in updates.items():
			frappe.db.set_value("Buyer Profile", buyer_profile, field, value)

	# Seller Profile
	seller_profile = frappe.db.get_value("Seller Profile", {"user": user}, "name")
	roles = frappe.get_roles(user)
	is_admin = "System Manager" in roles or "Marketplace Admin" in roles

	if seller_profile:
		updates = {}
		if first_name is not None or last_name is not None:
			updates["seller_name"] = full_name
		if business_name is not None:
			updates["business_name"] = business_name
		if phone is not None:
			updates["contact_phone"] = phone
		if country is not None:
			updates["country"] = country
		if address is not None:
			updates["address_line_1"] = address
		if city is not None:
			updates["city"] = city
		# permlevel 1 fields — admin only
		if tax_id_type is not None and is_admin:
			updates["tax_id_type"] = tax_id_type
		if tax_office is not None and is_admin:
			updates["tax_office"] = tax_office
		if bank_name is not None and is_admin:
			updates["bank_name"] = bank_name
		if iban is not None and is_admin:
			updates["iban"] = iban
		if account_holder_name is not None and is_admin:
			updates["account_holder_name"] = account_holder_name
		if avatar is not None:
			updates["avatar"] = avatar
		if website is not None:
			updates["website"] = website
		if job_title is not None:
			updates["job_title"] = job_title
		if year_established is not None:
			updates["year_established"] = year_established
		if employee_count is not None:
			updates["employee_count"] = employee_count
		if about_us is not None:
			updates["about_us"] = about_us
		if selling_platforms is not None:
			updates["selling_platforms"] = selling_platforms
		if postal_code is not None:
			updates["postal_code"] = postal_code
		if industry_preferences is not None:
			updates["industry_preferences"] = industry_preferences
		if sourcing_frequency is not None:
			updates["sourcing_frequency"] = sourcing_frequency
		if annual_spending is not None:
			updates["annual_spending"] = annual_spending
		for field, value in updates.items():
			frappe.db.set_value("Seller Profile", seller_profile, field, value)

	# Seller Application
	seller_app = frappe.db.get_value("Seller Application", {"applicant_user": user}, "name")
	if seller_app:
		updates = {}
		if business_name is not None:
			updates["business_name"] = business_name
		if phone is not None:
			updates["contact_phone"] = phone
		if country is not None:
			updates["country"] = country
		if address is not None:
			updates["address_line_1"] = address
		if city is not None:
			updates["city"] = city
		if tax_id_type is not None:
			updates["tax_id_type"] = tax_id_type
		if tax_office is not None:
			updates["tax_office"] = tax_office
		if bank_name is not None:
			updates["bank_name"] = bank_name
		if iban is not None:
			updates["iban"] = iban
		if account_holder_name is not None:
			updates["account_holder_name"] = account_holder_name
		for field, value in updates.items():
			frappe.db.set_value("Seller Application", seller_app, field, value)

	frappe.db.commit()

	return {"success": True, "message": _("Profile updated successfully.")}
