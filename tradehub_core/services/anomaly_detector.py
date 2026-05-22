"""FAZ 3.4 — OpenClaw anomaly detector.

Scheduled (hourly) job that scans Authorization Decision Log for
suspicious patterns and creates Authorization Anomaly Alert records.

Algılama tipleri:
  - high_severity_spike    : window içinde N+ HIGH severity log
  - rapid_deny_per_actor   : window içinde aynı actor'dan N+ DENY
  - cross_tenant_attempt   : tenant.mismatch / unapproved_supplier N+ kere
  - unusual_hour_burst     : 09:00-18:00 dışında N+ olay
  - pii_bulk_export        : pii.* kuralı, aynı actor N+ kere
  - rebac_frappe_drift     : Faz 3.5'te gerçek drift detection job ile devreye girer

Cooldown: aynı rule için son alert <= cooldown_minutes ise atla.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import frappe
from frappe.utils import now_datetime

from tradehub_core.services import anomaly_actions


@dataclass
class EvidenceGroup:
	"""Aggregated evidence for a single (actor, tenant) bucket.

	D10: `buyer_org` field eklendi — buyer-side anomaliler (cross-org Order,
	over_budget vb.) için organization scope. Detector grouping fonksiyonları
	evidence log'larından bu alanı propagate eder.
	"""

	actor: str | None
	tenant: str | None
	count: int
	log_ids: list[str]
	window_start: datetime
	window_end: datetime
	buyer_org: str | None = None


def run_detection(now: datetime | None = None) -> dict[str, Any]:
	"""Top-level scheduled entry: evaluate all active rules.

	Returns a summary dict for logs/diagnostics.
	"""
	now = now or now_datetime()
	summary: dict[str, Any] = {"evaluated": 0, "fired": 0, "skipped_cooldown": 0}

	rules = frappe.get_all(
		"Authorization Anomaly Rule",
		filters={"is_active": 1},
		fields=[
			"name",
			"rule_code",
			"rule_name",
			"detection_type",
			"threshold_count",
			"window_minutes",
			"severity_filter",
			"tenant_scope",
			"action_notify",
			"action_suspend_actor",
			"action_disable_tenant",
			"cooldown_minutes",
		],
	)

	for rule in rules:
		summary["evaluated"] += 1

		if _on_cooldown(rule, now):
			summary["skipped_cooldown"] += 1
			continue

		groups = _evaluate_rule(rule, now)
		if not groups:
			continue

		for group in groups:
			alert_name = _create_alert(rule, group, now)
			if alert_name:
				_run_actions(rule, group, alert_name)
				summary["fired"] += 1

	frappe.db.commit()
	return summary


# ---------------------------------------------------------------------------
# Cooldown
# ---------------------------------------------------------------------------


def _on_cooldown(rule: dict, now: datetime) -> bool:
	cooldown = int(rule.get("cooldown_minutes") or 0)
	if cooldown <= 0:
		return False

	last = frappe.db.get_value(
		"Authorization Anomaly Alert",
		{"rule": rule["name"]},
		"triggered_at",
		order_by="triggered_at desc",
	)
	if not last:
		return False

	if isinstance(last, str):
		try:
			last = datetime.fromisoformat(last)
		except ValueError:
			return False

	return (now - last) < timedelta(minutes=cooldown)


# ---------------------------------------------------------------------------
# Per-type evaluators
# ---------------------------------------------------------------------------


def _evaluate_rule(rule: dict, now: datetime) -> list[EvidenceGroup]:
	dtype = rule["detection_type"]
	window_start = now - timedelta(minutes=int(rule["window_minutes"]))

	dispatch = {
		"high_severity_spike": _detect_high_severity_spike,
		"rapid_deny_per_actor": _detect_rapid_deny_per_actor,
		"cross_tenant_attempt": _detect_cross_tenant_attempt,
		"unusual_hour_burst": _detect_unusual_hour_burst,
		"pii_bulk_export": _detect_pii_bulk_export,
		"rebac_frappe_drift": _detect_rebac_drift,
	}
	fn = dispatch.get(dtype)
	if not fn:
		return []

	return fn(rule, window_start, now)


def _common_filters(rule: dict, window_start: datetime, now: datetime) -> dict:
	filters: dict = {"creation": ["between", [window_start, now]]}
	severity = rule.get("severity_filter")
	if severity and severity != "any":
		filters["severity"] = severity
	if rule.get("tenant_scope"):
		filters["tenant"] = rule["tenant_scope"]
	return filters


def _fetch_logs(filters: dict) -> list[dict]:
	# D10: buyer_org field'ı ADL'de Custom Field (v15_5_2). get_all fields'a
	# eklenince yoksa NULL döner — geriye dönük uyumlu.
	return frappe.get_all(
		"Authorization Decision Log",
		filters=filters,
		fields=[
			"name", "actor", "tenant", "buyer_org",
			"decision", "severity", "rule_id", "action",
		],
		limit=10000,
		order_by="creation desc",
	) or []


def _first_buyer_org(entries: list[dict]) -> str | None:
	"""D10: Group içindeki ilk non-null buyer_org'u döndür (Counter mantığı
	overkill; ilk log'da varsa onu kullan)."""
	for e in entries:
		if e.get("buyer_org"):
			return e["buyer_org"]
	return None


def _detect_high_severity_spike(
	rule: dict, window_start: datetime, now: datetime
) -> list[EvidenceGroup]:
	filters = _common_filters(rule, window_start, now)
	filters["severity"] = "HIGH"

	logs = _fetch_logs(filters)
	if len(logs) < int(rule["threshold_count"]):
		return []

	return [
		EvidenceGroup(
			actor=None,
			tenant=rule.get("tenant_scope"),
			count=len(logs),
			log_ids=[log["name"] for log in logs[:50]],
			window_start=window_start,
			window_end=now,
			buyer_org=_first_buyer_org(logs),
		)
	]


def _detect_rapid_deny_per_actor(
	rule: dict, window_start: datetime, now: datetime
) -> list[EvidenceGroup]:
	filters = _common_filters(rule, window_start, now)
	filters["decision"] = "DENY"

	logs = _fetch_logs(filters)
	by_actor: dict[str, list[dict]] = defaultdict(list)
	for log in logs:
		if log.get("actor"):
			by_actor[log["actor"]].append(log)

	groups: list[EvidenceGroup] = []
	threshold = int(rule["threshold_count"])
	for actor, entries in by_actor.items():
		if len(entries) >= threshold:
			groups.append(
				EvidenceGroup(
					actor=actor,
					tenant=(entries[0].get("tenant") if entries else None),
					count=len(entries),
					log_ids=[e["name"] for e in entries[:50]],
					window_start=window_start,
					window_end=now,
					buyer_org=_first_buyer_org(entries),
				)
			)
	return groups


def _detect_cross_tenant_attempt(
	rule: dict, window_start: datetime, now: datetime
) -> list[EvidenceGroup]:
	filters = _common_filters(rule, window_start, now)
	filters["rule_id"] = [
		"in",
		[
			"tenant.mismatch",
			"procurement.unapproved_supplier",
			"L1.tenant.mismatch",
		],
	]
	logs = _fetch_logs(filters)
	by_actor: dict[str, list[dict]] = defaultdict(list)
	for log in logs:
		by_actor[log.get("actor") or "(unknown)"].append(log)

	threshold = int(rule["threshold_count"])
	groups: list[EvidenceGroup] = []
	for actor, entries in by_actor.items():
		if len(entries) >= threshold:
			groups.append(
				EvidenceGroup(
					actor=actor if actor != "(unknown)" else None,
					tenant=entries[0].get("tenant"),
					count=len(entries),
					log_ids=[e["name"] for e in entries[:50]],
					window_start=window_start,
					window_end=now,
					buyer_org=_first_buyer_org(entries),
				)
			)
	return groups


def _detect_unusual_hour_burst(
	rule: dict, window_start: datetime, now: datetime
) -> list[EvidenceGroup]:
	hour = now.hour
	if 9 <= hour < 18:
		return []  # business hours — bu kural devre dışı

	filters = _common_filters(rule, window_start, now)
	logs = _fetch_logs(filters)
	if len(logs) < int(rule["threshold_count"]):
		return []

	return [
		EvidenceGroup(
			actor=None,
			tenant=rule.get("tenant_scope"),
			count=len(logs),
			log_ids=[log["name"] for log in logs[:50]],
			window_start=window_start,
			window_end=now,
			buyer_org=_first_buyer_org(logs),
		)
	]


def _detect_pii_bulk_export(
	rule: dict, window_start: datetime, now: datetime
) -> list[EvidenceGroup]:
	filters = _common_filters(rule, window_start, now)
	filters["rule_id"] = ["like", "pii.%"]

	logs = _fetch_logs(filters)
	by_actor: dict[str, list[dict]] = defaultdict(list)
	for log in logs:
		by_actor[log.get("actor") or "(unknown)"].append(log)

	threshold = int(rule["threshold_count"])
	groups: list[EvidenceGroup] = []
	for actor, entries in by_actor.items():
		if len(entries) >= threshold:
			groups.append(
				EvidenceGroup(
					actor=actor if actor != "(unknown)" else None,
					tenant=entries[0].get("tenant"),
					count=len(entries),
					log_ids=[e["name"] for e in entries[:50]],
					window_start=window_start,
					window_end=now,
					buyer_org=_first_buyer_org(entries),
				)
			)
	return groups


def _detect_rebac_drift(
	rule: dict, window_start: datetime, now: datetime
) -> list[EvidenceGroup]:
	"""Faz 3.5 drift detection job ile devreye girer; şimdilik no-op."""
	return []


# ---------------------------------------------------------------------------
# Alert creation
# ---------------------------------------------------------------------------


def _create_alert(
	rule: dict, group: EvidenceGroup, now: datetime
) -> str | None:
	severity_map = {
		"high_severity_spike": "HIGH",
		"rapid_deny_per_actor": "MEDIUM",
		"cross_tenant_attempt": "HIGH",
		"unusual_hour_burst": "LOW",
		"pii_bulk_export": "HIGH",
		"rebac_frappe_drift": "MEDIUM",
	}
	if group.count >= 3 * int(rule["threshold_count"]):
		severity = "CRITICAL"
	else:
		severity = severity_map.get(rule["detection_type"], "MEDIUM")

	try:
		doc = frappe.new_doc("Authorization Anomaly Alert")
		doc.rule = rule["name"]
		doc.triggered_at = now
		doc.status = "open"
		doc.severity = severity
		doc.actor = group.actor
		doc.tenant = group.tenant
		# D10: buyer_org propagation — Custom Field (v15_5_3); doc.buyer_org
		# attribute setattr ile yazılır (Frappe Document üstünde her zaman
		# geçerli, Custom Field sync olmuşsa DB'ye yazar).
		if group.buyer_org:
			doc.buyer_org = group.buyer_org
		doc.event_count = group.count
		doc.window_start = group.window_start
		doc.window_end = group.window_end
		doc.evidence_log_ids = ",".join(group.log_ids)
		doc.insert(ignore_permissions=True)
		return doc.name
	except Exception as exc:
		frappe.log_error(f"anomaly_detector create_alert failed: {exc}", "Anomaly Detector")
		return None


def _run_actions(rule: dict, group: EvidenceGroup, alert_name: str) -> None:
	actions_taken: list[str] = []

	if rule.get("action_notify"):
		try:
			anomaly_actions.notify_super_admins(alert_name, rule, group)
			actions_taken.append("notify")
		except Exception as exc:
			frappe.log_error(f"notify action failed: {exc}", "Anomaly Actions")

	if rule.get("action_suspend_actor") and group.actor:
		try:
			anomaly_actions.suspend_actor(group.actor, reason=f"anomaly:{rule['rule_code']}")
			actions_taken.append(f"suspend_actor:{group.actor}")
		except Exception as exc:
			frappe.log_error(f"suspend action failed: {exc}", "Anomaly Actions")

	if rule.get("action_disable_tenant") and group.tenant:
		try:
			anomaly_actions.disable_tenant(group.tenant, reason=f"anomaly:{rule['rule_code']}")
			actions_taken.append(f"disable_tenant:{group.tenant}")
		except Exception as exc:
			frappe.log_error(f"disable_tenant action failed: {exc}", "Anomaly Actions")

	if actions_taken:
		try:
			frappe.db.set_value(
				"Authorization Anomaly Alert", alert_name, "action_taken",
				", ".join(actions_taken),
			)
		except Exception as exc:
			frappe.log_error(f"set action_taken failed: {exc}", "Anomaly Detector")
