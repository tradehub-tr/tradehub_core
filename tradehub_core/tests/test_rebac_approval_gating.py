"""#C6 — order.can_approve amount-gating için tuple wiring testi.

`_sync_approval_tuples`'ın şunları yazdığını doğrular:
  - `(order_approval:APP, approval, order:X)` — #C6 order→order_approval linki;
    order.can_approve bunun üzerinden order_approval'ın KOŞULLU can_approve_l1/l2'sine
    (needs_approval_l1/l2) çözülür → L1 approver limitini aşan order'ı onaylayamaz.
  - `(order:X, target_order, order_approval:APP)` — geriye dönük referans (yön:
    model `order_approval.target_order: [order]` → user=order, object=order_approval).
  - `(user:U, can_approve_l1, order_approval:APP, needs_approval_l1)` — L1 koşullu.
  - `(user:U, can_approve_l2, order_approval:APP, needs_approval_l2)` — L2 koşullu.

Amount-gating'in RUNTIME davranışı (L1 3000 onaylar, 10000 onaylayamaz) canlı
OpenFGA'ya karşı doğrulanmıştır; bu test tuple-yazımını CI'da kilitler.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_rebac_approval_gating
"""

from __future__ import annotations

import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe
	frappe.session = SimpleNamespace(user="Administrator")
	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None
	if not hasattr(frappe, "_"):
		frappe._ = lambda s: s

	# frappe.utils (approval_workflow top-level import: add_days, now_datetime)
	futils = sys.modules.get("frappe.utils")
	if futils is None:
		futils = types.ModuleType("frappe.utils")
		sys.modules["frappe.utils"] = futils
	futils.add_days = lambda d, n=0: d
	futils.now_datetime = lambda: None
	futils.today = lambda: None
	frappe.utils = futils


_install_frappe_stub()

from tradehub_core.services import approval_workflow  # noqa: E402


class ApprovalTupleGatingTests(unittest.TestCase):
	def _run_sync(self, l1_users, l2_users):
		captured: list = []
		approval = SimpleNamespace(name="APP-1", order="ORD-1")
		rule = SimpleNamespace(
			get_approvers_at_level=lambda lvl: l1_users if lvl == 1 else l2_users
		)
		with patch(
			"tradehub_core.services.rebac_client.write_tuples",
			side_effect=lambda t: captured.extend(t) or True,
		):
			approval_workflow._sync_approval_tuples(approval, rule)
		return captured

	def test_writes_c6_approval_link(self):
		"""#C6 — order→order_approval `approval` link tuple'ı yazılmalı."""
		captured = self._run_sync(["l1@x"], ["l2@x"])
		self.assertIn(("order_approval:APP-1", "approval", "order:ORD-1"), captured)

	def test_writes_target_order_link(self):
		"""target_order yönü: model `order_approval.target_order: [order]` →
		tuple (user=order, object=order_approval)."""
		captured = self._run_sync(["l1@x"], [])
		self.assertIn(("order:ORD-1", "target_order", "order_approval:APP-1"), captured)

	def test_writes_conditional_approver_tuples(self):
		"""L1/L2 approver tuple'ları amount condition'ı ile yazılmalı."""
		captured = self._run_sync(["l1@x"], ["l2@x"])
		self.assertIn(
			("user:l1@x", "can_approve_l1", "order_approval:APP-1", "needs_approval_l1"),
			captured,
		)
		self.assertIn(
			("user:l2@x", "can_approve_l2", "order_approval:APP-1", "needs_approval_l2"),
			captured,
		)


if __name__ == "__main__":
	unittest.main()
