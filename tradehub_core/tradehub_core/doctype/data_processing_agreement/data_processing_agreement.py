import frappe
from frappe.model.document import Document


class DataProcessingAgreement(Document):
    def validate(self):
        if self.cross_border_transfer and not self.transfer_mechanism:
            frappe.throw("Sınır ötesi veri aktarımı işaretliyse aktarım mekanizması belirtilmelidir.")
        if self.status == "Active" and not self.signed_at:
            frappe.throw("Aktif duruma geçirmeden önce imza tarihi girilmelidir.")
