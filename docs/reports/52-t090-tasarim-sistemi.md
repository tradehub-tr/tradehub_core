# 52 — T-090 · T-095 · T-120 · T-121 — Tasarım sistemi, erişilebilirlik, teslim bileşenleri

**Tarih:** 2026-08-19 · **Depo:** `admin-panel`, dal `ahmet` · **Kapsam:** kod yazıldı
**Paralel çalışma:** 6 panel ajanı aynı çalışma ağacında; bu rapor yalnız BU ajanın dosyalarını anlatır.

> **Okuma kuralı.** Bu belgede "geçti" yazan her satırın altında onu üreten komut vardır.
> Ölçülmeyen her şey **ÖLÇÜLMEDİ** diye yazılıdır ve tahminle doldurulmamıştır.
> Tarayıcıda hiçbir doğrulama yapılmadı.

---

## 0. Doğrulama — koşturulan komutlar ve çıktıları

| Komut | Çıkış | Sonuç |
|---|---:|---|
| `npm test` | **0** | **640 test, 640 geçti, 0 kaldı** |
| `npm run lint` | **0** | 0 hata, 2 uyarı — ikisi de `views/permission/PlansTab.vue:1024,1035` (`no-unused-vars`), **bu görevden ÖNCE de vardı**, dosya bu görevin dosyası değil |
| `npm run build` | **0** | `✓ built in 13.08s` |
| `npx prettier --check` (bu görevin 6 dosyası) | **0** | "All matched files use Prettier code style" |

Görev başındaki taban çizgi 571 testti. Ölçüm anında 640 — aradaki 69'un **31'i bu
görevin** (aşağıda dosya bazında), kalanı aynı anda çalışan diğer ajanların.

Görev sırasında koordinatörün bildirdiği kırmızı (`mediaSimulator.test.js` — çözülmemiş
çeviri anahtarı, C7 ajanının alanı) **son ölçümde yeşildi**; bu ajan o dosyaya ve
`i18n/locales/*`'a dokunmadı.

---

## 1. T-095 — Erişilebilirlik: elle yazılmış iddia yerine MAKİNE ölçümü

### 1.1 Neden bu iş yapıldı

Faz 9 denetimi (`docs/ui/faz9-media-library.md` §7.3) T-095 için şunu yazıyordu:

> "axe-core — kurulu değil · playwright — kurulu değil · vitest — kurulu değil"

Bugüne kadarki her erişilebilirlik iddiası **elle yazılmış assertion**'dı: şablon
metninde `aria-label` geçiyor mu diye dizgide arama. Bu yöntem, **aradığın kuralı**
doğrular; **bilmediğin kuralı** hiç sormaz.

### 1.2 Ne kuruldu

```
package.json  devDependencies:
  + axe-core  ^4.13.0   (kurulu sürüm 4.13.0)
  + jsdom     ^30.0.1   (kurulu sürüm 30.0.1)
package-lock.json: +561 satır — `npm ci` bozulmadı (`npm run build` EXIT 0 ile doğrulandı)
```

Kurulumdan **sonra** `npm test` ve `npm run build` yeniden koşturuldu (ikisi de EXIT 0):
diğer 5 ajanın paylaştığı `node_modules` bozulmadı.

**`axe-core` ve `jsdom` üretim paketine SIZMADI** — `dist/assets/*.js` içinde
`scanHtml` / `UNMEASURABLE_RULES` / `axeHarness` dizgeleri **hiçbir chunk'ta yok**
(ölçüldü: `grep -c` üzerinden, tüm chunk'lar 0).

### 1.3 Nasıl koşuyor

`src/components/media/a11y/axeHarness.js` (170 satır):
bileşen → `@vue/server-renderer` → HTML → `jsdom` belgesi → `axe-core` kaynağı script
olarak enjekte → `window.axe.run()`.

`axe-core`'u Node'dan `import` edip belge geçirmek **çalışmıyor**: paket kendini
yüklendiği `window`'a bağlıyor. Kaynağı enjekte etmek tek yol.

Etiket kümesi: `wcag2a` + `wcag2aa` + `wcag21a` + `wcag21aa`.

### 1.4 ÖLÇÜLEN SAYILAR

**Taranan yüzey:** 13 bileşen keşif taramasında, **8 durum** kalıcı teste bağlandı.

| Bileşen | Engelleyici (critical/serious) | Not |
|---|---:|---|
| `MediaImage` (türevli, adlandırılmış) | **0** | 4 kural geçti |
| `MediaImage` (bezeme, `alt=""`) | **0** | 3 kural geçti |
| `MediaVideo` (kontrollü + altyazılı) | **0** | 7 kural geçti |
| `MediaVideo` (sessiz döngü) | **0** | 7 kural geçti |
| `MediaThumb` (görsel) | **0** | 4 kural geçti |
| `MediaThumb` (belge ikonu) | **0** | — |
| `MediaBulkBar` | 0 | 14 kural geçti |
| `MediaFilterChips` | 0 | 1 kural geçti |
| `MediaCrumbs` | 0 | 11 kural geçti |
| `MediaFolderGrid` | 0 | 15 kural geçti |
| `MediaRenditionList` | 0 | 7 kural geçti |
| `MediaShortcutsModal` | 0 | 1 kural (Teleport → gövde boş) |
| **`MediaUploadQueue`** | **1** | `aria-progressbar-name` **serious** |
| **`MediaFilterRail`** | **1** | `aria-progressbar-name` **serious** |

> **BULUNAN: 2 · DÜZELTİLEN: 0 · KALAN: 2**

**Neden 0 düzeltildi:** her iki dosya da bu görevin dosya listesinde **değil**
(`MediaUploadQueue.vue`, `MediaFilterRail.vue`). 6 ajan aynı ağaçta çalışırken
sahibi olmadığım dosyayı düzenlemek çakışma üretir. Ölçüldü, adlandırıldı,
düzeltilmedi.

**Bulguların tam hâli ve düzeltmesi:**

| # | Dosya | Eleman | Kural | Düzeltme |
|---|---|---|---|---|
| 1 | `src/components/media/MediaUploadQueue.vue` | `<div class="upload-row__bar" role="progressbar" aria-valuenow=…>` | `aria-progressbar-name` (serious) | Aynı satırdaki dosya adını `aria-labelledby` ile bağla **ya da** `:aria-label` ver. **Yeni i18n anahtarı gerekmez** — dosya adı zaten görünür metin |
| 2 | `src/components/media/MediaFilterRail.vue` | `<div class="mrail__storage-bar" role="progressbar" aria-valuenow=…>` | `aria-progressbar-name` (serious) | Çubuğun üstündeki kota metnini `aria-labelledby` ile bağla |

**Bu, makine ölçümünün elle yazılmış denetimden farkının kanıtıdır.**
`docs/ui/faz9-media-library.md` §7.3 aynı `MediaUploadQueue.vue:41-46` bloğunu
*"`role="progressbar"` + `aria-valuenow/min/max` **doğru**"* diye **iyi örnek**
listesine yazmıştı. `axe-core` aynı bloğu **serious ihlal** buluyor: bir
`progressbar`'ın erişilebilir **adı** olmak zorunda; `aria-valuenow` adı yerine
geçmiyor. Elle yazılmış assertion bunu asla sormazdı.

### 1.5 ÖLÇÜLMEYEN — bu liste raporun parçası

| Ne | Neden ölçülmedi |
|---|---|
| **Renk kontrastı** (`color-contrast`) | Gerçek renk hesabı **boyama** ister; `jsdom` boyamıyor. Kural açıkça kapatıldı ve gerekçesi kodda yazılı. (Kontrast ayrıca ölçülüyor — `__tests__/mediaAccessibility.test.js` tokenlerden oranı hesaplıyor — ama **bu tarama onu ölçmez**) |
| **Dokunma hedefi ölçüsü** (`target-size`) | Düzen motoru ister; `jsdom`'da her `getBoundingClientRect()` 0×0 |
| **Kaydırılabilir bölge** (`scrollable-region-focusable`) | Taşma hesabı ister |
| **Teleport kullanan diyaloglar** | `MediaModal` ve onu saran `MediaPreviewModal`/`MediaPickerModal`, ayrıca `ConfirmDialog`: SSR'da `document` yok, teleport hedefi çözülemiyor, bileşen **hiç render edilmiyor**. Faz 9 §7.3'ün **10 ve 11 numaralı** diyalog bulguları (odak tuzağı, `role="dialog"` eksikliği) bu taramanın kapsamı **DIŞINDA** — kapandıkları ölçülmedi |
| **5 tam ekran** (`MediaLibraryView` vb.) | Görünüm bileşenleri SSR'da store/router/`window` bağımlılıklarıyla ayağa kalkmıyor; ölçüm bileşen düzeyinde kaldı |
| **Klavye ile gerçek odak sırası, ekran okuyucu çıktısı, `:focus-visible` görünürlüğü, hidrasyon SONRASI DOM** | Canlı tarayıcı gerekir. **Bu görevde tarayıcı doğrulaması yapılmadı** |
| `video-caption` | `axe` bu kuralı **`incomplete`** döndürüyor (ihlal değil): videonun sesi olup olmadığını statik olarak bilemiyor. `MediaVideo` altyazı izini destekliyor (`captionsSrc`), ama sesli içerikte altyazı sağlamak **çağıranın** sorumluluğu |

### 1.6 Tarama aracının kendisi ölçüldü

Bir tarama aracının en tehlikeli arızası **sessizce hiçbir şey bulmamaktır**.
`mediaAxe.test.js` içinde kasten bozuk bir parça taranıyor
(`<button></button><img src><div role="progressbar">`) ve tam olarak
`["aria-progressbar-name", "button-name", "image-alt"]` bulunduğu doğrulanıyor.
Bu test kırılırsa "0 ihlal" sonuçlarının hiçbiri güvenilir değildir.

### 1.7 Yan bulgu — SSR zamanlayıcı sızıntısı

`src/components/media/MediaUploadQueue.vue:125` `setInterval`'i **`setup()` içinde**
kuruyor, temizliği `onUnmounted`'a bağlı — o da SSR'da **hiç çağrılmıyor**. Sonuç: her
sunucu render'ı bir zamanlayıcı sızdırıyor ve **Node süreci hiç kapanmıyor**. Bu
tarama ilk kurulduğunda test koşucusu takıldı; sebebi buydu.

Tarayıcıda gerçek bir arıza değil (unmount'ta temizleniyor). Doğrusu yine de
`onMounted` içinde kurmaktır — SSR'da sayaç zaten anlamsız. Bileşen bu görevin dosyası
değil; test tarafında sızıntı yakalanıp temizleniyor ki tarama koşabilsin.

---

## 2. T-120 — `MediaImage` / `MediaVideo` teslim bileşenleri

### 2.1 Başlangıç durumu

`docs/reports/36-dogrulama-faz12-14.md` T-120 için: **KISMİ** —
*"`MediaVideo` karşılığı YOK"*. Panelde yalnız `MediaImage.vue` vardı ve o da
`<picture>`/`srcset`/`sizes` **taşımıyordu**: tek `<img src>`, yalnız CLS koruması.

### 2.2 `MediaImage.vue` — `<picture>` sözleşmesi eklendi

Eklenen prop'lar: `renditions` · `sizes` · `priority`. Mevcut CLS davranışı
(`width`/`height` öznitelikleri, `aspect-ratio`, LQIP kademesi) **değişmedi** —
o davranışı ölçen `mediaCls.test.js` (başka ajanın dosyası) hâlâ geçiyor.

| Sözleşme | Durum | Nasıl ölçüldü |
|---|:--:|---|
| AVIF → WebP → JPEG **sırası** | ✅ | `type="image/avif"` indeksi `type="image/webp"`'den küçük |
| JPEG ayrı `<source>` **değil**, `<img srcset>`'te | ✅ | `doesNotMatch(/type="image\/jpeg"/)` + `<img … srcset="…jpg 640w"` |
| `srcset` artan ve **tekilleştirilmiş** | ✅ | Aynı genişlikte ikinci aday atılıyor (tarayıcı için ayırt edilemez) |
| Her `srcset` ile birlikte `sizes` | ✅ | `srcset="` sayısı = `sizes="` sayısı |
| `sizes` yoksa **hiç** `srcset` yok | ✅ | Yanlış `sizes` ile servis, hiç `srcset` olmamasından kötü |
| Türev yoksa **düzgün yedek** | ✅ | Bugünkü gerçek hâl (`Media Rendition` tablosu boş): tek `<img>`, ölçüler yerinde |
| Tanınmayan biçim (`HEIC`) sessizce atılıyor | ✅ | Uydurma MIME üretilmiyor; `jpg`=`jpeg` normalize |
| `priority` → `fetchpriority="high"` + `loading="eager"` | ✅ | Varsayılan `lazy`, `fetchpriority` **yok** |
| `width`/`height` **daima** | ✅ | `priority` durumunda da basılıyor — CLS koruması önceliğe bağlanamaz |

`<picture>` `display: contents` ile stilleniyor: aksi hâlde araya giren satır-içi
kutu `width: 100%`'i shrink-to-fit'e çözer ve küçük resimler küçülürdü.

### 2.3 `MediaVideo.vue` — YENİ (287 satır)

| Sözleşme maddesi | Durum | Nasıl |
|---|:--:|---|
| **poster** | ✅ | `poster` özniteliği + **kutu yine `width`/`height`'tan ayrılıyor** — poster tek başına yer AYIRMAZ, poster inene kadar `<video>` varsayılan 300×150 kutusundadır |
| **muted-autoplay-loop** | ✅ | `background` modu üç koşulu **birden** kuruyor: `muted` + `loop` + `playsinline`. `muted` hem öznitelik hem **DOM özelliği** olarak kuruluyor (öznitelik tek başına bazı tarayıcılarda otomatik oynatmayı kurtarmıyor) |
| **playsinline** | ✅ | Her modda basılıyor |
| **HLS lazy** | ✅ | `preload="none"` + `<source>` etiketleri görünürlüğe kadar **DOM'a hiç basılmıyor** (`IntersectionObserver`, `rootMargin: 200px`). Sunucu çıktısında `<source>` ve `m3u8` **yok** — ölçüldü |
| **reduced-motion** | ✅ | `matchMedia("(prefers-reduced-motion: reduce)")` otomatik oynatmayı **iptal ediyor** ve kontrolleri **geri getiriyor**; ayar oturum içinde değişirse dinleyici video'yu `pause()` ediyor |
| Erişilebilir ad | ✅ | `label` prop'u; **verilmezse `aria-label` basılmıyor** (boş `aria-label`, adı olmayan elemandan kötüdür) |
| Altyazı | ✅ | `captionsSrc`/`captionsLang`/`captionsLabel` → `<track kind="captions" default>` |

**Kasıtlı karar — `hls.js` EKLENMEDİ.** Yeni bağımlılık kararı bu görevin işi değil
(admin-panel `CLAUDE.md` §2.11). `hlsSrc` yalnız tarayıcı HLS'i **yerli** olarak
çözebiliyorsa kullanılıyor (`canPlayType("application/vnd.apple.mpegurl")` →
Safari/iOS); çözemeyen tarayıcıda progresif `src` kalıyor. Yani HLS bir **iyileştirme
kademesi**, tek yol değil — Chrome'da `hlsSrc` verilse bile ekran boş kalmıyor.

`reduced-motion` kararının CSS'te **değil** JS'te verildiği ayrıca test ediliyor:
`autoplay` bir özniteliktir, `@media` onu kapatamaz — "destekliyoruz" iddiasının
ölçülebilir olması için kaynakta `matchMedia` + `change` dinleyicisi + `pause()`
aranıyor.

### 2.4 ÖLÇÜLMEYEN (T-120)

- **CLS SKORU.** "CLS = 0" **denmiyor**. Ölçülen: kayma kaynağı olan ölçüsüz
  `<img>`/`<video>` kalmadığı. Gerçek skor için Chrome + LayoutShift observer gerekir.
- Tarayıcının hangi adayı **gerçekte** indirdiği, oynatmanın başlayıp başlamadığı,
  HLS segment zamanlaması — hepsi canlı tarayıcı ister, **yapılmadı**.
- **SSR notu:** sunucu çıktısında `background` modu `autoplay` taşıyor, çünkü
  `prefers-reduced-motion` sunucuda bilinemez; karar hidrasyonda düzeltiliyor. Panel
  üretimde SSR kullanmadığı için bu yalnız test artefaktıdır.

---

## 3. T-121 — `sizes` gerçek düzenden türetiliyor

### 3.1 Kural: türetme motoru YENİDEN YAZILMADI

`sizes` dizgesini üreten algoritma `admin-panel/frontend/src/lib/media/simulator/select.js`
içindeki **`sizesAttribute(region, ctx)`**'tur ve o dosya
`tradehub_core/media/pipeline/simulator/srcset.py` ile **parite testine** bağlıdır.
Bu görev o dizine **yazmadı**, yalnız **çağırdı**.

`sizesAttribute`'un imzası bunun için zaten parametrik: `ctx` = `{containers, flatten}`,
yani kapsayıcı kümesi dışarıdan gelir.

**Tek istisna ve gerekçesi:** motorun kendi `flattenContainer`'ı `layout.js`'teki
**modül düzeyi** simülatör kapsayıcılarına bağlı, panelin kapsayıcılarını kabul
etmiyor; `lib/media/simulator/` bu görevde **salt okunur** olduğu için oraya bir
parametre eklenemedi. Bu yüzden aynı çözümleme panelin kapsayıcı haritası üzerinde
`makeFlatten()` ile yürütülüyor — ve **eşdeğerliği ölçülüyor**:

> `panelSizes.test.js` → *"kapsayıcı çözümlemesi simülatörünkiyle BİREBİR aynı"*
> — simülatörün **kendi 5 kapsayıcısı** × **240…2560px arası 8px adımlı süpürme**
> = **1.455 kombinasyon**, `deepEqual`, **0 sapma**.

İkinci bir çözümleme yazmanın tek kabul edilebilir şartı buydu.

### 3.2 Sayılar nereden geldi — hepsi kaynak dosyada okunabilir

| Değer | Kaynak (dosya:satır) |
|---|---|
| Ray 60px | `components/layout/IconRail.vue:3` → `w-[60px]` |
| Yan panel 220px | `components/layout/SidePanel.vue:16` → `width: '220px'` |
| Ray+panel yalnız ≥768px | `layouts/AppLayout.vue:6-7` `v-if="isLg"` + `useBreakpoint.js` `lg: (min-width: 768px)` |
| `main` iç boşluk 16→24px | `layouts/AppLayout.vue:14` `p-4 xl:p-6`; `assets/tailwind.css` `--breakpoint-xl: 1024px` |
| `.mpage` yan boşluk 16px | `MediaLibraryView.vue:1874` `padding: $s-5 $s-4 $s-10`; `media.scss` `$s-4: 1rem` |
| Detay sütunu 19rem / 21rem + 16px gap | `MediaLibraryView.vue:1948,1954` |
| Izgara boşluğu 12px | `MediaLibraryView.vue:2326` `gap: $s-3` (`0.75rem`) |
| Sütun sayısı kuralı | `MediaLibraryView.vue:1181` `detailDocked ? density : min(density, 4)` |
| `detailDocked` = ≥1280px | `MediaLibraryView.vue:1161` `is2xl` |
| Satır/tablo/kanban küçük resmi 40 / 36 / 36px | `MediaLibraryView.vue:2409, 2560, 2721` |
| Detay sheet'i `min(26rem, 100%)` | `MediaDetailPanel.vue:458` |

### 3.3 Üretilen `sizes` — gerçek çıktı

```
libraryGrid  (yoğunluk 3, detay kapalı):
  (min-width: 1024px) calc((100vw - 360px - 24px) / 3),
  (min-width: 768px)  calc((100vw - 344px - 24px) / 3),
                      calc((100vw - 64px  - 24px) / 3)

libraryGrid  (yoğunluk 6, detay AÇIK):
  (min-width: 1536px) calc((100vw - 712px - 60px) / 6),
  (min-width: 1280px) calc((100vw - 680px - 60px) / 6),
  (min-width: 1024px) calc((100vw - 360px - 36px) / 4),
  (min-width: 768px)  calc((100vw - 344px - 36px) / 4),
                      calc((100vw - 64px  - 36px) / 4)

rowThumb  → 40px     cellThumb / kanbanThumb → 36px
detailPreview → min(100vw, 416px)
```

Düşümler doğrulanabilir: `<768` → 32 (`main`) + 32 (`.mpage`) = **64**;
`768–1023` → +60+220 = **344**; `≥1024` → `main` 48'e çıkar = **360**;
detay açıkken `≥1280` +320 = **680**, `≥1536` +352 = **712**.
Yoğunluk 6'da `<1280` bandında **4 sütun tavanı** görünüyor — kaynaktaki
`min(density, 4)` kuralı dizgede birebir karşılığını buluyor.

### 3.4 Neden sabit ölçülü küçük resimlere de `sizes` yazılıyor

40px'lik bir kutuya `sizes` yazmak gereksiz görünür. Yazılmazsa tarayıcı `w`
tanımlayıcılı bir `srcset`'te **`100vw` varsayar** ve masaüstünde 40px'lik satır
önizlemesi için **en büyük basamağı** indirir. Kayıp sessizdir; `sizes="40px"` onu keser.

### 3.5 Elle yazılmış `sizes` yasağı test edilir

`panelSizes.test.js` → *"modülde ELLE YAZILMIŞ `sizes` dizgesi yok"*: `sizes.js`
kaynağından yorumlar çıkarılıp kalan kodda sabit `(min-width:` bandı ya da sabit `vw`
ifadesi **aranıyor ve bulunmaması** doğrulanıyor. T-121'in bütün meselesi budur — bir
`sizes` dizgesi kaynakta sabit dururken kırılım noktası değişirse **sessizce** yalan
söyler.

### 3.6 Arayüze bağlandı — ama kapatılabilir

`MediaThumb.vue` üç yeni prop aldı: `region` · `density` · `detailOpen`.
`region` boşken `sizes` **basılmıyor** ve davranış bu görevden **öncekiyle birebir
aynı** — mevcut çağıranların hiçbiri değişmedi (`MediaLibraryView.vue`,
`MediaDetailPanel.vue`, `MediaCard.vue` bu görevde **düzenlenmedi**).

> **Orkestratöre:** kazancın gerçekleşmesi için `MediaThumb` çağrılarına bölge
> geçilmeli — `MediaLibraryView.vue:405` → `region="rowThumb"`, `:489` →
> `region="cellThumb"`, `:558` → `region="kanbanThumb"`; `MediaCard.vue:17` →
> `region="libraryGrid" :density="…" :detail-open="…"`.
> Bu dosyalar bu görevin listesinde değil, **dokunulmadı**.

### 3.7 Paket boyutu ölçüldü — yeni maliyet YOK

`sizes.js` → `lib/media/simulator/select.js` → 27KB'lık vendor verisi zinciri
endişe vericiydi; ölçüldü:

- Vendor verisi `dist/assets/select-rAUwZAsY.js` adlı **ayrı chunk**'ta (32KB ham,
  **10,9KB gzip**).
- O chunk'ı **`index-*.js` giriş paketi zaten import ediyordu** (ölçüldü: `grep -l`
  → `index`, `MediaSimulatorView`, `CropStudioModal`, `ListingFormView`,
  `SellerCategoriesView`, `StorefrontLayoutEditor`, `useSellerMedia`).
- Yani `MediaThumb`'ın bu bağı **yeni indirme maliyeti getirmiyor**.

### 3.8 ÖLÇÜLMEYEN (T-121)

Kabul kriterinin **"seçilen rendition ile gerçek kutu farkı ≤ %25"** maddesi
`currentSrc` genişliği ile `getBoundingClientRect().width × DPR` karşılaştırması
ister. **Canlı tarayıcı gerekir; bu görevde tarayıcı doğrulaması YAPILMADI.**
Burada ölçülen, üretilen `sizes` dizgesinin **CSS kaynağıyla tutarlılığıdır** —
tarayıcının o dizgeyi nasıl çözdüğü değil. `docs/reports/120-sizes-dogrulama.md`
hâlâ **YOK** ve bu ajan onu üretemez.

---

## 4. T-090 — İskelet, tasarım sistemi, API istemcisi

Faz 9 §2 T-090'ı **~%55** ölçmüştü. Bu görevde **kapanan** ve **kapanmayan** maddeler:

| Kabul kriteri | Önce | Şimdi | Not |
|---|:--:|:--:|---|
| Vue 3 + Pinia + Vite | ✅ | ✅ | Değişmedi |
| Tasarım sistemi bileşenleri | ✅ | ✅ | **+3**: `MediaImage` (teslim sözleşmesiyle), `MediaVideo` (yeni), `MediaThumb` (bölge farkındalığıyla) |
| Hata→mesaj eşlemesi merkezi | ✅ | ✅ | `utils/api.js` `buildError()` deseni korundu, **dokunulmadı** |
| i18n TR/EN, her metin anahtar üzerinden | ✅ | ✅ | `MediaVideo` **hiçbir** metin üretmiyor: erişilebilir ad ve altyazı etiketi **prop** olarak çağırandan geliyor → `i18n/locales/*` dosyalarına dokunulmadı (yasak alan) |
| Lint + tip denetimi CI'da | 🟡 | 🟡 | Lint EXIT 0; tip denetimi hâlâ yok |
| **TypeScript strict** | ❌ | ❌ | **YAPILMADI — bilinçli.** `tsconfig.json` eklemek ve `.vue` dosyalarını `lang="ts"`'e çevirmek, 6 ajanın **aynı anda** düzenlediği bir ağaçta her dosyayı çakışma alanına sokar. Ölçülebilir kazancı yok, kırma riski yüksek |
| **Vitest** | ❌ | ❌ | **YAPILMADI — bilinçli.** Koşucu değişimi 640 testin tamamını etkiler. `node --test` ile **DOM testi yapılabildiği** bu görevde kanıtlandı: `jsdom` + `@vue/server-renderer` ile axe taraması koşuyor. Vitest'in gerekçesi zayıfladı |
| **OpenAPI tipli API istemcisi** | ❌ | ❌ | Şema üretimi backend işi; `tradehub_core` bu görevde yasak alan |

**`utils/api.js` bu görevde DEĞİŞTİRİLMEDİ.** Dosya listesinde olması izin
demekti, gereklilik değil; mevcut `request()` + CSRF + `buildError()` deseninde
ölçülebilir bir eksik bulunmadı.

---

## 5. Dosya envanteri

**Yeni:**

| Dosya | Satır | İş |
|---|---:|---|
| `src/components/media/MediaVideo.vue` | 287 | T-120 video teslim bileşeni |
| `src/components/media/delivery/sizes.js` | 255 | T-121 `sizes` türetimi |
| `src/components/media/a11y/axeHarness.js` | 170 | T-095 axe + jsdom koşucusu |
| `src/components/media/a11y/__tests__/mediaAxe.test.js` | 231 | **4 test** |
| `src/components/media/delivery/__tests__/panelSizes.test.js` | 151 | **9 test** |
| `src/components/media/delivery/__tests__/mediaDelivery.test.js` | 272 | **18 test** |

**Değiştirilen:**

| Dosya | Değişiklik |
|---|---|
| `src/components/media/MediaImage.vue` | `<picture>` + `renditions`/`sizes`/`priority`; mevcut CLS davranışı korundu |
| `src/components/media/MediaThumb.vue` | `region`/`density`/`detailOpen` prop'ları; `region` boşken davranış aynı |
| `package.json` | `axe-core@^4.13.0` + `jsdom@^30.0.1` (devDependencies) |
| `package-lock.json` | +561 satır |

**Bu görevin katkısı: 31 test** (571 → ölçüm anında 640; kalan 69−31=38 diğer ajanların).

---

## 6. Kapanmayan işler — sıradaki ajana

1. **2 `aria-progressbar-name` ihlali** (§1.4): `MediaUploadQueue.vue` ve
   `MediaFilterRail.vue`. Düzeltme `aria-labelledby` ile, **yeni i18n anahtarı
   gerektirmiyor**.
2. **`MediaThumb` bölge bağlantısı** (§3.6): 4 çağrı noktasına `region` geçilmeli,
   yoksa T-121'in kazancı arayüze ulaşmıyor.
3. **`MediaUploadQueue.vue:125` SSR zamanlayıcı sızıntısı** (§1.7): `setInterval`
   `onMounted` içine alınmalı.
4. **Teleport diyalogların taranması** (§1.5): SSR yerine `jsdom` üzerine gerçek
   `mount` gerekir; Faz 9 §7.3'ün 10-11 numaralı bulguları hâlâ **ölçülmemiş**.
5. **i18n TR/EN eşitlik testi** — Faz 9 §7.4 maddesi. Bu görevde **yazılmadı**:
   `i18n/locales/*` yasak alandı ve dosyalar eşzamanlı düzenleniyordu; bugün
   kırmızıya düşme riski gerçekti.
6. **Tarayıcı ölçümleri:** CLS skoru (T-120), `sizes` ≤%25 sapma (T-121),
   renk kontrastı / dokunma hedefi (T-095). Hepsi **ÖLÇÜLMEDİ**.
