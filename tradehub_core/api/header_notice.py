import frappe
from frappe.utils import get_datetime, now_datetime

CACHE_KEY = "header_notices_active"
CACHE_TTL = 60  # seconds


@frappe.whitelist(allow_guest=True)
def get_active_notices() -> dict:
	"""Storefront tarafından çağrılır; login zorunlu değil."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached

	settings = frappe.get_cached_doc("Header Notice Settings")
	display_mode = settings.display_mode or "marquee"

	now = now_datetime()
	rows = frappe.get_all(
		"Header Notice",
		filters={"is_active": 1},
		fields=[
			"name",
			"message_tr",
			"message_en",
			"link_text_tr",
			"link_text_en",
			"link_href",
			"icon",
			"background_color",
			"sort_order",
			"start_at",
			"end_at",
		],
		order_by="sort_order asc, creation desc",
	)

	def in_window(n: dict) -> bool:
		if n.get("start_at") and get_datetime(n["start_at"]) > now:
			return False
		if n.get("end_at") and get_datetime(n["end_at"]) < now:
			return False
		return True

	active = [
		{
			"name": n["name"],
			"message_tr": n["message_tr"],
			"message_en": n.get("message_en") or "",
			"link_text_tr": n.get("link_text_tr") or "",
			"link_text_en": n.get("link_text_en") or "",
			"link_href": n.get("link_href") or "",
			"icon": n.get("icon") or "none",
			"background_color": n.get("background_color") or "#1a1a1a",
			"sort_order": n["sort_order"],
		}
		for n in rows
		if in_window(n)
	]

	# Auto-downgrade: if only 1 notice, single mode regardless of setting
	effective_mode = "single" if len(active) <= 1 else display_mode

	payload = {
		"success": True,
		"display_mode": effective_mode,
		"notices": active,
	}
	frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
	return payload


def invalidate_cache(doc, method=None) -> None:
	"""hooks.py doc_events tarafından çağrılır."""
	frappe.cache.delete_value(CACHE_KEY)
