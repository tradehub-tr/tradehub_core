# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ApprovedSupplierList(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._enforce_single_default_per_tenant()
		self._validate_no_duplicate_suppliers()

	def _enforce_single_default_per_tenant(self) -> None:
		if not self.is_default:
			return
		other = frappe.db.get_value(
			"Approved Supplier List",
			{
				"tenant": self.tenant,
				"is_default": 1,
				"name": ["!=", self.name or ""],
			},
			"name",
		)
		if other:
			frappe.throw(
				_("Tenant {0} için zaten default bir liste var: {1}").format(self.tenant, other),
				exc=frappe.ValidationError,
			)

	def _validate_no_duplicate_suppliers(self) -> None:
		seen: set[str] = set()
		for entry in self.suppliers or []:
			if entry.supplier in seen:
				frappe.throw(
					_("Aynı supplier iki kez listelenemez: {0}").format(entry.supplier),
					exc=frappe.ValidationError,
				)
			seen.add(entry.supplier)

	def on_update(self):
		from tradehub_core.services import supplier_whitelist

		supplier_whitelist.invalidate_cache(self.tenant)

	def on_trash(self):
		from tradehub_core.services import supplier_whitelist

		supplier_whitelist.invalidate_cache(self.tenant)
