"""Faz 3 — yeni alanları idempotent initialize eder.

- Listing.weighted_rating / weighted_review_count → simple avg ile başlat
- Listing Review.risk_score → 0, weighted_contribution → 1.0
- Mevcut reviewer user'ları için Reviewer Reputation baseline
- Eski Approved review'lar için risk + weighted yeniden hesap
"""

import frappe


def execute():
	_init_listing_fields()
	_init_review_fields()
	_recompute_existing()
	_seed_reputations()
	frappe.db.commit()


def _init_listing_fields():
	cols = frappe.db.get_table_columns("Listing")
	updates = []
	if "weighted_rating" in cols:
		updates.append("weighted_rating = COALESCE(weighted_rating, average_rating)")
	if "weighted_review_count" in cols:
		updates.append("weighted_review_count = COALESCE(weighted_review_count, review_count)")
	if updates:
		frappe.db.sql("UPDATE `tabListing` SET " + ", ".join(updates))


def _init_review_fields():
	cols = frappe.db.get_table_columns("Listing Review")
	updates = []
	if "risk_score" in cols:
		updates.append("risk_score = COALESCE(risk_score, 0)")
	if "weighted_contribution" in cols:
		updates.append("weighted_contribution = COALESCE(weighted_contribution, 1.0)")
	if updates:
		frappe.db.sql("UPDATE `tabListing Review` SET " + ", ".join(updates))


def _recompute_existing():
	"""Mevcut Approved review'lar için risk skorunu hesapla + listing weighted rating."""
	if not frappe.db.table_exists("tabListing Review"):
		return
	if not frappe.db.table_exists("tabReview Risk Score"):
		return

	review_names = frappe.db.sql_list("SELECT name FROM `tabListing Review`")
	from tradehub_core.api.risk import compute_and_apply_risk_score

	for n in review_names:
		try:
			doc = frappe.get_doc("Listing Review", n)
			compute_and_apply_risk_score(doc)
		except Exception:
			frappe.log_error(
				title="phase3_risk_recompute_failed",
				message=f"review={n}",
			)

	# Tüm distinct listing'ler için weighted rating recompute
	from tradehub_core.api.rating_engine import recompute_listing_weighted

	listings = frappe.db.sql_list(
		"SELECT DISTINCT listing FROM `tabListing Review` WHERE status='Approved' AND listing IS NOT NULL"
	)
	for ln in listings:
		try:
			recompute_listing_weighted(ln)
		except Exception:
			frappe.log_error(
				title="phase3_weighted_recompute_failed",
				message=f"listing={ln}",
			)


def _seed_reputations():
	"""Mevcut tüm reviewer user'ları için Reviewer Reputation baseline."""
	if not frappe.db.table_exists("tabReviewer Reputation"):
		return
	from tradehub_core.api.reputation import recompute_user

	users = frappe.db.sql_list(
		"SELECT DISTINCT reviewer_user FROM `tabListing Review` WHERE reviewer_user IS NOT NULL"
	)
	for u in users:
		try:
			recompute_user(u)
		except Exception:
			frappe.log_error(
				title="phase3_reputation_seed_failed",
				message=f"user={u}",
			)
