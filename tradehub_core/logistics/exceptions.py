# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü exception sınıfları.

Tüm lojistik hataları LogisticsError'dan türer. Her sınıf üç şey taşır:

	http_status_code : Frappe'nin yanıta koyacağı HTTP durumu
	code             : istemcinin dallanma yapacağı KARARLI hata kodu
	docstring        : ne zaman fırlatıldığı

`code` değerleri sözleşmenin parçasıdır — `docs/logistics-api.schema.json`
içine bu sınıflardan üretilir ve istemci bunlara göre dallanır. Bir kodu
DEĞİŞTİRMEK kırıcı değişikliktir; yeni durum için yeni kod ekle.
"""

from __future__ import annotations

import frappe


class LogisticsError(frappe.ValidationError):
	"""Lojistik modülü temel hata sınıfı.

	HTTP 417 — Expectation Failed.
	Tüm lojistik hatalarının üst sınıfı.
	"""

	http_status_code = 417
	code = "LOGISTICS_ERROR"


class CarrierAPIError(LogisticsError):
	"""Kargo firması API'sinden dönen hata.

	HTTP 502 — Bad Gateway.
	Dış kargo API çağrısı başarısız olduğunda fırlatılır.
	"""

	http_status_code = 502
	code = "CARRIER_API_ERROR"


class CarrierTimeoutError(CarrierAPIError):
	"""Kargo firması API zaman aşımı hatası.

	HTTP 504 — Gateway Timeout.
	Dış kargo API çağrısı zaman aşımına uğradığında fırlatılır.
	"""

	http_status_code = 504
	code = "CARRIER_TIMEOUT"


class ShipmentStateError(LogisticsError):
	"""Geçersiz sevkiyat durum geçişi hatası.

	HTTP 409 — Conflict.
	İzin verilmeyen bir durum geçişi denendiğinde fırlatılır.
	"""

	http_status_code = 409
	code = "SHIPMENT_STATE_INVALID"


class TrackingNotFoundError(LogisticsError):
	"""Takip bilgisi bulunamadı hatası.

	HTTP 404 — Not Found.
	Belirtilen takip numarası veya sevkiyat bulunamadığında fırlatılır.
	"""

	http_status_code = 404
	code = "TRACKING_NOT_FOUND"


class IdempotencyConflictError(LogisticsError):
	"""Tekrarlanan istek çakışma hatası.

	HTTP 409 — Conflict.
	Aynı idempotency key ile farklı bir istek geldiğinde fırlatılır.
	"""

	http_status_code = 409
	code = "IDEMPOTENCY_CONFLICT"


class SplitInvariantError(LogisticsError):
	"""Sevkiyat bölme değişmezi ihlal hatası.

	HTTP 422 — Unprocessable Entity.
	Sevkiyat bölme işleminde INV-1..5 kuralları ihlal edildiğinde fırlatılır.
	"""

	http_status_code = 422
	code = "SPLIT_INVARIANT_VIOLATION"


class CarrierNotFoundError(LogisticsError):
	"""Kayıtlı olmayan kargo firması hatası.

	HTTP 404 — Not Found.
	Registry'de kayıtlı olmayan bir carrier_code istendiğinde fırlatılır.
	"""

	http_status_code = 404
	code = "CARRIER_NOT_FOUND"


class CarrierCapabilityError(LogisticsError):
	"""Kargo firması yetenek hatası.

	HTTP 400 — Bad Request.
	Kargo firmasının desteklemediği bir işlem talep edildiğinde fırlatılır.
	"""

	http_status_code = 400
	code = "CARRIER_CAPABILITY_UNSUPPORTED"


class FeatureDisabledError(LogisticsError):
	"""İlgili lojistik feature flag'i kapalı.

	HTTP 403 — Forbidden.
	Modül veya özellik `Logistics Settings` üzerinden kapatıldığında fırlatılır.
	Yetki eksikliğinden AYRI tutulur: istemci "yetkiniz yok" yerine
	"bu özellik henüz açık değil" göstermeli.
	"""

	http_status_code = 403
	code = "FEATURE_DISABLED"


class CapabilityRequiredError(LogisticsError):
	"""Gerekli capability kullanıcıda yok.

	HTTP 403 — Forbidden.
	Rol var ama ince taneli yetki (ör. `view.carrier_secret`) yoksa fırlatılır.
	"""

	http_status_code = 403
	code = "CAPABILITY_REQUIRED"
