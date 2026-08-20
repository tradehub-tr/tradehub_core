# 49 — T-111 cihaz çerçevesi ve sayfa şablonu render motoru

**Tarih:** 2026-08-19
**Depo / dal:** `admin-panel` / `ahmet`
**Kapsam:** T-111 (asıl iş) · T-110 (numara hizalaması)
**Kaynak kabul ölçütü:** `tradehub_core/docs/ui/faz11-simulator.md` §2
**Kaynak görev tanımı:** `https://karacaismail.github.io/imageoptimization/docs/62-faz11-simulator.html`

---

## 0. Bir cümlede

Simülatör 65 kombinasyonu **tabloda basıyordu**; artık **çiziyor**: cihazın
gerçek CSS genişliğinde kurulan, `transform: scale()` ile küçültülen, ölçek
yüzdesi görünen, `placements.json`'daki ızgara kuralını birebir taklit eden 65
cihaz çerçevesi. Seçim hesabına **tek satır dokunulmadı** — parite 65 ve 195
kombinasyonda 0 sapmada duruyor, 15 `sizes` dizgesi karakterine aynı.

---

## 1. Başlangıç durumu — ölçülen eksikler

Görev başında dört maddenin dördü de yoktu; kaynakta tek tek arandı:

| Kabul ölçütü maddesi | Başlangıç | Kanıt |
|---|---|---|
| Cihaz çerçevesi bileşeni | **YOK** | `components/media/simulator/` altında 4 dosya vardı: `SimOptionGroup`, `SimResultCard`, `SimMatrixTable`, `SimPosterCard` — hiçbiri çerçeve değil |
| `transform: scale()` | **YOK** | `grep -r "transform.*scale" src/components/media/simulator/` → eşleşme yok |
| Sayfa şablonu / grid taklidi | **YOK** | Sütun sayısı hiçbir yerde çizilmiyordu; `cols` yalnız kutu genişliği hesabında kullanılıyordu (`layout.js::boxWidth`) |
| Ölçek yüzdesi | **YOK** | — |

`MediaSimulatorView.vue`'nun kendi docstring'i de motoru değil **seçimi**
tarif ediyordu ("Sorduğu soru: bu cihaz … hangi türevi indirir"). Docstring
düzeltildi ve artık iki soruyu da yazıyor.

---

## 2. Ne yazıldı

### 2.1 Hesap çekirdeği — `src/lib/media/simulator/frame.js` (YENİ)

Saf modül, DOM'a hiç dokunmaz; çizim için gereken geometriyi üretir.

| Dışa açılan | İşi |
|---|---|
| `frameScale(cssWidth, availableWidth)` | Ölçek + **yüzde**. `MIN_SCALE`=0,05 tabanı, `MAX_SCALE`=1 tavanı |
| `deviceFrame(device, availableWidth)` | Çerçeve geometrisi: `cssWidth/cssHeight` (ölçekten **bağımsız**) + `scale`, `scalePct`, `renderedWidth/Height` |
| `frameStyle(frame)` | İki inline stil dizgesi: sahne (`width:390px;…;transform:scale(0.77);transform-origin:top left`) ve kabuk (ölçeklenmiş ölçü) |
| `containerParts(name, viewportPx)` | Kapsayıcı zincirinin **çizilebilir** parçaları: `marginPx`, `paddingPx`, `subtractPx`, `contentPx` |
| `regionLayout(region, device)` | Bir bölgenin çizilebilir yerleşimi: `kind`, `cols`/`perView`, `gapPx`, `reservePx`, `trackPx`, `bandMinVw`, `overflows`, `tile` ve **`boxPx`** |
| `pageTemplate(page, device, activeKey)` | Sayfanın tüm bölgelerinin blok listesi + `desktopLayout` (layout switch hangi kolda) |
| `slotAspect(slotKey)` | Karo yüksekliği için oran — profil `ratioLabel`'ından, uydurma yok |

**Kritik nokta — hesap değişmedi.** `regionLayout().boxPx` alanı
`layout.js::boxWidth()`'in döndürdüğü değerin **aynısıdır**; frame.js kutu
aritmetiğini yeniden yazmaz, çağırır. `layout.js`'e yalnız tek bir ekleme
yapıldı: `matchingStep()` artık `export` (davranış değişmedi) — çerçevenin
"hangi bant kazandı" bilgisini **ikinci bir eşleştirme yazmadan** okuyabilmesi
için. İkinci bir eşleştirme yazılsaydı, ekranda yazan bant ile kutu genişliği
sessizce ayrışabilirdi.

### 2.2 Bileşenler (YENİ)

| Dosya | İşi |
|---|---|
| `components/media/simulator/SimDeviceFrame.vue` | Cihaz çerçevesi: başlık şeridi (cihaz adı · `390×844` · `DPR 3` · `%77 · scale(0.77)`) + kabuk + sahne. Tembel montaj (`IntersectionObserver`) |
| `components/media/simulator/SimPageTemplate.vue` | Sayfa şablonu: bölge başına bir şerit, gerçek kapsayıcı kenar boşluğu, gerçek sütun sayısı, gerçek `gap`, rezerve sütunlar, taşma rozeti |
| `components/media/simulator/SimFrameGrid.vue` | 5 sayfa × 13 cihaz = **65 çerçeve**, sayfa başına bir şerit |
| `components/media/simulator/__tests__/frameRender.test.js` | 21 test — motorun gerçekten render ettiğinin kanıtı |

`MediaSimulatorView.vue` bunları bağladı: seçili cihazın çerçevesi sonuç
kartının **üstünde** (önce "nerede", sonra "hangi türev"), 65 çerçevelik matris
sayısal tablonun **üstünde**. Çerçevenin ölçeği `ResizeObserver` ile ölçülen
gerçek kap genişliğinden çıkar.

### 2.3 Reflow yasağına nasıl uyuldu

Kaynak §2 açıkça yazıyor: `width: 390px` + `transform: scale(0.6)`; CSS `zoom`
ya da kapsayıcıyı daraltmak **yanlıştır** — ikisi de düzeni yeniden hesaplatır
ve 390px'lik cihazın gerçek kırılımı yerine 234px'lik sahte bir kırılım simüle
edilir.

Uygulama:

* sahne **her zaman** `width:{cssWidth}px; height:{cssHeight}px` alır, ölçek
  ayrı bir alan olarak `transform`'a gider;
* `transform` yer kaplamayı değiştirmediği için **kabuk** ölçeklenmiş ölçüyü
  elle taşır (`renderedWidth × renderedHeight`), yoksa çerçeve ölçeklenmemiş
  boyu kadar yer isterdi;
* `transform-origin: top left` **fiziksel** olduğu için sahnenin konumu da
  fiziksel (`top:0; left:0`) — mantıksal `inset-inline-start` ile karıştırmak
  Arapça arayüzde sahneyi çerçevenin dışına kaydırırdı;
* CSS `zoom` üç dosyanın hiçbirinde yok ve bu **testle sabitlendi**.

### 2.4 Sayfa şablonu ne taklit ediyor, ne etmiyor

**Taklit ediyor (hepsi `placements.json`'dan):** kapsayıcı `max-width`,
ortalama, padding, sütun sayısı, sütun arası, `slider` `per_view`/`space`,
sabit px kutular, rezerve sütunlar, kazanan kırılım bandı, LCP adaylığı.

**Taklit ETMİYOR — bilerek:** bölgelerin sayfadaki **dikey konumu** ve
yüksekliği. Veride yok; sahte bir site başlığı ya da "hero 480px" varsayımı
çizmek ölçülmemiş bir şeyi ölçülmüş gibi göstermek olurdu. Bölgeler
`placements.json` sırasıyla, eşit aralıkla, kendi şeritlerinde duruyor.

**Rezerve sütunun yeri bir çizim varsayımıdır.** `grid.subtract_px` veride
yalnız bir px sayısı; listelemede 240–256px'lik filtre kolonu (grid'den
**önce**, `hidden lg:block`), mağaza vitrininde ise kartın kendi iç boşluğu
(`p-4 xl:p-6`, iki yana bölünür). Veri ikisini ayırmıyor, şablon hepsini başta
tek taralı şerit olarak çiziyor ve px değerini üstüne yazıyor. Kapsayıcının
`subtract` adımı (PDP sağ rayı) `derived_from`'da açıkça "sağ ray" dediği için
sonda çiziliyor.

### 2.5 Render motorunun ortaya çıkardığı bir şey

`product_detail/lightbox_main` kutusunu **yükseklikten** alıyor
(`82vh`, tavan 720, −84). iPhone 14'te (844px yükseklik) sonuç **608px** —
390px'lik viewport'tan geniş. Tablo bunu göstermiyordu, çünkü tabloda kutu tek
bir sayı. Çerçeve bunu kırpıyor **ve rozetliyor** (`608 > 390px`). Bu bir hata
raporu değil, verinin kendi gerçeği; sessizce sığdırmak yalan olurdu.

---

## 3. Ölçümler

Hepsi bu makinede koşturuldu; koşturulmayan hiçbir şeye "geçti" denmedi.

### 3.1 Parite — BOZULMADI

```
node --test src/lib/media/simulator/__tests__/srcsetParity.test.js
✔ cihaz ve bölge kümeleri referans uygulamayla birebir
✔ profil merdiveni politikadan aynı çıkıyor (FR-028 kelepçesi dahil)
✔ 65 birincil kombinasyonun tamamı panelin kapısından referansla aynı
✔ 65 kombinasyonun özeti ölçülen değerlerle aynı
✔ 15 bölgenin tamamında (195 kombinasyon) da sapma yok
✔ 15 bölgenin `sizes` dizgesi karakteri karakterine aynı
✔ `srcset` dizgesi referansla aynı
✔ 13 cihazın poster seçimi referansla aynı
… 13 test, 13 pass, 0 fail
```

**Ölçülen sapma: 0** — 65'te de, 195'te de. 15 `sizes` dizgesi karakterine
aynı. `num()`'un altı anlamlı haneye hizalanması (`4.8` ≠ `4.799999999999999`)
**hiç ellenmedi**.

Ayrıca yeni test dosyası paritenin ikinci bir yönünü ölçüyor:

```
✔ 195 kombinasyonda regionLayout().boxPx === boxWidth() — sapma 0
✔ containerParts() kapsayıcı genişliğini containerWidth() ile aynı çözüyor (65 kontrol)
✔ çerçeve motoru kutu matematiğini kendi yazmıyor, layout.js'i çağırıyor
```

Sonuncusu, render motoruna seçim aritmetiğinin (`requiredPx`, `selectRendition`,
`dpr *`) sızmadığını kaynak üzerinden doğruluyor.

### 3.2 Render motoru gerçekten render ediyor mu — 21 test

`src/components/media/simulator/__tests__/frameRender.test.js`, sunucu tarafı
render (SSR) çıktısına bakıyor. "Yazdım" demek yetmiyor, çıktıda görünmesi
gerekiyor:

| Ne ölçüldü | Sonuç |
|---|---|
| Sahne cihazın **gerçek** CSS ölçüsünde kuruluyor mu | ✅ `width:390px`, `height:844px` çıktıda |
| Kabuk ölçeklenmiş ölçüyü taşıyor mu | ✅ `width:300px` (390 × 0,769) |
| `transform: scale()` uygulanıyor mu | ✅ `transform:scale(0.76923…)` + `transform-origin:top left` |
| CSS `zoom` kullanılmış mı | ✅ üç dosyanın hiçbirinde yok |
| Ölçek cihazın CSS genişliğini değiştiriyor mu | ✅ hayır — 200px ve 380px kapta `cssWidth` ikisinde de 390 |
| Ölçek yüzdesi görünüyor mu | ✅ `%77 · scale(0.77)` + `390×844` + `DPR 3` |
| Ölçek 1'i aşıyor mu / tabana kelepçeleniyor mu | ✅ tavan 1, taban `MIN_SCALE`, ölçülemeyen kapta çerçeve yok olmuyor |
| Şablon veriyle **aynı** sütun sayısını çiziyor mu | ✅ 1920px'te 7 karo (min_vw 1536 adımı), telefonda 2 |
| Karolar kutunun gerçek px genişliğinde mi | ✅ `boxWidth()` değeri çıktıda `width:{box}px` |
| Rezerve sütun (filtre kolonu 280px) çiziliyor mu | ✅ `simpage__reserve` + `width:280px` |
| Kapsayıcının sağ rayı (PDP, 410px) çiziliyor mu | ✅ `simpage__rail` |
| Taşan bölge sessizce sığdırılıyor mu | ✅ hayır — `simpage__over` rozeti |
| **65 çerçeve** hatasız render oluyor mu | ✅ 65 çerçeve, **195 bölge şeridi**, çıktıda `NaN`/`undefinedpx` yok |
| 65 kombinasyonda ölçek + şablon üretiliyor mu | ✅ 65/65, her blokta sonlu `boxPx`, `count ≥ 1`, sonlu karo yüksekliği |
| Ekran motoru gerçekten kullanıyor mu | ✅ `<SimDeviceFrame>` + `<SimFrameGrid>` + `:available-width="stageWidth"` |
| Tembel montaj gözlemci yoksa içeriği gizliyor mu | ✅ hayır — gözlemci yoksa doğrudan kuruluyor; gözlemci `onBeforeUnmount`'ta sökülüyor |

### 3.3 Bitirme koşulları

| Koşul | Komut | Sonuç |
|---|---|---|
| Lint | `npm run lint` | **EXIT 0** — 0 hata, 2 uyarı. İkisi de `views/permission/PlansTab.vue` (dokunulmadı, önceden vardı). Simülatör dosyalarında 0 uyarı |
| Build | `npm run build` | **EXIT 0** — `MediaSimulatorView-*.js` 52,04 kB (gzip 17,82 kB), `MediaSimulatorView-*.css` 23,08 kB (gzip 3,36 kB) |
| Test | `npm test` | **EXIT 0 — 571 test, 571 pass, 0 fail** |
| Parite | `node --test …/srcsetParity.test.js` | **13/13**, 65 ve 195 kombinasyonda **0 sapma** |

> **Test sayısı notu.** Görev tanımında "bugün 396/396" yazıyordu; koşum
> sırasında sayı 396 → 464 → 503 → 571'e çıktı. Sebep: aynı depoda paralel
> çalışan diğer panel ajanları test ekliyor. 21'i bu görevin. Ara koşumlarda
> iki geçici kırmızı görüldü (`cropStudio.test.js` içinde iki test) — tek
> başına koşturulunca 41/41 geçtiler; başka bir ajanın dosyayı yazarken
> yakalanmasıydı. Son tam koşumda 0 fail.

---

## 4. T-110 — numara hizalaması

Kaynak dokümanda **T-110 tek görevdir**: *"Cihaz **ve yerleşim** kataloğunun
veri olarak tanımı."* İç kayıt bunu bir ara "cihaz kataloğu" ve "yerleşim
kataloğu" diye ikiye bölmüştü (`docs/reports/31-gorev-numara-hizalama.md`
§ tablo). Panelde kaynağın numarası kullanılacak şekilde üç yer düzeltildi:

| Dosya | Önce | Sonra |
|---|---|---|
| `scripts/sync-simulator.mjs` → `manifest.gorev` | `T-113…T-115` | `T-110…T-115` + gerekçe yorumu |
| `scripts/gen_simulator_vectors.py` → `doc["gorev"]` | `T-113…T-115` | `T-110…T-115` + gerekçe yorumu |
| `src/lib/media/simulator/layout.js` docstring | numara yok | T-110'un tek görev olduğu ve iç kaydın bölmüş olduğu yazılı |

Vendor'lanan `devices.json` / `simulator_data.js` içindeki `"generated_for":
"Faz 11 / T-110"` zaten kaynağın numarasını taşıyordu; bunlar bayt kopyası
oldukları için elle düzenlenmedi.

`npm run sync:simulator` yeniden koşturuldu: **parite vektörleri
bayt-aynı çıktı** (yalnız `gorev` metadata alanı ve manifest hash'i değişti).

---

## 5. Yan bulgu — vendor manifesti bayatlamıştı

Göreve başlarken `npm test` **395/396** veriyordu; tek kırmızı:

```
✖ manifest canlı tradehub_core kaynağıyla uyuşuyor
  kaynak değişmiş, `npm run sync:simulator` gerekli:
  tradehub_core/media/pipeline/policy/video_decision.json
```

Sebep bu görev değil: `tradehub_core`'da başka bir ajan `video_decision.json`'a
capped-CRF / fallback-REMUX / quality_gate blokları eklemişti (commit
edilmemiş, `git status` → ` M`). Simülatörün türettiği **`poster` bloğu
birebir aynı** kaldı (`json` karşılaştırması ile doğrulandı), yani parite
verisi etkilenmemişti — bayatlayan yalnız hash'ti.

`npm run sync:simulator` ile manifest tazelendi ve test yeşile döndü.
**Uyarı:** `tradehub_core`'daki değişiklik hâlâ commit edilmemiş; o dosya
tekrar düzenlenirse manifest yine bayatlar ve aynı test kırmızıya döner.
Çözümü yine tek komut: `npm run sync:simulator`.

---

## 6. ÖLÇÜLMEDİ — bu görevde yapılmayanlar

Kaynak §2'nin bir maddesi ölçüm gerektiriyor ve **karşılanmadı**:

* **"Cihaz matrisi modunda ilk boyama < 1,5 sn."** Tarayıcıda ölçüm
  YAPILMADI; imaj kurulmadı, sayfa açılmadı. Kaynak planın önerdiği tembel
  montaj (`IntersectionObserver` + aynı ölçüde yer tutucu) **uygulandı**, ama
  kaç ms kazandırdığı ve hedefin tutup tutmadığı **bilinmiyor**. Süre ya da
  FPS iddiası bu raporda YOK.
* **Ölçeklenmiş sahnenin gerçek piksel görünümü** — SSR çıktısındaki stil
  dizgeleri ölçüldü, tarayıcıda boyanmış hâli görülmedi.
* **`placements.json` değerlerinin gerçek sayfayla uyumu** — T-115'in ve
  T-110'un eksik kalan Playwright kabul ölçütünün işi; koşulmadı. Ekran bunu
  zaten üstünde beyan ediyor (`DEVICE_MEASUREMENT` / `PLACEMENT_MEASUREMENT`).
* **Karo en-boy oranı** bir çizim varsayımıdır: `product.image` profillerinin
  `height`'i `null` (politika o slotu kırpmıyor), oran `ratioLabel: "1:1"`
  etiketinden alınıyor. Seçim hesabına hiç girmiyor.
* **Rezerve sütunun hangi tarafta durduğu** (§2.4) veriden çıkmıyor, çizim
  varsayımı.

---

## 7. Dokunulan dosyalar

**Yeni**

* `admin-panel/frontend/src/lib/media/simulator/frame.js`
* `admin-panel/frontend/src/components/media/simulator/SimDeviceFrame.vue`
* `admin-panel/frontend/src/components/media/simulator/SimPageTemplate.vue`
* `admin-panel/frontend/src/components/media/simulator/SimFrameGrid.vue`
* `admin-panel/frontend/src/components/media/simulator/__tests__/frameRender.test.js`

**Değiştirilen**

* `admin-panel/frontend/src/lib/media/simulator/index.js` — frame.js dışa aktarımları
* `admin-panel/frontend/src/lib/media/simulator/layout.js` — `matchingStep` export + T-110 notu (davranış değişmedi)
* `admin-panel/frontend/src/views/system/MediaSimulatorView.vue` — çerçeve + çerçeve matrisi bağlandı, docstring motoru anlatıyor
* `admin-panel/frontend/scripts/sync-simulator.mjs` — görev numarası
* `admin-panel/frontend/scripts/gen_simulator_vectors.py` — görev numarası
* `admin-panel/frontend/src/lib/media/simulator/vendor/*` — `npm run sync:simulator` çıktısı

**Dokunulmayan (yasak alanlar):** `router/index.js`, `data/navigation.js`,
`i18n/locales/*.js`, `components/media/crop/**`, `components/media/upload/**`,
`lib/media/crop/**`, `MediaLibraryView.vue`, `MediaDetailPanel.vue`,
`MediaExplorerView.vue`, `SimResultCard.vue`, `SimPosterCard.vue`,
`tradehub_core/` (bu rapor hariç), `docker/`.

> **i18n notu.** `i18n/locales/*.js` yasak alanda olduğu için render motoru
> **tek bir yeni çeviri anahtarı eklemedi**. Çerçevenin bastığı her metin ya
> veriden gelir (cihaz adı, sayfa/bölge başlığı — matris tablosunun zaten
> kullandığı kaynak) ya da dilden bağımsız gösterimdir (`390×844`, `DPR 3`,
> `%77 · scale(0.77)`, `≥1024px`, `280px`, `LCP`, `7×`). Dört dilin anahtar
> eşitliğini denetleyen mevcut test bozulmadı.
