"""Satıcı sidebar'ına "Mesajlarım" + "Müsaitlik" navigasyon item'larını ekle.

Merge sırasında `seller.store.musteri` (Müşteri & Sosyal) grubundan iki item
düşmüştü; bu yüzden satıcı panelinde (DB-driven sidebar — TH Module Registry)
Mesajlarım ve Müsaitlik görünmüyordu. Bu patch o iki kaydı idempotent şekilde
oluşturur ve grup içi display_order'ları spec ile hizalar.

Spec kaynağı: setup/module_navigation_spec.py
Frontend route'ları zaten mevcut: /messaging/buyer-messages, /messaging/availability
"""

from __future__ import annotations

import frappe

_NEW_KEYS = [
	"seller.store.musteri.mesajlar",
	"seller.store.musteri.musaitlik",
]

# Grup içi nihai sıralama (spec ile birebir).
_ORDER = {
	"seller.store.musteri.mesajlar": 0,
	"seller.store.musteri.musaitlik": 1,
	"seller.store.musteri.yorum": 2,
	"seller.store.musteri.soru": 3,
	"seller.store.musteri.galeri": 4,
}


def execute() -> dict:
	from tradehub_core.setup.module_navigation_spec import get_all_modules

	by_key = {m["key"]: m for m in get_all_modules()}
	created: list[str] = []

	for key in _NEW_KEYS:
		if frappe.db.exists("TH Module Registry", key):
			continue
		spec = by_key.get(key)
		if not spec:
			frappe.log_error(f"{key} spec'te bulunamadı", "v15_8_7_seed_messaging_nav")
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
		doc.is_protected = 0
		doc.flags.ignore_permissions = True
		doc.flags.ignore_mandatory = True
		doc.insert(ignore_permissions=True)
		created.append(key)

	# display_order hizalama (mevcut kayıtlar dahil) — idempotent.
	for key, order in _ORDER.items():
		if frappe.db.exists("TH Module Registry", key):
			frappe.db.set_value("TH Module Registry", key, "display_order", order, update_modified=False)

	frappe.db.commit()

	try:
		frappe.utils.nestedset.rebuild_tree("TH Module Registry", "parent_th_module_registry")
	except Exception:
		frappe.log_error("nav rebuild_tree failed", "v15_8_7_seed_messaging_nav")

	return {"created": created}
