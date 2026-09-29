"""Builder köprüsü (14.2 / 14.3 / 14.5).

- Builder Page ↔ SEO Page 1:1, dil başına (`SEO Page(builder_page, lang)` benzersiz).
- Builder Page olayları: on_update → ayna + (commit sonrası) politika işi; yayın/geri çekme
  değişimi → route/sitemap/hreflang cache düşürme; on_trash → ayna arşivlenir, route gone.
- Builder çekirdeğine dokunulmaz: Builder `get_context` kendi metatags/canonical'ını üretir,
  `update_website_context` kancamız EN SON koşup aynı bağlam anahtarlarını tek elden yeniden
  belirler (4.3, `core.output`).
- Uzlaşma (`reconcile_pages`): her Builder Page için ayna var mı, yayın durumu tutuyor mu.
"""

from __future__ import annotations

import frappe
from frappe.utils import now_datetime

from tradehub_core.seo_helper.core import cache as cache_
from tradehub_core.seo_helper.core.queue import enqueue_after_commit

PUBLISH_STATE_BY_FLAG = {1: "published", 0: "draft"}


def _lang_of(bp) -> str:
	from tradehub_core.seo_helper.adapters.tradehub.meta import normalize_lang

	return normalize_lang(getattr(bp, "language", None) or bp.get("seo_lang") or "tr")


def _route_of(bp) -> str:
	return "/" + (bp.route or bp.page_name or "").lstrip("/")


def mirror_builder_page(bp) -> str:
	"""Builder Page için SEO Page aynasını oluştur/güncelle; döner: SEO Page.name."""
	lang = _lang_of(bp)
	name = frappe.db.get_value("SEO Page", {"builder_page": bp.name, "lang": lang}, "name")
	doc = frappe.get_doc("SEO Page", name) if name else frappe.new_doc("SEO Page")
	onceki_durum = doc.publish_state if name else None
	yeni_durum = bp.get("seo_publish_state") or PUBLISH_STATE_BY_FLAG[1 if bp.published else 0]
	# Builder'ın "published" bayrağı kapalıysa hiçbir SEO durumu yayında sayılmaz
	if not bp.published and yeni_durum == "published":
		yeni_durum = "draft"
	# Canonical: `seo_canonical` (Custom Field) GİRDİ, Builder'ın çekirdek `canonical_url` alanı ÇIKTI
	# yuvasıdır (politika sonucu oraya yazılır; Builder şablonu onu basar — bkz. core.policy).
	# Kullanıcı çekirdek alana yeni bir değer yazdıysa (son çıktıdan farklı) bunu girdi sayarız.
	son_cikti = doc.effective_canonical if name else None
	girdi = bp.get("seo_canonical")
	if bp.canonical_url and bp.canonical_url != son_cikti and bp.canonical_url != girdi:
		girdi = bp.canonical_url
		frappe.db.set_value("Builder Page", bp.name, "seo_canonical", girdi, update_modified=False)
	doc.update(
		{
			"builder_page": bp.name,
			"lang": lang,
			"route": _route_of(bp),
			"slug": bp.get("seo_slug") or (bp.route or "").rsplit("/", 1)[-1],
			"title": bp.page_title or bp.page_name,
			"meta_description": bp.meta_description,
			"canonical_url": girdi,
			"robots": bp.get("seo_robots"),
			"locale_cluster": bp.get("seo_locale_cluster"),
			"publish_state": yeni_durum,
			"og_image": bp.meta_image,
			"source": "builder",
		}
	)
	if not doc.get("domain"):
		doc.domain = frappe.db.get_value("SEO Domain", {"is_primary": 1}, "name")
	doc.flags.ignore_permissions = True  # ayna; yetki Builder Page'de denetlendi
	doc.save()
	if name and onceki_durum != yeni_durum and (yeni_durum == "published" or onceki_durum == "published"):
		from tradehub_core.seo_helper.experiments.changelog import on_builder_publish_change

		on_builder_publish_change(bp, onceki_durum, yeni_durum, doc.route, doc.store)
	if yeni_durum == "published" and onceki_durum != "published":
		doc.db_set("published_at", now_datetime(), update_modified=False)
	# 14.5 — yayından kaldırma: askıya alma/arşiv Builder'da da yayını kapatır → erişim HEMEN
	# kesilir (Builder yayınsız sayfayı servis etmez). db_set: hook zinciri yeniden tetiklenmez.
	if yeni_durum in ("suspended", "archived") and bp.published:
		frappe.db.set_value("Builder Page", bp.name, "published", 0, update_modified=False)
		clear_builder_route_cache(doc.route)
	cache_.bump_version("SEO Page", doc.name)
	return doc.name


def clear_builder_route_cache(route: str) -> None:
	"""Builder'ın route çözümleme cache'i + Frappe'nin Guest HTML cache'i (db_set Builder'ın kendi
	`clear_route_cache`'ini tetiklemez; Builder'ın public fonksiyonlarını çağırırız, patch değil)."""
	from frappe.website.utils import clear_cache

	clear_cache((route or "").strip("/"))
	try:
		from builder.builder.doctype.builder_page.builder_page import (
			find_page_with_path,
			get_web_pages_with_dynamic_routes,
		)

		find_page_with_path.clear_cache()
		get_web_pages_with_dynamic_routes.clear_cache()
	except Exception:  # noqa: BLE001 — Builder iç API'si değişirse yalnız cache tazeliği gecikir
		frappe.log_error(title="seo_helper builder route cache", message=frappe.get_traceback())


def on_builder_page_update(bp, method=None):
	"""Builder Page on_update: ayna + senkron politika (head ilk istekte doğru) + cache düşürme +
	commit sonrası yayılım işi (sitemap/hreflang/uzlaşma; 14.4)."""
	if bp.get("is_template") or bp.get("is_standard"):
		return
	name = mirror_builder_page(bp)
	from tradehub_core.seo_helper.core.policy import apply_for_page

	apply_for_page(name)
	page = frappe.db.get_value(
		"SEO Page", name, ["route", "lang", "domain", "store", "locale_cluster"], as_dict=True
	)
	cache_.invalidate_page(
		route=page.route,
		domain=page.domain or "*",
		lang=page.lang,
		store=page.store or "*",
		cluster=page.locale_cluster,
	)
	enqueue_after_commit("page.policy", {"page": name}, store=page.store, dedupe_key=f"page.policy:{name}")


def on_builder_page_trash(bp, method=None):
	for name in frappe.get_all("SEO Page", filters={"builder_page": bp.name}, pluck="name"):
		page = frappe.get_doc("SEO Page", name)
		page.db_set({"publish_state": "archived", "indexable": 0}, update_modified=False)
		cache_.bump_version("SEO Page", name)
		cache_.invalidate_page(
			route=page.route,
			domain=page.domain or "*",
			lang=page.lang,
			store=page.store or "*",
			cluster=page.locale_cluster,
		)
		frappe.db.set_value(
			"SEO Route", {"path": page.route, "lang": page.lang}, "status", "gone", update_modified=False
		)
		clear_builder_route_cache(page.route)


def reconcile_pages(**_) -> dict:
	"""Olay kaybı uzlaşması: aynası olmayan / yayın durumu uyuşmayan Builder Page'leri düzelt."""
	eksik = duzeltilen = 0
	for bp in frappe.get_all(
		"Builder Page", filters={"is_template": 0}, fields=["name", "published", "modified"]
	):
		pages = frappe.get_all(
			"SEO Page", filters={"builder_page": bp.name}, fields=["name", "publish_state"]
		)
		if not pages:
			mirror_builder_page(frappe.get_doc("Builder Page", bp.name))
			eksik += 1
			continue
		for p in pages:
			yayinda = p.publish_state == "published"
			if bool(bp.published) != yayinda and p.publish_state not in (
				"suspended",
				"archived",
				"scheduled",
			):
				mirror_builder_page(frappe.get_doc("Builder Page", bp.name))
				duzeltilen += 1
				break
	frappe.db.commit()
	return {"missing_created": eksik, "state_fixed": duzeltilen}
