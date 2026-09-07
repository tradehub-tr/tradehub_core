"""Sosyal kanıt — toplu uç (get_signals_batch) tekil uçla (get_signals) BİREBİR aynı olmalı.

Liste sayfası yalnız toplu ucu kullanır. Tekil uçtaki "Yeni ürün" yedek rozeti
(eşik geçen sinyal yokken, new_badge_enabled + max_age kuralı) toplu uçta eksik
kalırsa kart ızgarası hiç rozet göstermez; iki uç paylaşımlı per-listing cache
yazdığı için tekil uç da boş sonucu devralır. Bu test o denkliği sabitler.
"""

from __future__ import annotations

import frappe
from frappe.tests.utils import FrappeTestCase

from tradehub_core.api import social_proof
from tradehub_core.api.social_proof import _RESPONSE_CACHE_PREFIX, get_signals, get_signals_batch


def _sample_ids(limit=5):
	return frappe.get_all(
		"Listing",
		filters={"storefront_visible": 1, "status": "Active"},
		pluck="name",
		limit_page_length=limit,
		order_by="creation desc",
	)


def _clear(ids):
	for lid in ids:
		frappe.cache().delete_value(f"{_RESPONSE_CACHE_PREFIX}{lid}")


class TestSocialProofBatchFallback(FrappeTestCase):
	def setUp(self):
		self.ids = _sample_ids()
		self.assertTrue(self.ids, "Aktif vitrin ilanı yok — test verisi gerekli")
		_clear(self.ids)
		# Varsayılan ayar: yeni-ürün rozeti açık, yaş sınırı 0 (sinyalsiz her ürün "yeni")
		frappe.cache().delete_value(social_proof._SETTINGS_CACHE_KEY)

	def tearDown(self):
		_clear(self.ids)

	def test_batch_equals_single_for_every_listing(self):
		batch = get_signals_batch(",".join(self.ids))
		_clear(self.ids)  # tekil uç kendi hesaplasın, toplu ucun cache'ini devralmasın
		for lid in self.ids:
			self.assertEqual(batch[lid], get_signals(lid), f"{lid}: toplu ≠ tekil")

	def test_batch_gives_new_badge_when_no_signal_passes(self):
		settings = social_proof._get_settings()
		if not settings["new_badge_enabled"]:
			self.skipTest("new_badge kapalı")
		batch = get_signals_batch(",".join(self.ids))
		for lid in self.ids:
			sig = batch[lid]["signals"]
			self.assertTrue(sig, f"{lid}: sinyal listesi boş — 'new' yedek rozeti eksik")
			if len(sig) == 1:
				self.assertIn(sig[0]["type"], {"new", "sales", "favorites", "cart_now", "views_24h", "distinct_buyers", "seller_orders"})
			types = {s["type"] for s in sig}
			# 'new' yalnız gerçek sinyal yokken; gerçek sinyal varken 'new' olmamalı
			self.assertTrue(("new" in types) != bool(types - {"new"}), f"{lid}: {types}")
