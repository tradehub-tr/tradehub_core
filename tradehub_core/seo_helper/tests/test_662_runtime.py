"""MOGEM-662 Frappe entegrasyon testleri — tarama yöneticisi (checkpoint/duraklat/devam/bütçe/mod),
bot logu içe aktarma + kapsam, denetim tekilleştirme + yaşam döngüsü, pano, GSC kota/senkron (mock),
atıf kancası + toplulaştırma, değişiklik kaydı, deney, panel rol kapısı."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, nowdate

from tradehub_core.seo_helper.audit import reporter
from tradehub_core.seo_helper.crawler import fetcher, manager
from tradehub_core.seo_helper.tests.ortak import ACIKLAMA, ShcOrtam

HTML_OK = (
	'<html lang="tr"><head><title>%s</title><meta name="description" content="%s"><meta name="robots" content="index,follow">'
	'<link rel="canonical" href="%s"></head><body><h1>B</h1><p>%s</p><a href="/x">x</a></body></html>'
)


class _R:
	def __init__(self, status=200, text="", url=""):
		self.status_code, self.text, self.url, self.history = status, text, url, []
		self.headers = {"Content-Type": "text/html"}
		self.content = text.encode()


class _Session:
	"""Sahte HTTP: url → (status, html) ya da exception."""

	def __init__(self, pages: dict):
		self.pages, self.calls = pages, []

	def get(self, url, **kw):
		self.calls.append(url)
		if url.endswith("/robots.txt"):
			return _R(200, "User-agent: *\nDisallow: /gizli\n", url)
		v = self.pages.get(url)
		if isinstance(v, Exception):
			raise v
		if v is None:
			return _R(404, "<html><body>yok</body></html>", url)
		return _R(v[0], v[1], url)


KISA_BASLIK = "Toptan kampanya sayfası"


def _ok_html(url, title=KISA_BASLIK, desc=ACIKLAMA, words=200):
	return HTML_OK % (title, desc, url, " kelime" * words)


class Ortak662(ShcOrtam, FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self._site = frappe.utils.get_url().rstrip("/")

	def _run_cleanup(self, run):
		def _temizle():
			frappe.db.delete("SEO Crawl Page", {"crawl_run": run})
			frappe.db.delete("SEO Audit Finding", {"crawl_run": run})
			frappe.db.delete("SEO Sync Job", {"dedupe_key": ["like", f"crawl:{run}%"]})
			self._drop("SEO Crawl Run", run)

		self.addCleanup(_temizle)

	def _fetcher(self, pages: dict, **kw):
		s = _Session(pages)
		return fetcher.Fetcher(s, robots=fetcher.RobotsCache(s, "ua"), **kw), s


class TestCrawlManager(Ortak662):
	def test_tam_tarama_checkpoint_ve_sonuc(self):
		p1 = self._seo_page("c1")
		p2 = self._seo_page("c2", title="")
		from tradehub_core.seo_helper.core.policy import apply_for_page

		apply_for_page(p1)
		apply_for_page(p2)
		u1, u2 = (frappe.db.get_value("SEO Page", p, "effective_canonical") for p in (p1, p2))
		with patch("frappe.enqueue"):
			run = manager.start_crawl(
				"full", routes=[u1, u2, f"{self._site}/gizli/x", f"{self._site}/yok"], max_pages=0
			)
		self._run_cleanup(run)
		f, s = self._fetcher({u1: (200, _ok_html(u1)), u2: (200, _ok_html(u2, title="", words=5))})
		with patch.object(
			frappe.get_cached_doc("SEO Helper Settings"), "crawl_checkpoint_every", 1, create=True
		):
			out = manager.run_crawl_job(run, fetcher_obj=f)
		self.assertEqual(out["status"], "done")
		self.assertEqual((out["pages"], out["ok"], out["failed"]), (4, 2, 2))
		d = frappe.get_doc("SEO Crawl Run", run)
		self.assertEqual(
			(d.status, d.cursor, d.pages_ok, d.pages_failed, d.budget_exhausted), ("done", 4, 2, 2, 0)
		)
		sayfalar = {
			r.url: r
			for r in frappe.get_all(
				"SEO Crawl Page",
				filters={"crawl_run": run},
				fields=["url", "status_code", "robots_blocked", "title", "canonical", "word_count"],
			)
		}
		self.assertEqual(sayfalar[u1].title, KISA_BASLIK)
		self.assertEqual(sayfalar[u1].canonical, u1)
		self.assertEqual(sayfalar[f"{self._site}/gizli/x"].robots_blocked, 1)
		self.assertEqual(sayfalar[f"{self._site}/yok"].status_code, 404)
		self.assertEqual(sum(1 for c in s.calls if c.endswith("robots.txt")), 1)
		# 13.4 bulgular: temiz sayfa bulgusuz, boş başlık + ince içerik bulgulu, 404 teknik
		kodlar = {
			(b.url, b.code)
			for b in frappe.get_all("SEO Audit Finding", filters={"crawl_run": run}, fields=["url", "code"])
		}
		self.assertIn((u2, "TITLE_MISSING"), kodlar)
		self.assertIn((u2, "THIN_CONTENT"), kodlar)
		self.assertIn((f"{self._site}/yok", "HTTP_404"), kodlar)
		self.assertIn((f"{self._site}/gizli/x", "ROBOTS_BLOCKED"), kodlar)
		self.assertFalse({k for k in kodlar if k[0] == u1}, "temiz sayfa bulgusuz")
		self.assertEqual(d.findings, len(kodlar))

	def test_duraklat_devam_et_kaldigi_yerden(self):
		urls = [f"{self._site}/p{i}" for i in range(6)]
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=urls)
		self._run_cleanup(run)
		pages = {u: (200, _ok_html(u)) for u in urls}
		f, s = self._fetcher(pages)
		# 2 sayfada bir checkpoint; 2. checkpoint'te duraklatma isteği görülsün
		orijinal = manager._write_page

		def yaz_ve_duraklat(run_name, url, r, parsed, needs):
			orijinal(run_name, url, r, parsed, needs)
			if url.endswith("/p2"):
				frappe.db.set_value("SEO Crawl Run", run_name, "pause_requested", 1, update_modified=False)

		with (
			patch.object(
				frappe.get_cached_doc("SEO Helper Settings"), "crawl_checkpoint_every", 2, create=True
			),
			patch.object(manager, "_write_page", yaz_ve_duraklat),
		):
			out = manager.run_crawl_job(run, fetcher_obj=f)
		self.assertEqual(out["status"], "paused")
		self.assertEqual(
			out["cursor"], 3, "duraklatma isteği bir sonraki sayfada görülür (her sayfada okunur)"
		)
		self.assertEqual(len(s.calls) - 1, 3, "duraklattıktan sonra istek atılmadı")
		with patch("frappe.enqueue") as enq:
			r = manager.resume(run)
		self.assertEqual(r["cursor"], 3)
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", run, "status"), "queued")
		self.assertTrue(enq.called)
		f2, s2 = self._fetcher(pages)
		out2 = manager.run_crawl_job(run, fetcher_obj=f2)
		self.assertEqual(out2["status"], "done")
		self.assertEqual(len(s2.calls) - 1, 3, "yalnız kalan 3 sayfa alındı")
		self.assertEqual(frappe.db.count("SEO Crawl Page", {"crawl_run": run}), 6)
		with self.assertRaises(frappe.ValidationError):
			manager.resume(run)

	def test_butce_ve_hiz_siniri(self):
		urls = [f"{self._site}/b{i}" for i in range(5)]
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=urls, max_pages=3, rate_limit_rps=4)
		self._run_cleanup(run)
		f, s = self._fetcher({u: (200, _ok_html(u)) for u in urls})
		bekle = []
		f.rate_limiter = SimpleNamespace(wait=lambda host: bekle.append(host) or 0.0)
		out = manager.run_crawl_job(run, fetcher_obj=f)
		self.assertEqual((out["status"], out["pages"], out["budget"]), ("done", 3, "max_pages"))
		d = frappe.db.get_value(
			"SEO Crawl Run", run, ["budget_exhausted", "budget_reason", "rate_limit_rps"], as_dict=True
		)
		self.assertEqual((d.budget_exhausted, d.budget_reason, d.rate_limit_rps), (1, "max_pages", 4.0))
		self.assertEqual(len(bekle), 3, "her istek hız sınırından geçti")

	def test_modlar_artimli_ve_orneklem(self):
		urls = [f"{self._site}/m{i}" for i in range(10)]
		with patch("frappe.enqueue"):
			r_sample = manager.start_crawl("sample", routes=None, sample_size=3, seed="t")
			self._run_cleanup(r_sample)
		# routes=None → SEO Page adayları; örneklem en fazla 3
		self.assertLessEqual(frappe.db.get_value("SEO Crawl Run", r_sample, "pages_total"), 3)
		with patch("frappe.enqueue"), patch.object(manager, "candidate_urls", return_value=urls):
			r_inc = manager.start_crawl("incremental")
			self._run_cleanup(r_inc)
		self.assertEqual(
			frappe.db.get_value("SEO Crawl Run", r_inc, "pages_total"), 10, "hiç taranmamış → hepsi"
		)
		# şimdi ikisini 'taranmış' yap → artımlı ikinci koşum onları atlar
		for u in urls[:2]:
			frappe.get_doc(
				{
					"doctype": "SEO Crawl Page",
					"crawl_run": r_inc,
					"url": u,
					"route": u.replace(self._site, ""),
					"status_code": 200,
					"fetched_at": frappe.utils.now_datetime(),
				}
			).insert(ignore_permissions=True)
		with patch("frappe.enqueue"), patch.object(manager, "candidate_urls", return_value=urls):
			r_inc2 = manager.start_crawl("incremental")
			self._run_cleanup(r_inc2)
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", r_inc2, "pages_total"), 8)
		with self.assertRaises(frappe.ValidationError):
			manager.start_crawl("targeted")
		with self.assertRaises(frappe.ValidationError):
			manager.start_crawl("bozuk")

	def test_iptal_ve_hata_yolu(self):
		urls = [f"{self._site}/e{i}" for i in range(3)]
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=urls)
		self._run_cleanup(run)
		manager.cancel(run)
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", run, "status"), "cancelled")
		self.assertTrue(manager.run_crawl_job(run)["skipped"])
		with patch("frappe.enqueue"):
			run2 = manager.start_crawl("full", routes=urls)
		self._run_cleanup(run2)
		f, _ = self._fetcher({urls[0]: (200, _ok_html(urls[0]))})
		with (
			patch.object(manager, "_write_page", side_effect=RuntimeError("disk dolu")),
			self.assertRaises(RuntimeError),
		):
			manager.run_crawl_job(run2, fetcher_obj=f)
		d = frappe.db.get_value("SEO Crawl Run", run2, ["status", "last_error"], as_dict=True)
		self.assertEqual(d.status, "failed")
		self.assertIn("disk dolu", d.last_error)

	def test_ssrf_hedefli_tarama_yalniz_site_hostu(self):
		with patch("frappe.enqueue"), self.assertRaises(frappe.PermissionError):
			manager.start_crawl("targeted", routes=["http://169.254.169.254/latest/meta-data/"])
		with patch("frappe.enqueue"), self.assertRaises(frappe.ValidationError):
			manager.start_crawl("targeted", routes=["ftp://x/y"])
		self.assertIn(frappe.utils.get_url().split("://", 1)[1].rstrip("/").lower(), manager.allowed_hosts())

	def test_son_sayfada_duraklatma_istegi_kosumu_bitirir(self):
		urls = [f"{self._site}/son{i}" for i in range(2)]
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=urls)
		self._run_cleanup(run)
		f, _ = self._fetcher({u: (200, _ok_html(u)) for u in urls})
		orijinal = manager._write_page

		def yaz(run_name, url, r, parsed, needs):
			orijinal(run_name, url, r, parsed, needs)
			if url.endswith("/son1"):
				frappe.db.set_value("SEO Crawl Run", run_name, "pause_requested", 1, update_modified=False)

		with (
			patch.object(
				frappe.get_cached_doc("SEO Helper Settings"), "crawl_checkpoint_every", 1, create=True
			),
			patch.object(manager, "_write_page", yaz),
		):
			out = manager.run_crawl_job(run, fetcher_obj=f)
		self.assertEqual(
			out["status"], "done", "tüm URL'ler alındıysa duraklatma isteği koşumu askıda bırakmaz"
		)

	def test_kuyruktayken_duraklatilan_kosum_isci_tarafindan_calistirilmaz(self):
		urls = [f"{self._site}/q{i}" for i in range(3)]
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=urls)
		self._run_cleanup(run)
		manager.pause(run)
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", run, "status"), "paused")
		f, s = self._fetcher({u: (200, _ok_html(u)) for u in urls})
		out = manager.run_crawl_job(run, fetcher_obj=f)  # işçi kuyruktaki eski işi alsa bile
		self.assertTrue(out["skipped"])
		self.assertEqual(s.calls, [], "hiç istek atılmadı")
		with patch("frappe.enqueue"):
			manager.resume(run)
		out2 = manager.run_crawl_job(run, fetcher_obj=f)
		self.assertEqual((out2["status"], out2["pages"]), ("done", 3))

	def test_robots_txt_ham_sablon_site_bulgusu(self):
		u = f"{self._site}/rb"
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=[u])
		self._run_cleanup(run)
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"code": "ROBOTS_TXT_UNPARSEABLE"}))
		s = _Session({u: (200, _ok_html(u))})
		s.get = (
			lambda orig: lambda url, **kw: _R(200, "{{ robots_txt }}", url)
			if url.endswith("/robots.txt")
			else orig(url, **kw)
		)(s.get)
		f = fetcher.Fetcher(s, robots=fetcher.RobotsCache(s, "ua"))
		manager.run_crawl_job(run, fetcher_obj=f)
		self.assertTrue(
			frappe.db.exists("SEO Audit Finding", {"crawl_run": run, "code": "ROBOTS_TXT_UNPARSEABLE"})
		)

	def test_js_render_sayfasi_bulgu_uretir(self):
		u = f"{self._site}/spa"
		with patch("frappe.enqueue"):
			run = manager.start_crawl("full", routes=[u])
		self._run_cleanup(run)
		spa = '<html><head><script type="module" src="/@vite/client"></script></head><body><div id="app"></div></body></html>'
		f, _ = self._fetcher({u: (200, spa)})
		out = manager.run_crawl_job(run, fetcher_obj=f)
		self.assertEqual(out["needs_js"], 1)
		kodlar = {
			b.code for b in frappe.get_all("SEO Audit Finding", filters={"crawl_run": run}, fields=["code"])
		}
		self.assertIn("NEEDS_JS_RENDER", kodlar)
		self.assertNotIn("TITLE_MISSING", kodlar, "içerik denetimi JS gerektiren sayfada atlanır")


class TestBotLog(Ortak662):
	LOG = (
		'66.249.66.1 - - [21/Sep/2026:10:00:01 +0000] "GET /shc-bot-a HTTP/1.1" 200 1234 "-" "Mozilla/5.0 (compatible; Googlebot/2.1)"\n'
		'66.249.66.1 - - [21/Sep/2026:10:00:02 +0000] "GET /shc-bot-a HTTP/1.1" 200 1234 "-" "Googlebot/2.1"\n'
		'40.77.167.1 - - [21/Sep/2026:11:00:00 +0000] "GET /shc-bot-gizli HTTP/1.1" 403 0 "-" "bingbot/2.0"\n'
	)

	def test_ice_aktarma_idempotent_ve_kapsam(self):
		from tradehub_core.seo_helper.crawler import botlog

		frappe.db.delete("SEO Bot Visit", {"path": ["like", "/shc-bot-%"]})  # önceki koşum kalıntısı
		frappe.db.commit()
		self.addCleanup(lambda: frappe.db.delete("SEO Bot Visit", {"path": ["like", "/shc-bot-%"]}))
		r1 = botlog.import_text(self.LOG, host="t", verify=False)
		r2 = botlog.import_text(self.LOG, host="t", verify=False)
		self.assertEqual((r1["rows"], r2["rows"], r1["lines"]), (2, 2, 3))
		self.assertEqual(
			frappe.db.get_value("SEO Bot Visit", {"path": "/shc-bot-a"}, "hits"),
			2,
			"yeniden içe aktarma sayacı katlamaz",
		)
		self.assertEqual(frappe.db.get_value("SEO Bot Visit", {"path": "/shc-bot-gizli"}, "blocked"), 1)
		self.assertTrue(frappe.db.get_value("SEO Helper Settings", None, "bot_log_last_import_at"))
		p = self._seo_page("bot-req")
		route = frappe.db.get_value("SEO Page", p, "route")
		frappe.db.set_value("SEO Page", p, "indexable", 1)
		with patch.object(botlog, "requested_paths", return_value=({route, "/shc-bot-a"}, False)):
			k = botlog.coverage(days=400)
		self.assertIn(route, k["requested_not_crawled"])
		self.assertIn("/shc-bot-gizli", k["crawled_not_requested"])
		self.assertGreaterEqual(
			k["bots"]["googlebot"], 2
		)  # kapsam tüm kayıtları sayar (başka testlerin botları da olabilir)
		self.assertGreaterEqual(k["blocked_hits"], 1)


class TestIsciKesintisi(Ortak662):
	def test_stale_running_kosum_paused_olur_imlec_sayfa_sayisina(self):
		"""İşçi öldü, koşum 'running' kaldı: 30 dk hareketsiz → paused, cursor = yazılmış sayfa sayısı; taze koşuma dokunulmaz."""
		with patch("frappe.enqueue"):
			run = manager.start_crawl(
				"targeted", routes=[f"{self._site}/shc-stale-{self._sonek()}-{i}" for i in range(5)]
			)
		self._run_cleanup(run)
		frappe.db.set_value(
			"SEO Crawl Run",
			run,
			{
				"status": "running",
				"cursor": 0,
				"started_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-90),
			},
			update_modified=False,
		)
		for i in range(2):
			frappe.get_doc(
				{
					"doctype": "SEO Crawl Page",
					"crawl_run": run,
					"url": f"u{i}",
					"route": f"/u{i}",
					"status_code": 200,
					"fetched_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-60),
				}
			).insert(ignore_permissions=True)
		frappe.db.commit()
		taze = frappe.db.get_value("SEO Crawl Run", run, "name")
		r = manager.recover_stale_runs(minutes=30)
		self.assertIn(taze, r["paused"])
		d = frappe.db.get_value("SEO Crawl Run", run, ["status", "cursor", "last_error"], as_dict=True)
		self.assertEqual((d.status, d.cursor), ("paused", 2))
		self.assertEqual(
			frappe.db.get_value("SEO Crawl Run", run, ["pages_ok", "pages_failed"]),
			(2, 0),
			"sayaçlar satırlardan kuruldu",
		)
		self.assertIn("işçi kesildi", d.last_error)
		# taze etkinlik → dokunma
		frappe.db.set_value("SEO Crawl Run", run, "status", "running", update_modified=False)
		frappe.db.set_value("SEO Crawl Page", {"crawl_run": run}, "fetched_at", frappe.utils.now_datetime())
		frappe.db.commit()
		self.assertNotIn(run, manager.recover_stale_runs(minutes=30)["paused"])
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", run, "status"), "running")
		# resume kaldığı yerden (2. sayfadan) devam eder
		frappe.db.set_value("SEO Crawl Run", run, "status", "paused", update_modified=False)
		with patch("frappe.enqueue"):
			self.assertEqual(manager.resume(run)["cursor"], 2)


class TestAuditYasamDongusu(Ortak662):
	def test_yaris_aktif_anahtar_tekil(self):
		"""İki süreç aynı izi aynı anda yazar: ilk okuma 'yok' der, ekleme UNIQUE'e takılır → kilitli okuma ile
		mevcut kayıt güncellenir (çift aktif bulgu yok, occurrences 2). e2e-7 ile gerçek süreçlerde de doğrulandı."""
		from tradehub_core.seo_helper.audit import reporter

		url = f"{self._site}/shc-yaris-{self._sonek()}"
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": url}))
		f = self._bulgu(url)
		reporter.upsert_findings([f], crawl_run=None)  # "diğer süreç" yazdı
		gercek = reporter._mevcut_bulgu
		cagri = {"n": 0}

		def once_yok(fp, *, for_update=False):
			cagri["n"] += 1
			return None if cagri["n"] == 1 and not for_update else gercek(fp, for_update=for_update)

		with patch.object(reporter, "_mevcut_bulgu", side_effect=once_yok):
			r = reporter.upsert_findings([f], crawl_run=None)
		self.assertEqual((r["new"], r["updated"]), (0, 1))
		rows = frappe.get_all(
			"SEO Audit Finding",
			filters={"url": url},
			fields=["name", "status", "occurrences", "active_key", "fingerprint"],
		)
		self.assertEqual(len(rows), 1)
		self.assertEqual((rows[0].occurrences, rows[0].active_key), (2, rows[0].fingerprint))
		reporter.close_finding(rows[0].name)
		self.assertIsNone(
			frappe.db.get_value("SEO Audit Finding", {"url": url}, "active_key"), "kapalı bulgu anahtarı NULL"
		)
		reporter.upsert_findings(
			[f], crawl_run=None
		)  # kapalıyken iz yeniden üretildi → reopened, anahtar geri gelir
		self.assertEqual(
			frappe.db.get_value("SEO Audit Finding", {"url": url}, ["status", "active_key"]),
			("reopened", f["fingerprint"]),
		)

	def _bulgu(self, url, code="HTTP_5XX", **ek):
		from tradehub_core.seo_helper.audit.rules import finding, fingerprint

		f = finding(
			code,
			"technical",
			"error",
			"sunucu hatası",
			url=url,
			evidence={"_key": "5xx"},
			root_cause="x",
			recommendation="y",
		)
		f.update(ek)
		f["fingerprint"] = fingerprint(f)
		return f

	def test_tekillestirme_ve_yeniden_acma(self):
		u = f"{self._site}/shc-life-{self._sonek()}"
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": u}))
		r1 = reporter.upsert_findings([self._bulgu(u)], crawl_run=None)
		r2 = reporter.upsert_findings([self._bulgu(u)], crawl_run=None)
		self.assertEqual((r1["new"], r2["new"], r2["updated"]), (1, 0, 1))
		self.assertEqual(frappe.db.count("SEO Audit Finding", {"url": u}), 1)
		row = frappe.db.get_value(
			"SEO Audit Finding",
			{"url": u},
			[
				"name",
				"occurrences",
				"category",
				"root_cause",
				"owner_role",
				"recommendation",
				"evidence",
				"status",
			],
			as_dict=True,
		)
		self.assertEqual(
			(row.occurrences, row.category, row.owner_role, row.status),
			(2, "technical", "SEO Manager", "open"),
		)
		self.assertTrue(
			row.root_cause and row.recommendation and json.loads(row.evidence).get("_key") == "5xx"
		)
		reporter.close_finding(row.name)
		self.assertEqual(frappe.db.get_value("SEO Audit Finding", row.name, "status"), "closed")
		r3 = reporter.upsert_findings([self._bulgu(u)], crawl_run=None)
		self.assertEqual(r3["reopened"], 1)
		self.assertEqual(
			frappe.db.get_value("SEO Audit Finding", row.name, ["status", "resolved"]), ("reopened", 0)
		)

	def test_duzelt_yeniden_tara_kapat(self):
		u = f"{self._site}/shc-fix-{self._sonek()}"
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": u}))
		reporter.upsert_findings([self._bulgu(u)], crawl_run=None)
		name = frappe.db.get_value("SEO Audit Finding", {"url": u}, "name")
		with patch("frappe.enqueue"):
			r = reporter.mark_fixed(name)
		self._run_cleanup(r["recrawl_run"])
		self.assertEqual(r["status"], "recrawl_pending")
		self.assertEqual(
			frappe.db.get_value("SEO Crawl Run", r["recrawl_run"], ["mode", "pages_total"]), ("targeted", 1)
		)
		# yeniden tarama: sayfa artık 200 → iz üretilmez → kapanır
		f, _ = self._fetcher({u: (200, _ok_html(u))})
		manager.run_crawl_job(r["recrawl_run"], fetcher_obj=f)
		self.assertEqual(
			frappe.db.get_value("SEO Audit Finding", name, ["status", "resolved"]), ("closed", 1)
		)
		# aynı akış ama sorun sürüyor → yeniden açılır
		u2 = f"{self._site}/shc-fix2-{self._sonek()}"
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": u2}))
		reporter.upsert_findings([self._bulgu(u2)], crawl_run=None)
		n2 = frappe.db.get_value("SEO Audit Finding", {"url": u2}, "name")
		with patch("frappe.enqueue"):
			r2 = reporter.mark_fixed(n2)
		self._run_cleanup(r2["recrawl_run"])
		f2, _ = self._fetcher({u2: (500, "<html><body>hata</body></html>")})
		manager.run_crawl_job(r2["recrawl_run"], fetcher_obj=f2)
		self.assertEqual(frappe.db.get_value("SEO Audit Finding", n2, "status"), "reopened")
		self.assertEqual(
			frappe.db.count("SEO Audit Finding", {"url": u2}), 1, "yeniden tarama ikinci kayıt açmaz"
		)

	def test_rapor_ozet_ve_suzgec(self):
		u = f"{self._site}/shc-rep-{self._sonek()}"
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"url": u}))
		reporter.upsert_findings(
			[
				self._bulgu(u),
				self._bulgu(
					u,
					code="TITLE_MISSING",
					category="content",
					severity="warning",
					owner_role="SEO Editor",
					evidence={"_key": "title"},
				),
			],
			crawl_run=None,
		)
		r = reporter.report(category="content", days=1)
		self.assertTrue(all(x.category == "content" for x in r["rows"]))
		self.assertIn("SEO Editor", r["summary"]["by_owner"])
		tum = reporter.report(days=1)
		self.assertGreaterEqual(tum["by_status"].get("open", 0), 2)


class TestPano(Ortak662):
	def test_kaynaklar_guncellik_gorunurluk_anomali(self):
		from tradehub_core.seo_helper import board

		kaynaklar = {s["key"]: s for s in board.sources()}
		self.assertEqual(set(kaynaklar), {"search_console", "analytics", "crawler", "log", "merchant"})
		for s in kaynaklar.values():
			for k in ("configured", "last_at", "age_minutes", "stale"):
				self.assertIn(k, s)
		self.assertFalse(kaynaklar["search_console"]["configured"], "GSC ayarlanmadı → yapılandırılmamış")
		for dim in ("all", "store", "lang", "page_type"):
			rows = board.visibility(dim)
			self.assertTrue(rows)
			self.assertIn("crawl_ok_pct", rows[0])
		with self.assertRaises(frappe.ValidationError):
			board.visibility("bozuk")
		# anomali: 7 gün 100, bugün 40 → tıklama düşüşü 'bad'
		gun = frappe.utils.getdate(nowdate())
		for i in range(1, 8):
			board.write_snapshot(gun - timedelta(days=i), "search_console", "all", "all", "gsc_clicks", 100)
		board.write_snapshot(gun, "search_console", "all", "all", "gsc_clicks", 40)
		self.addCleanup(
			lambda: frappe.db.delete("SEO Metric Snapshot", {"metric": "gsc_clicks", "dimension": "all"})
		)
		an = {a["metric"]: a for a in board.anomalies()}
		self.assertTrue(an["gsc_clicks"]["anomaly"])
		self.assertTrue(an["gsc_clicks"]["bad"])
		self.assertEqual(an["gsc_clicks"]["direction"], "down")
		r = board.snapshot_daily()
		self.assertGreaterEqual(r["snapshots"], 5)
		self.assertTrue(
			frappe.db.exists(
				"SEO Metric Snapshot", {"metric": "pages_indexable", "dimension": "all", "day": gun}
			)
		)


class TestSearchConsoleFrappe(Ortak662):
	def test_kota_defteri(self):
		from tradehub_core.seo_helper.connectors import search_console as gsc

		self.addCleanup(lambda: frappe.db.delete("SEO Connector Quota", {"connector": "test"}))
		self.assertEqual(gsc.quota_consume("test", "m", 5, 10), 5)
		self.assertEqual(gsc.quota_consume("test", "m", 5, 10), 10)
		with self.assertRaises(gsc.QuotaExceeded):
			gsc.quota_consume("test", "m", 1, 10)
		self.assertEqual(gsc.quota_used("test", "m")["used"], 10)

	def test_senkron_mock_istemci_eksik_gunler(self):
		from tradehub_core.seo_helper.connectors import search_console as gsc

		bugun = frappe.utils.getdate(nowdate())
		rows = [
			{
				"date": (bugun - timedelta(days=5)).isoformat(),
				"page": f"{self._site}/urun/x",
				"clicks": 3,
				"impressions": 30,
				"ctr": 0.1,
				"position": 2,
			}
		]
		client = SimpleNamespace(search_analytics=lambda *a, **k: rows)
		self.addCleanup(lambda: frappe.db.delete("SEO Metric Snapshot", {"source": "search_console"}))
		self.addCleanup(lambda: frappe.db.delete("SEO Connector Quota", {"connector": "search_console"}))
		r = gsc.sync_search_analytics(days=7, client=client)
		self.assertEqual(r["rows"], 1)
		self.assertEqual(len(r["missing_days"]), 3, "veri gecikmesi 3 gün → 3 eksik gün")
		self.assertEqual(
			frappe.db.get_value(
				"SEO Metric Snapshot",
				{"metric": "gsc_clicks", "dimension": "all", "day": bugun - timedelta(days=5)},
				"value",
			),
			3,
		)
		self.assertEqual(
			frappe.db.get_value(
				"SEO Metric Snapshot", {"metric": "gsc_clicks", "dimension": "all", "day": bugun}, "missing"
			),
			1,
		)
		self.assertEqual(
			frappe.db.get_value(
				"SEO Metric Snapshot",
				{"metric": "gsc_clicks", "dimension": "page_type", "dimension_key": "listing"},
				"value",
			),
			3,
		)
		self.assertTrue(frappe.db.get_value("SEO Helper Settings", None, "gsc_last_sync_at"))
		self.assertEqual(gsc.quota_used("search_console", "search_analytics")["used"], 1)
		self.assertFalse(gsc.status()["configured"])

	def test_url_inspection_orneklem_ve_bulgu(self):
		frappe.db.set_single_value("SEO Helper Settings", "gsc_daily_inspection_quota", 2000)
		frappe.clear_cache(doctype="SEO Helper Settings")
		from tradehub_core.seo_helper.connectors import search_console as gsc

		p = self._seo_page("insp")
		from tradehub_core.seo_helper.core.policy import apply_for_page

		apply_for_page(p)
		u = frappe.db.get_value("SEO Page", p, "effective_canonical")
		client = SimpleNamespace(
			inspect=lambda url, language="tr": {
				"url": url,
				"verdict": "NEUTRAL",
				"coverage_state": "Discovered - currently not indexed",
				"google_canonical": None,
			}
		)
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"code": "GSC_NOT_INDEXED"}))
		self.addCleanup(lambda: frappe.db.delete("SEO Connector Quota", {"connector": "search_console"}))
		self.addCleanup(
			lambda: frappe.db.delete(
				"SEO Metric Snapshot", {"metric": ["in", ["gsc_sampled", "gsc_indexed_ratio"]]}
			)
		)
		r = gsc.sync_url_inspection(client=client, limit=1000)
		self.assertGreaterEqual(r["sampled"], 1)
		self.assertTrue(frappe.db.exists("SEO Audit Finding", {"code": "GSC_NOT_INDEXED", "url": u}))
		self.assertEqual(gsc.quota_used("search_console", "url_inspection")["used"], r["sampled"])


class TestAtifVeDeney(Ortak662):
	def test_kanca_cerezden_alanlari_doldurur(self):
		from tradehub_core.seo_helper.experiments import attribution

		if not frappe.get_meta("RFQ").has_field("seo_is_organic"):
			self.skipTest("atıf Custom Field'ları kurulu değil (after_migrate)")
		buyer = self._user("atif", roles=("Buyer",))
		cerez = attribution.sign_payload(
			attribution._secret(),
			attribution.landing_payload("/urun/abc", "https://www.google.com/", {}, "tr"),
		)
		# imzasız çerez yok sayılır (kod incelemesi bulgusu)
		sahte = SimpleNamespace(
			cookies={attribution.COOKIE: json.dumps({"organic": 1, "path": "/x"})}, headers={}
		)
		frappe.local.request = sahte
		self.assertIsNone(attribution._cookie_payload())
		req = SimpleNamespace(cookies={attribution.COOKIE: cerez}, headers={})
		onceki = getattr(frappe.local, "request", None)
		frappe.local.request = req
		try:
			doc = frappe.get_doc(
				{"doctype": "RFQ", "buyer": buyer, "product_name": "test", "quantity": 1, "status": "Pending"}
			)
			doc.flags.ignore_permissions = True
			doc.flags.ignore_mandatory = True
			doc.insert()
		finally:
			frappe.local.request = onceki
		self.addCleanup(lambda: self._drop("RFQ", doc.name))
		row = frappe.db.get_value(
			"RFQ", doc.name, ["seo_is_organic", "seo_landing_path", "seo_referrer"], as_dict=True
		)
		self.assertEqual((row.seo_is_organic, row.seo_landing_path), (1, "/urun/abc"))
		# toplulaştırma
		self.addCleanup(lambda: frappe.db.delete("SEO Metric Snapshot", {"source": "analytics"}))
		r = attribution.rollup_daily(nowdate())
		self.assertGreaterEqual(r["organic_conversions"], 1)
		self.assertGreaterEqual(
			frappe.db.get_value(
				"SEO Metric Snapshot",
				{
					"source": "analytics",
					"dimension": "page_type",
					"dimension_key": "listing",
					"metric": "rfq_organic",
				},
				"value",
			),
			1,
		)

	def test_degisiklik_kaydi_otomatik_politika_ve_builder(self):
		from tradehub_core.seo_helper.experiments import changelog

		self.addCleanup(lambda: frappe.db.delete("SEO Change Log", {"description": ["like", "%shc-cl%"]}))
		pol = frappe.get_doc(
			{
				"doctype": "SEO Policy",
				"policy_key": f"shc-cl-{self._sonek()}",
				"applies_to": "page",
				"min_title_len": 10,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("SEO Policy", pol.name))
		self.addCleanup(lambda: frappe.db.delete("SEO Change Log", {"scope_key": pol.name}))
		pol.min_title_len = 20
		pol.save(ignore_permissions=True)
		self.assertTrue(
			frappe.db.exists(
				"SEO Change Log", {"scope_key": pol.name, "change_type": "policy", "source": "auto"}
			)
		)
		bp = self._builder_page("cl")
		route = frappe.db.get_value("SEO Page", {"builder_page": bp}, "route")
		self.addCleanup(lambda: frappe.db.delete("SEO Change Log", {"route": route}))
		d = frappe.get_doc("Builder Page", bp)
		d.seo_publish_state = "suspended"
		d.flags.ignore_permissions = True
		d.save()
		self.assertTrue(
			frappe.db.exists("SEO Change Log", {"route": route, "change_type": "content", "source": "auto"})
		)
		n = changelog.log_change(change_type="deploy", description="shc-cl elle kayıt", expected_effect="x")
		self.assertTrue(any(r.name == n for r in changelog.recent(days=1, change_type="deploy")))
		with self.assertRaises(frappe.ValidationError):
			changelog.log_change(change_type="bozuk", description="x")

	def test_deney_olustur_degerlendir_mevsimsellik(self):
		from tradehub_core.seo_helper import board
		from tradehub_core.seo_helper.experiments import experiments

		key = f"shc-exp-{self._sonek()}"
		self.addCleanup(lambda: frappe.db.delete("SEO Change Log", {"experiment": key}))
		self.addCleanup(lambda: self._drop("SEO Experiment", key))
		self.addCleanup(
			lambda: frappe.db.delete(
				"SEO Metric Snapshot", {"dimension": "route", "dimension_key": ["like", "/shc-exp%"]}
			)
		)
		bugun = frappe.utils.getdate(nowdate())
		bas, bit = bugun - timedelta(days=6), bugun
		# 7 gün deney + 7 gün öncesi: deney 2→4, kontrol 2→2
		for i in range(14):
			g = bas - timedelta(days=7) + timedelta(days=i)
			deney = 4.0 if g >= bas else 2.0
			board.write_snapshot(g, "analytics", "route", "/shc-exp-t", "organic_conversions", deney)
			board.write_snapshot(g, "analytics", "route", "/shc-exp-c", "organic_conversions", 2.0)
		with self.assertRaises(frappe.ValidationError):
			experiments.create(
				key,
				title="x",
				treatment_routes=["/shc-exp-t"],
				control_routes=["/shc-exp-t"],
				start_date=bas,
				end_date=bit,
			)
		experiments.create(
			key,
			title="Başlık deneyi",
			treatment_routes=["/shc-exp-t"],
			control_routes=["/shc-exp-c"],
			start_date=bas,
			end_date=bit,
			hypothesis="h",
		)
		self.assertTrue(frappe.db.exists("SEO Change Log", {"experiment": key, "change_type": "experiment"}))
		r = experiments.evaluate(key)
		self.assertEqual(r["method"], "did")
		self.assertAlmostEqual(r["lift_pct"], 100.0)
		self.assertEqual(r["data_quality"], "ok")
		self.assertEqual(r["seasonality"]["method"], "weekday")
		self.assertEqual(frappe.db.get_value("SEO Experiment", key, "status"), "evaluated")
		self.assertIn(key, [e["name"] for e in experiments.list_experiments()])


class TestPanel662Kapisi(Ortak662):
	def test_satici_uclara_giremez_admin_girer(self):
		from tradehub_core.seo_helper.api import panel662 as p
		from tradehub_core.tests.mogem620_ortak import kullanici

		_s, u = self._seller("p662")
		with kullanici(u):
			for fn, args in (
				(p.crawl_runs, {}),
				(p.crawl_start, {"mode": "full"}),
				(p.botlog_coverage, {}),
				(p.board_overview, {}),
				(p.audit_report, {}),
				(p.gsc_status, {}),
				(p.changelog, {}),
				(p.experiments_list, {}),
				(p.botlog_import, {"text": "x"}),
				(p.audit_export, {"fmt": "csv"}),
				(p.audit_import_signals, {"kind": "all"}),
			):
				with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
					fn(**args)
		frappe.set_user("Administrator")
		self.assertIsInstance(p.crawl_runs(), list)
		ov = p.board_overview()
		self.assertEqual(set(ov), {"sources", "visibility", "anomalies", "conversions", "scope"})
		self.assertIn("limited", ov["scope"])
		self.assertIn("configured", p.gsc_status())
		with patch("frappe.enqueue"):
			r = p.crawl_start(
				mode="targeted", routes=[f"{self._site}/shc-panel-x"], max_pages="5", rate_limit_rps="1.5"
			)
		self._run_cleanup(r["name"])
		self.assertEqual((r["mode"], r["max_pages"], r["rate_limit_rps"]), ("targeted", 5, 1.5))
		with self.assertRaises(frappe.ValidationError):
			p.crawl_start(mode="full", max_pages="abc")
		with self.assertRaises(frappe.ValidationError):
			p.botlog_import(text="")


def _unused(_: date):  # pragma: no cover
	return add_days


class TestKatalogVeMerchantDenetimi(Ortak662):
	"""13.4 katalog + merchant kategorileri gerçek kayıtlarla: SEO Entity + mağaza + Merchant Map."""

	def test_merchant_ve_katalog_bulgulari(self):
		store, _ = self._seller("mm")
		ent = frappe.get_doc(
			{
				"doctype": "SEO Entity",
				"entity_type": "listing",
				"ref_doctype": "Listing",
				"ref_name": "LST-YOK",
				"store": store,
				"canonical_path": f"/urun/shc-mm-{self._sonek()}",
				"indexable": 1,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("SEO Entity", ent.name))
		self._seo_page(
			"mm", route=ent.canonical_path, store=store, entity=ent.name, source="catalog", title=""
		)
		mm = frappe.get_doc(
			{
				"doctype": "SEO Merchant Map",
				"store": store,
				"status": "draft",
				"feed_url": "",
				"mapping": json.dumps({"id": "sku"}),
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("SEO Merchant Map", mm.name))
		u = f"{self._site}{ent.canonical_path}"
		with patch("frappe.enqueue"):
			run = manager.start_crawl("targeted", routes=[u])
		self._run_cleanup(run)
		f, _ = self._fetcher({u: (200, _ok_html(u))})
		manager.run_crawl_job(run, fetcher_obj=f)
		kodlar = {
			b.code for b in frappe.get_all("SEO Audit Finding", filters={"crawl_run": run}, fields=["code"])
		}
		for k in (
			"MERCHANT_MAP_INACTIVE",
			"MERCHANT_FEED_MISSING",
			"MERCHANT_MAPPING_INCOMPLETE",
			"LISTING_META_MISSING",
		):
			self.assertIn(k, kodlar, kodlar)
		# sorumlu: merchant bulguları mağazaya yazılır
		row = frappe.db.get_value(
			"SEO Audit Finding",
			{"crawl_run": run, "code": "MERCHANT_FEED_MISSING"},
			["owner_role", "owner_store", "store"],
			as_dict=True,
		)
		self.assertEqual((row.owner_role, row.owner_store, row.store), ("Mağaza", store, store))
		# rapor mağaza süzgeci
		r = reporter.report(store=store, days=1)
		self.assertTrue(all(x.store == store for x in r["rows"]) and r["total"] >= 4)
		self.assertIn("Mağaza", r["summary"]["by_owner"])

	def test_artimli_mod_gercek_kosum_sonrasi(self):
		urls = [f"{self._site}/inc{i}" for i in range(4)]
		with patch("frappe.enqueue"):
			r1 = manager.start_crawl("targeted", routes=urls)
		self._run_cleanup(r1)
		f, _ = self._fetcher({u: (200, _ok_html(u)) for u in urls})
		manager.run_crawl_job(r1, fetcher_obj=f)
		with (
			patch("frappe.enqueue"),
			patch.object(manager, "candidate_urls", return_value=urls + [f"{self._site}/inc-yeni"]),
		):
			r2 = manager.start_crawl("incremental")
		self._run_cleanup(r2)
		self.assertEqual(
			json.loads(frappe.db.get_value("SEO Crawl Run", r2, "url_list")),
			[f"{self._site}/inc-yeni"],
			"yeni taranan sayfalar atlanır, hiç taranmamış seçilir",
		)
		# artımlı: N günden eski taranan yeniden seçilir
		frappe.db.sql(
			"update `tabSEO Crawl Page` set fetched_at = date_sub(now(), interval 30 day) where crawl_run=%s",
			r1,
		)
		frappe.db.commit()
		with patch("frappe.enqueue"), patch.object(manager, "candidate_urls", return_value=urls):
			r3 = manager.start_crawl("incremental")
		self._run_cleanup(r3)
		self.assertEqual(frappe.db.get_value("SEO Crawl Run", r3, "pages_total"), 4)
