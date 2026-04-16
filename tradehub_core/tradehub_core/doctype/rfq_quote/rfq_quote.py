import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.utils.notify import notify


class RFQQuote(Document):
	def before_insert(self):
		if not self.seller:
			self.seller = frappe.session.user
		if not self.seller_profile:
			self.seller_profile = frappe.db.get_value("Seller Profile", {"user": self.seller}, "name")

	def after_insert(self):
		self._update_rfq_quote_count()
		self._notify_buyer_new_quote()

	def on_update(self):
		self._notify_quote_status_change()

	def on_trash(self):
		self._update_rfq_quote_count()

	def _notify_buyer_new_quote(self):
		if not self.rfq:
			return
		buyer = frappe.db.get_value("RFQ", self.rfq, "buyer")
		if buyer:
			seller_name = (
				frappe.db.get_value("Seller Profile", {"user": self.seller}, "seller_name") or self.seller
			)
			notify(
				recipient_user=buyer,
				recipient_role="buyer",
				type="rfq",
				title=_("Yeni Teklif Geldi"),
				message=_("{0} talebinize {1} teklif verdi.").format(self.rfq, seller_name),
				action_url=f"/buyer-dashboard?tab=rfq&rfq={self.rfq}",
				reference_doctype="RFQ Quote",
				reference_name=self.name,
			)

	def _notify_quote_status_change(self):
		"""Teklif kabul/red edildiğinde satıcıya bildirim gönder."""
		old = self.get_doc_before_save()
		if not old or old.status == self.status:
			return
		if not self.seller:
			return

		if self.status == "Accepted":
			notify(
				recipient_user=self.seller,
				recipient_role="seller",
				type="rfq",
				title=_("Teklifiniz Kabul Edildi"),
				message=_("{0} talebine verdiğiniz teklif kabul edildi.").format(self.rfq),
				action_url=f"/app/rfq/{self.rfq}",
				reference_doctype="RFQ Quote",
				reference_name=self.name,
			)
		elif self.status == "Rejected":
			notify(
				recipient_user=self.seller,
				recipient_role="seller",
				type="rfq",
				title=_("Teklifiniz Reddedildi"),
				message=_("{0} talebine verdiğiniz teklif reddedildi.").format(self.rfq),
				action_url=f"/app/rfq/{self.rfq}",
				reference_doctype="RFQ Quote",
				reference_name=self.name,
			)

	def _update_rfq_quote_count(self):
		if self.rfq:
			count = frappe.db.count("RFQ Quote", {"rfq": self.rfq})
			frappe.db.set_value("RFQ", self.rfq, "quote_count", count)
