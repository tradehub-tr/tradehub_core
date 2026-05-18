"""Marketplace Settings (Single DocType) — Sprint 1 Adres Mimarisi (2026-05-15).

Adres ve fatura ile ilgili pazaryeri çapında varsayılanlar.
4 karar (kullanıcı 2026-05-15):
  - default_address_type=Individual
  - address_type_toggle_visible=1 (UI'da Bireysel/Kurumsal toggle görünür)
  - require_tax_id_business=1
  - require_tax_id_individual=0
"""

import frappe
from frappe.model.document import Document


class MarketplaceSettings(Document):
	def validate(self):
		super().validate()
		# Tüm field'lar Select/Check, ek validasyon yok.
		return None


def get_settings() -> dict:
	"""Frontend ve API tüketicileri için yardımcı: tek seferde tüm ayarları döndür."""
	doc = frappe.get_cached_doc("Marketplace Settings")
	return {
		"default_address_type": doc.default_address_type or "Individual",
		"address_type_toggle_visible": bool(doc.address_type_toggle_visible),
		"require_tax_id_business": bool(doc.require_tax_id_business),
		"require_tax_id_individual": bool(doc.require_tax_id_individual),
		"invoice_generation_mode": doc.invoice_generation_mode or "Manual",
	}
