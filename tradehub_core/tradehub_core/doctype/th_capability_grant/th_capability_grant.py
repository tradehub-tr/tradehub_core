import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class THCapabilityGrant(Document):
	def validate(self):
		self._enforce_unique_pair()
		self._populate_audit_fields()

	def on_update(self):
		_flush_grant_cache(self.role_profile)

	def after_insert(self):
		_flush_grant_cache(self.role_profile)

	def after_delete(self):
		_flush_grant_cache(self.role_profile)

	def _enforce_unique_pair(self):
		existing = frappe.db.get_value(
			"TH Capability Grant",
			{
				"role_profile": self.role_profile,
				"capability": self.capability,
				"name": ["!=", self.name],
			},
			"name",
		)
		if existing:
			frappe.throw(
				_("Bu role profile için bu capability zaten tanımlı: {0}").format(existing),
				exc=frappe.DuplicateEntryError,
			)

	def _populate_audit_fields(self):
		if not self.granted_by:
			self.granted_by = frappe.session.user
		if not self.granted_at:
			self.granted_at = now_datetime()


def _flush_grant_cache(role_profile: str | None = None):
	try:
		if role_profile:
			frappe.cache().delete_value(f"tradehub:grant:{role_profile}")
		frappe.cache().delete_keys("tradehub:cap:")
	except Exception:
		frappe.log_error("Grant cache flush failed", "TH Capability Grant")
