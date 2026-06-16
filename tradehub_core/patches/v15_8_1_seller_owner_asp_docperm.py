"""FAZ 8.1 — Seller Owner rolüne Admin Seller Profile yazma iznini geri ver (RBAC regresyon fix).

Sorun:
  v15_7_1 ile aynı sınıf hata, bu kez Admin Seller Profile üzerinde. RBAC Custom
  DocPerm modeli (v15_5_1_seed_role_docperms) Admin Seller Profile permlevel-0
  erişimini yalnız alt-rollere verdi (Seller Viewer = read). Ancak capability
  sistemi doğrulanmış satıcı-sahibine "Seller Owner" rolünü atıyor ve "Seller
  Owner" Admin Seller Profile'ın permlevel-0 Custom DocPerm'inde YOK (yalnız
  permlevel-2/PII satırında var). Frappe'de bir DocType'ta Custom DocPerm bulundu
  mu standart DocPerm (JSON'daki Seller/Marketplace Seller write izni) tamamen
  yok sayılır → satıcı kendi mağaza profilini OKUYOR (Seller Viewer permlevel-0
  read) ama KAYDEDEMİYOR:
    "User <x> does not have doctype access via role permission for document
     Admin Seller Profile" (403).
  Belirti: panelde "Mağaza Ayarları" → galeri foto / logo değişikliği Kaydet
  ederken 403. v15_6_28 bu doctype'a "Marketplace Seller" satırı eklemişti ama
  gerçek rol modelinde satıcı-sahibi "Marketplace Seller" değil "Seller Owner"
  taşıyor → o patch efektif değildi.

Çözüm:
  "Seller Owner" için Admin Seller Profile permlevel-0 read/write Custom DocPerm
  satırı ekle (if_owner=0 — profiller owner=Administrator ile provision edilir,
  if_owner sahibi dışlardı). Tenant izolasyonu permissions.admin_seller_profile_
  query_conditions + permissions.admin_seller_profile_has_permission tarafından
  korunur (user→profil eşlemesi) → satıcı YALNIZCA kendi profilini düzenler.
  create=0: profil admin onboarding'de oluşur, satıcı yeni profil açmaz.
  İdempotent.
"""

from __future__ import annotations

import frappe

_DT = "Admin Seller Profile"
_ROLE = "Seller Owner"


def execute() -> dict:
	if not frappe.db.exists("DocType", _DT):
		return {"skipped": "no_doctype"}
	if not frappe.db.exists("Role", _ROLE):
		return {"skipped": "no_role"}

	existing = frappe.db.exists(
		"Custom DocPerm", {"parent": _DT, "role": _ROLE, "permlevel": 0}
	)
	if existing:
		cd = frappe.get_doc("Custom DocPerm", existing)
		cd.read = 1
		cd.write = 1
		cd.create = 0
		cd.if_owner = 0
		cd.save(ignore_permissions=True)
		action = "updated"
	else:
		cd = frappe.new_doc("Custom DocPerm")
		cd.parent = _DT
		cd.parenttype = "DocType"
		cd.parentfield = "permissions"
		cd.role = _ROLE
		cd.permlevel = 0
		cd.read = 1
		cd.write = 1
		cd.create = 0
		cd.if_owner = 0
		cd.insert(ignore_permissions=True)
		action = "created"

	frappe.clear_cache(doctype=_DT)
	frappe.db.commit()
	return {action: "Seller Owner -> Admin Seller Profile (r/w)"}
