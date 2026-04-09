"""
Site geneli tema ayarları için whitelisted API.

- get_public_theme: Guest erişimli, cache'li. Storefront boot'unda çağrılır.
- save_theme_settings: Sadece System Manager / Marketplace Admin.
"""

import json

import frappe
from frappe import _

from tradehub_core.tradehub_core.doctype.tradehub_theme_settings.tradehub_theme_settings import (
    ALLOWED_THEME_KEYS,
)


PUBLIC_THEME_CACHE_KEY = "tradehub_public_theme"
SETTINGS_DOCTYPE = "Tradehub Theme Settings"


@frappe.whitelist(allow_guest=True)
def get_public_theme():
    """Storefront'un her sayfa yüklemesinde çağırdığı public endpoint.

    Cache'ten döner; `on_update` hook'u cache'i invalide eder. Sadece
    varsayılandan farklı override'lar ve son güncelleme zamanı döner.
    Hassas veri (email vs.) döndürmez.
    """
    cached = frappe.cache().get_value(PUBLIC_THEME_CACHE_KEY)
    if cached is not None:
        return cached

    try:
        doc = frappe.get_single(SETTINGS_DOCTYPE)
        overrides = json.loads(doc.overrides or "{}")
        if not isinstance(overrides, dict):
            overrides = {}
        last_updated_at = str(doc.last_updated_at or "")
    except frappe.DoesNotExistError:
        overrides = {}
        last_updated_at = ""

    payload = {
        "overrides": overrides,
        "last_updated_at": last_updated_at,
    }
    frappe.cache().set_value(PUBLIC_THEME_CACHE_KEY, payload)
    return payload


@frappe.whitelist()
def get_theme_settings():
    """Admin panel okuma endpoint'i. System Manager / Marketplace Admin gerekir."""
    _require_admin()
    doc = frappe.get_single(SETTINGS_DOCTYPE)
    try:
        overrides = json.loads(doc.overrides or "{}")
        if not isinstance(overrides, dict):
            overrides = {}
    except (TypeError, ValueError):
        overrides = {}

    return {
        "overrides": overrides,
        "last_updated_by": doc.last_updated_by or "",
        "last_updated_at": str(doc.last_updated_at or ""),
        "allowed_keys": sorted(ALLOWED_THEME_KEYS),
    }


@frappe.whitelist()
def save_theme_settings(overrides):
    """Admin panel yazma endpoint'i. Sadece yetkili admin rollerine açık."""
    _require_admin()

    if isinstance(overrides, str):
        try:
            parsed = json.loads(overrides)
        except (TypeError, ValueError):
            frappe.throw(_("Overrides geçerli bir JSON nesnesi olmalıdır."))
            return
    elif isinstance(overrides, dict):
        parsed = overrides
    else:
        frappe.throw(_("Overrides bir nesne (object) olmalıdır."))
        return

    if not isinstance(parsed, dict):
        frappe.throw(_("Overrides bir JSON nesnesi olmalıdır."))
        return

    doc = frappe.get_single(SETTINGS_DOCTYPE)
    doc.overrides = json.dumps(parsed)
    # validate() tüm value doğrulamasını yapar, on_update() cache invalide eder
    doc.save(ignore_permissions=False)

    return {"ok": True, "count": len(parsed)}


def _require_admin() -> None:
    """System Manager veya Marketplace Admin gerektirir."""
    roles = set(frappe.get_roles(frappe.session.user))
    if "System Manager" in roles or "Marketplace Admin" in roles:
        return
    frappe.throw(
        _("Bu işlem için yetkiniz yok. Yönetici rolü gereklidir."),
        frappe.PermissionError,
    )
