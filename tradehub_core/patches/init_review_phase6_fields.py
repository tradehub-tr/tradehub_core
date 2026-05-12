"""Faz 6 — Push Settings init + sample Moderation Rule seed."""

import frappe


def execute():
	_init_push_settings()
	_seed_default_moderation_rules()
	frappe.db.commit()


def _init_push_settings():
	if not frappe.db.exists("DocType", "Push Notification Settings"):
		return
	try:
		settings = frappe.get_single("Push Notification Settings")
		if not settings.vapid_subject:
			settings.vapid_subject = "mailto:admin@tradehub.local"
		settings.save(ignore_permissions=True)
	except Exception:
		frappe.log_error(title="phase6_push_settings_init")


def _seed_default_moderation_rules():
	if not frappe.db.table_exists("tabModeration Rule"):
		return
	defaults = [
		{
			"rule_name": "Auto-Reject High Risk (80+)",
			"trigger_type": "risk_score_high",
			"threshold_value": 80,
			"action": "auto_reject",
			"reason_template": "Otomatik red: Yüksek risk skoru tespit edildi.",
		},
		{
			"rule_name": "Auto-Hide Abuse 5+",
			"trigger_type": "abuse_threshold",
			"threshold_value": 5,
			"action": "auto_hide",
			"reason_template": "Otomatik gizleme: Çoklu ihbar alındı.",
		},
	]
	for d in defaults:
		if frappe.db.exists("Moderation Rule", d["rule_name"]):
			continue
		try:
			doc = frappe.new_doc("Moderation Rule")
			doc.update(d)
			doc.is_active = 1
			doc.insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(title="seed_moderation_rule_failed", message=d["rule_name"])
