# Copyright (c) 2026, TradeHub Team and contributors
# For license information, please see license.txt

"""Sevkiyat alan sözleşmesi — GEÇİCİ (provisional).

NE İŞE YARAR:
	Faz D'de tasarlanan operasyon ekranları henüz var olmayan bir veri modeline
	dayanıyor (`Shipment` DocType'ı Faz F'te gelecek). Ekranların uydurma
	mock'lara değil, YAZILI BİR SÖZLEŞMEYE bağlanması için alanlar burada
	tanımlanıyor; `scripts/gen_logistics_types.py` bunlardan şema, TypeScript
	tipi ve Storybook mock verisi üretiyor.

NEDEN "PROVISIONAL":
	Bu tanımlar bir DocType'tan türetilmedi — Linear görev metinlerindeki kapsam
	ve kabul kriterlerinden çıkarıldı. Katalog sözleşmesinden farkları:

	  katalog  → DocType JSON'u var, alan TİPLERİ oradan okunuyor, DOĞRULANMIŞ
	  sevkiyat → DocType yok, tipler burada beyan ediliyor, DOĞRULANMAMIŞ

	Şemada `"provisional": true` ile işaretlenirler. **Faz F backend'i bu
	sözleşmeye implement eder**; sapma gerekiyorsa açık bir karar olarak alınır
	ve sürüm politikası uygulanır (bkz. docs/LOGISTICS-API-CONTRACT.md §10).

KAYNAK GÖREVLER:
	TUR-105 Shipment, Item, Package, Leg, Event · adres snapshot · naming
	TUR-106 bölme, kalan miktar, sipariş genel durumu
	TUR-107 manuel taşıyıcı, takip no, maliyet, ödeyen taraf, belge
	TUR-108 sürücü/araç, randevu, teslim kodu
	TUR-109 bacak, şube, aktarma, kargoya devir
	TUR-112 olay normalizasyonu, kaynak, duplicate koruması
	TUR-114 paket, X/Y koli, barkod, etiket
	TUR-115 istasyon, konum, teslim kanıtı
	TUR-116 iade talebi, karar, depo kontrolü, kapanış
	TUR-121 alış maliyeti / satış ücreti ayrımı, snapshot, kural izi
"""

from __future__ import annotations

from typing import Any

#: Alan tipleri katalog sözleşmesiyle aynı sözlüğü kullanır (Frappe fieldtype
#: adları) — üretici tek bir tip eşlemesi bilsin diye.
#:
#: Her alan: (fieldname, fieldtype, required, note)
Field = tuple[str, str, bool, str]


def _f(name: str, ftype: str, required: bool = False, note: str = "") -> dict[str, Any]:
	return {"name": name, "type": ftype, "required": required, "note": note}


# ---------------------------------------------------------------------------
# Sevkiyat çekirdeği — TUR-105
# ---------------------------------------------------------------------------

SHIPMENT_LIST_FIELDS = [
	_f("name", "Data", True, "SHP-YYYY-##### (TUR-105 naming)"),
	_f("order", "Link", True, "Kaynak sipariş"),
	_f("seller_profile", "Link", True, "Tenant sahibi — satıcı yalnız kendi grubunu görür"),
	_f("buyer", "Link", False, "Alıcı kullanıcı"),
	_f("status", "Select", True, "ShipmentStatus enum'ından"),
	_f("shipment_type", "Select", True, "ShipmentType enum'ından"),
	_f("channel", "Link", False, "Shipping Channel"),
	_f("carrier", "Link", False, "Logistics Provider"),
	_f("carrier_service", "Link", False, "Carrier Service"),
	_f("tracking_number", "Data", False, "Takip veya fiş numarası (TUR-107)"),
	_f("package_count", "Int", False, "Toplam koli adedi"),
	_f("chargeable_weight", "Float", False, "Ücretlendirilebilir ağırlık (desi kuralı)"),
	_f("shipped_date", "Date", False, "Sevk tarihi"),
	_f("estimated_delivery_date", "Date", False, "Tahmini teslim"),
	_f("delivered_date", "Date", False, "Gerçekleşen teslim"),
	_f("is_delayed", "Check", False, "Gecikme tespiti (TUR-112)"),
	_f("modified", "Datetime", False, "Son güncelleme"),
]

SHIPMENT_DETAIL_FIELDS = [
	_f("origin_address_snapshot", "JSON", False, "Adres SNAPSHOT — sonradan bozulmaz (TUR-105)"),
	_f("destination_address_snapshot", "JSON", False, "Adres snapshot"),
	_f("warehouse", "Link", False, "Çıkış deposu"),
	_f("total_weight", "Float", False),
	_f("total_desi", "Float", False),
	_f("cost_paid_by", "Select", False, "CostPaidBy enum'ından (TUR-107)"),
	_f("carrier_cost", "Currency", False, "Taşıyıcı ALIŞ maliyeti — TUR-121 ayrımı"),
	_f("customer_charge", "Currency", False, "Müşteriye YANSITILAN ücret"),
	_f("currency", "Link", False),
	_f("exception_code", "Link", False, "Shipment Exception Code"),
	_f("delivery_code_required", "Check", False, "Tek kullanımlık teslim kodu (TUR-108)"),
	_f("payment_required_before_delivery", "Check", False, "Ödeme şartlı teslim (TUR-108)"),
	_f("notes", "Small Text", False),
]

SHIPMENT_ITEM_FIELDS = [
	_f("item", "Link", True, "Listing / ürün"),
	_f("item_name", "Data", True),
	_f("ordered_qty", "Float", True, "Siparişteki miktar"),
	_f("shipped_qty", "Float", True, "Bu sevkiyattaki miktar"),
	_f("remaining_qty", "Float", False, "Kalan — TUR-106 invariant'ı"),
	_f("uom", "Data", False, "Birim"),
	_f("weight_kg", "Float", False),
	_f("returned_qty", "Float", False, "İade edilen (TUR-116)"),
]

SHIPMENT_PACKAGE_FIELDS = [
	_f("package_code", "Data", True, "Benzersiz paket kodu (TUR-114)"),
	_f("sequence_label", "Data", True, "X/Y koli numarası, ör. 2/5"),
	_f("package_type", "Link", False, "Package Type katalogundan"),
	_f("parent_package", "Data", False, "Palet hiyerarşisi (TUR-120)"),
	_f("length_cm", "Float", False),
	_f("width_cm", "Float", False),
	_f("height_cm", "Float", False),
	_f("weight_kg", "Float", False),
	_f("desi", "Float", False),
	_f("barcode_url", "Data", False, "Barkod görseli"),
	_f("label_url", "Data", False, "Etiket PDF'i"),
	_f("label_printed_at", "Datetime", False, "Yeniden üretim geçmişi için"),
]

SHIPMENT_LEG_FIELDS = [
	_f("sequence", "Int", True, "Bacak sırası"),
	_f("leg_type", "Select", True, "LegType enum'ından"),
	_f("status", "Select", True, "LegStatus enum'ından"),
	_f("carrier", "Link", False, "Bu bacağın taşıyıcısı"),
	_f("origin_branch", "Link", False, "Carrier Branch — çıkış"),
	_f("destination_branch", "Link", False, "Carrier Branch — varış"),
	_f("handover_point", "Data", False, "Kargoya devir noktası (TUR-109)"),
	_f("handover_proof", "Data", False, "Devir kanıtı"),
	_f("vehicle_type", "Link", False),
	_f("started_at", "Datetime", False),
	_f("completed_at", "Datetime", False),
	_f("cost", "Currency", False, "Bacak bazlı maliyet — bağımsız görülebilmeli"),
]

SHIPMENT_EVENT_FIELDS = [
	_f("event_time", "Datetime", True),
	_f("status", "Select", True, "Normalize edilmiş iç durum"),
	_f("source", "Select", True, "manual | api | webhook | polling (TUR-112)"),
	_f("carrier_status_code", "Data", False, "Ham taşıyıcı kodu — izlenebilirlik"),
	_f("carrier_status_text", "Data", False),
	_f("location", "Data", False, "İstasyon/şube (TUR-115)"),
	_f("description", "Small Text", False),
	_f("exception_code", "Link", False),
	_f("actor", "Link", False, "Manuel değişiklikte kullanıcı (audit)"),
	_f("reason", "Small Text", False, "Manuel değişiklik gerekçesi (TUR-107)"),
	_f("dedupe_key", "Data", False, "Aynı olay iki kez işlenmesin (TUR-112)"),
]

# ---------------------------------------------------------------------------
# Teslim kanıtı — TUR-115
# ---------------------------------------------------------------------------

PROOF_OF_DELIVERY_FIELDS = [
	_f("delivered_at", "Datetime", True),
	_f("received_by", "Data", True, "Teslim alan kişi"),
	_f("delivery_code_used", "Check", False, "Tek kullanımlık kod doğrulandı mı"),
	_f("signature_url", "Data", False, "Yetki kontrollü"),
	_f("photo_url", "Data", False, "Yetki kontrollü"),
	_f("document_url", "Data", False),
	_f("location_source", "Select", False, "Konum kaynağı görünür olmalı"),
	_f("location_recorded_at", "Datetime", False),
]

# ---------------------------------------------------------------------------
# İade — TUR-116
# ---------------------------------------------------------------------------

RETURN_REQUEST_LIST_FIELDS = [
	_f("name", "Data", True),
	_f("order", "Link", True),
	_f("shipment", "Link", False, "Orijinal sevkiyatla çift yönlü ilişki"),
	_f("seller_profile", "Link", True),
	_f("buyer", "Link", True),
	_f("status", "Select", True, "requested | approved | rejected | in_transit | inspecting | closed"),
	_f("reason", "Select", True, "İade nedeni"),
	_f("requested_at", "Datetime", True),
	_f("decided_at", "Datetime", False),
	_f("is_closed", "Check", False, "Kapanınca DEĞİŞTİRİLEMEZ"),
]

RETURN_REQUEST_DETAIL_FIELDS = [
	_f("decision_note", "Small Text", False, "Onay/red gerekçesi — audit"),
	_f("return_shipment", "Link", False, "Ters yönlü sevkiyat"),
	_f("return_label_url", "Data", False),
	_f("inspection_result", "Select", False, "ok | damaged | missing_parts | mismatch"),
	_f("inspection_note", "Small Text", False),
	_f("refund_amount", "Currency", False),
	_f("refund_triggered_at", "Datetime", False, "Escrow/para iadesi tetikleyicisi"),
	_f("exchange_shipment", "Link", False, "Değişim gönderisi"),
]

# ---------------------------------------------------------------------------
# Fiyat teklifi — TUR-121
# ---------------------------------------------------------------------------

PRICE_QUOTE_FIELDS = [
	_f("quote_id", "Data", True),
	_f("carrier", "Link", True),
	_f("carrier_service", "Link", False),
	_f("carrier_cost", "Currency", True, "Taşıyıcı ALIŞ maliyeti"),
	_f("customer_charge", "Currency", True, "Müşteriye YANSITILAN ücret — ayrı raporlanır"),
	_f("currency", "Link", True),
	_f("chargeable_weight", "Float", False),
	_f("applied_rule", "Data", False, "Hangi kural uygulandı — AÇIKLANABİLİR olmalı"),
	_f("rule_priority", "Int", False, "Çakışma çözümü deterministik"),
	_f("valid_until", "Datetime", False, "Teklif geçerlilik süresi"),
	_f("is_snapshot", "Check", False, "Sipariş anındaki fiyat korunur"),
	_f("surcharges", "JSON", False, "Yakıt farkı, kat teslimatı, sigorta vb."),
]

# ---------------------------------------------------------------------------
# Şemaya girecek toplu tanım
# ---------------------------------------------------------------------------

PROVISIONAL_ENTITIES: dict[str, dict[str, Any]] = {
	"shipment": {
		"label": "Sevkiyat",
		"source_tasks": ["TUR-105", "TUR-106", "TUR-107"],
		"list_fields": SHIPMENT_LIST_FIELDS,
		"detail_fields": SHIPMENT_DETAIL_FIELDS,
		"child_tables": {
			"items": SHIPMENT_ITEM_FIELDS,
			"packages": SHIPMENT_PACKAGE_FIELDS,
			"legs": SHIPMENT_LEG_FIELDS,
			"events": SHIPMENT_EVENT_FIELDS,
		},
	},
	"proof_of_delivery": {
		"label": "Teslim Kanıtı",
		"source_tasks": ["TUR-115"],
		"list_fields": PROOF_OF_DELIVERY_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"return_request": {
		"label": "İade Talebi",
		"source_tasks": ["TUR-116"],
		"list_fields": RETURN_REQUEST_LIST_FIELDS,
		"detail_fields": RETURN_REQUEST_DETAIL_FIELDS,
		"child_tables": {},
	},
	"price_quote": {
		"label": "Fiyat Teklifi",
		"source_tasks": ["TUR-121"],
		"list_fields": PRICE_QUOTE_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
}


# ---------------------------------------------------------------------------
# Storybook örnek verisi
# ---------------------------------------------------------------------------
# Alan tanımlarının YANINDA duruyor ki ikisi birlikte değişsin. Veriler
# TUTARLI olmak zorunda: olay akışı duruma, miktarlar birbirine, paket
# ölçüleri desi kuralına uymalı — tasarım incelemesi tutarsız veriyle
# yanıltıcı olur.

SAMPLE_SHIPMENTS: list[dict[str, Any]] = [
	{
		"name": "SHP-2026-00042",
		"order": "ORD-2026-00871",
		"seller_profile": "SEL-00001",
		"buyer": "alici@ornek.com",
		"status": "In Transit",
		"shipment_type": "Standard",
		"channel": "CARGO",
		"carrier": "YK",
		"carrier_service": "YK-STD",
		"tracking_number": "7801234567890",
		"package_count": 3,
		"chargeable_weight": 42.0,
		"shipped_date": "2026-08-10",
		"estimated_delivery_date": "2026-08-13",
		"delivered_date": None,
		"is_delayed": 0,
		"modified": "2026-08-12 09:14:00",
	},
	{
		"name": "SHP-2026-00041",
		"order": "ORD-2026-00871",
		"seller_profile": "SEL-00001",
		"buyer": "alici@ornek.com",
		"status": "Delivered",
		"shipment_type": "Standard",
		"channel": "CARGO",
		"carrier": "AK",
		"carrier_service": "AK-STD",
		"tracking_number": "AK-556677",
		"package_count": 1,
		"chargeable_weight": 8.0,
		"shipped_date": "2026-08-06",
		"estimated_delivery_date": "2026-08-09",
		"delivered_date": "2026-08-08",
		"is_delayed": 0,
		"modified": "2026-08-08 16:22:00",
	},
	{
		"name": "SHP-2026-00038",
		"order": "ORD-2026-00863",
		"seller_profile": "SEL-00002",
		"buyer": "kurumsal@ornek.com",
		"status": "Failed",
		"shipment_type": "Standard",
		"channel": "CARGO",
		"carrier": "MNG",
		"carrier_service": None,
		"tracking_number": "MNG-99001",
		"package_count": 2,
		"chargeable_weight": 120.0,
		"shipped_date": "2026-08-04",
		"estimated_delivery_date": "2026-08-07",
		"delivered_date": None,
		"is_delayed": 1,
		"modified": "2026-08-11 11:05:00",
	},
	{
		"name": "SHP-2026-00035",
		"order": "ORD-2026-00840",
		"seller_profile": "SEL-00001",
		"buyer": "alici@ornek.com",
		"status": "Ready for Pickup",
		"shipment_type": "Buyer Pickup",
		"channel": "BUYER_PICKUP",
		"carrier": None,
		"carrier_service": None,
		"tracking_number": None,
		"package_count": 1,
		"chargeable_weight": 15.0,
		"shipped_date": None,
		"estimated_delivery_date": "2026-08-14",
		"delivered_date": None,
		"is_delayed": 0,
		"modified": "2026-08-12 08:00:00",
	},
	{
		"name": "SHP-2026-00030",
		"order": "ORD-2026-00822",
		"seller_profile": "SEL-00002",
		"buyer": "kurumsal@ornek.com",
		"status": "At Warehouse",
		"shipment_type": "Warehouse Transfer",
		"channel": "WAREHOUSE",
		"carrier": "SK",
		"carrier_service": None,
		"tracking_number": "AMB-4471",
		"package_count": 12,
		"chargeable_weight": 860.0,
		"shipped_date": "2026-08-09",
		"estimated_delivery_date": "2026-08-16",
		"delivered_date": None,
		"is_delayed": 0,
		"modified": "2026-08-11 19:40:00",
	},
]

#: SHP-2026-00042'nin detayı — liste satırıyla TUTARLI olmalı
SAMPLE_SHIPMENT_DETAIL: dict[str, Any] = {
	"origin_address_snapshot": {
		"unvan": "Demir Tekstil Ltd. Şti.",
		"adres": "İkitelli OSB, Bağcılar Cad. No:12",
		"ilce": "Başakşehir",
		"il": "İstanbul",
		"posta_kodu": "34490",
		"telefon": "+90 212 000 00 00",
	},
	"destination_address_snapshot": {
		"unvan": "Yıldız Mağazacılık A.Ş.",
		"adres": "Ostim Sanayi Sitesi 100. Sokak No:4",
		"ilce": "Yenimahalle",
		"il": "Ankara",
		"posta_kodu": "06370",
		"telefon": "+90 312 000 00 00",
	},
	"warehouse": None,
	"total_weight": 38.5,
	"total_desi": 42.0,
	"cost_paid_by": "Buyer",
	"carrier_cost": 268.40,
	"customer_charge": 349.90,
	"currency": "TRY",
	"exception_code": None,
	"delivery_code_required": 0,
	"payment_required_before_delivery": 0,
	"notes": "Kırılabilir ürün içerir, istifleme yapılmamalı.",
	"items": [
		{
			"item": "LST-00121", "item_name": "Pamuklu Kumaş Topu 40m",
			"ordered_qty": 20, "shipped_qty": 12, "remaining_qty": 8,
			"uom": "Top", "weight_kg": 2.4, "returned_qty": 0,
		},
		{
			"item": "LST-00133", "item_name": "Polyester Astar 50m",
			"ordered_qty": 10, "shipped_qty": 10, "remaining_qty": 0,
			"uom": "Top", "weight_kg": 1.1, "returned_qty": 0,
		},
	],
	"packages": [
		{
			"package_code": "PKG-42-001", "sequence_label": "1/3", "package_type": "BOX",
			"parent_package": None, "length_cm": 60, "width_cm": 40, "height_cm": 40,
			"weight_kg": 14.0, "desi": 32.0,
			"barcode_url": "/files/barkod/PKG-42-001.png",
			"label_url": "/files/etiket/PKG-42-001.pdf",
			"label_printed_at": "2026-08-10 08:12:00",
		},
		{
			"package_code": "PKG-42-002", "sequence_label": "2/3", "package_type": "BOX",
			"parent_package": None, "length_cm": 60, "width_cm": 40, "height_cm": 40,
			"weight_kg": 13.5, "desi": 32.0,
			"barcode_url": "/files/barkod/PKG-42-002.png",
			"label_url": "/files/etiket/PKG-42-002.pdf",
			"label_printed_at": "2026-08-10 08:12:00",
		},
		{
			"package_code": "PKG-42-003", "sequence_label": "3/3", "package_type": "LBOX",
			"parent_package": None, "length_cm": 80, "width_cm": 50, "height_cm": 45,
			"weight_kg": 11.0, "desi": 60.0,
			"barcode_url": "/files/barkod/PKG-42-003.png",
			"label_url": None, "label_printed_at": None,
		},
	],
	"legs": [
		{
			"sequence": 1, "leg_type": "Pickup", "status": "Completed", "carrier": "YK",
			"origin_branch": None, "destination_branch": "YK-34001",
			"handover_point": None, "handover_proof": None, "vehicle_type": "VAN",
			"started_at": "2026-08-10 09:00:00", "completed_at": "2026-08-10 11:30:00",
			"cost": 45.00,
		},
		{
			"sequence": 2, "leg_type": "Line Haul", "status": "In Progress", "carrier": "YK",
			"origin_branch": "YK-34001", "destination_branch": "AK-06010",
			"handover_point": "Ankara Aktarma", "handover_proof": "/files/devir/42-2.pdf",
			"vehicle_type": "TRUCK_M",
			"started_at": "2026-08-10 18:00:00", "completed_at": None,
			"cost": 180.40,
		},
		{
			"sequence": 3, "leg_type": "Last Mile", "status": "Planned", "carrier": "YK",
			"origin_branch": "AK-06010", "destination_branch": None,
			"handover_point": None, "handover_proof": None, "vehicle_type": "VAN",
			"started_at": None, "completed_at": None, "cost": 43.00,
		},
	],
	"events": [
		{
			"event_time": "2026-08-10 09:05:00", "status": "Picked Up", "source": "api",
			"carrier_status_code": "101", "carrier_status_text": "Kargo şubeye teslim edildi",
			"location": "İkitelli", "description": "Gönderi kuryeden teslim alındı",
			"exception_code": None, "actor": None, "reason": None,
			"dedupe_key": "YK-7801234567890-101",
		},
		{
			"event_time": "2026-08-10 18:20:00", "status": "In Transit", "source": "webhook",
			"carrier_status_code": "150", "carrier_status_text": "Transfer merkezinde",
			"location": "İstanbul Aktarma", "description": "Ankara'ya sevk edildi",
			"exception_code": None, "actor": None, "reason": None,
			"dedupe_key": "YK-7801234567890-150",
		},
		{
			"event_time": "2026-08-12 07:40:00", "status": "In Transit", "source": "polling",
			"carrier_status_code": "160", "carrier_status_text": "Varış şubesinde",
			"location": "Ostim", "description": "Dağıtıma hazırlanıyor",
			"exception_code": None, "actor": None, "reason": None,
			"dedupe_key": "YK-7801234567890-160",
		},
	],
}

SAMPLE_PROOF_OF_DELIVERY: list[dict[str, Any]] = [
	{
		"delivered_at": "2026-08-08 14:32:00",
		"received_by": "Mehmet Yıldız (Depo Sorumlusu)",
		"delivery_code_used": 1,
		"signature_url": "/files/pod/imza-41.png",
		"photo_url": "/files/pod/foto-41.jpg",
		"document_url": None,
		"location_source": "carrier_api",
		"location_recorded_at": "2026-08-08 14:32:00",
	},
]

SAMPLE_RETURN_REQUESTS: list[dict[str, Any]] = [
	{
		"name": "RET-2026-00007", "order": "ORD-2026-00871", "shipment": "SHP-2026-00041",
		"seller_profile": "SEL-00001", "buyer": "alici@ornek.com",
		"status": "inspecting", "reason": "damaged", "requested_at": "2026-08-09 10:00:00",
		"decided_at": "2026-08-09 15:20:00", "is_closed": 0,
	},
	{
		"name": "RET-2026-00006", "order": "ORD-2026-00863", "shipment": "SHP-2026-00038",
		"seller_profile": "SEL-00002", "buyer": "kurumsal@ornek.com",
		"status": "requested", "reason": "wrong_item", "requested_at": "2026-08-11 09:15:00",
		"decided_at": None, "is_closed": 0,
	},
	{
		"name": "RET-2026-00003", "order": "ORD-2026-00840", "shipment": "SHP-2026-00035",
		"seller_profile": "SEL-00001", "buyer": "alici@ornek.com",
		"status": "closed", "reason": "missing_parts", "requested_at": "2026-07-28 11:00:00",
		"decided_at": "2026-07-29 09:00:00", "is_closed": 1,
	},
]

SAMPLE_RETURN_DETAIL: dict[str, Any] = {
	"decision_note": "Hasar fotoğrafları incelendi, iade onaylandı.",
	"return_shipment": "SHP-2026-00044",
	"return_label_url": "/files/etiket/iade-RET-2026-00007.pdf",
	"inspection_result": "damaged",
	"inspection_note": "İki top kumaşta su hasarı tespit edildi.",
	"refund_amount": 2480.00,
	"refund_triggered_at": None,
	"exchange_shipment": None,
}

SAMPLE_PRICE_QUOTES: list[dict[str, Any]] = [
	{
		"quote_id": "Q-2026-0912-A", "carrier": "YK", "carrier_service": "YK-STD",
		"carrier_cost": 268.40, "customer_charge": 349.90, "currency": "TRY",
		"chargeable_weight": 42.0, "applied_rule": "Standart Kargo · 30-50 desi",
		"rule_priority": 10, "valid_until": "2026-08-13 09:00:00", "is_snapshot": 0,
		"surcharges": {"yakit_farki": 18.40, "sigorta": 0},
	},
	{
		"quote_id": "Q-2026-0912-B", "carrier": "AK", "carrier_service": "AK-STD",
		"carrier_cost": 245.00, "customer_charge": 349.90, "currency": "TRY",
		"chargeable_weight": 42.0, "applied_rule": "Standart Kargo · 30-50 desi",
		"rule_priority": 10, "valid_until": "2026-08-13 09:00:00", "is_snapshot": 0,
		"surcharges": {"yakit_farki": 15.00, "sigorta": 0},
	},
	{
		"quote_id": "Q-2026-0912-C", "carrier": "YK", "carrier_service": "YK-EXP",
		"carrier_cost": 410.00, "customer_charge": 0.00, "currency": "TRY",
		"chargeable_weight": 42.0, "applied_rule": "Ücretsiz kargo · 5000 TL üzeri sipariş",
		"rule_priority": 1, "valid_until": "2026-08-13 09:00:00", "is_snapshot": 1,
		"surcharges": {"yakit_farki": 24.00, "sigorta": 12.50},
	},
]

PROVISIONAL_SAMPLES: dict[str, dict[str, Any]] = {
	"shipment": {"rows": SAMPLE_SHIPMENTS, "detail": SAMPLE_SHIPMENT_DETAIL},
	"proof_of_delivery": {"rows": SAMPLE_PROOF_OF_DELIVERY, "detail": {}},
	"return_request": {"rows": SAMPLE_RETURN_REQUESTS, "detail": SAMPLE_RETURN_DETAIL},
	"price_quote": {"rows": SAMPLE_PRICE_QUOTES, "detail": {}},
}
