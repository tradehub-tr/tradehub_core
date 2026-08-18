# T-028 — Mevcut medyanın standartlaştırma (migration) planı

**Faz 2 · 2026-08-17 · Çalıştırılabilir hâli: `scripts/plan_backfill.py` (yazıldı, ÇALIŞTIRILMADI)**

---

## 0. Bu plan ne yapar, ne yapmaz

**Yapar:** bugünkü medya kümesini hedef standarda taşımanın sırasını, kapasitesini,
geri alma yolunu ve durdurma kriterini kodda var olan mekanizmalar üzerinden yazar.

**Yapmaz:**
- Ölçüm yapmaz. Docker kapalı, üretim DB'sine ve canlı siteye erişim yok. Bu belgedeki
  her sayının yanında ya `dosya:satır` ya da "türetilmiş / ÖLÇÜLMEDİ" etiketi var.
- Yeni bir optimizasyon motoru, yeni bir kuyruk soyutlaması, yeni bir arşiv düzeni
  tasarlamaz. Bunların hepsi kodda var (§4.1) ve bu plan onların **üstüne** kurulur.

### 0.1 Yöntem — bu belgedeki bilgi nereden geldi

| # | Kaynak | Ne için kullanıldı |
|---|---|---|
| S1 | `docs/MEDYA-DEPOLAMA-STANDARDI.md` | 2.166 tahmin-edilebilir ad, 2.858/192 dosya, ~2.400 referans, retro-rename ertelemesi |
| S2 | `docs/reports/02-medya-istatistigi.md` | Sayıların mutabakatı ve **9 tutarsızlık** (T-1…T-9) |
| S3 | `docs/reports/00-upload-slot-envanteri.md` | 41 doctype alanı, slot_key önerisi, B1–B8 sistemik eksikler |
| S4 | `docs/reports/03-render-envanteri.md` | CSS kutu ölçüleri, @1x/@2x/@3x talepleri, §3.9 profil eşiği önerisi |
| S5 | `docs/reports/06-depolama-maliyet.md` | Profil matrisi (§1.2), varlık sınıfı başına türev sayısı (§1.4) |
| S6 | `tradehub_core/media/*.py` (21 modül) | Mevcut kapılar, arşiv, runner, refs, usage, naming — okunan gerçek davranış |
| S7 | `docker/docker-compose.yml:163-175` | `queue-short` / `queue-long` worker tanımları |
| S8 | `tradehubfront/nginx.conf.template` + `docker/nginx/storefront.local.template` | TUR-141 sertleştirmesinin gerçek durumu (§8.1) |

> **En önemli uyarı (S2'den):** Bu kod tabanında "public dosya sayısı" için **on
> ayrı sayı** var (938 / 2.826 / 2.839 / 2.858 / 2.860 / 4.003 / 4.007 / 4.195 /
> 4.324 / 4.800 / 4.900 — `02-medya-istatistigi.md` §2.2). Hiçbiri doğrulanmadı.
> **Bu plandaki hiçbir kapasite kararı bu sayılardan birine sabitlenmemiştir**;
> hepsi formül olarak yazıldı, sayı `plan_backfill.py` çıktısından gelecek.

---

## 1. İki ayrı migration var — karıştırılmamalı

Görev tanımı ikisini de içeriyor ama bunlar **farklı riskler, farklı ölçekler ve
farklı ön koşullar** taşıyor. Tek iş gibi planlanırsa küçük olan büyük olanı bloke eder.

| | **M-A · İçerik standardizasyonu** | **M-B · Ad standardizasyonu (retro-rename)** |
|---|---|---|
| Ne değişir | Dosyanın **baytları** (piksel tavanı, renk uzayı, metadata) | Dosyanın **adı ve `file_url`'i** |
| `file_url` | **DEĞİŞMEZ** — `archive.py:5-6`, `engine.py:8-9` bunu açıkça garanti ediyor | **DEĞİŞİR** — migration'ın tanımı bu |
| Referans etkisi | **SIFIR** | ~2.378–2.400 referans (S1 `:152-153`) + gömülü JSON |
| 301 haritası | Gerekmez | Gerekir (2.166 girdi) |
| Kodda mekanizma | **VAR ve çalışıyor** (`runner.run_batch`, `archive`, `gates`) | **KISMEN** (`refs.retarget` var ama 7/23 alanı kapsıyor — §8.3) |
| Geri alma | **VAR** (`runner.restore_batch`, 30 gün) | **YOK** — yazılması gerekir |
| Ölçek | Kapı 4'ü geçen dosya sayısı kadar (gates.py:8: 4.007'de ~300) | 2.166 dosya (S1 `:150`) |
| Bu plandaki yeri | §2–§7 | §8 |

**Karar: M-A ve M-B ayrı ayrı yürütülür ve M-A önce gelir.** Gerekçe: M-A `file_url`'e
dokunmadığı için geri alınabilir ve referans riski yok; M-B'nin ön koşulu ise henüz
karşılanmamış (§8).

---

## 2. Slot bazında uyumlu/uyumsuz sayımı

### 2.1 Bugün NEDEN sayılamıyor — slot kayıt defteri yok

Bu, planın en sert kısıtı ve yeniden tasarlanacak bir şey değil, **belgelenecek bir eksik**:

- `File` doctype'ında slot bilgisi tutan **hiçbir alan yok**. `media/metadata.py:37-45`
  `_FIELD_MAP`'te `th_media_title/alt/description/tags/favorite/width/height` var —
  slot yok.
- `upload_policy.check()` imzası slot parametresi **almıyor**:
  `media/upload_policy.py:307-313` yalnız `file_name`, `content`, `size`,
  `media_endpoint` alıyor. S3 §7-B1 bunu zaten kaydetmiş.
- Dolayısıyla `select slot, count(*) from tabFile group by slot` **yazılamaz.**

### 2.2 Slot'un bugün uygulanabilir tek tanımı: ters referans

Slot bilgisi dosyada değil, **dosyayı gösteren alanda** duruyor. `media/usage.py`
bu eşlemeyi zaten `(tablo, kolon, tür, etiket)` dörtlüsü olarak tutuyor:

```
LIVE_SOURCES     8 çift   media/usage.py:31-42
ORDER_SOURCES    2 çift   media/usage.py:46-49
HISTORY_SOURCES  6 çift   media/usage.py:53-60
                ─────
                16 çift
```

Yani **slot ≈ `usage.py`'deki `kind` alanı**. `plan_backfill.py` slot atamasını
`usage._match_rows()` + `usage._urls_in()` ile yapar — bu iki fonksiyon yeniden
yazılmaz, import edilir (JSON kaçış varyantı `_search_variants`, `LOCATE` yerine
`LIKE` kullanmama kuralı ve chunk mantığı orada zaten çözülmüş).

### 2.3 Kapsam tavanı — bu sayımın üst sınırı %70 değil, en fazla %70

| Metrik | Değer | Kaynak |
|---|---:|---|
| `information_schema` taramasıyla bulunan, görsel URL'i geçen alan | **23** | `media/usage.py:8` |
| `usage.py`'de kayıtlı `(tablo, kolon)` çifti | **16** | `usage.py:31-60` (8+2+6) |
| Hiçbir kaynak listesinde olmayan alan | **7** | `23 − 16`, benim çıkarmam |
| S3 Tablo A'daki doctype alanı sayısı | **41** | `00-upload-slot-envanteri.md` §2 |

**Sonuç:** ters referansla üretilen slot dağılımı **eksiktir ve eksikliği yönlüdür**:
kayıtlı olmayan bir alanda geçen dosya "hiçbir slota ait değil" görünür. S3 §7-B6
eksik olanları tek tek sayıyor (`Admin Seller Profile.banner_image`,
`Product Category.image`, `Category Showcase Tile.image`, `Brand.logo`,
`Brand.hero_banner`, `Hero Slide.background_image`, `Logistics Provider.logo`,
`Shipping Channel.icon`, `Verification Source.icon`, `Static Page SEO.og_image`,
`Seller Product.image`, `Seller Gallery Image.poster_image`,
`Listing Variant Item.variant_video_url`, `Seller Category.image` +
RichTextEditor ile içeriğe gömülenler).

> **Bu, migration'ın kendisinden ÖNCE kapatılması gereken bir açıktır.** `LIVE_SOURCES`
> eksik olduğu sürece "bu dosya hangi slotta, hedefi ne" sorusu 14+ alan için
> cevapsız kalır ve o dosyalar C sınıfına (yok sayılabilir) yanlış olarak düşer.
> Ön koşul olarak §9-Ö2'ye yazıldı.

### 2.4 Slot başına uygunluk ölçütü

Ölçütler **türetilmiştir**: kaynak = S4'teki gerçek CSS kutu ölçüleri ve S5 §1.2
profil matrisi. Karar değil, öneridir (S4 §3.9 de aynı uyarıyı taşıyor).

| slot_key (`usage.py` `kind`) | En büyük render kutusu | Kaynak | Uygulanan profil (S5 §1.2) | **Gerekli kaynak genişlik** | Oran kuralı |
|---|---:|---|---|---:|---|
| `listing_main` (`tabListing.primary_image`) | 512 px PD ana; 636 px lightbox; hover-zoom | S4 §3.5, §3.8 | product-main (1600), **product-zoom (2400)** | **2400** | 1:1 (`object-contain` ana, `object-cover` kart) |
| `listing_gallery` (`tabListing Image.image`) | aynı galeri | S4 §3.5, §3.8 | aynı | **2400** | 1:1 |
| `variant_main` (`Listing Variant Item.variant_image`) | ÖLÇÜLEMEDİ (S3 Tablo A) | — | product-card (640) | **640** (alt sınır) | 1:1 |
| `variant_gallery` (JSON dizi) | ÖLÇÜLEMEDİ | — | product-card (640) | **640** | 1:1 |
| `seller_gallery` (`Seller Gallery Image.image`) | 276×276 px (lg) | S3 Tablo A | product-card (640) | **640** | **1:1 zorunlu** — `object-cover`, kare değilse merkezden kırpılıyor, uyarı yok |
| `seller_logo` (`Admin Seller Profile.logo`) | 120 px | S3 Tablo A | logo-square (256) | **256** | serbest (`object-contain`) |
| `storefront` (`Storefront Layout.sections`) | 1200×400 px → lg | S3 Tablo C `panel.layout_slide` | company-cover (1920) | **1920** | **ÇÖZÜLEMEZ** — aynı slayt 180/220/320/400 px yükseklikte, oran 6,7:1 → 3:1 arası değişiyor (S3 §7-B2). Tek görselle karşılanamaz |
| `listing_video` (`Listing.video_url`) | ÖLÇÜLEMEDİ | — | — | — | 16:9 (varsayım) |
| `cart_snapshot`, `order_receipt` | — | — | — | — | **C sınıfı** — sistem kopyası / dekont, dokunulmaz |

**Sınıflandırma için kullanılan üç ölçüt (hepsi kodla ölçülebilir):**

1. **Piksel tavanı:** `max(width,height) > presets.PRESETS["balanced"]["max_dim"]`
   → `2000` (`media/presets.py:15`). Kapı 4'ün eşiğinin ta kendisi (`gates.py:71`).
2. **Piksel tabanı:** `max(width,height) < gerekli_kaynak_genişlik` (yukarıdaki tablo).
   **Yükseltme (upscale) yapılamaz** — `engine.py:117` `im.thumbnail(...)` yalnız küçültür
   ve satır içi yorum bunu açıkça yazıyor.
3. **Oran sapması:** `|w/h − hedef_oran| / hedef_oran > tolerans`. Tolerans kodda
   **hiç yok** (S3 §7-B2: en-boy oranı yazan tek yer `OgImageUpload.vue:57` ve o da
   yalnız önizleme). `plan_backfill.py` varsayılan **%5** kullanır — bu bir öneridir.

### 2.5 ⚠️ Migration'ın en kritik çelişkisi: 2000 px tavanı vs 2400 px hedefi

Bu, sırası yanlış kurulursa **geri dönülemez** olan tek maddedir:

```
presets.py:15      balanced.max_dim = 2000     ← optimize edilen dosyanın YENİ tavanı
engine.py:177      im.thumbnail((1920, 1920))  ← to_webp() yolunun AYRI, sabit tavanı
06 §1.2            product-zoom  → 2000, 2400  ← hedef profilin istediği genişlik
presets.py:38      ARCHIVE_RETENTION_DAYS = 30 ← orijinalin ömrü
archive.py:113-153 purge_expired()             ← 30 günden eskiyi SİLER
```

Zincir:

1. `runner._process_one` (runner.py:229) dosyayı **2000 px'e indiriyor** ve
   `_write_original` (runner.py:255-265) ile **dosyanın kendi yoluna üzerine yazıyor**.
2. Orijinal `archive.store` (runner.py:248) ile `private/image_originals/` altına kopyalanıyor.
3. `archive.purge_expired` 30 gün sonra o kopyayı **siliyor** (`archive.py:131-136`).
4. O andan sonra 2400 px'lik `product-zoom` türevi **hiçbir şekilde üretilemez** —
   ne diskte ne arşivde 2000 px üstü piksel kalmıştır.

Ayrıca **iki farklı tavan** var: `optimize()` yolu 2000 px (`presets.py:15`),
`to_webp()` yolu **1920 px sabit** (`engine.py:177`, presets'ten okumuyor). Aynı
dosya hangi yoldan geçtiğine göre farklı tavana takılıyor.

**Zorunlu sıra kararı:**

> Türev seti (`srcset`) kararı verilmeden **yeni hiçbir optimizasyon koşusu
> başlatılmaz.** Karar 2400 px içeriyorsa `presets.py` tavanı **önce** yükseltilir.
> Bugüne kadar optimize edilmiş ve arşivi purge edilmiş dosyalar için 2400 px
> **kalıcı olarak kayıptır** ve o dosyalar B sınıfına (satıcı yeniden yükler) düşer.

Kaç dosyanın bu durumda olduğu **BİLİNMİYOR.** `inventory.summary()["optimized_count"]`
(`media/inventory.py:391-397`) bugünkü optimize sayısını verir; arşivde kaçının
kopyası kaldığı `archive.usage_bytes()` (`archive.py:98-110`) + dosya sayımıyla
ölçülür. Komutlar §10-D3.

### 2.6 Slot × uyum sayım sorgusu

Tam çalıştırılabilir hâli `scripts/plan_backfill.py` → `slot_compliance()`.
SQL'de tek başına **üretilemez**, üç sebeple:

| Neden SQL yetmiyor | Kanıt |
|---|---|
| Çözünürlük sütunları **tembel** doldurulur; dolu olma oranı bilinmiyor | `media/metadata.py:159-196` (`ensure_dimensions` çağrılmadıkça yazılmaz) |
| `Probe` dataclass'ında `mode` alanı yok → renk uzayı DB'de hiç yok | `media/engine.py:53-66` |
| Slot ataması `LOCATE` ile 16 tabloya ters tarama gerektiriyor | `media/usage.py:107-136` |

Bu yüzden `plan_backfill.py` **iki geçişli** çalışır: (1) SQL ile küme ve kapsam,
(2) diskten `engine.probe()` ile gerçek piksel/format. `dimension_coverage()`
(`scripts/media_stats.py:419-457`) kapsamı önce ölçer — kapsam yüksekse disk
geçişi atlanabilir.

---

## 3. Uyumsuzların sınıflandırması

### 3.1 A sınıfı — otomatik düzeltilebilir

**Bu sınıfın büyük kısmı ZATEN ÇÖZÜLMÜŞ.** Kural 5 gereği ne çözülmüş, ne çözülmemiş
tek tabloda:

| Uyumsuzluk | Bugünkü durum | Kanıt | Backfill'de yapılacak |
|---|---|---|---|
| **Piksel tavanı** (>2000 px) | ✅ **ÇÖZÜLMÜŞ** — Kapı 4 tam olarak bunu yapıyor; `optimize()` `max_dim`'e küçültüyor | `gates.py:70-72`, `runner.py:229`, `engine.py:117` | Mevcut `run_batch` çağrılır. Yeni kod YOK. **Ama §2.5 sırası zorunlu** |
| **Renk uzayı — JPEG CMYK** | ⚠️ **KISMEN** — `convert("RGB")` var **ama yalnız 6 kapıyı da geçen dosyada**. Kapı 4'e takılan CMYK JPEG tarayıcıya CMYK gider | `engine.py:121` | CMYK dosyaları **kapılardan bağımsız** ele alan ayrı bir geçiş gerekir → **YENİ İŞ** |
| **Renk uzayı — TIFF CMYK** | ❌ **BİLEREK ÇÖZÜLMEMİŞ** — TIFF `convert("RGB")` yapılmıyor, gerekçe satır içinde yazılı (alpha + renk yönetimi) | `engine.py:127-131` | Karar gerektirir; TIFF sayısı çok küçük (`engine.py:45`: 8 dosya, 101,7 MB ölçümü) → tek tek elle |
| **Renk uzayı — tespit** | ❌ **TESPİT DAHİ EDİLEMİYOR** — `Probe`'da `mode` yok | `engine.py:53-66` | `plan_backfill.py` PIL `im.mode`'u diskten okur (motor değiştirilmeden) |
| **Metadata — EXIF rotasyon** | ✅ **ÇÖZÜLMÜŞ** — `exif_transpose` ile pikseller fiziksel döndürülüyor | `engine.py:116`, gerekçe `engine.py:11-13` | Yok |
| **Metadata — ICC profili** | ✅ **ÇÖZÜLMÜŞ** — transpose'tan önce alınıp çıktıya taşınıyor | `engine.py:115,122,126,131` | Yok |
| **Metadata — EXIF temizliği** | ⚠️ **YAN ETKİ** — JPEG'de `convert("RGB")` EXIF'i düşürüyor; PNG/TIFF/WEBP yolunda **düşmüyor**. Kasıt değil, sonuç | `engine.py:121` vs `:126,131,133` | GPS/kamera seri no gibi PII taşıyan EXIF için **açık** bir strip adımı yok → **YENİ İŞ** |
| **DPI normalizasyonu** | ❌ **HİÇ YOK** — kod tabanında DPI okuyan/yazan tek satır bulunamadı; `Probe`'da alan yok, `optimize()` `dpi=` parametresi geçmiyor | `engine.py:53-66`, `:96-145` | Web servisi için DPI **anlamsızdır** (piksel boyutu bağlayıcıdır). Öneri: **hiç ele alınmasın**, yalnız baskıya giden PDF/TIFF için ölçülsün → §10-D5 |
| **0 bayt dosya** | ⚠️ **KISMEN** — `CONTENT_EMPTY` reddi var ama **yalnız `content` verilmişse** | `upload_policy.py:353-355` | Geriye dönük tarama yok; `plan_backfill.py` sayar |
| **Uzantı–içerik uyuşmazlığı** | ⚠️ **BİLİNÇLİ olarak reddedilmiyor** — zararsız uyuşmazlık uyarıya yazılıyor, yalnız tehlikeli içerik (`<svg`, `<script`) reddediliyor. Ölçüm: "1500 dosyada 0 uyuşmazlık" | `upload_policy.py:24-28`, `:187-195`, `:357-369` | Geriye dönük tarama yok; `plan_backfill.py` sayar (`upload_policy.sniff` import edilerek) |

**A sınıfının backfill'e giren gerçek kapsamı:** yalnız **piksel tavanı** bugün
tek satır kod yazmadan işlenebilir. CMYK-kapı-dışı, açık EXIF strip ve geriye dönük
uzantı taraması **yeni iş kalemleridir** ve bu migration'ın kapsamında değil —
tespit edilir, sayılır, ayrı görev açılır.

### 3.2 B sınıfı — satıcının yeniden yüklemesi gerekir

Bunlar **hiçbir sunucu işlemiyle** düzeltilemez, çünkü eksik piksel üretilemez.

| Alt sınıf | Ölçüt | Neden otomatik düzeltilemez |
|---|---|---|
| **B1 · Yetersiz çözünürlük** | `max(w,h) < gerekli_kaynak_genişlik` (§2.4) | `engine.py:117` yalnız küçültür — upscale yok ve olmamalı (yapay detay) |
| **B2 · Tavan yüzünden kayıp** | Dosya `th_optimized_at` dolu **ve** `max(w,h) ≤ 2000` **ve** hedef 2400 **ve** arşiv kopyası yok | §2.5 zinciri; `archive.exists(file_url)` (`archive.py:60-61`) ile kontrol edilir |
| **B3 · Kötü oran** | `seller_gallery` 1:1 bekliyor, kaynak kare değil | `object-cover` merkezden kırpıyor (S3 Tablo A satır `seller.gallery_image`); kırpma sunucuda yapılabilir ama **hangi bölge korunacağı bilinemez** — satıcının kararı |
| **B4 · Çözülemez slot** | `storefront` slaytı (oran 6,7:1 → 3:1 arası değişken) | S3 §7-B2. Tek görsel matematiksel olarak yetmez; art direction gerekir → satıcıdan **iki** görsel istenir |
| **B5 · Okunamayan dosya** | `probe.readable == False` | `engine.probe` `readable=False` döner (`engine.py:92-93`); içerik bozuk |
| **B6 · 0 bayt** | `file_size == 0` veya diskte 0 bayt | Yeniden yükleme dışında yol yok |

### 3.3 C sınıfı — yok sayılabilir

Bu dosyalara **hiç dokunulmaz** ve satıcıya **bildirilmez**. Sınıf, kodda zaten
tanımlı kapsam-dışı listelerinden türetilir — elle liste yazılmaz:

| Alt sınıf | Kaynak (tek doğruluk kaynağı) |
|---|---|
| Hassas doctype eki | `presets.EXCLUDED_DOCTYPES` — 8 doctype, `presets.py:44-53` |
| `attached_to_doctype` boş hassas belge | `presets.EXCLUDED_MEDIA_FIELDS` — 5 doctype / 7 alan, `presets.py:70-76`. **Uyarı:** S3 §7-B5 bu haritanın KYB'nin yalnız 2 alanını saydığını gösteriyor; 4 alan eksik |
| Private düzlem | `runner._assert_in_scope` `doc.is_private` reddediyor, `runner.py:141-143` |
| Hassas belgenin public ikizi | `runner._has_sensitive_twin`, `runner.py:183-192` (ölçüm: 44 dosya, 6'sı panelde listeli — `inventory.py:71-75`) |
| Sipariş/geçmiş kopyası | `usage.ORDER_SOURCES` (`usage.py:46-49`) — `refs.READONLY_TABLES` bunları hiç yazmıyor (`refs.py:42`) |
| Çöp kutusu / arşiv | `states.STATE_TRASHED`, `trash.TRASH_DIRNAME`, `presets.ARCHIVE_DIRNAME` — bu kökler `File` kaydı üretmez (S1 §3.2) |
| Motorun işlemediği format | `engine.SUPPORTED_FORMATS` = {JPEG, PNG, WEBP, TIFF} (`engine.py:21`); AVIF/GIF/BMP `FORMAT_EXTENSIONS`'ta var ama `SUPPORTED_FORMATS`'ta **yok** → `unsupported_format` |
| 200 KB altı | `presets.MIN_FILE_SIZE` (`presets.py:22`), Kapı 1 (`gates.py:58-59`) |

> **Kapsam kararı ikinci kez uygulanır ve bu bilinçli.** `runner._assert_in_scope`
> (`runner.py:129-161`) istemciden gelen listeye güvenmiyor; docstring'de gerekçe
> ölçümle yazılı ("27 dosya tüm kapıları geçiyordu"). Backfill planlayıcısı C sınıfını
> filtrelese bile runner tekrar kontrol eder — bu katman **kaldırılmamalı**.

### 3.4 Karar ağacı (tek tabloda)

```
dosya
 ├─ is_private=1  ya da  file_url '/files/' ile başlamıyor        → C  (runner.py:141)
 ├─ attached_to_doctype ∈ EXCLUDED_DOCTYPES                       → C  (presets.py:44)
 ├─ content_hash hassas ikize sahip                               → C  (runner.py:156)
 ├─ EXCLUDED_MEDIA_FIELDS ters referansı var                      → C  (presets.py:70)
 ├─ th_media_state ∈ {Trashed}                                    → C  (states.py:50)
 ├─ file_size < 200 KB                                            → C  (gates.py:58)
 ├─ probe.readable = False                                        → B5
 ├─ file_size = 0                                                 → B6
 ├─ probe.fmt ∉ SUPPORTED_FORMATS                                 → C  (gates.py:64)
 ├─ probe.animated                                                → C  (gates.py:67)
 ├─ max(w,h) < gerekli_kaynak_genişlik(slot)                       → B1
 ├─ th_optimized_at dolu ∧ max(w,h) ≤ 2000 ∧ hedef > 2000
 │        ∧ archive.exists() = False                              → B2  (§2.5)
 ├─ |oran − hedef_oran| > %5                                      → B3
 ├─ slot = storefront                                             → B4  (S3 §7-B2)
 ├─ max(w,h) > 2000                                               → A   (Kapı 4 geçer)
 ├─ probe.mode = CMYK ∧ max(w,h) ≤ 2000                            → A' (kapı dışı — YENİ İŞ)
 └─ hiçbiri                                                       → UYUMLU
```

`A'` işareti kasıtlı: bugünkü `run_batch` bu dosyaya **dokunmaz** (Kapı 4 `already_small`
der). Yani "otomatik düzeltilebilir" ama **mevcut kodla değil**.

---

## 4. Backfill planı

### 4.1 Mevcut mekanizma — yeniden tasarlanmayacak

Backfill için yeni bir worker, yeni bir arşiv, yeni bir ilerleme kaydı **yazılmayacak**.
Aşağıdakiler kodda var:

| Parça | Konum | Davranış |
|---|---|---|
| Toplu işleyici | `media/runner.py:53-126` `run_batch` | Sırayla işler, ilerleme yazar, `COMMIT_EVERY`'de commit'ler |
| Kapılar | `media/gates.py:42-85` | 6 kapı, hepsi zorunlu; biri bile geçmezse dosyaya dokunulmaz |
| Kuru koşu | `run_batch(dry_run=1)` | Kapılar + dönüşüm çalışır, **diske hiçbir şey yazılmaz** (`runner.py:243-245`) |
| Arşiv | `media/archive.py:64-79` `store` | Orijinali `private/image_originals/`'a yazar; **üzerine yazmaz** (`:73-74`) |
| Geri alma | `media/runner.py:293-365` `restore_batch` / `restore_original` | Arşivden geri yazar, damgayı temizler |
| İlerleme | `runner.progress_key` + Redis, TTL 3600 s (`presets.py:28`) | `read_progress(job_key)` |
| Denetim | `audit.log_media_batch` (`runner.py:112-125`) | **İş başına tek kayıt** — 2.800'lük işte ADL şişmesin |
| Durum makinesi | `media/states.py` | `Active → Archived` geçişi damgayla birlikte yazılıyor (`runner.py:290`) |
| Kapsam koruması | `runner._assert_in_scope` (`runner.py:129-161`) | Yazma yolunun üzerinde ikinci kez |

**Yazılacak tek şey: orkestratör.** Batch'leri kesen, aralarda hata oranını okuyan,
eşik aşılırsa **enqueue etmeyi bırakan** ince bir katman. `plan_backfill.py`
bu orkestratörün **planını** üretir (çalıştırmaz).

### 4.2 Batch boyutu — timeout aritmetiği

Sabitler:

| Sabit | Değer | Kaynak |
|---|---:|---|
| Kuyruk işi timeout'u | **3600 s** | `api/media_admin.py:211` (`timeout=3600`) |
| İstemciden gelen listede üst sınır | **2000 dosya** | `api/media_admin.py:40` (`MAX_BATCH`) |
| Commit / ilerleme aralığı | **10 dosya** | `presets.py:31` (`COMMIT_EVERY`) |
| İlerleme kaydı TTL | **3600 s** | `presets.py:28` (`PROGRESS_TTL`) |

Dosya başına zaman bütçesi = `3600 / N` (saf aritmetik):

| N (batch boyutu) | Dosya başına bütçe | Not |
|---:|---:|---|
| 2000 | **1,8 s** | `MAX_BATCH` üst sınırı. 20 MP'lik bir TIFF'i Pillow ile açıp yeniden encode etmek için gerçekçi değil |
| 500 | **7,2 s** | |
| **200** | **18 s** | **Önerilen** |
| 100 | **36 s** | Çok güvenli; iş sayısı 2× artar |

> `scope="pending"` ile çağrıldığında `MAX_BATCH` **uygulanmıyor** —
> `api/media_admin.py:197-202` yorumu bunu bilinçli olarak yazıyor ("sunucunun kendisi
> ürettiği için güvenilir ve sınırlanmaz"). Yani "tümünü optimize et" bugün **tek bir
> 3600 s'lik işe** tüm kümeyi koyuyor. **Backfill bu yolu KULLANMAMALI**; batch'ler
> dışarıdan kesilip `scope="selected"` ile gönderilmeli.

**Timeout kesilmesinin gerçek sonucu (kod okumasından türetilmiş, ölçülmedi):**

RQ işi timeout'ta öldürüldüğünde son commit'ten sonraki en çok **9 dosya** için şu
durum oluşur:

1. `archive.store` çalıştı → orijinal arşivde **var** (`runner.py:248`).
2. `_write_original` çalıştı → dosya diskte **optimize** (`runner.py:249`).
3. `_update_metadata` commit **edilmedi** → `th_optimized_at` **NULL**, `file_size`
   **eski (büyük) değer**, `th_media_state` hâlâ `Active` (`runner.py:268-290`).

Yeniden koşulduğunda: Kapı 5 (`already_optimized`) tetiklenmez (damga yok), ama dosya
artık ≤2000 px olduğu için **Kapı 4 `already_small`** der → dosya sonsuza kadar
"optimize edilmemiş" görünür. Sonuçlar:

- `inventory.summary()["total_bytes"]` (`inventory.py:380-388`) **fazla** raporlar.
- `archive.purge_expired` 30 gün sonra o orijinali siler; kayıt "optimize değil"
  derken orijinal **kalıcı olarak** gitmiş olur (§2.5'in sessiz varyantı).

**Bu yüzden batch boyutu timeout'a yaklaşmayacak şekilde seçilmelidir; bu bir
performans tercihi değil, veri tutarlılığı gereğidir.** Ölçüm komutu §10-D1.

### 4.3 Saatlik kapasite — ÖLÇÜLMEDİ

**Hiçbir throughput sayısı uydurulmadı.** Kapasite formülü:

```
saatlik_dosya = 3600 / t_dosya × paralel_worker
t_dosya = t_oku + t_probe + t_encode + t_arşiv_yaz + t_disk_yaz + t_db
```

Bilinen tek gerçek zaman ölçümü kodda (`usage.py:295-296`), ve o **optimizasyon
değil kullanım taraması**:

```
CANLI + SİPARİŞ  →   116 ms / 50 dosya  =  2,32 ms/dosya   (10 alan)
GEÇMİŞ           → 3.546 ms / 50 dosya  = 70,9  ms/dosya   (Version 934, Deleted 2.018, Error Log 552)
```

Bu sayılardan **çıkarım (ölçüm değil, doğrusal ekstrapolasyon)**: 2.858 dosyalık bir
kümede slot ataması için canlı tarama ≈ **6,6 s**, derin (geçmiş dahil) tarama ≈
**203 s ≈ 3,4 dk**. Ekstrapolasyon zayıf, çünkü `_match_rows` 400'lük chunk'larla
çalışıyor (`usage.py:64`, `:119`) ve maliyet hem URL sayısına hem tablo boyutuna bağlı.

**Paralel worker:** bugün `long` kuyruğunu dinleyen **tek** worker var
(`docker-compose.yml:170-175`). Yani `paralel_worker = 1`. Bu bir kapasite tavanıdır
ve §5'te ele alınıyor.

`t_encode`'un ölçüm yolu **dry-run** (`runner.py:61-63`: kapılar + dönüşüm çalışır,
diske yazılmaz) → `t_disk_yaz` ve `t_arşiv_yaz` hariç bir alt sınır verir. Komut §10-D1.

### 4.4 Toplam süre tahmini

```
toplam_saat = A_sınıfı_dosya_sayısı / saatlik_dosya
batch_sayısı = ceil(A_sınıfı_dosya_sayısı / N)
```

İki bilinmeyen de bugün ölçülemez:

- `A_sınıfı_dosya_sayısı` → `plan_backfill.py` üretir. **Bilinen tek yakınsama:**
  `gates.py:8-9` ölçümü 4.007 dosyanın **~300'ünün** Kapı 4'ü geçtiğini söylüyor
  (%7,5 — bu oran `02-medya-istatistigi.md` §2.6'da hesaplanmış). O ölçüm
  **2026-08-06 tarihli** (`02-medya-istatistigi.md` §1, K6) ve o günden beri yeni
  yüklemeler geldi.
- `saatlik_dosya` → §4.3, ölçülmedi.

> **Mertebe hissi (karar için kullanılmaz):** ~300 dosya × N=200 → 2 batch. Yani
> A sınıfı gerçekten bu mertebedeyse backfill **saatler değil dakikalar** işidir ve
> bu planın ağırlığı kapasitede değil, **§2.5 sıralamasında ve §8 rename'inde**.

### 4.5 Disk büyümesi

**İki ayrı büyüme var ve karıştırılmamalı.**

#### 4.5.1 Arşiv büyümesi (bu migration'a ait)

```
arşiv_bayt = Σ orijinal_bayt(A sınıfı dosyalar)          [30 gün boyunca]
net_kazanç = Σ (orijinal_bayt − yeni_bayt)               [purge'dan SONRA]
```

Mekanizma: `archive.store` her optimize edilen dosyanın orijinalini kopyalıyor
(`runner.py:248`, sıra kritik — arşiv başarısızsa dosyaya dokunulmuyor).
`archive.py:11` bunu açıkça söylüyor: *"Purge sonrası nihai kazanç gelir; o güne
kadar disk geçici olarak şişer."*

Geçici şişme penceresi = `ARCHIVE_RETENTION_DAYS = 30` gün (`presets.py:38`).

**Kritik nokta:** arşiv **bir kez** yazar, ikinci koşuda üzerine yazmaz
(`archive.py:73-74`). Yani backfill'i iki kez çalıştırmak arşivi iki katına
çıkarmaz — ama `purge_expired` `mtime` bazlı çalıştığı için (`archive.py:131`)
retention penceresi **ilk yazma anından** sayılır.

**Diskte yer var mı — BİLİNMİYOR.** `backup.py:11` **382 GB** boş alan diyor, ölçüm
**2026-08-13** tarihli (`02-medya-istatistigi.md` §1, K7) ve
`06-depolama-maliyet.md` §8.5 bu sayının tazelenmesi gerektiğini zaten yazıyor.
Ölçüm komutu §10-D4.

#### 4.5.2 Türev büyümesi (bu migration'a AİT DEĞİL)

`06-depolama-maliyet.md` §1.5: bugünkü ~3.050 dosya → **121.000–169.000** dosya,
çarpan **~40×–55×**. Bu, henüz **var olmayan** türev üretiminin (S3 §7-B3:
`srcset` grep sonucu 0; `presets.py:13-17` tek çıktı üretiyor) maliyetidir.

**Bu plan türev üretmez.** Ama §2.5 gereği türev **kararı** bu migration'ın ön
koşuludur — çünkü karar 2400 px içeriyorsa optimizasyon tavanı önce değişmeli.

### 4.6 Geri alma yolu

#### 4.6.1 M-A için: mevcut yol yeterli, YENİDEN TASARLANMAYACAK

Görev tanımı "yeni türevler ayrı dizinde, atomik geçiş" istiyor. **Bu desen mevcut
M-A için bilinçli olarak reddedilmiş ve gerekçesi kodda yazılı:**

> `archive.py:3-6`: *"Karar (2026-08-05'te güncellendi): dosyanın üstüne yazıyoruz ama
> orijinali süreli saklıyoruz. `file_url` değişmediği için 22 alandaki referanslar
> (JSON blob'lar dahil) kırılmaz."*

Yani ayrı dizin + atomik geçiş **`file_url`'i değiştirmek** demektir ve o anda M-A,
M-B'ye (retro-rename) dönüşür — ~2.400 referans + 301 haritası riskini M-A'ya taşır.
**Bu, planın kabul etmediği bir birleştirmedir.**

Mevcut geri alma yolu:

```
runner.restore_batch(file_names, job_key)        runner.py:293-329
  └─ restore_original(name)                      runner.py:332-365
       ├─ _assert_in_scope(doc)                  aynı kapsam kuralı geri almada da
       ├─ archive.read(file_url)                  arşivde yoksa throw
       ├─ ÖNCE DB (set_value + states.transition) runner.py:350-356
       ├─ SONRA disk (_write_original)            runner.py:357
       ├─ hata → frappe.db.rollback()             runner.py:358-361
       └─ archive.drop(file_url)                  runner.py:364
```

`runner.py:343-348` sıranın (DB→disk) gerekçesini ölçümle yazıyor: tersi denendiğinde
dosya orijinale dönmüş ama kayıt "optimize" görünüyordu.

**Geri alma penceresi 30 gündür ve bu backfill'in sert takvim kısıtıdır:**
backfill bittikten sonra doğrulama 30 gün içinde tamamlanmalı, yoksa
`archive.purge_expired` geri dönüşü kapatır.

#### 4.6.2 "Ayrı dizin + atomik geçiş" nerede DOĞRU desen

Yeni **türev** dosyaları için (`<hash>_768.webp` gibi) doğru desen tam olarak budur,
çünkü türev **yeni bir yol**dur, mevcut referansı kırmaz. S1 §5 türevlerin yerini
zaten tanımlamış: orijinalin yanında, aynı shard'da, `<hash>_<genişlik>.<ext>` suffix'i.
Atomik geçiş orada `srcset`'in yayına alınmasıyla olur (tüm türevler hazır olmadan
`srcset` basılmaz), dosya taşımayla değil.

#### 4.6.3 M-A için geri alma runbook'u

```python
# 1. Bir batch'i geri al (job_key ile değil, dosya listesiyle)
#    api/media_admin.py:230-267 → start_restore(scope="selected", file_names=[...])
# 2. Tüm optimize dosyaları geri al (filtreye uyan)
#    start_restore(scope="optimized")     ← inventory.optimized_file_names()
# 3. Tek dosya, senkron
#    restore_image(file_name)              api/media_admin.py:221-228
```

**Geri almanın kapsam sınırı:** `restore_original` `th_optimized_at` boşsa throw eder
(`runner.py:336-337`). §4.2'deki timeout senaryosunda damga yazılmadığı için o
dosyalar **geri alınamaz** — arşivde orijinal olsa bile. Bu dosyalar elle
kurtarılır; sorgu §10-D2.

---

## 5. Kuyruk önceliği

### 5.1 Bugünkü durum: backfill ile canlı yükleme AYNI kuyrukta

Kanıt:

| İş | Kuyruk | Timeout | Konum |
|---|---|---:|---|
| **Backfill** (`run_batch`) | `long` | 3600 s | `api/media_admin.py:208-217` |
| **Geri alma** (`restore_batch`) | `long` | 3600 s | `api/media_admin.py:258-266` |
| **CANLI video transcode** | `long` | 1800 s | `media/transcode.py:156-162` |
| Yedek dışa aktarımı | (kontrol edilmeli) | — | `media/backup_export.py:187` |

`transcode.py:6` gerekçeyi yazıyor: video transcode uzun sürdüğü için `queue="long"`.
Yani **satıcının o an yüklediği video, 3600 s'lik bir backfill işinin arkasında
bekler.**

Worker tanımları (`docker/docker-compose.yml:163-175`):

```yaml
queue-short:
  command: ["bench", "worker", "--queue", "short,default"]
queue-long:
  command: ["bench", "worker", "--queue", "long,default,short"]
```

- `long` kuyruğunu dinleyen **tek bir worker** var.
- `queue-long` aynı zamanda `default` ve `short`'u da dinliyor → `long`'da uzun bir iş
  varken bu worker `short`'a da bakamaz (ama `queue-short` ayrıca var, o kurtarır).
- **`long` kuyruğunda hiçbir öncelik ayrımı yok.** RQ, worker'a verilen sıradaki
  kuyrukları öncelik sırasıyla yoklar; **aynı kuyruk içinde** FIFO'dur.

### 5.2 Karar: backfill ayrı ve DÜŞÜK öncelikli kuyruğa alınır

```
Yeni kuyruk adı:  media_backfill
Yeni worker:      bench worker --queue media_backfill
Mevcut worker'lar DEĞİŞMEZ (canlı yollar aynı kalır)
```

Uygulama, tek satır: `api/media_admin.py:210` içindeki `queue="long"` backfill
çağrısında `queue="media_backfill"` olur. **Ama bu bir kod değişikliğidir ve bu
görevin kapsamı dışındadır** (kural 1). Bu plan onu **gerekli değişiklik** olarak
kaydeder, uygulamaz.

Compose'a eklenecek servis (öneri, yazılmadı):

```yaml
  queue-media-backfill:
    <<: *backend-defaults
    depends_on:
      create-site:
        condition: service_completed_successfully
    command: ["bench", "worker", "--queue", "media_backfill"]
```

Neden `long`'a `--burst` ya da ayrı worker eklemek yetmez: aynı kuyruğa ikinci bir
worker eklemek canlı transcode'un **arkasında bekleme** sorununu çözer ama backfill'i
**düşük öncelikli** yapmaz — iki iş eşit yarışır ve backfill CPU'nun yarısını alır.

### 5.3 Kod değişikliği yapılmadan uygulanabilir tek disiplin

`queue="long"` bugün değiştirilemiyorsa, backfill **operasyonel olarak** ayrıştırılır:

| Kural | Nasıl |
|---|---|
| Yalnız düşük trafik penceresinde çalıştır | Batch'ler elle/cron ile enqueue edilir |
| Tek seferde tek batch kuyrukta | Bir sonraki batch, öncekinin `read_progress(...)["state"]` değeri `completed`/`partial` olmadan enqueue **edilmez** |
| Batch küçük tutulur | N=200 → iş ~dakikalar, canlı transcode'un bekleme süresi sınırlı |
| Canlı kuyruk derinliği izlenir | Enqueue öncesi `long` kuyruğundaki iş sayısı okunur; 0 değilse beklenir |

Bu disiplinin **tamamı `plan_backfill.py`'nin ürettiği plan dosyasında** batch listesi
+ ön kontrol komutu olarak yazılıdır.

---

## 6. Satıcı bildirimi

### 6.1 Kim etkilenir — ve bu soru bugün kısmen cevapsız

Sahiplik zinciri **var ve çalışıyor**: `ownership.store_of` / `ownership.users_of`
(`media/ownership.py`), ölçüm: **2.839 / 2.839 (%100)** dosyanın yükleyeni bir
mağazaya çözülebiliyor (`ownership.py:6`). Yani "bu dosya kimin" sorusu cevaplanabilir.

Cevaplanamayan: **"bu dosya hangi ürünün hangi slotunda"** — `attached_to` **1.914
dosyada boş** (`ownership.py:7`, S2 §2.5). Bu dosyalar için slot yalnız §2.2'deki
ters referansla bulunur ve o da 7 alanı atlıyor (§2.3).

**Etkilenen küme = B sınıfı dosyaların sahibi mağazalar.** A sınıfı için satıcıya
**hiçbir şey söylenmez** — dosya sunucuda düzelir, `file_url` değişmez, görsel
kırılmaz. Bildirim yalnız B sınıfı içindir (satıcı eylemi gerekiyor).

### 6.2 Mesaj

Slot ve gerekçe **dosya bazında** yazılır, genel bir uyarı yeterli değil (satıcı
hangi görseli değiştireceğini bilemez).

**Panelde, medya kütüphanesinde ve ürün formunda gösterilecek rozet metni:**

```
⚠  Bu görsel yeni görüntü standardını karşılamıyor.

    Ürün:      {listing_title}
    Alan:      {slot_etiketi}        ← usage.py'deki label ("Ana görsel", "Galeri"…)
    Sorun:     {sebep}
    Gereken:   en az {gerekli_genişlik} px genişlik, {hedef_oran} oran
    Mevcut:    {w} × {h} px
    Son tarih: {tarih}

    Bu tarihe kadar değiştirilmezse görsel yayında kalır ancak
    yüksek çözünürlüklü ekranlarda bulanık görünmeye devam eder.
```

Sebep metinleri (§3.2 alt sınıflarıyla birebir):

| Alt sınıf | Satıcıya gösterilen |
|---|---|
| B1 | "Çözünürlük yetersiz — büyütme görüntüyü bozar" |
| B2 | "Görsel daha önce küçültüldü, orijinali artık yok" |
| B3 | "Kare olmayan görsel kenarlardan kırpılıyor" |
| B4 | "Bu alan için iki ayrı görsel gerekiyor (geniş + dar)" |
| B5 | "Dosya açılamıyor / bozuk" |
| B6 | "Dosya boş (0 bayt)" |

### 6.3 Panelde nasıl gösterilir — mevcut yüzeyler kullanılır

Yeni ekran **yazılmaz**. Kodda hazır üç yüzey var:

| Yüzey | Konum | Nasıl kullanılır |
|---|---|---|
| Medya kütüphanesi listesi | `admin-panel/.../MediaLibraryView.vue` + `useSellerMedia.js` | `inventory.list_files()` (`inventory.py:184-280`) satır başına `_decorate` ile rozet basıyor (`:298-312`) — aynı desene `compliance` alanı eklenir |
| Filtre | `inventory._apply_filters` (`inventory.py:121-145`) | `only_optimizable` gibi bir `only_noncompliant` süzgeci |
| Ürün formu galerisi | `admin-panel/.../ListingFormView.vue:1095-1168` | Kart üstünde rozet |

**Kalıcılık:** uyumluluk sonucu bir yere yazılmalı. `File`'da `th_media_*` alan deseni
zaten var (`metadata.py:37-45`). Öneri: sonucu `File`'a yazmak yerine
`verdict_map_all` gibi **Redis'te önbelleklemek** (`usage.py:397`, TTL 600 s —
`usage.py:VERDICT_TTL`). Gerekçe: uyumluluk hedef profil değişince değişir,
kalıcı damga eskir.

### 6.4 Son tarih

Kod tabanında satıcıya medya için son tarih veren bir mekanizma **yok**. Öneri:

| Aşama | Süre | Gerekçe |
|---|---|---|
| Bildirim yayına girer | T+0 | — |
| Yalnız rozet (bloklama yok) | T+0 … T+30 gün | Arşiv retention'ıyla aynı pencere (`presets.py:38`) — geri alma penceresi kapanmadan satıcı tepki verebilir |
| Yeni ürün yayınında zorunlu | T+30 gün | Yeni yüklemelerde L3 slot kuralı devreye girer (S3 §7-B1'in çözülmesine bağlı) |
| Eski görseller | **hiçbir zaman bloklanmaz** | Görseli yayından kaldırmak satıcının ürününü satılamaz hâle getirir; bu bir görüntü kalitesi işi, uyum işi değil |

---

## 7. Risk ve DURDURMA kriteri

### 7.1 DURDURMA: hata oranı > %2

**Tanım (kesin):**

```
hata_oranı = state["errors"] / state["processed"]
```

`state` = `runner.read_progress(job_key)` (`runner.py:28-29`).
`errors` yalnız **istisna fırlatan** dosyaları sayıyor (`runner.py:80-88`).
**`skipped` hata DEĞİLDİR** (`runner.py:76-79`) — Kapı 4'e takılmak normal davranıştır
ve backfill'in beklenen çoğunluğudur.

### 7.2 ⚠️ Bu kriterin kodda karşılığı YOK

`run_batch` hata oranını **izliyor ama durmuyor.** Döngü (`runner.py:68-93`) listeyi
sonuna kadar işler; `errors` sayacı yalnız sonda `state="partial"` üretir
(`runner.py:98`). **Batch ortasında abort eden bir kontrol yok.**

Sonuç: durdurma kriteri **batch granülaritesinde** uygulanabilir, dosya
granülaritesinde uygulanamaz. Yani:

```
en_kötü_durum_zarar = N dosya          (N = batch boyutu)
N = 200 → eşik aşılsa bile 200 dosya işlenmiş olur
```

Bu, §4.2'deki N=200 önerisinin **ikinci gerekçesidir**: N aynı zamanda
durdurma kriterinin çözünürlüğüdür.

### 7.3 Orkestratör runbook'u (batch arası kontrol)

```python
# HER BATCH'TEN SONRA, SONRAKİ BATCH ENQUEUE EDİLMEDEN ÖNCE:
from tradehub_core.media import runner
st = runner.read_progress(job_key)

# 1. İş bitti mi
assert st["state"] in ("completed", "partial"), f"hâlâ çalışıyor: {st['state']}"

# 2. DURDURMA KRİTERİ
oran = st["errors"] / max(st["processed"], 1)
if oran > 0.02:
    raise SystemExit(f"DUR: hata oranı %{oran*100:.1f} > %2 — kalan batch'ler enqueue EDİLMEZ")

# 3. İKİNCİL DURDURMA — skip sebebi anomalisi
sr = st["skip_reasons"]
if sr.get("file_missing", 0) > st["processed"] * 0.01:
    raise SystemExit("DUR: file_missing > %1 — disk/DB ayrışması var, önce Sorgu 7 (media_stats)")
if sr.get("decode_failed", 0) > st["processed"] * 0.01:
    raise SystemExit("DUR: decode_failed > %1 — Pillow/dosya bozulması")

# 4. İlerleme kaydı TTL'i 3600 s (presets.py:28) — bu okuma iş bitiminden
#    1 saat içinde yapılmalı, yoksa key kaybolur ve st["state"]="not_found" döner
```

> **`state="not_found"` bir "geçti" sonucu DEĞİLDİR** (`runner.py:29`). TTL dolmuşsa
> hata oranı **bilinmiyor** demektir ve durdurma kriteri sağlanamaz → o durumda da durulur.

### 7.4 Risk kaydı

| # | Risk | Şiddet | Kanıt | Azaltma |
|---|---|---|---|---|
| R1 | **2400 px hedefi, 2000 px tavanı ve 30 günlük arşiv** → kalıcı piksel kaybı | **KRİTİK / geri dönülemez** | §2.5 | Türev kararı backfill'den ÖNCE; `presets.py` tavanı gerekirse yükseltilir |
| R2 | Timeout kesilmesi → disk optimize / DB "optimize değil" ayrışması, sonra arşiv purge | **KRİTİK** | §4.2 | N=200; her batch sonrası `read_progress` kontrolü |
| R3 | Backfill canlı video transcode'u bloklar (aynı `long` kuyruğu) | YÜKSEK | §5.1 | Ayrı kuyruk (kod değişikliği) ya da §5.3 disiplini |
| R4 | Slot ataması 7 alanı atlıyor → dosyalar yanlışlıkla C sınıfına düşer | YÜKSEK | §2.3, S3 §7-B6 | `LIVE_SOURCES` genişletilmeden B sınıfı bildirimi yapılmaz |
| R5 | `EXCLUDED_MEDIA_FIELDS` KYB'nin 4 alanını saymıyor → hassas belge backfill'e girebilir | **KRİTİK (KVKK)** | S3 §7-B5, `presets.py:70-76` | Ön koşul Ö1; `runner._assert_in_scope` ikinci savunma ama o da aynı listeyi okuyor |
| R6 | 144 `Seller Application.identity_document` public tarafta olabilir | **KRİTİK (KVKK)** | S2 T-7, `presets.py:56-64` | `media_stats.py` Sorgu 6 **backfill'den önce** çalıştırılır |
| R7 | Kapasite ve toplam süre bilinmiyor | ORTA | §4.3-4.4 | dry-run ölçümü (§10-D1) |
| R8 | 382 GB boş alan sayısı 4 gün eski ve tazelenmedi | ORTA | `backup.py:11`, `06 §8.5` | §10-D4 |
| R9 | `to_webp()` 1920 px sabit tavanı `presets`'ten okumuyor → iki farklı tavan | ORTA | `engine.py:177` | Tespit edildi; düzeltme ayrı görev |
| R10 | Batch ortasında abort yok → eşik aşılsa bile N dosya işlenir | ORTA | §7.2, `runner.py:68-93` | N küçük tutulur |

---

## 8. M-B · Retro-rename ve ertelemenin GERÇEK durumu

### 8.1 ⚠️ Erteleme gerekçesi geçersiz: TUR-141 sertleştirmesi üretime ULAŞMADI

`MEDYA-DEPOLAMA-STANDARDI.md:159-160` retro-rename'i erteliyor ve şunu yazıyor:

> *"Bu arada nginx sertleştirmesi (TUR-141: `/files/`'a `X-Robots-Tag: noindex` +
> `limit_req`) eski isimlerin toplu çekilmesini pratikte zorlaştırır."*

**Bu ifade bugün doğru değil.** Doğrulama (dosya okuma, 2026-08-17):

| Dosya | Rol | `limit_req` | `/files/` bloğunda `X-Robots-Tag` |
|---|---|---:|---|
| `tradehubfront/nginx.conf.template` | **Üretimi besleyen KAYNAK şablon** (imaj bundan build ediliyor) | **0 eşleşme** | `proxy_hide_header X-Robots-Tag;` → header **KALDIRILIYOR** (`:365-366`) |
| `docker/nginx/storefront.local.template` | Local dev için **üretilmiş kopya** | 4 eşleşme (`:209` `limit_req_zone … files_zone … 10r/s`) | `add_header X-Robots-Tag "noindex" always;` + `limit_req zone=files_zone burst=20 nodelay;` (`:363-365`) |

Komutlar:

```bash
grep -c 'limit_req' /Users/ahmet/Desktop/istoc/tradehubfront/nginx.conf.template
# → 0
grep -c 'limit_req' /Users/ahmet/Desktop/istoc/docker/nginx/storefront.local.template
# → 4
```

**Ve local kopya kaynaktan bu içerikle ÜRETİLEMEZ.** `docker/gen-local-nginx.sh:20-25`
yalnız dört `sed` dönüşümü yapıyor: `https://→http://`, `wss://→ws://`, CSP'ye
`worker-src 'self'` ekleme, `proxy_ssl_server_name` ve `Strict-Transport-Security`
satırlarını silme. **`limit_req_zone` ekleyen ya da `proxy_hide_header`'ı `add_header`'a
çeviren bir dönüşüm yok.** Yani local dosya ya elle düzenlenmiş ya da sonradan
geri alınmış bir kaynaktan üretilmiş.

**Daha da güçlü kanıt — CI kaynağın `/files/`'ta noindex OLMAMASINI zorunlu kılıyor:**

`tradehubfront/scripts/check-nginx-noindex.sh:44-45` şu assert'i çalıştırıyor:

```bash
n=$(grep -c 'proxy_hide_header X-Robots-Tag;' "$T")   # T=nginx.conf.template
assert 'proxy_hide_header X-Robots-Tag sayısı' 12 "$n"
```

12 sayısı `/files/` bloğunu **içeriyor**. Yani biri kaynağa `add_header X-Robots-Tag
"noindex"` eklemeye çalışsa ve `proxy_hide_header`'ı kaldırsa **CI kırmızı olur.**
Sertleştirme kaynakta yok; kaynağın sözleşmesi onun **olmamasını** talep ediyor.

### 8.2 Riskin gerçek durumu

| Katman | Ne var | Ne yok |
|---|---|---|
| **Yeni yüklemeler** | ✅ İçerik-hash'li ad (32 hex = 128 bit) + shard, `media/naming.py:49-56`, `:59-66` | — |
| **Eski 2.166 dosya** | Verbatim ad (`0505.jpg`) — S1 `:150` | — |
| **Enumeration hız sınırı (üretim)** | — | ❌ **YOK** — `limit_req` kaynak şablonda 0 |
| **noindex (üretim, `/files/`)** | — | ❌ **YOK** — header aktif olarak **kaldırılıyor**; CI 12 sayısını zorunlu kılıyor |
| **Enumeration kanıtı** | 12 kör denemede **4 isabet** (`…design.md:22`, 2026-08-13) | — |

**Sonuç:** *"Aciliyeti düşük, çünkü nginx sertleştirmesi var"* gerekçesi
**dayanaksızdır.** Retro-rename'in gerçek durumu: **2.166 tahmin-edilebilir adres,
üretimde hiçbir hız sınırı ya da indeksleme koruması olmadan servis ediliyor.**

Bu, retro-rename'i M-A'nın önüne almayı **gerektirmez** (M-B'nin kendi ön koşulları
karşılanmadı, §8.3) — ama iki ucuz azaltma hemen yapılabilir ve retro-rename'den
bağımsızdır:

1. `limit_req` + `noindex`'i **kaynak şablona** taşımak (+ CI assert'ini 11'e
   güncellemek). Maliyet: bir nginx bloğu. Etki: enumeration'ın pratik hızı düşer.
2. `robots.txt`'e `/files/` disallow. Not: `docker/nginx/storefront.local.template:196-200`
   `$robots_tag`/`$robots_file` map'leri **fail-closed** kurulmuş
   (default `noindex, nofollow`, yalnız `istoc.com` boş) — yani mekanizma var,
   `/files/` ondan **muaf tutulmuş**.

### 8.3 M-B'nin ön koşulları — bugün karşılanmıyor

#### 8.3.1 Referans yükü

| Metrik | Değer | Kaynak |
|---|---:|---|
| `tabListing.primary_image` | 1.241 | S1 `:152` |
| `tabListing Image.image` | 1.137 | S1 `:153` |
| Toplam (benim toplamım) | **2.378** | `1.241 + 1.137` |
| Belgede yazan | ~2.400 | S1 `:152` |
| "Uzun kuyruk" için kalan pay | **22** | `2.400 − 2.378` |
| `usage.py`'de kayıtlı `(tablo,kolon)` çifti | 16 | `usage.py:31-60` |
| Görsel URL'i geçen alan (information_schema) | 23 | `usage.py:8` |

S2 T-6 bu payı **şüpheli** buluyor ve haklı: `tabVersion` ve `tabDeleted Document`
tipik olarak binlerce satır taşır (`usage.py:296` ölçümü: Version **934**,
Deleted Document **2.018**, Error Log **552** satır — 50 dosyalık bir tarama için).
Yani ya "~2.400" yalnız canlı kaynakları sayıyor **ya da tahmin düşük**.

#### 8.3.2 `refs.retarget` var — ama 7/23 alanı kapsıyor

Rename'in ihtiyacı olan primitif **kodda mevcut**: `refs.retarget(old_url, new_url)`
(`media/refs.py:197-236`). Ama kapsamı:

```
_WRITABLE = {(tablo, kolon) for tablo, kolon, _, _ in LIVE_SOURCES}     refs.py:53-55
          = 8 çift
eksi tabStorefront Layout.sections  → JSON, LOCATE ile bulunur ama exact=False
                                    → retarget "gömülü metin" diye ATLAR (refs.py:219-221)
          = 7 çift gerçekten yazılabilir
```

| Kapsanmayan | Ne olur |
|---|---|
| `tabStorefront Layout.sections` (JSON) | Rename sonrası vitrin düzeni **eski URL'i** gösterir → kırık görsel. `refs.py:203-206` gerekçesi haklı ("URL'i içeride kesip yapıştırmak JSON'u bozabilir") ama rename için **yetersiz** |
| `ORDER_SOURCES` (2 çift) | **Bilerek** dokunulmuyor (`refs.READONLY_TABLES`, `refs.py:42`) — geçmiş siparişin görüntüsü değişmemeli. Rename sonrası bu görseller 301'e bağımlı kalır |
| `HISTORY_SOURCES` (6 çift) | Hiç taranmıyor |
| 7 kayıtsız alan (§2.3) | Hiç bulunmuyor → **sessizce kırılır** |
| `Listing.video_url`, `variant_video_url` (`Data` tipi) | S3 Tablo A: alan tipi `Data`/`Long Text` — Attach taramasıyla bulunmaz |

**Ayrıca `retarget` commit ETMİYOR** — `refs.py`'de tek `frappe.db.commit()`
çağrısı `:186`'da, yani `clear()` içinde; `retarget`'ın gövdesi (`:228-236`)
doğrudan `return` ediyor. Çağıranın commit etmesi gerekiyor;
2.166 dosyalık bir döngüde bu, işlem sınırlarının elle yönetilmesi demektir.

#### 8.3.3 301 haritası

| Konu | Durum |
|---|---|
| Girdi sayısı | **2.166** (S1 `:150`) |
| Mekanizma | nginx `map` + `return 301` — kod tabanında böyle bir map **yok** |
| nginx `map_hash_max_size` varsayılanı | **2048** (nginx dokümanı; sürümde teyit edilmeli) → **2.166 > 2048**, ayar yükseltilmezse nginx uyarı verir / başlamaz |
| Nereye konur | Kaynak şablon `tradehubfront/nginx.conf.template` — `/files/` bloğunun **önüne** |
| Ne kadar yaşar | Süresiz. Eski URL'ler `tabVersion`/`tabDeleted Document`/`tabComment`'te kalıcı |
| Alternatif | Rename yerine **eski adı simlink/kopya olarak bırakmak** — enumeration açığını KAPATMAZ, dolayısıyla amaca hizmet etmez |

#### 8.3.4 M-B ön koşul listesi

Aşağıdakiler tamamlanmadan retro-rename **başlatılmaz**:

1. `LIVE_SOURCES` 23 alanı kapsayacak şekilde genişletilir (S3 §7-B6).
2. `refs.retarget` gömülü JSON alanlarını (`sections`, `variant_gallery`) güvenli
   şekilde yazabilir hâle getirilir (JSON parse → alan değiştir → yeniden serialize;
   metin kesip yapıştırma **değil**).
3. `retarget` commit sınırları netleştirilir (dosya başına mı, batch başına mı).
4. 301 map üretimi + `map_hash_max_size` ayarı + nginx CI assert'i.
5. Geri alma yolu yazılır: `retarget(new, old)` + dosyayı eski ada geri taşıma
   (M-A'nın `archive`/`restore` yolu **rename'i kapsamıyor** — `archive.relative_path_for`
   `file_url`'den yol türetiyor, `refs.py`/`archive.py` rename'i bilmiyor).
6. §8.2'deki iki ucuz azaltma (limit_req + noindex) **önce** yapılır — rename'in
   riskini almadan açığın hızını düşürür.

---

## 9. Uygulama sırası ve ön koşullar

### 9.1 Ön koşullar (hepsi backfill'den ÖNCE)

| # | Ön koşul | Neden | Kanıt |
|---|---|---|---|
| **Ö1** | `media_stats.py` **Sorgu 6 (PII maruziyeti)** çalıştırılır | 144+2 hassas belge public'te olabilir; backfill onlara dokunmamalı | S2 T-7, `presets.py:56-64` |
| **Ö2** | `EXCLUDED_MEDIA_FIELDS` KYB'nin 4 eksik alanıyla tamamlanır | R5 | S3 §7-B5 |
| **Ö3** | `media_stats.py` **Sorgu 1 (mutabakat)** çalıştırılır | Küme büyüklüğü bilinmiyor; on çelişik sayı var | S2 T-2/T-3/T-4 |
| **Ö4** | **Türev profil seti kararı** verilir; 2400 px içeriyorsa `presets.py` tavanı yükseltilir | R1 — geri dönülemez | §2.5 |
| **Ö5** | `LIVE_SOURCES` genişletilir (B sınıfı bildirimi için) | R4 | §2.3 |
| **Ö6** | Disk boş alan tazelenir | R8 | §10-D4 |

### 9.2 Sıra

```
 1. Ö1  PII maruziyeti ölçülür                      → engelleyici, KVKK
 2. Ö2  KVKK muafiyet haritası tamamlanır
 3. Ö3  Küme mutabakatı (media_stats.py)
 4.     plan_backfill.py çalıştırılır               → A/B/C sınıflandırması + batch planı
 5. Ö4  Türev profil kararı + gerekirse tavan       → R1'i kapatır
 6. Ö6  Disk kapasitesi doğrulanır
 7.     dry-run kapasite ölçümü (§10-D1)            → N ve süre netleşir
 8.     M-A backfill: batch batch, §7.3 kontrolüyle
 9.     30 gün doğrulama penceresi (arşiv purge'dan ÖNCE)
10. Ö5  LIVE_SOURCES genişletilir
11.     B sınıfı satıcı bildirimi yayına alınır
12.     §8.2 nginx azaltmaları (limit_req + noindex, kaynak şablona)
13.     M-B ön koşulları (§8.3.4) — ayrı görev, ayrı plan
```

**Adım 8 ile 9 arasında arşiv purge job'ı DURDURULUR** ya da retention geçici
olarak yükseltilir. `archive.purge_expired(retention_days=...)` parametre kabul
ediyor (`archive.py:113-114`) ama zamanlayıcı varsayılanla çağırıyor — hangi hook'un
çağırdığı doğrulanmalı (§10-D6).

---

## 10. ÜRETİMDE DOĞRULANMALI

Aşağıdakilerin hiçbiri bu oturumda çalıştırılmadı: **Docker kapalı, üretim DB'sine
ve canlı siteye erişim yok.** Her madde tam komutuyla yazılı.

### D1 — Kapasite: dosya başına gerçek süre (§4.3, §4.4, R7)

```bash
# dry_run=1 → kapılar + Pillow dönüşümü çalışır, DİSKE HİÇBİR ŞEY YAZILMAZ
#             (runner.py:61-63, :243-245)
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
import time
from tradehub_core.media import inventory, runner

# Kapı 4'ü geçmeye aday, en büyük 50 dosya
adaylar = inventory.pending_file_names(only_optimizable=1, min_bytes=200*1024)[:50]
print("aday:", len(adaylar))

t0 = time.time()
st = runner.run_batch(adaylar, preset="balanced", job_key="capacity-probe", dry_run=1)
gecen = time.time() - t0

print("gecen_saniye     :", round(gecen, 1))
print("dosya_basina_sn  :", round(gecen / max(st["processed"], 1), 3))
print("optimized        :", st["optimized"])
print("skipped          :", st["skipped"], st["skip_reasons"])
print("errors           :", st["errors"])
print("--- N onerisi: 3600 / (dosya_basina_sn * 3) ile guvenli batch boyutu ---")
EOF
```

> `pending_file_names(limit=0, *, search="", only_optimizable=0, min_bytes=0)`
> imzası `media/inventory.py:430-436`'da doğrulandı; boyuta göre **azalan**
> sıralı döner (`:448`) — kazancın çoğu ilk birkaç yüz dosyadan gelir.
> **dry-run `t_arşiv_yaz` ve `t_disk_yaz`'ı ÖLÇMEZ** → gerçek süre bundan büyüktür.
> Bu yüzden yukarıdaki formülde 3× güvenlik payı var (öneri, ölçüm değil).

### D2 — Timeout ayrışması: diskte optimize, DB'de değil (§4.2, R2)

```bash
# Arşivde kopyası VAR ama th_optimized_at BOŞ olan dosyalar = ayrışma
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
import frappe
from tradehub_core.media import archive

rows = frappe.db.sql("""
  select file_url, file_size, th_optimized_at, th_media_state
  from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and (th_optimized_at is null or th_optimized_at='')
""", as_dict=True)

ayrisan = [r for r in rows if archive.exists(r["file_url"])]
print("damgasiz dosya      :", len(rows))
print("AYRISAN (arsivde var):", len(ayrisan))
for r in ayrisan[:20]:
    print("  ", r["file_url"], r["file_size"], r["th_media_state"])
EOF
```

**Beklenen: 0.** Sıfır değilse §4.2'deki senaryo gerçekleşmiş; o dosyalar
`restore_original` ile **geri alınamaz** (`runner.py:336-337` damga arıyor) ve elle
kurtarılmalı — **arşiv purge'undan önce**.

### D3 — 2400 px kaybı: kaç dosya geri dönülemez (§2.5, R1)

```bash
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
import frappe
from tradehub_core.media import archive, inventory

ozet = inventory.summary()
print("optimize edilmis kayit:", ozet.get("optimized_count"))
print("arsiv bayt            :", archive.usage_bytes())

opt = frappe.db.sql("""
  select file_url from tabFile
  where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
    and th_optimized_at is not null and th_optimized_at<>''
  group by file_url
""", pluck=True)

arsivde   = [u for u in opt if archive.exists(u)]
kayip     = [u for u in opt if not archive.exists(u)]
print("optimize adres        :", len(opt))
print("arsivi DURAN (kurtarilabilir):", len(arsivde))
print("arsivi PURGE EDILMIS (KALICI KAYIP):", len(kayip))
EOF
```

`kayip` kümesindeki her dosya **B2 sınıfıdır** — 2400 px hedefi için satıcının
yeniden yüklemesi gerekir.

### D4 — Disk kapasitesi (§4.5.1, R8)

```bash
docker exec istocc-dev-backend-1 sh -c '
  S=/home/frappe/frappe-bench/sites/tradehub.localhost
  echo "── boş alan ──";        df -h  $S
  echo "── public/files ──";    du -sb $S/public/files
  echo "── private/files ──";   du -sb $S/private/files
  echo "── image_originals ──"; du -sb $S/private/image_originals   2>/dev/null
  echo "── media_trash ──";     du -sb $S/private/media_trash       2>/dev/null
  echo "── media-backups ──";   du -sb $S/private/media-backups     2>/dev/null
'
```

`backup.py:11`'deki **382 GB** (2026-08-13) bu çıktıyla değiştirilir.
Üç medya-özel kök ayrı sayılır (S1 §3.2) — yoksa "public medya" rakamı arşiv ve
çöple şişer.

### D5 — DPI: gerçekten bir sorun mu (§3.1)

```bash
# Kod tabanında DPI'ye dokunan satır var mı
grep -rn "dpi\|DPI\|resolution" /Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/media/
# Beklenen: eşleşme yok (bu belge yazılırken yoktu)

# Diskte gerçekten DPI etiketi taşıyan dosya var mı
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
import os, frappe
from collections import Counter
from PIL import Image

kok = frappe.get_site_path("public", "files")
c = Counter(); n = 0
for d, _dn, fn in os.walk(kok):
    for f in fn:
        if n >= 300: break
        try:
            with Image.open(os.path.join(d, f)) as im:
                c[im.info.get("dpi")] += 1
                n += 1
        except Exception:
            continue
print("ornek:", n)
for k, v in c.most_common(15): print("  dpi=", k, "->", v)
EOF
```

**Karar kuralı:** baskın değer `None` ya da `(72,72)`/`(96,96)` ise DPI **hiç ele
alınmaz** (web'de piksel boyutu bağlayıcıdır). 300 DPI kümesi anlamlıysa yalnız
baskıya giden PDF/TIFF için ayrı görev açılır.

### D6 — Arşiv purge zamanlayıcısı: backfill sırasında durdurulabilir mi (§9.2)

```bash
grep -n "purge_expired\|scheduler_events" /Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/hooks.py
# Hangi hook hangi sıklıkta çağırıyor, retention_days parametre geçiyor mu

docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
import frappe
print(frappe.get_hooks("scheduler_events"))
EOF
```

Amaç: backfill + 30 günlük doğrulama penceresi boyunca purge'un çalışmadığını
garanti etmek. Yolu yoksa `ARCHIVE_RETENTION_DAYS` geçici olarak yükseltilir
(`presets.py:38`).

### D7 — Kuyruk derinliği: backfill canlı yolu bloklar mı (§5, R3)

```bash
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
from frappe.utils.background_jobs import get_queue
for q in ("short", "default", "long"):
    kuyruk = get_queue(q)
    print(f"{q:8s} bekleyen={kuyruk.count}  basarisiz={kuyruk.failed_job_registry.count}")
EOF

# Worker'lar hangi kuyrukları dinliyor (compose'daki tanımla karşılaştır)
docker compose -f /Users/ahmet/Desktop/istoc/docker/docker-compose.yml ps queue-short queue-long
```

**Enqueue kuralı:** `long` kuyruğunda `bekleyen > 0` ise backfill batch'i
enqueue **edilmez** (§5.3).

### D8 — Slot × uyum dağılımı: planın ana çıktısı (§2.6)

```bash
docker cp scripts/plan_backfill.py istocc-dev-backend-1:/tmp/plan_backfill.py
docker exec -i istocc-dev-backend-1 bench --site tradehub.localhost console <<'EOF'
exec(open('/tmp/plan_backfill.py').read())
main()
EOF

# Kademeli — disk probe pahalıysa
#   main(probe_disk=False)              → yalnız SQL: küme, kapsam, slot dağılımı
#   main(sql=False, probe_limit=500)    → yalnız en büyük 500 dosyayı probe et
# JSON çıktısı
#   BACKFILL_PLAN_OUT=/tmp/backfill_plan.json
```

### Doğrulama sırası (bağımlılık gözeterek)

```
Ö1 (media_stats Sorgu 6)  ──► D2 ──► D3 ──► D4 ──► D8 ──► D1 ──► D7
                                                    │
                                          D5, D6 (paralel, engelleyici değil)
```

Ö1 ilk, çünkü KVKK maruziyeti varsa **hiçbir backfill başlamaz.**
D3 dördüncü, çünkü sonucu Ö4'ün (türev profil kararı) girdisidir.

---

## 11. Bu belgede geçen kaynak dosyalar

**Okunan kod (`/Users/ahmet/Desktop/istoc-medya-wt/`):**
`tradehub_core/media/presets.py`, `gates.py`, `runner.py`, `archive.py`, `engine.py`,
`refs.py`, `usage.py`, `naming.py`, `metadata.py`, `states.py`,
`tradehub_core/api/media_admin.py`, `scripts/media_stats.py`

**Okunan belgeler:** `docs/MEDYA-DEPOLAMA-STANDARDI.md`,
`docs/reports/00-upload-slot-envanteri.md`, `docs/reports/02-medya-istatistigi.md`,
`docs/reports/03-render-envanteri.md`, `docs/reports/06-depolama-maliyet.md`

**Okunan yapılandırma (SALT OKU, `/Users/ahmet/Desktop/istoc/`):**
`docker/docker-compose.yml`, `docker/gen-local-nginx.sh`,
`docker/nginx/storefront.local.template`, `tradehubfront/nginx.conf.template`,
`tradehubfront/scripts/check-nginx-noindex.sh`

**Bu görevde YAZILAN (yeni dosya):** `docs/plans/migration.md` (bu belge),
`scripts/plan_backfill.py`

**Bu görevde DEĞİŞTİRİLEN kod dosyası: YOK.**
