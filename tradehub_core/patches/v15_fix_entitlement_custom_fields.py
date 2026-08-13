# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""P2-1: Eksik User entitlement Custom Field kayıtlarını onarır (dev-ortam driftı).

v15_1_2_add_entitlement_custom_fields bazı ortamlarda kısmen uygulandı:
- User.tradehub_parent_organization: kolon DB'ye elle eklenmiş olabilir ama
  Custom Field kaydı yok. Kolon zaten varsa sorun değil — Custom Field kaydı
  oluşturulunca Frappe mevcut kolonu devralır (ALTER TABLE var olan kolonu atlar).
- User.tradehub_temporary_role_until: ne kolon ne kayıt var.

Orijinal alan tanımları (label / insert_after / description) birebir
v15_1_2_add_entitlement_custom_fields._CUSTOM_FIELDS'tan alındı.

Patch idempotent — Custom Field kaydı zaten varsa hiç dokunmaz.
"""

from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute() -> None:
	"""Eksik User entitlement Custom Field kayıtlarını idempotent oluştur."""
	fields: list[dict] = []

	if not frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "tradehub_parent_organization"}):
		fields.append(_parent_organization_field())

	if not frappe.db.exists("Custom Field", {"dt": "User", "fieldname": "tradehub_temporary_role_until"}):
		fields.append(_temporary_role_until_field())

	if not fields:
		return

	create_custom_fields({"User": fields}, update=True)


def _parent_organization_field() -> dict:
	"""tradehub_parent_organization tanımı.

	Organization DocType'ı mevcutsa Link (orijinal tanım); değilse Data olarak
	oluşturulur ve description'a CRM kurulunca Link'e çevrileceği notu düşülür
	(options'ı olmayan DocType'a Link açmak migrate'i kırar).
	"""
	field: dict = {
		"fieldname": "tradehub_parent_organization",
		"label": "Parent Organization (Buyer)",
		"insert_after": "tradehub_tenant",
		"description": "B2B alıcı sub-user için bağlı olunan organizasyon.",
	}
	if frappe.db.exists("DocType", "Organization"):
		field["fieldtype"] = "Link"
		field["options"] = "Organization"
	else:
		field["fieldtype"] = "Data"
		field["description"] += " (Organization DocType'ı henüz yok — CRM kurulunca Link'e çevrilir.)"
	return field


def _temporary_role_until_field() -> dict:
	"""tradehub_temporary_role_until tanımı (orijinalle birebir)."""
	return {
		"fieldname": "tradehub_temporary_role_until",
		"label": "Temporary Role Until",
		"fieldtype": "Datetime",
		"insert_after": "tradehub_is_owner",
		"description": "Bu tarihten sonra atanmış rol otomatik kalkar (Faz 3'te işler hale gelir).",
	}
