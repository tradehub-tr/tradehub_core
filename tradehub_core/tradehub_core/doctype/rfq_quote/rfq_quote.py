import frappe
from frappe.model.document import Document


class RFQQuote(Document):
	def before_insert(self):
		if not self.seller:
			self.seller = frappe.session.user
		if not self.seller_profile:
			self.seller_profile = frappe.db.get_value(
				"Seller Profile", {"user": self.seller}, "name"
			)

	def after_insert(self):
		self._update_rfq_quote_count()

	def on_trash(self):
		self._update_rfq_quote_count()

	def _update_rfq_quote_count(self):
		if self.rfq:
			count = frappe.db.count("RFQ Quote", {"rfq": self.rfq})
			frappe.db.set_value("RFQ", self.rfq, "quote_count", count)
