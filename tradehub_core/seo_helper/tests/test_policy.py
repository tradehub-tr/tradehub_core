"""Politika motoru — saf birim testleri (Frappe'siz). 11.4 deterministik kurallar."""

from __future__ import annotations

import unittest

from tradehub_core.seo_helper.core.policy import PUBLISH_STATES, evaluate

SITE = "https://istoc.example.com"
P = {
	"default_robots": "index,follow",
	"canonical_strategy": "self",
	"min_title_len": 10,
	"min_desc_len": 50,
	"index_requires_published": 1,
	"block_ugc_html": 1,
}


def _page(**kw):
	base = {
		"route": "/kampanya",
		"slug": "kampanya",
		"lang": "tr",
		"title": "Toptan kampanya sayfası başlığı",
		"meta_description": "x" * 60,
		"publish_state": "published",
	}
	base.update(kw)
	return base


class TestCanonical(unittest.TestCase):
	def test_self_canonical_route_tan(self):
		k = evaluate(_page(), P, site_url=SITE)
		self.assertEqual(k.canonical_url, f"{SITE}/kampanya")

	def test_override_goreli_yol_hosta_sabitlenir(self):
		k = evaluate(_page(canonical_url="/ozel"), P, site_url=SITE)
		self.assertEqual(k.canonical_url, f"{SITE}/ozel")

	def test_yanlis_host_kanonik_hosta_cekilir(self):
		k = evaluate(_page(canonical_url="https://www.baska.com/yol?x=1"), P, site_url=SITE)
		self.assertEqual(k.canonical_url, f"{SITE}/yol")
		self.assertIn("CANONICAL_HOST", [f["code"] for f in k.findings])

	def test_builder_canonical_girdi_olur(self):
		k = evaluate(_page(builder_meta={"canonical_url": f"{SITE}/builder-c"}), P, site_url=SITE)
		self.assertEqual(k.canonical_url, f"{SITE}/builder-c")


class TestRobots(unittest.TestCase):
	def test_yayinda_index(self):
		self.assertTrue(evaluate(_page(), P, site_url=SITE).indexable)

	def test_taslak_noindex(self):
		k = evaluate(_page(publish_state="draft"), P, site_url=SITE)
		self.assertEqual(k.robots, "noindex,follow")
		self.assertFalse(k.indexable)

	def test_prod_disi_noindex_nofollow(self):
		k = evaluate(_page(), P, site_url=SITE, env_prod=False)
		self.assertEqual(k.robots, "noindex,nofollow")
		self.assertFalse(k.indexable)

	def test_builder_disable_indexing_kazanir(self):
		k = evaluate(_page(builder_meta={"disable_indexing": 1}), P, site_url=SITE)
		self.assertEqual(k.robots, "noindex,follow")

	def test_gecersiz_robots_guvenli_tarafa(self):
		k = evaluate(_page(robots="index, everything"), P, site_url=SITE)
		self.assertEqual(k.robots, "noindex,follow")
		self.assertIn("ROBOTS_INVALID", [f["code"] for f in k.findings])


class TestDeterministikKurallar(unittest.TestCase):
	def test_kisa_baslik_yayinlanamaz(self):
		k = evaluate(_page(title="kısa"), P, site_url=SITE)
		self.assertFalse(k.publishable)
		self.assertIn("TITLE_SHORT", [f["code"] for f in k.findings])

	def test_bos_baslik(self):
		self.assertIn(
			"TITLE_MISSING", [f["code"] for f in evaluate(_page(title=""), P, site_url=SITE).findings]
		)

	def test_kisa_aciklama(self):
		self.assertIn(
			"DESC_SHORT",
			[f["code"] for f in evaluate(_page(meta_description="x"), P, site_url=SITE).findings],
		)

	def test_ugc_html_yayina_cikamaz(self):
		k = evaluate(_page(has_ugc_html=True), P, site_url=SITE)
		self.assertFalse(k.publishable)
		self.assertIn("UGC_HTML", [f["code"] for f in k.findings])

	def test_uzunluk_kurali_uyari_yayini_durdurmaz(self):
		k = evaluate(_page(), P, site_url=SITE, length_check=lambda t, d: ["Başlık 60'ı aşıyor"])
		self.assertTrue(k.publishable)
		self.assertEqual([f["severity"] for f in k.findings], ["warning"])

	def test_bilinmeyen_durum_taslaga_duser(self):
		k = evaluate(_page(publish_state="yayinda"), P, site_url=SITE)
		self.assertIn("STATE_INVALID", [f["code"] for f in k.findings])
		self.assertFalse(k.indexable)

	def test_durum_kumesi_7_4_ile_ayni(self):
		self.assertEqual(
			PUBLISH_STATES, ("draft", "review", "approved", "scheduled", "published", "suspended", "archived")
		)

	def test_politikasiz_calisir(self):
		k = evaluate(_page(), None, site_url=SITE)
		self.assertTrue(k.publishable)
		self.assertEqual(k.robots, "index,follow")


class TestGuvenilmeyenGirdi(unittest.TestCase):
	"""MCP gövdesi tipsizdir: liste/sözlük/sayı/None gelse de motor exception atmaz, sözleşme korunur."""

	def test_tipsiz_girdi_sozlesmeyi_bozmaz(self):
		bozuk = [None, "", 0, 1, -1, 2**40, 1.5, True, [], {}, [1, "a"], {"a": 1}, "\x00", "🙂"]
		import itertools

		for combo in itertools.islice(itertools.product(bozuk, repeat=3), 0, None, 7):
			page = {
				"route": combo[0],
				"title": combo[1],
				"meta_description": combo[2],
				"canonical_url": combo[1],
				"robots": combo[2],
				"publish_state": combo[0],
				"has_ugc_html": combo[1],
				"builder_meta": combo[2],
			}
			k = evaluate(page, {k: combo[0] for k in P}, site_url=SITE)
			self.assertTrue(k.canonical_url.startswith(SITE), k.canonical_url)
			self.assertIn(k.robots, ("index,follow", "noindex,follow", "noindex,nofollow", "index,nofollow"))
			if not k.publishable:
				self.assertTrue(any(f["severity"] == "error" for f in k.findings))

	def test_policy_ve_page_sozluk_degilse(self):
		k = evaluate("bozuk", ["bozuk"], site_url=SITE)
		self.assertEqual(k.canonical_url, f"{SITE}/")
		self.assertFalse(k.publishable)
