"""
Legacy auth endpoints — DEPRECATED.

All functionality has been moved to tradehub_core.api.v1.auth and
tradehub_core.api.v1.identity. These endpoints are disabled for security.

- register() → use v1/identity.register_user (OTP + rate limit + password policy)
- check_email() → use v1/auth.check_email_exists (rate limited)
- update_password() → use v1/identity.change_password (password policy enforced)
- get_current_user() → use v1/auth.get_session_user
"""

import frappe
from frappe import _


@frappe.whitelist(allow_guest=True)
def get_current_user():
	"""Return current session user info — kept for backward compatibility."""
	user_email = frappe.session.user
	if user_email == "Guest":
		return {"is_guest": True}

	user = frappe.get_doc("User", user_email)

	seller = frappe.db.get_value(
		"Seller Profile",
		{"user": user_email},
		["name", "seller_name", "seller_code", "status", "logo",
		 "health_score", "score_grade"],
		as_dict=True,
	)

	return {
		"is_guest": False,
		"email": user.email,
		"full_name": user.full_name,
		"is_seller": bool(seller),
		"seller": seller or None,
	}


# ── DISABLED ENDPOINTS ───────────────────────────────────────────────────────
# These functions are intentionally removed to prevent security bypass.
# register() — no OTP, no rate limit, no password policy
# check_email() — no rate limit, email enumeration risk
# update_password() — no password policy enforcement
