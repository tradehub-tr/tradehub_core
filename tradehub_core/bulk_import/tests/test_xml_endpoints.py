"""XML schema discovery + mapping save endpoint testleri."""

import os
import tempfile
import unittest

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False


SAMPLE_XML = (
	'<?xml version="1.0" encoding="UTF-8"?>\n'
	"<urunler>\n"
	"  <urun>\n"
	"    <kod>ABC-001</kod>\n"
	"    <adi>Çelik Cıvata</adi>\n"
	"    <fiyat>12.50</fiyat>\n"
	"  </urun>\n"
	"  <urun>\n"
	"    <kod>XYZ-002</kod>\n"
	"    <adi>Plastik Somun</adi>\n"
	"    <fiyat>3.75</fiyat>\n"
	"  </urun>\n"
	"</urunler>\n"
)


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestXmlEndpoints(FrappeTestCase):
	def test_discover_returns_tags(self):
		"""XML parse → tag yolları + örnek değerleri döner."""
		# Standalone parser smoke test — endpoint katmanı Frappe File DocType
		# gerektirir; full e2e için fixture ayrıca yazılmalı.
		from tradehub_core.bulk_import.parsers import xml_parser

		tmpdir = tempfile.mkdtemp()
		try:
			xml_path = os.path.join(tmpdir, "sample.xml")
			with open(xml_path, "w", encoding="utf-8") as f:
				f.write(SAMPLE_XML)
			headers, rows = xml_parser.parse_xml(xml_path)
			self.assertIn("kod", headers)
			self.assertIn("adi", headers)
			self.assertIn("fiyat", headers)
			self.assertEqual(len(rows), 2)
			self.assertEqual(rows[0]["kod"], "ABC-001")
		finally:
			import shutil

			shutil.rmtree(tmpdir, ignore_errors=True)


if __name__ == "__main__":
	unittest.main()
