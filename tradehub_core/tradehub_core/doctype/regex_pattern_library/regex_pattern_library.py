# Copyright (c) 2026, TradeHub Team and contributors

import re

import frappe
from frappe import _
from frappe.model.document import Document

_MAX_REGEX_LENGTH = 200
# Katastrofik geri izleme yaratabilen yaygın naif pattern'ları engelle.
_CATASTROPHIC_PATTERNS = (
	re.compile(r"\([^)]*\.\+\)\+"),  # (.+)+
	re.compile(r"\([^)]*\.\*\)\*"),  # (.*)*
	re.compile(r"\([^)]*\+\)\+"),  # (a+)+
)


class RegexPatternLibrary(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		self._validate_seller_scope_link()
		self._validate_patterns()
		self.last_modified_by = frappe.session.user

	def _validate_seller_scope_link(self):
		if self.scope == "Seller Override" and not self.seller_profile:
			frappe.throw(_("Seller Override kapsamında seller_profile zorunlu"))

	def _validate_patterns(self):
		# Pattern uzunluğu + katastrofik geri izleme heuristiği.
		for entry in self.patterns or []:
			pattern = (entry.regex or "").strip()
			if not pattern:
				frappe.throw(_("Regex pattern boş olamaz"))
			if len(pattern) > _MAX_REGEX_LENGTH:
				frappe.throw(
					_("Regex pattern {0} karakteri geçemez (mevcut: {1})").format(
						_MAX_REGEX_LENGTH, len(pattern)
					)
				)
			for compiled in _CATASTROPHIC_PATTERNS:
				if compiled.search(pattern):
					frappe.throw(_("Regex katastrofik geri izleme yaratabilir: {0}").format(pattern))
			try:
				re.compile(pattern)
			except re.error as exc:
				frappe.throw(_("Geçersiz regex: {0} ({1})").format(pattern, exc))
