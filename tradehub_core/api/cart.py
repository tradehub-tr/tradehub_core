import json

import frappe
from frappe import _

from tradehub_core.api._input import safe_int
from tradehub_core.utils.auth_guards import require_verified_email
from tradehub_core.utils.stock import reserve_stock_for_order

# Anında ödeme gerçekleşen yöntemler (ödeme gateway'i onaylar → direkt "Onaylanıyor")
INSTANT_PAYMENT_METHODS = {"credit_card", "iyzico", "paytr", "stripe"}

# Manuel onay gerektiren yöntemler (dekont/belge beklenir → "Ödeme Bekleniyor")
DEFERRED_PAYMENT_METHODS = {"bank_transfer", "check_promissory", "negotiated", "installment"}


def _invalidate_cart_cache(_cart_name):
	"""No-op: cache kaldırıldı. Listing status değiştiğinde stale data önlemek için."""
	pass


def _ensure_seller_kyb_verified(seller_profile_name: str, listing_label: str = ""):
	"""Listing'in satıcısının KYB Verified olduğunu kanıtla, değilse Türkçe throw.

	Sipariş gate'i: 3 katmanlı bypass-proof yapı (add_to_cart + create_order + Order
	doctype validate). Verified Seller rolü, KYBVerification.on_update hook'uyla
	otomatik atanır/kaldırılır. Listing'in storefront'ta görünür olması (Active)
	bu kontrolden BAĞIMSIZDIR; burada sadece para hareketi (satın alma) engellenir.
	"""
	if not seller_profile_name:
		return

	seller_user = frappe.db.get_value("Admin Seller Profile", seller_profile_name, "user")
	if not seller_user:
		return

	if "Verified Seller" not in frappe.get_roles(seller_user):
		if listing_label:
			frappe.throw(
				_("{0}: Bu satıcının KYB doğrulaması henüz tamamlanmadığı için sepete eklenemez.").format(
					listing_label
				),
				frappe.ValidationError,
			)
		else:
			frappe.throw(
				_("Bu satıcının KYB doğrulaması henüz tamamlanmadığı için ürün satın alınamaz."),
				frappe.ValidationError,
			)


def _build_cart_response_cached(cart_name):
	"""Cache kaldırıldı — her istek DB'den taze veri çeker."""
	return _build_cart_response(cart_name)


# ──────────────────────────── helpers ────────────────────────────────────────


def _parse_billing_info(billing_info_json):
	"""Fatura bilgisi JSON'unu parse edip doğrular. None ise {} döner (fatura opsiyonel)."""
	if not billing_info_json:
		return {}
	if isinstance(billing_info_json, str):
		try:
			data = json.loads(billing_info_json)
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz fatura bilgisi"))
	else:
		data = billing_info_json
	if not isinstance(data, dict):
		frappe.throw(_("Geçersiz fatura bilgisi"))

	billing_type = (data.get("type") or "").strip()
	if billing_type and billing_type not in ("Bireysel", "Şirket"):
		frappe.throw(_("Geçersiz fatura tipi"))

	if billing_type == "Şirket":
		if not (data.get("company_name") or "").strip():
			frappe.throw(_("Şirket ünvanı zorunludur"))
		if not (data.get("tax_office") or "").strip():
			frappe.throw(_("Vergi dairesi zorunludur"))
		tax_number = (data.get("tax_number") or "").strip()
		if not tax_number or not tax_number.isdigit() or len(tax_number) != 10:
			frappe.throw(_("Geçerli bir VKN giriniz (10 haneli)"))
	elif billing_type == "Bireysel":
		tcn = (data.get("tcn") or "").strip()
		if not tcn or not tcn.isdigit() or len(tcn) != 11:
			frappe.throw(_("Geçerli bir TCKN giriniz (11 haneli)"))

	same_as_shipping = bool(data.get("same_as_shipping"))
	if billing_type and not same_as_shipping:
		for k, label in (
			("address", "Adres"),
			("city", "İl"),
			("district", "İlçe"),
			("postal_code", "Posta kodu"),
		):
			if not (data.get(k) or "").strip():
				frappe.throw(_("Fatura {0} zorunludur").format(label.lower()))

	return {
		"type": billing_type,
		"company_name": (data.get("company_name") or "").strip(),
		"tax_office": (data.get("tax_office") or "").strip(),
		"tax_number": (data.get("tax_number") or "").strip(),
		"tcn": (data.get("tcn") or "").strip(),
		"e_invoice": 1 if data.get("e_invoice") else 0,
		"same_as_shipping": 1 if same_as_shipping else 0,
		"address": (data.get("address") or "").strip(),
		"city": (data.get("city") or "").strip(),
		"district": (data.get("district") or "").strip(),
		"postal_code": (data.get("postal_code") or "").strip(),
	}


def _get_or_create_cart(user):
	"""Get or create the active Cart for a user. Returns cart name."""
	cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	if not cart_name:
		try:
			cart = frappe.new_doc("Cart")
			cart.buyer = user
			cart.status = "Active"
			cart.insert(ignore_permissions=True)
			frappe.db.commit()
			cart_name = cart.name
		except frappe.DuplicateEntryError:
			# Race condition: another request created the cart first
			frappe.db.rollback()
			cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	return cart_name


def _verify_cart_item_owner(cart_item_name, user):
	"""Raises PermissionError if cart_item doesn't belong to user. Returns cart name."""
	# Use filter syntax for child table lookup (safer than positional string arg)
	rows = frappe.get_all(
		"Cart Item",
		filters={"name": cart_item_name},
		fields=["parent"],
	)
	if not rows:
		frappe.throw(_("Sepet öğesi bulunamadı"), frappe.DoesNotExistError)

	parent_cart = rows[0]["parent"]
	cart_buyer = frappe.db.get_value("Cart", parent_cart, "buyer")
	if cart_buyer != user:
		frappe.throw(_("Yetkisiz işlem"), frappe.PermissionError)
	return parent_cart


def _find_existing_cart_item(
	cart_name, listing, listing_variant, color_variant=None, variant_label=None, is_sample=False
):
	"""
	Find an existing Cart Item for the given listing + variant combination.
	Matches on listing_variant, color_variant, variant_label AND is_sample so that
	numune ve toptan satırları aynı varyantta bile birbirinden ayrı tutulur.
	"""
	all_rows = frappe.get_all(
		"Cart Item",
		filters={"parent": cart_name, "listing": listing},
		fields=[
			"name",
			"listing_variant",
			"color_variant",
			"variant_label",
			"is_sample",
			"quantity",
		],
	)
	norm_variant = listing_variant or None
	norm_color = color_variant or None
	norm_label = variant_label or None
	norm_sample = 1 if is_sample else 0
	for row in all_rows:
		row_variant = row.listing_variant or None
		row_color = row.color_variant or None
		row_label = row.variant_label or None
		row_sample = 1 if int(row.is_sample or 0) else 0
		if (
			row_variant == norm_variant
			and row_color == norm_color
			and row_label == norm_label
			and row_sample == norm_sample
		):
			return row
	return None


def _get_variant_stock_by_label(listing_name, variant_label):
	"""
	Parse variant_label (e.g. "Renk: Siyah | Malzeme: Pamuk | Beden: S")
	and find the matching Listing Variant Item's stock.
	Returns stock as float, or None if no match.
	"""
	if not variant_label:
		return None

	from tradehub_core.utils.stock import _find_variant_item_row

	row_name = _find_variant_item_row(listing_name, variant_label)
	if row_name:
		return float(frappe.db.get_value("Listing Variant Item", row_name, "variant_stock") or 0)
	return None


def _get_variant_price_by_label(listing_name, variant_label):
	"""
	Parse variant_label (e.g. "Renk: Mavi | Kumaş: Polyester | Boy: 50cm | Beden: S")
	and find the matching Listing Variant Item's variant_price.
	Returns price as float when > 0, else None (caller falls back to base price).
	"""
	if not variant_label:
		return None

	from tradehub_core.utils.stock import _find_variant_item_row

	row_name = _find_variant_item_row(listing_name, variant_label)
	if not row_name:
		return None
	vp = frappe.db.get_value("Listing Variant Item", row_name, "variant_price")
	if vp and float(vp) > 0:
		return float(vp)
	return None


def _check_stock(listing_doc, listing_name, listing_variant, total_qty, variant_label=None):
	"""
	Stok kontrolü: track_inventory açıksa toplam miktarı (mevcut + yeni) kontrol et.
	Sırasıyla:
	  1) variant_label ile varyant satırı stoğu (N-eksen)
	  2) Listing Variant doc stoğu
	  3) Listing seviyesi stok
	"""
	if not listing_doc.track_inventory or listing_doc.allow_backorders:
		return

	available = None

	# 1) variant_label ile per-variant stok kontrolü (N-eksen)
	if variant_label:
		label_stock = _get_variant_stock_by_label(listing_name, variant_label)
		if label_stock is not None:
			available = label_stock

	if available is None and listing_variant:
		# 2) Gerçek Listing Variant doc'u
		variant_doc = frappe.db.get_value("Listing Variant", listing_variant, ["stock_qty"], as_dict=True)
		if variant_doc and (variant_doc.stock_qty or 0) > 0:
			available = float(variant_doc.stock_qty)

	if available is None:
		# 3) Listing seviyesi stok
		available = float(listing_doc.stock_qty or 0)

	if total_qty > available:
		if available <= 0:
			frappe.throw(_("Bu üründen yeterli stok bulunmamaktadır."))
		else:
			frappe.throw(
				_("Bu üründen bu kadar stok yok. En fazla {0} adet eklenebilir.").format(int(available))
			)


def _build_cart_response(cart_name):
	"""
	Build a CartSupplier[] response from a Cart document.
	Matches the frontend's CartSupplier / CartProduct / CartSku interfaces exactly.
	"""
	items = frappe.get_all(
		"Cart Item",
		filters={"parent": cart_name},
		fields=[
			"name",
			"listing",
			"listing_variant",
			"color_variant",
			"variant_label",
			"is_sample",
			"quantity",
			"seller",
			"snapshot_title",
			"snapshot_image",
			"snapshot_price",
			"snapshot_currency",
		],
		order_by="creation asc",
	)

	# seller_id → {supplier dict with products dict}
	sellers_map = {}

	for item in items:
		listing = frappe.db.get_value(
			"Listing",
			item.listing,
			[
				"name",
				"title",
				"seller_profile",
				"primary_image",
				"selling_price",
				"base_price",
				"min_order_qty",
				"sell_in_moq_multiples",
				"currency",
				"status",
				"track_inventory",
				"allow_backorders",
				"stock_qty",
				"sample_price",
			],
			as_dict=True,
		)
		is_available = bool(listing and listing.status == "Active")
		row_is_sample = bool(int(item.is_sample or 0))

		# Satıcı ID'sini belirle: aktif listing'den veya snapshot'tan al
		if is_available:
			seller_id = listing.seller_profile
		else:
			seller_id = item.seller or (listing.seller_profile if listing else None)

		if not seller_id:
			continue

		# Listing yok ve snapshot da yok → gösterecek veri yok, atla
		if not listing and not item.snapshot_title and not item.snapshot_price:
			continue

		# Lazy-init seller bucket
		if seller_id not in sellers_map:
			seller = frappe.db.get_value(
				"Admin Seller Profile",
				seller_id,
				["seller_name", "seller_code", "logo"],
				as_dict=True,
			)
			if not seller:
				continue
			slug = seller.seller_code or seller_id
			sellers_map[seller_id] = {
				"id": seller_id,
				"name": seller.seller_name or seller_id,
				"href": f"/pages/seller.html?id={slug}",
				"selected": True,
				"products": {},
			}

		listing_name = item.listing

		# Lazy-init product bucket
		if listing_name not in sellers_map[seller_id]["products"]:
			if is_available:
				tiers = frappe.get_all(
					"Listing Bulk Pricing Tier",
					filters={"parent": listing_name},
					fields=["min_qty", "max_qty", "price"],
					order_by="min_qty asc",
				)
				price_tiers = [
					{"minQty": t.min_qty, "maxQty": t.max_qty or None, "price": float(t.price)} for t in tiers
				]
				sellers_map[seller_id]["products"][listing_name] = {
					"id": listing_name,
					"title": listing.title or "",
					"href": f"/pages/product-detail.html?id={listing_name}",
					"tags": [],
					"moqLabel": f"Min. {listing.min_order_qty or 1} Adet",
					"favoriteIcon": "♡",
					"deleteIcon": "🗑",
					"selected": True,
					"priceTiers": price_tiers,
					"baseCurrency": listing.currency or "USD",
					"skus": [],
				}
			else:
				# Snapshot yoksa listing verisini fallback olarak kullan
				snap_title = item.snapshot_title or (listing.title if listing else "") or ""
				_ = item.snapshot_image or (listing.primary_image if listing else "") or ""
				_ = float(item.snapshot_price or 0) or float(
					(listing.selling_price or listing.base_price or 0) if listing else 0
				)
				snap_currency = item.snapshot_currency or (listing.currency if listing else "USD") or "USD"
				sellers_map[seller_id]["products"][listing_name] = {
					"id": listing_name,
					"title": snap_title,
					"href": f"/pages/product-detail.html?id={listing_name}",
					"tags": [],
					"moqLabel": "",
					"favoriteIcon": "♡",
					"deleteIcon": "🗑",
					"selected": False,
					"priceTiers": [],
					"baseCurrency": snap_currency,
					"skus": [],
				}

		if is_available:
			# Canlı veri ile SKU oluştur
			# Numune satırlarında snapshot fiyatı (sample_price) referans alınır.
			if row_is_sample:
				base_price = float(item.snapshot_price or listing.sample_price or 0)
			else:
				base_price = float(listing.selling_price or listing.base_price or 0)
			sku_image = item.snapshot_image or listing.primary_image or ""
			# variant_label (frontend tarafından gönderilen tam etiket) varsa direkt kullan
			variant_text = item.variant_label or ""
			base_price_addon = 0.0

			# color_variant'tan görsel çek (snapshot yoksa)
			if item.color_variant and item.color_variant.startswith(listing_name + "-"):
				color_parts = item.color_variant[len(listing_name) + 1 :].split("-", 1)
				if len(color_parts) == 2:
					c_type, c_value = color_parts[0].strip(), color_parts[1].strip()
					civ = frappe.db.get_value(
						"Listing Variant Item",
						{
							"parent": listing_name,
							"parenttype": "Listing",
							"attribute_type": c_type,
							"attribute_value": c_value,
						},
						["variant_image"],
						as_dict=True,
					)
					if civ and civ.variant_image:
						sku_image = civ.variant_image

			variant = None
			if item.listing_variant and not variant_text and not row_is_sample:
				# Gerçek Listing Variant doc mu dene
				variant = frappe.db.get_value(
					"Listing Variant",
					item.listing_variant,
					["variant_name", "price", "primary_image", "stock_qty"],
					as_dict=True,
				)
				if variant:
					variant_text = variant.variant_name or ""
					if variant.primary_image:
						sku_image = variant.primary_image
					if variant.price:
						base_price_addon = float(variant.price) - base_price
				else:
					# Inline (sentetik) varyant: "LST-00004-Renk-Siyah" formatı
					# Attribute değerini ID'den çıkar
					parts = item.listing_variant.split("-")
					if len(parts) >= 3:
						variant_text = parts[-1]  # son parça attribute değeri
					# Inline varyant fiyatını bul
					inline_parts = (
						item.listing_variant[len(listing_name) + 1 :].split("-", 1)
						if item.listing_variant.startswith(listing_name + "-")
						else []
					)
					if len(inline_parts) == 2:
						attr_type, attr_value = inline_parts
						iv = frappe.db.get_value(
							"Listing Variant Item",
							{
								"parent": listing_name,
								"parenttype": "Listing",
								"attribute_type": attr_type,
								"attribute_value": attr_value,
							},
							["variant_price", "variant_image", "variant_stock"],
							as_dict=True,
						)
						if iv:
							if iv.variant_image:
								sku_image = iv.variant_image
							if iv.variant_price and iv.variant_price > 0:
								base_price_addon = float(iv.variant_price) - base_price

			# maxQty: track_inventory açıksa variant stoğunu, yoksa listing stoğunu kullan
			if listing.track_inventory and not listing.allow_backorders:
				if variant:
					max_qty = max(0, int(variant.stock_qty or 0))
				else:
					# variant_label ile per-variant stok (N-eksen)
					label_stock = (
						_get_variant_stock_by_label(listing_name, item.variant_label)
						if item.variant_label
						else None
					)
					if label_stock is not None:
						max_qty = max(0, int(label_stock))
					else:
						max_qty = max(0, int(listing.stock_qty or 0))
			else:
				max_qty = 999999

			# Çok-eksenli varyant için: variant_label varsa SKU bazlı fiyatı her zaman çöz
			sku_unit_price = base_price + base_price_addon
			sku_base_unit_price = base_price
			sku_price_addon = base_price_addon
			label_price = _get_variant_price_by_label(listing_name, item.variant_label)
			if label_price is not None:
				sku_unit_price = label_price
				sku_base_unit_price = label_price
				sku_price_addon = 0.0

			# Numune satırları MOQ/stok kuralından muaf, sabit min=max=1.
			sku_min_qty = 1 if row_is_sample else (listing.min_order_qty or 1)
			sku_max_qty = 1 if row_is_sample else max_qty
			sellers_map[seller_id]["products"][listing_name]["skus"].append(
				{
					"id": item.name,
					"skuImage": sku_image,
					"variantText": variant_text,
					"unitPrice": sku_unit_price,
					"priceAddon": sku_price_addon,
					"currency": listing.currency or "USD",
					"unit": "Adet",
					"quantity": item.quantity,
					"minQty": sku_min_qty,
					"sellInMoqMultiples": False if row_is_sample else bool(listing.sell_in_moq_multiples),
					"maxQty": sku_max_qty,
					"selected": True,
					"baseUnitPrice": sku_base_unit_price,
					"basePriceAddon": sku_price_addon,
					"baseCurrency": listing.currency or "USD",
					"listingVariant": item.listing_variant or None,
					"isAvailable": True,
					"isSample": row_is_sample,
				}
			)
		else:
			# Snapshot verisiyle SKU oluştur (satın alınamaz, gösterim amaçlı)
			# snap_title/image/price/currency product bucket'ta hesaplandı, aynısını kullan
			snap_price_sku = float(item.snapshot_price or 0) or float(
				(listing.selling_price or listing.base_price or 0) if listing else 0
			)
			snap_image_sku = item.snapshot_image or (listing.primary_image if listing else "") or ""
			snap_currency_sku = item.snapshot_currency or (listing.currency if listing else "USD") or "USD"
			sellers_map[seller_id]["products"][listing_name]["skus"].append(
				{
					"id": item.name,
					"skuImage": snap_image_sku,
					"variantText": "",
					"unitPrice": snap_price_sku,
					"priceAddon": 0,
					"currency": snap_currency_sku,
					"unit": "Adet",
					"quantity": item.quantity,
					"minQty": 1,
					"maxQty": 1 if row_is_sample else 999999,
					"selected": False,
					"baseUnitPrice": snap_price_sku,
					"basePriceAddon": 0,
					"baseCurrency": snap_currency_sku,
					"listingVariant": item.listing_variant or None,
					"isAvailable": False,
					"isSample": row_is_sample,
				}
			)

	suppliers = []
	for seller_data in sellers_map.values():
		suppliers.append(
			{
				"id": seller_data["id"],
				"name": seller_data["name"],
				"href": seller_data["href"],
				"selected": seller_data["selected"],
				"products": list(seller_data["products"].values()),
			}
		)

	return {"suppliers": suppliers}


# ──────────────────────────── endpoints ──────────────────────────────────────


@frappe.whitelist()
def get_cart():
	"""Return the current user's cart as CartSupplier[]."""
	user = frappe.session.user
	if not user or user == "Guest":
		return {"suppliers": []}

	cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	if not cart_name:
		return {"suppliers": []}

	return _build_cart_response_cached(cart_name)


@frappe.whitelist()
def check_stock(listing, quantity=1, listing_variant=None, variant_label=None, is_sample=0):
	"""
	Stok kontrolü yapar ama sepete eklemez.
	Ürün sayfasındaki drawer için kullanılır — gerçek kayıt cart.add_to_cart ile yapılır.
	variant_label: human-readable label (e.g. "Renk: Siyah | Malzeme: Pamuk | Beden: S")
	is_sample: 1 ise numune kontrolü (sample_price tanımlı mı, daha önce sepette numune var mı).
	Hata yoksa {"ok": True} döner, hata varsa frappe.throw() ile exception fırlatır.
	"""
	if not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı"), frappe.DoesNotExistError)

	listing_doc = frappe.db.get_value(
		"Listing",
		listing,
		["status", "stock_qty", "track_inventory", "allow_backorders", "sample_price"],
		as_dict=True,
	)
	if listing_doc.status != "Active":
		frappe.throw(_("Bu ürün şu an satışta değil"))

	is_sample_flag = bool(safe_int(is_sample, label=_("Numune")))
	qty = safe_int(quantity, label=_("Miktar"))
	listing_variant = listing_variant or None
	variant_label = variant_label or None

	if is_sample_flag:
		if not float(listing_doc.sample_price or 0):
			frappe.throw(_("Bu ürün için numune satışı tanımlı değil"))
		# Numune drawer'ı her zaman 1 adet — daha fazlasına izin verme.
		if qty > 1:
			frappe.throw(_("Numune için maksimum sipariş miktarı 1 adettir"))
		# Aynı kullanıcı zaten numune eklediyse tekrar eklenemesin (bilgi amaçlı).
		user = frappe.session.user
		if user and user != "Guest":
			cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
			if cart_name:
				exists = frappe.db.exists(
					"Cart Item", {"parent": cart_name, "listing": listing, "is_sample": 1}
				)
				if exists:
					frappe.throw(_("Bu üründen sepetinizde zaten 1 numune var"))
		return {"ok": True}

	_check_stock(listing_doc, listing, listing_variant, qty, variant_label=variant_label)
	return {"ok": True}


@frappe.whitelist()
def add_to_cart(
	listing,
	quantity=1,
	listing_variant=None,
	variant_label=None,
	color_variant=None,
	extra_axes=None,
	is_sample=0,
):
	"""
	Add a listing (optionally a specific variant) to cart.
	variant_label: human-readable combined label, e.g. "Renk: Lacivert | Malzeme: Pamuk | Beden: S"
	color_variant: inline color variant ID (e.g. "LST-00013-Renk-Lacivert") used for snapshot_image lookup.
	extra_axes: JSON string of extra axis selections, e.g. '{"Malzeme": "Pamuk"}'
	is_sample: 1 ise numune satırı; toptan satırından ayrı tutulur, miktar 1'e sabittir,
	  fiyat olarak listing.sample_price kullanılır.
	If already exists, increments quantity (numune hariç — numune zaten varsa hata fırlatır).
	Returns the full cart response.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sepete eklemek için giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	if not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı"), frappe.DoesNotExistError)

	# Listing durumu ve stok/MOQ kontrolü
	listing_doc = frappe.db.get_value(
		"Listing",
		listing,
		[
			"status",
			"min_order_qty",
			"sell_in_moq_multiples",
			"stock_qty",
			"track_inventory",
			"allow_backorders",
			"seller_profile",
			"title",
			"primary_image",
			"selling_price",
			"base_price",
			"currency",
			"sample_price",
		],
		as_dict=True,
	)
	if listing_doc.status != "Active":
		frappe.throw(_("Bu ürün şu an satışta değil"))

	# KYB Gate — Katman 1: Satıcı doğrulanmadıysa sepete eklenemez.
	# Listing Active görünmeye devam eder (storefront vitrini bağımsız), sadece
	# satın alma kapısı kapalıdır. Satıcı KYB onayı sonrası açılır.
	_ensure_seller_kyb_verified(listing_doc.seller_profile, listing_doc.title or "")

	is_sample_flag = bool(safe_int(is_sample, label=_("Numune")))
	qty = safe_int(quantity, label=_("Miktar"))

	if is_sample_flag:
		if not float(listing_doc.sample_price or 0):
			frappe.throw(_("Bu ürün için numune satışı tanımlı değil"))
		# Numuneler her zaman 1 adet — frontend yanlış gönderse bile burada zorla.
		qty = 1
	else:
		min_qty = int(listing_doc.min_order_qty or 1)
		if qty < min_qty:
			frappe.throw(_("Minimum sipariş miktarı: {0}").format(min_qty))
		if listing_doc.sell_in_moq_multiples and min_qty > 0 and qty % min_qty != 0:
			frappe.throw(_("Sipariş miktarı {0}'ın katları olmalıdır").format(min_qty))

	# Normalize variant: empty string → None
	listing_variant = listing_variant or None
	color_variant = color_variant or None

	cart_name = _get_or_create_cart(user)
	existing_row = _find_existing_cart_item(
		cart_name, listing, listing_variant, color_variant, variant_label, is_sample=is_sample_flag
	)
	existing_qty = existing_row.quantity if existing_row else 0

	if is_sample_flag:
		# Sepette aynı listing için zaten numune varsa tekrar eklenemez.
		if existing_row:
			frappe.throw(_("Bu üründen sepetinizde zaten 1 numune var"))
		# Numune satırı için stok kontrolü yapma — tek adetlik bir denemedir.
	else:
		total_qty = existing_qty + qty
		_check_stock(listing_doc, listing, listing_variant, total_qty, variant_label=variant_label)

	# Snapshot verisi hazırla
	snap_price = float(listing_doc.selling_price or listing_doc.base_price or 0)
	snap_image = listing_doc.primary_image or ""
	snap_title = listing_doc.title or ""
	snap_currency = listing_doc.currency or "USD"
	seller_id = listing_doc.seller_profile or None

	if is_sample_flag:
		# Numune fiyatını snapshot olarak yaz; tier hesabı devreye girmesin.
		snap_price = float(listing_doc.sample_price or 0)

	if listing_variant and not is_sample_flag:
		var_snap = frappe.db.get_value(
			"Listing Variant", listing_variant, ["primary_image", "price"], as_dict=True
		)
		if var_snap:
			if var_snap.primary_image:
				snap_image = var_snap.primary_image
			if var_snap.price:
				snap_price = float(var_snap.price)

	# Çok-eksenli varyant için: variant_label'dan SKU bazlı fiyatı çöz (varsa override)
	resolved_sku_price = _get_variant_price_by_label(listing, variant_label)
	if resolved_sku_price is not None:
		snap_price = resolved_sku_price

	# Renk varyantından görsel çek (color_variant = inline renk ID'si, ör. "LST-00013-Renk-Lacivert")
	if color_variant and color_variant.startswith(listing + "-"):
		color_parts = color_variant[len(listing) + 1 :].split("-", 1)
		if len(color_parts) == 2:
			color_type, color_value = color_parts[0].strip(), color_parts[1].strip()
			iv = frappe.db.get_value(
				"Listing Variant Item",
				{
					"parent": listing,
					"parenttype": "Listing",
					"attribute_type": color_type,
					"attribute_value": color_value,
				},
				["variant_image"],
				as_dict=True,
			)
			if iv and iv.variant_image:
				snap_image = iv.variant_image

	# cart_name ve existing_row yukarıda stok kontrolü için alındı — tekrar sorgulama
	if existing_row:
		# Numune yolu yukarıda zaten bloklandı; burası sadece toptan için.
		frappe.db.set_value(
			"Cart Item",
			existing_row.name,
			{
				"quantity": existing_row.quantity + qty,
				"variant_label": variant_label or existing_row.get("variant_label") or None,
				"snapshot_image": snap_image or existing_row.get("snapshot_image") or None,
			},
		)
	else:
		cart_doc = frappe.get_doc("Cart", cart_name)
		cart_doc.append(
			"items",
			{
				"listing": listing,
				"listing_variant": listing_variant,
				"color_variant": color_variant,
				"variant_label": variant_label or None,
				"is_sample": 1 if is_sample_flag else 0,
				"quantity": qty,
				"seller": seller_id,
				"snapshot_title": snap_title,
				"snapshot_image": snap_image,
				"snapshot_price": snap_price,
				"snapshot_currency": snap_currency,
			},
		)
		cart_doc.save(ignore_permissions=True)

	frappe.db.commit()
	_invalidate_cart_cache(cart_name)
	return _build_cart_response_cached(cart_name)


@frappe.whitelist()
def update_cart_item(cart_item, quantity):
	"""Update the quantity of a cart item."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	_verify_cart_item_owner(cart_item, user)

	qty = safe_int(quantity, label=_("Miktar"))
	if qty <= 0:
		frappe.throw(_("Miktar sıfırdan büyük olmalıdır"))

	# Stok kontrolü — variant_label ile per-variant stok kontrolü (N-eksen)
	cart_item_data = frappe.db.get_value(
		"Cart Item",
		cart_item,
		["listing", "listing_variant", "variant_label", "is_sample"],
		as_dict=True,
	)
	listing_name = cart_item_data.listing if cart_item_data else None
	listing_variant_name = cart_item_data.listing_variant if cart_item_data else None
	variant_label_value = cart_item_data.variant_label if cart_item_data else None
	row_is_sample = bool(int((cart_item_data or {}).get("is_sample") or 0))

	# Numune satırının miktarı her zaman 1 olmalı; sayfa kontrolü atlasa bile burada kilitle.
	if row_is_sample and qty != 1:
		frappe.throw(_("Numune için maksimum sipariş miktarı 1 adettir"))

	if listing_name and not row_is_sample:
		listing_doc = frappe.db.get_value(
			"Listing",
			listing_name,
			["stock_qty", "track_inventory", "allow_backorders"],
			as_dict=True,
		)
		if listing_doc:
			_check_stock(
				listing_doc, listing_name, listing_variant_name, qty, variant_label=variant_label_value
			)

	frappe.db.set_value("Cart Item", cart_item, "quantity", qty)
	frappe.db.commit()
	cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	if cart_name:
		_invalidate_cart_cache(cart_name)
	return {"success": True}


@frappe.whitelist()
def remove_cart_item(cart_item):
	"""Remove a single item from cart."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	cart_name = _verify_cart_item_owner(cart_item, user)
	frappe.delete_doc("Cart Item", cart_item, ignore_permissions=True)
	frappe.db.commit()
	_invalidate_cart_cache(cart_name)
	return {"success": True}


@frappe.whitelist()
def clear_cart():
	"""Remove all items from the active cart."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	if not cart_name:
		return {"success": True}

	frappe.db.delete("Cart Item", {"parent": cart_name})
	frappe.db.commit()
	_invalidate_cart_cache(cart_name)
	return {"success": True}


@frappe.whitelist()
def merge_guest_cart(items):
	"""
	Merge guest localStorage items into the logged-in user's cart.
	items: JSON list of {listing, listing_variant?, quantity}
	Returns the full cart response after merge.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	if isinstance(items, str):
		try:
			items = json.loads(items)
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz sepet verisi"))

	if not isinstance(items, list):
		frappe.throw(_("Geçersiz sepet verisi"))

	cart_name = _get_or_create_cart(user)

	# Load cart doc once for appending new items
	cart_doc = frappe.get_doc("Cart", cart_name)
	needs_save = False

	for item in items:
		listing = item.get("listing")
		listing_variant = item.get("listing_variant") or None
		variant_label = item.get("variant_label") or None
		qty = int(item.get("quantity", 1))

		if not listing or qty <= 0:
			continue
		if not frappe.db.exists("Listing", listing):
			continue

		existing_row = _find_existing_cart_item(cart_name, listing, listing_variant, None, variant_label)

		if existing_row:
			# Update in-memory cart_doc row so save() is consistent
			for row in cart_doc.items:
				if row.name == existing_row.name:
					row.quantity = existing_row.quantity + qty
					needs_save = True
					break
		else:
			# Snapshot verisi hazırla
			listing_snap = (
				frappe.db.get_value(
					"Listing",
					listing,
					["seller_profile", "title", "primary_image", "selling_price", "base_price", "currency"],
					as_dict=True,
				)
				or {}
			)
			snap_price = float(listing_snap.get("selling_price") or listing_snap.get("base_price") or 0)
			snap_image = listing_snap.get("primary_image") or ""
			snap_currency = listing_snap.get("currency") or "USD"
			if listing_variant:
				var_snap = frappe.db.get_value(
					"Listing Variant", listing_variant, ["primary_image", "price"], as_dict=True
				)
				if var_snap:
					if var_snap.primary_image:
						snap_image = var_snap.primary_image
					if var_snap.price:
						snap_price = float(var_snap.price)
			# Çok-eksenli varyant için: variant_label'dan SKU bazlı fiyatı çöz (varsa override)
			resolved_sku_price = _get_variant_price_by_label(listing, variant_label)
			if resolved_sku_price is not None:
				snap_price = resolved_sku_price
			cart_doc.append(
				"items",
				{
					"listing": listing,
					"listing_variant": listing_variant,
					"variant_label": variant_label,
					"quantity": qty,
					"seller": listing_snap.get("seller_profile") or None,
					"snapshot_title": listing_snap.get("title") or "",
					"snapshot_image": snap_image,
					"snapshot_price": snap_price,
					"snapshot_currency": snap_currency,
				},
			)
			needs_save = True

	if needs_save:
		cart_doc.save(ignore_permissions=True)

	frappe.db.commit()
	_invalidate_cart_cache(cart_name)
	return _build_cart_response_cached(cart_name)


@frappe.whitelist()
@require_verified_email
def create_order(
	orders_json,
	shipping_address=None,
	payment_method=None,
	coupon_code=None,
	coupon_discount=0,
	billing_info_json=None,
):
	"""
	Seçili sepet ürünlerinden sipariş(ler) oluşturur.
	orders_json: JSON list of {
	  seller_id, seller_name, shipping_fee, currency,
	  products: [{listing, listing_title, variation, unit_price, quantity, total_price, image}]
	}
	billing_info_json: JSON dict — fatura bilgileri (opsiyonel):
	  type ('Bireysel'|'Şirket'), company_name, tax_office, tax_number, tcn,
	  e_invoice (bool), same_as_shipping (bool), address, city, district, postal_code
	Returns: { orders: [{order_name, order_number, seller_name, total}] }
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Sipariş vermek için giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	if isinstance(orders_json, str):
		try:
			orders_data = json.loads(orders_json)
		except (ValueError, TypeError):
			frappe.throw(_("Geçersiz sipariş verisi"))
	else:
		orders_data = orders_json

	if not isinstance(orders_data, list) or len(orders_data) == 0:
		frappe.throw(_("Sipariş verisi boş olamaz"))

	if not shipping_address:
		frappe.throw(_("Teslimat adresi zorunludur"))
	addr_user = frappe.db.get_value("Addresses", shipping_address, "user")
	if not addr_user:
		frappe.throw(_("Geçersiz teslimat adresi"), frappe.DoesNotExistError)
	if addr_user != user:
		frappe.throw(_("Bu adres size ait değil"), frappe.PermissionError)

	billing_info = _parse_billing_info(billing_info_json)

	pm = payment_method or "bank_transfer"
	if pm not in (INSTANT_PAYMENT_METHODS | DEFERRED_PAYMENT_METHODS):
		frappe.throw(_("Geçersiz ödeme yöntemi"))

	order_count = len([o for o in orders_data if o.get("products")])

	# Kupon indirimi tüm siparişlerin toplam tutarını aşamaz (HATA 26).
	# Aksi halde Order.coupon_discount field'ı gerçek dışı bir sayı (örn. 100000)
	# olarak DB'ye yazılır; total max(0,...) ile clamp'lense de muhasebe/raporlamada
	# tutarsızlık doğar.
	total_payable = 0.0
	for o in orders_data:
		if not o.get("products"):
			continue
		_sub = sum(float(p.get("total_price", 0)) for p in o["products"])
		_ship = float(o.get("shipping_fee", 0))
		total_payable += _sub + _ship
	coupon_discount_val = min(float(coupon_discount or 0), total_payable)
	# Kupon indirimini siparişlere eşit dağıt
	per_order_coupon_discount = round(coupon_discount_val / order_count, 2) if order_count > 0 else 0

	created_orders = []

	for order_data in orders_data:
		seller_id = order_data.get("seller_id", "")
		products = order_data.get("products", [])
		shipping_fee = float(order_data.get("shipping_fee", 0))
		currency = order_data.get("currency", "USD")

		if not products:
			continue

		subtotal = sum(float(p.get("total_price", 0)) for p in products)
		total = subtotal + shipping_fee - per_order_coupon_discount

		if not seller_id or not frappe.db.exists("Admin Seller Profile", seller_id):
			frappe.throw(_("Geçersiz satıcı: {0}").format(seller_id or "(boş)"), frappe.DoesNotExistError)

		# KYB Gate — Katman 2: Satıcı doğrulanmadıysa sipariş oluşturulamaz.
		# Order.validate() ayrıca aynı kontrolü doctype-level enforce eder (Katman 3).
		_ensure_seller_kyb_verified(seller_id)

		order_doc = frappe.new_doc("Order")
		order_doc.buyer = user
		order_doc.seller = seller_id
		# Ödeme yöntemine göre başlangıç statüsü belirle
		if pm in INSTANT_PAYMENT_METHODS:
			order_doc.status = "Onaylanıyor"  # Gateway onayladı → beklemede gerek yok
		else:
			order_doc.status = "Ödeme Bekleniyor"  # Havale/Çek/Senet/Elden → manuel onay
		order_doc.payment_method = pm
		order_doc.currency = currency
		order_doc.subtotal = subtotal
		order_doc.shipping_fee = shipping_fee
		order_doc.coupon_code = coupon_code or ""
		order_doc.coupon_discount = per_order_coupon_discount
		order_doc.total = max(0, total)
		order_doc.shipping_address = shipping_address or ""
		order_doc.shipping_method = order_data.get("shipping_method", "")
		order_doc.ship_from = order_data.get("ship_from", "")
		order_doc.buyer_note = order_data.get("buyer_note", "") or ""

		if billing_info.get("type"):
			order_doc.billing_type = billing_info["type"]
			order_doc.billing_company_name = billing_info["company_name"]
			order_doc.billing_tax_office = billing_info["tax_office"]
			order_doc.billing_tax_number = billing_info["tax_number"]
			order_doc.billing_tcn = billing_info["tcn"]
			order_doc.billing_e_invoice = billing_info["e_invoice"]
			order_doc.billing_same_as_shipping = billing_info["same_as_shipping"]
			order_doc.billing_address = billing_info["address"]
			order_doc.billing_city = billing_info["city"]
			order_doc.billing_district = billing_info["district"]
			order_doc.billing_postal_code = billing_info["postal_code"]

		for p in products:
			# listing_variant artık Data alanı — sentetik ID'leri (LST-XXXXX-Tip-Değer) olduğu gibi sakla
			lv = p.get("listing_variant") or None
			order_doc.append(
				"items",
				{
					"listing": p.get("listing")
					if p.get("listing") and frappe.db.exists("Listing", p.get("listing"))
					else None,
					"listing_title": p.get("listing_title", ""),
					"listing_variant": lv,
					"variation": p.get("variation", ""),
					"unit_price": float(p.get("unit_price", 0)),
					"quantity": int(p.get("quantity", 1)),
					"total_price": float(p.get("total_price", 0)),
					"image": p.get("image", ""),
				},
			)

		order_doc.insert(ignore_permissions=True)
		# Stok rezervasyonu — sipariş oluşturulduğunda listing reserved_qty artır
		reserve_stock_for_order(order_doc.name)

		# Kredi kartı/gateway ödemesi ise Payment Transaction kaydı oluştur
		if pm in INSTANT_PAYMENT_METHODS:
			try:
				from tradehub_core.api.payment import create_payment_transaction

				pm_label_map = {
					"credit_card": "Kredi Kartı",
					"iyzico": "Kredi Kartı (Iyzico)",
					"paytr": "Kredi Kartı (PayTR)",
					"stripe": "Kredi Kartı (Stripe)",
				}
				create_payment_transaction(
					order_name=order_doc.name,
					buyer=user,
					transaction_type="Ödeme",
					amount=float(max(0, total)),
					currency=currency,
					payment_method=pm_label_map.get(pm, "Kredi Kartı"),
					status="Tamamlandı",
				)
			except Exception:
				frappe.log_error(
					f"Instant payment transaction creation failed for {order_doc.name}",
					"instant_payment_tracking",
				)

		created_orders.append(
			{
				"order_name": order_doc.name,
				"order_number": order_doc.name,
				"seller_name": order_data.get("seller_name", ""),
				"total": max(0, total),
				"currency": currency,
			}
		)

	if not created_orders:
		frappe.throw(_("Hiçbir sipariş oluşturulamadı"))

	# Kupon used_count artır
	if coupon_code:
		coupon_name = frappe.db.get_value(
			"Coupon", {"code": coupon_code.strip().upper(), "is_active": 1}, "name"
		)
		if coupon_name:
			current_count = int(frappe.db.get_value("Coupon", coupon_name, "used_count") or 0)
			frappe.db.set_value("Coupon", coupon_name, "used_count", current_count + 1)

	# Sadece sipariş verilen ürünleri sepetten sil (diğer satıcıların ürünleri kalır)
	cart_name = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	if cart_name:
		ordered_listings = set()
		for order_data in orders_data:
			for p in order_data.get("products", []):
				listing_id = p.get("listing")
				variant_id = p.get("listing_variant") or None
				if listing_id:
					ordered_listings.add((listing_id, variant_id))

		if ordered_listings:
			cart_items = frappe.get_all(
				"Cart Item",
				filters={"parent": cart_name},
				fields=["name", "listing", "listing_variant"],
			)
			for ci in cart_items:
				key = (ci.listing, ci.listing_variant or None)
				if key in ordered_listings:
					frappe.delete_doc("Cart Item", ci.name, ignore_permissions=True)

	frappe.db.commit()
	return {"orders": created_orders}


@frappe.whitelist()
def get_orders(page=1, page_size=20):
	"""Oturumdaki kullanıcının siparişlerini döndürür. order.py'ye proxy."""
	from tradehub_core.api.order import get_my_orders

	return get_my_orders(page=page, page_size=page_size)


@frappe.whitelist(allow_guest=True)
def validate_coupon(code, order_total=0):
	"""
	Kupon kodunu doğrular ve indirim bilgisini döndürür.
	"""
	if not code:
		frappe.throw(_("Kupon kodu boş olamaz"))

	import datetime

	coupon = frappe.db.get_value(
		"Coupon",
		{"code": code.strip().upper(), "is_active": 1},
		[
			"name",
			"code",
			"coupon_type",
			"value",
			"min_order",
			"max_uses",
			"used_count",
			"description",
			"expires_at",
		],
		as_dict=True,
	)

	if not coupon:
		frappe.throw(_("Geçersiz veya süresi dolmuş kupon kodu"))

	# Son geçerlilik tarihi kontrolü
	if coupon.expires_at:
		today = datetime.date.today()
		if coupon.expires_at < today:
			frappe.throw(_("Bu kuponun süresi dolmuş"))

	# Max kullanım kontrolü
	if coupon.max_uses and int(coupon.max_uses) > 0:
		if int(coupon.used_count or 0) >= int(coupon.max_uses):
			frappe.throw(_("Bu kupon maksimum kullanım sayısına ulaştı"))

	# Min sipariş tutarı kontrolü
	order_amount = float(order_total or 0)
	min_order = float(coupon.min_order or 0)
	if min_order > 0 and order_amount < min_order:
		frappe.throw(_("Bu kupon için minimum sipariş tutarı: {0}").format(min_order))

	# İndirim tutarını sipariş toplamı ile sınırla (HATA 26).
	# fixed type'ta gerçek değerin clamplenmiş hali döndürülür ki frontend
	# "ücretsiz değil" diye yanlış total göstermesin.
	value = float(coupon.value or 0)
	if coupon.coupon_type == "fixed" and order_amount > 0 and value > order_amount:
		value = order_amount

	return {
		"code": coupon.code,
		"type": coupon.coupon_type,
		"value": value,
		"minOrder": float(coupon.min_order or 0),
		"description": coupon.description or "",
	}


@frappe.whitelist()
def get_buyer_coupons():
	"""Sisteme tanımlı aktif kuponları ve durumlarını döndürür."""
	import datetime

	today = datetime.date.today()

	coupons = frappe.get_all(
		"Coupon",
		filters={"is_active": 1},
		fields=[
			"name",
			"code",
			"coupon_type",
			"value",
			"min_order",
			"max_uses",
			"used_count",
			"description",
			"expires_at",
		],
		order_by="creation desc",
	)

	result = []
	for c in coupons:
		if c.expires_at and c.expires_at < today:
			status = "expired"
		elif int(c.max_uses or 0) > 0 and int(c.used_count or 0) >= int(c.max_uses or 0):
			status = "used"
		else:
			status = "available"

		result.append(
			{
				"code": c.code,
				"type": c.coupon_type,
				"value": float(c.value or 0),
				"minOrder": float(c.min_order or 0),
				"description": c.description or "",
				"status": status,
				"expiresAt": str(c.expires_at) + "T23:59:59Z" if c.expires_at else "",
			}
		)

	return {"coupons": result}
