"""FAZ 3.5 — Delegation + Owner Transfer testleri.

Delegation:
  1. create_delegation → pending kayıt
  2. self delegation reddedilir
  3. starts_at >= ends_at reddedilir
  4. activate → role atanır + temporary_role_until set
  5. revoke → role kaldırılır
  6. expire_overdue → ends_at geçmiş aktif delegation'lar expired

Owner Transfer:
  7. create_transfer non-co-owner reddedilir
  8. confirm_by_current_owner — sadece current owner
  9. approve_by_super_admin — sadece system manager
 10. force transfer one-step
 11. reject

  cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_delegation
"""

from __future__ import annotations

import os
import sys
import types
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


_DB: dict = {}
_DOCS: dict[str, dict] = {}
_USERS: dict[str, dict] = {}
_AUDIT_LOGS: list[dict] = []
_ROLE_CHANGES: list[dict] = []


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	frappe.session = SimpleNamespace(user="admin@firm.com")
	frappe.get_roles = lambda u: _USERS.get(u, {}).get("roles", ["System Manager"])

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		if isinstance(filters, str):
			# Lookup by name
			if doctype == "User":
				return _USERS.get(filters, {}).get(fieldname)
			doc = _DOCS.get(filters)
			if doc:
				val = (
					doc.get(fieldname)
					if not isinstance(fieldname, list)
					else {f: doc.get(f) for f in fieldname}
				)
				return val
			return None
		# Filter dict
		for name, doc in _DOCS.items():
			if doctype == doc.get("doctype") and all(doc.get(k) == v for k, v in filters.items()):
				return doc.get(fieldname) if fieldname else name
		return None

	def db_set_value(doctype, name, fieldname, value):
		if doctype == "User":
			_USERS.setdefault(name, {})[fieldname] = value
			return
		if name in _DOCS:
			_DOCS[name][fieldname] = value

	def db_exists(doctype, name=None):
		if doctype == "User":
			return name in _USERS
		if doctype == "DocType":
			return True
		return name in _DOCS

	def has_column(table, column):
		return True

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		set_value=db_set_value,
		exists=db_exists,
		has_column=has_column,
		commit=lambda: None,
	)

	def get_all(doctype, filters=None, pluck=None, fields=None, order_by=None, **kwargs):
		rows = [d for d in _DOCS.values() if d.get("doctype") == doctype]
		if filters:

			def _match(d):
				for k, v in filters.items():
					val = d.get(k)
					if isinstance(v, list) and v[0] == "<=":
						if not val or val > v[1]:
							return False
					elif isinstance(v, list) and v[0] == "!=":
						if val == v[1]:
							return False
					elif val != v:
						return False
				return True

			rows = [d for d in rows if _match(d)]
		if pluck:
			return [d.get(pluck) for d in rows]
		return rows

	frappe.get_all = get_all

	def new_doc(doctype):
		ns = SimpleNamespace()
		ns.doctype = doctype
		ns.name = None
		ns.roles = []

		def _append(table, value):
			lst = getattr(ns, table, [])
			lst.append(SimpleNamespace(**value) if isinstance(value, dict) else value)
			setattr(ns, table, lst)

		def _insert(*a, **kw):
			if doctype == "Role Delegation":
				ns.name = (
					f"RD-{len([d for d in _DOCS.values() if d.get('doctype') == 'Role Delegation']):04d}"
				)
			elif doctype == "Owner Transfer Request":
				ns.name = f"OTR-{len([d for d in _DOCS.values() if d.get('doctype') == 'Owner Transfer Request']):04d}"
			data = {k: v for k, v in ns.__dict__.items() if not k.startswith("_")}
			data["doctype"] = doctype
			_DOCS[ns.name] = data
			return ns

		ns.append = _append
		ns.insert = _insert
		ns.save = lambda *a, **kw: (
			_DOCS.update(
				{
					ns.name: {
						**_DOCS.get(ns.name, {}),
						**{k: v for k, v in ns.__dict__.items() if not k.startswith("_")},
					}
				}
			)
			if ns.name
			else None
		)
		return ns

	frappe.new_doc = new_doc

	def get_doc(doctype, name):
		data = _DOCS.get(name, {})
		ns = SimpleNamespace(**data)
		ns.doctype = doctype
		ns.name = name
		# User için roles
		if doctype == "User":
			user_data = _USERS.get(name, {})
			ns.roles = [SimpleNamespace(role=r) for r in user_data.get("role_names", [])]
			ns.temporary_role_until = user_data.get("temporary_role_until")

			def _user_append(table, value):
				lst = list(getattr(ns, table, []))
				if isinstance(value, dict):
					lst.append(SimpleNamespace(**value))
				else:
					lst.append(value)
				setattr(ns, table, lst)

			ns.append = _user_append

			def _save(*a, **kw):
				_USERS[name] = {
					**user_data,
					"role_names": [r.role for r in ns.roles],
					"temporary_role_until": getattr(ns, "temporary_role_until", None),
				}

			ns.save = _save
		else:

			def _save(*a, **kw):
				updated = {k: v for k, v in ns.__dict__.items() if not k.startswith("_")}
				updated["doctype"] = doctype
				_DOCS[name] = updated

			ns.save = _save
		return ns

	frappe.get_doc = get_doc

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

	def _throw(msg, exc=Exception):
		if isinstance(exc, type):
			raise exc(msg)
		raise Exception(msg)

	frappe.throw = _throw
	frappe.log_error = lambda *a, **kw: None
	frappe.logger = lambda: SimpleNamespace(info=lambda *a, **kw: None)

	frappe.utils = types.ModuleType("frappe.utils")
	frappe.utils.now_datetime = lambda: datetime(2026, 5, 21, 14, 0, 0)
	frappe.utils.cint = int
	frappe.utils.flt = float
	sys.modules["frappe.utils"] = frappe.utils

	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.log_decision = lambda **kw: _AUDIT_LOGS.append(dict(kw)) or "ADL"
	audit_mod.log_role_change = lambda **kw: _ROLE_CHANGES.append(dict(kw)) or "RCL"
	sys.modules["tradehub_core.audit"] = audit_mod


_install_frappe_stub()


def _reset_state():
	_DB.clear()
	_DOCS.clear()
	_USERS.clear()
	_AUDIT_LOGS.clear()
	_ROLE_CHANGES.clear()
	_install_frappe_stub()


os.environ.setdefault("REBAC_BASE_URL", "http://test:8080")


from tradehub_core.services import delegation_service as dele  # noqa: E402
from tradehub_core.services import owner_transfer as ot  # noqa: E402

# ---------------------------------------------------------------------------
# Delegation tests
# ---------------------------------------------------------------------------


class DelegationCreateTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		# #E4 — delegator delege ettiği role sahip olmalı (get_roles "roles"'u okur).
		_USERS["a@x.com"] = {
			"role_names": ["Buyer Requisitioner"],
			"roles": ["Buyer Approver L1", "Buyer Requisitioner"],
		}
		_USERS["b@x.com"] = {"role_names": []}

	def test_create_pending(self):
		name = dele.create_delegation(
			delegator="a@x.com",
			delegate="b@x.com",
			role="Buyer Approver L1",
			tenant="ACME",
			starts_at=datetime(2026, 5, 21, 10),
			ends_at=datetime(2026, 5, 28, 18),
			reason="vacation",
		)
		self.assertIn("RD-", name)
		self.assertEqual(_DOCS[name]["status"], "pending")

	def test_self_delegation_rejected(self):
		with self.assertRaises(Exception):
			dele.create_delegation(
				delegator="a@x.com",
				delegate="a@x.com",
				role="X",
				tenant="ACME",
				starts_at=datetime(2026, 5, 21),
				ends_at=datetime(2026, 5, 22),
			)

	def test_invalid_dates_rejected(self):
		with self.assertRaises(Exception):
			dele.create_delegation(
				delegator="a@x.com",
				delegate="b@x.com",
				role="X",
				tenant="ACME",
				starts_at=datetime(2026, 5, 22),
				ends_at=datetime(2026, 5, 21),
			)


class DelegationLifecycleTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		# #E4 — delegator delege ettiği role sahip olmalı (get_roles "roles"'u okur).
		_USERS["a@x.com"] = {
			"role_names": ["Buyer Requisitioner"],
			"roles": ["Buyer Approver L1", "Buyer Requisitioner"],
		}
		_USERS["b@x.com"] = {"role_names": []}

	def test_activate_assigns_role(self):
		name = dele.create_delegation(
			"a@x.com",
			"b@x.com",
			"Buyer Approver L1",
			"ACME",
			datetime(2026, 5, 21, 10),
			datetime(2026, 5, 28, 18),
		)
		dele.activate_delegation(name)
		self.assertEqual(_DOCS[name]["status"], "active")
		self.assertIn("Buyer Approver L1", _USERS["b@x.com"]["role_names"])
		self.assertEqual(_USERS["b@x.com"]["temporary_role_until"], datetime(2026, 5, 28, 18))

	def test_revoke_removes_role(self):
		name = dele.create_delegation(
			"a@x.com",
			"b@x.com",
			"Buyer Approver L1",
			"ACME",
			datetime(2026, 5, 21, 10),
			datetime(2026, 5, 28, 18),
		)
		dele.activate_delegation(name)
		dele.revoke_delegation(name, reason="early_return")
		self.assertEqual(_DOCS[name]["status"], "revoked")
		self.assertNotIn("Buyer Approver L1", _USERS["b@x.com"]["role_names"])

	def test_expire_overdue(self):
		name = dele.create_delegation(
			"a@x.com",
			"b@x.com",
			"Buyer Approver L1",
			"ACME",
			datetime(2026, 5, 20, 10),
			datetime(2026, 5, 21, 9),  # past
		)
		dele.activate_delegation(name)

		summary = dele.expire_overdue_delegations(now=datetime(2026, 5, 21, 14, 0, 0))
		self.assertEqual(summary["expired"], 1)
		self.assertEqual(_DOCS[name]["status"], "expired")
		self.assertNotIn("Buyer Approver L1", _USERS["b@x.com"]["role_names"])

	def test_own_role_invariant(self):
		"""#E4 — delegator sahip olmadığı rolü delege edemez."""
		# a@x.com yalnız Buyer Approver L1 + Requisitioner'a sahip; L2 yok.
		with self.assertRaises(Exception):
			dele.create_delegation(
				"a@x.com",
				"b@x.com",
				"Buyer Approver L2",  # sahip değil
				"ACME",
				datetime(2026, 5, 21, 10),
				datetime(2026, 5, 28, 18),
			)

	def test_chain_redelegation_rejected(self):
		"""#E2 — delege edilmiş bir rol yeniden delege edilemez (zincir yasak)."""
		# b@x.com'a Buyer Approver L1 aktif delegation'la verilmiş olsun.
		name = dele.create_delegation(
			"a@x.com", "b@x.com", "Buyer Approver L1", "ACME",
			datetime(2026, 5, 21, 10), datetime(2026, 5, 28, 18),
		)
		dele.activate_delegation(name)
		# b artık rolü get_roles'ta da görsün (delegated).
		_USERS["b@x.com"]["roles"] = ["Buyer Approver L1"]
		# b bu rolü c'ye yeniden delege edemez.
		with self.assertRaises(Exception):
			dele.create_delegation(
				"b@x.com", "c@x.com", "Buyer Approver L1", "ACME",
				datetime(2026, 5, 21, 10), datetime(2026, 5, 28, 18),
			)

	def test_activate_before_starts_at_rejected(self):
		"""#E3 — starts_at gelecekteyse aktive edilemez (now=14:00)."""
		name = dele.create_delegation(
			"a@x.com", "b@x.com", "Buyer Approver L1", "ACME",
			datetime(2026, 5, 25, 10), datetime(2026, 5, 28, 18),  # gelecekte başlar
		)
		with self.assertRaises(Exception):
			dele.activate_delegation(name)

	def test_activate_cross_tenant_rejected(self):
		"""#E3 — platform/tenant-sahibi olmayan approver başka tenant'ı aktive edemez."""
		name = dele.create_delegation(
			"a@x.com", "b@x.com", "Buyer Approver L1", "ACME",
			datetime(2026, 5, 21, 10), datetime(2026, 5, 28, 18),
		)
		_USERS["outsider@x.com"] = {"roles": ["Buyer"]}  # platform değil, ACME sahibi değil
		with self.assertRaises(Exception):
			dele.activate_delegation(name, approver="outsider@x.com")


# ---------------------------------------------------------------------------
# Owner transfer tests
# ---------------------------------------------------------------------------


class OwnerTransferTests(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_USERS["owner@a.com"] = {
			"role_names": ["Seller Owner"],
			"tradehub_is_owner": 1,
			"tradehub_tenant": "ACME",
		}
		_USERS["coowner@a.com"] = {"role_names": ["Seller Co-Owner"], "role_profile_name": "Seller Co-Owner"}
		_USERS["random@a.com"] = {"role_names": ["Buyer Requisitioner"]}

		# Tenant lookup
		_DOCS["ACME"] = {"doctype": "Admin Seller Profile", "tradehub_owner": "owner@a.com"}

	def test_non_co_owner_rejected(self):
		with self.assertRaises(Exception):
			ot.create_transfer(tenant="ACME", proposed_owner="random@a.com")

	def test_two_step_flow(self):
		name = ot.create_transfer(tenant="ACME", proposed_owner="coowner@a.com", reason="founder leaving")
		self.assertEqual(_DOCS[name]["status"], "awaiting_owner_confirm")

		# Current owner confirms
		import frappe as _f

		_f.session.user = "owner@a.com"
		ot.confirm_by_current_owner(name)
		self.assertEqual(_DOCS[name]["status"], "awaiting_super_admin")

		# System Manager approves
		_f.session.user = "admin@firm.com"
		# get_roles default returns ["System Manager"]
		ot.approve_by_super_admin(name)
		self.assertEqual(_DOCS[name]["status"], "completed")

		# Owner flag swap
		self.assertEqual(_USERS["owner@a.com"]["tradehub_is_owner"], 0)
		self.assertEqual(_USERS["coowner@a.com"]["tradehub_is_owner"], 1)

	def test_force_transfer_one_step(self):
		import frappe as _f

		_f.session.user = "admin@firm.com"
		name = ot.create_transfer(
			tenant="ACME",
			proposed_owner="random@a.com",
			reason="owner missing",
			is_force=True,
		)
		# Force ile direkt awaiting_super_admin
		self.assertEqual(_DOCS[name]["status"], "awaiting_super_admin")
		# Random user co-owner değilse de force=True bypass etti
		ot.approve_by_super_admin(name)
		self.assertEqual(_DOCS[name]["status"], "completed")

	def test_reject(self):
		name = ot.create_transfer(
			tenant="ACME",
			proposed_owner="coowner@a.com",
		)
		ot.reject(name, reason="not authorized")
		self.assertEqual(_DOCS[name]["status"], "rejected")
		self.assertEqual(_DOCS[name]["rejection_reason"], "not authorized")


if __name__ == "__main__":
	unittest.main()
