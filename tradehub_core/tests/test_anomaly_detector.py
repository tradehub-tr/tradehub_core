"""FAZ 3.4 — Anomaly detector unit testleri.

Senaryolar:
  1. high_severity_spike threshold altında → no alert
  2. high_severity_spike threshold aşıldı → alert oluşur
  3. rapid_deny_per_actor — bir actor threshold aşar, diğeri değil → tek alert
  4. cross_tenant_attempt → tetiklenir
  5. unusual_hour_burst — business hours içinde no alert
  6. unusual_hour_burst — off-hour'da tetiklenir
  7. pii_bulk_export
  8. Cooldown — son alert window'unda → skip
  9. Severity escalation to CRITICAL — count >= 3*threshold
 10. Notify action handler çağrılır
 11. Suspend actor action — kullanıcı pasifleştirilir
 12. Inactive rule atlanır

  cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_anomaly_detector
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_RULES: list[dict] = []
_LOGS: list[dict] = []
_ALERTS: list[dict] = []
_USER_FLAGS: dict[str, dict] = {}
_NOTIFIED: list[str] = []
_SUSPENDED: list[str] = []


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Administrator")
	frappe.get_roles = lambda u: ["System Manager"]

	def get_all(doctype, filters=None, pluck=None, fields=None, order_by=None, limit=None, **kwargs):
		if doctype == "Authorization Anomaly Rule":
			rows = [r for r in _RULES if _matches(r, filters)]
			return rows
		if doctype == "Authorization Decision Log":
			rows = [log for log in _LOGS if _matches(log, filters)]
			rows.sort(key=lambda r: r.get("creation"), reverse=True)
			return rows[: (limit or len(rows))]
		if doctype == "Has Role":
			# Mock super admin lookup
			return ["admin@firm.com"]
		return []

	def db_get_value(doctype, filters=None, fieldname=None, order_by=None, **kwargs):
		if doctype == "Authorization Anomaly Alert" and isinstance(filters, dict):
			rule = filters.get("rule")
			matches = [a for a in _ALERTS if a.get("rule") == rule]
			if not matches:
				return None
			matches.sort(key=lambda a: a.get("triggered_at"), reverse=True)
			return matches[0].get(fieldname) if fieldname else matches[0].get("name")
		if doctype == "User":
			return _USER_FLAGS.get(filters, {}).get(fieldname)
		return None

	def db_set_value(doctype, name, fieldname, value):
		if doctype == "Authorization Anomaly Alert":
			for a in _ALERTS:
				if a["name"] == name:
					a[fieldname] = value
					return
		if doctype == "User":
			_USER_FLAGS.setdefault(name, {})[fieldname] = value
			if fieldname == "enabled" and value == 0:
				_SUSPENDED.append(name)

	def db_exists(doctype, name=None):
		if doctype == "DocType":
			return True
		if doctype == "User":
			return True
		return True

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		set_value=db_set_value,
		exists=db_exists,
		commit=lambda: None,
	)
	frappe.get_all = get_all

	def new_doc(doctype):
		ns = SimpleNamespace()
		ns.doctype = doctype
		ns.name = None

		def _insert(*a, **kw):
			# Auto-name
			if doctype == "Authorization Anomaly Alert":
				ns.name = f"AAA-{len(_ALERTS):04d}"
				_ALERTS.append(dict(ns.__dict__))
			elif doctype == "Notification Log":
				_NOTIFIED.append(ns.for_user if hasattr(ns, "for_user") else "?")
			return ns

		ns.insert = _insert
		return ns

	frappe.new_doc = new_doc

	def get_doc(doctype, name):
		if doctype == "Authorization Anomaly Alert":
			for a in _ALERTS:
				if a["name"] == name:
					ns = SimpleNamespace(**a)
					ns.save = lambda **kw: None
					return ns
		return SimpleNamespace()

	frappe.get_doc = get_doc

	def sendmail(**kwargs):
		_NOTIFIED.extend(kwargs.get("recipients", []))

	frappe.sendmail = sendmail

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "ValidationError"):

		class ValidationError(Exception):
			pass

		frappe.ValidationError = ValidationError
	frappe.throw = lambda msg, exc=Exception: (_ for _ in ()).throw(
		exc(msg) if isinstance(exc, type) else Exception(msg)
	)
	frappe.log_error = lambda *a, **kw: None
	frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)

	# frappe.utils.now_datetime — testte override edilebilir
	frappe.utils = types.ModuleType("frappe.utils")
	frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 14, 0, 0)
	frappe.utils.cint = int
	frappe.utils.flt = float
	sys.modules["frappe.utils"] = frappe.utils

	# audit stub
	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda **kw: "ADL"
	audit_mod.log_role_change = lambda **kw: "RCL"
	sys.modules["tradehub_core.audit"] = audit_mod


_install_frappe_stub()


def _matches(record: dict, filters: dict | None) -> bool:
	if not filters:
		return True
	for k, v in filters.items():
		val = record.get(k)
		if isinstance(v, list) and len(v) == 2 and v[0] == "between":
			start, end = v[1]
			if not (start <= val <= end):
				return False
		elif isinstance(v, list) and v[0] == "in":
			if val not in v[1]:
				return False
		elif isinstance(v, list) and v[0] == "like":
			pattern = v[1].replace("%", "")
			if pattern not in (val or ""):
				return False
		elif isinstance(v, list) and v[0] == "not in":
			if val in v[1]:
				return False
		else:
			if val != v:
				return False
	return True


def _reset_state():
	_RULES.clear()
	_LOGS.clear()
	_ALERTS.clear()
	_USER_FLAGS.clear()
	_NOTIFIED.clear()
	_SUSPENDED.clear()
	_install_frappe_stub()


os.environ.setdefault("REBAC_BASE_URL", "http://test:8080")

from tradehub_core.services import anomaly_detector as det  # noqa: E402


def _add_log(creation: datetime, **fields):
	log = {
		"name": f"ADL-{len(_LOGS):04d}",
		"creation": creation,
		"actor": fields.get("actor"),
		"tenant": fields.get("tenant"),
		"decision": fields.get("decision", "ALLOW"),
		"severity": fields.get("severity", "LOW"),
		"rule_id": fields.get("rule_id", "test"),
		"action": fields.get("action", "test"),
	}
	_LOGS.append(log)
	return log


def _add_rule(**fields):
	rule = {
		"name": fields.get("rule_code", f"AAR-{len(_RULES):04d}"),
		"rule_code": fields.get("rule_code", "TEST_RULE"),
		"rule_name": fields.get("rule_name", "Test Rule"),
		"detection_type": fields["detection_type"],
		"threshold_count": fields.get("threshold_count", 5),
		"window_minutes": fields.get("window_minutes", 5),
		"severity_filter": fields.get("severity_filter", "any"),
		"is_active": fields.get("is_active", 1),
		"cooldown_minutes": fields.get("cooldown_minutes", 0),
		"action_notify": fields.get("action_notify", 1),
		"action_suspend_actor": fields.get("action_suspend_actor", 0),
		"action_disable_tenant": fields.get("action_disable_tenant", 0),
		"tenant_scope": fields.get("tenant_scope"),
	}
	_RULES.append(rule)
	return rule


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class HighSeveritySpikeTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="HIGH_SPIKE",
			detection_type="high_severity_spike",
			threshold_count=3,
			window_minutes=5,
			severity_filter="HIGH",
		)

	def test_below_threshold_no_alert(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(2):
			_add_log(now - timedelta(minutes=1), severity="HIGH")
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 0)

	def test_threshold_exceeded_creates_alert(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(5):
			_add_log(now - timedelta(minutes=1), severity="HIGH")
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 1)
		self.assertEqual(_ALERTS[0]["event_count"], 5)


class RapidDenyTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="RAPID_DENY", detection_type="rapid_deny_per_actor", threshold_count=3, window_minutes=1
		)

	def test_one_actor_above_threshold_one_below(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(5):
			_add_log(now, decision="DENY", actor="bad@x.com", tenant="ACME")
		for _ in range(2):
			_add_log(now, decision="DENY", actor="ok@x.com", tenant="ACME")

		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 1)
		self.assertEqual(_ALERTS[0]["actor"], "bad@x.com")


class CrossTenantTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="CROSS_T", detection_type="cross_tenant_attempt", threshold_count=2, window_minutes=5
		)

	def test_triggers_on_threshold(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(3):
			_add_log(now, actor="probe@x.com", rule_id="tenant.mismatch")
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 1)
		self.assertEqual(_ALERTS[0]["actor"], "probe@x.com")


class UnusualHourTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="OFF_HOUR", detection_type="unusual_hour_burst", threshold_count=2, window_minutes=15
		)

	def test_business_hour_no_alert(self):
		now = datetime(2026, 5, 21, 11, 0, 0)
		for _ in range(5):
			_add_log(now)
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 0)

	def test_off_hour_alert(self):
		now = datetime(2026, 5, 21, 23, 0, 0)
		for _ in range(5):
			_add_log(now)
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 1)


class PIIBulkTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="PII_BULK", detection_type="pii_bulk_export", threshold_count=3, window_minutes=10
		)

	def test_triggers(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(5):
			_add_log(now, actor="scraper@x.com", rule_id="pii.access.allow")
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 1)


class CooldownTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="C_RULE",
			detection_type="high_severity_spike",
			threshold_count=2,
			window_minutes=5,
			severity_filter="HIGH",
			cooldown_minutes=30,
		)

	def test_recent_alert_skips(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		# Önceki alert (10 dk önce)
		_ALERTS.append(
			{
				"name": "AAA-EXISTING",
				"rule": "C_RULE",
				"triggered_at": now - timedelta(minutes=10),
			}
		)
		for _ in range(3):
			_add_log(now, severity="HIGH")
		summary = det.run_detection(now=now)
		self.assertEqual(summary["fired"], 0)
		self.assertEqual(summary["skipped_cooldown"], 1)


class SeverityEscalationTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="ESC",
			detection_type="high_severity_spike",
			threshold_count=3,
			window_minutes=5,
			severity_filter="HIGH",
		)

	def test_critical_escalation(self):
		# count = 10 > 3 * threshold (=9) → CRITICAL
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(10):
			_add_log(now, severity="HIGH")
		det.run_detection(now=now)
		self.assertEqual(_ALERTS[0]["severity"], "CRITICAL")


class ActionTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="A_NOTIFY",
			detection_type="rapid_deny_per_actor",
			threshold_count=2,
			window_minutes=5,
			action_notify=1,
			action_suspend_actor=1,
		)

	def test_notify_and_suspend(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(5):
			_add_log(now, decision="DENY", actor="bad@x.com")
		det.run_detection(now=now)

		self.assertEqual(len(_ALERTS), 1)
		# Notify çalışmış olmalı (Has Role → admin@firm.com)
		self.assertGreater(len(_NOTIFIED), 0)
		# Suspend çalışmış olmalı
		self.assertIn("bad@x.com", _SUSPENDED)


class InactiveRuleTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_add_rule(
			rule_code="DEAD",
			detection_type="high_severity_spike",
			threshold_count=1,
			window_minutes=5,
			severity_filter="HIGH",
			is_active=0,
		)

	def test_inactive_skipped(self):
		now = datetime(2026, 5, 21, 14, 0, 0)
		for _ in range(5):
			_add_log(now, severity="HIGH")
		det.run_detection(now=now)
		self.assertEqual(len(_ALERTS), 0)


if __name__ == "__main__":
	unittest.main()
