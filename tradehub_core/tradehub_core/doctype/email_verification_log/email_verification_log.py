"""Email Verification Log — append-only audit trail.

Each row records a single state change for a user's email verification flag,
plus the actor, IP, and (for admin overrides) the reason.

Retention: 12 months. After that a scheduler task should anonymise actor/IP
fields to comply with KVKK; deletion is intentionally not allowed via the UI.
"""

from frappe.model.document import Document


class EmailVerificationLog(Document):
	pass
