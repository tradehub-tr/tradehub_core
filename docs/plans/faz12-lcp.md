# T-122 — Faz 12 LCP planı: sayfa tipi × LCP öğesi × preload × karusel

> **Durum:** plan. Kod tarafı hazır (`tradehub_core/media/pipeline/delivery/picture.py`,
> `sizes.py`), storefront tarafı **uygulanmadı** — depo salt okunur.
> **Ölçüm tabanı:** `docs/reports/03-performans-taban-cizgisi.md` §7 (sabitlenen
> taban çizgisi) + `docs/reports/03-render-envanteri.md` §3 (piksel tablosu).
> **Bu belgedeki türev baytları ÖLÇÜLDÜ** — yöntem §6'da.

---

## 0. Yönetici özeti — 7 madde

1. **Ürün detay sayfasının 13,14 MB'ının 13.759.638 baytı 12 dosyadan geliyor**
   ve bu 12 dosya bu çalışmada tek tek ölçüldü (§6.1). Sayı tahmin değil:
   ölçülen `/files/` payı ile **birebir** eşleşiyor.
2. **13,14 MB'ın sebebi eksik `srcset` değil, karo şeridinin orijinali
   indirmesi.** 12 küçük resim 59×59 px kutuda tam boy master çekiyor
   (`03-performans-taban-cizgisi.md` §7). Türev merdiveni devreye girince aynı
   12 karo `w192` iner: **42.380 B (WebP)** — yani 13,76 MB → 42 KB.
3. **390px telefonda ilk yükleme 61.466 B (WebP) / 73.416 B (AVIF)** olur:
   12×`w192` karo + 1×`w1280` ana görsel. Bugünkü 13.759.638 bayta göre
   **224× azalma**; 900 KB hedefinin **1/15'i**.
4. **Merdivende 768 → 1280 boşluğu var ve tam iPhone 14/15'e denk geliyor.**
   390 CSS × DPR 2 = **780 px**; `w768` 12 piksel yetersiz kalıyor, tarayıcı
   `w1280`e sıçrıyor (fazlalık **1,64×**). Ana görsel 7.650 B yerine 13.833 B
   iniyor — **%81 fazla**. Öneri: `w768` → `w800` (§4.1).
5. **AVIF bugün WebP'den BÜYÜK çıkıyor** çünkü politikada
   `encoder_quality.avif = null` (kalibre edilmemiş) ve adaptif arama AVIF'i
   gereğinden yüksek SSIM'e taşıyor. Aynı SSIM'de ölçüldüğünde AVIF
   **%20 küçük** (§4.2). Kalibrasyon yapılmadan AVIF'i `<picture>`'ın başına
   koymak baytı ARTIRIR.
6. **Dört sayfanın LCP öğesi dört farklı türde** ve ikisi bu motorun
   kapsamı dışında: ana sayfada dış kaynak (Unsplash), mağaza profilinde CSS
   `background-image`. `<picture>`/`srcset` bu ikisini çözmez (§2).
7. **Preload statik olarak yazılamaz.** Storefront SPA; ham HTML'de `<img>`
   sayısı **0** ve LCP görselinin adresi ancak API yanıtından sonra biliniyor.
   Uygulanabilir tek yol `Link:` yanıt başlığı ya da SSR (§3.2).

---

## 1. Sayfa tipi × LCP öğesi (ÖLÇÜLEN)

Kaynak: `03-performans-taban-cizgisi.md` §2.3 Ölçüm A (masaüstü, kısıtsız).

| Sayfa | LCP öğesi (ölçülen) | Tür | Bu motorun kapsamında mı |
|---|---|---|---|
| Ana sayfa | `images.unsplash.com/photo-1441984904996…` (AVIF) | dış `<img>` | ❌ **Hayır** — üçüncü taraf hero |
| Ürün listeleme | `/files/Ekran Görüntüsü - 2026-06-22 10-27-16.png` | kart görseli | ✅ Evet (`listing/card_grid`) |
| Ürün detay | `/files/BLNT2888örn.jpg` | galeri ana görseli | ✅ Evet (`product_detail/main_image`) |
| Mağaza profili | `/images/verified.jpg` | **CSS `background-image`** | ⚠️ Kısmen — işaretleme yok |

### 1.1 İki kapsam dışı durum ve gerçek çözümleri

**Ana sayfa — dış hero.** LCP öğesi bizim medyamız değil; `srcset` üretmek
LCP'yi düşürmez. Yapılabilecek tek şey `<link rel="preconnect">` ile
`images.unsplash.com`'a erken bağlanmak, ya da hero'yu kendi medya hattımıza
almak. **Karar bu görevin kapsamı dışında** — ürün sahibine ait.

**Mağaza profili — CSS arka planı.** `background-image` `srcset` alamaz. İki
seçenek var: (a) `image-set()` ile DPR bazlı seçim (genişlik bazlı değil),
(b) öğeyi `<img>`'e çevirip `<picture>` kullanmak. (b) doğru olanıdır ama
storefront değişikliği gerektirir. Ayrıca `/images/verified.jpg` `/files/`
altında **değil** — bundle'lanmış statik varlık; medya motoru onu hiç görmüyor.

---

## 2. Ürün detay — ana görsel: cihaz × seçilen türev (ÖLÇÜLEN)

LCP kaynağı `/files/BLNT2888örn.jpg`: **199.092 B**, 2684×2959, 7,94 MP.
Kutu genişlikleri `tradehub_core/media/pipeline/delivery/sizes.py` üretiminden, bayt değerleri
gerçek kodlamadan (§6.1).

| Cihaz | CSS kutu | DPR | Gereken | Seçilen | AVIF | WebP | Azalma (AVIF) |
|---|---:|---:|---:|---|---:|---:|---:|
| iPhone SE (375) | 375 | 2 | 750 | `w768` | 7.650 B | 8.460 B | **26,0×** |
| **iPhone 14/15 (390)** | 390 | 2 | **780** | **`w1280`** | 13.833 B | 19.086 B | 14,4× |
| iPhone Pro Max (430) | 430 | 3 | 1290 | `w1920` | 20.682 B | 31.494 B | 9,6× |
| Tablet (768) | 768 | 2 | 1536 | `w1920` | 20.682 B | 31.494 B | 9,6× |
| Masaüstü (1440) | 377 | 1 | 377 | `w384` | 2.987 B | 3.150 B | **66,7×** |
| Masaüstü (1920) | 502 | 2 | 1004 | `w1280` | 13.833 B | 19.086 B | 14,4× |

> **15 piksel, %81 bayt.** iPhone SE (375px) `w768` alıp 7.650 B indirirken,
> 15 piksel daha geniş olan iPhone 14 (390px) `w1280`e sıçrayıp 13.833 B
> indiriyor. Sebep merdivendeki 768→1280 boşluğu; §4.1 bunu kapatıyor.

### 2.1 Hover-zoom masaüstünde bağlayıcı kısıt

`ProductImageGallery.ts:22` → `ZOOM_SCALE = 1.85`. `placements.json` bunu
`demand_multiplier` olarak taşıyor. ≥1536px'te kutu 502 → zoom'lu talep
**929 px @1x, 1858 px @2x**. Yani masaüstünde ana görsel için `w1920` basamağı
**zoom yüzünden** gerekli; LCP için değil. İki farklı ihtiyaç:

- **LCP anında** `w640`/`w1280` yeter (yukarıdaki tablo),
- **zoom açılınca** `w1920` gerekir.

Doğru davranış: LCP için küçük basamağı indir, zoom kaynağını
`pointerenter`de **ayrıca** iste. Bugünkü tek-boy master ikisini de aynı 
dosyayla karşılıyor ve LCP'yi zoom'un bedeliyle ödüyor.

---

## 3. Sayfa sayfa uygulama planı

### 3.1 Öncelik (`priority`) kuralları

| Render noktası | `loading` | `fetchpriority` | `decoding` | Gerekçe |
|---|---|---|---|---|
| PD ana görsel, **ilk slayt** | *(yazılmaz)* | `high` | `sync` | LCP adayı |
| PD ana görsel, slayt 2…n | `lazy` | — | `async` | Görünürde değil |
| PD karo şeridi (12 adet) | `lazy` | — | `async` | 80×80 kutu |
| Listeleme kartı, fold üstü ilk satır | *(yazılmaz)* | `high` | `sync` | LCP adayı |
| Listeleme kartı, kalanı | `lazy` | — | `async` | — |
| Sepet/checkout karoları | `lazy` | — | `async` | Fold altı |

`picture.py` bunu `PictureOptions(priority=…)` ve
`render_many(..., first_is_priority=True)` ile uygular; `priority=True` iken
`loading` özniteliği **hiç yazılmaz** (varsayılan zaten `eager`).

### 3.2 Preload — ölçülen engel ve uygulanabilir yol

**Ölçülen engel:** `03-performans-taban-cizgisi.md` §2.1 — dört sayfanın ham
HTML'inde `<img>` sayısı **0**; §1 — LCP görseli dördünde de "ilk belgede
keşfedilebilir" denetiminden **FAILED**. Storefront istemci-taraflı render.

Bu, `<link rel="preload">`'u `index.html`'e statik yazmayı **imkânsız** kılar:
hangi ürünün hangi görselinin yükleneceği HTML üretilirken bilinmiyor.

Üç uygulanabilir yol, maliyet sırasıyla:

1. **`Link:` yanıt başlığı (önerilen).** Ürün detay rotasına gelen istekte
   backend, `primary_image` alanından türev URL'ini bilir ve yanıta
   `Link: </files/…__w1280.avif>; rel=preload; as=image; imagesrcset="…"; imagesizes="…"`
   ekler. `picture.preload_link()` bu dizgeyi zaten üretiyor; başlığa çevirmek
   `api/delivery.py` tarafında küçük bir iştir. **Uyarı:** `imagesrcset`
   `Link` başlığında da geçerlidir ama tarayıcı desteği `<link>` etiketine göre
   daha dardır — üretimde doğrulanmalı, **ÖLÇÜLMEDİ**.
2. **103 Early Hints.** Aynı başlık, TTFB'den önce. nginx + Frappe zincirinde
   bugün yapılandırılmış değil; ayrı iş.
3. **SSR / ilk boyanın sunucudan gelmesi.** En doğru çözüm, en pahalı iş.
   Faz 12 kapsamı dışında.

**Yol 1 uygulanmazsa** kazanç yine de gerçekleşir (bayt 224× düşer) ama LCP
keşif gecikmesi (JS indir → çalıştır → API → `<img>`) **aynı kalır**. Yani
Faz 12'nin bayt iddiası preload'dan bağımsızdır; **zaman** iddiası değildir.

### 3.3 Karusel: ilk slayt eager

- **PD mobil galeri** (`MobileLayout.ts:144`): bugün zaten `i===0` eager,
  kalanı lazy — doğru davranış, korunmalı. Eklenecek tek şey ilk slayda
  `fetchpriority="high"`.
- **İlgili ürünler Swiper** (`RelatedProducts.ts:85`): tamamı `lazy` —
  doğru, fold altında.
- **Ana sayfa öneri slider'ı** (`RecommendationSlider.ts`): `placements.json`
  bu bölgeyi **dışlıyor** (slayt genişliği çalışma anında hesaplanıyor);
  `sizes` üretilemiyor. Bu bölge için önce DOM ölçümü gerekir — **ÖLÇÜLMEDİ**.

### 3.4 CLS

`03-performans-taban-cizgisi.md` §2.3: mobil ürün listelemede **CLS 0,51**
(eşik 0,25), tek bir kayma olayı, kök neden **ÖLÇÜLEMEDİ** ve trace
"kaynak yüklemesine bağlı değil, SPA iskelet→kart geçişine bağlı" diyor.

Buradan iki sonuç:

1. `width`/`height` yazmak bu 0,51'i **tek başına çözmez** — kayma görsel
   yüklemesinden değil, DOM değişiminden geliyor.
2. Yine de `picture.py` `width`/`height`'i **zorunlu** tutuyor, çünkü §4.3'ün
   ölçtüğü ikinci sorun gerçek: bugün yazılan `width`/`height` değerleri
   **gerçek en-boy oranını yansıtmıyor** (sabit `400×400`, `800×800`);
   sayfayı ayakta tutan şey Tailwind `aspect-*` kapları. Türev üretimi
   `fit: pad` + `target_ratio: 1:1` ile oranı GARANTİ ettiği için, yazılan
   oran artık gerçeği yansıtacak.

---

## 4. Politikaya önerilen iki değişiklik (ölçüme dayalı)

### 4.1 `w768` → `w800` (ya da `w800` ekle)

**Ölçülen sorun:** 390 CSS × DPR 2 = 780 px. `w768` 12 px yetersiz; tarayıcı
kuralı gereği bir üst basamağa (`w1280`) çıkıyor, fazlalık **1,64×**.

**Ölçülen çözüm** (12 PDP dosyasının ortalaması):

| Basamak | AVIF ort. | WebP ort. |
|---|---:|---:|
| `w640` | 34.389 B | 25.815 B |
| `w768` | 46.001 B | 34.912 B |
| **`w800`** | **49.342 B** | **37.557 B** |
| `w880` | 57.850 B | 44.254 B |
| `w1280` | 194.468 B | 160.747 B |

`w800`, `w768`e göre yalnız **%7 daha büyük**; ama 390px telefonda `w1280`
yerine seçildiğinde ana görsel **13.833 B → 7.954 B** (AVIF) düşüyor.

**Kapsanan cihazlar:** 390×2 = 780 ✓, 400×2 = 800 ✓. 430×2 = 860 hâlâ
`w1280`e gider — onun için `w880` gerekir; ama Pro Max zaten DPR 3 kullanıyor
(1290 → `w1920`), o yüzden `w880` bu ölçümde karşılığını bulmuyor.

**Etki (390px telefon, PDP ilk yükleme):**

| Merdiven | AVIF | WebP |
|---|---:|---:|
| Bugünkü (`w768`, `w1280`) | 73.416 B | 61.466 B |
| `w800` eklenmiş | **67.537 B** | **51.322 B** |

### 4.2 `encoder_quality.avif` kalibre edilmeli — bugün `null`

`policy/slots/product-image.json` AVIF kalitesini `null` bırakıyor ve şema bunu
"HENÜZ KALİBRE EDİLMEDİ" diye tanımlıyor. Sonuç ölçüldü: adaptif arama AVIF'i
q=70'te bırakıyor ve AVIF hedeflenen SSIM'in **üstüne** çıkıyor.

`w768` tuvali, 12 gerçek PDP dosyası, SSIM referansı kayıpsız PNG:

| Kodlama | Ort. SSIM | Ort. bayt | WebP q80'e göre |
|---|---:|---:|---:|
| WebP q80 | 0,9922 | 45.188 B | 1,00× |
| AVIF q70 | 0,9954 | 46.001 B | **1,02× (DAHA BÜYÜK)** |
| **AVIF q60** | **0,9929** | **36.298 B** | **0,80×** |
| AVIF q50 | 0,9859 | 24.498 B | 0,54× ✗ SSIM düşük |
| AVIF q40 | 0,9742 | 16.218 B | 0,36× ✗ SSIM düşük |

**Sonuç:** WebP q80 ile *aynı ya da daha iyi* SSIM veren en düşük AVIF kalitesi
**q60**'tır ve orada AVIF **%20 küçüktür**. Kalibrasyon yapılmadan AVIF'i
`<picture>`'ın ilk `<source>`'una koymak, her AVIF destekleyen tarayıcıya
%2 **daha büyük** dosya gönderir.

> **Kapsam uyarısı:** bu ölçüm tek slot (`product.image`), tek basamak (`w768`)
> ve 12 dosya üzerinde yapıldı. `q60` değerini politikaya yazmadan önce
> fixture korpusunun tamamında (`tests/fixtures/`, 34 görsel) ve `graphic`/
> `text` içerik sınıflarında tekrarlanmalı — o sınıflarda SSIM hedefi 0,98/0,99
> ve AVIF'in davranışı **ÖLÇÜLMEDİ**.

---

## 5. Görev metnindeki "product-card (240/320/480/640)" merdiveni

Bu merdiven **depoda yok**; `product.image` politikası
96/192/384/640/768/1280/1920 tanımlıyor. Yine de sorulduğu için ölçüldü.

**390px CSS × DPR 2 = 780 px hedefiyle:**

| Merdiven | Seçilen | Durum |
|---|---|---|
| 240/320/480/640 | **640** | ❌ **YETERSİZ** — 140 px eksik, görsel bulanık basılır |
| 96/…/768/1280/1920 (gerçek) | **1280** | ✅ Yeterli, fazlalık 1,64× |

Ölçülen baytlar (12 PDP dosyası ortalaması, varsayımsal merdiven):

| Basamak | AVIF | WebP | JPEG |
|---|---:|---:|---:|
| c240 | 6.990 B | 5.107 B | 7.428 B |
| c320 | 11.038 B | 8.251 B | 12.222 B |
| c480 | 21.009 B | 16.151 B | 23.496 B |
| c640 | 34.389 B | 25.815 B | 36.315 B |

**Kavram karışıklığı düzeltmesi:** 390px viewport'ta **780 px isteyen şey ürün
kartı değil, ürün detay ana görselidir** (kutu = tam viewport, `§3.6`). Aynı
telefonda ürün **kartı** çok daha küçük bir kutuya oturur ve
`delivery/sizes.py` bunu üretiyor:

| Bölge | 390px'te kutu | DPR 2 talebi | Gerçek merdivende seçilen |
|---|---:|---:|---|
| `home/hero_showcase_grid` | 171 px | 342 px | `w384` (14.675 B AVIF ort.) |
| `home/tailored_grid` | 173 px | 346 px | `w384` |
| `product_detail/main_image` | **390 px** | **780 px** | `w1280` |

Yani "product-card profili + 780 px hedefi" birbirine ait olmayan iki sayı.
Kart için `640` fazlasıyla yeter (`w384` seçilir); ana görsel için `640`
yetmez.

---

## 6. Türev matrisi devreye girince NE OLACAK — ölçülen hesap

### 6.1 Yöntem (yeniden üretilebilir)

1. Ölçülen PDP (`/urun/bonny-erzak-saklama-kabi-1-lt` = `LST-03999`) görselleri
   canlı veritabanından çıkarıldı: 1 `primary_image` + 11 `Listing Image`.
2. Dosyaların diskteki toplamı: **13.759.638 B** — raporun ölçtüğü `/files/`
   payıyla **birebir aynı**. Yani doğru dosya kümesi.
3. Her dosya `tradehub_core/media/pipeline/image/render.py::render_ladder` ile politikadaki
   tüm basamaklarda, AVIF ve WebP olarak **gerçekten kodlandı** (SSIM'li
   adaptif kalite araması dâhil). Ölçüm dosyaları: `_olcum_faz12/olcum.json`,
   `olcum800.json`, `avif_kalibre.json` (depo dışı çalışma dizini).

### 6.2 Sayfa toplamı — 390px telefon, DPR 2

Senaryo: karo şeridi 12 karo (`80px @2x = 160` → `w192`) + ilk slayt ana görsel
(780 → `w1280`).

| | Karo (12×`w192`) | Ana görsel | **Toplam** | Bugüne göre |
|---|---:|---:|---:|---:|
| AVIF | 59.583 B | 13.833 B | **73.416 B** (72 KB) | **187×** |
| WebP | 42.380 B | 19.086 B | **61.466 B** (60 KB) | **224×** |
| WebP + `w800` (§4.1) | 42.380 B | 8.942 B | **51.322 B** (50 KB) | **268×** |

**900 KB hedefi = 921.600 B.** Üç senaryonun üçü de hedefin **1/12'sinden
küçük**.

### 6.3 En kötü hâl — kullanıcı 12 slaydın hepsini kaydırırsa

| Merdiven | AVIF | WebP |
|---|---:|---:|
| Bugünkü (`w1280` ana) | 2.393.197 B (2,28 MB) | 1.971.348 B (1,88 MB) |
| `w800` eklenmiş | 651.685 B (0,62 MB) | 493.064 B (0,47 MB) |

Bu satır §4.1'in asıl gerekçesidir: 12 slaydın hepsi gezildiğinde `w800`
farkı 1,88 MB → 0,47 MB'a iniyor (**4×**). Ana görselde 12 px'lik basamak
boşluğu, tüm galeri gezildiğinde MB'lara dönüşüyor.

### 6.4 Depolama maliyeti

12 dosyanın **tam merdiveni** (politikadaki format ataması: `w96`/`w192` yalnız
WebP, `w384`+ AVIF+WebP):

| | Bayt | Oran |
|---|---:|---:|
| 12 orijinal (ham) | 13.759.638 B | 1,00× |
| 12 dosyanın tüm türevleri | 13.911.443 B | **1,01×** |

Yani türev merdiveni depolamayı **iki katına bile çıkarmıyor** — orijinal
kadar yer tutuyor. Dağılım:

- `w1920`: 7.588.843 B (**%55**)
- `w1280`: 4.262.582 B (**%31**)
- kalan beş basamak: **%14**

> **Karar girdisi:** merdivenin üst iki basamağı deponun **%85'i**. `w1920`
> yalnız hover-zoom (masaüstü) ve Pro Max @3x için gerekiyor. Depolama baskısı
> olursa kesilecek ilk yer burasıdır — `w1920`'yi **istek üzerine** (lazy
> derivative) üretmek, merdivenin geri kalanını üretmekten daha değerli.

---

## 7. ÖLÇÜLMEDİ — bu planın kapatmadıkları

| Konu | Durum | Ne gerekir |
|---|---|---|
| Ana sayfa / listeleme / mağaza sayfalarının dosya kümeleri | **ÖLÇÜLMEDİ** | PDP için yapılan §6.1 yöntemi o üç sayfaya da uygulanmalı |
| Gerçek LCP **süresi** (ms) türev sonrası | **ÖLÇÜLMEDİ** | Türevler üretilip servis edilmeden ölçülemez; `03-performans-taban-cizgisi.md` §6.1 komutu tekrar koşulacak |
| `Link:` başlığıyla preload'ın tarayıcı desteği | **ÖLÇÜLMEDİ** | Üretimde `imagesrcset` başlık desteği doğrulanmalı |
| CLS 0,51'in kök nedeni | **ÖLÇÜLEMEDİ** (§6.4, taban çizgisi raporu) | DOM mutasyon zaman damgası ↔ trace eşleştirmesi |
| AVIF q60'ın diğer içerik sınıflarında geçerliliği | **ÖLÇÜLMEDİ** | `graphic`/`text` sınıflarında (SSIM hedefi 0,98/0,99) tekrar |
| `home/recommendation_slider` kutusu | **ÖLÇÜLEMEDİ** | Slayt genişliği çalışma anında; DOM ölçümü gerekir |
| INP | **ÖLÇÜLEMEDİ** | `delivery/rum.py` alan verisi toplayacak (T-123) |

---

## 8. Kaynaklar

- `docs/reports/03-performans-taban-cizgisi.md` §1, §2.1–2.3, §4.3, §7
- `docs/reports/03-render-envanteri.md` §3.1–§3.9, §4
- `tradehub_core/media/pipeline/policy/slots/product-image.json` — profil merdiveni
- `tradehub_core/media/pipeline/simulator/placements.json` — kutu kuralları
- `tradehub_core/media/pipeline/delivery/picture.py`, `sizes.py` — bu planın kod tarafı
- Ölçüm çıktıları: `_olcum_faz12/olcum.json`, `olcum800.json`, `avif_kalibre.json`
