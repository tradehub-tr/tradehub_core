"""ECA validators — role-aware field/action whitelist'leri."""

LISTING_SELLER_VISIBLE_FIELDS = frozenset(
	{
		"title",
		"sku",
		"base_price",
		"selling_price",
		"stock_qty",
		"status",
		"primary_image",
		"product_category",
		"brand",
		"short_description",
		"description",
		"tags",
		"weight",
		"min_order_qty",
		"barcode",
		"discount_percentage",
		"creation",
		"modified",
	}
)

LISTING_SELLER_WRITABLE_FIELDS = frozenset(
	{
		"title",
		"sku",
		"base_price",
		"selling_price",
		"stock_qty",
		"primary_image",
		"product_category",
		"brand",
		"short_description",
		"description",
		"tags",
		"weight",
		"min_order_qty",
		"barcode",
		"discount_percentage",
	}
)

SELLER_ALLOWED_ACTIONS = frozenset({"field_update", "email", "webhook", "reject_row"})
ADMIN_ALLOWED_ACTIONS = frozenset(
	{
		"field_update",
		"email",
		"webhook",
		"reject_row",
		"create_document",
		"custom_script",
	}
)


def is_action_allowed(action_type: str, owner_role: str) -> bool:
	if owner_role in ("System Manager", "Marketplace Admin"):
		return action_type in ADMIN_ALLOWED_ACTIONS
	if owner_role == "Seller":
		return action_type in SELLER_ALLOWED_ACTIONS
	return False


def is_field_visible(fieldname: str, owner_role: str, doctype: str = "Listing") -> bool:
	if owner_role in ("System Manager", "Marketplace Admin"):
		return True
	if doctype == "Listing":
		return fieldname in LISTING_SELLER_VISIBLE_FIELDS
	return False


def is_field_writable(fieldname: str, owner_role: str, doctype: str = "Listing") -> bool:
	if owner_role in ("System Manager", "Marketplace Admin"):
		return True
	if doctype == "Listing":
		return fieldname in LISTING_SELLER_WRITABLE_FIELDS
	return False


def filter_doc_for_seller(doc_dict: dict, doctype: str = "Listing") -> dict:
	if doctype == "Listing":
		return {k: v for k, v in doc_dict.items() if k in LISTING_SELLER_VISIBLE_FIELDS}
	return {}
