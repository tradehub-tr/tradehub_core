import frappe
from frappe import _
from frappe.model.document import Document


class SellerXMLFeed(Document):
	def validate(self):
		# Frappe v15: Document base sınıfında validate() yok — super() çağrısı
		# AttributeError fırlatır (bkz. eca_action_template, addresses controller'ları).
		if self.fetch_hour is None or self.fetch_hour < 0 or self.fetch_hour > 23:
			frappe.throw(_("Çekme saati 0 ile 23 arasında olmalıdır."))
