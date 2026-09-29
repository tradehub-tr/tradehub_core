"""MOGEM-662 (24 Eyl metni) — sinyal kaynağı etiketi, 404/medya/bot-log içe aktarımı, tekrar deneme izi,
dışa rapor, pano kapsam sınırı. Kabul kriterleri: koşum kapsamı/zamanı/hatası/tekrar denemesi panelden
izlenir; bulgu URL+koşuyla ilişkili, tekrar eden hata kaydı çoğaltmaz; pano/rapor yalnız ölçülen veri;
Search Console yoksa eksiklik açık."""

from __future__ import annotations

import csv
import io
import json
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.seo_helper import board
from tradehub_core.seo_helper.api import panel662
from tradehub_core.seo_helper.audit import reporter, rules, signals
from tradehub_core.seo_helper.crawler import manager
from tradehub_core.seo_helper.tests.ortak import ShcOrtam


class Ortak(ShcOrtam, FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self._site = frappe.utils.get_url().rstrip("/")


class TestSinyalKaynagi(Ortak):
	def test_404_gunlugu_ayri_etiketle_ve_tekrar_cogaltmaz(self):
		yol = f"/shc-404-{self._sonek()}"
		log = frappe.get_doc(
			{
				"doctype": "SEO 404 Log",
				"path": yol,
				"hit_count": 12,
				"resolved": 0,
				"first_seen_at": frappe.utils.now_datetime(),
				"last_hit_at": frappe.utils.now_datetime(),
				"last_referer": "https://www.google.com/",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("SEO 404 Log", log.name))
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": f"{self._site}{yol}"}))
		r1 = signals.import_404_log(days=1)
		self.assertGreaterEqual(r1["rows"], 1)
		f = frappe.db.get_value(
			"SEO Audit Finding",
			{"url": f"{self._site}{yol}", "code": "NOTFOUND_LOG_HIT"},
			["signal_source", "severity", "occurrences", "evidence", "status", "crawl_run"],
			as_dict=True,
		)
		self.assertEqual(
			(f.signal_source, f.severity, f.occurrences, f.status, f.crawl_run),
			("notfound_log", "error", 1, "open", None),
		)
		self.assertEqual(json.loads(f.evidence)["hits"], 12)
		self.assertIn("google", json.loads(f.evidence)["last_referer"])
		signals.import_404_log(days=1)  # aynı hata tekrar → kayıt çoğalmaz, occurrences artar
		self.assertEqual(
			frappe.db.count("SEO Audit Finding", {"url": f"{self._site}{yol}", "code": "NOTFOUND_LOG_HIT"}), 1
		)
		self.assertEqual(
			frappe.db.get_value("SEO Audit Finding", {"url": f"{self._site}{yol}"}, "occurrences"), 2
		)

	def test_bot_engeli_log_kaynakli(self):
		yol = f"/shc-blk-{self._sonek()}"
		v = frappe.get_doc(
			{
				"doctype": "SEO Bot Visit",
				"day": frappe.utils.nowdate(),
				"bot": "googlebot",
				"host": "t",
				"path": yol,
				"status_code": 403,
				"hits": 4,
				"blocked": 1,
				"dedupe_key": f"blk-{self._sonek()}",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("SEO Bot Visit", v.name))
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": f"{self._site}{yol}"}))
		signals.import_bot_blocks(days=1)
		f = frappe.db.get_value(
			"SEO Audit Finding",
			{"url": f"{self._site}{yol}", "code": "BOT_BLOCKED"},
			["signal_source", "severity"],
			as_dict=True,
		)
		self.assertEqual((f.signal_source, f.severity), ("log", "error"))

	def test_medya_denetimi_media_kaynakli(self):
		sahte = {
			"files": [
				{
					"file_url": f"/files/shc-{self._sonek()}.jpg",
					"findings": [
						{"code": "missing_alt", "severity": "error", "message": "Alt metni yok", "detail": ""}
					],
					"score": {"overall": 42},
				}
			],
			"summary": {},
			"score": {},
			"total": 1,
		}
		url = f"{self._site}/files/shc-{self._sonek()}.jpg"
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": url}))
		with patch("tradehub_core.media.seo_audit.audit_batch", return_value=sahte):
			r = signals.import_media_audit(limit=5, urls=[f"/files/shc-{self._sonek()}.jpg"])
		self.assertEqual(r["rows"], 1)
		f = frappe.db.get_value(
			"SEO Audit Finding", {"url": url}, ["code", "signal_source", "category", "severity"], as_dict=True
		)
		self.assertEqual(
			(f.code, f.signal_source, f.category, f.severity),
			("MEDIA_MISSING_ALT", "media", "content", "error"),
		)

	def test_politika_ve_tarayici_kaynaklari_ayri(self):
		p = self._seo_page("src")
		pol = frappe.get_all("SEO Audit Finding", filters={"page": p}, pluck="signal_source")
		self.assertTrue(all(s == "policy" for s in pol), pol)
		url = f"{self._site}/shc-crawl-{self._sonek()}"
		f = rules.finding(
			"HTTP_404",
			"technical",
			"error",
			"yok",
			url=url,
			evidence={"_key": "404"},
			root_cause="x",
			recommendation="y",
		)
		f["fingerprint"] = rules.fingerprint(f)
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": url}))
		reporter.upsert_findings([f], crawl_run=None)
		self.assertEqual(frappe.db.get_value("SEO Audit Finding", {"url": url}, "signal_source"), "crawler")
		rep = reporter.report(signal_source="crawler", days=1)
		self.assertTrue(all(r.signal_source == "crawler" for r in rep["rows"]))
		self.assertIn("crawler", rep["by_source"])
		self.assertEqual(
			reporter.report(signal_source="yok-boyle", days=1)["total"],
			reporter.report(days=1)["total"],
			"geçersiz kaynak süzgeci yok sayılır",
		)


class TestDisaRaporVeIz(Ortak):
	def _bulgu(self):
		url = f"{self._site}/shc-exp-{self._sonek()}"
		f = rules.finding(
			"HTTP_5XX",
			"technical",
			"error",
			"sunucu",
			url=url,
			evidence={"_key": "5xx", "status": 503},
			root_cause="x",
			recommendation="y",
		)
		f["fingerprint"] = rules.fingerprint(f)
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": url}))
		reporter.upsert_findings([f], crawl_run=None)
		return url, frappe.db.get_value("SEO Audit Finding", {"url": url}, "name")

	def test_csv_ve_json_disa_aktarim_url_zaman_kaynak_iz(self):
		url, ad = self._bulgu()
		dosya, icerik = reporter.export("csv", days=1)
		self.assertTrue(dosya.endswith(".csv") and icerik.startswith("﻿"))
		rows = list(csv.DictReader(io.StringIO(icerik.lstrip("﻿"))))
		satir = next(r for r in rows if r["url"] == url)
		for k in (
			"signal_source",
			"first_observed",
			"last_observed",
			"crawl_run",
			"recrawl_run",
			"recrawl_count",
			"evidence",
		):
			self.assertIn(k, satir)
		self.assertEqual((satir["signal_source"], satir["recrawl_count"]), ("crawler", "0"))
		self.assertEqual(json.loads(satir["evidence"])["status"], 503)
		dosya, icerik = reporter.export("json", days=1)
		self.assertTrue(dosya.endswith(".json"))
		self.assertTrue(any(r["url"] == url for r in json.loads(icerik)))

	def test_panel_export_indirme_yaniti(self):
		self._bulgu()
		panel662.audit_export(fmt="csv", days=1)
		self.assertEqual(frappe.local.response.type, "download")
		self.assertTrue(frappe.local.response.filename.endswith(".csv"))
		self.assertIn("signal_source", frappe.local.response.filecontent)

	def test_mark_fixed_yeniden_tarama_sayaci(self):
		url, ad = self._bulgu()
		with patch("frappe.enqueue"):
			r1 = reporter.mark_fixed(ad, by="t")
			self.addCleanup(lambda: frappe.db.delete("SEO Crawl Run", {"name": r1["recrawl_run"]}))
			self.assertEqual(frappe.db.get_value("SEO Audit Finding", ad, "recrawl_count"), 1)
			reporter.reopen_finding(ad)
			r2 = reporter.mark_fixed(ad, by="t")
			self.addCleanup(lambda: frappe.db.delete("SEO Crawl Run", {"name": r2["recrawl_run"]}))
		self.assertEqual(
			frappe.db.get_value("SEO Audit Finding", ad, ["recrawl_count", "recrawl_run"]),
			(2, r2["recrawl_run"]),
		)

	def test_crawl_runs_tekrar_deneme_izi(self):
		with patch("frappe.enqueue"):
			run = manager.start_crawl("targeted", routes=[f"{self._site}/shc-trace-{self._sonek()}"])
		self.addCleanup(lambda: frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{run}%"]}))
		self.addCleanup(lambda: self._drop("SEO Crawl Run", run))
		frappe.db.set_value(
			"SEO Sync Job",
			{"dedupe_key": f"crawl:{run}:0"},
			{"attempts": 2, "status": "failed", "last_error": "bağlantı koptu"},
		)
		frappe.db.set_value("SEO Crawl Run", run, "last_error", "işçi kesildi", update_modified=False)
		row = next(r for r in panel662.crawl_runs(limit=50) if r.name == run)
		self.assertEqual(
			(row["job_attempts"], row["job_status"], row["job_last_error"]), (2, "failed", "bağlantı koptu")
		)
		self.assertEqual((row["scope_routes"], row["last_error"]), (1, "işçi kesildi"))
		self.assertIn("candidates", row)


class TestPanoKapsamSiniri(Ortak):
	def test_butce_kesik_ve_eksik_kaynak_acikca_raporlanir(self):
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", max_pages=1)
		self.addCleanup(lambda: frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{run}%"]}))
		self.addCleanup(lambda: self._drop("SEO Crawl Run", run))
		frappe.db.set_value(
			"SEO Crawl Run",
			run,
			{"status": "done", "cursor": 1, "budget_exhausted": 1, "budget_reason": "max_pages"},
			update_modified=False,
		)
		sc = board.scope_limits()
		kodlar = {r["code"] for r in sc["reasons"]}
		self.assertTrue(sc["limited"])
		self.assertIn("budget_exhausted", kodlar)
		gsc = frappe.db.get_single_value("SEO Helper Settings", "gsc_property")
		if not gsc:
			self.assertTrue(
				any(r["code"] == "source_missing" and r["source"] == "search_console" for r in sc["reasons"]),
				"Search Console bağı yoksa eksiklik açık görünür",
			)
		self.assertEqual(sc["last_crawl"]["run"], run)
		self.assertEqual(sc["last_crawl"]["crawled"], 1)
		self.assertIn("scope", board.overview())

	def test_basarisiz_kosum_kapsam_nedeni(self):
		with patch("frappe.enqueue"):
			run = manager.start_crawl("incremental")
		self.addCleanup(lambda: frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{run}%"]}))
		self.addCleanup(lambda: self._drop("SEO Crawl Run", run))
		frappe.db.set_value(
			"SEO Crawl Run", run, {"status": "failed", "last_error": "Traceback: boom"}, update_modified=False
		)
		sc = board.scope_limits()
		n = next(r for r in sc["reasons"] if r["code"] == "last_run_failed")
		self.assertEqual(n["run"], run)
		self.assertIn("boom", n["error"])


class TestKapsamBloklamaz(Ortak):
	def test_sitemap_onbellekte_yoksa_kismi_ve_kuyruk(self):
		"""Panel çağrısı (wait=False) 25 s'lik sitemap üretimini beklemez: kısmi kapsam + arka plan ısıtma."""
		from tradehub_core.seo_helper.adapters.tradehub import sitemap as sm
		from tradehub_core.seo_helper.crawler import botlog

		frappe.cache().delete_value(sm.ALL_URLS_CACHE)
		frappe.cache().delete_value(f"{sm.ALL_URLS_CACHE}:warming")
		with patch("frappe.enqueue") as enq:
			k = botlog.coverage(days=1, wait=False)
			self.assertTrue(k["partial"])
			self.assertEqual(k["partial_reason"], "sitemap_pending")
			self.assertEqual(enq.call_count, 1)
			botlog.coverage(days=1, wait=False)
			self.assertEqual(enq.call_count, 1, "ısıtma kilidi: ikinci çağrı yeniden kuyruklamaz")
		frappe.cache().set_value(sm.ALL_URLS_CACHE, [f"{self._site}/urun/x"], expires_in_sec=60)
		with patch("frappe.enqueue") as enq:
			k = botlog.coverage(days=1, wait=False)
			self.assertFalse(k["partial"])
			self.assertEqual(enq.call_count, 0)
		frappe.cache().delete_value(sm.ALL_URLS_CACHE)
		frappe.cache().delete_value(f"{sm.ALL_URLS_CACHE}:warming")


class TestGuvenlikSinirlari(Ortak):
	def test_crawl_start_sinirlari_ve_route_tavani(self):
		with patch("frappe.enqueue"):
			r = panel662.crawl_start(
				mode="targeted",
				routes=[f"{self._site}/shc-lim-{self._sonek()}"],
				rate_limit_rps=10**6,
				max_pages=10**9,
				max_seconds=10**9,
				max_mb=10**9,
				sample_size=-3,
			)
		self.addCleanup(
			lambda: frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{r['name']}%"]})
		)
		self.addCleanup(lambda: self._drop("SEO Crawl Run", r["name"]))
		d = frappe.db.get_value(
			"SEO Crawl Run",
			r["name"],
			["rate_limit_rps", "max_pages", "max_seconds", "max_bytes"],
			as_dict=True,
		)
		self.assertEqual(
			(d.rate_limit_rps, d.max_pages, d.max_seconds, d.max_bytes),
			(50.0, 100000, 86400, 2000 * 1024 * 1024),
		)
		with self.assertRaises(frappe.ValidationError):
			panel662.crawl_start(mode="targeted", routes=[f"{self._site}/x{i}" for i in range(5001)])
		with patch("frappe.enqueue"):
			r2 = panel662.crawl_start(
				mode="targeted", routes=[f"{self._site}/shc-lim2-{self._sonek()}"], rate_limit_rps=-1
			)
		self.addCleanup(
			lambda: frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{r2['name']}%"]})
		)
		self.addCleanup(lambda: self._drop("SEO Crawl Run", r2["name"]))
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", r2["name"], "rate_limit_rps"), 0.1)

	def test_oauth_state_dogrulanir(self):
		"""Sahte/eksik state ile callback kod takası YAPMAZ (hesap bağlama CSRF'i); doğru state tek kullanımlık."""
		frappe.db.set_single_value("SEO Helper Settings", "gsc_client_id", "test-client")
		frappe.clear_cache(doctype="SEO Helper Settings")
		self.addCleanup(lambda: frappe.db.set_single_value("SEO Helper Settings", "gsc_client_id", ""))
		with patch.object(panel662, "gsc_exchange_code") as takas:
			panel662.gsc_oauth_callback(code="k", state="sahte")
			self.assertEqual(takas.call_count, 0)
			self.assertIn("gsc=error", frappe.local.response["location"])
			state = panel662.gsc_auth_url()["url"].split("state=")[1].split("&")[0]
			panel662.gsc_oauth_callback(code="k", state=state)
			self.assertEqual(takas.call_count, 1)
			self.assertIn("gsc=connected", frappe.local.response["location"])
			panel662.gsc_oauth_callback(code="k", state=state)  # tekrar kullanım → reddedilir
			self.assertEqual(takas.call_count, 1)
