"""FAZ 2.3 — tuple_sync unit testleri.

tradehub_core.services.tuple_sync içindeki doc_event handler'ları:
  - on_user_insert / on_user_update / on_user_trash
  - on_admin_seller_profile_insert / on_admin_seller_profile_trash
  - on_organization_insert / on_organization_trash
  - on_listing_insert / on_listing_trash
  - on_order_insert / on_order_trash

için saf-Python testler. frappe.enqueue mock'lanır → enqueue'a verilen
tuple listesi doğrulanır.

    cd apps/tradehub_core && python3 -m unittest tradehub_core.tests.test_tuple_sync
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


_ENQUEUED: list[dict] = []  # frappe.enqueue çağrıları buraya birikir
_DB: dict = {}
_ROLES: dict[str, list[str]] = {}  # user → assigned roles (frappe.get_roles)


def _install_frappe_stub() -> None:
	frappe = sys.modules.get("frappe")
	if frappe is None:
		frappe = types.ModuleType("frappe")
		sys.modules["frappe"] = frappe

	def _enqueue(method, queue="short", **kwargs):
		_ENQUEUED.append({"method": method, "queue": queue, **kwargs})

	frappe.enqueue = _enqueue

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(filters), str(fieldname))
		return _DB.get(key)

	def get_all(doctype, filters=None, pluck=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: True,
	)
	frappe.get_all = get_all
	frappe.get_roles = lambda user: _ROLES.get(user, [])

	if not hasattr(frappe, "log_error"):
		frappe.log_error = lambda *a, **kw: None


_install_frappe_stub()


def _reset_state():
	"""Test'ler arası state'i temizle + frappe stub'ını force reinstall.

	Diğer test dosyaları frappe.db.get_value closure'unu kendi _DB'lerine
	bağlamış olabilir. setUp'ta tuple_sync'in beklediği davranışı zorla geri
	getiriyoruz.
	"""
	_ENQUEUED.clear()
	_DB.clear()
	_ROLES.clear()

	frappe = sys.modules["frappe"]

	def _enqueue(method, queue="short", **kwargs):
		_ENQUEUED.append({"method": method, "queue": queue, **kwargs})

	def db_get_value(doctype, filters=None, fieldname=None, **kwargs):
		key = ("get_value", doctype, str(filters), str(fieldname))
		return _DB.get(key)

	def get_all(doctype, filters=None, pluck=None, **kwargs):
		key = ("get_all", doctype, str(filters), pluck)
		return _DB.get(key, [])

	frappe.enqueue = _enqueue
	frappe.db = SimpleNamespace(
		get_value=db_get_value,
		exists=lambda *a, **kw: False,
		escape=lambda s: f"'{s}'",
		count=lambda *a, **kw: 0,
		has_column=lambda *a, **kw: True,
	)
	frappe.get_all = get_all
	frappe.get_roles = lambda user: _ROLES.get(user, [])


def _make_doc(doctype, name, owner="Administrator", **fields):
	doc = SimpleNamespace(doctype=doctype, name=name, owner=owner, **fields)
	doc.get = lambda field, default=None: getattr(doc, field, default)
	return doc


# Import sonra (stub kurulmalı)
from tradehub_core.services import tuple_sync  # noqa: E402

# ---------------------------------------------------------------------------
# User hooks
# ---------------------------------------------------------------------------


class UserInsertTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_seller_user_writes_member_tuple(self):
		"""Tenant'ı olan user → store:tenant'a member tuple."""
		doc = _make_doc(
			"User",
			"ahmet@anatolian.com",
			tradehub_tenant="STORE-A",
			tradehub_is_owner=0,
		)
		# Mock: bu user owner değil
		_DB[("get_value", "User", "ahmet@anatolian.com", "tradehub_is_owner")] = 0
		_DB[("get_value", "User", "ahmet@anatolian.com", "role_profile_name")] = "Seller Manager"

		tuple_sync.on_user_insert(doc)

		self.assertEqual(len(_ENQUEUED), 1)
		call = _ENQUEUED[0]
		self.assertIn("write_tuples", call["method"])

		tuples = call["tuples"]
		# (user:ahmet, member, store:STORE-A)
		self.assertEqual(len(tuples), 1)
		self.assertEqual(tuples[0], ("user:ahmet@anatolian.com", "member", "store:STORE-A"))

	def test_owner_user_writes_owner_and_member_tuples(self):
		"""Owner = is_owner=1 → owner + member tuple'ları."""
		doc = _make_doc("User", "mehmet@anatolian.com", tradehub_tenant="STORE-A")
		_DB[("get_value", "User", "mehmet@anatolian.com", "tradehub_is_owner")] = 1
		_DB[("get_value", "User", "mehmet@anatolian.com", "role_profile_name")] = "Seller Full Access"

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertEqual(len(tuples), 2)
		self.assertIn(("user:mehmet@anatolian.com", "member", "store:STORE-A"), tuples)
		self.assertIn(("user:mehmet@anatolian.com", "owner", "store:STORE-A"), tuples)

	def test_co_owner_writes_co_owner_tuple(self):
		"""Seller Co-Owner rolü → co_owner ilişkisi."""
		doc = _make_doc("User", "selin@anatolian.com", tradehub_tenant="STORE-A")
		_DB[("get_value", "User", "selin@anatolian.com", "tradehub_is_owner")] = 0
		_ROLES["selin@anatolian.com"] = ["Seller Co-Owner"]

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:selin@anatolian.com", "member", "store:STORE-A"), tuples)
		self.assertIn(("user:selin@anatolian.com", "co_owner", "store:STORE-A"), tuples)

	def test_buyer_procurement_writes_requisitioner_tuple(self):
		"""Buyer Procurement rolü → requisitioner ilişkisi."""
		doc = _make_doc(
			"User",
			"ayse@acme.com",
			tradehub_tenant=None,
			tradehub_parent_organization="ACME-INC",
		)
		_ROLES["ayse@acme.com"] = ["Buyer Procurement"]

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:ayse@acme.com", "member", "buyer_org:ACME-INC"), tuples)
		self.assertIn(("user:ayse@acme.com", "requisitioner", "buyer_org:ACME-INC"), tuples)

	def test_buyer_approver_l2_writes_both_l1_and_l2(self):
		"""Buyer Approver L2 hem can_approve_l1 hem can_approve_l2 (kümülatif)."""
		doc = _make_doc(
			"User",
			"demet@acme.com",
			tradehub_parent_organization="ACME-INC",
		)
		_ROLES["demet@acme.com"] = ["Buyer Approver L2"]

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:demet@acme.com", "approver_l1", "buyer_org:ACME-INC"), tuples)
		self.assertIn(("user:demet@acme.com", "approver_l2", "buyer_org:ACME-INC"), tuples)

	def test_buyer_approver_l1_only_writes_l1(self):
		"""Buyer Approver L1 sadece L1 — L2 tuple yazılmaz."""
		doc = _make_doc(
			"User",
			"can@acme.com",
			tradehub_parent_organization="ACME-INC",
		)
		_ROLES["can@acme.com"] = ["Buyer Approver L1"]

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:can@acme.com", "approver_l1", "buyer_org:ACME-INC"), tuples)
		self.assertNotIn(("user:can@acme.com", "approver_l2", "buyer_org:ACME-INC"), tuples)

	def test_buyer_finance_writes_finance_tuple(self):
		doc = _make_doc(
			"User",
			"fin@acme.com",
			tradehub_parent_organization="ACME-INC",
		)
		_ROLES["fin@acme.com"] = ["Buyer Finance"]

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:fin@acme.com", "finance", "buyer_org:ACME-INC"), tuples)

	def test_buyer_viewer_writes_viewer_tuple(self):
		doc = _make_doc(
			"User",
			"viewer@acme.com",
			tradehub_parent_organization="ACME-INC",
		)
		_ROLES["viewer@acme.com"] = ["Buyer Viewer"]

		tuple_sync.on_user_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:viewer@acme.com", "viewer", "buyer_org:ACME-INC"), tuples)

	def test_no_tenant_no_org_no_enqueue(self):
		"""Tenant ve parent_org yoksa enqueue olmaz."""
		doc = _make_doc("User", "loner@x.com", tradehub_tenant=None, tradehub_parent_organization=None)
		tuple_sync.on_user_insert(doc)
		self.assertEqual(len(_ENQUEUED), 0)


class UserTrashTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_trash_deletes_all_relations(self):
		"""User silinince tüm relation tuple'ları delete'a giden listede."""
		doc = _make_doc(
			"User",
			"ahmet@x.com",
			tradehub_tenant="STORE-A",
			tradehub_parent_organization="ACME",
		)

		tuple_sync.on_user_trash(doc)

		# delete_tuples'a verilen tuple'lar
		self.assertEqual(_ENQUEUED[0]["method"], "tradehub_core.services.rebac_client.delete_tuples")
		tuples = _ENQUEUED[0]["tuples"]
		# Hem store hem buyer_org ilişkileri silinmeli
		self.assertGreaterEqual(len(tuples), 6)
		user = "user:ahmet@x.com"
		self.assertIn((user, "member", "store:STORE-A"), tuples)
		self.assertIn((user, "owner", "store:STORE-A"), tuples)
		self.assertIn((user, "member", "buyer_org:ACME"), tuples)
		self.assertIn((user, "admin", "buyer_org:ACME"), tuples)


# ---------------------------------------------------------------------------
# Admin Seller Profile hooks
# ---------------------------------------------------------------------------


class AdminSellerProfileTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_insert_writes_owner_tuple(self):
		"""ASP create → store oluşur, Owner tuple'ı yazılır."""
		doc = _make_doc("Admin Seller Profile", "STORE-A", user="mehmet@x.com")
		tuple_sync.on_admin_seller_profile_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:mehmet@x.com", "owner", "store:STORE-A"), tuples)
		self.assertIn(("user:mehmet@x.com", "member", "store:STORE-A"), tuples)

	def test_insert_without_user_skips(self):
		"""user field boşsa enqueue olmaz."""
		doc = _make_doc("Admin Seller Profile", "STORE-NEW", user=None)
		tuple_sync.on_admin_seller_profile_insert(doc)
		self.assertEqual(len(_ENQUEUED), 0)


class OwnerTransferUpdateTests(unittest.TestCase):
	"""#C2 — on_*_update owner/reassignment tuple bakımı (orphan/stale önleme)."""

	def setUp(self):
		_reset_state()

	def _upd(self, doctype, name, before_fields, after_fields):
		before = _make_doc(doctype, name, **before_fields)
		doc = _make_doc(doctype, name, **after_fields)
		doc.get_doc_before_save = lambda: before
		return doc

	def _writes(self):
		return [t for e in _ENQUEUED if e["method"].endswith("write_tuples") for t in e["tuples"]]

	def _deletes(self):
		return [t for e in _ENQUEUED if e["method"].endswith("delete_tuples") for t in e["tuples"]]

	def test_asp_owner_change_realigns(self):
		doc = self._upd("Admin Seller Profile", "STORE-A", {"user": "old@x"}, {"user": "new@x"})
		tuple_sync.on_admin_seller_profile_update(doc)
		self.assertIn(("user:old@x", "owner", "store:STORE-A"), self._deletes())
		self.assertIn(("user:new@x", "owner", "store:STORE-A"), self._writes())

	def test_asp_no_change_noop(self):
		doc = self._upd("Admin Seller Profile", "STORE-A", {"user": "same@x"}, {"user": "same@x"})
		tuple_sync.on_admin_seller_profile_update(doc)
		self.assertEqual(len(_ENQUEUED), 0)

	def test_listing_moved_to_new_store(self):
		doc = self._upd("Listing", "LST-1", {"seller_profile": "S1"}, {"seller_profile": "S2"})
		tuple_sync.on_listing_update(doc)
		self.assertIn(("store:S1", "store_link", "listing:LST-1"), self._deletes())
		self.assertIn(("store:S2", "store_link", "listing:LST-1"), self._writes())

	def test_order_reassigned(self):
		doc = self._upd("Order", "ORD-1", {"seller": "S1"}, {"seller": "S2"})
		tuple_sync.on_order_update(doc)
		self.assertIn(("store:S1", "store_link", "order:ORD-1"), self._deletes())
		self.assertIn(("store:S2", "store_link", "order:ORD-1"), self._writes())

	def test_no_before_save_noop(self):
		doc = _make_doc("Listing", "LST-9", seller_profile="S1")
		doc.get_doc_before_save = lambda: None
		tuple_sync.on_listing_update(doc)
		self.assertEqual(len(_ENQUEUED), 0)


# ---------------------------------------------------------------------------
# Organization hooks
# ---------------------------------------------------------------------------


class OrganizationTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_org_with_parent_creates_group_hierarchy(self):
		"""parent_org varsa group:X parent group:Y tuple'ı yazılır."""
		doc = _make_doc(
			"CRM Organization",
			"acme-pazarlama",
			tradehub_parent_org="acme-istanbul",
			tradehub_org_admin="mehmet@acme.com",
		)
		tuple_sync.on_organization_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		# Hierarchy
		self.assertIn(("group:acme-pazarlama", "parent", "group:acme-istanbul"), tuples)
		# Admin
		self.assertIn(("user:mehmet@acme.com", "admin", "buyer_org:acme-pazarlama"), tuples)

	def test_org_without_parent_no_hierarchy(self):
		"""Root org → hierarchy tuple yok."""
		doc = _make_doc("CRM Organization", "acme-root", tradehub_parent_org=None, tradehub_org_admin=None)
		tuple_sync.on_organization_insert(doc)
		# Boş tuples (admin yok, parent yok)
		self.assertEqual(len(_ENQUEUED), 0)


# ---------------------------------------------------------------------------
# Listing hooks
# ---------------------------------------------------------------------------


class ListingTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_listing_insert_writes_store_link(self):
		doc = _make_doc("Listing", "LIST-001", seller_profile="STORE-A")
		tuple_sync.on_listing_insert(doc)
		tuples = _ENQUEUED[0]["tuples"]
		self.assertEqual(tuples, [("store:STORE-A", "store_link", "listing:LIST-001")])

	def test_listing_without_seller_skips(self):
		doc = _make_doc("Listing", "LIST-X", seller_profile=None)
		tuple_sync.on_listing_insert(doc)
		self.assertEqual(len(_ENQUEUED), 0)


# ---------------------------------------------------------------------------
# Order hooks
# ---------------------------------------------------------------------------


class OrderTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_order_insert_full(self):
		"""Order = store_link + buyer + buyer_org_link + requisitioner tuple'ları.

		buyer_org, Order.buyer'ın User.tradehub_parent_organization'ından çözülür.
		"""
		# buyer'ın org'u User lookup'tan gelir
		_DB[("get_value", "User", "ali@acme.com", "tradehub_parent_organization")] = "ACME-INC"
		doc = _make_doc(
			"Order",
			"ORD-9382",
			owner="ayse@acme.com",
			seller="STORE-A",
			buyer="ali@acme.com",
		)
		tuple_sync.on_order_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("store:STORE-A", "store_link", "order:ORD-9382"), tuples)
		self.assertIn(("user:ali@acme.com", "buyer", "order:ORD-9382"), tuples)
		self.assertIn(("buyer_org:ACME-INC", "buyer_org_link", "order:ORD-9382"), tuples)
		self.assertIn(("user:ayse@acme.com", "requisitioner", "order:ORD-9382"), tuples)

	def test_order_buyer_no_org(self):
		"""Org'suz (bireysel) buyer → sadece buyer tuple'ı, buyer_org_link YOK."""
		_DB[("get_value", "User", "solo@x.com", "tradehub_parent_organization")] = None
		doc = _make_doc("Order", "ORD-2", owner="Administrator", seller="STORE-A", buyer="solo@x.com")
		tuple_sync.on_order_insert(doc)
		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("user:solo@x.com", "buyer", "order:ORD-2"), tuples)
		self.assertFalse(
			any(t[1] == "buyer_org_link" for t in tuples),
			"org'suz buyer için buyer_org_link yazılmamalı",
		)

	def test_order_administrator_owner_excluded(self):
		"""Administrator tarafından oluşturulan order'da requisitioner skip."""
		doc = _make_doc("Order", "ORD-001", owner="Administrator", seller="STORE-A")
		tuple_sync.on_order_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		# Sadece store_link (buyer yok, requisitioner yok)
		self.assertEqual(len(tuples), 1)
		self.assertEqual(tuples[0], ("store:STORE-A", "store_link", "order:ORD-001"))


# ---------------------------------------------------------------------------
# enqueue_after_commit flag
# ---------------------------------------------------------------------------


class EnqueueAfterCommitTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def test_writes_use_enqueue_after_commit(self):
		"""Tüm async tuple sync DB commit'ten sonra çalışmalı."""
		doc = _make_doc("Listing", "L-1", seller_profile="STORE-A")
		tuple_sync.on_listing_insert(doc)
		self.assertTrue(_ENQUEUED[0].get("enqueue_after_commit"))


class ReconcileTests(unittest.TestCase):
	"""#C6 — reconcile_user beklenen tuple'ları (idempotent) yeniden yazar."""

	def setUp(self):
		_reset_state()

	def test_reconcile_writes_expected_tuples(self):
		_DB[("get_value", "User", "seller@x", "tradehub_tenant")] = "STORE-A"
		_DB[("get_value", "User", "seller@x", "tradehub_parent_organization")] = None
		_ROLES["seller@x"] = ["Seller Owner"]
		n = tuple_sync.reconcile_user("seller@x")
		self.assertGreater(n, 0)
		tuples = [t for e in _ENQUEUED for t in e["tuples"]]
		self.assertIn(("user:seller@x", "owner", "store:STORE-A"), tuples)
		self.assertIn(("user:seller@x", "member", "store:STORE-A"), tuples)

	def test_reconcile_no_tenant_noop(self):
		_DB[("get_value", "User", "nobody@x", "tradehub_tenant")] = None
		_DB[("get_value", "User", "nobody@x", "tradehub_parent_organization")] = None
		n = tuple_sync.reconcile_user("nobody@x")
		self.assertEqual(n, 0)
		self.assertEqual(len(_ENQUEUED), 0)


# ---------------------------------------------------------------------------
# Faz 3 — backfill (enforce öncesi tam tuple basımı)
# ---------------------------------------------------------------------------


class BackfillTests(unittest.TestCase):
	def setUp(self):
		_reset_state()

	def _seed(self):
		def row(name, **f):
			r = SimpleNamespace(name=name, **f)
			r.get = lambda field, default=None: getattr(r, field, default)
			return r

		# Store: SEL-1 owner var, SEL-2 owner YOK (skip edilmeli).
		_DB[("get_all", "Admin Seller Profile", "None", None)] = [
			row("SEL-1", user="owner@x"),
			row("SEL-2", user=None),
		]
		# User: seller@x, SEL-1 tenant + owner flag.
		_DB[("get_all", "User", "{'enabled': 1}", "name")] = ["seller@x"]
		_DB[("get_value", "User", "seller@x", "tradehub_tenant")] = "SEL-1"
		_DB[("get_value", "User", "seller@x", "tradehub_parent_organization")] = None
		_DB[("get_value", "User", "seller@x", "tradehub_is_owner")] = 1
		# Listing: LST-1 seller_profile var, LST-2 YOK (skip).
		_DB[("get_all", "Listing", "None", None)] = [
			row("LST-1", seller_profile="SEL-1"),
			row("LST-2", seller_profile=None),
		]
		# Order: ORD-1 seller_profile var.
		_DB[("get_all", "Order", "None", None)] = [row("ORD-1", seller="SEL-1")]

	def test_dry_run_counts_and_no_write(self):
		self._seed()
		res = tuple_sync.backfill(dry_run=True)
		self.assertEqual(res["stores"], 1, "owner'sız SEL-2 skip edilmeli")
		self.assertEqual(res["listings"], 1, "seller_profile'sız LST-2 skip edilmeli")
		self.assertEqual(res["orders"], 1)
		self.assertEqual(res["users"], 1)
		self.assertGreater(res["tuples"], 0)
		self.assertEqual(len(_ENQUEUED), 0, "dry_run → OpenFGA'ya yazmamalı")

	def test_writes_when_configured(self):
		self._seed()
		orig = tuple_sync._is_rebac_configured
		tuple_sync._is_rebac_configured = lambda: True
		try:
			res = tuple_sync.backfill(chunk_size=2)
		finally:
			tuple_sync._is_rebac_configured = orig
		self.assertNotIn("skipped", res)
		written = [t for e in _ENQUEUED for t in e["tuples"]]
		self.assertIn(("store:SEL-1", "store_link", "listing:LST-1"), written)
		self.assertIn(("store:SEL-1", "store_link", "order:ORD-1"), written)
		self.assertIn(("user:owner@x", "owner", "store:SEL-1"), written)

	def test_skipped_when_not_configured(self):
		self._seed()
		orig = tuple_sync._is_rebac_configured
		tuple_sync._is_rebac_configured = lambda: False
		try:
			res = tuple_sync.backfill()
		finally:
			tuple_sync._is_rebac_configured = orig
		self.assertTrue(res.get("skipped"), "STORE_ID boşken backfill skip etmeli")
		self.assertEqual(len(_ENQUEUED), 0)


if __name__ == "__main__":
	unittest.main()
