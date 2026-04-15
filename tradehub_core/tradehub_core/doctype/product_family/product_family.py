import frappe
from frappe import _
from frappe.model.document import Document


class ProductFamily(Document):
	def validate(self):
		self._validate_parent_cycle()
		self._normalize_variant_axes()

	def _validate_parent_cycle(self):
		if not self.parent_family:
			return
		if self.parent_family == self.name:
			frappe.throw(_("Aile kendisinin üstü olamaz."))
		visited = {self.name}
		current = self.parent_family
		while current:
			if current in visited:
				frappe.throw(_("Aile hiyerarşisinde döngü: {0}").format(current))
			visited.add(current)
			current = frappe.db.get_value("Product Family", current, "parent_family")

	def _normalize_variant_axes(self):
		if self.variant_axes:
			parts = [p.strip() for p in self.variant_axes.split(",") if p.strip()]
			self.variant_axes = ",".join(parts)
