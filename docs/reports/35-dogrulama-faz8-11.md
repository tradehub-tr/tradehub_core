# 35 · Doğrulama — Faz 8, 9, 10, 11

**Tarih:** 2026-08-19 · **Yöntem:** salt okuma + ölçüm. Hiçbir kaynak dosya değiştirilmedi.
**Kaynak:** `https://karacaismail.github.io/imageoptimization/docs/` — `52-faz8-api.html`,
`60-faz9-media-library.html`, `61-faz10-crop-studio.html`, `62-faz11-simulator.html`.

Bu rapor mevcut raporlara (özellikle `31-gorev-numara-hizalama.md` ve `32-faz8-api-kapanis.md`)
**dayanmaz**; onları yalnız çapraz kontrol için kullanır. Koşturulmayan hiçbir şeye "geçti" denmedi.
Ölçülemeyen her kriter **ölçülmedi** olarak işaretlendi.

> **Süre/performans iddiası yoktur.** Ölçüm sırasında makinede paralel üç ajan daha koşuyordu;
> hiçbir zamanlama sayısı bu rapora alınmadı.

---

## 0 · Koşturulan ölçümler (ham çıktı)

| # | Komut | Sonuç |
|---|---|---|
| 1 | `bench run-tests --module tradehub_core.tests.test_api_contracts` | **Ran 126 tests — OK** (0 hata) |
| 2 | `bench run-tests --module tradehub_core.tests.test_http_api_contracts` | **Ran 25 tests — OK (skipped=7)** |
| 3 | Aynısı + `ISTOC_HTTP_BASE=http://127.0.0.1:8000 ISTOC_HTTP_HOST=istoc.localhost` | **Ran 25 tests — OK, 0 atlandı** |
| 4 | `bench run-tests --module tradehub_core.tests.test_crop_geometry` | **Ran 37 tests — FAILED (failures=1)** |
| 5 | `bench run-tests --module tradehub_core.tests.test_simulator_srcset` | **Ran 34 tests — OK** |
| 6 | `cd admin-panel/frontend && npm test` | **393 tests · pass 393 · fail 0** |
| 7 | `node --experimental-strip-types tradehub_core/tests/tools/run_ts_vectors.ts` (host, node v24.18.1) | `{"toplam":592,"kosulan":584,"hata_vakasi":8,"uyusmazlik":0,"en_buyuk_sapma_px":0}` |

### 0.1 · İki tuzak — kendi ölçüm hatam, kayda geçiyor

**(a) Paralel ajan çarpışması.** `test_crop_geometry` ve `test_http_api_contracts` ilk
koşumlarında `helpdesk/test_utils.py::make_new_sla` içinde `TimestampMismatchError` ile
**çöktü** — testler hiç koşmadı. Bu bir ürün kusuru değil, aynı sitede eşzamanlı test
koşan başka ajanların `before_tests` yarışı. Her iki modül de temiz koşum alınana kadar
tekrarlandı; yukarıdaki tablo temiz koşumları gösterir.

**(b) Yanlış taban adres.** Canlı HTTP testlerini önce `ISTOC_HTTP_BASE=http://localhost:8000`
ile koştum → **6 failure + 1 error**, hepsi `404 != 403`. Bu **benim kurulum hatamdı**:
Frappe siteyi `Host` başlığından çözer, `localhost:8000` hiçbir siteye düşmüyor
(`/api/method/ping` bile 404). `istoc.localhost:8000` ise Python `urllib` içinden DNS ile
çözülemedi (`socket.gaierror`). Testin kendi docstring'indeki reçete
(`ISTOC_HTTP_BASE` + `ISTOC_HTTP_HOST`) uygulanınca **25/25 geçti**. İlk koşumdaki 6
failure **gerçek bulgu değildir** ve öyle raporlanmamalıdır.

### 0.2 · `test_crop_geometry`'nin tek hatası

```
FAIL: test_ts_ikizi_ayni_sayiyi_veriyor
AssertionError: [] is not true : koşucu özet üretmedi:
STDERR:/home/frappe/.nvm/versions/node/v20.19.2/bin/node: bad option: --experimental-strip-types
```

Konteyner içindeki node **v20.19.2**; `--experimental-strip-types` Node 22.6+ ile geldi.
Yani **T-100'ün asıl sözü — TS ve Python aynı sayıyı veriyor mu — reponun kendi
koşumunda ölçülemiyor ve test kırmızı.** Test bu durumda sessizce atlamıyor, bilerek
patlıyor; bu doğru davranış.

**Ben bu boşluğu kapattım:** aynı koşucuyu host'ta node v24.18.1 ile kendim koşturdum
(satır 7). **592 vektörün 584'ü + 8 hata vakası, uyuşmazlık = 0, en büyük sapma = 0 px.**
Yani parite iddiası **maddeten doğru**, fakat **CI kapısı bugün kırmızı**.

Python tarafının kendi ölçümleri (aynı koşumun stdout'u):

```
[çapraz] crop.py ↔ crop_geometry.py en büyük sapma = 1.818989e-12 px
[çapraz-kutu] 800 örnek · 1 px yuvarlama farkı olan = 0
[oran] 3652 örnek · en büyük bağıl oran sapması = 2.070e-16
[vektör] 584 vektör · en büyük sapma = 0.0 px (yok)
```

> Not: brief'teki "592 vektör" sayısı dosyadaki **toplam**dır; koşulan 584, kalan 8 tanesi
> hata vakasıdır. "584 vektörde 0 px" demek daha doğru.

### 0.3 · Faz 8 sayısal iddialarının doğrulanması

`docs/api/openapi-http.yaml` gerçek bir YAML ayrıştırıcıyla okundu:

| İddia | Ölçüm | Sonuç |
|---|---|---|
| 87 uç | `paths: 87`, `operations: 87`, `x-endpoint-count: 87` | ✅ doğru |
| `pipeline/api/` altında hiç `@frappe.whitelist()` yok | `grep -rE "^\s*@frappe\.whitelist" tradehub_core/media/` → **0** (8 grep isabetinin hepsi "YOK" diyen docstring) | ✅ doğru |
| Misafire açık uç = 3 | `x-guest-endpoints: 3` **ve** `security: []` taşıyan operasyon = 3, ikisi birebir aynı küme | ✅ doğru |
| `openapi.yaml` değişmedi | `git status --porcelain docs/api/` → yalnız `?? openapi-http.yaml` | ✅ doğru |

Misafir uçları: `media_access.download`, `media_manifest.get_manifest`,
`media_manifest.get_manifest_batch`.

### 0.4 · Canlı DB'de DocType denetimi (Faz 10'un kilidi)

`frappe.db.exists("DocType", …)` ile **canlı** `istoc.localhost` üzerinde:

```
Media Crop Intent       -> None      ← KURULU DEĞİL
Media Crop Override     -> None
Media Upload Session    -> None
Media Placement Preview -> None
Media Asset / Rendition / Storage Settings / Engine Settings / Processing Job / Profile -> kurulu
```

Kurulu `Media%` DocType sayısı: **6**.
`tradehub_core/media/pipeline/doctype_specs/` altındaki **spec** sayısı: **16**
(`media_crop_intent.json` dahil).
Gerçek Frappe DocType dizini (`tradehub_core/tradehub_core/doctype/`) altındaki medya
DocType'ı: **6**.

**Sonuç:** `media_crop_intent.json` yalnızca bir *spec* dosyasıdır; Frappe DocType'ı değildir
ve kurulu değildir. Panel'in `useCropStudio.js:329`'daki `const saveAvailable = false;`
sabiti bir eksiklik değil, **doğru bir dürüstlük beyanıdır** — kaydı alacak uç ve tablo
gerçekten yoktur. (`CropStudioModal.vue:215` de bunu yorumda söylüyor.)

---

## 1 · Faz 8 — API katmanı

| ID | Başlık | Kaynağın kabul kriteri (özet) | Durum | Kanıt |
|---|---|---|---|---|
| **T-080** | OpenAPI sözleşmesi (contract-first) | Tüm uçlar/şemalar/hata kodları; **spectral** lint geçiyor; her uçta örnek istek/yanıt; şemadan **TS tipleri üretilip frontend kullanıyor** | **KISMİ** | `openapi.yaml` (77 KB) + yeni `openapi-http.yaml` (87 uç) var. **Spectral yapılandırması yok** (`.spectral*` bulunamadı, repoda `spectral` geçmiyor). **Üretilmiş TS tipi yok**; panel `package.json`'da `openapi-typescript`/`openapi-generator` yok |
| **T-081** | Upload session + resumable (tus) | `create_session` politika+kota döndürür; **tus** ile kaldığı yerden devam; `finalize` sunucu doğrulaması; aynı **`Idempotency-Key`** ikinci `finalize`'da aynı sonuç; yarım oturumlar zamanlanmış işle temizlenir | **YOK** | Panel'de `uppy`/`tus` **bağımlılığı yok**; `lib/upload-ui/` altında resumable/chunk mantığı yok. Medya kodunda `Idempotency-Key` geçmiyor. `Media Upload Session` DocType'ı **kurulu değil**. `pipeline/api/upload.py` `@frappe.whitelist()` taşımadığı için HTTP'den çağrılamaz. (Ayrı, tus olmayan bir yükleme yolu var: `MediaUploadQueue.vue` + `lib/upload-ui/`) |
| **T-082** | Crop intent + önizleme uçları | `save_intent` koordinat doğrular ve yalnız etkilenen rendition'ları kuyruğa alır; `suggest_focal` güven skoru; `preview` kalıcı yazmadan; **`previewed_placements`** kaydediliyor | **KISMİ** | Odak önerisi tarafı var (`lib/media/crop/focusSuggest.js`). **`save_intent` uçtan uca yok**: `Media Crop Intent` DocType'ı kurulu değil (§0.4), panel `saveAvailable=false`. **`previewed_placements` repoda hiç geçmiyor** |
| **T-083** | Manifest ve teslim uçları | profil/oran/odak/LQIP + format→genişlik→URL matrisi; üretilmemiş genişlik yok; `manifest_batch` tek istekte N varlık; **ETag/304**; yayımlanmamış varlık 404/403 | **TAM** *(ETag hariç)* | `get_manifest` + `get_manifest_batch` misafir uçları olarak belgede ve **canlı ölçümde** çalışıyor (25/25 canlı sözleşme testi). Sızdırmama kuralı canlı testlerde doğrulandı. **ETag/304 davranışı ayrıca ölçülmedi** |
| **T-084** | Yönetim uçları + contract testleri | Admin uçları superadmin'e kapalı, **negatif** yetki testleri; **schemathesis/dredd** ile şema doğrulama; **fuzzing** ile beklenmedik 5xx yok; hata kodları i18n | **KISMİ** | `test_api_contracts` **126/126**, `test_http_api_contracts` doğru yapılandırmayla **25/25** (misafir reddi testleri dahil, canlı ölçüldü). **`schemathesis`/`dredd` repoda yok** → şema-güdümlü fuzzing **yapılmıyor** |
| **T-085** | Faz 8 kapanış: dondurma + SDK | OpenAPI v1 donduruldu, breaking-change süreci belgeli; **TS istemci SDK** üretilmiş ve frontend kullanıyor; **Postman/Bruno** koleksiyonu | **KISMİ** | Üretim betiği (`scripts/gen_http_openapi.py`), "ELLE DÜZENLEMEYİN" başlığı ve sapma testi var — dondurma tarafı gerçek. **TS SDK yok. Postman/Bruno koleksiyonu yok** (`*.bru`, `*postman*` bulunamadı) |

**Ek bulgu (Faz 8):** `test_http_api_contracts`'ın **7 testi varsayılan koşumda atlanıyor**
(`@unittest.skipUnless(CANLI_TABAN, …)`). Yani `bench run-tests` ile koşan CI, gerçek HTTP
yüzeyini **ölçmez**; 25 testin yalnız 18'i çalışır. Testler `ISTOC_HTTP_BASE` verildiğinde
geçiyor (ben ölçtüm) ama bu env değişkenini veren bir CI yapılandırması bulunamadı.

---

## 2 · Faz 9 — Medya kütüphanesi arayüzü

`npm test` → **393/393 geçiyor** (fail 0). Brief'teki sayı doğrulandı.
Aşağıdaki "KISMİ"ler test başarısızlığından değil, **kaynağın kabul kriterinin
ölçülmemiş ya da karşılanmamış maddelerinden** gelir.

| ID | Başlık | Kaynağın kabul kriteri (özet) | Durum | Kanıt |
|---|---|---|---|---|
| **T-090** | İskelet, tasarım sistemi, API istemcisi | Vue 3 + **TypeScript (strict)** + Vite + Pinia + **Vitest**; DS bileşenleri; **OpenAPI tipli** API istemcisi; i18n (TR/EN) | **KISMİ** | Vue 3 + Vite + **Pinia 2.2** + `vue-i18n 11` ✅. DS bileşenleri `components/common/` altında geniş (AppSelect, BaseSwitch, ConfirmDialog, KanbanBoard, datatable…) ✅. i18n **4 dil** (tr/en/ar/ru) ✅ — kriteri aşıyor. **TypeScript strict YOK**: `tsconfig*.json` yok, `src` altında 10 `.ts` karşılık **569** `.js`/`.vue`. **Vitest YOK** — `"test": "node --test"`. **OpenAPI tipli istemci yok** |
| **T-091** | Uppy + tus yükleyici ve preflight paneli | Sürükle-bırak/klasör/yapıştır; **Web Worker**'da dosya başına preflight; ihlalde yükleme başlamaz; cihaz bütçesine göre istemci küçültme; kesintiden sonra **devam**; 50 dosyada akıcı UI | **YOK** | `uppy`/`tus` bağımlılığı **yok**; `lib/upload-ui/` içinde resumable/chunk yok. Web Worker preflight bulunamadı. Yükleme kuyruğu bileşeni (`MediaUploadQueue.vue`) var ama kriterin çekirdeği (tus + preflight worker) karşılanmıyor |
| **T-092** | Grid, arama, filtre, sanal kaydırma | 10.000 varlıkta akıcı sanal kaydırma; **LQIP + CLS = 0**; çok alanlı arama; **filtre durumu URL'de**; canlı işlem durumu; **`manifest_batch` tek istek (N+1 yok)** | **KISMİ** | Sanal kaydırma **var ve testli**: `useVirtualGrid.js` + `virtualGrid.test.js`, `MediaFolderGrid.vue` (`virtualThreshold: 60`). LQIP **var ve testli**: `MediaImage.vue` + `mediaCls.test.js` (data-URI, düz renk ve **stil enjeksiyonu reddi** dahil). **`manifest_batch` panelde hiç kullanılmıyor** → N+1 kriteri karşılanmıyor. 10.000 varlıkta akıcılık **ölçülmedi** |
| **T-093** | Detay çekmecesi: versiyon/rendition/kullanım/kalite | Kaynak↔normalize yan yana; insan dilinde kalite raporu; **SSIM'li** rendition listesi; kullanım listesi; yeniden işle/crop/indir/silme talebi; denetim geçmişi | **KISMİ** | Bileşenler var: `MediaDetailPanel.vue`, `MediaRenditionList.vue`, `MediaUsageDialog.vue`, `MediaRecordDialog.vue`, `mediaActions.js`. **SSIM'li kalite raporu ve kaynak↔normalize karşılaştırması ölçülmedi** — bu kriterlerin karşılandığına dair koşulmuş kanıt yok |
| **T-094** | Klasör/etiket organizasyonu + toplu işlemler | Klasör ağacı, sürükle-bırak taşıma, yeniden adlandırma; etiketleme; toplu işlem + kısmi hata raporu; **toplu silme grace period içinde geri alınabilir** | **KISMİ** | `MediaFolderGrid.vue`, `MediaCrumbs.vue`, `MediaBulkBar.vue`, `MediaFilterRail.vue`, `MediaFilterChips.vue` var. **Grace period içinde geri alınabilir toplu silme ölçülmedi** |
| **T-095** | Erişilebilirlik ve i18n doğrulaması | **axe-core taraması critical/serious bulgu üretmiyor**; tüm akış yalnız klavyeyle; `aria-live` duyuruları; TR/EN tam, **eksik anahtar CI'ı kırar**; AA kontrast | **KISMİ** | Elle yazılmış a11y testleri **var ve geçiyor**: `cropStudioA11y.test.js` (22 test), `simulatorA11y.test.js` (17 test), klavye kısayolları (`cropShortcuts.js`, `MediaShortcutsModal.vue`). Ama **`axe-core` bağımlılık olarak kurulu değil** → kaynağın adıyla istediği tarama **hiç koşmuyor**. **Eksik i18n anahtarını CI'da kıran bir kapı bulunamadı**. AA kontrast **ölçülmedi** |

---

## 3 · Faz 10 — Crop Studio

| ID | Başlık | Kaynağın kabul kriteri (özet) | Durum | Kanıt |
|---|---|---|---|---|
| **T-100** | Crop çekirdeği: paylaşılan geometri | TS ve Python **aynı test vektörlerinde aynı sonucu** veriyor; vektörler JSON'da, **iki tarafta da koşuluyor**; tolerans ≤ 0.5 px | **KISMİ** | **Madde olarak doğru, kapı olarak kırmızı.** Ben host node v24 ile koşturdum: **584 vektör, uyuşmazlık 0, en büyük sapma 0 px** — tolerans fazlasıyla sağlanıyor. Ancak reponun kendi koşumunda **`test_crop_geometry` FAILED** (konteyner node v20.19.2 `--experimental-strip-types` desteklemiyor) → "iki tarafta da koşuluyor" kriteri **bugünkü ortamda karşılanmıyor**. Python tarafı 37 testin 36'sı geçiyor |
| **T-101** | Crop stage (tutamak, zoom, focal) | 8 tutamak + gövde + zoom + focal, pointer events; oran kilidi taşmasız; **etkileşimde 60 fps**; klavyeyle piksel hassasiyeti; undo/redo; yüksek çözünürlük önizlemede küçültülür | **KISMİ** | `CropCanvas.vue`, `CropHandles.vue`, `CropToolbar.vue`, `lib/media/crop/cropHandles.js` (13 test), `useCropHistory.js` (undo/redo), `cropShortcuts.js` (klavye) — hepsi var ve `npm test`'te geçiyor. **60 fps ölçülmedi** (paralel ajanlar nedeniyle zamanlama ölçümü yapılmadı) |
| **T-102** | Canlı çoklu önizleme (rendition kartları) | Tüm slot profilleri için kart, gerçek CSS ölçüsünde; değişimde **16 ms içinde** güncelleme, sunucu isteği yok; kartta profil/px/fit/yeterlilik; yetersiz kaynak uyarısı; profil override | **KISMİ** | `CropPreviewStrip.vue` + `lib/media/crop/slotProfiles.js` + `vendor/slot_profiles.js` var. **16 ms bütçesi ölçülmedi** |
| **T-103** | Otomatik odak önerisi + güvenli alan | **Öneri Web Worker'da**, ana iş parçacığı bloklanmaz; eşik altı güven gizlenir; "öneri" rozeti, onayda `method=manual`; güvenli alan çizilir | **KISMİ** | `lib/media/crop/focusSuggest.js` var. **Web Worker kullanımı bulunamadı** — hesap ana iş parçacığında görünüyor. Eşik/rozet/`method=manual` akışı ölçülmedi |
| **T-104** | Politika uyarıları + crop intent kaydı | Canlı uyarılar; DPI/piksel açıklaması; **reject seviyesi ihlal yokken kaydetmeye izin**; kaydedilen intent JSON API şemasına uyar ve **`previewed_placements` içerir**; kayıt sonrası hangi rendition'ların yeniden üretileceği | **KISMİ** | Uyarı tarafı gerçek: `cropPolicy.js` (20 test), `cropWarnings.js`, `CropPolicyNotice.vue` — geçiyor. **Kayıt tarafı YOK**: `useCropStudio.js:329` `saveAvailable = false` sabit; `Media Crop Intent` DocType'ı **canlı DB'de kurulu değil** (§0.4); **`previewed_placements` repoda hiç geçmiyor**. Kodun kendi yorumu da bunu söylüyor: *"bu yükü alacak bir uç BUGÜN YOKTUR"* |
| **T-105** | Faz 10 kapanış: crop doğruluk kabulü | **UI önizlemesi sunucu rendition'ıyla piksel düzeyinde eşleşiyor**; **20 gerçek görselde elle karşılaştırma** yapılmış ve raporlanmış; etkileşim performans hedefleri tutuyor | **YOK** | Ölçülen parite **geometri hesabının** paritesidir (TS ↔ Python sayı uyumu), **UI önizlemesi ↔ sunucunun ürettiği gerçek rendition** karşılaştırması değildir. 20 görsellik elle karşılaştırma raporu repoda bulunamadı. Etkileşim performansı ölçülmedi |

> **Brief'teki "geometri paritesi 592 vektörde 0 px" iddiası doğrudur** (584 koşulan + 8 hata
> vakası), fakat iki uyarıyla: (1) bunu ölçen test **repo ortamında kırmızı**, (2) bu parite
> T-105'in istediği **UI ↔ sunucu piksel paritesi değildir**.

---

## 4 · Faz 11 — Simülatör

⚠️ **Numara hizalaması:** Kaynağın **T-110**'u tek görevdir — *"Cihaz **ve yerleşim**
kataloğunun veri olarak tanımı"*. İç kayıt bunu ikiye bölmüş ve kayma sonucu kaynağın
gerçek **T-111'ini (cihaz çerçevesi ve sayfa şablonu render motoru) TAM saymış**.
Aşağıda **kaynağın numaraları** kullanılmıştır ve T-111 özellikle ölçülmüştür.

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-110** | Cihaz ve yerleşim kataloğunun veri olarak tanımı | `devices.json` + `placements.json` var, yeni cihaz/sayfa kod değişmeden eklenebiliyor; **her yerleşim gerçek uygulamanın CSS breakpoint'leriyle doğrulanmış** (aynı sütun sayısı, aynı kutu ölçüsü); sapmada uygulama CSS'i kaynak kabul edilir | **KISMİ** | Dosyalar **iki tarafta da var**: `tradehub_core/media/pipeline/simulator/{devices,placements}.json` ve panelde `lib/media/simulator/vendor/`. Hash zincirli vendor senkronu (`sync-simulator.mjs`, `vendor.manifest.json`) ✅. Panel testi 13 cihaz + 15 yerleşim listeliyor ✅. **Ama CSS doğrulaması yapılmamış** — parite testinin kendi docstring'i açıkça yazıyor: *"`devices.json`/`placements.json` değerleri de **ölçülmedi** — emülasyon/CSS aritmetiği"*. Ekran da bunu üstte beyan ediyor. Kriterin ikinci maddesi **karşılanmıyor** |
| **T-111** | **Cihaz çerçevesi ve sayfa şablonu render motoru** | Her cihaz **gerçek CSS genişliğinde render** edilip ekrana **`transform: scale()`** ile sığdırılıyor (yeniden düzen yok); **ölçek yüzdesi kullanıcıya gösteriliyor**; sayfa şablonları **gerçek grid mantığını taklit ediyor**; **13 cihaz × 5 sayfa = 65 kombinasyon hatasız render**; ilk boyama < 1.5 sn | **YOK** | **Render motoru yok.** Simülatör bir *seçim hesaplayıcısı + matris tablosudur*. Bileşenlerin tamamı: `SimMatrixTable.vue`, `SimOptionGroup.vue`, `SimPosterCard.vue`, `SimResultCard.vue` — **cihaz çerçevesi bileşeni yok**. `transform: scale()` ile cihaz render'ı **hiçbir yerde yok** (bulunan tüm `transform` isabetleri `text-transform: uppercase` ve `grid-template-columns`). **Ölçek yüzdesi göstergesi yok. Sayfa şablonu / grid taklidi yok.** 65 kombinasyon **render edilmiyor, tabloda basılıyor** — panel testinin kendi adı: *"65 kombinasyonun tamamı **tabloda** basılıyor"*. `MediaSimulatorView.vue`'nun kendi docstring'i de motoru değil seçimi tarif ediyor: *"Ekranın işi seçim, gösterim ve dürüstlük"*. İlk boyama ölçülmedi (ölçülecek bir render de yok) |
| **T-112** | srcset seçim göstergesi + çözünürlük yeterlilik uyarısı | Her yerleşim için "tarayıcı hangi rendition'ı indirir" hesaplanıyor; kaynak yetersizse **kırmızı uyarı**; **tahmini indirilecek bayt** gösteriliyor; **LCP elementi işaretleniyor** | **KISMİ** | Seçim hesabı **var ve ölçüldü**: `lib/media/simulator/select.js`; backend `test_simulator_srcset` **34/34 geçti**, 65 kombinasyonda `kaynak_yetersiz=0`, `asiri_servis=1`, `zoom_yetersiz=6`. LCP işareti **var**: `layout.js:75` `lcpCandidate`. Yetersizlik uyarısı **var**. **Yerleşim başına "tahmini indirilecek bayt" bulunamadı** — `formatBytes` yalnız poster kartında `POSTER_SPEC.maxBytes` için kullanılıyor |
| **T-113** | Video slotu için poster/oynatma simülasyonu | Poster kadrajı **ve otomatik oynatma davranışı**; **mobilde ilk 10 saniyede inecek tahmini bayt**; **`prefers-reduced-motion` ayrı önizleme**; kapak üstü UI güvenli alan ihlali uyarısı | **KISMİ** | Poster tarafı var ve testli: `SimPosterCard.vue`, `lib/media/simulator/poster.js`, parite testinde **13 poster vektörü**. **`prefers-reduced-motion` repoda simülatör tarafında hiç geçmiyor. Otomatik oynatma davranışı simülasyonu yok. İlk 10 saniye bayt tahmini yok.** Dört maddenin üçü karşılanmıyor |
| **T-114** | Onay kapısı ve `previewed_placements` kaydı | Kullanıcı tüm yerleşim sınıflarını **görmeden onaylayamıyor**; görünürlük eşiği (≥1 sn ve %50 görünür) ile izleme; uyarılı yerleşimde açık kabul; **kayıt sunucuda da doğrulanıyor**; **audit log** | **YOK** | **`previewed_placements` ne panelde ne backend'de geçiyor** (arama yalnız ilgisiz `approvalQueue`/i18n isabetleri verdi). Görünürlük eşiği izleme yok, onay kapısı yok, sunucu tarafı doğrulama yok, audit log yok. `Media Placement Preview` DocType'ı da **kurulu değil** (§0.4). T-082'nin `previewed_placements` maddesiyle birlikte düşer |
| **T-115** | Simülatörün gerçek sayfayla doğrulanması (drift testi) | Her cihaz için **gerçek sayfa ile simülatör önizlemesi otomatik karşılaştırılıyor**; kutu ölçüsünde **2 px üzeri sapma CI'da kırmızı**; sapma raporunda sebep CSS değişikliği gösteriliyor; **test günlük çalışıyor** | **YOK** | Böyle bir test yok. `srcsetParity.test.js` panelin JS'ini **Python referansıyla** karşılaştırır — **gerçek sayfayla değil**; docstring'i bunu açıkça dışlıyor: *"ÖLÇÜLMEZ — … gerçek tarayıcı davranışı"*. 2 px CI kapısı yok, günlük koşum yok, sapma-sebep raporu yok. `sync-simulator.mjs`'in hash zinciri veri senkronunu korur, **CSS drift'ini değil** |

> **Brief'teki "65 ve 195 kombinasyonda 0 sapma" iddiası doğrudur ve ölçüldü** — ama bu
> **srcset seçim paritesidir** (panel JS ↔ Python referansı), T-115'in istediği
> **simülatör ↔ gerçek sayfa** drift'i değildir. İki şey aynı ada sahip değildir.

---

## 5 · Sayım

| Faz | Görev | TAM | KISMİ | YOK |
|---|---|---|---|---|
| **Faz 8** — API | 6 (T-080…T-085) | **1** (T-083) | **4** (T-080, T-082, T-084, T-085) | **1** (T-081) |
| **Faz 9** — Medya kütüphanesi | 6 (T-090…T-095) | **0** | **5** (T-090, T-092, T-093, T-094, T-095) | **1** (T-091) |
| **Faz 10** — Crop Studio | 6 (T-100…T-105) | **0** | **5** (T-100…T-104) | **1** (T-105) |
| **Faz 11** — Simülatör | 6 (T-110…T-115) | **0** | **3** (T-110, T-112, T-113) | **3** (T-111, T-114, T-115) |
| **Toplam** | **24** | **1** | **17** | **6** |

---

## 6 · Kapanışı engelleyen üç madde

1. **`Media Crop Intent` DocType'ı kurulu değil.** 16 spec dosyasına karşılık 6 gerçek
   DocType var. Bu tek eksik, T-082'nin `save_intent`'ini, T-104'ün tamamını ve
   T-105'in ön koşulunu birlikte düşürüyor. Panel'in `saveAvailable=false` sabiti
   sebep değil **sonuçtur**.

2. **Kaynağın T-111'i (render motoru) hiç yapılmamış.** İç kayıttaki numara kayması bunu
   TAM göstermiş. Ölçülen: cihaz çerçevesi bileşeni yok, `transform: scale()` yok, sayfa
   şablonu yok, ölçek yüzdesi yok. Faz 11'in görsel çekirdeği eksik; mevcut ekran
   dürüst ama farklı bir şey — bir srcset seçim hesaplayıcısı.

3. **İki test kapısı gerçekte kapalı.** (a) `test_crop_geometry` konteynerde **kırmızı**
   (node v20 < 22.6); T-100'ün asıl sözü CI'da ölçülmüyor. (b)
   `test_http_api_contracts`'ın **7 canlı testi varsayılan koşumda atlanıyor**;
   `ISTOC_HTTP_BASE` veren bir yapılandırma bulunamadı. Her iki testin de içeriği
   sağlam — sorun yalnızca koşum ortamı. Konteyner node'unu 22.6+ yapmak ve CI'a
   `ISTOC_HTTP_BASE` + `ISTOC_HTTP_HOST` eklemek ikisini de yeşile çevirir.

## 7 · Ölçülmedi (dürüstlük listesi)

Aşağıdakiler hakkında bu raporda **hiçbir geçti/kaldı hükmü yoktur**:
tüm zamanlama/performans hedefleri (60 fps, 16 ms, <1.5 sn, ilk boyama, 50 dosya akıcılığı,
10.000 varlık kaydırma) — paralel ajanlar nedeniyle kasten ölçülmedi;
ETag/304 davranışı; SSIM'li kalite raporu; AA kontrast oranları; toplu silmenin grace
period geri alımı; gerçek tarayıcı srcset seçimi; `devices.json`/`placements.json`
değerlerinin gerçek CSS'e uygunluğu.

**Yan etki bırakılmadı:** hiçbir kaynak dosya değiştirilmedi, bayrak açılmadı, test kaydı
üretilmedi, imaj kurulmadı. Yalnız bu rapor dosyası yazıldı.
