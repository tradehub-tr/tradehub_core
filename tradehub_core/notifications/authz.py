"""Bildirim şablon yönetimi yetkisi — sunucunun tek karar noktası.

Rol tablosu onaylanmış ürün kararı DEĞİLDİR (tasarım T51; BACKEND-PLANI §2 geçici davranış):
  super-admin       : Administrator, System Manager, Marketplace Admin
  icerik-yoneticisi : "Notification Content Manager" Frappe rolü (taslak/çeviri/test/onay isteği)
  salt-okunur       : "Notification Viewer" Frappe rolü (yalnız okuma)
Yayın, kanal kuralı ve sürüme dönüş yalnız super-admin. Roller seed edilir, kimseye atanmaz.
"""

from __future__ import annotations

import frappe
from frappe import _

ADMIN_ROLES = {"System Manager", "Marketplace Admin"}
CONTENT_MANAGER_ROLE = "Notification Content Manager"
VIEWER_ROLE = "Notification Viewer"

CAPABILITIES = {
	"super-admin": ["goruntule", "duzenle", "yayinla", "kanal", "test"],
	"icerik-yoneticisi": ["goruntule", "duzenle", "test"],
	"salt-okunur": ["goruntule"],
}


def template_role(user: str | None = None) -> str | None:
	user = user or frappe.session.user
	if not user or user == "Guest":
		return None
	if user == "Administrator":
		return "super-admin"
	roles = set(frappe.get_roles(user))
	if roles & ADMIN_ROLES:
		return "super-admin"
	if CONTENT_MANAGER_ROLE in roles:
		return "icerik-yoneticisi"
	if VIEWER_ROLE in roles:
		return "salt-okunur"
	return None


def require(capability: str) -> str:
	"""Yetki yoksa 401/403 fırlatır; varsa rolü döner."""
	if frappe.session.user == "Guest":
		frappe.throw(_("Oturum açmanız gerekiyor."), frappe.AuthenticationError)
	role = template_role()
	if not role or capability not in CAPABILITIES[role]:
		frappe.throw(_("Bu işlem için yetkiniz yok."), frappe.PermissionError)
	return role


def capabilities(role: str | None) -> list[str]:
	return list(CAPABILITIES.get(role or "", []))
