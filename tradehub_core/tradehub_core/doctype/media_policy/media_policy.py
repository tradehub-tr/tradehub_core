"""Validated projection of the canonical slot-policy JSON files."""

from __future__ import annotations

import re

import frappe
from frappe import _
from frappe.model.document import Document

_SLOT_KEY = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class MediaPolicy(Document):
	def validate(self) -> None:
		if hasattr(super(), "validate"):
			super().validate()
		self.slot_key = (self.slot_key or "").strip()
		if not _SLOT_KEY.fullmatch(self.slot_key):
			frappe.throw(_("Slot anahtarı '<alan>.<slot>' biçiminde olmalı: {0}").format(self.slot_key))
		seen: set[str] = set()
		for row in self.get("profiles") or ():
			if row.profile in seen:
				frappe.throw(_("Politika profili tekrar ediyor: {0}").format(row.profile))
			seen.add(row.profile)
