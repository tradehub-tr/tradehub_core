"""
RFQ (Request for Quotation) API endpoints.

Storefront:
  - create_rfq: Buyer creates an RFQ
  - get_my_rfqs: Buyer lists their RFQs
  - get_rfq_detail: Buyer views RFQ detail + quotes
  - get_my_inquiries: Buyer lists their inquiries
  - search_categories: Autocomplete for product name → category
  - add_rfq_details: Add additional details to an existing RFQ
  - close_rfq: Close an RFQ

Admin Panel / Seller:
  - submit_quote: Seller submits a quote for an RFQ
  - get_seller_rfqs: Seller sees RFQs matching their categories
"""

from html import escape as html_escape

import frappe
from frappe import _

from tradehub_core.utils.auth_guards import require_verified_email


@frappe.whitelist()
@require_verified_email
def create_rfq(product_name, description, quantity, unit, category=None, share_business_card=0, ai_enabled=0):
	"""Create a new RFQ for the logged-in buyer."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in to create an RFQ"), frappe.AuthenticationError)

	doc = frappe.new_doc("RFQ")
	doc.buyer = user
	doc.product_name = product_name
	doc.description = description
	doc.quantity = float(quantity)
	doc.unit = unit
	doc.category = category or None
	doc.share_business_card = int(share_business_card)
	doc.ai_enabled = int(ai_enabled)
	doc.status = "Pending"
	doc.insert()
	frappe.db.commit()

	return {"success": True, "rfq_id": doc.name}


@frappe.whitelist()
def get_my_rfqs(status=None, limit_page_length=20, limit_start=0):
	"""Get RFQs created by the logged-in buyer."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	filters = {"buyer": user}
	if status and status != "all":
		filters["status"] = status

	rfqs = frappe.get_all(
		"RFQ",
		filters=filters,
		fields=[
			"name",
			"product_name",
			"status",
			"quantity",
			"unit",
			"quote_count",
			"category",
			"creation",
			"modified",
		],
		order_by="creation desc",
		limit_page_length=min(int(limit_page_length) or 100, 100),
		limit_start=int(limit_start),
	)

	for rfq in rfqs:
		# Get quote status summary + unseen count
		quotes = frappe.get_all(
			"RFQ Quote",
			filters={"rfq": rfq.name},
			fields=["status", "is_seen_by_buyer"],
		)
		if quotes:
			status_counts = {}
			unseen_count = 0
			for q in quotes:
				status_counts[q.status] = status_counts.get(q.status, 0) + 1
				if not q.is_seen_by_buyer:
					unseen_count += 1
			if unseen_count:
				status_counts["Unseen"] = unseen_count
			rfq["quote_summary"] = status_counts
			rfq["quotation_from"] = ""
		else:
			rfq["quote_summary"] = {}
			rfq["quotation_from"] = ""

	total = frappe.db.count("RFQ", filters)

	return {"data": rfqs, "total": total}


@frappe.whitelist()
def get_rfq_detail(rfq_id):
	"""Get RFQ detail including quotes with seller info."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	rfq = frappe.get_doc("RFQ", rfq_id)

	is_admin = (
		user == "Administrator"
		or "System Manager" in frappe.get_roles(user)
		or "Marketplace Admin" in frappe.get_roles(user)
	)
	is_buyer = rfq.buyer == user
	is_seller_with_quote = "Seller" in frappe.get_roles(user) and frappe.db.exists(
		"RFQ Quote", {"rfq": rfq_id, "seller": user}
	)

	if not (is_buyer or is_seller_with_quote or is_admin):
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	quotes = frappe.get_all(
		"RFQ Quote",
		filters={"rfq": rfq_id},
		fields=[
			"name",
			"seller",
			"seller_profile",
			"price_per_unit",
			"total_price",
			"currency",
			"lead_time_days",
			"message",
			"status",
			"creation",
			"listing",
		],
		order_by="creation desc",
	)

	# Batch fetch: users, seller profiles, listings (avoid N+1)
	seller_emails = list({q.seller for q in quotes if q.seller})
	profile_ids = list({q.seller_profile for q in quotes if q.seller_profile})
	listing_ids = list({q.listing for q in quotes if q.get("listing")})

	users_map = {}
	if seller_emails:
		for u in frappe.get_all(
			"User", filters={"name": ["in", seller_emails]}, fields=["name", "full_name"]
		):
			users_map[u.name] = u.full_name or ""

	profiles_map = {}
	if profile_ids:
		for sp in frappe.get_all(
			"Seller Profile",
			filters={"name": ["in", profile_ids]},
			fields=[
				"name",
				"business_name",
				"seller_name",
				"country",
				"seller_type",
				"year_established",
				"employee_count",
				"about_us",
				"website",
			],
		):
			profiles_map[sp.name] = sp

	listings_map = {}
	if listing_ids:
		for ld in frappe.get_all(
			"Listing", filters={"name": ["in", listing_ids]}, fields=["name", "title", "primary_image"]
		):
			listings_map[ld.name] = ld
		# Batch fetch first images for listings without primary_image
		no_img_ids = [lid for lid in listing_ids if not listings_map.get(lid, {}).get("primary_image")]
		if no_img_ids:
			for img in frappe.get_all(
				"Listing Image",
				filters={"parent": ["in", no_img_ids]},
				fields=["parent", "image"],
				order_by="sort_order asc",
			):
				if img.parent not in listings_map:
					listings_map[img.parent] = {"title": "", "primary_image": ""}
				if not listings_map[img.parent].get("primary_image"):
					listings_map[img.parent]["primary_image"] = img.image

	for q in quotes:
		q["seller_name"] = users_map.get(q.seller, "")
		sp = profiles_map.get(q.seller_profile)
		q["seller_company"] = (sp.business_name or sp.seller_name or "") if sp else ""
		q["seller_country"] = (sp.country or "") if sp else ""
		q["seller_type"] = (sp.seller_type or "") if sp else ""
		q["seller_year_established"] = (sp.year_established or "") if sp else ""
		q["seller_employee_count"] = (sp.employee_count or "") if sp else ""
		q["seller_about"] = (sp.about_us or "") if sp else ""
		q["seller_website"] = (sp.website or "") if sp else ""
		ld = listings_map.get(q.get("listing"))
		q["listing_title"] = (ld.get("title") or "") if ld else ""
		q["listing_image"] = (ld.get("primary_image") or "") if ld else ""

	# Mark unseen quotes as seen when buyer views them
	if rfq.buyer == user:
		unseen = frappe.get_all(
			"RFQ Quote",
			filters={"rfq": rfq_id, "is_seen_by_buyer": 0},
			fields=["name"],
		)
		for uq in unseen:
			frappe.db.set_value("RFQ Quote", uq.name, "is_seen_by_buyer", 1)
		if unseen:
			frappe.db.commit()

	category_name = ""
	if rfq.category:
		category_name = frappe.db.get_value("Product Category", rfq.category, "category_name") or rfq.category

	return {
		"rfq": {
			"name": rfq.name,
			"buyer": rfq.buyer,
			"product_name": rfq.product_name,
			"description": rfq.description,
			"quantity": rfq.quantity,
			"unit": rfq.unit,
			"status": rfq.status,
			"category": rfq.category,
			"category_name": category_name,
			"additional_details": rfq.additional_details or "",
			"quote_count": rfq.quote_count,
			"share_business_card": rfq.share_business_card,
			"creation": str(rfq.creation),
			"modified": str(rfq.modified),
		},
		"quotes": quotes,
	}


@frappe.whitelist()
def get_my_inquiries(filter_type="all", limit_page_length=20, limit_start=0):
	"""Get inquiries sent by the logged-in buyer."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	filters = {"sender_email": user}

	if filter_type == "trash":
		filters["is_trashed"] = 1
	elif filter_type != "all":
		filters["is_trashed"] = 0
		filters["folder"] = filter_type

	if "is_trashed" not in filters:
		filters["is_trashed"] = 0

	inquiries = frappe.get_all(
		"Seller Inquiry",
		filters=filters,
		fields=[
			"name",
			"message",
			"status",
			"seller",
			"seller_code",
			"sender_name",
			"sender_email",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=min(int(limit_page_length) or 100, 100),
		limit_start=int(limit_start),
	)

	for inq in inquiries:
		if inq.seller:
			seller_data = frappe.db.get_value(
				"Admin Seller Profile",
				inq.seller,
				["seller_name", "company_name"],
				as_dict=True,
			)
			if seller_data:
				inq["seller_name"] = seller_data.seller_name or ""
				inq["seller_company"] = seller_data.company_name or ""
			else:
				inq["seller_name"] = ""
				inq["seller_company"] = ""
		else:
			inq["seller_name"] = ""
			inq["seller_company"] = ""

	total = frappe.db.count("Seller Inquiry", filters)
	return {"data": inquiries, "total": total}


@frappe.whitelist()
@require_verified_email
def submit_quote(
	rfq_id, price_per_unit=0, total_price=0, currency="TRY", lead_time_days=0, message="", listing_id=None
):
	"""Seller submits a quote for an RFQ."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	if "Seller" not in frappe.get_roles(user):
		frappe.throw(_("Only sellers can submit quotes"), frappe.PermissionError)

	if not frappe.db.exists("RFQ", rfq_id):
		frappe.throw(_("RFQ not found"), frappe.DoesNotExistError)

	# Prevent duplicate quotes from same seller
	existing = frappe.db.exists("RFQ Quote", {"rfq": rfq_id, "seller": user})
	if existing:
		frappe.throw(_("You have already submitted a quote for this RFQ"))

	doc = frappe.new_doc("RFQ Quote")
	doc.rfq = rfq_id
	doc.seller = user
	doc.price_per_unit = float(price_per_unit) if price_per_unit else 0
	doc.total_price = float(total_price) if total_price else 0
	doc.currency = currency
	doc.lead_time_days = int(lead_time_days) if lead_time_days else 0
	doc.message = message
	doc.status = "Submitted"
	if listing_id and frappe.db.exists("Listing", listing_id):
		doc.listing = listing_id
		listing_data = frappe.db.get_value("Listing", listing_id, ["title", "primary_image"], as_dict=True)
		if listing_data:
			doc.listing_title = listing_data.title or ""
			doc.listing_image = listing_data.primary_image or ""
			# Fallback: get first image from child table if primary_image is empty
			if not doc.listing_image:
				first_img = frappe.db.get_value(
					"Listing Image", {"parent": listing_id}, "image", order_by="sort_order asc"
				)
				doc.listing_image = first_img or ""
	doc.insert()
	frappe.db.commit()

	return {"success": True, "quote_id": doc.name}


@frappe.whitelist()
def get_seller_rfqs(status=None, limit_page_length=20, limit_start=0):
	"""Get Approved RFQs matching the seller's categories."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	if "Seller" not in frappe.get_roles(user):
		frappe.throw(_("Only sellers can view RFQs"), frappe.PermissionError)

	# User → Admin Seller Profile
	seller_profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not seller_profile:
		seller_profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")

	cat_names = set()
	if seller_profile:
		# 1. Seller Category'den (onaylı kategoriler)
		seller_categories = frappe.get_all(
			"Seller Category",
			filters={"seller": seller_profile, "status": "Active", "is_enabled": 1},
			fields=["category"],
		)
		for sc in seller_categories:
			if sc.category:
				cat_names.add(sc.category)

		# 2. Listing'lerden (platform kategorisi)
		seller_code = frappe.db.get_value("Admin Seller Profile", seller_profile, "seller_code")
		if seller_code:
			listings = frappe.get_all(
				"Listing",
				filters={"seller_profile": seller_code, "status": ["in", ["Aktif", "Active"]]},
				fields=["product_category"],
			)
			for lst in listings:
				if lst.product_category:
					cat_names.add(lst.product_category)

	cat_names = list(cat_names)

	# Exclude RFQs where this seller already submitted a quote
	quoted_rfqs = frappe.get_all(
		"RFQ Quote",
		filters={"seller": user},
		fields=["rfq"],
		pluck="rfq",
	)

	# Only show Approved RFQs
	filters = {"status": "Approved"}

	if quoted_rfqs:
		filters["name"] = ["not in", quoted_rfqs]

	if cat_names:
		# Show RFQs matching seller's categories OR RFQs without category
		filters["category"] = ["in", cat_names + [None, ""]]
	else:
		filters["category"] = ["in", [None, ""]]

	rfqs = frappe.get_all(
		"RFQ",
		filters=filters,
		fields=[
			"name",
			"product_name",
			"description",
			"status",
			"quantity",
			"unit",
			"category",
			"quote_count",
			"buyer",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=min(int(limit_page_length) or 100, 100),
		limit_start=int(limit_start),
	)

	for rfq in rfqs:
		rfq["buyer_name"] = frappe.db.get_value("User", rfq.buyer, "full_name") or ""
		if rfq.get("category"):
			rfq["category"] = (
				frappe.db.get_value("Product Category", rfq["category"], "category_name") or rfq["category"]
			)
		# Check if current seller already submitted a quote
		rfq["my_quote"] = frappe.db.exists("RFQ Quote", {"rfq": rfq.name, "seller": user}) or ""

	total = frappe.db.count("RFQ", filters)
	return {"data": rfqs, "total": total}


@frappe.whitelist(allow_guest=True)
def search_categories(query=""):
	"""Search product categories for autocomplete."""
	if not query or len(query) < 2:
		return []

	categories = frappe.get_all(
		"Product Category",
		filters={"category_name": ["like", f"%{query}%"]},
		fields=["name", "category_name", "parent_product_category"],
		order_by="category_name asc",
		limit_page_length=10,
	)

	results = []
	for cat in categories:
		# Build breadcrumb path
		path_parts = [cat.category_name]
		parent = cat.parent_product_category
		depth = 0
		while parent and depth < 5:
			parent_name = frappe.db.get_value(
				"Product Category", parent, ["category_name", "parent_product_category"], as_dict=True
			)
			if parent_name:
				path_parts.insert(0, parent_name.category_name)
				parent = parent_name.parent_product_category
			else:
				break
			depth += 1

		results.append(
			{
				"name": cat.name,
				"category_name": cat.category_name,
				"path": " >> ".join(path_parts),
			}
		)

	return results


@frappe.whitelist()
@require_verified_email
def add_rfq_details(rfq_id, additional_details):
	"""Add additional details to an existing RFQ (one-time)."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	rfq = frappe.get_doc("RFQ", rfq_id)
	if rfq.buyer != user:
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	if rfq.additional_details:
		frappe.throw(_("Additional details can only be added once"))

	rfq.additional_details = html_escape(additional_details)[:100]
	rfq.save()
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
@require_verified_email
def close_rfq(rfq_id):
	"""Close an RFQ."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	rfq = frappe.get_doc("RFQ", rfq_id)
	if rfq.buyer != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	if rfq.status in ("Closed", "Completed"):
		frappe.throw(_("This RFQ is already {0}").format(rfq.status))

	rfq.status = "Closed"
	rfq.save()
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
@require_verified_email
def accept_quote(quote_id):
	"""Buyer accepts a quote — sets quote to Accepted, RFQ to Completed."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	quote = frappe.get_doc("RFQ Quote", quote_id)
	# Lock RFQ row to prevent concurrent accept
	rfq = frappe.get_doc("RFQ", quote.rfq, for_update=True)

	if rfq.buyer != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	if rfq.status not in ("Approved",):
		frappe.throw(_("Quotes can only be accepted on Approved RFQs"))

	if quote.status != "Submitted":
		frappe.throw(_("This quote has already been processed"))

	quote.status = "Accepted"
	quote.save(ignore_permissions=True)

	# Reject all other quotes for this RFQ
	other_quotes = frappe.get_all(
		"RFQ Quote", filters={"rfq": rfq.name, "name": ["!=", quote_id], "status": "Submitted"}
	)
	for oq in other_quotes:
		frappe.db.set_value("RFQ Quote", oq.name, "status", "Rejected")

	# Set RFQ to Completed
	rfq.status = "Completed"
	rfq.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def reject_quote(quote_id):
	"""Buyer rejects a quote."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	quote = frappe.get_doc("RFQ Quote", quote_id)
	rfq = frappe.get_doc("RFQ", quote.rfq)

	if rfq.buyer != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	quote.status = "Rejected"
	quote.save(ignore_permissions=True)
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def trash_inquiry(inquiry_id):
	"""Move a buyer's inquiry to trash (or restore it)."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	inq = frappe.get_doc("Seller Inquiry", inquiry_id)
	if inq.sender_email != user:
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	inq.is_trashed = 1
	inq.save()
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist(allow_guest=True)
def get_uom_list():
	"""Get list of UOM options for RFQ form."""
	uoms = frappe.get_all("UOM", fields=["name"], order_by="name asc", limit_page_length=0)
	return [u.name for u in uoms]


@frappe.whitelist()
def get_my_listings():
	"""Get listings owned by the logged-in seller (for quote product selection)."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	if "Seller" not in frappe.get_roles(user):
		frappe.throw(_("Only sellers can view listings"), frappe.PermissionError)

	# Find seller profile
	seller_profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not seller_profile:
		seller_profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")

	if not seller_profile:
		return []

	listings = frappe.get_all(
		"Listing",
		filters={"seller_profile": seller_profile, "status": "Active"},
		fields=["name", "title", "primary_image"],
		order_by="title asc",
		limit_page_length=50,
	)

	# Fallback: get first child image if primary_image is empty
	for l in listings:
		if not l.get("primary_image"):
			first_img = frappe.db.get_value(
				"Listing Image", {"parent": l.name}, "image", order_by="sort_order asc"
			)
			l["primary_image"] = first_img or ""

	return listings


ALLOWED_FILE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".pdf", ".doc", ".docx", ".xls", ".xlsx")


@frappe.whitelist()
def add_rfq_attachment(rfq_id, file_url, file_name):
	"""Add uploaded file to RFQ attachments child table."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	# Server-side file extension validation
	ext = ("." + file_name.rsplit(".", 1)[-1].lower()) if "." in file_name else ""
	if ext not in ALLOWED_FILE_EXTENSIONS:
		frappe.throw(_("File type not allowed. Allowed: JPG, PNG, GIF, PDF, DOC, XLS"))

	rfq = frappe.get_doc("RFQ", rfq_id)
	if rfq.buyer != user and "System Manager" not in frappe.get_roles(user):
		frappe.throw(_("Permission denied"), frappe.PermissionError)

	rfq.append(
		"attachments",
		{
			"file": file_url,
			"file_name": file_name,
		},
	)
	rfq.save()
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def get_my_quotes(limit_page_length=20, limit_start=0):
	"""Get quotes submitted by the logged-in seller."""
	user = frappe.session.user
	if user == "Guest":
		frappe.throw(_("Please log in"), frappe.AuthenticationError)

	if "Seller" not in frappe.get_roles(user):
		frappe.throw(_("Only sellers can view quotes"), frappe.PermissionError)

	quotes = frappe.get_all(
		"RFQ Quote",
		filters={"seller": user},
		fields=[
			"name",
			"rfq",
			"price_per_unit",
			"total_price",
			"currency",
			"lead_time_days",
			"message",
			"status",
			"creation",
		],
		order_by="creation desc",
		limit_page_length=min(int(limit_page_length) or 100, 100),
		limit_start=int(limit_start),
	)

	for q in quotes:
		rfq_data = frappe.db.get_value(
			"RFQ",
			q.rfq,
			["product_name", "quantity", "unit"],
			as_dict=True,
		)
		if rfq_data:
			q["rfq_product_name"] = rfq_data.product_name
			q["rfq_quantity"] = rfq_data.quantity
			q["rfq_unit"] = rfq_data.unit
		else:
			q["rfq_product_name"] = ""
			q["rfq_quantity"] = 0
			q["rfq_unit"] = ""

	total = frappe.db.count("RFQ Quote", {"seller": user})
	return {"data": quotes, "total": total}
