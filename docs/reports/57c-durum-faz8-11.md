# 57c · Faz 8–11 durum ölçümü — 24 görev

**Tarih:** 2026-08-19 · **Yöntem:** salt okuma + koşum · **Ölçüm penceresi:** 22:27:59 – 22:47:04
**Depolar:** `tradehub_core` (`ahmet`), `admin-panel` (`ahmet`) · **Canlı site:** `istoc.localhost` (docker compose)
**Numaralandırma:** kaynak dokümanın (`.../62-faz11-simulator.html` vb.) kendi ID'leri. Faz 11'de iç kayıttaki
kayma **kullanılmadı**: kaynağın **T-110**'u "cihaz **ve yerleşim** kataloğu" tek görevdir, **T-111** render motorudur.

> ### Ölçüm koşulları — okumadan önce
>
> Ölçüm sırasında aynı makinede **7 ajan kod yazıyordu**, üçü panelde. Panel testi ölçüm penceresi
> içinde **değişti** (§0.2); her sayının saati yazılıdır. **Hiçbir süre/FPS/ilk-boyama iddiası yoktur** —
> zamanlamaya bağlı her kabul ölçütü "ölçülmedi" olarak işaretlendi. `bench migrate` **koşulmadı**.
> Hiçbir bayrağa dokunulmadı, hiçbir kaynak dosya değiştirilmedi; yalnız bu dosya yazıldı.

---

## 0 · Koşturulan ölçümler (ham çıktı, saatiyle)

| # | Saat | Komut | Sonuç |
|---|---|---|---|
| 1 | 22:28:42–44 | `bench --site istoc.localhost run-tests --module …test_api_contracts` | **Ran 126 — OK** |
| 2 | 22:29:03–08 | `…test_http_api_contracts` (iki deneme) | **ÇÖKTÜ** — `helpdesk/test_utils.py::make_new_sla` → `TimestampMismatchError`. Ürün kusuru DEĞİL: paralel ajanların `before_tests` yarışı |
| 3 | 22:29:16–22 | `…test_http_api_contracts` + `ISTOC_HTTP_BASE=http://127.0.0.1:8000` `ISTOC_HTTP_HOST=istoc.localhost` | **Ran 41 — OK (skipped=6)** |
| 4 | 22:30:00–22:31:17 | aynısı + `ISTOC_HTTP_USER=Administrator` `ISTOC_HTTP_PASS=admin` | **Ran 41 — OK, 0 atlandı** |
| 5 | 22:37:48 | `…test_crop_geometry` | **Ran 37 — OK (skipped=1)** |
| 6 | 22:38:06 | `…test_simulator_srcset` | **Ran 34 — OK** |
| 7 | 22:38:19 | `…test_crop` | **Ran 26 — OK** |
| 8 | 22:40:00–22:42:24 | `…test_media_crop_intent` | **Ran 17 — OK** |
| 9 | 22:38:58–22:39:02 | `admin-panel/frontend$ npm run parity:crop` | **tests 72 · pass 72 · fail 0 · skipped 0** |
| 10 | 22:28:40–22:29:00 | `admin-panel/frontend$ npm test` **(1. ölçüm)** | **tests 571 · pass 570 · fail 1** |
| 11 | 22:29:55–22:31:18 | `npm test` **(2. ölçüm)** | **tests 571 · pass 570 · fail 1** — 1. ile aynı |
| 12 | 22:45:01–22:45:20 | `npm test` **(3. ölçüm)** | **tests 609 · pass 609 · fail 0** |

`npm run build` **koşturulmadı** (aynı dizinde üç ajan çalışıyor).

### 0.1 · Faz 8 sayısal iddiaları — doğrulandı

`docs/api/openapi-http.yaml` gerçek YAML ayrıştırıcıyla okundu (22:33):

| Brief'teki iddia | Ölçüm | Sonuç |
|---|---|---|
| 87 → **90 yol** | `paths: 90`, `operations: 90`, `x-endpoint-count: 90` | ✅ |
| ölçülmemiş uç 77 → **1** | `x-unmeasured-endpoints` uzunluğu = **1** (`x-measured` 69, `x-partially-measured` 20, `x-mismatched` 0) | ✅ |
| sözleşme testi 25 → **41, 0 atlama** | **41** doğru. **"0 atlama" YALNIZ kimlik verilirse:** `ISTOC_HTTP_BASE`+`HOST` ile 41/41 **skipped=6**; `+USER`+`PASS` ile 41/41 **0 atlama** | ⚠️ koşullu |
| misafire açık uç = 3 | `security: []` taşıyan operasyon = 3, `x-guest-endpoints` = 3, iki küme birebir aynı | ✅ |
| `openapi.yaml` değişmedi | `git status --porcelain docs/api/` → yalnız `?? openapi-http.yaml` | ✅ |

**6 atlanan test** `@unittest.skipUnless(CANLI_TABAN and CANLI_KULLANICI and CANLI_PAROLA)` ile korunan
`YetkiliCanliTesti` sınıfıdır. `ISTOC_HTTP_USER`/`PASS` veren bir CI yapılandırması **bulunamadı** — yani
CI'ın gördüğü sayı 41/41 değil, **41/41 (skipped=6)**'dır.

### 0.2 · Panel testi ölçüm penceresi içinde değişti — iki farklı sonuç, ikisi de yazılı

| Saat | tests | pass | fail |
|---|---:|---:|---:|
| 22:28:40 | 571 | 570 | **1** |
| 22:29:55 | 571 | 570 | **1** |
| **22:45:01** | **609** | **609** | **0** |

**Kırmızı olan test:** `src/views/system/__tests__/mediaSimulator.test.js:73` —
*"ekran dört dilde de çiziliyor ve çeviri anahtarı sızmıyor"*. Sebep uydurma değil, **ölçüldü**:
`SimPosterCard.vue` / `SimResultCard.vue`'nun kullandığı ~20 `mediaSimulator.poster.*` ve
`mediaSimulator.result.*` anahtarı **dört dilin hiçbirinde yoktu** (`src/i18n/locales/*.js` son yazma
19:42; bileşenler 20:26). Anahtarlar SSR çıktısına ham metin olarak sızıyordu.

22:42–22:43'te `SimPosterCard.vue`, `SimResultCard.vue` ve `SimApprovalGate.vue` yeniden yazıldı;
22:45 ölçümünde suite yeşil ve 38 test daha büyük. **Locale dosyaları hâlâ 19:42 tarihli** (22:45:38'de
doğrulandı) — yani sızıntı anahtar eklenerek değil, bileşen tarafında kapatıldı. Bu, T-095'in
"eksik anahtar CI'ı kırar" maddesinin **gerçekten çalıştığının** kanıtıdır: kapı bugün bir kez kırmızı
yandı ve 16 dakika içinde kapatıldı.

### 0.3 · Canlı DocType denetimi — rapor 35'e göre değişti

`frappe.db.exists("DocType", …)`, canlı `istoc.localhost` (22:33):

```
Media Crop Intent        -> KURULU      (rapor 35'te YOKTU)
Media Crop Override      -> KURULU      (rapor 35'te YOKTU)
Media Upload Session     -> None        (hâlâ yok)
Media Placement Preview  -> None        (hâlâ yok)
Media Asset / Rendition / Usage / Version / Profile /
Storage Settings / Engine Settings / Processing Job -> KURULU
```

Kurulu `Media%` DocType sayısı: **10** (rapor 35'te 6). Satır sayıları: `Media Crop Intent` 0,
`Media Crop Override` 0, `Media Asset` 0, `Media Rendition` 0, `Media Usage` 0, `Media Version` 0.
**Tablolar kurulu ama boş** — bu, "gerçek rendition baytı" ya da "SSIM" gösteren her ekranın bugün
"—" bastığı anlamına gelir (T-093, T-112).

### 0.4 · `overrides` yolu — KIRIK değil ama ÖLÇÜLMEDİ; iki belge şimdi **eskimiş**

Brief `Media Crop Override.profile`in docname (`product.image:w384`) beklediğini, `crop.py`nin kısa ad
(`w384`) beklediğini söylüyordu. **Canlı ölçüm (22:34):**

```
Media Crop Override alanları (DocField, canlı DB):
  profile  Data   (options: None)   ← Link DEĞİL
  x,y,w,h  Float
  method   Select (manual|smartcrop)
```

`tradehub_core/tradehub_core/doctype/media_crop_override/media_crop_override.json` dosya damgası
**22:14** — yani ölçümümden 14 dakika önce `Link → Media Profile` **`Data`ya çevrilmiş** ve migrate
edilmiş. `core/crop.py::override_for` zaten düz dizge karşılaştırması yapıyor (`str(key) != profile_key`),
dolayısıyla kısa ad artık iki katmanda da geçerlidir.

**Ama uçtan uca ölçülmedi.** Bunu ölçmek `Media Asset` + `Media Crop Intent` yazmayı gerektirir; bu görev
salt okumadır ve `Media Asset` tablosu boştur. `test_media_crop_intent.py` içinde `overrides` geçmiyor
(grep: 0 isabet) — yani **repo da bu yolu sınamıyor**.

Bu düzeltmeden sonra **iki belge yanlış bilgi taşıyor**:

1. `docs/api/openapi-http.yaml` → `save_intent` altındaki `x-mismatch`: *"`overrides` yolu UÇTAN UCA
   ÇALIŞMIYOR … `Media Crop Override.profile` bir `Link → Media Profile`tır"* — **artık değil.**
2. `admin-panel/frontend/src/composables/useSimulatorApproval.js` modül başlığı aynı gerekçeyle
   `overrides` anahtarını **yasaklıyor** (`withPreviewedPlacements` `TypeError` fırlatıyor).
3. `tradehub_core/media/pipeline/doctype_specs/media_crop_override.json` **spec'i hâlâ `Link → Media
   Profile` diyor** — spec ile gerçek DocType artık ayrışmış durumda.

### 0.5 · TS ↔ Python parite kapısı — düzeldi, ama iki ayrı yerde

| Kapı | Ölçüm | Not |
|---|---|---|
| Panel: `npm run parity:crop` | **72/72 · 0 atlama** (22:38:58) | Kapı artık türetilmiş `vendor/crop_geometry.js` üzerinden koşuyor; **hiçbir node bayrağı gerekmiyor**. Brief'in "tip soyma kapalıyken 72/72" iddiası **doğrulandı** |
| Python: `test_crop_geometry` | **37/37 OK, skipped=1** (22:37:48) | Atlanan test `TypeScriptPariteTesti::test_ts_ikizi_ayni_sayiyi_veriyor`. Sebep ölçüldü: konteynerde `which node` **boş** (`PATH=/usr/local/bin:/usr/bin:/bin:…`, nvm PATH'te değil) → `shutil.which("node")` None → `skipTest` |

Yani **rapor 35'teki kırmızı kapı artık kırmızı değil — ama yeşil de değil, SESSİZ.** Python tarafı
node'u hiç bulamadığı için TS ikizini çağırmıyor; ölçümü panel deposu yapıyor. Python'un **kendi**
vektör koşumu geçiyor ve sayıyı basıyor:

```
[çapraz]     crop.py ↔ crop_geometry.py en büyük sapma = 1.818989e-12 px
[çapraz-kutu] 800 örnek · 1 px yuvarlama farkı olan = 0
[oran]       3652 örnek · en büyük bağıl oran sapması = 2.070e-16
[vektör]     584 vektör · en büyük sapma = 0.0 px (yok)
```

### 0.6 · T-105 · UI ↔ sunucu piksel paritesi — üç ayrışmanın **üçü de açık**

`src/lib/media/crop/__tests__/cropPixelParity.test.js` (dosya damgası **20:26**, 22:45:38'de yeniden
okundu — **değişmemiş**) 600 vakayı beş sınıfta donduruyor:

| Sınıf | Vaka | Sapan | En büyük sapma (px) | Sebep (testin kendi beyanı) |
|---|---:|---:|---:|---|
| A · oran kilitli, zoom yok | 120 | 5 | **1** | yuvarlama ifadesi: panel `floor(v+0.5)`, sunucu `int(round(v))` |
| **B · zoom** | 120 | **119** | **7391** | **zoom KAYDEDİLMİYOR** — `savePayload` yalnız odak + override taşır |
| **C · serbest kırpma + override** | 120 | **104** | **3704** | sunucu override'ı profilin oranına zorlar, panel serbest dikdörtgeni gösterir |
| D · kilitli oran + override | 120 | 7 | **1** | yalnız yuvarlama |
| **E · serbest kırpma, override yok** | 120 | **86** | **3481** | panel taban bölgeyi gösterir, sunucu profil oranına kırpar |

**Brief "C5 zoom'u kapattı (sapma < 0,5 px)" diyor — çalışma ağacında böyle bir değişiklik YOK.**
Doğrulama: `useCropStudio.js:490-506` `savePayload`'ı okundu; gönderilen alanlar `focal_x/y`,
`safe_area`, `method`, `algorithm`, `confidence`, `approved_by_user`, `overrides` — **`zoom` yok**.
Test dosyasının B satırı hâlâ `enBuyuk: 7391`. C5'in işi başka bir dalda/worktree'de olabilir; **bu
ölçüm çalışma ağacınadır** ve 22:45 itibarıyla **üç ayrışma da açıktır**.

### 0.7 · T-081/091 · sunucuda tus **YOK** — doğrulandı, ama tablo rapor 35'ten farklı

```
grep -rni "tus-resumable|upload-offset|upload-length"  tradehub_core/ docs/api/   → 0 isabet
grep -rni "Idempotency-Key"                            tradehub_core/ docs/api/   → 0 isabet
admin-panel/frontend/package.json                      → uppy YOK, tus-js-client YOK
```

**Ama "YOK" demek artık yanlış olur:** tus'suz, kendi sözleşmesini konuşan **çalışan bir parçalı
yükleyici var** ve openapi'de belgeli:

- Sunucu: `tradehub_core/media/chunked.py` (`begin` / `put_chunk` / `finish` / `meta_of` / `cleanup`,
  `SESSION_TTL_HOURS = 6`), uçlar `api/seller_media.upload_begin|upload_chunk|upload_finish|upload_status`
  — dördü de `openapi-http.yaml`'ın 90 yolu içinde.
- Panel: `src/lib/media/upload/session.js` (kaldığı yerden devam — `upload_status` ile sunucudan
  alınan `received[]` üzerinden), `preflight.worker.js` + `preflightClient.js` (**gerçek Web Worker**),
  `PreflightPanel.vue`, `UploadDropzone.vue`, `browser-image-compression` bağımlılığı (istemci küçültme).
- `session.js`'in kendi başlığı tus'un neden kurulmadığını yazıyor: *"`tus-js-client` kurmak, konuşacağı
  bir sunucu olmadan ölü bir bağımlılık olurdu."* — bu bilinçli bir **ARAÇ/PROTOKOL** kararıdır.

**Ölçülen gerçek eksik:** `chunked.cleanup()` hiçbir yerden çağrılmıyor —
`grep -rn "chunked" --include=*.py` yalnız `api/seller_media.py`'yi veriyor, `hooks.py`'nin
`scheduler_events` listesinde geçmiyor. Yani *"yarım oturumlar zamanlanmış işle temizlenir"* maddesi
**karşılanmıyor**: fonksiyon var, zamanlayıcı yok.

---

## 1 · Faz 8 — API katmanı

| ID | Başlık | Kaynağın kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-080** | OpenAPI sözleşmesi (contract-first) | Tüm uçlar/şemalar/hata kodları; **spectral** lint geçiyor; her uçta örnek istek/yanıt; şemadan **TS tipleri üretilip frontend kullanıyor** | **KISMİ** | 90 yol / 90 operasyon, 69 ölçülmüş + 20 kısmen + **1 ölçülmemiş**, 10 maddelik `x-contract-deviations` (22:33). Örnekler `x-measurement` olarak gerçek çağrıdan geliyor. **Spectral yok** (`.spectral*` bulunamadı, `package.json`'da yok). **Üretilmiş TS tipi yok** (`openapi-typescript`/`openapi-generator` bağımlılık listesinde yok) | ARAÇ |
| **T-081** | Upload session + resumable (tus) | `create_session` politika+kota; **tus** ile devam; `finalize` sunucu doğrulaması; aynı **`Idempotency-Key`** ikinci `finalize`'da aynı sonuç; yarım oturumlar zamanlanmış işle temizlenir | **KISMİ** | §0.7: parçalı yükleme uçtan uca var ve openapi'de belgeli, devam `upload_status` ile gerçek. **tus başlığı repoda 0 isabet, `Idempotency-Key` 0 isabet, `uppy`/`tus-js-client` kurulu değil (bilinçli).** `chunked.cleanup()` **zamanlanmamış**. `Media Upload Session` DocType'ı **kurulu değil** | ARAÇ |
| **T-082** | Crop intent + önizleme uçları | `save_intent` koordinat doğrular ve **yalnız etkilenen rendition'ları kuyruğa alır**; `suggest_focal` güven skoru; `preview` kalıcı yazmadan; **`previewed_placements`** kaydediliyor | **KISMİ** | Üç uç canlı ve ölçüldü: `test_media_crop_intent` **17/17 OK** (22:40–22:42) — idempotency (ikinci çağrıda satır sayısı 1), 0-1 reddi, bilinmeyen method reddi, kiracı izolasyonu, misafir 403. `test_http_api_contracts::test_kirpma_uclari_misafire_KAPALI` canlıda **41/41** içinde geçti. `previewed_placements` DocType alanı (JSON) **var** ve `save_intent` yazıyor. **Eksik: rendition kuyruğa alma yok** — `grep -n "rendition\|kuyru\|enqueue\|queue" api/media_crop.py` → **0 isabet**. `overrides` yolu §0.4: düzeltilmiş görünüyor ama **uçtan uca ölçülmedi ve repoda testi yok** | AJAN |
| **T-083** | Manifest ve teslim uçları | profil/oran/odak/LQIP + format→genişlik→URL matrisi; üretilmemiş genişlik yok; `manifest_batch` tek istekte N varlık; **ETag/304**; yayımlanmamış varlık 404/403 | **KISMİ** | `get_manifest` + `get_manifest_batch` misafir uçları canlıda ölçüldü (41/41). `missing` daima boş (numaralandırma kehaneti), `max_batch=50`, alt gövdelerde `etag` yok — hepsi test edildi. Misafir imzalı adres alamıyor (403), imzasız `download` 403. **ETag var, `304` YOK:** `test_if_none_match_not_modified_gövdesi` bilerek `assertEqual(durum, 200)` diyor — *"Bu katman 304 ÜRETMEZ; gövdede bayrak taşır"*. Üstelik `x-contract-deviations[0]` **iki ayrı sözleşme** olduğunu yazıyor: `get_manifest` → `{not_modified, etag, cache_control}`, `get_intent` → `{etag, status: 304}` | KARAR |
| **T-084** | Yönetim uçları + contract testleri | Admin uçları kapalı, **negatif** yetki testleri; **schemathesis/dredd** ile şema doğrulama; **fuzzing** ile beklenmedik 5xx yok; hata kodları i18n | **KISMİ** | `test_api_contracts` **126/126 OK** (22:28:42). `test_http_api_contracts` **41/41, 0 atlama** (22:30–22:31). Negatif yetki **örneklem değil, tam tarama**: `test_misafir_TUM_oturumlu_uclarda_reddediliyor` 90 ucun oturum isteyen **87'sinin tamamını** çağırıp 403 doğruluyor. **`schemathesis`/`dredd` repoda hâlâ yok** (grep: yalnız eski raporlarda geçiyor) → şema güdümlü fuzzing yapılmıyor. Bilinen sapmalar (417/500/`TypeError`) belgede **beyan edilmiş**, gizlenmemiş | ARAÇ |
| **T-085** | Faz 8 kapanış: dondurma + SDK | OpenAPI v1 donduruldu, breaking-change süreci belgeli; **TS istemci SDK** üretilmiş ve frontend kullanıyor; **Postman/Bruno** koleksiyonu | **KISMİ** | Dondurma **gerçek ve ölçüldü**: dosya başlığı "ÜRETİLMİŞ DOSYA — ELLE DÜZENLEMEYİN", üretici `scripts/gen_http_openapi.py`, sapma testi `test_http_api_contracts` içinde ve **41/41 içinde geçti** (bayt bayt kilit). **TS SDK yok. Postman/Bruno yok** (`*.bru`, `*postman*` → 0 isabet) | ARAÇ |

---

## 2 · Faz 9 — Medya kütüphanesi arayüzü

| ID | Başlık | Kaynağın kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-090** | İskelet, tasarım sistemi, API istemcisi | Vue 3 + **TypeScript (strict)** + Vite + Pinia + **Vitest**; DS bileşenleri; **OpenAPI tipli** API istemcisi; i18n (TR/EN) | **KISMİ** | Vue 3 + Vite + Pinia + `vue-i18n 11` ✅, i18n **4 dil** (tr/en/ar/ru) ✅ kriteri aşıyor, DS bileşenleri geniş ✅. **TypeScript strict YOK** — `tsconfig*` dosyası **yok**, `src` altında **10 `.ts`** karşılık **607 `.js`/`.vue`** (22:37 sayımı). **Vitest YOK** — `"test": "node --test"`. **OpenAPI tipli istemci yok** | KARAR |
| **T-091** | Uppy + tus yükleyici ve preflight paneli | Sürükle-bırak/klasör/yapıştır; **Web Worker**'da dosya başına preflight; ihlalde yükleme başlamaz; cihaz bütçesine göre istemci küçültme; kesintiden sonra **devam**; 50 dosyada akıcı UI | **KISMİ** | **Rapor 35'te YOK'tu, artık değil.** `preflight.worker.js` + `preflightClient.js:34` `new Worker(new URL("./preflight.worker.js"), {type:"module"})` — **gerçek Web Worker**. `dropFiles.js`, `UploadDropzone.vue`, `PreflightPanel.vue`, `UploadQueueRow.vue`, `MediaUploader.vue` var. Devam `session.js` + `upload_status` ile gerçek. İstemci küçültme `browser-image-compression`. **`uppy`/`tus-js-client` kurulu değil** (§0.7, bilinçli). **50 dosyada akıcılık ölçülmedi** | ARAÇ |
| **T-092** | Grid, arama, filtre, sanal kaydırma | 10.000 varlıkta akıcı sanal kaydırma; **LQIP + CLS = 0**; çok alanlı arama; **filtre durumu URL'de**; canlı işlem durumu; **`manifest_batch` tek istek (N+1 yok)** | **KISMİ** | Sanal kaydırma `useVirtualGrid.js` + `virtualGrid.test.js` ✅. LQIP/CLS `MediaImage.vue` + `mediaCls.test.js` ✅. **Filtre durumu URL'de — YENİ ve ölçüldü:** `MediaLibraryView.vue:1060` `decodeFilterQuery(route.query, FILTER_SCHEMA, URL_DEFAULTS)`, `:1084` `router.replace({query})`, `:1089` adres→ekran yönü de bağlı. **`manifest_batch` panelde hâlâ HİÇ kullanılmıyor** (`grep -rn "manifest_batch" src lib` → 0 isabet) → **N+1 kriteri karşılanmıyor**. 10.000 varlıkta akıcılık ölçülmedi | AJAN |
| **T-093** | Detay çekmecesi: versiyon/rendition/kullanım/kalite | Kaynak↔normalize yan yana; insan dilinde kalite raporu; **SSIM'li** rendition listesi; kullanım listesi; yeniden işle/crop/indir/silme talebi; denetim geçmişi | **KISMİ** | **Kaynak↔normalize yan yana VAR:** `MediaQualityPanel.vue` — *"Detay çekmecesinin KALİTE sekmesi — kaynak ile normalize sonuç yan yana"*, ölçü/MP/DPI/format/renk uzayı/alfa sütunları. **SSIM VAR:** `MediaRenditionList.vue:85` SSIM sütunu, `useMediaRenditions.js:107` ölçülmemişse "—" basıyor, `mediaRenditions.test.js` bunu sınıyor. `MediaUsageDialog`, `MediaRecordDialog`, `mediaActions.js`, `mediaDetailDrawer.test.js` var. **Ama canlı DB'de `Media Rendition` = 0 satır** (§0.3) → ekran bugün her sütunda "—" basar; kalite raporunun **gerçek veriyle** çalıştığı ölçülmedi | AJAN |
| **T-094** | Klasör/etiket organizasyonu + toplu işlemler | Klasör ağacı, sürükle-bırak taşıma, yeniden adlandırma; etiketleme; toplu işlem + **kısmi hata raporu**; **toplu silme grace period içinde geri alınabilir** | **KISMİ** | **Kısmi hata raporu VAR ve yeni:** `MediaBulkBar.vue:57` *"KISMİ SONUÇ — T-094'ün '48 başarılı, 2 başarısız' şartı… Önceden bu bilgi hiç ekrana gelmiyordu"*, `role="alert"` + başarısız listesi. **Geri alma şeridi VAR:** `MediaLibraryView.vue:628` `undoEntry` + `onUndo()` → `store.undo()`. `MediaFolderGrid`, `MediaCrumbs`, `MediaFilterRail`, `MediaFilterChips` var. **Ölçülmedi:** geri almanın **toplu silmeyi** grace period içinde kapsayıp kapsamadığı — `:1599` kalıcı silmenin *"geri alınamaz olduğu AÇIKÇA yazılır"* dediği ayrı bir yol | AJAN |
| **T-095** | Erişilebilirlik ve i18n doğrulaması | **axe-core taraması critical/serious bulgu üretmiyor**; tüm akış yalnız klavyeyle; `aria-live` duyuruları; TR/EN tam, **eksik anahtar CI'ı kırar**; AA kontrast | **KISMİ** | **`axe-core` ARTIK KURULU** (`devDependencies: "axe-core": "^4.13.0"`) — **ama hiçbir yerde kullanılmıyor**: `grep -rn "axe" src scripts` yalnız `VariantWizard.vue`'daki `axes` (varyant ekseni) değişkenini veriyor, `axe.run` 0 isabet. Yani **tarama hâlâ koşmuyor**; bağımlılık ölü duruyor. **Eksik anahtar kapısı VAR ve bugün ÇALIŞTI** (§0.2): 4 dilde SSR + `assertDoesNotMatch(/mediaSimulator\.[a-z]/i)` — 22:29'da kırmızıydı, 22:45'te yeşil. Elle yazılmış a11y testleri (`cropStudioA11y` 22, `simulatorA11y` 17) geçiyor, `aria-live` bağlı. **AA kontrast ölçülmedi** | ARAÇ |

---

## 3 · Faz 10 — Crop Studio

| ID | Başlık | Kaynağın kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-100** | Crop çekirdeği: paylaşılan geometri | TS ve Python **aynı test vektörlerinde aynı sonucu** veriyor; vektörler JSON'da, **iki tarafta da koşuluyor**; tolerans ≤ 0.5 px | **TAM** | §0.5. Python: `test_crop_geometry` **37/37 OK**, `[vektör] 584 vektör · en büyük sapma = 0.0 px`, `crop.py ↔ crop_geometry.py` çapraz sapma `1.8e-12 px`. Panel: `npm run parity:crop` **72/72, 0 atlama**, 592 vektörün tamamı türetilmiş `crop_geometry.js` üzerinden. Tolerans 0,5 px'e karşı ölçüm **0 px**. ⚠️ Not: Python'un node'u çağıran testi konteynerde **atlıyor** (node PATH'te yok) — ölçümü panel deposu yapıyor, ama **iki taraf da vektörleri gerçekten koşuyor** | — |
| **T-101** | Crop stage (tutamak, zoom, focal) | 8 tutamak + gövde + zoom + focal; oran kilidi taşmasız; **etkileşimde 60 fps**; klavyeyle piksel hassasiyeti; undo/redo; yüksek çözünürlük önizlemede küçültülür | **KISMİ** | `CropCanvas.vue`, `CropHandles.vue`, `cropHandles.js`, `useCropHistory.js`, `cropShortcuts.js` var ve `npm test`te geçiyor. **60 fps ölçülmedi** (7 ajan koşarken zamanlama ölçülmez). **Yeni ağırlaştırıcı bulgu:** T-105 ölçümü, sahnede gösterilen kutunun sunucunun keseceği kutudan **zoom kullanıldığında 119/120 vakada** ayrıştığını gösteriyor (§0.6) — yani tutamak/zoom doğru çalışıyor ama **sonucu kalıcılaşmıyor** | AJAN |
| **T-102** | Canlı çoklu önizleme (rendition kartları) | Tüm slot profilleri için kart, gerçek CSS ölçüsünde; değişimde **16 ms içinde** güncelleme, sunucu isteği yok; kartta profil/px/fit/yeterlilik; yetersiz kaynak uyarısı; profil override | **KISMİ** | `CropPreviewStrip.vue` (+ `IntersectionObserver` ile görünmeyeni çizmiyor, `:253`), `lib/media/crop/slotProfiles.js`, `vendor/slot_profiles.js` var; testleri `npm test` içinde geçiyor. **16 ms bütçesi ölçülmedi** — ölçüm için sessiz makine + tarayıcı gerekir | İNSAN |
| **T-103** | Otomatik odak önerisi + güvenli alan | **Öneri Web Worker'da**, ana iş parçacığı bloklanmaz; eşik altı güven gizlenir; "öneri" rozeti, onayda `method=manual`; güvenli alan çizilir | **KISMİ** | Öneri artık **sunucuda**: `api/media_crop.suggest_focal` canlı, `test_media_crop_intent::test_suggest_focal_on_real_image` **gerçek görselde** ölçüldü ve geçti (22:40–22:42); `CropStudioModal.vue:310` *"Sunucu önce"* diyor; `focusSuggest.js` yanıtı panel şekline çeviriyor ve bozuk yanıtta **güven uydurmuyor**. Güvenli alan `cropSafeArea.test.js` ile testli. **Kriterin yazdığı Web Worker YOK** (`grep -n "Worker" focusSuggest.js` → 0); sunucu çağrısı da ana iş parçacığını bloklamaz ama **kaynağın istediği çözüm bu değil**. Eşik/rozet/`method=manual` akışı ölçülmedi | AJAN |
| **T-104** | Politika uyarıları + crop intent kaydı | Canlı uyarılar; DPI/piksel açıklaması; **reject seviyesi ihlal yokken kaydetmeye izin**; kaydedilen intent JSON API şemasına uyar ve **`previewed_placements` içerir**; kayıt sonrası hangi rendition'ların yeniden üretileceği | **KISMİ** | **Rapor 35'in "kayıt tarafı YOK" hükmü düştü.** `useCropStudio.js:547` artık sabit değil, **computed**: `Boolean(asset) && usable && !blocked && payloadIssues.length === 0` — yani "reject ihlali yokken kaydet açık" kriteri **kodda gerçek**. Uç bağlı: `:558` `tradehub_core.api.media_crop.save_intent`. Sunucu tarafı 17/17 ölçüldü, idempotent. Uyarı tarafı (`cropPolicy.js`, `cropWarnings.js`, `CropPolicyNotice.vue`) geçiyor. **Eksik iki madde:** (a) `savePayload` **`previewed_placements` GÖNDERMİYOR** — o alanı yalnız `SimApprovalGate.vue:144` üretiyor ve o bileşen ekranda **mount edilmiyor** (T-114); (b) **hangi rendition'ların yeniden üretileceği hiç hesaplanmıyor** (§T-082) | AJAN |
| **T-105** | Faz 10 kapanış: crop doğruluk kabulü | **UI önizlemesi sunucu rendition'ıyla piksel düzeyinde eşleşiyor**; **20 gerçek görselde elle karşılaştırma** yapılmış ve raporlanmış; etkileşim performans hedefleri tutuyor | **KISMİ** | **Rapor 35'te YOK'tu; artık ölçüm VAR ama kabul GEÇMİYOR.** `cropPixelParity.test.js` 600 vakayı beş sınıfta koşuyor ve sapmaları **donduruyor** (§0.6): A 5/120 (1 px), **B 119/120 (7391 px)**, C 104/120 (3704 px), D 7/120 (1 px), **E 86/120 (3481 px)**. Tolerans 0,5 px; **üç sınıf bunu binlerce kat aşıyor ve 22:45 itibarıyla üçü de açık** — `savePayload`'da `zoom` yok (doğrulandı). **20 gerçek görsellik elle karşılaştırma raporu repoda bulunamadı.** Sunucunun ürettiği **görselin** pikselleri testin kendi beyanıyla **ölçülmüyor** | KARAR |

---

## 4 · Faz 11 — Simülatör (kaynağın numaraları)

| ID | Başlık | Kaynağın kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-110** | **Cihaz ve yerleşim kataloğunun veri olarak tanımı** (tek görev) | `devices.json` + `placements.json` var, yeni cihaz/sayfa kod değişmeden eklenebiliyor; **her yerleşim gerçek uygulamanın CSS breakpoint'leriyle doğrulanmış**; sapmada uygulama CSS'i kaynak | **KISMİ** | Veri iki tarafta: `media/pipeline/simulator/{devices,placements}.json` ve panelde `lib/media/simulator/vendor/`; sha256 zincirli senkron (`sync-simulator.mjs`, `vendor.manifest.json`) ve `srcsetParity.test.js` bu zinciri sınıyor. 13 cihaz + 15 yerleşim doğrulandı. **CSS doğrulaması hâlâ yapılmamış** — `MediaSimulatorView.vue` ekranın üstünde bunu **kendisi beyan ediyor**: `EMULE_DEGERLER_OLCULMEDI` ve `CSS_OKUNARAK_HESAPLANDI_TARAYICIDA_DOGRULANMADI`. Playwright repoda **yok** | ARAÇ |
| **T-111** | **Cihaz çerçevesi ve sayfa şablonu render motoru** | Her cihaz **gerçek CSS genişliğinde** render edilip **`transform: scale()`** ile sığdırılıyor (reflow yok); **ölçek yüzdesi gösteriliyor**; sayfa şablonları **gerçek grid mantığını taklit ediyor**; **13×5 = 65 kombinasyon hatasız render**; ilk boyama **< 1,5 sn** | **KISMİ** | **Rapor 35'te YOK'tu — motor yazıldı ve ölçüldü.** `SimDeviceFrame.vue`, `SimPageTemplate.vue`, `SimFrameGrid.vue`, `lib/media/simulator/frame.js` (13 KB) var; üçü de `MediaSimulatorView.vue:176/190/206`'da **mount edilmiş**. `frameRender.test.js` **ölçüyor**: "sahneyi cihazın GERÇEK CSS ölçüsünde kuruyor", "ölçek transform ile uygulanıyor", "**CSS `zoom` HİÇBİR YERDE kullanılmıyor**", "ölçek yüzdesi çerçevenin başlığında yazıyor" (`:95` `%{{scalePct}} · scale({{scale}})`), "şablon veri ile AYNI sütun sayısını çiziyor", "**5 sayfa × 13 cihaz = 65 çerçeve, sunucuda hatasız**", "**195 kombinasyonda `regionLayout().boxPx === boxWidth()` — sapma 0**", "çerçeve motoru kutu matematiğini kendi yazmıyor, `layout.js`'i çağırıyor". Tembel montaj `IntersectionObserver`'a bağlı ama gözlemci yoksa içerik gizlenmiyor. **Tek eksik: ilk boyama < 1,5 sn ölçülmedi** — testin kendi adı bunu söylüyor: *"ölçüm dürüstlüğü: süre iddiası yok, ÖLÇÜLMEDİ yazılı"*. Bu görev bir sessiz makinede tek ölçümle TAM'a çıkar | İNSAN |
| **T-112** | srcset seçim göstergesi + çözünürlük yeterlilik uyarısı | Her yerleşim için "tarayıcı hangi rendition'ı indirir"; kaynak yetersizse **kırmızı uyarı**; **tahmini indirilecek bayt**; **LCP elementi işaretleniyor** | **KISMİ** | Seçim hesabı ölçüldü: `test_simulator_srcset` **34/34 OK** (22:38:06), 65 kombinasyonda `kaynak_yetersiz=0 · asiri_servis=1 · zoom_yetersiz=6`, 1120 px kaynakla `kaynak_yetersiz=4`. Panel tarafında `srcsetParity.test.js` 65 + 195 kombinasyonda referansla **sapma 0**. LCP rozeti var (`layout.js` `lcpCandidate`, `SimResultCard` `lcpBadge`). **Bayt alanı ARTIK VAR** (`SimResultCard.vue:203` `bytesText`) — **ama tahmin üretmiyor:** *"Bayt TAHMİN EDİLMEZ… ekran bunun yerine 'türev üretilmedi, bayt bilinmiyor' der"*. Canlı `Media Rendition` = **0 satır** (§0.3) → bugün her satırda `bytesUnknown`. Kaynak "tahmini bayt" istiyor, uygulama **bilinçli olarak tahmin etmeyi reddediyor** | KARAR |
| **T-113** | Video slotu için poster/oynatma simülasyonu | Poster kadrajı **ve otomatik oynatma davranışı** (`muted`/`loop`, kontrol yerleşimi); **mobilde ilk 10 saniyede inecek tahmini bayt**; **`prefers-reduced-motion` ayrı önizleme**; kapak üstü UI **güvenli alan ihlali** uyarısı | **KISMİ** | **Rapor 35'in "dört maddenin üçü karşılanmıyor" hükmü düştü — dördü de kodda var (22:42'de yeniden yazıldı):** `SimPosterCard.vue:60-92` yüzey başına `autoplay/muted/loop`; `:109` `PREVIEW_STATES = ["poster","autoplay","reduced"]` → **`prefers-reduced-motion` ayrı önizleme durumu**; `:166` `firstWindowBytes` → **ilk 10 saniye baytı**; `:67` `zones` → kapağın üstüne binen ögeler ve `cover.zones[].pct` ile **örtme yüzdesi + güvenli alan hükmü**. `MediaVideo.vue:178` gerçek `matchMedia("(prefers-reduced-motion: reduce)")` da var. **Ölçülmedi:** bu dört maddenin doğruluğu — bileşen son ölçümden **3 dakika önce** yeniden yazıldı ve poster tarafına özel bir parite testi (`srcsetParity` 13 poster vektörü dışında) yok; bayt tahmini bit hızı girilmezse `null` | AJAN |
| **T-114** | Onay kapısı ve `previewed_placements` kaydı | Kullanıcı tüm yerleşim sınıflarını **görmeden onaylayamıyor**; görünürlük eşiği (≥1 sn, %50) ile izleme; uyarılı yerleşimde açık kabul; **kayıt sunucuda da doğrulanıyor**; **audit log** | **KISMİ** | **Rapor 35'te YOK'tu — istemci tarafı yazıldı.** `useSimulatorApproval.js` (`VISIBILITY_RATIO = 0.5`, `DWELL_MS = 1000`, `BLOCK_MISSING_PLACEMENT`, `BLOCK_UNACKNOWLEDGED_WARNING`), `SimApprovalGate.vue`, `approvalGate.test.js` (*"IntersectionObserver yoksa hiçbir yerleşim işaretlenmez"*, *"kapı kendiliğinden açılmamalı"*). Sunucuda alan **var** ve `save_intent` yazıyor. **Üç ölçülmüş eksik:** (1) `SimApprovalGate` **`MediaSimulatorView.vue`'da import edilmiyor** — ekranda yok (view 20:24, bileşen 22:43); (2) **sunucu doğrulamıyor** — `_validate_previewed_placements` yalnız "geçerli JSON mu" bakıyor, eksik cihaz sınıfı reddedilmiyor, `preview_gate_passed` alanı yok, `MEDIA_PREVIEW_REQUIRED` repoda 0 isabet; (3) **audit log yok**. Bileşenin kendi metni de bunu yazıyor: *"Bu kapı bugün YALNIZ istemcide duruyor"*. `Media Placement Preview` DocType'ı **kurulu değil** | AJAN |
| **T-115** | Simülatörün gerçek sayfayla doğrulanması (drift testi) | Her cihaz için **gerçek sayfa ile simülatör önizlemesi otomatik karşılaştırılıyor**; kutu ölçüsünde **2 px üzeri sapma CI'da kırmızı**; sapma raporunda sebep CSS değişikliği; **test günlük çalışıyor** | **YOK** | Böyle bir test hâlâ yok. `grep -rniE "playwright" src scripts package.json` → **0 isabet**. `frameRender.test.js`'teki `drift` sayacı **panelin kendi iki hesabını** karşılaştırır (`regionLayout().boxPx` ↔ `boxWidth()`), gerçek sayfayı değil. `srcsetParity.test.js` paneli **Python referansıyla** karşılaştırır. `SimResultCard.vue:178` bunu kendi kabul ediyor: *"kutusunun taşıp taşmadığı tarayıcıda ÖLÇÜLMEDİ (T-115 drift testi)"*. 2 px CI kapısı yok, günlük koşum yok, sapma-sebep raporu yok | ARAÇ |

---

## 5 · Sayım

| Faz | Görev | TAM | KISMİ | YOK |
|---|---:|---:|---:|---:|
| **Faz 8** — API | 6 | 0 | **6** | 0 |
| **Faz 9** — Medya kütüphanesi | 6 | 0 | **6** | 0 |
| **Faz 10** — Crop Studio | 6 | **1** (T-100) | **5** | 0 |
| **Faz 11** — Simülatör | 6 | 0 | **5** | **1** (T-115) |
| **Toplam** | **24** | **1** | **22** | **1** |

### Engelleyen dağılımı

| Engelleyen | Adet | Görevler |
|---|---:|---|
| **AJAN** | **9** | T-082, T-092, T-093, T-094, T-101, T-103, T-104, T-113, T-114 |
| **ARAÇ** | **8** | T-080, T-081, T-084, T-085, T-091, T-095, T-110, T-115 |
| **KARAR** | **4** | T-083, T-090, T-105, T-112 |
| **İNSAN** | **2** | T-102, T-111 |
| **—** | **1** | T-100 |

### Rapor 35 (bu sabah) ↔ bu rapor (22:47)

| | TAM | KISMİ | YOK |
|---|---:|---:|---:|
| `35-dogrulama-faz8-11.md` | 1 | 17 | **6** |
| **Bu rapor** | 1 | 22 | **1** |

**Kazanım TAM'da değil, YOK'ta: 6 → 1.** Gün içinde YOK'tan çıkan beş görev: **T-081** (parçalı
yükleyici + preflight), **T-091** (Web Worker preflight + devam), **T-105** (piksel paritesi ilk kez
ölçüldü), **T-111** (render motoru), **T-114** (istemci onay kapısı). TAM sayısı değişmedi çünkü bu
beşinin hiçbiri kaynağın **bütün** kabul maddelerini karşılamıyor; ayrıca **T-083 TAM'dan KISMİ'ye
düştü** — rapor 35 ETag'i "ölçülmedi" diye dışarıda bırakmıştı, bu rapor ölçtü ve **304 üretilmediğini**
buldu.

---

## 6 · Kapanışı engelleyen dört madde (ölçülmüş, sıralı)

1. **T-105'in üç ayrışması açık — ve ikisi ürün kararı istiyor.** Zoom (7391 px) kapatılabilir:
   `savePayload`'a zoom eklenip sunucunun zinciri o kutudan kurulmalı. Override oranı (3704 px) ve taban
   bölge (3481 px) ise "panel kullanıcının çizdiğini mi, sunucunun keseceğini mi gösterecek" sorusudur —
   bu bir **KARAR**, kod değil. Brief'in "C5 zoom'u kapattı" bilgisi **çalışma ağacında doğrulanmadı**.

2. **`previewed_placements` zinciri üç yerde kopuk.** Alan var (DocType), uç yazıyor (`save_intent`),
   üreten kod var (`SimApprovalGate`) — ama (a) bileşen ekrana **bağlanmamış**, (b) `useCropStudio`'nun
   kendi yükü bu alanı **taşımıyor**, (c) sunucu gövdeyi **doğrulamıyor**. Üçü kapanmadan T-104 ve T-114
   TAM olamaz. Tek tek küçük işler; hepsi **AJAN**.

3. **`overrides` yolu düzeltilmiş ama kimse ölçmüyor.** DocType 22:14'te `Link`→`Data` çevrildi ve canlı
   DB'de doğrulandı; buna karşılık `openapi-http.yaml`'ın `x-mismatch` metni, `useSimulatorApproval.js`'in
   `overrides` yasağı ve `doctype_specs/media_crop_override.json` **hâlâ eski gerçeği anlatıyor**.
   `test_media_crop_intent`'te `overrides` geçmiyor. **Düzeltmeyi kilitleyen bir test yazılmadan bu yol
   yarın sessizce geri kırılabilir.**

4. **İki bağımlılık kurulu ama ölü, iki kapı kurulu ama sessiz.** `axe-core` `devDependencies`'te fakat
   `axe.run` 0 isabet (T-095). `chunked.cleanup()` yazılı fakat `scheduler_events`'te yok (T-081).
   Konteynerde `node` PATH'te olmadığı için Python'un TS parite testi **atlıyor** (T-100 — panel tarafı
   ölçtüğü için not düşmez, ama kapı sessizdir). `test_http_api_contracts`'ın 6 yetkili testi
   `ISTOC_HTTP_USER`/`PASS` veren bir CI olmadığı için **atlanıyor** (T-084).

---

## 7 · Ölçülmedi (dürüstlük listesi)

Bu raporda **hiçbir geçti/kaldı hükmü olmayan** maddeler:

- **Bütün zamanlama hedefleri** — 60 fps (T-101), 16 ms (T-102), ilk boyama < 1,5 sn (T-111),
  50 dosyada akıcılık (T-091), 10.000 varlıkta kaydırma (T-092). 7 ajan koşarken kasten ölçülmedi.
- **`overrides` yolunun uçtan uca çalışması** (§0.4) — yazma gerektirir, bu görev salt okumadır.
- **T-113'ün dört maddesinin doğruluğu** — bileşen son ölçümden 3 dakika önce yeniden yazıldı.
- **T-093'ün kalite raporu ve SSIM'i gerçek veriyle** — canlı DB'de 0 rendition var.
- **Toplu silmenin grace period içinde geri alınabilirliği** (T-094).
- **AA kontrast oranları**, **axe critical/serious bulgusu** (tarama hiç koşmuyor).
- **`devices.json`/`placements.json` değerlerinin gerçek CSS'e uygunluğu** — ekranın kendisi
  `CSS_OKUNARAK_HESAPLANDI_TARAYICIDA_DOGRULANMADI` diye beyan ediyor.
- **Sunucunun ürettiği görselin pikselleri** — `cropPixelParity` kutuyu karşılaştırır, görüntüyü değil.

**Yan etki:** hiçbir kaynak dosya değiştirilmedi, bayrak açılmadı, `bench migrate` koşulmadı, DocType
kurulmadı, DB'ye yazılmadı. Tek yazma: `ISTOC_HTTP_USER=Administrator` ile alınan **okuma-yalnız**
oturum (test sınıfının kendi beyanı: *"Yalnız OKUYAN uçlar çağrılır. Yazan uçlar bu testte YOK"*).
Geçici dosya bırakılmadı. Yalnız bu rapor yazıldı.
