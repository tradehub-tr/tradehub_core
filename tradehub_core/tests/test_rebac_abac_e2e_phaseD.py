"""FAZ D — ReBAC + ABAC adversarial / interleaved scenario tests.

5 P0 senaryo gerçek koşum + sonuçlarla birlikte:

  1. Multi-layer interleaved deny chain — L0/L1/L2 ALLOW, L2 ABAC DENY
  2. order.total=None → ABAC default-allow vektörü mü?
  3. TR jurisdiction KVKK PII region-mismatch — L3 DENY çalışıyor mu?
  4. Buyer Approver L1 → Pro plan → kendi org seller → 100K EUR full-stack approve
  5. Currency normalize bug — Order USD 6000 → EUR tier nasıl hesaplanıyor

Bonus:
  6. _record() SKIP→ALLOW path — tüm katmanlar SKIP olduğunda decision ALLOW mı?
"""

from __future__ import annotations

import unittest

from tradehub_core.services import authorization_simulator as sim  # noqa: E402

# Re-use the heavy frappe stub + helpers from test_authorization_simulator.
# This dosya yalnızca scenario'ları içerir; stub re-write yok.
from tradehub_core.tests.test_authorization_simulator import (  # noqa: E402
	_PERM_RESULTS,
	_make_caller_system_manager,
	_reset_state,
	_setup_actor,
	_setup_resource,
)


class _PhaseDBase(unittest.TestCase):
	def setUp(self):
		_reset_state()
		_make_caller_system_manager()

		# has_feature default-True
		from tradehub_core.entitlement import core as ent_core

		ent_core.has_feature = lambda store, key: True

		# ReBAC default-allow
		from tradehub_core.services import rebac_client as rc

		rc.check = lambda **kwargs: True

		# PII default — boş alan, L3 SKIP
		from tradehub_core.utils import pii as pii_utils

		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: []
		pii_utils.get_user_max_permlevel = lambda u, dt: 9
		pii_utils.is_strict_jurisdiction = lambda r: r in {"TR", "EU"}
		pii_utils.get_jurisdiction_for_region = lambda r: {
			"TR": "KVKK",
			"EU": "GDPR",
		}.get(r)


# ============================================================================
# Senaryo 1 — Multi-layer interleaved DENY chain
# ============================================================================
#
# Beklenti: L0 ALLOW + L1 ALLOW + L2 Frappe ALLOW + L2 ReBAC ALLOW + L2 ABAC DENY
# → first_deny LAYER_L2_ABAC olmalı; overall DENY.


class S1_InterleavedDenyChain(_PhaseDBase):
	def test_first_deny_is_abac(self):
		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval",
			"OA-S1",
			total=200,  # < 500 → needs_approval_l1 = False (DENY)
			currency="EUR",
			seller_profile="ACME",
		)

		# Tüm önceki katmanlar ALLOW — Frappe permission True (default),
		# ReBAC check True (default), L0 has_feature True.
		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S1",
			context={"amount": 200, "request_hour": 14},
		)

		self.assertEqual(res["decision"], "DENY")
		self.assertEqual(res["first_deny"]["layer"], sim.LAYER_L2_ABAC)

		layers = {s["layer"]: s["result"] for s in res["trace"]}
		# L0, L1, L2 Frappe, L2 ReBAC hepsi ALLOW olmalı (interleave kanıtı)
		self.assertEqual(layers[sim.LAYER_L0], "ALLOW")
		self.assertEqual(layers[sim.LAYER_L1], "ALLOW")
		self.assertEqual(layers[sim.LAYER_L2_FRAPPE], "ALLOW")
		self.assertEqual(layers[sim.LAYER_L2_REBAC], "ALLOW")
		self.assertEqual(layers[sim.LAYER_L2_ABAC], "DENY")


# ============================================================================
# Senaryo 2 — order.total = None (default-allow vector?)
# ============================================================================
#
# Hipotez: build_order_context() amount=None → float(0). Sonuçta
# amount=0 olur, L1 condition (500<amount<=5000) False döner — DENY.
# Yani SIZINTI vektörü değil (amount=0 'silinmiş order' davranışı DENY üretiyor).


class S2_OrderTotalNoneBehavior(_PhaseDBase):
	def test_amount_none_falls_to_zero_and_denies(self):
		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval",
			"OA-S2-NONE",
			total=None,
			currency="EUR",
			seller_profile="ACME",
		)

		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S2-NONE",
			# Context'te amount yok — resource_snapshot.fields'tan okunur,
			# orada da None → fallback `or 0`
		)

		# Beklenen: DENY (ABAC L1 condition fail), first_deny ABAC
		self.assertEqual(res["decision"], "DENY")
		self.assertEqual(res["first_deny"]["layer"], sim.LAYER_L2_ABAC)

		abac = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_ABAC)
		# amount=0 detail'ında görünmeli
		self.assertIn("amount=0", abac["meta"]["conditions"][0]["detail"])

	def test_amount_none_with_context_explicit_zero_is_also_deny(self):
		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval",
			"OA-S2-ZERO",
			total=None,
			seller_profile="ACME",
		)

		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S2-ZERO",
			context={"amount": 0, "request_hour": 14},
		)
		self.assertEqual(res["decision"], "DENY")


# ============================================================================
# Senaryo 3 — TR KVKK PII region-mismatch (L3 DENY)
# ============================================================================
#
# Order TR jurisdiction'da, user EU bölgesinde, target_region=TR
# → L3 pii.jurisdiction_mismatch DENY çalışmalı.


class S3_KvkkRegionMismatch(_PhaseDBase):
	def test_tr_target_eu_user_l3_deny(self):
		from tradehub_core.utils import pii as pii_utils

		# PII alanı VAR; permlevel yeterli; ama target_region TR & strict
		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: ["tc_no"]
		pii_utils.get_user_max_permlevel = lambda u, dt: 2
		pii_utils.is_strict_jurisdiction = lambda r: r == "TR"
		pii_utils.get_jurisdiction_for_region = lambda r: "KVKK" if r == "TR" else None

		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],  # ← TR yok
		)
		_setup_resource(
			"Order Approval",
			"OA-S3",
			total=1500,
			seller_profile="ACME",
		)

		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S3",
			context={
				"amount": 1500,
				"request_hour": 14,
				"target_region": "TR",
			},
		)

		self.assertEqual(res["decision"], "DENY")
		l3 = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L3)
		self.assertEqual(l3["result"], "DENY")
		self.assertIn("jurisdiction", l3["check"])

	def test_tr_target_tr_user_passes(self):
		from tradehub_core.utils import pii as pii_utils

		pii_utils.get_pii_fieldnames = lambda dt, min_permlevel=1: ["tc_no"]
		pii_utils.get_user_max_permlevel = lambda u, dt: 2
		pii_utils.is_strict_jurisdiction = lambda r: r == "TR"

		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["TR", "EU"],
		)
		_setup_resource("Order Approval", "OA-S3B", total=1500, seller_profile="ACME")

		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S3B",
			context={"amount": 1500, "request_hour": 14, "target_region": "TR"},
		)
		self.assertEqual(res["decision"], "ALLOW")


# ============================================================================
# Senaryo 4 — Buyer Approver L1 → Pro plan → own org seller → 100K EUR
# ============================================================================
#
# Beklenti: 100K > 5000 → ABAC L2 condition (needs_approval_l2) kontrol
# edilmeli, amount büyüklük olarak L2 koşulunu sağlar (>5000). Aksiyon
# `approve` → simulator amount'a göre L2 koşulunu seçer.
# Tüm 4 katman ALLOW dönmeli.


class S4_FullStack100KApprove(_PhaseDBase):
	def test_100k_eur_full_chain_allow(self):
		_setup_actor(
			"approver@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval",
			"OA-S4-100K",
			total=100000,
			currency="EUR",
			seller_profile="ACME",
		)

		res = sim.simulate(
			"approver@acme.com",
			"approve",
			"Order Approval",
			"OA-S4-100K",
			context={"amount": 100000, "currency": "EUR", "request_hour": 14},
		)

		# Beklenti: ALLOW; ABAC L2 condition geçer (>5000 amount → needs_approval_l2)
		self.assertEqual(res["decision"], "ALLOW", msg=f"trace={res['trace']}")

		abac = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_ABAC)
		self.assertEqual(abac["result"], "ALLOW")
		conditions = abac["meta"]["conditions"]
		# needs_approval_l2 koşulu denenmeli (amount > 5000 branch)
		names = [c["name"] for c in conditions]
		self.assertIn("needs_approval_l2", names)


# ============================================================================
# Senaryo 5 — Currency normalize bug (USD 6000 → tier hesabı?)
# ============================================================================
#
# Order currency=USD, amount=6000. ABAC simulator amount'u float(6000) olarak
# kullanır — currency conversion YAPMAZ. Yani 6000 USD ~ 5500 EUR olsa bile
# simulator bunu 6000 olarak işler ve needs_approval_l2 branch'e düşer.
#
# BU BİR BUG OLABİLİR: Eğer iş kuralı "EUR cinsinden tier" ise 6000 USD'nin
# EUR karşılığı ≈ 5400 EUR (TCMB) ve L1 branch'e düşmesi gerekirdi.


class S5_CurrencyNormalizeAudit(_PhaseDBase):
	def test_usd_6000_treated_as_raw_amount(self):
		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval",
			"OA-S5-USD",
			total=6000,
			currency="USD",
			seller_profile="ACME",
		)

		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S5-USD",
			context={"amount": 6000, "currency": "USD", "request_hour": 14},
		)

		abac = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_ABAC)
		conditions_meta = abac["meta"]["conditions"]
		names = [c["name"] for c in conditions_meta]

		# Bug kanıtı: USD/EUR ayrımı yapılmıyor; 6000 > 5000 olduğu için
		# direkt L2 branch'e düşer. Gerçek "currency neutral tier" implementasyonu
		# olsaydı conversion ile L1 koşulu test edilirdi.
		self.assertIn("needs_approval_l2", names)
		# 6000 > 5000 → L2 condition True → ALLOW
		self.assertEqual(res["decision"], "ALLOW")

	def test_usd_4900_below_threshold_no_conversion(self):
		_setup_actor(
			"buyer@acme.com",
			["Buyer Approver L1"],
			tenant="ACME",
			plan="Pro",
			regions=["EU"],
		)
		_setup_resource(
			"Order Approval",
			"OA-S5-USD2",
			total=4900,
			currency="USD",
			seller_profile="ACME",
		)

		res = sim.simulate(
			"buyer@acme.com",
			"approve",
			"Order Approval",
			"OA-S5-USD2",
			context={"amount": 4900, "currency": "USD", "request_hour": 14},
		)
		abac = next(s for s in res["trace"] if s["layer"] == sim.LAYER_L2_ABAC)
		# 4900 <= 5000 → L1 branch (500 < amount <= 5000) → ALLOW
		self.assertEqual(abac["result"], "ALLOW")


# ============================================================================
# Senaryo 6 — _record() SKIP→ALLOW path exploit
# ============================================================================
#
# Tüm katmanlar SKIP olduğunda decision default-init "ALLOW" olarak gelir.
# Yeni doctype `Test Resource` için ne L0 mapping, ne ReBAC mapping,
# ne ABAC kapsamı var; L1 SKIP (tenant=None), L3 SKIP (PII boş).
# → Simulator ALLOW döner.


class S6_AllSkipDefaultAllow(_PhaseDBase):
	def test_unknown_doctype_all_skip_returns_allow(self):
		_setup_actor("admin@x.com", ["System Manager"], tenant=None)
		_setup_resource("Test Resource", "TR-1")  # no tenant, no fields

		res = sim.simulate("admin@x.com", "read", "Test Resource", "TR-1")

		# Beklenti: ALLOW (tehlikeli; default-allow vektörü)
		self.assertEqual(res["decision"], "ALLOW", msg=f"trace={res['trace']}")

		results = {s["layer"]: s["result"] for s in res["trace"]}
		# Hepsi SKIP olmalı — gerçek erişim kararı verilmedi
		self.assertEqual(results.get(sim.LAYER_L0), "SKIP")
		self.assertEqual(results.get(sim.LAYER_L1), "SKIP")
		self.assertEqual(results.get(sim.LAYER_L2_REBAC), "SKIP")
		self.assertEqual(results.get(sim.LAYER_L2_ABAC), "SKIP")
		self.assertEqual(results.get(sim.LAYER_L3), "SKIP")
		# L2 Frappe ALLOW (default has_permission True) — SKIP'ten ALLOW
		# yönünde tek "gerçek" karar burası.
		self.assertEqual(results.get(sim.LAYER_L2_FRAPPE), "ALLOW")

	def test_non_admin_caller_with_no_actor_tenant_unknown_doctype(self):
		"""Tenant=None aktör + tanımsız doctype + Frappe perm DENY → DENY."""
		_setup_actor("noone@x.com", ["Buyer Requisitioner"], tenant=None)
		_setup_resource("Test Resource", "TR-2")
		_PERM_RESULTS[("noone@x.com", "Test Resource", "read", "TR-2")] = False

		res = sim.simulate("noone@x.com", "read", "Test Resource", "TR-2")
		# L2 Frappe DENY → overall DENY
		self.assertEqual(res["decision"], "DENY")
		self.assertEqual(res["first_deny"]["layer"], sim.LAYER_L2_FRAPPE)


if __name__ == "__main__":
	unittest.main()
