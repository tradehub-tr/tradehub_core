import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.utils.notify import notify


class RFQ(Document):
	def before_insert(self):
		if not self.buyer:
			self.buyer = frappe.session.user

	def validate(self):
		self._validate_status_transition()

	def on_update(self):
		self._update_quote_count()
		self._send_status_notifications()

	def _send_status_notifications(self):
		old = self.get_doc_before_save()
		if not old or old.status == self.status:
			return

		if self.status == "Approved":
			notify(
				recipient_user=self.buyer,
				recipient_role="buyer",
				type="rfq",
				title=_("RFQ Onaylandı"),
				message=_("{0} numaralı teklif talebiniz onaylandı.").format(self.name),
				action_url=f"/buyer-dashboard?tab=rfq&rfq={self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)
		elif self.status == "Rejected":
			notify(
				recipient_user=self.buyer,
				recipient_role="buyer",
				type="rfq",
				title=_("RFQ Reddedildi"),
				message=_("{0} numaralı teklif talebiniz reddedildi.").format(self.name),
				action_url=f"/buyer-dashboard?tab=rfq&rfq={self.name}",
				reference_doctype="RFQ",
				reference_name=self.name,
			)

	def _validate_status_transition(self):
		if self.is_new():
			return
		old_status = self.get_doc_before_save()
		if not old_status:
			return
		old_status = old_status.status
		if old_status == self.status:
			return

		user = frappe.session.user
		is_admin = (
			user == "Administrator"
			or "System Manager" in frappe.get_roles(user)
			or "Marketplace Admin" in frappe.get_roles(user)
		)

		# Pending → Approved/Rejected: only admin
		if old_status == "Pending" and self.status in ("Approved", "Rejected"):
			if not is_admin:
				frappe.throw(_("Only administrators can approve or reject RFQs"))

	def _update_quote_count(self):
		count = frappe.db.count("RFQ Quote", {"rfq": self.name})
		if count != self.quote_count:
			self.db_set("quote_count", count)
