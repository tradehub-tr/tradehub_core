"""
SEO sitemap scheduler ve manuel rebuild endpoint'leri.

`daily_sitemap_rebuild()` cron tarafından çağrılır (hooks.scheduler_events).
`rebuild_all_sitemaps_now()` whitelist endpoint — manuel trigger için.

Not: Cron her gün tüm tip için rebuild eder (dirty flag'e bağımlı değil).
mark_dirty Redis'e yazılıyor ama Frappe v15 cache.get_value lazy-commit
davranışı yüzünden cron-time okuma güvenilmez. 254 row için tüm rebuild
< 1 saniye; optimization gerekirse Faz 6'da düzeltilir.
"""

import frappe

from tradehub_core.seo.sitemap_cache import get_default_cache
from tradehub_core.seo.sitemap_generator import DOCTYPE_CONFIG, build_for_type, build_index


def _rebuild_type(doctype: str) -> None:
	"""Tek doctype için sitemap yeniden üret + cache'e koy + dirty temizle."""
	cache = get_default_cache()
	xml = build_for_type(doctype)
	cache.set_xml(doctype, xml)
	cache.clear_dirty(doctype)


def _rebuild_index() -> None:
	"""Sitemap index'i yeniden üret + cache'e koy."""
	cache = get_default_cache()
	xml = build_index()
	cache.set_xml("index", xml)


def daily_sitemap_rebuild() -> None:
	"""Cron daily 03:00 — tüm doctype'ları rebuild + index refresh.

	hooks.scheduler_events['daily'] ile bağlanır. is_dirty kontrolü
	yapılmaz; her gün full rebuild (254 row için < 1 saniye)."""
	for doctype in DOCTYPE_CONFIG.keys():
		_rebuild_type(doctype)
	_rebuild_index()

	frappe.logger().info(
		f"[SEO] daily_sitemap_rebuild: {list(DOCTYPE_CONFIG.keys())} regenerated"
	)


@frappe.whitelist()
def rebuild_all_sitemaps_now() -> dict:
	"""Manuel trigger: 4 sitemap + index'i hemen yeniden üret.

	Yalnızca System Manager / Marketplace Admin çağırabilir."""
	frappe.only_for(["System Manager", "Marketplace Admin"])

	for doctype in DOCTYPE_CONFIG.keys():
		_rebuild_type(doctype)
	_rebuild_index()

	return {"ok": True, "rebuilt": list(DOCTYPE_CONFIG.keys())}
