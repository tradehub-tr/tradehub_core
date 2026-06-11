# Copyright (c) 2026, TR TradeHub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class SalesTeam(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._assert_members_not_in_other_active_team()

	def _assert_members_not_in_other_active_team(self):
		"""Bir saha elemanı aynı anda yalnız bir AKTİF ekipte olabilir.

		Pasif ekipte aynı eleman olabilir (arşiv). Batch sorgu — üye listesi küçük
		olsa da N+1'den kaçın (anti-pattern #6).
		"""
		if not self.is_active:
			return
		agents = [m.agent for m in self.members if m.agent]
		if not agents:
			return
		dupes = frappe.get_all(
			"Sales Team Member",
			filters={"agent": ["in", agents], "parent": ["!=", self.name]},
			fields=["agent", "parent"],
		)
		if not dupes:
			return
		active_parents = set(
			frappe.get_all(
				"Sales Team",
				filters={"name": ["in", list({d.parent for d in dupes})], "is_active": 1},
				pluck="name",
			)
		)
		for d in dupes:
			if d.parent in active_parents:
				frappe.throw(_("{0} zaten aktif bir ekipte: {1}").format(d.agent, d.parent))
