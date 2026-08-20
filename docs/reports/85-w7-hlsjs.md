# 85 — W7: hls.js entegrasyonu (FE yarısı)

**Tarih:** 2026-08-20 · **Kapsam:** admin-panel/frontend + tradehubfront · **Commit:** atılmadı (talimat gereği)

Rapor 81'in devamı: HLS artık gerçekten üretiliyor (master + 3 basamak);
bu iş oynatıcı tarafını kurdu. Backend manifest ucu (W7-1, paralel) bu işin
DIŞINDA — uca kablolama sonraki turda.

## Ne yapıldı

### Ortak karar (iki repoda aynı sözleşme)

1. Tarayıcı HLS'i **yerli** çözüyorsa (Safari/iOS `canPlayType`) → hls.js hiç indirilmez.
2. Yerli destek yok + `.m3u8` kaynak → hls.js **dinamik `import()`** ile gelir, MSE üzerinden çalar.
3. Motor gelmezse (MSE yok / import patladı) → progresif kaynağa düşülür; hiçbir yol fırlatmaz.

hls.js `^1.7.1` (npm latest, 2026-08-20). API Context7 `/video-dev/hls.js`ten
doğrulandı: `isSupported`, `loadSource`/`attachMedia`, ölümcül `MEDIA_ERROR`da
tek hak `recoverMediaError`, diğer ölümcüllerde `destroy` (dokümandaki öneri).

### Panel (`admin-panel/frontend`)

- **Yeni** `src/components/media/delivery/hlsPlayback.js` — saf karar
  (`decidePlayback`), savunmacı motor yükleyici (`loadHlsEngine`, `web-vitals`
  `collector.js` deseniyle aynı), bağlama+hata protokolü (`startHlsPlayback`).
- `src/components/media/MediaVideo.vue` — `attach()` (görünürlük anı) artık
  `engageHls()` da çağırıyor: motor bile görünürlükten önce indirilmez.
  Davranış sözleşmesi korunuyor: kaynaklar görünürlüğe kadar bağlanmaz,
  `background`/`reduce` kuralları aynen, hls yolu da tıkanırsa progresif
  `<source>`a düşülür, o da yoksa `error` emit. Yarış bileti: import
  beklerken kaynak değişir/söküm olursa eski bağlanma iptal.
- `package.json`/`package-lock.json` — `hls.js: ^1.7.1`.
- **Yeni test** `delivery/__tests__/hlsPlayback.test.js` (14 test): karar
  tablosu, yükleyici savunması, sahte-Hls ile hata protokolü, "hls.js yalnız
  dinamik import" kaynak sözleşmesi, SSR'da tembelliğin sürdüğü.
  `mediaDelivery.test.js`e DOKUNULMADI.

### Storefront (`tradehubfront`)

Ölçüm — `<video>` basan yüzeyler: `ProductVideoSection.ts` (ürün tanıtım),
`StoreHeader.ts` (satıcı vitrin ana medya + küçük resimler),
`CompanyProfile.ts` (video modalı), ayrıca `toVideoEmbedHtml` üzerinden
galeri ana medya / lightbox / MediaViewer; `brand/rfq/trade-assurance`
statik mp4 (HLS adayı değil, dokunulmadı).

- **Yeni** `src/utils/hlsVideo.ts` — `isHlsUrl`, `attachVideoSource`
  (karar + yarış iptali + hata protokolü), `hydrateHlsVideos` +
  `ensureHlsHydration` (MutationObserver: `innerHTML` ile giren
  `video[data-hls-src]` otomatik bağlanır — bu projede video HTML'i dizge
  olarak çok noktadan basılıyor).
- **Yeni** `src/alpine/videoSrc.ts` — `x-video-src` direktifi
  (`evaluateLater`/`effect`/`cleanup`, Alpine v3 deseni Context7 doğrulandı);
  `src/alpine/index.ts`te kayıt.
- `ProductVideoSection.ts` — `toVideoEmbedHtml`e HLS dalı (`data-hls-src`,
  düz `src` basılmaz) + `poster` parametresi. `ProductVideoSection()` bugünkü
  veriden `p.videoPoster` bağlar (elle yüklü alan; manifest posteri sonraki
  tur aynı alandan akar), `data-listing-poster` swap için saklanır; varyant
  videosunda listing kapağı bilerek kullanılmaz. Galeri/lightbox/MediaViewer
  aynı fonksiyonu kullandığından HLS dalını bedavaya alır.
- `StoreHeader.ts` ana video + `CompanyProfile.ts` modal videosu →
  `:src` yerine `x-video-src`. (StoreHeader küçük-resim `<video src+#t=0.5>`
  bilerek bırakıldı: HLS öğelerinde `item.poster` yolu zaten var; manifest
  posteri gelince o dolacak.)
- `types/product.ts` + `listingService.ts` — `videoPoster` geçişi (API bugün
  basmıyor; bastığı gün otomatik akar; boş/whitespace poster sayılmaz).
- `vite.config.ts` — `vendor-hls` manualChunk (repo kuralı: >50KB lib).
  Chunk yalnız dinamik import'tan referanslı → tembel kalıyor.
- **Yeni testler**: `src/utils/hlsVideo.test.ts` (12) +
  `src/components/product/ProductVideoSection.test.ts` (9).

## Doğrulama (hepsi ölçüldü)

| Kontrol | Sonuç |
|---|---|
| Panel `npm test` | 900 test / **893 pass / 2 fail / 5 skip** (taban 879+ korunuyor; 2 kırık aşağıda) |
| Panel yeni test dosyası | 14/14 yeşil |
| Panel eslint | 0 hata (2 uyarı `views/permission/PlansTab.vue` — başka ajanın dosyası) |
| Panel `vite build` | 0; `hls-*.js` 594 KB ayrı chunk, `dist/index.html`te REFERANSSIZ (tembel) |
| Storefront `tsc --noEmit` | 0 |
| Storefront vitest | 292 test / **286 pass / 6 fail** — taban ile AYNI 3 dosya/6 test (aşağıda) |
| Storefront eslint | 0 hata 0 uyarı |
| Storefront `npm run build` | 0; `vendor-hls-*.js` 592 KB ayrı chunk, HTML'lerde referanssız |
| `check:dup` | temiz |
| Panel lockfile konteyner `npm ci --dry-run --ignore-scripts` (node:22-alpine) | exit 0 |
| Storefront lockfile aynı kontrol | exit 0 |

**Vacuity (ikisi de yapıldı, geri alındı):**
- Panel: `decidePlayback` "her zaman progresif"e bozuldu → 1 test kırmızı; geri alındı → 14/14.
- Storefront: `isHlsUrl` "her zaman false"a bozuldu → 10 test kırmızı; geri alındı → 21/21.

## Bilinen kırıklar — BENİM DOSYALARIMDAN DEĞİL (düzeltilmedi, talimat gereği)

- **Panel 2 fail:** `simulator/__tests__/videoDecision.test.js` ve
  `lib/media/simulator/__tests__/srcsetParity.test.js` — ikisi de vendored
  kopyaları **canlı `tradehub_core` kaynağıyla** karşılaştıran parite
  testleri. `tradehub_core`da paralel ajanın (W7-1) commitsiz medya-pipeline
  değişiklikleri duruyor (`media/pipeline/...` git-modified); fark
  `video_decision.json`/manifest hash'lerinde. Simulator alanı bu görevde
  yasaklı; dokunulmadı. Backend işi commitlenince `sync:simulator` ile
  vendored kopyalar tazelenmeli.
- **Storefront 6 fail (taban ile birebir aynı):** `ProductOrderPanel.test.ts`
  (4, kampanya rozeti/panel yerleşimi), `ProductBuyBox.test.ts` (1,
  `pd-price-tiers`), `messages.test.ts` (1, `BottomNav` mock eksiği) —
  üçü de video/HLS/poster'a değmeyen, paralel işlerin yüzeyleri.

## Ölçülmeyen

Gerçek HLS oynatma (segment akışı, ABR basamak geçişi) — hls.js jsdom/
happy-dom'da çalışmaz, canlı tarayıcı ister; bu turda tarayıcı doğrulaması
yapılmadı. Manifest ucuna kablolama ve manifest-türevi poster sonraki turun işi.
