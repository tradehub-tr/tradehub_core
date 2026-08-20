# 90 — W8: Video hattının kalanları (önizleme klibi · LISTING API · T-141 S7/S8)

**Tarih:** 2026-08-20 · **Ortam:** DEV (`istoc.localhost`, `istoc-dev` compose)
**Görev:** Rapor 84'ün (W7-1) bilinçli açık bıraktığı üç kalemi ÖNCE ölçüp
(yapılmış mı?), yapılmamışsa kapatmak. Süre iddiası yok; ölçü birimi BAYT,
VMAF, HTTP durum kodu, DOM özniteliği ve test sayısı.

---

## 0. Sonuç özeti

| Kalem | Ön ölçüm (bugün 12:00 öncesi) | Sonuç |
|---|---|---|
| 1. Hareketli önizleme klibi | **YAPILMAMIŞTI** | **YAPILDI** (ölçüldü) |
| 2. videoPoster/video → LISTING API | **YAPILMAMIŞTI** | **YAPILDI** (ölçüldü) |
| 3. T-141 S7/S8 gerçek test | **YAPILMAMIŞTI** | **YAPILDI** (ölçüldü) |

Regresyon: istenen tüm suitler yeşil (`test_video_servis` 28, video 58+109=167,
manifest 11+16, `test_pipeline_bridge` 25*, `test_video_live_run` 17) + yeni
**23** backend testi + **5** Playwright testi + vitest video suitleri 21.
\* Görev 22 istiyordu; modülde bugün 25 test var (paralel dalga eklemiş) — 25/25 OK.

**Kısıtlara uyum:** hiçbir repoda commit atılmadı; `hooks.py`/`patches.txt`'e
DOKUNULMADI (`git diff` kanıtı: `api/listing.py`'de yalnız +28 satırlık video
bloğu benim; hooks/patches değişiklikleri önceki dalgaların uncommitted işi);
`MediaVideo.vue`'ya (admin-panel) dokunulmadı; şema değişikliği YOK → migrate
koşulmadı; `vmaf_min` (93) ve eşikler değişmedi.

---

## 1. Kalem 1 — Hareketli önizleme klibi (T-073 kalanı)

### 1a. Ön ölçüm: YAPILMAMIŞTI

- `_produce_video_outputs` zinciri yalnız `primary → poster → hls` üretiyordu;
  `make_preview_clip` çağıran TEK üretim satırı yoktu (grep: `preview` yalnız
  `poster.py` motorunda ve bir yorumda).
- Manifest `video` bloğunda `previewSrc` alanı yoktu (rapor 84 §5 gövdesi ve
  kod: `src/type/hlsSrc/poster/…` — preview yok).
- DEV DB ölçümü: iki video varlığının (`3pjpbple42`, `59jmq0pkp0`) türev
  satırları `h264/poster/hls` + `poster` — **`preview` profili 0 kayıt**.

### 1b. Yapılan (W7-1'in kurduğu desenle)

`media/pipeline_bridge.py` — yeni `_produce_video_preview` (posterle aynı
sözleşme: best-effort, hata teslimi düşürmez), zincire `poster`dan sonra
eklendi; `VIDEO_PREVIEW_PROFILE="preview"` sabiti iki uçta da (köprü +
manifest) tanımlı:

- **Kuyruk yolu:** ayrı iş YOK — klip, `_run_video_job`un ürettiği türevlerden
  biri (poster gibi). Şartname (51-faz7 §T-073) klibi poster'la aynı görev
  altında sayıyor.
- **Kanonik adres:** `dedup.rendition_path` kökü —
  `/files/media/{asset}/{version_hash}/preview-{genişlik}.mp4`. Genişlik
  ÇIKTININ ölçülen değeri (klip ölçeği yönelime duyarlı: dikey kaynakta 480
  kısa kenar; `spec.width=854` dikeyde yalan söylerdi).
- **DocType kaydı:** `Media Rendition(profile=preview, format=mp4)`;
  `quality` alanı klibin CRF'ini taşır.
- **Bayt kapısı:** motorda (CRF 28→32→36 + süre 6→4→3 merdiveni). Merdiven
  tükenip 1 MB görev kapısı aşılırsa (`within_task_gate=False`) dosya SİLİNİR
  ve satır AÇILMAZ — h264/HLS kapılarıyla aynı "satır yalnız teslim edilebilir
  dosyanın künyesidir" sözleşmesi. 400 KB politika hedefi aşımı teslimi
  engellemez (motor notu sonuçta).
- **Manifest:** `_tek_video_govdesi` artık `previewSrc` basıyor (yalnız video
  slotunda — görsel gövdesi/ETag'i DEĞİŞMEDİ, 11+16 test yeşil).

### 1c. Ölçümler

Backfill (yeni üretim fonksiyonu bench console'dan, mevcut version_hash
altına — hash politika/motor değişmediği için AYNI kaldı, INV-09 tutarlı):

| Varlık | Klip | Bayt | Kapılar |
|---|---|---:|---|
| `59jmq0pkp0` (limon, 720×720) | `preview-480.mp4` | 116.775 | 1 MB görev + 400 KB politika: İKİSİ DE GEÇTİ |
| `3pjpbple42` (9mb, 1280×720) | `preview-854.mp4` | 41.786 | aynı |

HTTP (gateway): iki adres de **200 `video/mp4`** (bayt-birebir).
Worker zinciri testle ölçüldü: sentetik videoda `_run_video_job` sonrası
`preview` satırı + kanonik adres (`parse_rendition_path`) + diskte dosya +
süre ≤ merdiven tavanı (`test_worker_preview_turevini_uretir_ve_kaydeder`);
kapıdan düşen klibin kayda geçmediği ve hatanın teslimi düşürmediği ayrıca
testli (mock'lu iki test).

## 2. Kalem 2 — video varlığının LISTING API'sine bağlanması

### 2a. Ön ölçüm: YAPILMAMIŞTI

- `api/listing.py::get_listing_detail` yalnız ham `videoUrl` basıyordu
  (curl, 11:19): `{"videoUrl": "/files/Evde taze sıkılmış … limon.mp4"}` —
  `videoPoster`/`hlsSrc` alan adları dosyada hiç geçmiyordu.
- Storefront tarafı hazırdı (W7-2): `listingService.ts` `videoPoster`'ı
  bekliyor ("API bastığı gün otomatik akar" notu yerinde).

### 2b. Yapılan

- **`api/media_manifest.py` (yalnız EK):** `video_bloklari(ilanlar)` —
  LISTING API'nin alt-katman girişi. Manifest mantığı KOPYALANMADI:
  fonksiyon `_video_manifest_batch_icin`i çağırır; görünürlük/bayrak/sızıntı
  kuralları oradadır (görünmez ilan → blok `None`, alanlar boş — yayın
  takvimi sızmaz). Whitelist değil; süreç-içi çağrı.
- **`api/listing.py`:** `get_listing_detail` gövdesine 4 alan:
  `videoPoster`, `videoHlsSrc`, `videoPreviewSrc`, `videoSrc` (h264 türevi;
  passthrough'ta ham dosya). Ham `videoUrl` DEĞİŞMEDİ. Video alanları detay
  ucunu asla düşürmez (`_video_manifest_blogu` try/except; testli).
- **Storefront (yalnız alan tüketimi):** `types/product.ts` +
  `listingService.ts` (yeni alanlar, boş/whitespace elenir; galeri video
  slaytının `src`'i artık `videoHlsSrc || videoSrc || videoUrl`, slayta
  `poster` bağlandı), `alpine/product.ts` `renderInlineVideo(url, poster)`,
  `ProductVideoSection.ts` aynı tercih sırası + `data-listing-preview`.
  `MediaVideo.vue`'ya dokunulmadı.

### 2c. Ölçümler

curl (gateway, LST-04043 — cache temizlenip):

```json
"videoUrl":        "/files/Evde taze sıkılmış … limon.mp4",          ← ham, değişmedi
"videoPoster":     "/files/media/59jmq0pkp0/3ebd…b12b/poster-720.webp",
"videoHlsSrc":     null,                                              ← passthrough: HLS yok (doğru)
"videoPreviewSrc": "/files/media/59jmq0pkp0/3ebd…b12b/preview-480.mp4",
"videoSrc":        "/files/Evde taze sıkılmış … limon.mp4"            ← h264 türevi yok → ham
```

**Vitrin DOM'u (canlı, istoc.localhost — storefront imajı rebuild edildi):**
ürün sayfası CSR olduğu için düz curl yalnız iskeleti görür (ölçüldü:
`data-hls-src` HTML kaynağında 0); gerçek ölçüm render edilmiş DOM'da yapıldı
(headless Chrome). LST-04043 video slaytı:

```
<video src="/files/Evde taze sıkılmış … limon.mp4"
       poster="/files/media/59jmq0pkp0/3ebd…b12b/poster-720.webp" …>
```

→ **manifest posteri ürün sayfasında canlı akıyor.** `data-hls-src` canlıda
gösterilemedi çünkü DEV'deki tek HLS'li ilan (LST-04419) hâlâ
`Pending`/görünmez — manifest bilinçli boş dönüyor (rapor 84 §8.4; yayına
alma moderasyon kararı, bu görevde İLAN YAYINLANMADI). HLS akışının DOM
kanıtı gerçek bileşenlerle Playwright'ta: API `videoHlsSrc` bastığında ana
alanda `video[data-hls-src="…master.m3u8"][poster]` basılıyor ve ham dosya
DOM'da geçmiyor (§3 vitrin testleri, yeşil).

Not: `get_listing_detail` yanıtı ilan×dil önbellikli (TTL 300 sn) — türev
sonradan üretilirse alanlar en geç 5 dk'da akmaya başlar.

## 3. Kalem 3 — T-141 video senaryoları (S7/S8)

### 3a. Ön ölçüm: YAPILMAMIŞTI

`tests/e2e/media-video-pipeline.spec.ts` iki `test.skip`'li iskeletti (hiçbir
şey ölçmüyordu); atlama gerekçesi "boru hattı ölü + fixture yok" idi — ikisi
de düştü (hat canlı, fixture'lar `tests/fixtures/media/video/` altında).

### 3b. Yapılan — iki yarımlı gerçek test

- **Bench-yardımcılı yarı** (kabul ölçütleri tarayıcıdan görünmez):
  yeni `tradehub_core/tests/t141_bench.py` — assert'süz ÖLÇÜM ucu
  (`docker exec … bench execute` → JSON); iddiayı Playwright verir. Sahte
  yeşil iki uçta da imkânsız: helper'da assert yok, testte ölçüm yok.
  Docker/konteyner yoksa test SKIP (yeşil değil).
- **Vitrin yarısı:** paketin standart `page.route()` mock deseniyle gerçek
  bileşenler üzerinden DOM ölçümü.
- Görev şartına uyum: S8 **kapının SONUCUNU** iddia eder — kapı GEÇERSE
  küçülme + VMAF ≥ eşik; kapı DÜŞERSE (89,31<93 vakası) türevin teslim
  EDİLMEDİĞİ; "türev üretildi" varsayımı yok. VMAF ölçülemiyorsa
  (libvmaf'sız imaj) SKIP — sayı uydurulmaz.

### 3c. Ölçümler (2026-08-20, konteyner ffmpeg n8.1.2-44, libvmaf=1)

**S7** (`video_efficient_720p_750k.mp4`, 1.092.127 B):
karar **PASSTHROUGH** (`rule=default`), `writes_new_file=false`; uygulama
ffmpeg koşturmadı, hedefe dosya yazılmadı; kaynak SHA-256 koşum öncesi/sonrası
**AYNI** → "dokunulmadı" bayt kanıtıyla.

**S8** (`video_bloated_720p_8m.mp4`): karar **TRANSCODE**
(`bitrate_over_cap`); üretim kapılarıyla sonuç:

| Ölçüm | Değer |
|---|---|
| Bayt | 10.450.180 → **3.518.231** (kazanç %66,33 ≥ %10) |
| VMAF | **96,655 ≥ 93** → `vmaf_gate: GECTI` |
| Teslim | çıktı diskte, `accepted=true` |

**Playwright: 5/5 yeşil** (S7 bench, S8 bench, S7 vitrin — türev yokken ham
mp4 progressive + `data-hls-src` YOK, S8 vitrin — `data-hls-src`+poster var
ve ham dosya DOM'da yok, S8 vitrin-b — HLS'siz h264 türevi `src` olur).

## 4. Testler ve regresyon

Yeni: `tradehub_core/tests/test_video_preview_ve_listing.py` — **23 test**
(preview worker zinciri + kapı/hata sözleşmeleri; manifest `previewSrc`
dolu/boş; `get_listing_detail` alanları dolu / bayrak kapalı → None /
manifest düşse bile uç düşmez; W7 `TestManifestVideo`'nun 5 testi miras
yoluyla iki fixture bağlamında yeniden koşuyor — bedava regresyon).

| Suit (konteyner, `bench run-tests`) | Sonuç |
|---|---|
| `test_video_preview_ve_listing` (yeni) | **23/23 OK** |
| `test_video_servis` | **28/28 OK** |
| `test_pipeline_bridge` | **25/25 OK** (görev şartı 22 idi; bugün 25) |
| `test_media_manifest_api` / `test_manifest_batch` | **11/11 / 16/16 OK** |
| `test_video_decision` + `test_video_transcode` | **58+109 = 167/167 OK** |
| `test_video_live_run` | **17/17 OK** |
| Playwright `media-video-pipeline.spec.ts` | **5/5 OK** |
| vitest `ProductVideoSection` + `hlsVideo` | **21/21 OK** |
| `tsc --noEmit` / eslint (değişen dosyalar) | temiz |

Vitest tam koşumunda 6 KIRMIZI var (`ProductOrderPanel`/`ProductBuyBox`/
`messages`) — **benden ÖNCE de kırmızıydılar** (ölçüldü: 4 dosyam stash'lanıp
aynı testler koşuldu → aynı 6 kırmızı; paralel dalgaların uncommitted işi).

## 5. Değişen dosyalar

| Dosya | Ne |
|---|---|
| `tradehub_core/media/pipeline_bridge.py` | `VIDEO_PREVIEW_PROFILE` + `_produce_video_preview` + zincire ek |
| `tradehub_core/api/media_manifest.py` | `VIDEO_PREVIEW_PROFILE`, `previewSrc`, `video_bloklari()` (EK) |
| `tradehub_core/api/listing.py` | +28 satır: `_video_manifest_blogu` + 4 alan |
| `tradehub_core/tests/test_video_preview_ve_listing.py` | yeni, 23 test |
| `tradehub_core/tests/t141_bench.py` | yeni, S7/S8 ölçüm ucu |
| `tradehubfront/src/types/product.ts` | `videoHlsSrc/videoSrc/videoPreviewSrc`, `ProductImage.poster` |
| `tradehubfront/src/services/listingService.ts` | alan eşleme + galeri video slaytı kaynak tercihi + poster |
| `tradehubfront/src/alpine/product.ts` | `renderInlineVideo(url, poster)` (3 çağrı noktası) |
| `tradehubfront/src/components/product/ProductVideoSection.ts` | kaynak tercihi + `data-listing-preview` |
| `tradehubfront/tests/e2e/media-video-pipeline.spec.ts` | iskelet → 5 gerçek test |

## 6. DEV'de bırakılan izler / notlar

1. İki `Media Rendition(preview)` satırı + iki klip dosyası (§1c) — mevcut
   version_hash köklerinin altında (hash değişmedi; politika/motor aynı).
2. Konteyner kodu `docker cp` ile eşitlendi (backend + queue-long, restart'lı;
   md5 repo ile birebir doğrulandı) — kalıcılık için imaj rebuild gerekir
   (bilinen durum). **Storefront imajı rebuild edildi** (`compose build
   storefront`) — canlı DOM ölçümü bunun üzerinde.
3. **Paralel dalga gözlemi:** ben senkron etmeden ÖNCE konteynerdeki
   `pipeline_bridge.py` benim yerel düzenlememle bayt-birebir aynıydı
   (mtime 11:47:47) — bu repoda eşzamanlı çalışan başka bir ajan dosyaları
   konteynere kopyalıyor görünüyor. Çakışma görülmedi ama bilinmeli.
4. LST-04419 hâlâ `Pending` — canlı `data-hls-src` ölçümü ilan yayına
   alınınca tek tıkla doğrulanabilir (uç ve vitrin hazır, DOM kanıtı testte).
5. `get_listing_detail` önbelleği (300 sn) türev alanlarını da taşıyor —
   türev üretimi anında görünmesi istenirse cache invalidation ayrı iş.
6. Rapor 84 §8'in diğer kalemleri (poster srcset, karar izi şeması, W6-B
   artık dosyaları) bu görevin kapsamı dışında; hâlâ açık.
