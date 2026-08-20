# 51 — T-112 · T-113 · T-114 · Simülatör kartları ve onay kapısı

**Tarih:** 2026-08-19
**Depo:** `admin-panel/frontend` · dal `ahmet`
**Kaynak kabul ölçütleri:** `docs/ui/faz11-simulator.md` §1.4, §3, §4 ve
`https://karacaismail.github.io/imageoptimization/docs/62-faz11-simulator.html` (T-112/113/114)

> **Ölçüm uyarısı.** Bu görevde **tarayıcı doğrulaması YAPILMADI**. Süre, FPS,
> ilk boyama ve gerçek yerleşim iddiası YOK. Aşağıda "ölçüldü" yazan her şey
> Node koşucusunda (SSR çıktısı + saf hesap) ölçülmüştür.

---

## 0. Kapılar — koşturuldu

| Kapı | Komut | Sonuç |
|---|---|---|
| Testler | `npm test` | **609 / 609 geçti** (taban 571 + bu görevin 38 testi), `fail 0` |
| Parite | `node --test "src/lib/media/simulator/__tests__/*.test.js"` | **13 / 13** — 65 ve 195 kombinasyonda **0 sapma**, 15 `sizes` dizgesi **karakterine aynı**, 13 poster vektörü aynı |
| Lint | `npm run lint` | **EXIT 0** (2 uyarı var, ikisi de `views/permission/PlansTab.vue` — bu görevden ÖNCE oradaydı, yeni uyarı yok) |
| Build | `npm run build` | **EXIT 0** |

---

## 1. Dosyalar

| Dosya | Durum | Satır |
|---|---|---|
| `src/components/media/simulator/SimResultCard.vue` | genişletildi (T-112) | 585 |
| `src/components/media/simulator/SimPosterCard.vue` | genişletildi (T-113) | 727 |
| `src/components/media/simulator/SimApprovalGate.vue` | **yeni** (T-114) | 512 |
| `src/composables/useSimulatorApproval.js` | **yeni** (T-114) | 324 |
| `src/components/media/simulator/__tests__/simulatorCards.test.js` | **yeni** (18 test) | 246 |
| `src/components/media/simulator/__tests__/approvalGate.test.js` | **yeni** (20 test) | 256 |

Dokunulmayanlar: `router/index.js`, `data/navigation.js`, `i18n/locales/*.js`,
`SimDeviceFrame.vue`, `SimPageTemplate.vue`, `SimFrameGrid.vue`,
`MediaSimulatorView.vue`, `lib/media/simulator/**`, `components/media/crop/**`,
`components/media/upload/**`, `package.json`, `tradehub_core` kodu, `docker/`.

---

## 2. T-112 — srcset seçim göstergesi ve çözünürlük yeterlilik uyarısı

Kabul ölçütü dört madde; üçü karşılandı, biri **kısmen** (gerekçesi ölçüldü).

### 2.1 Yeterlilik hükmü — ✅

Uyarı listesinin ÜSTÜNE tek cümlelik bir hüküm kondu; ton üçe ayrıldı ve
ikisi karıştırılmıyor:

| Durum | Ton | Metin |
|---|---|---|
| `chosen.width >= requiredPx` | yeşil | "Seçilen basamak yetiyor…" |
| `chosen.width < requiredPx` | **kırmızı** | "**Kaynak yetersiz — büyütme yapılmaz.** … Yakınlaştırmayı azaltın ya da daha yüksek çözünürlüklü bir görsel yükleyin." |
| kutuya yetiyor ama zoom'da yetmiyor | sarı | "{m}× yakınlaştırmada yetmiyor…" |
| profil yok | kırmızı | "Bu slotta profil tanımlı değil" |

Hüküm ikinci bir kural yazmaz: `selection.sufficient` / `zoomSufficient`
`lib/media/simulator/select.js`'ten gelir ve parite testinde `srcset.py` ile
karşılaştırılır. Test: `simulatorCards.test.js` — kırmızı vaka p50 kaynakla
(1120 px) `iphone-14 × product_detail/main_image`, **ölçüldü**: `deficit 50 px`.

### 2.2 LCP işaretlemesi — ✅

`region.lcpCandidate` (yani `placements.json::lcp_candidate`) doğruysa başlıkta
rozet, altında not: *lazy-load EDİLMEMELİ, `loading="eager"` + `fetchpriority="high"`*.
LCP olmayan bölgede rozet basılmıyor (test var). Ayrı bir LCP listesi
TUTULMADI — bayrak zaten veride.

### 2.3 Kutu > viewport uyarısı — ✅ (C6'nın bulgusu)

C6'nın bulduğu vaka ekrana taşındı: `product_detail/lightbox_main` `vh_pct`
kuralıyla hesaplandığı için kutu viewport **genişliğini** aşabiliyor.
**Ölçüldü:** `iphone-14` → kutu **608,08 px**, viewport **390 px**, taşma
**218 px (1,56×)**. Kart bunu ayrı bir satırda yazıyor ve sebebini söylüyor:
*gereken piksel TAM kutudan hesaplanıyor, ekranda hiç görünmeyecek bir genişlik
için basamak seçiliyor olabilir.* Sığan kombinasyonda satır basılmıyor (test var).

> Bu bir **sapma işaretidir, düzeltme değil**. Gerçek storefront kutusunun
> taşıp taşmadığı tarayıcıda **ÖLÇÜLMEDİ** — T-115 drift testinin işi.

### 2.4 "Tahmini indirilecek bayt" — ⚠️ KISMİ, bilinçli

Kabul ölçütü *"gerçek rendition boyutlarından"* diyor. Kart baytı **yalnız**
`Media Rendition.bytes` alanından okur (`useSrcsetSimulator.probe()` o alanı
zaten çekiyordu, kullanılmıyordu). Tablo bugün **boş** (boru hattı bayrakları
kapalı), o yüzden ekranda "Bilinmiyor — türev henüz üretilmedi" yazıyor.

**Bayt TAHMİN EDİLMEDİ.** `genişlik² × sabit` gibi bir formül yazmak,
ölçülmemiş bir sayıyı ölçülmüş gibi göstermek olurdu. Testler ikisini de
kilitliyor: satır varken bayt basılıyor, yokken hiçbir `NN,N KB` dizgesi
çıkmıyor.

**Aynı sebeple yapılmayan:** kaynak dokümandaki *"sayfa toplamı: bu cihazda bu
sayfada indirilecek tahmini görsel baytı; standarttaki bütçeyi aşıyorsa uyarı"*
maddesi. İki girdisi de yok — türev baytları yok, `docs/standards` içinde
panele vendor'lanmış bir sayfa bayt bütçesi yok. **YAPILMADI**, uydurulmadı.

---

## 3. T-113 — video slotu için poster/oynatma simülasyonu

### 3.1 Yüzey verisi kaynaktan OKUNDU (ölçülmedi)

`placements.json` video için bir bölge ölçmemiş (spec §3 "ön koşul"). Bu
görevde `tradehub_core`'a yazılamadığı için iki yüzeyin künyesi **panelde**
duruyor, her alanın yanında `dosya:satır` referansıyla:

| Yüzey | Kaynak | autoplay | muted | loop | playsinline | `poster` | preload | controls |
|---|---|---|---|---|---|---|---|---|
| Satıcı kapak videosu (`company.cover_video`) | `tradehubfront/src/components/seller/StoreHeader.ts:297-345` | **YOK** | var | YOK | var | var | metadata | özel (uygulama çizer) |
| Ürün tanıtım videosu (`product.video`) | `tradehubfront/src/components/product/ProductVideoSection.ts:63,81` | YOK (yalnız `autoplay=true` çağrısında) | YOK | YOK | var | **YOK** | metadata | yerel |

**İki gerçek bulgu:**

- **B4 — Satıcı kapak videosu otomatik OYNAMIYOR.** `StoreHeader.ts:308`
  `playsinline preload="metadata" muted` yazıyor, `autoplay` **yok**. Yani
  kaynak dokümandaki "(b) otomatik oynatma" ve "(c) `prefers-reduced-motion`"
  senaryolarının bu yüzeyde **karşılığı yok**; kart bunu gizlemiyor, durum
  seçildiğinde açıkça yazıyor. `prefers-reduced-motion` ayrı önizlemesi
  ancak kendiliğinden oynayan bir yüzeyde anlam taşır.
- **B5 — Ürün videosuna `poster` özniteliği HİÇ yazılmıyor.**
  `ProductVideoSection.ts:63` `<video src=… controls preload="metadata"
  playsinline>` üretiyor; `poster=` yok. Oysa `product.video` slotu
  `poster_192` ve `poster_1024` profillerini tanımlıyor. Poster üretilse bile
  **storefront onu kullanmıyor.** Düzeltme storefront tarafında (bu depodan
  yapılamaz), Faz 12/13'e.

### 3.2 Güvenli alan — ✅ hesaplanıyor, ⚠️ bir ögesi ölçülemedi

Kapağın üstüne binen ögeler ve kapladıkları pay, aktif cihazın kutusundan
hesaplanıyor (kutu 16:9 `aspect-video`, `StoreHeader.ts:297`):

| Öge | Kaynak | Ölçü |
|---|---|---|
| Kontrol çubuğu | `StoreHeader.ts:327` `px-3 py-2.5` (20 px) + 20 px ikon satırı | 40 px yükseklik, tam genişlik |
| Oynat düğmesi | `StoreHeader.ts:320` `w-14 h-14` | 56×56 px, merkez |
| Yerel kontroller (ürün videosu) | `ProductVideoSection.ts:63` `controls` | **ÖLÇÜLMEDİ** — yüksekliği tarayıcıya bağlı |

Örtme payı sabit piksel / değişken kutu olduğu için **cihazla değişiyor** ve
en dar telefonda en büyük — **ölçüldü** (vekil kutu üzerinden):

| Cihaz | Kutu | Kapak yüksekliği | Kontrol çubuğu | Oynat düğmesi |
|---|---|---|---|---|
| `galaxy-s23` | 360 px | 203 px | **%19,7** | %4,3 |
| `iphone-14` | 390 px | 219 px | %18,3 | %3,7 |
| `desktop-1080p` | 502 px | 282 px | **%14,2** | %2,2 |

Test bunu doğruluyor (dar kutuda pay > geniş kutuda pay).

Kart, "önemli içerik örtülüyor mu" sorusuna **cevap vermiyor** ve bunu yazıyor:
o soru kırpma niyetinin güvenli alanını ister, bu kartta seçili varlık yok.

### 3.3 Üç önizleme durumu — ✅

`poster` / `autoplay` / `reduced` düğmeleri (`aria-pressed`), 16:9 bir mock
kapak çizimi (poster + oynat düğmesi + kontrol çubuğu, güvenli alan taralı).
Çizim `aria-hidden` — her sayı altta metin olarak da var. **Gerçek bir video
elementi ya da gerçek bir poster dosyası GÖSTERİLMİYOR**; uç yok, uydurulmadı.

### 3.4 "İlk 10 saniyenin baytı" — ⚠️ KISMİ

Hesap var: `bit hızı × 10 sn ÷ 8`. Ama **varsayılan bit hızı yazılmadı** ve
**karşılaştırılacak tavan yok**:

- `scripts/sync-simulator.mjs` `video_decision.json`'dan **yalnız `poster`
  bloğunu** türetiyor. HLS merdiveni (`360p 800 · 480p 1400 · 720p 2800 ·
  1080p 5000 kbps`) ve `bitrate_over_cap` **2.500.000 bps** eşiği panele
  **vendor'lanmadı**.
- `scripts/` ve `lib/media/simulator/vendor/` bu görevde salt okunurdu.

Alan boş başlıyor, kullanıcı bit hızını girince tahmin çıkıyor; tavanın
yokluğu ekranda açıkça yazıyor. **Gereken değişiklik** aşağıda §6.2.

**Ayrıca yapılmayan:** *"video dosyası işlenmemişse LQIP + 'işleniyor' durumu"*.
Bu bir varlık durumu gerektiriyor (`Media Asset.status`), kart varlıksız
çalışıyor. **YAPILMADI.**

---

## 4. T-114 — onay kapısı ve `previewed_placements` kaydı

### 4.1 Kapının kuralları

`useSimulatorApproval.js`:

- **Zorunlu yerleşimler** = `lcp_candidate` işaretli bölgeler. Ayrı liste
  tutulmadı — bayrak `placements.json`'da zaten var. Bugün **5 bölge**:
  `home/hero_showcase_grid`, `listing/card_grid`, `listing/brand_grid`,
  `product_detail/main_image`, `seller_shop/product_grid`.
- **Yerleşim sınıfı** = cihaz sınıfı: `phone`, `tablet`, `laptop`, `desktop`.
- Toplam gereklilik: **5 × 4 = 20**.
- **Görünürlük eşiği:** `IntersectionObserver` ile kutu `≥ %50` görünür VE
  `≥ 1000 ms` ekranda. Eşikler `VISIBILITY_RATIO` / `DWELL_MS` sabitlerinde,
  tek yerde.
- **Uyarılı yerleşimler** açık onay kutusu ister; kabul edilmeden kapı açılmaz.
- `IntersectionObserver` yoksa (SSR / Node) **hiçbir şey işaretlenmez** —
  kapının yokluğunda kendiliğinden açılması, kapıyı olmamasından kötü yapardı.
  Test var.
- Gereklilik kümesi boşsa kapı **yine açılmaz** (`gereklilik_yok` engeli):
  vakumda açılan kapı, kapı değildir.
- Aynı çift için ikinci kayıt gelirse **daha uzun kalma kazanır**; denetim
  kaydındaki süre kısalmaz.

`SimApprovalGate.vue`: ilerleme çubuğu (`role="progressbar"`), canlı sayaç
(`aria-live`), 20 satırlık kontrol listesi (her satır kendi kutusunu gözlemler
ve o kombinasyonun seçim özetini gösterir), eksik satırda "Bu yerleşime git"
(`goto` olayı), uyarı kabul kutuları, **pasif** "Onayla ve yayınla" düğmesi
(`aria-describedby` ile sebebe bağlı) ve gidecek kaydın `<details>` önizlemesi.

### 4.2 `previewed_placements` yolu — yazıldı, kırık yola BAĞLANMADI

Kaydın şekli (`Media Crop Intent.previewed_placements`, JSON alan):

```json
[{"page":"listing","region":"card_grid","placement":"listing/card_grid",
  "device":"iphone-14","device_class":"phone",
  "ts":"2026-08-19T…Z","dwell_ms":1240}]
```

`withPreviewedPlacements(base, placements)` saf fonksiyon:

1. **`overrides` taşıyan yükü REDDEDER** (test var). Gerekçe ölçüldü:
   `save_intent`'in `overrides` yolu **her zaman 417** dönüyor —
   `Media Crop Override.profile` bir `Link → Media Profile`tır ve
   `product.image:w384` docname'i bekler, kütüphane ise slot içi kısa adı
   (`w384`) bekler (`docs/reports/41-t080-api-sozlesme.md` §4). Şerit A ajanı
   bunu düzeltiyor; bu kapı o yola **hiç bağlanmadı**.
2. **`asset` zorunlu** ve mevcut niyet alanları **korunur**: `save_intent`
   gönderilmeyen alanı `None` yazdığı için yalnız `previewed_placements`
   göndermek kayıtlı **odak noktasını SİLERDİ**. Test var.
3. `submit()` kapı kapalıyken **istek atmaz**, `MEDIA_PREVIEW_REQUIRED` fırlatır.

`SimApprovalGate.vue` **ağ isteği atmaz**: onayı `approve` olayıyla yukarı
verir. Kaydı `save_intent`'e yazmak, kırpma niyetinin geri kalan alanlarına
sahip olan ekranın (Crop Studio) işidir — iki ekranın aynı DocType'a yarım
yükle yazması, birinin diğerinin alanını silmesi demekti.

### 4.3 Sunucu tarafı kapı — **YOK**, ölçüldü

| Kabul ölçütü maddesi | Durum |
|---|---|
| `previewed_placements` alanı | ✅ **VAR** — `media_crop_intent.json`, `JSON` tipi |
| `save_intent` bu alanı yazıyor | ✅ **VAR** — `api/media_crop.py:283-284, 422, 450` |
| Sunucu gövdeyi **doğruluyor** | ❌ **YOK** — `_validate_previewed_placements()` yalnız "geçerli JSON mu" bakıyor; eksik cihaz sınıfıyla gelen kayıt **reddedilmiyor** |
| `preview_gate_passed` alanı | ❌ **YOK** (DocType'ta böyle bir alan yok) |
| Eksik önizlemeyle yayımı reddeden uç / `MEDIA_PREVIEW_REQUIRED` | ❌ **YOK** — dizge repoda hiç geçmiyor |
| Denetim kaydı | ❌ **YOK** — kayıt istemci tarafında üretiliyor, sunucuya ayrı bir denetim satırı yazılmıyor |

Ekran bunu **saklamıyor**, kapının altında yazıyor. Kaynak plandaki uyarı
aynen geçerli: bu kapı **kanıt değil BEYAN** toplar; gücü teknik zorlamadan
değil, beyanın denetim kaydına yazılmasından gelir. Bugün o yazma da yok.

---

## 5. i18n — GEREKEN ANAHTARLAR (orkestratör ekleyecek)

`i18n/locales/*.js` bu görevde dokunulmadı. Yeni metinler `t(key, params,
varsayılan)` üçüncü argümanıyla yazıldı: **anahtar yolu ekrana sızmıyor**,
Türkçe metin basılıyor, anahtar eklendiği anda varsayılan devre dışı kalıyor.
Bu yüzden `views/system/__tests__/mediaSimulator.test.js`'teki *"çeviri
anahtarı sızmıyor"* testi **yeşil kaldı**.

Varsayılan metinler bileşenlerin içinde duruyor; anahtarlar dört dile
eklendiğinde **silinebilirler** (silinmezlerse de zarar vermezler, sadece ölü
metin olurlar).

### 5.1 `mediaSimulator.result.*` (T-112)

| Anahtar | Parametreler |
|---|---|
| `lcpBadge` | — |
| `lcpNote` | — |
| `bytes` | — |
| `bytesUnknown` | — |
| `bytesNote` | — |
| `overflowText` | `{boxPx} {viewportPx} {overflowPx} {ratio}` |
| `verdict.ok` | `{chosen} {required}` |
| `verdict.short` | `{chosen} {required} {deficit}` |
| `verdict.zoomShort` | `{multiplier} {zoom} {chosen}` |
| `verdict.none` | — |

### 5.2 `mediaSimulator.poster.*` (T-113)

`surfaceTitle` · `surface.company_cover_video` · `surface.product_video` ·
`stateTitle` · `state.poster` · `state.autoplay` · `state.reduced` ·
`stageNote {device} {width} {height} {aspect}` · `noAutoplay` · `reducedNoop` ·
`attr.autoplay` · `attr.muted` · `attr.loop` · `attr.playsinline` ·
`attr.poster` · `attr.preload` · `attr.controls` · `yes` · `no` ·
`controls.custom` · `controls.native` · `safeTitle` · `zone.controlBar` ·
`zone.playButton` · `zone.nativeControls` · `zoneUnmeasured` ·
`safeVerdict {pct} {unmeasured}` · `dataTitle` · `bitrate` ·
`firstWindow {s} {bytes}` · `firstWindowEmpty {s}` · `noBudget`

### 5.3 `mediaSimulator.gate.*` (T-114)

`title` · `lead` · `threshold {pct} {ms}` · `progress {done} {total}` ·
`class.phone` · `class.tablet` · `class.laptop` · `class.desktop` · `seen` ·
`notSeen` · `goto` · `warningsTitle` · `ackLabel {warning} {n}` ·
`blocker.gereklilik_yok` · `blocker.yerlesim_gorulmedi {n}` ·
`blocker.uyari_kabul_edilmedi {n}` · `noAsset` · `publish` · `serverGap` ·
`payloadTitle`

> Varsayılan Türkçe metinlerin tamamı bileşen kaynağında; çeviriyi oradan
> kopyalayıp dört dile taşımak yeterli. `simulatorA11y.test.js` dört dilin
> anahtar kümesinin **birebir aynı** olmasını zorluyor.

---

## 6. Bağlanması gerekenler (bu görevde YAPILMADI)

### 6.1 Panel — orkestratörün lane'i

`SimApprovalGate.vue` **hiçbir yere monte edilmedi** (`MediaSimulatorView.vue`
dokunma listesindeydi). Bağlantı:

```vue
<SimApprovalGate
  :devices="DEVICES" :regions="ALL_REGIONS" :source-width="sourceWidth"
  :asset="assetName"
  @goto="({ region, device }) => { regionKey = region.key; deviceId = device.id; }"
  @approve="onApprove"
/>
```

`onApprove` kaydı Crop Studio'nun `save_intent` yüküyle birleştirmeli:
`withPreviewedPlacements(cropPayload, previewed_placements)` — **`overrides`
göndermeden**.

### 6.2 `tradehub_core` / build betiği

| # | İş | Dosya | Neden |
|---|---|---|---|
| 1 | `video_decision.json`'ın `rules`+`hls.ladder` bit hızlarını vendor'la | `admin-panel/frontend/scripts/sync-simulator.mjs` | T-113 "ilk 10 sn baytı standartla karşılaştırılsın" maddesi bugün karşılaştıracak tavana sahip değil |
| 2 | Video bölgelerini `placements.json`'a ekle: `seller_shop/cover_video`, `product_detail/gallery_video` (+ `safe_zones[]`) | `tradehub_core/media/pipeline/simulator/placements.json` | Poster kutusu bugün `product_detail/main_image` **vekiliyle** hesaplanıyor; §3.1 künyeleri oraya taşınmalı |
| 3 | Sunucu tarafı onay kapısı | yeni uç, ör. `tradehub_core.api.media_crop.publish_asset` | Eksik `previewed_placements` ile yayımı **400 + `MEDIA_PREVIEW_REQUIRED`** ile reddetmeli; `zorunlu = lcp_candidate bölgeler × cihaz sınıfları` sunucuda **kendisi** hesaplanmalı |
| 4 | `preview_gate_passed` (Check) alanı + denetim kaydı | `media_crop_intent.json` + `media/av.py`'nin izlediği denetim yolu | Kapının sonucu ve "kim, ne zaman, neyi gördü" sunucuda saklanmıyor |
| 5 | `save_intent` `overrides` sözlük çakışması | Şerit A ajanında | Bu kapı o yola **bağlanmadı**; düzeldiğinde de bağlanmasına gerek yok |
| 6 | Storefront: ürün videosuna `poster` özniteliği (B5) | `tradehubfront/.../ProductVideoSection.ts:63` | Poster profilleri üretilse de kullanılmıyor |

---

## 7. Ölçülmeyenler — tek liste

- Tarayıcıda gerçek yerleşim, gerçek `getBoundingClientRect()`, drift (T-115).
- Süre / FPS / ilk boyama: **hiçbir iddia yok**.
- Gerçek ekran okuyucu (NVDA/VoiceOver), gerçek odak halkası, renk kontrastı, RTL.
- `IntersectionObserver` eşiğinin gerçek tarayıcıda tutması: Node koşucusunda
  `IntersectionObserver` **yok**, o dal yalnız "hiçbir şey işaretlemiyor"
  yönüyle test edildi.
- Türev baytları: `Media Rendition` tablosu boş — bayt gösterimi **canlı veriyle
  hiç ölçülmedi**, yalnız sahte satırla (SSR testi) doğrulandı.
- Ürün videosunun yerel kontrol çubuğu yüksekliği (tarayıcıya bağlı).
- Yüzey künyeleri (`StoreHeader.ts` / `ProductVideoSection.ts`) **okundu**,
  tarayıcıda **doğrulanmadı**.
