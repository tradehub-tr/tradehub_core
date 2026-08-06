# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü permission fonksiyonları.

Platform yöneticileri tam erişime sahipken, seller ve buyer kullanıcıları
yalnızca kendi sevkiyatlarına erişebilir (tenant izolasyonu).

Bu fonksiyonlar hooks.py içinde permission_query_conditions ve
has_permission olarak kayıt edilir.
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _


def shipment_query_conditions(user: Optional[str] = None) -> str:
	"""Shipment listesi için SQL koşulu döndürür.

	Platform rolleri (System Manager, Logistics Manager) tam erişim alır.
	Seller rolü yalnızca kendi mağazasına ait sevkiyatları görür.
	Buyer rolü yalnızca kendi siparişlerine ait sevkiyatları görür.

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	# TODO: Implementasyon — platform full access + tenant isolation
	return ""


def shipment_has_permission(
	doc: "frappe.Document",
	ptype: str,
	user: Optional[str] = None,
) -> bool:
	"""Tek bir Shipment dokümanı için yetki kontrolü.

	Args:
		doc: Shipment dokümanı.
		ptype: İzin tipi (read, write, create, delete, submit, cancel).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	# TODO: Implementasyon — platform full access + tenant isolation
	return True


def carrier_credential_query_conditions(user: Optional[str] = None) -> str:
	"""Carrier Credential listesi için SQL koşulu döndürür.

	Kargo firması kimlik bilgileri yalnızca platform yöneticileri ve
	ilgili seller tarafından görülebilir.

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	# TODO: Implementasyon — platform full access + seller isolation
	return ""


def carrier_credential_has_permission(
	doc: "frappe.Document",
	ptype: str,
	user: Optional[str] = None,
) -> bool:
	"""Tek bir Carrier Credential dokümanı için yetki kontrolü.

	Args:
		doc: Carrier Credential dokümanı.
		ptype: İzin tipi (read, write, create, delete).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	# TODO: Implementasyon — platform full access + seller isolation
	return True


# -------------------------------------------------------------------------
# Logistics Settings — Singleton permission fonksiyonlari (TUR-102)
# -------------------------------------------------------------------------


def logistics_settings_query_conditions(user: str | None = None) -> str:
	"""Logistics Settings icin permission query condition.

	Singleton DocType oldugu icin liste sorgusunda ek filtre gerekmez.
	System Manager ve Marketplace Admin erisebilir (DocType permissions
	tarafindan kontrol edilir).

	Args:
		user: Kullanici e-posta adresi (None ise session user).

	Returns:
		SQL condition string'i (bos = kisitlama yok).
	"""
	if not user:
		user = frappe.session.user

	# System Manager ve Marketplace Admin her zaman erisebilir
	if "System Manager" in frappe.get_roles(user) or "Marketplace Admin" in frappe.get_roles(user):
		return ""

	# Diger roller icin erisim yok
	return "1=0"


def logistics_settings_has_permission(
	doc: Optional["frappe.Document"] = None,
	ptype: str = "read",
	user: str | None = None,
) -> bool:
	"""Logistics Settings icin per-doc permission kontrolu.

	Singleton DocType oldugu icin basit rol kontrolu yeterli.
	System Manager tam CRUD, Marketplace Admin read + write.

	Args:
		doc: Logistics Settings dokumani.
		ptype: Permission tipi (read, write, create, delete).
		user: Kullanici e-posta adresi (None ise session user).

	Returns:
		Erisim izni verilip verilmedigi.
	"""
	if not user:
		user = frappe.session.user

	roles = frappe.get_roles(user)

	# System Manager tam erisim
	if "System Manager" in roles:
		return True

	# Marketplace Admin read + write
	if "Marketplace Admin" in roles:
		if ptype in ("read", "write"):
			return True

	return False
