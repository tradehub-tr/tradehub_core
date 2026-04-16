"""
Platform Notification yardımcı fonksiyonları.

Kullanım:
    from tradehub_core.utils.notify import notify

    notify(
        recipient_user="ali@example.com",
        recipient_role="seller",
        type="order",
        title="Yeni Sipariş",
        message="#ORD-001 siparişi alındı.",
        action_url="/dashboard/orders/ORD-001",
        reference_doctype="Order",
        reference_name="ORD-001",
    )
"""

import frappe


def notify(
	recipient_user: str,
	type: str,
	title: str,
	message: str,
	recipient_role: str = "",
	action_url: str = "",
	reference_doctype: str = "",
	reference_name: str = "",
	channel: str = "in_app",
) -> str:
	"""Platform Notification kaydı oluştur ve kaydet.

	Returns:
	    Oluşturulan bildirimin `name` değeri.
	"""
	if not recipient_user:
		return ""

	doc = frappe.get_doc(
		{
			"doctype": "Platform Notification",
			"recipient_user": recipient_user,
			"recipient_role": recipient_role,
			"type": type,
			"title": title,
			"message": message,
			"action_url": action_url,
			"reference_doctype": reference_doctype,
			"reference_name": reference_name,
			"channel": channel,
			"is_read": 0,
		}
	)
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
