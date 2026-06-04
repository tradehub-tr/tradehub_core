# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt


class FieldCommissionSettings(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		if flt(self.global_per_sale_amount) < 0:
			from frappe import _, throw

			throw(_("Global satış başı tutar negatif olamaz."))
