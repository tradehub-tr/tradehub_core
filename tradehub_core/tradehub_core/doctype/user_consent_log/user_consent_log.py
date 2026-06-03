import frappe
from frappe.model.document import Document


class UserConsentLog(Document):
	def before_insert(self):
		if not self.ip_address:
			self.ip_address = frappe.local.request_ip if hasattr(frappe.local, "request_ip") else None
		if not self.user_agent and hasattr(frappe.local, "request") and frappe.local.request:
			self.user_agent = (frappe.local.request.headers.get("User-Agent") or "")[:500]
