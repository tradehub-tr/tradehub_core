import frappe
from frappe.utils import get_datetime, now_datetime

CACHE_KEY = "header_notices_active"
CACHE_TTL = 60  # seconds


@frappe.whitelist(allow_guest=True)
def get_active_notices() -> dict:
	"""Storefront tarafından çağrılır; login zorunlu değil."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return {"success": True, "notices": cached}

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
			"sort_order",
			"start_at",
			"end_at",
		],
		order_by="sort_order asc, creation desc",
	)

	def in_window(n: dict) -> bool:
		# frappe.get_all datetime'ı string döndürebilir → get_datetime ile parse
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
			"sort_order": n["sort_order"],
		}
		for n in rows
		if in_window(n)
	]

	frappe.cache.set_value(CACHE_KEY, active, expires_in_sec=CACHE_TTL)
	return {"success": True, "notices": active}


def invalidate_cache(doc, method=None) -> None:
	"""hooks.py doc_events tarafından çağrılır."""
	frappe.cache.delete_value(CACHE_KEY)
