# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""TUR-102: Lojistik katalog seed verileri.

Bu veri sozluklerini v15_log024-036 seed patch'leri tuketiyor
(Shipping Channel/Method, Logistics Provider, Vehicle Type, Package Type,
Shipment Exception Code). Patch'lerin okumadigi anahtarlar burada tutulmaz.

Kullanim:
	from tradehub_core.logistics.seed import LOGISTICS_PROVIDERS, PACKAGE_TYPES
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Kargo firmalari
# ---------------------------------------------------------------------------

LOGISTICS_PROVIDERS: list[dict[str, Any]] = [
	{"provider_name": "Yurtiçi Kargo", "code": "YK", "country": "TR"},
	{"provider_name": "Aras Kargo", "code": "AK", "country": "TR"},
	{"provider_name": "MNG Kargo", "code": "MNG", "country": "TR"},
	{"provider_name": "PTT Kargo", "code": "PTT", "country": "TR"},
	{"provider_name": "Sürat Kargo", "code": "SK", "country": "TR"},
	{"provider_name": "UPS", "code": "UPS", "country": "US"},
	{"provider_name": "DHL", "code": "DHL", "country": "DE"},
	{"provider_name": "FedEx", "code": "FEDEX", "country": "US"},
]

# ---------------------------------------------------------------------------
# Paket tipleri
# ---------------------------------------------------------------------------

PACKAGE_TYPES: list[dict[str, Any]] = [
	{"type_name": "Standart Koli", "code": "BOX", "max_weight_kg": 30},
	{"type_name": "Buyuk Koli", "code": "LBOX", "max_weight_kg": 50},
	{"type_name": "Palet", "code": "PLT", "max_weight_kg": 1000},
	{"type_name": "Zarf", "code": "ENV", "max_weight_kg": 1},
	{"type_name": "Tup", "code": "TUBE", "max_weight_kg": 15},
]

# ---------------------------------------------------------------------------
# Arac tipleri
# ---------------------------------------------------------------------------

VEHICLE_TYPES: list[dict[str, Any]] = [
	{"type_name": "Motokurye", "code": "MOTO", "max_weight_kg": 10},
	{"type_name": "Panelvan", "code": "VAN", "max_weight_kg": 500},
	{"type_name": "Kamyonet", "code": "TRUCK_S", "max_weight_kg": 3500},
	{"type_name": "Kamyon", "code": "TRUCK_M", "max_weight_kg": 12000},
	{"type_name": "TIR", "code": "TRUCK_L", "max_weight_kg": 24000},
]

# ---------------------------------------------------------------------------
# Istisna kodlari
# ---------------------------------------------------------------------------

# Severity + kategori + aksiyon TEK KAYNAK olarak asagidaki EXCEPTION_META'da tutulur
# (seed patch'i v15_log034 + Storybook fixture ureticisi ayni sozlugu okur).
# Buradaki eski "severity" anahtari hic okunmadigi icin kaldirildi (P2-2).
EXCEPTION_CODES: list[dict[str, Any]] = [
	{"code": "ADDR_NOT_FOUND", "label": "Adres bulunamadi"},
	{"code": "RECIPIENT_ABSENT", "label": "Alici adreste degil"},
	{"code": "REFUSED", "label": "Teslim alinmadi / reddedildi"},
	{"code": "DAMAGED", "label": "Paket hasarli"},
	{"code": "CUSTOMS_HOLD", "label": "Gumrukte bekliyor"},
	{"code": "WRONG_ADDRESS", "label": "Yanlis adres"},
	{"code": "SIZE_EXCEED", "label": "Boyut/agirlik limiti asildi"},
	{"code": "WEATHER", "label": "Hava kosullari nedeniyle gecikme"},
]

# code -> (severity, exception_category, is_retriable, suggested_action)
# Seed severity esleme kurali: critical->Critical, high->Warning, medium->Warning, low->Info
#
# Seed patch'i (v15_log034) ile Storybook fixture ureticisi ayni sozlugu okur.
# Ayri dursalardi fixture kategoriyi alan tipinden uydururdu -- tasarim
# incelemesi "DAMAGED / Customs" gibi gercekte olmayan eslesmeler gorurdu.
EXCEPTION_META: dict[str, tuple[str, str, int, str]] = {
	"ADDR_NOT_FOUND": ("Warning", "Address", 1, "Alıcıdan adres teyidi alın, düzeltme sonrası yeniden dene"),
	"RECIPIENT_ABSENT": ("Warning", "Recipient", 1, "Sonraki gün yeniden dağıtım dene"),
	"REFUSED": ("Warning", "Recipient", 0, "İade sürecini başlat"),
	"DAMAGED": ("Critical", "Package", 0, "Hasar tutanağı + satıcıya bildirim"),
	"CUSTOMS_HOLD": ("Warning", "Customs", 1, "Gümrük evraklarını kontrol et"),
	"WRONG_ADDRESS": ("Warning", "Address", 1, "Doğru adresi al, yönlendirme talep et"),
	"SIZE_EXCEED": ("Warning", "Package", 0, "Farklı servis/kanal ile yeniden gönder"),
	"WEATHER": ("Info", "Weather", 1, "Bekle; SLA'ya gecikme notu düş"),
}

# ---------------------------------------------------------------------------
# Gonderim kanallari
# ---------------------------------------------------------------------------

# Gorunen adlar (Turkce aksanli) TEK KAYNAK olarak
# v15_log024_seed_shipping_channels_methods.CHANNEL_DISPLAY_NAMES'te tutulur —
# buradaki eski "name" anahtari hic okunmadigi icin kaldirildi (P2-2).
SHIPPING_CHANNELS: list[dict[str, Any]] = [
	{"code": "CARGO"},
	{"code": "WAREHOUSE"},
	{"code": "COURIER"},
	{"code": "SELLER_VEHICLE"},
	{"code": "BUYER_PICKUP"},
]
