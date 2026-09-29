"""14.6 — Builder yükseltme uyumluluk testi: sürüm pini, Custom Field'lar, hook'lar, adaptörler.

Builder yükseltilince ÖNCE bu modül koşar; kırılırsa yükseltme geri alınır (docs/OPERASYON.md).
"""

from __future__ import annotations

import subprocess

import frappe
from frappe.tests.utils import FrappeTestCase

PINNED_BUILDER = "v1.34.0"
CUSTOM_FIELDS = (
	"seo_slug",
	"seo_canonical",
	"seo_robots",
	"seo_locale_cluster",
	"seo_lang",
	"seo_publish_state",
)
BUILDER_FIELDS_WE_READ = (
	"page_title",
	"route",
	"published",
	"meta_description",
	"canonical_url",
	"disable_indexing",
	"language",
	"meta_image",
	"is_template",
	"is_standard",
	"head_html",
	"draft_blocks",
	"blocks",
)
BUILDER_CONTEXT_KEYS = ("title", "canonical_url", "disable_indexing", "metatags", "_head_html")


class TestBuilderUyum(FrappeTestCase):
	def test_builder_kurulu_ve_pinli(self):
		self.assertIn("builder", frappe.get_installed_apps())
		try:
			tag = subprocess.run(
				["git", "-C", frappe.get_app_path("builder", ".."), "describe", "--tags", "--exact-match"],
				capture_output=True,
				text=True,
				timeout=10,
			).stdout.strip()
		except Exception:  # noqa: BLE001
			tag = ""
		if tag:
			self.assertEqual(
				tag, PINNED_BUILDER, "Builder sürümü pinden sapmış — OPERASYON.md §Builder yükseltme"
			)

	def test_required_apps(self):
		"""Ayrı app iken `required_apps` ile bağlıydı; tradehub_core içinde builder YUMUŞAK bağımlılık —
		bu sitede kurulu olmalı (Builder köprüsü/e2e bunu varsayar) ve tradehub_core'dan sonra yüklenmiş olmalı."""
		kurulu = frappe.get_installed_apps()
		self.assertIn("builder", kurulu)
		self.assertLess(kurulu.index("tradehub_core"), kurulu.index("builder"))

	def test_custom_fieldlar_builder_page_ustunde(self):
		mevcut = {f.fieldname for f in frappe.get_meta("Builder Page").fields}
		for f in CUSTOM_FIELDS:
			self.assertIn(f, mevcut, f"Custom Field eksik: {f}")
		self.assertEqual(
			frappe.db.count("Custom Field", {"dt": "Builder Page", "fieldname": ["in", list(CUSTOM_FIELDS)]}),
			len(CUSTOM_FIELDS),
		)

	def test_builder_cekirdek_alanlari_hala_var(self):
		"""Köprünün okuduğu Builder alanları yükseltmede kaybolmamalı."""
		mevcut = {f.fieldname for f in frappe.get_meta("Builder Page").fields}
		for f in BUILDER_FIELDS_WE_READ:
			self.assertIn(f, mevcut, f"Builder Page alanı yok oldu: {f}")

	def test_builder_sablonu_bagim_anahtarlarini_okuyor(self):
		"""Tek head üreticisi Builder şablonunun okuduğu bağlam anahtarlarını belirler; şablon değişirse burası kırılır."""
		yol = frappe.get_app_path("builder", "templates", "generators", "webpage.html")
		with open(yol, encoding="utf-8") as f:
			sablon = f.read()
		for k in ("{{title}}", "canonical_url", "disable_indexing", "_head_html", "meta_block.html"):
			self.assertIn(k, sablon, f"Builder şablonu artık '{k}' okumuyor")

	def test_builder_cekirdegine_patch_yok(self):
		"""Yalnız hooks/Custom Field/DocType olayı: builder dizininde bizden bir değişiklik olmamalı."""
		r = subprocess.run(
			["git", "-C", frappe.get_app_path("builder", ".."), "status", "--porcelain"],
			capture_output=True,
			text=True,
			timeout=10,
		)
		# `bench build` yarn.lock'u yeniden yazabilir; kilit dosyası çekirdek patch'i sayılmaz.
		kirli = [
			ln
			for ln in r.stdout.splitlines()
			if ln.strip() and not ln.strip().endswith(("yarn.lock", "package-lock.json"))
		]
		self.assertEqual(kirli, [], f"builder çalışma ağacı kirli: {kirli[:5]}")

	def test_hooklar_kayitli(self):
		h = frappe.get_hooks()
		self.assertIn(
			"tradehub_core.seo_helper.cms.bridge.on_builder_page_update",
			h["doc_events"]["Builder Page"]["on_update"],
		)
		self.assertIn(
			"tradehub_core.seo_helper.cms.bridge.on_builder_page_trash",
			h["doc_events"]["Builder Page"]["on_trash"],
		)
		self.assertIn(
			"tradehub_core.seo_helper.core.output.update_website_context", h["update_website_context"]
		)
		self.assertIn("tradehub_core.seo_helper.mcp.auth.authenticate_mcp_client", h["auth_hooks"])
		self.assertIn(
			"tradehub_core.seo_helper.core.queue.sweep_due_jobs", h["scheduler_events"]["cron"]["*/5 * * * *"]
		)
		for dt in ("SEO Page", "MCP Draft", "MCP Client"):
			self.assertIn(dt, h["permission_query_conditions"])
			self.assertIn(dt, h["has_permission"])

	def test_tradehub_adaptor_imzalari(self):
		"""tradehub_core.seo imzası değişirse önce burası kırılır (adaptör katmanı tek temas noktası)."""
		import inspect

		from tradehub_core.seo.meta_builder import compose_seo_payload
		from tradehub_core.seo.seo_html_injector import render_seo_head
		from tradehub_core.seo.sitemap_cache import dirty_key_for

		self.assertEqual(
			set(inspect.signature(compose_seo_payload).parameters)
			>= {"record", "url_prefix", "defaults", "site_url", "lang"},
			True,
		)
		self.assertEqual(list(inspect.signature(render_seo_head).parameters), ["seo"])
		self.assertTrue(dirty_key_for("Listing"))
		from tradehub_core.seo_helper.adapters.tradehub import meta as meta_ad

		seo = meta_ad.compose(
			{"title": "Başlık deneme", "description": "açıklama"},
			lang="tr",
			route="/deneme",
			robots="index,follow",
		)
		self.assertIn("canonical", seo)
		self.assertIn("<title>", meta_ad.render_head(seo))

	def test_moduller_ve_doctypelar(self):
		from pathlib import Path

		moduller = Path(frappe.get_app_path("tradehub_core", "modules.txt")).read_text().splitlines()
		self.assertEqual(moduller[0], "Tradehub Core")
		for m in (
			"SEO Core",
			"SEO Catalog",
			"SEO CMS",
			"SEO Merchant",
			"SEO Crawler",
			"SEO Helper",
			"SEO MCP",
		):
			self.assertIn(m, moduller)
			self.assertEqual(frappe.db.get_value("Module Def", m, "app_name"), "tradehub_core", m)
		for dt in (
			"SEO Entity",
			"SEO Page",
			"SEO Domain",
			"SEO Route",
			"SEO Policy",
			"SEO Profile",
			"SEO Redirect Rule",
			"SEO Locale Cluster",
			"SEO Facet Landing Page",
			"SEO Merchant Map",
			"SEO Sync Job",
			"SEO Crawl Run",
			"SEO Audit Finding",
			"SEO Helper Rule",
			"MCP Client",
			"MCP Tool Call",
			"MCP Draft",
			"SEO Helper Settings",
		):
			self.assertTrue(frappe.db.exists("DocType", dt), dt)
		self.assertTrue(frappe.db.exists("SEO Policy", "default"))
		self.assertTrue(frappe.db.exists("SEO Domain", {"is_primary": 1}))
		for r in ("SEO Manager", "SEO Editor", "MCP Agent"):
			self.assertTrue(frappe.db.exists("Role", r), r)
