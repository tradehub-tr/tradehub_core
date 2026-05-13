## [v1.0.8-beta.8] - 2026-05-13 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(changelog): commit body bullet'larını subject altında nested gösterildi (@ahmeetseker)

### Duzeltildi
- fix(release-workflows): commit body bullet'larını subject altında nested göster (@ahmeetseker)

---
## [v1.0.8-beta.7] - 2026-05-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(release-workflows): commit body bullet'larini CHANGELOG'a dahil et (@ahmeetseker)

---
## [v1.0.8-beta.6] - 2026-05-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(release): commit mesajındaki boşlukları temizlendi (@ahmeetseker)

---
## [v1.0.8-beta.5] - 2026-05-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat: update auth and listing APIs to enhance seller profile management and listing visibility (@boraydeger32)

---
## [v1.0.8-beta.3] - 2026-05-11 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(header-notice): 5 değişiklik (@ahmeetseker)
  - add Header Notice DocType schema and controller
  - add migration patch for Header Notice
  - add public API endpoint with 60s cache
  - wire cache invalidation via doc_events hooks
  - add display_mode settings + per-notice background_color

### Duzeltildi
- fix(header-notice): 3 değişiklik (@ahmeetseker)
  - use tab indentation and add search_index for filter fields
  - commit after setUpClass cleanup to ensure test isolation
  - drop auto-downgrade so storefront uses admin's chosen mode

---

## [v1.0.8-beta.1] - 2026-05-11 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(api): API yanıtında hata mesajı düzeltildi (@ahmeetseker)

---

## [Belgelenmemiş Özellikler — Geliştirme Süreci Özeti] - 2026-05-08

Bu bölüm, geliştirme sürecinde koda eklenmiş ancak önceki sürüm changelog'larında (özellikle v1.0.7-beta.1 ile v1.0.7-beta.10 arası ve v1.0.5 prod sonrası) yeterince belgelenmemiş özellikleri kapsamlı olarak listeler. Her madde, etkilediği domain, ne yaptığı ve teknik kapsamıyla birlikte yazılmıştır. Kaynak: `git log version-15..ahmet` + dosya bazlı kod taraması.

### Eklendi (Belgelenmemiş)
- feat(ci): 3 aşamalı release akışı (beta/rc/prod) ve Jenkins tetiklemesine geçiş — `.github/workflows/beta-release.yml` eklendi, mevcut `rc-release.yml` ve `prod-release.yml` Jenkins job'larını çağıracak şekilde yeniden düzenlendi; otomatik changelog commit'leri `github-actions[bot]` üzerinden atılır hâle getirildi (@ahmeetseker)
- feat(listing): 2 değişiklik (@boraydeger32)
  - "Out of Stock" statüsü storefront davranışı — `STOREFRONT_VISIBLE_STATUSES` artık Active + Out of Stock'u kapsıyor; ilan stokta yokken listede/detayda görünür ama stok değerleri runtime'da 0'a sıfırlanıp sepete ekleme engelleniyor, statü Active'e döndüğünde DB'deki orijinal stok geri geliyor (`tradehub_core/api/listing.py`, +80 satır)
  - Varyant özellik linkleme + negatif değer doğrulaması — `Listing.validate` içine `_resolve_attribute_links` eklendi; serbest metinle girilen özellik adları otomatik `Product Attribute` kayıtlarına bağlanıyor; varyant fiyat/stok kontrolünde yanlış alan adları (price→variant_price, stock→variant_stock) düzeltildi
- feat(checkout): Sepet/sipariş için fatura bilgisi (billing_info) — `cart.add_to_cart` ve `cart.create_order` artık JSON `billing_info` kabul ediyor; `_parse_billing_info` Bireysel TCKN-11 / Şirket VKN-10 doğrulaması yapıyor; `same_as_shipping` ile teslimat adresinden snapshot'lanabiliyor; `Order` doctype'ına 98 satırlık fatura alanı eklendi (billing_type, tax_office, vkn/tcn, e_invoice, fatura adresi snapshot'u) (@ahmeetseker)
- feat(cart): 2 değişiklik
  - Numune (is_sample) sepet satırı — `Cart Item` doctype'ına `is_sample` boolean alanı eklendi; aynı listing/varyantın bulk vs numune satırları artık ayrı tutuluyor; numune satırı `Listing.sample_price` ile fiyatlanıyor; `add_cart_item_is_sample` idempotent migration patch'i ile mevcut DB'lere de yansıtıldı (@ahmeetseker)
  - SKU bazlı varyant fiyatı + kampanya snapshot tutarlılığı — `_get_variant_price_by_label`, `_get_listing_effective_price` ve `_get_discount_factor` helper'ları eklendi; çoklu eksenli varyantlarda artık `Listing Variant Item.variant_price` döndürülüyor; `add_to_cart` snapshot, `_build_cart_response`, `merge_guest_cart` ve tier fiyatları listing detayındaki indirimle bire bir tutarlı; `variant_price` ve `sample_price` kampanya indirimine tabi değil (@boraydeger32, @ahmeetseker)
- feat(category): Ürün kategorisi benzersizlik kontrolü — `Product Category.validate` içine 30 satırlık eklenti ile aynı parent altında aynı isimli kategori oluşturmayı engelleyen kontrol eklendi (@boraydeger32)
- feat(crm-overrides): Marketplace Seller için CRM override layer'ı — `tradehub_core/api/v1/crm_overrides.py` içinde `crm.api.session.get_users` ve `crm.api.session.get_organizations` whitelist override'ları (`hooks.py:override_whitelisted_methods`); `get_users`/`get_organizations` artık satıcının yalnızca kendi User/Organization kayıtlarını görmesini sağlayacak şekilde sızıntı önlemli; `save_contact` Contact CRUD child table senkronu (`email_ids`/`phone_nos`) için server-side `doc.save` köprüsü; `crm_get_count(doctype, filters)` permission-aware sayım endpoint'i — Marketplace Seller rolüne sahip kullanıcıya kendi `seller` field'ı + owner fallback ile filtre uygular (@ahmeetseker)
- feat(seller-role-sync): Admin Seller Profile ↔ User rol senkron hook'u — `utils/seller_role_sync.py` eklendi; profil aktifken kullanıcıya `Marketplace Seller` rolü atanır, askıya alındığında geri alınır; `hooks.py` doc_events'lerine bağlandı; `backfill_marketplace_seller_role` patch'i ile aktif Admin Seller Profile sahibi kullanıcılara rol geriye dönük atandı (CRM doctype DocPerm bu role bağlı, eskiden yalnız `Seller` atanıyordu) (@ahmeetseker)
- feat(crm-seed): CRM Lead Source seed — `seed_crm_lead_sources` patch'i ile Lead "Kaynak" dropdown'una varsayılan değerler dolduruldu (Frappe CRM uygulaması yüklü değilse no-op ile geçer); ardından autoname field'ı `source_name` olarak düzeltildi (@ahmeetseker)
- feat(notifications): 4 değişiklik (@boraydeger32)
  - action_url sanitize — `utils/notify._sanitize_action_url` eklendi; yalnızca `/...` path veya `https://` kabul edilir; `javascript:`, `data:`, `http:`, protocol-relative URL'ler reddedilir (XSS/açık yönlendirme koruması)
  - Permission-aware Platform Notification görünürlüğü — `Platform Notification` için `get_permission_query_conditions` + `has_permission` `hooks.py`'a kaydedildi; Marketplace Buyer/Seller Desk'te yalnızca kendi bildirimlerini görür; `notify_team_members` ve `notify_assigned_users` bulk helper'ları içinde Administrator/Guest hedefleri filtrelendi (#8 spam fix)
  - Bildirim mark_read idempotency — `api/notification.mark_read` artık daha önce okunmuş kayıtta `read_at` damgasını korur (audit trail) ve owner+is_read'i tek sorguda kontrol eder; `get_new_notifications` `is_read=0`'ı her zaman zorunlu hâle getirdi (drawer'dan okunan eski bildirimin `since` parametresi ile re-toast edilmesi engellendi, #2 fix)
  - Cleanup retention uzatması — `notification_cleanup` görevinde okunmamış bildirim retention süresi 180 gün → 365 güne çıkarıldı; uzun süre pasif kalan kullanıcının kritik bildirimlerinin sessizce silinmesi engellendi
- feat(seller): Mağaza storefront medya grupları — `api/seller.get_seller` yanıtına `media_groups` (overview / 360 / production / QC kategorileri) eklendi; `Admin Seller Profile.gallery_images` çocuk tablosundan video önceliğiyle türetilir; `Seller Gallery Image` doctype'ına `category`, `media_type`, `video_url`, `poster_image`, `sort_order` alanları eklendi; `image` artık `media_type`'a `depends_on` ile bağlı; `_build_media_groups` helper'ı satıcı namespace'inde gruplama yapar — frontend StoreHeader hardcoded thumb'lar yerine bu yapıyı kullanır (@boraydeger32)
- feat(verified-seller): Verified Seller rolü ve KYB sync hattı — `KYB Verification.on_update` 5 status için `Verified Seller` rolünü kullanıcıya senkronlar (Verified iken atar, diğer durumlarda kaldırır); `assign_verified_seller_role` patch'i mevcut KYB durumlarına göre rolleri geriye dönük atar/temizler; `cleanup_legacy_verification_fields` patch'i `Admin Seller Profile.is_verified` ve `verification_type` alanlarını DB sütun audit ile DROP eder (artık tek doğruluk kaynağı KYB Verification + role) (@aliiball)
- feat(order-gate): 3 katmanlı doğrulanmış-satıcı sipariş gate'i — Sipariş açma yolunun her aşamasında KYB doğrulaması zorunlu hâle getirildi: `cart.add_to_cart` (sepete eklerken), `cart.create_order` (siparişi başlatırken) ve `Order.validate` (DB save anında); `_ensure_seller_kyb_verified` helper'ı doğrulanmamış satıcıların ürünlerinin sipariş edilmesini engelliyor (@aliiball)
- feat(listing-filter): Doğrulanmış tedarikçi ve MOQ filtreleri — `listing.get_listings` artık `min_order` parametresi alıyor; `verified_supplier` filtresi `Verified Seller` rolüne sahip kullanıcıları sorgulayan SQL ile bağlandı (`tradehub_core/api/listing.py:731+`); `listing.get_listing_detail` ve `seller.get_sellers` `verified` flag'ini KYB rolünden hesaplıyor; storefront'taki "Verified Supplier" sayacı (`verifiedSupplierCount`) bu filtreden besleniyor (@aliiball)
- feat(auth): Session payload'a is_verified_seller — `api/v1/auth.get_session_user` yanıtına `is_verified_seller` boolean'ı eklendi (rol setinde "Verified Seller" var mı?); frontend auth store'da `isVerifiedSeller` ve `kybStatus` computed property'leri bu alandan beslenecek şekilde tasarlandı (@aliiball)
- feat(utils/country): Yeni ülke yardımcısı — `tradehub_core/utils/country.py` eklendi; 15 ülke için ISO-2 kod, ülke adı ve emoji bayrak haritası; case-insensitive arama desteği; `get_seller`, profil ve listing yanıtlarında bayrak/standart kod normalizasyonu için kullanılır (@aliiball)
- feat(seller-application): KYB skeleton ignore_mandatory bypass — `become_seller` ve `Seller Application` approval flow'unda KYB Verification iskeleti `ignore_mandatory=True` ile insert edilir; gerçek alan zorunluluğu yalnızca `submit_kyb_documents` endpoint'inde uygulanır (yarım profilden submit'e geçişin tek noktadan kontrolü) (@aliiball)
- feat(profile-avatar): Avatar tek doğruluk kaynağına konsolidasyon — `Buyer Profile.avatar` ve `Seller Profile.avatar` custom alanları kaldırıldı; tek doğruluk kaynağı `User.user_image` oldu; `auth.get_user_profile` ve `update_user_profile` buna göre güncellendi; `cleanup_avatar_fields` idempotent patch'i SP/BP avatar değerlerini boş `User.user_image`'lere taşır (mevcut user_image'i ezmez), sonra avatar kolonlarını DROP eder; `seed_demo_data` artık User.user_image üzerinden yazar (@aliiball)
- feat(kyb): 4 değişiklik (@aliiball)
  - bank_account_document zorunlu 6. KYB belgesi — `KYB Verification` doctype'ına eklendi; `submit_kyb_documents`'te 6 belgenin tamamı `reqd:1`; status field `read_only:1` (yalnız review akışından değiştirilebilir)
  - KYB upload defansif sertleştirme — `upload_kyb_document` endpoint'i: extension whitelist (pdf/jpg/jpeg/png/webp/docx), magic-byte doğrulama (DOCX için ZIP+`[Content_Types].xml`/`word/` kontrolü), 10 MB cap, `is_private=1` attach; rate limit: upload 20/300s, submit_kyb_documents 1/60s
  - KYB resubmit/review akışı — Resubmit yalnızca Rejected → Pending'de ve belge field'ı gerçekten değiştiyse çalışır; Verified/Under Review'da no-op (status flicker önlendi); response `resubmitted` + `previous_status` flag'leri döner; `review_kyb` Pending ve Expired aksiyonlarını destekler; Rejected için min 20 karakterlik `rejection_reason` zorunlu (endpoint + doctype validate, defense-in-depth); admin-only `notes` field permlevel 2 ile tarih+kullanıcı damgalı append edilir; `verified_by`/`verified_at` artık "son inceleyen/son inceleme" semantiğine sahip; Pending'e dönüşte sıfırlanır, Verified'da `rejection_reason` temizlenir
  - get_kyb_status pre-fill önceliği — Seller Application önce, Seller Profile fallback olarak pre-fill kaynağı; mevcut KYB'lerde eksik alanlar idempotent doldurulur; bildirim `action_url` `/pages/dashboard/kyb.html`'e güncellendi; admin bildirimi resubmit/ilk başvuruyu ayrıştırır, dedup kaldırıldı (her gerçek geçiş ayrı bildirim)
- feat(profile): business_name boş gönderilemez doğrulaması — `update_user_profile` artık boş `business_name` ile güncellemeye izin vermiyor (storefront satıcı vitrini için zorunlu alan) (@aliiball)
- feat(patch): assign_seller_role_legacy — Approved `Seller Application`'ı olup `Seller` rolü eksik kalmış kullanıcılara rolü geriye dönük atayan patch; manuel SQL/admin müdahalesinden doğan permission 403'lerini düzeltir (@aliiball)

### Duzeltildi (Belgelenmemiş)
- fix(api,security): Defansif input validasyonu + dosya upload XSS koruması — `tradehub_core/api/` genelinde `cint`/`flt` ile sayısal parametreler sertleştirildi; `hooks.py:doc_events.File.before_insert.reject_unsafe_files` File doctype'ına yüklenen tehlikeli içerikleri (HTML/SVG/JS) before_insert aşamasında reddeder (@boraydeger32)
- fix(patches/cleanup_avatar_fields): `frappe.db.sql` yerine `frappe.db.sql_ddl` + explicit commit — Frappe v15 `check_implicit_commit()` veri yazımı sonrası ALTER TABLE'da `ImplicitCommitError` fırlatıyordu; veri migration'ı `frappe.db.commit()` ile commit'lenip, DROP COLUMN `sql_ddl` ile çalıştırıldı (DDL implicit-commit guard'ından muaf); patch idempotent kaldı (kolon var-mı kontrolü ile) (@ahmeetseker)
- fix(patches/seed_crm_lead_sources): autoname field düzeltmesi — CRM Lead Source autoname'i `lead_source` değil `source_name`; orijinal patch yanlış field set edip insert'te `Source Name is required` ValidationError'a düşüyordu; beta'da CRM app yüklü olmadığı için `table_exists=False` no-op olarak sessiz kalmıştı, fresh DB'de yakalandı (@ahmeetseker)
- fix(patches): HD Ticket DocType dependency check — Helpdesk app yüklü değilken `seed_helpdesk_*` ve `add_helpdesk_ticket_link_fields` patch'lerinin migration'ı kırmaması için DocType varlığı kontrolü eklendi (graceful skip) (@ahmeetseker)
- fix(patches/grant_seller_crm_permissions): Hem Seller hem Marketplace Seller rolüne CRM perm — Eski patch yalnızca `Seller` rolüne grant ediyordu; `add_seller_to_crm_doctypes` ve `grant_seller_crm_permissions` patch'leri force re-run için yeniden adlandırıldı; `expand seller CRM permissions to lookup tables + permlevel 1` ile lookup doctype'ları (`CRM Lead Source` vb.) ve permlevel 1 alanları kapsama alındı (@ahmeetseker)
- fix(seller-permissions): Owner fallback — `permissions.py` Marketplace Seller scope'unda `seller` field'ı boş ya da legacy kayıtlarda `owner = current user` fallback'i; sahibinin oluşturduğu eski CRM kayıtlarına erişim kaybı engellendi (@ahmeetseker)
- fix(notifications): notify util erken `frappe.db.commit()` kaldırıldı — Outer transaction'ı bozuyordu; bildirim oluşturma artık çağıran transaction'a uyumlu (@boraydeger32)
- fix(listing): certifications child table defansif handle — `listing.py`'de `certifications` artık hem child table list hem string formatını idempotent şekilde işler (eski seed'lerden gelen string formatını kırmadan yeni Link formatına geçiş için) (@aliiball)

### Degistirildi (Belgelenmemiş)
- refactor(crm): seller field child doctype kapsamına dahil — `Lead/Deal/Organization/Contact/Task/Note/Call Log` 7 CRM doctype'ında `seller` Custom Field + DocPerm + permission_query/has_permission scope kuralları sertleştirildi; lookup tablolarındaki permlevel 1 alanları da Marketplace Seller rolüne açıldı (@ahmeetseker)
- refactor(notifications): action_url tüm bildirim üreticilerinde dashboard sayfa rotalarına güncellendi (KYB, sipariş, RFQ, ticket için) — eski hardcoded URL'ler kaldırıldı (@aliiball, @boraydeger32)
- refactor(seller-profile): Storefront'ta kullanılmayan legacy alanlar (`is_verified`, `verification_type`, profil avatar) doctype'tan ve API yanıtlarından kaldırıldı; tek doğruluk kaynağı sırasıyla `Verified Seller` rolü, `KYB Verification` ve `User.user_image` (@aliiball)

---

## [v1.0.7-beta.8] - 2026-05-07 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(patches): expand seller CRM permissions to lookup tables + permlevel 1 (@ahmeetseker)

### Degistirildi
- refactor(patches): rename add_seller_to_crm_doctypes to force re-run (@ahmeetseker)

---

## [v1.0.7-beta.7] - 2026-05-07 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(patches): grant CRM perms to both Seller and Marketplace Seller roles (@ahmeetseker)

### Degistirildi
- refactor(patches): rename grant_seller_crm_permissions to force re-run (@ahmeetseker)

---

## [v1.0.7-beta.6] - 2026-05-07 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix: add dependency check for HD Ticket DocType to prevent patch failure if helpdesk app is missing (@ahmeetseker)

---

## [v1.0.7-beta.4] - 2026-05-06 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(kyb,profile): KYB belge upload sertleştirme + resubmit/review akışı + avatar User.user_image konsolidasyonu (@aliiball)

## [v1.0.7-beta.3] - 2026-05-06 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix: update seller permissions to include owner fallback and implement permission-aware CRM count endpoint (@ahmeetseker)

---

## [v1.0.4-rc.32] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(seller-application): Notify applicant on submission + EN translations for in-app notifications (@aliiball)

## [v1.0.4-rc.30] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(identity): Rework email verification — OTP-only flow, gating, audit, Desk User cleanup (@aliiball)

## [v1.0.4-rc.29] - 2026-04-29 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(helpdesk,seller-crm): SLA + canned response + tag/saved filter + CRM scope (@ahmeetseker)

## [v1.0.4-rc.28] - 2026-04-28 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(seller,seed): satıcı arama/kategori filtresi + sektörel ürün spec havuzu (@ahmeetseker)

## [v1.0.4-rc.27] - 2026-04-27 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(listing): kategori subtree filtresi + B2B min_order_qty senkron patch (@ahmeetseker)

## [v1.0.4-rc.26] - 2026-04-22 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: add image parameter to update_seller_category and change required status of category field (@boraydeger32)

## [v1.0.4-rc.25] - 2026-04-21 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(helpdesk): 2 değişiklik (@ahmeetseker)
  - HD Ticket akışına in-app + e-posta bildirim hattı (yeni ticket → team, ajan yanıtı → müşteri, müşteri yanıtı → ajan/team)
  - HD Ticket'a related_order/related_rfq/related_listing custom field'ları (idempotent patch) + create_ticket parametre kabulü
- feat(notify): notify util'ı send_email parametresi + notify_team_members ve notify_assigned_users bulk helper'ları ile genişletildi (@ahmeetseker)
- feat(dashboard): platform_overview ve seller_overview dashboard'larına HD Ticket KPI widget'ları (Açık Talep / Yanıt Bekleyen) (@ahmeetseker)
- feat(helpdesk-sla): Helpdesk SLA Policy doctype + 4 default policy + hourly breach checker (HD Ticket Comment dedup'lı in-app + e-posta bildirim) (@ahmeetseker)
- feat(helpdesk-canned-response): Helpdesk Canned Response doctype + scope (platform/team/personal) + composer entegrasyonu için API (list_for_user, render) (@ahmeetseker)
- feat(api/public): bulk_update_tickets — toplu durum/öncelik/atama/team değişikliği wrapper'ı (max 200, permission query bazlı per-ticket kontrol) (@ahmeetseker)
- feat(seller-inquiry): JSON'a reply_message + replied_at + replied_by + buyer alanları + list_my_inquiries / get_inquiry / reply_inquiry / trash_inquiry API'leri + alıcı/satıcı bildirim hattı (@ahmeetseker)
- feat(helpdesk-tags): Helpdesk Ticket Tag + Helpdesk Ticket Tag Link doctype'ları + list/add/remove API'leri (renkli chip desteği) (@ahmeetseker)
- feat(helpdesk-saved-filter): Helpdesk Saved Filter doctype + list_my/save/delete API'leri (kişisel + ekiple paylaşılabilir görünümler) (@ahmeetseker)
- feat(crm-seller-scope): 2 değişiklik (@ahmeetseker)
  - 7 Frappe CRM doctype'ına (Lead/Deal/Organization/Contact/Task/Note/Call) `seller` Custom Field + Marketplace Seller rolü için Custom DocPerm + permission_query/has_permission scope
  - yeni CRM kaydı oluşturulurken creator'ın seller profile'ını otomatik set eden before_insert hook
- feat(seller-crm-api): 2 değişiklik (@ahmeetseker)
  - tradehub_core.api.seller_crm.dashboard_kpis (open_leads, pipeline_value, won_this_month, conversion_rate, my_open_tasks)
  - inquiry_to_lead + rfq_to_lead + lead_to_deal köprü API'leri (Mağaza Sorusu/RFQ → CRM Lead, Lead → Deal dönüşümü permission-aware)

## [v1.0.4-rc.24] - 2026-04-21 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Degistirildi
- refactor: clean up string concatenation and formatting in various files (@boraydeger32)

---

## [v1.0.4-rc.23] - 2026-04-20 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Degistirildi
- refactor: replace Pexels CDN image IDs with direct DummyJSON product image URLs in seed_demo_data.py (@ahmeetseker)
- refactor: rename unused dictionary key variable in seed_demo_data.py to underscore (@ahmeetseker)

---

## [v1.0.4-rc.21] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Degistirildi
- refactor(cart): _get_inline_variant_stock tamamen kaldırıldı (@ahmeetseker)

---

## [v1.0.4-rc.20] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix(rfq): Satıcı RFQ eşleşmesine listing platform kategorisi desteği eklendi. (@aliiball)

---

## [v1.0.4-rc.18] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(payment): kredi kartı ödemeleri için Payment Transaction kaydı ve havale backfill mekanizması (@ahmeetseker)

## [v1.0.4-rc.17] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(currency): TCMB entegrasyonu ile dinamik para birimi sistemi geliştirildi. (@aliiball)

## [v1.0.4-rc.16] - 2026-04-16 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(theme): ürün kartı token whitelist'i (_PRODUCT_CARD_KEYS, 80 anahtar) (@ahmeetseker)

## [v1.0.4-rc.15] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(dashboard): Config tabanlı widget engine, 2 dashboard ve 25 hazır widget eklendi. (@aliiball)

## [v1.0.4-rc.13] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: add agent_reply_ticket headless API to update HD Ticket status without email triggers (@ahmeetseker)

## [v1.0.4-rc.11] - 2026-04-15 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(api/public): create_ticket login zorunlu hale getirildi (@ahmeetseker)

### Duzeltildi
- fix(helpdesk): müşteri user'ında HD Team/Agent insert PermissionError → 403 (@ahmeetseker)

---

## [v1.0.4-rc.9] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix: backfill patch'inde nowdatetime import hatası düzeltildi — now_datetime kullanıldı (@ahmeetseker)

---

## [v1.0.4-rc.8] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix(patches): backfill_payment_transactions — Frappe v15 için now_datetime'a çevir (@aliiball)

---

## [v1.0.4-rc.7] - 2026-04-14 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(recommendations): Related Products skor pipeline + API + scheduler (@aliiball)

## [v1.0.4-rc.5] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): Kategori kartlarına editoryal metin + rozet eklendi. (@aliiball)

## [v1.0.4-rc.4] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix: tüm frappe.get_doc(dict) çağrıları frappe.new_doc() ile değiştirildi (@ahmeetseker)

---

## [v1.0.4-rc.2] - 2026-04-13 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(tailored): "Size Özel Seçimler" öneri endpoint'leri + User Product View DocType (@aliiball)

---

## [v1.0.4] - 2026-04-13 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat: Dashboard Banner DocType'ı ve aktif banner API endpoint'i ekle   - Dashboard Banner DocType'ı oluşturuldu (başlık, link, sıralama, aktiflik)   - get_active_banners API endpoint'i eklendi   - Demo veri seed script'i eklendi (seed_demo_data.py) (@ahmeetseker)
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@ahmeetseker)
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@ahmeetseker)
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@aliiball)
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@ahmeetseker)
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@aliiball)
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@aliiball)

## [v1.0.3-rc.19] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix: seed script child table hatası düzeltildi — doc.append() yöntemiyle Frappe uyumluluğu sağlandı (@ahmeetseker)

## [v1.0.3-rc.18] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Degistirildi
- refactor(listing): compare_at_price ve is_on_sale sütunlarını kaldır (@aliiball)

---

## [v1.0.3-rc.17] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: Dashboard Banner DocType'ı ve aktif banner API endpoint'i ekle (@ahmeetseker)

## [v1.0.3-rc.14] - 2026-04-10 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: Tema API'sine rate limit ekle ve palet/tipografi/input token whitelist'ini genişlet (@TurksabYonetim)

## [v1.0.3-rc.13] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: auth yanıtına user_image ekle ve update_profile_image API uç noktasını uygula (@TurksabYonetim)

## [v1.0.3-rc.12] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(search): Kişiselleştirilmiş arama önerileri + Search History + prod optimizasyonu (@TurksabYonetim)

## [v1.0.3-rc.11] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(notification): 2 değişiklik (@boraydeger32)
  - Platform Notification DocType ve notify yardımcısı eklendi
  - API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count)

### Duzeltildi
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@boraydeger32)

---

## [v1.0.3-rc.8] - 2026-04-09 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat:  Güvenli JSON geçersiz kılmaları ve public API erişimiyle site geneli tema ayarları eklendi (@TurksabYonetim)

## [v1.0.3-rc.7] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(notification): API endpoint'leri eklendi (get/mark_read/mark_all_read/unread_count) (@TurksabYonetim)

### Duzeltildi
- fix: add_certification_to_workspace patch link validasyon hatası düzeltildi (@TurksabYonetim)

---

## [v1.0.3-rc.6] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(notification): Platform Notification DocType ve notify yardımcısı eklendi (@TurksabYonetim)

## [v1.0.3-rc.4] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Certification): Sertifika yönetim sistemi — DocType'lar, API, güvenlik ve facets'lar yapıldı (@TurksabYonetim)

## [v1.0.3-rc.3] - 2026-04-08 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(Listing): Arama filtreleri, faceted counts, relevance sort ve performans iyileştirmeleri yapıldı (@TurksabYonetim)

### Duzeltildi
- fix(Listing): Ayrıntılı yanıtta productCategoryId eklendi, breadcrumb kaynağı düzeltildi (@aliiball)

---

## [v1.0.3] - 2026-04-06 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@ahmeetseker)
- feat: update email verification and password reset links to use configurable storefront URL (@ahmeetseker)

### Duzeltildi
- fix: hardcode storefront URL and update reset password link path in identity API (@ahmeetseker)

---

## [v1.0.2-rc.5] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(auth): fix storefront URLs, add email verification redirect and resend endpoint (@TurksabYonetim)

## [v1.0.2-rc.4] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix: hardcode storefront URL and update reset password link path in identity API (@TurksabYonetim)

---

## [v1.0.2-rc.3] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: update email verification and password reset links to use configurable storefront URL (@TurksabYonetim)

## [v1.0.2-rc.2] - 2026-04-06 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(RFQ): Sabit kodlanmış ürünler API çağrılarıyla RFQ sayfasına dinamik şekilde yansıtıldı. (@aliiball)

### Duzeltildi
- fix(Listing): breadcrumb için product_category kullanıldı, aksi takdirde satıcı kategorisine geri dönülmesi sağlandı (@aliiball)

---

## [v1.0.2] - 2026-04-06 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@boraydeger32)
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@boraydeger32)
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@ahmeetseker)

## [v1.0.1-rc.5] - 2026-04-03 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: Sepet öğelerine color_variant ve variant_label desteği eklendi, dinamik görsel çözümleme getirildi ve auth yanıtına CSRF token eklendi (@TurksabYonetim)

## [v1.0.1-rc.4] - 2026-04-03 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Duzeltildi
- fix: revoke_approval ile Seller Profile'ı Suspended yapısı eklendi. (@aliiball)

---

## [v1.0.1-rc.3] - 2026-04-03 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat: Storefront düzeni yönetimini uygulamak, listeleme durumu iş akışını geliştirmek ve sipariş doküman tipini takip bilgileri ile daha ayrıntılı durum alanlarıyla güncellemek. (@TurksabYonetim)

---

## [v1.0.1-rc.2] - 2026-04-02 RC

Bu surum rc.istoc.com'da test asamasindadir.

### Eklendi
- feat(storefront): satıcı vitrin düzeni ve tema ayarları için yeni fonksiyonlar eklendi (@TurksabYonetim)

---
