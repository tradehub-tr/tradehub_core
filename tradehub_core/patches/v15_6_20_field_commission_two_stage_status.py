# Copyright (c) 2026, TR TradeHub and contributors
"""Faz C — iki kademeli onay geçişi.

- 'Saha Ekip Lideri' rolünü idempotent yaratır (fixture export'u DB'de yoksa boş).
- Eski 'Beklemede' Field Commission kayıtlarını 'Süperadmin Onayı Bekliyor'a taşır
  (eski kayıtların ekip/lideri yok → lider kademesi atlanır).
"""

import frappe


def execute():
	# 1) Rol — idempotent
	if not frappe.db.exists("Role", "Saha Ekip Lideri"):
		role = frappe.new_doc("Role")
		role.role_name = "Saha Ekip Lideri"
		role.desk_access = 0
		role.insert(ignore_permissions=True)

	# 2) Eski durum taşıma — tablo yoksa (yeni kurulum) atla.
	# NOT: has_column/table_exists DOCTYPE adı bekler (içeride 'tab' ekler); 'tabField
	# Commission' verirsek 'tabtabField Commission' aranır → TableMissingError.
	if not frappe.db.table_exists("Field Commission"):
		return
	frappe.db.sql(
		"""UPDATE `tabField Commission` SET status = %s WHERE status = %s""",
		("Süperadmin Onayı Bekliyor", "Beklemede"),
	)
	frappe.db.commit()
