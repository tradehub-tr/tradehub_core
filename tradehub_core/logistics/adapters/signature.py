# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Webhook HMAC imza dogrulamasi — SAF modul (W1).

Bu modul BILEREK frappe'siz ve stdlib-only tutulur:

- `BaseCarrierAdapter.verify_webhook_signature` default'u BU fonksiyonu cagirir.
- Webhook endpoint'i (api/v1/logistics_webhook.py, BE-3) adapter COZULEMESE
  bile fallback-HMAC olarak AYNI fonksiyonu cagirir (W1 kurali: imza
  dogrulamasi endpoint'te, adapter cozumu yalniz job'da).

Baslik adi ve prefix degerleri PARAMETREDIR — sabitlerin tek otoritesi
`logistics/constants.py`'dir (BE-1); bu modul sabit import etmez ki
endpoint <-> adapter arasinda cift kaynak olusmasin.
"""

from __future__ import annotations

import hashlib
import hmac


def verify_hmac_signature(
	raw_body: bytes,
	signature_header: str | None,
	secret: str,
	prefix: str = "sha256=",
) -> bool:
	"""HMAC-SHA256 webhook imzasini sabit-zamanli dogrula.

	Beklenen baslik bicimi: ``<prefix><hex(HMAC-SHA256(secret, raw_body))>``.

	Guvenlik sozlesmesi:
	- Karsilastirma HER ZAMAN `hmac.compare_digest` iledir ('==' yasak, AC-3).
	- Bos/None secret veya baslik, yanlis tip, bozuk prefix → False.
	- HICBIR girdi icin exception firlatmaz (endpoint'in tek tip 401
	  davranisini bozacak sizinti olmasin diye) — bilinmeyen hata da False'tur.
	- Hex kismi buyuk/kucuk harf duyarsiz kabul edilir (tasiyicilar
	  buyuk harfli hex gonderebiliyor); prefix ise birebir eslesmelidir.
	"""
	try:
		if not isinstance(raw_body, (bytes, bytearray)):
			return False
		if not secret or not isinstance(secret, str):
			return False
		if not signature_header or not isinstance(signature_header, str):
			return False
		if not isinstance(prefix, str):
			return False

		candidate: str = signature_header.strip()
		if not candidate.startswith(prefix):
			return False

		provided_hex: str = candidate[len(prefix) :].strip().lower()
		if not provided_hex:
			return False

		expected_hex: str = hmac.new(secret.encode("utf-8"), bytes(raw_body), hashlib.sha256).hexdigest()
		return hmac.compare_digest(expected_hex, provided_hex)
	except Exception:
		# Saf fonksiyon sozlesmesi: asla firlatma — dogrulanamayan her sey gecersizdir.
		# (ornek: non-ASCII hex string'de compare_digest TypeError firlatir)
		return False
