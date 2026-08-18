# 09 — Slot Bazında Medya İstatistiği ve Politika Uyum Ölçümü

**Tarih:** 2026-08-18
**Ortam:** Docker canlı — `istoc-dev-backend-1`, site `istoc.localhost`, 12 servis ayakta
**Önceki adım:** `08-canli-olcum.md` (dosya düzeyi ölçüm — `tabFile` üzerinden)
**Bu rapor:** Slot düzeyi. Her Faz 2 politikası, bağlı olduğu gerçek `(doctype, field)` verisine uygulandı ve **kaç dosyanın kuralı ihlal ettiği sayıldı**.

> Bu ölçüm olmadan Faz 2 politikaları kâğıt üzerinde kalırdı. Aşağıdaki sayılar **T-028 migration planının doğrudan girdisidir**.

---

## 0. Ölçüm yöntemi ve dürüstlük notları

**Nasıl ölçüldü**

1. `media_engine/policy/slots/*.json` → `bound_to[]` alanlarından `slot_key → (doctype, field)` haritası çıkarıldı.
2. `docs/standards/policies/*.json` → `doctype_field` alanından ikinci harita çıkarıldı.
3. Her `(doctype, field)` için konteynerde `SELECT name, <field> FROM tab<DocType>` çalıştırıldı.
4. `Long Text` alanlarda (`Storefront Layout.sections`, `Listing Variant Item.variant_gallery`) JSON içi URL'ler çıkarıldı.
5. URL'ler diskteki gerçek yola çözüldü (`/files/…` → `sites/istoc.localhost/public/files/…`, `/private/files/…` → `…/private/files/…`).
6. Rasterlar Pillow 12.2.0 (konteyner içi) ile, videolar `/usr/bin/ffprobe` ile açıldı.
7. Her dosyaya, bağlı olduğu slotun `accept` + `require` kuralları tek tek uygulandı.

**Neyi ölçemedim — açıkça**

| Konu | Durum |
|---|---|
| Harici URL'lerin piksel/bayt değerleri | **ÖLÇÜLEMEDİ.** 719 eşsiz referans `cdn.dummyjson.com`, `images.pexels.com`, `images.unsplash.com`, `ui-avatars.com` gibi dış hostlara işaret ediyor. Dosya bizim diskimizde değil; indirmedim (ölçüm ortamı dış ağa çıkarılmadı). |
| PDF/DOCX sayfa boyutları | **ÖLÇÜLEMEDİ.** `document.attachment` altındaki 2 dosya PDF/DOCX. pdfium/poppler kurulu değil; piksel kuralları bunlara uygulanamadı. |
| 7 kayıtta dosya | **DİSKTE YOK.** Alan dolu ama `public/files` altında dosya bulunamadı. |
| `Shipping Channel.icon` | Alan mevcut, **5 kaydın 5'i de boş**. Ölçülecek veri yok. |
| `Listing Review Image`, `Seller Product`, `Shipment Document`, `Data Processing Agreement` | Tablo mevcut ama **0 kayıt**. |
| `Listing Variant Item.variant_video_url` | Alan mevcut, **0 dolu kayıt**. |

**Politika sürümü uyarısı — önemli**

Ölçüm sırasında `media_engine/policy/slots/` dosyaları **eşzamanlı olarak değiştirildi**:

```
seller-logo.json   → 2026-08-18 09:31:22
brand-logo.json    → 2026-08-18 09:32:20
(diğer 7 slot dosyası 2026-08-17 tarihli, değişmedi)
```

Bu iki dosyada JPEG yasağı kaldırıldı (`rejected_extensions`'tan `.jpg`/`.jpeg` çıkarıldı) ve `alpha_channel` `required` → `optional` yapıldı. Rapor **her iki sürüme göre de** sayı veriyor (§4). Diğer slotların sonuçları **2026-08-18 09:33:12** anlık kopyasına dayanıyor.

---

## 1. Slot → alan haritası (çıkarılan)

### 1.A `media_engine/policy/slots/` — 9 slot, 34 alan bağı

| slot_key | bağlı `(doctype, field)` |
|---|---|
| `product.image` | `Listing.primary_image`, `Listing Image.image`, `Listing Variant Item.variant_image`, `Listing Variant Item.variant_gallery` |
| `product.video` | `Listing.video_url`, `Listing Variant Item.variant_video_url` |
| `company.cover_image` | `Admin Seller Profile.banner_image`, `Storefront Layout.sections`, `Seller Gallery Image.poster_image` |
| `company.cover_video` | `Seller Gallery Image.video_url`, `Seller Gallery Image.poster_image` |
| `seller.logo` | `Admin Seller Profile.logo`, `Storefront Layout.sections` (→ *hatalı*, §7-A) |
| `brand.logo` | `Brand.logo` |
| `category.banner` | `Category Showcase Tile.image`, `Brand.hero_banner`, `Seller Category.image` |
| `user.avatar` | `User.user_image` |
| `document.attachment` | 14 alan: `KYB Verification`×6, `KYC Verification.identity_document`, `Seller Application.identity_document`, `Seller Certification.document`, `Seller Verification.document`, `Shipment Document.file`, `Data Processing Agreement.document`, `Order.receipt_url`, `Payment Transaction.receipt_url` |

**Doğrulama sonucu:** 34 alan bağının **34'ü de veritabanında gerçekten mevcut**. Hayalet alan bağı yok. (`SHOW COLUMNS` ile tek tek doğrulandı.)

### 1.B `docs/standards/policies/` — 13 slot, 13 alan

Bu set `media_engine` seti ile **kısmen çakışıyor ve kısmen çelişiyor** (§7-B). Hepsi `doctype_field` alanı taşıyor ve hepsi geçerli bir alana işaret ediyor.

---

## 2. Kapsam özeti

| Ölçüt | Değer |
|---|---|
| Toplam alan referansı (mükerrer dahil) | **6.443** |
| Eşsiz URL | **3.239** |
| — yerel, açıldı ve ölçüldü (raster) | **2.506** |
| — yerel video (ffprobe okundu) | **5** |
| — yerel belge (PDF/DOCX, piksel ölçülemez) | **2** |
| — **harici URL (dosya sunucumuzda değil)** | **719** |
| — kayıt dolu ama diskte dosya yok | **7** |
| Ölçülen yerel dosyaların toplam boyutu | 732,0 MB *(slotlar arası mükerrer sayımlı)* |

**08-canli-olcum.md ile karşılaştırma:** `tabFile` 4.958 kayıt tutuyordu. Slotlara bağlı eşsiz yerel dosya 2.513. Yani **`tabFile`'daki dosyaların yaklaşık yarısı hiçbir tanımlı slota bağlı değil** — bu, 00-upload-slot-envanteri.md §7-B6'daki "kayıtlı olmayan görsel silme adayı olur" riskinin sayısal karşılığıdır.

---

## 3. ANA SONUÇ TABLOSU — `media_engine` slot politikaları

Bir dosya **en az bir kuralı** ihlal ediyorsa "uyumsuz" sayıldı. Harici URL ve diskte olmayan dosya da uyumsuz sayıldı (slot politikası bunları kabul etmiyor).

| slot | eşsiz dosya | uyumlu | uyumsuz | uyumsuzluk % | en sık ihlal nedeni |
|---|---:|---:|---:|---:|---|
| `product.image` | 3.061 | 1.573 | **1.488** | **48,6 %** | harici URL — 668 dosya |
| `document.attachment` | 61 | 3 | **56** | **91,8 %** | `min_short_edge` (1654) altı — 52 dosya |
| `company.cover_image` | 34 | 28 | 6 | 17,6 % | kayıt var, dosya diskte yok — 3 |
| `category.banner` | 32 | 0 | **32** | **100,0 %** | harici URL — 30 dosya |
| `seller.logo` (güncel v2) | 19 | 13 | 6 | 31,6 % | dosya diskte yok — 2 |
| `seller.logo` (dünkü v1) | 19 | 3 | **16** | **84,2 %** | alfa kanalı yok — 13 dosya |
| `company.cover_video` | 6 | 1 | 5 | 83,3 % | harici URL — 4 dosya |
| `user.avatar` | 6 | 0 | **6** | **100,0 %** | harici URL — 6 dosya (hepsi) |
| `product.video` | 5 | 1 | 4 | 80,0 % | oran dışı (16:9 değil) — 3 dosya |
| `brand.logo` (güncel v2) | 1 | 1 | 0 | 0,0 % | — |
| `brand.logo` (dünkü v1) | 1 | 0 | 1 | 100,0 % | yasaklı uzantı `.jpeg` + alfa yok |

> `Seller Gallery Image.poster_image` hem `company.cover_image` hem `company.cover_video` slotuna bağlı olduğu için 2 dosya iki satırda da sayılıyor.

---

## 4. Slot slot detay

### 4.1 `product.image` — EN KRİTİK

**Kurallar:** `min_short_edge=1000`, `min_area=1.000.000`, `allowed_ratios=["1:1","4:5","3:4"]` `tolerans=0,02`, `max_megapixels_hard=80`, `max_bytes=25 MB`, uzantı `.jpg/.jpeg/.png/.webp/.tif/.tiff`

**Sonuç:**

| | dosya | oran |
|---|---:|---:|
| Eşsiz referans | 3.061 | — |
| Harici URL (`cdn.dummyjson.com`) | 668 | 21,8 % |
| Yerel, ölçüldü | 2.393 | 78,2 % |
| **Yerel dosyalardan uyumlu** | **1.573** | **65,7 %** |
| **Yerel dosyalardan uyumsuz** | **820** | **34,3 %** |
| Tüm referanslar üzerinden uyumsuz | 1.488 | 48,6 % |

**İhlal nedenleri** (bir dosya birden fazla neden taşıyabilir):

| neden | dosya |
|---|---:|
| harici URL (dosya sunucuda değil) | 668 |
| `min_short_edge < 1000` | 566 |
| oran dışı (1:1 / 4:5 / 3:4 değil) | 564 |
| `min_area < 1 MP` | 493 |
| `max_bytes` aşımı (>25 MB) | 0 |
| `max_megapixels_hard` aşımı (>80 MP) | 0 |
| kabul dışı uzantı | 0 |

**Alan bazında kırılım** *(dosyalar tabloda soldan sağa tekilleştirildi; bir dosya birden çok alanda kullanılıyorsa ilk alana sayıldı)*:

| alan | eşsiz dosya | yerel ölçülen | harici | uyumlu | uyumsuz | uyumsuzluk % | en sık neden |
|---|---:|---:|---:|---:|---:|---:|---|
| `Listing.primary_image` | 1.312 | 1.118 | 194 | 823 | 489 | 37,3 % | `min_short_edge<1000` |
| `Listing Image.image` | 1.350 | 876 | 474 | 519 | 831 | 61,6 % | harici URL |
| `Listing Variant Item.variant_image` | 283 | 283 | 0 | 156 | 127 | 44,9 % | oran dışı |
| `Listing Variant Item.variant_gallery` | 116 | 116 | 0 | 75 | 41 | 35,3 % | oran dışı |

**Yerel 2.393 dosyanın dağılımı:**

- Format: JPEG 1.844 · PNG 277 · WEBP 272
- Mod: RGB 2.157 · RGBA 170 · P 42 · **CMYK 18** · L 6 · (alfa taşıyan: 209)
- Kısa kenar: p50 **1.138** · p90 2.264 · p99 4.480 · min **55** · max 7.049
- Megapiksel: p50 1,71 · p90 6,00 · p99 29,21 · max **72,71**
- Bayt: p50 74 KB · p90 689 KB · p99 2,66 MB · max 9,95 MB
- Oran (w/h): p50 1,000 · min 0,301 · max 2,591
- Tam kare (1:1 ±0,02): **1.012 dosya (%42,3)**

**Kısa kenar eşik duyarlılığı — T-028 için doğrudan girdi:**

| eşik | altında kalan | oran |
|---|---:|---:|
| < 512 px | 222 | 9,3 % |
| < 800 px | 282 | 11,8 % |
| **< 1000 px (mevcut kural)** | **566** | **23,7 %** |
| < 1200 px | 1.922 | 80,3 % |
| < 1600 px | 2.049 | 85,6 % |
| < 2000 px (standards policy tabanı) | 2.110 | **88,2 %** |
| < 2560 px | 2.177 | 91,0 % |

> **Bu tablo raporun en önemli bulgusudur.** `media_engine` politikası 1000 px istiyor → %23,7 düşüyor (yönetilebilir). `docs/standards/policies/listing.primary_image.json` ise `min_long_edge=2000` istiyor → yerel ürün görsellerinin **%88,2'si** düşer. İki politika seti aynı slot için 8 kat farklı bir eşik dayatıyor; ikisi aynı anda yürürlükte olamaz (§7-B).

**Oran ihlali nerede yoğunlaşıyor** (564 dosya):

| w/h bandı | dosya |
|---|---:|
| 1,02 – 1,35 (hafif yatay) | 153 |
| 0,60 – 0,75 | 141 |
| 1,35 – 1,80 | 140 |
| 0,80 – 0,98 | 64 |
| > 1,80 (çok yatay) | 36 |
| < 0,60 (çok dikey) | 27 |
| 0,75 – 0,80 (3:4'e yakın, toleransın hemen dışı) | 3 |

> `ratio_tolerance` 0,02'den 0,05'e çıkarılsa bile kazanç küçük: toleransın hemen dışında (0,75–0,80 bandı) sadece 3 dosya var. Oran ihlalinin ana gövdesi gerçekten farklı oranlarda çekilmiş görseller — tolerans gevşetmekle değil, **yeniden kırpmayla** çözülür.

**Anomaliler (yerel ürün görselleri içinde):** >20 MP **106** dosya · >50 MP 5 · CMYK **18** · alfa kanallı 209 · >5 MB 1 · >10 MB 0

---

### 4.2 `document.attachment` — kural veriye hiç uymuyor

**Kurallar:** `min_short_edge=1654`, `min_area=3.868.706`, `allowed_ratios=["210:297"]` `tolerans=1`, `max_bytes=10 MB`

**Sonuç:** 61 eşsiz dosya · **uyumlu 3** · **uyumsuz 56 (%91,8)** · piksel kuralı uygulanamayan 2 (PDF/DOCX)

| neden | dosya |
|---|---:|
| `min_short_edge < 1654` | **52** |
| `min_area < 3,87 MP` | 50 |
| oran dışı (210:297 A4) | 33 |
| kayıt var, dosya diskte yok | 2 |
| piksel kuralları uygulanamadı (PDF/DOCX) | 2 |
| harici URL (`www.africau.edu/…/sample.pdf`) | 1 |

**Ölçülen 56 raster:** PNG 35 · JPEG 21 · alfa taşıyan **32** · kısa kenar p50 **800** p90 1.500 p99 3.096 min 198 max 4.160 · MP p50 1,38 max 17,31 · bayt p50 136 KB max 7,55 MB

> **Yorum:** 1654 px kısa kenar = A4 @ 200 dpi. Verinin p50'si 800 px. Bu kural mevcut belgelerin **%93'ünü** reddeder. Kural yanlış değil (KYB belgesi okunabilir olmalı) ama **geriye dönük uygulanamaz** — T-028'de bu slot için "yeni yüklemelerde zorla, mevcutta uyarı" ayrımı şart.
>
> Ayrıca `Order.receipt_url` ve `Payment Transaction.receipt_url` aynı dosyaları paylaşıyor (3'er dosya, birebir aynı boyutlar: 928×…, 4160×… , 6,1 MB / 7,2 MB). Bu, 08 raporundaki "Payment Transaction sızıntısı" bulgusuyla aynı dosya kümesi.

---

### 4.3 `category.banner` — %100 uyumsuz, çünkü veri bizim değil

**Kurallar:** `min_short_edge=480`, `min_area=460.800`, `allowed_ratios=["5:4","3:2","16:9","2:1","5:2","3:1"]` `tolerans=0,12`

**Sonuç:** 32 eşsiz dosya · uyumlu **0** · uyumsuz **32 (%100)**

| neden | dosya |
|---|---:|
| harici URL | **30** (`cdn.dummyjson.com` 23, `images.unsplash.com` 7) |
| oran dışı | 2 |
| `min_area` altı | 1 |

Yerel olan **yalnızca 2 dosya** var (`Brand.hero_banner` 600×600, `Seller Category.image` 679×679). İkisi de kare — banner slotunun izin verdiği hiçbir orana uymuyor.

> Bu slot şu anda **fiilen seed/demo verisiyle doluyor**. Politika ölçülebilir bir gerçekliğe oturmuyor; önce veri yerelleştirilmeli.

---

### 4.4 `user.avatar` — %100 uyumsuz, tek nedenle

**Sonuç:** 6 eşsiz dosya · uyumlu **0** · uyumsuz **6 (%100)** · nedeni: **hepsi harici URL**

- `ui-avatars.com/api/?name=…` — 5 (dinamik üretilen avatar servisi)
- `secure.gravatar.com/avatar/…?d=404` — 1

63 `User` kaydının yalnızca 6'sında `user_image` dolu, hiçbiri yerel dosya değil. `min_short_edge=96` gibi son derece gevşek bir kural bile ölçülemiyor çünkü **ölçülecek yerel dosya yok**.

> Bu bir politika sorunu değil, bir mimari sorun: avatar slotu üçüncü taraf hizmete bağımlı. Medya motorunun bu slot üzerinde bugün **sıfır kontrolü var**.

---

### 4.5 `company.cover_image` — en sağlıklı slot

**Kurallar:** `min_short_edge=400`, `min_area=768.000`, `allowed_ratios=["2:1","5:2","3:1","7:2","4:1","24:5"]` `tolerans=0,12`

**Sonuç:** 34 eşsiz dosya · **uyumlu 28** · uyumsuz **6 (%17,6)**

| neden | dosya |
|---|---:|
| kayıt var, dosya diskte yok | 3 |
| `min_area` altı | 2 |
| `min_short_edge` altı | 1 |
| oran dışı | 1 |
| harici URL | 1 |

**Ölçülen 30 raster:** WEBP 12 · JPEG 11 · PNG 7 · alfa 1 · kısa kenar p50 701 p90 1.778 min 315 max 1.778 · MP p50 1,38 max 6,32 · bayt p50 169 KB p99 1,91 MB · oran p50 **2,701** min 1,00 max 4,897

> Oran p50'si 2,70 — politikanın izin verdiği bandın (2:1 … 24:5 = 4,8) tam ortasında. **Politika burada gerçek veriye oturuyor.** Bu slot Faz 2 standartlarının doğru kalibre edildiği tek örnektir.

---

### 4.6 `seller.logo` ve `brand.logo` — politika ölçüm sırasında değişti

Aşağıdaki tablo, aynı 20 dosyanın iki politika sürümüne göre sonucudur.

| slot | sürüm | uyumlu | uyumsuz | uyumsuzluk % | başlıca nedenler |
|---|---|---:|---:|---:|---|
| `seller.logo` | **v1** (2026-08-17, JPEG yasak + alfa zorunlu) | 3 | 16 | **84,2 %** | alfa yok 13 · yasaklı `.jpg` 7 · `.jpeg` 1 · diskte yok 2 · `aspect_band` dışı 2 · `max_bytes` 1 · `min_short_edge` 1 |
| `seller.logo` | **v2** (2026-08-18 09:31, JPEG serbest + alfa opsiyonel) | 13 | 6 | **31,6 %** | diskte yok 2 · `aspect_band` dışı 2 · `max_bytes` 1 · `min_short_edge` 1 |
| `brand.logo` | **v1** (2026-08-17) | 0 | 1 | 100,0 % | yasaklı `.jpeg` · alfa yok |
| `brand.logo` | **v2** (2026-08-18 09:32) | 1 | 0 | 0,0 % | — |

**`Admin Seller Profile.logo` — 19 dosyanın tamamı (17 ölçüldü, 2 diskte yok):**

| boyut | oran | format | mod | alfa | bayt |
|---|---:|---|---|---|---:|
| 1376×768 | 1,79 | PNG | RGB | hayır | 226,8 KB |
| 1408×768 | 1,83 | PNG | RGBA | **evet** | **1.379,6 KB** ← `max_bytes` (1024 KB) aşımı |
| 2471×2656 | 0,93 | JPEG | RGB | hayır | 200,2 KB |
| 1024×356 | **2,88** | JPEG | RGB | hayır | 11,8 KB ← `aspect_band` (0,5–2,0) dışı |
| 447×447 | 1,00 | JPEG | RGB | hayır | 11,8 KB |
| 1254×1254 | 1,00 | PNG | RGB | hayır | 591,5 KB |
| 1024×1024 | 1,00 | PNG | RGBA | **evet** | 206,3 KB |
| 1046×1046 | 1,00 | PNG | RGBA | **evet** | 159,1 KB |
| 400×400 | 1,00 | PNG | RGB | hayır | 18,9 KB |
| 2048×2048 | 1,00 | JPEG | RGB | hayır | 99,4 KB |
| 1024×356 | **2,88** | JPEG | RGB | hayır | 12,0 KB ← `aspect_band` dışı |
| 1024×1024 | 1,00 | PNG | RGBA | **evet** | 518,7 KB |
| 1254×1254 | 1,00 | PNG | RGB | hayır | 758,8 KB |
| 1080×1080 | 1,00 | JPEG | RGB | hayır | 42,5 KB |
| 400×400 | 1,00 | PNG | RGB | hayır | 36,7 KB |
| **200×200** | 1,00 | JPEG | RGB | hayır | 3,4 KB ← `min_short_edge` (256) altı |
| 1254×1254 | 1,00 | JPEG | RGB | hayır | 62,5 KB |
| *(diskte yok)* | — | — | — | — | — |
| *(diskte yok)* | — | — | — | — | — |

**Ölçülen gerçek:** 17 logodan **yalnızca 4'ü alfa kanalı taşıyor (%23,5)**, **8'i JPEG (%47,1)**, 13'ü tam kare, 2'si 2,88 oranında yatay.

> v1'in "alfa zorunlu" kuralı mevcut logo stokunun **%76,5'ini** reddediyordu. v2'ye geçiş bu veriye bakılarak yapılmışsa doğru bir karardır; ancak `format_priority` içinde `png_with_alpha` hâlâ ilk sırada — yani tercih korunmuş, zorunluluk kaldırılmış. Bu tutarlı.
>
> **Kalan 6 uyumsuzun hiçbiri format kaynaklı değil**: 2 kayıp dosya, 2 aşırı yatay logo (2,88), 1 fazla büyük PNG, 1 çok küçük (200 px) logo. Bunlar tek tek elle düzeltilebilir bir sayıdır.

---

### 4.7 Video slotları

| slot | eşsiz | yerel video | uyumlu | uyumsuz | nedenler |
|---|---:|---:|---:|---:|---|
| `product.video` | 5 | 4 | 1 | 4 (%80) | oran dışı 3 · harici URL 1 (`a.co/d/…` — bu bir Amazon kısaltma linki, video bile değil) · `min_short_edge` 1 · `min_area` 1 |
| `company.cover_video` | 6 | 1 | 1 | 5 (%83,3) | harici URL 4 (`shorturl.at`, `kastamonuplastik.com`, `videos.pexels.com`, `images.pexels.com`) · kabul dışı uzantı `.png` 1 |

**Notlar:**
- `Listing.video_url` 2.735 kayıttan yalnızca **5'inde** dolu. `Listing Variant Item.variant_video_url` 2.911 kayıtta **0** dolu.
- `company.cover_video` slotu `Seller Gallery Image.poster_image` alanını da kapsıyor; oradaki 400×400 PNG doğal olarak video kurallarına takılıyor. **Bu bir `bound_to` hatası** (§7-A) — poster görseli bir video slotunun `accept.extensions` listesine göre değerlendirilemez.
- Video bit hızı / süre dağılımı bu raporda **yeniden ölçülmedi**; 08-canli-olcum.md'deki değerler geçerlidir (23 dosya, 5'i okunabildi, hepsi h264, süre p50 33 sn max 540 sn, bitrate p50 746 kbps).

---

## 5. `docs/standards/policies/` seti — uyum tablosu

Bu set yalnızca `min_long_edge` / `max_long_edge` / `aspect_ratio` kuralı taşıyor.

| slot | alan | dosya | uyumlu | uyumsuz | uyumsuzluk % | en sık neden |
|---|---|---:|---:|---:|---:|---|
| `listing.gallery_image` | `Listing Image.image` | 1.374 | 8 | **1.366** | **99,4 %** | `min_long_edge<2000` — 736 |
| `listing.variant_image` | `Listing Variant Item.variant_image` | 1.082 | 26 | **1.056** | **97,6 %** | harici URL — 611 |
| `listing.primary_image` | `Listing.primary_image` | 1.312 | 36 | **1.276** | **97,3 %** | `min_long_edge<2000` — 1.045 |
| `seller.gallery_image` | `Seller Gallery Image.image` | 41 | 0 | 41 | 100,0 % | harici URL — 33 |
| `category_showcase.tile_image` | `Category Showcase Tile.image` | 7 | 0 | 7 | 100,0 % | harici URL — 7 |
| `brand.hero_banner` | `Brand.hero_banner` | 1 | 0 | 1 | 100,0 % | `min_long_edge<1840` |
| `seo.og_image` | `Static Page SEO.og_image` | 1 | 0 | 1 | 100,0 % | oran dışı (1.91:1; dosya 2000×2000) |
| `seller.logo` | `Admin Seller Profile.logo` | 19 | 7 | 12 | 63,2 % | `max_long_edge>1024` — 9 |
| `seller.banner` | `Admin Seller Profile.banner_image` | 2 | 1 | 1 | 50,0 % | oran dışı (4:1) |
| `brand.logo` | `Brand.logo` | 1 | 1 | 0 | 0,0 % | — |
| `review.image` | `Listing Review Image.image` | 0 | 0 | 0 | — | **0 kayıt** |
| `seller_product.image` | `Seller Product.image` | 0 | 0 | 0 | — | **0 kayıt** |
| `shipping_channel.icon` | `Shipping Channel.icon` | 0 | 0 | 0 | — | **5 kayıt, hepsi boş** |

> Ürün ailesinin üç slotu da **%97'nin üzerinde uyumsuz**. Bu set bugünkü haliyle uygulanamaz.

---

## 6. İki politika seti çelişiyor — sayısal kanıt

Aynı `(doctype, field)` çiftine iki farklı taban dayatılıyor:

| alan | `media_engine` kuralı | uyumsuzluk | `docs/standards/policies` kuralı | uyumsuzluk |
|---|---|---:|---|---:|
| `Listing.primary_image` | kısa kenar ≥ 1000 | **37,3 %** | uzun kenar ≥ 2000 | **97,3 %** |
| `Listing Image.image` | kısa kenar ≥ 1000 | 61,6 % | uzun kenar ≥ 2000 | **99,4 %** |
| `Listing Variant Item.variant_image` | kısa kenar ≥ 1000 | 44,9 % | uzun kenar ≥ 2000 | **97,6 %** |
| `Admin Seller Profile.logo` | kısa kenar ≥ 256, üst sınır 4096 | 31,6 % | 400 ≤ uzun kenar ≤ 1024 | 63,2 % |
| `Brand.logo` | kısa kenar ≥ 256 | 0,0 % | 400 ≤ uzun kenar ≤ 1024 | 0,0 % |

`Admin Seller Profile.logo` örneği çelişkiyi en net gösteriyor: `media_engine` üst sınırı **4096 px**, `standards` üst sınırı **1024 px**. Aynı 17 dosyanın 9'u ikinci kurala takılıyor, birincisine hiçbiri takılmıyor.

**Sonuç: T-028 öncesinde bu iki setten biri kaynak-doğru (source of truth) ilan edilmeli.** Aksi halde migration hangi eşiği uygulayacağını bilemez.

---

## 7. Politika dosyalarında bulunan hatalar

### 7-A `bound_to` hataları (ölçümle doğrulandı)

1. **`seller.logo` → `Storefront Layout.sections` (JSON içinde `header.logo`) — YANLIŞ.**
   34 `Storefront Layout` kaydının tamamı tarandı. `sections` JSON'ında bulunan **tek URL yolu** `[].settings.slides[].image` (32 adet) — yani hero banner slide görselleri. **`header.logo` diye bir anahtar hiç yok.** Bu bağ ölçümde devre dışı bırakıldı.

2. **`company.cover_video` → `Seller Gallery Image.poster_image` — TARTIŞMALI.**
   Poster bir görsel; video slotunun `accept.extensions` (`.mp4/.webm/.mov/.m4v`) listesine göre değerlendirilince otomatik ihlal üretiyor. Poster ayrı bir alt-slot olarak modellenmeli.

3. **`document.attachment` → `Order.receipt_url` + `Payment Transaction.receipt_url`**
   Aynı 3 dosyayı gösteriyorlar (boyutlar birebir aynı). Slot tanımı hatalı değil ama veri mükerrer.

### 7-B Ölçülemeyen ama kayda değer

- `Category Showcase Tile.image` iki farklı slota bağlı (`category.banner` ve `category_showcase.tile_image`) ve iki farklı kural taşıyor.
- `Brand.hero_banner` aynı şekilde `category.banner` ve `brand.hero_banner` slotlarında.

---

## 8. T-028 migration planı için doğrudan girdiler

**Öncelik sırasıyla, sayılarla:**

| # | İş | Etkilenen dosya | Kanıt |
|---|---|---:|---|
| 1 | **Harici URL'leri yerelleştir** — indir, `tabFile`'a kaydet, alanı güncelle | **719 eşsiz referans** (668'i ürün görseli, `cdn.dummyjson.com`) | §2, §4.1 |
| 2 | **Ürün görselini yeniden kırp** — 1:1 / 4:5 / 3:4 dışındakiler | **564 dosya** | §4.1 |
| 3 | **Ürün görselini büyüt/değiştir** — kısa kenar < 1000 | **566 dosya** | §4.1 |
| 4 | **KYB/KYC belge eşiğini yeniden değerlendir** — 1654 px kuralı %93'ü reddediyor | 52 / 56 dosya | §4.2 |
| 5 | **Ölü referansları temizle** — kayıt dolu, dosya diskte yok | **7 kayıt** | §2 |
| 6 | **CMYK → sRGB dönüşümü** (ürün görselleri) | **18 dosya** | §4.1 |
| 7 | **>20 MP ürün görsellerini küçült** | **106 dosya** (5'i >50 MP) | §4.1 |
| 8 | **Logo düzeltmeleri** — 2 aşırı yatay, 1 aşırı büyük, 1 çok küçük, 2 kayıp | 6 dosya | §4.6 |
| 9 | **Avatar mimarisi** — `ui-avatars.com` / gravatar bağımlılığını kaldır | 6 kayıt | §4.4 |
| 10 | **`bound_to` düzeltmeleri** — `seller.logo` ↔ `Storefront Layout.sections` bağını kaldır | — | §7-A |
| 11 | **İki politika setinden birini kaynak-doğru ilan et** | tüm slotlar | §6 |

**Migration'ın "sessizce çalışamayacağı" yerler:** §4.2 (belge eşiği) ve §4.1 adım 2 (yeniden kırpma) insan kararı gerektirir — kırpma ürünün görünüşünü değiştirir, otomatikleştirilemez.

---

## 9. Yeniden üretilebilirlik

- Ölçüm scriptleri: `/tmp/slotmeasure.py` (konteyner içi), `eval2.py` / `detail.py` / `deep.py` (yerel scratchpad)
- Ham ölçüm çıktısı: `slotdata.json` — 3.239 eşsiz URL, her biri için `state / w / h / bytes / fmt / mode / alpha / ext`
- Politika anlık kopyası: 2026-08-18 09:33:12 (`media_engine/policy/` tam kopya)
- Bu rapordaki **hiçbir sayı tahmin değildir**; her biri yukarıdaki scriptlerin çıktısıdır. Ölçülemeyen her şey §0'da açıkça listelenmiştir.
