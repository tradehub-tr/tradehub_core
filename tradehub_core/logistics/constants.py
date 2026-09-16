# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Lojistik modülü sabitleri.

Sevkiyat durumları, geçiş matrisi, tip tanımları ve feature flag
default'larını içerir. Tüm lojistik modülleri bu sabitleri referans alır.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Shipment Status
# ---------------------------------------------------------------------------


class ShipmentStatus:
	"""Sevkiyat durum string'leri."""

	DRAFT = "Draft"
	PENDING = "Pending"
	READY_FOR_PICKUP = "Ready for Pickup"
	PICKED_UP = "Picked Up"
	IN_TRANSIT = "In Transit"
	AT_WAREHOUSE = "At Warehouse"
	OUT_FOR_DELIVERY = "Out for Delivery"
	DELIVERED = "Delivered"
	RETURNED = "Returned"
	CANCELLED = "Cancelled"
	FAILED = "Failed"

	ALL: tuple[str, ...] = (
		DRAFT,
		PENDING,
		READY_FOR_PICKUP,
		PICKED_UP,
		IN_TRANSIT,
		AT_WAREHOUSE,
		OUT_FOR_DELIVERY,
		DELIVERED,
		RETURNED,
		CANCELLED,
		FAILED,
	)


# ---------------------------------------------------------------------------
# Terminal statuses — bu durumlara geçildiğinde sevkiyat kapanır
# ---------------------------------------------------------------------------

TERMINAL_STATUSES: set[str] = {
	ShipmentStatus.CANCELLED,
	ShipmentStatus.RETURNED,
	ShipmentStatus.DELIVERED,
}

# ---------------------------------------------------------------------------
# Allowed transitions — durum geçiş matrisi
# ---------------------------------------------------------------------------

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
	ShipmentStatus.DRAFT: {
		ShipmentStatus.PENDING,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.PENDING: {
		ShipmentStatus.READY_FOR_PICKUP,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.READY_FOR_PICKUP: {
		ShipmentStatus.PICKED_UP,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.PICKED_UP: {
		ShipmentStatus.IN_TRANSIT,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.IN_TRANSIT: {
		ShipmentStatus.AT_WAREHOUSE,
		ShipmentStatus.OUT_FOR_DELIVERY,
		ShipmentStatus.DELIVERED,
		ShipmentStatus.FAILED,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.AT_WAREHOUSE: {
		ShipmentStatus.IN_TRANSIT,
		ShipmentStatus.OUT_FOR_DELIVERY,
		ShipmentStatus.CANCELLED,
	},
	ShipmentStatus.OUT_FOR_DELIVERY: {
		ShipmentStatus.DELIVERED,
		ShipmentStatus.FAILED,
		ShipmentStatus.RETURNED,
	},
	ShipmentStatus.DELIVERED: set(),
	ShipmentStatus.RETURNED: set(),
	ShipmentStatus.CANCELLED: set(),
	ShipmentStatus.FAILED: {
		ShipmentStatus.IN_TRANSIT,
		ShipmentStatus.RETURNED,
		ShipmentStatus.CANCELLED,
	},
}


# ---------------------------------------------------------------------------
# Satıcı geçiş alt kümesi — G0 rol matrisi (C2 satırı)
#
# Satıcı sevkiyat DocPerm'inde write taşımaz; tek istisna FBM/Trendyol'daki
# "kargoya verildi" onayıdır: kendi tenant'ındaki sevkiyatı Alıma Hazır →
# Alındı'ya geçirebilir (api/v1/shipment.update_shipment_status dar yolu).
# Genişletme kararı (örn. SELLER_VEHICLE kanalında teslimat zinciri) D1
# fazına ait — buraya durum eklemek FE'ye buton açar, bilinçli dar tutuldu.
# ---------------------------------------------------------------------------

SELLER_ALLOWED_TRANSITIONS: dict[str, set[str]] = {
	ShipmentStatus.READY_FOR_PICKUP: {
		ShipmentStatus.PICKED_UP,
	},
}


def is_seller_transition_allowed(from_status: str, to_status: str) -> bool:
	"""Satıcının yapabileceği geçiş mi? (ALLOWED_TRANSITIONS'ın alt kümesi.)"""
	return to_status in SELLER_ALLOWED_TRANSITIONS.get(from_status, set())


# ---------------------------------------------------------------------------
# Durum geçiş kuralı — saf fonksiyon (Dalga B, LOG-049)
#
# Bu fonksiyon BİLİNÇLİ olarak frappe'siz tutulmuştur: hem shipment_service
# (transition_status) hem logistics/hooks.py (validate_state_transition) aynı
# kuralı buradan kullanır (DRY) ve tests/test_state_machine.py bench olmadan
# standalone çalıştırabilir.
# ---------------------------------------------------------------------------


def is_transition_allowed(from_status: str, to_status: str) -> bool:
	"""from_status → to_status geçişi ALLOWED_TRANSITIONS matrisine göre geçerli mi?

	Kurallar:
	  - Aynı duruma geçiş her zaman True (idempotent no-op — motor event
	    üretmeden dokümanı olduğu gibi döndürür).
	  - Terminal durumlardan çıkış matriste boş set olduğu için otomatik False.
	  - Matriste tanımsız (bilinmeyen) kaynak durum → False (fail-closed).

	Args:
		from_status: Mevcut sevkiyat durumu.
		to_status: Hedef sevkiyat durumu.

	Returns:
		Geçiş izinliyse True.
	"""
	if from_status == to_status:
		return True
	return to_status in ALLOWED_TRANSITIONS.get(from_status, set())


# ---------------------------------------------------------------------------
# Shipment Type
# ---------------------------------------------------------------------------


class ShipmentType:
	"""Sevkiyat tipleri."""

	STANDARD = "Standard"
	SELLER_DELIVERY = "Seller Delivery"
	BUYER_PICKUP = "Buyer Pickup"
	WAREHOUSE_TRANSFER = "Warehouse Transfer"

	ALL: tuple[str, ...] = (
		STANDARD,
		SELLER_DELIVERY,
		BUYER_PICKUP,
		WAREHOUSE_TRANSFER,
	)


# ---------------------------------------------------------------------------
# Leg Type
# ---------------------------------------------------------------------------


class LegType:
	"""Sevkiyat bacak tipleri."""

	PICKUP = "Pickup"
	LINE_HAUL = "Line Haul"
	TRANSFER = "Transfer"
	LAST_MILE = "Last Mile"
	RETURN = "Return"

	ALL: tuple[str, ...] = (
		PICKUP,
		LINE_HAUL,
		TRANSFER,
		LAST_MILE,
		RETURN,
	)


# ---------------------------------------------------------------------------
# Leg Status
# ---------------------------------------------------------------------------


class LegStatus:
	"""Sevkiyat bacak durumları."""

	PLANNED = "Planned"
	IN_PROGRESS = "In Progress"
	ARRIVED = "Arrived"
	COMPLETED = "Completed"
	CANCELLED = "Cancelled"

	ALL: tuple[str, ...] = (
		PLANNED,
		IN_PROGRESS,
		ARRIVED,
		COMPLETED,
		CANCELLED,
	)


# ---------------------------------------------------------------------------
# Cost Paid By
# ---------------------------------------------------------------------------


class CostPaidBy:
	"""Kargo ücretini ödeyen taraf."""

	SELLER = "Seller"
	BUYER = "Buyer"
	PLATFORM = "Platform"

	ALL: tuple[str, ...] = (
		SELLER,
		BUYER,
		PLATFORM,
	)


# ---------------------------------------------------------------------------
# Feature flag defaults
# ---------------------------------------------------------------------------

LOGISTICS_FEATURE_FLAGS: dict[str, bool] = {
	"carrier_api_enabled": False,
	"multi_carrier_enabled": False,
	"shipping_zone_pricing_enabled": False,
	"auto_tracking_enabled": False,
	"split_shipment_enabled": False,
	"multi_leg_enabled": False,
	"cost_estimation_enabled": False,
	"webhook_notifications_enabled": False,
	# Inbound carrier webhook ucu (09-BE webhook dilimi). Mevcut
	# `webhook_notifications_enabled` GIDEN bildirimlerin flag'i — adi
	# yaniltici oldugu icin YENIDEN KULLANILMADI, gelen taraf ayri flag
	# (flag enflasyonu itirazi Bora'ya sunuldu, spec risks listesi).
	"carrier_webhook_enabled": False,
	"return_flow_enabled": False,
	"seller_delivery_enabled": False,
	"buyer_pickup_enabled": False,
	"warehouse_transfer_enabled": False,
}


# ---------------------------------------------------------------------------
# Genel sabitler
# ---------------------------------------------------------------------------

CACHE_PREFIX: str = "tc:logistics:"

# Tek dogruluk kaynagi shipment.json naming_series options'i — bu sabit yalnizca
# referans amaclidir (runtime adlandirmayi Shipment DocType'in kendi serisi yapar).
SHIPMENT_NAMING_SERIES: str = "SHP-.YYYY.-.#####"

API_VERSION: str = "v1"


# ---------------------------------------------------------------------------
# Entegrasyon logu — Select sozlesmesi (09-BE A)
# ---------------------------------------------------------------------------

# TEK DOGRULUK KAYNAGI. Ayni liste daha once DORT yerde ayri ayri yaziliydi:
# adapters/http_client.py, integration/log.py, contract.py ve
# carrier_integration_log.json. Dordunun birbirinden sapmasi sessiz veri kaybi
# uretir: adapter'in gecerli saydigi bir deger DocType'ta Select disi kalir ve
# kayit sozlesme ihlali olarak yazilir. Python tarafi buradan import eder;
# DocType JSON'u (Frappe sema dosyasi oldugu icin import edemez) test ile
# bu kumeye baglanir: tests/test_integration_log.py::TestContractSingleSource.
INTEGRATION_LOG_OPERATIONS: frozenset[str] = frozenset(
	{
		"create_shipment",
		"cancel",
		"label",
		"quote",
		"track",
		"webhook",
	}
)

INTEGRATION_LOG_DIRECTIONS: frozenset[str] = frozenset({"outbound", "inbound"})

# DocType Select `options` alani SIRALI bir metindir; testin karsilastirabilmesi
# ve JSON'un elle guncellenebilmesi icin kanonik sira burada tutulur.
INTEGRATION_LOG_OPERATION_ORDER: tuple[str, ...] = (
	"create_shipment",
	"cancel",
	"label",
	"quote",
	"track",
	"webhook",
)

INTEGRATION_LOG_DIRECTION_ORDER: tuple[str, ...] = ("outbound", "inbound")

# Entegrasyon logu saklama suresinin ALT SINIRI (gun). `0` "saklama kapali"
# demektir ve o anlam korunur; `0` disindaki her deger bu sinirin altina
# inemez.
#
# OLCULDU (denetim 2026-08-28): `Logistics Settings.validate` yalnizca desi
# bolenini dogruluyordu; Marketplace Admin `integration_log_retention_days`
# alanini `1` (hatta `-5`) yapabiliyordu ve deger DB'ye yaziliyordu. `1` gun
# demek, ertesi gunku saklama kosumunun denetim/entegrasyon izini imha etmesi
# demek — silme yolunun DocPerm'i kapatildigi icin (bkz.
# `carrier_integration_log.py` docstring) geriye kalan TEK silme yolu budur ve
# bir alt sinira baglanmak zorunda.
#
# 30 gun: bir olayin fark edilip incelenmesi icin en az bir aylik pencere
# birakir; ust sinir YOK (saklamayi uzatmak guvenli tarafta).
MIN_INTEGRATION_LOG_RETENTION_DAYS: int = 30


# ---------------------------------------------------------------------------
# Carrier webhook alicisi — sabitler (09-BE webhook dilimi)
# ---------------------------------------------------------------------------

# Guest webhook ucunun kabul ettigi en buyuk ham govde (bayt). Imza
# HESAPLANMADAN once kontrol edilir (AC-5): once dogrulayip sonra boyuta
# bakmak, saldirgana bedava HMAC hesabi yaptirmak olurdu. Asilirsa 413.
# 128 KB, taniiyici push payload'lari icin comert bir ust sinir; log
# katmaninin 64 KB kirpma davranisindan BILEREK buyuk — kirpma loglama
# sorunu, kabul siniri guvenlik sorunu.
MAX_WEBHOOK_BODY_BYTES: int = 131072

# Ayni ham govdenin Redis dedupe kaydinin TTL'i — 48 saat (W4: AC-7'deki
# "48 saat" bu sabitle okunur, saniye degil). Tasiyicilarin retry
# pencereleri tipik 24-72 saat; 48 saat retry firtinasini yutar, uc katmanli
# idempotency'nin ilk katmanidir (digerleri: transition no-op + event_hash
# unique — TTL dolsa bile onlar tutar).
WEBHOOK_DEDUPE_TTL_SECONDS: int = 172800

# Imza basligi ve deger oneki. Deger bicimi: "sha256=<hex(HMAC-SHA256)>".
# Onek, ileride farkli algoritma/versiyon gerektiginde ("sha512=..." gibi)
# istemciyi kirmadan ayirt etmeye yarar — GitHub webhook konvansiyonu.
WEBHOOK_SIGNATURE_HEADER: str = "X-Webhook-Signature"
WEBHOOK_SIGNATURE_PREFIX: str = "sha256="


# ---------------------------------------------------------------------------
# Kimlik bilgisi alanlari — deger-tabanli redaksiyonun TEK KAYNAGI
# ---------------------------------------------------------------------------

# `Carrier Account` uzerinde DEGERI sir olan alanlar. Uc tuketicisi var ve
# ucu de BURADAN import eder:
#   * `logistics/integration/secrets.py::collect_secret_values` — log katmaninin
#     deger-tabanli redaksiyonu icin plaintext toplar
#   * `logistics/adapters/http_client.py` — o toplayiciyi cagirir
#   * `api/v1/logistics_admin.py::SECRET_FIELDS` — degeri yanita KONMAYAN alanlar
#
# ONCEKI DURUM: liste iki yerde AYRI ICERIKLE yaziliydi (transport'ta yedi ad,
# API katmaninda dort) ve transport'taki yorum "ayni kume ... ikisi birlikte
# degismeli" diyerek YANLIS bilgi veriyordu. Fazladan uc ad (`refresh_token`,
# `password`, `secret`) DocType'ta hic yok — spekulatifti.
#
# KATMAN GEREKCESI YOK: `api/v1/logistics_admin.py` zaten
# `tradehub_core.logistics.api_utils`'ten import ediyor; api -> logistics
# yonu KURULU. Kume, `Carrier Account` meta'sindaki `fieldtype == "Password"`
# alanlariyla BIREBIR ayni olmak zorunda — sozlesme testi bunu kilitler
# (tests/test_carrier_account.py::TestCredentialSecretFieldsContract). DocType'a
# yeni bir sir alani eklendiginde redaksiyon sessizce kor kalmasin.
CREDENTIAL_SECRET_FIELDS: tuple[str, ...] = (
	"api_key",
	"api_secret",
	"webhook_secret",
	"access_token",
)
