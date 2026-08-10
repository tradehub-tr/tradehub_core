import frappe
from frappe import _
from frappe.model.document import Document


class ShippingMethod(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		self._validate_estimated_days()

	def _validate_estimated_days(self) -> None:
		if (
			self.estimated_delivery_days_min is not None
			and self.estimated_delivery_days_max is not None
			and self.estimated_delivery_days_max < self.estimated_delivery_days_min
		):
			frappe.throw(
				_("Tahmini teslimat gün aralığı geçersiz: maksimum ({0}) minimumdan ({1}) küçük olamaz").format(
					self.estimated_delivery_days_max, self.estimated_delivery_days_min
				)
			)
