"""MOGEM-662 kablo testi (620 dersi: fonksiyon yazılmış ama hiç çağrılmıyor olabilir) — hooks/kuyruk/zamanlayıcı
kayıtları var mı, kayıtlı yollar import edilebiliyor mu, sayfa temizliği geriye tarihli koşumda çalışıyor mu."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.seo_helper.core.queue import HANDLERS
from tradehub_core.seo_helper.crawler import manager
from tradehub_core.seo_helper.tests.ortak import ShcOrtam


class TestKablolar(FrappeTestCase):
	def test_hooklar_ve_zamanlayici_kayitli_ve_import_edilebilir(self):
		h = frappe.get_hooks()
		for dt in ("RFQ", "Seller Inquiry", "Order"):
			self.assertIn(
				"tradehub_core.seo_helper.experiments.attribution.on_conversion_insert",
				h["doc_events"][dt]["after_insert"],
			)
		self.assertIn(
			"tradehub_core.seo_helper.experiments.changelog.on_seo_policy_update",
			h["doc_events"]["SEO Policy"]["on_update"],
		)
		self.assertIn(
			"tradehub_core.seo_helper.experiments.changelog.on_redirect_change",
			h["doc_events"]["SEO Redirect Rule"]["after_insert"],
		)
		gunluk = h["scheduler_events"]["daily"]
		for fn in (
			"tradehub_core.seo_helper.crawler.botlog.import_scheduled",
			"tradehub_core.seo_helper.board.daily_job",
			"tradehub_core.seo_helper.connectors.search_console.scheduled_sync",
			"tradehub_core.seo_helper.crawler.manager.scheduled_incremental_crawl",
			"tradehub_core.seo_helper.crawler.manager.purge_old_pages",
		):
			self.assertIn(fn, gunluk)
			self.assertTrue(callable(frappe.get_attr(fn)), fn)
		self.assertIn(
			"tradehub_core.seo_helper.crawler.manager.recover_stale_runs", h["scheduler_events"]["hourly"]
		)
		for key in ("crawl.run", "gsc.sync"):
			self.assertIn(key, HANDLERS)
			self.assertTrue(callable(frappe.get_attr(HANDLERS[key])), key)
		# Scheduled Job Type kayıtları (migrate sonrası)
		for fn in (
			"tradehub_core.seo_helper.board.daily_job",
			"tradehub_core.seo_helper.crawler.botlog.import_scheduled",
		):
			self.assertTrue(
				frappe.db.exists("Scheduled Job Type", {"method": fn}), f"Scheduled Job Type yok: {fn}"
			)

	def test_whitelisted_uclar_kayitli(self):
		from tradehub_core.seo_helper.api import landing, panel662

		self.assertIn(landing.record_landing, frappe.whitelisted)
		self.assertTrue(
			frappe.guest_methods and landing.record_landing in frappe.guest_methods,
			"record_landing guest'e açık olmalı",
		)
		for ad in (
			"crawl_start",
			"botlog_import",
			"board_overview",
			"audit_report",
			"audit_export",
			"audit_import_signals",
			"gsc_status",
			"changelog_add",
			"experiment_create",
		):
			fn = getattr(panel662, ad)
			self.assertIn(fn, frappe.whitelisted, ad)
			self.assertNotIn(fn, frappe.guest_methods, f"{ad} misafire açık olmamalı")
		# dekoratör yanlış fonksiyona kayarsa (yardımcı whitelist'e girer, uç düşer) burada yakalanır — 25 Eyl'de oldu
		self.assertNotIn(
			panel662._report_filters, frappe.whitelisted, "yardımcı fonksiyon whitelist'te olmamalı"
		)

	def test_custom_fieldlar_donusum_doctypelarinda(self):
		for dt in ("RFQ", "Seller Inquiry", "Order"):
			meta = frappe.get_meta(dt)
			for f in ("seo_landing_path", "seo_is_organic", "seo_utm_source", "seo_landing_lang"):
				self.assertTrue(meta.has_field(f), f"{dt}.{f}")


class TestFrappeOptionalFieldTuzagi(FrappeTestCase):
	def test_alan_adlari_frappe_optional_fields_ile_cakismaz(self):
		"""Frappe DatabaseQuery.set_optional_columns alt dize eşleşmesi yapar: '_seen' geçen her alan
		(first_seen!) track_seen kapalı DocType'ta SELECT ve FILTER'dan sessizce düşer. Uygulama alanlarında
		bu alt dizeler bulunmamalı; get_all gerçekten değeri döndürmeli."""
		from frappe.model.db_query import optional_fields

		for dt in (
			"SEO Audit Finding",
			"SEO Bot Visit",
			"SEO Crawl Page",
			"SEO Crawl Run",
			"SEO Metric Snapshot",
		):
			for f in frappe.get_meta(dt).fields:
				for opt in optional_fields:
					self.assertNotIn(
						opt, f.fieldname, f"{dt}.{f.fieldname} Frappe optional_fields '{opt}' ile çakışır"
					)
		rows = frappe.get_all(
			"SEO Audit Finding", fields=["name", "first_observed", "last_observed"], limit=1
		)
		if rows:
			self.assertIn("first_observed", rows[0])


class TestSitemapOnbellek(FrappeTestCase):
	def test_all_urls_onbellekli_ve_dirty_dusurur(self):
		"""Tam sitemap üretimi ~25 s (10k URL); kapsam/aday çağrıları önbellekten okumalı, kirli bayrak düşürmeli."""
		from tradehub_core.seo_helper.adapters.tradehub import sitemap as sm

		frappe.cache().delete_value(sm.ALL_URLS_CACHE)
		with patch(
			"tradehub_core.seo.sitemap_generator.build_chunks_for_type",
			return_value=["<url><loc>http://x/a</loc></url>"],
		) as b:
			u1 = sm.all_urls()
			u2 = sm.all_urls()
			self.assertEqual(u1, u2)
			self.assertGreaterEqual(len(u1), 1)
			self.assertEqual(b.call_count, len(u1) and b.call_count, "ikinci çağrı üretici çağırmadı")
			ilk = b.call_count
			sm.all_urls()
			self.assertEqual(b.call_count, ilk, "önbellek isabeti (expires=True okuması)")
			sm.mark_dirty("Listing")
			sm.all_urls()
			self.assertGreater(b.call_count, ilk, "kirli bayrak önbelleği düşürdü")
		frappe.cache().delete_value(sm.ALL_URLS_CACHE)


class TestSayfaTemizligi(ShcOrtam, FrappeTestCase):
	def test_eski_kosumun_sayfalari_silinir_kosum_kalir(self):
		frappe.set_user("Administrator")
		with patch("frappe.enqueue"):
			run = manager.start_crawl("targeted", routes=[f"{frappe.utils.get_url()}/purge-{self._sonek()}"])
		self.addCleanup(lambda: frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{run}%"]}))
		self.addCleanup(lambda: self._drop("SEO Crawl Run", run))
		frappe.get_doc(
			{"doctype": "SEO Crawl Page", "crawl_run": run, "url": "x", "route": "/x", "status_code": 200}
		).insert(ignore_permissions=True)
		frappe.db.sql(
			"update `tabSEO Crawl Run` set creation = date_sub(now(), interval 90 day) where name=%s", run
		)
		frappe.db.commit()
		r = manager.purge_old_pages(days=60)
		self.assertGreaterEqual(r["runs"], 1)
		self.assertEqual(frappe.db.count("SEO Crawl Page", {"crawl_run": run}), 0)
		self.assertTrue(frappe.db.exists("SEO Crawl Run", run), "koşum özeti kalır")


class TestVarYokSizintisi(FrappeTestCase):
	"""25 Eyl 2026 rol matrisi bulgusu: satıcı `rotate_key(client="yok")` ile 404 alıyordu — var/yok bilgisi
	mağaza dışına sızıyordu. `get_doc_or_deny` yönetici olmayana her koşulda 403 verir."""

	EMAIL = "shc-wiring-satici@test.local"

	def setUp(self):
		frappe.set_user("Administrator")
		if not frappe.db.exists("User", self.EMAIL):
			frappe.get_doc(
				{
					"doctype": "User",
					"email": self.EMAIL,
					"first_name": "Wiring Satıcı",
					"send_welcome_email": 0,
					"enabled": 1,
					"roles": [{"role": "Marketplace Seller"}],
				}
			).insert(ignore_permissions=True)

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_var_olmayan_kayit_yoneticiye_404_digerine_403(self):
		from tradehub_core.seo_helper.core.permissions import get_doc_or_deny
		from tradehub_core.seo_helper.mcp import api as mcp_api
		from tradehub_core.seo_helper.mcp import ops

		frappe.set_user("Administrator")
		with self.assertRaises(frappe.DoesNotExistError):
			get_doc_or_deny("MCP Client", "shc-yok-x")
		frappe.set_user(self.EMAIL)
		with self.assertRaises(frappe.PermissionError):
			get_doc_or_deny("MCP Client", "shc-yok-x")
		with self.assertRaises(frappe.PermissionError):
			get_doc_or_deny("MCP Draft", None)
		# uçlar da aynı kapıdan geçer (get_doc'a geri dönülürse bu test kırılır)
		for fn, kw in ((ops.rotate_key, {"client": "shc-yok-x"}), (ops.disable_client, {"client": "shc-yok-x"}), (mcp_api.approve_draft, {"draft": "shc-yok-x"}), (mcp_api.reject_draft, {"draft": "shc-yok-x"})):
			with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
				fn(**kw)


class TestHedefiSilinmisIs(FrappeTestCase):
	"""Kuyruktaki iş hedef kaydı silindikten sonra koşarsa: tek seferde 'done · target_missing', 5 deneme yok."""

	def tearDown(self):
		# run_job kendi içinde commit eder → FrappeTestCase geri alamaz; satırı elle sil (canlı kuyruğa sızmasın)
		frappe.db.delete("SEO Sync Job", {"payload": ["like", '%shc-yok-run%']})
		frappe.db.commit()

	def test_silinmis_kosum_isi_tekrar_denenmez(self):
		from tradehub_core.seo_helper.core import queue

		job = frappe.get_doc(
			{"doctype": "SEO Sync Job", "job_type": "crawl.run", "queue": "seo_long", "status": "queued", "payload": '{"crawl_run": "shc-yok-run"}'}
		).insert(ignore_permissions=True)
		sonuc = queue.run_job(job.name)
		self.assertEqual(sonuc.get("skipped"), "target_missing")
		d = frappe.db.get_value("SEO Sync Job", job.name, ["status", "attempts", "next_attempt_at"], as_dict=True)
		self.assertEqual((d.status, d.attempts, d.next_attempt_at), ("done", 1, None))
