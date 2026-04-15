import frappe
from frappe.utils.nestedset import NestedSet
import re

def _slugify(text):
    tr_map = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosucgiosu")
    text = text.translate(tr_map).lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text

class ProductCategory(NestedSet):
    nsm_parent_field = "parent_product_category"

    def before_save(self):
        if not self.url_slug:
            self.url_slug = _slugify(self.category_name)
