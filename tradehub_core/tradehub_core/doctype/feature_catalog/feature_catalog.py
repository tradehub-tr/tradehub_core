# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Feature Catalog DocType controller.

Tüm `feature.*` ve `quota.*` key'lerinin tek doğru kaynağı (registry).
Subscription Plan'daki capability_flags ve quota_limits JSON'larında bu
registry'deki key'ler kullanılır; tanımsız key kullanılırsa Plan validate
edilirken uyarı verilir.

Detay: docs/yetki/03-doctype-sablonlari.md §4
"""

import re

import frappe
from frappe import _
from frappe.model.document import Document

_KEY_PATTERN = re.compile(r"^(feature|quota)\.[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$")


class FeatureCatalog(Document):
	def validate(self) -> None:
		self._validate_key_format()
		self._validate_key_matches_type()
		self._validate_default_value()

	def _validate_key_format(self) -> None:
		"""feature_key dot-notation lowercase olmalı."""
		if not self.feature_key:
			return
		key = self.feature_key.strip()
		if not _KEY_PATTERN.match(key):
			frappe.throw(
				_(
					"Feature Key dot-notation lowercase olmalı: 'feature.category.name' veya "
					"'quota.metric_name' (örn. 'feature.pim.multi_variant', 'quota.max_sub_users')."
				)
			)
		self.feature_key = key

	def _validate_key_matches_type(self) -> None:
		"""'feature.*' Capability, 'quota.*' Quota olmalı."""
		if not self.feature_key or not self.feature_type:
			return
		if self.feature_key.startswith("feature.") and self.feature_type != "Capability":
			frappe.throw(
				_("'feature.*' prefix'i Capability tipinde olmalı. Şu an: {0}").format(self.feature_type)
			)
		if self.feature_key.startswith("quota.") and self.feature_type != "Quota":
			frappe.throw(_("'quota.*' prefix'i Quota tipinde olmalı. Şu an: {0}").format(self.feature_type))

	def _validate_default_value(self) -> None:
		"""default_value tip uyumlu olmalı."""
		if not self.default_value:
			return
		val = str(self.default_value).strip()
		if self.feature_type == "Capability":
			if val.lower() not in ("true", "false", "1", "0"):
				frappe.throw(_("Capability default_value 'true' veya 'false' olmalı. Şu an: {0}").format(val))
		elif self.feature_type == "Quota":
			try:
				int(val)
			except ValueError:
				frappe.throw(_("Quota default_value tam sayı olmalı. Şu an: {0}").format(val))
