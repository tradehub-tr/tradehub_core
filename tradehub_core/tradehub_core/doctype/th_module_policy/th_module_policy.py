import frappe
from frappe import _
from frappe.model.document import Document


class THModulePolicy(Document):
	def validate(self):
		self._enforce_unique_pair()
		self._validate_date_range()

	def on_update(self):
		_flush_module_cache()

	def after_insert(self):
		_flush_module_cache()

	def after_delete(self):
		_flush_module_cache()

	def _enforce_unique_pair(self):
		existing = frappe.db.get_value(
			"TH Module Policy",
			{"module": self.module, "role_profile": self.role_profile, "name": ["!=", self.name]},
			"name",
		)
		if existing:
			frappe.throw(
				_("Bu modül için bu role profile zaten tanımlı: {0}").format(existing),
				exc=frappe.DuplicateEntryError,
			)

	def _validate_date_range(self):
		if self.effective_from and self.effective_to and self.effective_from > self.effective_to:
			frappe.throw(
				_("Başlangıç tarihi bitişten sonra olamaz."),
				exc=frappe.ValidationError,
			)


def _flush_module_cache():
	try:
		frappe.cache().delete_keys("tradehub:mod:")
	except Exception:
		frappe.log_error("Module cache flush failed", "TH Module Policy")
