# Copyright (c) 2024, Istoc.com and contributors
# For license information, please see license.txt

"""Desi hesaplama utility testleri."""

from __future__ import annotations

import unittest

from tradehub_core.logistics.services.desi import (
	calculate_desi,
	calculate_shipment_totals,
	get_chargeable_weight,
)


class TestCalculateDesi(unittest.TestCase):
	"""calculate_desi fonksiyonu testleri."""

	def test_basic_desi_calculation(self) -> None:
		"""30x20x15 cm kutu, divisor=3000 -> 9000/3000 = 3.0 desi."""
		result: float = calculate_desi(30, 20, 15)
		self.assertEqual(result, 3.0)

	def test_desi_ceil_rounding(self) -> None:
		"""Varsayilan ceil yuvarlama ile kesirli deger yukari yuvarlanmali."""
		# 40x30x25 = 30000 / 3000 = 10.0 (tam sayi, ceil etkilemez)
		self.assertEqual(calculate_desi(40, 30, 25), 10.0)

		# 31x20x15 = 9300 / 3000 = 3.1 -> ceil = 4.0
		result: float = calculate_desi(31, 20, 15)
		self.assertEqual(result, 4.0)

	def test_chargeable_weight_uses_max(self) -> None:
		"""Ucretlendirilebilir agirlik, fiili ve hacimsel arasindaki buyuk olan olmali."""
		# Fiili agirlik buyukse
		self.assertEqual(get_chargeable_weight(10.0, 5.0), 10.0)
		# Hacimsel agirlik buyukse
		self.assertEqual(get_chargeable_weight(3.0, 8.0), 8.0)
		# Esitse
		self.assertEqual(get_chargeable_weight(5.0, 5.0), 5.0)

	def test_zero_dimensions(self) -> None:
		"""Sifir boyutlu paket icin desi 0 olmali."""
		self.assertEqual(calculate_desi(0, 20, 15), 0.0)
		self.assertEqual(calculate_desi(30, 0, 15), 0.0)
		self.assertEqual(calculate_desi(30, 20, 0), 0.0)
		self.assertEqual(calculate_desi(0, 0, 0), 0.0)

	def test_international_divisor(self) -> None:
		"""Uluslararasi gonderiler icin divisor=5000 kullanilmali."""
		# 50x40x30 = 60000 / 5000 = 12.0
		result: float = calculate_desi(50, 40, 30, divisor=5000)
		self.assertEqual(result, 12.0)

		# 50x40x31 = 62000 / 5000 = 12.4 -> ceil = 13.0
		result_ceil: float = calculate_desi(50, 40, 31, divisor=5000)
		self.assertEqual(result_ceil, 13.0)


class TestCalculateShipmentTotals(unittest.TestCase):
	"""calculate_shipment_totals fonksiyonu testleri."""

	def test_single_item(self) -> None:
		"""Tek parcali gonderi icin toplamlar."""
		items: list[dict] = [
			{
				"length_cm": 30,
				"width_cm": 20,
				"height_cm": 15,
				"weight_kg": 2.5,
				"qty": 1,
			}
		]
		result: dict = calculate_shipment_totals(items)
		self.assertEqual(result["total_weight"], 2.5)
		self.assertEqual(result["total_desi"], 3.0)
		self.assertEqual(result["chargeable_weight"], 3.0)
		self.assertEqual(result["parcel_count"], 1)

	def test_multiple_items_with_qty(self) -> None:
		"""Coklu parcel ve qty ile toplamlar."""
		items: list[dict] = [
			{
				"length_cm": 30,
				"width_cm": 20,
				"height_cm": 15,
				"weight_kg": 2.0,
				"qty": 2,
			},
			{
				"length_cm": 10,
				"width_cm": 10,
				"height_cm": 10,
				"weight_kg": 0.5,
				"qty": 3,
			},
		]
		result: dict = calculate_shipment_totals(items)
		# 2.0*2 + 0.5*3 = 5.5
		self.assertEqual(result["total_weight"], 5.5)
		self.assertEqual(result["parcel_count"], 5)


if __name__ == "__main__":
	unittest.main()
