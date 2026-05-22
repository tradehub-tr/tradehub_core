# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Order Approval — bir order için onay zinciri instance'ı.

State machine:
  Pending L1 → Approved L1 → Pending L2 (varsa) → Approved
                            ↘ Rejected
                                ↘ Timeout Rejected (Faz 3 scheduler)

Tek aktif Order Approval per Order. Reject sonrası order baştan submit edilirse
yeni Order Approval oluşturulur.

Detay: docs/yetki/faz-2/03-faz-2-detayli-plan.md §2.5
"""

import frappe
from frappe import _
from frappe.model.document import Document

# State machine — Hangi geçişler geçerli
_VALID_TRANSITIONS: dict[str, set[str]] = {
	"Pending L1": {"Approved L1", "Approved", "Rejected", "Timeout Rejected"},
	"Approved L1": {"Pending L2", "Approved"},  # L1 onaylandı, L2 var ise Pending L2'ye
	"Pending L2": {"Approved", "Rejected", "Timeout Rejected"},
	"Approved": set(),  # terminal
	"Rejected": set(),  # terminal
	"Timeout Rejected": set(),  # terminal
}


class OrderApproval(Document):
	def validate(self) -> None:
		self._validate_status_transition()
		self._validate_max_level()

	def _validate_status_transition(self) -> None:
		"""State machine geçiş kontrolü."""
		if self.is_new() or not self.name:
			return
		old_status = frappe.db.get_value("Order Approval", self.name, "status")
		if old_status and old_status != self.status:
			allowed = _VALID_TRANSITIONS.get(old_status, set())
			if self.status not in allowed:
				frappe.throw(
					_("Geçersiz status geçişi: {0} → {1}. İzin verilen: {2}").format(
						old_status, self.status, ", ".join(sorted(allowed)) or "(terminal)"
					)
				)

	def _validate_max_level(self) -> None:
		if (self.max_level or 0) not in (1, 2):
			frappe.throw(_("max_level 1 veya 2 olmalı."))

	def is_terminal(self) -> bool:
		"""Onay süreci sona erdi mi?"""
		return self.status in ("Approved", "Rejected", "Timeout Rejected")
