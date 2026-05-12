"""Faz 1 — Listing.average_rating artık Listing Review'dan beslenir.

Bu patch idempotent:
  1) Listing tablosundaki rating cache field'larını sıfırlar (eski Seller Review
     proxy değerleri temizlenir).
  2) Mevcut Listing Review (status='Approved') kayıtları varsa her bir Listing
     için recompute_listing_rating çalıştırılır — taze kurulumda yorum yoktur,
     bu kısım no-op olur.
"""

import frappe


def execute():
	# Listing Review doctype yoksa (örn. eski branch'tan migrate ediyoruz) çık
	if not frappe.db.table_exists("tabListing Review"):
		# Önce sadece sıfırla
		_reset_listing_rating_cache()
		return

	_reset_listing_rating_cache()
	_recompute_from_existing_reviews()
	frappe.db.commit()


def _reset_listing_rating_cache():
	# rating_distribution ve last_review_at yeni alanlar — DB'de varsa NULL'a çek;
	# average_rating ve review_count'u 0'la.
	cols = frappe.db.get_table_columns("Listing")
	updates = ["average_rating = 0", "review_count = 0"]
	if "rating_distribution" in cols:
		updates.append("rating_distribution = NULL")
	if "last_review_at" in cols:
		updates.append("last_review_at = NULL")
	frappe.db.sql("UPDATE `tabListing` SET " + ", ".join(updates))


def _recompute_from_existing_reviews():
	from tradehub_core.api.review import recompute_listing_rating

	listings = frappe.db.sql_list(
		"SELECT DISTINCT listing FROM `tabListing Review` WHERE status = 'Approved' AND listing IS NOT NULL"
	)
	for listing_name in listings:
		try:
			recompute_listing_rating(listing_name)
		except Exception:
			frappe.log_error(
				title="recompute_listing_ratings_from_listing_review",
				message=f"Listing {listing_name} agregasyon hatası",
			)
