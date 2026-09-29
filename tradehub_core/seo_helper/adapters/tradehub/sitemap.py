"""Sitemap adaptörü — tradehub_core sitemap cache/dirty mekanizması sarılır."""

from __future__ import annotations

import frappe

ALL_URLS_CACHE = "shc:sitemap:all_urls"
ALL_URLS_TTL = 3600  # sn — tam üretim ~25 s (10k URL); panel/kapsam çağrıları önbellekten okur


def mark_dirty(doctype: str) -> None:
	"""tradehub'ın kirli bayrağı: bir sonraki yeniden üretimde bu tür yeniden kurulur."""
	from tradehub_core.seo.sitemap_cache import dirty_key_for

	frappe.cache().set_value(dirty_key_for(doctype), 1)
	frappe.cache().delete_value(ALL_URLS_CACHE)


def invalidate_all() -> None:
	from tradehub_core.seo.sitemap_cache import get_default_cache

	frappe.cache().delete_value(ALL_URLS_CACHE)
	cache = get_default_cache()
	if hasattr(cache, "invalidate_all"):
		cache.invalidate_all()
	else:  # eski sürüm: tür bazlı
		for dt in ("Listing", "Product Category", "Brand", "Admin Seller Profile", "Builder Page"):
			mark_dirty(dt)


def rebuild_all() -> dict:
	from tradehub_core.seo.tasks import rebuild_all_sitemaps

	return rebuild_all_sitemaps()


def urlentry(**kw) -> dict:
	from tradehub_core.seo.sitemap_generator import urlentry

	return urlentry(**kw)


def build_urlset_xml(urls, include_hreflang: bool = True) -> str:
	from tradehub_core.seo.sitemap_generator import build_urlset_xml

	return build_urlset_xml(urls, include_hreflang=include_hreflang)


def cached_urls() -> list[str] | None:
	"""Önbellekteki sitemap URL listesi; yoksa None (üretim tetiklenmez)."""
	# expires=True şart: TTL'li anahtarda ıska yerel cache'e None yazar ve süreç bir daha Redis'e bakmaz (666 dersi)
	onbellek = frappe.cache().get_value(ALL_URLS_CACHE, expires=True)
	return list(onbellek) if onbellek else None


def warm_urls_async() -> None:
	"""Önbellek boşsa üretimi kuyruğa at (HTTP isteğini 25 s bloklamamak için); tekrar kuyruklama yok."""
	kilit = f"{ALL_URLS_CACHE}:warming"
	if frappe.cache().get_value(kilit, expires=True):
		return
	frappe.cache().set_value(kilit, 1, expires_in_sec=120)
	frappe.enqueue(
		"tradehub_core.seo_helper.adapters.tradehub.sitemap.all_urls",
		queue="seo",
		job_name="seo_helper.sitemap.warm",
		enqueue_after_commit=True,
	)


def all_urls(limit: int = 100000, *, use_cache: bool = True) -> list[str]:
	"""Sitemap'e giren tüm mutlak URL'ler (tradehub üreteci, tür tür). Crawler/bot kapsam karşılaştırması için.
	Üretim pahalı (tüm türlerin XML parçaları) → 1 saat önbellek; `mark_dirty`/`invalidate_all` düşürür."""
	import re

	from tradehub_core.seo import sitemap_generator as sg

	if use_cache:
		onbellek = cached_urls()
		if onbellek:
			return onbellek[:limit]
	out: list[str] = []
	for doctype in getattr(sg, "DOCTYPE_CONFIG", {}):
		try:
			for chunk in sg.build_chunks_for_type(doctype):
				metin = chunk if isinstance(chunk, str) else ""
				for loc in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", metin):
					out.append(loc.replace("&amp;", "&"))
					if len(out) >= limit:
						return out
		except Exception:  # noqa: BLE001 — bir tür düşerse diğerleri devam eder
			frappe.log_error(title=f"seo_helper sitemap.all_urls {doctype}", message=frappe.get_traceback())
	if use_cache and out:
		frappe.cache().set_value(ALL_URLS_CACHE, out, expires_in_sec=ALL_URLS_TTL)
	return out
