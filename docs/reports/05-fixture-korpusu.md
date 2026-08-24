# Golden Fixture Korpusu — T-006

**Tarih:** 2026-08-18 · **Branch:** `medya-motoru-faz0-faz2` · **Ortam:** yerel stack (12 servis ayakta)
**Çıktı:** `tests/fixtures/media/` (34 görsel + 7 video) · `tests/fixtures/malicious/` (10 kötücül) · `tests/fixtures/media/manifest.json`

Bu korpus Faz 1'in **ön koşuludur**. Motora dokunmadan önce "çıktı bozuldu mu"
sorusunu cevaplayacak referans kümesi budur. Korpus olmadan yapılan her motor
değişikliği, doğrulanamayan bir değişikliktir.

> **Bu rapordaki her sayı ölçüldü.** Geometri/biçim/bayt ölçümleri yerel
> Pillow 11.3.0 ile, motor davranışı ölçümleri (`engine.probe`,
> `engine.optimize`, `ffprobe`, `needs_transcode`) konteynerde **gerçek
> `tradehub_core` kaynak dosyaları** çalıştırılarak yapıldı. Ham çıktılar
> `tests/fixtures/media/live-probe.json` içinde kanıt olarak duruyor.
> Ölçülemeyen hiçbir alan doldurulmadı.

---

## 1. Korpus tek bakışta

| | |
|---|---:|
| Fixture sayısı | **51** |
| Toplam boyut | **60,84 MB** (bütçe 200 MB — %30) |
| `expect` ↔ `olculen` doğrulaması | **51 GEÇTİ / 0 KALDI** |
| Manifest ↔ disk eşleşmesi | **51 / 51**, fazlalık ve eksik yok |

| sınıf | adet | | beklenen aksiyon | adet |
|---|---:|---|---|---:|
| `photo` | 17 | | `process` | 26 |
| `transparent` | 5 | | `passthrough` | 5 |
| `graphic` | 10 | | `reject` | 20 |
| `animation` | 2 | | | |
| `video` | 7 | | | |
| `malicious` | 10 | | | |

**Kötücül fixture'lar ayrı dizindedir** (`tests/fixtures/malicious/`) ve
manifest'te `"class": "malicious"` ile işaretlidir. Hiçbiri
`tests/fixtures/media/` altına karışmaz — bir test koşucusu "medya klasörünü
tara" derse bombayı yanlışlıkla açmaz.

---

## 2. Doğrulama yöntemi

Manifest'te her fixture iki blok taşır:

- **`expect`** — BEYAN. Fixture'ın ne olması gerektiği.
- **`olculen`** — ÖLÇÜM. Dosyadan gerçekten okunan değerler (sha256 dâhil).

`scripts/build_fixture_manifest.py` ikisini karşılaştırır ve `dogrulama`
alanına `GEÇTİ`/`KALDI` yazar; bir tek uyuşmazlıkta çıkış kodu 1 olur. Yani
manifest'teki hiçbir sayı elle yazılmadı — **beyan edilen ile ölçülen ayrı
tutuldu ki fixture'ın kendisi bozulduğunda sessizce geçmesin.**

Bozuk dosyalarda **başlık (`Image.open`) ile piksel (`Image.load`) ayrı
ölçülür**. Bu ayrım keyfî değil: motorun `probe()`/`optimize()` ayrımının
birebir karşılığıdır ve §4'te görüleceği gibi gerçek bir güvenlik açığını
görünür kılar.

---

## 3. Korpus envanteri (ölçülmüş)


#### A) Görsel fixture'lar (34)

| dosya | sınıf | slot | beklenen | ölçülen | bayt | biçim/mod | doğrulama |
|---|---|---|---|---|---:|---|---|
| `p01_18mp_1mb.jpg` | photo | `product.image` | **reject** | 5184×3456 · 17,92 MP | 1.02 MB | JPEG / RGB | ✅ |
| `dpi_3000x3000_300dpi.tif` | photo | `product.image` | **process** | 3000×3000 · 9,00 MP | 20.98 MB | TIFF / RGB | ✅ |
| `mode_cmyk.jpg` | photo | `product.image` | **process** | 1600×1600 · 2,56 MP | 1.89 MB | JPEG / CMYK | ✅ |
| `mode_rgba_alpha.png` | transparent | `product.image` | **process** | 1200×1200 · 1,44 MP | 10.2 KB | PNG / RGBA | ✅ |
| `mode_palette_p.png` | graphic | `product.image` | **process** | 1200×1200 · 1,44 MP | 800.5 KB | PNG / P | ✅ |
| `mode_grayscale_l.png` | graphic | `product.image` | **process** | 1400×1400 · 1,96 MP | 883.6 KB | PNG / L | ✅ |
| `geom_strip_400x4000.png` | graphic | `product.image` | **reject** | 400×4000 · 1,60 MP | 2.31 MB | PNG / RGB | ✅ |
| `geom_1x1.png` | graphic | `product.image` | **reject** | 1×1 | 69 B | PNG / RGB | ✅ |
| `exif_orientation6.jpg` | graphic | `product.image` | **reject** | 1200×1600 · 1,92 MP | 46.9 KB | JPEG / RGB | ✅ |
| `exif_gps.jpg` | photo | `product.image` | **process** | 1600×1600 · 2,56 MP | 724.6 KB | JPEG / RGB | ✅ |
| `enc_progressive.jpg` | photo | `product.image` | **process** | 1800×1800 · 3,24 MP | 670.2 KB | JPEG / RGB | ✅ |
| `anim_6frames.gif` | animation | `product.image` | **reject** | 600×600 · 0,36 MP | 5.4 KB | GIF / P | ✅ |
| `anim_webp.webp` | animation | `product.image` | **reject** | 600×600 · 0,36 MP | 14.6 KB | WEBP / RGBA | ✅ |
| `enc_webp_lossy.webp` | photo | `product.image` | **process** | 1600×1600 · 2,56 MP | 499.4 KB | WEBP / RGB | ✅ |
| `enc_webp_lossless.webp` | transparent | `seller.logo` | **process** | 1024×1024 · 1,05 MP | 1.5 KB | WEBP / RGBA | ✅ |
| `edge_short32.jpg` | photo | `product.image` | **reject** | 32×48 · 0,00 MP | 1.3 KB | JPEG / RGB | ✅ |
| `edge_short4480.jpg` | photo | `product.image` | **process** | 4480×5600 · 25,09 MP | 1.61 MB | JPEG / RGB | ✅ |
| `edge_72mp.jpg` | photo | `product.image` | **process** | 8527×8527 · 72,71 MP | 1.34 MB | JPEG / RGB | ✅ |
| `bound_short999.jpg` | photo | `product.image` | **reject** | 999×999 · 1,00 MP | 244.8 KB | JPEG / RGB | ✅ |
| `bound_short1000.jpg` | photo | `product.image` | **process** | 1000×1000 · 1,00 MP | 242.5 KB | JPEG / RGB | ✅ |
| `ok_product_1x1_2400.jpg` | photo | `product.image` | **process** | 2400×2400 · 5,76 MP | 1.02 MB | JPEG / RGB | ✅ |
| `ok_product_4x5.jpg` | photo | `product.image` | **process** | 2000×2500 · 5,00 MP | 788.5 KB | JPEG / RGB | ✅ |
| `logo_alpha_512.png` | transparent | `seller.logo` | **process** | 512×512 · 0,26 MP | 3.0 KB | PNG / RGBA | ✅ |
| `logo_jpeg_noalpha.jpg` | graphic | `seller.logo` | **process** | 600×600 · 0,36 MP | 17.3 KB | JPEG / RGB | ✅ |
| `logo_wordmark_2876.png` | transparent | `seller.logo` | **reject** | 1438×500 · 0,72 MP | 4.8 KB | PNG / RGBA | ✅ |
| `logo_short200.png` | transparent | `seller.logo` | **reject** | 200×200 · 0,04 MP | 1.0 KB | PNG / RGBA | ✅ |
| `ok_cover_24x5.jpg` | photo | `company.cover_image` | **process** | 2400×500 · 1,20 MP | 210.1 KB | JPEG / RGB | ✅ |
| `ok_banner_2x1.jpg` | photo | `category.banner` | **process** | 2000×1000 · 2,00 MP | 340.0 KB | JPEG / RGB | ✅ |
| `ok_avatar_96.png` | graphic | `user.avatar` | **process** | 96×96 · 0,01 MP | 505 B | PNG / RGB | ✅ |
| `content_blank_white.png` | graphic | `product.image` | **process** | 1200×1200 · 1,44 MP | 6.7 KB | PNG / RGB | ✅ |
| `content_border_40pct.png` | graphic | `product.image` | **process** | 1400×1400 · 1,96 MP | 153.7 KB | PNG / RGB | ✅ |
| `content_border_08pct.png` | graphic | `product.image` | **process** | 1400×1400 · 1,96 MP | 2.50 MB | PNG / RGB | ✅ |
| `icc_srgb_embedded.jpg` | photo | `product.image` | **process** | 1600×1600 · 2,56 MP | 575.3 KB | JPEG / RGB | ✅ |
| `fmt_tiff_lzw.tif` | photo | `product.image` | **process** | 1500×1500 · 2,25 MP | 8.14 MB | TIFF / RGB | ✅ |

#### B) Kötücül fixture'lar (10)

| dosya | sınıf | slot | beklenen | ölçülen | bayt | biçim/mod | doğrulama |
|---|---|---|---|---|---:|---|---|
| `bomb_100mp.png` | malicious | `product.image` | **reject** | 10000×10000 · 100,00 MP | 94.9 KB | PNG / L | ✅ |
| `script_payload.svg` | malicious | `seller.logo` | **reject** | — | 555 B | PIL açamıyor | ✅ |
| `polyglot_pdf_as.jpg` | malicious | `product.image` | **reject** | — | 637 B | PIL açamıyor | ✅ |
| `polyglot_png_as.jpg` | malicious | `product.image` | **reject** | 256×256 · 0,07 MP | 1.4 KB | PNG / RGBA | ✅ |
| `empty_zero_byte.jpg` | malicious | `product.image` | **reject** | — | 0 B | PIL açamıyor | ✅ |
| `truncated.jpg` | malicious | `product.image` | **reject** | 1600×1200 · 1,92 MP | 241.3 KB | JPEG / RGB (load ✗) | ✅ |
| `fake_docx.docx` | malicious | `document.attachment` | **reject** | — | 369 B | PIL açamıyor | ✅ |
| `executable_as.png` | malicious | `user.avatar` | **reject** | — | 359 B | PIL açamıyor | ✅ |
| `data_uri_svg.txt` | malicious | `seller.logo` | **reject** | — | 179 B | PIL açamıyor | ✅ |
| `jpeg_with_html_tail.jpg` | malicious | `user.avatar` | **reject** | 320×320 · 0,10 MP | 14.4 KB | JPEG / RGB | ✅ |

#### C) Video fixture'lar (7)

| dosya | sınıf | slot | beklenen | ölçülen | bayt | biçim/mod | doğrulama |
|---|---|---|---|---|---:|---|---|
| `video_efficient_720p_750k.mp4` | video | `product.video` | **passthrough** | 1280×720 · 6 sn | 661.8 KB | h264 / ses var | ✅ |
| `video_bloated_720p_8m.mp4` | video | `product.video` | **process** | 1280×720 · 6 sn | 6.00 MB | h264 / ses var | ✅ |
| `video_silent_noaudio_720p.mp4` | video | `product.video` | **passthrough** | 1280×720 · 8 sn | 818.5 KB | h264 / ses yok | ✅ |
| `video_vertical_9x16.mp4` | video | `product.video` | **passthrough** | 720×1280 · 8 sn | 993.9 KB | h264 / ses var | ✅ |
| `video_long_540s_320x240.mp4` | video | `product.video` | **passthrough** | 320×240 · 540 sn | 3.81 MB | h264 / ses yok | ✅ |
| `video_square_352.mp4` | video | `product.video` | **passthrough** | 352×352 · 6 sn | 287.5 KB | h264 / ses yok | ✅ |
| `video_16x9_1080p.mp4` | video | `product.video` | **process** | 1920×1080 · 6 sn | 1.08 MB | h264 / ses yok | ✅ |

---

## 4. Korpusun ilk çıktısı: bugünkü motorun ölçülmüş davranışı

Fixture'lar üretilir üretilmez konteynerde **gerçek** `tradehub_core.media.pipeline`
ve `tradehub_core.media.transcode` kaynak dosyalarına uygulandı. Aşağıdakiler
tahmin değil, koşum sonucudur (`tests/fixtures/media/live-probe.json`).

### B-1 — 100 MP decompression bomb bugün HİÇ durdurulmuyor ⚠ EN YÜKSEK

| adım | sonuç |
|---|---|
| dosya | `bomb_100mp.png`, **97.221 bayt** (95 KB) |
| açılan piksel | **100.000.000** (100 MP ≈ 100 MB ham) |
| `engine.probe()` | `readable=True`, `fmt=PNG`, `supported=True` |
| `engine.optimize(max_dim=2000, quality=85)` | **`ok=True`**, çıktı 2000×2000, 3.982 bayt |
| süre | **314,8 ms** |
| Pillow `MAX_IMAGE_PIXELS` (konteyner) | 89.478.485 → yalnız `DecompressionBombWarning`, **istisna değil** |

95 KB'lık bir yükleme bugün sunucuda 100 MP açtırıyor ve **başarıyla işleniyor**.
Pillow'un kendi koruması bir *uyarı* basıyor, akışı kesmiyor. SRS **FR-011**'in
"YOK" işareti (`grep MAX_IMAGE_PIXELS tradehub_core/` → 0 sonuç) bu ölçümle
doğrulandı: koruma yalnız eksik değil, **kütüphane varsayılanı da yeterli değil**.
`accept.max_megapixels_hard` bir yerde okunup **hata fırlatmadıkça** bu açık kapalı sayılmaz.

### B-2 — `probe()` tek başına bir kabul kapısı değil

| dosya | `engine.probe()` | `engine.optimize()` |
|---|---|---|
| `truncated.jpg` (veri %40'ta kesik) | `readable=True`, 1600×1200 | **`ok=False`, `reason="error:OSError"`** |

Başlık sağlam olduğu için `probe()` dosyayı okunabilir sayıyor; bozukluk ancak
piksel çözülürken ortaya çıkıyor. `probe(readable=False)`'ı tek ret ölçütü yapan
bir tasarım bu dosyayı kabul eder ve hata kullanıcıya değil log'a düşer.
`content_rules.unreadable` kuralının hangi çağrıya bakacağı **açıkça yazılmalı**.

### B-3 — Uzantı/içerik uyuşmazlığı motor katmanında görünmez

| dosya | sonuç |
|---|---|
| `polyglot_png_as.jpg` (içerik geçerli PNG, ad `.jpg`) | `probe` PNG diyor, `optimize` **`ok=True`** |
| `polyglot_pdf_as.jpg` (içerik `%PDF-`) | `probe` `readable=False` → burada durur |

İkincisi motor tarafından zaten durduruluyor. Tehlikeli olan **birincisi**:
tamamen geçerli bir görsel, yanlış uzantıyla. Motor mutlu; Content-Type'ı
uzantıdan türeten her katman yanlış tip servis eder. Savunma L0'da,
**magic-byte ile** olmak zorunda (FR-009 bugün "KISMEN": uyuşmazlık L0'da
yalnız uyarı, sert kontrol yalnız `kyb.upload_kyb_document` içinde).

### B-4 — Aynı kullanıcı hatası, iki farklı ret kodu

| dosya | `optimize()` `reason` |
|---|---|
| `anim_webp.webp` | `animated` |
| `anim_6frames.gif` | `unsupported_format` |

Kullanıcı açısından ikisi de "hareketli görsel yükledim". Mesaj sözlüğünde
`animated` için yazılmış özenli metin (`product-image.json` → `messages.tr.animated`)
GIF yükleyen kullanıcıya **hiç ulaşmaz**; o `format_not_supported` görür.
FR-060'ın kodlu ret sözleşmesi bu iki yolu birleştirmeli.

### B-5 — Gövde sonuna iliştirilen yük yalnız optimize hattında temizleniyor

`jpeg_with_html_tail.jpg` (geçerli JPEG + `<script>` kuyruğu): `optimize()`
yeniden kodladığı için kuyruk düşüyor (14.760 B giriş → 15.561 B çıkış; çıktının
**büyümesi** yeniden kodlamanın kanıtı). Ama `presets.py`'deki muafiyet
listelerinden geçen dosyalar (belge doctype'ları, KYB) optimize edilmiyor —
onlarda kuyruk **olduğu gibi** diske yazılır. Savunma yeniden kodlamaya
bırakılamaz.

### B-6 — 9 dakikalık video sunucuya hiç uğramıyor

| dosya | genişlik | bitrate | `needs_transcode()` |
|---|---:|---:|---|
| `video_long_540s_320x240.mp4` (**540 sn**) | 320 | 59 kbps | **False** |
| `video_efficient_720p_750k.mp4` | 1280 | 797 kbps | False |
| `video_bloated_720p_8m.mp4` | 1280 | **8.249 kbps** | **True** |
| `video_16x9_1080p.mp4` | **1920** | 1.505 kbps | **True** |

Gerçek `transcode.needs_transcode()` koşuldu (`NEEDS_TRANSCODE_MAX_WIDTH=1280`,
`NEEDS_TRANSCODE_MAX_BITRATE=2.500.000`). İki kolun **bağımsız** çalıştığı
`video_bloated` (yalnız bitrate tetikler) ve `video_16x9_1080p` (yalnız genişlik
tetikler) çiftiyle kanıtlandı.

Asıl bulgu sonuncusu: canlıdaki **en uzun video (540 sn)** her iki eşiğin de
altında kaldığı için **hiç işlenmiyor**. `product-video.json` içinde **süre için
tek bir kural yok** — ne `accept`'te ne `require`'da. Dokümanın önerdiği 180 sn
tavanı hiçbir politika dosyasında yazılı değil. Bu boşluğun taşıyıcısı
`video_long_540s_320x240.mp4`'tür.

### B-7 — 72,71 MP bugünkü tavandan geçiyor

`edge_72mp.jpg` (8527×8527 = 72,71 MP) `accept.max_megapixels_hard = 80`'in
altında kaldığı için **kabul edilir**. Canlı ölçümdeki maksimum tam olarak bu
değerdi (08 §1.3). `optimize()` bu dosyayı **494,3 ms**'de işledi — yani tavan
düşürülmezse tek bir yükleme yarım saniye CPU yiyor. Fixture, tavan 80'den
aşağı çekildiğinde `expected_action`'ı `reject`'e dönecek şekilde işaretlendi;
politika değişikliğinin alarmı korpusun içinde duruyor.

---

## 5. Korpusun ortaya çıkardığı doküman çelişkileri

Bu üç madde fixture yazılırken çıktı; ikisi **kod değil, doküman** düzeltmesi gerektiriyor.

| # | Çelişki | Fixture | Ne yapılmalı |
|---|---|---|---|
| Ç-1 | **SRS FR-019** "logo slotlarında alfa **zorunlu**, alfası olmayan **reddedilir**" diyor. `seller-logo.json` ise `require.alpha_channel: "optional"`. Canlı ölçüm ikincisini haklı çıkardı: logoların **%50'si JPEG** (08 §2.1) ve K1 kararı ölçümle "kabul + uyarı"ya döndü. | `logo_jpeg_noalpha.jpg` | **FR-019 metni düzeltilmeli.** Bugünkü hâliyle uygulanırsa mevcut logoların yarısı reddedilir. |
| Ç-2 | `product-image.json` → `content_rules.entropy_bits` **`action: "reject"`**. `content_rules.json` → `decision_model.reject_allowed_rules` yalnız `nsfw_content` ve `extreme_blur`. İki politika aynı kural için farklı aksiyon yazıyor. | `content_blank_white.png` | Tek kaynağa indirilmeli. Eşik `UNCALIBRATED` olduğu için bugünkü doğru davranış **kabul + uyarı**. |
| Ç-3 | `logo_wordmark_2876.png` oranı 2,876 → band dışı → `reject`. Ama K2 kararı canlıdaki bu iki gerçek dosyayı "istisna olarak ele alınmalı" diye açık bıraktı; istisna mekanizması **hiçbir yerde tanımlı değil**. | `logo_wordmark_2876.png` | İstisna mekanizması yazılınca fixture'ın `expected_action`'ı güncellenmeli. |

---

## 6. Fixture ↔ kural eşlemesi

`kural` sütunu `docs/srs/SRS-v1.0.md` FR kodlarına ve slot politikasındaki alan
adlarına atıf yapar. `canlı karşılık` sütunu, fixture'ın hangi **ölçülmüş**
gerçeği temsil ettiğini gösterir (`—` = saf sentetik sınır vakası).


| dosya | zorladığı kural / FR | canlı karşılık |
|---|---|---|
| `p01_18mp_1mb.jpg` | `FR-011`, `FR-015`, `require.allowed_ratios` | 08-canli-olcum.md §1.3 — canlıda >20 MP 179 dosya |
| `dpi_3000x3000_300dpi.tif` | `FR-029`, `FR-030`, `master.dpi_out` | 08 §1.1 — canlıda 11 TIFF var |
| `mode_cmyk.jpg` | `master.colorspace=srgb` | 08 §1.1 — canlıda 38 CMYK dosya |
| `mode_rgba_alpha.png` | `accept.mime`, `master.format=webp` | 08 §1.3 — canlıda 597 alfa kanallı dosya |
| `mode_palette_p.png` | `master.colorspace=srgb` | 08 §1.1 — canlıda 74 paletli dosya |
| `mode_grayscale_l.png` | `master.colorspace=srgb` | 08 §1.1 — canlıda 7 gri tonlama dosya |
| `geom_strip_400x4000.png` | `FR-015`, `FR-016`, `require.min_short_edge` | — |
| `geom_1x1.png` | `FR-015`, `require.min_area` | — |
| `exif_orientation6.jpg` | `FR-016`, `master.orientation=apply_exif` | — |
| `exif_gps.jpg` | `FR-039`, `master.strip_metadata.gps` | — |
| `enc_progressive.jpg` | `accept.mime` | — |
| `anim_6frames.gif` | `FR-012`, `accept.mime`, `accept.allow_animated=false` | — |
| `anim_webp.webp` | `FR-012`, `accept.allow_animated=false` | — |
| `enc_webp_lossy.webp` | `quality.reencode_floor_saving_ratio` | 08 §1.1 — canlıda 384 WEBP dosya |
| `enc_webp_lossless.webp` | `FR-038`, `master.encoding=lossless` | — |
| `edge_short32.jpg` | `FR-015`, `FR-028`, `require.min_short_edge` | 08 §1.2 — kısa kenar min = 32 |
| `edge_short4480.jpg` | `FR-028`, `master.max_long_edge` | 08 §1.2 — kısa kenar p99 = 4.480 |
| `edge_72mp.jpg` | `FR-011`, `accept.max_megapixels_hard=80` | 08 §1.2/§1.3 — MP maksimum = 72,71 |
| `bound_short999.jpg` | `FR-015`, `require.min_short_edge=1000`, `require.min_area` | — |
| `bound_short1000.jpg` | `FR-015`, `require.min_short_edge=1000`, `require.min_area` | — |
| `ok_product_1x1_2400.jpg` | `master.max_long_edge=2400`, `FR-035` | — |
| `ok_product_4x5.jpg` | `FR-016`, `FR-037`, `profiles[].fit=pad` | — |
| `logo_alpha_512.png` | `FR-019`, `FR-020`, `require.recommended_edge=512` | — |
| `logo_jpeg_noalpha.jpg` | `FR-019`, `require.alpha_channel=optional`, `accept.format_priority` | 08 §2.1 — 18 gerçek logonun 9'u (%50) JPEG |
| `logo_wordmark_2876.png` | `FR-020`, `require.aspect_band` | 08 §2.1/§2.2 — band dışı 2 dosya, ikisi de oran 2,876 |
| `logo_short200.png` | `require.min_short_edge=256`, `on_violation.require=reject` | 08 §2.1 — kısa kenar aralığı 200–2.471; <256 olan 1/18 |
| `ok_cover_24x5.jpg` | `FR-016`, `FR-023`, `require.allowed_ratios=24:5` | — |
| `ok_banner_2x1.jpg` | `FR-016`, `FR-024`, `master.max_long_edge=2000` | — |
| `ok_avatar_96.png` | `FR-021`, `require.min_short_edge=96`, `master.min_long_edge` | — |
| `content_blank_white.png` | `content_rules.entropy_bits`, `FR-048`, `FR-057` | — |
| `content_border_40pct.png` | `content_rules.border_ratio`, `auto_fix` | — |
| `content_border_08pct.png` | `content_rules.border_ratio` | — |
| `icc_srgb_embedded.jpg` | `master.strip_metadata.icc=false` | — |
| `fmt_tiff_lzw.tif` | `accept.mime`, `engine.SUPPORTED_FORMATS` | 08 §1.1 — canlıda 11 TIFF |
| `bomb_100mp.png` | `FR-011`, `accept.max_megapixels_hard=80` | — |
| `script_payload.svg` | `FR-014`, `FR-119`, `accept.conditional_extensions` | — |
| `polyglot_pdf_as.jpg` | `FR-009`, `magic_byte_matches_extension` | — |
| `polyglot_png_as.jpg` | `FR-009`, `FR-008` | — |
| `empty_zero_byte.jpg` | `FR-009`, `unreadable` | — |
| `truncated.jpg` | `FR-009`, `content_rules.unreadable` | — |
| `fake_docx.docx` | `FR-010`, `content_rules.magic_byte` | — |
| `executable_as.png` | `FR-009`, `magic_byte_matches_extension` | — |
| `data_uri_svg.txt` | `FR-013`, `accept.allow_data_uri=false` | 08 §2 — DB'ye gömülü 18 data: URI logosu |
| `jpeg_with_html_tail.jpg` | `FR-009`, `content_rules` | — |
| `video_efficient_720p_750k.mp4` | `needs_transcode`, `NEEDS_TRANSCODE_MAX_BITRATE` | 08 §7 — bitrate p50 746 kbps |
| `video_bloated_720p_8m.mp4` | `needs_transcode`, `NEEDS_TRANSCODE_MAX_BITRATE=2500000`, `accept.max_bytes` | — |
| `video_silent_noaudio_720p.mp4` | `needs_transcode`, `video.renditions` | 08 §7 — ses içeren 4/23 |
| `video_vertical_9x16.mp4` | `FR-016`, `require.allowed_ratios=16:9`, `on_violation.require=warn` | 08 §7 — çözünürlük örneği 720×1280 |
| `video_long_540s_320x240.mp4` | `needs_transcode`, `require.min_area`, `SÜRE KURALI YOK` | 08 §7 — süre p90 = max = 540 sn |
| `video_square_352.mp4` | `require.min_short_edge=360`, `on_violation.require=warn` | 08 §7 — çözünürlük örneği 352×352 |
| `video_16x9_1080p.mp4` | `needs_transcode`, `NEEDS_TRANSCODE_MAX_WIDTH=1280`, `master.max_long_edge=1280` | 08 §7 — çözünürlük örneği 1920×1080 |

---

## 7. Canlı korpusla izlenebilirlik

Manifest'te **21 fixture** 08 no'lu canlı ölçüm raporundaki somut bir sayıya
bağlanmış (`canli_karsilik` alanı); bunların **20'si** `kaynak:
"canlı-veriden-türetilmiş"` olarak işaretli, kalan **31'i** `"sentetik"`.
Bu, korpusun "hayal edilmiş sınırlar" değil, **var olan içeriğin sınırları**
olmasını sağlar.

| canlı ölçüm (08-canli-olcum.md) | değer | temsil eden fixture |
|---|---:|---|
| Megapiksel MAKSİMUM | 72,71 MP | `edge_72mp.jpg` (8527×8527 = 72,71 MP) |
| Kısa kenar p99 | 4.480 | `edge_short4480.jpg` (4480×5600) |
| Kısa kenar minimum | 32 | `edge_short32.jpg` (32×48) |
| >20 MP dosya (P-01 tuzağı) | 179 adet | `p01_18mp_1mb.jpg` (17,92 MP / 1,02 MB) |
| CMYK | 38 adet | `mode_cmyk.jpg` |
| Alfa kanallı | 597 adet | `mode_rgba_alpha.png` |
| Paletli (P) | 74 adet | `mode_palette_p.png` |
| Gri tonlama (L) | 7 adet | `mode_grayscale_l.png` |
| TIFF | 11 adet | `fmt_tiff_lzw.tif`, `dpi_3000x3000_300dpi.tif` |
| WEBP | 384 adet | `enc_webp_lossy.webp` |
| Logo: JPEG payı | %50 (9/18) | `logo_jpeg_noalpha.jpg` |
| Logo: band dışı oran | 2,876 (2 dosya) | `logo_wordmark_2876.png` |
| Logo: kısa kenar minimum | 200 px | `logo_short200.png` |
| Logo: `data:` URI kaydı | 18 adet | `data_uri_svg.txt` |
| Video: süre maksimum | 540 sn | `video_long_540s_320x240.mp4` |
| Video: bitrate p50 | 746 kbps | `video_efficient_720p_750k.mp4` (797 kbps) |
| Video: sessiz oran | 19/23 | `video_silent_noaudio_720p.mp4` |
| Video: 9:16 örneği | 720×1280 | `video_vertical_9x16.mp4` |
| Video: en düşük çözünürlük | 352×352 | `video_square_352.mp4` |
| Video: 16:9 örneği | 1920×1080 | `video_16x9_1080p.mp4` |

Kalan fixture'lar **sentetik sınır vakalarıdır**: canlıda karşılığı yok ama
kuralın iki yakasını (`bound_short999` / `bound_short1000`) ya da bir saldırı
biçimini (`bomb_100mp.png`, `script_payload.svg`) temsil ederler.

### 7.1 Sınır çiftleri

Bir eşiğin `>` mi `>=` mi olduğu tek dosyayla ölçülemez. Korpusta dört çift var:

| kural | ALT yaka (ret) | ÜST yaka (kabul) |
|---|---|---|
| `require.min_short_edge = 1000` + `min_area = 1.000.000` | `bound_short999.jpg` (999×999 = 998.001) | `bound_short1000.jpg` (1000×1000 = 1.000.000 TAM) |
| `content_rules.border_ratio > 0,25` | `content_border_08pct.png` (%8 — tetiklenmemeli) | `content_border_40pct.png` (%40 — `auto_fix`) |
| `needs_transcode` bitrate kolu | `video_efficient_720p_750k.mp4` (797 kbps) | `video_bloated_720p_8m.mp4` (8.249 kbps) — **aynı kaynak içerik, aynı süre, aynı çözünürlük** |
| `needs_transcode` genişlik kolu | `video_efficient_720p_750k.mp4` (1280 — TAM eşikte, tetiklemez) | `video_16x9_1080p.mp4` (1920) |

Ayrıca `ok_cover_24x5.jpg` (2400×500 = 4,80) `company.cover_image`'ın **en geniş
kabul oranıyla tam eşit**, `ok_avatar_96.png` (96×96) `user.avatar`'ın kabul
tabanıyla tam eşit, `logo_alpha_512.png` (512×512) `low_resolution_warn_below`
ile tam eşit. Üçü de "sınırda kabul" davranışını ölçer.

### 7.2 Tek bir şeyi ayıran fixture'lar

Korpustaki en değerli iki dosya, **tek bir değişkende** ayrışanlardır:

- **`anim_webp.webp`** — WebP `accept.mime` listesinde **VAR**. Tek ihlal
  animasyon. Uzantı/MIME'a bakıp `is_animated` bayrağına bakmayan bir kapı bunu
  geçirir ve motor türev üretemez. `anim_6frames.gif` bu ayrımı yapamaz (GIF
  zaten listede yok).
- **`exif_orientation6.jpg`** — Saklanan 1200×1600 → oran 0,75 = **3:4, kabul
  bandında**. EXIF `orientation=6` uygulandıktan sonra 1600×1200 → oran 1,333,
  **bantta yok**. Oranı transpose **öncesi** ölçen uygulama bu dosyayı
  yanlışlıkla kabul eder. Fixture'ın tek ayırt edici özelliği kapı sırasıdır.

---

## 8. Bu korpusun KAPSAMADIKLARI

Dürüstlük gereği: aşağıdakiler **üretilmedi** ve Faz 1 bunlara güvenemez.

| eksik | neden | etkilediği FR |
|---|---|---|
| **Gerçek fotoğraf** | Tüm görseller sentetik (Pillow ilkelleriyle üretildi). Sentetik doku, gerçek fotoğrafın frekans dağılımını taşımaz. | **`content_rules` eşikleri bu korpusla KALİBRE EDİLEMEZ.** `entropy_bits`, `blur_laplacian_variance`, `target_ssim_per_class` gerçek üretim görselleri gerektirir (`scripts/calibrate_content_rules.py`). Korpus bu kuralların **çalıştığını** test eder, **eşiğini** değil. |
| **HEIC / AVIF** | Konteynerde `pillow-heif` ve `pillow-avif-plugin` yok; üretemedim. Yerelde Pillow AVIF desteği var ama konteynerde açılamayacağı için asimetrik fixture üretmek yanıltıcı olurdu. | `product-image.json` `open_questions[0]` — HEIC sessiz kayıp senaryosu **test edilemedi** |
| **Geçerli PDF ve geçerli DOCX** | `document.attachment` slotunun POZİTİF kontrolü yok; yalnız negatif (`fake_docx.docx`) var. | FR-010, FR-027, FR-045, FR-111 |
| **SVG sanitizer pozitif vakası** | Yalnız kötücül SVG var. "Temiz SVG kabul edilmeli" tarafı yok — çünkü FR-014 bugün SVG'yi **tümden** reddediyor; pozitif fixture ancak SVG-1…SVG-10 karşılandığında anlamlı olur. | FR-014, FR-119, FR-120 |
| **NSFW / moderasyon** | Üretilemez ve üretilmemeli. | FR-048, FR-051, FR-056 |
| **Kota / rate-limit** | Bunlar dosya değil **akış** fixture'larıdır (N dosya × M saniye); korpus dosya düzeyinde. | FR-070…FR-091 |
| **Gerçek EXIF çeşitliliği** | GPS ve orientation elle yazıldı; gerçek telefon EXIF'lerinde onlarca üretici etiketi ve Display P3 profili olur. | FR-039 kısmen; `master.colorspace` `open_questions[2]` **açık** |
| **Üretim paritesi** | Ölçümler yerel konteynerde. Üretim imajını Frappe Cloud kendi build ediyor. | Tüm ölçümler üretimde **doğrulanmadı** |

### 8.1 Ölçüm ortamı tutarsızlığı — bilinmeli

| | sürüm |
|---|---|
| Yerel Pillow (geometri ölçümleri, fixture üretimi) | **11.3.0** |
| Konteyner Pillow (`engine.*` ölçümleri) | **12.2.0** |

İki Pillow aynı değil. Fixture'lar 11.3.0 ile üretildi, motor davranışı 12.2.0
ile ölçüldü. Bugün bir sapma **gözlenmedi** (51 fixture'ın 51'inde geometri
ölçümleri iki tarafta da tutarlı) ama sürüm farkı kayıt altına alındı; ileride
bir fixture beklenmedik davranırsa ilk bakılacak yer burasıdır.

---

## 9. Yeniden üretim

```bash
# 1) Görseller + kötücül dosyalar (yerel, yalnız Pillow gerekir)
python3 scripts/gen_fixtures_images.py

# 2) Videolar (konteynerin ffmpeg'i)
docker cp scripts/gen_fixtures_video.sh istoc-dev-backend-1:/tmp/
docker exec istoc-dev-backend-1 sh /tmp/gen_fixtures_video.sh
docker cp istoc-dev-backend-1:/tmp/fixvid/. tests/fixtures/media/video/

# 3) Manifest üret + doğrula (uyuşmazlıkta çıkış kodu 1)
python3 scripts/build_fixture_manifest.py
```

Üretici deterministiktir: `random` modülü yerine sabit bir LCG kullanılır, bu
yüzden aynı Pillow sürümünde fixture'lar bit-bit aynı çıkar. Manifest her
fixture için **sha256** taşır; bir dosya sessizce değişirse hash tutmaz.

`scripts/` altındaki üç dosya bu görevin çıktısıdır ve `tradehub_core/`
altında **hiçbir dosya değiştirilmedi** (kural 1).

---

## 10. Faz 1'e devir

Korpus **hazır ve doğrulanmış**. Faz 1'in ilk işi bu korpusu bir test koşucusuna
bağlamaktır; manifest bunun için yeterli bilgiyi taşır (`slot`,
`expected_action`, `expect`, `kural`).

Öncelik sırası, korpusun kendi ölçümünden çıkıyor:

| # | iş | dayanak |
|---|---|---|
| 1 | `accept.max_megapixels_hard` kontrolünü **başlıktan okuyup istisna fırlatan** bir kapıya bağla | §4 B-1 — 95 KB'lık dosya bugün 100 MP açtırıyor ve **başarıyla işleniyor** |
| 2 | L0'a magic-byte **reddi** ekle (bugün yalnız uyarı) | §4 B-3 — `polyglot_png_as.jpg` motordan sorunsuz geçiyor |
| 3 | `probe()` yerine `probe() + decode denemesi` ikilisini kabul kapısı yap | §4 B-2 — `truncated.jpg` `probe`'u geçiyor |
| 4 | `product-video.json`'a **süre** kuralı ekle | §4 B-6 — 540 sn'lik video hiç işlenmiyor, politikada süre alanı yok |
| 5 | FR-019 metnini ölçüme göre düzelt | §5 Ç-1 — logoların %50'si JPEG |
| 6 | `entropy_bits` aksiyonunu iki politika arasında tekleştir | §5 Ç-2 |
| 7 | Gerçek fotoğraf korpusu topla (kalibrasyon için) | §8 — sentetik içerik eşik kalibre edemez |

> **Başarısız olduğum yer:** gerçek fotoğraf örneği içeren bir alt korpus
> üretemedim. Canlı `tabFile` içeriğinden örnekleme yapmak teknik olarak
> mümkündü ama o dosyalar gerçek satıcı/ürün verisidir; repoya kopyalanması
> KVKK ve ticari gizlilik açısından ayrı bir karar gerektirir ve bu görevin
> yetkisi dışındadır. `content_rules` eşiklerinin kalibrasyonu bu yüzden
> **açık kalmıştır** (§8 ilk satır).

---

## Güncel korpus eki — 2026-08-23

Yukarıdaki tarihsel açıklar W9 çalışmasında kapandı. Bugünkü manifest ölçümü:

| Sınıf | Adet |
|---|---:|
| Görsel (`images/`) | 36 |
| Video (`video/`) | 11 |
| Kötücül (`fixtures/malicious/`, ayrı dizin) | 10 |
| Toplam | **57** |
| Manifest doğrulaması | **57/57 GEÇTİ** |
| Toplam boyut | 94.879.477 B (90,48 MiB), 1 GiB sınırının altında |

Korpus artık dört gerçek DEV video, gerçek Canon fotoğraf ve Adobe RGB ICC'li
gerçek görsel taşır; sentetik sınır vakaları ayrıca korunur. Her kayıt SHA-256,
ölçülen metadata, kaynak sınıfı ve beklenen motor kararı taşır. Kötücül dosyalar
normal medya dizininin dışında tutulur ve yalnız test kapısında okunur.

Tek komutlu kapı:

```bash
python -m pytest -m fixtures tradehub_core/tests/test_faz0_closure.py -q
```

Pytest bulunmayan Frappe çalışma zamanında aynı test standard library ile de
koşar: `python -m unittest tradehub_core.tests.test_faz0_closure`.

2026-08-23 doğrulaması: kapanış kapısı unittest **11/11**, gerçek
`pytest -m fixtures` **11/11**, motor/manifest paritesi `test_policy_engine`
**38/38** ve kötücül kabul kapısı `test_media_security_gate` **18/18** geçti.
