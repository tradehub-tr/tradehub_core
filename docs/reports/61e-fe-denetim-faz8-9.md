# FE Denetimi — Faz 8 (T-080…T-085) ve Faz 9 (T-090…T-095)

**Tarih:** 2026-08-20 · **Tip:** salt okunur denetim, hiçbir dosya değiştirilmedi.
**Kapsam:** her görevin **frontend payının** kod tabanında yapılmış olup olmadığı.

## Yöntem notu — belge iki farklı tarihte iki farklı gerçeklik gösteriyor

`/Users/ahmet/Desktop/istoc/tradehub_core/docs/ui/faz9-media-library.md` (yerel kopya,
2026-08-18 tarihli) okundu ve **başlangıç hipotezi** olarak kullanıldı, ama **kanıt
sayılmadı** (kural #5). Resmi görev tanımları
`https://karacaismail.github.io/imageoptimization/docs/52-faz8-api.html` ve
`.../60-faz9-media-library.html`'den WebFetch ile çekildi — **başarılı**, aşağıdaki
kabul kriterleri oradan.

`admin-panel/frontend`'de bugün (`git status`) **23 değiştirilmiş + 45 yeni dosya**,
3.355 satır eklenmiş, commit edilmemiş durumda (`git diff --stat`, 2026-08-20). Bu,
18 Ağustos'taki yerel raporun ölçtüğü andan **sonra** yapılmış iş — rapor bu yüzden
büyük ölçüde **güncelliğini yitirmiş** (örn. rapor "axe-core kurulu değil" diyor;
bugün `node_modules/axe-core` kurulu VE `node --test` ile 4/4 test GEÇİYOR — kendim
çalıştırıp doğruladım). Bu denetim, yerel raporu değil, **bugünkü kodu** temel aldı;
her satırda taze `grep`/`git`/test çalıştırma kanıtı var.

---

## Tablo

| Görev | Rol | FE payı | Durum | Kanıt (dosya:satır) | Eksik olan |
|---|---|---|---|---|---|
| T-080 | Backend | OpenAPI'den üretilen TS tipleri + tipli istemci FE'de kullanılmalı | **YOK** | `admin-panel/frontend`'de `tsconfig*.json` yok (`ls` boş); `find . -iname "*openapi*"` ve `*.d.ts` (node_modules hariç) **0 sonuç**. `src/utils/api.js` elle yazılmış string uç adlarıyla çalışıyor. | Şemadan üretilmiş TS tipi ve bunu tüketen istemci hiç yok. |
| T-081 | Backend | Client raporu (telemetri) + resumable/idempotency ile uyumlu istemci | **KISMİ** | `src/lib/media/upload/session.js:1-51` — dosya başlığında **açıkça**: "T-081 metni 'tus' diyor. Sunucuda tus YOK" (satır 6-7); `chunked.py` sözleşmesine (`upload_begin/chunk/finish/abort/status`) karşı `localStorage` tabanlı devam edebilirlik kurulu (satır 22-50). Satır 40-45: **"Idempotency-Key YOK"** — sunucuda alan yok, istemci yalnız `finish`i tek sefere kilitliyor. | Idempotency-Key (sunucu eksik, istemci de dolayısıyla yok); gerçek tus protokolü (bilinçli, gerekçeli). |
| T-082 | Backend | Crop intent + preview uçlarını tüketen istemci | **KISMİ** | `src/composables/useSimulatorApproval.js:11,23,57,75-86` — `Media Crop Intent.previewed_placements` alanını dolduran saf fonksiyon (T-114 onay kapısı). `src/components/media/crop/` (6 dosya: CropStudioModal/Canvas/Handles/PreviewStrip/Toolbar/PolicyNotice) `MediaLibraryView.vue:678,734-735`'e async component olarak bağlı. **AMA** `MediaLibraryView.vue:677` yorumu: **"Kaydetme ucu henüz yok — modal bunu kendi içinde söylüyor"**; `useCropStudio.js` (664 satır) içinde `grep "api\.\|callMethod\|fetch("` **0 sonuç** — hiçbir sunucu çağrısı yok. | Kırpma niyetini sunucuya yazan gerçek istek yok; UI tamamen istemci tarafında asılı duruyor. |
| T-083 | Backend | `manifest_batch` ile toplu teslim tüketimi (N+1 yok) | **KISMİ** | `grep -rn "manifest_batch" src` → **0 sonuç**. `src/composables/useMediaRenditions.js:9-19` — açık yorum: "Özel bir uç YOK... boru hattının uçları (`api/media_manifest.py`) ilan+slot bazlı manifest veriyor ama 'şu dosyanın türevleri' sorusunu yanıtlamıyor" → veri **iki adımlı genel REST** (`File → Media Asset → Media Rendition`, satır 12-19) ile okunuyor. `src/components/media/delivery/sizes.js` yalnız CSS `sizes` türetiyor (`simulator/select.js` motoruyla), manifest ucu değil. | `manifest_batch` gerçek tüketimi yok; N+1 riski hâlâ orada (iki adımlı REST). |
| T-084 | Backend | Hata kodu kataloğu i18n senkronu | **FE-DIŞI** | Kod→mesaj eşlemesi (`uploadPolicy.js`, `media.errors.*`) zaten T-090/T-095 kapsamında ayrıca sayıldı; T-084'ün asıl gövdesi (admin uçları + sözleşme testleri) FE'de karşılığı olmayan saf backend işi. Ayrı bir FE bulgusu yok. | — (görev esasen backend; benzersiz bir FE parçası tespit edilmedi) |
| T-085 | Backend | Tipli TS SDK (`ui/src/api/client.ts`) FE'de zorunlu kullanım | **YOK** | Resmi belgenin adını verdiği `ui/src/api/client.ts` admin-panel'de yok; `find` ile hiçbir openapi/SDK dosyası bulunamadı (T-080 ile aynı taramanın sonucu). FE hâlâ `src/utils/api.js` elle yazılmış istemciyi kullanıyor. | Tipli istemci, `Idempotency-Key` üretimi (client.ts'nin işi), Bruno/Postman koleksiyonunun FE'de tüketimi. |
| T-090 | Frontend | Frontend iskelet, tasarım sistemi, API istemcisi | **KISMİ** | Vue3+Pinia+Vite: `package.json`. **TS strict YOK**: `tsconfig*.json` yok (taze doğrulandı). **Vitest YOK**: `package.json` `"test": "node --test ..."` (taze doğrulandı, `vitest` bağımlılığı 0). **Axe-core KURULU** (`package.json` devDependencies `"axe-core": "^4.13.0"`, `node_modules/axe-core` var) — 08-18 raporunun tersi, bugün ölçüldü (bkz. T-095). Tasarım sistemi bileşenleri var ama resmi adlarla (Button/Modal/Drawer/Table/Toast/Progress/Tooltip) **birebir değil** — `src/components/common/` `AppSelect`, `ConfirmDialog`, `ChildTable`, `Skeleton`, `BaseSwitch` vb. farklı adlandırma. OpenAPI tipli istemci YOK (T-080/085 ile aynı bulgu). i18n TR/EN medya ad alanı **tam** (917/916 anahtar, tek fark `media.quality.col.attribute` — node ile flatten edilip ölçüldü); **RU/AR medya ad alanının çoğu YOK** (bkz. T-095). | TS strict, Vitest, OpenAPI tipli istemci, resmi isimlendirmeyle DS bileşenleri, RU/AR çevirisi. |
| T-091 | Frontend | Uppy + tus yükleyici, preflight paneli | **KISMİ** | Uppy/tus **kurulmadı** — `MediaUploader.vue:86-93` gerekçeli ("sunucuda tus yok, Uppy kendi kuyruk modelini getirir"). Kendi yükleyici: **Web Worker VAR** — `src/lib/media/upload/preflight.worker.js` (26 satır) `probe.js`'i worker içinde çalıştırıyor; `preflightClient.js:34` `new Worker(new URL("./preflight.worker.js", ...))`. `probe.js:78,104` DPI okuyor (`readDpi`); yorum satırında MP/alfa/video (`mediabunny`) de kapsanıyor. **Eşzamanlılık sınırı VAR**: `useMediaUpload.js:63` `concurrency = 2` (eski "50 paralel istek" sorunu kapanmış). **Sayfa yenilenince devam**: `session.js` `localStorage` tabanlı, çalışıyor (T-081 ile aynı kanıt). Idempotency-Key YOK (gerekçeli, T-081). | Gerçek Uppy/tus (bilinçli atlandı); Idempotency-Key. **"50 dosyada <50ms" iddiası ÖLÇÜLMEDİ** — tarayıcıda koşturulmadı. |
| T-092 | Frontend | Asset grid, arama, filtre, sanal kaydırma | **KISMİ** | Sanal kaydırma altyapısı **yeni kuruldu**: `src/composables/useVirtualGrid.js` (229 satır) + test. **AMA** `grep "useVirtualGrid" src/views/seller/MediaLibraryView.vue` → **0 sonuç** — yalnız `MediaFolderGrid.vue` (klasör tarayıcısı) kullanıyor; T-092'nin asıl hedefi olan **ana varlık ızgarasında sanal kaydırma hâlâ bağlı değil** (kural #2: bileşen var ama mount edilmemiş). **Filtre durumu URL'de artık VAR**: `MediaLibraryView.vue:720,1032-1033,1099` `useRoute/useRouter` + `router.replace({query})`; yeni `src/utils/mediaFilterUrl.js`. `manifest_batch` yok (T-083 ile aynı). Realtime/socket.io: `grep` **0 sonuç**, paket bağımlılığı yok. | Ana ızgarada sanal kaydırma bağlantısı, `manifest_batch` tüketimi, Frappe realtime güncelleme. |
| T-093 | Frontend | Asset detay çekmecesi: versiyon, rendition, kullanım, kalite | **KISMİ** | Sekmeli düzen **artık var**: `MediaDetailPanel.vue:25` `role="tablist"`, `:32` `role="tab"`, `:52,194,213,224,251` `role="tabpanel"`. Kalite paneli bağlı: `:227,327` `MediaQualityPanel`. SSIM alanı okunuyor (`useMediaRenditions.js:31` `RENDITION_FIELDS`) ama `:17-19` dürüstçe: "Tablo şu an BOŞ: bayraklar kapalı, hiçbir türev üretilmedi". Sürüm sekmesi **açıkça** "kurulu değil" diyor: `MediaDetailPanel.vue:236-246` — `Media Version` DocType'ı yok, sahte veri gösterilmiyor. Kırpma eylemi düğmesi var (`:289-294`) ama kaydetme ucu yok (T-082). **Tek varlık için "yeniden işle" hiçbir yerde**: `grep -rl reprocess src/components/media src/stores src/composables src/views/seller` → **0 sonuç**. | Reprocess eylemi, sürüm/geçmiş (backend'de kurulu değil), crop kaydetme ucu, gerçek türev verisi (backend bayrakları kapalı). |
| T-094 | Frontend | Klasör/etiket organizasyonu, toplu işlemler | **KISMİ** | Gerçek satıcı klasör ağacı (DocType) **yok**: `grep -rln "Media Folder"` → 0. `SellerMediaExplorerView.vue` (507 satır, yeni) sanal kök klasörler kullanıyor (`public/private/chat`, satır 84-86) — gezinme var, gerçek hiyerarşi/DocType yok. Sürükle-bırak taşıma/rename: `grep "draggable\|rename"` explorer dosyalarında **0 sonuç**. **Toplu kısmi hata raporu artık var** (en somut yeni kazanım): `MediaBulkBar.vue:57,64,71,84,87,95` `role="alert"` + `media.bulk.partial` ("48 başarılı, 2 başarısız" kalıbı). Toplu buton listesi (`:3-99`) yalnız tag/download/archive/delete — **reprocess/move yok**. | Gerçek klasör DocType'ı, sürükle-bırak taşıma/rename, toplu reprocess/taşı. |
| T-095 | QA | Erişilebilirlik + i18n doğrulaması | **KISMİ** | **axe-core artık gerçekten çalışıyor** (08-18 raporunun tam tersi — bugün çalıştırıp doğruladım): `node --test src/components/media/a11y/__tests__/mediaAxe.test.js` → **4/4 test GEÇTİ** (`tests 4, pass 4, fail 0`). Harness: `src/components/media/a11y/axeHarness.js` (SSR + gerçek axe-core, `window.axe.run()`). **Kapsam sınırlı**: yalnız 3 "teslim bileşeni" (MediaImage, MediaVideo, MediaThumb, `mediaAxe.test.js:97-113`) taze taranıyor + 2 komşu bileşen sabit "taban çizgi ≤2 bulgu" ile izleniyor (`:139-165`); **5 ana ekran** (MediaLibraryView, MediaOptimizeView, MediaAuditView, MediaExplorerView, MediaBackupView) axe kapsamı **DIŞINDA**; Teleport'lu diyaloglar SSR'da render edilemediği için **taranamıyor** (test dosyası kendi yorumunda itiraf ediyor, satır 27-32). **i18n — dört dil ayrı ayrı sayıldı (node ile flatten):** TR **917**, EN **916** (1 eksik: `media.quality.col.attribute`), **RU 151, AR 151**. RU/AR'da **yalnız** `mediaStorage` (54/54) ve `mediaSimulator` (97/97) ad alanları tam; **ana `media.*` (285), `mediaOptimize` (131), `mediaBackup` (67), `mediaExplorer` (36), `mediaAccess` (18), `mediaAudit` (192), `mediaRecord` (11), `mediaUsage` (26) ad alanlarının TAMAMI RU/AR'da 0** — yani T-090…T-094'ün ürettiği asıl ekranların RU/AR çevirisi **yok**. Roving tabindex, dialog odak tuzağı (MediaRecordDialog/MediaUsageDialog), `ConfirmDialog` `role="dialog"` — üçü de bugün tekrar grep edildi, **hâlâ 0 sonuç** (düzeltilmemiş). aria-live yeni yüzeylerde (crop/simulator, 9 dosya) var, eski 5 ana ekranda yok. | axe kapsamı 5 ekranın tamamına genişletilmeli, **RU/AR medya çevirisi (766/917 anahtar eksik)**, roving tabindex, 2 diyalogda odak tuzağı, `ConfirmDialog` dialog rolü, kontrast ölçümü. |

---

## Sayım

| Durum | Adet | Görevler |
|---|---:|---|
| TAM | 0 | — |
| KISMİ | 9 | T-081, T-082, T-083, T-090, T-091, T-092, T-093, T-094, T-095 |
| YOK | 2 | T-080, T-085 |
| FE-DIŞI | 1 | T-084 |
| ÖLÇÜLEMEDİ | 0 | — |
| **Toplam** | **12** | — |

---

## En önemli 3 bulgu

1. **RU/AR çevirisi, medya ekranlarının %83'ünde (766/917 anahtar) yok.** Yerel 08-18
   raporu yalnız TR/EN'i ölçmüş ve "i18n neredeyse tam" demişti — RU/AR'ı hiç
   saymamıştı. Bugün dört dili ayrı ayrı flatten edip saydım: RU ve AR yalnız
   `mediaStorage` (54) ve `mediaSimulator` (97) ad alanlarında tam; T-090…T-094'ün
   asıl ürettiği ekranların (`media.*`, `mediaOptimize`, `mediaAudit`, `mediaExplorer`,
   `mediaUsage`, `mediaAccess`, `mediaRecord`, `mediaBackup` — toplam 766 anahtar) RU/AR
   karşılığı **sıfır**. T-095'in "TR/EN tam" kabul kriteri dört dil değil iki dil için
   doğru; görev seti dört dil istiyor (kural #4).

2. **Kırpma stüdyosu (T-082/T-093) ve manifest_batch (T-083) UI'ı var, sunucu bağlantısı yok.**
   İki ayrı yerde kod kendi kendini itiraf ediyor: `MediaLibraryView.vue:677`
   "Kaydetme ucu henüz yok"; `useMediaRenditions.js:9-19` "manifest_batch değil,
   genel REST ile iki adımda okunuyor". Ekranlar hazır görünüyor ama T-082/T-083'ün
   asıl vaadi (kırpma niyetini kalıcı kaydetmek, tek istekte manifest almak) **hiçbiri
   FE'den tetiklenmiyor**. Bu, "ekran var ≠ uç var" kuralının (kural #3) tam örneği.

3. **08-18 tarihli yerel rapor bugünkü koda göre büyük ölçüde geçersiz.** Aradan geçen
   ~36 saatte 45 yeni dosya + 3.355 satır eklendi (crop stüdyosu, simülatör, axe-core
   harness'i, Web Worker preflight, URL'de filtre durumu, kısmi hata raporu, sekmeli
   detay paneli). Raporun "axe kurulu değil" bulgusu artık **yanlış** — bugün
   çalıştırıp 4/4 test geçtiğini doğruladım. Bir raporu kanıt saymamak (kural #5)
   burada gerçekten pahalıya mal olacaktı: aradaki fark tesadüfi değil, aktif
   geliştirme sürüyor.

---

## Ölçemediklerim

- **T-091 "50 dosyada <50ms ana thread blok" iddiası** — tarayıcıda koşturulmadı,
  yalnız kodda `concurrency=2` + Worker varlığı doğrulandı.
- **axe-core taramasının 5 ana ekranın tamamını kapsayıp kapsamadığı gerçek tarayıcıda** —
  yalnız `node --test` (SSR + jsdom benzeri) ile 3 bileşen üzerinde koştu; Teleport'lu
  diyaloglar (MediaModal, MediaPreviewModal, MediaPickerModal) hiç taranamadı.
- **Renk kontrastı (AA)** — `axeHarness.js` içinde `color-contrast` kuralı bilinçli
  olarak kapalı (`UNMEASURABLE_RULES`), tarayıcıda hiç ölçülmedi.
- **10.000 varlıklı gerçek mağaza davranışı** — yerel doküman "canlıda en büyük mağaza
  750 dosya" diyor, bunu kendim doğrulamadım (backend sorgusu gerektirir, salt-FE
  denetim kapsamı dışı).
- **Klavye ile uçtan uca akış (dosya seç → preflight → önizle → onayla)** — kodda
  kısayol composable'ı (`useMediaShortcuts.js`) var ama gerçek tarayıcıda koşturulmadı.
- **T-084'ün backend sözleşme testlerinin FE ile gerçekten senkron olup olmadığı** —
  yalnız kod tarafı (`uploadPolicy.js` kodları) okundu, backend hata kataloğuyla
  bire bir eşleşme kontrolü yapılmadı (iki depoyu birbirine karşı diff'lemek gerekir).
- **Performans/süre iddiası yapılmadı** (kural #7 gereği).
