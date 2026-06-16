"""FAZ 8.3 — Seller Owner rolüne KYB/KYC Verification'da permlevel-0 erişimi
geri ver (RBAC regresyon fix — v15_8_1/v15_8_2 kapsam tamamlama).

Sorun:
  v15_8_1 (Admin Seller Profile) ve v15_8_2 (Order/Seller Balance/Seller Review/
  Seller Inquiry/Listing Review) ile aynı kök neden, bu kez KYB/KYC Verification.
  Frappe'de bir DocType'ta Custom DocPerm bulundu mu standart DocPerm (JSON)
  TAMAMEN yok sayılır. KYB/KYC Verification'da Custom DocPerm var (PII patch'i +
  v15_7_6 permlevel-0 onarımı). v15_7_6 yalnız JSON rollerini (Seller if_owner=1,
  Marketplace Admin, System Manager) ayna aldı; doğrulanmış satıcı-sahibinin
  taşıdığı "Seller Owner" rolü KYB/KYC permlevel-0 Custom DocPerm'inde YOK →
  satıcı kendi KYB kaydını generic panel formunda açamıyor/kaydedemiyor:
    "User <x> does not have doctype access via role permission for document
     KYB Verification" (403).
  Belirti: panelde Profil & Finans → KYB Doğrulama açılınca 403, alanlar boş.

Çözüm:
  "Seller Owner" için KYB/KYC Verification permlevel-0 read+write Custom DocPerm
  ekle (if_owner=0 — KYB kayıtları kimi yolda owner≠user provision edilebilir;
  if_owner sahibi dışlardı — v15_8_1 ile aynı gerekçe). Tenant izolasyonu KORUNUR:
  her iki doctype'ta permission_query_conditions + has_permission hook'u var
  (hooks.py → kyb_verification_*; doc.user==user) → satıcı YALNIZCA kendi kaydını
  görür/düzenler. create=0: kayıt sistem (onay akışı / get_kyb_status) tarafından
  üretilir, satıcı formdan oluşturmaz. İdempotent.
"""

from __future__ import annotations

import frappe

# doctype -> permlevel-0 bayrakları. KYC, v15_7_6'da KYB ile birlikte ele alındığı
# için aynı boşluğa sahip; kilit (#3) davranışını değiştirmez, sadece erişimi tamamlar.
_GRANTS = {
	"KYB Verification": {"read": 1, "write": 1, "create": 0},
	"KYC Verification": {"read": 1, "write": 1, "create": 0},
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
