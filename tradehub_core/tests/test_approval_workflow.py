"""FAZ 2.5 — Approval workflow + state machine testleri.

tradehub_core.services.approval_workflow içindeki:
  - find_matching_rule (amount range + filtreler)
  - start_approval / approve / reject (state machine)
  - L1 → Approved (max_level=1)
  - L1 → Pending L2 → Approved (max_level=2)
  - Reject (her seviyede)
  - Cross-tenant approver koruması

için saf-Python testler. Frappe stub'lanır.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_approval_workflow
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DB: dict = {}  # Mock DB: ("get_value"/"exists"/"get_all", ...) → result
_DOCS: dict = {}  # Mock doc store: (doctype, name) → SimpleNamespace
_ENQUEUED: list = []


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="Administrator")
	frappe.get_roles = lambda u: _DB.get(("roles", u), ["System Manager"])

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(filters), str(fieldname))
		return _DB.get(key)

	def db_exists(doctype, filters=None):
		key = ("exists", doctype, str(filters))
		return _DB.get(key, False)

	def get_all(doctype, filters=None, fields=None, pluck=None, order_by=None, **kwargs):
		key = ("get_all", doctype, str(filters), str(fields), pluck)
		return _DB.get(key, [])

	def db_sql(query, values=None, as_dict=False, **kwargs):
		"""SQL mock — sadece HOTFIX-4 FOR UPDATE lock'larını destekler.

		`SELECT ... FROM tabOrder Approval WHERE order=... FOR UPDATE` →
		mevcut active approval bulunmuyor (yeni order) varsay → [] döner.

		`SELECT ... FROM tabOrder Approval WHERE name=... FOR UPDATE` →
		approval_name geçerli kabul edilir → dummy row döner.
		"""
		q = (query or "").strip().lower()
		if "from `taborder approval`" not in q:
			return []
		if "where `order` =" in q or "where `order`=" in q:
			return []  # no active approval (new flow)
		if "where name =" in q:
			approval_name = values[0] if isinstance(values, tuple | list) else values
			row = {"name": approval_name, "status": "Pending L1", "current_level": 1, "max_level": 1}
			return [row] if as_dict else [(approval_name,)]
		return []

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=db_exists,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		commit=lambda: None,
		sql=db_sql,
	)
	frappe.get_all = get_all

	def get_doc(*args, **kwargs):
		if len(args) == 1 and isinstance(args[0], dict):
			# Yeni doc oluştur
			data = args[0]
			doctype = data.get("doctype")
			data.setdefault("name", None)  # autoname placeholder
			doc = SimpleNamespace(**data)
			doc.flags = SimpleNamespace()
			doc.is_new = lambda: doc.name is None
			doc.is_terminal = lambda: (
				getattr(doc, "status", "")
				in (
					"Approved",
					"Rejected",
					"Timeout Rejected",
				)
			)
			doc.get = lambda field, default=None: getattr(doc, field, default)

			def _append(field, child_data):
				existing = getattr(doc, field, None) or []
				child = SimpleNamespace(**child_data)
				existing.append(child)
				setattr(doc, field, existing)

			doc.append = _append

			def _insert(ignore_permissions=False, **kw):
				if not doc.name:
					doc.name = f"{doctype}-{len(_DOCS) + 1:06d}"
				_DOCS[(doctype, doc.name)] = doc
				return doc

			doc.insert = _insert

			def _save(ignore_permissions=False, **kw):
				_DOCS[(doctype, doc.name)] = doc

			doc.save = _save

			# Approval-rule specific helpers
			if doctype == "Approval Rule":

				def get_approvers_at_level(level):
					return [
						r.approver
						for r in sorted(
							[r for r in (doc.approvers or []) if r.approver_level == level],
							key=lambda r: getattr(r, "sequence", 0) or 0,
						)
					]

				def max_level():
					levels = [r.approver_level for r in (doc.approvers or [])]
					return max(levels) if levels else 0

				doc.get_approvers_at_level = get_approvers_at_level
				doc.max_level = max_level

			return doc
		# Mevcut doc'u getir
		doctype, name = args
		key = (doctype, name)
		if key not in _DOCS:
			raise Exception(f"{doctype} '{name}' not found")
		return _DOCS[key]

	frappe.get_doc = get_doc

	def _enqueue(method, queue="short", **kwargs):
		_ENQUEUED.append({"method": method, **kwargs})

	frappe.enqueue = _enqueue

	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s
	if not hasattr(frappe, "PermissionError"):

		class PermissionError(Exception):
			pass

		frappe.PermissionError = PermissionError
	if not hasattr(frappe, "throw"):

		def _throw(msg, exc=Exception):
			raise (exc(msg) if isinstance(exc, type) else Exception(msg))

		frappe.throw = _throw
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
	if not hasattr(frappe, "logger"):
		frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)
	if not hasattr(frappe, "sendmail"):
		frappe.sendmail = lambda **kw: None

	if not hasattr(frappe, "utils") or not hasattr(frappe.utils, "now_datetime"):
		frappe.utils = types.ModuleType("frappe.utils")
		from datetime import datetime, timedelta

		frappe.utils.cint = int
		frappe.utils.flt = float
		frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 12, 0, 0)
		frappe.utils.add_days = lambda dt, days: (dt or datetime.now()) + timedelta(days=days)
		frappe.utils.get_url = lambda: "https://test.local"
		sys.modules["frappe.utils"] = frappe.utils

	if not hasattr(frappe, "whitelist"):

		def _whitelist(*args, **kwargs):
			def _decorator(fn):
				return fn

			if args and callable(args[0]):
				return args[0]
			return _decorator

		frappe.whitelist = _whitelist


_install_frappe_stub()


def _reset_state():
	_DB.clear()
	_DOCS.clear()
	_ENQUEUED.clear()
	_install_frappe_stub()


from tradehub_core.services import approval_workflow as wf  # noqa: E402


def _make_rule(name, org, min_a, max_a, l1_users, l2_users=None, currency="EUR"):
	"""Mock Approval Rule oluştur."""
	approvers = [
		SimpleNamespace(approver=u, approver_level=1, sequence=i, idx=i) for i, u in enumerate(l1_users)
	] + [
		SimpleNamespace(approver=u, approver_level=2, sequence=i, idx=i + 10)
		for i, u in enumerate(l2_users or [])
	]
	rule = SimpleNamespace(
		name=name,
		organization=org,
		min_amount=min_a,
		max_amount=max_a,
		currency=currency,
		approvers=approvers,
		category_filter=None,
		supplier_filter=None,
		priority=100,
		is_active=1,
		approval_timeout_days=7,
	)
	# .get() method (Frappe Document gibi)
	rule.get = lambda field, default=None, _r=rule: getattr(_r, field, default)
	rule.get_approvers_at_level = lambda level, _rule=rule: [
		r.approver for r in (_rule.approvers or []) if r.approver_level == level
	]
	rule.max_level = lambda _rule=rule: max([r.approver_level for r in (_rule.approvers or [])], default=0)
	_DOCS[("Approval Rule", name)] = rule
	return rule


def _make_order(name, buyer, total, currency="EUR", seller_profile="STORE-A"):
	"""Mock Order oluştur."""
	order = SimpleNamespace(
		name=name,
		buyer=buyer,
		owner=buyer,
		total=total,
		currency=currency,
		seller_profile=seller_profile,
		status="Ödeme Bekleniyor",
	)
	order.get = lambda field, default=None: getattr(order, field, default)
	order.save = lambda ignore_permissions=False, **kw: None
	order.db_set = lambda field, value: setattr(order, field, value)
	_DOCS[("Order", name)] = order
	return order


# ---------------------------------------------------------------------------
# find_matching_rule
# ---------------------------------------------------------------------------


class FindMatchingRuleTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_no_organization_returns_none(self):
		self.assertIsNone(wf.find_matching_rule("", 1000))

	def test_amount_below_min_no_match(self):
		_make_rule("AR-1", "acme", min_a=1000, max_a=5000, l1_users=["mehmet@x.com"])
		_DB[
			(
				"get_all",
				"Approval Rule",
				"{'organization': ['in', ['acme']], 'is_active': 1}",
				str(
					[
						"name",
						"organization",
						"min_amount",
						"max_amount",
						"category_filter",
						"supplier_filter",
						"priority",
					]
				),
				None,
			)
		] = [
			{
				"name": "AR-1",
				"organization": "acme",
				"min_amount": 1000,
				"max_amount": 5000,
				"category_filter": None,
				"supplier_filter": None,
				"priority": 100,
			}
		]
		# 500 < 1000 → match yok
		self.assertIsNone(wf.find_matching_rule("acme", 500))

	def test_amount_in_range_matches(self):
		_DB[
			(
				"get_all",
				"Approval Rule",
				"{'organization': ['in', ['acme']], 'is_active': 1}",
				str(
					[
						"name",
						"organization",
						"min_amount",
						"max_amount",
						"category_filter",
						"supplier_filter",
						"priority",
					]
				),
				None,
			)
		] = [
			{
				"name": "AR-1",
				"organization": "acme",
				"min_amount": 1000,
				"max_amount": 5000,
				"category_filter": None,
				"supplier_filter": None,
				"priority": 100,
			}
		]
		# 3000 ∈ [1000, 5000) → match
		self.assertEqual(wf.find_matching_rule("acme", 3000), "AR-1")

	def test_amount_at_max_no_match(self):
		"""max_amount exclusive."""
		_DB[
			(
				"get_all",
				"Approval Rule",
				"{'organization': ['in', ['acme']], 'is_active': 1}",
				str(
					[
						"name",
						"organization",
						"min_amount",
						"max_amount",
						"category_filter",
						"supplier_filter",
						"priority",
					]
				),
				None,
			)
		] = [
			{
				"name": "AR-1",
				"organization": "acme",
				"min_amount": 1000,
				"max_amount": 5000,
				"category_filter": None,
				"supplier_filter": None,
				"priority": 100,
			}
		]
		# 5000 = max_amount → match yok (exclusive)
		self.assertIsNone(wf.find_matching_rule("acme", 5000))

	def test_priority_wins(self):
		_DB[
			(
				"get_all",
				"Approval Rule",
				"{'organization': ['in', ['acme']], 'is_active': 1}",
				str(
					[
						"name",
						"organization",
						"min_amount",
						"max_amount",
						"category_filter",
						"supplier_filter",
						"priority",
					]
				),
				None,
			)
		] = [
			{
				"name": "AR-PRIORITY",
				"organization": "acme",
				"min_amount": 0,
				"max_amount": None,
				"category_filter": None,
				"supplier_filter": None,
				"priority": 10,  # lower = first
			},
			{
				"name": "AR-DEFAULT",
				"organization": "acme",
				"min_amount": 0,
				"max_amount": None,
				"category_filter": None,
				"supplier_filter": None,
				"priority": 100,
			},
		]
		self.assertEqual(wf.find_matching_rule("acme", 1000), "AR-PRIORITY")


# ---------------------------------------------------------------------------
# start_approval / approve / reject state machine
# ---------------------------------------------------------------------------


class StateMachineTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		sys.modules["frappe"].session.user = "Administrator"
		_DB[("roles", "Administrator")] = ["System Manager"]

	def test_single_level_approve_terminal(self):
		"""max_level=1 → L1 onay → Approved (terminal)."""
		_make_order("ORD-1", "ayse@acme.com", total=1500)
		_make_rule("AR-1", "acme", 1000, 5000, l1_users=["can@acme.com"])

		# Mock: buyer'ın organization'ı
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-1", "AR-1")
		approval = _DOCS[("Order Approval", approval_name)]
		self.assertEqual(approval.status, "Pending L1")

		# can@acme.com onaylar
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1"]

		new_status = wf.approve(approval_name)
		self.assertEqual(new_status, "Approved")
		self.assertEqual(approval.status, "Approved")

	def test_two_level_approve_flow(self):
		"""max_level=2 → L1 onay → Pending L2 → L2 onay → Approved."""
		_make_order("ORD-2", "ayse@acme.com", total=10000)
		_make_rule(
			"AR-2",
			"acme",
			5000,
			None,
			l1_users=["can@acme.com"],
			l2_users=["demet@acme.com"],
		)
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-2", "AR-2")
		approval = _DOCS[("Order Approval", approval_name)]
		self.assertEqual(approval.status, "Pending L1")
		self.assertEqual(approval.max_level, 2)

		# L1 onay
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1"]
		status = wf.approve(approval_name, comment="L1 onay")
		self.assertEqual(status, "Pending L2")
		self.assertEqual(approval.current_level, 2)

		# L2 onay (Demet)
		sys.modules["frappe"].session.user = "demet@acme.com"
		_DB[("roles", "demet@acme.com")] = ["Buyer Approver L2"]
		status = wf.approve(approval_name, comment="CFO onay")
		self.assertEqual(status, "Approved")

	def test_reject_at_l1(self):
		"""L1 reject → terminal Rejected."""
		_make_order("ORD-3", "ayse@acme.com", total=2000)
		_make_rule("AR-3", "acme", 1000, 5000, l1_users=["can@acme.com"])
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-3", "AR-3")
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1"]

		status = wf.reject(approval_name, reason="Bütçe yok")
		self.assertEqual(status, "Rejected")

		approval = _DOCS[("Order Approval", approval_name)]
		self.assertEqual(approval.rejection_reason, "Bütçe yok")

	def test_unauthorized_approver_rejected(self):
		"""Yetkisiz user onaylayamaz."""
		_make_order("ORD-4", "ayse@acme.com", total=2000)
		_make_rule("AR-4", "acme", 0, None, l1_users=["can@acme.com"])
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-4", "AR-4")

		# Başka user onaylamaya çalışır
		sys.modules["frappe"].session.user = "rando@x.com"
		_DB[("roles", "rando@x.com")] = ["Buyer"]
		with self.assertRaises(Exception):
			wf.approve(approval_name)

	def test_reject_without_reason_rejected(self):
		_make_order("ORD-5", "ayse@acme.com", total=2000)
		_make_rule("AR-5", "acme", 0, None, l1_users=["can@acme.com"])
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-5", "AR-5")
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1"]

		with self.assertRaises(Exception):
			wf.reject(approval_name, reason="")

	def test_double_approve_rejected(self):
		"""Terminal state'te tekrar approve → hata."""
		_make_order("ORD-6", "ayse@acme.com", total=1500)
		_make_rule("AR-6", "acme", 0, None, l1_users=["can@acme.com"])
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-6", "AR-6")
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1"]

		wf.approve(approval_name)  # 1st: Approved
		# 2nd: zaten terminal
		with self.assertRaises(Exception):
			wf.approve(approval_name)

	def test_self_approval_rejected(self):
		"""#E1 — Talep sahibi kendi siparişini onaylayamaz (görev ayrılığı)."""
		# Order sahibi = can@acme.com; aynı zamanda L1 approver.
		_make_order("ORD-7", "can@acme.com", total=1500)
		_make_rule("AR-7", "acme", 0, None, l1_users=["can@acme.com"])
		_DB[("get_value", "User", "can@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-7", "AR-7")
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1"]

		with self.assertRaises(Exception):
			wf.approve(approval_name)

	def test_l1_approver_cannot_approve_l2(self):
		"""#E1 — Level 1'i onaylayan kişi Level 2'yi onaylayamaz."""
		_make_order("ORD-8", "ayse@acme.com", total=10000)
		# Aynı kişi (can) hem L1 hem L2 approver.
		_make_rule(
			"AR-8", "acme", 5000, None, l1_users=["can@acme.com"], l2_users=["can@acme.com"]
		)
		_DB[("get_value", "User", "ayse@acme.com", "tradehub_parent_organization")] = "acme"

		approval_name = wf.start_approval("ORD-8", "AR-8")
		sys.modules["frappe"].session.user = "can@acme.com"
		_DB[("roles", "can@acme.com")] = ["Buyer Approver L1", "Buyer Approver L2"]
		status = wf.approve(approval_name, comment="L1")
		self.assertEqual(status, "Pending L2")

		# can L2'yi onaylamaya çalışır → SoD reddi
		with self.assertRaises(Exception):
			wf.approve(approval_name, comment="L2 self")


if __name__ == "__main__":
	unittest.main()
