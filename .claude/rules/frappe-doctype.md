---
paths:
  - "**/doctype/**/*.py"
  - "**/doctype/**/*.json"
  - "**/*.py"
---

# Frappe DocType tasarımı

## 1. DocType oluşturma

```
tradehub_core/tradehub_core/doctype/{snake_case_name}/
  ├── {name}.json        DocType schema (lowercase, snake_case)
  ├── {name}.py          class {PascalCase}(Document) controller
  ├── {name}.js          (opsiyonel) form script
  ├── test_{name}.py     (opsiyonel ama önerilir) — Frappe test runner
  └── __init__.py        Boş
```

## 2. DocType tasarım disiplini (DocType bloat'tan kaçın)

- **Tekrarlayan veri → Child Table** (`istable=1`, parent'ta `Table` field). Aynı Buyer için 5 adres → ayrı Address DocType + Link, **kopyalanmış field değil**.
- **Kontrollü vocabulary → Select** field (1-2 satırlı) ya da **Link** + ayrı DocType.
- **İlişkiler → Link**, asla string ile `name` kopyalama.
- **Ağaç yapısı → `is_tree=1`** (NSM `lft/rgt` kolonları otomatik). `_get_category_descendants` bu yapıyı `lft >= ? AND rgt <= ?` ile tek query'de sorguluyor — örnek model.
- **Dosya/medya → File** doctype + Link (raw path ile değil).
- **Free-text alanı analytics field'ı olarak kullanma** — index'lenemez, agg edilemez. Yapılandırılmış field çıkar.

## 3. Child Table kuralları

- `istable=1`, parent'ta `Table` field, `options=Child DocType Name`.
- `parent`, `parenttype`, `parentfield`, `idx` Frappe tarafından otomatik oluşur.
- Child kayıt için ayrı CRUD endpoint **yazma** — parent'ı save eden flow zaten child'ı yazar.

## 4. DocType isimlendirme

- **DocType:** `Title Case` (örn. "Buyer Profile").
- **Klasör/dosya:** snake_case (`buyer_profile/buyer_profile.py`).
- **Class:** PascalCase (`class BuyerProfile(Document)`).
- **Whitelist endpoint:** fiil ile başla (`get_listing_detail`, `add_to_cart`).
- **İç helper:** `_underscore_prefix`.
- **Sabitler:** `ALL_CAPS` (`STOREFRONT_VISIBLE_STATUSES`, `CACHE_TTL`).

## 5. Index'siz büyük tablo filtre yasak

Bir kolon üstünde sürekli filtre yapıyorsan (territory, seller, status) **index ekle**:

```python
frappe.db.add_index("Listing", ["seller", "status"])
```

Ya da DocType JSON'da `"search_index": 1`.

## 6. Schema değişikliği — migration patch zorunlu

- **Custom field SQL'le ekleme yasak** — her zaman patch + custom_field doctype.
- **Field DB'den el ile silme yasak** — `patches.txt` üzerinden idempotent migration.

```python
# tradehub_core/patches/v15_xx_yyy.py
import frappe

def execute():
    # idempotent — patch tekrar çalışırsa kırılmasın
    if not frappe.db.has_column("tabListing", "new_field"):
        return
    frappe.db.sql("UPDATE `tabListing` SET new_field = %s WHERE new_field IS NULL", (0,))
    frappe.db.commit()
```

Sırayı `patches.txt`'ye ekle: `tradehub_core.patches.v15_xx_yyy`.

## 7. DocType controller (Python class)

```python
import frappe
from frappe.model.document import Document

class BuyerProfile(Document):
    def validate(self):
        super().validate()      # ← ZORUNLU; mevcut doğrulama düşmesin
        # iş kuralları

    def before_save(self):
        super().before_save()
```

## 8. Reload-doc (custom field uyumu)

```bash
bench --site dev.localhost reload-doc tradehub_core doctype listing
```
