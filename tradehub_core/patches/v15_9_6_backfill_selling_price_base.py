import frappe


def execute():
	"""Y3 — Mevcut listing'ler için selling_price_base (TRY) alanını doldur.

	Alan DocType JSON ile gelir (migrate model-sync kolonu ekler); bu patch
	post_model_sync'te çalışıp değerleri güncel kurla hesaplar. Sonraki tazeleme
	günlük TCMB job'u (refresh_listing_price_base) + her Listing.validate ile olur.
	"""
	from tradehub_core.services.tcmb import refresh_listing_price_base

	refresh_listing_price_base()
	frappe.db.commit()
