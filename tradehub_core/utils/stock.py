import json as _json

import frappe
from frappe import _
from frappe.utils import add_to_date, flt, now_datetime

# Aynı listing için aynı türde stok bildirimi en az bu kadar saat arayla gönderilir.
STOCK_ALERT_COOLDOWN_HOURS = 24


def _find_variant_item_row(listing_name, variation_label):
	"""Parse a variant_label like 'Renk: Siyah | Malzeme: Pamuk | Beden: S'
	and find the matching Listing Variant Item row.
	Returns the child row name or None.
	"""
	if not variation_label:
		return None

	# Parse "Key: Value | Key: Value" format
	parsed = {}
	for part in variation_label.split("|"):
		part = part.strip()
		if ":" in part:
			key, val = part.split(":", 1)
			parsed[key.strip()] = val.strip()

	if not parsed:
		return None

	rows = frappe.get_all(
		"Listing Variant Item",
		filters={"parent": listing_name, "parenttype": "Listing"},
		fields=[
			"name",
			"attribute_type",
			"attribute_value",
			"attribute_type_2",
			"attribute_value_2",
			"axis_values_json",
		],
	)

	for row in rows:
		# Check axis1 match
		if row.attribute_type and parsed.get(row.attribute_type) != row.attribute_value:
			continue
		# Check axis2 match
		if row.attribute_type_2 and parsed.get(row.attribute_type_2) != row.attribute_value_2:
			continue
		# Check extra axes match
		if row.axis_values_json:
			try:
				extra = _json.loads(row.axis_values_json)
				skip = False
				for ax_name, ax_val in extra.items():
					if ax_name == row.attribute_type or ax_name == row.attribute_type_2:
						continue
					if parsed.get(ax_name) != ax_val:
						skip = True
						break
				if skip:
					continue
			except Exception:
				pass
		return row.name

	return None


def _update_variant_stock(listing_name, variation_label, qty_delta):
	"""Update variant_stock on the matching Listing Variant Item row.
	qty_delta is negative for deductions, positive for releases.
	"""
	row_name = _find_variant_item_row(listing_name, variation_label)
	if not row_name:
		return
	current = flt(frappe.db.get_value("Listing Variant Item", row_name, "variant_stock"))
	new_stock = max(0, current + qty_delta)
	frappe.db.set_value("Listing Variant Item", row_name, "variant_stock", new_stock)


def reserve_stock_for_order(order_name):
	"""Sipariş oluşturulduğunda listing stoklarını rezerve et.
	reserved_qty artırılır, available_qty otomatik hesaplanır.
	Varyant seviyesinde de variant_stock düşürülür (overselling önlenir).
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation"],
	)
	for item in items:
		if not item.listing:
			continue
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory", "reserved_qty"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)
		new_reserved = flt(listing.reserved_qty) + qty
		frappe.db.set_value("Listing", item.listing, "reserved_qty", new_reserved)
		# Per-variant stock reservation
		_update_variant_stock(item.listing, item.variation, -qty)
		_recalculate_available(item.listing)


def release_stock_for_order(order_name):
	"""Sipariş iptal edildiğinde rezervasyonu kaldır.
	reserved_qty azaltılır, varyant seviyesinde variant_stock geri eklenir.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation"],
	)
	for item in items:
		if not item.listing:
			continue
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory", "reserved_qty"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)
		new_reserved = max(0, flt(listing.reserved_qty) - qty)
		frappe.db.set_value("Listing", item.listing, "reserved_qty", new_reserved)
		# Per-variant stock release (give back)
		_update_variant_stock(item.listing, item.variation, +qty)
		_recalculate_available(item.listing)


def deduct_stock_for_order(order_name):
	"""Sipariş tamamlandığında gerçek stoktan düş.
	stock_qty azaltılır, reserved_qty azaltılır.
	Varyant seviyesinde de variant_stock güncellenir.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation"],
	)
	for item in items:
		if not item.listing:
			continue
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory", "stock_qty", "reserved_qty"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)
		new_stock = max(0, flt(listing.stock_qty) - qty)
		new_reserved = max(0, flt(listing.reserved_qty) - qty)
		frappe.db.set_value(
			"Listing",
			item.listing,
			{
				"stock_qty": new_stock,
				"reserved_qty": new_reserved,
			},
		)
		# Per-variant stock deduction
		_update_variant_stock(item.listing, item.variation, -qty)
		_recalculate_available(item.listing)


def _recalculate_available(listing_name):
	"""available_qty = stock_qty - reserved_qty, minimum 0.
	Stok değişikliğinde gerekirse satıcıya alert gönderir.
	"""
	vals = frappe.db.get_value(
		"Listing",
		listing_name,
		[
			"stock_qty",
			"reserved_qty",
			"available_qty",
			"track_inventory",
			"status",
			"seller_profile",
			"title",
			"listing_code",
			"low_stock_threshold",
		],
		as_dict=True,
	)
	if not vals:
		return

	old_available = flt(vals.available_qty)
	new_available = max(0, flt(vals.stock_qty) - flt(vals.reserved_qty))
	frappe.db.set_value("Listing", listing_name, "available_qty", new_available)

	# Stok alert kontrolü
	if vals.track_inventory and vals.status == "Active" and old_available != new_available:
		_send_stock_alert_if_needed(listing_name, vals, old_available, new_available)


def _send_stock_alert_if_needed(listing_name, vals, old_available, new_available):
	"""Stok tükendi veya düşük stok uyarısı gönder.
	Aynı listing + aynı alert başlığı için 24 saat cooldown uygular.
	"""
	from tradehub_core.utils.notify import notify

	seller_user = (
		frappe.db.get_value("Admin Seller Profile", vals.seller_profile, "user")
		if vals.seller_profile
		else None
	)
	if not seller_user:
		return

	title_text = vals.title or vals.listing_code or listing_name
	alert_title = None
	alert_message = None

	if new_available <= 0 and old_available > 0:
		alert_title = _("Stok Tükendi")
		alert_message = _("{0} ürününüzün stoğu tükendi.").format(title_text)
	elif (
		flt(vals.low_stock_threshold) > 0
		and new_available <= flt(vals.low_stock_threshold)
		and old_available > flt(vals.low_stock_threshold)
	):
		alert_title = _("Düşük Stok Uyarısı")
		alert_message = _("{0} ürününüzün stoğu {1} adede düştü.").format(title_text, int(new_available))

	if not alert_title:
		return

	# Persistent duplicate guard: aynı listing + aynı başlık, son 24 saat içinde gönderilmiş mi?
	cutoff = add_to_date(now_datetime(), hours=-STOCK_ALERT_COOLDOWN_HOURS)
	already_sent = frappe.db.exists(
		"Platform Notification",
		{
			"recipient_user": seller_user,
			"reference_doctype": "Listing",
			"reference_name": listing_name,
			"title": alert_title,
			"creation": [">", cutoff],
		},
	)
	if already_sent:
		return

	notify(
		recipient_user=seller_user,
		recipient_role="seller",
		type="stock",
		title=alert_title,
		message=alert_message,
		action_url=f"/app/listing/{listing_name}",
		reference_doctype="Listing",
		reference_name=listing_name,
	)
