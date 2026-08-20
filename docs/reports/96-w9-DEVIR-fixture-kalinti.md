# 96 · W9 DEVİR NOTU — fixture + kalıntı (bu ajan; tam rapor aabb5f6'da)

**Tarih:** 2026-08-20 · **Kapsam:** T-006 fixture eksikleri · T-032 kalıntı · T-140 ölçümü
**NOT:** Bu W9-2 görevinin PARALEL kopyası (aabb5f6) da koşuyordu; tam
`96-w9-temizlik.md`'yi o yazıyor olabilir. Bu dosya yalnız BENİM fiilen
DEĞİŞTİRDİĞİM şeyleri ve ölçümlerimi devreder — çakışmayı önlemek için ayrı ad.
Commit YOK.

---

## 1. T-006 — video/görsel fixture eksikleri (YAPILDI, ölçüldü)

Rapor 94 §3'ün 5 eksik türü ÖLÇÜLDÜ; sentetik ÜRETİLMEDİ. DEV'de 4.213 görsel
(PIL/ICC/EXIF) + 6 gerçek video (>100 KB, ffprobe) tarandı (`istoc-dev-backend-1`).

**Korpusa eklenen 6 GERÇEK dosya** (`docker cp`, bayt-birebir; köken notu +
sha256 manifest'te `koken` blokunda):

| Fixture | Köken | sha256 (baş) | needs_transcode / karar |
|---|---|---|---|
| `video/real_satici_720x720_28s.mp4` | LST-04043 limon videosu (canlı satıcı) | `eb52e15d…` | PASSTHROUGH (**8. video eksiği kapandı**) |
| `video/real_uretim_h264_1280.mp4` | boru hattı üretim çıktısı (9mb REMUX, INV-09 adresli) | `64fa75a4…` | False (üretim çıktısı = meşru fixture) |
| `video/real_uretim_preview_480.mp4` | W8 preview türevi (rapor 90) | `7d4cf07f…` | False |
| `video/video_real_seller_1080p_2997fps.mp4` | DEV `10 (1).mp4`; **korpusun tek kesirli fps'i (29,97)** | `1a61c34c…` | True |
| `images/real_foto_canon_2240x2905.tif` | Canon EOS 5D Mark IV, gerçek fotoğraf (AS-27) | `79ed518c…` | reject/ratio (motorla ölçüldü) |
| `images/real_adobergb_3780x2717.png` | Adobe RGB (1998) ICC'li görsel (T-061/3) | `2f043395…` | reject/ratio (motorla ölçüldü) |

> `video_real_seller_1080p_2997fps.mp4` fixture dizinine bu koşum sırasında
> PARALEL bir elden gelmişti (change 12:40); üzerine yazmadım — köken sha256'yla
> doğrulayıp künyesini bu koşumda ölçtüm ve manifest'e meşru fixture olarak
> aldım.

**TEMİN EDİLEMEDİ (manifest `eksik_turler`'e yazıldı):**
- **4K/60fps uzun video** — DEV'deki 6 gerçek video ≤1920×1080 ve ≤30 fps.
- **HDR/BT.2020 video** — 6/6'da `color_primaries ∈ {bt709, smpte170m/bt470bg, unknown}`.
- **Gerçek fotoğraf (AS-27)** — 1 gerçek fotoğraf alındı ama korpus hâlâ ağırlıkla
  sentetik; tek dosya kalibrasyon DEĞİL (kayda geçti).

**Manifest yeniden üretimi:** `python3 scripts/build_fixture_manifest.py` →
**57 fixture · GEÇTİ 57 · KALDI 0 · 86,13 MB** (iki koşumda birebir; deterministik).
Özet: video 7→**11**, photo 17→**19**; `_w9_eki` bloklarıyla `live-probe.json`'a
4 videonun ffprobe/needs_transcode künyesi KONTEYNERDE ölçülüp eklendi.

## 2. T-032 — kalıntı temizliği (ÖLÇÜLDÜ + betiklerde YAPILDI)

**Ölçüm — `media_engine` kalıntısının bugünkü doğası:**

- **SAD gövdesi (M-01):** rapor 88 ZATEN kapatmış — gövdedeki 6 `media_engine`
  satırı gerçek yola çevrilmiş; kalanlar M-01 izleme tablosunda TARİHSEL kayıt.
- **Python testleri** (`test_state_machine`, `test_api_contracts`,
  `test_migration_backfill`): `import … as media_engine` bilinçli TAKMA AD,
  kalıntı değil. `test_state_machine` 47/47 OK (dizin yokluğunu sabitliyor).
- **`patches/v15_9_22_media_engine_settings.py`** → `media_engine_settings`
  GERÇEK doctype adı (13 kurulu doctypeten biri). Kalıntı DEĞİL.
- **Ölü betik kalıntısı (ÇAĞIRANI SIFIR — düzeltildi):** 5 betikte ya ölü
  `from media_engine.X import` (modül o adla YOK → ImportError) ya ölü
  `ROOT/tests/fixtures` yolu (göç sonrası dizin yok) vardı:
  - `scripts/measure_ssim_quality.py`, `scripts/measure_render_t063.py`,
    `scripts/measure_faz1.py` → import `tradehub_core.media.pipeline.*`'a çevrildi.
  - `scripts/gen_fixtures_images.py`, `scripts/build_fixture_manifest.py`,
    ve yukarıdaki üçünün `--fixtures` varsayılanı →
    `ROOT/tradehub_core/tests/fixtures`'a çevrildi.
  - Beşinde de `# W9 T-032 düzeltmesi` imzası; `py_compile` 5/5 OK.
  - `gen_fixtures_video.sh` → `/tmp/fixvid`'e yazıyor, `tests/` köküne referans
    yok; düzeltme GEREKMEDİ.

**RAPORLANIR (dokunulmadı — doc sahipliği rapor 88 doc-ajanında + çakışma riski):**
`docs/ui/faz11-simulator.md` (`python3 -m media_engine.simulator.srcset` — ölü
komut, gerçek yol `tradehub_core.media.pipeline.simulator.srcset`),
`docs/ui/faz9-media-library.md`, `docs/adr/0003-*` (BİLİNÇLİ tarihsel — media_engine
app'inin neden reddedildiğini anlatıyor), `docs/plans/faz14-golive.md`,
`docs/api/README.md`, `docs/data/data-model-review.md`, `docs/sad/review-v1.0.md`.
Bunların bir kısmı bilinçli tarihsel referans; kalanlar bayat doc — belge
sahibinin işi.

## 3. T-140 — 12 aday ölçümü (matris YENİDEN ÜRETİLMEDİ — gerekçe aşağıda)

Rapor 93 §2'nin ~12 "emin olunamayan" adayı bugün (aynı gün) yeniden ölçüldü.
**Sonuç: hiçbiri yeni etiketi hak edecek kadar DEĞİŞMEDİ → hepsi KALICI-GEREKÇELİ.**

- **FR-127 (playsinline):** ZATEN kapsanıyor — `mediaDelivery.test.js:189`
  `[FR-127]` (W3-A/rapor 68'den beri; muted+playsinline+loop). Storefront
  `ProductVideoSection.test.ts` playsinline'ı KOŞULSUZ assert ediyor (autoplay
  değil) → FR-127'nin "autoplayda muted+playsinline" sözleşmesini TEK BAŞINA
  kanıtlamıyor; ayrıca zaten kapsandığından etiket gereksiz. UNCHANGED.
- **FR-118 (`private_transcode_atlandi`):** mesaj HİÇBİR testte yok
  (`mediaVideoStatus.test.js` grep=0); yalnız slot JSON + vendor'da. UNCHANGED —
  gerekçeli kalıyor.
- **hlsPlayback.test.js:** playsinline assert=0; HLS teslimi hâlâ FR değil.
- Kalan adaylar (dedupCheck, videoDecision, policyEngineParity, lcpImagePreload,
  cardGridWindow, mediaOrphans, sellerMediaFolders, crop/console-access spec'leri,
  skip'li media-video-pipeline) rapor 93'teki gerekçeleriyle AYNI.

**Matris neden yeniden üretilmedi:** `scripts/gen_traceability.py` (+135 satır) ve
`docs/test/traceability.md` PARALEL ellerce uncommitted değiştirilmiş; ben
dokunmadım. Aynı gün, gereksinim sürüklenmesi 0 olduğundan matris sayıları
değişmezdi. Betiği koşmak paralel ajanın diff'ini bozar → çakışma riski.
Koordinatör tam raporu aabb5f6'ya verdi; matris yeniden üretimi orada tek elde
toplanmalı.

## 4. Dokunduğum dosyalar (tam liste)

| Dosya | İş | Doğrulama |
|---|---|---|
| `tradehub_core/tests/fixtures/media/manifest.json` | 6 gerçek fixture + `eksik_turler` + `koken`/`guncelleme` | betikten yeniden üretildi 57/57 |
| `tradehub_core/tests/fixtures/media/live-probe.json` | 4 video ffprobe/nt bloğu (`_w9_eki`) | konteynerde ölçüldü |
| `tradehub_core/tests/fixtures/media/video/real_*.mp4` (3) + `video_real_seller_1080p_2997fps.mp4` (paralel) | ikili (docker cp) | sha256 doğrulandı |
| `tradehub_core/tests/fixtures/media/images/real_*.{tif,png}` (2) | ikili (docker cp) | sha256 doğrulandı |
| `scripts/build_fixture_manifest.py` | yol düzeltmesi + 6 SPEC + `EKSIK_TURLER` + köken taşıma | koştu, exit 0 |
| `scripts/gen_fixtures_images.py` | `tests/`→`tradehub_core/tests/` yol | py_compile OK |
| `scripts/measure_ssim_quality.py` | ölü import + `--fixtures` yolu | py_compile OK |
| `scripts/measure_render_t063.py` | ölü import + FIXTURE yolu | py_compile OK |
| `scripts/measure_faz1.py` | ölü import + `--fixtures` yolu | py_compile OK |

**DOKUNULMADI:** `gen_traceability.py`, `traceability.md`, hooks/patches, panel
bileşenleri, storefront ızgara/manifest (W9-1), commit yok.

## 5. Sayım

| Kalem | Hüküm |
|---|---|
| T-006 8. video | **YAPILDI** (gerçek satıcı videosu) |
| T-006 4K/60fps · HDR | **YAPILAMADI** — DEV'de gerçek kaynak yok (ölçüldü), sentetik yasak |
| T-006 AdobeRGB · gerçek fotoğraf | **YAPILDI** (gerçek kaynak), foto korpusu hâlâ ağırlıkla sentetik notlu |
| T-032 betik kalıntısı | **YAPILDI** (5 betik, çağıranı sıfır ölü kod) |
| T-032 doc kalıntısı | **RAPORLANDI** (doc sahibi + çakışma) |
| T-140 12 aday | **ÖLÇÜLDÜ** — hepsi KALICI-GEREKÇELİ (aynı gün, sürüklenme yok); matris aabb5f6'da |
