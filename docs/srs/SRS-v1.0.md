# SRS v1.0 — İstoç Medya Motoru Yazılım Gereksinim Spesifikasyonu

> **DURUM: HÂLÂ TASLAK (DRAFT).** Onaylanmadı. §0.3'teki programatik kontrol
> **2026-08-18'de yeniden koşuldu**; T3 ve T9 kapandı, T8 kapandı, ama **T1, T2,
> T4, T5, T6, T7 açık**. Tam eksik listesi §0.3-B ve §6.7'de.

**Görev:** T-029 (Faz 2 kapanış) · **İlk yazım:** 2026-08-17
**Revizyon 2:** 2026-08-18 — canlı ölçüm dalgası (Docker açık)
**Branch:** `medya-motoru-faz0-faz2` · **Çalışma alanı:** `/Users/ahmet/Desktop/istoc-medya-wt`
**Kaynak tasarım dokümanı:** https://karacaismail.github.io/imageoptimization/docs/ (15 faz, 102 görev)

---

## Revizyon 2 — 2026-08-18: ne değişti

İlk yazımda **Docker kapalıydı** ve belge bunu §0.2'de açıkça beyan ediyordu.
Bu revizyonda stack ayakta, veritabanına ve diske erişim var. Değişenler:

| # | Değişiklik | Dayanak |
|---|---|---|
| 1 | §0.2 ölçüm beyanı yeniden yazıldı: artık **canlı ölçülmüş sayılar var**, hangileri olduğu tek tek yazılı | `08-canli-olcum.md`, `09-slot-bazinda-istatistik.md` |
| 2 | §0.3 programatik kontrol **yeniden koşuldu**; T1–T9'un her biri yeni çıktıyla güncellendi (T3, T8, T9 kapandı) | bu oturumun komut çıktıları |
| 3 | **FR-019 değişti**: logo alfa zorunluluğu **ret → uyarı**. Gerekçe: JPEG payı ölçüldü, %50 çıktı; `logo.md` §13-K1'in kendi tetiği (%10) kararı düşürdü | `logo.md` §13-K1, `08-canli-olcum.md` §2.2 |
| 4 | **8 yeni gereksinim** (FR-143…FR-150) ölçülen anomalilerden doğdu: piksel tavanı, CMYK, alfa, iki politika seti çelişkisi, harici URL, uyum karnesi, doğrulama betiğinin kendisi | §3.M |
| 5 | **BULGU:** `max_megapixels_hard = 80` bugünkü kütüphanenin **hiçbir dosyasını** reddetmiyor (en büyük dosya 72,71 MP). Eşik güvenlik kapısı olarak **işlevsiz** | §3.M, FR-143 |
| 6 | §6.1 ve §6.7 kapı tabloları yeni ölçümlerle güncellendi | §6 |
| 7 | §7 izlenebilirlik matrisine yeni satırlar + **§7.5 slot bazlı uyum ölçümü** eklendi | §7 |
| 8 | §8.0 ve §8.2 (şema doğrulaması ve piksel dağılımı) **koşuldu ve kapandı** | §8 |

**Kriter gevşetilmedi.** Hiçbir kabul kriteri, geçiş kapısı ya da eşik "artık
geçsin diye" düşürülmedi. Kapanan maddeler gerçekten kapandı; kapanmayanlar
§0.3-B'de sayıyla listeli.

---

## 0. Bu belgenin kimliği

### 0.1 Girdi belgeleri — hepsi okundu

| Belge | Görev | Boyut (bayt, `ls -la`) |
|---|---|---|
| `docs/standards/README.md` | T-023 | 21.940 |
| `docs/standards/product-image.md` | T-020 | 46.115 |
| `docs/standards/logo.md` | T-021 | 78.188 |
| `docs/standards/company-cover-video.md` | T-022 | 53.835 |
| `docs/standards/product-video.md` | T-023 | 14.578 |
| `docs/standards/company-cover-image.md` | T-023 | 16.933 |
| `docs/standards/category-banner.md` | T-023 | 16.576 |
| `docs/standards/user-avatar.md` | T-023 | 17.686 |
| `docs/standards/document-attachment.md` | T-023 | 22.147 |
| `docs/standards/dpi-ve-cozunurluk.md` | T-024 | 32.839 |
| `docs/standards/icerik-kurallari.md` | T-025 | 37.926 |
| `docs/standards/retention.md` | T-026 | 38.717 |
| `docs/standards/kota.md` | T-027 | 47.963 |
| `docs/standards/policies/_schema.md` | T-024 | 2.003 |
| `docs/standards/policies/*.json` | T-024 | 13 dosya |
| `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` | T-020 | 1 dosya |
| `tradehub_core/media/pipeline/policy/slots/*.json` | T-020…T-023 | 9 dosya |
| `tradehub_core/media/pipeline/policy/content_rules.json` | T-025 | 32.977 |
| `tradehub_core/media/pipeline/policy/retention.schema.json` | T-026 | 31.865 |
| `tradehub_core/media/pipeline/policy/quota.schema.json` | T-027 | 48.581 |
| `docs/plans/migration.md` | T-028 | 1 dosya |
| `docs/reports/00-…, 01-…, 02-…, 03-…, 04-…, 06-…` | T-001…T-008 | 7 rapor |
| `docs/MEDYA-{DEPOLAMA-STANDARDI,ERISIM-MODELI,YUKLEME-SOZLESMESI,TARIH-STANDARDI}.md` | TUR-123/126/130 | Faz 1 |

**Revizyon 2'de eklenen girdi belgeleri (2026-08-18):**

| Belge | Görev | Ne getirdi |
|---|---|---|
| `docs/reports/08-canli-olcum.md` | T-003/T-004 kapanışı | 4.958 dosyalık envanter, format/mod/piksel dağılımı, logo K1–K2 tetikleri, video dağılımı, PII maruziyeti |
| `docs/reports/09-slot-bazinda-istatistik.md` | slot × gerçek veri | 9 slotun **ölçülmüş uyum oranı**, ihlal nedenleri, iki politika setinin sayısal çelişkisi |
| `docs/reports/03-performans-taban-cizgisi.md` | T-004 | LCP/CLS taban çizgisi **ölçüldü** (Chrome DevTools, masaüstü + Slow 4G/4×CPU). §8.8'in bir kısmını kapatır; rev2'nin **hiçbir** gereksinimi bu sayılara dayanmıyor, o yüzden §3'e girmedi |
| `docs/reports/05-fixture-korpusu.md` | T-006 | **51 fixture** (34 görsel + 7 video + 10 kötücül), `expect` ↔ `olculen` doğrulaması 51/51 GEÇTİ. **G5'i kapatmaz:** bu bir *regresyon* korpusudur, içerik kuralı kalibrasyonu için gereken *etiketli* korpus (≥300 görsel, kural başına ≥30/sınıf) değildir |
| `docs/reports/05-kutuphane-benchmark.md` | T-007 | Pillow / pyvips / ffmpeg karşılaştırması **koşuldu** (K-11'in bir parçasını kapatır); rev2 gereksinimlerine girdi vermedi |
| `docs/standards/logo.md` §13 (güncel) | T-021 | K1/K2 **ölçümle çözüldü**; karar tabloları ve tetikler silinmeden korunmuş |
| `docs/standards/company-cover-video.md` §10 (güncel) | T-022 | §10.0 ölçüm etkisi + **K8 yeni karar** (geçiş penceresi) |
| `tradehub_core/media/pipeline/policy/slots/{seller,brand}-logo.json` (güncel) | T-021 | JPEG serbest, alfa `optional`, `no_alpha_channel` → `warn` |
| `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` v1.3.0 | T-020 | Logo sınıfı + video biçimleri ifade edilebiliyor → 9/9 uyum |

### 0.2 Ölçüm beyanı

#### 0.2-a İlk yazımın beyanı (2026-08-17) — kayıt için korunuyor

**Docker kapalı. Üretim veritabanına ve canlı siteye erişim YOK.** Bu belgede
tarayıcıda ölçülmüş tek bir sayı, üretim veritabanından okunmuş tek bir sayı
yoktur. Her sayı ya (a) `dosya:satır` referansı, ya (b) bu makinede çalıştırılmış
bir komutun çıktısı, ya (c) yanında aritmetiği yazılı bir hesaptır.
Ölçüm gerektiren her şey **§8 ÜRETİMDE DOĞRULANMALI**'da, çalıştırılacak komutla
birlikte listelidir.

#### 0.2-b Revizyon 2 beyanı (2026-08-18) — YERELDE ölçüldü, ÜRETİMDE değil

**Docker açık, 12 servis ayakta, site `istoc.localhost`.** Aşağıdaki sayılar
artık tahmin değil, **yerel stack'te ölçüm**:

| Ölçülen | Değer | Nerede |
|---|---|---|
| `tabFile` kaydı (klasör hariç) | **4.958** (4.350 public / 608 private), **1.559,5 MB** | `08-canli-olcum.md` §1 |
| Görsel / video / belge | 4.812 / 23 / 57 · diskte yok 7 · açılamayan 59 | aynı |
| Format dağılımı | JPEG 3.631 · PNG 786 · WEBP 384 · TIFF 11 | aynı §1.1 |
| Renk modu | RGB 4.096 · **RGBA 597** · P 74 · **CMYK 38** · L 7 | aynı |
| Megapiksel | p50 1,56 · p90 5,01 · p99 29,21 · **MAX 72,71** | aynı §1.2 |
| Kısa kenar | p50 1.120 · p90 2.160 · p99 4.480 · min 32 | aynı |
| Bayt | p50 81 KB · p90 869 KB · p99 3,6 MB · max 22,1 MB | aynı |
| Anomali | **>20 MP = 179** · CMYK 38 · alfa 597 · >20 MB 1 · 0 bayt 0 | aynı §1.3 |
| Logo (18 gerçek dosya) | JPEG **%50** · oran bandı içi **%89** · kısa kenar<512 %33 | aynı §2.1 |
| Video (23 dosya, 5 okunabildi) | hepsi h264 · süre p50 33 s **MAX 540 s** · bitrate p50 746 kbps | aynı §7 |
| **Slot bazlı uyum oranları** | 9 slot × gerçek veri; ihlal sayıları tek tek | `09-slot-bazinda-istatistik.md` §3 |
| Megapiksel eşik duyarlılığı | 16/20/25/30/40/50/60/72/75/80 MP için üstünde kalan sayı | bu belge §3.M, FR-143 |

**Bu revizyonda ilk kez ölçülenler** (önceki sürümde §8'de "üretimde
doğrulanmalı" diye bekliyordu):

- §8.0 — şema doğrulaması yeniden koşuldu → **9/9 uyumlu, 0 şema hatası**
- §8.2 — gerçek dosyaların piksel ve oran dağılımı → `09-…md` §4.1
- §8.29 — `data:` URI logoların gerçek sayısı → 18, **hepsi demo seed**

**HÂLÂ ÖLÇÜLMEDİ — dürüstlük sınırı:**

| Konu | Neden |
|---|---|
| **Üretim ortamı** | Tüm sayılar **yerel** stack'ten. Üretim imajını Frappe Cloud kendi build ediyor; `docker/backend.Dockerfile` kullanılmıyor. Bu ölçümler üretimi **doğrulamaz** |
| LCP / CLS / Lighthouse | Tarayıcı otomasyonu koşulmadı (§8.8, §8.19) |
| 719 harici URL'nin piksel/bayt değeri | Dosyalar bizim diskimizde değil; ölçüm ortamı dış ağa çıkarılmadı (`09-…md` §0) |
| PDF/DOCX sayfa geometrisi | pdfium/poppler kurulu değil (`09-…md` §0) |
| `encoder_quality` doğruluğu | Kalibrasyon koşumu gerekir — **T4 açık** |
| İçerik kuralı eşikleri | Etiketli korpus yok — **T4 açık** |
| Türev (rung) baytları | Türev üretimi yazılmadı — `logo.md` §13-K3 açık |

**Bu revizyon da hiçbir mevcut kod dosyasını değiştirmedi.**
`tradehub_core/` altında tek satır değişmedi; yalnız bu belge yazıldı.

**Bu belge hiçbir mevcut kod dosyasını değiştirmedi.** Yalnız bu dosya yazıldı.

**Kod hacmi — bu makinede ölçüldü (`wc -l`, 2026-08-17):**

| Yüzey | Satır | Komut |
|---|---:|---|
| `tradehub_core/media/*.py` | **8.200** | `wc -l tradehub_core/media/*.py` |
| `tradehub_core/api/{seller_media,media_admin,media_access}.py` | **1.569** | `wc -l` (494 + 873 + 202) |
| `tradehub_core/api/moderation.py` | 209 | `wc -l` |
| Backend medya testleri (`test_media_*.py`, `test_engine_webp.py`, `tests/test_policy_dpi.py`) | **2.972** | `wc -l` |
| `tradehubfront/src/lib/upload-ui/*.ts` | 1.780 | `wc -l` |
| `{tradehubfront,admin-panel/frontend}/src/lib/media/*` | 639 | `wc -l` |
| `tradehubfront/src/utils/mediaUrl.ts` | 75 | `wc -l` |
| **Bu ölçümlerin toplamı** | **15.444** | — |

> Görev tanımındaki **21.430 satır** rakamı bu belgede **doğrulanmadı**. Yukarıdaki
> 15.444 satır ölçüldü; kalan fark render bileşenlerini (`ProductImageGallery.ts`,
> `StoreHeader.ts`, `section-registry.ts`, `CategoryShowcase.ts`, `MediaViewer.ts`,
> `ProfileImageDropzone.vue`, `DocTypeFormView.vue` …) kapsıyor olmalıdır. Bu
> belgenin hiçbir gereksinimi 21.430 sayısına dayanmıyor.

### 0.3 ZORUNLU KONTROL — `TBD` taraması ve TASLAK gerekçesi

Komut ve **gerçek çıktısı** (2026-08-17, bu makinede):

```bash
$ cd /Users/ahmet/Desktop/istoc-medya-wt
$ grep -rn TBD docs/standards/
docs/standards/company-cover-video.md:272:gösterir. Hiçbiri TBD değildir.

$ grep -rn TBD docs/standards/ | wc -l
       1

$ grep -rn "TBD" tradehub_core/media/pipeline/policy/ | wc -l
       0
```

**Bulgu:** `docs/standards/` altında `TBD` dizgesi **1 kez** geçiyor ve bu tek
geçiş bir **olumsuzlama** cümlesidir (`company-cover-video.md:272` — "Hiçbiri TBD
değildir."), yer tutucu değil. Yani **hiçbir standart belgesinde açıkta bırakılmış
`TBD` yer tutucusu yoktur.**

Diğer yer tutucu kalıpları da tarandı:

```bash
$ grep -rniE "\b(TODO|FIXME|XXX|TBC)\b" docs/standards/ | wc -l
       0
$ grep -rniE "placeholder|belirlenecek|karar bekliyor|açık soru" docs/standards/ | wc -l
       8
```

8 satırın hepsi **bilinçli olarak işaretlenmiş, gerekçeli** açık maddelerdir
(`icerik-kurallari.md:382,696,706` kategori adları placeholder;
`product-image.md:147` HEIC/AVIF açık sorusu; `kota.md:676` no-op stub;
`README.md:133,205,244`), gizli boşluk değil.

> **REVİZYON 2 — 2026-08-18, yeniden koşuldu.** Yukarıdaki dört tarama aynen
> tekrarlandı; **çıktılar değişmedi**:
>
> ```
> $ grep -rn TBD docs/standards/ | wc -l                       →  1
>   (tek geçiş: company-cover-video.md:280 "Hiçbiri TBD değildir." — olumsuzlama)
> $ grep -rn "TBD" tradehub_core/media/pipeline/policy/ | wc -l                →  0
> $ grep -rniE "\b(TODO|FIXME|XXX|TBC)\b" docs/standards/ | wc -l  →  0
> $ grep -rniE "placeholder|belirlenecek|karar bekliyor|açık soru" docs/standards/ | wc -l  →  8
> ```
>
> Yani **standart belgelerinde açıkta `TBD` yok** — bu bulgu 2026-08-18'de de
> geçerlidir. TASLAK'ın sebebi hâlâ aşağıdaki T-maddeleridir.

**Buna karşın SRS "TASLAK" olarak işaretlenmiştir.** Sebep `TBD` dizgesi değil,
aşağıdaki **programatik olarak sayılmış** kapanmamış maddelerdir:

| # | Eksik | Ölçüm komutu ve çıktısı |
|---|---|---|
| **T1** | **9 slot politikasının 0'ı `active`.** 8'i `status: "draft"`, 1'inde `status` alanı hiç yok (`company-cover-video.json`). | `python3` ile `status` alanı okundu: `draft ×8`, `None ×1` |
| **T2** | **51 açık soru (`open_questions`).** Dağılım: `brand-logo` 7, `seller-logo` 7, `product-image` 7, `category-banner` 6, `company-cover-image` 6, `document-attachment` 6, `product-video` 6, `user-avatar` 6, `company-cover-video` 0 (onun karşılığı `pending_admin_decisions`, 7 madde K1–K7). | `len(d["open_questions"])` toplamı = **51** |
| **T3** | **3 politika dosyası şemaya uymuyor.** Şema `additionalProperties: false` (`slot-policy.schema.json:7`). Kök anahtar karşılaştırması: `seller-logo.json` 6 fazla anahtar (`css_safe_area`, `dark_theme`, `not_render_points`, `production_verification_required`, `render_points`, `svg_policy`); `brand-logo.json` 6 fazla anahtar; `company-cover-video.json` 21 fazla + **10 zorunlu alan eksik** (`accept`, `master`, `messages`, `on_violation`, `profiles`, `require`, `roles`, `schema_version`, `slot_key`, `sources`). | Kök anahtar kümesi farkı Python ile hesaplandı; çıktı §7.3'te |
| **T4** | **`content_rules.json` tamamen kalibre edilmemiş.** `calibration_status: "UNCALIBRATED"`; 9 kuralın 9'unda `threshold_status` = "KALİBRE EDİLMEDİ — başlangıç değeri" (1 kural "KALİBRE EDİLMEZ — ürün kararı"); `not_measured.items` 6 madde. | `grep -c` ve JSON okuması |
| **T5** | **`encoder_quality` alanlarında `null` var.** Şema kuralı: `status='active'` bir politikada `null` bulunamaz (`slot-policy.schema.json:305`). Politika başına `null` sayısı: `product-image` 5, `company-cover-image` 6, `seller-logo` 5, `brand-logo` 3, `category-banner` 3, `company-cover-video` 2, `product-video` 1, `document-attachment` 0, `user-avatar` 0. | `grep -c ': *null'` |
| **T6** | **4 ayrı politika kayıt yeri var.** `tradehub_core/media/pipeline/policy/slots/` (9 dosya, 3 farklı biçim) + `docs/standards/policies/` (13 dosya, `_schema.md` biçimi). Hangisinin kanonik olacağı **karara bağlanmadı** (`docs/standards/README.md:133`). | `ls` sayımı |
| **T7** | **7 platform yöneticisi kararı onaysız.** `logo.md` §13 K1–K6 (6 karar) + `company-cover-video.md` §10 K1–K7 (7 karar). Her birinde öneri ve varsayılan yazılı, onay **yok**. | Belge okuması |
| **T8** | **Şema v1.0.0 video/belge biçimlerini ifade edemiyor.** `profiles[].formats` enum'u `avif\|webp\|jpeg\|png`; `master.format` enum'unda `webm` yok → gerçek video rendition'ı (`transcode.py:243-246`) politikada yazılamadı. | `slot-policy.schema.json:300`, `:216`; `product-video.md` §5 |
| **T9** | **Şema doğrulaması bu oturumda YENİDEN KOŞTURULAMADI.** `jsonschema` bu Python kurulumunda yok (`python3 -c "import jsonschema"` → `ModuleNotFoundError`; `pip list \| grep -i jsonschema` → boş). T3'teki bulgu kök-anahtar karşılaştırmasıyla bağımsız olarak doğrulandı; derin (alan içi) doğrulama **yapılmadı**. `docs/standards/README.md` §6 tablosundaki "6/9 uyumlu" sonucu **o oturumun** çıktısıdır, bu oturumda tekrarlanmadı. | §8.0 |

**TASLAK'tan v1.0 ONAYLI'ya geçiş kapısı** §6.7'de tanımlıdır.

---

### 0.3-B ZORUNLU KONTROL — 2026-08-18 YENİDEN KOŞUMU

> Bu bölüm T1–T9'un her birini **yeniden ölçer**. Yukarıdaki tablo 2026-08-17
> anlık görüntüsüdür ve **silinmedi**; aşağıdaki tablo o günden bugüne neyin
> değiştiğini gösterir.

**Koşulan komutlar ve gerçek çıktıları:**

```
# 1) Şema doğrulaması — artık koşulabiliyor: jsonschema 4.25.1 KURULU
$ python3 -c "import jsonschema; print(jsonschema.__version__)"
4.25.1
$ python3 <Draft202012Validator ile 9 politikanın tamamı>
brand-logo.json OK · category-banner.json OK · company-cover-image.json OK
company-cover-video.json OK · document-attachment.json OK · product-image.json OK
product-video.json OK · seller-logo.json OK · user-avatar.json OK
Şemaya uyumlu: 9/9 · uyumsuz: 0

# 2) status alanı
ACTIVE sayısı = 0 / 9        (9'unun 9'u da status: "draft")

# 3) open_questions
brand-logo 5 · category-banner 6 · company-cover-image 6 · company-cover-video 8 (+7 pending_admin_decisions)
document-attachment 6 · product-image 7 · product-video 6 · seller-logo 5 · user-avatar 6
open_questions toplamı = 55

# 4) encoder_quality null (profiles[].encoder_quality içinde, alan alan sayıldı)
category-banner 3 · company-cover-image 5 · product-image 5 · product-video 1 · diğer 5 dosya 0
TOPLAM = 14

# 5) content_rules
calibration_status = UNCALIBRATED · 9 kural · not_measured.items = 6

# 6) docs/standards/README.md §6 doğrulama betiği — AYNEN çalıştırıldı
[D3] brand.logo: content_rules 'animated' tanımsız message_key 'animated'
Traceback (most recent call last): ... KeyError: 'max_megapixels'
ÇIKIŞ KODU = 1
```

**Betiğin kendisi çöküyor.** `README.md` §6 betiği `master["max_megapixels"]`
okumaya çalışıyor; `seller-logo.json` ve `brand-logo.json`'ın `master` bloğunda
bu alan **yok** (yalnız `max_long_edge` var). Betiği `KeyError` yerine hata
sayan bir varyantla koşturunca tam liste çıktı:

```
[D3] brand.logo : content_rules 'animated' → tanımsız message_key 'animated'
                  (messages.tr'de karşılığı 'format_animated')
[D4] brand.logo : master.max_megapixels YOK
[D5] brand-logo : politika var, docs/standards/brand-logo.md YOK
[D3] seller.logo: content_rules 'animated' → tanımsız message_key 'animated'
[D4] seller.logo: master.max_megapixels YOK
[D5] seller-logo: politika var, docs/standards/seller-logo.md YOK

şemaya uyumlu politika: 9/9 | toplam hata: 6 | ÇIKIŞ KODU = 1
```

> **D5 hakkında dürüstlük notu.** İki logo slotunun standart belgesi
> `docs/standards/logo.md`'dir (tek belge, iki slot). D5 kontrolü dosya adı
> eşleşmesi arıyor, bu yüzden **yanlış pozitif** üretiyor. Ama betik **yazıldığı
> gibi** hata sayıyor ve çıkış kodu 1 dönüyor — G1 kapısı çıkış kodu 0 istiyor.
> Kural gevşetilmedi: ya betik düzeltilir (FR-148), ya belge bölünür. Ölçüm
> "6 hata" der; yorum "4'ü gerçek, 2'si betik kusuru" der. İkisi de yazılı.

**T1–T9 — 2026-08-18 durumu:**

| # | Madde | 2026-08-17 | **2026-08-18** | Durum |
|---|---|---|---|---|
| **T1** | Politikaların `active` olması | 0/9 (`draft`×8, `status` yok ×1) | **0/9** — 9'u da `draft`, `status` alanı **9'unda da var** | ❌ **AÇIK** |
| **T2** | Açık sorular | 51 | **55** (arttı: `company-cover-video` 0 → 8; logo'lar 7 → 5) | ❌ **AÇIK — geriledi** |
| **T3** | Şemaya uymayan politika | 3 dosya | **0 dosya** — şema v1.3.0 logo sınıfını da ifade ediyor | ✅ **KAPANDI** |
| **T4** | `content_rules` kalibrasyonu | `UNCALIBRATED` | **`UNCALIBRATED`** — değişmedi | ❌ **AÇIK** |
| **T5** | `encoder_quality` `null` | ham `: null` sayımı | **14** gerçek `encoder_quality` null, **4 politikada 0** | ❌ **AÇIK ama daraldı** |
| **T6** | Kanonik politika kayıt yeri | 4 yer, karar yok | **Karar yok** — ve artık **sayısal bedeli ölçüldü**: aynı alana 8 kat farklı eşik (§3.M FR-147) | ❌ **AÇIK — bedeli ölçüldü** |
| **T7** | Yönetici kararları | 13 karar onaysız | **14 karar** (logo K1–K6 + kapak videosu K1–**K8**); **2'si ölçümle çözüldü** (logo K1, K2) → **12 açık** | ❌ **AÇIK — 2/14 kapandı** |
| **T8** | Şema video/belge biçimini ifade edemiyor | `master.format` enum'unda `webm` yok | **KAPANDI** — enum artık `webp/avif/jpeg/png/webm/mp4/preserve`; `product-video.json` `master.format = "webm"`, `video.renditions[]` gerçek codec/CRF taşıyor | ✅ **KAPANDI** |
| **T9** | Şema doğrulaması koşturulamadı | `jsonschema` yok | **KOŞTURULDU** — jsonschema 4.25.1, 9/9 uyumlu, 0 hata | ✅ **KAPANDI** |

**Yeni madde — bu revizyonda doğdu:**

| # | Madde | Ölçüm |
|---|---|---|
| **T10** | **Doğrulama betiğinin kendisi bozuk.** `README.md` §6 betiği `KeyError` ile çöküyor; D3'te 2 gerçek hata (`message_key` uyuşmazlığı), D4'te 2 eksik alan, D5'te 2 yanlış pozitif üretiyor. Çıkış kodu **1**. | Yukarıdaki koşum · → **FR-148** |

**SONUÇ: SRS HÂLÂ TASLAK.** 9 maddenin 3'ü kapandı (T3, T8, T9), 6'sı açık
(T1, T2, T4, T5, T6, T7), 1 yeni madde eklendi (T10). Geçiş kapısı §6.7'de
madde madde güncellendi.

**`active` olmaya en yakın politika — ölçüldü.** G6 iki koşul istiyor:
`open_questions` boş **ve** `encoder_quality` null yok.

| politika | şema | `encoder_quality` null | `open_questions` | gerçek veride uyumsuzluk | G6'ya uzaklık |
|---|---|---:|---:|---:|---|
| `brand-logo` | ✅ | **0** | 5 | **%0,0** (n=1) | **yalnız 5 açık soru** |
| `seller-logo` | ✅ | **0** | 5 | %31,6 (n=19) | 5 açık soru |
| `document-attachment` | ✅ | **0** | 6 | %91,8 (n=61) | 6 açık soru + eşik gerçekçi değil |
| `user-avatar` | ✅ | **0** | 6 | %100 (n=6, hepsi harici URL) | 6 açık soru + ölçülecek yerel dosya yok |
| `company-cover-video` | ✅ | **0** | 8 (+7 karar) | %83,3 (n=6) | 8 açık soru + 7 yönetici kararı |
| `company-cover-image` | ✅ | 5 | 6 | **%17,6** (n=34) | 5 null + 6 soru |
| `product-image` | ✅ | 5 | 7 | %48,6 (n=3.061) | 5 null + 7 soru |
| `category-banner` | ✅ | 3 | 6 | %100 (n=32) | 3 null + 6 soru |
| `product-video` | ✅ | 1 | 6 | %80,0 (n=5) | 1 null + 6 soru |

> **`brand.logo` teknik olarak `active`'e en yakındır** (0 null, 5 soru, gerçek
> veride %0 ihlal) — **ama n=1**. Tek dosyalık bir küme üzerinden "%0 uyumsuz"
> demek istatistiksel olarak boştur; bu satır bir aday işaretidir, kanıt değil.
> `company.cover_image` ise **n=34 ile %17,6** uyumsuzluk gösteriyor — ölçülebilir
> bir kümede politikanın veriye oturduğu **tek** slot budur (`09-…md` §4.5).

### 0.4 Terimler

| Terim | Anlam |
|---|---|
| **slot** | Bir medya yükleme noktasının kanonik kimliği. Biçim `<alan>.<slot>` (ör. `product.image`). Kaynak: `docs/reports/00-upload-slot-envanteri.md` §8. **Kodda bugün karşılığı yoktur.** |
| **master** | Türevlerin üretildiği tek kaynak dosya. Kullanıcıya servis edilmez. |
| **türev / profil (derivative)** | Master'dan üretilen, belirli genişlikteki servis dosyası. **Bugün üretilmiyor** (`docs/reports/03-render-envanteri.md` §6.3). |
| **L0 / L1 / L2 / L3** | Doğrulama katmanları. L0 = global `File` kancası (her yol), L1 = uca özel sunucu doğrulaması (yalnız 3 uç), L2 = istemci ön kontrolü, L3 = slot semantiği (boyut/oran/adet/rol) — **sistemde hiç yok**. Kaynak: `docs/reports/00-upload-slot-envanteri.md` §1. |
| **ret sözleşmesi** | `Kod(kod, retryable)` çifti; istemci hata **metnine değil koda** bakar. `tradehub_core/media/upload_policy.py:104-139` (14 kod). |
| **B1…B8** | `docs/reports/00-upload-slot-envanteri.md` §7-B'deki sistem çapında eksikler. |
| **I1…I9** | `docs/standards/product-image.md` §2.2'deki, JSON Schema ile ifade edilemeyen değişmezler. |
| **D1…D5** | `docs/standards/README.md` §6 doğrulama betiğindeki değişmezler. |
| **SVG-1…SVG-10** | `docs/standards/logo.md` §6.2'deki SVG kabul ön koşulları. |
| **Ç1…Ç12** | `docs/standards/company-cover-video.md` §9'daki doğrulanmış çelişkiler. |
| **E1…E10** | `docs/standards/README.md` §4'teki ölçülen eksikler. |
| **F1…F18** | `docs/standards/logo.md` §11'deki bulgular. |
| **A1…A3** | `docs/standards/dpi-ve-cozunurluk.md` §6'daki açık maddeler. |
| **T1…T10** | Bu SRS'in TASLAK kalma gerekçeleri. T1–T9 rev1'de (§0.3), T10 rev2'de (§0.3-B) sayıldı. Her biri §6.7'deki bir kapıya (G1–G7) bağlıdır. |
| **G1…G7** | TASLAK → `v1.0 ONAYLI` geçiş kapıları (§6.7). G7 rev2'de eklendi (piksel tavanının işlevsel olması). |
| **rev2-A…rev2-I** | 2026-08-18 canlı ölçümünde bulunan, gereksinime bağlanmış anomaliler (§7.4 ters yön tablosu). |

---

## 1. Amaç ve kapsam

### 1.1 Amaç

Bu belge, İstoç B2B pazaryerinin **medya motoru** için yazılım gereksinimlerini
tanımlar. Motorun işi: bir medya dosyasının **kabul edilmesi, normalize edilmesi,
türevlerinin üretilmesi, saklanması, servis edilmesi, kotalanması ve silinmesi**.

Bu belge **yeniden tasarım değildir.** `tradehub_core/media/` altında 8.200 satır
(§0.2, ölçüldü) çalışan kod var. SRS'nin üç işi vardır:

1. **Çalışanı sözleşmeye bağlamak** — mevcut davranışı gereksinim olarak yazmak,
   böylece bir sonraki geliştirici onu "eksik" sanıp yeniden yazmasın (§3'teki
   her FR'de "Bugün" kolonu bunu söyler).
2. **Eksiği test edilebilir biçimde yazmak** — özellikle L3 (slot semantiği) hiç
   yok; 41 doctype alanının **0'ında** piksel/oran/adet kuralı var
   (`docs/reports/00-upload-slot-envanteri.md` §10).
3. **Ölçülmemişi ölçülmemiş olarak işaretlemek** — §8.

### 1.2 Kapsam İÇİ

| # | Konu | Kaynak standart |
|---|---|---|
| 1 | Slot kimliği ve slot politikası kayıt defteri (L3) | `product-image.md` §1.2, `README.md` §0 |
| 2 | Kabul kapısı: MIME, bayt, megapiksel, animasyon, magic-byte | `product-image.md` §3.1, `document-attachment.md` §1 |
| 3 | Geometri kapısı: kısa kenar, alan, en-boy oranı, adet | `product-image.md` §3.2, §4 |
| 4 | Master üretimi: tavan, DPI, renk uzayı, metadata temizliği | `dpi-ve-cozunurluk.md` §1-§5 |
| 5 | Türev merdiveni (profiles) ve `fit`/`pad` kararları | `product-image.md` §6-§7, `logo.md` §3.3, §5 |
| 6 | 9 slotun somut geometri sözleşmesi | `product-image.md`, `product-video.md`, `company-cover-image.md`, `company-cover-video.md`, `category-banner.md`, `user-avatar.md`, `document-attachment.md`, `logo.md` (seller + brand) |
| 7 | İçerik uygunluk kuralları ve moderasyon | `icerik-kurallari.md` |
| 8 | Kota (5 metrik) ve rate limiting | `kota.md` |
| 9 | Saklama, soft-delete, legal hold, yedek | `retention.md` |
| 10 | Erişim modeli, imzalı URL, PII koruması | `docs/MEDYA-ERISIM-MODELI.md`, `docs/reports/04-yetki-modeli.md` |
| 11 | Depolama yerleşimi ve isimlendirme | `docs/MEDYA-DEPOLAMA-STANDARDI.md` |
| 12 | Hata sözleşmesi ve kullanıcı mesajları (4 dil) | `docs/MEDYA-YUKLEME-SOZLESMESI.md`, `dpi-ve-cozunurluk.md` §7 |
| 13 | Video: transcode, rendition, poster, altyazı, ses | `company-cover-video.md`, `product-video.md` |
| 14 | Erişilebilirlik (altyazı, reduced-motion, klavye) | `company-cover-video.md` §8 |
| 15 | Mevcut medyanın standartlaştırılması (migration) | `docs/plans/migration.md` |

### 1.3 Kapsam DIŞI — ve neden

| Konu | Neden dışı | Kanıt |
|---|---|---|
| **Nesne deposu (S3 / MinIO)** | Kodda **yok**. `boto3`/`minio`/`s3_bucket` geçen tek satır bir yorum. `requirements.txt` 3 satır. | `retention.md` §5.3; `audit/__init__.py:23` |
| **CDN** | Kodda **yok**. `?t=Date.now()` cache-buster'ı "CDN gelirse sorun zaten çözülmüş" notuyla yazılmış — yani CDN yok. | `user-avatar.md` §7 madde 3; `alpine/settings.ts:126` |
| **HLS / DASH** | `hls`/`HLS` → her iki frontend'de **0 eşleşme**. Kapak slotu için gereksiz olduğu §6.8'de sayıyla gösterilmiş. | `company-cover-video.md` §6.8 |
| **`tr_tradehub` app'inin içi** | Ayrı app. `header_bg_image` ve `factory_video_url` orada olabilir; bu worktree'de **0 eşleşme**. | `company-cover-image.md` §1; `company-cover-video.md` §1.B |
| **Otomatik konuşma tespiti (VAD/ASR)** | Bu fazda kapsam dışı bırakıldı; `silencedetect` yalnız "ses var mı" ayrımı yapabiliyor. | `company-cover-video.md` §10-K5 |
| **iOS / Android uygulama ikonu ailesi** | Ayrı varlık ailesi; `ios/` ve `android/` dizinleri repoda **yok**. | `logo.md` §9 |
| **PDF içi aktif içerik taraması** | Ayrı güvenlik konusu olarak kaydedildi, gereksinim gövdesine alınmadı (NFR olarak izlenir). | `document-attachment.md` §7.6 |
| **Platform logosu (iStoc) varlık yönetimi** | Upload slotu değil — derleme zamanı bundle varlığı. Kuralı `logo.md` §2'de; SRS'de yalnız F1/F2/F15 bulgusu olarak izlenir. | `logo.md` §2 |
| **`completeness_score` skorlaması** | İçerik kuralları ona **dokunmaz**; 3-görsel eşiği orada zaten var. | `icerik-kurallari.md` §8 |

### 1.4 Sürüm ve bağımlılık uyarısı

Kaynak koddaki sürüme duyarlı bileşenler (proje `CLAUDE.md` tablosu ile birlikte
okunmalı): Frappe **v15**, Tailwind **4.3.x** (JS config yok, `@theme`),
Alpine **3.15.x**, Vue **3.5.x**, vue-i18n **11** (tek süslü parantez),
i18next **25.10.x** (çift süslü parantez). Bu ayrım FR-045'in gövdesidir.
Pillow **pinlenmemiş** (§5, K-07) — bu belgedeki DPI davranışı Pillow 11.3.0 ile
ölçüldü (`dpi-ve-cozunurluk.md` §0).

---

## 2. Aktörler ve roller

Rol adları kod okumasından alındı; matrisin kaynağı
`docs/reports/04-yetki-modeli.md` §4.1–§4.3.

### 2.1 Aktör tanımları

| Aktör | Teknik karşılığı | Medya motorundaki işi | Kaynak |
|---|---|---|---|
| **Satıcı (Seller)** | Oturumdan mağazası çözülen kullanıcı (owner veya alt kullanıcı). `ownership.store_of()` → `utils/tenant._get_seller_profile_for_user()` | Ürün görseli/videosu, logo, kapak, vitrin galerisi, KYB belgesi yükler; kendi kütüphanesini yönetir; kendi dosyasını arşivler/siler | `04-yetki-modeli.md` §3.1; `api/seller_media.py:34-54` |
| **Moderatör** | **AYRI ROL OLARAK YOK.** Bugün `Marketplace Admin` rolünün bir alt kümesi olarak davranıyor; `Image Moderation Log.decision` alanında `manual_review` seçeneği var ama **hiçbir kod onu kuyruğa düşürmüyor** | İçerik kurallarının `review`/`manual_review` çıktısını inceler, itirazı karara bağlar | `icerik-kurallari.md` §1.2 madde 3; `04-yetki-modeli.md` §4.1 |
| **Platform yöneticisi (Marketplace Admin)** | `Marketplace Admin` rolü; `_guard()` kapısı — 27 uç | Envanter, optimizasyon başlatma, arşivden geri yükleme, çöpe taşıma, erişim seviyesi değiştirme, denetim okuma/dışa aktarma | `04-yetki-modeli.md` §2.1, §4.1; `api/media_admin.py:32` |
| **Sistem yöneticisi (System Manager)** | `System Manager` rolü; `_guard_destructive()` kapısı — 12 uç | Yukarıdakiler **+ geri alınamaz** işlemler: kalıcı silme, çöp/arşiv purge, kırık referans onarımı, yedek al/geri yükle/sil | `04-yetki-modeli.md` §2.1; `api/media_admin.py:37` |
| **Alıcı (Buyer)** | Giriş yapmış, mağazası olmayan kullanıcı | Yorum görseli yükler (`Listing Review Image`, tavan 10 dosya), avatar yükler, RFQ eki yükler; imzalı URL isteyebilir (yetkisi varsa) | `icerik-kurallari.md` §1.3; `listing_review.py:25`; `user-avatar.md` §1 |
| **Misafir (Guest)** | Anonim istek; `frappe.session.user == "Guest"` | Yalnız **public** medyayı okur (`/files/…`, nginx doğrudan). Private yol → **403**. İmzalı URL **üretemez**; geçerli imzayla **indirebilir** | `04-yetki-modeli.md` §4.3, §7.2; `media_access.py:118` |
| **Administrator** | Frappe süper kullanıcı | `frappe.only_for` onu **atlar** → tüm yönetim uçlarına erişir **ve reddi denetime hiç yazılmaz**. Satıcı arayüzünü **kullanamaz** (`utils/tenant.py:129-130`) | `04-yetki-modeli.md` §4.1 notu, §8-D |
| **Sistem (system)** | Kullanıcı yüklemesi değil; sistemin kopyaladığı/ürettiği dosya | `Cart Item.snapshot_image`, `Order.receipt_url`, transcode çıktısı, yedek blob'ları | `slot-policy.schema.json:65` |

### 2.2 Rol → yetenek matrisi (SRS gereksinimlerine bağlı olan kısım)

`✔` = izinli · `✖` = reddedilir · `A` = yalnız kendi kapsamında

| Yetenek | Administrator | System Manager | Marketplace Admin | Moderatör | Satıcı | Alıcı | Misafir | FR |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|---|
| Slota dosya yüklemek | ✖¹ | ✖¹ | ✖¹ | — | ✔ | ✔ (yorum/avatar) | ✖ | FR-001, FR-007 |
| Kendi kütüphanesini listelemek | ✖¹ | ✖¹ | ✖¹ | — | A | ✖ | ✖ | FR-070 |
| Başka satıcının dosyasını görmek | ✖ | ✖ | ✖ | ✖ | **✖** | ✖ | ✖ | NFR-016 |
| Envanteri/denetimi okumak | ✔ | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | FR-085 |
| `review`/`manual_review` kuyruğunu işlemek | ✔ | ✔ | ✔ | **✔ (FR-037)** | ✖ | ✖ | ✖ | FR-037 |
| Erişim seviyesini değiştirmek (public↔private) | ✔ | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | FR-071 |
| PII dosyasını public yapmak | **✖** | **✖** | **✖** | ✖ | ✖ | ✖ | ✖ | FR-070 |
| Çöpe taşımak / geri almak | ✔ | ✔ | ✔ | ✖ | A | ✖ | ✖ | FR-060 |
| Kalıcı silmek / purge | ✔ | ✔ | **✖** | ✖ | A (bırakma) | ✖ | ✖ | FR-060, FR-065 |
| `legal_hold` konulmuş dosyayı silmek | **✖** | **✖** | **✖** | ✖ | ✖ | ✖ | ✖ | FR-062 |
| İmzalı URL üretmek | ✔ | read yetkisi varsa | read yetkisi varsa | read yetkisi varsa | read yetkisi varsa | read yetkisi varsa | **✖** | FR-072 |
| İmzalı URL ile indirmek | ✔ | ✔ | ✔ | ✔ | ✔ | ✔ | **✔ (imza+süre geçerliyse)** | FR-072, FR-073 |
| Retention süresini değiştirmek | ✔ | ✔ | ✖ | ✖ | ✖ | ✖ | ✖ | FR-061 |

¹ Rol yüksek olsa bile `_get_seller_profile_for_user` mağaza çözemezse
`current_store()` `PermissionError` atar; `Administrator` özel olarak dışlanmıştır
(`utils/tenant.py:129-130`). **Yönetici satıcı arayüzünü kullanamaz** — ayrı
yönetim arayüzü var.

### 2.3 EKSİK AKTÖR — kayda geçirilir

**Moderatör ayrı bir rol olarak tanımlı değildir.** Somut sonuçları:

1. `Image Moderation Log.decision` alanında `manual_review` seçeneği var, hiçbir
   kod bunu bir kuyruğa düşürmüyor — "kaydedilir, kimse bakmaz"
   (`icerik-kurallari.md` §1.2 madde 3).
2. İçerik kurallarının `review` aksiyonu (`product-image.md` §8.1'de 2 kural,
   `category-banner.md` §6'da 2 kural, `document-attachment.md` §5'te 2 kural)
   **gidecek bir kuyruğa sahip değil**.
3. `icerik-kurallari.md` §5'teki aşamalı açılışın **stage_1 çıkış koşulu**
   ("moderatörün el ile verdiği karar ile otomatik kararın uyumu > %95")
   moderatör rolü olmadan **ölçülemez**.

FR-037 bu boşluğu gereksinim olarak kapatır.

---

## 3. Fonksiyonel gereksinimler

**Okuma kılavuzu.** Her gereksinim "**Sistem … YAPMALIDIR**" biçimindedir ve üç
kolon taşır:

- **Kabul testi** — gereksinimin doğrulanma yöntemi. Yürütülebilir bir iddia
  olacak biçimde yazıldı.
- **Bugün** — mevcut kodun durumu: `VAR` (çalışıyor, korunacak) · `KISMEN` ·
  `YOK` · `HATALI` (çalışıyor ama yanlış).
- **Kaynak** — `dosya:satır` ya da `belge §bölüm`.

`YOK`/`HATALI` işaretli bir gereksinimi uygulamak **kod değişikliği** demektir ve
bu görevin kapsamı dışıdır (§5, K-11).

> **REVİZYON 2 (2026-08-18).** §3.A–§3.L rev1'de yazıldı ve bu revizyonda
> **iki yerde** değişti: **FR-019** (logo alfa: ret → uyarı, ölçüm kararı
> düşürdü) ve **FR-138** (tetiği ölçüldü, aşıldı). FR-011'e bir uyarı notu
> eklendi. **§3.M tamamen yenidir** ve yalnız ölçülmüş anomalilerden doğan
> 8 gereksinimi (FR-143…FR-150) içerir. Rev1'in hiçbir satırı silinmedi.

### 3.A — Slot kimliği ve politika kayıt defteri

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-001** | Sistem, her yükleme isteğinde dosyanın hangi slota ait olduğunu **kanonik bir `slot_key` ile** almalı ve doğrulama kararını o slotun politikasına göre vermelidir. | `upload_policy.check()` imzasında `slot_key` parametresi vardır; `slot_key` verilmeden çağrı yapılırsa varsayılan "slotsuz" davranış (bugünkü L0) uygulanır ve bu durum loglanır. Testte: `check(file_name, content, size, media_endpoint, slot_key="product.image")` çağrısı slot politikasındaki `require.min_short_edge` ihlalinde `product_image_short_edge_too_small` kodu döndürür. | **YOK** — imza `file_name`, `content`, `size`, `media_endpoint` alıyor | `upload_policy.py:307-313`; B1 |
| **FR-002** | Sistem, slot politikalarını **tek bir kayıt defterinden** okumalı ve tüm politika dosyaları **tek bir şemaya** uymalıdır. | `tradehub_core/media/pipeline/policy/slots/*.json` dosyalarının **tamamı** `slot-policy.schema.json` ile doğrulanır ve `jsonschema` hata sayısı **0**'dır. `docs/standards/policies/` ile çakışan ikinci kayıt yeri **kaldırılmış veya kanonik olarak işaretlenmiş**tir. | **YOK** — 4 ayrı kayıt yeri, 3 farklı biçim | T3, T6; `README.md` §5 |
| **FR-003** | Sistem, politika şeması doğrulamasını **CI'da** çalıştırmalı ve hata varsa derlemeyi başarısız saymalıdır. | `docs/standards/README.md` §6 betiği CI adımı olarak koşar; çıkış kodu 0 değilse iş başarısızdır. (Betiğin **bilinen kör noktası** şudur ve giderilmelidir: şema hatası olan dosya `continue` ile atlanıyor, D1–D5 o dosyada hiç çalışmıyor.) | **YOK** — betik var, CI bağlantısı yok | `README.md` §6, §6 "kör noktası" notu |
| **FR-004** | Sistem, bir politikadaki **her sayının kaynağını** `sources` bloğunda taşımayı zorunlu tutmalıdır; boş ya da "bilinmiyor" değeri kabul edilmemelidir. | Şema `$defs.provenance` `minLength: 8` ve kabul edilen 4 biçim (`dosya:satır`, `docs/… §bölüm`, `hesap: <formül>`, `ÖLÇÜLMEDİ: <ne yapılmalı>`). `sources` boş olan politika şema doğrulamasını geçmez. Ölçülen mevcut durum: `product-image` 30, `document-attachment` 26, `company-cover-image` 25, `user-avatar` 25, `product-video` 23, `category-banner` 22, `seller-logo` 20, `brand-logo` 19 kaynak girdisi. | **VAR** (şema düzeyinde zorunlu) | `slot-policy.schema.json:421-426`, `:457-461` |
| **FR-005** | Sistem, bir politikayı yalnız **`open_questions` boş** VE **hiçbir `encoder_quality` `null` değil** iken `status: "active"` kabul etmelidir; `draft` politika üretimde **zorlanmamalıdır**. | Yükleyici, `status != "active"` politikayı yalnız "ölç ve logla" modunda uygular; hiçbir ret üretmez. `status="active"` + `open_questions` dolu bir politika yüklenirse hata verir. Bugün 9 politikanın **hiçbiri** bu kapıyı geçemez (T1, T2, T5). | **YOK** — kapı tanımlı, uygulayan kod yok | `slot-policy.schema.json:35`; `README.md` §8 madde 6 |
| **FR-006** | Sistem, her politikanın `bound_to` listesindeki `<doctype>.<field>` çiftlerinin **gerçekten var olduğunu** doğrulamalı ve var olmayan alanı hata olarak bildirmelidir. | `frappe.db.sql("select parent, fieldname from tabDocField where fieldname = %s", alan)` her `bound_to` girdisi için satır döndürür. Bilinen karşı örnek: `header_bg_image` → **0 sonuç** (E2). | **YOK** | `company-cover-image.md` §1, §8.1; `README.md` §6 "ölçmediği" tablosu |
| **FR-007** | Sistem, bir slot politikasının **global tavanı gevşetmesine izin vermemelidir**: efektif tavan `min(slot.accept.max_bytes, upload_policy.MAX_BYTES[kind], Frappe max_file_size)` olmalıdır. | `effective_max` üç değerin minimumunu döndürür. Testte: `product.video` slotu 10 MB, `MAX_BYTES[video]` 200 MB, `platform_limit()` 25 MB → efektif **10 MB**. | **KISMEN** — `min(bizim, platform_limit())` var, plan ve slot zincire girmiyor | `upload_policy.py:262-265`; I4; `kota.md` §5.4 |
| **FR-008** | Sistem, `accept.extensions` listesi ile `accept.mime` listesi ayrıştığında **politikayı sessizce delinmiş saymamalı**, hata bildirmelidir. | Politika yükleyici, uzantı↔MIME karşılığı kümesi tutmuyorsa doğrulama hatası verir. Gerekçe: mevcut kapı kararını **uzantıdan** veriyor (`upload_policy.py:317-320`); iki liste ayrışırsa uzantı kazanır. | **YOK** | I5; `slot-policy.schema.json:108` |

### 3.B — Kabul kapısı (dosya açılmadan)

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-009** | Sistem, MIME/uzantı kararını **içerik imzasına (magic byte)** göre vermeli ve uzantı ile içerik uyuşmazlığında **reddetmelidir**. | `.png` uzantılı, içeriği `%PDF-` olan dosya reddedilir; kod `upload_content_dangerous` / slot bazlı `icerik_uzantiyla_uyusmuyor`. Referans uygulama: `kyb.py:23-58` `_detect_format` (PDF `%PDF-`, JPEG `FF D8 FF`, PNG 8 bayt, WEBP `RIFF`+`WEBP`, DOCX `PK\x03\x04`+`[Content_Types].xml`+`word/`). | **KISMEN** — L0'da uyuşmazlık **yalnız uyarı**; magic-byte yalnız `kyb.upload_kyb_document`'ta | `upload_policy.py:366-369`; `kyb.py:460-478`; `document-attachment.md` §1, §5 |
| **FR-010** | Sistem, `.docx` beyan eden bir dosyanın gerçekten DOCX olduğunu ZIP içeriğinden doğrulamalıdır. | `.zip`'i `.docx` uzantısıyla yükleme reddedilir (`docx_gecersiz`). | **KISMEN** — yalnız KYB ucunda | `kyb.py:46-53`; `document-attachment.json` `content_rules[docx_is_real_docx]` |
| **FR-011** | Sistem, **decompression bomb** koruması olarak, görselin tamamı açılmadan yalnız başlıktan piksel sayısını okumalı ve `accept.max_megapixels_hard` aşılırsa **istisnasız reddetmelidir**. | `PIL.Image.open(...).size` ile ölçülür, piksel okunmadan. 25 MB'lık ama 200 MP açılan bir PNG reddedilir (`too_many_pixels`). Politika değerleri: görsel slotlarında **80 MP**, `product.video` **8,3 MP** (`sources` bloğundaki türetme: `hesap: 3840×2160 / 1e6 = 8,29` → 4K kare üst sınırı; sunucu her hâlükârda 1280 genişliğe indirdiği için 4K üstünün görsel karşılığı yok). | **YOK** — `grep MAX_IMAGE_PIXELS tradehub_core/` → 0 sonuç; benzer koruma yalnız feed indirmede. **REV2 UYARISI: eşik değerinin kendisi de yanlış — bkz. FR-143.** Ayrıca `seller-logo.json` ve `brand-logo.json`'da `accept.max_megapixels_hard` alanı **hiç yok** (FR-144) | `product-image.md` §3.1; `bulk_import/feed_security.py:77-84`; §3.M |
| **FR-012** | Sistem, `allow_animated: false` olan slotlarda animasyonlu görseli **reddetmelidir**; `auto_fix` seçilen slotta ilk kareyi alıp statik türev üretmelidir. | Animasyonlu GIF `user.avatar` slotuna yüklenince `animasyon_duruldu` mesajıyla ilk kare alınır. `product.image`'a yüklenince reddedilir (`animated`). Bugün animasyonlu dosya **hiç işlenmiyor, olduğu gibi saklanıyor** — 5 MB'lık animasyonlu GIF 36 px'lik sohbet avatarında servis edilebiliyor. | **HATALI** — motor atlıyor (`reason="animated"`), dosya kabul ediliyor | `engine.py:111-112`; `gates.py:68-69`; `user-avatar.md` §5.2 |
| **FR-013** | Sistem, medya alanına `data:` URI yazılmasını **reddetmelidir**; medya bir **dosya** olarak yüklenmelidir. | `Admin Seller Profile.logo` alanına `data:image/svg+xml;base64,…` yazma girişimi `logo_data_uri_forbidden` ile reddedilir. Demo seed'i ayrı bir bayrakla muaf tutulur (`utils/security.py:98-109` `_SYSTEM_FLAGS` deseni). | **YOK** — kanal açık; `seed_demo_data.py:231-245` iki güvenlik kapısını da atlıyor | `logo.md` §6.1, SVG-10, F14 |
| **FR-014** | Sistem, `.svg` ve `.svgz` yüklemelerini **SVG-1…SVG-10 ön koşullarının tamamı** karşılanana kadar reddetmeye devam etmelidir. | `.svg` yüklemesi reddedilir. Kısmi açılış (yalnız `utils/security.py:29` uzantı yasağını kaldırmak) **yasaktır**: ikinci kapı (`upload_policy.py:190` `b"<svg"`) hâlâ reddeder, kural test edilemez. `.svgz` **kalıcı olarak** yasak (SVG-6). | **VAR** (iki kapı reddediyor) — korunacak | `utils/security.py:29-30`; `upload_policy.py:190`; `logo.md` §6 |

### 3.C — Geometri kapısı (görsel açıldıktan sonra) — L3

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-015** | Sistem, `require.min_short_edge` ve `require.min_area` kontrollerini **`>=` (eşitlik geçerli)** ile uygulamalıdır. | 1:1 oranda tam `1000×1000` bir görsel `min_short_edge=1000` **ve** `min_area=1.000.000` kurallarının **ikisini de** geçer. `>` kullanılırsa iki kural sınırda çelişir. | **YOK** — 0 slotta piksel kuralı var | `product-image.md` §3.2; `slot-policy.schema.json:142`; B2 |
| **FR-016** | Sistem, en-boy oranı kontrolünü **bağıl** tolerans ile uygulamalıdır: kabul ⟺ `min over r ∈ allowed_ratios of \|(w/h) − r\| / r ≤ ratio_tolerance`. | `3:4` (r=0,75) ve `1:1` (r=1,0) oranları ±%2 toleransta **aynı bağıl** genişliği alır. Mutlak fark kullanılırsa `3:4` için tolerans fiilen %2,7 olur. | **YOK** — oranı yazan tek yer bir önizleme CSS'i (`OgImageUpload.vue:57`) | `product-image.md` §4.1; `slot-policy.schema.json:160`; B2 |
| **FR-017** | Sistem, bir slotun `allowed_ratios` tolerans bantlarının **çakışmadığını** doğrulamalıdır; her kabul edilen görsel **tek bir orana** atanmalıdır. | `product.image` için bantlar: `3:4` → 0,735–0,765; `4:5` → 0,784–0,816; `1:1` → 0,980–1,020. Boşluklar var, çakışma yok. Bu doğrulama politika yükleme anında yapılır. | **YOK** | I8; `product-image.md` §4.2 |
| **FR-018** | Sistem, `require.max_count` ile galeri **adet** sınırını uygulamalıdır. | `product.image` slotunda 13. görselin eklenmesi `too_many_files` ile reddedilir (`max_count: 12`). `company.cover_image` slider'ında 6. slayt reddedilir (`max_count: 5`). | **YOK** — hiçbir galeri slotunda adet kuralı yok | `product-image.md` §3.2; `company-cover-image.json` `require.max_count`; §7-A |
| **FR-019** ⚠ **DEĞİŞTİ (rev2)** | Sistem, logo slotlarında alfa kanalını **tercih etmeli**, alfası olmayan dosyayı **kabul edip uyarmalıdır** — reddetmemelidir. Alfasızlık **ölçülmeli** ve kayıt `logo_opaque` olarak işaretlenmelidir. | Opak JPEG logo **kabul edilir**; `format_no_alpha` **uyarı** mesajı döner ("Logonuz kaydedildi — bu bir engel değil, uyarı."); kayıt `logo_opaque` işaretlenir. Alfalı kabul modları değişmedi: `RGBA`, `LA`, `transparency` taşıyan `P`. Politikada karşılığı: `require.alpha_channel = "optional"`, `content_rules[no_alpha_channel].action = "warn"` — **ikisi de dosyada doğrulandı** (`seller-logo.json`, `brand-logo.json`, 2026-08-18). `format_priority` içinde `png_with_alpha` **hâlâ ilk sırada**, `jpeg_opaque` son sırada: tercih korundu, zorunluluk kalktı. | **YOK** | `logo.md` §13-K1 (**ölçümle çözüldü**); `08-canli-olcum.md` §2.2; `09-slot-bazinda-istatistik.md` §4.6 |
| **FR-019-R** | *(rev2 gerekçe kaydı — gereksinim değil, karar izi)* Bu değişiklik bir kriter gevşetmesi **değildir**; `logo.md` §13-K1'de **önceden yazılmış** sayısal tetiğin çalışmasıdır: *"JPEG payı %10'u geçerse karar B'ye çevrilmeli."* Ölçüm: **9/18 = %50** — tetiğin **beş katı**. Öneri A (ret) ölçümle düştü. Ölçümün **çürütmediği** gerekçe aynen duruyor: 16 render noktasının 11'i logonun altına açık plaka boyuyor, opak JPEG orada hâlâ görünür kutu bırakıyor — bu yüzden karar "yoksay" değil, **"uyar ve say"**dır. Ters tetik de yazılı: geçiş sonunda JPEG payı %10'un altına inerse sert ret yeniden gündeme gelir. **Ölçülen bedel:** v1 (alfa zorunlu) kuralı `seller.logo` stokunun **%84,2'sini** reddediyordu; v2 ile **%31,6**'ya indi ve kalan 6 uyumsuzun **hiçbiri format kaynaklı değil** (2 kayıp dosya, 2 aşırı yatay logo, 1 büyük PNG, 1 çok küçük logo). | ölçüm kaydı | — | `09-…md` §4.6 |
| **FR-020** | Sistem, logo master'ını kabul bandındaki (`1:2 … 2:1`) her orandan **1:1'e saydam letterbox** ile normalize etmeli; **asla kırpmamalıdır**. | Normalize edilmiş master kare olduğu için `object-cover` kullanan **5** render noktasında kırpma matematiksel olarak imkânsız hâle gelir: `seller-shop.ts:129`, `seller-dashboard.ts:66`, `seller-dashboard.ts:158`, `StorefrontEdit.vue:79`, `StorefrontLayoutEditor.vue:247`. Bu, **mevcut kodun tek satırına dokunmadan** çözülür. | **YOK** | `logo.md` §3.5, F4 |
| **FR-021** | Sistem, `user.avatar` slotunda `1:1` oranı **zorunlu** tutmalı (tolerans ±%2) ve dışını **reddetmelidir**. | 4:3 bir avatar reddedilir (`kare_degil`). Gerekçe: 8 render noktasının **tamamı** kare kutu + `rounded-full` + `object-cover`. `on_violation.require = reject` (diğer slotlarda `warn`) — 1:1 dışı avatar daire maskede **sistematik olarak** bozulur ve düzeltmesi kullanıcı için kolaydır. | **YOK** — bugün sessizce merkezden kırpılıyor | `user-avatar.md` §3, §6 |
| **FR-022** | Sistem, dairesel maskeli slotlarda **güvenli alanı** dairenin iç teğet karesi (`1/√2 = %70,7`) olarak uygulamalı ve dışına taşan içerik için **uyarı** üretmelidir. | `circle_inscribed_square_fraction` kuralı, eşik `0.707`, aksiyon `warn`. | **YOK** | `user-avatar.md` §3 |
| **FR-023** | Sistem, `company.cover_image` slotunda güvenli alanı **merkez %41,7'lik dikey şerit** olarak uygulamalı ve dışına taşan içerik için uyarı üretmelidir. | Türetme: kutunun oran aralığı 2,00…4,80 (360px→1920px viewport, `section-registry.ts:103` `h-[180px] sm:220 md:320 lg:400` + tam viewport genişliği). Önerilen master oranı 24:5 = 4,80. `görünen genişlik oranı = 2,00 / 4,80 = 0,417`. Dikeyde `cover` daima tam yüksekliği kullanır → dikey güvenli alan %100. | **YOK** | `company-cover-image.md` §3.3 |
| **FR-024** | Sistem, `category.banner` slotunda güvenli alanı **merkez %42 × %42** olarak uygulamalıdır. | Türetme: kutu oran aralığı 0,82…4,68 (`CategoryShowcase.ts:245` bento grid, `columns=4` varsayımı). En kötü durumu minimize eden oran iki ucun geometrik ortalamasıdır: `sqrt(0,82 × 4,68) = 1,96 ≈ 2:1`. O oranda en kötü kesit iki eksende eşitlenir: `0,82/1,96 = 0,418` ve `1,96/4,68 = 0,419`. | **YOK** | `category-banner.md` §3.3 |
| **FR-025** | Sistem, `company.cover_video` slotunda videoya gömülü metni **title-safe** dikdörtgen içinde tutmayı zorunlu kılmalıdır: sol/sağ %10, üst %6, alt %26 iç boşluk. | 1280×720 master üzerinde kullanılabilir alan `1024 × 490 px`. Alt %26 türetmesi: kontrol çubuğu 40 px (`StoreHeader.ts:329`, `:333-334`), en kötü kutu yüksekliği 166,5 px (360px viewport) → `40/166,5 = %24,0` + %2 emniyet. Ayrıca merkezdeki **72 × 72 px** (56 px oynat düğmesi `StoreHeader.ts:321` + 8 px pay) kritik metin taşımamalıdır. | **YOK** | `company-cover-video.md` §3.1 |
| **FR-026** | Sistem, kapak videosuna **gömülü logo** yüklenmesinde uyarı üretmelidir (ret değil). | `cover_video_burned_logo_warning`. Gerekçe: arayüz RTL'de mantıksal yön özellikleriyle (`start-2`/`end-2`/`ms-1`) otomatik aynalanıyor; **videoya gömülü logo aynalanamaz**. Mağaza logosu zaten videonun yanında ayrı `<img>` olarak render ediliyor (`CompanyInfo.ts:47`, 120 px). | **YOK** | `company-cover-video.md` §3.2 |
| **FR-027** | Sistem, belge slotunda geometri ihlalini **`warn`** ile karşılamalı, **reddetmemelidir**. | Uzun kenarı 2339 px altındaki bir vergi levhası kabul edilir + `cozunurluk_dusuk` uyarısı üretilir. Gerekçe: telefonla çekilmiş düşük çözünürlüklü belge **bugün kabul ediliyor** ve KYB süreci onun üzerinden yürüyor; sert ret çalışan bir akışı kırar. | **YOK** (uyarı da yok) | `document-attachment.md` §5 "Neden `require: warn`" |

### 3.D — Master üretimi, DPI ve türev merdiveni

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-028** | Sistem **asla upscale yapmamalıdır**; master üretimi yalnız küçültme yönünde çalışmalıdır. | `engine.optimize(800×600, max_dim=2000)` → **800×600** (büyütülmedi). Ölçüldü (Pillow 11.3.0): `800×600@2000 → 800×600`; `1200×900@2560 → 1200×900`; `3000×3000@2400 → 2400×2400`; `4000×2000@2000 → 2000×1000`. Test: `tests/test_policy_dpi.py::test_thumbnail_upscale_yapmaz`, `::test_zaten_tavanin_altindaki_dosya_buyumez`. | **VAR** — korunacak | `engine.py:97,117`; `dpi-ve-cozunurluk.md` §2.1 |
| **FR-029** | Sistem, **DPI değişimini asla piksel kaybına çevirmemelidir.** | `3000×3000 @300dpi → 2400×2400 @72dpi` doğru; `3000×3000 @300dpi → 720×720` (72/300 oranının piksele uygulanması) **hatadır**. Her slot politikasında `dpi_policy.pixels_preserved` **her zaman `true`**; test her policy'de bu üçünü (`output_dpi`, `strip_input_dpi`, `pixels_preserved`) zorlar: `tests/test_policy_dpi.py::test_dpi_policy_pikselin_korundugunu_soyluyor`. | **VAR** (fiilen) | `dpi-ve-cozunurluk.md` §1; `policies/_schema.md` |
| **FR-030** | Sistem, çıktı DPI metadata'sını **açıkça yazmalıdır** (ekran medyası 72, belge 200); metadata'yı tüketici uygulamanın varsayılanına bırakmamalıdır. | `engine.py`'deki her `save()` çağrısı `dpi=(72,72)` taşır (WEBP hariç — biçimde alan yok). Ölçülen mevcut durum: JPEG→JPEG çıktısı `dpi=None`, `jfif_unit=0`, `jfif_density=(1,1)`; PNG→PNG `dpi=None` (pHYs düşüyor); **TIFF→TIFF `(1, 1)`** (Pillow varsayılanı — "1 dpi" DTP'de görseli 2000 inç genişliğinde açar). `grep -rn "dpi\|DPI" tradehub_core/media/ tradehub_core/api/` → **0 sonuç**. Mevcut durumu sabitleyen test: `::test_optimize_ciktisinda_mutlak_dpi_metadatasi_yok` (motor düzeltilirse **kırılır**, kasıtlı). | **YOK** | `dpi-ve-cozunurluk.md` §4, §5 |
| **FR-031** | Sistem, `master.max_long_edge` değerini kod tabanında **var olan** bir eşikten türetmeli; yeni sayı uydurmamalıdır. | Politika değerleri ve kaynakları: `company.cover_image` **2560** (`presets.py:14` `safe`), `category.banner` **2000** (`presets.py:15` `balanced`), `product.video` **1280** (`transcode.py:242` ffmpeg hedefi), `product.image` **2400** (hesap: tablet dikey 768 CSS px × DPR3 = 2304 → üst basamak), `user.avatar` **256** (hesap: 72 × DPR3 = 216 → üst basamak), `document.attachment` **5000** (türetme: 300 dpi'de 42 cm kenar; küçültmeyi pratikte kapatır), logo **4096** (türetme: vektörden export edilmiş büyük PNG reddedilmesin). Test: `::test_max_long_edge_preset_tavanini_asmiyor`. | **KISMEN** | `README.md` "Tabloyu okuma notları"; `product-image.md` §5.3 |
| **FR-032** | Sistem, master invaryantını korumalıdır: `max_long_edge² / 1e6 ≥ max_megapixels`. | `user.avatar`: `256²/1e6 = 0,065536 ≥ 0,0655` ✔ (değer **aşağı** yuvarlandı; yukarı yuvarlanırsa invaryant kırılır). D4 kontrolü bunu 6 uyumlu politikada 0 hatayla geçmiş. | **YOK** (kod tarafında) | I2; D4; `README.md` §6 |
| **FR-033** | Sistem, `master.min_long_edge` altında kalan dosyayı **reddetmemeli**, "under-spec" işaretleyip **hangi profilleri üretemediğini söylemelidir**. | Uzun kenarı 1000–1999 px olan bir ürün görseli kabul edilir, master üretilir, `master_under_spec` uyarısı gösterilir ve `w1920` profili üretilmez. Ret eşiği `require.min_short_edge`'dir, `min_long_edge` değildir. | **YOK** | `product-image.md` §3.3; `slot-policy.schema.json:196` |
| **FR-034** | Sistem, her türev profilini **somut bir CSS kutusu × DPR hesabından** türetmeli; `derived_from` alanı olmayan profil kabul edilmemelidir. | Şema `profiles[].derived_from` zorunlu. D2 kontrolü: `derived_from`/`serves` eksik profil **0**. Profil genişliği `master.max_long_edge`'i aşamaz (D2, I1). | **VAR** (şema düzeyinde) | `slot-policy.schema.json:279,333`; D2; I1 |
| **FR-035** | Sistem, her master'dan slot politikasında tanımlı **türev merdivenini üretmelidir**. | Slot başına profil sayısı ve genişlikleri: `product.image` **7** (96/192/384/640/768/1280/1920), `company.cover_image` **5** (768/1280/1920/2560 + `cover_16x9_1000`), `seller.logo` ve `brand.logo` **5** (64/128/256/512 + og1200×630), `user.avatar` **3** (96/160/256), `category.banner` **3** (480/960/1920), `product.video` **2** (poster_192, poster_1024), `document.attachment` **1** (`doc_thumb_512`, **private**). | **YOK** — bir yükleme → bir dosya | `03-render-envanteri.md` §6.3; ilgili politika JSON'ları |
| **FR-036** | Sistem, iki komşu profil arasındaki oran **1,25'in altındaysa** profilleri birleştirmelidir. | `product.image` merdiveni 9 adaydan 7'ye indi: `1080→1280` (1,19) birleşti, `1600→1920` (1,20) birleşti. **İstisna: `640→768` (1,20) birleştirilmedi** — ikisi de tam bir gerçek kutuya oturuyor (640: 640px viewport'ta kart @2x = 592; 768: PD mobil tablet dikey @1x'e **tam eşit**). Gerekçesi politikada yazılı ve `768` "merdivenin en zayıf halkası, depolama bütçesi izin vermezse **ilk düşürülecek profil**" olarak işaretli. | **YOK** | `product-image.md` §6 |
| **FR-037** | Sistem, kare kutuya giden profilleri (`w96`–`w768`) **`pad` ile 1:1'e dolgulamalı**; detay/zoom kaynağı profilleri (`w1280`, `w1920`) **`contain` bırakmalıdır**. | 3:4 bir ürün görseli `w640`'ta 1:1'e dolgulandığı için kartlardaki `object-cover` **kırpmaz**. `w1920`'de dolgu yapılmaz: 3:4'ü 1:1'e dolgulamak 1920 px'in **480 px'ini beyaza** harcar, ürün 1440 px kalır ve zoom talebi (1858 px) karşılanmaz. **Bu bir görünüm değişikliğidir ve ticari onay gerektirir.** | **YOK** | `product-image.md` §7, §4.3 |
| **FR-038** | Sistem, logo türevlerini **kayıpsız** üretmelidir. | Logo slotunda `engine.to_webp`'in kayıplı yolu (`quality=80` sabit, `engine.py:148`, `:180`) **çalışmaz**; `lossless=True, method=6` kullanılır. Gerekçe: q80 kayıplı encode logonun keskin kenarında halkalanma (ringing) üretir. Türev bayt tavanları ölçülen referanslardan: 512→**40 KiB** (`icon-512.png` = 27.128 B +%51), 256→**16 KiB** (`icon-256` = 9.159 B +%79), 128→**8 KiB** (`icon-128` = 3.600 B +%128), 64→**4 KiB** (ara değer ≈1.700 B +%141). Tavan aşılırsa üretim **başarısız sayılmaz**; `logo_derivative_oversize` uyarısıyla yazılır. | **HATALI** — `seller_media` yolundan geçen her logo q80 WebP'ye çevriliyor | `logo.md` §3.6, §3.7, §5, F5 |
| **FR-039** | Sistem, `master.strip_metadata.gps` alanını **`true`** uygulamalı; GPS koordinatlarını çıktıdan silmelidir (KVKK). | Ürün görselinden `GPSInfo` IFD (etiket 34853) silinir. `strip_metadata.icc` ise **`false`** kalmalıdır — ICC bilinçli olarak korunuyor; silmek renk yönetimini bozar. EXIF silinmeden **önce** yön bilgisi piksellere uygulanmalıdır (`ImageOps.exif_transpose`). | **YOK** — EXIF temizliği kod tabanında yok; avatar ucu engine'e hiç girmiyor | `product-image.md` §3.3; `slot-policy.schema.json:226`; `engine.py:11-13,116`; `user-avatar.md` §8.4 |
| **FR-040** | Sistem, türev dosyalarını **orijinalin yanında, aynı shard dizininde, ekli suffix** ile saklamalıdır. | Yerleşim: `/files/<ab>/<hash>.jpg` (orijinal), `/files/<ab>/<hash>_thumb.webp`, `/files/<ab>/<hash>_768.webp`, `/files/<ab>/<hash>_720.webm`. Dosya adı `<sha256(içerik)[:32]>.<uzantı>`, shard `hash[:2]` (256 alt dizin). Test: `test_media_naming.py` (9 test). | **KISMEN** — isimlendirme+shard VAR, türev YOK | `MEDYA-DEPOLAMA-STANDARDI.md` §4, §5 |
| **FR-041** | Sistem, kapak videosu slotunda **yerinde değiştirmeyi (in-place replace) yasaklamalı**; rendition'ları ayrı adreslere yazmalıdır. | `.mp4` adresine VP9/WebM baytı yazılmaz. Bugünkü hata (Ç1): `dst_path = f"{src_path}.transcoding.webm"` → `os.replace(dst_path, src_path)` → nginx `Content-Type`'ı uzantıdan türettiği için **WebM baytları `video/mp4` olarak servis ediliyor**; `<source type="video/mp4">` yazmak **yalan** olur. Kapak slotu 6 nesne tutar: 720p WebM + 720p MP4 + 480p WebM + 480p MP4 + poster + 6 s önizleme klibi. | **HATALI** | `company-cover-video.md` §6.5, Ç1; `transcode.py:230,252` |
| **FR-042** | Sistem, poster'ı satıcı yüklememişse **otomatik üretmelidir**. | Dört adım: (1) `Seller Gallery Image.poster_image` doluysa **o kazanır**; (2) boşsa `ffmpeg -ss 0.5 -t 4.5 -vf "thumbnail=n=120,scale=1280:-2" -frames:v 1 -c:v libwebp -quality 78`, arama penceresi `[0,5 s , min(5 s, süre × 0,25)]`; (3) seçilen karenin ortalama parlaklığı `<%6` veya `>%94` ise pencere `[süre×0,25 , süre×0,50]`'ye kaydırılıp bir kez daha denenir, ikinci deneme de takılırsa `cover_video_poster_unresolved` ile satıcıdan el ile poster istenir; (4) çıktı WebP 1280×720, **≤120 KB** (q78 → q70 → q62 → 854×480). | **YOK** — poster boşsa kutu siyah kalıyor (Ç7) | `company-cover-video.md` §6.9 |
| **FR-043** | Sistem, mağaza kartı/arama sonucu hover'ı için **6 saniyelik, sessiz, döngülü** önizleme klibi üretmelidir. | 854×480 VP9 WebM (+H.264 MP4 yedeği), `-an` (ses yok), döngü açık, **≤400 KB** (türetme: 6 s × 500 kbps = 3 Mbit = 375 KB → 400 KB). Başlangıç noktası poster'ın seçildiği zaman damgası — kullanıcının gördüğü kareden başlar. Kapak kutusunda **kullanılmaz**. | **YOK** | `company-cover-video.md` §6.11 |
| **FR-044** | Sistem, og:image türevini **contain + pad + düz beyaz zemin** ile üretmeli; kırpmamalı ve alfayı belirsiz bir renge düşürmemelidir. | 1:1 bir logo 1200×630 canvas'a merkeze, en fazla `630 × 0,72 = 453 px` yükseklikte yerleşir (%14 üst + %14 alt güvenli alan). Zemin `#FFFFFF` (PIL varsayılanına bırakılmaz). Bugünkü hasar ölçüldü (F13): `og_image.py:34` `convert("RGB")` → alfa düşer; `:45-49` cover-crop → 1:1 logonun yüksekliğinin **%47,5'i** kesilir (`top = (1200−630)//2 = 285`, 285+285 = 570 / 1200); `:51` JPEG q85. `data:` URI kaynaklar sessizce `""` dönüyor → **loglanmalıdır**. | **HATALI** | `logo.md` §3.10, F13; `seo/meta_builder.py:261,282` |
| **FR-045** | Sistem, belge slotunun türevini de **private** saklamalıdır. | `doc_thumb_512` `is_private=1`. Gerekçe: bir kimlik kartının 512 px'lik küçük resminde TC kimlik numarası okunabilir. Orijinal **değişmeden** saklanır (`presets.py:44-53` bunu 8 doctype için zaten sağlıyor). | **KISMEN** — orijinal muafiyeti VAR, türev YOK | `document-attachment.md` §4 |

### 3.E — İçerik uygunluk kuralları ve moderasyon

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-046** | Sistem, içerik kurallarını **tek bir ön işleme** üzerinde çalıştırmalıdır: EXIF transpose → uzun kenar **512 px** LANCZOS → RGB, luma BT.601 → alfa beyaz zemine kompozit. | Ön işleme değişirse eşikler anlamını yitirir (Laplacian varyansı **ölçeğe duyarlıdır**). Test: aynı görsel iki farklı analiz ölçeğinde farklı `laplacian_var` verir; motor **her zaman** 512 px kullanır. | **YOK** | `icerik-kurallari.md` §3.0; `content_rules.json` `preprocessing` |
| **FR-047** | Sistem, ölçülemeyen görselde kuralı **sessizce atlamalı** (`pass` + sebep `not_measurable`) ve uyarı üretmemelidir. | Animasyonlu görsel veya uzun kenarı **< 200 px** olan görsel `pass` döner, sebep loglanır. "Ölçemedim"i "temiz" saymak da "kirli" saymak da yanlıştır. | **YOK** | `icerik-kurallari.md` §3.0; `content_rules.json` `preprocessing.skip_if` |
| **FR-048** | Sistem, **yalnız iki kuralın** RED üretmesine izin vermelidir: `nsfw_content` ve `extreme_blur`. Diğer 7 kural en fazla `warn` döner ve yayını **asla engellemez**. | `content_rules.json` `decision_model.reject_allowed_rules` = `["nsfw_content", "extreme_blur"]`; ölçülen aksiyon dağılımı: `warn` **7**, `reject` **2**; `can_reject: true` olan kural sayısı **2**. Gerekçe: satıcı ilk üç yanlış uyarıdan sonra hepsini kapatmayı öğrenir. | **YOK** (politika yazılı, uygulayan kod yok) | `icerik-kurallari.md` §2; `content_rules.json` |
| **FR-049** | Sistem, birden çok kural tetiklendiğinde **en yüksek aksiyonu** uygulamalı, uyarıları **birikimli** listelemelidir. | Sıra: `reject > manual_review > warn > pass`. Bir uyarı diğerini bastırmaz. | **YOK** | `content_rules.json` `decision_model.aggregation` |
| **FR-050** | Sistem, RED kararında dosyayı **silmemeli**; ilgili kaydı `Hidden` durumuna alıp moderasyon kuyruğuna düşürmeli ve itiraza açık tutmalıdır. | "Sessiz silme YOK." Mevcut davranışla aynı: `moderation.py:172-173` `Listing Review.status = "Hidden"`. | **VAR** (yalnız yorum görselinde) | `moderation.py:172-173`; `icerik-kurallari.md` §2 |
| **FR-051** | Sistem, moderasyon skorlarını **eşiklemelidir**; kararı yalnız dil modelinin döndürdüğü `decision` dizgesine bırakmamalıdır. | `nsfw_score >= 0.85` **veya** `violence_score >= 0.85` → RED; `0.50–0.85` bandı → `manual_review`; stub modunda → `pass`. Bugünkü hata: `moderation.py:165-166` skorları **kaydediyor**, `:172` kararı yalnız `decision` **string**'ine bakarak veriyor — yani eşik diye bir şey yok. | **HATALI** | `icerik-kurallari.md` §1.2 madde 2, §3.7 |
| **FR-052** | Sistem, moderasyonu **ürün görsellerine ve satıcı vitrin görsellerine de** uygulamalıdır. | Hook bugün yalnız `Listing Review Image` → `after_insert` (`hooks.py:437-439`). `Listing Image` (ürün görseli) ve `Seller Gallery Image` **hiç moderasyondan geçmiyor** — yani pazaryerinde asıl teşhir edilen görseller denetimsiz. Kabul: her üç doctype için moderasyon kaydı üretilir. | **YOK** | `icerik-kurallari.md` §1.2 madde 1, §7.8 |
| **FR-053** | Sistem, `manual_review` kararını **gerçek bir kuyruğa** düşürmelidir. | `Image Moderation Log.decision` alanında `manual_review` seçeneği var, **hiçbir kod bunu bir kuyruğa düşürmüyor**. Kabul: moderatör bir listede bekleyen kayıtları görür ve karara bağlar. Bu FR-037'nin (moderatör rolü) önkoşuludur. | **YOK** — "kaydedilir, kimse bakmaz" | `icerik-kurallari.md` §1.2 madde 3 |
| **FR-054** | Sistem, moderasyon sağlayıcısı erişilemediğinde **fail-open** davranmalı **ama sessiz kalmamalıdır**. | Anahtar yoksa `_stub_check_image()` her şeye `allow` (`moderation.py:95-97`) — bu davranış **korunur** (yükleme akışı kırılmasın), ancak bir **alarm** üretilmelidir. Bugün: anahtar süresi dolarsa moderasyon **sessizce** kapanır, hiçbir uyarı yok. | **HATALI** (fail-open var, alarm yok) | `icerik-kurallari.md` §1.2 madde 4 |
| **FR-055** | Sistem, moderasyon çağrısını **asenkron** çalıştırmalıdır. | Bugün `after_insert` içinde 30 saniyeye kadar bloklayan HTTP isteği var (`moderation.py:130` `timeout=30`) → yükleme gecikmesi doğrudan sağlayıcının yanıt süresine bağlı. Kabul: `frappe.enqueue` ile kuyruğa alınır. Ayrıca kural motorunun kendi maliyeti görsel başına **100 ms**'yi aşarsa `after_insert`'te değil kuyrukta çalışmalıdır (NFR-005). | **HATALI** | `icerik-kurallari.md` §1.2 madde 5, §7.7 |
| **FR-056** | Sistem, riskli kategorilerde RED yerine `manual_review` uygulamalıdır. | `content_rules.json` `category_overrides` 5 kural: iç giyim/mayo/çorap/tekstil → `nsfw_content: manual_review`; bıçak/kesici/hırdavat/av → `manual_review`; gıda/kasap/et → `manual_review`; tablo/ayna/çerçeve → `border_frame: enabled=false`. **Kategori adları placeholder'dır** ve gerçek `Product Category` adlarıyla değiştirilmelidir (§8.5). | **YOK** | `icerik-kurallari.md` §3.7, §7.6 |
| **FR-057** | Sistem, içerik kurallarını **üç aşamada** açmalıdır ve kalibre edilmemiş eşikle RED üretmemelidir. | **Stage 0 — gölge (≥14 gün):** tüm kurallar çalışır, loglanır, kullanıcıya hiçbir şey gösterilmez; RED kuralları da yalnız loglar. Çıkış: el ile örneklenen 200 tetiklenmede FP < %5 (RED kurallarında < %1). **Stage 1 — yalnız uyarı:** `extreme_blur` ve `nsfw_content` `reject` **yerine** `manual_review`. Çıkış: moderatör kararı ile otomatik karar uyumu > %95. **Stage 2 — uygulama:** yalnız o iki kural RED üretir, diğer her şey **kalıcı olarak** uyarı kalır. **Geri alma tetiği:** haftalık itiraz oranı reddedilen görsellerin %10'unu aşarsa stage 1'e dönülür. | **YOK** | `icerik-kurallari.md` §5; `content_rules.json` `rollout` |
| **FR-058** | Sistem, kullanıcı mesajlarına **ölçülmemiş istatistik yazmamalıdır**. | `min_image_count` mesajı "daha çok tıklanıyor" der ama **oran/yüzde içermez** — gerçek tıklanma farkı bu kod tabanında ölçülmedi. Kabul testi: mesaj kataloğunda kaynağı olmayan hiçbir sayı geçmez. | **VAR** (politika bunu bilinçle uyguluyor) | `icerik-kurallari.md` §3.9 notu |
| **FR-059** | Sistem, minimum görsel sayısı uyarısını **yayın öncesinde** göstermeli ve sayım tanımını değiştirmemelidir. | Eşik `< 3`; `primary_image` sayıya **dâhil değil** — `completeness.py:139-140` ile **aynı** tanım. Uyarı `completeness_score`'a **dokunmaz**. | **KISMEN** — eşik `completeness.py:231-232`'de var, görünür uyarı yok | `icerik-kurallari.md` §1.3, §3.9 |

### 3.F — Hata sözleşmesi ve kullanıcı mesajları

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-060** | Sistem, her reddi **`(kod, retryable)`** çifti olarak döndürmeli; istemci karar verirken hata **metnine değil koda** bakmalıdır. | Mevcut sözleşme 14 kod taşıyor (`upload_policy.py:104-139`). Slot bazlı kodlar `on_violation.error_code_prefix` ile üretilir: `product.image` → `product_image_<message_key>` (ör. `product_image_ratio_not_allowed`); logo slotları → önek `logo`; diğerleri → önek `upload`. `retryable` kullanıcının dosyasıyla ilgili hatalarda **false** (`upload_policy.py:97-100`). | **VAR** (çekirdek) — korunacak | `upload_policy.py:104-139`; `product-image.md` §8.3 |
| **FR-061** | Sistem, kodlu ret sözleşmesini **tüm yükleme uçlarında** kullanmalıdır. | Bugün **iki uç sözleşmeyi atlıyor**: `identity.py:940,952` (avatar) ve `kyb.py:440-476` (belge) düz `frappe.throw` metni fırlatıyor → istemci koda değil metne bakmak zorunda, çeviri değişince kırılıyor. Kabul: her iki uç `upload_policy.reddet(Kod, mesaj)` çağırır. | **KISMEN** | E9; `user-avatar.md` §6; `document-attachment.md` §5 |
| **FR-062** | Sistem, her kullanıcı mesajında **iki soruyu** yanıtlamalıdır: (1) NEDEN reddedildi, (2) NASIL düzeltilir. | Şema `$defs.messageMap` `minLength: 20` ile tek kelimelik metni engelliyor. Her `content_rules[].message_key` `messages.tr` içinde **var olmak zorundadır** (D3, I6). Ölçülen mesaj sayıları: `product-image` 18, `document-attachment` 12, logo slotları 12, `product-video` 10, `user-avatar` 9, `company-cover-image` 8, `category-banner` 8. | **VAR** (şema düzeyinde) | `slot-policy.schema.json:462-471`; I6; D3 |
| **FR-063** | Sistem, ret mesajını sahaya özgü **uygulanabilir** bir çözümle bitirmelidir. | Örnek (`product-image.md` §8.2): kısa kenar reddinde mesaj, WhatsApp'tan gelen görsellerin sıkıştırıldığını ve dosyanın e-posta/bilgisayar üzerinden alınması gerektiğini söyler. Gerekçe: B2B satıcıların görselleri tedarikçiden WhatsApp ile gelir; bu cümle olmadan kullanıcı aynı sıkıştırılmış dosyayı tekrar tekrar dener. | **YOK** | `product-image.md` §8.2 |
| **FR-064** | Sistem, yükleme yanıtında **optimizasyon özeti** döndürmelidir. | Yanıtta `optimization` bloğu: `source_width`, `source_height`, `output_width`, `output_height`, `source_dpi`, `output_dpi`, `source_bytes`, `output_bytes`, `pixels_preserved`, `reason`. Bugün `_kaydet()` yalnız `{file_url, file_name, bytes, …}` döndürüyor ve `bytes` **çıktı** boyutudur — girdi boyutu, girdi/çıktı piksel ölçüsü ve girdi DPI'sı yanıtta **yok**. Bu blok olmadan §FR-065'teki metin **üretilemez**. | **YOK** | A3; `dpi-ve-cozunurluk.md` §6-A3; `seller_media.py:330-336` |
| **FR-065** | Sistem, optimizasyon özetinde DPI satırını **"(piksel korundu)" ibaresi olmadan göstermemelidir.** | Hedef metin: `Görseliniz optimize edildi: 3000×3000 → 2400×2400 piksel, 300 dpi → 72 dpi (piksel korundu), 12,4 MB → 1,1 MB`. İbare olmadan cümle satıcıya *"çözünürlüğüm %76 düştü"* (72/300) diye okunur → destek talebi + gereksiz yeniden yükleme. Kural: `parts.dpi` **asla** `parts.pixels` olmadan gösterilmez. Çeviri zorunlulukları: en `(pixels preserved)`, ru `(пиксели сохранены)`, ar `(تم الحفاظ على البكسل)`. | **YOK** | `dpi-ve-cozunurluk.md` §7.1, §7.4, §7.5 |
| **FR-066** | Sistem, ölçü verisi gelmediğinde **sayı uydurmamalı**, ayrı bir mesaj anahtarı kullanmalıdır. | `media.optimize.summaryUnknown` = "Görseliniz optimize edildi. Yeni boyut: {toSize}". Karar ağacı: `optimization` bloğu YOK → `summaryUnknown`; `source_dpi == null` → `parts.dpi` **gösterilmez** (istemci canvas'ından geçen dosyada DPI yoktur). | **YOK** | `dpi-ve-cozunurluk.md` §7.4 |
| **FR-067** | Sistem, iki frontend için **doğru interpolasyon sözdizimini** kullanmalıdır. | Storefront i18next → **çift** süslü parantez (`{{fromW}}`), dosyalar `tradehubfront/src/i18n/locales/{tr,en,ar,ru}.ts`. Panel vue-i18n@11 → **tek** süslü parantez (`{fromW}`), dosyalar `admin-panel/frontend/src/i18n/locales/{tr,en,ar,ru}.js`. Storefront anahtarlarını kopyalayıp `{{}}` bırakmak panelde **ham metin** basar. | **YOK** | `dpi-ve-cozunurluk.md` §7.2, §7.3; `admin-panel/frontend/package.json:34` |
| **FR-068** | Sistem, sayı ve ölçü biçimini **tek yardımcıdan** üretmelidir. | 1024 tabanı, tek ondalık, ondalık ayırıcı **virgül** (`mediaFormat.js:7-17` `formatBytes`); piksel ayırıcı **`×` (U+00D7)**, `x` değil (`mediaFormat.js:22` `formatDimensions`). Tarih/saat için `MEDYA-TARIH-STANDARDI.md`'deki tek kaynak (`formatDay`, `formatDateTime`, `formatClock`, `formatAgo`, `toTimestamp`) kullanılır; API çıktısı **ISO 8601 + saat dilimi kayması** (`+03:00`) taşır. | **VAR** — korunacak | `dpi-ve-cozunurluk.md` §7.1; `MEDYA-TARIH-STANDARDI.md` §2 |
| **FR-069** | Sistem, RTL dilde sayı grubunun yön kaymasını önlemelidir. | Arapça'da `3000×3000` ifadesi LRI/PDI (`⁦…⁩`) ile sarılır. `tradehubfront/src/i18n/index.ts` RTL listesi `ar`'ı içeriyor ama sayı yönü için özel sarmalayıcı **yok** → üretimde göz kontrolü gerekir (§8.6). | **YOK** | `dpi-ve-cozunurluk.md` §7.5 |

### 3.G — Kota

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-070** | Sistem, satıcı başına **toplam depolama** kotasını uygulamalıdır. | Plan varsayılanları (`v15_9_17_seed_storage_quota.py:38-44`): `enterprise` **-1** (sınırsız), `pro` **5000 MB**, `premium` **5000**, `starter` **2000**, `free` + eşleşmeyen custom plan **500** (`_FALLBACK_MB`). Eşleşme plan adında **alt dize** arıyor (`:47-50`) → "Pro Plus" → 5000. Yama **idempotent** (`:69-71`) — admin override'ları ezilmiyor. Test: `test_media_quota.py` (10 test), `test_media_pipeline_integration.py::test_dusuk_kotada_upload_reddedilir`. | **VAR** — korunacak | `kota.md` §1.1 |
| **FR-071** | Sistem, kota limiti planda tanımsızsa (`None`) yüklemeyi **reddetmemelidir** (fail-open) ve bu tutarsızlığı belgelemelidir. | `checks.py:262-263` `limit_mb is None` → `return`. **Dikkat:** `core.within_quota` aynı `None` girdisine **False** döndürüyor (`core.py:221-223`) — iki fonksiyon **ters** cevap veriyor. Medya tarafındaki fail-open bilinçli ve gerekçeli, ama tutarsızlık belgelenmeliydi. Test: `test_media_quota.py::test_tanimsiz_kota_reddetmez`. | **VAR** (belgelenmemiş) | `kota.md` §1.2 |
| **FR-072** | Sistem, kota kontrolünü dosya **diske yazılmadan önce** yapmalı; `File.before_insert` kapısını **güvenlik ağı olarak korumalıdır**. | Kontrol noktası `api/seller_media.py:281`'deki `upload_policy.check(...)` ile aynı yerde, `doc.insert()` **öncesinde**. Şema karşılığı: `enforcement.check_point` ∈ `pre_write \| doc_before_insert \| both`, varsayılan **`both`**. Bugün yalnız `doc_before_insert` (`hooks.py:231-237`) → kotayı aşan yükleme **diske yazıldıktan sonra** reddediliyor; rollback `File` kaydını geri alır ama `os.write`'ı geri almaz → **yetim dosya** (kotaya da sayılmaz, çünkü `storage_usage` `tabFile` üzerinden sayıyor). | **KISMEN** | `kota.md` §2; `quota.schema.json` `enforcement.check_point` |
| **FR-073** | Sistem, eşzamanlı yüklemede kota aşımını (TOCTOU) engellemelidir. | `storage_usage` kilitsiz bir `SELECT` (`files.py:237-245`) — `for update` yok, advisory lock yok, kontrol ile yazma arasında serileştirme yok. N eşzamanlı yükleme aynı `current_bytes`'ı okur, hepsi geçer; aşımın teorik üst sınırı `(N-1) × dosya_boyutu`. Hesap (ölçüm değil): 10 eşzamanlı **200 MB** video (`upload_policy.py:69`) → `9 × 200 = 1.800 MB` aşım; STARTER kotası 2000 MB. Şema: `enforcement.concurrency_guard.strategy` ∈ `none \| row_lock \| advisory_lock \| reservation`; **`reservation` en doğru** — baytı kontrol anında rezerve et, yazma başarılıysa kalıcılaştır, değilse TTL ile serbest bırak (bu aynı zamanda FR-072'yi de çözer). | **YOK** — `strategy: none` | `kota.md` §3 |
| **FR-074** | Sistem, kota kapsamını **açık bayraklarla** tanımlamalı; bugünkü davranışı varsayılan olarak taşımalıdır. | Şema `scope`: `count_public: true`, `count_private: **false**`, `count_trashed: **false**`, `count_archive_originals: **false**`, `count_backup: **false**`, `dedup_by: "file_url"`. Ölçülen gerçekler: private dosyalar hiç sayılmıyor (`files.py:240` `is_private=0`) → **private yükleme sınırsız**; arşiv `File` kaydı yaratmıyor (`archive.py:8-9`) → kotaya girmiyor; **çöp fiilen `true`** — `trash.py:41-45` taşıma fiziksel, `file_url` `/files/…` kalıyor → `storage_usage` filtrelerini geçmeye devam ediyor → **"Kotam doldu → sildim → hâlâ dolu."** (§8.4'te doğrulanmalı). Tekilleştirme `group by file_url` + `max(file_size)` — kod yorumundaki ölçüm: 1,49 GB yerine 1,06 GB. | **KISMEN** | `kota.md` §1.3, §4.1, §4.3 |
| **FR-075** | Sistem, kotayı **beş metrikle** ifade edebilmelidir. | (1) Toplam depolama — **VAR**; (2) aylık yükleme sayısı `uploads.per_month` — **YOK** (`grep "quota.max"` → `max_products`, `max_sub_users`, `max_co_owners`, `max_regions`, `max_orders_per_month`, `max_active_listings`, `max_storage_mb`; yükleme sayısı yok); (3) eşzamanlı iş `jobs.concurrent` — **YOK** (transcode `long` kuyruğuna gidiyor, plan bazlı sınır yok → gürültülü komşu); (4) toplam video süresi `video.total_duration_minutes` — **YOK ve ölçülmüyor** (`File` üzerinde süre alanı hiç yok; önce `th_media_duration_seconds` gerekiyor); (5) tek dosya maks boyutu — **VAR ama plan bazlı değil**. | **1/5 VAR** | `kota.md` §5 |
| **FR-076** | Sistem, tek dosya tavanını **plan zincirine** dâhil etmelidir: `min(plan, politika, frappe)`. | Bugün zincir `min(bizim, platform_limit())` (`upload_policy.py:264-265`) — plan **hiç girmiyor**. Somut tutarsızlık: FREE planın kotası 500 MB iken tek dosyada 200 MB video yüklenebiliyor → **iki dosya kotayı bitiriyor**. Platform tavanları: image 25 MB, video 200 MB, document 50 MB, other 50 MB, bilinmeyen 50 MB (`upload_policy.py:67-76`). | **YOK** | `kota.md` §5.4 |
| **FR-077** | Sistem, yeni kota metriklerini **`notify_only` ile açmalı**, ölçüm yapılmadan `block`'a geçmemelidir. | Şema her metrik için ayrı `on_exceed` ∈ `block \| queue \| notify_only`; **yeni metriklerin varsayılanı `notify_only`**. Bugün yalnız `block` var (`checks.py:278-281`). | **YOK** | `kota.md` §5.5 |
| **FR-078** | Sistem, toplu içe aktarmada kotayı **iş başlamadan önce toplu kontrol** etmelidir. | `bulk_import.precheck_total_bytes: true`; kota yetmiyorsa iş **hiç başlamaz** (`on_insufficient_quota` ∈ `reject_job \| partial_with_report \| notify_only`, varsayılan `reject_job`). Bugün bulk import kotadan **muaf** (`checks.py:249-252`, iki bayrak kanalı) — yani **en çok dosya yükleyen yolda kota yok**. | **YOK** | `kota.md` §4.2 |
| **FR-079** | Sistem, kota muafiyetlerini **açık listeyle** tutmalıdır. | Yedi erken `return` (`checks.py:238-260`): `is_folder`, System Manager, Marketplace Admin, `EXCLUDED_DOCTYPES`, **bulk import (yüksek risk)**, **private dosyalar (yüksek risk)**, mağazasız oturum. Şema `exemptions.*` bunların hepsini adlandırıyor. Test: `test_media_quota.py` bu muafiyetlerin 6'sını ayrı ayrı bağlıyor. | **VAR** — belgelendi | `kota.md` §4 |
| **FR-080** | Sistem, kota kullanımını satıcıya **göstermeli** ve eşiğe yaklaşınca uyarmalıdır. | `observability.expose_usage_to_seller: true`, `warn_threshold_percent: **80**`, `audit_quota_rejections: true`. | **KISMEN** — `get_my_usage` ucu var, %80 uyarısı yok | `quota.schema.json` `observability` |
| **FR-081** | Sistem, kota reddini **HTTP 429 ile karıştırmamalıdır**. | Kota reddi `upload_quota_exceeded` kodu + `retryable=False` (`upload_policy.py:120`) — kota dolu, tekrar denemek aynı sonucu verir. Bu bir 429 **değildir**; 429'u ayrı sınıf üretiyor (`api/rate_limit.py:24-27`) ve kota kapısı onu kullanmıyor. | **VAR** — korunacak | `kota.md` §1.4 |

### 3.H — Rate limiting

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-082** | Sistem, **medya yükleme uçlarına** rate limit uygulamalıdır. | `api/seller_media.py` içindeki 18 whitelisted uçta `@rate_limit` decorator'ı **hiç geçmiyor** (`grep -n "@rate_limit" api/seller_media.py` → 0 satır). Korumasız uçlar arasında `upload_media` (:250-251), `upload_begin` (:355-356), `upload_chunk` (:366-367), `upload_finish` (:380-381) ve **yıkıcı** `purge_media` (:160-161) var. Karşılaştırma: bir yorum göndermek dakikada 5 istekle sınırlı (`storefront_api.py:280`), **200 MB video yüklemek sınırsız**. Önerilen değerler (türetme, ölçüm değil): `upload_media` 30/60s, `upload_begin` 10/60s, `upload_chunk` 300/60s, `upload_finish` 10/60s, `purge_media` 10/300s, okuma uçları 120/60s. | **YOK** — medya: **0 satır** | `kota.md` §6.7, §7.1 |
| **FR-083** | Sistem, rate limit sayacını **tek atomik işlemle** artırmalıdır. | `INCR key` → dönen değer `1` ise `EXPIRE key window`. Bugünkü hata: `get_value` → `int` → karşılaştır → `delete_value` → `set_value` (`rate_limit.py:61-82`) — Redis `INCR` kullanılmıyor. İki sonucu var: (a) **eksik sayım** — N eşzamanlı istek aynı `current`'ı okur, sayaç 1 artar, N istek geçer; (b) `delete` ile `set` arasında kova **yok** → o aralıkta gelen istek `current=0` okur, limit tamamen atlanır. | **HATALI** | `kota.md` §6.4 |
| **FR-084** | Sistem, sabit pencereyi **her istekte sıfırlamamalıdır**. | Bugün her istek TTL'i baştan başlatıyor (`rate_limit.py:79-82` `delete + set` deseni) → sayaç ancak trafik `window_seconds` boyunca **tam durduğunda** sıfırlanıyor. Yani `max_calls=60, window=60` bir kullanıcı için "dakikada 60" değil, **"60 istek, sonra 60 saniye tam sessizlik"** demek; sürekli gezinen normal kullanıcı da duvara çarpar. Şema `rate_limit.algorithm` varsayılanı **`fixed_window_incr`** (bugünkü hatalı davranış `fixed_window_ttl_reset`). | **HATALI** | `kota.md` §6.3 |
| **FR-085** | Sistem, misafir kovasını **oturum kimliğine değil istemci parmak izine** bağlamalıdır. | Bugün `_bucket_key` = `f"rl:{name}:{user}"` ve `user = frappe.session.user if per_user else "_global"` (`rate_limit.py:30-31`, `:53`) → kimliği doğrulanmamış istekte değer `"Guest"` → **tüm anonim internet trafiği tek kovada**: `rl:<scope>:Guest`. Somut sonuç: `sf_review_page` için (`storefront_api.py:43-44`, `max_calls=60, per_user=True`) **tüm dünyaya toplam** dakikada 60 istek — tek bot o ucu bir dakika boyunca herkese kapatabilir; yani rate limiting **bir DoS aracına** dönüşüyor. En sert örnek `mobile_api.py:135` (`mobile_login`, 10/60, `per_user=False`): saldırgan dakikada 10 başarısız denemeyle **tüm mobil kullanıcıların girişini** kapatabilir (lockout-as-DoS). Şema: `guest_bucket.key_strategy` ∈ `session_user \| ip \| ip_and_ua \| forwarded_for` + `trusted_proxy_depth`. | **HATALI** | `kota.md` §6.2 |
| **FR-086** | Sistem, IP bazlı kovaya geçmeden önce **proxy zincirini doğrulamalıdır**. | `trusted_proxy_depth` varsayılanı `null` bırakıldı çünkü `docker/nginx` yapılandırması okunmadı. Yanlış konumdan `X-Forwarded-For` okumak **IP taklidine kapı açar**. Ayrıca uygulama sırası bağlayıcıdır: **FR-083/FR-084'ten sonra** — bugünkü TTL-reset hatasıyla IP bazlı kova, tek IP arkasındaki tüm kurumsal kullanıcıları kalıcı kilitleyebilir. | **YOK** | `kota.md` §6.2, §9 adım 5, §10.7 |
| **FR-087** | Sistem, 429 yanıtında **`Retry-After` başlığını kovanın kalan TTL'i** ile göndermelidir. | Yanıt sözleşmesi: `Retry-After: <kalan TTL>`, `X-RateLimit-Limit`, `X-RateLimit-Remaining: 0`, `X-RateLimit-Reset: <unix ts>`, gövdede `{"code": "rate_limited", "retry_after": <saniye>}` + Türkçe mesaj. Bugün: durum kodu **doğru** (`TooManyRequestsError.http_status_code = 429`, `rate_limit.py:24-27`) ama `Retry-After` **yok** ve mesajdaki süre **yanıltıcı** — `window_seconds` sonra tekrar denemek işe yaramaz, çünkü o deneme TTL'i yeniden sıfırlar (FR-084). | **KISMEN** (2/3) | `kota.md` §6.6, §7.3 |
| **FR-088** | Sistem, rate limit reddini **mevcut ret sözleşmesine** almalı ve `retryable=True` işaretlemelidir. | Yeni kod: `RATE_LIMITED = Kod("upload_rate_limited", True)`. Kota reddinin **tersine** (`retryable=False`), rate limit reddi geçicidir; istemci bekleyip tekrar denemelidir (`upload_policy.py:94-96` ayrımı). Bu, uygulama sırasının **1. adımı**: tek satır, hiçbir davranış değişmez, sonraki adımların sözleşmeye girmesini sağlar. | **YOK** — `TooManyRequestsError` düz bir `ValidationError` alt sınıfı | `kota.md` §7.3, §9 adım 1 |
| **FR-089** | Sistem, istek sayısının yanına **bayt kovası** (kullanıcı başına MB/dakika) uygulamalıdır. | Gerekçe: 30 × 8 MB ile 30 × 100 KB aynı sayılıyor. Plan bazlı öneriler (türetme: `min(kotanın %10-20'si, sunucu kapasitesi)`): FREE **100 MB/dk** (500 MB kotanın %20'si), STARTER **250** (%12,5), PRO/PREMIUM **500** (%10), ENTERPRISE **1000** (sınır artık kota değil sunucu kapasitesi). **"Sunucu kapasitesi" ölçülmedi** (§8.7). | **YOK** | `kota.md` §7.2 |
| **FR-090** | Sistem, rate limit arka ucu erişilemediğinde **fail-open** davranmalı ama **alarm üretmelidir**. | `rate_limit.py:57-69` Redis hatasında isteği geçiriyor — bu **korunur** (fail-closed tüm kullanıcıları kilitler). Eksik olan: `frappe.log_error` çağrısı var, bunun bir **alarma** bağlanması yok. Şema: `on_backend_failure: "fail_open"` + `alert_on_backend_failure: true`. Sessiz fail-open, korumanın kapalı olduğunu kimseye söylemez. | **KISMEN** | `kota.md` §6.5 |
| **FR-091** | Sistem, rate limit uygulamasını **tek bir mekanizmada** birleştirmelidir. | Bugün **üç** bağımsız uygulama var: proje içi decorator (`api/rate_limit.py:34`), Frappe'nin kendi limiter'ı (`api/public.py:18`), ve elle yazılmış üçüncü bir tane (`api/theme.py:94` — kendi sabitleri: `_SAVE_RATE_LIMIT_COUNT = 10`, `_SAVE_RATE_LIMIT_WINDOW_SECONDS = 60`, kendi Redis anahtar öneki). Üçü farklı anahtar şeması, farklı hata mesajı, farklı HTTP davranışı üretiyor. | **HATALI** | `kota.md` §6.1 |

### 3.I — Saklama (retention), silme ve yedek

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-092** | Sistem, silmeyi **iki adımlı** yapmalıdır: canlı dosya → çöp (bekleme penceresi) → kalıcı silme. | `delete_permanently()` **yalnız çöpteki** dosyaya uygulanabilir (`trash.py:210`); canlı bir dosyayı tek adımda silmek mümkün değildir. Kod yorumunun gerekçesi: *"tek bir yanlış tıklamanın geri dönüşü olmayan sonuç doğurmasını engelliyor"* (`trash.py:213-215`). | **VAR** — korunacak | `retention.md` §2.1 |
| **FR-093** | Sistem, silme kapılarından **dördünü `force` ile aşılamaz**, yalnız "kullanımda" kapısını aşılabilir tutmalıdır. | `_assert_trashable()` beş kapı (`trash.py:64-108`): kayıt yok → throw; **private → reddet (aşılamaz)**; **kapsam dışı doctype (`EXCLUDED_DOCTYPES`) → reddet (aşılamaz)**; **hassas içerik ikizi (`_has_sensitive_twin`) → reddet (aşılamaz)**; kullanımda → reddet (**`force` ile aşılabilir**, kullanıcıya "bu dosya {n} üründe kullanılıyor, görselleri kırılacak" uyarısı gösterildikten sonra). Gerekçe kodda yazılı: kapsam engelleri *"gizlilik kararı, kullanıcı tercihi değil"* (`trash.py:67-71`). | **VAR** — korunacak | `retention.md` §2.2 |
| **FR-094** | Sistem, "kullanılmadı" tanımını **açıkça yazılı ve sürümlü** tutmalıdır. | Dört karar etiketi (`usage.py:61`): `in_use` (çöpe atılamaz, yalnız `force`), `order_only` (**atılamaz** — sipariş kaynakları "geçmiş siparişin delili"), `history_only` (atılabilir), `unused` (atılabilir). `TRASHABLE_VERDICTS = {"unused", "history_only"}` (`trash.py:34`). Taranan kaynak: **16 (tablo, kolon) çifti** — 8 CANLI + 2 SİPARİŞ + 6 GEÇMİŞ (`usage.py:32-59`, sayım elle yapıldı). Derin tarama **zorunlu** (`deep_scan_required: true`, `trash.py:101`). | **VAR** — korunacak | `retention.md` §3 |
| **FR-095** | Sistem, "görsel URL'i geçen alan" sayısındaki **belgeleme tutarsızlığını** gidermelidir. | Üç ayrı yerde üç farklı sayı yazılı: `usage.py:7-8` "**23** alan", `archive.py:5` "**22** alan", kodda sınıflanmış çift sayısı **16**. Hangisinin doğru olduğu `information_schema` taraması gerektiriyor (§8.9). | **HATALI** (belge) | `retention.md` §3.2 notu |
| **FR-096** | Sistem, `LIVE_SOURCES` listesini **tamamlamalıdır**; listede olmayan bir alan silme taramasında "kullanılmıyor" görünür. | 41 alanın yalnız **8'i** kayıtlı (`usage.py:32-41`). Eksik ve **silme adayı görünen** alanlar arasında: `Admin Seller Profile.banner_image`, `Seller Gallery Image.poster_image`, `Listing Variant Item.variant_video_url`, `Brand.logo`, `Brand.hero_banner`, `Brand.video_url`, `Product Category.image`, `Seller Category.image`, `Category Showcase Tile.image`, `Hero Slide.background_image`, `Logistics Provider.logo`, `Shipping Channel.icon`, `Verification Source.icon`, `Static Page SEO.og_image`, `Seller Product.image` + `RichTextEditor` ile içeriğe gömülen görseller. Bu, `brand.logo` politikasının **uygulanmadan önce** kapatılması gereken ön koşuludur. | **YOK** | B6; `brand-logo.json` `open_questions` |
| **FR-097** | Sistem, bir dosyanın **son referansı kalktıktan sonra** silme adayı olması için bir bekleme (grace) süresi uygulamalıdır. | `unused_definition.grace_days_after_last_reference`, varsayılan `0`. Bugün referans kalkar kalkmaz dosya silme adayı oluyor. | **YOK** | `retention.md` §3.4 |
| **FR-098** | Sistem, "frontend'de sabit yazılmış görsel" boşluğunu **makinece okunabilir** biçimde işaretlemelidir. | `unused_definition.frontend_scan_completed`, varsayılan **`false`**. `true` yapılmadıkça otomatik silme politikası `action: "delete"` ile **çalıştırılmamalıdır**. Boşluğun kaynağı kodda yazılı: *"'kullanılmıyor' taraması yalnız veritabanını kapsıyor. Frontend kodunda sabit yazılmış … bir görsel taramada 'kullanılmıyor' görünür ama sitede kırılır"* (`trash.py:10-13`). 30 günlük çöp penceresi **tam olarak bu hatayı geri alınabilir kılmak için** var. | **YOK** | `retention.md` §3.3, §3.4 |
| **FR-099** | Sistem, saklama sürelerini **konfigüre edilebilir** yapmalıdır. | Dört pencerenin dördü de Python sabiti: `TRASH_RETENTION_DAYS = 30` (`trash.py:31`), `ARCHIVE_RETENTION_DAYS = 30` (`presets.py:38`), `KEEP_SETS = 14` (`backup.py:385`), `KEEP_HOURS = 48` (`backup_export.py:45`). Hiçbirinde `frappe.db.get_single_value` / `frappe.conf` okuması yok → değiştirmek kod düzenlemesi + deploy + (imaj tabanlı kurulumda) imaj rebuild gerektiriyor. **İyi haber:** fonksiyon imzaları hazır — `trash.purge_expired(retention_days=…)` (`trash.py:268-270`) ve `archive.purge_expired(retention_days=…)` (`archive.py:113-115`) parametre kabul ediyor; sabit yalnız **varsayılan değer**. Şema `configurability.source` ∈ `python_constant \| site_config \| doctype_single \| policy_file`, bugünkü değer `python_constant`. Ayrıca `change_requires_audit: true` ve `shorten_requires_confirmation: true`. | **YOK** | `retention.md` §5.1, §7 |
| **FR-100** | Sistem, **`legal_hold`** işaretli varlığı hiçbir politikayla silmemelidir. | Repo tarandı: `grep -rniI "legal_hold\|legalhold\|litigation\|yasal saklama"` → `tradehub_core/` altında **0 eşleşme**. `File` üzerindeki 12 custom alanın hiçbiri bu değil (`th_optimized_at`, `th_original_size`, `th_trashed_at`, `th_media_state`, `th_media_title`, `th_media_alt`, `th_media_description`, `th_media_tags`, `th_media_favorite`, `th_media_width`, `th_media_height`, `th_media_video_status`). Şema: `legal_hold.overrides_all_policies` bir **`const: true`** — şemaya uyan hiçbir konfigürasyon bunu kapatamaz; `field: "th_legal_hold"`; `applies_to: ["original","derivative","trash","archive","backup"]` (**çöpteki** dosya da korunur); `audit_action: "media.legal_hold_block"`; `release_requires_reason: true`. Uygulama: `_assert_trashable`'a **altıncı kapı**, `force` ile **aşılamaz** grupta. **Uygulama maliyeti görünür kılındı:** `purge_expired` (`trash.py:293`) bugün diskte dolaşıp mtime'a bakıyor, hiçbir `File` alanı okumuyor → legal hold eklendiğinde toplu ön-yükleme (`frappe.get_all`) gerekir, aksi hâlde döngüye N sorgu eklenir. | **YOK** | `retention.md` §5.2, §6.3, §8 |
| **FR-101** | Sistem, her silme olayını **denetime yazmalı**; hiçbir şey silinmediğinde de kayıt atmalıdır. | Altı audit action: `media.trash` (+`bytes`, `forced` bayrağı), `media.untrash`, `media.delete` (silinen `File` adları + temizlenen referanslar), `media.purge_trash` (+`trigger`, `retention_days`, ilk 50 dosya adı), `media.purge_archive`, `media.scope_denied`. **`trigger` alanı ayrımı zorunlu:** `scheduled` (günlük job, yalnız süresi dolanlar) ile `manual` ("Çöpü boşalt" → çöpün TAMAMI hemen) — kod yorumu: *"'çöp temizliği' ifadesi bakım işi gibi okunuyordu"*. **Hiçbir şey silinmediyse de kayıt atılır** (`trash.py:319-320`): *"'purge çalıştı mı' sorusu denetimden cevaplanabilmeli."* | **VAR** — korunacak | `retention.md` §2.3 |
| **FR-102** | Sistem, dosya silinince referans zincirini **üç farklı davranışla** temizlemelidir. | `refs.clear(url)` (`refs.py:147`): **satır silinir** — `ROW_OWNED_TABLES` (`tabListing Image`, `tabListing Variant Item`, `tabSeller Gallery Image`; gerekçe: *"görsel gidince satırın varlık sebebi kalmıyor"*); **alan boşaltılır** — diğerleri (ör. `Listing.primary_image`); **hiç dokunulmaz** — `READONLY_TABLES` (`tabCart Item`, `tabOrder`; gerekçe: *"Referansı silmek geçmişi değiştirmek olur — yalnız raporlanır"*). | **VAR** — korunacak | `retention.md` §2.4 |
| **FR-103** | Sistem, orijinal dosyayı **varsayılan olarak süresiz** saklamalıdır. | `original_retention.keep_forever: true`, `local_days: null`. Şema `if/then/else` ile zorluyor: `keep_forever: false` ise `local_days` (integer ≥ 1) **ve** `then` **zorunlu** alan olur → "süresiz saklamayı kapattım ama ne yapılacağını yazmadım" durumu şema düzeyinde imkânsız. Bugünkü fiilî davranışla uyumlu: canlı dosyayı silen tek yol `trash.purge_expired` ve o da **yalnız daha önce elle çöpe taşınmış** dosyalara dokunuyor (`trash.py:281-293`). | **VAR** (fiilen) | `retention.md` §6.1 |
| **FR-104** | Sistem, türev saklama politikasını **bugün boş kümeye** uygulandığını açıkça işaretlemelidir. | `derivative_retention.pipeline_status` ∈ `absent \| in_place_overwrite \| separate_artifacts`, **bugünkü doğru değer `absent`**. Gerekçe: bu kod tabanı türev üretmiyor; hem görsel hem video yolu **dosyanın üstüne yazıyor** (`archive.py:4-6`, `transcode.py:26-29`); `thumbnail_url` repoda **hiç geçmiyor**. Varsayılanlar: `unused_after_days: 90` (**kaynağı görev tanımı, ölçüm değil** — `x-provenance` ile işaretli; kod tabanında 90 günlük medya penceresi yok, `audit/tasks.py:32` `_HOT_DAYS_DECISION = 90` audit satırları içindir), `action: "notify_only"`, `regenerate_on_demand: true`, `always_keep_profiles: []`. `regenerate_on_demand: false` + `action: "delete"` kombinasyonu **veri kaybı** demektir ve şema onu `x-requires-review` ile işaretler. | **YOK** (bilinçli) | `retention.md` §5.4, §6.2 |
| **FR-105** | Sistem, uygulanmamış bir depolama hedefi seçildiğinde politikayı **reddetmelidir**. | Her `then` seçeneğinin yanında `implementation_status` ∈ `implemented \| not_implemented`; `s3_standard` ve `s3_cold` için varsayılan **`not_implemented`**. Bir politika `not_implemented` bir hedef seçerse yükleyici **reddeder** — sessizce `delete`'e düşmek **en tehlikeli davranış** olurdu. | **YOK** | `retention.md` §5.3 |
| **FR-106** | Sistem, yedek alma ile temizlik sırasını **korumalı**: ÖNCE yedek, SONRA eskileri temizle. | `backup.run_scheduled` (`backup.py:390-397`): yedek alınamazsa `prune` **hiç çalışmaz** (`raise`). Şema `on_backup_failure: "skip_purge"` bunu varsayılan olarak koruyor. `backup_export.cleanup()` aynı fonksiyona bağlı ve hatası **yutuluyor** (*"Paket temizliği yedeği düşürmemeli"*) → `export_cleanup_failure_is_fatal: false`. | **VAR** — korunacak | `retention.md` §4.4 |
| **FR-107** | Sistem, disk ile veritabanı arasındaki **yetim/kırık kayıtları** düzenli olarak uzlaştırmalıdır. | `orphan_reconciliation`: `enabled: false` (bugün), `schedule: "weekly_long"`, `directions: ["db_without_disk", "disk_without_db", "dangling_references"]`, `auto_repair: false`. Bugün `refs.find_dangling()` (`refs.py:19`) **yarısını** yapıyor ama `hooks.py:92-219` scheduler bloklarında çağrısı **yok**. Kısmi başarısızlık penceresi ölçüldü: `move_to_trash` DB+disk'i tek `try` içinde sarıp hatada rollback yapıyor (`trash.py:153-168`), ama `purge_expired` (`trash.py:293-316`) ve `delete_permanently` (`trash.py:229-232`) için aynı garanti **yok** — `except Exception: … continue` ile döngü devam ettiği için **kısmi durum sessizce kalıcı** olabiliyor. | **KISMEN** | `retention.md` §5.5, §6.4 |
| **FR-108** | Sistem, günlük saklama görevlerini **çalıştırmalı** ve çalıştığını denetimden kanıtlanabilir kılmalıdır. | `hooks.py:127-138` üç medya görevi tanımlıyor: `archive.purge_expired` (:131), `trash.purge_expired` (:133), `backup.run_scheduled` (:138). **Tanımlı olmak koşmak değildir** — `Scheduled Job Log`'da günde birer `Complete` satırı beklenir (§8.10). Hiç satır yoksa çöp **hiç boşalmıyor** demektir. | **KISMEN** | `retention.md` §4.1, §9.1 |

### 3.J — Erişim, izolasyon ve güvenlik

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-109** | Sistem, PII kapsamındaki doctype'lara bağlı dosyanın **public yapılmasını reddetmelidir**. | `EXCLUDED_DOCTYPES` 8 doctype (`presets.py:44-53`): KYB Verification, KYC Verification, Seller Certification, Seller Verification, Seller Application, Order, Payment Transaction, Data Export Request. Test: `test_media_access_level.py::test_kyb_belgesi_public_yapilamaz`, `::test_kyb_belgesi_private_yapilabilir`, `::test_attached_to_doctype_bos_ama_seller_application_referansli_dosya_public_yapilamaz`. **İki bağımsız tespit yolu şart**: `attached_to_doctype` kontrolü + **ters referans** taraması (`EXCLUDED_MEDIA_FIELDS`) — çünkü canlı DB'de `Seller Application.identity_document` **144 dosya** ve `Seller Certification.document` **2 dosya** `attached_to_doctype` **BOŞ** (bu iki sayı `presets.py:56-64` yorumundan **alıntıdır**, bu çalışmada ölçülmedi). | **VAR** — korunacak (15 test) | `04-yetki-modeli.md` §6; `test_media_access_level.py` |
| **FR-110** | Sistem, KVKK muafiyet haritasını (`EXCLUDED_MEDIA_FIELDS`) **tamamlamalıdır**. | `presets.py:70-76` KYB'nin yalnız **2** alanını sayıyor (`identity_document`, `bank_account_document`); `imza_sirkuleri`, `ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` **yok**. Ayrıca `Shipment Document.file` ve `Data Processing Agreement.document` `EXCLUDED_DOCTYPES`'ta **hiç yok** → görsel olarak taranmışlarsa **küçültülüyorlar** (FR-111). Kodun kendi bakım notu bu riski **zaten yazmış** (`presets.py:66-69`). | **YOK** | B5; E5; `document-attachment.md` §2, §3.4 |
| **FR-111** | Sistem, belge doctype'larını optimizasyon hattından **muaf tutmalı**; hassas belgeyi küçültmemelidir. | Ölçülen tuzak: `presets.py:15` `balanced.max_dim = 2000` + `engine.py:117` `im.thumbnail((max_dim, max_dim))` → `2000 px / 11,693 inç = **171 dpi**`. Yani 300 dpi'lik bir A4 taraması optimizasyon hattına girerse 171 dpi'ye düşer. Tuzak 8 doctype için `EXCLUDED_DOCTYPES` sayesinde kapalı, **2 doctype açıkta**. PDF muafiyeti ayrıdır: `engine.py:98-100` `fmt not in SUPPORTED_FORMATS` → PDF hiç işlenmez; tuzak yalnız **görsel olarak** (jpg/png/webp) taranmış belgeler için geçerlidir. | **KISMEN** (8/10) | E4; `document-attachment.md` §3.3, §7.1 |
| **FR-112** | Sistem, private dosya için **imzalı süreli URL** üretebilmeli; yetkisiz kullanıcı için **imza üretmemelidir**. | Sıra (`media_access.py:102-141`): Guest → `PermissionError`; `_require_private_path` (path traversal `..` + public yol reddi); `file_doc.has_permission("read")` yoksa `media.access_denied` (`reason="signed_url_denied"`) + `PermissionError`; `_clamp_ttl`; `get_signed_params({"file", "exp"})`. Kripto **kendimiz yazılmadı** — Frappe `verified_command` (site secret ile HMAC-SHA512). **İmza yetkiyi yaratmaz, imza anındaki yetkiyi taşır.** Public dosya **imzalanamaz**. Test: `test_media_access.py` (17 test). | **VAR** — korunacak | `04-yetki-modeli.md` §7.1, §7.2 |
| **FR-113** | Sistem, imzalı URL TTL'ini **clamp** etmelidir. | Varsayılan **900 sn** (15 dk), alt sınır **60 sn**, üst sınır **86.400 sn** (24 saat) (`media_access.py:48-50`). `_clamp_ttl` sessizce clamp'ler; parse edilemeyen değer varsayılana düşer. Gerekçe: üst sınır olmadan link isteyen taraf pratikte **sınırsız süreli bir kapı** açabilir. Test: `::test_ttl_ust_sinira_clamp_edilir`. **Kabul edilmiş sınır:** iptal (revocation) **yok** — imza üretildikten sonra kullanıcının yetkisi alınsa bile link TTL boyunca çalışır; tek fren 24 saatlik üst sınır. | **VAR** — korunacak | `04-yetki-modeli.md` §7.3, §7.5, §8-C |
| **FR-114** | Sistem, imzalı indirme ucundaki **her ret dalını denetime yazmalıdır**. | Altı doğrulama ve ret nedeni (`media_access.py:144-202`): `verify_request()` → `invalid_signature`; `_require_private_path` → `bad_path`; `int(exp)` → `malformed_exp`; `exp <= now` → `expired`; `check_path_safety` (2. katman) → `bad_path`; `send_private_file`. Gerekçe: guest'e açık bir uçta imzasız/süresi geçmiş/bozuk link denemeleri (brute-force, probe) aksi hâlde **hiç iz bırakmadan** geçerdi. `download_private_file` **bilinçli olarak kullanılmıyor** (Guest'e Forbidden döndürüyor). `claimed_file` yalnız **kayıt amaçlı** okunur; serve kararı asla o ham değere dayanmaz. Test: 4 ayrı ret-audit testi. | **VAR** — korunacak | `04-yetki-modeli.md` §7.4 |
| **FR-115** | Sistem, satıcı izolasyonunu **beş katmanda** uygulamalı ve başka mağazanın dosyasının **varlığını bile** ifşa etmemelidir. | Katman A: mağaza dışarıdan alınmaz, **oturumdan çözülür** (`ownership.store_of()`); `api/seller_media.py` içindeki **21 whitelisted ucun tamamı** `_store()` çağırır. Katman B: tek dosya işlemlerinde `assert_owns` → sahibi olmadığı dosyada **"Dosya bulunamadı"** döner (kod yorumu: *"sahibi olmadığı bir adresin varlığını doğrulamak keşif …"*). Katman C: toplu işlemlerde **sessiz atlama, ifşasız**. Katman D: liste sorgularında **SQL seviyesinde daraltma**. Katman E: parçalı yükleme oturumları kapsamlı. `purge` dönüşündeki `remaining_owners` bir **sayı**, kimlik değil. | **VAR** — korunacak | `04-yetki-modeli.md` §3 |
| **FR-116** | Sistem, erişim seviyesi değişikliğini **atomik** yapmalı ve denetime yazmalıdır. | Taşıma (`private/files/<ab>/` ↔ `public/files/<ab>/`, shard korunur) + referans güncelleme (`_WRITABLE` allow-list) + `File.is_private` **tek transaction**. Audit: `media.level_changed` (kim, dosya, eski→yeni seviye, zaman). Denetim kaydında **maskeleme** uygulanır: ham URL context'e yazılmaz (`::test_gecis_hassas_isaretlenir_ve_ham_url_context_e_yazilmaz`, `::test_gercek_adl_kaydinda_object_name_maskeli`). | **VAR** — korunacak | `MEDYA-ERISIM-MODELI.md` §4.2; `04-yetki-modeli.md` §6.6 |
| **FR-117** | Sistem, dosyanın gizli/açık olmasını **slot politikasından** almalıdır; hangi ekrandan yüklendiğine bağlı bırakmamalıdır. | Bugünkü tutarsızlık (B8): panel jenerik yükleyicisi her dosyayı `is_private=1` yapıyor (`DocTypeFormView.vue:2306`); storefront yorum görselleri `is_private=0` (`WriteReviewModal.ts:145`); `StorefrontEdit.uploadFile` `is_private=0` (`StorefrontEdit.vue:968`); RFQ `is_private=1` (`rfq/uploader.ts:36`). Politika karşılıkları: `company.cover_image` → `is_private=1` **reject** (`gizli_yuklendi`); `document.attachment` → `is_private=0` **reject** (`gizli_olmali`); `product.video` → `is_private=1` **warn**. | **YOK** | B8; ilgili politika `content_rules` |
| **FR-118** | Sistem, private video normalize edilmediğinde kullanıcıya **bir şey söylemelidir**. | `transcode.py:194` `is_private` ise **sessizce** `return` ediyor; kullanıcıya hiçbir şey söylenmiyor. Aynısı `transcode.py:201-204` (satıcı değil / Listing'e bağlı değil) için. Kabul: `private_transcode_atlandi` / `kapsam_disi_transcode_yok` mesajları gösterilir. | **YOK** | E7; `product-video.md` §6 |
| **FR-119** | Sistem, SVG kabulünü **on maddenin tamamı** karşılanmadan açmamalıdır. | SVG-1: iki kapı **birlikte**, yalnız `slot_key ∈ {seller.logo, brand.logo}` için (global açılış yasak) → **slot kayıt defteri (FR-001/FR-002) önkoşul**. SVG-2: sanitize **sunucuda**, `File` kaydı yazılmadan önce; kaydedilen **sanitize edilmiş** sürümdür. SVG-3: `is_dangerous()` baypası yalnız "sanitize edildi" **bayrağına** bağlı (uzantıya veya slot adına değil). SVG-4: **izin listesi** (yasak liste değil) — 19 element, 40 attribute; `script`, `foreignObject`, `image`, `style`, `animate*`, `filter`/`fe*`, tüm `on*` silinir; `href`/`xlink:href` yalnız `#` ile başlıyorsa korunur. SVG-5: `<!DOCTYPE`/`<!ENTITY` → **sanitize edilmez, reddedilir** (billion laughs sanitize'den önce bellek tüketir); parser **`defusedxml`**. SVG-6: `.svgz` **yasak kalır**. SVG-7: her zaman `<img src>`, **asla inline** (ne `innerHTML`, ne `x-html`, ne `v-html`). SVG-8: `Content-Type: image/svg+xml` + `X-Content-Type-Options: nosniff` + `CSP: default-src 'none'; style-src 'unsafe-inline'; sandbox`. SVG-9: bayt **32.768 B**, düğüm **256**, `viewBox` **zorunlu**. SVG-10: `data:` URI yasağı (FR-013). | **VAR** (reddediyor) — açılış koşulları YOK | `logo.md` §6 |
| **FR-120** | Sistem, SVG bayt tavanını **birincil**, düğüm tavanını **ikincil** savunma olarak uygulamalıdır. | Ölçüm bunu kanıtlıyor: `svgviewer-output.svg` **yalnız 75 düğüm** ama **137.695 bayt** — tüm ağırlık `path` `d` verisinde; düğüm sayısına bakan bir kural bu dosyayı **geçirirdi**. Referans ölçümler (`stat -f %z` + regex düğüm sayımı): `amex.svg` 4.879 B / 2 düğüm, `vite.svg` 1.497 B / 11, `ta-logo.svg` **12.379 B / 20** (gerçek kelime markası), `ta-shield-pattern.svg` 105.516 B, `ui.svg` 463 düğüm (sprite). Tavan 32 KiB = `ta-logo.svg`'nin **2,65 katı**; 256 düğüm = **12,8 katı**. | **YOK** | `logo.md` §6.2 SVG-9 |

### 3.K — Render, responsive servis ve erişilebilirlik

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-121** | Sistem, görseli `srcset`/`sizes`/`<picture>` ile **cihaza uygun boyda** servis etmelidir. | Bugün storefront'ta `srcset` kullanımı **0** (`grep -rni "srcset" src \| wc -l` → 0), `<picture>` **0**. `<picture>` içindeki `<source>` sırası `profiles[].formats` dizisinin sırasıdır: **en modern önce** (`["avif","webp"]`). Galeri görselinin **tek giriş noktası** `renderGalleryMedia` (`ProductImageGallery.ts:54-77`) — `srcset` **oraya** eklenir. **Sıra bağlayıcıdır:** türev merdiveni (FR-035) bitmeden `srcset` yazmanın gösterecek ikinci dosyası yoktur. | **YOK** | `03-render-envanteri.md` §4, §0-1; `logo.md` §5 |
| **FR-122** | Sistem, `srcset` yazmadan önce URL yeniden yazıcısının **`srcset` attribute'unu izlediğini** garanti etmelidir. | `tradehubfront/src/utils/mediaUrl.ts:76` `MutationObserver` `attributeFilter` = `["src","style"]` — **`srcset` yok**. Bugün `srcset` eklenirse GitHub Pages önizlemesinde görseller **kırılır**. Bu, FR-121'in kod düzeyindeki önkoşuludur. | **YOK** | `03-render-envanteri.md` §6.1 |
| **FR-123** | Sistem, bugünkü aşırı-servis oranını **azaltmalıdır**. | Hesap (bayt değil, **piksel katı**): sepet SKU satırı 40 px @2x = 80 px talep, indirilen 1920 px → `(1920/80)² = **576×**`; kart ızgarası 360 px telefon (156 px @2x = 312) → **≈38×**; kart ızgarası masaüstü (343 @2x = 685) → **≈7,9×**; PD mobil 430 px @3x (1290) → **≈2,2×**; masaüstü hover-zoom @2x (1858) → **≈1,07×**. **Bu tablo bayt tasarrufu DEĞİLDİR** — bayt piksel sayısıyla doğrusal artmaz; gerçek bayt kazancı **ölçülmedi** (§8.8). Tablonun söylediği tek şey: kapasite talebi 80 px ile 1908 px arasında **24 kat** değişiyor ve bugün **tek dosyayla** karşılanıyor. | **YOK** | `product-image.md` §1.3 |
| **FR-124** | Sistem, CLS'i önlemek için her görsel kutusunda oran veya sabit ölçü rezerve etmelidir. | Ürün render noktalarının tamamında `aspect-square` kapsayıcı + `width`/`height` attribute → `03-render-envanteri.md` §5'te R1–R15, R17, R18, R20 **"risk yok"**. `category.banner` da korumalı: `width/height` attr `400×400` + sabit `auto-rows` (R12 "risk YOK"). **Bilinen ihlal (Ç6):** kapak videosu skeleton'ı `lg:w-[500px] h-[300px]` (5:3), gerçek kutu `aspect-video` (16:9 → 281,25 px) → yükleme bitince **18,75 px** dikey kayma. **İkinci ihlal:** `SettingsLayout.ts:99` `width="64" height="64"` yazıyor, kutu `size-[72px]` (`:98`) — CLS riski yok (kap sabit px) ama attribute **yanlış**. | **KISMEN** | `03-render-envanteri.md` §5; Ç6; `user-avatar.md` §2 |
| **FR-125** | Sistem, konuşma içeren kapak videosunda **VTT altyazıyı zorunlu** tutmalıdır. | Bugün her iki frontend'de `<track` / `kind="captions"` / `.vtt` → **0 eşleşme**. Kurallar: `story` + ses akışı + **konuşma** → `.vtt` **ZORUNLU**, eksikse yayına alınmaz (`cover_video_captions_required`); `story` + yalnız müzik/ortam sesi → `.vtt` zorunlu değil, `Seller Gallery Image.caption` **zorunlu**; ses akışı yok → `caption` zorunlu; `ambient` → `caption` zorunlu. Uygulama gereksinimleri: `subtitles_vtt` (Attach) alanı; `.vtt` uzantısı `upload_policy.EXTENSIONS` içinde **yok** → yeni `KIND_CAPTION`, tavan **512 KB**; oynatıcıya `<track kind="captions" srclang="tr" label="Türkçe" default>` + aç/kapat düğmesi. **Videoya gömülü altyazı yasak** — `<track>` altyazısıyla üst üste biner. | **YOK** | `company-cover-video.md` §8.1 |
| **FR-126** | Sistem, `prefers-reduced-motion` altında **otomatik** hareketi iptal etmeli, kullanıcının kendi başlattığı oynatmayı kısıtlamamalıdır. | `story` → **değişmez** (WCAG 2.2 SC 2.2.2 yalnız otomatik hareketi hedefler). `ambient` → **otomatik oynatma İPTAL**, poster + oynat düğmesi gösterilir. Önizleme klibi (hover) → **oynatılmaz**, poster gösterilir. **CSS bunu yapamaz:** `style.css:757-765` global kuralı `animation-duration`/`transition-duration` değerlerini `0.01ms`'ye çeker ama `<video>` oynatmasına **etkisi yoktur** → kontrol JS'te olmalı ve `matchMedia` sonucu **oynatma anında** okunmalıdır (init'te önbelleğe alınmamalı; kullanıcı OS ayarını sekme açıkken değiştirebilir). | **YOK** | `company-cover-video.md` §8.2 |
| **FR-127** | Sistem, otomatik oynatmada `muted` + `playsinline` özniteliklerini **istisnasız** uygulamalıdır. | Bugün kapak videosunda `autoplay` **yok** (`StoreHeader.ts:301-309`) — bu davranış **korunur** ("çalışanı bozma"). Otomatik oynatma açılırsa ikisi zorunludur. **Bilinen ihlal (Ç9):** ürün videosu modalinde `controls autoplay` var, `muted` **yok** (`CompanyProfile.ts:1002`) → tarayıcı otomatik oynatmayı bloklar, kullanıcı boş oynatıcı görür. `ambient` modda ses akışı **tamamen çıkarılır** (`-an`). | **KISMEN** | `company-cover-video.md` §6.6, Ç9 |
| **FR-128** | Sistem, video kontrollerini **klavyeyle kullanılabilir** ve **çevrilebilir** kılmalıdır. | Bugünkü boşluklar: seek çubuğu `<div>` + `@click`, `role`/`tabindex` yok (`StoreHeader.ts:339`) → klavye kullanıcısı konum değiştiremiyor; gerekli: `role="slider"` + `aria-valuenow/min/max` + `@keydown.arrow-left/right`. Oynat/duraklat `aria-label="Oynat"` **sabit** (`:332`) → ekran okuyucu duraklat durumunda da "Oynat" duyurur. Üç etiket (`"Oynat"`, `"Sesi aç/kapat"`, `"Tam ekran"` — `:332,347,352`) **düz Türkçe string**, dosyanın geri kalanı `t(...)` kullanıyor → 4 dilde çevrilmiyor. iOS'ta tam ekran **çalışmıyor**: yalnız `v.requestFullscreen` kontrol ediliyor (`:274-277`), iOS Safari `webkitEnterFullscreen()` ister → düğme sessizce hiçbir şey yapmıyor. | **YOK** | `company-cover-video.md` §8.3 |
| **FR-129** | Sistem, ses seviyesini **normalize etmeli** ve ses bitrate'ini **sabitlemelidir**. | Opus **96k stereo** (720p) / **64k mono** (`-ac 1`, 480p); EBU R128 `loudnorm=I=-16:TP=-1:LRA=11`. Bugün `-c:a libopus` **bitrate belirtmeden** yazılı (`transcode.py:246`) → kodlayıcı varsayılanına bağlı; **ffmpeg sürümü değişince çıktı sessizce değişir** (Ç10). | **YOK** | `company-cover-video.md` §6.6, Ç10 |
| **FR-130** | Sistem, progressive video teslimi için **anahtar kare aralığını** ve **WebM cue yerleşimini** sabitlemelidir. | Anahtar kare **2 s** (`-g 60` @ 30 fps) — el yapımı seek çubuğu (`StoreHeader.ts:261-266`) rastgele noktaya atlıyor; 2 s'den seyrek anahtar kare seek'i gözle görülür geciktirir. WebM index **başta** olmalı: `-cues_to_front 1`; aksi hâlde `preload="metadata"` ve seek için tarayıcı dosyanın **sonuna** range isteği atar → mobilde ek RTT (Ç11). `preload` **`metadata`** kalır (`auto` **yasak** — pasif bütçeyi tek başına aşar); Save-Data / `2g` altında **`none`**. | **YOK** | `company-cover-video.md` §6.4, §6.7, Ç11 |
| **FR-131** | Sistem, "çözülmüş" bir sorunu **yeniden kural yapmamalıdır**. | Somut örnek: `category.banner` slotunda "görselin alt %30'una önemli şey koyma" kuralı **yazılmamalıdır** — `CategoryShowcase.ts:154` gradient scrim'i (`bg-gradient-to-t from-black/75 via-black/25 to-transparent`) etiketi her görselde okunur kılıyor. Politikadaki karşılığı: `bottom_third_text_overlap` kuralı aksiyon **`ignore`** (ölç, sakla, sus). | **VAR** — korunacak | `category-banner.md` §6, §7 |
| **FR-132** | Sistem, ölü render bileşenlerine göre standart yazmamalıdır. | Mount edilmediği `grep` ile doğrulanmış **dört** bileşen: `components/seller/HeroBanner.ts`, `components/seller/CompanyInfo.ts`, `components/seller/CategoryProductListing.ts`, `components/product/ProductVideoSection.ts` — dördü de barrel'da dışa aktarılıyor, hiçbiri mount edilmiyor. Kabul: yeni bir profil/oran kuralı eklenirken bileşenin mount edildiği `grep` ile doğrulanır. | **VAR** (E8 olarak kayıtlı) | E8; `product-video.md` §2; `category-banner.md` §1 |

### 3.L — Gözlemlenebilirlik, ölçüm altyapısı ve migration

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-133** | Sistem, video için **ölçü ve süre metadatasını** veritabanına yazmalıdır. | Bugün `ensure_dimensions()` (`metadata.py:159-196`) boyutu `engine.probe()` ile okuyor; `probe` yalnız **PIL** kullanıyor (`engine.py:79-93`) → PIL video açmaz → `readable=False` → `{}` döner. Sonuç: **hiçbir videonun genişlik/yükseklik/süresi veritabanında tutulmuyor**; `th_media_width`/`th_media_height` video satırlarında **boş**; süre için ayrılmış alan **hiç yok**. Bu, süre/oran/çözünürlük kuralının **bugün zorlanamamasının teknik nedenidir** (Ç5). Kabul: `th_media_duration_ms` (veya `_seconds`) alanı + video için `ffprobe` tabanlı `ensure_dimensions` dalı. `ffprobe` zaten çağrılıyor (`transcode.py:83-90`) ve genişlik/bitrate okuyor; süreyi de okuyabilir ama **saklamıyor**. Bu FR, FR-075 metrik 4'ün ve FR-134'ün önkoşuludur. | **YOK** | Ç5; `company-cover-video.md` §5.4; `kota.md` §5.3 |
| **FR-134** | Sistem, süre kuralını **ölçülebilir** hâle geldikten sonra uygulamalıdır. | `product.video`: 10 MB tavanı + 2,5 Mbps eşiği zımni bir süre sınırı üretiyor — `10 · 1024 · 1024 · 8 / 2.500.000 = **33,5 saniye**`; standart bunu `warn` olarak kaydeder, **reddetmez**. `company.cover_video`: `story` **6–60 s**, `ambient` **3–8 s**. 60 s türetmesi: `60 s × 1,6 Mbps = 96 Mbit = 12 MB` teslim kapısı. | **YOK** | `product-video.md` §3; `company-cover-video.md` §6.2 |
| **FR-135** | Sistem, her içerik kuralı için **dört metrik** toplamalıdır. | `trigger_count`, `trigger_rate` (tetiklenen/değerlendirilen), `manual_override_count` (moderatör kararı otomatikten farklı), `appeal_count`, `appeal_success_rate`. **Üretimde yanlış pozitifin tek gerçek ölçüsü `appeal_success_rate`'tir** — etiketli korpus üretimde yok. Bu oran **%5'i aşan kural kalibrasyona geri döner**. | **YOK** | `icerik-kurallari.md` §6; `content_rules.json` `observability` |
| **FR-136** | Sistem, moderasyon logunda **kaynak referansını** taşımalıdır. | `Image Moderation Log` doctype'ında yalnız `review` (Link → Listing Review) alanı var; ürün görselleri için genel bir kaynak referansı (`source_doctype` + `source_name`) **yok**. FR-052 (kapsam genişletme) bu alan olmadan loglanamaz. | **YOK** | `icerik-kurallari.md` §6 |
| **FR-137** | Sistem, migration (geriye dönük standartlaştırma) işini **canlı yükleme kuyruğundan ayrı ve düşük öncelikli** çalıştırmalıdır. | Bugün backfill ile canlı yükleme **aynı kuyrukta**. Kabul: ayrı, düşük öncelikli kuyruk; canlı yüklemenin gecikmesi backfill'den etkilenmez. Kuyruk kapasitesi ölçülmedi (§8.7). | **YOK** | `docs/plans/migration.md` §5.1, §5.2 |
| **FR-138** | Sistem, `require.*` kurallarını **geçmişe dönük uygulamamalıdır** (grandfathering) ve eşiği ölçmeden zorlamamalıdır. | Karar eşiği yazılı: `kisa_kenar_RET + oran_RET` toplamı `toplam`ın **%10'unu** aşıyorsa politika yalnız **yeni** yüklemelere uygulanır, mevcutlara uygulanmaz ve bir düzeltme kampanyası gerekir. Logo için ayrı eşik: ihlal oranı **%5**'i geçerse sert ret **uyarı** moduna alınır. `max_count=12` de geçmişe dönük uygulanamaz — 12'nin üstünde galerisi olan ilan **kaydedilemez hâle gelir**. **REV2 — TETİK ÖLÇÜLDÜ VE AŞILDI:** `product.image` yerel 2.393 dosyada `kisa_kenar_RET` = **566 (%23,7)**, `oran_RET` = **564 (%23,6)**; toplam **%10 eşiğinin iki katından fazla** → grandfathering **artık opsiyonel değil, zorunludur**. Logo eşiği (%5) de aşıldı: `seller.logo` v2 uyumsuzluğu **%31,6**, ölçülen 17 dosyada `require` ihlali **4 (%23,5)**, `min_short_edge<256` **1 (%5,9)** → logo `require` aksiyonu mevcut içerik için **`warn`** olmalıdır. `document.attachment` **%91,8** ile en uç örnek: 1654 px kuralı mevcut belgelerin ~%93'ünü reddeder. | **YOK** | `product-image.md` §9.1, §9.10; `logo.md` §12-D1, §13-K6; **`09-slot-bazinda-istatistik.md` §3, §4.1, §4.2, §4.6** |
| **FR-139** | Sistem, migration'da **durdurma kriteri** taşımalıdır. | `docs/plans/migration.md` §7.1: hata oranı **> %2** → DURDUR. Geri alma yolu üç seviyede tanımlı: batch'i dosya listesiyle geri al (`start_restore(scope="selected", file_names=[…])`), tüm optimize dosyaları geri al (`scope="optimized"`), tek dosya senkron (`restore_image`). | **KISMEN** — geri alma altyapısı VAR, durdurma kriteri politika | `migration.md` §4.6, §7.1 |
| **FR-140** | Sistem, etkilenen satıcıya **bildirim** göndermeli ve son tarih vermelidir. | `migration.md` §6.2 mesaj metni, §6.3 mevcut panel yüzeyleri, §6.4 son tarih. **Kim etkilenir sorusu bugün kısmen cevapsız** (§6.1) — FR-096 (`LIVE_SOURCES`) ve §8.8 ölçümü olmadan liste tam çıkarılamıyor. | **YOK** | `migration.md` §6 |
| **FR-141** | Sistem, eşik kalibrasyonunu **gerçek üretim korpusuyla** yapmalıdır. | Korpus gereksinimi: **en az 300 görsel**, gerçek üretim görsellerinden örneklenmiş (betik 300 altında **uyarı basar**); her kural için **her iki sınıftan en az 30 örnek** (altında "YETERSİZ ETİKET" der, eşik önermez); kategori dağılımı üretimi yansıtmalı ve riskli kategoriler (iç giyim, kasap, bıçak) **mutlaka temsil edilmeli** — yoksa FP oranı **yapay olarak iyi** çıkar. FP bütçesi: uyarı kuralları **%5**, RED kuralları **%1** (`--fp-budget 0.01` ile ayrı koşum). Betik ağa **çıkmaz** ve politika dosyasını **değiştirmez** — önerir, uygulamak insan kararıdır. Betik: `scripts/calibrate_content_rules.py` (891 satır, `chmod +x` yapıldı, **ÇALIŞTIRILMADI** — yalnız `py_compile` ile sözdizimi denetlendi). | **YOK** | `icerik-kurallari.md` §4 |
| **FR-142** | Sistem, kalibrasyon durumunu politika dosyasında **makinece okunabilir** tutmalıdır. | Kalibrasyondan sonra ilgili satırda `threshold_status` değeri `"KALİBRE EDİLMEDİ — başlangıç değeri"` yerine `"kalibre: <tarih>, korpus n=<N>, FP=<oran>"` olur. Bugünkü ölçülen durum: `calibration_status: "UNCALIBRATED"`, 9 kuralda 9 kez "KALİBRE EDİLMEDİ". | **YOK** | `icerik-kurallari.md` §4.4; T4 |

---

### 3.M — REVİZYON 2: ölçülen anomalilerden doğan gereksinimler

> Bu bölümün **tamamı** 2026-08-18 canlı ölçümünden doğdu. Her gereksinimin
> altında onu doğuran **sayı** yazılı. Sayısı olmayan gereksinim bu bölüme
> yazılmadı.

#### 3.M.1 BULGU — piksel tavanı fiilen kapalı değil

Politika görsel slotlarında `accept.max_megapixels_hard = 80` diyor.
**Bugünkü kütüphanenin en büyük dosyası 72,71 MP.** Yani eşik **hiçbir dosyayı
reddetmiyor** — decompression-bomb kapısı olarak var, koruma olarak yok.

**Ölçüm** (konteynerde, 4.812 görselin tamamı Pillow ile açıldı; `MAX_IMAGE_PIXELS`
kapatılarak. `tabFile` satır sayımıdır — aynı dosya birden çok kayıtta geçebilir):

| eşik (MP) | üstünde kalan kayıt | oran | en büyük dosyanın RGBA çözme maliyeti |
|---:|---:|---:|---|
| 16 | 263 | %5,47 | — |
| **20** | **179** | %3,72 | — |
| 25 | 116 | %2,41 | — |
| 30 | 39 | %0,81 | — |
| **40** | **12** | **%0,25** | — |
| 50 | 11 | %0,23 | — |
| 60 | 3 | %0,06 | — |
| 72 | 3 | %0,06 | — |
| **75** | **0** | **%0,00** | — |
| **80 (mevcut kural)** | **0** | **%0,00** | **hiçbir şey reddedilmiyor** |
| 100 | 0 | %0,00 | — |

En büyük 5 dosya (ölçülen):

| MP | boyut | mod | disk | RGBA çözüldüğünde RAM |
|---:|---|---|---:|---:|
| **72,71** | 10315×7049 | RGB | 9,70 MB | **~291 MB** |
| 54,00 | 9000×6000 | RGB | 4,25 MB | ~216 MB |
| 48,02 | 5658×8487 | RGB | 1,24 MB | ~192 MB |
| 36,27 | 7677×4724 | RGBA | 10,89 MB | ~145 MB |
| 36,16 | 7361×4912 | **CMYK** | 2,55 MB | ~145 MB |

**Bellek bağlamı — ölçüldü:** `istoc-dev-backend-1` konteynerinin bellek
limiti **yok** (`HostConfig.Memory = 0`); host'ta 8,787 GiB paylaşılıyor ve
backend'in ölçüm anındaki RSS'i **208,2 MiB**. Tek bir 72,71 MP dosyanın RGBA
çözümü **~291 MB** — yani **backend'in tüm ayak izinin 1,4 katı** tek bir
istekte ayrılır. Disk üzerindeki dosya **9,70 MB**; bayt tavanı (25 MB) bunu
**durdurmaz**. Klasik decompression-bomb profili budur.

| ID | Gereksinim | Kabul testi | Bugün | Kaynak |
|---|---|---|---|---|
| **FR-143** | Sistem, `accept.max_megapixels_hard` değerini **bayt tavanından değil, çözme anındaki bellek bütçesinden** türetmeli; eşik gerçek kütüphaneyi kesen bir yerde durmalıdır. | Eşik `E` MP için en kötü durum belleği `E × 4 bayt/px` ile hesaplanır ve politikanın `sources` bloğunda **yazılı** olur. **Önerilen değer: 40 MP** (≈160 MB/çözüm). Gerekçe: (a) 40 MP bugün **12 kayıt** (%0,25) reddeder — reddedilen küme insan eliyle incelenebilecek kadar küçüktür; (b) 80 MP **0 kayıt** reddeder, yani hiçbir işlevi yoktur; (c) 20 MP'ye inmek **179 kayıt** (%3,72) reddeder — güvenlik kapısının kalibrasyon kararına dönüşmesi demektir ve o karar FR-149'un konusudur. **Sert ret ile kalite kararı ayrılmalıdır:** `max_megapixels_hard` bir **güvenlik** kapısıdır (ret), `master.max_megapixels` bir **kalite** kapısıdır (küçültme). Bugün ikincisi yok, birincisi işlevsiz. | **YOK** — kod tarafında hiç kontrol yok; **politika değeri de fiilen kapalı** | bu bölüm §3.M.1 ölçümü; `product-image.md` §3.1 |
| **FR-144** | Sistem, **her** görsel slotunda `accept.max_megapixels_hard` alanının **var olmasını** zorunlu kılmalıdır; alanı olmayan politika `active` yapılamamalıdır. | Ölçüldü: 9 politikanın **7'sinde** alan var (görsel 80 MP, video 8,3 MP), **2'sinde YOK** — `seller-logo.json` ve `brand-logo.json`. Bu iki slotta bugün **hiçbir piksel tavanı yok**; 500 MP'lik bir "logo" kabul yolunda tek bir sayıya bile takılmaz (`accept.max_bytes` 1 MB / 576 KB onu **durdurmaz**: bomba dosyalar tam da küçük bayt–büyük piksel profilindedir). Şema bu alanı **zorunlu** yapmalı. | **HATALI** — alan iki logo politikasında eksik | `tradehub_core/media/pipeline/policy/slots/{seller,brand}-logo.json` `accept` bloğu (2026-08-18 okundu) |
| **FR-145** | Sistem, CMYK ve diğer sRGB dışı renk uzaylarını **kabul yolunda** sRGB'ye çevirmeli; çeviriyi yalnız optimizasyondan geçen dosyalara bırakmamalıdır. | Ölçüldü: kütüphanede **38 CMYK dosya**; bunların **18'i ürün görseli** (`09-…md` §4.1) ve biri **36,16 MP**. Bugün `engine.optimize` çeviriyor, ama yalnız **optimize edilen** dosyayı; optimizasyon kapılarından (`gates.py` Kapı 1 `MIN_FILE_SIZE=200KB`, Kapı 4 `already_small`) dönen CMYK dosya **çevrilmeden servis edilir** ve tarayıcıda yanlış renk verir. Kabul: CMYK bir dosya, optimizasyon kapılarından dönse bile, master üretiminde sRGB'ye çevrilir; çeviri `optimization` yanıt bloğunda raporlanır. | **KISMEN** — `engine.optimize` çeviriyor; kapılardan dönen dosya çevrilmiyor | `08-canli-olcum.md` §1.1, §1.3; `09-…md` §4.1; `engine.py`; `gates.py:55-72` |
| **FR-146** | Sistem, alfa kanalı taşıyan bir master'ı **alfasız bir biçime düşürmemelidir**. | Ölçüldü: kütüphanede **597 alfalı dosya** (%12,4); `document.attachment` altındaki 56 rasterın **32'si** alfalı; ürün görsellerinde 209 alfalı. Kabul: master formatı seçilirken alfa varlığı kontrol edilir; alfa varsa `jpeg` **seçilemez** (WebP/PNG/AVIF zorunlu). Alfa düşürme yalnız açıkça `pad_color` tanımlı bir slotta (ör. og:image, FR-044) ve **düz beyaz zemine kompozit** ile yapılabilir. | **YOK** — format seçiminde alfa kontrolü yok | `08-canli-olcum.md` §1.1; `09-…md` §4.1, §4.2 |
| **FR-147** | Sistem **tek bir kaynak-doğru politika setine** dayanmalıdır; iki set aynı anda yürürlükte olamaz. | Ölçüldü — çelişkinin **sayısal** bedeli: aynı `(doctype, field)` çiftine iki farklı taban dayatılıyor. `Listing.primary_image`: `media_engine` kısa kenar ≥ 1000 → **%37,3** uyumsuz; `docs/standards/policies` uzun kenar ≥ 2000 → **%97,3** uyumsuz. `Admin Seller Profile.logo`: `media_engine` üst sınır **4096 px** → 0 dosya takılıyor; `standards` üst sınır **1024 px** → **9/17 dosya** takılıyor. Aynı 17 dosya, iki kural, iki sonuç. Kabul: kanonik set ilan edilir, diğeri ya silinir ya `deprecated: true` + `superseded_by` taşır; ikinci sette kalan **hiçbir** eşik yükleme yolunda okunmaz. | **YOK** — karar verilmedi (T6) | `09-slot-bazinda-istatistik.md` §5, §6; `README.md:288` |
| **FR-148** | Sistem'in politika doğrulama betiği **her koşumda çalışabilir** olmalı ve tek bir çıkış koduyla sonuç vermelidir. | `docs/standards/README.md` §6 betiği bugün **çöküyor**: `master["max_megapixels"]` eksik olduğu için `KeyError`. Eksik alanı hata sayan varyantla koşunca **6 hata**: D3 ×2 (`content_rules[animated].message_key = "animated"`, ama `messages.tr`'de anahtar **`format_animated`**), D4 ×2 (`master.max_megapixels` yok — FR-032 invaryantı bu iki politikada **doğrulanamıyor**), D5 ×2 (yanlış pozitif: iki logo slotunun ortak belgesi `logo.md`). Kabul: betik eksik alanı `KeyError` yerine **hata** sayar; D5 kontrolü politika→belge eşlemesini dosya adından değil politikanın kendi alanından okur; 9/9'da çıkış kodu **0**. **Bu FR, G1 kapısının ön koşuludur.** | **HATALI** — betik yazıldığı gibi koşamıyor | §0.3-B koşum çıktısı; `README.md` §6 |
| **FR-149** | Sistem, bir slot politikasını `active` yapmadan **önce**, o politikanın gerçek veriye uygulanmış **uyum karnesini** politikanın içinde taşımalıdır. | Her politikada `compliance_measured` bloğu: `{measured_at, dataset, n, violation_rate, top_violation, enforcement_mode}`. `enforcement_mode` **ölçümden türer**: `violation_rate > %10` ise `new_uploads_only`, aksi hâlde `all`. Ölçülen bugünkü karne (`09-…md` §3): `company.cover_image` %17,6 · `seller.logo` %31,6 · `product.image` %48,6 · `product.video` %80,0 · `company.cover_video` %83,3 · `document.attachment` %91,8 · `category.banner` %100 · `user.avatar` %100 · `brand.logo` %0 (n=1). **Yani bugün 9 slotun 8'i `new_uploads_only` moduna düşer.** Bu sayı yazılı olmadan hiçbir politika `active` edilemez — FR-138'in makine-okunur karşılığıdır. | **YOK** — şemada böyle bir blok yok | `09-slot-bazinda-istatistik.md` §3; FR-138 |
| **FR-150** | Sistem, slot alanında **harici URL** bulunduğunda bunu bir politika ihlali olarak **raporlamalı**, sessizce geçmemelidir. | Ölçüldü: 3.239 eşsiz referansın **719'u** harici host (`cdn.dummyjson.com`, `images.pexels.com`, `images.unsplash.com`, `ui-avatars.com`). `user.avatar` slotunun **6/6'sı**, `category.banner`'ın **30/32'si** harici. Bu dosyalar üzerinde medya motorunun **sıfır kontrolü** var: piksel, bayt, format, saklama, silme — hiçbiri uygulanamaz. Kabul: harici URL taşıyan alan `external_reference` olarak işaretlenir; slot uyum karnesinde (FR-149) **ayrı satır** olarak sayılır; `active` bir slotta yeni harici URL **kabul edilmez**. | **YOK** — bugün alan serbest metin | `09-slot-bazinda-istatistik.md` §0, §2, §4.3, §4.4 |

#### 3.M.2 Bu bölümün kapsam dışı bıraktığı

| Konu | Neden yazılmadı |
|---|---|
| 20 MP üstü 179 dosyanın **küçültülmesi** | Bu bir **migration** işidir (T-028, `09-…md` §8 madde 7), gereksinim değil. FR-143 yalnız **kabul kapısını** düzeltir; mevcut dosyalara dokunmaz (FR-138) |
| CMYK 38 dosyanın **dönüştürülmesi** | Aynı — migration (`09-…md` §8 madde 6) |
| `max_megapixels_hard` için **kesin** sayı | 40 MP bir **öneridir**, karar değil. Bellek bütçesi (kaç eşzamanlı çözme, worker başına ne kadar RAM) ölçülmedi — konteynerde bellek limiti yok, gerçek eşzamanlılık profili bilinmiyor. Sayı §9.2'de ürün+backend onayı ister |
| 719 harici URL'nin **indirilmesi** | Ölçüm ortamı dış ağa çıkarılmadı; boyutları bilinmiyor → depolama etkisi hesaplanamadı |

---

## 4. Fonksiyonel olmayan gereksinimler

### 4.1 Performans

| ID | Gereksinim | Eşik ve türetmesi | Bugün | Kaynak |
|---|---|---|---|---|
| **NFR-001** | Kapak videosunun **pasif** mobil veri maliyeti (kullanıcı hiçbir şeye dokunmadan) tavanı aşmamalıdır. | **150 KB** = poster WebP ≤ **120 KB** + konteyner metadata (`preload="metadata"`, cue'lar başta) ≤ **30 KB**. Save-Data veya `effectiveType ∈ {slow-2g, 2g}` ise `preload="none"` → tavan **120 KB**. | **ÖLÇÜLMEDİ** | `company-cover-video.md` §6.7 |
| **NFR-002** | Kapak videosunun **ilk 10 saniyelik aktif** maliyeti tavanı aşmamalıdır. | **1.250 KB** = 480p tier tavanı 1,0 Mbps × 10 s = 10 Mbit. Hedef ortalama (0,7 Mbps) ile tipik **≈875 KB**. En kötü toplam (dokunduktan sonra 10 s): **1.400 KB**. | **ÖLÇÜLMEDİ** | `company-cover-video.md` §6.7 |
| **NFR-003** | Teslim edilen video rendition'ı dosya kapısını aşmamalıdır. | 720p WebM (VP9/Opus, CRF 32, `-maxrate 2500k -bufsize 5000k`, hedef ort. ≤1,6 Mbps) → **≤12 MB**; 720p MP4 (H.264 High/AAC-LC, CRF 23, 2800k) → ≤14 MB; 480p WebM (CRF 34, 1000k, hedef ort. ≤0,7 Mbps) → **≤5 MB**; 480p MP4 (CRF 25, 1200k) → ≤6 MB. Kapı aşılırsa **CRF +2 ile yeniden encode, en çok 2 deneme**, sonra `cover_video_too_heavy` ile ret. Bugün böyle bir kapı **yok** — çıktı ne olursa olsun `os.replace` ile yazılıyor. | **YOK** | `company-cover-video.md` §6.4 |
| **NFR-004** | Kapak videosu depolaması kotayı öngörülebilir tutmalıdır. | 6 nesne/kapak (720p WebM+MP4, 480p WebM+MP4, poster, önizleme). Tipik 30 s kapak ≈ **19 MB**; 60 s en kötü ≈ **37,5 MB**. Yükleme tavanı **80 MB** (türetme: 60 s × 10 Mbps cömert 1080p master = 600 Mbit = 75 MB → 80 MB). **Karar bekliyor:** rendition'lar `File` kaydı açarsa kota **6 kat** tüketir; öneri rendition'ların `File` kaydı **açmaması** (arşivin `ARCHIVE_DIRNAME` deseniyle aynı yaklaşım). | **YOK** | `company-cover-video.md` §6.3, §6.5, §10-K7 |
| **NFR-005** | İçerik kuralı motoru senkron yolda gecikme eklememelidir. | Görsel başına ortalama süre **100 ms**'yi aşarsa kural motoru `after_insert`'te değil kuyrukta (`frappe.enqueue`) çalışmalıdır. Her görselde 512 px'e indirme + 6 metrik hesabı yapılıyor. **ÖLÇÜLMEDİ** — komut §8.7'de. | **ÖLÇÜLMEDİ** | `icerik-kurallari.md` §7.7 |
| **NFR-006** | Transcode işi tek başına sistemi kilitlememelidir. | ffmpeg timeout **1700 s** (`transcode.py:52`), RQ kuyruk timeout **1800 s** (`:159`) → tek iş en fazla ~28 dakika tutar. `nice -n 10` ile önceliklendirilmiş (`:236`). **Koşullu** transcode: yalnız `genişlik > 1280` VEYA `bitrate > 2,5 Mbps` olan videolar işlenir — kodun kendi gerekçesi: *"sunucunun HER videoyu tekrar transcode etmesi 100'lerce eşzamanlı yüklemede kuyruğu boğar"*. **Kapak slotu istisnası:** rendition'lar koşulsuz üretilir (mağaza başına 1 dosya, nadiren değişir → kuyruk riski yok). | **VAR** — korunacak | `company-cover-video.md` §5.2, §6.12; `transcode.py` |
| **NFR-007** | Parçalı yükleme parametreleri değişmemelidir. | Parça **2 MB** (küçüğün bedeli istek sayısı, büyüğün bedeli bellek ve kopan parçanın yeniden gönderimi); azami parça **256** (sayaç olmadan sonsuz parça = diski doldurma yolu) → oturum tavanı **512 MB**; tek parça eşiği **8 MB** (base64 %33 şişirdiği için ham sınırın altında); oturum ömrü **6 saat** (tarayıcı kapanınca parçalar diskte kalıyor). | **VAR** — korunacak | `MEDYA-YUKLEME-SOZLESMESI.md` §4; `chunked.py:43,47,51` |
| **NFR-008** | Core Web Vitals bütçeleri karşılanmalıdır. | LCP **< 2500 ms**, CLS **< 0,1**, TBT **< 300 ms**, performans skoru **≥ 0,8**, SEO **≥ 0,9** (`lighthouserc.cjs:30-36`). En kritik iki audit: `uses-responsive-images` ve `modern-image-formats` — `srcset` ve AVIF eksikliğinin **bayt cinsinden** bedelini yalnız onlar verir. **ÖLÇÜLMEDİ** — komut §8.8'de. | **ÖLÇÜLMEDİ** | `03-render-envanteri.md` §7.1; `product-image.md` §9.9 |
| **NFR-009** | Türev merdiveni depolama bütçesini aşmamalıdır. | `product.image` merdiveninin **piksel alanı** hesabı: 7 profilin toplamı **6.517.760 px**, master (2400²) **5.760.000 px** → `ladder/master = **1,13**` (biçim başına). İki biçim (AVIF+WebP) ile ladder ≈ **2,26 × master piksel alanı**; master'ın kendisi de 1920→2400 geçişinde `(2400/1920)² = **1,5625**` yani **+%56** büyür. Logo tarafı: 4 rung × 2 format = `(4+8+16+40) KiB × 2 = 136 KiB` + og:image 120 KiB = **256 KiB/logo**; yalnız WebP ile **188 KiB/logo**. **Bunlar piksel/tavan hesabıdır, bayt ölçümü değildir** (§8.8). `06-depolama-maliyet.md` bütçesiyle çapraz kontrol edilmeden merdiven onaylanmamalıdır. | **ÖLÇÜLMEDİ** | `product-image.md` §5.5, §9.5; `logo.md` §12-D7 |
| **NFR-010** | Master tavanının yükseltilmesi türev üretimi gelmeden **uygulanmamalıdır**. | Bugün master **aynı zamanda servis edilen dosyadır**. `engine.py:177`'yi 1920 → 2400 yapmak, türevler gelmeden **her render noktasına %56 daha büyük dosya göndermek** demektir — sepet SKU satırı (80 px talep) 1920 yerine 2400 indirmeye başlar. Zorunlu sıra: **(1)** türev üretimi + URL sözleşmesi → **(2)** master tavanı 2400 → **(3)** `srcset`/`sizes` (önkoşulu `mediaUrl.ts:76`). | **YOK** | `product-image.md` §5.4 |
| **NFR-011** | Optimizasyon kapıları korunmalıdır: gereksiz yeniden encode yapılmamalıdır. | Kapı 1 `MIN_FILE_SIZE = 200 KB` (`presets.py:23`); Kapı 4 `already_small` — uzun kenarı `max_dim`'i **aşmayan** dosya hiç açılıp yeniden kaydedilmez, **bit düzeyinde aynı kalır** → nesil kaybı riski sıfır (`gates.py:70-72`); Kapı 5 `already_optimized` en başta (`gates.py:55-56`) — bir kez işlenmiş dosya ikinci kez küçültülmez (**DPI açısından kritik**: aynı dosyanın iki tur `thumbnail` görmesi kümülatif kayıp demek olurdu); Kapı 6 `MIN_SAVING_RATIO = 0.10` (`presets.py:25`) — türev kaynağından en az %10 küçülmüyorsa üretilmez. `gates.py:7-9` yorumundaki eski ölçüm: 4.007 dosyanın yalnız ~300'ü Kapı 4'ü geçiyor (**alıntı, bu çalışmada doğrulanmadı**). | **VAR** — korunacak | `dpi-ve-cozunurluk.md` §2.2; `gates.py`; `presets.py` |
| **NFR-012** | Avatar slotunda israf ölçülebilir biçimde azaltılmalıdır. | En büyük avatar kutusu **72 CSS px**, dosya tavanı **5 MB**, optimizasyon **çağrılmıyor** (`identity.py:955-966` File'ı doğrudan açıyor). Hesap: `4000 / (36 × 3) = **37 kat** fazla piksel genişliği`. Ayrıca Kapı 1 (200 KB) avatar için **doğru eşik değil** — 200 KB'lık bir dosya 72 px'lik kutu için hâlâ gereğinden büyük. Gerçek israf sayısı **ÖLÇÜLMEDİ** (§8.3). | **YOK** | E3; `user-avatar.md` §3, §5.4, §8.2 |
| **NFR-013** | Kota ve rate limit okumaları önbelleklenebilir olmalıdır. | `get_quota_limits(store)` cache'li (`entitlement/core.py:157`). Şema `enforcement.cache_ttl_seconds` alanını tanımlıyor (varsayılan `null`). | **KISMEN** | `kota.md` §1; `quota.schema.json` |

### 4.2 Güvenlik

| ID | Gereksinim | Eşik / kural | Bugün | Kaynak |
|---|---|---|---|---|
| **NFR-014** | Karar her zaman **sunucunun** olmalıdır; istemcideki her kontrol yalnız hızlandırma amaçlıdır. | Sorumluluk matrisi 20 satır; ad kontrolü, uzantı allowlist, yasaklı uzantı, boyut, içerik imzası, tehlikeli içerik, ad kırpma (140 karakter), mağaza kapsamı, kalıcı kayıt, denetim, üstveri temizleme, dönüştürme, kota, dosya adı üretimi → hepsi **Sunucu**. | **VAR** — korunacak | `MEDYA-YUKLEME-SOZLESMESI.md` §2 |
| **NFR-015** | Tek kapı politikası korunmalıdır: **her** yükleme yolu aynı `check()`'ten geçmelidir. | Zincir: `hooks.py:227-252` → `utils/security.py:96` → `media/upload_policy.py:307`. Yasak uzantı, dosya adı temizliği, boyut tavanı, ilk 512 baytta tehlikeli içerik taraması (`<html`, `<svg`, `<script`, `<?xml`, `<%`, `#!/`). Ölçülen kapsam: `seller_media.upload_media` **1** ekran, Frappe `upload_file` **22** ekran — ikisi de kancadan geçiyor. İzin listesi (dar) **kasten** yalnız medya uçlarında; gerekçe `upload_policy.py:18-23`: izin listesine çevirmek *"bugün çalışan ve listede olmayan her akışı sessizce kırardı"*. | **VAR** — korunacak | `MEDYA-YUKLEME-SOZLESMESI.md` §1, §3 |
| **NFR-016** | Bir satıcı başka bir mağazanın dosyasının **varlığını bile** öğrenememelidir. | Sahibi olmadığı dosyada **"Dosya bulunamadı"** döner; toplu işlemlerde sessiz atlama; `remaining_owners` bir **sayı**. Testler: FR-115 kapıları. | **VAR** — korunacak | `04-yetki-modeli.md` §3.2, §3.3, §3.6 |
| **NFR-017** | Geri alınamaz işlemler **yalnız en yüksek role** açık olmalıdır. | `ALLOWED_ROLES = ("System Manager", "Marketplace Admin")` → **27** uç; `DESTRUCTIVE_ROLES = ("System Manager",)` → **12** uç. Gerekçe kodda yazılı: *"Arşiv silindikten sonra optimize edilmiş görsellerin orijinali sistemde kalmıyor — bu yetkiyi `Marketplace Admin` seviyesine açmak geri dönüşü olmayan bir riski yayar."* | **VAR** — korunacak | `04-yetki-modeli.md` §2 |
| **NFR-018** | Private dizin web'den **doğrudan erişilemez** olmalıdır. | Erişim `X-Accel-Redirect` ile internal nginx location'a yönlenir. Guest → **403** (canlı doğrulanmış, `MEDYA-ERISIM-MODELI.md` §2.2). | **VAR** — korunacak | `MEDYA-ERISIM-MODELI.md` §2.2 |
| **NFR-019** | Dosya adları **tahmin edilemez** olmalıdır. | `<sha256(içerik)[:32]>.<uzantı>` = **128-bit** → enumeration imkânsız. Ölçülen risk: eski isimlerin %50'si (`0505.jpg`) URL'den toplu çekilebiliyordu; **2.166** tahmin-edilebilir eski isim hâlâ korunuyor (retro-rename ertelendi: ~2.400 referans güncellemesi + 301 haritası gerektiriyor). Ara önlem: nginx `X-Robots-Tag: noindex` + `limit_req`. | **VAR** (yeni yüklemeler) | `MEDYA-DEPOLAMA-STANDARDI.md` §4.1, §7 |
| **NFR-020** | Yol geçişi (path traversal) **iki bağımsız katmanda** engellenmelidir. | `_require_private_path` (`media_access.py:66-76`) + `check_path_safety` (`:189`). Testler: `::test_path_traversal_reddedilir`, `::test_path_traversal_download_da_reddedilir`. | **VAR** — korunacak | `04-yetki-modeli.md` §7.4 |
| **NFR-021** | Sistem kendi kriptosunu **yazmamalıdır**. | Frappe `verified_command` (site secret ile HMAC-SHA512). | **VAR** — korunacak | `04-yetki-modeli.md` §7.1 |
| **NFR-022** | Kullanıcı SVG'si hiçbir koşulda DOM'a **inline edilmemelidir**. | Ne `innerHTML`, ne Alpine `x-html`, ne Vue `v-html`. Bugün satıcı/marka logosu **yalnız** `<img src>` / `:src` ile basılıyor (16+3 render noktasının hepsi) — bu ayrım **korunmalı**: `<img>` ile yüklenen SVG script çalıştırmaz, sanitize kaçırsa bile **ikinci savunma hattı**. İnline `<svg>` olan tek yerler sabit kodlanmış ikonlar. | **VAR** — korunacak | `logo.md` §6.2 SVG-7 |
| **NFR-023** | CSS injection kapatılmış kalmalıdır. | `section-registry.ts` `safeHexColor()` bölüm arka plan rengini süzüyor (`:159,205,792`); `CategoryShowcase.ts:137` `sanitizeImageUrl` + `:135` `sanitizeHref` + `escapeAttr`/`escapeText`. | **VAR** — korunacak | `company-cover-image.md` §7; `category-banner.md` §7 |
| **NFR-024** | İstemci sıkıştırmasının **bilinçli kapatıldığı** yerler geri açılmamalıdır. | KYC: `KycLayout.ts:381` `compress: false`; KYB: `alpine/kyb.ts:303-306` `autoCustomUploader` ile sıkıştırmayı atlıyor. Gerekçe: **OCR okunabilirliği**. **Hiçbir "optimizasyon" önerisi bunu geri açmamalıdır.** | **VAR** — korunacak | `document-attachment.md` §6 madde 5 |
| **NFR-025** | PDF içindeki aktif içerik riski **kayıtta tutulmalıdır**. | `engine.py` PDF'e dokunmuyor; `upload_policy.py:187-224` yalnız ilk 512 baytta `<html`/`<svg`/`<script` arıyor → **PDF içindeki `/JS`, `/JavaScript`, `/OpenAction`, `/Launch`, `/EmbeddedFile` taranmıyor**. Bu, belge slotunda ortaya çıkan **ayrı bir güvenlik konusudur**; SRS'de gereksinim gövdesine alınmadı, izlenen risk olarak kayıtlıdır. Tarama komutu §8.11'de. | **YOK** | `document-attachment.md` §7.6 |
| **NFR-026** | `Administrator` reddi denetime **yazılmıyor** — bu bilinen sınır kayıtta tutulmalıdır. | `frappe.only_for` Administrator'ı **atlar** (`api/media_admin.py:59-60`) → ret denetim kaydı Administrator için **hiç oluşmuyor**. | **HATALI** (kabul edilmiş sınır) | `04-yetki-modeli.md` §4.1 notu, §8-D |
| **NFR-027** | `File` doctype'ı için tenant-aware `permission_query_conditions` **yok** — bu sınır kayıtta tutulmalıdır. | `tradehub_core`'da `File` için custom `has_permission` yok → Frappe varsayılanı + bağlı-doc delegasyonu geçerli. Satıcı alt kullanıcılarının rollerine bağlı olarak bu bir açık olabilir; belirleyici ölçüm §8.12'de. | **YOK** | `04-yetki-modeli.md` §8-B, §9.2 |

### 4.3 Erişilebilirlik

| ID | Gereksinim | Eşik / kural | Bugün | Kaynak |
|---|---|---|---|---|
| **NFR-028** | Görsel yoksa arayüz **kırılmamalıdır**. | Kapak: `onerror` ile `linear-gradient` + `minHeight: 300px` (`section-registry.ts:104-105`). Kategori: tonal gri + koyu metin, `labelColor`/`hoverColor` görselin varlığına göre değişiyor (`CategoryShowcase.ts:157-158`). Avatar: baş harf + gradient (`SettingsLayout.ts:100-104`). Logo: `bg-*` plaka. | **VAR** — korunacak | `company-cover-image.md` §7; `category-banner.md` §7; `user-avatar.md` §7 |
| **NFR-029** | Görsel üstündeki metin **her görselde okunabilir** olmalıdır. | Kategori döşemesinde gradient scrim: `bg-gradient-to-t from-black/75 via-black/25 to-transparent` (`CategoryShowcase.ts:154`). Bu **zaten çözülmüştür** ve üstüne kural yazılmamalıdır (FR-131). | **VAR** — korunacak | `category-banner.md` §6, §7 |
| **NFR-030** | Slider kontrolleri erişilebilir olmalıdır. | Önceki/sonraki butonları `aria-label` ile (`section-registry.ts:185,188`), pagination (`:212`). | **VAR** — korunacak | `company-cover-image.md` §7 madde 6 |
| **NFR-031** | Arayüz RTL'de **otomatik aynalanmalı**; aynalanamayan içerik videoya/görsele gömülmemelidir. | Mantıksal yön özellikleri kullanılıyor (`start-2`/`end-2`/`ms-1`/`pe-0`). Bunun sonucu FR-026'dır (gömülü logo yasağı) ve FR-069'dur (sayı yönü). | **VAR** — korunacak | `company-cover-video.md` §3.2 |
| **NFR-032** | Yükleme ilerleme geri bildirimi tüm slotlarda **tutarlı** olmalıdır. | Ortak UX değerleri: tick 100 ms, +%10-18, cap %85, success hold 350 ms — KYC/KYB/SlotDropzone ve avatar aynı değerleri kullanıyor (`alpine/settings.ts:89-95`). | **VAR** — korunacak | `user-avatar.md` §7 madde 5 |
| **NFR-033** | `alt` metni ve `loading`/`decoding` öznitelikleri uygulanmış kalmalıdır. | Kategori döşemesi: `loading="lazy" decoding="async"` (`CategoryShowcase.ts:152`). Fold-üstü/altı lazy ayrımı **bilinçli** bir CWV kararıdır (`ListingCard.ts:17-23`). **Kısıt:** CSS `background` ile basılan slotlarda (`Brand.hero_banner` `brand.ts:145-148`, `Hero Slide.background_image` `HeroTopSlider.ts:136`, `seller-shop.ts:118-119`) `loading`/`decoding`/`srcset`/`fetchpriority` **uygulanamaz** (B4) — politika bunu `rendered_as_css_background` kuralıyla `review` olarak işaretler. | **KISMEN** | `03-render-envanteri.md` §4.1; B4 |

### 4.4 Gözlemlenebilirlik

| ID | Gereksinim | Eşik / kural | Bugün | Kaynak |
|---|---|---|---|---|
| **NFR-034** | Medya olayları **tek bir denetim şemasına** yazılmalıdır. | `media.*` action ad alanı (`media/audit.py:43-68`): `media.trash`, `media.untrash`, `media.delete`, `media.purge_trash`, `media.purge_archive`, `media.scope_denied`, `media.access_denied`, `media.level_changed`, `media.upload`, `media.signed_access`. Yeni action'lar aynı desene uymalıdır (ör. `media.legal_hold_block`). **Yazma hedefi doğrulanmalı:** `media/schema.py:33` `FULL_TABLES = ("tabFile", "tabAuthorization Decision Log")` listesinden çıkarıldı; `audit.log_media_event`'in gerçekte hangi doctype'a yazdığı **bu çalışmada doğrulanmadı** (§8.13). | **VAR** (kısmen doğrulanmamış) | `retention.md` §9.2; `kota.md` §10.6 |
| **NFR-035** | Denetim kaydında hassas değerler **maskelenmelidir**. | Erişim seviyesi geçişinde ham URL context'e yazılmaz, `object_name` maskeli. İki test bunu bağlıyor. | **VAR** — korunacak | `04-yetki-modeli.md` §6.6 |
| **NFR-036** | Zamanlanmış görevlerin **koştuğu** denetimden kanıtlanabilir olmalıdır. | `Scheduled Job Log`'da `%media%` görevleri için günde birer `Complete` satırı. Purge audit'inde `trigger`, `retention_days`, `deleted`, `freed_bytes` alanları. Hiçbir şey silinmediğinde de kayıt (`trash.py:319-320`). | **KISMEN** | `retention.md` §9.1, §9.2 |
| **NFR-037** | Kural tetiklenmelerinin **sebebi** loglanmalıdır. | `not_measurable` durumunda kural sessizce atlanır **ve loglanır**. `SKIP_REASONS` sözlüğü zaten var (`gates.py:28-37`). | **KISMEN** | `icerik-kurallari.md` §3.0; `gates.py:28-37` |
| **NFR-038** | Rate limit olayları denetlenebilir olmalıdır. | `audit_rate_limit_events: true`, `alert_on_backend_failure: true`. | **YOK** | `quota.schema.json` `rate_limit` |
| **NFR-039** | Video hattının sağlığı izlenebilir olmalıdır. | `File.th_media_video_status` ∈ `processing`/`ready`/`failed` (`transcode.py:48-50`); panel `media/inventory.py:239,261`'den okuyor. İzlenecek: `failed` oranı ve **`processing`'de 24 saatten fazla takılı** satırlar; `NULL` satırlar hattın hiç dokunmadığı videolardır. | **VAR** (alan) — izleme YOK | `product-video.md` §7 madde 7; `company-cover-video.md` §11-D4 |

### 4.5 Dayanıklılık ve tutarlılık

| ID | Gereksinim | Eşik / kural | Bugün | Kaynak |
|---|---|---|---|---|
| **NFR-040** | Transcode **idempotent** olmalıdır. | Aynı dosya `upload_media` ve global `after_insert` kancasından iki kez tetiklenirse ikinci kez kuyruğa **girmez** (`transcode.py:139-140`). Testler: `::test_zaten_processing_ise_tekrar_enqueue_edilmez`, `::test_zaten_ready_ise_tekrar_enqueue_edilmez`, `::test_zaten_kuyruklanmis_dosyada_ikinci_kez_enqueue_cagrilmiyor`. | **VAR** — korunacak | `product-video.md` §7 madde 3 |
| **NFR-041** | Yarım dosya **asla yazılmamalıdır**. | ffmpeg çıktısı geçici `.transcoding.webm` dosyasına gider (`transcode.py:230`), başarıda `os.replace` ile atomik takas edilir (`:251`). | **VAR** — korunacak | `product-video.md` §7 madde 5, 6 |
| **NFR-042** | Yedek/geri yükleme, transcode ile **çatışmamalıdır**. | `media/backup.py:79-84` durum alanını yedekliyor; `media/restore.py:198` + `flags.th_skip_transcode` (`transcode.py:191-192`) geri yüklenen dosyayı **ezmiyor**. | **VAR** — korunacak | `product-video.md` §7 madde 8 |
| **NFR-043** | `ffprobe` okunamadığında **güvenli tarafa** düşülmelidir. | `needs_transcode` ffprobe hatasında **`True`** döner (emin değilsek transcode et) + `log_error` (`transcode.py:96-106`). Üç test bunu bağlıyor. **Kritik uyarı:** ffmpeg/ffprobe imajda yoksa her videoda `log_error` yazılır, `True` dönülür ve `_run_transcode` `FileNotFoundError` alır → **hiçbir video normalize edilmez** (§8.14). | **VAR** — korunacak | `product-video.md` §6, §8.1 |
| **NFR-044** | `file_url` **sabit** kalmalı; referanslar kırılmamalıdır. | Görsel: format korunur (JPEG→JPEG, PNG→PNG) → uzantı değişmez (`engine.py:8-9`). Video: `os.replace` ile yerinde yazma (`transcode.py:29-31`). **İstisna:** kapak videosu slotunda yerinde yazma **yasaklanır** (FR-041) — o slotta manifest tutulur. | **VAR** — korunacak (bir istisnayla) | `dpi-ve-cozunurluk.md` §2; `company-cover-video.md` §6.5 |
| **NFR-045** | Aynı sınır için **tek sayı** olmalıdır. | Ölçülen çelişkiler: **video boyutu 4 farklı sayı** — 200 MB (`upload_policy.py:69`), 25 MB (`platform_limit()` Frappe varsayımı, `:239-259`), 10 MB (`ListingFormView.vue:4169`), 10 MB (doctype `description`) → standart **en sıkı olanı (10 MB)** alır, yeni sayı üretmez. **"Verimli" bitrate barı 2 farklı sayı** — istemci 2,0 Mbps (`compress.video.js:29`), sunucu 2,5 Mbps (`transcode.py:67`) → aynı dosya giriş kapısına göre iki farklı sonuç alıyor; karar: **2,0 Mbps'te birleştir** (dar olan kazanır). **Uzun kenar 3 farklı sayı** — 1920 (`engine.py:177` garanti-WebP), 2000 (`presets.py:15` balanced), 2560 (`presets.py:14` safe) + istemcide 1920 (`compress.image.ts:10`, `compress.image.js:9`). **Panel oran tavsiyesi ↔ önizleme çelişkisi** — `ProfileImageDropzone.vue:135` dikdörtgen önizleme 256×144 = **16:9**, aynı bileşenin `recommendedSize` metni **1600×400 = 4:1**, gerçek kutu 1920px'te **4,8:1**. **Panel logo tavsiyesi ↔ standart** — 400×400 (`DocTypeFormView.vue:448`) vs 512×512; 400 master **512 rung'unu doğuramaz** (upscale yok). | **HATALI** | B7; Ç3; Ç4; A1; F17; F18 |
| **NFR-046** | Aynı kural iki yerde **tekrar yazılmamalıdır**. | `Seller Gallery Image.category` enum'u iki yerde: doctype `options` ve `_MEDIA_CATEGORIES` (`api/seller.py:760-765`). Biri değişirse `_build_media_groups` bilinmeyen kategoriyi **sessizce `overview`'a düşürür** (`api/seller.py:806-808`). Karar: enum'un **tek kaynağı doctype JSON'u** olmalı (Ç12). | **HATALI** | Ç12 |
| **NFR-047** | İki tavanın birbirini **sessizce kilitlemesi** önlenmelidir. | Ölçülen kilit (A1): `to_webp` 1920'ye iniyor; `balanced` preset tavanı 2000; `1920 <= 2000` olduğu için Kapı 4 (`already_small`) dosyayı **hiç açmıyor** → batch optimizer o dosyayı kurtaramıyor. Arşiv **30 gün** (`presets.py:38`) — o pencere kapandıktan sonra 1920'nin üstündeki piksel **kalıcı olarak kayıp**. Testte sabitlendi: `tests/test_policy_dpi.py::TestUploadYoluTabaniKarsilamiyor` `@unittest.expectedFailure`; test **yeşile dönerse** (*unexpected success*) biri tavanı düzeltmiş demektir ve madde kapanır. Bayt maliyeti ölçüldü (3000×3000 sentetik **gürültü**, WebP q80, `method=4` — gürültü en kötü durumdur, gerçek fotoğraf daha küçüktür): 1920 → 987.436 B; **2000 → 1.047.028 B (+%6,0)**; 2400 → 1.781.120 B (+%80,4); 2560 → 2.315.410 B (+%134,5). Öneri: üç noktadaki 1920 → **2000** (2560 değil). | **HATALI** | A1; `dpi-ve-cozunurluk.md` §6-A1; `product-image.md` §9.8 |
| **NFR-048** | Her giriş yolu **aynı tavana** tabi olmalıdır. | Ölçülen açık (A2): `IMAGE_TO_WEBP_EXTENSIONS` kümesinde `.webp` **yok** (`seller_media.py:245-247`) → `.webp` uzantısıyla gelen içerik `to_webp`'e hiç girmez, `thumbnail` **görmez**; tek sınır L0'ın 25 MB'ı. İstemci sıkıştırmasını atlayan bir çağrı (doğrudan API, otomasyon, bulk) 8000×8000 bir WebP'yi olduğu gibi kütüphaneye koyabilir. Bu bir DPI sorunu değil, aynı standardın öbür yarısıdır: **uzun kenar tavanı her giriş yolunda uygulanmalı.** | **HATALI** | A2; `dpi-ve-cozunurluk.md` §6-A2 |
| **NFR-049** | Yedekleme dayanıklılığı korunmalıdır. | Günlük yedek → `prune(keep=14)` → `backup_export.cleanup()` sırası (`backup.py:390-419`); içerik-adresli havuz `blobs/<xx>/<sha256>` + manifest; paket ömrü **48 saat**. Yedek alınamazsa `prune` **hiç çalışmaz**. | **VAR** — korunacak | `retention.md` §1, §4.4 |
| **NFR-050** | Aynı içerik **tek fiziksel dosya** olmalıdır. | İçerik-adresli isim → doğal dedup; Frappe'nin `content_hash` dedup'ı da insert öncesi yakalıyor. Testler: `test_media_naming.py::test_ayni_icerik_ayni_hash_farkli_ad_gizli`, `::test_ayni_icerik_iki_kez_yazilinca_ayni_dosya_adini_uretir`, `test_media_pipeline_integration.py::test_ayni_icerik_iki_kez_yuklenince_ayni_file_url_uretir`. | **VAR** — korunacak | `MEDYA-DEPOLAMA-STANDARDI.md` §4.3 |
| **NFR-051** | Dizin başına dosya sayısı **ölçeklenebilir** kalmalıdır. | Hash-prefix shard `hash[:2]` → **256** alt dizin (`00`–`ff`) → dizin başına ~N/256. Ölçülen bugünkü düz yapı: `public/files/` **2.858** dosya, `private/files/` **192** dosya (bu iki sayı `MEDYA-DEPOLAMA-STANDARDI.md` §2'den **alıntıdır**, bu çalışmada ölçülmedi). Mevcut `file_url`'ler **kırılmaz**: shard yalnız yeni yüklemelere uygulanır; nginx her iki deseni de servis eder. | **VAR** — korunacak | `MEDYA-DEPOLAMA-STANDARDI.md` §3, §4.2, §6 |
| **NFR-052** | Tarih/saat gösterimi kullanıcının saat dilimine göre **tek anlamlı** olmalıdır. | Saklama değişmiyor; API çıktısı **ISO 8601 + `+03:00` kayması** taşır (`T` ayıracı zorunlu — boşluklu biçim bazı tarayıcılarda ayrıştırılamıyor). Panel gösterimi tek kaynaktan: `formatDay`, `formatDateTime`, `formatClock`, `formatAgo`, `toTimestamp`. Ölçülen hata: kayma olmadan Londra kullanıcısı 09:39 yerine 07:39 görmeliyken 09:39 görüyordu; panelde **dört ayrı biçimlendirme** vardı (biri dili `tr-TR`'ye sabitlemiş, biri ham dize kırpıyordu). | **VAR** — korunacak | `MEDYA-TARIH-STANDARDI.md` §1, §2 |

---

## 5. Kısıtlar

Bu bölüm **değiştirilemez ya da bu fazda değiştirilmeyecek** koşulları listeler.
Her kısıt bir tasarım kararını kilitler; bir gereksinim bir kısıtla çelişiyorsa
**kısıt kazanır** ve gereksinim change request'e döner.

### 5.1 Mimari kısıtlar

| ID | Kısıt | Kanıt | Sonucu |
|---|---|---|---|
| **K-01** | **Medya kodu `tradehub_core` içindedir; ayrı bir Frappe app DEĞİLDİR.** | `tradehub_core/media/` (8.200 satır, ölçüldü), `tradehub_core/api/{seller_media,media_admin,media_access}.py`. `apps.txt`'te ayrı bir medya app'i yok. | Slot kayıt defteri (FR-002) `tradehub_core` içine yazılır. Ayrı app'e çıkarmak `hooks.py` (doc_events + scheduler_events), `patches/` ve `File` custom alanlarının taşınması demektir — **bu SRS'in kapsamı dışı, ayrı bir mimari karar**. |
| **K-02** | **Nesne deposu (S3 / MinIO) YOKTUR.** | `boto3`/`s3_bucket`/`aws_access`/`minio` geçen **tek** satır bir yorum: `audit/__init__.py:23` ("10 yıl arşiv (S3/MinIO — Faz 3'te encryption)"). `requirements.txt` **3 satır**: `defusedxml>=0.7`, `scikit-learn>=1.3` + bir yorum. | Bütün saklama **tek yerel diskte**: `frappe.get_site_path("private", …)`. `retention.schema.json`'daki `s3_standard`/`s3_cold` hedefleri `implementation_status: not_implemented` ve seçilirse yükleyici **reddeder** (FR-105). Katmanlı depolama bir gereksinim değil, **gelecek yer tutucusudur**. |
| **K-03** | **CDN YOKTUR.** | `?t=Date.now()` cache-buster'ı "**ileride CDN eklenirse** bu sorun zaten çözülmüş demektir" notuyla yazılmış (`user-avatar.md` §7 madde 3, `alpine/settings.ts:126`). `MEDYA-DEPOLAMA-STANDARDI.md` §8 CDN'i "geçiş" olarak listeliyor, mevcut değil. | Bant genişliği maliyeti **doğrudan origin'de**. `srcset` kazancı (FR-121) CDN olmadan da geçerlidir ama önbellek parçalanması maliyeti origin'e biner — merdivenin 7 profille sınırlı tutulması (FR-036) bu yüzden önemlidir. Public dosyalar nginx tarafından **doğrudan** servis edilir. |
| **K-04** | **Türev (derivative) üretimi YOKTUR: bir yükleme → bir dosya.** | `03-render-envanteri.md` §6.3; `engine.py:117,177` aynı dosyayı küçültüyor, ayrı çıktı + ayrı `file_url` üretmiyor; `thumbnail_url` repoda **hiç geçmiyor**. | Tüm `profiles[]` girdileri bugün **kâğıt üzerindedir** (`README.md` §6 "ölçmediği" tablosu). `derivative_retention` **boş kümeye** uygulanır (FR-104). `srcset` yazmanın gösterecek ikinci dosyası yoktur (FR-121). |
| **K-05** | **Sunucu bir yüklemenin hangi slota ait olduğunu BİLMEZ.** | `upload_policy.check()` imzası: `file_name`, `content`, `size`, `media_endpoint` — **slot parametresi yok** (`upload_policy.py:307-313`). | Bu, **B1**'dir ve `docs/reports/00-upload-slot-envanteri.md` §7-B onu "Faz 2'nin çözmesi gereken tek yapısal eksik" olarak işaretlemiştir. Slot kimliği olmadan **B2, B3, B5, B6, B8'in hiçbiri** çözülemez. Bu SRS'teki L3 gereksinimlerinin (FR-015…FR-027) **tamamı** FR-001'e bağımlıdır. |
| **K-06** | **Video ölçü/süre metadatası veritabanında YOKTUR.** | `ensure_dimensions()` → `engine.probe()` → yalnız PIL (`engine.py:79-93`); PIL video açmaz → `{}`. `th_media_width`/`th_media_height` video satırlarında boş; süre alanı **hiç yok**. | Süre/oran/çözünürlük kuralı bugün **zorlanamaz** (Ç5). FR-133 bunun önkoşuludur. |
| **K-07** | **Pillow pinlenmemiştir.** | `requirements.txt` ve `pyproject.toml` ikisinde de Pillow geçmiyor; sürüm Frappe'nin bağımlılığından gelir. | Bu belgedeki DPI davranışı **Pillow 11.3.0** ile ölçüldü. Pillow'un JPEG yazıcısı DPI/JFIF davranışını değiştirdiyse §FR-030 tablosu üretimde farklı çıkar → §8.1 doğrulaması **zorunludur**. |
| **K-08** | **HEIC/AVIF eklentileri KURULU DEĞİLDİR.** | `pillow-heif` / `pillow-avif-plugin` ne `requirements.txt` ne `pyproject.toml` içinde (ikisi de okundu). | Çelişki: `upload_policy.py:57-60` `.avif` ve `.heic`'i "image" sayıp L0'dan **geçiriyor**; `seller_media.py:245-247` ikisini de WebP'ye çevirmeyi **hedefliyor**; ama `engine.SUPPORTED_FORMATS` (`engine.py:21`) ikisini de **içermiyor** → `optimize()` `unsupported_format` döner. `to_webp()` istisna atarsa `seller_media.py:294-300` onu **yakalıyor**, orijinal içerikle devam ediyor ve yalnız `log_error` yazıyor. **Sonuç:** eklenti yoksa bir HEIC ürün görseli sessizce `.heic` olarak kütüphaneye giriyor, ne WebP'ye çevriliyor ne optimize ediliyor ve HEIC'i çözemeyen tarayıcılarda **hiç görünmüyor**; kullanıcıya hiçbir uyarı gitmiyor. Politika bu yüzden `accept.mime`'a almadı ve açık ret mesajı (`format_not_supported`) öneriyor. Eklenti kuruluysa karar **tersine döner** (§8.15). |
| **K-09** | **`pytesseract` / `tesseract-ocr` KURULU DEĞİLDİR.** | Ne `pyproject.toml` (`dependencies = ["defusedxml>=0.7", "scikit-learn>=1.3"]`) ne `requirements.txt` içinde. | `overlay_text` kuralının **yedek yolu kapalıdır**; yalnız mevcut Vision `text_detected` yoluyla çalışabilir — ve o yol bugün **yalnız `Listing Review Image`'da** tetikleniyor (FR-052). |
| **K-10** | **`numpy` yalnız dolaylı bir bağımlılıktır.** | `requirements.txt:3` `scikit-learn>=1.3` üzerinden. Pillow da doğrudan bağımlılık değil — `media/engine.py` kullanıyor ama `pyproject.toml` listesinde yok, **Frappe ile geldiği varsayılıyor**. | Kalibrasyon betiği (`scripts/calibrate_content_rules.py`) numpy/Pillow yokluğunda `ImportError` ile ölmez; ne kurulacağını yazıp **çıkış kodu 3** döner. Doğrulama §8.16. |
| **K-11** | **Bu çalışmada mevcut kod dosyaları DEĞİŞTİRİLMEZ.** | T-020…T-029 görev kuralı 1. Her standart belgesinin son bölümü ("Değiştirilmeyenler" / "Bu belgenin YAPMADIKLARI") bunu tekrar ediyor. | `HATALI`/`YOK` işaretli her gereksinim **uygulama görevidir**, bu belgenin çıktısı değil. Bu SRS yalnız yeni dosya üretti. |
| **K-12** | **Frappe `File` doctype'ının iç sırası doğrulanamamıştır.** | `find / -name "file.py" -path "*core/doctype/file*"` → **0 sonuç** (frappe Docker imajının içinde, Docker kapalı). | `before_insert` hook'unun Frappe'nin kendi disk yazma adımından önce mi sonra mı koştuğu **doğrulanmadı**. Sonuç iki durumda da aynıdır: kotayı aşan yükleme **diske yazıldıktan sonra** reddediliyor (FR-072). Transaction rollback `File` **kaydını** geri alır ama `os.write`'ı geri almaz; Frappe'nin `on_rollback` temizliği yapıp yapmadığı da doğrulanmadı → **yetim dosya** (§8.17). |
| **K-13** | **`tr_tradehub` ayrı bir app'tir ve bu worktree'de yoktur.** | `pages/seller-shop.ts:118-119` `seller?.header_bg_image` okuyor; `grep -rn header_bg_image tradehub_core/` → **0 sonuç**. `StorefrontEdit.vue:1223` `tr_tradehub.api.v1.seller.update_storefront` çağırıyor; `factory_video_url` `tradehub_core/**/*.py`, doctype JSON'ları ve `tradehubfront/src/**` içinde **0 eşleşme**. | İki slot alanı **sahipsizdir**: satıcı panelden bir kapak videosu yükleyip kaydediyor, storefront o alanı **hiç okumuyor** (Ç2) — panelin gösterdiği kapak ile vitrinin gösterdiği kapak **aynı dosya değil**. Karar: kanonik slot `seller.cover_video` (`Seller Gallery Image` yolu); `factory_video_url` bir **alias**, yeni yükleme kabul etmez, mevcut değeri taşınır. `header_bg_image` **hiçbir doctype'ta yoksa ölü koddur** ve politikadan çıkarılmalıdır (§8.18). |
| **K-14** | **Platform 4 dil taşır ve `ar` RTL'dir.** | `tradehubfront/src/i18n/locales/{tr,en,ar,ru}.ts`; `admin-panel/frontend/src/i18n/locales/{tr,en,ar,ru}.js`; RTL listesi `ar`'ı içeriyor (`i18n/index.ts`). | Her mesaj 4 dilde yazılmalıdır (FR-062). İki farklı interpolasyon sözdizimi (FR-067). Sayı yönü sarmalayıcısı **yok** (FR-069). `(piksel korundu)` ibaresi **çeviri kısaltmasına kurban edilemez** (FR-065). |
| **K-15** | **Tailwind kırılım noktaları EZİLMİŞTİR.** | `tradehubfront/src/style.css:256-260`: `sm=480`, `md=640`, `lg=768`, `xl=1024` — **Tailwind varsayılanı değil**. | Bu belgedeki **tüm** CSS kutu ölçüleri bu ölçekle hesaplanmıştır. Tailwind varsayılanıyla hesap yapılırsa **tüm geometri tabloları yanlış çıkar**. Not: `company-cover-video.md` §0 kendi hesabını Tailwind **varsayılan** ölçeğiyle (`sm 640 / md 768 / lg 1024 / xl 1280`) yaptığını beyan ediyor — o belgenin §2.2 tablosu bu yüzden diğerlerinden farklı bir tabana dayanır ve §8.19'da doğrulanmalıdır. |
| **K-16** | **Desteklenen DPR aralığı 1, 2, 3'tür. DPR 4 desteklenmez.** | `capacitor.config.ts:22` `appId: 'com.istoc.app'` (iOS+Android hedefi); modern iPhone ekranları DPR 3. Gerekçe: DPR 4'ün piyasada anlamlı payı olan cihazı yok ve her rung'ı 1,78× büyütürdü. | Tüm profil genişlikleri `kutu × DPR ∈ {1,2,3}` hesabından türetilir (FR-034). |
| **K-17** | **nginx `Content-Type`'ı dosya uzantısından türetir.** | `company-cover-video.md` Ç1. | Yerinde biçim değiştirme (`.mp4` adresine WebM yazma) **MIME'ı yalanlar** → FR-041 bunu kapak slotunda yasaklar. Uzantısı yanlış dosyalar da risklidir: `icons/*.webp` dosyalarının **7'si de gerçekte PNG** (`file` çıktısı; baytları `public/icons/*.png` ile özdeş: 27128 = 27128) — F8. |
| **K-18** | **Docker kapalı; üretim veritabanı ve canlı siteye erişim yok.** | §0.2. | Bu belgede **hiçbir** üretim ölçümü yoktur. §8 bunun tam listesidir. `jsonschema` bu Python kurulumunda da yok (T9). |
| **K-19** | **Politika dosyaları 4 ayrı yerde ve 3 farklı biçimdedir.** | T3, T6. | Kayıt defteri yazılmadan önce **tek biçime indirilmelidir** (FR-002); aksi hâlde politikaları okuyacak kod her dosya için **ayrı ayrıştırıcı** yazmak zorunda kalır. En küçük müdahale: şemada tanımlı olmayan alanların `notes[]`/`open_questions[]` içine taşınması **ya da** şemanın v1.1'de o alanları tanımlaması. |
| **K-20** | **`srcset` bugün eklenirse görseller kırılır.** | `tradehubfront/src/utils/mediaUrl.ts:76` `MutationObserver` `attributeFilter` = `["src","style"]`. | FR-122, FR-121'in **kod düzeyinde önkoşuludur**. |
| **K-21** | **`slot-policy.schema.json` v1.0.0 video ve belge biçimlerini ifade edemez.** | `profiles[].formats` enum'u `avif\|webp\|jpeg\|png` (`:300`); `master.format` enum'unda `webm` yok (`:216`). | `product-video.json` bu yüzden `master.format = "preserve"` yazmak zorunda kaldı ve gerçek rendition (1280 genişlik, VP9+Opus, WebM kabı — `transcode.py:243-246`) politikada **ifade edilemedi**. Şema v1.1'de `profiles[].formats` + `master.format` enum'larına video biçimleri ve `profiles[].codec` alanı eklenmelidir. Bu, T8'dir ve FR-002'nin bir parçasıdır. |
| **K-22** | **`.vtt` uzantısı yükleme politikasında tanımlı değildir.** | `upload_policy.EXTENSIONS` (`upload_policy.py:57-65`) içinde `.vtt` **yok**. | FR-125 yeni bir tür (`KIND_CAPTION`, tavan 512 KB) eklenmesini gerektirir — `KIND_DOCUMENT`'a **sokulmamalıdır** (belge tavanı 50 MB, altyazı için anlamsız). |

### 5.2 Kısıtların gereksinimler üzerindeki bağımlılık zinciri

```
K-05 (slot kimliği yok)  ──►  FR-001, FR-002
                                  │
                                  ├──►  FR-015…FR-027   (L3 geometri kapısı)
                                  ├──►  FR-117           (slot başına is_private)
                                  └──►  FR-119 (SVG-1)   (slot kapsamlı SVG açılışı)

K-04 (türev yok)  ──►  FR-034, FR-035, FR-036, FR-037, FR-038
                            │
                            ├──►  K-20 ──►  FR-122  ──►  FR-121 (srcset)
                            └──►  NFR-010 (master 2400 ancak bundan SONRA)

K-06 (video ölçüsü yok)  ──►  FR-133  ──►  FR-134 (süre kuralı)
                                       └──►  FR-075 metrik 4 (video süresi kotası)

K-02 (S3 yok)  ──►  FR-105 (not_implemented hedefi reddet)
K-13 (tr_tradehub)  ──►  FR-006 (bound_to doğrulaması)  ──►  §8.18
K-21 (şema v1.0.0)  ──►  FR-002 (şema v1.1)
```

---

## 6. Kabul kriterleri

### 6.1 Faz 2 (bu çalışma) — kapanış kriterleri

| # | Kriter | Durum | Kanıt |
|---|---|---|---|
| 1 | 9 slot için insan-okur standart belgesi yazıldı | ✅ | `docs/standards/*.md` 12 dosya + README |
| 2 | Her slot için makine-okunur politika yazıldı | ✅ | `tradehub_core/media/pipeline/policy/slots/*.json` 9 dosya |
| 3 | Politika şeması yazıldı ve JSON Schema draft 2020-12 olarak geçerli | ✅ | `slot-policy.schema.json`; `product-image.md` §2 doğrulama koşumu |
| 4 | Her politikada `sources` bloğu dolu, hiçbir sayı kaynaksız değil | ✅ | Şema `provenance` zorunlu; 19–30 kaynak/politika |
| 5 | Kota politikası şeması yazıldı | ✅ | `quota.schema.json` (8 zorunlu kök alan) |
| 6 | Saklama politikası şeması yazıldı | ✅ | `retention.schema.json` (5 zorunlu kök alan) |
| 7 | İçerik kuralları politikası + kalibrasyon betiği yazıldı | ✅ | `content_rules.json` (9 kural) + `scripts/calibrate_content_rules.py` (891 satır) |
| 8 | DPI/çözünürlük standardı + testi yazıldı | ✅ | `dpi-ve-cozunurluk.md` + `tests/test_policy_dpi.py` (19 test, 1 bilinçli `expectedFailure`) |
| 9 | Migration planı yazıldı | ✅ | `docs/plans/migration.md` |
| 10 | SRS yazıldı | ✅ | bu belge |
| 11 | **Tüm politikalar tek şemaya uyuyor** | ✅ **(rev2)** | **T3 KAPANDI** — jsonschema 4.25.1 ile 9/9 uyumlu, 0 hata (§0.3-B) |
| 12 | **Politikalar `active`** | ❌ | **T1** — **0/9**, 9'u da `draft` (yeniden ölçüldü 2026-08-18) |
| 13 | **Açık sorular kapatıldı** | ❌ | **T2** — **55** açık soru (51'den **arttı**) |
| 14 | **Platform yöneticisi kararları onaylandı** | ❌ | **T7** — **14 karar**, **2'si ölçümle çözüldü** (logo K1, K2) → **12 açık** |
| 15 | **Eşikler kalibre edildi** | ❌ | **T4** — `UNCALIBRATED`, 9/9 kural "KALİBRE EDİLMEDİ" (değişmedi) |
| 16 | **Kanonik politika kayıt yeri seçildi** | ❌ | **T6** — 4 yer; **bedeli ölçüldü**: aynı alana 8 kat farklı eşik (FR-147) |
| **17** | **Şema video/belge biçimini ifade edebiliyor** | ✅ **(rev2)** | **T8 KAPANDI** — `master.format` enum'unda `webm`/`mp4` var; `product-video.json` `master.format="webm"`, `video.renditions[]` gerçek codec/CRF taşıyor |
| **18** | **Doğrulama betiği koşabiliyor** | ❌ **(rev2, YENİ)** | **T10** — `README.md` §6 betiği `KeyError` ile çöküyor; düzeltilmiş varyantla 6 hata, çıkış kodu 1 (FR-148) |
| **19** | **Politikalar gerçek veriye uygulandı ve uyum oranı ölçüldü** | ✅ **(rev2)** | `09-slot-bazinda-istatistik.md` — 9 slot × 3.239 eşsiz URL; her slotun ihlal sayısı ve nedeni yazılı |

**Faz 2, 19 kriterin 12'siyle kapanmıştır** (rev1'de 10/16 idi; rev2'de T3 ve T8
kapandı, 3 yeni kriter eklendi — 19 numaralı yeni kriter ✅, 18 numaralı ❌).
Kalan **7** kriter §6.7'deki geçiş kapısıdır.

> **Neden kriter sayısı arttı?** §9.3 "kabul kriterinin **düşürülmesi**" için CR
> ister; **eklenmesi** için istemez. 17, 18 ve 19 numaralı kriterler mevcut hiçbir
> kriteri gevşetmiyor, ölçülen üç yeni gerçeği kayda geçiriyor.

### 6.2 Faz 3 — L3 doğrulayıcı ve türev üretimi

Aşağıdakiler tamamlanmadan hiçbir slot politikası `active` yapılamaz.

- [ ] `upload_policy.check()` `slot_key` parametresi alıyor (FR-001) — **K-05'i kapatır**
- [ ] Slot kayıt defteri politika JSON'larını okuyor; 9 dosyanın 9'u tek şemaya uyuyor (FR-002, FR-003)
- [ ] `bound_to` alanlarının varlığı Frappe metadata sorgusuyla doğrulanıyor (FR-006)
- [ ] Efektif bayt tavanı `min(slot, politika, frappe)` (FR-007)
- [ ] `max_megapixels_hard` kontrolü, görsel **tamamı açılmadan** uygulanıyor (FR-011)
- [ ] **(rev2)** `max_megapixels_hard` eşiği bellek bütçesinden türetilmiş ve gerçek kütüphaneyi kesiyor (FR-143) — bugünkü 80 MP **0 dosya** reddediyor
- [ ] **(rev2)** `max_megapixels_hard` alanı **9/9** politikada mevcut (FR-144) — bugün 7/9
- [ ] **(rev2)** CMYK → sRGB dönüşümü optimizasyon kapılarından bağımsız çalışıyor (FR-145) — 38 dosya
- [ ] **(rev2)** Alfa taşıyan master alfasız biçime düşürülmüyor (FR-146) — 597 dosya
- [ ] **(rev2)** Her `active` politika `compliance_measured` karnesi taşıyor (FR-149)
- [ ] **(rev2)** Harici URL bir ihlal olarak raporlanıyor (FR-150) — 719 referans
- [ ] Geometri kapısı `>=` ile, oran kontrolü **bağıl** tolerans ile çalışıyor (FR-015, FR-016)
- [ ] Politika yükleyici tolerans bantlarının çakışmadığını doğruluyor (FR-017)
- [ ] Adet kuralı uygulanıyor (FR-018)
- [ ] `ffprobe` tabanlı video ölçü/süre yazımı + `th_media_duration_ms` alanı (FR-133) — **K-06'yı kapatır**
- [ ] Kodlu ret sözleşmesi `identity.py` ve `kyb.py` dâhil **tüm** uçlarda (FR-061)
- [ ] Türev merdiveni üretiliyor; her profil `derived_from` taşıyor (FR-034, FR-035) — **K-04'ü kapatır**
- [ ] Logo türevleri **kayıpsız** (FR-038); logo master'ı 1:1 saydam letterbox (FR-020)
- [ ] `optimization` yanıt bloğu döndürülüyor (FR-064)
- [ ] Kullanıcı mesajları 4 dilde, doğru interpolasyonla (FR-062, FR-067) ve `(piksel korundu)` ibaresiyle (FR-065)

### 6.3 Faz 3 — kota ve rate limit

- [ ] `RATE_LIMITED = Kod("upload_rate_limited", True)` eklendi (FR-088) — **1. adım, davranış değişmez**
- [ ] `rate_limit.py` `INCR`+`EXPIRE`'a geçti (FR-083) → kalıcı kilit hatası da düzeldi (FR-084)
- [ ] `Retry-After` (kalan TTL) + `X-RateLimit-*` başlıkları (FR-087)
- [ ] Medya uçlarına decorator eklendi; ilk sürüm cömert değerlerle (FR-082)
- [ ] Misafir kovası IP'ye bağlandı — **ancak** nginx `X-Forwarded-For` zinciri doğrulandıktan sonra (FR-085, FR-086, §8.20)
- [ ] Kota kontrolü `doc.insert()` öncesine taşındı; `before_insert` kapısı **güvenlik ağı olarak kaldı** (FR-072)
- [ ] Eşzamanlılık koruması (`reservation`) devrede (FR-073)
- [ ] Bulk import ön-kontrolü (FR-078)
- [ ] Yeni metrikler `notify_only` ile açıldı (FR-075, FR-077)

> **Sıra bağlayıcıdır:** FR-085 (IP kovası) **FR-083'ten sonra** gelmelidir; bugünkü
> TTL-reset hatasıyla IP bazlı kova tek IP arkasındaki tüm kurumsal kullanıcıları
> **kalıcı kilitleyebilir**.

### 6.4 Faz 3 — saklama ve legal hold

- [ ] `th_legal_hold` custom alanı (yeni yama, `v15_9_13_media_trash_field.py` deseninde) — tek başına hiçbir davranışı değiştirmez
- [ ] `_assert_trashable`'a **altıncı kapı**, `force` ile aşılamaz grupta (FR-100)
- [ ] `purge_expired`'a legal hold kontrolü — **toplu ön-yükleme ile** (aksi hâlde döngüye N sorgu eklenir)
- [ ] Konfigürasyon okuyucusu; `retention_days` parametreleri `hooks.py` çağrı yerlerine geçiyor (FR-099)
- [ ] `orphan_reconciliation` görevi `weekly_long` bloğunda (FR-107)
- [ ] `LIVE_SOURCES` tamamlandı (FR-096)

> **Sıra bağlayıcıdır:** legal hold (FR-100) **konfigürasyondan (FR-099) önce**
> gelmelidir; aksi hâlde süreleri kısaltmak legal hold korumasından **önce**
> mümkün olur.

### 6.5 Faz 3+ — içerik kuralları

- [ ] Korpus örneklendi ve **el ile etiketlendi** (≥300 görsel, kural başına ≥30/sınıf, riskli kategoriler temsilli) (FR-141)
- [ ] Kalibrasyon betiği koştu; her kuralda `threshold_status` "kalibre: …" oldu (FR-142)
- [ ] Stage 0 (gölge, ≥14 gün) tamamlandı; her kuralda FP < %5 (RED kurallarında < %1) (FR-057)
- [ ] Moderatör rolü + `manual_review` kuyruğu devrede (FR-053, §2.3)
- [ ] Moderasyon kapsamı `Listing Image` ve `Seller Gallery Image`'a genişledi (FR-052)
- [ ] Skorlar eşiklendi (FR-051); moderasyon asenkron (FR-055); fail-open alarma bağlandı (FR-054)
- [ ] Kategori muafiyet listesi **gerçek** `Product Category` adlarıyla değiştirildi (FR-056, §8.5)
- [ ] Stage 1 çıkış koşulu ölçüldü: moderatör ↔ otomatik karar uyumu > %95

### 6.6 Faz 3+ — render ve srcset

- [ ] `mediaUrl.ts:76` `attributeFilter` `srcset`'i kapsıyor (FR-122) — **K-20'yi kapatır**
- [ ] `renderGalleryMedia` `srcset`/`sizes` üretiyor (FR-121)
- [ ] Master tavanı 2400'e çıkarıldı — **yalnız türev üretimi bittikten sonra** (NFR-010)
- [ ] Üç noktadaki 1920 → 2000 hizalandı (`engine.py:177`, `compress.image.ts:10`, `compress.image.js:9`) → `TestUploadYoluTabaniKarsilamiyor` **unexpected success** verir (NFR-047)
- [ ] `.webp` giriş yoluna uzun kenar tavanı uygulandı (NFR-048)
- [ ] Kapak videosu rendition'ları ayrı adreslere yazılıyor; yerinde değiştirme kapak slotunda yasak (FR-041) — **K-17'yi kapatır**
- [ ] Otomatik poster + 6 s önizleme klibi üretiliyor (FR-042, FR-043)
- [ ] `subtitles_vtt` alanı + `<track>` + altyazı düğmesi + `KIND_CAPTION` (FR-125) — **K-22'yi kapatır**
- [ ] `prefers-reduced-motion` JS kapısı (FR-126); seek çubuğu klavye + `aria-label` dinamik + 3 etiket i18n + iOS `webkitEnterFullscreen` (FR-128)
- [ ] Skeleton `aspect-video`'ya çevrildi (FR-124, Ç6)

### 6.7 TASLAK → v1.0 ONAYLI geçiş kapısı

Bu SRS aşağıdaki **altı** koşul karşılandığında `v1.0 ONAYLI` olur. Koşullar
§0.3'teki T1–T9 maddeleriyle birebir eşleşir.

| # | Koşul | Kapatılan madde | Doğrulama |
|---|---|---|---|
| **G1** | `tradehub_core/media/pipeline/policy/slots/*.json` dosyalarının **tamamı** `slot-policy.schema.json` ile 0 hatayla doğrulanıyor; `docs/standards/policies/` ile hangisinin kanonik olduğu karara bağlanmış | T3, T6, T9, T10 | `pip install jsonschema` + `README.md` §6 betiği, çıkış kodu **0** |
| **G2** | Şema **v1.1**'e çıkmış ve video/belge biçimlerini ifade ediyor (`profiles[].formats` + `master.format` enum'ları + `profiles[].codec`) | T8, K-21 | `product-video.json` `master.format` artık `"preserve"` değil, gerçek rendition yazılı |
| **G3** | **Açık soruların** her biri ya kapatılmış ya bir change request numarasına bağlanmış | T2 | `sum(len(d["open_questions"]))` = **0** ya da her madde bir CR-ID taşıyor |
| **G4** | **Platform yöneticisi kararları** (logo K1–K6, kapak videosu K1–K8) onaylanmış ve karar belgeye işlenmiş | T7 | `logo.md` §13 ve `company-cover-video.md` §10 her maddede "ONAY: …" ya da "ÖLÇÜMLE ÇÖZÜLDÜ" satırı taşıyor |
| **G5** | İçerik kuralı eşikleri kalibre edilmiş; `calibration_status != "UNCALIBRATED"` | T4 | `content_rules.json` her kuralda `threshold_status` "kalibre: <tarih>, korpus n=<N>, FP=<oran>" |
| **G6** | En az bir slot politikası `status: "active"` (yani `open_questions` boş **ve** hiçbir `encoder_quality` `null` değil) | T1, T5 | `README.md` §6 betiğinde D4 kontrolü 0 hata |
| **G7** *(rev2, yeni)* | Piksel tavanı **işlevsel**: `accept.max_megapixels_hard` her görsel slotunda **var** ve bugünkü kütüphaneyi kesiyor | FR-143, FR-144 | 9/9 politikada alan mevcut; eşik `sources` bloğunda bellek bütçesiyle türetilmiş |

#### 6.7-B Kapıların 2026-08-18 durumu — YENİDEN ÖLÇÜLDÜ

| Kapı | Durum | Ölçülen kanıt | Eksik olan tam olarak ne |
|---|---|---|---|
| **G1** | 🟡 **KISMEN** | Şema doğrulaması **9/9, 0 hata** (T3, T9 kapandı). Ama `README.md` §6 betiği **çıkış kodu 1** veriyor — `KeyError` ile çöküyor (T10) ve kanonik set kararı **yok** (T6) | (a) betiğin `master.max_megapixels` eksiğini `KeyError` yerine hata sayması + iki logo politikasına alanın eklenmesi; (b) `content_rules[animated].message_key` → `format_animated` düzeltmesi (2 dosya); (c) D5 politika↔belge eşleme kontrolünün düzeltilmesi; (d) **`tradehub_core/media/pipeline/policy/slots/` mi `docs/standards/policies/` mi kanonik — bu karar yazılı değil** |
| **G2** | ✅ **GEÇTİ** | `master.format` enum = `webp/avif/jpeg/png/webm/mp4/preserve`; ayrı video profil enum'u `webm/mp4`; `product-video.json` `master.format = "webm"`, `video.renditions[0]` = `product_1280_webm` / `libvpx-vp9` / CRF 32 / `libopus`; `company-cover-video.json` `cover_720_webm` maxrate 2500 kbps | — |
| **G3** | ❌ **AÇIK — GERİLEDİ** | `open_questions` toplamı **55** (rev1'de 51). Dağılım: `company-cover-video` **8** (+7 `pending_admin_decisions`), `product-image` 7, `category-banner`/`company-cover-image`/`document-attachment`/`product-video`/`user-avatar` 6'şar, `brand-logo`/`seller-logo` 5'er | **55 maddenin 55'i** — hiçbiri kapatılmadı, hiçbirine CR-ID bağlanmadı. Logo'larda 7→5 düşüş K1/K2'nin çözülmesinden; kapak videosunda 0→8 artış ölçümün yeni sorular doğurmasından |
| **G4** | 🟡 **2/14** | Logo **K1** (JPEG: ret→uyarı) ve **K2** (oran bandı 1:2…2:1 korundu) **ölçümle çözüldü** ve politikalara işlendi — doğrulandı: `seller-logo.json` `require.alpha_channel="optional"`, `content_rules[no_alpha_channel].action="warn"` | **12 karar açık:** logo K3 (merdiven rung sayısı — türev üretimi olmadan ölçülemez), K4, K5, K6; kapak videosu K1–K8. Kapak videosu **K8 yeni doğdu** (mevcut içerik için geçiş penceresi) — yani açık karar sayısı 13→12'ye yalnız 1 net indi |
| **G5** | ❌ **AÇIK — DEĞİŞMEDİ** | `content_rules.json` `calibration_status = "UNCALIBRATED"`; 9 kuralın 8'i "KALİBRE EDİLMEDİ — başlangıç değeri", 1'i "KALİBRE EDİLMEZ — ürün kararı"; `not_measured.items` = 6 | Etiketli korpus (≥300 görsel, kural başına ≥30/sınıf) **yok**; `scripts/calibrate_content_rules.py` **koşmadı**. Bu kapı ölçüm değil **veri etiketleme** işi ister |
| **G6** | ❌ **AÇIK — 0/9** | 9 politikanın **9'u** `status: "draft"`. `encoder_quality` null: **14** toplam, ama **5 politikada 0** (`brand-logo`, `seller-logo`, `company-cover-video`, `document-attachment`, `user-avatar`) | Tek engel bu 5 politikada **`open_questions`**: 5, 5, 8, 6, 6 madde. G6'ya en yakın: `brand-logo` / `seller-logo` (5'er soru, 0 null, şema uyumlu) |
| **G7** | ❌ **AÇIK — YENİ** | `max_megapixels_hard = 80` bugünkü **0 dosyayı** reddediyor (max 72,71 MP); `seller-logo.json` ve `brand-logo.json`'da alan **hiç yok** | Eşiğin bellek bütçesinden türetilmesi (FR-143, öneri 40 MP) + iki logo politikasına alanın eklenmesi (FR-144) + şemada alanın zorunlu yapılması |

**SONUÇ: 7 kapının 1'i geçti (G2), 2'si kısmen (G1, G4), 4'ü açık
(G3, G5, G6, G7). SRS `v1.0 ONAYLI` OLAMAZ — HÂLÂ TASLAK.**

**Kapıları geçmek için gereken iş — büyükten küçüğe, ölçülmüş büyüklükle:**

| # | İş | Büyüklük (ölçüldü) | Kapı |
|---|---|---|---|
| 1 | İçerik kuralı korpusunu etiketle ve kalibrasyonu koştur | ≥300 görsel el etiketi, 9 kural | G5 |
| 2 | 55 açık soruyu kapat ya da CR'a bağla | 55 madde, 9 dosya | G3, G6 |
| 3 | 12 yönetici kararını onaya çıkar | 12 karar, 2 belge | G4 |
| 4 | Kanonik politika setini ilan et | 2 set, 22 dosya; 8 kat eşik farkı | G1 |
| 5 | Doğrulama betiğini onar (4 gerçek hata + 2 yanlış pozitif) | 1 betik, 2 politika dosyası | G1 |
| 6 | Piksel tavanını bellek bütçesinden türet, 2 logo politikasına ekle | 2 dosya + 1 şema alanı | G7 |

> **1, 2 ve 3 numaralı işler bu oturumda kapatılamazdı**: birincisi insan
> etiketlemesi, ikincisi ve üçüncüsü **onay yetkisi** ister. 4, 5 ve 6 numaralı
> işler teknik olarak yapılabilirdi ama **politika ve kod değişikliği**
> demektir — bu turun kapsamı analiz + spesifikasyondur (§1.3, K-11).

**G1–G7 karşılanmadan hiçbir slot politikası üretimde zorlanmamalıdır.**
Bugünkü `draft` durumu bir kusur değil, **bilinçli bir frendir**: kalibre edilmemiş
eşikle RED üretmek satıcı kaybettirir (FR-057).

---

## 7. İzlenebilirlik matrisi

**Kolonlar.** *Slot politikası* = gereksinimi taşıyan makine-okunur dosya(lar).
*Değişmez / bulgu* = gereksinimi doğuran invariant ya da ölçülmüş eksik
(I=invariant, D=doğrulama betiği kontrolü, B=sistem çapında eksik, E=slot eksiği,
F=logo bulgusu, Ç=kapak videosu çelişkisi, A=DPI açığı, T=SRS TASLAK gerekçesi,
K=kısıt, SVG=SVG ön koşulu). *Faz* = F1 (Faz 1'de teslim edildi) · F2 (bu
çalışma — belge/politika) · F3 (uygulama) · F3+ (sonraki). *Test* = mevcut test
dosyası ya da **YOK → yazılmalı**.

Faz numaraları bu worktree'deki belgelerde geçen değerlerden alınmıştır
(`company-cover-video.md` §12 "Faz 3+", `retention.md` §8, `product-video.md`
§1 "Faz 3 görevi"). **Kaynak tasarım dokümanının 15 fazlı numaralandırmasıyla
birebir eşleştirme yapılmadı** — o liste bu worktree'de yok.

### 7.1 Fonksiyonel gereksinimler

| FR | Slot politikası / şema | Değişmez / bulgu | Faz | Test |
|---|---|---|---|---|
| FR-001 | tüm `slots/*.json` (`slot_key`) | **B1**, K-05 | F3 | **YOK** → `test_slot_registry.py` |
| FR-002 | `slot-policy.schema.json` | T3, T6, K-19 | F3 | **YOK** → `test_slot_registry.py` |
| FR-003 | — | T9 | F3 | `README.md` §6 betiği (CI'ya bağlanacak) |
| FR-004 | tüm `slots/*.json` (`sources`) | **D3**, `$defs.provenance` | **F2 ✅** | `test_policy_dpi.py::test_her_policy_gecerli_json_ve_zorunlu_alanlari_tasiyor` |
| FR-005 | tüm `slots/*.json` (`status`) | **D4**, T1, T5 | F3 | **YOK** → `test_slot_registry.py` |
| FR-006 | `slots/*.json` (`bound_to`) | **E2**, K-13 | F3 | **YOK** (Frappe metadata gerekir) |
| FR-007 | tüm `slots/*.json` (`accept.max_bytes`) | **I4** | F3 | **YOK** → `test_upload_policy_l3.py` |
| FR-008 | `accept.mime` ↔ `accept.extensions` | **I5** | F3 | **YOK** → `test_slot_registry.py` |
| FR-009 | `document-attachment.json` (`magic_byte_*`) | `document-attachment.md` §1 | F3 | **YOK** → `test_upload_policy_l3.py` |
| FR-010 | `document-attachment.json` (`docx_is_real_docx`) | `kyb.py:46-53` | F3 | **YOK** |
| FR-011 | tüm `slots/*.json` (`max_megapixels_hard`) | `product-image.md` §3.1 | F3 | **YOK** → `test_upload_policy_l3.py` |
| FR-012 | `user-avatar.json` (`is_animated`), `product-image.json` (`animated`) | `engine.py:111-112` | F3 | `test_engine_webp.py` (dolaylı) |
| FR-013 | `seller-logo.json`, `brand-logo.json` (`data_uri_value`) | **F14**, SVG-10 | F3 | **YOK** |
| FR-014 | `seller-logo.json`, `brand-logo.json` (`svg_policy.enabled=false`) | **SVG-1…SVG-10** | F3+ | **YOK** → `test_svg_sanitize.py` |
| FR-015 | tüm `slots/*.json` (`require.min_short_edge`, `min_area`) | **B2**, `slot-policy.schema.json:142` | F3 | `test_policy_dpi.py::test_min_long_edge_max_long_edge_i_asmaz` (kısmen) |
| FR-016 | tüm `slots/*.json` (`allowed_ratios`, `ratio_tolerance`) | **B2** | F3 | `test_policy_dpi.py::test_free_oranda_tolerans_null` (kısmen) |
| FR-017 | `product-image.json` | **I8** | F3 | **YOK** → `test_slot_registry.py` |
| FR-018 | `product-image.json` (`max_count:12`), `company-cover-image.json` (`max_count:5`) | §7-A | F3 | **YOK** |
| FR-019 | `seller-logo.json`, `brand-logo.json` (`alpha_channel: required`) | **F5**, `logo.md` §3.6 | F3 | `test_engine_webp.py::test_to_webp_seffaf_png_alfa_kanalini_korur` (kısmen) |
| FR-020 | `seller-logo.json`, `brand-logo.json` (`master.fit: pad`, `target_ratio: 1:1`) | **F4** | F3 | **YOK** → `test_derivatives.py` |
| FR-021 | `user-avatar.json` (`allowed_ratios:["1:1"]`, `on_violation.require: reject`) | `user-avatar.md` §3, §6 | F3 | **YOK** |
| FR-022 | `user-avatar.json` (`circle_inscribed_square_fraction: 0.707`) | `user-avatar.md` §3 | F3+ | **YOK** |
| FR-023 | `company-cover-image.json` (`safe_area_center_width_fraction`) | `company-cover-image.md` §3.3 | F3+ | **YOK** |
| FR-024 | `category-banner.json` (`safe_area_center_fraction`) | `category-banner.md` §3.3 | F3+ | **YOK** |
| FR-025 | `company-cover-video.json` (`safe_area`) | `company-cover-video.md` §3.1 | F3+ | **YOK** |
| FR-026 | `company-cover-video.json` (`cover_video_burned_logo_warning`) | `company-cover-video.md` §3.2 | F3+ | **YOK** |
| FR-027 | `document-attachment.json` (`on_violation.require: warn`) | `document-attachment.md` §5 | F3 | **YOK** |
| FR-028 | tüm `slots/*.json` (`master.allow_upscale:false`) | `engine.py:97,117` | **F1 ✅** | `test_policy_dpi.py::test_thumbnail_upscale_yapmaz`, `::test_zaten_tavanin_altindaki_dosya_buyumez`, `::test_dikdortgen_gorselde_yalniz_uzun_kenar_tavana_oturur` |
| FR-029 | `docs/standards/policies/*.json` (`dpi_policy.pixels_preserved`) | `dpi-ve-cozunurluk.md` §1 | **F2 ✅** | `test_policy_dpi.py::test_dpi_policy_pikselin_korundugunu_soyluyor`, `::test_dpi_dususu_pikseli_dusurmez` |
| FR-030 | tüm `slots/*.json` (`master.dpi_out`) | **A**, K-07 | F3 | `test_policy_dpi.py::test_optimize_ciktisinda_mutlak_dpi_metadatasi_yok`, `::test_to_webp_ciktisinda_dpi_alani_hic_yok` (mevcut durumu sabitliyor) |
| FR-031 | tüm `slots/*.json` (`master.max_long_edge`) | `presets.py:13-17`, `transcode.py:242` | **F2 ✅** | `test_policy_dpi.py::test_max_long_edge_preset_tavanini_asmiyor` |
| FR-032 | tüm `slots/*.json` (`master.max_megapixels`) | **I2**, **D4** | **F2 ✅** | `README.md` §6 betiği (D4) |
| FR-033 | tüm `slots/*.json` (`master.min_long_edge`) | `product-image.md` §3.3 | F3 | `test_policy_dpi.py::test_target_long_edge_min_max_araliginda` (kısmen) |
| FR-034 | tüm `slots/*.json` (`profiles[].derived_from`) | **I1**, **D2** | **F2 ✅** | `README.md` §6 betiği (D2) |
| FR-035 | tüm `slots/*.json` (`profiles[]`) | **D1**, K-04 | F3 | **YOK** → `test_derivatives.py` |
| FR-036 | `product-image.json` (7 profil) | `product-image.md` §6 | **F2 ✅** | — (tasarım kararı) |
| FR-037 | `product-image.json` (`fit: pad` / `contain`) | `product-image.md` §7 | F3 | **YOK** → `test_derivatives.py` |
| FR-038 | `seller-logo.json`, `brand-logo.json` (`master.encoding: lossless`) | **F5** | F3 | **YOK** → `test_derivatives.py` |
| FR-039 | tüm `slots/*.json` (`strip_metadata.gps:true`, `icc:false`) | `product-image.md` §3.3 | F3 | **YOK** → `test_metadata_strip.py` |
| FR-040 | — (`MEDYA-DEPOLAMA-STANDARDI.md` §5) | — | F3 | `test_media_naming.py` (9 test, isimlendirme+shard) |
| FR-041 | `company-cover-video.json` (`rendition_policy`) | **Ç1**, K-17 | F3+ | `test_media_transcode.py` (mevcut yerinde yazmayı bağlıyor — **değişecek**) |
| FR-042 | `company-cover-video.json` (`poster`) | **Ç7** | F3+ | **YOK** → `test_poster.py` |
| FR-043 | `company-cover-video.json` (`preview_clip`) | `company-cover-video.md` §6.11 | F3+ | **YOK** |
| FR-044 | `seller-logo.json`, `brand-logo.json` (`profiles[og1200x630]`) | **F13** | F3 | `seo/tests/test_og_image.py` (mevcut davranışı bağlıyor — **değişecek**) |
| FR-045 | `document-attachment.json` (`profiles[doc_thumb_512].private`) | `document-attachment.md` §4 | F3 | **YOK** |
| FR-046 | `content_rules.json` (`preprocessing`) | `icerik-kurallari.md` §3.0 | F3+ | **YOK** → `test_content_rules.py` |
| FR-047 | `content_rules.json` (`preprocessing.skip_if`) | `gates.py:28-37` | F3+ | **YOK** |
| FR-048 | `content_rules.json` (`decision_model.reject_allowed_rules`) | `icerik-kurallari.md` §2 | F3+ | **YOK** |
| FR-049 | `content_rules.json` (`decision_model.aggregation`) | — | F3+ | **YOK** |
| FR-050 | `content_rules.json` (`decision_model.reject_semantics`) | `moderation.py:172-173` | **F1 ✅** (yorum görselinde) | **YOK** |
| FR-051 | `content_rules.json` (`rules[nsfw_content].threshold`) | `icerik-kurallari.md` §1.2/2 | F3+ | **YOK** |
| FR-052 | `content_rules.json` | `icerik-kurallari.md` §1.2/1 | F3+ | **YOK** |
| FR-053 | `content_rules.json` | `icerik-kurallari.md` §1.2/3, §2.3 | F3+ | **YOK** |
| FR-054 | `content_rules.json` | `icerik-kurallari.md` §1.2/4 | F3+ | **YOK** |
| FR-055 | `content_rules.json` | `icerik-kurallari.md` §1.2/5 | F3+ | **YOK** |
| FR-056 | `content_rules.json` (`category_overrides`) | `icerik-kurallari.md` §3.7 | F3+ | **YOK** |
| FR-057 | `content_rules.json` (`rollout`) | `icerik-kurallari.md` §5 | F3+ | **YOK** |
| FR-058 | `content_rules.json` (`rules[min_image_count].message_tr`) | `icerik-kurallari.md` §3.9 | **F2 ✅** | **YOK** |
| FR-059 | `content_rules.json` (`rules[min_image_count]`) | `completeness.py:231-232` | F3+ | **YOK** |
| FR-060 | tüm `slots/*.json` (`on_violation.error_code_prefix`, `retryable`) | `upload_policy.py:104-139` | **F1 ✅** | **YOK** → `test_upload_policy.py` (mevcut değil) |
| FR-061 | `user-avatar.json`, `document-attachment.json` | **E9** | F3 | **YOK** |
| FR-062 | tüm `slots/*.json` (`messages.tr`) | **I6**, **D3** | **F2 ✅** | `README.md` §6 betiği (D3) |
| FR-063 | `product-image.json` (`messages.tr.short_edge_too_small`) | `product-image.md` §8.2 | **F2 ✅** | — |
| FR-064 | — | **A3** | F3 | **YOK** |
| FR-065 | — (i18n anahtarları `dpi-ve-cozunurluk.md` §7.2/§7.3) | `dpi-ve-cozunurluk.md` §7.1 | F3 | **YOK** |
| FR-066 | — | `dpi-ve-cozunurluk.md` §7.4 | F3 | **YOK** |
| FR-067 | — | K-14 | F3 | **YOK** → `seo/tests/test_i18n.py` deseni |
| FR-068 | — | `mediaFormat.js:7-22`, `MEDYA-TARIH-STANDARDI.md` | **F1 ✅** | **YOK** (panel testi) |
| FR-069 | — | K-14 | F3+ | **YOK** (görsel kontrol, §8.6) |
| FR-070 | `quota.schema.json` (`storage.total_gb`) | `kota.md` §1 | **F1 ✅** | `test_media_quota.py` (10 test), `test_media_pipeline_integration.py::test_dusuk_kotada_upload_reddedilir` |
| FR-071 | `quota.schema.json` (`exemptions.undefined_plan_limit_fails_open`) | `kota.md` §1.2 | **F1 ✅** | `test_media_quota.py::test_tanimsiz_kota_reddetmez` |
| FR-072 | `quota.schema.json` (`enforcement.check_point`) | `kota.md` §2, K-12 | F3 | **YOK** |
| FR-073 | `quota.schema.json` (`enforcement.concurrency_guard`) | `kota.md` §3 | F3 | **YOK** |
| FR-074 | `quota.schema.json` (`scope.*`) | `kota.md` §4.1, §4.3 | F3 | `test_media_quota.py::test_private_dosya_muaf`, `::test_klasor_muaf` |
| FR-075 | `quota.schema.json` (`uploads`, `jobs`, `video`, `file`) | `kota.md` §5 | F3+ | **YOK** |
| FR-076 | `quota.schema.json` (`file.max_bytes_per_kind.plan_overrides`) | `kota.md` §5.4 | F3+ | **YOK** |
| FR-077 | `quota.schema.json` (`on_exceed`) | `kota.md` §5.5 | F3+ | **YOK** |
| FR-078 | `quota.schema.json` (`bulk_import.precheck_total_bytes`) | `kota.md` §4.2 | F3+ | **YOK** |
| FR-079 | `quota.schema.json` (`exemptions.*`) | `kota.md` §4 | **F1 ✅** | `test_media_quota.py::test_kyb_dosyasi_kotadan_muaf`, `::test_system_manager_muaf`, `::test_magazasiz_oturum_muaf` |
| FR-080 | `quota.schema.json` (`observability`) | — | F3+ | **YOK** |
| FR-081 | `quota.schema.json` (`storage.total_gb.on_exceed`) | `upload_policy.py:120` | **F1 ✅** | `test_media_quota.py::test_kota_asiminda_upload_reddedilir`, `::test_tam_kota_sinirinda_reddedilir` |
| FR-082 | `quota.schema.json` (`rate_limit.media_endpoints`) | `kota.md` §6.7 | F3 | **YOK** → `test_rate_limit.py` |
| FR-083 | `quota.schema.json` (`rate_limit.atomic_counter`) | `kota.md` §6.4 | F3 | **YOK** → `test_rate_limit.py` |
| FR-084 | `quota.schema.json` (`rate_limit.algorithm`) | `kota.md` §6.3 | F3 | **YOK** |
| FR-085 | `quota.schema.json` (`rate_limit.guest_bucket.key_strategy`) | `kota.md` §6.2 | F3 | **YOK** |
| FR-086 | `quota.schema.json` (`guest_bucket.trusted_proxy_depth`) | `kota.md` §6.2, §10.7 | F3 | **YOK** (§8.20) |
| FR-087 | `quota.schema.json` (`rate_limit.response`) | `kota.md` §6.6, §7.3 | F3 | **YOK** |
| FR-088 | `quota.schema.json` (`rate_limit`) | `kota.md` §9 adım 1 | F3 | **YOK** |
| FR-089 | `quota.schema.json` (`rate_limit.media_endpoints` bayt kovası) | `kota.md` §7.2 | F3+ | **YOK** |
| FR-090 | `quota.schema.json` (`on_backend_failure`, `alert_on_backend_failure`) | `kota.md` §6.5 | F3 | **YOK** |
| FR-091 | `quota.schema.json` (`rate_limit.implementation_fragmentation`) | `kota.md` §6.1 | F3+ | **YOK** |
| FR-092 | `retention.schema.json` (`soft_delete.require_two_step`) | `trash.py:210-215` | **F1 ✅** | **YOK** → `test_trash_retention.py` |
| FR-093 | `retention.schema.json` (`soft_delete.scope_gates`) | `trash.py:64-108` | **F1 ✅** | **YOK** |
| FR-094 | `retention.schema.json` (`unused_definition`) | `usage.py:32-61`, `trash.py:34` | **F1 ✅** | `test_media_browse.py::test_kullanilmayan_yukleme_unused_klasorune_duser` (dolaylı) |
| FR-095 | `retention.schema.json` (`unused_definition.sources`) | `retention.md` §3.2 notu | F3 | **YOK** (§8.9) |
| FR-096 | `retention.schema.json` (`unused_definition.sources`) | **B6** | F3 | **YOK** |
| FR-097 | `retention.schema.json` (`grace_days_after_last_reference`) | `retention.md` §3.4 | F3+ | **YOK** |
| FR-098 | `retention.schema.json` (`frontend_scan_completed`) | `trash.py:10-13` | F3+ | **YOK** |
| FR-099 | `retention.schema.json` (`configurability.source`) | `retention.md` §5.1 | F3 | **YOK** |
| FR-100 | `retention.schema.json` (`legal_hold.*`) | `retention.md` §5.2 | F3 | **YOK** → `test_legal_hold.py` |
| FR-101 | `retention.schema.json` (`soft_delete.audit_required`, `audit_empty_runs`, `distinguish_manual_and_scheduled`) | `audit.py:43-68` | **F1 ✅** | **YOK** |
| FR-102 | `retention.schema.json` (`readonly_reference_tables`) | `refs.py:16-42` | **F1 ✅** | **YOK** |
| FR-103 | `retention.schema.json` (`original_retention.keep_forever`) | `retention.md` §6.1 | **F1 ✅** (fiilen) | **YOK** |
| FR-104 | `retention.schema.json` (`derivative_retention.pipeline_status`) | K-04 | **F2 ✅** (işaretlendi) | **YOK** |
| FR-105 | `retention.schema.json` (`storage_targets.*.implementation_status`) | K-02 | F3+ | **YOK** |
| FR-106 | `retention.schema.json` (`backup.on_backup_failure`) | `backup.py:390-419` | **F1 ✅** | **YOK** |
| FR-107 | `retention.schema.json` (`orphan_reconciliation`) | `retention.md` §5.5 | F3+ | **YOK** |
| FR-108 | `retention.schema.json` (`soft_delete`) | `hooks.py:127-138` | **F1 ✅** | **YOK** (§8.10) |
| FR-109 | — (`presets.py:44-53`) | `04-yetki-modeli.md` §6 | **F1 ✅** | `test_media_access_level.py` (**15 test**) |
| FR-110 | `document-attachment.json` (`kvkk_field_map_complete`) | **B5**, **E5** | F3 | **YOK** (§8.21) |
| FR-111 | `document-attachment.json` (`optimizer_excluded`) | **E4** | F3 | **YOK** (§8.22) |
| FR-112 | — (`media_access.py:102-141`) | `04-yetki-modeli.md` §7.2 | **F1 ✅** | `test_media_access.py` (**17 test**) |
| FR-113 | — (`media_access.py:48-50`) | `04-yetki-modeli.md` §7.3 | **F1 ✅** | `test_media_access.py::test_ttl_ust_sinira_clamp_edilir` |
| FR-114 | — (`media_access.py:144-202`) | `04-yetki-modeli.md` §7.4 | **F1 ✅** | `test_media_access.py` (4 ret-audit testi) |
| FR-115 | — (`ownership.py`, `api/seller_media.py`) | `04-yetki-modeli.md` §3 | **F1 ✅** | `test_media_browse.py::test_endpoint_kok_ve_yetki` (kısmen) |
| FR-116 | — (`media_admin.set_access_level`) | `MEDYA-ERISIM-MODELI.md` §4.2 | **F1 ✅** | `test_media_access_level.py::test_basarili_degisim_media_level_changed_yazar` |
| FR-117 | tüm `slots/*.json` (`content_rules[is_private]`) | **B8** | F3 | **YOK** |
| FR-118 | `product-video.json` (`content_rules[is_private]` → `warn`) | **E7** | F3 | `test_media_transcode.py::test_private_video_muaf` (mevcut **sessiz** davranışı bağlıyor) |
| FR-119 | `seller-logo.json`, `brand-logo.json` (`svg_policy`) | **SVG-1…SVG-10** | F3+ | **YOK** → `test_svg_sanitize.py` |
| FR-120 | `seller-logo.json`, `brand-logo.json` (`svg_policy.max_bytes`, `max_nodes`) | SVG-9 | F3+ | **YOK** |
| FR-121 | tüm `slots/*.json` (`profiles[].formats` sırası) | K-04, K-20 | F3+ | **YOK** |
| FR-122 | — (`mediaUrl.ts:76`) | K-20 | F3+ | **YOK** (frontend testi) |
| FR-123 | `product-image.json` (`profiles[].max_overshoot`) | `product-image.md` §1.3 | F3+ | **YOK** (§8.8) |
| FR-124 | — | **Ç6** | F3+ | **YOK** |
| FR-125 | `company-cover-video.json` (`accessibility`) | K-22 | F3+ | **YOK** |
| FR-126 | `company-cover-video.json` (`accessibility`, `modes`) | `company-cover-video.md` §8.2 | F3+ | **YOK** |
| FR-127 | `company-cover-video.json` (`playback_attributes`) | **Ç9** | F3+ | **YOK** |
| FR-128 | `company-cover-video.json` (`accessibility`) | `company-cover-video.md` §8.3 | F3+ | **YOK** |
| FR-129 | `company-cover-video.json` (`transcode`) | **Ç10** | F3+ | **YOK** |
| FR-130 | `company-cover-video.json` (`transcode`, `adaptive_streaming`) | **Ç11** | F3+ | **YOK** (§8.23) |
| FR-131 | `category-banner.json` (`bottom_third_text_overlap` → `ignore`) | `category-banner.md` §6 | **F2 ✅** | — |
| FR-132 | — | **E8** | **F2 ✅** (kayda geçti) | **YOK** (grep disiplini) |
| FR-133 | `company-cover-video.json` (`unmeasured_disclaimer`) | **Ç5**, K-06 | F3 | **YOK** |
| FR-134 | `product-video.json` (`duration_seconds`), `company-cover-video.json` (`modes`) | `product-video.md` §3 | F3 | **YOK** |
| FR-135 | `content_rules.json` (`observability.required_metrics_per_rule`) | `icerik-kurallari.md` §6 | F3+ | **YOK** |
| FR-136 | `content_rules.json` (`observability.log_target`) | `icerik-kurallari.md` §6 | F3+ | **YOK** |
| FR-137 | — (`docs/plans/migration.md` §5) | `migration.md` §5.1 | F3+ | **YOK** |
| FR-138 | tüm `slots/*.json` (`open_questions` — geriye dönük uygulama maddeleri) | `product-image.md` §9.1 | F3 | **YOK** (§8.24) |
| FR-139 | — (`migration.md` §7.1) | `migration.md` §4.6 | F3+ | `api/media_admin.py` restore uçları (mevcut) |
| FR-140 | — (`migration.md` §6) | `migration.md` §6.1 | F3+ | **YOK** |
| FR-141 | `content_rules.json` (`calibration_script`) | T4 | F3+ | `scripts/calibrate_content_rules.py` (**çalıştırılmadı**) |
| FR-142 | `content_rules.json` (`threshold_status`) | T4 | F3+ | **YOK** |
| **FR-143** | tüm görsel `slots/*.json` (`accept.max_megapixels_hard`) | **rev2 ölçümü §3.M.1** (80 MP → 0 dosya reddediyor; max 72,71 MP) | F3 | **YOK** → `test_upload_policy_l3.py::test_megapiksel_tavani_gercek_dosyayi_kesiyor` |
| **FR-144** | `seller-logo.json`, `brand-logo.json` (**alan YOK**); `slot-policy.schema.json` (`required`) | **rev2 bulgusu** — 2/9 politikada piksel tavanı yok | F2 → F3 | **YOK** → `test_slot_registry.py::test_her_gorsel_slotunda_piksel_tavani_var` |
| **FR-145** | tüm görsel `slots/*.json` (`master.colorspace: srgb`) | **38 CMYK dosya** (18'i ürün görseli); `gates.py:55-72` bypass | F3 | **YOK** → `test_engine_colorspace.py` |
| **FR-146** | tüm `slots/*.json` (`master.format` + alfa) | **597 alfalı dosya**; `document.attachment`'ta 32/56 | F3 | `test_engine_webp.py::test_to_webp_seffaf_png_alfa_kanalini_korur` (kısmen) |
| **FR-147** | `tradehub_core/media/pipeline/policy/slots/` ↔ `docs/standards/policies/` | **T6**; `09-…md` §6 (8 kat eşik farkı) | F2 (karar) → F3 | **YOK** → `test_slot_registry.py::test_tek_kanonik_kayit_yeri` |
| **FR-148** | `docs/standards/README.md` §6 betiği | **T10**; D3 ×2, D4 ×2, D5 ×2, çıkış kodu 1 | F2 | betiğin kendisi test yerine geçer (çıkış kodu **0** olmalı) |
| **FR-149** | tüm `slots/*.json` (**yeni blok** `compliance_measured`); `slot-policy.schema.json` | **FR-138**; `09-…md` §3 (9 slotun 8'i > %10 ihlal) | F2 → F3 | **YOK** → `test_slot_registry.py::test_active_politika_uyum_karnesi_tasiyor` |
| **FR-150** | tüm `slots/*.json` (`accept` — harici URL) | **719 harici referans**; `user.avatar` 6/6, `category.banner` 30/32 | F3 | **YOK** → `test_upload_policy_l3.py::test_harici_url_ihlal_olarak_raporlanir` |

### 7.2 Fonksiyonel olmayan gereksinimler

| NFR | Politika / şema | Değişmez / bulgu | Faz | Test |
|---|---|---|---|---|
| NFR-001 | `company-cover-video.json` (`mobile_data_budget`) | `company-cover-video.md` §6.7 | F3+ | **YOK** (§8.25) |
| NFR-002 | `company-cover-video.json` (`mobile_data_budget`) | — | F3+ | **YOK** (§8.25) |
| NFR-003 | `company-cover-video.json` (`renditions`) | — | F3+ | **YOK** |
| NFR-004 | `company-cover-video.json` (`rendition_policy`) | §10-K7 | F3+ | **YOK** |
| NFR-005 | `content_rules.json` (`preprocessing`) | `icerik-kurallari.md` §7.7 | F3+ | **YOK** (§8.7) |
| NFR-006 | `product-video.json`, `company-cover-video.json` (`transcode`) | `transcode.py:8-16,52,157` | **F1 ✅** | `test_media_transcode.py` (**22 test**) |
| NFR-007 | — (`chunked.py:43,47,51`) | `MEDYA-YUKLEME-SOZLESMESI.md` §4 | **F1 ✅** | `test_media_pipeline_integration.py` (kısmen) |
| NFR-008 | — (`lighthouserc.cjs:30-36`) | `03-render-envanteri.md` §7.1 | F3+ | **YOK** (§8.8) |
| NFR-009 | tüm `slots/*.json` (`profiles[]`) | `product-image.md` §5.5 | F3+ | **YOK** (§8.8) |
| NFR-010 | `product-image.json` (`master.max_long_edge:2400`) | **A1** | F3+ | `test_policy_dpi.py::TestUploadYoluTabaniKarsilamiyor` (`expectedFailure`) |
| NFR-011 | — (`gates.py`, `presets.py`) | `dpi-ve-cozunurluk.md` §2.2 | **F1 ✅** | `test_policy_dpi.py::test_zaten_tavanin_altindaki_dosya_buyumez` |
| NFR-012 | `user-avatar.json` (`optimizer_ran` → `review`) | **E3** | F3 | **YOK** (§8.3) |
| NFR-013 | `quota.schema.json` (`enforcement.cache_ttl_seconds`) | `entitlement/core.py:157` | F3+ | **YOK** |
| NFR-014 | — | `MEDYA-YUKLEME-SOZLESMESI.md` §2 | **F1 ✅** | — (sözleşme) |
| NFR-015 | — (`hooks.py:227-252`) | `MEDYA-YUKLEME-SOZLESMESI.md` §3 | **F1 ✅** | **YOK** → `test_upload_policy.py` |
| NFR-016 | — (`ownership.py`) | `04-yetki-modeli.md` §3 | **F1 ✅** | `test_media_browse.py` (14 test, kapsam/klasör izolasyonu) |
| NFR-017 | — (`media_admin.py:32,37`) | `04-yetki-modeli.md` §2 | **F1 ✅** | `test_media_access_level.py::test_yetkisiz_kullanici_reddedilir`, `::test_yetkisiz_kullanici_liste_alamaz` |
| NFR-018 | — | `MEDYA-ERISIM-MODELI.md` §2.2 | **F1 ✅** | `test_media_access.py` (dolaylı) |
| NFR-019 | — (`naming.py`) | `MEDYA-DEPOLAMA-STANDARDI.md` §4.1 | **F1 ✅** | `test_media_naming.py` (9 test) |
| NFR-020 | — (`media_access.py:66-76,189`) | `04-yetki-modeli.md` §7.4 | **F1 ✅** | `test_media_access.py::test_path_traversal_reddedilir`, `::test_path_traversal_download_da_reddedilir` |
| NFR-021 | — | `04-yetki-modeli.md` §7.1 | **F1 ✅** | `test_media_access.py::test_gecersiz_imza_reddedilir` |
| NFR-022 | `seller-logo.json`, `brand-logo.json` (`svg_policy`) | SVG-7 | F3+ | **YOK** |
| NFR-023 | — (`section-registry.ts`, `CategoryShowcase.ts`) | `company-cover-image.md` §7 | **F1 ✅** | **YOK** (frontend) |
| NFR-024 | `document-attachment.json` (`client_compression_disabled` → `reject`) | `document-attachment.md` §6/5 | **F1 ✅** | **YOK** |
| NFR-025 | — | `document-attachment.md` §7.6 | F3+ | **YOK** (§8.11) |
| NFR-026 | — | `04-yetki-modeli.md` §8-D | **kabul edilmiş sınır** | **YOK** |
| NFR-027 | — | `04-yetki-modeli.md` §8-B | F3+ | **YOK** (§8.12) |
| NFR-028 | `category-banner.json`, `company-cover-image.json` | `company-cover-image.md` §7 | **F1 ✅** | **YOK** (frontend) |
| NFR-029 | `category-banner.json` (`bottom_third_text_overlap`) | `category-banner.md` §7 | **F1 ✅** | — |
| NFR-030 | — (`section-registry.ts:185,188,212`) | `company-cover-image.md` §7 | **F1 ✅** | **YOK** |
| NFR-031 | `company-cover-video.json` | `company-cover-video.md` §3.2 | **F1 ✅** | **YOK** |
| NFR-032 | `user-avatar.json` | `user-avatar.md` §7/5 | **F1 ✅** | **YOK** |
| NFR-033 | tüm `slots/*.json` (`rendered_as_css_background` → `review`) | **B4** | F3+ | **YOK** |
| NFR-034 | `retention.schema.json`, `quota.schema.json` (audit alanları) | `audit.py:43-68` | **F1 ✅** | `test_audit.py`, `test_audit_hashchain.py` (mevcut, medya-özel değil) |
| NFR-035 | — | `04-yetki-modeli.md` §6.6 | **F1 ✅** | `test_media_access_level.py::test_gercek_adl_kaydinda_object_name_maskeli` |
| NFR-036 | `retention.schema.json` (`audit_empty_runs`) | `retention.md` §9.1 | F3 | **YOK** (§8.10) |
| NFR-037 | `content_rules.json` (`preprocessing.skip_if.note`) | `gates.py:28-37` | F3+ | **YOK** |
| NFR-038 | `quota.schema.json` (`audit_rate_limit_events`) | — | F3 | **YOK** |
| NFR-039 | `product-video.json`, `company-cover-video.json` | `transcode.py:48-50` | F3 | `test_media_transcode.py::test_run_transcode_hata_durumunda_failed_isaretler` |
| NFR-040 | `product-video.json` | `transcode.py:139-140` | **F1 ✅** | `test_media_transcode.py` (3 idempotanlık testi) |
| NFR-041 | `product-video.json` | `transcode.py:230,251` | **F1 ✅** | `test_media_transcode.py::test_run_transcode_ffmpeg_komutunu_dogru_argumanlarla_kurar_ve_ready_isaretler` |
| NFR-042 | — (`backup.py:79-84`, `restore.py:198`) | `product-video.md` §7/8 | **F1 ✅** | **YOK** |
| NFR-043 | `product-video.json` (`ffprobe_readable` → `review`) | `transcode.py:96-106` | **F1 ✅** | `test_media_transcode.py` (3 "güvenli taraf" testi) |
| NFR-044 | tüm `slots/*.json` (`master.format: preserve` yerlerinde) | `engine.py:8-9`, `transcode.py:29-31` | **F1 ✅** | `test_media_naming.py::test_file_doc_gorunen_ad_degismez` |
| NFR-045 | tüm `slots/*.json` (`accept.max_bytes` en sıkı değer) | **B7**, **Ç3**, **Ç4**, **A1**, **F17**, **F18** | F3 | `test_policy_dpi.py::test_max_long_edge_preset_tavanini_asmiyor` |
| NFR-046 | — (`api/seller.py:760-765`) | **Ç12** | F3+ | **YOK** |
| NFR-047 | `product-image.json` | **A1** | F3+ | `test_policy_dpi.py::TestUploadYoluTabaniKarsilamiyor` (`expectedFailure`), `test_engine_webp.py::test_to_webp_boyutu_1920_ile_sinirlar` |
| NFR-048 | `product-image.json` | **A2** | F3 | **YOK** (§8.26) |
| NFR-049 | `retention.schema.json` (`backup`) | `backup.py:390-419` | **F1 ✅** | **YOK** |
| NFR-050 | — (`naming.py`) | `MEDYA-DEPOLAMA-STANDARDI.md` §4.3 | **F1 ✅** | `test_media_naming.py::test_ayni_icerik_ayni_hash_farkli_ad_gizli`, `test_media_pipeline_integration.py::test_ayni_icerik_iki_kez_yuklenince_ayni_file_url_uretir` |
| NFR-051 | — | `MEDYA-DEPOLAMA-STANDARDI.md` §4.2 | **F1 ✅** | `test_media_naming.py::test_public_dosya_hash_isimli_yazilir_ve_url_doner` |
| NFR-052 | — | `MEDYA-TARIH-STANDARDI.md` §2 | **F1 ✅** | **YOK** (panel testi) |

### 7.3 Test kapsamı — ölçülen durum

`wc -l` ve `grep -c "def test_"` ile bu makinede sayıldı (2026-08-17):

| Test dosyası | Test sayısı | Neyi bağlıyor |
|---|---:|---|
| `tradehub_core/tests/test_media_transcode.py` | **22** | NFR-006, NFR-040, NFR-041, NFR-043, FR-118 |
| `tests/test_policy_dpi.py` | **19** (+1 bilinçli `expectedFailure`) | FR-004, FR-028…FR-033, NFR-010, NFR-011, NFR-045, NFR-047 |
| `tradehub_core/tests/test_media_access.py` | **17** | FR-112, FR-113, FR-114, NFR-020, NFR-021 |
| `tradehub_core/tests/test_media_access_level.py` | **15** | FR-109, FR-116, NFR-017, NFR-035 |
| `tradehub_core/tests/test_media_browse.py` | **14** | FR-094, FR-115, NFR-016 |
| `tradehub_core/tests/test_media_quota.py` | **10** | FR-070, FR-071, FR-074, FR-079, FR-081 |
| `tradehub_core/tests/test_media_naming.py` | **9** | FR-040, NFR-019, NFR-044, NFR-050, NFR-051 |
| `tradehub_core/tests/test_media_pipeline_integration.py` | **6** | FR-070, NFR-007, NFR-050 |
| `tradehub_core/tests/test_engine_webp.py` | **4** | FR-012, FR-019, NFR-047 |
| **Toplam** | **116** | — |

**Testi olmayan gereksinim alanları — yazılması gereken dosyalar:**

| Önerilen dosya | Kapsayacağı gereksinimler | Neden bugün yok |
|---|---|---|
| `test_slot_registry.py` | FR-001, FR-002, FR-005, FR-008, FR-017 | Kayıt defteri kodu **yok** (K-05) |
| `test_upload_policy_l3.py` | FR-007, FR-009, FR-011, FR-015, FR-016, FR-018 | L3 katmanı **hiç yok** |
| `test_upload_policy.py` | FR-060, NFR-015 | `upload_policy.py` için **hiç test dosyası yok** (`ls tradehub_core/tests/ \| grep -i upload` → boş) |
| `test_derivatives.py` | FR-020, FR-035, FR-037, FR-038 | Türev üretimi **yok** (K-04) |
| `test_content_rules.py` | FR-046…FR-059 | Kural motoru **yok** |
| `test_rate_limit.py` | FR-082…FR-091 | Medya uçlarında rate limit **yok** |
| `test_trash_retention.py` | FR-092, FR-093, FR-101, FR-108 | `trash.py`/`archive.py` için **hiç test dosyası yok** |
| `test_legal_hold.py` | FR-100 | `th_legal_hold` alanı **yok** |
| `test_poster.py` | FR-042, FR-043 | Poster üretimi **yok** |
| `test_svg_sanitize.py` | FR-014, FR-119, FR-120, NFR-022 | SVG kabulü **kapalı** (bilinçli) |
| `test_metadata_strip.py` | FR-039 | EXIF/GPS temizliği **yok** |

### 7.4 Ters yön — bulgu → gereksinim

Bu tablo, envanter ve standart belgelerinde ölçülmüş **her** eksiğin bir
gereksinime bağlandığını gösterir. Bağlanmamış bulgu **yoktur**.

| Bulgu | Ne | Karşılık gereksinim |
|---|---|---|
| **B1** | Slot kayıt defteri yok | FR-001, FR-002 |
| **B2** | En-boy oranı kuralı yok | FR-016, FR-017 |
| **B3** | Türev boy üretimi yok | FR-035, FR-121 |
| **B4** | Bazı slotlar `<img>` değil CSS background | NFR-033 |
| **B5** | KVKK muafiyet haritası eksik | FR-110 |
| **B6** | `LIVE_SOURCES` eksik (41 alanın 8'i) | FR-096 |
| **B7** | Aynı sınır için üç/dört farklı sayı | NFR-045 |
| **B8** | `is_private` tutarsızlığı | FR-117 |
| **E1** | `category.banner` backend alanı yok | FR-006, §8.27 |
| **E2** | `header_bg_image` backend'de yok | FR-006, K-13, §8.18 |
| **E3** | Avatar optimize edilmiyor | NFR-012 |
| **E4** | 2 doctype'ta dpi kaybı tuzağı açık | FR-111 |
| **E5** | KVKK alan haritası 4 KYB alanında eksik | FR-110 |
| **E6** | `product.video` 16:9 ama kutu 1:1 | FR-132, §8.28 |
| **E7** | Private video sessizce normalize edilmiyor | FR-118 |
| **E8** | Ölü render bileşenleri (4 adet) | FR-132 |
| **E9** | Kodlu ret sözleşmesi 2 uçta kullanılmıyor | FR-061 |
| **E10** | Şema video/belge biçimlerini ifade edemiyor | FR-002, K-21, T8 |
| **A1** | Ürün tabanı 2000, hat 1920'de kesiyor | NFR-047, NFR-010 |
| **A2** | `.webp` yükleme hiçbir tavana tabi değil | NFR-048 |
| **A3** | Yükleme yanıtı ölçü döndürmüyor | FR-064 |
| **Ç1** | Yerinde değiştirme MIME'ı yalanlıyor | FR-041, K-17 |
| **Ç2** | `factory_video_url` hiçbir yere bağlanmıyor | K-13, FR-006 |
| **Ç3** | Üç farklı boyut tavanı | NFR-045 |
| **Ç4** | İstemci/sunucu "verimli" barı ayrışık | NFR-045 |
| **Ç5** | Video ölçü metadatası yazılmıyor | FR-133, K-06 |
| **Ç6** | Skeleton ↔ kutu oran uyuşmazlığı (18,75 px CLS) | FR-124 |
| **Ç7** | Ana oynatıcıda poster yedeği yok | FR-042 |
| **Ç8** | Ana kutu 16:9, küçük resim 4:3 (%25 kırpma) | FR-042 (poster merkez %75 kısıtı) |
| **Ç9** | Ürün videosu modalinde sesli autoplay | FR-127 |
| **Ç10** | Opus bitrate sabitlenmemiş | FR-129 |
| **Ç11** | WebM cue'ları başta değil | FR-130 |
| **Ç12** | Kategori enum'u iki yerde tekrar | NFR-046 |
| **F1/F2/F15** | Platform logosu 87×32, koyu tema bağlanmamış, 5 kopya | **kapsam dışı** (§1.3) — `logo.md` §2'de kuralı yazılı |
| **F3** | `seller-shop.ts:124` logo plakası yok | FR-019 gerekçesi; `logo.md` §3.9 |
| **F4** | 5 render noktası logoyu kırpıyor | FR-020 |
| **F5** | Logo kayıplı WebP q80'e çevriliyor | FR-038 |
| **F6** | Marka logosu gönderiliyor, basılmıyor | FR-132 (ölü veri yolu) |
| **F7** | Sohbet avatarı üçüncü parti `ui-avatars.com` | **kapsam dışı** — `logo.md` §9'da ileriye dönük kural |
| **F8/F9** | `icons/*.webp` gerçekte PNG; ölü manifest | K-17 |
| **F10/F11/F12** | Panel favicon 404; og:image bildirilmiyor; favicon varyantları eksik | **kapsam dışı** (§1.3) |
| **F13** | og:image logoyu kırpıyor + alfa düşürüyor | FR-044 |
| **F14** | `data:` URI SVG logolar DB'de | FR-013, §8.29 |
| **F16** | `menu-header-bg.png` 1,7 MB | **kapsam dışı** — not düşüldü |
| **F17** | Panel 400×400 tavsiyesi ↔ standart 512 | NFR-045, `logo.md` §13-K5 |
| **F18** | Banner dropzone oranı ↔ tavsiyesi çelişiyor | NFR-045 |
| **I1…I9** | Şemayla ifade edilemeyen değişmezler | FR-007, FR-008, FR-017, FR-032, FR-034, FR-062 |
| **D1…D5** | Doğrulama betiği kontrolleri | FR-003, FR-004, FR-005, FR-034, FR-062 |
| **SVG-1…SVG-10** | SVG kabul ön koşulları | FR-014, FR-119, FR-120, NFR-022 |
| **T1…T10** | SRS TASLAK gerekçeleri | §6.7 G1–G7 |
| **rev2-A** | 179 kayıt > 20 MP; max 72,71 MP; tavan 80 MP hiçbirini kesmiyor | **FR-143** |
| **rev2-B** | 2 logo politikasında `max_megapixels_hard` alanı yok | **FR-144** |
| **rev2-C** | 38 CMYK dosya; optimizasyon kapılarından dönen çevrilmiyor | **FR-145** |
| **rev2-D** | 597 alfalı dosya; format zincirinde alfa koruması yok | **FR-146** |
| **rev2-E** | İki politika seti aynı alana 8 kat farklı eşik dayatıyor | **FR-147** |
| **rev2-F** | Doğrulama betiği `KeyError` ile çöküyor, çıkış kodu 1 | **FR-148** |
| **rev2-G** | 9 slotun 8'i gerçek veride > %10 ihlal oranında | **FR-149**, FR-138 |
| **rev2-H** | 719 harici URL referansı; 2 slot %100 harici | **FR-150** |
| **rev2-I** | Logo JPEG payı %50 → K1 ölçümle B'ye döndü | **FR-019 (değişti)** |

---

### 7.5 Slot bazlı uyum ölçümü — gereksinim ↔ gerçek veri

> **rev2'de eklendi.** Bu tablo, §3'teki kuralların **bugünkü veriye
> uygulandığında ne kadar dosyayı kestiğini** gösterir. Kaynak:
> `09-slot-bazinda-istatistik.md` §3. "Uyumsuz" = en az bir kuralı ihlal eden;
> harici URL ve diskte olmayan dosya da uyumsuz sayıldı.

| slot | n | uyumsuz | oran | en sık ihlal | Bağlı gereksinim | FR-138/FR-149 sonucu |
|---|---:|---:|---:|---|---|---|
| `brand.logo` | 1 | 0 | **%0,0** | — | FR-019, FR-020 | `all` — **ama n=1, istatistiksel değeri yok** |
| `company.cover_image` | 34 | 6 | **%17,6** | dosya diskte yok (3) | FR-023, FR-031 | `all` — **eşiğin altında kalan tek anlamlı küme** |
| `seller.logo` | 19 | 6 | %31,6 | dosya diskte yok (2), `aspect_band` (2) | FR-019, FR-020 | `new_uploads_only` (logo eşiği %5 aşıldı) |
| `product.image` | 3.061 | 1.488 | %48,6 | harici URL (668), `min_short_edge` (566), oran (564) | FR-015, FR-016, FR-018 | `new_uploads_only` |
| `product.video` | 5 | 4 | %80,0 | oran ≠ 16:9 (3) | FR-134, `product-video.md` §3 | `new_uploads_only` |
| `company.cover_video` | 6 | 5 | %83,3 | harici URL (4) | FR-025, FR-026, FR-134 | `new_uploads_only` |
| `document.attachment` | 61 | 56 | **%91,8** | `min_short_edge < 1654` (52) | **FR-027** (zaten `warn`) | `new_uploads_only` — FR-027 bunu **önceden** öngörmüştü |
| `category.banner` | 32 | 32 | **%100** | harici URL (30) | FR-024, **FR-150** | veri yerelleştirilmeden ölçüm anlamsız |
| `user.avatar` | 6 | 6 | **%100** | harici URL (6/6) | FR-021, FR-022, **FR-150** | slot üzerinde **sıfır kontrol** — mimari sorun |

**Bu tablonun gereksinimlere üç etkisi:**

1. **FR-027 doğrulandı.** Belge slotunda `require` aksiyonunu `warn` yapan
   gerekçe ("telefonla çekilmiş belge bugün kabul ediliyor") **%91,8 ile
   ölçüldü**. Rev1'de gerekçeydi, rev2'de kanıt.
2. **FR-138 zorunlu hâle geldi.** %10 tetiği 9 slotun 8'inde aşıldı.
   Grandfathering bir tercih değil, **tek uygulanabilir yol**.
3. **FR-150 doğdu.** İki slotun %100'ü, bir slotun %94'ü harici URL — bu bir
   politika kalibrasyon sorunu değil, **kontrol alanı sorunu**.

> **Ölçülmedi:** `product.image`'ın 3.061 referansının 668'i harici olduğu için
> o dosyaların piksel/oran değerleri **bilinmiyor**. Yerel 2.393 dosya
> üzerinden uyumsuzluk **%34,3**; tüm referanslar üzerinden **%48,6**. İki sayı
> da doğrudur, farkı harici URL'lerin ne olduğunun bilinmemesidir.

---

## 8. ÜRETİMDE DOĞRULANMALI

> **REVİZYON 2 NOTU (2026-08-18).** Aşağıdaki giriş paragrafı **rev1'e aittir**
> ve artık kısmen geçersizdir: Docker **açıldı**, yerel veritabanına ve diske
> erişildi, `jsonschema` **kuruldu**. Bu bölümün **§8.0, §8.2 ve §8.29**
> maddeleri koşuldu ve kapandı (aşağıda işaretli). Kalan maddeler için sınır
> değişti: artık "Docker kapalı" değil, **"yerel ölçüldü, üretim
> doğrulanmadı"**. Üretim imajını Frappe Cloud kendi build ettiği için
> `docker/backend.Dockerfile` bağımlı hiçbir bulgu üretime taşınamaz.

Aşağıdakilerin **hiçbiri** bu oturumda yapılamadı: Docker kapalı, üretim
veritabanına ve canlı siteye erişim yok, etiketli görsel korpusu yok,
`jsonschema` bu Python kurulumunda yok. Her madde **çalıştırılacak komutu** ve
**hangi karara girdiğini** içerir. Site adı `istoc.localhost` varsayıldı; gerçek
site adıyla değiştirilmelidir.

Uzun betikler kaynak belgelerde **zaten tam olarak yazılıdır**; burada tekrar
edilmedi, bölüm referansı verildi.

### 8.0 Şema doğrulamasının yeniden koşturulması (T9) — ✅ **KOŞULDU (2026-08-18)**

> **SONUÇ.** `jsonschema` **4.25.1** kurulu bulundu. `Draft202012Validator` ile
> 9 politikanın **9'u da 0 hatayla** geçti — rev1'in "6/9 uyumlu, uyumsuzlar
> `seller-logo`, `brand-logo`, `company-cover-video`" beklentisi **aşıldı**:
> şema v1.3.0 logo sınıfını da ifade ediyor. **T3 ve T9 kapandı.**
>
> **Ama `README.md` §6 betiği çıkış kodu 0 vermedi.** Betik `KeyError:
> 'max_megapixels'` ile **çöktü** (iki logo politikasının `master` bloğunda alan
> yok). Eksik alanı hata sayan varyantla: **6 hata, çıkış kodu 1**
> (D3 ×2 `message_key` uyuşmazlığı, D4 ×2 eksik alan, D5 ×2 yanlış pozitif).
> **G1 kapısı bu yüzden hâlâ açık** → FR-148, T10.
>
> **Rev1'in tahmini doğrulandı:** "şema uyumu sağlandığında D5 satırı **2**
> olacaktır" denmişti — oldu. Ama bunun yanlış pozitif olduğu da rev1'de
> yazılıydı değil, rev2'de tespit edildi: iki logo slotunun standart belgesi
> ortaktır (`logo.md`), ayrı `.md` dosyası **olmamalıdır**. Düzeltilmesi gereken
> D5 kontrolüdür, belge yapısı değil.

**Rev1'de yazılmış koşum yönergesi (kayıt için):**

```bash
cd /Users/ahmet/Desktop/istoc-medya-wt
python3 -m pip install --user jsonschema
# Ardından docs/standards/README.md §6'daki betiği aynen çalıştır:
#   şemaya uyumlu politika sayısı ve D1–D5 değişmez ihlalleri raporlanır.
# Beklenen (kök-anahtar karşılaştırmasından): 6/9 uyumlu; uyumsuzlar
#   seller-logo.json, brand-logo.json, company-cover-video.json
# Çıkış kodu 0 olmalı → G1 kapısı (§6.7)
```

**Betiğin bilinen kör noktası düzeltilmelidir:** şema hatası olan dosya `continue`
ile atlandığı için D1–D5 o dosyada **hiç çalışmıyor** → "0 hata" yalnız şemaya
uyumlu dosyalar için geçerlidir. Ayrıca D5 (politika var, `.md` yok) bu yüzden
`seller-logo` ve `brand-logo` için **hiç çalışmıyor**; şema uyumu sağlandığında
o satır **2** olacaktır (ikisinin de `.md` karşılığı gerçekte **yok**).

### 8.1 Üretimdeki Pillow sürümü ve DPI davranışı (FR-030, K-07)

Tam betik: `dpi-ve-cozunurluk.md` §8-M1. Beklenen (bu ortamda Pillow 11.3.0 ile
ölçülen): `boyut: 2400 2400`, `cikti dpi: None`, `jfif_unit: 0`,
`jfif_density: (1, 1)`. Farklı çıkarsa FR-030 tablosu güncellenir.

### 8.2 Gerçek dosyaların piksel ve oran dağılımı (FR-138) — ✅ **KOŞULDU (2026-08-18)**

> **SONUÇ — rev1'in "en kritik ölçüm" dediği madde kapandı.**
> `09-slot-bazinda-istatistik.md` §4.1, `product.image` slotunun **3.061 eşsiz
> referansını** ölçtü (2.393'ü yerel, 668'i harici).
>
> | rev1'de sorulan | ölçülen |
> |---|---:|
> | `kisa_kenar_RET` | **566** (yerel dosyaların **%23,7**'si) |
> | `oran_RET` | **564** (%23,6) |
> | `alan_RET` (`min_area < 1 MP`) | **493** |
> | `megapiksel_RET` (>80 MP) | **0** → FR-143'ün doğduğu yer |
> | `max_bytes` aşımı (>25 MB) | **0** |
> | kabul dışı uzantı | **0** |
>
> **FR-138 karar eşiği aşıldı:** `kisa_kenar_RET + oran_RET` toplamı %10'un
> **iki katından fazla** → politika yalnız yeni yüklemelere uygulanabilir.
>
> **Eşik duyarlılığı da ölçüldü** (`09-…md` §4.1): `< 512 px` %9,3 · `< 800 px`
> %11,8 · **`< 1000 px` (mevcut kural) %23,7** · `< 2000 px` (rakip politika
> tabanı) **%88,2**. İki politika setinin farkı burada 8 kata çıkıyor → FR-147.
>
> **Tolerans gevşetmek işe yaramaz — ölçüldü:** `ratio_tolerance` 0,02'den
> 0,05'e çıkarılsa toleransın hemen dışındaki bantta (0,75–0,80) yalnız
> **3 dosya** var. Oran ihlalinin gövdesi gerçekten farklı oranlarda çekilmiş
> görsellerdir; çözümü yeniden kırpmadır (insan kararı, `09-…md` §8).
>
> **Hâlâ ölçülmedi:** uzun kenar histogramında **tam 1920** ve **tam 2000**
> değerlerinin sayısı (NFR-047 kilidinin büyüklüğü) — bu kırılım alınmadı.

**Rev1'de yazılmış koşum yönergesi (kayıt için):**

Tam betik: `product-image.md` §9.1 (uyum karnesi: `kisa_kenar_RET`, `alan_RET`,
`oran_RET`, `master_under_spec`, `megapiksel_RET` + reddedilen oran histogramı +
uzun kenar histogramı). Ek betikler: `dpi-ve-cozunurluk.md` §8-M2,
`company-cover-image.md` §8.3, `category-banner.md` §8.3,
`document-attachment.md` §7.3, `logo.md` §12-D1.

**Karar bağlantısı:** `kisa_kenar_RET + oran_RET` toplamı `toplam`ın **%10'unu**
aşarsa politika yalnız yeni yüklemelere uygulanır (FR-138). Logo için eşik **%5**.
Uzun kenar histogramında **tam 1920** ve **tam 2000** değerlerinin sayısı,
NFR-047'deki kilidin **üretimdeki büyüklüğüdür**.

### 8.3 Avatar israfının gerçek ölçüsü (NFR-012, E3)

Tam betik: `user-avatar.md` §8.2 (`>256px`, `<96px`, `kare_degil`, `animasyonlu`
sayımları + tahmini kazanç) ve §8.3 (`th_optimized_at` dağılımı — beklenti:
**tamamı "OPTIMIZE EDILMEDI"**). §8.2'deki `bayt_israf` **tahmindir**, ölçüm
değil (piksel ile bayt arasında doğrusallık varsayılmıştır).

### 8.4 Çöpe atılan dosya kotadan düşüyor mu (FR-074)

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select count(*) copteki_kayit,
       round(sum(file_size)/1048576,1) mb,
       sum(case when is_private=0 and left(file_url,7)='/files/' then 1 else 0 end)
         kota_sorgusuna_giren
from tabFile where th_trashed_at is not null and is_folder = 0;"
```

`kota_sorgusuna_giren > 0` ise iddia **doğrulanır**: satıcı sildiği hâlde kotası
düşmüyor. Ek: `kota.md` §10.3 (private hacmi), §10.2 (kotayı aşmış satıcı),
§10.5 (yetim dosya).

### 8.5 Kategori muafiyet listesindeki placeholder adlar (FR-056)

Tam sorgu: `icerik-kurallari.md` §7.6. `content_rules.json` →
`category_overrides` içindeki kategori adları **placeholder'dır** ve bu sorgunun
çıktısıyla değiştirilmelidir.

### 8.6 RTL sayı yönü — görsel kontrol (FR-069)

Tam adımlar: `dpi-ve-cozunurluk.md` §8-M4. Panel/storefront dili `ar` yapılır, bir
ürün görseli yüklenir, optimizasyon özeti ekran görüntüsüyle kaydedilir ve
sayıların sırası (`3000×3000` önce, `2400×2400` sonra) korunuyor mu bakılır.

### 8.7 Kural motorunun ve kuyruğun gerçek maliyeti (NFR-005, FR-137)

```bash
# Görsel başına ortalama süre (korpus hazır olduğunda):
time python3 /Users/ahmet/Desktop/istoc-medya-wt/scripts/calibrate_content_rules.py \
  --corpus /veri/korpus --manifest /veri/korpus/manifest.csv \
  --out /tmp/olcum.json --limit 400
```

**100 ms**'yi aşarsa kural motoru kuyrukta çalışmalıdır. Kuyruk kapasitesi:
`kota.md` §10.6 (long kuyruk derinliği + `nproc`). ffmpeg tek iş için 1700 s'ye
kadar çalışabildiğinden `worker sayısı × 60/1700 ≈ dakikada tamamlanabilir iş`.

### 8.8 Lighthouse, bayt kazancı ve depolama bütçesi (NFR-008, NFR-009, FR-123)

Tam komutlar: `03-render-envanteri.md` §7.1 (4 sayfa × 2 profil Lighthouse),
§7.2 (DOM'dan gerçek kutu genişlikleri), §7.3 (gerçek dosya boyutu dağılımı);
`product-image.md` §9.5 (ladder bayt oranı); `logo.md` §12-D4 (gerçek logo
dosyalarından kayıpsız WebP üretimi — §FR-038'deki 4/8/16/40 KiB tavanlarını
**onaylar ya da düzeltir**); `company-cover-video.md` §11-D8 (CLS/LCP).
En kritik iki audit: `uses-responsive-images`, `modern-image-formats`.

### 8.9 "Görsel URL'i geçen alan" sayısı gerçekte kaç (FR-095, FR-096)

Tam sorgu: `retention.md` §9.4 (`information_schema.columns` taraması). Sonuç
`usage.py:32-59`'daki **16** çiftle karşılaştırılmalı. Listede olmayan ve gerçekten
medya URL'i tutan bir kolon varsa **o kolondaki dosyalar bugün "kullanılmıyor"
görünüyor** — yani silme adayı.

### 8.10 Zamanlanmış görevler gerçekten koşuyor mu (FR-108, NFR-036)

Tam komutlar: `retention.md` §9.1 (`bench doctor` + `Scheduled Job Log` sorgusu),
§9.2 (purge audit izi), §9.3 (dört saklama alanının disk boyutu — `du` ile
`usage_bytes()` iki yoldan karşılaştırma), §9.5 (30 günü aşmış çöp),
§9.6 (`th_trashed_at` ↔ disk örtüşmesi), §9.7 (yedek set sayısı).

### 8.11 PDF içinde aktif içerik var mı (NFR-025)

Tam betik: `document-attachment.md` §7.6 (`/JavaScript`, `/JS`, `/OpenAction`,
`/Launch`, `/EmbeddedFile` regex taraması).

### 8.12 Satıcı alt kullanıcılarının rolleri (NFR-027)

Tam sorgu: `04-yetki-modeli.md` §9.2. **"System User" satırı VARSA** §8-B gerçek
bir açıktır; yoksa Frappe varsayılanı (`owner = user`) zaten kilitliyor demektir.

### 8.13 Medya audit'inin gerçek yazma hedefi (NFR-034)

`media/schema.py:33` `FULL_TABLES = ("tabFile", "tabAuthorization Decision Log")`
listesinden çıkarıldı; `audit.log_media_event` / `log_media_batch`'in **gerçekte
hangi doctype'a yazdığı** doğrulanmalıdır — bu çalışmada `media/audit.py`'nin
yalnız action sabitleri (satır 43-68) okundu, yazma hedefi okunmadı.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import inspect
from tradehub_core.media import audit
print(inspect.getsource(audit))
PY
```

### 8.14 ffmpeg/ffprobe imajda var mı (NFR-043 — **yoksa hiçbir video normalize edilmiyor**)

```bash
docker compose exec backend which ffmpeg ffprobe
docker compose exec backend ffmpeg -version | head -1
docker compose exec backend ffmpeg -encoders 2>/dev/null | grep -E "libvpx-vp9|libopus|libx264|libwebp"
docker compose exec backend ffmpeg -hide_banner -h muxer=webm 2>&1 | grep -i cues_to_front
docker compose exec backend ffmpeg -hide_banner -filters 2>/dev/null | grep -E "thumbnail|loudnorm"
```

`cues_to_front` (FR-130), `loudnorm` (FR-129), `thumbnail` + `libwebp` (FR-042)
gereksinimleri **kurulu imajda doğrulanmadan uygulanamaz**. Video durum dağılımı:
`product-video.md` §8.2, `company-cover-video.md` §11-D4.

### 8.15 HEIC / AVIF gerçekten açılabiliyor mu (K-08)

Tam betik: `product-image.md` §9.7. `features.check("heif")` **False** dönerse ya
`pillow-heif` eklenir ya `upload_policy.EXTENSIONS`'tan `.heic`/`.avif`
**çıkarılır**. Bugünkü hâl ikisinin arasında ve **bir istisnaya açık**.

### 8.16 Bağımlılıkların gerçekten var olduğu (K-09, K-10)

Tam komutlar: `icerik-kurallari.md` §7.1. Beklenen: Pillow ve numpy **var**,
`pytesseract` **YOK** → `overlay_text` yalnız Vision `text_detected` yoluyla
çalışabilir.

### 8.17 Yetim dosya var mı (FR-072, K-12)

Tam komutlar: `kota.md` §10.5 (`comm -23` / `comm -13` ile disk ↔ DB
karşılaştırması). İlk liste yetim dosyalar (kotaya sayılmayan ama disk tüketen),
ikinci liste kırık kayıtlar. `du -sh public/files` ile `storage_usage()` toplamı
arasındaki fark bu iki listeyle **açıklanmalıdır**.

### 8.18 `header_bg_image` ve `tr_tradehub` (FR-006, K-13, E2)

Tam komutlar: `company-cover-image.md` §8.1 (`list-apps`,
`frappe.get_installed_apps()`, `tabDocField` sorgusu, panel Network sekmesinde
`tr_tradehub.api.v1.seller.get_storefront` HTTP kodu). **`header_bg_image`
hiçbir doctype'ta yoksa `pages/seller-shop.ts:118-119` ölü koddur ve politikadan
çıkarılmalıdır.** Ayrıca `company-cover-image.md` §8.2 (`banner_image` ölü mü) ve
§8.4 (panelden yüklenen kapaklar private mı).

### 8.19 Gerçek CSS kutu ölçüleri (K-15)

Tarayıcı konsolu betikleri: `logo.md` §12-D3 (logo kutuları, DPR 1/2/3 ayrı ayrı),
`company-cover-image.md` §8.5 (hero bandı + StoreHeader 16:9),
`category-banner.md` §8.6 (bento, 360/430/768/1920 px'te),
`user-avatar.md` §8.6 (daire avatarlar),
`company-cover-video.md` §11-D7 (**1023 px dâhil** 7 genişlikte),
`product-video.md` §8.5 (tablet @2x büyütmesi),
`product-image.md` §9.3 (israf listesi + zoom talebi),
`dpi-ve-cozunurluk.md` §8-M3 (genel `fazlalik` ölçümü).

**`company-cover-video.md` §2.2 tablosu Tailwind varsayılan ölçeğiyle
hesaplanmıştır** (`sm 640 / md 768 / lg 1024 / xl 1280`), diğer belgeler ezilmiş
ölçekle (`sm 480 / md 640 / lg 768 / xl 1024`). Bu ayrım D7 ölçümünde **özellikle
kontrol edilmelidir**.

### 8.20 nginx `X-Forwarded-For` zinciri (FR-085, FR-086)

Tam komutlar: `kota.md` §10.7. Ayrıca canlı bir istekle test edilmelidir: sahte
`X-Forwarded-For` gönderip uygulamanın onu mu yoksa gerçek `remote_addr`'ı mı
gördüğüne bakılır. **Uygulama sahte değeri görüyorsa IP bazlı kova IP taklidiyle
atlatılabilir ve FR-085 o hâliyle uygulanmamalıdır.**

> **Not:** `/Users/ahmet/Desktop/istoc/docker/nginx/` bu çalışmada **okunmadı**.
> Ayrıca MEMORY kaydı ("İstoç sistem tasarımı denetimi", 2026-08-16) "prod'a
> ulaşmamış nginx sertleştirmesi"nden söz ediyor — nginx yapılandırmasının
> prod'da yerel dosyayla aynı olduğu **varsayılmamalı**, prod'daki dosya ayrıca
> okunmalıdır. Bu, FR-119 SVG-8 (yanıt başlıkları) için de belirleyicidir
> (`logo.md` §12-D6).

### 8.21 KVKK alan haritası eksiğinin bedeli (FR-110)

Tam betik: `document-attachment.md` §7.2. Son blok, `presets.py:70-76`'ya
eklenmesi gereken **dosya sayısını** verir. Ayrıca `04-yetki-modeli.md` §9.4
("**PII dosyası PUBLIC mi**" kontrolü — beklenen **BOŞ**; dolu çıkarsa **aktif
KVKK olayı**) ve §9.5.

### 8.22 Hassas belgeler küçültülmüş mü (FR-111, E4)

Tam betikler: `document-attachment.md` §7.1 (`Shipment Document` /
`Data Processing Agreement` için `th_optimized_at is not null` sorgusu +
efektif dpi hesabı). **Dönen her satır küçültülmüş bir hassas belgedir.**
`~171 dpi` civarı değerler `engine.py:117`'nin belgeye dokunduğunu **kanıtlar**.
200 dpi eşiğinin doğruluğu için OCR ölçümü: §7.5.

### 8.23 Byte-range ve Content-Type (FR-041, FR-130, Ç1)

Tam komutlar: `company-cover-video.md` §11-D5. `Content-Type: video/mp4` +
ilk 4 baytın `1a45dfa3` (Matroska/WebM) çıkması Ç1'i **doğrular**.
`Accept-Ranges: bytes` yoksa progressive seek çalışmıyor demektir.

### 8.24 Galeri adet dağılımı (FR-018, FR-138)

Tam sorgu: `product-image.md` §9.10. 12'nin üstünde galerisi olan ilan varsa
kural geçmişe dönük uygulanamaz — **o ilanlar kaydedilemez hâle gelir**.
Yorum görseli tavanı 10 (`listing_review.py:25`), satıcı vitrin tavanı 20
(`api/seller.py:1647`) — bu ikisi zaten uygulanıyor.

### 8.25 Kapak videosu pasif/aktif veri bütçesi (NFR-001, NFR-002)

Tam adımlar: `company-cover-video.md` §11-D9 (DevTools Network "Slow 4G", cache
boş, mobil emülasyon, **hiçbir şeye dokunmadan** poster+video transfer toplamı;
otomatik alternatif `lighthouse` `network-requests` audit'i).
Beklenen: **≤150 KB**. Ayrıca §11-D1 (kapak videosu envanteri — kaç mağazada var,
**kaçının poster'ı boş**), §11-D2 (süre/çözünürlük/bitrate dağılımı),
§11-D3 (viewport × DPR dağılımı — **1080p tier kararının K1 girdisi**: 768-1023 px
× DPR ≥ 2 hücresinin payı **> %15** ise 1080p eklenir).

### 8.26 `.webp` bypass'ının saha etkisi (NFR-048, A2)

Tam betik: `dpi-ve-cozunurluk.md` §8-M5. `len(buyuk) > 0` ise A2 **kuramsal
değil, sahada gerçekleşmiş** demektir.

### 8.27 Kategori bandı alanı yaratılacak mı (E1)

Tam sorgu: `category-banner.md` §8.1 (`tabDocField`'da `%banner%`/`%hero%`/
`%cover%`). Sonuç boşsa `components/seller/CategoryProductListing.ts`
**silinmeli** ya da alan yaratılmalıdır — **ürün kararı, ölçüm değil**.
Ayrıca §8.2 (bento span dağılımı ve `columns` değeri — §2 tablosu `columns=4`
**varsayımıyla** üretildi; üretimde 5 veya 6 ise `catbanner_1920` profili
**gereksiz** hâle gelir), §8.4, §8.5.

### 8.28 `ProductVideoSection` ölü mü, mount edilmeli mi (E6)

`product-video.md` §2 ve §8.4 (`Listing.video_url` alanlarının kaçı DOSYA, kaçı
YouTube/Vimeo). **Karar verilene kadar 16:9 render kutusu yalnız kâğıt üzerinde
vardır** ve `product.video` slotunun 16:9 oran kuralı `warn` seviyesinde
kalmalıdır.

### 8.29 `data:` URI logoların gerçek sayısı (FR-013, F14)

Tam betik: `logo.md` §12-D2. Beklenti: bunlar `seed_demo_data.py` çıktısı olduğu
için **üretimde 0 olmalı**. 0 değilse SVG-10 **acildir**. Ayrıca §12-D5 (og:image
kırpma hasarının görsel doğrulaması — %47,5 kesilme beklenir), §12-D7 (depolama
etkisi), §12-D8 (koyu tema kullanım oranı).

### 8.30 Ölçülemeyen ve kasıtlı olarak boş bırakılanlar

| Konu | Neden |
|---|---|
| Bant genişliği / CDN maliyeti | Ağ ölçümü ve CDN gerektirir; **CDN yok** (K-03) |
| Gerçek DPR ve viewport dağılımı | RUM/analytics erişimi gerektirir; kod tarafında ölçüm kancası **bugün yok** |
| Transcode kuyruğunun gerçek gecikmesi | Worker metrikleri gerektirir |
| Vision (moderasyon) tarama maliyeti | Token/görsel fiyatı bu oturumda bilinmiyor; 400 görsellik tarama **ücretlidir** ve tarama öncesi hesaplanmalıdır |
| `encoder_quality` değerlerinin doğruluğu | Kalibrasyon koşumu gerektirir (SSIM hedefleri: photo 0,96 / graphic 0,98 / text 0,99 / fine_detail 0,975) |
| `master.colorspace: srgb` renk kayması riski | Mevcut davranış `preserve` (`engine.py:115,122,126,131,133`); bu bir **değişiklik önerisidir** ve üretim görselleriyle görsel karşılaştırma gerektirir |
| OCR başarı oranı ve 200 dpi eşiğinin doğruluğu | tesseract koşumu + üretim belgeleri gerektirir (`document-attachment.md` §7.5) |
| 10 MB vs 200 MB video tavanından hangisinin doğru olduğu | **Ürün kararı**, ölçüm değil |
| Kapak videosunun zorunlu mu opsiyonel mi olacağı | **Ürün kararı** (`company-cover-video.md` §10-K3) |
| Slider slayt adedi üst sınırı (5) | **Ürün kararı** |
| KYC ucunun L1'e taşınıp taşınmayacağı | **Ürün/güvenlik kararı** |
| Sohbet avatarlarının kaynağı | `conv.avatar` alanının kaynağı bu repoda **izlenemedi** |

---

## 9. Onay

### 9.1 Bu belgenin durumu

| Alan | Değer |
|---|---|
| Belge | `docs/srs/SRS-v1.0.md` |
| Sürüm | **v1.0 — HÂLÂ TASLAK** (revizyon 2) |
| Görev | T-029 (Faz 2 kapanış) · T-029 yenileme (rev2) |
| Tarih | 2026-08-17 (ilk yazım) · **2026-08-18 (revizyon 2)** |
| Branch | `medya-motoru-faz0-faz2` |
| Fonksiyonel gereksinim | **150** (FR-001 … FR-150) — rev2'de **+8** |
| Fonksiyonel olmayan gereksinim | **52** (NFR-001 … NFR-052) — değişmedi |
| Kısıt | **22** (K-01 … K-22) — değişmedi |
| Kabul kriteri grubu | 6 (§6.1 … §6.6) + geçiş kapısı (§6.7, **G1…G7**) |
| Faz 2 kapanış kriteri | **19** (rev1: 16) · geçen **12** |
| Üretimde doğrulanacak madde | **31** (§8.0 … §8.30) — **3'ü koşuldu ve kapandı**: §8.0, §8.2, §8.29 |
| TASLAK gerekçesi (T-maddesi) | **10** (T1…T10) · kapanan **3** (T3, T8, T9) · açık **6** · yeni **1** |
| Yönetici kararı | **14** (logo K1–K6, kapak videosu K1–K8) · çözülen **2** · açık **12** |
| Açık soru (`open_questions`) | **55** (rev1: 51) |
| Mevcut test | **116** (9 dosya, rev1'de ölçüldü — rev2'de yeniden sayılmadı) |
| Yazılması gereken test dosyası | **11** (§7.3) + rev2'de adı geçen 5 yeni test |
| Değiştirilen mevcut kod dosyası | **0** (rev1 ve rev2'de) |

**Rev2'de değişen gereksinimler — CR takibi için:**

| FR | Değişiklik | Yetki |
|---|---|---|
| **FR-019** | Logo alfa: **ret → uyarı** (aksiyon değişikliği) | §9.3'e göre CR gerektirir — **ancak** `logo.md` §13-K1'de **önceden yazılmış sayısal tetiğin** işlemesidir. §9.3'ün 2. istisnası ("bir `open_questions`/karar maddesinin kapatılması, gerekçesi ve dayanağı yazılmak koşuluyla") kapsamında sayıldı. Onay yine de **platform yöneticisinden** alınmalıdır (§9.2) |
| **FR-011** | Eşik değeri değişmedi; **uyarı notu** eklendi | Bilgi güncellemesi — CR gerekmez |
| **FR-138** | Eşik değişmedi; **tetik ölçüldü ve aşıldı** | Bilgi güncellemesi — CR gerekmez |
| **FR-143…FR-150** | **8 yeni gereksinim** | Gereksinim **eklenmesi** §9.3'e göre CR ister. Bunlar onay öncesi bir TASLAK'a eklendiği için CR numarası verilmedi; belge onaylanırsa bu 8 madde de onaylanan kapsamın parçasıdır |

> **Hiçbir eşik gevşetilmedi.** FR-143 bir eşiği **sıkılaştırmayı** öneriyor
> (80 → 40 MP). FR-019 sertliği azaltıyor ama bu, belgenin **kendi önceden
> yazılmış tetiğinin** sonucudur ve ters tetiği de yazılıdır.

### 9.2 Onay blokları

| Rol | Onaylanan kapsam | İmza / tarih |
|---|---|---|
| Platform yöneticisi | §2 aktör modeli, §5 kısıtlar, §6.7 geçiş kapısı (**G1–G7**), T7'deki **14 karar** (logo K1–K6, kapak videosu K1–K8) — bunların **K1/K2'si ölçümle çözüldü, onay yine gerekli** — ve **FR-019 aksiyon değişikliği** | ☐ |
| Teknik sorumlu (backend) | §3.A–§3.D, §3.G–§3.J, §4.1–§4.2, §4.5, §7 izlenebilirlik | ☐ |
| Teknik sorumlu (frontend) | §3.F, §3.K, §4.3, K-15, K-16, K-20 | ☐ |
| Güvenlik / KVKK | §3.J, §4.2, FR-039, FR-109, FR-110, FR-111, FR-119, NFR-025, §8.21 | ☐ |
| Ürün | §1.2 kapsam, §1.3 kapsam dışı, FR-037 (görünüm değişikliği), FR-138 (geriye dönük uygulama), §8.30'daki ürün kararları | ☐ |

### 9.3 Değişiklik yönetimi

**Bu noktadan sonraki değişiklikler change request'tir.**

Yani: bu belge onaylandıktan sonra §3'teki bir gereksinimin **eklenmesi,
kaldırılması, eşiğinin değiştirilmesi veya aksiyonunun (`reject`/`warn`/`review`/
`auto_fix`/`ignore`) değiştirilmesi**; §4'teki bir eşiğin gevşetilmesi; §5'teki bir
kısıtın kaldırılması; §6'daki bir kabul kriterinin düşürülmesi — **hiçbiri belge
düzenlemesiyle yapılmaz.** Her biri için bir change request açılır ve şu dördü
birlikte yazılır:

1. **Neyin değiştiği** — FR/NFR/K numarası ve eski→yeni değer.
2. **Neden** — hangi ölçüm, hangi üretim verisi ya da hangi ürün kararı bunu
   gerektiriyor. **Ölçüm gerekiyorsa §8'deki hangi madde çalıştırıldı ve çıktısı
   ne oldu** — çıktı olmadan eşik değişikliği kabul edilmez (§0.2 kuralı).
3. **Etki** — §7 izlenebilirlik matrisinde hangi satırlar, hangi politika
   dosyaları, hangi test dosyaları değişir.
4. **Onay** — §9.2'deki hangi rolün onayı gerekli.

**İstisna — change request gerektirmeyen üç işlem:**

- §8'deki bir ölçümün **çalıştırılması** ve çıktısının ilgili belgeye eklenmesi.
  Bu bir bilgi güncellemesidir; ancak çıktı bir eşiğin **değişmesini** gerektiriyorsa
  o değişiklik change request'tir.
- Bir `open_questions` maddesinin **kapatılması** (T2), kapatma gerekçesi ve
  dayanağı yazılmak koşuluyla.
- Yazılım hatası düzeltmesi: `HATALI` işaretli bir davranışın gereksinimde yazılı
  hâline **getirilmesi**. Gereksinimin kendisi değişmediği için CR gerekmez.

**Change request numaralandırması:** `CR-MEDYA-<nnn>`; her CR bu belgenin ilgili
bölümüne dipnot olarak bağlanır ve §7 matrisinde etkilediği satırlara işlenir.

**Sürüm kuralı:** §6.7'deki **G1–G7** kapılarının tamamı geçildiğinde belge
`v1.0 ONAYLI` olur. Onaylı bir belgeye giren her CR **minor** sürüm artırır
(v1.1, v1.2 …); bir kısıtın (K-**) kaldırılması ya da bir aktörün eklenmesi
**major** sürüm artırır (v2.0).

**Rev2 sürüm notu.** Bu revizyon **v1.1 değildir**. Sürüm kuralı minor artışı
"onaylı bir belgeye giren CR" için tanımlıyor; belge onaylanmadığı için
numara artmadı. Belge hâlâ **v1.0 TASLAK**, ikinci revizyonu.

---

*Bu belge T-029 kapsamında yazıldı, 2026-08-18'de canlı ölçümle revize edildi.
Hiçbir mevcut kod dosyası değiştirilmedi. Rev1'de hiçbir sayı ölçülmemişti;
rev2'de sayıların bir kısmı **yerel stack'te** ölçüldü — **hiçbiri üretimde
ölçülmedi** ve bu ayrım §0.2-b'de tablo hâlinde yazılıdır. Ölçülemeyen her şey
"ÖLÇÜLEMEDİ" olarak işaretlendi; kaynağı olmayan hiçbir sayı §3–§5'te yoktur.*
