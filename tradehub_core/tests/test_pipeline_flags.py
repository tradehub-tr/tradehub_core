# Copyright (c) 2026, Tradehub and contributors
# For license information, please see license.txt

"""`media.pipeline_flags` testleri — Dalga A emniyet subabı (A1b).

Yeni kurulum varsayılanları açık olsa da açıkça kapatılan şalter ve okuma
hataları üretimi durdurmalıdır.

    docker exec istoc-dev-backend-1 bench --site istoc.localhost \
        run-tests --module tradehub_core.tests.test_pipeline_flags
"""

from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

import frappe

from tradehub_core.media import pipeline_flags
from tradehub_core.patches import v15_9_22_media_engine_settings as settings_patch
from tradehub_core.patches import v15_9_57_media_pipeline_defaults as defaults_patch

DOCTYPE = pipeline_flags.SETTINGS_DOCTYPE
KORUNAN_ALANLAR = (
	"media_pipeline_enabled",
	"rendition_on_upload",
	"manifest_api_enabled",
	"active_slots",
	"max_renditions_per_asset",
	"rollout_percent",
	"rollout_stores",
	"notes",
)


class TestPipelineSettingsDefaults(unittest.TestCase):
	def _migrate(self, saved: dict) -> tuple[dict, Mock]:
		values = dict(saved)
		frappe_mock = Mock()
		frappe_mock.db.sql.side_effect = lambda query, args: [(1,)] if args[1] in values else []
		frappe_mock.db.set_single_value.side_effect = lambda doctype, key, value: values.update({key: value})
		with patch.object(settings_patch, "frappe", frappe_mock):
			defaults_patch.execute()
		return values, frappe_mock

	def test_new_install_enables_processing_and_delivery(self):
		values, _ = self._migrate({})
		for field in pipeline_flags.FLAG_FIELDS:
			self.assertEqual(values[field], 1)
		self.assertIn("*", pipeline_flags.parse_slot_keys(values["active_slots"]))
		self.assertGreater(values["max_renditions_per_asset"], 0)

	def test_repeat_migration_preserves_explicit_disabled_settings(self):
		values, _ = self._migrate({})
		for field in pipeline_flags.FLAG_FIELDS:
			values[field] = 0
		values["active_slots"] = ""

		after, frappe_mock = self._migrate(values)

		self.assertEqual(after, values)
		frappe_mock.db.set_single_value.assert_not_called()

	def test_missing_fields_do_not_overwrite_saved_scope_or_kill_switch(self):
		values, _ = self._migrate(
			{"media_pipeline_enabled": 0, "active_slots": "seller.logo", "max_renditions_per_asset": 12}
		)

		self.assertEqual(values["media_pipeline_enabled"], 0)
		self.assertEqual(values["active_slots"], "seller.logo")
		self.assertEqual(values["max_renditions_per_asset"], 12)
		self.assertEqual(values["rendition_on_upload"], 1)
		self.assertEqual(values["manifest_api_enabled"], 1)


class TestPipelineFlags(unittest.TestCase):
	def setUp(self) -> None:
		# Testler gerçek singleton'ı yazıyor; orijinal değerleri geri koyabilmek
		# için sakla (test veritabanı da olsa kirli bırakmayalım).
		self._orijinal = {alan: frappe.db.get_single_value(DOCTYPE, alan) for alan in KORUNAN_ALANLAR}
		pipeline_flags.clear_cache()

	def tearDown(self) -> None:
		for alan, deger in self._orijinal.items():
			frappe.db.set_single_value(DOCTYPE, alan, deger)
		pipeline_flags.clear_cache()

	def _ayarla(self, **degerler: object) -> None:
		for alan, deger in degerler.items():
			frappe.db.set_single_value(DOCTYPE, alan, deger)
		pipeline_flags.clear_cache()

	# --- ana şalter -----------------------------------------------------

	def test_kayitli_kapatma_tercihi_korunur(self):
		"""Varsayılan açık olsa da kayıtlı 0 ana şalteri kapatır."""
		self._ayarla(media_pipeline_enabled=0)

		self.assertFalse(pipeline_flags.is_enabled())

	def test_acikken_true(self):
		self._ayarla(media_pipeline_enabled=1)

		self.assertTrue(pipeline_flags.is_enabled())

	def test_alt_bayraklar_ana_salter_kapaliyken_false(self):
		"""Alt bayrak 1 olsa bile ana şalter kapalıysa kapalıdır."""
		self._ayarla(
			media_pipeline_enabled=0,
			rendition_on_upload=1,
			manifest_api_enabled=1,
		)

		self.assertFalse(pipeline_flags.is_enabled("rendition_on_upload"))
		self.assertFalse(pipeline_flags.is_enabled("manifest_api_enabled"))

	def test_alt_bayrak_ana_salter_acikken_kendi_degerini_izler(self):
		self._ayarla(
			media_pipeline_enabled=1,
			rendition_on_upload=1,
			manifest_api_enabled=0,
		)

		self.assertTrue(pipeline_flags.is_enabled("rendition_on_upload"))
		self.assertFalse(pipeline_flags.is_enabled("manifest_api_enabled"))

	def test_bilinmeyen_alan_false(self):
		"""Beyaz liste dışı alan bayrak sayılmaz — `notes` dolu diye açılmasın."""
		self._ayarla(media_pipeline_enabled=1, notes="dolu")

		self.assertFalse(pipeline_flags.is_enabled("notes"))
		self.assertFalse(pipeline_flags.is_enabled("olmayan_alan"))

	# --- fail-safe ------------------------------------------------------

	def test_doctype_yokken_false(self):
		"""DocType/DB okunamıyorsa exception sızmaz, sonuç False."""

		def _patla(*args, **kwargs):
			raise frappe.DoesNotExistError("DocType Media Engine Settings not found")

		self._ayarla(media_pipeline_enabled=1)
		with patch.object(frappe.db, "get_single_value", side_effect=_patla):
			pipeline_flags.clear_cache()

			self.assertFalse(pipeline_flags.is_enabled())
			self.assertFalse(pipeline_flags.is_enabled("manifest_api_enabled"))
			self.assertFalse(pipeline_flags.is_slot_enabled("product.image"))
			self.assertEqual(pipeline_flags.max_renditions_per_asset(), 40)

	def test_deger_none_ise_false(self):
		"""Singles'ta satır hiç yoksa get_single_value None döner → False."""
		with patch.object(frappe.db, "get_single_value", return_value=None):
			pipeline_flags.clear_cache()

			self.assertFalse(pipeline_flags.is_enabled())

	# --- slotlar --------------------------------------------------------

	def test_slot_ana_salter_kapaliyken_false(self):
		self._ayarla(media_pipeline_enabled=0, active_slots="product.image")

		self.assertFalse(pipeline_flags.is_slot_enabled("product.image"))

	def test_slot_listede_varsa_true(self):
		self._ayarla(media_pipeline_enabled=1, active_slots="product.image\nseller.logo")

		self.assertTrue(pipeline_flags.is_slot_enabled("product.image"))
		self.assertTrue(pipeline_flags.is_slot_enabled("seller.logo"))
		self.assertFalse(pipeline_flags.is_slot_enabled("user.avatar"))

	def test_slot_listesi_bos_ise_hicbiri_acik_degil(self):
		self._ayarla(media_pipeline_enabled=1, active_slots="")

		self.assertFalse(pipeline_flags.is_slot_enabled("product.image"))

	def test_slot_joker_tumunu_acar(self):
		self._ayarla(media_pipeline_enabled=1, active_slots="*")

		self.assertTrue(pipeline_flags.is_slot_enabled("product.image"))
		self.assertTrue(pipeline_flags.is_slot_enabled("user.avatar"))

	def test_slot_virgul_ve_bosluk_toleransi(self):
		self._ayarla(media_pipeline_enabled=1, active_slots=" Product.Image , seller.logo ")

		self.assertTrue(pipeline_flags.is_slot_enabled("product.image"))
		self.assertTrue(pipeline_flags.is_slot_enabled(" PRODUCT.IMAGE "))
		self.assertFalse(pipeline_flags.is_slot_enabled(""))

	# --- tavan ----------------------------------------------------------

	def test_max_renditions_varsayilani(self):
		self._ayarla(max_renditions_per_asset=0)

		self.assertEqual(pipeline_flags.max_renditions_per_asset(), 40)

	def test_max_renditions_kayitli_degeri_okur(self):
		self._ayarla(max_renditions_per_asset=12)

		self.assertEqual(pipeline_flags.max_renditions_per_asset(), 12)

	# --- deterministik rollout -----------------------------------------

	def test_rollout_sifirda_yalniz_canary_magaza_acik(self):
		self._ayarla(
			media_pipeline_enabled=1,
			rollout_percent=0,
			rollout_stores="SELLER-CANARY, seller-second",
		)

		self.assertTrue(pipeline_flags.is_store_enabled("seller-canary"))
		self.assertTrue(pipeline_flags.is_store_enabled("SELLER-SECOND"))
		self.assertFalse(pipeline_flags.is_store_enabled("SELLER-OUT"))
		self.assertFalse(pipeline_flags.is_store_enabled(""))

	def test_rollout_kumesi_10dan_50ye_100e_monoton_buyur(self):
		self._ayarla(media_pipeline_enabled=1, rollout_stores="")
		magazalar = [f"SELLER-{i:04d}" for i in range(500)]
		kumeler: dict[int, set[str]] = {}
		for yuzde in (10, 50, 100):
			self._ayarla(rollout_percent=yuzde)
			kumeler[yuzde] = {s for s in magazalar if pipeline_flags.is_store_enabled(s)}

		self.assertTrue(kumeler[10])
		self.assertLess(kumeler[10], kumeler[50])
		self.assertLess(kumeler[50], kumeler[100])
		self.assertEqual(kumeler[100], set(magazalar))

	def test_rollout_kovasi_surecler_arasi_sabit_sha256_degeridir(self):
		self.assertEqual(pipeline_flags.rollout_bucket("SELLER-001"), 52)
		self.assertEqual(pipeline_flags.rollout_bucket(" seller-001 "), 52)

	def test_ana_salter_rollout_canarysini_da_keser(self):
		self._ayarla(
			media_pipeline_enabled=0,
			rollout_percent=100,
			rollout_stores="SELLER-CANARY",
		)

		self.assertFalse(pipeline_flags.is_store_enabled("SELLER-CANARY"))

	# --- önbellek -------------------------------------------------------

	def test_onbellek_istek_kapsaminda_tek_okuma_yapar(self):
		self._ayarla(media_pipeline_enabled=1)
		with patch.object(frappe.db, "get_single_value", wraps=frappe.db.get_single_value) as casus:
			pipeline_flags.clear_cache()
			pipeline_flags.is_enabled()
			pipeline_flags.is_enabled()
			pipeline_flags.is_enabled()

			self.assertEqual(casus.call_count, 1)

	def test_clear_cache_yeni_degeri_gorunur_kilar(self):
		self._ayarla(media_pipeline_enabled=0)
		self.assertFalse(pipeline_flags.is_enabled())

		self._ayarla(media_pipeline_enabled=1)  # clear_cache dahil

		self.assertTrue(pipeline_flags.is_enabled())
