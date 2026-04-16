import frappe
from frappe.model.document import Document


class PlatformNotification(Document):
	def before_save(self):
		if self.is_read and not self.read_at:
			self.read_at = frappe.utils.now()
