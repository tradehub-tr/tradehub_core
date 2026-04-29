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
        send_email=True,
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
	send_email: bool = False,
	email_subject: str = "",
	email_body: str = "",
) -> str:
	"""Platform Notification kaydı oluştur, opsiyonel olarak e-posta gönder.

	`send_email=True` verilirse Platform Notification kaydedildikten sonra
	`frappe.sendmail` queue'ya atılır (now=False). Hata durumunda kayıt
	kaybolmaz; sadece log'a düşer ve `email_sent` False kalır.

	Returns:
	    Oluşturulan bildirimin `name` değeri (hata durumunda "").
	"""
	if not recipient_user or recipient_user == "Guest":
		return ""

	effective_channel = "email" if send_email else channel

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Platform Notification",
				"recipient_user": recipient_user,
				"recipient_role": recipient_role,
				"type": type,
				"title": (title or "")[:200] or "(Bildirim)",
				"message": (message or "")[:1000],
				"action_url": action_url,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"channel": effective_channel,
				"is_read": 0,
			}
		)
		doc.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="notify: Platform Notification insert")
		return ""

	if send_email:
		recipient_email = _resolve_user_email(recipient_user)
		if recipient_email:
			subject = email_subject or title
			body = email_body or message
			ok = _send_email(
				recipient_email,
				subject,
				body,
				reference_doctype=reference_doctype,
				reference_name=reference_name,
			)
			if ok:
				try:
					frappe.db.set_value(
						"Platform Notification",
						doc.name,
						"email_sent",
						1,
						update_modified=False,
					)
				except Exception:
					frappe.log_error(title="notify: email_sent flag")

	frappe.db.commit()
	return doc.name


def _resolve_user_email(user: str) -> str:
	"""User name → e-posta. Administrator gibi özel name'lerde User.email'den çek."""
	if not user:
		return ""
	if "@" in user:
		return user
	return frappe.db.get_value("User", user, "email") or ""


def _send_email(
	recipient: str,
	subject: str,
	body_html: str,
	reference_doctype: str = "",
	reference_name: str = "",
) -> bool:
	"""frappe.sendmail wrapper — queue'ya atar (now=False).

	Default outgoing Email Account yoksa Frappe sessizce skip eder; hata
	yakalanırsa False döner ve email_sent False kalır.
	"""
	kwargs = {
		"recipients": [recipient],
		"subject": subject,
		"message": body_html,
		"now": False,
		"delayed": True,
	}
	if reference_doctype and reference_name:
		kwargs["reference_doctype"] = reference_doctype
		kwargs["reference_name"] = reference_name
	try:
		frappe.sendmail(**kwargs)
		return True
	except Exception:
		frappe.log_error(title="notify: sendmail")
		return False


# ── Bulk helpers ─────────────────────────────────────────────────────────


def notify_team_members(
	team_name: str,
	type: str,
	title: str,
	message: str,
	action_url: str = "",
	reference_doctype: str = "",
	reference_name: str = "",
	send_email: bool = False,
	email_subject: str = "",
	email_body: str = "",
	exclude_user: str = "",
) -> int:
	"""HD Team üyelerine in-app (+ opsiyonel e-posta) bildirim gönder.

	Returns:
	    Başarılı bildirim sayısı.
	"""
	if not team_name:
		return 0

	try:
		users = frappe.get_all(
			"HD Team Member",
			filters={"parent": team_name},
			pluck="user",
		)
	except Exception:
		frappe.log_error(title="notify_team_members: HD Team Member fetch")
		return 0

	role = "seller" if team_name.startswith("Seller-") else "admin"
	count = 0
	for user in users:
		if not user or user == exclude_user:
			continue
		name = notify(
			recipient_user=user,
			type=type,
			title=title,
			message=message,
			recipient_role=role,
			action_url=action_url,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
			send_email=send_email,
			email_subject=email_subject,
			email_body=email_body,
		)
		if name:
			count += 1
	return count


def notify_assigned_users(
	doctype: str,
	docname: str,
	type: str,
	title: str,
	message: str,
	action_url: str = "",
	send_email: bool = False,
	email_subject: str = "",
	email_body: str = "",
	exclude_user: str = "",
	recipient_role: str = "",
) -> int:
	"""Doc'a atanmış (ToDo) kullanıcıları bilgilendir.

	Returns:
	    Başarılı bildirim sayısı.
	"""
	if not doctype or not docname:
		return 0

	try:
		users = frappe.get_all(
			"ToDo",
			filters={
				"reference_type": doctype,
				"reference_name": docname,
				"status": "Open",
			},
			pluck="allocated_to",
		)
	except Exception:
		frappe.log_error(title="notify_assigned_users: ToDo fetch")
		return 0

	count = 0
	for user in users:
		if not user or user == exclude_user:
			continue
		name = notify(
			recipient_user=user,
			type=type,
			title=title,
			message=message,
			recipient_role=recipient_role,
			action_url=action_url,
			reference_doctype=doctype,
			reference_name=docname,
			send_email=send_email,
			email_subject=email_subject,
			email_body=email_body,
		)
		if name:
			count += 1
	return count
