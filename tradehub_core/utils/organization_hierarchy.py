# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 2.4 — Organization parent_org cycle koruması + hiyerarşi yardımcıları.

CRM Organization.tradehub_parent_org self-reference field'ı için validate
hook. Cycle (A → B → A) veya self-loop (A → A) oluşmamalı.

Helper'lar:
  - validate_no_cycle(doc): cycle check
  - get_ancestors(org_name): kök'e kadar parent zinciri
  - get_descendants(org_name): alt-org'lar (depth-first)
  - get_depth(org_name): hiyerarşi derinliği (kök=0)

Detay: model.fga group hierarchy (Faz 2.1)
"""

from __future__ import annotations

import frappe
from frappe import _

# Maximum hiyerarşi derinliği (Faz 2.4 limit; sonsuz cycle'a karşı koruma)
MAX_HIERARCHY_DEPTH = 10


def validate_no_cycle(doc, method=None) -> None:
	"""CRM Organization.validate hook — parent_org cycle'ını engelle.

	Cycle örnekleri:
	  - Self-loop: A.parent_org = A
	  - 2-cycle: A.parent = B, B.parent = A
	  - N-cycle: A → B → C → A
	"""
	if not doc.get("tradehub_parent_org"):
		return  # Root org, sorun yok

	if doc.tradehub_parent_org == doc.name:
		frappe.throw(_("Organization kendisini parent olarak gösteremez."))

	# Parent zincirini takip et — kendine geliyorsa cycle
	visited: set[str] = {doc.name}
	current = doc.tradehub_parent_org
	depth = 0

	while current and depth < MAX_HIERARCHY_DEPTH:
		if current in visited:
			frappe.throw(
				_("Organization hiyerarşisinde döngü (cycle) tespit edildi: {0} → ... → {1}").format(
					doc.name, current
				)
			)
		visited.add(current)
		next_parent = frappe.db.get_value("CRM Organization", current, "tradehub_parent_org")
		if not next_parent:
			break
		current = next_parent
		depth += 1

	if depth >= MAX_HIERARCHY_DEPTH:
		frappe.throw(
			_("Organization hiyerarşi derinliği {0}'i geçemez.").format(MAX_HIERARCHY_DEPTH)
		)


def get_ancestors(org_name: str) -> list[str]:
	"""org_name'in atalarını (parent zinciri) döner. Kök en sonda.

	Returns:
	    [parent, grandparent, ..., root]
	"""
	if not org_name:
		return []

	ancestors: list[str] = []
	visited: set[str] = {org_name}
	current = frappe.db.get_value("CRM Organization", org_name, "tradehub_parent_org")
	depth = 0

	while current and depth < MAX_HIERARCHY_DEPTH:
		if current in visited:
			# Cycle güvenlik kontrolü (validate_no_cycle yakalamış olmalı)
			break
		visited.add(current)
		ancestors.append(current)
		current = frappe.db.get_value("CRM Organization", current, "tradehub_parent_org")
		depth += 1

	return ancestors


def get_descendants(org_name: str) -> list[str]:
	"""org_name'in altındaki tüm org'ları depth-first döner.

	Returns:
	    [child1, child1_child1, ..., child2, ...]
	"""
	if not org_name:
		return []

	descendants: list[str] = []
	stack = [org_name]
	visited: set[str] = {org_name}

	while stack:
		current = stack.pop()
		children = frappe.get_all(
			"CRM Organization",
			filters={"tradehub_parent_org": current},
			pluck="name",
		)
		for child in children:
			if child in visited:
				continue  # cycle defense
			visited.add(child)
			descendants.append(child)
			stack.append(child)

	return descendants


def get_depth(org_name: str) -> int:
	"""Organization'ın hiyerarşi derinliği (kök=0)."""
	return len(get_ancestors(org_name))


def get_root(org_name: str) -> str:
	"""En üst (root) organization'ı döner."""
	ancestors = get_ancestors(org_name)
	return ancestors[-1] if ancestors else org_name
