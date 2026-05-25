"""
Tracking ayarları API.

- get_public_tracking: Guest erişimli, cache'li. Storefront boot'unda çağrılır.
- get_tracking_settings: Admin panel okuma endpoint'i.
- save_tracking_settings: Admin panel yazma endpoint'i.

Güvenlik katmanları:
  1. _require_admin() — System Manager / Marketplace Admin rolü
  2. DocType.validate() — ID format doğrulama
  3. _enforce_save_rate_limit() — kullanıcı başına dakikada 10 save
"""

import json

import frappe
from frappe import _

CACHE_KEY = "tradehub_tracking_config"
SETTINGS_DOCTYPE = "Tracking Settings"

_SAVE_RATE_LIMIT_COUNT = 10
_SAVE_RATE_LIMIT_WINDOW_SECONDS = 60
_SAVE_RATE_LIMIT_CACHE_PREFIX = "tradehub_tracking_save_rl:"

_TRACKER_FIELDS = [
	("gtm_id", "gtm_enabled"),
	("metrica_id", "metrica_enabled"),
	("fb_pixel_id", "fb_pixel_enabled"),
	("criteo_partner_id", "criteo_enabled"),
]

_ALL_FIELDS = [f for pair in _TRACKER_FIELDS for f in pair]


@frappe.whitelist(allow_guest=True)
def get_public_tracking() -> dict:
	"""Storefront'un her sayfa yüklemesinde çağırdığı public endpoint.

	Cache'ten döner; DocType on_update hook'u cache'i invalide eder.
	Sadece aktif + ID'si dolu tracker'ların ID'lerini döner, diğerleri None.
	"""
	cached = frappe.cache().get_value(CACHE_KEY)
	if cached is not None:
		return cached

	try:
		doc = frappe.get_single(SETTINGS_DOCTYPE)
	except frappe.DoesNotExistError:
		payload = {id_field: None for id_field, _ in _TRACKER_FIELDS}
		frappe.cache().set_value(CACHE_KEY, payload, expires_in_sec=3600)
		return payload

	payload = {}
	for id_field, enabled_field in _TRACKER_FIELDS:
		id_val = (getattr(doc, id_field, None) or "").strip()
		is_enabled = bool(getattr(doc, enabled_field, 0))
		payload[id_field] = id_val if (id_val and is_enabled) else None

	frappe.cache().set_value(CACHE_KEY, payload, expires_in_sec=3600)
	return payload


@frappe.whitelist()
def get_tracking_settings() -> dict:
	"""Admin panel okuma endpoint'i. System Manager / Marketplace Admin gerekir."""
	_require_admin()
	doc = frappe.get_single(SETTINGS_DOCTYPE)
	result = {}
	for field in _ALL_FIELDS:
		result[field] = getattr(doc, field, None)
	result["modified"] = str(doc.modified or "")
	result["modified_by"] = doc.modified_by or ""
	return result


@frappe.whitelist(methods=["POST"])
def save_tracking_settings(settings: str | dict) -> dict:
	"""Admin panel yazma endpoint'i.

	Güvenlik:
	  - Rol kontrolü (_require_admin)
	  - Rate limit (_enforce_save_rate_limit)
	  - Whitelist + format validation (DocType.validate)
	"""
	_require_admin()
	_enforce_save_rate_limit()

	if isinstance(settings, str):
		try:
			parsed = json.loads(settings)
		except (TypeError, ValueError):
			frappe.throw(_("Geçersiz JSON formatı."), frappe.ValidationError)
			return {}
	elif isinstance(settings, dict):
		parsed = settings
	else:
		frappe.throw(_("Ayarlar bir nesne (object) olmalıdır."), frappe.ValidationError)
		return {}

	doc = frappe.get_single(SETTINGS_DOCTYPE)
	for field in _ALL_FIELDS:
		if field in parsed:
			setattr(doc, field, parsed[field])

	doc.save(ignore_permissions=False)

	return {"ok": True}


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
	"""Kullanıcı başına rate limit: 60s pencerede max 10 save."""
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
			_("Çok fazla kayıt denemesi. Lütfen {0} saniye bekleyin.").format(
				_SAVE_RATE_LIMIT_WINDOW_SECONDS
			),
			frappe.PermissionError,
		)

	cache.set_value(
		cache_key,
		current + 1,
		expires_in_sec=_SAVE_RATE_LIMIT_WINDOW_SECONDS,
	)
