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
		self.assertEqual(tuples, [("listing:LIST-001", "store_link", "store:STORE-A")])

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
		"""Order = store_link + buyer_org_link + requisitioner tuple'ları."""
		doc = _make_doc(
			"Order",
			"ORD-9382",
			owner="ayse@acme.com",
			seller_profile="STORE-A",
			buyer_organization="ACME-INC",
		)
		tuple_sync.on_order_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		self.assertIn(("order:ORD-9382", "store_link", "store:STORE-A"), tuples)
		self.assertIn(("order:ORD-9382", "buyer_org_link", "buyer_org:ACME-INC"), tuples)
		self.assertIn(("order:ORD-9382", "requisitioner", "user:ayse@acme.com"), tuples)

	def test_order_administrator_owner_excluded(self):
		"""Administrator tarafından oluşturulan order'da requisitioner skip."""
		doc = _make_doc("Order", "ORD-001", owner="Administrator", seller_profile="STORE-A")
		tuple_sync.on_order_insert(doc)

		tuples = _ENQUEUED[0]["tuples"]
		# Sadece store_link, requisitioner yok
		self.assertEqual(len(tuples), 1)
		self.assertEqual(tuples[0], ("order:ORD-001", "store_link", "store:STORE-A"))


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


if __name__ == "__main__":
	unittest.main()
