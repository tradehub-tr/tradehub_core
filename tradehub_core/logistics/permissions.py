# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü permission fonksiyonları.

Platform yöneticileri tam erişime sahipken, seller ve buyer kullanıcıları
yalnızca kendi sevkiyatlarına erişebilir (tenant izolasyonu).

Bu fonksiyonlar hooks.py içinde permission_query_conditions ve
has_permission olarak kayıt edilir. TUR-105'te Shipment/Carrier Credential
DocType'ları oluşturulunca hooks.py kaydı yapılacak.

Rol matrisi:
  - Platform full access: System Manager, Marketplace Admin, Logistics Manager,
    Support Agent, Platform Admin
  - Platform Finance: read-only (has_permission'da kontrol)
  - Seller-scoped: Logistics Operator / Seller rolleri (seller_profile match)
  - Buyer-scoped: kendi siparişine ait sevkiyatlar (buyer match)
"""

from __future__ import annotations

from typing import Optional

import frappe
from frappe import _

# ---------------------------------------------------------------------------
# Platform rol kümeleri — permissions.py ana modülündeki ile tutarlı
# ---------------------------------------------------------------------------
_PLATFORM_FULL_ACCESS_ROLES: frozenset[str] = frozenset({
	"System Manager",
	"Marketplace Admin",
	"Logistics Manager",
	"Support Agent",
	"Platform Admin",
})

_SHIPMENT_WRITE_ROLES: frozenset[str] = frozenset({
	"System Manager",
	"Marketplace Admin",
	"Logistics Manager",
	"Platform Admin",
})

_SHIPMENT_CANCEL_ROLES: frozenset[str] = frozenset({
	"Logistics Manager",
})

_WRITE_PTYPES: frozenset[str] = frozenset({
	"write", "create", "delete", "submit", "cancel", "amend",
})


# ---------------------------------------------------------------------------
# Helper: seller_profile resolver (mevcut permissions.py pattern)
# ---------------------------------------------------------------------------
def _get_user_seller_profile(user: str) -> str | None:
	"""User'ın bağlı olduğu Admin Seller Profile name'ini döndürür.

	Kanonik tenant resolver'ı kullanır (User.tradehub_tenant).
	Test fallback'i: Admin Seller Profile.user ile arama.
	"""
	try:
		from tradehub_core.utils.tenant import _get_seller_profile_for_user

		return _get_seller_profile_for_user(user)
	except (ImportError, AttributeError):
		# Test fallback — production'da tenant_utils her zaman yüklü
		return frappe.db.get_value(
			"Admin Seller Profile", {"user": user}, "name"
		)


def _doc_field(doc: object, field: str) -> str | None:
	"""Doc veya dict'ten field değeri oku (defensive)."""
	if isinstance(doc, dict):
		return doc.get(field)
	return getattr(doc, field, None)


def _log_deny(
	user: str,
	action: str,
	doc: object | None = None,
	reason: str = "",
) -> None:
	"""Permission DENY kararını audit log'a yaz (best-effort)."""
	try:
		from tradehub_core.audit import log as audit

		audit.log_decision(
			actor=user,
			action=action,
			decision=audit.DECISION_DENY,
			layer=audit.LAYER_L2,
			object_doctype="Shipment" if "shipment" in action else "Carrier Credential",
			object_name=_doc_field(doc, "name") if doc else None,
			tenant=_doc_field(doc, "seller_profile") if doc else None,
			rule_id=f"logistics.{action}",
			context={"reason": reason} if reason else None,
		)
	except Exception:  # noqa: BLE001 — audit hatası business flow'u bozmaz
		frappe.log_error(
			f"Audit log yazılamadı: {action} deny for {user}",
			"logistics.permissions",
		)


# ---------------------------------------------------------------------------
# Shipment permission fonksiyonları
# ---------------------------------------------------------------------------


def shipment_query_conditions(user: Optional[str] = None) -> str:
	"""Shipment listesi için SQL koşulu döndürür.

	Platform rolleri (System Manager, Logistics Manager, Support Agent,
	Platform Admin, Marketplace Admin) tam erişim alır.
	Platform Finance read-only erişim alır (has_permission'da kontrol).
	Seller rolü yalnızca kendi mağazasına ait sevkiyatları görür.
	Buyer rolü yalnızca kendi siparişlerine ait sevkiyatları görür.

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))

	# Platform full access: tüm sevkiyatları görür
	if roles & _PLATFORM_FULL_ACCESS_ROLES:
		return ""

	# Platform Finance: read-only ama tüm sevkiyatları listeleyebilir
	if "Platform Finance" in roles:
		return ""

	# Seller-scoped: Logistics Operator veya Seller rolleri
	seller_profile = _get_user_seller_profile(user)
	if seller_profile:
		return (
			f"`tabShipment`.`seller_profile` = {frappe.db.escape(seller_profile)}"
		)

	# Buyer-scoped: kendi siparişlerine ait sevkiyatlar
	return f"`tabShipment`.`buyer` = {frappe.db.escape(user)}"


def shipment_has_permission(
	doc: object,
	ptype: Optional[str] = None,
	user: Optional[str] = None,
) -> bool:
	"""Tek bir Shipment dokümanı için yetki kontrolü.

	Rol + ptype matrisi:
	  - Administrator: tam erişim
	  - cancel: sadece Logistics Manager
	  - write + shipping_cost değişti: Logistics Manager veya Platform Finance
	  - read: tenant izolasyonu (seller_profile match veya buyer match)
	  - Support Agent: sadece read
	  - Buyer: sadece read, kendi siparişi
	  - Her DENY'da audit.log_decision() çağrılır

	Args:
		doc: Shipment dokümanı.
		ptype: İzin tipi (read, write, create, delete, submit, cancel).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		_log_deny(user or "Guest", "shipment.access", doc, "guest_denied")
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))

	# ptype='cancel' → sadece Logistics Manager
	if ptype == "cancel":
		if roles & _SHIPMENT_CANCEL_ROLES:
			return True
		_log_deny(user, "shipment.cancel", doc, "cancel_requires_logistics_manager")
		return False

	# Support Agent → sadece read
	if "Support Agent" in roles and not (roles & (_PLATFORM_FULL_ACCESS_ROLES - {"Support Agent"})):
		if ptype and ptype != "read":
			_log_deny(user, f"shipment.{ptype}", doc, "support_agent_read_only")
			return False
		# read izni için tenant kontrolüne gerek yok — tüm sevkiyatları okuyabilir
		return True

	# Platform Finance → read + shipping_cost write
	if "Platform Finance" in roles and not (roles & _SHIPMENT_WRITE_ROLES):
		if ptype and ptype in _WRITE_PTYPES:
			# shipping_cost değişikliği için özel izin: has_value_changed kontrolü
			# doc.get_doc_before_save() ile yapılır; burada sadece write ptype'ı
			# kabul edilir (Logistics Manager + Platform Finance)
			if ptype == "write":
				return True  # Controller tarafında field-level kontrol yapılacak
			_log_deny(user, f"shipment.{ptype}", doc, "platform_finance_limited_write")
			return False
		return True  # read izni

	# Platform full access rolleri — write dahil tam erişim
	if roles & _SHIPMENT_WRITE_ROLES:
		return True

	# doc yoksa (doctype-seviyesi kontrol) → tenant kontrolü yapılamaz
	if doc is None:
		return True

	# Seller-scoped: kendi mağazasının sevkiyatı
	seller_profile = _get_user_seller_profile(user)
	doc_seller = _doc_field(doc, "seller_profile")

	if seller_profile and doc_seller:
		if doc_seller == seller_profile:
			return True
		_log_deny(user, f"shipment.{ptype or 'read'}", doc, "seller_profile_mismatch")
		return False

	# Buyer-scoped: kendi siparişi → sadece read
	doc_buyer = _doc_field(doc, "buyer")
	if doc_buyer == user:
		if ptype and ptype != "read":
			_log_deny(user, f"shipment.{ptype}", doc, "buyer_read_only")
			return False
		return True

	_log_deny(user, f"shipment.{ptype or 'read'}", doc, "no_access")
	return False


# ---------------------------------------------------------------------------
# Carrier Credential permission fonksiyonları
# ---------------------------------------------------------------------------


def carrier_credential_query_conditions(user: Optional[str] = None) -> str:
	"""Carrier Credential listesi için SQL koşulu döndürür.

	Carrier Integration Manager tam erişim (kendi tenant).
	Logistics Manager read-only (kendi tenant).
	Diğer roller erişemez.

	Args:
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		SQL WHERE koşul string'i.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		return "1=0"

	if user == "Administrator":
		return ""

	roles = set(frappe.get_roles(user))

	# Platform admin rolleri: tam erişim
	if roles & {"System Manager", "Marketplace Admin", "Platform Admin"}:
		return ""

	# Carrier Integration Manager veya Logistics Manager: kendi tenant'ı
	if roles & {"Carrier Integration Manager", "Logistics Manager"}:
		seller_profile = _get_user_seller_profile(user)
		if seller_profile:
			return (
				f"`tabCarrier Credential`.`seller_profile`"
				f" = {frappe.db.escape(seller_profile)}"
			)

	# Diğer roller → erişim yok
	return "1=0"


def carrier_credential_has_permission(
	doc: object,
	ptype: Optional[str] = None,
	user: Optional[str] = None,
) -> bool:
	"""Tek bir Carrier Credential dokümanı için yetki kontrolü.

	Carrier Integration Manager → tam CRUD (kendi tenant).
	Logistics Manager → sadece read (kendi tenant).
	Platform admin rolleri → tam erişim.
	Diğer → False.

	Args:
		doc: Carrier Credential dokümanı.
		ptype: İzin tipi (read, write, create, delete).
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.

	Returns:
		Erişim izni varsa True.
	"""
	user = user or frappe.session.user
	if not user or user == "Guest":
		_log_deny(user or "Guest", "carrier_credential.access", doc, "guest_denied")
		return False

	if user == "Administrator":
		return True

	roles = set(frappe.get_roles(user))

	# Platform admin rolleri: tam erişim
	if roles & {"System Manager", "Marketplace Admin", "Platform Admin"}:
		return True

	# doc yoksa (doctype-seviyesi kontrol)
	if doc is None:
		if roles & {"Carrier Integration Manager", "Logistics Manager"}:
			return True
		_log_deny(user, "carrier_credential.access", doc, "no_role")
		return False

	# Tenant izolasyonu: seller_profile eşleşmesi
	seller_profile = _get_user_seller_profile(user)
	doc_seller = _doc_field(doc, "seller_profile")

	if not seller_profile or (doc_seller and doc_seller != seller_profile):
		_log_deny(
			user, f"carrier_credential.{ptype or 'read'}", doc,
			"seller_profile_mismatch",
		)
		return False

	# Carrier Integration Manager → tam CRUD
	if "Carrier Integration Manager" in roles:
		return True

	# Logistics Manager → sadece read
	if "Logistics Manager" in roles:
		if ptype and ptype != "read":
			_log_deny(
				user, f"carrier_credential.{ptype}", doc,
				"logistics_manager_read_only",
			)
			return False
		return True

	_log_deny(user, f"carrier_credential.{ptype or 'read'}", doc, "no_role")
	return False


# ---------------------------------------------------------------------------
# Cost field maskeleme guard'ları (BE-8)
# ---------------------------------------------------------------------------


def mask_shipment_cost_fields(doc: object, user: Optional[str] = None) -> None:
	"""view.logistics_cost capability yoksa maliyet alanlarını maskele.

	Shipment dokümanında shipping_cost, insurance_cost, total_cost gibi
	hassas maliyet alanlarını capability kontrolü ile maskeler.

	Args:
		doc: Shipment dokümanı.
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.
	"""
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return

	try:
		from tradehub_core.utils.permission_resolver import has_capability

		if has_capability(user, "view.logistics_cost"):
			return
	except (ImportError, AttributeError):
		# permission_resolver mevcut değilse maskeleme UYGULA (fail-closed — güvenli taraf)
		pass

	# Maliyet alanlarını maskele
	cost_fields = (
		"shipping_cost", "insurance_cost", "total_cost",
		"carrier_cost", "fuel_surcharge", "packaging_cost",
	)
	for field in cost_fields:
		if hasattr(doc, field) and getattr(doc, field, None) is not None:
			setattr(doc, field, 0)


def mask_carrier_credential_fields(doc: object, user: Optional[str] = None) -> None:
	"""view.carrier_secret capability yoksa api_key/api_secret maskele.

	Carrier Credential dokümanında hassas API anahtarlarını capability
	kontrolü ile maskeler.

	Args:
		doc: Carrier Credential dokümanı.
		user: Kullanıcı e-posta adresi. None ise mevcut oturum kullanıcısı.
	"""
	user = user or frappe.session.user
	if not user or user == "Administrator":
		return

	try:
		from tradehub_core.utils.permission_resolver import has_capability

		if has_capability(user, "view.carrier_secret"):
			return
	except (ImportError, AttributeError):
		# permission_resolver mevcut değilse maskeleme UYGULA (fail-closed — güvenli taraf)
		pass

	# Hassas alanları maskele
	secret_fields = ("api_key", "api_secret", "webhook_secret", "access_token")
	mask_value = "••••••••"
	for field in secret_fields:
		if hasattr(doc, field) and getattr(doc, field, None):
			setattr(doc, field, mask_value)


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
