"""Politika motoru — deterministik doğrulama (MOGEM-660 §11.4) + canonical/robots/yayın kararı.

Girdi: SEO Page (+ bağlı Policy/Profile/Domain). Çıktı: karar sözlüğü ve `SEO Audit Finding`
satırları. Motor saf `evaluate()` (Frappe'siz test edilebilir) + Frappe sarmalayıcı
`apply_for_page`. Ajan/MCP taslakları da aynı motordan geçer; geçmeyen taslak onaylanamaz.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PUBLISH_STATES = ("draft", "review", "approved", "scheduled", "published", "suspended", "archived")
INDEXABLE_STATES = {"published"}
ROBOTS_ALLOWED = {"index,follow", "noindex,follow", "noindex,nofollow", "index,nofollow"}


@dataclass
class Decision:
	canonical_url: str
	robots: str
	indexable: bool
	publishable: bool
	findings: list[dict] = field(default_factory=list)

	def as_dict(self) -> dict:
		return {
			"canonical_url": self.canonical_url,
			"robots": self.robots,
			"indexable": self.indexable,
			"publishable": self.publishable,
			"findings": self.findings,
		}


def _finding(code: str, severity: str, message: str) -> dict:
	return {"code": code, "severity": severity, "message": message}


def _s(v) -> str:
	"""Güvenilmeyen girdi (MCP gövdesi) → metin: None/koleksiyon boş, sayılar/bool metin, NUL temizlenir."""
	if v is None or isinstance(v, bool) or isinstance(v, list | dict | tuple | set):
		return "" if not isinstance(v, bool) else ("1" if v else "")
	return str(v).replace("\x00", "").strip()


def _i(v, default: int = 0) -> int:
	try:
		return int(float(v))
	except (TypeError, ValueError):
		return default


def _d(v) -> dict:
	return v if isinstance(v, dict) else {}


def evaluate(
	page: dict, policy: dict | None, *, site_url: str, env_prod: bool = True, length_check=None
) -> Decision:
	"""Saf karar. `page`: route, slug, lang, title, meta_description, publish_state, robots,
	canonical_url, builder_meta (Builder'ın kendi alanları), has_ugc_html. `policy`: default_robots,
	canonical_strategy, min_title_len, min_desc_len, index_requires_published, block_ugc_html."""
	policy = _d(policy)
	page = _d(page)
	findings: list[dict] = []
	state = _s(page.get("publish_state")) or "draft"
	if state not in PUBLISH_STATES:
		findings.append(_finding("STATE_INVALID", "error", f"Bilinmeyen yayın durumu: {state}"))
		state = "draft"

	# 1) Canonical — override > Builder canonical > kendi route'u (kanonik host'a sabit)
	strateji = _s(policy.get("canonical_strategy")) or "self"
	base = site_url.rstrip("/")
	route = "/" + _s(page.get("route")).lstrip("/")
	builder_meta = _d(page.get("builder_meta"))
	canonical = _s(page.get("canonical_url")) or _s(builder_meta.get("canonical_url"))
	if not canonical:
		canonical = (
			f"{base}{route}" if strateji == "self" else (_s(page.get("parent_canonical")) or f"{base}{route}")
		)
		if not canonical.startswith(base):
			canonical = f"{base}{route}"
	elif canonical.startswith("/"):
		canonical = f"{base}{canonical}"
	elif not canonical.startswith(base):
		findings.append(_finding("CANONICAL_HOST", "warning", "Canonical kanonik host'a sabitlendi"))
		from urllib.parse import urlsplit

		canonical = f"{base}{urlsplit(canonical).path}"

	# 2) Robots — durum/ortam/politika; açık noindex her zaman kazanır
	robots = (_s(page.get("robots")) or _s(policy.get("default_robots")) or "index,follow").replace(" ", "")
	if robots not in ROBOTS_ALLOWED:
		findings.append(_finding("ROBOTS_INVALID", "error", f"Geçersiz robots: {robots}"))
		robots = "noindex,follow"
	if _i(builder_meta.get("disable_indexing")) or _s(builder_meta.get("disable_indexing")).lower() == "true":
		robots = "noindex,follow"
	if not env_prod:
		robots = "noindex,nofollow"
	if _i(policy.get("index_requires_published", 1), 1) and state not in INDEXABLE_STATES:
		robots = "noindex,follow" if robots.startswith("index") else robots
	indexable = robots.startswith("index") and state in INDEXABLE_STATES and env_prod

	# 3) Deterministik içerik kuralları (11.4) — yayınlanabilirliği belirler
	title = _s(page.get("title"))
	desc = _s(page.get("meta_description"))
	min_t = _i(policy.get("min_title_len"))
	min_d = _i(policy.get("min_desc_len"))
	if not title:
		findings.append(_finding("TITLE_MISSING", "error", "Başlık boş"))
	elif min_t and len(title) < min_t:
		findings.append(_finding("TITLE_SHORT", "error", f"Başlık {min_t} karakterden kısa ({len(title)})"))
	if min_d and len(desc) < min_d:
		findings.append(
			_finding("DESC_SHORT", "error", f"Meta açıklama {min_d} karakterden kısa ({len(desc)})")
		)
	if length_check:
		for msg in length_check(title, desc) or []:
			findings.append(_finding("LENGTH_RULE", "warning", msg))
	if _i(policy.get("block_ugc_html")) and (
		page.get("has_ugc_html") is True or _i(page.get("has_ugc_html"))
	):
		findings.append(_finding("UGC_HTML", "error", "Denetlenmemiş HTML/UGC içerik yayına çıkamaz"))
	if not _s(page.get("slug")) and not _s(page.get("route")):
		findings.append(_finding("ROUTE_MISSING", "error", "Route/slug yok"))

	publishable = not any(f["severity"] == "error" for f in findings)
	return Decision(
		canonical_url=canonical,
		robots=robots,
		indexable=indexable,
		publishable=publishable,
		findings=findings,
	)


# ── Frappe sarmalayıcı ────────────────────────────────────────────────────


def apply_for_page(page_name: str) -> dict:
	import frappe

	from tradehub_core.seo_helper.adapters.tradehub import meta as meta_ad
	from tradehub_core.seo_helper.adapters.tradehub import robots as robots_ad

	if not frappe.db.exists("SEO Page", page_name):  # iş kuyruğa girdikten sonra silinmiş olabilir
		return {"page": page_name, "skipped": "missing", "publishable": False, "findings": []}
	page = frappe.get_doc("SEO Page", page_name)
	policy = frappe.get_doc("SEO Policy", page.policy).as_dict() if page.policy else _default_policy()
	builder_meta = {}
	if page.builder_page and frappe.db.exists("Builder Page", page.builder_page):
		builder_meta = (
			frappe.db.get_value(
				"Builder Page",
				page.builder_page,
				["canonical_url", "disable_indexing", "meta_description", "page_title", "published"],
				as_dict=True,
			)
			or {}
		)
	karar = evaluate(
		{
			"route": page.route,
			"slug": page.slug,
			"lang": page.lang,
			"title": page.title or builder_meta.get("page_title"),
			"meta_description": page.meta_description or builder_meta.get("meta_description"),
			"publish_state": page.publish_state,
			"robots": page.robots,
			"canonical_url": page.canonical_url,
			"builder_meta": builder_meta,
			"has_ugc_html": page.get("has_ugc_html"),
		},
		policy,
		site_url=meta_ad.site_url(),
		env_prod=robots_ad.indexing_allowed_for_env(),
		length_check=meta_ad.check_lengths,
	)
	page.db_set(
		{
			"effective_canonical": karar.canonical_url,
			"effective_robots": karar.robots,
			"indexable": 1 if karar.indexable else 0,
			"publishable": 1 if karar.publishable else 0,
			"last_evaluated_at": frappe.utils.now_datetime(),
		},
		update_modified=False,
	)
	_write_findings(page, karar.findings)
	_sync_builder_canonical(page, karar.canonical_url)
	# cache: effective_* değişti → sürüm damgası + head/HTML cache (14.5 aynı veri sürümü)
	from tradehub_core.seo_helper.core import cache as cache_

	cache_.bump_version("SEO Page", page.name)
	cache_.invalidate_page(
		route=page.route,
		domain=page.domain or "*",
		lang=page.lang,
		store=page.store or "*",
		cluster=page.locale_cluster,
	)
	return karar.as_dict()


def _sync_builder_canonical(page, canonical: str) -> None:
	"""Tek üretici (4.3): Frappe, `update_website_context` kancalarından SONRA Builder'ın
	`set_missing_values` → `set_canonical_url`'ünü koşturur ve `context.canonical_url`'ü Builder Page'in
	kendi `canonical_url` alanından yeniden yazar. Bu yüzden politika sonucu o alana yazılır; alan çıktı
	yuvasıdır, girdi `seo_canonical` Custom Field'ıdır (cms.bridge). Çekirdeğe patch yok."""
	import frappe

	if not page.builder_page or not canonical:
		return
	mevcut = frappe.db.get_value("Builder Page", page.builder_page, "canonical_url")
	if mevcut != canonical:
		frappe.db.set_value(
			"Builder Page", page.builder_page, "canonical_url", canonical, update_modified=False
		)
		frappe.clear_document_cache("Builder Page", page.builder_page)


def apply_for_page_job(page: str, **_):
	"""Commit sonrası yayılım/uzlaşma işi. on_update zaten senkron değerlendirdiyse (last_evaluated_at ≥
	Builder Page.modified) yeniden yazmaz — işçi ile Builder kaydı arasında kilit çekişmesi/deadlock
	(monkey bulgusu) olmaz; yalnız olay kaybında/eski aynada değerlendirir."""
	import frappe

	row = frappe.db.get_value("SEO Page", page, ["last_evaluated_at", "builder_page"], as_dict=True)
	if not row:
		return {"page": page, "skipped": "missing"}
	if row.builder_page and row.last_evaluated_at:
		bp_mod = frappe.db.get_value("Builder Page", row.builder_page, "modified")
		if bp_mod and row.last_evaluated_at >= bp_mod:
			return {"page": page, "skipped": "fresh"}
	return apply_for_page(page)


def _default_policy() -> dict:
	import frappe

	if frappe.db.exists("SEO Policy", "default"):  # kurulumda oluşturulur (setup.install._defaults)
		return frappe.get_cached_doc("SEO Policy", "default").as_dict()
	s = frappe.get_cached_doc("SEO Helper Settings")
	return {
		"default_robots": s.default_robots or "index,follow",
		"canonical_strategy": "self",
		"min_title_len": s.min_title_len or 0,
		"min_desc_len": s.min_desc_len or 0,
		"index_requires_published": 1,
		"block_ugc_html": 1,
	}


def _write_findings(page, findings: list[dict]) -> None:
	import frappe

	frappe.db.delete("SEO Audit Finding", {"page": page.name, "crawl_run": ["is", "not set"]})
	for f in findings:
		frappe.get_doc(
			{
				"doctype": "SEO Audit Finding",
				"page": page.name,
				"route": page.route,
				"store": page.store,
				"severity": f["severity"],
				"code": f["code"],
				"message": f["message"],
				"signal_source": "policy",
			}
		).insert(ignore_permissions=True)
