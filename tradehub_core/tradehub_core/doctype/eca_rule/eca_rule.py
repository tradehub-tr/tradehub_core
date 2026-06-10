# Copyright (c) 2026, TradeHub Team and contributors

import json

import frappe
from frappe import _
from frappe.model.document import Document

from tradehub_core.eca.condition_compiler import CompileError, compile_condition

_SELLER_PRIORITY_MIN = 100
_SELLER_PRIORITY_MAX = 999
_ADMIN_PRIORITY_MIN = 1000
_SELLER_FORBIDDEN_ACTIONS = ("custom_script", "create_document")


class ECARule(Document):
	def validate(self):
		# super().validate() — Frappe v15: Document.validate yok
		# Builder doluysa condition'ı ondan ÜRET (condition salt-üretilmiş olur).
		self._compile_condition_from_builder()
		# Owner rolüne göre execution_phase otomatik set edilir.
		self.execution_phase = "Seller Phase" if self.owner_role == "Seller" else "Admin Phase"
		self._validate_scope_and_priority()
		self._validate_per_seller_link()

	def _compile_condition_from_builder(self):
		"""condition_builder doluysa condition alanını derler.

		Builder boşsa elle girilen condition korunur (geri uyum).
		"""
		raw = (self.condition_builder or "").strip()
		if not raw:
			return
		try:
			builder = json.loads(raw)
		except json.JSONDecodeError:
			frappe.throw(_("Condition Builder geçerli JSON değil"))
		try:
			self.condition = compile_condition(builder, doctype=self.reference_doctype or "Listing")
		except CompileError as e:
			frappe.throw(_("Condition Builder derlenemedi: {0}").format(str(e)))

	def _validate_scope_and_priority(self):
		if self.owner_role == "Seller":
			if self.rule_scope != "Per-Seller":
				frappe.throw(_("Satıcı kuralları yalnızca 'Per-Seller' kapsamında olabilir"))
			if self.action_type in _SELLER_FORBIDDEN_ACTIONS:
				frappe.throw(_("Custom Script ve Create Document aksiyonları satıcılara kapalıdır"))
			if not (_SELLER_PRIORITY_MIN <= (self.priority or 0) <= _SELLER_PRIORITY_MAX):
				frappe.throw(_("Satıcı kuralları priority 100-999 aralığında olmalı"))
		elif self.owner_role in ("System Manager", "Marketplace Admin"):
			if (self.priority or 0) < _ADMIN_PRIORITY_MIN:
				frappe.throw(_("Platform kuralları priority 1000+ olmalı"))

	def _validate_per_seller_link(self):
		if self.rule_scope == "Per-Seller" and not self.seller_profile:
			frappe.throw(_("Per-Seller kapsamında seller_profile zorunlu"))
