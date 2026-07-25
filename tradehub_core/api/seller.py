import re

import frappe
from frappe import _
from frappe.utils import getdate, nowdate

from tradehub_core.api._input import safe_float
from tradehub_core.api.rate_limit import rate_limit


def _strip_html(text):
	"""Strip HTML tags from text for plain-text display."""
	if not text:
		return ""
	return re.sub(r"<[^>]+>", "", text).strip()


def _seller_codes_from_listing_filters(listing_filters: dict) -> set:
	"""Verilen Listing filtresine uyan aktif ilanların satıcı (seller_profile) kod setini döndürür.
	Manufacturer filtrelerinden Listing-türevli olanlar (kategori, min_order, ürün sertifikası)
	bu set üzerinden Admin Seller Profile.seller_code'a indirgenir."""
	rows = frappe.get_all(
		"Listing",
		filters=listing_filters,
		fields=["seller_profile"],
		distinct=True,
		limit_page_length=0,
	)
	return {r.seller_profile for r in rows if r.get("seller_profile")}


def _verified_seller_codes() -> set:
	"""'Verified Seller' rolüne sahip kullanıcıların Admin Seller Profile.seller_code seti.
	Onaylanmış Satıcı filtresi için tek doğruluk kaynağı User.role (bkz. get_sellers verified akışı)."""
	rows = frappe.db.sql(
		"""SELECT asp.seller_code
		   FROM `tabAdmin Seller Profile` asp
		   JOIN `tabHas Role` hr ON hr.parent = asp.user
		   WHERE hr.role = 'Verified Seller' AND hr.parenttype = 'User'
		     AND asp.seller_code IS NOT NULL AND asp.seller_code != ''"""
	)
	return {r[0] for r in rows if r[0]}


def _resolve_seller_filters(
	search=None,
	keyword=None,
	category=None,
	country=None,
	min_rating=None,
	min_order=None,
	founded_year_min=None,
	verified=None,
	mgmt_certs=None,
	product_certs=None,
) -> dict | None:
	"""Manufacturer filtre paramlarını Admin Seller Profile get_all filtre dict'ine çevirir.

	Dönüş: filters dict; hiçbir satıcı eşleşemiyorsa None (çağıran boş sonuç döndürür).
	get_sellers (liste) ve get_manufacturer_facets (sayım) AYNI çözümü paylaşır → count ↔ liste tutarlı."""
	filters = {"status": "Active"}
	if search:
		filters["seller_name"] = ["like", "%" + str(search) + "%"]

	# seller_code daraltmaları: her biri bir kod seti; hepsi kesişir.
	code_sets: list[set] = []
	keyword = (keyword or "").strip()
	category = (category or "").strip()
	if keyword or category:
		listing_filters = {"status": "Active"}
		if category:
			from tradehub_core.api.listing import _get_category_descendants

			platform_cat = frappe.db.get_value("Product Category", {"url_slug": category}, "name")
			if platform_cat:
				descendants = _get_category_descendants(platform_cat)
				listing_filters["product_category"] = (
					descendants[0] if len(descendants) == 1 else ["in", descendants]
				)
			elif frappe.db.exists("Product Category", category):
				listing_filters["product_category"] = category
			else:
				listing_filters["category"] = category
		if keyword:
			listing_filters["title"] = ["like", "%" + keyword + "%"]
		code_sets.append(_seller_codes_from_listing_filters(listing_filters))

	if min_order:
		mo = safe_float(min_order, label=_("Min. sipariş"))
		if mo > 0:
			code_sets.append(
				_seller_codes_from_listing_filters({"status": "Active", "min_order_qty": [">=", mo]})
			)

	if product_certs:
		pcert_list = [c.strip() for c in str(product_certs).split(",") if c.strip()]
		if pcert_list:
			cert_parents = frappe.get_all(
				"Listing Certification",
				filters={"certification_type": ["in", pcert_list]},
				fields=["parent"],
				distinct=True,
				limit_page_length=0,
			)
			pnames = [r.parent for r in cert_parents if r.get("parent")]
			codes = (
				_seller_codes_from_listing_filters({"status": "Active", "name": ["in", pnames]})
				if pnames
				else set()
			)
			code_sets.append(codes)

	if verified:
		code_sets.append(_verified_seller_codes())

	if code_sets:
		final_codes = set.intersection(*code_sets) if len(code_sets) > 1 else code_sets[0]
		if not final_codes:
			return None
		filters["seller_code"] = ["in", sorted(final_codes)]

	# Direct Admin Seller Profile alanları
	if country:
		clist = [c.strip() for c in str(country).split(",") if c.strip()]
		if clist:
			filters["country"] = ["in", clist] if len(clist) > 1 else clist[0]
	if min_rating:
		filters["rating"] = [">=", safe_float(min_rating, label=_("Puan"))]
	if founded_year_min:
		# Firma yaşı X+ yıl → kuruluş yılı (bu yıl - X) ve öncesi.
		try:
			threshold = getdate(nowdate()).year - int(founded_year_min)
			filters["founded_year"] = ["<=", threshold]
		except (ValueError, TypeError):
			pass

	# Yönetim sertifikası: doğrulanmış Seller Certification'a sahip ASP name seti.
	if mgmt_certs:
		mcert_list = [c.strip() for c in str(mgmt_certs).split(",") if c.strip()]
		if mcert_list:
			cert_rows = frappe.get_all(
				"Seller Certification",
				filters={"certification_type": ["in", mcert_list], "verification_status": "Verified"},
				fields=["parent"],
				distinct=True,
				limit_page_length=0,
			)
			cert_names = sorted({r.parent for r in cert_rows if r.get("parent")})
			if not cert_names:
				return None
			filters["name"] = ["in", cert_names]

	return filters


def _empty_manufacturer_facets() -> dict:
	return {
		"countries": [],
		"ratings": [],
		"foundedYears": [],
		"managementCertifications": [],
		"productCertifications": [],
		"verifiedSupplierCount": 0,
		"total": 0,
	}


def _is_founded_year_at_most(value, cutoff: int) -> bool:
	"""Frappe'nin string döndürebildiği kuruluş yılını facet sayımı için güvenle karşılaştırır."""
	if value in (None, ""):
		return False
	try:
		return int(value) <= cutoff
	except (TypeError, ValueError):
		return False


def _resolve_category_display_name(category: str) -> str:
	"""Product Category url_slug'ından görünen adı çözer (manufacturers başlığı için).

	Frontend `findCategoryBySlug` client ağacı sığ olduğu için hash'li/derin
	kategori slug'larını çözemiyor; products backend'den (get_listings.categoryName)
	çözdüğü için tutarsızlık oluyordu. Burada backend authoritative adı döndürür.
	Bulunamazsa boş string (frontend slug'ı korur)."""
	category = (category or "").strip()
	if not category:
		return ""
	cat_name = frappe.db.get_value("Product Category", {"url_slug": category}, "name")
	if not cat_name and frappe.db.exists("Product Category", category):
		cat_name = category
	if not cat_name:
		return ""
	return frappe.db.get_value("Product Category", cat_name, "category_name") or ""


@frappe.whitelist(allow_guest=True)
def get_manufacturer_facets(
	search=None,
	keyword=None,
	category=None,
	country=None,
	min_rating=None,
	min_order=None,
	founded_year_min=None,
	verified=None,
	mgmt_certs=None,
	product_certs=None,
) -> dict:
	"""Üreticiler sayfası facet sayımları — count birimi = ÜRETİCİ (listing değil).

	get_sellers ile AYNI _resolve_seller_filters çözümünü kullanır → count ↔ liste tutarlı.
	Tüm aktif filtreler uygulanıp kalan üretici seti üzerinde her boyut sayılır (monotonic narrow)."""
	# Kategori görünen adı — satıcı olmasa bile başlık çözülsün diye boş-kontrolden ÖNCE.
	category_display = _resolve_category_display_name(category)

	filters = _resolve_seller_filters(
		search, keyword, category, country, min_rating, min_order,
		founded_year_min, verified, mgmt_certs, product_certs,
	)
	if filters is None:
		return {"data": {**_empty_manufacturer_facets(), "categoryName": category_display}}

	matched = frappe.get_all(
		"Admin Seller Profile",
		filters=filters,
		fields=["name", "seller_code", "country", "rating", "founded_year"],
		limit_page_length=0,
	)
	if not matched:
		return {"data": {**_empty_manufacturer_facets(), "categoryName": category_display}}

	names = [m.name for m in matched]
	codes = [m.seller_code for m in matched if m.get("seller_code")]

	# Ülke — üretici sayısı
	country_counts: dict[str, int] = {}
	for m in matched:
		if m.get("country"):
			country_counts[m.country] = country_counts.get(m.country, 0) + 1
	countries = [
		{"value": c, "label": c, "count": n}
		for c, n in sorted(country_counts.items(), key=lambda x: -x[1])
	]

	# Mağaza puanı — eşik başına üretici sayısı (4+/3+/2+/1+)
	ratings = []
	for th in (4, 3, 2, 1):
		cnt = sum(1 for m in matched if (m.get("rating") or 0) >= th)
		if cnt:
			ratings.append({"value": str(th), "label": f"{th}+", "count": cnt})

	# Firma yaşı — eşik başına üretici sayısı (5+/10+/15+ yıl → kuruluş yılı ≤ cutoff)
	current_year = getdate(nowdate()).year
	foundedYears = []
	for th in (5, 10, 15):
		cutoff = current_year - th
		cnt = sum(1 for m in matched if _is_founded_year_at_most(m.get("founded_year"), cutoff))
		if cnt:
			foundedYears.append({"value": str(th), "label": f"{th}+", "count": cnt})

	# Onaylanmış Satıcı — üretici sayısı
	verified_codes = _verified_seller_codes()
	verifiedSupplierCount = sum(1 for m in matched if m.get("seller_code") in verified_codes)

	# Yönetim sertifikaları — cert türü başına DISTINCT üretici sayısı
	mgmt_seen: dict[str, set] = {}
	if names:
		for r in frappe.get_all(
			"Seller Certification",
			filters={"parent": ["in", names], "verification_status": "Verified"},
			fields=["parent", "certification_type"],
			limit_page_length=0,
		):
			if r.get("certification_type"):
				mgmt_seen.setdefault(r.certification_type, set()).add(r.parent)
	managementCertifications = [
		{"value": ct, "label": ct, "count": len(ps)}
		for ct, ps in sorted(mgmt_seen.items(), key=lambda x: -len(x[1]))
	]

	# Ürün sertifikaları — cert türü başına DISTINCT üretici sayısı (Listing üzerinden)
	prod_seen: dict[str, set] = {}
	if codes:
		listings = frappe.get_all(
			"Listing",
			filters={"seller_profile": ["in", codes], "status": "Active"},
			fields=["name", "seller_profile"],
			limit_page_length=0,
		)
		listing_to_seller = {l.name: l.seller_profile for l in listings}
		if listing_to_seller:
			for r in frappe.get_all(
				"Listing Certification",
				filters={"parent": ["in", list(listing_to_seller.keys())]},
				fields=["parent", "certification_type"],
				limit_page_length=0,
			):
				seller = listing_to_seller.get(r.parent)
				if r.get("certification_type") and seller:
					prod_seen.setdefault(r.certification_type, set()).add(seller)
	productCertifications = [
		{"value": ct, "label": ct, "count": len(ss)}
		for ct, ss in sorted(prod_seen.items(), key=lambda x: -len(x[1]))
	]

	return {
		"data": {
			"countries": countries,
			"ratings": ratings,
			"foundedYears": foundedYears,
			"managementCertifications": managementCertifications,
			"productCertifications": productCertifications,
			"verifiedSupplierCount": verifiedSupplierCount,
			"total": len(matched),
			"categoryName": category_display,
		}
	}


@frappe.whitelist(allow_guest=True)
def get_sellers(
	search=None,
	keyword=None,
	category=None,
	page=1,
	page_size=20,
	country=None,
	min_rating=None,
	min_order=None,
	founded_year_min=None,
	verified=None,
	mgmt_certs=None,
	product_certs=None,
):
	filters = _resolve_seller_filters(
		search,
		keyword,
		category,
		country,
		min_rating,
		min_order,
		founded_year_min,
		verified,
		mgmt_certs,
		product_certs,
	)
	if filters is None:
		return {"sellers": [], "total": 0, "page": int(page), "page_size": int(page_size)}

	sellers = frappe.get_all(
		"Admin Seller Profile",
		filters=filters,
		fields=[
			"name",
			"seller_code",
			"seller_name",
			"user",
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
			# İş bilgisi — storefront üretici kartındaki istatistik + servis satırı için
			"founded_year",
			"staff_count",
			"annual_revenue",
			"factory_size",
			"business_type",
			"main_markets",
		],
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="seller_name asc",
	)
	# Batch fetch — hangi user'lar "Verified Seller" rolüne sahip (N+1 önle)
	seller_users = [s.user for s in sellers if s.get("user")]
	verified_users_set = set()
	if seller_users:
		verified_rows = frappe.db.sql(
			"""SELECT DISTINCT parent FROM `tabHas Role`
			   WHERE role = 'Verified Seller' AND parenttype = 'User' AND parent IN %(users)s""",
			{"users": tuple(seller_users)},
		)
		verified_users_set = {row[0] for row in verified_rows}
	# Batch fetch verifications — tek sorguda tüm satıcılar (N+1 önle)
	seller_names = [s["name"] for s in sellers]
	verif_map = _verifications_by_seller(seller_names) if seller_names else {}
	is_guest = frappe.session.user == "Guest"
	for s in sellers:
		s["slug"] = s.get("seller_code") or s.get("name", "")
		s["rating"] = float(s.get("rating") or 0)
		s["review_count"] = int(s.get("total_orders") or 0)
		s["cover_image"] = s.get("banner_image", "")
		s["short_description"] = _strip_html(s.get("description", ""))
		# Eski health_score-bazlı verified mantığı kaldırıldı; tek doğruluk kaynağı
		# User.role.Verified Seller (KYB Verified satıcılar).
		s["verified"] = bool(s.get("user") and s["user"] in verified_users_set)
		s["kybVerified"] = s["verified"]
		seller_verifs = list(verif_map.get(s["name"], []))
		s["verifications"] = seller_verifs
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
					"slug",
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
						"slug": l.get("slug") or "",
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
	# Sertifikalar child table — `frappe.db.get_value` skaler kolonlar dışına çıkamaz,
	# bu yüzden ayrı sorgu. Yalnız doğrulanmış sertifikalar storefront'a sızar.
	seller["certifications"] = frappe.get_all(
		"Seller Certification",
		filters={"parent": seller["name"], "verification_status": "Verified"},
		fields=["certification_type", "verification_status"],
	)
	seller["slug"] = seller.get("seller_code", "")
	seller["rating"] = float(seller.get("rating") or 0)
	seller["review_count"] = int(seller.get("review_count") or seller.get("total_orders") or 0)
	seller["cover_image"] = seller.get("banner_image", "")
	seller["store_name"] = seller.get("company_name") or seller.get("seller_name") or ""
	seller["business_name"] = seller.get("company_name") or seller.get("seller_name") or ""
	seller["short_description"] = _strip_html(seller.get("description", ""))
	# Eski is_verified field'ı silindi. verified == User.role.Verified Seller
	# (KYB onaylanınca otomatik atanır, geri çekilince kalkar). Tek doğruluk kaynağı.
	seller_user = seller.get("user") or frappe.db.get_value(
		"Admin Seller Profile", seller.get("name"), "user"
	)
	seller["verified"] = bool(seller_user and "Verified Seller" in frappe.get_roles(seller_user))
	seller["kybVerified"] = seller["verified"]
	seller["is_verified"] = seller["verified"]  # Alpine x-show geriye uyumluluk
	seller["response_time"] = seller.get("response_time") or ""
	seller["response_rate"] = float(seller.get("response_rate") or 0)
	seller["on_time_delivery"] = float(seller.get("on_time_delivery") or 0)

	# Satıcının varsayılan adresini ekle. Addresses.seller → Admin Seller Profile'a link
	# (save_address oraya yazar) ve seller["name"] zaten ASP adıdır. Önceki kod yanlışlıkla
	# User Profile adıyla filtreliyordu → hiç eşleşmiyordu (adres her zaman boş dönüyordu).
	# Misafire (login olmamış) PII (adres, email, telefon, user) sızdırılmaz — KVKK.
	is_guest = frappe.session.user == "Guest"
	default_addr = None
	if not is_guest:
		asp_name = seller["name"]
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
			{"kind": "Seller", "seller": asp_name, "is_default": 1},
			addr_fields,
			as_dict=True,
		)
		if not default_addr:
			rows = frappe.get_all(
				"Addresses",
				filters={"kind": "Seller", "seller": asp_name},
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

	# Storefront medya gallery: gallery_images child tablosu, kategoriye gore gruplanir.
	# Frontend StoreHeader hardcoded thumbs yerine bu media_groups'i kullanir.
	# Bos gruplar (count=0) yine donulur — UI tab'i kayit yoksa atlayabilir.
	seller["media_groups"] = _build_media_groups(seller["name"])

	# v4: Storefront sadece Verified cert'leri görür (verification_status="Verified").
	# Pending/Rejected gizlenir. CompanyProfile.ts bu listeyi okur.
	seller["verified_certifications"] = _get_verified_seller_certs(seller["name"])
	# Geriye uyumluluk: eski `certifications` text alanını (split edilen) bilinçli olarak
	# verified cert isimleri ile virgüllü string olarak doldur — eski Alpine kodu
	# bozulmasın diye.
	seller["certifications"] = ", ".join(c["certification_name"] for c in seller["verified_certifications"])

	# Saha doğrulama rozetleri — mağaza sayfası header + satıcı bilgisi için.
	seller_verifs = _verifications_by_seller([seller["name"]]).get(seller["name"], [])
	seller["verifications"] = seller_verifs

	# Panelden yönetilen SEO payload'ı (BE-LD) — storefront applyServerSeo ile
	# uygular. Üretim hatası public endpoint'i DÜŞÜRMEMELİ → None fallback.
	try:
		from tradehub_core.seo.meta_builder import build_for_seller

		record = dict(seller)
		record.setdefault("slug", seller.get("seller_code"))
		seller["seo"] = build_for_seller(record)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "seller.get_seller seo payload")
		seller["seo"] = None

	return seller


def _get_verified_seller_certs(profile_name: str) -> list:
	"""Yalnız verification_status='Verified' mağaza sertifikaları.

	Storefront cert rozetleri bu listeyi kullanır. Pending/Rejected gizli.
	"""
	if not profile_name:
		return []
	rows = frappe.db.sql(
		"""
		SELECT
			sc.certification_type,
			sc.certificate_number,
			sc.issued_date,
			sc.expiry_date,
			sc.document,
			ct.certification_name,
			ct.category,
			ct.description
		FROM `tabSeller Certification` sc
		LEFT JOIN `tabCertification Type` ct ON ct.name = sc.certification_type
		WHERE sc.parent = %(profile)s
			AND sc.parenttype = 'Admin Seller Profile'
			AND IFNULL(sc.verification_status, 'Pending') = 'Verified'
			AND (sc.expiry_date IS NULL OR sc.expiry_date >= CURDATE())
		ORDER BY sc.idx ASC
		""",
		{"profile": profile_name},
		as_dict=True,
	)
	return rows


# ── Satıcı Doğrulama (Verification) API'leri ─────────────────────────────────


def _verifications_by_seller(seller_profile_names: list) -> dict:
	"""TEK sorguda (N+1 yok) Seller Verification + Verification Source join.

	Dönen: {seller_profile_name: [{source_name, icon, description, inspection_date, document_url}]}.
	Yalnız status='Verified' ve geçerlilik tarihi geçmemiş kayıtlar dahil edilir.
	"""
	if not seller_profile_names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT
			sv.name AS verification_name,
			sv.seller,
			sv.inspection_date,
			sv.document,
			vs.source_name,
			vs.icon,
			vs.description
		FROM `tabSeller Verification` sv
		INNER JOIN `tabVerification Source` vs ON vs.name = sv.source
		WHERE sv.seller IN %(names)s
		  AND sv.status = 'Verified'
		  AND (sv.expiry_date IS NULL OR sv.expiry_date >= CURDATE())
		  AND vs.is_active = 1
		ORDER BY sv.seller ASC, sv.creation ASC
		""",
		{"names": tuple(seller_profile_names)},
		as_dict=True,
	)
	result: dict = {}
	for row in rows:
		seller = row.seller
		if seller not in result:
			result[seller] = []
		result[seller].append(
			{
				"source_name": row.source_name or "",
				"icon": row.icon or "",
				"description": row.description or "",
				"inspection_date": str(row.inspection_date) if row.inspection_date else "",
				# Belge private File; ziyaretçi ham /private/files yolunu açamaz (403).
				# Guest download endpoint'i Verified + süresi geçmemiş kontrolüyle servis eder.
				"document_url": (
					"/api/method/tradehub_core.api.seller.download_verification_document"
					f"?verification={row.verification_name}"
					if row.document
					else ""
				),
			}
		)
	return result


@frappe.whitelist(allow_guest=True)
def get_seller_verifications(seller_code: str) -> list:
	"""Public: Satıcının onaylı doğrulama rozetlerini döndür.

	seller_code = Admin Seller Profile.seller_code (URL slug / name).
	Yalnız status='Verified' + geçerli (expiry geçmemiş) kayıtlar görünür;
	Pending/Rejected gizlenir.
	"""
	if not seller_code:
		return []
	profile_name = frappe.db.get_value(
		"Admin Seller Profile", {"seller_code": seller_code, "status": "Active"}, "name"
	)
	if not profile_name:
		return []
	verifs = _verifications_by_seller([profile_name]).get(profile_name, [])
	return verifs


@frappe.whitelist(allow_guest=True)
def download_verification_document(verification: str):
	"""Public: Onaylı saha doğrulama (denetim) belgesini indir.

	Belge private File olarak saklanır; yalnız status='Verified' + süresi
	geçmemiş kayıtların belgesi bu endpoint üzerinden dışa açılır (mağaza
	sayfası "Raporu indirin" + rozet tooltip'i). Pending/Rejected belge sızmaz.
	"""
	if not verification:
		frappe.throw(_("Geçersiz parametre"))
	row = frappe.db.get_value(
		"Seller Verification",
		verification,
		["document", "status", "expiry_date"],
		as_dict=True,
	)
	if (
		not row
		or not row.document
		or row.status != "Verified"
		or (row.expiry_date and getdate(row.expiry_date) < getdate(nowdate()))
	):
		frappe.throw(_("Belge bulunamadı"), frappe.DoesNotExistError)

	file_name = frappe.db.get_value("File", {"file_url": row.document}, "name")
	if not file_name:
		frappe.throw(_("Belge bulunamadı"), frappe.DoesNotExistError)
	# Private File izni guest'e kapalı; erişim kararını yukarıdaki
	# Verified + expiry kontrolü veriyor, bu yüzden içerik doğrudan okunur.
	file_doc = frappe.get_doc("File", file_name)
	frappe.local.response.filename = file_doc.file_name
	frappe.local.response.filecontent = file_doc.get_content()
	frappe.local.response.type = "download"


_MEDIA_CATEGORIES = (
	("overview", "Genel Bakış"),
	("360_view", "360° Görünüm"),
	("production", "Üretim"),
	("quality_control", "Kalite Kontrol"),
)


def _build_media_groups(admin_seller_profile_name):
	"""
	Admin Seller Profile.gallery_images child satirlarini kategoriye gore gruplar.

	Donus formati frontend StoreHeader Alpine x-data icin tasarlandi:
	  [
	    {
	      "key": "overview", "label": "Genel Bakış", "count": N,
	      "items": [{"media_type": "video"|"image", "src": ..., "poster": ..., "caption": ...}]
	    }, ...
	  ]
	Sira: media_type=video onceligi (UI ilk videoyu ana medya yapsin), sonra sort_order, sonra idx.
	"""
	rows = frappe.get_all(
		"Seller Gallery Image",
		filters={"parent": admin_seller_profile_name, "parenttype": "Admin Seller Profile"},
		fields=[
			"category",
			"media_type",
			"image",
			"video_url",
			"poster_image",
			"caption",
			"sort_order",
			"idx",
		],
		order_by="sort_order asc, idx asc",
	)

	groups_by_key = {key: [] for key, _label in _MEDIA_CATEGORIES}
	for r in rows:
		key = (r.get("category") or "overview").strip()
		if key not in groups_by_key:
			# Bilinmeyen kategori — overview'a düşür (geriye dönük uyum)
			key = "overview"
		mtype = (r.get("media_type") or "image").strip()
		# Esnek src cozumlemesi: child table grid'inde sadece "Görsel" sutunu
		# in_list_view ile gorunduygu icin kullanici video MP4'unu da o alana
		# yukluyor olabilir. media_type'a oncelikli alani dene, dolu degilse
		# karşı alana fallback (video → image, image → video_url).
		if mtype == "video":
			src = r.get("video_url") or r.get("image") or ""
		else:
			src = r.get("image") or r.get("video_url") or ""
		if not src:
			continue
		groups_by_key[key].append(
			{
				"media_type": mtype,
				"src": src,
				"poster": r.get("poster_image") or "",
				"caption": r.get("caption") or "",
			}
		)

	result = []
	for key, label in _MEDIA_CATEGORIES:
		items = groups_by_key[key]
		# Video'yu basa al (ana medya genelde video oluyor)
		items.sort(key=lambda it: 0 if it["media_type"] == "video" else 1)
		result.append({"key": key, "label": label, "count": len(items), "items": items})
	return result


@frappe.whitelist()
def get_my_supplier_profile():
	"""Returns the Admin Seller Profile name for the logged-in seller."""
	user = frappe.session.user
	if not user or user == "Guest":
		return None
	return frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")


@frappe.whitelist()
def get_my_admin_seller_profile():
	"""Returns the Admin Seller Profile for the logged-in user.

	Sub-user desteği: Eğer kullanıcı ASP'nin doğrudan `user`'ı değilse
	(owner) ama `User.tradehub_tenant` ile bağlıysa (Co-Owner, Staff, vb.),
	o tenant'ın ASP'sini döndür. Yazma yetkisi ayrı capability kontrolünden
	geçer (`update_my_admin_seller_profile` → `seller_profile.write`).
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		return None

	# 1) Owner: doğrudan ASP.user
	name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")

	# 2) Sub-user: User.tradehub_tenant → ASP.name
	if not name:
		from tradehub_core.utils.tenant import _get_seller_profile_for_user

		name = _get_seller_profile_for_user(user)

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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("seller_profile.write")

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


# Storefront satıcı self-servis profil formu (seller-dashboard) alan setleri.
# YAZILABILIR allowlist — hassas alanlar (tax_id/tax_office/iban → KYB/finansal,
# ayrı güvenli akışla düzenlenir) ve toplanmayan adres alanları
# (address_line2/district/postal_code → doğru evi Addresses doctype'ı) HARİÇ.
_PROFILE_EDITABLE_FIELDS = frozenset(
	{
		"seller_name",
		"slogan",
		"description",
		"logo",
		"banner_image",
		"phone",
		"website",
		"address_line1",
		"city",
		"company_name",
		"business_type",
		"founded_year",
		"staff_count",
		"annual_revenue",
		"factory_size",
		"main_markets",
	}
)

# Forma yüklenen (okuma) alanlar — yazılamayanlar (tax/iban) da dahil,
# çünkü formda görüntüleniyorlar (update_profile yalnızca allowlist'i yazar).
_PROFILE_READ_FIELDS = [
	"seller_name",
	"company_name",
	"phone",
	"website",
	"slogan",
	"description",
	"logo",
	"banner_image",
	"business_type",
	"founded_year",
	"staff_count",
	"annual_revenue",
	"factory_size",
	"main_markets",
	"address_line1",
	"city",
	"tax_id",
	"tax_office",
	"iban",
	# Salt-okunur mağaza metrikleri (dashboard header + Performans kartları).
	# update_profile yalnızca _PROFILE_EDITABLE_FIELDS'i yazar → bunlar yazılamaz.
	# health_score bilinçli HARİÇ (kaynağı güvenilmez; Admin panelde de hidden=1).
	"seller_code",
	"score_grade",
	"total_orders",
	"rating",
]


def _get_my_seller_profile_name() -> str:
	"""Giriş yapan kullanıcının kendi Admin Seller Profile adını döndürür.
	Sahiplik garantisi: lookup {"user": session.user} — başka profil erişilemez."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetkisiz"), frappe.PermissionError)
	name = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
	if not name:
		frappe.throw(_("Satıcı profili bulunamadı"), frappe.DoesNotExistError)
	return name


@frappe.whitelist()
def get_my_profile() -> dict:
	"""Giriş yapan satıcının kendi mağaza profilini (self-servis form için) döndürür."""
	name = _get_my_seller_profile_name()
	return frappe.db.get_value("Admin Seller Profile", name, _PROFILE_READ_FIELDS, as_dict=True) or {}


@frappe.whitelist()
def update_profile(data=None) -> dict:
	"""Satıcının kendi mağaza profilini günceller — SADECE allowlist alanları.

	Güvenlik: hassas (tax_id/tax_office/iban) ve toplanmayan (address_line2/
	district/postal_code) alanlar allowlist dışı; gelseler bile yoksayılır.
	Sahiplik {"user": session.user} lookup'ı ile garanti (başka profil yazılamaz)."""
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("seller_profile.write")
	name = _get_my_seller_profile_name()

	if isinstance(data, str):
		data = frappe.parse_json(data)
	if not isinstance(data, dict):
		frappe.throw(_("Geçersiz veri"), frappe.ValidationError)

	updates = {k: v for k, v in data.items() if k in _PROFILE_EDITABLE_FIELDS}
	for field, value in updates.items():
		frappe.db.set_value("Admin Seller Profile", name, field, value)
	if updates:
		frappe.db.commit()
	return {"updated": sorted(updates.keys())}


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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("category.write")

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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("category.write")

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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("category.write")

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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("category.write")

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


# ── Satıcı Doğrulama (Seller Verification) Onay Kuyruğu ─────────────────

VERIFICATION_STATUSES = ("Requested", "Scheduled", "Pending", "Verified", "Rejected")


@frappe.whitelist()
def list_pending_seller_verifications(status: str | None = None) -> dict:
	"""Admin: Seller Verification kayıtlarını listele (N+1 yok).

	status None → onay/talep bekleyenler (Requested/Scheduled/Pending) — eski davranış.
	status "all" → tüm kayıtlar. Tek durum adı → yalnız o durum.
	Dönüş {"data": [...], "total": N} — kardeş endpoint list_pending_seller_certs
	ile aynı zarf; admin panel res.message.data bekler, düz liste boş görünür.
	"""
	if (
		"System Manager" not in frappe.get_roles(frappe.session.user)
		and frappe.session.user != "Administrator"
	):
		frappe.throw(_("Yetki hatası"), frappe.PermissionError)

	if status and status != "all" and status not in VERIFICATION_STATUSES:
		frappe.throw(_("Geçersiz durum filtresi."))
	if not status:
		status_filter = ["in", ["Requested", "Scheduled", "Pending"]]
	elif status == "all":
		status_filter = ["in", list(VERIFICATION_STATUSES)]
	else:
		status_filter = status

	# System Manager/Administrator sistem işlemi — get_all ile perm bypass kasıtlı
	rows = frappe.get_all(
		"Seller Verification",
		filters={"status": status_filter},
		fields=[
			"name",
			"seller",
			"source",
			"status",
			"inspection_date",
			"expiry_date",
			"scheduled_date",
			"request_note",
			"admin_note",
			"document",
			"creation",
		],
		order_by="creation asc",
	)
	if not rows:
		return {"data": [], "total": 0}

	# Batch: seller_name + source_name — N+1 yoktur
	seller_ids = list({r.seller for r in rows if r.get("seller")})
	source_ids = list({r.source for r in rows if r.get("source")})

	seller_map = (
		{
			r.name: r.seller_name
			for r in frappe.get_all(
				"Admin Seller Profile",
				filters={"name": ["in", seller_ids]},
				fields=["name", "seller_name"],
			)
		}
		if seller_ids
		else {}
	)
	source_map = (
		{
			r.name: r.source_name
			for r in frappe.get_all(
				"Verification Source",
				filters={"name": ["in", source_ids]},
				fields=["name", "source_name"],
			)
		}
		if source_ids
		else {}
	)

	for r in rows:
		r["seller_name"] = seller_map.get(r.seller, r.seller or "-")
		r["source_name"] = source_map.get(r.source, r.source or "-")

	return {"data": rows, "total": len(rows)}


@frappe.whitelist()
def schedule_verification(name: str | int, scheduled_date: str, admin_note: str = "") -> dict:
	"""Superadmin: Denetim talebini planla (Requested → Scheduled).

	name int|str: Seller Verification autoincrement (name = bigint); v15 whitelist
	type-check'i saf str beklerse int argümanı FrappeTypeError ile reddeder.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Bu işlemi yalnızca Administrator yapabilir"), frappe.PermissionError)
	if not scheduled_date:
		frappe.throw(_("Planlanan tarih zorunludur."))

	doc = frappe.get_doc("Seller Verification", name)
	if doc.status not in ("Requested", "Scheduled"):
		frappe.throw(_("Yalnızca talep aşamasındaki kayıtlar planlanabilir."))
	doc.scheduled_date = scheduled_date
	if admin_note:
		doc.admin_note = admin_note
	doc.status = "Scheduled"
	doc.save(ignore_permissions=True)  # Administrator sistem işlemi
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def approve_seller_verification(name: str | int) -> dict:
	"""Superadmin: Seller Verification kaydını 'Verified' olarak onayla."""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Bu işlemi yalnızca Administrator yapabilir"), frappe.PermissionError)

	doc = frappe.get_doc("Seller Verification", name)
	doc.status = "Verified"
	doc.save(ignore_permissions=True)  # Administrator tarafından tetiklenen sistem işlemi
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def reject_seller_verification(name: str | int, reason: str = "") -> dict:
	"""Superadmin: Seller Verification kaydını 'Rejected' olarak reddet.

	Doctype'ta reason alanı yok; reason varsa Frappe Comment olarak eklenir.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Bu işlemi yalnızca Administrator yapabilir"), frappe.PermissionError)

	doc = frappe.get_doc("Seller Verification", name)
	doc.status = "Rejected"
	doc.save(ignore_permissions=True)  # Administrator tarafından tetiklenen sistem işlemi

	if reason and reason.strip():
		frappe.get_doc(
			{
				"doctype": "Comment",
				"comment_type": "Comment",
				"reference_doctype": "Seller Verification",
				"reference_name": name,
				"content": reason.strip(),
			}
		).insert(ignore_permissions=True)

	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist(methods=["POST"])
def update_seller_verification(
	name: str | int,
	source: str | None = None,
	document: str | None = None,
	inspection_date: str | None = None,
	expiry_date: str | None = None,
	scheduled_date: str | None = None,
	admin_note: str | None = None,
	status: str | None = None,
) -> dict:
	"""Superadmin: Seller Verification kaydının alanlarını düzenle (yanlış tarih vb.).

	Yalnız gönderilen (None olmayan) alanlar yazılır; boş string alanı temizler.
	seller alanı parametre olarak kabul edilmez — kayıt başka satıcıya taşınamaz.
	doc.save() controller validate()'ini çalıştırır: duplicate kuralı (source
	değişikliği aktif kayıtla çakışırsa engellenir) ve durum kuralları korunur.
	"""
	if frappe.session.user != "Administrator":
		frappe.throw(_("Bu işlemi yalnızca Administrator yapabilir"), frappe.PermissionError)

	doc = frappe.get_doc("Seller Verification", name)

	if status is not None:
		if status not in VERIFICATION_STATUSES:
			frappe.throw(_("Geçersiz durum değeri."))
		doc.status = status
	if source is not None:
		doc.source = source
	if document is not None:
		doc.document = document.strip() or None
	if inspection_date is not None:
		doc.inspection_date = inspection_date or None
	if expiry_date is not None:
		doc.expiry_date = expiry_date or None
	if scheduled_date is not None:
		doc.scheduled_date = scheduled_date or None
	if admin_note is not None:
		doc.admin_note = admin_note.strip() or None

	doc.save(ignore_permissions=True)  # Administrator sistem işlemi
	frappe.db.commit()
	return {"ok": True, "name": doc.name, "status": doc.status}


def _get_seller_profile_for_session():
	"""FAZ 1.5 — Merkezi tenant resolver'ı kullan (sub-user için tradehub_tenant fallback)."""
	from tradehub_core.utils.tenant import _get_seller_profile_for_user

	return _get_seller_profile_for_user(frappe.session.user)


def _safe_page_int(value, *, default: int, minimum: int, maximum: int) -> int:
	"""Guest query değerlerini kontrollü bir pozitif tam sayıya indirger."""
	try:
		parsed = int(value)
	except (TypeError, ValueError):
		return default
	return min(maximum, max(minimum, parsed))


def _seller_products_order_by(sort_by=None, sort_dir=None, sort=None) -> str:
	"""Public seller-store ürünleri için yalnız izinli ve deterministik sıralama.

	`sort` mevcut storefront UI adlarını destekler; `sort_by` + `sort_dir` yeni,
	açık API sözleşmesidir. Kolon isimleri kullanıcı girdisinden asla kurulmaz.
	"""
	aliases = {
		"default": ("creation", "desc"),
		"newest": ("creation", "desc"),
		"price_asc": ("selling_price", "asc"),
		"price_desc": ("selling_price", "desc"),
		"best_selling": ("order_count", "desc"),
	}
	if sort in aliases:
		sort_by, sort_dir = aliases[sort]

	columns = {"creation", "selling_price", "order_count"}
	direction = str(sort_dir or "").lower()
	if sort_by not in columns:
		sort_by, direction = "creation", "desc"
	elif direction not in {"asc", "desc"}:
		direction = "desc"

	return f"{sort_by} {direction}, name {direction}"


@frappe.whitelist(allow_guest=True)
def get_seller_products(
	seller_code,
	category=None,
	page=1,
	page_size=40,
	category_type="seller",
	sort_by=None,
	sort_dir=None,
	sort=None,
):
	# seller_code = Admin Seller Profile name
	if not frappe.db.exists("Admin Seller Profile", seller_code):
		return {"products": [], "total": 0}
	filters = {"seller_profile": seller_code, "status": "Active"}
	if category:
		# Eski istemciler category_type göndermediği için seller-category davranışı
		# varsayılan kalır. Platform kategorisi ancak açık tip ile filtrelenir.
		filters["product_category" if category_type == "platform" else "category"] = category
	page_number = _safe_page_int(page, default=1, minimum=1, maximum=100_000)
	page_limit = _safe_page_int(page_size, default=40, minimum=1, maximum=100)
	listings = frappe.get_all(
		"Listing",
		filters=filters,
		fields=[
			"name",
			"slug",
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
		limit_start=(page_number - 1) * page_limit,
		limit_page_length=page_limit,
		order_by=_seller_products_order_by(sort_by=sort_by, sort_dir=sort_dir, sort=sort),
	)
	for l in listings:
		l["id"] = l.get("name", "")
		l["product_name"] = l.get("title", "")
		l["image"] = l.get("primary_image", "")
		l["currency"] = l.get("currency") or "USD"
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
	from tradehub_core.tradehub_core.scoring.grading import seller_rating_to_grade

	frappe.db.set_value(
		"Admin Seller Profile",
		seller_code,
		{"rating": avg, "review_count": count, "score_grade": seller_rating_to_grade(avg, count)},
	)


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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("gallery.write")

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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("gallery.write")

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

	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("storefront.write")

	# F-012: Yetki kontrolü — _get_seller_profile_for_session ile tutarlı pattern
	is_admin = frappe.session.user == "Administrator" or "System Manager" in frappe.get_roles()
	if not is_admin:
		resolved_profile = _get_seller_profile_for_session()
		if not resolved_profile or resolved_profile != seller_code:
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


# M18 fix — guest erişimli; sender bilgisi oturumdan alınıyor (impersonation engelli),
# ek olarak spam'e karşı rate-limit (IP/oturum başına 10 / 5 dk).
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=10, window_seconds=300, per_user=True)
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
	# F-034: Spam koruması — boş/çok kısa mesaj ve guest'te email zorunluluğu
	clean_message = (message or "").strip()
	if len(clean_message) < 10:
		frappe.throw(_("Mesaj en az 10 karakter olmalıdır."), frappe.ValidationError)
	if not sender_email:
		frappe.throw(_("İletişim bilgisi gereklidir. Lütfen giriş yapın veya e-posta adresinizi girin."), frappe.ValidationError)

	doc = frappe.new_doc("Seller Inquiry")
	doc.seller = seller_code
	doc.seller_code = seller_code
	doc.message = clean_message
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

	# C4 fix — KRİTİK tenant guard. `get_all` permission_query_conditions'ı UYGULAMAZ;
	# bu yüzden seller filtresi ELLE eklenmeli, aksi halde tüm mağazaların inquiry'leri
	# (alıcı PII dahil) sızar. Çağıranın kendi Admin Seller Profile'ı:
	profile, _user = _get_my_seller_profile()

	try:
		page = int(page) or 1
	except (TypeError, ValueError):
		page = 1
	try:
		page_size = int(page_size) or 20
	except (TypeError, ValueError):
		page_size = 20
	page_size = min(max(page_size, 1), 100)

	filters = {"is_trashed": 0, "seller": profile}
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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("inquiry.reply")

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
	from tradehub_core.utils.seller_capabilities import require_seller_capability

	require_seller_capability("inquiry.reply")

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

	# 4) HD Ticket'lar — yalnızca bu satıcının siparişine bağlı ticket'lar.
	# H11 fix — eski koşul `OR t.related_order IS NULL` alıcının diğer satıcılara/
	# platforma açtığı (bu satıcıyla ilgisiz) ticket'ları da sızdırıyordu; kaldırıldı.
	tickets = frappe.db.sql(
		"""
		SELECT t.name, t.subject, t.status, t.priority, t.creation
		FROM `tabHD Ticket` t
		INNER JOIN `tabOrder` o ON o.name = t.related_order
		WHERE t.raised_by = %(buyer)s
		  AND o.seller = %(seller)s
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

	# H11 fix — User PII (full_name/email/mobile_no) yalnız bu satıcıyla gerçek bir
	# ilişki varsa döndürülür (sipariş, inquiry veya seller-scoped ticket). Aksi halde
	# herhangi bir satıcı keyfi e-posta sorgulayarak PII hasat edebilirdi.
	has_relationship = bool(stats["order_count"] > 0 or inquiries or tickets)
	if not has_relationship:
		user_doc = None

	return {
		"buyer": buyer,
		"user": user_doc,
		"stats": stats,
		"orders": orders,
		"inquiries": inquiries,
		"tickets": tickets,
	}
