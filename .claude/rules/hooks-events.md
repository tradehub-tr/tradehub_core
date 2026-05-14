---
paths:
  - "tradehub_core/hooks.py"
  - "**/doctype/**/*.py"
  - "**/*.py"
---

# hooks.py + doc_events + scheduler

## 1. Mevcut hooks.py kayıtları

`tradehub_core/hooks.py` **dokunulurken silmeden ekle** kuralı geçerli.

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
    "File":                 {before_insert: reject_unsafe_files},   # XSS guard
    "Listing":              {on_update/after_insert/on_trash → cache invalidation +
                             recommendations engine},
    "Product Category":     {on_trash: cascading cleanup},
    "Order":                {before_save: bump_listing_order_counts,
                             on_update: invalidate_tailored_user_cache},
    "Seller Review":        {after_insert/on_update/on_trash: rating proxy recompute},
    "Admin Seller Profile": {after_insert/on_update: helpdesk + role sync},
    "CRM Lead/Deal/Org/Task/Note/Call Log + Contact": {before_insert: autoset seller},
}

# Multi-tenant izolasyon — tüm seller-scoped doctype'lar için query filter
permission_query_conditions = { Listing, Admin Seller Profile, Seller Balance,
    Seller Review, Order, Brand, HD Ticket, CRM*, Contact,
    Platform Notification, ... }
has_permission = { aynı setin per-doc kontrolleri }

override_whitelisted_methods = {
    "crm.api.session.get_users":         tradehub_core.api.v1.crm_overrides.get_users,
    "crm.api.session.get_organizations": tradehub_core.api.v1.crm_overrides.get_organizations,
}
```

## 2. `before_save` mı `on_update` mi?

Order için `before_save` kullanılmasının nedeni hooks.py içinde yorum olarak açıklanmış:

> `on_update` form save sırasında hidden read-only field'ları drop eder, `metrics_credited` değeri her seferinde sıfırlanır → counter 2x/3x şişer.

Yeni Order side-effect'lerini eklerken **aynı kuralı** dikkate al.

## 3. Hook kuralları (yasak liste)

- ⛔ **`hooks.py`'yi silme/üzerine yazma** — mevcut dict'lere `append` et.
- ⛔ **`doc_events["*"]` wildcard'ı geçersiz kılma** — varsa hala çalışmalı.
- ⛔ **`validate()` override'da super çağırmamak** — mevcut doğrulama düşer. `super().validate()` zorunlu.
- ⛔ **`doc.db_set("field", x)` ile validate'i bypass** — gerçekten gerekli olmadıkça kullanma; gerekiyorsa **niye** olduğunu yorumla.

## 4. Yeni doc_event eklerken

1. **Sıralama:** `before_save` → `validate` → `before_insert/update` → `before_save` → DB → `after_insert/update` → `on_update`.
2. **Idempotent yap** — aynı doc_event 2× çalışırsa kırılmasın.
3. **Heavy work `frappe.enqueue`'a** — doc_event içinde uzun iş = save UI'ı dondurur.
4. **Cache invalidation** doc_event'in işi — `on_update` + `after_insert` + `on_trash` üçünden de çağır (Listing örneği).
5. **i18n** hata mesajları için `frappe.throw(_("..."))`.

## 5. Scheduler event ekleme

```python
# hooks.py
scheduler_events = {
    "daily": [
        # mevcut...
        "tradehub_core.tasks.my_new_daily_job",
    ],
}
```

Sonra `tradehub_core/tasks.py`'a fonksiyonu ekle. Heavy work için `"weekly_long"` queue.

## 6. `permission_query_conditions` (multi-tenant)

Yeni DocType seller-scoped ise (seller'a göre filtrelenmeli):

```python
# permissions.py
def get_listing_query_conditions(user):
    """Seller sadece kendi listing'lerini görür."""
    seller = get_current_seller(user)
    if not seller:
        return ""
    return f"`tabListing`.seller = {frappe.db.escape(seller)}"

# hooks.py
permission_query_conditions = {
    "Listing": "tradehub_core.permissions.get_listing_query_conditions",
}
```

Aynı DocType için `has_permission` (per-doc) de eklemeyi unutma.
