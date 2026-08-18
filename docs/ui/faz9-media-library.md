# Faz 9 — Media Library UI (T-090…T-095) · Kapsam Haritası ve Uygulama Planı

**Tarih:** 2026-08-18 · **Kapsam:** analiz + plan · **Kod yazılmadı** (admin-panel ayrı depo, salt oku).

Bu belge "yeniden yaz" belgesi değildir. Panelde **9.448 satır** medya arayüzü ve ek
olarak **19 medya bileşeni** zaten çalışıyor. Aşağıdaki her satır, o çalışan koda karşı
T-090…T-095'in kabul kriterlerinin tek tek denetlenmesidir.

---

## 0. Yöntem — bu belgedeki sayılar nereden geldi

Tüm sayımlar `/Users/ahmet/Desktop/istoc/admin-panel/frontend/` üzerinde, kaynak
dosyaların **`<template>` bloğu ayrıştırılarak** yapıldı (naif `grep` değil: `<script>`
içindeki `title:` alanları ve HTML yorumları sayımı kirletiyordu; ilk denemede
`MediaOptimizeView` şablonu hiç taranmadan "0 hata" çıktı, çünkü o dosyada `<script>`
başta duruyor).

| Ölçüm | Nasıl |
|---|---|
| Buton erişilebilir adı | `<template>` içinden `<button>…</button>` blokları çıkarıldı; açılış etiketinde `aria-label`/`aria-labelledby`/`title` **veya** gövdede metin arandı |
| i18n eşitliği | `tr.js` / `en.js` düzleştirilip anahtar kümeleri karşılaştırıldı (Node) |
| Sayfa tavanı | `stores/media.js` → `useSellerMedia.js` → `api/seller_media.py` → `media/inventory.py` çağrı zinciri okundu |
| DOM maliyeti | `MediaCard` + `MediaThumb` şablonlarındaki eleman etiketleri sayıldı |

**Tarayıcıda çalıştırılmadı.** Kare hızı, ana iş parçacığı bloklama süresi, gerçek LCP/CLS
değerleri ve axe-core taraması **ÖLÇÜLMEDİ** — §9'a bakınız.

---

## 1. Envanter — bugün ne var

### 1.1 Ekranlar

| Dosya | Satır | Rol | Faz 9 ile ilişkisi |
|---|---:|---|---|
| `src/views/seller/MediaLibraryView.vue` | 2.636 | **Satıcı medya kütüphanesi** | T-090…T-095'in **asıl hedefi** |
| `src/views/system/MediaExplorerView.vue` | 770 | Yönetici dosya gezgini (sanal klasör ağacı, `media/browse.py`) | T-094'ün *yönetici* karşılığı; satıcı klasörü değil |
| `src/views/system/MediaOptimizeView.vue` | 2.334 | Toplu optimizasyon kuyruğu | T-093 "reprocess" ve T-094 toplu işlem için **hazır kalıp** |
| `src/views/system/MediaBackupView.vue` | 1.027 | Yedek/geri yükleme | Faz 9 kapsamı dışı (TUR-131) |
| `src/views/system/MediaAuditView.vue` | 2.681 | Denetim kaydı + canlı izleme | T-093 "History" sekmesi için **hazır veri kaynağı** |

### 1.2 Bileşenler (`src/components/media/`, 19 dosya)

`MediaCard` · `MediaThumb` · `MediaDetailPanel` · `MediaFilterRail` · `MediaFilterChips` ·
`MediaBulkBar` · `MediaUploadQueue` · `MediaPickerModal` · `MediaPreviewModal` ·
`MediaShortcutsModal` · `MediaModal` · `MediaPickButton` · `MediaRecordDialog` ·
`MediaUsageDialog` · `mediaActions.js` + `__tests__/` (2 test dosyası)

### 1.3 Veri katmanı

```
MediaLibraryView.vue
  └─ stores/media.js (841 satır, Pinia setup store)
       └─ composables/useSellerMedia.js  → tradehub_core.api.seller_media.*
            └─ tradehub_core/media/inventory.py  (MAX_PAGE_SIZE = 200)
```

Ayrı ve **kullanılmayan ikinci yükleme yolu**: `src/lib/upload-ui/` (1.669 satır
**TypeScript**, storefront ile ortak) → `components/upload/MultiFileUpload.vue`,
`SlotUpload.vue`. Medya kütüphanesi bu yolu kullanmıyor; kendi `useDropzone` +
`store.enqueueUploads` yolunu kullanıyor. **İki upload yolu, iki farklı önkontrol.**

---

## 2. Kapsam haritası — T-090…T-095

Kısaltma: ✅ karşılanmış · 🟡 kısmen · ❌ yok

### T-090 — Frontend iskelet, tasarım sistemi, API istemcisi

| Kabul kriteri | Durum | Kanıt |
|---|:--:|---|
| Vue 3 + Pinia + Vite | ✅ | `package.json`: vue, pinia, vue-router, vite |
| **TypeScript strict** | ❌ | Panelde `tsconfig.json` **yok**. Tüm `.vue` dosyaları `<script setup>` (JS). Tek TS adası: `src/lib/upload-ui/*.ts` (9 dosya) |
| **Vitest** | ❌ | `package.json` → `"test": "node --test \"src/**/*.test.js\""`. Vitest bağımlılığı yok, DOM testi yok |
| Lint + type check CI'da | 🟡 | `eslint` + `prettier` var; `vue-tsc`/tip denetimi yok |
| Tasarım sistemi bileşenleri | ✅ | `components/common/`: `ConfirmDialog`, `DataTable`, `ListPagination`, `ViewModeToggle`, `AppIcon`, toast (`useToast`) — hepsi karanlık tema uyumlu (`assets/scss/` `@include dark`) |
| OpenAPI tipli API istemcisi | ❌ | `utils/api.js` elle yazılmış; şema üretimi yok |
| Hata→mesaj eşlemesi merkezi | ✅ | `uploadPolicy.precheck()` **metin değil kod** döner (`upload_ext_denied` vb.); çeviri ekranın işi. Doğru kalıp, korunmalı |
| i18n TR/EN, her metin anahtar üzerinden | ✅ | 711 medya anahtarı, **%100 eşit** (§7.1). Şablonlarda sabit Türkçe metin bulunamadı — **tek istisna** `components/common/ListPagination.vue:57` → `` `${n} / sayfa` `` |

### T-091 — Uppy + tus yükleyici ve preflight paneli

| Kabul kriteri | Durum | Kanıt |
|---|:--:|---|
| Sürükle-bırak, çoklu dosya | ✅ | `composables/useDropzone.js`; `MediaLibraryView.vue:53` (`<input multiple>`) |
| Klasör bırakma, yapıştırma (paste) | ❌ | `webkitGetAsEntry` / `paste` dinleyicisi yok |
| Dosya başı preflight — **boyut** | ✅ | `utils/uploadPolicy.js:145` (`upload_too_large`) |
| Preflight — **format / deny-list** | ✅ | `uploadPolicy.js:130-142`; sunucudaki sırayla **aynı** (yorumda gerekçesi yazılı) |
| Preflight — **magic-byte / zararlı içerik** | ✅ | `uploadPolicy.js:90` `sniffDangerous()` — ilk 512 bayt |
| Preflight — **MP (megapiksel)** | ❌ | Yok |
| Preflight — **DPI** | ❌ | Yok. `exifr` bağımlılığı yok |
| Preflight — **alfa kanalı** | ❌ | Yok |
| Preflight — **video süre/codec** | ❌ | Yok. `mediainfo.js` bağımlılığı yok |
| **Web Worker'da** çalışması | ❌ | `precheck()` ana iş parçacığında, `enqueueUploads` içinde `for … await` ile **seri** (`stores/media.js:626`) |
| Politika ihlali yüklemeyi engeller | ✅ | `stores/media.js:648` → `status: "error"`, `runUpload` çağrılmaz |
| İhlal metni + **çözüm yolu** | 🟡 | Kod → çeviri var; "ne yapmalıyım" yönlendirmesi yok |
| İstemcide küçültme (cihaz bütçesine göre) | 🟡 | `lib/media/compress.image.js`: **sabit** 1920px / 0,5 MB. Cihaz bütçesi yok, slot politikası okunmuyor |
| Sunucuya devretme + kullanıcıya bildirim | 🟡 | WebP desteklenmiyorsa JPEG q85 fallback var (`compress.image.js:41`); kullanıcıya bildirilmiyor |
| **Resumable / tus** | 🟡 | Parçalı yükleme **var** (`useSellerMedia.js:286` `uploadChunked` → `upload_begin/chunk/finish/abort`) ama tus değil, **base64** ile (+%33 ağ yükü) |
| **Sayfa yenilenince oturum korunur** | ❌ | `uploads` sadece bellekte (`stores/media.js`); `upload_id` hiçbir yere yazılmıyor. Yenile → kuyruk kaybolur, sunucuda yarım oturum kalır |
| 50 dosyada akıcı arayüz (<50 ms blok) | ❌ | `enqueueUploads` her dosya için `runUpload(id)` **hemen** çağırıyor → **eşzamanlılık sınırı yok**. 50 dosya = 50 paralel istek. (İlginç: kullanılmayan `lib/upload-ui/uploader.ts:54` içinde `concurrency ?? 2` **zaten var**) |

### T-092 — Varlık ızgarası, arama, filtre, sanal kaydırma

| Kabul kriteri | Durum | Kanıt |
|---|:--:|---|
| Izgara + liste + tablo + kanban görünümü | ✅ | `MediaLibraryView.vue:366` (grid), `:390` (rows), `DataTable`, `ViewModeToggle` |
| Arama: dosya adı | ✅ | `stores/media.js:244` `filtered`, 300 ms debounce (`MediaLibraryView.vue` `SEARCH_DEBOUNCE`) |
| Filtre: etiket, tür, sahip, format, yön, boyut, tarih, kullanım | ✅ | `stores/media.js:186-208` — 14 ayrı filtre + `useDataTable` sözleşmesi |
| Filtre: **ürün, durum, slot** | ❌ | Slot kavramı arayüzde **hiç yok** (§8) |
| Aralık filtreleri (tarih, boyut) | ✅ | `sizeRange`, `usageRange`, `dateRange` |
| **10.000 varlıkta akıcı kaydırma / sanal kaydırma** | ❌ | Sayfalama var (12/24/48), sanal kaydırma **yok**. `vue-virtual-scroller` bağımlılığı yok. **Asıl sorun sanal kaydırma değil, 200'lük tavan** → §5 |
| **LQIP yer tutucu, CLS = 0** | 🟡 | CLS koruması **var** ama LQIP **yok** → §6 |
| **Filtre durumu URL'de** | ❌ | `MediaLibraryView.vue` içinde `useRoute`/`useRouter` **hiç yok**. Paylaşılabilir bağlantı ve geri tuşu çalışmıyor. **Kalıp panelde mevcut:** `MediaAuditView.vue:115-146` (URL_KEYS + `router.replace` + `watch(route.query)`) |
| Canlı durum rozetleri | 🟡 | `videoStatus` rozeti var (`useSellerMedia.js` `video_status`) |
| **Frappe realtime ile güncelleme** | ❌ | `socket.io` bağımlılığı yok, `frappe.realtime` çağrısı yok. Yoklama (polling) da yok — `MediaAuditView` `REFRESH_INTERVALS` ile yokluyor, kütüphane yoklamıyor |
| **Tek `manifest_batch` isteği (N+1 yok)** | ❌ | Her `<img>` `item.fileUrl` (ORİJİNAL dosya) çekiyor → §6 |
| Klavye gezinme (oklar, boşlukla seçim, shift+tık aralık) | ✅ | `composables/useMediaShortcuts.js` (105 satır): `←→↑↓`, `Enter`, `Space`, `Shift+Space` aralık, `Ctrl+A`, `Ctrl+Z`, `/`, `p`, `a`, `Delete`, `Escape`. `MediaShortcutsModal` ile keşfedilebilir. **Faz 9'un en iyi karşılanmış maddesi** |

### T-093 — Varlık detay çekmecesi: sürümler, türevler, kullanım, kalite

| Kabul kriteri | Durum | Kanıt |
|---|:--:|---|
| Detay paneli var | ✅ | `components/media/MediaDetailPanel.vue` (16 KB), `MediaLibraryView.vue:605` |
| Üstveri düzenleme (başlık, alt, açıklama, etiket) | ✅ | `MediaDetailPanel.vue:64-98` |
| **Sekmeli düzen (Özet / Türevler / Kullanım / Kalite / Geçmiş)** | ❌ | Panel **tek sütun, düz**. `tab` kelimesi şablonda hiç geçmiyor |
| Kaynak ↔ normalize edilmiş **yan yana** karşılaştırma | ❌ | Yalnız `size` + `dimensions` (`:46`, `:50`). Kaynak/sonuç ayrımı yok |
| **Sade dilde kalite raporu** ("3000×3000 → 2400×2400; 12,4 MB → 1,1 MB") | ❌ | Yok |
| Renk uzayı / alfa / DPI gösterimi | ❌ | Yok. Arka uçta `th_media_width` **0/2853 dolu** (%0) — veri de yok |
| **Türev listesi** (profil/format/genişlik/boyut/SSIM) | ❌ | Yok. `tradehub_core/media/pipeline/quality/ssim.py` **hazır**, arayüze bağlanmamış |
| Eksik basamak + **sebebi** | ❌ | Yok. `Variant.available=False` sözleşmesi `tradehub_core/media/pipeline/contracts/delivery.py:80` içinde tanımlı, tüketilmiyor |
| Kullanım listesi (hangi üründe) | ✅ | `MediaDetailPanel.vue:127-139` + `stores/media.js:173` `loadUsage`. **`usageDetail: null` = "henüz sorulmadı"** ayrımı doğru kurulmuş — boş dizi olsaydı panel "kullanılmıyor" derdi |
| Eylem: yeniden işle (reprocess) | ❌ | Kütüphanede yok. `MediaOptimizeView` yönetici tarafında yapıyor |
| Eylem: kırpma stüdyosu | ❌ | Yok |
| Eylem: indir (yetki kontrollü) | ✅ | `rowActions` `download` |
| Eylem: silme talebi | ✅ | `purge` + `archive` + kullanımdaysa **kilitli** (`MediaLibraryView.vue:757`) |
| **Denetim kaydı görünür** | ❌ | Kütüphanede yok. `MediaAuditView` (2.681 satır) **aynı veriyi** yönetici tarafında gösteriyor |

### T-094 — Klasör/etiket organizasyonu ve toplu işlemler

| Kabul kriteri | Durum | Kanıt |
|---|:--:|---|
| **Klasör ağacı (satıcı kapsamlı)** | ❌ | `folder`/`klasör` geçen tek satır yok. `Media Folder` DocType yok |
| Sürükle-bırak taşıma, yeniden adlandırma | ❌ | Klasör yok. (`vuedraggable` bağımlılığı mevcut — kullanılabilir) |
| Etiket filtreleme | ✅ | `stores/media.js` `tagFilter` (AND mantığı), `availableTags` etiket bulutu |
| **Toplu etiketleme** | ✅ | `stores/media.js:434` `addTagToMany` + `MediaBulkBar.vue:15` |
| Toplu arşivle / sil | ✅ | `archiveMany:451`, `removeMany:482`, `purgeMany:508` |
| Toplu indir | ✅ | `MediaBulkBar.vue:21` |
| **Toplu yeniden işle** | ❌ | `MediaBulkBar`'da yok |
| **Toplu taşıma** | ❌ | Klasör yok |
| **İlerleme + kısmi hata raporu** ("48 başarılı, 2 başarısız — sebepleri") | ❌ | `_toplu()` (`api/seller_media.py:173`) sayaç döndürüyor; arayüz tek toast gösteriyor, satır satır sebep göstermiyor |
| Geri alınabilir silme (grace period) | ✅ | `stores/media.js` `undoEntry` + `undo():585` + `Ctrl+Z`. Arka uçta `media/trash.py` 30/30 gün |

### T-095 — Erişilebilirlik ve i18n doğrulaması

→ Ayrıntılı ölçüm §7'de. Özet: **i18n neredeyse tam, erişilebilirlik araçları sıfır.**

| Kabul kriteri | Durum |
|---|:--:|
| axe-core taramasında kritik/ciddi bulgu yok | ❌ (araç kurulu değil) |
| Yalnız klavye ile tam akış | 🟡 (kısayollar var, odak yönetimi eksik) |
| Yükleme ilerlemesi/hataları `aria-live` ile duyuruluyor | ❌ (5 ekranda **0** `aria-live`) |
| TR/EN tam, eksik anahtar CI'yı kırar | 🟡 (tam ama CI denetimi yok) |
| Renk kontrastı AA | ❌ ÖLÇÜLMEDİ |
| Hata yalnız renkle değil, ikon + metinle | ✅ |

---

## 3. Özet tablo

| Görev | Karşılanan | Kısmi | Eksik | Kabaca |
|---|---:|---:|---:|---:|
| T-090 İskelet & DS | 4 | 1 | 3 | **~%55** |
| T-091 Yükleyici & preflight | 5 | 4 | 8 | **~%40** |
| T-092 Izgara & sanal kaydırma | 6 | 1 | 6 | **~%50** |
| T-093 Detay çekmecesi | 4 | 0 | 9 | **~%30** |
| T-094 Klasör & toplu işlem | 5 | 0 | 5 | **~%50** |
| T-095 Erişilebilirlik & i18n | 1 | 2 | 3 | **~%35** |

Yüzdeler kabul kriteri **sayısına** göre; ağırlıklandırılmadı.

---

## 4. Eksikler için uygulama planı

Her madde: **hangi dosya · hangi satır · hangi bileşen**.
Sıralama bağımlılığa göre; A blokları diğerlerinin önkoşulu.

### A1 — 200'lük tavanı kaldır (T-092, **her şeyin önkoşulu**)

**Sorun.** `stores/media.js:139` sabit `pageSize: 200` istiyor;
`tradehub_core/media/inventory.py:49` `MAX_PAGE_SIZE = 200` ile tavanlıyor. Filtreleme,
sayaçlar, etiket bulutu ve sıralama **hepsi bu 200'lük dilim üzerinde** çalışıyor
(`stores/media.js:244` `filtered`, `:230` `counts`, `:300` `availableTags`).

**Yapılacak — arka uç** (`tradehub_core/` altına **yazılmaz**, `tradehub_core/media/pipeline/api/` altına yeni uç):

1. `tradehub_core/media/pipeline/api/library.py` (yeni) — `inventory.list_files` üzerine ince sarmalayıcı:
   - `list_assets(cursor, limit, filters)` → imleç (cursor) tabanlı; `limit ≤ 100`
   - filtreler **SQL'e** iner: `kind`, `ext`, `tags`, `usage_state`, `size_min/max`,
     `date_from/to`, `orientation`, `archived`
   - `facets` ayrı uçtan: `list_facets(filters)` → `{counts, tags, formats}` — sayaçlar
     dilimden değil `COUNT(*)`'tan gelmeli
2. Test: `tests/test_library_api.py` — imleç kararlılığı (aynı imleç aynı sayfayı verir),
   filtre + facet tutarlılığı, kiracı sınırı (`ownership.scope`).

**Yapılacak — panel** (`stores/media.js`):

- `filtered` / `paged` / `counts` / `availableTags` / `availableFormats` computed'ları
  **sunucu yanıtına** dönüştürülür; istemci süzgeci silinir (~130 satır düşer)
- `serverTotal` (`stores/media.js:108`, **bugün tanımlı ama arayüzde kullanılmıyor**)
  `counts.all` yerine başlığa bağlanır → `MediaLibraryView.vue:10`

> **Bugünkü hata:** 10.000 varlıkta başlık *"200 dosya"* yazar. `media.pageSubtitle`
> (`i18n/locales/tr.js:8474` = `"{count} dosya · {size}"`) `counts.all` ile besleniyor ve
> `counts.all` 200'lük dilimden sayıyor. Kullanıcıya **yanlış sayı** gösteriliyor.

### A2 — `manifest_batch` ve türev teslimi (T-092/T-093, LQIP'in önkoşulu)

`tradehub_core/media/pipeline/contracts/delivery.py:125` `RenderManifest.to_dict()` **tam olarak arayüzün
ihtiyacı olan sözlüğü** üretiyor (`src`, `srcset`, `sizes`, `width`, `height`,
`aspect_ratio`, `loading`, `decoding`, `sources[]`). Tüketen yok.

1. `tradehub_core/media/pipeline/api/manifest.py` (yeni) → `manifest_batch(keys[], slot, context)`
   - girdi en çok 100 anahtar (`seller_media.MAX_BATCH = 200` ile hizalı, daha dar)
   - çıktı `{key: RenderManifest.to_dict()}`
   - `to_dict()` çıktısına **`lqip`** alanı eklenir (§6)
2. `stores/media.js` → `loadReal()` sonrası tek `manifest_batch` çağrısı; sonuç
   `item.manifest` olarak saklanır
3. `components/media/MediaThumb.vue` → `<img :src>` yerine `<picture>` + `<source
   :srcset :type>` + `:sizes`; `width`/`height` öznitelikleri manifest'ten

### A3 — Sanal kaydırma (T-092)

**A1'den sonra.** Bağımlılık: `vue-virtual-scroller` (kurulu değil) veya ~120 satırlık
kendi penceresi. Sürüm uyarısı: `vue-virtual-scroller` v2 Vue 3 için `@next` etiketinde —
kurmadan önce `context7` ile doğrulanmalı (proje kuralı).

- `MediaLibraryView.vue:366` `<ul class="mgrid">` → `<RecycleScroller>`
- `:390` `<ul class="mrows">` → aynı
- `MediaCard` sabit yükseklikli olmalı (bugün `MediaThumb` `padding-top: 100%` ile
  zaten sabit oran veriyor → **uygun**)
- `useMediaShortcuts` imleci (`MediaLibraryView.vue:1218` `cursor`, `:1646`
  `scrollIntoView`) sanal listede `scrollToItem(index)` ile değiştirilir — bugünkü
  `gridEl.children[cursor]` sanal listede **çalışmaz**, bu satır kırılacak

### A4 — Preflight'ı slot politikasına bağla + Worker'a taşı (T-091)

`tradehub_core/media/pipeline/policy/engine.py` (1.278 satır) `PolicyEngine.evaluate(slot, probe, role)`
→ `Decision.to_dict()` **hazır**. Panelin `uploadPolicy.precheck()` (174 satır) bunun
%20'sini kapsıyor.

1. `src/workers/preflight.worker.js` (yeni)
   - `createImageBitmap()` → genişlik/yükseklik → **MP**
   - `exifr` (yeni bağımlılık, ~30 KB) → **DPI**, EXIF yönü
   - PNG `IHDR` bayt 25 (color type 4/6) → **alfa**; WebP `VP8L`/`ALPH` chunk
   - video: `HTMLVideoElement.loadedmetadata` → **süre**; codec için `mediainfo.js`
     (~1 MB wasm) **ya da** yalnız sunucuya bırakılır — karar gerekli
2. Sonuç `probe` sözlüğü → **iki seçenek**:
   - (a) `tradehub_core/media/pipeline/api/policy.py` → `evaluate_slot(slot, probe)` uç noktası (tek RTT)
   - (b) `policy/*.json` politikalarının TS portu (T-033) → çevrimdışı çalışır
   - **Öneri: (a)** — tek doğruluk kaynağı; politika JSON'u sürüm sürüklemesine açık
3. `stores/media.js:626` `enqueueUploads` → `for … await` yerine `Promise.all` + Worker
   havuzu; ayrıca **`runUpload` eşzamanlılığı 2-3'e sınırlanır** (kalıp hazır:
   `lib/upload-ui/uploader.ts:54`)
4. `MediaUploadQueue.vue` → yeni `PreflightPanel` bölümü: ihlal + **çözüm yolu** metni
   (`Decision.to_dict()` zaten `message` + `params` taşıyor)

### A5 — Yenilemeye dayanıklı yükleme (T-091)

- `stores/media.js` — `upload_begin` dönüşündeki `upload_id`, `chunk_bytes`, gönderilen
  son `index` **IndexedDB**'ye yazılır (dosya tutamacı `File` nesnesi olarak; Chromium'da
  saklanabilir, Safari'de saklanamaz → orada kuyruk "devam etmek için dosyayı tekrar
  seçin" der, sessizce kaybetmez)
- `onMounted` → yarım oturumlar `upload_status` (`api/seller_media.py:407`) ile
  doğrulanır, ölüler temizlenir
- tus'a geçiş **önerilmez**: `media/chunked.py` çalışıyor, sözleşme kurulu. Kazanç
  base64'ten `ArrayBuffer`'a geçmekte (**+%33 ağ yükü** ortadan kalkar), protokolü
  değiştirmekte değil

### A6 — Detay çekmecesini sekmelendir (T-093)

`MediaDetailPanel.vue` (183 satırlık şablon) **korunur**, "Özet" sekmesi olur.

| Sekme | Yeni dosya | Veri kaynağı |
|---|---|---|
| Özet | mevcut `MediaDetailPanel.vue:1-125` | mevcut |
| **Türevler** | `MediaDetailRenditions.vue` | A2 `manifest_batch` → `variants[]`; `available:false` olan basamak **sebebiyle** listelenir |
| Kullanım | mevcut `:127-139` ayrıştırılır | mevcut `loadUsage` |
| **Kalite** | `MediaDetailQuality.vue` | `tradehub_core/media/pipeline/quality/ssim.py` + yeni `quality_report(key)` ucu. Sade dil şablonu **i18n anahtarı** olmalı: `media.detail.quality.summary = "{sw}×{sh} → {tw}×{th}; {sdpi}→{tdpi} dpi; {sbytes} → {tbytes}"` |
| **Geçmiş** | `MediaDetailHistory.vue` | `MediaAuditView`'ın `useMediaAudit` composable'ı **tek varlığa** daraltılır — yeniden yazılmaz |

Sekme başlığı için `role="tablist"`/`role="tab"`/`aria-selected` + ok tuşu gezinme
(T-095 ile birlikte yapılmalı, sonradan eklenirse yine unutulur).

### A7 — Klasörler (T-094)

En büyük yeni iş. `MediaExplorerView`'ın **sanal** klasörleri (`media/browse.py`:
`public_stores`, `private_groups`) satıcı klasörü **değil** — yeniden kullanılamaz.

1. DocType `Media Folder`: `store` (Link, zorunlu), `parent_media_folder` (Tree),
   `folder_name`. `tradehub_core/` altına yazılamaz → `tradehub_core/media/pipeline/doctype_specs/`
   içine **belirtim** yazılır, uygulama ayrı bir görevde
2. `File` üzerine klasör bağı: `File`'a alan eklenemez → `media_engine` tarafında
   eşleme tablosu (`Media Folder Item`) veya `File.folder` alanının satıcı kapsamlı
   yeniden kullanımı — **karar gerekli, ölçülmedi**
3. Panel: `MediaFilterRail.vue`'ye ağaç bölümü (bileşen `MediaFolderTree.vue`);
   sürükle-bırak `vuedraggable` (kurulu)
4. `MediaBulkBar.vue` → `move` + `reprocess` düğmeleri
5. Kısmi hata raporu: `api/seller_media.py:173` `_toplu()` bugün yalnız sayaç dönüyor →
   `{ok: [...], fail: [{url, code}]}` döndürecek şekilde genişletilir; `MediaBulkBar`
   sonucu `MediaBulkResultDialog.vue` ile satır satır gösterir

---

## 5. T-092 — sanal kaydırma: 10.000 varlıkta ne olur

### 5.1 Bugünkü zincir

```
MediaLibraryView  PAGE_SIZES = [12, 24, 48]          (:728)
stores/media.js   paged = filtered.slice(...)        (:287)  ← istemci
stores/media.js   loadReal → pageSize: 200           (:139)  ← SABİT
useSellerMedia    load({pageSize})                   (:88)
api/seller_media  get_my_media(page_size=50)         (:67)
media/inventory   page_size = min(MAX_PAGE_SIZE=200) (:248)  ← TAVAN
```

### 5.2 10.000 varlıkta gerçekleşecekler (öncelik sırasıyla)

**1 — Varlıkların %98'i erişilemez.** Sunucu en çok 200 satır döner. Kalan 9.800 dosya
kütüphane ekranından **görünmez, aranamaz, filtrelenemez**. Sanal kaydırma bu sorunu
çözmez: kaydıracak veri gelmiyor.

**2 — Ekran yanlış sayı gösterir.** `counts.all` (`stores/media.js:230`) 200'lük dilimden
sayar; başlık "200 dosya · X MB" yazar (`MediaLibraryView.vue:10`). Kullanıcı
kütüphanesinin 200 dosyadan ibaret olduğunu sanır. `serverTotal` (`:108`) doğru değeri
**zaten tutuyor**, hiçbir yerde okunmuyor.

**3 — Filtreler yalan söyler.** `filtered` (`:244`), `availableTags` (`:300`) ve format
listesi hep aynı 200 satırdan türer. "WEBP" filtresi, ilk 200'de WEBP yoksa **boş** döner —
kütüphanede 3.000 WEBP olsa bile.

**4 — Ancak bundan sonra DOM sorunu gelir.** Ölçülen: `MediaCard` şablonu **31 eleman**,
içindeki `MediaThumb` **7 eleman** → kart başına **~38 DOM elemanı**.

| Senaryo | Kart | DOM elemanı (hesaplanan) |
|---|---:|---:|
| Bugün, sayfa = 48 | 48 | ~1.824 |
| Sayfalama kalkar, 10k tek listede | 10.000 | **~380.000** |
| Sanal kaydırma, ~60 görünür + tampon | ~90 | ~3.420 |

380.000 eleman uygulanabilir değil. Sanal kaydırma **zorunlu** — ama **A1'den sonra**.

**5 — Ağ yükü, DOM'dan daha erken vurur.** `MediaThumb.vue:6` `:src="item.fileUrl"` →
**orijinal dosya**. Ölçülen ortalama dosya boyutu 1.559 MB / 4.958 = **~0,31 MB**.

| Görünüm | Kart | Hesaplanan indirme |
|---|---:|---:|
| Izgara sayfa = 48 (bugün) | 48 | **~15 MB** |
| Sanal kaydırma, 10k içinde 500 kart kaydırılırsa | 500 | **~157 MB** |

`loading="lazy"` görünmeyeni ertelemekten başka bir şey yapmıyor; **görünen** her kart
tam boy orijinali indiriyor. Bu, ürün detay sayfasındaki "13,14 MB = hedefin 15 katı"
sorununun **aynısının** panel ızgarasındaki tekrarıdır.

### 5.3 Sonuç

> Sanal kaydırma T-092'nin **dördüncü** önceliğidir. Sırasıyla:
> **(1)** sunucu tarafı filtre + imleç sayfalama (A1) →
> **(2)** `manifest_batch` ile küçük türev teslimi (A2) →
> **(3)** doğru toplam sayı →
> **(4)** sanal kaydırma (A3).
> Ters sırada yapılırsa 200 satır çok akıcı kayar.

**ÖLÇÜLMEDİ:** gerçek kare hızı, kaydırma sırasındaki ana iş parçacığı bloklaması, gerçek
LCP. Panelde 10.000 varlıklı bir mağaza bugün mevcut değil (canlıda en büyük mağaza 750
dosya — `stores/media.js:130` yorumu bunu söylüyor ve ölçüme dayandığını belirtiyor).

---

## 6. LQIP yer tutucu ve CLS

### 6.1 CLS bugün zaten 0 — ama LQIP yok

`MediaThumb.vue` düzen kayması **yaşamıyor**: oran `aspect-ratio` ile değil
`::before { padding-top: 100% }` ile kuruluyor (dosyada gerekçesi yazılı: grid item
içinde `aspect-ratio` satır yüksekliği üretmiyordu). Kutu görsel gelmeden **önce**
rezerve ediliyor → **CLS = 0** ızgara ve detay panelinde.

**Ama:**
- Yer tutucu = düz gri (`$l-bg-muted`) — LQIP değil
- `width`/`height` öznitelikleri **hiç yok** (5 ekran + 19 bileşende `srcset`, `sizes`,
  `:width`, `:height` toplam **0 eşleşme**)
- `MediaThumb` dışındaki 13 `<img>` (`MediaAuditView` ×6, `MediaOptimizeView` ×4,
  `MediaExplorerView` ×1, `MediaRecordDialog` ×1, `MediaUploadQueue` ×1) **oran kutusu
  içinde değil** → oralarda CLS **ÖLÇÜLMEDİ**, muhtemelen > 0

### 6.2 Hangi bileşene ne eklenmeli

**Tek dosya: `admin-panel/frontend/src/components/media/MediaThumb.vue`** (3.258 bayt,
tüm ızgara/liste/kart/detay önizlemesi buradan geçiyor — tek noktadan kazanılır).

Üretim tarafı — `media_engine`:

1. `tradehub_core/media/pipeline/image/lqip.py` (**yeni**) — mevcut motorun üstüne sarmalayıcı:
   - `tradehub_core/media/pipeline.py` `optimize()` ile 20×20'ye küçült
   - WebP q20 → base64 `data:` URI, **hedef ≤ 1.400 bayt** (satır içi gömülecek)
   - `probe()`'tan `intrinsic_width/height` — `th_media_width` bugün **%0 dolu**, bu
     yüzden LQIP üretimi çözünürlük yazımını da tetiklemeli (aynı geçişte)
2. `tradehub_core/media/pipeline/contracts/delivery.py:162` `RenderManifest.to_dict()` → `"lqip"` ve
   `"placeholder_color"` alanları eklenir (`to_dict()` sözleşmesi zaten "boş alanlar
   KORUNUR" diyor — `""` = "üretilmedi", `null` = "sorulmadı" ayrımı korunmalı)
3. Test: `tests/test_lqip.py` — 51 golden fixture üzerinde LQIP ≤ 1.400 bayt, CMYK ve
   alfa'da çökmeme (**38 CMYK + 597 alfa** dosya ölçülmüş, ikisi de fixture korpusunda)

Tüketim tarafı — `MediaThumb.vue`:

```
<div class="media-thumb" :style="{ '--ar': ar }">        ← oran manifest'ten, sabit 1:1 değil
  <img class="media-thumb__lqip" :src="item.manifest.lqip" alt="" aria-hidden="true" />
  <picture>
    <source v-for="s in item.manifest.sources" :srcset="s.srcset" :sizes="s.sizes" :type="s.type" />
    <img class="media-thumb__fill" :src="item.manifest.src"
         :width="item.manifest.width" :height="item.manifest.height"
         :alt="item.alt || item.fileName" loading="lazy" decoding="async"
         @load="lqipGoster = false" @error="broken = true" />
  </picture>
</div>
```

- LQIP `filter: blur(8px); transform: scale(1.06)` ile çizilir (scale, blur kenarındaki
  şeffaf halkayı kapatır)
- `@load` → LQIP `opacity: 0`, 150 ms geçiş. `base.scss:224` global
  `prefers-reduced-motion` guard'ı geçişi zaten kapatıyor — ek iş yok
- **`alt`**: bugün `:alt="item.fileName"` (`MediaThumb.vue:7`). Kütüphanede
  `missingAlt` filtresi **var** demek ki `item.alt` alanı var → `item.alt || item.fileName`
  olmalı. Dosya adını alt metin diye okutmak ekran okuyucuda gürültü
- Üçüncü kademe (ikon + uzantı rozeti, `:16-21`) **korunur** — video/PDF için doğru

**Not:** `@load` ile LQIP söndürmek, görsel önbellekten gelirse `@load` tetiklenmeyebilir
riskini taşır. `img.complete` kontrolü `onMounted`'da yapılmalı.

---

## 7. T-095 — Erişilebilirlik: ölçülmüş sayılar

### 7.1 i18n — iyi durumda

`i18n/locales/tr.js` ↔ `en.js` düzleştirilip karşılaştırıldı:

| Ad alanı | TR | EN | Eksik EN | Eksik TR |
|---|---:|---:|---:|---:|
| `media.*` | 234 | 234 | **0** | **0** |
| `mediaAudit.*` | 192 | 192 | 0 | 0 |
| `mediaOptimize.*` | 131 | 131 | 0 | 0 |
| `mediaBackup.*` | 67 | 67 | 0 | 0 |
| `mediaExplorer.*` | 32 | 32 | 0 | 0 |
| `mediaUsage.*` | 26 | 26 | 0 | 0 |
| `mediaAccess.*` | 18 | 18 | 0 | 0 |
| `mediaRecord.*` | 11 | 11 | 0 | 0 |
| **Medya toplam** | **711** | **711** | **0** | **0** |
| Panel geneli | 7.606 | 7.626 | 0 | **20** (`adminFeeds.*`, medya dışı) |

- Boş değerli medya anahtarı: **0**
- TR ile EN değeri birebir aynı olan: **5** — `mediaOptimize.stat.netDisk`,
  `mediaOptimize.confirm.trashPart`, `mediaAudit.severity.normal`, `media.kinds.video`,
  `media.filters.format`. Dördü meşru ortak kelime ("Video", "Format", "Normal"); ikisi
  gözden geçirilmeli
- **Eksik:** CI denetimi yok. `src/i18n/__tests__/` içinde yalnız `initializeI18n.test.js`
  var, eşitlik testi yok
- **Tek sabit metin bulgusu:** `components/common/ListPagination.vue:57` →
  `` `${n} / sayfa` `` — İngilizce arayüzde de "12 / sayfa" yazıyor.
  `t("common.perPage", { n })` olmalı

### 7.2 Erişilebilirlik öznitelikleri — dosya bazında sayım

| Dosya | `<button>` | `aria-label` | `aria-*` toplam | `role=` | `tabindex` | `aria-live` | `@keydown` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `MediaLibraryView.vue` | 24 | 14 | 18 | 4 | **0** | **0** | 0 |
| `MediaExplorerView.vue` | 7 | 1 | 1 | **0** | **0** | **0** | 0 |
| `MediaOptimizeView.vue` | 40 | 2 | 2 | **0** | **0** | **0** | 0 |
| `MediaBackupView.vue` | 11 | 1 | 4 | 1 | **0** | **0** | 0 |
| `MediaAuditView.vue` | 31 | 3 | 4 | 1 | **0** | **0** | 0 |
| `components/media/*` (19 dosya) | 47 | 27 | — | — | 1 | **0** | 0 |
| **TOPLAM** | **160** | **48** | — | — | **1** | **0** | **0** |

Tek `tabindex` geçişi (`MediaModal.vue:64`) bir CSS seçici dizgesinin içinde — şablonda
odaklanabilir yapılmış **hiçbir** eleman yok.

`@keydown` sayısı 0 olsa da klavye **çalışıyor**: `useMediaShortcuts.js` `window`
üzerinde dinliyor (`:103`).

### 7.3 Doğrulanmış bulgular

**İyi (bozulmasın):**
- **160 butonun 159'unda** erişilebilir ad var (`aria-label`, `title` ya da metin)
- `alt` özniteliği olmayan `<img>`: **0**
- Genel odak halkası **var**: `assets/scss/base.scss:200-202`
  (`button:focus-visible`, `[role="button"]`, `a`) — bileşen dosyalarında `:focus`
  aramanın 1 sonuç vermesi yanıltıcı, kural global
- `prefers-reduced-motion` global guard **var**: `assets/scss/base.scss:224`
- `MediaCard.vue`: `aria-selected`, `role="checkbox"` + `aria-checked`, her hızlı işlem
  butonunda `aria-label` — **panelin en iyi bileşeni**
- `MediaUploadQueue.vue:41-46`: `role="progressbar"` + `aria-valuenow/min/max` doğru

**Düzeltilecek — kesin (dosya:satır):**

| # | Bulgu | Konum | Etki |
|---|---|---|---|
| 1 | **`aria-live` hiç yok** (5 ekran, 19 bileşen) | `MediaUploadQueue.vue` | Yükleme ilerlemesi, hata ve "48 başarılı / 2 hatalı" ekran okuyucuya **hiç** duyurulmuyor. T-095'in açık maddesi |
| 2 | **`aria-selected` geçersiz yerde** | `MediaCard.vue:2-10` — `<article :aria-selected>` | `article` rolü `aria-selected` kabul etmez → axe `aria-allowed-attr` **ciddi** bulgu. Çözüm: ızgara `<ul>`'una `role="listbox"` + `<li>`'ye `role="option"`, ya da `aria-selected` kaldırılıp `aria-checked` (zaten `:44`'te var) tek kalır |
| 3 | **Roving tabindex yok** | `MediaLibraryView.vue:1218` `cursor` + `MediaCard.vue:6` `mcard--focused` | Ok tuşu imleci **görsel** olarak taşıyor, DOM odağını **taşımıyor**. Ekran okuyucu hiçbir şey duyurmuyor. Çözüm: `<li :tabindex="i === cursor ? 0 : -1">` + `cursor` değişince `.focus()`; `:1646` `scrollIntoView` yerine odak |
| 4 | **Izgara kabında rol yok** | `MediaLibraryView.vue:366` `<ul class="mgrid">`, `:390` `<ul class="mrows">` | `role="listbox"` + `aria-multiselectable="true"` + `aria-label` gerek |
| 5 | **Etiketsiz onay kutusu** ×5 | `MediaOptimizeView.vue:988, 1094, 1147, 1174, 1311` | `<label>` sarmalayıcısı da yok → axe `label` **ciddi**. `:1147` "tümünü seç" başlığında; `aria-label` şart |
| 6 | **Etiketsiz `<select>`** | `MediaAuditView.vue:676` | Sarmalayan `<label>` yalnız `AppIcon` içeriyor, metin yok → hesaplanan ad boş |
| 7 | **Adı olmayan buton** | `MediaOptimizeView.vue:863` | `aria-label` yok, `title` yok, metin yok |
| 8 | **Yalnız `title` ile adlandırılmış ikon butonu** ×6 | `MediaOptimizeView.vue:937, 1103, 1120`; `MediaAuditView.vue:869, 882, 1008` | axe geçer ama dokunmatikte `title` görünmez; `aria-label` eklenmeli |
| 9 | **Arama girdisinde yalnız `placeholder`** ×3 | `MediaExplorerView.vue:337`, `MediaOptimizeView.vue:734`, `MediaAuditView.vue:775` | `MediaLibraryView` her iki aramasında da `aria-label` **doğru yapılmış** (`:96`, `:211`) — sistem ekranları geride |
| 10 | **İki diyalogda odak tuzağı yok** | `MediaRecordDialog.vue:67`, `MediaUsageDialog.vue:84` | İkisi de `role="dialog" aria-modal="true"` ilan ediyor ama `activeElement`/Tab döngüsü/odak dönüşü **yok**. Klavye kullanıcısı diyalogun arkasına sekebiliyor. **`MediaModal.vue:58-104` bunun doğrusunu zaten yapıyor** (Tab döngüsü, ilk odak, odak dönüşü, `useScrollLock`) ve `MediaShortcutsModal`/`MediaPickerModal`/`MediaPreviewModal` onu kullanıyor → çözüm: bu iki diyalog `MediaModal` sarmalayıcısına taşınır |
| 11 | **`ConfirmDialog` diyalog rolü ilan etmiyor** | `components/common/ConfirmDialog.vue` | `role="dialog"`, `aria-modal`, odak tuzağı — hiçbiri yok. Silme onayı buradan geçiyor (`MediaLibraryView.vue`) |

**Araç eksikleri (T-095'in kendisi):**
- `axe-core` — kurulu değil
- `playwright` — kurulu değil
- `vitest` + `@vue/test-utils` — kurulu değil (`node --test`, DOM yok)
- `docs/reports/90-erisilebilirlik.md` — henüz yok (T-095'in çıktısı)

### 7.4 T-095 uygulama sırası

1. `npm i -D @axe-core/playwright playwright vitest @vue/test-utils jsdom` (admin-panel)
2. `tests/a11y/media.spec.js` — 5 ekranda axe taraması, `critical`/`serious` = 0 eşiği
3. `tests/a11y/keyboard.spec.js` — yalnız klavye: dosya seç → preflight → önizle → onayla
4. `tests/i18n/parity.test.js` — TR/EN anahtar eşitliği (**bugün geçer**, regresyonu tutar)
5. Yukarıdaki 1-11 numaralı bulgular düzeltilir (7-9 arası ~30 dakikalık iş; 10-11 `MediaModal` sarmalaması)
6. Kontrast ölçümü → `docs/reports/90-erisilebilirlik.md`

---

## 8. Depolar arası bağımlılık — plan yapılırken bilinmesi gereken

`tradehub_core/media/pipeline/api/__init__.py` (Faz 3 çıktısı) şunu **yazılı** olarak söylüyor:

> "Bu paketin ekleyeceği tek yeni şey, bugün var olmayan **slot kimliği**dir:
> `upload_policy.check()` imzasında slot parametresi yok, bu yüzden sunucu bir yüklemenin
> hangi slota ait olduğunu bilmiyor ve slot bazlı hiçbir kural uygulanamıyor. …
> **FAZ 3'TE UYGULANMADI.** Uygulanmasının ön koşulu, slot anahtarının istemciden
> (storefront + admin panel) gönderilmesidir; iki depo da SALT OKUNUR."
> — `IMPLEMENTED = False`, bkz. `docs/sad/review-v1.0.md` R-03

Faz 9 bu düğümün **tam üstünde** duruyor:

- `tradehub_core/media/pipeline/policy/` altında **9 slot politikası** hazır, hiçbiri uygulanmıyor
- Ölçülen slot uyumsuzluğu: `product.image` **%48,6**, `document.attachment` **%91,8**
- Panelde slot kavramı **hiç yok**: `MediaLibraryView` yüklerken slot göndermiyor,
  `lib/upload-ui/facades/SlotDropzone.ts`'teki `slotId` **KYC belge slotu**, medya
  politikası slotu değil

**Faz 9'un teslim etmesi gereken sözleşme (kod değil, karar):**

| Uç | Yeni alan | Kim gönderir |
|---|---|---|
| `seller_media.upload_media` | `slot: str` | `stores/media.js` `enqueueUploads` |
| `seller_media.upload_begin` | `slot: str` | `useSellerMedia.uploadChunked` |
| `media_engine.api.policy.evaluate_slot` | `{slot, probe}` → `Decision` | preflight Worker (A4) |

Medya kütüphanesinden yapılan **serbest** yüklemede slot yok. İki seçenek — **karar gerekli**:
(a) `library.generic` diye bir varsayılan politika tanımlanır, ya da
(b) slot yalnız *bağlamlı* yüklemede (ürün formu, kategori bandı) zorunlu olur,
kütüphane yüklemesi bugünkü genel kurallara tabi kalır.
**Öneri (a)** — (b) kütüphaneyi politikayı atlatma yoluna çevirir.

---

## 9. ÖLÇÜLMEDİ

Dürüstlük için: bu belgede **olmayan** sayılar.

- Gerçek kare hızı / kaydırma akıcılığı — tarayıcıda çalıştırılmadı
- 50 dosyalık yüklemede ana iş parçacığı bloklama süresi (T-091 eşiği <50 ms)
- Gerçek CLS / LCP değerleri — `MediaThumb` dışındaki 13 `<img>` için oran kutusu yok,
  CLS > 0 olması **muhtemel** ama doğrulanmadı
- axe-core tarama sonucu — araç kurulu değil. §7.3'teki bulgular kaynak okumasından
- Renk kontrast oranları
- 10.000 varlıklı gerçek mağaza davranışı — canlıda en büyük mağaza 750 dosya
- `MediaFolder` için `File` DocType'ına klasör bağının maliyeti (§4 A7-2)
- `MediaModal` odak tuzağının gerçek tarayıcı davranışı (kaynak doğru, çalıştırılmadı)

---

## 10. Önerilen iş sırası

| Sıra | İş | Görev | Depo | Ön koşul |
|---:|---|---|---|---|
| 1 | Sunucu tarafı filtre + imleç sayfalama + facet | T-092 | `tradehub_core/media/pipeline/api/library.py` | — |
| 2 | `serverTotal`'ı başlığa bağla (**yanlış sayı düzeltmesi**) | T-092 | panel | 1 |
| 3 | `manifest_batch` + LQIP üretimi | T-092/093 | `tradehub_core/media/pipeline/api/manifest.py`, `image/lqip.py` | — |
| 4 | `MediaThumb` → `<picture>` + LQIP | T-092 | panel | 3 |
| 5 | Erişilebilirlik bulguları 1-9 (§7.3) | T-095 | panel | — (paralel) |
| 6 | axe + playwright + i18n parity CI | T-095 | panel | — (paralel) |
| 7 | Preflight Worker + slot politikası ucu | T-091 | ikisi | §8 kararı |
| 8 | Yükleme eşzamanlılık sınırı + IndexedDB devam | T-091 | panel | 7 |
| 9 | Sanal kaydırma | T-092 | panel | 1, 4 |
| 10 | Detay çekmecesi sekmeleri (Türevler/Kalite/Geçmiş) | T-093 | ikisi | 3 |
| 11 | Klasör ağacı + toplu taşıma + kısmi hata raporu | T-094 | ikisi | — |

**5 ve 6 hemen başlayabilir** — hiçbir arka uç işine bağlı değil ve T-095 zaten
T-090…T-094'ün tamamına bağımlı olduğu için en sona bırakılırsa hiç yapılmaz.

---

## Ek — dosya konumları

**Panel (salt oku):** `/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/`
`views/seller/MediaLibraryView.vue` · `views/system/Media{Explorer,Optimize,Backup,Audit}View.vue` ·
`components/media/` (19) · `stores/media.js` · `composables/useSellerMedia.js` ·
`composables/useMediaShortcuts.js` · `utils/uploadPolicy.js` · `lib/media/compress*.js` ·
`lib/upload-ui/` (TS) · `i18n/locales/{tr,en}.js`

**Arka uç (oku):** `/Users/ahmet/Desktop/istoc/tradehub_core/tradehub_core/`
`api/seller_media.py` · `media/inventory.py` · `media/browse.py` · `media/chunked.py`

**Yeni kodun yeri:** `/Users/ahmet/Desktop/istoc/tradehub_core/tradehub_core/media/pipeline/`
`api/library.py` (yeni) · `api/manifest.py` (yeni) · `api/policy.py` (yeni) ·
`image/lqip.py` (yeni) · mevcut: `policy/engine.py`, `contracts/delivery.py`, `quality/ssim.py`
