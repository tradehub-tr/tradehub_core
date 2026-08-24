# T-022 — Şirket kapak videosu standardı

> **Güncel karar — 2026-08-23.** Makine kaynağı
> `tradehub_core/media/pipeline/policy/slots/company-cover-video.json` şemaya
> uyumludur; `standard_status=fixed`, açık soru sayısı 0 ve ffmpeg/ffprobe
> çalışma ortamı doğrulanmıştır. Aşağıdaki numaralı açık kararlar 2026-08-17/18
> karar günlüğüdür; çözümleri politika dosyasının `resolution_notes` alanında
> kayıtlıdır. `status=draft` yalnız Faz 3 rollout durumudur.

**Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2` · **Doküman fazı:** KİLİT görev
**Makine-okunur eşi:** `tradehub_core/media/pipeline/policy/slots/company-cover-video.json`

Bu belge şirket (mağaza) profilindeki **kapak videosu** slotunu tanımlar. Amaç
yeniden tasarım değil: bugün kodda çalışan davranışı ölçüp yazmak, eksiği sayıya
bağlamak. Kod tabanında hâlihazırda çalışan her mekanizma **kaynağıyla** anlatılır;
yeni getirilen her kural "BUGÜN YOK" etiketiyle işaretlenir.

> **Bu belge kod değiştirmez.** Yalnız kural koyar. Uygulama görevleri Faz 3+.

> **GÜNCELLEME — 2026-08-18 (canlı ölçüm).** Docker açıldı ve `docs/reports/08-canli-olcum.md`
> §7'de **23 video dosyası** tarandı (5'i `ffprobe` ile okunabildi). Sonuçlar
> **§10.0**'a işlendi: §6.12'nin "koşulsuz rendition" istisnası **ölçümle
> doğrulandı**, §6.1/§6.2 eşikleri değişmedi ama mevcut içeriğin geçişi için
> **yeni bir karar (K8)** doğdu. §11'in D-maddeleri hâlâ **açık** — bu ölçüm slot
> eşlemesi yapmadı, yani ölçülen 23 dosyanın kaçının kapak videosu olduğu
> **bilinmiyor**.

---

## 0. Yöntem — her sayı nereden geldi

| Sayı türü | Nasıl elde edildi |
|---|---|
| CSS kutu ölçüleri (px) | Kaynak koddaki Tailwind utility sınıfları okundu, Tailwind v4 varsayılan ölçeğiyle px'e çevrildi (`1rem = 16px`; breakpoint'ler `sm 640 / md 768 / lg 1024 / xl 1280`). Aritmetik §2'de açık yazıldı. **Tarayıcıda computed style ölçülmedi.** |
| Kodlayıcı eşikleri | `tradehub_core/media/transcode.py` ve `admin-panel/frontend/src/lib/media/compress.video.js` sabitleri doğrudan okundu (satır numaraları verildi) |
| Yükleme tavanları | `tradehub_core/media/upload_policy.py:67-76`, `admin-panel/.../StorefrontEdit.vue:1007`, `seller_gallery_image.json` `description` |
| Bitrate / bayt bütçeleri | Bu belgede **türetildi**; her türetmenin aritmetiği yanında yazılı (ör. `1.0 Mbps × 10 s = 10 Mbit = 1.250 KB`) |
| Kod boşlukları ("BUGÜN YOK") | `grep` ile sıfır sonuç: `<track`, `kind="captions"`, `.vtt`, `hls`, `HLS` → `tradehubfront/src` + `admin-panel/frontend/src` içinde **0 eşleşme** |

**Ölçülemeyen:** Docker kapalı; üretim veritabanı ve canlı siteye erişim yok.
Gerçek kapak videosu envanteri (kaç mağazada var, gerçek süre/çözünürlük/bitrate
dağılımı), gerçek DPR/viewport dağılımı, gerçek `th_media_video_status` dağılımı
ve tarayıcıda hesaplanmış kutu ölçüleri bu belgede **YOK** → §11.

---

## 1. Slot kimliği — kapak videosu bugün nerede yaşıyor

Kapak videosu **tek bir alan değil**; üç ayrı yol var ve **ikisi birbirine
bağlanmıyor.** T-001 bu slotu "⚠️ KISMEN" işaretlemişti (`docs/reports/00-upload-slot-envanteri.md:222`);
aşağısı o satırın tam açılımı.

### 1.A — ÇALIŞAN yol: `Seller Gallery Image` → StoreHeader oynatıcısı

| Katman | Kaynak |
|---|---|
| Depolama | `Admin Seller Profile.gallery_images` → child doctype `Seller Gallery Image` (`tradehub_core/tradehub_core/doctype/seller_gallery_image/seller_gallery_image.json`) |
| Alanlar | `category` (Select: `overview` / `360_view` / `production` / `quality_control`, reqd), `media_type` (Select: `image` / `video`, reqd), `image` (Attach Image), `video_url` (Attach), `poster_image` (Attach Image), `caption` (Data), `sort_order` (Int) |
| API | `tradehub_core/api/seller.py:590` → `_build_media_groups()` (`:769-828`); kategori listesi `_MEDIA_CATEGORIES` (`:760-765`) |
| Sıralama | `order_by="sort_order asc, idx asc"` (`api/seller.py:795`), sonra **video başa alınır** (`:823-824`) → kapak videosu ana medya olur |
| Frontend veri | `tradehubfront/src/alpine/seller.ts:339-348` `get mediaGroups()` — `count > 0` olan gruplar süzülür |
| Oynatıcı | `tradehubfront/src/components/seller/StoreHeader.ts:203-418` |

Yani **"şirket kapak videosu" = `media_groups[0].items[0]` ve `media_type == "video"`.**
Ayrı bir "kapak" alanı yok; kapak, sıralamanın türevi.

### 1.B — SAHİPSİZ yol: `factory_video_url`

`admin-panel/frontend/src/views/seller/StorefrontEdit.vue:501-546` ayrı bir
"Fabrika Videosu" yükleme kartı sunuyor; `:1014` dosyayı yükler, `:1228`
kaydeder.

**Doğrulanmış boşluk:** `factory_video_url` bu repoda
- `tradehub_core/**/*.py` içinde **0 eşleşme**,
- `tradehub_core/**/*.json` (doctype) içinde **0 eşleşme**,
- `tradehubfront/src/**` içinde **0 eşleşme**.

Kaydetme çağrısı `tr_tradehub.api.v1.seller.update_storefront`
(`StorefrontEdit.vue:1223`) — **başka bir app**. Yani satıcı panelden bir kapak
videosu yükleyip kaydediyor, storefront o alanı hiç okumuyor. Panelin gösterdiği
kapak ile vitrinin gösterdiği kapak **aynı dosya değil.**

> **Standart kararı:** Kanonik kapak videosu slotu **1.A** yoludur
> (`slot_key = seller.cover_video`). `factory_video_url` bir **eş anlamlı
> (alias)** olarak kabul edilir; yeni yükleme kabul etmez, mevcut değeri
> `Seller Gallery Image` (`category=overview`, `media_type=video`, `sort_order=0`)
> satırına taşınır. Taşıma görevi Faz 3.

### 1.C — Ürün videosu (kapak DEĞİL, karıştırılmasın)

`components/seller/CompanyProfile.ts:930-1010` "Videolar" sekmesi
`Listing.video_url` alanlarını listeler; YouTube/Vimeo embed veya `<video>`.
Bu **ürün** videosudur, bu standardın kapsamı dışında. Ancak §9'daki iki
bulgunun kaynağı orada.

---

## 2. Ölçülen kutu — masaüstü / tablet / mobil

### 2.1 Kutuyu üreten sınıf zinciri

| Katman | Sınıf | Kaynak |
|---|---|---|
| Sayfa kabı | `max-w-[1200px] mx-auto px-4 lg:px-8 py-6` | `StoreHeader.ts:46` |
| Beyaz kart iç boşluğu | `px-4 sm:px-6 lg:px-10 py-6 lg:py-8 lg:pb-10` | `StoreHeader.ts:128` |
| Satır | `flex flex-col-reverse lg:flex-row gap-6 lg:gap-8` | `StoreHeader.ts:129` |
| Video kolonu | `w-full lg:w-[500px] shrink-0` | `StoreHeader.ts:203` |
| Medya kutusu | `relative w-full rounded-sm overflow-hidden bg-gray-900 aspect-video` | `StoreHeader.ts:297` |
| `<video>` | `w-full h-full object-cover` | `StoreHeader.ts:304` |

### 2.2 Aritmetik (Tailwind varsayılan ölçeği, `1rem = 16px`)

`px-4 = 16px` · `px-6 = 24px` · `px-8 = 32px` · `px-10 = 40px` · `gap-8 = 32px`

| Viewport | Kap genişliği | Kart içi genişlik | Video kutusu (CSS px) | DPR2 cihaz px |
|---|---|---|---|---|
| 360 (küçük mobil) | 360 − 2×16 = **328** | 328 − 2×16 = **296** | **296 × 166,5** | 592 × 333 |
| 390 (iPhone 14 sınıfı) | 390 − 32 = **358** | 358 − 32 = **326** | **326 × 183,4** | 652 × 367 |
| 640 (`sm`) | 640 − 32 = **608** | 608 − 2×24 = **560** | **560 × 315** | 1120 × 630 |
| 768 (`md`, tablet dikey) | 768 − 32 = **736** | 736 − 48 = **688** | **688 × 387** | 1376 × 774 |
| **1023 (lg'nin bir altı)** | 1023 − 32 = **991** | 991 − 48 = **943** | **943 × 530,4** ← en geniş | **1886 × 1061** |
| 1024 (`lg`) | 1024 − 2×32 = **960** | 960 − 2×40 = **880** | **500 × 281,25** (sabit kolon) | 1000 × 563 |
| ≥1200 | **1200** | 1200 − 64 − 80 = **1056** | **500 × 281,25** | 1000 × 563 |

**Ölçümün en önemli sonucu:** Kutu **masaüstünde değil, 1023 px viewport'ta en
geniş** (943 CSS px). `lg:flex-row` devreye girer girmez kolon 500 px'e sabitlenir
ve viewport ne kadar büyürse büyüsün büyümez (`shrink-0`, `lg:w-[500px]`).
Yani "masaüstü için yüksek çözünürlük" sezgisi bu slotta yanlıştır; kritik nokta
tablet bandıdır.

### 2.3 Oran ve `object-fit`

- Kutu **her breakpoint'te 16:9** (`aspect-video`, `StoreHeader.ts:297`). Mobilde
  farklı bir oran **yok**.
- `object-fit: cover` (`StoreHeader.ts:304`). Master 16:9 ise `cover` ile
  `contain` aynı sonucu verir, **kırpma olmaz**. Master 16:9 değilse **sessizce
  kırpılır** ve yükleyene hiçbir uyarı gösterilmez (bu, T-001 §7-B2'nin video
  karşılığıdır).
- Boş/başarısız durumda kutu `bg-gray-900` ile siyah kalır (`:297`).

### 2.4 Mobilde video ÜSTTE

`flex-col-reverse lg:flex-row` (`StoreHeader.ts:129`): mobil/tablet DOM sırası
tersine çevrilir → **video, istatistik bloğunun ÜSTÜNDE** görünür. Yani kapak
videosu mobilde katlamanın (fold) üstünde, LCP adayı konumdadır. Pasif veri
bütçesi (§6) bu yüzden sert tutuldu.

### 2.5 Küçük resim (thumbnail) kutusu

- Grid: `grid-template-columns: repeat(auto-fill, minmax(96px, 1fr))` (`StoreHeader.ts:378`)
- Hücre: `aspect-[4/3]` (`StoreHeader.ts:381`) → en az **96 × 72 CSS px** (DPR2: 192 × 144)
- Dikkat: ana kutu **16:9**, küçük resim **4:3**. Aynı poster iki farklı orana
  `object-cover` ile basılıyor → küçük resimde poster'ın sol/sağından **%25
  kırpılır** (16/9 ÷ 4/3 = 1,333 → 1 − 1/1,333 = %25).

---

## 3. Üstüne binen katmanlar ve güvenli alan (safe area)

Kutunun üstünde üç şey var; ölçüleri kodda sabit:

| Katman | Ölçü | Kaynak |
|---|---|---|
| Kontrol çubuğu | `absolute bottom-0 inset-x-0 px-3 py-2.5` + `w-5 h-5` ikonlar → **≈ 40 px yükseklik** (10 + 20 + 10) | `StoreHeader.ts:329`, `:333-334` |
| Çubuk gradyanı | `linear-gradient(to top, rgba(0,0,0,0.7) 0%, rgba(0,0,0,0.3) 70%, transparent 100%)` — kutunun **tamamına** yayılır | `StoreHeader.ts:330` |
| Ortadaki oynat düğmesi | `w-14 h-14` = **56 × 56 px**, kutunun tam ortası | `StoreHeader.ts:321` |

### 3.1 Güvenli alanın yüzdeye çevrilmesi

| Viewport | Kutu yüksekliği | 40 px çubuk = | 56 px düğme = |
|---|---|---|---|
| ≥1024 (500 × 281,25) | 281,25 px | **%14,2** | %19,9 |
| 768 (688 × 387) | 387 px | %10,3 | %14,5 |
| **360 (296 × 166,5)** | 166,5 px | **%24,0** ← en kötü | **%33,6** |

**KARAR — title-safe alan.** Videonun içine gömülü (burned-in) her metin
aşağıdaki dikdörtgenin içinde kalmalı:

```
sol/sağ  : %10 iç boşluk       (2 × 10 = %20 kenar payı)
üst      : %6 iç boşluk
alt      : %26 iç boşluk       (mobil en kötü %24 + %2 emniyet)
```

→ 1280 × 720 master üzerinde kullanılabilir alan:
genişlik `1280 × (1 − 0,10 − 0,10) = 1024 px`,
yükseklik `720 × (1 − 0,06 − 0,26) = 489,6 ≈ 490 px`
→ **1024 × 490 px**, sol kenardan 128 px, üstten 43 px içeride.

Ek olarak **merkezdeki 72 × 72 px** (56 px düğme + 8 px pay) dairesel bölge de
kritik metin taşımamalı — oynat düğmesi orada duruyor ve videonun ilk karesi
poster olarak da kullanılıyor (§7).

### 3.2 Logo gömme YASAK

`StoreHeader.ts` ve `section-registry.ts` boyunca mantıksal yön özellikleri
kullanılıyor (`start-2` / `end-2` / `ms-1` / `pe-0`; ör. `section-registry.ts:185,188`)
— yani arayüz RTL'de otomatik aynalanıyor. **Videoya gömülü bir logo aynalanamaz.**
Kararname: kapak videosuna logo/marka **gömülmez**; mağaza logosu zaten videonun
yanında ayrı `<img>` olarak render ediliyor (`components/seller/CompanyInfo.ts:47`,
120 px genişlik). Gömülü logo taşıyan yüklemeler reddedilmez ama panelde uyarı
gösterilir (`cover_video_burned_logo_warning`).

---

## 4. Bugünkü oynatma davranışı — kodda ne var

| Özellik | Bugünkü kod | Kaynak |
|---|---|---|
| Otomatik oynatma | **YOK.** `<video>` üzerinde `autoplay` özniteliği bulunmuyor | `StoreHeader.ts:301-309` |
| Ses | `muted` özniteliği **sabit yazılı**; Alpine state `muted: true` ile başlar | `StoreHeader.ts:308`, `:207` |
| Ses açma | `toggleMute()` — kullanıcı el ile açabilir | `StoreHeader.ts:255-260`, düğme `:347-350` |
| `playsinline` | **VAR** (ana oynatıcı ve küçük resim videoları) | `StoreHeader.ts:308`, `:403` |
| `loop` | **YOK** — bitince `@ended="playing = false"` ile oynat düğmesi geri gelir | `StoreHeader.ts:307` |
| `preload` | `metadata` | `StoreHeader.ts:308` |
| `poster` | `:poster="current.poster || ''"` → `Seller Gallery Image.poster_image`; **boşsa poster hiç yok** | `StoreHeader.ts:303` |
| Poster yedeği | Yalnız **küçük resim** ızgarasında: `:src="item.src + '#t=0.5'"` + `<video preload="metadata">` (tarayıcı 0,5 s'ye seek eder). Ana oynatıcıda bu yedek **yok** | `StoreHeader.ts:401-405` |
| Seek | El yapımı ilerleme çubuğu, `@click="seek($event)"` | `StoreHeader.ts:261-266`, `:339` |
| Tam ekran | `v.requestFullscreen()` | `StoreHeader.ts:274-277` |
| Altyazı | **YOK.** Her iki frontend'de `<track` / `kind="captions"` / `.vtt` → 0 eşleşme | grep |
| HLS / DASH | **YOK.** `hls` / `HLS` → 0 eşleşme | grep |
| `prefers-reduced-motion` | Global CSS kuralı animasyon/geçiş sürelerini sıfırlıyor ama **`<video>` oynatmasına etkisi yok** | `tradehubfront/src/style.css:757-765` |

---

## 5. Bugünkü işleme hattı — üç eşik, üç ayrı sayı

### 5.1 İstemci (satıcı paneli, mediabunny)

`admin-panel/frontend/src/lib/media/compress.video.js`

| Sabit | Değer | Satır |
|---|---|---|
| `MAX_BOYUT_BYTES` | 100 MB üstü istemcide işlenmez → sunucuya | `:24` |
| `MAX_SURE_SANIYE` | 180 s üstü verimsiz video istemcide işlenmez | `:25` |
| `HEDEF_GENISLIK` | 1280 | `:26` |
| `VERIMLI_BITRATE` | **2.000.000 (2,0 Mbps)** — altındaysa dokunma | `:29` |
| Çıktı | VP9/WebM; tarayıcı VP9 encode edemezse H.264/MP4 | `:66-100` |
| Son koruma | Çıktı orijinalden küçük değilse orijinali kullan | `:88` |

### 5.2 Sunucu (ffmpeg, RQ `long` kuyruğu)

`tradehub_core/media/transcode.py`

| Sabit / davranış | Değer | Satır |
|---|---|---|
| `NEEDS_TRANSCODE_MAX_WIDTH` | 1280 | `:66` |
| `NEEDS_TRANSCODE_MAX_BITRATE` | **2.500.000 (2,5 Mbps)** | `:67` |
| Eşik kuralı | `genişlik > 1280 VEYA bitrate > 2,5 Mbps → transcode` | `:75-76` |
| ffprobe okunamazsa | **Güvenli tarafa: `True`** (emin değilsek transcode et) | `:96-103` |
| ffmpeg komutu | `nice -n 10 ffmpeg -y -i SRC -vf scale='min(1280,iw)':-2 -c:v libvpx-vp9 -b:v 0 -crf 32 -c:a libopus DST` | `:235-248` |
| Çıktı yerleştirme | `os.replace(dst_path, src_path)` — **orijinalin ÜZERİNE**, `file_url` sabit | `:252` |
| ffmpeg timeout | 1700 s | `:44` |
| Kuyruk timeout | 1800 s | `:157` |
| Durum alanı | `File.th_media_video_status` ∈ `processing` / `ready` / `failed` | `:48-50` |

### 5.3 Yükleme tavanları — dört ayrı sayı, üçü çelişiyor

| Kaynak | Değer | Satır |
|---|---|---|
| Sunucu politikası (video) | **200 MB** | `media/upload_policy.py:69` |
| Doctype alan açıklaması | "MP4/WebM, maks **10MB**" | `seller_gallery_image.json` → `video_url.description` |
| Panel `factory_video_url` istemci kontrolü | **10 MB** | `StorefrontEdit.vue:1007` |
| İstemci sıkıştırma kapısı | **100 MB** üstü işlenmez (ret değil, pas) | `compress.video.js:24` |

Aynı slot için üç farklı tavan yazılı. Bu standardın §6'sı bu üç sayıyı **tek
sayıya** indirir.

### 5.4 Video için ÖLÇÜ METADATASI YOK

`media/metadata.py:159-196` `ensure_dimensions()` boyutu `engine.probe()` ile
okur; `engine.probe()` yalnız **PIL/Pillow** kullanır (`media/engine.py:79-93`).
PIL video açmaz → `readable=False` → `{}` döner. Sonuç: **hiçbir videonun
genişlik/yükseklik/süresi veritabanında tutulmuyor.** `File.th_media_width` /
`th_media_height` (`patches/v15_9_15_media_metadata_fields.py:69,85`) video
satırlarında boş kalır. Süre için ayrılmış bir alan hiç yok.

Bu, süre/oran/çözünürlük kuralının **bugün zorlanamamasının teknik nedenidir** —
kural yazmak yeterli değil, `th_media_duration_ms` + video için `ffprobe`
tabanlı `ensure_dimensions` dalı gerekiyor (Faz 3 görevi).

---

## 6. STANDART — kararlar ve sayıları

Aşağıdaki her satır bir karardır. "Türetme" sütunu sayının nereden geldiğini
gösterir. Hiçbiri belirsiz bırakılmamıştır.

### 6.1 Oran ve çözünürlük

| Kural | Değer | Türetme |
|---|---|---|
| Kabul edilen oran | **16:9**, tolerans **±%1** | Kutu her breakpoint'te `aspect-video` (`StoreHeader.ts:297`). Tolerans, 1920×1080 → 1920×1090 gibi kodlayıcı yuvarlamalarını geçirir |
| Mobil alternatif oran | **YOK — bilinçli karar** | Kutu mobilde de 16:9 (§2.2). Dikey (9:16 / 4:5) master `object-cover` altında %56 yatay kırpılırdı. Mobil alternatif **oran değil, ÇÖZÜNÜRLÜK tier'ı** olarak verilir (aşağı) |
| Yükleme min çözünürlük | **1280 × 720** | Masaüstü kutusu 500 CSS px, DPR2 → 1000 cihaz px. 1280 ≥ 1000 ✔. Bunun altı masaüstünde upscale |
| Yükleme maks çözünürlük | **3840 × 2160** | Kabul edilir ama daima küçültülür; tavsiye 1920 × 1080. 4K üstü `cover_video_resolution_too_high` |
| Yükleme kare hızı | 24 / 25 / 30 fps kabul; 50 / 60 fps **30 fps'e düşürülür** | 60 fps aynı kalitede ~%80 fazla bit ister; fabrika turu / konuşan kafa içeriğinde görsel kazanç yok |
| Teslim tier'ları | **2 tier:** `720p` (1280 × 720) ve `480p` (854 × 480) | 720p mevcut `scale='min(1280,iw)'` hedefiyle aynı (`transcode.py:242`) → hattı bölmez. 480p, 560 CSS px'lik `sm` kutusunu DPR1'de tam, DPR2'de %76 doldurur |
| 1080p tier | **BU SÜRÜMDE YOK** | 1023 px viewport'ta kutu 943 CSS px; DPR2'de 1886 cihaz px isteniyor, 1280 ile 1,47× upscale oluyor. 1080p'ye çıkmak bitrate tavanını 2,5 → 4,5 Mbps'e (**+%80 bayt**) taşır. Ölçülmemiş bir viewport bandı için bu bedel ödenmiyor → §10-K1 (onay bekleyen), §11-D3 (ölçüm) |

### 6.2 Süre

| Kural | Değer | Türetme |
|---|---|---|
| Mod `story` (varsayılan) min süre | **6 s** | Önizleme klibi 6 s (§6.7). Master, kendi önizlemesinden kısa olamaz |
| Mod `story` maks süre | **60 s** | Teslim bayt tavanıyla birlikte türetildi: 60 s × 1,6 Mbps hedef ortalama = 96 Mbit = **12 MB** (§6.4). 60 s aynı zamanda HLS eşiğinin altında kalmayı garantiler (§6.8) |
| Mod `ambient` (opt-in) süre | **3–8 s** | Sessiz, döngülü klip. 8 s × 0,7 Mbps = 5,6 Mbit = 700 KB — pasif+aktif bütçenin (§6.6) içinde kalır |
| Süre ölçümü | `ffprobe -show_entries format=duration` | `needs_transcode` zaten ffprobe çağırıyor (`transcode.py:83-90`); aynı çağrıya `format=duration` eklenir |

### 6.3 Yükleme bayt tavanı

| Kural | Değer | Türetme |
|---|---|---|
| Bu slot için maks yükleme baytı | **80 MB** | 60 s × 10 Mbps (cömert 1080p master tavanı) = 600 Mbit = 75 MB → 80 MB'a yuvarlandı |
| Küresel tavanla ilişki | 80 MB < 200 MB (`upload_policy.py:69`) → çelişki yok, slot daha dar |
| Doctype açıklaması "10MB" | **GEÇERSİZ, düzeltilmeli** | 60 s'lik 1080p H.264 master 10 MB'a sığmaz (10 MB / 60 s = 1,33 Mbps → 1080p'de görünür bozulma). Bugün panel bu yüzden meşru kapak videolarını sessizce reddediyor (`StorefrontEdit.vue:1007`) |
| Panel istemci tavanı | **80 MB'a yükseltilmeli** | Sunucuyla aynı sayı; istemci sunucudan farklı sayı tutmamalı (T-001 §L2 ilkesi) |

### 6.4 Teslim bitrate tavanı ve dosya boyutu kapısı

`-b:v 0 -crf 32` bugün **kısıtsız kalite-bazlı** encode (`transcode.py:244-245`).
Yani tepe bitrate tavansız. Kapak videosu katlamanın üstünde durduğu için tavan
zorunlu hâle getirilir.

| Tier | Codec | CRF | `-maxrate` | `-bufsize` | Hedef ortalama | Teslim dosya kapısı |
|---|---|---|---|---|---|---|
| `720p` WebM | VP9 / Opus | 32 | **2500k** | 5000k | ≤ **1,6 Mbps** | ≤ **12 MB** |
| `720p` MP4 (yedek) | H.264 High / AAC-LC | CRF 23 | 2800k | 5600k | ≤ 1,9 Mbps | ≤ 14 MB |
| `480p` WebM | VP9 / Opus | 34 | **1000k** | 2000k | ≤ **0,7 Mbps** | ≤ **5 MB** |
| `480p` MP4 (yedek) | H.264 High / AAC-LC | CRF 25 | 1200k | 2400k | ≤ 0,85 Mbps | ≤ 6 MB |

- CRF 32 / VP9 mevcut hattan **korunuyor** (`transcode.py:245`); bu standart onu
  değiştirmiyor, üstüne `-maxrate/-bufsize` ekliyor.
- Kapı aşılırsa: CRF **+2** ile yeniden encode, **en çok 2 deneme**, sonra
  `cover_video_too_heavy` ile ret. (Bugün böyle bir kapı yok — çıktı ne olursa
  olsun `os.replace` ile yazılıyor, `transcode.py:252`.)
- 12 MB türetmesi: 60 s × 1,6 Mbps = 96 Mbit = 12 MB. 5 MB türetmesi:
  60 s × 0,7 Mbps = 42 Mbit ≈ 5,25 MB → 5 MB.
- **Anahtar kare aralığı: 2 s** (`-g 60` @ 30 fps). Gerekçe: el yapımı seek
  çubuğu (`StoreHeader.ts:261-266`) rastgele noktaya atlıyor; 2 s'den seyrek
  anahtar kare seek'i gözle görülür geciktirir. Ayrıca ileride HLS
  segmentlemesi (§6.8) 2 s'nin katına ihtiyaç duyar.
- **WebM index başta olmalı:** `-cues_to_front 1` (webm muxer). Aksi hâlde
  `preload="metadata"` ve seek için tarayıcı dosyanın **sonuna** range isteği
  atar → mobilde ek gecikme. (Bugün bu bayrak yok, `transcode.py:235-248`.)

### 6.5 MP4 yedeği — ZORUNLU (bugün YOK, ve bugünkü davranış hatalı)

Bugünkü hat **yalnız WebM üretiyor** ve çıktıyı **orijinalin üzerine** yazıyor:

```
dst_path = f"{src_path}.transcoding.webm"     # transcode.py:230
...
os.replace(dst_path, src_path)                # transcode.py:252
```

Sonuç: satıcı `kapak.mp4` yükler, sunucu VP9/WebM üretir ve **baytları
`kapak.mp4` adresine yazar**. `file_url` bilinçli olarak sabit tutuluyor
(`transcode.py:29-31` — referanslar kırılmasın diye), fakat:

1. nginx `Content-Type`'ı uzantıdan türetir → **WebM baytları `video/mp4` olarak
   servis edilir.**
2. `<source type="video/mp4">` yazmak bu durumda **yalan** olur; tip uyuşmazlığında
   tarayıcı kaynağı atlayabilir.
3. WebM konteynerini desteklemeyen eski Safari sürümlerinde kapak videosu **hiç
   oynamaz** ve yedek yol yoktur.

**KARAR:** Kapak slotu için **yerinde değiştirme (in-place replace) yasak.**
Renditionlar ayrı adreslere yazılır ve slot bir manifest tutar:

```
<video poster="…/cover_poster.webp" playsinline preload="metadata" muted>
  <source src="…/cover_720.webm" type="video/webm; codecs=vp9,opus">
  <source src="…/cover_720.mp4"  type="video/mp4;  codecs=avc1.640028,mp4a.40.2">
</video>
```

480p tier `media` sorgusu ya da istemci seçimiyle verilir (§6.6).
Toplam 4 dosya + 1 poster + 1 önizleme klibi = **6 nesne / kapak.**
Tipik 30 s kapak için depolama ≈ 6 + 7 + 2,6 + 3 + 0,12 + 0,4 ≈ **19 MB**;
60 s en kötü hâlde ≈ **37,5 MB**. Kota etkisi `docs/reports/06-depolama-maliyet.md`
ile çapraz okunmalı.

### 6.6 Ses politikası

| Kural | Değer | Gerekçe |
|---|---|---|
| Varsayılan davranış | **Otomatik oynatma YOK** — kullanıcı dokunarak başlatır | Bugünkü kod böyle (`StoreHeader.ts:301-309`, `autoplay` yok). Rule: çalışanı bozma |
| Otomatik oynatma açılırsa | `muted` + `playsinline` **ZORUNLU**, istisnasız | `muted`+`playsinline` olmadan mobil tarayıcılar oynatmayı reddeder; ayrıca sesli otomatik oynatma B2B vitrininde saldırgan |
| `muted` başlangıç durumu | `true` (korunur) | `StoreHeader.ts:207-208`, `:308` |
| Kullanıcı sesi açabilir | **Evet**, `toggleMute()` korunur | `StoreHeader.ts:255-260` |
| Mod `ambient` | Ses **akışı tamamen çıkarılır** (`-an`) | Döngüde çalan ses dayanılmaz; ayrıca sessiz dosya %8-12 daha küçük |
| Opus bitrate — 720p | **`-b:a 96k`** stereo | Bugün `-c:a libopus` **bitrate belirtmeden** yazılı (`transcode.py:246`) → kodlayıcı varsayılanına bağlı; ffmpeg sürümü değişince sessizce değişir. Sabitlemek zorunlu |
| Opus bitrate — 480p | **`-b:a 64k`** mono (`-ac 1`) | Mobil veri bütçesi (§6.7) içinde kalması için |
| Ses seviyesi normalizasyonu | **EBU R128:** entegre **−16 LUFS**, tepe **−1 dBTP** (`-af loudnorm=I=-16:TP=-1:LRA=11`) | Farklı satıcıların videoları arasında ses zıplamasın. −16 LUFS web/streaming yaygın hedefidir (standarda atıf, ölçüm değil) |

### 6.7 Mobil veri bütçesi

Bu slot mobilde katlamanın üstünde (§2.4), bu yüzden bütçe **iki parçalı**:

| Bütçe | Tavan | Türetme |
|---|---|---|
| **Pasif** (kullanıcı hiç dokunmadan) | **150 KB** | Poster WebP ≤ **120 KB** + konteyner metadata (`preload="metadata"`, cues başta) ≤ **30 KB** |
| **Aktif — ilk 10 saniye** | **1.250 KB** | 480p tier tavanı 1,0 Mbps × 10 s = 10 Mbit = 1.250 KB. Hedef ortalama (0,7 Mbps) ile tipik ≈ **875 KB** |
| En kötü toplam (dokunmadan sonra 10 s) | **1.400 KB** | 150 + 1.250 |

Uygulama kuralları:

- Mobil/tablet (`max-width: 1023px`) → **480p tier**. Masaüstü (`min-width: 1024px`)
  → 720p tier. Eşik 1024, `lg` breakpoint'iyle aynı (`StoreHeader.ts:203`).
- `navigator.connection.saveData === true` **veya** `effectiveType ∈ {slow-2g, 2g}`
  → `preload="none"`, yalnız poster. Pasif bütçe 150 → **120 KB**'a düşer.
- `preload="metadata"` korunur (bugünkü değer, `StoreHeader.ts:308`); `auto`
  **yasak** — pasif bütçeyi tek başına aşar.

### 6.8 HLS geçiş eşiği

Bugün HLS/DASH **hiç yok** (grep: 0 eşleşme). Karar: bu slot **progressive**
kalır. HLS şu üç koşuldan **biri** sağlanırsa zorunlu olur:

```
duration_s              >  60
max_rendition_bytes     >  12 MB
distinct_resolution_tiers > 2
```

Kapak slotu üç koşulu da **tanım gereği** sağlamaz (§6.2 60 s, §6.4 12 MB,
§6.1 iki tier) → **HLS bu slot için gereksiz.** Eşik, gelecekteki uzun-form
"şirket tanıtım filmi" slotu için buraya yazılıyor; o slot açıldığında HLS
(veya LL-HLS) ilk günden zorunludur.

Byte-range zorunluluğu: progressive teslim seek'in çalışması için
`Accept-Ranges: bytes` gerektirir → §11-D5'te doğrulama komutu var.

### 6.9 Poster seçim kuralı — "ilk anlamlı kare"

Bugün: `poster` yalnız satıcının el ile yüklediği `poster_image` alanından gelir
(`StoreHeader.ts:303`); boşsa **poster yok**, kutu siyah kalır (`bg-gray-900`,
`:297`). Otomatik poster üretimi hiçbir yerde yok (`grep poster|thumbnail` →
`media/*.py` içinde yalnız PIL `im.thumbnail` çağrıları, `engine.py:117,177`).

**KARAR — dört adımlı poster kuralı:**

1. **Satıcı override kazanır.** `Seller Gallery Image.poster_image` doluysa o
   kullanılır (mevcut davranış korunur).
2. **Boşsa sunucu üretir.** Arama penceresi
   `[0,5 s , min(5 s, süre × 0,25)]` — açılış siyahlığını (0-0,5 s) atlar,
   videonun ilk çeyreğinden çıkmaz.
   ```
   ffmpeg -ss 0.5 -t 4.5 -i cover_720.webm \
     -vf "thumbnail=n=120,scale=1280:-2" -frames:v 1 \
     -c:v libwebp -quality 78 cover_poster.webp
   ```
   ffmpeg'in `thumbnail` filtresi n kare içinden histogram uzaklığına göre **en
   temsili** olanı seçer — "anlamlı kare"nin uygulanabilir tanımı budur.
3. **Kalite kapısı.** Seçilen karenin ortalama parlaklığı `< %6` veya `> %94`
   ise (tam siyah/tam beyaz açılış) pencere `[süre × 0,25 , süre × 0,50]`
   aralığına kaydırılıp bir kez daha denenir. İkinci deneme de kapıya
   takılırsa poster üretilmez, `cover_video_poster_unresolved` ile satıcıdan
   el ile poster istenir.
4. **Poster çıktısı.** WebP, **1280 × 720**, hedef **≤ 120 KB**
   (q78 → aşarsa q70 → aşarsa q62; üçü de aşarsa 854 × 480'e düşülür).
   Pasif bütçenin (§6.7) ana kalemi bu 120 KB'dır.

**Küçük resim uyarısı:** Küçük resim ızgarası 4:3 (`StoreHeader.ts:381`); 16:9
poster orada %25 yatay kırpılacak (§2.5). Poster'ın anlamlı öznesi **merkez %75
genişlik** içinde kalmalı — bu, §3.1'deki %10 kenar payından daha sıkı olan
gerçek kısıttır.

**`#t=0.5` yedeği kaldırılmaz ama yeterli sayılmaz:** `StoreHeader.ts:402`
yalnız küçük resimde çalışıyor, ana oynatıcıda yok; ayrıca tam bir `<video>`
elemanı + metadata indirmesi demek — pasif bütçeye poster'dan pahalıya oturur.
Otomatik poster üretimi devreye girince bu yedek yolun tek işlevi eski
(migrate edilmemiş) satırlardır.

### 6.10 Loop

| Mod | `loop` | Gerekçe |
|---|---|---|
| `story` (varsayılan) | **KAPALI** | Ses taşıyan anlatı bir videonun döngüye girmesi rahatsız edici. Ayrıca bugünkü kodda `@ended="playing = false"` (`StoreHeader.ts:307`) bilinçli bir "bitti" durumu üretiyor — oynat düğmesi geri geliyor. `loop` bu durumu hiç oluşmayacak hâle getirir |
| `ambient` (opt-in, BUGÜN YOK) | **AÇIK** + `autoplay` + `muted` + `playsinline`, kontroller gizli | 3-8 s sessiz atmosfer klibi. `prefers-reduced-motion` altında **otomatik oynatma iptal**, poster + oynat düğmesi gösterilir (§8.2) |

### 6.11 Önizleme klibi

| Kural | Değer | Türetme |
|---|---|---|
| Süre | **6 s** | §6.2'deki min `story` süresinin kaynağı; kart üzerinde hover ile izlenecek en uzun makul aralık |
| Başlangıç noktası | Poster'ın seçildiği zaman damgası (§6.9-2) | Önizleme, kullanıcının poster'da gördüğü kareden başlar → görsel süreklilik |
| Çözünürlük / codec | 854 × 480 VP9 WebM (+ H.264 MP4 yedeği) | 480p tier ile aynı |
| Ses | **YOK** (`-an`) | Hover ile ses çalmak kabul edilemez |
| Döngü | AÇIK (hover süresince) | Ses yok, süre kısa → §6.10'daki gerekçe geçerli değil |
| Bayt tavanı | **≤ 400 KB** | 6 s × 500 kbps = 3 Mbit = 375 KB → 400 KB'a yuvarlandı |
| Nerede kullanılır | Mağaza kartı / arama sonucu / küçük resim hover; **kapak kutusunda kullanılmaz** | Kapak kutusunda tam video var |
| Bugünkü durum | **YOK** — hiçbir yerde önizleme klibi üretilmiyor veya oynatılmıyor | |

### 6.12 Transcode eşikleri — bu slot için DEĞİŞTİRİLİYOR

Genel kütüphane için mevcut koşullu eşikler (`transcode.py:66-67`, `:75-76`)
**korunur.** Gerekçesi kodda ölçümle yazılı: "100'lerce eşzamanlı yüklemede
kuyruğu boğar" (`transcode.py:14-16`). Buna dokunmuyoruz.

**Kapak slotu için istisna:** `needs_transcode()` sonucu ne olursa olsun
renditionlar **koşulsuz** üretilir.

| Gerekçe | Sayı |
|---|---|
| Kapak videosu **mağaza başına 1 dosya**, nadiren değişir → kuyruk riski yok | `_build_media_groups` başına en fazla 4 kategori × ilk video (`api/seller.py:760-765`) |
| Koşullu atlama kapak slotunda **poster üretimini de atlar** — poster hattı transcode hattının içinde | §6.9 |
| Koşullu atlama **MP4 yedeğini** ve **480p tier'ı** hiç üretmez → §6.5'teki Safari kırılganlığı sürer | §6.5 |

**Ayrıca giderilecek çelişki:** İstemci "zaten verimli" barı **2,0 Mbps**
(`compress.video.js:29`), sunucu barı **2,5 Mbps** (`transcode.py:67`). 1280 ×
720 @ 2,3 Mbps bir dosya:
- panelden geçerse istemci dönüştürür (2,3 > 2,0),
- istemci sıkıştırması olmayan bir yoldan (`upload_file` → global
  `after_insert` kancası, `transcode.py:167`) geçerse sunucu **atlar** (2,3 < 2,5).

Aynı dosya, giriş kapısına göre iki farklı sonuç alıyor. **Karar: iki sayı
2,0 Mbps'te birleştirilir** (dar olan kazanır; sunucu barı 2,5 → 2,0 iner).
Kapak slotunda bu zaten moot (koşulsuz), ama genel kütüphanede tutarlılık için
gerekli.

### 6.13 Slot doğrulama (L3) — reddedilecek durumlar ve hata kodları

`media/upload_policy.py` bugün **hiçbir slot için** piksel/oran/süre/adet
kontrolü yapmıyor (T-001 §L3: "Sistemde hiç yok"). Bu slotun L3 sözleşmesi:

| Kod | Koşul | `retryable` |
|---|---|---|
| `cover_video_aspect_invalid` | `abs(w/h − 16/9) / (16/9) > 0,01` | false |
| `cover_video_resolution_too_low` | `w < 1280` veya `h < 720` | false |
| `cover_video_resolution_too_high` | `w > 3840` veya `h > 2160` | false |
| `cover_video_too_short` | `story`: `duration < 6 s` · `ambient`: `< 3 s` | false |
| `cover_video_too_long` | `story`: `duration > 60 s` · `ambient`: `> 8 s` | false |
| `cover_video_too_large` | `bytes > 80 MB` | false |
| `cover_video_too_heavy` | Encode sonrası tier dosyası, 2 CRF denemesinden sonra hâlâ kapı üstünde | false |
| `cover_video_no_video_stream` | ffprobe video stream döndürmedi | false |
| `cover_video_poster_unresolved` | Otomatik poster iki denemede de parlaklık kapısını geçemedi | false |
| `cover_video_captions_required` | Ses akışı var, konuşma içeriyor, `.vtt` yok (§8.1) | false |
| `cover_video_transcode_failed` | ffmpeg hata verdi | **true** |
| `cover_video_burned_logo_warning` | (uyarı, ret değil) §3.2 | — |

Kod adlandırma deseni `upload_policy.Kod` dataclass'ıyla uyumlu
(`upload_policy.py:98-120`).

---

## 7. Özet karar tablosu (tek bakış)

| Alan | Karar |
|---|---|
| Oran | 16:9 ±%1 · mobil alternatif oran YOK |
| Min çözünürlük | 1280 × 720 |
| Maks çözünürlük | 3840 × 2160 (tavsiye 1920 × 1080) |
| Teslim tier'ları | 720p (1280×720) + 480p (854×480); 1080p yok |
| Min süre | `story` 6 s · `ambient` 3 s |
| Maks süre | `story` 60 s · `ambient` 8 s |
| Maks yükleme baytı | 80 MB |
| Teslim bitrate tavanı | 720p 2.500 kbps (hedef ort. 1.600) · 480p 1.000 kbps (hedef ort. 700) |
| Teslim dosya kapısı | 720p ≤ 12 MB · 480p ≤ 5 MB |
| Ses | Otomatik oynatma yok → ses serbest, `muted` başlangıç. Otomatik oynatmada `muted` ZORUNLU. `ambient`'te ses akışı yok |
| Ses bitrate | Opus 96k stereo (720p) / 64k mono (480p); loudnorm I=−16 TP=−1 |
| Loop | `story` kapalı · `ambient` açık |
| `playsinline` | Her zaman zorunlu (bugün var) |
| `preload` | `metadata`; Save-Data/2g'de `none`; `auto` yasak |
| Poster | Satıcı override → yoksa `thumbnail=n=120` @ [0,5 s, min(5 s, süre×0,25)]; WebP 1280×720 ≤ 120 KB |
| Önizleme klibi | 6 s, 854×480, sessiz, döngülü, ≤ 400 KB |
| HLS eşiği | süre > 60 s VEYA rendition > 12 MB VEYA tier > 2 → bu slotta hiçbiri, HLS yok |
| Pasif mobil bütçe | 150 KB (poster 120 + metadata 30) |
| İlk 10 s mobil tavanı | **1.250 KB** (en kötü toplam 1.400 KB) |
| VTT altyazı | Konuşma içeren `story` için ZORUNLU (§8.1) |
| `prefers-reduced-motion` | `ambient` otomatik oynatma iptal; `story` etkilenmez (§8.2) |
| Anahtar kare | 2 s (`-g 60` @ 30 fps) |
| Yerinde değiştirme | **Bu slotta YASAK** — renditionlar ayrı adres (§6.5) |

---

## 8. Erişilebilirlik

### 8.1 VTT altyazı — konuşma varsa ZORUNLU

**Bugünkü durum:** Her iki frontend'de `<track` / `kind="captions"` / `.vtt`
araması **0 sonuç** veriyor. Altyazı altyapısı yok, altyazı alanı yok, oynatıcıda
altyazı düğmesi yok.

**KARAR:**

| Durum | Altyazı |
|---|---|
| `story` + ses akışı var + **konuşma** içeriyor | **`.vtt` ZORUNLU.** Eksikse yayına alınmaz: `cover_video_captions_required` |
| `story` + ses akışı var + yalnız müzik/ortam sesi | `.vtt` zorunlu değil; bunun yerine `Seller Gallery Image.caption` (mevcut alan) **zorunlu** — videonun ne gösterdiğini anlatan metin |
| `story` + ses akışı yok | Altyazı zorunlu değil; `caption` zorunlu |
| `ambient` | Ses akışı tanım gereği yok → altyazı zorunlu değil; `caption` zorunlu |

Uygulama gereksinimleri (BUGÜN YOK, Faz 3):
- `Seller Gallery Image` içine `subtitles_vtt` (Attach) alanı; `.vtt` uzantısı
  `upload_policy.EXTENSIONS` (`upload_policy.py:57-65`) içinde **yok** → eklenmesi
  gerekiyor (`KIND_DOCUMENT` değil, yeni `KIND_CAPTION`, tavan **512 KB**).
- Oynatıcıya `<track kind="captions" srclang="tr" label="Türkçe" default>` +
  altyazı aç/kapat düğmesi (`StoreHeader.ts:329-355` kontrol çubuğuna).
- Dil: platform 4 dil taşıyor (`i18n/locales/` içinde `tr`, `en`, `ru`, `ar`
  görüldü). Zorunlu olan **yalnız videonun konuşma dili**; diğer diller opsiyonel.
- Altyazı, §3.1'deki alt %26 güvenli alanın **içine** düşer (tarayıcı altyazıyı
  alta yerleştirir) — bu yüzden videoya **gömülü altyazı yasak**: gömülü altyazı
  ile `<track>` altyazısı üst üste biner.

### 8.2 `prefers-reduced-motion`

**Bugünkü durum:** `tradehubfront/src/style.css:757-765` global kural
tüm `animation-duration` / `transition-duration` değerlerini `0.01ms`'ye çeker.
Bu **CSS animasyonlarını** durdurur; `<video>` oynatmasına **etkisi yoktur**.
`story` modu bugün kullanıcı başlatmalı olduğu için pratikte sorun yok.

**KARAR:**

| Mod | `prefers-reduced-motion: reduce` altında davranış |
|---|---|
| `story` | **Değişmez.** Kullanıcının kendi başlattığı oynatma kısıtlanmaz — WCAG 2.2 SC 2.2.2 yalnız otomatik hareketi hedefler |
| `ambient` | **Otomatik oynatma İPTAL.** Poster + ortadaki oynat düğmesi gösterilir; kullanıcı isterse başlatır. Döngü de kullanıcı başlattıysa devam eder |
| Önizleme klibi (hover) | **Oynatılmaz.** Poster gösterilir |
| Kapak kutusunun kendi CSS geçişleri | Global kural (`style.css:757-765`) zaten hâlleder |

Uygulama notu: **CSS bunu yapamaz.** Kontrol JS'te olmalı:
```js
const azHareket = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
if (mod === "ambient" && !azHareket) video.play();
```
`matchMedia` sonucu **oynatma anında** okunmalı, init'te önbelleğe alınmamalı —
kullanıcı işletim sistemi ayarını sekme açıkken değiştirebilir.

### 8.3 Bu slotta tespit edilen diğer erişilebilirlik boşlukları

| Bulgu | Kaynak | Neden sorun |
|---|---|---|
| Seek çubuğu klavyeyle kullanılamıyor | `StoreHeader.ts:339` — `<div>` + `@click`, `role`/`tabindex` yok | Klavye kullanıcısı videoda konum değiştiremiyor. Gerekli: `role="slider"` + `aria-valuenow/min/max` + `@keydown.arrow-left/right` |
| Oynat/duraklat etiketi değişmiyor | `StoreHeader.ts:332` — `aria-label="Oynat"` sabit | Ekran okuyucu duraklat durumunda da "Oynat" duyurur. `:aria-label="playing ? 'Duraklat' : 'Oynat'"` gerekli |
| Etiketler i18n dışında | `StoreHeader.ts:332,347,352` — `"Oynat"`, `"Sesi aç/kapat"`, `"Tam ekran"` düz Türkçe string | Dosyanın geri kalanı `t(...)` kullanıyor (ör. `:19`, `:58`); bu üç etiket 4 dilde çevrilmiyor |
| iOS'ta tam ekran çalışmıyor | `StoreHeader.ts:274-277` yalnız `v.requestFullscreen` kontrol ediyor | iOS Safari `<video>` için `webkitEnterFullscreen()` ister; bugün düğme iOS'ta sessizce hiçbir şey yapmıyor |
| Poster yoksa boş siyah kutu | `StoreHeader.ts:297,303` | Görsel bağlam yok; §6.9 otomatik poster bunu kapatır |

---

## 9. Bugünkü kodda doğrulanmış çelişkiler ve kırılganlıklar

Hepsi bu oturumda dosya okunarak doğrulandı. Hiçbiri bu görevde **düzeltilmedi**
(Kural 1: mevcut kod dosyaları değiştirilmez).

| # | Bulgu | Kanıt | Etki |
|---|---|---|---|
| **Ç1** | **Yerinde değiştirme MIME'ı yalanlıyor.** `.mp4` adresine VP9/WebM baytları yazılıyor | `transcode.py:230` + `:252` | nginx `video/mp4` servis eder; `<source type>` yazılamaz; WebM desteklemeyen tarayıcıda kapak hiç oynamaz |
| **Ç2** | **`factory_video_url` hiçbir yere bağlanmıyor.** Panel yükler, kaydeder, storefront okumaz | `StorefrontEdit.vue:1014,1228` → `tr_tradehub...update_storefront`; `tradehub_core` ve `tradehubfront` içinde 0 eşleşme | Satıcı kapak videosu yükledi sanıyor, vitrinde görünmüyor |
| **Ç3** | **Üç farklı boyut tavanı.** 200 MB (sunucu) / 10 MB (doctype açıklaması) / 10 MB (panel istemcisi) | `upload_policy.py:69`; `seller_gallery_image.json` `video_url.description`; `StorefrontEdit.vue:1007` | Meşru kapak videoları panelde sessizce reddediliyor |
| **Ç4** | **İstemci/sunucu "verimli" barı ayrışık.** 2,0 vs 2,5 Mbps | `compress.video.js:29` vs `transcode.py:67` | Aynı dosya giriş kapısına göre farklı işlenir (§6.12) |
| **Ç5** | **Video ölçü metadatası hiç yazılmıyor.** `ensure_dimensions` PIL'e bağlı | `metadata.py:180-186` → `engine.probe` `engine.py:79-93` | Süre/oran/çözünürlük kuralı bugün **zorlanamaz**; panel video için "—" gösterir |
| **Ç6** | **Skeleton ↔ gerçek kutu oran uyuşmazlığı → CLS.** Skeleton `lg:w-[500px] h-[300px]` (5:3), gerçek kutu `aspect-video` (16:9 → 281,25 px) | `StoreHeader.ts:39` vs `:297` | Yükleme bitince **18,75 px** dikey kayma (300 − 281,25) |
| **Ç7** | **Ana oynatıcıda poster yedeği yok.** `#t=0.5` hilesi yalnız küçük resimde | `StoreHeader.ts:303` vs `:402` | `poster_image` boş olan her kapak siyah kutu olarak açılıyor |
| **Ç8** | **Ana kutu 16:9, küçük resim 4:3.** Aynı poster iki orana `object-cover` | `StoreHeader.ts:297` vs `:381` | Küçük resimde %25 yatay kırpma, uyarı yok |
| **Ç9** | **Ürün videosu modalinde sesli otomatik oynatma.** `controls autoplay`, `muted` **yok** | `CompanyProfile.ts:1002` | Tarayıcı otomatik oynatmayı bloklar → kullanıcı boş oynatıcı görür. (Kapak slotu değil, ama aynı `<video>` deseni) |
| **Ç10** | **Opus bitrate sabitlenmemiş.** `-c:a libopus`, `-b:a` yok | `transcode.py:246` | ffmpeg sürümü değişirse çıktı ses bitrate'i sessizce değişir |
| **Ç11** | **WebM cue'ları başta değil.** `-cues_to_front` yok | `transcode.py:235-248` | `preload="metadata"` ve seek için dosya sonuna range isteği → mobilde ek RTT |
| **Ç12** | **Kategori enum'u iki yerde tekrar.** Doctype `options` ile `_MEDIA_CATEGORIES` ayrı yazılı | `seller_gallery_image.json` `category.options` vs `api/seller.py:760-765` | Biri değişirse `_build_media_groups` bilinmeyen kategoriyi sessizce `overview`'a düşürür (`api/seller.py:806-808`) |

---

## 10. PLATFORM YÖNETİCİSİ ONAYI BEKLEYEN KARARLAR

Aşağıdakiler teknik değil **iş/ürün** kararıdır. Her biri için önerim yazılı;
onay gelene kadar **parantez içindeki varsayılan** geçerlidir.

---

### 10.0 Ölçüm etkisi — 2026-08-18 (canlı stack)

`docs/reports/08-canli-olcum.md` §7, Docker açıkken **23 video dosyasını** taradı.
Bu bölüm o ölçümün bu belgedeki kararlara ne yaptığını kaydeder.

**Ölçümün kapsamı ve KAPSAMADIĞI — önce bu okunmalı:**

| Ne | Değer |
|---|---|
| `tabFile` içindeki video kaydı | **23** |
| `ffprobe` ile **okunabilen** | **5** (kalanı diskte yok ya da bozuk) |
| **ÖLÇÜLEMEDİ — slot eşlemesi** | Bu 23 dosyanın **kaçının kapak videosu** olduğu bilinmiyor. Rapor §4, "slot bazında dağılım"ı kapatılmayanlar arasında sayıyor. Aşağıdaki her sayı **tüm video kütüphanesi** içindir, bu slot için **değil** |
| **ÖLÇÜLEMEDİ — §11-D1** | "Gerçek kapak videosu envanteri" hâlâ açık. `Seller Gallery Image` üzerinden slot bazlı sayım yapılmadı |

**Ölçülen değerler** (5 okunabilen dosya üzerinden; codec ve çözünürlük n=5,
ses n=23):

| Ölçüt | Sonuç |
|---|---|
| Codec | h264 — **5/5** |
| Ses akışı içeren | **4/23** |
| Süre | p50 **33 sn** · p90 = max **540 sn (9 dk)** |
| Bitrate | p50 **746 kbps** · max **1.169 kbps** |
| Çözünürlükler | 720×1280 (**9:16**) · 720×720 (**1:1**) · 1280×720 (16:9) · 352×352 (**1:1**) · 1920×1080 (16:9) |
| `tabFile.file_size` güvenilirliği | **BOZUK** — videoların çoğunda p50 = **19 bayt** |

> **Çözünürlük listesi hakkında:** rapor §7 bu beş çözünürlüğü *"örnekleri"* diye
> yazıyor. Beş değer, okunabilen beş dosyayla **birebir örtüştüğü** için aşağıdaki
> "3/5", "2/5" sayımları bu listeyi **tam küme** kabul eder. Bu eşleşme
> **teyit edilmedi**; ölçüm yeniden koşulursa doğrulanmalıdır.

#### Ölçümden ETKİLENEN kararlar

| Etkilenen | Bu belgedeki hüküm | Ölçüm | Ne oldu |
|---|---|---|---|
| **§6.1 — oran 16:9 ±%1** | Tek oran, mobil alternatif yok (bilinçli) | Okunabilen 5 dosyanın **2'si 16:9**; kalan 3'ü **9:16 ve 1:1** | Karar **düşmedi** ama bedeli ölçüldü: kural bugünkü içeriğe geriye dönük uygulanırsa mevcut dosyaların çoğunluğu geçersiz olur → **yeni karar K8** (aşağıda) |
| **§6.1 — min 1280×720** | Altı `cover_video_resolution_too_low` | 352×352, 720×720, 720×1280 → **3/5 eşiğin altında** | Aynı sonuç: eşik doğru, **geçiş penceresi** şart → **K8** |
| **§6.2 — `story` maks 60 sn** | 60 sn üstü `cover_video_too_long` | Ölçülen **max 540 sn = tavanın 9 katı**; p50 33 sn tavanın **içinde** | Tavan **değişmiyor** (60 sn türetmesi bayt tavanına bağlı, §6.4). Ama 540 sn'lik dosya gerçek → **K8** |
| **§6.12 — kapak slotunda koşulsuz rendition** | `needs_transcode()` sonucu ne olursa olsun üret | Ölçülen bitrate p50 **746 kbps**, max **1.169 kbps** — sunucu barı **2.500 kbps**'in (`transcode.py:67`) ve istemci barı **2.000 kbps**'in (`compress.video.js:29`) **tamamen altında** | **ÖLÇÜMLE DOĞRULANDI.** Bugün bu videoların **hepsi passthrough** oluyor: koşullu eşik hiç tetiklenmiyor → ne rendition, ne poster, ne MP4 yedeği, ne 480p tier üretiliyor. §6.12'nin "koşulsuz" istisnası bir tercih değil, **zorunluluk** |
| **§6.12 — 2,5 → 2,0 Mbps birleştirme** | İki bar tek sayıda birleşsin | Ölçülen içeriğin **tamamı iki barın da altında** | Karar **geçerli ama bu içerikte etkisiz** (moot). Gerekçesi tutarlılık, bu ölçüm onu ne doğruluyor ne çürütüyor |
| **§6.3 / §6.4 — bayt kapıları** | 80 MB yükleme, 12 MB / 5 MB teslim | `tabFile.file_size` videolarda **p50 = 19 bayt** | **Uygulama notu (yeni):** bayt tabanlı hiçbir kapı `tabFile.file_size`'a güvenemez; boyut **diskten** okunmalı. Kapı sayıları değişmedi |
| **§6.8 — HLS eşiği** | `duration > 60 sn` üç koşuldan biri | Kütüphanede **540 sn'lik dosya var** | §6.8'in "kapak slotu bu koşulları tanım gereği sağlamaz" cümlesi **yeni içerik için** doğru; **mevcut** içerik grandfather edilirse doğru değil → **K8**'e bağlı |
| **§8.1 — VTT altyazı (K4'ün konusu)** | Konuşma varsa zorunlu | **4/23** dosya ses akışı taşıyor | K4'ün **üst sınırı** ölçüldü: bu veri setinde altyazı yükümlülüğü **en çok 4 dosyayı** ilgilendirebilir. "Ses var" ≠ "konuşma var" (§10-K5) ve slot eşlemesi yok → K4 **kapanmadı**, ölçeği daraldı |

#### Ölçümden ETKİLENMEYEN / hâlâ bekleyen kararlar

| # | Karar | Neden hâlâ açık |
|---|---|---|
| **K1** | 1080p tier eklenecek mi? | Tetiği **viewport × DPR payı** (§11-D3), medya envanteri değil. Bu ölçüm tarayıcı tarafına hiç dokunmadı → **ÖLÇÜLMEDİ**, varsayılan (eklenmedi) sürüyor |
| **K2** | `ambient` mod açılsın mı? | İş/kötüye kullanım kararı; ölçümle çözülmez. Zayıf destek: **19/23** dosyada ses yok, yani sessiz-döngü içerik zaten yaygın — ama bu bir onay tetiği değil |
| **K3** | Kapak videosu zorunlu mu? | İş kararı. Ölçüm dolaylı destek veriyor (tüm kütüphanede **23** video var, yani video **nadir**) ama zorunluluk sorusu ölçüm sorusu değil |
| **K4** | Altyazı yürürlük tarihi | Yukarıda: ölçeği daraldı (≤ 4 dosya), **kapanmadı**. §11-D1 (kapak sayısı) hâlâ açık |
| **K5** | Konuşma tespiti otomatik mi, beyan mı? | ffprobe "ses akışı var mı"yı söyler, "konuşma mı müzik mi"yi söylemez — belgenin kendi tespiti **ölçümle doğrulandı**, karar değişmedi |
| **K6** | Kategori enum'u genişlesin mi? | Ölçüm kategori dağılımına bakmadı → **ÖLÇÜLMEDİ** |
| **K7** | 80 MB tavanı kotayı zorlar mı? | Kota sorusu açık. Ölçüm yalnız şunu ekledi: rendition **baytlarını** planlarken `tabFile.file_size` kullanılamaz (p50 = 19 bayt) |

#### K8 — ÖLÇÜMDEN DOĞAN YENİ KARAR: mevcut içerik için geçiş penceresi

**Soru:** §6.1 (16:9 ±%1, min 1280×720) ve §6.2 (maks 60 sn) kuralları **mevcut**
videolara uygulanacak mı?

**Ölçülen gerçek:** okunabilen 5 dosyanın **3'ü** çözünürlük eşiğinin altında,
**3'ü** 16:9 değil, biri **540 sn**. Kurallar geriye dönük uygulanırsa bu içerik
geçersiz olur. Kural yeni yüklemeye uygulanırsa mevcut kapaklar **kırık oranla**
render edilmeye devam eder (`aspect-video` kutusunda `object-cover` → 9:16 bir
master'ın **%56'sı yatay kırpılır**, §6.1).

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİM)** — Yalnız YENİ yüklemelere; mevcut videolar dokunulmadan yaşar, envanterde `cover_video_legacy_geometry` işaretlenir | Hiçbir mağaza aniden kapaksız kalmaz. Mevcut kırpma sorunu görünür kalır ama **yeni** sorun doğmaz |
| B — Geriye dönük tarama + satıcıya bildirim + N gün sonra pasifleştirme | Standart gerçekten uygulanır. Ama **§11-D1 ölçülmeden** kaç mağazanın etkileneceği bilinmiyor ve mağaza kapağını kaldırmak ticari karardır |
| C — Mevcut dikey/kare masterlar için sunucuda otomatik 16:9 pad (letterbox) | Kırpma yerine siyah bant. Logo standardının 1:1 saydam pad çözümünün video karşılığı. Bedeli: her legacy dosya için bir transcode geçişi; kazancı ölçülmedi |

**Öneri: A**, ve §11-D1 koşulduktan sonra B için ayrı karar. **Varsayılan (onay
gelene kadar): A.**

---

**K1 — 1080p tier eklenecek mi?**
Öneri: **Şimdi eklenmesin** (varsayılan: eklenmedi). §11-D3 ölçümü tablet-DPR2
(768-1023 px viewport × DPR ≥ 2) payını **%15'in üstünde** gösterirse eklenir;
bitrate tavanı 4.500 kbps, dosya kapısı 22 MB, depolama maliyeti kapak başına
+~%60. Karar kriteri sayısal, ölçüm sonrası otomatik uygulanabilir.

**K2 — `ambient` mod açılsın mı?**
Öneri: **Açılsın, ama yalnız doğrulanmış (verified) satıcılara** (varsayılan:
kapalı). Gerekçe: otomatik oynayan döngü, kötü kullanılırsa vitrinin tamamını
hareketli reklam panosuna çevirir. `VerificationBadge` altyapısı zaten var
(`components/seller/VerificationBadge.ts`, `seller.verifications`).

**K3 — Kapak videosu zorunlu mu, opsiyonel mi?**
Öneri: **Opsiyonel kalsın** (varsayılan: opsiyonel). Bugün de opsiyonel —
`media_groups` boşsa `mediaGroups` boş dizi döner (`alpine/seller.ts:341-347`)
ve `thumbs.length > 1` kontrolüyle UI sessizce küçülür (`StoreHeader.ts:360`).
Zorunlu kılmak, videosu olmayan mağazaları cezalandırır.

**K4 — Altyazı zorunluluğunun yürürlük tarihi.**
Öneri: **Yeni yüklemeler için hemen; mevcut kapaklar için 90 gün geçiş**
(varsayılan: yalnız yeni yüklemeler). Mevcut kapak sayısı ölçülemedi (§11-D1);
geçiş penceresi o sayı bilinmeden takvime bağlanmamalı.

**K5 — Konuşma tespiti otomatik mi, satıcı beyanı mı?**
Öneri: **Satıcı beyanı + rastgele denetim** (varsayılan: satıcı beyanı).
Yükleme formunda "Bu videoda konuşma var" onay kutusu; işaretliyse `.vtt`
zorunlu. Otomatik konuşma tespiti (VAD/ASR) bu fazda kapsam dışı — ffmpeg
`silencedetect` ile "ses akışı var mı" ayrımı yapılabilir ama "konuşma mı müzik
mi" ayrımı yapılamaz.

**K6 — `Seller Gallery Image` kategori enum'u genişleyecek mi?**
Öneri: **Bu fazda genişletilmesin** (varsayılan: 4 kategori sabit) ve enum'un
**tek kaynağı doctype JSON'u** olsun; `_MEDIA_CATEGORIES` oradan türetilsin
(Ç12'nin çözümü). Yeni kategori isteği gelirse ayrı görev.

**K7 — 80 MB yükleme tavanı kotayı zorlar mı?**
Öneri: **80 MB kabul edilsin** (varsayılan: 80 MB). Ancak kapak videosu
renditionları (6 nesne, tipik ~19 MB / en kötü ~37,5 MB — §6.5) satıcının medya
kotasından sayılıyor mu, ayrı mı tutuluyor sorusu iş kararı.
`entitlement.checks.check_media_storage_quota` (`hooks.py` üzerinden, T-001 §L0)
bugün her `File` kaydını sayıyor; rendition'lar da `File` olacaksa kota **6 kat**
tüketilir. Önerim: rendition'lar `File` kaydı **açmasın** (görsel arşivinin
`ARCHIVE_DIRNAME` deseniyle aynı yaklaşım, `presets.py:33-35` — "envanteri ve
kotayı şişirmesin") ve yalnız master kotadan sayılsın.

---

---

## 10.9 ONAYLANAN KARARLAR — 2026-08-19 (platform yöneticisi)

Aşağıdaki üç karar platform yöneticisi tarafından verildi. Varsayılanlar
yürürlükten kalktı; her birinin uygulama işi ayrı görev olarak açılmalıdır.

| # | Karar | Sonuç | Öneriyle uyum |
|---|---|---|---|
| **K2** | `ambient` mod | ✅ **AÇILDI — yalnız doğrulanmış (verified) satıcılara** | Öneriyle **aynı** |
| **K7** | Rendition'lar medya kotasından sayılsın mı? | ✅ **SAYILSIN** | Öneriden **AYRILDI** ⚠️ |
| **K8** | Mevcut içerik için geçiş penceresi | ✅ **Yeni yüklemelere hemen; mevcut kapaklara dokunulmaz** | Öneriyle **aynı** |

### K2 — uygulama notu
Kapı `VerificationBadge` altyapısına bağlanacak
(`components/seller/VerificationBadge.ts`, `seller.verifications`). Doğrulanmamış
satıcıda `ambient` istenirse sessizce standart moda düşülür — hata gösterilmez.
Ölçümün zayıf desteği: 23 videonun **19'unda ses akışı yok**, yani sessiz-döngü
içerik zaten yaygın.

### K7 — ⚠️ öneriden ayrılan karar ve BEDELİ
Belgedeki öneri "rendition'lar `File` kaydı açmasın, yalnız master kotadan
sayılsın" idi. **Karar bunun tersi: rendition'lar da kotadan sayılacak.**

**⚠️ DÜZELTME — 2026-08-19, ölçümle.** Bu bölüm ilk yazıldığında "yaklaşık
6 kat" diyordu. `docs/reports/18-faz7-kapanis.md` 3 gerçek kapak videosunda
tarttı ve sayıyı düşürdü:

| Ne | İlk iddia | ÖLÇÜLEN |
|---|---|---|
| Nesne sayısı | 6× | **6×** (doğru) |
| **Bayt** çarpanı | ~6× | **2,85× · 3,13× · 4,56×** |
| §6.5 "tipik 30 sn ≈ 19 MB" | 19 MB | **4,95–8,80 MB** (tahmin 2–4 kat yüksek) |

Kritik ayrım: kota kapısı **bayt** üzerinden zorluyor (`entitlement/checks.py:272`
← `media/files.py:267 storage_usage`), **nesne sayısı üzerinden değil**. Yani
operatif çarpan **~3**, ~6 değil.

Buna karşılık ölçüm yeni bir eksik ortaya çıkardı: **6 nesne modeli HLS'i hiç
saymıyor.** HLS gereken tek dosya **409 nesne / +27,3 MB** üretti. Kota
planlaması HLS'i içermek zorunda.

Ayrıca K7 bugün **uygulanmıyor**: video paketi `frappe` import etmiyor ve
`File` kaydı açmıyor. Karar yürürlüğe girdiğinde bu bağlantı kurulacak.

> **Bağlı görev — bu karar tek başına eksiktir.** Kota değerleri yeniden
> boyutlandırılmalı ya da rendition'lar için ayrı bir kota kalemi tanımlanmalıdır.
> Aksi hâlde karar, satıcıların bugünkü kotalarını fiilen 6'ya bölmek anlamına
> gelir. `docs/standards/kota.md` bu karara göre güncellenmeli.

### K8 — kapsam
Ölçüm (`docs/reports/08-canli-olcum.md` §7): okunabilen 5 videonun **3'ü**
çözünürlük eşiğinin (1280×720) altında, biri **540 sn** (60 sn tavanının 9 katı).
Karar bu içeriğe **dokunmuyor**: kural yalnız yeni yüklemelerde uygulanır, mevcut
kapaklar olduğu gibi kalır ve hiçbir satıcının vitrini bozulmaz.

Not: bu 23 videonun kaçının gerçekten **kapak videosu** olduğu hâlâ bilinmiyor
(§11-D1 açık). Karar bu belirsizlikten etkilenmiyor — mevcut içeriğe zaten
dokunulmuyor — ama envanter ölçümü yine de yapılmalı.

## 11. ÜRETİMDE DOĞRULANMALI

Aşağıdaki hiçbir şey **bu belgenin yazıldığı oturumda** (2026-08-17) ölçülmedi;
Docker kapalıydı, üretim veritabanına ve canlı siteye erişim yoktu. Her madde
çalıştırılacak **tam komutu** içerir.

> **KISMİ KAPANIŞ — 2026-08-18.** Yerel stack açıldı ve `docs/reports/08-canli-olcum.md`
> §7 ile **D2'nin bir bölümü** (süre / çözünürlük / bitrate / codec dağılımı)
> **kütüphane genelinde** ölçüldü — ayrıntı ve sayılar §10.0'da. **D1 kapanmadı:**
> ölçüm slot eşlemesi yapmadı, yani bu dağılımın hangi kısmının kapak videosuna
> ait olduğu bilinmiyor; D2 de bu yüzden **slot bazında hâlâ açıktır**. D3–D9
> ölçülmedi. Ayrıca ölçüm **yerelde** yapıldı: üretim paritesi doğrulanmadı
> (üretim imajını Frappe Cloud kendi build ediyor, `docker/backend.Dockerfile`
> kullanılmıyor — rapor §3).

### D1 — Gerçek kapak videosu envanteri

```bash
# docker exec -it <backend-container> bench --site <site> console
frappe.db.sql("""
  SELECT sgi.category,
         sgi.media_type,
         COUNT(*)                                   AS satir,
         SUM(sgi.video_url IS NOT NULL AND sgi.video_url != '')  AS video_dolu,
         SUM(sgi.poster_image IS NULL OR sgi.poster_image = '')   AS poster_BOS
  FROM `tabSeller Gallery Image` sgi
  WHERE sgi.parenttype = 'Admin Seller Profile'
  GROUP BY sgi.category, sgi.media_type
  ORDER BY satir DESC
""", as_dict=True)
```
Cevaplaması gereken: kaç mağazada kapak videosu var, **kaçının poster'ı boş**
(§6.9'un aciliyeti), kategori dağılımı.

### D2 — Gerçek süre / çözünürlük / bitrate dağılımı

```bash
# Backend konteynerinde, site public dosyaları altında
docker exec -it <backend-container> bash -lc '
cd /home/frappe/frappe-bench/sites/<site>/public/files
for f in $(mysql -N -B -e "SELECT file_name FROM \`tabFile\` \
    WHERE file_url IN (SELECT video_url FROM \`tabSeller Gallery Image\` \
    WHERE video_url IS NOT NULL AND video_url != \"\")" <db>); do
  ffprobe -v error -select_streams v:0 \
    -show_entries stream=width,height,r_frame_rate,bit_rate,nb_frames \
    -show_entries format=duration,bit_rate,size \
    -of csv=p=0 "$f" | sed "s|^|$f,|"
done' | tee /tmp/kapak-video-envanteri.csv
```
Cevaplaması gereken: §6.1'deki 16:9 varsayımı kaç dosyada tutuyor,
§6.2'deki 6-60 s aralığı kaç dosyayı dışarıda bırakır, §6.4 bitrate tavanı
gerçekçi mi.

### D3 — Viewport + DPR dağılımı (K1 kararının girdisi)

```
# Analytics/RUM sağlayıcısında, mağaza profili sayfası (/magaza/*) için:
#   boyut 1: window.innerWidth kovaları  → [<640, 640-767, 768-1023, 1024-1199, >=1200]
#   boyut 2: window.devicePixelRatio kovaları → [1, 1.5, 2, 3]
#   metrik : oturum sayısı
# Aranan sayı: (768-1023) × (DPR >= 2) hücresinin toplam içindeki payı.
# Bu pay > %15 ise §10-K1 uyarınca 1080p tier eklenir.
```
Kod tarafında ölçüm kancası **bugün yok**; `utils/tracking.ts`
(`tradehubfront/src/utils/`) içine eklenmesi ayrı görev.

### D4 — `th_media_video_status` dağılımı (transcode hattı sağlığı)

```bash
# bench console
frappe.db.sql("""
  SELECT th_media_video_status AS durum, COUNT(*) AS adet,
         ROUND(AVG(file_size)/1048576, 2) AS ort_MB
  FROM `tabFile`
  WHERE LOWER(file_name) REGEXP '\\\\.(mp4|webm|mov|m4v)$'
  GROUP BY th_media_video_status
""", as_dict=True)
```
`failed` oranı ve `processing`'de **takılı kalmış** (24 saatten eski) satırlar
aranıyor. `NULL` satırlar hattın hiç dokunmadığı videolardır.

### D5 — Byte-range ve Content-Type doğrulaması (Ç1'in kanıtı)

```bash
# Ç1'i kanıtlar: .mp4 adresine WebM baytı yazılmış mı?
curl -sI 'https://<canli-site>/files/<kapak-dosyasi>.mp4' | \
  grep -iE 'content-type|accept-ranges|content-length'

# İlk 4 baytı oku: 1A 45 DF A3 = Matroska/WebM · 66 74 79 70 ("ftyp") = MP4
curl -s -r 0-3 'https://<canli-site>/files/<kapak-dosyasi>.mp4' | xxd -p
```
`Content-Type: video/mp4` + `1a45dfa3` çıktısı Ç1'i **doğrular**.
`Accept-Ranges: bytes` yoksa §6.8'deki progressive seek çalışmıyor demektir.

### D6 — ffmpeg/ffprobe yetenek doğrulaması

```bash
docker exec -it <worker-container> bash -lc '
  ffmpeg -version | head -1
  ffmpeg -hide_banner -encoders 2>/dev/null | grep -E "libvpx-vp9|libopus|libx264|libwebp"
  ffmpeg -hide_banner -h muxer=webm 2>&1 | grep -i cues_to_front
  ffmpeg -hide_banner -filters 2>/dev/null | grep -E "^ .*(thumbnail|loudnorm)"
'
```
§6.4'ün `-cues_to_front 1`, §6.6'nın `loudnorm`, §6.9'un `thumbnail` ve
`libwebp` gereksinimleri **kurulu imajda var mı** — hepsi doğrulanmadan §6
uygulanamaz.

### D7 — Gerçek kutu ölçüleri (tarayıcıda)

```js
// Canlı mağaza profilinde DevTools konsolu:
const kutu = document.querySelector('#store-header .aspect-video');
const v = kutu?.querySelector('video');
console.table([{
  viewport: innerWidth, dpr: devicePixelRatio,
  kutuW: kutu?.getBoundingClientRect().width,
  kutuH: kutu?.getBoundingClientRect().height,
  oran: (kutu?.getBoundingClientRect().width / kutu?.getBoundingClientRect().height).toFixed(4),
  videoW: v?.videoWidth, videoH: v?.videoHeight,
  objectFit: v && getComputedStyle(v).objectFit,
  poster: v?.getAttribute('poster') || '(YOK)',
}]);
```
360 / 390 / 640 / 768 / **1023** / 1024 / 1440 genişliklerinde tekrarlanmalı.
§2.2 tablosu bu çıktıyla karşılaştırılıp **doğrulanmalı** — tablo koddan
hesaplandı, tarayıcıdan okunmadı.

### D8 — CLS ölçümü (Ç6'nın büyüklüğü)

```bash
npx lighthouse 'https://<canli-site>/magaza/<kod>' \
  --only-categories=performance --form-factor=mobile \
  --throttling-method=devtools --output=json \
  --output-path=/tmp/kapak-lh.json
python3 -c "import json;d=json.load(open('/tmp/kapak-lh.json'));\
print('CLS', d['audits']['cumulative-layout-shift']['numericValue']);\
print('LCP', d['audits']['largest-contentful-paint']['numericValue'], 'ms');\
print('LCP element:', d['audits'].get('largest-contentful-paint-element',{}).get('displayValue'))"
```
Aranan: LCP elemanı **kapak videosunun poster'ı mı** (§2.4 mobilde video üstte
olduğu için beklenen bu) ve Ç6'nın 18,75 px kaymasının CLS'e katkısı.

### D9 — Pasif mobil bütçenin gerçek ölçümü (§6.7'nin 150 KB'ı)

```bash
# Chrome DevTools > Network, throttling "Slow 4G", cache boş, mobil emülasyon.
# Sayfa yüklendikten sonra HİÇBİR ŞEYE DOKUNMADAN:
#   filtre: Media + Img → poster + video isteklerinin toplam Transfer boyutu
# Beklenen: <= 150 KB. Aşıyorsa hangi kalem taşıyor (poster mı, metadata mı)?
#
# Otomatik alternatif:
npx lighthouse 'https://<canli-site>/magaza/<kod>' --form-factor=mobile \
  --output=json --output-path=/tmp/kapak-net.json
python3 -c "import json;d=json.load(open('/tmp/kapak-net.json'));\
[print(i['resourceType'], round(i['transferSize']/1024,1),'KB', i['url'][:100]) \
 for i in d['audits']['network-requests']['details']['items'] \
 if i['resourceType'] in ('Media','Image')]"
```

---

## 12. Bu standardı uygulamak için gereken kod işleri (Faz 3+ girdisi)

Sıra bağımlılığa göre. Hiçbiri bu görevde yapılmadı.

| # | İş | Neden gerekli | Dokunulacak yer |
|---|---|---|---|
| 1 | `ffprobe` tabanlı video ölçü/süre okuma + `th_media_duration_ms` alanı | Ç5 — §6.1/§6.2 kuralları bugün zorlanamıyor | `media/metadata.py`, yeni patch |
| 2 | `tradehub_core/media/pipeline/policy/slots/` kayıt defterini okuyan L3 doğrulayıcı | T-001: L3 sistemde hiç yok | `media/upload_policy.py` |
| 3 | Kapak slotu için çok-rendition transcode (yerinde değiştirme yerine) | Ç1 + §6.5 | `media/transcode.py` (yeni fonksiyon; mevcut `_run_transcode` **korunur**) |
| 4 | Otomatik poster üretimi (`thumbnail` + parlaklık kapısı) | Ç7 + §6.9 | yeni `media/poster.py` |
| 5 | 6 s önizleme klibi üretimi | §6.11 | aynı modül |
| 6 | `factory_video_url` → `Seller Gallery Image` göçü | Ç2 | yeni patch + `tr_tradehub` tarafıyla koordinasyon |
| 7 | Doctype açıklaması + panel istemci tavanı 80 MB'a hizalanması | Ç3 | `seller_gallery_image.json`, `StorefrontEdit.vue` |
| 8 | İstemci/sunucu "verimli" barının 2,0 Mbps'te birleştirilmesi | Ç4 | `transcode.py:67` |
| 9 | `subtitles_vtt` alanı + `<track>` + altyazı düğmesi + `KIND_CAPTION` | §8.1 | doctype, `StoreHeader.ts`, `upload_policy.py` |
| 10 | `ambient` mod + `prefers-reduced-motion` JS kapısı | §6.10, §8.2 | `StoreHeader.ts` |
| 11 | Skeleton'ı `aspect-video`'ya çevirme | Ç6 | `StoreHeader.ts:39` |
| 12 | Seek çubuğu `role="slider"` + klavye; `aria-label` dinamik; 3 etiketin i18n'e alınması; iOS `webkitEnterFullscreen` | §8.3 | `StoreHeader.ts` |
| 13 | Kategori enum'unun tek kaynağa indirilmesi | Ç12 | `api/seller.py:760-765` |
| 14 | Ürün videosu modalinde `muted` eklenmesi (veya `autoplay` kaldırılması) | Ç9 | `CompanyProfile.ts:1002` |

---

## 13. Kaynak dosya dizini

Bu belgede atıf yapılan her dosya, tam yolla:

**Backend (yazılabilir worktree)**
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/transcode.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/upload_policy.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/metadata.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/pipeline.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/presets.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/backup.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/api/seller.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/api/seller_media.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/tradehub_core/doctype/seller_gallery_image/seller_gallery_image.json`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/patches/v15_9_15_media_metadata_fields.py`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/patches/v15_9_16_media_video_status.py`

**Storefront (SALT OKU)**
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/components/seller/StoreHeader.ts`
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/components/seller/CompanyProfile.ts`
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/components/seller/CompanyInfo.ts`
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/components/seller/HeroBanner.ts`
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/alpine/seller.ts`
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/utils/seller/section-registry.ts`
- `/Users/ahmet/Desktop/istoc/tradehubfront/src/style.css`

**Admin panel (SALT OKU)**
- `/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/lib/media/compress.video.js`
- `/Users/ahmet/Desktop/istoc/admin-panel/frontend/src/views/seller/StorefrontEdit.vue`

**Bu çalışmanın diğer çıktıları**
- `/Users/ahmet/Desktop/istoc-medya-wt/docs/reports/00-upload-slot-envanteri.md` (T-001)
- `/Users/ahmet/Desktop/istoc-medya-wt/docs/reports/03-render-envanteri.md`
- `/Users/ahmet/Desktop/istoc-medya-wt/docs/reports/06-depolama-maliyet.md`
- `/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/pipeline/policy/slots/company-cover-video.json`

---

## VARSAYILANDA ONAYLANAN KARARLAR — 2026-08-19

Aşağıdaki kararlar platform yöneticisi tarafından **varsayılan seçenekte
onaylanmıştır**. Her birinde varsayılan, bu belgedeki öneriyle zaten aynıydı ve
hâlihazırda yürürlükteydi — onay hiçbir davranışı değiştirmez, yalnız kararı
"açık" olmaktan çıkarır. Yanlış bulunan olursa tek satırlık bir değişiklikle
çevrilebilir.

| # | Karar | Onaylanan | Not |
|---|---|---|---|
| **K1** | 1080p tier eklensin mi? | **Eklenmesin** | Öneriyle aynı. Tetik açık kalıyor: §11-D3 tablet-DPR2 payı > %15 çıkarsa yeniden açılır |
| **K3** | Kapak videosu zorunlu mu? | **Opsiyonel kalsın** | Öneriyle aynı |
| **K4** | Altyazı zorunluluğunun yürürlüğü | **Yalnız yeni yüklemeler** | Öneri "mevcuda 90 gün geçiş" idi; **K8 kararı (mevcuda dokunma) bu ayrımı kapattı** — ikisi artık tutarlı |
| **K5** | Konuşma tespiti otomatik mi, beyan mı? | **Satıcı beyanı + rastgele denetim** | Öneriyle aynı |
| **K6** | Kategori enum'u genişlesin mi? | **Genişletilmesin (4 kategori sabit)** | Öneriyle aynı. Enum'un tek kaynağı doctype JSON'u olmalı (Ç12) |

Bu belgedeki hiçbir seçenek tablosu silinmedi; kararlar istenirse yeniden açılabilir.
