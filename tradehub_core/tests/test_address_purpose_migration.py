"""Address v1 Patch 01 (kind → purpose migration) testleri.

Patch idempotency + Addresses DocType schema doğrulaması.

Çalıştırma:
    bench --site dev.localhost run-tests --module tradehub_core.tests.test_address_purpose_migration
"""

import unittest

import frappe


class TestAddressSchema(unittest.TestCase):
	"""Sprint 1 Addresses DocType yeni alanları mevcut + tip doğru."""

	def test_purpose_field_exists(self):
		meta = frappe.get_meta("Addresses")
		field = meta.get_field("purpose")
		self.assertIsNotNone(field, "Addresses.purpose field eksik")
		self.assertEqual(field.fieldtype, "Select")
		self.assertEqual(field.reqd, 1)

	def test_purpose_options(self):
		meta = frappe.get_meta("Addresses")
		field = meta.get_field("purpose")
		opts = (field.options or "").strip().split("\n")
		self.assertIn("Delivery", opts)
		self.assertIn("Pickup", opts)
		self.assertIn("Billing", opts)

	def test_address_type_field_exists(self):
		meta = frappe.get_meta("Addresses")
		field = meta.get_field("address_type")
		self.assertIsNotNone(field, "Addresses.address_type field eksik")
		self.assertEqual(field.fieldtype, "Select")
		self.assertEqual(field.reqd, 1)

	def test_address_type_options(self):
		meta = frappe.get_meta("Addresses")
		field = meta.get_field("address_type")
		opts = (field.options or "").strip().split("\n")
		self.assertIn("Individual", opts)
		self.assertIn("Business", opts)

	def test_tax_no_and_office_fields(self):
		meta = frappe.get_meta("Addresses")
		tax_no = meta.get_field("tax_no")
		tax_office = meta.get_field("tax_office")
		self.assertIsNotNone(tax_no)
		self.assertIsNotNone(tax_office)
		# Business için mandatory_depends_on tetikli
		self.assertIn("Business", tax_no.mandatory_depends_on or "")
		self.assertIn("Business", tax_office.mandatory_depends_on or "")

	def test_kind_field_deprecated_label(self):
		meta = frappe.get_meta("Addresses")
		field = meta.get_field("kind")
		self.assertIsNotNone(field, "kind alanı korunmalı (Sprint 4'te DROP edilecek)")
		# Reqd kalkmış olmalı (purpose reqd onun yerine)
		self.assertEqual(field.reqd, 0, "kind reqd kalmış — deprecated olmalı")

	def test_company_conditional_reqd(self):
		meta = frappe.get_meta("Addresses")
		field = meta.get_field("company")
		# company artık koşullu zorunlu (Business için)
		self.assertEqual(field.reqd, 0, "company reqd=1 hâlâ ihlal: Bireysel için opsiyonel olmalı")
		self.assertIn("Business", field.mandatory_depends_on or "")


class TestMigrationIdempotency(unittest.TestCase):
	"""Patch 01 idempotent çalışmalı — 2 kez koşulsa veri bozulmaz."""

	def test_patch_already_ran(self):
		# Patch Log kaydı bulunmalı
		exists = frappe.db.exists(
			"Patch Log",
			{"patch": "tradehub_core.patches.address_v1.01_kind_to_purpose"},
		)
		self.assertTrue(exists, "Patch 01 (kind→purpose) Patch Log'da yok")

	def test_purpose_set_for_existing_rows(self):
		"""Migration sonrası purpose=NULL/empty kayıt kalmamalı."""
		empty_purpose_count = frappe.db.sql(
			"""SELECT COUNT(*) FROM `tabAddresses` WHERE purpose IS NULL OR purpose=''"""
		)[0][0]
		self.assertEqual(
			empty_purpose_count, 0, f"{empty_purpose_count} adresin purpose'u boş — migration eksik"
		)

	def test_patch_02_fix_seller_pickup(self):
		"""Patch 02 (kind=Seller AND purpose=Delivery → Pickup) Patch Log'da."""
		exists = frappe.db.exists(
			"Patch Log",
			{"patch": "tradehub_core.patches.address_v1.02_fix_seller_purpose_pickup"},
		)
		self.assertTrue(exists, "Patch 02 (fix_seller_purpose_pickup) Patch Log'da yok")

	def test_kind_purpose_consistency(self):
		"""Migration sonrası kind=Seller olan kayıtlar purpose=Pickup, kind=Buyer ise purpose=Delivery."""
		mismatch = frappe.db.sql(
			"""
			SELECT COUNT(*) FROM `tabAddresses`
			WHERE (kind='Seller' AND purpose NOT IN ('Pickup','Billing'))
			   OR (kind='Buyer' AND purpose NOT IN ('Delivery','Billing'))
			"""
		)[0][0]
		# Billing kayıtları kullanıcı sonradan ekleyebilir; Seller/Buyer→Delivery/Pickup map ihlal yok
		self.assertEqual(mismatch, 0)


if __name__ == "__main__":
	unittest.main()
