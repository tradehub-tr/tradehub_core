import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate


class SellerCertification(Document):
	def validate(self):
		self._validate_certification_type()
		self._validate_dates()

	def _validate_certification_type(self):
		"""Cert Type Approved olmalı (kategori serbest — mağaza her ikisi de olabilir)."""
		if not self.certification_type:
			return
		ct = frappe.db.get_value(
			"Certification Type",
			self.certification_type,
			["status", "category"],
			as_dict=True,
		)
		if not ct:
			frappe.throw(_("Sertifika tipi bulunamadı: {0}").format(self.certification_type))
		if ct.status != "Approved":
			frappe.throw(
				_("Sadece onaylanmış sertifikalar atanabilir. '{0}' durumu: {1}").format(
					self.certification_type, ct.status
				)
			)

	def _validate_dates(self):
		if self.issued_date and self.expiry_date:
			if getdate(self.expiry_date) < getdate(self.issued_date):
				frappe.throw(_("Bitiş tarihi verilme tarihinden önce olamaz."))
