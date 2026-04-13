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
