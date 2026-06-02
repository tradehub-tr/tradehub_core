# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""FAZ 3.4 — Default Authorization Anomaly Rule seed.

Idempotent: aynı rule_code varsa skip.
"""

from __future__ import annotations

import frappe

_DEFAULT_RULES = [
	{
		"rule_code": "HIGH_SEVERITY_SPIKE",
		"rule_name": "High Severity Spike",
		"detection_type": "high_severity_spike",
		"threshold_count": 10,
		"window_minutes": 5,
		"severity_filter": "HIGH",
		"action_notify": 1,
		"cooldown_minutes": 30,
		"description": "5 dakikada 10+ HIGH severity audit log",
	},
	{
		"rule_code": "RAPID_DENY_BURST",
		"rule_name": "Rapid Deny Burst (per actor)",
		"detection_type": "rapid_deny_per_actor",
		"threshold_count": 5,
		"window_minutes": 1,
		"severity_filter": "any",
		"action_notify": 1,
		"cooldown_minutes": 15,
		"description": "1 dakikada aynı kullanıcıdan 5+ DENY",
	},
	{
		"rule_code": "CROSS_TENANT_PROBE",
		"rule_name": "Cross-tenant Probe",
		"detection_type": "cross_tenant_attempt",
		"threshold_count": 3,
		"window_minutes": 5,
		"severity_filter": "any",
		"action_notify": 1,
		"action_suspend_actor": 1,
		"cooldown_minutes": 60,
		"description": "5 dakikada 3+ cross-tenant access denemesi → kullanıcıyı pasifle",
	},
	{
		"rule_code": "OFFHOUR_BURST",
		"rule_name": "Off-Hour Burst",
		"detection_type": "unusual_hour_burst",
		"threshold_count": 20,
		"window_minutes": 15,
		"severity_filter": "any",
		"action_notify": 1,
		"cooldown_minutes": 60,
		"description": "Mesai dışında 15 dakikada 20+ olay",
	},
	{
		"rule_code": "PII_BULK_ACCESS",
		"rule_name": "PII Bulk Access (per actor)",
		"detection_type": "pii_bulk_export",
		"threshold_count": 50,
		"window_minutes": 10,
		"severity_filter": "any",
		"action_notify": 1,
		"cooldown_minutes": 30,
		"description": "10 dakikada aynı kullanıcıdan 50+ PII erişimi",
	},
]


def execute() -> None:
	if not frappe.db.exists("DocType", "Authorization Anomaly Rule"):
		return

	for spec in _DEFAULT_RULES:
		if frappe.db.exists("Authorization Anomaly Rule", spec["rule_code"]):
			continue
		doc = frappe.new_doc("Authorization Anomaly Rule")
		for k, v in spec.items():
			setattr(doc, k, v)
		doc.is_active = 1
		doc.insert(ignore_permissions=True)

	frappe.db.commit()
