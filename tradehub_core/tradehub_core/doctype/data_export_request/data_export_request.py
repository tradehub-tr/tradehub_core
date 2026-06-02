import frappe
from frappe.model.document import Document


class DataExportRequest(Document):
	def before_insert(self):
		self.user = frappe.session.user
		self.requested_at = frappe.utils.now_datetime()
		self._check_rate_limit()

	def _check_rate_limit(self):
		recent = frappe.db.count(
			"Data Export Request",
			filters={
				"user": self.user,
				"requested_at": (
					">",
					frappe.utils.add_to_date(None, hours=-24),
				),
				"status": ("in", ["Pending", "Processing", "Ready"]),
			},
		)
		if recent:
			frappe.throw(
				"24 saat içinde yalnızca 1 veri dışa aktarma talebi oluşturabilirsiniz.",
				frappe.RateLimitExceededError,
			)
