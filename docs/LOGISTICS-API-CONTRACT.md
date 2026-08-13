# Lojistik API Sözleşmesi — v1

> **Sürüm:** `contract_version = 1.0.0` · **Dondurulma:** 2026-08-12 (Faz B)
> **Makine-okunur karşılığı:** `docs/logistics-api.schema.json` (üretilmiş)
> **Tipler:** `tradehubfront/src/types/logistics.d.ts` (üretilmiş)
> **Mock veri:** `docs/generated/fixtures/*.json` (üretilmiş)

Bu belge **frontend'in kodlayacağı tek gerçektir.** Faz D'de Storybook ekranları,
Faz E'de panel entegrasyonu ve Faz F'de backend implementasyonu aynı bu belgeye
bakar.

---

## 1. Sözleşme nasıl korunur

Sözleşme üç yerde yaşamaz — **bir yerde** yaşar ve diğerleri ondan üretilir:

```
Python kaynak (OTORİTE)
  logistics/constants.py          enum'lar, feature flag'ler
  logistics/exceptions.py         hata kodları + HTTP durumları
  api/v1/logistics_catalog.py     CATALOGS sözlüğü = katalog sözleşmesi
  api/v1/logistics_admin.py       hesap / ayar / yetki sözleşmesi
  doctype/**/*.json               alan TİPLERİ
        │  python3 scripts/gen_logistics_types.py --sync
        ▼
  docs/logistics-api.schema.json          ← bu belgenin makine karşılığı
  docs/generated/logistics.d.ts           ← storefront tipleri
  docs/generated/fixtures/*.json          ← Storybook mock verisi
  tradehubfront/src/types/logistics.d.ts  ← senkron kopya
```

**Kural:** üretilmiş dosyaları elle düzenleme. CI `--check` ile bayat kopyayı
yakalar. Sözleşmeyi değiştirmek = Python kaynağını değiştirip yeniden üretmek.

---

## 2. Yanıt zarfı

Lojistik uçlarının **tamamı** aynı iki şekilden birini döndürür.

```jsonc
// Başarı
{ "ok": true, "data": { /* uca özgü yük */ } }

// Hata
{ "ok": false, "error": { "code": "SHIPMENT_STATE_INVALID",
                          "message": "Geçersiz durum geçişi",
                          "details": { /* opsiyonel */ } } }
```

| Alan | Sözleşme |
|---|---|
| `ok` | Dallanma noktası. `true` ise `data`, `false` ise `error` vardır |
| `error.code` | **Kararlı** anahtar. İstemci buna göre dallanır |
| `error.message` | i18n'li, kullanıcıya gösterilir. **Dallanma için kullanılmaz** |
| `error.details` | Yalnız gerektiğinde bulunur; varlığı kontrol edilmeli |

HTTP durumu yanıtla birlikte gelir (`error.code` ile eşleşir, tablo §4).

> **Neden ayrı bir zarf:** Repo'da üç rakip konvansiyon var (`success` 120 yer,
> `ok` 49, `data` 23) ve hiçbiri hata kodu taşımıyor. Mevcut uçlar
> DEĞİŞTİRİLMEDİ; bu zarf yalnız lojistik yüzeyi için geçerli.

---

## 3. Uç kataloğu

Tümü `POST|GET /api/method/tradehub_core.api.v1.<modül>.<fonksiyon>` biçiminde çağrılır.

### 3.1 Public — `api.v1.logistics` (misafir erişimine açık)

| Uç | Bayrak | Not |
|---|---|---|
| `get_available_shipping_methods(listing_id?, lang)` | — | İlan verilirse **yayında olmalı**; taslak/reddedilmiş ilan `NOT_FOUND` döner |
| `estimate_shipping_cost(origin?, destination?, weight_kg?, listing_id?)` | `cost_estimation_enabled` | 🔸 Faz F'te uygulanacak |
| `track_shipment_public(tracking_number)` | `auto_tracking_enabled` | 🔸 Faz F'te uygulanacak |

### 3.2 Katalog yönetimi — `api.v1.logistics_catalog` (giriş zorunlu)

| Uç | Döndürdüğü |
|---|---|
| `list_catalog_keys()` | Yönetilebilir katalogların listesi + arama/filtre yetenekleri |
| `list_catalog(catalog, page, page_size, search?, is_active?, filters?, order_by?)` | `{items, total, page, page_size}` |
| `get_catalog_item(catalog, name)` | Tam kayıt (child tablolar dahil) |
| `create_catalog_item(catalog, values)` | `{name}` |
| `update_catalog_item(catalog, name, values)` | `{name}` |
| `set_catalog_item_active(catalog, name, is_active)` | `{name, is_active}` |

**`catalog` değerleri (10):** `shipping_channel` · `shipping_method` ·
`logistics_provider` · `carrier_service` · `carrier_branch` ·
`service_coverage_area` · `carrier_status_mapping` · `package_type` ·
`vehicle_type` · `shipment_exception_code`

Kurallar:
- `catalog` bir **allowlist**'tir; listede olmayan değer `VALIDATION_ERROR` döner
- `filters` yalnız katalogun ilan ettiği alanları kabul eder; başka alan **sessizce yok sayılmaz**, hata verir
- `values` yalnız sözleşmedeki alanları kabul eder — aynı kural
- Sayfa boyutu üst sınırı **200**, varsayılan **50**
- **Silme yok.** Kayıtlar başka dokümanlardan referans alınabildiği için `set_catalog_item_active(..., 0)` kullanılır

> **Neden DocType şeması doğrudan açılmıyor:** Alan listeleri `CATALOGS` içinde
> elle yazılı. Bir DocType'a alan eklemek API'yi otomatik genişletmez —
> sözleşme bilinçli bir karar olarak kalır. (Faz A.6'da dört DocType değişti;
> şema doğrudan açık olsaydı frontend habersiz kırılırdı.)

### 3.3 Yönetim — `api.v1.logistics_admin` (giriş zorunlu)

| Uç | Not |
|---|---|
| `list_carrier_accounts(carrier?, is_active?, page, page_size)` | Tenant izolasyonu uygulanır |
| `get_carrier_account(name)` | Gizli alan **değerleri dönmez** |
| `save_carrier_account(name?, values)` | `name` yoksa oluşturur |
| `reveal_carrier_secret(name, secret_field)` | `view.carrier_secret` + denetim kaydı |
| `get_logistics_settings()` | Ayarlar + **bilinen tüm** feature flag'ler |
| `update_logistics_settings(values)` | Bayraklar hariç ayar alanları |
| `set_feature_flag(flag, enabled)` | Tek anahtar |
| `get_logistics_permissions()` | Panelin aksiyon görünürlüğü |

---

## 4. Hata kodları

| Kod | HTTP | Ne zaman |
|---|---:|---|
| `VALIDATION_ERROR` | 417 | Genel doğrulama; bilinmeyen katalog/alan |
| `PERMISSION_DENIED` | 403 | DocPerm veya tenant reddi |
| `CAPABILITY_REQUIRED` | 403 | İnce taneli yetki eksik |
| `FEATURE_DISABLED` | 403 | Feature flag kapalı — **yetki sorunu DEĞİL** |
| `NOT_FOUND` | 404 | Kayıt yok ya da görünür değil |
| `DUPLICATE_ENTRY` | 409 | Benzersizlik ihlali |
| `LOGISTICS_ERROR` | 417 | Lojistik genel hatası |
| `SHIPMENT_STATE_INVALID` | 409 | İzin verilmeyen durum geçişi |
| `IDEMPOTENCY_CONFLICT` | 409 | Aynı anahtar, farklı istek |
| `SPLIT_INVARIANT_VIOLATION` | 422 | INV-1..5 ihlali |
| `TRACKING_NOT_FOUND` | 404 | Takip kaydı yok |
| `CARRIER_NOT_FOUND` | 404 | Registry'de olmayan taşıyıcı |
| `CARRIER_CAPABILITY_UNSUPPORTED` | 400 | Taşıyıcı bu işlemi desteklemiyor |
| `CARRIER_API_ERROR` | 502 | Taşıyıcı API'si hata döndü |
| `CARRIER_TIMEOUT` | 504 | Taşıyıcı API'si zaman aşımı |
| `INTERNAL_ERROR` | 500 | Beklenmeyen hata — **ayrıntı istemciye verilmez**, log'a yazılır |

> `FEATURE_DISABLED` ile `PERMISSION_DENIED` **ayrı ekran** göstermelidir:
> "bu özellik henüz açık değil" ≠ "yetkiniz yok".

---

## 5. Gizli bilgi sınırı

`api_key` · `api_secret` · `webhook_secret` · `access_token`

- Liste ve detay yanıtlarında **hiçbir koşulda dönmez** — yalnız `has_api_key: true` gibi bayraklar
- Değeri okumak: `reveal_carrier_secret(name, secret_field)` — tek kayıt, tek alan, toplu okuma yolu yok
- Gereken yetki: **`view.carrier_secret`**
- Her okuma `Authorization Decision Log`'a **HIGH severity** ile yazılır
- Yazma serbesttir; **boş string gönderilen gizli alan "dokunma" demektir** (panel formu her kaydettiğinde secret'ı silmesin)

> **Neden maskeleme değil:** Maskelenmiş değer de yanıt gövdesinde, tarayıcı
> geçmişinde ve ara sunucu loglarında dolaşır. Hiç göndermemek tek güvenli yol.

---

## 6. Yetki modeli

**Yetki kararı yalnız backend'de verilir.** `get_logistics_permissions()` bir
**kullanıcı deneyimi kolaylığıdır**, güvenlik sınırı değildir; istemcinin bu
yanıtı değiştirmesi hiçbir kapıyı açmaz. Backend her istekte kararı yeniden verir.

| Katman | Nerede |
|---|---|
| Rol (DocPerm) | `frappe.get_list` / `doc.save()` otomatik uygular |
| Tenant izolasyonu | `permission_query_conditions` + `has_permission` |
| Capability | Dekoratör (`@logistics_endpoint(capability=...)`) |
| Feature flag | Dekoratör (`@logistics_endpoint(flag=...)`) |

Kontrol sırası: **flag → rol → capability → iş mantığı.** Kapalı bir özellik
"yetkiniz yok" dememelidir.

**Katalog yönetimi feature flag'e bağlı DEĞİLDİR** — yönetici, modül müşteriye
açılmadan önce katalogları yapılandırabilmelidir.

---

## 7. Feature flag'ler

`logistics_enabled` **ana anahtardır**: kapalıyken diğer 12 bayrağın değeri
okunmaz, hepsi kapalı sayılır. Kademeli açılış (Beta → RC → PROD) tek anahtarla
geri alınabilsin diye.

Bayraklar: `carrier_api_enabled` · `multi_carrier_enabled` ·
`shipping_zone_pricing_enabled` · `auto_tracking_enabled` ·
`split_shipment_enabled` · `multi_leg_enabled` · `cost_estimation_enabled` ·
`webhook_notifications_enabled` · `return_flow_enabled` ·
`seller_delivery_enabled` · `buyer_pickup_enabled` · `warehouse_transfer_enabled`

Okuma sırası: `Logistics Settings` → `site_config` → varsayılan (**hepsi kapalı**).

---

## 8. Idempotency — 🔸 REZERVE, Faz F'te uygulanacak

Kargo API'leri **gerçek gönderi ve ücret üretir**; ağ hatasında yapılan retry
çift gönderi yaratır. Gönderi oluşturan/iptal eden uçlar idempotent olmalıdır.

| Konu | Sözleşme |
|---|---|
| Header | `Idempotency-Key` — istek başına benzersiz |
| Aynı anahtar + aynı gövde | **İlk yanıt** tekrar döner, yeni işlem yapılmaz |
| Aynı anahtar + farklı gövde | `IDEMPOTENCY_CONFLICT` (409) |
| TTL | 24 saat |

> **Durum:** Bu bölüm sözleşme olarak **dondurulmuştur**, kodu Faz F'te gelecek.
> Bilinçli olarak iskelet kod yazılmadı — çalışmayan yüzey, çalışıyor sanılan
> yüzeyden daha tehlikelidir (kök `clean-code.md` §6).

---

## 9. Sayfalama ve arama

```jsonc
{ "items": [...], "total": 42, "page": 1, "page_size": 50 }
```

- `page` 1'den başlar · `page_size` varsayılan 50, üst sınır 200
- `search` katalogun ilan ettiği alanlarda `LIKE %term%` ile arar
- `order_by` verilmezse katalogun varsayılan sıralaması kullanılır

---

## 10. Sürüm politikası

`contract_version` **semver**'dir.

| Değişiklik | Sürüm |
|---|---|
| Yeni uç, yeni opsiyonel alan, yeni hata kodu | MINOR |
| Alan adı değişikliği, alan kaldırma, **hata kodu değiştirme**, zorunluluk ekleme | **MAJOR** |
| Açıklama/örnek düzeltmesi | PATCH |

**Kırıcı değişiklik `v2` namespace'i açar; `v1` bozulmaz.**

Hata kodu değerini değiştirmek kırıcıdır — istemci ona göre dallanıyor. Yeni
durum için **yeni kod** ekle.

---

## 11. Frontend için hızlı başlangıç

```ts
import type {
  LogisticsResponse, CatalogPage, LogisticsProviderListItem,
} from "@/types/logistics";

const res: LogisticsResponse<CatalogPage<LogisticsProviderListItem>> =
  await request("tradehub_core.api.v1.logistics_catalog.list_catalog", {
    catalog: "logistics_provider", page: 1, page_size: 50,
  });

if (!res.ok) {
  if (res.error.code === "FEATURE_DISABLED") return showModuleClosedScreen();
  if (res.error.code === "PERMISSION_DENIED") return showNoAccessScreen();
  return showError(res.error.message);
}
renderTable(res.data.items);
```

⚠️ **`is_active` bir `number`'dır (0/1), boolean değil.** Frappe Check alanı
integer döndürür; `=== true` sessizce hep `false` verir. Üretilen tipler bunu
doğru yazıyor.

Mock ile çalışmak (Faz C/D): `docs/generated/fixtures/<catalog>.json` — her
katalogda `default`, `empty`, `error` senaryoları hazır.

---

## 12. Bu sözleşmenin kapsamadıkları

Aşağıdakiler **henüz sözleşme değildir**; Faz F'te eklenecek ve o zaman
`contract_version` MINOR artacaktır:

- Shipment CRUD, durum geçişleri, bölme, çok bacaklı sevkiyat
- Taşıyıcı entegrasyonu (teklif, gönderi oluşturma, etiket, takip)
- Maliyet/fiyatlandırma hesapları
- İade akışı, SLA/istisna yönetimi
- Webhook alıcıları
