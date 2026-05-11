"""Pure-Python unit tests for rfq_has_permission.

Frappe runtime is stubbed at module load — runs with plain unittest:

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_rfq_permissions
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


def _install_frappe_stub() -> None:
	"""Minimal frappe stub so importing permissions.py doesn't blow up."""
	if "frappe" in sys.modules:
		return

	frappe = types.ModuleType("frappe")
	frappe.db = types.SimpleNamespace(
		get_value=lambda *a, **kw: None,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
	)
	frappe.get_roles = lambda u: []
	frappe.utils = types.ModuleType("frappe.utils")
	frappe.utils.cint = int
	frappe.utils.flt = float
	sys.modules["frappe"] = frappe
	sys.modules["frappe.utils"] = frappe.utils

	# tenant utils stub
	tenant_mod = types.ModuleType("tradehub_core.utils.tenant")
	tenant_mod._has_tenant_field = lambda *a, **kw: False
	tenant_mod.get_current_tenant = lambda *a, **kw: None
	tenant_mod.is_tenant_admin = lambda *a, **kw: False
	sys.modules["tradehub_core.utils.tenant"] = tenant_mod


_install_frappe_stub()

from tradehub_core import permissions  # noqa: E402


def _make_rfq(buyer="alice@x.com", name="RFQ-001", status="Approved", category="CAT-X"):
	return SimpleNamespace(buyer=buyer, name=name, status=status, category=category)


class GuestAndAdminTests(unittest.TestCase):
	def test_guest_denied(self):
		import frappe

		frappe.get_roles = lambda u: []
		self.assertFalse(permissions.rfq_has_permission(_make_rfq(), "read", "Guest"))

	def test_system_manager_allowed(self):
		import frappe

		frappe.get_roles = lambda u: ["System Manager"]
		self.assertTrue(permissions.rfq_has_permission(_make_rfq(), "read", "admin@x.com"))
		self.assertTrue(permissions.rfq_has_permission(_make_rfq(), "write", "admin@x.com"))
		self.assertTrue(permissions.rfq_has_permission(_make_rfq(), "delete", "admin@x.com"))

	def test_marketplace_admin_allowed(self):
		import frappe

		frappe.get_roles = lambda u: ["Marketplace Admin"]
		self.assertTrue(permissions.rfq_has_permission(_make_rfq(), "read", "ma@x.com"))


class BuyerTests(unittest.TestCase):
	def test_owner_can_read_and_write(self):
		import frappe

		frappe.get_roles = lambda u: ["Buyer"]
		doc = _make_rfq(buyer="alice@x.com")
		self.assertTrue(permissions.rfq_has_permission(doc, "read", "alice@x.com"))
		self.assertTrue(permissions.rfq_has_permission(doc, "write", "alice@x.com"))

	def test_other_buyer_denied(self):
		import frappe

		frappe.get_roles = lambda u: ["Buyer"]
		doc = _make_rfq(buyer="alice@x.com")
		self.assertFalse(permissions.rfq_has_permission(doc, "read", "eve@x.com"))


class SellerTests(unittest.TestCase):
	def setUp(self):
		import frappe

		frappe.get_roles = lambda u: ["Seller"]
		self.frappe = frappe

	def test_seller_with_existing_quote_can_read(self):
		# RFQ Quote exists → ok regardless of status / category
		self.frappe.db.exists = lambda dt, filt: dt == "RFQ Quote"
		self.frappe.db.get_value = lambda *a, **kw: None
		doc = _make_rfq(status="Pending", category=None)
		self.assertTrue(permissions.rfq_has_permission(doc, "read", "seller@x.com"))

	def test_seller_cannot_write_even_when_eligible(self):
		self.frappe.db.exists = lambda dt, filt: dt == "RFQ Quote"
		doc = _make_rfq()
		self.assertFalse(permissions.rfq_has_permission(doc, "write", "seller@x.com"))

	def test_seller_category_match_on_approved_rfq(self):
		# No existing quote, but category matches → ok
		calls = []

		def mock_exists(dt, filt):
			calls.append((dt, filt))
			if dt == "RFQ Quote":
				return False
			if dt == "Seller Category":
				return filt.get("category") == "CAT-X" and filt.get("status") == "Active"
			return False

		self.frappe.db.exists = mock_exists
		self.frappe.db.get_value = lambda dt, filt, field=None: (
			"SELLER-001" if dt == "Admin Seller Profile" else None
		)
		doc = _make_rfq(status="Approved", category="CAT-X")
		self.assertTrue(permissions.rfq_has_permission(doc, "read", "seller@x.com"))

	def test_seller_category_mismatch(self):
		self.frappe.db.exists = lambda dt, filt: False  # no quote, no category match
		self.frappe.db.get_value = lambda *a, **kw: "SELLER-001"
		doc = _make_rfq(status="Approved", category="CAT-Y")
		self.assertFalse(permissions.rfq_has_permission(doc, "read", "seller@x.com"))

	def test_seller_pending_rfq_denied_without_quote(self):
		# Pending RFQ + category match → still denied (must be Approved)
		self.frappe.db.exists = lambda dt, filt: dt == "Seller Category"
		self.frappe.db.get_value = lambda *a, **kw: "SELLER-001"
		doc = _make_rfq(status="Pending", category="CAT-X")
		self.assertFalse(permissions.rfq_has_permission(doc, "read", "seller@x.com"))

	def test_seller_without_profile_denied(self):
		self.frappe.db.exists = lambda dt, filt: False
		self.frappe.db.get_value = lambda *a, **kw: None  # no profile
		doc = _make_rfq(status="Approved", category="CAT-X")
		self.assertFalse(permissions.rfq_has_permission(doc, "read", "seller@x.com"))


class DoctypeLevelTests(unittest.TestCase):
	def test_doc_none_admin_true(self):
		import frappe

		frappe.get_roles = lambda u: ["System Manager"]
		self.assertTrue(permissions.rfq_has_permission(None, "read", "admin@x.com"))

	def test_doc_none_non_admin_true_for_listing(self):
		# doctype-level check (doc=None) → defer to per-doc; allow list rendering.
		import frappe

		frappe.get_roles = lambda u: ["Buyer"]
		self.assertTrue(permissions.rfq_has_permission(None, "read", "alice@x.com"))


if __name__ == "__main__":
	unittest.main()
