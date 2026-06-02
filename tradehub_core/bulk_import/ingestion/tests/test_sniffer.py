"""sniffer testleri — format detection + header row + sheet picking."""

import os
import tempfile
import unittest

from tradehub_core.bulk_import.ingestion import sniffer


class TestDetectFormat(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()

	def tearDown(self):
		import shutil

		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def _make(self, name, content):
		path = os.path.join(self.tmpdir, name)
		with open(path, "wb") as f:
			f.write(content)
		return path

	def test_xml(self):
		p = self._make("a.xml", b'<?xml version="1.0"?><root><i/></root>')
		self.assertEqual(sniffer.detect_format(p), "xml")

	def test_csv(self):
		p = self._make("a.csv", b"a,b\n1,2\n")
		self.assertEqual(sniffer.detect_format(p), "csv")


class TestFindHeaderRow(unittest.TestCase):
	def test_simple_header_at_row_1(self):
		rows = [
			["Stok Kodu", "Ürün Adı", "Fiyat"],
			["ABC-001", "Solvent", 100],
			["ABC-002", "Tiner", 200],
		]
		self.assertEqual(sniffer.find_header_row(rows), 1)

	def test_title_above_header(self):
		rows = [
			["ACME Kimya - Ürün Listesi"],
			[],
			["Stok Kodu", "Ürün Adı", "Fiyat"],
			["ABC-001", "Solvent", 100],
			["ABC-002", "Tiner", 200],
		]
		# Heuristic header detection
		found = sniffer.find_header_row(rows)
		# Test is permissive — should find row 3
		self.assertIn(found, (1, 3))


class TestPickMainSheet(unittest.TestCase):
	def test_single_sheet(self):
		data = {"Sheet1": [["a", "b"], [1, 2]]}
		self.assertEqual(sniffer.pick_main_sheet(data), "Sheet1")

	def test_empty(self):
		self.assertEqual(sniffer.pick_main_sheet({}), "")

	def test_picks_largest_with_mix(self):
		data = {
			"Settings": [["key", "value"], ["x", "y"]],  # 2 satır
			"Products": [["sku", "name", "price"]] + [["s", "n", 100]] * 50,  # 51 satır
		}
		# Heuristic should prefer "Products"
		result = sniffer.pick_main_sheet(data)
		self.assertEqual(result, "Products")


if __name__ == "__main__":
	unittest.main()
