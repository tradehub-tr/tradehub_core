# TradeHub Core — Proje Rehberi (CLAUDE.md)

Bu dosya Auto-Claude agent'larının her oturum başında okuduğu tek kaynak belgedir.
Projenin gerçek yapısını, kod yazım kurallarını, anti-pattern'leri ve Frappe v15 best
practice referanslarını içerir. Bu belge gerçek dizin ağacını, bağımlılıkları ve
ölçülmüş kod borçlarını yansıtır — kod ile çelişirse bu belge değil, kod doğrudur:
gördüğünü kayıt et, çelişkiyi flag et, gerekirse bu belgeyi güncelle.

> Son güncelleme: 2026-05-08 — kod tarama + Frappe v15 dokümantasyonu kıyaslamasıyla.

---

## 1. PROJE KİMLİĞİ

| Alan | Değer |
|------|-------|
| Domain | B2B Marketplace (İstoç Ticaret Merkezi tabanlı) |
| Tip | Frappe custom app — backend + DocType + REST API + DocType formları |
| Framework | Frappe v15 (`>=15.0.0,<16.0.0`) + ERPNext v15 |
| Python | `requires-python = ">=3.10"` (production runtime: 3.12.3) |
| ORM/DB | MariaDB 10.6+ (Frappe ORM + frappe.qb / frappe.db) |
| Cache/Queue | Redis (cache + queue + socketio) |
| Lint | Ruff (line-length 110, target-version py310, tab indent) |
| Build | flit_core (pyproject.toml dinamik versiyon) |
| Tek runtime bağımlılığı | `frappe` (requirements.txt) |
| Mimari yaklaşım | **Tek monolitik app** — tüm modüller `tradehub_core/` altında |

> ⚠️ **Geçmiş tasarımla farkı:** Daha eski belgelerde 7 ayrı app (catalog, commerce,
> seller, logistics, marketing, compliance) bahsi geçiyordu. **Bugün** kod tek
> `tradehub_core` app'i içinde monolitik. Yeni feature'lar bu mevcut yapıya eklenir.
> İleride app'lere bölme kararı alınırsa Bölüm 11 (Refactor Hedefleri) güncellenir.

---

## 2. DİZİN VE MODÜL HARİTASI

```
tradehub_core/                          (repo kökü)
├── pyproject.toml                      (flit_core, ruff config)
├── setup.py                            (legacy + flit ikili)
├── requirements.txt                    (sadece "frappe")
├── CHANGELOG.md
└── tradehub_core/                      (Python paketi — Frappe app modülü)
    ├── hooks.py                        (doc_events, scheduler_events, perms)
    ├── modules.txt                     ("Tradehub Core")
    ├── patches.txt                     (migration patch sırası)
    ├── permissions.py                  (1176 satır — query_conditions + has_permission)
    ├── seed_demo_data.py               (3972 satır — DEV ortamı seed)
    ├── tasks.py                        (1224 satır — scheduler entry point'leri)
    ├── api/                            (REST/whitelist endpoints)
    │   ├── listing.py    (3407 satır)  ← kritik refactor adayı
    │   ├── cart.py       (1387 satır)
    │   ├── seller.py     (1314 satır)
    │   ├── order.py      (1072 satır)
    │   ├── payment.py    (830 satır)
    │   ├── public.py     (805 satır)
    │   ├── rfq.py, category.py, tailored.py, ...
    │   └── v1/
    │       ├── identity.py (1786 satır)
    │       └── crm_overrides.py
    ├── eca/                            (Event–Condition–Action rule engine)
    │   └── dispatcher.py
    ├── recommendations/                (Related products, kategori embeddings)
    │   ├── engine.py, tasks.py, swap.py, cleanup.py
    ├── services/                       (TCMB döviz, dış servis adaptörleri)
    ├── setup/                          (after_install / after_migrate)
    ├── tradehub_core/                  ← Frappe konvansiyonu: modül namespace
    │   ├── api/                        (kpi_dashboard, dashboard_engine)
    │   ├── doctype/                    (75+ doctype dizini)
    │   ├── utils/                      (auth_guards, tenant, security, …)
    │   ├── scoring/                    (engine.py)
    │   ├── workspace/, fixtures/, config/
    ├── utils/                          (kök seviye yardımcılar)
    └── webhooks/                       (ERPNext + dış sistem köprüleri)
```

**DocType sayısı (yaklaşık):** 75+ aktif DocType (`tradehub_core/doctype/` altında).
**Whitelist endpoint sayısı:** ~269 (`@frappe.whitelist()` taraması).
**Toplam Python satırı:** ~322 dosya, en büyük 10 dosya ~16k satır.

---

## 3. STACK VE SÜRÜM REHBERİ

### 3.1 Python
- **Minimum:** 3.10 (`pyproject.toml` `requires-python`)
- **Production:** 3.12.3 (Frappe v15 önerilen sürüm)
- **Yeni kod:** 3.10+ özellikleri (PEP 604 union types `X | Y`, structural pattern
  matching, `tomllib`) serbest kullanılabilir. 3.11+ özelliği (Self type, exception
  groups) kullanmadan önce ortak runtime'ı doğrula.

### 3.2 Frappe
- **Sürüm:** `>=15.0.0,<16.0.0`. v14 doc'una **bakma** — v15 API'leri farklıdır.
- **Modern API'ler (v15):**
  - `frappe.qb` (Query Builder, PyPika tabanlı, parametreli & DB-agnostik)
  - `frappe.get_docs` (parent + child tabloları tek seferde batch çek)
  - `frappe.get_list` (permission-aware liste)
  - `frappe.client_cache` (request-scoped cache; redis'i kirletmez)
  - Type annotation tabanlı parametre tipi doğrulaması — whitelist endpoint'lerde
    `def fn(name: str, qty: int)` runtime'da type-check edilir.
- **Eski/legacy API'ler (kullanmayın):**
  - `cur_frm`, `$c_obj()`, `get_query`, `add_fetch` (ERPNext coding standards)
  - `frappe.db.sql(f"... {var} ...")` — SQL injection açar (Bölüm 8.2)

### 3.3 Lint / Format
- **Ruff** aktif: `select = E, F, W, I, B, UP`. `pyproject.toml`'a göre çalışır.
- **Tab indent** zorunlu (Frappe konvansiyonu). Boşluk indent ruff'tan geçmez.
- **Line length 110**, ama `E501` ignored — DocType docstring'leri uzun olabilir.

---

## 4. HOOKS.PY — MEVCUT KAYITLAR

`tradehub_core/hooks.py` **dokunulurken silmeden ekle** kuralı geçerli. Aktif hook'lar:

```python
required_apps = ["frappe", "erpnext"]
app_include_js = "seller_redirect.js"

scheduler_events = {
    "hourly":      [refresh_copurchase_lift, sla_breach_check],
    "daily":       [tcmb_fx, cleanup_expired_tokens, notification_cleanup,
                    cleanup_old_search_history, cleanup_old_user_product_views,
                    rebuild_price_tiers, autoflag_accessory_categories],
    "weekly_long": [build_category_embeddings, rebuild_related_matrix],
}

doc_events = {
    "File":                   {before_insert: reject_unsafe_files},   # XSS guard
    "Listing":                {on_update/after_insert/on_trash → cache invalidation +
                               recommendations engine},
    "Product Category":       {on_trash: cascading cleanup},
    "Order":                  {before_save: bump_listing_order_counts,
                               on_update: invalidate_tailored_user_cache},
    "Seller Review":          {after_insert/on_update/on_trash: rating proxy recompute},
    "Admin Seller Profile":   {after_insert/on_update: helpdesk + role sync},
    "CRM Lead/Deal/Org/Task/Note/Call Log + Contact":  {before_insert: autoset seller},
}

# Multi-tenant izolasyon — tüm seller-scoped doctype'lar için query filter
permission_query_conditions = { Listing, Admin Seller Profile, Seller Balance,
    Seller Review, Order, Brand, HD Ticket, CRM*, Contact, Platform Notification, ... }
has_permission = { aynı setin per-doc kontrolleri }

override_whitelisted_methods = {
    "crm.api.session.get_users":         tradehub_core.api.v1.crm_overrides.get_users,
    "crm.api.session.get_organizations": tradehub_core.api.v1.crm_overrides.get_organizations,
}
```

**`before_save` mı `on_update` mi?** Order için `before_save` kullanılmasının
nedeni hooks.py içinde yorum olarak açıklanmış: `on_update` form save sırasında
hidden read-only field'ları drop eder, `metrics_credited` değeri her seferinde
sıfırlanır → counter 2x/3x şişer. Yeni Order side-effect'lerini eklerken **aynı
kuralı** dikkate al.

---

## 5. FRAPPE GELİŞTİRME — DOĞRU YAKLAŞIM

### 5.1 DocType oluşturma
```
tradehub_core/tradehub_core/doctype/{snake_case_name}/
  ├── {name}.json        DocType schema (lowercase, snake_case)
  ├── {name}.py          class {PascalCase}(Document) controller
  ├── {name}.js          (opsiyonel) form script
  ├── test_{name}.py     (opsiyonel ama önerilir) — Frappe test runner
  └── __init__.py        Boş
```

**DocType tasarım disiplini (DocType bloat'tan kaçın):**
- Tekrarlayan veri → **Child Table** (`istable=1`, parent'ta `Table` field).
  Aynı Buyer için 5 adres → ayrı Address DocType + Link, **kopyalanmış field değil**.
- Kontrollü vocabulary → **Select** field (1-2 satırlı) ya da **Link** + ayrı DocType.
- İlişkiler → **Link**, asla string ile name kopyalama.
- Ağaç yapısı → `is_tree=1` (NSM lft/rgt kolonları otomatik). `_get_category_descendants`
  bu yapıyı `lft >= ? AND rgt <= ?` ile tek query'de sorguluyor — örnek model.
- Dosya/medya → **File** doctype + Link (raw path ile değil).
- Free-text alanı **analytics field'ı olarak kullanma** — index'lenemez, agg
  edilemez. Bunun yerine yapılandırılmış field çıkar.

### 5.2 Child Table kuralları
- `istable=1`, parent'ta `Table` field, `options=Child DocType Name`.
- `parent`, `parenttype`, `parentfield`, `idx` Frappe tarafından otomatik oluşur.
- Child kayıt için ayrı CRUD endpoint **yazma** — parent'ı save eden flow zaten
  child'ı yazar.

### 5.3 Python API — tercih sırası

| İhtiyaç | Önerilen API | Kaçınılacak |
|---------|--------------|-------------|
| Liste sorgu (yetki uygulansın) | `frappe.get_list("X", filters=..., fields=[...])` | `frappe.db.sql("SELECT ...")` |
| Liste sorgu (sistem işi, perm by-pass) | `frappe.get_all` (gerekçe yorumla) | Aynı |
| Tek field okuma | `frappe.db.get_value("X", name, "field")` | `get_doc` (overkill) |
| Çoklu field | `frappe.db.get_value("X", name, ["a","b"], as_dict=True)` | Birden fazla `get_value` |
| Doc CRUD | `frappe.get_doc(...)`, `doc.save()`, `doc.insert()`, `doc.delete()` | Doğrudan SQL UPDATE |
| Karmaşık JOIN/agg | **`frappe.qb`** (PyPika, parametreli, DB-agnostik) | `frappe.db.sql(f"... {var} ...")` |
| Async / uzun iş | `frappe.enqueue("path.fn", queue="default" / "long")` | İstek içinde 30 sn+ iş |
| Cache | `frappe.cache.get_value/set_value`, `frappe.client_cache` (request-scoped) | Module-level dict |
| Hata mesajı | `frappe.throw(_("Hata mesajı"), exc=SomeError)` | `raise Exception(...)` |
| i18n | `from frappe import _; _("...")` her kullanıcıya gidecek string için | Çıplak string |

### 5.4 frappe.qb mini örneği (raw SQL yerine)
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
Parametreler otomatik escape edilir. `frappe.db.sql` ile elle `%s` yapmak zorunda
değilsin. **`tradehub_core` repo'sunda şu an 0 (sıfır) `frappe.qb` kullanımı var
ve 218 raw SQL var** — yeni kod yazarken qb'yi tercih et, dokunduğun raw SQL'i
qb'ye taşımayı düşün (kapsam dışına çıkma kuralıyla — Bölüm 11).

### 5.5 Whitelist endpoint iskeleti
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

`@frappe.whitelist(allow_guest=True)` **yalnızca** açıkça public olan endpoint'ler
için (storefront listing arama, brand list vb.). Buyer/seller verisine dokunan
hiçbir endpoint guest olamaz.

### 5.6 Migration patch
```python
# tradehub_core/patches/v15_xx_yyy.py
import frappe

def execute():
    # idempotent — patch tekrar çalışırsa kırılmasın
    if not frappe.db.has_column("tabListing", "new_field"):
        return  # custom field tarafında halledilmiştir
    frappe.db.sql("UPDATE `tabListing` SET new_field = %s WHERE new_field IS NULL", (0,))
    frappe.db.commit()
```
Sırayı `patches.txt`'ye ekle: `tradehub_core.patches.v15_xx_yyy`.

### 5.7 Client-side JS
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

---

## 6. KESİNLİKLE YAPILMAMASI GEREKENLER (anti-pattern listesi)

Aşağıdaki kuralların her biri **ya kod tarama bulgusundan ya Frappe coding-standards
referansından** çıktı — kanıtla yazıldı, dogma değil.

### 6.1 Veritabanı / DocType
1. ⛔ **DocType bloat** — yarım kalan/kullanılmayan DocType bırakma. "Bir gün
   lazım olur" diye 30 field ekleme. Frappe'de production'da DocType clone'lamak
   kolay olduğu için sprawl en sık görülen sorun.
2. ⛔ **Tekrarlayan field** — aynı veriyi birden fazla yerde tutma (örn. seller_name'i
   her listing'e kopyalamak). Link kullan, denormalize etme zorunluluğun varsa
   yorumla **neden** olduğunu belirt (`Seller Review` rating proxy gibi).
3. ⛔ **Custom field SQL'le ekleme** — her zaman patch + custom_field doctype.
4. ⛔ **Field DB'den el ile silme** — `patches.txt` üzerinden idempotent migration.
5. ⛔ **Index'siz büyük tablo filtre** — bir kolon üstünde sürekli filtre
   yapıyorsan (territory, seller, status) index ekle:
   `frappe.db.add_index("Listing", ["seller", "status"])` ya da DocType JSON'da
   `"search_index": 1`.

### 6.2 Sorgular ve performans
6. ⛔ **Loop içinde DB call (N+1)** — `for x in items: frappe.db.get_value(...)`
   yerine batch fetch:
   ```python
   ids = [it.product for it in items]
   prices = {p.name: p.price for p in
             frappe.get_all("Product", {"name": ["in", ids]}, ["name", "price"])}
   for it in items: it.price = prices.get(it.product)
   ```
   *Tarama: ~38 olası N+1 pattern var, gözden geçirilecek.*
7. ⛔ **Tüm dataset'i belleğe yükleme** — pagelen yok, limit yok loop yok. Büyük
   batch'leri `frappe.enqueue` + `chunk` ile böl (`recommendations/swap.py` örneği).
8. ⛔ **`fields=["*"]`** — 50 kolonlu DocType'ı sadece 2 field için hiç çekme.
9. ⛔ **Senkron uzun iş** — 1 sn'den fazla süren ya da dış HTTP yapan iş
   `frappe.enqueue("…", queue="long")` ile arkaya alınmalı.
10. ⛔ **Cache'siz hot path** — storefront listing arama, kategori ağacı vb.
    her istekte hesaplanıyorsa Redis cache (`frappe.cache.set_value` + TTL).
    `_get_category_descendants` 10 dk TTL ile zaten örnekliyor.

### 6.3 Güvenlik
11. ⛔ **Raw SQL'de string interpolation** — `frappe.db.sql(f"… {x} …")` ya da
    `.format(x)` SQL injection açar. Tarama 14+ olası saldırı vektörü gösterdi
    (örn. `recommendations/swap.py` shadow/archive table adları). Sabit
    table/column adları için bile `frappe.db.escape` veya whitelist + assert.
12. ⛔ **`@frappe.whitelist()` + auth check yok** — endpoint sadece login isteyip
    kaynak sahipliğini doğrulamıyorsa farklı tenant'ın verisine erişilir. Her
    endpoint'te ya `doc.check_permission("read"|"write")` ya `frappe.only_for([...])`
    ya da `tenant.validate_tenant(doc)` çağrısı zorunlu.
13. ⛔ **`ignore_permissions=True` rasgele** — repo'da 275 kullanım var; bunların
    çoğu sistem yolları (after_install, scheduler, ERPNext sync) için **doğru**.
    Yeni eklerken kuralı uygula: *user input ile akan flow'da `ignore_permissions`
    yasak*. Eğer guest endpoint user adına doc oluşturuyorsa whitelist + role
    kısıtlama (`frappe.only_for`) + DocType allowlist gerekir.
14. ⛔ **`frappe.get_all`** kullanıcı verisi okurken — **`frappe.get_list`** kullan
    (permission_query_conditions devreye girer). `get_all` system-only.
15. ⛔ **`eval()`, `exec()`, kullanıcı input'undan `frappe.get_attr`** — RCE riski.
    Gerekirse `frappe.safe_eval` veya `frappe.utils.safe_exec.safe_exec`.
16. ⛔ **Path traversal** — kullanıcı dosya yolu vermeden önce `os.path.abspath`
    + `startswith(site_path)` doğrulaması; tercihen File doctype API'si.
17. ⛔ **CSRF bypass** — `ignore_csrf_for_token_auth` sadece pure API consumer için.
    Browser-tabanlı POST'larda CSRF token gönder.

### 6.4 Hooks ve event flow
18. ⛔ **`hooks.py`'yi silme/üzerine yazma** — mevcut dict'lere **append** et.
19. ⛔ **`doc_events["*"]` wildcard'ı geçersiz kılma** — varsa hala çalışmalı.
20. ⛔ **`validate()` override'da super çağırmamak** — mevcut doğrulama düşer.
    `super().validate()` zorunlu.
21. ⛔ **`doc.db_set("field", x)` ile validate'i bypass** — gerçekten gerekli
    olmadıkça kullanma; gerekiyorsa **niye** olduğunu yorumla.

### 6.5 Cross-app referans
22. ⛔ **ERPNext core'a deep import** — `from erpnext.x.y import …` kırılgan.
    Hooks veya Frappe'nin sağladığı stable API ile ilerle.
23. ⛔ **Yukarı yönde bağımlılık** — bugün tek app olduğu için pratik bir sorun
    yok; ileride bölünürse `tradehub_core` üst kalmalı, alt katmanlara doğru
    referans yasak.

### 6.6 Kod kalitesi
24. ⛔ **`except Exception:` (gerekçesiz)** — repo'da 182 yer var. Çoğu silently
    fail. En az `frappe.log_error("ne", "scope")` çağrısı + spesifik exception
    sınıfı yakalama gerekir.
25. ⛔ **`except:` (bare except)** — `KeyboardInterrupt` ve `SystemExit`'i de yutar.
    *Tarama: 3 yerde var, temizlenmeli.*
26. ⛔ **`print(...)` ile loglama** — repo'da ~69 yer (test dışı). `frappe.logger().info(...)`
    veya `frappe.log_error("...", "...")` kullan.
27. ⛔ **i18n'siz kullanıcı string'i** — `frappe.throw(_("..."))` zorunlu.
    Repo'da 592 i18n çağrısı var, yeni mesaj eklerken aynı kalıbı koru.
28. ⛔ **`__init__.py` dolu mantık** — boş init + ayrı modüllerde fonksiyon.

---

## 7. CLEAN CODE — TRADEHUB STANDARDI

### 7.1 Stil
- **Tab indent**, line-length 110, double quote (`pyproject.toml [tool.ruff.format]`).
- Modüller PEP 8 + Ruff'un seçtiği subset (E, F, W, I, B, UP).
- **Import sırası:** stdlib → 3rd party → frappe → tradehub_core. Ruff `isort`
  bunu otomatik yapar.

### 7.2 Fonksiyon ve modül boyutu
- **Fonksiyon ≤ ~30 satır.** Birden fazla "paragraf" varsa muhtemelen iki şey
  yapıyordur — ayır.
- **Tek sorumluluk:** "kullanıcıyı doğrula **ve** indirim hesapla" iki fonksiyon.
- **Dosya ≤ ~500 satır hedef.** Üstüne çıkıyorsa modüle böl. Bugün repo'da
  `seed_demo_data.py` 3972, `listing.py` 3407, `erpnext_sync.py` 2809 satır —
  bunlar Bölüm 11'deki refactor adayları.

### 7.3 İsimlendirme
- DocType: `Title Case` (örn. "Buyer Profile"). Klasör/dosya snake_case
  (`buyer_profile/buyer_profile.py`). Class PascalCase (`class BuyerProfile`).
- Whitelist endpoint: fiil ile başla (`get_listing_detail`, `add_to_cart`).
  Iç helper `_underscore_prefix`.
- Sabitler ALL_CAPS (`STOREFRONT_VISIBLE_STATUSES`, `CACHE_TTL`).

### 7.4 Type hints
- **Yeni kod için zorunlu** — Frappe v15 type annotation'ı runtime parametre
  doğrulama için kullanır. `def fn(name: str, qty: int) -> dict: …`
- Mevcut dosyaya dokunurken sadece dokunduğun fonksiyona ekle (refactor'u
  patlatma).

### 7.5 Yorum
- **Niye** yaz, **ne** değil. `# i++` yerine `# 0-tabanlı index'i dashboard kuralına
  göre 1-tabanlıya çeviriyoruz`.
- Bir tarihsel hata ya da iş kuralı varsa yorumla — `hooks.py`'deki Order
  `before_save` yorumu (counter 2x/3x şişmesi) iyi örnek.
- TODO/FIXME bırakırken ya issue link ekle ya 1 hafta içinde çöz; rotting
  TODO'lar borç.

### 7.6 Test
- Yeni DocType / API endpoint için en az 1 happy path + 1 error path test'i.
- `bench --site dev.localhost run-tests --doctype "Listing"` ile çalıştır.
- Test kütüphanesi olarak Frappe'nin built-in test runner'ı (`unittest` tabanlı).
  Yeni dependency ekleme.

### 7.7 Cache + invalidation
- TTL sınırla — `CACHE_TTL = 30` gibi sabit. Sınırsız TTL = dirty data.
- Yazma anında invalidate et — `invalidate_listing_cache` `Listing` doc_event'inde
  `on_update/after_insert/on_trash` üçünden de çağrılır (örnek model).
- `frappe.client_cache` request-scope; `frappe.cache` cross-request. İhtiyaca
  göre seç.

---

## 8. GÜVENLİK KONTROL LİSTESİ (her PR için)

- [ ] Yeni `@frappe.whitelist()` var mı? Auth check var mı?
- [ ] `allow_guest=True` kullanıyorsam gerçekten public mi (storefront veri)?
- [ ] User input → SQL: parametreli (`%s` veya qb)? Hiç `f"..."` yok değil mi?
- [ ] `ignore_permissions=True` ekledim mi? Gerekçe yorumla.
- [ ] DocType field'ı tenant'a bağlıysa `permission_query_conditions` listesinde
      mi? `hooks.py`'ye ekledim mi?
- [ ] Yeni dosya yolu kullanıyorsam path traversal açtım mı?
- [ ] Yeni HTTP entegrasyonunda timeout var mı? Retry stratejisi?

---

## 9. PERFORMANS KONTROL LİSTESİ

- [ ] Loop içinde DB call var mı? Batch fetch'e çevirdim mi?
- [ ] `fields=["*"]` ya da gereksiz field var mı?
- [ ] Sık filtreyle giden kolonun index'i var mı?
- [ ] Storefront/hot path'te cache var mı? TTL ne?
- [ ] 1 sn+ alan iş `frappe.enqueue`'a alındı mı?
- [ ] Schema değişiyorsa migration patch idempotent mi?
- [ ] `frappe.db.sql` yerine `frappe.qb` veya `get_list` mümkün mü?

---

## 10. BENCH VE GÜNLÜK KOMUTLAR

```bash
# Temel
bench --site dev.localhost migrate
bench --site dev.localhost console
bench --site dev.localhost clear-cache

# Tek doctype'ı yeniden taşı (custom field uyumu)
bench --site dev.localhost reload-doc tradehub_core doctype listing

# Test
bench --site dev.localhost run-tests --app tradehub_core
bench --site dev.localhost run-tests --doctype "Listing"

# Build (asset bundling)
bench build --app tradehub_core

# Lint
ruff check tradehub_core/
ruff format --check tradehub_core/
```

---

## 11. MEVCUT KOD BORÇLARI VE REFAKTOR HEDEFLERİ

Aşağıdaki listeler **mevcut kod taramasından** çıktı — yeni feature eklerken
"yolda" iyileştirilmeli, izole refactor PR'ı için de adaylar:

### 11.1 Aşırı büyük dosyalar (>1000 satır)
| Dosya | Satır | Yorum |
|------|------|-------|
| `tradehub_core/seed_demo_data.py` | 3972 | DEV seed; modüllere bölünebilir (per-domain). |
| `tradehub_core/api/listing.py` | 3407 | Kritik. Search / detail / write / cache sorumluluğu karışmış. |
| `tradehub_core/tradehub_core/utils/erpnext_sync.py` | 2809 | Customer / Supplier / Sales Order sync ayrı dosya. |
| `tradehub_core/api/v1/identity.py` | 1786 | Login/refresh/profile/password ayrı. |
| `tradehub_core/api/cart.py` | 1387 | Cart CRUD vs. promo / pricing ayrı. |
| `tradehub_core/api/seller.py` | 1314 | Profile / KPI / approvals ayrı. |
| `tradehub_core/tasks.py` | 1224 | Hourly / daily / weekly ayrı modül. |
| `tradehub_core/permissions.py` | 1176 | Per-doctype dosya altına dağıtılabilir. |
| `tradehub_core/api/order.py` | 1072 | OK ama yaklaşıyor. |
| `tradehub_core/tradehub_core/api/kpi_dashboard.py` | 1018 | OK ama yaklaşıyor. |

### 11.2 Sorgu modernizasyonu
- **0** `frappe.qb` kullanımı, **218** `frappe.db.sql`. Yeni kod qb ile başlasın;
  raw SQL'e dokunulduğunda mümkünse qb'ye taşı (kapsam kuralıyla — sırf bunun
  için mega-PR açma).
- F-string SQL pattern'i (`recommendations/swap.py` shadow/archive tablo adı
  formatı) en az `frappe.db.escape` veya isim whitelist kontrolüyle sertleşmeli.

### 11.3 Whitelist + auth audit
- 269 whitelist endpoint var. `permissions.py` query_conditions sadece liste
  endpoint'lerini koruyor; *single-doc fetch* endpoint'leri için `doc.check_permission`
  çağrılarının kapsamı doğrulanmalı (özellikle `api/listing.py`, `api/seller.py`,
  `api/cart.py`).

### 11.4 Hata yönetimi
- 182 `except Exception` — büyük çoğunluğu en azından `frappe.log_error` + spesifik
  exception sınıfı'na evrilmeli.
- 69 `print()` çağrısı — `frappe.logger()` ya da `frappe.log_error` ile değiştir.

### 11.5 Belge / kod tutarsızlığı (TARİHSEL)
- Bu CLAUDE.md eskiden 7 ayrı app anlatıyordu (catalog, commerce, seller, logistics,
  marketing, compliance) — kod o yapıda **değil**. Belge bugün gerçek monolit'i
  yansıtacak şekilde yenilendi (2026-05-08). Eski belgeye atıfta bulunan PR
  açıklamaları, issue'lar ya da CHANGELOG kayıtları varsa onlar da güncellenebilir.

---

## 12. AUTO-CLAUDE TASK YAZIM KURALLARI

### 12.1 Atomik task boyutu
- 1-3 dosya → simple
- 4-8 dosya → standard
- 9+ dosya → BÖL (ya feature'ı parçala ya refactor'ı izole PR yap)

### 12.2 Definition of Done (DoD)
- ✅ Dosya mevcut + grep pattern doğrulanmış
- ✅ `python -m py_compile <file>` veya import smoke testi
- ✅ `ruff check` temiz
- ✅ `bench --site dev.localhost migrate` patlamıyor
- ✅ İlgili DocType için (eğer test varsa) `bench run-tests --doctype "X"` yeşil
- ✅ Yeni whitelist endpoint için Bölüm 8 güvenlik kontrol listesi geçildi
- ❌ "Form'da dropdown çalışıyor görünüyor" (manuel UI doğrulaması site/test ortamı
   gerektirir, otomasyon DoD'i değil)

### 12.3 Yeni feature açarken hatırlatma
1. Belgede gerçeklikten kopuk bir şey gördüysen **önce belgeyi düzelt** (bu dosya).
2. Yeni DocType ekliyorsan: schema → controller → permission → hooks → patch → test.
3. Yeni endpoint ekliyorsan: type hints → permission check → i18n hata mesajı →
   cache invalidation → en az 1 happy + 1 error path test.
4. Schema değiştiriyorsan: migration patch (idempotent) + `patches.txt` kaydı.

---

## 13. REFERANSLAR (Frappe v15 dokümantasyonu)

- Frappe Hooks reference: https://docs.frappe.io/framework/user/en/python-api/hooks
- Frappe Database API: https://docs.frappe.io/framework/user/en/api/database
- Frappe Query Builder (qb): https://docs.frappe.io/framework/v15/user/en/api/query-builder
- Frappe v15 release notes: https://frappeframework.com/version-15
- ERPNext Coding Standards: https://github.com/frappe/erpnext/wiki/Coding-Standards
- ERPNext Code Security Guidelines: https://github.com/frappe/erpnext/wiki/Code-Security-Guidelines
- ERPNext Performance Tuning: https://github.com/frappe/erpnext/wiki/ERPNext-Performance-Tuning
- Migrating to v15: https://github.com/frappe/frappe/wiki/Migrating-to-version-15

---

**Bu belgenin yaşayan kısmı:** Bölüm 4 (hooks.py kayıtları), Bölüm 11 (refactor
hedefleri) ve Bölüm 2 (modül haritası) — kod değiştikçe güncellenmeli.
**Sabit kısmı:** Bölüm 5–9 (best practice + anti-pattern listeleri) — tek sefer
disipliniyle yazıldı, küçük ekleme/çıkarmalarla yaşar.
