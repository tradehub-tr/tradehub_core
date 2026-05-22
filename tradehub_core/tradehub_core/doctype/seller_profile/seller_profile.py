"""DEPRECATED: Seller Profile DocType artık User Profile birleşmesine
(Sprint 2 — user_profile_v1 patch'leri) tabidir.

Controller hook'ları boşaltıldı (Sprint 2 PR — Bloker 2 Hibrit C+B stratejisi).
_sync_to_related_docs, _sync_status, has_value_changed kullanan tüm
senkronizasyon kodları silindi. Mekanik garanti: hook fonksiyonu yok.

DocType Sprint 4'te (90 gün sonra) drop edilir. O zamana kadar hidden=1, read_only=1.
"""

from frappe.model.document import Document


class SellerProfile(Document):
	pass
