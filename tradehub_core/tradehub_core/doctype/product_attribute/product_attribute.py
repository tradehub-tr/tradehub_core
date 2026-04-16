import re

import frappe
from frappe import _
from frappe.model.document import Document

SELECT_TYPES = {"Select", "Multi-Select", "Color"}
NUMERIC_TYPES = {"Number", "Integer", "Decimal"}


class ProductAttribute(Document):
	def validate(self):
		self._validate_select_options()
		self._validate_numeric_bounds()
		self._validate_regex()
		self._validate_variant_axis()

	def _validate_select_options(self):
		if self.data_type in SELECT_TYPES and not self.value_options:
			frappe.throw(_("{0} tipi için en az bir değer seçeneği gerekli.").format(self.data_type))

	def _validate_numeric_bounds(self):
		if self.data_type not in NUMERIC_TYPES:
			return
		if self.min_value and self.max_value:
			try:
				if float(self.min_value) > float(self.max_value):
					frappe.throw(_("Min değer Max değerden büyük olamaz."))
			except ValueError:
				frappe.throw(_("Min/Max sayısal olmalı."))

	def _validate_regex(self):
		if self.regex_pattern:
			try:
				re.compile(self.regex_pattern)
			except re.error as exc:
				frappe.throw(_("Geçersiz regex: {0}").format(exc))

	def _validate_variant_axis(self):
		if self.is_variant_axis and self.data_type not in SELECT_TYPES:
			frappe.throw(_("Varyant ekseni yalnızca Select/Multi-Select/Color tipinde olabilir."))
