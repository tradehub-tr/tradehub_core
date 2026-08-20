# FE Denetimi — Faz 6 (Image Engine) ve Faz 7 (Video Engine) — T-060…T-075

Salt okunur denetim. Hiçbir dosya değiştirilmedi. Kaynak belgeler: `50-faz6-image-engine.html`, `51-faz7-video-engine.html` (ikisi de WebFetch ile başarıyla çekildi).

Aranan dizinler: `admin-panel/frontend/src`, `tradehubfront/src`, çapraz kontrol için `tradehub_core`.

**Kritik bağlam:** `media_pipeline_enabled` ana bayrağı varsayılan olarak **0** (kapalı) — `tradehub_core/tradehub_core/patches/v15_9_22_media_engine_settings.py:24`. Bu, aşağıdaki birçok "KISMİ" kararın nedenidir: FE kodu doğru yazılmış ve gerçek backend sözleşmesine (srcset.py, picture.py) karşı test edilmiş olsa da, bayrak kapalıyken uçtan uca veri akmıyor ve panel/mağaza bunu dürüstçe boş/"—" olarak gösteriyor.

| Görev | Rol | FE payı | Durum | Kanıt (dosya:satır) | Eksik olan |
|---|---|---|---|---|---|
| T-060 | Backend | Probe+guard — belge kendisi "Yok" diyor | FE-DIŞI | `50-faz6-image-engine.html` özet tablosu: "Frontend Gereksinimi: Yok"; FE'de `probe`/`guard` kavramına karşılık gelen hiçbir kod yok (grep boş) | — |
| T-061 | Backend | Normalize sonucu manifestte (width, height, dpi, colorspace, has_alpha) | KISMİ | `admin-panel/frontend/src/components/media/MediaQualityPanel.vue:76-84` (width/height/megapiksel gerçek veriyle akıyor) ve `:97-99` (`dpi`, `colorSpace`, `alpha` satırları hep `"—"` — hiçbir uçtan gelmiyor, yorum satır 12-16'da açık) | dpi/colorspace/alpha hiçbir yerde FE'ye ulaşmıyor |
| T-062 | Backend | Sınıflandırma + format zinciri manifestte | YOK | Kod tabanında `classification`, `format_chain`, `job_type`, `video_from_animation` için sıfır eşleşme (admin-panel + tradehubfront, tüm src) | Manifest'te sınıf/format zinciri alanı hiç yok; hiçbir bileşen bunu okumuyor |
| T-063 | Backend | Rendition listesi, srcset/`<picture>` | KISMİ | Kod TAM: `tradehubfront/src/components/media/ResponsiveImage.ts:2-12,268-304` (tek nokta `<picture>` üretici) + `admin-panel/frontend/src/components/media/MediaImage.vue:29-36,210-216` + `admin-panel/frontend/src/lib/media/simulator/select.js:293` (backend `srcset.py` ile satır satır parite testi: `__tests__/srcsetParity.test.js`). Veri ucu BOŞ: `admin-panel/frontend/src/composables/useMediaRenditions.js:19-21` "Tablo şu an BOŞ: bayraklar kapalı, hiçbir türev üretilmedi" | Kod doğru ve test edilmiş ama `media_pipeline_enabled=0` olduğu için gerçek türev verisi akmıyor — panel "henüz üretilmedi" gösteriyor |
| T-064 | Backend | Version geçişinde 404 olmaması (pasif garanti) | FE-DIŞI | Media-engine idempotency/reprocess/`engine_signature` kavramlarına dair FE'de sıfır kod; bulunan tek "idempotency" eşleşmeleri lojistik/upload-session'a ait, medya motoruyla ilgisiz (`admin-panel/frontend/src/lib/media/upload/session.js:40,401` — farklı bir T-081 konusu) | FE'nin üretmesi gereken bir artefakt yok; davranış canlı ortamda ölçülür |
| T-065 | Backend | LQIP/BlurHash + dominant renk gösterimi | KISMİ | Bileşen mantığı GERÇEK ve test edilmiş: `admin-panel/frontend/src/components/media/MediaImage.vue:21-26,58,194,249` + `MediaVideo.vue:63,67-68,149` + XSS-güvenlik testi `components/media/__tests__/mediaCls.test.js:83-101`. Ama veri kaynağı boş: `admin-panel/frontend/src/composables/useSellerMedia.js` satır ~40-70 satır-eşleme fonksiyonunda `lqip` alanı YOK → `MediaThumb.vue:10`'daki `item.lqip` her zaman boş string. `tradehubfront` tarafında `lqip` kavramı manifest arayüzünde (`src/lib/media/manifest.ts:38-67`) hiç yok — mağaza tarafında sıfır destek. `dominant_color` hiçbir dosyada yok | Admin panelde prop var ama beslenmiyor; mağazada (buyer-facing) LQIP hiç yok; dominant renk hiçbir yerde yok |
| T-066 | Backend | Kalite raporu paneli (satıcı) | KISMİ | `admin-panel/frontend/src/components/media/MediaQualityPanel.vue` gerçek: `useMediaRenditions` ile bağlı, tasarruf oranı SADECE iki gerçek bayt varken hesaplanıyor (satır 109-118, "%0 tasarruf" fabrikasyonu yok), SSIM "0,000" yerine "—" (satır 120-125,188-198) — dürüst boş durum. `MediaDetailPanel.vue:227,327`'de gerçekten bağlı (kullanılıyor). Ama: `Media Quality Report` DocType'ı kurulu değil (satır 22-25) → "uygulanan işleme kararları" listesi yok; aylık platform raporu (yönetici tarafı) FE'de hiç yok | Karar listesi + yönetici aylık raporu eksik; mevcut olan kısım gerçek veriyle çalışıyor ama girdi çoğunlukla boş (flag kapalı) |
| T-067 | QA | Faz 6 kapanış regresyonu — belge "Yok" diyor | FE-DIŞI | `50-faz6-image-engine.html` özet tablosu: "Frontend Gereksinimi: Yok" (CI/QA işi) | — |
| T-070 | Backend | ffprobe — belge "Yok" diyor | FE-DIŞI | `51-faz7-video-engine.html`: "Frontend/Panel gereksinimleri: Yok" | — |
| T-071 | Backend | Karar gerekçeleri simülatörde gösterilecek | YOK | `admin-panel/frontend/scripts/sync-simulator.mjs:106-118` `video_decision.json`'dan YALNIZ `poster` bloğunun sayısal alanlarını (width, format, maxBytes, qualityLadder…) vendor'lıyor — karar KURALLARININ (`when`/`action`/`why`) kendisi ya da bir "işlem günlüğü/gerekçe" gösterimi FE'de yok. `SimPosterCard.vue:435` HLS merdiveninin de vendor'lanmadığını doğruluyor | Decision-table gerekçe/log gösterimi tamamen yok; yalnız poster parametreleri sızmış |
| T-072 | Backend | Transcode/benefit gate — belge "Yok" diyor | FE-DIŞI | `51-faz7-video-engine.html`: "Frontend/Panel gereksinimleri: Yok" | — |
| T-073 | Backend | Poster, preview klip, hareketli önizleme | KISMİ | `admin-panel/frontend/src/components/media/MediaVideo.vue:12-16,63-68,232` poster prop'u düzen-kaymasız render ediyor (kod gerçek). `tradehubfront/src/components/seller/StoreHeader.ts:303,395-401` posteri gerçekten kullanıyor — AMA kaynağı `tradehub_core/tradehub_core/api/seller.py:790,819` `poster_image` alanı, yani **elle yüklenen** bir görsel (`seed_demo_data.py:3454` Pexels stok fotoğrafı), T-073'ün ffmpeg tabanlı üretim hattı (`media/pipeline/video/poster.py`) DEĞİL. Asıl ürün tanıtım videosu `tradehubfront/src/components/product/ProductVideoSection.ts:63` `<video>` etiketine **poster hiç yazmıyor** — bu, panelin kendi denetim yorumuyla da doğrulanıyor: `admin-panel/frontend/src/components/media/simulator/SimPosterCard.vue:11-14` "poster üretmeyi biliyor ama onu çağıran bir API ucu kurulu DEĞİL". Preview klip / `prefers-reduced-motion` manifest varyantı hiçbir yerde yok | Gerçek motor-üretimi poster hiçbir FE yüzeyine bağlı değil (API ucu bile yok); ana ürün videosu poster'sız; preview klip ve reduced-motion dalı FE'de hiç yok |
| T-074 | Backend | HLS/adaptif teslim, uyumlu oynatıcı | KISMİ | `admin-panel/frontend/src/components/media/MediaVideo.vue:18-31,60-61,136-137` `hlsSrc` prop'u + native-HLS-only mantığı VAR ve belgelenmiş, ama **hls.js bilinçli eklenmedi** ("hls.js EKLENMEDİ. Yeni bağımlılık kararı bu görevin işi değil", satır 27-28) — bu belgenin istediği "Vue bileşeni hls.js'i tembel yüklemeli" gereksiniminden sapma. `hlsSrc` grep'i yalnız TANIM ve mantığı buluyor; hiçbir çağıran (`MediaDetailPanel.vue`, `MediaPreviewModal.vue`) gerçek bir `.m3u8` geçmiyor — mekanizma besleniyor değil. `tradehubfront`'ta `.m3u8`/`hls` için sıfır eşleşme — mağazada hiç yok. `SimPosterCard.vue:435` HLS merdiveninin (360p/480p/720p/1080p) simülatöre de vendor'lanmadığını doğruluyor | hls.js yok (bilinçli); gerçek HLS kaynağı hiçbir yerde beslenmiyor; mağazada sıfır destek; adaptif bitrate göstergesi yok |
| T-075 | QA | Faz 7 kapanış — panelde video durumu (isteğe bağlı) | FE-DIŞI | `51-faz7-video-engine.html` özet tablosu bu satırı "(isteğe bağlı)" olarak işaretliyor; QA/regresyon raporu esasen CI işi. FE'de buna karşılık gelen bir "video işlem durumu" widget'ı bulunamadı | — |

## Sayım

Toplam **14** görev denetlendi.

| Durum | Adet | Görevler |
|---|---|---|
| TAM | 0 | — |
| KISMİ | 6 | T-061, T-063, T-065, T-066, T-073, T-074 |
| YOK | 2 | T-062, T-071 |
| FE-DIŞI | 6 | T-060, T-064, T-067, T-070, T-072, T-075 |
| ÖLÇÜLEMEDİ | 0 | — |

6 + 2 + 6 = 14 ✓

## En önemli 3 bulgu

1. **Ana bayrak kapalı — bütün "KISMİ"lerin ortak nedeni.** `media_pipeline_enabled` varsayılan **0** (`tradehub_core/tradehub_core/patches/v15_9_22_media_engine_settings.py:24`). FE'nin rendition listesi (T-063) ve kalite paneli (T-066) kodu gerçek, backend sözleşmesine karşı test edilmiş ve dürüst boş-durum mesajları basıyor (`useMediaRenditions.js:19-21`: "bayraklar kapalı, hiçbir türev üretilmedi") — ama bugün gerçek veriyle hiç dolmuyor. Bu, kod kusuru değil, dağıtım/konfigürasyon durumu; rapor bunu KISMİ olarak işaretledi (uydurma sayı yok, dürüst ilan var).

2. **Poster (T-073) iki ayrı, birbirinden kopuk yol üzerinden akıyor — hiçbiri gerçek video motoruna bağlı değil.** Mağazanın satıcı vitrini (`StoreHeader.ts`) elle yüklenen `poster_image` alanını kullanıyor (`api/seller.py:819`, seed verisinde Pexels stok fotoğrafı) — T-073'ün ffmpeg tabanlı "ilk anlamlı kare" üretimiyle (`media/pipeline/video/poster.py`) hiçbir ilişkisi yok. Asıl ürün tanıtım videosu (`ProductVideoSection.ts:63`) posteri **hiç yazmıyor**. Panelin kendi simülatör yorumu bunu doğruluyor: motor posteri üretmeyi biliyor ama "onu çağıran bir API ucu kurulu DEĞİL" (`SimPosterCard.vue:13-14`) — yani backend entegrasyonu da eksik, sadece FE değil.

3. **LQIP (T-065) admin panelde "bağlanmamış tesisat", mağazada tamamen yok.** `MediaImage.vue`/`MediaVideo.vue` LQIP'i doğru ve güvenli (XSS testli) şekilde render ediyor, ama veriyi besleyen `useSellerMedia.js` satır-eşleyicisi `lqip` alanını hiç taşımıyor — prop pratikte her zaman boş. `tradehubfront` manifest arayüzünde (`lib/media/manifest.ts`) `lqip` diye bir alan yok — buyer-facing sayfalarda blur placeholder hiç gösterilmiyor. `dominant_color` da kod tabanının hiçbir yerinde yok.

## Ölçemediklerin

- **Gerçek tarayıcı davranışı** (LQIP'in gerçekten CLS'siz göründüğü, video autoplay/HLS'in gerçekten çalıştığı, `<picture>` seçiminin gerçek cihazda doğru basamağı indirdiği) — yalnız statik kod okundu, tarayıcı/Playwright koşturulmadı. `MediaVideo.vue:48-53`'ün kendi yorumu da bunu doğruluyor: "Gerçek oynatma… ve CLS SKORU ölçülmedi."
- **`npm test` gerçekten yeşil mi** — `srcsetParity.test.js`, `mediaCls.test.js`, `mediaDelivery.test.js` gibi testlerin varlığı ve içeriği okundu, ama test suite bu denetimde çalıştırılmadı (salt okunur kural gereği; ayrıca komut koşturma zaten görev kapsamı dışı tutuldu).
- **`media_pipeline_enabled` açıldığında uçtan uca gerçekten doğru veri geleceği** — kod okunarak makul görünüyor (parite testleri var) ama canlı/staging ortamda doğrulanmadı.
- **Süre, performans, sıkıştırma oranı iddiaları** — hiç ölçülmedi, rapora hiçbir sayı yazılmadı (kural 6).
