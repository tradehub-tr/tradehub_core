"""
SEO sitemap scheduler ve manuel rebuild endpoint'leri (BE-MAP).

`daily_sitemap_rebuild()` cron tarafından çağrılır (hooks.scheduler_events)
ve asıl işi LONG queue'ya atar — 1M kayıtlık rebuild default worker'ı
kilitleyemez. `rebuild_all_sitemaps_now()` whitelist endpoint (manuel trigger)
aynı işi yine long queue üzerinden koşturur.

Parçalar diske yazılır (public/files/sitemaps/), Redis yalnız index +
tek-parça fallback taşır. Parça sayıları Redis'te tutulur; kaybolursa
`discover_parts_from_disk()` glob fallback'i devreye girer.
"""

import frappe

from tradehub_core.seo.sitemap_cache import (
	cleanup_stale_chunks,
	discover_parts_from_disk,
	get_default_cache,
	read_sitemap_file,
	write_sitemap_file,
)
from tradehub_core.seo.sitemap_generator import (
	DOCTYPE_CONFIG,
	build_chunks_for_type,
	build_index,
	sitemap_file_name,
)

PARTS_KEY = "tradehub:seo:sitemap_parts"  # {sub_name: parça sayısı}


def _rebuild_type(doctype: str) -> int:
	"""Tek doctype: parçaları akıtarak diske yaz, bayat parçaları sil.

	Döner: yazılan parça sayısı."""
	cfg = DOCTYPE_CONFIG[doctype]
	sub = cfg["sub_sitemap_name"]
	cache = get_default_cache()

	# Parça sayısı üretim bitmeden bilinmez → önce numaralı adlarla yaz,
	# tek parça çıkarsa suffix'siz kanonik ada da yaz (küçük doctype'lar).
	chunks = []
	for i, xml in enumerate(build_chunks_for_type(doctype), start=1):
		write_sitemap_file(f"sitemap-{sub}-{i}.xml", xml)
		chunks.append(i)
		if i == 1:
			# Tek-parça fallback: Redis'e de koy (endpoint disk yoksa buradan okur)
			cache.set_xml(doctype, xml)

	total = len(chunks)
	keep = {f"sitemap-{sub}-{i}.xml" for i in chunks}
	if total == 1:
		# Kanonik suffix'siz ad — index tek parçada bunu ilan eder
		canonical = sitemap_file_name(sub, 1, 1)
		xml = read_sitemap_file(f"sitemap-{sub}-1.xml")
		if xml is not None:
			write_sitemap_file(canonical, xml)
			keep.add(canonical)
	cleanup_stale_chunks(sub, keep)
	cache.clear_dirty(doctype)
	return total


def _store_parts(parts: dict) -> None:
	frappe.cache.set_value(PARTS_KEY, parts, expires_in_sec=7 * 24 * 60 * 60)


def _load_parts() -> dict:
	parts = frappe.cache.get_value(PARTS_KEY)
	if isinstance(parts, dict) and parts:
		return parts
	# Redis flush/restore sonrası glob fallback'i
	return discover_parts_from_disk()


def _rebuild_index(parts: dict | None = None) -> None:
	"""Sitemap index'i yeniden üret + cache'e ve diske koy."""
	cache = get_default_cache()
	xml = build_index(parts or _load_parts())
	cache.set_xml("index", xml)
	write_sitemap_file("sitemap-index.xml", xml)


def rebuild_all_sitemaps() -> dict:
	"""Tüm tipleri rebuild et (LONG queue işçisinde koşar)."""
	parts: dict = {}
	for doctype, cfg in DOCTYPE_CONFIG.items():
		try:
			parts[cfg["sub_sitemap_name"]] = _rebuild_type(doctype)
		except Exception:
			# Bir tip patlarsa diğerleri yine üretilsin; bayat XML 503'e tercih
			# (plan FAZ E kararı) — Error Log + haftalık GSC kontrolü izler.
			frappe.log_error(frappe.get_traceback(), f"sitemap rebuild: {doctype}")
	_store_parts(parts)
	_rebuild_index(parts)
	frappe.logger().info(f"[SEO] sitemap rebuild: {parts}")
	return {"ok": True, "parts": parts}


def daily_sitemap_rebuild() -> None:
	"""Cron daily — rebuild'i LONG queue'ya at (worker'ı kilitleme)."""
	frappe.enqueue(
		"tradehub_core.seo.tasks.rebuild_all_sitemaps",
		queue="long",
		job_id="seo-sitemap-rebuild",
		deduplicate=True,
	)


@frappe.whitelist()
def rebuild_all_sitemaps_now() -> dict:
	"""Manuel trigger: rebuild'i long queue'ya sıraya koy.

	Yalnızca System Manager / Marketplace Admin çağırabilir."""
	frappe.only_for(["System Manager", "Marketplace Admin"])

	frappe.enqueue(
		"tradehub_core.seo.tasks.rebuild_all_sitemaps",
		queue="long",
		job_id="seo-sitemap-rebuild",
		deduplicate=True,
	)
	return {"ok": True, "queued": True, "queue": "long"}
