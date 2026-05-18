"""Sprint 1 Adres Mimarisi (2026-05-15) — kind → purpose migration.

Mevcut Addresses kayıtlarında:
  - kind="Buyer"  → purpose="Delivery"
  - kind="Seller" → purpose="Pickup"
Tüm mevcut adresler default address_type="Business" set edilir (B2B pazaryeri,
mevcut veriler çoğunlukla kurumsal). Migration sonrası kullanıcı bireysel adres
ekleyebilir (default Individual).

Idempotent: purpose/address_type zaten doluysa dokunmaz.
"""

import frappe


def execute():
	# 1) kind → purpose map (sadece boş purpose'lar için)
	frappe.db.sql(
		"""
		UPDATE `tabAddresses`
		SET purpose = CASE
			WHEN kind = 'Seller' THEN 'Pickup'
			ELSE 'Delivery'
		END
		WHERE (purpose IS NULL OR purpose = '')
		"""
	)

	# 2) Mevcut adresleri Business olarak işaretle (geriye uyumluluk).
	# Yeni eklenen adresler default Individual olur (Marketplace Settings).
	frappe.db.sql(
		"""
		UPDATE `tabAddresses`
		SET address_type = 'Business'
		WHERE (address_type IS NULL OR address_type = '')
		"""
	)

	frappe.db.commit()
