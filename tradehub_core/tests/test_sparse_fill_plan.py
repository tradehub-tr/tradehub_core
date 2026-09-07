"""Az sonuç dolgusu — sayfalama planı (saf, DB'siz).

Ürün listeleme sayfasında asıl sonuç SPARSE_FILL_THRESHOLD (50) altındaysa
arkasına "tüm ürünler" eklenir ve sayfalama birleşik liste üzerinden devam eder.
Bu test, sayfa başına "kaç asıl + kaç dolgu, dolgu nereden başlar" planını sabitler.
"""

from __future__ import annotations

import unittest

from tradehub_core.api.listing import SPARSE_FILL_THRESHOLD, _sparse_fill_plan


class TestSparseFillPlan(unittest.TestCase):
	def test_threshold_is_fifty(self):
		self.assertEqual(SPARSE_FILL_THRESHOLD, 50)

	def test_empty_primary_fills_whole_first_page_from_zero(self):
		# 0 asıl sonuç, sayfa 1 (start=0), sayfa 40, sayfada 0 asıl kart
		self.assertEqual(_sparse_fill_plan(0, 0, 40, 0), (0, 40, 0))

	def test_primary_smaller_than_page_fills_remainder(self):
		# 8 asıl, sayfa 1: 8 asıl kart var → 32 dolgu, dolgu 8. indeksten başlar
		self.assertEqual(_sparse_fill_plan(8, 0, 40, 8), (0, 32, 8))

	def test_primary_fills_first_page_completely_no_fill(self):
		# 49 asıl, sayfa 1: 40 asıl kart → dolgu yok
		self.assertEqual(_sparse_fill_plan(49, 0, 40, 40), (0, 0, None))

	def test_second_page_continues_primary_then_fill(self):
		# 49 asıl, sayfa 2 (start=40): 9 asıl kart → 31 dolgu, dolgu offset 0, indeks 9
		self.assertEqual(_sparse_fill_plan(49, 40, 40, 9), (0, 31, 9))

	def test_later_pages_are_pure_fill_with_shifted_offset(self):
		# 8 asıl, sayfa 3 (start=80): 0 asıl kart → 40 dolgu, offset 80-8=72
		self.assertEqual(_sparse_fill_plan(8, 80, 40, 0), (72, 40, 0))
