# Lojistik Modulu (tradehub_core.logistics)

## Genel Bakis

Istoc.com B2B marketplace lojistik alt-modulu. Sevkiyat yonetimi, kargo firma
entegrasyonlari, takip otomasyonu ve fiyatlandirma motorunu kapsar.

Bu modul `tradehub_core` monolitik app'in bir parcasidir ve bagimsiz bir Frappe
app'i olarak calistirilmaz.

## Dizin Yapisi

```
logistics/
├── __init__.py              # Public API: is_enabled(), get_logistics_settings()
├── constants.py             # ShipmentStatus, ALLOWED_TRANSITIONS, feature flags
├── exceptions.py            # LogisticsError ve alt siniflar
├── hooks.py                 # doc_event handler stub'lari (validate, snapshot, vb.)
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
│   ├── shipment_service.py  # Sevkiyat CRUD + state machine (stub, TUR-105)
│   ├── tracking_service.py  # Takip sorgu servisi
│   ├── split_engine.py      # Sevkiyat bolme motoru (INV-1..5)
│   ├── pricing_engine.py    # Kargo fiyatlandirma motoru
│   ├── rate_calculator.py   # Tarife hesaplayici
│   ├── desi.py              # Desi/hacimsel agirlik hesaplama
│   └── notifier.py          # Bildirim servisi
├── jobs/                    # Arka plan islemleri (tracking poll, vb.)
├── reports/                 # Lojistik raporlari (TUR-102)
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
4. `Carrier Credential` DocType'ina hesap bilgilerini gir (TUR-106)

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

```bash
# Tum lojistik testleri
cd /path/to/frappe-bench
bench --site dev.localhost run-tests --module tradehub_core.logistics.tests

# Belirli test dosyasi
bench --site dev.localhost run-tests --module tradehub_core.logistics.tests.test_constants
```

## Ilgili Gorevler (Linear)

| Gorev | Konu |
|-------|------|
| TUR-102 | Lojistik modul iskelet ve adapter pattern |
| TUR-103 | Shipment DocType + state machine |
| TUR-104 | Ana lojistik kataloglari (provider, paket tipi, arac) |
| TUR-105 | Shipment CRUD + state transitions |
| TUR-106 | Carrier Credential DocType |
| TUR-107 | Yurtici Kargo adapter entegrasyonu |
| TUR-108 | Aras Kargo adapter entegrasyonu |
| TUR-109 ~ TUR-121 | Diger lojistik gorevleri |
