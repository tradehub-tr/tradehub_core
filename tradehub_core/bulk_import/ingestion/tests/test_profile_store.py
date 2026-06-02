"""Seller Template Profile testleri — fingerprint deterministic."""

import unittest

from tradehub_core.bulk_import.ingestion import profile_store


class TestFingerprint(unittest.TestCase):
	def test_same_headers_same_seller_same_fingerprint(self):
		fp1 = profile_store.compute_fingerprint(["sku", "name", "price"], "SP-001")
		fp2 = profile_store.compute_fingerprint(["sku", "name", "price"], "SP-001")
		self.assertEqual(fp1, fp2)

	def test_reordered_headers_same_fingerprint(self):
		fp1 = profile_store.compute_fingerprint(["sku", "name", "price"], "SP-001")
		fp2 = profile_store.compute_fingerprint(["price", "sku", "name"], "SP-001")
		self.assertEqual(fp1, fp2)

	def test_different_sellers_different_fingerprint(self):
		fp1 = profile_store.compute_fingerprint(["sku", "name"], "SP-001")
		fp2 = profile_store.compute_fingerprint(["sku", "name"], "SP-002")
		self.assertNotEqual(fp1, fp2)

	def test_case_normalize(self):
		fp1 = profile_store.compute_fingerprint(["SKU", "Name"], "SP-001")
		fp2 = profile_store.compute_fingerprint(["sku", "name"], "SP-001")
		self.assertEqual(fp1, fp2)


if __name__ == "__main__":
	unittest.main()
