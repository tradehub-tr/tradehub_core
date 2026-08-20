# 46 — T-093: Detay çekmecesi (versiyon / rendition / kullanım / kalite)

**Tarih:** 2026-08-19
**Depo/branch:** `admin-panel` · `ahmet`
**Kaynak kriter:** <https://karacaismail.github.io/imageoptimization/docs/60-faz9-media-library.html> — "Asset Detay Çekmecesi (T-093)"

---

## 1. Ne yapıldı

Satıcı medya kütüphanesindeki detay paneli (`MediaDetailPanel.vue`) **beş sekmeli
bir çekmeceye** dönüştürüldü — kaynağın "Çekmece beş sekmeden oluşacaktır: Özet,
Rendition'lar, Kullanım, Kalite ve Geçmiş" maddesinin karşılığı:

| Sekme | İçerik | Durum |
|---|---|---|
| Özet | Önizleme + ad/başlık/alt/açıklama/etiket + boyut, çözünürlük, tarih | Mevcuttu, sekmeye taşındı |
| Türevler | `MediaRenditionList` (bugün eklenen bileşen) | Mevcuttu, sekmeye taşındı |
| Kullanım | **YENİ** `MediaUsagePanel` — canlı / sipariş / geçmiş kırılımı | Yeni |
| Kalite | **YENİ** `MediaQualityPanel` — kaynak ↔ normalize sonuç, SSIM, tasarruf | Yeni |
| Sürüm | "DocType kurulu değil" durumu | Yeni (veri yok, uydurulmadı) |

Kaynağın beşinci sekmesi "Geçmiş" olarak adlandırılıyor ve içeriği olarak
*Media Processing Job + audit* tarif ediliyor. Burada sekme **"Sürüm"** olarak
kuruldu, çünkü görevin kapsamı `versiyon` başlığıydı ve sürüm geçmişinin
dayanağı olan `Media Version` DocType'ı kurulu değil (§3.3). İşlem geçmişi /
audit ayrı bir görevin konusu.

### Dosyalar

| Dosya | Durum |
|---|---|
| `frontend/src/components/media/MediaDetailPanel.vue` | değiştirildi (sekmeler, sürüm bölümü) |
| `frontend/src/components/media/MediaUsagePanel.vue` | **yeni** |
| `frontend/src/components/media/MediaQualityPanel.vue` | **yeni** |
| `frontend/src/composables/useMediaUsage.js` | **yeni** |
| `frontend/src/composables/__tests__/mediaUsage.test.js` | **yeni** (10 test) |
| `frontend/src/composables/__tests__/fixtures/sellerMediaStub.js` | **yeni** (test sahtesi) |
| `frontend/src/components/media/__tests__/mediaDetailDrawer.test.js` | **yeni** (11 test) |

Yasak alanların hiçbirine dokunulmadı: `router/index.js`, `data/navigation.js`,
`i18n/locales/*`, `MediaLibraryView.vue`, `MediaExplorerView.vue`,
`upload/**`, `crop/**`, `simulator/**`, `MediaRenditionList.vue`,
`useMediaRenditions.js` (yalnız **okundu/kullanıldı**), `tradehub_core`,
`docker/`.

---

## 2. Ölçülen backend gerçeği

Kod okunarak doğrulandı; hiçbir uç uydurulmadı.

| Konu | Ölçüm | Kaynak |
|---|---|---|
| Kullanım ucu | `tradehub_core.api.seller_media.get_my_usage(file_url)` — mağaza **oturumdan** çözülüyor, parametre yok | `tradehub_core/api/seller_media.py:172` |
| Yanıt şekli | `{file_url, verdict, usages[], orders[], history[], records[], redundant_records}` | `tradehub_core/media/usage.py:461` `resolve()` |
| Özet ucu | `get_my_summary()` — `store/active/trashed/bytes/quota_bytes/tags`. Bu görevde **kullanılmadı** (üst şerit zaten okuyor) | `seller_media.py` |
| `Media Rendition` tablosu | **BOŞ** (bayraklar kapalı) — boş durum birinci sınıf tutuldu | görev brifingi + `useMediaRenditions.js` başlık notu |
| `Media Version` DocType | **KURULU DEĞİL** | §3.3 |
| SSIM | `Media Rendition.ssim` alanı var; ölçülmemişse `0` geliyor | `useMediaRenditions.js` |

### 2.1 Brifingdeki iki rakam düzeltildi

Görev metni "`LIVE_SOURCES` **10 giriş** tutuyor" ve "`core/usage.py:134` kendi
deyimiyle *bellek içi depo*" diyordu. Ölçüm:

- `tradehub_core/media/usage.py` içinde **`LIVE_SOURCES` 8 giriş**,
  `ORDER_SOURCES` 2, `HISTORY_SOURCES` 6 (toplam 16 taranan kaynak kolonu).
  "10" muhtemelen canlı + sipariş toplamı.
- **`tradehub_core/core/usage.py` diye bir dosya YOK.** "Bellek içi depo"
  ifadesi `tradehub_core/docs/reports/34-dogrulama-faz4-7.md:289` satırında
  geçiyor: *"`Media Usage` **kalıcı kayıt değil**, bellek içi depo; kaynağın
  1. kriteri karşılanmıyor"*.

**Sonuç aynı ve önemli:** kalıcı bir kullanım dizini yok, döküm istek anında
sabit bir kaynak listesi taranarak üretiliyor. Bu yüzden ekrana bir **sayı
yazılmadı** (8/2/6 sayıları frontend'e kopyalansa backend değişince sessizce
yalan söylerdi); bunun yerine sınır **cümle** olarak, her durumda görünür
biçimde basılıyor (`media.usage.scanNote`).

---

## 3. Dürüstlük kararları (bu görevin asıl işi)

### 3.1 Kullanım — "bilinmeyen" ile "boş" ayrı

`useMediaUsage` dört boş durumu ayrı tutuyor, `useMediaRenditions` ile aynı
sözleşme:

```
noFile   → sorulacak adres yok, istek hiç atılmadı
notUsed  → arka taraf yanıtladı, taranan kaynakların hiçbirinde yok
denied   → sunucu "bakamazsın" dedi (403 / PermissionError) — arıza değil
error    → gerçekten bir şey kırıldı
```

Bunların dışında bir beşinci hâl var ve en kritiği o: **`report` hâlâ `null` ve
hiçbir bayrak yanmamışsa cevap henüz gelmemiştir.** O anda ekran "kullanılmıyor"
demez. Test: *"cevap gelmeden 'kullanılmıyor' denmez — report null kalır"*.

Ayrıca yetki reddinde `report` `null` bırakılıyor — reddedilen bir istek boş
liste gibi gösterilseydi satıcı kendi ürününde duran görseli silmeye
yönlendirilirdi.

Sonuç `verdict` arka taraftan **olduğu gibi** taşınıyor, ekranda yeniden
hesaplanmıyor: aynı soruya iki yerin farklı cevap vermesi silme akışında kabul
edilemez.

### 3.2 Kalite — ölçülmemiş olan "—", sıfır değil

- SSIM `0` ise `—` gösteriliyor; "0,000" yazmak ölçüm eksikliğini kalite
  felaketi gibi gösterirdi.
- Tasarruf oranı **yalnız iki gerçek bayt varken** hesaplanıyor; aksi hâlde
  satır hiç çizilmiyor ("%0 tasarruf" yazılmıyor).
- Kaynak künyesinden **DPI, renk uzayı ve alfa** hiçbir uçta yok. Satırlar
  tablodan **çıkarılmadı**, `—` ile duruyor: satırı gizlemek "ölçüldü ve
  sorunsuz" izlenimi verirdi.
- Normalize sonucun temsilcisi **en büyük türev** (merdivenin kaynakla
  karşılaştırılabilir tek basamağı); toplam bayt kullanılsaydı yanıltıcı olurdu.
- `Media Quality Report` DocType'ı da kurulu değil → kaynağın istediği
  "uygulanan işleme kararları" listesi gösterilemiyor, bu da not olarak yazılı.

### 3.3 Sürüm — `Media Version` kurulu değil

Ölçüm (`tradehub_core/tradehub_core/doctype/` altında kurulu medya doctype'ları):

```
media_asset · media_crop_intent · media_crop_override · media_engine_settings
media_processing_job · media_profile · media_rendition · media_storage_settings
```

`media_version` **yok**. Ayrıca `media_asset.json` başlığındaki sapma notu
açıkça yazıyor: *"(3) `active_version` alanı YOK — Media Version bu dalgada
kurulmadı."* Şema yalnız `media/pipeline/doctype_specs/media_version.json`
içinde tasarım olarak duruyor.

Bu yüzden Sürüm sekmesinde **boş liste, "sürüm bulunamadı" ya da tek satırlık
sahte bir geçmiş yok** — üçü de özelliğin var olduğunu ve bu dosyanın sürümsüz
olduğunu söylerdi. Ekran "kurulu değil" diyor. Bunu doğrulayan test:
*"sürüm sekmesi UYDURMAZ: DocType kurulu değil, boş liste gösterilmez"*.

> **Bakım borcu:** bu blok statik. `Media Version` kurulduğunda
> `MediaDetailPanel.vue` içindeki `versions` sekmesi gerçek listeyle
> değiştirilmeli; kod içinde bu gerekçe yorum olarak duruyor.

### 3.4 Özet'ten kaldırılan çelişki

Özet'teki eski kullanım bloğu `item.usageDetail`'e bakıyordu. `useSellerMedia`
bu alanı hiç doldurmuyor (yalnız `stores/media.js` `loadUsage()` doldurabiliyor),
dolayısıyla pratikte hep *"Kullanım bilgisi doğrulanmadı"* yazıyordu. Yeni
Kullanım sekmesi doğrulanmış dökümü gösterirken aynı ekranda "doğrulanmadı"
satırının durması **doğrudan çelişki** olurdu; blok Özet'ten kaldırıldı, konu
tamamen Kullanım sekmesine devredildi.

`stores/media.js:loadUsage` ve `MediaLibraryView`'daki çağrısı **değiştirilmedi**
(yasak alan); `usageDetail` hâlâ `MediaPreviewModal` tarafından kullanılıyor.

---

## 4. Erişilebilirlik

- WAI-ARIA tabs deseni: `role="tablist"` / `role="tab"` / `role="tabpanel"`,
  `aria-selected`, `aria-controls`, `aria-labelledby`.
- **Roving tabindex**: yalnız etkin sekme Tab sırasında (`tabindex="0"`),
  diğerleri `-1`; şeritte gezinme `ArrowLeft/Right`, `Home`, `End` ile. Beş
  düğme de Tab sırasında olsaydı klavye kullanıcısı içeriğe beş Tab'da ulaşırdı.
- Sekme düğmeleri `tap-target` (44px) mixin'iyle; şerit dar ekranda yatay
  kaydırılıyor (sarmalanıp içeriği aşağı itmiyor).
- Boş/arıza metinleri bilinçli olarak `muted` **değil** — tek başına ekranda
  kalan bilgi, okunabilirliği kontrast oranına bağlı.
- Vitrin bağlantısı rengi `$brand` (sarı) **değil**; bağlantı olduğu altı
  çizgiyle bildiriliyor — sarı, açık zeminde metin kontrastını geçmiyor.

**Ölçülmedi:** gerçek ekran okuyucu (NVDA/VoiceOver), görsel odak halkası,
tarayıcıdaki gerçek Tab sırası. Bu görevde **tarayıcı doğrulaması yapılmadı**.

---

## 5. i18n — orkestratörün bağlaması gereken anahtarlar

Locale dosyaları yasak alan; kod `t(...)` kullanıyor, anahtarlar aşağıda.
4 dil de (`tr`, `en`, `ru`, `ar`) doldurulmalı.

### Yeni: `media.detail.*`
```
tabsLabel
tab.summary · tab.renditions · tab.usage · tab.quality · tab.versions
```

### Yeni: `media.usage.*`
```
title · count ({n}) · loading · denied · failed
noFile · notFound · unknown · scanNote
liveTitle · ordersTitle · historyTitle · historyCount ({n}) · recordsTitle
openPage · unpublished · noAttachment · targetMissing
redundant ({n}) · attachedMismatch
verdict.in_use · verdict.order_only · verdict.history_only · verdict.unused · verdict.unknown
```

`scanNote` metninin taşıması gereken anlam (§2.1): *bu döküm kalıcı bir kullanım
kaydından değil, istek anında taranan sabit bir kaynak listesinden geliyor;
listede olmayan bir alanda geçen dosya burada görünmez.*

`notFound` metni **"hiçbir yerde kullanılmıyor" DEMEMELİ** — "taranan
kaynaklarda bulunamadı" demeli.

### Yeni: `media.quality.*`
```
title · caption · loading · denied · failed · notInPipeline · notMeasured
col.attribute · col.source · col.result
attr.dimensions · attr.megapixels · attr.bytes · attr.format
attr.dpi · attr.colorSpace · attr.alpha
savings ({percent}, {from}, {to}) · ssimWorst ({value}, {n}, {total}) · ssimNone
scopeNote
```

`scopeNote` iki eksiği birden söylemeli: (1) DPI/renk uzayı/alfa arka taraftan
gelmiyor, (2) `Media Quality Report` DocType'ı kurulu değil.

### Yeni: `media.versions.*`
```
title · notInstalled · scopeNote
```

### Artık kullanılmayanlar (silme kararı sende, i18n bana yasak)
- `media.detail.usageUnknown` — başka kullanan yok, **yetim**.
- `media.detail.notUsed` — başka kullanan yok, **yetim**.
- `media.detail.usedIn` — hâlâ `MediaPreviewModal.vue:102` kullanıyor, **kalmalı**.

Anahtar listesinin kodda gerçekten geçtiğini doğrulayan bir test var
(*"çeviri anahtarları tek listede"*), böylece liste kodla birlikte çürümüyor.

---

## 6. Doğrulama — ne koşturuldu

Hepsi `admin-panel/frontend` içinde, gerçekten çalıştırıldı:

| Komut | Sonuç |
|---|---|
| `npm run lint` | **EXIT 0** — 0 hata, 2 uyarı. İkisi de **benim değil**: `views/permission/PlansTab.vue:1024,1035` (`addFeature`/`removeFeature` kullanılmıyor), başlangıçtan beri var. |
| `npm run build` | **EXIT 0** — `✓ built in 4m 57s` |
| `npm test` | **EXIT 0** — `tests 560 · pass 560 · fail 0` |
| `npx prettier --write <yalnız kendi 7 dosyam>` | biçimlendirildi (paralel ajanların dosyalarına dokunmamak için `lint:fix` **kullanılmadı**) |

### 6.1 Test sayısı hakkında dürüst not

Brifing "bugün 396/396" diyordu. **Ölçüm farklı çıktı:**

- **Başlangıç (işe başlarken, kendi değişikliğim yokken):**
  `tests 396 · pass 395 · fail 1`.
  Düşen test: `src/lib/media/simulator/__tests__/srcsetParity.test.js:247`
  — *"manifest canlı tradehub_core kaynağıyla uyuşuyor"*, sebep
  `tradehub_core/.../policy/video_decision.json` değişmiş, `npm run sync:simulator`
  gerekiyordu. Hem `simulator/**` hem `tradehub_core` bana **yasak**, dokunmadım.
- **Bitişte:** `tests 560 · pass 560 · fail 0`.
  Sayının 396 → 560'a çıkması ve o testin düzelmesi paralel çalışan diğer
  ajanların katkısı; benim eklediğim 21 test (10 + 11) bunun içinde.

Yani "396/396" hiçbir noktada ölçülmedi; ölçülen değerler yukarıdaki ikisi.

### 6.2 Boş durum testleri (brifingin 3. bitirme koşulu)

| Boş durum | Test |
|---|---|
| Türev yok | `türev yokken kalite paneli 'ölçüm yok' der, sıfır uydurmaz` + mevcut `mediaRenditions.test.js` |
| Kullanım yok | `taranan kaynaklarda bulunamayınca boş sebep 'notUsed' olur`, `adres yoksa istek atılmaz ve panel çökmeden gerekçe gösterir` |
| Versiyon yok | `sürüm sekmesi UYDURMAZ: DocType kurulu değil, boş liste gösterilmez` |
| Yetki reddi | `yetki reddi ARIZA olarak gösterilmez, ayrı bayrağa düşer`, `yetki reddi ekranı çökertmez, boş liste gibi de göstermez` |
| Arka taraf hiçbir anahtar göndermezse | `eksik alanlar çökertmez` |

Üçü de çizim sırasında **çökmedi ve hata basmadı** — SSR çıktısı üretildi ve
beklenen gerekçe metni/işareti bulundu.

---

## 7. Ölçülmeyenler (iddia edilmiyor)

- **DOLU hâlin ekran çıktısı.** `Media Rendition` tablosu boş; ayrıca SSR tek
  geçişte çizdiği için istek cevabı render'a yetişmiyor. Veri gelmiş hâlin
  görünümü bu görevde **ölçülmedi**. Normalizasyon mantığı (gruplama, sayfa
  adresi, üç değerli `target_exists`, sipariş/geçmiş ayrımı) composable
  seviyesinde ölçüldü.
- **Tarayıcı doğrulaması yapılmadı** — ne satıcı panelinde ne Storybook'ta
  açıldı. Görsel yerleşim, sekme şeridinin dar sheet'teki davranışı ve gerçek
  odak sırası **görülmedi**.
- **Süre/performans iddiası yok.** İstek sayısı azaltıldı (tembel sekmeler:
  ziyaret edilmeyen sekme DOM'a girmiyor ve isteğini atmıyor) ama bunun
  kullanıcıya yansıyan süresi ölçülmedi.
- **Backend'e hiç istek atılmadı** (Frappe ayağa kaldırılmadı); uç adları ve
  yanıt şekilleri **kod okunarak** doğrulandı.
- Rota / menü / i18n bağlantısı bu görevin kapsamı **değil**; anahtarlar §5'te.

---

## 8. Açık bulgular / devir notları

1. **i18n bağlanmadan ekran anahtar adları gösterir.** §5 listesi doldurulana
   kadar Kullanım/Kalite/Sürüm sekmeleri `media.usage.title` gibi ham anahtar
   basar. Test bu duruma dayanıklı yazıldı (metin değil yapı doğrulanıyor).
2. **`media.detail.usageUnknown` ve `media.detail.notUsed` yetim kaldı.** 4
   locale'de duruyorlar, artık hiçbir bileşen kullanmıyor.
3. **Sürüm sekmesi statik.** `Media Version` kurulduğu gün elle güncellenmeli
   (kodda gerekçeli yorum var).
4. **DPI / renk uzayı / alfa hiçbir uçtan gelmiyor.** Kaynağın kabul kriteri
   bunları istiyor; bugün `—`. Backend'de bu üç alanın çıkarılması ayrı bir iş.
5. **`Media Quality Report` kurulu değil**, dolayısıyla "uygulanan işleme
   kararları" bölümü hiç yapılmadı — uydurulmadı.
6. **`srcsetParity` testi başlangıçta kırıktı** (§6.1). Bitişte geçiyor ama
   düzelten ben değilim; `sync:simulator` senkronunun kalıcı olduğundan emin
   olunmalı.
