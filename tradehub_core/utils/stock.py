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


def _lock_listing_row(listing_name):
	"""Listing satırını mevcut transaction süresince kilitle (race koruması).
	read-modify-write akışlarında, başka bir worker'ın aynı satıra concurrent
	UPDATE göndermesini bloklar. Frappe `frappe.db.sql` SELECT ... FOR UPDATE.
	"""
	frappe.db.sql(
		"SELECT name FROM `tabListing` WHERE name=%s FOR UPDATE",
		(listing_name,),
	)


def reserve_stock_for_order(order_name):
	"""Sipariş oluşturulduğunda listing stoklarını rezerve et.

	Atomik UPDATE ile yapılır — WHERE klozunda "available_qty >= qty" şartı
	tek deyimde değerlendirilir. Etkilenen satır 0 ise (yeterli stok yok)
	`frappe.throw` ile sipariş geri çevrilir.

	Bu, `FOR UPDATE` lock + ayrı SELECT/UPDATE pattern'inin yarattığı
	check-then-act yarışını kapatır (E2E test'te 3 paralel istek 2 stoklu
	üründen 3 sipariş alıyordu — N1 over-sell bug'ı).

	`allow_backorders=1` veya `track_inventory=0` ise kontrol atlanır.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation", "listing_title"],
	)
	for item in items:
		if not item.listing:
			continue
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory", "allow_backorders", "title"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)

		if listing.allow_backorders:
			# Backorder serbest — kontrolsüz rezerve et
			frappe.db.sql(
				"UPDATE `tabListing` SET reserved_qty = COALESCE(reserved_qty,0) + %s WHERE name=%s",
				(qty, item.listing),
			)
		else:
			# Atomik: yalnız available_qty (= stock_qty - reserved_qty) >= qty ise rezerve et.
			# Etkilenen satır 0 ise stok yetmemiş demektir.
			affected = frappe.db.sql(
				"""UPDATE `tabListing`
				   SET reserved_qty = COALESCE(reserved_qty,0) + %s
				   WHERE name=%s
				     AND (COALESCE(stock_qty,0) - COALESCE(reserved_qty,0)) >= %s""",
				(qty, item.listing, qty),
			)
			# frappe.db.sql etkilenen satır sayısını döndürmez; cursor.rowcount kullan
			rowcount = frappe.db._cursor.rowcount if frappe.db._cursor else 0
			if rowcount == 0:
				# Atomik koşul başarısız → stok yetmiyor; tüm transaction'ı rollback için throw
				title = listing.title or item.listing_title or item.listing
				frappe.throw(
					_("Yetersiz stok: {0} için talep ettiğiniz miktar mevcut stoğu aşıyor.").format(title),
					frappe.ValidationError,
				)

		# Per-variant stock reservation (variant override; race koruması: aynı
		# tabListing lock'u listing-scope'taki tüm worker'ları serileştirir)
		_update_variant_stock(item.listing, item.variation, -qty)
		_recalculate_available(item.listing)


def release_stock_for_order(order_name):
	"""Sipariş iptal edildiğinde rezervasyonu kaldır.
	reserved_qty atomik UPDATE ile azaltılır, GREATEST(0, ...) ile alttan
	sınırlandırılır. Varyant seviyesinde variant_stock geri eklenir.
	"""
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation"],
	)
	for item in items:
		if not item.listing:
			continue
		_lock_listing_row(item.listing)
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)
		frappe.db.sql(
			"UPDATE `tabListing` SET reserved_qty = GREATEST(0, COALESCE(reserved_qty,0) - %s) WHERE name=%s",
			(qty, item.listing),
		)
		# Per-variant stock release (give back)
		_update_variant_stock(item.listing, item.variation, +qty)
		_recalculate_available(item.listing)


def deduct_stock_for_order(order_name):
	"""Sipariş tamamlandığında gerçek stoktan düş — idempotent.

	`Order.stock_deducted=1` ise no-op (çift düşmeyi engeller).
	stock_qty azaltılır, reserved_qty azaltılır (atomik). Varyant seviyesinde
	variant_stock güncellenir. Başarıyla tamamlanırsa `Order.stock_deducted=1`
	flag'i set edilir.
	"""
	# Idempotency: zaten düşülmüşse no-op
	already_deducted = frappe.db.get_value("Order", order_name, "stock_deducted")
	if already_deducted:
		return

	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation"],
	)
	for item in items:
		if not item.listing:
			continue
		_lock_listing_row(item.listing)
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)
		# Atomik: hem stock_qty hem reserved_qty düşür, GREATEST(0,...) ile clamp
		frappe.db.sql(
			"""UPDATE `tabListing`
			   SET stock_qty = GREATEST(0, COALESCE(stock_qty,0) - %s),
			       reserved_qty = GREATEST(0, COALESCE(reserved_qty,0) - %s)
			   WHERE name=%s""",
			(qty, qty, item.listing),
		)
		# Per-variant stock deduction
		_update_variant_stock(item.listing, item.variation, -qty)
		_recalculate_available(item.listing)

	# Idempotency flag
	frappe.db.set_value("Order", order_name, "stock_deducted", 1, update_modified=False)


def restore_stock_for_refund(order_name):
	"""İade onaylandığında stoku geri yükle — `Order.stock_deducted` flag'ine göre
	doğru yönde delta uygular:

	- stock_deducted=1 (instant pay veya remittance sonrası): stock_qty geri yüklenir.
	- stock_deducted=0 (henüz havale onayı yok): reserved_qty düşürülür (release).

	Her iki durumda variant_stock geri yüklenir ve `_recalculate_available` çağrılır.
	"""
	deducted = frappe.db.get_value("Order", order_name, "stock_deducted") or 0
	items = frappe.get_all(
		"Order Item",
		filters={"parent": order_name},
		fields=["listing", "quantity", "variation"],
	)
	for item in items:
		if not item.listing:
			continue
		_lock_listing_row(item.listing)
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			["track_inventory"],
			as_dict=True,
		)
		if not listing or not listing.track_inventory:
			continue
		qty = flt(item.quantity)
		if deducted:
			# Stock zaten fiziksel olarak düşülmüş; geri ekle
			frappe.db.sql(
				"UPDATE `tabListing` SET stock_qty = COALESCE(stock_qty,0) + %s WHERE name=%s",
				(qty, item.listing),
			)
		else:
			# Sadece rezerveydi; rezervasyondan düş
			frappe.db.sql(
				"UPDATE `tabListing` SET reserved_qty = GREATEST(0, COALESCE(reserved_qty,0) - %s) WHERE name=%s",
				(qty, item.listing),
			)
		# Varyant stoku her iki durumda da geri yüklenir
		_update_variant_stock(item.listing, item.variation, +qty)
		_recalculate_available(item.listing)

	# Refund sonrası stock_deducted=0 (bir daha düşülmesin)
	if deducted:
		frappe.db.set_value("Order", order_name, "stock_deducted", 0, update_modified=False)


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
