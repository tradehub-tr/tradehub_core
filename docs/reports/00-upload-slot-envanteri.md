# T-001 — Upload slot envanteri (tam liste)

**Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2` · **Faz 2'nin girdisi**

Bu belge sistemdeki **her medya yükleme alanını** listeler. Amaç yeniden tasarım
değil, **eksiğin yerini göstermek**: kod tabanında zaten çalışan bir mekanizma
varsa bu belge onu anlatır ve kaynağını gösterir.

---

## 0. Yöntem — sayılar nereden geldi

| Sayı | Nasıl ölçüldü |
|---|---|
| **199** doctype klasörü | `ls tradehub_core/tradehub_core/doctype/ \| wc -l` (1 satır `__init__.py`, yani 198 doctype) |
| **41** dosya-tutan alan | Python taraması: her `*/*.json` içinde `doctype == "DocType"` olan dosyaların `fields[]` dizisinde `fieldtype ∈ {Attach, Attach Image, Image}` |
| **30** doctype | Yukarıdaki 41 alanın dağıldığı benzersiz doctype sayısı |
| **0** adet `fieldtype: "Image"` | Aynı tarama — `Image` tipi bu kod tabanında hiç kullanılmıyor; hepsi `Attach` (18) ve `Attach Image` (23) |
| **8** kayıtlı "canlı kullanım" kaynağı | `tradehub_core/media/usage.py:32-41` `LIVE_SOURCES` sabiti |
| **8.200** satır | `wc -l tradehub_core/media/*.py` toplamı (yalnız `media/` modülü; storefront + panel upload UI dahil değil) |

Tarama komutu (yeniden üretilebilir):

```bash
cd /Users/ahmet/Desktop/istoc-medya-wt
python3 - <<'EOF'
import json, glob
for p in sorted(glob.glob('tradehub_core/tradehub_core/doctype/*/*.json')):
    try: d = json.load(open(p))
    except Exception: continue
    if not isinstance(d, dict) or d.get('doctype') != 'DocType': continue
    for f in d.get('fields', []) or []:
        if f.get('fieldtype') in ('Attach', 'Attach Image', 'Image'):
            print(d['name'], f['fieldname'], f['fieldtype'], sep=' | ')
EOF
```

**Ölçülemeyen:** Docker kapalı, üretim veritabanı ve canlı site erişimi yok.
Gerçek dosya sayıları, gerçek piksel boyutları, gerçek en-boy oranı dağılımı ve
tarayıcıda hesaplanmış (computed) kutu ölçüleri bu belgede **YOK**. CSS kutu
ölçüleri **kaynak koddaki utility sınıflarından** okundu; Tailwind varsayılan
ölçeğiyle px'e çevrildi (`1rem = 16px`, `w-32 = 8rem = 128px`). §9'a bakınız.

---

## 1. Doğrulama katmanları — tabloda kullanılan kısaltmalar

Tablodaki "mevcut doğrulama" sütunu bu dört katmana atıf yapar. **Bu katmanlar
zaten kodda var**; T-001 onları yeniden tasarlamıyor, yerini gösteriyor.

### L0 — Global `File` kancası (HER yükleme yolunda)

`tradehub_core/hooks.py:227-252` → `doc_events["File"]["before_insert"]`:

```
tradehub_core.utils.security.reject_unsafe_files      ← kapı
tradehub_core.entitlement.checks.check_media_storage_quota
```

`utils/security.py:68` `reject_unsafe_files()` yasak uzantı listesini uygular,
sonra `:96` satırında `_apply_upload_policy(doc)` çağırır →
`media/upload_policy.py:307` `check()`. L0'ın uyguladıkları:

| Kural | Kaynak |
|---|---|
| Yasak uzantı (svg/html/js/xml…) | `utils/security.py:90` `_DENIED_EXTENSIONS` |
| Dosya adı temizliği (yol karakteri, `\0`, 140 karakter kırpma) | `upload_policy.py:272-291` |
| Boyut tavanı: görsel 25 MB / video 200 MB / belge 50 MB / bilinmeyen 50 MB | `upload_policy.py:67-76` |
| Gerçekleşebilir tavan = min(bizim, Frappe `max_file_size`) | `upload_policy.py:262-265` |
| Tehlikeli içerik (ilk 512 bayt `<html`, `<svg`, `<script`, `<?xml`, `<%`, `#!/`) | `upload_policy.py:187-224` |
| İçerik/uzantı uyuşmazlığı → **uyarı**, ret değil | `upload_policy.py:366-369` |

L0 **atlanır**: `in_install / in_install_app / in_migrate / in_patch / in_import /
in_test` bayraklarında (`utils/security.py:102-109`) ve bulk-import kanalında
(`utils/security.py:85-88`).

> **L0'ın yapmadıkları:** piksel boyutu kontrolü, en-boy oranı kontrolü, slot
> başına adet limiti, slot başına MIME allowlist'i. **Hiçbir slot için yok.**

### L1 — Uca özel sunucu doğrulaması (yalnız 3 uç)

| Uç | Ek kural | Kaynak |
|---|---|---|
| `seller_media.upload_media` | Dar izin listesi: yalnız image/video + `.pdf` (`media_endpoint=True`) | `upload_policy.py:79-80`, `:334-340` |
| `api/v1/identity.update_profile_image` | Uzantı `.jpg/.jpeg/.png/.webp/.gif` + 5 MB sert tavan | `api/v1/identity.py:940-955` |
| `api/v1/kyb.upload_kyb_document` | Uzantı allowlist + **magic-byte** + 10 MB + `is_private=1` | `api/v1/kyb.py:439-458` |

### L2 — İstemci ön kontrolü

Sunucudan alınan sınırlarla çalışan tek doğru uygulama:
`admin-panel/frontend/src/utils/uploadPolicy.js` (sınırlar
`seller_media.upload_limits`'ten gelir, istemciye **yazılmaz**). Geri kalan
ekranlarda L2 = elle yazılmış `accept` özniteliği ve/veya elle yazılmış MB
sabiti — sunucuyla ayrışabilir.

### L3 — Slot semantiği (boyut / oran / adet / rol)

**Sistemde hiç yok.** Tabloda bu yüzden her satırın notu aynı yöne bakar.

---

## 2. Tablo A — Backend DocType alanları (41 alan / 30 doctype)

Sıra alfabetik (doctype). `slot_key` bu belgede önerilen kanonik anahtardır;
kodda **henüz karşılığı yoktur** — Faz 2'nin üreteceği kayıt defterinin adıdır.

| slot_key | doctype.field | rol | iş amacı | mevcut doğrulama | render edildiği bileşen(ler) | CSS kutu ölçüsü | en-boy oranı | not |
|---|---|---|---|---|---|---|---|---|
| `seller.logo` | `Admin Seller Profile.logo` (Attach Image) | satıcı + admin | Mağaza logosu — mağaza sayfası, ürün sayfası satıcı paneli, üretici listesi | L0. Panelde önerilen ölçü metni var (`DocTypeFormView.vue:448` → `400×400`) ama **zorlanmıyor** | `tradehubfront/src/components/seller/CompanyInfo.ts:47`; `.../CompanyProfile.ts:1030` | 120×auto px (CompanyInfo, `w-[120px] h-auto object-contain`); 48×48 px kutu (CompanyProfile, `w-12 h-12`, `object-contain`) | serbest — `object-contain`, kırpılmıyor | `usage.py:39` `LIVE_SOURCES`'ta kayıtlı (`seller_logo`). Ölçü tavsiyesi UI metni, L3 değil |
| `seller.banner` | `Admin Seller Profile.banner_image` (Attach Image) | satıcı + admin | Mağaza üst bandı | L0. Önerilen `1600×400` (`DocTypeFormView.vue:448`) — zorlanmıyor | ÖLÇÜLEMEDİ — storefront'ta `banner_image` alanını okuyan bir bileşen bulunamadı (grep `banner_image` → yalnız panel) | ÖLÇÜLEMEDİ | 4:1 (yalnız tavsiye) | **`LIVE_SOURCES`'ta YOK** → bu görsel silme kararında "kullanılmıyor" görünür. Bkz. §7-B1 |
| `seller.gallery_image` | `Seller Gallery Image.image` (Attach Image) | satıcı | Mağaza/fabrika galerisi | L0 | `tradehubfront/src/utils/seller/section-registry.ts:571-573`; `.../manufacturers/ManufacturerList.ts:353-357` | vitrin: `aspect-square` hücre, grid `grid-cols-2 sm:3 lg:4 gap-3`, kap `max-w-[1200px] px-4 lg:px-8` → lg'de ≈ **276×276 px**; üretici listesi 165×165 px (xl: 220×220 px) | **1:1**, `object-cover` (kırpılıyor) | `LIVE_SOURCES:38` (`seller_gallery`). Yüklenen görsel kare değilse merkezden kırpılır — uyarı yok |
| `seller.gallery_video` | `Seller Gallery Image.video_url` (Attach) | satıcı | Galeri video öğesi | L0 (video tavanı 200 MB, ama alan açıklaması "maks 10MB" diyor) | `tradehubfront/src/components/seller/CompanyProfile.ts:998-1002` | ÖLÇÜLEMEDİ (kap `w-full h-full`, dış kutu ölçülmedi) | ÖLÇÜLEMEDİ | **Metin/kod çelişkisi:** DocType açıklaması 10 MB, sunucu 200 MB (`upload_policy.py:69`), panel istemcisi 10 MB (`ListingFormView.vue:4169`). Üç ayrı sayı |
| `seller.gallery_poster` | `Seller Gallery Image.poster_image` (Attach Image) | satıcı | Video kapağı | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | `LIVE_SOURCES`'ta YOK |
| `brand.logo` | `Brand.logo` (Attach Image) | admin | Marka sayfası logosu | L0 | `tradehubfront/src/pages/brand.ts:101` | 96×96 px (`w-24 h-24`), md ≥768px'te 128×128 px (`md:w-32 md:h-32`), iç `p-3` = 12 px | serbest — `object-contain` | Küçük gösterim (`brand.ts:138`): 16×16 px (`w-4 h-4`) |
| `brand.hero_banner` | `Brand.hero_banner` (Attach Image) | admin | Marka sayfası üst görseli | L0. Alan açıklaması "önerilen 1920×400" (`brand.json`) — zorlanmıyor | `tradehubfront/src/pages/brand.ts:145-148` — CSS `background: url(...) center/cover` | Kap `container-boxed` = `max-width: var(--container-lg)` (`style.css:1540-1543`, yorumda **1840px**), yükseklik içerikten (`py-8 md:py-14`) | **serbest, `cover`** — sabit oran yok | Görsel `<img>` değil CSS background → `loading`/`decoding`/srcset uygulanamıyor. Bkz. §7-B4 |
| `brand.video` | `Brand.video_url` (Attach) | admin | Marka tanıtım videosu | L0. Açıklama "MP4/WebM, maks 10MB" — zorlanmıyor (sunucu 200 MB) | `tradehubfront/src/pages/brand.ts:188-215` | `padding-top: 56.25%` ile oranlı kutu, genişlik `container-boxed` | **16:9** (sabit) | Alan adı `video_url` ama tipi `Attach` — hem dosya hem YouTube/Vimeo URL kabul ediyor (`brand.ts:190-204`). Karma anlam |
| `bulk_import.data_file` | `Bulk Import Job.data_file` (Attach, **reqd**) | satıcı | Toplu ürün verisi (xlsx/csv/xml) | L0 **BYPASS EDİLİR** — `utils/security.py:85-88` bulk kanalını muaf tutar; kendi allowlist'i `bulk_import.api.upload_bulk_file` içinde | `admin-panel/.../BulkProductImportView.vue:667-671` | ÖLÇÜLEMEDİ (dosya, görsel değil) | — | `accept=".xlsx,.csv,.xml"`. Medya değil ama L0 muafiyeti taşıdığı için envanterde |
| `bulk_import.images_zip` | `Bulk Import Job.images_zip` (Attach) | satıcı | Ürün görselleri ZIP paketi | L0 bypass (aynı kanal) | `BulkProductImportView.vue:795-799` | — | — | **ZIP içindeki görseller L0'dan geçiyor mu bilinmiyor** → §9-M2 |
| `cart.snapshot_image` | `Cart Item.snapshot_image` (Attach Image) | sistem | Sepetteki ürünün o anki görseli | L0 (sistem yazıyor, kullanıcı yüklemiyor) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | **Yükleme slotu DEĞİL**, kopya alan. `usage.py:46` `ORDER_SOURCES` — silme kararında ayrı ağırlık |
| `category_showcase.tile_image` | `Category Showcase Tile.image` (Attach Image) | admin | Ana sayfa bento kategori döşemesi | L0 | `tradehubfront/src/components/category/CategoryShowcase.ts:154-165` | Hücre ölçüsü `col_span`/`row_span`'den geliyor (`spanClasses`, `CategoryShowcase.ts:137`) → **sabit px yok**; 1×1, 2×1 (geniş), 2×2 (hero) varyantları | Hücreye göre değişken; `object-cover` ile **kırpılıyor** | Tek bir görsel 3 farklı orana kırpılıyor ve yükleyene hangisi olduğu söylenmiyor. Bkz. §7-B2 |
| `gdpr.export_file` | `Data Export Request.file_url` (Attach) | sistem | KVKK veri dışa aktarımı | L0. `presets.py:52` **EXCLUDED_DOCTYPES** — optimizasyondan muaf | — | — | — | Kullanıcı yüklemesi değil, sistem çıktısı |
| `gdpr.dpa_document` | `Data Processing Agreement.document` (Attach) | admin | İmzalı sözleşme | L0 | — | — | — | `EXCLUDED_DOCTYPES`'ta **YOK** ama hassas belge. Bkz. §7-B5 |
| `hero_slide.background` | `Hero Slide.background_image` (Attach Image) | admin | Ana sayfa slider arka planı | L0 | `admin-panel/.../HeroSlideEditModal.vue:91-93` (yükleme); render: `tradehubfront/src/components/hero/HeroTopSlider.ts:134-140` | Slayt `h-full` — dış kutu ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | Render CSS `background`ile yapılıyor (`HeroTopSlider.ts:136`), `<img>` değil |
| `kyb.identity_document` | `KYB Verification.identity_document` (Attach, **reqd**) | satıcı | Kimlik belgesi (KVKK) | **L0 + L1** (`kyb.py:439-458`: allowlist + magic-byte + 10 MB + private) | `tradehubfront/src/alpine/kyb.ts:290-336`; `admin-panel/.../DocTypeFormView.vue:2263-2296` | SlotDropzone kutusu: **h-40 = 160 px** yükseklik, genişlik grid'den (`SlotDropzone.ts:95`); mobil `max-sm:h-32` = 128 px | serbest (`object-cover` küçük resim) | En sıkı korunan slot. `presets.py:44` EXCLUDED + `:73` EXCLUDED_MEDIA_FIELDS |
| `kyb.imza_sirkuleri` | `KYB Verification.imza_sirkuleri` (Attach, **reqd**) | satıcı | İmza sirküleri | L0 + L1 | aynı SlotDropzone | 160 px yükseklik | serbest | `EXCLUDED_MEDIA_FIELDS`'ta **YOK** → bkz. §7-B5 |
| `kyb.ticaret_sicil` | `KYB Verification.ticaret_sicil_gazetesi` (Attach, **reqd**) | satıcı | Ticaret sicil gazetesi | L0 + L1 | aynı | 160 px | serbest | `EXCLUDED_MEDIA_FIELDS`'ta YOK |
| `kyb.faaliyet_belgesi` | `KYB Verification.faaliyet_belgesi` (Attach, opsiyonel) | satıcı | Faaliyet belgesi | L0 + L1 | aynı | 160 px | serbest | `EXCLUDED_MEDIA_FIELDS`'ta YOK |
| `kyb.vergi_levhasi` | `KYB Verification.vergi_levhasi` (Attach, **reqd**) | satıcı | Vergi levhası | L0 + L1 | aynı | 160 px | serbest | `EXCLUDED_MEDIA_FIELDS`'ta YOK |
| `kyb.bank_account` | `KYB Verification.bank_account_document` (Attach, **reqd**) | satıcı | IBAN onaylı banka belgesi | L0 + L1 | aynı | 160 px | serbest | `presets.py:73` EXCLUDED_MEDIA_FIELDS'ta **VAR** |
| `kyc.identity_document` | `KYC Verification.identity_document` (Attach, **reqd**) | alıcı + satıcı | Bireysel/kurumsal kimlik | **L0**; L1 yok — bu slot Frappe `upload_file`'a gidiyor (`KycLayout.ts:376`) | `tradehubfront/src/components/kyc/KycLayout.ts:362-382` | SlotDropzone 160 px (mobil 128 px) | serbest | `compress: false` bilinçli (`KycLayout.ts:381`) — OCR okunabilirliği. `presets.py:71` EXCLUDED_MEDIA_FIELDS'ta VAR |
| `listing.primary_image` | `Listing.primary_image` (Attach Image) | satıcı | Ürün ana görseli | L0 | `tradehubfront/src/components/product/ProductImageGallery.ts:246-248`; kart: `.../shared/ProductCard.ts:13`, `.../shared/ListingCard.ts:163` | Ürün sayfası ana görsel: `aspect-square w-full max-w-[512px]` → **maks 512×512 px**; kart: `aspect-square` (genişlik grid'den) | **1:1**, `object-contain` (ana), `object-cover` (kart) | `LIVE_SOURCES:33`. Ana görselde contain, kartta cover → **aynı dosya iki farklı davranış**. Bkz. §7-B3 |
| `listing.gallery_image` | `Listing Image.image` (Attach Image, **reqd**) | satıcı | Ürün ek görselleri | L0 | `ProductImageGallery.ts` (aynı galeri) | ana 512×512 px; dikey küçük resim **70×70 px** (`ProductImageGallery.ts:103`); mobil şerit **76×76 px** (`:111`, `<960px` → 68×68); lightbox küçük resim **52×52 px** (`:340`) | 1:1 | Küçük resimlerde `object-contain` zorlanıyor (`:106` `[&_img]:!object-contain`) |
| `listing.video` | `Listing.video_url` (**Data**, options=URL) — *tipi Attach değil* | satıcı | Ürün tanıtım videosu | L0 dosya yüklenirse (`ListingFormView.vue:4166` → 10 MB istemci kontrolü) | `tradehubfront/src/components/product/ProductVideoSection.ts:56-63` | ÖLÇÜLEMEDİ (kap `absolute inset-0`, dış kutu ölçülmedi) | ÖLÇÜLEMEDİ | **Tip tuzağı:** alan `Data/URL` ama panel oraya `upload_file` çıktısını yazıyor. `LIVE_SOURCES:34`'te kayıtlı. Attach taramasıyla **bulunamaz** |
| `listing.variant_image` | `Listing Variant Item.variant_image` (Attach Image) | satıcı | Varyant (renk) görseli | L0 | ÖLÇÜLEMEDİ (varyant matrisi `variantMatrix.ts`, render kutusu ölçülmedi) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | `LIVE_SOURCES:36` |
| `listing.variant_gallery` | `Listing Variant Item.variant_gallery` (**Long Text**, JSON dizi) | satıcı | Varyant ek görselleri | L0 (her dosya ayrı yüklenir) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | JSON içinde URL listesi (`bulk_import/persister.py:614-640`). `LIVE_SOURCES:37`'de var. Attach taramasıyla bulunamaz |
| `listing.variant_video` | `Listing Variant Item.variant_video_url` (**Data**) | satıcı | Varyant videosu | L0 dosya ise | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | `LIVE_SOURCES`'ta **YOK** → silme taramasında görünmez |
| `review.image` | `Listing Review Image.image` (Attach Image, **reqd**) | alıcı | Ürün yorumu görseli | L0 + L2 (`WriteReviewModal.ts:23-26`: 5 dosya, 5 MB, jpg/jpeg/png/gif/webp) | `tradehubfront/src/components/product/ProductReviews.ts`, `ReviewsModal.ts` | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | Yükleme `upload_file` + `folder: Home/Attachments`, `is_private=0` (`WriteReviewModal.ts:145`) |
| `review.seller_product_image` | `Seller Review.product_image` (Attach Image) | alıcı | Satıcı değerlendirmesi görseli | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — |
| `logistics.provider_logo` | `Logistics Provider.logo` (Attach Image) | admin | Kargo firması logosu | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | `LIVE_SOURCES`'ta YOK |
| `order.receipt` | `Order.receipt_url` (Attach) | alıcı | Havale/EFT dekontu | L0 + L2 (`OrdersPageLayout.ts:1548`: `.jpg,.jpeg,.png,.gif,.pdf`, **boyut kontrolü yok**) | `tradehubfront/src/components/orders/OrdersPageLayout.ts:1545-1550` | ÖLÇÜLEMEDİ | — | `presets.py:50` EXCLUDED_DOCTYPES (optimizasyondan muaf). `usage.py:47` ORDER_SOURCES |
| `order.item_image` | `Order Item.image` (Attach Image) | sistem | Sipariş satırı görsel kopyası | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | Yükleme slotu değil, kopya |
| `payment.receipt` | `Payment Transaction.receipt_url` (Attach) | sistem/admin | Ödeme makbuzu | L0. `presets.py:51` EXCLUDED | — | — | — | Hassas |
| `category.image` | `Product Category.image` (Attach Image) | admin | Platform kategori görseli | L0 + L2 (`CategoryManagementView.vue:924`: `image/*`, **boyut kontrolü yok**) | `tradehubfront/src/components/categories/CategoryGrid.ts:14-18`; `.../hero/MobileCategoryBar.ts:21-25`; `.../hero/CategoryBrowse.ts:20` | CategoryGrid: **68×68 px** (sm 96, lg 112, xl 128 px), **daire** (`rounded-full`); MobileCategoryBar: 42/52/60 px; CategoryBrowse: 80×80 px | **1:1 daire**, `object-cover` | Aynı dosya 6 farklı ölçüde servis ediliyor, tek boy üretiliyor. Bkz. §7-B3 |
| `seller_category.image` | `Seller Category.image` (Attach Image) | satıcı | Satıcının kendi kategori görseli | L0 + L2 (`SellerCategoriesView.vue:377-382` ve `:509-514`, `image/*`, boyut yok) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | `Product Category` ile **ayrı kavram** (bkz. tradehubfront `.claude/rules/typescript.md` §5 uyarısı) |
| `seller_application.identity` | `Seller Application.identity_document` (Attach) | satıcı | Başvuru kimlik belgesi | L0 | `tradehubfront/src/components/auth/SupplierSetupForm.ts:307` (`accept=".pdf,.jpg,.jpeg,.png"`, **boyut kontrolü yok**) | Girdi `absolute inset-0 opacity-0` — görünmez katman, kutu dış öğeden | ÖLÇÜLEMEDİ | `presets.py:49` EXCLUDED + `:72` EXCLUDED_MEDIA_FIELDS. `gates.py`/`presets.py:56-64` notuna göre canlıda **144 dosyada `attached_to_doctype` boş** |
| `seller_certification.document` | `Seller Certification.document` (Attach) | satıcı | Sertifika/belge | L0 + L2 (`MyCertificationsView.vue:769-770`: `.pdf,image/jpeg,image/png`) | ÖLÇÜLEMEDİ (`ProductCertificates.ts` rozet gösteriyor, belgeyi değil) | rozet satırı 52 px yükseklik (`ProductCertificates.ts:30`), ikon 32×32 px | — | `presets.py:47` EXCLUDED + `:74` EXCLUDED_MEDIA_FIELDS. Canlıda 2 dosyada `attached_to_doctype` boş |
| `seller_verification.document` | `Seller Verification.document` (Attach) | satıcı | 3. taraf denetim raporu | L0 + L2 (`MyVerificationsView.vue:306-307`) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — | `presets.py:48` EXCLUDED + `:75` EXCLUDED_MEDIA_FIELDS |
| `shipment.document` | `Shipment Document.file` (Attach) | satıcı/kargo | Sevkiyat belgesi | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — | `EXCLUDED_DOCTYPES`'ta **YOK** — sevk irsaliyesi/POD hassas olabilir |
| `shipping_channel.icon` | `Shipping Channel.icon` (Attach Image) | admin | Kargo kanalı ikonu | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | Küçük ikon — L3 boyut kuralı en çok burada anlamlı olurdu |
| `seo.og_image` | `Static Page SEO.og_image` (Attach Image) | admin | Open Graph paylaşım görseli | L0 + L2 (`OgImageUpload.vue:103`: `image/jpeg,image/png,image/webp`) | `admin-panel/.../seo/OgImageUpload.vue:57` (önizleme) | Önizleme `w-full max-w-md aspect-[1.91/1]` → **maks 448×235 px** | **1.91:1** (OG standardı, UI'da zorlanmıyor) | Kod tabanında **en-boy oranını açıkça yazan tek slot** |
| `verification_source.icon` | `Verification Source.icon` (Attach Image) | admin | Doğrulama rozeti görseli | L0 + L2 (`VerificationSourceView.vue:307-311`: `image/*`) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — |
| `seller_product.image` | `Seller Product.image` (Attach Image) | satıcı | (eski/ikincil ürün kaydı) | L0 | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | `LIVE_SOURCES`'ta YOK. Bu doctype hâlâ kullanılıyor mu → §9-M3 |

---

## 3. Tablo B — Storefront yükleme bileşenleri (`tradehubfront/src/`)

Storefront'ta ortak bir yükleme kütüphanesi var: `src/lib/upload-ui/`
(**1.780 satır**, `wc -l src/lib/upload-ui/*.ts src/lib/upload-ui/facades/*.ts`).
4 facade + çekirdek (`uploader`, `dropzone`, `file-list`) + `utils`.

| slot_key | bileşen | rol | iş amacı | mevcut doğrulama | CSS kutu ölçüsü | en-boy oranı | not |
|---|---|---|---|---|---|---|---|
| `ui.slot_dropzone` | `lib/upload-ui/facades/SlotDropzone.ts` | — (altyapı) | Sabit etiketli tek-dosya slotları | Yalnız **boyut** (`:183-187`), varsayılan 5 MB. Uzantı kontrolü **YOK** — `accept` sadece pencere süzgeci | Kart yüksekliği `h-40` = **160 px**, mobil `max-sm:h-32` = 128 px; grid `grid-cols-1 sm:2 lg:3 gap-6` (`:76`) | küçük resim `object-cover` → kare değil, kutuya göre | **DOĞRULAMA YOK (uzantı)** — istemcide; L0 sunucuda yakalar |
| `ui.multifile_dropzone` | `facades/MultiFileDropzone.ts` + `dropzone.ts` | — (altyapı) | Çoklu dosya sürükle-bırak | `dropzone.ts`: uzantı + boyut + maxFiles + ad/boyut tekrarı | Kutu `px-6 py-8` = 24/32 px iç boşluk, ikon 48×48 px (`dropzone.ts:38-39`) | — | Tek yeri: uzantı allowlist'i **istemciye yazılı**, sunucudan gelmiyor |
| `ui.image_picker` | `facades/ImagePicker.ts` | — (altyapı) | Tek görsel seçici | ÖLÇÜLEMEDİ (dosya okunmadı; barrel'da dışa aktarılıyor, `index.ts:53`) | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | Storefront'ta **kullanan yer bulunamadı** (grep `ImagePickerController` → yalnız kütüphane) |
| `ui.attach_field` | `facades/AttachField.ts` | — (altyapı) | Tek dosya eki | ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — | Storefront'ta **kullanan yer bulunamadı** |
| `kyc.identity_document` | `components/kyc/KycLayout.ts:362-382` | alıcı/satıcı | KYC kimlik | 10 MB (`:370`), `accept=".pdf,.jpg,.jpeg,.png,.webp,.docx"` (`:369`), `compress:false` (`:381`) | 160 px (SlotDropzone) | — | Uç: `/api/method/upload_file` → **L1 yok**, yalnız L0 |
| `kyb.*` (6 slot) | `alpine/kyb.ts:290-336` + `components/kyb/KybLayout.ts:19-26` | satıcı | KYB evrakları | 10 MB (`kyb.ts:295`), aynı `accept` (`:294`) | 160 px | — | Uç: `tradehub_core.api.v1.kyb.upload_kyb_document` → **L1 var**. `autoCustomUploader` ile sıkıştırmayı bilinçli atlıyor (`kyb.ts:303-306`) |
| `review.images` | `components/product/WriteReviewModal.ts:23-26,123-145` ve `EditReviewModal.ts:76-94` | alıcı | Ürün yorumu görselleri | 5 dosya, **5 MB**, `.jpg .jpeg .png .gif .webp` | dropzone `px-6 py-8` | — | `is_private=0`, `folder=Home/Attachments` |
| `support.ticket_attachment` | `alpine/help.ts:28-43,952-978` | alıcı/satıcı | Destek talebi eki | 5 dosya, **10 MB**, 10 uzantı (jpg…xlsx) | dropzone `px-6 py-8` | — | — |
| `rfq.attachment` | `types/rfq.ts:46-61` + `components/rfq/dropzone.ts:14-25` + `components/rfq/uploader.ts:30-41` | alıcı | Teklif talebi eki | 6 dosya, **10 MB**, aynı 10 uzantı | ÖLÇÜLEMEDİ | — | `is_private=1`, `doctype=RFQ` bağlanıyor — **tek doğru bağlama örneği** |
| `user.avatar` (storefront) | `components/settings/SettingsLayout.ts:96-97` + `alpine/settings.ts:70-86` | alıcı/satıcı | Kullanıcı profil fotoğrafı | MIME `image/(jpeg\|png\|webp\|gif)` + **5 MB** (istemci), **L1** sunucuda (`identity.py:940-955`) | **72×72 px** (`size-[72px]`), mobil 48×48 px (`max-sm:size-12`), `rounded-full` | **1:1 daire**, `object-cover` | İki taraflı doğrulaması olan **tek görsel slotu** |
| `product.question_attachment` | `components/product/QuestionFormSheet.ts:70` | alıcı | Ürün sorusuna ek | `accept="image/*,application/pdf"` — **boyut kontrolü YOK** | ÖLÇÜLEMEDİ | — | **DOĞRULAMA YOK (boyut, istemci)** |
| `chat.photo` | `components/chat-shared/sub/PhotoSourceMenu.ts:13` | alıcı/satıcı | Sohbette fotoğraf | `accept="image/*"` — **boyut kontrolü YOK** | ÖLÇÜLEMEDİ | — | **DOĞRULAMA YOK (boyut, istemci)** |
| `chat.file` | `components/chat-shared/sub/FileSourceMenu.ts:12` | alıcı/satıcı | Sohbette dosya | `accept` özniteliği **hiç yok**, boyut kontrolü yok | ÖLÇÜLEMEDİ | — | **DOĞRULAMA YOK (istemci, tamamen)** — en açık istemci kapısı |
| `order.receipt` | `components/orders/OrdersPageLayout.ts:1545-1550` | alıcı | Dekont | `accept=".jpg,.jpeg,.png,.gif,.pdf"` — boyut yok | Etiket `px-6 py-2.5`, pill buton | — | **DOĞRULAMA YOK (boyut, istemci)** |
| `seller_application.identity` | `components/auth/SupplierSetupForm.ts:307` | satıcı | Başvuru kimlik | `accept=".pdf,.jpg,.jpeg,.png"` — boyut yok | Görünmez katman (`absolute inset-0 opacity-0`) | — | **DOĞRULAMA YOK (boyut, istemci)** |

---

## 4. Tablo C — Admin panel yükleme bileşenleri (`admin-panel/frontend/src/`)

| slot_key | bileşen | rol | iş amacı | mevcut doğrulama | CSS kutu ölçüsü | en-boy oranı | not |
|---|---|---|---|---|---|---|---|
| `panel.generic_attach` | `views/doctype/DocTypeFormView.vue:2263-2334` (`uploadFile`) | admin + satıcı | **Tüm** Attach/Attach Image alanları için jenerik yükleme | `UPLOAD_MAX_BYTES = 10 MB` (`:2229`); `accept` = `image/*` (Attach Image) veya `*` (Attach) (`:2235-2238`); KYB alanlarında ayrı allowlist + 10 MB (`:2224-2225`) | Önizleme kartı **240×160 px** (`w-60 h-40`, `:512`); alt tablo satırında **40×40 px** (`w-10 h-10`, `:862`) | serbest / `object-cover` (tablo) | `is_private=1` varsayılan (`:2306`) — **panelden yüklenen her şey private**. Bu, storefront'ta gösterilecek görseller için sorun olabilir → §9-M4 |
| `panel.profile_image_dropzone` | `components/upload/ProfileImageDropzone.vue` | admin + satıcı | Logo / banner tipli tek görsel | `accept` varsayılan `image/jpeg,image/png,image/webp` (`:122`), `maxBytes` varsayılan **5 MB** (`:123`) | `shape="square"` → **160×160 px** (`w-40 h-40`); `shape="rectangle"` → `w-full sm:w-64 h-36` = **256×144 px** (sm ≥640px) (`:135`) | kare 1:1 / dikdörtgen **16:9** | Yalnız **2 yerde** kullanılıyor: `Admin Seller Profile.logo` ve `.banner_image` (`DocTypeFormView.vue:439-451`). `recommendedSize` metni 400×400 / 1600×400 — **görsel oranıyla uyuşmuyor** (banner kutusu 16:9, tavsiye 4:1) |
| `panel.listing_primary` | `views/seller/ListingFormView.vue:436-507` | satıcı | Ürün ana görseli | `accept="image/*"`; **boyut kontrolü YOK**; `doUpload` → `prepareMedia` ile tarayıcıda WebP'ye çeviriyor (`:4752-4762`) | Önizleme **128×128 px** (`w-32 h-32`, `:436`) | 1:1 kutu, `object-cover` | **DOĞRULAMA YOK (boyut, istemci)** — L0 25 MB'da yakalar |
| `panel.listing_gallery` | `ListingFormView.vue:1095-1168` | satıcı | Ürün galeri görselleri | `accept="image/*"`, `multiple`; **boyut ve adet kontrolü YOK** | Kart `aspect-square rounded-xl` (`:1048`), ekleme döşemesi `aspect-square` (`:1132`) | 1:1 | **DOĞRULAMA YOK (boyut + adet)** |
| `panel.listing_video` | `ListingFormView.vue:1215, 4166-4185` | satıcı | Ürün videosu | `accept="video/*"` + **10 MB istemci** (`:4169`); `prepareVideo` ile WebM'e çeviriyor | ÖLÇÜLEMEDİ | — | Sunucu tavanı 200 MB, istemci 10 MB → **190 MB'lık sessiz fark** |
| `panel.storefront_logo` | `views/seller/StorefrontEdit.vue:107-113, 1047-1061` | satıcı | Mağaza logosu | `accept="image/*"`; **boyut kontrolü YOK** | **80×80 px** (`w-20 h-20`, `:73-74`), `rounded-xl` | serbest, `object-cover` | **DOĞRULAMA YOK (boyut)** + bkz. §9-M1 (`tr_tradehub`) |
| `panel.storefront_banner` | `StorefrontEdit.vue:252-258, 1064-1078` | satıcı | Mağaza bandı | `accept="image/*"`; boyut yok | Önizleme `w-full h-40` = **160 px yükseklik** (`:245`) | `object-cover` | **DOĞRULAMA YOK (boyut)** |
| `panel.storefront_slider` | `StorefrontEdit.vue:344-350, 1097-1110` | satıcı | Mağaza slider görselleri | `accept="image/*"`, `multiple`; **hiç kontrol yok** (dosyalar `URL.createObjectURL` ile beklemeye alınıyor) | Dropzone `p-8` = 32 px | — | **DOĞRULAMA YOK** |
| `panel.storefront_factory_images` | `StorefrontEdit.vue:453-459, 1081-1094` | satıcı | Fabrika görselleri | `accept="image/*"`, `multiple`; **hiç kontrol yok** | Dropzone `p-8` | — | **DOĞRULAMA YOK** |
| `panel.storefront_factory_video` | `StorefrontEdit.vue:503-543, 1004-1021` | satıcı | Şirket profili tanıtım (fabrika) videosu | **10 MB istemci** (`:1007`) | Etiket `px-3 py-2` | — | Sunucu 200 MB — aynı 190 MB'lık fark |
| `panel.storefront_layout_logo` | `views/seller/StorefrontLayoutEditor.vue:272-278` | satıcı | Vitrin düzeni header logosu | `accept="image/*"`; boyut ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — | Vitrin JSON'una yazılıyor (`Storefront Layout.sections`) → `LIVE_SOURCES:37` |
| `panel.layout_slide` | `components/seller/LayoutSectionCard.vue:195-199` | satıcı | Vitrin hero slaytları | `accept="image/*"`; boyut ÖLÇÜLEMEDİ | Render: `utils/seller/section-registry.ts:208` → **h-180 / sm 220 / md 320 / lg 400 px** | Kap `store-hero` genişliği (`max-w-[1200px]` bölüm sarmalayıcı) → lg'de ≈ **3:1** | Aynı slayt 180 px'ten 400 px'e uzuyor → oran 1200:180 ≈ 6.7:1'den 3:1'e değişiyor. Tek görselle karşılanamaz. Bkz. §7-B2 |
| `panel.category_image` | `views/products/CategoryManagementView.vue:924-928` | admin | Platform kategori görseli | `accept="image/*"`; **boyut yok** | ÖLÇÜLEMEDİ | — | **DOĞRULAMA YOK (boyut)** |
| `panel.seller_category_image` | `views/seller/SellerCategoriesView.vue:377-383, 509-515` | satıcı | Satıcı kategori görseli | `accept="image/*"`; **boyut yok** | Dropzone `p-4` = 16 px | — | **DOĞRULAMA YOK (boyut)** |
| `panel.hero_slide_bg` | `components/system/HeroSlideEditModal.vue:91-93` | admin | Ana sayfa slider arka planı | `accept="image/jpeg,image/png,image/webp"`; boyut ÖLÇÜLEMEDİ | `.hs-upload__preview { width: 100% }` (`:543-544`) | ÖLÇÜLEMEDİ | — |
| `panel.verification_source_icon` | `views/admin/VerificationSourceView.vue:307-311` | admin | Doğrulama rozeti ikonu | `accept="image/*"`; boyut yok | ÖLÇÜLEMEDİ | — | **DOĞRULAMA YOK (boyut)** |
| `panel.certification_document` | `views/seller/MyCertificationsView.vue:767-773` | satıcı | Sertifika belgesi | `accept=".pdf,image/jpeg,image/png"`; boyut ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — | — |
| `panel.verification_document` | `views/seller/MyVerificationsView.vue:304-310` | satıcı | Denetim belgesi | `accept=".pdf,image/jpeg,image/png"`; boyut ÖLÇÜLEMEDİ | ÖLÇÜLEMEDİ | — | — |
| `panel.bulk_data_file` | `views/bulk-import/BulkProductImportView.vue:667-671` | satıcı | Toplu içe aktarma verisi | `accept=".xlsx,.csv,.xml"` | ÖLÇÜLEMEDİ | — | L0 **bypass** kanalı |
| `panel.bulk_images_zip` | `BulkProductImportView.vue:795-799` | satıcı | Görsel ZIP | `accept=".zip,application/zip,application/x-zip-compressed"` | ÖLÇÜLEMEDİ | — | L0 bypass |
| `panel.category_json_import` | `CategoryManagementView.vue:1146-1150` | admin | Kategori ağacı JSON | `accept=".json"` | — | — | Medya değil |
| `panel.helpdesk_attachment` | `views/helpdesk/TicketDetailView.vue:351` | admin | Destek yanıtı eki | **`accept` yok, boyut yok, `multiple`** | ÖLÇÜLEMEDİ | — | **DOĞRULAMA YOK (istemci, tamamen)** |
| `panel.richtext_image` | `components/common/RichTextEditor.vue:34` | admin + satıcı | Zengin metin içi görsel | `accept="image/*"`; boyut ÖLÇÜLEMEDİ | Editör içi — ÖLÇÜLEMEDİ | — | Bu görseller **hiçbir `LIVE_SOURCES` alanında geçmez** → içerik içinde gömülü, silme taramasında görünmez. Bkz. §7-B1 |
| `panel.user_avatar` | `components/layout/IconRail.vue:37-41, 173-210` + `stores/auth.js:199-218` | admin + satıcı | Panel kullanıcı avatarı | MIME `image/(jpeg\|png\|webp\|gif)` + **5 MB** (istemci, `auth.js:201-206`), **L1** sunucuda | **36×36 px** (`w-9 h-9`, `IconRail.vue:45`), `rounded-full` | 1:1 daire, `object-cover` | Storefront avatarıyla aynı uç ve aynı kural — **tutarlı** |
| `panel.media_library_upload` | `views/seller/MediaLibraryView.vue:53, 342, 624` + `composables/useSellerMedia.js:245-263` | satıcı | Medya kütüphanesi | **L2 doğru uygulanmış:** `accept` sunucudan gelen `media_extensions` listesinden üretiliyor (`MediaLibraryView.vue:724-727`), sınırlar `policy.loadLimits()` ile alınıyor (`useSellerMedia.js:245`), 8 MB üstü **parçalı yükleme** (`upload_policy.py:89`) | Kart/tablo/grid görünümleri — ÖLÇÜLEMEDİ | — | **Referans uygulama.** Uç `seller_media.upload_media` → **L1 dar izin listesi** |
| `panel.media_picker` | `components/media/MediaPickerModal.vue:35`, `MediaDetailPanel.vue:206` | satıcı | Kütüphaneden seçme + değiştirme | `MediaPickerModal`: `accept` = `kabulEdilen` (dinamik); `MediaDetailPanel:206`: **sabit yazılı** `"image/*,video/*,.pdf"` | ÖLÇÜLEMEDİ | — | `MediaDetailPanel`'deki sabit liste sunucuyla ayrışabilir |

---

## 5. Dokümanın istediği 8 slot — var/yok karnesi

| Doküman slotu | Var mı | Nerede | Doğrulama | Boyut/oran kuralı |
|---|---|---|---|---|
| **Ürün görseli** | ✅ VAR | `Listing.primary_image` + `Listing Image.image` (+ varyant alanları) | L0 (25 MB); panelde istemci kontrolü **yok** | **YOK** — 1:1 kutuya `object-cover`/`object-contain` |
| **Ürün videosu** | ✅ VAR (ama `Data` tipinde) | `Listing.video_url` (fieldtype **Data**), `Listing Variant Item.variant_video_url` | L0 200 MB / istemci 10 MB | **YOK** |
| **Satıcı logosu** | ✅ VAR | `Admin Seller Profile.logo` | L0; tavsiye metni 400×400 | tavsiye var, **zorlama yok** |
| **Şirket profili kapak videosu** | ⚠️ KISMEN | Storefront'ta `Seller Gallery Image.video_url` + `poster_image`; panelde `StorefrontEdit.factory_video_url` — ama o alan **bu repoda bir doctype'a bağlı değil** (§9-M1) | L0; istemci 10 MB | **YOK** |
| **Kategori banner** | ⚠️ İKİ AYRI KAVRAM | `Product Category.image` (daire ikon, banner değil), `Category Showcase Tile.image` (bento döşeme), `Brand.hero_banner` (marka bandı), `Admin Seller Profile.banner_image` (mağaza bandı) | L0 | **YOK** — hiçbirinde |
| **Marka logosu** | ✅ VAR | `Brand.logo` | L0 | **YOK** |
| **Belge / sertifika eki** | ✅ VAR (7 slot) | KYB×6, KYC×1, `Seller Certification.document`, `Seller Verification.document`, `Seller Application.identity_document`, `Shipment Document.file`, `Data Processing Agreement.document` | KYB'de **L1 en sıkı**; diğerlerinde yalnız L0 | — |
| **Kullanıcı avatarı** | ✅ VAR | Frappe çekirdeği `User.user_image` — **`tradehub_core` doctype'larında değil**, bu yüzden 41'lik taramada çıkmaz | **L1 + L2 (5 MB, 4 MIME)** — iki taraflı | 1:1 daire (72/48/36 px) |

---

## 6. Zaten çözülmüş olanlar — üstüne yazılmayacaklar

Bu bölüm **kural 5** gereği: aşağıdakiler kodda çalışıyor, Faz 2 bunları yeniden
tasarlamamalı.

1. **Tek kapı politikası (L0).** `hooks.py:227-252` + `utils/security.py:96` +
   `upload_policy.py:307`. Panelin 22 ekranına dokunmadan hepsi aynı sözleşmeye
   sokulmuş. Kaynak gerekçe: `docs/MEDYA-YUKLEME-SOZLESMESI.md` §1.
2. **Kodlu ret sözleşmesi.** `upload_policy.py:104-139` — 14 hata kodu +
   `retryable` bayrağı. İstemci metne değil koda bakıyor.
3. **Sınırların sunucudan dağıtımı.** `upload_policy.py:398-428` `limits()` →
   `seller_media.upload_limits` → `admin-panel/src/utils/uploadPolicy.js`. İki
   tarafa ayrı sabit koyma sorunu **medya kütüphanesinde** çözülmüş.
4. **Parçalı yükleme.** `media/chunked.py` (293 satır), eşik
   `SINGLE_SHOT_LIMIT = 8 MB` (`upload_policy.py:89`).
5. **Optimizasyon kapıları.** `media/gates.py:42-85` — 6 kapı, hepsi zorunlu.
   `presets.py:13-17` (safe/balanced/aggressive), `MIN_FILE_SIZE = 200 KB`,
   `MIN_SAVING_RATIO = 0.10`.
6. **Hassas belge muafiyeti.** `presets.py:44-53` `EXCLUDED_DOCTYPES` (8 adet) +
   `:70-76` `EXCLUDED_MEDIA_FIELDS` (5 doctype, 7 alan) — ters referans taraması
   için.
7. **Kullanım/silme çözümlemesi.** `media/usage.py` — `LIVE_SOURCES` (8),
   `ORDER_SOURCES` (2), `HISTORY_SOURCES` (6), `verdicts_for()`, `images_of()`
   (`:573`). Mağaza kapsamı süzgeci `STORE_FILTERS` (`usage.py:98-107`).
8. **Sayaçlı silme / paylaşılan dosya.** `media/seller_media.py` — aynı içerik
   birden çok mağazada tek fiziksel dosya, sahibi kalmayınca silinir.
9. **İstemci sıkıştırma.** `admin-panel/src/lib/media/compress.js` — görsel →
   WebP (`browser-image-compression`), video → WebM (`mediabunny`), dinamik
   import ile chunk ayrımı. KYC/KYB'de bilinçli olarak **kapalı**
   (`KycLayout.ts:381`, `kyb.ts:303-306`).
10. **Ortak yükleme UI kütüphanesi.** `tradehubfront/src/lib/upload-ui/` — 4
    facade, tek `uploadFiles()` çekirdeği.

---

## 7. DOĞRULAMA YOK — açık işaretleme

### 7-A. İstemcide hiçbir kontrolü olmayan slotlar

`accept` özniteliği **doğrulama değildir** — yalnız dosya seçme penceresini
süzer, sürükle-bırak edilen dosyayı denetlemez
(`docs/MEDYA-YUKLEME-SOZLESMESI.md` §1).

| slot | dosya:satır | eksik olan |
|---|---|---|
| `chat.file` | `tradehubfront/src/components/chat-shared/sub/FileSourceMenu.ts:12` | `accept` yok, boyut yok |
| `panel.helpdesk_attachment` | `admin-panel/.../helpdesk/TicketDetailView.vue:351` | `accept` yok, boyut yok, `multiple` |
| `chat.photo` | `.../chat-shared/sub/PhotoSourceMenu.ts:13` | boyut yok |
| `product.question_attachment` | `.../product/QuestionFormSheet.ts:70` | boyut yok |
| `order.receipt` | `.../orders/OrdersPageLayout.ts:1548` | boyut yok |
| `seller_application.identity` | `.../auth/SupplierSetupForm.ts:307` | boyut yok |
| `panel.listing_primary` | `admin-panel/.../ListingFormView.vue:502-507` | boyut yok |
| `panel.listing_gallery` | `ListingFormView.vue:1162-1168` | boyut yok, **adet yok** |
| `panel.storefront_logo` | `StorefrontEdit.vue:107-113` | boyut yok |
| `panel.storefront_banner` | `StorefrontEdit.vue:252-258` | boyut yok |
| `panel.storefront_slider` | `StorefrontEdit.vue:344-350` | boyut yok, adet yok |
| `panel.storefront_factory_images` | `StorefrontEdit.vue:453-459` | boyut yok, adet yok |
| `panel.category_image` | `CategoryManagementView.vue:924-928` | boyut yok |
| `panel.seller_category_image` | `SellerCategoriesView.vue:377-383`, `:509-515` | boyut yok |
| `panel.verification_source_icon` | `VerificationSourceView.vue:307-311` | boyut yok |
| `ui.slot_dropzone` (kütüphane) | `lib/upload-ui/facades/SlotDropzone.ts:182-198` | uzantı kontrolü yok |

### 7-B. Sistemin tamamında eksik olanlar

| # | Eksik | Kanıt |
|---|---|---|
| **B1** | **Slot kayıt defteri yok.** Sunucu bir dosyanın "hangi slota" yüklendiğini bilmiyor. `upload_policy.check()` (`:307`) yalnız `file_name`, `content`, `size`, `media_endpoint` alıyor — slot parametresi yok. Bu yüzden slot bazlı hiçbir kural yazılamaz. | `upload_policy.py:307-313` |
| **B2** | **En-boy oranı kuralı yok.** Kod tabanında en-boy oranını yazan **tek yer** `OgImageUpload.vue:57` (`aspect-[1.91/1]`) ve orası da yalnız önizleme; yüklenen dosya kontrol edilmiyor. `Category Showcase Tile.image` 3 farklı orana (1×1, 2×1, 2×2), `panel.layout_slide` 4 farklı yüksekliğe (180/220/320/400 px) `object-cover` ile kırpılıyor. | `CategoryShowcase.ts:137,154`; `section-registry.ts:208` |
| **B3** | **Türev boy (responsive variant) üretimi yok.** `Product Category.image` 6 farklı ölçüde servis ediliyor (42, 52, 60, 68, 80, 96, 112, 128 px) — hepsi **aynı orijinal dosya**. `srcset`/`sizes` kullanan hiçbir bileşen bulunamadı (grep `srcset` → storefront'ta 0 sonuç). `media/presets.py:13-17` yalnız **tek** çıktı üretiyor (max_dim + quality), boy seti değil. | `CategoryGrid.ts:18`; `MobileCategoryBar.ts:25`; `CategoryBrowse.ts:20`; `presets.py:13-17` |
| **B4** | **Bazı slotlar `<img>` değil CSS `background`.** `Brand.hero_banner` (`brand.ts:145-148`) ve `Hero Slide.background_image` (`HeroTopSlider.ts:136`) inline `style="background:url(...)"` ile basılıyor → `loading="lazy"`, `decoding="async"`, `srcset`, `fetchpriority` uygulanamıyor. | `brand.ts:145-148`; `HeroTopSlider.ts:136` |
| **B5** | **KVKK muafiyet haritası eksik.** `presets.py:70-76` `EXCLUDED_MEDIA_FIELDS` KYB'nin yalnız 2 alanını sayıyor (`identity_document`, `bank_account_document`); `imza_sirkuleri`, `ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` **yok**. `Shipment Document.file` ve `Data Processing Agreement.document` ise `EXCLUDED_DOCTYPES`'ta hiç yok. Kodun kendi bakım notu (`presets.py:66-69`) bunun tehlikesini zaten yazıyor. | `presets.py:44-76` |
| **B6** | **`LIVE_SOURCES` eksik.** 41 alanın yalnız 8'i kayıtlı (`usage.py:32-41`). Kayıtlı olmayan bir görsel "kullanılmıyor" görünür ve silme adayı olur. Eksik olanlar arasında: `Admin Seller Profile.banner_image`, `Seller Gallery Image.poster_image`, `Listing Variant Item.variant_video_url`, `Brand.logo`, `Brand.hero_banner`, `Brand.video_url`, `Product Category.image`, `Seller Category.image`, `Category Showcase Tile.image`, `Hero Slide.background_image`, `Logistics Provider.logo`, `Shipping Channel.icon`, `Verification Source.icon`, `Static Page SEO.og_image`, `Seller Product.image` + `RichTextEditor` ile içeriğe gömülen görseller. | `usage.py:32-41` vs. Tablo A |
| **B7** | **Aynı sınır için üç farklı sayı.** Video: DocType açıklaması **10 MB** (`brand.json`, `seller_gallery_image.json`), sunucu politikası **200 MB** (`upload_policy.py:69`), panel istemcisi **10 MB** (`ListingFormView.vue:4169`, `StorefrontEdit.vue:1007`). Ayrıca `platform_limit()` (`upload_policy.py:239-259`) Frappe tavanını **25 MB** varsayıyor → ilan edilen 200 MB pratikte 25 MB. | 4 ayrı dosya |
| **B8** | **`is_private` tutarsızlığı.** Panel jenerik yükleyicisi her dosyayı `is_private=1` yapıyor (`DocTypeFormView.vue:2306`); storefront yorum görselleri `is_private=0` (`WriteReviewModal.ts:145`); `StorefrontEdit.uploadFile` `is_private=0` (`StorefrontEdit.vue:968`); RFQ `is_private=1` (`rfq/uploader.ts:36`). Slot başına erişim seviyesi kuralı **yok** — dosyanın gizli/açık olması hangi ekrandan yüklendiğine bağlı. | 4 ayrı dosya |

---

## 8. Slot anahtarı önerisi (Faz 2 girdisi)

Tablo A/B/C'deki `slot_key` alanları bu belgede **ilk kez** tanımlandı. Kodda
karşılığı yok. Önerilen biçim:

```
<alan>.<slot>          # örn. listing.primary_image, seller.logo
panel.<bileşen>        # yalnız panelde yaşayan, doctype alanına bağlanmayan
ui.<facade>            # altyapı bileşeni, gerçek slot değil
```

Toplam: **41** doctype alanı + **16** storefront bileşeni + **26** panel
bileşeni. Bunların bir kısmı aynı doctype alanına bağlandığı için **benzersiz iş
slotu sayısı 41'den fazladır** (aynı alan hem panelden hem storefront'tan
doldurulabiliyor: örn. `kyb.identity_document` iki ayrı istemciden).

---

## 9. ÜRETİMDE DOĞRULANMALI

Aşağıdakiler bu ortamda **ölçülemedi** (Docker kapalı, üretim DB ve canlı site
erişimi yok). Her madde için çalıştırılacak tam komut yazılıdır.

### M1 — `tr_tradehub` app'i var mı?

`admin-panel/frontend/src/views/seller/StorefrontEdit.vue` beş ayrı yerde
(`:916`, `:1130`, `:1138`, `:1155`, `:1223`) `tr_tradehub.api.v1.seller.*`
çağırıyor. Bu çalışma alanında `tr_tradehub` adında bir app **yok**
(`find /Users/ahmet/Desktop/istoc -maxdepth 2 -name "tr_tradehub*"` → 0 sonuç) ve
API istemcisinde yeniden yazma katmanı bulunamadı (`grep -rn "tr_tradehub" src/`
→ yalnız bu dosya). Eğer app kurulu değilse **mağaza logosu / banner / slider /
fabrika görselleri / fabrika videosu slotlarının tamamı ölü koddur**.

```bash
docker compose exec backend bench --site istoc.localhost list-apps
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.get_installed_apps())
PY
# Tarayıcıda: panel → Mağaza Düzenle → Network sekmesinde
#   /api/method/tr_tradehub.api.v1.seller.get_storefront
# isteğinin HTTP kodunu oku (200 mi 404 mü).
```

### M2 — Bulk import ZIP içindeki görseller L0'dan geçiyor mu?

`utils/security.py:85-88` bulk kanalını L0'dan muaf tutuyor. ZIP açıldıktan
sonra tek tek yazılan görseller de aynı muafiyetle mi yazılıyor?

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
frappe.flags.in_bulk_import_upload = False
# ZIP'ten görsel yazan kod yolunu izle:
import inspect, tradehub_core.bulk_import.persister as p
print(inspect.getsource(p))
PY
grep -rn "in_bulk_import_upload\|bulk_import_safe" \
  /Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/bulk_import/
```

### M3 — Ölü slotlar hangileri (gerçek kullanım sayıları)?

Tablo A'da `Seller Product.image`, `Seller Review.product_image`,
`Shipping Channel.icon`, `Verification Source.icon`, `Logistics Provider.logo`
için **hiçbir render bileşeni bulunamadı**. Gerçekten kullanılıyorlar mı:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
for dt, fld in [
    ("Seller Product","image"), ("Seller Review","product_image"),
    ("Shipping Channel","icon"), ("Verification Source","icon"),
    ("Logistics Provider","logo"), ("Admin Seller Profile","banner_image"),
    ("Seller Gallery Image","poster_image"), ("Category Showcase Tile","image"),
    ("Hero Slide","background_image"), ("Static Page SEO","og_image"),
    ("Brand","logo"), ("Brand","hero_banner"), ("Brand","video_url"),
    ("Product Category","image"), ("Seller Category","image"),
    ("Listing Variant Item","variant_video_url"),
]:
    try:
        n = frappe.db.count(dt, {fld: ["is","set"]})
    except Exception as e:
        n = f"HATA: {e}"
    print(f"{dt}.{fld}: {n}")
PY
```

### M4 — Panelden yüklenen görseller storefront'ta görünüyor mu?

`DocTypeFormView.vue:2306` her dosyayı `is_private=1` yapıyor. Bu, storefront'ta
gösterilmesi gereken bir görsel için `/private/files/...` adresi üretir.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
rows = frappe.db.sql("""
  select is_private, count(*) c
  from tabFile
  where file_url like '%/files/%'
  group by is_private
""", as_dict=True)
print(rows)
# Storefront'ta gösterilen alanlarda private dosya var mı:
print(frappe.db.sql("""
  select l.name, l.primary_image
  from tabListing l join tabFile f on f.file_url = l.primary_image
  where f.is_private = 1 limit 20
""", as_dict=True))
PY
```

### M5 — Gerçek piksel boyutları ve en-boy oranı dağılımı

Bu belgedeki tüm "CSS kutu ölçüsü" değerleri **kaynak koddan** okundu, tarayıcıda
ölçülmedi. Gerçek dosyaların hangi orana sahip olduğu bilinmiyor.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from PIL import Image
from collections import Counter
say = Counter()
for f in frappe.get_all("File",
        filters={"file_url": ["like", "/files/%"]},
        fields=["file_url", "file_name"], limit_page_length=0):
    p = frappe.get_site_path("public", f.file_url.lstrip("/"))
    if not os.path.exists(p): continue
    try:
        with Image.open(p) as im:
            w, h = im.size
            say[round(w/h, 2)] += 1
    except Exception:
        pass
for oran, n in say.most_common(20):
    print(oran, n)
PY
```

### M6 — Slot başına gerçek dosya sayısı ve toplam bayt

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select attached_to_doctype, attached_to_field,
         count(*) adet, sum(file_size) toplam_bayt
  from tabFile
  where attached_to_doctype is not null and attached_to_doctype != ''
  group by attached_to_doctype, attached_to_field
  order by adet desc
""", as_dict=True))
# attached_to_doctype BOŞ olanlar — presets.py:56-64 bu sorunu zaten kaydetmiş:
print(frappe.db.sql("""
  select count(*) from tabFile
  where (attached_to_doctype is null or attached_to_doctype = '')
    and is_folder = 0
"""))
PY
```

### M7 — Frappe `max_file_size` gerçek değeri

`upload_policy.py:239-259` bunu okuyup ilan edilen sınırı kısıtlıyor. 200 MB'lık
video sınırının gerçekleşip gerçekleşmediği buna bağlı.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
from frappe.core.api.file import get_max_file_size
import frappe
print("max_file_size:", get_max_file_size())
print("site_config:", frappe.conf.get("max_file_size"))
from tradehub_core.media import upload_policy as up
print(up.limits())
PY
# nginx tarafı (413 üreten katman):
docker compose exec proxy grep -rn "client_max_body_size" /etc/nginx/
```

### M8 — `LIVE_SOURCES` eksiğinin gerçek maliyeti

B6'daki iddia: kayıtlı olmayan slotlardaki görseller "kullanılmıyor" görünür.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
from tradehub_core.media import usage
# Örnek: bir marka logosu gerçekten "unused" mı görünüyor?
u = frappe.db.get_value("Brand", {"logo": ["is","set"]}, "logo")
print(u, usage.verdicts_for([u], deep=True) if u else "veri yok")
PY
```

---

## 10. Özet

- **41** DocType alanı, **30** doctype, **0** adet `fieldtype: Image`.
- **16** storefront + **26** panel yükleme bileşeni.
- **1** güvenlik kapısı (L0) herkesi kapsıyor — bu **çözülmüş**.
- **3** uçta uca özel sunucu kuralı (L1) var; **38** doctype alanı yalnız L0'a
  güveniyor.
- **16** yükleme noktasında istemci tarafı boyut/uzantı kontrolü **yok**.
- **0** slotta piksel boyutu, en-boy oranı veya adet kuralı var.
- **0** bileşende `srcset` / türev boy kullanımı var.
- **8/41** alan silme-kararı taramasında (`LIVE_SOURCES`) kayıtlı.

Faz 2'nin çözmesi gereken tek yapısal eksik **B1**: sunucu bir yüklemenin hangi
slota ait olduğunu bilmiyor. Slot kimliği olmadan B2, B3, B5, B6 ve B8'in hiçbiri
çözülemez.

---

### Bu belgede geçen tüm kaynak dosyalar

**Backend** (`/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/`)
`hooks.py`, `utils/security.py`, `media/upload_policy.py`, `media/presets.py`,
`media/gates.py`, `media/usage.py`, `media/refs.py`, `media/seller_media.py`,
`media/chunked.py`, `api/v1/identity.py`, `api/v1/kyb.py`,
`bulk_import/persister.py`, `tradehub_core/doctype/*/*.json`

**Storefront** (`/Users/ahmet/Desktop/istoc/tradehubfront/src/`) — SALT OKU
`lib/upload-ui/{index,uploader,dropzone,file-list,utils}.ts`,
`lib/upload-ui/facades/{SlotDropzone,MultiFileDropzone,ImagePicker,AttachField}.ts`,
`alpine/{kyb,help,settings}.ts`, `components/kyc/KycLayout.ts`,
`components/kyb/KybLayout.ts`, `components/product/{WriteReviewModal,EditReviewModal,ProductImageGallery,ProductVideoSection,ProductCertificates,QuestionFormSheet}.ts`,
`components/chat-shared/sub/{FileSourceMenu,PhotoSourceMenu}.ts`,
`components/orders/OrdersPageLayout.ts`, `components/auth/SupplierSetupForm.ts`,
`components/settings/SettingsLayout.ts`, `components/seller/{CompanyInfo,CompanyProfile}.ts`,
`components/categories/CategoryGrid.ts`, `components/category/CategoryShowcase.ts`,
`components/hero/{HeroTopSlider,MobileCategoryBar,CategoryBrowse}.ts`,
`components/manufacturers/ManufacturerList.ts`, `components/shared/{ProductCard,ListingCard}.ts`,
`components/rfq/{dropzone,uploader}.ts`, `types/rfq.ts`, `pages/brand.ts`,
`services/listingService.ts`, `utils/seller/section-registry.ts`, `style.css`

**Admin panel** (`/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/`) — SALT OKU
`views/doctype/DocTypeFormView.vue`, `views/seller/{ListingFormView,StorefrontEdit,StorefrontLayoutEditor,SellerCategoriesView,MediaLibraryView,MyCertificationsView,MyVerificationsView}.vue`,
`views/products/CategoryManagementView.vue`, `views/admin/VerificationSourceView.vue`,
`views/bulk-import/BulkProductImportView.vue`, `views/helpdesk/TicketDetailView.vue`,
`components/upload/ProfileImageDropzone.vue`, `components/seo/OgImageUpload.vue`,
`components/media/{MediaPickerModal,MediaDetailPanel}.vue`,
`components/system/HeroSlideEditModal.vue`, `components/seller/LayoutSectionCard.vue`,
`components/layout/IconRail.vue`, `components/common/RichTextEditor.vue`,
`composables/useSellerMedia.js`, `lib/media/compress.js`, `utils/uploadPolicy.js`,
`stores/auth.js`
