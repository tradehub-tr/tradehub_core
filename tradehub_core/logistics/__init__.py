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

# Modülün ana kapısı. `Logistics Settings.logistics_enabled` alanı — feature_flags
# JSON'unun İÇİNDE değil, ayrı bir Check alanı.
MASTER_FLAG = "logistics_enabled"


def _is_master_enabled() -> bool:
	"""Lojistik modülünün ana anahtarı açık mı?

	Sıra `is_enabled` ile aynı: DocType alanı → site_config → varsayılan (kapalı).
	"""
	try:
		settings_doc = frappe.get_cached_doc("Logistics Settings")
		value = settings_doc.get(MASTER_FLAG)
		if value is not None:
			return bool(value)
	except frappe.DoesNotExistError:
		pass

	site_val = frappe.conf.get(f"tradehub_{MASTER_FLAG}")
	if site_val is not None:
		return bool(site_val)

	return False


def is_enabled(flag: str) -> bool:
	"""Lojistik feature flag kontrolü.

	Kontrol sırası:
		0. Ana bayrak (`logistics_enabled`) — kapalıysa diğer TÜM bayraklar kapalı
		1. Logistics Settings DocType'ındaki feature_flags JSON alanı
		2. site_config'deki tradehub_logistics_{flag} key'i
		3. LOGISTICS_FEATURE_FLAGS default dict'i

	Ana bayrak neden ayrı: kademeli açılışta (Beta → RC → PROD) tek anahtarla
	tüm lojistik yüzeyini kapatabilmek gerekiyor. Alt bayraklar tek tek açık
	bırakılsa bile ana bayrak kapalıyken hiçbiri devreye girmez.

	DİKKAT — katalog yönetimi bu kapıya BAĞLI DEĞİL: yönetici, modül müşteriye
	açılmadan ÖNCE katalogları yapılandırabilmeli. Katalog endpoint'leri rol ve
	capability ile korunur, feature flag ile değil.

	Args:
		flag: Kontrol edilecek feature flag adı.

	Returns:
		Feature flag'in aktif olup olmadığı.

	Raises:
		frappe.ValidationError: Flag adı boş ise.
	"""
	if not flag:
		frappe.throw(_("Feature flag adı boş olamaz."))

	if flag == MASTER_FLAG:
		return _is_master_enabled()

	# 0. Ana bayrak kapalıysa alt bayrakların değeri okunmaz
	if not _is_master_enabled():
		return False

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


def get_logistics_settings() -> frappe.Document:
	"""Logistics Settings singleton DocType'ını döndürür.

	Returns:
		Logistics Settings dokümanı (cached).

	Raises:
		frappe.DoesNotExistError: DocType henüz oluşturulmamışsa.
	"""
	return frappe.get_cached_doc("Logistics Settings")


__all__ = [
	"MASTER_FLAG",
	"get_logistics_settings",
	"is_enabled",
]
