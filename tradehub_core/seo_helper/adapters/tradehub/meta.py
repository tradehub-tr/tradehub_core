"""Metadata adaptörü — `tradehub_core.seo.meta_builder` + `seo_html_injector`."""

from __future__ import annotations

import frappe


def site_url() -> str:
	from tradehub_core.seo.site_url import storefront_url

	return storefront_url()


def compose(
	record: dict,
	*,
	lang: str,
	route: str,
	robots: str,
	og_type: str = "website",
	json_ld: list[dict] | None = None,
) -> dict:
	"""Saf `compose_seo_payload` çağrısı (gerçek imza: record, url_prefix, defaults, site_url, og_type,
	slug_field, og_image_resolver, json_ld, lang). Builder sayfası için url_prefix boş, slug = route."""
	from tradehub_core.seo.meta_builder import compose_seo_payload

	kayit = dict(record)
	kayit.setdefault("slug", (route or "/").strip("/"))
	kayit.setdefault("robots", robots)
	return compose_seo_payload(
		record=kayit,
		url_prefix="",
		defaults=current_site_defaults(),
		site_url=site_url(),
		og_type=og_type,
		slug_field="slug",
		json_ld=json_ld,
		lang=lang,
	)


def render_head(seo: dict) -> str:
	"""Tek head bloğu — Jinja şablonu tradehub_core'da (`seo/templates/seo_head.html`)."""
	from tradehub_core.seo.seo_html_injector import render_seo_head

	return render_seo_head(seo)


def hreflang_links(canonical_tr_path: str) -> list[dict]:
	from tradehub_core.seo.i18n import build_hreflang_links

	return build_hreflang_links(canonical_tr_path, site_url())


def normalize_lang(lang: str | None) -> str:
	from tradehub_core.seo.i18n import normalize_lang

	return normalize_lang(lang)


def check_lengths(meta_title: str, meta_description: str) -> list[str]:
	"""tradehub'ın uzunluk kuralı — politika motoru deterministik doğrulamada kullanır (11.4)."""
	from tradehub_core.seo.hooks_seo import _check_seo_lengths

	return _check_seo_lengths(meta_title or "", meta_description or "")


def current_site_defaults() -> dict:
	from tradehub_core.seo.meta_builder import _load_site_defaults

	try:
		return _load_site_defaults()
	except Exception:  # noqa: BLE001 — Website Settings yoksa boş varsayılanla devam
		frappe.log_error(title="seo_helper: site defaults okunamadı", message=frappe.get_traceback())
		return {}
