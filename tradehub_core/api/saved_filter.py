"""
Helpdesk Saved Filter API.

Kullanıcının kişisel ticket görünümlerini saklar (filtre + sıralama).
is_shared=1 ise team üyeleri de görür.
"""

import json

import frappe
from frappe import _


@frappe.whitelist()
def list_my_filters():
	"""Çağıranın görebileceği saved filter'ları döndür.

	- Sahibi olduğu hepsi
	- Aynı team'lerdeki paylaşılan (is_shared=1) filter'lar
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)

	user_teams = frappe.get_all(
		"HD Team Member",
		filters={"user": user},
		pluck="parent",
	)

	# Sahibi olduğum filter'lar
	mine = frappe.get_all(
		"Helpdesk Saved Filter",
		filters={"owner_user": user},
		fields=["name", "label", "is_pinned", "is_shared", "filters_json", "owner_user"],
		order_by="is_pinned desc, label asc",
		limit_page_length=200,
	)

	shared = []
	if user_teams:
		# Paylaşılan filter'ları, sahibi aynı team'de olanlar üzerinden bul
		shared_team_users = frappe.get_all(
			"HD Team Member",
			filters={"parent": ["in", user_teams]},
			pluck="user",
		)
		shared_team_users = list({u for u in shared_team_users if u and u != user})
		if shared_team_users:
			shared = frappe.get_all(
				"Helpdesk Saved Filter",
				filters={"is_shared": 1, "owner_user": ["in", shared_team_users]},
				fields=["name", "label", "is_pinned", "is_shared", "filters_json", "owner_user"],
				order_by="label asc",
				limit_page_length=200,
			)

	return {"mine": mine, "shared": shared}


@frappe.whitelist()
def save_filter(label: str, filters_json: str, name: str = "", is_pinned: int = 0, is_shared: int = 0):
	"""Yeni veya mevcut filter'ı kaydet."""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Giriş yapmalısınız."), frappe.PermissionError)
	if not (label or "").strip():
		frappe.throw(_("Görünüm adı zorunlu."), frappe.ValidationError)

	# JSON validate
	try:
		json.loads(filters_json or "{}")
	except (TypeError, ValueError):
		frappe.throw(_("Filtre JSON geçersiz."), frappe.ValidationError)

	if name:
		# Update — sadece sahibi
		owner = frappe.db.get_value("Helpdesk Saved Filter", name, "owner_user")
		if owner != user and "System Manager" not in frappe.get_roles():
			frappe.throw(_("Bu görünümü değiştirme yetkiniz yok."), frappe.PermissionError)
		doc = frappe.get_doc("Helpdesk Saved Filter", name)
		doc.label = label.strip()[:140]
		doc.filters_json = filters_json
		doc.is_pinned = int(is_pinned or 0)
		doc.is_shared = int(is_shared or 0)
		doc.save(ignore_permissions=True)
	else:
		doc = frappe.new_doc("Helpdesk Saved Filter")
		doc.label = label.strip()[:140]
		doc.owner_user = user
		doc.filters_json = filters_json
		doc.is_pinned = int(is_pinned or 0)
		doc.is_shared = int(is_shared or 0)
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
	return {"name": doc.name, "ok": True}


@frappe.whitelist()
def delete_filter(name: str):
	"""Sahibi filter'ı silebilir."""
	user = frappe.session.user
	owner = frappe.db.get_value("Helpdesk Saved Filter", name, "owner_user")
	if not owner:
		frappe.throw(_("Görünüm bulunamadı."), frappe.DoesNotExistError)
	if owner != user and "System Manager" not in frappe.get_roles():
		frappe.throw(_("Yetkiniz yok."), frappe.PermissionError)

	frappe.delete_doc("Helpdesk Saved Filter", name, ignore_permissions=True)
	frappe.db.commit()
	return {"ok": True}
