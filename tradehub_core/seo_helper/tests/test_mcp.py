"""MCP — kimlik (API key + rol + mağaza), araçlar yalnız taslak üretir, insan onayı, kota/günlük/rotasyon."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.seo_helper.tests.ortak import ACIKLAMA, BASLIK, ShcOrtam


class TestKimlik(ShcOrtam, FrappeTestCase):
	def test_anahtarsiz_ve_bozuk_anahtar_401(self):
		from tradehub_core.seo_helper.mcp import api

		for key in (None, "shc_x_y", "yanlis"):
			with self.mcp_istek(key), self.assertRaises(frappe.AuthenticationError):
				api.page_create(BASLIK, "/x")

	def test_kapsam_disi_403(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("kapsam", scopes="page:read")
		with self.mcp_istek(c["key"]), self.assertRaises(frappe.PermissionError):
			api.page_create(BASLIK, "/x")

	def test_kanca_yalniz_mcp_yolunda_oturum_kurar_ve_govdeyi_korur(self):
		from tradehub_core.seo_helper.mcp.auth import AGENT_USER, authenticate_mcp_client

		c = self._mcp_client("kanca")
		with self.mcp_istek(c["key"], "/api/method/frappe.client.get_list"):
			authenticate_mcp_client()
			self.assertEqual(frappe.session.user, "Guest", "başka yolda anahtar oturum açmaz")
		with self.mcp_istek(c["key"]):
			frappe.local.form_dict = frappe._dict(title="t")
			authenticate_mcp_client()
			self.assertEqual(frappe.session.user, AGENT_USER)
			self.assertEqual(frappe.local.form_dict.get("title"), "t")

	def test_magazali_istemci_magaza_sahibi_olarak_kosar_ve_baskasina_giremez(self):
		from tradehub_core.seo_helper.mcp import api
		from tradehub_core.seo_helper.mcp.auth import authenticate_mcp_client

		s1, u1 = self._seller("m1")
		s2, _ = self._seller("m2")
		c = self._mcp_client("magaza", store=s1)
		with self.mcp_istek(c["key"]):
			authenticate_mcp_client()
			self.assertEqual(frappe.session.user, u1)
			with self.assertRaises(frappe.PermissionError):
				api.page_create(BASLIK, "/x", store=s2)

	def test_kapali_istemci_reddedilir(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("kapali")
		frappe.db.set_value("MCP Client", c["name"], "enabled", 0)
		with self.mcp_istek(c["key"]), self.assertRaises(frappe.AuthenticationError):
			api.result_read()

	def test_anahtar_dbde_yalniz_ozet(self):
		c = self._mcp_client("ozet")
		row = frappe.db.get_value("MCP Client", c["name"], ["api_key_hash", "api_key_prefix"], as_dict=True)
		self.assertNotIn(c["key"], (row.api_key_hash, row.api_key_prefix))
		self.assertEqual(len(row.api_key_hash), 64)


class TestAraclarYalnizTaslak(ShcOrtam, FrappeTestCase):
	def test_page_create_taslak_uretir_builder_page_acmaz(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("pc")
		once = frappe.db.count("Builder Page")
		with self.mcp_istek(c["key"]):
			out = api.page_create(BASLIK, f"/mcp-{self._sonek()}", meta_description=ACIKLAMA)
		self.assertEqual(frappe.db.count("Builder Page"), once, "ajan doğrudan sayfa AÇAMAZ")
		d = frappe.db.get_value(
			"MCP Draft", out["draft"], ["status", "draft_type", "validation"], as_dict=True
		)
		self.assertEqual((d.status, d.draft_type), ("draft", "page_create"))
		self.assertTrue(out["validation"]["publishable"])
		call = frappe.db.get_value(
			"MCP Tool Call", {"draft": out["draft"]}, ["tool", "result", "duration_ms"], as_dict=True
		)
		self.assertEqual((call.tool, call.result), ("page_create", "ok"))

	def test_deterministik_dogrulama_taslaga_islenir_ve_onayi_engeller(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("val")
		with self.mcp_istek(c["key"]):
			out = api.page_create("kısa", f"/mcp-v-{self._sonek()}", meta_description="x")
		self.assertFalse(out["validation"]["publishable"])
		self.assertIn("TITLE_SHORT", [f["code"] for f in out["validation"]["findings"]])
		frappe.set_user("Administrator")
		with self.assertRaises(frappe.ValidationError):
			api.approve_draft(out["draft"])

	def test_block_add_script_reddeder_ve_hatayi_gunluge_yazar(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("blk")
		bp = self._builder_page("blk")
		with self.mcp_istek(c["key"]), self.assertRaises(frappe.ValidationError):
			api.block_add(bp, {"element": "div", "innerHTML": "<script>alert(1)</script>"})
		self.assertEqual(
			frappe.db.get_value("MCP Tool Call", {"client": c["name"], "tool": "block_add"}, "result"),
			"error",
		)

	def test_metadata_suggest_openai_mock_kota_maliyet(self):
		from tradehub_core.seo_helper.mcp import api, openai_client

		c = self._mcp_client("meta", budget=1000)
		bp = self._builder_page("meta")
		cevap = SimpleNamespace(
			status_code=200,
			text="",
			json=lambda: {
				"usage": {"input_tokens": 120, "output_tokens": 40},
				"output": [
					{
						"content": [
							{
								"type": "output_text",
								"text": json.dumps({"title": BASLIK, "meta_description": ACIKLAMA}),
							}
						]
					}
				],
			},
		)
		with (
			patch.dict(frappe.local.conf, {"openai_api_key": "sk-test"}),
			patch.object(openai_client.requests, "post", return_value=cevap) as post,
			self.mcp_istek(c["key"]),
		):
			out = api.metadata_suggest(builder_page=bp, content="içerik")
		self.assertEqual(post.call_args.kwargs["timeout"], 60)
		self.assertEqual(out["suggestion"]["title"], BASLIK)
		call = frappe.db.get_value(
			"MCP Tool Call",
			{"draft": out["draft"]},
			["cost_tokens_in", "cost_tokens_out", "cost_usd"],
			as_dict=True,
		)
		self.assertEqual((call.cost_tokens_in, call.cost_tokens_out), (120, 40))
		self.assertGreater(call.cost_usd, 0)
		self.assertEqual(frappe.db.get_value("MCP Client", c["name"], "tokens_used_month"), 160)
		# kota dolunca 429
		frappe.db.set_value("MCP Client", c["name"], "tokens_used_month", 1000)
		with self.mcp_istek(c["key"]):
			from tradehub_core.api.rate_limit import TooManyRequestsError

			with self.assertRaises(TooManyRequestsError):
				api.metadata_suggest(builder_page=bp, content="içerik")

	def test_openai_zaman_asimi_tekrar_deneme(self):
		import requests

		from tradehub_core.seo_helper.mcp import openai_client

		c = self._mcp_client("retry")
		ok = SimpleNamespace(
			status_code=200,
			text="",
			json=lambda: {"usage": {"input_tokens": 1, "output_tokens": 1}, "output": []},
		)
		with (
			patch.dict(frappe.local.conf, {"openai_api_key": "sk-test"}),
			patch.object(openai_client.time, "sleep"),
		):
			post = patch.object(
				openai_client.requests,
				"post",
				side_effect=[requests.Timeout("t"), SimpleNamespace(status_code=503, text="", json=dict), ok],
			).start()
			self.addCleanup(patch.stopall)
			r = openai_client.complete(
				"p", client=frappe._dict(name=c["name"], monthly_token_budget=0, tokens_used_month=0)
			)
		self.assertEqual((r["attempts"], post.call_count), (3, 3))
		with (
			patch.dict(frappe.local.conf, {"openai_api_key": "sk-test"}),
			patch.object(openai_client.time, "sleep"),
			patch.object(openai_client.requests, "post", side_effect=requests.Timeout("t")),
		):
			with self.assertRaises(frappe.ValidationError):
				openai_client.complete("p", client=None)

	def test_audit_ayri_kuyrukta_ve_sonuc_okunur(self):
		from tradehub_core.seo_helper.core import queue as q
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("audit")
		p = self._seo_page("audit", title="kısa")
		with patch("frappe.enqueue") as enq, self.mcp_istek(c["key"]):
			out = api.seo_audit_run(routes=[frappe.db.get_value("SEO Page", p, "route")])
		self.assertEqual(enq.call_args.kwargs["queue"], "mcp")
		self.addCleanup(lambda: self._drop("SEO Crawl Run", out["crawl_run"]))
		self.addCleanup(lambda: self._drop("SEO Sync Job", out["job"]))
		self.addCleanup(lambda: frappe.db.delete("SEO Audit Finding", {"crawl_run": out["crawl_run"]}))
		q.run_job(out["job"])
		with self.mcp_istek(c["key"]):
			r = api.result_read(crawl_run=out["crawl_run"])
		self.assertEqual(r["run"]["status"], "done")
		self.assertIn("TITLE_SHORT", [f["code"] for f in r["findings"]])


class TestInsanOnayi(ShcOrtam, FrappeTestCase):
	def test_onay_taslagi_uygular_ama_yayinlamaz(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("onay")
		route = f"/mcp-onay-{self._sonek()}"
		with self.mcp_istek(c["key"]):
			out = api.page_create(BASLIK, route, meta_description=ACIKLAMA)
		frappe.set_user("Administrator")
		r = api.approve_draft(out["draft"], "uygun")
		self.addCleanup(lambda: self._drop_builder_page(r["target"]))
		bp = frappe.db.get_value(
			"Builder Page", r["target"], ["published", "page_title", "route"], as_dict=True
		)
		self.assertEqual((bp.published, bp.page_title, bp.route), (0, BASLIK, route.strip("/")))
		self.assertEqual(
			frappe.db.get_value("MCP Draft", out["draft"], ["status", "reviewed_by"], as_dict=True),
			{"status": "applied", "reviewed_by": "Administrator"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.approve_draft(out["draft"])

	def test_red_ve_baska_magaza_onaylayamaz(self):
		from tradehub_core.seo_helper.mcp import api
		from tradehub_core.tests.mogem620_ortak import kullanici

		s1, _ = self._seller("o1")
		_s2, u2 = self._seller("o2")
		c = self._mcp_client("red", store=s1)
		with self.mcp_istek(c["key"]):
			out = api.page_create(BASLIK, f"/mcp-red-{self._sonek()}", meta_description=ACIKLAMA)
		with kullanici(u2), self.assertRaises(frappe.PermissionError):
			api.reject_draft(out["draft"])
		frappe.set_user("Administrator")
		api.reject_draft(out["draft"], "olmaz")
		self.assertEqual(frappe.db.get_value("MCP Draft", out["draft"], "status"), "rejected")


class TestMagazaIzolasyonu(ShcOrtam, FrappeTestCase):
	"""Kod incelemesi bulgusu: yazma araçları hedef sayfanın GERÇEK mağazasını doğrulamalı (1.4)."""

	def _magaza_sayfasi(self, tag, store):
		bp = self._builder_page(tag)
		frappe.db.set_value("SEO Page", {"builder_page": bp}, "store", store)
		frappe.db.commit()
		return bp

	def test_baska_magazanin_sayfasina_blok_eklenemez(self):
		from tradehub_core.seo_helper.mcp import api

		s1, _ = self._seller("i1")
		s2, _ = self._seller("i2")
		bp_b = self._magaza_sayfasi("izo", s2)
		c = self._mcp_client("izo", store=s1)
		for arac, args in (
			("block_add", dict(builder_page=bp_b, block={"element": "p", "innerHTML": "x"})),
			("page_update", dict(builder_page=bp_b, changes={"title": BASLIK})),
			("translation_draft", dict(builder_page=bp_b, target_lang="en")),
			("metadata_suggest", dict(builder_page=bp_b, content="x")),
		):
			with self.mcp_istek(c["key"]), self.assertRaises(frappe.PermissionError, msg=arac):
				getattr(api, arac)(**args)
		self.assertEqual(frappe.db.count("MCP Draft", {"client": c["name"]}), 0)
		self.assertEqual(
			frappe.db.count("MCP Tool Call", {"client": c["name"], "result": "denied"}),
			4,
			"reddedilen çağrı günlükte",
		)

	def test_magaza_istemcisi_platform_sayfasina_dokunamaz(self):
		from tradehub_core.seo_helper.mcp import api

		s1, _ = self._seller("p1")
		bp_platform = self._builder_page("plat")  # store=None
		c = self._mcp_client("plat", store=s1)
		with self.mcp_istek(c["key"]), self.assertRaises(frappe.PermissionError):
			api.block_add(bp_platform, {"element": "p"})

	def test_platform_taslagini_satici_onaylayamaz(self):
		from tradehub_core.seo_helper.mcp import api
		from tradehub_core.tests.mogem620_ortak import kullanici

		_s1, u1 = self._seller("po")
		c = self._mcp_client("po")  # platform istemcisi
		with self.mcp_istek(c["key"]):
			out = api.page_create(BASLIK, f"/mcp-po-{self._sonek()}", meta_description=ACIKLAMA)
		with kullanici(u1), self.assertRaises(frappe.PermissionError):
			api.approve_draft(out["draft"])
		with kullanici(u1), self.assertRaises(frappe.PermissionError):
			api.reject_draft(out["draft"])
		self.assertEqual(frappe.db.get_value("MCP Draft", out["draft"], "status"), "draft")

	def test_taslak_hedefin_gercek_magazasiyla_damgalanir(self):
		from tradehub_core.seo_helper.mcp import api

		s1, _ = self._seller("d1")
		bp = self._magaza_sayfasi("damga", s1)
		c = self._mcp_client("damga")  # platform istemcisi, store vermeden
		with self.mcp_istek(c["key"]):
			out = api.block_add(bp, {"element": "p", "innerHTML": "x"})
		self.assertEqual(frappe.db.get_value("MCP Draft", out["draft"], "store"), s1)


class TestTipsizArgumanlar(ShcOrtam, FrappeTestCase):
	"""Monkey bulgusu: eksik/tipsiz/bozuk argümanlar 500 (TypeError/JSONDecodeError) değil,
	ValidationError (417) + günlükte 'error' olmalı; alan listesi sorguya beyaz listeden gider."""

	def test_bozuk_argumanlar_validation_error(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("tipsiz")
		bp = self._builder_page("tipsiz")
		durumlar = [
			("page_create", {}),
			("page_create", {"title": ["x"], "route": {"a": 1}}),
			("page_create", {"title": BASLIK, "route": "kötü yol<script>"}),
			("page_create", {"title": BASLIK, "route": "/ok", "blocks": "{bozuk json"}),
			("page_update", {"builder_page": bp, "changes": "[1,2]"}),
			("block_add", {"builder_page": bp, "block": 12}),
			("block_add", {"builder_page": bp, "block": {"element": "p"}, "position": "abc"}),
			("translation_draft", {"builder_page": bp, "target_lang": "en", "fields": ["name; drop table"]}),
			("translation_draft", {"builder_page": bp}),
			("seo_audit_run", {"routes": "not json"}),
			("seo_audit_run", {"routes": [{"a": 1}, "x\x00y"]}),
			("result_read", {"crawl_run": ["liste"]}),
		]
		for arac, args in durumlar:
			with self.mcp_istek(c["key"]):
				with self.assertRaises(frappe.ValidationError, msg=f"{arac} {args}"):
					getattr(api, arac)(**args)
		self.assertGreaterEqual(
			frappe.db.count("MCP Tool Call", {"client": c["name"], "result": "error"}), len(durumlar) - 1
		)
		self.assertEqual(frappe.db.count("MCP Draft", {"client": c["name"]}), 0)

	def test_gecerli_string_json_kabul(self):
		from tradehub_core.seo_helper.mcp import api

		c = self._mcp_client("strjson")
		with self.mcp_istek(c["key"]):
			out = api.page_create(BASLIK, f"mcp-sj-{self._sonek()}", meta_description=ACIKLAMA, blocks="[]")
		self.assertTrue(out["validation"]["publishable"])


class TestOperasyon(ShcOrtam, FrappeTestCase):
	def test_anahtar_olustur_rotasyon_kapat(self):
		from tradehub_core.seo_helper.mcp import auth, ops

		frappe.set_user("Administrator")
		r = ops.create_client(f"shc-ops-{self._sonek()}")
		self.addCleanup(lambda: self._drop("MCP Client", r["client"]))
		self.assertTrue(auth.client_for_key(r["api_key"]))
		r2 = ops.rotate_key(r["client"])
		self.assertIsNone(auth.client_for_key(r["api_key"]), "eski anahtar anında ölür")
		self.assertTrue(auth.client_for_key(r2["api_key"]))
		ops.disable_client(r["client"])
		self.assertIsNone(auth.client_for_key(r2["api_key"]))

	def test_gunluk_saklama_ve_aylik_sifirlama(self):
		from tradehub_core.seo_helper.mcp import ops

		c = self._mcp_client("saklama")
		frappe.db.set_value("MCP Client", c["name"], {"tokens_used_month": 5, "calls_month": 2})
		eski = frappe.get_doc(
			{"doctype": "MCP Tool Call", "client": c["name"], "tool": "x", "result": "ok"}
		).insert(ignore_permissions=True)
		frappe.db.set_value(
			"MCP Tool Call",
			eski.name,
			"creation",
			frappe.utils.add_to_date(frappe.utils.now_datetime(), days=-400),
			update_modified=False,
		)
		yeni = frappe.get_doc(
			{"doctype": "MCP Tool Call", "client": c["name"], "tool": "x", "result": "ok"}
		).insert(ignore_permissions=True)
		r = ops.purge_tool_call_log()
		self.assertGreaterEqual(r["purged"], 1)
		self.assertFalse(frappe.db.exists("MCP Tool Call", eski.name))
		self.assertTrue(frappe.db.exists("MCP Tool Call", yeni.name))
		ops.reset_monthly_quotas()
		self.assertEqual(frappe.db.get_value("MCP Client", c["name"], "tokens_used_month"), 0)
		snap = ops.daily_cost_snapshot()
		self.assertIn("month_usd", snap)

	def test_mcp_sunucu_arac_seti_gorev_metniyle_ayni(self):
		from tradehub_core.seo_helper.mcp import api, server

		beklenen = {
			"page_create",
			"page_update",
			"block_add",
			"metadata_suggest",
			"translation_draft",
			"seo_audit_run",
			"result_read",
		}
		self.assertEqual(set(server.TOOLS), beklenen)
		for t in beklenen:
			self.assertTrue(callable(getattr(api, t)), t)
			self.assertTrue(
				getattr(api, t).__dict__.get("whitelisted", getattr(getattr(api, t), "is_whitelisted", True))
			)
