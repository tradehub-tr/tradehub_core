"""13.1 Crawl Manager — Frappe tarafı: koşum aç, `seo_long` kuyruğunda işle, checkpoint,
duraklat/devam et/iptal, bütçe. Sonuçlar `SEO Crawl Page`; bitişte denetim (13.4) koşar.

Kuyruk: `core.queue` (`SEO Sync Job`, backoff, dedupe) — handler `crawl.run`.
Duraklatma: iş her `checkpoint_every` sayfada `pause_requested`'ı DB'den yeniden okur; görürse
`cursor`'ı yazıp `paused` bırakır. `resume` aynı URL listesiyle (plan sabit) yeniden kuyruklar.
"""

from __future__ import annotations

import json
import time
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.utils import now_datetime

from tradehub_core.seo_helper.crawler import botlog, fetcher, plan

FETCH_FIELDS = (
	"status_code",
	"fetched_at",
	"response_ms",
	"bytes",
	"rendered_with",
	"needs_js",
	"robots_blocked",
	"redirect_chain",
	"final_url",
	"title",
	"meta_description",
	"canonical",
	"robots_meta",
	"h1_count",
	"word_count",
	"hreflang",
	"internal_links",
	"images_without_alt",
	"json_ld_types",
	"content_hash",
	"error",
)


def _settings():
	return frappe.get_cached_doc("SEO Helper Settings")


def _site() -> str:
	from tradehub_core.seo_helper.adapters.tradehub.meta import site_url

	return site_url().rstrip("/")


def allowed_hosts() -> set[str]:
	"""Tarayıcının gidebileceği hostlar: site URL'i + SEO Domain kayıtları (+ storefront_base_url). SSRF kalkanı."""
	hosts = {urlsplit(_site()).netloc.lower()}
	for d in frappe.get_all("SEO Domain", fields=["host", "storefront_base_url"], limit_page_length=200):
		if d.host:
			hosts.add(d.host.lower().strip("/"))
		if d.storefront_base_url:
			u = d.storefront_base_url.strip()
			hosts.add(
				urlsplit(u if "://" in u else f"//{u}").netloc.lower()
			)  # şemasız girildiyse de host çıkar
	return {h for h in hosts if h}


def _validate_target(url: str, hosts: set[str]) -> str:
	parts = urlsplit(url)
	if parts.scheme not in ("http", "https") or not parts.netloc:
		frappe.throw(_("Geçersiz tarama adresi: {0}").format(url[:120]), frappe.ValidationError)
	if parts.netloc.lower() not in hosts:
		frappe.throw(
			_("Tarama yalnız site hostlarına yapılır ({0}); reddedildi: {1}").format(
				", ".join(sorted(hosts)), parts.netloc
			),
			frappe.PermissionError,
		)
	return url


def candidate_urls(*, store: str | None = None, routes: list[str] | None = None) -> list[str]:
	"""Adaylar: yayında SEO Page'ler (+ sitemap URL'leri); `routes` verilirse yalnız onlar (mutlak URL'e
	çevrilir; mutlak verildiyse host beyaz listesinden geçer — SSRF kalkanı)."""
	site = _site()
	if routes:
		hosts = allowed_hosts()
		return [_validate_target(r, hosts) if "://" in r else f"{site}/{r.strip('/')}" for r in routes if r]
	filters = {"publish_state": "published"}
	if store:
		filters["store"] = store
	urls = []
	for p in frappe.get_all(
		"SEO Page",
		filters=filters,
		fields=["route", "effective_canonical"],
		order_by="route",
		limit_page_length=100000,
	):
		urls.append(p.effective_canonical or f"{site}{p.route}")
	try:
		from tradehub_core.seo_helper.adapters.tradehub import sitemap as sm

		urls.extend(sm.all_urls())
	except Exception:  # noqa: BLE001 — sitemap okunamazsa SEO Page listesi yeter; kayda düş
		frappe.log_error(title="seo_helper crawl sitemap", message=frappe.get_traceback())
	return urls


def _last_crawled_map(urls: list[str]) -> dict[str, str]:
	if not urls:
		return {}
	out: dict[str, str] = {}
	for i in range(0, len(urls), 1000):  # büyük IN yerine 1000'lik parçalar
		rows = frappe.db.sql(
			"select url, max(fetched_at) as son from `tabSEO Crawl Page` where url in %(u)s and status_code > 0 group by url",
			{"u": urls[i : i + 1000]},
			as_dict=True,
		)
		out.update({r.url: r.son for r in rows if r.son})
	return out


def _changed_since_last_crawl(urls: list[str]) -> set[str]:
	"""Son taramadan sonra değişen SEO Page'ler (modified > son fetched_at)."""
	son = _last_crawled_map(urls)
	if not son:
		return set()
	rows = frappe.get_all(
		"SEO Page", fields=["effective_canonical", "route", "modified"], limit_page_length=100000
	)
	site = _site()
	out = set()
	for r in rows:
		u = r.effective_canonical or f"{site}{r.route}"
		if u in son and r.modified and str(r.modified) > str(son[u]):
			out.add(u)
	return out


def start_crawl(
	mode: str = "full",
	*,
	routes: list[str] | None = None,
	store: str | None = None,
	sample_size: int | None = None,
	sample_pct: float | None = None,
	seed: str | None = None,
	max_pages: int | None = None,
	max_seconds: int | None = None,
	max_mb: int | None = None,
	rate_limit_rps: float | None = None,
	triggered_by: str | None = None,
	enqueue: bool = True,
) -> str:
	"""Koşum kaydı + plan (URL listesi) + kuyruk. Döner: SEO Crawl Run adı."""
	if mode not in plan.MODES:
		frappe.throw(_("Bilinmeyen tarama modu: {0}").format(mode), frappe.ValidationError)
	s = _settings()
	adaylar = candidate_urls(store=store, routes=routes)
	if mode == "targeted" and not routes:
		frappe.throw(_("targeted mod için route listesi gerekli"), frappe.ValidationError)
	seed = seed or now_datetime().strftime("%Y%m%d%H%M%S")
	secim = plan.select_urls(
		adaylar,
		"targeted" if routes else mode,
		last_crawled=_last_crawled_map(adaylar) if mode == "incremental" else None,
		changed=_changed_since_last_crawl(adaylar) if mode == "incremental" else None,
		incremental_days=int(s.crawl_incremental_days or 7),
		sample_size=sample_size,
		sample_pct=sample_pct,
		seed=seed,
	)
	run = frappe.get_doc(
		{
			"doctype": "SEO Crawl Run",
			"mode": mode,
			"scope": json.dumps(
				{"routes": routes or [], "store": store, "mode": mode, "candidates": len(adaylar)}
			),
			"status": "queued",
			"triggered_by": triggered_by or f"panel:{frappe.session.user}",
			"queue": "seo_long",
			"rate_limit_rps": float(
				rate_limit_rps if rate_limit_rps is not None else (s.crawl_rate_limit_rps or 2)
			),
			"max_pages": int(max_pages if max_pages is not None else (s.crawl_max_pages or 500)),
			"max_seconds": int(max_seconds if max_seconds is not None else (s.crawl_max_seconds or 1200)),
			"max_bytes": int(max_mb if max_mb is not None else (s.crawl_max_mb or 200)) * 1024 * 1024,
			"pages_total": len(secim),
			"url_list": json.dumps(secim),
			"sample_seed": seed,
			"cursor": 0,
		}
	).insert(ignore_permissions=True)  # sistem kaydı; rol denetimi API'de
	if enqueue:
		_enqueue(run.name)
	return run.name


def _enqueue(run: str, *, cursor: int = 0) -> str | None:
	from tradehub_core.seo_helper.core.queue import enqueue_after_commit

	# dedupe anahtarı imleci taşır: duraklat/devam et döngüsünde her devam yeni iş açar
	return enqueue_after_commit(
		"crawl.run", {"crawl_run": run}, queue="long", dedupe_key=f"crawl:{run}:{cursor}", timeout=7200
	)


def pause(run: str) -> dict:
	st = frappe.db.get_value("SEO Crawl Run", run, "status")
	if st not in ("queued", "running"):
		frappe.throw(
			_("Yalnız kuyruktaki/çalışan koşum duraklatılır (durum: {0})").format(st), frappe.ValidationError
		)
	frappe.db.set_value(
		"SEO Crawl Run",
		run,
		{"pause_requested": 1, **({"status": "paused"} if st == "queued" else {})},
		update_modified=False,
	)
	return {"run": run, "pause_requested": True}


def resume(run: str) -> dict:
	st = frappe.db.get_value("SEO Crawl Run", run, "status")
	if st != "paused":
		frappe.throw(
			_("Yalnız duraklatılmış koşum devam ettirilir (durum: {0})").format(st), frappe.ValidationError
		)
	frappe.db.set_value(
		"SEO Crawl Run", run, {"pause_requested": 0, "status": "queued"}, update_modified=False
	)
	cursor = int(frappe.db.get_value("SEO Crawl Run", run, "cursor") or 0)
	job = _enqueue(run, cursor=cursor)
	return {"run": run, "job": job, "cursor": cursor}


def cancel(run: str) -> dict:
	st = frappe.db.get_value("SEO Crawl Run", run, "status")
	if st in ("done", "failed", "cancelled"):
		frappe.throw(_("Bitmiş koşum iptal edilemez"), frappe.ValidationError)
	frappe.db.set_value(
		"SEO Crawl Run",
		run,
		{"pause_requested": 1, "status": "cancelled", "finished_at": now_datetime()},
		update_modified=False,
	)
	return {"run": run, "status": "cancelled"}


def _build_fetcher(run, session=None):
	import requests

	s = _settings()
	session = session or requests.Session()
	ua = s.crawl_user_agent or fetcher.DEFAULT_UA
	return fetcher.Fetcher(
		session,
		ua=ua,
		allowed_hosts=allowed_hosts(),
		rate_limiter=plan.RateLimiter(rps=float(run.rate_limit_rps or 0)),
		robots=fetcher.RobotsCache(session, ua),
		respect_robots=bool(s.crawl_respect_robots),
		js_renderer=fetcher.JsRenderer(s.crawl_js_render_command),
	)


def _write_page(run_name: str, url: str, r: fetcher.FetchResult, parsed: dict, needs_js: bool) -> None:
	route = urlsplit(r.final_url or url).path or "/"
	doc = {
		"doctype": "SEO Crawl Page",
		"crawl_run": run_name,
		"url": url[:1000],
		"route": route[:500],
		"status_code": r.status,
		"fetched_at": now_datetime(),
		"response_ms": r.response_ms,
		"bytes": r.bytes,
		"rendered_with": r.rendered_with,
		"needs_js": 1 if needs_js else 0,
		"robots_blocked": 1 if r.robots_blocked else 0,
		"redirect_chain": json.dumps(r.redirect_chain),
		"final_url": (r.final_url or "")[:1000],
		"title": (parsed.get("title") or "")[:500],
		"meta_description": parsed.get("meta_description") or "",
		"canonical": (parsed.get("canonical") or "")[:1000],
		"robots_meta": (parsed.get("robots_meta") or "")[:140],
		"html_lang": (parsed.get("html_lang") or "")[:20],
		"h1_count": parsed.get("h1_count") or 0,
		"word_count": parsed.get("word_count") or 0,
		"hreflang": json.dumps(parsed.get("hreflang") or []),
		"internal_links": parsed.get("internal_links") or 0,
		"images_without_alt": parsed.get("images_without_alt") or 0,
		"json_ld_types": json.dumps(parsed.get("json_ld_types") or []),
		"content_hash": parsed.get("content_hash") or "",
		"error": (r.error or "")[:500],
	}
	frappe.get_doc(doc).insert(ignore_permissions=True)


def run_crawl_job(crawl_run: str, *, session=None, fetcher_obj=None, clock=time.monotonic, **_) -> dict:
	"""Kuyruk işçisi. İdempotent: `cursor`'dan devam eder; sayfa satırları aynı URL için yeniden yazılmaz."""
	run = frappe.get_doc("SEO Crawl Run", crawl_run)
	if run.status in ("done", "cancelled", "failed"):
		return {"run": crawl_run, "status": run.status, "skipped": True}
	if run.status == "paused" or run.pause_requested:
		# kuyruktayken duraklatıldı: iş çalışmaz; `resume` yeni iş kuyruklar (dedupe anahtarı imleçli)
		return {"run": crawl_run, "status": "paused", "skipped": True}
	urls = json.loads(run.url_list or "[]")
	s = _settings()
	adim = max(1, int(s.crawl_checkpoint_every or 20))
	f = fetcher_obj or _build_fetcher(run, session=session)
	butce = plan.Budget(
		max_pages=int(run.max_pages or 0),
		max_seconds=int(run.max_seconds or 0),
		max_bytes=int(run.max_bytes or 0),
	)
	run.db_set(
		{"status": "running", "started_at": run.started_at or now_datetime(), "pause_requested": 0},
		update_modified=False,
	)
	frappe.db.commit()
	i = int(run.cursor or 0)
	ok = int(run.pages_ok or 0)
	fail = int(run.pages_failed or 0)
	js = int(run.pages_needs_js or 0)
	bayt = int(run.bytes_total or 0)
	gecen0 = int(run.elapsed_seconds or 0)
	t0 = clock()
	sonuc_durum = "done"
	neden = ""
	try:
		while i < len(urls):
			gecen = gecen0 + int(clock() - t0)
			sebep = butce.exceeded(pages=i, seconds=gecen, bytes_=bayt)
			if sebep:
				neden = sebep
				break
			u = urls[i]
			r = f.fetch(u)
			parsed = fetcher.parse_html(r.html, u) if r.html else {}
			needs = bool(r.html) and r.rendered_with != "js" and fetcher.needs_js(parsed, r.html)
			_write_page(run.name, u, r, parsed, needs)
			i += 1
			bayt += int(r.bytes or 0)
			if r.ok:
				ok += 1
			else:
				fail += 1
			if needs:
				js += 1
			# Sayfa satırı hemen kalıcı olsun ve İŞÇİNİN ANLIK GÖRÜNTÜSÜ TAZELENSİN: MariaDB REPEATABLE READ'de
			# commit etmeyen işçi, web sürecinin yazdığı `pause_requested`'ı hiç göremezdi (e2e'de ölçüldü).
			frappe.db.commit()
			# duraklatma isteği her sayfada okunur (ucuz sorgu; HTTP maliyetinin yanında önemsiz) → anında yanıt;
			# ilerleme yazımı (checkpoint) her `adim` sayfada bir
			duraklat = i < len(urls) and bool(
				frappe.db.get_value("SEO Crawl Run", run.name, "pause_requested")
			)
			if i % adim == 0 or i == len(urls) or duraklat:
				run.db_set(
					{
						"cursor": i,
						"pages_ok": ok,
						"pages_failed": fail,
						"pages_needs_js": js,
						"bytes_total": bayt,
						"elapsed_seconds": gecen0 + int(clock() - t0),
					},
					update_modified=False,
				)
				frappe.db.commit()
				if duraklat:
					sonuc_durum = "paused"
					break
	except Exception:  # noqa: BLE001 — kısmi sonuç korunur, koşum failed
		run.db_set(
			{
				"status": "failed",
				"cursor": i,
				"pages_ok": ok,
				"pages_failed": fail,
				"last_error": frappe.get_traceback()[-1500:],
				"finished_at": now_datetime(),
			},
			update_modified=False,
		)
		frappe.db.commit()
		raise
	if sonuc_durum == "paused":
		guncel = frappe.db.get_value("SEO Crawl Run", run.name, "status")
		run.db_set(
			{
				"status": "cancelled" if guncel == "cancelled" else "paused",
				"cursor": i,
				"pages_ok": ok,
				"pages_failed": fail,
				"pages_needs_js": js,
				"bytes_total": bayt,
				"elapsed_seconds": gecen0 + int(clock() - t0),
			},
			update_modified=False,
		)
		frappe.db.commit()
		return {
			"run": run.name,
			"status": frappe.db.get_value("SEO Crawl Run", run.name, "status"),
			"cursor": i,
		}
	bitis = {
		"status": "done",
		"cursor": i,
		"pages_ok": ok,
		"pages_failed": fail,
		"pages_needs_js": js,
		"bytes_total": bayt,
		"elapsed_seconds": gecen0 + int(clock() - t0),
		"finished_at": now_datetime(),
		"budget_exhausted": 1 if neden else 0,
		"budget_reason": neden,
	}
	run.db_set(bitis, update_modified=False)
	frappe.db.commit()
	# 13.4 — denetim raporlayıcı (+ robots.txt okunamadıysa site düzeyinde teknik bulgu)
	from tradehub_core.seo_helper.audit.reporter import run_for_crawl, upsert_findings
	from tradehub_core.seo_helper.audit.rules import finding, fingerprint

	robots_cache = getattr(f, "robots", None)
	for host in sorted(getattr(robots_cache, "unparseable", set()) or []):
		b = finding(
			"ROBOTS_TXT_UNPARSEABLE",
			"technical",
			"error",
			"robots.txt okunamadı ya da ham şablon döndü (render edilmemiş)",
			url=f"{host}/robots.txt",
			evidence={"_key": "robots_txt", "host": host},
			root_cause="robots.txt uç noktası hata veriyor ya da şablon bağlamı boş ({{ robots_txt }})",
			recommendation="robots.txt üretimini (tradehub_core.seo.robots_generator) ve www şablonunu kontrol et",
		)
		b["fingerprint"] = fingerprint(b)
		upsert_findings([b], crawl_run=run.name)
	rapor = run_for_crawl(run.name)
	frappe.db.commit()
	return {
		"run": run.name,
		"status": "done",
		"pages": i,
		"ok": ok,
		"failed": fail,
		"needs_js": js,
		"budget": neden or None,
		"findings": rapor.get("findings", 0),
		**{
			k: rapor.get(k, 0)
			for k in ("new", "updated", "reopened", "closed_after_recrawl", "reopened_after_recrawl")
		},
	}


def run_summary(run: str) -> dict:
	d = frappe.get_doc("SEO Crawl Run", run)
	return {
		"name": d.name,
		"mode": d.mode,
		"status": d.status,
		"pages_total": d.pages_total,
		"cursor": d.cursor,
		"pages_ok": d.pages_ok,
		"pages_failed": d.pages_failed,
		"pages_needs_js": d.pages_needs_js,
		"bytes_total": d.bytes_total,
		"elapsed_seconds": d.elapsed_seconds,
		"budget_exhausted": d.budget_exhausted,
		"budget_reason": d.budget_reason,
		"pause_requested": d.pause_requested,
		"findings": d.findings,
		"started_at": d.started_at,
		"finished_at": d.finished_at,
		"triggered_by": d.triggered_by,
		"rate_limit_rps": d.rate_limit_rps,
		"max_pages": d.max_pages,
		"max_seconds": d.max_seconds,
	}


def bot_page_type(path: str) -> str:
	return botlog.page_type_of(path)


def scheduled_incremental_crawl() -> dict | None:
	"""Günlük: son 24 saatte tam/artımlı koşum yoksa artımlı koşum başlat (bütçe Settings'ten)."""
	from frappe.utils import add_to_date

	son = frappe.db.get_value(
		"SEO Crawl Run",
		{"mode": ["in", ["full", "incremental"]], "creation": [">=", add_to_date(now_datetime(), hours=-24)]},
		"name",
	)
	if son:
		return None
	run = start_crawl("incremental", triggered_by="scheduler")
	frappe.db.commit()
	return {"run": run}


def recover_stale_runs(minutes: int = 30) -> dict:
	"""İşçi kesildiyse (yeniden başlatma/OOM/deploy) `running` kalan koşumlar: son etkinlik (son sayfa alınma /
	başlangıç) N dakikadan eskiyse `paused`'a alınır — `resume` kaldığı yerden devam eder. İmleç yazılmış sayfa
	sayısına eşitlenir (her sayfa commit'li; checkpoint imleci geride kalmış olabilir → çift satır önlenir).
	Saatlik zamanlayıcı."""
	from frappe.utils import add_to_date, get_datetime

	esik = add_to_date(now_datetime(), minutes=-int(minutes))
	alinan = []
	for r in frappe.get_all(
		"SEO Crawl Run", filters={"status": "running"}, fields=["name", "started_at", "modified"]
	):
		son = (
			frappe.db.get_value("SEO Crawl Page", {"crawl_run": r.name}, "max(fetched_at)")
			or r.started_at
			or r.modified
		)
		if son and get_datetime(son) > get_datetime(esik):
			continue
		# sayaçlar yazılmış satırlardan yeniden kurulur (checkpoint her N sayfada bir; kesinti arada olabilir)
		n, ok_, fail_, js_, bayt_ = frappe.db.sql(
			"""select count(*), sum(status_code between 200 and 299 and coalesce(error,'')=''),
			sum(not (status_code between 200 and 299 and coalesce(error,'')='')), sum(needs_js), coalesce(sum(bytes),0)
			from `tabSEO Crawl Page` where crawl_run=%s""",
			r.name,
		)[0]
		frappe.db.set_value(
			"SEO Crawl Run",
			r.name,
			{
				"status": "paused",
				"pause_requested": 0,
				"cursor": int(n or 0),
				"pages_ok": int(ok_ or 0),
				"pages_failed": int(fail_ or 0),
				"pages_needs_js": int(js_ or 0),
				"bytes_total": int(bayt_ or 0),
				"last_error": f"işçi kesildi: son etkinlik {son}; {minutes} dk sonra duraklatıldı (devam et ile sürer)",
			},
			update_modified=False,
		)
		alinan.append(r.name)
	if alinan:
		frappe.db.commit()
	return {"paused": alinan}


def purge_old_pages(days: int = 60) -> dict:
	"""Tarama sayfası satırları büyür: N günden eski koşumların sayfalarını sil (koşum özeti kalır)."""
	from frappe.utils import add_to_date

	esik = add_to_date(now_datetime(), days=-int(days))
	runs = frappe.get_all(
		"SEO Crawl Run", filters={"creation": ["<", esik]}, pluck="name", limit_page_length=1000
	)
	n = 0
	for r in runs:
		n += frappe.db.count("SEO Crawl Page", {"crawl_run": r})
		frappe.db.delete("SEO Crawl Page", {"crawl_run": r})
	frappe.db.commit()
	return {"runs": len(runs), "pages_deleted": n}
