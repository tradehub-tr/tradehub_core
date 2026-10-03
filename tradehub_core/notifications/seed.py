"""Katalog, şablon taslakları, roller ve indeksler için idempotent seed.

İkinci ve sonraki çalıştırmalar mevcut olay kuralını, taslağı, yayını ve kullanıcı tercihini
EZMEZ: yalnız eksik kayıt eklenir. `after_migrate` ve patch aynı fonksiyonu çağırır.
"""

from __future__ import annotations

import json

import frappe

from tradehub_core.notifications import authz, catalog, content_seed, store

ROLES = (authz.CONTENT_MANAGER_ROLE, authz.VIEWER_ROLE)


def seed_roles() -> None:
	for name in ROLES:
		if not frappe.db.exists("Role", name):
			role = frappe.new_doc("Role")
			role.role_name = name
			role.desk_access = 0
			role.insert(ignore_permissions=True)


def seed_catalog() -> dict:
	created = {"events": 0, "templates": 0}
	with store._Write():
		for order, ev in enumerate(catalog.EVENTS):
			key = ev["key"]
			if not frappe.db.exists(store.EVENT, key):
				doc = frappe.get_doc(
					{
						"doctype": store.EVENT,
						"event_key": key,
						"category": ev["category"],
						"recipients": json.dumps(ev["recipients"]),
						"channels": json.dumps(ev["channels"]),
						"defaults": json.dumps(ev["defaults"]),
						"delivery": ev["delivery"],
						"mandatory": int(catalog.mandatory_of(ev["channels"])),
						"enabled": 1,
						"sort_order": order,
						"revision": 0,
					}
				)
				doc.insert(ignore_permissions=True)
				created["events"] += 1
			if not frappe.db.exists(store.TEMPLATE, key):
				tree, states, representative = content_seed.seed_for(ev)
				doc = frappe.get_doc(
					{
						"doctype": store.TEMPLATE,
						"event": key,
						"draft": json.dumps(tree, ensure_ascii=False),
						"translation_states": json.dumps(states),
						"draft_changed": 1,
						"representative": int(representative),
					}
				)
				doc.insert(ignore_permissions=True)
				created["templates"] += 1
	return created


def ensure_indexes() -> None:
	if frappe.db.table_exists(store.VERSION):
		frappe.db.add_unique(store.VERSION, ["event", "version"], constraint_name="unique_event_version")
	if frappe.db.table_exists(store.DELIVERY):
		frappe.db.add_index(store.DELIVERY, ["status", "due_at"], "status_due_at")
		frappe.db.add_index(store.DELIVERY, ["user", "creation"], "user_creation")
		frappe.db.add_index(
			store.DELIVERY, ["event", "template_version", "creation"], "event_version_creation"
		)
	if frappe.db.table_exists("Commercial Consent Sync"):
		frappe.db.add_index("Commercial Consent Sync", ["status", "next_retry_at"], "status_next_retry")


def run() -> dict:
	if not frappe.db.table_exists(store.EVENT) or not frappe.db.table_exists(store.TEMPLATE):
		return {}
	seed_roles()
	ensure_indexes()
	return seed_catalog()
