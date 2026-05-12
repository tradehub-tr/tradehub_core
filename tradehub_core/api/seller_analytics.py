"""Faz 6 — Seller Review Analytics (premium dashboard).

Her satıcı için period-based metrics (7d/30d/90d/1y):
  - Toplam yorum, ortalama puan, weighted rating, helpful ratio
  - Response rate + ort. yanıt saat
  - KYB buyer %
  - Anlaşmazlık sayısı
  - Top topics (sentiment'tan)
  - Sentiment breakdown
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import add_to_date, now_datetime

PERIOD_DAYS = {"7d": 7, "30d": 30, "90d": 90, "1y": 365}


def _compute_seller_period(seller: str, period: str) -> dict:
	if seller is None or period not in PERIOD_DAYS:
		frappe.throw("Geçersiz parametreler")
	days = PERIOD_DAYS[period]
	cutoff = add_to_date(now_datetime(), days=-days)

	# Bu satıcının listing'leri
	listings = frappe.get_all("Listing", filters={"seller_profile": seller}, pluck="name")
	if not listings:
		return {
			"total_reviews": 0,
			"avg_rating": 0,
			"weighted_rating": 0,
			"helpful_ratio": 0,
			"response_rate": 0,
			"avg_response_hours": 0,
			"kyb_buyer_pct": 0,
			"dispute_count": 0,
			"top_topics": [],
			"sentiment_breakdown": {},
		}

	# Yorumlar
	reviews = frappe.db.sql(
		"""
		SELECT name, rating, helpful_count, not_helpful_count,
			seller_reply, seller_reply_within_hours, is_kyb_verified,
			related_dispute
		FROM `tabListing Review`
		WHERE listing IN %(listings)s AND status='Approved'
		  AND submitted_at >= %(cutoff)s
	""",
		{"listings": tuple(listings) if listings else ("__none__",), "cutoff": cutoff},
		as_dict=True,
	)

	total = len(reviews)
	if total == 0:
		return {
			"total_reviews": 0,
			"avg_rating": 0,
			"weighted_rating": 0,
			"helpful_ratio": 0,
			"response_rate": 0,
			"avg_response_hours": 0,
			"kyb_buyer_pct": 0,
			"dispute_count": 0,
			"top_topics": [],
			"sentiment_breakdown": {},
		}

	avg_rating = round(sum(r.rating for r in reviews) / total, 2)
	helpful_sum = sum(r.helpful_count for r in reviews)
	not_helpful_sum = sum(r.not_helpful_count for r in reviews)
	helpful_total = helpful_sum + not_helpful_sum
	helpful_ratio = round(helpful_sum * 100 / helpful_total, 2) if helpful_total else 0

	replied = [r for r in reviews if r.seller_reply]
	response_rate = round(len(replied) * 100 / total, 2)
	response_hours = [r.seller_reply_within_hours for r in replied if r.seller_reply_within_hours]
	avg_response = round(sum(response_hours) / len(response_hours), 2) if response_hours else 0

	kyb_count = sum(1 for r in reviews if r.is_kyb_verified)
	kyb_pct = round(kyb_count * 100 / total, 2)
	dispute_count = sum(1 for r in reviews if r.related_dispute)

	# Sentiment + topics
	sentiments = {"positive": 0, "neutral": 0, "negative": 0, "mixed": 0}
	topic_freq: dict[str, int] = {}
	review_names = [r.name for r in reviews]
	if review_names:
		sent_rows = frappe.get_all(
			"Review Sentiment Analysis",
			filters={"review": ["in", review_names]},
			fields=["overall_sentiment", "topics_json"],
		)
		for s in sent_rows:
			if s.overall_sentiment in sentiments:
				sentiments[s.overall_sentiment] += 1
			if s.topics_json:
				try:
					for t in json.loads(s.topics_json):
						topic_freq[t] = topic_freq.get(t, 0) + 1
				except Exception:
					pass
	top_topics = sorted(topic_freq.items(), key=lambda x: -x[1])[:10]

	# Weighted rating (Listing.weighted_rating ortalaması — bu satıcının
	# listing'lerinin ağırlıklı puanı)
	w_row = frappe.db.sql(
		"""
		SELECT AVG(weighted_rating) FROM `tabListing`
		WHERE seller_profile=%s AND weighted_rating > 0
	""",
		(seller,),
	)
	weighted_rating = round(float(w_row[0][0] or 0), 2) if w_row else 0

	return {
		"total_reviews": total,
		"avg_rating": avg_rating,
		"weighted_rating": weighted_rating,
		"helpful_ratio": helpful_ratio,
		"response_rate": response_rate,
		"avg_response_hours": avg_response,
		"kyb_buyer_pct": kyb_pct,
		"dispute_count": dispute_count,
		"top_topics": [{"topic": t, "count": c} for t, c in top_topics],
		"sentiment_breakdown": sentiments,
	}


@frappe.whitelist()
def get_seller_review_analytics(seller: str = None, period: str = "30d") -> dict:
	"""Admin / Seller — analytics çek (cache + compute)."""
	from tradehub_core.api.review import _is_admin

	# Seller kendi profili ise OK; admin her satıcıyı görür
	user = frappe.session.user
	if not _is_admin():
		# Kullanıcının kendi seller profile'ı
		own = frappe.db.get_value("Admin Seller Profile", {"user": user}, "name")
		if not own:
			frappe.throw("Yetkisiz", frappe.PermissionError)
		seller = own
	elif not seller:
		frappe.throw("Seller zorunlu")

	stats = _compute_seller_period(seller, period)

	# Cache (Seller Review Analytics) upsert
	try:
		existing = frappe.db.get_value(
			"Seller Review Analytics", {"seller": seller, "period": period}, "name"
		)
		if existing:
			doc = frappe.get_doc("Seller Review Analytics", existing)
		else:
			doc = frappe.new_doc("Seller Review Analytics")
			doc.seller = seller
			doc.period = period
		for k, v in stats.items():
			if k in ("top_topics", "sentiment_breakdown"):
				continue
			if hasattr(doc, k):
				setattr(doc, k, v)
		doc.top_topics_json = json.dumps(stats["top_topics"], ensure_ascii=False)
		doc.sentiment_breakdown_json = json.dumps(stats["sentiment_breakdown"])
		doc.computed_at = now_datetime()
		if existing:
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)
		frappe.db.commit()
	except Exception:
		frappe.log_error(title="seller_analytics_cache_failed")

	return {"seller": seller, "period": period, **stats}


def compute_all_sellers():
	"""Daily scheduler — tüm satıcılar için 30d period."""
	sellers = frappe.get_all("Admin Seller Profile", pluck="name", limit=500)
	for s in sellers:
		try:
			_compute_seller_period(s, "30d")
		except Exception:
			frappe.log_error(title="seller_analytics_compute_failed", message=f"seller={s}")
