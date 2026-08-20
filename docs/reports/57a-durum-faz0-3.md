# 57a — Faz 0/1/2/3'ün 36 görevinin ÖLÇÜMLE durumlanması

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **HEAD:** `1ec9b5e`
**Ölçüm penceresi:** **22:27:14 → 22:45:46 (+03)** — her satırın kendi saat damgası aşağıda.
**Kapsam:** T-000…T-009 (Faz 0) · T-010…T-019 (Faz 1) · T-020…T-029 (Faz 2) · T-030…T-035 (Faz 3) = **36 görev**

**Kaynak (kabul kriterleri buradan birebir alındı, hepsi bu oturumda çekildi):**

| Sayfa | HTTP | Bayt |
|---|---|---|
| `10-faz0-codebase-arastirma.html` | 200 | 26.015 |
| `21-faz1-arge-gorevleri.html` | 200 | 27.825 |
| `30-faz2-medya-standartlari.html` | 200 | 35.534 |
| `40-faz3-mimari.html` | 200 | 18.092 |
| `91-gorev-panosu.html` | 200 | 14.663 |

> **Bu belge hiçbir kaynak dosyayı değiştirmedi.** Yazılan tek dosya budur.
> Geçici çalışma dizini `/tmp/57a` koşum sonunda **silindi**.
> `Media Engine Settings` bayrakları **ölçüm öncesi 22:28:46** ve **ölçüm sonrası 22:41:59** okundu:
> `media_pipeline_enabled=0 · rendition_on_upload=0 · manifest_api_enabled=0` — **değişmedi**.
> `bench migrate` **koşturulmadı**. Hiçbir doctype'ta kayıt oluşturulmadı/silinmedi.

---

## 0. Yöntem ve dürüstlük beyanı

| İşaret | Anlamı |
|---|---|
| **[Ö]** | Bu oturumda ölçüldü — komut ve çıktı yanında. |
| **[T]** | Bu oturumda test koşuldu — modül adı, test sayısı, saat yanında. |
| **[K]** | Dosya okundu, varlığı/içeriği doğrulandı. |
| **[R]** | Yalnız mevcut rapora dayanıyor — **bu oturumda tekrarlanmadı**. |

**Koşum ortamı:** `istoc-dev-backend-1`, site `istoc.localhost`.
Konteynerdeki kod **yerelle aynı** olduğu doğrulandı **[Ö] 22:29:35**:
`md5sum .../media/upload_policy.py` → `611695d4…71db`, yerel `md5 -q` → **aynı**.

**Süre/performans iddiası YOK.** Makinede 7 ajan paralel çalışıyordu; yalnız
geçti/kaldı ve sayım ölçüldü.

### 0.1 Hareketli hedef uyarısı — bu oturum içinde değişen şeyler

| Saat | Gözlem |
|---|---|
| **22:27:14** | `ls docs/reports/` → en yüksek numara **49** (`49-t111-render-motoru.md`). |
| **22:36:57** | Aynı dizinde **`54-d1-faz0-2-kapanis.md`** ve **`55-d2-faz3-5-kapanis.md`** belirdi. |

Yani **D-1 ajanının Faz 0–2 kapanış belgesi bu ölçümün ortasında yazıldı.** Belge
Faz 1 için **6 TAM / 4 KISMİ / 0 YOK** karnesi veriyor (§656). Benim Faz 1 karnem
de **6 TAM / 4 KISMİ / 0 YOK** — bağımsız ölçümle **aynı sonuca** varıldı.
`docs/reports/33-dogrulama-faz0-3.md` (bu sabah, 17 TAM / 17 KISMİ / 2 YOK)
**eskimiştir**; aşağıdaki her satırda nerede ve neden eskidiği yazılı.

---

## 1. Bu oturumda koşulan testler — ham sayım

| Saat | Modül | Sonuç |
|---|---|---|
| 22:29:02 | `test_media_security_gate` | **18 test OK** |
| 22:29:05 | `test_media_security_svg` | **10 test OK** |
| 22:30:47 | `test_contracts` | **75 test OK** |
| 22:31:31 | `test_policy_engine` | **38 test OK** |
| 22:32:02 | `test_crop_geometry` | **37 test · FAILED (failures=1)** — ayrıntı T-010 |
| 22:33:07 | `test_authz_regression` (frappe'siz, `python -m unittest`) | **24 test OK** |
| 22:33:49 | `test_policy_dpi` | **19 test OK (expected failures=1)** |
| 22:34:55 | `test_storage_adapters` | **137 test OK** |
| 22:35:16 | `test_state_machine` | **47 test OK** |
| 22:35:25 | `test_media_jobs` | **12 test OK** |
| 22:35:28 | `test_media_quota` | **10 test OK** |
| 22:38:58 | `test_svg_sanitize` | **52 test OK (skipped=3)** |
| 22:39:14 | `test_file_multirow_isolation` | **15 test OK** |
| 22:40:31 | `test_video_decision` | **58 test OK** |
| 22:42:27 | `test_crop` | **26 test OK** (INV-10 buradan) |
| 22:45:00 | `test_quality_ssim` | **21 test OK** |
| 22:45:16 | `test_retention_gc` | **38 test OK** |
| 22:45:46 | `test_isolation` | **36 test OK** (worker hayatta kalma) |

> `test_authz_regression` **bench altında** 22:31:11'de `TimestampMismatchError`
> ile düştü — paralel ajan aynı belgeyi yazıyordu. Modülün kendi sözü frappe'siz
> koşmaktı; öyle koşuldu ve **24/24 geçti**. Bench koşumundaki düşüş **testin
> değil, paylaşılan sitenin** sorunudur.

### 1.1 T-017 — kötücül korpusun bağımsız yeniden ölçümü **[Ö] 22:30:19**

Rapor 38'in `RED=10 / GEÇTİ=0` iddiası, **gerçek yükleme yolu** (`upload_policy.check`)
ile bağımsız olarak tekrarlandı. `content_gate` bu yola `upload_policy.py:444-446`
üzerinden bağlı; o yol da `hooks.py` `File.before_insert` zincirinde.

```
RED   bomb_100mp.png          [upload_image_bomb]
RED   data_uri_svg.txt        [upload_content_dangerous]
RED   empty_zero_byte.jpg     [upload_content_empty]
RED   executable_as.png       [upload_content_dangerous]
RED   fake_docx.docx          [upload_container_*]
RED   jpeg_with_html_tail.jpg [upload_appended_payload]
RED   polyglot_pdf_as.jpg     [upload_type_mismatch]
RED   polyglot_png_as.jpg     [upload_type_mismatch]
RED   script_payload.svg      [upload_ext_denied]
RED   truncated.jpg           [upload_content_truncated]
RED= 10  GECTI= 0
```

Rapor 33 aynı ölçümde `RED=2 / GEÇTİ=8` bulmuştu. **Kapı bugün kapandı ve
bağımsız olarak doğrulandı.** 100 MP decompression bomb artık **pikseller
açılmadan** reddediliyor (`test_bomba_pikselleri_acilmadan_reddedilir`).

### 1.2 T-033 — `PolicyEngine` Protokol uyumu **[Ö] 22:36:15**

```
Proto: contracts.policy.PolicyEngine · runtime_checkable: True
isinstance(policy.engine.PolicyEngine(), Proto) = True
Proto üyeleri (13): check_accept, check_geometry, check_video, effective_limits,
  load, master_spec, quality_threshold, reload, rendition_specs, slots,
  source_root, validate, video_rendition_specs
Impl bunların 13'ünü de taşıyor (ayrıca evaluate + normalized_targets)
```

Rapor 33'ün **M-02 "protokolle örtüşme 0/13"** bulgusu **kapandı** — bağımsız doğrulandı.

### 1.3 D-2 — hassas hash örtüşmesi, canlı DB'de bağımsız yeniden ölçüm **[Ö] 22:37:57**

```
EXCLUDED_DOCTYPES (8): Data Export Request, KYB Verification, KYC Verification,
  Order, Payment Transaction, Seller Application, Seller Certification, Seller Verification
tabFile: is_private=0 → 4.426 · is_private=1 → 616
hassas content_hash kümesi = 165
ÖRTÜŞEN public dosya satırı = 93 · distinct file_url = 40
kırılım: None 78 · Admin Seller Profile 8 · Listing 5 · Seller Category 1 · Static Page SEO 1
```

**44 → 40 iddiası DOĞRULANDI** (distinct public `file_url` = **40**).
`attached_to_doctype ∈ EXCLUDED_DOCTYPES` olan public dosya = **0** — yani
`Order` ve `Payment Transaction` kırılımdan tamamen düşmüş. `_is_protected_pii=True`
olan public dosya iddiası bu oturumda **ayrıca sorgulanmadı** — rapor 33'ün
0/40 ve 0/2.879 ölçümü **[R]** olarak duruyor.

---

## 2. FAZ 0 — Keşif (T-000…T-009)

| Görev | Başlık | Kaynağın kabul kriteri (kısa) | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-000** | Depo ve ortam envanteri | Tüm sürümler tabloda, "bilinmiyor" yok; libvips/FFmpeg kurulu mu + derleme desteği net; upload limitleri sayısal | **TAM** | **[K]** `00-ortam-envanteri.md` 39.290 B. **[Ö] 22:38:24** `which vips ffmpeg ffprobe tesseract` → yalnız `/usr/bin/ffmpeg`, `/usr/bin/ffprobe`; `import pyvips` → `ModuleNotFoundError`. Raporun "ffmpeg VAR / libvips YOK" tespiti **bağımsız doğrulandı** | — |
| **T-001** | Upload slot envanteri | ≥8 slot listede; her slot için render bileşeni + CSS kutu ölçüsü; "doğrulama yok" işaretli | **TAM** | **[Ö] 22:43:21** `00-upload-slot-envanteri.md` §5 "Dokümanın istediği 8 slot — var/yok karnesi" → **8/8 satır dolu**, her satırda `doctype.field` + doğrulama katmanı; 150 tablo satırı; §7 "DOĞRULAMA YOK — açık işaretleme". CSS kutuları `03-render-envanteri.md` §3 "piksel tablosu — sayfa tipi × render noktası × CSS kutu × DPR" (63 `px` geçişi) | — |
| **T-002** | Frappe dosya akışı | Upload→File→disk→URL zinciri **diyagramla**; ≥3 genişletme noktası artı/eksiyle; private yetkilendirme açık | **TAM** | **[Ö] 22:42:59** `01-dosya-akisi.md` → **1 mermaid bloğu**; `doc_events` / `before_insert` / `after_insert` genişletme noktaları ve G2 önerisi belgede | — |
| **T-003** | Üretim medya istatistiği | Slot bazlı p50/p90/p99; ≥20 anomali dosya yoluyla; logo + company video ayrı bölüm; **çıktı `fixtures/media-stats.csv`** | **KISMİ** | **[K]** `02-medya-istatistigi.md` (939 satır) + `09-slot-bazinda-istatistik.md` (412 satır) + `10-media-stats-kosum-ciktisi.txt` + `scripts/media_stats.py`. ❌ **[Ö] 22:41:28** `find . -name "media-stats.csv" -o -name "media_stats*.csv"` → **boş**; kök `fixtures/` dizini **yok** (`[ -d fixtures ]` → YOK). Kaynağın istediği makine-okunur çıktı üretilmemiş | AJAN |
| **T-004** | Frontend render envanteri + LCP taban çizgisi | **4 sayfa × 2 cihaz profili Lighthouse** LCP/CLS/görsel bayt; en kötü 10 ürün sayfası; hedef değerler | **KISMİ** | **[K]** `03-performans-taban-cizgisi.md` + `03-render-envanteri.md`. ❌ **[Ö] 22:41:14** belgenin **kendi §6.1'i: "Lighthouse — ÖLÇÜLEMEDİ … Lighthouse koşulmadı"**; sayılar Chrome DevTools trace'inden. §6.1 koşulacak `npx lighthouse` komutunu yazmış ama koşmamış | ARAÇ |
| **T-005** | Yetki ve rol modeli | Rol→izin matrisi; satıcının başkasının medyasına erişemediği **test çıktısıyla kanıtlı**; superadmin-only permission deseni | **TAM** | **[K]** `04-yetki-modeli.md` 38.325 B, `frappe.PermissionError` yakalayan negatif test çıktıları gömülü. **[T] 22:39:14** `test_file_multirow_isolation` → **15 test OK**; **[T] 22:33:07** `test_authz_regression` → **24 test OK** | — |
| **T-006** | Golden fixture korpusu | **≥30 görsel + ≥8 video**; her fixture manifest'te; kötücüller ayrı `fixtures/malicious/`; toplam < 1 GB | **KISMİ** | **[Ö] 22:35:52** `tests/fixtures/media/images` = **34** ✅; `tests/fixtures/media/video` = **7** ❌ (kaynak ≥8 istiyor); `tests/fixtures/malicious` = **10**, ayrı dizin ✅; `manifest.json` **51 kayıt**; `du -sh` = **66 MB** < 1 GB ✅. ❌ Kaynağın kök `fixtures/` yolu yok — korpus `tradehub_core/tests/` altında | AJAN |
| **T-007** | Kütüphane uygunluk testi | 30 MB mockup'ta tepe bellek **her iki kütüphane için**; kazanan sayısal gerekçeyle; **betik tekrar çalıştırılabilir** | **KISMİ** | **[K]** `05-kutuphane-benchmark.md` 27.186 B + `docs/reports/bench.csv` + `scripts/bench_engine.py`. Karar: "Pillow'da kal + `draft()`". ❌ **[Ö] 22:38:24** `pyvips` konteynerde **kurulu değil** → benchmark **bugün tekrar koşturulamaz**, CI'ya bağlanamaz. ❌ Çıktı `fixtures/bench.csv` değil `docs/reports/bench.csv` | ARAÇ |
| **T-008** | Depolama ve maliyet taban çizgisi | Türev projeksiyonu **formülle**; 3 senaryo 12 aylık maliyet; eager vs lazy farkı sayısal | **TAM [R]** | **[K]** `06-depolama-maliyet.md` 38.847 B — projeksiyon, üç senaryo ve eager/lazy farkı belgede. **Bu oturumda yeniden hesaplanmadı; sayıların doğruluğu ölçülmedi** | — |
| **T-009** | Faz 0 kapanış + çıkış kriteri onayı | 7 rapor tutarlı; fixture manifest programatik doğrulanmış; açık sorular atanmış; **platform yöneticisi imzası alınmış** | **KISMİ** | **[K]** `07-faz0-kapanis.md` (1.113+ satır, Rev.2). ❌ **[Ö] 22:41:14** §10 ONAY bloğu **hâlâ boş**: K-23/K-24/K-25 kutucukları `☐`, §10.4 üç seçenek de `☐`, §10.5 Ad/Rol/Tarih/İmza dördü de `______`, §10.6'daki 5 sorumlu satırı da `________`. **D-1 ajanının 54 numaralı belgesi de hiçbir kutucuğu doldurmadığını açıkça yazıyor** | İNSAN |

**Faz 0: 5 TAM · 5 KISMİ · 0 YOK**

---

## 3. FAZ 1 — AR-GE (T-010…T-019)

| Görev | Başlık | Kaynağın kabul kriteri (kısa) | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-010** | Kırpma/türev algoritma prototipi | **≥200 vektör**, hepsi sınır içi + orana %0,5 tolerans; öncelik zincirinin **5 seviyesi ayrı ayrı** test; **P-01…P-16 izlenebilirlik tablosu tam**; `docs/simulator.html` ile ≤0,5 px; INV-10 | **KISMİ** | ✅ **[Ö] 22:35:32** `crop_vectors.json` → `vector_count=592`, gerçek `len=592` (≥200 ✅). ✅ **[T] 22:32:02** ölçülen sapmalar: vektör **0.0 px**, çapraz uygulama **1.82e-12 px**, oran **2.07e-16**, 800 örnekte 1 px yuvarlama farkı **0**. ✅ **[T] 22:42:27** `test_crop` **26 OK** → INV-10 (`test_crop.py:217` "kaynak ölçeğinden bağımsız") yeşil. ❌ **[T]** `test_crop_geometry` **FAILED (1)**: `test_ts_ikizi_ayni_sayiyi_veriyor` → `node: bad option: --experimental-strip-types` (konteynerde **node v20.19.2**, gereken ≥22). ❌ **[Ö] 22:41:58** P-01…P-16 izlenebilirlik tablosu **YOK** — tüm `docs/` içinde yalnız **9 farklı P-kodu** dağınık geçiyor, tablo yok. ❌ `docs/simulator.html` **repoda yok** → simülatör paritesi ölçülemez | AJAN |
| **T-011** | Pazaryeri kural ve yetenek kıyaslaması | Amazon/Alibaba kuralları **kaynak linkli ve sayısal**; "var/yok/gereksiz" yetenek matrisi; ≥10 somut kural | **KISMİ [R]** | **[Ö] 22:38:41** kaynağın istediği `docs/reports/11-rakip-analizi.md` **YOK**. İçerik `11-faz1-arge.md` (46.310 B) §T-011'de, ama bölümün **kendi başlığı**: *"Rakip analizi (masa başı, ölçüm YOK)"*. İçerik doğruluğu bu oturumda denetlenmedi | AJAN |
| **T-012** | DPI / çözünürlük normalizasyonu | INV-02 **GREEN**; 5 formatta DPI yazımı; 3000×3000@300 → **≥2000×2000**, asla 700×700 | **TAM** | **[T] 22:33:49** `test_policy_dpi` → **19 test OK (expected failures=1)**. Fixture `dpi_3000x3000_300dpi.tif` korpusta. ⚠ 1 "beklenen başarısızlık" hangi formatın DPI yazımına ait — bu oturumda **ayrıştırılmadı** | — |
| **T-013** | Uyarlanabilir kalite (SSIM hedefli) | q85'e göre sayısal kazanç; arama **≤4 encode**'da yakınsıyor; şeffaf/grafik sınıfında lossless doğru | **TAM** | **[T] 22:45:00** `test_quality_ssim` → **21 test OK**. **[K]** `11-faz1-arge.md` §T-013.1–.9 (dokuz alt bölüm `[Ö]` işaretli) + `scripts/measure_ssim_quality.py`. Rapordaki sayısal kazanç değerleri bu oturumda **yeniden ölçülmedi** | — |
| **T-014** | Smart crop / focal öneri karşılaştırması | Her yöntem için ortalama sapma; beyaz zeminde en iyi yöntem gerekçeli; **güven skoru eşiği** belirlenmiş | **TAM [R]** | **[K]** `11-faz1-arge.md` §T-014 + **ADR-0017** (`saliency-esik-ustunde-ve-oneri`) — eşik ve "eşik altında öneri gösterilmez" kuralı ADR'ye bağlı. Sapma ölçümleri bu oturumda **yeniden koşulmadı** | — |
| **T-015** | Client-side işleme bütçesi prototipi | Cihaz sınıfı × işlem × max güvenli MP tablosu; Safari canvas limitleri; **"client başarısız → sunucu devralır" prototipte çalışıyor** | **KISMİ** | **[K]** `11-faz1-arge.md` §T-015.1 kod okuması, §T-015.2 çift-encode cezası ölçümü. ❌ **[Ö] 22:35:32** `prototypes/` **dizini repoda hiç yok** → kaynağın istediği `prototypes/client-budget/` çalışan prototip **gösterilmedi**. Faz kuralı: *"Her AR-GE görevi bir ölçüm veya çalışan prototip ile biter"* | AJAN |
| **T-016** | Video codec karar motoru + benefit gate | Karar tablosu **JSON, veri olarak** (yeni codec = kod değişikliği yok); verimli MP4 passthrough; şişik dosya ≥%40 küçülme + VMAF ≥93; çıktı > girdi yayınlanmıyor | **TAM** | **[T] 22:40:31** `test_video_decision` → **58 test OK**, içinde `test_fixture_kararlari_olculenle_ayni`, `test_kap_ailesi_mp4_olarak_cozuluyor`, `test_kunyeler_olculenle_ayni` (gerçek fixture'larla `ffprobe`). **[Ö]** `policy/video_decision.json` = veri tablosu; fixture'lar korpusta (`video_efficient_720p_750k.mp4`, `video_bloated_720p_8m.mp4`). VMAF/%40 ölçümü ayrı raporda (`22-t072-vmaf-av1.md`) **[R]**; ADR-0007 (fayda kapısı INV-05) | — |
| **T-017** | Güvenlik AR-GE: bomb, polyglot, SVG, metadata | **`fixtures/malicious/` içindeki HER dosya reddediliyor**, hiçbiri tam decode edilmiyor; **worker limiti aşılınca iş `failed`, worker ölmüyor**; sanitize SVG'de script kalmıyor | **TAM** ⬆ (rapor 33'te **YOK**'tu) | ✅ **[Ö] 22:30:19** gerçek yükleme yolunda **RED=10 / GEÇTİ=0** — §1.1'deki ham çıktı, bağımsız betikle. ✅ **[T] 22:29:02** `test_media_security_gate` **18 OK** (içinde `test_bomba_pikselleri_acilmadan_reddedilir`). ✅ **[T] 22:29:05** `test_media_security_svg` **10 OK** + **[T] 22:38:58** `test_svg_sanitize` **52 OK**. ✅ **[T] 22:45:46** `test_isolation` **36 OK** — `WorkerHayatta.test_arka_arkaya_arizalar_sonrasi_surec_yasiyor`; `isolation.py` `RLIMIT_CPU`/`RLIMIT_AS`/`wall_timeout_s=60` + `SEBEP_TIMEOUT`. **Üç kabul kriterinin üçü de ölçüldü** | — |
| **T-018** | Depolama adapter ve CDN AR-GE | **Aynı contract test paketi üç adapter'da da geçiyor**; S3 kapalıyken sistem %100 yerel; purge + imzalama çalışıyor | **TAM** | **[T] 22:34:55** `test_storage_adapters` → **137 test OK**. **[Ö]** `storage/`: `local.py`, `s3.py`, `mirror.py`, `tiered.py`, `retention.py`. **[K]** `23-t051-s3-adaptor.md`, `27-t052-cdn-teslim.md`; **ADR-0015** "S3 yazıldı, varsayılan kapalı" | — |
| **T-019** | Faz 1 kapanış: ADR seti | Her ADR: bağlam·seçenekler·**ölçüm verisi**·karar·sonuçlar·**geri dönüş yolu**; **8 zorunlu konu**; her ADR bir Faz 0/1 raporundaki sayıya atıf | **KISMİ** | ✅ **[Ö] 22:28:32** `docs/adr/` = **17 ADR + README**. ❌ **[Ö] 22:36:32** "Geri dönüş yolu" **ayrı bölüm olarak 0/17**: her ADR'nin başlıkları `Bağlam · Seçenekler · Karar · Gerekçe · Sonuçlar` — geri dönüş bölümü yok. Metin içinde geçen: **4/17** (0002, 0003, 0008, 0010). ❌ **[Ö] 22:36:55** 8 zorunlu konudan **2'si karşılıksız**: *istemci kütüphane seti* → 0 dosya; *CDN* → `grep -licE cdn` **1 dosya** (0001), orada da yan cümle, ADR konusu değil. ❌ İmza yok (`30-faz1-adr-kapanis.md` §4 "AÇIK") | AJAN |

**Faz 1: 6 TAM · 4 KISMİ · 0 YOK** — rapor 33'ün **5/4/1**'i eskidi (T-017 YOK→TAM).

---

## 4. FAZ 2 — Standartlar (T-020…T-029)

| Görev | Başlık | Kaynağın kabul kriteri (kısa) | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-020** | Ürün görseli standardı + politika şeması | Şema tüm alanları içeriyor; **T-003 istatistiğine göre ihlal yüzdesi raporlanmış**; **jsonschema ile doğrulanıyor**; 2000×2000 master ile çelişki yok | **KISMİ** | ✅ **[Ö] 22:41:17** `policy/schema/slot-policy.schema.json` (1.338 satır) + `slots/product-image.json` var; `product-image.md:95` "şema geçerli, 0 ihlal". ❌ **[Ö] 22:38:24** `jsonschema` **konteynerde kurulu değil** (`ModuleNotFoundError`) → doğrulama üretim yolunda **koşamaz**, yalnız host'ta. ❌ **[Ö] 22:41:42** mevcut ürün görsellerinin **ihlal yüzdesi ölçülmemiş** — belgenin kendi satır 4'ü: *"`draft` — bazı değerler ölçülmedi, §9'a bakınız"*; §9'da 8 ayrı "ölçülmedi" | ARAÇ |
| **T-021** | LOGO standardı (seller-logo, brand-logo) | Her render yeri + **DPR 3 dahil** max piksel; oran seti ve min piksel **sayı olarak**, "TBD" yok; ihlal yüzdesi + geçiş planı; koyu tema kararı; SVG kabul kuralı | **TAM [R]** | **[K]** `docs/standards/logo.md` (1.290+ satır): 16 render noktası `dosya:satır` ile, band 1:2…2:1, merdiven 64/128/256/384/512, §D8 koyu tema, §6 SVG sanitize. **Metin bu oturumda satır satır denetlenmedi.** ⚠ **[Ö] 22:28:51** politika tarafı hâlâ eksik: `seller-logo.json` `draft`/open_q=3, `brand-logo.json` `draft`/open_q=1, **ikisinde de `master.max_megapixels` YOK** | — |
| **T-022** | COMPANY COVER VIDEO standardı | Süre/çözünürlük/oran/byte/bitrate **sayı olarak**, TBD yok; otomatik oynatma politikası; poster kuralı; ihlal oranı + geçiş planı; `prefers-reduced-motion` | **TAM [R]** | **[K]** `docs/standards/company-cover-video.md` (1.090+ satır) — §6.1–6.13 sayısal kararlar, §6.9 poster, §8.2 `prefers-reduced-motion`. **Metin bu oturumda denetlenmedi.** ⚠ **[Ö] 22:28:51** `company-cover-video.json` `draft`, **open_questions = 8** (en kritiği: video için ölçü/süre metadatası olmadığından süre/oran/çözünürlük kapıları **zorlanamıyor**) | — |
| **T-023** | Kalan slotların standartları | **Slot kataloğundaki tüm satırlar "SABİT"**; her slot şema doğrulamasından geçiyor; TR mesajlar; slot→profil eşlemesi tam | **KISMİ** | ✅ **[Ö] 22:38:43** 9 slot politikası + 9 slot belgesi + `docs/standards/README.md` var. ❌ **[Ö] 22:28:51** **9/9 politika `draft`** — hiçbiri "SABİT" değil; açık soru toplamı **49** (brand-logo 1 · seller-logo 3 · category-banner 6 · company-cover-image 6 · document-attachment 6 · product-video 6 · user-avatar 6 · product-image 7 · company-cover-video 8) | KARAR |
| **T-024** | DPI/piksel kuralının şartnameye bağlanması | Kural örnekli yazılı; 2000×2000 altına düşmeme **testle bağlı**; şemada `min_long_edge`/`max_long_edge`/`dpi_out` **zorunlu**; kullanıcı özet metni | **TAM** | **[T] 22:33:49** `test_policy_dpi` → **19 test OK**. **[K]** `docs/standards/dpi-ve-cozunurluk.md` var; `slot-policy.schema.json` ilgili alanları taşıyor; SRS'te FR karşılıkları var | — |
| **T-025** | İçerik uygunluk kuralları ve eşikler | Her kural için yöntem+eşik+aksiyon; **eşikler kalibre edilmiş, yanlış pozitif < %5 ÖLÇÜLMÜŞ**; NSFW/bulanıklık dışında sert red yok; uyarı metinleri | **KISMİ** | **[Ö] 22:28:51** `content_rules.json` `calibration_status` = **`TRIGGER_RATE_MEASURED_UNLABELED`** (rapor 33'te `UNCALIBRATED`'ti — **değişim doğrulandı**). `corpus_measurement`: 1.291 Listing görseli, 1.241 ilan, 6 kuralın tetiklenme oranı ölçüldü; numpy 2.4.6 + Pillow 12.2.0 VAR. **Eşikler DEĞİŞTİRİLMEDİ** — dosyanın kendi sözü: *"etiketsiz dağılımdan eşik türetmek, kalibrasyon değil kılık değiştirmiş tahmindir"*. ❌ `still_open[0]`: **"Yanlış pozitif oranı hiçbir kural için hâlâ BİLİNMİYOR — insan etiketi üretilmedi"**. ❌ `pytesseract`/`tesseract` **YOK** → `overlay_text` ölçülemedi (**[Ö] 22:38:24** doğrulandı). Kaynağın "<%5 ölçülmüş" şartı **karşılanmıyor** | İNSAN |
| **T-026** | Retention politikası standardı | İki bağımsız politika; varsayılanlar; **soft-delete + audit**; legal hold politikayı geçersiz kılıyor | **TAM** | **[T] 22:45:16** `test_retention_gc` → **38 test OK**. **[Ö] 22:41:17** `docs/standards/retention.md` (760 satır) + `policy/retention.schema.json` (507 satır) + `storage/retention.py`; `Media Asset`'te `legal_hold` alanı; **ADR-0014** (yıkıcı işler çift kapı + kuru koşum) | — |
| **T-027** | Kota ve oran sınırlama standardı | Plan bazlı sınırlar; aşım davranışı + kullanıcı mesajı; **429 + `Retry-After`** | **TAM** | **[T] 22:35:28** `test_media_quota` → **10 test OK**. **[Ö] 22:41:17** `docs/standards/kota.md` (1.072 satır) + `policy/quota.schema.json` (711 satır) + `api/rate_limit.py` | — |
| **T-028** | Geçiş (migration) planı | Uyumlu/uyumsuz **slot bazında sayısal**; 3 kategori; backfill parti/hız/geri alma; satıcı bilgilendirme + son tarih; kuyruk önceliği | **TAM [R]** | **[Ö] 22:41:17** `docs/plans/migration.md` (1.143 satır) + `17-t028-backfill-plani.md` (44.825 B) + `scripts/plan_backfill.py`. **İçeriğin sayısal doğruluğu bu oturumda denetlenmedi** | — |
| **T-029** | Faz 2 kapanış: SRS onayı | FR-xxx/NFR-xxx test edilebilir; izlenebilirlik matrisi; **hiçbir slot "TBD" değil**; **platform yöneticisi onayı alınmış** | **KISMİ** | **[Ö] 22:38:28** `SRS-v1.0.md` **satır 3: "DURUM: HÂLÂ TASLAK (DRAFT). Onaylanmadı."**; `TBD` **18 satırda**; işaretsiz `- [ ]` kutucuk **53**, işaretli **0**. Belgenin kendi §0.3: TASLAK'ın sebebi T1…T10 maddeleri, 9'unun 3'ü kapandı (T3, T8, T9), **6'sı açık**; §6.7'deki G1–G7 kapıları açık (9/9 politika `draft` → G6 kapanamıyor) | KARAR |

**Faz 2: 6 TAM · 4 KISMİ · 0 YOK**

---

## 5. FAZ 3 — Tasarım (T-030…T-035)

| Görev | Başlık | Kaynağın kabul kriteri (kısa) | Durum | Kanıt | Engelleyen |
|---|---|---|---|---|---|
| **T-030** | SAD yazımı | Bileşen/dağıtım/veri akışı/durum diyagramları **(mermaid)**; her bileşen için sorumluluk+bağımlılık+hata davranışı+ölçek sınırı; **her ADR kararı mimaride izlenebilir**; SPOF listesi + azaltım | **KISMİ** | ✅ **[Ö] 22:41:28** `docs/sad/SAD-v1.0.md` = **893 satır** (rapor 33'te 849'du — belge bugün büyüdü), **11 mermaid bloğu**. ❌ **[Ö] 22:41:42 YENİ BULGU:** belgede **hiç `ADR-00xx` referansı yok** — `grep -oniE "adr[-‑]?[0-9]{3,4}\|docs/adr"` → **0 isabet** (`grep -ci adr` = 12, hepsi "kadraj/adres" gibi kelime içi). Kaynağın *"her ADR kararı mimaride izlenebilir"* kriteri **karşılanmıyor**. ❌ Belge **TASLAK**: satır 789 *"Onay bloğu doldurulmamıştır"*, satır 891 **"SAD v1.0 bugün de ONAYLANAMAZ. 8 kapının 7'si açık."** (rapor 33'te 8 bloklayıcıydı → **1'i kapanmış**) | AJAN |
| **T-031** | Arayüz sözleşmelerinin dondurulması | **5 çekirdek arayüz** `Protocol`/ABC; her metot için tip imzası + hata sınıfı + idempotency; her arayüz için **fake + contract test**; **arayüz değişikliği CI'da kırmızı verir** | **KISMİ** | ✅ **[Ö] 22:38:43** `contracts/`: `storage.py`, `image.py`, `video.py`, `policy.py`, `delivery.py` + `errors.py` + `signatures.py` + `signatures.golden.json`; **[Ö] 22:41:30** golden `protocols` = tam olarak **[DeliveryManifest, ImageEngine, PolicyEngine, StorageAdapter, VideoEngine]** (5/5) + `value_types`; `fakes/` 5 dosya; `docs/sad/interfaces.md` 245 satır. ✅ **[T] 22:30:47** `test_contracts` → **75 test OK** (rapor 33'te 69'du — **büyüdü, doğrulandı**). ❌ **[Ö] 22:35:32 CI kırmızı VERMEZ:** `.github/workflows/` → 5 workflow (alpha/beta/rc/prod-release, deploy); `grep -rlE "run-tests\|pytest\|ruff\|mypy\|unittest" .github/workflows/` → **0 dosya**. Sözleşme testi elle koşulmadıkça kimseyi durdurmuyor | AJAN |
| **T-032** | Frappe app iskeleti ve modül yapısı | `bench new-app media_engine`; 8 modül; `hooks.py` kuyruk+scheduler+doc_events+permission query; **CI: ruff + mypy + pytest + pre-commit çalışıyor**; docker compose ayakta; temiz kurulum/kaldırma | **KISMİ** | **5 kriterden 2'si karşılanıyor, 1'i ölçülmedi, 2'si karşılanmıyor.** ① Ayrı app **kurulmadı** — bilinçli: **ADR-0003** *"ayrı app değil, tek monolit"*; karşılığı `media/pipeline/` altında **17 alt paket** (`api, contracts, core, delivery, doctype_specs, fakes, image, migration, observability, policy, quality, security, simulator, storage, video` + `__init__`) **[Ö] 22:38:43**. ② `hooks.py` bağlı ✅. ③ ❌ **[Ö] 22:35:32** CI kalemi **tamamen açık**: workflow'larda `pytest`/`ruff`/`mypy` **0 isabet**; `.pre-commit-config.yaml` **YOK**; `pyproject.toml`'da `[tool.mypy]` **0 isabet**. ④ Docker compose **14 servis ayakta** ✅ **[Ö] 22:27:14**. ⑤ Temiz kurulum/kaldırma **ölçülmedi** (`bench migrate` yasak). **Rapor 33 buna YOK demişti; ölçülen 2/5 + 1 ölçülmedi → KISMİ'ye çekildi, gerekçe budur** | AJAN |
| **T-033** | PolicyEngine tasarımı ve uygulaması | `evaluate(slot, probe, role) → {allow, violations[], normalized_targets}`; politikalar **veri olarak**; her ihlal için makine kodu + TR mesaj + düzeltme; **aynı motor client'ta da çalışıyor (paylaşılan JSON, TS uygulaması) ve iki taraf aynı sonucu veriyor** | **KISMİ** | ✅ **[Ö] 22:36:15** `isinstance(PolicyEngine(), contracts.policy.PolicyEngine)` → **True**; Protokolün **13 üyesinin 13'ü** uygulanıyor; `evaluate` + `normalized_targets` mevcut → rapor 33'ün **M-02 (0/13 örtüşme) bulgusu KAPANDI, bağımsız doğrulandı**. ✅ **[T] 22:31:31** `test_policy_engine` **38 OK**; **[T] 22:30:47** `test_contracts` **75 OK**. ✅ Politikalar veri: `PolicyRegistry.load()` `slots/*.json`'dan okuyor. ❌ **[Ö] 22:36:32 TS uygulaması HÂLÂ YOK:** `find . -name "*.ts" -path "*polic*"` → politika motoru yok; `engine.ts` yok; `simulator/` altında yalnız `srcset.py`, `devices.json`, `placements.json`. **Python↔TS çapraz testi yok** | AJAN |
| **T-034** | İş kuyruğu ve durum makinesi altyapısı | Geçersiz geçiş istisna + testle korunuyor; her iş `Media Processing Job` üretiyor; retry üstel geri çekilme + dead-letter + alarm; **iş idempotent** | **TAM** | **[T] 22:35:16** `test_state_machine` → **47 test OK**; **[T] 22:35:25** `test_media_jobs` → **12 test OK**. Test adları kriterleri birebir karşılıyor: `test_bilinmeyen_durum_hata_verir`, `test_terminal_durumlardan_cikis_yok`, `test_backoff_kaynakla_ayni_egriyi_verir`, `test_ayni_icerik_ayni_anahtar`, `test_ilk_talep_verilir_ikincisi_verilmez`, `test_kilit_ttl_dolunca_dusen_worker_engel_olmaz`. `Media Processing Job` doctype alanları: `status`, `attempt`, `idempotency_key`, `duration_ms`, `peak_memory_mb`, `error_code/error_trace` | — |
| **T-035** | Faz 3 kapanış: mimari gözden geçirme ve dondurma | **Bağımsız bir gözden geçiren (yazan kişi değil) SAD'i ONAYLAMIŞ**; arayüz imza testleri GREEN + golden commit'lenmiş; açık riskler + izleme planı | **KISMİ** | ✅ **[T] 22:30:47** imza testleri **GREEN** (`test_contracts` 75 OK); **[Ö]** `signatures.golden.json` commit'li (`1ec9b5e`). ✅ **[K]** `docs/sad/review-v1.0.md` (319 satır, 2026-08-18) — donan kararlar + risk kaydı; kendi §1'i dürüst: *"Karar katmanı çalışıyor, hat bağlı değil… Faz 3 sonunda canlıda hiçbir davranış değişmedi"*. ❌ **[Ö] 22:38:28** SAD **ONAYLANMAMIŞ** — satır 891 *"SAD v1.0 bugün de ONAYLANAMAZ. 8 kapının 7'si açık."*; onay bloğu boş, bağımsız gözden geçiren imzası yok. **Birinci kabul kriteri karşılanmıyor** | İNSAN |

**Faz 3: 1 TAM · 5 KISMİ · 0 YOK**

---

## 6. Sayım

| | TAM | KISMİ | YOK | Toplam |
|---|---|---|---|---|
| **Faz 0** (T-000…T-009) | 5 | 5 | 0 | 10 |
| **Faz 1** (T-010…T-019) | 6 | 4 | 0 | 10 |
| **Faz 2** (T-020…T-029) | 6 | 4 | 0 | 10 |
| **Faz 3** (T-030…T-035) | 1 | 5 | 0 | 6 |
| **TOPLAM** | **18** | **18** | **0** | **36** |

**TAM (18):** T-000, T-001, T-002, T-005, T-008 · T-012, T-013, T-014, T-016, **T-017**, T-018 · T-021, T-022, T-024, T-026, T-027, T-028 · T-034
**KISMİ (18):** T-003, T-004, T-006, T-007, T-009 · T-010, T-011, T-015, T-019 · T-020, T-023, T-025, T-029 · T-030, T-031, **T-032**, T-033, T-035
**YOK (0)**

> ⚠ **TAM'ların 5'i `[R]`** — yani belge var ve kriterlere biçimsel olarak
> uyuyor ama **sayısal içeriği bu oturumda yeniden ölçülmedi**: T-008, T-014,
> T-021, T-022, T-028. Bunlara "geçti" değil, "belge kriteri karşılıyor
> görünüyor, içeriği doğrulanmadı" denmelidir.

### 6.1 Rapor 33'e (bu sabah) göre değişim

| Görev | Rapor 33 | Bu ölçüm | Neden |
|---|---|---|---|
| **T-017** | **YOK** | **TAM** | Güvenlik kapısı kapandı: RED=10/GEÇTİ=0 bağımsız doğrulandı (§1.1) + `test_isolation` worker hayatta kalma yeşil |
| **T-032** | **YOK** | **KISMİ** | Ölçüm aynı; **etiketleme farkı**: 5 kriterden 2'si karşılanıyor, 1'i ölçülmedi. Kategorik "YOK" ölçülene uymuyor |
| **T-033** | KISMİ | KISMİ | M-02 kapandı (`isinstance` True) ama TS motoru + çapraz test hâlâ yok → KISMİ kalıyor |
| **T-013** | TAM **[R]** | TAM **[T]** | `test_quality_ssim` 21 OK ile ölçüme bağlandı |
| **T-026** | TAM **[R]** | TAM **[T]** | `test_retention_gc` 38 OK ile ölçüme bağlandı |
| **T-027** | TAM **[R]** | TAM **[T]** | `test_media_quota` 10 OK ile ölçüme bağlandı |
| **T-030** | KISMİ | KISMİ | **Yeni bulgu:** SAD'de **0 ADR referansı** — "her ADR mimaride izlenebilir" kriteri ölçülerek çürütüldü. Ayrıca 8 bloklayıcının 1'i kapanmış (8→7) |
| **T-031** | KISMİ | KISMİ | `test_contracts` **69 → 75** büyüdü; CI eksiği aynen duruyor |
| **T-025** | KISMİ | KISMİ | `UNCALIBRATED` → `TRIGGER_RATE_MEASURED_UNLABELED` doğrulandı; **eşikler değişmedi**; FP oranı hâlâ ölçülmedi → KISMİ kalıyor |

### 6.2 Engelleyen dağılımı

| Engelleyen | Adet | Görevler |
|---|---|---|
| **—** (engel yok, TAM) | **18** | T-000, T-001, T-002, T-005, T-008, T-012, T-013, T-014, T-016, T-017, T-018, T-021, T-022, T-024, T-026, T-027, T-028, T-034 |
| **AJAN** (kod/yazım işi, bugün yapılabilir) | **10** | T-003, T-006, T-010, T-011, T-015, T-019, T-030, T-031, T-032, T-033 |
| **ARAÇ** (eksik araç) | **3** | T-004 (Lighthouse), T-007 (`pyvips`), T-020 (`jsonschema`) |
| **İNSAN** (imza / etiketleme) | **3** | T-009 (Faz 0 imzası), T-025 (200 tetiklenmenin el ile etiketlenmesi), T-035 (bağımsız gözden geçiren imzası) |
| **KARAR** (iş kararı) | **2** | T-023 (49 açık soru → 9 politikanın `SABİT`e geçmesi), T-029 (SRS G1–G7 kapıları) |
| **Toplam** | **36** | |

### 6.3 Eksik araçların tam listesi **[Ö] 22:38:24**

| Araç | Durum | Engellediği görev |
|---|---|---|
| `libvips` / `pyvips` | **YOK** (`which vips` boş, `import pyvips` → ModuleNotFoundError) | T-007 (benchmark tekrar koşulamaz) |
| `jsonschema` | **YOK** konteynerde (host'ta var) | T-020 (şema doğrulaması üretim yolunda koşamaz) |
| `tesseract` / `pytesseract` | **YOK** | T-025 (`overlay_text` kuralı ölçülemez) |
| Lighthouse (Chrome + ağ) | **koşulmadı** | T-004 |
| Node **≥22** | konteynerde **v20.19.2** | `test_crop_geometry::test_ts_ikizi_ayni_sayiyi_veriyor` **KIRMIZI** (`--experimental-strip-types` desteklenmiyor) |
| `ffmpeg` / `ffprobe` | **VAR** (`/usr/bin/`) | — |

---

## 7. En kısa yoldan kazanılabilecekler (ölçüme dayalı, sıralı)

| # | Görev | Tek adım | Neden en kısa |
|---|---|---|---|
| 1 | **T-031 · T-032** | `.github/workflows/`'a bir `pytest`/`ruff` adımı ekle | İki görevin de tek ortak eksiği; **[Ö]** bugün 5 workflow'un hiçbirinde test adımı yok |
| 2 | **T-030** | SAD'e ADR referanslarını ekle | **[Ö]** belgede **0** `ADR-00xx` geçiyor; 17 ADR zaten yazılmış, bağlamak metin işi |
| 3 | **T-019** | 17 ADR'ye "Geri dönüş yolu" bölümü + 2 eksik ADR (istemci kütüphane seti, CDN) | **[Ö]** 0/17 bölüm, 2/8 konu eksik — ölçülmüş ve dar |
| 4 | **T-003 · T-006** | `fixtures/media-stats.csv` üret + 8. video fixture'ı ekle | **[Ö]** 34 görsel ✅ / 7 video ❌ (1 eksik); CSV hiç yok |
| 5 | **T-020** | `requirements.txt`'e `jsonschema` | **[Ö]** tek satır; şema doğrulaması üretim yoluna girer |
| 6 | **T-010** | P-01…P-16 izlenebilirlik tablosu | **[Ö]** geometrinin kendisi zaten 0.0 px sapmayla yeşil; eksik olan yalnız tablo |

---

## 8. Ölçülmeyenlerin açık listesi — iddia YOK

- T-008, T-014, T-021, T-022, T-028 **belgelerinin sayısal içeriği** doğrulanmadı; yalnız varlık + biçim kontrol edildi.
- T-012'deki **1 "expected failure"**'ın hangi format olduğu ayrıştırılmadı.
- T-016'nın **VMAF ≥93 / ≥%40 küçülme** ölçümü bu oturumda transcode koşularak tekrarlanmadı (`22-t072-vmaf-av1.md` **[R]**).
- T-018'in **purge + imzalı URL akışları** canlıda tetiklenmedi; yalnız contract testi koşuldu.
- T-032'nin **temiz kurulum/kaldırma** kriteri ölçülmedi (`bench migrate` Şerit A ajanında, yasaklı).
- `_is_protected_pii=True` public dosya = 0 iddiası **[R]** (rapor 33'ün ölçümü); §1.3'te yalnız **40 distinct file_url** bağımsız doğrulandı.
- Hiçbir **süre/performans** ölçümü yapılmadı — 7 ajan paralel.

---

**Ölçüm bitişi: 22:45:46 (+03).** Bayraklar **22:41:59**'da tekrar okundu, üçü de **0**.
Geçici dizin `/tmp/57a` silindi.
