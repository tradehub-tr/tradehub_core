"""A2 — Enforce-hazırlık raporu (rebac_drift_detection.enforce_readiness_report) testleri.

frappe + rebac_client stub'lanır → gerçek Frappe/sidecar gerektirmez.
Union enforce semantiği: yalnız rebac_overpermits davranış değiştirir → enforce-güvenli
koşulu rebac_overpermits == 0.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

_USERS: list = []
_DOCS: list = []


def _install() -> None:
	f = sys.modules.get("frappe") or types.ModuleType("frappe")
	f.__path__ = []

	def _get_all(doctype, **k):
		if doctype == "User":
			return list(_USERS)
		return [{"name": n} for n in _DOCS]

	f.get_all = _get_all
	f.has_permission = lambda **k: True
	f.db = types.SimpleNamespace(commit=lambda: None, get_value=lambda *a, **k: None)
	utils = types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: "NOW"
	f.utils = utils
	sys.modules["frappe"] = f
	sys.modules["frappe.utils"] = utils

	# Fake rebac_client submodule — gerçek `requests` import'unu önler.
	rc = types.ModuleType("tradehub_core.services.rebac_client")
	rc.healthz = lambda: True
	rc.check = lambda **k: False
	sys.modules["tradehub_core.services.rebac_client"] = rc


_install()

from tradehub_core.services import rebac_drift_detection as drift  # noqa: E402

_SCOPE = [("Order", "read", "can_view")]


class EnforceReadinessTests(unittest.TestCase):
	def setUp(self):
		_USERS.clear()
		_USERS.extend(["u1", "u2"])
		_DOCS.clear()
		_DOCS.extend(["D1", "D2"])
		_install()

	def test_rebac_over_grant_makes_unsafe(self):
		# u1/D1 → ReBAC over-grant (RBAC deny, ReBAC allow) → enforce-TEHLİKELİ
		drift._compare = lambda u, dt, pt, rel, dn: (False, True) if (u == "u1" and dn == "D1") else (True, True)
		r = drift.enforce_readiness_report(scope=_SCOPE)
		st = r["doctypes"]["Order [read]"]
		self.assertEqual(st["rebac_overpermits"], 1)
		self.assertFalse(st["enforce_safe"])
		self.assertFalse(r["enforce_safe_all"])
		self.assertTrue(len(st["samples"]) >= 1)

	def test_no_over_grant_is_safe(self):
		drift._compare = lambda *a: (True, True)
		r = drift.enforce_readiness_report(scope=_SCOPE)
		st = r["doctypes"]["Order [read]"]
		self.assertEqual(st["rebac_overpermits"], 0)
		self.assertTrue(st["enforce_safe"])
		self.assertTrue(r["enforce_safe_all"])

	def test_frappe_overpermit_safe_but_counted(self):
		# RBAC allow, ReBAC deny → union'da ZARARSIZ ama sayılır (eksik grant sinyali)
		drift._compare = lambda *a: (True, False)
		r = drift.enforce_readiness_report(scope=_SCOPE)
		st = r["doctypes"]["Order [read]"]
		self.assertEqual(st["frappe_overpermits"], 4)  # 2 user × 2 doc
		self.assertEqual(st["rebac_overpermits"], 0)
		self.assertTrue(st["enforce_safe"])

	def test_all_skipped_not_safe(self):
		# _compare hep None (karşılaştırılamıyor) → compared=0 → enforce-güvenli DEĞİL
		drift._compare = lambda *a: None
		r = drift.enforce_readiness_report(scope=_SCOPE)
		st = r["doctypes"]["Order [read]"]
		self.assertEqual(st["compared"], 0)
		self.assertFalse(st["enforce_safe"])

	def test_sidecar_down_skips(self):
		sys.modules["tradehub_core.services.rebac_client"].healthz = lambda: False
		r = drift.enforce_readiness_report(scope=_SCOPE)
		self.assertEqual(r.get("skipped"), "sidecar_unavailable")


if __name__ == "__main__":
	unittest.main()
