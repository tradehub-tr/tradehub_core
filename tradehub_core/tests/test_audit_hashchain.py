"""Faz 6 (#F1) — Audit hash-chain tamper-evidence unit testleri.

frappe.get_all stub'lanır → gerçek DB gerektirmez; CI authz gate'inde koşar.
adl_entry_hash determinizmi + verify_chain'in içerik/linkage kurcalamasını
tespit etmesi doğrulanır.
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))

_ROWS: list = []


def _install() -> None:
	f = sys.modules.get("frappe") or types.ModuleType("frappe")
	if not hasattr(f, "__path__"):
		f.__path__ = []  # paket gibi davran (from frappe.utils import ...)
	f.get_all = lambda dt, filters=None, fields=None, order_by=None, limit=None: list(_ROWS)
	f.log_error = lambda *a, **k: None
	f.session = types.SimpleNamespace(user="tester@x")
	utils = sys.modules.get("frappe.utils") or types.ModuleType("frappe.utils")
	utils.now_datetime = lambda: None
	f.utils = utils
	sys.modules["frappe"] = f
	sys.modules["frappe.utils"] = utils


_install()

from tradehub_core.audit import log as A  # noqa: E402


def _mk(name: str, **overrides) -> dict:
	row = {"name": name, "prev_hash": None, "entry_hash": None, "creation": name}
	for f in A.ADL_HASH_FIELDS:
		row[f] = ""
	row.update(overrides)
	return row


def _build_chain(entries: list[dict]) -> list[dict]:
	rows = []
	prev = "GENESIS"
	for i, e in enumerate(entries):
		r = _mk(f"ADL-{i:03d}", **e)
		r["prev_hash"] = prev
		r["entry_hash"] = A.adl_entry_hash(r, prev)
		prev = r["entry_hash"]
		rows.append(r)
	return rows


class HashHelperTests(unittest.TestCase):
	def test_hash_deterministic_and_64_hex(self):
		r = _mk("X", actor="u@x", decision="ALLOW")
		h = A.adl_entry_hash(r, "GENESIS")
		self.assertEqual(len(h), 64)
		self.assertEqual(h, A.adl_entry_hash(dict(r), "GENESIS"))

	def test_content_change_changes_hash(self):
		r = _mk("X", actor="u@x", decision="ALLOW")
		h1 = A.adl_entry_hash(r, "GENESIS")
		r2 = dict(r)
		r2["decision"] = "DENY"
		self.assertNotEqual(h1, A.adl_entry_hash(r2, "GENESIS"))

	def test_prev_hash_changes_hash(self):
		r = _mk("X", actor="u@x")
		self.assertNotEqual(A.adl_entry_hash(r, "A"), A.adl_entry_hash(r, "B"))


class VerifyChainTests(unittest.TestCase):
	def setUp(self):
		_ROWS.clear()
		_install()

	def test_valid_chain_ok(self):
		_ROWS.extend(_build_chain([{"actor": "a@x", "decision": "ALLOW"}, {"actor": "b@x", "decision": "DENY"}]))
		v = A.verify_chain()
		self.assertTrue(v["ok"])
		self.assertEqual(v["checked"], 2)
		self.assertEqual(v["tampered"], [])

	def test_content_tamper_detected(self):
		rows = _build_chain([{"actor": "a@x", "decision": "ALLOW"}, {"actor": "b@x", "decision": "DENY"}])
		# entry_hash sabit ama içerik değişti (saldırgan DB update) → recompute uyuşmaz
		rows[1]["decision"] = "ALLOW"
		_ROWS.extend(rows)
		v = A.verify_chain()
		self.assertFalse(v["ok"])
		self.assertTrue(
			any(t["name"] == rows[1]["name"] and t["kind"] == "content" for t in v["tampered"])
		)

	def test_broken_link_detected_on_deletion(self):
		rows = _build_chain([{"actor": "a@x"}, {"actor": "b@x"}, {"actor": "c@x"}])
		del rows[1]  # ortadaki kaydı sil → linkage kopar
		_ROWS.extend(rows)
		v = A.verify_chain()
		self.assertFalse(v["ok"])
		self.assertGreaterEqual(len(v["broken_links"]), 1)

	def test_bad_genesis_detected(self):
		rows = _build_chain([{"actor": "a@x"}])
		rows[0]["prev_hash"] = "TAMPERED"  # ilk kayıt GENESIS değil
		# entry_hash'i de prev'e göre yeniden hesapla ki içerik-tamper değil linkage olsun
		rows[0]["entry_hash"] = A.adl_entry_hash(rows[0], "TAMPERED")
		_ROWS.extend(rows)
		v = A.verify_chain()
		self.assertFalse(v["ok"])
		self.assertTrue(any(b["kind"] == "bad_genesis" for b in v["broken_links"]))


if __name__ == "__main__":
	unittest.main()
