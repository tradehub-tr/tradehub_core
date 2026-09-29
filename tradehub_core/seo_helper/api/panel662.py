"""MOGEM-662 panel uçları (süper admin) — tarama yöneticisi, bot logu, pano, denetim raporlayıcı,
Search Console, deneyler/değişiklik kaydı. Rol kapısı `api.panel._require_admin` ile aynı."""

from __future__ import annotations

import json

import frappe
from frappe import _

from tradehub_core.seo_helper.api.panel import _j, _lim, _require_admin


def _req(v, ad: str) -> str:
	"""Zorunlu metin argümanı: boş/tipsiz → ValidationError (417), TypeError/500 değil."""
	if v is None or isinstance(v, bool | list | dict):
		frappe.throw(_("'{0}' zorunlu").format(ad), frappe.ValidationError)
	m = str(v).strip()
	if not m:
		frappe.throw(_("'{0}' zorunlu").format(ad), frappe.ValidationError)
	return m[:200]


def _int(v, default: int, ad: str = "") -> int:
	if v in (None, ""):
		return default
	try:
		return int(float(v))
	except (TypeError, ValueError):
		frappe.throw(_("'{0}' tam sayı olmalı").format(ad or "değer"), frappe.ValidationError)


def _list(v):
	v = _j(v) if isinstance(v, str) else (v or [])
	return [str(x) for x in v] if isinstance(v, list) else []


# ── 13.1 Crawl Manager ────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def crawl_start(
	mode: str = "full",
	routes=None,
	store: str = "",
	sample_size=None,
	sample_pct=None,
	max_pages=None,
	max_seconds=None,
	max_mb=None,
	rate_limit_rps=None,
) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.crawler.manager import run_summary, start_crawl

	def _num(v, tip):
		if v in (None, ""):
			return None
		try:
			return tip(v)
		except (TypeError, ValueError):
			frappe.throw(_("Sayısal değer bekleniyor"), frappe.ValidationError)

	def _sinir(v, alt, ust):
		return None if v is None else max(alt, min(v, ust))

	rotalar = _list(routes)
	if len(rotalar) > 5000:
		frappe.throw(_("Hedefli tarama en fazla 5000 route alır"), frappe.ValidationError)
	# üst sınırlar: yanlış/kötü niyetli değer siteyi ya da işçiyi boğmasın (rps 50 tavan, 0.1 taban)
	run = start_crawl(
		mode,
		routes=rotalar or None,
		store=str(store or "")[:140] or None,
		sample_size=_sinir(_num(sample_size, int), 1, 100000),
		sample_pct=_sinir(_num(sample_pct, float), 0.01, 100.0),
		max_pages=_sinir(_num(max_pages, int), 1, 100000),
		max_seconds=_sinir(_num(max_seconds, int), 5, 86400),
		max_mb=_sinir(
			_num(max_mb, int), 1, 2000
		),  # 2000 MB: bayt alanı Int (2^31) — 5000 MB taşardı (ölçüldü)
		rate_limit_rps=_sinir(_num(rate_limit_rps, float), 0.1, 50.0),
	)
	return run_summary(run)


@frappe.whitelist(methods=["POST"])
def crawl_pause(run=None) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.crawler.manager import pause

	return pause(_req(run, "run"))


@frappe.whitelist(methods=["POST"])
def crawl_resume(run=None) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.crawler.manager import resume

	return resume(_req(run, "run"))


@frappe.whitelist(methods=["POST"])
def crawl_cancel(run=None) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.crawler.manager import cancel

	return cancel(_req(run, "run"))


@frappe.whitelist(methods=["GET"])
def crawl_runs(limit=20, status: str = "") -> list:
	_require_admin()
	f = {}
	if status:
		f["status"] = str(status)[:30]
	rows = frappe.get_all(
		"SEO Crawl Run",
		filters=f,
		fields=[
			"name",
			"mode",
			"status",
			"pages_total",
			"cursor",
			"pages_ok",
			"pages_failed",
			"pages_needs_js",
			"findings",
			"budget_exhausted",
			"budget_reason",
			"pause_requested",
			"elapsed_seconds",
			"bytes_total",
			"started_at",
			"finished_at",
			"triggered_by",
			"rate_limit_rps",
			"max_pages",
			"creation",
			"scope",
			"last_error",
			"resumed_from",
		],
		order_by="creation desc",
		limit_page_length=_lim(limit, 20),
	)
	return _with_job_trace(rows)


def _with_job_trace(rows: list) -> list:
	"""662 §1/§3: koşumun kapsamı (aday sayısı/route'lar), zamanı, hatası ve TEKRAR DENEME izi
	(kuyruk işi: deneme sayısı, durum, son hata, sonraki deneme) panelden izlenir."""
	import json as _json

	if not rows:
		return rows
	adlar = [r.name for r in rows]
	isler: dict[str, list] = {}
	for j in frappe.get_all(
		"SEO Sync Job",
		filters={"dedupe_key": ["like", "crawl:%"]},
		fields=["dedupe_key", "status", "attempts", "last_error", "next_attempt_at", "finished_at"],
		order_by="creation asc",
		limit_page_length=10000,
	):
		run = (j.dedupe_key or "").split(":")[1] if ":" in (j.dedupe_key or "") else ""
		if run in adlar:
			isler.setdefault(run, []).append(j)
	for r in rows:
		try:
			kapsam = _json.loads(r.scope or "{}") if isinstance(r.scope, str) else (r.scope or {})
		except ValueError:
			kapsam = {}
		r["candidates"] = kapsam.get("candidates")
		r["scope_routes"] = len(kapsam.get("routes") or [])
		r["scope_store"] = kapsam.get("store")
		js = isler.get(r.name) or []
		r["job_count"] = len(js)
		r["job_attempts"] = sum(int(j.attempts or 0) for j in js)
		son = js[-1] if js else None
		r["job_status"] = son.status if son else None
		r["job_last_error"] = (son.last_error or "")[:300] if son else ""
		r["job_next_attempt_at"] = son.next_attempt_at if son else None
	return rows


@frappe.whitelist(methods=["GET"])
def crawl_trend(limit=20) -> list:
	"""662 §2 'trend': son tam/artımlı koşumlar aynı koşum kimliğiyle — sayfa başarı yüzdesi, bulgu, hata, süre."""
	_require_admin()
	rows = frappe.get_all(
		"SEO Crawl Run",
		filters={"mode": ["!=", "targeted"], "status": ["in", ["done", "failed", "cancelled"]]},
		fields=[
			"name",
			"mode",
			"status",
			"cursor",
			"pages_ok",
			"pages_failed",
			"pages_needs_js",
			"findings",
			"elapsed_seconds",
			"finished_at",
			"creation",
			"budget_exhausted",
		],
		order_by="creation desc",
		limit_page_length=_lim(limit, 20),
	)
	out = []
	for r in rows:
		toplam = int(r.cursor or 0)
		out.append(
			{
				**r,
				"ok_pct": round(100.0 * int(r.pages_ok or 0) / toplam, 1) if toplam else None,
				"errors_open": frappe.db.count(
					"SEO Audit Finding",
					{"crawl_run": r.name, "severity": "error", "status": ["in", ["open", "reopened"]]},
				),
			}
		)
	return list(reversed(out))  # eskiden yeniye


@frappe.whitelist(methods=["GET"])
def crawl_pages(run=None, status: str = "", search: str = "", limit=100) -> dict:
	_require_admin()
	f: dict = {"crawl_run": _req(run, "run")}
	if status == "error":
		f["status_code"] = [">=", 400]
	elif status == "needs_js":
		f["needs_js"] = 1
	elif status == "ok":
		f["status_code"] = ["between", [200, 299]]
	if search:
		f["url"] = ["like", f"%{search}%"]
	rows = frappe.get_all(
		"SEO Crawl Page",
		filters=f,
		fields=[
			"name",
			"url",
			"route",
			"status_code",
			"response_ms",
			"bytes",
			"rendered_with",
			"needs_js",
			"robots_blocked",
			"title",
			"canonical",
			"robots_meta",
			"h1_count",
			"word_count",
			"internal_links",
			"images_without_alt",
			"error",
			"fetched_at",
		],
		order_by="fetched_at asc",
		limit_page_length=_lim(limit, 100),
	)
	return {"rows": rows, "total": frappe.db.count("SEO Crawl Page", f)}


# ── 13.2 Bot logu ─────────────────────────────────────────────────────────


@frappe.whitelist(methods=["POST"])
def botlog_import(text: str = "", host: str = "") -> dict:
	"""Elle yapıştırılan log metni (ya da panelden yüklenen dosya içeriği)."""
	_require_admin()
	from tradehub_core.seo_helper.crawler.botlog import import_text

	if not text or len(text) > 20_000_000:
		frappe.throw(_("Log metni boş ya da çok büyük (>20 MB)"), frappe.ValidationError)
	return import_text(text, host=host or frappe.local.site)


@frappe.whitelist(methods=["POST"])
def botlog_import_scheduled() -> dict:
	_require_admin()
	from tradehub_core.seo_helper.crawler.botlog import import_scheduled

	return import_scheduled()


@frappe.whitelist(methods=["GET"])
def botlog_coverage(days=7) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.crawler.botlog import coverage

	return coverage(
		max(1, min(_int(days, 7, "days"), 400)), wait=False
	)  # panel bloklanmaz; kısmiyse işaretli


@frappe.whitelist(methods=["GET"])
def botlog_visits(days=7, bot: str = "", blocked=0, limit=200) -> list:
	_require_admin()
	from frappe.utils import add_days, nowdate

	f: dict = {"day": [">=", add_days(nowdate(), -max(1, min(_int(days, 7, "days"), 400)))]}
	if bot:
		f["bot"] = bot
	if int(blocked or 0):
		f["blocked"] = 1
	return frappe.get_all(
		"SEO Bot Visit",
		filters=f,
		fields=["day", "bot", "path", "status_code", "hits", "blocked", "verified", "last_observed"],
		order_by="hits desc",
		limit_page_length=_lim(limit, 200),
	)


# ── 13.3 Pano ─────────────────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def board_overview() -> dict:
	_require_admin()
	from tradehub_core.seo_helper.board import overview

	return overview()


@frappe.whitelist(methods=["GET"])
def board_visibility(dimension: str = "all") -> list:
	_require_admin()
	from tradehub_core.seo_helper.board import visibility

	return visibility(dimension if dimension in ("all", "store", "lang", "page_type") else "all")


@frappe.whitelist(methods=["GET"])
def board_conversions(dimension: str = "all", days=30) -> list:
	_require_admin()
	from tradehub_core.seo_helper.board import conversions

	return conversions(
		dimension if dimension in ("all", "store", "lang", "page_type") else "all", _int(days, 30, "days")
	)


@frappe.whitelist(methods=["GET"])
def board_anomalies() -> list:
	_require_admin()
	from tradehub_core.seo_helper.board import anomalies

	return anomalies()


@frappe.whitelist(methods=["POST"])
def board_snapshot_now() -> dict:
	_require_admin()
	from tradehub_core.seo_helper.board import daily_job

	return daily_job()


# ── 13.4 Denetim raporlayıcı ──────────────────────────────────────────────


def _report_filters(crawl_run, category, status, store, days, limit, signal_source="") -> dict:
	return {
		"crawl_run": str(crawl_run or "")[:140] or None,
		"category": category
		if category in ("technical", "content", "catalog", "international", "merchant", "policy")
		else None,
		"status": str(status or "")[:30] or None,
		"store": str(store or "")[:140] or None,
		"days": max(1, min(_int(days, 30, "days"), 3650)),
		"limit": _int(limit, 500, "limit"),
		"signal_source": str(signal_source or "")[:20] or None,
	}


@frappe.whitelist(methods=["GET"])
def audit_report(
	crawl_run: str = "",
	category: str = "",
	status: str = "",
	store: str = "",
	days=30,
	limit=500,
	signal_source: str = "",
) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.audit.reporter import report

	return report(**_report_filters(crawl_run, category, status, store, days, limit, signal_source))


@frappe.whitelist(methods=["GET"])
def audit_export(
	fmt: str = "csv",
	crawl_run: str = "",
	category: str = "",
	status: str = "",
	store: str = "",
	days=30,
	limit=5000,
	signal_source: str = "",
):
	"""662 §3 — denetlenebilir dışa rapor (CSV/JSON indirme): yalnız gerçekten yazılmış bulgular."""
	_require_admin()
	from tradehub_core.seo_helper.audit.reporter import export

	fmt = "json" if str(fmt).lower() == "json" else "csv"
	ad, icerik = export(
		fmt, **_report_filters(crawl_run, category, status, store, days, limit, signal_source)
	)
	frappe.local.response.filename = ad
	frappe.local.response.filecontent = icerik
	frappe.local.response.type = "download"


@frappe.whitelist(methods=["POST"])
def audit_import_signals(kind: str = "all") -> dict:
	"""662 §2 — var olan 404 / medya / bot-log sinyallerini ayrı etiketle rapora al."""
	_require_admin()
	from tradehub_core.seo_helper.audit.signals import import_all

	if kind not in ("all", "notfound_log", "media", "log"):
		frappe.throw(_("kind: all | notfound_log | media | log"), frappe.ValidationError)
	return import_all(kind)


@frappe.whitelist(methods=["POST"])
def audit_mark_fixed(finding=None, recrawl=1) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.audit.reporter import mark_fixed

	ad = _req(finding, "finding")
	if not frappe.db.exists("SEO Audit Finding", ad):
		frappe.throw(_("Bulgu yok"), frappe.DoesNotExistError)
	return mark_fixed(ad, recrawl=bool(_int(recrawl, 1, "recrawl")))


@frappe.whitelist(methods=["POST"])
def audit_close(finding=None, note: str = "") -> dict:
	_require_admin()
	from tradehub_core.seo_helper.audit.reporter import close_finding

	ad = _req(finding, "finding")
	if not frappe.db.exists("SEO Audit Finding", ad):
		frappe.throw(_("Bulgu yok"), frappe.DoesNotExistError)
	return close_finding(ad, note=str(note or "")[:500])


@frappe.whitelist(methods=["POST"])
def audit_reopen(finding=None) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.audit.reporter import reopen_finding

	ad = _req(finding, "finding")
	if not frappe.db.exists("SEO Audit Finding", ad):
		frappe.throw(_("Bulgu yok"), frappe.DoesNotExistError)
	return reopen_finding(ad)


@frappe.whitelist(methods=["POST"])
def audit_rerun(crawl_run=None) -> dict:
	"""Mevcut tarama sonuçları üzerinde kuralları yeniden koştur (kural güncellemesi sonrası)."""
	_require_admin()
	from tradehub_core.seo_helper.audit.reporter import run_for_crawl

	ad = _req(crawl_run, "crawl_run")
	if not frappe.db.exists("SEO Crawl Run", ad):
		frappe.throw(_("Koşum yok"), frappe.DoesNotExistError)
	return {k: v for k, v in run_for_crawl(ad).items() if k != "fingerprints"}


# ── 13.5 Search Console ───────────────────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def gsc_status() -> dict:
	_require_admin()
	from tradehub_core.seo_helper.connectors.search_console import status

	return status()


@frappe.whitelist(methods=["GET"])
def gsc_auth_url(redirect_uri: str = "") -> dict:
	_require_admin()
	from tradehub_core.seo_helper.connectors.search_console import auth_url

	s = frappe.get_cached_doc("SEO Helper Settings")
	if not s.gsc_client_id:
		frappe.throw(_("Önce OAuth Client ID/Secret'ı Settings'e gir"), frappe.ValidationError)
	uri = redirect_uri or frappe.utils.get_url(
		"/api/method/tradehub_core.seo_helper.api.panel662.gsc_oauth_callback"
	)
	# CSRF kalkanı: state bu yöneticinin oturumuna bağlı, 10 dk geçerli; callback doğrular (saldırganın kendi
	# Google hesabını kurbanın sitesine bağlatması engellenir)
	state = frappe.generate_hash(length=24)
	frappe.cache().set_value(f"shc:gsc:state:{frappe.session.user}", state, expires_in_sec=600)
	return {"url": auth_url(s.gsc_client_id, uri, state=state), "redirect_uri": uri}


@frappe.whitelist(methods=["POST"])
def gsc_exchange_code(code=None, redirect_uri: str = "") -> dict:
	"""OAuth kodunu refresh token'a çevir ve Settings'e (Password) yaz. Token yanıtı loglanmaz."""
	_require_admin()
	import requests

	from tradehub_core.seo_helper.connectors.search_console import SearchConsoleClient

	code = _req(code, "code")
	s = frappe.get_doc("SEO Helper Settings")
	if not s.gsc_client_id:
		frappe.throw(_("Önce OAuth Client ID/Secret'ı Settings'e gir"), frappe.ValidationError)
	uri = redirect_uri or frappe.utils.get_url(
		"/api/method/tradehub_core.seo_helper.api.panel662.gsc_oauth_callback"
	)
	d = SearchConsoleClient.exchange_code(
		requests,
		client_id=s.gsc_client_id,
		client_secret=s.get_password("gsc_client_secret"),
		code=code,
		redirect_uri=uri,
	)
	s.gsc_refresh_token = d["refresh_token"]
	s.flags.ignore_permissions = True
	s.save()
	return {"connected": True}


@frappe.whitelist(allow_guest=False, methods=["GET"])
def gsc_oauth_callback(code: str = "", state: str = "", error: str = ""):
	"""Google geri dönüşü (oturum açık yönetici). Kodu takas eder, panele döner."""
	_require_admin()
	beklenen = frappe.cache().get_value(f"shc:gsc:state:{frappe.session.user}", expires=True)
	# panel ayrı origin'de olabilir (dev: 8082); site_config `admin_panel_url` varsa oraya, yoksa göreli yol
	panel = (frappe.conf.get("admin_panel_url") or "").rstrip("/")
	if error or not code or not state or not beklenen or state != beklenen:
		frappe.local.response["type"] = "redirect"
		frappe.local.response["location"] = f"{panel}/seo/helper?gsc=error"
		return
	frappe.cache().delete_value(f"shc:gsc:state:{frappe.session.user}")  # tek kullanımlık
	gsc_exchange_code(code)
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = f"{panel}/seo/helper?gsc=connected"


@frappe.whitelist(methods=["POST"])
def gsc_sync_now(days=14, inspect=0) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.connectors.search_console import (
		NotConfigured,
		status,
		sync_search_analytics,
		sync_url_inspection,
	)

	if not status()["configured"]:
		frappe.throw(
			_("Search Console yapılandırılmadı (client id/secret, refresh token, property)"),
			frappe.ValidationError,
		)
	try:
		out = {"analytics": sync_search_analytics(_int(days, 14, "days"))}
	except NotConfigured as e:
		frappe.throw(str(e), frappe.ValidationError)
	if _int(inspect, 0, "inspect"):
		out["inspection"] = sync_url_inspection()
	return out


@frappe.whitelist(methods=["POST"])
def gsc_submit_sitemap(feedpath: str = "") -> dict:
	_require_admin()
	from tradehub_core.seo_helper.connectors.search_console import (
		NotConfigured,
		SearchConsoleError,
		settings_client,
	)

	try:
		return settings_client().submit_sitemap(feedpath or frappe.utils.get_url("/sitemap.xml"))
	except NotConfigured as e:
		frappe.throw(str(e), frappe.ValidationError)
	except SearchConsoleError as e:  # Google hatası (kota/yetki) 500 değil, okunur mesaj
		frappe.throw(_("Search Console: {0}").format(str(e)[:300]), frappe.ValidationError)


# ── 13.6 Deneyler / değişiklik kaydı ─────────────────────────────────────


@frappe.whitelist(methods=["GET"])
def changelog(days=30, change_type: str = "", route: str = "", limit=200) -> list:
	_require_admin()
	from tradehub_core.seo_helper.experiments.changelog import recent

	return recent(
		max(1, min(_int(days, 30, "days"), 3650)),
		change_type=str(change_type or "")[:30] or None,
		route=str(route or "")[:300] or None,
		limit=_int(limit, 200, "limit"),
	)


@frappe.whitelist(methods=["POST"])
def changelog_add(
	change_type=None,
	description=None,
	scope_type: str = "site",
	scope_key: str = "",
	route: str = "",
	expected_effect: str = "",
) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.experiments.changelog import log_change

	description = _req(description, "description")
	change_type = _req(change_type, "change_type")
	if scope_type not in ("site", "domain", "lang", "store", "page_type", "route"):
		scope_type = "site"
	return {
		"name": log_change(
			change_type=change_type,
			description=description,
			scope_type=scope_type,
			scope_key=str(scope_key or "")[:140],
			route=str(route or "")[:500],
			expected_effect=str(expected_effect or "")[:1000],
		)
	}


@frappe.whitelist(methods=["GET"])
def experiments_list() -> list:
	_require_admin()
	from tradehub_core.seo_helper.experiments.experiments import list_experiments

	return list_experiments()


@frappe.whitelist(methods=["POST"])
def experiment_create(
	experiment_key=None,
	title=None,
	treatment_routes=None,
	control_routes=None,
	start_date: str = "",
	end_date: str = "",
	metric: str = "organic_conversions",
	hypothesis: str = "",
	seasonality: str = "weekday",
) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.experiments.experiments import create

	experiment_key, title = _req(experiment_key, "experiment_key"), _req(title, "title")
	if not start_date or not end_date:
		frappe.throw(_("başlangıç ve bitiş tarihi zorunlu"), frappe.ValidationError)
	try:
		frappe.utils.getdate(start_date), frappe.utils.getdate(end_date)
	except Exception:  # noqa: BLE001 — tarih ayrıştırma hatası 417
		frappe.throw(_("tarih biçimi YYYY-MM-DD"), frappe.ValidationError)
	if seasonality not in ("none", "weekday", "yoy"):
		seasonality = "weekday"
	return {
		"name": create(
			experiment_key,
			title=str(title)[:140],
			treatment_routes=_list(treatment_routes),
			control_routes=_list(control_routes),
			start_date=start_date,
			end_date=end_date,
			metric=metric,
			hypothesis=hypothesis,
			seasonality=seasonality,
		)
	}


@frappe.whitelist(methods=["POST"])
def experiment_evaluate(experiment=None) -> dict:
	_require_admin()
	from tradehub_core.seo_helper.experiments.experiments import evaluate

	ad = _req(experiment, "experiment")
	if not frappe.db.exists("SEO Experiment", ad):
		frappe.throw(_("Deney yok"), frappe.DoesNotExistError)
	return evaluate(ad)


@frappe.whitelist(methods=["GET"])
def conversions_series(metric: str = "organic_conversions", days=30) -> list:
	_require_admin()
	from tradehub_core.seo_helper.board import series

	return [
		{"day": d.isoformat(), "value": v}
		for d, v in sorted(
			series(
				str(metric or "organic_conversions")[:80],
				source="analytics",
				days=max(1, min(_int(days, 30, "days"), 3650)),
			).items()
		)
	]


def _json(v):
	return json.dumps(v, ensure_ascii=False, default=str)
