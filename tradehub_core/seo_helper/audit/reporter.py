"""13.4 Audit Reporter — Frappe tarafı: olguları topla, kuralları koştur, bulguları tekilleştirerek yaz,
yaşam döngüsü (open → fixed → recrawl_pending → closed / reopened), rapor.

Tekilleştirme: `fingerprint` (kategori+kod+url+kanıt anahtarı). Aynı iz açık/yeniden açılmış/yeniden
tarama bekleyen bir bulguyla eşleşirse `occurrences += 1`, `last_observed` güncellenir; kapalı bulguyla
eşleşirse **yeniden açılır** (reopened). Yeniden tarama (targeted crawl) bittiğinde `recrawl_pending`
bulgular: iz tekrar üretilmediyse `closed`, üretildiyse `reopened`.
"""

from __future__ import annotations

import json
from urllib.parse import urlsplit

import frappe
from frappe import _
from frappe.utils import add_to_date, now_datetime

from tradehub_core.seo_helper.audit import rules

ACTIVE_STATUSES = ("open", "reopened", "recrawl_pending", "fixed")


def _active_key(status: str, fingerprint: str) -> str | None:
	"""Aktif bulgu için parmak izi (DB'de UNIQUE) — aynı iz için ikinci aktif kayıt, iki koşum aynı anda
	yazsa bile (ayrı süreç/işlem) DB düzeyinde engellenir; kapalıyken NULL (çok kayıt serbest)."""
	return fingerprint if status in ACTIVE_STATUSES and fingerprint else None


def _site() -> str:
	from tradehub_core.seo_helper.adapters.tradehub.meta import site_url

	return site_url().rstrip("/")


def _page_by_route(route: str, lang: str | None = None):
	route = "/" + (route or "").strip("/")
	f = {"route": route}
	if lang:
		f["lang"] = lang
	return frappe.db.get_value(
		"SEO Page",
		f,
		[
			"name",
			"route",
			"lang",
			"store",
			"title",
			"effective_canonical",
			"effective_robots",
			"indexable",
			"publish_state",
			"locale_cluster",
			"entity",
		],
		as_dict=True,
	)


def _cluster_facts(page) -> dict | None:
	if not page or not page.locale_cluster:
		return None
	members = frappe.get_all(
		"SEO Page",
		filters={"locale_cluster": page.locale_cluster, "publish_state": "published"},
		fields=["lang", "route", "effective_canonical"],
	)
	return {
		"key": page.locale_cluster,
		"members": [{"lang": m.lang, "route": m.route, "url": m.effective_canonical} for m in members],
	}


def _reciprocal_missing(page, cluster: dict | None, crawl_by_url: dict) -> list[str]:
	"""Karşı sayfa (aynı koşumda tarandıysa) bu sayfaya hreflang veriyor mu?"""
	if not cluster or not page:
		return []
	eksik = []
	for m in cluster["members"]:
		if m["lang"] == page.lang or not m.get("url"):
			continue
		karsi = crawl_by_url.get(m["url"]) or crawl_by_url.get(m.get("route") or "")
		if not karsi:
			continue
		ham = karsi.get("hreflang") or []
		if isinstance(
			ham, str
		):  # SEO Crawl Page satırı: JSON metni (ayrıştırma yalnız kendi sayfası için yapılır)
			try:
				ham = json.loads(ham or "[]")
			except ValueError:
				ham = []
		hl = {(h.get("lang") or "").lower() for h in ham if isinstance(h, dict)}
		if page.lang and page.lang.lower() not in hl and not karsi.get("needs_js"):
			eksik.append(m["lang"])
	return eksik


def _entity_facts(page, route: str) -> dict | None:
	ent = None
	if page and page.entity:
		ent = frappe.db.get_value(
			"SEO Entity",
			page.entity,
			["name", "entity_type", "store", "indexable", "canonical_path", "ref_doctype", "ref_name"],
			as_dict=True,
		)
	elif route:
		ent = frappe.db.get_value(
			"SEO Entity",
			{"canonical_path": route},
			["name", "entity_type", "store", "indexable", "canonical_path", "ref_doctype", "ref_name"],
			as_dict=True,
		)
	if not ent:
		return None
	d = dict(ent)
	d["title"] = page.title if page else ""
	if (
		ent.entity_type == "listing"
		and ent.ref_doctype == "Listing"
		and ent.ref_name
		and frappe.db.exists("Listing", ent.ref_name)
	):
		row = (
			frappe.db.get_value(
				"Listing", ent.ref_name, ["slug", "stock_quantity", "meta_title"], as_dict=True
			)
			or {}
		)
		d["title"] = row.get("meta_title") or d["title"]
		if row.get("slug"):
			dup = frappe.get_all(
				"Listing",
				filters={"slug": row["slug"], "name": ["!=", ent.ref_name]},
				pluck="name",
				limit_page_length=10,
			)
			if dup:
				d["duplicate_slug"] = dup
		if row.get("stock_quantity") is not None and float(row.get("stock_quantity") or 0) <= 0:
			d["stock_status"] = "out"
	return d


def _merchant_facts(store: str | None) -> dict | None:
	if not store:
		return None
	m = frappe.db.get_value(
		"SEO Merchant Map", {"store": store}, ["status", "feed_url", "mapping", "last_sync_at"], as_dict=True
	)
	if not m:
		return {}
	try:
		mapping = json.loads(m.mapping) if isinstance(m.mapping, str) else (m.mapping or {})
	except ValueError:
		mapping = {}
	yas = None
	if m.last_sync_at:
		yas = (now_datetime() - m.last_sync_at).days
	return {"status": m.status, "feed_url": m.feed_url, "mapping": mapping, "last_sync_age_days": yas}


def facts_for_crawl_page(cp, crawl_by_url: dict, dup_titles: dict) -> dict:
	route = cp.route or urlsplit(cp.url).path or "/"
	page = _page_by_route(route)
	crawl = dict(cp)
	for k in ("redirect_chain", "hreflang", "json_ld_types"):
		try:
			crawl[k] = (
				json.loads(crawl.get(k) or "[]") if isinstance(crawl.get(k), str) else (crawl.get(k) or [])
			)
		except ValueError:
			crawl[k] = []
	cluster = _cluster_facts(page)
	return {
		"url": cp.url,
		"crawl": crawl,
		"page": dict(page) if page else None,
		"cluster": cluster,
		"reciprocal_missing": _reciprocal_missing(page, cluster, crawl_by_url),
		"entity": _entity_facts(page, route),
		"merchant": _merchant_facts((page or {}).get("store") if page else None),
		"duplicate_titles": [u for u in dup_titles.get((cp.title or "").strip(), []) if u != cp.url]
		if cp.title
		else [],
	}


SIGNAL_SOURCES = ("crawler", "log", "gsc", "media", "notfound_log", "policy", "mcp")


def upsert_findings(findings: list[dict], *, crawl_run: str | None, signal_source: str = "crawler") -> dict:
	"""Tekilleştirerek yaz. Döner: {new, updated, reopened, fingerprints}.
	`signal_source` (662 §2): bulgunun hangi sinyalden geldiği — bulgu sözlüğündeki `signal_source` öncelikli."""
	if signal_source not in SIGNAL_SOURCES:
		signal_source = "crawler"
	simdi = now_datetime()
	yeni = guncel = yeniden = 0
	izler = set()
	for f in findings:
		fp = f.get("fingerprint") or rules.fingerprint(f)
		izler.add(fp)
		mevcut = _mevcut_bulgu(fp)
		route = urlsplit(f.get("url") or "").path or (f.get("route") or "")
		page = (
			frappe.db.get_value("SEO Page", {"route": route}, ["name", "store"], as_dict=True)
			if route
			else None
		)
		if mevcut:
			tur = _guncelle(mevcut, f, fp, crawl_run, simdi)
			yeniden += tur == "reopened"
			guncel += tur == "updated"
			continue
		frappe.db.savepoint("shc_bulgu")
		try:
			_yeni_bulgu(f, fp, route, page, crawl_run, simdi, signal_source)
		except (
			frappe.DuplicateEntryError,
			frappe.UniqueValidationError,
		):  # Frappe: alan UNIQUE ihlali → UniqueValidationError
			# yarış: başka süreç aynı izi az önce yazdı (active_key UNIQUE) → kilitli okuma ile (REPEATABLE READ
			# anlık görüntüsünü aşarak) mevcut kaydı bul ve güncelle
			frappe.db.rollback(save_point="shc_bulgu")
			mevcut = _mevcut_bulgu(fp, for_update=True)
			if not mevcut:
				raise
			tur = _guncelle(mevcut, f, fp, crawl_run, simdi)
			yeniden += tur == "reopened"
			guncel += tur == "updated"
			continue
		yeni += 1
	return {"new": yeni, "updated": guncel, "reopened": yeniden, "fingerprints": izler}


def _mevcut_bulgu(fp: str, *, for_update: bool = False):
	return frappe.db.get_value(
		"SEO Audit Finding",
		{"fingerprint": fp, "status": ["in", list(ACTIVE_STATUSES) + ["closed"]]},
		["name", "status", "occurrences"],
		as_dict=True,
		order_by="creation desc",
		for_update=for_update,
	)


def _guncelle(mevcut, f: dict, fp: str, crawl_run: str | None, simdi) -> str:
	veri = {
		"occurrences": int(mevcut.occurrences or 0) + 1,
		"last_observed": simdi,
		"message": f["message"],
		"evidence": json.dumps(f.get("evidence") or {}, ensure_ascii=False, default=str),
	}
	if crawl_run:
		veri["crawl_run"] = crawl_run
	if mevcut.status == "closed":
		veri.update({"status": "reopened", "resolved": 0, "resolved_at": None, "closed_at": None})
		tur = "reopened"
	elif mevcut.status in ("fixed", "recrawl_pending"):
		veri.update({"status": "reopened"})  # düzeltildi denmiş ama iz hâlâ üretiliyor
		tur = "reopened"
	else:
		tur = "updated"
	veri["active_key"] = _active_key(veri.get("status") or mevcut.status, fp)
	frappe.db.set_value("SEO Audit Finding", mevcut.name, veri, update_modified=True)
	return tur


def _yeni_bulgu(
	f: dict, fp: str, route: str, page, crawl_run: str | None, simdi, signal_source: str = "crawler"
) -> None:
	frappe.get_doc(
		{
			"doctype": "SEO Audit Finding",
			"crawl_run": crawl_run,
			"page": page.name if page else None,
			"route": route,
			"url": (f.get("url") or "")[:1000],
			"store": (page.store if page else None) or f.get("store"),
			"severity": f["severity"],
			"code": f["code"],
			"message": f["message"],
			"category": f.get("category") or "technical",
			"evidence": json.dumps(f.get("evidence") or {}, ensure_ascii=False, default=str),
			"root_cause": f.get("root_cause") or "",
			"owner_role": f.get("owner_role") or "",
			"owner_store": (page.store if page else None) if (f.get("owner_role") == "Mağaza") else None,
			"recommendation": f.get("recommendation") or "",
			"fingerprint": fp,
			"signal_source": f.get("signal_source")
			if f.get("signal_source") in SIGNAL_SOURCES
			else signal_source,
			"active_key": _active_key("open", fp),
			"status": "open",
			"occurrences": 1,
			"first_observed": simdi,
			"last_observed": simdi,
		}
	).insert(ignore_permissions=True)


def run_for_crawl(crawl_run: str) -> dict:
	"""Koşumun tüm sayfaları için kuralları koştur; bulguları yaz; koşum sayaçlarını güncelle;
	yeniden tarama bekleyen bulguları uzlaştır."""
	s = frappe.get_cached_doc("SEO Helper Settings")
	pages = frappe.get_all(
		"SEO Crawl Page", filters={"crawl_run": crawl_run}, fields=["*"], limit_page_length=100000
	)
	by_url = {p.url: p for p in pages}
	# karşılık (hreflang) denetimi küme üyesini effective_canonical ile arar; hedefli taramada URL başka
	# hostta olabilir → route ile de eriş ("/..." anahtarları "http..." ile çakışmaz)
	by_url.update({p.route: p for p in pages if p.route and p.route not in by_url})
	dup: dict[str, list[str]] = {}
	for p in pages:
		if p.title and not (p.final_url and p.final_url.rstrip("/") != (p.url or "").rstrip("/")):
			dup.setdefault(p.title.strip(), []).append(p.url)  # yönlendirilen kaynaklar çift başlık sayılmaz
	tum = []
	for p in pages:
		f = facts_for_crawl_page(p, by_url, dup)
		if p.final_url and p.final_url.rstrip("/") != (p.url or "").rstrip("/"):
			# yönlendirilen kaynak URL: içerik hedef sayfanındır → yalnız teknik kurallar (çift başlık/h1 vb.
			# hedef sayfada zaten raporlanır; burada tekrar etmesi yanlış pozitif)
			tek = rules.technical(f)
			for x in tek:
				x["fingerprint"] = rules.fingerprint(x)
			tum.extend(tek)
			continue
		tum.extend(rules.run_all(f, min_title=int(s.min_title_len or 10), min_desc=int(s.min_desc_len or 50)))
	yaz = upsert_findings(tum, crawl_run=crawl_run)
	uzlas = reconcile_after_recrawl(crawl_run, yaz["fingerprints"], {p.url for p in pages})
	# sayaç = koşuma bağlı TÜM bulgular (site düzeyi robots.txt bulgusu gibi ayrıca yazılanlar dahil)
	frappe.db.set_value(
		"SEO Crawl Run",
		crawl_run,
		"findings",
		frappe.db.count("SEO Audit Finding", {"crawl_run": crawl_run}),
		update_modified=False,
	)
	return {
		"run": crawl_run,
		"pages": len(pages),
		"findings": len(tum),
		**{k: v for k, v in yaz.items() if k != "fingerprints"},
		**uzlas,
		"summary": rules.summarize(tum),
	}


def mark_fixed(finding: str, *, by: str | None = None, recrawl: bool = True) -> dict:
	"""İnsan 'düzelttim' der → fixed; yeniden tarama kuyruklanır → recrawl_pending."""
	d = frappe.get_doc("SEO Audit Finding", finding)
	if d.status in ("closed",):
		frappe.throw(_("Kapalı bulgu düzeltildi işaretlenemez"), frappe.ValidationError)
	veri = {"status": "fixed", "fixed_by": by or frappe.session.user, "fixed_at": now_datetime()}
	run = None
	if recrawl and d.url:
		from tradehub_core.seo_helper.crawler.manager import start_crawl

		run = start_crawl("targeted", routes=[d.url], triggered_by=f"recrawl:{finding}")
		veri.update(
			{"status": "recrawl_pending", "recrawl_run": run, "recrawl_count": int(d.recrawl_count or 0) + 1}
		)
	d.db_set(veri, update_modified=True)
	return {"finding": finding, "status": veri["status"], "recrawl_run": run}


def close_finding(finding: str, *, note: str = "") -> dict:
	d = frappe.get_doc("SEO Audit Finding", finding)
	d.db_set(
		{
			"status": "closed",
			"active_key": None,
			"resolved": 1,
			"resolved_at": now_datetime(),
			"closed_at": now_datetime(),
		},
		update_modified=True,
	)
	return {"finding": finding, "status": "closed", "note": note}


def reopen_finding(finding: str) -> dict:
	d = frappe.get_doc("SEO Audit Finding", finding)
	d.db_set(
		{
			"status": "reopened",
			"active_key": _active_key("reopened", d.fingerprint),
			"resolved": 0,
			"resolved_at": None,
			"closed_at": None,
			"last_observed": now_datetime(),
		},
		update_modified=True,
	)
	return {"finding": finding, "status": "reopened"}


def reconcile_after_recrawl(crawl_run: str, produced: set[str], crawled_urls: set[str]) -> dict:
	"""Bu koşumu bekleyen (recrawl_run == run) ya da taranan URL'lerdeki `recrawl_pending`/`fixed`
	bulgular: iz üretilmediyse kapat, üretildiyse yeniden aç."""
	kapanan = acilan = 0
	bekleyen = frappe.get_all(
		"SEO Audit Finding",
		filters={"status": ["in", ["recrawl_pending", "fixed"]]},
		fields=["name", "fingerprint", "url", "recrawl_run"],
		limit_page_length=10000,
	)
	for b in bekleyen:
		if b.recrawl_run != crawl_run and b.url not in crawled_urls:
			continue
		if b.fingerprint in produced:
			acilan += 1  # upsert zaten reopened yaptı; sayaç için
		else:
			frappe.db.set_value(
				"SEO Audit Finding",
				b.name,
				{
					"status": "closed",
					"active_key": None,
					"resolved": 1,
					"resolved_at": now_datetime(),
					"closed_at": now_datetime(),
					"recrawl_run": crawl_run,
				},
				update_modified=True,
			)
			kapanan += 1
	return {"closed_after_recrawl": kapanan, "reopened_after_recrawl": acilan}


def report(
	*,
	crawl_run: str | None = None,
	category: str | None = None,
	status: str | None = None,
	store: str | None = None,
	days: int = 30,
	limit: int = 500,
	signal_source: str | None = None,
) -> dict:
	f: dict = {}
	if crawl_run:
		f["crawl_run"] = crawl_run
	if signal_source in SIGNAL_SOURCES:
		f["signal_source"] = signal_source
	if category:
		f["category"] = category
	if status and status != "all":
		f["status"] = status
	elif not status:
		f["status"] = ["in", list(ACTIVE_STATUSES)]
	if store:
		f["store"] = store
	if days:
		f["last_observed"] = [">=", add_to_date(now_datetime(), days=-int(days))]
	rows = frappe.get_all(
		"SEO Audit Finding",
		filters=f,
		fields=[
			"name",
			"category",
			"code",
			"severity",
			"message",
			"url",
			"route",
			"store",
			"evidence",
			"root_cause",
			"owner_role",
			"owner_store",
			"recommendation",
			"status",
			"occurrences",
			"first_observed",
			"last_observed",
			"fixed_by",
			"recrawl_run",
			"recrawl_count",
			"crawl_run",
			"signal_source",
		],
		order_by="last_observed desc",
		limit_page_length=max(1, min(int(limit), 2000)),
	)
	sira = {"error": 0, "warning": 1, "info": 2}
	rows.sort(key=lambda r: sira.get(r.severity, 3))  # önem sırası; aynı önemde last_observed desc korunur
	for r in rows:
		try:
			r.evidence = (
				json.loads(r.evidence) if isinstance(r.evidence, str) and r.evidence else (r.evidence or {})
			)
		except ValueError:
			r.evidence = {"raw": r.evidence}
	ozet = rules.summarize(
		[
			{"category": r.category or "technical", "severity": r.severity, "owner_role": r.owner_role}
			for r in rows
		]
	)
	durum = {}
	kaynak = {}
	for r in rows:
		durum[r.status] = durum.get(r.status, 0) + 1
		kaynak[r.signal_source or "crawler"] = kaynak.get(r.signal_source or "crawler", 0) + 1
	return {"rows": rows, "summary": ozet, "by_status": durum, "by_source": kaynak, "total": len(rows)}


EXPORT_COLUMNS = (
	"name",
	"signal_source",
	"category",
	"code",
	"severity",
	"status",
	"url",
	"route",
	"store",
	"message",
	"first_observed",
	"last_observed",
	"occurrences",
	"crawl_run",
	"recrawl_run",
	"recrawl_count",
	"owner_role",
	"owner_store",
	"root_cause",
	"recommendation",
	"evidence",
)


def export(fmt: str = "csv", **filters) -> tuple[str, str]:
	"""Denetlenebilir dışa aktarma (662 §3): URL, zaman (ilk/son görülme), sinyal kaynağı, tekrar deneme izi
	(koşum, yeniden tarama koşumu ve sayısı) her satırda. Döner: (dosya adı, içerik)."""
	import csv
	import io

	rows = report(**filters)["rows"]
	damga = now_datetime().strftime("%Y%m%d-%H%M")
	if fmt == "json":
		return f"seo-denetim-{damga}.json", json.dumps(
			[{k: r.get(k) for k in EXPORT_COLUMNS} for r in rows], ensure_ascii=False, default=str, indent=1
		)
	buf = io.StringIO()
	w = csv.writer(buf, lineterminator="\n")
	w.writerow(EXPORT_COLUMNS)
	for r in rows:
		w.writerow(
			[
				json.dumps(r.get(k), ensure_ascii=False, default=str)
				if k == "evidence"
				else (r.get(k) if r.get(k) is not None else "")
				for k in EXPORT_COLUMNS
			]
		)
	return f"seo-denetim-{damga}.csv", "\ufeff" + buf.getvalue()  # BOM: Excel'de Türkçe karakter
