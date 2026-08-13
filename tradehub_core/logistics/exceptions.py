# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü exception sınıfları.

Tüm lojistik hataları LogisticsError'dan türer. Her exception sınıfı
uygun HTTP status kodu ve i18n-ready mesaj taşır.
"""

from __future__ import annotations

import frappe


class LogisticsError(frappe.ValidationError):
	"""Lojistik modülü temel hata sınıfı.

	HTTP 417 — Expectation Failed.
	Tüm lojistik hatalarının üst sınıfı.
	"""

	http_status_code = 417


class CarrierAPIError(LogisticsError):
	"""Kargo firması API'sinden dönen hata.

	HTTP 502 — Bad Gateway.
	Dış kargo API çağrısı başarısız olduğunda fırlatılır.
	"""

	http_status_code = 502


class CarrierTimeoutError(CarrierAPIError):
	"""Kargo firması API zaman aşımı hatası.

	HTTP 504 — Gateway Timeout.
	Dış kargo API çağrısı zaman aşımına uğradığında fırlatılır.
	"""

	http_status_code = 504


class ShipmentStateError(LogisticsError):
	"""Geçersiz sevkiyat durum geçişi hatası.

	HTTP 409 — Conflict.
	İzin verilmeyen bir durum geçişi denendiğinde fırlatılır.
	"""

	http_status_code = 409


class TrackingNotFoundError(LogisticsError):
	"""Takip bilgisi bulunamadı hatası.

	HTTP 404 — Not Found.
	Belirtilen takip numarası veya sevkiyat bulunamadığında fırlatılır.
	"""

	http_status_code = 404


class IdempotencyConflictError(LogisticsError):
	"""Tekrarlanan istek çakışma hatası.

	HTTP 409 — Conflict.
	Aynı idempotency key ile farklı bir istek geldiğinde fırlatılır.
	"""

	http_status_code = 409


class SplitInvariantError(LogisticsError):
	"""Sevkiyat bölme değişmezi ihlal hatası.

	HTTP 422 — Unprocessable Entity.
	Sevkiyat bölme işleminde INV-1..5 kuralları ihlal edildiğinde fırlatılır.
	"""

	http_status_code = 422


class CarrierNotFoundError(LogisticsError):
	"""Kayıtlı olmayan kargo firması hatası.

	HTTP 404 — Not Found.
	Registry'de kayıtlı olmayan bir carrier_code istendiğinde fırlatılır.
	"""

	http_status_code = 404


class CarrierCapabilityError(LogisticsError):
	"""Kargo firması yetenek hatası.

	HTTP 400 — Bad Request.
	Kargo firmasının desteklemediği bir işlem talep edildiğinde fırlatılır.
	"""

	http_status_code = 400
