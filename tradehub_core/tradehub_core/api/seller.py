import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_sellers(search=None, page=1, page_size=20):
	filters = {"status": "Active"}
	if search:
		filters["seller_name"] = ["like", "%" + search + "%"]
	sellers = frappe.get_all(
		"Seller Profile",
		filters=filters,
		fields=[
			"name",
			"seller_code",
			"seller_name",
			"city",
			"country",
			"logo",
			"banner_image",
			"description",
			"is_featured",
			"average_rating",
			"total_reviews",
			"joined_at",
			"status",
			"verification_status",
			"is_top_seller",
			"is_premium_seller",
			"email",
			"website",
		],
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="seller_name asc",
	)
	for s in sellers:
		s["slug"] = s.get("seller_code", "")
		s["rating"] = s.get("average_rating", 0)
		s["review_count"] = s.get("total_reviews", 0)
		s["member_since"] = s.get("joined_at", "")
		s["cover_image"] = s.get("banner_image", "")
		s["short_description"] = s.get("description", "")
		s["verified"] = s.get("verification_status") in ["Verified", "Onaylı"]
		try:
			images = frappe.get_all("Item", filters={"seller_code": s.seller_code}, fields=["image"], limit=5)
			s["product_images"] = [i.image for i in images if i.image]
		except Exception:
			s["product_images"] = []
	total = frappe.db.count("Seller Profile", filters=filters)
	return {"sellers": sellers, "total": total, "page": int(page), "page_size": int(page_size)}


@frappe.whitelist(allow_guest=True)
def get_seller(slug):
	seller = frappe.db.get_value(
		"Seller Profile",
		{"seller_code": slug, "status": "Active"},
		[
			"name",
			"seller_code",
			"seller_name",
			"city",
			"country",
			"logo",
			"banner_image",
			"description",
			"average_rating",
			"total_reviews",
			"joined_at",
			"email",
			"phone",
			"website",
			"status",
			"verification_status",
			"is_featured",
			"is_top_seller",
		],
		as_dict=True,
	)
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	seller["slug"] = seller.get("seller_code", "")
	seller["rating"] = seller.get("average_rating", 0)
	seller["review_count"] = seller.get("total_reviews", 0)
	seller["member_since"] = seller.get("joined_at", "")
	seller["cover_image"] = seller.get("banner_image", "")
	seller["short_description"] = seller.get("description", "")
	seller["verified"] = seller.get("verification_status") in ["Verified", "Onaylı"]
	return seller


@frappe.whitelist(allow_guest=True)
def get_reviews(seller_code, page=1, page_size=10):
	seller = frappe.db.get_value("Seller Profile", {"seller_code": seller_code, "status": "Active"}, "name")
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	filters = {"seller": seller}
	reviews = frappe.get_all(
		"Seller Review",
		filters=filters,
		fields=[
			"name",
			"reviewer_name",
			"rating",
			"comment",
			"creation",
			"product_name",
			"verified_purchase",
		],
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="creation desc",
	)
	total = frappe.db.count("Seller Review", filters=filters)
	return {"reviews": reviews, "total": total}


@frappe.whitelist(allow_guest=True)
def get_storefront_layout(seller_code):
	seller = frappe.db.get_value("Seller Profile", {"seller_code": seller_code, "status": "Active"}, "name")
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)

	layout = frappe.db.get_value(
		"Storefront Layout",
		{"seller_profile": seller, "is_published": 1},
		["sections", "theme_config"],
		as_dict=True,
	)
	if not layout:
		from tradehub_core.tradehub_core.doctype.storefront_layout.storefront_layout import (
			DEFAULT_SECTIONS,
			DEFAULT_THEME,
		)

		return {"sections": DEFAULT_SECTIONS, "theme": DEFAULT_THEME}

	import json

	sections = layout.get("sections") or "[]"
	theme = layout.get("theme_config") or "{}"
	return {
		"sections": json.loads(sections) if isinstance(sections, str) else sections,
		"theme": json.loads(theme) if isinstance(theme, str) else theme,
	}


@frappe.whitelist()
def save_storefront_layout(seller_code, sections, theme_config=None):
	import json

	seller = frappe.db.get_value(
		"Seller Profile", {"seller_code": seller_code, "status": "Active"}, ["name", "user"], as_dict=True
	)
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)

	if frappe.session.user != seller.user and "Marketplace Admin" not in frappe.get_roles():
		frappe.throw(_("Bu islem icin yetkiniz yok"), frappe.PermissionError)

	existing = frappe.db.get_value("Storefront Layout", {"seller_profile": seller.name}, "name")

	if existing:
		doc = frappe.get_doc("Storefront Layout", existing)
	else:
		doc = frappe.new_doc("Storefront Layout")
		doc.seller_profile = seller.name

	doc.sections = sections if isinstance(sections, str) else json.dumps(sections)
	if theme_config:
		doc.theme_config = theme_config if isinstance(theme_config, str) else json.dumps(theme_config)

	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name}


@frappe.whitelist()
def publish_storefront_layout(seller_code, publish=1):
	seller = frappe.db.get_value(
		"Seller Profile", {"seller_code": seller_code, "status": "Active"}, ["name", "user"], as_dict=True
	)
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)

	if frappe.session.user != seller.user and "Marketplace Admin" not in frappe.get_roles():
		frappe.throw(_("Bu islem icin yetkiniz yok"), frappe.PermissionError)

	existing = frappe.db.get_value("Storefront Layout", {"seller_profile": seller.name}, "name")
	if not existing:
		frappe.throw(_("Henuz bir sayfa duzeni olusturulmamis"), frappe.DoesNotExistError)

	frappe.db.set_value("Storefront Layout", existing, "is_published", int(publish))
	frappe.db.commit()
	return {"success": True}


@frappe.whitelist(allow_guest=True)
def send_inquiry(seller_code, message, share_business_card=0):
	seller = frappe.db.get_value(
		"Seller Profile",
		{"seller_code": seller_code, "status": "Active"},
		["name", "seller_code"],
		as_dict=True,
	)
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	sender_name, sender_email = "", ""
	if frappe.session.user and frappe.session.user != "Guest":
		user = frappe.db.get_value("User", frappe.session.user, ["full_name", "email"], as_dict=True)
		if user:
			sender_name = user.full_name or ""
			sender_email = user.email or ""
	doc = frappe.new_doc("Seller Inquiry")
	doc.seller = seller.name
	doc.seller_code = seller.seller_code
	doc.message = message.strip()
	doc.sender_name = sender_name
	doc.sender_email = sender_email
	doc.share_business_card = int(share_business_card)
	doc.status = "Yeni"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "inquiry_id": doc.name}
