# Slot standartları — özet

## Güncel durum — 2026-08-23

Bu bölüm aşağıdaki tarihli çalışma notlarının önüne geçer. Eski bölümler karar
geçmişini korumak için silinmemiştir; bugünkü doğruluk kaynağı şudur:

- çalışma zamanı/yükleme politikası:
  `tradehub_core/media/pipeline/policy/slots/*.json` (**9 slot**),
- kanonik Draft 2020-12 şeması:
  `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json`,
- insan tarafından okunabilir gerekçeler: `docs/standards/*.md`,
- MIME/EXIF ve hatalı metadata sözleşmesi: `docs/standards/mime-exif.md`,
- yükleme öncesi/sonrası doğrulama sınırı: `docs/standards/upload-validation.md`,
- tenant kota modeli ve raporlama: `docs/standards/tenant-media-quota.md`,
- `docs/standards/policies/*.json`: yalnız DPI/alan ölçüm izdüşümü; ikinci bir
  yürütme motoru veya rakip politika seti değildir.

Güncel otomatik doğrulama sonucu: **9/9 politika şemaya uyumlu**, 9/9
`standard_status=fixed`, 9/9 gerçek uyum ölçümü taşıyor, `encoder_quality`
içinde **null değer yok**. `status=draft`, standardın belirsiz olduğu anlamına
gelmez; Faz 3 çalışma-zamanı rollout durumudur. Sabit standardı rollout'tan
ayırmak için `standard_status` alanı özellikle eklenmiştir.

Tek Faz 2 insan kapısı T-025 yanlış-pozitif kalibrasyonudur:
`content_rules.json.calibration_status=TRIGGER_RATE_MEASURED_UNLABELED`.
1.291 gerçek ürün görselinde tetik oranları ölçüldü; fakat insan etiketleri
olmadan yanlış-pozitif oranı uydurulmadı. Bu nedenle içerik kuralları gölge
modunda/uyarı düzeyinde kalır; yalnız NSFW ve korumalı aşırı bulanıklık kuralı
şema gereği sert red adayı olabilir. T-029 platform imza alanı da insan
onayına kadar boş kalır.

> Aşağıdaki 2026-08-17/18 metni tarihsel karar günlüğüdür. “Kod tarafından
> okunmuyor”, “6/9 şema uyumlu”, “AVIF null” ve benzeri ifadeler bugünkü
> durum değildir.

**Yazan görev:** T-023 · **Tarih:** 2026-08-17 11:45 · **Branch:** `medya-motoru-faz0-faz2`

> **Güncelleme — 2026-08-17 13:01.** İki tutarsızlık kapatıldı, hiçbir bölüm
> silinmedi: (1) `company-cover-video.json` slot politikası şemasına taşındı ve
> şema **v1.1.0**'a çıktı (opsiyonel `video` bloğu; §4 E10'un video yarısı
> kapandı) — etkilenen satırlar §5 ve §6'da işaretli; (2) iki policy setinin
> kapsam farkı **§5-B**'de haritalandı (`tradehub_core/media/pipeline/policy/slots/` ve
> `docs/standards/policies/`).
>
> **Güncelleme — 2026-08-17 (şema v1.2.0).** Şemaya opsiyonel bir `logo`
> bloğu eklendi (`svg_policy`, `dark_theme`, `css_safe_area`, `render_points`,
> `not_render_points`/`unmeasured`) ve `seller-logo.json` ile `brand-logo.json`
> bu beş üst düzey alanı `logo.*` altına taşıyarak `schema_version: "1.2.0"`
> yazdı — içerikte tek bir sayı/metin değişmedi, yalnız bir seviye içe alındı.
> Bu taşımayla hedeflenen 5 alanın ürettiği doğrulama hatası **0'a indi**
> (`logo` yolunda hiç hata yok). Ancak iki dosyanın **tam şema uyumu (9/9)
> sağlanamadı**: `accept`, `require`, `master`, `quality`, `profiles`,
> `content_rules`, `on_violation` ve `production_verification_required`
> bloklarında bu görevin kapsamı DIŞINDA, önceden var olan ~39 ayrı uyumsuzluk
> ölçüldü (ör. `accept.max_bytes_svg` şemada yok, `master.pad_color` hex-renk
> deseniyle eşleşmiyor, `quality.metric: "bit_exact"` enum'da yok,
> `production_verification_required[]` öğeleri obje değil string). Bu
> uyumsuzluklar "üst düzeyde fazla alan" tanısıyla açıklanamaz; ayrı bir görev
> gerektirir.

Bu klasör her medya yükleme slotu için **kabul / geometri / profil / ihlal**
sözleşmesini tutar. Makine tarafı `tradehub_core/media/pipeline/policy/slots/<slot>.json`,
insan tarafı `docs/standards/<slot>.md`.

> **Hiçbiri bugün kod tarafından okunmuyor.** Sebep tek ve yapısal:
> `tradehub_core/media/upload_policy.py:307-313` — `check()` imzası
> `file_name`, `content`, `size`, `media_endpoint` alıyor; **slot parametresi
> yok**. Sunucu bir yüklemenin hangi slota ait olduğunu bilmediği için slot bazlı
> hiçbir kural yazılamıyor. `docs/reports/00-upload-slot-envanteri.md` §7-B **B1**
> bunu "Faz 2'nin çözmesi gereken tek yapısal eksik" olarak işaretlemiş.
> Bu klasör o eksik kimliğin **veri biçimidir**.

---

## 0. Karar durumu — 2026-08-18

Bu klasördeki standartların **numaralı (K-serisi) kararları** platform yöneticisi
onayı bekler. Docker açıldıktan sonra yapılan canlı ölçüm
(`docs/reports/08-canli-olcum.md`) bunlardan **ikisini kapattı**.

| | Adet |
|---|---:|
| **Toplam numaralı karar** | **14** |
| — ✅ **Çözüldü** (ölçümle) | **2** |
| — ⏳ **Bekliyor** | **12** |

### Çözülenler — 2

| Karar | Belge | Tetik (önceden yazılıydı) | Ölçüm (2026-08-18) | Sonuç |
|---|---|---|---:|---|
| **K1** JPEG logo: ret mi, uyarı mı? | `logo.md` §13 | JPEG payı **> %10** ⇒ B | **9/18 = %50** | **B** — kabul + uyarı + geçiş penceresi. Öneri A (ret) **düştü** |
| **K2** Oran bandı 1:2…2:1 mi, 1:4…4:1 mi? | `logo.md` §13 | Band dışı **> %20** ⇒ B | **2/18 = %11** | **A onaylandı** — band **1:2…2:1** aynen kaldı |

İkisi de `tradehub_core/media/pipeline/policy/slots/seller-logo.json` ve `brand-logo.json` içinde
uygulandı (`accept.mime`, `require.alpha_channel`,
`content_rules[no_alpha_channel].action`, `messages.tr.*`). Şema uyumu **9/9**
korundu.

> **Bu iki karar neden mekanik olarak verilebildi:** tetikleri sayı olarak
> **önceden** yazılmıştı. Ölçüm geldiğinde tartışma değil, karşılaştırma gerekti.
> Yeni karar yazan herkes aynı deseni izlemelidir.

### Bekleyenler — 12

| Karar | Belge | Neden hâlâ açık | Varsayılan |
|---|---|---|---|
| **K3** Merdiven 4 rung mu, 5 mi (+384)? | `logo.md` §13 | **ÖLÇÜLEMEDİ** — tetik 512 rung'unun *gerçek baytı*; türev üretimi (**T-063**) yazılmadan o dosya yok | A (4 rung) |
| **K4** PNG yedeği üretilsin mi? | `logo.md` §13 | Sayısal tetik yok; tarayıcı payı verisi gerekiyor | A (yalnız kayıpsız WebP) |
| **K5** Panelin 400×400 tavsiyesi | `logo.md` §13 | Ayrı görev (tek satır metin, `DocTypeFormView.vue:448`) | A (512×512) |
| **K6** 256 px sert reddi geriye dönük mü? | `logo.md` §13 | Ticari karar. Kısmi ölçüm var: kısa kenar < 256 = **1/18 = %5,5** | A (yalnız yeni yüklemeler) |
| **K1** 1080p tier eklensin mi? | `company-cover-video.md` §10 | Tetiği **viewport × DPR payı** (§11-D3); bu ölçüm tarayıcıya dokunmadı | Eklenmedi |
| **K2** `ambient` mod açılsın mı? | `company-cover-video.md` §10 | İş/kötüye kullanım kararı, ölçümle çözülmez | Kapalı |
| **K3** Kapak videosu zorunlu mu? | `company-cover-video.md` §10 | İş kararı | Opsiyonel |
| **K4** Altyazı yürürlük tarihi | `company-cover-video.md` §10 | Ölçek daraldı (**4/23** dosyada ses akışı var) ama slot eşlemesi yok (§11-D1 açık) | Yalnız yeni yüklemeler |
| **K5** Konuşma tespiti otomatik mi, beyan mı? | `company-cover-video.md` §10 | ffprobe "ses var mı"yı ayırır, "konuşma mı"yı ayırmaz — ölçüm bunu **doğruladı**, kararı vermedi | Satıcı beyanı |
| **K6** Kategori enum'u genişlesin mi? | `company-cover-video.md` §10 | **ÖLÇÜLMEDİ** — kategori dağılımına bakılmadı | 4 kategori sabit |
| **K7** 80 MB tavanı kotayı zorlar mı? | `company-cover-video.md` §10 | Kota/iş kararı. Ölçüm yalnız şunu ekledi: `tabFile.file_size` videolarda **bozuk** (p50 = 19 bayt), bayt planlaması ona dayanamaz | 80 MB |
| **K8** Mevcut videolara geçiş penceresi | `company-cover-video.md` §10.0 | **ÖLÇÜMDEN DOĞDU** — okunabilen 5 dosyanın 3'ü min çözünürlüğün altında, 3'ü 16:9 değil, biri 540 sn | A (yalnız yeni yüklemeler) |

### Kapsam uyarısı — bu tablo her açık kalemi saymaz

- Sayım yalnız **numaralı K-kararlarını** kapsar; bunlar yalnız iki belgede var
  (`logo.md` §13 = 6, `company-cover-video.md` §10 = 8).
- Diğer 7 slot politikasının açık kalemleri **numarasızdır** ve JSON'ların
  `open_questions` dizisinde durur. Bugünkü toplam: **9 dosyada 55 madde**
  (`seller-logo` 5, `brand-logo` 5, `company-cover-video` 8, `product-image` 7,
  `category-banner` / `company-cover-image` / `document-attachment` /
  `product-video` / `user-avatar` 6'şar). Bunlar bir karar değil, ölçüm bekleyen
  sorulardır — §7'deki ortak doğrulama listesiyle birlikte okunmalıdır.
- `seller-logo` ve `brand-logo`'nun `open_questions` sayısı 7'den **5'e** düştü:
  K1 ve K2 çözüldüğü için o iki madde `notes` altına, sonucuyla birlikte taşındı.

---

## 1. T-023'ün kapsadığı 5 slot — özet tablo

| slot | min (kabul) | maks / master | oran | format | profiller | ihlal aksiyonu |
|---|---|---|---|---|---|---|
| **`product.video`**<br>`product-video.json` | kısa kenar **360** (640×360), ≥10 kb | master **1280** uzun kenar (`transcode.py:242`), **10 MB** | **16:9** ±%6 | `.mp4 .webm .mov .m4v` → çıktı **VP9+Opus WebM** | *video rendition şemada ifade edilemedi (§4)*; poster: `poster_192`, `poster_1024` | default `reject`; genişlik/bitrate `auto_fix` (sunucu transcode eder); oran `warn`; `is_private` `warn` |
| **`company.cover_image`**<br>`company-cover-image.json` | kısa kenar **400**, alan **768.000**; <960 px → `reject` | master **2560** (`presets.py:14` safe), **5 MB** | **2,00:1 … 4,80:1** (öneri 24:5), tolerans %12 | `.jpg .jpeg .png .webp` → webp/avif | `cover_768`, `cover_1280`, `cover_1920`, `cover_2560`, `cover_16x9_1000` | default `reject`; geometri `warn`; **`is_private=1` → `reject`**; güvenli alan `warn` |
| **`category.banner`**<br>`category-banner.json` | kısa kenar **480**, alan **460.800**; <960 px → `reject` | master **2000** (`presets.py:15` balanced), **5 MB** | **1,10:1 … 3,36:1** (öneri 2:1), tolerans %12 | `.jpg .jpeg .png .webp` → webp/avif | `catbanner_480`, `catbanner_960`, `catbanner_1920` | default `reject`; geometri `warn`; span belirsizliği `review`; alt şerit kuralı **`ignore`** (çözülmüş) |
| **`user.avatar`**<br>`user-avatar.json` | kısa kenar **96**, alan **9.216** | master **256**, **5 MB** | **1:1 zorunlu**, tolerans %2 | `.jpg .jpeg .png .webp` (**`.gif` çıkarıldı**) → webp | `avatar_96`, `avatar_160`, `avatar_256` | default `reject`; **`require` → `reject`** (kare zorunlu); >256 px `auto_fix`; animasyon `auto_fix`; optimize edilmemiş `review` |
| **`document.attachment`**<br>`document-attachment.json` | kısa kenar **1654**, alan **3.868.706** (A4 @200 dpi) | master **5000** (küçültme pratikte kapalı), **10 MB** | **serbest** (`ratio_tolerance: 1`) | `.pdf .jpg .jpeg .png .webp .docx` → **biçim korunur** | `doc_thumb_512` (**private**) | default `reject`; **`content_rules` → `reject`** (magic-byte, private, attach hedefi); **geometri `warn`** (akış kırılmasın) |

### Tabloyu okuma notları

- **min / maks kolonlarındaki her sayının türetmesi** ilgili `.md` dosyasının
  §3'ünde ve JSON'un `sources` bloğunda yazılıdır. `sources` şema tarafından
  zorunlu (`provenance`: `dosya:satır` / `docs/... §bölüm` / `hesap: <formül>` /
  `ÖLÇÜLMEDİ: <ne yapılmalı>`) — boş bırakılamaz.
- **Hiçbir maks değeri uydurulmadı.** Üçü kodda zaten var olan eşiklerden alındı:
  2560 (`presets.py:14` `safe`), 2000 (`presets.py:15` `balanced`),
  1280 (`transcode.py:242` ffmpeg hedefi). 256 (avatar) ve 5000 (belge) türetildi
  ve gerekçesi yazıldı.
- **Boyut tavanları da uydurulmadı:** 5 MB kod tabanının fiili görsel taban
  çizgisi (`ProfileImageDropzone.vue:123`, `identity.py:952`,
  `WriteReviewModal.ts:23-26`); 10 MB `kyb.py:20` ve `ListingFormView.vue:4169`.
- **`ihlal aksiyonu` sözlüğü** şemadan gelir: `reject` (ret) · `warn` (kabul +
  uyarı + kayıt) · `review` (kabul + moderasyon kuyruğu) · `auto_fix` (sistem
  düzeltir ve söyler) · `ignore` (ölç, sakla, sus).

---

## 2. En büyük piksel talebinden en küçüğe

Bu sıralama, hangi slotun neden farklı master boyu aldığını tek bakışta
gösteriyor. Tüm CSS kutuları **kaynak koddan** okundu, tarayıcıda ölçülmedi.

| slot | en büyük gerçek CSS kutusu | kaynak | master | rezerv |
|---|---|---|---|---|
| `company.cover_image` | **1920×400** (tam viewport, `lg:h-[400px]`) | `section-registry.ts:103` + `:795` | 2560 | 1,33× (@2x karşılanmıyor — bilinçli) |
| `category.banner` | **880×210** (2×1 döşeme @1920) | `CategoryShowcase.ts:245` | 2000 | @2x=1760 karşılanıyor |
| `product.video` | **1023×1023** (mobil MediaViewer) / 502×502 (masaüstü) | `MediaViewer.ts:54` / `03-render-envanteri.md` §3.5 | 1280 | masaüstü @2x ✅, tablet @2x (1536) ❌ |
| `document.attachment` | 240×160 (panel önizlemesi) — **gösterim slotu değil** | `DocTypeFormView.vue:512` | 5000 | okunabilirlik belirleyici, kutu değil |
| `user.avatar` | **72×72** | `SettingsLayout.ts:98` | 256 | @3x=216 karşılanıyor |

---

## 3. Bu 5 slotta ZATEN ÇÖZÜLMÜŞ olanlar

Kural 5 gereği: aşağıdakiler kodda çalışıyor, **yeniden tasarlanmayacak.**

| slot | zaten çözülmüş |
|---|---|
| `product.video` | Asenkron transcode hattının **tamamı** (`media/transcode.py`): koşullu tetikleme, idempotanlık, global `after_insert` ağı, yerinde takas, durum alanı, yedek/geri yükleme farkındalığı. Parçalı yükleme (`media/chunked.py`, eşik 8 MB). |
| `company.cover_image` | Tek kapı L0; sunucu tarafı garanti-WebP (`engine.py:147-181`); EXIF yön + ICC koruma; `onerror` gradient fallback; `safeHexColor` ile CSS injection kapatılmış. |
| `category.banner` | Gradient scrim ile etiket okunabilirliği (`CategoryShowcase.ts:154`) — **"alt şeride metin koyma" kuralı yazılmamalı**; görselsiz fallback; CLS koruması (R12 "risk YOK"); boşluksuz bento dizilimi. |
| `user.avatar` | **Üç yerde aynı 5 MB** (sunucu + iki istemci); rate limit 10/300 sn; `?t=Date.now()` cache-buster (CDN gelirse sorun zaten çözülmüş); `User`'a doğru attach. |
| `document.attachment` | `kyb.py:411-501`'in tüm zinciri (magic-byte dahil); `presets.py:44-53` + `:70-76` muafiyet listeleri; **istemci sıkıştırmasının bilinçli kapatılması** (`KycLayout.ts:381`, `kyb.ts:303-306`) — hiçbir optimizasyon önerisi bunu geri açmamalı. |

---

## 4. Bu 5 slotta ölçülen EKSİKLER

| # | Eksik | Kanıt |
|---|---|---|
| E1 | **`category.banner`'ın backend alanı YOK.** Banner biçimindeki tek render (`CategoryProductListing.ts:88-90`) hiçbir sayfada mount edilmiyor; `bannerImage` yalnız `types/seller/types.ts:119` (tip) ve `data/seller/mockData.ts:286,411` (mock) içinde. `product_category.json`'da dosya tutan tek alan `image` (daire ikon). | `docs/standards/category-banner.md` §1 |
| E2 | **`company.cover_image` için okunan alan backend'de yok.** `pages/seller-shop.ts:118-119` `seller?.header_bg_image` okuyor; `grep -rn header_bg_image tradehub_core/` → **0 sonuç**. | `docs/standards/company-cover-image.md` §1, §8.1 |
| E3 | **`user.avatar` optimize EDİLMİYOR.** `identity.py:955-966` File'ı doğrudan açıyor, `engine.optimize()`/`to_webp()` çağrılmıyor. 4000 px'lik bir dosya 36 px'lik kutuya inebiliyor → 37 kat piksel israfı. | `docs/standards/user-avatar.md` §5.4, §8.2 |
| E4 | **Belgede dpi kaybı tuzağı 2 doctype'ta açık.** `Shipment Document` ve `Data Processing Agreement` `EXCLUDED_DOCTYPES`'ta yok; `presets.py:15` max_dim 2000 → A4'te **171 dpi**. | `docs/standards/document-attachment.md` §3.3, §7.1 |
| E5 | **KVKK alan haritası 4 KYB alanında eksik.** `presets.py:70-76` yalnız `identity_document` ve `bank_account_document`'i sayıyor. Kodun kendi bakım notu (`presets.py:66-69`) riski zaten yazmış. | `docs/standards/document-attachment.md` §3.4, §7.2 |
| E6 | **`product.video` 16:9 ama kutu 1:1.** `ProductVideoSection()` (16:9 kutu) hiçbir sayfada çağrılmıyor; video yalnız kare galeri kutusunda gösteriliyor → 502×502'lik kutuda 220 px siyah bant. | `docs/standards/product-video.md` §2 |
| E7 | **Private video sessizce normalize edilmiyor.** `transcode.py:194` `is_private` ise `return` ediyor; kullanıcıya hiçbir şey söylenmiyor. Aynısı `transcode.py:201-204` (satıcı değil / Listing'e bağlı değil) için. | `docs/standards/product-video.md` §6 |
| E8 | **Ölü render bileşenleri.** `components/seller/HeroBanner.ts`, `components/seller/CompanyInfo.ts`, `components/seller/CategoryProductListing.ts`, `components/product/ProductVideoSection.ts` — dördü de barrel'da dışa aktarılıyor, hiçbiri mount edilmiyor. Yanlış kutu ölçüsüne göre standart yazma riski. | ilgili `.md` §2'ler |
| E9 | **Kodlu ret sözleşmesi 2 uçta kullanılmıyor.** `identity.py:940,952` ve `kyb.py:440-476` düz `frappe.throw` metni fırlatıyor; `upload_policy.py:104-139`'daki 14 kodlu sözleşmeyi atlıyorlar. İstemci koda değil metne bakmak zorunda. | `user-avatar.md` §6, `document-attachment.md` §5 |
| E10 | **Şema video ve belge biçimlerini ifade edemiyor.** `slot-policy.schema.json` v1.0.0'da `profiles[].formats` enum'u `avif\|webp\|jpeg\|png`; `master.format` enum'unda `webm` yok. Gerçek video rendition'ı (`transcode.py:243-246`) politikada yazılamadı. | `docs/standards/product-video.md` §4 |

> **E10 — VİDEO YARISI KAPANDI (2026-08-17 13:01).** Şema **v1.1.0**'a çıktı:
> opsiyonel `video` bloğu (içinde `video.renditions[]`) eklendi ve
> `master.format` enum'una `webm` + `mp4` girdi. Gerçek video rendition'ı artık
> politikada yazılabiliyor: `product-video.json` → `video.renditions[0]`
> (`product_1280_webm`), `company-cover-video.json` → 4 rendition. `profiles[]`
> hâlâ yalnız görsel biçimleri kabul ediyor — bu **bilinçli**: video slotunda
> `profiles[]` poster/küçük resim görsellerini (`<picture>` kaynağı),
> `video.renditions[]` teslim edilen videoyu (`<video><source>` kaynağı)
> tanımlar.
> **BELGE YARISI AÇIK:** `master.format` enum'unda `pdf`/`docx` yok;
> `document-attachment.json` bu yüzden `preserve` yazıyor. Belge slotu için
> biçim korunması doğru davranış olduğundan bu bir hata değil ama şema
> "biçim korunuyor" ile "biçim ifade edilemiyor" arasını ayırt edemiyor.

---

## 5. Klasör envanteri ve ŞEMA UYUMSUZLUĞU

`2026-08-17 11:45` anlık görüntüsü. Bu klasöre birden çok görev (T-020 … T-023)
paralel yazdığı için liste değişebilir.

### `tradehub_core/media/pipeline/policy/slots/` — 9 dosya

| dosya | `slot_key` | `slot-policy.schema.json` **v1.1.0**'a uyum |
|---|---|---|
| `product-image.json` | `product.image` | ✅ |
| `product-video.json` | `product.video` | ✅ (T-023) |
| `company-cover-image.json` | `company.cover_image` | ✅ (T-023) |
| `category-banner.json` | `category.banner` | ✅ (T-023) |
| `user-avatar.json` | `user.avatar` | ✅ (T-023) |
| `document-attachment.json` | `document.attachment` | ✅ (T-023) |
| `seller-logo.json` | `seller.logo` | ❌ **32 şema hatası** — şema anahtarları var (`schema_version`, `slot_key`, `status: draft`) ama şemada tanımlı olmayan **ek alanlar** taşıyor (`css_safe_area`, `dark_theme`, `not_render_points`, `production_verification…`) ve `additionalProperties: false` bunları reddediyor |
| `brand-logo.json` | `brand.logo` | ❌ **32 şema hatası** — aynı biçim, aynı sebep |
| `company-cover-video.json` | `company.cover_video` | ✅ **(2026-08-17 13:01 itibarıyla)** — önceki hâli üçüncü bir biçimdi (`slot_key` hiç yok; kök anahtarlar `_meta`, `identity`, `render_box`, `modes`, `upload_constraints`, `transcode`, `renditions`…) ve **11 şema hatası** veriyordu. Şema v1.1.0'ın `video` bloğuna taşındı |

**Bu klasörde şu an 2 ayrı politika biçimi var** (2026-08-17 13:01; önceki
anlık görüntüde 3'tü). T-023 kendi 5 dosyasını
`tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json`'a uydurdu (doğrulandı,
§6). `company-cover-video.json` sonradan aynı şemaya taşındı: zorunlu üst
düzey alanlar dolduruldu, videoya özgü içeriğin tamamı yeni `video` bloğuna
geçti, `bound_to` gerçek alanla (`Seller Gallery Image.video_url`) dolduruldu
ve **hiçbir sayı/gerekçe/karar silinmedi** (eşleme tablosu o dosyanın
`notes[]` içinde "ŞEMA UYUMLANDIRMASI" başlığıyla yazılı). Kalan **2 dosya**
(`seller-logo.json`, `brand-logo.json`) hâlâ ikinci biçimde ve
**değiştirilmedi** — başka görevlerin çıktısı.

> `company-cover-video.json`'ın `slot_key`'i T-022 taslağında
> `seller.cover_video` yazıyordu; kapak **görseli** zaten `company.cover_image`
> olduğu için ikisi ayrışmasın diye `company.cover_video` seçildi. Envanterdeki
> **doctype biçimindeki** karşılığı ise `seller.gallery_video`'dur
> (`00-upload-slot-envanteri.md` §2). Üç adlandırma ailesinin farkı §5-B'de.

> Bu üç dosya **aktif olarak yazılmaya devam ediyordu**: aynı seans içinde
> `brand-logo.json` ve `seller-logo.json`'ın kök anahtarları Türkçeden
> (`kabul`, `normalizasyon`, `turevler`, `status: "onay_bekliyor"`) şema
> anahtarlarına döndü, ama ek alanlar kaldığı için hata sayısı değişmedi.
> Sayılar bu yüzden **anlık görüntüdür**; §6 betiği güncel sonucu verir.

**Faz 2 başlamadan tek biçime indirilmeli;** aksi hâlde politikaları okuyacak
kod her dosya için ayrı ayrıştırıcı yazmak zorunda kalır. En küçük müdahale:
şemada tanımlı olmayan alanların `notes[]`/`open_questions[]` içine taşınması ya
da şemanın v1.1'de o alanları tanımlaması.

> **GÜNCELLEME (2026-08-17, şema v1.3.0) — logo sınıfı uyumlandırıldı: 9/9 tam uyum.**
>
> Yukarıdaki tablonun son iki ❌ satırı (`seller-logo.json`, `brand-logo.json`)
> **kapandı.** Son ölçümde ikisi de **39'ar hata** veriyordu ve hata profili
> **birebir aynıydı** — yani tek bir sistematik uyumsuzluk: şemanın **alt
> blokları** fotoğraf/ürün slotu için yazılmıştı, `additionalProperties: false`
> kullanıyordu ve logo sınıfının meşru ihtiyaçlarını ifade edemiyordu.
> Yukarıda önerilen "en küçük müdahale"nin ilk seçeneği (**alanları
> `notes[]`'a taşımak**) **uygulanmadı**: politikalar doğruydu, dar olan şemaydı
> — ölçülmüş bir kararı yorum satırına indirmek onu doğrulanamaz hâle getirirdi.
> İkinci seçenek uygulandı: **şema genişletildi, iki logo JSON'unun içeriğine
> hiç dokunulmadı** (tek sayı, tek metin, tek anahtar adı değişmedi; iki dosya
> hâlâ `schema_version: "1.2.0"` yazıyor ve öyle geçerli).
>
> **Genişletilen bloklar ve neden:**
>
> | blok | genişletme |
> |---|---|
> | `accept` | + `conditional_extensions`, `rejected_extensions`, `format_priority`, `max_bytes_svg`, `allow_data_uri` (hepsi opsiyonel) |
> | `require` | + `recommended_edge`, `low_resolution_warn_below`, `max_edge`, `aspect_band` (**sürekli** oran bandı — ayrık `allowed_ratios` listesiyle ifade edilemiyordu), `alpha_channel`, `alpha_accepted_pil_modes` |
> | `master` | + `target_ratio`, `fit`, `pad_color`, `allow_crop`, `allow_upscale`, `encoding`, `in_file_safe_area_percent` |
> | `quality` | `metric` enum'una **`bit_exact`** (kayıpsız logoda SSIM yanıltıcı); + `lossless_required`, `reason`; `reencode_floor_saving_ratio` artık `null` kabul ediyor ("kapı bilinçle kapatıldı" ≠ "yazılmadı") |
> | `profiles[]` | + `max_bytes`, `byte_reference`, `max_overshoot_note`, `max_content_height`, `fixes`, `conditional`; `pad_color` **hex VEYA `"transparent"`**; `encoder_quality.*` **integer VEYA `null` VEYA `"lossless"`** (WebP'de `quality=100` hâlâ kayıplıdır — kip sayıyla ifade edilemez) |
> | `content_rules[]` | `threshold` **dizi** kabul ediyor (band eşiği `[0.5, 2.0]`); `comparator` enum'una `outside`/`inside`/`pad_to`; `message_key` **`null`** olabiliyor (`auto_fix` kuralında gösterilecek hata yok); + `measured_on` (aynı eşik "girdi" ile "sanitize çıktısı"nda farklı sonuç verir) |
> | `on_violation` | + `retryable_reason` |
> | `production_verification_required[]` | öğe artık **düz metin VEYA `{id,what,how}` objesi** (`anyOf`) — ölçüm betiği `logo.md §12`'de tam hâliyle yazılıyken buraya kopyalamak iki sürüm doğurur |
>
> **Zorunluluklar KALDIRILMADI, sınıf koşullu yapıldı.** `accept.max_megapixels_hard`,
> `require.{min_area, allowed_ratios, ratio_tolerance}` ve
> `master.{max_megapixels, dpi_out}` — bu beş kapı raster fotoğraf sınıfına aittir.
> "Düpedüz opsiyonel" seçeneği **reddedildi**: o zaman yedi mevcut dosyanın
> decompression-bomb ve oran kapıları sessizce isteğe bağlı olurdu ve şema o
> kaybı bir daha yakalayamazdı. Yerine kökte bir `allOf`/`if` bloğu var:
> **`logo` bloğu taşımayan** her politikada beşi de zorunlu kalır. Ayırt edici
> olarak yeni bir `kind`/`media_class` anahtarı **eklenmedi** — eklemek dokuz
> politika dosyasının hepsini düzenlemeyi gerektirirdi; v1.2.0'da eklenen `logo`
> bloğunun **varlığı** zaten yalnız iki logo dosyasında bulunuyor.
> Regresyon kontrolü: beş alanın her biri `product-image.json`'dan tek tek
> silindiğinde şema **hâlâ reddediyor**.
>
> **Sonuç:** şema geçerli draft 2020-12; `tradehub_core/media/pipeline/policy/slots/*.json`
> **9/9 tam uyum** (önce 7/9). `schema_version` enum'u
> `["1.0.0","1.1.0","1.2.0","1.3.0"]` — dokunulmayan yedi dosya kendi sürümünü
> yazmaya devam eder, toplu güncelleme gerekmez. `python3 -m unittest
> tests.test_policy_dpi` → 19 test, `OK` (1 beklenen başarısızlık).

Ek olarak `docs/standards/policies/` altında **13 dosya** daha var
(`listing.primary_image.json`, `seller.logo.json`, `seo.og_image.json`, …) —
`tradehub_core/media/pipeline/policy/slots/` ile **çakışan** dördüncü bir kayıt yeri.
`docs/standards/policies/_schema.md` kendi biçimini tarif ediyor.
Hangisinin kanonik olacağı bir karar bekliyor.

> **DÜZELTME (2026-08-17 13:01):** Bu iki set **çakışmıyor, kapsamları
> farklı** — biri DPI/çözünürlük politikası, diğeri tam slot sözleşmesi ve
> ikisi `bound_to` üzerinden birbirine bağlanıyor. "Hangisi kanonik" sorusunun
> cevabı "ikisi de, ama farklı sorular için". Tam kapsam haritası, hangi
> alanın hangi sette olduğu ve iş bölümü **§5-B**'de.

### `docs/standards/*.md` — 12 dosya

T-023: `product-video.md`, `company-cover-image.md`, `category-banner.md`,
`user-avatar.md`, `document-attachment.md`, `README.md`.
Diğer görevler: `product-image.md`, `company-cover-video.md`, `logo.md`,
`dpi-ve-cozunurluk.md`, `icerik-kurallari.md`, `kota.md`, `retention.md`.

---

## 5-B. Policy kapsam haritası — iki policy setinin iş bölümü

*Eklendi: 2026-08-17 13:01. Bu bölüm §5'in son paragrafındaki "hangisi kanonik"
sorusunun cevabıdır. Numarası bilinçli olarak `5-B`: §6'ya yapılan metin
içi atıflar bozulmasın.*

### 5-B.1 İki set, iki ayrı soru

İki policy seti var, **çelişmiyorlar — kapsamları farklı.** Aynı alan hakkında
farklı şeyler söylüyorlar ve `bound_to` üzerinden birbirlerine bağlanıyorlar.

| | `tradehub_core/media/pipeline/policy/slots/*.json` | `docs/standards/policies/*.json` |
|---|---|---|
| **Dosya sayısı** | 9 | 13 |
| **Yazan görev** | T-020 (şema), T-022, T-023 | T-024 |
| **Cevapladığı soru** | "Bu yükleme kabul edilir mi, kabul edilirse neye dönüşür ve kullanıcıya ne denir?" | "Bu görselin DPI'ı ve uzun kenarı ne olmalı, piksel korunuyor mu?" |
| **Kapsam** | `accept` (MIME/bayt/megapiksel) · `require` (kısa kenar/alan/oran/adet) · `master` · `profiles[]` · `video{}` (v1.1.0) · `content_rules[]` · `on_violation` · `messages{tr,en}` · `sources` | `min/max/target_long_edge` · `aspect_ratio` + `aspect_tolerance` · `fit` · `dpi_policy{output_dpi, strip_input_dpi, pixels_preserved}` · `olcum{}` |
| **`slot_key` biçimi** | kavramsal: `product.image`, `seller.logo`, `company.cover_video` | gerçek doctype alanı: `listing.primary_image`, `brand.hero_banner` |
| **Şema** | `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` v1.1.0 — JSON Schema draft 2020-12, `additionalProperties: false` | `docs/standards/policies/_schema.md` — **düzyazı** şema tarifi, makine doğrulaması yok |
| **Test ediliyor mu?** | **Hayır.** Yalnız §6 betiğiyle şema/değişmez doğrulaması yapılıyor (CI'da çalıştırılabilir, bugün çalışmıyor) | **Evet** — `tests/test_policy_dpi.py`, 19 test (1 beklenen başarısızlık). **Bu klasörün test edilen TEK policy setidir** |
| **Kod okuyor mu?** | Hayır (`upload_policy.check()` imzasında slot yok — B1) | Hayır; testler dosyaları okuyor, üretim kodu okumuyor |

**Doğruluk kaynağı (source of truth) ayrımı:**

- **Kabul/red kararı** ve kullanıcıya dönen metin/kod için doğruluk kaynağı
  **tam slot policy'sidir.** Bir alanın maksimum baytı, izinli MIME'ı, izinli
  oranı, ret kodu ve mesajı yalnız orada yazılıdır.
- **DPI davranışı** için doğruluk kaynağı **DPI policy'sidir** — ve tek sebebi
  şu: yalnız o set test ediliyor. `tests/test_policy_dpi.py` hem policy
  dosyalarının kendi iç tutarlılığını (`min_long_edge <= max_long_edge`, ürün
  slotlarında `min_long_edge >= 2000`) hem de motorun davranışını
  (`engine.py`'de `im.thumbnail()` yalnız küçültür, DPI oranını piksele
  UYGULAMAZ) doğruluyor. Tam slot policy'sinde `master.dpi_out` alanı da var
  ama onu doğrulayan hiçbir test yok.
- **İki set aynı alan için farklı uzun kenar/oran söylüyorsa** çelişki bir
  bulgu olarak yazılmalıdır — sessizce biri seçilmemelidir. Bugün böyle bir
  çelişki **aranmadı**; iki setin ortak 8 alanı için karşılaştırma yapılmadı
  (bkz. 5-B.6, kalan iş #3).

### 5-B.2 Adlandırma: üç biçim, aynı kavram

| kayıt yeri | dosya adı örneği | anahtar örneği | kural |
|---|---|---|---|
| `tradehub_core/media/pipeline/policy/slots/` | `product-image.json` — **TİRE** | `product.image` — **NOKTA** | Dosya adı = `slot_key`'in tire hâli. Şema deseni: `^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$` |
| `docs/standards/policies/` | `listing.primary_image.json` — **NOKTA** | `listing.primary_image` | Dosya adı = `slot_key`'in aynısı. `slot_key`, gerçek alanın küçük harfli hâli: `Listing.primary_image` → `listing.primary_image` |
| `docs/standards/*.md` | `product-image.md` — **TİRE** | — | Slot policy dosya adıyla birebir aynı olmak zorunda; §6 betiğinin D5 değişmezi bunu kontrol ediyor |

> **Tuzak:** aynı kavram üç ayrı adla anılabiliyor —
> `company.cover_image` (tam policy) / `seller.banner` (DPI policy) /
> `Admin Seller Profile.banner_image` (gerçek alan). Aynı şekilde
> `company.cover_video` (tam policy) / `seller.gallery_video` (envanter) /
> `Seller Gallery Image.video_url` (gerçek alan).
> **Eşleştirme yalnız gerçek `doctype.field` üzerinden güvenlidir** —
> `slot_key` üzerinden yapılan eşleştirme sessizce yanlış sonuç verir.
> Dosya adındaki tire/nokta farkı da bu yüzden kozmetik değil: iki setin
> dosya adları aynı desende olsaydı iki farklı anahtar uzayı karışırdı.

### 5-B.3 Tablo A — DPI policy'si olan 13 alan

`✅ (bound_to)` = alanın kendi adını taşıyan bir slot policy dosyası yok ama
alan, başka bir slot policy'sinin `bound_to[]` listesinde yer alıyor; o
politikanın tüm kapıları bu alana uygulanır.

| gerçek doctype.field | DPI policy | tam slot policy | bağlı `slot_key` | öncelik |
|---|---|---|---|---|
| `Listing.primary_image` | ✅ `listing.primary_image.json` | ✅ (bound_to) | `product.image` | — kapsandı |
| `Listing Image.image` | ✅ `listing.gallery_image.json` | ✅ (bound_to) | `product.image` | — kapsandı |
| `Listing Variant Item.variant_image` | ✅ `listing.variant_image.json` | ✅ (bound_to) | `product.image` | — kapsandı |
| `Admin Seller Profile.banner_image` | ✅ `seller.banner.json` | ✅ (bound_to) | `company.cover_image` | — kapsandı |
| `Admin Seller Profile.logo` | ✅ `seller.logo.json` | ✅ dosya (`seller-logo.json`) | `seller.logo` | — kapsandı, **ama dosya şemaya uymuyor** (§5, 40 hata) |
| `Brand.logo` | ✅ `brand.logo.json` | ✅ dosya (`brand-logo.json`) | `brand.logo` | — kapsandı, **ama dosya şemaya uymuyor** (§5, 40 hata) |
| `Brand.hero_banner` | ✅ `brand.hero_banner.json` | ✅ (bound_to) | `category.banner` | — kapsandı |
| `Category Showcase Tile.image` | ✅ `category_showcase.tile_image.json` | ✅ (bound_to) | `category.banner` | — kapsandı |
| `Seller Gallery Image.image` | ✅ `seller.gallery_image.json` | ❌ **YOK** | — | **P1** |
| `Listing Review Image.image` | ✅ `review.image.json` | ❌ **YOK** | — | **P2** |
| `Static Page SEO.og_image` | ✅ `seo.og_image.json` | ❌ **YOK** | — | **P2** |
| `Seller Product.image` | ✅ `seller_product.image.json` | ❌ **YOK** | — | **P3** |
| `Shipping Channel.icon` | ✅ `shipping_channel.icon.json` | ❌ **YOK** | — | **P3** |

**Öncelik gerekçeleri** (hepsi kanıta bağlı, tercih değil):

- **P1 `Seller Gallery Image.image`** — bugün **canlı render'ı var** ve
  görsel **sessizce kırpılıyor**: vitrin hücresi `aspect-square`
  (`section-registry.ts:571-573`), üretici listesi 165×165 / xl 220×220
  (`ManufacturerList.ts:353-357`); kare olmayan yüklemede merkezden kırpma
  yapılıyor ve **uyarı gösterilmiyor**
  (`00-upload-slot-envanteri.md` §2 `seller.gallery_image` satırı).
  Kapsam dışı kalan tek "canlı + kırpan" slot budur.
- **P2 `Listing Review Image.image`** — alıcı yüklemesi, yani içerik kuralları
  (yüz/çıplaklık/metin) ve adet kuralı asıl burada gerekiyor; L2 istemci
  kontrolü zaten var ve **`.gif` kabul ediyor**
  (`WriteReviewModal.ts:23-26`: 5 dosya, 5 MB, jpg/jpeg/png/**gif**/webp) —
  `user.avatar`'da `.gif` bilinçli olarak çıkarılmıştı (§1), aynı karar burada
  verilmedi.
- **P2 `Static Page SEO.og_image`** — oranı ve ölçüsü **dış platformlar**
  dayatıyor (1200×630), yani tarayıcı kutusu ölçmeye gerek yok: tam policy'nin
  en kolay yazılabileceği slot. Yanlış ölçüde og_image sessizce kırpılıp
  paylaşımda bozuk görünür.
- **P3 `Seller Product.image`** — `LIVE_SOURCES`'ta yok (§7-B B6) ve storefront
  render'ı bulunamadı; ölü ya da ölmekte olan bir alana standart yazmak E8'in
  hatasını tekrarlamak olur. Önce mount kontrolü.
- **P3 `Shipping Channel.icon`** — admin yüklemesi, düşük hacim, küçük kutu;
  `LIVE_SOURCES`'ta yok. Riski en düşük slot.

### 5-B.4 Tablo B — tam slot policy'si olan ama DPI policy'si OLMAYAN 22 alan

DPI policy seti **yalnız `kind: image` alanları için** yazıldı (13 dosyanın
hepsinde `"kind": "image"`). Aşağıdaki **22 alan** tam slot policy
kapsamındadır ama DPI policy'si yoktur. Tabloda **23 satır** görünür:
`Storefront Layout.sections` iki ayrı slota bağlı (`company.cover_image` slayt
görseli, `seller.logo` JSON içindeki `header.logo`) ve iki kez listelenmiştir.

> **İki alan bilinçli olarak iki slota bağlı.** Çelişki değil, iş bölümü:
> `Storefront Layout.sections` (yukarıdaki) ve
> `Seller Gallery Image.poster_image` — ikincisinin **kabul kapısı ve
> geometrisi** `company.cover_image`'a tabidir (bir görseldir), **hangi kareden
> ve hangi kuralla üretileceği** `company.cover_video` → `video.poster`'a
> tabidir. Bu ayrım iki dosyanın `bound_to[].source` metinlerinde yazılıdır.

| bağlı `slot_key` | alanlar | DPI policy'sinin olmama sebebi |
|---|---|---|
| `document.attachment` | `KYB Verification.{identity_document, imza_sirkuleri, ticaret_sicil_gazetesi, faaliyet_belgesi, vergi_levhasi, bank_account_document}`, `KYC Verification.identity_document`, `Seller Application.identity_document`, `Seller Certification.document`, `Seller Verification.document`, `Shipment Document.file`, `Data Processing Agreement.document`, `Order.receipt_url`, `Payment Transaction.receipt_url` (**14 alan**) | **Kasıtlı.** Belgede DPI kuralı görselin TERSİDİR: okunabilirlik/OCR için A4'te ~200 dpi taban gerekiyor (`document-attachment.json`: kısa kenar 1654, alan 3.868.706) ve `presets.py:44-53`, `:70-76` muafiyetleri optimizasyonu zaten kapatıyor. "72 dpi'a indir, pikseli koru" kuralı buraya uygulanamaz |
| `product.video` | `Listing.video_url`, `Listing Variant Item.variant_video_url` | **Kasıtlı.** Video; DPI kavramı yok (`master.dpi_out: 72` yalnız şema zorunluluğu olduğu için yazıldı) |
| `company.cover_video` | `Seller Gallery Image.video_url` | **Kasıtlı.** Aynı sebep |
| `product.image` | `Listing Variant Item.variant_gallery` (Long Text, JSON dizi) | **İfade edilemiyor.** DPI policy bir `doctype_field` başına bir dosya; JSON dizisi içindeki URL'ler alan düzeyinde adreslenemiyor |
| `company.cover_image` | `Storefront Layout.sections` (Long Text, slayt URL'i JSON içinde) | **İfade edilemiyor.** Aynı sebep. **CANLI RENDER BUDUR** (`section-registry.ts:117-222`) — yani en çok görünen kapak görseli DPI policy kapsamı dışında |
| `seller.logo` | `Storefront Layout.sections` (JSON içinde `header.logo`) | **İfade edilemiyor.** Aynı sebep. Ayrıca `bound_to[].field` değeri burada gerçek alan adı değil, parantezli bir açıklama taşıyor — düzeltilmeli |
| `company.cover_image` | `Seller Gallery Image.poster_image` | **EKSİK.** Bu bir Attach **Image**; DPI policy'si olmalı ama yok. Kapak videosunun poster'ı (`company-cover-video.json` → `video.poster`) buraya yazılıyor |
| `category.banner` | `Seller Category.image` | **EKSİK.** Attach Image; DPI policy'si yok. Storefront render'ı da bulunamadı — önce mount kontrolü |
| `user.avatar` | `User.user_image` | **EKSİK ama mazereti var:** alan Frappe çekirdeğinde, `tradehub_core` doctype'larında değil, bu yüzden 41'lik taramada hiç çıkmıyor (`00-upload-slot-envanteri.md` §5 açıkça yazıyor). Yine de bir görsel ve **hiç optimize edilmiyor** (E3) |

### 5-B.5 Tablo C — hiçbir sette olmayan alanlar

Envanterin (`00-upload-slot-envanteri.md` §2 Tablo A) şu alanları **her iki
sette de yok**:

| envanter `slot_key` | gerçek doctype.field | değerlendirme |
|---|---|---|
| `brand.video` | `Brand.video_url` | **GERÇEK BOŞLUK.** Marka tanıtım videosu, 16:9 canlı render (`pages/brand.ts:188-215`). `product.video` ve `company.cover_video` yazıldı, bu üçüncü video slotu atlandı |
| `category.image` | `Product Category.image` | **GERÇEK BOŞLUK.** `category.banner` politikası `Category Showcase Tile.image`, `Brand.hero_banner` ve `Seller Category.image`'ı bağlıyor; `product_category.json`'ın dosya tutan tek alanı olan `image` (daire ikon) hiçbir yere bağlı değil (E1 ile aynı kök) |
| `hero_slide.background` | `Hero Slide.background_image` | **GERÇEK BOŞLUK.** Ana sayfa slider arka planı; CSS `background` ile render ediliyor (`HeroTopSlider.ts:134-140`), yani en büyük piksel talebi olan yüzeylerden biri |
| `logistics.provider_logo` | `Logistics Provider.logo` | **GERÇEK BOŞLUK.** Logo ailesinden (`brand.logo`/`seller.logo` yazıldı), bu atlandı |
| `verification_source.icon` | `Verification Source.icon` | **GERÇEK BOŞLUK.** İkon ailesinden (`shipping_channel.icon` DPI policy'si var), bu atlandı |
| `review.seller_product_image` | `Seller Review.product_image` | **GERÇEK BOŞLUK.** `review.image`'ın kardeşi; DPI policy'si bile yok |
| `cart.snapshot_image` | `Cart Item.snapshot_image` | **Boşluk DEĞİL** — yükleme slotu değil, sistemin kopyaladığı alan (`usage.py:46` `ORDER_SOURCES`) |
| `order.item_image` | `Order Item.image` | **Boşluk DEĞİL** — aynı sebep, kopya alan |
| `gdpr.export_file` | `Data Export Request.file_url` | **Boşluk DEĞİL** — sistem çıktısı, kullanıcı yüklemesi değil; `presets.py:52` muaf |
| `bulk_import.data_file` | `Bulk Import Job.data_file` | **Boşluk DEĞİL** — medya değil veri dosyası (xlsx/csv/xml). Ama L0'ı **bypass ediyor** (`utils/security.py:85-88`) → güvenlik konusu, medya standardı konusu değil |
| `bulk_import.images_zip` | `Bulk Import Job.images_zip` | **Kısmen boşluk:** ZIP'in kendisi medya değil ama **içindeki görseller L0'dan geçiyor mu bilinmiyor** (§9-M2). Çözülmesi gereken yer bu klasör değil, bulk_import hattı |

### 5-B.6 Kapsam kararı: BİLİNÇLİ, ama iddia edilenden farklı

**Kapsam dışı kalmak bir hata değil, bir sıralama kararıdır.** T-023 beş yüksek
etkili slotu seçti (ürün videosu, şirket kapak görseli, kategori bandı,
avatar, belge), T-022 kapak videosunu yazdı, T-024 ise DPI kuralını **13 alana
birden** yaydı — çünkü DPI kuralı slot bilgisi gerektirmiyor, alan bilgisi
yetiyor. Yüksek etkili slotlarda **derin** sözleşme, geri kalanda **sığ ama
geniş** DPI sözleşmesi: bilinçli iş bölümü.

**Bir düzeltme:** bu bölüm yazılırken "8 gerçek alanın yalnız DPI policy'si var,
tam slot policy'si yok" diye bir sayı dolaşıyordu. Ölçüm bunu **doğrulamadı** —
doğru sayı **5**:

| iddia edilen | ölçülen durum |
|---|---|
| `brand.hero_banner` | **tam policy VAR** — `category-banner.json` `bound_to[1]` (`Brand.hero_banner`, Attach Image, kaynak `brand.json:107`) |
| `listing.gallery_image` | **tam policy VAR** — `product-image.json` `bound_to[1]` (`Listing Image.image`) |
| `listing.variant_image` | **tam policy VAR** — `product-image.json` `bound_to[2]` (`Listing Variant Item.variant_image`) |
| `review.image` | tam policy YOK ✅ |
| `seller.gallery_image` | tam policy YOK ✅ |
| `seller_product.image` | tam policy YOK ✅ |
| `seo.og_image` | tam policy YOK ✅ |
| `shipping_channel.icon` | tam policy YOK ✅ |

Yanılmanın sebebi tam olarak 5-B.2'de anlatılan tuzaktır: `slot_key`'ler
eşleşmediği için (`listing.gallery_image` ≠ `product.image`) alan kapsam dışı
görünüyor; oysa `bound_to` üzerinden kapsanıyor. **Kapsam sorusu her zaman
gerçek `doctype.field` üzerinden sorulmalıdır.** Kontrol betiği 5-B.7'de.

**Kalan iş — Faz 3'ün ilk görevi olarak açılmalı.** Faz 2'nin numaraları
T-020…T-029 ile dolu (T-029 kapanış belgesi), bu yüzden yeni numara gerekiyor;
öneri **T-030 — kalan slot politikaları**, üç iş paketiyle:

1. **T-030/A — 5 slot politikası** (Tablo A'daki P1-P3 sırasıyla):
   `seller.gallery_image` → `review.image` → `seo.og_image` →
   `seller_product.image` → `shipping_channel.icon`. Her biri için
   `tradehub_core/media/pipeline/policy/slots/<ad>.json` + `docs/standards/<ad>.md` (§6 D5
   değişmezi ikisini birlikte istiyor).
2. **T-030/B — Tablo C'deki 6 gerçek boşluk**: `brand.video`,
   `category.image` (`Product Category.image`), `hero_slide.background`,
   `logistics.provider_logo`, `verification_source.icon`,
   `review.seller_product_image`. Bunlar bugün **hiçbir** policy setinde yok;
   en azından DPI policy'leri yazılmalı (ucuz, test altyapısı hazır).
3. **T-030/C — iki set arasında çelişki taraması**: ortak 8 alan için
   `max_long_edge` / `aspect_ratio` / `fit` değerleri karşılaştırılmalı ve
   `tests/test_policy_dpi.py` yanına **çapraz tutarlılık testi** yazılmalı
   (bugün böyle bir test yok; iki set sessizce ayrışabilir).
4. **T-030/D — şemaya uymayan 2 dosya**: `seller-logo.json`,
   `brand-logo.json` (§5). Bunlar T-030'un önkoşulu değil ama §6 betiği
   CI'ya girmeden kapatılmalı.

### 5-B.7 Kapsam haritasını yeniden üretme

Tablo A/B/C elle yazılmadı, aşağıdaki betikle üretildi. Klasöre paralel
görevler yazdığı için **çalıştırmak güncel sonucu verir**:

```bash
cd /Users/ahmet/Desktop/istoc-medya-wt
python3 - <<'PY'
import json, glob, os, re

dpi = {}
for f in sorted(glob.glob("docs/standards/policies/*.json")):
    d = json.load(open(f))
    dpi[d["doctype_field"]] = os.path.basename(f)

tam = {}
for f in sorted(glob.glob("tradehub_core/media/pipeline/policy/slots/*.json")):
    d = json.load(open(f))
    for b in d.get("bound_to") or []:
        alan = f"{b['doctype']}.{re.sub(r' .*', '', b['field'])}"
        tam.setdefault(alan, []).append((d["slot_key"], os.path.basename(f)))

print("== Tablo A: DPI policy'si olan alanlar ==")
for alan, dosya in dpi.items():
    m = tam.get(alan)
    durum = f"tam policy VAR -> {m[0][0]} ({m[0][1]})" if m else "tam policy YOK"
    print(f"  {alan:42s} | {dosya:36s} | {durum}")

print("\n== Tablo B: tam policy VAR, DPI policy YOK ==")
for alan, m in sorted(tam.items()):
    if alan not in dpi:
        print(f"  {alan:52s} | {m[0][0]}")

print(f"\nDPI: {len(dpi)} alan | tam policy bound_to: {len(tam)} alan "
      f"| kesişim: {len(set(dpi) & set(tam))}")
PY
```

`2026-08-17 13:01` çıktısı: **DPI 13 alan · tam policy `bound_to` 30 alan ·
kesişim 8** → yalnız DPI policy'si olan **5** alan (`Listing Review Image.image`,
`Seller Gallery Image.image`, `Seller Product.image`, `Shipping Channel.icon`,
`Static Page SEO.og_image`), yalnız tam policy'si olan **22** alan
(Tablo B'de 23 satır — `Storefront Layout.sections` iki slota bağlı).

---

## 6. Programatik doğrulama — profilsiz slot ve slotsuz profil olmamalı

Aşağıdaki betik dört değişmezi kontrol eder. `jsonschema` gerekir
(`pip install jsonschema`).

```bash
cd /Users/ahmet/Desktop/istoc-medya-wt
python3 - <<'PY'
import json, glob, os, sys
try:
    import jsonschema
except ImportError:
    sys.exit("jsonschema gerekli: pip install jsonschema")

SCHEMA = "tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json"
sema = json.load(open(SCHEMA))
dogrulayici = jsonschema.Draft202012Validator(sema)

politikalar = sorted(glob.glob("tradehub_core/media/pipeline/policy/slots/*.json"))
standartlar = {os.path.basename(p)[:-3] for p in glob.glob("docs/standards/*.md")
               if not p.endswith("README.md")}

hata = 0
uyumlu = []

for p in politikalar:
    ad = os.path.basename(p)[:-5]
    d = json.load(open(p))
    hatalar = list(dogrulayici.iter_errors(d))
    if hatalar:
        print(f"[SEMA] {ad}: {len(hatalar)} hata — ilk: {hatalar[0].message[:90]}")
        hata += 1
        continue
    uyumlu.append((ad, d))

for ad, d in uyumlu:
    sk = d["slot_key"]

    # DEĞİŞMEZ 1 — profilsiz slot olamaz
    if not d.get("profiles"):
        print(f"[D1] {sk}: PROFİLSİZ SLOT"); hata += 1

    # DEĞİŞMEZ 2 — slotsuz profil olamaz: her profil bir CSS kutusuna dayanmalı
    for pr in d["profiles"]:
        if not pr.get("derived_from"):
            print(f"[D2] {sk}/{pr['name']}: derived_from YOK"); hata += 1
        if not pr.get("serves"):
            print(f"[D2] {sk}/{pr['name']}: serves YOK — hangi render noktasına hizmet ettiği belirsiz"); hata += 1
        if pr["width"] > d["master"]["max_long_edge"]:
            print(f"[D2] {sk}/{pr['name']}: profil ({pr['width']}) master'dan büyük "
                  f"({d['master']['max_long_edge']}) — upscale yok"); hata += 1

    # DEĞİŞMEZ 3 — her message_key tanımlı olmalı, her sayının kaynağı olmalı
    mesajlar = set(d["messages"]["tr"])
    for kural in d.get("content_rules", []):
        mk = kural.get("message_key")
        if mk and mk not in mesajlar:
            print(f"[D3] {sk}: content_rules '{kural['rule']}' tanımsız message_key '{mk}'"); hata += 1
    if not d.get("sources"):
        print(f"[D3] {sk}: sources BOŞ — her sayının kaynağı yazılmalı"); hata += 1

    # DEĞİŞMEZ 4 — master invaryantı + status/açık soru tutarlılığı
    m = d["master"]
    if m["max_long_edge"] ** 2 / 1e6 < m["max_megapixels"]:
        print(f"[D4] {sk}: max_long_edge^2/1e6 ({m['max_long_edge']**2/1e6:.4f}) "
              f"< max_megapixels ({m['max_megapixels']})"); hata += 1
    if d.get("status") == "active":
        if d.get("open_questions"):
            print(f"[D4] {sk}: status=active ama open_questions dolu"); hata += 1
        for pr in d["profiles"]:
            for b, q in (pr.get("encoder_quality") or {}).items():
                if q is None:
                    print(f"[D4] {sk}/{pr['name']}: status=active ama encoder_quality.{b} null"); hata += 1

    # DEĞİŞMEZ 5 — politika ↔ standart belgesi eşleşmesi
    if ad not in standartlar:
        print(f"[D5] {ad}: politika var, docs/standards/{ad}.md YOK"); hata += 1

# Ters yön: .md var politika yok (bilgi amaçlı — bazı .md'ler slot değil, konu belgesi)
politika_adlari = {os.path.basename(p)[:-5] for p in politikalar}
for s in sorted(standartlar - politika_adlari):
    print(f"[bilgi] docs/standards/{s}.md için slot politikası yok (konu belgesi olabilir)")

print(f"\nşemaya uyumlu politika: {len(uyumlu)}/{len(politikalar)} | toplam hata: {hata}")
sys.exit(1 if hata else 0)
PY
```

### 2026-08-17 11:45 itibarıyla gerçek çıktı

Betik bu makinede çalıştırıldı. Sonuç:

| Kontrol | Sonuç |
|---|---|
| Şemaya uyumlu politika | **6 / 9** — `seller-logo.json` (32 hata), `brand-logo.json` (32 hata), `company-cover-video.json` (11 hata) uyumsuz (§5) |
| D1 profilsiz slot | **0** — 6 uyumlu politikanın hepsinde profil var (2, 3, 3, 5, 7 ve 1 profil) |
| D2 `derived_from` / `serves` eksik profil | **0** — şema `derived_from`'u zorunlu kılıyor |
| D2 master'dan büyük profil | **0** |
| D3 tanımsız `message_key` | **0** |
| D4 master invaryantı | **0** — `user.avatar`'da yuvarlama yönü düzeltildi (0,0656 → 0,0655; 256²/1e6 = 0,065536) |
| D4 `status=active` + açık soru | **0** — 6 politikanın hepsi `draft`, hepsinde açık soru var, hepsinde bazı `encoder_quality.avif` **null**. **Hiçbiri `active` olamaz** ve olmamalı |
| D5 politika var `.md` yok | **0 rapor edildi** — dikkat: D5 yalnız şemaya uyumlu dosyalarda çalışır. `seller-logo` ve `brand-logo` şema aşamasında `continue` ile atlandığı için D5'e hiç girmiyor; ikisinin de `.md` karşılığı **gerçekte yok**. Şema uyumsuzluğu giderildiğinde bu satır 2 olacaktır |
| Ters yön (`.md` var politika yok) | **5 bilgi satırı** — `dpi-ve-cozunurluk`, `icerik-kurallari`, `kota`, `logo`, `retention`. Bunlar slot değil **konu belgesi**; hata değil |
| Betiğin çıkış kodu | **1** (3 şema hatası nedeniyle) — CI'da bu kod başarısızlık demektir |

> **Not:** klasöre paralel görevler yazdığı için bu tablo bir **anlık
> görüntüdür**. Betiği yeniden çalıştırmak güncel sonucu verir.
>
> **Betiğin bilinen kör noktası:** şema hatası olan bir dosya `continue` ile
> atlanır, dolayısıyla D1-D5 o dosyada hiç çalışmaz. Yani "0 hata" gördüğün
> değişmez, yalnız **şemaya uyumlu** dosyalar için geçerlidir. Şema uyumu
> önce sağlanmalı.

### 2026-08-17 13:01 itibarıyla gerçek çıktı — GÜNCELLENDİ

Betik aynı makinede yeniden çalıştırıldı (`jsonschema` 4.25.1). Değişen
satırlar:

| Kontrol | Yeni sonuç | Değişim sebebi |
|---|---|---|
| Şemaya uyumlu politika | **7 / 9** — uyumsuz kalanlar: `seller-logo.json` (**40** hata), `brand-logo.json` (**40** hata) | `company-cover-video.json` şemaya taşındı (§5). İki logo dosyasının hata sayısı 32 → 40: dosyalar bu arada yazılmaya devam etti ve şema v1.1.0 üç yeni üst düzey alan tanımladığı için hata dökümü yeniden hesaplandı — **dosyalara dokunulmadı** |
| D1 profilsiz slot | **0** — 7 uyumlu politikanın hepsinde profil var (2, 3, 3, 5, 7, 1 ve 3 profil) | `company.cover_video` 3 profille katıldı: `poster_1280`, `poster_854`, `thumb_192` |
| D2 / D3 / D4 | **0** (değişmedi) | `company.cover_video`'nun 12 `content_rules` kuralının `message_key`'lerinin hepsi `messages.tr` içinde tanımlı; master invaryantı 1280²/1e6 = 1,638 ≥ 0,93 |
| D5 politika var `.md` yok | **0** (değişmedi) | `docs/standards/company-cover-video.md` zaten vardı |
| Betiğin çıkış kodu | **1** (2 şema hatası nedeniyle) | CI'ya girmeden önce T-030/D (5-B.6) kapatılmalı |

Ek doğrulamalar (aynı çalıştırma):

- Şema dosyasının kendisi geçerli bir **draft 2020-12** şeması:
  `jsonschema.Draft202012Validator.check_schema()` → hata yok.
- Şemanın `required` listesindeki 10 alanın **9 / 9 dosyada** tamamı mevcut
  (bu kontrol şema uyumsuz iki logo dosyasında da geçiyor — onların sorunu
  eksik alan değil, **fazla** alan).
- `video.poster.profile` / `fallback_profile` değerleri `profiles[].name`
  içinde tanımlı: `company-cover-video` → `poster_1280` / `poster_854`,
  `product-video` → `poster_1024` / `poster_192`.
- `video.validation_codes[].message_key` değerlerinin hepsi `messages.tr`
  içinde tanımlı; `company-cover-video`'da `messages.tr` ve `messages.en`
  anahtar kümeleri **birebir aynı** (17 anahtar).
- `tests/test_policy_dpi.py`: **19 test, hepsi geçiyor** (1 beklenen
  başarısızlık) — bu değişiklikler DPI policy setine dokunmadı.

### Betiğin ölçmediği — ve neden

| Kontrol | Neden yapılamadı |
|---|---|
| **Slot ↔ gerçek yükleme yolu eşleşmesi** | Kodda slot kimliği yok (`upload_policy.py:307-313`). "Her yükleme yolunun bir slotu var mı?" sorusu ancak B1 çözüldükten sonra programatik olarak sorulabilir. Bugün elle: `docs/reports/00-upload-slot-envanteri.md` Tablo A/B/C. |
| **Profilin gerçekten üretilip üretilmediği** | Türev üretimi **yok**: bir yükleme → bir dosya (`docs/reports/03-render-envanteri.md` §6.3). Tüm `profiles[]` girdileri bugün **kağıt üzerinde**. |
| **Eşiklerin doğruluğu** | Üretim verisi gerekiyor. Her `.md` dosyasının son bölümü ("ÜRETİMDE DOĞRULANMALI") çalıştırılacak tam komutları içerir. |
| **`bound_to` alanlarının gerçekten var olduğu** | Frappe metadata sorgusu gerekiyor. Kontrol: `frappe.db.sql("select parent, fieldname from tabDocField where fieldname = %s", alan)`. Bu görevde `admin_seller_profile.json` ve `product_category.json` **elle** doğrulandı; `header_bg_image` **bulunamadı** (E2). |

---

## 7. ÜRETİMDE DOĞRULANMALI — ortak liste

Docker kapalı; üretim veritabanına ve canlı siteye erişim yok. Bu klasördeki
**hiçbir sayı ölçüm değil**: CSS kutuları kaynak koddaki utility sınıflarından
okundu ve Tailwind ölçeğiyle px'e çevrildi (`1rem = 16px`); kırılımlar
`tradehubfront/src/style.css:256-260`'tan alındı (bu projede `sm=480`, `md=640`,
`lg=768`, `xl=1024` — **Tailwind varsayılanı değil**).

Slot bazlı komutlar ilgili `.md` dosyasının son bölümündedir:

| slot | bölüm | en kritik ölçüm |
|---|---|---|
| `product.video` | `product-video.md` §8 | ffmpeg/ffprobe imajda var mı (§8.1) — yoksa **hiçbir video normalize edilmiyor** |
| `company.cover_image` | `company-cover-image.md` §8 | `header_bg_image` / `tr_tradehub` gerçekten var mı (§8.1) |
| `category.banner` | `category-banner.md` §8 | Bento `columns` değeri ve span dağılımı (§8.2) — profil basamakları buna bağlı |
| `user.avatar` | `user-avatar.md` §8 | 256 px'den büyük avatar sayısı (§8.2) — israfın tek sayısı |
| `document.attachment` | `document-attachment.md` §7 | `Shipment Document` / `Data Processing Agreement` küçültülmüş mü (§7.1) |

Ayrıca tüm slotlar için ortak, envanter raporlarında zaten yazılı olanlar:

- **Gerçek oran dağılımı:** `docs/reports/00-upload-slot-envanteri.md` §9-M5
- **Slot başına dosya sayısı ve toplam bayt:** aynı belge §9-M6
- **Frappe `max_file_size` gerçek değeri:** aynı belge §9-M7 (ilan edilen
  200 MB'ın gerçekleşip gerçekleşmediği buna bağlı)
- **`LIVE_SOURCES` eksiğinin bedeli:** aynı belge §9-M8
- **Lighthouse / LCP / CLS:** `docs/reports/03-render-envanteri.md` §7.1

---

## 8. Bu klasörü genişletirken

1. **Şema ilk.** Yeni politika `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json`'a
   uymalı; §6 betiği CI'da çalıştırılabilir.
2. **`sources` zorunlu.** Şema `provenance` biçimini dayatıyor: `dosya:satır`,
   `docs/... §bölüm`, `hesap: <formül>` ya da `ÖLÇÜLMEDİ: <ne yapılmalı>`.
   "bilinmiyor" yazılamaz.
3. **Profil uydurulamaz.** Her profil `derived_from` ile somut bir CSS kutusu ×
   DPR hesabına dayanmalı. Kutular `docs/reports/03-render-envanteri.md` §3'te.
4. **Ölü render'a göre standart yazma.** E8'deki dört bileşen bunun canlı
   örneği; `grep` ile mount edildiğini doğrula.
5. **Çözülmüş şeyi kural yapma.** Kural 5. Örnek: `category.banner`'da alt
   şerit metin kuralı `ignore` — `CategoryShowcase.ts:154` gradient scrim'i
   sorunu zaten çözüyor.
6. **`active`'e geçiş kapısı:** `open_questions` boş **ve** hiçbir
   `encoder_quality` `null` olmayacak. Bugün 6 politikanın **hiçbiri** bu kapıyı
   geçemiyor — ve geçmemeli.
7. **Video slotu yazıyorsan `video` bloğunu kullan** (şema v1.1.0).
   `profiles[]` video slotunda **poster ve küçük resim görsellerini** tanımlar
   (`<picture>` kaynağı); teslim edilen video türevleri
   `video.renditions[]` altına yazılır (`<video><source>` kaynağı). İkisini
   karıştırmak §4 E10'un tekrarıdır. `video.poster.profile` bir
   `profiles[].name` değerine işaret **etmek zorundadır**.
   `video` bloğu **opsiyoneldir** ve görsel slotlarında yazılmaz;
   `schema_version` "1.0.0" yazan politikalar geçerliliğini korur.
8. **Yeni bir alanın kapsamda olup olmadığını `slot_key`'e bakarak sorma.**
   Kapsam sorusu her zaman gerçek `doctype.field` üzerinden sorulur —
   üç ayrı adlandırma ailesi var (§5-B.2) ve `bound_to` üzerinden kapsanan
   alanların `slot_key`'i kendi adını taşımaz. Kontrol betiği 5-B.7'de.
