"""FAZ 5.1 — 9 yeni role seed et + her birine minimum DocPerm.

Permission Console'da görünen Role Profile'lar (Buyer Operations, Seller
Manager, Platform Finance Manager vb.) içerdeki rolleri referans veriyordu
ama bu roller DB'de hiç yoktu → atanan kullanıcı sıfır yetkiyle giriyordu.

Bu patch:
  1. role.json fixture'daki yeni rolleri DB'ye seed eder (idempotent)
  2. Her role minimum DocPerm setini Custom DocPerm üzerinden ekler

Tenant izolasyonu permissions.py'deki query_conditions üzerinden uygulanır
(buyer-side: tradehub_parent_organization, seller-side: seller_profile).
"""

from __future__ import annotations

import frappe

# ---------------------------------------------------------------------------
# 1. Role oluşturma (idempotent)
# ---------------------------------------------------------------------------

# (role_name, desk_access)
_NEW_ROLES: list[tuple[str, int]] = [
	("Buyer Admin", 0),
	("Buyer Procurement", 0),
	("Buyer Finance", 0),
	("Buyer Viewer", 0),
	("Seller Finance", 0),
	("Seller Staff", 0),
	("Seller Viewer", 0),
	("Platform Admin", 1),
	("Platform Finance", 1),
	("Support Agent", 1),
]


def _ensure_roles() -> list[str]:
	created: list[str] = []
	for role_name, desk_access in _NEW_ROLES:
		if frappe.db.exists("Role", role_name):
			continue
		doc = frappe.new_doc("Role")
		doc.role_name = role_name
		doc.desk_access = desk_access
		doc.is_custom = 1
		doc.insert(ignore_permissions=True)
		created.append(role_name)
	return created

# Sentinel — DocPerm matrisi.
# Her tuple: (doctype, role, perm dict)
# perm dict anahtarları: r=read, w=write, c=create, d=delete, e=export,
#                         rpt=report, share, im=import, if_owner

# ---- Buyer-side roles (organization scope) ----------------------------------

_BUYER_VIEWER_PERMS = [
	("Order", "read"),
	("Order Approval", "read"),
	("Approval Rule", "read"),
	("Cost Center", "read"),
]

_BUYER_PROCUREMENT_PERMS = [
	("Order", "read"), ("Order", "write"), ("Order", "create"),
	("Order Approval", "read"),
	("Approval Rule", "read"),
	("Cost Center", "read"),
]

_BUYER_FINANCE_PERMS = [
	("Order", "read"),
	("Order Approval", "read"),
	("Cost Center", "read"), ("Cost Center", "write"), ("Cost Center", "create"),
	("Authorization Decision Log", "read"),
]

# ---- Seller-side roles (seller_profile scope) -------------------------------

_SELLER_VIEWER_PERMS = [
	("Listing", "read"),
	("Order", "read"),
	("Seller Inquiry", "read"),
	("Seller Balance", "read"),
	("Admin Seller Profile", "read"),
	("Seller Review", "read"),
]

_SELLER_STAFF_PERMS = [
	("Listing", "read"), ("Listing", "write"), ("Listing", "create"),
	("Order", "read"),
	("Seller Inquiry", "read"), ("Seller Inquiry", "write"),
	("Listing Review", "read"),
]

_SELLER_FINANCE_PERMS = [
	("Seller Balance", "read"),
	("Order", "read"),
	("Listing", "read"),
	("Admin Seller Profile", "read"),
]

# Seller Admin / Co-Owner — şu ana kadar boş "marker rol"du; minimum izin
# verelim ki Role Profile bundle'larında işlev kazansın. Owner-level field
# kısıtlamaları utils/owner_lock.enforce_owner_only_fields ile uygulanıyor.
_SELLER_ADMIN_PERMS = [
	("Listing", "read"), ("Listing", "write"), ("Listing", "create"), ("Listing", "delete"),
	("Order", "read"), ("Order", "write"),
	("Seller Inquiry", "read"), ("Seller Inquiry", "write"), ("Seller Inquiry", "create"),
	("Admin Seller Profile", "read"), ("Admin Seller Profile", "write"),
	("Seller Balance", "read"),
	("Listing Review", "read"), ("Listing Review", "write"),
	("Seller Review", "read"),
]

_SELLER_CO_OWNER_PERMS = _SELLER_ADMIN_PERMS + [
	("Owner Transfer Request", "read"), ("Owner Transfer Request", "write"),
	("Role Delegation", "read"),
]

# ---- Platform-side roles (platform-full or scoped) --------------------------

# Platform Admin = Marketplace Admin benzeri (tüm tradehub doctype'larında
# read/write/create). Marketplace Admin halihazırda 62 DocPerm taşıyor; biz
# yeni rolü permissions.py içindeki _PLATFORM_FULL_ACCESS_ROLES set'ine
# ekliyoruz — bu sayede 11 yeni ReBAC/Audit doctype'a otomatik full access
# alır. Burada ek olarak ana storefront doctype'larına da DocPerm veriyoruz.
_PLATFORM_ADMIN_PERMS = [
	("Listing", "read"), ("Listing", "write"), ("Listing", "create"), ("Listing", "delete"),
	("Order", "read"), ("Order", "write"), ("Order", "create"),
	("Admin Seller Profile", "read"), ("Admin Seller Profile", "write"),
	("Seller Balance", "read"), ("Seller Balance", "write"),
	("User Profile", "read"), ("User Profile", "write"),
	("Subscription Plan", "read"), ("Subscription Plan", "write"),
	# ReBAC/Audit doctype'lar — permissions.py'de zaten Platform Admin için
	# query_conditions bypass aktif; yine de DocPerm ihtiyacı var.
	("Order Approval", "read"), ("Order Approval", "write"),
	("Approval Rule", "read"), ("Approval Rule", "write"),
	("Cost Center", "read"), ("Cost Center", "write"),
	("Authorization Decision Log", "read"),
	("Role Change Log", "read"),
	("Authorization Anomaly Alert", "read"), ("Authorization Anomaly Alert", "write"),
	("Authorization Anomaly Rule", "read"), ("Authorization Anomaly Rule", "write"),
	("Permission Override Log", "read"),
	("Owner Transfer Request", "read"),
	("Role Delegation", "read"),
]

_PLATFORM_FINANCE_PERMS = [
	("Order", "read"),
	("Seller Balance", "read"),
	("Admin Seller Profile", "read"),
	("Subscription Plan", "read"),
	("Authorization Decision Log", "read"),
]

_SUPPORT_AGENT_PERMS = [
	("HD Ticket", "read"), ("HD Ticket", "write"), ("HD Ticket", "create"),
	("User Profile", "read"),
	("Listing", "read"),
	("Order", "read"),
	("Admin Seller Profile", "read"),
]

# Master matris: rol → permissions list
_ROLE_MATRIX: dict[str, list[tuple[str, str]]] = {
	"Buyer Viewer": _BUYER_VIEWER_PERMS,
	"Buyer Procurement": _BUYER_PROCUREMENT_PERMS,
	"Buyer Finance": _BUYER_FINANCE_PERMS,
	"Seller Viewer": _SELLER_VIEWER_PERMS,
	"Seller Staff": _SELLER_STAFF_PERMS,
	"Seller Finance": _SELLER_FINANCE_PERMS,
	"Seller Admin": _SELLER_ADMIN_PERMS,
	"Seller Co-Owner": _SELLER_CO_OWNER_PERMS,
	"Platform Admin": _PLATFORM_ADMIN_PERMS,
	"Platform Finance": _PLATFORM_FINANCE_PERMS,
	"Support Agent": _SUPPORT_AGENT_PERMS,
}


def execute() -> dict:
	roles_created = _ensure_roles()

	created = 0
	skipped = 0
	missing_doctypes: set[str] = set()
	missing_roles: set[str] = set()

	for role, perms in _ROLE_MATRIX.items():
		if not frappe.db.exists("Role", role):
			missing_roles.add(role)
			continue

		# Aynı doctype için birden fazla perm tipi olabilir; satır bazında
		# tek bir Custom DocPerm kaydı + içine read/write/create flag'leri.
		grouped: dict[str, dict[str, int]] = {}
		for doctype, ptype in perms:
			grouped.setdefault(doctype, {})[ptype] = 1

		for doctype, flags in grouped.items():
			if not frappe.db.exists("DocType", doctype):
				missing_doctypes.add(doctype)
				continue
			# Aynı (parent=doctype, role, permlevel=0) zaten varsa skip — idempotent
			existing = frappe.db.exists(
				"Custom DocPerm",
				{"parent": doctype, "role": role, "permlevel": 0},
			)
			if existing:
				skipped += 1
				continue
			try:
				doc = frappe.new_doc("Custom DocPerm")
				doc.parent = doctype
				doc.parenttype = "DocType"
				doc.parentfield = "permissions"
				doc.role = role
				doc.permlevel = 0
				doc.read = flags.get("read", 0)
				doc.write = flags.get("write", 0)
				doc.create = flags.get("create", 0)
				doc.delete = flags.get("delete", 0)
				doc.report = 1 if flags.get("read") else 0
				doc.export = 1 if flags.get("read") else 0
				doc.share = 0
				doc.if_owner = 0  # tenant izolasyonu permissions.py'de
				doc.insert(ignore_permissions=True)
				created += 1
			except Exception as exc:
				frappe.log_error(
					f"Custom DocPerm seed fail {role}@{doctype}: {exc}",
					"v15_5_1_seed_role_docperms",
				)

	if created:
		frappe.db.commit()
		frappe.clear_cache()

	return {
		"roles_created": roles_created,
		"docperm_created": created,
		"docperm_skipped": skipped,
		"missing_doctypes": sorted(missing_doctypes),
		"missing_roles": sorted(missing_roles),
	}
