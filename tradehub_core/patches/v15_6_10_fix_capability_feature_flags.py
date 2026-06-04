"""Sprint 6 — Capability Registry plan_feature_flag düzeltmesi.

`rfq.quote` ve `crm.lead_capture` capability'lerine yanlış key'lerle
(`feature.rfq_module`, `feature.crm_module`) plan_feature_flag yazılmıştı.
Feature Catalog'da gerçek key'ler `feature.functional.rfq` ve
`feature.crm.module` olduğu için "Tüm planlara ekle" CTA validation hatası
veriyordu (Subscription Plan._validate_capability_flags).

Bu patch:
  1. TH Capability Registry kayıtlarındaki plan_feature_flag'leri günceller
  2. Mevcut Subscription Plan capability_flags JSON'larında eski key'leri
     yeni key'lerle değiştirir (içerik kaybı olmaz)
"""

from __future__ import annotations

import json

import frappe

_MIGRATIONS = [
	("rfq.quote", "feature.rfq_module", "feature.functional.rfq"),
	("crm.lead_capture", "feature.crm_module", "feature.crm.module"),
]


def execute() -> dict:
	updated_caps: list[str] = []
	updated_plans: list[str] = []

	# 1) Capability Registry kayıtlarını güncelle
	for cap_key, _old_flag, new_flag in _MIGRATIONS:
		if not frappe.db.exists("TH Capability Registry", cap_key):
			continue
		current = frappe.db.get_value("TH Capability Registry", cap_key, "plan_feature_flag")
		if current == new_flag:
			continue
		frappe.db.set_value(
			"TH Capability Registry", cap_key, "plan_feature_flag", new_flag, update_modified=False
		)
		updated_caps.append(cap_key)

	# 2) Subscription Plan capability_flags JSON migrasyonu
	plans = frappe.get_all("Subscription Plan", fields=["name", "capability_flags"])
	for p in plans:
		raw = p.get("capability_flags")
		if not raw:
			continue
		try:
			flags = json.loads(raw) if isinstance(raw, str) else raw
		except (ValueError, TypeError):
			continue
		if not isinstance(flags, dict):
			continue
		changed = False
		for _cap_key, old_flag, new_flag in _MIGRATIONS:
			if old_flag in flags and new_flag not in flags:
				flags[new_flag] = flags.pop(old_flag)
				changed = True
			elif old_flag in flags:
				# Hem eski hem yeni varsa eskiyi düş
				flags.pop(old_flag)
				changed = True
		if changed:
			frappe.db.set_value(
				"Subscription Plan",
				p["name"],
				"capability_flags",
				json.dumps(flags, ensure_ascii=False),
				update_modified=False,
			)
			updated_plans.append(p["name"])

	frappe.db.commit()

	# Capability cache flush
	from tradehub_core.utils.permission_resolver import flush_all_cache

	flush_all_cache()

	return {
		"updated_capabilities": updated_caps,
		"updated_plans": updated_plans,
	}
