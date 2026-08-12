# Lojistik Modulu (tradehub_core.logistics)

## Genel Bakis

Istoc.com B2B marketplace lojistik alt-modulu. Sevkiyat yonetimi, kargo firma
entegrasyonlari, takip otomasyonu ve fiyatlandirma motorunu kapsar.

Bu modul `tradehub_core` monolitik app'in bir parcasidir ve bagimsiz bir Frappe
app'i olarak calistirilmaz.

Mimari kararlar, repo sınırları ve API sözleşmesi: **`tradehub_core/docs/LOGISTICS-ARCHITECTURE.md`**

## ⚠️ Mevcut olgunluk (2026-08-12)

Bu modül **iskelet aşamasındadır**. Aşağıdaki tablo neyin çalıştığını, neyin
sadece yer tuttuğunu gösterir — dosya varlığını "hazır" diye okuma.

| Bileşen | Durum |
|---|---|
| Katalog DocType'ları (12) + seed | ✅ Çalışıyor |
| Logistics Settings singleton + feature flag okuyucu | ✅ Çalışıyor (ama `is_enabled()` **hiçbir yerden çağrılmıyor**) |
| Rol / permission / tenant izolasyonu (`permissions.py`) | ✅ Kod hazır — Carrier Account için `hooks.py`'a bağlı |
| Adapter ABC + registry + MockCarrierAdapter | ✅ Çalışıyor (ama boot'ta **hiçbir carrier register edilmiyor**) |
| Desi / ücretlendirilebilir ağırlık | ✅ Çalışıyor |
| Durum makinesi sabitleri | ✅ Tanımlı — **uygulayan kod yok** (Shipment DocType henüz yok) |
| `hooks.py` içindeki 7 doc_event handler | 🔸 **Hepsi `pass`** — ana `hooks.py`'a bağlı değil |
| `services/` (6 modül), `jobs/` (2 modül), `adapters/http_client.py` | 🔸 **Docstring + TODO** — gövde yok |
| `reports/` | 🔸 Boş |
| API endpoint'leri (8) | 🔸 7'si `throw("henüz aktif değil")` |
| Shipment DocType | ❌ Yok |

## Dizin Yapisi

```
logistics/
├── __init__.py              # Public API: is_enabled(), get_logistics_settings()
├── constants.py             # ShipmentStatus, ALLOWED_TRANSITIONS, feature flags
├── exceptions.py            # LogisticsError ve alt siniflar
├── hooks.py                 # 🔸 7 doc_event handler — HEPSİ `pass`, ana hooks.py'a bağlı değil
├── permissions.py           # Sevkiyat erisim kontrolleri
├── cache.py                 # Redis cache yardimcilari (tc:logistics: prefix)
├── seed.py                  # Lojistik katalog seed verileri (provider, paket tipi vb.)
├── README.md                # Bu dosya
├── adapters/
│   ├── __init__.py
│   ├── base.py              # BaseCarrierAdapter ABC + data contract dataclass'lari
│   ├── registry.py          # register_carrier / get_adapter / list_registered_carriers
│   └── carriers/
│       ├── __init__.py
│       └── mock_carrier.py  # Test/dev icin deterministik sahte adapter
├── services/
│   ├── __init__.py
│   ├── desi.py              # ✅ Desi/hacimsel ağırlık hesaplama
│   ├── shipment_service.py  # 🔸 STUB — Sevkiyat CRUD + state machine
│   ├── tracking_service.py  # 🔸 STUB — Takip sorgu servisi
│   ├── split_engine.py      # 🔸 STUB — Sevkiyat bölme motoru (INV-1..5)
│   ├── pricing_engine.py    # 🔸 STUB — Kargo fiyatlandırma motoru
│   ├── rate_calculator.py   # 🔸 STUB — Tarife hesaplayıcı
│   └── notifier.py          # 🔸 STUB — Bildirim servisi
├── jobs/
│   ├── tracking_poll.py     # 🔸 STUB — scheduler_events'e KAYITLI DEĞİL
│   └── sla_monitor.py       # 🔸 STUB — scheduler_events'e KAYITLI DEĞİL
├── reports/                 # 🔸 BOŞ
│   └── __init__.py
└── tests/
    ├── __init__.py
    ├── test_module_import.py      # Import smoke testi
    ├── test_constants.py          # Durum makinesi invariant testleri
    └── test_adapter_contract.py   # Adapter ABC sozlesme + registry testleri
```

## Feature Flags

Modul feature flag mekanizmasi ile kontrol edilir. Tum flag'ler varsayilan
olarak **kapali** gelir (`constants.py` icinde `LOGISTICS_FEATURE_FLAGS`).

| Flag | Aciklama |
|------|----------|
| `carrier_api_enabled` | Kargo API cagrilari |
| `auto_tracking_enabled` | Otomatik tracking poll |
| `split_shipment_enabled` | Sevkiyat bolme ozelligi |
| `multi_leg_enabled` | Cok bacakli sevkiyat |
| `cost_estimation_enabled` | Maliyet tahmini |
| `webhook_notifications_enabled` | Webhook bildirimleri |
| `return_flow_enabled` | Iade akisi |
| `seller_delivery_enabled` | Satici teslimat |
| `buyer_pickup_enabled` | Alici teslim alma |
| `warehouse_transfer_enabled` | Depo transferi |

### Kullanim Ornegi

```python
from tradehub_core.logistics import is_enabled

if not is_enabled("carrier_api_enabled"):
    frappe.throw(_("Kargo API entegrasyonu aktif degil."))
```

Kontrol sirasi:
1. `Logistics Settings` DocType'indaki `feature_flags` JSON alani
2. `site_config`'deki `tradehub_logistics_{flag}` key'i
3. `LOGISTICS_FEATURE_FLAGS` default dict'i

## Yeni Tasiyici Ekleme (Adapter Pattern)

1. `adapters/carriers/` altina yeni dosya olustur (orn. `yurtici.py`)
2. `BaseCarrierAdapter`'i extend et ve abstract metotlari implement et:
   - `authenticate()` -- kimlik dogrulama
   - `get_quote(request)` -- fiyat teklifi
   - `create_shipment(request)` -- gonderi olusturma
   - `track(tracking_number)` -- takip sorgusu
3. `register_carrier()` ile registry'ye kaydet:
   ```python
   from tradehub_core.logistics.adapters.registry import register_carrier
   from tradehub_core.logistics.adapters.carriers.yurtici import YurticiAdapter

   register_carrier("yk", YurticiAdapter)
   ```
4. `Carrier Account` DocType'ına hesap bilgilerini gir (satıcı bazlı; secret
   alanları `Password` fieldtype ile saklanır, `view.carrier_secret`
   capability'si olmayan kullanıcıya maskelenir)

> ⚠️ Şu an **hiçbir adapter boot sırasında register edilmiyor** —
> `register_carrier` yalnızca testlerden çağrılıyor, dolayısıyla production'da
> `list_registered_carriers()` boş döner. Bootstrap kaydı F bloğunda eklenecek.

### Adapter Data Contract'lari

- `QuoteRequest` / `QuoteResponse` -- fiyat teklifi
- `ShipmentRequest` / `ShipmentResponse` -- gonderi olusturma
- `TrackingResponse` / `TrackingEvent` -- takip
- `CancelResponse` -- iptal

Tum data contract'lar `adapters/base.py` icinde `@dataclass` olarak tanimlidir.

## Durum Makinesi

Sevkiyat durumlari `ShipmentStatus` sinifinda, gecis matrisi
`ALLOWED_TRANSITIONS` dict'inde tanimlidir. Terminal durumlar
(`Delivered`, `Returned`, `Cancelled`) cikis gecisine sahip degildir.

```
Draft -> Pending -> Ready for Pickup -> Picked Up -> In Transit
                                                        |
                                          +-------------+-------------+
                                          |             |             |
                                     At Warehouse  Out for Delivery  Failed
                                          |             |             |
                                          +------+------+       +----+----+
                                                 |               |        |
                                             Delivered      In Transit  Returned
                                                                         |
                                                                      Cancelled
```

## Naming Conventions

- Shipment: `SHP-2026-00001` (SHIPMENT_NAMING_SERIES)
- Git branch: `logistics/feature/TUR-XXX-kisa-aciklama`
- Migration patch: `v15_logistics_NNN_aciklama.py`
- Cache key prefix: `tc:logistics:`

## Test Calistirma

LOCAL dev'de bench komutları container içinde çalışır (kök `CLAUDE.md` §4.4):

```bash
# Test modülü bazında (paket adı değil, MODÜL adı verilmeli)
docker exec istoccom-backend-1 bash -c "cd /home/frappe/workspace/frappe-bench && \
  bench --site dev.localhost run-tests --module tradehub_core.logistics.tests.test_constants"

# Mevcut test modülleri
#   test_module_import          — import smoke
#   test_constants              — durum makinesi invariantları
#   test_adapter_contract       — adapter ABC sözleşmesi + registry
#   test_desi                   — desi / ücretlendirilebilir ağırlık
#   test_logistics_permissions  — rol/yetki + tenant izolasyonu
#   test_logistics_roles        — Role Profile + capability grant bütünlüğü
```

## Ilgili Gorevler (Linear)

**Doğrulanmış** (commit geçmişinden):

| Görev | Konu | Durum |
|-------|------|-------|
| TUR-102 | Lojistik mimari temeli — modül iskeleti, adapter pattern, feature flag, durum makinesi sabitleri | Kısmi |
| TUR-103 | Rol ve yetki modeli — 3 rol, permission query, tenant izolasyonu, alan maskeleme, audit | Kısmi |
| TUR-104 | Ana lojistik katalogları — 12 DocType + 6 seed patch | Kısmi |

> ⚠️ **TUR-105 ve sonrası için bu dosyada eşleşme TUTULMUYOR.** Önceki sürümde
> burada TUR-103'ü "Shipment DocType", TUR-104'ü "kataloglar" diye gösteren bir
> tablo vardı; **yanlıştı**. Güncel görev listesi için Linear otoritedir —
> tahmini eşleşme yazma.

Patch adlandırması ayrı bir seri kullanıyor (`v15_log0NN_*`), Linear ID'siyle
birebir örtüşmez; ikisini karıştırma.
