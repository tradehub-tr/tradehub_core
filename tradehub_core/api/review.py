"""Listing Review public API (Faz 1).

Buyer / public / admin uçları + Listing rating cache yeniden hesaplaması.
Sözleşme ve doğrulama detayları için
``tradehub_core.tradehub_core.doctype.listing_review.listing_review`` modülüne bakın.
"""

from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils import cint, now_datetime

from tradehub_core.api.rate_limit import rate_limit

VALID_SORTS = {
	"recent": "published_at DESC, submitted_at DESC",
	"high": "rating DESC, published_at DESC",
	"low": "rating ASC, published_at DESC",
	"helpful": "helpful_count DESC, published_at DESC",
}

ADMIN_ROLES = {"System Manager", "Marketplace Admin"}

ABUSE_AUTO_HIDE_THRESHOLD = 3
ASPECT_FIELDS = (
	"product_quality_rating",
	"service_rating",
	"shipping_rating",
	"spec_match_rating",
	"documentation_rating",
)
ASPECT_LISTING_CACHE = {
	"product_quality_rating": "quality_avg",
	"service_rating": "service_avg",
	"shipping_rating": "shipping_avg",
	"spec_match_rating": "spec_match_avg",
	"documentation_rating": "documentation_avg",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Bu işlem için giriş yapmalısınız"), frappe.AuthenticationError)


def _is_admin(user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	return bool(set(frappe.get_roles(user)) & ADMIN_ROLES)


def _safe_int(value, label: str, lo: int | None = None, hi: int | None = None) -> int:
	try:
		v = int(value)
	except (TypeError, ValueError):
		frappe.throw(_("Geçersiz {0}").format(label))
	if lo is not None and v < lo:
		frappe.throw(_("{0} en az {1} olmalı").format(label, lo))
	if hi is not None and v > hi:
		frappe.throw(_("{0} en fazla {1} olmalı").format(label, hi))
	return v


# ---------------------------------------------------------------------------
# recompute_listing_rating
# ---------------------------------------------------------------------------
def recompute_listing_rating(listing_name: str | None, exclude_review_name: str | None = None):
	"""Listing.average_rating + review_count + rating_distribution + last_review_at
	+ 5 boyut ortalaması (Faz 2) değerlerini Listing Review (status=Approved)
	toplamından yeniden hesaplar.

	`exclude_review_name`: on_trash sırasında kullanılır — Frappe lifecycle'ında
	on_trash hook'u kayıt fiziksel silinmeden ÖNCE çalışır, bu yüzden
	silinmekte olan review'ın name'i agregasyondan dışlanmalıdır.
	"""
	if not listing_name:
		return
	if not frappe.db.exists("Listing", listing_name):
		return

	aspect_cols = ", ".join(ASPECT_FIELDS)
	if exclude_review_name:
		rows = frappe.db.sql(
			f"""
			SELECT rating, published_at, {aspect_cols}
			FROM `tabListing Review`
			WHERE listing = %s AND status = 'Approved' AND name != %s
			""",
			(listing_name, exclude_review_name),
			as_dict=True,
		)
	else:
		rows = frappe.db.sql(
			f"""
			SELECT rating, published_at, {aspect_cols}
			FROM `tabListing Review`
			WHERE listing = %s AND status = 'Approved'
			""",
			(listing_name,),
			as_dict=True,
		)

	count = len(rows)
	dist = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
	total = 0
	last_at = None
	for r in rows:
		rt = int(r.rating or 0)
		if 1 <= rt <= 5:
			dist[str(rt)] += 1
			total += rt
		if r.published_at and (last_at is None or r.published_at > last_at):
			last_at = r.published_at

	avg = round(total / count, 2) if count else 0.0

	# 5 boyut ortalamaları — null değerler ortalamaya katılmaz
	aspect_avgs = {}
	for aspect_field, listing_cache_field in ASPECT_LISTING_CACHE.items():
		valid = [int(r[aspect_field]) for r in rows if r.get(aspect_field)]
		aspect_avgs[listing_cache_field] = round(sum(valid) / len(valid), 2) if valid else 0.0

	update_payload = {
		"average_rating": avg,
		"review_count": count,
		"rating_distribution": json.dumps(dist),
		"last_review_at": last_at,
	}
	update_payload.update(aspect_avgs)

	frappe.db.set_value("Listing", listing_name, update_payload, update_modified=False)

	# Faz 3: weighted rating (ML) cache'i de güncelle
	try:
		from tradehub_core.api.rating_engine import recompute_listing_weighted

		recompute_listing_weighted(listing_name)
	except Exception:
		frappe.log_error(title="weighted_recompute_failed", message=f"listing={listing_name}")

	# Storefront listeleme cache'i — listing.py içindeki invalidator
	try:
		from tradehub_core.api.listing import invalidate_listing_cache

		invalidate_listing_cache()
	except Exception:
		# Cache invalidation kritik değil; ana yazma yine de geçerli kalır
		pass


# ---------------------------------------------------------------------------
# Lifecycle handlers (hooks.py'den çağrılır)
# ---------------------------------------------------------------------------
def on_review_after_insert(doc, method=None):
	# Insert anında status varsayılan Pending — agregasyona dahil olmaz.
	# Ama admin/seed ile direkt Approved insert edilirse rating güncellenmeli.
	if doc.status == "Approved":
		recompute_listing_rating(doc.listing)


def on_review_on_update(doc, method=None):
	# on_update controller içinde de çağrılıyor; idempotent olduğu için
	# burada ek bir tetikleme yapmıyoruz.
	return


def on_review_on_trash(doc, method=None):
	# Controller on_trash zaten Listing'i yeniden hesaplatıyor;
	# burası savunma amaçlı çift kontrol — silinmekte olan kayıt
	# henüz tablodadır, agregasyondan name ile dışlanır.
	if doc.listing:
		recompute_listing_rating(doc.listing, exclude_review_name=doc.name)


# ---------------------------------------------------------------------------
# Public / Buyer API
# ---------------------------------------------------------------------------
@frappe.whitelist()
def submit_listing_review(
	order_item: str,
	rating,
	body: str,
	title: str | None = None,
	images=None,
	video_url: str | None = None,
	aspects=None,
):
	"""Buyer endpoint — yeni Listing Review oluşturur (status=Pending).

	Faz 2 ek parametreler:
	  - images: [{image, caption?}, ...] (max 10)
	  - video_url: YouTube/Vimeo URL
	  - aspects: {product_quality, service, shipping, spec_match, documentation}
	            her biri 1..5 (opsiyonel)
	"""
	_ensure_logged_in()
	if not order_item:
		frappe.throw(_("Sipariş kalemi zorunludur"))

	# Order Item bilgilerini al
	oi = frappe.db.get_value(
		"Order Item",
		order_item,
		["parent", "parenttype", "listing"],
		as_dict=True,
	)
	if not oi or oi.parenttype != "Order":
		frappe.throw(_("Sipariş kalemi bulunamadı"), frappe.DoesNotExistError)

	# H8 fix — BOLA guard: yalnız siparişin sahibi (buyer) o kaleme yorum yazabilir.
	# Eskiden order_item doğrudan kabul ediliyor, parent Order'ın sahipliği
	# doğrulanmıyordu → herhangi bir kullanıcı başkasının siparişine "doğrulanmış
	# satın alım" yorumu oluşturabiliyordu.
	order_buyer = frappe.db.get_value("Order", oi.parent, "buyer")
	if order_buyer != frappe.session.user:
		frappe.throw(_("Bu siparişe ait olmadığınız için yorum yazamazsınız"), frappe.PermissionError)

	rating_int = _safe_int(rating, _("Puan"), 1, 5)

	doc = frappe.new_doc("Listing Review")
	doc.listing = oi.listing
	doc.order = oi.parent
	doc.order_item = order_item
	doc.reviewer_user = frappe.session.user
	doc.rating = rating_int
	doc.title = (title or "").strip() or None
	doc.body = (body or "").strip()
	doc.status = "Pending"
	doc.submitted_at = now_datetime()

	# Faz 2: aspect ratings
	if aspects:
		if isinstance(aspects, str):
			try:
				aspects = json.loads(aspects)
			except (ValueError, TypeError):
				aspects = {}
		if isinstance(aspects, dict):
			aspect_map = {
				"product_quality": "product_quality_rating",
				"service": "service_rating",
				"shipping": "shipping_rating",
				"spec_match": "spec_match_rating",
				"documentation": "documentation_rating",
			}
			for k, db_field in aspect_map.items():
				if k in aspects and aspects[k]:
					doc.set(db_field, _safe_int(aspects[k], k, 1, 5))

	# Faz 2: images
	if images:
		if isinstance(images, str):
			try:
				images = json.loads(images)
			except (ValueError, TypeError):
				images = []
		if isinstance(images, list):
			for img in images[:10]:
				if not isinstance(img, dict) or not img.get("image"):
					continue
				doc.append(
					"images",
					{"image": img["image"], "caption": img.get("caption")},
				)

	# Faz 2: video URL
	if video_url:
		doc.video_url = video_url.strip() or None

	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def update_listing_review(name: str, rating=None, title: str | None = None, body: str | None = None):
	"""Buyer endpoint — yorumun içeriğini günceller.

	Düzenleme penceresi (24s), edit_count artışı ve yeniden-moderasyon
	(status=Pending) DocType controller'ında (`_enforce_edit_window`) tek
	noktadan uygulanır — buyer içeriği değiştirince yorum tekrar onaya girer.
	Burada yalnız sahiplik kontrolü + alan ataması yapılır.
	"""
	_ensure_logged_in()
	doc = frappe.get_doc("Listing Review", name)
	user = frappe.session.user
	is_admin = _is_admin()
	if doc.reviewer_user != user and not is_admin:
		frappe.throw(
			_("Bu yorumu yalnızca sahibi düzenleyebilir"),
			frappe.PermissionError,
		)

	if rating is not None:
		doc.rating = _safe_int(rating, _("Puan"), 1, 5)
	if title is not None:
		doc.title = (title or "").strip() or None
	if body is not None:
		doc.body = (body or "").strip()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"success": True,
		"name": doc.name,
		"edit_count": doc.edit_count,
		"status": doc.status,
	}


@frappe.whitelist(allow_guest=True)
def list_listing_reviews(
	listing: str,
	page: int = 1,
	page_size: int = 10,
	sort_by: str = "recent",
	only_verified: int = 0,
):
	"""Public — bir listing'in onaylı yorumlarını sayfalı döndürür.

	Login'li kullanıcının **kendi Pending yorumu** da listede gözükür
	(`is_own_pending=true` flag ile). Böylece "yorumum kayboldu mu?"
	şüphesi olmaz.
	"""
	if not listing:
		frappe.throw(_("Ürün zorunlu"))
	page = max(1, cint(page))
	page_size = min(50, max(1, cint(page_size)))
	order_by = VALID_SORTS.get(sort_by, VALID_SORTS["recent"])

	# Filter — Approved + (kendi Pending'lerim)
	# Login kullanıcı kendi Pending yorumunu görsün ki "kayboldu mu?"
	# şüphesi olmasın. Guest sadece Approved'ı görür.
	# DİKKAT: only_verified filtresi sadece public/Approved yorumlara uygulanır.
	# Kendi Pending yorumumuz verified olmasa da kendine görünmelidir; aksi
	# halde "filtreyi açtım, yorumum kayboldu" şüphesi olur.
	user = frappe.session.user
	is_guest = user == "Guest"
	verified_only = bool(cint(only_verified))

	if is_guest:
		approved_clause = "status = 'Approved'"
		if verified_only:
			approved_clause += " AND is_verified_purchase = 1"
		where_clause = f"listing = %(listing)s AND {approved_clause}"
		params = {"listing": listing}
	else:
		# Approved (filtreye uyan) OR (kendi Pending'im — filtre uygulanmaz)
		approved_clause = "status = 'Approved'"
		if verified_only:
			approved_clause += " AND is_verified_purchase = 1"
		where_clause = (
			"listing = %(listing)s AND ("
			f"  ({approved_clause})"
			"  OR (status = 'Pending' AND reviewer_user = %(user)s)"
			")"
		)
		params = {"listing": listing, "user": user}

	total_row = frappe.db.sql(
		f"SELECT COUNT(*) FROM `tabListing Review` WHERE {where_clause}",
		params,
	)
	total = int(total_row[0][0]) if total_row else 0

	limit = page_size
	offset = (page - 1) * page_size
	reviews = frappe.db.sql(
		f"""
		SELECT
			name, reviewer_user, reviewer_display_name, rating, title, body,
			status, is_verified_purchase, is_kyb_verified, published_at,
			edit_count, submitted_at, product_quality_rating, service_rating,
			shipping_rating, spec_match_rating, documentation_rating,
			video_url, helpful_count, not_helpful_count,
			seller_reply, seller_reply_at, seller_reply_within_hours
		FROM `tabListing Review`
		WHERE {where_clause}
		ORDER BY
			CASE WHEN status='Pending' AND reviewer_user=%(_self_user)s THEN 0 ELSE 1 END,
			{order_by}
		LIMIT %(_limit)s OFFSET %(_offset)s
		""",
		{
			**params,
			"_self_user": user if not is_guest else "__none__",
			"_limit": limit,
			"_offset": offset,
		},
		as_dict=True,
	)

	# Görselleri batch çek (her review için ayrı sorgu yerine tek seferde)
	# autoincrement Listing Review.name int olarak gelir; parent SQL'de
	# string olarak saklanır. Dict eşleşmesi için her ikisini de str() ile
	# normalize ediyoruz.
	review_names = [str(r["name"]) for r in reviews]
	images_by_review = {}
	if review_names:
		image_rows = frappe.get_all(
			"Listing Review Image",
			filters={"parent": ["in", review_names], "parenttype": "Listing Review"},
			fields=["parent", "image", "caption", "width", "height", "idx"],
			order_by="parent ASC, idx ASC",
		)
		for img in image_rows:
			images_by_review.setdefault(str(img["parent"]), []).append(
				{
					"image": img["image"],
					"caption": img.get("caption"),
					"width": img.get("width"),
					"height": img.get("height"),
				}
			)

	from datetime import timedelta

	from frappe.utils import get_datetime, now_datetime

	now_ts = now_datetime()
	edit_window_hours = 24
	for r in reviews:
		r["edited"] = bool(r.get("edit_count") or 0)
		r.pop("edit_count", None)
		r["images"] = images_by_review.get(str(r["name"]), [])
		r["aspects"] = {
			"product_quality": r.pop("product_quality_rating", None),
			"service": r.pop("service_rating", None),
			"shipping": r.pop("shipping_rating", None),
			"spec_match": r.pop("spec_match_rating", None),
			"documentation": r.pop("documentation_rating", None),
		}
		r["reply"] = (
			{
				"body": r.get("seller_reply"),
				"at": r.get("seller_reply_at"),
				"within_hours": r.get("seller_reply_within_hours"),
			}
			if r.get("seller_reply")
			else None
		)
		for f in ("seller_reply", "seller_reply_at", "seller_reply_within_hours"):
			r.pop(f, None)
		# Frontend "Onay bekliyor" rozetini gösterebilsin
		is_mine = (not is_guest) and r.get("reviewer_user") == user
		r["is_own_pending"] = is_mine and r.get("status") == "Pending"
		r["is_mine"] = is_mine
		# Edit penceresi: kendi yorumum + 24 saat içinde (her düzenleme tekrar
		# moderasyona gittiği için ayrı bir edit-sayısı limiti yok).
		can_edit = False
		if is_mine and r.get("submitted_at"):
			submitted = get_datetime(r["submitted_at"])
			if now_ts - submitted < timedelta(hours=edit_window_hours):
				can_edit = True
		r["can_edit"] = can_edit
		# reviewer_user kişisel bilgi — sadece kendi yorumum için döndür
		if not is_mine:
			r.pop("reviewer_user", None)
	return {"reviews": reviews, "total": total, "page": page, "page_size": page_size}


@frappe.whitelist(allow_guest=True)
def get_listing_rating_summary(listing: str):
	"""Public — Listing cache field'larından özet."""
	if not listing:
		frappe.throw(_("Ürün zorunlu"))
	row = frappe.db.get_value(
		"Listing",
		listing,
		[
			"average_rating",
			"review_count",
			"rating_distribution",
			"quality_avg",
			"service_avg",
			"shipping_avg",
			"spec_match_avg",
			"documentation_avg",
		],
		as_dict=True,
	)
	if not row:
		frappe.throw(_("Ürün bulunamadı"), frappe.DoesNotExistError)

	dist = {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0}
	if row.rating_distribution:
		try:
			parsed = json.loads(row.rating_distribution)
			if isinstance(parsed, dict):
				for k in dist:
					dist[k] = int(parsed.get(k, 0) or 0)
		except (ValueError, TypeError):
			pass

	# Verified ve KYB sayaçları (Listing'de cache değil, anlık sayım)
	verified_count = frappe.db.count(
		"Listing Review",
		filters={"listing": listing, "status": "Approved", "is_verified_purchase": 1},
	)
	kyb_count = frappe.db.count(
		"Listing Review",
		filters={"listing": listing, "status": "Approved", "is_kyb_verified": 1},
	)

	# Faz 3: weighted rating + trust signals
	weighted_data = {}
	try:
		from tradehub_core.api.rating_engine import compute_weighted_rating

		weighted_data = compute_weighted_rating(listing)
	except Exception:
		weighted_data = {
			"weighted_rating": 0.0,
			"weighted_review_count": 0,
			"trust_signals": {},
		}

	return {
		"average_rating": float(row.average_rating or 0),
		"review_count": int(row.review_count or 0),
		"rating_distribution": dist,
		"verified_purchase_count": verified_count,
		"kyb_verified_count": kyb_count,
		"aspect_averages": {
			"product_quality": float(row.quality_avg or 0),
			"service": float(row.service_avg or 0),
			"shipping": float(row.shipping_avg or 0),
			"spec_match": float(row.spec_match_avg or 0),
			"documentation": float(row.documentation_avg or 0),
		},
		"weighted_rating": weighted_data.get("weighted_rating", 0.0),
		"weighted_review_count": weighted_data.get("weighted_review_count", 0),
		"trust_signals": weighted_data.get("trust_signals", {}),
	}


@frappe.whitelist()
def get_my_pending_reviews(page: int = 1, page_size: int = 10):
	"""Buyer endpoint — teslim alınmış ama henüz yorum yapılmamış order item'lar.

	Order.status in ('Tamamlandı', 'Kargoda') ve Order Item.has_review=0.
	"""
	_ensure_logged_in()
	user = frappe.session.user
	page = max(1, cint(page))
	page_size = min(50, max(1, cint(page_size)))
	offset = (page - 1) * page_size

	# Bench/SQL — Order ve Order Item join
	rows = frappe.db.sql(
		"""
		SELECT
			oi.name AS order_item,
			oi.listing AS listing,
			oi.listing_title AS listing_title,
			oi.image AS image,
			oi.quantity AS quantity,
			o.name AS `order`,
			o.order_date AS order_date,
			o.status AS order_status
		FROM `tabOrder Item` oi
		INNER JOIN `tabOrder` o ON o.name = oi.parent
		WHERE o.buyer = %(user)s
		  AND o.status IN ('Tamamlandı','Kargoda')
		  AND COALESCE(oi.has_review, 0) = 0
		ORDER BY o.order_date DESC, oi.idx ASC
		LIMIT %(limit)s OFFSET %(offset)s
		""",
		{"user": user, "limit": page_size, "offset": offset},
		as_dict=True,
	)
	total = frappe.db.sql(
		"""
		SELECT COUNT(*) AS cnt
		FROM `tabOrder Item` oi
		INNER JOIN `tabOrder` o ON o.name = oi.parent
		WHERE o.buyer = %(user)s
		  AND o.status IN ('Tamamlandı','Kargoda')
		  AND COALESCE(oi.has_review, 0) = 0
		""",
		{"user": user},
		as_dict=True,
	)
	return {"items": rows, "total": int(total[0].cnt) if total else 0}


# ---------------------------------------------------------------------------
# Admin moderation
# ---------------------------------------------------------------------------
@frappe.whitelist()
def get_order_item_listing(order_item: str):
	"""Form auto-fill helper — Order Item child doctype'a permission tanımı
	olmadığı için fetch_from veya frappe.db.get_value('Order Item') desk-API
	çağrısı 'Not permitted' verir. Bu endpoint server-side ignore_permissions
	ile listing değerini döndürür. Yalnız `name` field'ı olan, dönüş skalar.
	"""
	_ensure_logged_in()
	if not order_item:
		return {"listing": None}
	row = frappe.db.get_value(
		"Order Item",
		order_item,
		["listing", "parent", "parenttype"],
		as_dict=True,
	)
	if not row or row.parenttype != "Order":
		return {"listing": None}
	# M11 fix — IDOR guard: caller, order'ın alıcısı VEYA listing'in satıcısı ya da
	# admin olmalı. Eskiden herhangi bir kullanıcı keyfi order_item id'siyle
	# listing/order eşlemesini enumerate edebiliyordu.
	if not _is_admin():
		caller = frappe.session.user
		order_buyer = frappe.db.get_value("Order", row.parent, "buyer")
		if order_buyer != caller:
			seller_profile = frappe.db.get_value("Listing", row.listing, "seller_profile")
			caller_seller = frappe.db.get_value("Admin Seller Profile", {"user": caller}, "name")
			if not (seller_profile and caller_seller and seller_profile == caller_seller):
				frappe.throw(_("Bu kayda erişim yetkiniz yok"), frappe.PermissionError)
	return {"listing": row.listing, "order": row.parent}


@frappe.whitelist()
def admin_delete_listing_review(name: str):
	"""Cascade-aware delete: Frappe link guard'ı atlatır.

	Listing Review'a Link veren child doctype'lar (Review Risk Score,
	Review Helpful Vote, Review Abuse Report) önce silinir, sonra ana
	kayıt `ignore_links=True` ile silinir.
	"""
	_ensure_logged_in()
	if not _is_admin():
		frappe.throw(_("Bu işlem için yönetici yetkisi gerekli"), frappe.PermissionError)

	if not frappe.db.exists("Listing Review", name):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)

	# 1) Cascade silme — bağlı kayıtları temizle
	# Faz 2-6 boyunca eklenen tüm review-link'li child doctype'lar.
	# Yeni doctype eklendiğinde bu listeye ekleyin — yoksa orphan kayıt kalır.
	cascade_doctypes = (
		"Review Risk Score",
		"Review Helpful Vote",
		"Review Abuse Report",
		"Review Sentiment Analysis",  # Faz 6
		"Image Moderation Log",  # Faz 6
	)
	for child_dt in cascade_doctypes:
		if not frappe.db.table_exists(f"tab{child_dt}"):
			continue
		linked = frappe.get_all(child_dt, filters={"review": name}, pluck="name")
		for n in linked:
			frappe.delete_doc(child_dt, n, ignore_permissions=True, force=True)

	# 2) Ana kaydı sil — link guard'ı atlat
	doc = frappe.get_doc("Listing Review", name)
	listing_name = doc.listing
	order_item = doc.order_item

	# Order Item.has_review temizliği (on_trash'in normalde yapacağı şey)
	if order_item:
		frappe.db.set_value(
			"Order Item",
			order_item,
			{"has_review": 0, "review": None},
			update_modified=False,
		)

	frappe.delete_doc(
		"Listing Review",
		name,
		ignore_permissions=True,
		force=True,
		delete_permanently=True,
	)

	# 3) Listing rating cache'i yenile
	try:
		recompute_listing_rating(listing_name)
	except Exception:
		pass

	frappe.db.commit()
	return {"success": True, "deleted": name}


@frappe.whitelist()
def get_admin_review_list(
	status: str | None = None,
	listing: str | None = None,
	search: str | None = None,
	reviewer: str | None = None,
	min_rating: int | None = None,
	page: int = 1,
	page_size: int = 20,
):
	"""Admin/Seller — moderasyon paneli için yorum listesi.

	Admin tüm yorumları görür, Seller sadece kendi listing'lerinin yorumlarını.

	Args:
		status: 'Pending' | 'Approved' | 'Rejected' | 'Hidden' | 'all' | None
		listing: belirli bir listing'in yorumları
		search: title/body'de LIKE arama (case-insensitive)
		reviewer: reviewer_user e-postası LIKE
		min_rating: minimum rating filter (1-5)
	"""
	_ensure_logged_in()
	user = frappe.session.user

	filters: dict = {}
	if status and status != "all":
		filters["status"] = status
	if listing:
		filters["listing"] = listing
	if reviewer:
		filters["reviewer_user"] = ["like", f"%{reviewer}%"]
	if min_rating is not None:
		try:
			mr = int(min_rating)
			if 1 <= mr <= 5:
				filters["rating"] = [">=", mr]
		except (ValueError, TypeError):
			pass

	# Seller scope — kendi listing'lerini filtrele
	if not _is_admin(user):
		seller_profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		if not seller_profile:
			return {"reviews": [], "total": 0, "page": 1, "page_size": page_size}
		listings = frappe.get_all("Listing", filters={"seller_profile": seller_profile}, pluck="name")
		if not listings:
			return {"reviews": [], "total": 0, "page": 1, "page_size": page_size}
		# `listing` filter override (seller'ın izin verilen scope'a)
		if "listing" in filters and isinstance(filters["listing"], str):
			# Eğer seller specific listing istiyor ama o listing'i kendisinin değilse → boş
			if filters["listing"] not in listings:
				return {"reviews": [], "total": 0, "page": 1, "page_size": page_size}
		else:
			filters["listing"] = ["in", listings]

	# Search filter — title VEYA body'de LIKE
	# Frappe filter syntax'ında OR yok; or_filters parametresi ile yapılır
	or_filters = None
	if search:
		s = f"%{search}%"
		or_filters = [
			["Listing Review", "title", "like", s],
			["Listing Review", "body", "like", s],
		]

	page = max(1, cint(page))
	page_size = min(100, max(1, cint(page_size)))

	# frappe.db.count or_filters'ı desteklemez — manuel olarak get_all + len() kullan
	if or_filters:
		total_rows = frappe.get_all(
			"Listing Review",
			filters=filters,
			or_filters=or_filters,
			fields=["name"],
			limit_page_length=0,
		)
		total = len(total_rows)
	else:
		total = frappe.db.count("Listing Review", filters=filters)

	get_all_kwargs = {
		"filters": filters,
		"fields": [
			"name",
			"listing",
			"rating",
			"title",
			"body",
			"status",
			"rejected_reason",
			"reviewer_user",
			"reviewer_display_name",
			"is_verified_purchase",
			"is_kyb_verified",
			"helpful_count",
			"not_helpful_count",
			"submitted_at",
			"published_at",
			"edit_count",
			"abuse_report_count",
			"current_stage",
		],
		"order_by": "FIELD(status, 'Pending', 'Approved', 'Hidden', 'Rejected'), submitted_at DESC",
		"limit_start": (page - 1) * page_size,
		"limit_page_length": page_size,
	}
	if or_filters:
		get_all_kwargs["or_filters"] = or_filters
	rows = frappe.get_all("Listing Review", **get_all_kwargs)

	# Listing başlıkları + görseller batch fetch
	if rows:
		listing_names = list({r["listing"] for r in rows if r.get("listing")})
		titles = {}
		if listing_names:
			lrows = frappe.get_all(
				"Listing", filters={"name": ["in", listing_names]}, fields=["name", "title"]
			)
			titles = {r["name"]: r["title"] for r in lrows}
		# Review images batch
		review_names = [r["name"] for r in rows]
		images_by_review = {}
		img_rows = frappe.get_all(
			"Listing Review Image",
			filters={"parent": ["in", [str(n) for n in review_names]]},
			fields=["parent", "image", "caption"],
		)
		for img in img_rows:
			images_by_review.setdefault(str(img["parent"]), []).append(
				{
					"image": img["image"],
					"caption": img.get("caption"),
				}
			)

		# Şikayet (abuse) detaylarını batch fetch — admin moderasyonda
		# kim/neden/ne zaman/not görmek için
		abuse_by_review: dict[str, list[dict]] = {}
		abuse_rows = frappe.get_all(
			"Review Abuse Report",
			filters={"review": ["in", [str(n) for n in review_names]]},
			fields=["name", "review", "reporter", "reason", "note", "creation", "resolved"],
			order_by="creation DESC",
		)
		for a in abuse_rows:
			abuse_by_review.setdefault(str(a["review"]), []).append(
				{
					"name": a["name"],
					"reporter": a["reporter"],
					"reason": a["reason"],
					"note": a.get("note") or "",
					"created_at": a["creation"],
					"resolved": bool(a.get("resolved")),
				}
			)

		for r in rows:
			r["listing_title"] = titles.get(r.get("listing"), r.get("listing"))
			r["images"] = images_by_review.get(str(r["name"]), [])
			r["abuse_reports"] = abuse_by_review.get(str(r["name"]), [])

	return {"reviews": rows, "total": total, "page": page, "page_size": page_size}


@frappe.whitelist()
def get_admin_review_counts():
	"""Moderasyon paneli için status başına sayılar."""
	_ensure_logged_in()
	user = frappe.session.user

	base_filter = {}
	if not _is_admin(user):
		seller_profile = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		if not seller_profile:
			return {"pending": 0, "approved": 0, "rejected": 0, "hidden": 0, "total": 0}
		listings = frappe.get_all("Listing", filters={"seller_profile": seller_profile}, pluck="name")
		if not listings:
			return {"pending": 0, "approved": 0, "rejected": 0, "hidden": 0, "total": 0}
		base_filter = {"listing": ["in", listings]}

	pending = frappe.db.count("Listing Review", filters={**base_filter, "status": "Pending"})
	approved = frappe.db.count("Listing Review", filters={**base_filter, "status": "Approved"})
	rejected = frappe.db.count("Listing Review", filters={**base_filter, "status": "Rejected"})
	hidden = frappe.db.count("Listing Review", filters={**base_filter, "status": "Hidden"})
	return {
		"pending": pending,
		"approved": approved,
		"rejected": rejected,
		"hidden": hidden,
		"total": pending + approved + rejected + hidden,
	}


@frappe.whitelist()
@rate_limit(max_calls=30, window_seconds=60, scope="admin_dismiss_abuse")
def admin_dismiss_abuse_report(name: str, note: str | None = None):
	"""Admin: bir şikayet kaydını geçersiz say (resolved=1) ve yorumdaki
	abuse_report_count'u yeniden hesapla. Eğer yorumun şikayet sayısı eşiğin
	altına düşerse ve status='Hidden' ise admin manuel 'Tekrar Yayınla'
	yapabilir (bu fonksiyon status'u değiştirmez)."""
	_ensure_logged_in()
	if not _is_admin():
		frappe.throw(
			_("Bu işlem için yönetici yetkisi gerekli"),
			frappe.PermissionError,
		)
	if not name or not frappe.db.exists("Review Abuse Report", name):
		frappe.throw(_("Şikayet kaydı bulunamadı"), frappe.DoesNotExistError)

	review = frappe.db.get_value("Review Abuse Report", name, "review")
	frappe.db.set_value(
		"Review Abuse Report",
		name,
		{
			"resolved": 1,
			"resolution_note": note or _("Admin tarafından geçersiz sayıldı"),
		},
		update_modified=False,
	)
	# Yorumun açık (resolved=0) şikayet sayısını yeniden hesapla
	open_count = frappe.db.count(
		"Review Abuse Report",
		filters={"review": review, "resolved": 0},
	)
	frappe.db.set_value(
		"Listing Review",
		review,
		"abuse_report_count",
		open_count,
		update_modified=False,
	)
	frappe.db.commit()
	return {
		"success": True,
		"review": review,
		"new_abuse_count": open_count,
	}


@frappe.whitelist()
def admin_moderate_review(name: str, action: str, reason: str | None = None):
	_ensure_logged_in()
	if not _is_admin():
		frappe.throw(_("Bu işlem için yönetici yetkisi gerekli"), frappe.PermissionError)

	action = (action or "").lower().strip()
	if action not in {"approve", "reject", "hide", "unhide"}:
		frappe.throw(_("Geçersiz aksiyon"))

	doc = frappe.get_doc("Listing Review", name)

	if action == "approve":
		doc.status = "Approved"
		doc.rejected_reason = None
	elif action == "reject":
		if not reason:
			frappe.throw(_("Red için neden zorunludur"))
		doc.status = "Rejected"
		doc.rejected_reason = reason
	elif action == "hide":
		doc.status = "Hidden"
	elif action == "unhide":
		doc.status = "Approved"
		# Yorum admin kararıyla geri yayınlandığında mevcut tüm şikayetleri
		# "geçersiz" olarak işaretle ve sayacı sıfırla. Aksi halde 1 yeni
		# şikayet (4 toplam) yorumu otomatik tekrar gizler — admin kararı
		# atlatılır. Yeni gelen şikayetler sıfırdan sayılır.
		frappe.db.sql(
			"""
			UPDATE `tabReview Abuse Report`
			SET resolved=1, resolution_note=%(note)s
			WHERE review=%(review)s AND resolved=0
			""",
			{
				"review": name,
				"note": _("Admin tarafından 'Tekrar Yayınla' ile geçersiz sayıldı"),
			},
		)
		doc.abuse_report_count = 0

	doc.save(ignore_permissions=True)
	frappe.db.commit()

	# Not: Yorum sahibine bildirim controller'daki on_update zincirinde
	# (Listing Review._notify_buyer_published/rejected/hidden) gönderilir.
	# Burada ikinci bir notify çağırırsak buyer aynı eylem için 2 bildirim alır.

	return {"success": True, "status": doc.status}


@frappe.whitelist()
def admin_bulk_moderate(names, action: str, reason: str | None = None):
	"""Toplu moderasyon — birden çok review'i tek seferde Approve/Reject/Hide."""
	_ensure_logged_in()
	if not _is_admin():
		frappe.throw(_("Bu işlem için yönetici yetkisi gerekli"), frappe.PermissionError)

	if isinstance(names, str):
		try:
			names = json.loads(names)
		except (ValueError, TypeError):
			names = [names]
	if not isinstance(names, list) or not names:
		frappe.throw(_("Geçerli kayıt listesi gönderin"))

	results = []
	for n in names:
		try:
			r = admin_moderate_review(name=n, action=action, reason=reason)
			results.append({"name": n, "ok": True, "status": r.get("status")})
		except Exception as e:
			results.append({"name": n, "ok": False, "error": str(e)})
	return {"results": results, "total": len(names)}


# ---------------------------------------------------------------------------
# Faz 2 — Helpful Vote
# ---------------------------------------------------------------------------
def recompute_review_helpful_counts(review_name: str, exclude_vote_name: str | None = None):
	"""Listing Review için helpful/not_helpful sayaçlarını DB'den yeniden hesaplar."""
	if not review_name or not frappe.db.exists("Listing Review", review_name):
		return
	params = [review_name]
	exclude_clause = ""
	if exclude_vote_name:
		exclude_clause = " AND name != %s"
		params.append(exclude_vote_name)

	row = frappe.db.sql(
		f"""
		SELECT
			SUM(CASE WHEN vote='helpful' THEN 1 ELSE 0 END) AS helpful_count,
			SUM(CASE WHEN vote='not_helpful' THEN 1 ELSE 0 END) AS not_helpful_count
		FROM `tabReview Helpful Vote`
		WHERE review = %s {exclude_clause}
		""",
		params,
		as_dict=True,
	)
	helpful = int((row[0].helpful_count or 0) if row else 0)
	not_helpful = int((row[0].not_helpful_count or 0) if row else 0)
	frappe.db.set_value(
		"Listing Review",
		review_name,
		{"helpful_count": helpful, "not_helpful_count": not_helpful},
		update_modified=False,
	)


@frappe.whitelist()
def vote_review_helpful(review: str, vote: str):
	"""Buyer/giriş yapmış kullanıcı bir yoruma faydalı / faydalı değil oyu verir.

	Aynı kullanıcı yeniden çağırırsa oyu günceller.
	"""
	_ensure_logged_in()
	user = frappe.session.user
	if vote not in ("helpful", "not_helpful"):
		frappe.throw(_("Geçersiz oy"))

	if not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)

	# Status check: yalnız Approved yoruma oy verilebilir
	status = frappe.db.get_value("Listing Review", review, "status")
	if status != "Approved":
		frappe.throw(_("Yalnızca yayında olan yorumlara oy verebilirsiniz"))

	# Kendi yorumuna oy vermek yasak
	reviewer_user = frappe.db.get_value("Listing Review", review, "reviewer_user")
	if reviewer_user == user:
		frappe.throw(_("Kendi yorumunuza oy veremezsiniz"), frappe.PermissionError)

	existing = frappe.db.get_value("Review Helpful Vote", {"review": review, "voter": user}, "name")
	if existing:
		doc = frappe.get_doc("Review Helpful Vote", existing)
		if doc.vote == vote:
			return {"success": True, "name": doc.name, "vote": doc.vote, "changed": False}
		doc.vote = vote
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Review Helpful Vote")
		doc.review = review
		doc.voter = user
		doc.vote = vote
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name, "vote": doc.vote, "changed": True}


@frappe.whitelist()
def unvote_review(review: str):
	"""Verilen oyu geri al."""
	_ensure_logged_in()
	user = frappe.session.user
	existing = frappe.db.get_value("Review Helpful Vote", {"review": review, "voter": user}, "name")
	if not existing:
		return {"success": True, "removed": False}
	frappe.delete_doc("Review Helpful Vote", existing, ignore_permissions=True, force=True)
	frappe.db.commit()
	return {"success": True, "removed": True}


# ---------------------------------------------------------------------------
# Faz 2 — Abuse Report + threshold
# ---------------------------------------------------------------------------
def recompute_abuse_count_and_threshold(review_name: str, exclude_report_name: str | None = None):
	"""Listing Review.abuse_report_count'u günceller; eşik aşılırsa otomatik Hidden."""
	if not review_name or not frappe.db.exists("Listing Review", review_name):
		return
	params = [review_name]
	exclude_clause = ""
	if exclude_report_name:
		exclude_clause = " AND name != %s"
		params.append(exclude_report_name)

	count = (
		frappe.db.sql(
			f"""
			SELECT COUNT(*) FROM `tabReview Abuse Report`
			WHERE review = %s AND COALESCE(resolved, 0) = 0 {exclude_clause}
			""",
			params,
		)[0][0]
		or 0
	)

	current = frappe.db.get_value(
		"Listing Review", review_name, ["status", "abuse_report_count"], as_dict=True
	)
	frappe.db.set_value(
		"Listing Review",
		review_name,
		"abuse_report_count",
		int(count),
		update_modified=False,
	)

	# Eşik aşıldıysa ve hâlâ Approved ise → Hidden + admin'e bildirim.
	# DİKKAT: doc.save() validate() çağırır → _guard_verified_purchase gibi
	# alıcı kontrolleri farklı kullanıcı bağlamında patlar (auto-hide
	# 3. şikayetin owner'ı verified buyer olmayabilir — örn. başka satıcı,
	# admin vb.). Bu yüzden save() yerine doğrudan set_value kullanıyoruz.
	# Statüs değişiklik trigger'larını manuel olarak burada yönetiyoruz.
	if count >= ABUSE_AUTO_HIDE_THRESHOLD and current and current.status == "Approved":
		frappe.db.set_value(
			"Listing Review",
			review_name,
			"status",
			"Hidden",
			update_modified=False,
		)
		# Listing rating cache'i yenile — Hidden olan yorum artık ortalamaya
		# katkı vermemeli.
		try:
			listing_name = frappe.db.get_value("Listing Review", review_name, "listing")
			if listing_name:
				recompute_listing_rating(listing_name)
		except Exception:
			frappe.log_error(
				title="auto_hide_recompute_rating_failed",
				message=f"review={review_name}",
			)
		_notify_admins_threshold_hit(review_name, int(count))


def _notify_admins_threshold_hit(review_name: str, count: int):
	from tradehub_core.utils.notify import notify

	admins = frappe.get_all(
		"Has Role",
		filters={"role": ["in", ["System Manager", "Marketplace Admin"]], "parenttype": "User"},
		fields=["parent"],
	)
	for admin in {a.parent for a in admins}:
		try:
			notify(
				recipient_user=admin,
				recipient_role="admin",
				type="review",
				title=_("Yorum Otomatik Gizlendi"),
				message=_("{0} ihbar eşiği aşıldı ve yorum gizlendi.").format(count),
				action_url=f"/app/listing-review/{review_name}",
				reference_doctype="Listing Review",
				reference_name=review_name,
			)
		except Exception:
			pass


@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=300, scope="review_abuse_report_direct")
def report_review_abuse(review: str, reason: str, note: str | None = None):
	"""Bir yorum hakkında ihbar oluşturur.

	Rate-limit: 10 çağrı / 5 dakika (kullanıcı başına).
	Storefront wrapper'ı (`storefront_api.report_abuse`) ayrı bir scope ile
	korumalı; direkt API çağrıları için bu decorator brute-force'u engeller.
	"""
	_ensure_logged_in()
	user = frappe.session.user
	if not frappe.db.exists("Listing Review", review):
		frappe.throw(_("Yorum bulunamadı"), frappe.DoesNotExistError)

	valid_reasons = {"Off-topic", "Spam", "Hate Speech", "Personal Info", "Fake", "Other"}
	if reason not in valid_reasons:
		frappe.throw(_("Geçersiz neden"))

	# Aynı kullanıcı tekrar ihbar edemez
	if frappe.db.exists("Review Abuse Report", {"review": review, "reporter": user}):
		frappe.throw(_("Bu yorumu zaten ihbar ettiniz"))

	doc = frappe.new_doc("Review Abuse Report")
	doc.review = review
	doc.reporter = user
	doc.reason = reason
	doc.note = (note or "").strip() or None
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name}


# ---------------------------------------------------------------------------
# Faz 2 — Seller Reply
# ---------------------------------------------------------------------------
@frappe.whitelist()
def submit_seller_reply(review: str, reply: str):
	"""Satıcı kendi ürününün yorumuna yanıt yazar."""
	_ensure_logged_in()
	if not reply or not reply.strip():
		frappe.throw(_("Yanıt boş olamaz"))
	doc = frappe.get_doc("Listing Review", review)
	# Kontrol: bu satıcının ürünü mü?
	seller_user = frappe.db.get_value("Admin Seller Profile", doc.seller, "user") if doc.seller else None
	if not _is_admin() and seller_user != frappe.session.user:
		frappe.throw(_("Bu yoruma yalnızca ürünün satıcısı yanıt yazabilir"), frappe.PermissionError)
	if doc.seller_reply and doc.seller_reply.strip():
		frappe.throw(_("Yanıt zaten mevcut. Düzenlemek için update_seller_reply kullanın"))

	doc.seller_reply = reply.strip()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {
		"success": True,
		"name": doc.name,
		"seller_reply_at": doc.seller_reply_at,
		"seller_reply_within_hours": doc.seller_reply_within_hours,
	}


@frappe.whitelist()
def update_seller_reply(review: str, reply: str):
	"""Mevcut yanıtı güncelle (24 saat içinde)."""
	_ensure_logged_in()
	if not reply or not reply.strip():
		frappe.throw(_("Yanıt boş olamaz"))
	doc = frappe.get_doc("Listing Review", review)
	seller_user = frappe.db.get_value("Admin Seller Profile", doc.seller, "user") if doc.seller else None
	if not _is_admin() and seller_user != frappe.session.user:
		frappe.throw(_("Yanıtı yalnızca satıcı düzenleyebilir"), frappe.PermissionError)
	if not doc.seller_reply:
		frappe.throw(_("Henüz yanıt yazılmadı"))
	doc.seller_reply = reply.strip()
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True, "name": doc.name}


@frappe.whitelist()
def delete_seller_reply(review: str):
	"""Yanıtı kaldır."""
	_ensure_logged_in()
	doc = frappe.get_doc("Listing Review", review)
	seller_user = frappe.db.get_value("Admin Seller Profile", doc.seller, "user") if doc.seller else None
	if not _is_admin() and seller_user != frappe.session.user:
		frappe.throw(_("Yanıtı yalnızca satıcı veya yönetici silebilir"), frappe.PermissionError)
	doc.seller_reply = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	return {"success": True}
