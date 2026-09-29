"""Çalışma zamanı — Builder köprüsü, tek head üreticisi, kuyruk/uzlaşma, cache, izinler, ayna."""

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.seo_helper.tests.ortak import ACIKLAMA, BASLIK, ShcOrtam


class TestBuilderKoprusu(ShcOrtam, FrappeTestCase):
	def test_builder_page_kaydi_seo_page_aynasi_uretir(self):
		bp = self._builder_page("ayna")
		rows = frappe.get_all(
			"SEO Page",
			filters={"builder_page": bp},
			fields=["name", "lang", "route", "title", "publish_state", "source", "data_version"],
		)
		self.assertEqual(len(rows), 1)
		r = rows[0]
		self.assertEqual((r.lang, r.publish_state, r.source), ("tr", "published", "builder"))
		self.assertTrue(r.route.startswith("/shc-ayna-"))
		self.assertEqual(r.title, BASLIK)
		self.assertGreaterEqual(int(r.data_version), 1)
		# politika işi commit sonrası kuyruğa alındı (SEO Sync Job)
		job = frappe.db.get_value(
			"SEO Sync Job",
			{
				"dedupe_key": f"page.policy:{rows[0].name}",
				"job_type": "page.policy",
			},
			"name",
		)
		self.assertTrue(job)

	def test_ikinci_kayit_ikinci_ayna_acmaz_1e1(self):
		bp = self._builder_page("tekil")
		doc = frappe.get_doc("Builder Page", bp)
		doc.page_title = BASLIK + " v2"
		doc.flags.ignore_permissions = True
		doc.save()
		self.assertEqual(frappe.db.count("SEO Page", {"builder_page": bp}), 1)
		self.assertEqual(frappe.db.get_value("SEO Page", {"builder_page": bp}, "title"), BASLIK + " v2")

	def test_custom_field_yayin_durumu_aynaya_gecer(self):
		bp = self._builder_page(
			"durum", seo_publish_state="review", seo_robots="noindex,follow", seo_slug="ozel-slug"
		)
		r = frappe.db.get_value(
			"SEO Page", {"builder_page": bp}, ["publish_state", "robots", "slug"], as_dict=True
		)
		self.assertEqual((r.publish_state, r.robots, r.slug), ("review", "noindex,follow", "ozel-slug"))

	def test_yayinsiz_builder_sayfasi_published_sayilmaz(self):
		bp = self._builder_page("yayinsiz", published=0, seo_publish_state="published")
		self.assertEqual(frappe.db.get_value("SEO Page", {"builder_page": bp}, "publish_state"), "draft")

	def test_askiya_alma_builder_yayinini_hemen_kapatir(self):
		bp = self._builder_page("askiya")
		doc = frappe.get_doc("Builder Page", bp)
		doc.seo_publish_state = "suspended"
		doc.flags.ignore_permissions = True
		doc.save()
		self.assertEqual(
			frappe.db.get_value("Builder Page", bp, "published"), 0, "14.5: erişim hemen kesilir"
		)
		from tradehub_core.seo_helper.core.output import head_for_route

		self.assertEqual(
			head_for_route(frappe.db.get_value("SEO Page", {"builder_page": bp}, "route"))["status"], 410
		)

	def test_silme_aynayi_arsivler_route_gone(self):
		bp = self._builder_page("sil")
		page = frappe.db.get_value("SEO Page", {"builder_page": bp}, ["name", "route", "lang"], as_dict=True)
		frappe.get_doc(
			{
				"doctype": "SEO Route",
				"path": page.route,
				"lang": page.lang,
				"target_doctype": "Builder Page",
				"target_name": bp,
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: frappe.db.delete("SEO Route", {"path": page.route}))
		frappe.delete_doc("Builder Page", bp, force=True, ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("SEO Page", page.name, "publish_state"), "archived")
		self.assertEqual(frappe.db.get_value("SEO Route", {"path": page.route}, "status"), "gone")

	def test_uzlasma_eksik_aynayi_tamamlar(self):
		from tradehub_core.seo_helper.cms.bridge import reconcile_pages

		bp = self._builder_page("uzlasma")
		frappe.db.delete("SEO Page", {"builder_page": bp})  # olay kaybı simülasyonu
		frappe.db.commit()
		r = reconcile_pages()
		self.assertGreaterEqual(r["missing_created"], 1)
		self.assertEqual(frappe.db.count("SEO Page", {"builder_page": bp}), 1)


class TestCanonicalCiktiYuvasi(ShcOrtam, FrappeTestCase):
	"""Frappe, hook'lardan SONRA Builder'ın set_canonical_url'ünü koşturur → Builder'ın çekirdek
	canonical_url alanı politika ÇIKTISI, seo_canonical Custom Field'ı GİRDİ olarak ayrılır."""

	def test_yanlis_hostlu_girdi_cikti_yuvasina_duzeltilmis_yazilir(self):
		bp = self._builder_page("cy", canonical_url="https://www.baska-host.com/yol")
		row = frappe.db.get_value("Builder Page", bp, ["canonical_url", "seo_canonical"], as_dict=True)
		from tradehub_core.seo_helper.adapters.tradehub.meta import site_url

		self.assertEqual(row.canonical_url, f"{site_url()}/yol", "çıktı yuvası politika sonucu")
		self.assertEqual(row.seo_canonical, "https://www.baska-host.com/yol", "girdi korunur")
		self.assertEqual(
			frappe.db.get_value("SEO Page", {"builder_page": bp}, "effective_canonical"), f"{site_url()}/yol"
		)

	def test_ikinci_kayit_ciktiyi_girdi_sanmaz(self):
		bp = self._builder_page("cy2", canonical_url="https://www.baska-host.com/yol")
		doc = frappe.get_doc("Builder Page", bp)
		doc.page_title = BASLIK + " v2"
		doc.flags.ignore_permissions = True
		doc.save()  # canonical_url artık çıktı değerini taşıyor; girdi değişmemeli
		self.assertEqual(
			frappe.db.get_value("Builder Page", bp, "seo_canonical"), "https://www.baska-host.com/yol"
		)

	def test_kullanici_cekirdek_alana_yeni_deger_yazarsa_girdi_olur(self):
		bp = self._builder_page("cy3")
		doc = frappe.get_doc("Builder Page", bp)
		doc.canonical_url = "/yeni-kanonik"
		doc.flags.ignore_permissions = True
		doc.save()
		from tradehub_core.seo_helper.adapters.tradehub.meta import site_url

		row = frappe.db.get_value("Builder Page", bp, ["canonical_url", "seo_canonical"], as_dict=True)
		self.assertEqual(
			(row.seo_canonical, row.canonical_url), ("/yeni-kanonik", f"{site_url()}/yeni-kanonik")
		)

	def test_politika_uygulamasi_surumu_artirir_ve_head_cache_yenilenir(self):
		from tradehub_core.seo_helper.core.output import head_for_route
		from tradehub_core.seo_helper.core.policy import apply_for_page

		p = self._seo_page("pv")
		apply_for_page(p)
		route = frappe.db.get_value("SEO Page", p, "route")
		v1 = head_for_route(route)["parts"]["data_version"]
		frappe.db.set_value("SEO Page", p, "robots", "noindex,follow", update_modified=False)
		apply_for_page(p)  # bump + invalidate → yeni robots hemen head'de
		out = head_for_route(route)
		self.assertGreater(out["parts"]["data_version"], v1)
		self.assertEqual(out["parts"]["robots"], "noindex,follow")


class TestTekHeadUreticisi(ShcOrtam, FrappeTestCase):
	def test_head_parcalari_ve_tek_robots(self):
		from tradehub_core.seo_helper.core.output import build_head_parts, head_for_route
		from tradehub_core.seo_helper.core.policy import apply_for_page

		p = self._seo_page("head", locale_cluster=None)
		apply_for_page(p)
		page = frappe.get_doc("SEO Page", p).as_dict()
		parts = build_head_parts(page)
		self.assertEqual(parts["canonical"], page["effective_canonical"])
		self.assertIn('name="robots" content="index,follow"', parts["extras_html"])
		self.assertEqual(parts["extras_html"].count('name="robots"'), 1)
		self.assertIn('"@type": "WebPage"'.replace(" ", ""), parts["extras_html"].replace(" ", ""))
		self.assertEqual(parts["metatags"]["description"], ACIKLAMA)
		out = head_for_route(page["route"], "tr")
		self.assertEqual(out["status"], 200)
		self.assertEqual(out["parts"]["data_version"], int(page["data_version"] or 0))

	def test_website_context_builder_alanlarini_tek_elden_belirler(self):
		from tradehub_core.seo_helper.core.output import update_website_context
		from tradehub_core.seo_helper.core.policy import apply_for_page

		p = self._seo_page("ctx")
		apply_for_page(p)
		page = frappe.get_doc("SEO Page", p)
		ctx = frappe._dict(
			route=page.route,
			title="Builder başlığı",
			canonical_url="https://baska/x",
			disable_indexing=1,
			metatags={"description": "builder"},
			_head_html="<meta name=x>",
		)
		ctx = update_website_context(ctx)
		self.assertEqual(ctx["title"], BASLIK)
		self.assertEqual(ctx["canonical_url"], page.effective_canonical)
		self.assertEqual(ctx["disable_indexing"], 0)
		self.assertEqual(ctx["metatags"]["description"], ACIKLAMA)
		self.assertTrue(ctx["_head_html"].startswith("<meta name=x>"))
		self.assertEqual(ctx["_head_html"].count('name="robots"'), 1)

	def test_bilinmeyen_route_dokunmaz(self):
		from tradehub_core.seo_helper.core.output import update_website_context

		ctx = frappe._dict(route="/yok-boyle-bir-sayfa", title="T")
		self.assertEqual(update_website_context(ctx)["title"], "T")

	def test_cache_veri_surumune_yetisir(self):
		from tradehub_core.seo_helper.core import cache as cache_
		from tradehub_core.seo_helper.core.output import head_for_route
		from tradehub_core.seo_helper.core.policy import apply_for_page

		p = self._seo_page("ver")
		apply_for_page(p)
		route = frappe.db.get_value("SEO Page", p, "route")
		v1 = head_for_route(route)["parts"]["data_version"]
		frappe.db.set_value("SEO Page", p, "title", BASLIK + " yeni", update_modified=False)
		cache_.bump_version("SEO Page", p)
		out = head_for_route(route)
		self.assertGreater(out["parts"]["data_version"], v1)
		self.assertEqual(out["parts"]["title"], BASLIK + " yeni", "sürüm değişince cache yeniden üretildi")

	def test_hreflang_kumesi(self):
		from tradehub_core.seo_helper.core.output import build_head_parts
		from tradehub_core.seo_helper.core.policy import apply_for_page

		frappe.get_doc({"doctype": "SEO Locale Cluster", "cluster_key": f"shc-kume-{self._sonek()}"}).insert(
			ignore_permissions=True
		)
		kume = f"shc-kume-{self._sonek()}"
		self.addCleanup(lambda: self._drop("SEO Locale Cluster", kume))
		tr = self._seo_page("hl-tr", locale_cluster=kume, lang="tr")
		en = self._seo_page("hl-en", locale_cluster=kume, lang="en")
		apply_for_page(tr)
		apply_for_page(en)
		parts = build_head_parts(frappe.get_doc("SEO Page", tr).as_dict())
		self.assertIn('hreflang="en"', parts["extras_html"])
		self.assertIn('hreflang="x-default"', parts["extras_html"])


class TestKuyruk(ShcOrtam, FrappeTestCase):
	def test_is_yasam_dongusu_backoff_dead_requeue(self):
		from tradehub_core.seo_helper.core import queue as q

		with (
			patch.object(
				q,
				"HANDLERS",
				{**q.HANDLERS, "test.patla": "tradehub_core.seo_helper.tests.test_runtime._patla"},
			),
			patch("frappe.enqueue"),
		):
			job = q.enqueue_after_commit("test.patla", {"x": 1}, dedupe_key=f"t:{self._sonek()}")
			self.addCleanup(lambda: self._drop("SEO Sync Job", job))
			self.assertEqual(
				q.enqueue_after_commit("test.patla", {"x": 1}, dedupe_key=f"t:{self._sonek()}"),
				job,
				"dedupe: aynı iş iki kez açılmaz",
			)
			for i in range(1, 6):
				r = q.run_job(job)
				row = frappe.db.get_value(
					"SEO Sync Job", job, ["status", "attempts", "next_attempt_at"], as_dict=True
				)
				self.assertEqual(row.attempts, i)
				if i < 5:
					self.assertEqual((r["status"], row.status), ("failed", "failed"))
					self.assertTrue(row.next_attempt_at)
					frappe.db.set_value(
						"SEO Sync Job",
						job,
						"next_attempt_at",
						frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-1),
					)
					frappe.db.set_value("SEO Sync Job", job, "status", "failed")
				else:
					self.assertEqual(row.status, "dead")
			self.assertTrue(q.run_job(job).get("skipped"), "ölü iş kendiliğinden koşmaz")
			q.requeue(job)
			self.assertEqual(
				frappe.db.get_value("SEO Sync Job", job, ["status", "attempts"], as_dict=True),
				{"status": "queued", "attempts": 0},
			)

	def test_supurucu_suresi_geleni_ve_eskimis_kuyrugu_alir(self):
		from tradehub_core.seo_helper.core import queue as q

		with (
			patch.object(
				q, "HANDLERS", {**q.HANDLERS, "test.ok": "tradehub_core.seo_helper.tests.test_runtime._ok"}
			),
			patch("frappe.enqueue"),
		):
			j1 = q.enqueue_after_commit("test.ok", {}, dedupe_key=f"s1:{self._sonek()}")
			j2 = q.enqueue_after_commit("test.ok", {}, dedupe_key=f"s2:{self._sonek()}")
			for j in (j1, j2):
				self.addCleanup(lambda j=j: self._drop("SEO Sync Job", j))
			frappe.db.set_value(
				"SEO Sync Job",
				j1,
				{
					"status": "failed",
					"next_attempt_at": frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-1),
				},
				update_modified=False,
			)
			frappe.db.set_value(
				"SEO Sync Job",
				j2,
				"modified",
				frappe.utils.add_to_date(frappe.utils.now_datetime(), minutes=-30),
				update_modified=False,
			)
			frappe.db.commit()
			with patch.object(q.frappe.db, "commit"):
				r = q.sweep_due_jobs()
			self.assertGreaterEqual(r["done"], 2, r)

	def test_kuyruk_adlari_kapasite_ayrimi(self):
		from tradehub_core.seo_helper.core.queue import QUEUES

		self.assertEqual(QUEUES, {"default": "seo", "long": "seo_long", "mcp": "mcp"})


class TestCacheAnahtari(FrappeTestCase):
	def test_kapsam_anahtarin_parcasi(self):
		from tradehub_core.seo_helper.core import cache as c

		k = c.key("head", domain="istoc.com", lang="en", market="TR", store="SEL-1", ref="/x")
		self.assertEqual(k, "shc:head:istoc.com:en:TR:SEL-1:/x")
		self.assertNotEqual(
			k, c.key("head", domain="istoc.com", lang="tr", market="TR", store="SEL-1", ref="/x")
		)
		with self.assertRaises(ValueError):
			c.key("bilinmeyen")


class TestIzinler(ShcOrtam, FrappeTestCase):
	def test_satici_yalniz_kendi_magazasini_gorur(self):
		from tradehub_core.tests.mogem620_ortak import kullanici

		s1, u1 = self._seller("iz1")
		s2, _u2 = self._seller("iz2")
		p1 = self._seo_page("iz1", store=s1)
		p2 = self._seo_page("iz2", store=s2)
		with kullanici(u1):
			adlar = set(frappe.get_list("SEO Page", filters={"name": ["in", [p1, p2]]}, pluck="name"))
			self.assertEqual(adlar, {p1})
			self.assertTrue(frappe.has_permission("SEO Page", "read", frappe.get_doc("SEO Page", p1)))
			self.assertFalse(frappe.has_permission("SEO Page", "read", frappe.get_doc("SEO Page", p2)))

	def test_magazasiz_kullanici_hic_gormez_admin_hepsini(self):
		from tradehub_core.tests.mogem620_ortak import kullanici

		p = self._seo_page("izadmin")
		u = self._user("magazasiz")
		with kullanici(u):
			self.assertEqual(frappe.get_list("SEO Page", filters={"name": p}, pluck="name"), [])
		self.assertIn(p, frappe.get_list("SEO Page", filters={"name": p}, pluck="name"))

	def test_api_kapisi(self):
		from tradehub_core.seo_helper.core.permissions import require_store_access
		from tradehub_core.tests.mogem620_ortak import kullanici

		s1, u1 = self._seller("api1")
		s2, _ = self._seller("api2")
		with kullanici(u1):
			self.assertEqual(require_store_access(None), s1)
			with self.assertRaises(frappe.PermissionError):
				require_store_access(s2)


class TestKatalogAynasi(ShcOrtam, FrappeTestCase):
	def test_listing_kaydi_seo_entity_uretir(self):
		seller, _ = self._seller("katalog")
		doc = frappe.get_doc(
			{
				"doctype": "Listing",
				"title": BASLIK,
				"seller_profile": seller,
				"seller_sku": f"SHC-{self._sonek()}",
				"currency": "TRY",
				"base_price": 10,
				"selling_price": 9,
				"stock_qty": 1,
				"status": "Active",
				"description": ACIKLAMA,
			}
		)
		doc.flags.from_admin = True
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(lambda: self._drop("Listing", doc.name))
		self.addCleanup(lambda: frappe.db.delete("SEO Entity", {"ref_name": doc.name}))
		e = frappe.db.get_value(
			"SEO Entity",
			{"ref_doctype": "Listing", "ref_name": doc.name},
			["entity_type", "store", "indexable", "data_version"],
			as_dict=True,
		)
		self.assertIsNotNone(e)
		self.assertEqual((e.entity_type, e.store), ("listing", seller))


def _patla(**_):
	raise RuntimeError("bilerek")


def _ok(**_):
	return {"ok": True}


class TestGeriDoldurma(ShcOrtam, FrappeTestCase):
	def test_patch_aynasiz_builder_sayfasini_tamamlar_idempotent(self):
		from tradehub_core.seo_helper.patches.v0_1.backfill_builder_pages import execute

		bp = self._builder_page("bf")
		frappe.db.delete("SEO Page", {"builder_page": bp})
		frappe.db.commit()
		execute()
		self.assertEqual(frappe.db.count("SEO Page", {"builder_page": bp}), 1)
		p = frappe.db.get_value(
			"SEO Page", {"builder_page": bp}, ["effective_canonical", "publish_state"], as_dict=True
		)
		self.assertTrue(p.effective_canonical, "politika geri doldurmada uygulanır")
		execute()  # ikinci koşum dokunmaz
		self.assertEqual(frappe.db.count("SEO Page", {"builder_page": bp}), 1)
