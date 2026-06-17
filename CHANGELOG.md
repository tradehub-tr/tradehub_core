## [v1.5.3-beta.1] - 2026-06-17 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(seller): üretici kartı için iş bilgisi alanları get_sellers'a eklendi (@ahmeetseker)
  - founded_year, staff_count, annual_revenue, factory_size, business_type, main_markets alanları storefront kart istatistik/servis satırı için döndürülüyor
  - v15_8_6 patch'i: Custom DocPerm'i olan tüm tradehub_core doctype'larında satıcıya permlevel>0 read tanımlıysa permlevel-0 read+write (if_owner) ekler
  - "Seller" ve "Marketplace Seller" rolleri birlikte eklenir, rol şeması geçişine dayanıklı; PII permlevel 1/2/3 satırlarına dokunulmaz; idempotent

---
## [v1.5.3] - 2026-06-16 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Duzeltildi
- fix(tenant): counterparty doctype'lar seller izolasyon hook'undan muaf tutuldu (@ahmeetseker)
  - Order/Order Dispute/Seller Review/Listing Review/Seller Inquiry için seller field'ı sahiplik değil karşı taraf referansı; enforce/validate hook'ları COUNTERPARTY_SELLER_DOCTYPES seti ile erken return yapıyor
  - Satıcı sıfatı da olan kullanıcı başka satıcıdan alışveriş yaptığında oluşan hatalı cross-tenant reddi giderildi; izolasyon zaten query_conditions + has_permission + API buyer==session.user katmanında sağlanıyor
- fix(rbac): Seller Owner rolüne KYB/KYC erişim izni eklendi (@aliiball)
  - Panelde KYB/KYC Doğrulama açılırken alınan 403 "does not have doctype access via role permission" hatası düzeltildi
  - v15_8_1/v15_8_2 kapsamı dışında kalan KYB/KYC Verification için Seller Owner'a permlevel-0 read/write Custom DocPerm ekleyen v15_8_3 patch'i eklendi
  - Tenant izolasyonu has_permission + query_conditions hook'larıyla korunuyor (if_owner=0; satıcı yalnızca kendi kaydına erişir)
- fix(kyb): belge yüklenmeden "Beklemede" görünmesi düzeltildi (@aliiball)
  - KYB Verification'a "Draft" başlangıç durumu eklendi; auto-create noktaları (onay akışı, get_kyb_status, belge upload) artık Pending yerine Draft yaratıyor
  - Gerçek başvuru yalnızca tüm zorunlu belgeler yüklenip gönderilince (submit_kyb_documents: Draft→Pending) oluşuyor; admin'e bildirim de artık sadece bu noktada gidiyor
  - Draft durumunda satış kapalı (can_sell=0)
  - v15_8_4 patch: belgesiz mevcut "Pending" kayıtları "Draft"a taşıyor
- fix(kyb): doğrulanmış satıcının rolü kalıcı eklenmiyordu düzeltildi (@aliiball)
  - role_profile_name="Seller Full Access" User.save'de rolleri resetleyip "Verified Seller"ı sildiği için KYB Verified satıcılar storefront'ta "doğrulanmadı" görünüyordu
  - _sync_verified_seller_role artık Has Role'u doğrudan yönetiyor (add_roles değil); User on_update kalkanı rolü silinmeye karşı koruyor
  - v15_8_5 patch: tüm Verified satıcılara rolü doğrudan ekleyerek mevcut bozuk kayıtları iyileştirir
- fix(order): sipariş oluşturmada olmayan tradehub_buyer_tenant kolonu 500 hatası düzeltildi (@aliiball)
  - _resolve_buyer_tenant / _buyer_tenant_for_user döngüleri olmayan kolona get_value çağırıp MariaDB 1054 fırlatıyordu; has_column guard ile olmayan alan atlanıp var olan tradehub_tenant'a düşülüyor
  - supplier_whitelist.py, cost_center.py, permissions.py
- fix(listing): b2b fiyat aralığında hardcoded $ yerine listing para birimi kullanıldı (@aliiball)
  - _get_price_range ve _format_listing_card b2b dalı listing.currency'yi yok sayıp sabit $ basıyordu; _format_price(..., currency) ile düzeltildi
- fix(rbac): mağaza sahiplerine Marketplace Seller temel rolünü ver (@boraydeger32)
  - Marketplace Seller'ı "Seller Full Access" Role Profile'ına ekler (kalıcı kaynak; profil _PROTECTED_ROLE_PROFILES'ta olduğu için UI'dan silinemez)
  - Mevcut owner user'lara Has Role'u doğrudan ekler (User save etmeden → desk_access rolü user_type'ı System User'a çevirmez; seed _grant_verified_seller_role deseni)

### Degistirildi
- refactor(seller): listing currency fallback default'u USD'ye hizalandı (@aliiball)

---
## [v1.5.2-rc.1] - 2026-06-16 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Duzeltildi
- fix(tenant): counterparty doctype'lar seller izolasyon hook'undan muaf tutuldu (@ahmeetseker)
  - Order/Order Dispute/Seller Review/Listing Review/Seller Inquiry için seller field'ı sahiplik değil karşı taraf referansı; enforce/validate hook'ları COUNTERPARTY_SELLER_DOCTYPES seti ile erken return yapıyor
  - Satıcı sıfatı da olan kullanıcı başka satıcıdan alışveriş yaptığında oluşan hatalı cross-tenant reddi giderildi; izolasyon zaten query_conditions + has_permission + API buyer==session.user katmanında sağlanıyor
- fix(rbac): Seller Owner rolüne KYB/KYC erişim izni eklendi (@aliiball)
  - Panelde KYB/KYC Doğrulama açılırken alınan 403 "does not have doctype access via role permission" hatası düzeltildi
  - v15_8_1/v15_8_2 kapsamı dışında kalan KYB/KYC Verification için Seller Owner'a permlevel-0 read/write Custom DocPerm ekleyen v15_8_3 patch'i eklendi
  - Tenant izolasyonu has_permission + query_conditions hook'larıyla korunuyor (if_owner=0; satıcı yalnızca kendi kaydına erişir)
- fix(kyb): belge yüklenmeden "Beklemede" görünmesi düzeltildi (@aliiball)
  - KYB Verification'a "Draft" başlangıç durumu eklendi; auto-create noktaları (onay akışı, get_kyb_status, belge upload) artık Pending yerine Draft yaratıyor
  - Gerçek başvuru yalnızca tüm zorunlu belgeler yüklenip gönderilince (submit_kyb_documents: Draft→Pending) oluşuyor; admin'e bildirim de artık sadece bu noktada gidiyor
  - Draft durumunda satış kapalı (can_sell=0)
  - v15_8_4 patch: belgesiz mevcut "Pending" kayıtları "Draft"a taşıyor
- fix(kyb): doğrulanmış satıcının rolü kalıcı eklenmiyordu düzeltildi (@aliiball)
  - role_profile_name="Seller Full Access" User.save'de rolleri resetleyip "Verified Seller"ı sildiği için KYB Verified satıcılar storefront'ta "doğrulanmadı" görünüyordu
  - _sync_verified_seller_role artık Has Role'u doğrudan yönetiyor (add_roles değil); User on_update kalkanı rolü silinmeye karşı koruyor
  - v15_8_5 patch: tüm Verified satıcılara rolü doğrudan ekleyerek mevcut bozuk kayıtları iyileştirir
- fix(order): sipariş oluşturmada olmayan tradehub_buyer_tenant kolonu 500 hatası düzeltildi (@aliiball)
  - _resolve_buyer_tenant / _buyer_tenant_for_user döngüleri olmayan kolona get_value çağırıp MariaDB 1054 fırlatıyordu; has_column guard ile olmayan alan atlanıp var olan tradehub_tenant'a düşülüyor
  - supplier_whitelist.py, cost_center.py, permissions.py
- fix(listing): b2b fiyat aralığında hardcoded $ yerine listing para birimi kullanıldı (@aliiball)
  - _get_price_range ve _format_listing_card b2b dalı listing.currency'yi yok sayıp sabit $ basıyordu; _format_price(..., currency) ile düzeltildi
- fix(rbac): mağaza sahiplerine Marketplace Seller temel rolünü ver (@boraydeger32)
  - Marketplace Seller'ı "Seller Full Access" Role Profile'ına ekler (kalıcı kaynak; profil _PROTECTED_ROLE_PROFILES'ta olduğu için UI'dan silinemez)
  - Mevcut owner user'lara Has Role'u doğrudan ekler (User save etmeden → desk_access rolü user_type'ı System User'a çevirmez; seed _grant_verified_seller_role deseni)

### Degistirildi
- refactor(seller): listing currency fallback default'u USD'ye hizalandı (@aliiball)

---
## [v1.5.2-beta.3] - 2026-06-16 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(rbac): mağaza sahiplerine Marketplace Seller temel rolünü ver (@boraydeger32)
  - Marketplace Seller'ı "Seller Full Access" Role Profile'ına ekler (kalıcı kaynak; profil _PROTECTED_ROLE_PROFILES'ta olduğu için UI'dan silinemez)
  - Mevcut owner user'lara Has Role'u doğrudan ekler (User save etmeden → desk_access rolü user_type'ı System User'a çevirmez; seed _grant_verified_seller_role deseni)

---
## [v1.5.2-beta.2] - 2026-06-16 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(rbac): Seller Owner rolüne KYB/KYC erişim izni eklendi (@aliiball)
  - Panelde KYB/KYC Doğrulama açılırken alınan 403 "does not have doctype access via role permission" hatası düzeltildi
  - v15_8_1/v15_8_2 kapsamı dışında kalan KYB/KYC Verification için Seller Owner'a permlevel-0 read/write Custom DocPerm ekleyen v15_8_3 patch'i eklendi
  - Tenant izolasyonu has_permission + query_conditions hook'larıyla korunuyor (if_owner=0; satıcı yalnızca kendi kaydına erişir)
- fix(kyb): belge yüklenmeden "Beklemede" görünmesi düzeltildi (@aliiball)
  - KYB Verification'a "Draft" başlangıç durumu eklendi; auto-create noktaları (onay akışı, get_kyb_status, belge upload) artık Pending yerine Draft yaratıyor
  - Gerçek başvuru yalnızca tüm zorunlu belgeler yüklenip gönderilince (submit_kyb_documents: Draft→Pending) oluşuyor; admin'e bildirim de artık sadece bu noktada gidiyor
  - Draft durumunda satış kapalı (can_sell=0)
  - v15_8_4 patch: belgesiz mevcut "Pending" kayıtları "Draft"a taşıyor
- fix(kyb): doğrulanmış satıcının rolü kalıcı eklenmiyordu düzeltildi (@aliiball)
  - role_profile_name="Seller Full Access" User.save'de rolleri resetleyip "Verified Seller"ı sildiği için KYB Verified satıcılar storefront'ta "doğrulanmadı" görünüyordu
  - _sync_verified_seller_role artık Has Role'u doğrudan yönetiyor (add_roles değil); User on_update kalkanı rolü silinmeye karşı koruyor
  - v15_8_5 patch: tüm Verified satıcılara rolü doğrudan ekleyerek mevcut bozuk kayıtları iyileştirir
- fix(order): sipariş oluşturmada olmayan tradehub_buyer_tenant kolonu 500 hatası düzeltildi (@aliiball)
  - _resolve_buyer_tenant / _buyer_tenant_for_user döngüleri olmayan kolona get_value çağırıp MariaDB 1054 fırlatıyordu; has_column guard ile olmayan alan atlanıp var olan tradehub_tenant'a düşülüyor
  - supplier_whitelist.py, cost_center.py, permissions.py
- fix(listing): b2b fiyat aralığında hardcoded $ yerine listing para birimi kullanıldı (@aliiball)
  - _get_price_range ve _format_listing_card b2b dalı listing.currency'yi yok sayıp sabit $ basıyordu; _format_price(..., currency) ile düzeltildi

### Degistirildi
- refactor(seller): listing currency fallback default'u USD'ye hizalandı (@aliiball)

---
## [v1.5.2-beta.1] - 2026-06-15 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(tenant): counterparty doctype'lar seller izolasyon hook'undan muaf tutuldu (@ahmeetseker)
  - Order/Order Dispute/Seller Review/Listing Review/Seller Inquiry için seller field'ı sahiplik değil karşı taraf referansı; enforce/validate hook'ları COUNTERPARTY_SELLER_DOCTYPES seti ile erken return yapıyor
  - Satıcı sıfatı da olan kullanıcı başka satıcıdan alışveriş yaptığında oluşan hatalı cross-tenant reddi giderildi; izolasyon zaten query_conditions + has_permission + API buyer==session.user katmanında sağlanıyor

---
## [v1.5.2] - 2026-06-15 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Duzeltildi
- fix(perm): Seller Owner mağaza profili yazma izni geri verildi (@ahmeetseker)
  - Admin Seller Profile Custom DocPerm'inde Seller Owner permlevel-0 satırı eksikti; satıcı kendi profilini okuyabiliyor ama kaydedemiyordu ("does not have doctype access via role permission" 403)
  - v15_8_1_seller_owner_asp_docperm patch'i permlevel-0 read/write ekler (if_owner=0; izolasyonu admin_seller_profile_has_permission hook sağlar)
  - v15_5_1 RBAC reseed regresyonu; Listing (v15_7_1) ve KYB/KYC (v15_7_6) düzeltilmişti, Admin Seller Profile atlanmıştı
- fix(perm): Seller Owner kardeş satıcı-doctype read izinleri geri verildi (@ahmeetseker)
  - Order/Seller Balance/Seller Review/Seller Inquiry/Listing Review permlevel-0 read (v15_8_2 patch); alt-rol union ayna alındı
  - 5 doctype'ta da permission_query_conditions + has_permission tenant hook'u var → satıcı yalnız kendi kayıtlarını görür (izolasyon korunur)
  - v15_5_1 RBAC reseed regresyonu; Seller Owner sistemik atlanmıştı (Admin Seller Profile v15_8_1, Listing v15_7_1, KYB/KYC v15_7_6)

---
## [v1.5.1-rc.1] - 2026-06-15 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Duzeltildi
- fix(perm): Seller Owner mağaza profili yazma izni geri verildi (@ahmeetseker)
  - Admin Seller Profile Custom DocPerm'inde Seller Owner permlevel-0 satırı eksikti; satıcı kendi profilini okuyabiliyor ama kaydedemiyordu ("does not have doctype access via role permission" 403)
  - v15_8_1_seller_owner_asp_docperm patch'i permlevel-0 read/write ekler (if_owner=0; izolasyonu admin_seller_profile_has_permission hook sağlar)
  - v15_5_1 RBAC reseed regresyonu; Listing (v15_7_1) ve KYB/KYC (v15_7_6) düzeltilmişti, Admin Seller Profile atlanmıştı
- fix(perm): Seller Owner kardeş satıcı-doctype read izinleri geri verildi (@ahmeetseker)
  - Order/Seller Balance/Seller Review/Seller Inquiry/Listing Review permlevel-0 read (v15_8_2 patch); alt-rol union ayna alındı
  - 5 doctype'ta da permission_query_conditions + has_permission tenant hook'u var → satıcı yalnız kendi kayıtlarını görür (izolasyon korunur)
  - v15_5_1 RBAC reseed regresyonu; Seller Owner sistemik atlanmıştı (Admin Seller Profile v15_8_1, Listing v15_7_1, KYB/KYC v15_7_6)

---
## [v1.5.1-beta.2] - 2026-06-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(perm): Seller Owner kardeş satıcı-doctype read izinleri geri verildi (@ahmeetseker)
  - Order/Seller Balance/Seller Review/Seller Inquiry/Listing Review permlevel-0 read (v15_8_2 patch); alt-rol union ayna alındı
  - 5 doctype'ta da permission_query_conditions + has_permission tenant hook'u var → satıcı yalnız kendi kayıtlarını görür (izolasyon korunur)
  - v15_5_1 RBAC reseed regresyonu; Seller Owner sistemik atlanmıştı (Admin Seller Profile v15_8_1, Listing v15_7_1, KYB/KYC v15_7_6)

---
## [v1.5.1-beta.1] - 2026-06-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(perm): Seller Owner mağaza profili yazma izni geri verildi (@ahmeetseker)
  - Admin Seller Profile Custom DocPerm'inde Seller Owner permlevel-0 satırı eksikti; satıcı kendi profilini okuyabiliyor ama kaydedemiyordu ("does not have doctype access via role permission" 403)
  - v15_8_1_seller_owner_asp_docperm patch'i permlevel-0 read/write ekler (if_owner=0; izolasyonu admin_seller_profile_has_permission hook sağlar)
  - v15_5_1 RBAC reseed regresyonu; Listing (v15_7_1) ve KYB/KYC (v15_7_6) düzeltilmişti, Admin Seller Profile atlanmıştı

---
## [v1.5.1] - 2026-06-12 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(pricing): komisyon "Özel" ayrımı — commission_is_custom alanı (@boraydeger32)
  - Subscription Plan: commission_is_custom (Check) — admin komisyonu boş bıraktıysa 1; DB kolonu NOT NULL olduğundan 0'dan ayırt etmek için şart
  - public_pricing: payload'a commission_custom eklendi; matris hücresi artık "boş → Özel, sayı → %X (0 dahil)" (önceden 0 da Özel sayılıyordu)
  - permission_console: yeni alan display whitelist + finansal alan (SM-only) listesinde; create/update/full_detail endpoint'leri taşıyor
  - Deploy notu: prod'da bench migrate gerekli (yeni kolon)

---
## [v1.5.0-rc.1] - 2026-06-12 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(pricing): komisyon "Özel" ayrımı — commission_is_custom alanı (@boraydeger32)
  - Subscription Plan: commission_is_custom (Check) — admin komisyonu boş bıraktıysa 1; DB kolonu NOT NULL olduğundan 0'dan ayırt etmek için şart
  - public_pricing: payload'a commission_custom eklendi; matris hücresi artık "boş → Özel, sayı → %X (0 dahil)" (önceden 0 da Özel sayılıyordu)
  - permission_console: yeni alan display whitelist + finansal alan (SM-only) listesinde; create/update/full_detail endpoint'leri taşıyor
  - Deploy notu: prod'da bench migrate gerekli (yeni kolon)

---
## [v1.5.0-beta.1] - 2026-06-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(pricing): komisyon "Özel" ayrımı — commission_is_custom alanı (@boraydeger32)
  - Subscription Plan: commission_is_custom (Check) — admin komisyonu boş bıraktıysa 1; DB kolonu NOT NULL olduğundan 0'dan ayırt etmek için şart
  - public_pricing: payload'a commission_custom eklendi; matris hücresi artık "boş → Özel, sayı → %X (0 dahil)" (önceden 0 da Özel sayılıyordu)
  - permission_console: yeni alan display whitelist + finansal alan (SM-only) listesinde; create/update/full_detail endpoint'leri taşıyor
  - Deploy notu: prod'da bench migrate gerekli (yeni kolon)

---
## [v1.5.0] - 2026-06-12 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(bulk-import): interaktif yetim-görsel atama (önizleme + override) (@aliiball)
- feat(seed): demo satıcı sayısı 16'ya çıkarıldı ve after_migrate idempotent seed eklendi (@ahmeetseker)
  - DEMO-011..016 eklendi (Şeker Tekstil, Bal Gıda, Aydeğer Elektronik, Anadolu Ayakkabı, Lale Kozmetik, Marmara Ev Tekstili)
  - run_idempotent_seed after_migrate hook'una bağlandı; site_config.demo_seed_enabled bayrağıyla çalışır
  - _seed(cleanup_first) ile manuel reset / otomatik idempotent path ayrıldı
  - _create_listing ve _ensure_seller idempotent hale getirildi (rename ile gerçek hesabı demo'ya dönüştürme)
  - gerçek ekip e-postaları (ahmet.seker/ali.bal/bora.aydeger) cleanup'ta korunuyor, User silinmez
  - demo şifresi Turksab2026! olarak güncellendi

### Duzeltildi
- fix(bulk-import): satıcı profili owner yerine kanonik resolver ile çözülüyor (@aliiball)
  - api.py (6 yer) ve feed_api.py owner lookup'ları get_current_seller_profile() (utils/tenant) ile değiştirildi — user/email/tradehub_tenant kaskadı
  - tradehub_tenant ile davet edilen alt-kullanıcılar (Co-Owner, Finance Staff) artık ortak mağazaya toplu yükleme yapabiliyor
  - regex_lib.py zaten kanonik resolver kullanıyordu, dokunulmadı

### Degistirildi
- refactor(auth): kayıt ve re-verify OTP süresi 30 dakikaya çıkarıldı (@aliiball)
  - registration_otp ve reverify_otp cache TTL 600s → 1800s
  - yanlış denemede TTL reset değerleri de 1800s'e hizalandı (süre kısalma hatası önlendi)
  - send/resend dönüş değeri expires_in_minutes 10 → 30
  - OTP e-posta şablonundaki geçerlilik metni 30 dakika olarak güncellendi
- refactor(ci): lint workflow PR tetiği kaldırıldı (@ahmeetseker)
  - pull_request trigger silindi; lint artık sadece push'ta çalışır

---
## [v1.4.1-rc.1] - 2026-06-12 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(bulk-import): interaktif yetim-görsel atama (önizleme + override) (@aliiball)
- feat(seed): demo satıcı sayısı 16'ya çıkarıldı ve after_migrate idempotent seed eklendi (@ahmeetseker)
  - DEMO-011..016 eklendi (Şeker Tekstil, Bal Gıda, Aydeğer Elektronik, Anadolu Ayakkabı, Lale Kozmetik, Marmara Ev Tekstili)
  - run_idempotent_seed after_migrate hook'una bağlandı; site_config.demo_seed_enabled bayrağıyla çalışır
  - _seed(cleanup_first) ile manuel reset / otomatik idempotent path ayrıldı
  - _create_listing ve _ensure_seller idempotent hale getirildi (rename ile gerçek hesabı demo'ya dönüştürme)
  - gerçek ekip e-postaları (ahmet.seker/ali.bal/bora.aydeger) cleanup'ta korunuyor, User silinmez
  - demo şifresi Turksab2026! olarak güncellendi

### Duzeltildi
- fix(bulk-import): satıcı profili owner yerine kanonik resolver ile çözülüyor (@aliiball)
  - api.py (6 yer) ve feed_api.py owner lookup'ları get_current_seller_profile() (utils/tenant) ile değiştirildi — user/email/tradehub_tenant kaskadı
  - tradehub_tenant ile davet edilen alt-kullanıcılar (Co-Owner, Finance Staff) artık ortak mağazaya toplu yükleme yapabiliyor
  - regex_lib.py zaten kanonik resolver kullanıyordu, dokunulmadı

### Degistirildi
- refactor(auth): kayıt ve re-verify OTP süresi 30 dakikaya çıkarıldı (@aliiball)
  - registration_otp ve reverify_otp cache TTL 600s → 1800s
  - yanlış denemede TTL reset değerleri de 1800s'e hizalandı (süre kısalma hatası önlendi)
  - send/resend dönüş değeri expires_in_minutes 10 → 30
  - OTP e-posta şablonundaki geçerlilik metni 30 dakika olarak güncellendi
- refactor(ci): lint workflow PR tetiği kaldırıldı (@ahmeetseker)
  - pull_request trigger silindi; lint artık sadece push'ta çalışır

---
## [v1.4.1-beta.3] - 2026-06-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(seed): demo satıcı sayısı 16'ya çıkarıldı ve after_migrate idempotent seed eklendi (@ahmeetseker)
  - DEMO-011..016 eklendi (Şeker Tekstil, Bal Gıda, Aydeğer Elektronik, Anadolu Ayakkabı, Lale Kozmetik, Marmara Ev Tekstili)
  - run_idempotent_seed after_migrate hook'una bağlandı; site_config.demo_seed_enabled bayrağıyla çalışır
  - _seed(cleanup_first) ile manuel reset / otomatik idempotent path ayrıldı
  - _create_listing ve _ensure_seller idempotent hale getirildi (rename ile gerçek hesabı demo'ya dönüştürme)
  - gerçek ekip e-postaları (ahmet.seker/ali.bal/bora.aydeger) cleanup'ta korunuyor, User silinmez
  - demo şifresi Turksab2026! olarak güncellendi

### Degistirildi
- refactor(ci): lint workflow PR tetiği kaldırıldı (@ahmeetseker)
  - pull_request trigger silindi; lint artık sadece push'ta çalışır

---
## [v1.4.1-beta.1] - 2026-06-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(bulk-import): interaktif yetim-görsel atama (önizleme + override) (@aliiball)

### Duzeltildi
- fix(bulk-import): satıcı profili owner yerine kanonik resolver ile çözülüyor (@aliiball)
  - api.py (6 yer) ve feed_api.py owner lookup'ları get_current_seller_profile() (utils/tenant) ile değiştirildi — user/email/tradehub_tenant kaskadı
  - tradehub_tenant ile davet edilen alt-kullanıcılar (Co-Owner, Finance Staff) artık ortak mağazaya toplu yükleme yapabiliyor
  - regex_lib.py zaten kanonik resolver kullanıyordu, dokunulmadı

### Degistirildi
- refactor(auth): kayıt ve re-verify OTP süresi 30 dakikaya çıkarıldı (@aliiball)
  - registration_otp ve reverify_otp cache TTL 600s → 1800s
  - yanlış denemede TTL reset değerleri de 1800s'e hizalandı (süre kısalma hatası önlendi)
  - send/resend dönüş değeri expires_in_minutes 10 → 30
  - OTP e-posta şablonundaki geçerlilik metni 30 dakika olarak güncellendi

---
## [v1.4.1] - 2026-06-12 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Duzeltildi
- fix(security): tenant izolasyonu, IDOR/BOLA ve yetki sertleştirmesi (@boraydeger32)
  - procurement: `_resolve_tenant_arg` ile `tenant` parametresi cross-tenant baypası kapatıldı; mevcut kayıtta sahiplik kontrolü
  - seller.list_my_inquiries: get_all -> seller filtreli sorgu (cross-tenant sızıntı)
  - Store Subscription: permission_query_conditions + has_permission + DocType'tan seller `write` izni kaldırıldı (ödemesiz plan yükseltme)
  - subscription.upgrade_subscription_plan: ücretli aktivasyon admin/ödeme koşulu
  - delegation: power-role blocklist + delegator rol doğrulaması
  - buyer_team: rol profili allowlist (davet + güncelleme)
  - owner_transfer: reject/request_transfer için owner/admin guard
  - review.submit_listing_review, ab_testing.get_ab_test_report, review.get_order_item_listing, listing.get_completeness_breakdown, reputation.get_invitation_list, compliance.get_field_policies: sahiplik/rol kontrolü
  - payment.verify_supplier_account: banka PII enumerasyonu -> yalnız boolean
  - seller.get_customer_detail: ilişki kapısı + ticket sızıntısı düzeltildi
  - cart.create_order: kupon indirimi ve kargo server-side (client manipülasyonu)
  - mobile_api: hardcoded JWT fallback secret kaldırıldı (fail-closed)
  - identity.upload_private_file: 5MB cap; social_proof/seller: rate-limit
  - bulk_import + seller_certifications: dosyalar private; chat: uzantı allowlist
  - payment.export_transactions: sayfa limiti

---
## [v1.4.0-rc.1] - 2026-06-12 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Duzeltildi
- fix(security): tenant izolasyonu, IDOR/BOLA ve yetki sertleştirmesi (@boraydeger32)
  - procurement: `_resolve_tenant_arg` ile `tenant` parametresi cross-tenant baypası kapatıldı; mevcut kayıtta sahiplik kontrolü
  - seller.list_my_inquiries: get_all -> seller filtreli sorgu (cross-tenant sızıntı)
  - Store Subscription: permission_query_conditions + has_permission + DocType'tan seller `write` izni kaldırıldı (ödemesiz plan yükseltme)
  - subscription.upgrade_subscription_plan: ücretli aktivasyon admin/ödeme koşulu
  - delegation: power-role blocklist + delegator rol doğrulaması
  - buyer_team: rol profili allowlist (davet + güncelleme)
  - owner_transfer: reject/request_transfer için owner/admin guard
  - review.submit_listing_review, ab_testing.get_ab_test_report, review.get_order_item_listing, listing.get_completeness_breakdown, reputation.get_invitation_list, compliance.get_field_policies: sahiplik/rol kontrolü
  - payment.verify_supplier_account: banka PII enumerasyonu -> yalnız boolean
  - seller.get_customer_detail: ilişki kapısı + ticket sızıntısı düzeltildi
  - cart.create_order: kupon indirimi ve kargo server-side (client manipülasyonu)
  - mobile_api: hardcoded JWT fallback secret kaldırıldı (fail-closed)
  - identity.upload_private_file: 5MB cap; social_proof/seller: rate-limit
  - bulk_import + seller_certifications: dosyalar private; chat: uzantı allowlist
  - payment.export_transactions: sayfa limiti

---
## [v1.4.0-beta.1] - 2026-06-12 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(security): tenant izolasyonu, IDOR/BOLA ve yetki sertleştirmesi (@boraydeger32)
  - procurement: `_resolve_tenant_arg` ile `tenant` parametresi cross-tenant baypası kapatıldı; mevcut kayıtta sahiplik kontrolü
  - seller.list_my_inquiries: get_all -> seller filtreli sorgu (cross-tenant sızıntı)
  - Store Subscription: permission_query_conditions + has_permission + DocType'tan seller `write` izni kaldırıldı (ödemesiz plan yükseltme)
  - subscription.upgrade_subscription_plan: ücretli aktivasyon admin/ödeme koşulu
  - delegation: power-role blocklist + delegator rol doğrulaması
  - buyer_team: rol profili allowlist (davet + güncelleme)
  - owner_transfer: reject/request_transfer için owner/admin guard
  - review.submit_listing_review, ab_testing.get_ab_test_report, review.get_order_item_listing, listing.get_completeness_breakdown, reputation.get_invitation_list, compliance.get_field_policies: sahiplik/rol kontrolü
  - payment.verify_supplier_account: banka PII enumerasyonu -> yalnız boolean
  - seller.get_customer_detail: ilişki kapısı + ticket sızıntısı düzeltildi
  - cart.create_order: kupon indirimi ve kargo server-side (client manipülasyonu)
  - mobile_api: hardcoded JWT fallback secret kaldırıldı (fail-closed)
  - identity.upload_private_file: 5MB cap; social_proof/seller: rate-limit
  - bulk_import + seller_certifications: dosyalar private; chat: uzantı allowlist
  - payment.export_transactions: sayfa limiti

---
## [v1.4.0] - 2026-06-11 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(bulk-import): kolon eşleştirme dayanıklılığı eklendi (@aliiball)
  - Kolon eşleştirmede ilk-gelen-kapar yerine skorlu arbitrasyon (en yüksek skor kazanır); kaybeden başlıklar conflicts olarak raporlanır
  - Semantic eşleştirmeye Türkçe-fold eklendi (BİRİM/İ/Ş gibi başlıklar ASCII alias'larla doğru eşleşir)
  - 15 eksik canonical alan alias'ı eklendi (stock_uom/currency/condition/kargo vb.); 'birim' artık stock_uom'a gider, fiyatı çalmaz
  - Çoklu görsel kolonu için primary_image + image_2..N slot ataması
  - validate_mapping ile fiyat/SKU/ad sütunu eşleşmezse ham MandatoryError yerine anlaşılır hata
- feat(bulk-import): derin görsel eşleştirme ve optimizasyon eklendi (@aliiball)
  - SKU anahtarları normalize edilir (büyük/küçük + Türkçe-fold); klasör galerisi doğal/sayısal sıralanır
  - ZIP içeriği magic-number ile doğrulanır; eşleşmeyen dosyalar yetim olarak raporlanır
  - Satıcıya özel 'SKU Filename' desenleri görsel eşleştirmede fallback olarak tüketilir
  - Yüklenen görseller web boyutuna küçültülür + yeniden sıkıştırılır (1600px, format korunur, başarısızsa orijinal); ZIP ve URL
- feat(bulk-import): import akışı orkestrasyonu güçlendirildi (@aliiball)
  - Onaylanan eşleştirme satıcı profili olarak öğrenilir (xlsx/csv); aynı başlıklı sonraki dosyalar otomatik eşlenir
  - Sniffer ile xlsx başlık satırı ve ana sayfa otomatik tespiti (dry_run önizlemeye taşınır)
  - Mapping ön-kontrolü: zorunlu sütun eşleşmezse tek anlaşılır hatayla erken durdurma
  - Görsel eşleştiriciye gerçek ürün SKU listesi (known_skus) geçirilir
  - ECA reject satırları yakalanıp eca_rejected olarak skip raporlanır
  - Ham MandatoryError anlaşılır mesaja çevrilir; hata kayıtlarına ilgili alan + önem derecesi yazılır; yetim görsel özeti eklenir
  - dry_run çıktısına conflicts/detected alanları, şablona görsel kolonları, görsel limiti 50 MB, get_import_status'a severity/field
- feat(bulk-import): DocType alanları ve migration'lar eklendi (@aliiball)
  - Bulk Import Job'a remember_mapping (Check) alanı
  - Bulk Import Job Error.error_type'a eca_rejected seçeneği; error'a field + severity alanları
  - İlgili idempotent reload-doc migration'ları (v15_7_7/8/9) ve patches.txt kayıtları
- feat(eca): süper admin kural sihirbazı + governance + ağaç/arama değer seçici (@aliiball)
  - admin şema 12 eylem + canlı sayım + dry-run önizleme (persist yok)
  - governance: çakışma uyarısı, versiyon geçmişi/geri-al, örnek üründe test
  - create_document tıklama-bazlı (kayıt türü dropdown + alan eşleyici; "DocType"/JSON yok)
  - kategori değeri için link_tree_roots/children/search (path'li, 11k düz dump yerine)
  - satıcı çağrıları regresyonsuz (5 eylem korunur)
- feat(bulk-import): xlsx ham satır okuyucu eklendi (sniffer başlık/sayfa tespiti) (@aliiball)
  - read_raw(): başlık satırı ve ana sayfa tespiti için tüm dosyayı belleğe almadan ilk N ham satırı döndürür (sniffer.find_header_row / pick_main_sheet ile kullanılır)

### Duzeltildi
- fix(eca): reject_row toplu yüklemede satır atlamaya bağlandı (@aliiball)
  - reject_row aksiyonu flag set ediyordu ama hiçbir yer okumuyordu; artık validate fazında ECARejectionError fırlatılır ve insert DB yazımından önce iptal edilir
  - Yalnız validate/before_save/before_insert event'lerinde fırlatılır (after_insert/on_update'te orphan kayıt koruması)

---
## [v1.3.2-rc.1] - 2026-06-11 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(bulk-import): kolon eşleştirme dayanıklılığı eklendi (@aliiball)
  - Kolon eşleştirmede ilk-gelen-kapar yerine skorlu arbitrasyon (en yüksek skor kazanır); kaybeden başlıklar conflicts olarak raporlanır
  - Semantic eşleştirmeye Türkçe-fold eklendi (BİRİM/İ/Ş gibi başlıklar ASCII alias'larla doğru eşleşir)
  - 15 eksik canonical alan alias'ı eklendi (stock_uom/currency/condition/kargo vb.); 'birim' artık stock_uom'a gider, fiyatı çalmaz
  - Çoklu görsel kolonu için primary_image + image_2..N slot ataması
  - validate_mapping ile fiyat/SKU/ad sütunu eşleşmezse ham MandatoryError yerine anlaşılır hata
- feat(bulk-import): derin görsel eşleştirme ve optimizasyon eklendi (@aliiball)
  - SKU anahtarları normalize edilir (büyük/küçük + Türkçe-fold); klasör galerisi doğal/sayısal sıralanır
  - ZIP içeriği magic-number ile doğrulanır; eşleşmeyen dosyalar yetim olarak raporlanır
  - Satıcıya özel 'SKU Filename' desenleri görsel eşleştirmede fallback olarak tüketilir
  - Yüklenen görseller web boyutuna küçültülür + yeniden sıkıştırılır (1600px, format korunur, başarısızsa orijinal); ZIP ve URL
- feat(bulk-import): import akışı orkestrasyonu güçlendirildi (@aliiball)
  - Onaylanan eşleştirme satıcı profili olarak öğrenilir (xlsx/csv); aynı başlıklı sonraki dosyalar otomatik eşlenir
  - Sniffer ile xlsx başlık satırı ve ana sayfa otomatik tespiti (dry_run önizlemeye taşınır)
  - Mapping ön-kontrolü: zorunlu sütun eşleşmezse tek anlaşılır hatayla erken durdurma
  - Görsel eşleştiriciye gerçek ürün SKU listesi (known_skus) geçirilir
  - ECA reject satırları yakalanıp eca_rejected olarak skip raporlanır
  - Ham MandatoryError anlaşılır mesaja çevrilir; hata kayıtlarına ilgili alan + önem derecesi yazılır; yetim görsel özeti eklenir
  - dry_run çıktısına conflicts/detected alanları, şablona görsel kolonları, görsel limiti 50 MB, get_import_status'a severity/field
- feat(bulk-import): DocType alanları ve migration'lar eklendi (@aliiball)
  - Bulk Import Job'a remember_mapping (Check) alanı
  - Bulk Import Job Error.error_type'a eca_rejected seçeneği; error'a field + severity alanları
  - İlgili idempotent reload-doc migration'ları (v15_7_7/8/9) ve patches.txt kayıtları
- feat(eca): süper admin kural sihirbazı + governance + ağaç/arama değer seçici (@aliiball)
  - admin şema 12 eylem + canlı sayım + dry-run önizleme (persist yok)
  - governance: çakışma uyarısı, versiyon geçmişi/geri-al, örnek üründe test
  - create_document tıklama-bazlı (kayıt türü dropdown + alan eşleyici; "DocType"/JSON yok)
  - kategori değeri için link_tree_roots/children/search (path'li, 11k düz dump yerine)
  - satıcı çağrıları regresyonsuz (5 eylem korunur)
- feat(bulk-import): xlsx ham satır okuyucu eklendi (sniffer başlık/sayfa tespiti) (@aliiball)
  - read_raw(): başlık satırı ve ana sayfa tespiti için tüm dosyayı belleğe almadan ilk N ham satırı döndürür (sniffer.find_header_row / pick_main_sheet ile kullanılır)

### Duzeltildi
- fix(eca): reject_row toplu yüklemede satır atlamaya bağlandı (@aliiball)
  - reject_row aksiyonu flag set ediyordu ama hiçbir yer okumuyordu; artık validate fazında ECARejectionError fırlatılır ve insert DB yazımından önce iptal edilir
  - Yalnız validate/before_save/before_insert event'lerinde fırlatılır (after_insert/on_update'te orphan kayıt koruması)

---
## [v1.3.2-beta.1] - 2026-06-11 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(bulk-import): kolon eşleştirme dayanıklılığı eklendi (@aliiball)
  - Kolon eşleştirmede ilk-gelen-kapar yerine skorlu arbitrasyon (en yüksek skor kazanır); kaybeden başlıklar conflicts olarak raporlanır
  - Semantic eşleştirmeye Türkçe-fold eklendi (BİRİM/İ/Ş gibi başlıklar ASCII alias'larla doğru eşleşir)
  - 15 eksik canonical alan alias'ı eklendi (stock_uom/currency/condition/kargo vb.); 'birim' artık stock_uom'a gider, fiyatı çalmaz
  - Çoklu görsel kolonu için primary_image + image_2..N slot ataması
  - validate_mapping ile fiyat/SKU/ad sütunu eşleşmezse ham MandatoryError yerine anlaşılır hata
- feat(bulk-import): derin görsel eşleştirme ve optimizasyon eklendi (@aliiball)
  - SKU anahtarları normalize edilir (büyük/küçük + Türkçe-fold); klasör galerisi doğal/sayısal sıralanır
  - ZIP içeriği magic-number ile doğrulanır; eşleşmeyen dosyalar yetim olarak raporlanır
  - Satıcıya özel 'SKU Filename' desenleri görsel eşleştirmede fallback olarak tüketilir
  - Yüklenen görseller web boyutuna küçültülür + yeniden sıkıştırılır (1600px, format korunur, başarısızsa orijinal); ZIP ve URL
- feat(bulk-import): import akışı orkestrasyonu güçlendirildi (@aliiball)
  - Onaylanan eşleştirme satıcı profili olarak öğrenilir (xlsx/csv); aynı başlıklı sonraki dosyalar otomatik eşlenir
  - Sniffer ile xlsx başlık satırı ve ana sayfa otomatik tespiti (dry_run önizlemeye taşınır)
  - Mapping ön-kontrolü: zorunlu sütun eşleşmezse tek anlaşılır hatayla erken durdurma
  - Görsel eşleştiriciye gerçek ürün SKU listesi (known_skus) geçirilir
  - ECA reject satırları yakalanıp eca_rejected olarak skip raporlanır
  - Ham MandatoryError anlaşılır mesaja çevrilir; hata kayıtlarına ilgili alan + önem derecesi yazılır; yetim görsel özeti eklenir
  - dry_run çıktısına conflicts/detected alanları, şablona görsel kolonları, görsel limiti 50 MB, get_import_status'a severity/field
- feat(bulk-import): DocType alanları ve migration'lar eklendi (@aliiball)
  - Bulk Import Job'a remember_mapping (Check) alanı
  - Bulk Import Job Error.error_type'a eca_rejected seçeneği; error'a field + severity alanları
  - İlgili idempotent reload-doc migration'ları (v15_7_7/8/9) ve patches.txt kayıtları
- feat(eca): süper admin kural sihirbazı + governance + ağaç/arama değer seçici (@aliiball)
  - admin şema 12 eylem + canlı sayım + dry-run önizleme (persist yok)
  - governance: çakışma uyarısı, versiyon geçmişi/geri-al, örnek üründe test
  - create_document tıklama-bazlı (kayıt türü dropdown + alan eşleyici; "DocType"/JSON yok)
  - kategori değeri için link_tree_roots/children/search (path'li, 11k düz dump yerine)
  - satıcı çağrıları regresyonsuz (5 eylem korunur)
- feat(bulk-import): xlsx ham satır okuyucu eklendi (sniffer başlık/sayfa tespiti) (@aliiball)
  - read_raw(): başlık satırı ve ana sayfa tespiti için tüm dosyayı belleğe almadan ilk N ham satırı döndürür (sniffer.find_header_row / pick_main_sheet ile kullanılır)

### Duzeltildi
- fix(eca): reject_row toplu yüklemede satır atlamaya bağlandı (@aliiball)
  - reject_row aksiyonu flag set ediyordu ama hiçbir yer okumuyordu; artık validate fazında ECARejectionError fırlatılır ve insert DB yazımından önce iptal edilir
  - Yalnız validate/before_save/before_insert event'lerinde fırlatılır (after_insert/on_update'te orphan kayıt koruması)

---
## [v1.3.2] - 2026-06-11 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Duzeltildi
- fix(seo): satıcı kendi ürününün SEO'sunu düzenleyebilsin (@boraydeger32)

---
## [v1.3.1-rc.1] - 2026-06-11 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Duzeltildi
- fix(seo): satıcı kendi ürününün SEO'sunu düzenleyebilsin (@boraydeger32)

---
## [v1.3.1-beta.1] - 2026-06-11 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(seo): satıcı kendi ürününün SEO'sunu düzenleyebilsin (@boraydeger32)

---
## [v1.3.1] - 2026-06-11 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Duzeltildi
- fix(seo): paylaşım ve SEO URL'leri backend domaini gösterme hatası düzeltildi (@ahmeetseker)
  - canonical, og:url, hreflang, sitemap, robots ve JSON-LD schema URL'leri artık site_config.storefront_url üzerinden üretiliyor (örn. https://istoc.com); frappe.utils.get_url() request Host'unu döndürdüğü için backend domaini (istoc.cronbi.com) çıkıyordu
  - ortak storefront_url() helper'ı eklendi (seo/site_url.py); meta_builder, sitemap_generator, schema_builder, robots_generator, hooks_seo ve page_resolver bu helper'a bağlandı

### Degistirildi
- refactor(format): backend kaynakları Ruff ile yeniden biçimlendirildi (@ahmeetseker)

---
## [v1.3.0-rc.1] - 2026-06-11 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Duzeltildi
- fix(seo): paylaşım ve SEO URL'leri backend domaini gösterme hatası düzeltildi (@ahmeetseker)
  - canonical, og:url, hreflang, sitemap, robots ve JSON-LD schema URL'leri artık site_config.storefront_url üzerinden üretiliyor (örn. https://istoc.com); frappe.utils.get_url() request Host'unu döndürdüğü için backend domaini (istoc.cronbi.com) çıkıyordu
  - ortak storefront_url() helper'ı eklendi (seo/site_url.py); meta_builder, sitemap_generator, schema_builder, robots_generator, hooks_seo ve page_resolver bu helper'a bağlandı

### Degistirildi
- refactor(format): backend kaynakları Ruff ile yeniden biçimlendirildi (@ahmeetseker)

---
## [v1.3.0-beta.1] - 2026-06-11 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(seo): paylaşım ve SEO URL'leri backend domaini gösterme hatası düzeltildi (@ahmeetseker)
  - canonical, og:url, hreflang, sitemap, robots ve JSON-LD schema URL'leri artık site_config.storefront_url üzerinden üretiliyor (örn. https://istoc.com); frappe.utils.get_url() request Host'unu döndürdüğü için backend domaini (istoc.cronbi.com) çıkıyordu
  - ortak storefront_url() helper'ı eklendi (seo/site_url.py); meta_builder, sitemap_generator, schema_builder, robots_generator, hooks_seo ve page_resolver bu helper'a bağlandı

### Degistirildi
- refactor(format): backend kaynakları Ruff ile yeniden biçimlendirildi (@ahmeetseker)

---
## [v1.3.0] - 2026-06-11 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(handover): Custom DocPerm permlevel-0 taban izni invariant kontrolü eklendi (@aliiball)
- feat(eca): süper admin kural sihirbazı + governance + tıklama-bazlı eylemler (@aliiball)
  - admin şema 12 eylem + canlı sayım + dry-run önizleme (preview_rule_effect, persist yok)
  - governance: detect_rule_conflicts, get/restore_rule_versions, test_rule_on_product
  - create_document tıklama-bazlı (get_creatable_doctypes/get_doctype_target_fields/get_link_options)
  - "DocType" kelimesi kullanıcıya gösterilmez; satıcı çağrıları regresyonsuz (5 eylem)
- feat(bulk-import): admin Sistem Eşleştirme + parametrik SKU/XML (@aliiball)
  - System-scope kolon/değer eşleme endpointleri (admin guard) + Seller Value Mapping scope alanı
  - SKU/XML parametrik: fiyat ayraç + XML etiket adı (regex sistem üretir), ham regex gated
  - Regex Pattern Library kullanım sayacı (match_count); link-değer okunur ad (title_field)
- feat(bulk-import): admin geçmişinde satıcı adı zenginleştirme (@aliiball)
  - get_my_history admin yanıtına satıcı (mağaza) adını ekler; tabloda Satıcı kolonu için
- feat(subscription): "Abonelik" sidebar item + mevcut abonelik detayı (@boraydeger32)
  - Satıcı sidebar'ına (Profil & Finans) "Abonelik" → /abonelik nav item'ı (module_navigation_spec + TH Module Registry seed patch v15_7_5)
  - get_seller_access_state ok yanıtına trial_start/started_at/current_period_end (abonelik ekranındaki mevcut paket/durum/tarih kartı için)

### Duzeltildi
- fix(kyb): satıcı kendi KYB/KYC kaydını panelde açarken 403 hatası düzeltildi (@aliiball)
  - v15_1_3 PII patch'i permlevel 1/2/3 Custom DocPerm eklerken taban permlevel-0 satırını kopyalamadığı için Custom DocPerm standart DocPerm'i ezdi ve temel read düştü
  - v15_7_6 onarım patch'i: tabDocPerm permlevel-0 satırlarını Custom DocPerm'e aynalar
  - v15_1_3 + pii_permlevel_setup: setup_custom_perms ile taban izinler korunur
- fix(patches): has_column'a DocType adı verilerek migrate hatası giderildi (@aliiball)
  - "tabSeller Value Mapping" gibi tab-önekli ad ikinci kez prefix'lenip TableMissingError veriyordu; tablo + sütun kontrolü doğru DocType adıyla yapılır (v15_7_4)

---
## [v1.2.1-rc.1] - 2026-06-11 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(handover): Custom DocPerm permlevel-0 taban izni invariant kontrolü eklendi (@aliiball)
- feat(eca): süper admin kural sihirbazı + governance + tıklama-bazlı eylemler (@aliiball)
  - admin şema 12 eylem + canlı sayım + dry-run önizleme (preview_rule_effect, persist yok)
  - governance: detect_rule_conflicts, get/restore_rule_versions, test_rule_on_product
  - create_document tıklama-bazlı (get_creatable_doctypes/get_doctype_target_fields/get_link_options)
  - "DocType" kelimesi kullanıcıya gösterilmez; satıcı çağrıları regresyonsuz (5 eylem)
- feat(bulk-import): admin Sistem Eşleştirme + parametrik SKU/XML (@aliiball)
  - System-scope kolon/değer eşleme endpointleri (admin guard) + Seller Value Mapping scope alanı
  - SKU/XML parametrik: fiyat ayraç + XML etiket adı (regex sistem üretir), ham regex gated
  - Regex Pattern Library kullanım sayacı (match_count); link-değer okunur ad (title_field)
- feat(bulk-import): admin geçmişinde satıcı adı zenginleştirme (@aliiball)
  - get_my_history admin yanıtına satıcı (mağaza) adını ekler; tabloda Satıcı kolonu için
- feat(subscription): "Abonelik" sidebar item + mevcut abonelik detayı (@boraydeger32)
  - Satıcı sidebar'ına (Profil & Finans) "Abonelik" → /abonelik nav item'ı (module_navigation_spec + TH Module Registry seed patch v15_7_5)
  - get_seller_access_state ok yanıtına trial_start/started_at/current_period_end (abonelik ekranındaki mevcut paket/durum/tarih kartı için)

### Duzeltildi
- fix(kyb): satıcı kendi KYB/KYC kaydını panelde açarken 403 hatası düzeltildi (@aliiball)
  - v15_1_3 PII patch'i permlevel 1/2/3 Custom DocPerm eklerken taban permlevel-0 satırını kopyalamadığı için Custom DocPerm standart DocPerm'i ezdi ve temel read düştü
  - v15_7_6 onarım patch'i: tabDocPerm permlevel-0 satırlarını Custom DocPerm'e aynalar
  - v15_1_3 + pii_permlevel_setup: setup_custom_perms ile taban izinler korunur
- fix(patches): has_column'a DocType adı verilerek migrate hatası giderildi (@aliiball)
  - "tabSeller Value Mapping" gibi tab-önekli ad ikinci kez prefix'lenip TableMissingError veriyordu; tablo + sütun kontrolü doğru DocType adıyla yapılır (v15_7_4)

---
## [v1.2.1-beta.3] - 2026-06-11 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(subscription): "Abonelik" sidebar item + mevcut abonelik detayı (@boraydeger32)
  - Satıcı sidebar'ına (Profil & Finans) "Abonelik" → /abonelik nav item'ı (module_navigation_spec + TH Module Registry seed patch v15_7_5)
  - get_seller_access_state ok yanıtına trial_start/started_at/current_period_end (abonelik ekranındaki mevcut paket/durum/tarih kartı için)

---
## [v1.2.1-beta.2] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(eca): süper admin kural sihirbazı + governance + tıklama-bazlı eylemler (@aliiball)
  - admin şema 12 eylem + canlı sayım + dry-run önizleme (preview_rule_effect, persist yok)
  - governance: detect_rule_conflicts, get/restore_rule_versions, test_rule_on_product
  - create_document tıklama-bazlı (get_creatable_doctypes/get_doctype_target_fields/get_link_options)
  - "DocType" kelimesi kullanıcıya gösterilmez; satıcı çağrıları regresyonsuz (5 eylem)
- feat(bulk-import): admin Sistem Eşleştirme + parametrik SKU/XML (@aliiball)
  - System-scope kolon/değer eşleme endpointleri (admin guard) + Seller Value Mapping scope alanı
  - SKU/XML parametrik: fiyat ayraç + XML etiket adı (regex sistem üretir), ham regex gated
  - Regex Pattern Library kullanım sayacı (match_count); link-değer okunur ad (title_field)
- feat(bulk-import): admin geçmişinde satıcı adı zenginleştirme (@aliiball)
  - get_my_history admin yanıtına satıcı (mağaza) adını ekler; tabloda Satıcı kolonu için

### Duzeltildi
- fix(patches): has_column'a DocType adı verilerek migrate hatası giderildi (@aliiball)
  - "tabSeller Value Mapping" gibi tab-önekli ad ikinci kez prefix'lenip TableMissingError veriyordu; tablo + sütun kontrolü doğru DocType adıyla yapılır (v15_7_4)

---
## [v1.2.1-beta.1] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(handover): Custom DocPerm permlevel-0 taban izni invariant kontrolü eklendi (@aliiball)

### Duzeltildi
- fix(kyb): satıcı kendi KYB/KYC kaydını panelde açarken 403 hatası düzeltildi (@aliiball)
  - v15_1_3 PII patch'i permlevel 1/2/3 Custom DocPerm eklerken taban permlevel-0 satırını kopyalamadığı için Custom DocPerm standart DocPerm'i ezdi ve temel read düştü
  - v15_7_6 onarım patch'i: tabDocPerm permlevel-0 satırlarını Custom DocPerm'e aynalar
  - v15_1_3 + pii_permlevel_setup: setup_custom_perms ile taban izinler korunur

---
## [v1.2.1] - 2026-06-10 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(subscription): trial + paywall gate, havale ödeme ve feature enforcement (@boraydeger32)
  - Store Subscription: `expired` durumu + trial alanları (trial_start/used, reminder bayrakları, trial_plan); state machine + reaktivasyon fix
  - get_seller_access_state kapı endpoint'i; onayda otomatik Pro trial (Seller Application.requested_trial_plan -> _start_trial_if_requested)
  - 30-dk cron: trial bitiş bildirimleri (T-3g/1g/2s, idempotent) + expiry->expired
  - Havale/EFT ödeme: Subscription Payment doctype + Marketplace Settings banka alanlari + create/confirm/reject/list endpoint'leri (manuel admin onayi)
  - Feature enforcement: enforce_feature helper + CRM ve toplu ice aktarim endpoint'lerinde plan kapisi (platform admin muaf)

---
## [v1.2.0-rc.1] - 2026-06-10 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(subscription): trial + paywall gate, havale ödeme ve feature enforcement (@boraydeger32)
  - Store Subscription: `expired` durumu + trial alanları (trial_start/used, reminder bayrakları, trial_plan); state machine + reaktivasyon fix
  - get_seller_access_state kapı endpoint'i; onayda otomatik Pro trial (Seller Application.requested_trial_plan -> _start_trial_if_requested)
  - 30-dk cron: trial bitiş bildirimleri (T-3g/1g/2s, idempotent) + expiry->expired
  - Havale/EFT ödeme: Subscription Payment doctype + Marketplace Settings banka alanlari + create/confirm/reject/list endpoint'leri (manuel admin onayi)
  - Feature enforcement: enforce_feature helper + CRM ve toplu ice aktarim endpoint'lerinde plan kapisi (platform admin muaf)

---
## [v1.2.0-beta.1] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(subscription): trial + paywall gate, havale ödeme ve feature enforcement (@boraydeger32)
  - Store Subscription: `expired` durumu + trial alanları (trial_start/used, reminder bayrakları, trial_plan); state machine + reaktivasyon fix
  - get_seller_access_state kapı endpoint'i; onayda otomatik Pro trial (Seller Application.requested_trial_plan -> _start_trial_if_requested)
  - 30-dk cron: trial bitiş bildirimleri (T-3g/1g/2s, idempotent) + expiry->expired
  - Havale/EFT ödeme: Subscription Payment doctype + Marketplace Settings banka alanlari + create/confirm/reject/list endpoint'leri (manuel admin onayi)
  - Feature enforcement: enforce_feature helper + CRM ve toplu ice aktarim endpoint'lerinde plan kapisi (platform admin muaf)

---
## [v1.2.0] - 2026-06-10 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(i18n): çok-dilli içerik altyapısı + kategori/platform-terim çevirileri (@aliturguttursab)
  - seo/i18n.py: resolve_content_field + {field}_{lang} sufix modeli, normalize_lang, CONTENT_TRANSLATABLE/CHILD config (Listing, Product Category, Listing Attribute Value, Listing Variant Item).
  - utils/content_i18n.py + DocType controller (Listing, Product Category): validate()'te base ↔ varsayılan-dil senkronu + zorunlu-dil kontrolü.
  - patches v15_7_0 (parent kolonlar) + v15_7_2 (child kolonlar): custom field üretimi + mevcut TR içeriği _tr koluna backfill. patches.txt + fixtures/custom_field.json güncellendi. (v15_7_1: seller-owner listing docperm patch'i de dahil.)
  - PLATFORM_TERMS + translate_platform_term + format_discount_badge.
  - api/listing.py: spec grup başlıkları (Genel/Teknik...), paketleme etiketleri + package_type değerleri, UOM birimleri (Adet→Piece), teslim süresi (iş günü/gün), kart stats/indirim, kategori breadcrumb; tümü lang ile çözülüyor.
- feat(i18n): demo içerik çevirilerini backfill eden patch (v15_7_3) (@aliturguttursab)
  - İdempotent: yalnızca boş (_en null/'') satırları doldurur; mevcut çeviriyi ezmez.
  - Yalnızca haritadaki kaynakla eşleşen (demo) içerik çevrilir; gerçek/farklı içerik etkilenmez (oto-çeviri ayrı özellik).
  - patches.txt post_model_sync sonuna eklendi (kolonlar v15_7_0/2'de oluşur).
- feat(pricing): paket yapısı, kart içeriği ve quota enforcement düzeltmeleri (@boraydeger32)
  - 3 paketlik yapı: Basic / Pro Platinium / Enterprise (STARTER kaldırıldı, fixture'dan da çıkarıldı); Enterprise "Teklif Al" + 14 gün trial alanı
  - Subscription Plan'a price_override_label alanı (fiyat yerine özel metin)
  - Feature Catalog'a is_coming_soon alanı (storefront "Yakında" rozeti)
  - public_pricing: ortak kart seti gösterimi (✓/✗), display_name fallback, enum/quota text_value ve coming_soon kart verisine eklendi
  - permission_console: boş sayısal alanları 0'a normalize (fiyatsız plan kaydında "Value missing" hatası giderildi)
  - fix: sub-user quota sayımı owner'ı dahil ediyordu → tradehub_is_owner=0 filtresi (seller_users.invite/reactivate); limit yalnız sub-user'ları sayar
  - patch'ler: enforcement→pricing taşıma, 3-tier yapı, Enterprise full kart, küratörlü ve ortak kart setleri (v15_6_24..28)
- feat(i18n-ux): get_category_tree çeviri tamamlanmışlık bilgisi (Faz 2) (@aliturguttursab)
- feat(i18n): get_category_translations — çeviri workbench için düz kategori listesi (@aliturguttursab)
- feat(trial): global trial config + storefront trial_config + matris "Yakında" (@boraydeger32)
  - Trial Settings (Single DocType): trial_enabled/trial_plan/trial_days/trial_cta_label + get_trial_settings helper + on_update cache invalidation
  - permission_console: get_trial_settings / update_trial_settings (plan trial_days senkron)
  - public_pricing: response'a trial_config; _build_features_matrix'e coming_soon
- feat(pim): mini-PIM şema + zorunlu-attribute temizliği (@aliiball)
  - Product Attribute: attribute_label_en + include_in_bulk_template
  - Listing Variant Item: 3. eksen (attribute_type_3/value_3) + axis_values_json
  - product-type bazlı zorunlu-attribute enforcement kaldırıldı (cleanup patch)
- feat(bulk-import): kolon otomatik eşleme + import boru hattı iyileştirmeleri (@aliiball)
  - canonical_fields PIM+varyant eş anlamlıları + resolver attribute katmanı
  - önizleme/import 4 katmanlı resolver kullanır (sessiz veri kaybı düzeltildi)
  - get_import_status hata listesi + özet döner; örnek görsel ZIP endpoint'i
  - runner: değer-eşleme transform + görsel URL ingest kancası + eski hata temizleme
- feat(bulk-import): hücre değeri + kolon-adı eşleştirme (Seller Value Mapping) (@aliiball)
  - Seller Value Mapping doctype: alan + gelen değer → hedef değer (satıcı bazlı)
  - hardcoded _TR_*_ALIASES satıcı-yapılandırılabilir genel lookup'a taşındı
  - regex_lib: regex'siz kolon-alias + güvenli regex üretimi endpointleri
- feat(eca): kural sihirbazı backend (şema + derleme + canlı sayım) (@aliiball)
  - get_rule_schema / count_matching / save_wizard_rule + get_mapping_targets
  - sihirbaz eylemleri mevcut condition_compiler + action_type'a derlenir
  - count_matching tenant-scoped get_all kullanır (Listing izin hatası giderildi)
- feat(feed): URL'den otomatik XML çekme + görsel ingest + run-history (@aliiball)
  - Seller XML Feed + saatlik scheduler (24h) + SSRF korumalı fetch + auto-disable
  - uzak görsel URL'leri indir/doğrula/barındır (URL cache) + bulk_import_safe fix
  - Bulk Import Job source_feed bağı → list_feed_runs + feed_dry_run (persist yok)
- feat(feed): XML Feed plan-bazlı yetkilendirme (Pricing Table) (@aliiball)
  - feature.import.xml_feed capability'si (Feature Catalog + plan seed)
  - entitlement_snapshot feature.import. prefix'ini frontend'e açar
- feat(pricing): seed feature tooltip descriptions for comparison table (@boraydeger32)

### Duzeltildi
- fix(plan): planda zaten kayıtlı deprecated capability key save'i engellemesin (@boraydeger32)
- fix(bulk-import): listing persisteri ignore_permissions ile yazar (@aliiball)
  - create/update/variants yolları ignore_permissions=True (güvenilir sunucu işi)
  - seller_profile açıkça set edildiği için tenant izolasyonu korunur
- fix(permissions): yeni doctype tenant hook'ları + satıcı Custom DocPerm onarımı (@aliiball)
  - Seller Value Mapping / Seller XML Feed için query_conditions + has_permission
  - Marketplace Seller 7 satıcı-doctype Custom DocPerm'ine eklendi (form erişimi)
  - patches.txt'ye yeni migration'lar eklendi
- fix(category): log_error başlık/mesaj ayrımı (CharacterLengthExceeded) (@aliiball)

### Degistirildi
- refactor(lint): simplify lint workflow by removing auto-fix steps and changing permissions (@ahmeetseker)
- refactor(nav): satıcı menüsü — XML Feed maddesi + "Eşleştirmelerim" (@aliiball)
  - TH Module Registry'ye seller-feed kaydı; "Pattern'lerim" → "Eşleştirmelerim"

---
## [v1.1.0-rc.1] - 2026-06-10 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(i18n): çok-dilli içerik altyapısı + kategori/platform-terim çevirileri (@aliturguttursab)
  - seo/i18n.py: resolve_content_field + {field}_{lang} sufix modeli, normalize_lang, CONTENT_TRANSLATABLE/CHILD config (Listing, Product Category, Listing Attribute Value, Listing Variant Item).
  - utils/content_i18n.py + DocType controller (Listing, Product Category): validate()'te base ↔ varsayılan-dil senkronu + zorunlu-dil kontrolü.
  - patches v15_7_0 (parent kolonlar) + v15_7_2 (child kolonlar): custom field üretimi + mevcut TR içeriği _tr koluna backfill. patches.txt + fixtures/custom_field.json güncellendi. (v15_7_1: seller-owner listing docperm patch'i de dahil.)
  - PLATFORM_TERMS + translate_platform_term + format_discount_badge.
  - api/listing.py: spec grup başlıkları (Genel/Teknik...), paketleme etiketleri + package_type değerleri, UOM birimleri (Adet→Piece), teslim süresi (iş günü/gün), kart stats/indirim, kategori breadcrumb; tümü lang ile çözülüyor.
- feat(i18n): demo içerik çevirilerini backfill eden patch (v15_7_3) (@aliturguttursab)
  - İdempotent: yalnızca boş (_en null/'') satırları doldurur; mevcut çeviriyi ezmez.
  - Yalnızca haritadaki kaynakla eşleşen (demo) içerik çevrilir; gerçek/farklı içerik etkilenmez (oto-çeviri ayrı özellik).
  - patches.txt post_model_sync sonuna eklendi (kolonlar v15_7_0/2'de oluşur).
- feat(pricing): paket yapısı, kart içeriği ve quota enforcement düzeltmeleri (@boraydeger32)
  - 3 paketlik yapı: Basic / Pro Platinium / Enterprise (STARTER kaldırıldı, fixture'dan da çıkarıldı); Enterprise "Teklif Al" + 14 gün trial alanı
  - Subscription Plan'a price_override_label alanı (fiyat yerine özel metin)
  - Feature Catalog'a is_coming_soon alanı (storefront "Yakında" rozeti)
  - public_pricing: ortak kart seti gösterimi (✓/✗), display_name fallback, enum/quota text_value ve coming_soon kart verisine eklendi
  - permission_console: boş sayısal alanları 0'a normalize (fiyatsız plan kaydında "Value missing" hatası giderildi)
  - fix: sub-user quota sayımı owner'ı dahil ediyordu → tradehub_is_owner=0 filtresi (seller_users.invite/reactivate); limit yalnız sub-user'ları sayar
  - patch'ler: enforcement→pricing taşıma, 3-tier yapı, Enterprise full kart, küratörlü ve ortak kart setleri (v15_6_24..28)
- feat(i18n-ux): get_category_tree çeviri tamamlanmışlık bilgisi (Faz 2) (@aliturguttursab)
- feat(i18n): get_category_translations — çeviri workbench için düz kategori listesi (@aliturguttursab)
- feat(trial): global trial config + storefront trial_config + matris "Yakında" (@boraydeger32)
  - Trial Settings (Single DocType): trial_enabled/trial_plan/trial_days/trial_cta_label + get_trial_settings helper + on_update cache invalidation
  - permission_console: get_trial_settings / update_trial_settings (plan trial_days senkron)
  - public_pricing: response'a trial_config; _build_features_matrix'e coming_soon
- feat(pim): mini-PIM şema + zorunlu-attribute temizliği (@aliiball)
  - Product Attribute: attribute_label_en + include_in_bulk_template
  - Listing Variant Item: 3. eksen (attribute_type_3/value_3) + axis_values_json
  - product-type bazlı zorunlu-attribute enforcement kaldırıldı (cleanup patch)
- feat(bulk-import): kolon otomatik eşleme + import boru hattı iyileştirmeleri (@aliiball)
  - canonical_fields PIM+varyant eş anlamlıları + resolver attribute katmanı
  - önizleme/import 4 katmanlı resolver kullanır (sessiz veri kaybı düzeltildi)
  - get_import_status hata listesi + özet döner; örnek görsel ZIP endpoint'i
  - runner: değer-eşleme transform + görsel URL ingest kancası + eski hata temizleme
- feat(bulk-import): hücre değeri + kolon-adı eşleştirme (Seller Value Mapping) (@aliiball)
  - Seller Value Mapping doctype: alan + gelen değer → hedef değer (satıcı bazlı)
  - hardcoded _TR_*_ALIASES satıcı-yapılandırılabilir genel lookup'a taşındı
  - regex_lib: regex'siz kolon-alias + güvenli regex üretimi endpointleri
- feat(eca): kural sihirbazı backend (şema + derleme + canlı sayım) (@aliiball)
  - get_rule_schema / count_matching / save_wizard_rule + get_mapping_targets
  - sihirbaz eylemleri mevcut condition_compiler + action_type'a derlenir
  - count_matching tenant-scoped get_all kullanır (Listing izin hatası giderildi)
- feat(feed): URL'den otomatik XML çekme + görsel ingest + run-history (@aliiball)
  - Seller XML Feed + saatlik scheduler (24h) + SSRF korumalı fetch + auto-disable
  - uzak görsel URL'leri indir/doğrula/barındır (URL cache) + bulk_import_safe fix
  - Bulk Import Job source_feed bağı → list_feed_runs + feed_dry_run (persist yok)
- feat(feed): XML Feed plan-bazlı yetkilendirme (Pricing Table) (@aliiball)
  - feature.import.xml_feed capability'si (Feature Catalog + plan seed)
  - entitlement_snapshot feature.import. prefix'ini frontend'e açar
- feat(pricing): seed feature tooltip descriptions for comparison table (@boraydeger32)

### Duzeltildi
- fix(plan): planda zaten kayıtlı deprecated capability key save'i engellemesin (@boraydeger32)
- fix(bulk-import): listing persisteri ignore_permissions ile yazar (@aliiball)
  - create/update/variants yolları ignore_permissions=True (güvenilir sunucu işi)
  - seller_profile açıkça set edildiği için tenant izolasyonu korunur
- fix(permissions): yeni doctype tenant hook'ları + satıcı Custom DocPerm onarımı (@aliiball)
  - Seller Value Mapping / Seller XML Feed için query_conditions + has_permission
  - Marketplace Seller 7 satıcı-doctype Custom DocPerm'ine eklendi (form erişimi)
  - patches.txt'ye yeni migration'lar eklendi
- fix(category): log_error başlık/mesaj ayrımı (CharacterLengthExceeded) (@aliiball)

### Degistirildi
- refactor(lint): simplify lint workflow by removing auto-fix steps and changing permissions (@ahmeetseker)
- refactor(nav): satıcı menüsü — XML Feed maddesi + "Eşleştirmelerim" (@aliiball)
  - TH Module Registry'ye seller-feed kaydı; "Pattern'lerim" → "Eşleştirmelerim"

---
## [v1.1.0-beta.11] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(pricing): seed feature tooltip descriptions for comparison table (@boraydeger32)

---
## [v1.1.0-beta.10] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(pim): mini-PIM şema + zorunlu-attribute temizliği (@aliiball)
  - Product Attribute: attribute_label_en + include_in_bulk_template
  - Listing Variant Item: 3. eksen (attribute_type_3/value_3) + axis_values_json
  - product-type bazlı zorunlu-attribute enforcement kaldırıldı (cleanup patch)
- feat(bulk-import): kolon otomatik eşleme + import boru hattı iyileştirmeleri (@aliiball)
  - canonical_fields PIM+varyant eş anlamlıları + resolver attribute katmanı
  - önizleme/import 4 katmanlı resolver kullanır (sessiz veri kaybı düzeltildi)
  - get_import_status hata listesi + özet döner; örnek görsel ZIP endpoint'i
  - runner: değer-eşleme transform + görsel URL ingest kancası + eski hata temizleme
- feat(bulk-import): hücre değeri + kolon-adı eşleştirme (Seller Value Mapping) (@aliiball)
  - Seller Value Mapping doctype: alan + gelen değer → hedef değer (satıcı bazlı)
  - hardcoded _TR_*_ALIASES satıcı-yapılandırılabilir genel lookup'a taşındı
  - regex_lib: regex'siz kolon-alias + güvenli regex üretimi endpointleri
- feat(eca): kural sihirbazı backend (şema + derleme + canlı sayım) (@aliiball)
  - get_rule_schema / count_matching / save_wizard_rule + get_mapping_targets
  - sihirbaz eylemleri mevcut condition_compiler + action_type'a derlenir
  - count_matching tenant-scoped get_all kullanır (Listing izin hatası giderildi)
- feat(feed): URL'den otomatik XML çekme + görsel ingest + run-history (@aliiball)
  - Seller XML Feed + saatlik scheduler (24h) + SSRF korumalı fetch + auto-disable
  - uzak görsel URL'leri indir/doğrula/barındır (URL cache) + bulk_import_safe fix
  - Bulk Import Job source_feed bağı → list_feed_runs + feed_dry_run (persist yok)
- feat(feed): XML Feed plan-bazlı yetkilendirme (Pricing Table) (@aliiball)
  - feature.import.xml_feed capability'si (Feature Catalog + plan seed)
  - entitlement_snapshot feature.import. prefix'ini frontend'e açar

### Duzeltildi
- fix(bulk-import): listing persisteri ignore_permissions ile yazar (@aliiball)
  - create/update/variants yolları ignore_permissions=True (güvenilir sunucu işi)
  - seller_profile açıkça set edildiği için tenant izolasyonu korunur
- fix(permissions): yeni doctype tenant hook'ları + satıcı Custom DocPerm onarımı (@aliiball)
  - Seller Value Mapping / Seller XML Feed için query_conditions + has_permission
  - Marketplace Seller 7 satıcı-doctype Custom DocPerm'ine eklendi (form erişimi)
  - patches.txt'ye yeni migration'lar eklendi
- fix(category): log_error başlık/mesaj ayrımı (CharacterLengthExceeded) (@aliiball)

### Degistirildi
- refactor(nav): satıcı menüsü — XML Feed maddesi + "Eşleştirmelerim" (@aliiball)
  - TH Module Registry'ye seller-feed kaydı; "Pattern'lerim" → "Eşleştirmelerim"

---
## [v1.1.0-beta.9] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(plan): planda zaten kayıtlı deprecated capability key save'i engellemesin (@boraydeger32)

---
## [v1.1.0-beta.8] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(trial): global trial config + storefront trial_config + matris "Yakında" (@boraydeger32)
  - Trial Settings (Single DocType): trial_enabled/trial_plan/trial_days/trial_cta_label + get_trial_settings helper + on_update cache invalidation
  - permission_console: get_trial_settings / update_trial_settings (plan trial_days senkron)
  - public_pricing: response'a trial_config; _build_features_matrix'e coming_soon

---
## [v1.1.0-beta.7] - 2026-06-10 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(i18n-ux): get_category_tree çeviri tamamlanmışlık bilgisi (Faz 2) (@aliturguttursab)
- feat(i18n): get_category_translations — çeviri workbench için düz kategori listesi (@aliturguttursab)

---
## [v1.1.0-beta.4] - 2026-06-09 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(pricing): paket yapısı, kart içeriği ve quota enforcement düzeltmeleri (@boraydeger32)
  - 3 paketlik yapı: Basic / Pro Platinium / Enterprise (STARTER kaldırıldı, fixture'dan da çıkarıldı); Enterprise "Teklif Al" + 14 gün trial alanı
  - Subscription Plan'a price_override_label alanı (fiyat yerine özel metin)
  - Feature Catalog'a is_coming_soon alanı (storefront "Yakında" rozeti)
  - public_pricing: ortak kart seti gösterimi (✓/✗), display_name fallback, enum/quota text_value ve coming_soon kart verisine eklendi
  - permission_console: boş sayısal alanları 0'a normalize (fiyatsız plan kaydında "Value missing" hatası giderildi)
  - fix: sub-user quota sayımı owner'ı dahil ediyordu → tradehub_is_owner=0 filtresi (seller_users.invite/reactivate); limit yalnız sub-user'ları sayar
  - patch'ler: enforcement→pricing taşıma, 3-tier yapı, Enterprise full kart, küratörlü ve ortak kart setleri (v15_6_24..28)

---
## [v1.1.0-beta.3] - 2026-06-09 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(i18n): demo içerik çevirilerini backfill eden patch (v15_7_3) (@aliturguttursab)
  - İdempotent: yalnızca boş (_en null/'') satırları doldurur; mevcut çeviriyi ezmez.
  - Yalnızca haritadaki kaynakla eşleşen (demo) içerik çevrilir; gerçek/farklı içerik etkilenmez (oto-çeviri ayrı özellik).
  - patches.txt post_model_sync sonuna eklendi (kolonlar v15_7_0/2'de oluşur).

---
## [v1.1.0-beta.2] - 2026-06-08 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(i18n): çok-dilli içerik altyapısı + kategori/platform-terim çevirileri (@aliturguttursab)
  - seo/i18n.py: resolve_content_field + {field}_{lang} sufix modeli, normalize_lang, CONTENT_TRANSLATABLE/CHILD config (Listing, Product Category, Listing Attribute Value, Listing Variant Item).
  - utils/content_i18n.py + DocType controller (Listing, Product Category): validate()'te base ↔ varsayılan-dil senkronu + zorunlu-dil kontrolü.
  - patches v15_7_0 (parent kolonlar) + v15_7_2 (child kolonlar): custom field üretimi + mevcut TR içeriği _tr koluna backfill. patches.txt + fixtures/custom_field.json güncellendi. (v15_7_1: seller-owner listing docperm patch'i de dahil.)
  - PLATFORM_TERMS + translate_platform_term + format_discount_badge.
  - api/listing.py: spec grup başlıkları (Genel/Teknik...), paketleme etiketleri + package_type değerleri, UOM birimleri (Adet→Piece), teslim süresi (iş günü/gün), kart stats/indirim, kategori breadcrumb; tümü lang ile çözülüyor.

---
## [v1.1.0-beta.1] - 2026-06-08 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Degistirildi
- refactor(lint): simplify lint workflow by removing auto-fix steps and changing permissions (@ahmeetseker)

---
## [v1.1.0] - 2026-06-05 PROD

Bu surum istoc.cronbi.com'da yayindadir.

### Eklendi
- feat(changelog): v1.0.10-beta.1 sürüm notları eklendi (@ahmeetseker)
- feat(addresses): Sprint 1 Faz D adres mimarisi eklendi (@aliiball)
  - Addresses DocType'a purpose (Delivery/Pickup/Billing), address_type (Individual/Business), tax_no, tax_office field'ları
  - kind field'ı deprecated etiketlendi (Sprint 4'te DROP)
  - company Business hesap tipi için koşullu reqd
  - utils/tax_validation.py: Maliye VKN + NVI TCKN checksum dispatcher
  - patches/address_v1 idempotent migration (01_kind_to_purpose, 02_fix_seller_purpose_pickup)
  - test_address_purpose_migration + test_tax_validation
- feat(marketplace-settings): Marketplace Settings Single DocType eklendi (@aliiball)
  - Pazaryeri çapında adres + fatura varsayılanları
  - default_address_type=Individual, address_type_toggle_visible=1, require_tax_id_business=1, invoice_generation_mode=Manual
  - test_marketplace_settings
- feat(user-profile): User Profile DocType + 20 migration patch eklendi (@aliiball)
  - 3 profil DocType (Buyer Profile + Seller Profile + Verified Supplier) tek User Profile + Admin Seller Profile mimarisine taşındı (Sprint 2)
  - can_buy/can_sell capability flag'leri, account_type Individual/Business
  - patches/user_profile_v1 (01-20) migration serisi: doctype create, verification_kind, index, controller noop, buyer/seller migrate, hybrid merge, member_id, link/dynamic_link refs, user_permissions, user_types, scoring fields, tenant placeholder, scheduler events, validate, deprecate old, owner fix, kyc_kyb_split (19), normalize_capability_flags (20)
  - hooks.py: User Profile permission query + has_permission + Sprint 2 buyer metric/scoring scheduler events
  - setup/install.py: Sprint 2 kapsamında 5 rol (Buyer, Seller, Marketplace Admin, Marketplace Seller, Marketplace Buyer); 14 hiyerarşik rol Sprint 3 RBAC reformuna ertelendi
  - 3 workspace JSON: Seller Profile → User Profile + Admin Seller Profile
  - test_user_profile
- feat(kyc): KYC Verification DocType + 4 endpoint + checkout gate eklendi (@aliiball)
  - KYC Verification DocType: account_type toggle (Business/Individual), Kurumsal alanları (company_name, tax_id, phone, email_field, address, billing_address) + ortak identity_document
  - api/v1/kyc.py: submit_kyc_documents / review_kyc / get_kyc_status / get_prefill_data 4 endpoint
  - get_prefill_data cross-form prefill — User Profile + son KYC/KYB Verification'dan değerler birleşik
  - cart.py _ensure_buyer_kyc_verified — create_order başında KYC.Verified zorunluluğu, [KYC_<STATE>] prefix'li mesaj
  - gate add_to_cart'tan kaldırıldı (sadece create_order'da)
  - test_kyc_gate + test_kyc_verification
- feat(capability-invariant): Sprint 2.6 status-bazlı auth flags eklendi (@aliiball)
  - auth.py get_user_profile seller bloğu User Profile mimarisine taşındı (legacy alias: business_name=company_name, contact_phone=phone)
  - is_seller artık can_sell capability + "Seller" rolü fallback
  - kyc_locked/kyb_locked formülü "not can_buy/can_sell" yerine kyc_status=='Locked'/kyb_status=='Locked' (status-bazlı semantik)
  - kyc_required/kyb_required Pending|Rejected listesi
  - get_session_user response: kyc_required, kyb_required, kyc_locked, kyb_locked flag'leri
  - register_user registration_type param (Alici/Satici)
  - test_capability_flag_invariant
- feat(kyb): mersis_no + kep_address + rejection_category eklendi (@aliiball)
  - KYB Verification.mersis_no (16 hane) + kep_address (email format)
  - rejection_category Select (Re-submit | Suspended) — KYC ve KYB ayrı
  - verification_kind alanı kaldırıldı (KYC ayrı DocType'a taşındı)
  - document_expiry_date kaldırıldı (Soru 8 — expiry yok)
  - faaliyet_belgesi opsiyonel oldu
  - kyb_verification.py table_exists("Seller Profile") backward compat guard + 10 satır dormant blok kaldırıldı
  - api/v1/kyb.py User Profile mimarisine taşındı
- feat(changelog): v2.1.0-beta.1 sürüm notları eklendi (@aliiball)
  - Sprint 1 Adres Mimarisi + Sprint 2 User Profile + Sprint 2.6 capability invariant + KYC/KYB ayrımı bullet'ları
  - CLAUDE.md aktif mimari memory referansları (§6.1) eklendi
- feat(seo): SEO yönetim modülü, social proof ve arama API'leri eklendi (@ahmeetseker)
  - SEO Redirect, SEO 404 Log, Static Page SEO, Listing View Counter doctype'ları eklendi
  - tradehub_core/seo/ paketi (redirect handler + 404 logger) ve seed_static_pages script'i
  - api/seo.py + api/seo_admin.py — public/admin SEO endpoint'leri
  - Social Proof Settings doctype + api/social_proof.py + test'leri
  - api/search.py arama servisi ve test'leri eklendi
  - api/listing.py view counter, SEO meta ve filtre alanları için genişletildi
  - hooks.py: yeni doctype'lar, fixtures ve scheduler entry'leri
- feat(authz): yetki sistemi FAZ 1-5 — entitlement, RBAC bundle, (@boraydeger32)
  - Region, Feature Catalog, Subscription Plan, Subscription Plan Region, Store Subscription, Pricing Plan Feature DocType'ları.
  - entitlement/ modülü (core, checks, sync) + entitlement_snapshot API.
  - Custom fields ve PII permlevel patch'leri.
  - Approval Rule + Approval Rule Approver + Order Approval + Order Approval Log DocType'ları.
  - services/approval_workflow.py + order_approval_hooks.py + API.
  - Buyer Approver L1/L2 rolleri ve role profile bundle'ları.
  - PII Field Policy + PII Jurisdiction Rule DocType'ları, utils/pii*, Compliance Officer rolü, jurisdiction-aware masking.
  - Approved Supplier List/Entry + supplier_whitelist service.
  - Cost Center DocType + service.
  - Authorization Anomaly Rule/Alert + detector + actions (saatlik scheduler).
  - Role Delegation + Role Change Log + delegation_service + rebac_drift_detection (günlük scheduler).
  - Owner Transfer Request + owner_transfer service.
  - Pricing Plan custom fields + presets + real prices patch'leri.
  - public_pricing API (storefront sell sayfası için).
  - Signup CTA unification + commission rates repair.
  - Buyer Admin/Procurement/Finance/Viewer, Seller Admin/Co-Owner/ Finance/Staff/Viewer, Platform Admin/Finance, Support Agent rolleri.
  - role_docperms seed + role_profiles sync + ADL buyer_org field.
  - audit/ modülü (log, tasks, user_hooks) + Authorization Decision Log DocType + Permission Override Log.
  - authorization_simulator (Süper Admin debug aracı).
  - permission_console API + buyer_team + seller_users sub-user invite.
  - rebac_client + tuple_sync (ReBAC sidecar entegrasyonu).
  - permissions.py +657 satır (DocType bazlı yetki kuralları).
  - utils/tenant.py +495 satır (tenant isolation hardening).
  - hooks.py: 18 yeni patch, scheduler event'leri, doc_events.
  - tests/: 20+ yeni test dosyası (tenant, abac, anomaly, approval, delegation, entitlement, organization hierarchy, PII, procurement, rebac, simulator, sub-users, tuple sync).
- feat(bulk-import): toplu ürün içe aktarma sistemi eklendi (@aliiball)
  - BulkImportJob ve BulkImportJobError DocType'ları
  - Excel/CSV/XML parser'ları, persister ve image matcher
  - Çok dilli kolon eşleme için regex destekli ingestion
  - Background runner + worker task'ları (RQ)
  - Bildirim entegrasyonu ve hata satırı raporlama
  - v15_bulk_import_init patch'i ile DocType + örnek veri seed
  - EcaRule, EcaRuleLog, EcaActionTemplate DocType'ları
  - Dispatcher: event çözümleme, condition eval, action execution
  - SafeRegex ve validator katmanı (DoS-safe pattern çalıştırma)
  - API endpoint'leri ve permission entegrasyonu
  - Hooks.py: doc_events üzerinden tetikleyici kayıtları
  - Birim testleri (eca/tests/)
  - RegexPatternLibrary ve RegexPatternEntry DocType'ları
  - BulkImport ve ECA kullanır (kolon başlığı → field mapping)
  - Seed patch ile T1+T2 alan paterni hazır gelir
  - SellerTemplateProfile DocType eklendi
  - dashboard.py kaldırıldı, mantık dashboard_engine.py altında toplandı
  - Total users widget patch'i UserProfile'a yönlendirildi
  - permissions.py: ECA + BulkImport için yeni yetki tanımları
  - utils/security.py: rate-limit yardımcısı eklendi
  - api/listing.py: seller_sku döner, ECA tetikleyicileri bağlandı
- feat(privacy): GDPR/KVKK Faz 3.5 — veri taşınabilirlik, onay yönetimi ve ROPA (@ahmeetseker)
  - Veri dışa aktarma (GDPR Madde 20): şifre doğrulamalı export talebi, token bazlı güvenli indirme, süresi dolan export'ların otomatik temizliği
  - Onay yönetimi: consent kayıt/geri çekme API'leri, kullanıcı onay durumu sorgulama
  - ROPA export (GDPR Madde 30): JSON/CSV formatında kayıt dışa aktarma
  - Veri saklama politikası: günlük otomatik anonimleştirme enforcement
  - DPA yönetimi: haftalık süre sonu uyarı e-postaları
  - SEO iyileştirmeleri: CDN cache stratejisi (s-maxage), hardcoded SEO tag temizleme, listing slug/code çözümleme
  - Yeni DocType'lar: Tracking Settings, Consent Policy Version, Data Export Request, Data Processing Agreement, Data Retention Policy, Processing Activity Record, User Consent Log
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor
- feat(plans): plan/özellik entitlement modeli + storefront pricing tutarlılığı (@boraydeger32)
  - Feature Catalog API: list/create/update/delete/restore/reorder (feature_catalog.py)
  - Plan Feature matris API: list_plan_features + bulk_update_plan_features (plan_features.py)
  - value_type feature seviyesine taşındı (boolean/quota/enum/text); feature_catalog + pricing_plan_feature şema güncellemesi
  - public_pricing: komisyon & aktif ürün limiti için plan field TEK OTORİTE (kart ↔ karşılaştırma tablosu birebir; Sınırsız/Özel/binlik ayraç biçimi)
  - patch'ler (v15_6_20..23): matris seed, value_type storefront, içerik seed, legacy temizlik
- feat(core): satış sıralaması ve 2 aşamalı hakediş akışı eklendi (@ahmeetseker)
  - Category Showcase Settings/Tile doctype'ları ve storefront API'si (get_active_tiles) eklendi
  - Ürün detayına kategori bazlı satış sıralaması hesabı eklendi (rekabet sıralaması, 1 saat cache)
  - get_mega_menu 3 seviyeli nested kategori ağacı döndürecek şekilde genişletildi
  - Saha hakedişine 2 aşamalı onay (leader_approve/leader_reject) ve Sales Team/Member doctype'ları eklendi
  - Paket bazlı kota bonusu (Field Commission Quota Tier) ve recompute_quota_bonus eklendi
  - Field Commission Settings: global_per_sale_amount kaldırıldı, kota dönemine indirgendi
  - Üç yeni patch eklendi (iki aşamalı durum, kind/period, global tutar düşürme)

### Duzeltildi
- fix(release): son tag bilgisini güncelledi ve boş guard sorununu çözdü (@ahmeetseker)
- fix(identity): email_verified UPDATE SQL User Profile tablosuna yönlendirildi (@aliiball)
  - identity.py 6 yerde UPDATE tabBuyer Profile SQL'i tabUser Profile'a taşındı — email_verified flag artık doğru tabloya yazılıyor
  - register_supplier User Profile Sprint 2.6 davranışına uyarlandı
  - LIVE BUG
- fix(permissions): seller_balance permission Admin Seller Profile.name'e taşındı (@aliiball)
  - permissions.py seller_balance permission kullanıcı email'i yerine _get_seller_profile_name(user) (Admin Seller Profile.name) lookup
  - permissions.py docstring örnekleri "Seller Profile" → "Admin Seller Profile"
- fix(seo): seller storefront page_resolver ve slug registry'si düzeltildi (@ahmeetseker)
  - Admin Seller Profile için SLUG_FIELD_MAP `slug` → `seller_code` olarak düzeltildi (DB kolonu yoktu, lookup boş dönüyordu)
  - TEMPLATE_MAP'te seller template yolu `pages/seller/seller-shop.html` → `seller-storefront.html` güncellendi
  - static_pages_registry'de /markalar → /ureticiler ve /firsat → /firsatlar yenilendi, başlık "Tüm Üreticiler" oldu
  - get_seller API'sinde sertifikalar ayrı `frappe.get_all` ile çekildi, yalnız `verification_status = Verified` olanlar storefront'a sızar
  - Brand schema breadcrumb'unda yanlış /markalar atfı kaldırıldı (o URL aslında Üreticiler sayfasına gidiyordu)
- fix(hooks): Regex Pattern Library dict'inde eksik brace düzeltildi (@aliiball)
  - doc_events["Regex Pattern Library"] iç dict'i `},` ile kapatılmamış, sonraki tüm doctype'lar bu dict'in içine gömülüyordu
  - permission_query_conditions parse hatası giderildi
- fix(api): SEO URL geçişi sonrası kırılan endpoint'leri düzelt (@ahmeetseker)
  - listing.py: kaldırılmış is_verified sütununu sorgulardan temizle
  - listing.py: _format_listing_card'da href'i /urun/{slug} formatına geçir
  - listing.py: slug eksik olan 2 sorguya slug field'ı ekle
  - seller.py: get_sellers ürün listesine slug field'ı ekle
  - identity.py: register created_via değerini seller_application olarak düzelt
  - seo_admin.py: Static Page SEO kayıtlarını lazy auto-create et
- fix(pricing): ReBAC/ABAC pricing table schema, validation ve entitlement düzeltmeleri (@boraydeger32)
  - Subscription Plan DocType'a 8 eksik alan eklendi (badge_label, badge_color, theme, short_tagline, commission_rate, max_active_listings, cta_label, cta_action) + pricing_features Table field — public_pricing API artık çalışıyor
  - Store Subscription state machine'e trial→past_due geçişi eklendi (M2)
  - Capability flag validation: tanımsız key'ler artık reject ediliyor (M4)
  - Override JSON key whitelist: plan'da olmayan key'ler reddediliyor (M5)
  - Subscription lifecycle idempotent hale getirildi — race condition önlemi (M6)
  - Entitlement negative cache TTL 60s→10s (K2)
  - ABAC context'e order_region eklendi + N+1 category extraction batch fetch (R2)
  - Authorization simulator UNAVAILABLE→DENY fail-closed mapping (R3)
  - Drift detection'a Store Subscription eklendi (R4)
  - Approval workflow'a entitlement quota guard eklendi — key guard dahil (R1)
  - Feature Catalog + Subscription Plan seed data (3 plan, 13 feature, 20 bullet)
  - Product Category external_id reqd kaldırıldı (migration uyumu)
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(roles): role.json fixture'ı Sprint 2 hiyerarşisine sadeleştirildi (@aliiball)
  - 14 hiyerarşik rol Sprint 3 RBAC reformuna kadar setup/install.py'de kod tabanında refere edilen 5 role indirgendi
  - role.json fixture %99 azaltıldı (146 → 1 satır)
- refactor(profile): 25 modül User Profile + Admin Seller Profile'a taşındı (@aliiball)
  - api/buyer.py + qa.py: _resolve_display_name User Profile + full_name
  - api/seller.py: 7 endpoint Admin Seller Profile (replace_all)
  - api/seller_addresses.py: _resolve_seller_profile Admin Seller Profile
  - api/rfq.py: profiles batch fetch User Profile + Admin Seller Profile join (business/year_established/employee_count)
  - api/dashboard.py + kpi_dashboard.py: _profile_status_breakdown + _platform_totals tabBuyer Profile → tabUser Profile (can_buy=1 filter)
  - tradehub_core/api/seller.py + scoring/engine.py + utils/erpnext_sync.py + utils/seller_payout.py + webhooks/erpnext_hooks.py Sprint 2 uyumu
  - doctype controller temizliği: buyer_profile, seller_profile, listing_review, rfq_quote, seller_application, seller_balance, seller_product
  - utils/auth_guards.py: is_email_verified User Profile'a taşındı
  - utils/tenant_seller_validation.py: Senaryo B bypass Sprint 3'e ertelendi
  - tasks.py: User Profile terminolojisi + Sprint 2 scheduler events
  - translations/en.csv + tr.csv: User Profile/Admin Seller Profile/ Mağaza Profili stringleri güncellendi
- refactor(tests): test_cross_app_link_resolution Sprint 2.6 mimarisine uyarlandı (@aliiball)
  - verification_kind testi kaldırıldı (KYC ayrı DocType'a taşındı)
  - KYC Verification DocType varlığı eklendi
  - legacy assertion temizliği (~580 satır)
- refactor(changelog): manuel v2.1.0-beta.1 entry'si geri alındı (@aliiball)
  - beta-release.yml workflow'unun LAST_PROD-beta.N hesabıyla çakışıyordu
  - Ali → version-15 merge sonrası workflow doğru versiyonu (v1.0.9-beta.3) ve (@author) suffix'lerini otomatik üretecek
- refactor(changelog): v2.1.0-beta.1 release bloğu kaldırıldı (@ahmeetseker)
  - 413af5e revert'i Ali → version-15 back-merge sırasında uygulanmayıp v2.1.0-beta.1 bloğu version-15 üstünde kaldı, istoc-changelog viewer hatalı release gösteriyordu
  - v1.0.9-beta.2 içindeki yanıltıcı "feat(changelog): v2.1.0-beta.1 sürüm notları eklendi" bullet'ı temizlendi
  - v1.0.9-beta.3 içindeki revert kayıt bullet'ı, audit izi olarak bırakıldı
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)
- refactor(doctype): DocType etiketleri Modül olarak güncellendi (@aliiball)
  - Dashboard Widget: source_doctype label "Kaynak Modül"
  - ECA Action Template: create_doctype label "Oluşturulacak Modül"
  - Regex Pattern Library: target_doctype label "Hedef Modül"

---
## [v1.0.9-rc.2] - 2026-06-05 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(changelog): v1.0.10-beta.1 sürüm notları eklendi (@ahmeetseker)
- feat(addresses): Sprint 1 Faz D adres mimarisi eklendi (@aliiball)
  - Addresses DocType'a purpose (Delivery/Pickup/Billing), address_type (Individual/Business), tax_no, tax_office field'ları
  - kind field'ı deprecated etiketlendi (Sprint 4'te DROP)
  - company Business hesap tipi için koşullu reqd
  - utils/tax_validation.py: Maliye VKN + NVI TCKN checksum dispatcher
  - patches/address_v1 idempotent migration (01_kind_to_purpose, 02_fix_seller_purpose_pickup)
  - test_address_purpose_migration + test_tax_validation
- feat(marketplace-settings): Marketplace Settings Single DocType eklendi (@aliiball)
  - Pazaryeri çapında adres + fatura varsayılanları
  - default_address_type=Individual, address_type_toggle_visible=1, require_tax_id_business=1, invoice_generation_mode=Manual
  - test_marketplace_settings
- feat(user-profile): User Profile DocType + 20 migration patch eklendi (@aliiball)
  - 3 profil DocType (Buyer Profile + Seller Profile + Verified Supplier) tek User Profile + Admin Seller Profile mimarisine taşındı (Sprint 2)
  - can_buy/can_sell capability flag'leri, account_type Individual/Business
  - patches/user_profile_v1 (01-20) migration serisi: doctype create, verification_kind, index, controller noop, buyer/seller migrate, hybrid merge, member_id, link/dynamic_link refs, user_permissions, user_types, scoring fields, tenant placeholder, scheduler events, validate, deprecate old, owner fix, kyc_kyb_split (19), normalize_capability_flags (20)
  - hooks.py: User Profile permission query + has_permission + Sprint 2 buyer metric/scoring scheduler events
  - setup/install.py: Sprint 2 kapsamında 5 rol (Buyer, Seller, Marketplace Admin, Marketplace Seller, Marketplace Buyer); 14 hiyerarşik rol Sprint 3 RBAC reformuna ertelendi
  - 3 workspace JSON: Seller Profile → User Profile + Admin Seller Profile
  - test_user_profile
- feat(kyc): KYC Verification DocType + 4 endpoint + checkout gate eklendi (@aliiball)
  - KYC Verification DocType: account_type toggle (Business/Individual), Kurumsal alanları (company_name, tax_id, phone, email_field, address, billing_address) + ortak identity_document
  - api/v1/kyc.py: submit_kyc_documents / review_kyc / get_kyc_status / get_prefill_data 4 endpoint
  - get_prefill_data cross-form prefill — User Profile + son KYC/KYB Verification'dan değerler birleşik
  - cart.py _ensure_buyer_kyc_verified — create_order başında KYC.Verified zorunluluğu, [KYC_<STATE>] prefix'li mesaj
  - gate add_to_cart'tan kaldırıldı (sadece create_order'da)
  - test_kyc_gate + test_kyc_verification
- feat(capability-invariant): Sprint 2.6 status-bazlı auth flags eklendi (@aliiball)
  - auth.py get_user_profile seller bloğu User Profile mimarisine taşındı (legacy alias: business_name=company_name, contact_phone=phone)
  - is_seller artık can_sell capability + "Seller" rolü fallback
  - kyc_locked/kyb_locked formülü "not can_buy/can_sell" yerine kyc_status=='Locked'/kyb_status=='Locked' (status-bazlı semantik)
  - kyc_required/kyb_required Pending|Rejected listesi
  - get_session_user response: kyc_required, kyb_required, kyc_locked, kyb_locked flag'leri
  - register_user registration_type param (Alici/Satici)
  - test_capability_flag_invariant
- feat(kyb): mersis_no + kep_address + rejection_category eklendi (@aliiball)
  - KYB Verification.mersis_no (16 hane) + kep_address (email format)
  - rejection_category Select (Re-submit | Suspended) — KYC ve KYB ayrı
  - verification_kind alanı kaldırıldı (KYC ayrı DocType'a taşındı)
  - document_expiry_date kaldırıldı (Soru 8 — expiry yok)
  - faaliyet_belgesi opsiyonel oldu
  - kyb_verification.py table_exists("Seller Profile") backward compat guard + 10 satır dormant blok kaldırıldı
  - api/v1/kyb.py User Profile mimarisine taşındı
- feat(changelog): v2.1.0-beta.1 sürüm notları eklendi (@aliiball)
  - Sprint 1 Adres Mimarisi + Sprint 2 User Profile + Sprint 2.6 capability invariant + KYC/KYB ayrımı bullet'ları
  - CLAUDE.md aktif mimari memory referansları (§6.1) eklendi
- feat(seo): SEO yönetim modülü, social proof ve arama API'leri eklendi (@ahmeetseker)
  - SEO Redirect, SEO 404 Log, Static Page SEO, Listing View Counter doctype'ları eklendi
  - tradehub_core/seo/ paketi (redirect handler + 404 logger) ve seed_static_pages script'i
  - api/seo.py + api/seo_admin.py — public/admin SEO endpoint'leri
  - Social Proof Settings doctype + api/social_proof.py + test'leri
  - api/search.py arama servisi ve test'leri eklendi
  - api/listing.py view counter, SEO meta ve filtre alanları için genişletildi
  - hooks.py: yeni doctype'lar, fixtures ve scheduler entry'leri
- feat(authz): yetki sistemi FAZ 1-5 — entitlement, RBAC bundle, (@boraydeger32)
  - Region, Feature Catalog, Subscription Plan, Subscription Plan Region, Store Subscription, Pricing Plan Feature DocType'ları.
  - entitlement/ modülü (core, checks, sync) + entitlement_snapshot API.
  - Custom fields ve PII permlevel patch'leri.
  - Approval Rule + Approval Rule Approver + Order Approval + Order Approval Log DocType'ları.
  - services/approval_workflow.py + order_approval_hooks.py + API.
  - Buyer Approver L1/L2 rolleri ve role profile bundle'ları.
  - PII Field Policy + PII Jurisdiction Rule DocType'ları, utils/pii*, Compliance Officer rolü, jurisdiction-aware masking.
  - Approved Supplier List/Entry + supplier_whitelist service.
  - Cost Center DocType + service.
  - Authorization Anomaly Rule/Alert + detector + actions (saatlik scheduler).
  - Role Delegation + Role Change Log + delegation_service + rebac_drift_detection (günlük scheduler).
  - Owner Transfer Request + owner_transfer service.
  - Pricing Plan custom fields + presets + real prices patch'leri.
  - public_pricing API (storefront sell sayfası için).
  - Signup CTA unification + commission rates repair.
  - Buyer Admin/Procurement/Finance/Viewer, Seller Admin/Co-Owner/ Finance/Staff/Viewer, Platform Admin/Finance, Support Agent rolleri.
  - role_docperms seed + role_profiles sync + ADL buyer_org field.
  - audit/ modülü (log, tasks, user_hooks) + Authorization Decision Log DocType + Permission Override Log.
  - authorization_simulator (Süper Admin debug aracı).
  - permission_console API + buyer_team + seller_users sub-user invite.
  - rebac_client + tuple_sync (ReBAC sidecar entegrasyonu).
  - permissions.py +657 satır (DocType bazlı yetki kuralları).
  - utils/tenant.py +495 satır (tenant isolation hardening).
  - hooks.py: 18 yeni patch, scheduler event'leri, doc_events.
  - tests/: 20+ yeni test dosyası (tenant, abac, anomaly, approval, delegation, entitlement, organization hierarchy, PII, procurement, rebac, simulator, sub-users, tuple sync).
- feat(bulk-import): toplu ürün içe aktarma sistemi eklendi (@aliiball)
  - BulkImportJob ve BulkImportJobError DocType'ları
  - Excel/CSV/XML parser'ları, persister ve image matcher
  - Çok dilli kolon eşleme için regex destekli ingestion
  - Background runner + worker task'ları (RQ)
  - Bildirim entegrasyonu ve hata satırı raporlama
  - v15_bulk_import_init patch'i ile DocType + örnek veri seed
  - EcaRule, EcaRuleLog, EcaActionTemplate DocType'ları
  - Dispatcher: event çözümleme, condition eval, action execution
  - SafeRegex ve validator katmanı (DoS-safe pattern çalıştırma)
  - API endpoint'leri ve permission entegrasyonu
  - Hooks.py: doc_events üzerinden tetikleyici kayıtları
  - Birim testleri (eca/tests/)
  - RegexPatternLibrary ve RegexPatternEntry DocType'ları
  - BulkImport ve ECA kullanır (kolon başlığı → field mapping)
  - Seed patch ile T1+T2 alan paterni hazır gelir
  - SellerTemplateProfile DocType eklendi
  - dashboard.py kaldırıldı, mantık dashboard_engine.py altında toplandı
  - Total users widget patch'i UserProfile'a yönlendirildi
  - permissions.py: ECA + BulkImport için yeni yetki tanımları
  - utils/security.py: rate-limit yardımcısı eklendi
  - api/listing.py: seller_sku döner, ECA tetikleyicileri bağlandı
- feat(privacy): GDPR/KVKK Faz 3.5 — veri taşınabilirlik, onay yönetimi ve ROPA (@ahmeetseker)
  - Veri dışa aktarma (GDPR Madde 20): şifre doğrulamalı export talebi, token bazlı güvenli indirme, süresi dolan export'ların otomatik temizliği
  - Onay yönetimi: consent kayıt/geri çekme API'leri, kullanıcı onay durumu sorgulama
  - ROPA export (GDPR Madde 30): JSON/CSV formatında kayıt dışa aktarma
  - Veri saklama politikası: günlük otomatik anonimleştirme enforcement
  - DPA yönetimi: haftalık süre sonu uyarı e-postaları
  - SEO iyileştirmeleri: CDN cache stratejisi (s-maxage), hardcoded SEO tag temizleme, listing slug/code çözümleme
  - Yeni DocType'lar: Tracking Settings, Consent Policy Version, Data Export Request, Data Processing Agreement, Data Retention Policy, Processing Activity Record, User Consent Log
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor
- feat(plans): plan/özellik entitlement modeli + storefront pricing tutarlılığı (@boraydeger32)
  - Feature Catalog API: list/create/update/delete/restore/reorder (feature_catalog.py)
  - Plan Feature matris API: list_plan_features + bulk_update_plan_features (plan_features.py)
  - value_type feature seviyesine taşındı (boolean/quota/enum/text); feature_catalog + pricing_plan_feature şema güncellemesi
  - public_pricing: komisyon & aktif ürün limiti için plan field TEK OTORİTE (kart ↔ karşılaştırma tablosu birebir; Sınırsız/Özel/binlik ayraç biçimi)
  - patch'ler (v15_6_20..23): matris seed, value_type storefront, içerik seed, legacy temizlik
- feat(core): satış sıralaması ve 2 aşamalı hakediş akışı eklendi (@ahmeetseker)
  - Category Showcase Settings/Tile doctype'ları ve storefront API'si (get_active_tiles) eklendi
  - Ürün detayına kategori bazlı satış sıralaması hesabı eklendi (rekabet sıralaması, 1 saat cache)
  - get_mega_menu 3 seviyeli nested kategori ağacı döndürecek şekilde genişletildi
  - Saha hakedişine 2 aşamalı onay (leader_approve/leader_reject) ve Sales Team/Member doctype'ları eklendi
  - Paket bazlı kota bonusu (Field Commission Quota Tier) ve recompute_quota_bonus eklendi
  - Field Commission Settings: global_per_sale_amount kaldırıldı, kota dönemine indirgendi
  - Üç yeni patch eklendi (iki aşamalı durum, kind/period, global tutar düşürme)

### Duzeltildi
- fix(release): son tag bilgisini güncelledi ve boş guard sorununu çözdü (@ahmeetseker)
- fix(identity): email_verified UPDATE SQL User Profile tablosuna yönlendirildi (@aliiball)
  - identity.py 6 yerde UPDATE tabBuyer Profile SQL'i tabUser Profile'a taşındı — email_verified flag artık doğru tabloya yazılıyor
  - register_supplier User Profile Sprint 2.6 davranışına uyarlandı
  - LIVE BUG
- fix(permissions): seller_balance permission Admin Seller Profile.name'e taşındı (@aliiball)
  - permissions.py seller_balance permission kullanıcı email'i yerine _get_seller_profile_name(user) (Admin Seller Profile.name) lookup
  - permissions.py docstring örnekleri "Seller Profile" → "Admin Seller Profile"
- fix(seo): seller storefront page_resolver ve slug registry'si düzeltildi (@ahmeetseker)
  - Admin Seller Profile için SLUG_FIELD_MAP `slug` → `seller_code` olarak düzeltildi (DB kolonu yoktu, lookup boş dönüyordu)
  - TEMPLATE_MAP'te seller template yolu `pages/seller/seller-shop.html` → `seller-storefront.html` güncellendi
  - static_pages_registry'de /markalar → /ureticiler ve /firsat → /firsatlar yenilendi, başlık "Tüm Üreticiler" oldu
  - get_seller API'sinde sertifikalar ayrı `frappe.get_all` ile çekildi, yalnız `verification_status = Verified` olanlar storefront'a sızar
  - Brand schema breadcrumb'unda yanlış /markalar atfı kaldırıldı (o URL aslında Üreticiler sayfasına gidiyordu)
- fix(hooks): Regex Pattern Library dict'inde eksik brace düzeltildi (@aliiball)
  - doc_events["Regex Pattern Library"] iç dict'i `},` ile kapatılmamış, sonraki tüm doctype'lar bu dict'in içine gömülüyordu
  - permission_query_conditions parse hatası giderildi
- fix(api): SEO URL geçişi sonrası kırılan endpoint'leri düzelt (@ahmeetseker)
  - listing.py: kaldırılmış is_verified sütununu sorgulardan temizle
  - listing.py: _format_listing_card'da href'i /urun/{slug} formatına geçir
  - listing.py: slug eksik olan 2 sorguya slug field'ı ekle
  - seller.py: get_sellers ürün listesine slug field'ı ekle
  - identity.py: register created_via değerini seller_application olarak düzelt
  - seo_admin.py: Static Page SEO kayıtlarını lazy auto-create et
- fix(pricing): ReBAC/ABAC pricing table schema, validation ve entitlement düzeltmeleri (@boraydeger32)
  - Subscription Plan DocType'a 8 eksik alan eklendi (badge_label, badge_color, theme, short_tagline, commission_rate, max_active_listings, cta_label, cta_action) + pricing_features Table field — public_pricing API artık çalışıyor
  - Store Subscription state machine'e trial→past_due geçişi eklendi (M2)
  - Capability flag validation: tanımsız key'ler artık reject ediliyor (M4)
  - Override JSON key whitelist: plan'da olmayan key'ler reddediliyor (M5)
  - Subscription lifecycle idempotent hale getirildi — race condition önlemi (M6)
  - Entitlement negative cache TTL 60s→10s (K2)
  - ABAC context'e order_region eklendi + N+1 category extraction batch fetch (R2)
  - Authorization simulator UNAVAILABLE→DENY fail-closed mapping (R3)
  - Drift detection'a Store Subscription eklendi (R4)
  - Approval workflow'a entitlement quota guard eklendi — key guard dahil (R1)
  - Feature Catalog + Subscription Plan seed data (3 plan, 13 feature, 20 bullet)
  - Product Category external_id reqd kaldırıldı (migration uyumu)
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(roles): role.json fixture'ı Sprint 2 hiyerarşisine sadeleştirildi (@aliiball)
  - 14 hiyerarşik rol Sprint 3 RBAC reformuna kadar setup/install.py'de kod tabanında refere edilen 5 role indirgendi
  - role.json fixture %99 azaltıldı (146 → 1 satır)
- refactor(profile): 25 modül User Profile + Admin Seller Profile'a taşındı (@aliiball)
  - api/buyer.py + qa.py: _resolve_display_name User Profile + full_name
  - api/seller.py: 7 endpoint Admin Seller Profile (replace_all)
  - api/seller_addresses.py: _resolve_seller_profile Admin Seller Profile
  - api/rfq.py: profiles batch fetch User Profile + Admin Seller Profile join (business/year_established/employee_count)
  - api/dashboard.py + kpi_dashboard.py: _profile_status_breakdown + _platform_totals tabBuyer Profile → tabUser Profile (can_buy=1 filter)
  - tradehub_core/api/seller.py + scoring/engine.py + utils/erpnext_sync.py + utils/seller_payout.py + webhooks/erpnext_hooks.py Sprint 2 uyumu
  - doctype controller temizliği: buyer_profile, seller_profile, listing_review, rfq_quote, seller_application, seller_balance, seller_product
  - utils/auth_guards.py: is_email_verified User Profile'a taşındı
  - utils/tenant_seller_validation.py: Senaryo B bypass Sprint 3'e ertelendi
  - tasks.py: User Profile terminolojisi + Sprint 2 scheduler events
  - translations/en.csv + tr.csv: User Profile/Admin Seller Profile/ Mağaza Profili stringleri güncellendi
- refactor(tests): test_cross_app_link_resolution Sprint 2.6 mimarisine uyarlandı (@aliiball)
  - verification_kind testi kaldırıldı (KYC ayrı DocType'a taşındı)
  - KYC Verification DocType varlığı eklendi
  - legacy assertion temizliği (~580 satır)
- refactor(changelog): manuel v2.1.0-beta.1 entry'si geri alındı (@aliiball)
  - beta-release.yml workflow'unun LAST_PROD-beta.N hesabıyla çakışıyordu
  - Ali → version-15 merge sonrası workflow doğru versiyonu (v1.0.9-beta.3) ve (@author) suffix'lerini otomatik üretecek
- refactor(changelog): v2.1.0-beta.1 release bloğu kaldırıldı (@ahmeetseker)
  - 413af5e revert'i Ali → version-15 back-merge sırasında uygulanmayıp v2.1.0-beta.1 bloğu version-15 üstünde kaldı, istoc-changelog viewer hatalı release gösteriyordu
  - v1.0.9-beta.2 içindeki yanıltıcı "feat(changelog): v2.1.0-beta.1 sürüm notları eklendi" bullet'ı temizlendi
  - v1.0.9-beta.3 içindeki revert kayıt bullet'ı, audit izi olarak bırakıldı
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)
- refactor(doctype): DocType etiketleri Modül olarak güncellendi (@aliiball)
  - Dashboard Widget: source_doctype label "Kaynak Modül"
  - ECA Action Template: create_doctype label "Oluşturulacak Modül"
  - Regex Pattern Library: target_doctype label "Hedef Modül"

---
## [v1.0.9-beta.29] - 2026-06-05 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor
- feat(plans): plan/özellik entitlement modeli + storefront pricing tutarlılığı (@boraydeger32)
  - Feature Catalog API: list/create/update/delete/restore/reorder (feature_catalog.py)
  - Plan Feature matris API: list_plan_features + bulk_update_plan_features (plan_features.py)
  - value_type feature seviyesine taşındı (boolean/quota/enum/text); feature_catalog + pricing_plan_feature şema güncellemesi
  - public_pricing: komisyon & aktif ürün limiti için plan field TEK OTORİTE (kart ↔ karşılaştırma tablosu birebir; Sınırsız/Özel/binlik ayraç biçimi)
  - patch'ler (v15_6_20..23): matris seed, value_type storefront, içerik seed, legacy temizlik
- feat(core): satış sıralaması ve 2 aşamalı hakediş akışı eklendi (@ahmeetseker)
  - Category Showcase Settings/Tile doctype'ları ve storefront API'si (get_active_tiles) eklendi
  - Ürün detayına kategori bazlı satış sıralaması hesabı eklendi (rekabet sıralaması, 1 saat cache)
  - get_mega_menu 3 seviyeli nested kategori ağacı döndürecek şekilde genişletildi
  - Saha hakedişine 2 aşamalı onay (leader_approve/leader_reject) ve Sales Team/Member doctype'ları eklendi
  - Paket bazlı kota bonusu (Field Commission Quota Tier) ve recompute_quota_bonus eklendi
  - Field Commission Settings: global_per_sale_amount kaldırıldı, kota dönemine indirgendi
  - Üç yeni patch eklendi (iki aşamalı durum, kind/period, global tutar düşürme)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)
- refactor(doctype): DocType etiketleri Modül olarak güncellendi (@aliiball)
  - Dashboard Widget: source_doctype label "Kaynak Modül"
  - ECA Action Template: create_doctype label "Oluşturulacak Modül"
  - Regex Pattern Library: target_doctype label "Hedef Modül"

---
## [v1.0.9-beta.28] - 2026-06-05 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor
- feat(plans): plan/özellik entitlement modeli + storefront pricing tutarlılığı (@boraydeger32)
  - Feature Catalog API: list/create/update/delete/restore/reorder (feature_catalog.py)
  - Plan Feature matris API: list_plan_features + bulk_update_plan_features (plan_features.py)
  - value_type feature seviyesine taşındı (boolean/quota/enum/text); feature_catalog + pricing_plan_feature şema güncellemesi
  - public_pricing: komisyon & aktif ürün limiti için plan field TEK OTORİTE (kart ↔ karşılaştırma tablosu birebir; Sınırsız/Özel/binlik ayraç biçimi)
  - patch'ler (v15_6_20..23): matris seed, value_type storefront, içerik seed, legacy temizlik
- feat(core): satış sıralaması ve 2 aşamalı hakediş akışı eklendi (@ahmeetseker)
  - Category Showcase Settings/Tile doctype'ları ve storefront API'si (get_active_tiles) eklendi
  - Ürün detayına kategori bazlı satış sıralaması hesabı eklendi (rekabet sıralaması, 1 saat cache)
  - get_mega_menu 3 seviyeli nested kategori ağacı döndürecek şekilde genişletildi
  - Saha hakedişine 2 aşamalı onay (leader_approve/leader_reject) ve Sales Team/Member doctype'ları eklendi
  - Paket bazlı kota bonusu (Field Commission Quota Tier) ve recompute_quota_bonus eklendi
  - Field Commission Settings: global_per_sale_amount kaldırıldı, kota dönemine indirgendi
  - Üç yeni patch eklendi (iki aşamalı durum, kind/period, global tutar düşürme)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)
- refactor(doctype): DocType etiketleri Modül olarak güncellendi (@aliiball)
  - Dashboard Widget: source_doctype label "Kaynak Modül"
  - ECA Action Template: create_doctype label "Oluşturulacak Modül"
  - Regex Pattern Library: target_doctype label "Hedef Modül"

---
## [v1.0.9-beta.27] - 2026-06-05 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor
- feat(plans): plan/özellik entitlement modeli + storefront pricing tutarlılığı (@boraydeger32)
  - Feature Catalog API: list/create/update/delete/restore/reorder (feature_catalog.py)
  - Plan Feature matris API: list_plan_features + bulk_update_plan_features (plan_features.py)
  - value_type feature seviyesine taşındı (boolean/quota/enum/text); feature_catalog + pricing_plan_feature şema güncellemesi
  - public_pricing: komisyon & aktif ürün limiti için plan field TEK OTORİTE (kart ↔ karşılaştırma tablosu birebir; Sınırsız/Özel/binlik ayraç biçimi)
  - patch'ler (v15_6_20..23): matris seed, value_type storefront, içerik seed, legacy temizlik

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)
- refactor(doctype): DocType etiketleri Modül olarak güncellendi (@aliiball)
  - Dashboard Widget: source_doctype label "Kaynak Modül"
  - ECA Action Template: create_doctype label "Oluşturulacak Modül"
  - Regex Pattern Library: target_doctype label "Hedef Modül"

---
## [v1.0.9-beta.26] - 2026-06-04 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)
- refactor(doctype): DocType etiketleri Modül olarak güncellendi (@aliiball)
  - Dashboard Widget: source_doctype label "Kaynak Modül"
  - ECA Action Template: create_doctype label "Oluşturulacak Modül"
  - Regex Pattern Library: target_doctype label "Hedef Modül"

---
## [v1.0.9-beta.25] - 2026-06-04 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)
- feat(dashboard): scope-resolution gate ile satıcı widget görünürlüğü düzeltildi (@aliiball)
  - _user_can_read kaldırıldı; yerine _widget_is_safe scope-resolution gate
  - _check_dashboard_access ile URL crafting saldırılarına karşı koruma (satıcı platform_overview veya başka satıcının scope'unu çağıramaz)
  - Dashboard Widget'a first-class scope_field column eklendi (config_json'dan auto-backfill + save-time validation)
  - DEFAULT_SCOPE_FIELDS 5'ten 13 doctype'a genişletildi (RFQ, Cart, Conversation, Seller Application, Brand, HD Ticket vb.)
  - backfill_widget_scope_field patch'i mevcut widget'ları yeni column'a göçürür (idempotent)
  - get_default_scope_fields whitelist endpoint UI auto-populate için
  - list_widgets_for_admin artık resolved_scope_field döndürüyor

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.24] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.23] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur
- fix(plans): v15_6_19 retry patch — Patch Log bypass for plan seed (@boraydeger32)

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.22] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.21] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık
- fix(plans): v15_6_18 patch ignore_links + allowed_regions skip (@boraydeger32)
  - allowed_regions field skip — admin sonradan ekleyebilir
  - doc.flags.ignore_links = True — Region/Currency vs. fixture eksikse link validation bypass; plan'ın temel pricing/feature alanları seed olur

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.20] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test
- feat(plans): Plan CRUD + v15_6_18 fixture seed + plan_code case fix (@boraydeger32)
  - Fixture'dan Subscription Plan kayıtlarını DB'ye idempotent insert
  - Frappe v15 `bench migrate` fixture import etmediği için (sadece schema + patches.txt) beta'da plan'lar hiç yaratılmamıştı → storefront pricing boş, admin panel Planlar tab boş
  - Patch hem lowercase hem UPPERCASE name kontrolü ile mevcut kayıtları korur; sadece tamamen eksik senaryoyu kapatır
  - Public pricing cache flush sonrası storefront anında dolu görür
  - create_subscription_plan(plan_code, plan_name, monthly_price, ...) → System Manager-only (Marketplace Admin engellendi, Faz F.4 ile uyum) → Default is_public=False (admin önce capability/quota doldurur) → Audit log HIGH severity, rule_id: auth.admin_plan_crud
  - delete_subscription_plan(plan_code) → _PROTECTED_PLAN_CODES (FREE/STARTER/PRO/ENTERPRISE) silinemez → Aktif/trial Store Subscription varsa engellenir → Cascade: pricing_features child + cache flush → Audit HIGH
  - _PLAN_CODE_PATTERN: ^([a-z][a-z0-9_-]*|[A-Z][A-Z0-9_-]*)$ (lowercase VEYA UPPERCASE; mixed case yasak)
  - _normalize_plan_code artık case'i zorla değiştirmez — sadece strip + validate
  - Mevcut DB UPPERCASE plan'lar (FREE/STARTER/PRO/ENTERPRISE) save sırasında hata vermez; lowercase custom plan'lar (pro-annual, premium) yeni eklenir
  - test_rebac_abac_e2e_phaseD: import sırası düzeltildi (test_authorization_simulator frappe stub'ı kuruyor, sim import'u sonra)

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.19] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık

### Degistirildi
- refactor(tests): rebac/abac e2e testinde tekrarlı types importu kaldırıldı (@aliiball)

---
## [v1.0.9-beta.18] - 2026-06-03 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor
- feat(chat): TeamsLike buyer↔seller chat with Jitsi video calls (@aliturguttursab)
  - api/chat.py: Chatwoot-backed threads, buyer external-identity JWT + seller token auth, seller auto-provisioning, attachments, and Jitsi video calls. start_video_call mints a per-user GUEST token (moderator:false) for the thread invite link so only the call initiator is moderator/host; the counterpart who opens the invite joins as a non-moderator participant.
  - api/reservation.py: Plus-tier reservation gating + seller availability slots, with a scheduler that expires stale reservations.
  - doctypes: Teamslike Settings, Chat Reservation, Seller Availability Slot.
  - patches: teamslike user fields, settings init, admin/seller chat tier.
- feat(rbac): Faz A-H — RBAC/ABAC/Pricing kapsamlı sertleştirme (@boraydeger32)
  - v15_6_11_resync_feature_catalog: 40 fixture entry DB'ye upsert
  - v15_6_12_sync_plan_capability_flags: FREE/STARTER/ENTERPRISE doldu
  - v15_6_13_seed_sales_tier_grants: Sales tier grant'ları
  - v15_6_14_seed_seller_sales_role_profile: Seller Sales Rep profile
  - v15_6_15_fix_quota_orders_unlimited: max_orders_per_month -1
  - seller_capabilities: _TIER_SALES_ROLES + _TIER_ROLE_FALLBACK
  - _validate_roles_assignable allowlist (System Manager engeli)
  - parent_profile protected klon engeli
  - 5 mutating endpoint methods=["POST"] (CSRF)
  - api/order.py 3 yerde ignore_permissions=True kaldırıldı
  - update_capability_grant + update_module_policy + update_plan_capability_flag log_decision (HIGH severity, context dolu)
  - reset_password + change_password + delete_account audit (HIGH)
  - _merge_plan_json_field helper: partial payload veri kaybı bug'ı
  - update_pricing_plan + update_plan_capabilities MERGE semantiği (default)
  - _validate_capability_flags deprecated key reject
  - api/v1/subscription.upgrade_subscription_plan self-service endpoint
  - list_assignable_roles power-role filter
  - v15_6_16_seed_protected_module_flags: 6 modül is_protected=1
  - create/update/delete_role_profile object_doctype + name audit alanları
  - _PRICING_FINANCIAL_FIELDS: Marketplace Admin fiyat erişimi yok
  - authorization_simulator._enforce_positive_affirm: SKIP→ALLOW fail-open kapandı
  - abac_context.normalize_amount_to_eur: TCMB Currency Rate Pair lookup
  - workflow.py orchestrator scaffold (authorize / authorize_or_throw)
  - v15_6_17_reset_enterprise_public_flag: storefront sızıntı engeli
  - subscription_plan._sanitize_rich_text_fields: XSS koruması
  - rule_id naming: auth.admin_module_policy_toggle
  - test_protected_module_cannot_be_hidden_via_policy e2e test

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı
- fix(kyc-kyb): admin doctype görünürlük ve validation iyileştirmeleri (@aliiball)
  - KYC submit_kyc_documents rate limit gevşetildi (1/60s -> 10/300s); kullanıcı validation hatası alıp düzeltirken 429'a takılmıyor
  - KYC validation hataları (TCKN/VKN, dosya uzantısı, zorunlu alan eksik, rejection reason) Error Log'a defer_insert ile yazılır oldu; PII güvenliği için sadece metadata loglanıyor, hassas değerler loglanmıyor
  - KYB company_title ve KYC account_type/company_name alanlarına permlevel 1 eklendi; admin paneldeki list view'da artık dolu görünüyor
  - KYC tab_review yapısı KYB ile aynı hale getirildi: depends_on kaldırıldı, reviewed_by ve reviewed_at field'ları tab_account'tan tab_review'e taşındı, Doğrulama Bilgileri section break eklendi
  - KYC submitted_at field'ı kaldırıldı; Frappe built-in creation aynı bilgiyi tutuyor, KYB ile tutarlılık sağlandı
  - KYB rejection_reason ve notes alanları sadece Rejected/Suspended'da görünür hale getirildi; Pending'de boş textarea görünmüyor artık

---
## [v1.1.0-beta.1] - 2026-06-02 BETA — Sprint 6: DB-driven RBAC + Süper Admin Konsolu

Sprint 6 yetki ve maskeleme altyapısını **kod sabitlerinden DB-driven hale** getirir. Süper admin artık tek panelden capability, modül görünürlüğü, plan kapısı ve PII maskeleme kurallarını koddan bağımsız yönetir. 96 yeni E2E test paketi (`test_sprint6_rbac.py`) regresyon kalkanı.

### Eklendi

- feat(rbac): TH Capability Registry + TH Capability Grant DocType'ları — capability listesi ve role profile grant matrisi DB'leştirildi (@boraydeger32)
  - `tradehub_core/doctype/th_capability_registry/` — capability_key, label, module_group, default_tier, is_owner_only, is_protected, requires_kyc, requires_aml, plan_feature_flag
  - `tradehub_core/doctype/th_capability_grant/` — (role_profile, capability) unique pair, granted flag, expires_at TTL, audit metadata
  - Seed: `SELLER_CAPABILITIES` Python dict + `_TIER_*` frozenset → 31 capability + 94 grant matrix
  - `is_protected` flag ile UI'dan silinemez korumalı capability'ler
- feat(rbac): TH Module Registry + TH Module Policy DocType'ları — sidebar item ve modül görünürlük politikası DB-driven (@boraydeger32)
  - `tradehub_core/doctype/th_module_registry/` — tree DocType, panel/section_key/parent hiyerarşisi, item_type (section/group/item), route/doctype_ref hedef
  - `tradehub_core/doctype/th_module_policy/` — (module, role_profile) unique pair, mode (visible/masked/hidden), condition_json (ABAC opsiyonel)
  - Seed: `navigation.js` sidebar item'ları → 75+ modül + 263 hidden policy (sub-user gating)
- feat(rbac): `tradehub_core/utils/permission_resolver.py` — DB-first cache'li resolver (@boraydeger32)
  - `get_capabilities(user)` — TH Capability Grant'tan capability seti (Redis 5dk TTL, key: `tradehub:cap:user:*`)
  - `get_module_mode_map(user, panel)` — Modül key → mode haritası
  - `get_navigation_tree(user, panel)` — Frontend-ready sidebar JSON
  - `apply_field_mask(value, pattern)` — 6 pattern: none/last4/initials/iban_xxx_last4/bullets/email_domain
  - hooks: `on_capability_*_change`, `on_module_*_change`, `on_user_role_change` ile otomatik cache invalidation
- feat(rbac): `seller_capabilities.has_seller_capability` DB-first + Python fallback (@boraydeger32)
  - TH Capability Registry'den metadata (is_owner_only/requires_kyc/plan_feature_flag) okur
  - TH Capability Grant'tan role profile match kontrolü
  - K6 Role Delegation fallback Python `_TIER_*` set'lerinden devam
  - `get_user_capabilities()` aynı pattern — `get_session_user` payload'unda `capabilities` listesi
- feat(api): Süper Admin Konsolu endpoint'leri — `tradehub_core/api/v1/permission_console.py` (@boraydeger32)
  - `list_capabilities()` — capability + grant matrix JSON
  - `update_capability_grant(role_profile, capability, granted, note)` — single cell toggle, fail-secure protected check
  - `list_modules_tree(panel)` — module tree + policy matrix
  - `update_module_policy(module, role_profile, mode, note)` — single cell mode set, protected hidden reddedilir
  - `list_rbac_audit(limit)` — Frappe Version + Authorization Decision Log birleştirilmiş timeline
  - `list_plan_capability_sync()` — Capability Registry plan_feature_flag ↔ Subscription Plan capability_flags tutarlılık tespiti
  - `update_plan_capability_flag(plan_codes, feature_flag, enabled)` — bulk plan capability_flags güncelleme + entitlement cache flush
- feat(api): `get_navigation(panel)` endpoint — `tradehub_core/api/v1/navigation.py` frontend için hazır sidebar tree (@boraydeger32)
- feat(api): CRM list maskeleme — `crm_overrides.crm_list_contacts` + `apply_list_masking` helper (@boraydeger32)
  - Frontend `frappe.client.get_list` yerine bu custom endpoint çağırır
  - Per-field capability kontrolü (view.customer_pii / view.bank_info / view.tax_id)
  - Per-row `_masked_fields` listesi UI badge rendering için
- feat(rbac): Field-level PII maskeleme `on_load` hook — `tradehub_core/api/v1/crm_masking.py` (@boraydeger32)
  - `mask_pii_fields(doc, method)` doc_event handler — Contact / Admin Seller Profile / User Profile
  - Rate-limited audit log (`pii_mask_log:{user}:{doctype}` cache key, 1 saat TTL)
  - `doc.flags._masked_fields` ile frontend için maskeleme listesi
- feat(rbac): Frappe Desk PII koruması — Property Setter + Custom DocPerm (@boraydeger32)
  - `tradehub_core/setup/pii_permlevel_setup.py` — idempotent permlevel uygulama helper
  - PII alanları (iban, tax_id, bank_name, account_holder, email_id, phone, mobile_no) → permlevel 2
  - Privileged role'ler (Seller Owner, Co-Owner, Compliance Officer, System Manager, Marketplace Admin) → read=1
  - Non-privileged role'ler ("Seller", "Marketplace Seller") → read=0 (Frappe DocType migrate side-effect temizliği)
- feat(api): Backend serializer maskeleme — `api/v1/auth.get_user_profile` (@boraydeger32)
  - Sub-user için IBAN / bank_name / account_holder (view.bank_info kapısı)
  - Sub-user için tax_id (view.tax_id kapısı)
  - Response'a `_masked: {bank_info, tax_id}` flag eklendi
- feat(api): `api/order.py` shipping_address maskeleme (`view.customer_shipping` kapısı) (@boraydeger32)
- feat(ui): Süper Admin Konsolu Vue 3 paneli — `admin-panel/frontend/src/views/system/PermissionConsoleView.vue` 10 tab (@boraydeger32)
  - Yeni: PermissionOverviewTab (KPI + audit timeline + Plan Sync uyarı bandı)
  - Yeni: CapabilityMatrixTab (matrix + bulk grant + per-plan toggle + role highlight + masked event chip)
  - Yeni: ModuleMatrixTab (3-state tree + collapse + korumalı modül modal)
  - Mevcut: RolesTab (Sprint 6'da capability bölümü eklendi)
  - Embed: ComplianceMaskMatrixView, AuthorizationSimulatorView, AnomalyDashboardView
  - Mevcut: PlansTab, UsersTab, AuditLogTab (Sprint 5'te field-mask filtresi eklendi)
  - Router refactor: `?tab=...` query param ile deep link + browser back/forward
- feat(ui): `usePermission()` composable — `admin-panel/frontend/src/composables/usePermission.js` (@boraydeger32)
  - `can(capability)`, `seesModule(key)`, `moduleMode(key)`, `isMasked(key)`, `isHidden(key)`
  - `auth.js` `userCapabilities` Set'e dönüştürüldü (O(1) lookup)
  - `canAccess()` yeni tag: `capability:<key>`
- feat(ui): DB-driven sidebar — `stores/navigation.js` loadDbSections action (@boraydeger32)
  - Login sonrası `/api/method/.../get_navigation` paralel fetch (admin + seller panel)
  - Fail-safe fallback: backend ulaşılmazsa hard-coded `data/navigation.js`
- feat(ui): `DocTypeFormView.vue` — bullet karakterli değer için 🔒 Maskeli badge + tooltip (@boraydeger32)
- feat(ui): Owner-only / Korumalı capability detay panel banner'ları + Korumalı modül uyarı modal'ı (@boraydeger32)
- feat(ui): Bulk Capability Grant — "Tüm sub-user role'lerine ver/çek" tek tıklama + onay modalı (@boraydeger32)
- feat(rbac): Audit timeline genişletme — `pii.field_masked` event'lerini Frappe Version kayıtlarıyla birleştir (@boraydeger32)
  - `list_decision_logs` endpoint `action` filter + `context` field response
  - PermissionOverviewTab timeline'da maskeleme olayları (sarı tema, eye-off ikon)
  - AuditLogTab "🔒 Maskeleme" hızlı filtre preset + masked_fields chip render
- feat(rbac): Yeni capability'ler (@boraydeger32)
  - `view.tax_id` (default tier COOWNER) — KYB Verification + Admin Seller Profile tax_id okuma
  - `view.customer_pii` (default tier SALES, COOWNER+MANAGEMENT grant) — CRM Lead/Contact/Org email/phone okuma
- test: 96 E2E test paketi — `tradehub_core/tests/test_sprint6_rbac.py` (@boraydeger32)
  - TestSprint6_A (DocType existence + seed counts) — 11 test
  - TestSprint6_B (permission_resolver functions) — 7 test
  - TestSprint6_C (has_seller_capability decision chain) — 5 test
  - TestSprint6_D (permission_console endpoints) — 8 test
  - TestSprint6_E (navigation get_navigation) — 3 test
  - TestSprint6_F (cache invalidation hooks) — 2 test
  - TestSprint6_G (security boundaries) — 5 test
  - TestSprint6_H (E2E scenarios) — 3 test
  - TestSprint4_I (mask patterns) — 8 test
  - TestSprint4_J (view.tax_id capability) — 4 test
  - TestSprint5_K (view.customer_pii capability) — 3 test
  - TestSprint5_L (Contact PII masking handler) — 4 test
  - TestSprint5_M (Admin Seller Profile per-field) — 5 test
  - TestSprint5_N (plan capability sync) — 6 test
  - TestSprint5_O (update_plan_capability_flag) — 6 test
  - TestSprint5_P/P2 (mask audit log + endpoint integration) — 4 test
  - TestSprint5_Q (apply_list_masking) — 6 test
  - TestSprint5_R (Desk permlevel protection) — 5 test

### Düzeltildi

- fix(rbac): Seller Application onayında "Seller Owner" rolü atama eksik — Sprint 3'te planlanmış ama yapılmamış (Sprint 1 öncesi auth.is_owner çift kapı tutarsızlığı) (@boraydeger32)
  - `seller_application._approve_application` — Seller + Seller Owner rolleri + `tradehub_is_owner=1` + `tradehub_tenant=ASP.name` + `role_profile_name="Seller Full Access"`
  - `seller_application._revoke_approval` — Seller Owner rolü ve flag'leri geri al
  - Migration `v15_5_5_seller_owner_role_backfill` — mevcut Active ASP sahiplerine retroactive rol atama
- fix(rbac): sub-user için get_session_user'da kyb_status / is_verified_seller / can_sell tenant owner'dan miras alınır (önceki: kullanıcının kendi User Profile'ından, sub-user için yanlış) (@boraydeger32)

### Migration patches (sırasıyla)

```
tradehub_core.patches.v15_5_5_seller_owner_role_backfill
tradehub_core.patches.v15_6_0_seed_capability_registry
tradehub_core.patches.v15_6_1_seed_capability_grant
tradehub_core.patches.v15_6_2_seed_module_registry
tradehub_core.patches.v15_6_3_seed_module_policy
tradehub_core.patches.v15_6_4_seed_view_tax_id
tradehub_core.patches.v15_6_5_seed_view_customer_pii
tradehub_core.patches.v15_6_6_apply_pii_permlevel
tradehub_core.patches.v15_6_7_promote_pii_permlevel_to_2
tradehub_core.patches.v15_6_8_lock_non_privileged_pii_read
```

Hepsi **idempotent** — tekrar çalıştırılabilir, mevcut kayıtlara dokunmaz.

### Breaking Changes

- ⚠ Frappe Desk'te `Admin Seller Profile`, `User Profile`, `Contact` DocType'larındaki IBAN/tax_id/email_id vb. alanlar artık **permlevel 2**'de. Sub-user rolleri (`Seller`, `Marketplace Seller`) bu alanları göremez. Bu kasıtlı bir güvenlik değişikliğidir; eski davranışa dönülmesi önerilmez.
- ⚠ `auth.userCapabilities` artık `Array` değil `Set`. Eski kod `auth.userCapabilities.includes(...)` çağırıyorsa `auth.userCapabilities.has(...)` veya `auth.can(...)` ile değiştirilmeli.
- ⚠ `navigation.js`'deki `requires:[...]` tag'leri **geriye uyumlu** kalmaya devam ediyor (fallback), ancak gerçek sidebar visibility **TH Module Policy** kayıtlarından çözümleniyor. Hard-coded değişiklik production'da etki etmez — TH Module Policy düzenlenmeli.

### Deploy notları

Production deploy adımları için → `Sprint6-Production-Checklist.md`

---

## [v1.0.9-beta.15] - 2026-05-26 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)
- fix(stock): available_qty tercih edilerek stok hesaplaması düzeltildi (@ahmeetseker)
  - cart.py: stok kontrolü ve sepet response'da available_qty (= stock_qty - reserved_qty)
  - listing.py: get_listing_detail'de available_qty None kontrolü ile falsy 0 değeri sorunu giderildi
  - listing_stats.py: aynı None-safe available_qty fallback mantığı uygulandı

---
## [v1.0.9-beta.14] - 2026-05-26 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor

### Duzeltildi
- fix(security): address validation, AML gate, has_permission explicit deny (@boraydeger32)
  - buyer.py: reject invalid purpose/address_type with frappe.throw (no silent fallback)
  - buyer.py: add phone prefix-number consistency check for non-TR phones
  - seller_addresses.py: add missing _doc_to_dict fields (purpose, address_type, tax_no, tax_office)
  - seller_addresses.py: phone prefix consistency + ignore_permissions justification comments
  - buyer.py: add ignore_permissions justification comments on save/insert/delete
  - permissions.py: replace return None with return False in 6 has_permission functions (listing_review, review_helpful_vote, review_abuse_report, listing_question, order_dispute, trusted_reviewer_invitation) — prevents cross-tenant fall-through
  - permissions.py: listing_question_has_permission now grants seller read access to questions on their own listings
  - permissions.py: implement real AML/sanctions gate (_check_aml_sanctions) with KYB Verification aml_check_status/sanctions_status check + graceful fallback
  - seller_capabilities.py: implement real _check_aml_clean with same pattern
  - test_address_validators.py: 29 new E2E tests (purpose validation, phone prefix, company optional, alert→toast, field symmetry, DocType schema integrity)
  - test_rebac_abac_e2e.py: 123 new standalone tests (ABAC evaluators, capability matrix, tier hierarchy, KYC/AML sets, source audit, cross-layer consistency, frontend-backend sync, subscription plan fixtures)

---
## [v1.0.9-beta.13] - 2026-05-25 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(rbac): rol bazlı veri maskeleme, sub-user güvenlik düzeltmeleri ve demo data (@boraydeger32)
  - dashboard_engine.py'ye data_sensitivity + _should_mask + _mask_data katmanı
  - Dashboard Widget'a data_sensitivity custom field (financial/profit/balance/pii)
  - view.* capability'ler eklendi (7 adet: financial_summary, profit_detail, balance, bank_info, customer_full, customer_shipping, order_amounts)
  - Seller Sales Rep rol profili ve _TIER_SALES tier tanımı
  - Role_profile bazlı cache isolation (60s TTL) + invalidate_dashboard_cache()
  - Maskeleme kararları DECISION_FIELD_MASKED audit log'a yazılıyor

---
## [v1.0.9-rc.1] - 2026-05-25 RC

Bu surum rcistoc.cronbi.com'da onay asamasindadir.

### Eklendi
- feat(changelog): v1.0.10-beta.1 sürüm notları eklendi (@ahmeetseker)
- feat(addresses): Sprint 1 Faz D adres mimarisi eklendi (@aliiball)
  - Addresses DocType'a purpose (Delivery/Pickup/Billing), address_type (Individual/Business), tax_no, tax_office field'ları
  - kind field'ı deprecated etiketlendi (Sprint 4'te DROP)
  - company Business hesap tipi için koşullu reqd
  - utils/tax_validation.py: Maliye VKN + NVI TCKN checksum dispatcher
  - patches/address_v1 idempotent migration (01_kind_to_purpose, 02_fix_seller_purpose_pickup)
  - test_address_purpose_migration + test_tax_validation
- feat(marketplace-settings): Marketplace Settings Single DocType eklendi (@aliiball)
  - Pazaryeri çapında adres + fatura varsayılanları
  - default_address_type=Individual, address_type_toggle_visible=1, require_tax_id_business=1, invoice_generation_mode=Manual
  - test_marketplace_settings
- feat(user-profile): User Profile DocType + 20 migration patch eklendi (@aliiball)
  - 3 profil DocType (Buyer Profile + Seller Profile + Verified Supplier) tek User Profile + Admin Seller Profile mimarisine taşındı (Sprint 2)
  - can_buy/can_sell capability flag'leri, account_type Individual/Business
  - patches/user_profile_v1 (01-20) migration serisi: doctype create, verification_kind, index, controller noop, buyer/seller migrate, hybrid merge, member_id, link/dynamic_link refs, user_permissions, user_types, scoring fields, tenant placeholder, scheduler events, validate, deprecate old, owner fix, kyc_kyb_split (19), normalize_capability_flags (20)
  - hooks.py: User Profile permission query + has_permission + Sprint 2 buyer metric/scoring scheduler events
  - setup/install.py: Sprint 2 kapsamında 5 rol (Buyer, Seller, Marketplace Admin, Marketplace Seller, Marketplace Buyer); 14 hiyerarşik rol Sprint 3 RBAC reformuna ertelendi
  - 3 workspace JSON: Seller Profile → User Profile + Admin Seller Profile
  - test_user_profile
- feat(kyc): KYC Verification DocType + 4 endpoint + checkout gate eklendi (@aliiball)
  - KYC Verification DocType: account_type toggle (Business/Individual), Kurumsal alanları (company_name, tax_id, phone, email_field, address, billing_address) + ortak identity_document
  - api/v1/kyc.py: submit_kyc_documents / review_kyc / get_kyc_status / get_prefill_data 4 endpoint
  - get_prefill_data cross-form prefill — User Profile + son KYC/KYB Verification'dan değerler birleşik
  - cart.py _ensure_buyer_kyc_verified — create_order başında KYC.Verified zorunluluğu, [KYC_<STATE>] prefix'li mesaj
  - gate add_to_cart'tan kaldırıldı (sadece create_order'da)
  - test_kyc_gate + test_kyc_verification
- feat(capability-invariant): Sprint 2.6 status-bazlı auth flags eklendi (@aliiball)
  - auth.py get_user_profile seller bloğu User Profile mimarisine taşındı (legacy alias: business_name=company_name, contact_phone=phone)
  - is_seller artık can_sell capability + "Seller" rolü fallback
  - kyc_locked/kyb_locked formülü "not can_buy/can_sell" yerine kyc_status=='Locked'/kyb_status=='Locked' (status-bazlı semantik)
  - kyc_required/kyb_required Pending|Rejected listesi
  - get_session_user response: kyc_required, kyb_required, kyc_locked, kyb_locked flag'leri
  - register_user registration_type param (Alici/Satici)
  - test_capability_flag_invariant
- feat(kyb): mersis_no + kep_address + rejection_category eklendi (@aliiball)
  - KYB Verification.mersis_no (16 hane) + kep_address (email format)
  - rejection_category Select (Re-submit | Suspended) — KYC ve KYB ayrı
  - verification_kind alanı kaldırıldı (KYC ayrı DocType'a taşındı)
  - document_expiry_date kaldırıldı (Soru 8 — expiry yok)
  - faaliyet_belgesi opsiyonel oldu
  - kyb_verification.py table_exists("Seller Profile") backward compat guard + 10 satır dormant blok kaldırıldı
  - api/v1/kyb.py User Profile mimarisine taşındı
- feat(changelog): v2.1.0-beta.1 sürüm notları eklendi (@aliiball)
  - Sprint 1 Adres Mimarisi + Sprint 2 User Profile + Sprint 2.6 capability invariant + KYC/KYB ayrımı bullet'ları
  - CLAUDE.md aktif mimari memory referansları (§6.1) eklendi
- feat(seo): SEO yönetim modülü, social proof ve arama API'leri eklendi (@ahmeetseker)
  - SEO Redirect, SEO 404 Log, Static Page SEO, Listing View Counter doctype'ları eklendi
  - tradehub_core/seo/ paketi (redirect handler + 404 logger) ve seed_static_pages script'i
  - api/seo.py + api/seo_admin.py — public/admin SEO endpoint'leri
  - Social Proof Settings doctype + api/social_proof.py + test'leri
  - api/search.py arama servisi ve test'leri eklendi
  - api/listing.py view counter, SEO meta ve filtre alanları için genişletildi
  - hooks.py: yeni doctype'lar, fixtures ve scheduler entry'leri
- feat(authz): yetki sistemi FAZ 1-5 — entitlement, RBAC bundle, (@boraydeger32)
  - Region, Feature Catalog, Subscription Plan, Subscription Plan Region, Store Subscription, Pricing Plan Feature DocType'ları.
  - entitlement/ modülü (core, checks, sync) + entitlement_snapshot API.
  - Custom fields ve PII permlevel patch'leri.
  - Approval Rule + Approval Rule Approver + Order Approval + Order Approval Log DocType'ları.
  - services/approval_workflow.py + order_approval_hooks.py + API.
  - Buyer Approver L1/L2 rolleri ve role profile bundle'ları.
  - PII Field Policy + PII Jurisdiction Rule DocType'ları, utils/pii*, Compliance Officer rolü, jurisdiction-aware masking.
  - Approved Supplier List/Entry + supplier_whitelist service.
  - Cost Center DocType + service.
  - Authorization Anomaly Rule/Alert + detector + actions (saatlik scheduler).
  - Role Delegation + Role Change Log + delegation_service + rebac_drift_detection (günlük scheduler).
  - Owner Transfer Request + owner_transfer service.
  - Pricing Plan custom fields + presets + real prices patch'leri.
  - public_pricing API (storefront sell sayfası için).
  - Signup CTA unification + commission rates repair.
  - Buyer Admin/Procurement/Finance/Viewer, Seller Admin/Co-Owner/ Finance/Staff/Viewer, Platform Admin/Finance, Support Agent rolleri.
  - role_docperms seed + role_profiles sync + ADL buyer_org field.
  - audit/ modülü (log, tasks, user_hooks) + Authorization Decision Log DocType + Permission Override Log.
  - authorization_simulator (Süper Admin debug aracı).
  - permission_console API + buyer_team + seller_users sub-user invite.
  - rebac_client + tuple_sync (ReBAC sidecar entegrasyonu).
  - permissions.py +657 satır (DocType bazlı yetki kuralları).
  - utils/tenant.py +495 satır (tenant isolation hardening).
  - hooks.py: 18 yeni patch, scheduler event'leri, doc_events.
  - tests/: 20+ yeni test dosyası (tenant, abac, anomaly, approval, delegation, entitlement, organization hierarchy, PII, procurement, rebac, simulator, sub-users, tuple sync).
- feat(bulk-import): toplu ürün içe aktarma sistemi eklendi (@aliiball)
  - BulkImportJob ve BulkImportJobError DocType'ları
  - Excel/CSV/XML parser'ları, persister ve image matcher
  - Çok dilli kolon eşleme için regex destekli ingestion
  - Background runner + worker task'ları (RQ)
  - Bildirim entegrasyonu ve hata satırı raporlama
  - v15_bulk_import_init patch'i ile DocType + örnek veri seed
  - EcaRule, EcaRuleLog, EcaActionTemplate DocType'ları
  - Dispatcher: event çözümleme, condition eval, action execution
  - SafeRegex ve validator katmanı (DoS-safe pattern çalıştırma)
  - API endpoint'leri ve permission entegrasyonu
  - Hooks.py: doc_events üzerinden tetikleyici kayıtları
  - Birim testleri (eca/tests/)
  - RegexPatternLibrary ve RegexPatternEntry DocType'ları
  - BulkImport ve ECA kullanır (kolon başlığı → field mapping)
  - Seed patch ile T1+T2 alan paterni hazır gelir
  - SellerTemplateProfile DocType eklendi
  - dashboard.py kaldırıldı, mantık dashboard_engine.py altında toplandı
  - Total users widget patch'i UserProfile'a yönlendirildi
  - permissions.py: ECA + BulkImport için yeni yetki tanımları
  - utils/security.py: rate-limit yardımcısı eklendi
  - api/listing.py: seller_sku döner, ECA tetikleyicileri bağlandı
- feat(privacy): GDPR/KVKK Faz 3.5 — veri taşınabilirlik, onay yönetimi ve ROPA (@ahmeetseker)
  - Veri dışa aktarma (GDPR Madde 20): şifre doğrulamalı export talebi, token bazlı güvenli indirme, süresi dolan export'ların otomatik temizliği
  - Onay yönetimi: consent kayıt/geri çekme API'leri, kullanıcı onay durumu sorgulama
  - ROPA export (GDPR Madde 30): JSON/CSV formatında kayıt dışa aktarma
  - Veri saklama politikası: günlük otomatik anonimleştirme enforcement
  - DPA yönetimi: haftalık süre sonu uyarı e-postaları
  - SEO iyileştirmeleri: CDN cache stratejisi (s-maxage), hardcoded SEO tag temizleme, listing slug/code çözümleme
  - Yeni DocType'lar: Tracking Settings, Consent Policy Version, Data Export Request, Data Processing Agreement, Data Retention Policy, Processing Activity Record, User Consent Log

### Duzeltildi
- fix(release): son tag bilgisini güncelledi ve boş guard sorununu çözdü (@ahmeetseker)
- fix(identity): email_verified UPDATE SQL User Profile tablosuna yönlendirildi (@aliiball)
  - identity.py 6 yerde UPDATE tabBuyer Profile SQL'i tabUser Profile'a taşındı — email_verified flag artık doğru tabloya yazılıyor
  - register_supplier User Profile Sprint 2.6 davranışına uyarlandı
  - LIVE BUG
- fix(permissions): seller_balance permission Admin Seller Profile.name'e taşındı (@aliiball)
  - permissions.py seller_balance permission kullanıcı email'i yerine _get_seller_profile_name(user) (Admin Seller Profile.name) lookup
  - permissions.py docstring örnekleri "Seller Profile" → "Admin Seller Profile"
- fix(seo): seller storefront page_resolver ve slug registry'si düzeltildi (@ahmeetseker)
  - Admin Seller Profile için SLUG_FIELD_MAP `slug` → `seller_code` olarak düzeltildi (DB kolonu yoktu, lookup boş dönüyordu)
  - TEMPLATE_MAP'te seller template yolu `pages/seller/seller-shop.html` → `seller-storefront.html` güncellendi
  - static_pages_registry'de /markalar → /ureticiler ve /firsat → /firsatlar yenilendi, başlık "Tüm Üreticiler" oldu
  - get_seller API'sinde sertifikalar ayrı `frappe.get_all` ile çekildi, yalnız `verification_status = Verified` olanlar storefront'a sızar
  - Brand schema breadcrumb'unda yanlış /markalar atfı kaldırıldı (o URL aslında Üreticiler sayfasına gidiyordu)
- fix(hooks): Regex Pattern Library dict'inde eksik brace düzeltildi (@aliiball)
  - doc_events["Regex Pattern Library"] iç dict'i `},` ile kapatılmamış, sonraki tüm doctype'lar bu dict'in içine gömülüyordu
  - permission_query_conditions parse hatası giderildi
- fix(api): SEO URL geçişi sonrası kırılan endpoint'leri düzelt (@ahmeetseker)
  - listing.py: kaldırılmış is_verified sütununu sorgulardan temizle
  - listing.py: _format_listing_card'da href'i /urun/{slug} formatına geçir
  - listing.py: slug eksik olan 2 sorguya slug field'ı ekle
  - seller.py: get_sellers ürün listesine slug field'ı ekle
  - identity.py: register created_via değerini seller_application olarak düzelt
  - seo_admin.py: Static Page SEO kayıtlarını lazy auto-create et
- fix(pricing): ReBAC/ABAC pricing table schema, validation ve entitlement düzeltmeleri (@boraydeger32)
  - Subscription Plan DocType'a 8 eksik alan eklendi (badge_label, badge_color, theme, short_tagline, commission_rate, max_active_listings, cta_label, cta_action) + pricing_features Table field — public_pricing API artık çalışıyor
  - Store Subscription state machine'e trial→past_due geçişi eklendi (M2)
  - Capability flag validation: tanımsız key'ler artık reject ediliyor (M4)
  - Override JSON key whitelist: plan'da olmayan key'ler reddediliyor (M5)
  - Subscription lifecycle idempotent hale getirildi — race condition önlemi (M6)
  - Entitlement negative cache TTL 60s→10s (K2)
  - ABAC context'e order_region eklendi + N+1 category extraction batch fetch (R2)
  - Authorization simulator UNAVAILABLE→DENY fail-closed mapping (R3)
  - Drift detection'a Store Subscription eklendi (R4)
  - Approval workflow'a entitlement quota guard eklendi — key guard dahil (R1)
  - Feature Catalog + Subscription Plan seed data (3 plan, 13 feature, 20 bullet)
  - Product Category external_id reqd kaldırıldı (migration uyumu)

### Degistirildi
- refactor(roles): role.json fixture'ı Sprint 2 hiyerarşisine sadeleştirildi (@aliiball)
  - 14 hiyerarşik rol Sprint 3 RBAC reformuna kadar setup/install.py'de kod tabanında refere edilen 5 role indirgendi
  - role.json fixture %99 azaltıldı (146 → 1 satır)
- refactor(profile): 25 modül User Profile + Admin Seller Profile'a taşındı (@aliiball)
  - api/buyer.py + qa.py: _resolve_display_name User Profile + full_name
  - api/seller.py: 7 endpoint Admin Seller Profile (replace_all)
  - api/seller_addresses.py: _resolve_seller_profile Admin Seller Profile
  - api/rfq.py: profiles batch fetch User Profile + Admin Seller Profile join (business/year_established/employee_count)
  - api/dashboard.py + kpi_dashboard.py: _profile_status_breakdown + _platform_totals tabBuyer Profile → tabUser Profile (can_buy=1 filter)
  - tradehub_core/api/seller.py + scoring/engine.py + utils/erpnext_sync.py + utils/seller_payout.py + webhooks/erpnext_hooks.py Sprint 2 uyumu
  - doctype controller temizliği: buyer_profile, seller_profile, listing_review, rfq_quote, seller_application, seller_balance, seller_product
  - utils/auth_guards.py: is_email_verified User Profile'a taşındı
  - utils/tenant_seller_validation.py: Senaryo B bypass Sprint 3'e ertelendi
  - tasks.py: User Profile terminolojisi + Sprint 2 scheduler events
  - translations/en.csv + tr.csv: User Profile/Admin Seller Profile/ Mağaza Profili stringleri güncellendi
- refactor(tests): test_cross_app_link_resolution Sprint 2.6 mimarisine uyarlandı (@aliiball)
  - verification_kind testi kaldırıldı (KYC ayrı DocType'a taşındı)
  - KYC Verification DocType varlığı eklendi
  - legacy assertion temizliği (~580 satır)
- refactor(changelog): manuel v2.1.0-beta.1 entry'si geri alındı (@aliiball)
  - beta-release.yml workflow'unun LAST_PROD-beta.N hesabıyla çakışıyordu
  - Ali → version-15 merge sonrası workflow doğru versiyonu (v1.0.9-beta.3) ve (@author) suffix'lerini otomatik üretecek
- refactor(changelog): v2.1.0-beta.1 release bloğu kaldırıldı (@ahmeetseker)
  - 413af5e revert'i Ali → version-15 back-merge sırasında uygulanmayıp v2.1.0-beta.1 bloğu version-15 üstünde kaldı, istoc-changelog viewer hatalı release gösteriyordu
  - v1.0.9-beta.2 içindeki yanıltıcı "feat(changelog): v2.1.0-beta.1 sürüm notları eklendi" bullet'ı temizlendi
  - v1.0.9-beta.3 içindeki revert kayıt bullet'ı, audit izi olarak bırakıldı

---
## [v1.0.9-beta.12] - 2026-05-25 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(pricing): ReBAC/ABAC pricing table schema, validation ve entitlement düzeltmeleri (@boraydeger32)
  - Subscription Plan DocType'a 8 eksik alan eklendi (badge_label, badge_color, theme, short_tagline, commission_rate, max_active_listings, cta_label, cta_action) + pricing_features Table field — public_pricing API artık çalışıyor
  - Store Subscription state machine'e trial→past_due geçişi eklendi (M2)
  - Capability flag validation: tanımsız key'ler artık reject ediliyor (M4)
  - Override JSON key whitelist: plan'da olmayan key'ler reddediliyor (M5)
  - Subscription lifecycle idempotent hale getirildi — race condition önlemi (M6)
  - Entitlement negative cache TTL 60s→10s (K2)
  - ABAC context'e order_region eklendi + N+1 category extraction batch fetch (R2)
  - Authorization simulator UNAVAILABLE→DENY fail-closed mapping (R3)
  - Drift detection'a Store Subscription eklendi (R4)
  - Approval workflow'a entitlement quota guard eklendi — key guard dahil (R1)
  - Feature Catalog + Subscription Plan seed data (3 plan, 13 feature, 20 bullet)
  - Product Category external_id reqd kaldırıldı (migration uyumu)

---
## [v1.0.9-beta.11] - 2026-05-25 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(privacy): GDPR/KVKK Faz 3.5 — veri taşınabilirlik, onay yönetimi ve ROPA (@ahmeetseker)
  - Veri dışa aktarma (GDPR Madde 20): şifre doğrulamalı export talebi, token bazlı güvenli indirme, süresi dolan export'ların otomatik temizliği
  - Onay yönetimi: consent kayıt/geri çekme API'leri, kullanıcı onay durumu sorgulama
  - ROPA export (GDPR Madde 30): JSON/CSV formatında kayıt dışa aktarma
  - Veri saklama politikası: günlük otomatik anonimleştirme enforcement
  - DPA yönetimi: haftalık süre sonu uyarı e-postaları
  - SEO iyileştirmeleri: CDN cache stratejisi (s-maxage), hardcoded SEO tag temizleme, listing slug/code çözümleme
  - Yeni DocType'lar: Tracking Settings, Consent Policy Version, Data Export Request, Data Processing Agreement, Data Retention Policy, Processing Activity Record, User Consent Log

---
## [v1.0.9-beta.10] - 2026-05-25 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(api): SEO URL geçişi sonrası kırılan endpoint'leri düzelt (@ahmeetseker)
  - listing.py: kaldırılmış is_verified sütununu sorgulardan temizle
  - listing.py: _format_listing_card'da href'i /urun/{slug} formatına geçir
  - listing.py: slug eksik olan 2 sorguya slug field'ı ekle
  - seller.py: get_sellers ürün listesine slug field'ı ekle
  - identity.py: register created_via değerini seller_application olarak düzelt
  - seo_admin.py: Static Page SEO kayıtlarını lazy auto-create et

---
## [v1.0.9-beta.9] - 2026-05-22 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(hooks): Regex Pattern Library dict'inde eksik brace düzeltildi (@aliiball)
  - doc_events["Regex Pattern Library"] iç dict'i `},` ile kapatılmamış, sonraki tüm doctype'lar bu dict'in içine gömülüyordu
  - permission_query_conditions parse hatası giderildi

---
## [v1.0.9-beta.8] - 2026-05-22 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(seo): seller storefront page_resolver ve slug registry'si düzeltildi (@ahmeetseker)
  - Admin Seller Profile için SLUG_FIELD_MAP `slug` → `seller_code` olarak düzeltildi (DB kolonu yoktu, lookup boş dönüyordu)
  - TEMPLATE_MAP'te seller template yolu `pages/seller/seller-shop.html` → `seller-storefront.html` güncellendi
  - static_pages_registry'de /markalar → /ureticiler ve /firsat → /firsatlar yenilendi, başlık "Tüm Üreticiler" oldu
  - get_seller API'sinde sertifikalar ayrı `frappe.get_all` ile çekildi, yalnız `verification_status = Verified` olanlar storefront'a sızar
  - Brand schema breadcrumb'unda yanlış /markalar atfı kaldırıldı (o URL aslında Üreticiler sayfasına gidiyordu)

---
## [v1.0.9-beta.7] - 2026-05-22 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(bulk-import): toplu ürün içe aktarma sistemi eklendi (@aliiball)
  - BulkImportJob ve BulkImportJobError DocType'ları
  - Excel/CSV/XML parser'ları, persister ve image matcher
  - Çok dilli kolon eşleme için regex destekli ingestion
  - Background runner + worker task'ları (RQ)
  - Bildirim entegrasyonu ve hata satırı raporlama
  - v15_bulk_import_init patch'i ile DocType + örnek veri seed
  - EcaRule, EcaRuleLog, EcaActionTemplate DocType'ları
  - Dispatcher: event çözümleme, condition eval, action execution
  - SafeRegex ve validator katmanı (DoS-safe pattern çalıştırma)
  - API endpoint'leri ve permission entegrasyonu
  - Hooks.py: doc_events üzerinden tetikleyici kayıtları
  - Birim testleri (eca/tests/)
  - RegexPatternLibrary ve RegexPatternEntry DocType'ları
  - BulkImport ve ECA kullanır (kolon başlığı → field mapping)
  - Seed patch ile T1+T2 alan paterni hazır gelir
  - SellerTemplateProfile DocType eklendi
  - dashboard.py kaldırıldı, mantık dashboard_engine.py altında toplandı
  - Total users widget patch'i UserProfile'a yönlendirildi
  - permissions.py: ECA + BulkImport için yeni yetki tanımları
  - utils/security.py: rate-limit yardımcısı eklendi
  - api/listing.py: seller_sku döner, ECA tetikleyicileri bağlandı

---
## [v1.0.9-beta.6] - 2026-05-22 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(authz): yetki sistemi FAZ 1-5 — entitlement, RBAC bundle, (@boraydeger32)
  - Region, Feature Catalog, Subscription Plan, Subscription Plan Region, Store Subscription, Pricing Plan Feature DocType'ları.
  - entitlement/ modülü (core, checks, sync) + entitlement_snapshot API.
  - Custom fields ve PII permlevel patch'leri.
  - Approval Rule + Approval Rule Approver + Order Approval + Order Approval Log DocType'ları.
  - services/approval_workflow.py + order_approval_hooks.py + API.
  - Buyer Approver L1/L2 rolleri ve role profile bundle'ları.
  - PII Field Policy + PII Jurisdiction Rule DocType'ları, utils/pii*, Compliance Officer rolü, jurisdiction-aware masking.
  - Approved Supplier List/Entry + supplier_whitelist service.
  - Cost Center DocType + service.
  - Authorization Anomaly Rule/Alert + detector + actions (saatlik scheduler).
  - Role Delegation + Role Change Log + delegation_service + rebac_drift_detection (günlük scheduler).
  - Owner Transfer Request + owner_transfer service.
  - Pricing Plan custom fields + presets + real prices patch'leri.
  - public_pricing API (storefront sell sayfası için).
  - Signup CTA unification + commission rates repair.
  - Buyer Admin/Procurement/Finance/Viewer, Seller Admin/Co-Owner/ Finance/Staff/Viewer, Platform Admin/Finance, Support Agent rolleri.
  - role_docperms seed + role_profiles sync + ADL buyer_org field.
  - audit/ modülü (log, tasks, user_hooks) + Authorization Decision Log DocType + Permission Override Log.
  - authorization_simulator (Süper Admin debug aracı).
  - permission_console API + buyer_team + seller_users sub-user invite.
  - rebac_client + tuple_sync (ReBAC sidecar entegrasyonu).
  - permissions.py +657 satır (DocType bazlı yetki kuralları).
  - utils/tenant.py +495 satır (tenant isolation hardening).
  - hooks.py: 18 yeni patch, scheduler event'leri, doc_events.
  - tests/: 20+ yeni test dosyası (tenant, abac, anomaly, approval, delegation, entitlement, organization hierarchy, PII, procurement, rebac, simulator, sub-users, tuple sync).

---
## [v1.0.9-beta.5] - 2026-05-22 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(seo): SEO yönetim modülü, social proof ve arama API'leri eklendi (@ahmeetseker)
  - SEO Redirect, SEO 404 Log, Static Page SEO, Listing View Counter doctype'ları eklendi
  - tradehub_core/seo/ paketi (redirect handler + 404 logger) ve seed_static_pages script'i
  - api/seo.py + api/seo_admin.py — public/admin SEO endpoint'leri
  - Social Proof Settings doctype + api/social_proof.py + test'leri
  - api/search.py arama servisi ve test'leri eklendi
  - api/listing.py view counter, SEO meta ve filtre alanları için genişletildi
  - hooks.py: yeni doctype'lar, fixtures ve scheduler entry'leri

---
## [v1.0.9-beta.4] - 2026-05-20 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Degistirildi
- refactor(changelog): v2.1.0-beta.1 release bloğu kaldırıldı (@ahmeetseker)
  - 413af5e revert'i Ali → version-15 back-merge sırasında uygulanmayıp v2.1.0-beta.1 bloğu version-15 üstünde kaldı, istoc-changelog viewer hatalı release gösteriyordu
  - v1.0.9-beta.2 içindeki yanıltıcı "feat(changelog): v2.1.0-beta.1 sürüm notları eklendi" bullet'ı temizlendi
  - v1.0.9-beta.3 içindeki revert kayıt bullet'ı, audit izi olarak bırakıldı

---
## [v1.0.9-beta.3] - 2026-05-18 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Degistirildi
- refactor(changelog): manuel v2.1.0-beta.1 entry'si geri alındı (@aliiball)
  - beta-release.yml workflow'unun LAST_PROD-beta.N hesabıyla çakışıyordu
  - Ali → version-15 merge sonrası workflow doğru versiyonu (v1.0.9-beta.3) ve (@author) suffix'lerini otomatik üretecek

---
## [v1.0.9-beta.2] - 2026-05-18 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(addresses): Sprint 1 Faz D adres mimarisi eklendi (@aliiball)
  - Addresses DocType'a purpose (Delivery/Pickup/Billing), address_type (Individual/Business), tax_no, tax_office field'ları
  - kind field'ı deprecated etiketlendi (Sprint 4'te DROP)
  - company Business hesap tipi için koşullu reqd
  - utils/tax_validation.py: Maliye VKN + NVI TCKN checksum dispatcher
  - patches/address_v1 idempotent migration (01_kind_to_purpose, 02_fix_seller_purpose_pickup)
  - test_address_purpose_migration + test_tax_validation
- feat(marketplace-settings): Marketplace Settings Single DocType eklendi (@aliiball)
  - Pazaryeri çapında adres + fatura varsayılanları
  - default_address_type=Individual, address_type_toggle_visible=1, require_tax_id_business=1, invoice_generation_mode=Manual
  - test_marketplace_settings
- feat(user-profile): User Profile DocType + 20 migration patch eklendi (@aliiball)
  - 3 profil DocType (Buyer Profile + Seller Profile + Verified Supplier) tek User Profile + Admin Seller Profile mimarisine taşındı (Sprint 2)
  - can_buy/can_sell capability flag'leri, account_type Individual/Business
  - patches/user_profile_v1 (01-20) migration serisi: doctype create, verification_kind, index, controller noop, buyer/seller migrate, hybrid merge, member_id, link/dynamic_link refs, user_permissions, user_types, scoring fields, tenant placeholder, scheduler events, validate, deprecate old, owner fix, kyc_kyb_split (19), normalize_capability_flags (20)
  - hooks.py: User Profile permission query + has_permission + Sprint 2 buyer metric/scoring scheduler events
  - setup/install.py: Sprint 2 kapsamında 5 rol (Buyer, Seller, Marketplace Admin, Marketplace Seller, Marketplace Buyer); 14 hiyerarşik rol Sprint 3 RBAC reformuna ertelendi
  - 3 workspace JSON: Seller Profile → User Profile + Admin Seller Profile
  - test_user_profile
- feat(kyc): KYC Verification DocType + 4 endpoint + checkout gate eklendi (@aliiball)
  - KYC Verification DocType: account_type toggle (Business/Individual), Kurumsal alanları (company_name, tax_id, phone, email_field, address, billing_address) + ortak identity_document
  - api/v1/kyc.py: submit_kyc_documents / review_kyc / get_kyc_status / get_prefill_data 4 endpoint
  - get_prefill_data cross-form prefill — User Profile + son KYC/KYB Verification'dan değerler birleşik
  - cart.py _ensure_buyer_kyc_verified — create_order başında KYC.Verified zorunluluğu, [KYC_<STATE>] prefix'li mesaj
  - gate add_to_cart'tan kaldırıldı (sadece create_order'da)
  - test_kyc_gate + test_kyc_verification
- feat(capability-invariant): Sprint 2.6 status-bazlı auth flags eklendi (@aliiball)
  - auth.py get_user_profile seller bloğu User Profile mimarisine taşındı (legacy alias: business_name=company_name, contact_phone=phone)
  - is_seller artık can_sell capability + "Seller" rolü fallback
  - kyc_locked/kyb_locked formülü "not can_buy/can_sell" yerine kyc_status=='Locked'/kyb_status=='Locked' (status-bazlı semantik)
  - kyc_required/kyb_required Pending|Rejected listesi
  - get_session_user response: kyc_required, kyb_required, kyc_locked, kyb_locked flag'leri
  - register_user registration_type param (Alici/Satici)
  - test_capability_flag_invariant
- feat(kyb): mersis_no + kep_address + rejection_category eklendi (@aliiball)
  - KYB Verification.mersis_no (16 hane) + kep_address (email format)
  - rejection_category Select (Re-submit | Suspended) — KYC ve KYB ayrı
  - verification_kind alanı kaldırıldı (KYC ayrı DocType'a taşındı)
  - document_expiry_date kaldırıldı (Soru 8 — expiry yok)
  - faaliyet_belgesi opsiyonel oldu
  - kyb_verification.py table_exists("Seller Profile") backward compat guard + 10 satır dormant blok kaldırıldı
  - api/v1/kyb.py User Profile mimarisine taşındı

### Duzeltildi
- fix(identity): email_verified UPDATE SQL User Profile tablosuna yönlendirildi (@aliiball)
  - identity.py 6 yerde UPDATE tabBuyer Profile SQL'i tabUser Profile'a taşındı — email_verified flag artık doğru tabloya yazılıyor
  - register_supplier User Profile Sprint 2.6 davranışına uyarlandı
  - LIVE BUG
- fix(permissions): seller_balance permission Admin Seller Profile.name'e taşındı (@aliiball)
  - permissions.py seller_balance permission kullanıcı email'i yerine _get_seller_profile_name(user) (Admin Seller Profile.name) lookup
  - permissions.py docstring örnekleri "Seller Profile" → "Admin Seller Profile"

### Degistirildi
- refactor(roles): role.json fixture'ı Sprint 2 hiyerarşisine sadeleştirildi (@aliiball)
  - 14 hiyerarşik rol Sprint 3 RBAC reformuna kadar setup/install.py'de kod tabanında refere edilen 5 role indirgendi
  - role.json fixture %99 azaltıldı (146 → 1 satır)
- refactor(profile): 25 modül User Profile + Admin Seller Profile'a taşındı (@aliiball)
  - api/buyer.py + qa.py: _resolve_display_name User Profile + full_name
  - api/seller.py: 7 endpoint Admin Seller Profile (replace_all)
  - api/seller_addresses.py: _resolve_seller_profile Admin Seller Profile
  - api/rfq.py: profiles batch fetch User Profile + Admin Seller Profile join (business/year_established/employee_count)
  - api/dashboard.py + kpi_dashboard.py: _profile_status_breakdown + _platform_totals tabBuyer Profile → tabUser Profile (can_buy=1 filter)
  - tradehub_core/api/seller.py + scoring/engine.py + utils/erpnext_sync.py + utils/seller_payout.py + webhooks/erpnext_hooks.py Sprint 2 uyumu
  - doctype controller temizliği: buyer_profile, seller_profile, listing_review, rfq_quote, seller_application, seller_balance, seller_product
  - utils/auth_guards.py: is_email_verified User Profile'a taşındı
  - utils/tenant_seller_validation.py: Senaryo B bypass Sprint 3'e ertelendi
  - tasks.py: User Profile terminolojisi + Sprint 2 scheduler events
  - translations/en.csv + tr.csv: User Profile/Admin Seller Profile/ Mağaza Profili stringleri güncellendi
- refactor(tests): test_cross_app_link_resolution Sprint 2.6 mimarisine uyarlandı (@aliiball)
  - verification_kind testi kaldırıldı (KYC ayrı DocType'a taşındı)
  - KYC Verification DocType varlığı eklendi
  - legacy assertion temizliği (~580 satır)

---
## [v1.0.9-beta.1] - 2026-05-15 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Eklendi
- feat(changelog): v1.0.10-beta.1 sürüm notları eklendi (@ahmeetseker)

### Duzeltildi
- fix(release): son tag bilgisini güncelledi ve boş guard sorununu çözdü (@ahmeetseker)

---
## [v1.0.10-beta.1] - 2026-05-15 BETA

> Geriye dönük belgeleme — daha önce CHANGELOG'a girmemiş backend feature'ların kapsamı. Sürüm tag'i alınmamış DocType ve API katmanları bu entry altında toplandı.

### Eklendi
- feat(favorites): Buyer Favorite & Wishlist DocType'ları (`buyer_favorite_item`, `buyer_favorite_list`) + `api/favorites.py` (~438 satır, list/add/remove/list_favorite_items endpoint'leri) (@boraydeger32)
- feat(reviews-engine): Review risk scoring + sentiment analysis altyapısı — `review_risk_factor`, `review_risk_score`, `review_sentiment_analysis`, `review_translation`, `review_abuse_report`, `reviewer_reputation`, `review_analytics_snapshot` DocType'ları; `api/rating_engine.py`, `api/sentiment.py`, `api/risk.py` (@boraydeger32)
- feat(catalog): Product Family & Attribute Set mimarisi — `product_family`, `product_family_attribute`, `product_type`, `product_type_required_attribute`, `attribute_set`, `attribute_set_group`, `attribute_set_item`, `attribute_set_category_map` DocType'ları (marka/varyant/aile/attribute + satıcı izolasyonu) (@boraydeger32)
- feat(promotions): Coupon DocType — kupon/promosyon altyapısı (@TurksabYonetim)
- feat(email-preferences): E-posta tercih altyapısı — `email_preference_category`, `email_preference_item`, `user_email_preference` DocType'ları + `api/v1/email_preferences.py` (opt-out/abonelik yönetimi) (@ahmeetseker)
- feat(mobile): Mobil API token + push notification altyapısı — `mobile_api_token`, `push_subscription`, `push_notification_settings` DocType'ları (@boraydeger32)
- feat(moderation): Görsel moderasyon altyapısı — `image_moderation_log` + `moderation_rule` DocType'ları (@boraydeger32)
- feat(addresses): Buyer Address DocType (`addresses`) + `api/seller_addresses.py` (~372 satır, satıcı adres CRUD); kargo yöntemi DocType'ları (`shipping_method`, `shipping_method_item`) (@boraydeger32)
- feat(ab-testing): Listing A/B test altyapısı — `ab_test_variant`, `listing_ab_test` DocType'ları (@boraydeger32)
- feat(dashboard): Dashboard widget engine detayları — `dashboard_widget` + `dashboard_widget_role` DocType'ları (config tabanlı widget engine, 2 dashboard + 25 hazır widget) (@aliiball)

---
## [v1.0.9] - 2026-05-15 PROD

Bu surum canliya alindi. v1.0.8 PROD'dan bu yana beta + RC asamasinda test edilen tum feat/fix dahildir.

### Eklendi
- feat(changelog): commit body bullet'larını subject altında nested gösterildi (@ahmeetseker)
- feat: update auth and listing APIs to enhance seller profile management and listing visibility (@boraydeger32)
- feat(header-notice): 5 değişiklik (@ahmeetseker)
  - add Header Notice DocType schema and controller
  - add migration patch for Header Notice
  - add public API endpoint with 60s cache
  - wire cache invalidation via doc_events hooks
  - add display_mode settings + per-notice background_color

### Duzeltildi
- fix(ci): release workflow printf format string bug (@boraydeger32)
- fix(security): create_order price tampering + atomik stok flow + ECA RCE engeli (@boraydeger32)
  - api/cart.py: _recompute_order_items_server_side helper — client unit_price/total_price reddedilir, server listing/variant fiyatından recompute eder. is_sample flag'i listing.sample_price'a yönlendirir (numune siparişlerin selling_price ile faturalandığı 5x overcharge regresyonu kapatıldı). create_order 2-pass (önce tüm recompute, sonra Order doc create). Instant payment dalında deduct_stock_for_order çağrısı eklendi — kredi kartı/gateway ödemesinde reserved_qty kalıcı şişme + refund hayalet stok engeli.
  - api/order.py: cancel_order Order.stock_deducted'a göre doğru restore yolunu seçer (=1 ise restore_stock_for_refund stock_qty geri, =0 ise release_stock_for_order sadece reserved azalt). Eski davranış: havale dekontu sonrası iptal kalıcı stok kaybına yol açıyordu. Refund-approve dalındaki ad-hoc UPDATE bloğu silinip restore_stock_for_refund helper'ına yönlendirildi — variant_stock ve _recalculate_available + low-stock alert artık tutarlı.
  - utils/stock.py: reserve/release/deduct atomik UPDATE'lere çevrildi (COALESCE/GREATEST). reserve_stock_for_order tek deyimde `WHERE (stock_qty - reserved_qty) >= qty` ile race altında over-sell engeller; cursor.rowcount=0 → "Yetersiz stok" throw (paralel 3 istekten 2 başarılı + 1 reject). deduct_stock_for_order Order.stock_deducted flag'iyle idempotent (çift çağrı no-op). restore_stock_for_refund yeni — flag'e göre doğru yöne delta uygular. _lock_listing_row (SELECT ... FOR UPDATE) yardımcı eklendi.
  - eca/dispatcher.py: _execute_custom_script_action `exec(script, context)` yerine 3-katmanlı koruma — (1) rule'a son dokunan kullanıcının System Manager / Marketplace Admin rolü doğrulaması, (2) site config'inde server_script_enabled aktif değilse no-op, (3) Frappe RestrictedPython tabanlı safe_exec sandbox. Eski exec, ECA Rule write yetkisi alabilen herhangi bir rolün arbitrary Python (DB drop, file system, subprocess) yürütmesine açıktı; doğrulandı: DROP TABLE tabUser engellendi, tablo intact.
  - order.json: yeni stock_deducted (Check, default 0, read_only). Stok düşürme idempotency'sini ve refund/cancel yön kararını taşır.
  - order_item.json: yeni is_sample (Check). Sample (numune) satırının fiyat hesabını listing.sample_price'a yönlendirir.
- fix(category): search_platform_categories'de `_` shadow UnboundLocalError'unu gider (@boraydeger32)
  - Loop değişkeni `_depth` olarak yeniden adlandırıldı; gerekçe inline yorumla belgelendi.
  - Aynı dosyada Ruff auto-format: get_all `fields=[...]` array'i one-per-line hizalandı.
- fix(notifications): satıcı bildirimlerinde bozuk action_url'leri admin-panel route'larına yönlendir (@boraydeger32)
  - seller_category.py: kategori onay/red → /seller-categories (2 yer)
  - listing_review.py: ürün yorumu moderasyon/yayın/gizle → /review-moderation (3 yer; buyer'a giden /account/reviews bildirimleri dokunulmadı)
  - seller_review.py: satıcı değerlendirmesi yeni/gizle/yayınla → /review-moderation (3 yer)
  - seller_application.py: başvuru alındı/onaylandı/reddedildi → /dashboard (3 yer; cross-app navigation karmaşası olmasın diye genel landing)
- fix(release-workflows): commit body bullet'larını subject altında nested göster (@ahmeetseker)
- fix(release-workflows): commit body bullet'larini CHANGELOG'a dahil et (@ahmeetseker)
- fix(release): commit mesajındaki boşlukları temizlendi (@ahmeetseker)
- fix(header-notice): 3 değişiklik (@ahmeetseker)
  - use tab indentation and add search_index for filter fields
  - commit after setUpClass cleanup to ensure test isolation
  - drop auto-downgrade so storefront uses admin's chosen mode
- fix(api): API yanıtında hata mesajı düzeltildi (@ahmeetseker)

---
## [v1.0.8-rc.1] - 2026-05-15 RC

Bu surum onay asamasindadir. v1.0.8 PROD'dan bu yana beta tag'lerinde test edilen tum feat/fix bu RC entry'sinde toplanmistir.

### Eklendi
- feat(changelog): commit body bullet'larını subject altında nested gösterildi (@ahmeetseker)
- feat: update auth and listing APIs to enhance seller profile management and listing visibility (@boraydeger32)
- feat(header-notice): 5 değişiklik (@ahmeetseker)
  - add Header Notice DocType schema and controller
  - add migration patch for Header Notice
  - add public API endpoint with 60s cache
  - wire cache invalidation via doc_events hooks
  - add display_mode settings + per-notice background_color

### Duzeltildi
- fix(ci): release workflow printf format string bug (@boraydeger32)
- fix(security): create_order price tampering + atomik stok flow + ECA RCE engeli (@boraydeger32)
  - api/cart.py: _recompute_order_items_server_side helper — client unit_price/total_price reddedilir, server listing/variant fiyatından recompute eder. is_sample flag'i listing.sample_price'a yönlendirir (numune siparişlerin selling_price ile faturalandığı 5x overcharge regresyonu kapatıldı). create_order 2-pass (önce tüm recompute, sonra Order doc create). Instant payment dalında deduct_stock_for_order çağrısı eklendi — kredi kartı/gateway ödemesinde reserved_qty kalıcı şişme + refund hayalet stok engeli.
  - api/order.py: cancel_order Order.stock_deducted'a göre doğru restore yolunu seçer (=1 ise restore_stock_for_refund stock_qty geri, =0 ise release_stock_for_order sadece reserved azalt). Eski davranış: havale dekontu sonrası iptal kalıcı stok kaybına yol açıyordu. Refund-approve dalındaki ad-hoc UPDATE bloğu silinip restore_stock_for_refund helper'ına yönlendirildi — variant_stock ve _recalculate_available + low-stock alert artık tutarlı.
  - utils/stock.py: reserve/release/deduct atomik UPDATE'lere çevrildi (COALESCE/GREATEST). reserve_stock_for_order tek deyimde `WHERE (stock_qty - reserved_qty) >= qty` ile race altında over-sell engeller; cursor.rowcount=0 → "Yetersiz stok" throw (paralel 3 istekten 2 başarılı + 1 reject). deduct_stock_for_order Order.stock_deducted flag'iyle idempotent (çift çağrı no-op). restore_stock_for_refund yeni — flag'e göre doğru yöne delta uygular. _lock_listing_row (SELECT ... FOR UPDATE) yardımcı eklendi.
  - eca/dispatcher.py: _execute_custom_script_action `exec(script, context)` yerine 3-katmanlı koruma — (1) rule'a son dokunan kullanıcının System Manager / Marketplace Admin rolü doğrulaması, (2) site config'inde server_script_enabled aktif değilse no-op, (3) Frappe RestrictedPython tabanlı safe_exec sandbox. Eski exec, ECA Rule write yetkisi alabilen herhangi bir rolün arbitrary Python (DB drop, file system, subprocess) yürütmesine açıktı; doğrulandı: DROP TABLE tabUser engellendi, tablo intact.
  - order.json: yeni stock_deducted (Check, default 0, read_only). Stok düşürme idempotency'sini ve refund/cancel yön kararını taşır.
  - order_item.json: yeni is_sample (Check). Sample (numune) satırının fiyat hesabını listing.sample_price'a yönlendirir.
- fix(category): search_platform_categories'de `_` shadow UnboundLocalError'unu gider (@boraydeger32)
  - Loop değişkeni `_depth` olarak yeniden adlandırıldı; gerekçe inline yorumla belgelendi.
  - Aynı dosyada Ruff auto-format: get_all `fields=[...]` array'i one-per-line hizalandı.
- fix(notifications): satıcı bildirimlerinde bozuk action_url'leri admin-panel route'larına yönlendir (@boraydeger32)
  - seller_category.py: kategori onay/red → /seller-categories (2 yer)
  - listing_review.py: ürün yorumu moderasyon/yayın/gizle → /review-moderation (3 yer; buyer'a giden /account/reviews bildirimleri dokunulmadı)
  - seller_review.py: satıcı değerlendirmesi yeni/gizle/yayınla → /review-moderation (3 yer)
  - seller_application.py: başvuru alındı/onaylandı/reddedildi → /dashboard (3 yer; cross-app navigation karmaşası olmasın diye genel landing)
- fix(release-workflows): commit body bullet'larını subject altında nested göster (@ahmeetseker)
- fix(release-workflows): commit body bullet'larini CHANGELOG'a dahil et (@ahmeetseker)
- fix(release): commit mesajındaki boşlukları temizlendi (@ahmeetseker)
- fix(header-notice): 3 değişiklik (@ahmeetseker)
  - use tab indentation and add search_index for filter fields
  - commit after setUpClass cleanup to ensure test isolation
  - drop auto-downgrade so storefront uses admin's chosen mode
- fix(api): API yanıtında hata mesajı düzeltildi (@ahmeetseker)

---
## [v1.0.8-beta.13] - 2026-05-14 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(ci): release workflow printf format string bug (@boraydeger32)

---
## [v1.0.8-beta.12] - 2026-05-14 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(security): create_order price tampering + atomik stok flow + ECA RCE engeli (@boraydeger32)
  - api/cart.py: _recompute_order_items_server_side helper — client unit_price/total_price reddedilir, server listing/variant fiyatından recompute eder. is_sample flag'i listing.sample_price'a yönlendirir (numune siparişlerin selling_price ile faturalandığı 5x overcharge regresyonu kapatıldı). create_order 2-pass (önce tüm recompute, sonra Order doc create). Instant payment dalında deduct_stock_for_order çağrısı eklendi — kredi kartı/gateway ödemesinde reserved_qty kalıcı şişme + refund hayalet stok engeli.
  - api/order.py: cancel_order Order.stock_deducted'a göre doğru restore yolunu seçer (=1 ise restore_stock_for_refund stock_qty geri, =0 ise release_stock_for_order sadece reserved azalt). Eski davranış: havale dekontu sonrası iptal kalıcı stok kaybına yol açıyordu. Refund-approve dalındaki ad-hoc UPDATE bloğu silinip restore_stock_for_refund helper'ına yönlendirildi — variant_stock ve _recalculate_available + low-stock alert artık tutarlı.
  - utils/stock.py: reserve/release/deduct atomik UPDATE'lere çevrildi (COALESCE/GREATEST). reserve_stock_for_order tek deyimde `WHERE (stock_qty - reserved_qty) >= qty` ile race altında over-sell engeller; cursor.rowcount=0 → "Yetersiz stok" throw (paralel 3 istekten 2 başarılı + 1 reject). deduct_stock_for_order Order.stock_deducted flag'iyle idempotent (çift çağrı no-op). restore_stock_for_refund yeni — flag'e göre doğru yöne delta uygular. _lock_listing_row (SELECT ... FOR UPDATE) yardımcı eklendi.
  - eca/dispatcher.py: _execute_custom_script_action `exec(script, context)` yerine 3-katmanlı koruma — (1) rule'a son dokunan kullanıcının System Manager / Marketplace Admin rolü doğrulaması, (2) site config'inde server_script_enabled aktif değilse no-op, (3) Frappe RestrictedPython tabanlı safe_exec sandbox. Eski exec, ECA Rule write yetkisi alabilen herhangi bir rolün arbitrary Python (DB drop, file system, subprocess) yürütmesine açıktı; doğrulandı: DROP TABLE tabUser engellendi, tablo intact.
  - order.json: yeni stock_deducted (Check, default 0, read_only). Stok düşürme idempotency'sini ve refund/cancel yön kararını taşır.
  - order_item.json: yeni is_sample (Check). Sample (numune) satırının fiyat hesabını listing.sample_price'a yönlendirir.

---
## [v1.0.8-beta.10] - 2026-05-13 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(category): search_platform_categories'de `_` shadow UnboundLocalError'unu gider (@boraydeger32)
  - Loop değişkeni `_depth` olarak yeniden adlandırıldı; gerekçe inline yorumla belgelendi.
  - Aynı dosyada Ruff auto-format: get_all `fields=[...]` array'i one-per-line hizalandı.

---
## [v1.0.8-beta.9] - 2026-05-13 BETA

Bu surum betaistoc.cronbi.com'da test asamasindadir.

### Duzeltildi
- fix(notifications): satıcı bildirimlerinde bozuk action_url'leri admin-panel route'larına yönlendir (@boraydeger32)
  - seller_category.py: kategori onay/red → /seller-categories (2 yer)
  - listing_review.py: ürün yorumu moderasyon/yayın/gizle → /review-moderation (3 yer; buyer'a giden /account/reviews bildirimleri dokunulmadı)
  - seller_review.py: satıcı değerlendirmesi yeni/gizle/yayınla → /review-moderation (3 yer)
  - seller_application.py: başvuru alındı/onaylandı/reddedildi → /dashboard (3 yer; cross-app navigation karmaşası olmasın diye genel landing)

---
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
