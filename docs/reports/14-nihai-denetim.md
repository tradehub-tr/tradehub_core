# 14 — Nihai Bütünlük Denetimi

**Tarih:** 2026-08-18 · **Depo:** `tradehub_core` · **Dal:** `ahmet`
**Kapsam:** `tradehub_core/media/pipeline/` + `tests/` + `docs/` altında bu çalışmada üretilen HER ŞEY.
**Denetleyenin kuralı:** Her "tamam" iddiasının yanında bu makinede koşulmuş bir komut
çıktısı ya da `dosya:satır` vardır. Kanıt yoksa **KANIT YOK** yazılıdır. Sayı
üretilmediyse **ÖLÇÜLMEDİ** yazılıdır.

---

## 0. ÖNCE KIRIK OLANLAR

Sıra ciddiyete göre.

| # | Bulgu | Kanıt | Etki |
|---|---|---|---|
| **B1** | **Testler 18 koşumun 1'inde kırıldı.** Bu denetimde suite **18 kez** baştan sona koşuldu. **17 koşum `OK`, 1 koşum `FAILED (failures=1, skipped=70, expected failures=1)`.** Kırılan testin adı o koşumda yakalanamadı (stdout atılmıştı) ve sonraki 15 koşumda tekrar üretilemedi. | 18 koşum kaydı; kırık koşum `-v` biçiminde | **Suite kararsız (flaky), oran ≈ %5,6.** CI'ya bu hâliyle bağlanırsa rastgele kırmızı üretir. Kırılan test bulunmadan Faz 14 "tüm testler yeşil" denemez. |
| **B2** | **`media_engine` hiçbir yere bağlı değil — üretimde sıfır erişimi var.** `grep -n media_engine tradehub_core/hooks.py` → **0 sonuç**. `grep -rn whitelist tradehub_core/media/pipeline/api/*.py` → tek `@frappe.whitelist()` yok, hepsi "Saf Python — `@frappe.whitelist()` YOK" diyor. `ls tradehub_core/tradehub_core/doctype/ \| grep -i media` → **0 sonuç**; 15 DocType spesifikasyonunun hiçbiri kurulmadı. | `tradehub_core/media/pipeline/api/__init__.py:3-4`, `tradehub_core/media/pipeline/api/delivery.py:77` | 31.152 satır Python **hiçbir isteğe cevap vermiyor**. Motor değil, kütüphane. Üretime mesafe buradan ölçülür. |
| **B3** | **Video kodeği üzerinde üç ayrı katman üç ayrı şey söylüyor.** Faz 2 slot politikaları birincil teslimi **VP9/WebM** yazıyor; Faz 7 karar tablosu ve transcode kodu birincil hedefi **H.264/MP4** yazıyor ve *"vp9 de bu kurala TAKILIR ve H.264'e döner"* diyor; Faz 3'te dondurulan sözleşme hâlâ `libvpx-vp9`/`webm` varsayılanı taşıyor; Faz 8 teslim katmanı `("webm", "mp4")` sırasıyla WebM'i birincil sunuyor. | `tradehub_core/media/pipeline/policy/slots/product-video.json:132`, `video_decision.json:129,251-253`, `tradehub_core/media/pipeline/video/transcode.py:88`, `tradehub_core/media/pipeline/contracts/video.py:175-176`, `tradehub_core/media/pipeline/delivery/manifest.py:67` | Bugün kodlansa **üretilen dosya ile teslim edilen `<source type>` uyuşmaz.** Ayrıntı §7.1. |
| **B4** | **Ölçülmüş `sizes` tablosu üretim yoluna bağlı değil.** `delivery/sizes.py` 5 yerleşim için ölçülmüş kutu genişlikleri taşıyor ve `install(builder)` fonksiyonu var; ama `api/delivery.py` yalnız `manifest`i çağırıyor, `manifest.py:76` `SIZES_TABLE` **boş** ve `sizes_source: UNMEASURED` yazıyor. Hiçbir üretim modülü `delivery.sizes`'ı import etmiyor. | `tradehub_core/media/pipeline/api/delivery.py:34-35`, `tradehub_core/media/pipeline/delivery/manifest.py:76-77`, `sizes.py:438` | T-121 ölçüldü ama **yanıta yazılmıyor**; teslim edilen `<img>` `sizes` özniteliği boş kalır. Faz 12'nin ana kazancı devre dışı. |
| **B5** | **`media_engine` lint kapısından geçmiyor: 1.036 ruff bulgusu.** Aynı config ile `tradehub_core/` (çalışan üretim uygulaması) **35**, `tests/` **48**. | `python3 -m ruff check media_engine --output-format=concise \| wc -l` → 1036 | Çoğu kozmetik (UP006 600, UP045 240, UP035 140) ama içinde 2 kullanılmayan değişken (`render.py:500 fmt`, `render.py:568 cropped`), 2 kullanılmayan import, 1 sırasız import bloğu var. Depo tek bir `ruff check` kapısı koyduğu anda kırmızı. |
| **B6** | **VMAF kapısı ölçülemedi.** Faz 7'nin çıkış kriteri "VMAF hedefleri tutuyor". Konteynerdeki ffmpeg 5.1.9 `libvmaf` içermiyor; testin adı bunu yazıyor: `test_kalite_olculebiliyor_ama_VMAF_YOK`. | `tests/test_video_transcode.py` skip mesajı | **KANIT YOK.** Faz 7 kapanamaz. |
| **B7** | **İzlenebilirlik %36,6.** T-140'ın kendi kabul kriteri "her FR/NFR en az bir teste bağlı". 202 gereksinimin **128'i kapsanmıyor**. | `docs/test/traceability.md` §0 | Faz 14 çıkış kriteri **SAĞLANMIYOR**. |

---

## 1. Derleme — `py_compile`

```
$ for f in $(find media_engine -name "*.py"); do python3 -m py_compile "$f"; done
py_compile bitti, hata bayragi=0
$ find media_engine -name "*.py" | wc -l
71
```

**71/71 dosya derlendi. Derlenmeyen dosya YOK.**

Paket dağılımı (dosya · Python satırı):

| Paket | Dosya | `.py` satırı |
|---|---:|---:|
| `api/` | 7 | 4.522 |
| `image/` | 8 | 4.534 |
| `core/` | 10 | 3.648 |
| `storage/` | 6 | 3.049 |
| `delivery/` | 6 | 2.684 |
| `video/` | 6 | 2.656 |
| `contracts/` | 9 | 2.057 |
| `security/` | 3 | 1.717 |
| `fakes/` | 6 | 1.358 |
| `policy/` | 16 | 1.303 |
| `observability/` | 3 | 1.164 |
| `migration/` | 2 | 879 |
| `simulator/` | 4 | 878 |
| `quality/` | 2 | 613 |
| `doctype_specs/` | 17 | 0 (JSON + SQL) |
| **Toplam `.py`** | **71** | **31.152** |
| Veri dosyaları (JSON/SQL/TS) | — | 10.458 satır |
| `tests/*.py` | 29 | 15.532 |
| Bu çalışmada üretilen `docs/*.md` | — | 30.172 |

---

## 2. Testler — aynen raporlanmıştır

```
$ cd /Users/ahmet/Desktop/istoc/tradehub_core
$ python3 -m unittest discover -s tests -q
----------------------------------------------------------------------
Ran 1376 tests in 106.116s

OK (skipped=70, expected failures=1)
```

**Uyarı — bu sonuç kararlı değil.** Bkz. B1. Suite bu denetimde **18 kez**
baştan sona koşuldu:

| Koşum | Sonuç |
|---|---|
| `-q` × 2 | `OK (skipped=70, expected failures=1)` |
| `-v` #1 | **`FAILED (failures=1, skipped=70, expected failures=1)`** |
| `-v` #2…#16 | `OK (skipped=70, expected failures=1)` × 15 |
| **Toplam** | **17 OK · 1 FAILED (≈ %5,6 kararsızlık)** |

**Kırılan test kimliği bulunamadı** — o koşumda stdout atılmıştı ve 15 tekrar
denemesinde hata bir daha üretilmedi.

### 2.1 Dosya başına test sayısı (ölçüldü)

| Dosya | Test | Dosya | Test |
|---|---:|---|---:|
| `test_storage_adapters.py` | 137 | `test_dedup.py` | 57 |
| `test_api_contracts.py` | 126 | `test_svg_sanitize.py` | 52 |
| `test_video_transcode.py` | 89 | `test_migration_backfill.py` | 50 |
| `test_render.py` | 73 | `test_retention.py` | 47 |
| `test_observability.py` | 72 | `test_state_machine.py` | 47 |
| `test_contracts.py` | 69 | `test_usage.py` | 45 |
| `test_video_decision.py` | 58 | `test_e2e_scenarios.py` | 39 |
| `test_policy_engine.py` | 38 | `test_crop_geometry.py` | 37 |
| `test_isolation.py` | 36 | `test_simulator_srcset.py` | 34 |
| `test_image_classify.py` | 32 | `test_render_regression.py` | 32 |
| `test_image_lqip.py` | 27 | `test_crop.py` | 26 |
| `test_delivery_rum.py` | 26 | `test_image_normalize.py` | 25 |
| `test_delivery_picture.py` | 24 | `test_delivery_sizes.py` | 22 |
| `test_quality_ssim.py` | 21 | `test_policy_dpi.py` | 19 |
| `test_image_probe.py` | 16 | | |
| | | **Toplam** | **1.376** |

Toplam doğrulandı: 29 dosyanın tek tek koşulan test sayıları **1.376** ediyor.

### 2.2 70 atlanan testin gerekçe dağılımı (ölçüldü)

| Adet | Gerekçe | Sınıf |
|---:|---|---|
| 36 | `ffmpeg`/`ffprobe` yok — konteynerde koşulmalı | ortam |
| 9 | numpy kurulu ortamda ölçülen bayt/SSIM taban çizgisi burada anlamsız | ortam |
| 7 | `ffprobe` yok | ortam |
| 3 | **RLIMIT_AS macOS/Darwin'de UYGULANMIYOR** (2026-08-18 ölçümü) | ortam — güvenlik kanıtı yerelde alınamıyor |
| 2 | `ffprobe` yok (konteynerde var) | ortam |
| 1 | **VMAF ölçülemedi** — ffmpeg 5.1.9 libvmaf içermiyor | **kanıt boşluğu (B6)** |
| 1 | **Gerçek AWS/MinIO'ya karşı ölçüm YOK** — boto3 yerelde kurulu değil | **kanıt boşluğu** |
| 1 | LCP yalnız gerçek tarayıcıda ölçülür — tarayıcı yok | kapsam dışı |
| 1 | Mesajın satıcının ekranında göründüğü yalnız UAT ile ölçülür | kapsam dışı |
| 1 | Crop Studio / simülatör **EKRANI yazılmadı** | **eksik özellik** |
| 1 | `'Önizlemeden geçmeden onaylayamaz'` kuralının **kodda karşılığı YOK** | **eksik özellik** |
| 1 | `'İstendiğinde yeniden üretilir'` için **on-demand teslim ucu YOK** | **eksik özellik** |
| 1 | `'Yalnız etkilenen rendition yenilenir'` için **iş planlayıcı YOK** | **eksik özellik** |
| 1 | `frappe` yok: üretim TTL sabitleri okunamıyor | ortam |
| 1 | `frappe/naming.py` yok | ortam |
| 1 | PyYAML kurulu değil | ortam |
| 1 | numpy yok — karşılaştırılacak ikinci arka uç yok | ortam |
| 1 | numpy yok — yalnız saf Python yolu | ortam |
| **70** | **Toplam** | |

Sınıf özeti: **64 ortam/kapsam** (başka makinede kapanır) · **2 kanıt boşluğu**
(VMAF, gerçek S3) · **4 eksik özellik**. Toplam 70.

**Kod eksikliğinden atlanan 4 test — bunlar ortam eksikliği DEĞİL, YAZILMAMIŞ ÖZELLİK:**

1. `Senaryo05OnizlemesizOnay::test_onizleme_onay_kapisi_YOK` — *"önizlemeden
   geçmeden onaylayamaz"* kuralının kodda karşılığı yok; ne `api/crop.py`'de
   ne durum makinesinde `preview_approved` kapısı var.
2. `Senaryo12TurevSilinirYenidenUretilir::test_tembel_yeniden_uretim_ucu_YOK` —
   on-demand teslim ucu yok; `api/delivery.py` üretilmemiş profili `srcset`'e
   hiç koymuyor.
3. `Senaryo06KirpmaDegisinceUrlDegisir::test_yalniz_etkilenen_rendition_...` —
   iş planlayıcı (hangi profil hangi niyetten etkilenir) `tradehub_core/media/pipeline/` içinde
   **yok**.
4. Crop Studio / önizleme simülatörü **ekranı yazılmadı** (Faz 10/11 belge
   seviyesinde kaldı) → ekran görüntüsü/kayıt üretilemiyor.

### 2.3 Bağımsız doğruladığım iddialar

| İddia | Kaynak | Denetim sonucu |
|---|---|---|
| TS ikizi parite: 584 vektör, sapma 0 px | `13-faz14-kabul.md:47` | ✅ **DOĞRU**, koşuldu: `[TS parite] 584 vektör + 8 hata vakası · uyuşmazlık = 0 · en büyük sapma = 0 px` (node v24.18.1) |
| `openapi.yaml` 2.461 satır | `13-faz14-kabul.md` | ✅ `wc -l` → 2461 |
| 51 golden fixture | `manifest.json` | ✅ 41 medya + 10 kötücül = 51; manifest özeti `gecti: 51, kaldi: 0` |
| `test_storage_adapters.py` 74 test | `13-faz14-kabul.md:44` | ❌ **YANLIŞ** — ölçülen **137** |
| "16 DocType spesifikasyonu" | `13-faz14-kabul.md:41,136` | ❌ **YANLIŞ** — `doctype_specs/*.json` (index hariç) **15**; `_index.json` da 15 sayıyor |
| Faz 13: "`docs/security/` boş" | `13-faz14-kabul.md:49` | ❌ **YANLIŞ** — `docs/security/` içinde `faz13-gdpr.md` ve `faz13-tehdit-modeli.md` var. Doğru ifade: *pentest raporu yok*, klasör boş değil |

---

## 3. Şema uyumu — hâlâ 9/9

```
$ python3 -c "import json,glob,jsonschema; s=json.load(open('tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json')); \
  v=jsonschema.Draft202012Validator(s); print(sum(1 for f in glob.glob('tradehub_core/media/pipeline/policy/slots/*.json') \
  if not list(v.iter_errors(json.load(open(f))))),'/9')"
9 /9
```

**9/9 — bozulmamış.** Doğrulanan dosyalar: `brand-logo`, `category-banner`,
`company-cover-image`, `company-cover-video`, `document-attachment`,
`product-image`, `product-video`, `seller-logo`, `user-avatar`.

---

## 4. Kural ihlali denetimi — `tradehub_core/tradehub_core/` değişti mi?

**HAYIR. İHLAL YOK.**

`git status` üretim ağacında değişiklik gösteriyor, ama bunlar **bu çalışmaya ait değil**:

```
 M requirements.txt
 M tradehub_core/api/analytics.py
 M tradehub_core/api/search.py
?? tradehub_core/api/{accounting,advanced_search,carrier_adapter,
   elasticsearch_integration,invoice,logistics,shipment_core}.py
?? tradehub_core/tradehub_core/doctype/platform_invoice{,_item}/
```

Kanıt — zaman damgaları ayrışıyor:

| Küme | mtime |
|---|---|
| `tradehub_core/api/*` değişiklikleri, `requirements.txt` | **17 Ağustos** 19:56 – 21:37 |
| `tradehub_core/**` altında 18 Ağustos'ta dokunulan 27 dosya | **11:28:46 – 11:32:08** — son commit/merge `af60eba` (11:32:08) ile birebir; git checkout mtime'ı, içerik `git status`'ta temiz |
| `tradehub_core/media/pipeline/**` ilk yazılan dosya | **11:46:48** |

Yani üretim ağacına yazılan son bayt **11:32**, medya motoru çalışmasının ilk
baytı **11:46**. Bu çalışma `tradehub_core/tradehub_core/` altına **hiçbir şey
yazmadı**. `git status` içinde `tradehub_core/tradehub_core/media/` altından tek
bir değişiklik yok.

> Not: `docs/` ve `tests/` ve `scripts/` ve `tradehub_core/media/pipeline/` altındaki her şey
> yeni (`??`). `requirements.txt`'teki tek satırlık değişiklik 17 Ağustos'a ait,
> bu çalışmanın değil.

---

## 5. Faz faz durum tablosu

Kapı durumu = kaynak dokümanın faz çıkış kriteri.

| Faz | Üretilen | Eksik | Kapı |
|---|---|---|---|
| **0** Kod tabanı araştırması | 11 rapor (`00-…`→`10-…`), `scripts/media_stats.py`, 51 fixture + manifest, benchmark (360 koşum) | Kapanış raporunun kendisi "HAYIR" diyor: D-2 (44 dosya KVKK), K-2, K-3, G-2 açık | ❌ **AÇIK** |
| **1** AR-GE | `docs/reports/11-faz1-arge.md` (10 soru, ölçümlü), `scripts/measure_faz1.py`, `tradehub_core/media/pipeline/quality/ssim.py` + 21 test | **ADR seti YOK** — `find docs -iname "*adr*"` → **0**. İmza yok | ❌ **AÇIK** |
| **2** Medya standartları | 13 standart belgesi, `policy/schema/` + 9 slot (9/9), `content_rules.json`, `quota.schema.json`, `retention.schema.json`, `docs/plans/migration.md`, SRS v1.0 | **SRS TASLAK** (`SRS-v1.0.md:3` "Onaylanmadı", T1/T2/T4-T7 açık); `plan_backfill.py` **çalıştırılmadı** | ❌ **AÇIK** |
| **3** Sistem mimarisi | `docs/sad/SAD-v1.0.md`, `interfaces.md`, `review-v1.0.md`, `contracts/` (5 protokol) + `signatures.golden.json` + 69 test, `fakes/`, `policy/engine.py`, `core/state.py`, `core/jobs.py` | **SAD TASLAK** (`SAD-v1.0.md:3`), onay bloğu boş | ⚠ **KISMEN** (sözleşme donduruldu, SAD onaysız) |
| **4** Veri modeli | 15 DocType spesifikasyonu + `_ddl.sql` + `_index.json`, `core/crop.py`, `core/dedup.py`, `core/usage.py` + 128 test, `docs/data/data-model-review.md` | Şemalar Frappe'ye **kurulmadı**; `data-model-review.md` §8 açık maddeler | ⚠ **KISMEN** |
| **5** Depolama / S3 / CDN | `storage/{local,s3,mirror,tiered,retention}.py` + 184 test, `delivery/signed.py`, `docs/plans/backup-dr.md` | **Gerçek S3'e karşı ÖLÇÜLMEDİ** (boto3 yok); ayar DocType'ı kurulmadı; DR tatbikatı yok | ⚠ **KISMEN** |
| **6** Image Engine | `image/{probe,normalize,classify,render,reprocess,lqip,report}.py` (4.534 satır) + 205 test, `docs/data/t063-render-olcum.json` | — (idempotensi testi var: `DefterTesti::test_ikinci_kosum_encode_etmez`) | ✅ **KANITLI** — tek tam kapanan faz |
| **7** Video Engine | `video/{probe,decision,transcode,poster,hls}.py` + 147 test, `policy/video_decision.json` | **VMAF ölçülemedi** (B6); HLS gerçek paketleme/oynatma ölçülmedi; Faz 7 kapanış belgesi (T-075) **yok** | ❌ **AÇIK** |
| **8** API katmanı | `api/{spec,upload,crop,delivery,admin,envelope}.py` (4.522 satır), `docs/api/openapi.yaml` (2.461 satır) + 126 test | Hiçbir uç `@frappe.whitelist()` taşımıyor — **çalışan uç yok** (B2) | ✅ sözleşme KANITLI / ⚠ çalışır değil |
| **9** Media Library UI | `docs/ui/faz9-media-library.md` (yalnız plan) | **Arayüz yazılmadı** (admin-panel salt oku) | ❌ **AÇIK** |
| **10** Crop Studio | `core/crop_geometry.py` + `.ts` ikizi, `tests/fixtures/crop_vectors.json`, parite 584 vektör 0 px (ölçüldü) | **Arayüz yazılmadı** (T-101…T-105) | ⚠ **KISMEN** |
| **11** Önizleme simülatörü | `simulator/{devices,placements}.json`, `srcset.py`, 13 cihaz × 5 yerleşim = 65 kombinasyon + 34 test | **Ekran yok** (T-113…T-115) | ⚠ **KISMEN** |
| **12** Headless teslim | `delivery/{picture,sizes,rum}.py` + 72 test, `docs/plans/faz12-lcp.md`, `docs/reports/12-performans-kabul.md` | **"Sonra" ölçümü yok**; 15 ölçütün 5'i kapatılamadı; `sizes` üretim yoluna bağlı değil (B4); storefront salt oku | ❌ **AÇIK** |
| **13** Güvenlik / observability | `security/{isolation,svg}.py`, `observability/{metrics,logging}.py` + 160 test, `docs/security/faz13-{tehdit-modeli,gdpr}.md` | **Pentest raporu YOK** (T-135); alarm/dashboard yayında değil; RLIMIT_AS yerelde doğrulanamadı | ❌ **AÇIK** |
| **14** Test / kabul | `docs/test/traceability.md` + `req-test-map.json` + `scripts/gen_traceability.py`, `tests/test_e2e_scenarios.py` (39), `migration/backfill.py` + 50 test, `docs/plans/faz14-{uat,golive}.md`, `docs/reports/13-faz14-kabul.md` | İzlenebilirlik **%36,6** (hedef %100); UAT yapılmadı; imza bloğu boş | ❌ **AÇIK** |

### 5.1 Kapı özeti

| Durum | Faz | Hangileri |
|---|---:|---|
| ✅ Kapandı | **1** | 6 |
| ⚠ Kısmen | **5** | 3, 4, 5, 10, 11 (+ 8 sözleşme tarafı) |
| ❌ Açık | **9** | 0, 1, 2, 7, 9, 12, 13, 14 (+ 8 çalışırlık tarafı) |

> `13-faz14-kabul.md` "2 faz KANITLI (6 ve 8)" diyor. Ben Faz 8'i **ayırıyorum**:
> sözleşme ve testleri kanıtlı, ama fazın adı "API katmanı" ve ortada **çağrılabilir
> tek bir uç yok**. Sözleşme kanıtlı, katman değil.

---

## 6. 102 görevin karnesi

Görev kimlikleri kaynak dokümanın numaralandırmasından türetildi ve toplamı
**birebir 102** ediyor: Faz 0-1-2 × 10, Faz 3 × 6, Faz 4 × 5, Faz 5 × 6,
Faz 6 × 8, Faz 7-8-9-10-11 × 6, Faz 12 × 5, Faz 13-14 × 6.

Ölçüt: **TAM** = kod ve/veya ölçüm çıktısı var, testi/kanıtı koşuldu. **KISMİ** =
çıktı var ama kabul kriterinin bir parçası eksik (ne eksik olduğu yazılı).
**YOK** = yalnız plan/atıf var ya da hiçbir şey yok.

### Faz 0 — 10/10 TAM

| Görev | Durum | Kanıt |
|---|---|---|
| T-000 Ortam envanteri | TAM | `docs/reports/00-ortam-envanteri.md` |
| T-001 Upload slot envanteri | TAM | `docs/reports/00-upload-slot-envanteri.md` |
| T-002 Dosya akışı | TAM | `docs/reports/01-dosya-akisi.md` |
| T-003 Medya istatistiği | TAM | `02-medya-istatistigi.md` + `08-canli-olcum.md` + `scripts/media_stats.py` |
| T-004 Render envanteri + LCP taban | TAM | `03-render-envanteri.md`, `03-performans-taban-cizgisi.md` |
| T-005 Yetki modeli | TAM | `04-yetki-modeli.md` |
| T-006 Fixture korpusu | TAM | 51 fixture, `manifest.json` özeti `gecti: 51, kaldi: 0` |
| T-007 Kütüphane benchmark | TAM | `05-kutuphane-benchmark.md`, 360 koşum 0 hata |
| T-008 Depolama/maliyet | TAM | `06-depolama-maliyet.md` |
| T-009 Faz 0 kapanış | TAM (rapor) | `07-faz0-kapanis.md` — **kapanışın kendisi "HAYIR" diyor** |

### Faz 1 — 8 TAM / 2 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-010 Ölçüm çerçevesi + korpus bütünlüğü | TAM | — (51 fixture'ın 5'i hash sürüklemesi bulundu) |
| T-011 Rakip kalite seçimi araştırması | KISMİ | Yalnız doküman kaynaklı `[D]`; İstoç korpusunda **ölçüm yok** |
| T-012 DPI normalizasyonu | TAM | — |
| T-013 Hedef-SSIM ikili arama | TAM | `quality/ssim.py` + 21 test + `scripts/measure_ssim_quality.py` |
| T-014 Saliency kırpma | TAM | Canlı 400 görselde ölçüldü |
| T-015 İstemci ön-sıkıştırma çelişkisi | TAM | — |
| T-016 Video hattı / AV1 | KISMİ | AV1 **kalite eşitlenmedi**; karar verilemedi |
| T-017 Yükleme kapısı zararlı içerik | TAM | 10 fixture'ın 6'sı geçti — ölçüm var |
| T-018 İçerik-adresli tekilleştirme | TAM | 45,2 MB / %3,9 |
| T-019 Faz 1 kapanış | TAM | `11-faz1-arge.md` |
| **Faz kapısı** | — | **ADR seti YOK (0 dosya)** |

### Faz 2 — 8 TAM / 2 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-020 `product.image` standardı | TAM | — |
| T-021 Logo standardı | TAM | — |
| T-022 Kapak videosu standardı | TAM | — |
| T-023 Kalan slot standartları (5 belge) | TAM | — |
| T-024 DPI ve çözünürlük | TAM | + `tests/test_policy_dpi.py` 19 test |
| T-025 İçerik kuralları | TAM | `content_rules.json` + kalibrasyon betiği |
| T-026 Saklama (retention) | TAM | `retention.schema.json` + `docs/standards/retention.md` |
| T-027 Kota | TAM | `quota.schema.json` + `docs/standards/kota.md` |
| T-028 Migration planı | KISMİ | `scripts/plan_backfill.py` **YAZILDI, ÇALIŞTIRILMADI** |
| T-029 Faz 2 kapanış / SRS | KISMİ | **SRS TASLAK**, onaylanmadı |

### Faz 3 — 5 TAM / 1 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-030 SAD | KISMİ | **TASLAK**, onay bloğu boş |
| T-031 Arayüz sözleşmeleri | TAM | `contracts/` + `signatures.golden.json` + 69 test |
| T-032 Paket iskeleti | TAM | `tradehub_core/media/pipeline/__init__.py` + `IMPLEMENTED` haritası (18 anahtar, hepsi `True`) |
| T-033 PolicyEngine | TAM | `policy/engine.py` + 38 test |
| T-034 Durum makinesi + kuyruk zarfı | TAM | `core/state.py`, `core/jobs.py` + 47 test |
| T-035 Faz 3 kapanış | TAM | `docs/sad/review-v1.0.md` |

### Faz 4 — 3 TAM / 2 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-040 DocType şemaları | KISMİ | 15 spesifikasyon var; **Frappe'ye kurulmadı**, `hooks.py`'ye bağlanmadı |
| T-041 Crop intent / override | TAM | `core/crop.py` + `crop_geometry.py` + 63 test |
| T-042 Tekilleştirme | TAM | `core/dedup.py` + 57 test |
| T-043 Kullanım / referans | TAM | `core/usage.py` + 45 test |
| T-044 Faz 4 kapanış | KISMİ | `data-model-review.md` §8 açık maddeler; `_ddl.sql` koşulmadı |

### Faz 5 — 3 TAM / 3 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-050 Yerel adaptör | TAM | `storage/local.py` |
| T-051 S3 / mirror / tiered | KISMİ | **Gerçek S3'e karşı ÖLÇÜLMEDİ** — boto3 yok, dış ağ yok |
| T-052 İmzalı URL | TAM | `delivery/signed.py` + testler |
| T-053 Saklama | TAM | `storage/retention.py` + 47 test |
| T-054 Yedekleme / DR | KISMİ | Plan var (`docs/plans/backup-dr.md`), **tatbikat yok** |
| T-055 Depolama fabrikası / superadmin ayarı | KISMİ | Fabrika kodu var; **ayar DocType'ı kurulmadı** |

### Faz 6 — 8/8 TAM

| Görev | Durum | Kanıt |
|---|---|---|
| T-060 Probe | TAM | `image/probe.py` + 16 test |
| T-061 Normalize | TAM | `image/normalize.py` + 25 test |
| T-062 Sınıflandırma | TAM | `image/classify.py` + 32 test |
| T-063 Profil matrisi / render | TAM | `image/render.py` (4.5k satır dosya kümesinde en büyüğü) + 73 test + `docs/data/t063-render-olcum.json` |
| T-064 Yeniden işleme | TAM | `image/reprocess.py` |
| T-065 LQIP | TAM | `image/lqip.py` + 27 test |
| T-066 Kalite raporu | TAM | `image/report.py` |
| T-067 Altın regresyon | TAM | `tests/test_render_regression.py` 32 test |

### Faz 7 — 4 TAM / 2 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-070 Video probe | TAM | `video/probe.py` |
| T-071 Karar tablosu | TAM | `policy/video_decision.json` + 58 test |
| T-072 Transcode (H.264/AAC/faststart) | KISMİ | Kod ve fayda kapısı testli; **VMAF KANIT YOK** (B6); §7.1 çelişkisi açık |
| T-073 Poster | TAM | `video/poster.py` |
| T-074 HLS | KISMİ | Komut üretimi ve GOP hizası testli; **gerçek paketleme/oynatma ÖLÇÜLMEDİ** |
| T-075 Faz 7 kapanış | KISMİ | Kapanış **belgesi yok**; yalnız `video/__init__.py` başlığında atıf |

### Faz 8 — 6/6 TAM (sözleşme) · 0/6 çalışır

| Görev | Durum | Not |
|---|---|---|
| T-080 Zarf / hata modeli | TAM | `api/envelope.py`, `api/spec.py` |
| T-081 Yükleme uçları | TAM | `api/upload.py` |
| T-082 Kırpma uçları | TAM | `api/crop.py` |
| T-083 Teslim uçları | TAM | `api/delivery.py` + `delivery/manifest.py` |
| T-084 Yönetim uçları | TAM | `api/admin.py` |
| T-085 Sürüm dondurma / SDK | TAM | `docs/api/README.md`, `openapi.yaml` |
| **Hepsi için** | — | **Hiçbiri `@frappe.whitelist()` taşımıyor → HTTP'den erişilemez (B2)** |

### Faz 9 — 0/6

T-090…T-095 **YOK.** Yalnız `docs/ui/faz9-media-library.md` (kapsam haritası +
plan). Arayüz yazılmadı — admin-panel ayrı depo, salt oku.

### Faz 10 — 1 TAM / 5 YOK

| Görev | Durum |
|---|---|
| T-100 Geometri çekirdeği + TS ikizi | **TAM** — 584 vektörde sapma 0 px, node ile bu denetimde yeniden koşuldu |
| T-101…T-105 | **YOK** — `docs/ui/faz10-crop-studio.md` planı var, kod yok |

### Faz 11 — 3 TAM / 3 YOK

| Görev | Durum |
|---|---|
| T-110 Cihaz kataloğu | TAM — `simulator/devices.json` (13 cihaz) |
| T-111 Yerleşim kataloğu | TAM — `simulator/placements.json` (5 sayfa) |
| T-112 `srcset` simülasyonu | TAM — `simulator/srcset.py` + 34 test; 65 kombinasyon hesaplanıyor (kaynak_yetersiz=0 @2160px, zoom_yetersiz=6, aşırı servis=1) |
| T-113…T-115 | **YOK** — ekran yok |

### Faz 12 — 3 TAM / 2 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-120 `<picture>` üretimi | TAM | `delivery/picture.py` + 24 test |
| T-121 `sizes` türetimi | TAM (ölçüm) | **Üretim yoluna BAĞLI DEĞİL** (B4) |
| T-122 LCP planı | KISMİ | Plan; storefront **uygulanmadı** (salt oku) |
| T-123 RUM şeması | TAM | `delivery/rum.py` + 26 test; **saha verisi yok** |
| T-124 Faz 12 kabul | KISMİ | Raporun kendisi 15 ölçütün 5'ini "KAPATILAMADI" diyor; "sonra" ölçümü yok |

### Faz 13 — 5 TAM / 1 YOK

| Görev | Durum | Eksik |
|---|---|---|
| T-130 Süreç izolasyonu | TAM | `security/isolation.py` + 36 test; **RLIMIT_AS macOS'ta doğrulanamadı** (2 skip) |
| T-131 SVG temizleme | TAM | `security/svg.py` + 52 test |
| T-132 Tehdit modeli | TAM | `docs/security/faz13-tehdit-modeli.md` |
| T-133 Metrik + log | TAM | `observability/{metrics,logging}.py` + 72 test; **alarm yayında değil** |
| T-134 KVKK / EXIF | TAM | `docs/security/faz13-gdpr.md` |
| T-135 Pentest / güvenlik kapanışı | **YOK** | Rapor yok; yalnız go-live planında bağımlılık olarak anılıyor |

### Faz 14 — 4 TAM / 2 KISMİ

| Görev | Durum | Eksik |
|---|---|---|
| T-140 İzlenebilirlik matrisi | TAM (araç) | Üretici + matris var; **kriteri sağlamıyor: %36,6** (B7) |
| T-141 E2E senaryoları | TAM | `tests/test_e2e_scenarios.py` 39 test; **3'ü yazılmamış özellik yüzünden skip** |
| T-142 UAT / satıcı pilotu | KISMİ | Plan var, **oturum yapılmadı** |
| T-143 Backfill | TAM (kod) | `migration/backfill.py` + 50 test; **gerçek veriye koşulmadı** |
| T-144 Go-live runbook | KISMİ | Plan var, **tatbikat yok** |
| T-145 Kabul dosyası | TAM | `docs/reports/13-faz14-kabul.md`; **imza bloğu boş** |

### 6.1 Karne toplamı

**YOK olan 15 görev:** T-090…T-095 (Faz 9, Media Library UI · 6),
T-101…T-105 (Faz 10, Crop Studio ekranı · 5 — T-100 hariç),
T-113…T-115 (Faz 11, simülatör ekranı · 3), T-135 (pentest · 1).
Onbeşinin ortak özelliği: **hepsi ekran ya da dış doğrulama işi**, yani salt
okunur depolar ve üretim erişimi olmadan bu çalışma alanında üretilemez.

| Faz | TAM | KISMİ | YOK | Toplam |
|---|---:|---:|---:|---:|
| 0 | 10 | 0 | 0 | 10 |
| 1 | 8 | 2 | 0 | 10 |
| 2 | 8 | 2 | 0 | 10 |
| 3 | 5 | 1 | 0 | 6 |
| 4 | 3 | 2 | 0 | 5 |
| 5 | 3 | 3 | 0 | 6 |
| 6 | 8 | 0 | 0 | 8 |
| 7 | 4 | 2 | 0 | 6 |
| 8 | 6 | 0 | 0 | 6 |
| 9 | 0 | 0 | 6 | 6 |
| 10 | 1 | 0 | 5 | 6 |
| 11 | 3 | 0 | 3 | 6 |
| 12 | 3 | 2 | 0 | 5 |
| 13 | 5 | 0 | 1 | 6 |
| 14 | 4 | 2 | 0 | 6 |
| **Toplam** | **71** | **16** | **15** | **102** |

**Kesin karne: TAM 71 (%69,6) · KISMİ 16 (%15,7) · YOK 15 (%14,7).**

> Uyarı: "TAM" burada **görev çıktısı üretildi ve kanıtı var** demektir; **faz
> kapısı geçildi** demek DEĞİLDİR. 15 fazın 14'ünün kapısı hâlâ açık (§5.1).
> Ayrıca 71 TAM görevin hiçbirinin çıktısı **üretimde çalışmıyor** (B2).

---

## 7. Çelişki taraması

### 7.1 H.264 vs VP9 — **GERÇEK ÇELİŞKİ, AÇIK**

| Katman | Ne diyor | Yer |
|---|---|---|
| Faz 2 slot politikası | `master.format: webm`, rendition `libvpx-vp9` + `opus`, `mime: video/webm; codecs=vp9,opus` | `policy/slots/product-video.json:132-139`, `company-cover-video.json:367,473,519` |
| Faz 2 standardı | 720p/480p **WebM birincil**, MP4 "yedek" | `docs/standards/company-cover-video.md:320-323` |
| Faz 7 karar tablosu | **H.264 birincil.** *"vp9 de bu kurala TAKILIR ve H.264'e döner"* | `policy/video_decision.json:125-129, 232-253` |
| Faz 7 kodu | `video_codec = "libx264"`, `audio_codec = "aac"`, `+faststart` | `video/transcode.py:88-97` |
| Faz 3 dondurulmuş sözleşme | `PreviewClipSpec.video_codec = "libvpx-vp9"`, `container = "webm"` | `contracts/video.py:175-176` |
| Faz 8 teslim | `CONTAINER_ORDER = ("webm", "mp4")` — WebM birincil | `delivery/manifest.py:67` |

Faz 7 sapmayı **biliyor ve gerekçelendiriyor** (Safari'de VP9 `<video>` ile
oynamıyor; bugünkü hat WebM baytını `.mp4` adresine yazıp MIME'ı yalanlıyor).
**Ama Faz 2 politikaları, Faz 3 sözleşmesi ve Faz 8 teslim sırası
güncellenmedi.** Bugün uçtan uca koşulsa: `transcode.py` **H.264/MP4** üretir,
`manifest.py` **WebM'i birincil** sunar, politika **WebM bekler**. Üç katman üç
farklı gerçek.

**Karar gerekiyor** (bu denetimin yetkisi dışında): ya politika+sözleşme H.264'e
çekilir, ya karar tablosu VP9'a döner. Ara durum kalıcı olamaz.

### 7.2 Piksel tavanı 1920 vs 2400 — **ÇELİŞKİ DEĞİL, KATMAN FARKI**

- `product-image.json` → `master.max_long_edge = 2400`, `max_megapixels = 5.76`
- Aynı dosyada `profiles[]` en üst basamak → **1920**
- `docs/standards/product-image.md` §5 mevcut kodun 1920/2000/1600 dediğini
  açıkça yazıp §5.3'te **2400** kararını gerekçelendiriyor.

**Master 2400, en büyük türev 1920 — tutarlı.** Simülatör de bunu doğruluyor:
2160 px kaynakla `kaynak_yetersiz = 0`, 1120 px kaynakla 4 kombinasyon yetersiz.
Çelişki **yok**; mevcut üretim kodunun 1920'de sabit olması ise bilinen ve
belgelenmiş bir **uygulama borcu** (T-015).

### 7.3 Pillow vs pyvips — **ÇELİŞKİ YOK**

Tüm belgeler aynı kararı veriyor: **Pillow'da kalınır.** (`SAD-v1.0.md` S-02,
`review-v1.0.md` D-16, `05-kutuphane-benchmark.md`, `data-model-review.md`.)
Kod tarafında `media_engine` içinde `pyvips` importu **yok** (grep → 0).

İki **küçük tutarsızlık** var, karar değişmiyor:
- `SAD-v1.0.md:112` *">15 MP'de (korpusun %3,7'si) kazanıyor"* — benchmark
  %3,7'yi **>20 MP** için veriyor (`05-kutuphane-benchmark.md:243,495`), kazanç
  eşiğini ise **>15 MP** (`:231`). SAD iki farklı eşiği tek cümlede birleştirmiş.
- `08-canli-olcum.md:118` *"pyvips YOK — ModuleNotFoundError"* ile
  `05-kutuphane-benchmark.md:38` *"pyvips 3.1.1 kurulu"* çelişiyor gibi
  görünüyor; gerçekte **zaman farkı** (kurulum benchmark için sonradan yapıldı,
  ve `07-faz0-kapanis.md:689` kurulumun kalıcı olmadığını yazıyor).

### 7.4 Ayrı app vs modül — **ÇELİŞKİ YOK**

`SAD-v1.0.md` §2.1 (S-01), `SRS-v1.0.md` K-01 ve `tradehub_core/media/pipeline/__init__.py`
başlığı **aynı** kararı veriyor: `media_engine` **Frappe app'i değil**,
`tradehub_core` yanında duran saf kütüphane. Kod bunu uyguluyor: modül
düzeyinde `import frappe` yok (6 yerde bilinçli geç import), `modules.txt`'e
eklenmemiş, `hooks.py`'ye dokunulmamış. Karar tutarlı ve **denetlenebilir**
(`test_state_machine.py::test_cekirdekte_frappe_importu_yok`).

### 7.5 Gereksinim sayısı — **TUTARSIZLIK**

Görev brief'i "142 FR + 52 NFR" diyor; `SRS-v1.0.md` içinde benzersiz
**FR-xxx = 150**, **NFR-xxx = 52**; `traceability.md` **150 FR + 52 NFR = 202**
sayıyor. SRS rev2'de 8 gereksinim eklenmiş (`FR-143…FR-150`, `SRS-v1.0.md:24`).
**Doğru sayı 150 + 52 = 202**; brief'teki 142 rev1'e ait.

### 7.6 Rapor içi sayı hataları (§2.3'te ölçüldü)

`13-faz14-kabul.md` üç yerde yanlış sayı veriyor: `test_storage_adapters.py`
74 (gerçek 137), "16 DocType" (gerçek 15), "`docs/security/` boş" (2 dosya var).
Kabul dosyasının kendisi kanıt dosyası olduğu için bunlar düzeltilmelidir.

---

## 8. Sonuç

### 8.1 Proje şu an nerede

**Elde olan:** 31.152 satır derlenen Python, 15.532 satır test, 1.376 koşan
test, 30.172 satır ölçüme dayalı Türkçe belge, 9/9 şema uyumlu slot politikası,
51 golden fixture, 2.461 satır OpenAPI. Bu **ciddi ve büyük ölçüde ölçülmüş**
bir tasarım+kütüphane gövdesi. Faz 6 (Image Engine) gerçekten kapandı.

**Elde olmayan:** çalışan bir sistem. `media_engine` `hooks.py`'ye bağlı değil,
tek `@frappe.whitelist()` ucu yok, 15 DocType'ın hiçbiri kurulmadı, hiçbir
storefront/admin arayüzü yazılmadı (o depolar salt okunur), gerçek S3'e karşı
ölçüm yok, VMAF yok, pentest yok, saha LCP ölçümü yok.

### 8.2 Üretime mesafe

**Kod yazımı olarak yakın, devreye alma olarak çok uzak.** Kütüphane katmanı
%70 hazır; onu üretime bağlayan **tek bir satır bile yazılmadı** — bu bilinçli
bir karardı (`tradehub_core/tradehub_core/` salt oku kuralı), ama sonucu şu:
bugün bu depodan `git merge` yapılsa **üretimde hiçbir şey değişmez**.
Kullanıcının gördüğü 13,14 MB'lık ürün detay sayfası **aynen kalır**.

Somut mesafe: 15 DocType kurulumu + `hooks.py` kancaları + 6 API modülünün
whitelist sarmalayıcıları + admin/storefront arayüzleri + gerçek ortam
ölçümleri. Bunların hiçbiri başlamadı.

### 8.3 Sıradaki 5 iş — sırayla

1. **B1'i kapat: kararsız testi bul.** 18 koşumun 1'i kırıldı (≈ %5,6). Suite'i
   `-v` ile en az 40 kez koş, **her koşumun stdout+stderr'ini ayrı dosyaya**
   sakla (bu denetimde kırık koşumun çıktısı atıldığı için test adı kayboldu),
   kırılan testin adını çıkar ve düzelt. Kararsız bir suite üzerine hiçbir kabul
   kriteri kurulamaz. *(Yarım gün.)*

2. **B3'ü kapat: video kodeği kararını tek yere indir.** Ya `product-video.json`
   + `company-cover-video.json` + `contracts/video.py` + `manifest.py`
   `CONTAINER_ORDER` H.264/MP4'e çekilir, ya `video_decision.json` VP9'a döner.
   Karar `docs/` altında tek bir ADR'ye yazılır (Faz 1 kapısı zaten ADR seti
   istiyor ve **0 ADR var**). *(1 gün.)*

3. **B4'ü kapat: `sizes`'i teslim yoluna bağla.** `api/delivery.py` →
   `manifest.ManifestBuilder` kurulurken `delivery.sizes.install(builder)`
   çağrılsın; `sizes_source` `TABLE`'a dönsün. Testi: `test_api_contracts.py`
   içinde "teslim yanıtında `sizes` boş DEĞİL" iddiası. Faz 12'nin ölçülmüş
   kazancı ancak böyle gerçek olur. *(Yarım gün.)*

4. **B2'ye ilk adım: tek bir uç gerçekten çalışsın.** `tradehub_core` içine
   **yalnız** ince bir köprü modülü (`api/media_engine_bridge.py`) yaz:
   `@frappe.whitelist()` ile `media_engine.api.delivery.get_manifest`'i çağırsın.
   Tek uç, tek DocType'sız, salt okunur. Bu, B2'yi "hiç bağlı değil"den
   "bir ucu bağlı"ya taşır ve kalan entegrasyonun şablonunu verir.
   **Uyarı: bu iş bu çalışmanın salt-oku kuralını deler — önce izin alınmalı.**
   *(1 gün + izin.)*

5. **Kabul dosyasındaki üç yanlış sayıyı düzelt** (`13-faz14-kabul.md`: 74→137,
   16→15 DocType, "`docs/security/` boş" ifadesi) ve **`07-faz0-kapanis.md`'nin
   4 bloklayıcısına** (D-2 KVKK'lı 44 dosya, K-2, K-3, G-2) karar verdir.
   Faz 0 kapanmadan sonraki 14 fazın imzası anlamsız. *(Yarım gün + karar
   toplantısı.)*

---

## 9. Bu denetimin koştuğu komutlar

```
git status --porcelain
git log --format="%h %ad %s" --date=iso -10
find tradehub_core -newermt "2026-08-18 00:00:00" -type f
for f in $(find media_engine -name "*.py"); do python3 -m py_compile "$f"; done
python3 -m unittest discover -s tests -q/-v         # 18 kez (17 OK, 1 FAILED)
python3 -m unittest discover -s tests -v            # skip gerekçeleri için
python3 -m unittest tests.test_crop_geometry -v     # TS parite doğrulaması
python3 -c "...jsonschema... "                      # 9/9
python3 -m ruff check media_engine|tests|tradehub_core --output-format=concise
wc -l docs/api/openapi.yaml
node --version                                      # v24.18.1
```

**Bu belge hiçbir kod dosyasını değiştirmedi.**
