"""Süper admin paneli uçları — rol kapısı (satıcı giremez), liste/özet/detay, denetim, kuyruk, istemciler."""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.seo_helper.api import panel
from tradehub_core.seo_helper.tests.ortak import ACIKLAMA, BASLIK, ShcOrtam


class TestPanelKapisi(ShcOrtam, FrappeTestCase):
	def test_satici_hicbir_uca_giremez(self):
		from tradehub_core.tests.mogem620_ortak import kullanici

		_s, u = self._seller("pk")
		with kullanici(u):
			for fn, args in (
				(panel.summary, {}),
				(panel.drafts, {}),
				(panel.pages, {}),
				(panel.findings, {}),
				(panel.crawl_runs, {}),
				(panel.audit_run, {"routes": []}),
				(panel.queue, {}),
				(panel.requeue_jobs, {"all_dead": 1}),
				(panel.clients, {}),
				(panel.tool_calls, {}),
			):
				with self.assertRaises(frappe.PermissionError, msg=fn.__name__):
					fn(**args)

	def test_seo_manager_rolu_girer(self):
		from tradehub_core.tests.mogem620_ortak import kullanici

		u = self._user("sm", roles=("SEO Manager",))
		with kullanici(u):
			self.assertIn("drafts_pending", panel.summary())


class TestPanelVeri(ShcOrtam, FrappeTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")

	def test_ozet_ve_taslak_listesi_detayi(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("pv")
		with self.mcp_istek(c["key"]):
			iyi = api.page_create(BASLIK, f"/pnl-{self._sonek()}", meta_description=ACIKLAMA)
			kotu = api.page_create("kısa", f"/pnl-k-{self._sonek()}", meta_description="x")
		frappe.set_user("Administrator")
		oz = panel.summary()
		self.assertGreaterEqual(oz["drafts_pending"], 2)
		self.assertGreaterEqual(oz["drafts_invalid"], 1)
		liste = panel.drafts(status="draft", limit=200)
		adlar = {r.name: r for r in liste["rows"]}
		self.assertIn(iyi["draft"], adlar)
		self.assertTrue(adlar[iyi["draft"]].publishable)
		self.assertFalse(adlar[kotu["draft"]].publishable)
		self.assertIn("TITLE_SHORT", adlar[kotu["draft"]].finding_codes)
		self.assertEqual(
			adlar[iyi["draft"]].client_name, frappe.db.get_value("MCP Client", c["name"], "client_name")
		)
		d = panel.draft_detail(iyi["draft"])
		self.assertEqual(d["payload"]["title"], BASLIK)
		self.assertEqual(d["tool_call"]["tool"], "page_create")
		self.assertIsNone(d["current"], "page_create'in hedefi henüz yok")

	def test_sayfalar_bulgular_denetim(self):
		p = self._seo_page("pb", title="kısa")
		from tradehub_core.seo_helper.core.policy import apply_for_page

		apply_for_page(p)
		route = frappe.db.get_value("SEO Page", p, "route")
		s = panel.pages(search=route)
		self.assertEqual(len(s["rows"]), 1)
		self.assertGreaterEqual(s["rows"][0].errors, 1)
		self.assertIn("TITLE_SHORT", [f.code for f in panel.findings(page=p)])
		with self.subTest("denetim mcp kuyruğuna gider"):
			from unittest.mock import patch

			with patch("frappe.enqueue") as enq:
				out = panel.audit_run(routes=[route])
			self.addCleanup(lambda: self._drop("SEO Crawl Run", out["crawl_run"]))
			self.addCleanup(lambda: self._drop("SEO Sync Job", out["job"]))
			self.assertEqual(enq.call_args.kwargs["queue"], "mcp")
			self.assertEqual(
				frappe.db.get_value("SEO Crawl Run", out["crawl_run"], "triggered_by"), "panel:Administrator"
			)
			self.assertEqual(panel.crawl_runs(limit=5)[0].name, out["crawl_run"])

	def test_kuyruk_ozeti_ve_dead_requeue(self):
		job = frappe.get_doc(
			{
				"doctype": "SEO Sync Job",
				"job_type": "page.policy",
				"queue": "seo",
				"status": "dead",
				"attempts": 5,
				"payload": "{}",
			}
		).insert(ignore_permissions=True)
		self.addCleanup(lambda: self._drop("SEO Sync Job", job.name))
		q = panel.queue(status="dead")
		self.assertIn(job.name, [r.name for r in q["rows"]])
		self.assertGreaterEqual(q["counts"]["dead"], 1)
		from unittest.mock import patch

		with patch("frappe.enqueue"):
			r = panel.requeue_jobs(jobs=[job.name])
		self.assertEqual(r["requeued"], 1)
		self.assertEqual(frappe.db.get_value("SEO Sync Job", job.name, ["status", "attempts"]), ("queued", 0))

	def test_istemciler_hash_donmez_kullanim_gelir(self):
		c = self._mcp_client("pi")
		frappe.get_doc(
			{
				"doctype": "MCP Tool Call",
				"client": c["name"],
				"tool": "page_create",
				"result": "ok",
				"cost_usd": 0.01,
			}
		).insert(ignore_permissions=True)
		rows = {r.name: r for r in panel.clients()}
		self.assertIn(c["name"], rows)
		self.assertNotIn("api_key_hash", rows[c["name"]])
		self.assertEqual(rows[c["name"]].month_calls, 1)
		self.assertGreater(rows[c["name"]].month_usd, 0)
		self.assertEqual(panel.tool_calls(client=c["name"])[0].tool, "page_create")
