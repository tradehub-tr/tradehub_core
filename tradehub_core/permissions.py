# Copyright (c) 2024, TradeHub Team and contributors
# For license information, please see license.txt

"""
Tenant-based permission handlers for TradeHub multi-tenant platform.
Provides permission query conditions and permission checks for tenant isolation.

These functions are registered in hooks.py under:
- permission_query_conditions
- has_permission
"""

import frappe
from frappe.utils import cint, flt

# Import tenant utilities
from tradehub_core.utils.tenant import _has_tenant_field, get_current_tenant, is_tenant_admin

# ---------------------------------------------------------------------------
# ABAC (Attribute-Based Access Control) Policy Constants
# ---------------------------------------------------------------------------

# Financial DocTypes that require KYC verification before access is granted.
# Users without a verified KYC profile will be denied access to these DocTypes.
FINANCIAL_DOCTYPES = frozenset(
	[
		"Payment Intent",
		"Escrow Account",
		"Seller Balance",
		"Commission Plan",
		"Commission Rule",
	]
)

# DocTypes that require AML/sanctions clearance. Users with an AML hit
# ("Hit Found") or sanctions match ("Match Found") on their KYC Profile
# will be blocked from accessing these DocTypes.
AML_SENSITIVE_DOCTYPES = frozenset(
	[
		"Payment Intent",
		"Escrow Account",
		"Seller Balance",
	]
)


def get_tenant_permission_query_conditions(user=None):
	"""
	Get SQL WHERE conditions for tenant-based permission filtering.

	This function is called by Frappe when building list queries for DocTypes
	that have it registered in permission_query_conditions in hooks.py.

	Args:
	    user (str, optional): User to check permissions for.
	        Defaults to current session user.

	Returns:
	    str: SQL WHERE clause fragment (without WHERE keyword).
	        Returns empty string if no filtering needed.

	Example:
	    # In hooks.py
	    permission_query_conditions = {
	        "Seller Profile": "tradehub_core.permissions.get_tenant_permission_query_conditions",
	        "Listing": "tradehub_core.permissions.get_tenant_permission_query_conditions",
	    }
	"""
	user = user or frappe.session.user

	# System Manager can see all tenants
	if "System Manager" in frappe.get_roles(user):
		return ""

	# Get current tenant context
	tenant = get_current_tenant()

	if not tenant:
		# No tenant context - user might be a guest or not assigned to a tenant
		# Allow access only to own records based on owner
		return f"`tabSeller Profile`.`owner` = '{frappe.db.escape(user)}'"

	# Return tenant filter condition
	return f"`tenant` = '{frappe.db.escape(tenant)}'"


def has_tenant_permission(doc, ptype=None, user=None):
	"""
	Check if user has permission to access a document based on tenant isolation.

	This function is called by Frappe when checking document-level permissions
	for DocTypes that have it registered in has_permission in hooks.py.

	Args:
	    doc: The document to check permission for.
	        Can be a Document object or a dict with doctype and name.
	    ptype (str, optional): Permission type ('read', 'write', 'delete', etc.).
	        Defaults to 'read'.
	    user (str, optional): User to check permissions for.
	        Defaults to current session user.

	Returns:
	    bool: True if user has permission, False otherwise.

	Example:
	    # In hooks.py
	    has_permission = {
	        "Seller Profile": "tradehub_core.permissions.has_tenant_permission",
	        "Listing": "tradehub_core.permissions.has_tenant_permission",
	    }
	"""
	user = user or frappe.session.user
	ptype = ptype or "read"

	# System Manager has full access
	if "System Manager" in frappe.get_roles(user):
		return True

	# Get document data
	if isinstance(doc, dict):
		doc_tenant = doc.get("tenant")
		doc_owner = doc.get("owner")
		doctype = doc.get("doctype")
	else:
		doc_tenant = getattr(doc, "tenant", None)
		doc_owner = getattr(doc, "owner", None)
		doctype = doc.doctype

	# If DocType doesn't have tenant field, allow based on standard permissions
	if doctype and not _has_tenant_field(doctype):
		return True

	# Get user's tenant
	user_tenant = get_current_tenant()

	# If document has no tenant, check owner
	if not doc_tenant:
		return doc_owner == user

	# If user has no tenant context, deny access to tenant-specific documents
	if not user_tenant:
		return False

	# Check tenant match
	if doc_tenant != user_tenant:
		return False

	# --- ABAC Layer Checks (regulatory, applied before tenant admin bypass) ---

	# KYC verification required for financial DocTypes
	if not _check_kyc_verification(user, doctype):
		return False

	# AML/sanctions check for sensitive DocTypes
	if not _check_aml_sanctions(user, doctype):
		return False

	# Spending limit validation for write/submit operations
	if ptype in ("write", "submit", "create"):
		if not _check_spending_limit(doc, user, ptype):
			return False

	# Tenant admin can perform all operations within their tenant
	if is_tenant_admin(user, user_tenant):
		return True

	# For write/delete operations, additional checks may apply
	if ptype in ("write", "delete", "cancel", "submit"):
		return _has_write_permission_in_tenant(doc, user, ptype)

	return True


def _has_write_permission_in_tenant(doc, user, ptype):
	"""
	Check if user has write/delete permission within their tenant.

	Args:
	    doc: The document to check.
	    user (str): The user.
	    ptype (str): Permission type.

	Returns:
	    bool: True if user has write permission, False otherwise.
	"""
	# Owner always has write permission to their own documents
	doc_owner = getattr(doc, "owner", None) if not isinstance(doc, dict) else doc.get("owner")
	if doc_owner == user:
		return True

	# Check role-based permissions within tenant
	# This integrates with Frappe's standard role permissions
	if isinstance(doc, dict):
		doctype = doc.get("doctype")
	else:
		doctype = doc.doctype

	# Get user roles
	roles = frappe.get_roles(user)

	# Check if any role has the required permission
	permissions = frappe.get_all(
		"DocPerm", filters={"parent": doctype, "role": ["in", roles], ptype: 1}, fields=["role"], limit=1
	)

	return len(permissions) > 0


# ---------------------------------------------------------------------------
# ABAC Layer Functions
# ---------------------------------------------------------------------------


def _check_kyc_verification(user, doctype):
	"""
	ABAC Layer: Deny access to financial DocTypes for non-KYC-verified users.

	Checks the ``kyc_verified`` custom field on the User record.  Only
	DocTypes listed in :data:`FINANCIAL_DOCTYPES` are gated; all other
	DocTypes pass through without a KYC check.

	Args:
	    user (str): User to check.
	    doctype (str): DocType being accessed.

	Returns:
	    bool: True if access is allowed, False if denied.
	"""
	if doctype not in FINANCIAL_DOCTYPES:
		return True

	# Use a short-lived cache to avoid repeated DB lookups during a request
	cache_key = f"kyc_verified:{user}"
	kyc_verified = frappe.cache().get_value(cache_key)

	if kyc_verified is None:
		kyc_verified = cint(frappe.db.get_value("User", user, "kyc_verified"))
		# Cache for 5 minutes — cleared on KYC Profile update
		frappe.cache().set_value(cache_key, kyc_verified, expires_in_sec=300)

	return bool(kyc_verified)


def _check_aml_sanctions(user, doctype):
	"""
	ABAC Layer: Block access for users flagged by AML or sanctions screening.

	Looks up the user's active KYC Profile and checks ``aml_check_status``
	and ``sanctions_status``.  A value of ``"Hit Found"`` (AML) or
	``"Match Found"`` (sanctions) results in access denial for DocTypes
	listed in :data:`AML_SENSITIVE_DOCTYPES`.

	Args:
	    user (str): User to check.
	    doctype (str): DocType being accessed.

	Returns:
	    bool: True if access is allowed, False if blocked.
	"""
	if doctype not in AML_SENSITIVE_DOCTYPES:
		return True

	cache_key = f"aml_status:{user}"
	aml_status = frappe.cache().get_value(cache_key)

	if aml_status is None:
		kyc_profile = frappe.db.get_value(
			"KYC Profile",
			{"user": user, "status": ("not in", ["Rejected", "Expired"])},
			["aml_check_status", "sanctions_status"],
			as_dict=True,
		)

		if kyc_profile:
			aml_status = {
				"aml_hit": kyc_profile.aml_check_status == "Hit Found",
				"sanctions_match": kyc_profile.sanctions_status == "Match Found",
			}
		else:
			# No active KYC profile — AML check not applicable
			aml_status = {"aml_hit": False, "sanctions_match": False}

		# Cache for 5 minutes — cleared on KYC Profile update
		frappe.cache().set_value(cache_key, aml_status, expires_in_sec=300)

	if aml_status.get("aml_hit") or aml_status.get("sanctions_match"):
		return False

	return True


def _check_spending_limit(doc, user, ptype):
	"""
	ABAC Layer: Enforce spending limits via the Spending Approval Rule DocType.

	For write/submit/create operations on documents that carry an amount,
	this function looks up applicable ``Spending Approval Rule`` records
	for the user's roles.  If the transaction amount falls within a rule's
	range and the user does not hold the required ``approver_role``, access
	is denied (approval is needed).  If the amount exceeds all defined
	limits, access is also denied.

	The check is intentionally lenient: if the Spending Approval Rule
	DocType does not exist yet (pre-migration), or no rules are defined,
	access is allowed.

	Args:
	    doc: The document being accessed (Document object or dict).
	    user (str): User performing the operation.
	    ptype (str): Permission type (``write``, ``submit``, ``create``).

	Returns:
	    bool: True if within limits or approved, False if denied.
	"""
	if ptype not in ("write", "submit", "create"):
		return True

	# Extract amount from document (check common amount field names)
	if isinstance(doc, dict):
		amount = doc.get("amount") or doc.get("total_amount") or doc.get("grand_total")
	else:
		amount = (
			getattr(doc, "amount", None)
			or getattr(doc, "total_amount", None)
			or getattr(doc, "grand_total", None)
		)

	if not amount:
		return True

	amount = flt(amount)
	if amount <= 0:
		return True

	# Gracefully handle missing Spending Approval Rule DocType
	try:
		if not frappe.db.exists("DocType", "Spending Approval Rule"):
			return True

		user_roles = frappe.get_roles(user)

		spending_rules = frappe.get_all(
			"Spending Approval Rule",
			filters={
				"is_active": 1,
				"role": ["in", user_roles],
			},
			fields=[
				"role",
				"min_amount",
				"max_amount",
				"approver_role",
				"approval_type",
			],
			order_by="max_amount asc",
		)

		if not spending_rules:
			return True

		for rule in spending_rules:
			if flt(rule.min_amount) <= amount <= flt(rule.max_amount):
				# Amount falls within this rule's range
				if rule.approver_role and rule.approver_role not in user_roles:
					# User lacks the approver role — needs approval
					return False
				# User holds the approver role — allowed
				return True

		# Amount exceeds all defined rule ceilings
		max_allowed = max(flt(r.max_amount) for r in spending_rules)
		if amount > max_allowed:
			return False

	except Exception:
		# Gracefully degrade: if anything fails (e.g., DocType not migrated),
		# allow the operation rather than locking out users.
		pass

	return True


def setup_tenant_permission_query_conditions():
	"""
	Build permission query conditions dict for all tenant-aware DocTypes.

	Returns:
	    dict: Dictionary mapping DocTypes to permission query condition functions.

	Usage:
	    # In hooks.py
	    from tradehub_core.permissions import setup_tenant_permission_query_conditions
	    permission_query_conditions = setup_tenant_permission_query_conditions()
	"""
	tenant_aware_doctypes = get_tenant_aware_doctypes()

	conditions = {}
	for doctype in tenant_aware_doctypes:
		conditions[doctype] = "tradehub_core.permissions.get_tenant_permission_query_conditions"

	return conditions


def setup_has_permission():
	"""
	Build has_permission dict for all tenant-aware DocTypes.

	Returns:
	    dict: Dictionary mapping DocTypes to has_permission functions.

	Usage:
	    # In hooks.py
	    from tradehub_core.permissions import setup_has_permission
	    has_permission = setup_has_permission()
	"""
	tenant_aware_doctypes = get_tenant_aware_doctypes()

	permissions = {}
	for doctype in tenant_aware_doctypes:
		permissions[doctype] = "tradehub_core.permissions.has_tenant_permission"

	return permissions


def get_tenant_aware_doctypes():
	"""
	Get list of DocTypes that have tenant isolation enabled.

	Returns:
	    list: List of DocType names with tenant field.
	"""
	cache_key = "tenant_aware_doctypes"
	doctypes = frappe.cache().get_value(cache_key)

	if doctypes is None:
		# Get all DocTypes with a 'tenant' field
		doctypes = frappe.get_all(
			"DocField",
			filters={"fieldname": "tenant", "fieldtype": "Link", "options": "Tenant"},
			pluck="parent",
			distinct=True,
		)

		# Also check Custom Fields
		custom_doctypes = frappe.get_all(
			"Custom Field",
			filters={"fieldname": "tenant", "fieldtype": "Link", "options": "Tenant"},
			pluck="dt",
			distinct=True,
		)

		doctypes = list(set(doctypes + custom_doctypes))

		# Cache for 1 hour
		frappe.cache().set_value(cache_key, doctypes, expires_in_sec=3600)

	return doctypes


def clear_tenant_permission_cache():
	"""
	Clear tenant permission related caches.
	Should be called when DocType definitions change.
	"""
	frappe.cache().delete_value("tenant_aware_doctypes")

	# Clear individual doctype tenant field cache
	for doctype in frappe.get_all("DocType", pluck="name"):
		frappe.cache().delete_value(f"doctype_has_tenant:{doctype}")


def get_restricted_record_condition(doctype, user=None):
	"""
	Get condition for restricting records based on user's tenant and permissions.

	This is a helper function for building complex queries with tenant isolation.

	Args:
	    doctype (str): The DocType name.
	    user (str, optional): User to check for. Defaults to current user.

	Returns:
	    str: SQL condition string.
	"""
	user = user or frappe.session.user

	# Build base condition
	conditions = []

	# Add tenant condition
	tenant_condition = get_tenant_permission_query_conditions(user)
	if tenant_condition:
		conditions.append(f"({tenant_condition})")

	# Join conditions
	if conditions:
		return " AND ".join(conditions)

	return ""


def apply_tenant_filter(filters, doctype=None, user=None):
	"""
	Apply tenant filter to a filters dictionary.

	Utility function for programmatically adding tenant isolation to queries.

	Args:
	    filters (dict): Existing filters dictionary.
	    doctype (str, optional): DocType name for tenant field check.
	    user (str, optional): User to get tenant for.

	Returns:
	    dict: Updated filters with tenant isolation.
	"""
	user = user or frappe.session.user

	# System Manager doesn't get filtered
	if "System Manager" in frappe.get_roles(user):
		return filters

	tenant = get_current_tenant()

	if tenant:
		filters = filters or {}
		filters["tenant"] = tenant

	return filters


# ---------------------------------------------------------------------------
# Seller-Isolation Permission Handlers
# ---------------------------------------------------------------------------
# These provide row-level security so each seller only sees their own records.
# System Manager bypasses all checks.
# ---------------------------------------------------------------------------


def _get_seller_profile_name(user):
	"""Return the Admin Seller Profile name (= seller_code) for the given user, or None."""
	profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not profile:
		profile = frappe.db.get_value("Admin Seller Profile", {"owner": user}, "name")
	if not profile:
		profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")
	return profile


# ── Listing ──────────────────────────────────────────────────────────────────


def listing_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabListing`.`seller_profile` = {frappe.db.escape(profile)}"
	return "1=0"


def listing_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	if not profile:
		return False
	# doc yoksa (doctype-seviyesi kontrol) veya henüz kaydedilmemişse izin ver
	if doc is None:
		return True
	doc_seller = getattr(doc, "seller_profile", None) or (
		doc.get("seller_profile") if isinstance(doc, dict) else None
	)
	# seller_profile henüz atanmamışsa izin ver (before_insert otomatik atar)
	if not doc_seller:
		return True
	return doc_seller == profile


# ── Admin Seller Profile ─────────────────────────────────────────────────────


def admin_seller_profile_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabAdmin Seller Profile`.`name` = {frappe.db.escape(profile)}"
	return "1=0"


def admin_seller_profile_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	doc_name = getattr(doc, "name", None) if not isinstance(doc, dict) else doc.get("name")
	return profile and doc_name == profile


# ── Seller Balance ───────────────────────────────────────────────────────────
# Seller Balance.seller links to "Seller Profile" whose name = user email.


def seller_balance_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	# Seller Profile is named by user, so seller field value = user email
	return f"`tabSeller Balance`.`seller` = {frappe.db.escape(user)}"


def seller_balance_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return seller_val == user


# ── Seller Review ────────────────────────────────────────────────────────────
# Seller Review.seller links to Admin Seller Profile.


def seller_review_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Review`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_review_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Seller Category ──────────────────────────────────────────────────────────
# Seller Category.seller links to Admin Seller Profile.


def seller_category_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Category`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_category_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Seller Gallery Image ─────────────────────────────────────────────────────
# Child table of Admin Seller Profile — filter by parent.


def seller_gallery_image_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Gallery Image`.`parent` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_gallery_image_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	parent_val = getattr(doc, "parent", None) if not isinstance(doc, dict) else doc.get("parent")
	return profile and parent_val == profile


# ── KYB Verification ─────────────────────────────────────────────────────────
# KYB Verification.user links to User.


def kyb_verification_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	return f"`tabKYB Verification`.`user` = {frappe.db.escape(user)}"


def kyb_verification_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	user_val = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	return user_val == user


# ── Order ─────────────────────────────────────────────────────────────────────
# Order.seller links to Admin Seller Profile.


def order_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabOrder`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def order_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Seller Inquiry ────────────────────────────────────────────────────────────
# Seller Inquiry.seller links to Admin Seller Profile.


def seller_inquiry_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Inquiry`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_inquiry_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Certification Type ───────────────────────────────────────────────────────
# Sellers should only see Approved certification types.


def certification_type_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return (
		f"(`tabCertification Type`.`status` = 'Approved'"
		f" OR `tabCertification Type`.`suggested_by` = {escaped_user})"
	)


def certification_type_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	status_val = getattr(doc, "status", None) if not isinstance(doc, dict) else doc.get("status")
	if status_val == "Approved":
		return True
	# Allow seller to see their own Pending/Rejected suggestions
	suggested_by = (
		getattr(doc, "suggested_by", None) if not isinstance(doc, dict) else doc.get("suggested_by")
	)
	return suggested_by == user


# ── Search History ──────────────────────────────────────────────────────────
# Search History.user links to User. Each user can only see their own records.


def search_history_query_conditions(user):
	if "System Manager" in frappe.get_roles(user):
		return ""
	return f"`tabSearch History`.`user` = {frappe.db.escape(user)}"


def search_history_has_permission(doc, ptype, user):
	if "System Manager" in frappe.get_roles(user):
		return True
	doc_user = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	return doc_user == user


def product_family_query_conditions(user):
	"""
	Satıcı sadece kendi oluşturduğu Product Family kayıtlarını görsün.
	Admin hepsini görür.
	"""
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return ""
	return f"`tabProduct Family`.`owner` = {frappe.db.escape(user)}"


def product_family_has_permission(doc, ptype, user):
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return None
	owner = getattr(doc, "owner", None) if not isinstance(doc, dict) else doc.get("owner")
	if owner and owner == user:
		return True
	return False


def product_attribute_query_conditions(user):
	"""
	Satıcı sadece kendi oluşturduğu Product Attribute kayıtlarını görsün.
	Admin hepsini görür.
	"""
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return ""
	return f"`tabProduct Attribute`.`owner` = {frappe.db.escape(user)}"


def product_attribute_has_permission(doc, ptype, user):
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return None
	owner = getattr(doc, "owner", None) if not isinstance(doc, dict) else doc.get("owner")
	if owner and owner == user:
		return True
	return False


def brand_query_conditions(user):
	"""
	Satıcı sadece aşağıdaki markaları listede görsün:
	  - Kendisinin önerdiği (suggested_by=user)
	  - brand_owner = kendi satıcı profili
	Admin (System Manager / Marketplace Admin) hepsini görür.
	"""
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return ""

	profile = _get_seller_profile_name(user)
	conditions = [f"`tabBrand`.`suggested_by` = {frappe.db.escape(user)}"]
	if profile:
		conditions.append(f"`tabBrand`.`brand_owner` = {frappe.db.escape(profile)}")
	return "(" + " OR ".join(conditions) + ")"


def brand_has_permission(doc, ptype, user):
	"""
	Satıcı sadece kendi önerdiği veya brand_owner'ı olduğu markayı görebilir/yazabilir.
	Admin her şeyi yapar.

	Not: brand_owner ve suggested_by alanları için DB'deki committed değere bakılır,
	aksi halde satıcı brand_owner=None'a çekip save etmeye çalışınca hook False dönüp
	validate aşamasına ulaşılamıyor.
	"""
	roles = set(frappe.get_roles(user))
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return None  # fall through to default (admin zaten yapabilir)

	if ptype not in {"read", "write"}:
		return None

	doc_name = getattr(doc, "name", None) if not isinstance(doc, dict) else doc.get("name")

	# Committed DB values take precedence over in-memory edits.
	suggested_by = None
	brand_owner = None
	if doc_name:
		row = frappe.db.get_value("Brand", doc_name, ["suggested_by", "brand_owner"], as_dict=True)
		if row:
			suggested_by = row.get("suggested_by")
			brand_owner = row.get("brand_owner")
	else:
		# New doc — fall back to in-memory
		suggested_by = (
			getattr(doc, "suggested_by", None) if not isinstance(doc, dict) else doc.get("suggested_by")
		)
		brand_owner = (
			getattr(doc, "brand_owner", None) if not isinstance(doc, dict) else doc.get("brand_owner")
		)

	# Kendi önerdiği marka
	if suggested_by and suggested_by == user:
		return True

	# Kendi brand_owner'ı olduğu marka — profile lookup'ı request-cache'le
	if brand_owner:
		owner_user = _brand_owner_user_cached(brand_owner)
		if owner_user and owner_user == user:
			return True

	# Diğer markalara (başkasının önerdiği/sahip olduğu) erişim yok
	return False


def _brand_owner_user_cached(seller_profile):
	"""Request-scoped cache for Admin Seller Profile → user lookups."""
	if not hasattr(frappe.local, "_brand_owner_cache"):
		frappe.local._brand_owner_cache = {}
	cache = frappe.local._brand_owner_cache
	if seller_profile in cache:
		return cache[seller_profile]
	value = frappe.db.get_value("Admin Seller Profile", seller_profile, "user") or ""
	cache[seller_profile] = value
	return value


# ── HD Ticket (Headless Helpdesk, marketplace routing) ─────────────────────
# Erişim kuralları:
#   - Full access: Administrator, System Manager, Support Manager, Agent Manager
#   - Agent + HD Team üyesi (satıcı): sadece kendi team'lerinin ticket'ları
#   - Agent (team'i yok): sadece Platform Support team'i
#   - Müşteri / diğer: sadece kendi raised_by ticket'ları

_HELPDESK_FULL_ACCESS_ROLES = frozenset(
	{
		"System Manager",
		"Support Manager",
		"Agent Manager",
	}
)

_PLATFORM_SUPPORT_TEAM = "Platform Support"


def _helpdesk_user_teams(user):
	"""User'in uyesi oldugu HD Team isimleri."""
	if not user or user == "Guest":
		return []
	rows = frappe.get_all(
		"HD Team Member",
		filters={"user": user},
		fields=["parent"],
	)
	return [r.parent for r in rows]


def helpdesk_ticket_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))
	if roles & _HELPDESK_FULL_ACCESS_ROLES:
		return ""

	escaped_user = frappe.db.escape(user)
	own_clause = f"`tabHD Ticket`.`raised_by` = {escaped_user}"

	# Agent (satici) admin panelde sadece team is yukunu gorur — kendi acitigi
	# ticket'lar alici baglaminda storefront'tan erisilir, burada gizli.
	if "Agent" in roles:
		teams = _helpdesk_user_teams(user)
		if teams:
			placeholders = ", ".join(frappe.db.escape(t) for t in teams)
			team_clause = f"`tabHD Ticket`.`agent_group` IN ({placeholders})"
		else:
			team_clause = f"`tabHD Ticket`.`agent_group` = {frappe.db.escape(_PLATFORM_SUPPORT_TEAM)}"
		return f"({team_clause} AND `tabHD Ticket`.`raised_by` != {escaped_user})"

	# Musteri / diger — sadece kendi acitigi ticket'lar
	return own_clause


def helpdesk_ticket_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & _HELPDESK_FULL_ACCESS_ROLES:
		return True

	agent_group = getattr(doc, "agent_group", None) if not isinstance(doc, dict) else doc.get("agent_group")
	raised_by = getattr(doc, "raised_by", None) if not isinstance(doc, dict) else doc.get("raised_by")

	if "Agent" in roles:
		# Self-ticket: alici baglami (storefront). Read izinli, yazma islemleri
		# (reply/status/priority) yasak — admin panelde ajan olarak mudahale
		# edemesin.
		if raised_by == user:
			return ptype == "read"
		teams = _helpdesk_user_teams(user)
		if teams:
			return agent_group in teams
		return agent_group == _PLATFORM_SUPPORT_TEAM

	return raised_by == user


# ── CRM scope (Marketplace Seller, headless Frappe CRM) ────────────────────
# Frappe CRM hiçbir scope filtre uygulamıyor — tüm Lead/Deal/Org/Contact
# tüm site genelinde görünür. Marketplace Seller rolündeki kullanıcı yalnız
# kendi `seller` (Admin Seller Profile) field'ına bağlı kayıtları görmeli.
#
# Erişim kuralları (her CRM doctype için aynı):
#   - System Manager / Marketplace Admin / Sales User / Sales Manager: full
#   - Marketplace Seller: seller = kendi profili
#   - Diğer (Buyer vb.): hiçbir kayıt
#
# `seller` field'ı patches.add_seller_to_crm_doctypes ile eklenmiş Custom
# Field'tır.

_CRM_FULL_ACCESS_ROLES = frozenset(
	{
		"System Manager",
		"Marketplace Admin",
		"Sales User",
		"Sales Manager",
		"Sales Master Manager",
	}
)


def _is_marketplace_seller(user):
	"""User'ın Marketplace Seller veya Seller rolü var mı."""
	if not user or user == "Guest":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & {"Marketplace Seller", "Seller"})


def _crm_query_for_doctype(user, doctype_table):
	"""Generic CRM permission query üreteci.

	doctype_table: SQL'deki tablo adı, örn. "tabCRM Lead"
	Returns: WHERE clause string (boş string = tüm erişim, "1=0" = engellendi)
	"""
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))
	if roles & _CRM_FULL_ACCESS_ROLES:
		return ""

	# Marketplace Seller — kendi profile'ı + kendi oluşturduğu eski kayıtlar.
	# `seller = profile` ana izolasyon kuralı; eski kayıtlarda autoset hook
	# henüz aktif değilse `seller` NULL kalmış olabilir → `owner = user`
	# fallback'i o kayıtlara erişimi açar (kendi yarattıkları için zaten güvenli).
	if "Marketplace Seller" in roles or "Seller" in roles:
		profile = _get_seller_profile_name(user)
		escaped_user = frappe.db.escape(user)
		if profile:
			escaped = frappe.db.escape(profile)
			return (
				f"(`{doctype_table}`.`seller` = {escaped} "
				f"OR `{doctype_table}`.`owner` = {escaped_user})"
			)
		return f"`{doctype_table}`.`owner` = {escaped_user}"

	# Diğer System User'lar (Buyer hariç tanınmamış admin paneli kullanıcıları)
	# — CRM tamamen kilitli yerine kişisel scope: sadece kendi oluşturduğu kayıtlar.
	if "Buyer" in roles:
		return "1=0"
	escaped_user = frappe.db.escape(user)
	return f"`{doctype_table}`.`owner` = {escaped_user}"


def _crm_has_permission_for_doc(doc, ptype, user):
	"""Generic CRM bireysel doc permission check'i.

	Marketplace Seller yalnız kendi `seller` profile'ına eşleşen kayıtları
	görebilir; admin/sistem havuzu (seller NULL) ve diğer satıcıların kayıtları
	tamamen gizlidir. Yeni kayıt oluşturma sırasında doc.seller boş gelir —
	`crm_seller_autoset.autoset_seller` before_insert hook'u onu doldurduğu için
	`ptype == "create"` durumunu izinli geçiyoruz.

	doc: Document veya dict; `seller` alanı içermeli (ya da pluck'lanır).
	"""
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & _CRM_FULL_ACCESS_ROLES:
		return True

	if "Marketplace Seller" in roles or "Seller" in roles:
		profile = _get_seller_profile_name(user)
		seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
		owner_val = getattr(doc, "owner", None) if not isinstance(doc, dict) else doc.get("owner")
		if ptype == "create" and not seller_val:
			return True
		# Profile eşleşirse veya eski (seller=NULL) kayıt kendi oluşturduğuysa eriş
		if profile and seller_val == profile:
			return True
		return owner_val == user

	# Buyer dışındaki System User'lar — kendi oluşturduğu kayıtlara erişim
	if "Buyer" in roles:
		return False
	if ptype == "create":
		return True
	owner_val = getattr(doc, "owner", None) if not isinstance(doc, dict) else doc.get("owner")
	return owner_val == user


# Doctype-spesifik wrapper'lar (hooks.py'a kayıt için ayrı isimler gerek)


def crm_lead_query_conditions(user):
	return _crm_query_for_doctype(user, "tabCRM Lead")


def crm_lead_has_permission(doc, ptype, user):
	return _crm_has_permission_for_doc(doc, ptype, user)


def crm_deal_query_conditions(user):
	return _crm_query_for_doctype(user, "tabCRM Deal")


def crm_deal_has_permission(doc, ptype, user):
	return _crm_has_permission_for_doc(doc, ptype, user)


def crm_organization_query_conditions(user):
	return _crm_query_for_doctype(user, "tabCRM Organization")


def crm_organization_has_permission(doc, ptype, user):
	return _crm_has_permission_for_doc(doc, ptype, user)


def contact_query_conditions(user):
	# Contact doctype tüm sistem genelinde kullanılır (User profili, Address vb.)
	# — Marketplace Seller yalnızca kendi `seller`'ı olan Contact'ları görür;
	# admin/sistem kişileri (seller NULL) ve diğer satıcıların kişileri gizli.
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & _CRM_FULL_ACCESS_ROLES:
		return ""
	if "Marketplace Seller" in roles or "Seller" in roles:
		profile = _get_seller_profile_name(user)
		if profile:
			escaped = frappe.db.escape(profile)
			return f"`tabContact`.`seller` = {escaped}"
		return "1=0"  # profili olmayan satıcı user'ı → hiçbir şey görmesin
	return ""  # Buyer vb. → standart Contact (sistem genelinde) erişimi


def contact_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & _CRM_FULL_ACCESS_ROLES:
		return True
	if "Marketplace Seller" in roles or "Seller" in roles:
		profile = _get_seller_profile_name(user)
		if not profile:
			return False
		seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
		# Yeni Contact oluşturma — autoset hook seller'ı satıcının profile'ı yapacak
		if ptype == "create" and not seller_val:
			return True
		return seller_val == profile
	return True  # diğer roller → standart Contact erişimi


def crm_task_query_conditions(user):
	return _crm_query_for_doctype(user, "tabCRM Task")


def crm_task_has_permission(doc, ptype, user):
	return _crm_has_permission_for_doc(doc, ptype, user)


def fcrm_note_query_conditions(user):
	return _crm_query_for_doctype(user, "tabFCRM Note")


def fcrm_note_has_permission(doc, ptype, user):
	return _crm_has_permission_for_doc(doc, ptype, user)


def crm_call_log_query_conditions(user):
	return _crm_query_for_doctype(user, "tabCRM Call Log")


def crm_call_log_has_permission(doc, ptype, user):
	return _crm_has_permission_for_doc(doc, ptype, user)
