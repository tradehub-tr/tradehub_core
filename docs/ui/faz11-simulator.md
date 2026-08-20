# Faz 11 — Önizleme simülatörü · uygulama planı

**Kapsam:** T-110 … T-115 (6 görev).
**Durum:** T-110 ve T-112 **kodlandı ve koşuyor**; T-111, T-113, T-114, T-115 **planlandı, yazılmadı**.
**Tarih:** 2026-08-18
**Kaynak görev tanımları:** `https://karacaismail.github.io/imageoptimization/docs/62-faz11-simulator.html`

> **Ölçüm uyarısı.** Bu belgedeki tüm kutu genişlikleri storefront kaynağındaki Tailwind sınıflarından **aritmetik olarak türetildi**; tarayıcıda `getBoundingClientRect()` ile **DOĞRULANMADI**. T-110'un kabul ölçütündeki "Playwright ile ≤2px fark" testi **KOŞULMADI** — planı §5'te. Cihaz `dpr`/`css_viewport` değerleri gerçek donanımda **ÖLÇÜLMEDİ**, standart emülasyon değerleridir.

---

## 0. Ne yapıldı, ne yapılmadı

| Görev | Kaynak dokümandaki başlık | Durum | Dosya |
|---|---|---|---|
| T-110 | Cihaz ve yerleşim kataloğunun veri olarak tanımı | ✅ **veri yazıldı**, ⚠️ Playwright doğrulaması yok | `tradehub_core/media/pipeline/simulator/devices.json`, `tradehub_core/media/pipeline/simulator/placements.json` |
| T-111 | Cihaz çerçevesi ve sayfa şablonu render motoru | ❌ **yazılmadı** — plan §2 | — |
| T-112 | srcset seçim göstergesi ve çözünürlük yeterlilik uyarısı | ✅ **hesap kodlandı**, ⚠️ "indirilecek bayt" kısmı yok | `tradehub_core/media/pipeline/simulator/srcset.py`, `tests/test_simulator_srcset.py` |
| T-113 | Video slotu için poster/oynatma simülasyonu | ❌ **yazılmadı** — plan §3 | — |
| T-114 | Onay kapısı ve `previewed_placements` kaydı | ❌ **yazılmadı** — plan §4 | — |
| T-115 | Simülatörün gerçek sayfayla doğrulanması (drift testi) | ❌ **yazılmadı** — plan §5 | — |

**Neden yalnız ikisi kodlandı:** T-111/113/114 tarayıcıda çalışan bir arayüz ister; storefront (`tradehubfront/`) ve admin panel (`admin-panel/frontend/`) bu görevde **SALT OKUNUR**dur, oraya kod yazılamaz. T-115 çalışan bir simülatör arayüzü olmadan anlamsızdır. Bu yüzden bu fazda **hesap çekirdeği** (bir arayüzün altına konabilecek, arayüzsüz de doğrulanabilir kısım) yazıldı; arayüz katmanının yeri ve sözleşmesi aşağıda belirlendi.

---

## 1. Kodlanan çekirdek — T-110 + T-112

### 1.1 `devices.json` — 13 referans cihaz

| # | id | Sınıf | CSS viewport | DPR | Fiziksel | Neden bu cihaz |
|---|---|---|---|---|---|---|
| 1 | `iphone-se-3` | phone | 375×667 | 2 | 750×1334 | Hâlâ satılan en dar ekran |
| 2 | `galaxy-s23` | phone | 360×780 | 3 | 1080×2340 | Android'in fiili standardı; raporun ilk satırı |
| 3 | `iphone-14` | phone | 390×844 | 3 | 1170×2532 | iOS'un en yaygın gövdesi |
| 4 | `moto-g-power` | phone | 412×823 | **1,75** | 721×1440 | **Lighthouse mobil varsayılanı** — CWV skorları bu cihazda üretilir |
| 5 | `iphone-15-pro-max` | phone | 430×932 | 3 | 1290×2796 | Telefon sınıfının en yüksek piksel talebi |
| 6 | `ipad-mini-6` | tablet | 744×1133 | 2 | 1488×2266 | 768px kırılımının **hemen altı** |
| 7 | `ipad-pro-11` | tablet | 834×1194 | 2 | 1668×2388 | Ürün detay hâlâ mobil düzende → en yüksek tekil talep |
| 8 | `ipad-pro-11-landscape` | tablet | 1194×834 | 2 | 2388×1668 | 1024–1279 bandının tek temsilcisi |
| 9 | `surface-pro-9` | laptop | 1368×912 | **1,5** | 2052×1368 | Windows %150 ölçek — ikinci kesirli DPR |
| 10 | `macbook-air-13` | laptop | 1440×900 | 2 | 2880×1800 | En yaygın dizüstü |
| 11 | `macbook-pro-16` | laptop | 1728×1117 | 2 | 3456×2234 | DPR 2 ile en geniş CSS viewport |
| 12 | `desktop-1080p` | desktop | 1920×1080 | 1 | 1920×1080 | Container'ın 1840px tavanının devreye girdiği ilk genişlik |
| 13 | `desktop-1440p` | desktop | 2560×1440 | 1 | 2560×1440 | Container doyduğu için kutular DEĞİŞMEZ — üst uçta fazladan basamak gerekmediğinin kanıtı |

`physical` alanı elle yazıldı; `tests/test_simulator_srcset.py::test_fiziksel_piksel_css_carpi_dpr` her satırın `round(css × dpr)` ile tuttuğunu doğrular.

### 1.2 `placements.json` — 5 sayfa × 15 bölge

Kutu genişliği **kod değil veridir**. Beş adım türü var, hiçbirinde sayfa adı geçmez:

| Adım | Formül | Kullanan bölge |
|---|---|---|
| `px` | sabit | sepet karoları, PD masaüstü ana görseli, galeri karoları |
| `vw_pct` | kapsayıcı içerik genişliğinin yüzdesi | PD mobil ana görseli (%100) |
| `vh_pct` | `min(pct×vh, cap) − minus` | lightbox ana görseli (**tek yüksekliğe bağlı bölge**) |
| `grid` | `(kapsayıcı − subtract − gap×(cols−1)) / cols` | 7 ızgara |
| `slider` | `(kapsayıcı − space×(perView−1)) / perView` | ilgili ürünler (Swiper) |

Kapsayıcılar da veridir (`boxed`, `pdp_shell`, `pdp_content_col`, `seller_shell`, `viewport`); `pdp_content_col` `base` alanıyla `pdp_shell`'den türer.

**Kapsanan 15 bölge:** `home/{hero_showcase_grid, top_deals, tailored_grid}` · `listing/{card_grid, brand_grid}` · `product_detail/{main_image, thumb_rail, lightbox_main, lightbox_thumb, related_slider}` · `cart_checkout/{summary_strip, sku_row, product_item, drawer_thumb}` · `seller_shop/product_grid`.

**Bilinçli dışlanan 3 bölge** (`excluded_regions`, gerekçesiyle dosyada):

| Bölge | Gerekçe |
|---|---|
| `home/category_bento` | Sütun sayısı çalışma anında `colCls`/`twoXlColCls` değişkenlerinden geliyor (`CategoryShowcase.ts:245`) → statik okumayla **çıkarılamaz**. OLCULMEDI |
| `home/recommendation_slider` | `RecommendationSlider.ts:141` `slidesPerView:"auto"` ile `:52` `xl:!w-[260px]` (!important) 1024–1279'da **çakışıyor**; hangisinin kazandığı ancak tarayıcıda görülür. OLCULMEDI |
| `seller_shop/template_tiles` (R19) | Genişlik `Storefront Layout` JSON'undan geliyor, kaynakta sabit CSS yok. OLCULMEDI |

### 1.3 Rapor doğrulaması — 19/19 tuttu

`docs/reports/03-render-envanteri.md` §3'te **elle** hesaplanmış 19 kutu genişliği, kural motoruyla **birebir** yeniden üretiliyor (`RaporDogrulamasi::test_rapordaki_19_kutu_birebir_uretiliyor`). Örnekler:

| Bölge | Viewport | Rapor | Motor |
|---|---|---|---|
| `home/hero_showcase_grid` | 1920 | 240,0 | **240,000** |
| `listing/card_grid` | 768 | 146,7 | **146,667** |
| `listing/card_grid` | 1920 | 286,4 | **286,400** |
| `product_detail/main_image` | 1536 | 502 | **502,000** |
| `product_detail/related_slider` | 1024 | 157 | **157,000** |
| `product_detail/lightbox_main` | h=1080 | 636 | **636,000** |

> **İki düzeltme yapıldı.**
> 1. **`related_slider` mobil satırları.** Rapor §3.7 mobil satırlarını `≈, ±5px` işaretlemişti; oradaki yaklaşım Swiper'ın gerçek formülüyle uyuşmuyor (360px'te rapor 226, Swiper formülü 230,9). Burada **Swiper'ın gerçek formülü** kullanıldı — aynı formül raporun masaüstü satırlarını (157 / 145,2 / 177,2 / 236,4) **birebir** üretiyor, yani formül doğrulandı, sapma raporun mobil yaklaşımındaydı.
> 2. **`seller_shop/product_grid` §3'te yoktu.** Aynı yöntemle yeni hesaplandı (`pages/seller-shop.ts:120` → `CompanyProfile.ts:786,802`); 1024px ve üstünde kutu **260px'te doyuyor**.

### 1.4 `srcset.py` — tarayıcı seçiminin simülasyonu

Taklit edilen kural (Chrome/Firefox/Safari'nin gözlenen davranışı, `contracts/delivery.py::DeliveryManifest.pick` ile aynı):

```
sizes → kutu (CSS px)  →  kutu × DPR = gereken  →  gerekeni karşılayan EN KÜÇÜK aday
                                                   hiçbiri karşılamıyorsa EN BÜYÜK
```

**Şartname sapması (kasıtlı):** HTML şartnamesi tarayıcıya takdir hakkı verir (ağ durumu, veri tasarrufu, önbellekteki daha büyük aday). Simülatör bunları modellemez; "ideal koşulda hangi basamak" sorusunu cevaplar.

Üretilen dört uyarı: `kaynak_yetersiz`, `asiri_servis` (politikadaki `max_overshoot` aşımı), `zoom_yetersiz` (PD ana görselinde 1,85× hover-zoom), `profil_yok`.

Çalıştırma:

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core
PYTHONPATH=. python3 -m media_engine.simulator.srcset            # 65 kombinasyon
PYTHONPATH=. python3 -m media_engine.simulator.srcset --all --sizes
PYTHONPATH=. python3 -m media_engine.simulator.srcset --source-width 1120
python3 -m unittest tests.test_simulator_srcset -v               # 34 test
```

> **Not:** Konteynerdeki `apps/tradehub_core` kopyasında `tradehub_core/media/pipeline/` ve `tests/` **yok** (farklı checkout). Bu paket saf stdlib + `media_engine.policy` kullanır, `import frappe` içermez; **yerel `python3` ile koşar**, bench gerekmez.

---
## 1.5 ⭐ SONUÇ — 13 cihaz × 5 sayfa = 65 kombinasyon

Aşağıdaki tablo `srcset.py` tarafından **üretildi**, elle yazılmadı. "Kutu" = CSS px, "Gereken" = kutu × DPR (yukarı yuvarlanmış), "Fazlalık" = seçilen / gereken.

```
Cihaz                 | DPR  | Sayfa/Bölge                 | Kutu | Gereken | Seçilen | Genişlik | Fazlalık | Uyarı        
----------------------+------+-----------------------------+------+---------+---------+----------+----------+--------------
iphone-se-3           | 2    | home/hero_showcase_grid     | 164  | 327     | w384    | 384      | 1.17×    | -            
galaxy-s23            | 3    | home/hero_showcase_grid     | 156  | 468     | w640    | 640      | 1.37×    | -            
iphone-14             | 3    | home/hero_showcase_grid     | 171  | 513     | w640    | 640      | 1.25×    | -            
moto-g-power          | 1.75 | home/hero_showcase_grid     | 182  | 319     | w384    | 384      | 1.20×    | -            
iphone-15-pro-max     | 3    | home/hero_showcase_grid     | 191  | 573     | w640    | 640      | 1.12×    | -            
ipad-mini-6           | 2    | home/hero_showcase_grid     | 227  | 454     | w640    | 640      | 1.41×    | -            
ipad-pro-11           | 2    | home/hero_showcase_grid     | 188  | 377     | w384    | 384      | 1.02×    | -            
ipad-pro-11-landscape | 2    | home/hero_showcase_grid     | 180  | 361     | w384    | 384      | 1.06×    | -            
surface-pro-9         | 1.5  | home/hero_showcase_grid     | 209  | 314     | w384    | 384      | 1.22×    | -            
macbook-air-13        | 2    | home/hero_showcase_grid     | 221  | 443     | w640    | 640      | 1.44×    | -            
macbook-pro-16        | 2    | home/hero_showcase_grid     | 224  | 448     | w640    | 640      | 1.43×    | -            
desktop-1080p         | 1    | home/hero_showcase_grid     | 240  | 240     | w384    | 384      | 1.60×    | -            
desktop-1440p         | 1    | home/hero_showcase_grid     | 240  | 240     | w384    | 384      | 1.60×    | -            
iphone-se-3           | 2    | listing/card_grid           | 164  | 327     | w384    | 384      | 1.17×    | -            
galaxy-s23            | 3    | listing/card_grid           | 156  | 468     | w640    | 640      | 1.37×    | -            
iphone-14             | 3    | listing/card_grid           | 171  | 513     | w640    | 640      | 1.25×    | -            
moto-g-power          | 1.75 | listing/card_grid           | 182  | 319     | w384    | 384      | 1.20×    | -            
iphone-15-pro-max     | 3    | listing/card_grid           | 191  | 573     | w640    | 640      | 1.12×    | -            
ipad-mini-6           | 2    | listing/card_grid           | 348  | 696     | w768    | 768      | 1.10×    | -            
ipad-pro-11           | 2    | listing/card_grid           | 169  | 338     | w384    | 384      | 1.14×    | -            
ipad-pro-11-landscape | 2    | listing/card_grid           | 283  | 567     | w640    | 640      | 1.13×    | -            
surface-pro-9         | 1.5  | listing/card_grid           | 198  | 298     | w384    | 384      | 1.29×    | -            
macbook-air-13        | 2    | listing/card_grid           | 213  | 426     | w640    | 640      | 1.50×    | -            
macbook-pro-16        | 2    | listing/card_grid           | 264  | 528     | w640    | 640      | 1.21×    | -            
desktop-1080p         | 1    | listing/card_grid           | 286  | 287     | w384    | 384      | 1.34×    | -            
desktop-1440p         | 1    | listing/card_grid           | 286  | 287     | w384    | 384      | 1.34×    | -            
iphone-se-3           | 2    | product_detail/main_image   | 375  | 750     | w768    | 768      | 1.02×    | -            
galaxy-s23            | 3    | product_detail/main_image   | 360  | 1080    | w1280   | 1280     | 1.19×    | -            
iphone-14             | 3    | product_detail/main_image   | 390  | 1170    | w1280   | 1280     | 1.09×    | -            
moto-g-power          | 1.75 | product_detail/main_image   | 412  | 721     | w768    | 768      | 1.07×    | -            
iphone-15-pro-max     | 3    | product_detail/main_image   | 430  | 1290    | w1920   | 1920     | 1.49×    | -            
ipad-mini-6           | 2    | product_detail/main_image   | 744  | 1488    | w1920   | 1920     | 1.29×    | -            
ipad-pro-11           | 2    | product_detail/main_image   | 834  | 1668    | w1920   | 1920     | 1.15×    | -            
ipad-pro-11-landscape | 2    | product_detail/main_image   | 300  | 600     | w640    | 640      | 1.07×    | zoom_yetersiz
surface-pro-9         | 1.5  | product_detail/main_image   | 377  | 566     | w640    | 640      | 1.13×    | zoom_yetersiz
macbook-air-13        | 2    | product_detail/main_image   | 377  | 754     | w768    | 768      | 1.02×    | zoom_yetersiz
macbook-pro-16        | 2    | product_detail/main_image   | 502  | 1004    | w1280   | 1280     | 1.27×    | zoom_yetersiz
desktop-1080p         | 1    | product_detail/main_image   | 502  | 502     | w640    | 640      | 1.27×    | zoom_yetersiz
desktop-1440p         | 1    | product_detail/main_image   | 502  | 502     | w640    | 640      | 1.27×    | zoom_yetersiz
iphone-se-3           | 2    | cart_checkout/summary_strip | 48   | 96      | w96     | 96       | 1.00×    | -            
galaxy-s23            | 3    | cart_checkout/summary_strip | 48   | 144     | w192    | 192      | 1.33×    | -            
iphone-14             | 3    | cart_checkout/summary_strip | 56   | 168     | w192    | 192      | 1.14×    | -            
moto-g-power          | 1.75 | cart_checkout/summary_strip | 56   | 98      | w192    | 192      | 1.96×    | asiri_servis 
iphone-15-pro-max     | 3    | cart_checkout/summary_strip | 56   | 168     | w192    | 192      | 1.14×    | -            
ipad-mini-6           | 2    | cart_checkout/summary_strip | 64   | 128     | w192    | 192      | 1.50×    | -            
ipad-pro-11           | 2    | cart_checkout/summary_strip | 64   | 128     | w192    | 192      | 1.50×    | -            
ipad-pro-11-landscape | 2    | cart_checkout/summary_strip | 64   | 128     | w192    | 192      | 1.50×    | -            
surface-pro-9         | 1.5  | cart_checkout/summary_strip | 64   | 96      | w96     | 96       | 1.00×    | -            
macbook-air-13        | 2    | cart_checkout/summary_strip | 64   | 128     | w192    | 192      | 1.50×    | -            
macbook-pro-16        | 2    | cart_checkout/summary_strip | 64   | 128     | w192    | 192      | 1.50×    | -            
desktop-1080p         | 1    | cart_checkout/summary_strip | 64   | 64      | w96     | 96       | 1.50×    | -            
desktop-1440p         | 1    | cart_checkout/summary_strip | 64   | 64      | w96     | 96       | 1.50×    | -            
iphone-se-3           | 2    | seller_shop/product_grid    | 148  | 295     | w384    | 384      | 1.30×    | -            
galaxy-s23            | 3    | seller_shop/product_grid    | 140  | 420     | w640    | 640      | 1.52×    | -            
iphone-14             | 3    | seller_shop/product_grid    | 155  | 465     | w640    | 640      | 1.38×    | -            
moto-g-power          | 1.75 | seller_shop/product_grid    | 166  | 291     | w384    | 384      | 1.32×    | -            
iphone-15-pro-max     | 3    | seller_shop/product_grid    | 175  | 525     | w640    | 640      | 1.22×    | -            
ipad-mini-6           | 2    | seller_shop/product_grid    | 216  | 432     | w640    | 640      | 1.48×    | -            
ipad-pro-11           | 2    | seller_shop/product_grid    | 235  | 471     | w640    | 640      | 1.36×    | -            
ipad-pro-11-landscape | 2    | seller_shop/product_grid    | 258  | 517     | w640    | 640      | 1.24×    | -            
surface-pro-9         | 1.5  | seller_shop/product_grid    | 260  | 390     | w640    | 640      | 1.64×    | -            
macbook-air-13        | 2    | seller_shop/product_grid    | 260  | 520     | w640    | 640      | 1.23×    | -            
macbook-pro-16        | 2    | seller_shop/product_grid    | 260  | 520     | w640    | 640      | 1.23×    | -            
desktop-1080p         | 1    | seller_shop/product_grid    | 260  | 260     | w384    | 384      | 1.48×    | -            
desktop-1440p         | 1    | seller_shop/product_grid    | 260  | 260     | w384    | 384      | 1.48×    | -            
```

### Özet sayılar

| Ölçü | Değer |
|---|---|
| Toplam kombinasyon | **65** |
| **Kaynak yetersizliği (sınırsız kaynak)** | **0 / 65** |
| Aşırı servis (`max_overshoot` = 1,85 aşımı) | **1 / 65** |
| Zoom yetersizliği (1,85× hover-zoom) | **6 / 65** |
| Ortalama fazlalık | **1,30×** |
| En yüksek fazlalık | **1,96×** |
| Seçilen basamak dağılımı | w640: 25 · w384: 17 · w192: 9 · w768: 4 · w96: 4 · w1280: 3 · w1920: 3 |

### Kaynak yetersizliği kaç kombinasyonda çıkıyor?

Merdivenin kendisi (96…1920) **65 kombinasyonun hepsini karşılıyor: 0 yetersizlik.** Yetersizlik, merdivenden değil **kaynak görselden** gelir. Canlıda ölçülen kısa kenar yüzdelikleriyle (`docs/reports/02-medya-istatistigi.md`: p50 = 1.120 px, p90 = 2.160 px) FR-028 upscale yasağı uygulandığında:

| Kaynak genişliği | Yetersiz kombinasyon | Hangileri |
|---|---|---|
| sınırsız (ideal) | **0 / 65** | — |
| **1.120 px (p50)** | **4 / 65** | `iphone-14`, `iphone-15-pro-max`, `ipad-mini-6`, `ipad-pro-11` → hepsi `product_detail/main_image` |
| 2.160 px (p90) | **0 / 65** | — |

15 bölgenin tamamı (195 kombinasyon) koşulduğunda p50 kaynakla yetersizlik **12 / 195**'e çıkar; eklenen 8'in hepsi `product_detail/lightbox_main`.

**Okunuşu:** ürün görsellerinin **yaklaşık yarısı** (kısa kenarı p50'nin altındakiler), ürün detay ana görselinde modern telefon ve tabletlerde **bulanık** basılacak. Bu bir merdiven kusuru değil, **kaynak kalitesi** kusurudur — çözümü `product-image.json`'daki `master.min_long_edge` kapısının yüklemede uygulanması (Faz 2 politikası, bugün `upload_policy.check()` slot bilmiyor: `docs/reports/00-upload-slot-envanteri.md` §7-B B1).

### Üç somut bulgu

**B1 — Merdivenin ALT ucunda basamak eksik.** `cart_checkout/sku_row` (36–40px kutu) DPR 1 masaüstünde 36px istiyor, en küçük basamak 96px → **2,40× fazlalık**, politikadaki 1,85 tavanının üstünde. `moto-g-power`'da `summary_strip` 1,96×. Ürün görselinin merdiveni **48px'lik bir basamakla** başlamalı ya da sepet karoları için ayrı bir mikro profil tanımlanmalı. (Bayt etkisi küçük ama tavanı politika koydu, ölçüm tavanı aşıyor — sessiz geçilemez.)

**B2 — Hover-zoom `srcset` ile çözülemez.** `ProductImageGallery.ts:22` `ZOOM_SCALE = 1.85`. Tarayıcı `sizes`'ı görür, `transform: scale()`'i görmez: 1024px ve üstündeki **6 cihazın hepsinde** seçilen türev zoom'da yetersiz kalıyor. `sizes`'a 1,85 yazmak da çözüm değildir — o zaman zoom açılmayan %95 ziyaretçiye 1,85 kat bayt iner. **Doğru çözüm:** zoom açıldığında JS'in `w1920` türevini ayrıca indirmesi (ikinci istek). Bu, storefront tarafında bir değişikliktir ve bu depodan yapılamaz — Faz 12/13'e taşınmalı.

**B3 — `sizes` tek bir `Xvw` ile yazılamaz.** `listing/card_grid` kutusu viewport ile **monoton artmıyor**: 640px'te 296px, 768px'te 146,7px'e **düşüyor** (aynı anda 3 sütuna geçip 240px filtre çubuğu açılıyor). Bu yüzden `sizes` kırılım başına ayrı ifade gerektirir ve **elle yazılırsa kaçınılmaz olarak yanlış olur.**

### Üretilen `sizes` dizgeleri (T-112 çıktısı)

`sizes_attribute()` bunları `placements.json`'dan üretir; CSS kırılımı değişince otomatik değişir.

```
product_detail/main_image
  (min-width: 1536px) 502px, (min-width: 1280px) 377px, (min-width: 1024px) 300px, 100vw

listing/card_grid
  (min-width: 1536px) calc((min(100vw, 1840px) - 64px - 344px) / 5),
  (min-width: 1280px) calc((min(100vw, 1840px) - 32px - 344px) / 5),
  (min-width: 1024px) calc((min(100vw, 1840px) - 32px - 312px) / 3),
  (min-width: 768px)  calc((min(100vw, 1840px) - 32px - 296px) / 3),
                      calc((min(100vw, 1840px) - 32px - 16px) / 2)

cart_checkout/summary_strip
  (min-width: 480px) 64px, (min-width: 380px) 56px, 48px
```

> ⚠️ **`sizes` yazılmadan önce yapılması gereken:** `tradehubfront/src/utils/mediaUrl.ts:76` `MutationObserver` `attributeFilter`'ı `["src","style"]` — **`srcset` listede YOK** ve `rewriteImg` (`:16-24`) yalnız `src` okur. GitHub Pages önizlemesinde `srcset` yazılırsa `src` yeniden yazılır, `srcset` yazılmaz → tarayıcı `srcset`i tercih eder → **görseller kırılır**. Bu dosya storefront'ta; bu depodan değiştirilemez.

---

## 2. T-111 — Cihaz çerçevesi ve sayfa şablonu render motoru (PLAN)

**Kabul ölçütü (kaynak doküman):** sayfalar **gerçek CSS genişliğinde** render edilir, sonra `transform: scale()` ile ekrana sığdırılır — **reflow olmadan**. Ölçek yüzdesi kullanıcıya görünür. Sayfa şablonları gerçek grid mantığını taklit eder. 13×5 kombinasyonun tamamı hatasız render olur, cihaz matrisi modunda ilk boyama **< 1,5 sn**.

**Nereye yazılacak.** Storefront ve admin panel bu görevde salt okunur. Simülatör arayüzü **admin panel içinde bir Vue görünümü** olmalıdır (yükleme onayı orada verilecek — T-114), ama o depo bu görevde dokunulamaz olduğu için sıra şudur:

1. Bu depoda **veri + hesap** hazır (bitti).
2. Bir Frappe whitelisted endpoint bu veriyi servis eder: `tradehub_core/media/pipeline/api/simulator.py` → `get_preview_matrix(slot_key, file_url)` → `{devices, placements, selections, sizes}`. `Selection.to_dict()` zaten bu şekli üretiyor.
3. Admin panel görünümü o JSON'u tüketir. **Panel değişikliği ayrı bir görev olarak açılmalı** (bu faz kapsamı dışında).

**Kritik tasarım kuralı — reflow yasağı.** Çerçeve `width: 390px` verilip `transform: scale(0.6)` uygulanmalıdır; `zoom` CSS özelliği ya da kapsayıcıyı daraltmak **YANLIŞTIR**: ikisi de layout'u yeniden hesaplatır, o zaman 390px'lik cihazın gerçek kırılımı değil, 234px'lik sahte bir kırılım simüle edilir. Ölçek yüzdesi (`%60`) kullanıcıya yazılmalı ki gördüğü boyutun gerçek boyut olmadığı belli olsun.

**< 1,5 sn ilk boyama için.** 65 çerçevenin hepsi aynı anda `<iframe>` olarak açılırsa hedef tutmaz. Öneri: çerçeveler `IntersectionObserver` ile görünür olunca mount edilir (storefront'ta zaten kanıtlanmış desen: `hero/ProductGrid.ts:61-110`), görünmeyenler `aspect-ratio` ile yer tutar. **Ölçülmedi** — bu bir tasarım önerisidir, 1,5 sn hedefinin tutup tutmadığı ancak arayüz yazıldıktan sonra ölçülür.

---

## 3. T-113 — Video slotu için poster/oynatma simülasyonu (PLAN)

**Kabul ölçütü:** poster çerçevelemesi, otomatik oynatma davranışı, `muted`/`loop`, kontrol yerleşimi gösterilir. Mobil veri senaryosunda **ilk 10 saniyenin tahmini baytı** standartla karşılaştırılır. `prefers-reduced-motion` için ayrı önizleme. Kapağın üstüne binen UI öğeleri **güvenli alan ihlali** uyarısı üretir.

**Hazır olan girdiler (yeniden yazılmayacak):**

| İhtiyaç | Zaten var |
|---|---|
| Poster profilleri | `policy/slots/company-cover-video.json` → `poster_1280` (1280×720), `poster_854`, `thumb_192`; `product-video.json` → `poster_192`, `poster_1024` |
| Poster üretimi | `tradehub_core/media/pipeline/video/poster.py` |
| Bit hızı / süre kararı | `tradehub_core/media/pipeline/video/decision.py` + `policy/video_decision.json` |
| Transcode | `tradehub_core/media/transcode.py` (VP9/Opus + retry) — **sarılır, yeniden yazılmaz** |

**Yapılacak iş:** `tradehub_core/media/pipeline/simulator/video.py` — `simulate_video(slot_key, device, duration_s, bitrate_kbps)` → poster kutusu (mevcut `box_width` ile, `slot_key` = `company.cover_video`), ilk 10 sn bayt tahmini (`bitrate × 10 / 8`), `autoplay` politikası ve güvenli alan kontrolü.

**Ön koşul — yeni yerleşim verisi gerekiyor.** Bugünkü `placements.json` yalnız `product.image` bölgeleri içeriyor. Video için en az iki bölge eklenmeli: `seller_shop/cover_video` (`StoreHeader.ts` `aspect-video` kutusu) ve `product_detail/gallery_video`. **İkisinin de CSS kutusu bu görevde okunmadı — OLCULMEDI.**

**Güvenli alan kontrolü için gereken veri de yok:** kapağın üstüne hangi UI öğesinin bindiği, storefront bileşenlerinin `absolute` yerleşiminden okunmalı. Bu bir sonraki okuma turudur.

---

## 4. T-114 — Onay kapısı ve `previewed_placements` kaydı (PLAN)

**Kabul ölçütü:** kullanıcı onaydan önce **tüm yerleşim sınıflarını** görür. Görünürlük takibi (**ekranda ≥%50, ≥1 sn**) hangi yerleşimin görüldüğünü kaydeder. Uyarı üreten yerleşimler **açık onay kutusu** ister. Sunucu tarafı, gerekli `previewed_placements` olmadan yayımı **reddeder**. Denetim kaydı kullanıcı, zaman damgası ve görülen yerleşimleri tutar.

**Veri modeli önerisi.** `tradehub_core/media/pipeline/doctype_specs/media_asset.json` genişletilir (yeni DocType açmak yerine — varlık başına tek gerçek kaynak):

| Alan | Tip | İçerik |
|---|---|---|
| `previewed_placements` | Long Text (JSON) | `[{"page":"listing","region":"card_grid","device":"iphone-14","ts":"…","dwell_ms":1240}]` |
| `preview_warnings_acknowledged` | Long Text (JSON) | onaylanan uyarı kodları: `kaynak_yetersiz`, `asiri_servis`, `zoom_yetersiz` |
| `preview_gate_passed` | Check | sunucu tarafı kapının sonucu (istemci bunu yazamaz) |

**Sunucu tarafı kapı — tek doğruluk noktası.** İstemcinin gönderdiği listeye güvenilmez; sunucu **kendi** hesaplar:

```
zorunlu = { (page, region) | region.lcp_candidate == True, slot_key = varlığın slotu }
eksik   = zorunlu − previewed_placements
uyarili = simulate_matrix(...) içinde warnings != () olan yerleşimler
reddet  eğer  eksik ≠ ∅  ya da  (uyarili − acknowledged) ≠ ∅
```

`lcp_candidate` bayrağı `placements.json`'da **zaten tanımlı** (5 bölgede `true`) — kapı için ayrı bir liste tutulmaz.

**Mevcut kapılarla ilişki (kural 8).** `tradehub_core/media/gates.py` "dosyaya dokunulsun mu", `PolicyEngine.evaluate()` "kabul edilsin mi" sorusuna cevap veriyor. Bu üçüncü kapı **"yayımlansın mı"** sorusudur; ikisinin yerine geçmez, sonrasına eklenir. Denetim kaydı için `tradehub_core/media/av.py`'nin kullandığı denetim yolu izlenmeli, yeni bir günlük mekanizması kurulmamalı.

**Risk.** Görünürlük takibi (≥%50, ≥1 sn) istemci tarafındadır ve **kandırılabilir**. Sunucu bunu kanıt değil **beyan** olarak ele almalı; kapının gerçek gücü "gördüm" beyanının denetim kaydına yazılmasından gelir, teknik zorlamadan değil. Bu sınır belgede açıkça durmalı ki kapı olduğundan güçlü sanılmasın.

---

## 5. T-115 — Drift testi (PLAN) · ve T-110'un eksik kalan kabul ölçütü

**Kabul ölçütü:** gerçek sayfalarla simülatör önizlemeleri arasında otomatik görsel karşılaştırma. Kutu ölçülerinde **2 px'i aşan sapma CI'ı düşürür**. Drift raporu hangi CSS değişikliğinin sapmaya yol açtığını gösterir. **Gecelik** koşar (PR başına değil), takıma bildirir.

Bu, T-110'un da eksik kalan kabul ölçütüdür: *"Playwright ile gerçek uygulama ölçümleri katalog hesabıyla karşılaştırılır; 2 pikseli aşan fark testi düşürür."* **Bu görevde koşulmadı.** Koşulması için gereken tam komut:

```bash
# 1) Ölçüm betiği — storefront'a DOSYA YAZMADAN, Playwright ile
cd /Users/ahmet/Desktop/istoc/tradehubfront
npx -y playwright@latest install chromium

# 2) Her cihaz × bölge için gerçek kutuyu oku (aşağıdaki seçiciler
#    placements.json'daki render_point alanlarından gelir)
node - <<'JS'
const { chromium } = require('playwright');
const devices = require('/Users/ahmet/Desktop/istoc/tradehub_core/tradehub_core/media/pipeline/simulator/devices.json').devices;
const SECICILER = {
  'home/hero_showcase_grid':      '#product-grid .product-card__image-area',
  'listing/card_grid':            '.product-grid .product-card__image-area',
  'product_detail/main_image':    '#pd-hero-gallery img',
  'cart_checkout/summary_strip':  '[data-cart-summary] img',
  'seller_shop/product_grid':     '.product-grid .product-card__image-area',
};
const URLLER = {  // GERÇEK id/slug ile doldurulacak — uydurulmadı
  home: '/', listing: '/pages/products.html',
  product_detail: '/pages/product-detail.html?id=<GERCEK-ID>',
  cart_checkout: '/sepet', seller_shop: '/magaza/<GERCEK-SLUG>',
};
const BASE = process.env.BASE || 'http://istoc.localhost';
(async () => {
  const b = await chromium.launch();
  for (const d of devices) {
    const ctx = await b.newContext({
      viewport: { width: d.css_viewport.width, height: d.css_viewport.height },
      deviceScaleFactor: d.dpr,
    });
    const p = await ctx.newPage();
    for (const [anahtar, sec] of Object.entries(SECICILER)) {
      const [sayfa] = anahtar.split('/');
      await p.goto(BASE + URLLER[sayfa], { waitUntil: 'networkidle' });
      const el = await p.$(sec);
      if (!el) { console.log(`${d.id}\t${anahtar}\tSECICI_BULUNAMADI`); continue; }
      const r = await el.boundingBox();
      console.log(`${d.id}\t${anahtar}\t${r.width.toFixed(2)}`);
    }
    await ctx.close();
  }
  await b.close();
})();
JS
```

```bash
# 3) Karşılaştır — 2px eşiği
cd /Users/ahmet/Desktop/istoc/tradehub_core
PYTHONPATH=. python3 - <<'PY'
import sys
from media_engine.simulator.srcset import box_width, load_devices, load_layout
cihazlar = {d.id: d for d in load_devices()}
L = load_layout()
kirik = 0
for satir in sys.stdin:
    cid, anahtar, olculen = satir.rstrip("\n").split("\t")
    if olculen == "SECICI_BULUNAMADI":
        print(f"ATLANDI {cid} {anahtar}"); continue
    sayfa, bolge = anahtar.split("/")
    hesap = box_width(L.region_of(sayfa, bolge), cihazlar[cid], L)
    fark = abs(hesap - float(olculen))
    if fark > 2.0:
        kirik += 1
        print(f"DRIFT {cid} {anahtar}: hesap={hesap:.2f} olculen={olculen} fark={fark:.2f}")
print(f"drift sayisi: {kirik}")
sys.exit(1 if kirik else 0)
PY
```

**Bilinen tuzak — kaydırma çubuğu.** `placements.json` container formülü kaydırma çubuğunu (masaüstünde ~15px) **yok sayar**; Playwright'ın `boundingBox()`'ı saymaz. Masaüstü satırlarında sistematik olarak ~2–3px sapma beklenir ve bu **gerçek bir drift değildir**. İki seçenekten biri seçilmeli ve belgeye yazılmalı: (a) eşiği masaüstünde 4px'e çıkar, ya da (b) `devices.json`'daki `scrollbar_px` alanını hesaba kat. Alan **zaten var ama uygulanmıyor** — bilinçli, çünkü hangisinin doğru olduğu ölçümden önce bilinemez.

**Gecelik koşum.** Depoda hazır Lighthouse CI yapılandırması var (`tradehubfront/lighthouserc.cjs`); drift testi onun yanına, ayrı bir gecelik iş olarak konmalı. **PR başına koşturulmamalı** — Playwright + 13 cihaz × 5 sayfa PR döngüsünü yavaşlatır ve zaten drift, PR'da değil zamanla birikir.

---

## 6. Sıradaki adımlar — bağımlılık sırasıyla

| Sıra | İş | Ön koşulu | Bu depoda yapılabilir mi |
|---|---|---|---|
| 1 | Playwright drift ölçümü (§5) — katalog ±2px doğrulaması | Docker açık + gerçek ürün id/slug | ✅ betik burada, koşum burada |
| 2 | `tradehub_core/media/pipeline/api/simulator.py` — matris endpoint'i | 1 | ✅ |
| 3 | Video yerleşimlerinin CSS'ten okunması (T-113 ön koşulu) | — | ✅ (okuma) |
| 4 | Merdivenin alt ucuna `w48` basamağı (B1) | ölçüm 1 | ✅ `policy/slots/product-image.json` |
| 5 | Admin panel simülatör görünümü (T-111) + onay kapısı (T-114) | 2 | ❌ **admin panel salt okunur** — ayrı görev |
| 6 | Storefront `srcset`/`sizes` + `mediaUrl.ts` genişletmesi | 2, 4 | ❌ **storefront salt okunur** — ayrı görev |
| 7 | Zoom için ikinci istek (B2) | 6 | ❌ storefront |

---

## 7. Üretilen dosyalar

| Dosya | Satır | İçerik |
|---|---|---|
| `tradehub_core/media/pipeline/simulator/__init__.py` | 35 | paket yolları + `IMPLEMENTED` bayrağı |
| `tradehub_core/media/pipeline/simulator/devices.json` | — | 13 cihaz (T-110) |
| `tradehub_core/media/pipeline/simulator/placements.json` | — | 5 sayfa · 15 bölge · 5 kapsayıcı · 3 dışlanan bölge (T-110/T-111 verisi) |
| `tradehub_core/media/pipeline/simulator/srcset.py` | 843 | seçim motoru + `sizes` üretimi + tablo + CLI (T-112) |
| `tests/test_simulator_srcset.py` | 396 | 34 test — veri bütünlüğü, rapor doğrulaması (19/19), seçim kuralı, upscale yasağı, `sizes`, 65 kombinasyon tablosu |
| `docs/ui/faz11-simulator.md` | — | bu belge |
