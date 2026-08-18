# T-004 — Frontend Render Envanteri (Storefront)

**Kapsam:** `/Users/ahmet/Desktop/istoc/tradehubfront/src/` — ürün görselinin ekrana basıldığı her nokta.
**Tarih:** 2026-08-17
**Durum:** Kod okuma + hesaplama. **Tarayıcı ölçümü YAPILMADI** — Docker kapalı, canlı siteye ve üretim veritabanına erişim yok. LCP/CLS **ölçülmedi**; bu belgede LCP/CLS'e dair hiçbir sayı yoktur. Ölçüm gerektiren her şey son bölümdedir.

> Bu belge yeni bir tasarım önermez. Storefront'ta zaten kurulmuş olan render düzenini (kutu genişlikleri, kırılım noktaları, mevcut `loading`/`decoding`/`width`/`height` disiplini) belgeler; eksik olanı (srcset/sizes/AVIF/preload) tespit eder.

---

## 0. Yönetici özeti — 6 madde

1. **`srcset` / `sizes` / `<picture>` kullanımı SIFIR.** Tüm storefront'ta 183 `<img>` etiketi var (test/snapshot hariç), hiçbirinde `srcset` yok. Doğrulama: `grep -rni "srcset" src | wc -l` → **0**; `grep -rni "<picture" src | wc -l` → **0**; `grep -rn 'sizes="' src | wc -l` → **0**.
2. **Buna karşılık `width`/`height` + `decoding` disiplini büyük ölçüde KURULU.** 135 `<img>` üzerinde `decoding=` var (`grep -rn 'decoding=' src | wc -l` → 135). Ürün kartı ve galeri gibi ana render noktalarında hem `width`/`height` attribute'u hem de `aspect-square` kapsayıcı var — yani CLS'e karşı **iki katmanlı** koruma zaten mevcut.
3. **`loading="lazy"` seçici ve bilinçli uygulanmış** (67 kullanım), fold-üstü kart ilk görselini bilerek eager bırakan bir opt-in bayrak var: `ListingCardOptions.lazy` — `src/components/shared/ListingCard.ts:17-23`.
4. **`fetchpriority="high"` yalnızca 1 yerde var** ve o da bir ürün görseli değil, `/sell` sayfasının bundle'lanmış statik hero'su: `src/components/sell/SellPageLayout.ts:113`. **Hiçbir ürün görseline LCP önceliği verilmiyor**, hiçbir sayfada `<link rel="preload" as="image">` yok (`grep -n "preload" index.html` → eşleşme yok).
5. **Backend bugün tek boy üretiyor.** `tradehub_core/media/engine.py:117` (`im.thumbnail((max_dim, max_dim))`) ve `:177` (`im.thumbnail((1920, 1920))`) — yükleme anında **tek bir master** küçültülüp saklanıyor, türev (derivative) boy üretilmiyor. Yani `srcset` yazılsa bile **bugün gösterecek ikinci bir dosya yok**. Faz 2'nin asıl işi budur.
6. **En kritik piksel talebi mobil ürün detay galerisidir:** kutu = tam viewport genişliği; 430px'lik bir telefonda DPR 3 → **1290 CSS-olmayan piksel** gerekiyor; mevcut master ise en fazla 1920px uzun kenar (`engine.py:177`). Kare olmayan görsellerde bu sınır zorlanıyor.

---

## 1. Ölçüm temeli — kırılım noktaları ve container sistemi

Tüm genişlik hesapları bu üç kaynaktan türetildi. **Hiçbiri varsayım değildir.**

### 1.1 Kırılım noktaları (Tailwind v4 `@theme`, ezilmiş)

`src/style.css:256-260`:

| Ad | Değer | Not |
|---|---|---|
| `xs` | 320px | |
| `sm` | 480px | Tailwind varsayılanı 640 — **ezilmiş** |
| `md` | 640px | Tailwind varsayılanı 768 — **ezilmiş** |
| `lg` | 768px | Tailwind varsayılanı 1024 — **ezilmiş** |
| `xl` | 1024px | Tailwind varsayılanı 1280 — **ezilmiş** |
| `2xl` | **1536px** | `--breakpoint-2xl` tanımlı DEĞİL → Tailwind v4 varsayılanı (96rem) geçerli |

> **Tuzak:** Bu projede `lg:` = 768px, `xl:` = 1024px. Tailwind belgelerinden okunan varsayılanlarla hesap yapılırsa tüm kutu genişlikleri yanlış çıkar. `pages/product-detail.ts:289-291` yorumu da bunu açıkça not ediyor: *"Bu projedeki `xl:` CSS kırılımı 1024px'tir."*

### 1.2 Container

`src/style.css:1540-1549` — `.container-boxed` ve `.container-wide` **aynı**:

```
max-width: var(--container-lg);          /* 1840px — style.css:249 */
padding-inline: var(--spacing-page-x);   /* 16px  — style.css:217 */
@variant 2xl { padding-inline: var(--spacing-page-x-lg); }  /* 32px — style.css:219 */
```

Türetilen formül (kutu modeli `border-box` olduğu için padding max-width'in İÇİNDEDİR):

```
içerik genişliği(W) = min(1840, W) − (W ≥ 1536 ? 64 : 32)
```

| Viewport | container içerik genişliği |
|---|---|
| 360 | 328 |
| 390 | 358 |
| 430 | 398 |
| 640 | 608 |
| 768 | 736 |
| 1024 | 992 |
| 1280 | 1248 |
| 1440 | 1408 |
| 1536 | 1472 |
| 1920 | **1776** (max-width devrede) |

> **Not:** Bu hesap dikey kaydırma çubuğunu (masaüstünde ~15px) yok sayar. Gerçek `innerWidth` çubuk kadar daralır. Etki ≤ %1, profil seçimini değiştirmez, ama Lighthouse çıktısıyla birebir tutmayabilir.

### 1.3 Grid boşluğu

`src/style.css:580` → `--product-grid-gap: 16px`. `ProductListingGrid` ve ana sayfa vitrini bu değişkeni inline `style="gap: var(--product-grid-gap, 16px)"` ile kullanıyor (`src/components/products/ProductListingGrid.ts:80,95`; `src/components/hero/ProductGrid.ts:185`).

---

## 2. Render noktası envanteri

Ürün görselinin basıldığı her yer. "Kutu" = CSS'in görsele ayırdığı kutu; "Oran" = kutunun en-boy oranını kim sabitliyor.

| # | Render noktası | Dosya:satır | Kutu | Oran / CLS koruması | `loading` | `decoding` | `w/h` attr | `srcset` |
|---|---|---|---|---|---|---|---|---|
| R1 | **ListingCard slider görseli** (liste/arama/marka/top-deals/tailored/çok-satanlar/ana sayfa vitrini) | `components/shared/ListingCard.ts:105`, kutu `:163` | grid hücresi genişliği, `w-full h-full` | `aspect-square` (ListingCard.ts:163) | ilk slayt eager, `i>0` veya `opts.lazy` → lazy | `async` | `400×400` | **yok** |
| R2 | **Ürün detay ANA görsel — masaüstü** | `components/product/ProductImageGallery.ts:66-75` (`renderGalleryMedia`) | `max-w-[512px]`, `aspect-square` (`:246`, `:248`) | `aspect-square` | `eager` | `sync` | `800×800` | **yok** |
| R3 | **Ürün detay galeri karosu (thumb)** | aynı fonksiyon, `size="thumb"` | `70×70` sabit, `p-1` → iç kutu 62px (`ProductImageGallery.ts:103`, `THUMB_SIZE=70` `:86`) | sabit px | `lazy` | `async` | `70×70` | **yok** |
| R4 | **Ürün detay lightbox ANA görsel** | `ProductImageGallery.ts:325` (aynı `renderGalleryMedia`, `large`) | `h-full aspect-square`, kapsayıcı `h-[min(82vh,720px)]` (`:322`) | `aspect-square` | `eager` | `sync` | `800×800` | **yok** |
| R5 | **Ürün detay lightbox karosu** | `ProductImageGallery.ts:189` | `52×52` (`:339` içindeki `[&_.gallery-lightbox-thumb]:!w-[52px]` sınıfı `LIGHTBOX_THUMB_SIZE=76`'yı ezer) | sabit px | `lazy` | `async` | `70×70` | **yok** |
| R6 | **Ürün detay ANA görsel — mobil** (<1024px) | `components/product/MobileLayout.ts:144`, kutu `:136` | **tam viewport genişliği**, `w-full aspect-square` | `aspect-square` | `i===0` eager, sonrası lazy | `async` | `800×800` | **yok** |
| R7 | **Ürün detay mobil karo şeridi** | `components/product/MobileLayout.ts:198` | `80×80` (attr) | — | `lazy` | `async` | `80×80` | **yok** |
| R8 | **İlgili ürünler (Swiper)** | `components/product/RelatedProducts.ts:85`, kutu `:82` | slide genişliği (bkz. §3.7) | `aspect-square` | `lazy` | `async` | `400×400` | **yok** |
| R9 | **Mobil öneri şeridi** | `components/product/MobileRecommendations.ts:58`, kutu `:55` | `basis-[42%]` (dar ekranda `basis-[46%]`, `:54`) | `aspect-square` | `lazy` | `async` | `400×400` | **yok** |
| R10 | **Ana sayfa "En İyi Fırsatlar"** | `components/hero/TopDeals.ts:58-65`, kutu `:97` | grid hücresi (bkz. §3.3) | `aspect-square` | `lazy` | `async` | `400×400` | **yok** |
| R11 | **Ana sayfa öneri slider'ı** | `components/hero/RecommendationSlider.ts:38-45` | slide `xl:!w-[260px]` (`:52`), kart `p-1.5 sm:p-2` | kapsayıcı `h-full` | `lazy` | `async` | `400×400` | **yok** |
| R12 | **Kategori vitrini (bento)** | `components/category/CategoryShowcase.ts:154`, grid `:245` | satır yüksekliği `auto-rows-[85px] sm:145px lg:210px`, sütun = grid | satır yüksekliği sabit | `lazy` | `async` | `400×400` | **yok** |
| R13 | **Sepet — ürün başlık görseli** | `components/cart/molecules/ProductItem.ts:84` | `40×40`, `sm:60×60` | sabit px | yok | `async` | `60×60` | **yok** |
| R14 | **Sepet — SKU satırı** | `components/cart/molecules/SkuRow.ts:24`, kutu `:36` | `36×36`, `sm:40×40` | sabit px | `lazy` | `async` | `60×60` | **yok** |
| R15 | **Sepet/checkout özet şeridi** | `components/cart/page/CartSummary.ts:22`, kutu `:20` | `56×56`; `<380px` `48×48`; `sm:64×64` | sabit px | yok | `async` | `64×64` | **yok** |
| R16 | **Sepet çekmecesi (Alpine)** | `alpine/cart.ts:640`, kutu `:639` | `56×56`, `sm:64×64` | sabit px | yok | yok | **yok** | **yok** |
| R17 | **Favoriler ürün kartı** | `components/favorites/FavoritesLayout.ts:990`, grid `:870` | grid hücresi | kapsayıcı | `lazy` | `async` | `400×400` | **yok** |
| R18 | **Mağaza (seller) ürün ızgarası** | `components/seller/CompanyProfile.ts:806`, grid `:802` | grid hücresi | kapsayıcı | `lazy` | `async` | `400×400` | **yok** |
| R19 | **Mağaza şablon motoru ürün karoları** | `utils/seller/section-registry.ts:280, 389, 414` | grid hücresi | kapsayıcı | `lazy` | **yok** | **yok** | **yok** |
| R20 | **Buyer dashboard mini kart** | `components/shared/ProductCard.ts:15-21` | `max-w-[169.5px]`, `aspect-square` | `aspect-square` | `lazy` | `async` | `170×170` | **yok** |

**Ürün görseli olmayan ama LCP adayı olabilecek tek eager/high görsel:** `components/sell/SellPageLayout.ts:107-115` — `loading="eager" fetchpriority="high"`, kaynak bundle'lanmış `assets/images/liman.avif` (`:21`). Bu tek başına, projede AVIF'in **statik pazarlama görselinde kullanıldığını ama kullanıcı yüklemesi medya hattında kullanılmadığını** gösterir.

---

## 3. ⭐ Piksel tablosu — sayfa tipi × render noktası × CSS kutu × DPR

**Bu bölüm Faz 2'nin profil genişliklerini belirleyecek asıl çıktıdır.**

**Hesap yöntemi:** §1'deki container formülü + ilgili bileşenin grid sınıfları. Her tablo altında formülün kaynağı verilmiştir. Rakamlar bir Node betiğiyle üretildi (aritmetik hata riskini düşürmek için), betik `scratchpad/calc.mjs`; her satır elle doğrulanabilir.
**@2x / @3x sütunları:** kutu genişliği × DPR, yukarı yuvarlanmış. Bunlar **gerekli görsel piksel genişlikleridir**, dosya boyutu değil.

### 3.1 Ürün listeleme sayfası (`/pages/products.html`)

Kaynak: `pages/products.ts:147` (container-boxed) → `:163` (`flex flex-col lg:flex-row gap-4 lg:gap-6`) → `:166` (`hidden lg:block` filtre kolonu) → `components/products/FilterSidebar.ts:557` (`w-full lg:w-60 xl:w-64` = 240px / 256px) → `components/products/ProductListingGrid.ts:94` (`grid-cols-2 lg:grid-cols-3 min-[1280px]:grid-cols-5`, gap 16px).

| Viewport | Sütun | Kenar çubuğu | **CSS kutu** | @1x | @2x | @3x |
|---|---|---|---|---|---|---|
| 360 | 2 | yok | 156.0 | 156 | 312 | 468 |
| 390 | 2 | yok | 171.0 | 171 | 342 | 513 |
| 430 | 2 | yok | 191.0 | 191 | 382 | 573 |
| **640** | **2** | yok | **296.0** | 296 | **592** | 888 |
| 768 | 3 | 240 | 146.7 | 147 | 294 | 440 |
| 1024 | 3 | 256 | 226.7 | 227 | 454 | 680 |
| 1280 | 5 | 256 | 180.8 | 181 | 362 | 543 |
| 1440 | 5 | 256 | 212.8 | 213 | 426 | 639 |
| 1536 | 5 | 256 | 225.6 | 226 | 452 | 677 |
| **1920** | 5 | 256 | **286.4** | 287 | **573** | 860 |

> **Dikkat çeken anomali:** Kutu genişliği viewport ile **monoton artmıyor**. 640px'te kart 296px, 768px'te 147px'e **düşüyor** — çünkü `lg` (768) hem 3 sütuna geçiyor hem de 240px'lik filtre çubuğunu açıyor. Bu, ileride yazılacak `sizes` attribute'unun basit bir `(min-width: …) Xvw` zinciriyle ifade edilemeyeceği, kırılım başına ayrı sabit değer gerektireceği anlamına gelir.

### 3.2 Ana sayfa ürün vitrini

Kaynak: `components/hero/ProductGrid.ts:184` — `grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-6 2xl:grid-cols-7`, `container-wide`, gap 16px.

| Viewport | Sütun | **CSS kutu** | @1x | @2x | @3x |
|---|---|---|---|---|---|
| 360 | 2 | 156.0 | 156 | 312 | 468 |
| 390 | 2 | 171.0 | 171 | 342 | 513 |
| 430 | 2 | 191.0 | 191 | 382 | 573 |
| 640 | 3 | 192.0 | 192 | 384 | 576 |
| 768 | 4 | 172.0 | 172 | 344 | 516 |
| 1024 | 6 | 152.0 | 152 | 304 | 456 |
| 1280 | 6 | 194.7 | 195 | 390 | 584 |
| 1440 | 6 | 221.3 | 222 | 443 | 664 |
| 1536 | 7 | 196.6 | 197 | 394 | 590 |
| 1920 | 7 | 240.0 | 240 | 480 | 720 |

> Bu ızgara **maksimum 240px** kutuya çıkıyor — yani ana sayfa vitrini için 480px'lik bir türev @2x'i tam karşılar. Şu an oraya 1920px'lik master gidiyor.

### 3.3 Ana sayfa "En İyi Fırsatlar"

Kaynak: `components/hero/TopDeals.ts:236` — `grid-cols-2 min-[550px]:grid-cols-3 lg:grid-cols-4 min-[850px]:grid-cols-5 min-[1000px]:grid-cols-6`, `gap-x-2 sm:gap-x-3 lg:gap-x-4` (8/12/16px), container `:211`.

| Viewport | Sütun | gap | **CSS kutu** | @1x | @2x | @3x |
|---|---|---|---|---|---|---|
| 360 | 2 | 8 | 160.0 | 160 | 320 | 480 |
| 390 | 2 | 8 | 175.0 | 175 | 350 | 525 |
| 430 | 2 | 8 | 195.0 | 195 | 390 | 585 |
| 640 | 3 | 12 | 194.7 | 195 | 390 | 584 |
| 768 | 4 | 16 | 172.0 | 172 | 344 | 516 |
| 1024 | 6 | 16 | 152.0 | 152 | 304 | 456 |
| 1280 | 6 | 16 | 194.7 | 195 | 390 | 584 |
| 1440 | 6 | 16 | 221.3 | 222 | 443 | 664 |
| 1536 | 6 | 16 | 232.0 | 232 | 464 | 696 |
| 1920 | 6 | 16 | 282.7 | 283 | 566 | 848 |

### 3.4 "Size Özel" + "Çok Satanlar" ızgaraları (aynı sınıf dizisi)

Kaynak: `components/tailored-selections/TailoredProductGrid.ts:22` ve `components/top-ranking-category/TopRankingCategoryGrid.ts:50` — ikisi de `grid-cols-2 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-3 lg:gap-4` (12/16px), `container-boxed`.

| Viewport | Sütun | **CSS kutu** | @1x | @2x | @3x |
|---|---|---|---|---|---|
| 360 | 2 | 158.0 | 158 | 316 | 474 |
| 390 | 2 | 173.0 | 173 | 346 | 519 |
| 430 | 2 | 193.0 | 193 | 386 | 579 |
| 640 | 3 | 194.7 | 195 | 390 | 584 |
| 768 | 4 | 172.0 | 172 | 344 | 516 |
| 1024 | 5 | 185.6 | 186 | 372 | 557 |
| 1280 | 5 | 236.8 | 237 | 474 | 711 |
| 1440 | 5 | 268.8 | 269 | 538 | 807 |
| 1536 | 5 | 281.6 | 282 | 564 | 845 |
| **1920** | 5 | **342.4** | 343 | **685** | 1028 |

> Marka sayfası (`pages/brand.ts:404,410`) `ProductListingGrid`'i **kenar çubuğu olmadan** kullanır; kutuları bu tabloya değil, §3.1'in "kenar çubuğu yok" varyantına yakındır: 1920'de `(1776−64)/5 = 342.4px`. Yani marka/kategori sayfası en geniş kart kutusuna sahip listeleme yüzeyidir.

### 3.5 Ürün detay — ANA görsel (masaüstü, ≥1024px)

Kaynak zinciri:
- `pages/product-detail.ts:251` → dış kap `max-w-[1736px] px-4 min-[1280px]:px-10`
- `:259` → `grid-cols-[minmax(0,1fr)_300px] min-[1280px]:grid-cols-[minmax(0,1fr)_394px]`, `gap-4`
- `:261` → içerik içi `grid-cols-[minmax(0,300px)_…] min-[1280px]:[minmax(0,465px)_…] min-[1536px]:[minmax(0,590px)_…]`
- `components/product/ProductImageGallery.ts:212` → `min-[1280px]:ps-[88px]` (dikey karo rayı)
- `:246` → `max-w-[512px] mx-auto`, `:248` → `aspect-square w-full`

| Viewport | Galeri sütunu | −karo rayı | **CSS kutu** (min(512, …)) | @1x | @2x | @3x |
|---|---|---|---|---|---|---|
| 1024–1279 | 300 | 0 | **300** | 300 | 600 | 900 |
| 1280–1535 | 465 | 88 | **377** | 377 | 754 | 1131 |
| ≥1536 | 590 | 88 | **502** | 502 | **1004** | 1506 |

> **Kod ile yorum çelişiyor:** `product-detail.ts:255-256` civarındaki ve `ProductImageGallery.ts:239-241` yorumu "max 560px, 2xl'de 680px" diyor; gerçek sınıf `max-w-[512px]` (`:246`). Faz 2'de profil genişliği seçilirken **yoruma değil sınıfa** güvenilmeli. (Yorumu düzeltmek bu görevin kapsamı dışında — kod dosyası değiştirilmedi.)

### 3.5b Hover-zoom: gizli piksel talebi

`ProductImageGallery.ts:22` → `export const ZOOM_SCALE = 1.85`, uygulanışı `alpine/product.ts:505` (`transform: scale(1.85)`).

Zoom açıkken görsel CSS kutusunun 1.85 katı ölçekte gösteriliyor. Yani **efektif** piksel ihtiyacı:

| Viewport | Kutu | Zoom'lu efektif @1x | Zoom'lu @2x |
|---|---|---|---|
| 1024–1279 | 300 | 555 | 1110 |
| 1280–1535 | 377 | 698 | 1395 |
| ≥1536 | 502 | **929** | **1858** |

> Bu, masaüstü ürün detayının neden 1920px master'a hâlâ ihtiyaç duyduğunun teknik gerekçesidir. Faz 2 profilleri "ana görsel 512px yeter" diye kurgulanırsa **zoom bulanıklaşır**. Ana görsel için ayrı bir "zoom kaynağı" profili gerekir.

### 3.6 Ürün detay — ANA görsel (mobil, <1024px)

Kaynak: `pages/product-detail.ts:291` (`matchMedia('(min-width: 1024px)')` → altı mobil düzen), `components/product/MobileLayout.ts:537` (kök sarmalayıcıda yatay padding YOK), `:136` (`w-full aspect-square`).

**Kutu = tam viewport genişliği.**

| Viewport | **CSS kutu** | @1x | @2x | @3x |
|---|---|---|---|---|
| 360 | 360 | 360 | 720 | **1080** |
| 390 (iPhone 14/15) | 390 | 390 | 780 | **1170** |
| 430 (iPhone Pro Max) | 430 | 430 | 860 | **1290** |
| 640 | 640 | 640 | 1280 | 1920 |
| 768 (tablet dikey) | 768 | 768 | **1536** | 2304 |
| 1023 | 1023 | 1023 | 2046 | 3069 |

> **Sistemdeki en yüksek piksel talebi burasıdır.** 768px'lik bir tablette DPR2 → 1536px; 1023px'te DPR2 → 2046px. Mevcut master tavanı 1920px (`media/engine.py:177`) — yani **geniş tabletlerde @2x zaten karşılanamıyor**. Faz 2'de "en büyük profil" kararı bu satırdan çıkmalı.

### 3.7 İlgili ürünler (Swiper)

Kaynak: `components/product/RelatedProducts.ts:247-256` — `slidesPerView: 1.4`, kırılımlar `480:2.2/12px`, `640:3/14px`, `960:4/16px`, `1280:5/16px`. Kapsayıcı = ürün detay içerik sütunu (masaüstü) ya da container-boxed (mobil).

| Viewport | slidesPerView | **CSS kutu (≈)** | @1x | @2x | @3x |
|---|---|---|---|---|---|
| 360 | 1.4 | ~226 | 226 | 452 | 678 |
| 390 | 1.4 | ~247 | 248 | 495 | 742 |
| 430 | 1.4 | ~276 | 276 | 552 | 828 |
| 640 | 3 | ~193 | 194 | 387 | 580 |
| 768 | 3 | ~236 | 236 | 472 | 708 |
| 1024 | 4 | ~157 | 157 | 314 | 471 |
| 1280 | 5 | ~145 | 146 | 291 | 436 |
| 1440 | 5 | ~177 | 178 | 355 | 532 |
| 1920 | 5 | ~236 | 237 | 473 | 710 |

> **Bu satırlar ≈ işaretlidir.** Swiper kesirli `slidesPerView`de slide genişliğini çalışma anında hesaplar; buradaki değerler `(kapsayıcı − spaceBetween×(n−1))/n` yaklaşımıyla türetildi, ±5px sapabilir. Kesin değer için §7'deki DOM ölçüm komutu.

### 3.8 Sabit boyutlu (grid'e bağlı olmayan) kutular

Bunlar viewport'tan bağımsız; doğrudan profil eşiği verirler.

| Render noktası | Kutu | @1x | @2x | @3x | Kaynak |
|---|---|---|---|---|---|
| PD galeri karosu | 70×70 (`p-1` → içerik 62) | 70 | 140 | 210 | `ProductImageGallery.ts:86,103` |
| PD lightbox karosu | 52×52 | 52 | 104 | 156 | `ProductImageGallery.ts:339` |
| PD mobil karo şeridi | 80×80 (attr) | 80 | 160 | 240 | `MobileLayout.ts:198` |
| Sepet SKU satırı | 36 / `sm:`40 | 40 | 80 | 120 | `SkuRow.ts:36` |
| Sepet ürün başlığı | 40 / `sm:`60 | 60 | 120 | 180 | `ProductItem.ts:84` |
| Checkout özet şeridi | 48 / 56 / `sm:`64 | 64 | 128 | 192 | `CartSummary.ts:20` |
| Sepet çekmecesi | 56 / `sm:`64 | 64 | 128 | 192 | `alpine/cart.ts:639` |
| Buyer dashboard mini kart | ≤169.5 | 170 | 340 | 510 | `shared/ProductCard.ts:13` |
| PD lightbox ana görsel | ≈636 (bkz. altta) | 636 | 1272 | 1908 | `ProductImageGallery.ts:322-324` |

Lightbox ana görsel hesabı: `#gallery-lightbox-inner` yüksekliği `min(82vh, 720px)` (`:322`); alttaki karo kapsülü ~68px (`52px` karo + `py-2`), aralık `gap-4` = 16px → sahne ≈ 720 − 68 − 16 = **636px**, görsel `h-full aspect-square` (`:324`) → 636×636. 1080p ekranda `82vh = 885 > 720` olduğu için 720 sınırı bağlayıcıdır.

### 3.9 Türetilmiş profil eşiği önerisi (Faz 2 girdisi)

Yukarıdaki tüm kutuların @1x/@2x/@3x taleplerinin birleşimi şu kümelenmeyi veriyor:

| Küme | Kapsadığı talep | Öneri genişlik |
|---|---|---|
| Mikro | sepet/SKU/karo @1x–@2x (40–210) | **96**, **192** |
| Küçük | kart @1x (146–343), karo @3x, mini kart @2x | **384** |
| Orta | kart @2x (291–685), PD masaüstü @1x, ilgili @2x | **640**, **768** |
| Büyük | kart @3x (436–1028), PD mobil @2x (720–1536), PD masaüstü @2x (600–1004) | **1080**, **1280** |
| Kaynak / zoom | PD mobil @3x (1080–1290), lightbox @2x (1272), masaüstü zoom @2x (1858) | **1600**, **1920** |

> Bu tablo **öneridir, karar değildir.** Faz 2'de karar verilirken bant genişliği maliyeti ve CDN cache isabet oranıyla birlikte tartılmalı. Buradaki katkı: **hangi genişliklerin hangi somut render kutusundan çıktığının izlenebilir olması.**

---

## 4. Mevcut optimizasyon durumu — var / yok

Sayılar `grep` ile doğrulandı; komutlar `cd /Users/ahmet/Desktop/istoc/tradehubfront/src` içinde çalıştırıldı.

| Teknik | Durum | Kanıt |
|---|---|---|
| `srcset` | ❌ **YOK (0)** | `grep -rni "srcset" . \| wc -l` → 0 |
| `sizes` | ❌ **YOK (0)** | `grep -rn 'sizes="' . \| wc -l` → 0 |
| `<picture>` / `<source type>` | ❌ **YOK (0)** | `grep -rni "<picture" . \| wc -l` → 0. (`<source>` 3 kez geçiyor ama üçü de `video/mp4`: `pages/trade-assurance.ts:128,252,356`) |
| `loading="lazy"` | ✅ **VAR (67)** | `grep -rn 'loading="lazy"' . \| wc -l` → 67 |
| `loading="eager"` (bilinçli) | ✅ VAR (2) | `grep -rn 'loading="eager"' . \| wc -l` → 2 (`ProductImageGallery.ts:73` şablonlu, `SellPageLayout.ts:112`) |
| `decoding` | ✅ VAR (135) | `grep -rn 'decoding=' . \| wc -l` → 135 |
| `fetchpriority="high"` | ⚠️ **1 tane, ürün görseli değil** | `SellPageLayout.ts:113` (statik `liman.avif`) |
| `<link rel="preload" as="image">` | ❌ **YOK** | `grep -n "preload" ../index.html` → eşleşme yok |
| `width`/`height` attribute | ✅ Ana yollarda VAR | 183 `<img>`in ~34'ünde eksik; ürün render noktalarında (R1–R12, R20) mevcut |
| LQIP / blurhash / thumbhash | ❌ **YOK** | `grep -rni "lqip\|blurhash\|thumbhash\|blur-up" .` → eşleşme yok |
| Skeleton / rezerve yükseklik | ✅ VAR (LQIP yerine) | `hero/ProductGrid.ts:184` `min-h-[2240px] md:min-h-[1900px] lg:min-h-[1510px] xl:min-h-[1000px] 2xl:min-h-[670px]`; `TopDeals.ts:236` `min-h-[235px] lg:min-h-[275px]`; kart iskeleti `hero/ProductGrid.ts:56` |
| AVIF (kullanıcı medyası) | ❌ YOK | Backend `engine.py:132` çıktı formatı: JPEG/PNG/TIFF korunur, diğerleri WEBP |
| AVIF (statik pazarlama görseli) | ✅ 2 dosya | `assets/images/liman.avif` (`SellPageLayout.ts:21`), `assets/images/kargo.avif` (`ShippingLogisticsPage.ts:4`) |
| WebP (kullanıcı medyası) | ✅ VAR (sunucu tarafı) | `media/engine.py:147` `to_webp()` — Safari/iOS/Capacitor'da client `canvas.toBlob('image/webp')` yoksa sunucuda tamamlanıyor |
| Progressive JPEG | ✅ VAR | `media/engine.py:120-122` `progressive=True` |
| EXIF rotasyon + ICC koruma | ✅ VAR | `media/engine.py:114-116` |
| Görsel CDN / on-the-fly resize | ❌ YOK | Görseller doğrudan `/files/` ve `/private/files/` altından servis ediliyor (`utils/mediaUrl.ts:11-13`) |

### 4.1 Şu an ZATEN ÇÖZÜLMÜŞ olan ve tekrar tasarlanmaması gerekenler

Bunlar T-004'ün "eksiği belgele, üstüne yazma" kuralına giren maddelerdir:

1. **Fold-üstü/fold-altı lazy ayrımı.** `ListingCard` opt-in `lazy` bayrağı (`ListingCard.ts:17-23`, kullanımı `hero/ProductGrid.ts:42-46`) — ana sayfa vitrini kartlarını lazy'ye çeviriyor, liste sayfası fold-üstü kartları eager bırakıyor. Bu karar 2026-07-23 tarihli CWV çalışmasında verilmiş (`main.ts:142-145` yorumu: opacity-0 giriş gating'i LCP ölçümünü bozduğu için kaldırılmış).
2. **Progressive mount + IntersectionObserver.** Ana sayfa kartları iki partide basılıyor; ikinci parti placeholder ile yer tutup görünür olunca mount ediliyor (`hero/ProductGrid.ts:61-110`). Placeholder `before:aspect-square` ile kutuyu önceden rezerve ediyor (`:56`).
3. **Galeri görselinin tek kaynaktan render'ı.** `renderGalleryMedia` (`ProductImageGallery.ts:54-77`) hem şablon hem Alpine slayt değişimi/lightbox/varyant swap için **zorunlu** tek giriş. Fonksiyondaki yorum (`:41-52`), elle `<img>` yazıldığında görselin intrinsic boyutta basılıp kırpıldığı gerçek bir regresyonu belgeliyor (2026-08-03). **Faz 2'de `srcset` eklenecekse buraya eklenmelidir** — tek nokta.
4. **Karo sınıflarının tek kaynağı.** `THUMB_CLASS` / `LIGHTBOX_THUMB_CLASS` (`ProductImageGallery.ts:106,115`) hem şablondan hem `alpine/product.ts:swapGalleryImages`'ten okunuyor; 2026-07-28'de yaşanan boyutsuz karo hatasının çözümü.
5. **Skeleton yükseklikleri.** `min-h-*` merdivenleri (§4 tablosu) LQIP yerine geçen, CLS'i kaynağında kesen mevcut çözüm. LQIP önerilecekse bunun **yerine** değil, **yanına** konumlandırılmalı.
6. **Sunucu tarafı garanti-WebP.** `media/engine.py:147-181` — Safari/iOS'ta client WebP üretemediğinde sunucu tamamlıyor. Yani "WebP'ye geçelim" bir Faz 2 maddesi **değildir**, zaten yapılmıştır.

---

## 5. CLS kaynakları — kod okumasından çıkarılan risk listesi

> **Uyarı:** Bunlar **CLS ölçümü değildir.** Ölçüm yapılmadı. Aşağıdakiler "kutu boyutu render öncesi biliniyor mu?" sorusuna kod düzeyinde verilen cevaplardır.

**Risk YOK (kutu CSS ile sabitlenmiş):** R1–R15, R17, R18, R20. Hepsinde ya `aspect-square` kapsayıcı ya sabit px kutu var. `width`/`height` attribute'unun eksik olduğu R16 (`alpine/cart.ts:640`) bile `w-14 h-14 sm:w-16 sm:h-16` sabit kutu içindedir → kayma üretmez.

**Riskli — kutu belirsiz:**

| Yer | Neden |
|---|---|
| `utils/seller/section-registry.ts:111` | Banner `<img>` yalnızca `heightCls` alıyor, `width`/`height` attr yok, oran sabitlenmiyor. Mağaza şablon motorunun tümü (R19) `decoding` ve `w/h` attr içermiyor. |
| `utils/seller/section-registry.ts:239,280,389,414,573,621,750` | `x-show` ile koşullu; Alpine değerlendirene kadar DOM'da yer tutmuyor olabilir. |
| `pages/seller-dashboard.ts` (66,158,168,257,319,381,405,773,855) | 9 `<img>`de `width`/`height` yok. Dashboard olduğu için CWV alan verisine düşük katkı, yine de düzeltilebilir. |
| `pages/brand.ts:101,138` | Marka logosu — kutu `w-24 h-24 md:w-32 md:h-32` sabit, **risk düşük**; yalnızca attribute eksik. |

`width`/`height` attribute'u eksik toplam 34 `<img>` tespit edildi. **Yöntem:** çok satırlı `<img …>` etiketlerini yakalayan bir regex betiği (`scratchpad/imgaudit.mjs`); betik `${… > …}` içeren şablon ifadelerinde erken kapanabildiği için **2 yanlış pozitif** (`ListingCard.ts:105`, `ProductImageGallery.ts:48`) elle elenmiştir. Gerçek sayı ≈ 32.

---

## 6. Görsel URL'i nasıl üretiliyor — ve bu `srcset`i neden bugün engelliyor

### 6.1 Frontend tarafı: `src/utils/mediaUrl.ts`

Bu dosya **URL üretmez**; API'den gelen hazır yolu **yeniden yazar**.

- `mediaUrl.ts:9` → `const MEDIA_BASE = import.meta.env.VITE_MEDIA_BASE || ""`
- `:11-13` → yalnızca `/files/` veya `/private/files/` ile **başlayan** yollar yeniden yazılır
- `:16-24` → `img.getAttribute("src")` okunur, `sanitizeUrl(MEDIA_BASE + src)` ile geri yazılır
- `:26-38` → inline `style` içindeki `url(/files/…)` da yeniden yazılır
- `:46-79` → `initMediaRewriter()` bir `MutationObserver` kurar; `attributeFilter: ["src", "style"]`
- Çağrı noktası: `src/alpine/index.ts:97`

Amacı (dosya başındaki yorum): GitHub Pages önizlemesinde `/files/` backend'e proxy edilmediği için, orada mutlak backend adresine çevirmek. Docker/üretimde `VITE_MEDIA_BASE` boş → `initMediaRewriter` **hemen return eder** (`:47`), yani üretimde no-op.

> ### ⚠️ Faz 2 için kritik uyarı
> `MutationObserver`'ın `attributeFilter`'ı **`["src", "style"]`** (`mediaUrl.ts:76`). **`srcset` listede YOK.** Ayrıca `rewriteImg` (`:16-24`) yalnız `src` okur.
> Bugün `srcset` eklenirse GitHub Pages önizlemesinde `src` yeniden yazılır ama `srcset` yazılmaz → tarayıcı `srcset`i tercih edeceği için **görseller kırılır**. `srcset` işine başlamadan önce `mediaUrl.ts` de genişletilmelidir. (Bu görevde dosya **değiştirilmedi**; yalnız tespit edildi.)

### 6.2 API tarafı: yol nereden geliyor

`src/services/listingService.ts` API yanıtındaki alanları düz string olarak taşır:
- `:256` → `images: Array.isArray(r.images) ? r.images.map((x) => x.image) : []`
- `:1328` → `const images: ProductImage[] = (raw.images || []).map((src: string, i: number) => …)`
- `:1281-1282` → `imageSrc: raw.imageSrc || undefined, images: raw.images || undefined`

`ListingCard.ts:83-86` gelen değeri şu testle kabul eder: `^(?:https?:)?\/\//` ya da `/` ile başlar ya da `data:image/`. Yani **frontend'in görsel URL'i üzerinde hiçbir dönüşüm yetkisi yok** — ne boyut eki, ne format eki, ne query parametresi. Türev boy seçimi **tamamen backend'in döndürdüğü alan yapısına bağlı**.

### 6.3 Backend tarafı: neden ikinci bir dosya yok

`tradehub_core/media/engine.py`:
- `:117` → `im.thumbnail((max_dim, max_dim))  # yalnız küçültür`
- `:177` → `to_webp()` içinde `im.thumbnail((1920, 1920))`
- `media/presets.py:14-16` → profiller: `safe` = 2560/q90, `balanced` = 2000/q88 (varsayılan), `aggressive` = 1600/q82

Bunlar **tek çıktı üreten** yollar: bir yükleme → bir dosya. Çoklu boy (derivative) üretimi, adlandırma şeması ve saklama yok.

**Sonuç:** `srcset`i frontend'e yazmak Faz 2'nin **ikinci** adımıdır. Birinci adım backend'de türev üretimi + URL sözleşmesidir. Bu envanterin sağladığı şey, o türevlerin **hangi genişliklerde** üretileceğinin kanıta dayalı listesidir (§3.9).

---

## 7. 🔬 ÜRETİMDE ÖLÇÜLECEK

Aşağıdakiler bu makinede **yapılamadı** (Docker kapalı, canlı siteye ve üretim veritabanına erişim yok). Her madde, çalıştırılacak tam komutla verilmiştir.

### 7.1 Lighthouse — 4 sayfa × 2 profil

Repo'da **hazır bir Lighthouse CI yapılandırması zaten var**: `/Users/ahmet/Desktop/istoc/tradehubfront/lighthouserc.cjs`. Şu an 3 URL ve yalnız `desktop` preset içeriyor (`:20-28`). Aşağıdaki koşumlar onu **değiştirmeden**, CLI bayraklarıyla genişletir.

**Ölçülecek 4 sayfa** (bu envanterin kapsadığı ürün-görseli yoğun yüzeyler):

| # | Sayfa | Neden | Beklenen LCP adayı |
|---|---|---|---|
| S1 | `/` (ana sayfa) | En yüksek trafik; vitrin ızgarası + En İyi Fırsatlar | CategoryShowcase bento karosu ya da hero metni (hero **görsel değil**, CSS gradient — `hero/HeroTopSlider.ts:136-139`) |
| S2 | `/pages/products.html?category=…` | Kart ızgarasının en yoğun hali; §3.1'in doğrulaması | Fold-üstü ilk ListingCard görseli (`ListingCard.ts:105`, eager) |
| S3 | `/pages/product-detail.html?id=…` | Tek büyük görsel + zoom + galeri | `renderGalleryMedia` large (`ProductImageGallery.ts:66`, `loading="eager" decoding="sync"`) |
| S4 | Mağaza sayfası (`/magaza/<slug>`) | Şablon motoru (R19) — `w/h` ve `decoding` eksik olan tek ürün yüzeyi | `section-registry.ts:280` karosu |

**2 profil:** `mobile` (Lighthouse varsayılan: Moto G Power emülasyonu, 4x CPU throttle, Slow 4G) ve `desktop`.

```bash
cd /Users/ahmet/Desktop/istoc/tradehubfront

# --- Profil 1: MOBILE (Lighthouse varsayılanı) ---
BASE="https://<URETIM-ALAN-ADI>"     # ör. https://istoc.com
PROD="<GERCEK-URUN-ID>"              # canlı bir listeleme id'si
SHOP="<GERCEK-MAGAZA-SLUG>"

for U in "/" "/pages/products.html?category=kozmetik" "/pages/product-detail.html?id=$PROD" "/magaza/$SHOP"; do
  SLUG=$(echo "$U" | tr '/?&=' '____')
  npx -y lighthouse "$BASE$U" \
    --preset=perf \
    --form-factor=mobile \
    --screenEmulation.mobile \
    --throttling-method=simulate \
    --only-categories=performance \
    --output=json --output=html \
    --output-path="./perf-reports/t004/mobile$SLUG" \
    --chrome-flags="--headless=new"
done

# --- Profil 2: DESKTOP ---
for U in "/" "/pages/products.html?category=kozmetik" "/pages/product-detail.html?id=$PROD" "/magaza/$SHOP"; do
  SLUG=$(echo "$U" | tr '/?&=' '____')
  npx -y lighthouse "$BASE$U" \
    --preset=desktop \
    --only-categories=performance \
    --output=json --output=html \
    --output-path="./perf-reports/t004/desktop$SLUG" \
    --chrome-flags="--headless=new"
done
```

**JSON'dan çıkarılacak metrikler** (her koşum için):

```bash
cd /Users/ahmet/Desktop/istoc/tradehubfront/perf-reports/t004
for f in *.report.json; do
  echo "=== $f"
  npx -y node-jq -r '
    [.audits["largest-contentful-paint"].numericValue,
     .audits["cumulative-layout-shift"].numericValue,
     .audits["total-blocking-time"].numericValue,
     (.audits["uses-responsive-images"].details.overallSavingsBytes // 0),
     (.audits["modern-image-formats"].details.overallSavingsBytes // 0),
     (.audits["efficient-animated-content"].details.overallSavingsBytes // 0)] | @tsv' "$f"
done
```

En kritik iki audit **`uses-responsive-images`** ve **`modern-image-formats`**: srcset ve AVIF eksikliğinin byte cinsinden bedelini bunlar verir. Bu envanterin §3 tablolarıyla çapraz doğrulanması gereken sayı odur.

**LCP elementinin ne olduğu** (tahminle değil, ölçümle):

```bash
npx -y node-jq -r '.audits["largest-contentful-paint-element"].details.items[0].items[0].node.snippet' \
  ./perf-reports/t004/mobile__pages_product-detail.html*.report.json
```

**Mevcut LHCI koşumu** (bütçe kontrolü, 3 tekrar, dosya sistemine rapor):

```bash
cd /Users/ahmet/Desktop/istoc/tradehubfront
LHCI_COLLECT_URL="https://<URETIM-ALAN-ADI>" npx -y @lhci/cli autorun --config=lighthouserc.cjs
# Bütçeler: LCP<2500ms, CLS<0.1, TBT<300ms, perf>=0.8, seo>=0.9  (lighthouserc.cjs:30-36)
# Sert kesme için: LHCI_ASSERT_MODE=strict ekle (lighthouserc.cjs:16)
```

### 7.2 Gerçek CSS kutu genişliklerinin DOM'dan doğrulanması

§3'teki tüm sayılar **hesaplanmıştır, ölçülmemiştir.** Kaydırma çubuğu genişliği, tarayıcı yuvarlaması ve Swiper'ın kesirli `slidesPerView` davranışı sapma yaratır. Doğrulama için canlı sayfada DevTools konsoluna:

```js
// Ürün listeleme sayfası — kart görsel kutusu
[...document.querySelectorAll('.product-grid img')].slice(0,3)
  .map(i => ({ css: i.getBoundingClientRect().width,
               natural: i.naturalWidth,
               dpr: devicePixelRatio,
               israf: (i.naturalWidth / (i.getBoundingClientRect().width * devicePixelRatio)).toFixed(2) }))

// Ürün detay ana görseli (masaüstü)
(() => { const i = document.querySelector('#gallery-main-image img');
  return { css: i.getBoundingClientRect().width, natural: i.naturalWidth,
           dpr: devicePixelRatio, zoomluGerekli: i.getBoundingClientRect().width * 1.85 * devicePixelRatio }; })()

// İlgili ürünler Swiper — kesirli slidesPerView'ün gerçek sonucu
[...document.querySelectorAll('.rp-card')].slice(0,3).map(e => e.getBoundingClientRect().width)

// Ürün detay mobil galerisi
document.querySelector('#pdm-gallery-wrap')?.getBoundingClientRect().width
```

`israf` sütunu > 1.0 olan her satır, o render noktasında gereğinden büyük dosya indirildiğini gösterir; §3.9'daki profil önerisinin doğrudan gerekçesi budur.

**Tüm sayfada aşırı büyük görselleri toplu listele:**

```js
[...document.images]
  .filter(i => i.naturalWidth > i.getBoundingClientRect().width * devicePixelRatio * 1.2)
  .map(i => ({ src: i.currentSrc.split('/').pop(),
               kutu: Math.round(i.getBoundingClientRect().width),
               dosya: i.naturalWidth,
               kat: (i.naturalWidth / (i.getBoundingClientRect().width * devicePixelRatio)).toFixed(1) }))
  .sort((a,b) => b.kat - a.kat)
```

### 7.3 Gerçek görsel dosya boyutu dağılımı

Bu envanter dosya **boyutlarını** içermez — üretim medyasına erişim yok. §3.9'daki profil kararı, gerçek dağılım bilinmeden kesinleşemez.

```bash
# Frappe bench üzerinden (üretim sunucusunda):
bench --site <site> execute frappe.client.get_list \
  --kwargs '{"doctype":"File","filters":{"is_folder":0},"fields":["name","file_url","file_size"],"limit_page_length":0}' \
  > /tmp/dosyalar.json

# Ardından: boyut histogramı + 1920px'e dayanmış master oranı
```

Ölçülmesi gereken 3 sayı:
1. Ürün görsellerinin **medyan** ve **p95** dosya boyutu (KB).
2. Uzun kenarı **tam 1920px** olan dosya oranı — `engine.py:177`'nin tavana dayadığı, yani orijinali daha büyük olan görsellerin payı.
3. Format dağılımı: WebP / JPEG / PNG oranı — `engine.py:132`'nin format-koruma dalı yüzünden JPEG ve PNG'ler WebP'ye **çevrilmiyor**.

### 7.4 Ölçülemeyen ve bu belgede kasıtlı olarak boş bırakılanlar

| Konu | Neden ölçülemedi |
|---|---|
| LCP değeri (ms) | Tarayıcı ve canlı site erişimi yok |
| CLS değeri | Aynı |
| LCP elementinin kimliği | Aynı — §7.1'de tahmin **"beklenen"** olarak işaretlenmiştir, veri değildir |
| Toplam görsel byte'ı / sayfa | Ağ ölçümü gerektirir |
| CDN cache isabet oranı | Altyapı erişimi gerektirir |
| Gerçek DPR dağılımı (kullanıcı tabanı) | RUM/analytics erişimi gerektirir; §3'teki DPR 1/2/3 sütunları **kapasite planı**dır, trafik ağırlığı değildir |

---

## 8. Ek — bu belgedeki her sayının kaynağı

| Sayı | Kaynak |
|---|---|
| Kırılımlar 320/480/640/768/1024 | `tradehubfront/src/style.css:256-260` |
| 2xl = 1536 | `--breakpoint-2xl` tanımlı değil → Tailwind v4 varsayılanı |
| Container 1840px | `tradehubfront/src/style.css:249` |
| Yatay padding 16/32 | `tradehubfront/src/style.css:217,219` + `:1540-1549` |
| Grid gap 16px | `tradehubfront/src/style.css:580` |
| Filtre çubuğu 240/256 | `tradehubfront/src/components/products/FilterSidebar.ts:557` |
| Liste sütunları 2/3/5 | `tradehubfront/src/components/products/ProductListingGrid.ts:94` |
| Ana sayfa sütunları 2/3/4/6/7 | `tradehubfront/src/components/hero/ProductGrid.ts:184` |
| PD galeri kolonları 300/465/590 | `tradehubfront/src/pages/product-detail.ts:261` |
| PD karo rayı 88px | `tradehubfront/src/components/product/ProductImageGallery.ts:212` |
| PD ana görsel tavanı 512px | `tradehubfront/src/components/product/ProductImageGallery.ts:246` |
| PD masaüstü/mobil eşiği 1024px | `tradehubfront/src/pages/product-detail.ts:291` |
| Zoom 1.85× | `tradehubfront/src/components/product/ProductImageGallery.ts:22`, `alpine/product.ts:505` |
| Karo 70px / boşluk 12px | `tradehubfront/src/components/product/ProductImageGallery.ts:86-87` |
| Lightbox karo 52px | `tradehubfront/src/components/product/ProductImageGallery.ts:339` |
| Lightbox sahne min(82vh,720px) | `tradehubfront/src/components/product/ProductImageGallery.ts:322` |
| Swiper 1.4/2.2/3/4/5 | `tradehubfront/src/components/product/RelatedProducts.ts:247-256` |
| Backend master tavanı 1920 | `tradehub_core/media/engine.py:177` |
| Profiller 2560/2000/1600 | `tradehub_core/media/presets.py:14-16` |
| srcset 0, picture 0, sizes 0 | `grep` — §4 tablosundaki komutlar |
| img 183 / lazy 67 / decoding 135 / fetchpriority 1 | `grep` + `scratchpad/imgaudit.mjs` (regex, 2 yanlış pozitif elle elendi) |
| LHCI bütçeleri | `tradehubfront/lighthouserc.cjs:30-36` |
