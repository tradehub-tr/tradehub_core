"""Satıcı sidebar'ına Lojistik → Fiyatlandırma navigasyonunu ekle (20-FE).

TH Module Registry'de dört kayıt oluşturur (idempotent):
	seller.logistics.pricing             (group)
	seller.logistics.pricing.rates       (item, /lojistik/tarifeler)
	seller.logistics.pricing.rules       (item, /lojistik/fiyat-kurallari)
	seller.logistics.pricing.simulation  (item, /lojistik/fiyat-simulasyonu)

NEDEN GEREKLİ:
	Satıcı sidebar'ı tamamen DB-driven. `stores/navigation.js` satıcıda
	fail-secure: DB yüklüyse frontend'deki statik `sellerPanelSections`
	fallback'ine ASLA düşmüyor. Ekranlar route olarak var ve manifestte
	`sellerVisible: true` — ama registry kaydı olmadan menüde HİÇ görünmüyor.

	13-FE'de tam bu adım atlandı ve satıcı menüsü boş kaldı; 14-FE'de
	sözleşmeye yazılarak tekrarlanması önlendi. 20-FE'de ölçüldü
	(2026-08-21): kayıt yokken `/panel/lojistik/tarifeler` adresi elle
	yazılınca AÇILIYOR, ama menüde görünmüyor — yani ekran ulaşılamaz.

HANGİ EKRANLAR VE NEDEN (20-FE karar defteri K1/K2):
	* Kargo fiyatlarım (K1) — satıcı kendi taşıyıcı anlaşmasını platform
	  üzerinden kullanabiliyor; hangi fiyata gittiğini görmesi gerekiyor.
	* Kargo kurallarım (K2) — kendi kuralını yazar; platform kuralları
	  salt-okunur.
	* Fiyat hesapla (K3) — "kargom neden 360 ₺" sorusunu destek hattına
	  düşmeden kendi cevaplayabilsin.

	K4 (kural formu) parametreli detay rotası — menüde YOK, listeden açılır.

	Maskeleme bu kayıtla İLGİSİZ: platformun alış maliyeti backend'de
	kırpılıyor (20-FE veri sözleşmesi §7.2). Kayıt yalnız kapıyı açar.

Spec kaynağı: setup/module_navigation_spec.py (key bazında seçilir).
Desen: v15_9_23_seed_seller_delivery_nav.py
"""

from __future__ import annotations

import frappe

# Sıra ÖNEMLİ: parent çocuklardan önce eklenmeli (nested set).
_KEYS = (
	"seller.logistics.pricing",
	"seller.logistics.pricing.rates",
	"seller.logistics.pricing.rules",
	"seller.logistics.pricing.simulation",
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
			frappe.log_error(f"{key} spec'te bulunamadı", "v15_9_37_seed_seller_pricing_nav")
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
			frappe.log_error("nav rebuild_tree failed", "v15_9_37_seed_seller_pricing_nav")

	return {"created": created}
