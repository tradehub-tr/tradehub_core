"""Sprint 1 Adres Mimarisi follow-up — Patch 02 (2026-05-18).

Patch 01 sonrası ortaya çıkan tutarsızlık fix'i:
  - Addresses field migration'ı sırasında purpose field default="Delivery" ile yaratıldı
  - Bu yüzden Patch 01'in `WHERE purpose IS NULL OR purpose=''` koşulu match etmedi
  - Sonuç: kind=Seller adresleri purpose=Delivery kaldı (Pickup olmalıydı)

Bu patch kind=Seller AND purpose=Delivery durumunu düzeltir. Idempotent — eğer
kullanıcı bir Delivery adresini manuel Seller'a çevirdiyse o zaten korumalı
(ileride manuel Seller=Delivery oluşmaz çünkü UI artık kind kullanmıyor).
"""

import frappe


def execute():
	# kind=Seller ama purpose=Delivery olan satırları Pickup'a güncelle
	frappe.db.sql(
		"""
		UPDATE `tabAddresses`
		SET purpose = 'Pickup'
		WHERE kind = 'Seller' AND purpose = 'Delivery'
		"""
	)
	frappe.db.commit()
