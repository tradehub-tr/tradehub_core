"""13.3 SEO Monitoring Board — kaynaklar + güncellik, boyut bazlı görünürlük/dönüşüm, anomali,
günlük anlık görüntü (`SEO Metric Snapshot`)."""

from __future__ import annotations

import json
from datetime import date, timedelta

import frappe
from frappe.utils import add_days, get_datetime, getdate, now_datetime, nowdate

from tradehub_core.seo_helper import board_math
from tradehub_core.seo_helper.crawler.botlog import page_type_of

DIMENSIONS = ("all", "store", "lang", "page_type")


def _settings():
	return frappe.get_cached_doc("SEO Helper Settings")


def _age_minutes(dt) -> int | None:
	if not dt:
		return None
	return int((now_datetime() - get_datetime(dt)).total_seconds() // 60)


def sources() -> list[dict]:
	"""Her veri kaynağı: yapılandırıldı mı, son veri anı, yaş, bayat mı."""
	s = _settings()
	esik = int(s.board_stale_hours or 36) * 60
	out = []

	def ekle(key, label, configured, last_at, extra=None):
		yas = _age_minutes(last_at)
		out.append(
			{
				"key": key,
				"label": label,
				"configured": bool(configured),
				"last_at": last_at,
				"age_minutes": yas,
				"stale": (yas is None or yas > esik) if configured else True,
				**(extra or {}),
			}
		)

	gsc_ok = bool(s.gsc_client_id and s.gsc_property)
	ekle("search_console", "Search Console", gsc_ok, s.gsc_last_sync_at, {"property": s.gsc_property})
	son_an = frappe.db.get_value("SEO Metric Snapshot", {"source": "analytics"}, "max(modified)")
	ekle(
		"analytics",
		"Analitik (organik dönüşüm)",
		frappe.db.exists("Custom Field", {"dt": "RFQ", "fieldname": "seo_is_organic"}) is not None,
		son_an,
	)
	son_crawl = frappe.db.get_value("SEO Crawl Run", {"status": "done"}, "max(finished_at)")
	ekle(
		"crawler",
		"Crawler",
		True,
		son_crawl,
		{"runs_done": frappe.db.count("SEO Crawl Run", {"status": "done"})},
	)
	ekle(
		"log",
		"Bot / sunucu logu",
		bool(s.bot_log_path),
		s.bot_log_last_import_at,
		{"rows": frappe.db.count("SEO Bot Visit")},
	)
	son_m = frappe.db.get_value("SEO Merchant Map", {"status": "active"}, "max(last_sync_at)")
	ekle(
		"merchant",
		"Merchant",
		frappe.db.count("SEO Merchant Map") > 0,
		son_m,
		{"maps": frappe.db.count("SEO Merchant Map", {"status": "active"})},
	)
	return out


def write_snapshot(
	day: date,
	source: str,
	dimension: str,
	dimension_key: str,
	metric: str,
	value: float,
	*,
	missing: bool = False,
) -> None:
	gun = getdate(day).isoformat()
	key = f"{gun}|{source}|{dimension}|{dimension_key}|{metric}"
	name = frappe.db.get_value("SEO Metric Snapshot", {"dedupe_key": key}, "name")
	veri = {
		"day": gun,
		"source": source,
		"dimension": dimension,
		"dimension_key": str(dimension_key)[:140],
		"metric": metric,
		"value": float(value or 0),
		"missing": 1 if missing else 0,
		"dedupe_key": key,
	}
	if name:
		frappe.db.set_value("SEO Metric Snapshot", name, veri, update_modified=True)
	else:
		frappe.get_doc({"doctype": "SEO Metric Snapshot", **veri}).insert(ignore_permissions=True)


def series(
	metric: str,
	*,
	source: str | None = None,
	dimension: str = "all",
	dimension_key: str = "all",
	days: int = 30,
) -> dict[date, float]:
	f = {
		"metric": metric,
		"dimension": dimension,
		"dimension_key": dimension_key,
		"missing": 0,
		"day": [">=", add_days(nowdate(), -int(days))],
	}
	if source:
		f["source"] = source
	rows = frappe.get_all(
		"SEO Metric Snapshot", filters=f, fields=["day", "value"], order_by="day asc", limit_page_length=10000
	)
	return {getdate(r.day): float(r.value or 0) for r in rows}


def visibility(dimension: str = "all") -> list[dict]:
	"""Mağaza/dil/sayfa türü bazlı görünürlük: sayfa, yayında, indekslenebilir, son tarama ok oranı,
	GSC tıklama/gösterim (varsa), açık bulgu."""
	if dimension not in DIMENSIONS:
		frappe.throw(f"boyut: {DIMENSIONS}")
	pages = frappe.get_all(
		"SEO Page",
		fields=["name", "route", "lang", "store", "publish_state", "indexable"],
		limit_page_length=100000,
	)
	son_run = frappe.db.get_value(
		"SEO Crawl Run",
		{"status": "done", "mode": ["in", ["full", "incremental", "sample"]]},
		"name",
		order_by="finished_at desc",
	)
	crawl = {}
	if son_run:
		for c in frappe.get_all(
			"SEO Crawl Page",
			filters={"crawl_run": son_run},
			fields=["route", "status_code", "needs_js", "response_ms"],
			limit_page_length=100000,
		):
			crawl[c.route] = c
	bulgu = {}
	for b in frappe.get_all(
		"SEO Audit Finding",
		filters={"status": ["in", ["open", "reopened", "recrawl_pending"]]},
		fields=["route", "severity"],
		limit_page_length=100000,
	):
		bulgu.setdefault(b.route, {"error": 0, "warning": 0, "info": 0})[b.severity] += 1
	gsc = {}
	if dimension == "page_type":
		for r in frappe.get_all(
			"SEO Metric Snapshot",
			filters={
				"source": "search_console",
				"dimension": "page_type",
				"metric": ["in", ["gsc_clicks", "gsc_impressions"]],
				"day": [">=", add_days(nowdate(), -7)],
				"missing": 0,
			},
			fields=["dimension_key", "metric", "sum(value) as v"],
			group_by="dimension_key, metric",
		):
			gsc.setdefault(r.dimension_key, {})[r.metric] = float(r.v or 0)
	gruplar: dict[str, dict] = {}
	for p in pages:
		key = (
			"all"
			if dimension == "all"
			else (p.store or "-")
			if dimension == "store"
			else (p.lang or "-")
			if dimension == "lang"
			else page_type_of(p.route)
		)
		g = gruplar.setdefault(
			key,
			{
				"key": key,
				"pages": 0,
				"published": 0,
				"indexable": 0,
				"crawled": 0,
				"crawl_ok": 0,
				"needs_js": 0,
				"avg_ms": 0.0,
				"_ms": [],
				"findings_error": 0,
				"findings_warning": 0,
			},
		)
		g["pages"] += 1
		g["published"] += 1 if p.publish_state == "published" else 0
		g["indexable"] += 1 if p.indexable else 0
		c = crawl.get(p.route)
		if c:
			g["crawled"] += 1
			g["crawl_ok"] += 1 if 200 <= int(c.status_code or 0) < 300 else 0
			g["needs_js"] += 1 if c.needs_js else 0
			g["_ms"].append(int(c.response_ms or 0))
		b = bulgu.get(p.route)
		if b:
			g["findings_error"] += b["error"]
			g["findings_warning"] += b["warning"]
	out = []
	for g in gruplar.values():
		ms = g.pop("_ms")
		g["avg_ms"] = round(sum(ms) / len(ms), 0) if ms else None
		g["crawl_ok_pct"] = round(100.0 * g["crawl_ok"] / g["crawled"], 1) if g["crawled"] else None
		if dimension == "page_type":
			g["gsc_clicks_7d"] = gsc.get(g["key"], {}).get("gsc_clicks")
			g["gsc_impressions_7d"] = gsc.get(g["key"], {}).get("gsc_impressions")
		out.append(g)
	if dimension == "all":
		toplam = frappe.get_all(
			"SEO Metric Snapshot",
			filters={
				"source": "search_console",
				"dimension": "all",
				"metric": ["in", ["gsc_clicks", "gsc_impressions"]],
				"day": [">=", add_days(nowdate(), -7)],
				"missing": 0,
			},
			fields=["metric", "sum(value) as v"],
			group_by="metric",
		)
		for r in toplam:
			for g in out:
				g[f"{r.metric}_7d"] = float(r.v or 0)
	return sorted(out, key=lambda g: -g["pages"])


def conversions(dimension: str = "all", days: int = 30) -> list[dict]:
	"""Organik ↔ tüm dönüşümler (RFQ / mağaza iletişimi / sipariş) boyut bazlı, son N gün toplamı."""
	rows = frappe.get_all(
		"SEO Metric Snapshot",
		filters={
			"source": "analytics",
			"dimension": dimension,
			"day": [">=", add_days(nowdate(), -int(days))],
			"missing": 0,
		},
		fields=["dimension_key", "metric", "sum(value) as v"],
		group_by="dimension_key, metric",
		limit_page_length=10000,
	)
	g: dict[str, dict] = {}
	for r in rows:
		g.setdefault(r.dimension_key, {"key": r.dimension_key})[r.metric] = float(r.v or 0)
	out = []
	for d in g.values():
		for kisa in ("rfq", "inquiry", "order"):
			t, o = d.get(f"{kisa}_total", 0.0), d.get(f"{kisa}_organic", 0.0)
			d[f"{kisa}_organic_pct"] = round(100.0 * o / t, 1) if t else None
		out.append(d)
	return sorted(
		out, key=lambda d: -(d.get("rfq_total", 0) + d.get("order_total", 0) + d.get("inquiry_total", 0))
	)


TRACKED = (
	("crawler", "crawl_ok_pct", "down"),
	("crawler", "crawl_5xx", "up"),
	("crawler", "pages_needs_js", "up"),
	("catalog", "pages_indexable", "down"),
	("catalog", "findings_error_open", "up"),
	("search_console", "gsc_clicks", "down"),
	("search_console", "gsc_impressions", "down"),
	("analytics", "organic_conversions", "down"),
	("log", "bot_hits", "down"),
	("log", "bot_blocked", "up"),
)


def anomalies(days: int | None = None) -> list[dict]:
	"""Bugün (ya da son gün) vs taban çizgisi; yalnız 'kötü yön' anomali sayılır (tıklama düşüşü, 5xx artışı)."""
	s = _settings()
	taban = int(days or s.board_baseline_days or 7)
	pct = float(s.board_anomaly_pct or 30)
	out = []
	for source, metric, kotu_yon in TRACKED:
		seri = series(metric, source=source, days=taban + 2)
		if not seri:
			continue
		gunler = sorted(seri)
		son = gunler[-1]
		gecmis = [seri[g] for g in gunler[:-1]][-taban:]
		r = board_math.detect_anomaly(seri[son], gecmis, pct_threshold=pct)
		kotu = r["anomaly"] and r.get("direction") == kotu_yon
		out.append({"source": source, "metric": metric, "day": son.isoformat(), **r, "bad": kotu})
	return sorted(out, key=lambda a: (not a["bad"], not a["anomaly"]))


def snapshot_daily(day: date | None = None) -> dict:
	"""Günlük: katalog/crawler/log metriklerini yaz (GSC ve analitik kendi senkronlarında yazar)."""
	gun = getdate(day or nowdate())
	yazilan = 0
	write_snapshot(gun, "catalog", "all", "all", "pages_total", frappe.db.count("SEO Page"))
	write_snapshot(
		gun,
		"catalog",
		"all",
		"all",
		"pages_indexable",
		frappe.db.count("SEO Page", {"indexable": 1, "publish_state": "published"}),
	)
	write_snapshot(
		gun,
		"catalog",
		"all",
		"all",
		"findings_error_open",
		frappe.db.count("SEO Audit Finding", {"status": ["in", ["open", "reopened"]], "severity": "error"}),
	)
	yazilan += 3
	run = frappe.db.get_value(
		"SEO Crawl Run",
		{"status": "done", "mode": ["!=", "targeted"]},
		["name", "pages_ok", "pages_failed", "pages_needs_js", "cursor"],
		as_dict=True,
		order_by="finished_at desc",
	)
	if run:
		toplam = int(run.cursor or 0)
		write_snapshot(
			gun,
			"crawler",
			"all",
			"all",
			"crawl_ok_pct",
			(100.0 * int(run.pages_ok or 0) / toplam) if toplam else 0.0,
			missing=not toplam,
		)
		write_snapshot(gun, "crawler", "all", "all", "pages_needs_js", int(run.pages_needs_js or 0))
		write_snapshot(
			gun,
			"crawler",
			"all",
			"all",
			"crawl_5xx",
			frappe.db.count("SEO Crawl Page", {"crawl_run": run.name, "status_code": [">=", 500]}),
		)
		yazilan += 3
	dun = add_days(gun, -1)
	hit = frappe.db.sql(
		"select coalesce(sum(hits),0), coalesce(sum(case when blocked=1 then hits else 0 end),0) from `tabSEO Bot Visit` where day=%s",
		(dun,),
	)[0]
	write_snapshot(
		dun,
		"log",
		"all",
		"all",
		"bot_hits",
		float(hit[0]),
		missing=not frappe.db.exists("SEO Bot Visit", {"day": dun}),
	)
	write_snapshot(
		dun,
		"log",
		"all",
		"all",
		"bot_blocked",
		float(hit[1]),
		missing=not frappe.db.exists("SEO Bot Visit", {"day": dun}),
	)
	yazilan += 2
	for tur, n in frappe.db.sql(
		"select coalesce(store,'-'), count(*) from `tabSEO Page` where publish_state='published' and indexable=1 group by store"
	):
		write_snapshot(gun, "catalog", "store", tur, "pages_indexable", float(n))
		yazilan += 1
	return {"day": gun.isoformat(), "snapshots": yazilan}


def daily_job() -> dict:
	"""Zamanlayıcı: anlık görüntü + analitik toplulaştırma + anomali özeti Settings'e."""
	from tradehub_core.seo_helper.experiments.attribution import rollup_daily

	r1 = snapshot_daily()
	r2 = rollup_daily()
	an = [a for a in anomalies() if a["bad"]]
	if an:
		frappe.log_error(title="SEO pano anomali", message=json.dumps(an, ensure_ascii=False, default=str))
	frappe.db.commit()
	return {**r1, "rollup": r2, "bad_anomalies": len(an)}


def scope_limits() -> dict:
	"""662 §3: pano yalnız gerçekten ölçülen veriyi gösterir — eksik kaynak, bayat veri, bütçede kesilen ya da
	başarısız son tarama varsa kapsam sınırı AÇIKÇA raporlanır (panel şerit olarak basar)."""
	nedenler: list[dict] = []
	for s in sources():
		if not s["configured"]:
			nedenler.append({"code": "source_missing", "source": s["key"], "label": s["label"]})
		elif s["stale"]:
			nedenler.append(
				{
					"code": "source_stale",
					"source": s["key"],
					"label": s["label"],
					"age_minutes": s["age_minutes"],
				}
			)
	son = frappe.db.get_value(
		"SEO Crawl Run",
		{"mode": ["!=", "targeted"]},
		[
			"name",
			"status",
			"mode",
			"cursor",
			"pages_total",
			"budget_exhausted",
			"budget_reason",
			"last_error",
			"finished_at",
			"creation",
		],
		as_dict=True,
		order_by="creation desc",
	)
	kapsam = None
	if son:
		try:
			cand = json.loads(frappe.db.get_value("SEO Crawl Run", son.name, "scope") or "{}").get(
				"candidates"
			)
		except ValueError:
			cand = None
		kapsam = {
			"run": son.name,
			"mode": son.mode,
			"status": son.status,
			"crawled": int(son.cursor or 0),
			"planned": int(son.pages_total or 0),
			"candidates": cand,
			"coverage_pct": round(100.0 * int(son.cursor or 0) / cand, 1) if cand else None,
			"finished_at": son.finished_at,
		}
		if son.status == "failed":
			nedenler.append(
				{"code": "last_run_failed", "run": son.name, "error": (son.last_error or "")[:200]}
			)
		elif son.status in ("paused", "cancelled"):
			nedenler.append({"code": "last_run_incomplete", "run": son.name, "status": son.status})
		if son.budget_exhausted:
			nedenler.append(
				{
					"code": "budget_exhausted",
					"run": son.name,
					"reason": son.budget_reason,
					"crawled": int(son.cursor or 0),
					"candidates": cand,
				}
			)
	else:
		nedenler.append({"code": "no_crawl"})
	return {"limited": bool(nedenler), "reasons": nedenler, "last_crawl": kapsam}


def overview() -> dict:
	return {
		"sources": sources(),
		"visibility": visibility("all"),
		"anomalies": anomalies()[:20],
		"conversions": conversions("all"),
		"scope": scope_limits(),
	}


def _unused(_: timedelta) -> None:  # pragma: no cover
	return None
