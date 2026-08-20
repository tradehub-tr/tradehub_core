# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Sözleşme bütünlüğü testleri (Faz B.10).

Çalıştırma:
	docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \\
	  bench --site dev.localhost run-tests \\
	  --module tradehub_core.logistics.tests.test_logistics_contract"

Bu süit KODUN DOĞRULUĞUNU değil, **kaynak ile üretilmiş artefaktların
ayrışmadığını** doğrular:

	* Üretilmiş dosyalar bayat mı? (`--check` ile aynı mantık)
	* Mock fixture'lar sözleşmeye uyuyor mu? — uymazsa Storybook yalan söyler
	  ve Faz D'de onaylanan ekran Faz E'de kırılır
	* Şemadaki hata kodları gerçek exception sınıflarıyla eşleşiyor mu?

ÇALIŞMA ORTAMI UYARISI:
	LOCAL dev'de docker yalnız `tradehub_core/tradehub_core` (Python paketi)
	mount ediyor; `scripts/` ve `docs/` konteynerde GÜNCEL DEĞİL. Bu yüzden bu
	süit bench içinde çalıştırıldığında ATLANIR.

	DİKKAT (denetim 2026-08-20): Bu atlamayı yakalayan bir CI kapısı HENÜZ YOK
	(hiçbir repoda lint.yml benzeri workflow bulunmuyor). Atlanan kontrolün
	tek güvencesi `python3 scripts/gen_logistics_types.py --check`'in lokalde
	(repo kökünden) koşulmasıdır. Süit bench dışında, gerçek dosya ağacıyla
	çalıştırıldığında tam koşar.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

APP_ROOT = Path(__file__).resolve().parents[3]
GENERATOR_PATH = APP_ROOT / "scripts" / "gen_logistics_types.py"

#: Üretici erişilebilir mi? (konteynerde scripts/ mount edilmiyor)
GENERATOR_AVAILABLE = GENERATOR_PATH.exists()
SKIP_REASON = (
	f"Üretici erişilebilir değil ({GENERATOR_PATH}); "
	"CI kapısı henüz kurulmadı — `gen_logistics_types.py --check` LOKAL koşulmalı"
)


def _load_generator():
	"""Üretici script'ini modül olarak yükler (scripts/ bir paket değil)."""
	spec = importlib.util.spec_from_file_location("gen_logistics_types", GENERATOR_PATH)
	module = importlib.util.module_from_spec(spec)
	spec.loader.exec_module(module)
	return module


@unittest.skipUnless(GENERATOR_AVAILABLE, SKIP_REASON)
class TestGeneratedArtifactsAreFresh(FrappeTestCase):
	"""Üretilmiş dosyalar kaynakla uyumlu olmalı."""

	def setUp(self):
		self.gen = _load_generator()

	def test_generated_files_are_not_stale(self):
		"""Kaynak değişip yeniden üretilmediyse burada yakalanır.

		CI'daki `gen_logistics_types.py --check` ile aynı karşılaştırma; testin
		de yapması, üreticiyi çalıştırmayı unutan bir PR'ın sessizce geçmemesi
		içindir.
		"""
		stale = [
			path.relative_to(APP_ROOT)
			for path, content in self.gen._render_all().items()
			if not path.exists() or path.read_text(encoding="utf-8") != content
		]
		self.assertEqual(
			stale,
			[],
			"Bayat üretilmiş dosya(lar). Çöz: python3 scripts/gen_logistics_types.py --sync",
		)

	def test_storefront_copy_matches_source(self):
		"""tradehubfront'a senkronlanan tip dosyası referans kopyayla aynı olmalı."""
		source = self.gen.DTS_PATH
		target = (APP_ROOT / "../tradehubfront/src/types/logistics.d.ts").resolve()
		if not target.exists():
			self.skipTest("tradehubfront kardeş dizinde değil (CI ortamı olabilir)")
		self.assertEqual(
			target.read_text(encoding="utf-8"),
			source.read_text(encoding="utf-8"),
			"Senkron kopya bayat. Çöz: python3 scripts/gen_logistics_types.py --sync",
		)


@unittest.skipUnless(GENERATOR_AVAILABLE, SKIP_REASON)
class TestSchemaMatchesCode(FrappeTestCase):
	"""Şema, gerçek Python sözleşmesinin aynası olmalı."""

	def setUp(self):
		self.gen = _load_generator()
		self.schema = json.loads(self.gen.SCHEMA_PATH.read_text(encoding="utf-8"))

	def test_every_catalog_is_in_schema(self):
		from tradehub_core.api.v1.logistics_catalog import CATALOGS

		self.assertEqual(set(self.schema["catalogs"]), set(CATALOGS))

	def test_every_exception_code_is_in_schema(self):
		from tradehub_core.logistics import exceptions as E

		codes = {
			getattr(E, name).code
			for name in dir(E)
			if isinstance(getattr(E, name), type) and hasattr(getattr(E, name), "code")
		}
		missing = codes - set(self.schema["error_codes"])
		self.assertEqual(missing, set(), "Şemada eksik hata kodu")

	def test_error_codes_carry_http_status(self):
		for code, status in self.schema["error_codes"].items():
			self.assertIsInstance(status, int, f"{code} HTTP durumu tamsayı olmalı")
			self.assertGreaterEqual(status, 400, f"{code} bir hata durumu olmalı")

	def test_shipment_status_enum_matches_constants(self):
		from tradehub_core.logistics.constants import ShipmentStatus

		self.assertEqual(
			self.schema["enums"]["ShipmentStatus"], list(ShipmentStatus.ALL)
		)

	def test_feature_flag_enum_matches_constants(self):
		from tradehub_core.logistics.constants import LOGISTICS_FEATURE_FLAGS

		self.assertEqual(
			set(self.schema["enums"]["FeatureFlag"]), set(LOGISTICS_FEATURE_FLAGS)
		)

	def test_secret_fields_declared_in_schema(self):
		from tradehub_core.api.v1.logistics_admin import SECRET_FIELDS

		self.assertEqual(
			set(self.schema["admin"]["carrier_account"]["secret_fields"]),
			set(SECRET_FIELDS),
		)

	def test_contract_fields_exist_in_doctypes(self):
		"""Sözleşmedeki her alan gerçekten DocType'ta olmalı.

		Üretici bunu zaten SystemExit ile yakalıyor; test, hatanın CI'da
		görünür olmasını sağlıyor.
		"""
		self.gen.build_schema()  # alan bulunamazsa SystemExit fırlatır


@unittest.skipUnless(GENERATOR_AVAILABLE, SKIP_REASON)
class TestFixturesConformToContract(FrappeTestCase):
	"""Storybook mock'ları sözleşmeye uymazsa Faz D onayı yanlış zeminde olur."""

	def setUp(self):
		self.gen = _load_generator()
		self.schema = json.loads(self.gen.SCHEMA_PATH.read_text(encoding="utf-8"))

	def _fixture(self, catalog: str) -> dict:
		path = self.gen.FIXTURE_ROOT / f"{catalog}.json"
		self.assertTrue(path.exists(), f"{catalog} için fixture yok")
		return json.loads(path.read_text(encoding="utf-8"))

	def test_every_catalog_has_fixture(self):
		for catalog in self.schema["catalogs"]:
			self._fixture(catalog)

	def test_fixtures_cover_default_empty_error_scenarios(self):
		"""Her ekranın en az bu üç durumu tasarlanmalı."""
		for catalog in self.schema["catalogs"]:
			self.assertEqual(
				set(self._fixture(catalog)), {"default", "empty", "error"}, catalog
			)

	def test_fixture_rows_match_list_fields_exactly(self):
		"""Fixture alanları sözleşmeyle birebir — eksik ya da fazla alan olmamalı."""
		for catalog, spec in self.schema["catalogs"].items():
			expected = {field["name"] for field in spec["list_fields"]}
			for row in self._fixture(catalog)["default"]["data"]["items"]:
				self.assertEqual(set(row), expected, f"{catalog} fixture alanları sapmış")

	def test_fixtures_use_envelope_shape(self):
		for catalog in self.schema["catalogs"]:
			fixture = self._fixture(catalog)
			self.assertTrue(fixture["default"]["ok"])
			self.assertFalse(fixture["error"]["ok"])
			self.assertIn("code", fixture["error"]["error"])

	def test_fixture_error_code_is_a_known_code(self):
		known = set(self.schema["error_codes"])
		for catalog in self.schema["catalogs"]:
			code = self._fixture(catalog)["error"]["error"]["code"]
			self.assertIn(code, known, f"{catalog} bilinmeyen hata kodu kullanıyor")

	def test_pagination_totals_are_consistent(self):
		for catalog in self.schema["catalogs"]:
			data = self._fixture(catalog)["default"]["data"]
			self.assertEqual(data["total"], len(data["items"]), catalog)
			self.assertEqual(self._fixture(catalog)["empty"]["data"]["total"], 0)
