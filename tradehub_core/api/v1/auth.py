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
	allowed = {"User Profile", "Admin Seller Profile", "KYB Verification"}
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
		["email", "full_name", "first_name", "last_name", "creation", "user_image"],
		as_dict=True,
	)

	if not user_data:
		return {"logged_in": False, "user": None}

	roles = frappe.get_roles(frappe.session.user)

	# Sprint 2: User Profile artık herkeste var (Buyer + Seller + hibrit).
	# is_seller = User Profile.can_sell capability flag'i (rol fallback'i ile).
	# has_seller_profile = Admin Seller Profile (mağaza entity) varlığı.
	up_data = (
		frappe.db.get_value(
			"User Profile",
			{"user": frappe.session.user},
			["can_sell", "can_buy"],
			as_dict=True,
		)
		or {}
	)

	is_admin = "System Manager" in roles or "Administrator" in roles or "Marketplace Admin" in roles
	is_field_agent = "Saha Pazarlama" in roles
	is_buyer = "Buyer" in roles or bool(up_data.get("can_buy"))
	# is_seller: direkt seller rolü VEYA can_sell flag VEYA bir tenant'a bağlı sub-user
	# (Seller Owner/Co-Owner/Admin/Finance Staff/Operations gibi tüm satıcı sub-user'lar)
	tenant_link = frappe.db.get_value("User", frappe.session.user, "tradehub_tenant")
	is_owner_flag = frappe.db.get_value("User", frappe.session.user, "tradehub_is_owner")
	is_seller = (
		"Seller" in roles
		or bool(up_data.get("can_sell"))
		or bool(tenant_link)
		or any(r.startswith("Seller ") for r in roles)
	)
	is_owner = bool(is_owner_flag) and ("Seller Owner" in roles)

	# Sub-user (Co-Owner / Manager / Operations / Finance Staff) için KYB ve
	# satıcı doğrulama statüsü tenant sahibinden (mağaza Owner'ı) miras alınır.
	# KYB doğrulaması mağaza entity'sine ait — sub-user kendi adına yapmaz.
	is_sub_user = bool(tenant_link) and not is_owner
	tenant_owner_user = (
		frappe.db.get_value("Admin Seller Profile", tenant_link, "user") if is_sub_user else None
	)
	kyb_source_user = tenant_owner_user or frappe.session.user
	is_verified_seller = "Verified Seller" in (
		frappe.get_roles(tenant_owner_user) if tenant_owner_user else roles
	)

	has_seller_profile = bool(
		frappe.db.exists(
			"Admin Seller Profile",
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
		"Draft",
		"Submitted",
		"Under Review",
	)

	rejected_seller_application = seller_application_status == "Rejected"

	# Sprint 2: seller_profile = Admin Seller Profile.name (mağaza URL'i için
	# `getSellerStoreUrl(user)` bu field'ı kullanır). User Profile.name = email
	# olduğundan storefront URL'i için anlamsız.
	#
	# Sub-user desteği: owner değilse User.tradehub_tenant fallback'i kullan.
	seller_profile = (
		frappe.db.get_value("Admin Seller Profile", {"user": frappe.session.user}, "name") or None
	)
	if not seller_profile:
		try:
			from tradehub_core.utils.tenant import _get_seller_profile_for_user

			seller_profile = _get_seller_profile_for_user(frappe.session.user)
		except Exception:
			seller_profile = None

	# Admin Seller Profile — satıcının mağaza profili (filtreleme için seller_code gerekli)
	admin_seller_profile = None
	if is_seller:
		try:
			asp_name = (
				frappe.db.get_value("Admin Seller Profile", {"user": frappe.session.user}, "name")
				or seller_profile
			)
			if asp_name:
				asp = frappe.db.get_value(
					"Admin Seller Profile",
					asp_name,
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

	# KYB verification — Sprint 2.6: verification_kind kolonu kaldırıldı,
	# KYC ayrı DocType'a taşındı. Bu DocType artık sadece KYB için.
	# Sub-user için sorgu tenant owner'ına yönlendirilir (kyb_source_user).
	kyb_data = frappe.db.get_value(
		"KYB Verification",
		{"user": kyb_source_user},
		["name", "status"],
		as_dict=True,
	)
	kyb_status = kyb_data.status if kyb_data else None
	kyb_verification = kyb_data.name if kyb_data else None

	# KYC status — User Profile.kyc_status (Business Buyer için banner) kullanıcının
	# kendi profilinden okunur (KYC kişi bazlı). kyb_status ve can_sell ise tenant
	# owner'dan miras alınır — KYB mağaza entity'sine ait.
	up_extra = (
		frappe.db.get_value(
			"User Profile",
			{"user": frappe.session.user},
			["kyc_status", "kyb_status", "account_type", "email_verified"],
			as_dict=True,
		)
		or {}
	)
	owner_up_extra = (
		frappe.db.get_value(
			"User Profile",
			{"user": tenant_owner_user},
			["kyb_status", "can_sell"],
			as_dict=True,
		)
		if is_sub_user and tenant_owner_user
		else None
	)
	kyc_status = up_extra.get("kyc_status") or None
	kyb_status_up = (
		(owner_up_extra.get("kyb_status") if owner_up_extra else None)
		or up_extra.get("kyb_status")
		or kyb_status
	)
	account_type = up_extra.get("account_type") or "Individual"
	email_verified = bool(up_extra.get("email_verified")) if up_extra else True
	effective_can_sell = (
		bool(owner_up_extra.get("can_sell")) if owner_up_extra else bool(up_data.get("can_sell"))
	)

	from frappe.sessions import get_csrf_token

	# Seller capability listesi — UI gating için (v-if="can('order.ship')" deseni).
	# Backend has_seller_capability ile tutarlı; frontend butonları gizler ama
	# son söz backend'deki require_seller_capability'dedir (defense-in-depth).
	from tradehub_core.utils.seller_capabilities import get_user_capabilities

	capabilities = get_user_capabilities() if is_seller or is_admin else []

	return {
		"logged_in": True,
		"csrf_token": get_csrf_token(),
		"user": {
			"email": user_data.email,
			"full_name": user_data.full_name,
			"first_name": user_data.first_name or "",
			"last_name": user_data.last_name or "",
			"user_image": user_data.user_image or "",
			"member_id": member_id,
			"roles": roles,
			"capabilities": capabilities,
			"role_profile_name": frappe.db.get_value("User", frappe.session.user, "role_profile_name") or "",
			"is_admin": is_admin,
			"is_seller": is_seller,
			"is_field_agent": is_field_agent,
			"is_owner": is_owner,
			"tenant": tenant_link,
			"is_verified_seller": is_verified_seller,
			"is_buyer": is_buyer,
			"has_seller_profile": has_seller_profile,
			"pending_seller_application": pending_seller_application,
			"rejected_seller_application": rejected_seller_application,
			"seller_application_status": seller_application_status,
			"seller_profile": seller_profile,
			"admin_seller_profile": admin_seller_profile,
			"kyb_status": kyb_status,
			"kyb_verification": kyb_verification,
			"kyc_status": kyc_status,
			"account_type": account_type,
			"can_buy": bool(up_data.get("can_buy")),
			"can_sell": effective_can_sell,
			# Sprint 2.6 (revised) — status-bazlı locked/required kararı.
			# can_buy/can_sell artık kyc_status/kyb_status'tan türetilen flag'ler
			# (KYC Verified → can_buy=1; KYB Verified → can_sell=1); locked/required
			# kararı doğrudan status üzerinden alınır:
			#   - kyc_locked: KYC admin tarafından "Locked" işaretlendi mi
			#   - kyb_locked: KYB admin tarafından "Locked" işaretlendi mi
			#   - kyc_required: kullanıcı KYC süreci başlatmış ama henüz Verified değil
			#   - kyb_required: kullanıcı KYB süreci başlatmış ama henüz Verified değil
			"kyc_locked": kyc_status == "Locked",
			"kyb_locked": kyb_status_up == "Locked",
			"kyc_required": kyc_status in ("Pending", "Rejected"),
			"kyb_required": kyb_status_up in ("Pending", "Rejected"),
			"email_verified": email_verified,
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
		["email", "full_name", "first_name", "last_name", "creation", "phone", "user_image"],
		as_dict=True,
	)

	if not user_data:
		frappe.throw(_("User not found."), frappe.DoesNotExistError)

	roles = frappe.get_roles(user)

	# Sprint 2.6 (revised, 2026-05-15): is_seller artık can_sell capability flag üzerinden.
	# Patch 20 invariant: can_sell=1 ⇔ kyb_status="Verified". "Seller" rolü fallback eski sistem için.
	is_seller = bool(frappe.db.get_value("User Profile", {"user": user}, "can_sell")) or "Seller" in roles

	# Read member_id from DB; fallback to computed value for legacy users
	member_id = (
		frappe.db.get_value("User Profile", {"user": user}, "member_id")
		or frappe.db.get_value("User Profile", {"user": user}, "member_id")
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
		"avatar": user_data.user_image or "",
	}

	# ── Seller ──
	if is_seller:
		base["account_type"] = "seller"

		# Sprint 2.6 (revised, 2026-05-15):
		# - Kişisel alanlar → User Profile
		# - Mağaza alanları (seller_name/seller_type, adres) → Admin Seller Profile
		# - User Profile'da OLMAYAN field'lar (seller_name, seller_type, business_name,
		#   contact_phone, address_line_1, city, postal_code) doğru DocType'a yönlendirildi.
		# - Legacy alias: response'ta business_name=company_name, contact_phone=phone (frontend uyumu)
		sp = frappe.db.get_value(
			"User Profile",
			{"user": user},
			[
				"full_name",
				"company_name",
				"tax_id",
				"phone",
				"country",
				"status",
				"tax_id_type",
				"tax_office",
				"bank_name",
				"iban",
				"account_holder_name",
				"website",
				"job_title",
				"year_established",
				"employee_count",
				"about_us",
				"selling_platforms",
				"industry_preferences",
				"sourcing_frequency",
				"annual_spending",
			],
			as_dict=True,
		)
		if sp:
			# Mağaza entity (Admin Seller Profile) ek bilgisi
			asp = (
				frappe.db.get_value(
					"Admin Seller Profile",
					{"user": user},
					["seller_name", "seller_type", "address_line1", "city", "postal_code"],
					as_dict=True,
				)
				or {}
			)
			# Sprint 4 — Sensitive field maskeleme.
			# Owner her capability'i otomatik alır; Co-Owner için view.bank_info /
			# view.tax_id grant edilir; Manager / Operations / Finance Staff için
			# bu capability'ler yoksa response IBAN/tax_id maskelenir.
			from tradehub_core.utils.permission_resolver import apply_field_mask
			from tradehub_core.utils.seller_capabilities import has_seller_capability

			can_view_bank = has_seller_capability("view.bank_info", user)
			can_view_tax = has_seller_capability("view.tax_id", user)

			iban_value = sp.iban or ""
			bank_name_value = sp.bank_name or ""
			account_holder_value = sp.account_holder_name or ""
			tax_id_value = sp.tax_id or ""

			if iban_value and not can_view_bank:
				iban_value = apply_field_mask(iban_value, "iban_xxx_last4")
			if not can_view_bank:
				bank_name_value = ""
				if account_holder_value:
					account_holder_value = apply_field_mask(account_holder_value, "initials")
			if tax_id_value and not can_view_tax:
				tax_id_value = apply_field_mask(tax_id_value, "last4")

			base.update(
				{
					"seller_name": asp.get("seller_name") or sp.full_name or "",
					"seller_type": asp.get("seller_type") or "",
					"company_name": sp.company_name or "",
					"business_name": sp.company_name or "",  # legacy alias
					"tax_id": tax_id_value,
					"phone": sp.phone or user_data.phone or "",
					"contact_phone": sp.phone or user_data.phone or "",  # legacy alias
					"country": sp.country or "",
					"seller_status": sp.status or "",
					"tax_id_type": sp.tax_id_type or "",
					"tax_office": sp.tax_office or "",
					"address": asp.get("address_line1") or "",
					"city": asp.get("city") or "",
					"postal_code": asp.get("postal_code") or "",
					"bank_name": bank_name_value,
					"iban": iban_value,
					"account_holder_name": account_holder_value,
					"website": sp.website or "",
					"job_title": sp.job_title or "",
					"year_established": sp.year_established or "",
					"employee_count": sp.employee_count or "",
					"about_us": sp.about_us or "",
					"selling_platforms": sp.selling_platforms or "",
					"industry_preferences": sp.industry_preferences or "",
					"sourcing_frequency": sp.sourcing_frequency or "",
					"annual_spending": sp.annual_spending or "",
					"_masked": {
						"bank_info": not can_view_bank,
						"tax_id": not can_view_tax,
					},
				}
			)
			return base

		# Fallback: Seller Application only (pending sellers)
		sa = frappe.db.get_value(
			"Seller Application",
			{"applicant_user": user},
			[
				"seller_type",
				"business_name",
				"contact_phone",
				"tax_id",
				"tax_id_type",
				"tax_office",
				"address_line_1",
				"city",
				"country",
				"bank_name",
				"iban",
				"account_holder_name",
				"status",
			],
			as_dict=True,
		)
		if sa:
			base.update(
				{
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
				}
			)
		return base

	# ── Buyer (default) ──
	base["account_type"] = "buyer"
	# Sprint 2.6: address/city/postal_code Frappe Address mimarisinde (Sprint 1).
	# User Profile'da bu alanlar yok — son KYC Verification'dan address çekilir.
	buyer_data = (
		frappe.db.get_value(
			"User Profile",
			{"user": user},
			[
				"country",
				"phone",
				"email_verified",
				"business_type",
				"company_name",
				"job_title",
				"website",
				"selling_platforms",
				"year_established",
				"employee_count",
				"about_us",
				"industry_preferences",
				"sourcing_frequency",
				"annual_spending",
			],
			as_dict=True,
		)
		or {}
	)
	# KYC Verification'dan adres bilgisi (varsa)
	kyc_addr = (
		frappe.db.get_value(
			"KYC Verification",
			{"user": user},
			["address", "billing_address"],
			as_dict=True,
		)
		or {}
	)
	base.update(
		{
			"email_verified": bool(buyer_data.get("email_verified")),
			"phone": user_data.phone or buyer_data.get("phone", "") or "",
			"country": buyer_data.get("country", "") or "",
			"business_type": buyer_data.get("business_type", "") or "",
			"company_name": buyer_data.get("company_name", "") or "",
			"address": kyc_addr.get("address", "") or "",
			"job_title": buyer_data.get("job_title", "") or "",
			"website": buyer_data.get("website", "") or "",
			"selling_platforms": buyer_data.get("selling_platforms", "") or "",
			"year_established": buyer_data.get("year_established", "") or "",
			"employee_count": buyer_data.get("employee_count", "") or "",
			"about_us": buyer_data.get("about_us", "") or "",
			"industry_preferences": buyer_data.get("industry_preferences", "") or "",
			"sourcing_frequency": buyer_data.get("sourcing_frequency", "") or "",
			"annual_spending": buyer_data.get("annual_spending", "") or "",
			"billing_address": kyc_addr.get("billing_address", "") or "",
			"city": "",  # Sprint 1: Frappe Address — şu an boş
			"postal_code": "",
		}
	)
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

	# ── Validate business_name (required for sellers if provided) ──
	if business_name is not None:
		business_name = business_name.strip()
		if not business_name:
			frappe.local.response["http_status_code"] = 400
			frappe.throw(
				_("Business Name is required."),
				frappe.ValidationError,
			)

	if first_name is not None:
		doc.first_name = first_name
	if last_name is not None:
		doc.last_name = last_name
	if phone is not None:
		doc.phone = phone
	if avatar is not None:
		doc.user_image = avatar

	doc.save(ignore_permissions=True)

	# ── Update ALL related profiles independently ──
	fn = first_name if first_name is not None else doc.first_name
	ln = last_name if last_name is not None else doc.last_name
	full_name = f"{fn} {ln}".strip()

	# Sprint 2.6: User Profile birleşik — tek update bloğu. Eski Buyer/Seller
	# Profile ayrı blokları kaldırıldı. address/city/postal_code Frappe Address
	# DocType'ında (Sprint 1 adres mimarisi); User Profile'a yazılmaz.
	user_profile = frappe.db.get_value("User Profile", {"user": user}, "name")
	roles = frappe.get_roles(user)
	is_admin = "System Manager" in roles or "Marketplace Admin" in roles

	if user_profile:
		updates: dict[str, object] = {}
		if first_name is not None or last_name is not None:
			updates["full_name"] = full_name
		if phone is not None:
			updates["phone"] = phone
		if country is not None:
			updates["country"] = country
		if business_type is not None:
			updates["business_type"] = business_type
		# Şirket adı: company_name (Sprint 2 birleşmesi; eski business_name kaldırıldı)
		if company_name is not None:
			updates["company_name"] = company_name
		if business_name is not None and not company_name:
			updates["company_name"] = business_name
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
		# address/city/postal_code: Sprint 1 adres mimarisinde Frappe Address — atla
		for field, value in updates.items():
			frappe.db.set_value("User Profile", user_profile, field, value)

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
