import frappe
from frappe import _
from frappe.model.document import Document


class ProductType(Document):
	def validate(self):
		self._validate_parent_cycle()
		self._validate_service_flags()

	def _validate_parent_cycle(self):
		if not self.parent_product_type:
			return
		if self.parent_product_type == self.name:
			frappe.throw(_("Ürün tipi kendisinin üst tipi olamaz."))
		visited = {self.name}
		current = self.parent_product_type
		while current:
			if current in visited:
				frappe.throw(_("Ürün tipi hiyerarşisinde döngü: {0}").format(current))
			visited.add(current)
			current = frappe.db.get_value("Product Type", current, "parent_product_type")

	def _validate_service_flags(self):
		if self.is_service and self.requires_shipping:
			frappe.throw(_("Hizmet tipi ürün kargo gerektiremez."))
		if self.is_digital and self.has_batch:
			frappe.throw(_("Dijital ürün parti takipli olamaz."))
