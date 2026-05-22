"""FAZ 3.6 hotfix — Order Approval / Approval Rule DocPerm `if_owner=1` tuzağını kaldır.

`if_owner=1` flag'i, Buyer Approver L1/L2 ve Buyer Admin'in **kendi açtıkları**
approval'ları görmesini sağlıyordu; ama approval'lar `start_approval()` tarafından
ignore_permissions=True ile oluşturulduğundan owner=requisitioner — yani approver
hiçbir approval'ı GÖREMİYORDU.

Yeni model: tenant/organization scope `permissions.py` içindeki yeni
`order_approval_query_conditions` / `approval_rule_query_conditions` üzerinden.

Bu patch idempotent — DocType JSON sync olmasa da DB'deki Custom DocPerm
kayıtlarındaki `if_owner` flag'ini düşürür.
"""

from __future__ import annotations

import frappe

_FIXES: list[tuple[str, list[str]]] = [
	("Order Approval", ["Buyer Admin", "Buyer Approver L1", "Buyer Approver L2", "Buyer"]),
	("Approval Rule", ["Buyer Admin", "Buyer Approver L1", "Buyer Approver L2"]),
]


def execute() -> dict:
	fixed = []
	for doctype, roles in _FIXES:
		for role in roles:
			# Custom DocPerm tarafı
			docperm_rows = frappe.get_all(
				"Custom DocPerm",
				filters={"parent": doctype, "role": role, "if_owner": 1},
				pluck="name",
			)
			for row in docperm_rows:
				frappe.db.set_value("Custom DocPerm", row, "if_owner", 0)
				fixed.append(f"Custom DocPerm:{row}")
			# Standard DocPerm (fixtures sync olduysa) — defansif
			std_rows = frappe.get_all(
				"DocPerm",
				filters={"parent": doctype, "role": role, "if_owner": 1},
				pluck="name",
			)
			for row in std_rows:
				frappe.db.set_value("DocPerm", row, "if_owner", 0)
				fixed.append(f"DocPerm:{row}")

	if fixed:
		frappe.db.commit()
		frappe.clear_cache()

	return {"fixed_rows": fixed, "count": len(fixed)}
