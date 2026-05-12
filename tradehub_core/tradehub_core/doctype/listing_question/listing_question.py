import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime


class ListingQuestion(Document):
	def before_insert(self):
		# Form'dan direkt insert için defaultlar
		if not self.submitted_at:
			self.submitted_at = now_datetime()
		if not self.asker:
			self.asker = frappe.session.user
		if not self.asker_display_name:
			self._populate_display_name()
		# KYB cache
		self._populate_kyb_flag()

	def validate(self):
		if not self.status:
			self.status = "Pending"

	def _populate_display_name(self):
		from tradehub_core.api.qa import _resolve_display_name

		self.asker_display_name = _resolve_display_name(self.asker)

	def _populate_kyb_flag(self):
		if not self.asker:
			return
		status = frappe.db.get_value("KYB Verification", {"user": self.asker}, "status")
		self.is_kyb_verified = 1 if status == "Verified" else 0
