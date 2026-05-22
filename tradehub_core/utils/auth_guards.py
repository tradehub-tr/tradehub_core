"""Auth guard decorators for tradehub_core endpoints.

``require_verified_email`` — yalnızca e-posta adresi doğrulanmış (Buyer Profile.
``email_verified`` = 1) kullanıcıların korunan endpoint'i çağırmasına izin verir.
Guest kullanıcılar zaten ``@frappe.whitelist()`` (allow_guest=False) tarafından
yakalanır; bu decorator ek bir doğrulama katmanıdır.

Kullanım:

    from tradehub_core.utils.auth_guards import require_verified_email

    @frappe.whitelist()
    @require_verified_email
    def create_order(...):
        ...

Hata yanıtı (HTTP 403):

    {"error": "EMAIL_NOT_VERIFIED", "message": "..."}
"""

from __future__ import annotations

from functools import wraps

import frappe
from frappe import _


def is_email_verified(user: str) -> bool:
	"""Return True iff User Profile.email_verified is set for ``user``.

	Sprint 2 (revised, 2026-05-15): Buyer Profile → User Profile.
	User Profile yoksa ``True`` döner — admin gibi profilsiz hesapları engellememek için.
	"""
	if not user or user == "Guest":
		return False
	if not frappe.db.exists("User Profile", {"user": user}):
		return True
	return bool(frappe.db.get_value("User Profile", {"user": user}, "email_verified"))


def require_verified_email(fn):
	"""Decorator: çağıran kullanıcı doğrulanmamışsa 403 ile reddet."""

	@wraps(fn)
	def wrapper(*args, **kwargs):
		user = frappe.session.user
		if user == "Guest":
			# Frappe whitelist baseline'ı zaten 401/403 atar; defansif fallback.
			frappe.local.response["http_status_code"] = 401
			frappe.throw(_("Not logged in."), frappe.AuthenticationError)

		if not is_email_verified(user):
			frappe.local.response["http_status_code"] = 403
			frappe.local.response["error_code"] = "EMAIL_NOT_VERIFIED"
			frappe.throw(
				_("Please verify your email address before performing this action."),
				frappe.PermissionError,
			)

		return fn(*args, **kwargs)

	return wrapper
