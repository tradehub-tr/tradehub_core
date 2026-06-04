# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

from frappe.model.document import Document
from frappe.utils import flt


class FieldCommission(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		# Sabit Ücret: komisyon doğrudan girilen tutardır (hook set eder), yeniden hesaplama.
		# Yüzde: commission_amount her zaman base × rate / 100 ile tutarlı kalsın.
		if self.commission_type != "Sabit Ücret":
			self.commission_amount = flt(self.base_amount) * flt(self.commission_rate) / 100.0
