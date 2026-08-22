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
	# Ad hizalaması (2026-08-13): bu üç alan gerçek DocType'taki adlarını
	# taşıyor. Sözleşme Linear metinlerinden çıkarılmıştı; şema otoritesi
	# `doctype/shipment/shipment.json`.
	_f("ship_date", "Date", False, "Sevk tarihi"),
	_f("estimated_delivery", "Date", False, "Tahmini teslim"),
	_f("actual_delivery", "Datetime", False, "Gerçekleşen teslim"),
	_f("is_delayed", "Check", False, "Gecikme tespiti (TUR-112)"),
	_f("modified", "Datetime", False, "Son güncelleme"),
]

SHIPMENT_DETAIL_FIELDS = [
	_f("warehouse", "Link", False, "Çıkış deposu"),
	_f("total_weight", "Float", False),
	_f("total_desi", "Float", False),
	_f("cost_paid_by", "Select", False, "CostPaidBy enum'ından (TUR-107)"),
	_f("carrier_cost", "Currency", False, "Taşıyıcı ALIŞ maliyeti — TUR-121 ayrımı"),
	_f("customer_charge", "Currency", False, "Müşteriye YANSITILAN ücret"),
	# ── 20-FE siparişi: fiyat motorunun sevkiyattaki izi ──
	#: `customer_charge` bu sözleşmede uzun süredir yazılı ama DocType'ta HİÇ
	#: yok (2026-08-21 ölçümü: tüm Python'da 0 kullanım). B8 maliyet sekmesi
	#: ve L3 maliyet raporu onu bekliyor ve bugün "—" gösteriyor. Üçü birlikte
	#: 20-BE'nin ilk işi.
	_f(
		"carrier_account",
		"Link",
		False,
		"Hangi HESAPLA gönderildi — satıcının kendi anlaşması mı, platformunki mi (20-FE K4)",
	),
	_f(
		"applied_pricing_rule",
		"Link",
		False,
		"Ücreti hangi kural üretti — şikayet araştırmasının tek dayanağı",
	),
	_f(
		"price_quote_snapshot",
		"JSON",
		False,
		"Sipariş anındaki teklif DONDURULUR; kural sonradan değişse bile bu sevkiyatın ücreti değişmez",
	),
	_f("currency", "Link", False),
	_f("exception_code", "Link", False, "Shipment Exception Code"),
	_f("delivery_code_required", "Check", False, "Tek kullanımlık teslim kodu (TUR-108)"),
	_f("payment_required_before_delivery", "Check", False, "Ödeme şartlı teslim (TUR-108)"),
	# DocType notu ÜÇE ayırıyor: satıcı, alıcı ve operasyon notu. Tek bir
	# `notes` alanı bunları birleştirirdi; `internal_note` ayrıca alıcıya
	# sızdırılmıyor (api/v1/shipment.py `_can_view_operational_fields`).
	_f("seller_note", "Small Text", False, "Satıcının notu"),
	_f("buyer_note", "Small Text", False, "Alıcının notu"),
	_f("internal_note", "Small Text", False, "Operasyon notu — alıcıya dönmez"),
	# TUR-108 — satıcı aracı ve alıcı teslim alma akışları. Kargo dışı
	# kanallarda taşıyıcı/takip no yerine BUNLAR izleniyor; panelin
	# "taşıyıcı atanmadı" demesi bu akışlarda yanlış olurdu.
	_f("driver_name", "Data", False, "Satıcı aracı sürücüsü (TUR-108)"),
	_f("driver_phone", "Data", False, "Sürücü iletişim"),
	_f("vehicle_plate", "Data", False, "Araç plakası"),
	_f("appointment_at", "Datetime", False, "Randevu zamanı — satıcı teslimi / alıcı teslim alma"),
	_f("appointment_window", "Data", False, "Randevu aralığı, ör. 09:00-12:00"),
	_f(
		"delivery_code_status",
		"Select",
		False,
		"not_required | pending | verified | failed — kodun DEĞERİ hiç dönmez",
	),
	_f("delivery_code_attempts", "Int", False, "Yanlış kod denemesi sayısı"),
	_f("pickup_location", "Data", False, "Alıcı teslim alma noktası (TUR-108)"),
	_f("payment_status", "Select", False, "unpaid | paid | waived — ödeme şartlı teslimde kapı"),
]

#: Adres snapshot'ları (TUR-105) — DocType'ta JSON alan DEĞİL, child tablo.
#: `Shipment Address Snapshot` ile birebir; `snapshot_type` Origin/Destination.
SHIPMENT_ADDRESS_SNAPSHOT_FIELDS = [
	_f("snapshot_type", "Select", True, "Origin | Destination"),
	_f("source_address", "Link", False, "Kaynak Addresses kaydı"),
	_f("contact_name", "Data", False),
	_f("company", "Data", False),
	_f("phone_prefix", "Data", False),
	_f("phone", "Data", False),
	_f("country", "Link", False),
	_f("state", "Data", False),
	_f("city", "Data", False),
	_f("street", "Small Text", False),
	_f("apartment", "Data", False),
	_f("postal_code", "Data", False),
	_f("tax_no", "Data", False),
	_f("tax_office", "Data", False),
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
	_f("closed_at", "Datetime", False, "Kapanış zamanı — sonrası DEĞİŞTİRİLEMEZ"),
	_f("closed_by", "Link", False, "Kapatan kullanıcı — audit"),
]

#: Kalem bazlı iade kontrolü (TUR-116 depo kontrolü).
#:
#: Talep düzeyinde tek bir `inspection_result` yetmiyor: üç kalemlik bir
#: iadede biri hasarlı diğeri sağlam olabilir ve para iadesi tutarı buna
#: göre değişir. Tek alan, kısmi kabulü ifade edemez.
RETURN_ITEM_FIELDS = [
	_f("item", "Link", True, "Listing / ürün"),
	_f("item_name", "Data", True),
	_f("requested_qty", "Float", True, "Alıcının iade etmek istediği"),
	_f("received_qty", "Float", False, "Depoya ULAŞAN — eksik gelebilir"),
	_f("accepted_qty", "Float", False, "Kontrol sonrası kabul edilen"),
	_f("uom", "Data", False),
	_f("inspection_result", "Select", False, "ok | damaged | missing_parts | mismatch"),
	_f("inspection_note", "Small Text", False),
	_f("unit_refund", "Currency", False, "Birim iade tutarı"),
]

# ---------------------------------------------------------------------------
# Fiyat teklifi — TUR-121
# ---------------------------------------------------------------------------

PRICE_QUOTE_FIELDS = [
	_f("quote_id", "Data", True),
	_f(
		"carrier_account",
		"Link",
		False,
		"Hangi HESABIN tarifesi — platform ve satıcı aynı taşıyıcıyla farklı fiyat alır",
	),
	_f("carrier", "Link", True),
	_f("carrier_service", "Link", False),
	_f("account_owner", "Data", False, "Boş = platform hesabı, dolu = satıcı adı (arayüz rozeti)"),
	_f("zone", "Link", False, "Varış bölgesi — Shipping Zone"),
	_f("chargeable_weight", "Float", False),
	# ── Tutarlar. KDV HARİÇ tutulur, vergi ayrı satır (20-FE Ö2) ──
	_f("carrier_cost", "Currency", False, "Taşıyıcı ALIŞ maliyeti — yetkisi olmayana HİÇ GÖNDERİLMEZ"),
	_f("customer_charge", "Currency", True, "Müşteriye YANSITILAN ücret, KDV hariç"),
	_f(
		"margin",
		"Currency",
		False,
		"Sunucu hesaplar — arayüz yuvarlama farkı üretmesin; maliyetle birlikte maskelenir",
	),
	_f("surcharge_total", "Currency", False, "Ek ücretlerin toplamı — dökümü `surcharges`'ta"),
	_f("tax_rate", "Percent", False),
	_f("tax_amount", "Currency", False),
	_f("total_with_tax", "Currency", True, "Alıcının ödediği — checkout bu alanı gösterir"),
	_f("currency", "Link", True),
	# ── Açıklanabilirlik (TUR-121 kabul kriteri) ──
	_f("applied_rule", "Data", False, "Kazanan kuralın adı (`name`)"),
	_f("applied_rule_name", "Data", False, "Kazanan kuralın okunabilir başlığı"),
	_f("applied_layer", "Select", False, "platform_mandatory | seller | platform — hangi katman kazandı"),
	_f("applied_tier_label", "Data", False, 'Uygulanan desi kademesi, ör. "30–50 desi"'),
	_f("rule_priority", "Int", False, "Çakışma çözümü deterministik"),
	_f("evaluations", "JSON", False, "Değerlendirme İZİ — denenen her kural ve elenme SEBEBİ (§3)"),
	# ── Kullanılabilirlik ──
	_f("available", "Check", False, "0 = bu hesapla fiyat üretilemedi; sebebi `unavailable_reason`"),
	_f("unavailable_reason", "Data", False, "Ör. NO_RULE_MATCHED"),
	_f("estimated_days_min", "Int", False),
	_f("estimated_days_max", "Int", False),
	_f("valid_until", "Datetime", False, "Teklif geçerlilik süresi"),
	_f("is_snapshot", "Check", False, "Sipariş anındaki fiyat korunur"),
	_f("surcharges", "JSON", False, "Yakıt farkı, ücra bölge, sigorta vb. — kalem kalem"),
]

#: Fiyatlandırma kuralı (TUR-121 · 20-FE kararları K1/K3/K6/K7).
#:
#: TUR-121 kabul kriteri: *"Kural çakışması deterministik çözülür ve
#: AÇIKLANABİLİR olmalıdır."* Bunun sözleşmedeki karşılığı `priority` +
#: eşleşme ölçütlerinin açıkça ALAN olması: bir teklifin neden o fiyatı
#: aldığı, kuralın alanlarına bakılarak anlatılabilmeli. Ölçütler bir JSON
#: ifadesine gömülseydi arayüz "şu kural uygulandı" diyebilir ama NEDEN
#: uygulandığını gösteremezdi (K7 kararı: serbest koşul kurucu YOK).
#:
#: ÜÇ KATMANLI DEĞERLENDİRME (K1): kurallar tek sırada değil, üç katmanda
#: denenir — (1) zorunlu platform kuralları, (2) satıcının kendi kuralları,
#: (3) normal platform kuralları. Bir katmanda eşleşme bulunursa aşağı
#: inilmez. `priority` katman İÇİNDE sıralar; katmanlar arası sırayı
#: `seller_profile` + `is_mandatory` belirler.
#:
#: KADEME TABLOSU (K6): gerçek tarifeler banttır (0-10 / 10-30 / 30+).
#: Her bant için ayrı kural yazmak 6 bölge × 8 bant = 48 kayıt demekti ve
#: öncelik listesi okunmaz olurdu. Kademe alt tablosu bir tarife satır
#: kümesini TEK kayıtta anlatıyor.
PRICING_RULE_FIELDS = [
	_f("name", "Data", True),
	_f("rule_name", "Data", True),
	# ── Sahiplik — iki kaynaklı fiyatlandırmanın belkemiği (K1) ──
	_f("seller_profile", "Link", False, "BOŞ = platform kuralı, DOLU = o satıcının kendi kuralı"),
	_f("owner_label", "Data", False, 'Arayüz rozeti: "Platform" ya da satıcı adı'),
	_f("layer", "Select", True, "platform_mandatory | seller | platform — sunucu türetir, arayüz gruplar"),
	_f("is_mandatory", "Check", False, "YALNIZ platform kuralında yazılabilir; satıcı kurallarını da ezer"),
	# ── Eşleşme ölçütleri — boş olan "sınırlama yok" demek ──
	_f(
		"carrier_account",
		"Link",
		False,
		"Hangi HESABIN tarifesi. Satıcının MNG'si ile platformun MNG'si ayrı fiyat",
	),
	_f("carrier", "Link", False, "Boş = tüm taşıyıcılar"),
	_f("carrier_service", "Link", False),
	_f("shipping_method", "Link", False),
	_f("zone", "Link", False, "Shipping Zone — serbest metin DEĞİL (K3)"),
	_f("zone_label", "Data", False, "Bölgenin okunabilir adı — arayüz ikinci istek atmasın"),
	_f("origin_city", "Data", False),
	_f("destination_city", "Data", False),
	_f("min_weight_kg", "Float", False),
	_f("max_weight_kg", "Float", False),
	_f("min_order_total", "Currency", False, "Ücretsiz kargo eşiği bu alanla kurulur"),
	_f("priority", "Int", True, "Katman İÇİNDE sıra; küçük sayı önce değerlendirilir"),
	_f("is_active", "Check", False),
	# ── Liste özetleri — TÜRETİLMİŞ, kademe tablosundan hesaplanır ──
	#: Liste ucu child tabloyu getirmiyor (200 kurallık listede N+1 sorgu
	#: demekti). K1 tablosu zaten aralık ve adet gösteriyor; ikisi burada.
	_f("tier_count", "Int", False, "Kaç desi kademesi var"),
	_f("min_base_cost", "Currency", False, "Kademelerin en düşük alışı — yetkisi olmayana GÖNDERİLMEZ"),
	_f("max_base_cost", "Currency", False, "En yüksek alış — aynı maskeleme"),
	_f("min_base_charge", "Currency", False, "Kademelerin en düşük satışı"),
	_f("max_base_charge", "Currency", False, "En yüksek satış"),
	_f(
		"has_negative_margin",
		"Check",
		False,
		'Bir kademede satış < alış — K1\'deki "zararda" rozeti; maliyetle birlikte maskelenir',
	),
	_f("surcharge_count", "Int", False),
	# ── Denetim uyarıları — SUNUCU hesaplar (sayfalama nedeniyle) ──
	#: Prototip bunları arayüzde hesaplıyordu ve liste sayfalandığı an
	#: YANLIŞ sonuç verirdi: 2. sayfadaki bir kural 1. sayfadakini
	#: gölgeliyorsa arayüz bunu göremez. Denetim sunucuda, tüm küme üzerinde.
	_f(
		"priority_conflict_with",
		"JSON",
		False,
		"Aynı katmanda aynı önceliği paylaşan AKTİF kuralların adları",
	),
	_f("shadowed_by", "Data", False, "Bu kuralı hiç çalıştırmayan, daha öncelikli ölçütsüz kuralın adı"),
	# ── Para ve geçerlilik ──
	_f("currency", "Link", False),
	_f("tax_rate", "Percent", False, "Fiyatlar KDV HARİÇ tutulur (20-FE Ö2)"),
	_f("valid_from", "Date", False),
	_f("valid_until", "Date", False),
]

#: Kuralın detayı — alt tablolar ve denetim izi burada.
PRICING_RULE_DETAIL_FIELDS = [
	_f("tiers", "Table", True, "Desi kademeleri — en az bir satır"),
	_f("surcharges", "Table", False, "Ek ücretler"),
	_f("description", "Small Text", False, "Kuralın neden var olduğu — altı ay sonra okuyan için"),
	_f("modified", "Datetime", False),
	_f("modified_by", "Data", False, "Fiyat paradır: kim değiştirdi izlenir (20-FE Ö3)"),
]

#: Desi kademesi (K6).
#:
#: Aralıklar YARI AÇIK: `min_desi <= desi < max_desi`. Kapalı olsaydı 10
#: desilik gönderi hem 0-10 hem 10-30 kademesine düşer ve iki farklı fiyat
#: çıkardı. `max_desi` boş = üst sınır yok.
PRICING_RULE_TIER_FIELDS = [
	_f("min_desi", "Float", True, "Dahil"),
	_f("max_desi", "Float", False, "HARİÇ — boş ise üst sınır yok"),
	_f("base_cost", "Currency", False, "Taşıyıcı ALIŞ maliyeti tabanı"),
	_f("base_charge", "Currency", False, "Müşteriye YANSITILAN taban ücret"),
	_f("per_desi_charge", "Currency", False, "Kademe alt sınırını AŞAN her desi için ek"),
	_f("min_charge", "Currency", False, "Asgari ücret — hesap bunun altına düşemez"),
]

#: Ek ücret (20-FE Ö1).
#:
#: Kural bazlı, çünkü Doğu bölgesinin yakıt farkı ile Marmara'nınki farklı
#: olabiliyor. `price_quote.surcharges` bu satırlardan türetiliyor; teklifte
#: kalem kalem gösterilmesi zorunlu — toplam içinde eriyen bir yakıt farkı
#: müşteri itirazında açıklanamaz.
PRICING_RULE_SURCHARGE_FIELDS = [
	_f("surcharge_type", "Data", True, "Yakıt farkı, sigorta, ücra bölge, kapıda ödeme…"),
	_f("calc_method", "Select", True, "fixed | percent"),
	_f("value", "Float", True, "fixed ise tutar, percent ise oran"),
	_f("applies_to", "Select", True, "cost | charge | both"),
]

# ---------------------------------------------------------------------------
# Kargo bölgesi — TUR-121 / 20-FE K3
# ---------------------------------------------------------------------------

#: Kargo bölgesi: adı olan bir il grubu.
#:
#: NEDEN VAR: kuralın `zone` alanı serbest metindi. Biri "TR-DOGU", başkası
#: "Doğu" yazınca İKİ AYRI bölge oluşuyor ve kural sessizce çalışmıyordu.
#: 20-FE'de satıcılar da kural yazacağı için sorun katlanıyordu: 50 satıcı
#: 50 farklı yazım üretir. Bölgeyi PLATFORM tanımlar, herkes aynı listeden
#: seçer (K3).
#:
#: GEÇİŞ NOTU: `Shipping Zone` DocType'ı 20-BE'de açılacak ve o gün bu varlık
#: `PROVISIONAL_ENTITIES`'ten çıkıp `logistics_catalog.CATALOGS`'a taşınacak —
#: jenerik katalog ekranından yönetilecek, AYRI EKRAN YAZILMAYACAK. Burada
#: geçici duruyor ki 20-FE mock'u sözleşmeli bir bölge listesi bulsun.
SHIPPING_ZONE_FIELDS = [
	_f("name", "Data", True, "Bölge kodu, ör. TR-DOGU"),
	_f("zone_code", "Data", True),
	_f("zone_name", "Data", True, 'Okunabilir ad, ör. "Doğu Anadolu"'),
	_f("is_active", "Check", False),
	_f("city_count", "Int", False, "Kaç il içeriyor — liste ekranı için türetilmiş"),
]

SHIPPING_ZONE_CITY_FIELDS = [
	_f("city", "Data", True, "İl adı — Türkiye il listesiyle birebir"),
]

# ---------------------------------------------------------------------------
# Raporlar — TUR-118
# ---------------------------------------------------------------------------

#: Performans raporu satırı (TUR-118).
#:
#: Her satır bir KIRILIM (taşıyıcı / yöntem / satıcı) için toplulaştırılmış
#: ölçüm. Ham sevkiyat listesi döndürüp arayüzde toplamak, sayfalama
#: yüzünden yanlış sonuç verirdi — 50 satırlık sayfadan hesaplanan
#: "ortalama teslim süresi" tüm veriyi temsil etmez.
PERFORMANCE_REPORT_FIELDS = [
	_f("dimension", "Data", True, "Kırılım değeri, ör. taşıyıcı kodu"),
	_f("dimension_label", "Data", True),
	_f("shipment_count", "Int", True),
	_f("delivered_count", "Int", False),
	_f("delayed_count", "Int", False),
	_f("failed_count", "Int", False),
	_f("returned_count", "Int", False),
	_f("avg_delivery_days", "Float", False, "Yalnız teslim edilenler üzerinden"),
	_f("p90_delivery_days", "Float", False, "Kuyruk davranışı — ortalama gizler"),
	_f("on_time_rate", "Float", False, "0-1 arası oran"),
	_f("failure_rate", "Float", False),
	_f("return_rate", "Float", False),
]

#: Maliyet raporu satırı (TUR-118, TUR-121).
#:
#: Alış ve satış AYRI kolonlar. Tek bir "kargo geliri" alanı TUR-121'in
#: ayrım kriterini ihlal ederdi; marj ayrıca hesaplanmış geliyor ki arayüz
#: yuvarlama farkı üretmesin.
COST_REPORT_FIELDS = [
	_f("dimension", "Data", True),
	_f("dimension_label", "Data", True),
	_f("shipment_count", "Int", True),
	_f("carrier_cost_total", "Currency", True, "Taşıyıcıya ÖDENEN"),
	_f("customer_charge_total", "Currency", True, "Müşteriden ALINAN"),
	_f("margin_total", "Currency", True, "Backend hesaplar — arayüz yuvarlama üretmesin"),
	_f("margin_rate", "Float", False, "0-1 arası; negatif olabilir"),
	_f("avg_cost_per_shipment", "Currency", False),
	_f("currency", "Link", True),
]

# ---------------------------------------------------------------------------
# Taşıyıcı entegrasyonu — TUR-110, TUR-111
# ---------------------------------------------------------------------------

CONNECTION_TEST_FIELDS = [
	_f("carrier_account", "Link", True, "Denenen hesap"),
	_f("probe", "Select", True, "authenticate | quote | track — hangi yetenek denendi"),
	_f("succeeded", "Check", True),
	_f("http_status", "Int", False, "Taşıyıcı yanıt kodu"),
	_f("duration_ms", "Int", False, "Gecikme — yavaş entegrasyon da bir arıza"),
	_f("message", "Small Text", False, "Kullanıcıya gösterilecek özet"),
	_f("error_code", "Data", False, "Taşıyıcının hata kodu — dallanma için"),
	_f("tested_at", "Datetime", True),
	_f("tested_by", "Link", False, "Denemeyi yapan kullanıcı — audit"),
]

#: Entegrasyon logu (TUR-110).
#:
#: MASKELEME SÖZLEŞMESİ: `request_body` ve `response_body` panele **maskelenmiş**
#: gelir. `Authorization`, `X-Api-Key` gibi başlıklar ve gövdedeki
#: `api_key`/`api_secret`/`token`/`password` anahtarları backend'de değiştirilir.
#: Maskeleme İSTEMCİDE yapılamaz: ham gövde yanıtta dolaşırsa tarayıcı
#: geçmişinde ve ara sunucu loglarında kalır (aynı gerekçe `logistics_admin.py`
#: gizli alan sözleşmesinde de yazılı).
INTEGRATION_LOG_FIELDS = [
	_f("name", "Data", True),
	_f("carrier", "Link", True),
	_f("carrier_account", "Link", False),
	_f("operation", "Select", True, "create_shipment | cancel | label | quote | track | webhook"),
	_f("direction", "Select", True, "outbound | inbound"),
	_f("shipment", "Link", False, "İlgili sevkiyat — varsa"),
	_f("succeeded", "Check", True),
	_f("http_status", "Int", False),
	_f("duration_ms", "Int", False),
	_f("attempt", "Int", False, "Kaçıncı deneme (yeniden çalıştırma sayacı)"),
	_f("error_code", "Data", False),
	_f("error_message", "Small Text", False),
	_f("request_body", "Code", False, "MASKELİ — credential'lar backend'de değiştirilir"),
	_f("response_body", "Code", False, "MASKELİ"),
	_f("is_retriable", "Check", False, "Yeniden çalıştırma anlamlı mı"),
	_f("created_at", "Datetime", True),
]

# ---------------------------------------------------------------------------
# Palet planı — TUR-120
# ---------------------------------------------------------------------------

PALLET_PLAN_FIELDS = [
	_f("name", "Data", True),
	_f("shipment", "Link", True),
	_f("pallet_code", "Data", True, "Paket hiyerarşisinde parent_package değeri"),
	_f("pallet_type", "Link", False, "Package Type katalogundan (palet tipleri)"),
	_f("layer_count", "Int", False, "Yerleşen katman"),
	_f("max_layers", "Int", False, "Palet tipinin katman kapasitesi"),
	_f("package_count", "Int", False, "Palete yerleşen koli"),
	_f("loaded_weight_kg", "Float", False),
	_f("max_weight_kg", "Float", False, "Aşılırsa AŞIRI YÜK uyarısı (TUR-120)"),
	_f("loaded_desi", "Float", False),
	_f("is_overloaded", "Check", False, "Ağırlık veya katman kapasitesi aşıldı"),
]

# ---------------------------------------------------------------------------
# Toplu içe aktarma — TUR-107
# ---------------------------------------------------------------------------

IMPORT_JOB_FIELDS = [
	_f("name", "Data", True),
	_f("file_name", "Data", True),
	_f("status", "Select", True, "mapping | previewing | applying | completed | failed"),
	_f("total_rows", "Int", True),
	_f("valid_rows", "Int", False),
	_f("error_rows", "Int", False),
	_f("applied_rows", "Int", False, "Gerçekten yazılan — kısmi başarı mümkün"),
	_f("column_mapping", "JSON", False, "CSV başlığı → sevkiyat alanı"),
	_f("errors", "JSON", False, "[{row, column, message}] — satır bazlı hata raporu"),
	_f("created_at", "Datetime", True),
	_f("created_by", "Link", False),
]

# ---------------------------------------------------------------------------
# Bildirim — TUR-113
# ---------------------------------------------------------------------------

NOTIFICATION_TEMPLATE_FIELDS = [
	_f("name", "Data", True),
	_f("event", "Select", True, "Hangi lojistik olayında tetiklenir"),
	_f("channel", "Select", True, "email | in_app | sms"),
	_f("recipient_role", "Select", True, "buyer | seller | operations"),
	_f("subject", "Data", False, "E-posta konusu"),
	_f("body", "Text Editor", False, "Değişkenler: {{shipment}}, {{tracking_number}}, {{status}}"),
	_f("is_active", "Check", False),
	_f("is_mandatory", "Check", False, "Zorunlu operasyon bildirimi — kapatılamaz (TUR-113)"),
]

#: Tercih yönetimi (TUR-113).
#:
#: `is_mandatory` şablondan gelir ve tercihe İZİN VERMEZ. Kabul kriteri
#: "zorunlu operasyon bildirimleri kullanıcı tercihiyle kapatılamaz" — bu
#: bir arayüz nezaketi değil, veri kısıtı; `enabled` alanı zorunlu şablonda
#: yazılamaz olmalı.
NOTIFICATION_PREFERENCE_FIELDS = [
	_f("template", "Link", True),
	_f("event", "Select", True),
	_f("channel", "Select", True),
	_f("recipient_role", "Select", True),
	_f("enabled", "Check", True),
	_f("is_mandatory", "Check", False, "Şablondan miras — true ise enabled yazılamaz"),
	_f("locked_reason", "Data", False, "Neden kapatılamadığı kullanıcıya açıklanır"),
]

OPERATION_ALERT_FIELDS = [
	_f("name", "Data", True),
	_f("alert_type", "Select", True, "sla_breach | integration_failure | exception_spike | stuck_shipment"),
	_f("severity", "Select", True, "Info | Warning | Critical"),
	_f("title", "Data", True),
	_f("detail", "Small Text", False),
	_f("shipment", "Link", False),
	_f("carrier", "Link", False),
	_f("affected_count", "Int", False, "Kaç kaydı etkiliyor — tekil mi toplu mu"),
	_f("raised_at", "Datetime", True),
	_f("acknowledged_at", "Datetime", False),
	_f("acknowledged_by", "Link", False),
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
			"address_snapshots": SHIPMENT_ADDRESS_SNAPSHOT_FIELDS,
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
		"child_tables": {"items": RETURN_ITEM_FIELDS},
	},
	"price_quote": {
		"label": "Fiyat Teklifi",
		"source_tasks": ["TUR-121"],
		"list_fields": PRICE_QUOTE_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"connection_test": {
		"label": "Bağlantı Testi Sonucu",
		"source_tasks": ["TUR-110", "TUR-111"],
		"list_fields": CONNECTION_TEST_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"integration_log": {
		"label": "Entegrasyon Logu",
		"source_tasks": ["TUR-110"],
		"list_fields": INTEGRATION_LOG_FIELDS,
		"detail_fields": [],
		"child_tables": {},
		"masked_fields": ["request_body", "response_body"],
	},
	"pallet_plan": {
		"label": "Palet Planı",
		"source_tasks": ["TUR-120"],
		"list_fields": PALLET_PLAN_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"import_job": {
		"label": "Toplu İçe Aktarma",
		"source_tasks": ["TUR-107"],
		"list_fields": IMPORT_JOB_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"notification_template": {
		"label": "Bildirim Şablonu",
		"source_tasks": ["TUR-113"],
		"list_fields": NOTIFICATION_TEMPLATE_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"notification_preference": {
		"label": "Bildirim Tercihi",
		"source_tasks": ["TUR-113"],
		"list_fields": NOTIFICATION_PREFERENCE_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"operation_alert": {
		"label": "Operasyon Alarmı",
		"source_tasks": ["TUR-113"],
		"list_fields": OPERATION_ALERT_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"pricing_rule": {
		"label": "Fiyatlandırma Kuralı",
		"source_tasks": ["TUR-121"],
		"list_fields": PRICING_RULE_FIELDS,
		"detail_fields": PRICING_RULE_DETAIL_FIELDS,
		"child_tables": {
			"tiers": PRICING_RULE_TIER_FIELDS,
			"surcharges": PRICING_RULE_SURCHARGE_FIELDS,
		},
		# Satıcının kendi anlaşmasının maliyeti platforma KAPALI (20-FE K2).
		# Maskeleme iki YÖNLÜ: platform kuralında satıcı, satıcı kuralında
		# platform bu alanları görmez — tek yönlü `mask_shipment_cost_fields`
		# bunu ifade edemiyor, 20-BE'de yeni bir kural yazılacak.
		"masked_fields": ["min_base_cost", "max_base_cost", "has_negative_margin"],
	},
	"shipping_zone": {
		"label": "Kargo Bölgesi",
		"source_tasks": ["TUR-121"],
		"list_fields": SHIPPING_ZONE_FIELDS,
		"detail_fields": [],
		"child_tables": {"cities": SHIPPING_ZONE_CITY_FIELDS},
	},
	"performance_report": {
		"label": "Performans Raporu",
		"source_tasks": ["TUR-118"],
		"list_fields": PERFORMANCE_REPORT_FIELDS,
		"detail_fields": [],
		"child_tables": {},
	},
	"cost_report": {
		"label": "Maliyet Raporu",
		"source_tasks": ["TUR-118", "TUR-121"],
		"list_fields": COST_REPORT_FIELDS,
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
		"ship_date": "2026-08-10",
		"estimated_delivery": "2026-08-13",
		"actual_delivery": None,
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
		"ship_date": "2026-08-06",
		"estimated_delivery": "2026-08-09",
		"actual_delivery": "2026-08-08",
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
		"ship_date": "2026-08-04",
		"estimated_delivery": "2026-08-07",
		"actual_delivery": None,
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
		"ship_date": None,
		"estimated_delivery": "2026-08-14",
		"actual_delivery": None,
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
		"ship_date": "2026-08-09",
		"estimated_delivery": "2026-08-16",
		"actual_delivery": None,
		"is_delayed": 0,
		"modified": "2026-08-11 19:40:00",
	},
]

#: SHP-2026-00042'nin detayı — liste satırıyla TUTARLI olmalı
SAMPLE_SHIPMENT_DETAIL: dict[str, Any] = {
	# Adres snapshot'ları child tablo — alan adları `Addresses` DocType'ından
	# birebir kopyalanıyor (hooks.py `_ADDRESS_COPY_FIELDS`), Türkçe anahtar yok.
	"address_snapshots": [
		{
			"snapshot_type": "Origin",
			"source_address": "ADDR-00042",
			"contact_name": "Mehmet Demir",
			"company": "Demir Tekstil Ltd. Şti.",
			"phone_prefix": "+90",
			"phone": "212 000 00 00",
			"country": "Turkey",
			"state": "İstanbul",
			"city": "Başakşehir",
			"street": "İkitelli OSB, Bağcılar Cad. No:12",
			"apartment": "Blok C",
			"postal_code": "34490",
			"tax_no": "1234567890",
			"tax_office": "İkitelli",
		},
		{
			"snapshot_type": "Destination",
			"source_address": "ADDR-00117",
			"contact_name": "Ayşe Yıldız",
			"company": "Yıldız Mağazacılık A.Ş.",
			"phone_prefix": "+90",
			"phone": "312 000 00 00",
			"country": "Turkey",
			"state": "Ankara",
			"city": "Yenimahalle",
			"street": "Ostim Sanayi Sitesi 100. Sokak No:4",
			"apartment": "No:4",
			"postal_code": "06370",
			"tax_no": "9876543210",
			"tax_office": "Ostim",
		},
	],
	"warehouse": None,
	"total_weight": 38.5,
	"total_desi": 42.0,
	"cost_paid_by": "Buyer",
	"carrier_cost": 268.40,
	"customer_charge": 349.90,
	# Fiyatın izi (20-FE): hangi hesapla gönderildi, hangi kural üretti ve
	# sipariş anındaki teklif. Şikayet araştırmasında tek dayanak bu üçü.
	"carrier_account": "CACC-YK-PLATFORM",
	"applied_pricing_rule": "PR-STD-YK",
	"price_quote_snapshot": {
		"quote_id": "Q-2026-0912-A",
		"quoted_at": "2026-08-12 09:00:00",
		"carrier_cost": 268.40,
		"customer_charge": 349.90,
		"tax_rate": 20.0,
		"tax_amount": 69.98,
		"total_with_tax": 419.88,
		"applied_rule": "PR-STD-YK",
		"applied_layer": "platform",
		"applied_tier_label": "30–50 desi",
		"currency": "TRY",
	},
	"currency": "TRY",
	"exception_code": None,
	"delivery_code_required": 0,
	"payment_required_before_delivery": 0,
	"seller_note": "Kırılabilir ürün içerir, istifleme yapılmamalı.",
	"buyer_note": "Teslimat öncesi lütfen arayın.",
	"internal_note": "Müşteri daha önce hasarlı teslim bildirmişti — fotoğraf çekilsin.",
	# Kargo kanalıyla giden bir sevkiyat: satıcı aracı/alıcı teslim alma
	# alanları BOŞ. D1/D2 ekranları kendi senaryolarını bu boşluğun üzerine
	# kuruyor — dolu bırakmak "her sevkiyatta sürücü var" izlenimi verirdi.
	"driver_name": None,
	"driver_phone": None,
	"vehicle_plate": None,
	"appointment_at": None,
	"appointment_window": None,
	"delivery_code_status": "not_required",
	"delivery_code_attempts": 0,
	"pickup_location": None,
	"payment_status": "paid",
	"items": [
		{
			"item": "LST-00121",
			"item_name": "Pamuklu Kumaş Topu 40m",
			"ordered_qty": 20,
			"shipped_qty": 12,
			"remaining_qty": 8,
			"uom": "Top",
			"weight_kg": 2.4,
			"returned_qty": 0,
		},
		{
			"item": "LST-00133",
			"item_name": "Polyester Astar 50m",
			"ordered_qty": 10,
			"shipped_qty": 10,
			"remaining_qty": 0,
			"uom": "Top",
			"weight_kg": 1.1,
			"returned_qty": 0,
		},
	],
	"packages": [
		{
			"package_code": "PKG-42-001",
			"sequence_label": "1/3",
			"package_type": "BOX",
			"parent_package": None,
			"length_cm": 60,
			"width_cm": 40,
			"height_cm": 40,
			"weight_kg": 14.0,
			"desi": 32.0,
			"barcode_url": "/files/barkod/PKG-42-001.png",
			"label_url": "/files/etiket/PKG-42-001.pdf",
			"label_printed_at": "2026-08-10 08:12:00",
		},
		{
			"package_code": "PKG-42-002",
			"sequence_label": "2/3",
			"package_type": "BOX",
			"parent_package": None,
			"length_cm": 60,
			"width_cm": 40,
			"height_cm": 40,
			"weight_kg": 13.5,
			"desi": 32.0,
			"barcode_url": "/files/barkod/PKG-42-002.png",
			"label_url": "/files/etiket/PKG-42-002.pdf",
			"label_printed_at": "2026-08-10 08:12:00",
		},
		{
			"package_code": "PKG-42-003",
			"sequence_label": "3/3",
			"package_type": "LBOX",
			"parent_package": None,
			"length_cm": 80,
			"width_cm": 50,
			"height_cm": 45,
			"weight_kg": 11.0,
			"desi": 60.0,
			"barcode_url": "/files/barkod/PKG-42-003.png",
			"label_url": None,
			"label_printed_at": None,
		},
	],
	"legs": [
		{
			"sequence": 1,
			"leg_type": "Pickup",
			"status": "Completed",
			"carrier": "YK",
			"origin_branch": None,
			"destination_branch": "YK-34001",
			"handover_point": None,
			"handover_proof": None,
			"vehicle_type": "VAN",
			"started_at": "2026-08-10 09:00:00",
			"completed_at": "2026-08-10 11:30:00",
			"cost": 45.00,
		},
		{
			"sequence": 2,
			"leg_type": "Line Haul",
			"status": "In Progress",
			"carrier": "YK",
			"origin_branch": "YK-34001",
			"destination_branch": "AK-06010",
			"handover_point": "Ankara Aktarma",
			"handover_proof": "/files/devir/42-2.pdf",
			"vehicle_type": "TRUCK_M",
			"started_at": "2026-08-10 18:00:00",
			"completed_at": None,
			"cost": 180.40,
		},
		{
			"sequence": 3,
			"leg_type": "Last Mile",
			"status": "Planned",
			"carrier": "YK",
			"origin_branch": "AK-06010",
			"destination_branch": None,
			"handover_point": None,
			"handover_proof": None,
			"vehicle_type": "VAN",
			"started_at": None,
			"completed_at": None,
			"cost": 43.00,
		},
	],
	"events": [
		{
			"event_time": "2026-08-10 09:05:00",
			"status": "Picked Up",
			"source": "api",
			"carrier_status_code": "101",
			"carrier_status_text": "Kargo şubeye teslim edildi",
			"location": "İkitelli",
			"description": "Gönderi kuryeden teslim alındı",
			"exception_code": None,
			"actor": None,
			"reason": None,
			"dedupe_key": "YK-7801234567890-101",
		},
		{
			"event_time": "2026-08-10 18:20:00",
			"status": "In Transit",
			"source": "webhook",
			"carrier_status_code": "150",
			"carrier_status_text": "Transfer merkezinde",
			"location": "İstanbul Aktarma",
			"description": "Ankara'ya sevk edildi",
			"exception_code": None,
			"actor": None,
			"reason": None,
			"dedupe_key": "YK-7801234567890-150",
		},
		{
			"event_time": "2026-08-12 07:40:00",
			"status": "In Transit",
			"source": "polling",
			"carrier_status_code": "160",
			"carrier_status_text": "Varış şubesinde",
			"location": "Ostim",
			"description": "Dağıtıma hazırlanıyor",
			"exception_code": None,
			"actor": None,
			"reason": None,
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
		"name": "RET-2026-00007",
		"order": "ORD-2026-00871",
		"shipment": "SHP-2026-00041",
		"seller_profile": "SEL-00001",
		"buyer": "alici@ornek.com",
		"status": "inspecting",
		"reason": "damaged",
		"requested_at": "2026-08-09 10:00:00",
		"decided_at": "2026-08-09 15:20:00",
		"is_closed": 0,
	},
	{
		"name": "RET-2026-00006",
		"order": "ORD-2026-00863",
		"shipment": "SHP-2026-00038",
		"seller_profile": "SEL-00002",
		"buyer": "kurumsal@ornek.com",
		"status": "requested",
		"reason": "wrong_item",
		"requested_at": "2026-08-11 09:15:00",
		"decided_at": None,
		"is_closed": 0,
	},
	{
		"name": "RET-2026-00003",
		"order": "ORD-2026-00840",
		"shipment": "SHP-2026-00035",
		"seller_profile": "SEL-00001",
		"buyer": "alici@ornek.com",
		"status": "closed",
		"reason": "missing_parts",
		"requested_at": "2026-07-28 11:00:00",
		"decided_at": "2026-07-29 09:00:00",
		"is_closed": 1,
	},
]

SAMPLE_RETURN_DETAIL: dict[str, Any] = {
	"decision_note": "Hasar fotoğrafları incelendi, iade onaylandı.",
	"return_shipment": "SHP-2026-00044",
	"return_label_url": "/files/etiket/iade-RET-2026-00007.pdf",
	"inspection_result": "damaged",
	"inspection_note": "İki top kumaşta su hasarı tespit edildi.",
	# Kabul edilen kalemlerden: 4 × 620,00 + 0 × 0,00 = 2480,00
	"refund_amount": 2480.00,
	"refund_triggered_at": None,
	"exchange_shipment": None,
	"closed_at": None,
	"closed_by": None,
	"items": [
		{
			"item": "LST-00121",
			"item_name": "Pamuklu Kumaş Topu 40m",
			"requested_qty": 6,
			"received_qty": 6,
			"accepted_qty": 4,
			"uom": "Top",
			"inspection_result": "damaged",
			"inspection_note": "2 topta su hasarı — kabul edilmedi.",
			"unit_refund": 620.00,
		},
		# Eksik gelen kalem: istenen 3, ulaşan 2. Depo kontrolünün asıl
		# yakaladığı durum bu ve para iadesi buna göre kısılıyor.
		{
			"item": "LST-00133",
			"item_name": "Polyester Astar 50m",
			"requested_qty": 3,
			"received_qty": 2,
			"accepted_qty": 0,
			"uom": "Top",
			"inspection_result": "missing_parts",
			"inspection_note": "1 top hiç ulaşmadı, gelen 2 top eksik parçalı.",
			"unit_refund": 0.00,
		},
	],
}

#: Fiyat teklifleri — 20-FE mockup'ıyla BİREBİR (onaylandı 2026-08-21).
#:
#: TEK SENARYO, DÖRT HESAP: 42 desi · 38,5 kg · İstanbul → Van (Doğu Anadolu) ·
#: sipariş 4.200 ₺ · satıcı Ali Hırdavat. `simulate_price` tek teklif değil,
#: kullanılabilir HER taşıyıcı hesabı için bir satır döndürür (20-FE K4/K5):
#: paketleme ekranı satıcıya seçtirecek, simülasyon ekranı yan yana gösterecek.
#:
#: Tutarlar birbiriyle TUTARLI olmak zorunda:
#:   satış(KDV hariç) + KDV = toplam · satış − alış = marj
#: Aras için: 360,38 + 72,08 = 432,46 ✓ · 360,38 − 262,15 = 98,23 ✓
#:
#: Son satır BİLEREK kullanılamaz durumda (PTT): ekranların "bu hesapla fiyat
#: üretilemedi" satırını tasarlayabilmesi için. Boş liste döndürmek yerine
#: hesabı SEBEBİYLE göstermek, "PTT neden yok?" sorusunu ekranda cevaplıyor.
SAMPLE_PRICE_QUOTES: list[dict[str, Any]] = [
	{
		"quote_id": "Q-2026-0821-ARAS",
		"carrier_account": "CACC-AK-SEL00001",
		"carrier": "AK",
		"carrier_service": "AK-STD",
		"account_owner": "Demir Tekstil",
		"zone": "TR-DOGU",
		"chargeable_weight": 42.0,
		"carrier_cost": 262.15,
		"customer_charge": 360.38,
		"margin": 98.23,
		"surcharge_total": 23.58,
		"tax_rate": 20.0,
		"tax_amount": 72.08,
		"total_with_tax": 432.46,
		"currency": "TRY",
		"applied_rule": "PR-ALI-ARAS-DOGU",
		"applied_rule_name": "Doğu Anadolu · Aras anlaşmam",
		"applied_layer": "seller",
		"applied_tier_label": "30–50 desi",
		"rule_priority": 10,
		"available": 1,
		"unavailable_reason": None,
		"estimated_days_min": 3,
		"estimated_days_max": 4,
		"valid_until": "2026-08-22 09:00:00",
		"is_snapshot": 0,
		"surcharges": [
			{"surcharge_type": "Yakıt farkı", "amount": 23.58, "basis": "percent", "value": 7.0},
		],
		# Değerlendirme İZİ — TUR-121'in "açıklanabilir olmalı" kriterinin
		# tek karşılığı. `reason_code` ZORUNLU: arayüz koda göre dallanır,
		# metne göre dallanmak i18n ile kırılır.
		"evaluations": [
			{
				"rule": "PR-FREE-5000",
				"rule_name": "Ücretsiz kargo · 5.000 ₺ üzeri sipariş",
				"layer": "platform_mandatory",
				"owner": None,
				"matched": 0,
				"reason_code": "ORDER_TOTAL_BELOW_MIN",
				"reason": "Sipariş tutarı 4.200,00 ₺ — eşik 5.000,00 ₺",
			},
			{
				"rule": "PR-ALI-SELF-IST",
				"rule_name": "İstanbul içi · kendi aracım",
				"layer": "seller",
				"owner": "SEL-00001",
				"matched": 0,
				"reason_code": "ZONE_MISMATCH",
				"reason": "Varış bölgesi Doğu Anadolu, kural Marmara için yazılmış",
			},
			{
				"rule": "PR-ALI-ARAS-DOGU",
				"rule_name": "Doğu Anadolu · Aras anlaşmam",
				"layer": "seller",
				"owner": "SEL-00001",
				"matched": 1,
				"reason_code": None,
				"reason": "30–50 desi kademesi · Doğu Anadolu · Aras Kargo — UYGULANDI",
			},
			{
				"rule": "PR-ALI-MNG-STD",
				"rule_name": "Standart · MNG anlaşmam",
				"layer": "seller",
				"owner": "SEL-00001",
				"matched": 0,
				"reason_code": "HIGHER_PRIORITY_WON",
				"reason": "Aynı katmanda #10 öncelikli kural önce eşleşti (bu kural #20)",
			},
			{
				"rule": "PR-STD-YK",
				"rule_name": "Standart Kargo · İç Anadolu",
				"layer": "platform",
				"owner": None,
				"matched": 0,
				"reason_code": "SELLER_LAYER_MATCHED",
				"reason": "Satıcı katmanında eşleşme bulundu — platform katmanına inilmedi",
			},
			{
				"rule": "PR-EAST-YK",
				"rule_name": "Doğu bölgesi ek ücreti",
				"layer": "platform",
				"owner": None,
				"matched": 0,
				"reason_code": "SELLER_LAYER_MATCHED",
				"reason": "Satıcı katmanında eşleşme bulundu — platform katmanına inilmedi",
			},
			{
				"rule": "PR-HEAVY",
				"rule_name": "Ağır yük · 100 kg üzeri",
				"layer": "platform",
				"owner": None,
				"matched": 0,
				"reason_code": "RULE_INACTIVE",
				"reason": "Kural pasif",
			},
		],
	},
	{
		"quote_id": "Q-2026-0821-MNG",
		"carrier_account": "CACC-MNG-SEL00001",
		"carrier": "MNG",
		"carrier_service": None,
		"account_owner": "Demir Tekstil",
		"zone": "TR-DOGU",
		"chargeable_weight": 42.0,
		"carrier_cost": 291.00,
		"customer_charge": 399.20,
		"margin": 108.20,
		"surcharge_total": 0.00,
		"tax_rate": 20.0,
		"tax_amount": 79.84,
		"total_with_tax": 479.04,
		"currency": "TRY",
		"applied_rule": "PR-ALI-MNG-STD",
		"applied_rule_name": "Standart · MNG anlaşmam",
		"applied_layer": "seller",
		"applied_tier_label": "30–50 desi",
		"rule_priority": 20,
		"available": 1,
		"unavailable_reason": None,
		"estimated_days_min": 2,
		"estimated_days_max": 2,
		"valid_until": "2026-08-22 09:00:00",
		"is_snapshot": 0,
		"surcharges": [],
		"evaluations": [],
	},
	{
		"quote_id": "Q-2026-0821-YK",
		"carrier_account": "CACC-YK-PLATFORM",
		"carrier": "YK",
		"carrier_service": "YK-STD",
		"account_owner": None,
		"zone": "TR-DOGU",
		"chargeable_weight": 42.0,
		"carrier_cost": 312.70,
		"customer_charge": 445.41,
		"margin": 132.71,
		"surcharge_total": 60.21,
		"tax_rate": 20.0,
		"tax_amount": 89.08,
		"total_with_tax": 534.49,
		"currency": "TRY",
		"applied_rule": "PR-EAST-YK",
		"applied_rule_name": "Doğu bölgesi ek ücreti",
		"applied_layer": "platform",
		"applied_tier_label": "30–50 desi",
		"rule_priority": 20,
		"available": 1,
		"unavailable_reason": None,
		"estimated_days_min": 2,
		"estimated_days_max": 3,
		"valid_until": "2026-08-22 09:00:00",
		"is_snapshot": 0,
		"surcharges": [
			{"surcharge_type": "Ücra bölge", "amount": 35.00, "basis": "fixed", "value": 35.0},
			{"surcharge_type": "Yakıt farkı", "amount": 25.21, "basis": "percent", "value": 6.0},
		],
		"evaluations": [],
	},
	{
		"quote_id": "Q-2026-0821-PTT",
		"carrier_account": "CACC-PTT-PLATFORM",
		"carrier": "PTT",
		"carrier_service": None,
		"account_owner": None,
		"zone": "TR-DOGU",
		"chargeable_weight": 42.0,
		"carrier_cost": None,
		"customer_charge": 0.00,
		"margin": None,
		"surcharge_total": 0.00,
		"tax_rate": 20.0,
		"tax_amount": 0.00,
		"total_with_tax": 0.00,
		"currency": "TRY",
		"applied_rule": None,
		"applied_rule_name": None,
		"applied_layer": None,
		"applied_tier_label": None,
		"rule_priority": None,
		"available": 0,
		"unavailable_reason": "NO_RULE_MATCHED",
		"estimated_days_min": None,
		"estimated_days_max": None,
		"valid_until": None,
		"is_snapshot": 0,
		"surcharges": [],
		"evaluations": [],
	},
]

SAMPLE_CONNECTION_TESTS: list[dict[str, Any]] = [
	{
		"carrier_account": "CACC-YK-PLATFORM",
		"probe": "authenticate",
		"succeeded": 1,
		"http_status": 200,
		"duration_ms": 412,
		"message": "Kimlik doğrulama başarılı.",
		"error_code": None,
		"tested_at": "2026-08-12 09:05:00",
		"tested_by": "operasyon@istoc.com",
	},
	{
		"carrier_account": "CACC-YK-PLATFORM",
		"probe": "quote",
		"succeeded": 1,
		"http_status": 200,
		"duration_ms": 1980,
		"message": "Fiyat sorgusu döndü (42 desi → 268,40 TL).",
		"error_code": None,
		"tested_at": "2026-08-12 09:05:01",
		"tested_by": "operasyon@istoc.com",
	},
	# Kısmi başarı gerçek hayatta en sık senaryo: hesap doğrulanıyor ama
	# takip yetkisi verilmemiş oluyor. Ekran "bağlantı çalışıyor" DEMEMELİ.
	{
		"carrier_account": "CACC-YK-PLATFORM",
		"probe": "track",
		"succeeded": 0,
		"http_status": 403,
		"duration_ms": 305,
		"message": "Takip servisi için hesap yetkilendirilmemiş.",
		"error_code": "TRACK_NOT_AUTHORIZED",
		"tested_at": "2026-08-12 09:05:03",
		"tested_by": "operasyon@istoc.com",
	},
]

SAMPLE_INTEGRATION_LOGS: list[dict[str, Any]] = [
	{
		"name": "ILOG-2026-004512",
		"carrier": "YK",
		"carrier_account": "CACC-YK-PLATFORM",
		"operation": "create_shipment",
		"direction": "outbound",
		"shipment": "SHP-2026-00042",
		"succeeded": 1,
		"http_status": 201,
		"duration_ms": 842,
		"attempt": 1,
		"error_code": None,
		"error_message": None,
		"request_body": '{"apiKey":"***MASKELİ***","desi":42,"alici":{"il":"Ankara"}}',
		"response_body": '{"takipNo":"7801234567890","durum":"OLUSTURULDU"}',
		"is_retriable": 0,
		"created_at": "2026-08-10 08:05:00",
	},
	{
		"name": "ILOG-2026-004518",
		"carrier": "YK",
		"carrier_account": "CACC-YK-PLATFORM",
		"operation": "track",
		"direction": "outbound",
		"shipment": "SHP-2026-00042",
		"succeeded": 0,
		"http_status": 403,
		"duration_ms": 305,
		"attempt": 2,
		"error_code": "TRACK_NOT_AUTHORIZED",
		"error_message": "Takip servisi için hesap yetkilendirilmemiş.",
		"request_body": '{"apiKey":"***MASKELİ***","takipNo":"7801234567890"}',
		"response_body": '{"hata":"YETKISIZ","kod":403}',
		"is_retriable": 1,
		"created_at": "2026-08-12 09:05:03",
	},
	{
		"name": "ILOG-2026-004520",
		"carrier": "AK",
		"carrier_account": "CACC-AK-SEL00001",
		"operation": "webhook",
		"direction": "inbound",
		"shipment": "SHP-2026-00038",
		"succeeded": 0,
		"http_status": 400,
		"duration_ms": 12,
		"attempt": 1,
		"error_code": "UNKNOWN_STATUS_CODE",
		"error_message": "Eşlenmemiş taşıyıcı durum kodu: 942",
		"request_body": '{"imza":"***MASKELİ***","durumKodu":"942","zaman":"2026-08-12T10:11:00"}',
		"response_body": '{"ok":false,"error":{"code":"UNKNOWN_STATUS_CODE"}}',
		"is_retriable": 1,
		"created_at": "2026-08-12 10:11:02",
	},
]

# Palet kapasitesi 800 kg / 5 katman; ikinci palet ağırlıkta aşıyor.
SAMPLE_PALLET_PLANS: list[dict[str, Any]] = [
	{
		"name": "PLT-2026-00019",
		"shipment": "SHP-2026-00042",
		"pallet_code": "PLT-42-A",
		"pallet_type": "PALLET_EU",
		"layer_count": 3,
		"max_layers": 5,
		"package_count": 2,
		"loaded_weight_kg": 26.0,
		"max_weight_kg": 800.0,
		"loaded_desi": 60.0,
		"is_overloaded": 0,
	},
	{
		"name": "PLT-2026-00020",
		"shipment": "SHP-2026-00042",
		"pallet_code": "PLT-42-B",
		"pallet_type": "PALLET_EU",
		"layer_count": 6,
		"max_layers": 5,
		"package_count": 1,
		"loaded_weight_kg": 12.5,
		"max_weight_kg": 800.0,
		"loaded_desi": 18.0,
		"is_overloaded": 1,
	},
]

SAMPLE_IMPORT_JOBS: list[dict[str, Any]] = [
	{
		"name": "IMP-2026-00031",
		"file_name": "sevkiyatlar-agustos.csv",
		"status": "previewing",
		"total_rows": 128,
		"valid_rows": 124,
		"error_rows": 4,
		"applied_rows": 0,
		"column_mapping": {
			"Siparis No": "order",
			"Kargo": "carrier",
			"Takip": "tracking_number",
			"Sevk Tarihi": "ship_date",
			"Tutar": "carrier_cost",
		},
		"errors": [
			{"row": 12, "column": "Kargo", "message": "Bilinmeyen taşıyıcı kodu: YRTC"},
			{"row": 45, "column": "Sevk Tarihi", "message": "Tarih çözümlenemedi: 32.08.2026"},
			{"row": 77, "column": "Siparis No", "message": "Sipariş bulunamadı: ORD-2026-99999"},
			{"row": 103, "column": "Tutar", "message": "Sayı değil: '—'"},
		],
		"created_at": "2026-08-12 08:30:00",
		"created_by": "operasyon@istoc.com",
	},
]

SAMPLE_NOTIFICATION_TEMPLATES: list[dict[str, Any]] = [
	{
		"name": "NT-SHIPPED-BUYER-EMAIL",
		"event": "shipment_shipped",
		"channel": "email",
		"recipient_role": "buyer",
		"subject": "Siparişiniz yola çıktı — {{tracking_number}}",
		"body": "<p>{{shipment}} numaralı sevkiyatınız {{carrier}} ile yola çıktı.</p>",
		"is_active": 1,
		"is_mandatory": 0,
	},
	{
		"name": "NT-EXCEPTION-OPS-INAPP",
		"event": "shipment_exception",
		"channel": "in_app",
		"recipient_role": "operations",
		"subject": None,
		"body": "<p>{{shipment}}: {{exception_code}} — {{status}}</p>",
		"is_active": 1,
		"is_mandatory": 1,
	},
	{
		"name": "NT-DELIVERED-SELLER-EMAIL",
		"event": "shipment_delivered",
		"channel": "email",
		"recipient_role": "seller",
		"subject": "Teslim edildi — {{shipment}}",
		"body": "<p>{{shipment}} teslim edildi.</p>",
		"is_active": 0,
		"is_mandatory": 0,
	},
]

SAMPLE_NOTIFICATION_PREFERENCES: list[dict[str, Any]] = [
	{
		"template": "NT-SHIPPED-BUYER-EMAIL",
		"event": "shipment_shipped",
		"channel": "email",
		"recipient_role": "buyer",
		"enabled": 1,
		"is_mandatory": 0,
		"locked_reason": None,
	},
	{
		"template": "NT-EXCEPTION-OPS-INAPP",
		"event": "shipment_exception",
		"channel": "in_app",
		"recipient_role": "operations",
		"enabled": 1,
		"is_mandatory": 1,
		"locked_reason": "Zorunlu operasyon bildirimi — kapatılamaz.",
	},
	{
		"template": "NT-DELIVERED-SELLER-EMAIL",
		"event": "shipment_delivered",
		"channel": "email",
		"recipient_role": "seller",
		"enabled": 0,
		"is_mandatory": 0,
		"locked_reason": None,
	},
]

SAMPLE_OPERATION_ALERTS: list[dict[str, Any]] = [
	{
		"name": "ALR-2026-00088",
		"alert_type": "integration_failure",
		"severity": "Critical",
		"title": "YK takip servisi 403 dönüyor",
		"detail": "Son 30 dakikada 14 takip sorgusu yetkisiz hatası aldı.",
		"shipment": None,
		"carrier": "YK",
		"affected_count": 14,
		"raised_at": "2026-08-12 09:35:00",
		"acknowledged_at": None,
		"acknowledged_by": None,
	},
	{
		"name": "ALR-2026-00087",
		"alert_type": "sla_breach",
		"severity": "Warning",
		"title": "3 sevkiyat tahmini teslim tarihini aştı",
		"detail": "SHP-2026-00035, SHP-2026-00038, SHP-2026-00041",
		"shipment": None,
		"carrier": None,
		"affected_count": 3,
		"raised_at": "2026-08-12 06:00:00",
		"acknowledged_at": "2026-08-12 08:10:00",
		"acknowledged_by": "operasyon@istoc.com",
	},
	{
		"name": "ALR-2026-00086",
		"alert_type": "stuck_shipment",
		"severity": "Warning",
		"title": "SHP-2026-00035 üç gündür durum değiştirmedi",
		"detail": "Son olay: 2026-08-09 14:20 · At Warehouse",
		"shipment": "SHP-2026-00035",
		"carrier": "AK",
		"affected_count": 1,
		"raised_at": "2026-08-12 05:00:00",
		"acknowledged_at": None,
		"acknowledged_by": None,
	},
]

#: Fiyat kuralı örnekleri — 20-FE mockup'ıyla BİREBİR (onaylandı 2026-08-21).
#:
#: Küme bilinçli olarak üç katmanı da içeriyor: bir zorunlu platform kuralı,
#: iki satıcının kendi kuralları, üç normal platform kuralı. Ayrıca iki tuzak
#: bilerek kuruldu ki ekranlar onları TASARLAYABİLSİN:
#:   * PR-STD-YK ve PR-STD-YK-ESKI aynı katmanda aynı önceliği paylaşıyor
#:     → `priority_conflict_with` dolu, K2 kırmızı uyarıyı çizebiliyor.
#:   * PR-ALI-SELF-IST'te satış (0) alışın (80) altında → `has_negative_margin`
#:     dolu, K1 "zararda" rozetini çizebiliyor. Satıcı kendi aracıyla teslim
#:     ederken kargoyu bilerek ücretsiz veriyor; zarar GERÇEK ve görünmeli.
SAMPLE_PRICING_RULES: list[dict[str, Any]] = [
	{
		"name": "PR-FREE-5000",
		"rule_name": "Ücretsiz kargo · 5.000 ₺ üzeri sipariş",
		"seller_profile": None,
		"owner_label": "Platform",
		"layer": "platform_mandatory",
		"is_mandatory": 1,
		"carrier_account": None,
		"carrier": None,
		"carrier_service": None,
		"shipping_method": None,
		"zone": None,
		"zone_label": None,
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": 5000.00,
		"priority": 1,
		"is_active": 1,
		"tier_count": 1,
		"min_base_cost": None,
		"max_base_cost": None,
		"min_base_charge": 0.00,
		"max_base_charge": 0.00,
		"has_negative_margin": 0,
		"surcharge_count": 0,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-01-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 0.0,
				"max_desi": None,
				"base_cost": None,
				"base_charge": 0.00,
				"per_desi_charge": None,
				"min_charge": None,
			},
		],
		"surcharges": [],
		"description": "Kampanya. Zorunlu işaretli: satıcı kendi tarifesini yazmış olsa bile bu kural kazanır.",
		"modified": "2026-08-20 14:05:00",
		"modified_by": "pazarlama@istoc.com",
	},
	{
		"name": "PR-ALI-SELF-IST",
		"rule_name": "İstanbul içi · kendi aracım",
		"seller_profile": "SEL-00001",
		"owner_label": "Demir Tekstil",
		"layer": "seller",
		"is_mandatory": 0,
		"carrier_account": None,
		"carrier": None,
		"carrier_service": None,
		"shipping_method": "Satıcı Aracı",
		"zone": "TR-MARMARA",
		"zone_label": "Marmara",
		"origin_city": "İstanbul",
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 5,
		"is_active": 1,
		"tier_count": 1,
		"min_base_cost": 80.00,
		"max_base_cost": 80.00,
		"min_base_charge": 0.00,
		"max_base_charge": 0.00,
		"has_negative_margin": 1,
		"surcharge_count": 0,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-03-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 0.0,
				"max_desi": None,
				"base_cost": 80.00,
				"base_charge": 0.00,
				"per_desi_charge": None,
				"min_charge": None,
			},
		],
		"surcharges": [],
		"description": "Kendi kamyonumla dağıtıyorum; yakıt maliyeti bende kalıyor, alıcıdan kargo almıyorum.",
		"modified": "2026-08-18 09:12:00",
		"modified_by": "mehmet@demirtekstil.com",
	},
	{
		"name": "PR-ALI-ARAS-DOGU",
		"rule_name": "Doğu Anadolu · Aras anlaşmam",
		"seller_profile": "SEL-00001",
		"owner_label": "Demir Tekstil",
		"layer": "seller",
		"is_mandatory": 0,
		"carrier_account": "CACC-AK-SEL00001",
		"carrier": "AK",
		"carrier_service": "AK-STD",
		"shipping_method": "Standart Kargo",
		"zone": "TR-DOGU",
		"zone_label": "Doğu Anadolu",
		"origin_city": "İstanbul",
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 10,
		"is_active": 1,
		"tier_count": 4,
		"min_base_cost": 120.00,
		"max_base_cost": 310.00,
		"min_base_charge": 165.00,
		"max_base_charge": 410.00,
		"has_negative_margin": 0,
		"surcharge_count": 1,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-01-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 0.0,
				"max_desi": 10.0,
				"base_cost": 120.00,
				"base_charge": 165.00,
				"per_desi_charge": None,
				"min_charge": 165.00,
			},
			{
				"min_desi": 10.0,
				"max_desi": 30.0,
				"base_cost": 185.00,
				"base_charge": 245.00,
				"per_desi_charge": 1.10,
				"min_charge": None,
			},
			{
				"min_desi": 30.0,
				"max_desi": 50.0,
				"base_cost": 245.00,
				"base_charge": 320.00,
				"per_desi_charge": 1.40,
				"min_charge": None,
			},
			{
				"min_desi": 50.0,
				"max_desi": None,
				"base_cost": 310.00,
				"base_charge": 410.00,
				"per_desi_charge": 2.20,
				"min_charge": None,
			},
		],
		"surcharges": [
			{"surcharge_type": "Yakıt farkı", "calc_method": "percent", "value": 7.0, "applies_to": "both"},
		],
		"description": "Aras ile 2026 sözleşmem. Yakıt farkı sözleşmede yüzde olarak tanımlı.",
		"modified": "2026-08-15 16:40:00",
		"modified_by": "mehmet@demirtekstil.com",
	},
	{
		"name": "PR-ALI-MNG-STD",
		"rule_name": "Standart · MNG anlaşmam",
		"seller_profile": "SEL-00001",
		"owner_label": "Demir Tekstil",
		"layer": "seller",
		"is_mandatory": 0,
		"carrier_account": "CACC-MNG-SEL00001",
		"carrier": "MNG",
		"carrier_service": None,
		"shipping_method": "Standart Kargo",
		"zone": None,
		"zone_label": None,
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 20,
		"is_active": 1,
		"tier_count": 1,
		"min_base_cost": 291.00,
		"max_base_cost": 291.00,
		"min_base_charge": 380.00,
		"max_base_charge": 380.00,
		"has_negative_margin": 0,
		"surcharge_count": 0,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-02-15",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 30.0,
				"max_desi": 50.0,
				"base_cost": 291.00,
				"base_charge": 380.00,
				"per_desi_charge": 1.60,
				"min_charge": None,
			},
		],
		"surcharges": [],
		"description": "MNG daha hızlı ama pahalı; Aras'ın gitmediği yerlerde kullanıyorum.",
		"modified": "2026-08-15 16:52:00",
		"modified_by": "mehmet@demirtekstil.com",
	},
	{
		"name": "PR-YLD-DOGU",
		"rule_name": "Doğu Anadolu · Yıldız tarifesi",
		"seller_profile": "SEL-00002",
		"owner_label": "Yıldız Nalbur",
		"layer": "seller",
		"is_mandatory": 0,
		"carrier_account": None,
		"carrier": None,
		"carrier_service": None,
		"shipping_method": None,
		"zone": "TR-DOGU",
		"zone_label": "Doğu Anadolu",
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 10,
		"is_active": 1,
		"tier_count": 1,
		"min_base_cost": 260.00,
		"max_base_cost": 260.00,
		"min_base_charge": 900.00,
		"max_base_charge": 900.00,
		"has_negative_margin": 0,
		"surcharge_count": 0,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-01-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 30.0,
				"max_desi": 50.0,
				"base_cost": 260.00,
				"base_charge": 900.00,
				"per_desi_charge": None,
				"min_charge": None,
			},
		],
		"surcharges": [],
		"description": "BAŞKA satıcının kuralı — Ali Hırdavat oturumunda GÖRÜNMEMELİ. Tenant sınırının ölçüldüğü kayıt.",
		"modified": "2026-08-11 11:00:00",
		"modified_by": "yildiz@yildiznalbur.com",
	},
	{
		"name": "PR-STD-YK",
		"rule_name": "Standart Kargo · İç Anadolu",
		"seller_profile": None,
		"owner_label": "Platform",
		"layer": "platform",
		"is_mandatory": 0,
		"carrier_account": "CACC-YK-PLATFORM",
		"carrier": "YK",
		"carrier_service": "YK-STD",
		"shipping_method": "Standart Kargo",
		"zone": "TR-IC",
		"zone_label": "İç Anadolu",
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 10,
		"is_active": 1,
		"tier_count": 3,
		"min_base_cost": 110.00,
		"max_base_cost": 210.00,
		"min_base_charge": 150.00,
		"max_base_charge": 280.00,
		"has_negative_margin": 0,
		"surcharge_count": 1,
		"priority_conflict_with": ["PR-STD-YK-ESKI"],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-01-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 0.0,
				"max_desi": 10.0,
				"base_cost": 110.00,
				"base_charge": 150.00,
				"per_desi_charge": None,
				"min_charge": 150.00,
			},
			{
				"min_desi": 10.0,
				"max_desi": 30.0,
				"base_cost": 165.00,
				"base_charge": 220.00,
				"per_desi_charge": 1.00,
				"min_charge": None,
			},
			{
				"min_desi": 30.0,
				"max_desi": 50.0,
				"base_cost": 210.00,
				"base_charge": 280.00,
				"per_desi_charge": 1.40,
				"min_charge": None,
			},
		],
		"surcharges": [
			{"surcharge_type": "Yakıt farkı", "calc_method": "percent", "value": 6.0, "applies_to": "both"},
		],
		"description": "Yurtiçi ile platform sözleşmesi, 2026 tarifesi.",
		"modified": "2026-08-01 10:00:00",
		"modified_by": "lojistik@istoc.com",
	},
	{
		"name": "PR-STD-YK-ESKI",
		"rule_name": "Standart Kargo · İç Anadolu (2025 tarifesi)",
		"seller_profile": None,
		"owner_label": "Platform",
		"layer": "platform",
		"is_mandatory": 0,
		"carrier_account": "CACC-YK-PLATFORM",
		"carrier": "YK",
		"carrier_service": "YK-STD",
		"shipping_method": "Standart Kargo",
		"zone": "TR-IC",
		"zone_label": "İç Anadolu",
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 10,
		"is_active": 1,
		"tier_count": 1,
		"min_base_cost": 195.00,
		"max_base_cost": 195.00,
		"min_base_charge": 260.00,
		"max_base_charge": 260.00,
		"has_negative_margin": 0,
		"surcharge_count": 0,
		"priority_conflict_with": ["PR-STD-YK"],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2025-01-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 30.0,
				"max_desi": 50.0,
				"base_cost": 195.00,
				"base_charge": 260.00,
				"per_desi_charge": 1.20,
				"min_charge": None,
			},
		],
		"surcharges": [],
		"description": "Geçen yılın tarifesi pasifleştirilmeyi unutmuş. AYNI önceliği paylaşıyor — hangisinin kazanacağı belirsiz.",
		"modified": "2025-01-04 08:30:00",
		"modified_by": "lojistik@istoc.com",
	},
	{
		"name": "PR-EAST-YK",
		"rule_name": "Doğu bölgesi ek ücreti",
		"seller_profile": None,
		"owner_label": "Platform",
		"layer": "platform",
		"is_mandatory": 0,
		"carrier_account": "CACC-YK-PLATFORM",
		"carrier": "YK",
		"carrier_service": None,
		"shipping_method": None,
		"zone": "TR-DOGU",
		"zone_label": "Doğu Anadolu",
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": None,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 20,
		"is_active": 1,
		"tier_count": 1,
		"min_base_cost": 260.00,
		"max_base_cost": 260.00,
		"min_base_charge": 360.00,
		"max_base_charge": 360.00,
		"has_negative_margin": 0,
		"surcharge_count": 2,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-01-01",
		"valid_until": None,
		"tiers": [
			{
				"min_desi": 30.0,
				"max_desi": 50.0,
				"base_cost": 260.00,
				"base_charge": 360.00,
				"per_desi_charge": 2.10,
				"min_charge": None,
			},
		],
		# SIRA ANLAMLI: ek ücretler yazıldıkları sırayla uygulanır ve `percent`
		# o ana kadar BİRİKMİŞ tutar üzerinden hesaplanır. Ücra bölge bedeli
		# önce ekleniyor, yakıt farkı onun da üzerine biniyor — taşıyıcıların
		# gerçek uygulaması bu. Sıra ters olsaydı 445,41 yerine 443,31 çıkardı.
		"surcharges": [
			{"surcharge_type": "Ücra bölge", "calc_method": "fixed", "value": 35.0, "applies_to": "both"},
			{"surcharge_type": "Yakıt farkı", "calc_method": "percent", "value": 6.0, "applies_to": "both"},
		],
		"description": "Doğu illerinde taşıyıcı ücra bölge bedeli uyguluyor; yansıtılıyor.",
		"modified": "2026-08-01 10:04:00",
		"modified_by": "lojistik@istoc.com",
	},
	{
		"name": "PR-HEAVY",
		"rule_name": "Ağır yük · 100 kg üzeri",
		"seller_profile": None,
		"owner_label": "Platform",
		"layer": "platform",
		"is_mandatory": 0,
		"carrier_account": None,
		"carrier": None,
		"carrier_service": None,
		"shipping_method": "Ambar Teslim",
		"zone": None,
		"zone_label": None,
		"origin_city": None,
		"destination_city": None,
		"min_weight_kg": 100.0,
		"max_weight_kg": None,
		"min_order_total": None,
		"priority": 15,
		"is_active": 0,
		"tier_count": 1,
		"min_base_cost": 850.00,
		"max_base_cost": 850.00,
		"min_base_charge": 1100.00,
		"max_base_charge": 1100.00,
		"has_negative_margin": 0,
		"surcharge_count": 0,
		"priority_conflict_with": [],
		"shadowed_by": None,
		"currency": "TRY",
		"tax_rate": 20.0,
		"valid_from": "2026-06-01",
		"valid_until": "2026-12-31",
		"tiers": [
			{
				"min_desi": 0.0,
				"max_desi": None,
				"base_cost": 850.00,
				"base_charge": 1100.00,
				"per_desi_charge": 0.90,
				"min_charge": None,
			},
		],
		"surcharges": [],
		"description": "PASİF kayıt — ekranların 'pasif' durumunu tasarlayabilmesi için kümede duruyor.",
		"modified": "2026-07-30 12:00:00",
		"modified_by": "lojistik@istoc.com",
	},
]

#: Kargo bölgeleri (20-FE K3) — 7 coğrafi bölge + ada/uzak yol.
#:
#: İl sayıları Türkiye'nin gerçek coğrafi bölge dağılımıyla tutarlı; toplam
#: 81. Tasarım incelemesi tutarsız veriyle yanıltıcı olur.
SAMPLE_SHIPPING_ZONES: list[dict[str, Any]] = [
	{
		"name": "TR-MARMARA",
		"zone_code": "TR-MARMARA",
		"zone_name": "Marmara",
		"is_active": 1,
		"city_count": 11,
		"cities": [
			{"city": "İstanbul"},
			{"city": "Bursa"},
			{"city": "Kocaeli"},
			{"city": "Tekirdağ"},
			{"city": "Balıkesir"},
			{"city": "Çanakkale"},
			{"city": "Edirne"},
			{"city": "Kırklareli"},
			{"city": "Sakarya"},
			{"city": "Yalova"},
			{"city": "Bilecik"},
		],
	},
	{
		"name": "TR-IC",
		"zone_code": "TR-IC",
		"zone_name": "İç Anadolu",
		"is_active": 1,
		"city_count": 13,
		"cities": [
			{"city": "Ankara"},
			{"city": "Konya"},
			{"city": "Kayseri"},
			{"city": "Sivas"},
			{"city": "Eskişehir"},
			{"city": "Kırıkkale"},
			{"city": "Aksaray"},
			{"city": "Niğde"},
			{"city": "Nevşehir"},
			{"city": "Kırşehir"},
			{"city": "Yozgat"},
			{"city": "Çankırı"},
			{"city": "Karaman"},
		],
	},
	{
		"name": "TR-DOGU",
		"zone_code": "TR-DOGU",
		"zone_name": "Doğu Anadolu",
		"is_active": 1,
		"city_count": 14,
		"cities": [
			{"city": "Van"},
			{"city": "Erzurum"},
			{"city": "Malatya"},
			{"city": "Elazığ"},
			{"city": "Ağrı"},
			{"city": "Kars"},
			{"city": "Muş"},
			{"city": "Bitlis"},
			{"city": "Hakkari"},
			{"city": "Erzincan"},
			{"city": "Bingöl"},
			{"city": "Tunceli"},
			{"city": "Ardahan"},
			{"city": "Iğdır"},
		],
	},
	{
		"name": "TR-ADA",
		"zone_code": "TR-ADA",
		"zone_name": "Ada ve uzak yol",
		"is_active": 0,
		"city_count": 2,
		"cities": [{"city": "Gökçeada"}, {"city": "Bozcaada"}],
	},
]

#: Oranlar sayılarla TUTARLI: YK için 120 sevkiyat, 108 teslim, 9 gecikme,
#: 3 başarısız → on_time = (108-9)/120 = 0,825; failure = 3/120 = 0,025.
SAMPLE_PERFORMANCE_REPORT: list[dict[str, Any]] = [
	{
		"dimension": "YK",
		"dimension_label": "Yurtiçi Kargo",
		"shipment_count": 120,
		"delivered_count": 108,
		"delayed_count": 9,
		"failed_count": 3,
		"returned_count": 6,
		"avg_delivery_days": 2.4,
		"p90_delivery_days": 4.8,
		"on_time_rate": 0.825,
		"failure_rate": 0.025,
		"return_rate": 0.05,
	},
	{
		"dimension": "AK",
		"dimension_label": "Aras Kargo",
		"shipment_count": 84,
		"delivered_count": 79,
		"delayed_count": 4,
		"failed_count": 1,
		"returned_count": 3,
		"avg_delivery_days": 2.1,
		"p90_delivery_days": 3.6,
		"on_time_rate": 0.893,
		"failure_rate": 0.012,
		"return_rate": 0.036,
	},
	# Kötü performans: ortalama iyi görünüyor ama p90 iki katı ve
	# başarısızlık oranı yüksek. Yalnız ortalamaya bakan bir rapor bunu
	# gizlerdi — p90 alanı bu yüzden sözleşmede.
	{
		"dimension": "MNG",
		"dimension_label": "MNG Kargo",
		"shipment_count": 41,
		"delivered_count": 30,
		"delayed_count": 11,
		"failed_count": 7,
		"returned_count": 4,
		"avg_delivery_days": 2.9,
		"p90_delivery_days": 8.5,
		"on_time_rate": 0.463,
		"failure_rate": 0.171,
		"return_rate": 0.098,
	},
]

#: Marj tutarları kolonlarla TUTARLI: 32 208,00 − 24 108,00 = 8 100,00.
#: MNG satırı bilinçli olarak ZARARDA — negatif marj görünmeli.
SAMPLE_COST_REPORT: list[dict[str, Any]] = [
	{
		"dimension": "YK",
		"dimension_label": "Yurtiçi Kargo",
		"shipment_count": 120,
		"carrier_cost_total": 24108.00,
		"customer_charge_total": 32208.00,
		"margin_total": 8100.00,
		"margin_rate": 0.2515,
		"avg_cost_per_shipment": 200.90,
		"currency": "TRY",
	},
	{
		"dimension": "AK",
		"dimension_label": "Aras Kargo",
		"shipment_count": 84,
		"carrier_cost_total": 16380.00,
		"customer_charge_total": 21504.00,
		"margin_total": 5124.00,
		"margin_rate": 0.2383,
		"avg_cost_per_shipment": 195.00,
		"currency": "TRY",
	},
	{
		"dimension": "MNG",
		"dimension_label": "MNG Kargo",
		"shipment_count": 41,
		"carrier_cost_total": 12710.00,
		"customer_charge_total": 11480.00,
		"margin_total": -1230.00,
		"margin_rate": -0.1071,
		"avg_cost_per_shipment": 310.00,
		"currency": "TRY",
	},
]

PROVISIONAL_SAMPLES: dict[str, dict[str, Any]] = {
	"shipment": {"rows": SAMPLE_SHIPMENTS, "detail": SAMPLE_SHIPMENT_DETAIL},
	"proof_of_delivery": {"rows": SAMPLE_PROOF_OF_DELIVERY, "detail": {}},
	"return_request": {"rows": SAMPLE_RETURN_REQUESTS, "detail": SAMPLE_RETURN_DETAIL},
	"price_quote": {"rows": SAMPLE_PRICE_QUOTES, "detail": {}},
	"connection_test": {"rows": SAMPLE_CONNECTION_TESTS, "detail": {}},
	"integration_log": {"rows": SAMPLE_INTEGRATION_LOGS, "detail": {}},
	"pallet_plan": {"rows": SAMPLE_PALLET_PLANS, "detail": {}},
	"import_job": {"rows": SAMPLE_IMPORT_JOBS, "detail": {}},
	"notification_template": {"rows": SAMPLE_NOTIFICATION_TEMPLATES, "detail": {}},
	"notification_preference": {"rows": SAMPLE_NOTIFICATION_PREFERENCES, "detail": {}},
	"operation_alert": {"rows": SAMPLE_OPERATION_ALERTS, "detail": {}},
	"pricing_rule": {"rows": SAMPLE_PRICING_RULES, "detail": {}},
	"shipping_zone": {"rows": SAMPLE_SHIPPING_ZONES, "detail": {}},
	"performance_report": {"rows": SAMPLE_PERFORMANCE_REPORT, "detail": {}},
	"cost_report": {"rows": SAMPLE_COST_REPORT, "detail": {}},
}
