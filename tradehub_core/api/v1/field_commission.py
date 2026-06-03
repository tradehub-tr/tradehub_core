# Copyright (c) 2026, TR TradeHub and contributors
"""Saha pazarlama hakediş API'si.

- Saha elemanı: get_my_commissions (yalnız kendi kayıtları + özet).
- Super admin: list_commissions, approve_commission, reject_commission, mark_paid.
"""

import frappe
from frappe import _
from frappe.utils import flt, now_datetime

# Hakediş yönetim yetkisi olan roller — permission katmanıyla TEK kaynak.
# permissions.py'deki query_conditions/has_permission de aynı seti kullanır;
# burada import ederek görünürlük (permission) ile aksiyon (API) hizalanır.
from tradehub_core.permissions import _FIELD_COMMISSION_ADMIN_ROLES as _ADMIN_ROLES

_LIST_FIELDS = [
	"name",
	"agent",
	"deal",
	"plan",
	"commission_type",
	"base_amount",
	"commission_rate",
	"commission_amount",
	"currency",
	"commission_mode",
	"status",
	"approved_at",
	"paid_at",
	"creation",
]


def _require_admin() -> None:
	user = frappe.session.user
	roles = set(frappe.get_roles(user))
	if user != "Administrator" and not (roles & _ADMIN_ROLES):
		frappe.throw(_("Bu işlem için yetkiniz yok."), exc=frappe.PermissionError)


def _summary(filters: dict) -> dict:
	"""Para birimi bazında durum toplamları.

	get_all kullanımı bilinçli: çağrı yerleri zaten yetki kapısından geçer —
	get_my_commissions agent==session user ile scope'lar, list_commissions
	_require_admin() ile korur. Aggregate sorgusu permission_query_conditions
	join'ine ihtiyaç duymadan toplamları doğrudan hesaplar.
	"""
	rows = frappe.get_all(
		"Field Commission",
		filters=filters,
		fields=["status", "currency", "sum(commission_amount) as total"],
		group_by="status, currency",
	)
	out: dict = {}
	for r in rows:
		cur = r.currency or ""
		out.setdefault(cur, {"Beklemede": 0, "Onaylandı": 0, "Ödendi": 0, "Reddedildi": 0})
		out[cur][r.status] = float(r.total or 0)
	return out


@frappe.whitelist()
def get_my_commissions(
	status: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
) -> dict:
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Yetki gerekli."), exc=frappe.PermissionError)
	filters: dict = {"agent": user}
	if status:
		filters["status"] = status
	# get_list: saha elemanının KENDİ verisi — permission_query_conditions
	# defense-in-depth olarak devreye girsin (rule #14).
	rows = frappe.get_list(
		"Field Commission",
		filters=filters,
		fields=_LIST_FIELDS,
		order_by="creation desc",
		limit_start=int(limit_start),
		limit_page_length=int(limit_page_length),
	)
	return {
		"rows": rows,
		"total": frappe.db.count("Field Commission", filters),
		"summary": _summary({"agent": user}),
	}


@frappe.whitelist()
def list_commissions(
	agent: str | None = None,
	status: str | None = None,
	plan: str | None = None,
	limit_start: int = 0,
	limit_page_length: int = 50,
) -> dict:
	_require_admin()
	filters: dict = {}
	if agent:
		filters["agent"] = agent
	if status:
		filters["status"] = status
	if plan:
		filters["plan"] = plan
	# get_all kabul: çağrı _require_admin() ile korunur — admin tüm kayıtları
	# yönetir, sistem/admin erişimi (rule #14 gerekçesi).
	rows = frappe.get_all(
		"Field Commission",
		filters=filters,
		fields=_LIST_FIELDS,
		order_by="creation desc",
		limit_start=int(limit_start),
		limit_page_length=int(limit_page_length),
	)
	return {
		"rows": rows,
		"total": frappe.db.count("Field Commission", filters),
		"summary": _summary(filters),
	}


def _transition(name: str, from_status: str, to_status: str, **extra) -> dict:
	_require_admin()
	doc = frappe.get_doc("Field Commission", name)
	if doc.status != from_status:
		frappe.throw(
			_("Sadece '{0}' durumundaki hakediş bu işleme uygundur (mevcut: {1}).").format(
				from_status, doc.status
			)
		)
	doc.status = to_status
	for k, v in extra.items():
		setattr(doc, k, v)
	doc.save(ignore_permissions=True)
	return {"ok": True, "name": doc.name, "status": doc.status}


@frappe.whitelist()
def approve_commission(name: str) -> dict:
	return _transition(
		name,
		"Beklemede",
		"Onaylandı",
		approved_by=frappe.session.user,
		approved_at=now_datetime(),
	)


@frappe.whitelist()
def reject_commission(name: str, note: str | None = None) -> dict:
	# note default None: parametresiz çağrıda Frappe TypeError(500) yerine i18n 417 dönsün.
	if not note:
		frappe.throw(_("Red sebebi (not) zorunludur."))
	return _transition(name, "Beklemede", "Reddedildi", note=note)


@frappe.whitelist()
def mark_paid(name: str) -> dict:
	return _transition(name, "Onaylandı", "Ödendi", paid_at=now_datetime())


@frappe.whitelist()
def get_settings() -> dict:
	"""Saha hakediş ayarlarını oku (süperadmin)."""
	_require_admin()
	return {
		"global_per_sale_amount": flt(
			frappe.db.get_single_value("Field Commission Settings", "global_per_sale_amount")
		),
	}


@frappe.whitelist()
def update_settings(global_per_sale_amount: float) -> dict:
	"""Saha hakediş ayarlarını güncelle (süperadmin)."""
	_require_admin()
	if flt(global_per_sale_amount) < 0:
		frappe.throw(_("Global satış başı tutar negatif olamaz."))
	doc = frappe.get_single("Field Commission Settings")
	doc.global_per_sale_amount = flt(global_per_sale_amount)
	# ignore_permissions: yetki yukarıda _require_admin() ile doğrulandı.
	doc.save(ignore_permissions=True)
	return {"ok": True, "global_per_sale_amount": flt(doc.global_per_sale_amount)}
