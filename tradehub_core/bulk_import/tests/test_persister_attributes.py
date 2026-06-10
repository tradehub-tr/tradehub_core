"""persister.create_listing attribute_values testleri.

Mapping satirinda `attr:<code>` deseni geldiginde persister'in bunu Listing
field'i degil, Listing.attribute_values child satiri olarak yazdigini dogrular.
Ayrica product_type kolonunun Listing.product_type Link alanina islendigini
kontrol eder.

Frappe DB gerektirir (FrappeTestCase). Her test FrappeTestCase'in otomatik
transaction rollback'i ile izole calisir; setUpClass fixture'lari commit ile
kalici yapilir (aksi halde rollback geri alir).
"""

from __future__ import annotations

import unittest

try:
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	import frappe

	from tradehub_core.bulk_import import persister

ATTR_CODE = "color"
PT_CODE = "TEST-PERSIST-PT"
SELLER_USER = "test_persist_seller@example.com"
SELLER_CODE = "TST-PERSIST-SLR"


def _ensure_attribute() -> str:
	"""`color` Product Attribute fixture'i (autoname field:attribute_code -> name=code)."""
	if not frappe.db.exists("Product Attribute", ATTR_CODE):
		frappe.get_doc(
			{
				"doctype": "Product Attribute",
				"attribute_code": ATTR_CODE,
				"attribute_label": "Renk",
				"data_type": "Text",
			}
		).insert(ignore_permissions=True)
	return ATTR_CODE


# Otomatik esleme e2e senaryosu icin betimleyici (descriptive) attribute'lar.
# attribute_label_en alani resolver._resolve_attributes tarafindan statik
# sablon basligi ("Material", "Warranty") ile (fold edilerek) eslestirilir;
# include_in_bulk_template=1 oncelik verir.
_PIM_ATTRS: tuple[tuple[str, str, str], ...] = (
	("material", "Malzeme", "Material"),
	("warranty", "Garanti", "Warranty"),
	("size", "Beden", "Size"),
)


def _ensure_pim_attributes() -> None:
	"""Statik sablon kolonlariyla otomatik eslenecek betimleyici attribute'lar."""
	for code, label_tr, label_en in _PIM_ATTRS:
		if frappe.db.exists("Product Attribute", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Product Attribute",
				"attribute_code": code,
				"attribute_label": label_tr,
				"attribute_label_en": label_en,
				"data_type": "Text",
				"include_in_bulk_template": 1,
			}
		).insert(ignore_permissions=True)


def _ensure_product_type() -> str:
	if not frappe.db.exists("Product Type", PT_CODE):
		frappe.get_doc(
			{
				"doctype": "Product Type",
				"type_code": PT_CODE,
				"type_name": "Persister Test Tipi",
			}
		).insert(ignore_permissions=True)
	return PT_CODE


def _ensure_seller() -> str:
	if not frappe.db.exists("User", SELLER_USER):
		frappe.get_doc(
			{
				"doctype": "User",
				"email": SELLER_USER,
				"first_name": "Persist",
				"last_name": "Seller",
				"send_welcome_email": 0,
				"enabled": 1,
			}
		).insert(ignore_permissions=True)
	existing = frappe.db.get_value("Admin Seller Profile", {"user": SELLER_USER}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Admin Seller Profile",
			"user": SELLER_USER,
			"email": SELLER_USER,
			"seller_name": "Persist Seller",
			"seller_code": SELLER_CODE,
			"status": "Active",
			"company_name": "Persist Co",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


def _ensure_job(seller_profile: str) -> str:
	"""Listing.created_by_bulk_job Link reqd -> gercek bir Bulk Import Job fixture'i."""
	doc = frappe.get_doc(
		{
			"doctype": "Bulk Import Job",
			"seller_profile": seller_profile,
			"data_file": "/private/files/test-persist.xlsx",
			"file_format": "xlsx",
		}
	)
	doc.insert(ignore_permissions=True)
	return doc.name


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestPersisterAttributes(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		cls.attr = _ensure_attribute()
		_ensure_pim_attributes()
		cls.product_type = _ensure_product_type()
		cls.seller = _ensure_seller()
		cls.job = _ensure_job(cls.seller)
		# Fixture'lar test rollback'inde kaybolmasin diye commit edilir.
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")

	def _row(self, **overrides) -> dict:
		"""attr:color iceren temel mapping satiri (canonical keys)."""
		data = {
			"sku": "PERSIST-001",
			"title": "Persister Test Urun",
			"base_price": "100",
			"product_type": PT_CODE,
			"attr:color": "Red",
		}
		data.update(overrides)
		return data

	# ------------------------------------------------------------------
	# attr:color -> attribute_values child satiri yazilir
	# ------------------------------------------------------------------
	def test_attr_column_writes_attribute_value_row(self):
		name = persister.create_listing(self._row(), self.seller, self.job)
		doc = frappe.get_doc("Listing", name)

		rows = {r.attribute: r.attribute_value for r in doc.attribute_values}
		self.assertIn(ATTR_CODE, rows)
		self.assertEqual(rows[ATTR_CODE], "Red")

	# ------------------------------------------------------------------
	# product_type kolonu Listing.product_type Link alanina islenir
	# ------------------------------------------------------------------
	def test_product_type_column_persisted(self):
		name = persister.create_listing(self._row(sku="PERSIST-002"), self.seller, self.job)
		product_type = frappe.db.get_value("Listing", name, "product_type")
		self.assertEqual(product_type, PT_CODE)

	# ------------------------------------------------------------------
	# attr:<code> key'i Listing DB field'i olarak yazilmaz (child-only)
	# ------------------------------------------------------------------
	def test_attr_key_not_written_as_listing_field(self):
		name = persister.create_listing(self._row(sku="PERSIST-003"), self.seller, self.job)
		doc = frappe.get_doc("Listing", name)
		# attr: prefix'li bir kolon Listing'de field olarak bulunmamali.
		self.assertFalse(hasattr(doc, "attr:color"))
		self.assertNotIn("color", {f.fieldname for f in doc.meta.fields})

	# ------------------------------------------------------------------
	# Bos attr degeri satir uretmez
	# ------------------------------------------------------------------
	def test_empty_attr_value_skipped(self):
		name = persister.create_listing(
			self._row(sku="PERSIST-004", **{"attr:color": ""}),
			self.seller,
			self.job,
		)
		doc = frappe.get_doc("Listing", name)
		self.assertEqual([r for r in doc.attribute_values if r.attribute == ATTR_CODE], [])

	# ------------------------------------------------------------------
	# Gecersiz attribute code satir yazmaz + warning ekler
	# ------------------------------------------------------------------
	def test_invalid_attr_code_warns_and_skips(self):
		warnings: list[str] = []
		name = persister.create_listing(
			self._row(sku="PERSIST-005", **{"attr:nonexistent_attr": "X"}),
			self.seller,
			self.job,
			warnings=warnings,
		)
		doc = frappe.get_doc("Listing", name)
		self.assertEqual([r for r in doc.attribute_values if r.attribute == "nonexistent_attr"], [])
		self.assertTrue(any("nonexistent_attr" in w for w in warnings))
		# Gecerli attr:color yine yazilmis olmali
		self.assertIn(ATTR_CODE, {r.attribute for r in doc.attribute_values})

	# ------------------------------------------------------------------
	# 3-eksenli varyant: Renk/Beden/Hafiza -> Listing Variant Item
	# attribute_type_3 / attribute_value_3 dolu yazilir; parent attr:color
	# attribute_values'a islenir.
	# ------------------------------------------------------------------
	def test_three_axis_variant_writes_attribute_type_3(self):
		parent = self._row(sku="PERSIST-VAR-PARENT")
		variant_rows = [
			{
				"variant_sku": "PERSIST-VAR-1",
				"variant_axis_1_type": "Renk",
				"variant_axis_1_value": "Kirmizi",
				"variant_axis_2_type": "Beden",
				"variant_axis_2_value": "M",
				"variant_axis_3_type": "Hafiza",
				"variant_axis_3_value": "128GB",
				"variant_price": "120",
				"variant_stock": "10",
			},
			{
				"variant_sku": "PERSIST-VAR-2",
				"variant_axis_1_type": "Renk",
				"variant_axis_1_value": "Mavi",
				"variant_axis_2_type": "Beden",
				"variant_axis_2_value": "L",
				"variant_axis_3_type": "Hafiza",
				"variant_axis_3_value": "256GB",
				"variant_price": "140",
				"variant_stock": "5",
			},
		]
		name = persister.create_listing_with_variants(
			parent, variant_rows, self.seller, self.job
		)
		doc = frappe.get_doc("Listing", name)

		# parent attr:color attribute_values'a yazilmis olmali
		self.assertIn(ATTR_CODE, {r.attribute for r in doc.attribute_values})

		# Iki varyant satiri + 3-eksen tum kolonlar dolu
		self.assertEqual(len(doc.variant_items), 2)
		first = doc.variant_items[0]
		self.assertEqual(first.attribute_type, "Renk")
		self.assertEqual(first.attribute_value, "Kirmizi")
		self.assertEqual(first.attribute_type_2, "Beden")
		self.assertEqual(first.attribute_value_2, "M")
		self.assertEqual(first.attribute_type_3, "Hafiza")
		self.assertEqual(first.attribute_value_3, "128GB")
		self.assertEqual(first.variant_sku, "PERSIST-VAR-1")

		# variant_axes_config 3 ekseni de toplamali
		import json

		axes = json.loads(doc.variant_axes_config)
		self.assertEqual(set(axes.keys()), {"Renk", "Beden", "Hafiza"})
		self.assertIn("128GB", axes["Hafiza"])
		self.assertIn("256GB", axes["Hafiza"])


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestPimAutoMappingEndToEnd(FrappeTestCase):
	"""Statik sablon kolonlarinin OTOMATIK eslenip persister'a aktigi e2e senaryo.

	Satici elle ugrasmaz: resolver.resolve_columns sablon basliklarini hic
	manuel mapping olmadan canonical/attr/variant hedeflerine baglar, sonra
	persister bunlardan product_type + attribute_values + Listing Variant Item
	yazar. urunler-pim.xlsx fixture'inin satir yapisini birebir yansitir
	(SHOE-A + Renk x Beden 4 varyant), repo disi dosyaya bagimli kalmadan.
	"""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		_ensure_attribute()
		_ensure_pim_attributes()
		cls.product_type = _ensure_product_type()
		cls.seller = _ensure_seller()
		cls.job = _ensure_job(cls.seller)
		frappe.db.commit()

	def setUp(self):
		frappe.set_user("Administrator")

	# Statik sablon basliklari — urunler-pim.xlsx ile ayni.
	_HEADERS = [
		"SKU",
		"Product Name",
		"Brand",
		"Product Type",
		"Material",
		"Warranty",
		"Unit Price",
		"Stock",
		"Parent SKU",
		"Variant SKU",
		"Variant Axis 1 Name",
		"Variant Axis 1 Value",
		"Variant Axis 2 Name",
		"Variant Axis 2 Value",
		"Variant Price",
		"Variant Stock",
	]

	def _resolve(self) -> dict[str, str]:
		"""Otomatik esleme: header -> canonical/attr/variant hedefi."""
		from tradehub_core.bulk_import.ingestion import semantic
		from tradehub_core.bulk_import.ingestion.resolver import resolve_columns

		semantic.clear_semantic_cache()
		res = resolve_columns(self._HEADERS, seller_profile=self.seller)
		return res

	# ------------------------------------------------------------------
	# Otomatik esleme: betimleyici + variant basliklari unmapped KALMAZ
	# ------------------------------------------------------------------
	def test_template_headers_auto_map_without_manual_intervention(self):
		res = self._resolve()
		mapping = res["mapping"]
		self.assertEqual(mapping.get("product_type"), "Product Type")
		self.assertEqual(mapping.get("attr:material"), "Material")
		self.assertEqual(mapping.get("attr:warranty"), "Warranty")
		self.assertEqual(mapping.get("variant_axis_1_type"), "Variant Axis 1 Name")
		self.assertEqual(mapping.get("variant_axis_1_value"), "Variant Axis 1 Value")
		self.assertEqual(mapping.get("variant_axis_2_type"), "Variant Axis 2 Name")
		self.assertEqual(mapping.get("variant_axis_2_value"), "Variant Axis 2 Value")
		# Hicbir PIM/variant basligi unmapped kalmamali — satici elle baglamaz.
		for header in ("Product Type", "Material", "Warranty", "Variant Axis 1 Name"):
			self.assertNotIn(header, res["unmapped"])

	# ------------------------------------------------------------------
	# Uctan uca: otomatik mapping -> persister -> product_type + attr + 4 varyant
	# ------------------------------------------------------------------
	def test_auto_mapping_persists_product_type_attrs_and_variants(self):
		res = self._resolve()
		header_to_target = {hdr: tgt for tgt, hdr in res["mapping"].items()}

		# urunler-pim.xlsx satir verisi (parent + 4 varyant).
		raw_rows = [
			["SHOE-A", "Spor Ayakkabi", "Nike", "AYAKKABI", "Deri", 24, "1200.00", 0,
				None, None, None, None, None, None, None, None],
			[None, None, None, None, None, None, None, None,
				"SHOE-A", "SHOE-A-KIR-40", "Renk", "Kirmizi", "Beden", "40", "1200.00", 20],
			[None, None, None, None, None, None, None, None,
				"SHOE-A", "SHOE-A-KIR-41", "Renk", "Kirmizi", "Beden", "41", "1200.00", 15],
			[None, None, None, None, None, None, None, None,
				"SHOE-A", "SHOE-A-MAV-40", "Renk", "Mavi", "Beden", "40", "1250.00", 10],
			[None, None, None, None, None, None, None, None,
				"SHOE-A", "SHOE-A-MAV-41", "Renk", "Mavi", "Beden", "41", "1250.00", 8],
		]

		def to_canonical(raw: list) -> dict:
			out: dict = {}
			for idx, header in enumerate(self._HEADERS):
				target = header_to_target.get(header)
				if not target:
					continue
				val = raw[idx]
				if val is None:
					continue
				out[target] = val
			return out

		parent_canon: dict | None = None
		variant_canons: list[dict] = []
		for raw in raw_rows:
			canon = to_canonical(raw)
			if not canon:
				continue
			if canon.get("sku") and not canon.get("parent_sku"):
				parent_canon = canon
			elif canon.get("parent_sku"):
				variant_canons.append(canon)

		self.assertIsNotNone(parent_canon)
		self.assertEqual(len(variant_canons), 4)

		name = persister.create_listing_with_variants(
			parent_canon, variant_canons, self.seller, self.job
		)
		doc = frappe.get_doc("Listing", name)

		# product_type Link
		self.assertEqual(doc.product_type, "AYAKKABI")

		# attribute_values: Material=Deri, Warranty=24
		attrs = {r.attribute: r.attribute_value for r in doc.attribute_values}
		self.assertEqual(attrs.get("material"), "Deri")
		self.assertEqual(str(attrs.get("warranty")), "24")

		# 4 varyant (Renk x Beden)
		self.assertEqual(doc.has_variants, 1)
		self.assertEqual(len(doc.variant_items), 4)
		self.assertEqual(
			{v.variant_sku for v in doc.variant_items},
			{"SHOE-A-KIR-40", "SHOE-A-KIR-41", "SHOE-A-MAV-40", "SHOE-A-MAV-41"},
		)
		first = doc.variant_items[0]
		self.assertEqual(first.attribute_type, "Renk")
		self.assertEqual(first.attribute_type_2, "Beden")

		import json

		axes = json.loads(doc.variant_axes_config or "{}")
		self.assertEqual(set(axes.keys()), {"Renk", "Beden"})
		self.assertEqual(set(axes["Renk"]), {"Kirmizi", "Mavi"})
		self.assertEqual(set(axes["Beden"]), {"40", "41"})


if __name__ == "__main__":
	unittest.main()
