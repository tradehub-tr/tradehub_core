import frappe
from frappe import _
from frappe.model.document import Document


class AttributeSet(Document):
	def validate(self):
		self._validate_parent_cycle()
		self._validate_unique_items()

	def _validate_parent_cycle(self):
		if not self.parent_attribute_set:
			return
		if self.parent_attribute_set == self.name:
			frappe.throw(_("Set kendisinin üstü olamaz."))
		visited = {self.name}
		current = self.parent_attribute_set
		while current:
			if current in visited:
				frappe.throw(_("Attribute Set hiyerarşisinde döngü: {0}").format(current))
			visited.add(current)
			current = frappe.db.get_value("Attribute Set", current, "parent_attribute_set")

	def _validate_unique_items(self):
		seen = set()
		for item in self.items or []:
			if item.attribute in seen:
				frappe.throw(_("Attribute {0} sette tekrar ediyor.").format(item.attribute))
			seen.add(item.attribute)
