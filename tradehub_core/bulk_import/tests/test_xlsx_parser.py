"""xlsx_parser standalone testleri."""

import os
import tempfile
import unittest

try:
	from openpyxl import Workbook

	HAS_OPENPYXL = True
except ImportError:
	HAS_OPENPYXL = False

from tradehub_core.bulk_import.parsers import xlsx_parser


@unittest.skipUnless(HAS_OPENPYXL, "openpyxl not installed")
class TestXlsxParser(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()
		self.xlsx_path = os.path.join(self.tmpdir, "test.xlsx")

	def tearDown(self):
		import shutil

		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def _create_xlsx(self, rows):
		wb = Workbook()
		ws = wb.active
		for row in rows:
			ws.append(row)
		wb.save(self.xlsx_path)

	def test_parse_basic(self):
		self._create_xlsx(
			[
				["Stok Kodu", "Ürün Adı", "Fiyat"],
				["ABC-001", "Solvent", 100],
				["ABC-002", "Tiner", 200],
			]
		)
		headers, rows = xlsx_parser.parse_xlsx(self.xlsx_path)
		self.assertEqual(headers, ["Stok Kodu", "Ürün Adı", "Fiyat"])
		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["Stok Kodu"], "ABC-001")
		self.assertEqual(rows[0]["Fiyat"], 100)

	def test_skip_empty_rows(self):
		self._create_xlsx(
			[
				["A", "B"],
				["x", "y"],
				[None, None],
				["a", "b"],
			]
		)
		_h, rows = xlsx_parser.parse_xlsx(self.xlsx_path)
		self.assertEqual(len(rows), 2)

	def test_custom_header_row(self):
		self._create_xlsx(
			[
				["Title row"],
				["Subtitle"],
				["A", "B"],
				["x", "y"],
			]
		)
		headers, rows = xlsx_parser.parse_xlsx(self.xlsx_path, header_row=3)
		self.assertEqual(headers, ["A", "B"])
		self.assertEqual(len(rows), 1)

	def test_list_sheets(self):
		self._create_xlsx([["a"]])
		sheets = xlsx_parser.list_sheets(self.xlsx_path)
		self.assertGreaterEqual(len(sheets), 1)


if __name__ == "__main__":
	unittest.main()
