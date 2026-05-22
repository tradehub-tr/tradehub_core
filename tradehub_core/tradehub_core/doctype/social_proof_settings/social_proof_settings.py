# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SocialProofSettings(Document):
	"""Singleton settings for social-proof rotating badges on product detail pages.

	The frontend reads these thresholds via tradehub_core.api.social_proof.get_signals;
	each metric is only emitted if value >= corresponding threshold. Cache is
	invalidated on update so the next get_signals call observes fresh values.
	"""

	def on_update(self):
		# Cache invalidated so next get_signals reads fresh values
		frappe.cache().delete_value("social_proof_settings")
