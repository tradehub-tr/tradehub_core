---
paths:
  - "**/*.py"
---

# Mevcut kod borçları + refactor hedefleri

Bu liste **mevcut kod taramasından** çıktı (2026-05-08). Yeni feature eklerken **yolda** iyileştirilmeli, izole refactor PR'ı için de aday.

## 1. Aşırı büyük dosyalar (>1000 satır)

| Dosya | Satır | Yorum |
|---|---:|---|
| `tradehub_core/seed_demo_data.py` | 3972 | DEV seed; modüllere bölünebilir (per-domain). |
| `tradehub_core/api/listing.py` | 3407 | **Kritik.** Search / detail / write / cache sorumluluğu karışmış. |
| `tradehub_core/tradehub_core/utils/erpnext_sync.py` | 2809 | Customer / Supplier / Sales Order sync ayrı dosya. |
| `tradehub_core/api/v1/identity.py` | 1786 | Login / refresh / profile / password ayrı. |
| `tradehub_core/api/cart.py` | 1387 | Cart CRUD vs. promo / pricing ayrı. |
| `tradehub_core/api/seller.py` | 1314 | Profile / KPI / approvals ayrı. |
| `tradehub_core/tasks.py` | 1224 | Hourly / daily / weekly ayrı modül. |
| `tradehub_core/permissions.py` | 1176 | Per-doctype dosya altına dağıtılabilir. |
| `tradehub_core/api/order.py` | 1072 | OK ama yaklaşıyor. |
| `tradehub_core/tradehub_core/api/kpi_dashboard.py` | 1018 | OK ama yaklaşıyor. |

**Strateji:** Dosyaya dokunduğunda fırsatçı temizlik yap, ama sırf split için mega-PR açma. İzole refactor PR'ı ayrı bir iş.

## 2. Sorgu modernizasyonu

- **0** `frappe.qb` kullanımı, **218** `frappe.db.sql`. Yeni kod qb ile başlasın.
- F-string SQL pattern'i (`recommendations/swap.py` shadow/archive tablo adı formatı) en az `frappe.db.escape` veya isim whitelist kontrolüyle sertleşmeli.

```python
# ❌ Mevcut pattern (swap.py)
shadow_table = f"tabListing_shadow_{seller_id}"
frappe.db.sql(f"SELECT * FROM `{shadow_table}` WHERE status = %s", ("Active",))

# ✅ Hedef (whitelist + escape)
ALLOWED_SHADOW_PREFIXES = {"tabListing_shadow_", "tabOrder_shadow_"}
assert any(shadow_table.startswith(p) for p in ALLOWED_SHADOW_PREFIXES), "Unsafe table name"
# Tablo adı sabit gibi davransa da explicit assert + escape şart.
```

## 3. Whitelist + auth audit

- **269 whitelist endpoint var.** `permissions.py` query_conditions sadece liste endpoint'lerini koruyor.
- *Single-doc fetch* endpoint'leri için `doc.check_permission` çağrılarının kapsamı doğrulanmalı:
  - `api/listing.py` — kritik (search + detail)
  - `api/seller.py` — kritik (seller profile)
  - `api/cart.py` — kritik (user-scoped cart)
- Audit deseni: her endpoint'in başında ya `doc.check_permission` ya `frappe.only_for` ya `tenant.validate_tenant`.

## 4. Hata yönetimi

- **182 `except Exception`** — büyük çoğunluğu en azından `frappe.log_error` + spesifik exception sınıfı'na evrilmeli.
- **69 `print()` çağrısı** (test dışı) — `frappe.logger()` ya da `frappe.log_error` ile değiştir.
- **3 bare `except:`** — `KeyboardInterrupt`/`SystemExit`'i yutar, temizlenmeli.

## 5. Belge / kod tutarsızlığı (TARİHSEL)

Bu CLAUDE.md eskiden **7 ayrı app** anlatıyordu (catalog, commerce, seller, logistics, marketing, compliance) — kod o yapıda **değil**. Belge 2026-05-08'de gerçek monolit'i yansıtacak şekilde yenilendi. Eski belgeye atıfta bulunan PR açıklamaları, issue'lar veya CHANGELOG kayıtları varsa onlar da güncellenebilir.

## 6. Refactor PR kuralları

- **Refactor commit'i ayrı:** `refactor(<area>): <neyi neye çevirdin>`
- **İki commit:** `refactor` önce, sonra `feat`
- **Kapsam dışına çıkma** — bir dosya refactor'unu mega-PR'a dönüştürme
- **Test ile gel** — refactor sonrası mevcut testler hala yeşil olmalı
- **`bench --site dev.localhost migrate` test'i** zorunlu
