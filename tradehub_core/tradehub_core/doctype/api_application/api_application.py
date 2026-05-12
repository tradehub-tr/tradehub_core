import secrets

from frappe.model.document import Document


class APIApplication(Document):
	def before_insert(self):
		if not self.client_id:
			self.client_id = secrets.token_urlsafe(16)
		if not self.client_secret:
			self.client_secret = secrets.token_urlsafe(32)
