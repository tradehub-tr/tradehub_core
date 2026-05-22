# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class AuthorizationAnomalyRule(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		if self.threshold_count is not None and int(self.threshold_count) < 1:
			frappe.throw(_("Threshold en az 1 olmalı"), exc=frappe.ValidationError)
		if self.window_minutes is not None and int(self.window_minutes) < 1:
			frappe.throw(_("Window minimum 1 dakika olmalı"), exc=frappe.ValidationError)
