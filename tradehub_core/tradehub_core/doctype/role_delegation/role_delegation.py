# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class RoleDelegation(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._validate_dates()
		self._validate_not_self_delegation()

	def _validate_dates(self) -> None:
		if self.starts_at and self.ends_at and self.starts_at >= self.ends_at:
			frappe.throw(
				_("Bitiş tarihi başlangıçtan sonra olmalı"),
				exc=frappe.ValidationError,
			)

	def _validate_not_self_delegation(self) -> None:
		if self.delegator and self.delegate and self.delegator == self.delegate:
			frappe.throw(
				_("Bir kullanıcı kendine delegation yapamaz"),
				exc=frappe.ValidationError,
			)
