---
paths:
  - "**/*.py"
---

# Python clean code — TradeHub standardı

Genel clean code prensipleri için kök `.claude/rules/clean-code.md`. Bu dosya Python-spesifik kurallar.

## 1. Stil

- **Tab indent** zorunlu (Frappe konvansiyonu, boşluk indent ruff'tan geçmez).
- **Line length 110**, ama `E501` ignored — DocType docstring'leri uzun olabilir.
- **Double quote** (`pyproject.toml [tool.ruff.format]`).
- Modüller PEP 8 + Ruff'un seçtiği subset (`E, F, W, I, B, UP`).

## 2. Import sırası (Ruff isort otomatik)

```python
# 1. stdlib
import os
import json
from datetime import datetime

# 2. 3rd party
import requests

# 3. frappe
import frappe
from frappe import _
from frappe.model.document import Document

# 4. tradehub_core (lokal)
from tradehub_core.utils.tenant import validate_tenant
```

## 3. Type hints — yeni kod için zorunlu

Frappe v15 type annotation'ı runtime parametre doğrulama için kullanır:

```python
@frappe.whitelist()
def update_listing(name: str, price: float, status: str = "Active") -> dict:
    ...
```

Mevcut dosyaya dokunurken **sadece dokunduğun fonksiyona** ekle (refactor'u patlatma).

## 4. Fonksiyon ve modül boyutu

- **Fonksiyon ≤ ~30 satır.** Birden fazla "paragraf" varsa muhtemelen iki şey yapıyordur — ayır.
- **Tek sorumluluk:** "kullanıcıyı doğrula **ve** indirim hesapla" iki fonksiyon.
- **Dosya ≤ ~500 satır hedef.** Üstüne çıkıyorsa modüle böl.

## 5. Yorum

- **Niye** yaz, **ne** değil. `# i++` yerine `# 0-tabanlı index'i dashboard kuralına göre 1-tabanlıya çeviriyoruz`.
- Bir tarihsel hata ya da iş kuralı varsa yorumla — `hooks.py`'deki Order `before_save` yorumu (counter 2x/3x şişmesi) iyi örnek.
- TODO/FIXME bırakırken ya issue link ekle ya 1 hafta içinde çöz; rotting TODO'lar borç.

## 6. Hata yönetimi

```python
# ❌
try:
    doc.save()
except Exception:
    pass

# ✅
try:
    doc.save()
except frappe.ValidationError as e:
    frappe.log_error(f"Listing save failed: {e}", "Listing.save")
    raise
```

- Bare `except:` ASLA — `KeyboardInterrupt`/`SystemExit`'i de yutar.
- `frappe.throw(_("Türkçe hata"), exc=ValidationError)` — `raise Exception(...)` değil.

## 7. Test

- Yeni DocType / API endpoint için **en az 1 happy path + 1 error path** test'i.
- `bench --site dev.localhost run-tests --doctype "Listing"` ile çalıştır.
- Test kütüphanesi: Frappe'nin built-in test runner'ı (`unittest` tabanlı). **Yeni dependency ekleme.**

## 8. Cache + invalidation

- **TTL sınırla** — `CACHE_TTL = 30` gibi sabit. Sınırsız TTL = dirty data.
- **Yazma anında invalidate et** — `invalidate_listing_cache` `Listing` doc_event'inde `on_update/after_insert/on_trash` üçünden de çağrılır (örnek model).
- **`frappe.client_cache` request-scope; `frappe.cache` cross-request.** İhtiyaca göre seç.

## 9. Auto-Claude task yazım kuralları

### Atomik task boyutu

- 1-3 dosya → simple
- 4-8 dosya → standard
- 9+ dosya → **BÖL** (ya feature'ı parçala ya refactor'ı izole PR yap)

### Definition of Done

- ✅ Dosya mevcut + grep pattern doğrulanmış
- ✅ `python -m py_compile <file>` veya import smoke testi
- ✅ `ruff check` temiz
- ✅ `bench --site dev.localhost migrate` patlamıyor
- ✅ İlgili DocType için `bench run-tests --doctype "X"` yeşil
- ✅ Yeni whitelist endpoint için güvenlik kontrol listesi geçildi (`checklists.md`)
- ❌ "Form'da dropdown çalışıyor görünüyor" — manuel UI doğrulaması site/test ortamı gerektirir, otomasyon DoD'i değil

### Yeni feature açarken

1. Belgede gerçeklikten kopuk bir şey gördüysen **önce belgeyi düzelt**.
2. Yeni DocType: schema → controller → permission → hooks → patch → test.
3. Yeni endpoint: type hints → permission check → i18n hata mesajı → cache invalidation → test.
4. Schema değişiyorsa: migration patch (idempotent) + `patches.txt` kaydı.
