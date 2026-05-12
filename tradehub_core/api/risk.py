"""Faz 3 — Review Risk Score Calculator.

Yeni bir yorum oluştuğunda otomatik 0-100 arası risk skoru hesaplar ve
`Review Risk Score` doctype'ına yazar. Yüksek riskli yorumlar agregadan
çıkarılır (`weighted_contribution = 0.1`) ve `Pending` durumda kalır.

Çağrıldığı yerler:
  - hooks.py → doc_events["Listing Review"]["after_insert"]
  - admin re-compute endpoint (manuel tetikleyici)
"""

from __future__ import annotations

import json
from difflib import SequenceMatcher

import frappe
from frappe.utils import get_datetime, now_datetime, time_diff_in_hours

ALGO_VERSION = "v1.0"

# Eşikler
RISK_THRESHOLD_MEDIUM = 31
RISK_THRESHOLD_HIGH = 61

# Faktör ağırlıkları
FACTOR_WEIGHTS = {
	"ip_burst": 30,
	"buyer_burst": 25,
	"seller_burst": 20,
	"body_length_anomaly": 15,
	"boilerplate": 25,
	"velocity": 10,
	"rating_text_mismatch": 20,
	"unverified_purchase": 10,
	"first_time_reviewer": 5,
}

# Bot/spam keyword'leri (basit sentiment proxy — 5★ ile birlikte fail eden)
NEGATIVE_KEYWORDS = (
	"kötü",
	"berbat",
	"rezalet",
	"iade",
	"sahte",
	"kandırıldım",
	"vasat",
	"kalitesiz",
	"geç",
	"hasarlı",
	"bozuk",
)

BOILERPLATE_SIMILARITY_THRESHOLD = 0.85


def _add_factor(factors, key, weight, label, evidence=""):
	factors.append(
		{
			"factor_key": key,
			"factor_label": label,
			"weight": weight,
			"evidence": evidence or "",
		}
	)


def _check_buyer_burst(review_doc, factors):
	"""Aynı buyer son 24 saatte 5+ review mı yaptı?"""
	if not review_doc.reviewer_user:
		return
	cnt = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabListing Review`
		WHERE reviewer_user = %s
		  AND name != %s
		  AND submitted_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
		""",
		(review_doc.reviewer_user, review_doc.name),
	)[0][0]
	if cnt >= 5:
		_add_factor(
			factors,
			"buyer_burst",
			FACTOR_WEIGHTS["buyer_burst"],
			"Buyer Burst",
			f"Bu kullanıcı son 24 saatte {cnt} review yaptı",
		)


def _check_seller_burst(review_doc, factors):
	"""Aynı satıcıya son 24 saatte 10+ aynı puanlı review."""
	if not review_doc.seller or not review_doc.rating:
		return
	cnt = frappe.db.sql(
		"""
		SELECT COUNT(*) FROM `tabListing Review`
		WHERE seller = %s AND rating = %s
		  AND name != %s
		  AND submitted_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
		""",
		(review_doc.seller, review_doc.rating, review_doc.name),
	)[0][0]
	if cnt >= 10 and review_doc.rating >= 4:
		_add_factor(
			factors,
			"seller_burst",
			FACTOR_WEIGHTS["seller_burst"],
			"Seller Burst (suspicious)",
			f"Bu satıcı son 24 saatte {cnt} adet {review_doc.rating}★ review aldı",
		)


def _check_body_length_anomaly(review_doc, factors):
	"""Çok kısa body + 5★ kombinasyonu (övgü botu pattern'i)."""
	body = (review_doc.body or "").strip()
	if review_doc.rating == 5 and len(body) < 30:
		_add_factor(
			factors,
			"body_length_anomaly",
			FACTOR_WEIGHTS["body_length_anomaly"],
			"Body Length Anomaly",
			f"5★ ama yorum {len(body)} karakter (çok kısa)",
		)


def _check_rating_text_mismatch(review_doc, factors):
	"""5★ olduğu halde body'de negatif kelime."""
	if review_doc.rating < 4:
		return
	body_lower = (review_doc.body or "").lower()
	hits = [kw for kw in NEGATIVE_KEYWORDS if kw in body_lower]
	if hits:
		_add_factor(
			factors,
			"rating_text_mismatch",
			FACTOR_WEIGHTS["rating_text_mismatch"],
			"Rating-Text Mismatch",
			f"Yüksek puan ama negatif kelimeler: {', '.join(hits[:3])}",
		)


def _check_boilerplate(review_doc, factors):
	"""Buyer'ın önceki yorumlarıyla yüksek benzerlik (boilerplate spam)."""
	if not review_doc.reviewer_user or not review_doc.body:
		return
	other_bodies = frappe.db.sql_list(
		"""
		SELECT body FROM `tabListing Review`
		WHERE reviewer_user = %s AND name != %s
		LIMIT 20
		""",
		(review_doc.reviewer_user, review_doc.name),
	)
	if not other_bodies:
		return
	my_body = (review_doc.body or "").lower().strip()
	max_sim = 0.0
	for ob in other_bodies:
		if not ob:
			continue
		sim = SequenceMatcher(None, my_body, ob.lower().strip()).ratio()
		if sim > max_sim:
			max_sim = sim
	if max_sim >= BOILERPLATE_SIMILARITY_THRESHOLD:
		_add_factor(
			factors,
			"boilerplate",
			FACTOR_WEIGHTS["boilerplate"],
			"Boilerplate Spam",
			f"Önceki yorumla benzerlik: {max_sim:.2f}",
		)


def _check_velocity(review_doc, factors):
	"""Order delivered → review aynı saniye (bot şüphesi).

	Order'da `modified` timestamp'i Tamamlandı'ya geçiş anını temsil eder
	(yaklaşık). 60 sn'den az fark riskli.
	"""
	if not review_doc.order:
		return
	order_modified = frappe.db.get_value("Order", review_doc.order, "modified")
	if not order_modified or not review_doc.submitted_at:
		return
	try:
		diff_hours = time_diff_in_hours(get_datetime(review_doc.submitted_at), get_datetime(order_modified))
	except Exception:
		return
	if 0 <= diff_hours < (1 / 60):  # 1 dakikadan az
		_add_factor(
			factors,
			"velocity",
			FACTOR_WEIGHTS["velocity"],
			"Suspicious Velocity",
			f"Order güncellemesi ile review arası {int(diff_hours * 3600)}s",
		)


def _check_unverified(review_doc, factors):
	"""Order_item silinmiş veya yoksa (data race)."""
	if not review_doc.order_item:
		_add_factor(
			factors,
			"unverified_purchase",
			FACTOR_WEIGHTS["unverified_purchase"],
			"Unverified Purchase",
			"Order item bağlantısı yok",
		)


def _check_first_time(review_doc, factors):
	if not review_doc.reviewer_user:
		return
	cnt = frappe.db.count(
		"Listing Review",
		filters={
			"reviewer_user": review_doc.reviewer_user,
			"name": ["!=", review_doc.name],
		},
	)
	if cnt == 0:
		_add_factor(
			factors,
			"first_time_reviewer",
			FACTOR_WEIGHTS["first_time_reviewer"],
			"First-time Reviewer",
			"Kullanıcının ilk yorumu",
		)


# Sinyal sırası — büyükten küçüğe (sklerli ağırlık)
SIGNALS = (
	_check_buyer_burst,
	_check_seller_burst,
	_check_body_length_anomaly,
	_check_rating_text_mismatch,
	_check_boilerplate,
	_check_velocity,
	_check_unverified,
	_check_first_time,
)


def compute_risk_score(review_doc) -> dict:
	"""Bir Listing Review için risk faktörlerini hesaplar.

	Returns:
	  {"total": int 0-100, "factors": list of dict}
	"""
	factors = []
	for signal in SIGNALS:
		try:
			signal(review_doc, factors)
		except Exception as e:
			frappe.log_error(
				title="risk_signal_failed",
				message=f"{signal.__name__}: {type(e).__name__}: {e}",
			)
	total = min(100, sum(f["weight"] for f in factors))
	return {"total": total, "factors": factors}


def compute_and_apply_risk_score(doc, method=None):
	"""hooks.py'den çağrılan after_insert handler.

	Listing Review oluşturulduktan sonra otomatik tetiklenir:
	  1. Risk skoru hesaplar
	  2. Review Risk Score doctype kaydı yaratır
	  3. Listing Review'da risk_score + weighted_contribution + risk_factors_json
	     cache field'larını günceller
	  4. Risk eşiği high (61+) ise weighted_contribution = 0.1 olur
	     Risk eşiği medium (31-60) ise weighted_contribution = 0.5 olur
	     Diğer durumda 1.0
	"""
	if not doc or not doc.name:
		return

	result = compute_risk_score(doc)
	total = int(result["total"])
	factors = result["factors"]

	# weighted_contribution hesabı
	if total >= RISK_THRESHOLD_HIGH:
		wc = 0.1
	elif total >= RISK_THRESHOLD_MEDIUM:
		wc = 0.5
	else:
		wc = 1.0

	# Review Risk Score kaydı (upsert)
	existing = frappe.db.get_value("Review Risk Score", {"review": doc.name}, "name")
	if existing:
		rs = frappe.get_doc("Review Risk Score", existing)
		rs.factors = []
	else:
		rs = frappe.new_doc("Review Risk Score")
		rs.review = doc.name
	rs.total_score = total
	rs.is_high_risk = 1 if total >= RISK_THRESHOLD_HIGH else 0
	rs.computed_at = now_datetime()
	rs.version = ALGO_VERSION
	for f in factors:
		rs.append("factors", f)
	if existing:
		rs.save(ignore_permissions=True)
	else:
		rs.insert(ignore_permissions=True)

	# Listing Review cache update (direct SQL — controller validate tetiklenmesin)
	frappe.db.set_value(
		"Listing Review",
		doc.name,
		{
			"risk_score": total,
			"weighted_contribution": wc,
			"risk_factors_json": json.dumps(factors, ensure_ascii=False),
		},
		update_modified=False,
	)
	frappe.db.commit()


@frappe.whitelist()
def admin_recompute_risk(review: str):
	"""Admin manuel re-compute."""
	if not frappe.has_permission("Listing Review", "write"):
		frappe.throw("Yetkisiz", frappe.PermissionError)
	doc = frappe.get_doc("Listing Review", review)
	compute_and_apply_risk_score(doc)
	# Listing rating'i tekrar çek
	from tradehub_core.api.review import recompute_listing_rating

	recompute_listing_rating(doc.listing)
	return {
		"success": True,
		"risk_score": frappe.db.get_value("Listing Review", review, "risk_score"),
	}
