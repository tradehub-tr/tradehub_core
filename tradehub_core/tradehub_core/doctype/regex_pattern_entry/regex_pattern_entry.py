# Copyright (c) 2026, TradeHub Team and contributors

import re

import frappe
from frappe import _
from frappe.model.document import Document

_MAX_REGEX_LENGTH = 200


class RegexPatternEntry(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		# Child seviyesinde de hızlı sanity check; parent ayrıca toplu doğruluyor.
		if self.regex and len(self.regex) > _MAX_REGEX_LENGTH:
			frappe.throw(_("Regex pattern {0} karakteri geçemez").format(_MAX_REGEX_LENGTH))
		if self.regex:
			try:
				re.compile(self.regex)
			except re.error as exc:
				frappe.throw(_("Geçersiz regex: {0} ({1})").format(self.regex, exc))
