"""Faz 5 — Storefront Public API.

Mobile-first storefront için optimize edilmiş public endpoint'ler.
Rate-limited ve cached. Mevcut review/qa/translation/rating_engine
modüllerini storefront formatına dönüştürerek tek noktadan sunar.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from tradehub_core.api.rate_limit import rate_limit

DEFAULT_PAGE_SIZE = 10
MAX_PAGE_SIZE = 50


def _ensure_logged_in():
	if frappe.session.user == "Guest":
		frappe.throw(_("Giriş yapın"), frappe.AuthenticationError)


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW PAGE (zengin storefront response)
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=60, window_seconds=60, scope="sf_review_page")
def get_storefront_review_page(
	listing: str,
	page: int = 1,
	page_size: int = DEFAULT_PAGE_SIZE,
	sort_by: str = "recent",
	only_verified: int = 0,
):
	"""Mobile-first review page response — summary + page + Q&A count.

	Tek API çağrısı ile review widget'ı render edilebilir.
	"""
	if not listing or not frappe.db.exists("Listing", listing):
		frappe.throw(_("Ürün bulunamadı"), frappe.DoesNotExistError)

	from tradehub_core.api.review import (
		get_listing_rating_summary,
		list_listing_reviews,
	)

	page = max(1, cint(page))
	page_size = min(MAX_PAGE_SIZE, max(1, cint(page_size)))

	summary = get_listing_rating_summary(listing=listing)
	listed = list_listing_reviews(
		listing=listing,
		page=page,
		page_size=page_size,
		sort_by=sort_by,
		only_verified=cint(only_verified),
	)

	# Q&A count
	q_total = frappe.db.count(
		"Listing Question",
		filters={"listing": listing, "status": "Answered"},
	)

	# Reputation per review — review'in reviewer_user'ı üzerinden
	review_names = [r["name"] for r in listed["reviews"]]
	reviewer_users = {}
	if review_names:
		rev_rows = frappe.get_all(
			"Listing Review",
			filters={"name": ["in", review_names]},
			fields=["name", "reviewer_user"],
		)
		reviewer_users = {str(r["name"]): r["reviewer_user"] for r in rev_rows}
	reputations = {}
	if reviewer_users:
		users = list(set(reviewer_users.values()))
		rep_rows = frappe.get_all(
			"Reviewer Reputation",
			filters={"user": ["in", users]},
			fields=["user", "tier", "score"],
		)
		reputations = {r["user"]: {"tier": r["tier"], "score": r["score"]} for r in rep_rows}

	for r in listed["reviews"]:
		ru = reviewer_users.get(str(r["name"]))
		r["reviewer"] = reputations.get(ru, {"tier": "Newcomer", "score": 50})

	return {
		"summary": summary,
		"reviews": listed["reviews"],
		"total": listed["total"],
		"page": page,
		"page_size": page_size,
		"qa_total": int(q_total),
	}


# ─────────────────────────────────────────────────────────────────────────────
# REVIEW ELIGIBILITY (storefront yorum yaz butonu için)
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist()
@rate_limit(max_calls=30, window_seconds=60, scope="sf_review_eligibility")
def get_review_eligibility(listing: str):
	"""Listing-bazlı yorum yapma uygunluğu.

	Returns:
		{
		  "can_review": bool,
		  "order_items": [{name, order, order_date, quantity}],
		  "already_reviewed_count": int,
		  "reason": str | None,  # 'not_logged_in' | 'no_purchase' | None
		  "user_logged_in": bool
		}
	"""
	if not listing:
		frappe.throw(_("Listing zorunlu"))
	if frappe.session.user == "Guest":
		return {
			"can_review": False,
			"order_items": [],
			"already_reviewed_count": 0,
			"reason": "not_logged_in",
			"user_logged_in": False,
		}
	user = frappe.session.user

	# Self-review guard — satıcı kendi ürününe yorum yazamaz.
	# Submit anında zaten Listing Review._guard_self_review() reddediyor,
	# ama burada erken döndürmek "Yorum Yaz" butonu disabled gelmesini sağlar
	# ve kullanıcı boşa form doldurmaz.
	seller_profile = frappe.db.get_value("Listing", listing, "seller_profile")
	if seller_profile:
		seller_user = frappe.db.get_value("Admin Seller Profile", seller_profile, "user")
		if seller_user and seller_user == user:
			return {
				"can_review": False,
				"order_items": [],
				"already_reviewed_count": 0,
				"reason": "own_listing",
				"user_logged_in": True,
			}

	# Tüm satın alma kalemleri (yorumlanmış + yorumlanmamış)
	all_rows = frappe.db.sql(
		"""
		SELECT
			oi.name AS name,
			oi.parent AS `order`,
			o.order_date AS order_date,
			oi.quantity AS quantity,
			COALESCE(oi.has_review, 0) AS has_review
		FROM `tabOrder Item` oi
		INNER JOIN `tabOrder` o ON o.name = oi.parent
		WHERE o.buyer = %(user)s
		  AND oi.listing = %(listing)s
		  AND o.status IN ('Tamamlandı','Kargoda')
		ORDER BY o.order_date DESC, oi.idx ASC
		""",
		{"user": user, "listing": listing},
		as_dict=True,
	)
	pending = [r for r in all_rows if not r.has_review]
	already_reviewed = len(all_rows) - len(pending)
	can_review = len(pending) > 0
	reason = None if can_review else ("no_purchase" if not all_rows else "already_reviewed")
	return {
		"can_review": can_review,
		"order_items": [
			{
				"name": r.name,
				"order": r["order"],
				"order_date": str(r.order_date) if r.order_date else None,
				"quantity": r.quantity,
			}
			for r in pending
		],
		"already_reviewed_count": already_reviewed,
		"reason": reason,
		"user_logged_in": True,
	}


# ─────────────────────────────────────────────────────────────────────────────
# MY REVIEWS (buyer dashboard için)
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist()
@rate_limit(max_calls=30, window_seconds=60, scope="sf_my_reviews")
def get_my_reviews(page: int = 1, page_size: int = 10):
	"""Login'li buyer'ın kendi yorumlarını listeler."""
	_ensure_logged_in()
	user = frappe.session.user
	page = max(1, cint(page))
	page_size = min(50, max(1, cint(page_size)))
	filters = {"reviewer_user": user}
	total = frappe.db.count("Listing Review", filters=filters)
	rows = frappe.get_all(
		"Listing Review",
		filters=filters,
		fields=[
			"name",
			"listing",
			"rating",
			"title",
			"body",
			"status",
			"submitted_at",
			"published_at",
			"helpful_count",
			"current_stage",
			"related_dispute",
		],
		order_by="submitted_at DESC",
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
	)
	return {"reviews": rows, "total": total, "page": page, "page_size": page_size}


# ─────────────────────────────────────────────────────────────────────────────
# RATE-LIMITED FORM SUBMITS
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=60, scope="sf_update_review")
def update_review(name: str, rating=None, title: str | None = None, body: str | None = None):
	"""Storefront wrapper — buyer kendi yorumunu 24h içinde düzenler."""
	from tradehub_core.api.review import update_listing_review

	return update_listing_review(name=name, rating=rating, title=title, body=body)


@frappe.whitelist()
@rate_limit(max_calls=5, window_seconds=60, scope="sf_submit_review")
def submit_review(
	order_item: str,
	rating,
	body: str,
	title: str | None = None,
	images=None,
	video_url: str | None = None,
	aspects=None,
	template_answers=None,
):
	"""Storefront review submit + opsiyonel kategori şablonu cevapları."""
	from tradehub_core.api.review import submit_listing_review

	res = submit_listing_review(
		order_item=order_item,
		rating=rating,
		body=body,
		title=title,
		images=images,
		video_url=video_url,
		aspects=aspects,
	)

	# Template answers varsa kaydet
	if template_answers and res.get("success"):
		try:
			from tradehub_core.api.templates import submit_template_answers

			submit_template_answers(review=res["name"], answers=template_answers)
		except Exception:
			pass
	return res


@frappe.whitelist()
@rate_limit(max_calls=5, window_seconds=60, scope="sf_submit_question")
def submit_question(listing: str, question: str):
	from tradehub_core.api.qa import submit_listing_question

	return submit_listing_question(listing=listing, question=question)


@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=60, scope="sf_submit_answer")
def submit_answer(question: str, answer: str):
	from tradehub_core.api.qa import submit_question_answer

	return submit_question_answer(question=question, answer=answer)


@frappe.whitelist()
@rate_limit(max_calls=20, window_seconds=60, scope="sf_helpful_vote")
def vote_helpful(review: str, vote: str):
	from tradehub_core.api.review import vote_review_helpful

	return vote_review_helpful(review=review, vote=vote)


@frappe.whitelist()
@rate_limit(max_calls=20, window_seconds=60, scope="sf_qa_vote")
def vote_qa_helpful(target_type: str, target_id: str):
	"""Storefront wrapper — Q&A soru/cevap için faydalı oy."""
	from tradehub_core.api.qa import vote_question_helpful

	return vote_question_helpful(target_type=target_type, target_id=target_id)


@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=60, scope="sf_translate")
def translate_review(review: str, target_lang: str = "tr"):
	"""Storefront çeviri endpoint'i — rate-limited."""
	from tradehub_core.api.translation import get_review_translation

	return get_review_translation(review=review, target_lang=target_lang)


@frappe.whitelist()
@rate_limit(max_calls=10, window_seconds=300, scope="sf_abuse_report")
def report_abuse(review: str, reason: str, note: str | None = None):
	from tradehub_core.api.review import report_review_abuse

	return report_review_abuse(review=review, reason=reason, note=note)


# ─────────────────────────────────────────────────────────────────────────────
# Q&A storefront
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=60, window_seconds=60, scope="sf_qa_page", per_user=False)
def get_qa_page(listing: str, page: int = 1, page_size: int = 10):
	from tradehub_core.api.qa import list_listing_questions

	return list_listing_questions(
		listing=listing, page=page, page_size=page_size, sort_by="recent", status="Answered"
	)


# ─────────────────────────────────────────────────────────────────────────────
# Category template (form için)
# ─────────────────────────────────────────────────────────────────────────────
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=60, window_seconds=60, scope="sf_template", per_user=False)
def get_category_template(listing: str):
	from tradehub_core.api.templates import get_category_template as _get

	return _get(listing=listing)
