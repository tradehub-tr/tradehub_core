import re

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet

from tradehub_core.utils.content_i18n import sync_content_translations


def _slugify(text):
	tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
	text = text.translate(tr_map).lower().strip()
	text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
	return text


class ProductCategory(NestedSet):
	nsm_parent_field = "parent_product_category"

	def validate(self):
		sync_content_translations(self)
		self._validate_unique_name_under_parent()

	def _validate_unique_name_under_parent(self):
		parent = self.parent_product_category or None

		filters = {
			"category_name": self.category_name,
			"name": ["!=", self.name or ""],
		}
		if parent:
			filters["parent_product_category"] = parent
		else:
			filters["parent_product_category"] = ["is", "not set"]

		if frappe.db.exists("Product Category", filters):
			if parent:
				parent_label = frappe.db.get_value("Product Category", parent, "category_name") or parent
				scope = _("'{0}' kategorisi").format(parent_label)
			else:
				scope = _("kök seviye")
			frappe.throw(
				_("'{0}' adında bir kategori bu seviyede zaten mevcut ({1} altında).").format(
					self.category_name, scope
				),
				title=_("Yinelenen kategori adı"),
			)

	def before_save(self):
		if not self.url_slug:
			self.url_slug = _slugify(self.category_name)
