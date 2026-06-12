"""FAZ 8.2 — Seller Owner rolüne kardeş satıcı-doctype'larında permlevel-0 erişimi
geri ver (RBAC regresyon fix, sistemik).

Sorun:
  v15_8_1 ile aynı kök neden, başka doctype'larda. v15_5_1_seed_role_docperms
  permlevel-0 Custom DocPerm'i yalnız alt-rollere (Seller Staff/Viewer/Finance)
  verdi; doğrulanmış satıcı-sahibinin taşıdığı "Seller Owner" rolünü atladı.
  Frappe'de Custom DocPerm standart DocPerm'i tamamen ezdiği için satıcı-sahibi
  kendi siparişlerini/bakiyesini/yorumlarını generic formda/listede açamıyor
  ("does not have doctype access via role permission" 403). Belirti: panelde
  Siparişler / bakiye / yorum sekmeleri 403.

  Denetim (Custom DocPerm permlevel-0, alt-rol erişimi var ama Seller Owner yok):
    Listing Review, Order, Seller Balance, Seller Inquiry, Seller Review.

Çözüm:
  Her doctype için "Seller Owner"a alt-rollerin permlevel-0 union'ını ayna al
  (read; Seller Inquiry'de write de). Tenant izolasyonu KORUNUR: 5 doctype'ın
  hepsinde permission_query_conditions + has_permission hook'u var (hooks.py) →
  satıcı YALNIZCA kendi kayıtlarını görür/düzenler. create=0: bu kayıtlar
  buyer/sistem tarafından üretilir, satıcı formdan oluşturmaz. İdempotent.

  NOT: Admin Seller Profile bu patch'te YOK — v15_8_1 onu read+WRITE ile ayrı
  ele aldı (sahip kendi profilini düzenlemeli; alt-roller yalnız read).
  Child-table'lar (Seller Gallery Image/Certification, Subscription Plan Region)
  bu patch'te YOK — Frappe child table'a (istable=1) doğrudan REST erişimini
  DocPerm'den bağımsız bloklar; o 403'ler frontend tarafında (child'ı parent
  üzerinden oku) çözülür, backend izinle değil.
"""

from __future__ import annotations

import frappe

# doctype -> ayna alınacak permlevel-0 bayrakları (alt-rol union'ı).
_GRANTS = {
	"Listing Review": {"read": 1, "write": 0, "create": 0},
	"Order": {"read": 1, "write": 0, "create": 0},
	"Seller Balance": {"read": 1, "write": 0, "create": 0},
	"Seller Inquiry": {"read": 1, "write": 1, "create": 0},
	"Seller Review": {"read": 1, "write": 0, "create": 0},
}
_ROLE = "Seller Owner"


def execute() -> dict:
	if not frappe.db.exists("Role", _ROLE):
		return {"skipped": "no_role"}

	touched = []
	for dt, flags in _GRANTS.items():
		if not frappe.db.exists("DocType", dt):
			continue
		existing = frappe.db.exists(
			"Custom DocPerm", {"parent": dt, "role": _ROLE, "permlevel": 0}
		)
		if existing:
			cd = frappe.get_doc("Custom DocPerm", existing)
			# Mevcut izinleri DARALTMA — yalnız eksik bayrağı aç (union).
			cd.read = cd.read or flags["read"]
			cd.write = cd.write or flags["write"]
			cd.create = cd.create or flags["create"]
			cd.save(ignore_permissions=True)
		else:
			cd = frappe.new_doc("Custom DocPerm")
			cd.parent = dt
			cd.parenttype = "DocType"
			cd.parentfield = "permissions"
			cd.role = _ROLE
			cd.permlevel = 0
			cd.read = flags["read"]
			cd.write = flags["write"]
			cd.create = flags["create"]
			cd.insert(ignore_permissions=True)
		frappe.clear_cache(doctype=dt)
		touched.append(dt)

	frappe.db.commit()
	return {"granted": touched}
