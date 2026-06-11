# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Faz J — Admin Plan Feature matrix endpoint'leri.

Admin panel "Paket İçeriği" sekmesi ModuleMatrixTab pattern'iyle matris UI
çalıştırır:
  - Üst: planlar (kolonlar)
  - Sol: feature'lar (kategori grupları halinde)
  - Hücre: value_type'a göre checkbox veya text

Bu modül iki endpoint sunar:
  - list_plan_features: matrisi besler (catalog + plan'lardaki mevcut row'lar)
  - bulk_update_plan_features: pendingChanges saveAll — hücre güncelleyip
    public_pricing cache'ini flush eder.

Yetki: System Manager veya Marketplace Admin. plan_code regex ile sertleştirilir.
"""

from __future__ import annotations

import re

import frappe
from frappe import _

from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache

# Plan code: UPPERCASE veya lowercase, snake_case veya kebab-case
_PLAN_CODE_PATTERN = re.compile(r"^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$")
_FEATURE_KEY_PATTERN = re.compile(r"^(feature|quota)\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")
_VALUE_TYPES = frozenset({"checkbox", "text"})


def _legacy_cell_type(value_type: str) -> str:
	"""Feature Catalog.value_type (4-tip) → legacy hücre tipi (checkbox/text).

	Burada lokal tanımlı — feature_catalog modülü plan_features'tan import ettiği
	için ters yönde import circular olur.
	"""
	return "checkbox" if value_type == "boolean" else "text"


# Komisyon & aktif ürün limiti storefront'ta plan FIELD'ından (commission_rate,
# max_active_listings) okunur (public_pricing override). Bu yüzden bu iki feature
# hücresi düzenlenince ilgili plan field'ı da senkronlanır — yoksa storefront
# eski değeri gösterir.
_PLAN_FIELD_BY_FEATURE = {
	"quota.commission_rate": "commission_rate",
	"quota.max_active_listings": "max_active_listings",
}


def _parse_commission(text_value: str) -> float:
	"""'%4' / '4' → 4.0; 'Özel' vb. → 0.0 (storefront 0'ı 'Özel' gösterir)."""
	tv = (text_value or "").strip().replace("%", "").replace(",", ".")
	try:
		return float(tv)
	except ValueError:
		return 0.0


def _parse_listings(text_value: str) -> int:
	"""'2.500' → 2500; 'Sınırsız' vb. → 0 (storefront 0'ı 'Sınırsız' gösterir)."""
	tv = (text_value or "").strip().replace(".", "").replace(",", "").replace(" ", "")
	try:
		return int(tv)
	except ValueError:
		return 0


def _require_plan_admin() -> None:
	"""System Manager veya Marketplace Admin gerekir."""
	user = frappe.session.user
	if user == "Administrator":
		return
	user_roles = set(frappe.get_roles(user))
	allowed = {"System Manager", "Marketplace Admin"}
	if not (user_roles & allowed):
		frappe.throw(
			_("Plan özelliklerini düzenleme yetkiniz yok"),
			frappe.PermissionError,
		)


def _resolve_plan_name(plan_code: str) -> str:
	"""UPPERCASE veya lowercase varyantını DB'de bulup gerçek name'i döner."""
	if not _PLAN_CODE_PATTERN.match(plan_code):
		frappe.throw(_("Geçersiz plan_code: {0}").format(plan_code))
	for variant in (plan_code, plan_code.upper(), plan_code.lower()):
		if frappe.db.exists("Subscription Plan", variant):
			return variant
	frappe.throw(_("Plan bulunamadı: {0}").format(plan_code))


@frappe.whitelist()
def list_plan_features() -> dict:
	"""Admin matris UI için: tüm aktif planlar + Feature Catalog kategorileri
	+ her hücre için mevcut value.

	Returns:
		{
			"plans": [
				{"plan_code": "FREE", "plan_name": "Free", "name": "FREE"},
				...
			],
			"categories": [
				{
					"name": "Komisyon & Limitler",
					"features": [
						{
							"feature_key": "...",
							"display_name": "...",
							"value_type": "checkbox" | "text",
							"feature_type": "Capability" | "Quota",
							"display_order": 10,
							"tooltip": "...",
							"values_by_plan": {
								"FREE": {"value_type": "checkbox", "is_included": true, "text_value": ""},
								...
							}
						},
						...
					]
				},
				...
			]
		}
	"""
	_require_plan_admin()

	plans_raw = frappe.get_all(
		"Subscription Plan",
		filters={"is_active": 1},
		fields=[
			"name",
			"plan_code",
			"plan_name",
			"display_order",
			"commission_rate",
			"max_active_listings",
		],
		order_by="display_order asc, plan_code asc",
	)
	plan_names = [p["name"] for p in plans_raw]
	plan_code_by_name = {p["name"]: (p.get("plan_code") or p["name"]) for p in plans_raw}

	# Faz J — Matris text_value boşsa plan field'dan fallback (admin UI'da
	# input'lar dolu kalsın; bidirectional sync). Save sırasında text_value
	# plan field'a yazılır; load sırasında plan field text_value'ya yansır.
	plan_field_fallbacks: dict[tuple[str, str], str] = {}
	for p in plans_raw:
		code = plan_code_by_name[p["name"]]
		cr = p.get("commission_rate")
		if cr is not None and float(cr) > 0:
			plan_field_fallbacks[("quota.commission_rate", code)] = (
				str(int(cr)) if float(cr).is_integer() else str(cr)
			)
		mal = p.get("max_active_listings")
		if mal:
			plan_field_fallbacks[("quota.max_active_listings", code)] = str(int(mal))

	# Feature Catalog — sadece display_category set edilmiş, deprecated olmayan
	catalog_rows = frappe.get_all(
		"Feature Catalog",
		filters={"is_deprecated": 0, "display_category": ["is", "set"]},
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
		],
		order_by="display_category asc, display_order asc, display_name asc",
	)
	catalog_rows = [r for r in catalog_rows if (r.get("display_category") or "").strip()]

	# Plan-Feature row'ları (matris hücreleri)
	feature_rows = frappe.get_all(
		"Pricing Plan Feature",
		filters={"parent": ["in", plan_names], "parenttype": "Subscription Plan"},
		fields=[
			"name",
			"parent",
			"feature_key",
			"value_type",
			"is_included",
			"text_value",
			"show_on_card",
			"sort_order",
			"display_text",
		],
	)
	cell_by_key_and_plan: dict[tuple[str, str], dict] = {}
	for row in feature_rows:
		fkey = row.get("feature_key")
		if not fkey:
			continue
		plan_code = plan_code_by_name.get(row["parent"], row["parent"])
		cell_by_key_and_plan[(fkey, plan_code)] = {
			"row_name": row["name"],
			"value_type": row.get("value_type") or "checkbox",
			"is_included": bool(row.get("is_included")),
			"text_value": row.get("text_value") or "",
			"show_on_card": bool(row.get("show_on_card")),
		}

	# Kategori grupla
	plan_codes = [plan_code_by_name[n] for n in plan_names]
	categories_map: dict[str, list[dict]] = {}
	category_order: list[str] = []
	for row in catalog_rows:
		cat = row["display_category"]
		if cat not in categories_map:
			categories_map[cat] = []
			category_order.append(cat)

		# Faz A — value_type kaynağı Feature Catalog (feature-seviyesi), hücre değil.
		control_type = row.get("value_type") or "boolean"
		legacy_vt = _legacy_cell_type(control_type)
		enum_options = [o.strip() for o in (row.get("enum_options") or "").split(",") if o.strip()]
		values_by_plan: dict[str, dict] = {}
		for code in plan_codes:
			cell = cell_by_key_and_plan.get((row["feature_key"], code))
			fallback_text = plan_field_fallbacks.get((row["feature_key"], code), "")
			if cell:
				# Cell var ama text_value boşsa plan field'dan doldur (input dolu görünsün)
				text_value = cell["text_value"] or fallback_text
				values_by_plan[code] = {
					"value_type": legacy_vt,
					"is_included": cell["is_included"] or bool(fallback_text),
					"text_value": text_value,
					"show_on_card": cell["show_on_card"],
				}
			else:
				values_by_plan[code] = {
					"value_type": legacy_vt,
					"is_included": bool(fallback_text),
					"text_value": fallback_text,
					"show_on_card": bool(row.get("show_on_card")),
				}

		categories_map[cat].append(
			{
				"feature_key": row["feature_key"],
				"display_name": row["display_name"],
				# Legacy alan (checkbox/text) — geriye uyum; yeni UI control_type kullanır.
				"value_type": legacy_vt,
				"control_type": control_type,
				"enum_options": enum_options,
				"unit": row.get("unit") or "",
				"feature_type": row.get("feature_type") or "Capability",
				"display_order": row.get("display_order") or 0,
				"tooltip": row.get("description") or None,
				# Feature-seviyesi varsayılan (geriye uyum); plan başına kürasyon
				# values_by_plan[code].show_on_card alanındadır.
				"show_on_card": bool(row.get("show_on_card")),
				"values_by_plan": values_by_plan,
			}
		)

	preferred_order = [
		"Komisyon & Limitler",
		"Vitrin & Mağaza",
		"B2B Ticaret Modülleri",
		"Pazarlama & Görünürlük",
		"Güven & Doğrulama",
		"Destek & Kurumsal",
	]
	ordered_categories = [c for c in preferred_order if c in categories_map]
	for c in category_order:
		if c not in ordered_categories:
			ordered_categories.append(c)

	return {
		"plans": [
			{
				"name": p["name"],
				"plan_code": plan_code_by_name[p["name"]],
				"plan_name": p.get("plan_name") or plan_code_by_name[p["name"]],
				"display_order": p.get("display_order") or 0,
			}
			for p in plans_raw
		],
		"categories": [{"name": c, "features": categories_map[c]} for c in ordered_categories],
	}


@frappe.whitelist()
def bulk_update_plan_features(updates: str | list) -> dict:
	"""Matris saveAll — birden çok hücreyi tek seferde güncelle.

	Args:
		updates: JSON string veya list of dicts:
			[
				{
					"plan_code": "FREE",
					"feature_key": "sample_sales",
					"value_type": "checkbox",
					"is_included": true,
					"text_value": ""
				},
				...
			]

	Returns:
		{"updated": int, "created": int, "errors": [...]}
	"""
	_require_plan_admin()

	if isinstance(updates, str):
		import json

		try:
			updates = json.loads(updates)
		except (json.JSONDecodeError, TypeError) as e:
			frappe.throw(_("Geçersiz JSON: {0}").format(str(e)))

	if not isinstance(updates, list):
		frappe.throw(_("updates bir liste olmalı"))

	updated = 0
	created = 0
	errors: list[dict] = []

	# Plan-bazlı grupla — her plan tek save() ile güncellensin.
	# Faz A: hücre value_type'ına entry'den GÜVENİLMEZ; kaynak Feature Catalog.
	by_plan: dict[str, list[dict]] = {}
	for entry in updates:
		if not isinstance(entry, dict):
			errors.append({"entry": entry, "error": "dict olmalı"})
			continue
		plan_code = entry.get("plan_code")
		feature_key = entry.get("feature_key")
		if not plan_code or not feature_key:
			errors.append({"entry": entry, "error": "plan_code ve feature_key zorunlu"})
			continue
		if not _FEATURE_KEY_PATTERN.match(feature_key):
			errors.append({"entry": entry, "error": "feature_key formatı hatalı"})
			continue
		by_plan.setdefault(plan_code, []).append(entry)

	for plan_code, entries in by_plan.items():
		try:
			plan_name = _resolve_plan_name(plan_code)
		except frappe.ValidationError as e:
			errors.append({"plan_code": plan_code, "error": str(e)})
			continue

		plan = frappe.get_doc("Subscription Plan", plan_name)
		# feature_key → existing row index map (parent doc'ta)
		row_by_key: dict[str, object] = {}
		for row in plan.get("pricing_features") or []:
			if row.get("feature_key"):
				row_by_key[row.feature_key] = row

		# Feature Catalog'tan display_name + value_type (hücre tipi kaynağı)
		feature_keys_in_batch = [e["feature_key"] for e in entries]
		catalog = {
			r["feature_key"]: r
			for r in frappe.get_all(
				"Feature Catalog",
				filters={"feature_key": ["in", feature_keys_in_batch]},
				fields=["feature_key", "display_name", "value_type"],
			)
		}

		for entry in entries:
			fkey = entry["feature_key"]
			cat = catalog.get(fkey, {})
			display_name = cat.get("display_name") or fkey
			# Hücre tipi katalogdan türetilir (entry'den değil)
			legacy_vt = _legacy_cell_type(cat.get("value_type") or "boolean")
			is_included = 1 if bool(entry.get("is_included")) else 0
			text_value = (entry.get("text_value") or "").strip()
			# show_on_card opsiyonel — gönderildiyse güncelle, yoksa koru
			has_card = "show_on_card" in entry
			card_val = 1 if bool(entry.get("show_on_card")) else 0

			# Komisyon / ürün limiti → plan field senkronu (storefront kaynağı)
			plan_field = _PLAN_FIELD_BY_FEATURE.get(fkey)
			if plan_field == "commission_rate":
				plan.commission_rate = _parse_commission(text_value)
			elif plan_field == "max_active_listings":
				plan.max_active_listings = _parse_listings(text_value)

			# is_disabled (per-kart üstü-çizili) is_included ile senkron tutulur:
			# boolean → dahil değilse disabled; text → değeri boşsa disabled.
			is_disabled = 0 if is_included else 1

			row = row_by_key.get(fkey)
			if row:
				row.value_type = legacy_vt
				row.is_included = is_included
				row.is_disabled = is_disabled
				row.text_value = text_value if legacy_vt == "text" else ""
				if has_card:
					row.show_on_card = card_val
				if not row.get("display_text"):
					row.display_text = display_name
				updated += 1
			else:
				new_row = plan.append("pricing_features", {})
				new_row.feature_key = fkey
				new_row.value_type = legacy_vt
				new_row.is_included = is_included
				new_row.is_disabled = is_disabled
				new_row.text_value = text_value if legacy_vt == "text" else ""
				new_row.show_on_card = card_val
				new_row.display_text = display_name
				created += 1

		plan.flags.ignore_permissions = True
		plan.flags.ignore_mandatory = True
		plan.flags.ignore_links = True
		plan.save(ignore_permissions=True)

	frappe.db.commit()
	invalidate_pricing_cache()

	return {"updated": updated, "created": created, "errors": errors}
