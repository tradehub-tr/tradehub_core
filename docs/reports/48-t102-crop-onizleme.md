# 48 — T-102 / T-103 / T-104: kırpma önizlemesi, güvenli alan ve niyet kaydı

**Tarih:** 2026-08-19
**Depo:** `admin-panel` (branch `ahmet`) — `tradehub_core` **okundu, tek satır değiştirilmedi**
**Görevler:** T-102 (canlı çoklu önizleme), T-103 (otomatik odak önerisi + güvenli alan),
T-104 (politika uyarıları + crop intent kaydı)

---

## 0. Bir cümlede

Rapor 31'in bıraktığı üç açığı kapattı: kart başına sunucu türevi durumu (T-102),
**güvenli alan** (T-103 — arayüzde hiç yoktu) ve **kaydetme akışının
tamamlanması** (T-104). Yol boyunca ölçülerek bulunan asıl kusur listede yoktu:
**kullanıcının yakınlaştırması kaydedilirken sessizce atılıyordu.**

---

## 1. Ölçülen sonuçlar

| Kapı | Sonuç |
|---|---|
| `npm run lint` | **EXIT 0** — 0 hata, 2 uyarı. İkisi de `views/permission/PlansTab.vue`'de (`addFeature`, `removeFeature` kullanılmıyor) ve **önceden vardı**; yeni uyarı yok. |
| `npm run build` | **EXIT 0** — `✓ built in 33.78s` |
| `npm test` | **EXIT 0** — **571 test, 571 pass, 0 fail, 0 skipped** |
| Kendi dört test dosyam | **100 test, 100 pass** |

> **Test sayısı hakkında dürüstlük notu.** Görev "bugün 396/396" diyordu. Bu
> depoda **14 ajan paralel çalışıyor** ve sayı benim koşumlarım sırasında
> 396 → 560 → 571 diye ilerledi (başkalarının eklediği testler). Başlangıç
> ölçümüm **396 test / 395 pass / 1 fail**tı; tek kırmızı
> `src/lib/media/simulator/__tests__/srcsetParity.test.js::manifest canlı
> tradehub_core kaynağıyla uyuşuyor` idi (`video_decision.json` hash'i
> ayrışmıştı) — **benim dosyalarımdan değil**, simülatör ajanının alanı. O ajan
> kendi senkronunu yaptı ve son koşumda yeşil geldi. Yani "396/396" iddiasını
> ben doğrulamadım; **doğruladığım şey son durumda 571/571**.

### Ölçülmeyenler (açıkça)

- **`< 16 ms` önizleme bütçesi ÖLÇÜLMEDİ.** Kare başına çizim süresi, DPR 1/2
  farkı, `createImageBitmap` maliyeti ve bellek tarayıcı ister. **Tarayıcıda
  doğrulama YAPILMADI** (görev kuralı).
- **Sunucunun canlı yanıtı ÖLÇÜLMEDİ.** Uçlar canlı ama bu ortamdan oturum
  açılamıyor. Ölçülen şey yükün *sözleşmeye* uygunluğu (§4).
- **smartcrop eşiği hâlâ kalibre değil.** Değiştirmedim; artık **gizlemiyorum**
  (§3.2).
- Ekran okuyucu (NVDA/VoiceOver), görsel odak halkası, DPR ≥ 2'de tutamak
  isabeti — hepsi ÖLÇÜLMEDİ.

### Uçların canlı olduğu — ölçülen ayrım

Görev "HTTP 403 = var, yetki istiyor" diyordu. Bunu doğruladım ve **ayrımı
sağlamlaştırdım**: Frappe'de olmayan bir method 403 değil **417** veriyor.

```
tradehub_core.api.media_crop.save_intent    → 403  PermissionError
tradehub_core.api.media_crop.suggest_focal  → 403  PermissionError
tradehub_core.api.media_crop.get_intent     → 403  PermissionError
tradehub_core.api.media_crop.bu_yok         → 417  "module ... has no attribute 'bu_yok'"
```

Yani 403 gerçekten "method var, oturum yok" demek. 417 olsaydı uç yoktu.

---

## 2. Yol boyunca çıkan asıl bulgu — **yakınlaştırma kaydedilmiyordu**

Görev listesinde yoktu; kaydetme yolunu uçtan uca izlerken çıktı.

Kaydedilen yük yalnız `focal_x`/`focal_y` taşıyordu. Sunucu
`core/crop.py`'nin öncelik zincirinde bu yükü **3. seviyeye** (`focal`) sokuyor
ve taban bölge olarak **tam kareyi** kullanıyor. Stüdyoda kullanıcı 4×
yakınlaştırıp kadraj çizdiğinde, sunucunun çözdüğü pencere o yakınlaştırmayı
hiç görmüyordu.

### Çözüm: `safe_area` = stüdyonun taban bölgesi

Bu bir keşif değil, iki fonksiyonun aynı olduğunun **ölçümü**:

| Stüdyo | Sunucu (2. seviye) |
|---|---|
| `cropWindow(sw, sh, base, targetAR, focalX, focalY)` | `_cover_window(safe, target_ratio, source_ratio, focal)` |

İkisi cebirsel olarak aynı: `base_unit.w/base_unit.h > r` koşulu
`base_px.w/base_px.h > targetAR`'a indirgeniyor, `ratioFit(..., INSIDE)`'ın
dallanmasının ta kendisi. Yani `safe = base / (sourceW, sourceH)` yazmak,
sunucunun **kullanıcının gördüğü pencereyi yeniden üretmesi** demek.

**Ölçüldü** (`cropStudio.test.js::sunucunun \`safe_focal\` seviyesi stüdyonun
penceresini AYNEN üretiyor`): 7 yakınlaştırma seviyesi × 4 pan konumu,
`_cover_window`in birebir JS yazımıyla karşılaştırma — **en büyük sapma
< 0,5 px** (T-100 parite toleransı). Regresyon kapısı ayrıca ölçüyor:
`safe_area` gönderilmezse sunucunun çözdüğü pencere **3 kattan fazla geniş**
çıkıyor — kaybın gerçekten var olduğunun kanıtı.

**Tam karede `null`.** `safe_region_of` tam kadrajı "belirtilmemiş" sayıyor
("her yer güvenli" ile "güvenli alan yok" aynı kapıya çıkar). Panel de aynı
ayrımı yapıyor; 1× yakınlaştırmada 2. ve 3. seviye aynı pencereyi veriyor.

**Boş sözlük gönderiliyor, alan atlanmıyor.** Uç `None` (dokunma) ile `{}`
(alanı SİL) ayrımını koruyor (`_parse_safe_area`). Panel niyetin tamamının
sahibi olduğu için 1×'e dönüldüğünde **siliyor** — yoksa eski bir
yakınlaştırmadan kalan güvenli alan, kullanıcının şimdi çizdiği kadrajı
sessizce daraltırdı.

---

## 3. Görev bazında ne yapıldı

### 3.1 T-102 — canlı çoklu önizleme (rendition kartları)

`Media Rendition` tablosu **boş** (bayraklar kapalı). Önizleme kaynak
görselden istemcide üretilmeye devam ediyor — değiştirilmedi. Eksik olan,
boş durumun **kart başına** söylenmesiydi: şeridin başlığındaki tek cümle
hangi profilin türevinin eksik olduğunu göstermiyordu.

- `CropPreviewStrip.vue` artık `renditions` prop'u alıyor; her kart
  `sunucu türevi yok` ya da `sunucu türevi · webp` diyor.
- Türev geldiğinde boş durumun yanlışlıkla yapışmadığı ayrıca ölçülüyor.
- Güvenli alan bandı kartın üstüne çizildi (§3.3) — **karartma değil çerçeve**;
  kullanıcı görselini görmeye devam etmeli.

Kaydetme akışıyla bağlantısı: `CropStudioModal` prop'u aşağı geçiriyor,
varsayılan `[]`. Çağıran (`MediaDetailPanel.vue` — **başka ajanın dosyası,
dokunulmadı**) değişmeden çalışır.

### 3.2 T-103 — otomatik odak önerisi + güvenli alan

**(a) Öneri artık sunucudan.** `suggest_focal` ucu canlı ve `focal_from_bytes`
EXIF rotasyonu uygulanmış 32×32 LANCZOS ızgarada ölçüyor; panelin tarayıcı
yolu 96 px'lik bir bitmap üzerinde çalışıyor ve **aynı sayıyı vermiyor**.
Sıralama: varlık kimliği varsa **önce uç**, uç erişilemezse tarayıcı yolu
**yedek** — ve hangisinin kullanıldığı `suggestion.source` alanında saklanıp
**ekranda söyleniyor** (`Sunucu önerisi alınamadı, tarayıcıda hesaplandı: …`).

**(b) `threshold_calibrated: false` GİZLENMİYOR.** Bitirme koşuluydu.
`CropToolbar.vue` (C4 ajanının dosyası, değiştirilemez) rozette yalnız
"güven %89" gösteriyor. Bilgi bu yüzden benim dosyamdan geliyor:
`cropWarnings` öneri devredeyken `suggestionUncalibrated` INFO uyarısı
üretiyor ve `CropPolicyNotice` onu basıyor —

> *"Otomatik öneri server tarafında hesaplandı; karşılaştırıldığı eşik (0.50)
> KALİBRE EDİLMEDİ. Sebep: measured."*

Alan yanıtta hiç yoksa **`false` varsayılıyor**: eksik bilgiyi "kalibre edildi"
diye okumak, ölçülmemiş bir eşiği ölçülmüş göstermek olurdu.

**(c) `measured: false` "öneri" diye sunulmuyor.** Sunucu düz renk görselde
merkez + `measured: false` + `reason` dönüyor. Panel bunu artık ayırıyor:
*"Öneri ölçülemedi (no_edge_energy) — merkez gösteriliyor, bu bir öneri
değil."* İstemci yolu da aynı şekle döndürüldü (`olcemedim()`), böylece iki
üretici tek şekil konuşuyor.

**(d) Güvenli alan — iki ayrı şey, ikisi de kuruldu.**

| | Nedir | Nereden gelir |
|---|---|---|
| **Kaydedilen** `safe_x/y/w/h` | Kadrajın içinden çıkarılacağı bölge | Stüdyonun taban bölgesi (§2) |
| **Politika bandı** | Dar ekranda kesin görünen orta kesit | Slot politikasının `content_rules` bloğu |

Politika bandı **hesaplanmadı, kopyalandı**:

| Slot | Kural | Eşik | Eksen |
|---|---|---|---|
| `company.cover_image` | `safe_area_center_width_fraction` | 0,417 | yalnız yatay (kutu oranı 2,00…4,80, hedef 4,80) |
| `category.banner` | `safe_area_center_fraction` | 0,42 | her iki eksen (bento kutusu 0,82:1…4,68:1) |

Kalan **yedi slotta güvenli alan kuralı YOK** — o slotlarda bant çizilmiyor ve
uyarı üretilmiyor. Uydurulmuş eşik konmadı.
`cropSafeArea.test.js` her koşuda bu iki sayıyı **canlı politika dosyalarıyla**
karşılaştırıyor ve kural kümesinin ayrışmadığını da ölçüyor; kardeş depo
ortamda yoksa **"geçti" demiyor, sebebini yazarak atlıyor**
(`cropGeometryParity.test.js` ile aynı disiplin).

İhlal uyarısı: odağın kadraj içindeki **göreli** konumu bandın dışına
düşerse `safeBand` WARN. Odak kelepçelenmiyor — kadrajın solundaki bir odak
negatif okunuyor, uyarının kendisi bu. Politika `action: "warn"` diyor ve panel
de **engellemiyor**; engel olsaydı kullanıcı kendi görselinden kilitlenirdi.
Odak bilinmiyorsa uyarı **üretilmiyor** ("konum bilmeden ihlal denemez"), ama
`safeBandActive` INFO rozeti yine çıkıyor.

### 3.3 T-104 — politika uyarıları + crop intent kaydı

Uyarı seti 8'den **11'e** çıktı (`safeBand`, `safeBandActive`,
`suggestionUncalibrated`). Kaydetme akışı tamamlandı:

- `savePayload` artık `safe_area` taşıyor (§2).
- `cropIntentApi.saveCropIntent` `safe_area`yı JSON dizgesi olarak gönderiyor —
  Frappe form-encoded gövdede iç içe sözlük taşıyamıyor, uç `_cozumle` ile
  çözüyor.
- **Sözleşme kapısı (`validateIntentPayload`).** Aralık dışı bir koordinat ya
  da bu slotta tanımlı olmayan bir profil **uca hiç gitmiyor**; sebep
  kullanıcının kadrajı hâlâ ekrandayken tek cümlede söyleniyor.

> **Bu ikinci bir doğruluk kaynağı DEĞİL.** Kontrol kasıtlı olarak sunucunun
> **alt kümesi**: burada geçen bir yük sunucuda reddedilebilir (kiracı sınırı,
> bilinmeyen varlık, `If-Match`), ama tersi olmamalı. Sunucu yetkili.

---

## 4. Kaydetme akışının uçtan uca sınanması — sözleşmeye göre

Görev "sahte uçla değil, sözleşmeye göre" diyordu. Uygulanan yöntem:
kurallar sunucunun **kendi kaynağından** okundu, panelde birebir yazıldı ve
**yazımın kaynakla eşleştiği ayrıca testle ölçülüyor**.

| Kural | Sunucudaki yeri | Panelde ölçen test |
|---|---|---|
| 0-1 dışı **reddedilir**, kelepçelenmez | `envelope.py::require_unit` | `0-1 DIŞI yük REDDEDİLİR`, `aralık dışı yük … UÇA GİTMEDEN durur` |
| `focal_x`/`focal_y` birlikte | `api/crop.py::save_intent` | `validateIntentPayload` |
| `method ∈ {manual, smartcrop, center}` | `api/media_crop.py::INTENT_METHODS` | `\`method\` yalnız manual\|smartcrop\|center` |
| `overrides[].profile` slotun profili olmalı | `api/crop.py::_parse_overrides` | `overrides[].profile YANLIŞSA reddedilir` |
| aynı profil iki kez olamaz | aynı yer | aynı test |
| kutu sıfır alanlı / dışarı taşan olamaz | `_parse_overrides`, `_parse_safe_area` | `validateIntentPayload` + zoom taraması |

Ayrıca `cropSafeArea.test.js` **kaynak metnini okuyup** doğruluyor:
`require_unit` gövdesinde `min(`/`max(` **belirmediği** (koordinatta kelepçeleme
başlarsa test kırmızıya döner), `1e-6` toleranslı taşma kontrolünün yerinde
olduğu, `safe_top/right/bottom/left` diye bir alanın **hiç bulunmadığı**,
`SMARTCROP_CONFIDENCE_THRESHOLD`ün panelin sayısıyla aynı olduğu ve
`calibrated: bool = False` varsayılanının durduğu.

**Ölçülen üç kabul:**

1. **Geçerli yük kabul edilir** — `payloadIssues` boş, `saveAvailable` true, uç
   tam bir kez çağrılıyor, `focal_x/y` 0-1'de, `method` Select'te.
   Yakınlaştırma taramasında 7 zoom seviyesinin **hepsinde** yük temiz.
2. **0-1 dışı yük reddedilir** — `focal_x = 1.4` verildiğinde `saveAvailable`
   false, `save()` **`rejects`** ve **uç hiç çağrılmıyor** (`cagrildi === 0`).
   Kelepçelenmiyor: sunucunun gerekçesi korunuyor — 1,4 biraz taşmış bir kadraj
   değil, çağıranın piksel gönderdiğinin kanıtı.
3. **`overrides[].profile` yanlışsa reddedilir** — `slot_key` gönderme
   (panelin eski hatası), profil adı hiç olmaması ve aynı profilin iki kez
   gelmesi ayrı ayrı reddediliyor; gerçek profil adı (`cover_16x9_1000`)
   geçiyor. Stüdyonun kendi ürettiği override satırlarının slotun **gerçek**
   profilleri olduğu da ölçülüyor.

---

## 5. i18n — yeni metinler nerede duruyor ve neden

`src/i18n/locales/*.js` bu görevde **başka bir ajanın dosyası** (yasak liste).
Yeni sekiz metin bu yüzden `useI18n({ messages })` ile **bileşen kapsamında**
tanımlandı; vue-i18n 11.4'ün yerel kapsamı eksik anahtarları köke düşürüyor
(`fallbackRoot`), yani mevcut `cropStudio.*` anahtarları aynen çalışıyor.
Dördü de yazıldı: **tr, en, ru, ar**.

Ölçüm anahtarın nerede tanımlandığına bakmıyor — **ekranda ham anahtarın
görünmediğini** ölçüyor. `CropPolicyNotice` dört dilde ayrı ayrı SSR ile
render ediliyor ve çıktıda `cropStudio.warn.` dizgesi aranıyor; vue-i18n
çözemediği anahtarı olduğu gibi bastığı için bu gerçek bir kapı, eksik çeviri
sessizce geçemiyor.

> **Devir notu:** locale dosyalarının sahibi bu sekiz anahtarı kalıcı yere
> taşımak isterse bileşenlerden `messages` bloğunu silmek yeterli — anahtar
> yolları (`cropStudio.warn.safeBand`, `cropStudio.warn.safeBandActive`,
> `cropStudio.warn.suggestionUncalibrated`, `cropStudio.preview.serverNone`,
> `cropStudio.preview.serverHas`, `cropStudio.preview.safeBand`,
> `cropStudio.save.contract`, `cropStudio.suggest.unmeasured`,
> `cropStudio.suggest.fellBack`) zaten kök şemayla uyumlu.

---

## 6. Dokunulan dosyalar

| Dosya | Satır | Ne değişti |
|---|---|---|
| `src/composables/useCropStudio.js` | 660 | `safeArea`, `savePayload.safe_area`, `payloadIssues`, `validateIntentPayload`, `INTENT_METHODS`, öneri künyesi, `save()` sözleşme kapısı |
| `src/lib/media/crop/cropWarnings.js` | 228 | `SAFE_BAND`, `safeBandFor`, `focalInWindow`, 3 yeni uyarı |
| `src/lib/media/crop/focusSuggest.js` | 223 | `THRESHOLD_CALIBRATED`, `REASON`, `SOURCE`, `fromServerSuggestion`, `olcemedim` |
| `src/lib/media/crop/cropIntentApi.js` | 66 | `safe_area` taşınması, `suggestCropFocal` |
| `src/components/media/crop/CropStudioModal.vue` | 511 | sunucu önerisi + yedek, `renditions`/`band` geçişi, sözleşme ve öneri notları |
| `src/components/media/crop/CropPreviewStrip.vue` | 369 | kart başına türev durumu, güvenli alan bandı |
| `src/components/media/crop/CropPolicyNotice.vue` | 186 | yeni uyarıların dört dilde metni |
| `src/composables/__tests__/cropStudio.test.js` | 795 | +14 test (sözleşme, güvenli alan, sunucu paritesi) |
| `src/lib/media/crop/__tests__/cropPolicy.test.js` | 270 | uyarı kümesi 8 → 11 |
| `src/lib/media/crop/__tests__/cropSafeArea.test.js` | 202 | **yeni** — 12 test, kaynağa bağlılık |
| `src/components/media/__tests__/cropStudioA11y.test.js` | 416 | +3 test, i18n kapsamı dört dile çıktı |

**Dokunulmayanlar (yasak liste):** `router/index.js`, `data/navigation.js`,
`i18n/locales/*`, `CropCanvas.vue`, `CropHandles.vue`, `CropToolbar.vue`,
`useCropHistory.js`, `lib/media/crop/geometry.js`, `scripts/sync-crop-geometry.mjs`,
`components/media/simulator/**`, `components/media/upload/**`, `tradehub_core`,
`docker/`.

`cropIntentApi.js` ve `slotProfiles.js` yasak listede değil ve başka bir ajana
atanmamış; ilki kaydetme yolunun taşıyıcısı olduğu için düzenlendi, ikincisi
yalnız **okundu**.

---

## 7. Açık kalanlar

1. **`< 16 ms` bütçesi ÖLÇÜLMEDİ** — hedef, sonuç değil. Tarayıcı gerekiyor.
2. **smartcrop eşiği kalibre değil.** Artık gizlenmiyor ama kalibre de
   edilmedi; T-041'den devralınan not aynen geçerli.
3. **`get_intent` hâlâ kullanılmıyor.** Stüdyo yazıyor, açılışta kayıtlı niyeti
   geri yüklemiyor. Uç var ve testli (rapor 37 §8.3'te de açık).
4. **`previewed_placements` gönderilmiyor** — T-114'ün işi.
5. **`If-Match` iyimser kilidi kullanılmıyor.** Uç destekliyor (412); panel
   göndermiyor, yani "son yazan kazanır". Tek kullanıcılı editörde kabul
   edilebilir, çok kullanıcılı olunca gerekir.
6. **`safe_area` ile `overrideRect` birlikte gönderildiğinde** sunucu 1.
   seviyeyi (override) seçiyor ve güvenli alan o profil için etkisiz kalıyor —
   zincirin doğru davranışı, ama arayüz bunu kullanıcıya söylemiyor.
7. `Media Rendition` boş olduğu için **kart başına türev rozetinin dolu hâli
   yalnız testte görüldü**, canlı veriyle görülmedi.
