"""Satıcı-sahibi (Marketplace Seller) Custom DocPerm onarımı.

Sorun: 7 satıcı-doctype'ında Custom DocPerm yalnız alt-kullanıcı granular
rolleri (Seller Staff/Viewer/Finance) + Platform Admin/Support Agent için
kurulmuştu. Frappe'de Custom DocPerm standart DocPerm'i TAMAMEN ezdiği için,
satıcı-sahibinin taşıdığı "Marketplace Seller" rolü efektif izinden düşmüştü →
sahip kendi Listing/Order/Seller Balance vb. kaydını generic formda açamıyor
("does not have doctype access via role permission").

Çözüm: her doctype için "Seller Staff" Custom DocPerm'ini ayna alıp aynı
ptype bayraklarıyla "Marketplace Seller" Custom DocPerm'i ekle. Güvenli çünkü:
- Alt-kullanıcılar "Marketplace Seller" taşımıyor → over-grant olmaz.
- 7 doctype'ın hepsinde permission_query_conditions + has_permission tenant
  hook'u var → erişim kendi verisine sınırlanır.

Idempotent: Marketplace Seller Custom DocPerm zaten varsa atlar.
"""

import frappe

DOCTYPES = [
	"Listing",
	"Order",
	"Seller Balance",
	"Admin Seller Profile",
	"Seller Review",
	"Seller Inquiry",
	"Listing Review",
]
OWNER_ROLE = "Marketplace Seller"
MIRROR_ROLE = "Seller Staff"
# Kopyalanacak izin bayrakları (ptype + meta).
_PERM_FIELDS = (
	"read",
	"write",
	"create",
	"delete",
	"submit",
	"cancel",
	"amend",
	"report",
	"export",
	"print",
	"email",
	"share",
	"permlevel",
	"if_owner",
)


def execute() -> None:
	created = []
	for dt in DOCTYPES:
		if frappe.db.exists("Custom DocPerm", {"parent": dt, "role": OWNER_ROLE}):
			continue
		staff = frappe.db.get_value(
			"Custom DocPerm",
			{"parent": dt, "role": MIRROR_ROLE},
			_PERM_FIELDS,
			as_dict=True,
		)
		if not staff:
			# Ayna kaynağı yoksa en azından read/write ver (owner operasyonel).
			staff = {"read": 1, "write": 1, "permlevel": 0, "if_owner": 0}
		doc = frappe.new_doc("Custom DocPerm")
		doc.parent = dt
		doc.parenttype = "DocType"
		doc.parentfield = "permissions"
		doc.role = OWNER_ROLE
		for field in _PERM_FIELDS:
			if field in staff and staff[field] is not None:
				doc.set(field, staff[field])
		doc.insert(ignore_permissions=True)
		created.append(dt)

	frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info(f"v15_6_28 Marketplace Seller Custom DocPerm eklendi: {created}")
