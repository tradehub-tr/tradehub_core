"""`get_currency_settings` VARSAYILAN PARA BİRİMİ SÖZLEŞMESİ.

Korunan iddia: **döndürülen `defaultCurrency` her zaman `currencies`
listesinde bulunur.**

Neden gerekli: `COUNTRY_CURRENCY_MAP` bugün `GB→GBP` ve `CN/HK/TW→CNY`
eşlemeleri taşıyor, ama Supported Currency'de yalnız USD/TRY/EUR tanımlı.
Doğrulama olmadan İngiltere'den gelen isteğe `defaultCurrency: "GBP"`
dönüyordu; o kodun ne kuru ne sembolü var, seçicide de görünmediği için
kullanıcı seçimini düzeltemiyordu.

Ölçüldü (16 Eyl 2026, lokal ve prod): X-Country=GB → GBP, X-Country=CN → CNY;
ikisi de desteklenen listede ve kur tablosunda YOK.

Frappe runtime stub'lanıyor — bench kabuğu gerekmez.

Çalıştırma:
    cd apps/tradehub_core && python -m unittest tradehub_core.tests.test_currency_varsayilan_secimi
"""

from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path

_APP_ROOT = Path(__file__).resolve().parents[2]
if str(_APP_ROOT) not in sys.path:
	sys.path.insert(0, str(_APP_ROOT))


def _install_frappe_stub() -> None:
	"""`import frappe` yapan modülün yüklenebilmesi için asgari stub."""
	if "frappe" in sys.modules:
		return
	frappe_stub = types.ModuleType("frappe")

	def whitelist(*_a, **_k):
		def decorator(fn):
			return fn

		return decorator

	frappe_stub.whitelist = whitelist
	frappe_stub.request = None
	sys.modules["frappe"] = frappe_stub


_install_frappe_stub()

from tradehub_core.api import currency  # noqa: E402

# Lokal ve prod'da bugün tanımlı olan para birimleri.
DESTEKLENEN = [
	{"code": "USD", "symbol": "$", "decimal_places": 2},
	{"code": "TRY", "symbol": "₺", "decimal_places": 2},
	{"code": "EUR", "symbol": "€", "decimal_places": 2},
]


class VarsayilanParaBirimiTesti(unittest.TestCase):
	def setUp(self) -> None:
		self._orijinal = (
			currency._get_supported_currencies,
			currency._get_exchange_rates,
			currency._detect_country,
		)
		currency._get_supported_currencies = lambda: list(DESTEKLENEN)
		currency._get_exchange_rates = lambda: {"USD": {"USD": 1, "TRY": 48.3195, "EUR": 0.860419}}

	def tearDown(self) -> None:
		(
			currency._get_supported_currencies,
			currency._get_exchange_rates,
			currency._detect_country,
		) = self._orijinal

	def _ulkeyle_cagir(self, ulke: str) -> dict:
		currency._detect_country = lambda: ulke
		return currency.get_currency_settings()

	def test_desteklenen_eslesme_korunur(self) -> None:
		self.assertEqual(self._ulkeyle_cagir("TR")["defaultCurrency"], "TRY")
		self.assertEqual(self._ulkeyle_cagir("DE")["defaultCurrency"], "EUR")

	def test_desteklenmeyen_eslesme_usd_ye_duser(self) -> None:
		"""GB→GBP ve CN→CNY tanımsız; USD'ye düşmeli."""
		self.assertEqual(self._ulkeyle_cagir("GB")["defaultCurrency"], "USD")
		self.assertEqual(self._ulkeyle_cagir("CN")["defaultCurrency"], "USD")

	def test_haritadaki_her_ulke_desteklenen_bir_kod_dondurur(self) -> None:
		"""Sözleşmenin genel hâli: harita büyürse de bu iddia bozulmamalı."""
		kodlar = {c["code"] for c in DESTEKLENEN}
		for ulke in currency.COUNTRY_CURRENCY_MAP:
			with self.subTest(ulke=ulke):
				self.assertIn(self._ulkeyle_cagir(ulke)["defaultCurrency"], kodlar)

	def test_haritada_olmayan_ulke_usd_dondurur(self) -> None:
		self.assertEqual(self._ulkeyle_cagir("ZZ")["defaultCurrency"], "USD")


if __name__ == "__main__":
	unittest.main()
