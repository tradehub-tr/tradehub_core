import frappe
from frappe.utils import get_datetime, now_datetime

CACHE_KEY = "hero_slides_active"
CACHE_TTL = 60  # seconds


def _background_css(slide: dict) -> str:
	"""Slide arka planını hazır CSS `background` değerine çevirir."""
	bg_type = slide.get("background_type") or "gradient"
	if bg_type == "image" and slide.get("background_image"):
		return f"url('{slide['background_image']}') center/cover no-repeat"
	if bg_type == "color":
		return slide.get("background_color") or "#1f5fae"
	# gradient (varsayılan)
	c1 = slide.get("background_color") or "#1f5fae"
	c2 = slide.get("background_color_2") or "#0c2e61"
	angle = slide.get("gradient_angle") or 120
	return f"linear-gradient({angle}deg, {c1} 0%, {c2} 100%)"


@frappe.whitelist(allow_guest=True)
def get_active_slides() -> dict:
	"""Storefront hero slider tarafından çağrılır; login zorunlu değil."""
	cached = frappe.cache.get_value(CACHE_KEY)
	if cached is not None:
		return cached

	now = now_datetime()
	rows = frappe.get_all(
		"Hero Slide",
		filters={"is_active": 1},
		fields=[
			"name",
			"label_tr",
			"label_en",
			"title_tr",
			"title_en",
			"description_tr",
			"description_en",
			"button_text_tr",
			"button_text_en",
			"button_href",
			"background_type",
			"background_image",
			"background_color",
			"background_color_2",
			"gradient_angle",
			"text_color",
			"content_align",
			"overlay",
			"sort_order",
			"start_at",
			"end_at",
		],
		order_by="sort_order asc, creation desc",
	)

	def in_window(s: dict) -> bool:
		if s.get("start_at") and get_datetime(s["start_at"]) > now:
			return False
		if s.get("end_at") and get_datetime(s["end_at"]) < now:
			return False
		return True

	slides = [
		{
			"name": s["name"],
			"label_tr": s.get("label_tr") or "",
			"label_en": s.get("label_en") or "",
			"title_tr": s.get("title_tr") or "",
			"title_en": s.get("title_en") or "",
			"description_tr": s.get("description_tr") or "",
			"description_en": s.get("description_en") or "",
			"button_text_tr": s.get("button_text_tr") or "",
			"button_text_en": s.get("button_text_en") or "",
			"button_href": s.get("button_href") or "",
			"background_type": s.get("background_type") or "gradient",
			"background_css": _background_css(s),
			"text_color": s.get("text_color") or "#ffffff",
			"content_align": s.get("content_align") or "center",
			"overlay": int(s.get("overlay") or 0),
			"sort_order": s.get("sort_order") or 0,
		}
		for s in rows
		if in_window(s)
	]

	payload = {"success": True, "slides": slides}
	frappe.cache.set_value(CACHE_KEY, payload, expires_in_sec=CACHE_TTL)
	return payload


def invalidate_cache(doc, method=None) -> None:
	"""hooks.py doc_events tarafından çağrılır."""
	frappe.cache.delete_value(CACHE_KEY)
