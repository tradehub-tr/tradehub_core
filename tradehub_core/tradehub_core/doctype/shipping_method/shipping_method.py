import frappe
from frappe import _
from frappe.model.document import Document


class ShippingMethod(Document):
	def validate(self) -> None:
		# super().validate() — Frappe v15: Document.validate yok
		self._validate_delivery_days()

	def _validate_delivery_days(self) -> None:
		"""Teslim süresi aralığını doğrular.

		Otorite alanlar `min_days` / `max_days`'tir. TUR-104'te eklenen
		`estimated_delivery_days_min/max` çifti kaldırıldı: storefront
		(`api/listing.py`) ve `Shipping Method Item` child tablosu zaten legacy
		alanları okuyordu, doğrulama ise yalnız yeni çifti kontrol ediyordu —
		iki kaynak birbirinden bağımsız sürükleniyor ve teslim süresi tutarsız
		görünebiliyordu.
		"""
		if self.min_days is None or self.max_days is None:
			return
		if self.max_days < self.min_days:
			frappe.throw(
				_(
					"Teslimat gün aralığı geçersiz: maksimum ({0}) minimumdan ({1}) küçük olamaz"
				).format(self.max_days, self.min_days)
			)
