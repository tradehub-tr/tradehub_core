# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class PIIFieldPolicy(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._validate_unique_jurisdictions()
		self._validate_permlevel()

	def _validate_unique_jurisdictions(self) -> None:
		seen: set[str] = set()
		for rule in self.jurisdiction_rules or []:
			if rule.jurisdiction in seen:
				frappe.throw(
					_("Aynı jurisdiction iki kez tanımlanamaz: {0}").format(rule.jurisdiction),
					exc=frappe.ValidationError,
				)
			seen.add(rule.jurisdiction)

	def _validate_permlevel(self) -> None:
		if self.permlevel is not None and int(self.permlevel) < 0:
			frappe.throw(_("Permlevel negatif olamaz"), exc=frappe.ValidationError)

	def on_update(self) -> None:
		from tradehub_core.utils import pii_compliance

		pii_compliance.invalidate_policy_cache(self.ref_doctype, self.fieldname)

	def on_trash(self) -> None:
		from tradehub_core.utils import pii_compliance

		pii_compliance.invalidate_policy_cache(self.ref_doctype, self.fieldname)
