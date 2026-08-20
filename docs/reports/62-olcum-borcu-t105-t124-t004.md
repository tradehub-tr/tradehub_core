# 62 — Ölçüm borcu: T-105 · T-124 · T-004

**Tarih:** 2026-08-20 · **Plan:** `docs/plans/frontend-kalan-45-plani.md` kova A, satır A6
**Görev tipi:** ÖLÇÜM. Bu turda hiçbir kaynak dosya değiştirilmedi.

> **Bu rapordaki her sayı gerçekten koşturuldu.** Koşturulamayan hiçbir şeye
> "geçti" denmedi; ölçülemeyen her kalem `ÖLÇÜLEMEDİ` olarak işaretlendi ve
> **neden** ölçülemediği yazıldı.

---

## Yönetici özeti

| Görev | Sonuç | Tek cümle |
|---|---|---|
| **T-105** | **ÖLÇÜLDÜ** | 72 test koştu, **72 geçti, 0 kırık**. Ama "geçti" ≠ "piksel paritesi var" — aşağıdaki uyarıyı okuyun. |
| **T-124** | **ÖLÇÜLDÜ** | Lighthouse 12 kez gerçekten koştu. LCP/CLS/TBT bütçelerinden **ikisi kırık**: `products.html` LCP **6352 ms** (bütçe 2500), `categories.html` CLS **0.5396** (bütçe 0.1). |
| **T-004** | **KISMEN KAPANDI** | Lighthouse taban çizgisi 4 sayfa için artık var. **INP hâlâ ÖLÇÜLEMEDİ** — lab Lighthouse INP üretemez. |

**En önemli üç bulgu:**

1. `products.html` LCP **6.35 s** — sayfada ~5 MB ham ürün görseli var (tek başına 1376 KB'lık bir PNG 400×400 kutuya çiziliyor). Bu tam olarak medya boru hattının çözdüğü problem ve boru hattı **kapalı** (`media_pipeline_enabled=0`).
2. `categories.html` CLS **0.5396** — kaymanın **0.5394'ü tek başına `<footer>`'dan** geliyor. Bu sayfa `lighthouserc.cjs`'in URL listesinde **yok**, yani bütçe dosyasının kendisinde kapsam boşluğu var.
3. `product-detail.html` ölçümü **temsili değil**: LCP öğesi "Aradığınız ürün mevcut değil veya kaldırılmış olabilir." metni. Config, ürün kimliği olmayan bir URL çağırdığı için **boş durum sayfasını** ölçüyor.

---

## T-105 — Faz 10 crop doğruluk kabulü · **ÖLÇÜLDÜ**

### Nasıl koşturuldu

```
cd admin-panel/frontend
node --test src/lib/media/crop/__tests__/cropGeometryParity.test.js \
             src/lib/media/crop/__tests__/cropPixelParity.test.js
node --test src/lib/media/crop/__tests__/cropHandles.test.js \
             src/lib/media/crop/__tests__/cropPolicy.test.js \
             src/lib/media/crop/__tests__/cropSafeArea.test.js
node scripts/sync-crop-geometry.mjs --check
```

Node **v24.18.1**. Paketin tamamı (`npm test`) **bilinçli koşturulmadı** — o sırada
başka ajanlar `admin-panel/frontend` içinde kod yazıyordu; tüm paket koşulsaydı
yakalanan kırık, ölçülen şeye ait olmayabilirdi. Yalnız 5 crop dosyası hedeflendi.

### Sayılar

| Dosya | Test | Geçti | Kırık | Atlandı |
|---|---:|---:|---:|---:|
| `cropGeometryParity.test.js` + `cropPixelParity.test.js` | 26 | **26** | **0** | 0 |
| `cropHandles` + `cropPolicy` + `cropSafeArea` | 46 | **46** | **0** | 0 |
| **Toplam** | **72** | **72** | **0** | **0** |

`sync-crop-geometry.mjs --check` → **çıkış kodu 0** (vendor kopyaları senkron).

Doğrulanan kapsam, testlerin kendi çıktısından:

- **592 vektörün tamamı** panelin geometri kapısından geçiyor — **0 px sapma**.
- **600 vakanın tamamı** canlı `useCropStudio` ile birebir yeniden üretiliyor.
- Vendor kopyaları manifestteki sha256 ile birebir; manifest canlı `tradehub_core`
  kaynağıyla uyuşuyor; vektörler canlı `core/crop.py` ile aynı sürümden
  (bu test **atlanmadı** — `tradehub_core` ortamda mevcut).

### ⚠️ "72/72 geçti" ne demek DEĞİL — bu satırı atlamayın

`cropPixelParity.test.js` bir **parite kabulü değil, karakterizasyon testidir.**
Ölçülmüş sapmaları sabitler; sıfır sapma iddia etmez. Testin kendi tanısal çıktısı:

| Sınıf | Vaka | **Sapan** | En büyük sapma | Sebep (testin kendi açıklamasından) |
|---|---:|---:|---:|---|
| A — oran kilitli, zoom yok | 120 | 5 | **1 px** | Yuvarlama ifadesi farkı: panel `floor(v+0.5)`, sunucu Python `int(round(v))` (yarım çifte) |
| B — zoom'lu | 120 | **119** | **7391 px** | **Zoom kaydedilmiyor.** `savePayload` yalnız odak + override taşır; sunucu pencereyi daima tam kadrajdan kurar |
| C — serbest kırpma + override | 120 | **104** | **3704 px** | Sunucu override'ı profilin oranına zorluyor (`_fit_ratio_keeping_center`), panel serbest dikdörtgeni olduğu gibi gösteriyor |
| D — kilitli oran + override | 120 | 7 | **1 px** | Yalnız yuvarlama |
| E — serbest kırpma, override yok | 120 | **86** | **3481 px** | Panel taban bölgeyi gösteriyor, sunucu profil oranına kırpıyor |

**Okunuşu:** Kanonik yolda (A, D) panel ile sunucu pratikte aynı — sapma en fazla
1 px ve sebebi kanıtlanmış (ayrı bir test, A'daki her sapmanın tam yarım piksel
sınırından geldiğini doğruluyor). **Ama B, C, E sınıflarında kullanıcının ekranda
gördüğü kadraj ile sunucunun keseceği kadraj ayrışıyor** — B'de 120 vakanın 119'u.
Testler yeşil çünkü bu sapmalar *beklenen değer olarak* dosyaya yazılmış.

`cropGeometryParity.test.js` ise **gerçek paritedir**: 592 vektör, 0 px. İki ölçüm
birbirinin yerine geçmez ve test dosyası bunu açıkça yazıyor.

**Karar için:** T-105'in "harman koşuldu ve yeşil" borcu **kapandı**. Ancak
"kullanıcı ne görüyorsa sunucu onu kesiyor" kabulü **A ve D sınıfları için
karşılanıyor, B / C / E için karşılanmıyor**. Bu ayrı bir iş kalemidir; en olası
kök neden zoom'un `savePayload`'a hiç girmemesi.

---

## T-124 — Faz 12 performans kabulü · **ÖLÇÜLDÜ**

### Önce: bildirilen derleme hatası — teşhis edildi

Bu oturumda daha önce `tradehubfront` derlemesi `npm ci` yüzünden başarısız olmuştu.
**Yeniden üretildi** (`npm ci --dry-run`, node_modules'e dokunmadan):

```
npm error code EUSAGE
npm error `npm ci` can only install packages when your package.json and
npm error package-lock.json are in sync.
npm error Missing: @emnapi/core@1.11.3 from lock file
npm error Missing: @emnapi/runtime@1.11.3 from lock file
npm error Invalid: lock file's @emnapi/wasi-threads@1.2.1 does not satisfy @emnapi/wasi-threads@1.2.3
npm error Missing: @emnapi/core@1.9.2 from lock file
npm error Missing: @emnapi/runtime@1.9.2 from lock file
npm error Missing: @emnapi/wasi-threads@1.2.1 from lock file
```

**Kök neden:** `@emnapi/*` geçişli bağımlılıkları `package-lock.json`'da tutarsız.
Çözümü `npm install` ile lock'u tazelemek — **bu görevde yasak olduğu için
yapılmadı**, `package-lock.json` ve `package.json` değiştirilmedi.

**Ama derlemenin kendisi sağlam.** `node_modules` zaten kurulu olduğu için
`npm ci` adımı atlanabiliyor ve derlemenin iki gerçek adımı temiz geçiyor:

| Adım | Komut | Sonuç |
|---|---|---|
| Tip kontrolü | `npx tsc --noEmit` | **çıkış 0**, sıfır hata |
| Paketleme | `npx vite build --outDir <tmp>` | **çıkış 0**, 4.56 s'de bitti, PWA 219 girdi ön-önbelleğe alındı |

Çıktı repo'nun `dist/`'ine değil geçici dizine yazıldı; **`tradehubfront/dist`
değiştirilmedi.** Not: bu derleme, o sırada başka ajanların yazdığı yarım medya
kodunu da içeriyordu ve yine de temiz geçti.

> **Sonuç:** `npm ci` kırık (lockfile), **`npm run build` kırık değil**. Bunlar
> ayrı sorunlar. Lockfile CI'da bloke eder, lokal derlemede etmez.

### Lighthouse — gerçekten koştu

`@lhci/cli@0.15.1`, Lighthouse **12.6.1**, `preset: desktop`, `numberOfRuns: 3`.
Config **`tradehubfront/lighthouserc.cjs`'in kendisi** `require` edildi; yalnız
`upload.outputDir` geçici dizine yönlendirildi ki repo'ya rapor yazılmasın.
Config'in **kendi varsayılan hedefi** olan `http://traderup.localhost` kullanıldı —
gerçek nginx (gzip **açık**, `nginx/1.31.3`), Docker yığını 7 saattir ayakta.

**Toplam 12 Lighthouse koşumu** (3 sayfa × 3 + kategori sayfası × 3).

#### Sonuçlar — config'in tanımladığı 3 sayfa

| Sayfa | Perf | **LCP** | **CLS** | **TBT** | FCP | SEO |
|---|---:|---:|---:|---:|---:|---:|
| `/` | 0.96 | **1354 ms** ✅ | **0.0002** ✅ | **0 ms** ✅ | 829 ms | 0.69 ⚠️ |
| `/pages/products.html` | 0.74 ⚠️ | **6352 ms** ❌ | 0.0469 ✅ | **0 ms** ✅ | 920 ms | 0.69 ⚠️ |
| `/pages/product-detail.html` | 0.97 | **1104 ms** ✅* | **0.0000** ✅ | **0 ms** ✅ | 939 ms | 0.66 ⚠️ |

Üç koşumun yayılımı çok dar (ör. products LCP: 6392 / 6352 / 6234 ms), yani sayı gürültü değil.

#### Bütçeye göre kabul

| Bütçe | Hedef | Sonuç |
|---|---|---|
| `largest-contentful-paint` | ≤ 2500 ms | **KIRIK** — `products.html` 6352 ms (2.5×) |
| `cumulative-layout-shift` | ≤ 0.1 | 3 sayfada geçti; **kategori sayfasında KIRIK** (aşağıda) |
| `total-blocking-time` | ≤ 300 ms | **GEÇTİ** — üç sayfada da **0 ms** |
| `categories:performance` | ≥ 0.8 | **KIRIK** — `products.html` 0.74 |
| `categories:seo` | ≥ 0.9 | Kırık görünüyor ama **gerçek bir kusur değil** ↓ |

**SEO 0.66–0.69 bir dev ortamı yapaylığıdır, kod kusuru değil.** Üç sayfada da
başarısız olan **tek** SEO denetimi `is-crawlable`. Sebebi doğrulandı:

```
X-Robots-Tag: noindex, nofollow
robots.txt: "# env: noindex — fail-closed default (FRONTEND_DOMAIN != istoc.com)"
```

Bu, staging'in bilinçli fail-closed davranışı (`check-nginx-noindex.sh` bunu zaten
zorluyor). **Prod domaininde ölçülmeden SEO skoru üzerine karar verilmemeli.**

#### `products.html` LCP 6352 ms — kök neden ölçüldü

LCP öğesi gerçek bir ürün görseli:
`<img src="/files/Adsız (1200 x 1200 piksel)322c7c.png" ... width="400" height="400">`

Lighthouse'un `uses-responsive-images` denetimi, aynı sayfada yüklenen ham görseller:

| Dosya | Boyut | Boşa giden |
|---|---:|---:|
| `Gemini_Generated_Image_qvm8hrqvm8hrqvm8.png` | 1376 KB | 1328 KB |
| `Adsız (1200 x 1200 piksel).png` | 1215 KB | 1184 KB |
| `AV-303706463.JPG` | 992 KB | 990 KB |
| `AV-301.JPG` | 756 KB | 754 KB |
| `Adsız (1200 x 1200 piksel) (1).png` | 690 KB | 672 KB |

İlk beş dosyada bile **~5 MB**, neredeyse tamamı israf: 1200×1200 kaynaklar 400×400
kutulara çiziliyor. Lighthouse'un ilk iki fırsatı: *Properly size images* **3410 ms**,
*Serve images in next-gen formats* **2930 ms**.

**Bu bir frontend kodu hatası değil.** `prioritize-lcp-image` ve `lcp-lazy-loaded`
denetimleri **tam puan** aldı — yani işaretleme doğru (LCP görseli lazy değil,
öncelikli). Sorun ham varlıkların sunulması: türev üretimi yok, WebP/AVIF yok.
Bu tam olarak **kova C'deki T-061…T-066'nın** (`media_pipeline_enabled` varsayılan **0**)
çözdüğü iş. **Boru hattı açılmadan `products.html` LCP bütçesi tutturulamaz** —
`<link rel="preload">` (T-122) 1.2 MB'lık bir PNG'yi 2.5 s'ye sığdıramaz.

#### `product-detail.html` ölçümü temsili DEĞİL — config kusuru

LCP öğesi: `<p class="text-gray-400 mb-4">` → metni:
**"Aradığınız ürün mevcut değil veya kaldırılmış olabilir."**

Config `/pages/product-detail.html`'i **ürün kimliği olmadan** çağırıyor, sayfa boş
durum ekranını gösteriyor. Ölçülen 1104 ms, **gerçek bir ürün sayfasının LCP'si
değil, bir hata ekranının LCP'si.** Bu sayfanın gerçek performansı hâlâ **ÖLÇÜLMEDİ.**
Düzeltmesi `lighthouserc.cjs`'e geçerli bir ürün parametreli URL koymak — bu görev
ölçüm görevi olduğu için **yapılmadı**, bulgu olarak bırakıldı.

### İkinci koşum — sıkıştırmasız statik sunucu (karşılaştırma)

Yerel `dist/` bir Python `http.server` üzerinden de ölçüldü (**gzip yok**):
`/` LCP 2018 ms · products 2267 ms · product-detail 2346 ms — üçü de bütçe içinde,
ama en büyük fırsat her sayfada *"Enable text compression" ~1000–1170 ms*.

**Bu koşum kabul için kullanılmamalıdır** — sıkıştırmasız olduğu için metin varlıklarında
kötümser, ama daha önemlisi yerel `dist/` (19 Ağu 13:00) ile Docker imajındaki
storefront **farklı derlemelerdir** ve o dist'te 1.2 MB'lık ürün görselleri yok.
İkisi arasındaki uçurumun (2267 ms ↔ 6352 ms) sebebi budur. **Geçerli kabul sayısı
nginx koşumudur.**

---

## T-004 — LCP taban çizgisi · **KISMEN KAPANDI**

`docs/reports/03-performans-taban-cizgisi.md` gerçek Chrome DevTools trace içeriyordu
ama Lighthouse hiç koşulmamıştı ve raporun kendisi bunu itiraf ediyordu.

### Kapanan boşluklar

| Boşluk | Durum | Kanıt |
|---|---|---|
| "Lighthouse hiç koşulmadı" | **KAPANDI** | Lighthouse 12.6.1, 12 koşum, yukarıdaki tablolar |
| Ana sayfa LCP taban çizgisi | **KAPANDI** | 1354 ms (nginx, desktop, 3 koşum) |
| Ürün liste sayfası LCP | **KAPANDI** | 6352 ms — **bütçe kırık**, kök neden ölçüldü |
| **Kategori sayfası** — "ÖLÇÜLMEDİ" idi | **KAPANDI** | Aşağıdaki tablo |
| CLS / TBT taban çizgisi | **KAPANDI** | Dört sayfa için de tabloda |

### Kategori sayfası — ilk kez ölçüldü

`lighthouserc.cjs`'in URL listesinde **yok**; bu görev için ayrıca koşturuldu
(aynı desktop preset, 3 koşum, aynı nginx).

| Sayfa | Perf | LCP | **CLS** | TBT | FCP |
|---|---:|---:|---:|---:|---:|
| `/pages/categories.html` | 0.78 ⚠️ | **861 ms** ✅ | **0.5396** ❌ | **0 ms** ✅ | 676 ms |

**CLS 0.5396 — bütçenin 5.4 katı.** Üç koşumda da bit-bit aynı (0.5395542118893937),
yani kararlı ve yeniden üretilebilir bir kusur, gürültü değil.

Lighthouse'un `layout-shifts` denetimine göre kaymanın dağılımı:

| Kayma | Skor | Kaynak düğüm |
|---|---:|---|
| 1 | **0.5394** | **`<footer>`** |
| 2 | 0.0001 | `<div class="flex flex-col sm:flex-row gap-2 shrink-0 lg:ms-4">` |

**Kaymanın %99.98'i tek bir düğümden: `<footer>`.** Footer geç enjekte ediliyor ve
üstündeki her şeyi itiyor. Yer ayrılmadığı (min-height / iskelet) için tek başına
sayfanın CLS bütçesini patlatıyor. **Tek düğümlük, dar kapsamlı bir düzeltme.**

Ayrıca: `categories.html` ve `/` sayfalarında LCP öğesi
`<p data-i18n-html="cookieBanner.description">` — **çerez bandının metni**. LCP adayı
bir ürün görseli değil, çerez bandı. T-122'nin (LCP görseli için `<link rel="preload">`)
bu sayfalarda **hiçbir etkisi olmaz**; önce çerez bandının LCP adayı olmaktan
çıkarılması gerekir.

### Kapanmayan boşluk

| Boşluk | Durum | Neden |
|---|---|---|
| **INP** | **ÖLÇÜLEMEDİ** | Lighthouse 12.6.1'in `interaction-to-next-paint-insight` denetimi üç sayfada da `notApplicable` döndü. **Lab modunda Lighthouse INP üretemez** — INP gerçek kullanıcı etkileşimi gerektirir, sentetik koşumda etkileşim yoktur. Tek yolu ya saha (RUM) verisi ya da etkileşimi taklit eden bir betik. Bu bir koşum eksikliği değil, aracın yapısal sınırıdır. |

RUM ucu **yok** (`Media RUM Sample` DocType'ı yok — plan kova C, T-123). Yani INP
bugün ne lab'da ne sahada ölçülebilir durumda; **T-123 açılmadan INP boşluğu kapanmaz.**
Lab'da bulunabilen en yakın vekil: `max-potential-fid` = **16 ms**, TBT = **0 ms**
(dört sayfada da) — ikisi de ana iş parçacığının boş olduğunu gösteriyor, ama
**bunlar INP değildir** ve INP yerine raporlanmamalıdır.

---

## Ölçüm koşullarının dürüst beyanı

- **Makine paylaşımlı.** Bu koşumlar sırasında aynı makinede 14 Docker servisi ve
  başka ajanların derleme/test işleri çalışıyordu. Lighthouse sayıları
  (LCP/CLS/TBT/FCP) aracın kendi ürettiği ölçümlerdir ve raporlanabilir, ama
  **mutlak eşik kararı için sessiz bir makinede yeniden koşulmalıdır.** CLS
  esasen yükten etkilenmez (kategori sayfasındaki 0.5396 üç koşumda bit-bit aynı);
  LCP etkilenebilir.
- Ölçüm ortamı **dev Docker yığını**, prod değil. `X-Robots-Tag: noindex` ve
  `robots.txt Disallow: /` bu ortamın bilinçli fail-closed ayarıdır.
- Duvar saati süresi / FPS iddiası yapılmamıştır.
- **`tradehubfront/dist/` hakkında dürüst not:** deneme derlemem çıktısını geçici
  dizine yazdı (derleme günlüğü bunu doğruluyor; `vite.config.ts` içinde `dist`'e
  yazan sabit kodlu bir kanca yok). Buna rağmen `dist/` içeriği 06:02'de baştan
  yazıldı — büyük olasılıkla **eşzamanlı çalışan başka bir ajanın `npm run build`'i**,
  ama bunu kesin olarak atfedemiyorum ve tahmin yürütmüyorum. Ölçüm açısından önemi
  yok: sıkıştırmasız statik sunucu koşumu **05:55'te**, yani bu yazımdan **önce**
  yapıldı ve o sırada `dist/` 19 Ağu 13:00 tarihliydi. Kabul için kullanılan nginx
  koşumu ise yerel `dist/`'i değil Docker imajını ölçüyor; hiç etkilenmiyor.
- **Değiştirilen kaynak dosya: yok.** `package.json` / `package-lock.json` /
  `lighthouserc.cjs` / `dist/` **elle sürülmedi**. Lighthouse çıktıları ve deneme
  derlemesi repo dışına (`~/.claude/jobs/56428c2d/tmp/`) yazıldı.
- Ham Lighthouse raporları (9 + 3 JSON/HTML) geçici dizindedir; kalıcı olması
  isteniyorsa `tradehubfront/perf-reports/lhci` altına taşınmalıdır.

---

## Ölçümden çıkan iş kalemleri (bu turda yapılmadı)

| # | İş | Kanıt |
|---|---|---|
| 1 | **Medya boru hattını aç** (`media_pipeline_enabled`) — `products.html` LCP'sinin tek gerçek çözümü | 6352 ms LCP; tek sayfada ~5 MB ham görsel |
| 2 | **`categories.html` footer'ına yer ayır** (min-height/iskelet) | CLS 0.5396'nın 0.5394'ü `<footer>`'dan |
| 3 | **`lighthouserc.cjs`'e `categories.html` ekle** | Bütçe dosyası CLS'i en kötü sayfayı ölçmüyor |
| 4 | **`product-detail.html` URL'sini ürün kimlikli yap** | Config bugün boş durum ekranını ölçüyor |
| 5 | **Çerez bandını LCP adayı olmaktan çıkar** | `/` ve `categories.html`'de LCP öğesi çerez bandı metni |
| 6 | **Lockfile'ı tazele** (`npm install`) — `npm ci` CI'da bloke | `@emnapi/*` tutarsızlığı |
| 7 | **Crop B/C/E sınıfı ayrışması** — muhtemelen zoom'un `savePayload`'a girmemesi | B: 120 vakanın 119'u sapıyor, 7391 px'e kadar |
