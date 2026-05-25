"""Consent management helpers — Faz 3.5."""

import frappe
from frappe.utils import now_datetime


def record_consent(
    user: str,
    consent_type: str,
    action: str,
    *,
    version: str | None = None,
    source: str = "settings",
    legal_basis: str | None = None,
    expires_at=None,
    metadata: dict | None = None,
) -> str:
    """Record a consent event. Returns the new log name."""
    doc = frappe.get_doc({
        "doctype": "User Consent Log",
        "user": user,
        "consent_type": consent_type,
        "action": action,
        "version": version or _get_active_version(consent_type),
        "source": source,
        "legal_basis": legal_basis,
        "expires_at": expires_at,
        "metadata": frappe.as_json(metadata) if metadata else None,
    })
    doc.insert(ignore_permissions=True)
    return doc.name


def check_consent(user: str, consent_type: str) -> dict:
    """Check if user has active consent for given type.

    Returns: {has_consent: bool, version: str|None, granted_at: str|None}
    """
    last = frappe.get_all(
        "User Consent Log",
        filters={"user": user, "consent_type": consent_type},
        fields=["action", "version", "creation", "expires_at"],
        order_by="creation desc",
        limit=1,
    )

    if not last:
        return {"has_consent": False, "version": None, "granted_at": None}

    entry = last[0]

    if entry.action == "withdrawn":
        return {"has_consent": False, "version": entry.version, "granted_at": None}

    if entry.expires_at and entry.expires_at < now_datetime():
        return {"has_consent": False, "version": entry.version, "granted_at": None}

    return {
        "has_consent": True,
        "version": entry.version,
        "granted_at": str(entry.creation),
    }


def get_user_consents(user: str) -> list[dict]:
    """Get all active consent statuses for a user."""
    consent_types = [
        "privacy_policy", "terms_of_service", "marketing_email",
        "marketing_sms", "cookie_analytics", "cookie_marketing",
        "cookie_functional", "kvkk_disclosure", "data_processing",
    ]
    result = []
    for ct in consent_types:
        status = check_consent(user, ct)
        status["consent_type"] = ct
        result.append(status)
    return result


def withdraw_consent(user: str, consent_type: str) -> str:
    """Record consent withdrawal."""
    return record_consent(
        user, consent_type, "withdrawn", source="settings",
    )


def _get_active_version(consent_type: str) -> str | None:
    """Get active policy version for a consent type, if one exists."""
    type_map = {
        "privacy_policy": "privacy_policy",
        "terms_of_service": "terms_of_service",
        "kvkk_disclosure": "kvkk_disclosure",
    }
    policy_type = type_map.get(consent_type)
    if not policy_type:
        return None

    versions = frappe.get_all(
        "Consent Policy Version",
        filters={"policy_type": policy_type, "status": "Active"},
        fields=["version"],
        order_by="effective_date desc",
        limit=1,
    )
    return versions[0].version if versions else None
