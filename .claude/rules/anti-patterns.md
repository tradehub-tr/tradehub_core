---
paths:
  - "**/*.py"
---

# Anti-pattern listesi (yapılmaması gerekenler)

Aşağıdaki kuralların her biri **kod tarama bulgusundan** ya da **Frappe coding standards** referansından çıktı — kanıtla yazıldı, dogma değil.

## Veritabanı / DocType

1. ⛔ **DocType bloat** — yarım kalan/kullanılmayan DocType bırakma. "Bir gün lazım olur" diye 30 field ekleme. Frappe'de DocType clone'lamak kolay olduğu için sprawl en sık görülen sorun.
2. ⛔ **Tekrarlayan field** — aynı veriyi birden fazla yerde tutma (örn. `seller_name`'i her listing'e kopyalamak). Link kullan; denormalize zorunluluğun varsa yorumla **neden** olduğunu belirt (`Seller Review` rating proxy gibi).
3. ⛔ **Custom field SQL'le ekleme** — her zaman patch + custom_field doctype.
4. ⛔ **Field DB'den el ile silme** — `patches.txt` üzerinden idempotent migration.
5. ⛔ **Index'siz büyük tablo filtre** — sürekli filtre yapılan kolona index ekle (`frappe.db.add_index` veya DocType JSON `"search_index": 1`).

## Sorgular ve performans

6. ⛔ **Loop içinde DB call (N+1)** — `for x in items: frappe.db.get_value(...)` yerine batch fetch:
   ```python
   ids = [it.product for it in items]
   prices = {p.name: p.price for p in
             frappe.get_all("Product", {"name": ["in", ids]}, ["name", "price"])}
   for it in items: it.price = prices.get(it.product)
   ```
   *Tarama: ~38 olası N+1 pattern var, gözden geçirilecek.*
7. ⛔ **Tüm dataset'i belleğe yükleme** — pagelen yok, limit yok loop yok. Büyük batch'leri `frappe.enqueue` + `chunk` ile böl (`recommendations/swap.py` örneği).
8. ⛔ **`fields=["*"]`** — 50 kolonlu DocType'ı sadece 2 field için hiç çekme.
9. ⛔ **Senkron uzun iş** — 1 sn+ süren ya da dış HTTP yapan iş `frappe.enqueue("…", queue="long")` ile arkaya alınmalı.
10. ⛔ **Cache'siz hot path** — storefront listing arama, kategori ağacı vb. her istekte hesaplanıyorsa Redis cache (`frappe.cache.set_value` + TTL). `_get_category_descendants` 10 dk TTL ile zaten örnekliyor.

## Güvenlik

11. ⛔ **Raw SQL'de string interpolation** — `frappe.db.sql(f"… {x} …")` ya da `.format(x)` SQL injection açar. *Tarama: 14+ vektör (örn. `recommendations/swap.py` shadow/archive table adları).* Sabit table/column adları için bile `frappe.db.escape` veya whitelist + assert.
12. ⛔ **`@frappe.whitelist()` + auth check yok** — endpoint sadece login isteyip kaynak sahipliğini doğrulamıyorsa farklı tenant'ın verisine erişilir. Her endpoint'te ya `doc.check_permission("read"|"write")` ya `frappe.only_for([...])` ya da `tenant.validate_tenant(doc)` çağrısı zorunlu.
13. ⛔ **`ignore_permissions=True` rasgele** — repo'da 275 kullanım var; çoğu sistem yolları (after_install, scheduler, ERPNext sync) için **doğru**. Yeni eklerken kural: *user input ile akan flow'da yasak*. Guest endpoint user adına doc oluşturuyorsa whitelist + role kısıtlama (`frappe.only_for`) + DocType allowlist gerekir.
14. ⛔ **`frappe.get_all` kullanıcı verisi okurken** — `frappe.get_list` kullan (permission_query_conditions devreye girer). `get_all` system-only.
15. ⛔ **`eval()`, `exec()`, kullanıcı input'undan `frappe.get_attr`** — RCE riski. Gerekirse `frappe.safe_eval` veya `frappe.utils.safe_exec.safe_exec`.
16. ⛔ **Path traversal** — kullanıcı dosya yolu vermeden önce `os.path.abspath` + `startswith(site_path)` doğrulaması; tercihen File doctype API'si.
17. ⛔ **CSRF bypass** — `ignore_csrf_for_token_auth` sadece pure API consumer için. Browser-tabanlı POST'larda CSRF token gönder.

## Hooks ve event flow

18. ⛔ **`hooks.py`'yi silme/üzerine yazma** — mevcut dict'lere append et.
19. ⛔ **`doc_events["*"]` wildcard'ı geçersiz kılma** — varsa hala çalışmalı.
20. ⛔ **`validate()` override'da super çağırmamak** — mevcut doğrulama düşer. `super().validate()` zorunlu.
21. ⛔ **`doc.db_set("field", x)` ile validate'i bypass** — gerçekten gerekli olmadıkça kullanma; gerekiyorsa **niye** olduğunu yorumla.

## Cross-app referans

22. ⛔ **ERPNext core'a deep import** — `from erpnext.x.y import …` kırılgan. Hooks veya Frappe'nin sağladığı stable API ile ilerle.
23. ⛔ **Yukarı yönde bağımlılık** — bugün tek app, pratik sorun yok; bölünürse `tradehub_core` üst kalmalı, alt katmanlara referans yasak.

## Kod kalitesi

24. ⛔ **`except Exception:` (gerekçesiz)** — repo'da 182 yer var. Çoğu silently fail. En az `frappe.log_error("ne", "scope")` çağrısı + spesifik exception sınıfı yakalama gerekir.
25. ⛔ **`except:` (bare except)** — `KeyboardInterrupt` ve `SystemExit`'i de yutar. *Tarama: 3 yerde var, temizlenmeli.*
26. ⛔ **`print(...)` ile loglama** — repo'da ~69 yer (test dışı). `frappe.logger().info(...)` veya `frappe.log_error("...", "...")` kullan.
27. ⛔ **i18n'siz kullanıcı string'i** — `frappe.throw(_("..."))` zorunlu. Repo'da 592 i18n çağrısı var, yeni mesaj eklerken aynı kalıbı koru.
28. ⛔ **`__init__.py` dolu mantık** — boş init + ayrı modüllerde fonksiyon.
