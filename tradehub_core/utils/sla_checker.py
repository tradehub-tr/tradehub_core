"""
HD Ticket SLA breach checker.

Saatlik scheduler:
- Aktif Helpdesk SLA Policy'leri yükle (priority bazlı)
- Açık ticket'lar (Open / Replied) için breach kontrol et:
  * İlk yanıt: first_responded_on yoksa ve creation + first_response_minutes geçtiyse
  * Çözüm: status Resolved/Closed değil ve creation + resolution_minutes geçtiyse
- Breach durumunda:
  * Ticket'a HD Ticket Comment ekle (magic string ile dedup)
  * Atanmış ajan(lar)a + team'e in-app + e-posta bildir
  * Bir kez bildirilen breach tekrar bildirilmez (comment dedup)

Magic string'ler:
  [SLA-FIRST-BREACH]
  [SLA-RESOLUTION-BREACH]
"""

import frappe
from frappe.utils import add_to_date, now_datetime

from tradehub_core.utils.notify import notify_assigned_users, notify_team_members

FIRST_BREACH_TAG = "[SLA-FIRST-BREACH]"
RESOLUTION_BREACH_TAG = "[SLA-RESOLUTION-BREACH]"


def check_sla_breaches():
	"""hourly scheduler tarafından çağrılır."""
	policies = _load_active_policies()
	if not policies:
		return

	# Açık veya yanıtlanmış ticket'lar (kapanmış olanlar SLA dışı)
	tickets = frappe.get_all(
		"HD Ticket",
		filters={"status": ["in", ["Open", "Replied"]]},
		fields=[
			"name",
			"subject",
			"priority",
			"creation",
			"first_responded_on",
			"agent_group",
			"raised_by",
		],
		limit_page_length=1000,
	)

	now = now_datetime()
	for t in tickets:
		policy = policies.get((t.get("priority") or "").strip())
		if not policy:
			continue
		_check_ticket(t, policy, now)


def _load_active_policies() -> dict:
	rows = frappe.get_all(
		"Helpdesk SLA Policy",
		filters={"is_active": 1},
		fields=["name", "priority", "first_response_minutes", "resolution_minutes"],
	)
	return {r.priority: r for r in rows}


def _check_ticket(ticket: dict, policy, now):
	created = frappe.utils.get_datetime(ticket["creation"])

	# 1) İlk yanıt SLA
	if not ticket.get("first_responded_on") and policy.first_response_minutes:
		breach_at = add_to_date(created, minutes=policy.first_response_minutes)
		if now > breach_at and not _already_notified(ticket["name"], FIRST_BREACH_TAG):
			_handle_breach(
				ticket,
				breach_kind="first",
				tag=FIRST_BREACH_TAG,
				breach_at=breach_at,
				policy_minutes=policy.first_response_minutes,
			)

	# 2) Çözüm SLA — Resolved/Closed olmayanlar
	if policy.resolution_minutes:
		breach_at = add_to_date(created, minutes=policy.resolution_minutes)
		if now > breach_at and not _already_notified(ticket["name"], RESOLUTION_BREACH_TAG):
			_handle_breach(
				ticket,
				breach_kind="resolution",
				tag=RESOLUTION_BREACH_TAG,
				breach_at=breach_at,
				policy_minutes=policy.resolution_minutes,
			)


def _already_notified(ticket_name: str, tag: str) -> bool:
	"""HD Ticket Comment'lerde tag string'i daha önce yazıldı mı?"""
	try:
		count = frappe.db.count(
			"HD Ticket Comment",
			filters={
				"reference_ticket": ticket_name,
				"content": ["like", f"%{tag}%"],
			},
		)
		return count > 0
	except Exception:
		# HD Ticket Comment doctype yoksa veya filter çalışmazsa breach tekrar
		# bildirilebilir — kabul edilebilir trade-off (sessiz hata yerine).
		return False


def _handle_breach(ticket: dict, breach_kind: str, tag: str, breach_at, policy_minutes: int):
	"""Breach kaydı: comment + bildirim."""
	ticket_name = ticket["name"]
	subject = ticket.get("subject") or ticket_name
	hours = round(policy_minutes / 60, 1)

	if breach_kind == "first":
		title = f"SLA: İlk yanıt aşıldı — {subject}"
		message = f"Bu talep {hours} saatlik ilk yanıt SLA'sini aştı. Lütfen müşteriye yanıt verin."
	else:
		title = f"SLA: Çözüm süresi aşıldı — {subject}"
		message = f"Bu talep {hours} saatlik çözüm SLA'sini aştı. Çözüme öncelik verin."

	# 1) HD Ticket Comment — dedup için tag, ajanın timeline'ında görünür
	try:
		comment = frappe.new_doc("HD Ticket Comment")
		comment.reference_ticket = ticket_name
		comment.content = f"{tag} {message}"
		comment.commented_by = "Administrator"
		comment.insert(ignore_permissions=True)
	except Exception:
		frappe.log_error(title=f"sla_checker: HD Ticket Comment {ticket_name}")

	# 2) Bildirim — atanmış varsa onlara, yoksa team'e
	body = _email_body_html(title, message, ticket_name)
	email_subject = f"[TradeHub SLA] {title}"

	assigned = notify_assigned_users(
		doctype="HD Ticket",
		docname=ticket_name,
		type="dispute",
		title=title,
		message=message,
		action_url=f"/helpdesk/tickets/{ticket_name}",
		send_email=True,
		email_subject=email_subject,
		email_body=body,
		recipient_role="admin",
	)

	if assigned == 0 and ticket.get("agent_group"):
		notify_team_members(
			team_name=ticket["agent_group"],
			type="dispute",
			title=title,
			message=message,
			action_url=f"/helpdesk/tickets/{ticket_name}",
			reference_doctype="HD Ticket",
			reference_name=ticket_name,
			send_email=True,
			email_subject=email_subject,
			email_body=body,
		)

	frappe.db.commit()


def _email_body_html(heading: str, body_text: str, ticket_name: str) -> str:
	from urllib.parse import quote

	from tradehub_core.seo.site_url import admin_panel_url

	link = f"{admin_panel_url()}/helpdesk/tickets/{quote(ticket_name, safe='')}"
	safe_body = frappe.utils.escape_html(body_text or "")
	return f"""
<div style="font-family: -apple-system, Segoe UI, Roboto, sans-serif; color: #222; max-width: 560px;">
  <h2 style="margin: 0 0 16px; font-size: 18px; color: #b91c1c;">⚠ SLA Breach</h2>
  <p style="margin: 0 0 8px; font-size: 14px;"><strong>{frappe.utils.escape_html(heading)}</strong></p>
  <div style="margin: 16px 0; padding: 12px 14px; background: #fef2f2; border-left: 3px solid #b91c1c; border-radius: 4px; font-size: 14px; line-height: 1.5;">
    {safe_body}
  </div>
  <p style="margin: 24px 0 0;">
    <a href="{frappe.utils.escape_html(link)}"
       style="display: inline-block; padding: 10px 18px; background: #b91c1c; color: #fff; text-decoration: none; border-radius: 6px; font-size: 14px;">
      Talebi Aç
    </a>
  </p>
  <p style="margin: 28px 0 0; font-size: 11px; color: #888;">
    Bu e-posta TradeHub SLA monitor tarafından otomatik gönderildi.
  </p>
</div>
""".strip()
