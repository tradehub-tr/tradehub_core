"""G0 rol matrisi — satıcı sidebar'ına Lojistik → Sevkiyatlar kalemini ekler.

Sorun:
	Satıcı sidebar'ı tamamen DB-driven (TH Module Registry) ve fail-secure:
	statik `sellerPanelSections` fallback'ine düşmüyor. G0 kararı satıcıya
	sevkiyat listesini (B1) açtı ve route + tenant filtresi çalışıyor
	(ölçüldü: ali.bal URL'den girip boş listesini gördü) — ama registry
	kaydı olmadığı için menüde görünmüyordu. 13-FE'de paketleme için aynı
	sorun aynı desenle çözülmüştü (v15_9_20_seed_logistics_seller_nav).

Çözüm:
	Spec'e eklenen iki kayıt seed edilir (group + item) ve Ali'nin
	"Paketleme" grubunun display_order'ı 1'e çekilir (Sevkiyatlar 0'a
	oturuyor; ikisi de 0 kalırsa sıra DB dönüş sırasına kalıyordu).
	İdempotent.
"""

from __future__ import annotations

import frappe

# Sıra ÖNEMLİ: parent çocuktan önce eklenmeli (nested set).
_KEYS = (
	"seller.logistics.shipments",
	"seller.logistics.shipments.list",
)


def execute() -> dict:
	from tradehub_core.setup.module_navigation_spec import get_all_modules

	modules = {m["key"]: m for m in get_all_modules()}
	created: list[str] = []

	for key in _KEYS:
		if frappe.db.exists("TH Module Registry", key):
			continue

		spec = modules.get(key)
		if not spec:
			frappe.log_error(f"{key} spec'te bulunamadı", "v15_9_21_g0_seed_seller_shipments_nav")
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

	# Paketleme grubu 0'da seed edilmişti; Sevkiyatlar 0'a geldi — sırayı netle.
	reordered = False
	if frappe.db.exists("TH Module Registry", "seller.logistics.packing"):
		if frappe.db.get_value("TH Module Registry", "seller.logistics.packing", "display_order") == 0:
			frappe.db.set_value("TH Module Registry", "seller.logistics.packing", "display_order", 1)
			reordered = True

	if created or reordered:
		frappe.db.commit()
		try:
			frappe.utils.nestedset.rebuild_tree("TH Module Registry", "parent_th_module_registry")
		except Exception:
			frappe.log_error("nav rebuild_tree failed", "v15_9_21_g0_seed_seller_shipments_nav")

	return {"created": created, "packing_reordered": reordered}
