"""
HD Ticket etiket yönetimi.

Helpdesk Ticket Tag        — etiket sözlüğü (renk, açıklama).
Helpdesk Ticket Tag Link   — ticket ↔ tag bağlantısı (n:m).
"""

import frappe
from frappe import _


@frappe.whitelist()
def list_tags():
	"""Tüm etiketleri (tag sözlüğü) listele."""
	return frappe.get_all(
		"Helpdesk Ticket Tag",
		fields=["name", "tag_name", "color", "description"],
		order_by="tag_name asc",
		limit_page_length=200,
	)


@frappe.whitelist()
def list_ticket_tags(ticket: str):
	"""Belirli ticket'a bağlı tag'leri (renkleriyle) döndür."""
	if not ticket:
		return []
	if not frappe.has_permission("HD Ticket", doc=ticket, ptype="read"):
		frappe.throw(_("Bu talebe erişim yetkiniz yok."), frappe.PermissionError)

	links = frappe.get_all(
		"Helpdesk Ticket Tag Link",
		filters={"ticket": ticket},
		fields=["name", "tag"],
		limit_page_length=100,
	)
	if not links:
		return []
	tag_names = [l.tag for l in links]
	tags = {
		t.name: t
		for t in frappe.get_all(
			"Helpdesk Ticket Tag",
			filters={"name": ["in", tag_names]},
			fields=["name", "tag_name", "color"],
		)
	}
	return [
		{
			"link_name": l.name,
			"tag": l.tag,
			"tag_name": tags.get(l.tag, {}).get("tag_name") or l.tag,
			"color": tags.get(l.tag, {}).get("color") or "slate",
		}
		for l in links
	]


@frappe.whitelist()
def add_ticket_tag(ticket: str, tag: str, create_if_missing: int = 1):
	"""Ticket'a etiket ekle. tag yoksa ve create_if_missing=1 ise oluştur."""
	if not ticket or not (tag or "").strip():
		frappe.throw(_("Ticket ve tag zorunlu."), frappe.ValidationError)
	if not frappe.has_permission("HD Ticket", doc=ticket, ptype="write"):
		frappe.throw(_("Etiket eklemek için yetkiniz yok."), frappe.PermissionError)

	tag_norm = tag.strip().lower().replace(" ", "-")[:80]

	# Tag yoksa oluştur
	if not frappe.db.exists("Helpdesk Ticket Tag", tag_norm):
		if not int(create_if_missing or 0):
			frappe.throw(_("Etiket bulunamadı."), frappe.DoesNotExistError)
		new_tag = frappe.new_doc("Helpdesk Ticket Tag")
		new_tag.tag_name = tag_norm
		new_tag.color = "slate"
		new_tag.insert(ignore_permissions=True)

	# Link oluştur (varsa duplicate hatası before_insert'te yakalanır)
	if frappe.db.exists("Helpdesk Ticket Tag Link", {"ticket": ticket, "tag": tag_norm}):
		return {"ok": True, "tag": tag_norm}

	link = frappe.new_doc("Helpdesk Ticket Tag Link")
	link.ticket = ticket
	link.tag = tag_norm
	link.tagged_by = frappe.session.user
	link.insert(ignore_permissions=True)
	frappe.db.commit()

	tag_doc = frappe.db.get_value("Helpdesk Ticket Tag", tag_norm, ["tag_name", "color"], as_dict=True)
	return {
		"ok": True,
		"tag": tag_norm,
		"link_name": link.name,
		"tag_name": tag_doc.tag_name if tag_doc else tag_norm,
		"color": tag_doc.color if tag_doc else "slate",
	}


@frappe.whitelist()
def remove_ticket_tag(link_name: str):
	"""Tag link'ini kaldır (ticket'tan etiketi çıkar)."""
	if not link_name:
		frappe.throw(_("link_name zorunlu."), frappe.ValidationError)

	link = frappe.db.get_value("Helpdesk Ticket Tag Link", link_name, ["ticket"], as_dict=True)
	if not link:
		frappe.throw(_("Etiket bağlantısı bulunamadı."), frappe.DoesNotExistError)
	if not frappe.has_permission("HD Ticket", doc=link.ticket, ptype="write"):
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)

	frappe.delete_doc("Helpdesk Ticket Tag Link", link_name, ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}
