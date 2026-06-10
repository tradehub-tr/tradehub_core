"""KYB/KYC Verification permlevel-0 Custom DocPerm onarımı.

Kök neden: `v15_1_3_pii_role_permissions.py` hedef doctype'lara (KYB/KYC
Verification dahil) yalnızca permlevel 1/2/3 Custom DocPerm satırı ekledi;
permlevel-0 taban izinlerini kopyalamadı. Frappe'de bir doctype için Custom
DocPerm varsa standart DocPerm (DocType JSON) TAMAMEN yok sayılır. permlevel-0
Custom DocPerm satırı bulunmadığından KYB/KYC'de Administrator dışında hiçbir
rol temel `read` alamadı → Seller, kendi KYB kaydını generic formda açarken
"does not have doctype access via role permission" (403) aldı.

Admin Seller Profile / User Profile aynı patch'ten etkilendi ama sonraki seed
patch'leri (v15_5_1, v15_6_28) permlevel-0 satırlarını eklediği için sağlam
kaldı; KYB/KYC o seed kapsamında değildi.

Çözüm: standart `tabDocPerm`'deki (JSON'dan senkron) permlevel-0 satırlarını,
eksikse `tabCustom DocPerm`'e ayna al. permlevel 1/2/3 satırlarına dokunmaz →
PII kilidi korunur. Idempotent: doctype'ta zaten permlevel-0 Custom DocPerm
varsa atlar.

v15_6_28 ile aynı sınıf hata; o patch 7 satıcı-doctype'ını onarmıştı ama
KYB/KYC kapsam dışındaydı.
"""

import frappe

_TARGET_DOCTYPES = ["KYB Verification", "KYC Verification"]

# tabDocPerm → tabCustom DocPerm kopyalanacak izin bayrakları (permlevel hariç,
# o sabit 0). v15_6_28 ile aynı alan seti.
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
	"if_owner",
)


def execute() -> None:
	repaired = []
	for dt in _TARGET_DOCTYPES:
		if not frappe.db.exists("DocType", dt):
			continue
		# Idempotent — permlevel-0 Custom DocPerm zaten varsa onarıma gerek yok.
		if frappe.db.exists("Custom DocPerm", {"parent": dt, "permlevel": 0}):
			continue

		# Standart DocPerm'in permlevel-0 satırları = DocType JSON'unun taban
		# izinleri (Seller/Marketplace Admin/System Manager ...). Bunları ayna al.
		base_perms = frappe.get_all(
			"DocPerm",
			filters={"parent": dt, "permlevel": 0},
			fields=["role", *_PERM_FIELDS],
		)
		for bp in base_perms:
			cp = frappe.new_doc("Custom DocPerm")
			cp.parent = dt
			cp.parenttype = "DocType"
			cp.parentfield = "permissions"
			cp.role = bp["role"]
			cp.permlevel = 0
			for f in _PERM_FIELDS:
				if bp.get(f) is not None:
					cp.set(f, bp[f])
			cp.insert(ignore_permissions=True)
		repaired.append((dt, len(base_perms)))

	frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info(f"v15_7_6 KYB/KYC permlevel-0 Custom DocPerm onarıldı: {repaired}")
