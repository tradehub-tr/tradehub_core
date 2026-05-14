---
paths:
  - "**/*.py"
---

# Güvenlik + performans kontrol listeleri (her PR için)

## 1. Güvenlik kontrol listesi

- [ ] Yeni `@frappe.whitelist()` var mı? Auth check var mı (`doc.check_permission` / `frappe.only_for` / `validate_tenant`)?
- [ ] `allow_guest=True` kullanıyorsam gerçekten public mi (storefront veri)?
- [ ] User input → SQL: parametreli (`%s` veya qb)? **Hiç `f"..."` yok değil mi?**
- [ ] `ignore_permissions=True` ekledim mi? **Gerekçe yorumla.**
- [ ] DocType field'ı tenant'a bağlıysa `permission_query_conditions` listesinde mi? `hooks.py`'ye ekledim mi?
- [ ] Yeni dosya yolu kullanıyorsam path traversal açtım mı?
- [ ] Yeni HTTP entegrasyonunda timeout var mı? Retry stratejisi?
- [ ] `eval`/`exec`/`get_attr` user input'undan mı? RCE riski.
- [ ] Browser-tabanlı POST'ta CSRF token var mı?
- [ ] Token/parola log'a yazılmıyor mu?

## 2. Performans kontrol listesi

- [ ] Loop içinde DB call var mı? **Batch fetch'e çevirdim mi?**
- [ ] `fields=["*"]` ya da gereksiz field var mı? Sadece kullanılan field'ları çek.
- [ ] Sık filtreyle giden kolonun **index'i var mı**?
- [ ] Storefront/hot path'te **cache var mı? TTL ne?**
- [ ] 1 sn+ alan iş `frappe.enqueue`'a alındı mı? (queue: `default` / `long`)
- [ ] Schema değişiyorsa migration patch **idempotent mi**?
- [ ] `frappe.db.sql` yerine `frappe.qb` veya `get_list` mümkün mü?
- [ ] Büyük dataset'i belleğe yüklüyor muyum? Pagelen/chunk var mı?

## 3. Tenant izolasyonu kontrol listesi

Seller-scoped DocType (Listing, Order, Seller Balance, vb.) ile çalışıyorsan:

- [ ] `permission_query_conditions` liste sorgusunda devreye giriyor mu?
- [ ] `has_permission` per-doc kontrolü ekledim mi?
- [ ] `frappe.get_list` (not `get_all`) kullandım mı?
- [ ] `validate_tenant(doc)` veya `doc.check_permission` çağırdım mı?
- [ ] Cross-seller veri sızıntısı testi yazdım mı? (farklı seller'ın doc'una erişim deneme)

## 4. i18n kontrolü

- [ ] Tüm kullanıcıya görünen string `_("...")` ile sarıldı mı?
- [ ] `frappe.throw(_("..."))` — `raise Exception("...")` değil mi?
- [ ] Hata mesajları Türkçe mi? (kullanıcı dili)
- [ ] Yeni mesaj eklerken mevcut çeviri dosyalarına da eklendi mi?

## 5. Cache invalidation kontrolü

- [ ] Yeni cache key'i için **invalidate fonksiyonu** yazıldı mı?
- [ ] `on_update` + `after_insert` + `on_trash` doc_event'lerinden çağrılıyor mu?
- [ ] TTL sabit (sınırsız değil)?
- [ ] Cache key prefix proje-spesifik mi (`tradehub:` veya `tc:`)?
