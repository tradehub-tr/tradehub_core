import frappe
from frappe import _
from frappe.model.document import Document


class UserEmailPreference(Document):
	def before_save(self):
		if self.user != frappe.session.user:
			roles = frappe.get_roles(frappe.session.user)
			if "System Manager" not in roles and "Marketplace Admin" not in roles:
				frappe.throw(
					_("Başka bir kullanıcının tercihlerini değiştiremezsiniz."),
					frappe.PermissionError,
				)
