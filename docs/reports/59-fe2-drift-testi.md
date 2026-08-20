# 59 — T-115: Simülatörün gerçek sayfayla doğrulanması (drift testi)

**Tarih:** 2026-08-20 · **Depo:** `admin-panel` (dal `ahmet`) · **Tür:** yeni test + ölçüm altyapısı
**Kaynak görev:** <https://karacaismail.github.io/imageoptimization/docs/62-faz11-simulator.html> — T-115
**İlgili plan:** `tradehub_core/docs/ui/faz11-simulator.md` §5 (T-115 planı, bugüne kadar **koşulmamıştı**)

> **Bu görevde `tradehubfront` ve `tradehub_core` SALT OKUNDU.** Yazılan dosyaların
> tamamı `admin-panel/frontend` altındadır (bu rapor hariç). `package.json`'a
> **dokunulmadı** — yeni npm bağımlılığı eklenmedi.

---

## 0. Tek sayfada sonuç

| | Sayı |
|---|---:|
| Gerçek tarayıcıda **ölçülen** kutu (cihaz × bölge) | **85** |
| Ölçüm denenen bölge | 12 / 15 |
| Çapraz kontrol (yayındaki imaj, 2 cihaz) | 14 ölçüm, **14'ü birebir aynı** |
| Gerekçesiyle **ölçülmeyen** bölge | 3 / 15 |
| **2px eşiğini aşan satır (DRIFT)** | **25 / 85** |
| **Sapan bölge** | **4 / 8** (ölçülebilen bölgelerin yarısı) |
| **En büyük sapma** | **80,68 px** — `seller_shop/product_grid` @ `ipad-pro-11` |
| Sapması **sıfır** olan bölge | 4 (`listing/card_grid`, `product_detail/{main_image, thumb_rail, lightbox_main}`) |

> ### Katalog gerçek sayfadan SAPIYOR. Dört bölgede, 25 satırda, en fazla **80,68 px**.
>
> Bu sapmalar **gizlenmedi ve test gevşetilmedi**: eşik hâlâ 2px, ölçüm betiği
> canlı koşumda herhangi bir sapmada **1 ile çıkıyor** (CI kırmızısı). `npm test`
> içindeki drift testi sapmaları AÇIK bir hata listesi olarak tutuyor ve liste
> büyürse / bir sapma kötüleşirse / bir sapma sessizce kaybolursa **kırılıyor**.

**Neden bu, `srcsetParity.test.js`'in ölçtüğü şeyden farklı:** parite testi iki
HESABI karşılaştırır (panelin JavaScript'i ↔ `srcset.py`). İkisi de aynı
`placements.json`'u okuduğu için ikisi birden gerçeğe göre yanlış olabilir —
**nitekim öyle çıktı.** 65/195 kombinasyondaki "0 sapma" hâlâ doğru ama
"simülatör doğru kutuyu gösteriyor" demek DEĞİL.

---

## 1. Yöntem — ve neden Playwright kurulmadı

Kabul ölçütü gerçek sayfada `getBoundingClientRect()` ister; bu bir tarayıcı
gerektirir. Üç seçenek vardı, seçilen ve gerekçesi:

| Seçenek | Karar | Gerekçe |
|---|---|---|
| Playwright/Puppeteer kur | ❌ | `admin-panel/frontend`'in `node_modules`'ını **üç ajan paylaşıyor**; oraya yeni bağımlılık eklemek ikisini de etkilerdi. |
| Storefront CSS'inden türet | ❌ | Kataloğu üreten yöntemin ta kendisi bu. Aynı yöntemle doğrulamak, sapmayı **tanım gereği** göremezdi. |
| **Ham CDP + kurulu Chrome** | ✅ | Node 24'ün **yerleşik** `WebSocket`'i + makinedeki Chrome. Gerçek yerleşim motoru, gerçek `getBoundingClientRect()`, **sıfır yeni bağımlılık**. |

Ölçüm gerçekten koştu: 13 cihaz × 5 sayfa, `Emulation.setDeviceMetricsOverride`
ile CSS viewport + DPR uygulanarak.

### 1.1 Kritik bulgu — hangi "gerçek sayfa"?

`http://istoc.localhost`'ta koşan storefront **eski bir derlemedir**. Kanıt:

| | Yayındaki imaj | Yerel `tradehubfront/dist` |
|---|---|---|
| Sepet paketi | `assets/pages-cart-DRqSFbd4.js` | `assets/CartPage-DRARABz6.js` |
| Kaynakta var olan `checkout-item-card` sınıfı | **hiçbir pakette yok** | var |
| `product-card__image-area` | yok | var |

(`docker-compose.yml` `dist/`i bind-mount etmiyor; imajın içinde — bu davranış
zaten biliniyordu.) Yayındaki imaja karşı ölçmek, "katalog yanlış" ile
"derleme eski"yi **birbirine karıştırırdı**. Bu yüzden:

- **Birincil ölçüm** `tradehubfront/dist`'e karşı yapıldı — storefront'un
  GÜNCEL kaynağından üretilmiş derleme. Kataloğun türetildiği kaynağın aynısı,
  dolayısıyla bulunan sapma **kataloğun kendi hatasıdır**, derleme gecikmesi değil.
- Veri katmanı (`/api`, `/files`) gerçek backend'e proxy'lendi, yani iki ölçüm
  aynı ürünleri gördü; fark yalnız CSS/işaretlemeden geliyor.
- `tradehubfront`'a **hiçbir dosya yazılmadı** — `dist/` yalnız okundu.

**Çapraz kontrol koşuldu.** Aynı ölçüm iki cihazda (`iphone-se-3`,
`desktop-1080p`) **yayındaki imaja karşı da** koşturuldu: 14 ölçümün
**14'ünde de** kutu genişliği yerel derlemeyle **birebir aynı** çıktı
(`top_deals` −8,00 / −4,70; `summary_strip` +8,00; `seller_shop` −60,50;
diğerleri 0). Yani aşağıdaki sapmalar **derleme gecikmesinden değil,
kataloğun kendisinden** geliyor — iki bağımsız derlemede aynı sapma ölçüldü.

### 1.2 Ölçüm ortamı

| Alan | Değer |
|---|---|
| Tarayıcı | `/Applications/Google Chrome.app` (headless, `--headless=new`) |
| Hedef | `http://127.0.0.1:<port>` — `tradehubfront/dist` (veri proxy'si `http://istoc.localhost`) |
| Ürün | `/urun/20-adet-alci-tas-boyama-seti-...` (canlı `get_listings` API'sinden, uydurulmadı) |
| Satıcı | `/magaza/SEL-00002` (aynı API yanıtındaki `supplierSlug`) |
| Sepet | `localStorage.tradehub_cart` misafir sepeti olarak tohumlandı (boş sepet özet şeridini basmıyor) |
| Cihazlar | `devices.json`'daki 13 referans cihazın tamamı |

---

## 2. ⭐ SONUÇ — bölge bazında sapma

Tablo `scripts/drift-measure.mjs` çıktısından üretildi, elle yazılmadı.

| Bölge | Ölçülen | Sapan | En büyük \|fark\| | Fark aralığı | Durum |
|---|---:|---:|---:|---|---|
| `home/hero_showcase_grid` | 13 | **4** | **2,01 px** | −2,01 … −2,00 | ⚠ sınırda |
| `home/top_deals` | 13 | **13** | **8,11 px** | −8,11 … −3,72 | ❌ **her cihazda** |
| `listing/card_grid` | 13 | 0 | 2,00 px | −2,00 … 0,00 | ✅ (eşikte) |
| `product_detail/main_image` | 12 | 0 | **0,00 px** | 0,00 | ✅ **birebir** |
| `product_detail/thumb_rail` | 4 | 0 | 0,00 px | 0,00 | ✅ birebir |
| `product_detail/lightbox_main` | 5 | 0 | 0,005 px | ~0 | ✅ birebir |
| `cart_checkout/summary_strip` | 13 | **2** | **8,00 px** | 0,00 … +8,00 | ❌ <380px'te |
| `seller_shop/product_grid` | 12 | **6** | **80,68 px** | −80,68 … −0,67 | ❌ **≥834px'te** |

### 2.1 `seller_shop/product_grid` — 80,68 px (en büyük)

Kataloğun `seller_shell` kapsayıcısı, mağaza sayfasındaki **sol kenar çubuğunu
hiç modellememiş**. Tarayıcıda ölçülen gerçek zincir (1920px):

```
.max-w-[1200px] px-8   → 1200 − 64        = 1136
.flex lg:flex-row gap-5 → sağ sütun         =  896   ← ~240px kenar çubuğu + boşluk DÜŞÜLMEMİŞ
section .p-4 xl:p-6     → 896 − 48         =  846
grid xl:grid-cols-4 gap-4 → (846 − 48) / 4 =  199,50
```

Katalog: `(1136 − 48 − 48) / 4 = 260,00`. **Fark −60,50 px** (masaüstünde),
`ipad-pro-11`'de **−80,68 px**.

> Bir yan bulgu: `placements.json` bu bölgenin kapsayıcısını
> `pages/seller-shop.ts:120`'den, kutusunu `CompanyProfile.ts:806`'dan türetmiş.
> Bunlar **iki ayrı sayfa**: `CompanyProfile` yalnız `seller-storefront.ts`
> tarafından kullanılıyor (`/magaza/<slug>`), `seller-shop.html` ise
> `/magaza/<slug>/dukkan`. Ölçüm `/magaza/<slug>` üzerinde yapıldı, çünkü
> `.product-card__image-area` orada.

### 2.2 `home/top_deals` — 13/13 cihaz

`TopDeals.ts:212` ızgaranın hemen üstüne bir sarmalayıcı koyuyor:

```html
<div class="rounded-md" style="padding: var(--space-card-padding, 16px)">
```

Bu dolgu **token duyarlı**: 375px'te yan başına 8px, 1920px'te 14,08px ölçüldü.
Katalog `boxed` içerik genişliğini doğrudan bölüyor, bu dolguyu hiç düşmüyor —
bu yüzden sapma da viewport'a göre değişiyor (−3,72 … −8,11 px).

### 2.3 `cart_checkout/summary_strip` — yalnız 380px altında

Sepet özetindeki karo `alpine/cart.ts:639`'dan geliyor: `w-14 h-14 sm:w-16
sm:h-16` — **iki basamak** (56 / 64). Kataloğun dayandığı
`components/cart/page/CartSummary.ts:20`'deki `max-[380px]:w-12` (48px) basamağı
`/sepet` sayfasında **render edilmiyor**. Sonuç: 375px ve 360px'te katalog 48
diyor, gerçek kutu 56 — **+8,00 px**.

### 2.4 `home/hero_showcase_grid` — sistematik 2 px

`ListingCard.ts:405` kart sarmalayıcısına `border border-gray-200` koyuyor;
görsel alanı sarmalayıcının içinde olduğu için **ızgara sütunundan 2px
(1px × 2 kenarlık) dar**. 13/13 cihazda sabit −2,00 px; ızgara sütunu kesirli
olduğunda −2,01'e çıkıp eşiği aşıyor. `listing/card_grid` aynı kartı
kullanıyor ama ≥480px'te `border-0` varyantı devreye girdiği için orada sapma yok.

### 2.5 Sapması sıfır olan bölgeler

`product_detail/{main_image, thumb_rail, lightbox_main}` **12+4+5 = 21 ölçümde
tam 0,00 px**. Bu, `faz11-simulator.md` §5'in "masaüstünde ~2–3px kaydırma
çubuğu sapması bekleyin" uyarısının **gerçekleşmediğini** de gösteriyor:
`lightbox_main` yükseklik tabanlı hesabı (`min(82vh, 720) − 84`) dahil tuttu.

> **`lightbox_main` @ iphone-14 = 608px, viewport 390px** gerginliği bu ölçümde
> **doğrulanamadı**: lightbox ≥1024px'te açılıyor, 7 telefon/tablet cihazında
> bölge `OLCULMEDI` olarak kaydedildi. Ölçülen 5 geniş cihazda sapma ~0.
> Yani o gerginlik **kaybolmadı, ölçülemedi** — kutu gerçekten 636px ve
> katalogla birebir; sorun kutunun viewport'tan geniş olmasında, kataloğun
> yanlış olmasında değil.

---

## 3. Ölçülemeyenler — gizlenmedi

| Bölge | Durum | Gerekçe |
|---|---|---|
| `listing/brand_grid` | ÖLÇÜLMEDİ | `/marka/<slug>` gerçek bir marka slug'ı ister; API yanıtındaki ürünlerin `brandSlug` alanı **boş** döndü. |
| `product_detail/lightbox_thumb` | ÖLÇÜLMEDİ | Karo listesi yalnız 2+ görselli üründe doluyor; referans üründe tek görsel var. |
| `cart_checkout/drawer_thumb` | ÖLÇÜLMEDİ | Sepet çekmecesi yalnız başlıktaki düğmeye basılınca açılıyor; akış tetiklenmedi. |
| `home/tailored_grid` | BULUNAMADI | `#ts-product-grid` varsayılan olarak `hidden`; sekme etkileşimi gerekiyor. |
| `product_detail/related_slider` | BULUNAMADI | Referans ürün için ilgili ürün dönmedi (`.rp-card` yok). |
| `cart_checkout/{sku_row, product_item}` | BULUNAMADI | Denenen seçiciler yayındaki işaretlemeyle eşleşmedi. |
| `product_detail/thumb_rail` | 8 cihazda ÖLÇÜLMEDİ | Şerit `min-[1280px]` altında gizli — gerçek davranış, eksik ölçüm değil. |
| `product_detail/lightbox_main` | 7 cihazda ÖLÇÜLMEDİ | Lightbox `<1024px`'te açılmıyor. |

**Süre/FPS iddiası bu raporda YOKTUR** — ölçülmedi.

---

## 4. Üretilen dosyalar

| Dosya | İşi |
|---|---|
| `admin-panel/frontend/scripts/drift-cdp.mjs` | Bağımlılıksız CDP istemcisi (Node yerleşik `WebSocket` + kurulu Chrome) |
| `admin-panel/frontend/scripts/drift-serve.mjs` | `tradehubfront/dist`'i nginx kurallarıyla servis eden geçici sunucu, `/api` proxy'li |
| `admin-panel/frontend/scripts/drift-targets.mjs` | 15 katalog bölgesi ⇄ gerçek DOM seçici eşlemesi + ölçülemeyenlerin gerekçesi |
| `admin-panel/frontend/scripts/drift-measure.mjs` | Ölçüm + karşılaştırma + rapor; **sapma varsa `exit 1`** |
| `admin-panel/frontend/src/lib/media/simulator/__tests__/drift.test.js` | 7 test — `npm test` içinde koşar |
| `.../__tests__/driftBaseline.js` | Bugünkü 4 açık sapmanın gerekçeli kaydı |
| `.../__tests__/fixtures/drift-measurements.json` | 156 satırlık ham ölçüm kanıtı (85 ölçüm + 71 gerekçeli boş satır) (ata zinciri + hesaplanmış CSS dahil) |

### Koşum

```bash
cd admin-panel/frontend

# GECELİK — gerçek tarayıcı, 13 cihaz. Sapma varsa exit 1 (CI kırmızısı).
node scripts/drift-measure.mjs --dist ../../tradehubfront/dist

# yayındaki imaja karşı
node scripts/drift-measure.mjs --base http://istoc.localhost

# tek cihaz / tek bölge
node scripts/drift-measure.mjs --devices iphone-14 --regions home/top_deals --no-write

# PR başına koşan kısım — tarayıcı gerekmez, donmuş ölçümü kataloğa karşı doğrular
npm test
```

`package.json`'a script **eklenmedi** (paylaşılan `node_modules` riski);
komutlar doğrudan `node` ile çağrılıyor.

---

## 5. Kabul ölçütü karnesi

| # | Kaynak kabul ölçütü | Durum |
|---|---|---|
| 1 | "Her cihaz için gerçek sayfa ile simülatör önizlemesi otomatik karşılaştırılıyor (görsel diff)." | ⚠ **KISMİ** — 13 cihazın tamamında **kutu ölçüsü** karşılaştırılıyor (85 ölçüm). **Görsel (piksel) diff YOK** — ekran görüntüsü karşılaştırması yapılmadı. |
| 2 | "Kutu ölçülerinde 2 px üzeri sapma CI'da kırmızı." | ✅ `drift-measure.mjs` sapmada `exit 1`. `npm test` tarafı bugünkü 4 sapmayı hata olarak kayda geçirip **büyümesini** engelliyor. |
| 3 | "Sapma raporunda hangi CSS değişikliğinin sebep olduğu gösteriliyor." | ✅ Her sapan satır ölçülen elemanın etiketini, sınıfını, hesaplanmış CSS'ini ve **4 kuşak ata zincirini** (genişlik / max-width / padding / grid-cols / gap) taşıyor; §2'deki dört kök neden bundan okundu. |
| 4 | "Test her PR'da değil, günlük (nightly) çalışıyor ve ekip bilgilendiriliyor." | ⚠ **KISMİ** — betik gecelik koşacak şekilde ayrıldı ve belgelendi, ama **zamanlanmış iş (cron/CI job) KURULMADI** ve bildirim kanalı **bağlanmadı**. |

### T-110'un eksik kalan kabul ölçütü

> *"Her yerleşim, gerçek uygulamanın CSS breakpoint'leriyle doğrulanmış."*

**Artık ölçüldü — ve 4 bölgede TUTMUYOR.** T-110 §3 şunu söylüyor:
*"Sapma varsa uygulama CSS'i kaynak kabul edilir ve **katalog düzeltilir**."*
Düzeltilecek dosya `tradehub_core/media/pipeline/simulator/placements.json`'dır
ve **bu görevin yazma alanı dışındadır**; §2'deki dört kök neden düzeltme için
yeterli bilgiyi veriyor.

---

## 6. Sıradaki adımlar

| # | İş | Nerede |
|---|---|---|
| 1 | `placements.json`: `seller_shell`'e kenar çubuğu düşümü (~290px) | `tradehub_core` |
| 2 | `placements.json`: `top_deals` adımlarına `--space-card-padding` düşümü | `tradehub_core` |
| 3 | `placements.json`: `summary_strip`'ten 380px basamağını kaldır, `render_point`'i `alpine/cart.ts:639` yap | `tradehub_core` |
| 4 | `placements.json`: kart kenarlığı için 2px `subtract_px` | `tradehub_core` |
| 5 | Gecelik iş + bildirim kanalı (kabul ölçütü §4) | CI yapılandırması |
| 6 | Ekran görüntüsü diff'i (kabul ölçütü §1'in "görsel" kısmı) | ayrı görev |
| 7 | Ölçülemeyen 3 bölge için gerçek marka slug'ı / çok görselli ürün / çekmece akışı | ölçüm verisi |
