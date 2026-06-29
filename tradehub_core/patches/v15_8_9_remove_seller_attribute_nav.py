"""Satıcı panelinden "Özellik Yönetimi" navigasyonunu kaldır.

Satıcı sidebar'ı DB-driven (TH Module Registry). "Ürün Özellikleri"
(Product Attribute) ve "Özellik Setleri" (Attribute Set) satıcıya bir fayda
sağlamıyordu: Product Attribute backend'de teknik özellik yazılırken otomatik
çözümleniyor, Attribute Set ise admin işidir (satıcıya salt-okunur). Bu üç
kaydı is_active=0 yaparak satıcı menüsünden gizleriz (get_navigation_tree
yalnızca is_active=1 kayıtları döndürür).

Spec kaynağı: setup/module_navigation_spec.py (ilgili bloklar kaldırıldı).
İdempotent: kayıt yoksa veya zaten pasifse atlar.
"""

from __future__ import annotations

import frappe

_KEYS = [
	"seller.products.ozellik.ozellikler",
	"seller.products.ozellik.setler",
	"seller.products.ozellik",
]


def execute() -> dict:
	deactivated: list[str] = []
	for key in _KEYS:
		if not frappe.db.exists("TH Module Registry", key):
			continue
		if frappe.db.get_value("TH Module Registry", key, "is_active"):
			frappe.db.set_value("TH Module Registry", key, "is_active", 0, update_modified=False)
			deactivated.append(key)

	if deactivated:
		try:
			from tradehub_core.utils.permission_resolver import flush_module_cache

			flush_module_cache()
		except Exception:
			frappe.log_error("flush_module_cache failed", "v15_8_9_remove_seller_attribute_nav")

	frappe.db.commit()
	return {"deactivated": deactivated}
