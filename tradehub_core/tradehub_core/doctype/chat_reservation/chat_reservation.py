from frappe import _, throw
from frappe.exceptions import ValidationError
from frappe.model.document import Document


class ChatReservation(Document):
	def validate(self):
		if self.start_at and self.end_at and self.start_at >= self.end_at:
			throw(_("Bitiş zamanı başlangıçtan sonra olmalı."), ValidationError)
		if self.buyer_user == self.seller_user:
			throw(_("Alıcı ve satıcı aynı kullanıcı olamaz."), ValidationError)
