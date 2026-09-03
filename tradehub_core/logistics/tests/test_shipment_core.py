# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Faz 4 Dalga C — Shipment cekirdek bench test paketi (LOG-054).

Kapsam: split motoru (create_shipment_draft_from_order / get_remaining_qty),
durum gecis motoru (transition_status / cancel_shipment), snapshot
degismezligi, tenant izolasyonu ve api/v1/shipment uctan uca akisi.

Gecis zincirleri logistics/constants.py ALLOWED_TRANSITIONS matrisine gore
kurulur (kod dogruluk kaynagi): Pending'den Picked Up'a DOGRUDAN gecis
YOKTUR — arada Ready for Pickup zorunludur.

Calistirma:
    docker exec istocc-dev-backend-1 bench --site tradehub.localhost \
        run-tests --module tradehub_core.logistics.tests.test_shipment_core
"""

from __future__ import annotations

import json
import unittest
import unittest.mock as mock

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api.v1 import shipment as shipment_api
from tradehub_core.logistics.constants import LegStatus, ShipmentStatus
from tradehub_core.logistics.exceptions import (
	IdempotencyConflictError,
	ShipmentStateError,
	SplitInvariantError,
)
from tradehub_core.logistics.permissions import (
	shipment_event_has_permission,
	shipment_has_permission,
	shipment_query_conditions,
)
from tradehub_core.logistics.services.shipment_service import cancel_shipment, transition_status
from tradehub_core.logistics.services.split_engine import (
	create_shipment_draft_from_order,
	get_remaining_qty,
)

_ORDER_QTY: int = 10


def _ensure_role(role_name: str) -> None:
	"""Rol yoksa olustur (idempotent — class-sonu rollback ile temizlenir)."""
	if frappe.db.exists("Role", role_name):
		return
	role = frappe.new_doc("Role")
	role.role_name = role_name
	role.desk_access = 0
	role.is_custom = 1
	role.insert(ignore_permissions=True)


def _make_user(email: str, roles: tuple[str, ...] = ()) -> str:
	"""Test kullanicisi olusturur ve rollerini baglar."""
	if not frappe.db.exists("User", email):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": email,
				"first_name": "Logistics",
				"last_name": "Test",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	if roles:
		user_doc = frappe.get_doc("User", email)
		user_doc.add_roles(*roles)
	return email


def _make_seller_profile(user: str, label: str) -> str:
	"""Admin Seller Profile olusturur (autoname=field:seller_code)."""
	return (
		frappe.get_doc(
			{
				"doctype": "Admin Seller Profile",
				"seller_name": f"Shipment Test {label}",
				"seller_code": f"SHPTEST-{frappe.generate_hash(length=8)}",
				"company_name": f"Shipment Test {label} A.S.",
				"user": user,
				"email": user,
			}
		)
		.insert(ignore_permissions=True, ignore_mandatory=True)
		.name
	)


class TestShipmentCore(FrappeTestCase):
	"""Shipment durum motoru + split + izolasyon + API testleri."""

	@classmethod
	def setUpClass(cls) -> None:
		super().setUpClass()
		frappe.set_user("Administrator")

		# get_all: test fixture'i — mevcut herhangi bir Listing yeterli.
		listings = frappe.get_all("Listing", fields=["name"], limit=1)
		if not listings:
			raise unittest.SkipTest("Sitede Listing kaydi yok — fixture kurulamiyor.")
		cls.listing = listings[0].name

		suffix: str = frappe.generate_hash(length=8).lower()

		for role in ("Verified Seller", "Logistics Operator", "Logistics Manager"):
			_ensure_role(role)

		# Seller 1 — siparisin sahibi. KYB gate'i icin Verified Seller sart
		# (Order.validate → _validate_seller_kyb_verified). Logistics Manager:
		# API uctan uca testinde Shipment create DocPerm'i bu rolden gelir;
		# Order'i ise tenant iliskisiyle (order.seller = kendi profili) okur —
		# seller/buyer iliskisi olmayan platform kullanicisi (System Manager
		# dahil) Order tenant izolasyonuna takilir, bu BILINCLIDIR.
		cls.seller1_user = _make_user(
			f"log-seller1-{suffix}@test.local",
			("Verified Seller", "Logistics Operator", "Logistics Manager"),
		)
		cls.seller1 = _make_seller_profile(cls.seller1_user, "Seller1")

		# Seller 2 — cross-tenant izolasyon karsiti (Shipment read DocPerm'i
		# Logistics Operator rolunden gelir; tenant filtresi permissions.py'de).
		# Verified Seller: F3 testi seller2'ye ait Order fixture'i kurar —
		# Order.validate KYB gate'i seller user'inda bu rolu arar.
		cls.seller2_user = _make_user(
			f"log-seller2-{suffix}@test.local", ("Logistics Operator", "Verified Seller")
		)
		cls.seller2 = _make_seller_profile(cls.seller2_user, "Seller2")

		# Seller 3 — P1-1 invariant testi: PLATFORM rolü (Logistics Manager)
		# taşıyan ama seller_profile'ı OLAN kullanıcı tenant-scoped kalmalı;
		# başka tenant'ın sevkiyatına platform-full erişim alamamalı.
		cls.seller3_user = _make_user(f"log-seller3-{suffix}@test.local", ("Logistics Manager",))
		cls.seller3 = _make_seller_profile(cls.seller3_user, "Seller3")

		cls.buyer = _make_user(f"log-buyer-{suffix}@test.local")

	def setUp(self) -> None:
		frappe.set_user("Administrator")
		self.order = self._make_order()
		self.order_item = self.order.items[0].name

	def tearDown(self) -> None:
		frappe.set_user("Administrator")

	# -------------------------------------------------------------------
	# Fixture yardimcilari
	# -------------------------------------------------------------------
	def _make_order(self, seller: str | None = None) -> frappe.model.document.Document:
		"""Verilen seller'a (default seller1) bagli, tek kalemli (qty=_ORDER_QTY) taze Order."""
		return frappe.get_doc(
			{
				"doctype": "Order",
				"buyer": self.buyer,
				"seller": seller or self.seller1,
				"status": "Onaylanıyor",
				"order_date": frappe.utils.now_datetime(),
				"items": [
					{
						"listing": self.listing,
						"listing_title": "Shipment Test Kalemi",
						"quantity": _ORDER_QTY,
						"unit_price": 5,
					}
				],
			}
		).insert(ignore_permissions=True, ignore_mandatory=True)

	def _draft(self, qty: int | None = None, idempotency_key: str | None = None):
		"""Order'dan Draft Shipment uretir (qty=None → tum kalan miktar)."""
		items = None
		if qty is not None:
			items = [{"order_item": self.order_item, "listing": self.listing, "qty": qty}]
		return create_shipment_draft_from_order(self.order.name, items=items, idempotency_key=idempotency_key)

	def _event_count(self, shipment_name: str) -> int:
		return frappe.db.count("Shipment Event", {"shipment": shipment_name})

	def _make_leg(
		self, shipment_name: str, sequence: int = 1, status: str | None = None
	) -> frappe.model.document.Document:
		"""Shipment Leg fixture'i (status None → JSON default Planned)."""
		payload: dict = {
			"doctype": "Shipment Leg",
			"shipment": shipment_name,
			"leg_sequence": sequence,
		}
		if status:
			payload["status"] = status
		return frappe.get_doc(payload).insert(ignore_permissions=True)

	# -------------------------------------------------------------------
	# 1. Split motoru
	# -------------------------------------------------------------------
	def test_create_shipment_from_order(self) -> None:
		"""Taslak Draft acilir, qty kalan miktara esit, Order fulfillment guncellenir."""
		shipment = self._draft()

		self.assertEqual(shipment.status, ShipmentStatus.DRAFT)
		self.assertEqual(len(shipment.items), 1)
		self.assertEqual(shipment.items[0].qty, _ORDER_QTY)
		self.assertEqual(shipment.seller_profile, self.seller1)
		self.assertEqual(get_remaining_qty(self.order_item), 0)

		order_state = frappe.db.get_value(
			"Order", self.order.name, ["fulfillment_status", "shipment_count"], as_dict=True
		)
		self.assertEqual(order_state.fulfillment_status, "Fulfilled")
		self.assertEqual(order_state.shipment_count, 1)

	def test_split_invariant_overship_rejected(self) -> None:
		"""Kalan miktari asan ikinci sevkiyat SplitInvariantError ile reddedilir."""
		self._draft(qty=6)
		self.assertEqual(get_remaining_qty(self.order_item), 4)

		with self.assertRaises(SplitInvariantError):
			self._draft(qty=6)  # 6 + 6 > 10 → INV-1 ihlali

	def test_qty_zero_rejected(self) -> None:
		"""qty=0 satiri SplitInvariantError ile reddedilir (F8a — minimum 1)."""
		with self.assertRaises(SplitInvariantError):
			self._draft(qty=0)

	def test_two_shipments_partial_to_fulfilled(self) -> None:
		"""6+4 split: ilk sevkiyat sonrasi Partially Fulfilled, ikincisi sonrasi Fulfilled."""
		self._draft(qty=6)
		state = frappe.db.get_value(
			"Order", self.order.name, ["fulfillment_status", "shipment_count"], as_dict=True
		)
		self.assertEqual(state.fulfillment_status, "Partially Fulfilled")
		self.assertEqual(state.shipment_count, 1)

		self._draft(qty=4)
		state = frappe.db.get_value(
			"Order", self.order.name, ["fulfillment_status", "shipment_count"], as_dict=True
		)
		self.assertEqual(state.fulfillment_status, "Fulfilled")
		self.assertEqual(state.shipment_count, 2)

	def test_idempotency_conflict(self) -> None:
		"""Ayni idempotency key farkli bir order ile IdempotencyConflictError firlatir (F2)."""
		key: str = f"test-conflict-{frappe.generate_hash(length=10)}"
		self._draft(qty=3, idempotency_key=key)

		other_order = self._make_order()
		with self.assertRaises(IdempotencyConflictError):
			create_shipment_draft_from_order(other_order.name, idempotency_key=key)

	def test_foreign_order_item_rejected(self) -> None:
		"""Seller1 sevkiyatina seller2'nin order_item'i baglanamaz (F3)."""
		foreign_order = self._make_order(seller=self.seller2)
		foreign_item: str = foreign_order.items[0].name

		with self.assertRaises(SplitInvariantError):
			create_shipment_draft_from_order(
				self.order.name,
				items=[{"order_item": foreign_item, "listing": self.listing, "qty": 1}],
			)

	# -------------------------------------------------------------------
	# 2. Durum motoru
	# -------------------------------------------------------------------
	def test_valid_transition_chain(self) -> None:
		"""Draft→Pending→Ready for Pickup→Picked Up→In Transit→Delivered zinciri.

		ALLOWED_TRANSITIONS matrisine gore tek gecerli tam-teslim zinciri budur
		(Pending'den Picked Up'a dogrudan gecis yok). ship_date Picked Up'ta,
		actual_delivery Delivered'da damgalanir.
		"""
		doc = self._draft()
		self.assertIsNone(doc.get("ship_date"))
		self.assertIsNone(doc.get("actual_delivery"))

		doc = transition_status(doc, ShipmentStatus.PENDING, source="Manual")
		doc = transition_status(doc, ShipmentStatus.READY_FOR_PICKUP, source="Manual")
		doc = transition_status(doc, ShipmentStatus.PICKED_UP, source="Manual")
		self.assertIsNotNone(doc.get("ship_date"), "Picked Up gecisi ship_date damgalamali")

		doc = transition_status(doc, ShipmentStatus.IN_TRANSIT, source="Manual")
		doc = transition_status(doc, ShipmentStatus.DELIVERED, source="Manual")

		self.assertEqual(doc.status, ShipmentStatus.DELIVERED)
		self.assertIsNotNone(doc.get("actual_delivery"), "Delivered gecisi actual_delivery damgalamali")

	def test_pending_to_picked_up_rejected(self) -> None:
		"""Pending'den dogrudan Picked Up GECERSIZDIR — arada Ready for Pickup sart.

		NOT: Eski mimari dokumanindaki gevsek matris bu gecise izin veriyordu;
		kod dogruluk kaynagi constants.py ALLOWED_TRANSITIONS'tir ve katidir.
		"""
		doc = self._draft()
		doc = transition_status(doc, ShipmentStatus.PENDING, source="Manual")

		with self.assertRaises(ShipmentStateError):
			transition_status(doc, ShipmentStatus.PICKED_UP, source="Manual")

	def test_invalid_transition_rejected(self) -> None:
		"""Draft'tan dogrudan Delivered gecisi ShipmentStateError firlatir."""
		doc = self._draft()
		with self.assertRaises(ShipmentStateError):
			transition_status(doc, ShipmentStatus.DELIVERED, source="Manual")

	def test_same_status_noop(self) -> None:
		"""Ayni duruma gecis sessiz no-op — event sayisi artmaz."""
		doc = self._draft()
		before_count = self._event_count(doc.name)

		result = transition_status(doc, ShipmentStatus.DRAFT, source="Manual")

		self.assertEqual(result.status, ShipmentStatus.DRAFT)
		self.assertEqual(self._event_count(doc.name), before_count)

	def test_transition_events_created(self) -> None:
		"""Her gecis 1 Shipment Event uretir; internal_status hedef durumdur."""
		doc = self._draft()
		self.assertEqual(self._event_count(doc.name), 0)

		doc = transition_status(doc, ShipmentStatus.PENDING, source="Manual")
		doc = transition_status(doc, ShipmentStatus.READY_FOR_PICKUP, source="Manual")

		# get_all: event append-only sistem kaydi — test dogrulamasi.
		events = frappe.get_all(
			"Shipment Event",
			filters={"shipment": doc.name},
			fields=["internal_status", "source", "seller_profile"],
		)
		self.assertEqual(len(events), 2)
		self.assertEqual(
			{e.internal_status for e in events},
			{ShipmentStatus.PENDING, ShipmentStatus.READY_FOR_PICKUP},
		)
		for event in events:
			self.assertEqual(event.source, "Manual")
			self.assertEqual(event.seller_profile, self.seller1)

	def test_terminal_state_locked(self) -> None:
		"""Cancelled (terminal) sonrasi her gecis denemesi reddedilir."""
		doc = self._draft()
		doc = cancel_shipment(doc, "Test iptali")

		self.assertEqual(doc.status, ShipmentStatus.CANCELLED)
		self.assertIn("Test iptali", doc.internal_note or "")
		# INV-5: iptal kalan miktari geri acar
		self.assertEqual(get_remaining_qty(self.order_item), _ORDER_QTY)

		with self.assertRaises(ShipmentStateError):
			transition_status(doc, ShipmentStatus.PENDING, source="Manual")

	# -------------------------------------------------------------------
	# 3. Adres snapshot degismezligi (F.3)
	# -------------------------------------------------------------------
	def test_snapshot_immutable(self) -> None:
		"""Dolu snapshot satiri kaydedildikten sonra alan degisikligi throw eder."""
		doc = self._draft()

		if not doc.get("address_snapshots"):
			# Test seller'inin Addresses kaydi yok — satiri manuel doldur.
			doc.append(
				"address_snapshots",
				{
					"snapshot_type": "Origin",
					"contact_name": "Test Gonderen",
					"city": "Istanbul",
					"country": "Turkey",
					"street": "Test Cad. No:1",
				},
			)
			doc.save()

		doc.reload()
		self.assertTrue(doc.get("address_snapshots"))

		doc.address_snapshots[0].city = "Ankara"
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_item_snapshot_immutable(self) -> None:
		"""Insert sonrasi unit_price degisikligi throw eder; qty degisikligi serbesttir (F7)."""
		doc = self._draft(qty=6)

		doc.items[0].unit_price = 999
		with self.assertRaises(frappe.ValidationError):
			doc.save()

		doc.reload()
		doc.items[0].qty = 4  # qty duzenlenebilir — INV-1 yeniden kosar
		doc.save()
		self.assertEqual(frappe.db.get_value("Shipment Item", doc.items[0].name, "qty"), 4)

	# -------------------------------------------------------------------
	# 4. Tenant izolasyonu
	# -------------------------------------------------------------------
	def test_cross_tenant_isolation(self) -> None:
		"""Ikinci seller, birinci seller'in sevkiyatini ne listede gorur ne okuyabilir."""
		shipment = self._draft()

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(self.seller2_user)

		# get_list → shipment_query_conditions devrede (seller_profile filtresi)
		visible = frappe.get_list("Shipment", pluck="name", limit_page_length=0)
		self.assertNotIn(shipment.name, visible)

		# Per-doc katman: has_permission hook'u da reddetmeli
		self.assertFalse(shipment_has_permission(shipment, "read", self.seller2_user))
		# Kendi tenant'inin sahibi ise okuyabilir (kontrol grubu)
		self.assertTrue(shipment_has_permission(shipment, "read", self.seller1_user))

	def test_cross_tenant_event_isolation(self) -> None:
		"""Seller2, seller1'in Shipment Event'lerini ne listede gorur ne per-doc okuyabilir (F1)."""
		doc = self._draft()
		transition_status(doc, ShipmentStatus.PENDING, source="Manual")

		# get_all: fixture dogrulamasi (Administrator context).
		event_names = frappe.get_all("Shipment Event", filters={"shipment": doc.name}, pluck="name")
		self.assertTrue(event_names, "Gecis en az 1 Shipment Event uretmeli")
		event = frappe.get_doc("Shipment Event", event_names[0])
		self.assertEqual(event.seller_profile, self.seller1)

		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(self.seller2_user)

		# get_list → shipment_event_query_conditions devrede (seller_profile filtresi)
		visible = frappe.get_list("Shipment Event", pluck="name", limit_page_length=0)
		self.assertNotIn(event.name, visible)

		# Per-doc katman: has_permission hook'u da reddetmeli
		self.assertFalse(shipment_event_has_permission(event, "read", self.seller2_user))
		# Kendi tenant'i okuyabilir (kontrol grubu)
		self.assertTrue(shipment_event_has_permission(event, "read", self.seller1_user))

	# -------------------------------------------------------------------
	# 5. API katmani (api/v1/shipment.py)
	# -------------------------------------------------------------------
	def test_api_create_and_status(self) -> None:
		"""create_shipment + update_shipment_status uctan uca (seller-tarafi kullanici).

		Kullanici seller1: Order'i tenant iliskisiyle okur (order.seller =
		kendi profili), Shipment create/write'i Logistics Manager DocPerm'iyle
		yapar. Platform ops (LM/SM) personasinin baska tenant'in Order'ini
		OKUYAMAMASI bilinclidir — Order read tenant izolasyonu uzerinden
		verilir; sevkiyat olusturma API'sinin seller-tarafi personasi
		Gorev 06/07'de netlesecek.
		"""
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.set_user(self.seller1_user)

		created = shipment_api.create_shipment(order=self.order.name)
		self.assertTrue(created["ok"])
		self.assertEqual(created["meta"]["api_version"], "v1")
		self.assertEqual(created["data"]["status"], ShipmentStatus.DRAFT)
		self.assertEqual(created["data"]["order"], self.order.name)
		name: str = created["data"]["name"]

		updated = shipment_api.update_shipment_status(name, ShipmentStatus.PENDING)
		self.assertTrue(updated["ok"])
		self.assertEqual(updated["data"]["previous_status"], ShipmentStatus.DRAFT)
		self.assertEqual(updated["data"]["status"], ShipmentStatus.PENDING)

		# Gecis matrisi API yolunda da gecerli: Pending → Picked Up reddedilir.
		# @logistics_endpoint (E2E bulgu A) hatayi zarfa cevirir; _fail icindeki
		# frappe.db.rollback commit edilmemis PAYLASILAN fixture'lari (order
		# kalan miktari) ucurup kardes testleri kirmasin diye mock'lanir —
		# rollback davranisinin kendisi test_logistics_api_utils'te kilitli.
		with mock.patch("frappe.db.rollback"):
			rejected = shipment_api.update_shipment_status(name, ShipmentStatus.PICKED_UP)
		self.assertFalse(rejected["ok"])
		self.assertEqual(rejected["error"]["code"], ShipmentStateError.code)

		self.assertEqual(frappe.db.get_value("Shipment", name, "status"), ShipmentStatus.PENDING)

	def test_idempotent_create(self) -> None:
		"""Ayni idempotency_key ile iki create ayni shipment'i dondurur."""
		key: str = f"test-idem-{frappe.generate_hash(length=10)}"
		items_json: str = json.dumps([{"order_item": self.order_item, "listing": self.listing, "qty": 3}])

		first = shipment_api.create_shipment(order=self.order.name, items=items_json, idempotency_key=key)
		second = shipment_api.create_shipment(order=self.order.name, items=items_json, idempotency_key=key)

		self.assertEqual(first["data"]["name"], second["data"]["name"])
		self.assertEqual(frappe.db.count("Shipment", {"idempotency_key": key}), 1)
		# Ikinci cagri yeni kalem sevk etmedi — kalan miktar degismedi.
		self.assertEqual(get_remaining_qty(self.order_item), _ORDER_QTY - 3)

	def test_api_missing_shipment_returns_not_found_envelope(self) -> None:
		"""E2E bulgu A: olmayan sevkiyat ham DoesNotExistError DEGIL, NOT_FOUND zarfi doner.

		Panel dallanmasi error.code uzerinden yapilir (logisticsEnvelope.js);
		zarfsiz ham hata panelde INTERNAL_ERROR + Ingilizce mesaj gosteriyordu.
		"""
		missing: str = f"SHP-YOK-{frappe.generate_hash(length=8)}"

		calls = (
			lambda: shipment_api.get_shipment_detail(missing),
			lambda: shipment_api.update_shipment_status(missing, ShipmentStatus.PENDING),
			lambda: shipment_api.cancel_shipment(missing),
		)
		for call in calls:
			frappe.local.response.pop("http_status_code", None)
			# _fail icindeki rollback commit edilmemis class fixture'larini
			# ucurmasin (order/seller kayitlari) — mock'lanir.
			with mock.patch("frappe.db.rollback"):
				result = call()
			self.assertFalse(result["ok"])
			self.assertEqual(result["error"]["code"], "NOT_FOUND")
			self.assertEqual(frappe.local.response.get("http_status_code"), 404)
			# i18n: get_doc'un Ingilizce ham mesaji degil, Turkce mesaj doner.
			self.assertIn(missing, result["error"]["message"])

	def test_api_create_missing_order_returns_not_found_envelope(self) -> None:
		"""E2E bulgu A: create_shipment'ta olmayan Order da NOT_FOUND zarfina esler."""
		frappe.local.response.pop("http_status_code", None)

		with mock.patch("frappe.db.rollback"):
			result = shipment_api.create_shipment(order=f"ORD-YOK-{frappe.generate_hash(length=8)}")

		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], "NOT_FOUND")
		self.assertEqual(frappe.local.response.get("http_status_code"), 404)

	# -------------------------------------------------------------------
	# 6. P1 duzeltme paketi (guvenlik/butunluk)
	# -------------------------------------------------------------------
	def test_platform_role_with_tenant_scoped(self) -> None:
		"""P1-1: seller_profile'li kullanici Logistics Manager rolu tasisa bile tenant-scoped kalir.

		Platform-full dallar (bos filtre / kosulsuz True) yalniz seller_profile'i
		OLMAYAN kullaniciya uygulanir — baska tenant'in sevkiyati ne listelenir
		ne okunur ne yazilir ne iptal edilir.
		"""
		shipment = self._draft()  # seller1 tenant'inin sevkiyati

		# Liste katmani: platform-full bos filtre DONMEMELI, tenant filtresi donmeli.
		condition: str = shipment_query_conditions(self.seller3_user)
		self.assertNotEqual(condition, "")
		self.assertIn(self.seller3, condition)

		# Per-doc katman: cross-tenant erisim tum ptype'larda reddedilir.
		self.assertFalse(shipment_has_permission(shipment, "read", self.seller3_user))
		self.assertFalse(shipment_has_permission(shipment, "write", self.seller3_user))
		self.assertFalse(shipment_has_permission(shipment, "cancel", self.seller3_user))

	def test_new_shipment_must_be_draft(self) -> None:
		"""P1-3: yeni Shipment yalniz Draft ile dogar — Delivered-insert baypasi kapali."""
		with self.assertRaises(ShipmentStateError):
			frappe.get_doc(
				{
					"doctype": "Shipment",
					"order": self.order.name,
					"seller_profile": self.seller1,
					"buyer": self.buyer,
					"status": ShipmentStatus.DELIVERED,
					"items": [{"order_item": self.order_item, "listing": self.listing, "qty": 1}],
				}
			).insert(ignore_permissions=True)

	def test_delete_updates_fulfillment(self) -> None:
		"""P1-2: sevkiyat silinince Order fulfillment_status + shipment_count tazelenir."""
		shipment = self._draft()
		state = frappe.db.get_value(
			"Order", self.order.name, ["fulfillment_status", "shipment_count"], as_dict=True
		)
		self.assertEqual(state.fulfillment_status, "Fulfilled")
		self.assertEqual(state.shipment_count, 1)

		shipment.delete()

		state = frappe.db.get_value(
			"Order", self.order.name, ["fulfillment_status", "shipment_count"], as_dict=True
		)
		self.assertEqual(state.fulfillment_status, "Unfulfilled")
		self.assertEqual(state.shipment_count, 0)

	def test_leg_completed_terminal(self) -> None:
		"""P1-5: Completed bacak terminaldir — Cancelled'a dahi gecilemez."""
		shipment = self._draft()
		leg = self._make_leg(shipment.name)

		for status in (LegStatus.IN_PROGRESS, LegStatus.ARRIVED, LegStatus.COMPLETED):
			leg.status = status
			leg.save(ignore_permissions=True)

		leg.status = LegStatus.CANCELLED
		with self.assertRaises(frappe.ValidationError):
			leg.save(ignore_permissions=True)

	def test_leg_insert_only_planned(self) -> None:
		"""P1-5: yeni bacak yalniz Planned durumuyla insert edilebilir."""
		shipment = self._draft()
		with self.assertRaises(frappe.ValidationError):
			self._make_leg(shipment.name, status=LegStatus.COMPLETED)

	def test_leg_sequence_unique(self) -> None:
		"""P1-5: ayni Shipment icinde leg_sequence tekildir; farkli sira serbesttir."""
		shipment = self._draft()
		self._make_leg(shipment.name, sequence=1)

		with self.assertRaises(frappe.ValidationError):
			self._make_leg(shipment.name, sequence=1)

		second = self._make_leg(shipment.name, sequence=2)
		self.assertTrue(second.name)

	def test_empty_idempotency_key(self) -> None:
		"""P1-6a: '' idempotency key None'a normalize edilir — iki bos-key create cakismaz."""
		first = self._draft(qty=3, idempotency_key="")
		second = self._draft(qty=3, idempotency_key="")

		self.assertNotEqual(first.name, second.name)
		self.assertIsNone(frappe.db.get_value("Shipment", first.name, "idempotency_key"))
		self.assertIsNone(frappe.db.get_value("Shipment", second.name, "idempotency_key"))

	def test_buyer_can_read_own_shipment(self) -> None:
		"""P1-6f: buyer (seller_profile'siz) kendi siparisinin sevkiyatini okuyabilir, yazamaz."""
		shipment = self._draft()

		self.assertTrue(shipment_has_permission(shipment, "read", self.buyer))
		self.assertFalse(shipment_has_permission(shipment, "write", self.buyer))
