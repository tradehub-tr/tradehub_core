import re

import frappe
from frappe import _
from frappe.model.document import Document

_CAPABILITY_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)*$")


class THCapabilityRegistry(Document):
	def validate(self):
		if not _CAPABILITY_KEY_RE.match(self.capability_key or ""):
			frappe.throw(
				_("Geçersiz capability_key formatı. Örnek: view.bank_info, order.ship"),
				exc=frappe.ValidationError,
			)

		if self.is_owner_only and self.default_tier != "OWNER_ONLY":
			self.default_tier = "OWNER_ONLY"

	def on_trash(self):
		if self.is_protected:
			frappe.throw(
				_("Korumalı capability silinemez: {0}").format(self.capability_key),
				exc=frappe.PermissionError,
			)

	def on_update(self):
		_flush_capability_cache()

	def after_delete(self):
		_flush_capability_cache()


def _flush_capability_cache():
	try:
		frappe.cache().delete_keys("tradehub:cap:")
	except Exception:
		frappe.log_error("Capability cache flush failed", "TH Capability Registry")
