# Faz 3 Kapanış İncelemesi — v1.0

**Görev:** T-035 (Faz 3 kapanışı) · **Tarih:** 2026-08-18 · **Depo:** `tradehub_core` · **Dal:** `ahmet`
**Kapsam:** T-032 (paket iskeleti), T-033 (PolicyEngine), T-034 (durum makinesi + kuyruk zarfı)

Bu belge iki şey yapar: Faz 3'te **donan kararları** yazar (bir daha tartışılmasınlar diye) ve
**risk kaydını** açar (unutulmasınlar diye). Övgü yok; ne çalıştığı ölçülerek, ne çalışmadığı
açıkça yazılıyor.

---

## 1. Tek cümlelik durum

**Karar katmanı çalışıyor, hat bağlı değil.** `PolicyEngine` 9 slot politikasını veri olarak
yüklüyor ve 51 golden fixture'ın 51'inde manifest beyanıyla aynı kararı veriyor; ama bu motoru
çağıran bir üretim yolu **yok** — `tradehub_core/media/pipeline/api/` iskelet ve slot kimliği hâlâ istemciden
gelmiyor. Faz 3 sonunda **canlıda hiçbir davranış değişmedi**.

---

## 2. Teslim edilenler (ölçülmüş)

### 2.1 Kod

| Dosya | Satır | Durum |
|---|---:|---|
| `tradehub_core/media/pipeline/policy/engine.py` | 1.278 | GERÇEK — PolicyEngine, PolicyRegistry, Decision |
| `tradehub_core/media/pipeline/core/probe.py` | 483 | GERÇEK — künye çıkarımı (frappe'siz) |
| `tradehub_core/media/pipeline/core/jobs.py` | 348 | GERÇEK — kuyruk zarfı + idempotency muhafızı |
| `tradehub_core/media/pipeline/core/state.py` | 257 | GERÇEK — ingest ekseni + yaşam döngüsü aynası |
| `tradehub_core/media/pipeline/core/errors.py` | 142 | GERÇEK — ihlal sözleşmesi |
| `tradehub_core/media/pipeline/api/__init__.py` | 26 | İSKELET (`IMPLEMENTED = False`) |
| `tradehub_core/media/pipeline/image/__init__.py` | 24 | İSKELET |
| `tradehub_core/media/pipeline/video/__init__.py` | 23 | İSKELET |
| `tradehub_core/media/pipeline/storage/__init__.py` | 19 | İSKELET |
| `tradehub_core/media/pipeline/delivery/__init__.py` | 19 | İSKELET |

Her iskelet paket kendi `__init__.py`'sinde **neyi saracağını, neyi sarmayacağını ve neden
uygulanmadığını** yazar; `IMPLEMENTED = False` bayrağı makine tarafından da okunur
(`tests/test_state_machine.py::test_iskelet_paketler_kendini_iskelet_ilan_ediyor`).

### 2.2 Test

| Dosya | Test | Kapsam |
|---|---:|---|
| `tests/test_policy_engine.py` | 38 | kayıt defteri, sınır vakaları, 51 fixture, ihlal sözleşmesi, hedef üretimi, ayna tutarlılığı |
| `tests/test_state_machine.py` | 46 | yaşam döngüsü aynası, ingest ekseni, iki eksen sözleşmesi, kuyruk politikası aynası, idempotency |
| **Toplam** | **84** | |

İki ortamda da geçiyor:

```
yerel      Python 3.9  / Pillow 11.3.0  → 84/84 OK
konteyner  Python 3.11.6 / Pillow 12.2.0 → 84/84 OK   (istoc-dev-backend-1, /home/frappe/olcum/faz3)
```

### 2.3 Ölçülen sonuçlar

| Ölçüm | Değer | Nasıl |
|---|---|---|
| Fixture uyumu | **51/51** | manifest `expected_action` ↔ `Decision.allow` |
| Yüklenen politika | 9/9 | `PolicyRegistry` |
| `evaluate()` maliyeti | **56,9 µs/çağrı** | 10.200 çağrı, yerel 3.9 |
| Politika yükleme | **1,42 ms** | 9 JSON, süreç başına bir kez |
| `bound_short999.jpg` | RET (`product_image_short_edge_too_small`) | T-033 kabul ölçütü |
| `bound_short1000.jpg` | GEÇER (yalnız `master_under_spec` uyarısı) | T-033 kabul ölçütü |

Kararın maliyeti ihmal edilebilir: bir yüklemede baskın maliyet dosyayı okumak ve `PIL.Image.open`,
karar değil. **Karar katmanını hatta koymanın performans bahanesi yoktur.**

---

## 3. Donmuş kararlar

Bunlar Faz 3'te KAPANDI. Yeniden açmak için yeni bir ölçüm ya da yeni bir gereksinim gerekir.

| # | Karar | Gerekçe / kanıt |
|---|---|---|
| **D-01** | Politika **veri**, motor **kod**. Yeni slot = `policy/slots/` altına bir JSON; `engine.py` değişmez. | `test_yeni_slot_kod_degismeden_calisir` çalışma anında onuncu politikayı yazıp doğruluyor; `test_motor_kaynaginda_slot_ozel_dal_yok` motorda slot sabiti olmadığını AST ile kanıtlıyor. |
| **D-02** | `evaluate()` saf fonksiyon; girdisi **dosya değil künye** (`MediaProbe`). | Karar test edilebilir olsun; aynı karar ffprobe çıktısından da, diskten de üretilebilsin. |
| **D-03** | `allow` = engelleyici ihlal yok. `warn` ve `auto_fix` yüklemeyi **durdurmaz**. | Slot politikalarının `on_violation` blokları bunu zaten böyle ilan ediyor (ör. `product.video` → `require: warn`). |
| **D-04** | Birden çok ihlalde **en yüksek aksiyon kazanır**, uyarılar birikimli listelenir. | `content_rules.json` `decision_model.aggregation` ile aynı kural. |
| **D-05** | Ölçülemeyen kural **"geçti" sayılmaz**; `Decision.skipped` içine `not_measurable` olarak yazılır. | Sessiz geçiş, kalibre edilmemiş eşiğin "çalışıyor" sanılmasının yoludur. `content_rules.json` `calibration_status = UNCALIBRATED`. |
| **D-06** | Her ihlal: **makine kodu + tr/en mesaj + düzeltme ipucu**. TR metni politikada varsa politika kazanır, EN her zaman motordan. | Politikaların 9/9'unda yalnız `messages.tr` var. `test_uretilen_her_ihlal_tam_sozlesmeyi_tasiyor` boş alan bırakmıyor. |
| **D-07** | Hata kodu = `on_violation.error_code_prefix` + `_` + kural adı. | `upload_policy.py:99` `Kod(kod, retryable)` sözleşmesiyle aynı biçim; istemci METNE değil KODA bakar. |
| **D-08** | Politika ihlalleri **`retryable = False`**. | `upload_policy.py:93-97` kuralı: kullanıcının dosyasıyla ilgili hata tekrar denenmez. |
| **D-09** | Mevcut yaşam döngüsü (`Active/Archived/Trashed/Deleted`) **ezilmez**; alım hattı **dik bir eksen** olarak eklenir. | `core/state.py` tabloyu aynalar, `test_gecis_tablosu_bire_bir_ayni` kaynaktan `ast` ile okuyup karşılaştırır. |
| **D-10** | `Active → Deleted` yok; kalıcı silme yalnız çöpten. | `states.py` başlığındaki bilinçli karar; `test_active_dogrudan_silinemez` koruyor. |
| **D-11** | Retry politikası (`MAX_ATTEMPTS`, `BACKOFF_SECONDS`, `STALE_AFTER_SECONDS`) **tek yerde**: `tradehub_core/media/jobs.py`. `media_engine` onu import eder, yoksa aynalar; test ayrışmayı düşürür. | `KuyrukPolitikasiAynasiTesti` (4 test). |
| **D-12** | İdempotency anahtarı **içerikten** türer (`sha256`), dosya adından değil. `params` anahtara girer. | `naming.py` zaten içerik-adresli adlandırma yapıyor; aynı içeriği iki kez yükleyen kullanıcı iki tam işlem ödememeli. |
| **D-13** | EXIF rotasyonu **oran kuralına uygulanır** (`MediaProbe.display_size`). | `exif_orientation6.jpg`: depolanan 1200×1600 (3:4, izinli), görünen 1600×1200 (4:3, izinsiz). `engine.py:102` çıktıda `exif_transpose` uyguluyor; kural da görünen ölçüye bakmalı. |
| **D-14** | DPI **ölçeğe girmez**. Ölçek yalnız uzun kenar tavanı ve megapiksel tavanından türer; `dpi_out` çıktı metadatasıdır. | `docs/standards/dpi-ve-cozunurluk.md`. `test_dpi_dususu_pikseli_dusurmez`: 3000×3000@300dpi → 2400×2400@72dpi; 720×720 YASAK. |
| **D-15** | **Büyütme yok.** Master girdiden büyük olamaz; masterdan büyük türev `upscale: true` ile işaretlenir, sessizce üretilmez. | `engine.optimize()` `im.thumbnail()` kullanıyor, zaten upscale yapmıyor (`test_policy_dpi.py`). |
| **D-16** | Pillow'da kalınıyor; pyvips'e geçilmedi. | `docs/reports/05-kutuphane-benchmark.md`: pyvips kutudan çıktığı hâliyle 0,94× yavaş, yalnız >20 MP'de (korpusun %3,7'si) kazanıyor, CMYK'de rengi bozuyor. |
| **D-17** | `media_engine` çekirdeğinde **modül düzeyinde `import frappe` yok**; yalnız `api/` içinde ve orada da tembel. | `test_cekirdekte_frappe_importu_yok` AST ile doğruluyor. Paket bench/site/DB olmadan test edilebilir kalır. |
| **D-18** | Güvenlik kararı politika kararını **ezer**: enfekte dosya politikayı geçse bile karantinaya gider. | `state.ingest_from_decision()`; `test_guvenlik_karari_politika_kararini_ezer`. |

---

## 4. Risk kaydı

Şiddet: **Y** = yüksek (üretime çıkışı engeller), **O** = orta, **D** = düşük.

### R-01 · Y · İki ayrı karar tipi yan yana duruyor

`tradehub_core/media/pipeline/contracts/policy.py` (paralel bir görevin çıktısı, `Protocol` + `dataclass`) ile
`tradehub_core/media/pipeline/policy/engine.py` (bu görevin çıktısı, somut uygulama) **aynı kavramları farklı
adlarla** tanımlıyor:

| Kavram | `contracts/policy.py` | `policy/engine.py` |
|---|---|---|
| ihlalin geldiği blok | `Violation.layer` | `Violation.block` |
| ölçülen değer | `Violation.measured` | `Violation.observed` |
| kararın izin alanı | `Decision.allowed` (property) | `Decision.allow` (alan) |
| ihlal açıklaması | `Violation.sebep` | `Violation.message` + `Violation.hint` |
| moderasyon aksiyonu | `manual_review` | `review` |

İki tip aynı anda yaşarsa çağıranlar hangisine bakacağını bilemez ve dönüşüm katmanı yazılır —
o katman da üçüncü bir hakikat olur. **Eylem:** tek tipe indirgenmeli; somut uygulamanın alan
adları `contracts`'a çekilmeli ya da tersi. Karar bir insana ait, kod yazana değil.
**Tetikleyici:** `api/` katmanı yazılmadan ÖNCE.

### R-02 · O · `review` ile `manual_review` iki yazım

Slot politikaları 12 kuralda `review` diyor; `content_rules.json` `decision_model.actions` ise
`manual_review` diyor. İkisini ayrı aksiyon saymak, bilinmeyen değerin `pass` seviyesine
düşmesine ve moderasyona gitmesi gereken dosyanın sessizce geçmesine yol açar.
**Bugünkü durum:** `core/errors.py` ikisini aynı sıraya ve ikisini de `BLOCKING_ACTIONS`'a bağladı
(`test_manual_review_ile_review_ayni_yukseklikte`). Bu bir **yama**; veri tarafında tek yazıma
inilmeli.

### R-03 · Y · Slot kimliği hâlâ istemciden gelmiyor

`upload_policy.check()` imzasında slot parametresi yok
(`docs/reports/00-upload-slot-envanteri.md` §7-B B1). PolicyEngine slot bekliyor ama onu
dolduracak bir yol yok. **Bu depodan çözülemez:** slot anahtarını gönderecek olan storefront
(`tradehubfront/`) ve admin panel (`admin-panel/frontend/`) SALT OKUNUR.
**Eylem:** iki frontend deposunda görev açılmalı; sunucu tarafında geçici çözüm olarak
`bound_to` eşleşmesinden (doctype + field) slot türetilebilir — 9 politikanın hepsinde
`bound_to` dolu. Bu türetme **yazılmadı**.

### R-04 · Y · 9/9 politika `status: draft`

| Slot | Şema | Durum | Açık soru |
|---|---|---|---|
| brand.logo | 1.2.0 | draft | 5 |
| seller.logo | 1.2.0 | draft | 5 |
| product.image | 1.0.0 | draft | 7 |
| product.video | 1.1.0 | draft | 6 |
| company.cover_image | 1.0.0 | draft | 6 |
| company.cover_video | 1.1.0 | draft | 8 |
| category.banner | 1.0.0 | draft | 6 |
| document.attachment | 1.0.0 | draft | 6 |
| user.avatar | 1.0.0 | draft | 6 |

Motor `status`'u **okuyor ama uygulamıyor**: `Decision.policy_status` alanında raporluyor,
kararı değiştirmiyor. Taslak bir politikayla gerçek kullanıcıyı reddetmek, canlı ölçümdeki
%48,6 uyumsuz `product.image` yüklemesinin yarısını kapıda döndürmek demektir.
**Eylem:** `status != "active"` iken `reject` → `warn`'a inen bir **gölge mod** (shadow mode)
gerekiyor. **BUGÜN YOK.** Yazılmadı çünkü gölge modun raporlama tarafı (kaç dosya reddedilecekti)
olmadan tek başına anlamsız; ikisi birlikte yazılmalı.

### R-05 · O · İçerik kurallarının %38'i ölçülemiyor

9 politikada toplam **72 `content_rules` örneği** var:

| Sınıf | Adet | Durum |
|---|---:|---|
| Künye metriğine bağlanmış | 16 | Motor değerlendiriyor |
| Yapısal olarak `accept`/`require` blokları kapsıyor | 29 | Kaybolmuyor, başka kapıdan uygulanıyor |
| **Değerlendirilemiyor** | **27** (25 farklı ad) | `skipped` → `not_measurable` |

Değerlendirilemeyenler piksel analizi istiyor (`entropy_bits`, `blur_laplacian_variance`,
`border_ratio`, `background_uniformity`, `text_area_ratio`, `watermark_suspect`,
`collage_suspect`, `duplicate_phash`, `safe_area_*`, `poster_mean_luma_out_of_range` …) ya da
sistem bağlamı istiyor (`optimizer_ran`, `attach_target_set`, `kvkk_field_map_complete`,
`rendered_as_css_background`, `tile_span_declared`).
`content_rules.json` kendi `calibration_status` alanında `UNCALIBRATED` diyor ve
`false_positive_budget = 0,05` hedefinin **ÖLÇÜLMEDİĞİNİ** yazıyor.
**Eylem:** `scripts/calibrate_content_rules.py` gerçek korpusla çalıştırılmadan bu kuralların
hiçbiri `reject` seviyesine çıkarılmamalı.

### R-06 · O · İki politika seti yan yana

`tradehub_core/media/pipeline/policy/slots/` (9 dosya, şema uyumlu) ile `docs/standards/policies/`
(`tests/test_policy_dpi.py`'nin okuduğu set) aynı anda duruyor. Hangisinin kanonik olduğu
**seçilmedi**. İki set ayrışırsa hangi sayının yürürlükte olduğu kimse için belli olmaz.
**Eylem:** tek kök seçilmeli; seçilmeyen ya silinmeli ya da açıkça "türetilmiş, elle
düzenlenmez" diye işaretlenmeli.

### R-07 · O · `appended_payload` taramasının yanlış pozitif oranı ölçülmedi

`upload_policy.is_dangerous()` yalnız dosyanın **başına** bakıyor (`upload_policy.py:224`);
geçerli bir JPEG'in **sonuna** eklenmiş `<script>` bu kontrolden geçiyor
(fixture `jpeg_with_html_tail.jpg`, `user.avatar` slotunda geometri kapıları da durdurmuyor).
`core/probe.py` bu boşluğu kapatıyor: JPEG'de EOI, PNG'de IEND sonrası kuyruk taranıyor.
**Ama** diğer biçimlerde kuyruk sınırı ucuza bilinemediği için **tüm gövdede** arama yapılıyor.
Yanlış pozitif oranı **ÖLÇÜLMEDİ** — korpusta bu yolla yanlış ret üreten dosya yok (51/51 uyum),
ama korpus 51 dosya; canlı 4.958 dosya.
**Eylem:** kural üretime alınmadan önce 4.958 dosyalık canlı korpusta taranmalı.

### R-08 · O · `InMemoryGuard` çok worker'lı üretimde işe yaramaz

`core/jobs.py` idempotency muhafızının **referans uygulaması süreç içidir**. Frappe kuyruğu
birden çok worker çalıştırır; süreç içi bir sözlük onları koordine edemez. Arayüz (`Protocol`)
taşıma katmanından bağımsız yazıldı, ama **Redis karşılığı yazılmadı**.
**Bugünkü koruma:** yalnız `transcode.py:178`'in durum alanına bakan ad-hoc kontrolü (yalnız video)
ve `jobs.STALE_AFTER_SECONDS` süre eşiği. **Çakışma anında durduran bir kilit üretimde yok.**

### R-09 · O · `existing_count` sözleşmesi uygulanmıyor

`require.max_count` kuralı, çağıranın **yüklemeden sonraki** toplam sayıyı geçmesini bekliyor
(sözleşme `_check_counts` içinde yazılı). Bugün bu değeri kimse doldurmuyor; kural
`skipped` → `not_measurable` olarak raporlanıyor. "12 mi 13 mü" hatası sessizce bir fazla dosya
kabul ettirir. **Eylem:** `api/` katmanı yazılırken bu sözleşme testle sabitlenmeli.

### R-10 · Y · Faz 3 sonunda canlıda hiçbir şey değişmedi

Bu, bir kusur değil kapsam gerçeğidir ama **kayda geçmelidir**:

| Ölçülen açık | Faz 3'teki durum |
|---|---|
| `th_media_width` dolu: **0/2853 (%0)** | Değişmedi — metadata yazan yol `image/` katmanında, İSKELET |
| Ürün detay sayfası **13,14 MB** görsel (900 KB hedefinin 15 katı) | Değişmedi — türev üretimi `image/`, İSKELET |
| **srcset/sizes: 31 görselin 0'ında** | Değişmedi — `delivery/` İSKELET ve storefront SALT OKUNUR |
| **1.166 yetim disk dosyası** | Değişmedi — bu fazın kapsamında değil |
| **179 dosya >20 MP, 38 CMYK, 597 alfa** | Motor artık bunlara ne yapılacağını **biliyor** (`normalized_targets`), ama **uygulayan yok** |

Karar katmanı ile uygulama katmanı arasındaki köprü (`api/` → `image/` → `storage/` → `delivery/`)
**dört iskelet paketten** ibaret. Faz 3'ün teslim ettiği şey **karar**, iş değil.

### R-11 · O · Video künyesi ffprobe'a bağlanmadı

`core/probe.py::probe_video_from_ffprobe()` **hazır bir sözlük** alıyor; ffprobe'u kendisi
çağırmıyor. Bu bilinçli (`transcode.py` zaten ffprobe çağırıyor, ikinci kez çağırmak israf),
ama **bağlantı yazılmadı**: bugün testler manifest'teki ölçülmüş kopyayı besliyor.
**Eylem:** `video/` katmanı yazılırken `transcode.py`'nin ffprobe çıktısı bu fonksiyona
bağlanmalı.

### R-12 · O · Aynı ağaçta paralel oturum çalışıyor

Bu görev yürürken aynı depoya başka bir oturum da yazdı: `tradehub_core/media/pipeline/contracts/`,
`tradehub_core/media/pipeline/fakes/`, `tradehub_core/media/pipeline/quality/`, `tradehub_core/media/pipeline/core/{crop,dedup,usage}.py`,
`tests/test_crop.py`, `tests/test_quality_ssim.py`. **`tradehub_core/media/pipeline/__init__.py` iki kez üzerine
yazıldı** ve bu görevin yazdığı içerik bir kez kayboldu (birleştirilerek geri kondu).
**Eylem:** paylaşılan dosyalar (`tradehub_core/media/pipeline/__init__.py`, `tests/` kökü) tek sahibe
bağlanmalı; aksi hâlde sessiz kayıp kaçınılmaz.

### R-13 · D · `MediaProbe` alan sayısı büyüyor

33 alanlı bir dataclass; her yeni kısıt türü bir alan daha ekliyor. Bugün okunabilir, ama
50 alanı geçerse "hangi alan kim tarafından dolduruluyor" sorusu cevapsız kalır.
**Eylem:** alanlar bloklara ayrılmalı (`geometry`, `security`, `video`) — bugün gerekmiyor.

---

## 5. Bilinçli olarak YAPILMAYANLAR

Bunlar unutulmadı; yapılmamaya karar verildi ve sebebi burada.

| Yapılmadı | Sebep |
|---|---|
| `upload_policy.check()`'in yeniden yazılması | Platform tabanı (ad/uzantı/deny-list/boyut) çalışıyor. PolicyEngine onun **üstüne** slot katmanı koyar; iki kapıdan ikisi de geçilmelidir. |
| `gates.py`'nin yeniden yazılması | Farklı soru: kapılar "dosyaya dokunulsun mu", PolicyEngine "kabul edilsin mi" der. Çakışma yok. |
| `engine.probe()`'un kopyalanması | `core/probe.py` onu **çağırır**. Kopyalamak iki Pillow yolu demekti. |
| Backoff/retry politikasının yeniden yazılması | `tradehub_core/media/jobs.py` sahibi; `media_engine` aynalar, test ayrışmayı düşürür (D-11). |
| `states.transition()`'ın yeniden yazılması | `File` kaydına yazan tek kapı bir tane olmalı. `core/state.py` yalnız **doğrular**, yazmaz. |
| ffprobe'un ikinci kez çağrılması | `transcode.py` zaten çağırıyor (R-11). |
| pyvips'e geçiş | Benchmark reddetti (D-16). |
| Piksel analizli içerik kuralları | Eşikler kalibre edilmedi (R-05). Kalibre edilmemiş eşiği çalıştırmak, çalışıyormuş gibi görünmesini sağlar. |

---

## 6. Kapanış ölçütü

Faz 3 için konan ölçüt: *"PolicyEngine GERÇEKTEN çalışmalı: 9 slot politikasını yükleyip
fixture'lara uygulayabilmeli. `bound_short999.jpg` REDDEDİLMELİ, `bound_short1000.jpg`
GEÇMELİ."*

| Ölçüt | Sonuç |
|---|---|
| 9 slot politikası yükleniyor | ✅ `PolicyRegistry` → 9/9 |
| Fixture'lara uygulanıyor | ✅ 51/51 manifest uyumu |
| `bound_short999.jpg` reddediliyor | ✅ `product_image_short_edge_too_small`, `observed=999`, `expected=1000` |
| `bound_short1000.jpg` geçiyor | ✅ `allow=True`, yalnız `master_under_spec` uyarısı |
| Her modül import edilebiliyor | ✅ `py_compile` + iki ortamda 84 test |
| Yeni slot için kod değişmiyor | ✅ çalışma anında onuncu politika ile kanıtlandı |

**Ölçüt karşılandı.** Ama §1'deki cümle geçerli: karar katmanı çalışıyor, hat bağlı değil.
Faz 4'ün ilk işi R-01 (tek karar tipi) ve R-03 (slot kimliği) olmalı; bu ikisi çözülmeden
`api/`, `image/`, `storage/`, `delivery/` katmanları yazılamaz.

---

## 7. Koşum

```bash
# Yerelde (bench/site GEREKMEZ)
cd /Users/ahmet/Desktop/istoc/tradehub_core
python3 -m unittest tests.test_policy_engine tests.test_state_machine -v

# Konteynerde. Dizin adı GÖREVE ÖZEL: `/home/frappe/olcum/faz3` altına paralel
# bir oturum farklı sahiplikle yazmış durumda ve üzerine yazılamıyor (R-12).
D=/home/frappe/olcum/faz3-t032-t035
docker exec istoc-dev-backend-1 bash -c "rm -rf $D; mkdir -p $D"
COPYFILE_DISABLE=1 tar -cf - media_engine tests tradehub_core/__init__.py tradehub_core/media \
  | docker exec -i istoc-dev-backend-1 tar -xf - -C $D
docker exec istoc-dev-backend-1 bash -c "cd $D && find . -name '._*' -delete &&
   /home/frappe/frappe-bench/env/bin/python tests/test_policy_engine.py &&
   /home/frappe/frappe-bench/env/bin/python tests/test_state_machine.py"
```

Son koşum (2026-08-18):

```
yerel      Python 3.9    / Pillow 11.3.0  →  38 + 46 = 84  OK
konteyner  Python 3.11.6 / Pillow 12.2.0  →  38 + 46 = 84  OK
regresyon  tests/test_policy_dpi.py (T-024, mevcut)  →  19  OK (1 beklenen hata)
```
