import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class THModuleRegistry(NestedSet):
	nsm_parent_field = "parent_th_module_registry"

	def validate(self):
		self._validate_target_consistency()
		self._validate_panel_inheritance()

	def on_update(self):
		_flush_module_cache()

	def on_trash(self):
		if self.is_protected:
			frappe.throw(
				_("Korumalı modül silinemez: {0}").format(self.module_key),
				exc=frappe.PermissionError,
			)
		# NestedSet base class handles cascade for tree

	def after_delete(self):
		_flush_module_cache()

	def _validate_target_consistency(self):
		"""Item tipi route veya doctype_ref'ten en az birini taşımalı.
		Section/group ise her ikisi de boş olmalı."""
		has_target = bool(self.route) or bool(self.doctype_ref)
		if self.item_type == "item" and not has_target:
			frappe.throw(
				_("Item tipi modül için route veya doctype_ref şart: {0}").format(self.module_key),
				exc=frappe.ValidationError,
			)
		if self.item_type in ("section", "group") and has_target:
			frappe.throw(
				_("Section/Group tipinde route/doctype_ref olmaz: {0}").format(self.module_key),
				exc=frappe.ValidationError,
			)

	def _validate_panel_inheritance(self):
		"""Alt modül üst modülün panel'ine uymalı."""
		if not self.parent_th_module_registry:
			return
		parent_panel = frappe.db.get_value("TH Module Registry", self.parent_th_module_registry, "panel")
		if parent_panel and parent_panel != self.panel:
			frappe.throw(
				_("Alt modül panel'i üst modülün panel'iyle aynı olmalı: {0} (üst: {1})").format(
					self.panel, parent_panel
				),
				exc=frappe.ValidationError,
			)


def _flush_module_cache():
	try:
		frappe.cache().delete_keys("tradehub:mod:")
	except Exception:
		frappe.log_error("Module cache flush failed", "TH Module Registry")
