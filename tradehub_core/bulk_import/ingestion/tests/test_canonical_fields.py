"""canonical_fields alias kapsamı — standalone (Frappe gerektirmez).

Regresyon: "BİRİM" sütununun base_price'a sızmasını engelleyen stock_uom
alias'ı ve şablonda hedef olan ama eskiden alias'sız kalan alanların kapsamı.
"""

import unittest

from tradehub_core.bulk_import.ingestion.canonical_fields import CANONICAL_FIELDS

# api.py _TEMPLATE_CORE_COLUMNS_EN'de hedef olan ve artık alias'ı bulunması
# gereken alanlar (eskiden yalnız birebir başlıkla eşleşiyorlardı).
_PREVIOUSLY_MISSING_TARGETS = {
	"stock_uom",
	"currency",
	"condition",
	"max_order_qty",
	"low_stock_threshold",
	"sell_in_moq_multiples",
	"track_inventory",
	"allow_backorders",
	"is_free_shipping",
	"shipping_weight",
	"handling_days",
	"ships_from_country",
	"ships_from_city",
	"country_of_origin",
	"video_url",
}


class TestCanonicalAliasCoverage(unittest.TestCase):
	def test_stock_uom_has_birim_alias(self):
		"""'birim' stock_uom'a bağlı olmalı — base_price'ı çalmasın."""
		self.assertIn("birim", CANONICAL_FIELDS.get("stock_uom", []))

	def test_previously_missing_targets_have_aliases(self):
		for field in _PREVIOUSLY_MISSING_TARGETS:
			self.assertIn(field, CANONICAL_FIELDS, f"{field} canonical alias bloğu eksik")
			self.assertTrue(CANONICAL_FIELDS[field], f"{field} alias listesi boş")

	def test_no_empty_alias_lists(self):
		for field, aliases in CANONICAL_FIELDS.items():
			self.assertTrue(aliases, f"{field} boş alias listesine sahip")


if __name__ == "__main__":
	unittest.main()
