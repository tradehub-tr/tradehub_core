"""Satıcı sidebar'ına Lojistik → Teslimat navigasyonunu ekle (14-FE).

TH Module Registry'de dört kayıt oluşturur (idempotent):
	seller.logistics.delivery                  (group)
	seller.logistics.delivery.pod              (item, /lojistik/teslim-kaniti)
	seller.logistics.delivery.seller_delivery  (item, /lojistik/satici-teslimati)
	seller.logistics.delivery.buyer_pickup     (item, /lojistik/alici-teslim-alma)

NEDEN GEREKLİ:
	Satıcı sidebar'ı tamamen DB-driven (TH Module Registry). `stores/navigation.js`
	satıcıda fail-secure davranıyor: DB yüklüyse frontend'deki statik
	`sellerPanelSections` fallback'ine ASLA düşmüyor. Ekranlar route olarak var
	ve manifestte `sellerVisible: true` işaretli — ama registry kaydı olmadan
	menüde HİÇ görünmüyor.

	13-FE'de bu adım backend'e bırakıldı ve satıcı menüsü boş kaldı; 14-FE'de
	tekrarlanmasın diye kayıt sözleşmeye baştan yazıldı
	(docs/lojistik/14-FE-VERI-SOZLESMESI.md §8).

HANGİ EKRANLAR VE NEDEN:
	* Teslim kanıtı (H0) — satıcı kendi teslimatının kanıtını KAYDEDEBİLİYOR
	  (14-FE karar defteri K-B); kuyruk onun giriş kapısı.
	* Satıcı teslimatı (D1) — kendi aracıyla teslim satıcının fiziksel işi.
	* Alıcı teslim alma (D2) — alıcının teslim alacağı paketi hazır eden satıcı.
	  D1/D2 kararı: G0 rol matrisi + 14-FE K-M.

	Tenant izolasyonu backend'de: bu kayıtlar yalnız KAPIYI açar, veri sınırını
	değiştirmez.

Spec kaynağı: setup/module_navigation_spec.py (key bazında seçilir).
Desen: v15_9_20_seed_logistics_seller_nav.py
"""

from __future__ import annotations

import frappe

# Sıra ÖNEMLİ: parent çocuklardan önce eklenmeli (nested set).
_KEYS = (
	"seller.logistics.delivery",
	"seller.logistics.delivery.pod",
	"seller.logistics.delivery.seller_delivery",
	"seller.logistics.delivery.buyer_pickup",
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
			frappe.log_error(f"{key} spec'te bulunamadı", "v15_9_23_seed_seller_delivery_nav")
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
			frappe.log_error("nav rebuild_tree failed", "v15_9_23_seed_seller_delivery_nav")

	return {"created": created}
