"""Faz 6 — Review Sentiment Analysis + Topic Extraction.

OpenAI GPT-4o-mini ile çalışır. Translation Settings.openai_api_key set ise
gerçek API; yoksa basit keyword-tabanlı stub fallback.
"""

from __future__ import annotations

import json

import frappe
from frappe.utils import now_datetime

ALGO_VERSION = "v1.0"

POSITIVE_KW = (
	"güzel",
	"kaliteli",
	"harika",
	"mükemmel",
	"tavsiye",
	"hızlı",
	"memnun",
	"iyi",
	"süper",
	"beğendim",
	"good",
	"great",
	"excellent",
)
NEGATIVE_KW = (
	"kötü",
	"berbat",
	"rezalet",
	"iade",
	"sahte",
	"kandırıldım",
	"vasat",
	"kalitesiz",
	"hasarlı",
	"bozuk",
	"geç",
	"bad",
	"terrible",
)


def _stub_analyze(text: str, rating: int) -> dict:
	"""Keyword bazlı basit sentiment + topic."""
	lower = (text or "").lower()
	pos = sum(1 for kw in POSITIVE_KW if kw in lower)
	neg = sum(1 for kw in NEGATIVE_KW if kw in lower)
	if pos > neg:
		sentiment = "positive"
		conf = min(0.8, 0.4 + pos * 0.1)
	elif neg > pos:
		sentiment = "negative"
		conf = min(0.8, 0.4 + neg * 0.1)
	elif pos > 0 and neg > 0:
		sentiment = "mixed"
		conf = 0.5
	else:
		sentiment = "neutral"
		conf = 0.3
	# Basit topic extraction
	topics = []
	topic_map = {
		"kargo": ["kargo", "teslim", "ulaştı", "geldi"],
		"kalite": ["kalite", "kaliteli", "kalitesiz"],
		"fiyat": ["fiyat", "ucuz", "pahalı"],
		"ambalaj": ["ambalaj", "paket"],
		"iletişim": ["iletişim", "yanıt", "destek"],
	}
	for topic, kws in topic_map.items():
		if any(kw in lower for kw in kws):
			topics.append(topic)
	return {
		"overall_sentiment": sentiment,
		"confidence": conf,
		"topics": topics,
		"aspect_sentiments": {},
		"model": "stub",
	}


def _openai_analyze(text: str, rating: int, api_key: str, model: str) -> dict:
	"""GPT-4o-mini ile structured sentiment analizi."""
	import urllib.error
	import urllib.request

	prompt = (
		"You are a B2B review analyzer. Given the review text and rating, "
		'return JSON: {"overall_sentiment":"positive|neutral|negative|mixed",'
		'"confidence":0-1,"topics":["kargo","kalite",...],'
		'"aspect_sentiments":{"kargo":"positive","kalite":"negative"}}. '
		f"Rating: {rating}/5\n\nText: {text}"
	)
	payload = {
		"model": model,
		"messages": [{"role": "user", "content": prompt}],
		"temperature": 0.2,
		"response_format": {"type": "json_object"},
	}
	req = urllib.request.Request(
		"https://api.openai.com/v1/chat/completions",
		data=json.dumps(payload).encode("utf-8"),
		headers={
			"Content-Type": "application/json",
			"Authorization": f"Bearer {api_key}",
		},
	)
	with urllib.request.urlopen(req, timeout=30) as resp:
		data = json.loads(resp.read().decode("utf-8"))
	content = data["choices"][0]["message"]["content"]
	parsed = json.loads(content)
	parsed["model"] = model
	return parsed


def _get_openai_config() -> tuple[str | None, str]:
	try:
		if frappe.db.table_exists("tabSingles"):
			settings = frappe.get_single("Translation Settings")
			api_key = settings.get_password("openai_api_key", raise_exception=False)
			model = settings.openai_model or "gpt-4o-mini"
			return api_key, model
	except Exception:
		frappe.log_error("OpenAI config fetch failed in _get_openai_config", "sentiment")
		pass
	return None, "gpt-4o-mini"


def analyze_review_sentiment(review_name: str) -> dict:
	"""Bir Listing Review için sentiment hesapla ve kaydet."""
	if not review_name or not frappe.db.exists("Listing Review", review_name):
		frappe.throw("Yorum bulunamadı", frappe.DoesNotExistError)

	rev = frappe.db.get_value(
		"Listing Review",
		review_name,
		["body", "rating", "detected_language"],
		as_dict=True,
	)
	text = rev.body or ""
	rating = int(rev.rating or 0)

	api_key, model = _get_openai_config()
	if api_key:
		try:
			result = _openai_analyze(text, rating, api_key, model)
		except Exception as e:
			frappe.log_error(title="sentiment_openai_failed", message=str(e))
			result = _stub_analyze(text, rating)
	else:
		result = _stub_analyze(text, rating)

	# Anomaly: 5★ but sentiment=negative, or 1★ but sentiment=positive
	anomaly = (rating >= 4 and result["overall_sentiment"] == "negative") or (
		rating <= 2 and result["overall_sentiment"] == "positive"
	)

	# Upsert
	existing = frappe.db.get_value(
		"Review Sentiment Analysis",
		{"review": review_name},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Review Sentiment Analysis", existing)
	else:
		doc = frappe.new_doc("Review Sentiment Analysis")
		doc.review = review_name
	doc.overall_sentiment = result["overall_sentiment"]
	doc.confidence = float(result.get("confidence", 0))
	doc.language = rev.detected_language or "tr"
	doc.model_version = result.get("model", "stub")
	doc.topics_json = json.dumps(result.get("topics", []), ensure_ascii=False)
	doc.aspect_sentiments_json = json.dumps(
		result.get("aspect_sentiments", {}),
		ensure_ascii=False,
	)
	doc.anomaly_flag = 1 if anomaly else 0
	doc.analyzed_at = now_datetime()
	if existing:
		doc.save(ignore_permissions=True)
	else:
		doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return {
		"success": True,
		"sentiment": doc.overall_sentiment,
		"confidence": doc.confidence,
		"anomaly": bool(anomaly),
		"topics": result.get("topics", []),
	}


def queue_analysis(doc, method=None):
	"""hooks.py — after_insert handler. Sync analiz (Frappe enqueue alternatif)."""
	if not doc or not doc.name:
		return
	try:
		analyze_review_sentiment(doc.name)
	except Exception:
		frappe.log_error(title="sentiment_queue_failed", message=f"review={doc.name}")


def batch_analyze_pending():
	"""Hourly scheduler — analiz edilmemiş Approved review'ları işle."""
	rows = frappe.db.sql(
		"""
		SELECT lr.name FROM `tabListing Review` lr
		LEFT JOIN `tabReview Sentiment Analysis` rsa ON rsa.review = lr.name
		WHERE lr.status='Approved' AND rsa.name IS NULL
		LIMIT 50
	""",
		as_dict=True,
	)
	for r in rows:
		try:
			analyze_review_sentiment(r.name)
		except Exception:
			frappe.log_error(title="batch_sentiment_failed", message=f"review={r.name}")


@frappe.whitelist(allow_guest=True)
def get_listing_sentiment_summary(listing: str) -> dict:
	"""Storefront: bir Listing için sentiment özet."""
	if not listing:
		frappe.throw("Listing zorunlu")
	rows = frappe.db.sql(
		"""
		SELECT rsa.overall_sentiment, rsa.topics_json
		FROM `tabReview Sentiment Analysis` rsa
		JOIN `tabListing Review` lr ON lr.name = rsa.review
		WHERE lr.listing = %s AND lr.status='Approved'
	""",
		(listing,),
		as_dict=True,
	)

	counts = {"positive": 0, "neutral": 0, "negative": 0, "mixed": 0}
	topic_freq: dict[str, int] = {}
	for r in rows:
		s = r.overall_sentiment
		if s in counts:
			counts[s] += 1
		if r.topics_json:
			try:
				for t in json.loads(r.topics_json):
					topic_freq[t] = topic_freq.get(t, 0) + 1
			except Exception:
				frappe.log_error("Sentiment topics_json parse failed", "sentiment")
				pass
	top_topics = sorted(topic_freq.items(), key=lambda x: -x[1])[:10]
	total = sum(counts.values())
	return {
		"total_analyzed": total,
		"sentiment_breakdown": counts,
		"positive_pct": round(counts["positive"] * 100 / total, 1) if total else 0,
		"negative_pct": round(counts["negative"] * 100 / total, 1) if total else 0,
		"top_topics": [{"topic": t, "count": c} for t, c in top_topics],
	}


@frappe.whitelist()
def admin_analyze_review(review: str):
	"""Admin manuel tetikleyici."""
	from tradehub_core.api.review import _is_admin

	if not _is_admin():
		frappe.throw("Yetkisiz", frappe.PermissionError)
	return analyze_review_sentiment(review)
