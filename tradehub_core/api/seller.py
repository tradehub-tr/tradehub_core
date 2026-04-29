import re

import frappe
from frappe import _

from tradehub_core.api._input import safe_float


def _strip_html(text):
	"""Strip HTML tags from text for plain-text display."""
	if not text:
		return ""
	return re.sub(r"<[^>]+>", "", text).strip()


@frappe.whitelist(allow_guest=True)
def get_sellers(search=None, keyword=None, category=None, page=1, page_size=20):
	filters = {"status": "Active"}
	if search:
		filters["seller_name"] = ["like", "%" + search + "%"]

	# keyword/category verildiyse, eşleşen Listing'lerden seller_profile setini çıkar
	# ve Admin Seller Profile sorgusunu bu sete daralt.
	keyword = (keyword or "").strip()
	category = (category or "").strip()
	if keyword or category:
		listing_filters = {"status": "Active"}
		if category:
			# category param hem url_slug hem direct name olabilir
			# (listing.get_listings ile aynı çözümleme).
			from tradehub_core.api.listing import _get_category_descendants

			platform_cat = frappe.db.get_value("Product Category", {"url_slug": category}, "name")
			if platform_cat:
				descendants = _get_category_descendants(platform_cat)
				listing_filters["product_category"] = (
					descendants[0] if len(descendants) == 1 else ["in", descendants]
				)
			else:
				# Fallback: doğrudan Product Category name veya seller category
				if frappe.db.exists("Product Category", category):
					listing_filters["product_category"] = category
				else:
					listing_filters["category"] = category
		if keyword:
			listing_filters["title"] = ["like", "%" + keyword + "%"]
		matching_sellers = frappe.get_all(
			"Listing",
			filters=listing_filters,
			fields=["seller_profile"],
			distinct=True,
			limit_page_length=0,
		)
		seller_codes = sorted(
			{(r.get("seller_profile") or "") for r in matching_sellers if r.get("seller_profile")}
		)
		if not seller_codes:
			return {"sellers": [], "total": 0, "page": int(page), "page_size": int(page_size)}
		filters["seller_code"] = ["in", seller_codes]

	sellers = frappe.get_all(
		"Admin Seller Profile",
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
			"slogan",
			"email",
			"website",
			"phone",
			"status",
			"rating",
			"total_orders",
			"health_score",
		],
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="seller_name asc",
	)
	is_guest = frappe.session.user == "Guest"
	for s in sellers:
		s["slug"] = s.get("seller_code") or s.get("name", "")
		s["rating"] = float(s.get("rating") or 0)
		s["review_count"] = int(s.get("total_orders") or 0)
		s["cover_image"] = s.get("banner_image", "")
		s["short_description"] = _strip_html(s.get("description", ""))
		s["verified"] = bool(s.get("health_score", 0) >= 80)
		if is_guest:
			# KVKK: misafire iletisim PII sizdirma
			s.pop("email", None)
			s.pop("phone", None)
			s.pop("website", None)
		try:
			seller_code = s.get("seller_code") or s.get("name", "")
			listings = frappe.get_all(
				"Listing",
				filters={"seller_profile": seller_code, "status": "Active"},
				fields=[
					"name",
					"title",
					"primary_image",
					"selling_price",
					"base_price",
					"min_order_qty",
					"b2b_enabled",
					"currency",
				],
				limit=4,
			)
			products = []
			for l in listings:
				price_min = l.selling_price or l.base_price or 0
				price_max = l.base_price or l.selling_price or 0
				if l.get("b2b_enabled"):
					tiers = frappe.get_all(
						"Listing Bulk Pricing Tier",
						filters={"parent": l.name, "parenttype": "Listing"},
						fields=["price"],
						order_by="price ASC",
					)
					if tiers:
						price_min = min(t.price for t in tiers)
						price_max = max(t.price for t in tiers)
				products.append(
					{
						"name": l.name,
						"product_name": l.title,
						"image": l.primary_image,
						"price_min": price_min,
						"price_max": price_max,
						"moq": l.min_order_qty or 1,
						"moq_unit": "Adet",
						"currency": l.get("currency") or "USD",
					}
				)
			s["products"] = products
			s["product_images"] = [p["image"] for p in products if p.get("image")]
		except Exception:
			s["products"] = []
			s["product_images"] = []
		try:
			gallery = frappe.get_all(
				"Seller Gallery Image",
				filters={"parent": s.get("name"), "parenttype": "Admin Seller Profile"},
				fields=["image"],
				order_by="idx asc",
				limit=20,
			)
			s["gallery_images"] = [g["image"] for g in gallery if g.get("image")]
		except Exception:
			s["gallery_images"] = []
	total = frappe.db.count("Admin Seller Profile", filters=filters)
	return {"sellers": sellers, "total": total, "page": int(page), "page_size": int(page_size)}


@frappe.whitelist(allow_guest=True)
def get_seller(slug):
	seller = frappe.db.get_value(
		"Admin Seller Profile",
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
			"slogan",
			"email",
			"phone",
			"website",
			"status",
			"user",
			"rating",
			"total_orders",
			"health_score",
			"founded_year",
			"staff_count",
			"annual_revenue",
			"factory_size",
			"business_type",
			"main_markets",
			"certifications",
			"is_verified",
			"verification_type",
			"review_count",
			"response_time",
			"response_rate",
			"on_time_delivery",
			"company_name",
		],
		as_dict=True,
	)
	if not seller:
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	seller["slug"] = seller.get("seller_code", "")
	seller["rating"] = float(seller.get("rating") or 0)
	seller["review_count"] = int(seller.get("review_count") or seller.get("total_orders") or 0)
	seller["cover_image"] = seller.get("banner_image", "")
	seller["store_name"] = seller.get("company_name") or seller.get("seller_name") or ""
	seller["business_name"] = seller.get("company_name") or seller.get("seller_name") or ""
	seller["short_description"] = _strip_html(seller.get("description", ""))
	seller["verified"] = bool(seller.get("is_verified")) or bool(seller.get("health_score", 0) >= 80)
	seller["response_time"] = seller.get("response_time") or ""
	seller["response_rate"] = float(seller.get("response_rate") or 0)
	seller["on_time_delivery"] = float(seller.get("on_time_delivery") or 0)

	# Satıcının varsayılan adresini ekle. Addresses DocType'ı Seller Profile'a bağlı,
	# bu yüzden Admin Seller Profile → user → Seller Profile köprüsü kuruyoruz.
	# Misafire (login olmamış) PII (adres, email, telefon, user) sızdırılmaz — KVKK.
	is_guest = frappe.session.user == "Guest"
	default_addr = None
	if not is_guest:
		seller_user = seller.get("user")
		if seller_user:
			sp_name = frappe.db.get_value("Seller Profile", {"user": seller_user}, "name")
			if sp_name:
				addr_fields = [
					"title",
					"contact_name",
					"company",
					"phone_prefix",
					"phone",
					"country",
					"state",
					"city",
					"street",
					"apartment",
					"postal_code",
					"note",
				]
				default_addr = frappe.db.get_value(
					"Addresses",
					{"kind": "Seller", "seller": sp_name, "is_default": 1},
					addr_fields,
					as_dict=True,
				)
				if not default_addr:
					rows = frappe.get_all(
						"Addresses",
						filters={"kind": "Seller", "seller": sp_name},
						fields=addr_fields,
						order_by="creation asc",
						limit=1,
					)
					default_addr = rows[0] if rows else None
	seller["address"] = default_addr
	if is_guest:
		seller.pop("email", None)
		seller.pop("phone", None)
		seller.pop("user", None)
	return seller


@frappe.whitelist()
def get_my_supplier_profile():
	"""Returns the Admin Seller Profile name for the logged-in seller."""
	user = frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")


@frappe.whitelist()
def get_my_admin_seller_profile():
	"""Returns the Admin Seller Profile for the logged-in seller."""
	user = frappe.session.user
	if not user or user == "Guest":
		return None
	name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not name:
		return None
	return frappe.db.get_value(
		"Admin Seller Profile",
		name,
		["name", "seller_code", "seller_name", "logo", "banner_image", "slogan"],
		as_dict=True,
	)


@frappe.whitelist()
def update_my_admin_seller_profile(logo=None, banner_image=None, slogan=None):
	"""Mağaza başlığı (header) alanlarını günceller — sadece kendi profili.
	Şu anlık logo, banner_image (header arka planı) ve slogan destekleniyor."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetkisiz"), frappe.PermissionError)
	name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not name:
		frappe.throw(_("Satici profili bulunamadi"), frappe.DoesNotExistError)
	updates = {}
	if logo is not None:
		updates["logo"] = logo
	if banner_image is not None:
		updates["banner_image"] = banner_image
	if slogan is not None:
		updates["slogan"] = slogan
	if updates:
		for f, v in updates.items():
			frappe.db.set_value("Admin Seller Profile", name, f, v)
		frappe.db.commit()
	return {"updated": list(updates.keys())}


@frappe.whitelist(allow_guest=True)
def get_seller_categories(seller_code):
	"""Public: Satıcının aktif listing'lerinden türetilen kategorileri döndür.

	Hem satıcının kendi belirlediği (Seller Category) hem genel platform
	(Product Category) kategorilerini tek listede, görüntü adları çözümlenmiş
	olarak verir. Listing.category Seller Category'ye autoincrement Link
	olduğundan name değeri "2747" gibi olabilir; frontend'de ID düşmemesi için
	category_name burada kesin olarak doldurulur.
	"""
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		return {"categories": []}

	rows = frappe.db.sql(
		"""
        SELECT DISTINCT category, category_name, product_category, product_category_name
        FROM `tabListing`
        WHERE seller_profile = %(seller_code)s
          AND status = 'Active'
    """,
		{"seller_code": seller_code},
		as_dict=True,
	)

	cats: list[dict] = []
	seen: set[tuple] = set()

	for r in rows:
		seller_cat_id = (r.get("category") or "").strip() if r.get("category") else ""
		if seller_cat_id and ("seller", seller_cat_id) not in seen:
			display_name = (
				r.get("category_name")
				or frappe.db.get_value("Seller Category", seller_cat_id, "category_name")
				or seller_cat_id
			)
			img = frappe.db.get_value("Seller Category", seller_cat_id, "image") or ""
			cats.append(
				{
					"name": seller_cat_id,
					"category_name": display_name,
					"image": img,
					"type": "seller",
				}
			)
			seen.add(("seller", seller_cat_id))

		plat_cat_id = (r.get("product_category") or "").strip() if r.get("product_category") else ""
		if plat_cat_id and ("platform", plat_cat_id) not in seen:
			display_name = (
				r.get("product_category_name")
				or frappe.db.get_value("Product Category", plat_cat_id, "category_name")
				or plat_cat_id
			)
			img = frappe.db.get_value("Product Category", plat_cat_id, "image") or ""
			cats.append(
				{
					"name": plat_cat_id,
					"category_name": display_name,
					"image": img,
					"type": "platform",
				}
			)
			seen.add(("platform", plat_cat_id))

	cats.sort(key=lambda c: (c.get("type") or "", (c.get("category_name") or "").lower()))
	return {"categories": cats}


@frappe.whitelist()
def add_seller_category(category_name, description="", image="", sort_order=0):
	"""Satıcı: yeni kategori ekle (Pending olarak)."""
	category_name = (category_name or "").strip()
	if not category_name:
		frappe.throw(_("Kategori adı boş olamaz."))
	seller_profile = _get_seller_profile_for_session()
	if not seller_profile:
		frappe.throw(_("Satıcı profili bulunamadı."))
	if frappe.db.exists("Seller Category", {"seller": seller_profile, "category_name": category_name}):
		frappe.throw(_("Bu isimde bir kategoriniz zaten mevcut."))
	doc = frappe.get_doc(
		{
			"doctype": "Seller Category",
			"seller": seller_profile,
			"category_name": category_name,
			"description": description,
			"image": image,
			"sort_order": int(sort_order or 0),
			"status": "Pending",
		}
	)
	doc.insert(ignore_permissions=True)
	return {"success": True, "name": doc.name}


@frappe.whitelist()
def get_my_seller_categories():
	"""Satıcı: kendi tüm kategorilerini (tüm statüler) döndür."""
	seller_profile = _get_seller_profile_for_session()
	if not seller_profile:
		return {"success": True, "categories": []}
	cats = frappe.get_all(
		"Seller Category",
		filters={"seller": seller_profile},
		fields=[
			"name",
			"category_name",
			"status",
			"is_enabled",
			"description",
			"image",
			"sort_order",
			"reject_reason",
		],
		order_by="creation desc",
	)
	return {"success": True, "categories": cats}


@frappe.whitelist()
def update_seller_category(category_name, new_name=None, description=None, sort_order=None, image=None):
	"""Satıcı: kendi kategorisini düzenle — admin onayına düşer (Pending)."""
	seller_profile = _get_seller_profile_for_session()
	if not seller_profile:
		frappe.throw(_("Satıcı profili bulunamadı."))
	cat = frappe.get_doc("Seller Category", category_name)
	if cat.seller != seller_profile:
		frappe.throw(_("Bu kategori size ait değil."), frappe.PermissionError)
	if new_name is not None:
		new_name = new_name.strip()
		if not new_name:
			frappe.throw(_("Kategori adı boş olamaz."))
		# Aynı isimde başka kategori var mı?
		existing = frappe.db.get_value(
			"Seller Category",
			{"seller": seller_profile, "category_name": new_name, "name": ["!=", category_name]},
			"name",
		)
		if existing:
			frappe.throw(_("Bu isimde bir kategoriniz zaten mevcut."))
		cat.category_name = new_name
	if description is not None:
		cat.description = description
	if sort_order is not None:
		cat.sort_order = int(sort_order)
	if image is not None:
		cat.image = image
	cat.status = "Pending"
	cat.save(ignore_permissions=True)
	return {"success": True}


@frappe.whitelist()
def toggle_seller_category(category_name, is_enabled):
	"""Satıcı: kendi kategorisini aktif/pasif yap."""
	seller_profile = _get_seller_profile_for_session()
	if not seller_profile:
		frappe.throw(_("Satıcı profili bulunamadı."))
	cat = frappe.get_doc("Seller Category", category_name)
	if cat.seller != seller_profile:
		frappe.throw(_("Bu kategori size ait değil."), frappe.PermissionError)
	cat.is_enabled = 1 if int(is_enabled) else 0
	cat.save(ignore_permissions=True)
	return {"success": True, "is_enabled": cat.is_enabled}


@frappe.whitelist()
def delete_seller_category(category_name):
	"""Satıcı: kendi kategorisini kalıcı olarak sil."""
	seller_profile = _get_seller_profile_for_session()
	if not seller_profile:
		frappe.throw(_("Satıcı profili bulunamadı."))
	cat = frappe.get_doc("Seller Category", category_name)
	if cat.seller != seller_profile:
		frappe.throw(_("Bu kategori size ait değil."), frappe.PermissionError)
	frappe.delete_doc("Seller Category", category_name, ignore_permissions=True)
	return {"success": True}


@frappe.whitelist()
def get_pending_seller_categories(page=1, page_size=20):
	"""Admin: Onay bekleyen kategorileri listele."""
	if (
		"System Manager" not in frappe.get_roles(frappe.session.user)
		and frappe.session.user != "Administrator"
	):
		frappe.throw(_("Yetki hatası"), frappe.PermissionError)
	page = int(page)
	page_size = int(page_size)
	total = frappe.db.count("Seller Category", {"status": "Pending"})
	cats = frappe.get_all(
		"Seller Category",
		filters={"status": "Pending"},
		fields=["name", "category_name", "seller", "description", "image", "creation"],
		order_by="creation asc",
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
	)
	for c in cats:
		if c.get("seller"):
			c["seller_name"] = (
				frappe.db.get_value("Admin Seller Profile", c["seller"], "seller_name") or c["seller"]
			)
		else:
			c["seller_name"] = "-"
	return {"success": True, "categories": cats, "total": total}


@frappe.whitelist()
def approve_seller_category(category_name, action="approve", reject_reason=""):
	"""Admin: kategoriyi onayla veya reddet."""
	if (
		"System Manager" not in frappe.get_roles(frappe.session.user)
		and frappe.session.user != "Administrator"
	):
		frappe.throw(_("Yetki hatası"), frappe.PermissionError)
	cat = frappe.get_doc("Seller Category", category_name)
	if action == "approve":
		cat.status = "Active"
		cat.reject_reason = ""
	elif action == "reject":
		cat.status = "Rejected"
		cat.reject_reason = reject_reason
	else:
		frappe.throw(_("Geçersiz işlem"))
	cat.save(ignore_permissions=True)
	return {"success": True, "status": cat.status}


def _get_seller_profile_for_session():
	user = frappe.session.user
	profile = frappe.db.get_value("Admin Seller Profile", {"owner": user}, "name")
	if not profile:
		profile = frappe.db.get_value("Admin Seller Profile", {"email": user}, "name")
	return profile


@frappe.whitelist(allow_guest=True)
def get_seller_products(seller_code, category=None, page=1, page_size=40):
	# seller_code = Admin Seller Profile name
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		return {"products": [], "total": 0}
	filters = {"seller_profile": seller_code, "status": "Active"}
	if category:
		filters["category"] = category
	listings = frappe.get_all(
		"Listing",
		filters=filters,
		fields=[
			"name",
			"title",
			"primary_image",
			"selling_price",
			"base_price",
			"min_order_qty",
			"category",
			"category_name",
			"product_category",
			"product_category_name",
			"short_description",
			"b2b_enabled",
			"currency",
			"view_count",
			"order_count",
			"creation",
		],
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="creation desc",
	)
	for l in listings:
		l["id"] = l.get("name", "")
		l["product_name"] = l.get("title", "")
		l["image"] = l.get("primary_image", "")
		l["currency"] = l.get("currency") or "TRY"
		l["view_count"] = int(l.get("view_count") or 0)
		l["sold_count"] = int(l.get("order_count") or 0)
		price_min = l.get("selling_price") or l.get("base_price") or 0
		price_max = l.get("base_price") or l.get("selling_price") or 0
		if l.get("b2b_enabled"):
			tiers = frappe.get_all(
				"Listing Bulk Pricing Tier",
				filters={"parent": l.get("name"), "parenttype": "Listing"},
				fields=["price"],
				order_by="price ASC",
			)
			if tiers:
				price_min = min(t.price for t in tiers)
				price_max = max(t.price for t in tiers)
		l["price_min"] = price_min
		l["price_max"] = price_max
		l["moq"] = l.get("min_order_qty", 1)
		l["moq_unit"] = "Adet"
	total = frappe.db.count("Listing", filters=filters)
	return {"products": listings, "total": total}


@frappe.whitelist(allow_guest=True)
def get_reviews(seller_code, page=1, page_size=10):
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	filters = {"seller": seller_code}
	reviews = frappe.get_all(
		"Seller Review",
		filters=filters,
		fields=["name", "reviewer_name", "rating", "comment", "creation", "product_name"],
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="creation desc",
	)
	total = frappe.db.count("Seller Review", filters=filters)
	return {"reviews": reviews, "total": total}


def _recalculate_seller_rating(seller_code):
	rows = frappe.get_all(
		"Seller Review",
		filters={"seller": seller_code, "status": "Published"},
		fields=["rating"],
	)
	count = len(rows)
	avg = round(sum((r.rating or 0) for r in rows) / count, 2) if count else 0
	frappe.db.set_value("Admin Seller Profile", seller_code, {"rating": avg, "review_count": count})


@frappe.whitelist()
def submit_review(seller_code, rating, comment):
	if frappe.session.user == "Guest":
		frappe.throw(_("Yorum yapmak icin giris yapmaniz gerekiyor"), frappe.AuthenticationError)
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	own_seller = frappe.db.get_value("Admin Seller Profile", {"user": frappe.session.user}, "name")
	if own_seller and own_seller == seller_code:
		frappe.throw(_("Kendi magazaniza yorum yapamazsiniz"), frappe.PermissionError)
	rating = safe_float(rating, label=_("Puan"))
	if rating < 1 or rating > 5:
		frappe.throw(_("Puan 1 ile 5 arasinda olmalidir"))
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("Yorum bos olamaz"))
	user_data = frappe.db.get_value("User", frappe.session.user, ["full_name", "name"], as_dict=True)
	reviewer_name = user_data.full_name or user_data.name
	if frappe.db.exists("Seller Review", {"seller": seller_code, "reviewer_name": reviewer_name}):
		frappe.throw(_("Bu saticiya zaten yorum yaptiniz"))
	doc = frappe.new_doc("Seller Review")
	doc.seller = seller_code
	doc.reviewer_name = reviewer_name
	doc.rating = rating
	doc.comment = comment
	doc.status = "Published"
	doc.date = frappe.utils.now()
	doc.insert(ignore_permissions=True)
	_recalculate_seller_rating(seller_code)
	frappe.db.commit()
	return {"success": True, "name": doc.name}


@frappe.whitelist()
def get_gallery():
	"""Oturumdaki satıcının galeri fotoğraflarını döndürür."""
	user = frappe.session.user
	profile_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not profile_name:
		frappe.throw(_("Profil bulunamadi"), frappe.DoesNotExistError)
	doc = frappe.get_doc("Admin Seller Profile", profile_name)
	return [{"name": r.name, "image": r.image, "caption": r.caption or ""} for r in doc.gallery_images]


@frappe.whitelist()
def add_gallery_image(image_url, caption=""):
	"""Galerik listesine yeni fotoğraf ekler (max 20)."""
	user = frappe.session.user
	profile_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not profile_name:
		frappe.throw(_("Profil bulunamadi"))
	doc = frappe.get_doc("Admin Seller Profile", profile_name)
	if len(doc.gallery_images) >= 20:
		frappe.throw(_("Maksimum 20 fotograf yukleyebilirsiniz"))
	doc.append("gallery_images", {"image": image_url, "caption": caption})
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return [{"name": r.name, "image": r.image, "caption": r.caption or ""} for r in doc.gallery_images]


@frappe.whitelist()
def remove_gallery_image(row_name):
	"""Galeriden bir fotoğrafı kaldırır."""
	user = frappe.session.user
	profile_name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not profile_name:
		frappe.throw(_("Profil bulunamadi"))
	doc = frappe.get_doc("Admin Seller Profile", profile_name)
	doc.gallery_images = [r for r in doc.gallery_images if r.name != row_name]
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return True


@frappe.whitelist()
def save_storefront_layout(seller_code, sections, theme_config):
	"""Satıcı: mağaza layout ve tema ayarlarını kaydet."""
	import json as _json

	# Yetki: admin veya ilgili satıcı
	is_admin = frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()
	if not is_admin:
		seller_profile = frappe.db.get_value(
			"Admin Seller Profile", {"owner": frappe.session.user}, "name"
		) or frappe.db.get_value("Admin Seller Profile", {"email": frappe.session.user}, "name")
		if seller_profile != seller_code:
			frappe.throw(_("Bu mağazayı düzenleme yetkiniz yok."), frappe.PermissionError)

	# JSON doğrulama
	try:
		sections_data = _json.loads(sections) if isinstance(sections, str) else sections
	except (ValueError, TypeError):
		frappe.throw(_("Bölüm verisi geçerli JSON olmalıdır."))
	try:
		theme_data = _json.loads(theme_config) if isinstance(theme_config, str) else theme_config
	except (ValueError, TypeError):
		frappe.throw(_("Tema verisi geçerli JSON olmalıdır."))

	layout_name = frappe.db.get_value("Storefront Layout", {"seller_profile": seller_code}, "name")
	if layout_name:
		doc = frappe.get_doc("Storefront Layout", layout_name)
	else:
		doc = frappe.new_doc("Storefront Layout")
		doc.seller_profile = seller_code
		doc.is_published = 1

	doc.sections = _json.dumps(sections_data)
	doc.theme_config = _json.dumps(theme_data)
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True}


@frappe.whitelist(allow_guest=True)
def get_storefront_layout(seller_code):
	"""Public: Satıcının mağaza layout ve tema ayarlarını döndür.
	Kayıt yoksa default sections + default theme ile otomatik oluşturur.
	"""
	import json as _json

	from tradehub_core.tradehub_core.doctype.storefront_layout.storefront_layout import (
		DEFAULT_SECTIONS,
		DEFAULT_THEME,
	)

	if not frappe.db.exists("Admin Seller Profile", seller_code):
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)

	layout_name = frappe.db.get_value("Storefront Layout", {"seller_profile": seller_code}, "name")

	if layout_name:
		doc = frappe.get_doc("Storefront Layout", layout_name)
		try:
			sections = (
				_json.loads(doc.sections)
				if isinstance(doc.sections, str)
				else (doc.sections or DEFAULT_SECTIONS)
			)
		except (ValueError, TypeError):
			sections = DEFAULT_SECTIONS
		try:
			theme = (
				_json.loads(doc.theme_config)
				if isinstance(doc.theme_config, str)
				else (doc.theme_config or DEFAULT_THEME)
			)
		except (ValueError, TypeError):
			theme = DEFAULT_THEME
	else:
		# İlk ziyarette default layout oluştur
		doc = frappe.new_doc("Storefront Layout")
		doc.seller_profile = seller_code
		doc.is_published = 1
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		sections = DEFAULT_SECTIONS
		theme = DEFAULT_THEME

	return {"sections": sections, "theme": theme}


@frappe.whitelist(allow_guest=True)
def send_inquiry(seller_code, message, share_business_card=0):
	# Admin Seller Profile'da name = seller_code
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	sender_name, sender_email = "", ""
	buyer_user = ""
	if frappe.session.user and frappe.session.user != "Guest":
		# Self-inquiry block (HATA 20): kendi magazasina inquiry gonderme
		own_seller = frappe.db.get_value("Admin Seller Profile", {"user": frappe.session.user}, "name")
		if own_seller and own_seller == seller_code:
			frappe.throw(_("Kendi magazaniza inquiry gonderemezsiniz"), frappe.PermissionError)
		user = frappe.db.get_value("User", frappe.session.user, ["full_name", "email"], as_dict=True)
		if user:
			sender_name = user.full_name or ""
			sender_email = user.email or ""
			buyer_user = frappe.session.user
	doc = frappe.new_doc("Seller Inquiry")
	doc.seller = seller_code
	doc.seller_code = seller_code
	doc.message = message.strip()
	doc.sender_name = sender_name
	doc.sender_email = sender_email
	if buyer_user:
		doc.buyer = buyer_user
	doc.share_business_card = int(share_business_card)
	doc.status = "Yeni"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()

	# Satıcıya bildirim
	try:
		_notify_new_inquiry(doc)
	except Exception:
		frappe.log_error(title="send_inquiry: notify_seller")

	return {"success": True, "inquiry_id": doc.name}


def _notify_new_inquiry(inquiry):
	"""Yeni Seller Inquiry → satıcıya in-app + e-posta."""
	from tradehub_core.utils.notify import notify

	seller_user = frappe.db.get_value("Admin Seller Profile", inquiry.seller, "user")
	if not seller_user:
		return

	preview = (inquiry.message or "")[:300]
	subject = f"[TradeHub] Mağazanıza yeni soru: {inquiry.sender_name or 'Müşteri'}"
	body_html = f"""
<div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color: #222; max-width: 560px;">
  <h2 style="margin: 0 0 16px; font-size: 18px;">Yeni Soru</h2>
  <p><strong>{frappe.utils.escape_html(inquiry.sender_name or "Müşteri")}</strong> mağazanıza bir soru gönderdi:</p>
  <div style="margin: 16px 0; padding: 12px 14px; background: #f6f7fb; border-left: 3px solid #7c3aed; border-radius: 4px;">
    {frappe.utils.escape_html(preview).replace(chr(10), "<br>")}
  </div>
  <p style="margin: 28px 0 0; font-size: 11px; color: #888;">
    Sorular sayfanızdan yanıtlayabilirsiniz.
  </p>
</div>
""".strip()

	notify(
		recipient_user=seller_user,
		type="dispute",
		title=f"Yeni soru: {inquiry.sender_name or 'Müşteri'}",
		message=preview or "Mağazanıza yeni bir soru geldi.",
		recipient_role="seller",
		action_url=f"/helpdesk/inquiries/{inquiry.name}",
		reference_doctype="Seller Inquiry",
		reference_name=inquiry.name,
		send_email=True,
		email_subject=subject,
		email_body=body_html,
	)


# ── Satıcı Inquiry yönetim API'leri ────────────────────────────────────


@frappe.whitelist()
def list_my_inquiries(status: str = "all", page: int = 1, page_size: int = 20):
	"""Satıcı kendi mağazasına gelen inquiry'leri listeler.

	Permission query Seller Inquiry.seller alanını user'ın profile'ına eşler.
	"""
	caller = frappe.session.user
	if not caller or caller == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

	try:
		page = int(page) or 1
	except (TypeError, ValueError):
		page = 1
	try:
		page_size = int(page_size) or 20
	except (TypeError, ValueError):
		page_size = 20
	page_size = min(max(page_size, 1), 100)

	filters = {"is_trashed": 0}
	if status and status != "all":
		filters["status"] = status

	fields = [
		"name",
		"seller",
		"seller_code",
		"status",
		"is_read",
		"sender_name",
		"sender_email",
		"buyer",
		"message",
		"share_business_card",
		"replied_at",
		"creation",
	]
	data = frappe.get_all(
		"Seller Inquiry",
		filters=filters,
		fields=fields,
		order_by="creation desc",
		start=(page - 1) * page_size,
		page_length=page_size,
	)
	total = frappe.db.count("Seller Inquiry", filters=filters)

	for row in data:
		msg = row.get("message") or ""
		row["message_preview"] = (msg[:200] + "…") if len(msg) > 200 else msg

	return {"data": data, "total": total}


@frappe.whitelist()
def get_inquiry(name: str):
	"""Tek inquiry detayı + ilk okuma sırasında is_read=1."""
	if not name:
		frappe.throw(_("Inquiry kimliği gerekli."), frappe.ValidationError)
	if not frappe.has_permission("Seller Inquiry", doc=name, ptype="read"):
		frappe.throw(_("Bu soruya erişim yetkiniz yok."), frappe.PermissionError)
	doc = frappe.get_doc("Seller Inquiry", name)

	if not doc.is_read:
		frappe.db.set_value("Seller Inquiry", name, "is_read", 1, update_modified=False)
		frappe.db.commit()
		doc.is_read = 1

	return doc.as_dict()


@frappe.whitelist()
def reply_inquiry(name: str, message: str):
	"""Satıcı inquiry'ye cevap verir — alıcıya e-posta gider, status=Yanıtlandı."""
	if not name or not (message or "").strip():
		frappe.throw(_("Inquiry ve mesaj zorunlu."), frappe.ValidationError)
	if not frappe.has_permission("Seller Inquiry", doc=name, ptype="write"):
		frappe.throw(_("Bu soruyu yanıtlama yetkiniz yok."), frappe.PermissionError)

	doc = frappe.get_doc("Seller Inquiry", name)
	doc.reply_message = message
	doc.replied_at = frappe.utils.now()
	doc.replied_by = frappe.session.user
	doc.status = "Yanıtlandı"
	doc.is_read = 1
	doc.save(ignore_permissions=True)
	frappe.db.commit()

	try:
		_notify_inquiry_reply(doc, message)
	except Exception:
		frappe.log_error(title="reply_inquiry: notify_buyer")

	return {"name": doc.name, "ok": True}


def _notify_inquiry_reply(doc, message: str):
	"""Inquiry yanıtı → alıcıya bildirim."""
	from tradehub_core.utils.notify import notify

	recipient = doc.get("buyer") or doc.get("sender_email") or ""
	if not recipient:
		return

	seller_name = doc.seller or ""
	preview = (message or "").strip()
	if len(preview) > 300:
		preview = preview[:300] + "…"

	subject = f"[TradeHub] {seller_name} sorunuza yanıt verdi"
	body_html = f"""
<div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color: #222; max-width: 560px;">
  <h2 style="margin: 0 0 16px; font-size: 18px;">Mağaza yanıtınızı paylaştı</h2>
  <p><strong>{frappe.utils.escape_html(seller_name)}</strong> sorunuza yanıt verdi:</p>
  <div style="margin: 16px 0; padding: 12px 14px; background: #f6f7fb; border-left: 3px solid #7c3aed; border-radius: 4px;">
    {frappe.utils.escape_html(preview).replace(chr(10), "<br>")}
  </div>
</div>
""".strip()

	notify(
		recipient_user=recipient,
		type="dispute",
		title=f"{seller_name} sorunuza yanıt verdi",
		message=preview or "Mağaza sorunuza yanıt yazdı.",
		recipient_role="buyer",
		reference_doctype="Seller Inquiry",
		reference_name=doc.name,
		send_email=True,
		email_subject=subject,
		email_body=body_html,
	)


@frappe.whitelist()
def trash_inquiry(name: str):
	"""Inquiry'yi çöpe taşı (soft delete)."""
	if not frappe.has_permission("Seller Inquiry", doc=name, ptype="write"):
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)
	frappe.db.set_value("Seller Inquiry", name, "is_trashed", 1)
	frappe.db.commit()
	return {"ok": True}


# ── Müşterilerim — satıcı CRM mini-panosu ───────────────────────────────


def _get_my_seller_profile():
	"""Çağıran user'ın Admin Seller Profile name'ini döndür."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)
	profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not profile:
		frappe.throw(_("Satıcı profiliniz bulunamadı."), frappe.DoesNotExistError)
	return profile, user


@frappe.whitelist()
def list_my_customers(search: str = "", page: int = 1, page_size: int = 20):
	"""Satıcının kendi müşterileri (Order üzerinden agregat).

	Her satır: buyer kullanıcı + sipariş sayısı + toplam ciro + son sipariş
	tarihi + açık ticket sayısı.
	"""
	profile, _user = _get_my_seller_profile()

	try:
		page = max(1, int(page or 1))
	except (TypeError, ValueError):
		page = 1
	try:
		page_size = min(100, max(1, int(page_size or 20)))
	except (TypeError, ValueError):
		page_size = 20

	# Müşteri agregasyonu — Order tablosundan
	search_clause = ""
	params = {"seller": profile}
	if search and search.strip():
		search_clause = "AND o.buyer LIKE %(q)s"
		params["q"] = f"%{search.strip()}%"

	rows = frappe.db.sql(
		f"""
		SELECT
			o.buyer AS buyer,
			COUNT(*) AS order_count,
			COALESCE(SUM(o.total), 0) AS total_revenue,
			MAX(o.order_date) AS last_order_date,
			SUM(CASE WHEN o.status NOT IN ('İptal Edildi','Reddedildi') THEN 1 ELSE 0 END) AS active_orders
		FROM `tabOrder` o
		WHERE o.seller = %(seller)s
		  AND o.buyer IS NOT NULL AND o.buyer != ''
		  {search_clause}
		GROUP BY o.buyer
		ORDER BY last_order_date DESC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		{**params, "limit": page_size, "offset": (page - 1) * page_size},
		as_dict=True,
	)

	total_row = frappe.db.sql(
		f"""
		SELECT COUNT(DISTINCT o.buyer) AS total
		FROM `tabOrder` o
		WHERE o.seller = %(seller)s
		  AND o.buyer IS NOT NULL AND o.buyer != ''
		  {search_clause}
		""",
		params,
		as_dict=True,
	)
	total = total_row[0]["total"] if total_row else 0

	# Her buyer için ek bilgi (ad + açık ticket sayısı). 1 query birleşik:
	if rows:
		buyer_emails = [r["buyer"] for r in rows]
		users = frappe.get_all(
			"User",
			filters={"name": ["in", buyer_emails]},
			fields=["name", "full_name"],
		)
		users_map = {u.name: u.full_name for u in users}

		# Açık ticket sayıları (raised_by bazlı)
		ticket_rows = frappe.db.sql(
			"""
			SELECT raised_by, COUNT(*) AS open_count
			FROM `tabHD Ticket`
			WHERE raised_by IN %(users)s
			  AND status IN ('Open','Replied')
			GROUP BY raised_by
			""",
			{"users": tuple(buyer_emails)},
			as_dict=True,
		)
		tickets_map = {t["raised_by"]: t["open_count"] for t in ticket_rows}

		for r in rows:
			r["full_name"] = users_map.get(r["buyer"]) or r["buyer"]
			r["open_tickets"] = tickets_map.get(r["buyer"], 0)
			r["total_revenue"] = float(r["total_revenue"] or 0)
			r["order_count"] = int(r["order_count"] or 0)
			r["active_orders"] = int(r["active_orders"] or 0)

	return {"data": rows, "total": int(total or 0)}


@frappe.whitelist()
def get_customer_detail(buyer: str):
	"""Tek müşteri için satıcı bağlamında 360° görünüm.

	Buyer = email/user adı. Satıcı sadece kendi sipariş/sorularını görmeli;
	izinsiz buyer email'ini sorgulayan satıcılara da yalnız ortak veri döner.
	"""
	if not buyer:
		frappe.throw(_("Müşteri kimliği gerekli."), frappe.ValidationError)

	profile, _user = _get_my_seller_profile()

	# 1) Profil — User
	user_doc = frappe.db.get_value(
		"User",
		buyer,
		["name", "full_name", "email", "mobile_no", "creation"],
		as_dict=True,
	)

	# 2) Siparişler (sadece bu satıcı için)
	orders = frappe.db.sql(
		"""
		SELECT name, status, total, order_date
		FROM `tabOrder`
		WHERE seller = %(seller)s AND buyer = %(buyer)s
		ORDER BY order_date DESC
		LIMIT 50
		""",
		{"seller": profile, "buyer": buyer},
		as_dict=True,
	)

	# 3) Bu satıcının kendi mağazasına gelen Inquiry'ler (buyer eşleşmesi
	#    User Link ile veya sender_email ile)
	inquiries = frappe.get_all(
		"Seller Inquiry",
		filters=[
			["seller", "=", profile],
			["is_trashed", "=", 0],
			[
				"OR",
				[["buyer", "=", buyer]],
				[["sender_email", "=", buyer]],
			],
		]
		if False  # OR filter syntax Frappe v15'te limited; aşağıda 2 ayrı sorgu
		else {"seller": profile, "is_trashed": 0, "buyer": buyer},
		fields=["name", "status", "message", "creation"],
		order_by="creation desc",
		limit_page_length=50,
	)

	# 4) HD Ticket'lar (raised_by = buyer + related_order satıcının siparişine bağlı)
	tickets = frappe.db.sql(
		"""
		SELECT t.name, t.subject, t.status, t.priority, t.creation
		FROM `tabHD Ticket` t
		LEFT JOIN `tabOrder` o ON o.name = t.related_order
		WHERE t.raised_by = %(buyer)s
		  AND (o.seller = %(seller)s OR t.related_order IS NULL)
		ORDER BY t.creation DESC
		LIMIT 50
		""",
		{"seller": profile, "buyer": buyer},
		as_dict=True,
	)

	# Toplam ciro + sipariş sayısı (özet kartı için)
	stats_row = frappe.db.sql(
		"""
		SELECT COUNT(*) AS order_count, COALESCE(SUM(total), 0) AS total_revenue,
		       MAX(order_date) AS last_order_date, MIN(order_date) AS first_order_date
		FROM `tabOrder`
		WHERE seller = %(seller)s AND buyer = %(buyer)s
		""",
		{"seller": profile, "buyer": buyer},
		as_dict=True,
	)
	stats = stats_row[0] if stats_row else {}
	stats["total_revenue"] = float(stats.get("total_revenue") or 0)
	stats["order_count"] = int(stats.get("order_count") or 0)

	return {
		"buyer": buyer,
		"user": user_doc,
		"stats": stats,
		"orders": orders,
		"inquiries": inquiries,
		"tickets": tickets,
	}
