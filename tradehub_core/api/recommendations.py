"""Whitelisted endpoints exposing the Related Products engine to the
admin panel UI.

Only Marketplace Admin / System Manager roles can mutate settings or
trigger a rebuild — `_require_admin` guards every write path. Read
endpoints (status, settings) inherit the underlying DocType permissions
so the same role gating applies.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import frappe
from frappe import _

from tradehub_core.recommendations import engine, swap

_ADMIN_ROLES = {"System Manager", "Marketplace Admin"}


def _require_admin() -> None:
	"""Raise frappe.PermissionError if caller lacks admin role."""
	user_roles = set(frappe.get_roles(frappe.session.user))
	if not user_roles & _ADMIN_ROLES:
		frappe.throw(
			_("Bu işlem için Marketplace Admin yetkisi gerekiyor."),
			frappe.PermissionError,
		)


@frappe.whitelist()
def get_settings() -> dict[str, Any]:
	"""Return the current Related Products Settings as a flat dict suitable
	for the admin form. Cached for 60s by the underlying get_settings call.
	"""
	_require_admin()
	from tradehub_core.tradehub_core.doctype.related_products_settings.related_products_settings import (
		get_settings as _settings,
	)

	return _settings()


@frappe.whitelist()
def update_settings(payload: dict[str, Any]) -> dict[str, Any]:
	"""Persist edited fields back to the Single DocType.

	Accepts either flat keys (max_results_per_tab, min_score_threshold,
	embedding_cosine_threshold, copurchase_lift_threshold,
	accessory_price_ratio_threshold) or nested per-scorer weights
	(similar.category, complementary.copurchase, etc.).
	"""
	_require_admin()
	if isinstance(payload, str):
		# Frappe whitelist may pass JSON strings depending on the client
		import json

		payload = json.loads(payload)

	doc = frappe.get_single("Related Products Settings")
	field_map = _flatten_payload(payload)
	for fieldname, value in field_map.items():
		if hasattr(doc, fieldname):
			setattr(doc, fieldname, value)
	doc.save(ignore_permissions=False)
	frappe.db.commit()
	# Bust the 60s settings cache so changes take effect immediately on
	# the next compute_for_listing call.
	frappe.cache().delete_key("related_products_settings")
	return {"status": "saved", "fields_updated": list(field_map.keys())}


@frappe.whitelist()
def trigger_rebuild() -> dict[str, Any]:
	"""Manually dispatch a full Related Listing Cache rebuild.

	Returns immediately after enqueueing chunks; the actual work runs on
	long-queue workers. Use `get_status` to poll progress.
	"""
	_require_admin()
	return engine.dispatch_full_rebuild()


@frappe.whitelist()
def get_status() -> dict[str, Any]:
	"""Return a snapshot of recommendation system health for the admin UI.

	Surfaces:
	  * row counts per relation type in PROD cache
	  * shadow table presence (indicates an in-flight rebuild)
	  * embedding + neighbour cache size
	  * last computed_at across the cache
	"""
	_require_admin()
	rows = frappe.db.sql(
		f"""
        SELECT relation_type, COUNT(*) AS cnt, MAX(computed_at) AS last_at
        FROM `{swap.PROD_TABLE}`
        GROUP BY relation_type
        """,
		as_dict=True,
	)
	by_type: dict[str, dict[str, Any]] = {}
	for r in rows:
		by_type[r["relation_type"]] = {
			"count": int(r["cnt"]),
			"last_computed_at": _serialize_dt(r["last_at"]),
		}

	embedding_count = (
		frappe.db.count("Category Embedding") if frappe.db.table_exists("Category Embedding") else 0
	)
	neighbour_count = (
		frappe.db.count("Category Neighbour Cache")
		if frappe.db.table_exists("Category Neighbour Cache")
		else 0
	)
	active_categories = frappe.db.count("Product Category", {"is_active": 1})
	active_listings = frappe.db.count("Listing", {"status": "Active", "is_visible": 1})

	return {
		"cache_by_relation": by_type,
		"cache_total": sum(b["count"] for b in by_type.values()),
		"shadow_in_progress": swap.shadow_exists(),
		"embedding_count": embedding_count,
		"neighbour_count": neighbour_count,
		"active_categories": active_categories,
		"active_listings": active_listings,
	}


# ─── helpers ──────────────────────────────────────────────────────────

# Maps nested payload keys to the flat fieldnames on Related Products Settings.
_NESTED_FIELD_MAP = {
	("similar", "category"): "weight_similar_category",
	("similar", "attribute"): "weight_similar_attribute",
	("similar", "price_tier"): "weight_similar_price_tier",
	("similar", "rating"): "weight_similar_rating",
	("substitute", "same_category"): "weight_substitute_same_category",
	("substitute", "different_seller"): "weight_substitute_different_seller",
	("substitute", "attribute"): "weight_substitute_attribute",
	("substitute", "price_proximity"): "weight_substitute_price_proximity",
	("complementary", "copurchase"): "weight_complementary_copurchase",
	("complementary", "coview"): "weight_complementary_coview",
	("complementary", "embedding"): "weight_complementary_embedding",
	("accessory", "token"): "weight_accessory_token",
	("accessory", "price_ratio"): "weight_accessory_price_ratio",
	("accessory", "category_pattern"): "weight_accessory_category_pattern",
	("accessory", "copurchase"): "weight_accessory_copurchase",
}

_FLAT_FIELDS = {
	"max_results_per_tab",
	"min_score_threshold",
	"copurchase_lift_threshold",
	"accessory_price_ratio_threshold",
	"embedding_cosine_threshold",
}


def _flatten_payload(payload: dict[str, Any]) -> dict[str, Any]:
	"""Map either flat or nested settings payload to DocType fieldnames."""
	out: dict[str, Any] = {}
	for key, value in payload.items():
		if key in _FLAT_FIELDS:
			out[key] = value
			continue
		if isinstance(value, dict):
			for inner_key, inner_value in value.items():
				fieldname = _NESTED_FIELD_MAP.get((key, inner_key))
				if fieldname:
					out[fieldname] = inner_value
			continue
		# Unknown key — silently skip (forward-compatible)
	return out


def _serialize_dt(dt: Any) -> str | None:
	if isinstance(dt, datetime):
		return dt.strftime("%Y-%m-%d %H:%M:%S")
	if dt is None:
		return None
	return str(dt)
