import frappe
from frappe.model.document import Document
from frappe.utils import add_days, getdate


class ProcessingActivityRecord(Document):
    def validate(self):
        if self.review_interval_days and self.review_interval_days < 1:
            frappe.throw("Gözden geçirme aralığı en az 1 gün olmalıdır.")

    @property
    def needs_review(self) -> bool:
        if not self.last_reviewed or not self.review_interval_days:
            return True
        next_review = add_days(getdate(self.last_reviewed), self.review_interval_days)
        return getdate() >= next_review
