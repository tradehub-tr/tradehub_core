"""Trial Settings (Single DocType) — global ücretsiz deneme konfigürasyonu (2026-06-09).

Süper admin tek yerden trial'ı yönetir: hangi paket denenebilir, kaç gün, buton metni,
aktif mi. Storefront pricing kartı (buton-üstü CTA + üst bant) bu ayara göre çalışır.
Trial başlatma akışı: register?plan=X&trial=1 → upgrade_subscription_plan(start_trial=True).
"""

import frappe
from frappe.model.document import Document

from tradehub_core.api.v1.public_pricing import invalidate_pricing_cache


class TrialSettings(Document):
	def validate(self):
		# Negatif gün engelle
		if int(self.trial_days or 0) < 0:
			self.trial_days = 0

	def on_update(self):
		# Storefront pricing cache'i tazele (trial_config değişti)
		invalidate_pricing_cache()


def get_trial_settings() -> dict:
	"""Frontend/API tüketicileri için tek seferde trial ayarları."""
	doc = frappe.get_cached_doc("Trial Settings")
	return {
		"trial_enabled": bool(doc.trial_enabled),
		"trial_plan": doc.trial_plan or "",
		"trial_days": int(doc.trial_days or 0),
		"trial_cta_label": doc.trial_cta_label or "",
	}
