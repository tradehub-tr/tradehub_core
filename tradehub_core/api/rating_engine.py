"""Faz 3 — ML-Weighted Rating Engine.

Listing.weighted_rating = SUM(rating × weight) / SUM(weight)

weight = base_weight (1.0)
       × verified_purchase_multi   (1.0 / 0.3)
       × kyb_buyer_multi           (KYB ✅: 1.5)
       × order_size_multi          (büyük sipariş bonusu, 1.0..1.3)
       × recency_decay             (lineer 0-12 ay 1.0 → 0.5, sonra 0.5)
       × reviewer_tier_multi       (1.0..2.0)
       × risk_penalty              (weighted_contribution: 0.1/0.5/1.0)
"""

from __future__ import annotations

import frappe
from frappe.utils import flt, get_datetime, now_datetime

# Çarpanlar
VERIFIED_PURCHASE_HIGH = 1.0
VERIFIED_PURCHASE_LOW = 0.3
KYB_BUYER_BONUS = 1.5

ORDER_SIZE_TIERS = (
	(10000, 1.3),  # 10K+ TRY: +30%
	(5000, 1.2),
	(1000, 1.1),
	(0, 1.0),
)

RECENCY_MONTHS_FULL = 6  # 0-6 ay tam ağırlık
RECENCY_MONTHS_MIN = 12  # 12 ay sonra min
RECENCY_MIN_FACTOR = 0.5


def _verified_purchase_multi(review: dict) -> float:
	return VERIFIED_PURCHASE_HIGH if review.get("is_verified_purchase") else VERIFIED_PURCHASE_LOW


def _kyb_multi(review: dict) -> float:
	return KYB_BUYER_BONUS if review.get("is_kyb_verified") else 1.0


def _order_size_multi(review: dict) -> float:
	total = flt(review.get("order_total") or 0)
	for threshold, factor in ORDER_SIZE_TIERS:
		if total >= threshold:
			return factor
	return 1.0


def _recency_decay(review: dict) -> float:
	"""Lineer decay: 0-6 ay 1.0, 6-12 ay arası 1.0 → 0.5, 12+ ay 0.5."""
	pub = review.get("published_at") or review.get("submitted_at")
	if not pub:
		return 1.0
	try:
		pub_dt = get_datetime(pub)
		now = get_datetime(now_datetime())
		days = max(0, (now - pub_dt).days)
	except Exception:
		return 1.0
	months = days / 30.0
	if months <= RECENCY_MONTHS_FULL:
		return 1.0
	if months >= RECENCY_MONTHS_MIN:
		return RECENCY_MIN_FACTOR
	# Lineer interp: RECENCY_MONTHS_FULL..RECENCY_MONTHS_MIN arası 1.0..0.5
	span = RECENCY_MONTHS_MIN - RECENCY_MONTHS_FULL
	progress = (months - RECENCY_MONTHS_FULL) / span
	return 1.0 - (progress * (1.0 - RECENCY_MIN_FACTOR))


def _reviewer_tier_multi(review: dict) -> float:
	user = review.get("reviewer_user")
	if not user:
		return 1.0
	from tradehub_core.api.reputation import get_tier_weight

	return get_tier_weight(user)


def _risk_penalty(review: dict) -> float:
	"""weighted_contribution direkt zaten 0.1/0.5/1.0 — return olduğu gibi."""
	wc = review.get("weighted_contribution")
	if wc is None:
		return 1.0
	try:
		return flt(wc)
	except Exception:
		return 1.0


def compute_review_weight(review: dict) -> float:
	w = 1.0
	w *= _verified_purchase_multi(review)
	w *= _kyb_multi(review)
	w *= _order_size_multi(review)
	w *= _recency_decay(review)
	w *= _reviewer_tier_multi(review)
	w *= _risk_penalty(review)
	return w


def compute_weighted_rating(listing_name: str) -> dict:
	"""Bir Listing için ağırlıklı rating hesabı + trust signals.

	Returns:
	  dict: {
	    weighted_rating: float,
	    weighted_review_count: int,
	    trust_signals: {...}
	  }
	"""
	if not listing_name:
		return {"weighted_rating": 0.0, "weighted_review_count": 0, "trust_signals": {}}

	rows = frappe.db.sql(
		"""
		SELECT
			lr.name,
			lr.rating,
			lr.reviewer_user,
			lr.is_verified_purchase,
			lr.is_kyb_verified,
			lr.weighted_contribution,
			lr.published_at,
			lr.submitted_at,
			o.total AS order_total
		FROM `tabListing Review` lr
		LEFT JOIN `tabOrder` o ON o.name = lr.`order`
		WHERE lr.listing = %s AND lr.status = 'Approved'
		""",
		(listing_name,),
		as_dict=True,
	)
	if not rows:
		return {
			"weighted_rating": 0.0,
			"weighted_review_count": 0,
			"trust_signals": {
				"verified_purchase_pct": 0,
				"kyb_verified_pct": 0,
				"trusted_reviewer_pct": 0,
				"avg_review_age_days": 0,
			},
		}

	total_w = 0.0
	weighted_sum = 0.0
	verified_count = 0
	kyb_count = 0
	trusted_count = 0
	age_days_sum = 0

	for r in rows:
		w = compute_review_weight(r)
		total_w += w
		weighted_sum += flt(r.rating) * w
		if r.is_verified_purchase:
			verified_count += 1
		if r.is_kyb_verified:
			kyb_count += 1
		# Trust signal: Trusted+ tier'a sahip reviewer
		if r.reviewer_user:
			tier = frappe.db.get_value("Reviewer Reputation", r.reviewer_user, "tier")
			if tier in ("Trusted", "Top Contributor", "Verified Pro"):
				trusted_count += 1
		# Age
		pub = r.published_at or r.submitted_at
		if pub:
			try:
				age_days_sum += max(0, (get_datetime(now_datetime()) - get_datetime(pub)).days)
			except Exception:
				pass

	cnt = len(rows)
	weighted_rating = round(weighted_sum / total_w, 2) if total_w else 0.0

	trust_signals = {
		"verified_purchase_pct": round(verified_count * 100.0 / cnt, 1),
		"kyb_verified_pct": round(kyb_count * 100.0 / cnt, 1),
		"trusted_reviewer_pct": round(trusted_count * 100.0 / cnt, 1),
		"avg_review_age_days": int(age_days_sum / cnt) if cnt else 0,
	}

	return {
		"weighted_rating": weighted_rating,
		"weighted_review_count": cnt,
		"trust_signals": trust_signals,
	}


def recompute_listing_weighted(listing_name: str):
	"""Listing.weighted_rating + weighted_review_count cache update."""
	if not listing_name:
		return
	out = compute_weighted_rating(listing_name)
	frappe.db.set_value(
		"Listing",
		listing_name,
		{
			"weighted_rating": out["weighted_rating"],
			"weighted_review_count": out["weighted_review_count"],
		},
		update_modified=False,
	)


@frappe.whitelist(allow_guest=True)
def get_listing_weighted_rating(listing: str):
	"""Public — Listing için weighted rating + trust signals."""
	if not listing:
		frappe.throw("listing zorunlu")
	out = compute_weighted_rating(listing)
	# Ek bilgi: simple avg da gönder (tooltip için)
	simple = frappe.db.get_value("Listing", listing, ["average_rating", "review_count"], as_dict=True)
	out["simple_average_rating"] = float(simple.average_rating or 0) if simple else 0
	out["simple_review_count"] = int(simple.review_count or 0) if simple else 0
	return out


# ── Scheduler ───────────────────────────────────────────────────────────────
def daily_recompute_listing_weights():
	"""Günlük cron — Approved review'i olan Listing'lerin weighted rating'ini yenile.

	Recency decay zaman ilerledikçe değiştiği için günde 1 sefer önemli.
	"""
	listings = frappe.db.sql_list(
		"SELECT DISTINCT listing FROM `tabListing Review` WHERE status='Approved' AND listing IS NOT NULL"
	)
	for ln in listings:
		try:
			recompute_listing_weighted(ln)
		except Exception:
			frappe.log_error(title="daily_weighted_failed", message=f"listing={ln}")


@frappe.whitelist()
def admin_recompute_all_ratings():
	"""Admin endpoint — tüm Listing'lerin weighted rating'ini yeniden hesaplar."""
	if not frappe.has_permission("Listing", "write"):
		frappe.throw("Yetkisiz", frappe.PermissionError)
	listings = frappe.db.sql_list(
		"SELECT DISTINCT listing FROM `tabListing Review` WHERE status='Approved' AND listing IS NOT NULL"
	)
	for ln in listings:
		recompute_listing_weighted(ln)
	frappe.db.commit()
	return {"success": True, "count": len(listings)}
