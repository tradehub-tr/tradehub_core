# Lojistik Modulu (tradehub_core.logistics)

## Genel Bakis

Istoc.com B2B marketplace lojistik alt-modulu. Sevkiyat yonetimi, kargo firma
entegrasyonlari, takip otomasyonu ve fiyatlandirma motorunu kapsar.

Bu modul `tradehub_core` monolitik app'in bir parcasidir ve bagimsiz bir Frappe
app'i olarak calistirilmaz.

Mimari kararlar, repo sınırları ve API sözleşmesi: **`tradehub_core/docs/LOGISTICS-ARCHITECTURE.md`**

## ⚠️ Mevcut olgunluk (2026-08-12)

Modül **kısmen çalışır durumda**. Aşağıdaki tablo neyin çalıştığını, neyin
sadece yer tuttuğunu gösterir — dosya varlığını "hazır" diye okuma.

| Bileşen | Durum |
|---|---|
| Katalog DocType'ları (12) + seed | ✅ Çalışıyor |
| Shipment DocType ailesi (Shipment + Item/Event/Leg/Package/Document/Address Snapshot) | ✅ Var |
| Logistics Settings singleton + feature flag okuyucu | ✅ Çalışıyor — `is_enabled()` `api_utils.logistics_endpoint` kapısından çağrılıyor |
| Rol / permission / tenant izolasyonu (`permissions.py`) | ✅ Çalışıyor |
| Desi / ücretlendirilebilir ağırlık (`services/desi.py`) | ✅ Çalışıyor |
| Durum makinesi (`constants` + `services/shipment_service.py`) | ✅ `transition_status` + `cancel_shipment` uygulanıyor (LOG-049/050) |
| Sevkiyat bölme (`services/split_engine.py`) | ✅ INV-1..5 veri katmanı uygulanıyor (LOG-045) |
| `hooks.py` doc_event handler'ları | ✅ 6'sı ana `hooks.py`'a **bağlı** (`snapshot_*`, `validate_*`, `on_shipment_*`); `update_order_fulfillment` içeriden çağrılıyor |
| Katalog + admin API'si (`api/v1/logistics*.py`) | ✅ Çalışıyor — `{ok,data}` zarfı, yetki kapıları, gizli alan sözleşmesi |
| Adapter ABC + registry + MockCarrierAdapter | 🔸 Çalışıyor ama boot'ta **hiçbir carrier register edilmiyor** (yalnız testlerde) |
| `services/`: `tracking_service`, `pricing_engine`, `rate_calculator`, `notifier` | 🔸 **Docstring'den ibaret** (7'şer satır) — gövde yok |
| `jobs/`: `tracking_poll`, `sla_monitor` | 🔸 Docstring'den ibaret **ve `scheduler_events`'e KAYITLI DEĞİL** — yazılsalar da çalışmazlar |
| `reports/` | 🔸 **Boş** (yalnız `__init__.py`) |
| Sevkiyat operasyon uçları (oluştur/iptal/böl/takip) | ❌ Yok — Faz F |

## Dizin Yapisi

```
logistics/
├── __init__.py              # Public API: is_enabled(), get_logistics_settings()
├── constants.py             # ShipmentStatus, ALLOWED_TRANSITIONS, feature flags
├── exceptions.py            # LogisticsError ve alt siniflar
├── hooks.py                 # doc_event handler'lari (state validate, snapshot, fulfillment)
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
│   ├── shipment_service.py  # Durum gecis motoru: transition_status + cancel_shipment (LOG-049/050)
│   ├── tracking_service.py  # Takip sorgu servisi (stub, TUR-112)
│   ├── split_engine.py      # Sevkiyat bolme motoru INV-1..5 (LOG-045)
│   ├── pricing_engine.py    # Kargo fiyatlandirma motoru (stub, TUR-121)
│   ├── rate_calculator.py   # Tarife hesaplayici (stub, TUR-121)
│   ├── desi.py              # Desi/hacimsel agirlik hesaplama
│   └── notifier.py          # Bildirim servisi (stub, TUR-113)
├── jobs/                    # STUB — scheduler_events'e KAYITLI DEGIL
│   ├── tracking_poll.py     #   (yazilsa da calismaz)
│   └── sla_monitor.py
├── reports/                 # BOS — yalniz __init__.py (TUR-102)
│   └── __init__.py
└── tests/
    ├── __init__.py
    ├── test_module_import.py         # Import smoke testi
    ├── test_constants.py             # Durum makinesi invariant testleri
    ├── test_state_machine.py         # is_transition_allowed saf kural testleri
    ├── test_desi.py                  # Desi hesaplama testleri
    ├── test_adapter_contract.py      # Adapter ABC sozlesme + registry testleri
    ├── test_logistics_permissions.py # Permission unit testleri (standalone mock)
    └── test_shipment_core.py         # Bench entegrasyon paketi (split/state/API, LOG-054)
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

> NOT: Adapter kaydi henuz kablolanmadi — registry bos baslar, MockCarrierAdapter
> dahil hicbir adapter otomatik register edilmez. Ilk gercek adapter TUR-107/109'da
> baglanacak.

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
> `list_registered_carriers()` boş döner. Bootstrap kaydı ilk gerçek adapter
> göreviyle (TUR-107/109) eklenecek.

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

In Transit       -> At Warehouse | Out for Delivery | Delivered | Failed
At Warehouse     -> In Transit   | Out for Delivery
Out for Delivery -> Delivered    | Failed | Returned
Failed           -> In Transit   | Returned

Cancelled: Out for Delivery haric tum terminal-olmayan durumlardan erisilir
(Draft, Pending, Ready for Pickup, Picked Up, In Transit, At Warehouse, Failed).

Terminal: Delivered, Returned, Cancelled — cikis gecisi YOKTUR
(Returned'dan Cancelled'a gecis de yoktur; kaynak: constants.ALLOWED_TRANSITIONS).
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
