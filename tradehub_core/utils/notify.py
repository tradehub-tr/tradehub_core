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


def _sanitize_action_url(url: str) -> str:
	"""
	action_url whitelist (#5) — phishing/XSS koruması.

	Yalniz iki tip URL kabul edilir:
	  1) Relative path: '/...' (ama '//attacker.com' protocol-relative DEGIL)
	  2) Mutlak HTTPS: 'https://...'

	'javascript:', 'data:', 'vbscript:', 'http:' (insecure), 'file:' vb. reddedilir.
	Reddedilen URL bos string'e dönüştürülür — bildirim yine olusur ama UI'da
	'Görüntüle' butonu cikmaz.
	"""
	if not url or not isinstance(url, str):
		return ""
	trimmed = url.strip()
	if not trimmed:
		return ""
	# Relative path — '//attacker.com' protocol-relative URL'i reject
	if trimmed.startswith("/") and not trimmed.startswith("//"):
		return trimmed
	# Mutlak HTTPS
	if trimmed.lower().startswith("https://"):
		return trimmed
	return ""


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
	event_key: str = "",
	event_data: dict | None = None,
	occurrence_id: str = "",
) -> str:
	"""Platform Notification kaydı oluştur, opsiyonel olarak e-posta gönder.

	`event_key` (bildirim kataloğu anahtarı) verilirse çağrı olay odaklı gönderim servisine
	(`notifications.dispatch.emit`) gider: kullanıcı tercihi, kanal kuralı ve yayınlanmış şablon
	uygulanır. Yeni yolun üstlendiği kanalı (ya da kapalı/kullanıcının kapattığı kanalı) aşağıdaki
	eski yol GÖNDERMEZ; yayınlanmış şablonu olmayan kanal eski davranışla devam eder. `event_key`
	vermeyen mevcut çağrılar hiç değişmeden çalışır.

	`send_email=True` verilirse Platform Notification kaydedildikten sonra
	`frappe.sendmail` queue'ya atılır (now=False). Hata durumunda kayıt
	kaybolmaz; sadece log'a düşer ve `email_sent` False kalır.

	**Transaction:** Bu helper artik `frappe.db.commit()` cagirmiyor. Outer
	caller (HTTP request, doctype hook, scheduler runner) commit'ten
	sorumlu — Frappe HTTP request'leri sonunda otomatik commit eder, doctype
	save akislari da kendi transaction'lariyla commit ederler. Erken commit
	outer transaction'i kirip kismi rollback'i imkansizlastiriyordu.

	Returns:
	    Oluşturulan bildirimin `name` değeri (hata durumunda "").
	"""
	if not recipient_user:
		return ""
	# Guest, Administrator veya systemic user'lara bildirim atilmaz —
	# Administrator'a yanlis konfigle binlerce mesaj birikiyordu (#8).
	if recipient_user in ("Guest", "Administrator"):
		return ""

	if event_key:
		handled = _emit_event(
			event_key,
			recipient_user,
			event_data or {},
			occurrence_id or f"{reference_doctype}:{reference_name}:{event_key}",
			{
				"type": type,
				"reference_doctype": reference_doctype,
				"reference_name": reference_name,
				"recipient_role": recipient_role,
			},
		)
		if "email" in handled:
			send_email = False
		if "inapp" in handled:
			if not send_email:
				return ""
			# Uygulama içi kanal yeni yolda; legacy yalnız e-postayı (şablonu yoksa) gönderir.
			return _legacy_email_only(recipient_user, title, message, email_subject, email_body, reference_doctype, reference_name)

	effective_channel = "email" if send_email else channel

	# action_url phishing/XSS guvenli haline cevir — kabul edilmeyenler bos
	# string olarak yazilir (bildirim olusur ama 'Görüntüle' butonu olmaz).
	safe_action_url = _sanitize_action_url(action_url)

	try:
		doc = frappe.get_doc(
			{
				"doctype": "Platform Notification",
				"recipient_user": recipient_user,
				"recipient_role": recipient_role,
				"type": type,
				"title": (title or "")[:200] or "(Bildirim)",
				"message": (message or "")[:1000],
				"action_url": safe_action_url,
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

	# Caller commit'ten sorumlu — Frappe HTTP request'leri ve doctype save
	# akislari otomatik commit eder.
	return doc.name


def _emit_event(event_key: str, user: str, data: dict, occurrence_id: str, meta: dict) -> set:
	"""Yeni gönderim yolunu çağırır; hata olursa (kanal kaybetmemek için) eski yola bırakır."""
	try:
		from tradehub_core.notifications.dispatch import emit

		return emit(event_key, user, data, occurrence_id, meta=meta)["handled"]
	except Exception:
		frappe.log_error(title=f"notify: dispatch {event_key}")
		return set()


def _legacy_email_only(user, title, message, email_subject, email_body, reference_doctype, reference_name) -> str:
	recipient_email = _resolve_user_email(user)
	if recipient_email:
		_send_email(
			recipient_email,
			email_subject or title,
			email_body or message,
			reference_doctype=reference_doctype,
			reference_name=reference_name,
		)
	return ""


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
