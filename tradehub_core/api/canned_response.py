"""
Helpdesk Canned Response API.

Ajan ticket detay composer'ında "şablon ekle" dropdown için listeleme +
seçilen şablonu ticket bağlamına göre render etme (placeholder
substitution: {{ticket_id}}, {{customer_name}}, {{order_id}}).
"""

import re

import frappe
from frappe import _

PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-z_]+)\s*\}\}")


@frappe.whitelist()
def list_for_user(category: str = "") -> list:
	"""Çağıran user'ın görebileceği canned response listesi.

	scope=platform: hepsi
	scope=team: kullanıcı o team'in üyesiyse
	scope=personal: sadece sahibi
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

	user_teams = frappe.get_all(
		"HD Team Member",
		filters={"user": user},
		pluck="parent",
	)

	filters = [["is_active", "=", 1]]
	if category:
		filters.append(["category", "=", category])

	rows = frappe.get_all(
		"Helpdesk Canned Response",
		filters=filters,
		fields=[
			"name",
			"title",
			"category",
			"scope",
			"created_by_team",
			"owner",
			"content",
		],
		order_by="title asc",
		limit_page_length=500,
	)

	visible = []
	for r in rows:
		scope = r.get("scope") or "platform"
		if scope == "platform":
			visible.append(r)
		elif scope == "team":
			if r.get("created_by_team") in user_teams:
				visible.append(r)
		elif scope == "personal":
			if r.get("owner") == user:
				visible.append(r)
	return visible


@frappe.whitelist()
def render(canned_response: str, ticket: str = "") -> dict:
	"""Şablonu seçilen ticket bağlamında render et."""
	if not canned_response:
		frappe.throw(_("Şablon kimliği gerekli."), frappe.ValidationError)

	if not frappe.has_permission("Helpdesk Canned Response", doc=canned_response, ptype="read"):
		frappe.throw(_("Bu şablona erişim yetkiniz yok."), frappe.PermissionError)

	doc = frappe.get_doc("Helpdesk Canned Response", canned_response)
	content = doc.content or ""

	context = {"ticket_id": "", "customer_name": "", "order_id": ""}
	if ticket and frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
		ticket_doc = frappe.db.get_value(
			"HD Ticket",
			ticket,
			["name", "customer_name", "raised_by"],
			as_dict=True,
		)
		if ticket_doc:
			context["ticket_id"] = ticket_doc.name or ""
			context["customer_name"] = ticket_doc.customer_name or ticket_doc.raised_by or ""

	def replace(match):
		key = match.group(1)
		return frappe.utils.escape_html(str(context.get(key) or f"{{{{{key}}}}}"))

	rendered = PLACEHOLDER_RE.sub(replace, content)
	return {"title": doc.title, "content": rendered}
