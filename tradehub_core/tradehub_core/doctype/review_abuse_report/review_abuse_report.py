"""Review Abuse Report — yorumlara karşı ihbar (Faz 2).

Eşik (default 3) aşılırsa Listing Review otomatik 'Hidden' olur.
"""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime

ABUSE_THRESHOLD = 3


class ReviewAbuseReport(Document):
	def validate(self):
		if not self.created_at:
			self.created_at = now_datetime()
		if not self.reporter:
			self.reporter = frappe.session.user
		if self.reporter == "Guest":
			frappe.throw(_("İhbar için giriş yapmalısınız"), frappe.AuthenticationError)

		# Aynı (review, reporter) için bir kez ihbar
		filters = {"review": self.review, "reporter": self.reporter}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Review Abuse Report", filters):
			frappe.throw(_("Bu yorumu zaten ihbar ettiniz"))

	def after_insert(self):
		self._update_review_count_and_threshold()

	def on_update(self):
		old = self.get_doc_before_save()
		if old and bool(old.resolved) != bool(self.resolved):
			self._update_review_count_and_threshold()

	def on_trash(self):
		self._update_review_count_and_threshold(exclude_self=True)

	def _update_review_count_and_threshold(self, exclude_self: bool = False):
		if not self.review:
			return
		from tradehub_core.api.review import recompute_abuse_count_and_threshold

		recompute_abuse_count_and_threshold(
			self.review,
			exclude_report_name=self.name if exclude_self else None,
		)
