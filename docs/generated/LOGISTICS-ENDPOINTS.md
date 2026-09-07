# Lojistik uç sözleşmesi — backend başlangıç belgesi

> **ÜRETİLMİŞ DOSYA — elle düzenleme.**
> Kaynak: `tradehub_core/logistics/contract.py` → `PROVISIONAL_ENDPOINTS`
> Yenile: `python3 scripts/gen_logistics_types.py --sync`
> Bayat mı: `python3 scripts/gen_logistics_types.py --check`

Bu belge **6 modüldeki 38 yazılmamış ucun** sözleşmesidir.
Varlıkların hangi alanları taşıdığı ayrı yerde: `docs/logistics-api.schema.json`
→ `provisional` (ve okunabilir özeti `LOGISTICS-API-CONTRACT.md` §3).

**🔸 işaretli hata kodları henüz `logistics/exceptions.py`'de TANIMLI DEĞİL.**
Ekranlar bu kodlara göre dallanıyor; uç yazılırken kod da tanımlanmalı,
yoksa istemci `INTERNAL_ERROR` görür ve doğru kutuyu çizemez.

---

## `api.v1.pickup` — Alıcı teslim alma (randevu + teslim kodu)

**Sahip:** 07-BE · **FE kaynağı:** `07-FE-VERI-SOZLESMESI.md`

| Uç | Döndürür | Hata kodları |
|---|---|---|
| `list_appointment_slots(shipment, date)` | özel yük: `date`, `slots[].value`, `slots[].label`, `slots[].available` | `NOT_FOUND` · `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `request_appointment(shipment, date, slot)` | `shipment` → `appointment_at`, `appointment_window` | `VALIDATION_ERROR` · 🔸`CONFLICT` · `NOT_FOUND` · `PERMISSION_DENIED` |
| `confirm_delivery(shipment, code?)` | `shipment` → `delivery_code_status`, `delivery_code_attempts`, `status` | 🔸`DELIVERY_CODE_EXPIRED` · `PERMISSION_DENIED` · `NOT_FOUND` |
| `resend_delivery_code(shipment)` | `shipment` → `delivery_code_expires_at`, `delivery_code_status` | `PERMISSION_DENIED` · `NOT_FOUND` · `FEATURE_DISABLED` |

**Parametreler:**

- `list_appointment_slots` → `date` (str, zorunlu) — YYYY-MM-DD
- `request_appointment` → `date` (str, zorunlu) — YYYY-MM-DD
- `request_appointment` → `slot` (str, zorunlu) — ör. 09-12
- `confirm_delivery` → `code` (str) — yalnız delivery_code_required=1 iken

**Uygulama notları:**

- `list_appointment_slots` — Boş `slots` ya da hepsi `available:false` → ekran S3-3 (form çizilmez).
- `request_appointment` — Aynı uç hem oluşturur hem değiştirir (S3-1 = S3-2). Ayrı `update_appointment` ucu ekranda ikinci bir kod yolu demek olurdu.
- `confirm_delivery` — Yanlış kod HATA DEĞİL: uç `ok:true` + `delivery_code_status:"failed"` + artmış sayaç döner; ekran formu açık tutar (S4-3). Süre dolumu ise `ok:false` + DELIVERY_CODE_EXPIRED (S4-5).
- `resend_delivery_code` — Yeni kodu mevcut kanaldan iletir (SMS/e-posta — 12-BE'nin işi). `delivery_code_expires_at` sözleşmede yoksa FE bu ucu HİÇ çağırmaz, buton çizilmez (§1.2).

**Sunucuda tekrarlanması gereken kapılar:**

- `list_appointment_slots` — Kapasiteyi SUNUCU bilir; FE listeyi üretmez.
- `list_appointment_slots` — `label` sunucudan gelir — depo çalışma saatleri işletmeye göre değişir.
- `request_appointment` — Geçmiş tarih SUNUCUDA reddedilir → VALIDATION_ERROR. FE'deki iki kat kontrol (input min + Alpine) deneyimdir, güvenlik değildir.
- `confirm_delivery` — Kodun DEĞERİ hiçbir yanıtta dönmez (K-F).
- `confirm_delivery` — Ödeme kontrolü SUNUCUDA tekrarlanır → PERMISSION_DENIED. FE formu hiç çizmiyor (S4-6) ama bu kapı değil kolaylıktır.
- `resend_delivery_code` — Deneme hakkını SIFIRLAMAZ (S4-5) — süre dolumu alıcının hatası değil, ama kod tahmin denemesi de sıfırlanmamalı.

**Varlık sözleşmesinde HENÜZ olmayan alanlar:**

- `resend_delivery_code` → `delivery_code_expires_at` — 07-BE (MOGEM-540) — 07-FE §1: 'Bugün süre kavramı sözleşmede yok'. Alan gelmezse FE bu ucu hiç çağırmaz, buton çizilmez.

---

## `api.v1.packaging` — Paketleme, koli, etiket ve palet

**Sahip:** 13-BE (palet kısmı 19-BE) · **FE kaynağı:** `13-FE-VERI-SOZLESMESI.md`

| Uç | Döndürür | Hata kodları |
|---|---|---|
| `get_packing_queue(bucket?, seller?, carrier?, date_from?, date_to?, page?, page_size?)` | özel yük: `items[].shipment`, `items[].order`, `items[].buyer_name`, `items[].seller_name`, `items[].item_count`, `items[].package_count`, `items[].waiting_hours`, `items[].carrier`, `items[].bucket`, `items[].status`, `total`, `page`, `page_size`, `buckets.unpacked`, `buckets.partial`, `buckets.awaiting_label`, `buckets.ready` | `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `get_shipment_packing(shipment)` | özel yük: `shipment`, `order`, `buyer_name`, `status`, `modified`, `is_locked`, `desi_divisor`, `items[].row_id`, `items[].order_item`, `items[].listing`, `items[].item_name`, `items[].variation`, `items[].qty`, `items[].packed_qty`, `items[].uom`, `items[].scan_code`, `packages[].row_id`, `packages[].package_code`, `packages[].sequence`, `packages[].package_type`, `packages[].length_cm`, `packages[].width_cm`, `packages[].height_cm`, `packages[].weight_kg`, `packages[].qty`, `packages[].desi`, `packages[].chargeable_kg`, `packages[].barcode`, `packages[].contents[].shipment_item`, `packages[].contents[].qty`, `packages[].label.status`, `packages[].label.url`, `packages[].label.barcode_url`, `packages[].label.format`, `packages[].label.generated_at`, `packages[].label.printed_at`, `packages[].label.print_count`, `packages[].label.carrier_tracking`, `totals.package_count`, `totals.total_weight`, `totals.total_desi`, `totals.chargeable_weight`, `package_types[].name`, `package_types[].package_name`, `package_types[].length_cm`, `package_types[].width_cm`, `package_types[].height_cm`, `package_types[].max_weight_kg`, `package_types[].max_desi`, `package_types[].is_default` | `NOT_FOUND` · `PERMISSION_DENIED` |
| `save_shipment_packages(shipment, packages, modified)` | özel yük: `packages[]`, `totals`, `modified` | 🔸`CONFLICT` · 🔸`VALIDATION_FAILED` · 🔸`SHIPMENT_LOCKED` · `PERMISSION_DENIED` |
| `complete_packing(shipment, modified)` | `shipment` → `status`, `modified` | 🔸`VALIDATION_FAILED` · 🔸`CONFLICT` · 🔸`SHIPMENT_LOCKED` |
| `mark_shipment_ready(shipment)` | `shipment` → `status` | 🔸`VALIDATION_FAILED` · 🔸`SHIPMENT_LOCKED` · `PERMISSION_DENIED` |
| `generate_shipment_labels(shipment, package_codes, format?)` | özel yük: `labels[].package_code`, `labels[].url`, `labels[].barcode_url`, `labels[].format`, `labels[].generated_at`, `batch_url` | 🔸`CARRIER_ERROR` · 🔸`VALIDATION_FAILED` · 🔸`SHIPMENT_LOCKED` · `NOT_FOUND` |
| `reprint_shipment_labels(shipment, package_codes, reason, reason_note?)` | özel yük: `labels[].package_code`, `labels[].url`, `labels[].format`, `labels[].print_count`, `labels[].printed_at` | 🔸`LABEL_STALE` · `NOT_FOUND` · `PERMISSION_DENIED` |
| `void_shipment_label(shipment, package_code, reason)` | özel yük: `package_code`, `label` | `NOT_FOUND` · 🔸`SHIPMENT_LOCKED` · `PERMISSION_DENIED` |
| `get_packing_slip(shipment, package_codes?)` | özel yük: `url`, `format` | `NOT_FOUND` · `PERMISSION_DENIED` |
| `get_pallet_plan(shipment)` | özel yük: `pallets[].name`, `pallets[].shipment`, `pallets[].pallet_code`, `pallets[].pallet_type`, `pallets[].layer_count`, `pallets[].max_layers`, `pallets[].package_count`, `pallets[].loaded_weight_kg`, `pallets[].max_weight_kg`, `pallets[].loaded_desi`, `pallets[].is_overloaded`, `pallet_types[].name`, `pallet_types[].max_layers`, `pallet_types[].max_weight_kg`, `pallet_types[].is_default`, `modified` | `NOT_FOUND` · `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `save_pallet_plan(shipment, pallets, modified)` | özel yük: `pallets[].name`, `pallets[].pallet_code`, `pallets[].pallet_type`, `pallets[].layer_count`, `pallets[].package_count`, `pallets[].loaded_weight_kg`, `pallets[].loaded_desi`, `pallets[].is_overloaded`, `modified` | 🔸`CONFLICT` · 🔸`VALIDATION_FAILED` · 🔸`SHIPMENT_LOCKED` |

**Parametreler:**

- `get_packing_queue` → `bucket` (str) — unpacked|partial|awaiting_label|ready
- `get_packing_queue` → `page` (int) — varsayılan 1
- `get_packing_queue` → `page_size` (int) — varsayılan 50
- `save_shipment_packages` → `modified` (str, zorunlu) — optimistik kilit damgası
- `generate_shipment_labels` → `format` (str) — varsayılan thermal_100x150
- `reprint_shipment_labels` → `reason` (str, zorunlu) — ilk basımda null gelebilir

**Uygulama notları:**

- `get_packing_queue` — `buckets` AYNI ÇAĞRIDAN gelmeli. Ayrı istek sayaçları listeden kaydırır: kullanıcı 'Paketlenmedi 2' görür, tıklar, 3 kayıt gelir. `waiting_hours` ham saat — 24sa sarı / 72sa kırmızı eşiği SUNUM kararı.
- `get_shipment_packing` — P2 ve P3'ün ORTAK yükü. `package_types` yükle birlikte gelir, ayrı katalog çağrısı yapılmaz: koli formu preset ölçüleri anında dolsun (ikinci istek her koli açılışını yavaşlatırdı). Aynısı `get_pallet_plan` içindeki `pallet_types` için geçerli. `modified` optimistik kilit damgası.
- `save_shipment_packages` — Yan etkiler: Shipment.total_weight/total_desi/chargeable_weight güncellenir; `content_hash` değişen kolilerin `label_status` → Stale.
- `mark_shipment_ready` — Başarıda status → Ready for Pickup; sevkiyat paketleme kuyruğundan düşer.
- `reprint_shipment_labels` — D2 kararı: ilk basımda gerekçe SORULMAZ, 2. basımdan itibaren zorunlu. Bu bir SUNUM kararıdır — sunucu her zaman `reason` kabul eder.
- `get_pallet_plan` — `pallet_types` yükle birlikte gelir — ayrı katalog çağrısı palet formunu yavaşlatırdı (bkz. get_shipment_packing gerekçesi).
- `save_pallet_plan` — Sahibi 19-BE (palet/desi) — paketleme ekranından çağrılır.

**Sunucuda tekrarlanması gereken kapılar:**

- `get_packing_queue` — Kova tanımları SUNUCUDA hesaplanır, FE tekrarlamaz: unpacked=packages boş · partial=packed_qty<qty olan kalem var · awaiting_label=tüm kalemler paketli ama label_status=None koli var · ready=tümü etiketli.
- `get_shipment_packing` — `is_locked` terminal durumu bildirir → ekran salt-okunur.
- `save_shipment_packages` — Sunucu doğrulaması FE'dekinin TEKRARI ama otorite burasıdır: boş koli yok (contents dolu) · weight_kg>0 · kalem başına atanan toplam <= qty · aynı kalem bir kolide bir kez → VALIDATION_FAILED; terminal durum → SHIPMENT_LOCKED.
- `generate_shipment_labels` — Taşıyıcı hatasında `details.carrier_message` ÇEVRİLMİŞ gelir.

---

## `api.v1.pod` — Teslim kanıtı, teslimat akışları ve devir

**Sahip:** 14-BE · **FE kaynağı:** `14-FE-VERI-SOZLESMESI.md`

| Uç | Döndürür | Hata kodları |
|---|---|---|
| `get_pod_queue(bucket?, q?, carrier?, seller?, page?, page_size?)` | özel yük: `rows[].shipment`, `rows[].order`, `rows[].buyer_name`, `rows[].seller_name`, `rows[].carrier`, `rows[].status`, `rows[].package_count`, `rows[].pallet_count`, `rows[].waybill_number`, `rows[].delivery_point`, `rows[].actual_delivery`, `rows[].hours_since`, `rows[].alarm`, `rows[].bucket`, `rows[].delivered_package_count`, `rows[].total_package_count`, `total`, `buckets[].key`, `buckets[].label`, `buckets[].count`, `buckets[].hint` | `PERMISSION_DENIED` · `CAPABILITY_REQUIRED` |
| `get_proof_of_delivery(shipment)` | `proof_of_delivery` kaydı | `NOT_FOUND` · `CAPABILITY_REQUIRED` |
| `record_proof_of_delivery(shipment, delivered_at, received_by, received_by_title, delivered_package_count, total_package_count, delivered_pallet_count?, returned_pallet_count?, has_discrepancy?, exception_code?, discrepancy_note?, signature_file?, photo_file?, document_file?, location_source?, location_recorded_at?, delivery_point?, modified?)` | `proof_of_delivery` kaydı | 🔸`CONFLICT` · 🔸`POD_ALREADY_RECORDED` · 🔸`INVALID_STATUS` · `VALIDATION_ERROR` |
| `amend_proof_of_delivery(shipment, reason, modified)` | `proof_of_delivery` kaydı | `VALIDATION_ERROR` · 🔸`CONFLICT` · `CAPABILITY_REQUIRED` · `NOT_FOUND` |
| `list_delivery_flows(flow_type, q?, status?)` | özel yük: `items[].shipment`, `items[].order`, `items[].buyer_name`, `items[].seller_name`, `items[].status`, `items[].shipment_type`, `items[].package_count`, `items[].appointment_at`, `items[].appointment_window`, `items[].driver_name`, `items[].driver_phone`, `items[].vehicle_plate`, `items[].delivery_code_required`, `items[].delivery_code_status`, `items[].delivery_code_attempts`, `items[].payment_required_before_delivery`, `items[].payment_status`, `total` | `PERMISSION_DENIED` · `VALIDATION_ERROR` |
| `hand_over_shipment(shipment, delivery_code?, received_by, received_by_title, modified)` | `shipment` → `status` | 🔸`PAYMENT_REQUIRED` · 🔸`DELIVERY_CODE_NOT_VERIFIED` · 🔸`CONFLICT` · `NOT_FOUND` |

**Parametreler:**

- `get_pod_queue` → `q` (str) — serbest arama
- `amend_proof_of_delivery` → `reason` (str, zorunlu) — boş olamaz

**Uygulama notları:**

- `get_pod_queue` — Kovalar AYRI istekle gelmez (13-FE'de ölçülen sayaç kayması gerekçesi).
- `get_proof_of_delivery` — POD yoksa 404 DEĞİL, `proof_of_delivery: null` döner — bu hata değil eksik veridir (S10-2). ⚠ `view.pod_media` capability'si bugün kodda YOK (`permissions.py` yalnız view.logistics_cost + view.carrier_secret tanımlıyor) — 14-BE'nin borcu.
- `record_proof_of_delivery` — Yanıt kaydedilen POD + `created: true`. POD varsa üstüne YAZILMAZ → amend.
- `amend_proof_of_delivery` — `reason` dışındaki alanlar `record_proof_of_delivery` ile aynı. Kullanım vakası: satıcı beyanını operasyon düzeltir (K-B).
- `list_delivery_flows` — D1 / D2 ekranlarının ortak kaynağı.
- `hand_over_shipment` — Başarıda sevkiyat Delivered olur ve POD kaydı tetiklenir — teslim aksiyonu POD'u doğurur, iki iş ayrılamaz (K-F).

**Sunucuda tekrarlanması gereken kapılar:**

- `get_pod_queue` — Satıcı çağırırsa liste kendi `seller_profile`'ıyla SÜZÜLÜR (§6.1).
- `get_pod_queue` — Bekleme süresi (DWELL_WARN_HOURS=24) SUNUCUDA hesaplanır — istemcinin saati güvenilmez.
- `get_proof_of_delivery` — Medya yetkisi (`view.pod_media`) yoksa `signature_url`, `photo_url`, `document_url` yanıttan HİÇ ÇIKARILIR — null gönderilmez, maskelenmez. Ekran o alanları çizmez, kırık görsel göstermez (S10-3).
- `record_proof_of_delivery` — `source` damgasını SUNUCU belirler (Logistics Manager→operator, satıcı→seller, webhook→carrier). İstemci GÖNDEREMEZ.
- `record_proof_of_delivery` — Kısmi teslimde (`delivered_package_count < total_package_count`) `has_discrepancy=1` ZORUNLU; o da `exception_code` zorunlu kılar (§5.1).
- `record_proof_of_delivery` — Sevkiyat `Delivered` değilse INVALID_STATUS.
- `amend_proof_of_delivery` — `pod.amend` yetkisi gerekir — SATICIDA YOK (§6.1).
- `amend_proof_of_delivery` — Kayıt SİLİNMEZ; denetim izine yeni sürüm yazılır.
- `hand_over_shipment` — Ödeme kapısı: `payment_required_before_delivery=1` ve `payment_status="unpaid"` → PAYMENT_REQUIRED.
- `hand_over_shipment` — Kod kapısı: `delivery_code_required=1` ve status != verified → DELIVERY_CODE_NOT_VERIFIED. 3 başarısız denemede kod KİLİTLENİR.

---

## `api.v1.returns` — İade talebi yaşam döngüsü

**Sahip:** 15-BE · **FE kaynağı:** `15-FE-VERI-SOZLESMESI.md`

| Uç | Döndürür | Hata kodları |
|---|---|---|
| `get_return_eligibility(shipment)` | özel yük: `shipment`, `window_open`, `window_days`, `days_left`, `returnable_items[].item`, `returnable_items[].item_name`, `returnable_items[].delivered_qty`, `returnable_items[].already_returned_qty`, `returnable_items[].uom`, `reasons[].value`, `reasons[].label_key` | `NOT_FOUND` · `PERMISSION_DENIED` |
| `list_return_requests(status?, page?, page_size?)` | `return_request` listesi — `{items, total, page, page_size}` | `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `get_return_request(name)` | `return_request` kaydı | `NOT_FOUND` · `PERMISSION_DENIED` |
| `create_return_request(shipment, reason, note?, items, idempotency_key?)` | `return_request` kaydı | 🔸`QTY_EXCEEDS_DELIVERED` · 🔸`RETURN_WINDOW_CLOSED` · 🔸`NOTHING_RETURNABLE` · `IDEMPOTENCY_CONFLICT` · `VALIDATION_ERROR` |
| `decide_return_request(name, decision, decision_note?, create_return_shipment?)` | `return_request` kaydı | 🔸`DECISION_NOTE_REQUIRED` · 🔸`RETURN_ALREADY_DECIDED` · 🔸`RETURN_CLOSED` · `PERMISSION_DENIED` |
| `save_return_inspection(name, items)` | `return_request` kaydı | 🔸`ACCEPTED_EXCEEDS_RECEIVED` · 🔸`RETURN_CLOSED` · `PERMISSION_DENIED` · `VALIDATION_ERROR` |
| `close_return_request(name, trigger_refund?)` | `return_request` kaydı | 🔸`RETURN_NOT_CLOSABLE` · 🔸`RETURN_CLOSED` · `PERMISSION_DENIED` |

**Parametreler:**

- `list_return_requests` → `page` (int) — varsayılan 1
- `list_return_requests` → `page_size` (int) — varsayılan 50
- `create_return_request` → `reason` (str, zorunlu) — return_reason kataloğundan
- `create_return_request` → `items` (list, zorunlu) — [{item, qty}]
- `decide_return_request` → `decision` (str, zorunlu) — approved|rejected
- `decide_return_request` → `decision_note` (str) — redde ZORUNLU, >=10 karakter
- `save_return_inspection` → `items` (list, zorunlu) — [{item, received_qty, accepted_qty}]

**Uygulama notları:**

- `get_return_eligibility` — İade formunun VE sipariş kartındaki düğmenin tek kaynağı; üç soruyu birden cevaplar (pencere açık mı, ne iade edilebilir, hangi nedenler). `window_open: 0` → ekran formu hiç çizmez, kapalı kutusunu gösterir (M-B-2); `returnable_items: []` → 'zaten iade edildi' (M-B-3). İkisi de HATA DEĞİL, normal yanıt — bu yüzden NOTHING_RETURNABLE burada YOK. Sipariş listesi bu ucu N kez ÇAĞIRMAZ (toplu gösterge gerekir, §2.2).
- `create_return_request` — Rol: ALICI.
- `decide_return_request` — RETURN_ALREADY_DECIDED ile RETURN_CLOSED AYRI kodlardır — ekran farklı kutu çiziyor (M-E-3). Rol: satıcı / admin.
- `save_return_inspection` — Rol: platform operasyon / admin.
- `close_return_request` — Uygulama sırasında EN SONA (§9): geri alınamaz ve escrow'a dokunur. Rol: platform yöneticisi.

**Sunucuda tekrarlanması gereken kapılar:**

- `get_return_eligibility` — `delivered_qty` TESLİM edilendir, sevk edilen değil (§1.4) — kısmi teslimatta yalnız eline geçen kalem listelenir.
- `get_return_eligibility` — `reasons` yalnız `is_active` kayıtları taşır, `reason_code asc` sırada.
- `get_return_eligibility` — `label_key` döner, `label` DEĞİL: etiket dört dilde FE'de. Sunucu kendi dilinde metin gönderirse Rusça arayüzde Türkçe görünür.
- `list_return_requests` — Rol süzgeci SUNUCUDA (§6.1): alıcı yalnız kendi taleplerini, satıcı kendi sevkiyatlarınınkini görür.
- `list_return_requests` — Yalnız RETURN_REQUEST_LIST_FIELDS döner — `refund_amount` ve diğer DETAIL alanları liste satırında YOK.
- `get_return_request` — Rol süzgeci sunucuda (§6.1).
- `create_return_request` — `qty > delivered_qty - already_returned_qty` → QTY_EXCEEDS_DELIVERED.
- `create_return_request` — Pencere kapalıysa RETURN_WINDOW_CLOSED — FE formu zaten çizmiyor ama kapı sunucudadır.
- `decide_return_request` — Redde `decision_note` ZORUNLU (en az 10 karakter) → DECISION_NOTE_REQUIRED. Gerekçesiz red, alıcıya sebebini söylemeden hayır demektir.
- `decide_return_request` — Satıcı KAPANIŞ/para iadesi TETİKLEYEMEZ (§6.3).
- `save_return_inspection` — `accepted_qty > received_qty` → ACCEPTED_EXCEEDS_RECEIVED.
- `close_return_request` — Üç ön koşul SUNUCUDA ayrı ayrı doğrulanır; eksikse RETURN_NOT_CLOSABLE ve HANGİ koşulun eksik olduğu bildirilir.
- `close_return_request` — Kapanınca kayıt DEĞİŞTİRİLEMEZ (TUR-116): sonraki her yazma → RETURN_CLOSED.

---

## `api.v1.pricing` — Kargo fiyat kuralları ve simülasyon

**Sahip:** 20-BE · **FE kaynağı:** `20-FE-VERI-SOZLESMESI.md`

| Uç | Döndürür | Hata kodları |
|---|---|---|
| `list_pricing_rules(scope?, q?, zone?, carrier_account?, seller?, is_active?, start?, page_length?)` | özel yük: `items[]`, `layers.platform_mandatory`, `layers.seller`, `layers.platform`, `total`, `page`, `page_size` | `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `get_pricing_rule(name)` | `pricing_rule` kaydı | `NOT_FOUND` · `PERMISSION_DENIED` |
| `save_pricing_rule(name?, values)` | `pricing_rule` kaydı | `PERMISSION_DENIED` · 🔸`MANDATORY_NOT_ALLOWED` · `VALIDATION_ERROR` · 🔸`TIER_RANGE_OVERLAP` · 🔸`TIER_RANGE_GAP` |
| `reorder_pricing_rules(layer, order)` | özel yük: `items[]` | `NOT_FOUND` · `VALIDATION_ERROR` · `PERMISSION_DENIED` |
| `delete_pricing_rule(name)` | özel yük: `name` | 🔸`RULE_IN_USE` · `NOT_FOUND` · `PERMISSION_DENIED` |
| `simulate_price(desi?, weight_kg?, zone?, order_total?, seller_profile?, origin_city?, shipment?, order?)` | özel yük: `input`, `quotes[]`, `recommended` | `VALIDATION_ERROR` · 🔸`ZONE_NOT_FOUND` · `PERMISSION_DENIED` |

**Parametreler:**

- `list_pricing_rules` → `scope` (str) — all|mine
- `save_pricing_rule` → `name` (str) — yoksa oluşturur
- `reorder_pricing_rules` → `order` (list, zorunlu) — kural adları, yeni sıra
- `simulate_price` → `desi` (int) — (a) serbest deneme
- `simulate_price` → `weight_kg` (int) — (a)
- `simulate_price` → `zone` (str) — (a)
- `simulate_price` → `order_total` (int) — (a)
- `simulate_price` → `seller_profile` (str) — (a)
- `simulate_price` → `origin_city` (str) — (a)
- `simulate_price` → `shipment` (str) — (b) gerçek sipariş
- `simulate_price` → `order` (str) — (b)

**Uygulama notları:**

- `list_pricing_rules` — `layers` sayaçları listeyle AYNI yanıttan gelir. Ayrı istek sayaçları kaydırır: kullanıcı 'Satıcı kuralları 4' görür, açar, 3 kayıt gelir (14-FE'de ölçülmüş tuzak). `items[]` = pricing_rule list_fields.
- `save_pricing_rule` — Öncelik çakışması KASITLI olarak hata DEĞİL: kaydı reddetmek yöneticiyi kilitler (iki kuralı sırayla düzenlemek imkânsızlaşır).
- `reorder_pricing_rules` — Sıra sürükleyerek değişir (kök CLAUDE.md §4.14e: sayı yazdırma, sürükletme).
- `simulate_price` — İki girdi biçimi (K5): (a) serbest deneme, (b) `shipment` ya da `order` — değerleri sunucu doldurur. Yanıt TEK teklif değil LİSTE: her kullanılabilir hesap için bir `price_quote` satırı. Kullanılamayan hesap listeden DÜŞMEZ: `available: 0` + `unavailable_reason` ile döner.

**Sunucuda tekrarlanması gereken kapılar:**

- `list_pricing_rules` — Sıralama SUNUCUDA: layer (mandatory→seller→platform), sonra priority artan, sonra name. Arayüz yeniden sıralamaz — sayfalama ile bozulurdu.
- `save_pricing_rule` — Sahiplik: satıcı yalnız `seller_profile == kendi` yazabilir → aksi PERMISSION_DENIED.
- `save_pricing_rule` — `is_mandatory` yalnız platform → MANDATORY_NOT_ALLOWED.
- `save_pricing_rule` — En az bir kademe (VALIDATION_ERROR, details.fields.tiers); kademe aralıklarında çakışma → TIER_RANGE_OVERLAP, boşluk → TIER_RANGE_GAP.
- `reorder_pricing_rules` — Her ad var olmalı (NOT_FOUND) · her kural `layer` ile AYNI katmanda olmalı (VALIDATION_ERROR) · satıcı yalnız kendi kurallarını sıralar (PERMISSION_DENIED).
- `delete_pricing_rule` — Aktif sevkiyatlarda `applied_pricing_rule` olarak kullanılıyorsa SİLİNMEZ → RULE_IN_USE.
- `simulate_price` — `recommended` SUNUCUDAN gelir; arayüz 'en ucuzu' kendisi seçmez — kural satıcının varsayılan hesabını (Carrier Account.is_default) tercih eder, yoksa en düşük satışa düşer. İki yerde hesaplanırsa ikisi ayrışır.

---

## `api.v1.notifications` — Bildirim tercihleri ve alıcı bildirim akışı

**Sahip:** 12-BE · **FE kaynağı:** `12-FE-VERI-SOZLESMESI.md`

| Uç | Döndürür | Hata kodları |
|---|---|---|
| `list_notification_preferences()` | `notification_preference` listesi — `{items, total, page, page_size}` | `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `set_notification_preference(template, enabled)` | `notification_preference` kaydı | 🔸`MANDATORY_PREFERENCE` · `NOT_FOUND` · `PERMISSION_DENIED` · `VALIDATION_ERROR` |
| `list_notifications(page?, page_size?)` | `notification_log` listesi — `{items, total, page, page_size}` | `PERMISSION_DENIED` · `FEATURE_DISABLED` |
| `mark_notification_read(name)` | `notification_log` → `name`, `read_at` | `PERMISSION_DENIED` · `NOT_FOUND` |

**Parametreler:**

- `list_notifications` → `page` (int) — varsayılan 1
- `list_notifications` → `page_size` (int) — varsayılan 20

**Uygulama notları:**

- `list_notification_preferences` — Parametre almaz — kimin tercihleri olduğunu sunucu oturumdan bilir.
- `set_notification_preference` — Güncellenmiş satırın TAMAMI döner, yalnız `ok:true` değil — sunucunun düzelttiği bir değer sessizce kaybolmasın. Aynı değeri yeniden yazmak hata değil, idempotent.
- `list_notifications` — En yeni önce.
- `mark_notification_read` — Zaten okunmuşsa mevcut `read_at` döner, üzerine yazılmaz — idempotent. Uygulama sırasında EN SONA (§9): ekran bu uç olmadan da çalışır, yalnız her kayıt okunmamış görünür.

**Sunucuda tekrarlanması gereken kapılar:**

- `list_notification_preferences` — Çağıranın ROLÜNE AİT OLMAYAN satır DÖNMEZ (§6.1). Gösterim tercihi değil yetki kapısı: ölçüldüğünde ekran alıcıya satıcının ve operasyon ekibinin tercihlerini gösteriyordu.
- `set_notification_preference` — `is_mandatory=1` şablonda `enabled` YAZILAMAZ → MANDATORY_PREFERENCE. Veri kısıtı, arayüz nezaketi değil: FE anahtarı `disabled` çiziyor (S7-2) ama bu kolaylıktır, kapı değildir (§6.2).
- `list_notifications` — `status` = queued|failed olan kayıt ALICIYA DÖNMEZ — gönderilmemiş bildirimi 'geldi' diye göstermek yanlış bilgi olur. Süzgeç sunucuda.
- `list_notifications` — `recipient` alanı yanıtta dönmez: zaten çağıranın kendisi.
- `mark_notification_read` — Başkasının bildirimi işaretlenemez → PERMISSION_DENIED.

---

## 🔸 Tanımsız hata kodları

Ekranlar **24 koda** göre dallanıyor ama hiçbiri
`logistics/exceptions.py` ya da `logistics/api_utils.py` içinde tanımlı değil.
Ucu yazan kişi kodu da tanımlar; tanımlamazsa istemci `INTERNAL_ERROR` görür.

| Kod | Kaç uçta | Nerede |
|---|---:|---|
| `ACCEPTED_EXCEEDS_RECEIVED` | 1 | `returns.save_return_inspection` |
| `CARRIER_ERROR` | 1 | `packaging.generate_shipment_labels` |
| `CONFLICT` | 7 | `pickup.request_appointment`, `packaging.save_shipment_packages`, `packaging.complete_packing`, `packaging.save_pallet_plan`, `pod.record_proof_of_delivery`, `pod.amend_proof_of_delivery`, `pod.hand_over_shipment` |
| `DECISION_NOTE_REQUIRED` | 1 | `returns.decide_return_request` |
| `DELIVERY_CODE_EXPIRED` | 1 | `pickup.confirm_delivery` |
| `DELIVERY_CODE_NOT_VERIFIED` | 1 | `pod.hand_over_shipment` |
| `INVALID_STATUS` | 1 | `pod.record_proof_of_delivery` |
| `LABEL_STALE` | 1 | `packaging.reprint_shipment_labels` |
| `MANDATORY_NOT_ALLOWED` | 1 | `pricing.save_pricing_rule` |
| `MANDATORY_PREFERENCE` | 1 | `notifications.set_notification_preference` |
| `NOTHING_RETURNABLE` | 1 | `returns.create_return_request` |
| `PAYMENT_REQUIRED` | 1 | `pod.hand_over_shipment` |
| `POD_ALREADY_RECORDED` | 1 | `pod.record_proof_of_delivery` |
| `QTY_EXCEEDS_DELIVERED` | 1 | `returns.create_return_request` |
| `RETURN_ALREADY_DECIDED` | 1 | `returns.decide_return_request` |
| `RETURN_CLOSED` | 3 | `returns.decide_return_request`, `returns.save_return_inspection`, `returns.close_return_request` |
| `RETURN_NOT_CLOSABLE` | 1 | `returns.close_return_request` |
| `RETURN_WINDOW_CLOSED` | 1 | `returns.create_return_request` |
| `RULE_IN_USE` | 1 | `pricing.delete_pricing_rule` |
| `SHIPMENT_LOCKED` | 6 | `packaging.save_shipment_packages`, `packaging.complete_packing`, `packaging.mark_shipment_ready`, `packaging.generate_shipment_labels`, `packaging.void_shipment_label`, `packaging.save_pallet_plan` |
| `TIER_RANGE_GAP` | 1 | `pricing.save_pricing_rule` |
| `TIER_RANGE_OVERLAP` | 1 | `pricing.save_pricing_rule` |
| `VALIDATION_FAILED` | 5 | `packaging.save_shipment_packages`, `packaging.complete_packing`, `packaging.mark_shipment_ready`, `packaging.generate_shipment_labels`, `packaging.save_pallet_plan` |
| `ZONE_NOT_FOUND` | 1 | `pricing.simulate_price` |

> `VALIDATION_FAILED` (13-FE) ile `VALIDATION_ERROR` (diğerleri) **aynı şeyin
> iki adı**. Uçlar yazılırken tek ada indirilmeli — bugün ekranlar iki farklı
> koda göre dallanıyor.

