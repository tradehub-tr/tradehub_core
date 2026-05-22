# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Subscription Plan DocType controller.

Bir planın yetenek bayrakları (capability_flags) ve kotalarını (quota_limits)
JSON olarak tutar. Süper Admin yeni plan ekleyebilir veya mevcut planın
detaylarını panelden değiştirebilir.

Detay: docs/yetki/03-doctype-sablonlari.md §2, docs/yetki/01-karar-dosyasi.md §1
"""

import json
import re

import frappe
from frappe import _
from frappe.model.document import Document

_PLAN_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class SubscriptionPlan(Document):
	def validate(self) -> None:
		self._normalize_plan_code()
		self._validate_capability_flags()
		self._validate_quota_limits()
		self._validate_pricing()

	def _normalize_plan_code(self) -> None:
		"""plan_code lowercase, kebab-case veya snake_case."""
		if not self.plan_code:
			return
		code = self.plan_code.strip().lower()
		if not _PLAN_CODE_PATTERN.match(code):
			frappe.throw(
				_(
					"Plan Code lowercase başlamalı ve sadece harf/rakam/tire/alt-çizgi içermeli "
					"(örn. 'free', 'starter', 'pro-annual')."
				)
			)
		self.plan_code = code

	def _validate_capability_flags(self) -> None:
		"""capability_flags geçerli JSON olmalı, key'ler Feature Catalog'ta tanımlı olmalı."""
		flags = self._parse_json_field("capability_flags")
		if not flags:
			return
		if not isinstance(flags, dict):
			frappe.throw(_("Capability Flags JSON nesnesi (dict) olmalı."))

		# Her key Feature Catalog'ta tanımlı olmalı
		unknown_keys = []
		for key, value in flags.items():
			if not key.startswith("feature."):
				frappe.throw(
					_("Capability flag key 'feature.' ile başlamalı: '{0}'").format(key)
				)
			if not isinstance(value, bool):
				frappe.throw(
					_("Capability flag '{0}' değeri boolean olmalı (true/false), şu an: {1}").format(
						key, type(value).__name__
					)
				)
			# Feature Catalog kontrolü (graceful — registry eksikse skip)
			if not frappe.db.exists("Feature Catalog", key):
				unknown_keys.append(key)

		if unknown_keys:
			# Uyarı: Feature Catalog'ta tanımlı değil. Hata fırlatmıyoruz çünkü
			# Süper Admin dynamic key ekleyebilir; sadece log yazıyoruz.
			frappe.log_error(
				f"Subscription Plan '{self.name}': Tanımsız capability key'ler: {unknown_keys}",
				"Subscription Plan Validation",
			)

	def _validate_quota_limits(self) -> None:
		"""quota_limits geçerli JSON, key'ler 'quota.', değerler integer olmalı."""
		quotas = self._parse_json_field("quota_limits")
		if not quotas:
			return
		if not isinstance(quotas, dict):
			frappe.throw(_("Quota Limits JSON nesnesi (dict) olmalı."))

		for key, value in quotas.items():
			if not key.startswith("quota."):
				frappe.throw(_("Quota key 'quota.' ile başlamalı: '{0}'").format(key))
			if not isinstance(value, int) or isinstance(value, bool):
				# bool subclass of int, exclude
				frappe.throw(
					_("Quota '{0}' değeri tam sayı olmalı, şu an: {1}").format(key, type(value).__name__)
				)
			if value < -1:
				# -1 = sınırsız, 0 = devre dışı, pozitif = limit
				frappe.throw(_("Quota '{0}' değeri -1 (sınırsız) veya >= 0 olmalı.").format(key))

	def _validate_pricing(self) -> None:
		"""Fiyat negatif olmamalı."""
		if (self.monthly_price or 0) < 0:
			frappe.throw(_("Monthly Price negatif olamaz."))
		if (self.yearly_price or 0) < 0:
			frappe.throw(_("Yearly Price negatif olamaz."))
		if (self.trial_days or 0) < 0:
			frappe.throw(_("Trial Days negatif olamaz."))

	def _parse_json_field(self, fieldname: str):
		"""JSON field'ını parse et — string ya da dict olabilir."""
		val = self.get(fieldname)
		if not val:
			return None
		if isinstance(val, (dict, list)):
			return val
		try:
			return json.loads(val)
		except (json.JSONDecodeError, TypeError) as e:
			frappe.throw(_("{0} geçerli JSON değil: {1}").format(fieldname, str(e)))

	def get_capability_flags(self) -> dict:
		"""Capability flags dict olarak döner."""
		return self._parse_json_field("capability_flags") or {}

	def get_quota_limits(self) -> dict:
		"""Quota limits dict olarak döner."""
		return self._parse_json_field("quota_limits") or {}

	def get_allowed_region_codes(self) -> list[str]:
		"""İzin verilen Region code listesi."""
		return [row.region for row in (self.allowed_regions or [])]

	def has_capability(self, feature_key: str) -> bool:
		"""Bu plan verilen capability'ye sahip mi?"""
		return bool(self.get_capability_flags().get(feature_key, False))

	def get_quota(self, quota_key: str, default: int = 0) -> int:
		"""Bu plan için verilen quota değeri (-1 = sınırsız)."""
		return int(self.get_quota_limits().get(quota_key, default))
