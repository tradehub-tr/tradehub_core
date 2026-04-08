import frappe
from frappe import _


def _get_current_user_email() -> str:
    """Oturumdaki kullanıcının e-postasını döndür."""
    return frappe.session.user


@frappe.whitelist()
def get_notifications(page=1, page_size=20, unread_only=False):
    """Oturumdaki kullanıcının bildirimlerini döndür.

    Returns:
        {
            "data": [...],
            "total": int,
            "unread_count": int,
            "page": int,
            "page_size": int,
            "has_next": bool
        }
    """
    user = _get_current_user_email()
    page = int(page)
    page_size = min(int(page_size), 100)
    start = (page - 1) * page_size

    filters = {"recipient_user": user}
    if unread_only:
        filters["is_read"] = 0

    total = frappe.db.count("Platform Notification", filters=filters)
    unread_count = frappe.db.count(
        "Platform Notification", filters={"recipient_user": user, "is_read": 0}
    )

    records = frappe.get_all(
        "Platform Notification",
        filters=filters,
        fields=[
            "name", "title", "message", "type", "action_url",
            "is_read", "read_at", "channel",
            "reference_doctype", "reference_name",
            "creation",
        ],
        order_by="creation desc",
        start=start,
        page_length=page_size,
    )

    return {
        "data": records,
        "total": total,
        "unread_count": unread_count,
        "page": page,
        "page_size": page_size,
        "has_next": (start + page_size) < total,
    }


@frappe.whitelist()
def get_unread_count():
    """Okundmamış bildirim sayısını döndür (header rozeti için)."""
    user = _get_current_user_email()
    count = frappe.db.count(
        "Platform Notification",
        filters={"recipient_user": user, "is_read": 0},
    )
    return {"count": count}


@frappe.whitelist()
def mark_read(notification_name):
    """Tek bir bildirimi okundu olarak işaretle."""
    if not notification_name:
        frappe.throw(_("Bildirim adı gerekli"))

    user = _get_current_user_email()

    # Sahiplik kontrolü
    owner = frappe.db.get_value(
        "Platform Notification", notification_name, "recipient_user"
    )
    if owner != user and "System Manager" not in frappe.get_roles():
        frappe.throw(_("Bu bildirimi okuma yetkiniz yok"), frappe.PermissionError)

    frappe.db.set_value(
        "Platform Notification",
        notification_name,
        {
            "is_read": 1,
            "read_at": frappe.utils.now(),
        },
        update_modified=False,
    )
    frappe.db.commit()
    return {"success": True}


@frappe.whitelist()
def mark_all_read():
    """Oturumdaki kullanıcının tüm bildirimlerini okundu yap."""
    user = _get_current_user_email()
    now = frappe.utils.now()

    frappe.db.sql(
        """
        UPDATE `tabPlatform Notification`
        SET is_read = 1, read_at = %s
        WHERE recipient_user = %s AND is_read = 0
        """,
        (now, user),
    )
    frappe.db.commit()
    return {"success": True}
