import re

import frappe
from frappe import _


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
	for s in sellers:
		s["slug"] = s.get("seller_code") or s.get("name", "")
		s["rating"] = float(s.get("rating") or 0)
		s["review_count"] = int(s.get("total_orders") or 0)
		s["cover_image"] = s.get("banner_image", "")
		s["short_description"] = _strip_html(s.get("description", ""))
		s["verified"] = bool(s.get("health_score", 0) >= 80)
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
	seller["short_description"] = _strip_html(seller.get("description", ""))
	seller["verified"] = bool(seller.get("is_verified")) or bool(seller.get("health_score", 0) >= 80)
	seller["response_time"] = seller.get("response_time") or ""
	seller["response_rate"] = float(seller.get("response_rate") or 0)
	seller["on_time_delivery"] = float(seller.get("on_time_delivery") or 0)

	# Satıcının varsayılan adresini ekle. Addresses DocType'ı Seller Profile'a bağlı,
	# bu yüzden Admin Seller Profile → user → Seller Profile köprüsü kuruyoruz.
	# TODO: İleride sadece ücretli üyelere (Premium Seller) gösterilecek — şimdilik public.
	default_addr = None
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
				# Varsayılan yoksa en eski adresi kullan
				rows = frappe.get_all(
					"Addresses",
					filters={"kind": "Seller", "seller": sp_name},
					fields=addr_fields,
					order_by="creation asc",
					limit=1,
				)
				default_addr = rows[0] if rows else None
	seller["address"] = default_addr
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
def update_seller_category(category_name, new_name=None, description=None, sort_order=None):
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
	"""Satıcı: kendi kategorisini pasife al (soft deactivate)."""
	seller_profile = _get_seller_profile_for_session()
	if not seller_profile:
		frappe.throw(_("Satıcı profili bulunamadı."))
	cat = frappe.get_doc("Seller Category", category_name)
	if cat.seller != seller_profile:
		frappe.throw(_("Bu kategori size ait değil."), frappe.PermissionError)
	cat.is_enabled = 0
	cat.save(ignore_permissions=True)
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


@frappe.whitelist()
def submit_review(seller_code, rating, comment):
	if frappe.session.user == "Guest":
		frappe.throw(_("Yorum yapmak icin giris yapmaniz gerekiyor"), frappe.AuthenticationError)
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		frappe.throw(_("Satici bulunamadi"), frappe.DoesNotExistError)
	rating = float(rating)
	if rating < 1 or rating > 5:
		frappe.throw(_("Puan 1 ile 5 arasinda olmalidir"))
	comment = (comment or "").strip()
	if not comment:
		frappe.throw(_("Yorum bos olamaz"))
	user_data = frappe.db.get_value("User", frappe.session.user, ["full_name", "name"], as_dict=True)
	reviewer_name = user_data.full_name or user_data.name
	doc = frappe.new_doc("Seller Review")
	doc.seller = seller_code
	doc.reviewer_name = reviewer_name
	doc.rating = rating
	doc.comment = comment
	doc.status = "Published"
	doc.date = frappe.utils.now()
	doc.insert(ignore_permissions=True)
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
	if frappe.session.user and frappe.session.user != "Guest":
		user = frappe.db.get_value("User", frappe.session.user, ["full_name", "email"], as_dict=True)
		if user:
			sender_name = user.full_name or ""
			sender_email = user.email or ""
	doc = frappe.new_doc("Seller Inquiry")
	doc.seller = seller_code
	doc.seller_code = seller_code
	doc.message = message.strip()
	doc.sender_name = sender_name
	doc.sender_email = sender_email
	doc.share_business_card = int(share_business_card)
	doc.status = "Yeni"
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "inquiry_id": doc.name}
