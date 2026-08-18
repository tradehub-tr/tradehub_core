# Faz 10 — Crop Studio · T-101…T-105 uygulama planı

**Durum:** T-100 (geometri) TAMAM ve ölçüldü. T-101…T-105 PLANLANDI, kod yazılmadı.
**Tarih:** 2026-08-18 · **Depo:** `tradehub_core` (branch `ahmet`)

---

## 0. T-100 nerede bitti — ölçülmüş sonuç

| Çıktı | Yol | Durum |
|---|---|---|
| Python geometri | `tradehub_core/media/pipeline/core/crop_geometry.py` | 4 çekirdek + 3 yardımcı fonksiyon |
| TypeScript ikizi | `tradehub_core/media/pipeline/core/crop_geometry.ts` | `tsc 5.9.3 --strict` temiz, `--erasableSyntaxOnly` temiz |
| Test vektörleri | `tests/fixtures/crop_vectors.json` | **592 vektör** (584 değer + 8 hata vakası) |
| Testler | `tests/test_crop_geometry.py` | **37 test**, yerelde ve konteynerde geçiyor |
| Vektör üreteci | `tests/tools/gen_crop_vectors.py` | bağımsız referans uygulama |
| TS parite koşucusu | `tests/tools/run_ts_vectors.ts` | node ile koşar |

**Ölçülen parite rakamları** (test çıktısından, uydurma değil):

```
[vektör]      584 vektör · en büyük sapma = 0.0 px
[TS parite]   584 vektör + 8 hata vakası · uyuşmazlık = 0 · en büyük sapma = 0 px
[çapraz]      crop.py ↔ crop_geometry.py en büyük sapma = 1.818989e-12 px
[çapraz-kutu] 800 örnek · 1 px yuvarlama farkı olan = 0
[oran]        3652 örnek · en büyük bağıl oran sapması = 2.070e-16
```

T-100'ün kabul kriteri "<= 0,5 px sapma"ydı. Gerçekleşen sapma **0,0 px** — yani
TypeScript ve Python yalnız yakın değil, aynı IEEE-754 double'ı üretiyor. Bu bir
tesadüf değil, tasarım kararı: iki dosyada işlem sırası, sıkıştırma zinciri ve
yuvarlama ifadesi (`floor(v + 0.5)`) birebir aynı yazıldı.

> Not: konteynerde (Python 3.11) 37 testin 36'sı geçti, TS parite testi
> **atlandı** — konteynerde `node` yok. Test bunu "geçti" diye değil,
> `skipped: node bulunamadı — TS paritesi ÖLÇÜLMEDİ` diye raporluyor. Parite
> ölçümü yerelde/CI'da node olan bir adımda koşmalıdır.

### Fonksiyon sözleşmesi (iki dilde aynı isim)

| Fonksiyon | Sorumluluk |
|---|---|
| `cropWindow(sw, sh, base, targetAR, focalX, focalY)` | Taban bölge içinde hedef orana uyan **en büyük** pencereyi odakta merkezle, kenara sıkıştır |
| `clampWindow(win, bounds, keepRatio?)` | Pencereyi sınırların içine hapset. `keepRatio` en-boy kilidi açıkken **zorunlu** |
| `ratioFit(w, h, targetAR, mode)` | `inside` (contain) / `outside` (cover) orana oturtma |
| `zoomBase(sw, sh, zoom, cx, cy)` | Zoom + pan merkezinden görünür taban bölge |
| `zoomFromBase(sw, sh, base)` | `zoomBase`'in tersi — kaydırıcıyı senkronlar |
| `focalFromWindow(win, sw, sh)` | Pencereden odak noktasını geri oku — **kalıcılaştırılan şey budur** |
| `roundWindow(win, sw?, sh?)` | Tam piksel kutusu `[left, top, w, h]` (PIL uyumlu) |

### Üç koordinat uzayı — karıştırılırsa sessiz hata

Bu, Crop Studio'daki en olası hata sınıfıdır ve tek savunma disiplindir:

| Uzay | Birim | Nerede | Kim sahibi |
|---|---|---|---|
| **Kaynak pikseli** | px, kaynağın tam çözünürlüğü | `crop_geometry.*` girdi/çıktısı | geometri |
| **Ekran pikseli** | px, `<canvas>`/CSS, DPR çarpanlı | fare olayları, tutamak isabeti | bileşen |
| **Normalize 0-1** | oransız | kaydedilen niyet (`focal_x`, override) | `crop.py` (INV-10) |

**Kural:** geometri fonksiyonlarına ekran pikseli GİRMEZ. Bileşen fareyi ekran
pikselinden kaynak pikseline çevirir, geometriyi çağırır, sonucu tekrar ekrana
çevirir. Kaydederken `focalFromWindow` ile normalize uzaya çıkar.

`crop.py` (T-041) **yeniden yazılmadı**. O, kadrajın nereden başlayacağını
(5 seviyeli öncelik zinciri) çözer; `crop_geometry` kullanıcının onu nasıl
taşıyacağını. `CaprazTutarlilikTesti` ikisinin aynı pencerede buluştuğunu
1500 rastgele girdide doğruluyor.

---

## 1. Politika gerçeği — Crop Studio aslında kaç profil için gerekli

9 slot politikasındaki **34 profil** tarandı (`tradehub_core/media/pipeline/policy/slots/*.json`):

| fit | height tanımlı | adet | kırpma? |
|---|---|---|---|
| `cover` | evet | **4** | **EVET — hedef oran var** |
| `cover` | hayır | 12 | hayır (yalnız genişlik ölçekleme) |
| `pad` | evet | 10 | hayır (letterbox) |
| `pad` | hayır | 5 | hayır |
| `contain` | hayır | 3 | hayır |

Kırpma gerektiren 4 profilin tamamı:

| Slot | Boyut | Gerçek oran |
|---|---|---|
| `company.cover_video` poster_1280 | 1280×720 | 16:9 (tam) |
| `company.cover_video` thumb_192 | 192×144 | 4:3 (tam) |
| `company.cover_image` cover_16x9_1000 | 1000×563 | **87:49** (16:9 değil) |
| `company.cover_video` poster_854 | 854×480 | **89:50** (16:9 değil) |

### Bulgu 1 — "16:9" düğmesi yanlış kadraj üretir

`1000×563` oranı 1,77619…; gerçek 16:9 ise 1,77778. Kullanıcıya "16:9" yazan bir
düğme gösterip `16/9` ile kırparsak, render 1000×563'e ölçeklerken kadrajı
yeniden kırpar ve kullanıcının hizaladığı kenar kayar. Fark küçük (~0,9 px), ama
kenara yaslanmış bir logoda görünür.

**Karar:** Crop Studio hedef oranı **asla ondan bağımsız bir isimden** almaz;
`width/height` profilinden hesaplar (`1000/563`). Etiket "16:9" olabilir, sayı
olamaz. Bu, `crop.py::parse_aspect_ratio`'nun `aspect_ratio_value` alanını
`aspect_ratio` metninden önce okumasıyla uyumludur.

### Bulgu 2 — 12 profil `cover` ama hedef oran yok

`cover` + `height: null`, "kırp" demekle "kırpma" demek arasında kalmış bir
durum. `crop.py` bunu `target_ratio=None` (serbest) sayar ve taban bölgeyi aynen
döndürür — davranış tanımlı, ama politikanın niyeti belirsiz. **Bu bir Faz 2
politika açığıdır, T-101…T-105 kapsamında ÇÖZÜLMEZ**; Crop Studio bu profiller
için oran kilidi sunmaz ve "bu profil kırpılmıyor" rozeti gösterir.

### Kapsam sonucu

Crop Studio bugün **yalnız `company.*` slotları** için gerçek iş yapar.
`product.image` (ölçüm: %48,6 uyumsuz, 4.812 görselin çoğunluğu) `pad`/`contain`
olduğu için kırpılmaz — oradaki uyumsuzluk kırpmayla değil, çözünürlük/format
ile çözülür. **Crop Studio'yu `product.image` uyumsuzluğunun çözümü olarak
sunmak yanlış olur.**

---

## 2. Nerede yaşayacak

**Admin panel** (`admin-panel/frontend`, Vue 3.5 `<script setup>` + Pinia 2
setup store + Tailwind 4). Storefront'ta kırpma arayüzü yok ve olmayacak.

Mevcut durum (okundu, uydurulmadı):

- `src/lib/upload-ui/facades/ImagePicker.ts:4` — *"Cropper.js opsiyonel — şu an
  basit önizleme + upload. Aspect ratio bilgi olarak kullanılır (caller kendisi
  crop UI eklerse, dosya değişmeden önce çağırabilir)."*
  **Bu, planlanmış bağlantı noktasıdır.** Crop Studio o "caller"dır.
- `src/components/media/` altında 15 bileşen var, **hiçbiri kırpma yapmıyor**
  (`grep -ri crop src/` → tek isabet yukarıdaki yorum).
- `src/composables/useMediaOptimize.js`, `useSellerMedia.js`, `useDropzone.js`
  mevcut — yeniden yazılmayacak, sarılacak.

### `crop_geometry.ts` admin panele nasıl girer

Dosya `tradehub_core` deposunda yaşar (tek doğruluk kaynağı orası). Panel onu
**kopyalamaz** — kopya, ayrışmanın garantisidir. İki seçenek:

1. **Build adımı** — `admin-panel` build'i dosyayı `src/lib/media/` altına
   senkronlar; senkron scripti kaynak hash'ini yazar, CI hash uyuşmazlığında düşer.
2. **npm workspace / git submodule** — daha temiz, ama İstoç'ta bugün ikisi de
   kurulu değil.

**Öneri: (1)**, çünkü bugünkü depo yapısını değiştirmiyor. **KARAR VERİLMEDİ** —
T-101 başlarken netleşmeli. Hangisi seçilirse seçilsin, `run_ts_vectors.ts`
panel tarafında da koşmalıdır; parite ölçümü tek depoda kalırsa yarısı ölçülmemiş
olur.

---

## 3. T-101 — Tuval, 8 tutamak, gövde sürükleme, zoom/pan

### Bileşenler

```
CropStudioModal.vue        kabuk: slot/profil seçimi, kaydet/vazgeç, kısayollar
  CropCanvas.vue           <canvas> — görsel + kadraj + karartma + ızgara
  CropHandles.vue          8 tutamak + gövde isabet alanı (DOM, canvas değil)
  CropToolbar.vue          oran kilidi, zoom kaydırıcısı, undo/redo, sıfırla
  CropPreviewStrip.vue     T-104
  CropPolicyNotice.vue     T-105
useCropStudio.js           durum + geçmiş + geometri çağrıları (composable)
```

**Tutamaklar neden DOM, çizim değil:** klavye erişimi (`tabindex`, `role="slider"`),
isabet alanı büyütme ve odak halkası bedavaya gelir. Canvas'a çizilen tutamağın
erişilebilirliği sıfırdan yazılır. Görsel ve kadraj karartması canvas'ta kalır.

### Etkileşim → geometri eşlemesi

| Jest | Hesap |
|---|---|
| Gövde sürükleme | `win.x += dx; win.y += dy` → `clampWindow(win, base)` |
| Köşe tutamağı (4) | karşı köşe sabit; yeni dikdörtgen → oran kilitliyse `ratioFit(..., inside)` → `clampWindow(..., base, keepRatio)` |
| Kenar tutamağı (4) | tek eksen; oran kilitliyse diğer eksen `ratioFit`'ten türer |
| Tekerlek / pinch | `zoom` değişir → `zoomBase(...)` → `cropWindow(...)` yeniden |
| Pan (boşlukta sürükleme) | `centerX/centerY` değişir → `zoomBase(...)` |

**Değişmez:** her jest sonunda pencere `clampWindow`'dan geçer. Tutamak
mantığında ayrıca sınır kontrolü YAZILMAZ — iki yerde sınır kontrolü, ikisinin
ayrışması demektir. `test_crop_geometry.py::OzellikTesti` bu tek kapıyı 4.000
girdide doğruluyor.

**Minimum pencere:** `MIN_EDGE_PX = 1.0` geometri tarafında; UI ayrıca **ekranda**
24 px'in altına inen tutamağı gizler (isabet alanı çakışır). Bu bir UI eşiği,
geometri eşiği değil — karıştırma.

### Kabul kriterleri (T-101)

- [ ] 8 tutamak + gövde, fare ve dokunmatikle çalışıyor (Pointer Events, tek yol)
- [ ] Pencere hiçbir jestte taban bölgeden taşmıyor (fuzz: 500 rastgele jest dizisi)
- [ ] Zoom 1…16 arası, `zoomFromBase` ile kaydırıcı senkron
- [ ] DPR ≥ 2 ekranda tutamak isabeti kayıyor mu — **ölçülecek**
- [ ] `prefers-reduced-motion` altında zoom animasyonu kapalı

---

## 4. T-102 — En-boy kilidi ve odak sürükleme

### En-boy kilidi

Kilit açık: `targetAR = null`, `ratioFit` kutuyu değiştirmez, `clampWindow`
`keepRatio=false`.
Kilit kapalı (profile bağlı): `targetAR = profil.width / profil.height`
(**Bulgu 1**: isimden değil, sayıdan).

Kritik: kilitliyken `clampWindow(win, bounds, keepRatio=true)` çağrılmalı.
`keepRatio=false` ile çağrılırsa kenarlar bağımsız kırpılır ve 1:1 kilitli
kullanıcı 1,03:1 kadraj alır — sessizce. Bu tam olarak `clampWindow`'un
`keepRatio` parametresinin var olma sebebidir.

### Odak sürükleme

Odak noktası ayrı bir tutamaktır (artı imleci), pencereden bağımsız sürüklenir.
İkisi arasındaki ilişki tek yönlü değildir ve bu bir tasarım kararıdır:

- **Odak sürüklenirse** → `cropWindow(...)` yeniden çalışır, pencere odağa
  göre kayar (kenar sıkıştırmalı).
- **Pencere sürüklenirse** → odak `focalFromWindow(win)` ile pencerenin
  merkezine taşınır.

İkincisi neden merkez: kenar sıkıştırma devredeyken **birden çok odak aynı
pencereyi verir** (odak köşenin dışına çıksa da pencere köşede kalır). Merkez,
bu küme içinde tek kararlı seçimdir; başka bir seçim gidiş-dönüşte kadrajı
kaydırırdı. `TersFonksiyonTesti::test_focal_gidis_donus` 1000 girdide
doğruluyor: pencere → odak → pencere aynı yere düşüyor.

### Kalıcılaştırma

Kaydedilen şey **pencere değil, odaktır** (normalize `focal_x`/`focal_y`) —
INV-10. Sebep: aynı görselin master'ı, arşiv kopyası ve satıcının yeniden
yüklediği hâli farklı piksel boyutlarında; piksel kadraj küçültülmüş kaynakta
kayar, normalize odak kaymaz.

**İstisna:** kullanıcı bir profil için oranı bozacak biçimde elle kadraj çizdiyse
`crop.py`'nin **1. seviyesi** (`override`) kullanılır — `Media Crop Override`
satırı, normalize dikdörtgen. Odak tek başına o kadrajı ifade edemez.

### Kabul kriterleri (T-102)

- [ ] Kilit açık/kapalı geçişinde pencere sıçramıyor (kilit kapanınca `ratioFit`
      merkezi koruyarak uygulanır)
- [ ] Odak → pencere → odak gidiş-dönüşü ≤ 0,5 px
- [ ] Kilitli sürüklemede oran sapması ≤ %0,5 (`crop.py::RATIO_TOLERANCE`)
- [ ] Override yazıldığında `crop.py` zincirinin 1. seviyesi kazanıyor

---

## 5. T-103 — Undo/redo (≥ 20 adım)

### Model

Komut deseni değil, **anlık görüntü yığını**. Durum küçük (7 sayı + slot/profil
anahtarı ≈ 100 bayt); 50 adım ≈ 5 KB. Komut deseninin ters-işlem karmaşıklığını
bu boyut için ödemeye değmez.

```js
// useCropHistory.js
const gecmis = ref([ilkDurum])   // anlık görüntüler
const imlec  = ref(0)
const AZAMI  = 50                // T-103 asgarisi 20; 50 seçildi, bkz. aşağıda
```

Anlık görüntü alanları: `zoom, centerX, centerY, focalX, focalY, lockedAR,
overrideRect|null`. **Pencere saklanmaz** — türetilmiş değerdir; saklanırsa
durumla tutarsızlaşabilir.

### Sürükleme sırasında yığın şişmez

Ham `pointermove` saniyede 120+ olay üretir; her birini yığına atmak 20 adımlık
geçmişi yarım saniyede tüketir. **Kural: yığına yazma `pointerup`'ta, jest başına
bir kez.** Sürükleme sırasında yalnız "canlı durum" güncellenir.

Klavye ok tuşları için **coalescing**: aynı yöndeki ardışık ok basışları 400 ms
içinde tek adımda birleşir (metin editörlerinin davranışı). Aksi hâlde 20 adım,
20 piksellik bir nudge'a gider.

### Kabul kriterleri (T-103)

- [ ] En az 20 adım geri (hedef 50)
- [ ] Redo, yeni bir değişiklikten sonra temizleniyor
- [ ] Bir sürükleme jesti = tam olarak 1 adım
- [ ] `Ctrl/Cmd+Z` / `Ctrl/Cmd+Shift+Z` — mevcut `useMediaShortcuts.js` ile
      çakışma taraması yapılacak (**ÖLÇÜLMEDİ**)
- [ ] Slot/profil değişince geçmiş sıfırlanır (farklı kadraj bağlamı)

---

## 6. T-104 — Canlı çoklu önizleme (< 16 ms)

Kullanıcı bir kadraj çizerken o slotun **tüm profilleri** aynı anda küçük
önizlemelerde güncellenmeli.

### Bütçe neye harcanıyor

Hedef 16 ms = 60 fps'de bir kare. Kritik gerçek: **her önizleme için ayrı
`drawImage` çağrısı yapılırsa** ölçek maliyeti profil sayısıyla çarpılır.
`company.cover_image` 5 profil, `brand.logo` 5 profil, `product.image` 8 profil.

**Tasarım:**

1. Kaynak görsel **bir kez** `createImageBitmap()` ile çözülür ve en büyük
   önizleme boyutunun ~2 katında bir ara bitmap'e ölçeklenir (`imageBitmap`
   yeniden kullanılır). 72,71 MP'lik bir kaynağı her karede ölçeklemek 16 ms'e
   sığmaz — ölçüm: p99 = 29,21 MP, MAX = 72,71 MP, 179 dosya > 20 MP.
2. Her karede önizlemeler **ara bitmap'ten** çizilir, orijinalden değil.
3. Çizim `requestAnimationFrame`'de toplanır; bir karede birden çok
   `pointermove` gelirse yalnız sonuncusu çizilir (coalescing).
4. Önizlemeler görünür alandaysa çizilir (`IntersectionObserver`).

`pad`/`contain` profilleri için önizleme kırpmaz, letterbox gösterir — kullanıcı
"neden kırpılmıyor" sorusunu sormadan görmelidir.

### Ölçüm — henüz yapılmadı

**< 16 ms hedefi ÖLÇÜLMEDİ.** Bu bir hedeftir, bir sonuç değil. T-104 kapanmadan
önce şunlar ölçülmeli:

- [ ] 72,71 MP kaynakta ilk `createImageBitmap` süresi (muhtemelen 16 ms'i
      kat kat aşar → yükleme sırasında bir kez, sürükleme sırasında değil)
- [ ] 8 profilde kare başına toplam çizim süresi, DPR 1 ve 2'de
- [ ] Bellek: ara bitmap + 8 önizleme canvas'ı
- [ ] Ölçüm ortamı: Chrome DevTools Performance, gerçek fixture'lar
      (`tests/fixtures/media/` — 34 görsel)

Ölçüm 16 ms'i aşarsa geri çekilme sırası: (a) sürükleme sırasında yalnız aktif
profili canlı güncelle, diğerlerini `pointerup`'ta; (b) önizleme çözünürlüğünü
düşür; (c) OffscreenCanvas + worker.

---

## 7. T-105 — Otomatik odak önerisi ve politika uyarıları

### Otomatik odak önerisi

`crop.py` zincirinin **4. seviyesi** (`smartcrop`) zaten tanımlı: öneri
`suggested_*` alanlarından okunur, `confidence >= eşik` ise kullanılır ve
`approved_by_user=0` iken UI'da **"öneri" rozeti** gösterilir
(`CropWindow.is_suggestion`).

**Bugünkü gerçek:** saliency modeli YOK. `crop.py`'de yazılı:
`SMARTCROP_CONFIDENCE_THRESHOLD = 0.5` ve başına açıkça *"ÖLÇÜLMEDİ — kalibrasyon
yapılmadı, saliency modeli henüz yok (Faz 3 mimarisinde AI Worker (L5))"*
düşülmüş. Bu plan o notu değiştirmiyor.

T-105 kapsamında **model yazılmaz**. Yazılacak olan:

1. **Arayüz** — "Otomatik öner" düğmesi, öneriyi pencereye uygular, "öneri"
   rozetini gösterir, kullanıcı dokununca rozet düşer (`approved_by_user=1`).
2. **Ucuz taban öneri (fallback)** — model gelene kadar: kenar-enerjisi ağırlık
   merkezi (Sobel benzeri, küçültülmüş bitmap üzerinde). Yüz/nesne tespiti
   DEĞİL, ve öyle sunulmayacak. Rozet metni "otomatik öneri", "yüz bulundu" değil.
3. **Güven değeri gerçekten hesaplanmalı** — sabit `0.9` yazmak, eşiği anlamsız
   kılar. Enerji dağılımının tepe/ortalama oranı gibi ölçülebilir bir sayı.

**Bu bir yer tutucudur ve öyle işaretlenmelidir.** AI Worker (L5) geldiğinde
arayüz değişmez, kaynak değişir — `crop.py` zaten `suggested_*` alanlarını
okuyor.

### Politika uyarıları

Uyarılar `tradehub_core/media/pipeline/policy/engine.py` ve slot politikalarından türer;
Crop Studio **kendi kural setini yazmaz** (rule 8 — sarar, yeniden yazmaz).

| Uyarı | Kaynak | Şiddet |
|---|---|---|
| Kırpma sonrası kısa kenar profil genişliğinin altında | profil `width`/`height` | **engelle** |
| Kaynak > 20 MP (179 dosya) | ölçüm + `content_rules.json` | uyar |
| CMYK kaynak (38 dosya) | `probe.py` mode | uyar — renk kayar |
| Alfa kanalı var, hedef format JPEG (597 dosya) | `probe.py` + profil `formats` | uyar |
| Bu profil kırpılmıyor (`pad`/`contain`, 30/34 profil) | slot politikası | bilgi |
| Hedef oran profil boyutundan türetildi, etiketten değil | **Bulgu 1** | bilgi |
| Slot uyumsuzluğu (`product.image` %48,6) | `docs/reports/` | uyar |

**"Engelle" yalnız tek durumda:** kırpma sonucu profilin gerektirdiği piksel
sayısını üretemiyorsa. Kalanı uyarıdır — kullanıcıyı kendi görselinden kilitlemek,
uyumsuz bir görselden kötüdür.

### Kabul kriterleri (T-105)

- [ ] Öneri düğmesi çalışıyor, rozet doğru düşüyor
- [ ] Güven değeri hesaplanıyor (sabit değil)
- [ ] 7 uyarının her biri için bir fixture testi
- [ ] Uyarı metinleri Türkçe, `vue-i18n` üzerinden
- [ ] Hiçbir uyarı `crop_geometry` içinde YAZILMIYOR (geometri politikasızdır)

---

## 8. Durum sözleşmesi

```ts
interface CropStudioState {
  // kaynak
  sourceW: number; sourceH: number;      // kaynak pikseli
  // görünüm
  zoom: number;                          // 1…16
  centerX: number; centerY: number;      // 0-1 normalize (pan)
  // niyet — KAYDEDİLEN kısım
  focalX: number; focalY: number;        // 0-1 normalize (INV-10)
  lockedAR: number | null;               // profil w/h'den, etiketten DEĞİL
  overrideRect: Rect | null;             // normalize; crop.py 1. seviye
  // türetilmiş — SAKLANMAZ
  // base = zoomBase(...); win = cropWindow(...)
}
```

Kaydetme yükü `crop.py`'nin `Media Crop Intent` sözleşmesine yazılır:
`focal_x`, `focal_y`, `safe_*`, `overrides[]`, `method`, `confidence`,
`approved_by_user`. **Yeni alan icat edilmez.**

---

## 9. Erişilebilirlik ve klavye

| Tuş | İş |
|---|---|
| `Tab` | tutamaklar arasında dolaş (8 + gövde + odak) |
| Ok tuşları | 1 px (kaynak pikseli), `Shift` ile 10 px |
| `+` / `-` | zoom |
| `L` | oran kilidi |
| `Ctrl/Cmd+Z`, `Ctrl/Cmd+Shift+Z` | undo / redo |
| `Esc` | vazgeç (değişiklik varsa onay sor) |
| `Enter` | uygula |

Her tutamak `role="slider"` + `aria-label` + `aria-valuetext` (canlı kadraj
boyutu). Ekran okuyucu için `aria-live="polite"` bir bölge kadraj boyutunu ve
politika uyarılarını duyurur. Kontrast: Tailwind 4 `@theme` token'ları —
**v4'te JS config yok**, `tailwind.config.js` yazılmayacak.

---

## 10. Test planı

| Katman | Araç | Kapsam |
|---|---|---|
| Geometri (T-100) | `unittest` + node koşucusu | **TAMAM** — 37 test, 592 vektör |
| Composable mantığı | `vitest` | geçmiş yığını, jest → geometri eşlemesi |
| Bileşen | `vitest` + Testing Library | tutamak sürükleme, klavye |
| Görsel regresyon | Storybook (kurulu) | 9 slot × 3 kadraj |
| Performans | DevTools Performance | T-104 bütçesi — **ÖLÇÜLECEK** |
| Parite | `run_ts_vectors.ts` | panel build'inde de koşmalı |

**CI'da zorunlu:** `run_ts_vectors.ts` node'lu bir adımda koşmalı. Yalnız Python
testleri koşarsa TS ayrışması sessizce geçer — Python kendi vektörlerini geçmeye
devam eder.

---

## 11. Riskler ve ÖLÇÜLMEMİŞ noktalar

| # | Konu | Durum |
|---|---|---|
| 1 | `< 16 ms` önizleme bütçesi | **ÖLÇÜLMEDİ** — hedef, sonuç değil |
| 2 | 72,71 MP kaynakta tarayıcı bellek davranışı | **ÖLÇÜLMEDİ** |
| 3 | `ZOOM_MAX = 16` kullanılabilirlik | **ÖLÇÜLMEDİ** — kalibre edilirse .py ve .ts BİRLİKTE |
| 4 | `SMARTCROP_CONFIDENCE_THRESHOLD = 0.5` | **ÖLÇÜLMEDİ** (T-041'den devralındı) |
| 5 | `useMediaShortcuts.js` kısayol çakışması | **TARANMADI** |
| 6 | `crop_geometry.ts` panele nasıl girecek | **KARAR VERİLMEDİ** (§2) |
| 7 | 12 profil `cover` ama hedef oransız | **Faz 2 politika açığı**, T-101…105 dışı |
| 8 | DPR ≥ 2'de tutamak isabeti | **ÖLÇÜLMEDİ** |
| 9 | Konteynerde node yok → parite testi orada atlanıyor | bilinen, raporlanıyor |

### Bu plan neyi çözmüyor

- `product.image` %48,6 slot uyumsuzluğu — `pad`/`contain`, kırpma konusu değil
- 1.166 yetim disk dosyası — Faz 10 dışı
- `th_media_width` 0/2853 (%0) doldurulmamış çözünürlük metadatası — Faz 10 dışı
- srcset/sizes eksikliği (31 görselin 0'ında) — teslim katmanı, kırpma değil
