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
from frappe.utils import flt

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

# K7 fix: DocTypes that require an OPERATIONAL subscription for WRITE operations.
# Suspended/canceled subscription'ı olan satıcılar read yapabilir (audit) ama
# write (yeni listing, sipariş, ürün) yapamaz. Past_due grace period dahil edilir
# (faturayı ödeyebilsin diye, K2 fix).
SUBSCRIPTION_GATED_DOCTYPES = frozenset(
	[
		"Listing",
		"Order",
		"Admin Seller Profile",
		"Seller Inquiry",
		"Listing Certification",
		"Seller Certification",
		"Seller Category",
		"Seller Gallery Image",
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
	        "Admin Seller Profile": "tradehub_core.permissions.get_tenant_permission_query_conditions",
	        "Listing": "tradehub_core.permissions.get_tenant_permission_query_conditions",
	    }
	"""
	user = user or frappe.session.user

	# System Manager can see all tenants
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	# Get current tenant context
	tenant = get_current_tenant()

	if not tenant:
		# Sprint 2 (revised, 2026-05-15): Seller Profile → Admin Seller Profile.
		# No tenant context — allow access only to own records based on owner.
		return f"`tabAdmin Seller Profile`.`owner` = '{frappe.db.escape(user)}'"

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
	        "Admin Seller Profile": "tradehub_core.permissions.has_tenant_permission",
	        "Listing": "tradehub_core.permissions.has_tenant_permission",
	    }
	"""
	user = user or frappe.session.user
	ptype = ptype or "read"

	# System Manager has full access
	if user == "Administrator" or _is_platform_full_access(user):
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

	# K7 fix: subscription must be operational for write ops on gated doctypes.
	# Suspended/canceled subscription → write yasak (read serbest, audit için).
	if not _check_subscription_active(user_tenant, doctype, ptype):
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

	Sprint 2 — S26: Eski User.kyc_verified field hayali idi. Şimdi
	`User Profile.kyc_status == "Verified"` üzerinden kontrol edilir.
	Bireysel kullanıcılar için (account_type=Individual) KYC zorunlu değil
	(graceful pass-through).

	Args:
	    user (str): User to check.
	    doctype (str): DocType being accessed.

	Returns:
	    bool: True if access is allowed, False if denied.
	"""
	if doctype not in FINANCIAL_DOCTYPES:
		return True

	cache_key = f"kyc_verified:{user}"
	kyc_verified = frappe.cache().get_value(cache_key)

	if kyc_verified is None:
		# User Profile.kyc_status veya kyb_status (Sprint 3'te ABAC genişletilebilir)
		row = frappe.db.get_value(
			"User Profile",
			{"user": user},
			["account_type", "kyc_status", "kyb_status"],
			as_dict=True,
		)
		if not row:
			# User Profile yok — Sprint 2 öncesi user veya orphan. İzin ver.
			kyc_verified = 1
		elif row.account_type == "Individual":
			# Bireysel — KYC zorunlu değil
			kyc_verified = 1
		elif row.kyc_status == "Verified" or row.kyb_status == "Verified":
			kyc_verified = 1
		else:
			kyc_verified = 0
		frappe.cache().set_value(cache_key, kyc_verified, expires_in_sec=300)

	return bool(kyc_verified)


def _check_aml_sanctions(user, doctype):
	"""
	ABAC Layer: Block access for users flagged by AML or sanctions screening.

	KYB Verification üzerinden AML/sanctions kontrolü. aml_check_status veya
	sanctions_status field'ı "Hit Found" / "Match Found" ise erişim engellenir.
	Field'lar henüz yoksa graceful fallback (izin ver) — ama field varsa kontrol eder.

	Args:
	    user (str): User to check.
	    doctype (str): DocType being accessed.

	Returns:
	    bool: True if access is allowed, False if blocked.
	"""
	if doctype not in AML_SENSITIVE_DOCTYPES:
		return True

	# KYB Verification'dan AML/sanctions field'larını kontrol et.
	# Field'lar henüz eklenmemişse (hasattr/column yok) graceful fallback.
	try:
		kyb = frappe.db.get_value(
			"KYB Verification",
			{"user": user, "docstatus": 1},
			["aml_check_status", "sanctions_status"],
			as_dict=True,
		)
	except Exception:
		# Field'lar henüz yoksa (column unknown) → graceful fallback: izin ver
		return True

	if not kyb:
		# KYB kaydı yok → AML kontrolü yapılamaz, izin ver (legacy user)
		return True

	blocked_statuses = {"Hit Found", "Match Found"}
	if (kyb.get("aml_check_status") or "") in blocked_statuses:
		frappe.log_error(
			f"AML gate: {user} blocked — aml_check_status={kyb.aml_check_status}",
			"AML/Sanctions Gate",
		)
		return False
	if (kyb.get("sanctions_status") or "") in blocked_statuses:
		frappe.log_error(
			f"AML gate: {user} blocked — sanctions_status={kyb.sanctions_status}",
			"AML/Sanctions Gate",
		)
		return False

	return True


def _check_subscription_active(user_tenant, doctype, ptype):
	"""K7 fix: subscription operational değilse SUBSCRIPTION_GATED_DOCTYPES
	üzerinde write op'ları reddet.

	Operational = trial/active/past_due (past_due grace period dahil — K2).
	Suspended/canceled → write yasak (read serbest, audit için).

	Args:
	    user_tenant: Admin Seller Profile.name
	    doctype: erişilen DocType
	    ptype: read/write/submit/create/delete/cancel

	Returns:
	    True izin ver, False reddet.
	"""
	# Sadece subscription-bağlı doctype'ları gate'le
	if doctype not in SUBSCRIPTION_GATED_DOCTYPES:
		return True
	# Sadece destructive op'ları gate'le (read serbest)
	if ptype not in ("write", "submit", "create", "delete", "cancel"):
		return True
	# Tenant yok = ABAC scope dışı (owner/admin yolu zaten devreye girer)
	if not user_tenant:
		return True

	from tradehub_core.entitlement import is_subscription_operational

	return is_subscription_operational(user_tenant)


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
	if user == "Administrator" or _is_platform_full_access(user):
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
	"""Return the Admin Seller Profile name for the given user.

	D6: Tek-source-of-truth `tenant_utils._get_seller_profile_for_user`'a
	delege. Test stub'larında tenant_utils import edilmemişse fallback
	(legacy lookup sırası) ile çalışmaya devam eder.
	Detay: utils/tenant.py:86 `_get_seller_profile_for_user`.
	"""
	try:
		from tradehub_core.utils.tenant import _get_seller_profile_for_user

		return _get_seller_profile_for_user(user)
	except (ImportError, AttributeError):
		# Test fallback — production'da tenant_utils her zaman yüklü
		profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		if not profile:
			profile = frappe.db.get_value("Admin Seller Profile", {"owner": user}, "name")
		if not profile:
			profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")
		return profile


# ── Listing ──────────────────────────────────────────────────────────────────


def listing_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabListing`.`seller_profile` = {frappe.db.escape(profile)}"
	return "1=0"


def listing_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
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
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabAdmin Seller Profile`.`name` = {frappe.db.escape(profile)}"
	return "1=0"


def admin_seller_profile_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	profile = _get_seller_profile_name(user)
	doc_name = getattr(doc, "name", None) if not isinstance(doc, dict) else doc.get("name")
	return profile and doc_name == profile


# ── Seller Balance ───────────────────────────────────────────────────────────
# Sprint 2 (revised, 2026-05-15): Seller Balance.seller artık Admin Seller Profile.name (SEL-XXXXX).
# Sprint 1'de field options "Admin Seller Profile" olarak güncellendi.


def seller_balance_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	# Admin Seller Profile lookup: kullanıcının mağazası filter
	profile = _get_seller_profile_name(user)
	if not profile:
		return "1=0"
	return f"`tabSeller Balance`.`seller` = {frappe.db.escape(profile)}"


def seller_balance_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	# Sprint 2 (revised, 2026-05-15): seller artık Admin Seller Profile.name (SEL-XXXXX),
	# user email değil. Kullanıcının kendi mağazasıyla eşleşmeli.
	profile = _get_seller_profile_name(user)
	return seller_val == profile


# ── Seller Review ────────────────────────────────────────────────────────────
# Seller Review.seller links to Admin Seller Profile.


def seller_review_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Review`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_review_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Listing Review ───────────────────────────────────────────────────────────
# Listing Review:
#   - Marketplace Admin / System Manager  → tüm kayıtlar
#   - Marketplace Seller                  → kendi seller profilinin yorumları
#   - Buyer / Marketplace Buyer           → kendi yazdığı yorumlar (reviewer_user)
#   - Public list (allow_guest API)       → status='Approved' filtresi API'da uygulanır;
#                                           desk listesinde guest ulaşmaz.


def listing_review_query_conditions(user):
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabListing Review`.`seller` = {frappe.db.escape(profile)}"
	# Buyer kendi yorumlarını görür
	return f"`tabListing Review`.`reviewer_user` = {frappe.db.escape(user)}"


def listing_review_has_permission(doc, ptype, user):
	# Administrator + admin rolleri her zaman izinli
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return True

	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	reviewer_val = (
		getattr(doc, "reviewer_user", None) if not isinstance(doc, dict) else doc.get("reviewer_user")
	)
	# Satıcı kendi ürünlerinin yorumlarını okuyabilir + reply yazabilir
	profile = _get_seller_profile_name(user)
	if profile and seller_val == profile:
		if ptype in ("read", "write"):  # write seller_reply için gerekli
			return True
	# Buyer kendi yorumunu okuyabilir/güncelleyebilir
	if reviewer_val and reviewer_val == user:
		return True
	# Explicit deny — cross-tenant erişimi engelle (fall-through yerine)
	return False


# ── Review Helpful Vote ─────────────────────────────────────────────────────
# Buyer yalnız kendi oyunu görür/silebilir; admin tümünü görür.


def review_helpful_vote_query_conditions(user):
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return ""
	return f"`tabReview Helpful Vote`.`voter` = {frappe.db.escape(user)}"


def review_helpful_vote_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return True
	voter = getattr(doc, "voter", None) if not isinstance(doc, dict) else doc.get("voter")
	if voter and voter == user:
		return True
	return False


# ── Review Abuse Report ─────────────────────────────────────────────────────


def review_abuse_report_query_conditions(user):
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return ""
	# Reporter kendi ihbarını görür; satıcı da kendi ürününe gelen ihbarları görmek isteyebilir.
	# Faz 2'de basit: sadece reporter görsün.
	return f"`tabReview Abuse Report`.`reporter` = {frappe.db.escape(user)}"


def review_abuse_report_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return True
	reporter = getattr(doc, "reporter", None) if not isinstance(doc, dict) else doc.get("reporter")
	if reporter and reporter == user:
		return True
	return False


# ── Faz 4: Listing Question ─────────────────────────────────────────────────


def listing_question_query_conditions(user):
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return ""
	# Public Approved soruları herkese; ama desk listesi için: asker veya seller
	profile = _get_seller_profile_name(user)
	if profile:
		# Satıcı kendi ürünlerinin sorularını görür
		return (
			f"`tabListing Question`.`listing` IN "
			f"(SELECT name FROM `tabListing` WHERE seller_profile = {frappe.db.escape(profile)})"
		)
	return f"`tabListing Question`.`asker` = {frappe.db.escape(user)}"


def listing_question_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return True
	asker = getattr(doc, "asker", None) if not isinstance(doc, dict) else doc.get("asker")
	if asker == user:
		return True
	# Listing question: satıcı kendi listing'inin sorularını da görebilmeli
	listing = getattr(doc, "listing", None) if not isinstance(doc, dict) else doc.get("listing")
	if listing and ptype == "read":
		profile = _get_seller_profile_name(user)
		if profile:
			seller_of_listing = frappe.db.get_value("Listing", listing, "seller_profile")
			if seller_of_listing == profile:
				return True
	return False


# ── Faz 4: Order Dispute ────────────────────────────────────────────────────


def order_dispute_query_conditions(user):
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabOrder Dispute`.`seller` = {frappe.db.escape(profile)}"
	return f"`tabOrder Dispute`.`buyer` = {frappe.db.escape(user)}"


def order_dispute_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return True
	buyer = getattr(doc, "buyer", None) if not isinstance(doc, dict) else doc.get("buyer")
	seller = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	if buyer == user:
		return True
	profile = _get_seller_profile_name(user)
	if profile and seller == profile and ptype == "read":
		return True
	return False


# ── Faz 4: Trusted Reviewer Invitation ──────────────────────────────────────


def trusted_reviewer_invitation_query_conditions(user):
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return ""
	return f"`tabTrusted Reviewer Invitation`.`user` = {frappe.db.escape(user)}"


def trusted_reviewer_invitation_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & {"System Manager", "Marketplace Admin"}:
		return True
	owner = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	if owner == user:
		return True
	return False


# ── Seller Category ──────────────────────────────────────────────────────────
# Seller Category.seller links to Admin Seller Profile.


def seller_category_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Category`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_category_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Seller Gallery Image ─────────────────────────────────────────────────────
# Child table of Admin Seller Profile — filter by parent.


def seller_gallery_image_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Gallery Image`.`parent` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_gallery_image_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	profile = _get_seller_profile_name(user)
	parent_val = getattr(doc, "parent", None) if not isinstance(doc, dict) else doc.get("parent")
	return profile and parent_val == profile


# ── KYB Verification ─────────────────────────────────────────────────────────
# KYB Verification.user links to User.


def kyb_verification_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	return f"`tabKYB Verification`.`user` = {frappe.db.escape(user)}"


def kyb_verification_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	user_val = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	return user_val == user


# ── Order ─────────────────────────────────────────────────────────────────────
# Order.seller links to Admin Seller Profile.


def order_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	# Platform-full rolleri tüm Order'ları görür (System Manager dahil)
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	# Seller tarafı — kendi seller_profile'ına bağlı order'lar
	profile = _get_seller_profile_name(user)
	# Buyer tarafı — kendi user veya org'undaki diğer buyer'lar
	orgs = _user_organizations(user)

	clauses: list[str] = []
	if profile:
		clauses.append(f"`tabOrder`.`seller` = {frappe.db.escape(profile)}")
	# Kullanıcı kendi açtığı order'ı her zaman görür
	clauses.append(f"`tabOrder`.`buyer` = {frappe.db.escape(user)}")
	if orgs:
		# Buyer organization üyelerinin order'ları (approver/admin/finance görsün)
		org_list = ", ".join(frappe.db.escape(o) for o in orgs)
		clauses.append(
			"`tabOrder`.`buyer` IN ("
			"SELECT `name` FROM `tabUser` "
			f"WHERE `tradehub_parent_organization` IN ({org_list})"
			")"
		)
	return "(" + " OR ".join(clauses) + ")"


def order_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True

	seller_val = _doc_field(doc, "seller")
	buyer_val = _doc_field(doc, "buyer")

	# Seller-side: kendi mağazasının order'ı
	profile = _get_seller_profile_name(user)
	if profile and seller_val == profile:
		return True

	# Buyer-side: kendi açtığı veya aynı organizasyon
	if buyer_val == user:
		return True
	if buyer_val:
		buyer_org = frappe.db.get_value("User", buyer_val, "tradehub_parent_organization")
		if buyer_org and buyer_org in _user_organizations(user):
			return True

	return False


# ── Seller Inquiry ────────────────────────────────────────────────────────────
# Seller Inquiry.seller links to Admin Seller Profile.


def seller_inquiry_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Inquiry`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_inquiry_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return profile and seller_val == profile


# ── Certification Type ───────────────────────────────────────────────────────
# Sellers should only see Approved certification types.


def certification_type_query_conditions(user):
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	escaped_user = frappe.db.escape(user)
	return (
		f"(`tabCertification Type`.`status` = 'Approved'"
		f" OR `tabCertification Type`.`suggested_by` = {escaped_user})"
	)


def certification_type_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
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
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	return f"`tabSearch History`.`user` = {frappe.db.escape(user)}"


def search_history_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
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
			return f"(`{doctype_table}`.`seller` = {escaped} OR `{doctype_table}`.`owner` = {escaped_user})"
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


# ── RFQ ──────────────────────────────────────────────────────────────────────
# Gates File access (is_private=1) on RFQ attachments. Frappe core calls
# RFQ.has_permission when serving /private/files/... for a File whose
# attached_to_doctype = "RFQ".


def rfq_has_permission(doc, ptype, user):
	"""Authorize RFQ access (and by proxy, its private file attachments).

	Read rules:
	- Buyer (owner) ✓ always
	- Admin (System Manager / Marketplace Admin) ✓ always
	- Seller ✓ if any of:
	    a) RFQ Quote already submitted by this seller for this RFQ
	    b) RFQ is Approved AND seller has an Active Seller Category matching doc.category
	- Write/Create: only Buyer (owner) or Admin
	- Delete: Admin only
	"""
	if user == "Guest":
		return False

	roles = frappe.get_roles(user)
	if "System Manager" in roles or "Marketplace Admin" in roles:
		return True

	# doctype-level (doc is None) — defer to per-doc check; allow listing-level read
	if doc is None:
		return True

	doc_buyer = getattr(doc, "buyer", None) if not isinstance(doc, dict) else doc.get("buyer")
	doc_name = getattr(doc, "name", None) if not isinstance(doc, dict) else doc.get("name")
	doc_status = getattr(doc, "status", None) if not isinstance(doc, dict) else doc.get("status")
	doc_category = getattr(doc, "category", None) if not isinstance(doc, dict) else doc.get("category")

	# Buyer (owner) — full read/write on their own RFQ
	if doc_buyer == user:
		return True

	# Seller — read only, conditional
	if "Seller" in roles:
		if ptype != "read":
			return False
		# (a) Already submitted quote
		if doc_name and frappe.db.exists("RFQ Quote", {"rfq": doc_name, "seller": user}):
			return True
		# (b) Approved + category match
		if doc_status != "Approved" or not doc_category:
			return False
		profile = _get_seller_profile_name(user)
		if not profile:
			return False
		return bool(
			frappe.db.exists(
				"Seller Category",
				{"seller": profile, "category": doc_category, "status": "Active", "is_enabled": 1},
			)
		)

	return False


# ── User Profile (Sprint 2 — User Profile Birleşmesi) ─────────────────────────
# Platform rolleri tüm User Profile'lara erişebilir; Buyer/Seller sadece kendi profili.

# D8: Platform-full-access rol haritası (mevcut ve gelecek için)
#
# Bu set içindeki roller her permission_query_conditions / has_permission
# fonksiyonunda otomatik bypass alır.
#
# Roller arası ayrım (tasarım niyeti):
#   - System Manager      → Frappe core super-admin (her şeyi yapar; emergency)
#   - Marketplace Admin   → Legacy platform admin (62+ standart DocPerm).
#                          v15 öncesi platform operasyon ekibinin rolü.
#                          Yeni özelliklerde kullanılmaz; yeni doctype'lar
#                          için **Platform Admin** tercih edilmeli.
#   - Platform Admin      → v15+ standart platform admin. Yeni feature'lar
#                          (Permission Console, Authorization Simulator vb.)
#                          için canonical rol.
#   - Platform Super Admin → Marketplace Admin + Platform Finance +
#                          Compliance Officer + Support Agent kompozit
#                          Role Profile. Tek başına DocPerm taşımaz; içerdiği
#                          rolleri bundle eder.
#   - Compliance Officer  → PII + Forensics rolü. Audit log + Anomaly
#                          dashboard erişimi. Sub-Admin değil; sadece okuma.
#
# Migration path: yeni feature'lar `Platform Admin` üzerinden gider;
# Marketplace Admin geriye dönük uyumluluk için tutulur.
_PLATFORM_FULL_ACCESS_ROLES = frozenset(
	{
		"System Manager",
		"Marketplace Admin",
		"Platform Super Admin",
		"Platform Admin",
		"Compliance Officer",
	}
)

# Platform Finance ek olarak audit log'ları okuyabilmeli (finansal denetim
# amacıyla); ama PII Policy / Anomaly Rule / Permission Override gibi yönetim
# doctype'larına dokunmamalı — `_PLATFORM_FULL_ACCESS_ROLES`'a değil bu set'e
# eklendi.
_PLATFORM_AUDIT_READ_ROLES = _PLATFORM_FULL_ACCESS_ROLES | {"Platform Finance"}


def user_profile_query_conditions(user):
	"""User Profile list query filtresi.
	Platform rolleri tümünü görür; diğerleri sadece kendi profilini."""
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & _PLATFORM_FULL_ACCESS_ROLES:
		return ""
	# Platform Helpdesk: read-only erişim (DocPerm tarafında permlevel 0 read)
	if "Platform Helpdesk" in roles:
		return ""
	# Buyer/Seller: sadece kendi User Profile
	return f"`tabUser Profile`.user = {frappe.db.escape(user)}"


def user_profile_has_permission(doc, ptype, user):
	"""User Profile per-doc permission."""
	if not user or user == "Guest":
		return False
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & _PLATFORM_FULL_ACCESS_ROLES:
		return True
	if "Platform Helpdesk" in roles and ptype == "read":
		return True
	# Buyer/Seller: sadece kendi profili
	doc_user = getattr(doc, "user", None) if not isinstance(doc, dict) else doc.get("user")
	return doc_user == user


# ---------------------------------------------------------------------------
# Bulk Import + ECA + Regex + Seller Template Profile permission handlers
# ---------------------------------------------------------------------------
# Admin/System Manager tüm kayıtları görür; satıcı sadece kendisine ait
# kayıtları. Per-doc kontrol (has_permission) ek olarak ptype'a göre platform
# kapsamlı ECA Rule / System Regex Library için read-only erişime izin verir.


def _is_admin(user: str) -> bool:
	roles = frappe.get_roles(user)
	return "System Manager" in roles or "Marketplace Admin" in roles


def _seller_of(user: str) -> str | None:
	# Kanonik tenant resolver'ı kullan (User.tradehub_tenant → Admin Seller
	# Profile.user → .email). `owner` (Frappe kayıt-yaratıcı sistem alanı)
	# ile aramak hatalıydı: profili admin/onboarding oluşturan satıcılarda
	# owner != satıcı user → resolver None döner, has_permission "create"
	# reddederdi (toplu içe aktarım job'ı patlardı). Resolver, import
	# endpoint'inin (get_current_seller_profile) kullandığıyla aynı olmalı.
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	return _get_seller_profile_for_user(user)


def bulk_import_job_query_conditions(user):
	"""Satıcı sadece kendi job'larını görür. Admin tümünü."""
	if _is_admin(user):
		return ""
	seller = _seller_of(user)
	if not seller:
		return "1=0"
	return f"`tabBulk Import Job`.seller_profile = {frappe.db.escape(seller)}"


def bulk_import_job_has_permission(doc, ptype, user):
	if _is_admin(user):
		return True
	seller = _seller_of(user)
	doc_seller = (
		getattr(doc, "seller_profile", None) if not isinstance(doc, dict) else doc.get("seller_profile")
	)
	return bool(seller) and doc_seller == seller


def eca_rule_query_conditions(user):
	"""Satıcı: kendi rules + Platform rules (read). Admin: all."""
	if _is_admin(user):
		return ""
	seller = _seller_of(user)
	if not seller:
		return "1=0"
	return (
		f"(`tabECA Rule`.rule_scope = 'Platform' OR "
		f"(`tabECA Rule`.rule_scope = 'Per-Seller' AND "
		f"`tabECA Rule`.seller_profile = {frappe.db.escape(seller)}))"
	)


def eca_rule_has_permission(doc, ptype, user):
	if _is_admin(user):
		return True
	seller = _seller_of(user)
	if not seller:
		return False
	rule_scope = getattr(doc, "rule_scope", None) if not isinstance(doc, dict) else doc.get("rule_scope")
	doc_seller = (
		getattr(doc, "seller_profile", None) if not isinstance(doc, dict) else doc.get("seller_profile")
	)
	if rule_scope == "Platform":
		# Satıcı Platform kuralını sadece okuyabilir.
		return ptype == "read"
	return doc_seller == seller


def eca_rule_log_query_conditions(user):
	"""Satıcı kendi kurallarının log'larını görür."""
	if _is_admin(user):
		return ""
	seller = _seller_of(user)
	if not seller:
		return "1=0"
	# Subquery: log.eca_rule → rule.seller_profile = my_seller
	return (
		f"`tabECA Rule Log`.eca_rule IN ("
		f"SELECT name FROM `tabECA Rule` WHERE seller_profile = {frappe.db.escape(seller)})"
	)


def regex_pattern_library_query_conditions(user):
	if _is_admin(user):
		return ""
	seller = _seller_of(user)
	if not seller:
		return "1=0"
	return (
		f"(`tabRegex Pattern Library`.scope = 'System' OR "
		f"(`tabRegex Pattern Library`.scope = 'Seller Override' AND "
		f"`tabRegex Pattern Library`.seller_profile = {frappe.db.escape(seller)}))"
	)


def regex_pattern_library_has_permission(doc, ptype, user):
	if _is_admin(user):
		return True
	seller = _seller_of(user)
	if not seller:
		return False
	scope = getattr(doc, "scope", None) if not isinstance(doc, dict) else doc.get("scope")
	doc_seller = (
		getattr(doc, "seller_profile", None) if not isinstance(doc, dict) else doc.get("seller_profile")
	)
	if scope == "System":
		return ptype == "read"
	return doc_seller == seller


def seller_value_mapping_query_conditions(user):
	"""Satıcı yalnız kendi değer eşleştirmelerini görür."""
	if _is_admin(user):
		return ""
	seller = _seller_of(user)
	if not seller:
		return "1=0"
	return f"`tabSeller Value Mapping`.seller_profile = {frappe.db.escape(seller)}"


def seller_value_mapping_has_permission(doc, ptype, user):
	if _is_admin(user):
		return True
	seller = _seller_of(user)
	if not seller:
		return False
	doc_seller = (
		getattr(doc, "seller_profile", None) if not isinstance(doc, dict) else doc.get("seller_profile")
	)
	return doc_seller == seller


def seller_template_profile_query_conditions(user):
	if _is_admin(user):
		return ""
	seller = _seller_of(user)
	if not seller:
		return "1=0"
	return f"`tabSeller Template Profile`.seller = {frappe.db.escape(seller)}"


def seller_template_profile_has_permission(doc, ptype, user):
	if _is_admin(user):
		return True
	seller = _seller_of(user)
	doc_seller = getattr(doc, "seller", None) if not isinstance(doc, dict) else doc.get("seller")
	return bool(seller) and doc_seller == seller


# ─────────────────────────────────────────────────────────────────────────────
# FAZ 2/3 — ReBAC/Audit DocType izolasyonu
# ─────────────────────────────────────────────────────────────────────────────
# Aşağıdaki 11 yeni doctype için tenant/organization scope ve per-doc kontrol.
# DocPerm tarafındaki if_owner=1 tuzağı kaldırıldı (Order Approval, Approval
# Rule) — yetkilendirmeyi tamamen burada belirliyoruz.
#
# Buyer-side scope: User.tradehub_parent_organization (+ ancestors)
# Seller-side scope: Admin Seller Profile (tenant)
# Platform-only:    System Manager / Marketplace Admin / Compliance Officer


def _doc_field(doc, name, default=None):
	"""SimpleNamespace / dict / Document üçü için ortak getter."""
	if doc is None:
		return default
	if isinstance(doc, dict):
		return doc.get(name, default)
	return getattr(doc, name, default)


def _user_organizations(user):
	"""Buyer user'ın bağlı olduğu organization + ataları.

	Returns:
	    set[str] — boşsa user bir org'a bağlı değil.
	"""
	if not user or user in ("Guest", "Administrator"):
		return set()
	org = frappe.db.get_value("User", user, "tradehub_parent_organization")
	if not org:
		return set()
	from tradehub_core.utils.organization_hierarchy import get_ancestors

	return {org, *get_ancestors(org)}


def _buyer_tenant_for_user(user):
	"""Buyer user'ın tenant (= Admin Seller Profile name'i). Yoksa None.

	Cost Center.tenant ve diğer buyer-tarafı seller-link'leri için kullanılır.
	"""
	if not user or user in ("Guest", "Administrator"):
		return None
	# has_column guard: tradehub_buyer_tenant custom field olmayabilir; olmayan
	# kolona get_value 1054 fırlatır → atlayıp var olan kolona düş.
	for fieldname in ("tradehub_buyer_tenant", "tradehub_tenant"):
		if not frappe.db.has_column("User", fieldname):
			continue
		val = frappe.db.get_value("User", user, fieldname)
		if val:
			return val
	return None


def _is_platform_full_access(user):
	if not user or user == "Guest":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & _PLATFORM_FULL_ACCESS_ROLES)


def _is_platform_audit_reader(user):
	"""Authorization Decision Log + Anomaly Alert için genişletilmiş okuma."""
	if not user or user == "Guest":
		return False
	roles = set(frappe.get_roles(user))
	return bool(roles & _PLATFORM_AUDIT_READ_ROLES)


# ── Order Approval ───────────────────────────────────────────────────────────
# Approver organization (+ ancestors) içindeki tüm approval'ları görür;
# Requisitioner kendi başlattıkları + admin scope dışındaki herkese KAPALI.


def order_approval_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	orgs = _user_organizations(user)
	clauses = []
	if orgs:
		org_list = ", ".join(frappe.db.escape(o) for o in orgs)
		clauses.append(f"`tabOrder Approval`.`organization` IN ({org_list})")
	# Requisitioner kendi başlattığı approval'ı her zaman görür
	clauses.append(f"`tabOrder Approval`.`requisitioner` = {frappe.db.escape(user)}")
	return "(" + " OR ".join(clauses) + ")"


def order_approval_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True
	doc_org = _doc_field(doc, "organization")
	doc_req = _doc_field(doc, "requisitioner")
	if doc_req == user:
		return True
	if doc_org and doc_org in _user_organizations(user):
		return True
	return False


# ── Approval Rule ────────────────────────────────────────────────────────────


def approval_rule_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	orgs = _user_organizations(user)
	if not orgs:
		return "1=0"
	org_list = ", ".join(frappe.db.escape(o) for o in orgs)
	return f"`tabApproval Rule`.`organization` IN ({org_list})"


def approval_rule_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True
	doc_org = _doc_field(doc, "organization")
	# Yeni rule oluşturulurken organization henüz set edilmemiş olabilir
	if not doc_org:
		return ptype in ("create", "write")
	return doc_org in _user_organizations(user)


# ── Cost Center ──────────────────────────────────────────────────────────────
# Buyer'ın tenant'ına bağlı cost center'lar; sellerlar için tanımsız.


def cost_center_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	tenant = _buyer_tenant_for_user(user)
	if not tenant:
		# Seller veya tenant'sız user → cost center göremesin
		return "1=0"
	return f"`tabCost Center`.`tenant` = {frappe.db.escape(tenant)}"


def cost_center_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True
	doc_tenant = _doc_field(doc, "tenant")
	user_tenant = _buyer_tenant_for_user(user)
	if not user_tenant:
		return False
	# Yeni cost center'da tenant henüz set edilmemiş olabilir
	if not doc_tenant:
		return ptype in ("create", "write")
	return doc_tenant == user_tenant


# ── Store Subscription ───────────────────────────────────────────────────────
# H14 fix — abonelik kayıtları tenant izolasyonunda eksikti. Seller yalnız kendi
# mağazasının (store = Admin Seller Profile) aboneliğini OKUR; plan/status yazımı
# admin'e kapalı (C8/C9 ile tutarlı — ücretli aktivasyon ödeme/admin akışından).


def store_subscription_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	store = _get_seller_profile_name(user)
	if not store:
		return "1=0"
	return f"`tabStore Subscription`.`store` = {frappe.db.escape(store)}"


def store_subscription_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	# Yazma/oluşturma/silme yalnız admin (self-service ücretli aktivasyon yasak).
	if ptype in ("write", "create", "delete"):
		return False
	if doc is None:
		return True
	store = _get_seller_profile_name(user)
	if not store:
		return False
	return _doc_field(doc, "store") == store


# ── Owner Transfer Request ───────────────────────────────────────────────────
# Seller-side. Mevcut owner ve proposed owner görür; tenant'ın diğer
# sub-user'ları görmez (devir sürecindeki kişiler ve admin).


def owner_transfer_request_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	# Seller tenant'ı (kendi mağazasının devirleri)
	tenant = _get_seller_profile_name(user)
	clauses = [
		f"`tabOwner Transfer Request`.`current_owner` = {frappe.db.escape(user)}",
		f"`tabOwner Transfer Request`.`proposed_owner` = {frappe.db.escape(user)}",
	]
	if tenant:
		clauses.append(f"`tabOwner Transfer Request`.`tenant` = {frappe.db.escape(tenant)}")
	return "(" + " OR ".join(clauses) + ")"


def owner_transfer_request_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True
	current = _doc_field(doc, "current_owner")
	proposed = _doc_field(doc, "proposed_owner")
	doc_tenant = _doc_field(doc, "tenant")
	if user in (current, proposed):
		return True
	user_tenant = _get_seller_profile_name(user)
	return bool(user_tenant and doc_tenant == user_tenant)


# ── Role Delegation ──────────────────────────────────────────────────────────
# Delegator + delegate görür; aynı tenant'ın owner'ı da görür.


def role_delegation_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	tenant = _get_seller_profile_name(user)
	clauses = [
		f"`tabRole Delegation`.`delegator` = {frappe.db.escape(user)}",
		f"`tabRole Delegation`.`delegate` = {frappe.db.escape(user)}",
	]
	if tenant:
		clauses.append(f"`tabRole Delegation`.`tenant` = {frappe.db.escape(tenant)}")
	return "(" + " OR ".join(clauses) + ")"


def role_delegation_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True
	delegator = _doc_field(doc, "delegator")
	delegate = _doc_field(doc, "delegate")
	doc_tenant = _doc_field(doc, "tenant")
	if user in (delegator, delegate):
		return True
	user_tenant = _get_seller_profile_name(user)
	return bool(user_tenant and doc_tenant == user_tenant)


# ── Authorization Decision Log ──────────────────────────────────────────────
# Platform rolleri tüm logları görür; seller sadece kendi tenant'ının logları.


def authorization_decision_log_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	# Platform Finance dahil audit-read rolleri tüm logları görür
	if user == "Administrator" or _is_platform_audit_reader(user):
		return ""

	clauses = [f"`tabAuthorization Decision Log`.`actor` = {frappe.db.escape(user)}"]

	# Seller-side: kullanıcının tenant'ına ait loglar
	tenant = _get_seller_profile_name(user)
	if tenant:
		clauses.append(f"`tabAuthorization Decision Log`.`tenant` = {frappe.db.escape(tenant)}")

	# O5: Buyer-side — kullanıcının organizasyonu (+ ancestors) için loglar
	orgs = _user_organizations(user)
	if orgs:
		org_list = ", ".join(frappe.db.escape(o) for o in orgs)
		clauses.append(f"`tabAuthorization Decision Log`.`buyer_org` IN ({org_list})")

	return "(" + " OR ".join(clauses) + ")"


def authorization_decision_log_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_audit_reader(user):
		return True
	if doc is None:
		return True
	doc_tenant = _doc_field(doc, "tenant")
	doc_buyer_org = _doc_field(doc, "buyer_org")
	doc_actor = _doc_field(doc, "actor")
	if doc_actor == user:
		return True
	user_tenant = _get_seller_profile_name(user)
	if user_tenant and doc_tenant == user_tenant:
		return True
	# O5: buyer organization match
	if doc_buyer_org and doc_buyer_org in _user_organizations(user):
		return True
	return False


# ── Role Change Log ──────────────────────────────────────────────────────────


def role_change_log_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""

	tenant = _get_seller_profile_name(user)
	clauses = [
		f"`tabRole Change Log`.`target_user` = {frappe.db.escape(user)}",
		f"`tabRole Change Log`.`changed_by` = {frappe.db.escape(user)}",
	]
	if tenant:
		clauses.append(f"`tabRole Change Log`.`tenant` = {frappe.db.escape(tenant)}")
	return "(" + " OR ".join(clauses) + ")"


def role_change_log_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	if doc is None:
		return True
	target = _doc_field(doc, "target_user")
	changed_by = _doc_field(doc, "changed_by")
	doc_tenant = _doc_field(doc, "tenant")
	if user in (target, changed_by):
		return True
	user_tenant = _get_seller_profile_name(user)
	return bool(user_tenant and doc_tenant == user_tenant)


# ── Authorization Anomaly Alert ─────────────────────────────────────────────
# Platform-only; ek olarak tenant_scope eşleşen tenant'ın owner'ı kendi
# tenant'ının alarmlarını görebilir.


def authorization_anomaly_alert_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	# Platform Finance dahil audit-read rolleri tüm tenant'ların alertlerini görür
	if user == "Administrator" or _is_platform_audit_reader(user):
		return ""

	clauses: list[str] = []
	tenant = _get_seller_profile_name(user)
	if tenant:
		clauses.append(f"`tabAuthorization Anomaly Alert`.`tenant` = {frappe.db.escape(tenant)}")
	# D10: Buyer-side — kullanıcının organizasyonu için alarmlar
	orgs = _user_organizations(user)
	if orgs:
		org_list = ", ".join(frappe.db.escape(o) for o in orgs)
		clauses.append(f"`tabAuthorization Anomaly Alert`.`buyer_org` IN ({org_list})")
	if not clauses:
		return "1=0"
	return "(" + " OR ".join(clauses) + ")"


def authorization_anomaly_alert_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_audit_reader(user):
		return True
	if doc is None:
		return True
	doc_tenant = _doc_field(doc, "tenant")
	doc_buyer_org = _doc_field(doc, "buyer_org")
	user_tenant = _get_seller_profile_name(user)
	if user_tenant and doc_tenant == user_tenant:
		return True
	# D10: buyer organization match
	if doc_buyer_org and doc_buyer_org in _user_organizations(user):
		return True
	return False


# ── Authorization Anomaly Rule ──────────────────────────────────────────────
# Platform-only.


def authorization_anomaly_rule_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	return "1=0"


def authorization_anomaly_rule_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	return False


# ── Permission Override Log ─────────────────────────────────────────────────
# Platform-only.


def permission_override_log_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	return "1=0"


def permission_override_log_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	return False


# ── PII Field Policy ─────────────────────────────────────────────────────────
# Platform-only.


def pii_field_policy_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	return "1=0"


def pii_field_policy_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	return False


def notification_settings_has_permission(doc, ptype=None, user=None, debug=False):
	"""Notification Settings — tenant Owner/Co-Owner kendi ekip üyelerinin
	settings'ine erişebilsin.

	Why: Owner sub-user'ı pasifleştirdiğinde User.on_update → toggle_notifications
	→ Notification Settings.save() çağrılır. Frappe core'un default has_permission'ı
	`doc.name == user` arar (kendi kendine erişim) ve owner'ı reddeder, akış patlar.
	Burası tenant member yönetim yetkisini Notification Settings'e de uzatır.

	How to apply: None döndürürse Frappe core has_permission zinciri devam eder
	(reversed sırada bizim hook önce çağrılır; True dönerse erken çıkış olur).
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None  # core handler'a bırak

	# doc.name = Notification Settings sahibi user email'i
	target_user = getattr(doc, "name", None) if not isinstance(doc, dict) else doc.get("name")
	if not target_user:
		return None

	# Aynı tenant'taki Owner/Co-Owner mi?
	current_tenant = frappe.db.get_value("User", user, "tradehub_tenant")
	target_tenant = frappe.db.get_value("User", target_user, "tradehub_tenant")
	if not current_tenant or current_tenant != target_tenant:
		return None  # tenant uyuşmazlığı → core handler karar versin

	is_owner = frappe.db.get_value("User", user, "tradehub_is_owner")
	role_profile = frappe.db.get_value("User", user, "role_profile_name")
	if is_owner or role_profile == "Seller Co-Owner":
		return True

	return None


# ---------------------------------------------------------------------------
# Field Commission (Saha Pazarlama Hakediş)
# Saha elemanı yalnız agent == kendisi olan kayıtları görür; admin hepsini.
# ---------------------------------------------------------------------------

# Hakedişi görme/yönetme yetkisi olan roller — API `_require_admin` ile AYNI set.
# `_CRM_FULL_ACCESS_ROLES` (Sales* dahil) kullanılsaydı Sales rolleri permission
# katmanında tüm hakedişleri görür ama API aksiyon alamazdı (yarı-yetki). Dar set +
# tek kaynak: API bu sabiti import eder.
_FIELD_COMMISSION_ADMIN_ROLES = frozenset({"System Manager", "Marketplace Admin"})
# Faz C — ekip lideri rolü. API leader_approve/leader_reject + get_team_commissions
# bu sabiti import eder (permission ↔ aksiyon tek kaynak).
_FIELD_COMMISSION_LEADER_ROLE = "Saha Ekip Lideri"


def field_commission_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator":
		return ""
	roles = set(frappe.get_roles(user))
	if roles & _FIELD_COMMISSION_ADMIN_ROLES:
		return ""
	if _FIELD_COMMISSION_LEADER_ROLE in roles:
		# Lider kendi ekibinin (team_leader == self) + kendi (agent == self) kayıtlarını görür.
		u = frappe.db.escape(user)
		return f"(`tabField Commission`.`team_leader` = {u} OR `tabField Commission`.`agent` = {u})"
	if "Saha Pazarlama" in roles:
		return f"`tabField Commission`.`agent` = {frappe.db.escape(user)}"
	return "1=0"


def field_commission_has_permission(doc, ptype, user):
	if user == "Administrator":
		return True
	roles = set(frappe.get_roles(user))
	if roles & _FIELD_COMMISSION_ADMIN_ROLES:
		return True
	if _FIELD_COMMISSION_LEADER_ROLE in roles and doc.get("team_leader") == user:
		# Lider kendi ekibinin kaydını okur (onay aksiyonu API'de ignore_permissions ile).
		return ptype in ("read", "report")
	if "Saha Pazarlama" in roles:
		# Saha elemanı yalnız kendi kaydını ve yalnız okuma.
		return ptype in ("read", "report") and doc.get("agent") == user
	return False


# ── Seller Verification ───────────────────────────────────────────────────────
# Seller Verification.seller links to Admin Seller Profile.
# Satıcı yalnız kendi başvurularını görür; status değişikliği controller'da kısıtlı.


def seller_verification_query_conditions(user):
	if not user or user == "Guest":
		return "1=0"
	if user == "Administrator" or _is_platform_full_access(user):
		return ""
	profile = _get_seller_profile_name(user)
	if profile:
		return f"`tabSeller Verification`.`seller` = {frappe.db.escape(profile)}"
	return "1=0"


def seller_verification_has_permission(doc, ptype, user):
	if user == "Administrator" or _is_platform_full_access(user):
		return True
	profile = _get_seller_profile_name(user)
	seller_val = _doc_field(doc, "seller")
	return bool(profile and seller_val == profile)
