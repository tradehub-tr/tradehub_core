"""Sprint 6 — TH Module Registry seed.

Sorun:
  Sidebar item listesi `admin-panel/frontend/src/data/navigation.js` JS sabit.
  Süper admin sidebar item ekleyemiyor, gizleyemiyor.

Çözüm:
  setup/module_navigation_spec.py içinde Python ekvivalan spec tutuluyor.
  Bu patch spec'i gezip TH Module Registry kayıtları üretir (3 seviye:
  section → group → item).

İdempotent: var olan kayıtların (module_key bazında) tekrar yaratılmasına
karşı koruma. Yeni eklenen item'lar otomatik seed edilir.
"""

from __future__ import annotations

import frappe


def execute() -> dict:
	from tradehub_core.setup.module_navigation_spec import get_all_modules

	created: list[str] = []
	skipped: list[str] = []

	# İki geçişte seed: önce section/group (parent olmadığı için kayıt sırası
	# önemli), sonra item'lar. Spec listesi zaten doğru sıralı ama emniyet için
	# `parent` referansı önce ekleneni şart kılıyor — tip bazında sırala.
	type_order = {"section": 0, "group": 1, "item": 2}
	sorted_spec = sorted(get_all_modules(), key=lambda x: type_order.get(x["type"], 9))

	for spec in sorted_spec:
		key = spec["key"]
		if frappe.db.exists("TH Module Registry", key):
			skipped.append(key)
			continue

		doc = frappe.new_doc("TH Module Registry")
		doc.module_key = key
		doc.parent_th_module_registry = spec.get("parent")
		doc.item_type = spec["type"]
		doc.panel = spec["panel"]
		doc.section_key = spec.get("section") or ""
		doc.label = spec.get("label") or ""
		doc.icon = spec.get("icon") or ""
		doc.color = spec.get("color") or ""
		doc.display_order = spec.get("order", 0)
		doc.route = spec.get("route") or ""
		doc.doctype_ref = spec.get("doctype") or ""
		doc.seller_owned = 1 if spec.get("seller_owned") else 0
		doc.is_active = 1
		doc.is_protected = 1 if spec.get("is_protected") else 0
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		created.append(key)

	frappe.db.commit()

	# NestedSet rebuild — lft/rgt değerleri ilk insert sırasında yanlış olabilir
	try:
		frappe.utils.nestedset.rebuild_tree("TH Module Registry", "parent_th_module_registry")
	except Exception:
		frappe.log_error("Failed to rebuild NestedSet tree for TH Module Registry", "v15_6_2_seed_module_registry")
		pass

	return {
		"created_count": len(created),
		"skipped_existing_count": len(skipped),
		"total_in_db": frappe.db.count("TH Module Registry"),
	}
