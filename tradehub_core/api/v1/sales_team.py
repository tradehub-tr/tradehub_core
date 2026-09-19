# Copyright (c) 2026, TR TradeHub and contributors
"""Satış Ekibi (saha pazarlama) yönetim API'si — admin panel.

Süper admin ekip kurar, lider ve üye atar. Atama sırasında roller otomatik verilir:
lider → 'Saha Ekip Lideri', üye → 'Saha Pazarlama'. Rol geri alınmaz (eleman başka
ekipte ya da pasif ekipte olabilir); gerekiyorsa Yetki Yönetimi'nden kaldırılır.
"""

import json

import frappe
from frappe import _
from frappe.model.rename_doc import rename_doc

from tradehub_core.permissions import _FIELD_COMMISSION_ADMIN_ROLES as _ADMIN_ROLES  # noqa: I001
from tradehub_core.permissions import _FIELD_COMMISSION_LEADER_ROLE as _LEADER_ROLE

_AGENT_ROLE = "Saha Pazarlama"
_PROTECTED_USERS = frozenset({"Administrator", "Guest"})


def _require_admin() -> None:
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not (roles & _ADMIN_ROLES):
		frappe.throw(_("Bu işlem için yetkiniz yok."), exc=frappe.PermissionError)


def _user_names(users: list[str]) -> dict[str, str]:
	if not users:
		return {}
	rows = frappe.get_all("User", filters={"name": ["in", users]}, fields=["name", "full_name"])
	return {r.name: r.full_name or r.name for r in rows}


def _serialize(doc, names: dict[str, str] | None = None) -> dict:
	members = [m.agent for m in doc.members if m.agent]
	names = names if names is not None else _user_names([doc.leader, *members])
	return {
		"name": doc.name,
		"team_name": doc.team_name,
		"leader": doc.leader,
		"leader_name": names.get(doc.leader, doc.leader),
		"is_active": int(doc.is_active or 0),
		"members": [{"agent": a, "full_name": names.get(a, a)} for a in members],
		"modified": str(doc.modified) if doc.modified else None,
	}


@frappe.whitelist()
def list_sales_teams() -> list[dict]:
	"""Tüm satış ekipleri + üyeleri (batch, N+1 yok)."""
	_require_admin()
	teams = frappe.get_all(
		"Sales Team",
		fields=["name", "team_name", "leader", "is_active", "modified"],
		order_by="is_active desc, team_name asc",
	)
	if not teams:
		return []
	member_rows = frappe.get_all(
		"Sales Team Member",
		filters={"parent": ["in", [t.name for t in teams]], "parenttype": "Sales Team"},
		fields=["parent", "agent", "idx"],
		order_by="idx asc",
	)
	by_team: dict[str, list[str]] = {}
	for r in member_rows:
		if r.agent:
			by_team.setdefault(r.parent, []).append(r.agent)
	all_users = {t.leader for t in teams if t.leader} | {r.agent for r in member_rows if r.agent}
	names = _user_names(list(all_users))
	return [
		{
			"name": t.name,
			"team_name": t.team_name,
			"leader": t.leader,
			"leader_name": names.get(t.leader, t.leader),
			"is_active": int(t.is_active or 0),
			"members": [{"agent": a, "full_name": names.get(a, a)} for a in by_team.get(t.name, [])],
			"modified": str(t.modified),
		}
		for t in teams
	]


@frappe.whitelist()
def search_users(q: str = "", limit: int = 20) -> list[dict]:
	"""Ekibe eklenecek aktif kullanıcıları e-posta / ad ile ara.

	Rolü olmayan kullanıcı Frappe'de 'Website User' görünür; ekibe alınınca rol
	eklenir ve System User'a döner. Bu yüzden user_type ile filtrelenmez.
	"""
	_require_admin()
	q = (q or "").strip()
	filters = {"enabled": 1, "name": ["not in", list(_PROTECTED_USERS)]}
	or_filters = {"name": ["like", f"%{q}%"], "full_name": ["like", f"%{q}%"]} if q else None
	rows = frappe.get_all(
		"User",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "full_name", "user_type"],
		order_by="full_name asc",
		limit_page_length=max(1, min(int(limit), 50)),
	)
	if not rows:
		return []
	role_rows = frappe.get_all(
		"Has Role",
		filters={
			"parenttype": "User",
			"parent": ["in", [r.name for r in rows]],
			"role": ["in", [_AGENT_ROLE, _LEADER_ROLE]],
		},
		fields=["parent", "role"],
	)
	roles: dict[str, set] = {}
	for r in role_rows:
		roles.setdefault(r.parent, set()).add(r.role)
	return [
		{
			"name": r.name,
			"full_name": r.full_name or r.name,
			"user_type": r.user_type,
			"is_agent": _AGENT_ROLE in roles.get(r.name, set()),
			"is_leader": _LEADER_ROLE in roles.get(r.name, set()),
		}
		for r in rows
	]


def _parse_members(members) -> list[str]:
	if members is None or members == "":
		return []
	if isinstance(members, str):
		members = json.loads(members)
	if not isinstance(members, list):
		frappe.throw(_("Üye listesi geçersiz."))
	out: list[str] = []
	for m in members:
		agent = (m.get("agent") if isinstance(m, dict) else m) or ""
		agent = str(agent).strip()
		if agent and agent not in out:
			out.append(agent)
	return out


def _assert_enabled_user(user: str, label: str) -> None:
	if user in _PROTECTED_USERS:
		frappe.throw(_("{0} olarak '{1}' seçilemez.").format(label, user))
	row = frappe.db.get_value("User", user, ["enabled"], as_dict=True)
	if not row:
		frappe.throw(_("Kullanıcı bulunamadı: {0}").format(user))
	if not row.enabled:
		frappe.throw(_("{0} pasif bir kullanıcı olamaz: {1}").format(label, user))


def _ensure_role(user: str, role: str) -> None:
	if user in _PROTECTED_USERS:
		return
	if frappe.db.exists("Has Role", {"parenttype": "User", "parent": user, "role": role}):
		return
	frappe.get_doc("User", user).add_roles(role)


@frappe.whitelist(methods=["POST"])
def save_sales_team(
	team_name: str,
	leader: str,
	members: list | str | None = None,
	is_active: int = 1,
	name: str | None = None,
) -> dict:
	"""Ekip oluştur (name yok) ya da güncelle (name var). Üye listesi tamamen değiştirilir.

	Ad değişirse belge yeniden adlandırılır (autoname field:team_name); Field Commission
	bağlantıları rename ile taşınır. Lider ve üyelere gerekli roller eklenir.
	"""
	_require_admin()
	team_name = (team_name or "").strip()
	leader = (leader or "").strip()
	if not team_name:
		frappe.throw(_("Ekip adı zorunlu."))
	if not leader:
		frappe.throw(_("Ekip lideri zorunlu."))
	agents = _parse_members(members)
	_assert_enabled_user(leader, _("Ekip lideri"))
	for a in agents:
		_assert_enabled_user(a, _("Üye"))

	if name:
		if not frappe.db.exists("Sales Team", name):
			frappe.throw(_("Ekip bulunamadı: {0}").format(name))
		if team_name != name:
			if frappe.db.exists("Sales Team", team_name):
				frappe.throw(_("Bu adda bir ekip zaten var: {0}").format(team_name))
			rename_doc("Sales Team", name, team_name, ignore_permissions=True, show_alert=False)
			name = team_name
		doc = frappe.get_doc("Sales Team", name)
	else:
		if frappe.db.exists("Sales Team", team_name):
			frappe.throw(_("Bu adda bir ekip zaten var: {0}").format(team_name))
		doc = frappe.new_doc("Sales Team")

	doc.team_name = team_name
	doc.leader = leader
	doc.is_active = int(is_active or 0)
	doc.set("members", [])
	for a in agents:
		doc.append("members", {"agent": a})
	doc.save(ignore_permissions=True)

	_ensure_role(leader, _LEADER_ROLE)
	for a in agents:
		_ensure_role(a, _AGENT_ROLE)

	return _serialize(doc)


@frappe.whitelist(methods=["POST"])
def delete_sales_team(name: str) -> dict:
	"""Ekibi sil. Hakediş kaydı bağlıysa silinmez — pasife alın."""
	_require_admin()
	if not frappe.db.exists("Sales Team", name):
		frappe.throw(_("Ekip bulunamadı: {0}").format(name))
	if frappe.db.exists("Field Commission", {"team": name}):
		frappe.throw(_("Bu ekibe bağlı hakediş kayıtları var; silmek yerine pasife alın."))
	frappe.delete_doc("Sales Team", name, ignore_permissions=True)
	return {"ok": True, "name": name}
