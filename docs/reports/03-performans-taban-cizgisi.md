# 03 — LCP / Performans Taban Çizgisi

**Görev:** T-004 · **Dalga:** 3 · **Tarih:** 2026-08-18
**Amaç:** Faz 12'nin "önce/sonra" karşılaştırmasının dayanacağı ölçülmüş taban çizgisi.

> **Sayı politikası.** Bu belgedeki her sayı bu oturumda ölçüldü. Ölçülemeyen
> her şey açıkça **ÖLÇÜLEMEDİ** olarak işaretlendi. Tahmin, benzetme veya
> "tipik değer" yok.

---

## 0. Ölçüm koşulları (tekrar üretilebilirlik için)

| | |
|---|---|
| Ortam | Docker, 12 servis ayakta, `istoc.localhost` (gateway :80) |
| Tarayıcı | Chrome, Chrome DevTools MCP üzerinden sürüldü |
| Sunucu | nginx/1.31.3 (storefront) → nginx (frappe-frontend) → gunicorn |
| Ölçüm A — **masaüstü** | viewport 1366×768×1, ağ kısıtı **yok**, CPU kısıtı **yok** |
| Ölçüm B — **mobil** | viewport 412×915×2.625 (mobile+touch), ağ **Slow 4G**, CPU **4×** |
| Bayt kaynağı | `PerformanceResourceTiming.encodedBodySize` (tarayıcı) + `Content-Length` (`curl -sI`, doğrulama) |
| LCP/CLS kaynağı | Chrome DevTools performance trace, `performance_start_trace(reload=true)` |

### Ölçümü etkileyen üç uyarı — sayıları okurken dikkate al

1. **Localhost'ta ağ gecikmesi ≈ 0.** Ölçüm A'daki LCP değerleri (275–538 ms)
   gerçek dünya değil, *alt sınır*dır. Gerçek kullanıcı LCP'si için Ölçüm B'ye
   (Slow 4G + 4× CPU) bak. Faz 12 karşılaştırması **aynı iki koşulda** yapılmalı.
2. **PWA Service Worker devrede.** Ölçüm A sırasında Chrome trace'i LCP kaynağı
   için `From a service worker: Yes` bildirdi. Workbox runtime cache'leri
   ölçüldü ve isimleri kaydedildi: `workbox-precache-v2`, **`frappe-files`**,
   `pages`, `frappe-api`. Ölçüm B'den **önce** SW kaydı silindi ve dört cache
   de boşaltıldı (`getRegistrations().unregister()` + `caches.delete()`).
3. **Ana sayfa verisinin bir kısmı demo/seed.** Ana sayfadaki 4 bozuk görsel
   `cdn.dummyjson.com`'a, 7 görsel `images.unsplash.com`'a gidiyor. Bunlar
   storefront kaynak kodunda **değil**; `tradehub_core/seed_demo_data.py`
   (satır 404-405) ve `Category Showcase Tile` kayıtlarından geliyor. Ana
   sayfa satırındaki dış-kaynak baytları bu yüzden "gerçek üretim yükü"
   sayılmamalı; **`/files/` baytları sayılmalı**.

---

## 1. Kritik bulgu — storefront istemci-taraflı render (SPA)

`curl http://istoc.localhost/` ile gelen HTML **7.766 bayt** ve içinde
**sıfır `<img>`** var. Gövde tamamen `<div id="app"></div>`. Tüm görseller
JavaScript çalıştıktan sonra DOM'a giriyor.

Sonucu ölçüldü: **her dört sayfada da LCP görselinin
"Request is discoverable in initial document" denetimi FAILED.** Tarayıcının
preload scanner'ı LCP görselini hiç göremiyor; keşif ancak JS bundle indirilip
çalıştıktan sonra oluyor.

Bu, LCP dökümündeki **Load delay** kaleminin neden her sayfada baskın
olduğunu açıklıyor (Ölçüm B):

| Sayfa (mobil) | TTFB | **Load delay** | Load duration | Render delay | LCP |
|---|---|---|---|---|---|
| Ana sayfa | 25 ms | **691 ms** | 2 ms | 58 ms | 776 ms |
| Ürün listeleme | 26 ms | **894 ms** | 3 ms | 139 ms | 1.062 ms |
| Ürün detay | 27 ms | **837 ms** | 3 ms | 52 ms | 919 ms |
| Mağaza profili | 30 ms | — | — | 709 ms | 740 ms |

Görselin kendisini indirmek 2–3 ms sürüyor. Zamanın %85-90'ı görselin
*keşfedilmesini beklemekle* geçiyor. **Görselleri küçültmek tek başına bu
tabanı düzeltmez; keşif yolu (SSR/preload/erken hint) de gerekiyor.**

---

## 2. Dört sayfa × ölçülen metrik tablosu

Ölçülen URL'ler (canlı sistemden slug çekilerek seçildi):

| Tip | URL |
|---|---|
| Ana sayfa | `http://istoc.localhost/` |
| Ürün listeleme | `http://istoc.localhost/urunler` |
| Ürün detay | `http://istoc.localhost/urun/bonny-erzak-saklama-kabi-1-lt` |
| Mağaza profili | `http://istoc.localhost/magaza/SEL-00034` (Mugiss) |

### 2.1 Ana tablo

| Metrik | Ana sayfa | Ürün listeleme | **Ürün detay** | Mağaza profili |
|---|---:|---:|---:|---:|
| Ham HTML — `curl`, sıkıştırmasız (bayt) | 7.766 | 8.514 | 7.988 | 6.346 |
| Ham HTML — gzip'li tel üstü (bayt) | 2.403 | 2.445 | 2.336 | 2.007 |
| Ham HTML içindeki `<img>` sayısı | **0** | **0** | **0** | **0** |
| Render sonrası DOM (karakter) | 244.842 | 770.569 | 255.057 | 248.746 |
| `<img>` sayısı (render sonrası) | 22 | **51** | 31 | 26 |
| Benzersiz görsel isteği | 22 | 41 | 15 | 12 |
| **TOPLAM GÖRSEL BAYTI** | **3.344.403 B<br>(3,19 MB)** | **8.462.503 B<br>(8,07 MB)** | **13.774.742 B<br>(13,14 MB)** | **1.068.262 B<br>(1,02 MB)** |
| — bunun `/files/` (kullanıcı medyası) payı | 2.863.387 B | ~8,05 MB | 13.759.638 B | 1.053.616 B |
| — dış kaynak (Unsplash) payı | 466.370 B | 0 | 0 | 0 |
| JS baytı (script+link) | 954.603 B | 907.611 B | 974.259 B | 957.822 B |
| CSS baytı | 25.356 B | 25.356 B | 25.356 B | 47.952 B |
| En büyük tek görsel | AV-303706463.JPG<br>1.016.179 B · 17,80 MP | Gemini_Generated_…png<br>1.409.363 B · 1,05 MP | **020 kirmizi orta 12'li.jpg<br>2.345.178 B · 32,50 MP** | ChatGPT Image….png<br>776.986 B · 1,57 MP |

### 2.2 Duyarlı görsel öznitelikleri — kaç `<img>`'de var

| Öznitelik | Ana sayfa | Ürün listeleme | Ürün detay | Mağaza |
|---|---:|---:|---:|---:|
| `srcset` | **0 / 22** | **0 / 51** | **0 / 31** | **0 / 26** |
| `sizes` | **0 / 22** | **0 / 51** | **0 / 31** | **0 / 26** |
| `<picture>` sarmalı | **0 / 22** | **0 / 51** | **0 / 31** | **0 / 26** |
| `fetchpriority` | **0 / 22** | **0 / 51** | **0 / 31** | **0 / 26** |
| `loading` (herhangi) | 16 / 22 | **0 / 51** | 27 / 31 | 21 / 26 |
| — `loading="lazy"` | 16 | **0** | 25 | 21 |
| — `loading="eager"` | 0 | 0 | 2 | 0 |
| `decoding` | 21 / 22 | 50 / 51 | 28 / 31 | 25 / 26 |
| `width` + `height` | 22 / 22 | 51 / 51 | 31 / 31 | 26 / 26 |

**Kaynak kodda doğrulama** (`tradehubfront/src` altında `grep -rl`):

| Desen | Eşleşen dosya |
|---|---|
| `srcset` | **0** |
| `sizes=` | **0** |
| `<picture` | **0** |
| `fetchpriority` | **1** (`components/sell/SellPageLayout.ts:113`) |
| `loading="lazy"` | 41 |

Yani duyarlı görsel altyapısı storefront'ta **hiç yok** — bu, ölçülen tek tek
sayfaların rastlantısı değil, kod tabanının tamamının durumu.

### 2.3 Core Web Vitals

**Ölçüm A — masaüstü, kısıt yok, SW cache sıcak** (alt sınır):

| Sayfa | LCP | CLS | LCP öğesi | Keşif denetimleri |
|---|---:|---:|---|---|
| Ana sayfa | 301 ms | 0,00 | `<img>` → `images.unsplash.com/photo-1441984904996…` (AVIF, dış) | fetchpriority ✗ · **lazy ✗** · ilk belgede ✗ |
| Ürün listeleme | 454 ms | 0,04 | `<img>` → `/files/Ekran Görüntüsü - 2026-06-22 10-27-16.png` | fetchpriority ✗ · lazy ✓ · ilk belgede ✗ |
| Ürün detay | 538 ms | 0,00 | `<img>` → `/files/BLNT2888örn.jpg` | fetchpriority ✗ · lazy ✓ · ilk belgede ✗ |
| Mağaza profili | 275 ms | 0,05 | **CSS `background-image`** → `/images/verified.jpg` | fetchpriority ✗ · lazy ✓ · ilk belgede ✗ |

**Ölçüm B — mobil, Slow 4G + 4× CPU, SW cache temizlenmiş** (taban çizgisi):

| Sayfa | LCP | CLS | Değerlendirme |
|---|---:|---:|---|
| Ana sayfa | **776 ms** | 0,01 | LCP iyi · CLS iyi |
| Ürün listeleme | **1.062 ms** | **0,51** | LCP iyi · **CLS kötü (eşik 0,25)** |
| Ürün detay | **919 ms** | 0,00 | LCP iyi · CLS iyi |
| Mağaza profili | **740 ms** | 0,00 | LCP iyi · CLS iyi |

> **CLS 0,51 — ürün listeleme, mobil.** Trace tek bir kaymayı gösterdi:
> 1.008 ms'de başlayan, skoru **0,5144** olan tek olay. Chrome'un
> CLSCulprits içgörüsü "No potential root causes identified" döndürdü;
> kayma bir kaynak yüklemesine değil, SPA'nın iskeletten gerçek karta geçiş
> render'ına bağlı görünüyor. **Kesin kök neden ÖLÇÜLEMEDİ** — bunu
> daraltmak ayrı bir görev (DOM mutasyon zaman damgası ile trace eşleştirmesi
> gerekiyor). Masaüstünde aynı sayfada CLS 0,04; sorun mobil viewport'a özgü.
>
> Not: CLS'in düşük göründüğü sayfalarda bile `width`/`height` değerleri
> **gerçek en-boy oranını yansıtmıyor** (§4.3). Şu an kurtaran şey Tailwind
> `aspect-*` / sabit yükseklikli kaplar; öznitelikler değil.

---

## 3. Doküman hedefine karşı durum

Hedef: **ürün sayfası görselleri < 900 KB**.

| Sayfa | Ölçülen | Hedef | Durum |
|---|---:|---:|---|
| Ürün detay | **13.774.742 B (13,14 MB)** | 921.600 B | **≈ 15,0× AŞIM** |
| Ürün listeleme | 8.462.503 B (8,07 MB) | — | (hedef tanımlı değil) |
| Ana sayfa | 3.344.403 B (3,19 MB) | — | (hedef tanımlı değil) |
| Mağaza profili | 1.068.262 B (1,02 MB) | — | (hedef tanımlı değil) |

**Ürün detay sayfasının 13,14 MB'ının nereden geldiği ölçüldü:** galeri
şeridindeki **12 küçük resim (thumbnail)**, ekranda **59×59 CSS px**
boyutunda görünüyor ama her biri **orijinal dosyayı tam boy** indiriyor.
Tek başına bu 12 thumbnail ~13 MB. Ana galeri görseli (`BLNT2888örn.jpg`,
199.092 B) sayfanın en hafif parçalarından biri.

Ölçülen en uç örnek: `020 kirmizi orta 12'li.jpg` — **2.345.178 bayt,
4480×7255 = 32,50 megapiksel**, ekranda **59×59 px** olarak çiziliyor.
Gösterilen piksel başına indirilen veri oranı ≈ **674:1**.

---

## 4. En ağır 10 görsel (ölçülen)

Bayt değerleri hem tarayıcı `encodedBodySize` hem `curl -sI` `Content-Length`
ile doğrulandı — ikisi birebir aynı çıktı.

| # | Dosya | Bayt | Boyut | MP | Ekranda | Geçtiği sayfa |
|---:|---|---:|---|---:|---|---|
| 1 | `/files/020 kirmizi orta 12'li.jpg` | 2.345.178 (2,24 MB) | 4480×7255 | 32,50 | 59×59 | ürün detay |
| 2 | `/files/018 siyah orta 12'li.jpg` | 2.092.124 (2,00 MB) | 4456×6345 | 28,27 | 59×59 | ürün detay |
| 3 | `/files/BLNT1818xx.jpg` | 2.066.448 (1,97 MB) | 3049×4574 | 13,95 | 59×59 | ürün detay |
| 4 | `/files/013 siyah orta 3 lü.jpg` | 1.987.254 (1,90 MB) | 4456×6345 | 28,27 | 59×59 | ürün detay |
| 5 | `/files/Gemini_Generated_Image_qvm8hrqvm8hrqvm8.png` | 1.409.363 (1,34 MB) | 976×1079 | 1,05 | 195×195 | ürün listeleme |
| 6 | `/files/019 bej buyuk 12'li calisma.jpg` | 1.263.061 (1,20 MB) | 3233×4494 | 14,53 | 59×59 | ürün detay |
| 7 | `/files/Adsız (1200 x 1200 piksel).png` | 1.244.500 (1,19 MB) | 1200×1200 | 1,44 | 195×195 | ürün listeleme |
| 8 | `/files/BLNT2184xx.jpg` | 1.172.797 (1,12 MB) | 2400×3600 | 8,64 | 59×59 | ürün detay |
| 9 | `/files/008 bej orta 3 lu.jpg` | 1.157.910 (1,10 MB) | 3233×4494 | 14,53 | 59×59 | ürün detay |
| 10 | `/files/AV-303706463.JPG` | 1.016.179 (0,97 MB) | 4105×4335 | 17,80 | 242×242 / 195×195 | ana sayfa **ve** listeleme |

**Top-10 toplamı: 15,02 MB.**

İki ayrı israf deseni ölçüldü:

- **Aşırı çözünürlük (1-4, 6, 8-10).** Piksel başına 0,06-0,15 bayt — JPEG
  sıkıştırması *iyi*; sorun dosyanın 8-32 MP olması. Faz 0'daki
  "179 dosya > 20 MP" bulgusunun sayfa üzerindeki karşılığı bu.
- **Yanlış format (5, 7).** Bunlar sadece 1,05 ve 1,44 MP ama piksel başına
  **1,34** ve **0,86 bayt** — fotoğrafik içerik PNG olarak kaydedilmiş.
  Aynı görseller WebP/AVIF olsaydı bir büyüklük mertebesi küçük olurdu.
  Faz 0'daki "PNG 786 dosya" sayısının maliyeti burada görünüyor.

### 4.1 Ayrıca: mağaza logosu tek başına sayfanın %72,7'si

`/files/ChatGPT Image 9 Tem 2026 14_00_30.png` — **776.986 bayt (759 KB)**,
**1254×1254**, mağaza profilinde **38×38 CSS px** avatar olarak çiziliyor.
Mağaza profili sayfasının toplam 1.068.262 baytlık görsel yükünün
**%72,7'si** bu tek logo. `docs/standards/logo.md` için doğrudan kanıt.

### 4.2 Ayrıca: mağaza kapağı en-boy oranı uyuşmuyor

Kapak görseli gerçek boyut **1920×720** (2,67:1) ama `<img>` öznitelikleri
`width="400" height="300"` (1,33:1). Öznitelikler CLS'i önlemek için var ama
yanlış oranı bildiriyor.

### 4.3 Ayrıca: `width`/`height` öznitelikleri sabit yazılmış

Ölçülen tüm sayfalarda öznitelikler **%100 dolu** ama içerik **sabit**:
ürün kartlarında her zaman `width="400" height="400"`, galeri
thumbnail'lerinde her zaman `width="70" height="70"` — görselin gerçek
boyutundan bağımsız. Örnek: `AV-303706463.JPG` gerçekte 4105×4335 (0,947:1)
iken `400×400` (1:1) bildiriliyor. Yani bu öznitelikler **CLS koruması
sağlamıyor**, yalnızca bir yer tutucu. Kaynakta doğrulandı:
`components/seller/CompanyProfile.ts`, `components/seller/CompanyInfo.ts`,
`components/seller/StoreHeader.ts`.

### 4.4 Ayrıca: `<img src="#">` hatası — ürün listeleme

Ürün listeleme sayfasında tedarikçi filtre listesindeki **10 adet logo
`<img>`'inin `src` değeri `#`**. Ölçülen sonuç: her biri sayfanın kendi
HTML'ini (8.514 B) görsel olarak indiriyor, `naturalWidth = 0` ile
çözümlemede başarısız oluyor. Chrome'un Cache içgörüsü de bunu
"8.5 kB wasted bytes" olarak işaretledi. `alt` değerleri gerçek tedarikçi
adları (`MarmaraT`, `AkdenizMut`, `KaradenizG`, `İstHırdavat`,
`OsmanlıAks`, `Boğaziçi`, …), `class="w-4 h-4 object-contain me-1"`.

---

## 5. nginx yanıt başlıkları — hangi yolda cache var, hangisinde yok

`curl -sI` ile ölçüldü:

| Yol | Cache-Control | Content-Encoding | Vary | Örnek |
|---|---|---|---|---|
| `/` (HTML) | **yok** | `gzip` | `Accept-Encoding` | `/`, `/urunler` |
| `/assets/` | `public, max-age=31536000, immutable` | `gzip` | `Accept-Encoding` | `index-CWGaxIi2.js` |
| `/images/` | `public, max-age=2592000` | yok | yok | `verified.jpg` (22.596 B) |
| `/fonts/` | `public, max-age=2592000` | yok | yok | `istoc-sans-400.woff2` (25.280 B) |
| `/favicon.ico` | `public, max-age=2592000` | yok | yok | 5.236 B |
| **`/files/` (kullanıcı medyası)** | **HİÇ YOK** | yok | yok | ölçülen 15 dosyanın **hepsinde** |
| `/manifest.webmanifest` | yok | yok | yok | `Content-Type: application/octet-stream` |

### 5.1 `/files/` neden cache başlığı almıyor — kök neden bulundu

`istoc-dev-storefront-1` nginx yapılandırmasında iki blok var:

```nginx
location ^~ /files/ {                          # ← ^~ : prefix, regex'i ezer
    add_header X-Robots-Tag "noindex" always;
    limit_req zone=files_zone burst=20 nodelay;
    proxy_pass http://frappe-frontend:8080/files/;
    # ← Cache-Control YOK
}

location ~* \.(?:png|jpg|jpeg|webp|gif|ico|svg|woff2?|ttf)$ {
    add_header Cache-Control "public, max-age=2592000";   # ← buraya hiç düşmüyor
}
```

`^~` işareti kasıtlı ve doğru (yapılandırmadaki yorum bunu açıklıyor:
`^~` olmadan `/files/urun.jpg` backend'e gitmez, regex'e düşer → 404). Ama
`^~` bloğu, atladığı regex bloğunun `Cache-Control`'ünü **yerine koymuyor**.
Upstream `istoc-dev-frappe-frontend-1` de `/files/` için `Cache-Control`
üretmiyor (ölçülen yanıt başlıklarında yok).

**Ölçülen sonuç:** sitenin en ağır varlıkları — tek sayfada 13 MB'a varan
kullanıcı medyası — **hiçbir açık önbellek yönergesi almıyor**. Şu anda bunu
kısmen telafi eden tek şey PWA Service Worker'ın `frappe-files` runtime
cache'i; yani önbellekleme HTTP katmanında değil, uygulama katmanında ve
yalnızca SW kayıtlı tarayıcılarda çalışıyor.

`/files/` yanıtlarında `Content-Encoding` de yok — bu görseller için doğru
(zaten sıkıştırılmış format), sorun değil.

---

## 6. ÖLÇÜLEMEDİ — ve koşulacak tam komut

### 6.1 Lighthouse — ÖLÇÜLEMEDİ

**Lighthouse koşulmadı.** Bu oturumdaki LCP/CLS değerleri Chrome DevTools
performance trace'inden alındı; Lighthouse performans skoru, Speed Index,
TBT ve "Properly size images" / "Serve images in next-gen formats" denetim
çıktıları **üretilmedi**.

Koşulacak tam komutlar (dört sayfa, mobil profil, HTML + JSON çıktı):

```bash
mkdir -p docs/reports/lighthouse-baseline && cd docs/reports/lighthouse-baseline

for u in \
  "http://istoc.localhost/|home" \
  "http://istoc.localhost/urunler|plp" \
  "http://istoc.localhost/urun/bonny-erzak-saklama-kabi-1-lt|pdp" \
  "http://istoc.localhost/magaza/SEL-00034|store" ; do
  URL="${u%%|*}"; NAME="${u##*|}"
  npx -y lighthouse@latest "$URL" \
    --preset=desktop=false \
    --form-factor=mobile \
    --screenEmulation.mobile \
    --screenEmulation.width=412 \
    --screenEmulation.height=915 \
    --screenEmulation.deviceScaleFactor=2.625 \
    --throttling-method=simulate \
    --throttling.rttMs=150 \
    --throttling.throughputKbps=1638.4 \
    --throttling.cpuSlowdownMultiplier=4 \
    --only-categories=performance \
    --output=html --output=json \
    --output-path="./${NAME}.report" \
    --chrome-flags="--headless=new --no-sandbox --ignore-certificate-errors"
done
```

Masaüstü karşılığı için aynı döngüde `--preset=desktop` kullan ve dosya
adlarına `-desktop` ekle.

**Önemli:** Lighthouse'u koşmadan önce Service Worker'ı devre dışı bırak,
yoksa `frappe-files` cache'i `/files/` baytlarını maskeler:

```bash
# Lighthouse zaten her koşuda temiz profil açar; ama elle doğrulama yaparken
# DevTools > Application > Service Workers > "Bypass for network" işaretle.
```

### 6.2 Gerçek kullanıcı (field) verisi — ÖLÇÜLEMEDİ

Chrome trace her dört sayfa için `Metrics (field / real users): n/a – no data
for this page in CrUX` bildirdi. `istoc.localhost` yerel bir ad olduğu için
CrUX'ta karşılığı yok; üretim alan adı ölçüme açılana kadar saha verisi
elde edilemez.

### 6.3 INP — ÖLÇÜLEMEDİ

INP etkileşim gerektirir; bu oturumda yalnızca sayfa yüklemesi ölçüldü.

### 6.4 Mobil ürün listeleme CLS 0,51'in kök nedeni — ÖLÇÜLEMEDİ

Skor ölçüldü (0,5144, tek kayma, t=1.008 ms) ama Chrome'un CLSCulprits
içgörüsü sorumlu düğümü belirleyemedi ("No potential root causes
identified"). Kök neden ayrı bir görev gerektiriyor.

### 6.5 Kategori sayfası — ÖLÇÜLMEDİ

Görev "ürün listeleme (`/kategori/...` ya da arama)" dediği için `/urunler`
seçildi; nginx'te ayrı bir `location ~ ^/kategori/(.+)$` SEO bloğu var ve
farklı davranabilir. `/kategori/...` ölçülmedi.

---

## 7. Faz 12 için sabitlenen taban çizgisi

Faz 12 "sonra" ölçümü **aynı dört URL'de, aynı iki koşulda** yapılmalı.
Karşılaştırılacak sayılar:

| Metrik | Ana sayfa | Ürün listeleme | Ürün detay | Mağaza |
|---|---:|---:|---:|---:|
| Toplam görsel baytı | 3.344.403 | 8.462.503 | **13.774.742** | 1.068.262 |
| `<img>` sayısı | 22 | 51 | 31 | 26 |
| `srcset` kullanan `<img>` | 0 | 0 | 0 | 0 |
| `loading="lazy"` | 16 | **0** | 25 | 21 |
| `fetchpriority="high"` | 0 | 0 | 0 | 0 |
| LCP (masaüstü, kısıtsız) | 301 ms | 454 ms | 538 ms | 275 ms |
| **LCP (mobil, Slow 4G, 4× CPU)** | **776 ms** | **1.062 ms** | **919 ms** | **740 ms** |
| CLS (mobil) | 0,01 | **0,51** | 0,00 | 0,00 |
| En büyük görsel (bayt) | 1.016.179 | 1.409.363 | 2.345.178 | 776.986 |
| En büyük görsel (MP) | 17,80 | 1,05 | 32,50 | 1,57 |

Ölçülen dört sayfanın toplam görsel yükü: **26.649.910 bayt (25,42 MB).**

Ayrıca sabitlenen niteliksel durumlar (Faz 12'de değişmiş olması beklenen):

- `/files/` yolunda `Cache-Control` **yok** (§5.1)
- Storefront kaynak kodunda `srcset` **0 dosya**, `<picture>` **0 dosya**,
  `fetchpriority` **1 dosya** (§2.2)
- Dört sayfanın dördünde de LCP görseli "ilk belgede keşfedilebilir"
  denetiminden **FAILED** (§1)
- Ürün detay galerisinde 12 thumbnail 59×59 px'de orijinali indiriyor (§3)
- Ürün listemede 10 adet `<img src="#">` (§4.4)

---

## 8. Kaynak dosyalar

- Ölçüm betikleri ve ham çıktı: bu oturumda geçici dizinde üretildi, kalıcı
  değil. Yeniden üretmek için §0'daki koşullar + §6.1'deki komut yeterli.
- nginx yapılandırması (salt okundu): `istoc-dev-storefront-1`
  `/etc/nginx/conf.d/` — `location ^~ /files/` (satır ~363),
  `location ^~ /assets/` (~382), `location ~* \.(png|jpg|…)$` (~518)
- Demo seed kaynağı (salt okundu):
  `tradehub_core/seed_demo_data.py:398-405` (dummyjson URL'leri)
- Sabit `width`/`height` desenleri (salt okundu):
  `tradehubfront/src/components/seller/CompanyProfile.ts`,
  `.../CompanyInfo.ts`, `.../StoreHeader.ts`

---

## Güncel 4 sayfa × 2 cihaz taban çizgisi — 2026-08-23

Lighthouse 12.6.1 / HeadlessChrome 151 ile her rota ve profil ayrı navigasyon
olarak koşuldu. Mobil profil 412×915, DPR 2,625, 150 ms RTT, 1.638,4 Kbps ve
4× CPU yavaşlatma; desktop 1350×940, DPR 1, 40 ms RTT, 10.240 Kbps ve 1× CPU.
Tam makine-okunur çıktı: `docs/data/faz0-lighthouse-baseline-2026-08-23.json`.

| Sayfa | Profil | Skor | LCP ms | CLS | TBT ms | Görsel transferi | Görsel istek |
|---|---|---:|---:|---:|---:|---:|---:|
| Ana sayfa | desktop | 96 | 1.381 | 0,0001 | 0 | 1.714.886 B | 17 |
| Ana sayfa | mobile | 70 | 5.796 | 0,0098 | 58 | 1.691.503 B | 16 |
| Ürün listesi | desktop | 95 | 1.377 | 0,0458 | 0 | 170.091 B | 42 |
| Ürün listesi | mobile | 44 | 7.441 | **0,4978** | 25 | 303.380 B | 42 |
| Ürün detayı | desktop | 74 | **12.875** | 0,0002 | 0 | **14.564.979 B** | 19 |
| Ürün detayı | mobile | 63 | **12.714** | 0 | 22 | 3.421.177 B | 12 |
| Mağaza | desktop | 92 | 1.760 | 0,0662 | 0 | 1.094.435 B | 13 |
| Mağaza | mobile | 70 | 5.637 | 0,1008 | 21 | 1.014.681 B | 9 |

Bu bir **taban çizgisidir**, hedef geçiş raporu değildir. Öncelik sırası:
ürün detayındaki 12,9 sn LCP ve 14,6 MB görsel yükü; mobil ürün listesindeki
0,498 CLS; sonra mobil ana/mağaza LCP. INP alan metriğidir; Lighthouse laboratuvar
koşusunda TBT kaydedildi, mevcut RUM INP kanıtı ayrı rapordadır.

### Görsel gövdesine göre en ağır 10 ürün — 20 ek koşum

1.231 adet storefront-visible, yerel görsel taşıyan ürün; ana + galeri
dosyalarının tekilleştirilmiş disk baytına göre sıralandı. İlk 10 ürünün her biri
mobil ve desktop profilde **ardışık** ölçüldü; eşzamanlı koşumla kaynak paylaşımı
yaratılmadı. Ayrıntı:

`docs/data/faz0-worst10-product-lighthouse-2026-08-23.json`

| Ürün | Yerel kaynak | Mobil LCP | Desktop LCP | Mobil görsel transferi | Desktop görsel transferi |
|---|---:|---:|---:|---:|---:|
| LST-03998 | 15 / 20.309.523 B | 5.954 ms | 5.917 ms | 5.833.673 B | **21.107.888 B** |
| LST-04011 | 12 / 19.930.044 B | 6.026 ms | 8.589 ms | 12.425 B | 20.726.616 B |
| LST-04000 | 14 / 18.407.206 B | 11.883 ms | 6.953 ms | 3.040.319 B | 19.184.949 B |
| LST-04002 | 12 / 17.555.117 B | 6.097 ms | 7.351 ms | 12.425 B | 18.406.283 B |
| LST-03999 | 12 / 13.759.638 B | 6.766 ms | **12.841 ms** | 3.418.304 B | 14.544.707 B |
| LST-03997 | 16 / 13.198.353 B | 6.027 ms | 7.196 ms | 1.297.657 B | 13.997.120 B |
| LST-04007 | 9 / 12.292.746 B | 6.024 ms | 5.715 ms | 5.420.027 B | 13.087.662 B |
| LST-04009 | 9 / 12.213.455 B | **18.480 ms** | 8.759 ms | 5.221.918 B | 13.008.371 B |
| LST-04006 | 11 / 11.177.415 B | 5.804 ms | 5.709 ms | 2.181.519 B | 11.973.426 B |
| LST-04004 | 12 / 10.665.979 B | 6.096 ms | 8.838 ms | 12.425 B | 11.462.545 B |

En kötü LCP mobilde LST-04009: 18.480 ms; en yüksek ölçülen transfer
desktop LST-03998: 21.107.888 B. Bazı mobil koşumlarda galeri fold-altında
ertelendiği için yalnız 12.425 B görsel transfer edildi; bu yüzden katalog disk
baytı seçim ölçütü, Lighthouse transferi ise ayrı sonuç olarak korunmuştur.
