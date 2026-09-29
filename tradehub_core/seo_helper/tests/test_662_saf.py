"""MOGEM-662 saf birim testleri (Frappe'siz): 13.1 plan/bütçe/hız/ayrıştırma, 13.2 log, 13.3 anomali,
13.4 kurallar/tekilleştirme, 13.5 GSC istemcisi/kota/örneklem/eksik veri, 13.6 atıf/mevsimsellik."""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace

from tradehub_core.seo_helper import board_math
from tradehub_core.seo_helper.audit import rules
from tradehub_core.seo_helper.connectors import search_console as gsc
from tradehub_core.seo_helper.crawler import botlog, fetcher, plan
from tradehub_core.seo_helper.experiments import attribution


class TestPlan(unittest.TestCase):
	def test_tam_tekrarsiz_ve_sirali(self):
		self.assertEqual(plan.select_urls(["/a", "/b", "/a", ""], "full"), ["/a", "/b"])

	def test_artimli_yalniz_eski_degisen_ve_hic_taranmamis(self):
		now = datetime(2026, 9, 22, 12)
		son = {"/yeni": now - timedelta(days=1), "/eski": now - timedelta(days=10), "/degisen": now}
		out = plan.select_urls(
			["/yeni", "/eski", "/degisen", "/hic"],
			"incremental",
			last_crawled=son,
			changed={"/degisen"},
			incremental_days=7,
			now=now,
		)
		self.assertEqual(out, ["/eski", "/degisen", "/hic"])

	def test_orneklem_deterministik_ve_boyutlu(self):
		adaylar = [f"/u{i}" for i in range(100)]
		a = plan.select_urls(adaylar, "sample", sample_size=10, seed="x")
		b = plan.select_urls(adaylar, "sample", sample_size=10, seed="x")
		c = plan.select_urls(adaylar, "sample", sample_pct=25, seed="y")
		self.assertEqual(a, b)
		self.assertEqual(len(a), 10)
		self.assertEqual(len(c), 25)
		self.assertNotEqual(a, plan.select_urls(adaylar, "sample", sample_size=10, seed="z"))

	def test_bilinmeyen_mod(self):
		with self.assertRaises(ValueError):
			plan.select_urls(["/a"], "bozuk")

	def test_butce(self):
		b = plan.Budget(max_pages=3, max_seconds=60, max_bytes=1000)
		self.assertIsNone(b.exceeded(pages=2, seconds=1, bytes_=10))
		self.assertEqual(b.exceeded(pages=3, seconds=1, bytes_=10), "max_pages")
		self.assertEqual(b.exceeded(pages=1, seconds=61, bytes_=10), "max_seconds")
		self.assertEqual(b.exceeded(pages=1, seconds=1, bytes_=1000), "max_bytes")
		self.assertIsNone(plan.Budget().exceeded(pages=10**6, seconds=10**6, bytes_=10**9), "0 = sınırsız")

	def test_hiz_siniri_host_basina(self):
		t = {"now": 0.0}
		beklenen = []
		rl = plan.RateLimiter(rps=2, clock=lambda: t["now"], sleep=lambda s: beklenen.append(s))
		self.assertEqual(rl.wait("a"), 0.0)
		self.assertAlmostEqual(rl.wait("a"), 0.5)
		self.assertEqual(rl.wait("b"), 0.0, "başka host bağımsız")
		self.assertEqual(plan.RateLimiter(rps=0).wait("a"), 0.0)


class _Resp:
	def __init__(self, status=200, text="", url="", history=None, ct="text/html"):
		self.status_code, self.text, self.url, self.history = status, text, url, history or []
		self.headers = {"Content-Type": ct}
		self.content = text.encode()

	def json(self):
		return json.loads(self.text)


class _Session:
	def __init__(self, pages: dict, robots=""):
		self.pages, self.robots, self.calls = pages, robots, []

	def get(self, url, **kw):
		self.calls.append(url)
		if url.endswith("/robots.txt"):
			return _Resp(200, self.robots, url, ct="text/plain")
		r = self.pages.get(url)
		if isinstance(r, Exception):
			raise r
		return r or _Resp(404, "<html><body>yok</body></html>", url)


HTML = """<html lang="tr"><head><title>Toptan Kampanya</title><meta name="description" content="Aciklama"><meta name="robots" content="index,follow">
<link rel="canonical" href="https://s.test/k"><link rel="alternate" hreflang="en" href="https://s.test/en/k"><link rel="alternate" hreflang="x-default" href="https://s.test/k">
<script type="application/ld+json">{"@type":"WebPage"}</script></head><body><h1>B</h1><p>%s</p><a href="/x">x</a><a href="https://baska.test/y">y</a><img src="a.jpg"><img src="b.jpg" alt="b"></body></html>""" % (
	" kelime" * 150
)
SPA = '<html><head><script type="module" src="/@vite/client"></script></head><body><div id="app"></div></body></html>'


class TestFetcher(unittest.TestCase):
	def test_parse_html_olgulari(self):
		p = fetcher.parse_html(HTML, "https://s.test/k")
		self.assertEqual(
			(p["title"], p["meta_description"], p["canonical"], p["robots_meta"]),
			("Toptan Kampanya", "Aciklama", "https://s.test/k", "index,follow"),
		)
		self.assertEqual(
			(p["h1_count"], p["internal_links"], p["images_without_alt"], p["json_ld_types"]),
			(1, 1, 1, ["WebPage"]),
		)
		self.assertEqual([h["lang"] for h in p["hreflang"]], ["en", "x-default"])
		self.assertGreaterEqual(p["word_count"], 150)
		self.assertTrue(p["content_hash"])

	def test_needs_js_spa_kabugu(self):
		self.assertTrue(fetcher.needs_js(fetcher.parse_html(SPA), SPA))
		self.assertFalse(fetcher.needs_js(fetcher.parse_html(HTML), HTML))

	def test_fetch_yonlendirme_zinciri_ve_robots(self):
		s = _Session(
			{
				"https://s.test/k": _Resp(
					200,
					HTML,
					"https://s.test/k2",
					history=[_Resp(301, "", "https://s.test/k"), _Resp(302, "", "https://s.test/k1")],
				)
			},
			robots="User-agent: *\nDisallow: /gizli",
		)
		f = fetcher.Fetcher(s, robots=fetcher.RobotsCache(s, fetcher.DEFAULT_UA))
		r = f.fetch("https://s.test/k")
		self.assertTrue(r.ok)
		self.assertEqual(len(r.redirect_chain), 2)
		self.assertEqual(r.final_url, "https://s.test/k2")
		e = f.fetch("https://s.test/gizli/x")
		self.assertTrue(e.robots_blocked)
		self.assertEqual(e.rendered_with, "none")
		self.assertEqual(sum(1 for c in s.calls if c.endswith("robots.txt")), 1, "robots bir kez okunur")

	def test_fetch_hata_ve_render_edilmemis_robots(self):
		s = _Session({"https://s.test/hata": ConnectionError("kopuk")}, robots="{{ robots_txt }}")
		rc = fetcher.RobotsCache(s, "ua")
		f = fetcher.Fetcher(s, robots=rc)
		self.assertTrue(rc.allowed("https://s.test/x"))
		self.assertIn("https://s.test", rc.unparseable)
		r = f.fetch("https://s.test/hata")
		self.assertFalse(r.ok)
		self.assertIn("ConnectionError", r.error)

	def test_js_render_komutla(self):
		s = _Session({"https://s.test/spa": _Resp(200, SPA, "https://s.test/spa")})
		js = fetcher.JsRenderer(
			"node render.js {url}", runner=lambda args, t: HTML if args[-1] == "https://s.test/spa" else ""
		)
		self.assertTrue(js.enabled)
		r = fetcher.Fetcher(s, respect_robots=False, js_renderer=js).fetch("https://s.test/spa")
		self.assertEqual(r.rendered_with, "js")
		self.assertIn("Toptan", r.html)
		self.assertFalse(fetcher.JsRenderer("").enabled)
		self.assertFalse(fetcher.JsRenderer("node x.js").enabled, "{url} yoksa kapalı")

	def test_js_render_dusunce_http_sonucu_kalir(self):
		s = _Session({"https://s.test/spa": _Resp(200, SPA, "https://s.test/spa")})

		def patla(args, t):
			raise RuntimeError("render yok")

		r = fetcher.Fetcher(
			s, respect_robots=False, js_renderer=fetcher.JsRenderer("x {url}", runner=patla)
		).fetch("https://s.test/spa")
		self.assertEqual(r.rendered_with, "http")
		self.assertIn("js_render", r.error)


LOG = """66.249.66.1 - - [21/Sep/2026:10:00:01 +0000] "GET /urun/abc HTTP/1.1" 200 1234 "-" "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
66.249.66.1 - - [21/Sep/2026:10:00:02 +0000] "GET /urun/abc HTTP/1.1" 200 1234 "-" "Mozilla/5.0 (compatible; Googlebot/2.1)"
40.77.167.1 - - [21/Sep/2026:11:00:00 +0000] "GET /gizli HTTP/1.1" 403 0 "-" "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
1.2.3.4 - - [21/Sep/2026:11:00:00 +0000] "GET /urun/abc HTTP/1.1" 200 10 "-" "Mozilla/5.0 Chrome"
bozuk satir
127.0.0.1 - - [22/Sep/2026 08:00:00] "GET /kategori/x?sayfa=2 HTTP/1.1" 200 -"""


class TestBotlog(unittest.TestCase):
	def test_ayristirma_ve_bot_siniflama(self):
		kayitlar, atlanan = botlog.parse_text(LOG)
		self.assertEqual(len(kayitlar), 5)
		self.assertEqual(atlanan, 1)
		self.assertEqual(kayitlar[-1]["path"], "/kategori/x", "sorgu dizesi atılır")
		self.assertEqual(botlog.classify_bot("Mozilla/5.0 (compatible; Googlebot/2.1)"), "googlebot")
		self.assertIsNone(botlog.classify_bot("Mozilla/5.0 Chrome"))

	def test_toplulastirma_engel_ve_dogrulama(self):
		kayitlar, _ = botlog.parse_text(LOG)
		toplu = botlog.aggregate(
			kayitlar,
			host="s.test",
			verify=True,
			resolver=lambda ip: "crawl-66-249-66-1.googlebot.com"
			if ip.startswith("66.")
			else "unknown.example",
		)
		satirlar = sorted(toplu.values(), key=lambda r: (r["bot"], r["path"]))
		self.assertEqual(
			[(r["bot"], r["path"], r["hits"], r["blocked"], r["verified"]) for r in satirlar],
			[("bingbot", "/gizli", 1, True, False), ("googlebot", "/urun/abc", 2, False, True)],
		)
		self.assertEqual(
			botlog.aggregate(kayitlar),
			botlog.aggregate(kayitlar),
			"yeniden içe aktarma aynı sonucu verir (set semantiği)",
		)

	def test_dogrulanmis_ve_sahte_bot_ayri_satir(self):
		"""Aynı gün/yol/durumda gerçek Googlebot (ters DNS doğrulu) ile UA taklidi ayrı satırlarda toplanır;
		doğrulama kapalıyken anahtar eski biçimde kalır (yeniden içe aktarma geriye uyumlu)."""
		kayitlar, _ = botlog.parse_text(
			'66.249.66.1 - - [22/Sep/2026:10:00:00 +0300] "GET /urun/x HTTP/1.1" 200 10 "-" "Googlebot/2.1"\n'
			'5.5.5.5 - - [22/Sep/2026:10:01:00 +0300] "GET /urun/x HTTP/1.1" 200 10 "-" "Googlebot/2.1 sahte"\n'
		)
		cozucu = lambda ip: "crawl-66-249-66-1.googlebot.com" if ip.startswith("66.") else "evil.example"  # noqa: E731
		toplu = botlog.aggregate(kayitlar, host="s.test", verify=True, resolver=cozucu)
		self.assertEqual(sorted((r["verified"], r["hits"]) for r in toplu.values()), [(False, 1), (True, 1)])
		kapali = botlog.aggregate(kayitlar, host="s.test", verify=False)
		self.assertEqual([(r["verified"], r["hits"]) for r in kapali.values()], [(False, 2)])
		self.assertEqual(
			next(iter(kapali)),
			botlog.dedupe_key("2026-09-22", "googlebot", "s.test", "/urun/x", 200),
			"eski anahtar biçimi",
		)

	def test_kapsam_karsilastirmasi(self):
		k = botlog.compare_coverage({"/a", "/b", "/c"}, {"/a": 5, "/x": 2})
		self.assertEqual(
			(k["both"], k["requested_not_crawled"], k["crawled_not_requested"]), (1, ["/b", "/c"], ["/x"])
		)
		self.assertEqual((k["coverage_pct"], k["hits_wasted"]), (33.3, 2))

	def test_sayfa_turu(self):
		self.assertEqual(
			[botlog.page_type_of(p) for p in ("/urun/a", "/kategori/b", "/", "/sitemap.xml", "/hakkimizda")],
			["listing", "category", "home", "system", "page"],
		)


class TestBoardMath(unittest.TestCase):
	def test_anomali_yuzde_ve_z(self):
		r = board_math.detect_anomaly(50, [100, 102, 98, 101, 99, 100, 100], pct_threshold=30)
		self.assertTrue(r["anomaly"])
		self.assertEqual(r["direction"], "down")
		self.assertFalse(board_math.detect_anomaly(105, [100, 102, 98, 101, 99, 100, 100])["anomaly"])
		self.assertEqual(board_math.detect_anomaly(5, [100])["reason"], "insufficient_history")

	def test_mevsimsellik_hafta_gunu_ve_yoy(self):
		gun = date(2026, 9, 21)
		seri = {gun - timedelta(days=7 * k): 100.0 + k for k in range(1, 5)}
		seri[gun] = 150.0
		self.assertAlmostEqual(board_math.weekday_baseline(seri, gun), 102.5)
		self.assertAlmostEqual(board_math.seasonal_adjust(seri, gun, "weekday")["ratio"], 150 / 102.5)
		self.assertTrue(board_math.seasonal_adjust(seri, gun, "yoy")["missing"])
		seri[date(2025, 9, 21)] = 75.0
		self.assertEqual(board_math.yoy_baseline(seri, gun), 75.0)

	def test_deney_karsilastirma_did(self):
		r = board_math.compare_groups(
			[12, 13, 14], [10, 10, 10], prior_treatment=[10, 10, 10], prior_control=[10, 10, 10]
		)
		self.assertEqual(r["method"], "did")
		self.assertAlmostEqual(r["lift_pct"], 30.0)
		self.assertTrue(board_math.compare_groups([1], [1])["insufficient"])

	def test_eksik_gunler(self):
		self.assertEqual(
			board_math.missing_days(date(2026, 1, 1), date(2026, 1, 3), {date(2026, 1, 2)}),
			[date(2026, 1, 1), date(2026, 1, 3)],
		)


def _facts(**crawl):
	c = {
		"url": "https://s.test/k",
		"status_code": 200,
		"title": "Toptan kampanya sayfası",
		"meta_description": "x" * 80,
		"h1_count": 1,
		"word_count": 300,
		"images_without_alt": 0,
		"canonical": "https://s.test/k",
		"robots_meta": "index,follow",
		"hreflang": [{"lang": "tr"}, {"lang": "en"}, {"lang": "x-default"}],
		"json_ld_types": ["WebPage"],
		"response_ms": 200,
	}
	c.update(crawl)
	return {
		"url": "https://s.test/k",
		"crawl": c,
		"page": {
			"effective_canonical": "https://s.test/k",
			"effective_robots": "index,follow",
			"indexable": 1,
			"lang": "tr",
		},
		"cluster": {"key": "k", "members": [{"lang": "tr"}, {"lang": "en"}]},
	}


class TestKurallar(unittest.TestCase):
	def test_temiz_sayfa_bulgusuz(self):
		self.assertEqual(rules.run_all(_facts()), [])

	def test_teknik_kategori(self):
		kodlar = {f["code"] for f in rules.technical(_facts(status_code=500))}
		self.assertIn("HTTP_5XX", kodlar)
		self.assertEqual(
			{f["code"] for f in rules.technical(_facts(robots_blocked=True))}, {"ROBOTS_BLOCKED"}
		)
		k = {
			f["code"]
			for f in rules.technical(
				_facts(
					canonical="https://s.test/baska",
					robots_meta="noindex,follow",
					response_ms=4000,
					redirect_chain=[{}, {}],
					needs_js=True,
				)
			)
		}
		self.assertEqual(
			k,
			{
				"CANONICAL_MISMATCH",
				"ROBOTS_MISMATCH",
				"INDEXABLE_BUT_NOINDEX",
				"SLOW_RESPONSE",
				"REDIRECT_CHAIN",
				"NEEDS_JS_RENDER",
			},
		)

	def test_icerik_kategori_needs_js_atlar(self):
		self.assertEqual(rules.content(_facts(needs_js=True, title="")), [])
		k = {
			f["code"]
			for f in rules.content(
				_facts(
					title="",
					meta_description="",
					h1_count=0,
					word_count=5,
					images_without_alt=2,
					json_ld_types=["INVALID"],
				)
			)
		}
		self.assertEqual(
			k,
			{
				"TITLE_MISSING",
				"DESC_MISSING",
				"H1_MISSING",
				"THIN_CONTENT",
				"IMG_ALT_MISSING",
				"JSONLD_INVALID",
			},
		)

	def test_katalog_uluslararasi_merchant(self):
		f = _facts()
		f["entity"] = {
			"name": "e1",
			"entity_type": "listing",
			"indexable": 1,
			"title": "",
			"duplicate_slug": ["e2"],
			"store": "S1",
		}
		f["page"] = None
		self.assertEqual(
			{x["code"] for x in rules.catalog(f)},
			{"ENTITY_WITHOUT_PAGE", "SLUG_DUPLICATE", "LISTING_META_MISSING"},
		)
		g = _facts(hreflang=[{"lang": "tr"}])
		g["reciprocal_missing"] = ["en"]
		self.assertEqual(
			{x["code"] for x in rules.international(g)},
			{"HREFLANG_MISSING", "HREFLANG_XDEFAULT_MISSING", "HREFLANG_NO_RETURN"},
		)
		h = _facts()
		h["entity"] = {"entity_type": "listing", "store": "S1"}
		h["merchant"] = {}
		self.assertEqual([x["code"] for x in rules.merchant(h)], ["MERCHANT_MAP_MISSING"])
		h["merchant"] = {"status": "draft", "feed_url": "", "mapping": {"id": 1}, "last_sync_age_days": 30}
		self.assertEqual(
			{x["code"] for x in rules.merchant(h)},
			{
				"MERCHANT_MAP_INACTIVE",
				"MERCHANT_FEED_MISSING",
				"MERCHANT_MAPPING_INCOMPLETE",
				"MERCHANT_SYNC_STALE",
			},
		)

	def test_her_bulgu_zorunlu_alanlari_tasir(self):
		for f in rules.run_all(_facts(status_code=404, title="", hreflang=[])):
			for k in (
				"code",
				"category",
				"severity",
				"message",
				"url",
				"evidence",
				"root_cause",
				"owner_role",
				"recommendation",
				"fingerprint",
			):
				self.assertIn(k, f)
				self.assertTrue(f[k] not in ("", None) or k in ("evidence",), f"{f['code']}.{k} boş")

	def test_parmak_izi_kararli_ve_kanit_anahtarina_duyarli(self):
		a = rules.run_all(_facts(status_code=500))[0]
		b = rules.run_all(_facts(status_code=503))[0]
		self.assertEqual(a["fingerprint"], b["fingerprint"], "aynı kod+url → aynı iz (durum değişse de)")
		c = rules.run_all(_facts(status_code=500))
		c[0]["url"] = "https://s.test/baska"
		self.assertNotEqual(rules.fingerprint(c[0]), a["fingerprint"])
		self.assertEqual(
			rules.summarize(rules.run_all(_facts(status_code=500, title="")))["by_category"]["technical"][
				"error"
			],
			1,
		)


class _Http:
	def __init__(self, seq):
		self.seq, self.calls = list(seq), []

	def _pop(self, url, kw):
		self.calls.append((url, kw))
		r = self.seq.pop(0)
		return r(url, kw) if callable(r) else r

	def post(self, url, **kw):
		return self._pop(url, kw)

	def get(self, url, **kw):
		return self._pop(url, kw)

	def put(self, url, **kw):
		return self._pop(url, kw)


def _j(status, body):
	return SimpleNamespace(status_code=status, text=json.dumps(body), json=lambda: body)


class TestSearchConsole(unittest.TestCase):
	def test_yapilandirilmamis(self):
		with self.assertRaises(gsc.NotConfigured):
			gsc.SearchConsoleClient(
				_Http([]), client_id="", client_secret="", refresh_token="", property_url=""
			)

	def test_auth_url_ve_kod_takasi(self):
		u = gsc.auth_url("cid", "https://p/cb", state="s")
		self.assertIn("access_type=offline", u)
		self.assertIn("prompt=consent", u)
		d = gsc.SearchConsoleClient.exchange_code(
			_Http([_j(200, {"refresh_token": "rt", "access_token": "at"})]),
			client_id="c",
			client_secret="s",
			code="k",
			redirect_uri="https://p/cb",
		)
		self.assertEqual(d["refresh_token"], "rt")
		with self.assertRaises(gsc.SearchConsoleError):
			gsc.SearchConsoleClient.exchange_code(
				_Http([_j(200, {"access_token": "at"})]),
				client_id="c",
				client_secret="s",
				code="k",
				redirect_uri="x",
			)

	def test_search_analytics_sayfalama_ve_token_tek_yenileme(self):
		def satir(n):
			return {
				"rows": [
					{
						"keys": ["2026-09-01", f"/p{i}"],
						"clicks": 1,
						"impressions": 10,
						"ctr": 0.1,
						"position": 3.0,
					}
					for i in range(n)
				]
			}

		http = _Http(
			[_j(200, {"access_token": "at", "expires_in": 3600}), _j(200, satir(2)), _j(200, satir(1))]
		)
		c = gsc.SearchConsoleClient(
			http, client_id="c", client_secret="s", refresh_token="r", property_url="sc-domain:s.test"
		)
		rows = c.search_analytics(
			date(2026, 9, 1), date(2026, 9, 2), dimensions=("date", "page"), row_limit=2
		)
		self.assertEqual(len(rows), 3)
		self.assertEqual(rows[0]["page"], "/p0")
		self.assertEqual(sum(1 for u, _ in http.calls if u == gsc.OAUTH_TOKEN), 1, "token bir kez alınır")
		self.assertEqual(c.calls, 2)

	def test_429_kota_ve_5xx_tekrar(self):
		http = _Http(
			[_j(200, {"access_token": "at"}), _j(503, {}), _j(200, {"sitemap": [{"path": "/sitemap.xml"}]})]
		)
		c = gsc.SearchConsoleClient(
			http, client_id="c", client_secret="s", refresh_token="r", property_url="p", sleep=lambda s: None
		)
		self.assertEqual(c.sitemaps()[0]["path"], "/sitemap.xml")
		http2 = _Http(
			[
				_j(200, {"access_token": "at"}),
				_j(429, {"error": "quota"}),
				_j(429, {"error": "quota"}),
				_j(429, {"error": "quota"}),
			]
		)
		c2 = gsc.SearchConsoleClient(
			http2, client_id="c", client_secret="s", refresh_token="r", property_url="p", sleep=lambda s: None
		)
		with self.assertRaises(gsc.QuotaExceeded):
			c2.sitemaps()

	def test_url_inspection_alanlari(self):
		http = _Http(
			[
				_j(200, {"access_token": "at"}),
				_j(
					200,
					{
						"inspectionResult": {
							"indexStatusResult": {
								"verdict": "PASS",
								"coverageState": "Submitted and indexed",
								"googleCanonical": "https://s.test/k",
							}
						}
					},
				),
			]
		)
		c = gsc.SearchConsoleClient(
			http, client_id="c", client_secret="s", refresh_token="r", property_url="p"
		)
		r = c.inspect("https://s.test/k")
		self.assertEqual((r["verdict"], r["google_canonical"]), ("PASS", "https://s.test/k"))
		self.assertEqual(http.calls[-1][0], gsc.INSPECT_API)

	def test_eksik_veri_gecikme_ve_orneklem(self):
		bugun = date(2026, 9, 22)
		s, e, gec = gsc.data_days(date(2026, 9, 10), bugun, lag_days=3, today=bugun)
		self.assertEqual((s, e), (date(2026, 9, 10), date(2026, 9, 19)))
		self.assertEqual(gec, [date(2026, 9, 20), date(2026, 9, 21), date(2026, 9, 22)])
		adaylar = [
			{"url": "/a", "published": 1, "indexable": 1, "changed_ts": 10},
			{"url": "/b", "published": 0, "indexable": 1, "changed_ts": 99},
			{"url": "/c", "published": 1, "indexable": 1, "changed_ts": 50},
		]
		self.assertEqual(
			gsc.sample_urls(adaylar, 2, seed="s"),
			["/c", "/a"],
			"yayında+indekslenebilir ve en son değişen önce",
		)
		self.assertEqual(gsc.sample_urls(adaylar, 0), [])


class TestAtif(unittest.TestCase):
	def test_organik_siniflama(self):
		self.assertEqual(
			attribution.classify("https://www.google.com/", "", ""),
			{"organic": True, "engine": "google", "channel": "organic"},
		)
		self.assertFalse(attribution.classify("https://t.co/x")["organic"])
		self.assertEqual(attribution.classify("", "newsletter", "email")["channel"], "email")
		self.assertTrue(attribution.classify("", "bing", "organic")["organic"])
		self.assertEqual(attribution.classify("")["channel"], "direct")

	def test_inis_yuku_ve_alanlar(self):
		p = attribution.landing_payload(
			"/urun/abc?x=1", "https://yandex.com.tr/search", {"utm_campaign": "k"}, lang="tr"
		)
		self.assertEqual((p["path"], p["organic"], p["engine"]), ("/urun/abc", 1, "yandex"))
		f = attribution.fields_from_payload(p)
		self.assertEqual(
			(f["seo_landing_path"], f["seo_is_organic"], f["seo_landing_lang"]), ("/urun/abc", 1, "tr")
		)
		self.assertEqual(set(f), set(attribution.FIELDS))


class TestIncelemeDuzeltmeleri(unittest.TestCase):
	"""Kod incelemesi bulguları: imzalı çerez, GSC ters aralık, fetcher host sınırı, log akışı."""

	def test_cerez_imzali_dogrulanir_sahte_reddedilir(self):
		p = attribution.landing_payload("/urun/x", "https://www.google.com/", {}, "tr")
		raw = attribution.sign_payload("gizli", p)
		self.assertEqual(attribution.verify_payload("gizli", raw), p)
		self.assertIsNone(attribution.verify_payload("baska", raw), "başka sır → red")
		self.assertIsNone(attribution.verify_payload("gizli", '{"organic":1}'), "imzasız JSON → red")
		govde, _ = raw.rsplit(".", 1)
		self.assertIsNone(attribution.verify_payload("gizli", govde + ".0" * 16))

	def test_gsc_tum_pencere_gecikmede(self):
		bugun = date(2026, 9, 22)
		s, e, gec = gsc.data_days(bugun - timedelta(days=1), bugun, lag_days=3, today=bugun)
		self.assertLess(e, s, "veri penceresi yok → end < start (API çağrılmaz)")
		self.assertEqual(len(gec), 2)

	def test_fetcher_host_beyaz_listesi_ve_dis_yonlendirme(self):
		s = _Session(
			{
				"https://s.test/k": _Resp(
					200, HTML, "https://evil.test/k", history=[_Resp(302, "", "https://s.test/k")]
				)
			}
		)
		f = fetcher.Fetcher(s, respect_robots=False, allowed_hosts={"s.test"})
		r = f.fetch("https://evil.test/x")
		self.assertIn("beyaz liste", r.error)
		self.assertEqual(s.calls, [], "istek hiç atılmadı")
		r2 = f.fetch("https://s.test/k")
		self.assertIn("dış hosta yönlendirme", r2.error)
		self.assertEqual((r2.html, r2.bytes), ("", 0))

	def test_fetcher_yonlendirme_adimi_istek_atilmadan_denetlenir(self):
		"""302 → dış host: hedefe İSTEK ATILMAZ (allow_redirects=False + adım öncesi beyaz liste)."""
		r302 = _Resp(302, "", "https://s.test/git")
		r302.headers["Location"] = "http://169.254.169.254/latest/meta-data/"
		s = _Session({"https://s.test/git": r302})
		f = fetcher.Fetcher(s, respect_robots=False, allowed_hosts={"s.test"})
		r = f.fetch("https://s.test/git")
		self.assertIn("dış hosta yönlendirme: 169.254.169.254", r.error)
		self.assertEqual(s.calls, ["https://s.test/git"], "metadata adresine istek atılmadı")
		self.assertEqual(
			(r.status, r.final_url, len(r.redirect_chain)),
			(302, "http://169.254.169.254/latest/meta-data/", 1),
		)
		# iç yönlendirme zinciri izlenir; göreli Location çözülür
		r1 = _Resp(301, "", "https://s.test/a")
		r1.headers["Location"] = "/b"
		r2 = _Resp(302, "", "https://s.test/b")
		r2.headers["Location"] = "https://s.test/k"
		s2 = _Session(
			{
				"https://s.test/a": r1,
				"https://s.test/b": r2,
				"https://s.test/k": _Resp(200, HTML, "https://s.test/k"),
			}
		)
		r = fetcher.Fetcher(s2, respect_robots=False, allowed_hosts={"s.test"}).fetch("https://s.test/a")
		self.assertEqual((r.status, r.final_url, r.error), (200, "https://s.test/k", ""))
		self.assertEqual([h["status"] for h in r.redirect_chain], [301, 302])
		self.assertTrue(r.html)
		# döngü: sınır aşılınca son 3xx kayda geçer, hata yazılır, sonsuz döngü yok
		rl = _Resp(301, "", "https://s.test/d")
		rl.headers["Location"] = "https://s.test/d"
		s3 = _Session({"https://s.test/d": rl})
		r = fetcher.Fetcher(s3, respect_robots=False, allowed_hosts={"s.test"}).fetch("https://s.test/d")
		self.assertIn("yönlendirme sınırı", r.error)
		self.assertEqual(
			(r.status, len(r.redirect_chain), len(s3.calls)),
			(301, fetcher.MAX_REDIRECTS, fetcher.MAX_REDIRECTS + 1),
		)

	def test_log_satir_yineleyicisi(self):
		kayitlar, atlanan = botlog.parse_text(iter(LOG.splitlines()))
		self.assertEqual((len(kayitlar), atlanan), (5, 1))


class TestKurallarTipsizGirdi(unittest.TestCase):
	def test_cop_olgular_exception_atmaz(self):
		import itertools

		bozuk = [
			None,
			"",
			0,
			-1,
			1.5,
			True,
			[],
			{},
			[1, "a"],
			{"a": 1},
			"🙂",
			float("inf"),
			float("nan"),
			"x" * 300,
		]
		for combo in itertools.islice(itertools.product(bozuk, repeat=3), 0, None, 5):
			facts = {
				"url": combo[0],
				"crawl": combo[1],
				"page": combo[2],
				"cluster": combo[0],
				"entity": combo[1],
				"merchant": combo[2],
			}
			if isinstance(combo[1], dict):
				facts["crawl"] = {
					k: combo[0]
					for k in (
						"url",
						"status_code",
						"title",
						"h1_count",
						"hreflang",
						"redirect_chain",
						"json_ld_types",
						"needs_js",
					)
				}
			out = rules.run_all(facts, min_title=combo[0], min_desc=combo[2])
			for f in out:
				self.assertIn(f["severity"], rules.SEVERITIES)
				self.assertTrue(f["fingerprint"])
