"""Cache / yayın çıktıları (14.5).

Anahtar şeması: `shc:{kind}:{domain}:{lang}:{market}:{store}:{key}` — domain, dil, pazar ve
mağaza kapsamı anahtarın parçasıdır; bir kapsamın çıktısı diğerine sızmaz.

Veri sürümü: her SEO Page/Entity `data_version` taşır; HTML, schema, sitemap ve feed çıktıları
bu sürümü damgalar (`X-SEO-Data-Version` başlığı / sitemap lastmod). Çıktı üreticisi sürümü
eşleştirmezse yeniden üretir — böylece dört çıktı aynı sürüme yetişir.

Yayından kaldırma: `invalidate_page` route/sitemap/hreflang cache'ini düşürür ve route
`gone` olur; `core.output` gone route'a 410 verir (erişim hemen kesilir).
"""

from __future__ import annotations

import frappe

PREFIX = "shc"
KINDS = ("html", "head", "schema", "sitemap", "feed", "route", "hreflang")


def key(
	kind: str, *, domain: str = "*", lang: str = "*", market: str = "*", store: str = "*", ref: str = ""
) -> str:
	if kind not in KINDS:
		raise ValueError(f"bilinmeyen cache türü: {kind}")
	return f"{PREFIX}:{kind}:{domain or '*'}:{lang or '*'}:{market or '*'}:{store or '*'}:{ref}"


def get(k: str):
	return frappe.cache().get_value(k, expires=True)


def set_(k: str, value, ttl: int = 300) -> None:
	frappe.cache().set_value(k, value, expires_in_sec=ttl)


def delete_pattern(pattern: str) -> None:
	try:
		frappe.cache().delete_keys(pattern)
	except Exception:  # noqa: BLE001 — cache düşürme kaydı asla kilitlemez
		frappe.log_error(title="seo_helper cache delete_keys", message=pattern)


def invalidate_page(
	*, route: str, domain: str = "*", lang: str = "*", store: str = "*", cluster: str | None = None
) -> None:
	"""Builder yayın/geri çekme ve SEO Page değişimi: route + head + schema + hreflang + sitemap."""
	for kind in ("html", "head", "schema", "route"):
		delete_pattern(f"{PREFIX}:{kind}:{domain}:{lang}:*:{store}:{route}")
	# Frappe'nin Guest için tuttuğu render edilmiş HTML (`website_page`, route "/" öneksiz anahtarlı)
	from frappe.website.utils import clear_cache as _clear_website_cache

	_clear_website_cache((route or "").strip("/"))
	if cluster:
		delete_pattern(f"{PREFIX}:hreflang:*:*:*:*:{cluster}")
	delete_pattern(f"{PREFIX}:sitemap:{domain}:*")
	from tradehub_core.seo_helper.adapters.tradehub import sitemap as sm

	sm.mark_dirty("Builder Page")


def invalidate_store(store: str) -> None:
	delete_pattern(f"{PREFIX}:*:*:*:*:{store}:*")


def bump_version(doctype: str, name: str) -> int:
	"""data_version'ı atomik artır ve döndür (aynı sürüm tüm çıktılara damgalanır)."""
	frappe.db.sql(
		f"UPDATE `tab{doctype}` SET data_version = COALESCE(data_version, 0) + 1 WHERE name = %s", (name,)
	)
	return int(frappe.db.get_value(doctype, name, "data_version") or 0)
