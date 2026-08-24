"""MOGEM-573 — tenant medya kota durum sözleşmesinin saf testleri."""

from __future__ import annotations

import unittest

from tradehub_core.media import quota_model as Q


class TenantMediaQuotaModelTests(unittest.TestCase):
	def test_plan_limit_semantigi(self):
		self.assertEqual(Q.resolve_limit_mb(None), (Q.MODE_UNCONFIGURED, None))
		self.assertEqual(Q.resolve_limit_mb(-1), (Q.MODE_UNLIMITED, None))
		self.assertEqual(Q.resolve_limit_mb("500"), (Q.MODE_LIMITED, 500 * Q.MIB))
		with self.assertRaises(ValueError):
			Q.resolve_limit_mb(-2)

	def test_yuzde_80_uyari_esigidir(self):
		limit = 100 * Q.MIB
		alt = Q.summarize(79 * Q.MIB, limit, Q.MODE_LIMITED)
		esik = Q.summarize(80 * Q.MIB, limit, Q.MODE_LIMITED)

		self.assertEqual(alt["quota_state"], Q.STATE_OK)
		self.assertEqual(esik["quota_state"], Q.STATE_WARNING)
		self.assertTrue(esik["is_warning"])
		self.assertEqual(esik["remaining_bytes"], 20 * Q.MIB)

	def test_tam_sinir_tukenmis_ama_asim_degil(self):
		limit = 10 * Q.MIB
		sonuc = Q.summarize(limit, limit, Q.MODE_LIMITED)

		self.assertEqual(sonuc["quota_state"], Q.STATE_EXHAUSTED)
		self.assertTrue(sonuc["is_exhausted"])
		self.assertFalse(sonuc["is_exceeded"])
		self.assertEqual(sonuc["usage_percent"], 100.0)
		self.assertEqual(sonuc["remaining_bytes"], 0)

	def test_asim_yuzdeyi_kirpmaz_ve_fazlayi_raporlar(self):
		limit = 10 * Q.MIB
		sonuc = Q.summarize(12 * Q.MIB, limit, Q.MODE_LIMITED)

		self.assertEqual(sonuc["quota_state"], Q.STATE_EXCEEDED)
		self.assertEqual(sonuc["usage_percent"], 120.0)
		self.assertEqual(sonuc["overage_bytes"], 2 * Q.MIB)

	def test_sinirsiz_ve_tanimsiz_modlar_ayri_raporlanir(self):
		unlimited = Q.summarize(999, None, Q.MODE_UNLIMITED)
		unconfigured = Q.summarize(999, None, Q.MODE_UNCONFIGURED)

		self.assertEqual(unlimited["quota_state"], Q.MODE_UNLIMITED)
		self.assertEqual(unconfigured["quota_state"], Q.MODE_UNCONFIGURED)
		self.assertIsNone(unlimited["usage_percent"])
		self.assertIsNone(unconfigured["remaining_bytes"])

	def test_sifir_limit_yuklemeyi_kapatir(self):
		sonuc = Q.summarize(0, 0, Q.MODE_LIMITED)
		self.assertEqual(sonuc["quota_state"], Q.STATE_EXHAUSTED)
		self.assertTrue(sonuc["is_exhausted"])
		self.assertTrue(Q.would_exceed(0, 1, 0))

	def test_esitlik_gecer_asim_bir_baytta_baslar(self):
		self.assertFalse(Q.would_exceed(90, 10, 100))
		self.assertTrue(Q.would_exceed(90, 11, 100))
		self.assertFalse(Q.would_exceed(10**12, 10**12, None))


if __name__ == "__main__":
	unittest.main()
