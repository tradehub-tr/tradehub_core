"""13.5 Search Console bağlayıcısı — property, OAuth2, Search Analytics, sitemap, URL Inspection;
kota, örnekleme ve eksik veri yönetimi.

Saf istemci (`SearchConsoleClient`) `http` nesnesi enjekte alır (requests benzeri: post/get/…);
Frappe tarafı (`settings_client`, `sync_*`) ayarları ve kota defterini bağlar. Google kimlik
bilgileri yalnız `SEO Helper Settings` (Password alanları) — koda/loga yazılmaz.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import date, timedelta
from urllib.parse import quote, urlencode

OAUTH_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
OAUTH_TOKEN = "https://oauth2.googleapis.com/token"
SCOPES = "https://www.googleapis.com/auth/webmasters"
API = "https://www.googleapis.com/webmasters/v3"
INSPECT_API = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
ROW_LIMIT = 25000
RETRY_STATUS = {429, 500, 502, 503, 504}


class SearchConsoleError(RuntimeError):
	pass


class QuotaExceeded(SearchConsoleError):
	pass


class NotConfigured(SearchConsoleError):
	pass


def auth_url(client_id: str, redirect_uri: str, state: str = "") -> str:
	q = {
		"client_id": client_id,
		"redirect_uri": redirect_uri,
		"response_type": "code",
		"scope": SCOPES,
		"access_type": "offline",
		"prompt": "consent",
	}
	if state:
		q["state"] = state
	return f"{OAUTH_AUTH}?{urlencode(q)}"


def data_days(start: date, end: date, *, lag_days: int, today: date) -> tuple[date, date, list[date]]:
	"""GSC verisi ~lag gün gecikmeli gelir: [start, end] aralığını olası son güne kırp; kırpılan
	günler 'henüz yok' listesine düşer (0 sayılmaz)."""
	son_mumkun = today - timedelta(days=int(lag_days))
	kirpilan = []
	d = max(start, son_mumkun + timedelta(days=1)) if end > son_mumkun else None
	if d is not None:
		while d <= end:
			kirpilan.append(d)
			d += timedelta(days=1)
	bitis = min(end, son_mumkun)
	if bitis < start:  # tüm pencere gecikme içinde: veri yok, aralık tersine dönmesin
		return start, start - timedelta(days=1), kirpilan
	return start, bitis, kirpilan


def sample_urls(candidates: list[dict], n: int, *, seed: str = "") -> list[str]:
	"""URL Inspection kotası için örneklem: öncelik = yayında+indekslenebilir, sonra en son değişen;
	eşitlikte tohumlu karıştırma (deterministik)."""

	def anahtar(c):
		oncelik = 0 if (c.get("published") and c.get("indexable")) else 1
		degisim = -(c.get("changed_ts") or 0)
		h = hashlib.sha256(f"{seed}|{c.get('url')}".encode()).hexdigest()
		return (oncelik, degisim, h)

	return [c["url"] for c in sorted(candidates, key=anahtar)[: max(0, int(n))] if c.get("url")]


class SearchConsoleClient:
	def __init__(
		self,
		http,
		*,
		client_id: str,
		client_secret: str,
		refresh_token: str,
		property_url: str,
		timeout: float = 30.0,
		sleep=time.sleep,
		retries: int = 2,
	):
		if not (client_id and client_secret and refresh_token and property_url):
			raise NotConfigured("Search Console ayarları eksik (client id/secret, refresh token, property)")
		self.http, self.timeout, self.sleep, self.retries = http, timeout, sleep, retries
		self.client_id, self.client_secret, self.refresh_token = client_id, client_secret, refresh_token
		self.property = property_url
		self._token: str | None = None
		self._token_exp: float = 0.0
		self.calls = 0

	# ── OAuth
	@classmethod
	def exchange_code(
		cls, http, *, client_id: str, client_secret: str, code: str, redirect_uri: str, timeout: float = 30.0
	) -> dict:
		r = http.post(
			OAUTH_TOKEN,
			data={
				"client_id": client_id,
				"client_secret": client_secret,
				"code": code,
				"grant_type": "authorization_code",
				"redirect_uri": redirect_uri,
			},
			timeout=timeout,
		)
		if r.status_code != 200:
			raise SearchConsoleError(f"kod takası {r.status_code}: {_safe(r)}")
		d = r.json()
		if not d.get("refresh_token"):
			raise SearchConsoleError("refresh_token dönmedi (prompt=consent gerekli)")
		return d

	def access_token(self) -> str:
		if self._token and time.time() < self._token_exp - 60:
			return self._token
		r = self.http.post(
			OAUTH_TOKEN,
			data={
				"client_id": self.client_id,
				"client_secret": self.client_secret,
				"refresh_token": self.refresh_token,
				"grant_type": "refresh_token",
			},
			timeout=self.timeout,
		)
		if r.status_code != 200:
			raise SearchConsoleError(f"token yenileme {r.status_code}: {_safe(r)}")
		d = r.json()
		self._token = d["access_token"]
		self._token_exp = time.time() + float(d.get("expires_in") or 3600)
		return self._token

	def _call(self, method: str, url: str, *, json_body=None, params=None):
		for deneme in range(self.retries + 1):
			hdr = {"Authorization": f"Bearer {self.access_token()}", "Accept": "application/json"}
			self.calls += 1
			r = getattr(self.http, method)(
				url, json=json_body, params=params, headers=hdr, timeout=self.timeout
			)
			if r.status_code == 429:
				if deneme < self.retries:
					self.sleep(2**deneme)
					continue
				raise QuotaExceeded(f"Google 429: {_safe(r)}")
			if r.status_code in RETRY_STATUS and deneme < self.retries:
				self.sleep(2**deneme)
				continue
			if r.status_code == 401 and deneme == 0:
				self._token = None  # token süresi dolmuş olabilir → bir kez yenile
				continue
			if r.status_code >= 400:
				raise SearchConsoleError(f"{method.upper()} {url} → {r.status_code}: {_safe(r)}")
			return r.json() if r.text else {}
		raise SearchConsoleError("tekrar denemeler tükendi")

	# ── Search Analytics
	def search_analytics(
		self,
		start: date,
		end: date,
		*,
		dimensions=("page",),
		row_limit: int = ROW_LIMIT,
		filters=None,
		max_pages: int = 20,
	) -> list[dict]:
		url = f"{API}/sites/{quote(self.property, safe='')}/searchAnalytics/query"
		rows, start_row = [], 0
		for _ in range(max_pages):
			body = {
				"startDate": start.isoformat(),
				"endDate": end.isoformat(),
				"dimensions": list(dimensions),
				"rowLimit": row_limit,
				"startRow": start_row,
				"dataState": "final",
			}
			if filters:
				body["dimensionFilterGroups"] = [{"filters": filters}]
			d = self._call("post", url, json_body=body)
			parca = d.get("rows") or []
			for r in parca:
				keys = r.get("keys") or []
				rows.append(
					{
						**{dim: keys[i] if i < len(keys) else None for i, dim in enumerate(dimensions)},
						"clicks": r.get("clicks", 0),
						"impressions": r.get("impressions", 0),
						"ctr": r.get("ctr", 0.0),
						"position": r.get("position", 0.0),
					}
				)
			if len(parca) < row_limit:
				break
			start_row += row_limit
		return rows

	# ── Sitemaps
	def sitemaps(self) -> list[dict]:
		d = self._call("get", f"{API}/sites/{quote(self.property, safe='')}/sitemaps")
		return d.get("sitemap") or []

	def submit_sitemap(self, feedpath: str) -> dict:
		self._call("put", f"{API}/sites/{quote(self.property, safe='')}/sitemaps/{quote(feedpath, safe='')}")
		return {"submitted": feedpath}

	# ── URL Inspection
	def inspect(self, url: str, language: str = "tr") -> dict:
		d = self._call(
			"post",
			INSPECT_API,
			json_body={"inspectionUrl": url, "siteUrl": self.property, "languageCode": language},
		)
		r = (d.get("inspectionResult") or {}).get("indexStatusResult") or {}
		return {
			"url": url,
			"verdict": r.get("verdict"),
			"coverage_state": r.get("coverageState"),
			"indexing_state": r.get("indexingState"),
			"robots_txt_state": r.get("robotsTxtState"),
			"last_crawl_time": r.get("lastCrawlTime"),
			"google_canonical": r.get("googleCanonical"),
			"user_canonical": r.get("userCanonical"),
			"crawled_as": r.get("crawledAs"),
			"raw": d,
		}


def _safe(r) -> str:
	try:
		return json.dumps(r.json())[:300]
	except Exception:  # noqa: BLE001
		return (getattr(r, "text", "") or "")[:300]


# ── Frappe tarafı ─────────────────────────────────────────────────────────


def settings_client(http=None):
	import frappe

	s = frappe.get_cached_doc("SEO Helper Settings")
	secret = s.get_password("gsc_client_secret", raise_exception=False) if s.gsc_client_id else ""
	rt = s.get_password("gsc_refresh_token", raise_exception=False) if s.gsc_client_id else ""
	if http is None:
		import requests

		http = requests
	return SearchConsoleClient(
		http,
		client_id=s.gsc_client_id or "",
		client_secret=secret or "",
		refresh_token=rt or "",
		property_url=s.gsc_property or "",
	)


def status() -> dict:
	import frappe

	s = frappe.get_cached_doc("SEO Helper Settings")
	return {
		"configured": bool(
			s.gsc_client_id and s.gsc_property and s.get_password("gsc_refresh_token", raise_exception=False)
		),
		"property": s.gsc_property,
		"has_client": bool(s.gsc_client_id),
		"has_refresh_token": bool(s.get_password("gsc_refresh_token", raise_exception=False))
		if s.gsc_client_id
		else False,
		"last_sync_at": s.gsc_last_sync_at,
		"lag_days": s.gsc_data_lag_days or 3,
		"quota": {
			"inspection": quota_used("search_console", "url_inspection"),
			"query": quota_used("search_console", "search_analytics"),
		},
	}


def quota_used(connector: str, metric: str, day: date | None = None) -> dict:
	import frappe
	from frappe.utils import nowdate

	gun = (day or nowdate()) if isinstance(day, str) or day is None else day.isoformat()
	row = frappe.db.get_value(
		"SEO Connector Quota",
		{"dedupe_key": f"{gun}|{connector}|{metric}"},
		["used", "limit_value"],
		as_dict=True,
	)
	return {
		"used": int(row.used) if row else 0,
		"limit": int(row.limit_value) if row and row.limit_value else None,
	}


def quota_consume(connector: str, metric: str, n: int, limit: int) -> int:
	"""Günlük sayaç; sınır aşılırsa QuotaExceeded (aşmadan önce reddeder)."""
	import frappe
	from frappe.utils import nowdate

	gun = nowdate()
	key = f"{gun}|{connector}|{metric}"
	name = frappe.db.get_value("SEO Connector Quota", {"dedupe_key": key}, "name")
	if not name:
		name = (
			frappe.get_doc(
				{
					"doctype": "SEO Connector Quota",
					"day": gun,
					"connector": connector,
					"metric": metric,
					"used": 0,
					"limit_value": limit,
					"dedupe_key": key,
				}
			)
			.insert(ignore_permissions=True)
			.name
		)
	used = int(frappe.db.get_value("SEO Connector Quota", name, "used") or 0)
	if limit and used + n > limit:
		raise QuotaExceeded(f"{connector}.{metric} günlük kota {limit} dolu ({used}+{n})")
	frappe.db.sql(
		"update `tabSEO Connector Quota` set used = used + %s, limit_value=%s where name=%s", (n, limit, name)
	)
	return used + n


def sync_search_analytics(days: int = 14, *, client=None) -> dict:
	"""Son N günün sayfa bazlı tıklama/gösterimini `SEO Metric Snapshot`'a yaz (eksik günler `missing`)."""
	import frappe
	from frappe.utils import getdate, now_datetime, nowdate

	from tradehub_core.seo_helper.board import write_snapshot

	s = frappe.get_cached_doc("SEO Helper Settings")
	client = client or settings_client()
	bugun = getdate(nowdate())
	start, end, gec = data_days(
		bugun - timedelta(days=int(days)), bugun, lag_days=int(s.gsc_data_lag_days or 3), today=bugun
	)
	rows = []
	if end >= start:  # penceresi olmayan çağrı kota yakmaz
		quota_consume("search_console", "search_analytics", 1, int(s.gsc_daily_query_quota or 2000))
		rows = client.search_analytics(start, end, dimensions=("date", "page"))
	gunluk: dict[str, dict[str, float]] = {}
	for r in rows:
		g = gunluk.setdefault(r["date"], {"clicks": 0.0, "impressions": 0.0, "pages": 0.0})
		g["clicks"] += float(r["clicks"] or 0)
		g["impressions"] += float(r["impressions"] or 0)
		g["pages"] += 1
	yazilan = 0
	d = start
	while d <= end:
		g = gunluk.get(d.isoformat())
		for metric in ("clicks", "impressions", "pages"):
			write_snapshot(
				d,
				"search_console",
				"all",
				"all",
				f"gsc_{metric}",
				(g or {}).get(metric, 0.0),
				missing=g is None,
			)
			yazilan += 1
		d += timedelta(days=1)
	for d in gec:
		for metric in ("clicks", "impressions", "pages"):
			write_snapshot(d, "search_console", "all", "all", f"gsc_{metric}", 0.0, missing=True)
	from tradehub_core.seo_helper.crawler.botlog import page_type_of

	turler: dict[tuple[str, str], dict[str, float]] = {}
	for r in rows:
		from urllib.parse import urlsplit

		t = page_type_of(urlsplit(r["page"] or "").path)
		g = turler.setdefault((r["date"], t), {"clicks": 0.0, "impressions": 0.0})
		g["clicks"] += float(r["clicks"] or 0)
		g["impressions"] += float(r["impressions"] or 0)
	for (gun, t), g in turler.items():
		write_snapshot(getdate(gun), "search_console", "page_type", t, "gsc_clicks", g["clicks"])
		write_snapshot(getdate(gun), "search_console", "page_type", t, "gsc_impressions", g["impressions"])
	frappe.db.set_value("SEO Helper Settings", None, "gsc_last_sync_at", now_datetime())
	return {
		"rows": len(rows),
		"days": (end - start).days + 1,
		"missing_days": [x.isoformat() for x in gec],
		"snapshots": yazilan,
	}


def sync_url_inspection(*, client=None, limit: int | None = None) -> dict:
	"""Örneklemli URL Inspection: kota defterinden düşer, sonuçları `SEO Page`'e (gsc_*) değil,
	`SEO Metric Snapshot`'a ve bulgu olarak yazar (indekslenmemiş yayında sayfa → GSC_NOT_INDEXED)."""
	import frappe
	from frappe.utils import getdate, nowdate

	from tradehub_core.seo_helper.audit.reporter import upsert_findings
	from tradehub_core.seo_helper.board import write_snapshot

	s = frappe.get_cached_doc("SEO Helper Settings")
	client = client or settings_client()
	n = int(limit or s.gsc_sample_size or 200)
	adaylar = [
		{
			"url": (p.effective_canonical or ""),
			"published": p.publish_state == "published",
			"indexable": bool(p.indexable),
			"changed_ts": (p.modified.timestamp() if p.modified else 0),
		}
		for p in frappe.get_all(
			"SEO Page",
			fields=["effective_canonical", "publish_state", "indexable", "modified"],
			limit_page_length=50000,
		)
		if p.effective_canonical
	]
	secim = sample_urls(adaylar, n, seed=nowdate())
	quota_consume("search_console", "url_inspection", len(secim), int(s.gsc_daily_inspection_quota or 2000))
	indeksli = 0
	bulgular = []
	for u in secim:
		r = client.inspect(u)
		if (r.get("verdict") or "").upper() == "PASS":
			indeksli += 1
		elif r.get("coverage_state"):
			bulgular.append(
				{
					"code": "GSC_NOT_INDEXED",
					"category": "technical",
					"severity": "warning",
					"message": f"Google: {r.get('coverage_state')}",
					"url": u,
					"evidence": {
						"_key": "gsc",
						"verdict": r.get("verdict"),
						"coverage_state": r.get("coverage_state"),
						"google_canonical": r.get("google_canonical"),
					},
					"root_cause": "Google sayfayı indekslememiş (kapsama durumu)",
					"owner_role": "SEO Manager",
					"recommendation": "Kapsama durumuna göre canonical/robots/içerik düzelt",
					"fingerprint": "",
				}
			)
	from tradehub_core.seo_helper.audit.rules import fingerprint

	for b in bulgular:
		b["fingerprint"] = fingerprint(b)
	if bulgular:
		upsert_findings(bulgular, crawl_run=None, signal_source="gsc")
	write_snapshot(getdate(nowdate()), "search_console", "all", "all", "gsc_sampled", float(len(secim)))
	write_snapshot(
		getdate(nowdate()),
		"search_console",
		"all",
		"all",
		"gsc_indexed_ratio",
		(indeksli / len(secim)) if secim else 0.0,
		missing=not secim,
	)
	return {"sampled": len(secim), "indexed": indeksli, "findings": len(bulgular)}


def scheduled_sync() -> dict | None:
	"""Günlük: yapılandırılmışsa Search Analytics (+ örneklemli URL Inspection) senkronu — kuyrukta."""
	import frappe

	if not status()["configured"]:
		return None
	from tradehub_core.seo_helper.core.queue import enqueue_after_commit

	job = enqueue_after_commit(
		"gsc.sync", {"days": 14, "inspect": 1}, queue="long", dedupe_key="gsc.sync:daily"
	)
	frappe.db.commit()
	return {"job": job}


def sync_job(days: int = 14, inspect: int = 0, **_) -> dict:
	out = {"analytics": sync_search_analytics(int(days))}
	if int(inspect or 0):
		out["inspection"] = sync_url_inspection()
	return out
