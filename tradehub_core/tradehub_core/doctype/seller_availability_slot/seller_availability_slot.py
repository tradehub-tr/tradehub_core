from frappe import _, throw
from frappe.exceptions import ValidationError
from frappe.model.document import Document


class SellerAvailabilitySlot(Document):
	def validate(self):
		if self.start_at and self.end_at and self.start_at >= self.end_at:
			throw(_("Bitiş zamanı başlangıçtan sonra olmalı."), ValidationError)
