"""13.6 Değişiklik kayıtları — otomatik (Builder yayın/geri çekme, politika, yönlendirme) + elle."""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

CHANGE_TYPES = ("content", "template", "policy", "redirect", "deploy", "experiment", "other")


def log_change(
	*,
	change_type: str,
	description: str,
	scope_type: str = "site",
	scope_key: str = "",
	route: str = "",
	store: str | None = None,
	actor: str | None = None,
	source: str = "manual",
	expected_effect: str = "",
	experiment: str | None = None,
) -> str:
	if change_type not in CHANGE_TYPES:
		frappe.throw(f"change_type: {CHANGE_TYPES}", frappe.ValidationError)
	d = frappe.get_doc(
		{
			"doctype": "SEO Change Log",
			"changed_at": now_datetime(),
			"change_type": change_type,
			"scope_type": scope_type,
			"scope_key": (scope_key or "")[:140],
			"route": (route or "")[:500],
			"store": store,
			"description": (description or "")[:2000],
			"actor": actor or frappe.session.user,
			"source": source,
			"expected_effect": (expected_effect or "")[:1000],
			"experiment": experiment,
		}
	).insert(ignore_permissions=True)
	return d.name


def on_seo_policy_update(doc, method=None):
	if doc.flags.get("in_insert") or getattr(doc, "is_new", lambda: False)():
		return
	onceki = doc.get_doc_before_save()
	if not onceki:
		return
	degisen = [
		f
		for f in (
			"default_robots",
			"canonical_strategy",
			"min_title_len",
			"min_desc_len",
			"index_requires_published",
			"block_ugc_html",
		)
		if onceki.get(f) != doc.get(f)
	]
	if degisen:
		log_change(
			change_type="policy",
			scope_type="site",
			scope_key=doc.name,
			description=f"SEO Policy {doc.name}: {', '.join(degisen)} değişti",
			source="auto",
		)


def on_builder_publish_change(
	bp, onceki_durum: str | None, yeni_durum: str, route: str, store: str | None
) -> None:
	"""cms.bridge çağırır: yayın durumu değişince kayıt düş."""
	if onceki_durum == yeni_durum:
		return
	log_change(
		change_type="content",
		scope_type="route",
		scope_key=route,
		route=route,
		store=store,
		description=f"Builder Page {bp.name}: {onceki_durum or '-'} → {yeni_durum}",
		source="auto",
	)


def on_redirect_change(doc, method=None):
	log_change(
		change_type="redirect",
		scope_type="route",
		scope_key=(doc.get("source_path") or doc.get("from_path") or doc.name),
		route=(doc.get("source_path") or doc.get("from_path") or ""),
		description=f"Yönlendirme {method}: {doc.name}",
		source="auto",
	)


def recent(
	days: int = 30, *, change_type: str | None = None, route: str | None = None, limit: int = 200
) -> list[dict]:
	from frappe.utils import add_to_date

	f: dict = {"changed_at": [">=", add_to_date(now_datetime(), days=-int(days))]}
	if change_type:
		f["change_type"] = change_type
	if route:
		f["route"] = ["like", f"%{route}%"]
	return frappe.get_all(
		"SEO Change Log",
		filters=f,
		fields=[
			"name",
			"changed_at",
			"change_type",
			"scope_type",
			"scope_key",
			"route",
			"store",
			"description",
			"actor",
			"source",
			"expected_effect",
			"experiment",
		],
		order_by="changed_at desc",
		limit_page_length=max(1, min(int(limit), 1000)),
	)
