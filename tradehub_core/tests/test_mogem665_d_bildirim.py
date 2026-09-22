"""MOGEM-665 · 5. Aşama — İstoc'tan dış sisteme stok bildirimi.

Kabul kriterleri (görev metni):
- Sipariş/iptal/iade kaynaklı stok değişimi dış sisteme iletilir (webhook, imzalı)
  ve yoklama ile de alınabilir (`changes`).
- İletilemeyen bildirim yeniden denenir; sürekli başarısız olan "ölü" olarak
  panelde görünür ve elle yeniden kuyruğa alınır.
- Dış sistemin API ile yaptığı güncelleme ona geri yankılanmaz (döngü yok).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_to_date, get_datetime, now_datetime

from tradehub_core.tests.mogem665_ortak import Mogem665Ortam

DT = "Catalog Outbound Event"


class _BildirimOrtam(Mogem665Ortam):
	def _webhook(self, b: dict, url: str = "https://erp.example.com/istoc/stok", secret: str = "cok-gizli"):
		doc = frappe.get_doc("API Application", b["app"])
		doc.webhook_url = url
		doc.webhook_secret = secret
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		return secret

	def _olay(self, listing: str, reason: str = "reserve") -> int:
		from tradehub_core.integration import outbound

		with patch("frappe.enqueue"):
			name = outbound.emit_stock_change(listing, reason)
		self.assertIsNotNone(name)
		self.addCleanup(lambda: self._drop(DT, name))
		return name

	def _temizle_olaylar(self, seller: str):
		for n in frappe.get_all(DT, filters={"seller_profile": seller}, pluck="name"):
			self._drop(DT, n)


class TestOlayUretimi(_BildirimOrtam, FrappeTestCase):
	def test_siparis_kaynakli_stok_hareketi_olay_uretir(self):
		from tradehub_core.utils import stock as stock_utils

		b = self._api_baglantisi("emit")
		name = self._listing(b["seller"], "EV-1", stock_qty=10)
		frappe.db.set_value("Listing", name, "reserved_qty", 4)
		with patch("frappe.enqueue") as enq:
			stock_utils._recalculate_available(name, reason="reserve")
		# Listing adı seri geri sarma (revert_series_if_last) ile yeniden kullanılabilir;
		# başka koşulardan kalan olaylar aynı ada denk düşmesin diye mağazaya göre süz.
		olaylar = frappe.get_all(
			DT,
			filters={"listing": name, "seller_profile": b["seller"]},
			fields=["name", "status", "reason", "stock_qty", "available_qty", "sku", "payload"],
		)
		self.assertEqual(len(olaylar), 1)
		ev = olaylar[0]
		self.addCleanup(lambda: self._drop(DT, ev.name))
		self.assertEqual(
			(ev.reason, float(ev.stock_qty), float(ev.available_qty), ev.sku), ("reserve", 10.0, 6.0, "EV-1")
		)
		self.assertEqual(ev.status, "skipped", "webhook yokken yalnız yoklama için saklanır")
		self.assertEqual(enq.call_count, 0)
		self.assertEqual(json.loads(ev.payload)["available_qty"], 6.0)

	def test_webhook_varsa_kuyruga_girer(self):
		b = self._api_baglantisi("emitwh")
		self._webhook(b)
		name = self._listing(b["seller"], "EV-2")
		from tradehub_core.integration import outbound

		with patch("frappe.enqueue") as enq:
			ev = outbound.emit_stock_change(name, "deduct")
		self.addCleanup(lambda: self._drop(DT, ev))
		self.assertEqual(frappe.db.get_value(DT, ev, "status"), "queued")
		self.assertEqual(enq.call_count, 1)
		self.assertEqual(enq.call_args.kwargs.get("event"), ev)
		self.assertTrue(enq.call_args.kwargs.get("enqueue_after_commit"))

	def test_api_stok_guncellemesi_olay_uretmez_yanki_yok(self):
		from tradehub_core.api.v1.catalog import update_stock
		from tradehub_core.utils import stock as stock_utils

		b = self._api_baglantisi("echo")
		self._webhook(b)
		name = self._listing(b["seller"], "EV-3", stock_qty=10)
		with self.bearer(b["token"]):
			update_stock([{"sku": "EV-3", "stock": 3}])
		stock_utils._recalculate_available(name)  # sebepsiz iç çağrı da olay üretmez
		self.assertEqual(frappe.db.count(DT, {"listing": name, "seller_profile": b["seller"]}), 0)

	def test_urun_silinince_olaylari_da_silinir(self):
		"""Seri geri sarma: silinen ürünün adı yeni ürüne verilebilir; olaylar yapışmamalı."""
		b = self._api_baglantisi("trash")
		name = self._listing(b["seller"], "TR-1")
		from tradehub_core.integration import outbound

		with patch("frappe.enqueue"):
			ev = outbound.emit_stock_change(name, "reserve")
		self.assertTrue(frappe.db.exists(DT, ev))
		frappe.delete_doc("Listing", name, force=True, ignore_permissions=True)
		frappe.db.commit()
		self.assertFalse(frappe.db.exists(DT, ev), "on_trash kaskadı çalışmadı")

	def test_olay_uretimi_hatasi_siparis_akisini_dusurmez(self):
		from tradehub_core.integration import outbound

		with patch.object(outbound.frappe, "get_doc", side_effect=RuntimeError("db patladı")):
			self.assertIsNone(outbound.emit_stock_change("LST-YOK", "reserve"))


class TestIletim(_BildirimOrtam, FrappeTestCase):
	def _teslim(self, ev: int, status_code: int = 200, text: str = "", exc: Exception | None = None):
		from tradehub_core.integration import outbound

		with patch.object(outbound, "validate_feed_url"), patch.object(outbound.requests, "post") as post:
			if exc:
				post.side_effect = exc
			else:
				post.return_value = SimpleNamespace(status_code=status_code, text=text)
			sonuc = outbound.deliver(ev)
		return sonuc, post

	def test_basarili_iletim_imzali(self):
		b = self._api_baglantisi("ok")
		secret = self._webhook(b)
		name = self._listing(b["seller"], "IL-1")
		ev = self._olay(name)
		sonuc, post = self._teslim(ev, 200)
		self.assertEqual(sonuc["status"], "sent")
		kw = post.call_args.kwargs
		self.assertEqual(post.call_args.args[0], "https://erp.example.com/istoc/stok")
		self.assertEqual(kw["timeout"], 10)
		body = kw["data"]
		beklenen = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
		self.assertEqual(kw["headers"]["X-Istoc-Signature"], beklenen)
		self.assertEqual(kw["headers"]["X-Istoc-Event"], "stock.changed")
		self.assertEqual(kw["headers"]["X-Istoc-Delivery"], str(ev))
		govde = json.loads(body)
		self.assertEqual((govde["sku"], govde["reason"], govde["id"]), ("IL-1", "reserve", ev))
		row = frappe.db.get_value(
			DT, ev, ["status", "attempts", "last_http_status", "delivered_at"], as_dict=True
		)
		self.assertEqual((row.status, row.attempts, row.last_http_status), ("sent", 1, 200))
		self.assertTrue(row.delivered_at)
		self.assertEqual(frappe.db.get_value("API Application", b["app"], "webhook_failures"), 0)

	def test_basarisiz_iletim_geri_cekilme_ve_olu(self):
		from tradehub_core.integration import outbound

		b = self._api_baglantisi("fail")
		self._webhook(b)
		name = self._listing(b["seller"], "IL-2")
		ev = self._olay(name)
		basla = now_datetime()
		sonuc, _ = self._teslim(ev, 500, "kapalı")
		self.assertEqual(sonuc["status"], "failed")
		row = frappe.db.get_value(
			DT, ev, ["status", "attempts", "next_attempt_at", "last_error", "last_http_status"], as_dict=True
		)
		self.assertEqual(
			(row.status, row.attempts, row.last_http_status, row.last_error), ("failed", 1, 500, "kapalı")
		)
		fark = (get_datetime(row.next_attempt_at) - basla).total_seconds()
		self.assertTrue(55 <= fark <= 90, f"1. geri çekilme ~1 dk olmalı: {fark}")
		self.assertEqual(frappe.db.get_value("API Application", b["app"], "webhook_failures"), 1)
		for _i in range(2, outbound.MAX_ATTEMPTS + 1):
			frappe.db.set_value(DT, ev, "next_attempt_at", add_to_date(now_datetime(), minutes=-1))
			sonuc, _ = self._teslim(ev, 503)
		row = frappe.db.get_value(DT, ev, ["status", "attempts", "next_attempt_at"], as_dict=True)
		self.assertEqual((row.status, row.attempts), ("dead", outbound.MAX_ATTEMPTS))
		self.assertIsNone(row.next_attempt_at)
		self.assertEqual(
			frappe.db.get_value("API Application", b["app"], "webhook_failures"), outbound.MAX_ATTEMPTS
		)
		sonuc, post = self._teslim(ev, 200)
		self.assertTrue(sonuc.get("skipped"), "ölü olay kendiliğinden tekrar denenmez")
		self.assertEqual(post.call_count, 0)

	def test_ag_hatasi_failed(self):
		import requests

		b = self._api_baglantisi("net")
		self._webhook(b)
		ev = self._olay(self._listing(b["seller"], "IL-3"))
		sonuc, _ = self._teslim(ev, exc=requests.ConnectionError("bağlanamadı"))
		self.assertEqual(sonuc["status"], "failed")
		self.assertIn("bağlanamadı", frappe.db.get_value(DT, ev, "last_error"))

	def test_ssrf_adres_iletim_aninda_reddedilir(self):
		from tradehub_core.integration import outbound

		b = self._api_baglantisi("ssrf")
		frappe.db.set_value("API Application", b["app"], "webhook_url", "http://127.0.0.1:9/ic")
		ev = self._olay(self._listing(b["seller"], "IL-4"))
		with patch.object(outbound.requests, "post") as post:
			sonuc = outbound.deliver(ev)
		self.assertEqual(sonuc["status"], "failed")
		self.assertEqual(post.call_count, 0, "iç ağ adresine istek ATILMAZ")

	def test_webhook_kaldirilmissa_skipped(self):
		b = self._api_baglantisi("nowh")
		self._webhook(b)
		ev = self._olay(self._listing(b["seller"], "IL-5"))
		frappe.db.set_value("API Application", b["app"], "webhook_url", "")
		from tradehub_core.integration import outbound

		self.assertEqual(outbound.deliver(ev)["status"], "skipped")

	def test_supurucu_suresi_gelenleri_ve_eskimis_kuyrugu_iletir(self):
		from tradehub_core.integration import outbound

		b = self._api_baglantisi("sweep")
		self._webhook(b)
		l1 = self._listing(b["seller"], "SW-1")
		e_due = self._olay(l1)
		e_later = self._olay(l1)
		e_stale = self._olay(l1)
		frappe.db.set_value(
			DT,
			e_due,
			{"status": "failed", "attempts": 1, "next_attempt_at": add_to_date(now_datetime(), minutes=-1)},
		)
		frappe.db.set_value(
			DT,
			e_later,
			{"status": "failed", "attempts": 1, "next_attempt_at": add_to_date(now_datetime(), minutes=+30)},
		)
		frappe.db.set_value(
			DT, e_stale, "modified", add_to_date(now_datetime(), minutes=-10), update_modified=False
		)  # set_value varsayılanı modified'ı şimdiye çeker
		frappe.db.commit()
		with (
			patch.object(outbound, "validate_feed_url"),
			patch.object(outbound.requests, "post") as post,
			patch.object(outbound.frappe.db, "commit"),
		):
			post.return_value = SimpleNamespace(status_code=204, text="")
			rapor = outbound.sweep_due()
		self.assertEqual((rapor["sent"], rapor["failed"]), (2, 0), rapor)
		self.assertEqual(frappe.db.get_value(DT, e_due, "status"), "sent")
		self.assertEqual(frappe.db.get_value(DT, e_stale, "status"), "sent")
		self.assertEqual(frappe.db.get_value(DT, e_later, "status"), "failed", "süresi gelmeyen dokunulmaz")


class TestPanelVeYeniden(_BildirimOrtam, FrappeTestCase):
	def test_panel_listesi_sayaclar_ve_izolasyon(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		a = self._api_baglantisi("pa")
		b = self._api_baglantisi("pb")
		la = self._listing(a["seller"], "PA-1")
		e1 = self._olay(la)
		e2 = self._olay(la, "release")
		frappe.db.set_value(DT, e2, "status", "dead")
		self._olay(self._listing(b["seller"], "PB-1"))
		with kullanici(a["user"]):
			out = ci.list_outbound_events()
			self.assertEqual(out["total"], 2)
			self.assertEqual({e["name"] for e in out["events"]}, {e1, e2})
			self.assertEqual(out["counts"]["dead"], 1)
			olu = ci.list_outbound_events(status="dead")
			self.assertEqual([e["name"] for e in olu["events"]], [e2])
		with kullanici(b["user"]):
			self.assertEqual(ci.list_outbound_events()["total"], 1)

	def test_yeniden_kuyruga_alma_yalniz_kendi_magazasi_ve_olu_failed(self):
		from tradehub_core.api import catalog_integration as ci
		from tradehub_core.tests.mogem620_ortak import kullanici

		a = self._api_baglantisi("ra")
		b = self._api_baglantisi("rb")
		e_dead = self._olay(self._listing(a["seller"], "RA-1"))
		e_sent = self._olay(self._listing(a["seller"], "RA-2"))
		frappe.db.set_value(DT, e_dead, {"status": "dead", "attempts": 5, "last_error": "x"})
		frappe.db.set_value(DT, e_sent, "status", "sent")
		with kullanici(b["user"]), self.assertRaises(frappe.PermissionError):
			ci.retry_outbound_event(e_dead)
		with kullanici(a["user"]):
			with self.assertRaises(frappe.ValidationError):
				ci.retry_outbound_event(e_sent)
			with patch("frappe.enqueue") as enq:
				ci.retry_outbound_event(e_dead)
			self.assertEqual(enq.call_count, 1)
		row = frappe.db.get_value(DT, e_dead, ["status", "attempts", "last_error"], as_dict=True)
		self.assertEqual((row.status, row.attempts, row.last_error), ("queued", 0, ""))

	def test_satici_get_list_ile_yalniz_kendi_olaylarini_gorur(self):
		from tradehub_core.tests.mogem620_ortak import kullanici

		a = self._api_baglantisi("qa")
		b = self._api_baglantisi("qb")
		ea = self._olay(self._listing(a["seller"], "QA-1"))
		self._olay(self._listing(b["seller"], "QB-1"))
		with kullanici(a["user"]):
			adlar = frappe.get_list(DT, pluck="name", ignore_permissions=False)
		self.assertEqual(set(adlar), {ea})


class TestYoklama(_BildirimOrtam, FrappeTestCase):
	def test_changes_imlecle_sayfalar_ve_izole(self):
		from tradehub_core.api.v1.catalog import changes

		a = self._api_baglantisi("poll")
		b = self._api_baglantisi("pollb")
		la = self._listing(a["seller"], "PL-1")
		e1, e2, e3 = self._olay(la, "reserve"), self._olay(la, "deduct"), self._olay(la, "refund")
		self._olay(self._listing(b["seller"], "PL-B"))
		with self.bearer(a["token"]):
			s1 = changes(since=0, limit=2)
			self.assertEqual([e["id"] for e in s1["events"]], [e1, e2])
			self.assertTrue(s1["has_more"])
			self.assertEqual(s1["next_since"], e2)
			s2 = changes(since=s1["next_since"], limit=2)
			self.assertEqual([e["id"] for e in s2["events"]], [e3])
			self.assertFalse(s2["has_more"])
			self.assertEqual(s2["events"][0]["reason"], "refund")
			self.assertEqual(s2["events"][0]["sku"], "PL-1")
			s3 = changes(since=s2["next_since"])
			self.assertEqual((s3["events"], s3["next_since"]), ([], e3))

	def test_changes_yetki_alani_gerekli(self):
		from tradehub_core.api.v1.catalog import changes

		b = self._api_baglantisi("pollscope", scopes=("stock:write",))
		with self.bearer(b["token"]), self.assertRaises(frappe.PermissionError):
			changes(since=0)
