"""BE-1 — Vitrin pasifleştirme servisi testleri (services/storefront_visibility).

Kapsam:
  - hide_store_listings: yalnız hedef mağazanın storefront_visible kolonunu
    0'lar; status/is_visible'a DOKUNMAZ; idempotent; parametreli sorgu;
    invalidate_listing_cache çağrılır (AC-4).
  - restore_store_listings: storefront_visible = (status IN
    STOREFRONT_VISIBLE_STATUSES AND is_visible) formülünden yeniden hesap —
    satıcının kendi gizlediği (is_visible=0) ürün restore'da gizli KALIR;
    idempotent (AC-6).
  - Drift guard (AC-9, K2 genişletmesi): Listing._set_storefront_visible,
    mağazanın Store Subscription status'u NON-OPERASYONELKEN (suspended /
    canceled / expired — entitlement._OPERATIONAL_STATUSES dışı)
    storefront_visible'ı 1'e çevirmez; operasyonelken (trial/active/past_due)
    ve ABONELİKSİZ mağazada (status=None) mevcut formül davranışı DEĞİŞMEZ;
    guard maliyeti tek get_value ve yalnız formül 1 döndüğünde ödenir.
  - BE-5 / AC-10 — kota-kontrollü restore: quota.max_products sonluysa formül
    sonrası en yeni N ürün vitrinde kalır, fazlası gizlenir; limit -1/tanımsız
    → bugünkü davranış (trim yok); is_visible=0 her durumda gizli; idempotent
    (ikinci koşu veri değiştirmez, bildirim TEKRARLAMAZ); owner yoksa bildirim
    sessiz atlanır, audit kaydı yine düşer.

    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_storefront_visibility
"""

from __future__ import annotations

import copy
import itertools
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


class _ValidationError(Exception):
	pass


# Gerçek sabitle aynı küme (api/listing.py) — stub modüle de bu verilir.
_VISIBLE_STATUSES = ("Active", "Out of Stock")

_STATE: dict = {}


def _reset_state() -> None:
	_STATE.update(
		{
			# name -> Listing satırı (seller_profile, status, is_visible, storefront_visible)
			"listings": {},
			# store -> Store Subscription status (drift guard için)
			"sub_status": {},
			"cache_invalidations": 0,  # invalidate_listing_cache çağrı sayısı
			"sql_calls": [],  # (normalize edilmiş query, values)
			"affected": [],  # her sql çağrısında storefront_visible'ı DEĞİŞEN listing adları
			"get_value_calls": [],  # (doctype, filters) — drift guard tek get_value iddiası
			# --- BE-5 / AC-10 ---
			"quota": {},  # store -> get_quota_limits(store) dönüşü ({} = aboneliksiz)
			"owners": {},  # store -> Admin Seller Profile.user (yoksa bildirim sessiz atlanır)
			"notifications": [],  # notify(**kw) çağrıları
			"audit_logs": [],  # log_decision(**kw) çağrıları
		}
	)


def _db_sql(query: str, values: tuple | None = None, **kw) -> tuple:
	"""SELECT + iki toplu UPDATE deseninin mini yorumlayıcısı.

	Yalnız servisin üretmesi beklenen sorguları tanır; başka SQL gelirse test
	patlar (yanlışlıkla farklı sorgu yazılmasına karşı emniyet)."""
	q = " ".join(query.split())
	vals = tuple(values or ())
	_STATE["sql_calls"].append((q, vals))

	# f-string SQL yasak: değerler query gövdesine gömülmemeli, %s ile gitmeli.
	assert "%s" in q, "parametresiz sorgu (f-string SQL?)"
	for v in vals:
		assert str(v) not in q, f"deger query'ye gomulmus: {v!r}"

	if q.startswith("SELECT name FROM `tabListing`"):
		# BE-5 okumaları: çağrı-başı vitrin fotoğrafı + creation DESC trim adayları.
		assert "WHERE seller_profile = %s AND storefront_visible = 1" in q, q
		store = vals[0]
		rows = [
			(name, row)
			for name, row in _STATE["listings"].items()
			if row["seller_profile"] == store and row["storefront_visible"] == 1
		]
		if "ORDER BY" in q:
			# Deterministik keep-set sözleşmesi: creation DESC, eşitlikte name DESC.
			assert "ORDER BY creation DESC, name DESC" in q, q
			rows.sort(key=lambda item: (item[1]["creation"], item[0]), reverse=True)
		return tuple((name,) for name, _row in rows)

	# status/is_visible'a yazma yasak — SET yalnız storefront_visible olmalı.
	assert q.startswith("UPDATE `tabListing` SET storefront_visible"), q

	changed: list[str] = []
	if "SET storefront_visible = 0" in q:
		# hide deseni + BE-5 trim deseni (yalnız adlandırılmış satırlar kapanır)
		assert "WHERE seller_profile = %s AND storefront_visible = 1" in q, q
		store = vals[0]
		names = set(vals[1:]) if "AND name IN (" in q else None
		for name, row in _STATE["listings"].items():
			if row["seller_profile"] != store or row["storefront_visible"] != 1:
				continue
			if names is not None and name not in names:
				continue
			row["storefront_visible"] = 0
			changed.append(name)
	elif "IF(is_visible = 1 AND status IN" in q:
		# restore deseni (backfill formülü, mağaza-scoped)
		assert "WHERE seller_profile = %s" in q, q
		statuses, store = vals[:-1], vals[-1]
		for name, row in _STATE["listings"].items():
			if row["seller_profile"] != store:
				continue
			new = 1 if (row["is_visible"] == 1 and row["status"] in statuses) else 0
			if row["storefront_visible"] != new:
				row["storefront_visible"] = new
				changed.append(name)
	else:
		raise AssertionError(f"stub desteklemiyor: {q}")
	_STATE["affected"].append(changed)
	return ()


def _db_get_value(doctype: str, filters=None, fieldname=None, order_by=None, **kw):
	if doctype == "Store Subscription":
		_STATE["get_value_calls"].append((doctype, dict(filters or {})))
		return _STATE["sub_status"].get((filters or {}).get("store"))
	if doctype == "Admin Seller Profile":
		# BE-5: owner lookup — get_value("Admin Seller Profile", store, "user")
		assert fieldname == "user", fieldname
		return _STATE["owners"].get(filters)
	raise AssertionError(f"stub desteklemiyor: get_value({doctype})")


def _install_stubs() -> None:
	frappe = types.ModuleType("frappe")
	sys.modules["frappe"] = frappe
	frappe.ValidationError = _ValidationError
	frappe.PermissionError = PermissionError  # entitlement.core import'u için
	frappe._ = lambda s: s

	def _throw(msg, exc=_ValidationError, **kw):
		raise exc(msg)

	frappe.throw = _throw
	frappe.log_error = lambda *a, **k: None
	frappe.logger = lambda *a, **k: SimpleNamespace(info=lambda *a, **k: None)
	frappe.db = SimpleNamespace(sql=_db_sql, get_value=_db_get_value, commit=lambda: None)

	utils = types.ModuleType("frappe.utils")
	utils.flt = lambda v, precision=None: float(v or 0)
	utils.now_datetime = lambda: None
	sys.modules["frappe.utils"] = utils

	model = types.ModuleType("frappe.model")
	document = types.ModuleType("frappe.model.document")

	class _Document:
		pass

	document.Document = _Document
	sys.modules["frappe.model"] = model
	sys.modules["frappe.model.document"] = document

	# api/listing.py 3400 satırlık gerçek modül — servis yalnız iki sembol
	# kullanıyor, stub'lanır; invalidate çağrısı sayaçla doğrulanır.
	api_listing = types.ModuleType("tradehub_core.api.listing")
	api_listing.STOREFRONT_VISIBLE_STATUSES = _VISIBLE_STATUSES

	def _invalidate_listing_cache(doc=None, method=None):
		_STATE["cache_invalidations"] += 1

	api_listing.invalidate_listing_cache = _invalidate_listing_cache
	sys.modules["tradehub_core.api.listing"] = api_listing

	# Listing controller'ın top-level import'ları (guard testinde gerçek
	# controller yüklenir, bu yardımcılar test kapsamı dışı).
	content_i18n = types.ModuleType("tradehub_core.utils.content_i18n")
	content_i18n.sync_content_translations = lambda doc: None
	sys.modules["tradehub_core.utils.content_i18n"] = content_i18n

	notify_mod = types.ModuleType("tradehub_core.utils.notify")

	def _notify(**kw) -> str:
		_STATE["notifications"].append(kw)
		return "PN-TEST"

	notify_mod.notify = _notify
	sys.modules["tradehub_core.utils.notify"] = notify_mod

	# BE-5: audit paketi (log_decision + ADL sabitleri) — gerçek paket frappe
	# runtime'ına gider, stub kayıt tutar; sabit değerler audit/log.py ile aynı.
	audit_mod = types.ModuleType("tradehub_core.audit")
	audit_mod.DECISION_DENY = "DENY"
	audit_mod.LAYER_L0 = "L0"
	audit_mod.SEVERITY_NORMAL = "NORMAL"

	def _log_decision(**kw) -> str:
		_STATE["audit_logs"].append(kw)
		return "ADL-TEST"

	audit_mod.log_decision = _log_decision
	sys.modules["tradehub_core.audit"] = audit_mod


_install_stubs()

from tradehub_core.entitlement import core as entitlement_core  # noqa: E402
from tradehub_core.entitlement.core import get_subscription_status  # noqa: E402, F401
from tradehub_core.services import storefront_visibility  # noqa: E402
from tradehub_core.tradehub_core.doctype.listing.listing import Listing  # noqa: E402

# BE-5: servis get_quota_limits'i çağrı anında lazy-import eder. Gerçek
# implementasyon frappe.cache + Store Subscription doc'una gider; testte
# sözleşmesi stub'lanır ({} = aboneliksiz → anahtar yok → trim yok).
entitlement_core.get_quota_limits = lambda store: dict(_STATE["quota"].get(store, {}))

# Seed sırası = creation sırası: SONRA eklenen daha YENİDİR (trim keep-set'i
# "creation DESC ilk N" olduğundan test kurgusunda kritik).
_CREATION_SEQ = itertools.count(1)


def _listing(
	name: str,
	store: str = "SELLER-A",
	status: str = "Active",
	is_visible: int = 1,
	sfv: int | None = None,
) -> dict:
	row = {
		"seller_profile": store,
		"status": status,
		"is_visible": is_visible,
		"creation": next(_CREATION_SEQ),
		# sfv verilmezse mevcut formülden hesapla (üretimdeki tutarlı başlangıç)
		"storefront_visible": sfv
		if sfv is not None
		else (1 if (is_visible and status in _VISIBLE_STATUSES) else 0),
	}
	_STATE["listings"][name] = row
	return row


def _seed_mixed_store() -> None:
	"""SELLER-A: karışık set + SELLER-B kontrol grubu."""
	_listing("L-VIS", status="Active", is_visible=1)  # vitrinde
	_listing("L-OOS", status="Out of Stock", is_visible=1)  # vitrinde
	_listing("L-HIDDEN", status="Active", is_visible=0)  # satıcı kendisi gizlemiş
	_listing("L-PENDING", status="Pending", is_visible=1)  # statü gereği görünmez
	_listing("L-OTHER", store="SELLER-B", status="Active", is_visible=1)  # başka mağaza


class TestHideStoreListings(unittest.TestCase):
	"""AC-4 — suspend anında toplu vitrin kapatma."""

	def setUp(self):
		_reset_state()
		_seed_mixed_store()

	def test_hide_zeroes_all_target_store_rows_only(self):
		storefront_visibility.hide_store_listings("SELLER-A")
		for name in ("L-VIS", "L-OOS", "L-HIDDEN", "L-PENDING"):
			self.assertEqual(_STATE["listings"][name]["storefront_visible"], 0, name)
		self.assertEqual(_STATE["listings"]["L-OTHER"]["storefront_visible"], 1, "Başka mağaza etkilenmemeli")

	def test_hide_does_not_touch_status_or_is_visible(self):
		before = copy.deepcopy(_STATE["listings"])
		storefront_visibility.hide_store_listings("SELLER-A")
		for name, row in _STATE["listings"].items():
			self.assertEqual(row["status"], before[name]["status"], name)
			self.assertEqual(row["is_visible"], before[name]["is_visible"], name)

	def test_hide_idempotent_second_run_changes_nothing(self):
		storefront_visibility.hide_store_listings("SELLER-A")
		snapshot = copy.deepcopy(_STATE["listings"])
		storefront_visibility.hide_store_listings("SELLER-A")
		self.assertEqual(_STATE["listings"], snapshot)
		self.assertEqual(_STATE["affected"][-1], [], "İkinci koşu hiçbir satırı değiştirmemeli")

	def test_hide_invalidates_listing_cache(self):
		storefront_visibility.hide_store_listings("SELLER-A")
		self.assertEqual(_STATE["cache_invalidations"], 1)

	def test_hide_requires_store(self):
		with self.assertRaises(_ValidationError):
			storefront_visibility.hide_store_listings("")
		self.assertEqual(_STATE["sql_calls"], [], "store'suz çağrı SQL koşturmamalı")


class TestRestoreStoreListings(unittest.TestCase):
	"""AC-6 — active'e dönüşte formülden yeniden hesap."""

	def setUp(self):
		_reset_state()
		_seed_mixed_store()

	def test_restore_after_hide_respects_seller_own_hidden(self):
		# Suspend → restore tam döngüsü: karışık is_visible seti.
		storefront_visibility.hide_store_listings("SELLER-A")
		storefront_visibility.restore_store_listings("SELLER-A")
		rows = _STATE["listings"]
		self.assertEqual(rows["L-VIS"]["storefront_visible"], 1, "Aktif+görünür geri açılmalı")
		self.assertEqual(rows["L-OOS"]["storefront_visible"], 1, "Out of Stock vitrin statüsü")
		self.assertEqual(
			rows["L-HIDDEN"]["storefront_visible"], 0, "Satıcının kendi gizlediği ürün gizli KALIR"
		)
		self.assertEqual(rows["L-PENDING"]["storefront_visible"], 0, "Pending vitrine çıkmaz")
		self.assertEqual(rows["L-OTHER"]["storefront_visible"], 1, "Başka mağaza etkilenmemeli")

	def test_restore_does_not_touch_status_or_is_visible(self):
		storefront_visibility.hide_store_listings("SELLER-A")
		before = copy.deepcopy(_STATE["listings"])
		storefront_visibility.restore_store_listings("SELLER-A")
		for name, row in _STATE["listings"].items():
			self.assertEqual(row["status"], before[name]["status"], name)
			self.assertEqual(row["is_visible"], before[name]["is_visible"], name)

	def test_restore_idempotent_second_run_changes_nothing(self):
		storefront_visibility.hide_store_listings("SELLER-A")
		storefront_visibility.restore_store_listings("SELLER-A")
		snapshot = copy.deepcopy(_STATE["listings"])
		storefront_visibility.restore_store_listings("SELLER-A")
		self.assertEqual(_STATE["listings"], snapshot)
		self.assertEqual(_STATE["affected"][-1], [], "İkinci restore hiçbir satırı değiştirmemeli")

	def test_restore_invalidates_listing_cache(self):
		storefront_visibility.restore_store_listings("SELLER-A")
		self.assertEqual(_STATE["cache_invalidations"], 1)

	def test_restore_requires_store(self):
		with self.assertRaises(_ValidationError):
			storefront_visibility.restore_store_listings("")
		self.assertEqual(_STATE["sql_calls"], [], "store'suz çağrı SQL koşturmamalı")

	def test_queries_are_parameterized(self):
		storefront_visibility.hide_store_listings("SELLER-A")
		storefront_visibility.restore_store_listings("SELLER-A")
		for q, vals in _STATE["sql_calls"]:
			self.assertIn("%s", q)
			self.assertIn("SELLER-A", vals, "Mağaza adı parametre olarak gitmeli")
			self.assertNotIn("SELLER-A", q, "Mağaza adı query gövdesine gömülmemeli")


class TestQuotaControlledRestore(unittest.TestCase):
	"""BE-5 / AC-10 — kota-kontrollü restore (quota.max_products)."""

	STORE = "SELLER-A"
	OWNER = "owner-a@example.com"

	def setUp(self):
		_reset_state()
		# Vitrin-uygun 4 ürün, seed sırası = yaş sırası: L-Q1 en ESKİ, L-Q4 en YENİ.
		_listing("L-Q1")
		_listing("L-Q2")
		_listing("L-Q3")
		_listing("L-Q4")
		_listing("L-QHIDDEN", is_visible=0)  # satıcı gizlemiş — kota sayımına girmez
		_listing("L-QPENDING", status="Pending")  # statü gereği görünmez
		_listing("L-QB", store="SELLER-B")  # kontrol grubu: başka mağaza
		_STATE["owners"][self.STORE] = self.OWNER

	def _set_limit(self, limit: int) -> None:
		_STATE["quota"][self.STORE] = {"quota.max_products": limit}

	def _dunning_cycle(self) -> None:
		"""Üretimdeki gerçek akış: suspend (hide) → ödeme → restore."""
		storefront_visibility.hide_store_listings(self.STORE)
		storefront_visibility.restore_store_listings(self.STORE)

	def _visible(self) -> set[str]:
		return {
			name
			for name, row in _STATE["listings"].items()
			if row["seller_profile"] == self.STORE and row["storefront_visible"] == 1
		}

	def test_limit_above_count_no_trim_no_notification(self):
		self._set_limit(10)
		self._dunning_cycle()
		self.assertEqual(self._visible(), {"L-Q1", "L-Q2", "L-Q3", "L-Q4"})
		self.assertEqual(_STATE["notifications"], [], "Limit altında bildirim olmamalı")
		self.assertEqual(_STATE["audit_logs"], [], "Limit altında audit kaydı olmamalı")

	def test_limit_exceeded_keeps_newest_n(self):
		self._set_limit(2)
		self._dunning_cycle()
		self.assertEqual(self._visible(), {"L-Q3", "L-Q4"}, "creation DESC ilk N (en yeni) kalmalı")
		self.assertEqual(_STATE["listings"]["L-QB"]["storefront_visible"], 1, "Başka mağaza etkilenmemeli")
		self.assertEqual(len(_STATE["notifications"]), 1, "Trim'de TEK bildirim gitmeli")
		self.assertEqual(_STATE["cache_invalidations"], 2, "hide + restore birer invalidation")

	def test_unlimited_minus_one_no_trim(self):
		self._set_limit(-1)
		self._dunning_cycle()
		self.assertEqual(self._visible(), {"L-Q1", "L-Q2", "L-Q3", "L-Q4"})
		self.assertEqual(_STATE["notifications"], [])

	def test_undefined_quota_no_trim(self):
		# get_quota_limits {} döner (aboneliksiz) → anahtar yok → güvenli taraf.
		self._dunning_cycle()
		self.assertEqual(self._visible(), {"L-Q1", "L-Q2", "L-Q3", "L-Q4"})
		self.assertEqual(_STATE["notifications"], [])
		self.assertEqual(_STATE["audit_logs"], [])

	def test_limit_zero_hides_all(self):
		# within_quota semantiği: 0 = devre dışı → trim TAMAMINI kapatır.
		# Görünür ön-durumdan restore: net değişiklik var → tek bildirim + audit.
		self._set_limit(0)
		storefront_visibility.restore_store_listings(self.STORE)
		self.assertEqual(self._visible(), set())
		self.assertEqual(len(_STATE["notifications"]), 1)
		self.assertEqual(_STATE["audit_logs"][0]["context"], {"limit": 0, "trimmed_count": 4})
		# İkinci koşu: durum artık kota-uyumlu → veri ve bildirim değişmez.
		storefront_visibility.restore_store_listings(self.STORE)
		self.assertEqual(self._visible(), set())
		self.assertEqual(len(_STATE["notifications"]), 1, "Bildirim TEKRARLAMAMALI")

	def test_limit_zero_after_full_hide_stays_silent(self):
		# Uç durum: suspend döneminde vitrin ZATEN tamamen kapalıyken limit 0 ile
		# restore net değişiklik üretmez → bildirim/audit YOK (idempotency gereği:
		# durum değişmeyen koşuda bildirim verilse her koşuda tekrarlardı).
		self._set_limit(0)
		self._dunning_cycle()
		self.assertEqual(self._visible(), set())
		self.assertEqual(_STATE["notifications"], [])
		self.assertEqual(_STATE["audit_logs"], [])

	def test_is_visible_mixture_preserved(self):
		self._set_limit(3)
		before = copy.deepcopy(_STATE["listings"])
		self._dunning_cycle()
		self.assertEqual(self._visible(), {"L-Q2", "L-Q3", "L-Q4"})
		rows = _STATE["listings"]
		self.assertEqual(rows["L-QHIDDEN"]["storefront_visible"], 0, "Satıcının gizlediği gizli KALIR")
		self.assertEqual(rows["L-QPENDING"]["storefront_visible"], 0, "Pending vitrine çıkmaz")
		for name, row in rows.items():
			self.assertEqual(row["status"], before[name]["status"], name)
			self.assertEqual(row["is_visible"], before[name]["is_visible"], name)

	def test_notification_and_audit_content(self):
		self._set_limit(1)
		self._dunning_cycle()
		note = _STATE["notifications"][0]
		self.assertEqual(note["recipient_user"], self.OWNER)
		self.assertEqual(note["reference_doctype"], "Admin Seller Profile")
		self.assertEqual(note["reference_name"], self.STORE)
		self.assertIn("3", note["message"], "Mesaj trim edilen ürün sayısını içermeli")
		audit = _STATE["audit_logs"][0]
		self.assertEqual(audit["decision"], "DENY")
		self.assertEqual(audit["layer"], "L0")
		self.assertEqual(audit["severity"], "NORMAL")
		self.assertEqual(audit["tenant"], self.STORE)
		self.assertEqual(audit["context"], {"limit": 1, "trimmed_count": 3})

	def test_idempotent_second_run_no_second_notification(self):
		self._set_limit(2)
		self._dunning_cycle()
		snapshot = copy.deepcopy(_STATE["listings"])
		storefront_visibility.restore_store_listings(self.STORE)
		self.assertEqual(_STATE["listings"], snapshot, "İkinci restore veri durumunu değiştirmemeli")
		self.assertEqual(len(_STATE["notifications"]), 1, "Bildirim TEKRARLAMAMALI")
		self.assertEqual(len(_STATE["audit_logs"]), 1, "Audit kaydı TEKRARLAMAMALI")

	def test_missing_owner_silent_but_audited(self):
		_STATE["owners"].clear()
		self._set_limit(2)
		self._dunning_cycle()
		self.assertEqual(self._visible(), {"L-Q3", "L-Q4"}, "Owner yokken trim yine uygulanmalı")
		self.assertEqual(_STATE["notifications"], [], "Owner yoksa bildirim SESSİZCE atlanmalı")
		self.assertEqual(len(_STATE["audit_logs"]), 1, "Audit kaydı yine düşmeli")

	def test_trim_update_is_parameterized(self):
		self._set_limit(2)
		self._dunning_cycle()
		trim_calls = [(q, vals) for q, vals in _STATE["sql_calls"] if "AND name IN (" in q]
		self.assertEqual(len(trim_calls), 1)
		q, vals = trim_calls[0]
		self.assertEqual(vals[0], self.STORE)
		self.assertEqual(set(vals[1:]), {"L-Q1", "L-Q2"}, "Yalnız limit dışı adlar parametre gitmeli")
		for v in vals:
			self.assertNotIn(str(v), q, "Değerler query gövdesine gömülmemeli")


class _GuardListing(Listing):
	"""Yalnız _set_storefront_visible test edilir — Document iskeleti stub."""


def _make_listing(status: str, is_visible: int, store: str | None = "SELLER-A") -> _GuardListing:
	doc = _GuardListing()
	doc.status = status
	doc.is_visible = is_visible
	doc.seller_profile = store
	doc.storefront_visible = None
	return doc


class TestListingDriftGuard(unittest.TestCase):
	"""AC-9 + K2 — NON-operasyonel (suspended/canceled/expired) mağazanın
	listing save'i vitrini geri açamaz."""

	def setUp(self):
		_reset_state()

	def test_suspended_store_listing_save_stays_hidden(self):
		_STATE["sub_status"]["SELLER-A"] = "suspended"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 0, "Suspended mağazada save 1'e çevirmemeli")

	def test_canceled_store_listing_save_stays_hidden(self):
		# K2: hesap silme / dönem-sonu iptali sonrası save vitrini geri açamaz.
		_STATE["sub_status"]["SELLER-A"] = "canceled"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 0, "Canceled mağazada save 1'e çevirmemeli")

	def test_expired_store_listing_save_stays_hidden(self):
		# K2: trial bitişi / dunning feshi (expired) sonrası save vitrini geri açamaz.
		_STATE["sub_status"]["SELLER-A"] = "expired"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 0, "Expired mağazada save 1'e çevirmemeli")

	def test_suspended_guard_uses_single_get_value(self):
		_STATE["sub_status"]["SELLER-A"] = "suspended"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(len(_STATE["get_value_calls"]), 1, "Guard maliyeti tek get_value olmalı")
		self.assertEqual(_STATE["get_value_calls"][0][1], {"store": "SELLER-A"})

	def test_non_operational_guard_uses_single_get_value(self):
		# K2 genişletmesi tek get_value sözleşmesini BOZMAZ (canceled örneği).
		_STATE["sub_status"]["SELLER-A"] = "canceled"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(len(_STATE["get_value_calls"]), 1, "Guard maliyeti tek get_value olmalı")

	def test_active_subscription_keeps_normal_formula(self):
		_STATE["sub_status"]["SELLER-A"] = "active"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 1)

	def test_past_due_subscription_keeps_normal_formula(self):
		# Dunning hoşgörü penceresi: past_due OPERASYONEL — vitrini KAPATMAZ.
		_STATE["sub_status"]["SELLER-A"] = "past_due"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 1)

	def test_trial_subscription_keeps_normal_formula(self):
		# trial OPERASYONEL — vitrin formülü değişmez.
		_STATE["sub_status"]["SELLER-A"] = "trial"
		doc = _make_listing("Active", 1)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 1)

	def test_missing_subscription_keeps_normal_formula(self):
		doc = _make_listing("Active", 1)  # sub_status boş → get_value None döner
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 1)

	def test_invisible_formula_skips_subscription_lookup(self):
		# Formül zaten 0 → guard sorgusu hiç yapılmaz (performans sözleşmesi).
		_STATE["sub_status"]["SELLER-A"] = "suspended"
		for status, is_visible in (("Active", 0), ("Pending", 1), ("Draft", 0)):
			doc = _make_listing(status, is_visible)
			doc._set_storefront_visible()
			self.assertEqual(doc.storefront_visible, 0, (status, is_visible))
		self.assertEqual(_STATE["get_value_calls"], [], "Formül 0 iken get_value çağrılmamalı")

	def test_missing_seller_profile_skips_lookup(self):
		doc = _make_listing("Active", 1, store=None)
		doc._set_storefront_visible()
		self.assertEqual(doc.storefront_visible, 1, "Profilsiz kayıtta mevcut davranış değişmez")
		self.assertEqual(_STATE["get_value_calls"], [])


if __name__ == "__main__":
	unittest.main()
