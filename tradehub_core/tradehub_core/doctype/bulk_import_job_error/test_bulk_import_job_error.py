# Copyright (c) 2026, TradeHub Team and contributors

import unittest

import frappe


class TestBulkImportJobError(unittest.TestCase):
	def test_child_row_attaches_to_parent(self):
		# Child DocType test'i: parent Bulk Import Job içinden append edilir.
		from tradehub_core.tradehub_core.doctype.bulk_import_job.test_bulk_import_job import (
			_ensure_seller,
		)

		seller = _ensure_seller()
		parent = frappe.get_doc(
			{
				"doctype": "Bulk Import Job",
				"seller_profile": seller,
				"data_file": "/files/test.csv",
				"file_format": "csv",
				"error_details": [
					{
						"row_number": 3,
						"sku": "SKU-ERR-1",
						"error_type": "validation",
						"error_message": "Fiyat negatif",
					}
				],
			}
		).insert(ignore_permissions=True)
		self.assertEqual(len(parent.error_details), 1)
		self.assertEqual(parent.error_details[0].row_number, 3)
		parent.delete(ignore_permissions=True)

	def test_missing_message_raises(self):
		from tradehub_core.tradehub_core.doctype.bulk_import_job.test_bulk_import_job import (
			_ensure_seller,
		)

		seller = _ensure_seller()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(
				{
					"doctype": "Bulk Import Job",
					"seller_profile": seller,
					"data_file": "/files/test.csv",
					"file_format": "csv",
					"error_details": [
						{
							"row_number": 5,
							"error_type": "system",
						}
					],
				}
			).insert(ignore_permissions=True)
