import frappe


@frappe.whitelist(allow_guest=False)
def get_active_banners():
	"""Return active dashboard banners sorted by sort_order."""
	banners = frappe.get_all(
		"Dashboard Banner",
		filters={"is_active": 1},
		fields=["title", "link_text", "link_href", "sort_order"],
		order_by="sort_order asc",
	)
	return {"success": True, "banners": banners}
