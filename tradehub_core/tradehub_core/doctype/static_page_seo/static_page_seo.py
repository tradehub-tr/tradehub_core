import frappe
from frappe import _
from frappe.model.document import Document


class StaticPageSEO(Document):
	def validate(self):
		# Path canonicalization: leading /, no trailing /, no double //
		if self.page_path:
			path = self.page_path.strip()
			if not path.startswith("/"):
				path = "/" + path
			if len(path) > 1 and path.endswith("/"):
				path = path.rstrip("/")
			while "//" in path:
				path = path.replace("//", "/")
			self.page_path = path
		# meta_title fallback
		if not self.meta_title and self.page_title:
			self.meta_title = self.page_title
