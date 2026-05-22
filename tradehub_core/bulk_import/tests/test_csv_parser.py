"""csv_parser standalone testleri."""

import os
import tempfile
import unittest

from tradehub_core.bulk_import.parsers import csv_parser


class TestCsvParser(unittest.TestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()
		self.csv_path = os.path.join(self.tmpdir, "test.csv")

	def tearDown(self):
		import shutil

		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def _write(self, content_bytes):
		with open(self.csv_path, "wb") as f:
			f.write(content_bytes)

	def test_comma_delimiter(self):
		self._write(b"sku,name\nABC-001,Solvent\n")
		headers, rows = csv_parser.parse_csv(self.csv_path)
		self.assertEqual(headers, ["sku", "name"])
		self.assertEqual(rows[0]["sku"], "ABC-001")

	def test_semicolon_delimiter(self):
		self._write(b"sku;name\nABC-001;Solvent\n")
		_h, rows = csv_parser.parse_csv(self.csv_path)
		self.assertEqual(rows[0]["sku"], "ABC-001")

	def test_utf8_bom(self):
		bom = b"\xef\xbb\xbf"
		self._write(bom + "ad,fiyat\nÜrün,100\n".encode())
		headers, rows = csv_parser.parse_csv(self.csv_path)
		# BOM stripped — header "ad" olmalı (BOM karakteri kalmamalı)
		self.assertNotIn("﻿", headers[0])
		self.assertEqual(rows[0]["ad"], "Ürün")

	def test_skip_blank_rows(self):
		self._write(b"a,b\nx,y\n,\np,q\n")
		_h, rows = csv_parser.parse_csv(self.csv_path)
		self.assertEqual(len(rows), 2)


if __name__ == "__main__":
	unittest.main()
