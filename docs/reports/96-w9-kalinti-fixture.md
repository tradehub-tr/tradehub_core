# 96 · W9 — kalıntı + fixture (ölçüm + test hizalama)

**Tarih:** 2026-08-20 · **Kapsam:** T-032 `media_engine` kalıntısı (ölçüm) · T-006 golden korpus video tarafı (ölçüm) · `test_video_decision.py` 7→11 hizalama (yapıldı)

> **Not — çakışan çaba:** Bu W9 penceresinde ikinci bir el aynı iki kalemi işledi ve
> daha kapsamlı `docs/reports/96-w9-DEVIR-fixture-kalinti.md` raporunu yazdı (6 gerçek
> fixture + betik kalıntı düzeltmeleri). Bu rapor onu **tekrarlamaz**: bağımsız ölçümümle
> onların sonucunu **doğrular** ve onların bıraktığı **tek boşluğu** (`test_video_decision.py`)
> kapatır. Fixture ikilileri, `manifest.json`, `live-probe.json` ve `scripts/*` o elin
> sahipliğinde — onlara **dokunmadım** (eşzamanlı yazımı ezmemek için).

---

## Kalem 1 — T-032 `media_engine` kalıntısı → **ZATEN YAPILMIŞ (ölçümle doğrulandı)**

`grep -rn media_engine tradehub_core/` her oluşumu üç meşru sınıfa ayrılıyor; **silinecek ölü, referanssız dosya YOK:**

| Oluşum | Durum | Kanıt |
|---|---|---|
| SAD gövdesi 6 satır (M-01) | Rapor 88 (W7-5) kapatmış — gerçek yola çevrilmiş | `docs/sad/SAD-v1.0.md:68-69` "repoda `media_engine` diye bir dizin hiç olmadı" |
| Test alias `import … as media_engine` | **Bilinçli takma ad**, kalıntı değil (`test_state_machine`, `test_api_contracts`, `test_migration_backfill`) | Modül gerçekte `tradehub_core.media.pipeline`; alias okunabilirlik için |
| `patches/v15_9_22_media_engine_settings.py` | **Canlı** — `media_engine_settings` DocType var | `patches.txt:248` + `doctype/media_engine_settings/` dizini mevcut |
| `media/pipeline/**` docstring/logger `"media_engine"` | Kütüphanenin **öz-kimlik** dizesi (LOGGER_ADI) | ADR-0003 "kaynak dokümanın adı"; taşıma değil |
| `scripts/measure_*.py` ölü `from media_engine.X import` | Eşzamanlı el **düzeltti** → `tradehub_core.media.pipeline.X` | `grep import media_engine scripts/measure_*.py` → **boş** (bugün) |

- **App kökünde `tests/` yok:** `ls tradehub_core/tests` → yok; testler `tradehub_core/tradehub_core/tests/` (M-01'in "tests kökü" yarısı zaten doğru).
- **Dizin yokluğu sabitlenmiş:** `test_state_machine` `(ROOT/tradehub_core/media_engine).exists()` **False** assert'i ile geçiyor — kimse yeniden `media_engine/` dizini açamaz.
- **Silme yapılmadı** → `bench migrate` doğrulaması **gerekmiyor** (şema/patch/doctype dokunuşu sıfır).

---

## Kalem 2 — T-006 golden korpus video 7/8 → **ZATEN YAPILMIŞ (7→11); ölçüm doğrulandı**

Eşzamanlı el rapor 94'ün "video 7/8" boşluğunu **kapatıp aştı**: korpus **11 video** (7 sentetik + 4 gerçek DEV kaynağı). Sentetik üretim YOK; hepsi `docker cp` ile bayt-birebir, sha256 doğrulamalı. Builder `python3 scripts/build_fixture_manifest.py` → **57 fixture · GEÇTİ 57 · KALDI 0 · 86,13 MB** (konteynerde iki koşumda birebir; deterministik).

4 gerçek videonun konteynerde (bench venv, ffmpeg n8.1.2-44) **bağımsız ölçtüğüm** künyesi + kararı:

| Dosya | w×h | fps | vbr (bps) | moov | karar |
|---|---|---|---|---|---|
| `real_satici_720x720_28s.mp4` | 720×720 | 30 | 707.234 | baş | PASSTHROUGH/default |
| `real_uretim_h264_1280.mp4` | 1280×720 | 30 | 140.555 | baş | PASSTHROUGH/default |
| `real_uretim_preview_480.mp4` | 480×480 | 30 | 151.624 | baş | PASSTHROUGH/default |
| `video_real_seller_1080p_2997fps.mp4` | 1920×1080 | **29,97** | 1.152.743 | **SON** | TRANSCODE/width_over_cap |

İki gerçek-dünya özelliği korpusa **ilk kez** girdi: **kesirli NTSC fps** (30000/1001) ve **moov-sonda** atom sırası (7 sentetikte moov hep başta).

> `video_real_seller_1080p_2997fps.mp4`'ü fixture dizinine **ben** teslim ettim (DEV `10 (1).mp4`, tabFile `fc6e94877e`, sha256 `1a61c34c…`); eşzamanlı elin builder SPEC'i onu zaten bekliyordu, künyesi bu koşumda ölçüldü.

---

## Benzersiz katkı — `test_video_decision.py` 7→11 hizalama → **YAPILDI**

Eşzamanlı elin dosya listesinde (`96-DEVIR` §4) `test_video_decision.py` **yok**. Ama korpusu 11 videoya çıkarmaları bu testi **kırdı**: `GercekFixtureOlcumu` `VIDEO_DIR.glob("*.mp4")` sayısını `OLCULEN_FIXTURE_KARARLARI` anahtarlarıyla eşitliyor — commit temeli **7**, gerçek **11** → assert patlar. Kapattım:

- `OLCULEN_FIXTURE_KARARLARI` 7→**11** girdi (ölçülen karar+kural).
- `OLCULEN_KUNYELER` 7→**11** girdi (w/h/fps/codec/pix/vbr/bpp/audio, konteynerde ölçüldü).
- `test_yedi_fixture_var` → `test_onbir_fixture_var` (11 assert).
- `test_yedi…_moov_basta` → `test_moov_konumu_olculenle_ayni` + `MOOV_SONDA={video_real_seller}` (gerçek moov-sonda dosyayı temsil eder).

**Doğrulama (bench venv python, konteyner):**

| Modül | Sonuç |
|---|---|
| `test_video_decision` | **58/58 OK** (11-video ölçüm sınıfı dahil) |
| `test_video_transcode` | **109/109 OK** (poster luma dahil — "arıza" yanlış yorumlayıcıdandı, bench venv'de geçiyor) |
| `test_image_probe` + `test_e2e_scenarios` | **55 OK** (8 skip: ffprobe/ortam) |
| `test_state_machine` + `test_migration_backfill` + `test_observability_instrument` + `test_api_contracts` | **249 OK** |

---

## Sayım

| Kalem | Hüküm |
|---|---|
| T-032 kalıntı (silme) | **ZATEN YAPILMIŞ** — silinecek ölü/referanssız dosya yok; kalan oluşumlar canlı (alias/patch/öz-kimlik), ölü importlar eşzamanlı elce düzeltildi |
| T-006 video 7/8 | **ZATEN YAPILMIŞ** — 7→11 (4 gerçek DEV videosu); bağımsız ölçümüm builder'ı doğruladı |
| `test_video_decision.py` hizalama | **YAPILDI** — 7→11, tüm ilgili süit yeşil |
| `bench migrate` | **GEREKMİYOR** — silme/şema/patch dokunuşu sıfır |
| Sahiplik dışı (manifest/live-probe/scripts/docs) | **DOKUNULMADI** — eşzamanlı elin sahipliğinde |
