import re

import frappe
from frappe import _
from frappe.model.document import Document


class SEORedirect(Document):
	def validate(self):
		super().validate() if hasattr(super(), "validate") else None
		self._validate_paths()
		self._validate_no_self_loop()
		self._validate_regex_if_applicable()

	def _validate_paths(self):
		"""source_path / ile başlamalı; target / veya http(s):// ile."""
		if not self.source_path or not self.source_path.startswith("/"):
			frappe.throw(_("Source Path '/' ile başlamalı"))
		if not self.target_path:
			frappe.throw(_("Target Path boş olamaz"))
		if not (self.target_path.startswith("/") or self.target_path.startswith(("http://", "https://"))):
			frappe.throw(_("Target Path '/' veya http(s):// ile başlamalı"))

	def _validate_no_self_loop(self):
		"""source == target self-loop oluşturur."""
		if self.source_path == self.target_path:
			frappe.throw(_("Source ve target aynı olamaz (self-loop)"))

	def _validate_regex_if_applicable(self):
		"""match_type=regex ise source_path geçerli regex olmalı."""
		if self.match_type == "regex":
			try:
				re.compile(self.source_path)
			except re.error as e:
				frappe.throw(_("Geçersiz regex: {0}").format(str(e)))
