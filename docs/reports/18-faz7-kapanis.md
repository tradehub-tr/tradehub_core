# T-075 — Faz 7 (Video Engine) kapanış raporu: video regresyonu ve kaynak bütçesi

**Görev:** T-075 · **Faz:** 7 · **Bağımlılık:** T-070…T-074 · **Tarih:** 2026-08-19
**Branch:** `ahmet` · **Ortam:** `istoc-dev-backend-1`, ffmpeg/ffprobe **5.1.9-0+deb12u1**
**Kaynak faz çıkış kriteri:** *"Fayda kapısı ihlali sıfır; VMAF hedefleri tutuyor"*
**Bu belge neyi kapatıyor:** `docs/reports/14-nihai-denetim.md:227` ve `:360` —
Faz 7'nin kapanış belgesinin yokluğu.

---

## 0. Bu belgenin kuralı

> **HİÇBİR SAYI KOŞULMADAN YAZILMADI. Ölçülemeyen ölçülemedi diye yazıldı.**

| İşaret | Anlamı |
|---|---|
| ✅ **KANITLI** | Kriter karşılandı **ve** kanıtı bu oturumda koşulmuş bir komuttur. Çıktısı aşağıda. |
| ⚠ **KISMEN** | Bir parçası ölçüldü, kalanı ölçülemedi. Hangi parça olduğu yazılı. |
| ❌ **KANIT YOK** | Ölçülemedi ya da ölçüm kriteri karşılamadı. Sebebi yazılı. |
| ⛔ **ARAÇ YOK** | Bu ortamda ölçmenin aracı yok. Eksik aracın adı yazılı. |

**Bu belge hiçbir kod dosyasını, politika JSON'unu ya da DocType'ı değiştirmedi.**
Tüm ölçümler konteynerin `/tmp` alanında geçici kopyalar üzerinde yapıldı; site
dosyalarına, veritabanına ve `tradehub_core/**` kaynak ağacına **yazılmadı**
(veritabanı yalnız `SELECT` ile okundu). Bayraklar 0 bırakıldı.

**Ölçülemeyen iki kalem baştan söyleniyor:**

1. **VMAF ölçülemedi.** Konteynerdeki ffmpeg `libvmaf` olmadan derlenmiş
   (§5.2'de doğrulaması var). Bu belgede **VMAF puanı yoktur** ve tahmini bir
   VMAF sayısı üretilmemiştir.
2. **Gerçek tarayıcı oynatması ölçülmedi.** HLS paketlemesi **gerçekten
   yapıldı ve gerçekten çözüldü** (§6), ama çözen ffmpeg'in HLS demuxer'ıdır,
   Safari/hls.js değildir. Aradaki fark §6.4'te yazılı.

---

## 1. Karne — Faz 7

| # | Kriter | Durum | Kanıt |
|---|---|---|---|
| K-1 | Karar tablosu 15 kural, hepsi tetiklenebilir | ✅ **KANITLI** | 58/58 test yeşil, `test_her_kural_en_az_bir_kez_tetiklendi` dahil (§2) |
| K-2 | Transcode H.264 High + AAC 128k + faststart üretiyor | ✅ **KANITLI** | 89/89 test yeşil; gerçek ffmpeg ile `test_cikti_gercekten_h264_high_aac`, `test_ciktida_moov_BASTA` (§2) |
| K-3 | **Fayda kapısı (INV-05) ihlali sıfır** | ✅ **KANITLI** | Canlı kütüphanenin 5 okunabilir videosunun **4'ünde** çıktı kaynaktan büyük çıktı ve **4'ünde de kapı çıktıyı attı, kaynağı korudu**. Tek bir bayt şişmesi diske yazılmadı (§5.3) |
| K-4 | Poster üretiliyor, parlaklık ve bayt kapısından geçiyor | ✅ **KANITLI** | 5/5 canlı dosyada üretildi; luma %13,9–%60,5 (kapı %6–%94), bayt 5.316–78.244 B (kapı 122.880 B), yeniden deneme 0 (§5.4) |
| K-5 | Önizleme klibi ≤ 1 MB, sessiz, 3-6 sn | ✅ **KANITLI** | 5/5 dosyada 6,0 sn / CRF 28 ilk basamakta tuttu; 40.992–328.061 B — hem 1 MB görev kapısı hem 400 KB politika hedefi (§5.4) |
| K-6 | HLS merdiveni gerçekten paketleniyor | ✅ **KANITLI** — **denetimin açığı kapandı** | 540 sn'lik gerçek dosyada 3 basamak, 405 segment, 27.301.407 B, master.m3u8 geçerli, segmentler mpegts/h264 (§6) |
| K-7 | HLS **gerçek oynatıcıda** oynuyor | ⚠ **KISMEN** | ffmpeg HLS demuxer master ve varyant playlist'i uçtan uca çözdü (rc 0). **Tarayıcı / hls.js denenmedi** (§6.4) |
| K-8 | **VMAF hedefleri tutuyor** | ⛔ **ARAÇ YOK** | `libvmaf` derlenmemiş — build config'de `--enable-libvmaf` **yok**, `-filters` yalnız `vmafmotion` listeliyor (VMAF puanı değil). Yerine SSIM/PSNR ölçüldü: 0,9900–0,9967 / 45,4–49,5 dB (§5.2) |
| K-9 | Kaynak bütçesi kütüphaneyle uyumlu | ⚠ **KISMEN** | Bütçe ölçüldü ve kütüphaneyle karşılaştırıldı (§4). **Motor tavanlarının ikisi de bugünkü kütüphanede ölü** ve H.264 hedefi kütüphanenin hiçbir dosyasında bayt kazandırmıyor (§4.3, B-1) |
| K-10 | K7 kota etkisi sayısallaştırıldı | ✅ **KANITLI** — **ama karar sayısı yanlış** | 6 nesnelik set 3 gerçek kapak videosunda ölçüldü: **2,85× – 4,56× bayt**, 6× **nesne**. Kararın "6 kat" ifadesi kotanın kapı ölçüsüyle uyuşmuyor (§7) |

### 1.1 Sonuç

> **FAZ 7 KAPANMIYOR.**

Kapanmamasının **tek** sebebi K-8'dir ve bu sebep bu oturumda değişmedi: fazın
kaynak dokümandaki çıkış kriteri iki bileşenli — *"fayda kapısı ihlali sıfır"*
**ve** *"VMAF hedefleri tutuyor"*. Birincisi bu oturumda **gerçek üretim
dosyalarında kanıtlandı**; ikincisinin ölçüm aracı bu ortamda **yok**.

Denetimin (`14-nihai-denetim.md:227`) saydığı üç gerekçeden **ikisi bu belgeyle
kapandı**:

| Denetimin gerekçesi | Bu belgeden sonra |
|---|---|
| Faz 7 kapanış belgesi (T-075) yok | ✅ **KAPANDI** — bu belge |
| HLS gerçek paketleme/oynatma ölçülmedi | ✅ **paketleme KAPANDI** (§6) / ⚠ tarayıcı oynatması açık |
| VMAF ölçülemedi (B6) | ❌ **AÇIK, DEĞİŞMEDİ** — araç yok |

Faz 7'nin denetimdeki durumu **❌ AÇIK** → **⚠ KISMEN** olarak güncellenmelidir.
"KANITLI" olması için gereken tek şey §9.1'de yazılı.

---

## 2. Test regresyonu — 147 test koşuldu

### 2.1 Koşum

```bash
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
    /home/frappe/frappe-bench/env/bin/python -m unittest \
    tradehub_core.tests.test_video_decision tradehub_core.tests.test_video_transcode
```

```
...............................................................................
...............................................................
----------------------------------------------------------------------
Ran 147 tests in 54.369s

OK
```

**147 test · 0 hata · 0 başarısız · 0 atlanan (skip).** Denetimdeki "147 test"
sayısı **birebir doğrulandı**.

> `OK` çıktısında `(skipped=…)` eki **yok**. Bu önemli: `test_video_transcode.py`
> başlığı gerçek-ffmpeg testlerinin ffmpeg olmayan makinede atlanacağını yazıyor.
> Konteynerde **hiçbiri atlanmadı**, yani 43 gerçek-ffmpeg testi de fiilen koştu.

### 2.2 Modül bazında

| Modül | Test | Süre | Sonuç |
|---|---:|---:|---|
| `tradehub_core/tests/test_video_decision.py` | **58** | 1,122 sn | ✅ OK |
| `tradehub_core/tests/test_video_transcode.py` | **89** | 46,855 sn | ✅ OK |
| **Toplam** | **147** | **54,369 sn** (birlikte) | ✅ **OK** |

### 2.3 Sınıf bazında — hangi görev neyi sınıyor

**`test_video_decision.py` — T-070 + T-071 (58)**

| Sınıf | Test | Ne sınıyor | ffmpeg |
|---|---:|---|---|
| `KuralTetikleme` | 22 | Tablodaki 15 kuralın her biri en az bir kez tetikleniyor; ölü kural avı | — |
| `TabloYuklemesi` | 11 | Bozuk tablo **yükleme anında** patlıyor (bilinmeyen değişken/operatör/aksiyon, tekrar eden id, boş liste) | — |
| `KunyeYardimcilari` | 11 | `probe()` hiçbir koşulda istisna atmıyor; bpp/kare hızı/moov taraması | — |
| `GercekFixtureOlcumu` | 7 | 7 fixture'ın künyesi ölçülenle aynı; 7/7'sinde moov başta | **✔** |
| `SiraOnemli` | 4 | REJECT > TRANSCODE > REMUX sıra önceliği | — |
| `CekirdekSafligi` | 2 | Modülde `frappe` importu yok | — |
| `YeniKuralKodDegismeden` | 1 | JSON'a kural eklemek `.py` değiştirmeden çalışıyor | — |

**`test_video_transcode.py` — T-072 + T-073 + T-074 (89)**

| Sınıf | Test | Ne sınıyor | ffmpeg |
|---|---:|---|---|
| `HlsMerdiveni` | 21 | Merdiven budama, büyütme yok, GOP hizası, capped-CRF, `%v` dizin tuzağı | — |
| `TranscodeKomutu` | 12 | H.264 High + AAC + faststart argümanları, `scale` tek tırnak, `-an`, `nice` | — |
| `GercekHls` | 11 | Gerçek paketleme, segment sayısı, playlist ayrıştırma | **✔** |
| `PosterPencereHesabi` | 10 | Poster penceresi, klip kısa-kenar bütçesi, iki katmanlı bayt kapısı | — |
| `GercekTranscode` | 9 | **INV-05 fayda kapısı**, çıktı kodeği, moov başta, VMAF yokluğu | **✔** |
| `GercekPoster` | 6 | Parlaklık kapısı, belirlenimcilik, ilk kare değil | **✔** |
| `GercekOnizlemeKlibi` | 6 | Sessiz klip, CRF merdiveni, bayt kapısı | **✔** |
| `SpecTablodanOkunuyor` | 4 | Spec'ler JSON'dan, koda gömülü değil | — |
| `KararUygulama` | 4 | PASSTHROUGH dokunmuyor, REJECT hata atmıyor, temp dosya aynı FS'te | — |
| `GercekRemux` | 4 | moov başa alınıyor, akışlar yeniden kodlanmıyor, kapıdan muaf | **✔** |
| `RemuxKomutu` | 2 | `-c copy` + `+faststart` | — |

**43 test gerçek ffmpeg çalıştırıyor** (`Gercek*` sınıfları), 104 test komut
sözleşmesini ffmpeg olmadan sınıyor.

### 2.4 Faz 7 DIŞI düşen testler — ayrıştırma

Aynı depoda video adı geçen iki modül daha var ve **ikisi de düştü**:

```bash
python -m unittest tradehub_core.tests.test_media_transcode \
                   tradehub_core.tests.test_media_transcode_retry
# Ran 0 tests in 0.003s
# FAILED (errors=15)
# frappe.exceptions.IncorrectSitePath: 404 Not Found: test_site does not exist
```

| Modül | Test | Sonuç | Kök neden | Faz 7 ile ilgili mi |
|---|---:|---|---|---|
| `test_media_transcode.py` | 22 | ⛔ yüklenemedi | `FrappeTestCase` → `test_site` gerekiyor; bu site kurulu değil | **HAYIR** |
| `test_media_transcode_retry.py` | 39 | ⛔ yüklenemedi | aynı | **HAYIR** |

**Ayrıştırma gerekçesi.** Bu iki modül **eski** hattı (`tradehub_core/media/transcode.py`
— VP9/WebM, `frappe.enqueue`, deneme sayacı) sınıyor. Faz 7 paketi o hatta
dokunmuyor; `video/__init__.py` başlığı bunu açıkça yazıyor
(*"SARMALANAN, YENİDEN YAZILMAYAN"*). Düşme nedeni **ortam** (Frappe test
sitesi yok), **kod kusuru değil**: 15 hatanın 15'i de `setUpClass` öncesinde,
`frappe.init()` aşamasında oluşuyor, tek bir test gövdesi çalışmadı. Bunlar
`bench --site <site> run-tests` ile koşulmalıdır; bu oturumda üretim sitesine
karşı test koşulmadı (paralel ajanlar aynı konteynerde çalışıyor).

**Faz 7 kapsamındaki 147 testin tamamı yeşildir. Faz 7 regresyonu YOKTUR.**

---

## 3. Canlı kütüphane ölçümünün teyidi

`docs/reports/08-canli-olcum.md` §7'nin sayıları **bugün yeniden ölçüldü**
(`ffprobe` ile, tek tek, gerçek dosyalar üzerinde).

### 3.1 Sayılar — **teyit edildi**

| Ölçüt | 08-canli-olcum §7 (2026-08-18) | **Bu ölçüm (2026-08-19)** | Durum |
|---|---|---|---|
| Codec | h264 (5/5) | **h264 (5/5)** | ✅ aynı |
| Ses içeren | 4/23 | **4/5 okunabilir** (= 4 dosya) | ✅ aynı dosya kümesi |
| Süre p50 | 33 sn | **32,995 sn** | ✅ aynı |
| Süre p90 / max | 540 sn (9 dk) | **540,0 sn** | ✅ aynı |
| Bitrate p50 | 746 kbps | **746,157 kbps** | ✅ aynı |
| Bitrate max | 1.169 kbps | **1.169,219 kbps** | ✅ aynı |
| Çözünürlükler | 720×1280, 720×720, 1280×720, 352×352, 1920×1080 | **birebir aynı beşi** | ✅ aynı |

**Kütüphane değişmemiş; 08'in ölçümü geçerlidir.**

### 3.2 Paydada fark — düzeltme

| Ölçü | 08-canli-olcum | Bu ölçüm | Fark |
|---|---:|---:|---|
| Video uzantılı `tabFile` satırı | **23** | **57** | sayım yöntemi |
| Tekil `file_url` | (verilmemiş) | **30** | — |
| Diskte var olan | (verilmemiş) | **30** | — |
| **ffprobe ile okunabilen** | **5** | **5** | ✅ aynı |

`scripts/media_stats.py:187` neden farklı olduğunu zaten yazıyor: kullandığı
`LIKE` deseni **4 baytlık karakter içeren satırlarda eşleşmiyor** — ve bu
kütüphanede emoji içeren dosya adları var
(`Evde taze sıkılmış … 🍹 … .mp4`). 23 sayısı **eksik sayımdır**; doğrusu
30 tekil URL / 57 satırdır.

Bu farkın Faz 7 sonuçlarına etkisi **yok**: fazladan gelen 25 dosyanın hepsi
**19–66 baytlık kırık kayıt** (`tabFile.file_size` p50 = 19 B uyarısı 08'de
zaten yazılı). ffprobe hiçbirinde video akışı bulamıyor; karar tablosu bunlara
`probe_unavailable` / `no_video_stream` → **REJECT** derdi.

### 3.3 Kapak videosu envanteri — hâlâ açık

`tabSeller Gallery Image`: **52 satır, `video_url` dolu olan yalnız 4**.
`company-cover-video.md` §11-D1'in sorusu (bu 23/30 videonun kaçı gerçekten
kapak videosu) bu ölçümle de kapanmıyor: 4 galeri satırı ile 5 okunabilir dosya
arasındaki eşleme yapılmadı. **D1 AÇIK kalıyor.**

---

## 4. Kaynak bütçesi — tavanlar ve gerçek kütüphane

### 4.1 Tavanlar nereden geliyor

| Tavan | Değer | Kaynak | Aksiyon |
|---|---|---|---|
| Çözünürlük üst sınırı | 3840×2160 | `video_decision.json` `resolution_over_max` | REJECT |
| Süre üst sınırı (motor) | 900 sn | `video_decision.json` `duration_over_engine_max` | REJECT |
| Genişlik tavanı | 1280 px | `width_over_cap` ← `media/transcode.py:98` | TRANSCODE |
| Bitrate tavanı | 2.500.000 bps | `bitrate_over_cap` ← `media/transcode.py:99` | TRANSCODE |
| Kare hızı tavanı | 30 fps | `fps_over_cap` ← `company-cover-video.json` | TRANSCODE |
| Verimlilik | bpp > 0,08 **VE** bitrate > 1,2 Mbps | `inefficient_encoding` | TRANSCODE |
| Ses bitrate | 192.000 bps | `audio_bitrate_over_cap` | TRANSCODE |
| Fayda kapısı | %10 (INV-05) | `targets.benefit_gate.min_saving_ratio` | çıktıyı at |
| ffprobe zaman aşımı | 20 sn | `contracts/video.py:42` | — |
| ffmpeg zaman aşımı | 1700 sn | `contracts/video.py:43` | — |
| **Slot** süre (kapak) | 6–60 sn | `slots/company-cover-video.json` | PolicyEngine |
| **Slot** süre (ürün) | 33 sn | `slots/product-video.json` | PolicyEngine |
| **Slot** bitrate | 2000 / 2500 kbps | slot JSON'ları | PolicyEngine |
| **Slot** çözünürlük tabanı (kapak) | 1280×720 | `slots/company-cover-video.json` | PolicyEngine |

### 4.2 Gerçek kütüphane bu tavanların neresinde

5 okunabilir dosyada karar tablosu **koşturuldu** (`decide()`):

| Dosya | Çözünürlük | Süre | Bayt | bpp | moov sonda | **Karar** | Kural | HLS gerekli |
|---|---|---:|---:|---:|---|---|---|---|
| `AQOOb74v…Rop ys.mp4` | 720×1280 | 33,0 sn | 3.077.433 | 0,0281 | hayır | **PASSTHROUGH** | (varsayılan) | hayır |
| `Evde taze sıkılmış…🍹….mp4` | 720×720 | 28,0 sn | 2.809.249 | 0,0455 | hayır | **PASSTHROUGH** | (varsayılan) | hayır |
| `9mb.mp4` | 1280×720 | **540,0 sn** | 9.622.535 | 0,0051 | **EVET** | **REMUX** | `moov_at_end` | **EVET** (540 > 60) |
| `AQPp_3LT…wRAd.mp4` | 352×352 | 28,9 sn | 1.085.963 | 0,0636 | hayır | **PASSTHROUGH** | (varsayılan) | hayır |
| `10 (1).mp4` | **1920×1080** | 58,2 sn | 8.504.902 | 0,0185 | **EVET** | **TRANSCODE** | `width_over_cap` | hayır |

**Dağılım: 3 PASSTHROUGH · 1 REMUX · 1 TRANSCODE · 0 REJECT.**

### 4.3 Tavan × kütüphane çapraz okuması

| Tavan | Kütüphanenin maksimumu | Kaç dosya aşıyor | Yorum |
|---|---|---:|---|
| 3840×2160 (REJECT) | 1920×1080 | **0** | **ölü kural** — JSON zaten öyle diyor |
| 900 sn (REJECT) | 540 sn | **0** | **ölü kural** — JSON zaten öyle diyor |
| 1280 px genişlik | 1920 px | **1** | tek TRANSCODE tetikleyicisi |
| 2,5 Mbps | 1,169 Mbps | **0** | 08'in *"bu eşik hiç tetiklenmiyor"* tespiti **teyit edildi** |
| 30 fps | 30,0 fps | **0** | — |
| bpp 0,08 **VE** 1,2 Mbps | bpp 0,0636 / 0,198 Mbps | **0** | iki koşullu kural doğru çalışıyor: en yüksek bpp'li dosya (352×352) mutlak tabana takılmadığı için **boşuna transcode edilmiyor** |
| 192 kbps ses | 98,3 kbps | **0** | — |
| **Slot** kapak süresi 6–60 sn | 540 sn | **1** (9× aşım) | K8 gereği **dokunulmuyor** |
| **Slot** ürün süresi 33 sn | 540 sn | **2** (540 sn, 58,2 sn) | K8 gereği **dokunulmuyor** |
| **Slot** kapak çözünürlük tabanı 1280×720 | — | **3** (720×1280, 720×720, 352×352) | K8 gereği **dokunulmuyor** |

**Sonuç:** motorun iki REJECT tavanı bugünkü kütüphanede **hiçbir dosyayı
vurmuyor** — bunlar gelecekteki yüklemeler için konmuş sınırlardır ve bu
belgede **ölçülmemiş** sayılmalıdır (tetiklenmedikleri için canlı doğrulamaları
yok; yalnız birim testleri var). Kütüphanenin gerçek darboğazı çözünürlük ve
süre **tabanı/tavanı**, bitrate değil.

---

## 5. Transcode yolu — gerçek dosyalarda uçtan uca koşum

5 canlı dosyanın **hepsi** `/tmp` altına kopyalandı ve boru hattı uçtan uca
koşturuldu: `probe → decide → apply_decision → make_poster → make_preview_clip → hls_required`.

### 5.1 Ana çıktı (master)

| Dosya | Aksiyon | Kaynak B | Çıktı B | Değişim | Duvar saati | Kabul |
|---|---|---:|---:|---:|---:|---|
| 720×1280 33 sn | PASSTHROUGH | 3.077.433 | — | dokunulmadı | 0,00 sn | ✅ |
| 720×720 28 sn | PASSTHROUGH | 2.809.249 | — | dokunulmadı | 0,00 sn | ✅ |
| 1280×720 540 sn | **REMUX** | 9.622.535 | 9.622.536 | **+1 B** | **0,07 sn** | ✅ (kapıdan muaf) |
| 352×352 29 sn | PASSTHROUGH | 1.085.963 | — | dokunulmadı | 0,00 sn | ✅ |
| **1920×1080 58 sn** | **TRANSCODE** | 8.504.902 | 14.490.432 | **+%70,4** | **15,17 sn** | ❌ **kapı ATTI, kaynak korundu** |

**Okunacak üç şey:**

1. **REMUX'un değeri sayıya döküldü.** 9,6 MB'lık, moov'u sonda olan bir dosya
   **0,07 saniyede** düzeltildi ve **1 bayt** büyüdü. Aynı dosyaya tam transcode
   uygulansaydı (aşağıdaki 15,17 sn / 58 sn oranıyla) ~140 saniye sürerdi.
   REMUX bugünkü hatta **hiç yok**; kazanç ~2000 kat CPU.
2. **INV-05 gerçek üretim dosyasında devreye girdi.** 1080p kaynak 1280'e
   indirildiği hâlde CRF 23 çıktısı kaynaktan **%70 büyük** çıktı. Kapı çıktıyı
   attı, kaynağı korudu. **Fayda kapısı ihlali sıfır** kriteri bu tek koşumla
   kanıtlanıyor — üstelik en zor durumda: kural TRANSCODE dedi, motor transcode
   etti, kapı sonucu reddetti.
3. **Ama ikinci mertebede bir sorun ortaya çıktı** — §8 B-2.

### 5.2 Kalite — VMAF yerine SSIM/PSNR

**VMAF neden ölçülemiyor (doğrulama):**

```bash
$ ffmpeg -hide_banner -filters | grep -c libvmaf
0
$ ffmpeg -hide_banner -version | tr ' ' '\n' | grep -c -- --enable-libvmaf
0
$ ffmpeg -hide_banner -filters | grep -iE 'ssim|psnr|vmaf'
 TS. psnr              VV->V      Calculate the PSNR between two video streams.
 TS. ssim              VV->V      Calculate the SSIM between two video streams.
 ... vmafmotion        V->V       Calculate the VMAF Motion score.
$ python -c 'from tradehub_core.media.pipeline.video import transcode as T; print(T.vmaf_available())'
False
```

> `vmafmotion` **VMAF değildir** — VMAF'ın yalnız hareket bileşenini hesaplar,
> kalite puanı üretmez. Bu filtre listede olduğu için "VMAF var" sanılabilir;
> **yok**.

**Ölçülebilen kalite** (`measure_quality`, referans çözünürlüğünde, çıktı
bikübik büyütülerek hizalanmış — yani hem yeniden kodlama hem küçültme kaybını
birlikte içerir):

| Kaynak | Çıktı bayt değişimi | **SSIM** | **PSNR** |
|---|---:|---:|---:|
| 720×1280 33 sn | **−%0,4** | **0,996714** | 49,485 dB |
| 720×720 28 sn | **+%17,6** | **0,992698** | 48,016 dB |
| 352×352 29 sn | **+%32,2** | **0,990044** | 45,351 dB |

Bu üç koşum **fayda kapısı kapatılarak** (`enforce_benefit_gate=False`)
yapıldı; amaç kalitenin ölçülmesiydi. Normal işletimde **üçü de kapıdan
düşerdi** (kazanç sırasıyla %0,4 / −%17,6 / −%32,2, hepsi %10 eşiğinin altında).

**Yorum:** SSIM ≥ 0,99 ve PSNR ≥ 45 dB, yeniden kodlamanın görsel olarak
neredeyse kayıpsız olduğunu gösterir. Ama **bu, "VMAF ≥ 93 tutuyor" demek
değildir.** SSIM ve VMAF farklı ölçeklerde farklı şeyleri ölçer; birinden
diğerine dönüşüm yapmak uydurma olur. **K-8 açık kalıyor.**

### 5.3 Fayda kapısı — canlı kütüphanedeki bilanço

| Dosya | Transcode edilse çıktı/kaynak | Kapı kararı |
|---|---:|---|
| 720×1280 33 sn | %99,6 | **AT** (kazanç %0,4 < %10) |
| 720×720 28 sn | %117,6 | **AT** (bayt şişmesi) |
| 352×352 29 sn | %132,2 | **AT** (bayt şişmesi) |
| 1920×1080 58 sn | %170,4 | **AT** (bayt şişmesi) |
| 1280×720 540 sn | (REMUX — kapıdan muaf) | — |

**Ölçülen 4 transcode adayının 4'ünde de çıktı kaynaktan büyük ya da eşdeğer.
Kapı 4/4 doğru karar verdi. Diske tek bayt şişmesi yazılmadı.**

Bu, "fayda kapısı ihlali sıfır" kriterinin **kanıtıdır** ve aynı zamanda §8
B-1'in kaynağıdır: bugünkü hedef ayarları bu kütüphaneye göre fazla cömert.

### 5.4 Poster ve önizleme klibi

| Dosya | Poster B | Zaman damgası | Luma % | Kalite | Deneme | Klip B | Klip sn | CRF |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 720×1280 33 sn | 18.528 | 3,320 sn | **13,88** | 78 | 1 | 168.473 | 6,0 | 28 |
| 720×720 28 sn | 16.912 | 1,233 sn | 54,29 | 78 | 1 | 139.778 | 6,0 | 28 |
| 1280×720 540 sn | 9.194 | 4,000 sn | 49,64 | 78 | 1 | 40.992 | 6,0 | 28 |
| 352×352 29 sn | 5.670 | 3,191 sn | 57,70 | 78 | 1 | 154.083 | 6,0 | 28 |
| 1920×1080 58 sn | 78.244 | 2,469 sn | 60,50 | 78 | 1 | 328.061 | 6,0 | 28 |

- **Poster: 5/5 üretildi.** Bayt kapısı 122.880 B — en büyüğü 78.244 B, **hepsi
  geçti**. Kalite merdiveninin ilk basamağı (78) hiç düşmedi.
- **Parlaklık kapısı 5/5 geçti**, yeniden deneme **hiç gerekmedi**. Ama ilk
  dosya **%13,88** ile %6 tabanına yakın — §8 B-4.
- **Klip: 5/5 üretildi.** Hepsi **6,0 sn** (merdivenin en uzun basamağı) ve
  **CRF 28** (en yüksek kalite basamağı) ile tuttu; süre ya da kalite düşürmek
  hiç gerekmedi. **1 MB görev kapısı ve 400 KB politika hedefi 5/5 sağlandı**
  (en büyüğü 328.061 B).
- Zaman damgaları **hiçbirinde 0,0 değil** — "ilk kare" tuzağı gerçek
  dosyalarda da atlanıyor.

### 5.5 CPU bütçesi

| İş | Kaynak | Duvar saati | Oran |
|---|---|---:|---:|
| `probe` | her dosya | 0,047 – 0,115 sn | — |
| REMUX | 9,6 MB / 540 sn | **0,07 sn** | ~7700× gerçek zaman |
| TRANSCODE | 1920×1080 / 58,2 sn | **15,17 sn** | **0,26×** gerçek zaman |
| Poster | her dosya | 0,15 – 0,73 sn | — |
| Önizleme klibi | her dosya | 0,29 – 1,06 sn | — |
| **HLS (3 basamak)** | 1280×720 / 540 sn | **295,78 sn** | **0,55×** gerçek zaman |

ffmpeg zaman aşımı **1700 sn**. En ağır ölçülen iş 295,78 sn — tavanın **%17'si**.
Motorun süre tavanı olan 900 sn'lik bir kaynak, aynı oranla (0,55×) ~493 sn
sürerdi; **yine tavanın altında**. Ancak bu bir **doğrusal projeksiyon**, ölçüm
değil: 1080p kaynakta 4 basamaklı bir merdiven daha pahalıdır ve **ölçülmedi**
(§8 B-5).

---

## 6. HLS — gerçek paketleme ve çözme

> Bu bölüm denetimin *"HLS gerçek paketleme/oynatma ölçülmedi"* açığını
> kapatıyor.

Kaynak: `9mb.mp4` — canlı kütüphanenin **gerçek** dosyası, 1280×720, **540 sn**,
9.622.535 B, moov sonda. Önce karar tablosunun dediği gibi **REMUX** edildi
(0,396 sn), sonra HLS paketlendi.

### 6.1 Merdiven seçimi

```
LADDER [('360p', (640, 360)), ('480p', (854, 480)), ('720p', (1280, 720))]
```

**1080p basamağı üretilmedi** — kaynak 720p, `no_upscale` kuralı doğru çalıştı.
`hls_required` = **True**, gerekçe: `sure 540.0 sn > 60 sn`.

### 6.2 Üretilen paket

| Basamak | Çözünürlük | Segment | Bayt | Hedef süre | Efektif bitrate |
|---|---|---:|---:|---:|---:|
| 360p | 640×360 | 135 | 7.299.637 | 4,0 sn | 108 kbps |
| 480p | 854×480 | 135 | 7.905.561 | 4,0 sn | 117 kbps |
| 720p | 1280×720 | 135 | 12.095.893 | 4,0 sn | 179 kbps |
| **Toplam** | — | **405** | **27.301.091** | — | — |

Diskte gerçekten sayılan: **409 dosya** (405 `.ts` + 3 varyant playlist +
1 master), **27.301.407 B**. Duvar saati **295,78 sn**, **tek ffmpeg koşumu**
(`split` filtresi ile kaynak bir kez çözülüyor).

**Kaynağa oran: 2,84×.**

> **capped-CRF düzeltmesi doğrulandı.** `video_decision.json`'un
> `rate_control_why` bölümü, sabit bitrate ile merdivenin 540 sn'lik fixture'da
> **4,5 kat** şiştiğini yazıyor (3.986.750 B → 17.833.465 B). Bu koşumda kaynak
> 140 kbps ve **en düşük basamak 108 kbps** çıktı — yani sabit bitrate'in
> "hedefi doldurma" davranışı ortadan kalkmış. En yüksek basamak bile kaynağın
> yalnız 1,26 katı. **Düzeltme çalışıyor.**

### 6.3 Playlist ve segment geçerliliği

`master.m3u8` (aynen):

```
#EXTM3U
#EXT-X-VERSION:6
#EXT-X-STREAM-INF:BANDWIDTH=941600,RESOLUTION=640x360,CODECS="avc1.64001e"
v360p/playlist.m3u8

#EXT-X-STREAM-INF:BANDWIDTH=1647800,RESOLUTION=854x480,CODECS="avc1.64001f"
v480p/playlist.m3u8

#EXT-X-STREAM-INF:BANDWIDTH=3295600,RESOLUTION=1280x720,CODECS="avc1.64001f"
v720p/playlist.m3u8
```

- Dizin adları **`v360p/` — indisle değil adla** (`%v` tuzağı: `name:360p`
  verilince ffmpeg `v0/` üretirdi). Test bunu sınıyor, gerçek koşum doğruladı.
- `CODECS` etiketleri gerçek: `avc1.64001e` = H.264 High Level 3.0,
  `avc1.64001f` = High Level 3.1. Uydurma değil, ffmpeg yazdı.
- `parse_master()` üç varyantı da ayrıştırdı; `playlist_stats()` üçünde de
  135 segment / 4,0 sn hedef süre okudu — **motorun kendi ayrıştırıcısı kendi
  çıktısını okuyabiliyor**.
- İlk segment `ffprobe` ile: `format_name=mpegts`, `codec_name=h264`,
  `640×360`, `duration=4.000000` — **`segment_duration_s: 4` politikası
  birebir tutuyor**.

### 6.4 Çözülebilirlik — üç bağımsız koşum

| Test | Komut | Sonuç | Süre |
|---|---|---|---:|
| 135 segmentin tamamı, concat ile | `ffmpeg -f concat -i … -f null -` | **rc 0**, stderr boş | 13,57 sn |
| Varyant playlist (HLS demuxer) | `ffmpeg -i v360p/playlist.m3u8 -f null -` | **rc 0**, stderr boş | 6,93 sn |
| **Master playlist** (HLS demuxer) | `ffmpeg -i master.m3u8 -f null -` | **rc 0**, stderr boş | 16,44 sn |

**Paket bütün, segmentler kesintisiz, playlist'ler bir HLS istemcisi
tarafından uçtan uca çözülebiliyor.**

> **Neyin ölçülmediği.** Bunu çözen ffmpeg'in HLS demuxer'ıdır. Safari'nin
> yerleşik HLS oynatıcısı ve hls.js **denenmedi** — bu ortamda tarayıcı yok ve
> `hls` dizesi storefront/admin-panel kaynağında hâlâ **0 eşleşme** veriyor
> (`video_decision.json` `hls.current_state: "yok"`). Demuxer testi güçlü bir
> vekildir (aynı standardı, aynı segmentleri okur) ama **ABR basamak geçişi,
> arama (seek), canlı buffer davranışı ölçülmedi**. K-7 bu yüzden ⚠ KISMEN.

---

## 7. K7 kararının kaynak bütçesine etkisi — sayısallaştırma

`docs/standards/company-cover-video.md` §10.9 **K7**: *"Rendition'lar medya
kotasından **SAYILSIN**"* — belgedeki öneriden **ayrılan** karar. Belgenin
gerekçesi: kapak videosu **6 nesne** üretiyor, satıcılar kotalarını
**~6 kat hızlı** doldurur.

### 7.1 6 nesnelik set — GERÇEKTEN ÖLÇÜLDÜ

3 gerçek, kapak boyutundaki canlı video (28–33 sn) için §6.5'in tarif ettiği
set üretildi ve tartıldı:

| Nesne | 720×1280 · 33 sn | 720×720 · 28 sn | 352×352 · 29 sn | Motor üretiyor mu |
|---|---:|---:|---:|---|
| kaynak | 3.077.433 | 2.809.249 | 1.085.963 | — |
| `cover_720.mp4` | 3.064.379 | 3.302.593 | 1.435.718 | ✅ **evet** (`H264Spec`) |
| `cover_720.webm` | 2.595.078 | 2.262.001 | 1.207.623 | ❌ hayır (`webm_fallback.implemented: false`) |
| `cover_480.mp4` | 1.543.763 | 1.783.006 | 1.174.013 | ❌ hayır |
| `cover_480.webm` | 1.397.488 | 1.294.230 | 977.973 | ❌ hayır |
| `cover_poster.webp` | 17.820 | 16.684 | 5.316 | ✅ **evet** |
| `cover_clip.mp4` | 165.566 | 137.038 | 150.480 | ✅ **evet** |
| **6 nesne toplam** | **8.784.094** | **8.795.552** | **4.951.123** | — |
| **kaynağa oran** | **2,85×** | **3,13×** | **4,56×** | — |
| bugün üretilen 3 nesne | 3.247.765 | 3.456.315 | 1.591.514 | — |
| bugün üretilenin oranı | **1,06×** | **1,23×** | **1,47×** | — |

**Ölçüm dürüstlüğü notu.** `cover_720.mp4`, poster ve klip **motorun kendi
kodu** ile üretildi. Diğer üçü motor tarafından **üretilmiyor**; onlar için
bugünkü hattın ayarları (`media/transcode.py:349-361` — libvpx-vp9, CRF 32,
libopus) ve motorun kendi kısa-kenar ölçek filtresi
(`poster.preview_scale_filter`, büyütme yapmaz) ile **elle ffmpeg komutu
kuruldu**. Bu üç satır bir **projeksiyon ölçümüdür**, motorun davranışı değil.
`cover_720.mp4` fayda kapısı kapatılarak üretildi; normal işletimde 3 dosyanın
2'sinde kapı çıktıyı atardı (§5.3).

### 7.2 "6 kat" doğru mu — HAYIR, kotanın kapısı BAYT

`tradehub_core/entitlement/checks.py` kotayı **bayt** üzerinden zorluyor:

```python
incoming_bytes = int(doc.get("file_size") or len(doc.get("content") or b"") or 0)
current_bytes  = files.storage_usage(store)["bytes"]
if current_bytes + incoming_bytes > limit_bytes:
    upload_policy.reddet(upload_policy.QUOTA_EXCEEDED, …)
```

`media/files.py:267 storage_usage()` **bayt** topluyor (`file_url`'e göre
tekilleştirilmiş `max(file_size)`); `files` sayısını da döndürüyor ama
**karşılaştırma yalnız baytla yapılıyor**.

| Ölçü | K7 kararının dediği | **Ölçülen** |
|---|---|---|
| Nesne sayısı (`File` kaydı) | 6× | **6×** ✅ |
| **Kotanın gerçekten baktığı: BAYT** | (ima: ~6×) | **2,85× – 4,56×**, medyan **3,13×** |
| §6.5 tipik 30 sn depolama tahmini | ≈ 19 MB | **4,95 – 8,80 MB** |

**İki düzeltme:**

1. **Kota etkisi ~6 kat değil, ~3 kat.** Nesne sayısı 6'ya çıkıyor ama
   rendition'ların büyük kısmı küçültülmüş (480p) ya da daha verimli kodekli
   (VP9); toplam bayt kaynağın **~3 katı**. K7'nin uygulama görevi kota
   yeniden boyutlandırmasını **3× üzerinden** yapmalı; 6× ile boyutlandırmak
   kotayı gereğinden fazla gevşetir.
2. **§6.5'in "≈19 MB tipik" tahmini 2–4 kat yüksek.** Gerçek 30 sn kapak
   videolarında ölçülen 4,95–8,80 MB. Tahminin "6+7+2,6+3+0,12+0,4" kırılımı
   kaynak videonun 1080p/yüksek bitrate olduğunu varsayıyor; bu kütüphanede
   kaynaklar 0,2–0,8 Mbps.

### 7.3 K7'nin ölçülmemiş üçüncü kenarı — HLS

§6.5'in "6 nesne" modeli **HLS'i hiç saymıyor**. Ölçülen tek HLS gerekli dosya:

| | Master tek başına | **HLS eklenince** |
|---|---:|---:|
| Nesne sayısı | 1 | **409** |
| Bayt | 9.622.536 | **+27.301.407** (toplam 36.923.943) |

`rendition_policy.object_count_per_cover = 6` bu dosya için **68 kat** yanlış.
Kapak videosunun süre tavanı 60 sn olduğu için kapak slotunda HLS **normalde
tetiklenmez** (`required_if_any.duration_s_gt: 60`) — ama `9mb.mp4` gibi
mevcut 540 sn'lik bir dosya slot eşlemesi yapıldığında tetikler, ve ürün
videosu tarafında (`product-video.json`) böyle bir güvence yok.
**K7 kararı HLS segmentlerinin kotadan sayılıp sayılmayacağını söylemiyor.**

### 7.4 K7 bugün UYGULANMIYOR

Faz 7 paketi **hiçbir `File` kaydı oluşturmuyor**: `video/` altındaki beş
modülün hiçbiri `frappe` import etmiyor (`test_video_decision.py::CekirdekSafligi`
bunu test ediyor). Rendition'lar bugün diske de yazılmıyor —
`transcode.py` tek bir hedef dosya üretiyor. **K7 kararı vardır, uygulaması
yoktur.** Kararın uygulanabilmesi için önce §6.5'in çok-rendition manifesti
yazılmalıdır (Faz 7 kapsamı dışında).

Ayrıca `storage_usage()` yalnız `owner in users_of(store)`, `is_private=0`,
`left(file_url,7)='/files/'` koşullarını sayıyor. Rendition'lar sistem
kullanıcısıyla ya da özel yola yazılırsa **kotadan hiç sayılmaz** — K7 sessizce
etkisiz kalır. Uygulama görevinde bu koşullar açıkça karşılanmalı.

### 7.5 K8 — kapsam teyidi

**K8:** *"Kural yalnız yeni yüklemelere; mevcut kapaklara dokunulmaz."*

Ölçüm bu kararın kapsamını **doğruluyor**: 5 okunabilir canlı videonun
**3'ü** kapak çözünürlük tabanının (1280×720) altında ve **1'i** 540 sn ile
60 sn tavanının 9 katı (§4.3). K8 olmasaydı bu içeriğin **%80'i** yeni kurala
takılırdı.

**K8'in ikinci sonucu (belgede yazmıyor):** mevcut içeriğe dokunulmadığı için
**Faz 7 kuralları üretim verisinde hiç çalışmayacak**. Kuralların canlı kanıtı
ancak yeni yüklemeler biriktikçe oluşur; bugün elde olan tek kanıt bu belgedeki
sentetik koşumlardır. Kapanış sonrası izleme (§9.2) bu yüzden gerekli.

---

## 8. Açık bulgular

| # | Bulgu | Şiddet | Kanıt | Faz 7'yi bloklar mı |
|---|---|---|---|---|
| **B-1** | **H.264 hedefi bugünkü kütüphanede hiç kazanmıyor.** CRF 23 / preset medium, 4 gerçek dosyanın 4'ünde de kaynaktan büyük çıktı üretti (%+0,4 … %+70,4). Kütüphane zaten düşük bitrate'li (p50 746 kbps); hedef kalite kaynağın kalitesinin üstünde. | **YÜKSEK** | §5.2, §5.3 | Hayır — kapı doğru davranıyor. Ama `width_over_cap` kuralının amacı hiç gerçekleşmiyor |
| **B-2** | **Kapıdan düşen TRANSCODE, aynı dosyanın REMUX ihtiyacını da öldürüyor.** `10 (1).mp4` hem `width_over_cap` hem `moov_at_end` sorununa sahip. Sıra gereği TRANSCODE kazanıyor, çıktı kapıdan düşüyor, kaynak korunuyor — ve **moov sonda kalıyor**. Motorda "kapı düştü → REMUX'a geri çekil" yolu yok (`transcode.py:363-372`). | **YÜKSEK** | §4.2, §5.1 | Hayır — ama teslim kalitesini doğrudan bozuyor (aşamalı indirmede ilk kare gecikmesi) |
| **B-3** | **`video_decision.json` `status: "draft"`.** Karar tablosu hâlâ taslak; onay bloğu yok. | ORTA | `policy/video_decision.json:4` | Kısmen — "onaylı" imzası yok |
| **B-4** | **Poster parlaklık kapısı tabanına yakın geçiş.** `AQOOb74v….mp4` posteri luma **%13,88**; kapı tabanı %6. Kütüphanenin 1/5'i tabanın 2,3 katı içinde. Daha karanlık bir kapak videosu ikinci pencereye, sonra `video_poster_unresolved`'a düşebilir; bu senaryo **gerçek dosyada ölçülmedi**. | DÜŞÜK | §5.4 | Hayır |
| **B-5** | **En kötü hâl HLS koşumu ölçülmedi.** Ölçülen: 720p / 540 sn / 3 basamak = 295,78 sn. Motorun tavanı 900 sn ve 1080p kaynakta merdiven 4 basamak olur. 1700 sn ffmpeg tavanına ve 1800 sn kuyruk tavanına karşı **hiç ölçülmedi**; projeksiyon ~493 sn (doğrusal, kanıt değil). | ORTA | §5.5, §6.2 | Hayır |
| **B-6** | **VMAF ölçülemedi.** ffmpeg `libvmaf` olmadan derlenmiş. Denetimin B6'sı **değişmedi**. | **YÜKSEK** | §5.2 | ✅ **EVET — tek bloklayıcı** |
| **B-7** | **Gerçek oynatıcıda oynatma ölçülmedi.** ffmpeg demuxer çözdü; Safari/hls.js denenmedi, storefront'ta HLS kodu yok. | ORTA | §6.4 | Hayır (K-7 kısmen) |
| **B-8** | **H.264 ↔ VP9 çelişkisi açık.** `14-nihai-denetim.md` §7.1'in tespiti bu oturumda **değişmedi**: Faz 7 H.264/MP4 üretiyor, `contracts/video.py:175-176` VP9/WebM donduruyor, `delivery/manifest.py:67` WebM'i birincil sunuyor. | **YÜKSEK** | 14-nihai-denetim §7.1 | Faz 7'yi tek başına bloklamıyor ama uçtan uca teslimi bloklar |
| **B-9** | **§6.5'in depolama tahmini ve K7'nin "6 kat"ı ölçümle uyuşmuyor.** Tahmin ≈19 MB, ölçüm 4,95–8,80 MB; "6 kat kota" nesne sayısıdır, kotanın baktığı bayt çarpanı ~3. | ORTA | §7.1, §7.2 | Hayır — ama K7'nin bağlı görevini yanlış boyutlandırır |
| **B-10** | **`media_stats.py` video sayımı eksik.** `LIKE` deseni 4 baytlık karakterli (emoji) dosya adlarını atlıyor: 23 yerine 30 tekil URL / 57 satır. | DÜŞÜK | §3.2 | Hayır |
| **B-11** | **Kapak videosu envanteri (D1) hâlâ açık.** 52 galeri satırının yalnız 4'ünde `video_url` dolu; bu 4'ün 5 okunabilir dosyayla eşlemesi yapılmadı. | ORTA | §3.3 | Hayır |

---

## 9. Kapanış için ne gerekiyor

### 9.1 Faz 7'yi ✅ KANITLI yapmak için gereken TEK şey

**B-6 — VMAF ölçüm aracı.** Üç yoldan biri:

| Yol | Ne gerektirir | Maliyet |
|---|---|---|
| **A** — konteyner imajına `libvmaf`'lı ffmpeg | `docker/backend.Dockerfile` içinde `--enable-libvmaf` ile derleme ya da libvmaf içeren bir paket kaynağı | imaj rebuild; **üretim imajını Frappe Cloud build ettiği için parite ayrı iş** |
| **B** — ayrı VMAF aracı | Netflix `vmaf` CLI'ını yalnız ölçüm için kurmak; motor kodu değişmez (`measure_quality` zaten `vmaf_available()` ile dallanıyor) | en ucuz; ölçüm CI'a bağlanmaz |
| **C** — kriteri değiştirmek | Faz çıkış kriterini SSIM/PSNR eşiğine çevirmek — **karar gerektirir, teknik iş değil** | imza gerektirir |

Yol A ya da B seçilirse: `measure_quality` **hiç değiştirilmeden** VMAF
döndürmeye başlar (`transcode.py:502-516`), `test_kalite_olculebiliyor_ama_VMAF_YOK`
testinin adı ve gövdesi güncellenir, bu belgenin §5.2'si VMAF sayısıyla
yeniden yazılır.

### 9.2 Kapanış öncesi kapatılması önerilen küme

1. **B-1 + B-2 birlikte** — hedef CRF'i kütüphaneye göre yeniden ayarlamak
   (ya da kaynağın bpp'sine göre uyarlamalı CRF) **ve** kapıdan düşen
   TRANSCODE'un REMUX'a geri çekilmesi. İkisi de `video_decision.json`
   üzerinden çözülebilir; `.py` değişikliği yalnız ikincisi için gerekir.
2. **B-8** — H.264/VP9 kararı verilmeli. Faz 7 kapansa bile bu çelişki
   çözülmeden uçtan uca teslim çalışmaz.
3. **B-3** — `video_decision.json` `status` alanı `draft` → `approved`.
4. **B-5** — 900 sn / 1080p / 4 basamak HLS koşumu ölçülmeli; zaman aşımı
   merdiveninin (1700 < 1800 < 2700) hâlâ geçerli olduğu doğrulanmalı.

### 9.3 Faz 7 dışına düşen, ama bu ölçümün ürettiği görevler

- **K7 uygulama görevi** ~3× bayt çarpanı üzerinden boyutlandırılmalı (§7.2),
  ve HLS segmentlerinin kotadan sayılıp sayılmayacağı **karara bağlanmalı** (§7.3).
- `docs/standards/kota.md` K7'ye göre güncellenmeli (§10.9'un bağlı görevi).
- **B-10** `scripts/media_stats.py` sayım deseni düzeltilmeli.
- **B-11** D1 envanteri (galeri satırı ↔ dosya eşlemesi) koşulmalı.

---

## 10. Yeniden üretme

Tüm komutlar **salt okuma**dır; site dosyalarına ve veritabanına yazmaz.
Geçici çıktılar konteynerin `/tmp` alanına üretilir ve sonunda silinir.

```bash
# ── 1. 147 test (§2)
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -m unittest \
  tradehub_core.tests.test_video_decision tradehub_core.tests.test_video_transcode -v

# ── 2. VMAF yokluğunun doğrulaması (§5.2)
docker exec istoc-dev-backend-1 bash -lc \
  'ffmpeg -hide_banner -filters | grep -c libvmaf ; \
   ffmpeg -hide_banner -version | tr " " "\n" | grep -c -- --enable-libvmaf ; \
   ffmpeg -hide_banner -filters | grep -iE "ssim|psnr|vmaf"'

# ── 3. Karar tablosunun canlı kütüphanedeki dağılımı (§4.2)
#    (5 okunabilir dosya için probe + decide + hls_required)
docker exec istoc-dev-backend-1 /home/frappe/frappe-bench/env/bin/python - <<'PY'
import os, sys
sys.path.insert(0, "/home/frappe/frappe-bench/apps/tradehub_core")
from tradehub_core.media.pipeline.video import probe as P, decision as D, hls as H
SRC = "/home/frappe/frappe-bench/sites/istoc.localhost/public/files"
for a in sorted(os.listdir(SRC)):
    if not a.lower().endswith((".mp4", ".mov", ".webm", ".mkv")):
        continue
    p = os.path.join(SRC, a)
    f = P.probe(p)
    if not f.measured or not f.has_video:
        continue
    d = D.decide(f)
    r = H.hls_required(f, rendition_bytes=os.path.getsize(p))
    print("%-30s %4dx%-4d %7.1fsn bpp=%.4f moovEnd=%-5s -> %-11s %-20s HLS=%s"
          % (a[:30], f.width, f.height, f.duration_s, f.bpp, f.moov_at_end,
             d.action, d.rule_id, r.required))
PY

# ── 4. HLS gerçek paketleme + çözme (§6) — ~5 dk CPU
#    (9mb.mp4 -> REMUX -> make_hls -> ffmpeg ile master/varyant çözme)
#    Tam betik bu belgenin §6 tablolarını üretir; iskeleti:
#      T.remux(src, dst) ; H.select_ladder(facts) ; H.make_hls(dst, outdir)
#      ffmpeg -v error -i <outdir>/master.m3u8       -f null -   # rc 0 beklenir
#      ffmpeg -v error -i <outdir>/v360p/playlist.m3u8 -f null - # rc 0 beklenir

# ── 5. Kota kapısının BAYT olduğunun doğrulaması (§7.2)
sed -n '267,295p' tradehub_core/media/files.py
grep -n "current_bytes + incoming_bytes" -B4 -A6 tradehub_core/entitlement/checks.py

# ── 6. Faz 7 DIŞI düşen testlerin kök nedeni (§2.4)
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -m unittest \
  tradehub_core.tests.test_media_transcode 2>&1 | tail -5
```

---

## 10-A. KANIT VE KAPI DURUMU — 2026-08-19, D3 ölçümü

> **Bu bölüm `docs/reports/56-d3-faz6-10-kapanis.md` §4 tarafından eklendi.**
> Belgenin gövdesine, kararlarına ve **§11 imza bloğuna dokunulmadı.** Amacı tek:
> bu belgenin bıraktığı üç bloklayıcının bugünkü ölçülmüş durumunu tek yerde
> göstermek.

### Bloklayıcıların bugünkü durumu

| Bloklayıcı (§9.1) | Bugün | Kanıt |
|---|---|---|
| **B-1** — H.264 hedefi kütüphanede hiç kazanmıyor | ✅ **KAPANDI** | `39-t072-video-hatti.md` §2: capped-CRF, tavan INV-05'ten türetiliyor. Kapıyı geçen gerçek TRANSCODE **0 → 2**, net **+2.676.734 B**. Vacuity anahtarı testte pinli |
| **B-2** — kapıdan düşen TRANSCODE, REMUX ihtiyacını öldürüyor | ✅ **KAPANDI** | `39-…` §3: gerçek dosyada (r1, moov sonda) geri çekilme doğrulandı; moov **başa alındı**. Kapalıyken moov'un sonda kaldığı ayrıca pinli |
| **B-6** — VMAF ölçülemedi (*"tek bloklayıcı"*) | ❌ **AÇIK** | 2026-08-19, D3: `docker exec istoc-dev-backend-1 ffmpeg -filters \| grep -c libvmaf` → **0**; `ffmpeg 5.1.9-0+deb12u1`. Üretim imajı değişmedi |
| **B-3** — `video_decision.json` `status: "draft"` | ❌ **AÇIK** | 2026-08-19, D3: dosyanın `status` alanı hâlâ `"draft"`. Aynı durum `brand-logo.json`, `seller-logo.json`, `company-cover-video.json` için de geçerli |

### Test kapısı — bugün koşuldu

```
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -m unittest \
  tradehub_core.tests.test_video_decision tradehub_core.tests.test_video_transcode

Ran 167 tests in 170.272s
OK
```

**167 test · 0 hata · 0 başarısız · 0 atlanan.** (Bu belge yazıldığında 147'ydi.)

### §1.1'in bekleyen maddesi — kriterin kendisi ölçümle BOŞ çıktı

Bu belge Faz 7'yi *"§9.1'deki tek bloklayıcı (B-6) kapandığında"* imzaya sunmayı
planlıyordu. `39-t072-video-hatti.md` §4 bu planın eksik olduğunu ölçtü:

> Gerçek 1080p bir kaynakta (r2) fayda kapısı çıktının en fazla **7.654.412 B**
> olmasını istiyor; o bütçedeki en iyi ölçülen VMAF **≈86–89**. VMAF **92,11**'e
> çıkmak **10.248.429 B** — kaynaktan **%20 BÜYÜK** dosya gerektiriyor.
> **VMAF ≥93 ile INV-05 fayda kapısı bu dosyada AYNI ANDA SAĞLANAMAZ.**

93 eşiği sentetik `testsrc2` korpusundan kalibre edilmişti; gerçek içerikte
CRF 23'ün bandı **75–90** ölçüldü (r2 86,40 · r3 77,81 · r6 74,88, çıktı
çözünürlüğünde, n=3).

**Sonuç:** `libvmaf` imaja eklense bile bu belge bugünkü kriterle imzalanamaz —
kapı boştur. Faz 7'nin kapanışı artık **teknik bir eksiğe değil, bir karara**
bağlıdır. Üç seçenek ve ölçülmüş bedelleri
`docs/reports/56-d3-faz6-10-kapanis.md` §4.3'tedir; karar platform yöneticisinindir.

### §9.2'nin diğer maddeleri — bugünkü durum

| Konu | Durum |
|---|---|
| T-072/4 süre farkı ≤100 ms | ✅ **ÖLÇÜLÜYOR** — gerçek ve sentetik kaynaklarda 0–1 ms (`39-…` §5) |
| T-074/3 mobil veri tavanı (ilk 10 sn) | ✅ **ÖLÇÜLÜYOR** — 161.841 / 173.121 / 275.581 B, tavan 1.280.000 B (`39-…` §6.1) |
| Tarayıcı oynatması | ✅ **DOĞRULANDI** — hls.js + HeadlessChrome 151, `readyState=4`, 405 segment (`39-…` §7) |
| **YENİ B-3** — HLS merdiveninde fayda kapısı yok, 720p basamağı kaynaktan %25,7 büyük | ❌ **AÇIK** (`39-…` §6.3) |
| Poster bayt kapısı (120 KB) gerçek içerikte ancak WebP kalite 40'ta tutuyor | **KARAR GEREKLİ** (`39-…` §8.2) |
| HDR→SDR tone-mapping · lip-sync · Safari/iOS yerel HLS | — **ÖLÇÜLMEDİ** |

---

## 11. İmza

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Faz 7 sorumlusu | — | — | ☐ |
| Medya motoru mimarı | — | — | ☐ |
| Platform yöneticisi | — | — | ☐ |

> **İmza bloğu bilinçli olarak boştur.** Faz 7 §1.1 uyarınca **kapanmamıştır**;
> imzalanacak bir kapanış yoktur. §9.1'deki tek bloklayıcı (B-6) kapandığında
> bu belge revize edilir ve imzaya sunulur.
