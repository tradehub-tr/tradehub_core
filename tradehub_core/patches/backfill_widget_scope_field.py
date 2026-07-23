"""Backfill Dashboard Widget.scope_field from legacy config_json.scope_field.

Eski seed'lerde widget'lar config_json içinde {"scope_field": "seller"} olarak
tutuyordu. Yeni mimaride scope_field first-class field. Bu patch:

1. config_json.scope_field var olan ama scope_field column'u boş olan widget'ları
   bulur
2. scope_field column'unu config_json'dan kopyalar
3. config_json'da başka konfig kalıyorsa onu olduğu gibi bırakır (regression yok)

İdempotent: scope_field zaten doluysa atlanır; yeniden koşturulduğunda zarar yok.
"""

import json

import frappe


def execute():
	# Tüm Dashboard Widget'ları al — scope_field boş olanlar dahil
	widgets = frappe.get_all(
		"Dashboard Widget",
		fields=["name", "scope_field", "config_json"],
	)

	updated = 0
	skipped_already_set = 0
	skipped_no_config = 0

	for w in widgets:
		# Idempotent: zaten set ise atla
		if w.get("scope_field"):
			skipped_already_set += 1
			continue
		if not w.get("config_json"):
			skipped_no_config += 1
			continue

		try:
			config = json.loads(w["config_json"])
		except (TypeError, ValueError):
			# Bozuk JSON'u atla — admin form'da yine de elle düzeltir
			continue

		legacy_field = config.get("scope_field")
		if not legacy_field:
			continue

		# Direct SQL ile field'a yaz (validate'i tetiklemez, döngüsel hatadan korur)
		frappe.db.set_value("Dashboard Widget", w["name"], "scope_field", legacy_field, update_modified=False)
		updated += 1

	frappe.db.commit()
	frappe.logger("patches").info(
		f"[backfill_widget_scope_field] updated={updated} "
		f"skipped_already_set={skipped_already_set} skipped_no_config={skipped_no_config}"
	)
