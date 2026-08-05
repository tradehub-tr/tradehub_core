# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü public API.

Kullanım:
	from tradehub_core.logistics import is_enabled
	if not is_enabled("carrier_api_enabled"):
		frappe.throw(_("Kargo API entegrasyonu aktif değil."))

	from tradehub_core.logistics import get_logistics_settings
	settings = get_logistics_settings()
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from tradehub_core.logistics.constants import LOGISTICS_FEATURE_FLAGS


def is_enabled(flag: str) -> bool:
	"""Lojistik feature flag kontrolü.

	Kontrol sırası:
		1. Logistics Settings DocType'ındaki feature_flags JSON alanı
		2. site_config'deki tradehub_logistics_{flag} key'i
		3. LOGISTICS_FEATURE_FLAGS default dict'i

	Args:
		flag: Kontrol edilecek feature flag adı.

	Returns:
		Feature flag'in aktif olup olmadığı.

	Raises:
		frappe.ValidationError: Flag adı boş ise.
	"""
	if not flag:
		frappe.throw(_("Feature flag adı boş olamaz."))

	# 1. Logistics Settings DocType feature_flags JSON
	try:
		settings_doc = frappe.get_cached_doc("Logistics Settings")
		feature_flags: dict[str, Any] = frappe.parse_json(
			settings_doc.get("feature_flags") or "{}"
		)
		if flag in feature_flags:
			return bool(feature_flags[flag])
	except frappe.DoesNotExistError:
		pass

	# 2. site_config key
	site_config_key = f"tradehub_logistics_{flag}"
	site_val = frappe.conf.get(site_config_key)
	if site_val is not None:
		return bool(site_val)

	# 3. Default
	return LOGISTICS_FEATURE_FLAGS.get(flag, False)


def get_logistics_settings() -> "frappe.Document":
	"""Logistics Settings singleton DocType'ını döndürür.

	Returns:
		Logistics Settings dokümanı (cached).

	Raises:
		frappe.DoesNotExistError: DocType henüz oluşturulmamışsa.
	"""
	return frappe.get_cached_doc("Logistics Settings")


__all__ = [
	"get_logistics_settings",
	"is_enabled",
]
