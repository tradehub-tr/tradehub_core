# T-021 — LOGO STANDARDI

**Durum:** KİLİT görev. Bu belge onaylanmadan hiçbir logo işi (derivative üretimi,
`srcset` yazımı, SVG kabulü, oran normalizasyonu) başlatılamaz.
**Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Girdi belgeleri:** `docs/reports/00-upload-slot-envanteri.md`, `docs/reports/03-render-envanteri.md`

**Ölçüm durumu:** Docker kapalı. Üretim veritabanına ve canlı siteye erişim YOK.
Bu belgedeki **hiçbir sayı tarayıcıda ölçülmedi**. Her sayı ya (a) kaynak kodda
yazılı bir CSS utility sınıfının Tailwind ölçeğine göre px karşılığı, ya (b) diskteki
bir dosyanın `file` / `stat -f %z` çıktısı, ya da (c) bu ikisinden türetilmiş aritmetik.
Her satırın yanında dayanağı var. Tarayıcı ölçümü gerektiren her şey §12'de.

> **GÜNCELLEME — 2026-08-18 (canlı ölçüm).** Docker açıldı ve `docs/reports/08-canli-olcum.md`
> §2'de **38 logo referansının 18 gerçek dosyası** ölçüldü. Bu ölçüm §13'teki
> **K1 ve K2 kararlarını kapattı** (§13.0 özet tablosu). Belgeden hiçbir bölüm
> silinmedi; etkilenen yerler (§3.5, §3.6, §13) ölçüm referansıyla güncellendi.
> Tarayıcıda ölçülen sayı hâlâ **yok** — §12-D3 açık.

---

## 0. Yönetici özeti — 10 madde

1. **Platform logosu (iStoc) DPR 2'de yetersiz.** Tek dosya `public/images/istoc-logo.png`,
   fiziksel ölçüsü **87×32 px** (`file public/images/istoc-logo.png` → "PNG image data, 87 x 32").
   Bu dosya storefront'ta **14 ayrı yerde** render ediliyor ve bunların **11'i DPR 2'de
   yetersiz kalıyor** (§2.1 tablosu). En kötüsü `HelpCenterHeader.ts:124` `lg:h-[26px]`:
   DPR 3'te 78 px yükseklik gerekiyor, dosyada 32 px var.
2. **Platform logosunun koyu tema varyantı ÜRETİLMİŞ ama header'a bağlanmamış.**
   `public/images/istoc-logo-beyaz.png` (1370×521, `file` çıktısı) mevcut ve
   `AuthLayout.ts:95`'te kullanılıyor. Fakat `TopBar.ts:875` başlığı
   `bg-white dark:bg-gray-900` ile render ediliyor ve `TopBar.ts:177` koyu mürekkepli
   `istoc-logo.png`'yi kullanıyor — koyu temada logo arka planla birleşiyor.
3. **Satıcı/marka logosu için en büyük piksel talebi 480 px.** Kaynak: admin panel
   `ProfileImageDropzone` kare varyantı `w-40 h-40` = 160 CSS px
   (`ProfileImageDropzone.vue:135`), DPR 3 → 480. Storefront'taki en büyük talep 420
   (`seller-shop.ts:124` `w-[140px] h-[140px]`, DPR 3). Bugünkü panel tavsiyesi
   **400×400** (`DocTypeFormView.vue:448`) → bu iki talebin ikisini de karşılamıyor.
4. **5 yerde logo KIRPILIYOR.** `object-cover` kullanan yerler: `seller-shop.ts:129`
   (140×140), `seller-dashboard.ts:66` (48×48), `seller-dashboard.ts:158` (56×56),
   `StorefrontEdit.vue:79` (80×80), `StorefrontLayoutEditor.vue:247` (64×64).
   Kare olmayan bir logo bu 5 yerde merkezden kesiliyor; 9 yerde (`object-contain`)
   kesilmiyor. Aynı dosya iki farklı davranış görüyor.
5. **`seller_media` yolundan geçen her logo KAYIPLI WebP'ye çevriliyor.**
   `api/seller_media.py:292` → `media/engine.py:148` `to_webp(data, quality: int = 80)`
   → `:180` `im.save(buf, "WEBP", quality=quality, method=4)`. Alfa korunuyor
   (`engine.py:169-176`, `tests/test_engine_webp.py:54`) ama **q80 kayıplı encode**
   logonun keskin kenarında halkalanma (ringing) üretir. Logo için `lossless=True`
   gerekir.
6. **og:image üretimi logoyu HEM kırpıyor HEM alfayı düşürüyor.**
   `seo/og_image.py:261` ve `:282` satırları satıcı/marka `logo` alanını og:image
   kaynağı yapıyor. `seo/og_image.py:34` `img.convert("RGB")` → **alfa düşer**;
   `:45-49` cover-crop → 1:1 bir logo 1200×630'a kırpılırken **yükseklikte %47,5
   kesilir** (hesap §5.4); `:51` `save(..., "JPEG", quality=85)` → **kayıplı**.
   Sosyal paylaşımda gösterilen satıcı logosu, logonun orta yatay bandı.
7. **SVG iki ayrı kapıda yasak, üçüncü bir kapı ise açık.** Uzantı yasağı
   `utils/security.py:29-30` (`.svg`, `.svgz`), içerik yasağı
   `media/upload_policy.py:190` (`b"<svg"`). Fakat `seed_demo_data.py:231-245`
   `_write_asset()` SVG'yi **`data:image/svg+xml;base64,…` olarak DB'ye yazıyor**
   (`:287`, `:3364` satıcı logosu, `:4209` marka logosu) — `File` kaydı hiç açılmadığı
   için iki kapının ikisini de atlıyor. **SVG logolar demo DB'de ZATEN VAR.**
8. **PWA ikon dosyalarının uzantısı yalan.** `icons/*.webp` dosyalarının 7'sinin de
   gerçek türü PNG (`file icons/icon-512.webp` → "PNG image data, 512 x 512") ve bayt
   boyutları `public/icons/*.png` ile birebir aynı (27128 = 27128). Bunlar yeniden
   adlandırılmış PNG'ler. Yayınlanan manifest (`dist/manifest.webmanifest`) bunları
   kullanmıyor — VitePWA `/icons/*.png`'yi yazıyor (`vite.config.ts:410-416`) — yani
   `public/manifest.webmanifest` ölü bir dosya. Yine de repoda kalıyor.
9. **Admin panelin favicon'u 404.** `admin-panel/frontend/index.html:18`
   `<link rel="icon" type="image/svg+xml" href="/favicon.svg">` diyor;
   `find . -name "favicon*" -not -path "./node_modules/*"` **hiçbir şey döndürmüyor**
   ve `public/` dizini mevcut değil.
10. **E-posta şablonlarında ve PDF faturada logo YOK — çünkü ikisi de yok.**
    `templates/emails/*.html` (5 dosya) içinde `<img`/`logo` eşleşmesi **0**
    (`grep -ciE 'img |logo'` her dosya için 0). Print format / PDF üreten kod da yok
    (`grep -rlniI "print_format\|get_pdf\|proforma"` → sonuç yok). Bu iki render
    noktası bu standartta **kapsam dışı bırakılmadı, sadece HENÜZ YOK**; §9'da ileriye
    dönük kural yazıldı.

---

## 1. Yöntem — sayılar nereden geldi

| Sayı tipi | Yöntem | Örnek |
|---|---|---|
| CSS kutu ölçüsü | Kaynak koddaki Tailwind utility sınıfı → px (`1rem = 16px`, `w-12 = 3rem = 48px`) | `w-12 h-12` → 48×48 |
| İç (içerik) kutu | Kutu − 2× padding sınıfı (`p-1` = 4px, `p-0.5` = 2px, `p-3` = 12px) | 48 − 8 = 40 |
| Dosyanın fiziksel piksel ölçüsü | `file <path>` | `istoc-logo.png` → 87 x 32 |
| Dosya baytı | `stat -f "%z" <path>` | `icon-512.png` → 27128 |
| SVG düğüm sayısı | `re.findall(r'<([a-zA-Z][a-zA-Z0-9:_-]*)', kaynak)` uzunluğu | `ta-logo.svg` → 20 |
| DPR ihtiyacı | içerik kutusu × DPR, yukarı yuvarlama yok (tam çarpım) | 140 × 3 = 420 |
| Kırılım noktaları | `tradehubfront/src/style.css:256-260` — **projede ezilmiş**: `sm`=480, `md`=640, `lg`=768, `xl`=1024 | `md:w-32` ≥640px değil, **≥640px** (bkz. not) |

> **Kırılım tuzağı.** Bu projede Tailwind varsayılanları ezilmiş
> (`style.css:256-260`): `sm`=320/480, `md`=640, `lg`=768, `xl`=1024.
> `docs/reports/03-render-envanteri.md` §1.1 bunu tablolamış. Logo kutularında
> kullanılan kırılımlar: `md:w-32 md:h-32` (`brand.ts:101`) → **≥640px**,
> `lg:w-[50px]` (`ManufacturerList.ts:242`) → **≥768px**,
> `sm:h-[25px]` (`TopBar.ts:177`) → **≥480px**.

**Desteklenecek DPR aralığı: 1, 2, 3.** Gerekçe: `capacitor.config.ts:22` iOS+Android
hedefi tanımlı (`appId: 'com.istoc.app'`); modern iPhone ekranları DPR 3
(`preferredContentMode: 'mobile'`, `capacitor.config.ts:35`). DPR 4 desteklenmiyor —
piyasada anlamlı payı olan cihaz yok ve her rung'ı 1,78× büyütürdü.

---

## 2. AİLE A — Platform logosu (iStoc kelime markası)

Bu bir upload slotu **değil**: dosya derleme zamanında bundle'lanıyor
(`public/images/` → `dist/images/`). Bu yüzden `tradehub_core/media/pipeline/policy/slots/` altında
JSON'u yok. Kuralı burada yazılı.

**Kaynak dosyalar ve ölçüleri (hepsi `file` + `stat` çıktısı):**

| Dosya | Fiziksel px | Bayt | Alfa | Not |
|---|---|---:|---|---|
| `tradehubfront/public/images/istoc-logo.png` | **87 × 32** | 2 547 | RGBA ✓ | Koyu mürekkep + turuncu nokta (dosya görsel olarak okundu) |
| `tradehubfront/public/images/istoc-logo-beyaz.png` | 1370 × 521 | 17 255 | RGBA ✓ | Beyaz varyant |
| `tradehubfront/src/assets/images/istoc-logo.png` | 87 × 32 | 2 547 | RGBA ✓ | `public/`'takiyle bayt-özdeş kopya |
| `admin-panel/frontend/src/assets/media/istoc-logo.png` | 87 × 32 | 2 547 | RGBA ✓ | 3. kopya |
| `admin-panel/frontend/src/assets/media/istoc-logo-beyaz.png` | 1370 × 521 | 17 255 | RGBA ✓ | 2. kopya |
| `tradehubfront/src/assets/images/tas_logo.png` (Trade Assurance) | 443 × 600 | 12 099 | RGBA ✓ | `TopBar.ts:584`'te 32×32 kutuda |
| `tradehubfront/src/assets/images/ta-logo.svg` (Trade Assurance) | 305 × 46 (viewBox) | 12 379 | vektör | 20 düğüm, 15 `path` |

> **87×32 dosyası 5 kez kopyalanmış** (üçü `istoc-logo.png`, ikisi `-beyaz`). Bayt
> özdeşliği `stat -f %z` ile doğrulandı: 2547 = 2547 = 2547. Bu bir logo standardı
> sorunu değil, bir varlık yönetimi sorunu — §11'e not düşüldü.

### 2.1 Piksel tablosu — platform logosu (native yükseklik 32 px)

Genişlik çarpanı = 87 / 32 = **2,71875**. Tüm render'lar `w-auto` olduğu için
belirleyici olan **yükseklik**.

| # | Render noktası | Dosya:satır | CSS yük. | DPR1 | DPR2 | DPR3 | 87×32 yeter mi? |
|---|---|---|---:|---:|---:|---:|---|
| P1 | TopBar ana logo (`<400px`) | `header/TopBar.ts:177` | 18 | 18 | 36 | 54 | DPR1 ✓ / DPR2 ✗ / DPR3 ✗ |
| P1b | TopBar ana logo (≥400px) | `header/TopBar.ts:177` | 22 | 22 | 44 | 66 | ✓ / ✗ / ✗ |
| P1c | TopBar ana logo (≥480px `sm:`) | `header/TopBar.ts:177` | 25 | 25 | 50 | 75 | ✓ / ✗ / ✗ |
| P2 | TopBar kompakt (dashboard) | `header/TopBar.ts:189` | 24 | 24 | 48 | 72 | ✓ / ✗ / ✗ |
| P3 | Checkout minimal header | `checkout/CheckoutMinimalHeader.ts:79` | 18→25 | 25 | 50 | 75 | ✓ / ✗ / ✗ |
| P4 | AuthLayout üst (açık) | `auth/AuthLayout.ts:71` | 24 | 24 | 48 | 72 | ✓ / ✗ / ✗ |
| P5 | AuthLayout yan panel (beyaz) | `auth/AuthLayout.ts:95` | 40 | 40 | 80 | 120 | ✓ (1370×521 kaynak) |
| P6 | Help Center header (`<768`) | `help-center/HelpCenterHeader.ts:124` | 22 | 22 | 44 | 66 | ✓ / ✗ / ✗ |
| P6b | Help Center header (≥768 `lg:`) | `help-center/HelpCenterHeader.ts:124` | **26** | 26 | 52 | **78** | ✓ / ✗ / ✗ ← **en büyük talep** |
| P7 | Sepet özeti (`<380px`) | `cart/page/CartSummary.ts:126` | 12 | 12 | 24 | 36 | ✓ / ✓ / ✗ |
| P7b | Sepet özeti (varsayılan) | `cart/page/CartSummary.ts:126` | 14 | 14 | 28 | 42 | ✓ / ✓ / ✗ |
| P7c | Sepet özeti (≥480 `sm:`) | `cart/page/CartSummary.ts:126` | 16 | 16 | 32 | 48 | ✓ / ✓ (tam sınır) / ✗ |
| P8 | Sipariş özeti | `checkout/OrderSummary.ts:74` | 14→16 | 16 | 32 | 48 | ✓ / ✓ / ✗ |
| P9 | Yüzen panel | `floating/FloatingPanel.ts:92` | 20 | 20 | 40 | 60 | ✓ / ✗ / ✗ |
| P10 | Mağaza vitrini "powered by" | `pages/seller-shop.ts:184` | **10** | 10 | 20 | 30 | ✓ / ✓ / ✓ ← **tek tam geçen** |
| P11 | Şifre sıfırlama / davet / başvuru / mobil nav / tedarikçi kurulum (6 yer) | `auth/AcceptInvitePage.ts:19`, `auth/ForgotPasswordPage.ts:51`, `auth/ResetPasswordPage.ts:25`, `seller/ApplicationPendingPage.ts:22`, `sidebar/MobileDashboardNav.ts:121`, `pages/supplier-setup.ts:68` | 28 (`h-7`) | 28 | 56 | 84 | ✓ / ✗ / ✗ |
| P12 | Admin panel giriş / auth layout (4 `<img>`) | `admin/layouts/AuthLayout.vue:19,20`, `admin/views/auth/LoginView.vue:6,7` | 32 (`h-8`) | 32 | 64 | 96 | ✓ (tam sınır) / ✗ / ✗ |
| P13 | Trade Assurance mega menü | `header/TopBar.ts:584` | 32 | 32 | 64 | 96 | ✓ (443×600 kaynak) |

**Sonuç (aritmetik):** 87×32 dosyası **19 render varyantından 4'ünde** DPR 2'yi
geçiyor (P7, P7b, P7c, P10) ve **yalnız 1'inde** DPR 3'ü geçiyor (P10, `h-[10px]`).

### 2.2 KARAR — platform logosu

| Alan | Değer | Dayanak |
|---|---|---|
| **Birincil format** | **SVG** (sanitize gerekmez — bundle varlığı, kullanıcı yüklemesi değil) | Kelime markası vektör; DPR bağımsız. Proje bunu **zaten yapabiliyor**: `src/assets/images/ta-logo.svg` (12 379 B, 20 düğüm) Vite ile bundle'lanıyor ve `TopBar.ts` içinde kullanılıyor. Yeni altyapı gerekmiyor. |
| **Raster yedek** | **261 × 96 PNG** (alfa zorunlu) | 87×32'nin tam 3 katı → tamsayı ölçek, yeniden örnekleme artefaktı yok. 96 px yükseklik en büyük talebi (P6b DPR3 = 78) **%23 pay** ile karşılar. |
| **Koyu tema varyantı** | **ZORUNLU** | `style.css:19` `@variant dark (&:where(.dark, .dark *))` → koyu tema aktif bir özellik. `TopBar.ts:875` `bg-white dark:bg-gray-900`. `istoc-logo.png` görsel olarak okundu: koyu mürekkep. Beyaz varyant **zaten var** (`istoc-logo-beyaz.png`), sadece bağlanmamış. |
| **Maksimum bayt (SVG)** | **8 192 B** (8 KB) | Ölçülen referans: `public/vite.svg` 1 497 B / 11 düğüm; `amex.svg` 4 879 B / 2 düğüm. iStoc kelime markası bu ikisinin karmaşıklığında. 8 KB = en büyük ölçülen basit logonun (`amex.svg`) 1,68 katı. |
| **Maksimum bayt (PNG 261×96)** | **12 288 B** (12 KB) | Ölçülen: 87×32 PNG = 2 547 B → 0,915 B/px. 261×96 = 25 056 px × 0,915 = 22 926 B. Ölçek büyüdükçe B/px düşer (PNG'de düz alanlar daha iyi sıkışır); ölçülen karşılaştırma: `icon-128.png` 3 600 B / 16 384 px = 0,220 B/px, `icon-512.png` 27 128 B / 262 144 px = 0,103 B/px. 261×96 için 0,4–0,5 B/px makul → 10–12,5 KB. Tavan **12 KB**. |
| **Alfa** | **ZORUNLU** | 19 render noktasının hepsi logoyu renkli/gradyanlı bir yüzeye basıyor. Örnek: `TopBar.ts:811` "Logo (smaller, white for gradient bg)" yorumu ve gradyan başlık. Opak dikdörtgen bu yüzeylerde görünür kutu üretir. |
| **Güvenli alan** | **file içinde 0%** | Bu 19 noktanın hiçbirinde logoya CSS padding uygulanmıyor (tümü `w-auto` + salt yükseklik). Dosya kenardan kenara olmalı; padding eklemek her render noktasında logoyu %X küçültür ve tablo bozulur. |
| **En-boy oranı** | **2,71875 : 1 (sabit)** | 87/32. Tüm render'lar `w-auto` — oran değişirse 19 yerde satır yüksekliği kayar. Yeni bir SVG çizilirse `viewBox` bu oranda olmalı. |
| **Favicon** | 32 / 48 / 96 PNG **+ 180 apple-touch** | Mevcut: `public/images/istoc-favicon-{32,48,96}.png` (1 644 / 2 443 / 4 745 B, `file` → 8-bit/color **RGB**, alfasız). `index.html:5` yalnız **32'yi** bildiriyor; `tradehub_core/seo/templates/seo_head.html:3-5` üçünü de bildiriyor. Yani Frappe-render'lı sayfa storefront'tan daha iyi. `index.html` 48+96 eksik. `apple-touch-icon.png` var (180×180, 5 714 B) ama `index.html`'de `<link rel="apple-touch-icon">` **yok** (`grep -n "apple-touch" index.html` → eşleşme yok). |
| **PWA ikonu** | 192 / 512 `any` + 192 / 512 `maskable` + 180 apple | `vite.config.ts:410-416` bunu zaten doğru yapıyor. Değişiklik gerekmez. `public/manifest.webmanifest` (elle yazılmış, `.webp` uzantılı PNG'lere işaret eden, `"type": "image/png"` yazan) **ölü dosya** — VitePWA kendi manifest'ini üretiyor (`dist/manifest.webmanifest` içeriği doğrulandı). |
| **og:image (varsayılan)** | **1200 × 630 JPEG** | `public/images/og-default.jpg` **zaten var** (`file` → 1200×630, 47 649 B) ama `grep -rn "og-default" src/ pages/ index.html` → **eşleşme yok**. Hiçbir yerden referans verilmiyor. `index.html:8-10` og:title/description/type var, **og:image yok**. |

---

## 3. AİLE B — Satıcı logosu (`seller.logo`)

**Slot:** `Admin Seller Profile.logo`, `fieldtype: Attach Image`
(`docs/reports/00-upload-slot-envanteri.md` Tablo A, satır 1).
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/seller-logo.json`

### 3.1 Render noktası envanteri — 15 nokta

"İçerik kutusu" = görselin gerçekten kapladığı kutu = dış kutu − 2× CSS padding.

| # | Render noktası | Dosya:satır | Dış kutu | Padding | **İçerik kutusu** | fit | Alt plaka |
|---|---|---|---|---|---:|---|---|
| S1 | Mağaza vitrini başlığı — masaüstü (≥480px) | `tradehubfront/src/pages/seller-shop.ts:124-129` | 140×140 (`w-[140px] h-[140px]`) | yok | **140** | `object-cover` ⚠ | **YOK** ⚠ |
| S2 | Mağaza vitrini başlığı — mobil (`sm:hidden`) | `pages/seller-shop.ts:204-207` | 50×50 | yok | **50** | `object-contain` | `bg-white` |
| S3 | Şirket bilgisi bloğu | `components/seller/CompanyInfo.ts:47` | `w-[120px] h-auto` | yok | **120** (genişlik) | `object-contain` | yok (metin bloğu içinde) |
| S4 | Mağaza sayfası "Tedarikçiye ulaş" yan kutusu | `components/seller/CompanyProfile.ts:1029-1030` | 48×48 (`w-12 h-12`) | `p-1` = 4 | **40** | `object-contain` | `bg-gray-50` |
| S5 | Ürün detay tedarikçi kartı | `components/product/CompanyProfile.ts:109` | 64×64 (`h-[64px] w-[64px]`) | yok | **64** | `object-contain` | `bg-white` |
| S6 | Üretici listesi kartı (≥768 `lg:`) | `components/manufacturers/ManufacturerList.ts:242-246` | 50×50 (`lg:w-[50px]`) | `p-1` = 4 | **42** | `object-contain` | `bg-gray-50` |
| S6b | Üretici listesi kartı (`<768`) | aynı | 48×48 (`w-12 h-12`) | `p-1` = 4 | **40** | `object-contain` | `bg-gray-50` |
| S7 | Üretici hero — "top ranking" karosu | `components/manufacturers/ManufacturersHero.ts:277-279` | 116×116 | yok | **116** | `object-contain` | `bg-gray-50` |
| S8 | Favoriler → kayıtlı satıcı satırı | `components/favorites/FavoritesLayout.ts:368-370` | 40×40 (`size-10`) | `p-1` = 4 | **32** | `object-contain` | `bg-gray-50` |
| S9 | Vitrin şablonu — kişi bilgisi kartı | `utils/seller/section-registry.ts:620-621` | 56×56 | `p-1` = 4 | **48** | `object-contain` | `bg-gray-100` |
| S10 | Vitrin şablonu — şirket mini kartı | `utils/seller/section-registry.ts:749-750` | 40×40 (`w-10 h-10`) | `p-0.5` = 2 | **36** | `object-contain` | `bg-gray-50` |
| S11 | Marka sayfası "satıcı" rozeti | `pages/brand.ts:138` | 16×16 (`w-4 h-4`) | yok | **16** | `object-contain` | `bg-white/10` (yarı saydam) |
| S12 | Satıcı dashboard üst başlık | `pages/seller-dashboard.ts:65-66` | 48×48 (`w-12 h-12`) | yok | **48** | `object-cover` ⚠ | `bg-gray-100` |
| S13 | Satıcı dashboard hesap formu önizleme | `pages/seller-dashboard.ts:157-158` | 56×56 (`w-14 h-14`) | yok | **56** | `object-cover` ⚠ | `bg-gray-50` |
| S14 | **Admin panel** — Admin Seller Profile formu dropzone | `admin-panel/frontend/src/components/upload/ProfileImageDropzone.vue:135` (`shape="square"` → `w-40 h-40`), bağlanma noktası `views/doctype/DocTypeFormView.vue:439-451` | 160×160 | yok | **160** ← **en büyük** | (dropzone içi) | — |
| S15 | **Admin panel** — Mağaza Ayarları logo önizleme | `admin/views/seller/StorefrontEdit.vue:74-82` | 80×80 (`w-20 h-20`) | yok | **80** | `object-cover` ⚠ | dashed border |
| S16 | **Admin panel** — Vitrin düzeni header logo önizleme | `admin/views/seller/StorefrontLayoutEditor.vue:241-249` | 64×64 (`w-16 h-16`) | yok | **64** | `object-cover` ⚠ | `bg-gray-50` |

**Ölçüm dışı bırakılanlar (gerekçeli):**
- `components/product/ProductSellerPanel.ts:122-124` — yorumda "logo 40×40" yazıyor ama
  kod **harf baş harfleri** basıyor (`sellerInitial`), `<img>` yok. Logo render noktası **değil**.
- `components/product/MobileLayout.ts:490` — sınıf adı `pdm-supplier-logo` ama içerik
  baş harfler (`si.name.charAt(0)`). Logo render noktası **değil**.
- `components/messages/*` — sohbet avatarı satıcı logosu **değil**:
  `alpine/messages.ts:97-100` `avatarFor()` üçüncü parti `https://ui-avatars.com/api/?...`
  URL'i üretiyor. Bu ayrı bir bulgu (§11-F7), logo slotu değil.

### 3.2 Piksel tablosu — DPR 1/2/3

| # | İçerik kutusu | DPR1 | DPR2 | DPR3 | Servis edilecek rung (§3.3) |
|---|---:|---:|---:|---:|---|
| S11 | 16 | 16 | 32 | 48 | 64 |
| S8 | 32 | 32 | 64 | 96 | 64 / 128 |
| S10 | 36 | 36 | 72 | 108 | 64 / 128 |
| S4, S6b | 40 | 40 | 80 | 120 | 64 / 128 |
| S6 | 42 | 42 | 84 | 126 | 64 / 128 |
| S9, S12 | 48 | 48 | 96 | 144 | 64 / 128 / 256 |
| S2 | 50 | 50 | 100 | 150 | 64 / 128 / 256 |
| S13 | 56 | 56 | 112 | 168 | 64 / 128 / 256 |
| S5, S16 | 64 | 64 | 128 | 192 | 64 / 128 / 256 |
| S15 | 80 | 80 | 160 | 240 | 128 / 256 / 256 |
| S7 | 116 | 116 | 232 | 348 | 128 / 256 / 512 |
| S3 | 120 | 120 | 240 | 360 | 128 / 256 / 512 |
| S1 | 140 | 140 | **280** | **420** | 256 / 512 / 512 |
| S14 | **160** | 160 | 320 | **480** | 256 / 512 / 512 |

**Maksimum ihtiyaç = 480 px** (S14, DPR 3). Storefront-only maksimum = **420 px** (S1, DPR 3).

### 3.3 KARAR — türev merdiveni (derivative ladder)

**Rung'lar: 64, 128, 256, 512 (kare, px).**

Gerekçe — ölçülen 14 farklı içerik kutusunun DPR 1/2/3 kombinasyonu 42 talep üretiyor;
bu 4 rung hepsini karşılıyor ve en kötü aşırı-servis oranı **280 → 512 = 1,83× doğrusal
(3,35× piksel)**. Beşinci bir rung (384) bu en kötü durumu 1,37×'e indirir ama:

- 512 rung'unun ölçülen referans baytı **27 128 B** (`icon-512.png`, 512×512 RGBA, kayıpsız PNG).
- 384 rung'u ≈ 512'nin 0,5625 katı piksel → tahmini 15–16 KB.
- Kazanç yalnız 3 talepte (280, 348, 360) ve satıcı başına ~11 KB.

Logo dosyaları mutlak olarak küçük olduğu için 4 rung yeterli. **384 rung'u
ONAY BEKLEYEN KARARLAR listesinde** (§13-K3).

**Bir rung ne zaman ÜRETİLMEZ:** master'ın kendi kenarından büyük rung üretilmez.
`media/engine.py:117` `im.thumbnail((max_dim, max_dim))` **yalnız küçültür** —
"upscale yok" (`engine.py:97` docstring). Yani 400×400 bir master'dan 512 rung'u
**hiçbir zaman doğmaz**. Bugünkü panel tavsiyesi (400×400,
`DocTypeFormView.vue:448`) bu yüzden 512 rung'unu ölü bırakır.

### 3.4 KARAR — master (kaydedilen orijinal) ölçüsü

| Eşik | Değer | Davranış | Dayanak |
|---|---:|---|---|
| **Önerilen** | **512 × 512** | Sessiz kabul | En büyük rung. `engine.py:117` upscale yapmadığı için 512 rung'unu doğurabilen tek alt sınır. |
| **Uyarı eşiği** | 256 – 511 px | Kabul + `logo_low_resolution` uyarısı; üretilebilen en büyük rung master'ın kendi ölçüsü | 256 px, S1'in (140 CSS px) DPR 2 talebini (280) **%8,6 açıkla** karşılamıyor — görsel olarak fark edilmesi zor, işlevsel olarak kabul edilebilir. |
| **Sert ret** | < 256 px (kısa kenar) | **RET**, kod `logo_too_small` | 256'nın altında S7 (116 px kutu) bile DPR 2'de (232) sınıra dayanır ve S1 DPR 2'de %8,6'dan fazla açık kalır. |
| **Üst sınır** | 4096 × 4096 | Üstü kabul, master 4096'ya küçültülür | `presets.py:16` `balanced.max_dim = 2000`, `safe.max_dim = 2560`. Logo için 4096 bu üçünden de büyük; niyet: kullanıcının vektörden export ettiği büyük PNG'yi reddetmemek, ama sınırsız da bırakmamak. Küçültme `engine.optimize` ile. |

### 3.5 KARAR — en-boy oranı

**Ölçüm:** 16 render noktasının **15'i 1:1 kare kutu**. Tek istisna
`CompanyInfo.ts:47` (`w-[120px] h-auto`) — serbest yükseklik.

**Kabul edilen oran bandı: 1:2 … 2:1 (w:h).** Dışı → RET, kod `logo_aspect_out_of_band`.

> **ÖLÇÜMLE ONAYLANDI — 2026-08-18.** §13-K2'nin tetiği ("band dışı > %20 ise iki-dosya
> modeline geç") çalıştırıldı: ölçülen 18 gerçek logonun **16'sı (%89) band içinde**,
> band dışı yalnız **2 dosya (%11)** ve ikisi de aynı orana sahip geniş kelime markası
> (w/h = 2,876). %11 < %20 → **band değişmedi.** Kaynak: `docs/reports/08-canli-olcum.md` §2.1.

Gerekçe (en küçük kutuya göre): en küçük içerik kutusu **32×32**
(S8, `FavoritesLayout.ts:368` `size-10` + `p-1`). `object-contain` ile 2:1 bir kelime
markası bu kutuda **32 × 16 px** olarak çizilir. 16 px, platform logosunun kendi en küçük
render'ıyla (`CartSummary.ts:126` `sm:h-4` = 16 px) **aynı büyüklük** — yani okunabilirlik
için sistemde zaten kabul edilmiş bir taban. 4:1'de aynı kutu 32 × 8 px verir; bu tabanın
yarısı. Bu yüzden band 2:1'de kapanıyor.

**Depolanan master oranı: her zaman 1:1.** Motor, kabul bandındaki her master'ı
**saydam letterbox** ile 1:1'e tamamlar (contain + pad, asla crop).

Gerekçe — bu, ölçülen bir hatayı çözer: **5 render noktası `object-cover` kullanıyor**
(S1 `seller-shop.ts:129`, S12 `seller-dashboard.ts:66`, S13 `seller-dashboard.ts:158`,
S15 `StorefrontEdit.vue:79`, S16 `StorefrontLayoutEditor.vue:247`). Kare olmayan bir
logo bu 5 yerde **merkezden kırpılır**. Master'ı 1:1'e padleyerek kırpma
matematiksel olarak imkânsız hâle gelir (kare kutu × kare kaynak = kırpma yok) ve
**mevcut kodun tek satırına dokunmadan** çözülür.

### 3.6 KARAR — format önceliği

**SVG > alfalı PNG > kayıpsız WebP > (alfalı AVIF, opsiyonel) > JPEG (uyarıyla, en son)**

> **GÜNCELLENDİ — 2026-08-18.** JPEG bu tabloda başlangıçta **✗ RET** idi. §13-K1'in
> tetiği ölçümle aşıldı (**JPEG payı %50**, tetik %10) → JPEG artık **reddedilmiyor,
> uyarılıyor**. Sıralamadaki yeri değişmedi: en sonda, "kabul edilir ama tavsiye
> edilmez". Ayrıntı ve gerekçe: §13-K1.

| Format | Karar | Dayanak |
|---|---|---|
| **SVG** | 1. tercih — **ama yalnız sanitize'den sonra** (§6) | Vektör; 4 rung'un tamamını tek dosyayla karşılar. Bugün **iki kapıda yasak**: `utils/security.py:29-30`, `upload_policy.py:190`. |
| **Alfalı PNG** | 2. tercih, **bugünkü tek geçerli seçenek** | `upload_policy.py:59` izin listesinde. `engine.optimize()` PNG'yi **kayıpsız** tutuyor: `engine.py:120-122` `im.save(buf, "PNG", optimize=True, icc_profile=icc)` — "PNG kayıpsızdır; quality parametresi geçerli değil". |
| **Kayıpsız WebP** | 3. tercih — **kod değişikliği şart** | `engine.py:180` `im.save(buf, "WEBP", quality=quality, method=4)`, `quality` varsayılanı **80** (`engine.py:148`). Bu **kayıplı**. Logo slotu için `lossless=True` gerekir. |
| **Kayıplı WebP** | ✗ RET (türev olarak da üretilmez) | Kesin kenar + düz renk = q80'de halkalanma. |
| **AVIF (alfalı)** | Opsiyonel 4. rung formatı | `upload_policy.py:59` `.avif` izinli. Fakat `engine.py:21` `SUPPORTED_FORMATS = {"JPEG","PNG","WEBP","TIFF"}` — **AVIF `optimize()` tarafından işlenemiyor** ("unsupported_format", `engine.py:109`). `seller_media` yolunda ise AVIF **WebP'ye çevriliyor** (`api/seller_media.py:245` `IMAGE_TO_WEBP_EXTENSIONS` içinde `.avif` var). Yani AVIF logo bugün AVIF olarak yaşamıyor. Kapsam dışı. |
| **JPEG** | ⚠ **UYARIYLA KABUL**, kod `logo_format_no_alpha` (2026-08-18'e kadar: ✗ RET) | JPEG'de alfa kanalı format tanımı gereği yok. 16 render noktasının **11'i** logonun altına açık gri/beyaz plaka koyuyor (`bg-gray-50` ×6, `bg-white` ×2, `bg-gray-100` ×2, `bg-white/10` ×1) — beyaz zeminli opak bir JPEG bu plakaların üzerinde görünür bir dikdörtgen bırakır. Ayrıca S1 (`seller-shop.ts:124`) **hiç plaka koymuyor**. **Bu görsel gerekçe hâlâ geçerli**, ama ölçüm reddi imkânsız kıldı: mevcut 18 gerçek logonun **9'u (%50) JPEG** (`docs/reports/08-canli-olcum.md` §2.1) → §13-K1 = B. Yaptırım `warn`, kullanıcıya ne kaybettiği söylenir. |
| **GIF** | ✗ RET, kod `logo_format_animated` | `upload_policy.py:59` izinli ama `engine.py:112` animasyonluyu atlıyor (`reason="animated"`) ve `api/seller_media.py:245` `.gif`'i WebP dönüşümünden bilinçli dışarıda tutuyor. Logo animasyonlu olmamalı. |
| **TIFF / BMP / HEIC** | ✗ RET, kod `logo_format_not_supported` | `upload_policy.py:59` izinli ama tarayıcı hiçbirini render etmez; `seller_media` yolu WebP'ye çevirir, `runner` yolu TIFF'i TIFF bırakır (`engine.py:126-131`). İki yol ayrışıyor. Logo slotunda kabul edilmemeli. |

**Alfa: TAVSİYE EDİLİR, ZORUNLU DEĞİL** (2026-08-18'e kadar: ZORUNLU). Alfa kanalı
taşıyan mod (`RGBA`, `LA`, veya `transparency` bilgisi taşıyan `P`) **beklenen**
durumdur; taşımayan dosya reddedilmez, **uyarı** üretir ve envantere `logo_opaque`
olarak düşer (§13-K1). Ölçüm (`docs/reports/08-canli-olcum.md` §2.1): 18 gerçek
logonun yalnız **4'ü (%22)** alfa taşıyor — "zorunlu" demek dosyaların %78'ini
reddetmek olurdu. `engine.py:169-176` bu üç modu zaten doğru ayırt ediyor; o mantık
logo slotunda **yeniden yazılmamalı**, ölçüm için çağrılmalı.

### 3.7 KARAR — bayt tavanları

| Katman | Tavan | Dayanak |
|---|---:|---|
| **Yükleme (master, raster)** | **1 048 576 B (1 MiB)** | 512×512 RGBA'nın **sıkıştırılmamış** boyutu = 512 × 512 × 4 = 1 048 576 B. Kendi ham raster'ından büyük bir dosya tanım gereği logo değil. Bugünkü fiili tavanlar: sunucu 25 MB (`upload_policy.py:68`), panel dropzone 5 MB (`ProfileImageDropzone.vue:123`), `identity.update_profile_image` 5 MB (`api/v1/identity.py:940-955`). 1 MiB üçünden de dar. |
| **Yükleme (master, SVG)** | **32 768 B (32 KiB)** | Ölçüm: `ta-logo.svg` (gerçek bir kelime markası, 305×46) = **12 379 B**. 32 KiB = bunun 2,65 katı. Karşı örnek — tavansız hâlde ne olduğu: aynı klasörde `ta-shield-pattern.svg` **105 516 B**, `svgviewer-output.svg` **137 695 B** (otomatik trace edilmiş illüstrasyon). Bayt tavanı bu ikisini reddeder. |
| **Türev 512** | **40 960 B (40 KiB)** | Ölçülen referans: `icon-512.png` = 27 128 B (512×512 RGBA kayıpsız PNG, `stat`). +%51 pay. |
| **Türev 256** | **16 384 B (16 KiB)** | Ölçülen: `icons/icon-256.webp` (gerçekte PNG, `file` ile doğrulandı) = 9 159 B. +%79 pay. |
| **Türev 128** | **8 192 B (8 KiB)** | Ölçülen: `icons/icon-128.webp` (gerçekte PNG) = 3 600 B. +%128 pay. |
| **Türev 64** | **4 096 B (4 KiB)** | Ölçülen: `icons/icon-48.webp` 1 332 B, `icon-72.webp` 2 021 B → 64 px için ara değer ≈ 1 700 B. +%141 pay. |

> Türev paylarının rung küçüldükçe genişlemesi kasıtlı: küçük ölçekte PNG başlık
> maliyeti (IHDR + palet + CRC) baytın sabit bir yüzdesini yiyor, ölçülen B/px eğrisi
> bunu gösteriyor (0,103 → 0,220 → 0,578 B/px sırasıyla 512 / 128 / 48 px'te).
> Tavan aşılırsa üretim **başarısız sayılmaz**; `logo_derivative_oversize`
> uyarısıyla yazılır ve envantere düşer. Aksi hâlde meşru ama karmaşık bir logo
> sessizce türevsiz kalırdı.

### 3.8 KARAR — güvenli alan (padding)

**Dosyanın içinde: 0% (kenardan kenara).**
**CSS tarafında: 8% (yalnız YENİ render noktaları için).**

Ölçüm — mevcut kodun logoya uyguladığı CSS padding'i, kutunun yüzdesi olarak:

| Render | Padding | Dış kutu | Kenar başına % |
|---|---|---:|---:|
| S10 `section-registry.ts:750` | `p-0.5` = 2 px | 40 | 5,00 % |
| S9 `section-registry.ts:621` | `p-1` = 4 px | 56 | 7,14 % |
| S4 `seller/CompanyProfile.ts:1030` | `p-1` = 4 px | 48 | 8,33 % |
| S6b `ManufacturerList.ts:245` | `p-1` = 4 px | 48 | 8,33 % |
| B1b `brand.ts:101` (`md:`) | `p-3` = 12 px | 128 | 9,375 % |
| S8 `FavoritesLayout.ts:370` | `p-1` = 4 px | 40 | 10,00 % |
| B1 `brand.ts:101` | `p-3` = 12 px | 96 | 12,50 % |

Medyan = **8,33 %** → standart değer **8 %**.

**Neden dosyaya gömülmüyor:** yukarıdaki 7 nokta padding'i **zaten CSS'te uyguluyor**.
Dosyaya %8 gömmek bu 7 yerde çift padding üretir (%8 + %8,33 = %16,3 → 40 px kutuda
logo 27 px'e düşer). Padding'i dosyaya taşımak 7 mevcut dosyada CSS değişikliği
gerektirir — bu görevin 1. mutlak kuralı bunu yasaklıyor ve zaten çalışan bir
mekanizmayı yeniden tasarlamak olur. Karar: **güvenli alan CSS'in sorumluluğunda
kalır**, standart yalnız değeri sabitler (%8) ve yeni render noktalarını bağlar.

**Tek istisna — oran normalizasyonu paddingi:** §3.5'teki 1:1 letterbox **saydam**
piksel ekler, görsel bir kenar boşluğu değildir. Logonun kendi kenarı ile canvas
kenarı arasına ek boşluk **konmaz**.

### 3.9 KARAR — koyu tema varyantı: GEREKMİYOR

**Ölçüm:** 16 render noktasının **11'i** logonun altına açık bir plaka boyuyor:
`bg-gray-50` (S4 `:1029`, S6 `:242`, S7 `:277`, S8 `:368`, S10 `:749`, S13 `:157`,
S16 `:243`), `bg-white` (S2 `:204`, S5 `:109`), `bg-gray-100` (S9 `:620`, S12 `:65`).
Bu plakalar `dark:` varyantı **taşımıyor** — yani koyu temada da açık kalıyorlar.
Logo her koşulda açık zemin üzerinde.

Plakasız 5 nokta: S1, S3, S11, S14, S15.
- S3 (`CompanyInfo.ts:47`) beyaz içerik bloğunda.
- S11 (`brand.ts:138`) `bg-white/10` yarı saydam, marka hero'sunun koyu gradyanı üstünde
  (`brand.ts:145-147` `linear-gradient(rgba(17,24,39,0.55), rgba(17,24,39,0.75))`) →
  **bu tek nokta koyu zemin**, ama kutu 16×16 ve dekoratif.
- S14/S15 admin panel önizlemesi.
- **S1 (`seller-shop.ts:124`) gerçek risk:** plaka yok, arka plan satıcının kendi
  `header_bg_image`'i (`:118-119`). Karanlık bir header görseline koyu bir logo binebilir.

**Karar:** satıcı logosu için koyu tema varyantı **istenmez** (satıcıdan iki dosya
istemek, 11 noktada gereksiz, 1 noktada çözülebilir bir sorun için). Yerine kural:
**logo her zaman açık bir plaka üzerinde render edilir.** S1 bu kuralı ihlal ediyor →
§11-F3'te bulgu olarak kayıtlı, düzeltmesi bu görevin kapsamı dışında.

### 3.10 KARAR — og:image türevi

Satıcı logosu og:image kaynağı olarak **kullanılıyor**: `seo/meta_builder.py:261`
`og_image_resolver=lambda r: ensure_og_image(r, source_field="logo")`.

Mevcut davranış (`seo/og_image.py`) üç yerde logoya zarar veriyor:

| Satır | Kod | Logoda sonucu |
|---|---|---|
| `:34` | `img = img.convert("RGB")` | **Alfa düşer.** Saydam logo, PIL'in RGBA→RGB dönüşümünde alfa kanalını atarak siyah/çöp zemin alır. |
| `:45-49` | cover-crop dalı (`src_ratio <= target_ratio`) | 1:1 bir logo: `new_w = 1200`, `new_h = round(512 × 1200/512) = 1200`, `top = (1200−630)//2 = 285`, `crop(0, 285, 1200, 915)`. **Logonun yüksekliğinin %47,5'i kesilir** (285 üstten + 285 alttan = 570 / 1200). Kalan: orta yatay bant. |
| `:51` | `img.save(out_path, "JPEG", quality=85, optimize=True)` | **Kayıplı**, ayrıca JPEG olduğu için alfa zaten imkânsız. |

**KARAR — logo kaynaklı og:image kuralı:**
- 1200 × 630 canvas, **contain + pad** (cover-crop DEĞİL). Logo merkeze, en fazla
  **630 × 0,72 = 453 px** yükseklikte yerleşir (%14 üst + %14 alt güvenli alan).
- Zemin: **düz beyaz `#FFFFFF`** (alfa düşürülecekse belirli bir renge düşürülür,
  PIL'in varsayılanına bırakılmaz).
- Çıktı: JPEG q85 kalabilir (og:image tüketicileri PNG/alfa beklemiyor; Facebook/X
  render'ı zaten düz zemine bindiriyor). Kayıplı encode burada kabul — çünkü logo
  453 px'e ölçeklendiğinde kenar zaten yumuşuyor ve dosya paylaşım hızını etkiliyor.
- `_resolve_to_disk_path` (`og_image.py:59-69`) yalnız `/files/…` ve absolute path
  çözüyor → `data:` URI logolar (§7) sessizce `""` dönüyor ve site varsayılanına
  düşüyor. Bu **doğru davranış**, ama sessiz; log gerekiyor.

---

## 4. AİLE C — Marka logosu (`brand.logo`)

**Slot:** `Brand.logo`, `fieldtype: Attach Image`
(`docs/reports/00-upload-slot-envanteri.md` Tablo A).
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/brand-logo.json`

### 4.1 Render noktası envanteri — 3 nokta

| # | Render noktası | Dosya:satır | Dış kutu | Padding | **İçerik kutusu** | fit | Alt plaka |
|---|---|---|---|---|---:|---|---|
| B1 | Marka hero logosu (`<640px`) | `tradehubfront/src/pages/brand.ts:101` | 96×96 (`w-24 h-24`) | `p-3` = 12 | **72** | `object-contain` | `bg-white` |
| B1b | Marka hero logosu (≥640px `md:`) | `pages/brand.ts:101` | 128×128 (`md:w-32 md:h-32`) | `p-3` = 12 | **104** ← en büyük | `object-contain` | `bg-white` |
| B2 | Ürün filtre kenar çubuğu — marka satırı | `components/products/FilterSidebar.ts:698` | 16×16 (`w-4 h-4`) | yok | **16** | `object-contain` | filtre satırı (beyaz) |

**Ölçülemedi ama var:** `api/search.py:81` ve `:93` marka logosunu arama öneri
yanıtına koyuyor (`"logo": r.logo or ""`); `api/tailored.py:721` de `logo` alanını
çekiyor. **Bu verinin storefront'ta bir `<img>`'e bağlandığı yer bulunamadı** —
`grep -rn "logo" src/ | grep -iE "<img|:src="` çıktısında arama öneri bileşeni yok.
Yani backend logoyu gönderiyor, frontend basmıyor. §11-F6.

### 4.2 Piksel tablosu

| # | İçerik kutusu | DPR1 | DPR2 | DPR3 | Rung |
|---|---:|---:|---:|---:|---|
| B2 | 16 | 16 | 32 | 48 | 64 |
| B1 | 72 | 72 | 144 | 216 | 128 / 256 / 256 |
| B1b | **104** | 104 | 208 | **312** | 128 / 256 / **512** |

**Maksimum ihtiyaç = 312 px** (B1b, DPR 3).

### 4.3 KARAR — marka logosu

Satıcı logosundan **tek farkı master alt sınırı**. Diğer her şey (merdiven, formatlar,
oran bandı, alfa, bayt tavanları, güvenli alan) **aynı** — iki ayrı standart tutmanın
bakım maliyeti, ölçülen fark (480 vs 312 px) karşılığında haklı değil.

| Alan | Değer | Dayanak / satıcıdan fark |
|---|---|---|
| Türev merdiveni | 64, 128, 256, 512 | Aynı. 312 talebi 512 rung'u ile karşılanır (1,64× aşırı-servis). |
| **Önerilen master** | **384 × 384** | 312 talebini karşılayan en küçük 2'nin katı olmayan tamsayı-dostu ölçü. 512'ye çıkarmak 512 rung'unu doğururdu; B1b onu asla kullanmaz. |
| **Uyarı eşiği** | 256 – 383 | 256'da B1b DPR 2 talebini (208) rahat karşılar; DPR 3 (312) açıkta kalır. |
| **Sert ret** | < 256 | Aynı gerekçe: B1 (72 px) DPR 3'te 216 istiyor. |
| Üst sınır | 4096 × 4096 | Aynı. |
| Oran bandı | 1:2 … 2:1, master 1:1'e saydam letterbox | Aynı. B2 (16×16) en küçük kutu; 2:1'de 16×8 → 8 px. **Satıcıdaki 32 px tabanından daha sıkışık** ama B2 dekoratif bir liste rozeti (marka adı yanında metin var), tek başına taşıyıcı değil. |
| Alfa | ZORUNLU | 3 render noktasının 2'si `bg-white` plaka; B1b marka hero'sunun **koyu gradyanı** üstünde beyaz plaka. Opak logo plakayla aynı renk olursa görünmez. |
| Bayt tavanı (master raster) | **589 824 B (576 KiB)** | 384 × 384 × 4 = 589 824 — aynı "ham raster" kuralı, 384 master'a uyarlanmış. |
| Bayt tavanı (master SVG) | 32 768 B | Aynı. |
| Güvenli alan | CSS'te %8; dosyada 0 | `brand.ts:101` `p-3` zaten %12,5 (96 kutu) / %9,375 (128 kutu) uyguluyor. |
| Koyu tema varyantı | **GEREKMİYOR** | Her iki hero varyantı `bg-white` plaka veriyor (`brand.ts:101`); B2 beyaz filtre satırında. Satıcıdaki S1 riski markada **yok** — marka hero'sunun arka planı logonun altına gelmiyor, plaka araya giriyor. |
| **og:image** | Aynı contain+pad kuralı | `seo/meta_builder.py:282` marka için de `source_field="logo"`. Aynı 3 hata (§3.10) markada da geçerli. |

---

## 5. Türev matrisi — ne üretilecek

Her iki slot için, her kabul edilen master'dan üretilecek dosyalar:

| Rung | Format | Encode | Bayt tavanı | Hangi render'ı besler |
|---:|---|---|---:|---|
| 64 | WebP **kayıpsız** | `lossless=True`, `method=6` | 4 KiB | S11/B2 (DPR3), S8 (DPR2), S4/S6/S10 (DPR1-2), S2/S5/S9/S12/S13/S16 (DPR1) |
| 64 | PNG (yedek) | `optimize=True` | 4 KiB | WebP desteklemeyen istemci — bkz. not |
| 128 | WebP kayıpsız + PNG | aynı | 8 KiB | S8/S10/S4/S6 (DPR3), S9/S2/S13/S5/S16 (DPR2), S15/S7/S3 (DPR1), B1 (DPR1-2) |
| 256 | WebP kayıpsız + PNG | aynı | 16 KiB | S9/S2/S13/S5/S16 (DPR3), S15 (DPR2-3), S7/S3 (DPR2), S1/S14 (DPR1), B1b (DPR2), B1 (DPR3) |
| 512 | WebP kayıpsız + PNG | aynı | 40 KiB | S7/S3 (DPR3), S1/S14 (DPR2-3), B1b (DPR3) |
| 1200×630 | JPEG q85, contain+pad, beyaz zemin | `seo/og_image.py` düzeltilmiş yol | 120 KiB | `og:image` / `twitter:image` |
| (master) | Yüklenen formatın kayıpsız hâli | — | 1 MiB / 576 KiB | Arşiv; yeniden türev üretimi |

> **PNG yedeği neden var:** proje AVIF'i statik pazarlama görselinde kullanıyor
> (`SellPageLayout.ts:21` `assets/images/liman.avif`) ama kullanıcı medyası hattında
> kullanmıyor (`docs/reports/03-render-envanteri.md` §2 son paragrafı). WebP ise
> `api/seller_media.py`'nin hedef formatı — yani WebP hattı kurulu. Buna karşılık
> `engine.to_webp` docstring'i (`engine.py:151-160`) Safari/iOS/Capacitor'da
> `canvas.toBlob('image/webp')` olmadığını not ediyor; bu **istemci encode'u** için
> geçerli, decode için değil. PNG yedeği yalnız `<picture>` fallback'i için, 4 rung ×
> ~1,5× bayt = kabul edilebilir. **Bu opsiyonel** → §13-K4.

> **`srcset` bugün yazılamaz.** `docs/reports/03-render-envanteri.md` §0-1: tüm
> storefront'ta `srcset` kullanımı **0** (`grep -rni "srcset" src | wc -l` → 0),
> `<picture>` **0**. Ve §0-5: backend tek boy üretiyor. Yani bu merdiven kurulmadan
> `srcset` yazmanın gösterecek ikinci dosyası yok. Sıra: merdiven → `srcset`.

---

## 6. SVG GÜVENLİK KURALI

### 6.1 Bugünkü durum — SVG üç kapıdan ikisinde yasak

| Kapı | Kod | Ne yapıyor |
|---|---|---|
| **Uzantı yasağı** | `tradehub_core/utils/security.py:27-44` `_DENIED_EXTENSIONS` içinde `".svg"` (`:29`) ve `".svgz"` (`:30`) | `File.before_insert` kancasında (`hooks.py:227-252` → `security.py:68` `reject_unsafe_files`) `:90-95` satırlarında `frappe.PermissionError` fırlatıyor. |
| **İçerik yasağı** | `tradehub_core/media/upload_policy.py:190` `_DANGEROUS_MARKERS` içinde `b"<svg"` | `upload_policy.py:225-231` `is_dangerous()` ilk 512 baytın **baştaki boşluk ve UTF-8 BOM'u atlanmış** hâline bakıyor (`:229`). Adı `.png`, içi `<svg onload=…>` olan dosyayı da yakalıyor (`:358` yorumu). |
| **`data:` URI** | **YASAK YOK** | `seed_demo_data.py:231-245` `_write_asset()` SVG'yi base64 data-URI'ye çevirip **doğrudan alan değerine** yazıyor: `:287` (satıcı logosu), `:3364` (`doc.logo = _demo_logo(...)`), `:4209` (marka logosu). `File` kaydı hiç açılmadığı için iki kapının **ikisi de devre dışı**. |

Yasak listesinin neden hâlâ liste olduğu `upload_policy.py:18-23`'te yazılı:
izin listesine çevirmek "bugün çalışan ve listede olmayan her akışı sessizce kırardı".
Bu gerekçe geçerli; bu standart onu **değiştirmiyor**.

Ayrıca: bundle'lanmış SVG'ler bu kapıların **kapsamında değil ve olmamalı**.
`src/assets/images/ta-logo.svg`, `public/icons/ui.svg` (463 düğüm), `public/vite.svg`
derleme zamanında Vite ile paketleniyor; `File` kaydı yok, kullanıcı girdisi değil.
Yasak yalnız **yüklenen** dosyaya uygulanır.

### 6.2 KURAL — "SVG kabul edilecekse önce sanitize gerekir"

Aşağıdaki 9 madde **tümü** karşılanmadan SVG kabul edilmez. Kısmi uygulama
(örneğin yalnız uzantı yasağını kaldırmak) sistemi bugünkünden **daha güvensiz**
hâle getirir, çünkü ikinci kapı hâlâ reddedeceği için kural test edilemez ve
"çalışmıyor" diye ikinci kapı da kaldırılır.

**SVG-1 — İki kapı birlikte, slot kapsamında açılır.**
`utils/security.py:27-44` ve `upload_policy.py:190` bağımsız iki gate. Yalnız birini
kaldırmak dosyayı hâlâ reddettirir. Açılış **global olmaz**: yalnız
`slot_key ∈ {seller.logo, brand.logo}` için. Bugün slot semantiği katmanı **yok**
(`docs/reports/00-upload-slot-envanteri.md` §1: "L3 — Slot semantiği (boyut / oran /
adet / rol): **Sistemde hiç yok**"). Yani **T-021'in politika JSON'ları ve onları
okuyan bir kayıt defteri ÖNCE kurulmalı**; SVG kabulü ondan sonra gelir. Bu, bu
görevin "KİLİT" olmasının teknik nedeni.

**SVG-2 — Sanitize SUNUCUDA, `File` kaydı yazılmadan ÖNCE.**
`docs/MEDYA-YUKLEME-SOZLESMESI.md`: "İstemcideki her kontrol hızlandırmak içindir.
Karar her zaman sunucunundur." Storefront'ta DOMPurify var
(`tradehubfront/CLAUDE.md` §2, `^3.3.2`) — o bir UX kolaylığı, kapı değil.
Sanitize `upload_policy.check()` içinde, `is_dangerous()` çağrısından **önce**
çalışmalı; çıktı bayt dizisi olarak yerine konur ve kaydedilen **sanitize edilmiş
sürümdür**, orijinal değil.

**SVG-3 — `is_dangerous()` bu slot için baypas edilir, ama YALNIZ sanitize geçtiyse.**
Sanitize'in çıktısı tanım gereği `<svg` ile başlar → `upload_policy.py:190` marker'ı
onu reddeder. Bu yüzden akış şu sırada olmalı:

```
1. slot_key logo slotu mu?                        değilse → bugünkü davranış (RET)
2. uzantı .svg mi?                                 .svgz ise → RET (SVG-6)
3. XML iyi biçimli mi (defusedxml)                 değilse → RET
4. DTD / ENTITY var mı                             varsa   → RET (SVG-5)
5. sanitize (allowlist) çalıştır                   
6. çıktı düğüm sayısı ≤ 256 mı                     değilse → RET
7. çıktı ≤ 32 KiB mi                               değilse → RET
8. `is_dangerous()` ATLA (yalnız burada)           
9. File kaydını SANITIZE EDİLMİŞ içerikle aç
```

Adım 8, kodda "sanitize edildi" bayrağına bağlı olmalı — uzantıya ya da slot adına
değil. Bayrak yoksa marker uygulanır.

**SVG-4 — Element / attribute allowlist. Yasak liste DEĞİL, izin listesi.**

İzinli elementler:
`svg`, `g`, `path`, `rect`, `circle`, `ellipse`, `line`, `polyline`, `polygon`,
`defs`, `linearGradient`, `radialGradient`, `stop`, `clipPath`, `mask`, `use`,
`title`, `desc`, `symbol`.

İzinli attribute'lar:
`viewBox`, `xmlns`, `width`, `height`, `d`, `x`, `y`, `x1`, `y1`, `x2`, `y2`,
`cx`, `cy`, `r`, `rx`, `ry`, `points`, `transform`, `fill`, `fill-rule`,
`fill-opacity`, `stroke`, `stroke-width`, `stroke-linecap`, `stroke-linejoin`,
`stroke-dasharray`, `stroke-opacity`, `opacity`, `offset`, `stop-color`,
`stop-opacity`, `gradientUnits`, `gradientTransform`, `clip-path`, `mask`,
`id`, `class`.

Bunun dışındaki **her element ve her attribute silinir** (dosya reddedilmez, temizlenir).

Özellikle silinenler ve nedeni:
- `script`, `handler` → doğrudan kod çalıştırma.
- `foreignObject` → içine HTML gömülebilir; HTML gömüldüğü an SVG bir HTML belgesi olur.
- `image` → dış kaynak isteği (SSRF / iz sürme); ayrıca base64 gömülü raster,
  "vektör logo" iddiasını yalanlar.
- `style` elementi ve `style` attribute'u → `background:url(...)`,
  `@import`, CSS ile dış istek. **Silinir**, çünkü stil bilgisi presentation
  attribute'larıyla (fill/stroke) zaten ifade edilebiliyor.
- `animate`, `animateTransform`, `animateMotion`, `set`, `discard` → logo animasyonlu
  olmaz (§3.6 GIF kararıyla tutarlı) ve SMIL geçmişte XSS vektörü.
- `on*` attribute'larının **tamamı** (`onload`, `onerror`, `onclick`, …) — allowlist
  yaklaşımı bunları otomatik siler; ayrıca isim-öneki kuralıyla ikinci kez taranır.
- `href` / `xlink:href`: **yalnız `#` ile başlayan** değer korunur (aynı dosya içi
  `<use>` referansı). `http:`, `https:`, `data:`, `javascript:`, protokol-relatif
  `//`, ve göreli yol → attribute silinir.
- `filter`, `feImage`, `fe*` → `feImage` dış kaynak çekebiliyor; filter zinciri
  logoda gerekmiyor ve render maliyeti öngörülemez.
- XML processing instruction, yorum, `<!DOCTYPE>`, `<!ENTITY>` → silinir/RET (SVG-5).

**SVG-5 — XXE ve entity genişletmesi: parse aşamasında RET.**
`<!DOCTYPE` veya `<!ENTITY` içeren dosya **sanitize edilmez, reddedilir**
(kod `logo_svg_dtd_forbidden`). Gerekçe: entity genişletmesi (billion laughs) sanitize
edilmeden **önce** bellek tüketir; temizlemeye çalışmak yerine reddetmek doğru sıradır.
Parser `defusedxml` olmalı — standart `xml.etree` varsayılan olarak entity çözer.
Not: `upload_policy.py:190` `_DANGEROUS_MARKERS` içinde `b"<?xml"` de var; XML
bildirimiyle başlayan meşru SVG'ler bu marker'a çarpar → SVG-3'teki baypas bunu da
kapsar, ama **yalnız DTD kontrolü geçtikten sonra**.

**SVG-6 — `.svgz` YASAK KALIR.**
`utils/security.py:30`. Gerekçe: gzip'i sanitize'den önce açmak yeni bir saldırı
yüzeyi (zip bomb) ekler ve kazanç ölçülemeyecek kadar küçük — 32 KiB tavanında
gzip'in tasarrufu ~20 KB, HTTP katmanı `Content-Encoding: gzip` ile aynı tasarrufu
zaten sağlıyor.

**SVG-7 — Servis kuralı: her zaman `<img src>`, asla inline.**
Storefront'ta satıcı/marka logosu **bugün de** yalnız `<img>` ile basılıyor —
16 + 3 render noktasının hepsi `<img src>` / `:src` (§3.1, §4.1 tabloları). İnline
`<svg>` olan tek yerler sabit kodlanmış ikonlar (`MessageList.ts:9` `TRADEHUB_AVATAR`,
`ManufacturersHero.ts:284` boş-durum ikonu). Bu ayrım **korunmalı**:
`<img>` ile yüklenen bir SVG, tarayıcı tarafından script çalıştırmaz — sanitize
kaçırsa bile ikinci savunma hattı. Kural: **kullanıcı SVG'si hiçbir koşulda DOM'a
inline edilmez** (ne `innerHTML`, ne Alpine `x-html`, ne Vue `v-html`).

**SVG-8 — Yanıt başlıkları.**
Kullanıcı SVG'si servis edilirken:
`Content-Type: image/svg+xml`, `X-Content-Type-Options: nosniff`,
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`.
Gerekçe: SVG-7 ile birlikte üçüncü savunma hattı. Bu başlıklar nginx katmanında;
`MEMORY.md`'de kayıtlı "prod'a ulaşmamış nginx sertleştirmesi" bulgusu bu adımın
**doğrulanması gereken** bir yer olduğunu gösteriyor (§12-D6).

**SVG-9 — Boyut tavanları (sanitize ÇIKTISI üzerinde ölçülür).**

| Tavan | Değer | Dayanak |
|---|---:|---|
| Bayt | **32 768 B** | `ta-logo.svg` = 12 379 B (gerçek kelime markası) × 2,65. Karşı örnek: `svgviewer-output.svg` 137 695 B, `ta-shield-pattern.svg` 105 516 B → ikisi de reddedilir. |
| Düğüm (element) sayısı | **256** | Ölçüm (regex `<([a-zA-Z][\w:-]*)`): `amex.svg` **2**, `vite.svg` **11**, `ta-logo.svg` **20**, `O1CN…tps-222-221.svg` **32**, `svgviewer-output.svg` **75** (otomatik trace), `ui.svg` **463** (çok-ikonlu sprite). 256 = gerçek kelime markasının 12,8 katı, otomatik-trace örneğinin 3,4 katı, sprite'ın altında. |
| `viewBox` | **zorunlu**, `width`/`height` opsiyonel | `viewBox` yoksa `object-contain` ölçekleme davranışı tarayıcılar arasında ayrışır. Ölçülen 8 SVG'nin 8'inde de `viewBox` var. |

> **Düğüm tavanı ikincil savunmadır, bayt tavanı birincil.** Ölçüm bunu kanıtlıyor:
> `svgviewer-output.svg` **yalnız 75 düğüm** ama **137 695 bayt** — tüm ağırlık `path`
> `d` verisinde. Düğüm sayısına bakan bir kural bu dosyayı geçirirdi; bayt tavanı
> reddediyor. Düğüm tavanı farklı bir riski kapsıyor: `<use>` zinciri ve derin `g`
> ağacı ile render maliyeti şişirmek.

**SVG-10 — Geriye dönük görev: mevcut `data:` URI SVG'leri.**
`seed_demo_data.py` yoluyla DB'ye yazılmış `data:image/svg+xml;base64,…` değerleri
**hiçbir kapıdan geçmemiş**. Bunlar demo verisi olduğu için bugün zararsız (içeriği
kendimiz üretiyoruz, `:277-287`) ama:
(a) alan değeri `text` (64 KB, `_write_asset` docstring `:237`) — 32 KiB tavanı
    yükleme yoluna konsa bile bu yolu bağlamaz;
(b) `seo/og_image.py:59-69` `data:` URI'yi çözemiyor → o satıcıların og:image'i
    sessizce site varsayılanına düşüyor;
(c) `media/usage.py` envanteri `File` kaydı olmadığı için bu logoları göremiyor.
**Kural:** logo alanına `data:` URI yazmak, üretimde **yasaklanmalı**; slot politikası
`allow_data_uri: false` taşıyor. Demo seed'i ayrı bir bayrakla muaf tutulur
(`upload_policy.py`'nin `_SYSTEM_FLAGS` deseni, `utils/security.py:98-109`).

---

## 7. Doğrulama kodları — logo slotuna özgü

`upload_policy.py:106-140` deseniyle uyumlu; `retryable` her zaman `False`
(aynı dosya aynı sonucu verir).

| Kod | Tetik | Mesaj (kullanıcıya) |
|---|---|---|
| `logo_too_small` | kısa kenar < 256 px | "Logo en az 256×256 piksel olmalı. Yüklediğiniz: {w}×{h}." |
| `logo_low_resolution` | 256 ≤ kısa kenar < 512 (satıcı) / < 384 (marka) | **Uyarı, ret değil.** "Logonuz yüksek çözünürlüklü ekranlarda bulanık görünebilir. Önerilen: {512\|384}×{512\|384}." |
| `logo_aspect_out_of_band` | oran 1:2 … 2:1 dışında | "Logo oranı 1:2 ile 2:1 arasında olmalı. Yüklediğiniz: {w}:{h}." |
| `logo_format_no_alpha` | JPEG, veya alfa kanalı olmayan PNG/WebP | "Logo saydam zeminli olmalı (PNG veya WebP, alfa kanallı). JPEG kabul edilmiyor." |
| `logo_format_animated` | `is_animated` | "Logo animasyonlu olamaz." |
| `logo_format_not_supported` | TIFF / BMP / HEIC / GIF | "Bu biçim logo için kabul edilmiyor. PNG, WebP veya SVG kullanın." |
| `logo_too_large` | raster > 1 MiB (satıcı) / 576 KiB (marka), SVG > 32 KiB | "Logo dosyası çok büyük ({n} MB). Üst sınır {m} MB." |
| `logo_svg_dtd_forbidden` | `<!DOCTYPE` / `<!ENTITY` | "SVG dosyası desteklenmeyen bir yapı içeriyor." |
| `logo_svg_too_complex` | sanitize sonrası düğüm > 256 | "SVG çok karmaşık. Logo olarak tasarlanmış, sadeleştirilmiş bir dosya yükleyin." |
| `logo_svg_empty_after_sanitize` | sanitize sonrası çizim elementi 0 | "SVG dosyasında güvenli olmayan içerik temizlendikten sonra çizilecek bir şey kalmadı." |
| `logo_data_uri_forbidden` | alan değeri `data:` ile başlıyor | "Logo bir dosya olarak yüklenmeli." |
| `logo_derivative_oversize` | türev bayt tavanını aştı | **Uyarı, ret değil.** Envantere düşer. |

Bu kodların **hiçbiri bugün kodda yok**. `upload_policy.py:106-140` içinde 14 kod var
ve hiçbiri slot-farkındalıklı değil. Bu tablo Faz 2'nin uygulama listesidir.

---

## 8. Politika JSON'ları — sözleşme

**Dosyalar:**
- `tradehub_core/media/pipeline/policy/slots/seller-logo.json`
- `tradehub_core/media/pipeline/policy/slots/brand-logo.json`

`tradehub_core/media/pipeline/` altında bu görevin başında hiçbir dosya yoktu
(`find media_engine -type f` → boş). Yani bu JSON'ları **okuyan kod henüz yazılmadı**.

**Şema seçimi.** Bu görev sürerken kardeş görevler aynı dizine 7 politika daha yazdı
ve ortaya **4 farklı şema** çıktı:

| Şema | Dosyalar | Anahtar deseni |
|---|---|---|
| **Çoğunluk (4 dosya)** | `product-image.json`, `product-video.json`, `company-cover-image.json`, `category-banner.json` | `$schema` / `schema_version` / `status` / `slot_key` / `title` / `roles` / `bound_to` / `accept` / `require` / `master` / `quality` / `profiles` / `content_rules` / `on_violation` / `messages` / `sources` / `open_questions` / `notes` |
| Türkçe anahtarlar | `document-attachment.json`, `user-avatar.json` | `$schema_surum` / `slot` / `gorev` / `kabul` / `geometri` / `profiller` … |
| Ayrı yapı | `company-cover-video.json` | `_meta` / `identity` / `render_box` / `modes` / `renditions` … |

**Bu görevin iki JSON'u çoğunluk şemasına hizalandı** — kayıt defteri yazılırken tek
bir okuyucu yeter. Logo'ya özgü bloklar (`svg_policy`, `dark_theme`, `css_safe_area`,
`render_points`, `production_verification_required`) çoğunluk şemasının üstüne
**ek alan** olarak bindi; ortak alanların hiçbirinin adı ya da anlamı değiştirilmedi.

> Şema çeşitliliği bir **teslim kusuru**: kayıt defteri yazılmadan önce 9 dosya tek
> şemaya indirilmeli. `notes[]` dizisinin son maddesi bunu her iki dosyada da not ediyor.

**Doğrulama izi.** Her sayısal alanın dayanağı (dosya:satır veya ölçüm yöntemi)
JSON'un içinde taşınıyor — belgeden ayrı düşmeye karşı sigorta:
- `sources` bloğu — 20 (satıcı) / 19 (marka) alan için dayanak.
- `profiles[].derived_from` — her rung'ın hangi kutu × DPR hesabından doğduğu.
- `profiles[].byte_reference` — her bayt tavanının ölçülen referans dosyası.
- `content_rules[].source` — her kuralın kod dayanağı.
- `render_points[]` — 17 (satıcı) / 3 (marka) render noktası, dosya:satır + kutu + fit + plaka.

**Ortak sabitler (iki dosya birbirini tutuyor, betikle doğrulandı):**
`profiles` = `[w64, w128, w256, w512, og1200x630]`;
`max_bytes` = `{64: 4096, 128: 8192, 256: 16384, 512: 40960, og: 122880}`;
`content_rules` 9 kural; `messages.tr` 12 mesaj; `open_questions` 7; `production_verification_required` 8.

**İki dosya arasındaki TÜM farklar** (bilinçli, gerekçesi JSON içinde):

| Alan | `seller.logo` | `brand.logo` | Neden |
|---|---|---|---|
| `require.recommended_edge` | 512 | **384** | Talep 480 vs 312 (§3.2 / §4.2) |
| `require.low_resolution_warn_below` | 512 | **384** | Aynı |
| `accept.max_bytes` | 1 048 576 | **589 824** | 512²×4 vs 384²×4 |
| `roles` | `["seller","admin"]` | **`["admin"]`** | `Brand.logo`'yu yalnız admin yazıyor |
| `dark_theme.violating_render` | S1 (`seller-shop.ts:124`) | **`null`** | Markada plakasız kutu yok |
| `render_points` | 17 | **3** | Ölçüm |
| `profiles[w512].conditional` | yok | **var** | 384 master'da 512 rung'u doğmaz |
| `bound_to` | 2 kayıt (+ `Storefront Layout.sections` JSON'u) | 1 kayıt | Ölçüm |

---

## 9. Henüz olmayan render noktaları — ileriye dönük kural

Görev tanımı e-posta şablonu, PDF fatura ve mobil uygulamayı sayıyor. Ölçüm sonucu:

| Nokta | Durum | Kanıt | Kural (uygulandığında) |
|---|---|---|---|
| **E-posta şablonu** | Logo **yok** | `templates/emails/*.html` (5 dosya), her birinde `grep -ciE 'img \|logo'` → **0** | E-posta istemcileri (Outlook) SVG ve WebP **render etmez**. Kural: **PNG**, `261×96` (§2.2 raster yedeği), mutlak `https://` URL, `width`/`height` attribute zorunlu, `alt="iStoc"`. Koyu tema: e-postada `prefers-color-scheme` desteği güvenilmez → **beyaz varyant kullanılmaz**, logo her zaman açık zemin `<td bgcolor="#ffffff">` içine konur. |
| **PDF fatura / proforma** | Kod **yok** | `grep -rlniI "print_format\|get_pdf\|proforma"` → sonuç yok | wkhtmltopdf/WeasyPrint SVG'yi kısmen render eder. Kural: **PNG 261×96 @ 300 DPI eşdeğeri** — 300 DPI'da 22 mm genişlik için 261 px yeterli (261 px / 300 dpi = 0,87 inç = 22,1 mm). Satıcı logosu faturada varsa: **512 rung, PNG**, alfa düşürülmeden. |
| **Mobil uygulama (Capacitor)** | Yapılandırma var, ikon **repo'da yok** | `capacitor.config.ts:22` `appId: 'com.istoc.app'`; `ios/` ve `android/` dizinleri repoda **yok** (`ls tradehubfront` çıktısı) | iOS `AppIcon` 1024×1024 PNG **alfasız** (App Store zorunluluğu), Android adaptive icon 108×108 dp foreground + background. Bu, web logosundan **ayrı bir varlık ailesidir** — `public/icons/icon-512.png` (512×512, RGBA) yetmez. |
| **Favicon** | Kısmen var, eksik bildirilmiş | `public/images/istoc-favicon-{32,48,96}.png` var; `index.html:5` yalnız 32'yi bildiriyor; `apple-touch-icon.png` (180×180) var ama `index.html`'de `<link rel="apple-touch-icon">` **yok** | 32 + 48 + 96 PNG bildirilir; 180 apple-touch bildirilir. Frappe tarafı bunu **zaten doğru yapıyor** (`seo/templates/seo_head.html:3-5`, üç boyut) — storefront `index.html` ondan geride. |
| **og:image** | Motor var, varsayılan bağlanmamış | `seo/og_image.py` (135 satır) + `seo/templates/seo_head.html:17,25`; `public/images/og-default.jpg` (1200×630, 47 649 B) **hiçbir yerden referans almıyor** | §3.10. |
| **Sohbet / mesaj avatarı** | Satıcı logosu **kullanılmıyor** | `alpine/messages.ts:97-100` `avatarFor()` → `https://ui-avatars.com/api/?...` (üçüncü parti, PNG) | Logo standardı buraya **bağlanmalı**: 64 rung, `object-contain`, açık plaka. Üçüncü parti çağrısı ayrı bir sorun (§11-F7). |

---

## 10. Uygulama sırası (bağımlılık zinciri)

```
T-021 (bu belge onayı)
   │
   ├─ 1. Slot kayıt defteri: tradehub_core/media/pipeline/policy/slots/*.json okuyan katman
   │       → docs/reports/00-upload-slot-envanteri.md §1 "L3 yok" bulgusunu kapatır
   │
   ├─ 2. Logo doğrulama kodları (§7) → upload_policy.py'ye slot-farkındalık
   │       → 400×400 tavsiye metni (DocTypeFormView.vue:448) ile 512 kararı hizalanır
   │
   ├─ 3. Oran normalizasyonu (1:1 saydam letterbox)
   │       → 5 object-cover kırpma noktasını kod değiştirmeden kapatır
   │
   ├─ 4. Türev merdiveni (64/128/256/512, kayıpsız WebP)
   │       → engine.to_webp'e lossless yolu (bugün quality=80 sabit)
   │
   ├─ 5. og:image logo yolu düzeltmesi (contain+pad, beyaz zemin)
   │       → seo/og_image.py:34,45-49,51
   │
   ├─ 6. srcset / <picture> (storefront + panel)   ← 4 bitmeden anlamsız
   │
   └─ 7. SVG kabulü (§6, SVG-1…SVG-10)             ← 1 bitmeden yapılamaz
```

Adım 7'nin en sonda olması kasıtlı: SVG kabulü **slot kapsamlı** olmak zorunda
(SVG-1) ve slot kapsamı adım 1'de doğuyor.

---

## 11. Bulgular — bu standardın açığa çıkardığı, düzeltilmeyen sorunlar

Bu görev **mevcut kod dosyalarını değiştirmez.** Aşağıdakiler kayıt altına alınıyor.

| # | Bulgu | Kanıt | Etki |
|---|---|---|---|
| **F1** | Platform logosu 87×32 tek dosya; 19 render varyantının 15'i DPR 2'de yetersiz | §2.1 tablosu; `file public/images/istoc-logo.png` | Retina ekranda başlık logosu bulanık — sitenin ilk gördüğü şey |
| **F2** | Header'da koyu tema logo varyantı bağlanmamış | `TopBar.ts:177` (koyu mürekkep logo) + `TopBar.ts:875` `dark:bg-gray-900`; varyant `public/images/istoc-logo-beyaz.png` **mevcut** | Koyu temada başlık logosu görünmüyor |
| **F3** | `seller-shop.ts:124` logo kutusu alt plaka **koymuyor**, arka planı satıcının yüklediği `header_bg_image` | `seller-shop.ts:118-119` + `:124-126` | Koyu header görselinde koyu logo kayboluyor. 16 noktanın 11'i plaka koyuyor; bu 1'i koymuyor |
| **F4** | 5 render noktası logoyu `object-cover` ile **kırpıyor** | `seller-shop.ts:129`, `seller-dashboard.ts:66`, `seller-dashboard.ts:158`, `StorefrontEdit.vue:79`, `StorefrontLayoutEditor.vue:247` | Kare olmayan logo merkezden kesiliyor; aynı dosya 9 noktada kesilmiyor → tutarsız görünüm |
| **F5** | `seller_media` yolundan geçen logo **kayıplı** WebP q80'e çevriliyor | `api/seller_media.py:292` → `engine.py:148` (`quality: int = 80`) → `:180` | Keskin logo kenarında halkalanma. Aynı dosya `runner.py:229` yolundan geçse PNG kalır ve kayıpsız olur → iki yol ayrışıyor |
| **F6** | Marka logosu arama önerisinde **gönderiliyor, basılmıyor** | `api/search.py:81,93` (`"logo": r.logo or ""`), `api/tailored.py:721`; storefront `<img>` eşleşmesi yok | Boşa network + boşa alan |
| **F7** | Sohbet avatarı satıcı logosu değil, **üçüncü parti** `ui-avatars.com` | `alpine/messages.ts:97-100` | Her sohbet listesi harici servise istek atıyor (iz sürme, CSP, çevrimdışı kırılma); satıcının kendi logosu elde varken kullanılmıyor |
| **F8** | `icons/*.webp` dosyalarının 7'si de gerçekte **PNG** | `file icons/icon-512.webp` → "PNG image data"; baytları `public/icons/*.png` ile özdeş (27128 = 27128) | Yanlış uzantı → yanlış `Content-Type` riski. Ancak yayınlanan manifest bunları kullanmıyor (`dist/manifest.webmanifest` doğrulandı) |
| **F9** | `public/manifest.webmanifest` **ölü dosya** ve içeriği hatalı | Dosyada `"src": "../icons/icon-48.webp"` + `"type": "image/png"` (uzantı/MIME çelişkisi); VitePWA kendi manifest'ini üretiyor (`vite.config.ts:398-421`), `index.html`'de elle `<link rel="manifest">` yok | Kafa karışıklığı; bir sonraki geliştirici yanlış dosyayı düzeltir |
| **F10** | Admin panel favicon **404** | `admin-panel/frontend/index.html:18` `href="/favicon.svg"`; `find . -name "favicon*" -not -path "./node_modules/*"` → boş; `public/` dizini yok | Sekmede varsayılan ikon |
| **F11** | Storefront `index.html` og:image bildirmiyor | `index.html:8-10` og:title/description/type var, og:image yok; `og-default.jpg` (1200×630) var ama referanssız | Ana sayfa paylaşımında görsel yok |
| **F12** | `index.html` favicon'un 48 ve 96 varyantlarını + apple-touch'ı bildirmiyor | `index.html:5` yalnız 32; dosyalar var; `seo/templates/seo_head.html:3-5` üçünü de bildiriyor | Frappe-render sayfa storefront'tan iyi |
| **F13** | og:image logoyu kırpıyor + alfayı düşürüyor + JPEG'liyor | `seo/og_image.py:34`, `:45-49`, `:51`; kaynak bağlanması `seo/meta_builder.py:261,282` | 1:1 logo yüksekliğinin **%47,5'i** kesiliyor; saydam logo çöp zemin alıyor |
| **F14** | SVG logolar `data:` URI olarak DB'de, **hiçbir kapıdan geçmemiş** | `seed_demo_data.py:231-245`, `:287`, `:3364`, `:4209` | Bugün demo verisi (kendi ürettiğimiz içerik) — ama kanal açık ve envanter/og:image/usage bu logoları görmüyor |
| **F15** | 87×32 logo dosyası repoda **5 kopya** | `stat -f %z`: `tradehubfront/public/images/istoc-logo.png` 2547, `tradehubfront/src/assets/images/istoc-logo.png` 2547, `admin/src/assets/media/istoc-logo.png` 2547 (+2 beyaz varyant, 17255 ×2) | Logo yenilenince 5 yerde güncellenmesi gerekecek; biri atlanır |
| **F16** | `menu-header-bg.png` **1,7 MB** ve 1024×1024 | `stat -f %z admin/src/assets/media/menu-header-bg.png` → 1 701 884; `file` → 1024×1024 RGB | Logo değil ama aynı klasörde ve panel bundle'ına giriyor. Kapsam dışı, not düşüldü |
| **F17** | Panel tavsiye metni ile bu standart çelişiyor | `DocTypeFormView.vue:448` `recommendedSize: '400×400'`; bu standart 512×512 diyor | 400×400 master 512 rung'unu **doğuramaz** (`engine.py:117` upscale yapmaz) → merdivenin üst basamağı ölü kalır |
| **F18** | Banner dropzone oranı ile tavsiyesi çelişiyor (logo değil, komşu slot) | `ProfileImageDropzone.vue:135` `rectangle` → `w-full sm:w-64 h-36` = 256×144 = **16:9**; `DocTypeFormView.vue:448` tavsiye `1600×400` = **4:1** | `docs/reports/00-upload-slot-envanteri.md` §7 de not etmiş. Logo standardının kapsamı dışında ama aynı bileşen |

---

## 12. ÜRETİMDE DOĞRULANMALI

Aşağıdakiler **ölçülmedi.** Docker kapalı; üretim veritabanına ve canlı siteye erişim
yok. Her madde çalıştırılacak tam komutu içerir.

### D1 — Gerçek logo dosyalarının piksel dağılımı

Bu standardın 256 / 384 / 512 eşikleri **kaynak koddan türetildi**, gerçek logo
dosyalarından değil. Kaç mevcut logonun eşiğin altında kaldığı bilinmiyor.

```bash
# Frappe bench konsolunda (üretim ya da üretim kopyası)
bench --site istoc.com console
```
```python
import os
from PIL import Image
import frappe

kok = frappe.get_site_path("public", "files")
sayac = {"lt256": 0, "256_383": 0, "384_511": 0, "gte512": 0, "data_uri": 0, "yok": 0}
oranlar = []
for dt, alan in (("Admin Seller Profile", "logo"), ("Brand", "logo")):
    for ad, url in frappe.get_all(dt, filters={alan: ["is", "set"]},
                                  fields=["name", alan], as_list=True):
        if not url:
            sayac["yok"] += 1; continue
        if url.startswith("data:"):
            sayac["data_uri"] += 1; continue
        p = os.path.join(kok, url[len("/files/"):]) if url.startswith("/files/") else ""
        if not p or not os.path.exists(p):
            sayac["yok"] += 1; continue
        try:
            with Image.open(p) as im:
                w, h = im.size
                kisa = min(w, h)
                oranlar.append((dt, ad, w, h, round(w / h, 3), im.mode,
                                os.path.getsize(p)))
                if kisa < 256: sayac["lt256"] += 1
                elif kisa < 384: sayac["256_383"] += 1
                elif kisa < 512: sayac["384_511"] += 1
                else: sayac["gte512"] += 1
        except Exception:
            sayac["yok"] += 1
print(sayac)
# Oran bandı ihlali (1:2 … 2:1 dışı)
print([r for r in oranlar if r[4] < 0.5 or r[4] > 2.0])
# Alfa kanalı olmayanlar (JPEG / RGB PNG)
print([r for r in oranlar if r[5] not in ("RGBA", "LA") ])
# Bayt tavanı (1 MiB) aşanlar
print([r for r in oranlar if r[6] > 1048576])
```

**Bu çıktı olmadan §3.4'teki sert ret eşiği (256) üretime alınamaz** — kaç satıcının
logosunu anında geçersiz kılacağı bilinmiyor. Eşik, ihlal oranı %5'i geçiyorsa
geriye dönük **uyarı** moduna alınmalı.

### D2 — `data:` URI logoların gerçek sayısı

```python
import frappe
for dt in ("Admin Seller Profile", "Brand"):
    n = frappe.db.count(dt, {"logo": ["like", "data:%"]})
    print(dt, "data-uri logo:", n)
    # 64 KB `text` sütun sınırına dayananlar
    print(frappe.db.sql(f"""
        SELECT name, LENGTH(logo) AS bayt FROM `tab{dt}`
        WHERE logo LIKE 'data:%' ORDER BY bayt DESC LIMIT 10
    """, as_dict=True))
```
Beklenti: bunlar `seed_demo_data.py` çıktısı olduğu için **üretimde 0 olmalı**.
0 değilse §6 SVG-10 acil.

### D3 — Tarayıcıda hesaplanmış (computed) logo kutusu

Bu belgedeki tüm CSS kutu ölçüleri **Tailwind sınıfından türetildi**, tarayıcıda
ölçülmedi. Doğrulama (canlı site, DevTools konsolu):

```js
// Her sayfada çalıştır: /, /magaza/<kod>, /urun/<slug>, /marka/<slug>,
// /uretici, /favoriler, /sepet, /odeme, /yardim
[...document.querySelectorAll('img')]
  .filter(i => /logo/i.test(i.className + i.alt + i.src) ||
               /logo/i.test(i.closest('[class*=logo]')?.className || ''))
  .map(i => {
    const r = i.getBoundingClientRect();
    return {
      src: i.currentSrc.split('/').pop(),
      cssW: +r.width.toFixed(1), cssH: +r.height.toFixed(1),
      natW: i.naturalWidth, natH: i.naturalHeight,
      dpr: devicePixelRatio,
      // >1 ise bulanık
      eksik: +(r.width * devicePixelRatio / i.naturalWidth).toFixed(2),
      fit: getComputedStyle(i).objectFit
    };
  });
```
`eksik > 1` olan her satır §2.1 / §3.2 tablolarının doğrulanmış hâlidir.
DPR 1, 2 ve 3 için ayrı ayrı (DevTools → Device Toolbar → DPR seçici).

### D4 — Türev baytlarının gerçek ölçümü

§3.7'deki tavanlar `public/icons/*.png` referanslarından **türetildi**; gerçek satıcı
logolarından kayıpsız WebP üretilmedi.

```bash
# Üretim kopyasında, gerçek logo dosyaları üzerinde
cd /tmp && mkdir -p logo-bench && cd logo-bench
# D1'in listelediği dosyalardan 50 tanesini kopyala, sonra:
python3 - <<'EOF'
import glob, io, os
from PIL import Image
for p in sorted(glob.glob("*.png")) + sorted(glob.glob("*.webp")):
    with Image.open(p) as im:
        if im.mode not in ("RGB", "RGBA"):
            im = im.convert("RGBA")
        for rung in (64, 128, 256, 512):
            if max(im.size) < rung:
                continue
            k = im.copy(); k.thumbnail((rung, rung))
            b = io.BytesIO(); k.save(b, "WEBP", lossless=True, method=6)
            b2 = io.BytesIO(); k.save(b2, "PNG", optimize=True)
            print(f"{p:40} {rung:>4} webp-lossless={len(b.getvalue()):>7} "
                  f"png={len(b2.getvalue()):>7}")
EOF
```
Bu tablo, §3.7'deki 4 / 8 / 16 / 40 KiB tavanlarını **onaylar ya da düzeltir**.
Kayıpsız WebP, düz renkli logolarda PNG'den küçük çıkmalı; **çıkmıyorsa** format
önceliğinde PNG öne alınmalı.

### D5 — og:image kırpma hasarının görsel doğrulaması

```bash
bench --site istoc.com console
```
```python
from tradehub_core.seo.og_image import ensure_og_image
import frappe
kayit = frappe.db.get_value("Admin Seller Profile",
    {"logo": ["is", "set"]}, ["name", "logo"], as_dict=True)
print(kayit)
print(ensure_og_image({"logo": kayit.logo}, source_field="logo"))
# Dönen /files/og_cache/<hash>.jpg dosyasını indir ve GÖRSEL OLARAK bak:
# - logonun üstü/altı kesilmiş mi (§3.10 hesabı: %47,5 beklenir)
# - saydam alan siyah mı
```

### D6 — SVG servis başlıkları

`MEMORY.md` "prod'a ulaşmamış nginx sertleştirmesi" bulgusu taşıyor. §6 SVG-8
uygulanmadan SVG kabulü açılamaz.

```bash
# Herhangi bir mevcut public görselde başlıkları kontrol et
curl -sSI https://istoc.com/files/<bir-logo>.png | grep -iE \
  "content-type|x-content-type-options|content-security-policy|cache-control"
# SVG için (SVG kabulü açıldıktan sonra)
curl -sSI https://istoc.com/files/<bir-logo>.svg | grep -iE \
  "content-type|x-content-type-options|content-security-policy"
```
Beklenen: `Content-Type: image/svg+xml`, `X-Content-Type-Options: nosniff`,
`Content-Security-Policy: default-src 'none'; style-src 'unsafe-inline'; sandbox`.

### D7 — Depolama etkisi

4 rung × 2 format (WebP + PNG) = 8 ek dosya / logo. Gerçek satıcı ve marka sayısı
bilinmiyor.

```python
import frappe
print("Logolu satıcı:", frappe.db.count("Admin Seller Profile", {"logo": ["is","set"]}))
print("Logolu marka:", frappe.db.count("Brand", {"logo": ["is","set"]}))
```
Tahmin formülü (§3.7 tavanlarıyla, en kötü durum):
`(4 + 8 + 16 + 40) KiB × 2 format = 136 KiB / logo` + og:image 120 KiB = **256 KiB / logo**.
Yalnız WebP (PNG yedeği olmadan): **68 + 120 = 188 KiB / logo**.
`N` = yukarıdaki iki sayının toplamı. `docs/reports/06-depolama-maliyet.md` ile
çapraz kontrol edilmeli.

### D8 — Koyu tema gerçekten kullanılıyor mu

§3.9 kararı ("koyu tema varyantı gerekmiyor") plakaların `dark:` varyantı
taşımadığı **ölçümüne** dayanıyor. Ama koyu temanın kullanım oranı bilinmiyor.

```js
// Canlı sitede, koyu tema açıkken
document.documentElement.classList.contains('dark')  // storefront: style.css:19
localStorage.getItem('th-theme')                      // admin: index.html:8
```
Ve görsel kontrol: `/magaza/<kod>` sayfasını koyu temada açıp S1
(`seller-shop.ts:124`, 140×140, plakasız) noktasının **ekran görüntüsünü** al.
Bu, F3 bulgusunun ciddiyetini belirler.

---

## 13. KARARLAR — 2'si ölçümle kapandı, 4'ü onay bekliyor

> **GÜNCELLEME — 2026-08-18.** Bu bölümdeki 6 karardan ikisi **sayısal bir tetik**
> taşıyordu ("şu oran şu eşiği geçerse B"). Docker açıldı, tetikler
> `docs/reports/08-canli-olcum.md` §2 ile çalıştırıldı. **K1 ve K2 artık onay
> bekleyen değil, ölçümle çözülmüş kararlardır.** Hiçbir seçenek tablosu silinmedi;
> her karara ölçüm sonucu ve yürürlükteki hüküm eklendi. Belgenin kendi kuralı
> sonucu belirledi — bu, tetikleri baştan yazmanın karşılığıdır.

### 13.0 Karar durumu — özet tablo

| # | Karar | Tetik (önceden yazılıydı) | Ölçüm (2026-08-18) | Durum | Yürürlükteki sonuç |
|---|---|---|---|---|---|
| **K1** | JPEG logo: RET mi, uyarıyla kabul mü? | JPEG payı **> %10** ⇒ B | **9/18 = %50** | ✅ **ÖLÇÜMLE ÇÖZÜLDÜ** | **B** — kabul + uyarı + geçiş penceresi. Öneri A (ret) **düştü** |
| **K2** | Oran bandı 1:2…2:1 mi, 1:4…4:1 mi? | Band dışı **> %20** ⇒ B | **2/18 = %11** | ✅ **ÖLÇÜMLE ÇÖZÜLDÜ** | **A onaylandı** — band **1:2…2:1** aynen kaldı |
| **K3** | Merdiven 4 rung mu, 5 mi (+384)? | 512 rung'u **40 KiB'e yaklaşırsa** ⇒ B | **p50 27.162 B · max 109.172 B · 5/18 tavanı AŞIYOR** | ✅ **ÖLÇÜMLE ÇÖZÜLDÜ** | **B** — 5 rung (+384). Varsayılan A **düştü** |
| **K4** | PNG yedeği üretilsin mi? | sayısal tetik yok | ölçülmedi | ⏳ **AÇIK** | Varsayılan **A** (yalnız kayıpsız WebP) |
| **K5** | Panelin 400×400 tavsiyesi ne olacak? | sayısal tetik yok (iş kararı) | ölçülmedi | ⏳ **AÇIK** | Varsayılan **A** (512×512), ayrı görev |
| **K6** | 256 px sert reddi geriye dönük mü? | sayısal tetik yok (ticari karar) | **kısmen**: kısa kenar < 256 = **1/18 = %5,5** | ⏳ **AÇIK** | Varsayılan **A** (yalnız yeni yüklemeler) |

**Ölçüm kümesi ve sınırları.** `Admin Seller Profile.logo` (27) + `Brand.logo` (11)
= **38 referans**; bunların **18'i diskte gerçek dosya**, 18'i DB'ye gömülü
`data:` URI (hepsi demo seed), 2'si diskte yok. Yukarıdaki yüzdeler bu **18
dosyalık küme** üzerinden. Kaynak: `docs/reports/08-canli-olcum.md` §2.

- **ÖLÇÜLEMEDİ — slot bazında ayrıştırma.** Aynı rapor §4, "slot bazında dağılım"ı
  kapatılmayanlar arasında sayıyor. K1 ve K2 sonucu `seller.logo` ve `brand.logo`
  için **ayrı ayrı değil, birleşik küme üzerinden** verildi; iki slot tek kod yolu
  paylaştığı için (`seller-logo.json` `notes`) ayrı yaptırım zaten istenmiyordu.
- **ÖLÇÜLEMEDİ — üretim verisi.** Ölçüm yerel stack'te (`istoc.localhost`) yapıldı.
  Üretimde dosya sayıları farklıdır; §12-D1 betiği üretimde de koşulmalıdır.
- **n = 18 küçük bir kümedir.** %50 ve %11 oranları bu küme için kesindir, üretim
  için tahmindir. Yine de tetikler bu belgede **eşiklerle** yazıldığı için karar
  mekanik olarak verilebilir: %50, %10'un beş katıdır — küme büyüklüğü bu farkı
  tersine çevirmez.

Kalan **4 kararı** (K3–K6) tek başıma veremem: her birinde iki seçenek de teknik
olarak savunulabilir ve seçim iş kuralına bağlı. Her birinde önerim ve gerekçesi var.

### K1 — JPEG logo: RET mi, uyarıyla kabul mü? — ✅ ÖLÇÜMLE ÇÖZÜLDÜ (2026-08-18)

**SONUÇ: B — kabul + uyarı + geçiş penceresi. Öneri A (ret) ölçümle DÜŞTÜ.**

Aşağıdaki seçenek tablosu kararın verildiği andaki hâliyle **silinmeden** duruyor;
altında ölçüm ve yürürlükteki hüküm var.

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — RET, kod `logo_format_no_alpha` | Standart net. 16 render noktasının 11'i logonun altına plaka koyuyor (`bg-gray-50` ×6, `bg-white` ×2, `bg-gray-100` ×2, `bg-white/10` ×1) — opak beyaz JPEG bu plakaların üzerinde görünür dikdörtgen bırakır. S1 (`seller-shop.ts:124`) hiç plaka koymuyor, orada JPEG satıcının kendi header görseline yamalı bir kutu olarak biner. |
| B — Kabul + `logo_opaque_warning` | Kimse engellenmez. Ama uyarı okunmaz; 11 noktada görsel bozukluk kalıcı olur ve "logo standardı var" iddiası boşa düşer. |
| C — Kabul + sunucuda otomatik arka plan kaldırma | Otomatik matting logoda güvenilmez (gradyanlı/gölgeli logolarda halka bırakır). Ölçemediğim bir kalite riski; önermiyorum. |

**Önerim A idi. ÖLÇÜM ONU DÜŞÜRDÜ.**

Tetik bu belgede **önceden** yazılıydı: *"Bu oran %10'u geçerse karar B'ye çevrilmeli
ve bir geçiş penceresi tanımlanmalı."* `docs/reports/08-canli-olcum.md` §2.1
(2026-08-18) tetiği çalıştırdı:

| Ölçüt | Değer | Tetik | Sonuç |
|---|---:|---|---|
| **JPEG payı** | **9/18 = %50** | > %10 ⇒ B | **B** |
| Alfa kanallı (RGBA) | 4/18 = %22 | — | Alfa **azınlıkta** |

%50, tetiğin **beş katıdır**. Öneri A uygulansaydı mevcut satıcı ve marka
logolarının **yarısı** standardın yürürlüğe girdiği gün geçersiz olurdu. Bu ticari
olarak kabul edilemez.

**Yürürlükteki karar — B. Politikada karşılığı** (`seller-logo.json`, `brand-logo.json`):

| Ne değişti | Eski | Yeni |
|---|---|---|
| `accept.mime` | `image/png`, `image/webp` | + **`image/jpeg`** |
| `accept.extensions` | `.png`, `.webp` | + **`.jpg`, `.jpeg`** |
| `accept.rejected_extensions` | `.jpg`, `.jpeg` içeriyordu | **`.jpg`/`.jpeg` çıkarıldı** |
| `accept.format_priority` | `svg` › `png_with_alpha` › `webp_lossless` | … › **`jpeg_opaque`** (en son sıra) |
| `require.alpha_channel` | `required` | **`optional`** |
| `content_rules[no_alpha_channel].action` | `reject` | **`warn`** |
| `messages.tr.format_no_alpha` | ret metni | **uyarı metni** ("Logonuz kaydedildi — bu bir engel değil, uyarı.") |

`optional` burada **"fark etmez" demek değildir**: alfasızlık ölçülür, kullanıcıya
ne kaybettiği söylenir ve kayıt envantere düşer.

**Geçiş penceresi.** Mevcut opak logolar **dokunulmadan yaşar**. Yeni yüklemede
uyarı gösterilir ve kayıt `logo_opaque` olarak işaretlenir. Sert rete dönüş ancak
şu koşulda gündeme gelir: geçiş sonunda §12-D1 yeniden koşulur ve JPEG payı **%10'un
altına** inmişse — yani tetik ters yönde de aynı sayıyla çalışır.

**Ölçümle ÇÜRÜTÜLMEYEN gerekçe.** 16 render noktasının 11'inin açık plaka boyaması
ve S1'in (`seller-shop.ts:124`) hiç plaka koymaması **aynen duruyor**. Opak JPEG
logo o 11 noktada hâlâ görünür bir kutu bırakıyor. Ölçüm *yaptırımın sertliğini*
değiştirdi, *sorunun varlığını* değil — bu yüzden kural silinmedi, `warn`'a indi.
Seçenek C (sunucuda otomatik arka plan kaldırma) hâlâ **önerilmiyor**: matting
gradyanlı/gölgeli logoda halka bırakır ve bu kalite riski **ölçülmedi**.

### K2 — Oran bandı: 1:2…2:1 mi, 1:4…4:1 mi? — ✅ ÖLÇÜMLE ÇÖZÜLDÜ (2026-08-18)

**SONUÇ: A ONAYLANDI. Band 1:2 … 2:1 olarak KALDI. Politikada değişen sayı YOK.**

Seçenek tablosu silinmeden duruyor; altında ölçüm ve hüküm var.

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — 1:2 … 2:1 | En küçük kutuda (32×32, `FavoritesLayout.ts:368`) 2:1 logo 32×16 px çizilir = platform logosunun kendi en küçük render'ıyla (`CartSummary.ts:126` `sm:h-4` = 16 px) aynı. Sistemde zaten kabul edilmiş bir okunabilirlik tabanı. |
| B — 1:4 … 4:1 + kutu ≤64 px için zorunlu **kare "mark" varyantı** | Geniş kelime markası olan satıcılar (çoğunluk olabilir) engellenmez. Bedeli: **iki dosya** — slot sayısı ikiye çıkar, panel iki dropzone gösterir, motor iki merdiven üretir. Ölçemediğim şey: kaç satıcının geniş kelime markası var (D1 `oranlar` çıktısı bunu verecek). |
| C — 1:4 … 4:1, ek varyant yok | 4:1 logo 32×32 kutuda 32×8 px → 8 px yükseklik. Okunmaz. Önermiyorum. |

**Önerim A idi. ÖLÇÜM ONU ONAYLADI.**

Tetik önceden yazılıydı: *"Mevcut logoların %20'sinden fazlası 2:1 dışındaysa B'ye
geçilmeli."* `docs/reports/08-canli-olcum.md` §2.1 (2026-08-18):

| Ölçüt | Değer | Tetik | Sonuç |
|---|---:|---|---|
| Band **içinde** (1:2 … 2:1) | **16/18 = %89** | — | — |
| Band **dışında** | **2/18 = %11** | > %20 ⇒ B | **%11 < %20 ⇒ A** |

Band dışı 2 dosyanın ikisi de **aynı orana** sahip: **w/h = 2,876** (geniş kelime
markası — `egemen-plastik`, `timex-logo`). Yani "geniş kelime markası olan satıcılar
çoğunluk olabilir" endişesi **ölçümle çürüdü**: iki dosya, iki satıcı.

**Yürürlükteki karar — A.** `require.aspect_band = { min_w_over_h: 0.5,
max_w_over_h: 2.0 }` **aynen kaldı**; iki logo politikasında da tek bir sayı
değişmedi, yalnız kaynak referansları ölçümle güncellendi. B seçeneğinin bedeli
(iki dosya → iki slot, panelde iki dropzone, motorda iki merdiven) **%11 için
ödenmiyor**.

**Band dışı 2 dosya nasıl ele alınır.** Kural gevşetilmez; bu iki satıcıdan
logolarının **kare (simge) sürümü** istenir — `messages.tr.aspect_out_of_band`
metni bunu zaten söylüyor. İki dosya için elle temas, 18 dosyalık kümede
yönetilebilir bir iştir; geriye dönük zorlama K6'ya bağlıdır (açık).

### K3 — Merdiven: 4 rung mu (64/128/256/512), 5 rung mu (+384)? — ✅ ÖLÇÜMLE ÇÖZÜLDÜ (2026-08-19)

**DURUM: ÇÖZÜLDÜ. SONUÇ B — 5 rung (+384). Öneri A ölçümle DÜŞTÜ.**

Tetik bu belgede **önceden** yazılıydı: *"D4 ölçümü 512 rung'unun gerçek baytını
verdiğinde, eğer 40 KiB tavanına yakın çıkıyorsa (yani gerçek logolar
`icon-512.png`'den ağırsa) B'ye geçilmeli."* Dalga A türev üretimini açtığı için
ölçüm 2026-08-19'da koşuldu — belgenin kendi öngördüğü koşul gerçekleşti.

**Ölçüm** — `Admin Seller Profile.logo` + `Brand.logo`, 20 referans, **18'i diskte
üretilebildi**; w512 kayıpsız WebP gerçek baytı:

| Ölçüt | Değer | Referans / tavan |
|---|---:|---|
| p50 | 27.162 B | `icon-512.png` = 27.128 B |
| p90 | 83.522 B | — |
| max | **109.172 B** | tavan 40.960 B'nin **2,7 katı** |
| Referanstan ağır | **9/18 (%50)** | tetik: "referanstan ağırsa B" |
| **Tavanı AŞAN** | **5/18 (%28)** | — |
| Tavana yakın (>%80) | 2/18 | — |

Tetik iki bağımsız okumadan da sağlanıyor. **B yürürlüğe girdi**;
`seller-logo.json` ve `brand-logo.json` `profiles[]` dizilerine `w384`
(`max_bytes` 23.040 = 40.960 × 384²/512²) eklendi, `Media Profile` tohumlayıcısı
2 yeni kayıt üretti.

> **Kararın çözmediği şey — ayrıca ele alınmalı.** En ağır 4 dosya AI üretimi PNG
> (Gemini/ChatGPT görselleri): fotoğrafımsı içerik, kayıpsız WebP'de doğal olarak
> şişiyor. 384 rung'u **aşırı-servisi** 1,83× → 1,37× indirir ama 109 KB'lık bir
> logoyu küçültmez. Ayrıca `max_bytes` türevlerde **yaptırımsız**: aşıldığında
> yalnız `NOTE_OVERSIZE` notu düşülüyor, ret ya da yeniden kodlama yok
> (`media/pipeline/image/render.py:934`). Fotoğrafımsı logolar için kayıplı yedek
> ya da bir içerik kuralı gerekiyor — bu K3'ün kapsamı dışında, yeni görev.

**Neden açık:** Tetik (aşağıda) *"512 rung'unun **gerçek baytı**"* üzerine kurulu.
O bayt ancak **türev merdiveni üretildikten sonra** ölçülebilir. Bugün türev **hiç
üretilmiyor**: bir yükleme → bir dosya (`media/engine.py:117`
`im.thumbnail((max_dim, max_dim))`, `docs/reports/03-render-envanteri.md` §0-5).
Yani ölçülecek dosya **henüz mevcut değil**, ölçüm atlanmadı.

**Ne zaman kapanır:** türev üretimi (**T-063**) yazıldıktan sonra, gerçek logolar
üzerinde §12-D4 koşulunca. `docs/reports/08-canli-olcum.md` §2.2 bunu böyle
kaydetti. O güne kadar **varsayılan A (4 rung) yürürlüktedir** — politikalardaki
`profiles[]` dizisi 4 rung taşımaya devam ediyor.

**Kısmi bilgi (karar vermeye yetmez):** ölçülen 18 logonun **6'sının (%33)** kısa
kenarı 512'nin altında; bu dosyalar `engine.py` upscale yapmadığı için 512 rung'unu
zaten doğurmayacak. Bu, 512 rung'unun **ne sıklıkla** üretileceğine dair bir ipucudur
— fakat tetik "ne sıklıkla" değil "**kaç bayt**" sorusudur, o yüzden karar açık kalır.

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — 4 rung | En kötü aşırı-servis 280 → 512 = 1,83× doğrusal / 3,35× piksel. Mutlak bedeli ölçülen referansla ~13 KB (`icon-512.png` 27 128 B ile 384'ün tahmini ~15 KB arası fark). Basit merdiven = basit `sizes` attribute'u. |
| B — 5 rung (+384) | En kötü aşırı-servis 1,37×'e düşer. Yalnız 3 talebi (280, 348, 360) etkiler. Depolamaya logo başına ~15–16 KB (WebP) ekler; D7'nin `N`'siyle çarpılınca gerçek sayı çıkar. |

**Öneri: A.** D4 ölçümü 512 rung'unun gerçek baytını verdiğinde, eğer **40 KiB
tavanına yakın çıkıyorsa** (yani gerçek logolar `icon-512.png`'den ağırsa) B'ye
geçilmeli.

### K4 — PNG yedeği: üretilsin mi?

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — Yalnız kayıpsız WebP, PNG yedeği YOK | Depolamayı yarıya indirir (188 vs 256 KiB/logo, D7). `api/seller_media.py`'nin hedef formatı zaten WebP (`:245` `IMAGE_TO_WEBP_EXTENSIONS`) — hat kurulu. WebP decode desteği bugün evrensel; `engine.py:151-160` docstring'inin bahsettiği eksiklik **encode** tarafı (Safari `canvas.toBlob`), decode değil. |
| B — WebP + PNG `<picture>` yedeği | Sıfır risk. Bedeli ~%36 ek depolama ve her render noktasında `<picture>` yazımı — bugün storefront'ta `<picture>` kullanımı **0** (`grep -rni "<picture" src \| wc -l` → 0, `docs/reports/03-render-envanteri.md` §0-1), yani 19 noktada yeni markup. |

**Öneri: A.** Doğrulama: `docs/reports/00-ortam-envanteri.md`'de tarayıcı payı verisi
varsa oradan; yoksa D3'ün çalıştırıldığı cihaz listesi.

### K5 — 512 rung'unu doğuramayan 400×400 tavsiyesi ne olacak?

Panel bugün **400×400** tavsiye ediyor (`DocTypeFormView.vue:448`). Bu standart 512
diyor. `engine.py:117` upscale yapmadığı için 400×400 master 512 rung'unu doğuramaz.

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — Tavsiye metni 512×512'ye çıkarılır | Merdiven bütün çalışır. Bedeli: tek satır metin değişikliği (`DocTypeFormView.vue:448`) — **bu görevin kapsamı dışında**, ayrı bir görev. |
| B — 512 rung'u düşürülür, merdiven 64/128/256 olur | S1 (140 px, DPR 2 = 280) ve S14 (160 px, DPR 3 = 480) 256 rung'uyla servis edilir → S14'te 1,88× eksik piksel, gözle görülür bulanıklık. |
| C — 400 master'dan 512 rung'u **upscale** ile üretilir | `engine.py:97` docstring'i "Yalnız downscale — upscale yok" diyor; bu bir tasarım kararı ve upscale kalite kazandırmaz, yalnız bayt harcar. Önermiyorum. |

**Öneri: A.**

### K6 — Sert ret eşiği (256 px) geriye dönük uygulanacak mı?

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — Yalnız YENİ yüklemelere; mevcut logolar dokunulmadan yaşar, envanterde `logo_low_resolution` işaretlenir | Hiçbir mağaza aniden logosuz kalmaz. Mevcut düşük çözünürlüklü logolar bulanık kalır ama görünür. |
| B — Geriye dönük tarama + satıcıya bildirim + N gün sonra kaldırma | Standart gerçekten uygulanır. Ama D1 çıktısı olmadan kaç mağazanın etkileneceği **bilinmiyor** ve mağaza logosunu kaldırmak ticari bir karar. |

**Öneri: A**, D1 çalıştıktan sonra B için ayrı bir karar alınır.

---

## 14. Kabul kriterleri — bu standart "uygulanmış" sayılır mı

- [ ] `tradehub_core/media/pipeline/policy/slots/seller-logo.json` ve `brand-logo.json` bir kayıt
      defteri tarafından **okunuyor** ve `upload_policy.check()` slot anahtarını alıyor.
- [ ] §7'deki 12 kodun tümü `upload_policy.py`'de tanımlı ve `ALL_CODES`'ta.
- [ ] Master, kabul bandındaki her oran için **1:1 saydam letterbox** ile
      normalize ediliyor → §11-F4'teki 5 `object-cover` noktasında kırpma
      matematiksel olarak imkânsız.
- [ ] 4 rung (64/128/256/512) **kayıpsız** üretiliyor; `engine.to_webp` kayıplı
      yolu logo slotunda çalışmıyor.
- [ ] og:image logo yolu **contain + pad + beyaz zemin**; `seo/og_image.py:34`'ün
      alfa düşürmesi belirli bir renge yapılıyor.
- [ ] SVG **hâlâ reddediliyor** — §6'nın 10 maddesi tamamlanmadan açılmıyor.
- [ ] `data:` URI logo yükleme yolu reddediliyor (`logo_data_uri_forbidden`).
- [ ] §12'deki D1, D2, D4 çalıştırılmış ve çıktıları bu belgeye eklenmiş.
- [x] §13-K1 (JPEG) ve §13-K2 (oran bandı) **ölçümle çözüldü** ve sonuç hem bu
      belgede (§13.0) hem iki politika JSON'unda işlendi — 2026-08-18.
- [ ] §13'teki kalan 4 kararın (K3, K4, K5, K6) her biri onaylanmış ve karar bu
      belgede işaretlenmiş. K3 ayrıca **T-063 (türev üretimi) olmadan ölçülemez**.

---

**Bu belge kapanmadan yapılmaması gerekenler:** `srcset` yazımı (gösterecek ikinci
dosya yok), SVG kabulü (slot kapsamı yok), 512 rung'una güvenen herhangi bir render
(400×400 tavsiyesi onu doğurmuyor), logo dosyalarının toplu yenilenmesi (5 kopya var,
F15).

---

## VARSAYILANDA ONAYLANAN KARARLAR — 2026-08-19

Aşağıdaki kararlar platform yöneticisi tarafından **varsayılan seçenekte
onaylanmıştır**. Her birinde varsayılan, bu belgedeki öneriyle zaten aynıydı ve
hâlihazırda yürürlükteydi — onay hiçbir davranışı değiştirmez, yalnız kararı
"açık" olmaktan çıkarır. Yanlış bulunan olursa tek satırlık bir değişiklikle
çevrilebilir.

| # | Karar | Onaylanan | Not |
|---|---|---|---|
| **K4** | PNG yedeği üretilsin mi? | **A — yalnız kayıpsız WebP** | Öneriyle aynı |
| **K5** | Panelin 400×400 tavsiyesi | **A — 512×512** | Öneriyle aynı; panel metni ayrı görev |
| **K6** | 256 px sert reddi geriye dönük mü? | **A — yalnız yeni yüklemeler** | Öneriyle aynı. Ölçüm: kısa kenar < 256 = 1/18 (%5,5) |

Bu belgedeki hiçbir seçenek tablosu silinmedi; kararlar istenirse yeniden açılabilir.
