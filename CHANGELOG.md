## [v1.0.5-rc.2] - 2026-04-30 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

---
## [v1.0.5-beta.1] - 2026-04-30 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

---
## [v1.0.5-rc.1] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.5] - 2026-04-29 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(seller-application): Notify applicant on submission + EN translations for in-app notifications (@aliiball)
- feat(identity): Rework email verification — OTP-only flow, gating, audit, Desk User cleanup (@aliiball)
- feat(helpdesk,seller-crm): SLA + canned response + tag/saved filter + CRM scope (@ahmeetseker)
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@Bora)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)

### Duzeltildi
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)

### Degistirildi
- refactor: clean up string concatenation and formatting in various files (@Bora)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)

---
## [v1.0.4-rc.32] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)
- feat(helpdesk,seller-crm): SLA + canned response + tag/saved filter + CRM scope (@ahmeetseker)
- feat(identity): Rework email verification — OTP-only flow, gating, audit, Desk User cleanup (@aliiball)
- feat(seller-application): Notify applicant on submission + EN translations for in-app notifications (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.31] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)
- feat(helpdesk,seller-crm): SLA + canned response + tag/saved filter + CRM scope (@ahmeetseker)
- feat(identity): Rework email verification — OTP-only flow, gating, audit, Desk User cleanup (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.30] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)
- feat(helpdesk,seller-crm): SLA + canned response + tag/saved filter + CRM scope (@ahmeetseker)
- feat(identity): Rework email verification — OTP-only flow, gating, audit, Desk User cleanup (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.29] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)
- feat(helpdesk,seller-crm): SLA + canned response + tag/saved filter + CRM scope (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.28] - 2026-04-28 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.27] - 2026-04-27 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.26] - 2026-04-22 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.25] - 2026-04-21 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)
- feat(helpdesk): HD Ticket akışına in-app + e-posta bildirim hattı (yeni ticket → team, ajan yanıtı → müşteri, müşteri yanıtı → ajan/team) (@ahmeetseker)
- feat(notify): notify util'ı send_email parametresi + notify_team_members ve notify_assigned_users bulk helper'ları ile genişletildi (@ahmeetseker)
- feat(dashboard): platform_overview ve seller_overview dashboard'larına HD Ticket KPI widget'ları (Açık Talep / Yanıt Bekleyen) (@ahmeetseker)
- feat(helpdesk-sla): Helpdesk SLA Policy doctype + 4 default policy + hourly breach checker (HD Ticket Comment dedup'lı in-app + e-posta bildirim) (@ahmeetseker)
- feat(helpdesk-canned-response): Helpdesk Canned Response doctype + scope (platform/team/personal) + composer entegrasyonu için API (list_for_user, render) (@ahmeetseker)
- feat(api/public): bulk_update_tickets — toplu durum/öncelik/atama/team değişikliği wrapper'ı (max 200, permission query bazlı per-ticket kontrol) (@ahmeetseker)
- feat(seller-inquiry): JSON'a reply_message + replied_at + replied_by + buyer alanları + list_my_inquiries / get_inquiry / reply_inquiry / trash_inquiry API'leri + alıcı/satıcı bildirim hattı (@ahmeetseker)
- feat(helpdesk): HD Ticket'a related_order/related_rfq/related_listing custom field'ları (idempotent patch) + create_ticket parametre kabulü (@ahmeetseker)
- feat(helpdesk-tags): Helpdesk Ticket Tag + Helpdesk Ticket Tag Link doctype'ları + list/add/remove API'leri (renkli chip desteği) (@ahmeetseker)
- feat(helpdesk-saved-filter): Helpdesk Saved Filter doctype + list_my/save/delete API'leri (kişisel + ekiple paylaşılabilir görünümler) (@ahmeetseker)
- feat(crm-seller-scope): 7 Frappe CRM doctype'ına (Lead/Deal/Organization/Contact/Task/Note/Call) `seller` Custom Field + Marketplace Seller rolü için Custom DocPerm + permission_query/has_permission scope (@ahmeetseker)
- feat(crm-seller-scope): yeni CRM kaydı oluşturulurken creator'ın seller profile'ını otomatik set eden before_insert hook (@ahmeetseker)
- feat(seller-crm-api): tradehub_core.api.seller_crm.dashboard_kpis (open_leads, pipeline_value, won_this_month, conversion_rate, my_open_tasks) (@ahmeetseker)
- feat(seller-crm-api): inquiry_to_lead + rfq_to_lead + lead_to_deal köprü API'leri (Mağaza Sorusu/RFQ → CRM Lead, Lead → Deal dönüşümü permission-aware) (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.24] - 2026-04-21 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---
## [v1.0.4-rc.23] - 2026-04-20 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)

---
## [v1.0.4-rc.22] - 2026-04-17 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)

---
## [v1.0.4-rc.21] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)

---
## [v1.0.4-rc.20] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

---
## [v1.0.4-rc.19] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.18] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.17] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.16] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.15] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.14] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.13] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.12] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.11] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---
## [v1.0.4-rc.10] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)

---
## [v1.0.4-rc.9] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)

---
## [v1.0.4-rc.8] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)

---
## [v1.0.4-rc.7] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)

---
## [v1.0.4-rc.6] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)

---
## [v1.0.4-rc.5] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)

---
## [v1.0.4-rc.4] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)

---
## [v1.0.4-rc.3] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)

---
## [v1.0.4-rc.2] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)

---
## [v1.0.4-rc.1] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.4] - 2026-04-13 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat: Dashboard Banner DocType'ı ve aktif banner API endpoint'i ekle   - Dashboard Banner DocType'ı oluşturuldu (başlık, link, sıralama, aktiflik)   - get_active_banners API endpoint'i eklendi   - Demo veri seed script'i eklendi (seed_demo_data.py) (@ahmeetseker)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@ahmet)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@ahmet)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@Ali)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@ahmet)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@ahmet)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@Bora)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@Bora)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@Bora)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@Bora)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@Bora)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@Ali)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@Ali)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@Ali)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@Ali)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@ahmet)
- feat: update email verification and password reset links to use configurable storefront URL (@ahmet)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@Bora)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@Bora)
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@ahmet)

### Duzeltildi
- fix: seed script child table hatası düzeltildi — doc.append() yöntemiyle Frappe uyumluluğu sağlandı (@ahmeetseker)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@Bora)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@Bora)
- fix: hardcode storefront URL and update reset password link path in identity API (@ahmet)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)

### Degistirildi
- refactor(listing): compare_at_price ve is_on_sale sütunlarını kaldır (@aliiball)

---
## [v1.0.3-rc.19] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)
- feat: Dashboard Banner DocType'ı ve aktif banner API endpoint'i ekle (@ahmeetseker)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)
- fix: seed script child table hatası düzeltildi — doc.append() yöntemiyle Frappe uyumluluğu sağlandı (@ahmeetseker)

### Degistirildi
- refactor(listing): compare_at_price ve is_on_sale sütunlarını kaldır (@aliiball)

---
## [v1.0.3-rc.18] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)
- feat: Dashboard Banner DocType'ı ve aktif banner API endpoint'i ekle (@ahmeetseker)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

### Degistirildi
- refactor(listing): compare_at_price ve is_on_sale sütunlarını kaldır (@aliiball)

---
## [v1.0.3-rc.17] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)
- feat: Dashboard Banner DocType'ı ve aktif banner API endpoint'i ekle (@ahmeetseker)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.16] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.15] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.14] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.13] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.12] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.11] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@boraydeger32)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@boraydeger32)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---
## [v1.0.3-rc.8] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)

---
## [v1.0.3-rc.7] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)

---
## [v1.0.3-rc.6] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)

---
## [v1.0.3-rc.5] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)

---
## [v1.0.3-rc.4] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)

---
## [v1.0.3-rc.3] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@Ali)

---
## [v1.0.3-rc.2] - 2026-04-07 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.3-rc.1] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.3] - 2026-04-06 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@ahmet)
- feat: update email verification and password reset links to use configurable storefront URL (@ahmet)
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)

### Duzeltildi
- fix: hardcode storefront URL and update reset password link path in identity API (@ahmet)
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)

---
## [v1.0.2-rc.5] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)

### Duzeltildi
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)

---
## [v1.0.2-rc.4] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)

### Duzeltildi
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)

---
## [v1.0.2-rc.3] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)

### Duzeltildi
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)

---
## [v1.0.2-rc.2] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@Ali)

### Duzeltildi
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@Ali)

---
## [v1.0.2-rc.1] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.2] - 2026-04-06 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@Bora)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@Bora)
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@ahmet)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)

---
## [v1.0.1-rc.5] - 2026-04-03 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@TurksabYonetim)
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)

---
## [v1.0.1-rc.4] - 2026-04-03 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@TurksabYonetim)

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@Ali)

---
## [v1.0.1-rc.3] - 2026-04-03 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@TurksabYonetim)

---
## [v1.0.1-rc.2] - 2026-04-02 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)

---
## [v1.0.1-rc.1] - 2026-04-01 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.1] - 2026-04-01 PROD

Bu surum istoc.cronbi.com'da yayindadir.

---
## [v1.0.0-rc.1] - 2026-04-01 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
## [v1.0.0-rc.1] - 2026-03-31 RC

Bu surum rc.istoc.com'da test asamasindadir.

---
# tradehub_core Changelog

Tüm önemli değişiklikler bu dosyada belgelenir.
Format: [SemVer](https://semver.org/) standardına göre.

---
