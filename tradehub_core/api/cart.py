import datetime
import json

import frappe
from frappe import _
from frappe.utils import flt

from tradehub_core.api._input import safe_int
from tradehub_core.api.rate_limit import rate_limit
from tradehub_core.utils.auth_guards import require_verified_email
from tradehub_core.utils.stock import deduct_stock_for_order, reserve_stock_for_order

# Anında ödeme gerçekleşen yöntemler (ödeme gateway'i onaylar → direkt "Onaylanıyor")
INSTANT_PAYMENT_METHODS = {"credit_card", "iyzico", "paytr", "stripe"}

# Manuel onay gerektiren yöntemler (dekont/belge beklenir → "Ödeme Bekleniyor")
DEFERRED_PAYMENT_METHODS = {"bank_transfer", "check_promissory", "negotiated", "installment"}


def _ensure_buyer_kyc_verified(user: str = ""):
	"""Sprint 2.6 (revised): Alıcı KYC Verified olmadan sipariş veremez
	(create_order gate'i — add_to_cart açık, kullanıcı her şeyi doldurabilsin).

	Hata mesajı [KYC_<STATE>] prefix ile dönülür; frontend bu prefix'i regex ile
	yakalayıp doğru modal mesajını gösterir.
	  - KYC_SUSPENDED: hesap askıda, destek talebi
	  - KYC_REJECTED: red gerekçesi, düzelt + tekrar gönder
	  - KYC_PENDING: onay bekleniyor
	  - KYC_LOCKED: KYC tetiklenmemiş (Satıcı kayıt → Alıcı olmak isterse)
	"""
	target_user = user or frappe.session.user
	if not target_user or target_user == "Guest":
		return

	kyc_status = frappe.db.get_value("User Profile", {"user": target_user}, "kyc_status")

	if kyc_status == "Verified":
		return

	if kyc_status == "Suspended":
		frappe.throw(
			_("[KYC_SUSPENDED] Hesabınız askıya alındı."),
			frappe.ValidationError,
		)
	if kyc_status == "Rejected":
		frappe.throw(
			_("[KYC_REJECTED] KYC doğrulamanız reddedildi."),
			frappe.ValidationError,
		)
	if kyc_status in ("Pending", "Under Review"):
		frappe.throw(
			_("[KYC_PENDING] KYC doğrulamanız onay bekliyor."),
			frappe.ValidationError,
		)
	# Locked veya NULL — KYC hiç başlatılmamış
	frappe.throw(
		_("[KYC_LOCKED] Ürün satın alabilmek için KYC doğrulamanızı tamamlamanız gerekir."),
		frappe.ValidationError,
	)


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


def _variant_row_snapshot(row_name):
	"""Listing Variant Item satırını sepet anlık görüntüsü sözlüğüne çevir.

	Eski kod olmayan bir "Listing Variant" doctype'ından `variant_name / price /
	primary_image / stock_qty` okuyordu (MOGEM-665 · 1. aşama). Aynı anahtar
	adları döndürülür ki çağıranlar değişmesin; `listing_variant` gerçek bir
	satır adı değilse (eski sentetik kimlikler gibi) None döner.
	"""
	if not row_name:
		return None
	row = frappe.db.get_value(
		"Listing Variant Item",
		{"name": row_name, "parenttype": "Listing"},
		[
			"attribute_type",
			"attribute_value",
			"attribute_type_2",
			"attribute_value_2",
			"variant_price",
			"variant_image",
			"variant_stock",
		],
		as_dict=True,
	)
	if not row:
		return None
	parcalar = [f"{row.attribute_type}: {row.attribute_value}"] if row.attribute_value else []
	if row.attribute_value_2:
		parcalar.append(f"{row.attribute_type_2}: {row.attribute_value_2}")
	return frappe._dict(
		variant_name=" | ".join(parcalar),
		price=row.variant_price,
		primary_image=row.variant_image,
		stock_qty=row.variant_stock,
	)


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


def _recompute_order_items_server_side(products):
	"""
	Sipariş oluşturulurken her item için fiyatı sunucuda yeniden hesaplar —
	client'tan gelen ``unit_price`` ve ``total_price`` değerleri kabul edilmez
	(price tampering koruması).

	Args:
	    products: Client'ın gönderdiği `[{listing, listing_variant, variation,
	              variant_label, quantity, ...}, ...]` listesi.

	Returns:
	    list of dict: [{
	        "p": orijinal item (kalan field'lar için),
	        "listing_doc": Listing doc,
	        "server_unit_price": float,
	        "server_total_price": float,
	        "quantity": int,
	    }, ...]

	Raises:
	    frappe.ValidationError: Listing bulunamazsa, quantity geçersizse veya
	                            fiyat hesaplanamazsa.
	"""
	recomputed = []
	for p in products:
		listing_name = p.get("listing")
		if not listing_name or not frappe.db.exists("Listing", listing_name):
			frappe.throw(_("Geçersiz ürün: {0}").format(listing_name or "(boş)"), frappe.DoesNotExistError)

		try:
			qty = int(p.get("quantity", 1))
		except (TypeError, ValueError):
			frappe.throw(_("Geçersiz miktar"))
		if qty < 1:
			frappe.throw(_("Geçersiz miktar"))

		listing_doc = frappe.get_cached_doc("Listing", listing_name)

		# Sample (numune) satırı kontrolü — frontend payload'da `is_sample`
		# truthy ise fiyat `listing.sample_price`'tan çekilir. Aksi halde
		# selling_price üzerinden hesaplanır ve numune ~5x overcharge olur.
		is_sample = bool(p.get("is_sample"))
		if is_sample:
			sample_price = float(listing_doc.sample_price or 0)
			if sample_price <= 0:
				frappe.throw(_("Bu ürün için numune fiyatı tanımlı değil: {0}").format(listing_name))
			server_price = sample_price
		else:
			# variant_label hem `variation` hem `variant_label` field adıyla gelebilir
			variant_label = p.get("variant_label") or p.get("variation") or ""
			server_price = _get_variant_price_by_label(
				listing_name, variant_label
			) or _get_listing_effective_price(listing_doc)
			if server_price is None or float(server_price) < 0:
				frappe.throw(_("Ürün fiyatı hesaplanamadı: {0}").format(listing_name))

		unit_price = flt(server_price, 2)
		recomputed.append(
			{
				"p": p,
				"listing_doc": listing_doc,
				"server_unit_price": unit_price,
				"server_total_price": flt(unit_price * qty, 2),
				"quantity": qty,
				"is_sample": is_sample,
			}
		)
	return recomputed


def _get_discount_factor(listing):
	"""
	Listing'in aktif kampanya indirim faktörünü döndürür.
	`listing.discount_percentage > 0` ise (1 - dp/100), değilse 1.0.

	`listing` dict veya doc olabilir (her ikisinde de attribute access çalışır).
	api/listing.py:get_listing_detail içindeki _apply_discount ile aynı semantik —
	tier'lara ve listing seviyesi fiyatlara uygulanır, variant_price'a uygulanmaz
	(varyant fiyatı kullanıcı override'ı, kampanyadan bağımsız sabit kalır).
	"""
	dp = (
		listing.get("discount_percentage")
		if hasattr(listing, "get")
		else getattr(listing, "discount_percentage", 0)
	)
	dp = flt(dp or 0, 2)
	return (1 - dp / 100) if dp > 0 else 1.0


def _get_listing_effective_price(listing):
	"""
	Listing seviyesindeki "müşteriye gösterilen" birim fiyatı döndürür:
	selling_price (yoksa base_price) × discount_factor, 2 ondalık.

	get_listing_detail'daki `_apply_discount(listing.selling_price)` ile birebir
	aynı sonucu üretir; cart akışı (add_to_cart snapshot, _build_cart_response,
	merge_guest_cart) bunu kullanarak ürün detay sayfası ile tutarlı kalır.
	"""
	base = flt(
		(listing.get("selling_price") if hasattr(listing, "get") else getattr(listing, "selling_price", 0))
		or (listing.get("base_price") if hasattr(listing, "get") else getattr(listing, "base_price", 0))
		or 0,
		2,
	)
	factor = _get_discount_factor(listing)
	return flt(base * factor, 2)


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
		else:
			# Belirtilen varyant bulunamadı — base stock'a sessiz fallback tehlikeli,
			# hata ver (olmayan varyant için sipariş oluşmasını engeller).
			frappe.throw(_("Seçilen varyant bulunamadı: {0}").format(variant_label))

	if available is None and listing_variant:
		# 2) Varyant satırı (Listing Variant Item child row adı). MOGEM-665 · 1.
		# aşama: eskiden olmayan "Listing Variant" doctype'ı okunuyor, boş dönüp
		# ürün seviyesi stoğa düşüyordu — stoğu 0 olan beden sepete giriyordu.
		# Satır bu ürüne ait olmalı; stoğu 0 da geçerli bir cevaptır (>0 değil).
		variant_row = frappe.db.get_value(
			"Listing Variant Item",
			{"name": listing_variant, "parent": listing_name, "parenttype": "Listing"},
			["variant_stock"],
			as_dict=True,
		)
		if variant_row:
			available = float(variant_row.variant_stock or 0)

	if available is None:
		# 3) Listing seviyesi stok — available_qty (= stock_qty - reserved_qty) tercih edilir
		_aq = getattr(listing_doc, "available_qty", None)
		available = float(_aq if _aq is not None else (listing_doc.stock_qty or 0))

	if total_qty > available:
		if available <= 0:
			frappe.throw(_("Bu üründen yeterli stok bulunmamaktadır."))
		else:
			frappe.throw(
				_("Bu üründen bu kadar stok yok. En fazla {0} adet eklenebilir.").format(int(available))
			)


def _sku_gorsellerini_cevir(sellers_map: dict, sku_basliklari: dict[str, str | None]) -> None:
	"""`skuImage`'ları okunur adrese çevirir — tüm sepet için TEK kod sorgusu (spec §5.3).

	`snapshot_image` ve varyant görseli DB'de olduğu gibi kalır; yalnız yanıt değişir.
	"""
	from tradehub_core.media import seo_url

	skular = [
		sku
		for seller in sellers_map.values()
		for product in seller["products"].values()
		for sku in product["skus"]
		if sku.get("skuImage")
	]
	codes = seo_url.codes_for([sku["skuImage"] for sku in skular])
	for sku in skular:
		sku["skuImage"] = seo_url.seo_image_url(sku["skuImage"], sku_basliklari.get(sku["id"]), codes)


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
	# SEO'lu görsel adresi için SKU → ilan başlığı (ilan silinmişse satırdaki ad).
	sku_basliklari: dict[str, str | None] = {}

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
				"discount_percentage",
				"min_order_qty",
				"sell_in_moq_multiples",
				"currency",
				"status",
				"track_inventory",
				"allow_backorders",
				"stock_qty",
				"available_qty",
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
				["seller_name", "seller_code", "logo", "user"],
				as_dict=True,
			)
			if not seller:
				continue
			slug = seller.seller_code or seller_id
			# Sprint 2.6: KYB Verified Seller rolüne göre — listing serializer'la tutarlı
			# (api/listing.py:_format_listing_card aynı pattern). Frontend Cart/Checkout
			# gating'i bu flag'e bakar.
			seller_kyb_verified = bool(seller.user and "Verified Seller" in frappe.get_roles(seller.user))
			sellers_map[seller_id] = {
				"id": seller_id,
				"name": seller.seller_name or seller_id,
				"href": f"/pages/seller.html?id={slug}",
				"selected": True,
				"sellerKybVerified": seller_kyb_verified,
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
				# Tier fiyatlarına da kampanya indirimi uygulanır (listing detayıyla
				# tutarlılık için — get_listing_detail tier'larda _apply_discount yapıyor).
				tier_factor = _get_discount_factor(listing)
				price_tiers = [
					{
						"minQty": t.min_qty,
						"maxQty": t.max_qty or None,
						"price": flt(flt(t.price) * tier_factor, 2),
					}
					for t in tiers
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
			# Numune satırlarında snapshot fiyatı (sample_price) referans alınır;
			# numune fiyatı kampanya indirimine TABİ DEĞİL — ayrı fiyat noktası.
			if row_is_sample:
				base_price = flt(item.snapshot_price or listing.sample_price or 0, 2)
			else:
				# Listing seviyesi fiyat: selling_price × discount_factor.
				# Kampanya indirimi listing detayında uygulandığı için cart'ta da
				# uygulanır; aksi halde mini cart / cart sayfası 499 görür ama
				# ürün detayı 383.08 gösterir (tutarsız).
				base_price = _get_listing_effective_price(listing)
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
				# Varyant satırı (Listing Variant Item) — olmayan "Listing Variant"
				# doctype'ı yerine (MOGEM-665 · 1. aşama).
				variant = _variant_row_snapshot(item.listing_variant)
				if variant:
					variant_text = variant.variant_name or ""
					if variant.primary_image:
						sku_image = variant.primary_image
					if variant.price:
						base_price_addon = flt(flt(variant.price) - base_price, 2)
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
								base_price_addon = flt(flt(iv.variant_price) - base_price, 2)

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
						_aq = getattr(listing, "available_qty", None)
						max_qty = max(0, int(_aq if _aq is not None else (listing.stock_qty or 0)))
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
			sku_basliklari[item.name] = listing.title
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
			sku_basliklari[item.name] = listing.title if listing else item.snapshot_title
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

	_sku_gorsellerini_cevir(sellers_map, sku_basliklari)

	suppliers = []
	for seller_data in sellers_map.values():
		suppliers.append(
			{
				"id": seller_data["id"],
				"name": seller_data["name"],
				"href": seller_data["href"],
				"selected": seller_data["selected"],
				"sellerKybVerified": seller_data.get("sellerKybVerified", False),
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

	return _build_cart_response(cart_name)


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
		["status", "stock_qty", "available_qty", "track_inventory", "allow_backorders", "sample_price"],
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
			"available_qty",
			"track_inventory",
			"allow_backorders",
			"seller_profile",
			"title",
			"primary_image",
			"selling_price",
			"base_price",
			"discount_percentage",
			"currency",
			"sample_price",
		],
		as_dict=True,
	)
	if listing_doc.status != "Active":
		frappe.throw(_("Bu ürün şu an satışta değil"))

	# Sprint 2.6 (revised): KYC gate'i sepete eklemeden create_order'a taşındı.
	# Kullanıcı sepeti doldurabilir + checkout'u tamamlayabilir; gate ödeme anında çalışır.

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

	# Snapshot verisi hazırla — listing detay sayfasıyla tutarlı olmak için
	# kampanya indirimi (discount_percentage) selling_price'a uygulanır.
	snap_price = _get_listing_effective_price(listing_doc)
	snap_image = listing_doc.primary_image or ""
	snap_title = listing_doc.title or ""
	snap_currency = listing_doc.currency or "USD"
	seller_id = listing_doc.seller_profile or None

	if is_sample_flag:
		# Numune fiyatını snapshot olarak yaz; tier/kampanya hesabı devreye girmesin.
		snap_price = float(listing_doc.sample_price or 0)

	if listing_variant and not is_sample_flag:
		var_snap = _variant_row_snapshot(listing_variant)
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

	return _build_cart_response(cart_name)


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
			["stock_qty", "available_qty", "track_inventory", "allow_backorders"],
			as_dict=True,
		)
		if listing_doc:
			_check_stock(
				listing_doc, listing_name, listing_variant_name, qty, variant_label=variant_label_value
			)

	frappe.db.set_value("Cart Item", cart_item, "quantity", qty)
	frappe.db.commit()

	return {"success": True}


@frappe.whitelist()
def remove_cart_item(cart_item):
	"""Remove a single item from cart."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmanız gerekiyor"), frappe.AuthenticationError)

	_verify_cart_item_owner(cart_item, user)
	frappe.delete_doc("Cart Item", cart_item, ignore_permissions=True)
	frappe.db.commit()

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
			# Snapshot verisi hazırla — listing detayıyla tutarlı kampanya indirimi
			# uygulanır (discount_percentage); variant override'ları altta öncelikli.
			listing_snap = (
				frappe.db.get_value(
					"Listing",
					listing,
					[
						"seller_profile",
						"title",
						"primary_image",
						"selling_price",
						"base_price",
						"discount_percentage",
						"currency",
					],
					as_dict=True,
				)
				or {}
			)
			snap_price = _get_listing_effective_price(listing_snap)
			snap_image = listing_snap.get("primary_image") or ""
			snap_currency = listing_snap.get("currency") or "USD"
			if listing_variant:
				var_snap = _variant_row_snapshot(listing_variant)
				if var_snap:
					if var_snap.primary_image:
						snap_image = var_snap.primary_image
					if var_snap.price:
						# Variant fiyatı kampanyaya tabi değil — kullanıcı override'ı
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

	return _build_cart_response(cart_name)


_COUPON_FIELDS = [
	"name",
	"code",
	"coupon_type",
	"value",
	"min_order",
	"max_uses",
	"used_count",
	"description",
	"expires_at",
]
def _sepet_gorselleri(user: str) -> dict[tuple[str, str], str]:
	"""`{(ilan, varyant): snapshot_image}` — kullanıcının aktif sepetinden TEK sorgu.

	`snapshot_image` `add_to_cart`'ta sunucuda türetilir (ana ya da varyant
	görseli, içerik-kodlu); sipariş satırı için istemci adresinden güvenilirdir.
	"""
	sepet = frappe.db.get_value("Cart", {"buyer": user, "status": "Active"}, "name")
	if not sepet:
		return {}
	gorseller: dict[tuple[str, str], str] = {}
	for r in frappe.get_all(
		"Cart Item",
		filters={"parent": sepet},
		fields=["listing", "listing_variant", "snapshot_image"],
		order_by="creation asc",
	):
		if r.snapshot_image:
			gorseller.setdefault((r.listing or "", r.listing_variant or ""), r.snapshot_image)
	return gorseller


def _siparis_kalemi_gorseli(p: dict, sepet_gorselleri: dict[tuple[str, str], str]) -> str:
	"""`Order Item.image`: sepetteki sunucu snapshot'ı, yoksa normalize edilmiş istemci adresi."""
	from tradehub_core.media import seo_cikti

	anahtar = (p.get("listing") or "", p.get("listing_variant") or "")
	return sepet_gorselleri.get(anahtar) or seo_cikti.to_storage_url(p.get("image") or "")


def _normalize_coupon_code(code) -> str:
	return str(code or "").strip().upper()


def _get_active_coupon(code, for_update: bool = False):
	return frappe.db.get_value(
		"Coupon",
		{"code": _normalize_coupon_code(code), "is_active": 1},
		_COUPON_FIELDS,
		as_dict=True,
		for_update=for_update,
	)


def _user_coupon_usage(user: str, code: str, locking: bool = False) -> int:
	if not locking:
		return frappe.db.count(
			"Order",
			{"buyer": user, "coupon_code": code, "status": ["not in", ["İptal Edildi"]]},
		)
	# REPEATABLE READ'de düz okuma işlemin başındaki anlık görüntüyü görür: kupon
	# kilidini bekleyen ikinci istek, ilkinin az önce commit'lediği siparişi GÖREMEZ
	# ve kişi başı kural delinir. Kilitli okuma en güncel commit'i okur; buyer_index
	# sayesinde yalnız bu alıcının sipariş aralığını kilitler (ölçüldü 28 Eyl, EXPLAIN).
	return frappe.db.sql(
		"""SELECT COUNT(*) FROM `tabOrder`
		WHERE buyer = %s AND coupon_code = %s AND IFNULL(status, '') != 'İptal Edildi'
		LOCK IN SHARE MODE""",
		(user, code),
	)[0][0]


def _coupon_rejection(coupon, code: str, order_total=None, user: str | None = None, locking: bool = False):
	"""Kuponun kullanılamama sebebi — (sebep_kodu, kullanıcı mesajı) ya da None.

	Kupon kurallarının TEK kaynağı: validate_coupon, sipariş ve kupon listesi aynı
	kuralları aynı sırayla uygular (üç ayrı kopya birbirinden sapmıştı — MOGEM-685).
	`order_total` None ise minimum tutar, `user` None ise kişi başı kural atlanır.
	`locking` yalnız sipariş anında (kupon satırı kilitliyken) verilir.
	"""
	if coupon.expires_at and coupon.expires_at < datetime.date.today():
		return "expired", _("Bu kuponun süresi dolmuş")
	if int(coupon.max_uses or 0) > 0 and int(coupon.used_count or 0) >= int(coupon.max_uses):
		return "exhausted", _("Bu kupon maksimum kullanım sayısına ulaştı")
	min_order = flt(coupon.min_order or 0, 2)
	if order_total is not None and min_order > 0 and flt(order_total, 2) < min_order:
		return "min_order", _("Bu kupon için minimum sipariş tutarı: {0}").format(min_order)
	# F-024: aynı kullanıcı aynı kuponu ikinci kez kullanamaz
	if user and user != "Guest" and _user_coupon_usage(user, code, locking) > 0:
		return "used_by_user", _("Bu kuponu daha önce kullandınız")
	return None


def _coupon_discount(coupon, product_total: float, shipping_total: float = 0.0) -> float:
	"""İndirim tutarı — ön yüzün gösterdiğiyle AYNI kural (alpine/checkout.ts).

	percent/fixed yalnız ürün toplamına uygulanır ve onu aşamaz; `shipping` kuponu
	kargo ücretini düşer, kupon değeri yok sayılır. Eskiden taban ürün+kargoydu ve
	`shipping` tanınmıyordu: %10'da ekran 930, tahsil 927; ücretsiz kargoda ekran
	1.000, tahsil 1.030 (MOGEM-685 Adım 3, ölçüldü 28 Eyl 2026).
	"""
	product_total = max(0.0, flt(product_total or 0, 2))
	kind = str(coupon.coupon_type or "").lower()
	if kind == "shipping":
		return max(0.0, flt(shipping_total or 0, 2))
	value = flt(coupon.value or 0, 2)
	discount = product_total * value / 100.0 if kind.startswith("percent") else value
	return flt(max(0.0, min(discount, product_total)), 2)


def _split_coupon_discount(total: float, weights: list[float]) -> list[float]:
	"""İndirimi siparişlere tabanları oranında böler; kuruş farkı sonuncuya.

	Eskiden eşit bölünüyordu: 100 ₺ ve 900 ₺'lik iki siparişte 300 ₺ indirimin
	150'si küçük siparişe düşüp toplamı eksiye götürüyordu.
	"""
	toplam = sum(weights)
	if total <= 0 or toplam <= 0:
		return [0.0] * len(weights)
	payler = [flt(total * w / toplam, 2) for w in weights]
	payler[-1] = flt(total - sum(payler[:-1]), 2)
	return payler


def _reserve_coupon(
	coupon_code: str, product_total: float, shipping_total: float, user: str
) -> tuple[str, float]:
	"""Kuponu sipariş işlemi içinde AYIRIR → (normalize kod, indirim tutarı).

	C6: indirim SERVER'da koddan hesaplanır; client'ın `coupon_discount`'u yok sayılır.
	F-02 (MOGEM-685): kupon satırı kilitli okunur, kurallar kilit altında uygulanır
	ve sayaç aynı kilit altında artırılır. Kilit create_order'ın tek commit'ine kadar
	sürer; aynı kuponla gelen eşzamanlı sipariş bekler ve güncel sayacı görür
	(eskiden iki istek de used_count=0 görüp ikisi de indirim alıyordu). Sipariş
	sonradan düşerse işlem geri alınır, sayaç da geri döner.

	Kural tutmazsa sipariş REDDEDİLİR — sessizce indirimsiz sipariş oluşmaz; alıcı
	ekranda indirimli fiyatı görmüştü (kullanıcı kararı, 28 Eyl 2026).
	"""
	code = _normalize_coupon_code(coupon_code)
	product_total = max(0.0, flt(product_total or 0, 2))
	coupon = _get_active_coupon(code, for_update=True)
	red = (
		# Minimum tutar kargo HARİÇ ürün toplamına bakar — ön yüz de öyle doğruluyor.
		_coupon_rejection(coupon, code, product_total, user, locking=True)
		if coupon
		else ("not_found", _("Geçersiz veya süresi dolmuş kupon kodu"))
	)
	if red:
		frappe.throw(
			_("{0} — sipariş oluşturulmadı; kuponu kaldırıp yeniden deneyin.").format(red[1]),
			frappe.ValidationError,
		)
	discount = _coupon_discount(coupon, product_total, shipping_total)
	if discount > 0:
		frappe.db.sql(
			"UPDATE `tabCoupon` SET used_count = COALESCE(used_count, 0) + 1 WHERE name = %s",
			(coupon.name,),
		)
	return code, discount


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

	# Sprint 2.6 — KYC Gate: Alıcı KYC Verified değilse sipariş veremez.
	_ensure_buyer_kyc_verified(user)

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

	# Geçiş 1: Tüm siparişlerin item fiyatlarını sunucu-tarafında yeniden hesapla
	# (price tampering korumasi). Client'ın gönderdiği unit_price/total_price/subtotal
	# DİKKATE ALINMAZ — gerçek fiyat listing/variant'tan üretilir.
	from tradehub_core.api.currency import _get_exchange_rate

	prepared_orders = []
	for o in orders_data:
		if not o.get("products"):
			continue
		recomputed_items = _recompute_order_items_server_side(o["products"])
		server_subtotal = sum(it["server_total_price"] for it in recomputed_items)

		# Sipariş para birimi = listing'in NATIVE para birimi (client'ın seçtiği
		# görüntüleme para birimi DEĞİL). Recompute zaten native fiyat üretiyor;
		# etiketi de native tutmak "ödenen ≠ görülen" hatasını engeller. Tek
		# satıcının tüm ürünleri aynı native currency'de olmalı — aksi halde
		# server_subtotal taban-karışık (anlamsız) bir toplam olur.
		native_currencies = {(it["listing_doc"].get("currency") or "USD") for it in recomputed_items}
		if len(native_currencies) > 1:
			frappe.throw(
				_("Bu satıcının ürünleri farklı para birimlerinde; tek siparişte birleştirilemez")
			)
		native_currency = next(iter(native_currencies))

		# C7 fix — kargo ücreti client'tan gelir; negatif değer toplam'ı düşürmek için
		# istismar edilebilir. Negatifi reddet (server-side tarife hesabı ayrı iş — bkz. rapor).
		# F-023: Üst sınır kontrolü eklendi — sıfır kargo istismarını azaltır.
		raw_shipping = float(o.get("shipping_fee", 0) or 0)
		if raw_shipping < 0:
			frappe.throw(_("Geçersiz kargo ücreti"), frappe.ValidationError)
		_MAX_SHIPPING_FEE = 50000  # TRY — makul üst sınır (TODO: server-side tarife hesabı)
		if raw_shipping > _MAX_SHIPPING_FEE:
			frappe.throw(_("Geçersiz kargo ücreti"), frappe.ValidationError)
		# Kargo, client'tan görüntüleme para biriminde geliyor; sipariş native
		# para biriminde saklandığı için native'e çevir (tutar ile etiket uyumlu kalsın).
		display_currency = o.get("currency") or native_currency
		if display_currency != native_currency and raw_shipping > 0:
			server_shipping = round(
				raw_shipping * _get_exchange_rate(display_currency, native_currency), 2
			)
		else:
			server_shipping = raw_shipping

		prepared_orders.append(
			{
				"order_data": o,
				"recomputed": recomputed_items,
				"subtotal": server_subtotal,
				"shipping_fee": server_shipping,
				"currency": native_currency,
			}
		)

	# C6 fix — kupon indirimi SERVER'da koddan hesaplanır; client'ın gönderdiği
	# `coupon_discount` parametresi YOK SAYILIR (bedava sipariş istismarı engeli).
	product_total = sum(po["subtotal"] for po in prepared_orders)
	shipping_total = sum(po["shipping_fee"] for po in prepared_orders)
	# Kupon siparişlerden ÖNCE ayrılır (kilit + kural + sayaç); siparişe normalize kod
	# yazılır ki kişi başı sayım "  kod" gibi varyantlarla atlatılamasın.
	coupon_code, coupon_discount_val = (
		_reserve_coupon(coupon_code, product_total, shipping_total, user) if coupon_code else ("", 0.0)
	)

	created_orders = []
	# Ürünlü siparişleri filtrele — kuruş farkı son geçerli siparişe atanmalı
	valid_orders = [po for po in prepared_orders if po["order_data"].get("products")]
	# İndirim her siparişin KENDİ tabanı oranında dağıtılır: kargo kuponunda kargo
	# ücretine, diğerlerinde ürün tutarına (kupon hangi tabana uygulandıysa o).
	kargo_kuponu = bool(coupon_code) and (
		str(frappe.db.get_value("Coupon", coupon_code, "coupon_type") or "").lower() == "shipping"
	)
	indirim_paylari = _split_coupon_discount(
		coupon_discount_val,
		[po["shipping_fee"] if kargo_kuponu else po["subtotal"] for po in valid_orders],
	)
	# Görsel sunucudan: sepet satırının snapshot'ı; yoksa istemcinin gönderdiği
	# (okunur olabilir) adres içerik-kodlu biçime çevrilir (review I-1). Tek sorgu.
	sepet_gorselleri = _sepet_gorselleri(user)

	for idx, po in enumerate(valid_orders):
		order_data = po["order_data"]
		seller_id = order_data.get("seller_id", "")
		shipping_fee = po["shipping_fee"]
		# Native listing currency (FAZ 1 / K1) — client'ın display currency'si değil.
		currency = po["currency"]

		subtotal = po["subtotal"]
		discount = indirim_paylari[idx]
		total = subtotal + shipping_fee - discount

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
		order_doc.coupon_discount = discount
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

		# Item append: unit_price/total_price/quantity sunucu-recompute'tan gelir,
		# client değerleri kullanılmaz.
		for it in po["recomputed"]:
			p = it["p"]
			# listing_variant artık Data alanı — sentetik ID'leri (LST-XXXXX-Tip-Değer) olduğu gibi sakla
			lv = p.get("listing_variant") or None
			order_doc.append(
				"items",
				{
					"listing": p.get("listing"),
					"listing_title": p.get("listing_title", ""),
					"listing_variant": lv,
					"variation": p.get("variation", ""),
					"unit_price": it["server_unit_price"],
					"quantity": it["quantity"],
					"total_price": it["server_total_price"],
					"image": _siparis_kalemi_gorseli(p, sepet_gorselleri),
					"is_sample": 1 if it["is_sample"] else 0,
				},
			)

		order_doc.insert(ignore_permissions=True)
		# Stok rezervasyonu — sipariş oluşturulduğunda listing reserved_qty artır
		reserve_stock_for_order(order_doc.name)
		# Instant payment (kredi kartı/gateway): ödeme zaten alındı → stoku
		# fiziksel olarak da düş. Aksi halde reserved_qty sonsuza dek şişer
		# (havalede submit_remittance bekler ama instant'ta o akış yok).
		if pm in INSTANT_PAYMENT_METHODS:
			deduct_stock_for_order(order_doc.name)

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
@rate_limit(max_calls=10, window_seconds=300, per_user=True)
def validate_coupon(code, order_total=0):
	"""
	Kupon kodunu doğrular ve indirim bilgisini döndürür.
	F-052: Rate limit eklendi (10/5dk). Guest brute-force'u engeller.
	"""
	if not code:
		frappe.throw(_("Kupon kodu boş olamaz"))

	coupon = _get_active_coupon(code)
	if not coupon:
		frappe.throw(_("Geçersiz veya süresi dolmuş kupon kodu"))

	order_amount = flt(order_total or 0, 2)
	# Kişi başı kural da önizlemede uygulanır: sepette "geçerli" görünüp siparişte
	# reddedilmesin (misafirde atlanır — oturum yok).
	red = _coupon_rejection(coupon, _normalize_coupon_code(code), order_amount, frappe.session.user)
	if red:
		frappe.throw(red[1])

	# İndirim tutarını sipariş toplamı ile sınırla (HATA 26).
	# fixed type'ta gerçek değerin clamplenmiş hali döndürülür ki frontend
	# "ücretsiz değil" diye yanlış total göstermesin.
	value = flt(coupon.value or 0, 2)
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
	"""Oturumdaki alıcının KULLANABİLECEĞİ kupon sayısı — panodaki "Kuponlar: N".

	Kod DÖNMEZ (MOGEM-685 Adım 4): eskiden giriş yapan her alıcıya tüm aktif kupon
	kodlarını değer/açıklamasıyla veriyordu; ön yüz yalnız sayıyı kullanıyordu ve
	özel (fenomen, telafi) kuponlar herkese açık hâle geliyordu. Süresi dolmuş,
	sınırı dolmuş ve bu alıcının zaten kullandığı kuponlar sayılmaz.
	"""
	user = frappe.session.user
	# Kişi başı kullanım tek sorguda — kupon başına ayrı sayım yapılmaz.
	kullanilan = set(
		frappe.get_all(
			"Order",
			filters={"buyer": user, "coupon_code": ["!=", ""], "status": ["not in", ["İptal Edildi"]]},
			pluck="coupon_code",
		)
	)
	coupons = frappe.get_all("Coupon", filters={"is_active": 1}, fields=_COUPON_FIELDS)
	available = sum(1 for c in coupons if c.code not in kullanilan and not _coupon_rejection(c, c.code))
	return {"available": available}
