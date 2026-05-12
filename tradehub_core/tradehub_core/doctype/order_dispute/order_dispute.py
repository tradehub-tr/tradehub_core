import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class OrderDispute(Document):
	def before_insert(self):
		if not self.opened_at:
			self.opened_at = now_datetime()

	def on_update(self):
		"""Status değiştiğinde Listing Review cache'ini sync et.

		Form'dan manuel resolve edildiğinde de `dispute_resolved_in_favor_of`
		cache'inin güncellenmesi için. API tarafı `resolve_dispute` zaten
		bunu yapıyor, ama Desk form save'i de tetiklesin.
		"""
		old = self.get_doc_before_save()
		if not old:
			return

		# Resolved state'lere geçiş
		if old.status != self.status and self.status in ("Resolved-Buyer", "Resolved-Seller"):
			if not self.resolved_at:
				frappe.db.set_value(
					"Order Dispute",
					self.name,
					"resolved_at",
					now_datetime(),
					update_modified=False,
				)
			# Listing Review cache
			if self.related_review:
				favor = "buyer" if self.status == "Resolved-Buyer" else "seller"
				if not self.in_favor_of:
					frappe.db.set_value(
						"Order Dispute",
						self.name,
						"in_favor_of",
						favor,
						update_modified=False,
					)
				frappe.db.set_value(
					"Listing Review",
					self.related_review,
					"dispute_resolved_in_favor_of",
					favor,
					update_modified=False,
				)
