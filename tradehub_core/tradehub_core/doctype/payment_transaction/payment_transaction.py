import frappe
from frappe.model.document import Document


class PaymentTransaction(Document):
    def validate(self):
        if self.transaction_type == "İade" and not self.refund_reason:
            frappe.throw(frappe._("İade işlemleri için neden belirtilmelidir."))
