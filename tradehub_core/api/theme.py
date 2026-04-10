"""
Site geneli tema ayarları için whitelisted API.

- get_public_theme: Guest erişimli, cache'li. Storefront boot'unda çağrılır.
- save_theme_settings: Sadece System Manager / Marketplace Admin.
- get_theme_settings: Admin panel okuma endpoint'i.

Güvenlik katmanları (defense in depth):
  1. _require_admin() — System Manager / Marketplace Admin rolü
  2. ALLOWED_THEME_KEYS — whitelist enforcement (DocType.validate())
  3. _FORBIDDEN_VALUE_PATTERNS — CSS injection karakterleri
  4. _COLOR_VALUE_RE / _NUMERIC_VALUE_RE / _TEXT_VALUE_RE — format doğrulama
  5. _enforce_save_rate_limit() — kullanıcı başına dakikada 10 save
"""

import json

import frappe
from frappe import _

from tradehub_core.tradehub_core.doctype.tradehub_theme_settings.tradehub_theme_settings import (
    ALLOWED_THEME_KEYS,
)


PUBLIC_THEME_CACHE_KEY = "tradehub_public_theme"
SETTINGS_DOCTYPE = "Tradehub Theme Settings"

# Rate limit: kullanıcı başına 60 saniyelik pencerede max 10 save
_SAVE_RATE_LIMIT_COUNT = 10
_SAVE_RATE_LIMIT_WINDOW_SECONDS = 60
_SAVE_RATE_LIMIT_CACHE_PREFIX = "tradehub_theme_save_rl:"


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
    """Admin panel yazma endpoint'i. Sadece yetkili admin rollerine açık.

    Güvenlik:
      - Rol kontrolü (_require_admin)
      - Rate limit (_enforce_save_rate_limit)
      - Whitelist + format validation (DocType.validate)
    """
    _require_admin()
    _enforce_save_rate_limit()

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


def _enforce_save_rate_limit() -> None:
    """Kullanıcı başına rate limit: 60s pencerede max 10 save.

    Frappe cache'inde sliding counter. Sınırı aşan istek 429 benzeri
    PermissionError ile reddedilir (brute-force / accidental save storm
    koruması).
    """
    user = frappe.session.user or "Guest"
    cache_key = f"{_SAVE_RATE_LIMIT_CACHE_PREFIX}{user}"
    cache = frappe.cache()
    current = cache.get_value(cache_key) or 0
    try:
        current = int(current)
    except (TypeError, ValueError):
        current = 0

    if current >= _SAVE_RATE_LIMIT_COUNT:
        frappe.throw(
            _(
                "Çok fazla tema kaydı denemesi. Lütfen {0} saniye bekleyin."
            ).format(_SAVE_RATE_LIMIT_WINDOW_SECONDS),
            frappe.PermissionError,
        )

    # Sayaç 0'dan 1'e geçerken TTL set et — sonraki artırmalar TTL'i etkilemesin
    cache.set_value(
        cache_key,
        current + 1,
        expires_in_sec=_SAVE_RATE_LIMIT_WINDOW_SECONDS,
    )
