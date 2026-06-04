import frappe
from frappe import _
from frappe.model.document import Document


class HeroSlide(Document):
	def validate(self):
		super().validate()
		if self.background_type == "image" and not self.background_image:
			frappe.throw(_("Arka plan türü 'görsel' iken arka plan görseli zorunludur."))
		if self.background_type in ("color", "gradient") and not self.background_color:
			frappe.throw(_("Arka plan rengi zorunludur."))
		if self.background_type == "gradient" and not self.background_color_2:
			frappe.throw(_("Gradient için bitiş rengi zorunludur."))
