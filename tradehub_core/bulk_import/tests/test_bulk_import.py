"""Bulk import integration testleri — xlsx layout tespiti + profil öğrenme.

Frappe context gerektirir (DB + entitlement import'ları). HAS_FRAPPE guard ile
frappe yoksa atlanır (standalone unittest ortamında import patlamasın).
"""

import os
import tempfile
import types
import unittest
from unittest.mock import patch

try:
	import frappe
	from frappe.tests.utils import FrappeTestCase

	HAS_FRAPPE = True
except ImportError:
	HAS_FRAPPE = False

if HAS_FRAPPE:
	import io
	import zipfile

	from openpyxl import Workbook
	from PIL import Image

	from tradehub_core.bulk_import import api, image_matcher

	# Gerçek (PIL-açılabilir) minimal görseller — Frappe File.before_insert EXIF
	# strip için PIL.Image.open çağırır; sahte byte'lar orada patlar.
	def _img_bytes(fmt: str) -> bytes:
		buf = io.BytesIO()
		Image.new("RGB", (1, 1), (255, 255, 255)).save(buf, fmt)
		return buf.getvalue()

	_JPEG = _img_bytes("JPEG")
	_PNG = _img_bytes("PNG")


def _make_xlsx(path: str) -> None:
	"""İki sayfalı xlsx: küçük 'Ayarlar' + başlığı 2. satırda olan 'Ürünler'."""
	wb = Workbook()
	settings = wb.active
	settings.title = "Ayarlar"
	settings.append(["anahtar", "değer"])
	settings.append(["versiyon", "1"])

	products = wb.create_sheet("Ürünler")
	products.append(["ACME Kimya - 2026 Fiyat Listesi"])  # başlık/logo satırı
	products.append(["Stok Kodu", "Ürün Adı", "Fiyat"])  # gerçek başlık (satır 2)
	for i in range(1, 21):
		products.append([f"ABC-{i:03d}", f"Ürün {i}", 100 + i])
	wb.save(path)


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestXlsxLayoutDetection(FrappeTestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()
		self.path = os.path.join(self.tmpdir, "test.xlsx")
		_make_xlsx(self.path)

	def tearDown(self):
		import shutil

		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def test_picks_product_sheet_and_header_row(self):
		layout = api._detect_xlsx_layout(self.path, None, None)
		# Ana sayfa "Ürünler" seçilmeli (Ayarlar değil)
		self.assertEqual(layout["sheet_name"], "Ürünler")
		# Başlık satırı 2 olarak tespit edilmeli (üstünde logo satırı var)
		self.assertEqual(layout["header_row"], 2)
		# Başlık 1. satırda olmadığı / çok sayfa olduğu için onay istenmeli
		self.assertTrue(layout["needs_header_pick"])
		self.assertIn("Ayarlar", layout["sheet_names"])

	def test_user_values_respected(self):
		# Kullanıcı açıkça verirse sniffer ezmemeli
		layout = api._detect_xlsx_layout(self.path, "Ayarlar", 1)
		self.assertEqual(layout["sheet_name"], "Ayarlar")
		self.assertEqual(layout["header_row"], 1)


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestBuildImageIndex(FrappeTestCase):
	def setUp(self):
		self.tmpdir = tempfile.mkdtemp()
		self.zip_path = os.path.join(self.tmpdir, "img.zip")

	def tearDown(self):
		import shutil

		shutil.rmtree(self.tmpdir, ignore_errors=True)

	def _make_zip(self, entries: dict):
		with zipfile.ZipFile(self.zip_path, "w") as z:
			for name, data in entries.items():
				z.writestr(name, data)

	def test_normalization_orphans_and_magic_number(self):
		self._make_zip(
			{
				"ABC-001.jpg": _JPEG,  # top-level
				"ABC-001_2.jpg": _JPEG,  # aynı SKU ikinci görsel
				"abc-002.png": _PNG,  # küçük harf → normalize ile abc-002
				"_loose.jpg": _JPEG,  # SKU paternine uymaz → yetim
				"FAKE.jpg": b"not an image",  # magic-number geçersiz → atlanır
				"notes.txt": b"x",  # görsel uzantısı değil → tamamen yok sayılır
			}
		)
		index, orphans = image_matcher.build_image_index(self.zip_path, "__TEST__")

		# Normalize edilmiş anahtarlar (küçük harf)
		self.assertEqual(len(index["abc-001"]), 2)
		self.assertIn("abc-002", index)
		# Magic-number geçersiz dosya indekslenmez
		self.assertNotIn("fake", index)
		# SKU paternine uymayan dosya yetim listesinde
		self.assertIn("_loose.jpg", orphans)

	def test_folder_gallery_natural_sort(self):
		self._make_zip(
			{
				"PROD-9/1.jpg": _JPEG,
				"PROD-9/2.jpg": _JPEG,
				"PROD-9/10.jpg": _JPEG,
			}
		)
		index, _orphans = image_matcher.build_image_index(self.zip_path, "__TEST__")
		# Klasör galerisi 3 görsel içerir (sıra _natural_key ile; pure test sırayı doğrular)
		self.assertEqual(len(index["prod-9"]), 3)

	def test_known_skus_deep_nesting(self):
		# Müşteri tarzı derin/dağınık yapı: SKU 2 kat içeride, kategori sarmalı,
		# "325 LOGOSUZ" eki, ve eşleşmeyen (KOD'suz) klasör.
		self._make_zip(
			{
				"FOTO - VIDEO/KATEGORI/307/307-1.jpg": _JPEG,
				"FOTO - VIDEO/KATEGORI/307/307-2.jpg": _JPEG,
				"FOTO - VIDEO/325 LOGOSUZ/Kamp1.png": _PNG,
				"FOTO - VIDEO/KATLANIR DOLAP/random.jpg": _JPEG,  # KOD yok → yetim
			}
		)
		index, orphans = image_matcher.build_image_index(self.zip_path, "__TEST__", known_skus={"307", "325"})
		self.assertEqual(len(index["307"]), 2)  # derin klasör eşleşti
		self.assertEqual(len(index["325"]), 1)  # ekli klasör (token) eşleşti
		self.assertIn("random.jpg", orphans)  # KOD'suz klasör yetim
		self.assertNotIn("katlanir dolap", index)

	def test_backward_compat_without_known_skus(self):
		# known_skus verilmezse eski üst-klasör=SKU davranışı korunur.
		self._make_zip({"307/1.jpg": _JPEG, "307/2.jpg": _JPEG})
		index, _orphans = image_matcher.build_image_index(self.zip_path, "__TEST__")
		self.assertEqual(len(index["307"]), 2)

	def test_image_overrides_force_and_ignore(self):
		# Yetim klasörler: biri SKU'ya atanır, diğeri yoksayılır.
		self._make_zip(
			{
				"FOTO/DOLAP/a.jpg": _JPEG,  # KOD yok → override ile 307'ye
				"FOTO/RAF/b.jpg": _JPEG,  # KOD yok → override ile yoksay
			}
		)
		overrides = {"FOTO/DOLAP": "307", "FOTO/RAF": "__ignore__"}
		index, orphans = image_matcher.build_image_index(
			self.zip_path, "__TEST__", known_skus={"307"}, image_overrides=overrides
		)
		self.assertEqual(len(index["307"]), 1)  # DOLAP → 307'ye zorlandı
		self.assertEqual(orphans, [])  # RAF yoksayıldı, DOLAP atandı → yetim kalmadı

	def test_preview_grouping_dry_with_thumbnails(self):
		# Önizleme: File KAYDETMEDEN matched/orphan + thumbnail döndürür.
		self._make_zip(
			{
				"FOTO/KATEGORI/307/307-1.jpg": _JPEG,
				"FOTO/KATEGORI/307/307-2.jpg": _JPEG,
				"FOTO/KATLANIR DOLAP/x.jpg": _JPEG,  # KOD yok → yetim
			}
		)
		res = image_matcher.preview_zip_grouping(self.zip_path, {"307"}, "__TEST__")
		self.assertEqual(res["total_images"], 3)
		# Eşleşen: 307 → 2 görsel + thumbnail
		m = {x["sku"]: x for x in res["matched"]}
		self.assertEqual(m["307"]["count"], 2)
		self.assertTrue(m["307"]["thumb"].startswith("data:image/jpeg;base64,"))
		# Yetim: KATLANIR DOLAP klasörü
		self.assertEqual(len(res["orphans"]), 1)
		o = res["orphans"][0]
		self.assertEqual(o["label"], "KATLANIR DOLAP")
		self.assertEqual(o["count"], 1)
		self.assertTrue(o["thumbs"][0].startswith("data:image/jpeg;base64,"))


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestEcaRejectionRaise(FrappeTestCase):
	"""reject_row flag set edilince evaluate_rules_two_phase'in insert'i iptal etmesi."""

	def _doc(self):
		return types.SimpleNamespace(
			doctype="Listing",
			seller_profile=None,
			flags=frappe._dict(eca_rejected=True, eca_reject_reason="Yasaklı kategori"),
		)

	def test_raises_on_validate_event(self):
		from tradehub_core.eca import dispatcher

		with (
			patch.object(dispatcher, "_is_eca_enabled", return_value=True),
			patch.object(dispatcher, "_get_phase_rules_v2", return_value=[]),
		):
			frappe.flags.in_bulk_import = True
			try:
				with self.assertRaises(dispatcher.ECARejectionError):
					dispatcher.evaluate_rules_two_phase(self._doc(), "validate")
			finally:
				frappe.flags.in_bulk_import = False

	def test_no_raise_on_after_insert(self):
		# Doc zaten yazılmış → after_insert'te raise edersek orphan kalır; etmemeli.
		from tradehub_core.eca import dispatcher

		with (
			patch.object(dispatcher, "_is_eca_enabled", return_value=True),
			patch.object(dispatcher, "_get_phase_rules_v2", return_value=[]),
		):
			frappe.flags.in_bulk_import = True
			try:
				dispatcher.evaluate_rules_two_phase(self._doc(), "after_insert")  # raise yok
			finally:
				frappe.flags.in_bulk_import = False


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestHumanizeException(FrappeTestCase):
	"""Ham MandatoryError → anlaşılır TR mesaj + ilgili alan."""

	def test_mandatory_error_humanized(self):
		from tradehub_core.bulk_import import runner

		class MandatoryError(Exception):  # type(e).__name__ == "MandatoryError"
			pass

		e = MandatoryError("[Listing, LST-00042]: base_price, selling_price")
		msg, field = runner._humanize_exception(e)
		self.assertIn("Fiyat", msg)
		self.assertIn("Satış Fiyatı", msg)
		self.assertNotIn("LST-00042", msg)  # ham referans kullanıcıya gitmez
		self.assertEqual(field, "base_price, selling_price")

	def test_generic_exception_passthrough(self):
		from tradehub_core.bulk_import import runner

		msg, field = runner._humanize_exception(ValueError("boom"))
		self.assertEqual(msg, "boom")
		self.assertIsNone(field)


@unittest.skipUnless(HAS_FRAPPE, "Frappe context required")
class TestSkuFilenameExtraction(FrappeTestCase):
	"""Satıcıya özel 'SKU Filename' deseninin dosya adından SKU çıkarması."""

	def test_named_group_extraction(self):
		from tradehub_core.bulk_import import regex_lib

		fake = [
			{
				"name": "L1",
				"target_field": "sku",
				"patterns": [{"enabled": 1, "regex": r"^urun-(?P<sku>\d+)", "flags": "IGNORECASE"}],
			}
		]
		with patch.object(regex_lib, "_get_patterns", side_effect=lambda sp, cat: fake if sp is None else []):
			self.assertEqual(regex_lib.extract_sku_from_filename("urun-12345.jpg", None), "12345")

	def test_no_match_returns_none(self):
		from tradehub_core.bulk_import import regex_lib

		with patch.object(regex_lib, "_get_patterns", return_value=[]):
			self.assertIsNone(regex_lib.extract_sku_from_filename("random.jpg", None))


# Not: Profil öğrenme round-trip'i (save_profile → lookup_profile → resolver Layer 1)
# geçerli Admin Seller Profile Link'i gerektirir; resolver Layer 1 tüketimi
# test_resolver.py::test_layer1_profile_hit_short_circuits ile, fingerprint
# test_profile_store.py ile kapsanıyor. Uçtan uca akış gerçek satıcıyla manuel
# doğrulandı (bkz. PLAN-bulk-import-robust-mapping.md Faz 2 durum notu).


if __name__ == "__main__":
	unittest.main()
