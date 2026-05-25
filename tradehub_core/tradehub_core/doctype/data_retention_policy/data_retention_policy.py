import frappe
from frappe.model.document import Document


class DataRetentionPolicy(Document):
    def validate(self):
        if self.retention_days < 1:
            frappe.throw("Saklama süresi en az 1 gün olmalıdır.")

        if not self.fields_to_anonymize:
            frappe.throw("En az bir anonimleştirilecek alan belirtilmelidir.")

        meta = frappe.get_meta(self.ref_doctype)
        if not meta.has_field(self.date_field):
            frappe.throw(f"{self.ref_doctype} DocType'ında '{self.date_field}' alanı bulunamadı.")

        for row in self.fields_to_anonymize:
            if not meta.has_field(row.fieldname):
                frappe.throw(
                    f"{self.ref_doctype} DocType'ında '{row.fieldname}' alanı bulunamadı."
                )
