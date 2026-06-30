import frappe
from frappe import _
from frappe.model.document import Document


class SellerVerification(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._check_duplicate()
		self._enforce_status_rule()

	def _check_duplicate(self):
		"""Aynı (seller, source) çifti ikinci kez eklenememeli."""
		if not self.seller or not self.source:
			return
		filters = {"seller": self.seller, "source": self.source}
		if not self.is_new():
			filters["name"] = ["!=", self.name]
		if frappe.db.exists("Seller Verification", filters):
			frappe.throw(
				_("Bu satıcı için bu doğrulama kaynağı zaten kayıtlı."),
				frappe.DuplicateEntryError,
			)

	def _enforce_status_rule(self):
		"""Status değişikliği yalnız Administrator veya System Manager yapabilir.

		Yeni kayıtlarda durum her zaman 'Pending' olarak ayarlanır; satıcı
		başvuruyu yükler, onay superadmin'e aittir.
		"""
		if self.is_new():
			# Satıcı kendi başvurusunu oluşturur; durum Pending'den başlar.
			self.status = "Pending"
			return
		old_status = frappe.db.get_value("Seller Verification", self.name, "status")
		if old_status == self.status:
			return
		roles = set(frappe.get_roles(frappe.session.user))
		if frappe.session.user != "Administrator" and "System Manager" not in roles:
			frappe.throw(
				_("Doğrulama durumu yalnızca Administrator tarafından değiştirilebilir."),
				frappe.PermissionError,
			)
