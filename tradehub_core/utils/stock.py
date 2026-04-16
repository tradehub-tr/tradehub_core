import frappe
from frappe import _
from frappe.utils import add_to_date, flt, now_datetime

# Aynı listing için aynı türde stok bildirimi en az bu kadar saat arayla gönderilir.
STOCK_ALERT_COOLDOWN_HOURS = 24


def reserve_stock_for_order(order_name):
	"""Sipariş oluşturulduğunda listing stoklarını rezerve et.
	reserved_qty artırılır, available_qty otomatik hesaplanır.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity"],
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
		new_reserved = flt(listing.reserved_qty) + flt(item.quantity)
		frappe.db.set_value("Listing", item.listing, "reserved_qty", new_reserved)
		_recalculate_available(item.listing)


def release_stock_for_order(order_name):
	"""Sipariş iptal edildiğinde rezervasyonu kaldır.
	reserved_qty azaltılır.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity"],
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
		new_reserved = max(0, flt(listing.reserved_qty) - flt(item.quantity))
		frappe.db.set_value("Listing", item.listing, "reserved_qty", new_reserved)
		_recalculate_available(item.listing)


def deduct_stock_for_order(order_name):
	"""Sipariş tamamlandığında gerçek stoktan düş.
	stock_qty azaltılır, reserved_qty azaltılır.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity"],
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
		new_stock = max(0, flt(listing.stock_qty) - flt(item.quantity))
		new_reserved = max(0, flt(listing.reserved_qty) - flt(item.quantity))
		frappe.db.set_value(
			"Listing",
			item.listing,
			{
				"stock_qty": new_stock,
				"reserved_qty": new_reserved,
			},
		)
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
