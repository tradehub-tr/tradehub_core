# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""User lifecycle utilities — atomic deactivation + session purge.

K8 fix: User pasifleştirildiğinde mevcut session/cache/token'lar tam temizlenir.
Eski davranış sadece `frappe.db.delete("Sessions", ...)` yapıyordu — ama:
  - Tarayıcıda cached session cookie hala valid (30 dk TTL)
  - Frappe user-level cache (roles, permissions, has_permission) stale
  - API token'lar (varsa) invalidate edilmemiş

Bu modül tek noktada tüm temizliği yapar. Çağıranlar:
  - tradehub_core/services/subscription_downgrade.py (_deactivate_user)
  - tradehub_core/api/v1/seller_users.py (deactivate_sub_user)
  - Owner Transfer akışı (gelecek)
"""

from __future__ import annotations

import frappe


def purge_user_sessions_and_caches(user: str) -> dict:
	"""User'ın tüm aktif oturumlarını ve cache'lerini temizler.

	Idempotent — birden çok kez güvenle çağrılabilir.

	Yapılanlar:
	  1. Sessions tablosundan tüm satırları sil (tarayıcı cookie geçersiz olur,
	     next request 417/401 alır → login redirect)
	  2. frappe.clear_cache(user=...) — Frappe'nin user-level cache'i
	     (get_roles, get_permissions, etc.) sıfırla
	  3. API anahtarlarını revoke (User.api_key sıfırla — varsa)
	  4. Entitlement cache'i de invalidate (user tenant'ı varsa)

	Args:
	    user: User email/name

	Returns:
	    {sessions_deleted, cache_cleared, api_key_revoked, entitlement_cache_cleared}
	"""
	result = {
		"sessions_deleted": False,
		"cache_cleared": False,
		"api_key_revoked": False,
		"entitlement_cache_cleared": False,
	}

	# 1. Sessions tablosu — açık tarayıcı oturumlarını öldür
	try:
		frappe.db.delete("Sessions", {"user": user})
		result["sessions_deleted"] = True
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"purge sessions fail ({user}): {exc}", "user_lifecycle")

	# 2. Frappe user-level cache (get_roles, get_permissions ...)
	try:
		frappe.clear_cache(user=user)
		result["cache_cleared"] = True
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"clear_cache fail ({user}): {exc}", "user_lifecycle")

	# 3. API anahtarını revoke et (Frappe User.api_key + api_secret)
	# Not: user_doc zaten enabled=0 olarak save edildi; api_key sıfırlama
	# ileride yeniden aktive olursa restart gerekecek bilgisi şeklinde.
	try:
		# frappe.db.set_value tetiklemez doc_event → güvenli
		if frappe.db.has_column("tabUser", "api_key"):
			frappe.db.set_value("User", user, {"api_key": "", "api_secret": ""})
			result["api_key_revoked"] = True
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"api_key revoke fail ({user}): {exc}", "user_lifecycle")

	# 4. Entitlement cache'i (user'ın tenant'ı varsa) invalidate
	try:
		tenant = frappe.db.get_value("User", user, "tradehub_tenant")
		if tenant:
			from tradehub_core.entitlement.core import invalidate_store_cache

			invalidate_store_cache(tenant)
			result["entitlement_cache_cleared"] = True
	except Exception as exc:  # noqa: BLE001
		frappe.log_error(f"entitlement cache clear fail ({user}): {exc}", "user_lifecycle")

	return result
