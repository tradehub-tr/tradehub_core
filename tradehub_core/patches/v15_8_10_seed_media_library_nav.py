"""Satıcı sidebar'ına "Medya Kütüphanesi" (Vitrin) navigasyon item'ı ekle.

TH Module Registry'de `seller.store.vitrin.medya` (route /media-library)
kaydını oluşturur (idempotent). Sayfa Düzeni'nin hemen altında konumlanır
(order 1).

Not: Seller sidebar tamamen DB-driven (TH Module Registry) — frontend statik
navigation.js fallback'i satıcıda kullanılmaz, bu yüzden DB kaydı şart.
Medya Kütüphanesi view'ı (admin-panel `/media-library`) route olarak vardı ama
registry kaydı olmadığı için sidebar'da hiç görünmüyordu.
Spec kaynağı: setup/module_navigation_spec.py (key bazında tek kaydı seç).
"""

from __future__ import annotations

import frappe

_KEY = "seller.store.vitrin.medya"


def execute() -> dict:
	from tradehub_core.setup.module_navigation_spec import get_all_modules

	if frappe.db.exists("TH Module Registry", _KEY):
		return {"created": []}

	spec = next((m for m in get_all_modules() if m["key"] == _KEY), None)
	if not spec:
		frappe.log_error(f"{_KEY} spec'te bulunamadı", "v15_8_10_seed_media_library_nav")
		return {"created": []}

	doc = frappe.new_doc("TH Module Registry")
	doc.module_key = _KEY
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
	frappe.db.commit()

	try:
		frappe.utils.nestedset.rebuild_tree("TH Module Registry", "parent_th_module_registry")
	except Exception:
		frappe.log_error("nav rebuild_tree failed", "v15_8_10_seed_media_library_nav")

	return {"created": [_KEY]}
