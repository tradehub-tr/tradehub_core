"""Satıcı permlevel-0 taban erişim onarımı (genel + gelecek-korumalı).

Kök neden: v15_1_3_pii_role_permissions.py PII'li doctype'lara Custom DocPerm
ekleyince Frappe doctype JSON'unu yok saymaya başladı; permlevel-0 taban satıcı
erişimi kopyalanmadı. Sonraki onarım patch'leri (v15_6_28, v15_7_1, v15_7_6,
v15_8_1/2/3) doctype-doctype yamadı ama User Profile ve Marketplace Seller
temel rolü atlandı → satıcı kendi User Profile'ını generic formda açarken 403
("does not have doctype access via role permission").

Tek-seferlik yama yerine GENEL kural: Custom DocPerm'i olan her tradehub_core
doctype'ında permlevel>0'da satıcı (Seller/Marketplace Seller) read izni
tanımlıysa (tasarım o doctype'ı satıcıya açmayı amaçlamış demektir) ama
permlevel-0'da o satıcı read'i yoksa, permlevel-0 read+write iznini (if_owner
ile) ekler. Hem 'Seller' (eski) hem 'Marketplace Seller' (canonical) eklenir —
rol şeması geçişine dayanıklı.

Güvenlik: if_owner=1 sadece kendi kaydı; permissions.py has_permission/
query_conditions hook'ları ek olarak kendi kaydıyla sınırlar (defense-in-depth).
permlevel 1/2/3 (PII) satırlarına DOKUNULMAZ — hassas alanlar field-level
kontrolde kalır. Idempotent. Frappe/ERPNext core doctype'ları kapsam dışı
(zaten 'All' rolü erişim verir, core izinlerine dokunulmaz).
"""

import frappe

_SELLER_BASE_ROLES = ("Seller", "Marketplace Seller")
_CORE_EXCLUDE = {"Contact", "Address", "User", "File", "Note", "ToDo"}


def execute() -> None:
	repaired = []
	parents = frappe.get_all("Custom DocPerm", fields=["parent"], distinct=True, pluck="parent")
	for dt in parents:
		if dt in _CORE_EXCLUDE or not frappe.db.exists("DocType", dt):
			continue
		rows = frappe.get_all(
			"Custom DocPerm",
			filters={"parent": dt},
			fields=["role", "permlevel", "read", "if_owner"],
		)
		pl0_read = {r["role"] for r in rows if r["permlevel"] == 0 and r["read"]}
		higher = [
			r
			for r in rows
			if r["permlevel"] > 0 and r["role"] in _SELLER_BASE_ROLES and r["read"]
		]
		if not higher:
			continue  # tasarım bu doctype'ı satıcıya açmamış → dokunma
		for base in _SELLER_BASE_ROLES:
			if base in pl0_read:
				continue  # idempotent
			src = next((r for r in higher if r["role"] == base), higher[0])
			cp = frappe.new_doc("Custom DocPerm")
			cp.parent = dt
			cp.parenttype = "DocType"
			cp.parentfield = "permissions"
			cp.role = base
			cp.permlevel = 0
			cp.read = 1
			cp.write = 1
			cp.if_owner = 1 if src.get("if_owner") else 0
			cp.insert(ignore_permissions=True)
			repaired.append((dt, base, cp.if_owner))

	frappe.db.commit()
	frappe.clear_cache()
	frappe.logger().info(f"v15_8_6 satıcı permlevel-0 onarımı: {repaired}")
