"""C9 — Store Subscription DocType izin regresyon testi.

Marketplace Seller / Seller rolleri kendi aboneliklerini DEĞİŞTİREMEMELİ
(yalnız read). Plan/status değişimi yalnızca admin + ödeme akışı üzerinden.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_store_subscription_perms
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_DOCTYPE_JSON = (
	Path(__file__).resolve().parents[1]
	/ "tradehub_core"
	/ "doctype"
	/ "store_subscription"
	/ "store_subscription.json"
)


class TestStoreSubscriptionPerms(unittest.TestCase):
	def setUp(self):
		self.perms = json.loads(_DOCTYPE_JSON.read_text())["permissions"]

	def _perm(self, role):
		return next((p for p in self.perms if p.get("role") == role), None)

	def test_seller_roles_cannot_write(self):
		for role in ("Marketplace Seller", "Seller"):
			p = self._perm(role)
			self.assertIsNotNone(p, f"{role} permission bloğu bulunmalı")
			self.assertNotEqual(p.get("write"), 1, f"{role} write iznine SAHİP OLMAMALI (C9)")
			self.assertNotEqual(p.get("create"), 1, f"{role} create iznine sahip olmamalı")
			self.assertNotEqual(p.get("delete"), 1, f"{role} delete iznine sahip olmamalı")

	def test_seller_can_still_read(self):
		p = self._perm("Marketplace Seller")
		self.assertEqual(p.get("read"), 1, "Seller kendi aboneliğini okuyabilmeli")

	def test_admin_retains_write(self):
		p = self._perm("System Manager")
		self.assertEqual(p.get("write"), 1, "System Manager write iznini korumalı")


if __name__ == "__main__":
	unittest.main()
