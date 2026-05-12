"""Review Helpful Vote — yorumlara faydalı/faydalı değil oyu (Faz 2)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class ReviewHelpfulVote(Document):
	def validate(self):
		if not self.voted_at:
			self.voted_at = now_datetime()
		if self.vote not in ("helpful", "not_helpful"):
			frappe.throw(_("Geçersiz oy değeri"))
		# Aynı (review, voter) için unique
		filters = {"review": self.review, "voter": self.voter}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Review Helpful Vote", filters):
			frappe.throw(_("Bu yoruma zaten oy verdiniz"))

	def after_insert(self):
		self._recompute_review_counts()

	def on_update(self):
		# Vote değişimi (helpful → not_helpful) sayaçları etkiler
		old = self.get_doc_before_save()
		if old and old.vote != self.vote:
			self._recompute_review_counts()

	def on_trash(self):
		self._recompute_review_counts(exclude_self=True)

	def _recompute_review_counts(self, exclude_self: bool = False):
		if not self.review:
			return
		from tradehub_core.api.review import recompute_review_helpful_counts

		recompute_review_helpful_counts(self.review, exclude_vote_name=self.name if exclude_self else None)
