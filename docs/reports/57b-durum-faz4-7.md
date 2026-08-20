# 57b · Faz 4-5-6-7 — ölçerek durum (25 görev)

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **HEAD:** `1ec9b5e` (çalışma ağacı kirli, 39 dosya `M`)
**Ölçüm penceresi:** **22:27:33 – 22:51:43** (her satırdaki saat, o iddianın ölçüldüğü an)
**Kapsam:** Kaynağın `41-faz4-veri-modeli.html`, `42-faz5-depolama-s3-cdn.html`,
`50-faz6-image-engine.html`, `51-faz7-video-engine.html` sayfalarındaki **25 görev**.

> **Numaralandırma:** Kaynağın numaraları kullanıldı. Faz 5'te iç kayıttaki kayma
> düzeltildi: kaynağın **T-050** = StorageAdapter uygulaması (iç rapor `23-`),
> kaynağın **T-051** = Media Storage Settings ekranı (iç rapor `25-`).

> **Bu rapor koşarken 7 ajan kod yazıyordu.** Şerit A aynı pencerede `bench migrate`
> koştu (patch günlüğü: 22:23:54 – 22:32:18). `bench migrate` **koşturulmadı**.
> Bayraklara **dokunulmadı** — 22:50:01'de üçü de **0** ölçüldü.
> Konteyner ölçüm sırasında **en az 4 kez yeniden başladı** (`Up 9 seconds` → exit 137);
> üç test koşumu bu yüzden yarıda kesildi ve tekrarlandı.

---

## 0. Bu koşumda fiilen ölçülenler

| Ölçüm | Değer | Saat |
|---|---:|---|
| Koşturulan test modülü | **24** | 22:29–22:47 |
| Koşturulan test | **1.048** | |
| Başarısız | **1** (`test_retention_gc`) | 22:39:31 |
| Atlanan | 12 | |
| Canlı DB sorgusu | 11 | |
| Gerçek HTTP isteği | 6 | 22:49:23–49 |
| Canlı GC kuru koşumu (kapılar açık/kapalı) | 2 | 22:48:37 |
| İmaj denetimi (ffmpeg/boto3/node) | 3 | 22:28:42 · 22:38:52 |

> **Süre/performans iddiası YOK.** Aynı konteynerde 7 ajan paralel çalışıyordu;
> ölçülen süreler karşılaştırılabilir değildir. Yalnız **geçti/kaldı** raporlanır.
> Testlerin içindeki bütçe assert'leri (ör. `BASLIK_BUTCESI_MS = 50.0`) "test geçti"
> olarak aktarılır; bu raporda ms değeri iddia edilmez.

### 0.1 Modül modül ham koşum

| Modül | Test | Sonuç | Saat |
|---|---:|---|---|
| `test_render_regression` | 32 | **OK** (1 atlandı) | 22:29:46 |
| `test_crop_geometry` | 37 | **OK** (1 **atlandı**) | 22:31:11 |
| `test_retention_gc` | 37 | **FAILED (1)** | 22:39:31 |
| `test_usage` | 45 | OK | 22:39:34 |
| `test_dedup` | 57 | OK | 22:39:35 |
| `test_media_usage_sources` | 12 | OK | 22:39:36 |
| `test_video_transcode` | **109** | **OK** | 22:40:07 |
| `test_video_decision` | 58 | OK | 22:45:15 |
| `test_media_transcode` | 22 | OK | 22:45:21 |
| `test_media_transcode_retry` | 39 | OK | 22:45:24 |
| `test_image_probe` | 16 | OK | 22:45:58 |
| `test_image_normalize` | 25 | OK | 22:45:59 |
| `test_image_classify` | 32 | OK | 22:46:21 |
| `test_render` | 73 | OK | 22:46:29 |
| `test_image_lqip` | 27 | OK | 22:46:45 |
| `test_quality_ssim` | 21 | OK | 22:46:54 |
| `test_crop` | 26 | OK | 22:46:56 |
| `test_media_crop_intent` | 17 | OK | 22:47:08 |
| `test_storage_adapters` | 137 | OK | 22:47:28 |
| `test_media_storage_settings` | 19 | OK | 22:47:29 |
| `test_retention` | 47 | OK (1 atlandı) | 22:47:35 |
| `test_delivery_sizes` | 22 | OK | 22:47:36 |
| `test_delivery_picture` | 24 | OK | 22:47:37 |
| `test_storage_adapters_minio` | 91 | OK (gerçek MinIO) | 22:47:42 |
| `test_e2e_scenarios` | 39 | OK (8 atlandı) | 22:47:47 |
| `test_media_manifest_api` | 11 | OK | 22:47:50 |

> Koşum komutu `--skip-before-tests` ile verildi. Sebep ölçüldü: paralel ajanlar
> `Helpdesk SLA Policy` singleton'ını aynı anda yazıyor ve `before_tests`
> `TimestampMismatchError` fırlatıp **modülü hiç koşturmadan** düşüyordu
> (22:30:57 ve 22:39:05'te iki kez görüldü). Bayrak yalnız kurulum kancasını
> atlar, testleri değil.

---

## 1. Bugün değişenlerin doğrulaması

### 1.1 DocType envanteri — **22:50:01 itibarıyla 10** (6 → 8 değil, **10**)

```
Media Asset · Media Crop Intent · Media Crop Override · Media Engine Settings
Media Processing Job · Media Profile · Media Rendition · Media Storage Settings
Media Usage · Media Version
```

Şerit A ölçüm penceresinin **içinde** iş bitirdi. Patch günlüğü (22:49:14'te okundu):

| Patch | Uygulanma |
|---|---|
| `v15_9_28_media_usage` | 22:23:54 |
| `v15_9_29_media_version` | 22:23:54 |
| `v15_9_30_media_asset_active_version` | 22:24:16 |
| `v15_9_31_media_crop_override_profile` | 22:24:16 |
| `v15_9_32_media_metrics_token` | 22:24:16 |
| `v15_9_33_media_metrics_scraper` | 22:32:18 |

**`Media Audit Log` kurulmadı** — ne `tabDocType`'ta ne diskte
(`tradehub_core/tradehub_core/doctype/` altında 10 medya dizini var).

**Kaynağın istediği 15 DocType'a göre 5'i hâlâ YOK:**
`Media Source` · `Media Policy` · `Media Policy Profile` · `Media Content Rule` ·
`Media Quality Report`.

### 1.2 `Media Asset.active_version` — **DÜZELDİ** (22:29:02)

`tabDocField`'da **var** (`Link`, `sb_lifecycle` bölümünde) ve fiziksel tabloda
**var** — kolon listesinin **sonunda**, yani sonradan `alter table` ile eklenmiş.
`active_version_index` indeksi de kurulu.

⚠ Ama **hiçbir kod bu alana yazmıyor.** `active_version`'ı okuyan tek yer
`media_version.py:75` (tutarlılık kontrolü); atomik sürüm geçişinin SQL'i
`media_version.py:10-23`'te **yalnız docstring olarak** duruyor. Alan kuruldu,
mekanizma kurulmadı → T-064'ün 4. kriteri açık.

### 1.3 T-043 — `LIVE_SOURCES` 17 · `ORDER_SOURCES` 5 · GC kapısı **YENİDEN ÜRETİLDİ**

Sabitler sayıldı (22:37:40, `tradehub_core/media/usage.py:54-71` ve `:83-89`):
**LIVE_SOURCES = 17**, **ORDER_SOURCES = 5**. Rapor edilen 8→17 / 2→5 doğrulandı.

Kullanım kapısının etkisi **bu koşumda yeniden ölçüldü** (22:48:37, `dry_run=True`,
agresif politika `keep_forever=false · local_days=1 · then=delete`, legal_hold açık;
geçici betik `/tmp/olcum_gc.py` koşum sonrası **silindi**):

| | taranan | korunan | **aday** | aday bayt |
|---|---:|---:|---:|---:|
| **Kapılar AÇIK** (bugünkü kod) | 4.539 | 3.931 | **608** | **386.749.767** |
| **Kapılar KAPALI** (`live_usage_urls`/`blind_spot_urls` boş) | 4.539 | 110 | **4.429** | **1.447.444.781** |
| **FARK** | — | — | **3.821 dosya** | **1.060.695.014 B (1,06 GB)** |

**İddia birebir doğrulandı.** `taranan` 4.528 → 4.539'a çıkmış (envanter büyümüş)
ama aday sayıları **aynı**: 608 ve 4.429. Hiçbir şey silinmedi (`bytes_freed=0`,
`deleted=0`).

### 1.4 T-053 — ayrı GC işleri **KAYITLI**, ama Faz 5 paketini **KIRMIZIYA** düşürdü

`hooks.py:210-211` (22:38:12'de okundu) — ikisi de `scheduler_events["daily"]`'de:

```
"tradehub_core.media.pipeline.storage.retention.run_scheduled_gc_originals",
"tradehub_core.media.pipeline.storage.retention.run_scheduled_gc_derivatives",
```

Birleşik `run_scheduled_gc` (`:194`) bilerek duruyor → toplam 3 kayıt.

⚠ **YENİ KIRMIZI (22:39:31):** `test_retention_gc` **37 test, 1 başarısız.**
Kırılan test `test_hooks_kaydi_henuz_yok` — kaydın **olmadığını** iddia ediyor:

```
AssertionError: '...retention.run_scheduled_gc_originals' unexpectedly found in [...]
: run_scheduled_gc_originals artık hooks.py'de kayıtlı — docs/reports/40-t043-kullanim-gc.md güncellenmeli
```

Yani **kriteri kapatan değişikliğin kendisi test paketini kırmızıya düşürdü.**
Testin kendi mesajı ne yapılacağını söylüyor. Bu bir kod hatası değil, **bayat
bir bekçi**; ama bugün Faz 5 paketi kırmızıdır ve öyle raporlanır.

### 1.5 Faz 6 (T-067) — altın matris **DÜZELMİŞ, DOĞRULANDI**

`test_render_regression` **22:29:46'da 32 test, OK** (1 atlandı). Sabah KIRMIZI olan
`MatrisKilidiTesti.test_matris_sayilari` geçiyor. Altın sabit
(`tests/test_render_regression.py:135-146`, 22:51:32'de okundu):

```
brand.logo: 6 · category.banner: 6 · company.cover_image: 10 · company.cover_video: 3
document.attachment: 1 · product.image: 12 · product.video: 3 · seller.logo: 6
user.avatar: 3 · _toplam: 50
```

**İddia birebir doğru:** `brand.logo:6`, `seller.logo:6`, `_toplam:50`.

### 1.6 Faz 7 — capped-CRF · REMUX · HLS

`test_video_transcode` **22:40:07'de 109 test, OK.** İddia edilen 109 sayısı doğru.
`capped_crf` (`video/transcode.py:95`, `:209 rate_ceiling_kbps`, `:265
_rate_control_args`) ve REMUX geri çekilme (`:444 remux_fallback_applies`,
`:355 build_remux_cmd`, `:574 remux`) kodda ve testte var
(`HizDenetimi`, `GeriCekilmeKurali`, `RemuxKomutu`, `GercekRemux`).

**Bu koşumda yeniden koşulmayanlar** (rapor 39'da ölçülmüş, burada tekrarlanmadı —
"ölçülmedi" olarak işaretlenir): transcode adayı 1→2 geçişi, 582.355 → 3.259.089 B
kazanç, 405 segmentli HLS paketinin HeadlessChrome + hls.js ile oynatılması.

### 1.7 `libvmaf` ve `boto3` — **İMAJ HÂLÂ ESKİ**

| Ölçüm | Sonuç | Saat |
|---|---|---|
| `docker ps` imaj kimliği | `d4a32d3496fc` (değişmedi) | 22:38:52 |
| `ffmpeg -filters \| grep -c " libvmaf "` | **0** | 22:28:42 ve 22:38:52 |
| `ffmpeg -version` | 5.1.9-0+deb12u1 (Debian) | 22:28:42 |
| sistem `python -c "import boto3"` | **ModuleNotFoundError** | 22:38:52 |
| **bench env** `env/bin/python -c "import boto3"` | **1.34.162 VAR** | 22:38:52 |
| `node --version` | **v20.19.2** | 22:28:42 |

**Sonuç:** `docker/backend.Dockerfile:68-123` libvmaf'lı statik ffmpeg derlemesini
**tarif ediyor** ve `pyproject.toml` `boto3>=1.34`'ü **beyan ediyor** — ama
**çalışan imaj bunların hiçbirini taşımıyor.** F1 ajanı tarifi yazmış, imaj
yeniden kurulmamış. boto3 bugün yalnız frappe'nin **transitif** bağımlılığı
olarak bench sanal ortamında duruyor (91 MinIO testi bu yüzden koşabildi);
frappe bırakırsa sessizce düşer. Node 20, `--experimental-strip-types` için
22+ istiyor → `crop_geometry.ts` ikizi bu konteynerde koşamıyor
(22:31:11'de test **atlandı**; sabah **kırmızıydı**, şimdi **sessiz**).

### 1.8 ⚠ Ölçüm penceresinin İÇİNDE değişti: `.github/workflows/ci.yml` doğdu

**22:31'de ölçülen:** `.github/workflows/` 5 dosya (`alpha/beta/rc/prod-release`,
`deploy`), `grep -niE "pytest|unittest|run-tests|ruff|mypy"` → **0 eşleşme**.

**22:59:00'da yeniden ölçülen:** **6 dosya.** `ci.yml` (mtime **22:56**, 11.210 B)
F1 ajanı tarafından yazılmış ve gerçek bir kapı içeriyor:

| Job | Ne yapıyor | Bloklayıcı mı |
|---|---|---|
| `ruff` | Değişen `.py` dosyalarında `ruff check` + `format --check` | **Evet** (yalnız değişen dosyalar) |
| `mypy` | `media/pipeline/contracts` (T-031'in donmuş 5 Protocol'ü) | **Evet** |
| `tests` | Test modüllerini **keşfeder** (import edilebilenleri), `unittest` ile teker teker koşar; MinIO service + ffmpeg + tesseract kuruyor; `MIN_MODUL: "85"` tabanı var | **Evet** |
| `pre-commit` | PR'da değişen dosyalarda | Evet |

**22:59:13'te ölçülen — hangi modüller CI'da koşar:**

| Modül | `frappe` import | CI'da |
|---|---|---|
| `test_render_regression` | yok | **koşar** |
| `test_video_transcode` · `test_video_decision` · `test_render` · `test_image_probe` · `test_dedup` · `test_usage` · `test_storage_adapters_minio` | yok | **koşar** |
| `test_retention_gc` | **var** | **atlanır** |

Yani **Faz 6 altın regresyon paketi ve Faz 7 video paketi CI'da koşacak;**
§1.4'teki kırmızı (`test_retention_gc`) ise `frappe` importu yüzünden CI'da
**atlanacak** — kapıyı geçer.

**Ama üç şey ölçülmedi ve öyle yazılıyor:**
1. Dosya **`??`** — commit edilmemiş, push edilmemiş. `git log -- .github/workflows/ci.yml` → **boş**.
2. Workflow'un kendi başlığı `:36-38`: "GitHub Actions üzerinde **HENÜZ KOŞMADI**".
3. `<10 dk` bütçesi ölçülmedi (`timeout-minutes: 45`); bu rapor süre iddiası yapmaz.

Bu satır, "ölçüm anına bağlı" uyarısının canlı örneğidir: aynı kriterin cevabı
28 dakika içinde **❌ → ⚠** oldu.

---

## 2. 25 görev — ölçüm tablosu

### Faz 4 — Veri modeli

| Görev | Başlık | Kaynağın kriteri | Durum | Kanıt (saat) | Engelleyen |
|---|---|---|---|---|---|
| **T-040** | DocType şemalarının yazımı | (1) Tablodaki tüm DocType'lar alan tipleri/zorunlulukları ile (2) `content_sha256` **unique**; `(version, profile, width, format)` **unique** (3) Satıcı yalnız kendi asset'i; Settings yalnız superadmin (4) Varsayılan profil/politika fixture/migration ile (5) `bench migrate` temiz + **belgelenmiş geri alma planı** | **KISMİ** | **(1) ❌ 10/15.** 22:50:01: kurulu 10 DocType. YOK: `Media Source`, `Media Policy`, `Media Policy Profile`, `Media Content Rule`, `Media Quality Report`. **(2) ❌** 22:29:13 `information_schema.statistics`: `content_sha256` indeksi **non_unique=1**; unique olan `asset_key`. `Media Rendition`'da **`version` alanı hiç yok** (22:29:20 `tabDocField`) — unique olan `rendition_key`. **(3) ✅** `media_asset.json:210-225` `if_owner:1` + `permissions.py:2653-2661` query condition + `hooks.py:885-899/982-1000`; `media_storage_settings.json:92-95` yalnız Media Superadmin + System Manager. **(4) ✅** `patches.txt:250` → `patches/v15_9_23_media_profile_seed.py` (fixture değil, patch — kriter "fixture/migration" diyor). **(5) ⚠** migrate temiz koştu (patch günlüğü 22:23–22:32) ama **`docs/plans/rollback-doctypes.md` YOK**; `docs/data/data-model-review.md:526-527` bunu kendisi "YAZILMADI" diye kaydediyor | **AJAN** |
| **T-041** | Crop intent + öncelik zinciri | (1) `resolve_crop(asset, profile) → window` zinciri uygular (2) Koordinatlar oransal; kaynak yeniden normalize edilince görsel çıktı **aynı** (3) Pencere kaynak sınırları içinde + oran **birebir** (4) `approved_by_user=0` iken smart crop **öneri olarak** kullanılabilir, UI'da öneri diye işaretli | **KISMİ** | **(1) ✅** `media/pipeline/core/crop.py:503` `resolve_crop(asset, profile, intent=None, confidence_threshold=None) -> CropWindow`; 5 adım `:572-576 / :578-584 / :586-588 / :590-597 / :599-604`. **(2) ✅ [T]** 22:31:11 `test_crop_geometry` 37 OK: 3.652 oran örneğinde en büyük bağıl sapma **2,07e-16**; 584 altın vektörde sapma **0,0 px**; 800 kutuda 1 px yuvarlama farkı **0**. **(3) ✅** `verify_window` `crop.py:610`; `test_crop` 26 OK (22:46:56); `test_media_crop_intent` 17 OK (22:47:08). **(4) ⚠ ÖLÇÜLMEDİ** — UI işaretlemesi `admin-panel` reposunda, bu depoda ölçülemez. **⚠ TS ikizi ATLANDI** (22:31:11): Node v20.19.2, `--experimental-strip-types` 22+ istiyor. Panel↔backend kırpma paritesi bu ortamda **doğrulanamıyor** — koruma inert (sabah kırmızıydı, şimdi sessiz atlıyor: **daha kötü**) | **ARAÇ** |
| **T-042** | Dedup, versiyonlama, içerik hash'i | (1) Aynı SHA-256 mevcut asset'e bağlanır, dosya yeniden yazılmaz (2) Eşzamanlı aynı yükleme yarışı yok (unique index + retry testi) (3) `version_hash = f(source_hash, policy_snapshot, crop_intent, engine_version)` (4) **Rendition URL'i `version_hash` taşır** (INV-09) (5) pHash benzerliği çalışır + uyarı üretir | **KISMİ** | **[T] 22:39:35 `test_dedup` 57 OK** — kütüphane katmanında beşi de yeşil. **Üretim yolunda üçü kopuk:** **(3) ❌** `core/dedup.py:270-295` 4 girdili doğru formülü tanımlıyor, ama üretim `pipeline_bridge.py:307-331`'deki **aynı adlı, tek girdili** `version_hash(doc)` = `sha256(içerik)[:32]`'yi kullanıyor (`:137`, `:384`); policy/crop/engine girdisi **yok**. **(4) ❌** `dedup.rendition_path` (`:366-383`, `/files/media/{asset}/{version_hash}/...`) **hiçbir üretim kodundan çağrılmıyor**; fiilen yazılan yol `pipeline_bridge.py:663` → `/files/{shard}/{sha256[:32]}`. **Canlı doğrulama (22:49:38):** `tabFile`'da `^/files/[0-9a-f]{2}/[0-9a-f]{32}\.` kalıbına uyan **tek bir public dosya yok** — o adres şeması üretimde hiç kullanılmamış. **(5) ⚠** `find_similar`/`identify_upload` (`dedup.py:550/599`) yalnız testlerden çağrılıyor; eşik `PHASH_DISTANCE_THRESHOLD=5` kendi yorumunda "**ÖLÇÜLMEDİ / kalibre edilmedi**" diyor | **AJAN** |
| **T-043** | Kullanım takibi + öksüz tespiti | (1) Asset takılıp çıkarılınca Usage kaydı güncellenir (2) Usage'ı olmayan + N gün eski asset'ler öksüz raporunda (3) **Otomatik silme kapalı**; rapor + superadmin onayı şart (4) Rendition erişim damgası **örnekleme** ile, her istekte değil | **KISMİ** | **(1) ✅ [T]** 22:39:34 `test_usage` 45 OK; 22:39:36 `test_media_usage_sources` 12 OK. Kaynak sayısı 22:37:40'ta sayıldı: **LIVE_SOURCES 17**, **ORDER_SOURCES 5**. **(2) ✅** `core/usage.py:604-687` `OrphanReport` + `classify_orphans`; `:689-754` disk taraması. **(3) ✅ silme kapalı / ⚠ onay akışı yok** — 22:48:37 canlı kuru koşum: `deleted=0`, `bytes_freed=0`; üç bayrak (`media_retention_gc_enforce` + `_originals_` + `_derivatives_`) kapalı, `dry_run` varsayılanı `True`. **Ama superadmin onay mekanizması kod olarak YOK** — yalnız `usage.py:611-614` ve `:886-888` docstring notu. **(4) ⚠ farklı mekanizma** — örnekleme değil, **deterministik zaman kovası**: `core/usage.py:499-527 should_record_access`, `ACCESS_WRITE_MIN_INTERVAL = 3600` sn. `access_sampling_rate` alanı yalnız `doctype_specs/media_engine_settings.json:58-63` taslağında; **kurulu DocType'ta yok** (22:50:01). Sapma bilinçli ve gerekçeli (`:503-511`) ama kriterin lafzı değil. **KAPI ETKİSİ ÖLÇÜLDÜ (§1.3): 3.821 dosya / 1,06 GB korunuyor** | **AJAN** |
| **T-044** | Faz 4 kapanış | (1) ER diyagramı + indeks planı belgeli; her sorgu yolu için indeks (2) Kritik sorgular **1M asset ölçeğinde `EXPLAIN`** ile incelenmiş (3) Migration ve **rollback pratikte kanıtlanmış** | **KISMİ** | **(1) ✅** `docs/data/data-model-review.md:30-45` mermaid `erDiagram`; `:169-219` indeks planı (68→57 indeks); Y1–Y7 sorgu yolları `:236-245`. **(2) ❌ ölçek yetmiyor** — belgenin kendi kaydı `:226-233`: ulaşılan **524.288 asset** (%52) / **2.097.152 rendition** (%7). `:523` "1M asset + 30M rendition — **KISMEN**"; `:525` `scripts/seed_synthetic.py` **YAZILMADI**. Ölçüm geçici `media_engine_ddl_test` DB'sinde yapılıp düşürülmüş → **yeniden üretilemiyor**. **(3) ⚠ yarısı** — migration kanıtlı (22:23–22:32 patch günlüğü, temiz), **rollback provası YAPILMADI** ve planı yazılmadı | **AJAN** |

### Faz 5 — Depolama · S3 · CDN

| Görev | Başlık | Kaynağın kriteri | Durum | Kanıt (saat) | Engelleyen |
|---|---|---|---|---|---|
| **T-050** | StorageAdapter (Local · S3 · Mirror · Tiered) | (1) Dört kip **tek sözleşme test paketini** geçer (2) "S3 kapalıyken S3 kütüphanesi **import bile edilmiyor**" — **testle doğrulanmış** (3) Yazma hatasında yarım dosya kalmaz (geçici ad + atomik rename) (4) Büyük dosyalar streaming; bellek dosya boyutundan bağımsız (5) Geçici hata → retry; kalıcı hata → yerel kopya korunur + **alarm** | **KISMİ** | **(1) ✅ [T]** `test_storage_adapters.py:259 StorageContractMixin` (24 ortak test) + `:249-252 HARNESSES` (local/s3/mirror/tiered) + `:437-447` dört sınıf üretimi. 22:47:28 **137 OK**; 22:47:42 `test_storage_adapters_minio` **91 OK (gerçek MinIO)**. **(2) ⚠ kod var, TEST YOK** — `storage/s3.py:202-210` `import boto3` fonksiyon içinde, `:84-91 boto3_available()` `find_spec` ile bakıyor. **Ama modül düzeyinde import olmadığını iddia eden bir test yok** (`ast.parse`/`sys.modules` denetimi bulunamadı); kriter "testle doğrulanmış" diyor. **(3) ✅** `local.py:182-202` `mkstemp` → `fsync` → `os.replace` → `_fsync_dir`; `test_yazma_gecici_dosya_birakmaz` (`:463`), `test_sweep_temp_files_kalintiyi_temizler` (`:500`). **(4) ✅** `local.py:82 CHUNK_SIZE=1MB`, `:217` parça parça kopya. **(5) ⚠ yarısı** — `mirror.py:276-303` retryable ayrımı + `:199` kuyruğa geri koyma + `:265-274` sayaç/hata listesi; yerel birincil ayakta (`test_ikinci...:634`). **Ama `s3.py`'de botocore `retries`/`max_attempts` yapılandırması YOK ve "alarm" bir sayaç — hiçbir alarm kuralına bağlı değil** | **AJAN** |
| **T-051** | Media Storage Settings ekranı + superadmin izolasyonu | (1) Beş bölüm ekranda gruplu + açıklamalı (2) Satıcı/alıcı erişimi **UI, REST ve `frappe.client`** üzerinden **engelleniyor** (3) Sırlar `Password`, API/log'a **hiç** dönmüyor (4) **"Bağlantıyı test et" butonu** yaz/oku/sil turu yapıp sonucu gösterir (5) Ayar değişikliği denetim kaydı üretir (kullanıcı, zaman, alan, eski→yeni) (6) Geçersiz kombinasyonlar engelleniyor | **KISMİ** | **[T] 22:47:29 `test_media_storage_settings` 19 OK.** **(1) ✅** JSON'da **5** section break: `:49` Birincil Depolama · `:55` S3 · `:63` CDN · `:68` imgproxy · `:74` Saklama. **(2) ✅ üç yol da test edilmiş** — `test_satici_OKUYAMAZ:149` (izin katmanı, 5 rol), `test_satici_rest_ucundan_da_okuyamaz:163` (`frappe.client.get` → PermissionError), `test_satici_whitelist_uclarindan_reddedilir:169`, `test_guest_reddedilir:177`. **(3) ✅** 3 `Password` alanı (`s3_secret_key:61`, `imgproxy_key:71`, `imgproxy_salt:72`); maskeleme `media_storage_settings.py:135`; sızıntı testleri `:110/:131/:194/:204/:210/:217`; `test_denetim_kaydi_yazilir_ve_sir_tasimaz:238`. **(4) ⚠ BUTON YOK** — `_s3_testi()` (`:440-487`) gerçek `put`→`get`→`delete` turunu yapıyor ve `@frappe.whitelist()` (`:389`) ile açık; **ama `media_storage_settings.js` diye bir dosya repoda yok** — ekranda buton yok, kriterin lafzı "buton". **(5) ✅** `on_update():247-269` → `media_audit.log_media_event`, değişen alanlar `:271`. **(6) ✅** `validate():186` → `_kip_dogrula:193`, `_imgproxy_dogrula:224`, `_saklama_dogrula:236` | **AJAN** |
| **T-052** | CDN teslim, imzalı URL, cache | (1) Public rendition'lar **`immutable`** başlığıyla (2) Özel/onay bekleyen medya kısa TTL imzalı URL; **imzasız erişim 403** (3) İçerik değişince URL değişir; **purge kullanılabilir ama gereksiz** (4) CDN kapalıyken aynı URL'ler yerel nginx ile çalışır (5) nginx: sendfile, sıkıştırma, doğru Content-Type, **range** desteği | **KISMİ** | **(1) ⚠ kural var, hiç tetiklenmiyor** — 22:49:38: hash biçimli yola (`/files/ab/…32hex….jpg`) **404'te bile** `Cache-Control: public, max-age=31536000, immutable` dönüyor → `gateway.conf:52-54` map'i çalışıyor. **Ama §T-042'de ölçüldüğü gibi o kalıba uyan tek bir gerçek dosya yok**; gerçek dosyalar (22:49:23, `/files/0012.png`) varsayılan kovada: `public, max-age=300, must-revalidate`. **(2) ✅ CANLI** 22:49:49: `/private/files/deneme.jpg` → **403**; `media_access.download` imzasız → **403**; `get_signed_url` misafir → **403**. **(3) ❌** `cdn_purge_api_url`/`cdn_purge_token` alanlarını **okuyan hiçbir Python kodu yok**; ayrıca üretim URL'i içerik değişince değişmiyor (T-042/4). **(4) ⚠** dev gateway'de çalışıyor; **üretimde ölçülmedi**. **(5) ⚠** 22:49:23: `Accept-Ranges: bytes` ✅, `Range: bytes=0-99` → **HTTP 206** ✅, `Content-Type: image/png` ✅; gzip `gateway.conf:64-69` (raster/video bilinçli dışarıda), `sendfile` bu dosyada **yok** (`:81-86` gerekçesi: upstream'de), **brotli yok**. ⚠ `gateway.conf` `docker/` altında ve **`docker/` bir git deposu değil** → versiyonlanmıyor, prod'a ulaştığı **ölçülmedi** | **AJAN** |
| **T-053** | Retention, arşivleme, GC | (1) Orijinal ve türev için **ayrı zamanlanmış işler**, ayarları dinamik okur (2) **`legal_hold=1` olan hiçbir asset hiçbir politikayla silinmiyor/taşınmıyor** (3) Silme: soft-delete → grace → audit; kalıcı silme ayrı + onaylı (4) Silinen türev talep anında **şeffafça yeniden üretilir** (5) Dry-run modu veriyi değiştirmeden ne silineceğini raporlar (6) Her koşum dosya sayısı/GB/katman geçişi raporu üretir | **KISMİ** | **(1) ✅ KAPANDI** 22:38:12: `hooks.py:210-211` ikisi de `daily`'de kayıtlı; ayrı kilit (`LOCK_ORIGINALS`/`LOCK_DERIVATIVES`) ve ayrı bayrak (`_originals_enforce`/`_derivatives_enforce`), `retention.py:1741` ve `:1761`. **(2) ⚠ kod var, VARSAYILAN KAPALI** — `retention.py:590/632/664` kapılar; `:85` varsayılan `{"enabled": False}`; `:22` docstring'i "Bugün YOK" diyor. `:555-558` "açık ama kapısız" kurulumu reddediyor. **(3) ⚠** trash 30g + archive 30g (`:86`, `:470/:505`); rapor `Error Log`'a yazılıyor — **ayrı bir audit zinciri değil**. **(4) ❌** `regenerate_on_demand` bayrağı okunuyor (`retention.py:396`) ama **silinen türevi yeniden üreten yol yok**. **(5) ✅** `dry_run=True` varsayılan (`:624`, `:647`) ve rapora gömülü (`:217`); §1.3'te canlı koşuldu. **(6) ⚠** `RetentionReport:210-240` `scanned/kept/deleted/blocked/bytes_freed/bytes_candidate` üretiyor — **bayt var, GB dönüşümü yok**. **⚠⚠ 22:39:31: `test_retention_gc` 37 test / 1 KIRMIZI** — `test_hooks_kaydi_henuz_yok` bayatladı (§1.4) | **AJAN** |
| **T-054** | Yedekleme ve felaket kurtarma | (1) Orijinaller ayrı hedefe yedeklenir; **RPO ve RTO sayısal** (2) **Geri yükleme prova edilmiş ve süresi ölçülmüş** (3) Türevlerin yedeklenmemesi **yazılı karar**, maliyetle gerekçeli (4) Periyodik yedek bütünlüğü hash + örnekleme ile doğrulanır | **KISMİ** | **(1) ⚠ hedef var, gerçek yok** — `docs/plans/backup-dr.md:74-81` sayısal hedef (S2: **RPO 24 saat**, **RTO ≤30 dk**); ama aynı belge `:23-24` bugünkü fiilî durumu **RPO "Sınırsız" / RTO "Ölçülemez"** diye yazıyor. **(2) ❌ CANLI ÖLÇÜM 22:51:34: `backup.list_sets()` → 0 set.** Geri yüklenecek yedek yok; prova yapılmadı; `backup-dr.md:372` "DB restore süresi ÖLÇÜLMEDİ". **(3) ✅** `backup-dr.md:221-246` — türev yedeğe girmez, orijinalden yeniden üretilir; gerekçe + istisna (elle kırpma) yazılı. **(4) ⚠ kod var, zamanlanmamış** — `media/backup.py:321 verify(set_id, deep=False)`, hash karşılaştırması `:341`; testler `test_media_seller_backup.py:177/:184`. **Ama `verify` hiçbir `scheduler_events` girdisinde yok** → periyodik doğrulama koşmuyor | **İNSAN** |
| **T-055** | Faz 5 kapanış: depolama kabul testleri | (1) Dört depolama kipinde **uçtan uca yükleme→teslim** senaryoları geçer (2) S3 ve CDN kapalıyken sistem tam işlevsel (3) **S3 açık + kimlik geçersiz** → yükleme yerelde başarılı, kopya başarısız + alarm, kullanıcıya hata yok (4) Retention kuru koşum raporları **incelenmiş ve onaylanmış** | **YOK** | Kaynağın çıktı kalemi **`tests/acceptance/test_storage_acceptance.py` — repoda YOK** (`tradehub_core/tests/acceptance/` dizini yok). **(1) ❌** dört kipte uçtan uca senaryo testi yok; en yakını adaptör sözleşmesi (137 OK) ve gerçek MinIO (91 OK) — teslim katmanını kapsamıyor. **(2) ⚠ dolaylı** `test_e2e_scenarios` 39 OK (22:47:47) ama **8 atlama** taşıyor ve depolama kipi senaryosu değil. **(3) ❌** geçersiz kimlik senaryosu testi yok; komşu test `test_e2e_scenarios.py:622 Senaryo11S3AynalamaVeKesinti` ikincil çöküşünü ölçüyor, kimlik hatasını değil — ve `:660 test_gercek_S3_ile_OLCULMEDI` adını kendisi koymuş. **(4) ⚠** kuru koşum raporu **üretilebiliyor** (§1.3'te ürettim) ama "**onaylanmış**" bir insan eylemidir, gerçekleşmedi. Ayrıca T-054'ün geri yükleme provası yok (0 set) | **AJAN** |

### Faz 6 — Görsel motoru

| Görev | Başlık | Kaynağın kriteri | Durum | Kanıt (saat) | Engelleyen |
|---|---|---|---|---|---|
| **T-060** | Probe + guard katmanı | (1) Probe format/boyut/alpha/kare/DPI/ICC/EXIF'i **decode etmeden** döner (2) `fixtures/malicious/` içindeki tüm dosyalar **decode edilmeden** reddedilir (3) Uzantı–MIME uyuşmazlığı ve polyglot reddedilir (4) 30 MB'ta probe **<50 ms** | **TAM** | **[T] 22:45:58 `test_image_probe` 16 OK.** **(1) ✅** `image/probe.py:375 probe_header()` — docstring "Piksel açılmaz, istisna atılmaz"; `HeaderProbe:151` alanları `frame_count:168`, `has_alpha:169`, `has_icc:170`, `dpi:171`, `exif_orientation:172`. **(2) ✅** `fixtures/malicious/` **10 dosya**; `test_tum_kotucul_fixturelar_reddedilir:68` + ret kodu doğrulaması `:76`. **(3) ✅** `image/probe.py:428 _extension_matches` + kapı `:509`; `core/probe.py:282 _has_leading_marker`, `:291 _has_appended_payload`, `:317 _container_valid`; polyglot fixture'ları `ext_content_mismatch` bekleniyor. **(4) ✅ bütçe testi VAR ve GEÇTİ** — `test_image_probe.py:35 BASLIK_BUTCESI_MS = 50.0`, `:196 test_30mb_dosyada_baslik_butcesi`, assert `:212`. *(Kural gereği ms değeri iddia edilmiyor; yalnız testin geçtiği raporlanıyor.)* | **—** |
| **T-061** | Normalize: yön, renk uzayı, DPI, piksel tavanı | (1) INV-01/02/03/04/07 testleri geçer (2) 3000×3000@300dpi → **2400×2400@72dpi** (3) CMYK ve AdobeRGB → sRGB, **ΔE ölçülmüş** (4) EXIF yön uygulanır + alan temizlenir; **GPS yok** (5) Şeffaf kaynakta alpha korunur (6) 30 MB fixture'da **tepe bellek <500 MB** | **KISMİ** | **[T] 22:45:59 `test_image_normalize` 25 OK.** **(1) ❌ izlenebilir değil** — `grep "INV-01\|INV-03\|INV-04\|INV-07"` Python'da **0 sonuç**; INV-02 yalnız 1 docstring atfı (`test_e2e_scenarios.py:219`). Davranışlar test ediliyor ama **invariant adıyla bağlanmamış**. **(2) ⚠ iki teste bölünmüş** — `test_image_normalize.py:158` (3000,3000) bekliyor; 2400'e inen assert **başka dosyada**: `test_policy_dpi.py:242-253` `(2400,2400)`. Tek bir "3000→2400@72" testi yok. **(3) ❌ ΔE YOK** — `grep "delta_e\|deltaE\|ΔE\|dE2000"` → **0 sonuç**. Var olan tek test mod kontrolü: `test_cmyk_srgbye_donusur:99` (`mode == "RGB"`). AdobeRGB fixture'ı/testi **bulunamadı**. **(4) ✅** `test_orientation6_boyutlari_takas_eder:66`, `test_orientation_uygulanan_dosyada_exif_yon_etiketi_kalmaz:88`, `test_gps_silinir:248`. **(5) ✅** `test_alfa_dusurulmez:127`, `:135`. **(6) ❌ TEST YOK** — `tracemalloc`/`ru_maxrss`/`getrusage` testlerde **0 sonuç**; yalnız `scripts/bench_engine.py:18-21`'de ölçüm aracı olarak var, test değil | **AJAN** |
| **T-062** | Sınıflandırma ve format zinciri | (1) photo/transparent/graphic/animation/**document** sınıfları ≥%95 doğrulukla ayrılır (2) Her sınıf Faz 2 tablosundaki zincir ve kalite hedefini kullanır (3) Grafik/logo **kayıpsız** seçer (4) **Animasyonlu GIF video hattına yönlendirilir** | **KISMİ** | **[T] 22:46:21 `test_image_classify` 32 OK.** **(1) ⚠ sınıf adı sapması + ölçüm var** — `image/classify.py:65-68`: `photo`, `graphic`, `transparent`, `animation`, **`text`**. Kaynağın `document` sınıfı **yok**. Doğruluk assert'i var: `test_image_classify.py:369 test_canli_olcum_kaydi` → `assertGreaterEqual(oran, 0.95)`, kayıt 46/48 = %95,8. ⚠ Dosyanın kendi başlığı `:21` "bu %95,8 sağlam bir tahmin **DEĞİLDİR**" diyor. **(2) ✅** zincirler `classify.py:179-193`. **(3) ✅** `test_grafik_zincirinde_jpeg_yok:301`, `test_photo_zinciri_kayipsiz_icermez:313`. **(4) ❌ TAM TERSİ** — animasyon sınıfı saptanıyor ama video hattına route eden kod **yok** (0 grep sonucu); `test_image_probe.py:150 test_animasyon_yasakliyken_reddedilir` — **reddediliyor, yönlendirilmiyor** | **AJAN** |
| **T-063** | Rendition üretimi (crop + resize + encode) | (1) Profil×genişlik×biçim matrisi üretilir; unique ihlali yok (2) Kırpma penceresi **simülatör çıktısıyla birebir** (3) Adaptif kalite SSIM hedefini **≤4 encode** denemesinde tutturur (4) Girdiden büyük rendition atılır, zincir alta düşer (5) Upscale engelli; eksik adımlar manifestten çıkar (6) **Eager profiller yayın öncesi, lazy profiller talep anında + kilit** | **KISMİ** | **[T] 22:46:29 `test_render` 73 OK.** **(1) ✅** `image/render.py:298 rendition_matrix()`, `:303 matrix_size()`; `test_render.py:113/121/128` (JSON ile birebir, kodda gömülü genişlik yok). **(2) ✅** tek kaynak `render.py:565` → `crop_mod.resolve_crop`; simülatör paritesi `test_crop.py:265` (`docs/simulator.html` `cropWindow()` JS'i ile) + `fixtures/crop_vectors.json`. **(3) ✅** `quality/ssim.py:78 DEFAULT_MAX_ENCODES = 4`; `test_render.py:417/423`, `test_quality_ssim.py:231` (22:46:54, 21 OK). **(4) ✅** `render.py:885` fayda kapısı; `test_render.py:369 FaydaKapisiTesti`, `:385 test_hicbir_turev_kaynaktan_buyuk_degil`, `:390 test_zincir_bir_alta_duser`. **(5) ✅** `render.py:346/400 upscale_blocked`, `:607 fit_scale > 1.0`; `test_render.py:180/187/218`. **(6) ❌ YOK** — `image/` ve `policy/*.json` içinde `eager`/`lazy` **0 sonuç**; tek kullanım `delivery/manifest.py:72,235` ve o HTML `loading` özniteliği, üretim stratejisi değil. **Kilitleme de yok** | **AJAN** |
| **T-064** | Idempotency ve yeniden işleme | (1) Motor çıktısı yeniden encode edilmeden yüklenir (2) Kırpma değişince **yalnız etkilenen** rendition'lar üretilir (3) Politika değişince **toplu yeniden işleme kuyruğa alınır**, canlı trafiği etkilemez (4) Yeni sürüm **atomik** yayınlanır; geçişte eski sürüm erişilebilir | **KISMİ** | **(1) ✅ [T]** `image/reprocess.py:400 decide()`, `:439 render_idempotent()`, `:489 render_ladder_idempotent()`; `test_render.py:567 test_ikinci_kosum_encode_etmez`, `:632 test_merdiven_idempotent`, `:584 test_bayat_motor_surumu_tazelenir` (22:46:29 paketinde). **(2) ⚠ yapısal, testi yok** — `reprocess.py:93 crop_signature()` + `:114 derivation_key()` crop imzasını anahtara sokuyor; `test_render.py:536/553` anahtar davranışını test ediyor ama "**yalnız etkilenen** rendition yeniden üretilir" iddiasını doğrudan ölçen test **yok**. **(3) ❌ BİLİNÇLİ OLARAK YOK** — `api/admin.py:494 plan_reprocess()` docstring `:502`: "**planı verir, iş atmaz**"; `:43` aynısını tekrar ediyor. Kuyruğa atan toplu iş **yok**. **(4) ❌ alan var, kod yok** — `active_version` kolonu 22:29:02'de kurulu ölçüldü, ama atomik geçişin 3 ifadelik SQL'i `media_version.py:10-23`'te **yalnız docstring**; alana yazan hiçbir fonksiyon yok. Eski sürümün erişilebilirliği `version_hash`'li adres şemasına dayanıyor — o da üretimde kullanılmıyor (T-042/4) | **AJAN** |
| **T-065** | LQIP ve dominant renk | (1) Sürüm başına LQIP dizesi + dominant renk, **<30 bayt** (2) LQIP **manifest'te döner**; frontend yüklenene kadar placeholder gösterir (3) Şeffaf görsellerin LQIP'i arka planı bozmaz | **KISMİ** | **[T] 22:46:45 `test_image_lqip` 27 OK.** **(1) ✅** `image/lqip.py:182 rgba_to_thumb_hash()`, `:405 encode()`, `:359 dominant_color()`; tavan `:63 MAX_HASH_BYTES = 30`; `test_tum_fixturelarda_30_baytin_altinda:74`, `test_sinir_asilirsa_sessizce_gecilmez:97`. *(ThumbHash seçilmiş — kriter "BlurHash/ThumbHash" dediği için sapma değil.)* **(2) ❌** `api/media_manifest.py` içinde `lqip`/`thumbhash` → **0 sonuç**; 22:47:50 `test_media_manifest_api` 11 OK ama LQIP alanı taşımıyor. Tüketen tek yer `delivery/picture.py:237` — **hazır string bekliyor**, üretim hattı bağlanmamış. Frontend placeholder'ı **ölçülmedi**. **(3) ✅** `test_saydam_bolge_geri_acildiginda_saydam:263`, `test_baskin_renk_saydam_bolgeyi_saymaz:272`, `test_opak_gorselde_alfa_biti_yok:258` | **AJAN** |
| **T-066** | Kalite raporu ve tasarruf telemetrisi | (1) Asset başına girdi/çıktı boyut, tasarruf oranı, SSIM **JSON olarak** loglanır (2) Kullanıcıya dönük özet Türkçe, doğru ve anlaşılır (3) **Aylık platform raporu:** toplam tasarruf GB, ortalama LCP etkisi, **en kötü 20 asset** | **KISMİ** | **(1) ✅ [T]** `image/report.py:213 build_report()`, `:390 write_report()`; boyut/oran `:70/:74`, `render.py:394 saving_ratio`; SSIM alanları `report.py:231/263-270` (`ssim_min/max/mean`, `proxy_measured`). `test_render.py:686 test_json_lanabilir_ve_semali`, `:692 test_toplamlar_gercek`, `:701 test_olculmeyen_alan_null_kalir_sifir_degil`, `:747 test_rapor_diske_yazilir`. **(2) ✅** `report.py:324 summarize_tr()`, JSON'a gömme `:278`, not çevirileri `:40-51`; `test_ozet_turkce_ve_sayilari_tasir:712`, `test_not_kodlari_turkceye_cevrilir:743`. **(3) ❌ YOK** — `media/` altında aylık/monthly/en kötü 20 → **0 sonuç**. Tek toplama `report.py:398 merge_reports()` ve onda GB/LCP/en-kötü-20 alanı yok | **AJAN** |
| **T-067** | Faz 6 kapanış: altın fixture regresyon paketi | (1) Tüm fixture'lar manifest beklentilerini karşılar (2) **12 invariant (INV-01…INV-12) ≥1 testle kapsanır; kapsam raporu var** (3) Performans bütçeleri ölçülü ve CI'da dayatılıyor (4) **Regresyon paketi her PR'da CI'da koşar (<10 dk)** | **KISMİ** | **(1) ✅ DÜZELDİ — DOĞRULANDI** 22:29:46: `test_render_regression` **32 test OK** (1 atlandı). Sabah kırmızı olan `MatrisKilidiTesti.test_matris_sayilari` geçiyor; altın sabit 22:51:32'de okundu: **`brand.logo:6`, `seller.logo:6`, `_toplam:50`** — iddia birebir doğru. **(2) ❌ 12'nin 7'si adsız** — Python'daki atıf sayımı: INV-01 **0**, INV-02 1, INV-03 **0**, INV-04 **0**, INV-05 32, INV-06 12, INV-07 **0**, INV-08 **0**, INV-09 9, INV-10 23, INV-11 **0**, INV-12 **0**. **Kapsam haritası dosyası YOK** (`find -iname "*invariant*"` → yalnız ilgisiz `test_capability_flag_invariant.py`). **(3) ⚠** bütçe assert'leri kodda var (`BASLIK_BUTCESI_MS`, `DEFAULT_MAX_ENCODES`) ama **CI'da dayatılmıyor** (bkz. 4). **(4) ⚠ DURUM 22:56'DA DEĞİŞTİ — bkz. §1.8** — 22:31'deki ölçüm 5 workflow / 0 test adımı diyordu. 22:59:00'da yeniden bakıldı: **`.github/workflows/ci.yml` var** (mtime 22:56, F1 ajanı) ve `unittest` koşan gerçek bir `tests` job'u içeriyor. `test_render_regression` `frappe` import etmiyor → CI'ın keşif döngüsü onu **bulur ve koşar** (22:59:13'te doğrulandı). **Ama dosya `??` (commit edilmemiş, push edilmemiş) ve kendi başlığı `:36-38` "GitHub Actions üzerinde **HENÜZ KOŞMADI**" diyor.** "Her PR'da koşar" bugün hâlâ **ölçülmedi**; <10 dk bütçesi de ölçülmedi (`timeout-minutes: 45`) | **AJAN** |

### Faz 7 — Video motoru

| Görev | Başlık | Kaynağın kriteri | Durum | Kanıt (saat) | Engelleyen |
|---|---|---|---|---|---|
| **T-070** | ffprobe tabanlı probe ve doğrulama | (1) Probe tüm karar değişkenlerini döner; eksik alanlarda güvenli varsayılan (2) Bozuk/kesik dosyalar tespit edilip reddedilir (3) **Timeout (30 sn) ve bellek limiti** uygulanır; worker hayatta kalır (4) Dikey çekimlerde rotation metadata doğru yorumlanır | **KISMİ** | **[T] 22:45:15 `test_video_decision` 58 OK.** **(1) ✅** `video/probe.py:282 ffprobe_json()`, `:328 probe()`; güvenli varsayılanlar `:302 _int(default=0)`, `:309 _float(default=0.0)`, `:207 parse_frame_rate()`; `test_olculmemis_kunye_alanlari_varsayilan:445`, `test_bozuk_kare_hizi_uydurmaz:412`. **(2) ✅** `probe.py:344/346`; `test_olculemeyen_kunye_reddedilir:239`, `test_video_akisi_yoksa_reddedilir:250`, istisna atmama `:452/:458`. **(3) ⚠ yarısı** — timeout **20 sn** (`contracts/video.py:42 FFPROBE_TIMEOUT_SECONDS = 20`; kriterin 30'undan sıkı, sorun değil). **Bellek limiti YOK** — `RLIMIT`/`preexec_fn`/`memory_limit` video hattında **0 sonuç**. **(4) ✅** `probe.py:316 _rotation_of()` hem `side_data_list[].rotation` hem eski `tags.rotate` (`:319-325`); fixture `video_vertical_9x16.mp4` | **AJAN** |
| **T-071** | Karar tablosu yorumlayıcısı | (1) Karar mantığı JSON'dan okunur; **kodda codec adı if/else zinciri yok** (2) Yeni codec desteği **yalnız JSON değişikliği** ister (testle kanıtlı) (3) Verimli MP4 fixture **PASSTHROUGH** alır (4) Her karar gerekçe + eşleşen kural kimliği loglar | **TAM** | **[T] 22:45:15 `test_video_decision` 58 OK.** **(1) ✅** `policy/video_decision.json` **377 satır**; okuyucu `video/decision.py:212 DecisionTable`. **Kanıt:** `grep -niE "\bh264\b\|\bhevc\b\|\bvp9\b\|\bav1\b\|libx264\|libaom" decision.py` → **0 sonuç**; codec adları yalnız JSON'da (`:128-129`). **(2) ✅** `test_video_decision.py:202 class YeniKuralKodDegismeden`, `:205 test_yeni_kural_kod_degismeden_calisir`. **(3) ✅** `:539 test_gorev_tanimindaki_iki_beklenti` — `video_efficient_720p_750k.mp4` → `ACTION_PASSTHROUGH`; ayrıca `:320 test_olculen_352_fixture_bosuna_transcode_edilmiyor`. **(4) ✅** `decision.py:131 rule_id`, `:133 reason`, `:150 as_dict()`; `:138 test_her_kuralin_kodu_ve_gerekcesi_var`, `:389 test_iz_kaydi_bakilan_kurallari_tasiyor`, `:366 test_her_kural_en_az_bir_kez_tetiklendi` | **—** |
| **T-072** | Transcode, fayda kapısı, kalite doğrulaması | (1) H.264 taban **her zaman** üretilir; AV1/VP9 yalnız fayda kapısı geçerse (2) **Hiçbir fixture çıktısı girdiden büyük yayınlanmaz (INV-05)** (3) **Şişirilmiş bitrate fixture'ında ≥%40 küçülme + VMAF ≥93** (4) Süre sapması ≤100 ms, ses senkronu korunur (5) HDR kaynak SDR'a tone-map, renk kırpılmadan (6) **faststart** (moov atom başta) | **KISMİ** | **[T] 22:40:07 `test_video_transcode` 109 OK** (iddia edilen 109 doğrulandı). **(1) ⚠ tasarım gereği hayır** — PASSTHROUGH kararında hiçbir şey üretilmiyor; AV1/VP9 **hiç üretilmiyor** (`docs/adr/0010-av1-simdi-eklenmiyor.md`; `video_decision.json:267` webm_fallback "**FAZ 7'de ÜRETİLMİYOR**"; `test_bugunku_hattin_vp9u_URETILMIYOR`). **(2) ✅** `transcode.py:98`, `:416 min_saving_ratio()`; testler `:306/:628/:657/:805`. **(3) ❌ VMAF ÖLÇÜLMÜYOR + ÇELİŞKİ** — 22:28:42 ve 22:38:52: **`ffmpeg -filters \| grep -c " libvmaf "` → 0.** Kod bunu saklamıyor: `video_decision.json:305 vmaf_note` ve `test_video_transcode.py:682 test_kalite_olculebiliyor_ama_VMAF_YOK` (`assertIsNone(k["vmaf"])`), `test_e2e_scenarios.py:502 test_VMAF_OLCULEMEDI`. Sahte VMAF üretilmiyor — **SSIM/PSNR proxy'sine düşülüyor.** **(4) ⚠ yarısı** — süre farkı `transcode.py:422 max_duration_delta_s()` (0,1 sn) + `:483 duration_delta_s()`, test `:699-710`. **Ses senkronu (A/V drift) ölçen test YOK.** **(5) ❌** `tonemap\|tone_map\|hdr\|bt2020\|zscale` → `media/` altında **0 sonuç**. **(6) ✅** `transcode.py:105/349-350` `-movflags +faststart`, remux `:366`; tespit `probe.py:237 moov_at_end_of()`; `test_video_decision.py:559 test_yedi_fixturun_yedisinde_de_moov_basta`. **capped-CRF ✅** `:95/:209/:265-278` + `HizDenetimi` testleri. **REMUX geri çekilme ✅** `:444 remux_fallback_applies` + `GeriCekilmeKurali`/`GercekRemux`; `test_remux_fayda_kapisina_TABI_DEGIL` | **KARAR** |
| **T-073** | Poster, önizleme klibi, animasyonlu önizleme | (1) Poster "**ilk anlamlı kare**"den seçilir (siyah/bulanık kare atlanır) ve görsel hattan geçer (2) Önizleme klibi 3–6 sn, sessiz, döngüye uygun, ≤1 MB (3) **Poster crop intent'e uyar**; simülatör video slotunu doğru gösterir (4) **Reduced-motion yolu yalnız-poster varyantı** teslim eder | **KISMİ** | **[T] 22:40:07 paketinde `GercekPoster` (`:848`) ve `GercekOnizlemeKlibi` (`:910`) geçti.** **(1) ⚠ yarısı** — `video/poster.py:176 poster_window()`, `:192 poster_retry_window()`, `:204 mean_luma_pct()` ile siyah/beyaz kare eleniyor; `:288 _poster_denemesi()`, `:327 make_poster()`. **Bulanıklık (blur) tespiti YOK** — yalnız ortalama luma. **(2) ✅** `poster.py:449 make_preview_clip()` (docstring `:458` "3-6 sn sessiz klip"), `:422 build_preview_cmd()` — `:431` "`-an` ZORUNLU"; 1 MB kapısı `:27` ve `:516`. **(3) ❌** `grep -n "crop" video/poster.py` → **0 sonuç**. Poster crop intent'i hiç okumuyor. Simülatör video slotu **ölçülmedi**. **(4) ❌ politika var, teslim kodu yok** — `policy/schema/slot-policy.schema.json:765/861/869` `reduced_motion` + `reduced_motion_behavior` zorunlu alan olarak tanımlı; **Python teslim yolunda uygulaması bulunamadı** | **AJAN** |
| **T-074** | HLS / uyarlanabilir teslim | (1) Eşiği aşan videolar için HLS merdiveni (360p–1080p) (2) **Master playlist ve segmentler doğru CDN cache başlıklarıyla** servis edilir (3) Mobil veri tavanı: ilk 10 saniyede inen bayt standarda karşı doğrulanır (4) Eşik altı videolar progressive MP4 (HLS zorlanmaz) | **KISMİ** | **[T] 22:40:07 paketinde `HlsMerdiveni` (`:434`) ve `GercekHls` (`:964`) geçti.** **(1) ✅** `video/hls.py:285 select_ladder()` (büyütme yasak `:20-26`), `:323 rung_dimensions()`, `:428 build_hls_cmd()`, `:644 make_hls()`; basamaklar tablodan (`:131 HlsSpec.from_table()`). **(2) ❌ YOK** — `.m3u8`/segment için `Cache-Control`/`max-age` ataması **0 sonuç**. Var olan sabitler (`dedup.py:57 CACHE_CONTROL_IMMUTABLE`, `api/envelope.py:337`) HLS çıktısına bağlı değil. Ayrıca `gateway.conf` map'i yalnız `/files/{2hex}/{32hex}.{ext}` kalıbını tanıyor — HLS segment adları o kalıba **uymuyor**. **(3) ✅** `hls.py:579 startup_bytes(playlist_path, window_s=10.0)`, tavan alanı `:184 startup_window_s`, `:554 playlist_stats()`; `GercekHls` içinde çağrılıyor. **(4) ✅** `hls.py:243 hls_required()` üç koşul (süre `:265`, bayt `:267`, çözünürlük `:269`); eşik altı tek dosya MP4 yolunda kalıyor. **⚠ Bu koşumda ölçülmedi:** 405 segmentli paketin HeadlessChrome + hls.js ile oynatılması — rapor 39 §7'de ölçülmüş, burada **tekrarlanmadı**; oradaki `bufferSeekOverHole` uyarısının kök nedeni hâlâ teşhis edilmemiş | **AJAN** |
| **T-075** | Faz 7 kapanış: video regresyonu ve kaynak bütçesi | (1) Tüm video fixture'ları manifest beklentilerine karşı **YEŞİL** (2) INV-05 hiçbir senaryoda ihlal edilmiyor (3) **Worker CPU/bellek bütçesi tanımlı; eşzamanlı transcode sayısı canlı yüklemeyi bloklamadan tavanlanmış** (4) **4K 60fps uzun video fixture'ı**: işleme süresi ve kaynak tüketimi ölçülmüş ve kabul edilebilir | **KISMİ** | **(1) ✅ [T]** 22:45:15 `test_video_decision.py:524 GercekFixtureOlcumu` — `:527 test_yedi_fixture_var`, `:532 test_fixture_kararlari_olculenle_ayni`, `:546 test_kunyeler_olculenle_ayni`, `:559 test_yedi_fixturun_yedisinde_de_moov_basta`. **(2) ✅** video: `test_video_transcode.py:306/628/657/805` (22:40:07); görsel: `test_render.py:385` (22:46:29). **(3) ⚠ yalnız `nice`** — `transcode.py:74 NICE_PREFIX = ("nice","-n","10")`, uygulama `:309/:361`, `hls.py:465`; test `test_nice_onceligi_korunuyor`. **CPU kotası/cgroup YOK, bellek bütçesi YOK** (`RLIMIT` → 0 sonuç), **eşzamanlı transcode tavanı YOK** (`eszamanl\|concurren\|max_active\|Semaphore` → 0 sonuç; tek "limit" `media/transcode.py:521 sweep_stuck_transcodes(limit=200)` ve o takılan kayıt süpürücüsü). **(4) ❌ FIXTURE YOK** — `tests/fixtures/media/video/` **7 dosya**, en büyüğü 1080p (`video_16x9_1080p.mp4`, 1.131.368 B); `gen_fixtures_video.sh` içinde `3840`/`2160`/`-r 60` → **0 sonuç**. Karar tablosu 4K'yı **reddediyor** (`test_4k_ustu_reddedilir:255`) ve bu sentetik künyeyle test edilmiş, dosyayla değil | **ARAÇ** |

---

## 3. Sayım

| Faz | Görev | TAM | KISMİ | YOK |
|---|---:|---:|---:|---:|
| Faz 4 | 5 | 0 | 5 | 0 |
| Faz 5 | 6 | 0 | 5 | 1 |
| Faz 6 | 8 | 1 | 7 | 0 |
| Faz 7 | 6 | 1 | 5 | 0 |
| **TOPLAM** | **25** | **2** | **22** | **1** |

### Engelleyen dağılımı

| Engelleyen | Sayı | Görevler |
|---|---:|---|
| **AJAN** | **19** | T-040 · T-042 · T-043 · T-044 · T-050 · T-051 · T-052 · T-053 · T-055 · T-061 · T-062 · T-063 · T-064 · T-065 · T-066 · T-067 · T-070 · T-073 · T-074 |
| **ARAÇ** | **2** | T-041 (Node 20 → TS ikizi koşamıyor) · T-075 (4K 60fps fixture üretimi) |
| **KARAR** | **1** | T-072 (VMAF ≥93 ⟂ INV-05) |
| **İNSAN** | **1** | T-054 (yedek hedefi + geri yükleme provası) |
| **—** | **2** | T-060 · T-071 |

---

## 4. Rapor 34 ile fark — ve neden

Bu sabahki `34-dogrulama-faz4-7.md` **TAM 12 · KISMİ 11 · YOK 1** demişti.
Bugünkü sayım **TAM 2 · KISMİ 22 · YOK 1**. **Bu bir gerileme değil, daha sıkı bir
okuma.** İki rapor arasında **gerçekten iyileşen** 3 madde var; kalan fark
kriterin **kütüphane katmanında** mı yoksa **teslim edilen üründe** mi arandığından
kaynaklanıyor.

### 4.1 Bugün gerçekten iyileşenler

| Madde | Sabah | Şimdi | Ölçüm |
|---|---|---|---|
| `test_render_regression` matris kilidi | **KIRMIZI** | **32 OK** | 22:29:46 |
| DocType envanteri | 6–8 | **10** (+`Media Usage`, `Media Version`, `Media Crop Override`) | 22:50:01 |
| `Media Asset.active_version` | kurulu tabloda **yoktu** | **kolon + indeks var** | 22:29:02 |
| T-053 ayrı GC işleri | kayıtsız | **`hooks.py:210-211` kayıtlı** | 22:38:12 |
| `test_crop_geometry` | **KIRMIZI** | **37 OK** | 22:31:11 |

### 4.2 Sabah TAM denip bugün KISMİ dediklerim — her biri için tek cümlelik sebep

| Görev | Sabah | Bugün | Ölçülen somut açık |
|---|---|---|---|
| T-041 | TAM | KISMİ | TS ikizi artık **kırmızı değil ama ATLANIYOR** — parite güvencesi sessizce inert oldu; kriterin UI yarısı bu depoda ölçülemez |
| T-042 | TAM | KISMİ | Üretim `version_hash`'i **tek girdili**; üretim rendition URL'i `version_hash` **taşımıyor**; o adres kalıbına uyan **0 dosya** ölçüldü |
| T-050 | TAM | KISMİ | Kriter "lazy import **testle doğrulanmış**" diyor — böyle bir test yok; "alarm" bir sayaç, alarm kuralına bağlı değil |
| T-051 | TAM | KISMİ | Kriter "**buton**" diyor; `media_storage_settings.js` yok — yalnız whitelisted metot var |
| T-061 | TAM | KISMİ | **ΔE hiç ölçülmüyor** (0 grep sonucu); tepe bellek <500 MB testi yok |
| T-062 | TAM | KISMİ | Kriter "animasyonlu GIF **video hattına yönlendirilir**" diyor; kod **reddediyor** |
| T-063 | TAM | KISMİ | **Eager/lazy profil + kilitleme hiç yok** (0 grep sonucu) |
| T-065 | TAM | KISMİ | LQIP **manifest'te dönmüyor** — `api/media_manifest.py` içinde 0 sonuç |
| T-066 | TAM | KISMİ | **Aylık platform raporu yok** (GB / LCP / en kötü 20) |
| T-070 | TAM | KISMİ | **Bellek limiti yok** — kriter "timeout **ve** bellek limiti" diyor |

**Kural:** koşturmadığıma "geçti", ölçemediğime "var" demedim. Bir kriterin
kütüphanede karşılanıp üretimde karşılanmaması **KISMİ**'dir.

---

## 5. KARAR bekleyen tek madde — T-072 / INV-05 ⟂ VMAF ≥93

Kaynağın T-072 kriteri iki şeyi **aynı anda** istiyor:

> "No fixture output exceeds input size for publication (**INV-05**)"
> "Inflated bitrate fixture shows ≥40% reduction with **VMAF ≥93**"

`39-t072-video-hatti.md` §4.2'nin **gerçek 1080p** dosyada ölçtüğü eğri (bu koşumda
yeniden ölçülmedi, aktarılıyor):

| Tavan | Çıktı baytı | Kaynağa göre | VMAF @1080p | Fayda kapısı |
|---|---:|---:|---:|---|
| 924k (uygulanan) | 6.887.018 | **−19,0%** | 78,01 | ✅ geçer |
| 1400k | 10.248.429 | **+20,5%** | 92,11 | ❌ düşer |
| tavansız CRF 23 | 14.490.432 | +70,4% | 90,21 | ❌ düşer |

Fayda kapısının tavanı **7.654.412 B**; o bütçedeki en iyi VMAF **≈86–89**.
**VMAF 93'e çıkmak dosyayı kaynaktan %20 büyütüyor.** İkisi bu içerikte
**aynı anda sağlanamaz.**

93 eşiği 7 **sentetik** `testsrc2` fixture'ının 6'sında ölçülmüştü; gerçek, zaten
bir kez sıkıştırılmış kütüphane içeriğinde CRF 23'ün ulaştığı bant **75–90**.

**Karar seçenekleri (bu rapor seçim yapmıyor):**
1. **INV-05 üstün** → VMAF eşiğini gerçek korpustan yeniden türet (ör. ≥85) ve
   kriteri kaynakta güncelle.
2. **VMAF ≥93 üstün** → INV-05'e "kaynak zaten verimsizse büyümeye izin" istisnası
   yaz — INV-05'in tanımını değiştirir.
3. **Kapsam daralt** → kriter yalnız **şişirilmiş** fixture için geçerli sayılsın,
   gerçek kütüphane içeriği için ayrı eşik tanımlansın.

> Ayrıca bu karar **ölçülemez durumda**: üretim imajında `libvmaf` **yok**
> (22:38:52). Hangi seçenek seçilirse seçilsin, önce imajın yeniden kurulması
> gerekiyor (§6).

---

## 6. Ölçüm anına bağlı / ölçülemeyenler

| Konu | Durum | Saat |
|---|---|---|
| DocType sayısı | **10** — Şerit A ölçüm penceresinin içinde bitirdi; sayı sonraki koşumda **değişebilir** | 22:50:01 |
| `Media Audit Log` | Kurulmadı (ne DB'de ne diskte) | 22:50:01 |
| `libvmaf` | **0** — `backend.Dockerfile:68-123` tarifi var, **imaj yeniden kurulmadı** | 22:38:52 |
| `boto3` | **bench env'de 1.34.162** (frappe transitif), sistem python'da **yok**; `pyproject.toml` beyanı imaja **girmedi** | 22:38:52 |
| Node | **v20.19.2** — `crop_geometry.ts` ikizi 22+ istiyor | 22:28:42 |
| Bayraklar | `media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0` — **dokunulmadı** | 22:50:01 |
| Yedek setleri | **0** | 22:51:34 |
| Konteyner kararlılığı | Ölçüm boyunca ≥4 yeniden başlatma (exit 137); 3 test koşumu kesilip tekrarlandı | 22:31–22:47 |
| `.github/workflows/ci.yml` | **22:56'da doğdu** — 22:31'de yoktu. Commit edilmemiş (`??`), GitHub'da hiç koşmadı | 22:59:00 |
| 405 segmentli HLS'in tarayıcıda oynaması | Rapor 39'da ölçülmüş, **bu koşumda tekrarlanmadı** | — |
| transcode 1→2 geçişi, 582 KB → 3,26 MB kazanç | Rapor 39'da ölçülmüş, **bu koşumda tekrarlanmadı** | — |
| `admin-panel` tarafındaki UI kriterleri (T-041/4, T-051/1, T-073/3) | Başka repo — **bu depodan ölçülemez** | — |
| 1M asset ölçeğinde `EXPLAIN` | Geçici DB düşürülmüş — **yeniden üretilemiyor** | — |

---

## 7. Bir sonraki koşumda ilk bakılacaklar

1. **`test_retention_gc` kırmızısı** (§1.4) — bayat bekçi; testin kendi mesajı ne
   yapılacağını yazıyor. Faz 5 paketi bugün kırmızıdır.
2. **İmaj yeniden kurulumu** — `libvmaf` + `boto3` + Node 22. Üçü de tek bir
   `docker compose build backend` ile çözülür ve **üç ayrı görevi** açar
   (T-072 KARAR'ı ölçülebilir hale gelir, T-050'nin MinIO paketi kırılganlıktan
   çıkar, T-041'in TS paritesi geri döner).
3. **`ci.yml` commit edilmemiş** (§1.8) — kapı **yazıldı** ama `??` durumunda ve
   GitHub'da hiç koşmadı. Commit + ilk PR koşumu, T-067/4 ile T-031'i **birlikte**
   kapatır. İlk koşumda `MIN_MODUL: "85"` tabanının gerçek keşif sayısını tutup
   tutmadığına bakılmalı.
4. **`hooks.py:194` birleşik `run_scheduled_gc`** hâlâ kayıtlı — ayrı işlerle
   birlikte 3 kayıt var; bilinçli mi, artık mı, karar verilmeli.
