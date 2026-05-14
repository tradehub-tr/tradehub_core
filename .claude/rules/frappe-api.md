---
paths:
  - "**/*.py"
---

# Frappe v15 Python API kuralları

> v14 doc'una **bakma** — v15 API'leri farklıdır.

## 1. Modern API'ler (v15)

- `frappe.qb` — Query Builder (PyPika tabanlı, parametreli, DB-agnostik)
- `frappe.get_docs` — parent + child tabloları tek seferde batch çek
- `frappe.get_list` — permission-aware liste (**kullanıcı verisi için tercih**)
- `frappe.client_cache` — request-scoped cache; redis'i kirletmez
- **Type annotation tabanlı parametre doğrulama** — whitelist endpoint'lerde `def fn(name: str, qty: int)` runtime'da type-check edilir

## 2. Eski/legacy API'ler (kullanma)

- `cur_frm`, `$c_obj()`, `get_query`, `add_fetch` (v14 alışkanlığı)
- `frappe.db.sql(f"... {var} ...")` — SQL injection açar
- `from erpnext.x.y import …` deep import — kırılgan, hook'lar ile ilerle

## 3. Python API — tercih sırası

| İhtiyaç | Önerilen | Kaçınılacak |
|---|---|---|
| Liste sorgu (yetki uygulansın) | `frappe.get_list("X", filters=..., fields=[...])` | `frappe.db.sql("SELECT ...")` |
| Liste sorgu (sistem işi, perm by-pass) | `frappe.get_all` (gerekçe yorumla) | Aynı |
| Tek field okuma | `frappe.db.get_value("X", name, "field")` | `get_doc` (overkill) |
| Çoklu field | `frappe.db.get_value("X", name, ["a","b"], as_dict=True)` | Birden fazla `get_value` |
| Doc CRUD | `frappe.get_doc(...)`, `doc.save()`, `doc.insert()`, `doc.delete()` | Doğrudan SQL UPDATE |
| Karmaşık JOIN/agg | **`frappe.qb`** (PyPika, parametreli) | `frappe.db.sql(f"... {var} ...")` |
| Async / uzun iş | `frappe.enqueue("path.fn", queue="default" / "long")` | İstek içinde 30 sn+ iş |
| Cache | `frappe.cache.get_value/set_value`, `frappe.client_cache` (request-scoped) | Module-level dict |
| Hata mesajı | `frappe.throw(_("Hata mesajı"), exc=SomeError)` | `raise Exception(...)` |
| i18n | `from frappe import _; _("...")` her kullanıcıya gidecek string için | Çıplak string |

## 4. `frappe.qb` mini örneği (raw SQL yerine)

```python
from frappe.query_builder import DocType
from frappe.query_builder.functions import Count

Listing = DocType("Listing")
Order   = DocType("Order")

q = (
    frappe.qb.from_(Listing)
        .left_join(Order).on(Order.listing == Listing.name)
        .select(Listing.name, Count(Order.name).as_("order_count"))
        .where(Listing.status == "Active")
        .groupby(Listing.name)
)
rows = q.run(as_dict=True)
```

Parametreler otomatik escape edilir. `frappe.db.sql` ile elle `%s` yapmak zorunda değilsin.

> **Durum:** `tradehub_core` repo'sunda şu an **0** `frappe.qb` kullanımı var ve **218** raw SQL var. Yeni kod qb ile başlasın; dokunduğun raw SQL'i qb'ye taşımayı düşün (kapsam kuralıyla — sırf bunun için mega-PR açma).

## 5. Whitelist endpoint iskeleti

```python
@frappe.whitelist()  # default: yalnızca giriş yapmış user
def update_listing_price(name: str, price: float) -> dict:
    # 1) Type — v15 type annotation runtime'da kontrol edilir; manuel isinstance gerekmez
    # 2) Yetki — get_doc default permission check etmez:
    doc = frappe.get_doc("Listing", name)
    doc.check_permission("write")            # ← her endpoint'te bilinçli karar
    # 3) İş kuralı
    doc.price = price
    doc.save()                                # save() permission'ı yine doğrular
    return {"ok": True, "name": doc.name}
```

`@frappe.whitelist(allow_guest=True)` **yalnızca** açıkça public olan endpoint'ler için (storefront listing arama, brand list). Buyer/seller verisine dokunan hiçbir endpoint guest olamaz.

## 6. `get_list` vs `get_all`

| Senaryo | API |
|---|---|
| Kullanıcı verisi okurken (storefront, buyer, seller) | **`frappe.get_list`** — `permission_query_conditions` devreye girer |
| Sistem işi, scheduler, sync (perm by-pass kasıtlı) | `frappe.get_all` (gerekçe yorumla) |

## 7. Client-side JS (Form scripts)

```javascript
frappe.ui.form.on('Listing', {
    refresh(frm) { /* … */ },
    seller(frm) {
        frm.set_query('category', () => ({
            filters: { is_active: 1, seller: frm.doc.seller }
        }));
    }
});
```

**v14 alışkanlıklarını kullanma:** `cur_frm`, `$c_obj()`, `add_fetch` artık önerilmiyor.
