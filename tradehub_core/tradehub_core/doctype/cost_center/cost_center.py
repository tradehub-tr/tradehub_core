# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class CostCenter(NestedSet):
	nsm_parent_field = "parent_cost_center"

	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._validate_tenant_match_with_parent()
		self._validate_currency_match_with_parent()

	def _validate_tenant_match_with_parent(self) -> None:
		if not self.parent_cost_center:
			return
		parent_tenant = frappe.db.get_value("Cost Center", self.parent_cost_center, "tenant")
		if parent_tenant and parent_tenant != self.tenant:
			frappe.throw(
				_("Parent cost center farklı bir tenant'a ait: {0}").format(parent_tenant),
				exc=frappe.ValidationError,
			)

	def _validate_currency_match_with_parent(self) -> None:
		if not self.parent_cost_center or not self.currency:
			return
		parent_currency = frappe.db.get_value("Cost Center", self.parent_cost_center, "currency")
		if parent_currency and parent_currency != self.currency:
			frappe.msgprint(
				_("Uyarı: parent cost center {0} para biriminde, bu cost center {1}").format(
					parent_currency, self.currency
				),
				indicator="orange",
			)
