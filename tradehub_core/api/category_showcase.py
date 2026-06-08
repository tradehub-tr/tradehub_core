import frappe
from frappe.utils import get_datetime, now_datetime

CACHE_KEY = "category_showcase_active"
CACHE_TTL = 60  # seconds


@frappe.whitelist(allow_guest=True)
def get_active_tiles() -> dict:
	"""Storefront tarafından çağrılır; login zorunlu değil."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached

	settings = frappe.get_cached_doc("Category Showcase Settings")
	enabled = bool(settings.is_enabled)
	section_title = {
		"tr": settings.section_title_tr or "",
		"en": settings.section_title_en or "",
	}
	columns = int(settings.columns or 4)

	if not enabled:
		payload = {
			"success": True,
			"enabled": False,
			"section_title": section_title,
			"columns": columns,
			"tiles": [],
		}
		frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
		return payload

	now = now_datetime()
	rows = frappe.get_all(
		"Category Showcase Tile",
		filters={"is_active": 1},
		fields=[
			"name",
			"tile_type",
			"col_span",
			"row_span",
			"sort_order",
			"label_tr",
			"label_en",
			"image",
			"link_href",
			"hover_text_tr",
			"hover_text_en",
			"promo_badge_tr",
			"promo_badge_en",
			"promo_title_tr",
			"promo_title_en",
			"background_color",
			"cta_text_tr",
			"cta_text_en",
			"cta_href",
			"start_at",
			"end_at",
		],
		order_by="sort_order asc, creation desc",
	)

	def in_window(r: dict) -> bool:
		if r.get("start_at") and get_datetime(r["start_at"]) > now:
			return False
		if r.get("end_at") and get_datetime(r["end_at"]) < now:
			return False
		return True

	tiles = [
		{
			"name": r["name"],
			"tile_type": r.get("tile_type") or "category",
			"col_span": int(r.get("col_span") or 1),
			"row_span": int(r.get("row_span") or 1),
			"sort_order": r.get("sort_order") or 0,
			"label_tr": r.get("label_tr") or "",
			"label_en": r.get("label_en") or "",
			"image": r.get("image") or "",
			"link_href": r.get("link_href") or "",
			"hover_text_tr": r.get("hover_text_tr") or "",
			"hover_text_en": r.get("hover_text_en") or "",
			"promo_badge_tr": r.get("promo_badge_tr") or "",
			"promo_badge_en": r.get("promo_badge_en") or "",
			"promo_title_tr": r.get("promo_title_tr") or "",
			"promo_title_en": r.get("promo_title_en") or "",
			"background_color": r.get("background_color") or "#cc9900",
			"cta_text_tr": r.get("cta_text_tr") or "",
			"cta_text_en": r.get("cta_text_en") or "",
			"cta_href": r.get("cta_href") or "",
		}
		for r in rows
		if in_window(r)
	]

	payload = {
		"success": True,
		"enabled": True,
		"section_title": section_title,
		"columns": columns,
		"tiles": tiles,
	}
	frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
	return payload


def invalidate_cache(doc, method=None) -> None:
	"""hooks.py doc_events tarafından çağrılır."""
	frappe.cache.delete_value(CACHE_KEY)
