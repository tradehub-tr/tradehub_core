"""Satıcı sidebar'ına Lojistik → Paketleme navigasyonunu ekle (13-FE).

TH Module Registry'de üç kayıt oluşturur (idempotent):
	seller.logistics              (section)
	seller.logistics.packing      (group)
	seller.logistics.packing.queue (item, route /lojistik/paketleme)

NEDEN GEREKLİ:
	Satıcı sidebar'ı tamamen DB-driven (TH Module Registry). `stores/navigation.js`
	satıcıda fail-secure davranıyor: DB yüklüyse frontend'deki statik
	`sellerPanelSections` fallback'ine ASLA düşmüyor. 13-FE paketleme ekranı
	route olarak var, yetkiler doğru çalışıyor (ölçüldü: satıcıda etiket
	üretme/basma açık, iptal kapalı) — ama registry kaydı olmadığı için
	menüde hiç görünmüyordu: ray vardı, açılan bölüm boştu.

	Satıcıya YALNIZ paketleme açılıyor. Katalog, taşıyıcı hesapları ve lojistik
	ayarları platform ekranı; admin menüsünde kalır.

Spec kaynağı: setup/module_navigation_spec.py (key bazında seçilir).
Desen: v15_8_10_seed_media_library_nav.py
"""

from __future__ import annotations

import frappe

# Sıra ÖNEMLİ: parent'lar çocuklardan önce eklenmeli (nested set).
_KEYS = (
	"seller.logistics",
	"seller.logistics.packing",
	"seller.logistics.packing.queue",
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
			frappe.log_error(f"{key} spec'te bulunamadı", "v15_9_20_seed_logistics_seller_nav")
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

	if created:
		frappe.db.commit()
		try:
			frappe.utils.nestedset.rebuild_tree("TH Module Registry", "parent_th_module_registry")
		except Exception:
			frappe.log_error("nav rebuild_tree failed", "v15_9_20_seed_logistics_seller_nav")

	return {"created": created}
