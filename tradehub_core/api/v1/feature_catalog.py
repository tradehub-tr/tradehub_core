# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Faz K — Admin Feature Catalog CRUD endpoint'leri.

Admin panel "Paket İçeriği" matrisinin satırlarını (özellikleri) yönetir.
`plan_features.py` sadece var olan feature'ların plan başına hücre değerini
değiştirir; bu modül feature'ın kendisini ekler/günceller/siler/sıralar.

Yeni bir feature eklendiğinde her aktif plan için boş bir Pricing Plan Feature
hücresi seed edilir; böylece matris satırı doğru input tipiyle (checkbox/text)
hemen görünür. Silme varsayılan olarak soft (is_deprecated=1) — mevcut hücre
verisi kaybolmasın.

Yetki: System Manager veya Marketplace Admin.
"""

from __future__ import annotations

import frappe
from frappe import _

from tradehub_core.api.v1.plan_features import _require_plan_admin
from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

# Faz A — value_type artık feature-seviyesi (Feature Catalog), hücre değil.
_VALUE_TYPES = frozenset({"boolean", "quota", "enum", "text"})

# Storefront matris kategorilerinin tercih edilen sırası — public_pricing ve
# plan_features ile aynı. Yeni kategoriler bu listenin sonuna eklenir.
_PREFERRED_CATEGORY_ORDER = [
	"Komisyon & Limitler",
	"Vitrin & Mağaza",
	"B2B Ticaret Modülleri",
	"Pazarlama & Görünürlük",
	"Güven & Doğrulama",
	"Destek & Kurumsal",
]


def _feature_type_from_key(feature_key: str) -> str:
	"""'feature.*' → Capability, 'quota.*' → Quota."""
	return "Capability" if feature_key.startswith("feature.") else "Quota"


def _legacy_cell_type(value_type: str) -> str:
	"""Feature value_type (4-tip) → legacy Pricing Plan Feature.value_type.

	boolean → checkbox (✓/boş); quota/enum/text → text. Storefront/admin geriye
	uyumu için hücrelerde tutuluyor; kaynak Feature Catalog.value_type.
	"""
	return "checkbox" if value_type == "boolean" else "text"


def _split_options(raw: str | None) -> list[str]:
	"""enum_options ham metnini ('A,B,C') temiz listeye çevir."""
	if not raw:
		return []
	return [o.strip() for o in str(raw).split(",") if o.strip()]


def _join_options(options) -> str:
	"""Liste veya virgüllü metni normalize edilmiş 'A,B,C' formatına getir."""
	if isinstance(options, str):
		items = _split_options(options)
	elif isinstance(options, list | tuple):
		items = [str(o).strip() for o in options if str(o).strip()]
	else:
		return ""
	return ",".join(items)


@frappe.whitelist()
def list_feature_catalog() -> dict:
	"""Yönetim ekranı için tüm storefront feature'larını (deprecated dahil) döner.

	Returns:
		{
			"features": [
				{
					"feature_key": "feature.storefront.tier",
					"display_name": "Vitrin tipi",
					"display_category": "Vitrin & Sergileme",
					"display_order": 20,
					"feature_type": "Capability",
					"description": "...",
					"show_on_card": true,
					"is_deprecated": false
				},
				...
			],
			"categories": ["Komisyon & Limitler", "Vitrin & Sergileme", ...]
		}
	"""
	_require_plan_admin()

	rows = frappe.get_all(
		"Feature Catalog",
		fields=[
			"feature_key",
			"display_name",
			"display_category",
			"display_order",
			"feature_type",
			"value_type",
			"enum_options",
			"unit",
			"description",
			"show_on_card",
			"is_coming_soon",
			"is_deprecated",
		],
		order_by="display_category asc, display_order asc, display_name asc",
	)

	features = [
		{
			"feature_key": r["feature_key"],
			"display_name": r["display_name"],
			"display_category": r.get("display_category") or "",
			"display_order": r.get("display_order") or 0,
			"feature_type": r.get("feature_type") or "Capability",
			"value_type": r.get("value_type") or "boolean",
			"enum_options": _split_options(r.get("enum_options")),
			"unit": r.get("unit") or "",
			"description": r.get("description") or "",
			"show_on_card": bool(r.get("show_on_card")),
			"is_coming_soon": bool(r.get("is_coming_soon")),
			"is_deprecated": bool(r.get("is_deprecated")),
		}
		for r in rows
	]

	# Mevcut kategorileri tercih sırasıyla, bilinmeyenleri sona ekleyerek topla
	existing = []
	for r in rows:
		cat = (r.get("display_category") or "").strip()
		if cat and cat not in existing:
			existing.append(cat)
	ordered = [c for c in _PREFERRED_CATEGORY_ORDER if c in existing]
	for c in existing:
		if c not in ordered:
			ordered.append(c)

	return {"features": features, "categories": ordered}


@frappe.whitelist()
def create_feature(
	feature_key: str,
	display_name: str,
	display_category: str,
	value_type: str = "boolean",
	enum_options=None,
	display_order: int = 0,
	description: str = "",
	show_on_card: int = 0,
	is_coming_soon: int = 0,
	unit: str = "",
) -> dict:
	"""Yeni storefront feature'ı oluştur + her aktif plan için boş hücre seed et.

	value_type (boolean/quota/enum/text) Feature Catalog'a yazılır ve tüm planlarda
	tutarlı kontrol tipini belirler. feature_type, key prefix'inden türetilir
	(feature.* → Capability, quota.* → Quota). enum value_type için enum_options
	(virgüllü metin veya liste) gerekir.
	"""
	_require_plan_admin()

	feature_key = (feature_key or "").strip()
	display_name = (display_name or "").strip()
	display_category = (display_category or "").strip()
	value_type = (value_type or "boolean").strip()

	if not feature_key or not display_name or not display_category:
		frappe.throw(_("feature_key, display_name ve display_category zorunlu"))
	if value_type not in _VALUE_TYPES:
		frappe.throw(_("value_type boolean / quota / enum / text olmalı"))
	options = _join_options(enum_options)
	if value_type == "enum" and not options:
		frappe.throw(_("enum value_type için en az bir seçenek (enum_options) gerekir"))
	if frappe.db.exists("Feature Catalog", feature_key):
		frappe.throw(_("Bu feature_key zaten mevcut: {0}").format(feature_key))

	doc = frappe.get_doc(
		{
			"doctype": "Feature Catalog",
			"feature_key": feature_key,
			"display_name": display_name,
			"category": "FunctionalFeatures",
			"feature_type": _feature_type_from_key(feature_key),
			"display_category": display_category,
			"value_type": value_type,
			"enum_options": options,
			"display_order": int(display_order or 0),
			"description": description or "",
			"show_on_card": 1 if int(show_on_card or 0) else 0,
			"is_coming_soon": 1 if int(is_coming_soon or 0) else 0,
			"unit": unit or "",
		}
	)
	# Feature Catalog validate'i key formatı + tip uyumunu zorlar (i18n hata)
	doc.insert(ignore_permissions=True)

	seeded = _seed_feature_cells(
		feature_key,
		display_name,
		_legacy_cell_type(value_type),
		int(display_order or 0),
		1 if int(show_on_card or 0) else 0,
	)

	frappe.db.commit()
	invalidate_pricing_cache()

	return {"feature_key": feature_key, "seeded_plans": seeded}


@frappe.whitelist()
def update_feature(
	feature_key: str,
	display_name: str | None = None,
	display_category: str | None = None,
	value_type: str | None = None,
	enum_options=None,
	unit: str | None = None,
	display_order: int | None = None,
	description: str | None = None,
	show_on_card: int | None = None,
	is_coming_soon: int | None = None,
) -> dict:
	"""Var olan feature'ın storefront alanlarını güncelle. feature_key sabit kalır.

	value_type değişirse tüm plan hücrelerinin legacy value_type'ı (checkbox/text)
	yeniden senkronlanır; böylece matris/storefront tutarlı kalır.
	"""
	_require_plan_admin()

	feature_key = (feature_key or "").strip()
	if not frappe.db.exists("Feature Catalog", feature_key):
		frappe.throw(_("Feature bulunamadı: {0}").format(feature_key))

	doc = frappe.get_doc("Feature Catalog", feature_key)
	value_type_changed = False
	if display_name is not None:
		doc.display_name = display_name.strip()
	if display_category is not None:
		doc.display_category = display_category.strip()
	if value_type is not None:
		vt = value_type.strip()
		if vt not in _VALUE_TYPES:
			frappe.throw(_("value_type boolean / quota / enum / text olmalı"))
		value_type_changed = vt != (doc.value_type or "boolean")
		doc.value_type = vt
	if enum_options is not None:
		doc.enum_options = _join_options(enum_options)
	if unit is not None:
		doc.unit = unit.strip()
	if display_order is not None:
		doc.display_order = int(display_order)
	if description is not None:
		doc.description = description
	if show_on_card is not None:
		doc.show_on_card = 1 if int(show_on_card) else 0
	if is_coming_soon is not None:
		doc.is_coming_soon = 1 if int(is_coming_soon) else 0
	if doc.value_type == "enum" and not _split_options(doc.enum_options):
		frappe.throw(_("enum value_type için en az bir seçenek (enum_options) gerekir"))
	doc.save(ignore_permissions=True)

	# value_type değiştiyse hücrelerin legacy tipini resync et
	if value_type_changed:
		legacy = _legacy_cell_type(doc.value_type)
		frappe.db.set_value(
			"Pricing Plan Feature",
			{"feature_key": feature_key, "parenttype": "Subscription Plan"},
			"value_type",
			legacy,
		)

	frappe.db.commit()
	invalidate_pricing_cache()

	return {"feature_key": feature_key}


@frappe.whitelist()
def delete_feature(feature_key: str, hard: int = 0) -> dict:
	"""Feature'ı sil. Varsayılan soft (is_deprecated=1); hard=1 ise tamamen kaldır.

	Soft silme matristen düşürür ama plan hücrelerini korur (geri alınabilir).
	Hard silme Feature Catalog kaydını + tüm plan hücrelerini siler.
	"""
	_require_plan_admin()

	feature_key = (feature_key or "").strip()
	if not frappe.db.exists("Feature Catalog", feature_key):
		frappe.throw(_("Feature bulunamadı: {0}").format(feature_key))

	if int(hard or 0):
		# Önce plan hücrelerini temizle (child row'lar parent save ile değil,
		# doğrudan silinir — Feature Catalog ile FK ilişkisi yok)
		frappe.db.delete("Pricing Plan Feature", {"feature_key": feature_key})
		frappe.delete_doc("Feature Catalog", feature_key, ignore_permissions=True, force=True)
		mode = "hard"
	else:
		frappe.db.set_value("Feature Catalog", feature_key, "is_deprecated", 1)
		mode = "soft"

	frappe.db.commit()
	invalidate_pricing_cache()

	return {"feature_key": feature_key, "mode": mode}


@frappe.whitelist()
def restore_feature(feature_key: str) -> dict:
	"""Soft-silinmiş (is_deprecated=1) bir feature'ı geri al."""
	_require_plan_admin()

	feature_key = (feature_key or "").strip()
	if not frappe.db.exists("Feature Catalog", feature_key):
		frappe.throw(_("Feature bulunamadı: {0}").format(feature_key))

	frappe.db.set_value("Feature Catalog", feature_key, "is_deprecated", 0)
	frappe.db.commit()
	invalidate_pricing_cache()

	return {"feature_key": feature_key}


@frappe.whitelist()
def reorder_features(orders: str | list) -> dict:
	"""Toplu display_order güncelle.

	Args:
		orders: [{"feature_key": "...", "display_order": 10}, ...]
	"""
	_require_plan_admin()

	if isinstance(orders, str):
		import json

		try:
			orders = json.loads(orders)
		except (json.JSONDecodeError, TypeError) as e:
			frappe.throw(_("Geçersiz JSON: {0}").format(str(e)))
	if not isinstance(orders, list):
		frappe.throw(_("orders bir liste olmalı"))

	updated = 0
	for entry in orders:
		if not isinstance(entry, dict):
			continue
		fkey = (entry.get("feature_key") or "").strip()
		if not fkey or not frappe.db.exists("Feature Catalog", fkey):
			continue
		frappe.db.set_value("Feature Catalog", fkey, "display_order", int(entry.get("display_order") or 0))
		updated += 1

	frappe.db.commit()
	invalidate_pricing_cache()

	return {"updated": updated}


def _seed_feature_cells(
	feature_key: str,
	display_name: str,
	legacy_value_type: str,
	sort_order: int,
	show_on_card: int = 0,
) -> int:
	"""Her aktif plan için boş bir Pricing Plan Feature hücresi ekle.

	legacy_value_type (checkbox/text) hücre input tipini belirler (kaynak
	Feature Catalog.value_type'tan türetilir). show_on_card hücre başına
	varsayılan kart görünürlüğüdür. Zaten hücresi olan planı atlar.
	"""
	plans = frappe.get_all("Subscription Plan", filters={"is_active": 1}, fields=["name"])
	seeded = 0
	for p in plans:
		plan = frappe.get_doc("Subscription Plan", p["name"])
		already = any((row.get("feature_key") == feature_key) for row in (plan.get("pricing_features") or []))
		if already:
			continue
		new_row = plan.append("pricing_features", {})
		new_row.feature_key = feature_key
		new_row.value_type = legacy_value_type
		new_row.is_included = 0
		new_row.text_value = ""
		new_row.show_on_card = 1 if show_on_card else 0
		new_row.display_text = display_name
		new_row.sort_order = sort_order
		plan.flags.ignore_permissions = True
		plan.flags.ignore_mandatory = True
		plan.flags.ignore_links = True
		plan.save(ignore_permissions=True)
		seeded += 1
	return seeded
