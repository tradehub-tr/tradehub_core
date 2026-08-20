# T-072 / T-016 — VMAF ölçümü ve AV1 vs H.264 bayt karşılaştırması

**Görevler:** T-072 (Transcode kalite kapısı — VMAF) · T-016 (AV1 vs H.264 aynı VMAF'ta bayt) · **Faz:** 7
**Tarih:** 2026-08-19 · **Branch:** `ahmet`
**Bu belge neyi kapatıyor:** `docs/reports/18-faz7-kapanis.md` §8 **B-6** — Faz 7'nin
**tek bloklayıcısı** olan "VMAF ölçüm aracı yok" bulgusu.

---

## ÖZET — 6 madde

| # | Sonuç | Kanıt |
|---|---|---|
| **1** | **VMAF ARACI ÇALIŞIYOR.** `linuxserver/ffmpeg` (ffmpeg 9.0, `--enable-libvmaf`) standalone `docker run` ile getirildi. `docker/docker-compose.yml`'a **dokunulmadı**, üretim imajı değişmedi. | §1.3 |
| **2** | **T-072 ÖLÇÜLDÜ.** 7 fixture'ın 7'sinde + canlı kütüphanenin tek TRANSCODE adayında VMAF ölçüldü. **6/7 fixture ≥ 93.** Düşen tek dosya 1080p sınıfı (**87,78**); gerçek 1080p dosyada **90,21**. | §3.3, §3.7 |
| **3** | **Faz 7'nin tek bloklayıcısı B-6 KAPANDI** — ama K-8 "kapının koruduğu kapsamda" geçiyor: kapıdan geçen tek çıktının VMAF'ı **97,44 ≥ 93**; canlı kütüphanede kapı **4/4 çıktıyı attığı** için kriter bugün **boş kümede** tutuyor. | §6.1, §6.2 |
| **4** | **T-016: AV1 gerçekten %31,7 daha verimli** (gerçek içerik, aynı VMAF: **0,683×** H.264). | §4.5 |
| **5** | **AMA AV1 B-1'i ÇÖZMÜYOR.** Aynı dosyada H.264 kaynağın **1,760 katı**; %31,7 kesinti **1,202 kata** indiriyor, kapı **0,90** istiyor. Kapıyı ancak **CRF 40 / VMAF 85,40**'ta geçiyor — 93 hedefinden **7,6 puan** aşağıda. **KARAR: AV1 şimdi eklenmesin**, önce hız denetimi düzeltilsin. Sayısal tetik §5.5'te. | §4.5, §5.1, §5.4, §5.5 |
| **6** | **SENTETİK FİXTURE KORPUSU İKİ KEZ YANILTTI** — küçültme kaybını abarttı (92,30 vs gerçek 98,53) ve AV1'in avantajını yarıya indirdi (0,862× vs gerçek 0,683×). 7 fixture'ın 7'si de `testsrc2`. **Kalite/bayt eşiği kararları bu korpusa dayandırılmamalı.** | §3.7, §4.5, V-2 |

---

## 0. Bu belgenin kuralı

> **HİÇBİR SAYI KOŞULMADAN YAZILMADI.** Her tablodaki her sayının komutu ve ham
> çıktısı bu belgede. Ölçülemeyen "ölçülemedi" diye yazıldı.

**Bu belge hiçbir kod dosyasını, politika JSON'unu, DocType'ı ya da
`docker/docker-compose.yml`'ı değiştirmedi.** Ölçüm çıktıları konteynerin
`/tmp/t072out` ve ana makinenin `/tmp/t072` alanında geçici dosyalardır; site
dosyalarına ve veritabanına yazılmadı. Bayraklar 0 bırakıldı.

---

## 1. VMAF aracı — nasıl getirildi, kanıtı

### 1.1 Başlangıç durumu (18-faz7-kapanis.md'nin bıraktığı yer)

Konteynerdeki ffmpeg `libvmaf` olmadan derlenmiş:

```bash
$ docker exec istoc-dev-backend-1 sh -c 'ffmpeg -hide_banner -version | tr " " "\n" | grep -E "enable-(libaom|libsvtav1|librav1e|libvmaf|libx264|libvpx)"'
--enable-libaom
--enable-libsvtav1
--enable-libvpx
--enable-libx264
--enable-librav1e
```

`--enable-libvmaf` **listede yok**. Buna karşılık **AV1 kodlayıcılarının üçü de
zaten var** — bu, §7'nin kararını doğrudan etkiler:

```bash
$ docker exec istoc-dev-backend-1 sh -c 'ffmpeg -hide_banner -encoders | grep -iE "av1|libx264|vp9"'
 V....D libaom-av1           libaom AV1 (codec av1)
 V....D librav1e             librav1e AV1 (codec av1)
 V..... libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder (codec av1)
 V....D libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10
 V....D libvpx-vp9           libvpx VP9 (codec vp9)
```

> **TUZAK — tekrarlanmasın.** Üretim ffmpeg'inin filtre listesinde `vmafmotion`
> **vardır**. O **VMAF DEĞİLDİR**: VMAF'ın yalnız hareket bileşenini hesaplar,
> kalite puanı üretmez. Bu belgedeki hiçbir sayı `vmafmotion`'dan gelmiyor.

### 1.2 Seçilen yol: hazır imaj, `docker run` ile — en az müdahale

`18-faz7-kapanis.md` §9.1 üç yol öneriyordu (A: imaj rebuild, B: ayrı araç,
C: kriteri değiştir). **B seçildi**, en ucuz biçimiyle: hazır bir imaj,
standalone `docker run`, dosyalar `-v` ile bağlı.

**`docker/docker-compose.yml`'a DOKUNULMADI.** Yeni servis eklenmedi, üretim
imajı değişmedi, `.py` değişmedi.

```bash
$ docker pull linuxserver/ffmpeg:latest
Status: Downloaded newer image for linuxserver/ffmpeg:latest
```

### 1.3 Aracın VMAF yapabildiğinin KANITI

```bash
$ docker run --rm --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner -filters | grep -iE 'libvmaf|ssim|psnr'
 TS apsnr             AA->A      Measure Audio Peak Signal-to-Noise Ratio.
 .. libvmaf           VV->V      Calculate the VMAF between two video streams.
 TS psnr              VV->V      Calculate the PSNR between two video streams.
 TS ssim              VV->V      Calculate the SSIM between two video streams.
 .. ssim360           VV->V      Calculate the SSIM between two 360 video streams.
 T. xpsnr             VV->V      Calculate the extended perceptually weighted peak signal-to-noise ratio (XPSNR) between two video streams.
```

`libvmaf` **var** — `vmafmotion` değil, **`libvmaf`**.

```bash
$ docker run --rm --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner -version | head -3
ffmpeg version 9.0 Copyright (c) 2000-2026 the FFmpeg developers
built with gcc 15 (Ubuntu 15.2.0-16ubuntu1)
configuration: ... --enable-libaom ... --enable-librav1e ... --enable-libsvtav1 ... --enable-libvmaf ... --enable-libx264 ...
```

**Ölçümün kendisinin doğrulaması** (dosyanın kendisiyle karşılaştırılması —
sıfır bozulma, VMAF tavana yakın olmalı):

```bash
$ docker run --rm -v /tmp/t072:/w --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest \
    -hide_banner -i /w/src/video_square_352.mp4 -i /w/src/video_square_352.mp4 \
    -filter_complex "[0:v][1:v]libvmaf" -f null -
[Parsed_libvmaf_0 @ 0xffff6c002ac0] VMAF score: 99.982856
```

Araç çalışıyor.

### 1.4 Ölçüm parametreleri (tekrarlanabilirlik)

```bash
$ docker run --rm --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner -h filter=libvmaf
Filter libvmaf
    Inputs:
       #0: main (video)          <- BOZULMUŞ (distorted)
       #1: reference (video)     <- KAYNAK
   model  (default "version=vmaf_v0.6.1")
   pool   (varsayılan: mean)
   n_subsample (default 1)       <- kare atlama YOK, her kare ölçüldü
```

| Parametre | Değer |
|---|---|
| Model | `vmaf_v0.6.1` (libvmaf varsayılanı) |
| Havuzlama | ortalama (mean) |
| Kare altörnekleme | **yok** (`n_subsample=1`) |
| Hizalama | Çıktı **referans çözünürlüğüne** bikübik büyütülür |

**Hizalama neden böyle:** `tradehub_core/media/pipeline/video/transcode.py`
`measure_quality()` tam olarak bunu yapıyor
(`[1:v]scale={ref.width}:{ref.height}:flags=bicubic[dist];[dist][0:v]…`) ve
gerekçesini docstring'inde yazıyor: *"kullanıcı 1080p ekranda ne görüyor"*.
Bu belgedeki filtre zinciri motorun kendi zinciriyle **birebir aynıdır** —
yalnız `ssim`/`psnr` yerine `libvmaf` yazıyor. Yani ölçülen sayı, motor
`vmaf_available()` True gördüğünde **kendisinin üreteceği sayıdır**.

---

## 2. Ölçülen korpus

Görev tanımındaki "7 video fixture" **doğrulandı** (tahmin edilmedi):

```bash
$ find . -type f \( -name "*.mp4" -o -name "*.mov" -o -name "*.webm" -o -name "*.mkv" \) | grep fixtures
./tradehub_core/tests/fixtures/media/video/video_square_352.mp4
./tradehub_core/tests/fixtures/media/video/video_silent_noaudio_720p.mp4
./tradehub_core/tests/fixtures/media/video/video_bloated_720p_8m.mp4
./tradehub_core/tests/fixtures/media/video/video_vertical_9x16.mp4
./tradehub_core/tests/fixtures/media/video/video_efficient_720p_750k.mp4
./tradehub_core/tests/fixtures/media/video/video_long_540s_320x240.mp4
./tradehub_core/tests/fixtures/media/video/video_16x9_1080p.mp4
```

**7 dosya, tamamı ölçüldü.** Ana makinedeki ve konteynerdeki kopyalar bayt
bayt aynı boyutta (ikisi de listelendi, karşılaştırıldı).

Künye ve karar tablosunun verdiği aksiyon (boru hattının kendi kodu koşturuldu,
**salt okuma**):

```bash
$ docker exec istoc-dev-backend-1 sh -c 'cd /home/frappe/frappe-bench/apps/tradehub_core && python -c "
from tradehub_core.media.pipeline.video import probe as P, decision as D
..."'
```

| Fixture | Çözünürlük | Süre | fps | Kodek | Video bitrate | Ses | **Karar** | Kural |
|---|---|---:|---:|---|---:|---|---|---|
| `video_16x9_1080p` | 1920×1080 | 6,0 s | 25 | h264 | 1.505.445 | yok | **TRANSCODE** | `width_over_cap` |
| `video_bloated_720p_8m` | 1280×720 | 10,0 s | 30 | h264 | 8.220.772 | aac | **TRANSCODE** | `bitrate_over_cap` |
| `video_efficient_720p_750k` | 1280×720 | 10,0 s | 30 | h264 | 767.652 | aac | PASSTHROUGH | `default` |
| `video_long_540s_320x240` | 320×240 | 540,0 s | 10 | h264 | 58.728 | yok | PASSTHROUGH | `default` |
| `video_silent_noaudio_720p` | 1280×720 | 8,0 s | 25 | h264 | 834.984 | yok | PASSTHROUGH | `default` |
| `video_square_352` | 352×352 | 6,0 s | 25 | h264 | 388.986 | yok | PASSTHROUGH | `default` |
| `video_vertical_9x16` | 720×1280 | 8,0 s | 30 | h264 | 911.187 | aac | PASSTHROUGH | `default` |

**7 fixture'ın 2'si TRANSCODE, 5'i PASSTHROUGH.** Kalitenin ölçülebilmesi için
**7'sinin de** transcode çıktısı üretildi (kapı kapatılarak) — §3.

---

## 3. T-072 — VMAF ölçümü

### 3.1 Transcode çıktıları nasıl üretildi

Çıktılar **boru hattının kendi kodu** ile, **üretim ffmpeg'i (5.1.9)** ile
üretildi. Yeniden yazılmış bir komut değil, `transcode.transcode()` çağrısı:

```bash
$ docker exec istoc-dev-backend-1 sh -c 'rm -rf /tmp/t072out && mkdir -p /tmp/t072out && cd /home/frappe/frappe-bench/apps/tradehub_core && python -c "
import json,glob,os
from tradehub_core.media.pipeline.video import probe as P, transcode as T
for f in sorted(glob.glob(\"tradehub_core/tests/fixtures/media/video/*.mp4\")):
    b=os.path.basename(f); dst=\"/tmp/t072out/h264_\"+b
    pr=P.probe(f)
    r=T.transcode(f,dst,facts=pr,enforce_benefit_gate=False)
    print(...)
"'
```

`enforce_benefit_gate=False` — **kalitenin ölçülebilmesi için**, aynen
`18-faz7-kapanis.md` §5.2'nin yaptığı gibi. Kapının normal işletimdeki kararı
§3.4'te ayrıca yazılı.

Üretilen komutun ham hâli (bir örnek; hepsi ham çıktıda):

```
nice -n 10 ffmpeg -y -i .../video_16x9_1080p.mp4 -map 0:v:0 -vf scale='min(1280,iw)':-2 \
  -c:v libx264 -profile:v high -level:v 4.0 -preset medium -crf 23 -pix_fmt yuv420p \
  -g 50 -keyint_min 50 -sc_threshold 0 -an -movflags +faststart \
  /tmp/t072out/h264_video_16x9_1080p.mp4.part.mp4
```

Bu, `video_decision.json` `targets.h264_primary` ile birebir uyumludur
(crf 23, preset medium, profile high, level 4.0, yuv420p, GOP = 2 sn × fps,
faststart).

### 3.2 VMAF ölçüm komutu

```bash
$ docker run --rm -v /tmp/t072:/w --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest \
    -hide_banner -i /w/src/<fixture> -i /w/out/h264_<fixture> \
    -filter_complex "[1:v]scale=<REF_W>:<REF_H>:flags=bicubic[dist];[dist][0:v]libvmaf" \
    -f null -
```

### 3.3 SONUÇ — ölçülen VMAF

| Fixture | Karar | Kaynak B | H.264 çıktı B | Bayt değişimi | **VMAF** | ≥ 93? | Kodlama süresi |
|---|---|---:|---:|---:|---:|:--:|---:|
| `video_16x9_1080p` | TRANSCODE | 1.131.368 | 1.067.950 | **−%5,6** | **87,78** | ❌ | 1,09 s |
| `video_bloated_720p_8m` | TRANSCODE | 10.450.180 | 4.087.312 | **−%60,9** | **97,44** | ✅ | 2,01 s |
| `video_efficient_720p_750k` | PASSTHROUGH | 1.092.127 | 2.007.172 | +%83,8 | 97,69 | ✅ | 1,50 s |
| `video_long_540s_320x240` | PASSTHROUGH | 3.986.750 | 8.784.382 | +%120,3 | **100,00** | ✅ | 3,73 s |
| `video_silent_noaudio_720p` | PASSTHROUGH | 838.179 | 1.545.301 | +%84,4 | 98,14 | ✅ | 1,02 s |
| `video_square_352` | PASSTHROUGH | 294.350 | 310.967 | +%5,6 | 98,56 | ✅ | 0,26 s |
| `video_vertical_9x16` | PASSTHROUGH | 1.017.771 | 1.829.609 | +%79,8 | 96,64 | ✅ | 1,46 s |

Ham VMAF satırları (`grep 'VMAF score'`):

```
video_16x9_1080p.mp4          (ref 1920x1080)  VMAF score: 87.781300
video_bloated_720p_8m.mp4     (ref 1280x720)   VMAF score: 97.442200
video_efficient_720p_750k.mp4 (ref 1280x720)   VMAF score: 97.689445
video_long_540s_320x240.mp4   (ref 320x240)    VMAF score: 99.999285
video_silent_noaudio_720p.mp4 (ref 1280x720)   VMAF score: 98.143932
video_square_352.mp4          (ref 352x352)    VMAF score: 98.558748
video_vertical_9x16.mp4       (ref 720x1280)   VMAF score: 96.637305
```

**6/7 fixture VMAF ≥ 93. Bir tanesi (`video_16x9_1080p`) 87,78 ile kalıyor.**

> "Kodlama süresi" sütunu boru hattının kendi `TranscodeResult.wall_s`
> değeridir (üretim ffmpeg 5.1.9, `nice -n 10`). Ana makine ölçüm boyunca
> **değişken yük** altındaydı; bu süreler **yön gösterir, kıyas ölçüsü
> değildir**. Kodek süre kıyası §5.3'te ayrıca, iç içe koşularak ölçüldü.

### 3.4 Tek düşen dosyanın anatomisi — kayıp nereden geliyor

`video_16x9_1080p` **tek 1080p
fixture**, yani **1280 teslim tavanının gerçekten küçültme yaptığı tek dosya**.
Kayıp üçe ayrıldı:

**(A) Yalnız kodlama kaybı** — çıktı kendi çözünürlüğünde (1280×720),
referans da 1280×720'ye indirilmiş:

```bash
$ docker run --rm -v /tmp/t072:/w --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner \
    -i /w/src/video_16x9_1080p.mp4 -i /w/out/h264_video_16x9_1080p.mp4 \
    -filter_complex "[0:v]scale=1280:720:flags=bicubic[ref];[1:v][ref]libvmaf" -f null -
[Parsed_libvmaf_1 @ 0xffff640101e0] VMAF score: 96.480769
```

**(B) Yalnız küçültme kaybı** — HİÇ YENİDEN KODLAMA YOK, sadece
1920→1280→1920 gidiş-dönüş:

```bash
$ docker run --rm -v /tmp/t072:/w --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner \
    -i /w/src/video_16x9_1080p.mp4 -i /w/src/video_16x9_1080p.mp4 \
    -filter_complex "[1:v]scale=1280:720:flags=bicubic,scale=1920:1080:flags=bicubic[dist];[dist][0:v]libvmaf" -f null -
[Parsed_libvmaf_2 @ 0xffff6c01d7e0] VMAF score: 92.295352
```

**(C) İkisi birlikte** (§3.3'teki sayı): **87,78**

| Bileşen | VMAF | Yorum |
|---|---:|---|
| Yalnız CRF 23 kodlaması (1280 referansta) | **96,48** | Kodlayıcı ayarı **sağlam** |
| Yalnız 1280 küçültmesi (kodlama yok) | **92,30** | **Tek başına 93'ün ALTINDA** |
| Küçültme + kodlama (teslim edilen) | **87,78** | |

> **Bu fixture'da `max_width: 1280` küçültmesi, kodlayıcı mükemmel olsa
> (CRF 0, kayıpsız) bile tavanı 92,30'a çekiyor** — yani VMAF ≥ 93 bu dosyada
> kodlama ayarıyla kurtarılamaz.
>
> **AMA BU SONUÇ GENELLENEMEZ.** Bu fixture sentetiktir (`testsrc2` test
> deseni) ve küçültmeye aşırı hassastır. **Aynı ölçüm gerçek bir 1080p
> dosyada tekrarlandığında küçültmenin tavanı 98,53 çıkıyor** — yani orada
> 93 rahatlıkla erişilebilir ve suçlu politika değil CRF 23'tür. Ayrıntı ve
> karşılaştırma tablosu **§3.7**'de; sonuç bulgusu **V-2**.

### 3.5 Fayda kapısıyla birlikte okuma — normal işletimde ne olur

Kapı `min_saving_ratio = 0.1` (`video_decision.json` `targets.benefit_gate`).
`saving_ratio = 1 − çıktı/kaynak`:

| Fixture | Karar | saving_ratio | Kapı | Diske yazılan |
|---|---|---:|---|---|
| `video_16x9_1080p` | TRANSCODE | **+0,056** | ❌ **AT** (0,056 < 0,10) | kaynak korunur |
| `video_bloated_720p_8m` | TRANSCODE | **+0,609** | ✅ **KABUL** | H.264 çıktı |
| diğer 5 | PASSTHROUGH | — | uygulanmaz | dokunulmaz |

**Bu, T-072 için belirleyici okuma:**

> Normal işletimde **7 fixture'ın yalnız 1'i** için transcode çıktısı diske
> yazılıyor: `video_bloated_720p_8m`. Onun VMAF'ı **97,44** — hedefin
> **4,4 puan üstünde**.
>
> **Boru hattının fiilen TESLİM ETTİĞİ her transcode çıktısı VMAF ≥ 93'ü
> tutuyor.** 87,78 puanlı çıktı hiçbir zaman diske yazılmıyor; fayda kapısı
> onu zaten atıyor.

**Canlı kütüphanede de aynı tablo:** `18-faz7-kapanis.md` §5.3'e göre 4
transcode adayının **4'ünde de** kapı çıktıyı attı. §3.7'de o adayın
(`10 (1).mp4`) VMAF'ı ölçüldü: **90,21 < 93** — ve kapı onu da **atıyor**.
Yani **canlı kütüphanede bugün teslim edilen tek bir transcode çıktısı bile
yok**; VMAF kriteri boş bir kümede tutuyor. Bu, kriterin geçtiğini söylerken
**dürüstçe eklenmesi gereken şerhtir** (§6.2).

Bu tam olarak `tests/test_e2e_scenarios.py::Senaryo08SisikVideoKuculur`'un
sorduğu sorudur — docstring'i aynen şöyle: *"Şişik bitrate video yüklenir →
küçülür, VMAF ≥ 93."* Aynı dosyada `test_VMAF_OLCULEMEDI` **skip** ediliyordu.
**Ölçüldü: 97,44 ≥ 93. Senaryo geçiyor.**

### 3.6 VMAF ile SSIM/PSNR karşılaştırması

Aynı 7 fixture üzerinde SSIM/PSNR de ölçüldü — **boru hattının kendi
`measure_quality()`'si ile, üretim ffmpeg 5.1.9'da**, yani
`18-faz7-kapanis.md` §5.2 ile birebir aynı yöntemle:

```bash
$ docker exec istoc-dev-backend-1 sh -c 'cd /home/frappe/frappe-bench/apps/tradehub_core && python -c "
from tradehub_core.media.pipeline.video import transcode as T
print(\"vmaf_available() =\", T.vmaf_available())
for f in sorted(glob.glob(\"tradehub_core/tests/fixtures/media/video/*.mp4\")):
    k=T.measure_quality(f, \"/tmp/t072out/h264_\"+os.path.basename(f)); print(...)
"'
vmaf_available() = False
{"file": "video_16x9_1080p.mp4",          "ssim": 0.97962,   "psnr": 36.750784, "vmaf": null, "note": "VMAF YOK — ffmpeg libvmaf olmadan derlenmis"}
{"file": "video_bloated_720p_8m.mp4",     "ssim": 0.995605,  "psnr": 44.546024, "vmaf": null, ...}
{"file": "video_efficient_720p_750k.mp4", "ssim": 0.997507,  "psnr": 48.003743, "vmaf": null, ...}
{"file": "video_long_540s_320x240.mp4",   "ssim": 0.997506,  "psnr": 49.51823,  "vmaf": null, ...}
{"file": "video_silent_noaudio_720p.mp4", "ssim": 0.997558,  "psnr": 47.918938, "vmaf": null, ...}
{"file": "video_square_352.mp4",          "ssim": 0.994879,  "psnr": 43.972081, "vmaf": null, ...}
{"file": "video_vertical_9x16.mp4",       "ssim": 0.997312,  "psnr": 47.183149, "vmaf": null, ...}
```

> Not: üretim konteynerinde `vmaf_available()` **hâlâ False** — bu belge o
> konteyneri değiştirmedi. VMAF ayrı bir imajla, dışarıdan ölçüldü (§1.2).

**Sıralama karşılaştırması** (1 = en iyi):

| Fixture | VMAF | # | SSIM | # | PSNR | # |
|---|---:|:--:|---:|:--:|---:|:--:|
| `video_long_540s_320x240` | 100,00 | 1 | 0,997506 | 3 | 49,52 | 1 |
| `video_square_352` | 98,56 | **2** | 0,994879 | **6** | 43,97 | **6** |
| `video_silent_noaudio_720p` | 98,14 | 3 | 0,997558 | 1 | 47,92 | 3 |
| `video_efficient_720p_750k` | 97,69 | 4 | 0,997507 | 2 | 48,00 | 2 |
| `video_bloated_720p_8m` | 97,44 | 5 | 0,995605 | 5 | 44,55 | 5 |
| `video_vertical_9x16` | 96,64 | 6 | 0,997312 | 4 | 47,18 | 4 |
| `video_16x9_1080p` | **87,78** | **7** | **0,979620** | **7** | **36,75** | **7** |

| Sıra korelasyonu (Spearman ρ, n=7) | Değer |
|---|---:|
| VMAF ↔ SSIM | **0,429** |
| VMAF ↔ PSNR | **0,571** |
| SSIM ↔ PSNR | **0,857** |

**Aynı yönde mi, ayrışıyor mu — üç cümlelik cevap:**

1. **Uç noktada AYNI YÖNDE.** Üç ölçü de `video_16x9_1080p`'yi **7/7 sonuncu**
   koyuyor. SSIM 0,9796 ve PSNR 36,75 dB, `18-faz7-kapanis.md` §5.2'nin ölçtüğü
   bandın (0,9900–0,9967 / 45,4–49,5 dB) **tamamen dışında**. Yani SSIM de bu
   dosyayı işaretlerdi — **ama §5.2 bu sınıftan bir dosya ölçmemişti**
   (ölçtüğü 3 dosyanın hiçbiri 1080p değildi, hiçbiri gerçekten küçültülmedi).
   Rapor 18'in *"neredeyse kayıpsız"* yorumu **ölçtüğü örneklem için doğruydu**;
   örneklem, başarısız olan tek sınıfı içermiyordu.

2. **Sıralamada AYRIŞIYOR.** SSIM ve PSNR birbiriyle güçlü uyumlu (ρ = 0,857),
   ama VMAF ikisiyle de zayıf uyumlu (ρ = 0,43 / 0,57). En keskin örnek
   **`video_square_352`**: SSIM'de 6/7, PSNR'de 6/7 (yani "kötüler" arasında),
   VMAF'ta **2/7** (yani "iyiler" arasında). 352×352'lik küçük kareli içerikte
   piksel-farkı ölçüleri cezalandırıyor, algısal model cezalandırmıyor.

3. **Dolayısıyla biri diğerinin yerine geçemez.** `18-faz7-kapanis.md` §5.2'nin
   *"SSIM ve VMAF farklı ölçeklerde farklı şeyleri ölçer; birinden diğerine
   dönüşüm yapmak uydurma olur"* cümlesi **ölçümle doğrulandı**. SSIM 0,99
   tabanı ile VMAF 93 tabanı bu korpusta **aynı dosyaları geçirmez**:
   VMAF 93 kapısı 1 dosya eler, SSIM 0,99 kapısı da aynı 1 dosyayı eler —
   ama sıralamalar farklı olduğu için korpus biraz değişse kararlar ayrışır.
   `18-faz7-kapanis.md` §9.1'in **C yolu** ("kriteri SSIM'e çevir") bu yüzden
   **bedelsiz değildir**; artık gerek de yok, çünkü B yolu koştu.

### 3.7 Aynı ölçüm GERÇEK içerikte — ve sentetik korpusun yanılttığı yer

Fixture'ların **7'si de sentetiktir**: `scripts/gen_fixtures_video.sh` hepsini
ffmpeg'in `testsrc2` test deseninden üretiyor.

```bash
$ head -12 scripts/gen_fixtures_video.sh
#!/bin/sh
# T-006 — video fixture üreteci. Konteynerin ffmpeg'i ile çalışır.
...
$FF -f lavfi -i "testsrc2=size=1280x720:rate=30:duration=10" \
    -f lavfi -i "sine=frequency=440:duration=10" \
    -c:v libx264 -preset medium -b:v 750k ...
$ grep -c "testsrc2" scripts/gen_fixtures_video.sh
7
```

`testsrc2` keskin kenarlı, yüksek kontrastlı, ince detaylı bir **test
desenidir** — gerçek B2B ürün videosuna hiç benzemez ve özellikle **küçültmeye
karşı aşırı hassastır**. Bu yüzden ölçüm gerçek içerikte tekrarlandı.

`18-faz7-kapanis.md` §4.2'nin ölçtüğü 5 canlı dosyanın **tek TRANSCODE adayı**
`10 (1).mp4`'tür (1920×1080, 58,2 sn) — `video_16x9_1080p` fixture'ının gerçek
karşılığı.

```bash
$ docker exec istoc-dev-backend-1 sh -c 'cp ".../public/files/10 (1).mp4" /tmp/t072live/live1080p.mp4'
$ ... python -c "... T.transcode(src, dst, facts=pr, enforce_benefit_gate=False) ..."
{"w": 1920, "h": 1080, "dur": 58.19, "action": "TRANSCODE", "rule": "width_over_cap",
 "src": 8504902, "out": 14490432, "saving": -0.7038, "wall": 87.35}

# C — küçültme + kodlama (teslim edilecek hâl)
[Parsed_libvmaf_1 @ 0xffff640101e0] VMAF score: 90.209983
# A — yalnız kodlama (referans 1280×720'ye indirilmiş)
[Parsed_libvmaf_1 @ 0xffff900101e0] VMAF score: 95.489100
# B — yalnız küçültme, KODLAMA YOK (1920→1280→1920)
[Parsed_libvmaf_2 @ 0xffff9801d7e0] VMAF score: 98.526974
```

> Bayt sayıları `18-faz7-kapanis.md` §5.1 ile **birebir aynı**
> (8.504.902 → 14.490.432, **+%70,4**). Ölçüm tekrarlanabilir.

| Bileşen | Fixture `video_16x9_1080p` (**sentetik**) | Canlı `10 (1).mp4` (**gerçek**) |
|---|---:|---:|
| **B** — yalnız 1280 küçültmesi (kodlama yok) | **92,30** | **98,53** |
| **A** — yalnız CRF 23 kodlaması (1280 referansta) | 96,48 | 95,49 |
| **C** — teslim edilecek (ikisi birlikte, 1920 referansta) | **87,78** | **90,21** |
| Fayda kapısı kararı | **AT** (kazanç %5,6 < %10) | **AT** (çıktı kaynaktan **%70,4 büyük**) |

**Bu tablonun söylediği iki ayrı şey var — karıştırılmamalı:**

1. **Ortak sonuç:** her iki 1080p dosyada da teslim edilecek çıktı **VMAF 93'ün
   altında** (87,78 / 90,21). Ve **her ikisinde de fayda kapısı çıktıyı zaten
   atıyor** — bu kalite hiçbir zaman kullanıcıya ulaşmıyor.

2. **Ayrışan sonuç — ve bu bir UYARI:** *kaybın nereden geldiği* iki korpusta
   **farklı**.
   - Sentetik fixture'da küçültmenin **tek başına** tavanı **92,30**, yani
     **93 zaten erişilemez**; kodlayıcı ne yaparsa yapsın kriter tutmaz.
   - Gerçek dosyada küçültmenin tavanı **98,53**, yani **93 rahatlıkla
     erişilebilir**; 90,21'e düşüren şey kodlamanın kendisidir
     (CRF 23 fazla agresif), politika değil.

   > **Yani sentetik korpusa bakarak *"`max_width: 1280` politikası VMAF 93'ü
   > imkânsız kılıyor, politika değişmeli"* denirdi. Gerçek içerik bunu
   > **yalanlıyor**: politika sağlam, ayar (CRF 23) fazla agresif.**
   > `testsrc2`'nin keskin kenarları küçültmede yok oluyor; gerçek video
   > yumuşak ve küçültmeye dayanıyor.

Bu, **V-2** bulgusudur ve T-016'nın da neden gerçek içerikte tekrarlandığını
açıklar (§4.5).

Geçici kopyalar ölçümden sonra silindi; site dosyalarına yazılmadı.

---

## 4. T-016 — AV1 vs H.264, aynı VMAF'ta bayt

### 4.1 Sorunun doğru hâli

`18-faz7-kapanis.md` **B-1** bulgusu bu ölçümün çerçevesini belirliyor:

> *"H.264 hedefi bugünkü kütüphanede hiç kazanmıyor. CRF 23 / preset medium,
> 4 gerçek dosyanın 4'ünde de kaynaktan büyük çıktı üretti (%+0,4 … %+70,4).
> Kütüphane zaten düşük bitrate'li (p50 746 kbps); hedef kalite kaynağın
> kalitesinin üstünde."*

§3.3 bunu **fixture korpusunda da doğruladı**: 7 fixture'ın **5'inde** H.264
çıktısı kaynaktan büyük (+%5,6 … +%120,3), 1'inde kazanç kapının altında
(−%5,6 < %10), yalnız 1'inde gerçek kazanç var (−%60,9).

Dolayısıyla T-016'nın sorusu **"AV1, H.264'ten iyi mi"** değildir — o sorunun
cevabı literatürde zaten bellidir ve bu kütüphanede karar vermez. Doğru soru:

> **AV1, H.264'ün kaybettiği yerde kaynaktan KÜÇÜK çıktı üretebiliyor mu?**
> Yani fayda kapısını (%10) AV1 açabiliyor mu?

Bu yüzden aşağıdaki tablolarda iki oran birden var: **AV1/H.264** (kodek
karşılaştırması) ve **AV1/kaynak** (kapıyı ilgilendiren tek oran).

### 4.2 Yöntem

**Aynı VMAF nasıl sabitlendi:** H.264 çapası boru hattının kendi hedefidir
(`targets.h264_primary`: CRF 23, preset medium). Onun ölçülen VMAF'ı **hedef**
kabul edildi. AV1 için CRF taraması {25, 30, 35, 40, 45} koşuldu; hedef VMAF'ı
kuşatan iki nokta arasında **CRF doğrusal, bayt logaritmik** interpole edildi
(bitrate CRF ile üssel değişir, doğrusal değil).

**Kontroller:**

| Değişken | Nasıl sabitlendi |
|---|---|
| ffmpeg sürümü | **İkisi de ffmpeg 9.0** (linuxserver imajı) ile kodlandı — karşılaştırma kodek farkını ölçsün, ffmpeg sürüm farkını değil |
| Ölçek filtresi | ikisinde de `scale='min(1280,iw)':-2` (boru hattıyla aynı) |
| GOP | ikisinde de 2 sn × kaynak fps |
| Ses | ikisinde de AAC 128k / 2 kanal / 48 kHz (sessiz kaynakta `-an`) |
| Piksel biçimi | ikisinde de `yuv420p` |
| Kap | ikisinde de mp4 + `+faststart` |
| VMAF hizalaması | ikisinde de referans çözünürlüğünde, bikübik (§1.4) |
| AV1 kodlayıcı | `libsvtav1`, **preset 6** |

**ffmpeg 9.0'ın H.264 çapası, üretim ffmpeg'i 5.1.9'unkiyle aynı mı?** Evet —
çapraz doğrulandı:

| Fixture | 5.1.9 çıktı B (boru hattı) | 9.0 çıktı B (bu tarama) | VMAF 5.1.9 | VMAF 9.0 |
|---|---:|---:|---:|---:|
| `video_16x9_1080p` | 1.067.950 | 1.067.935 | 87,7813 | 87,7813 |
| `video_bloated_720p_8m` | 4.087.312 | 4.087.260 | 97,4422 | 97,4422 |

Fark **15 ve 52 bayt** (‰0,001'in altında), VMAF **birebir aynı**. Tarama
sonuçları üretim ffmpeg'ini temsil ediyor.

**İnterpolasyon doğru mu — DOĞRULANDI.** Yöntem, ölçülmemiş bir noktayı
tahmin ettiği için sınandı: `video_16x9_1080p` **gerçekten** CRF 31'de
kodlandı ve model tahminiyle karşılaştırıldı.

```bash
$ docker run --rm -v /tmp/t072:/w --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest \
    -hide_banner -y -i /w/src/video_16x9_1080p.mp4 -map 0:v:0 -vf "scale='min(1280,iw)':-2" \
    -c:v libsvtav1 -preset 6 -crf 31 -pix_fmt yuv420p -g 50 -an -movflags +faststart /w/val/av1_crf31.mp4
$ ls -l val/av1_crf31.mp4
gercek bayt: 966691
$ ... -filter_complex "[1:v]scale=1920:1080:flags=bicubic[dist];[dist][0:v]libvmaf" -f null -
VMAF score: 87.960100
```

| CRF 31'de | Modelin tahmini | **Gerçek ölçüm** | Hata |
|---|---:|---:|---:|
| Bayt | 955.960 | **966.691** | **%1,1** |
| VMAF | 87,917 | **87,960** | **0,043 puan** |

Bayt tahmininde **%1,1**, VMAF'ta **0,04 puan** hata. İnterpolasyon
sonuçları taşıyacak kadar doğru.

**`preset 6` neden:** SVT-AV1'in preset ölçeği 0 (en yavaş/en iyi) – 13 (en
hızlı). 6, x264'ün `medium`'una karşılık gelen "üretimde koşulabilir" bandın
içindedir. **Bu bir seçimdir, ölçüm değildir** — daha yavaş bir preset daha
küçük dosya verir, daha hızlısı daha büyük. Kararın süre ayağı bu seçime
bağlıdır ve §5.3'te açıkça yazılı.

### 4.3 Ham tarama çıktısı — 7 fixture × (1 H.264 çapa + 5 AV1 CRF) = 42 koşum

```
file,codec,crf,bytes,src_bytes,ratio_vs_src,vmaf,elapsed
video_16x9_1080p.mp4,h264,23,1067935,1131368,.9439,87.781300,0:00:01.46
video_16x9_1080p.mp4,av1,25,1590541,1131368,1.4058,89.524060,0:00:02.69
video_16x9_1080p.mp4,av1,30,1058298,1131368,.9354,88.266253,0:00:02.80
video_16x9_1080p.mp4,av1,35,640917,1131368,.5664,86.521137,0:00:02.78
video_16x9_1080p.mp4,av1,40,357326,1131368,.3158,84.673817,0:00:05.92
video_16x9_1080p.mp4,av1,45,203198,1131368,.1796,82.767875,0:00:05.29
video_bloated_720p_8m.mp4,h264,23,4087260,10450180,.3911,97.442200,0:00:05.06
video_bloated_720p_8m.mp4,av1,25,6375406,10450180,.6100,98.808052,0:00:15.06
video_bloated_720p_8m.mp4,av1,30,4742261,10450180,.4537,98.150887,0:00:26.66
video_bloated_720p_8m.mp4,av1,35,3478920,10450180,.3329,97.013069,0:00:15.77
video_bloated_720p_8m.mp4,av1,40,2254156,10450180,.2157,95.296596,0:00:15.41
video_bloated_720p_8m.mp4,av1,45,1398469,10450180,.1338,93.398551,0:00:15.31
video_efficient_720p_750k.mp4,h264,23,2007016,1092127,1.8377,97.689445,0:00:06.74
video_efficient_720p_750k.mp4,av1,25,3751992,1092127,3.4354,98.447614,0:00:18.04
video_efficient_720p_750k.mp4,av1,30,2828668,1092127,2.5900,97.799984,0:00:21.30
video_efficient_720p_750k.mp4,av1,35,2125012,1092127,1.9457,96.856370,0:00:16.87
video_efficient_720p_750k.mp4,av1,40,1536371,1092127,1.4067,95.621503,0:00:17.10
video_efficient_720p_750k.mp4,av1,45,1043171,1092127,.9551,94.109670,0:00:22.24
video_long_540s_320x240.mp4,h264,23,8784367,3986750,2.2033,99.999285,0:00:15.84
video_long_540s_320x240.mp4,av1,25,17585027,3986750,4.4108,99.999444,0:00:39.91
video_long_540s_320x240.mp4,av1,30,14286777,3986750,3.5835,99.999415,0:00:41.13
video_long_540s_320x240.mp4,av1,35,11017379,3986750,2.7634,99.999303,0:00:47.19
video_long_540s_320x240.mp4,av1,40,8331750,3986750,2.0898,99.996952,0:01:04.57
video_long_540s_320x240.mp4,av1,45,6270635,3986750,1.5728,99.912508,0:00:58.07
video_silent_noaudio_720p.mp4,h264,23,1545286,838179,1.8436,98.143932,0:00:04.93
video_silent_noaudio_720p.mp4,av1,25,2681002,838179,3.1986,98.936623,0:00:12.41
video_silent_noaudio_720p.mp4,av1,30,1980731,838179,2.3631,98.279051,0:00:23.61
video_silent_noaudio_720p.mp4,av1,35,1448776,838179,1.7284,97.227219,0:00:09.37
video_silent_noaudio_720p.mp4,av1,40,1024363,838179,1.2221,95.908031,0:00:19.03
video_silent_noaudio_720p.mp4,av1,45,661752,838179,.7895,94.317092,0:00:11.76
video_square_352.mp4,h264,23,310952,294350,1.0564,98.558748,0:00:01.17
video_square_352.mp4,av1,25,509385,294350,1.7305,99.551206,0:00:02.67
video_square_352.mp4,av1,30,400964,294350,1.3622,99.183209,0:00:02.39
video_square_352.mp4,av1,35,290258,294350,.9860,98.470288,0:00:03.81
video_square_352.mp4,av1,40,195823,294350,.6652,97.435805,0:00:04.01
video_square_352.mp4,av1,45,127811,294350,.4342,96.077523,0:00:03.46
video_vertical_9x16.mp4,h264,23,1829312,1017771,1.7973,96.637305,0:00:08.94
video_vertical_9x16.mp4,av1,25,3601779,1017771,3.5388,97.886582,0:00:10.06
video_vertical_9x16.mp4,av1,30,2632989,1017771,2.5870,97.230916,0:00:11.44
video_vertical_9x16.mp4,av1,35,1932478,1017771,1.8987,96.066227,0:00:07.47
video_vertical_9x16.mp4,av1,40,1363008,1017771,1.3392,94.588670,0:00:07.52
video_vertical_9x16.mp4,av1,45,884543,1017771,.8690,92.639262,0:00:06.11
```

> **`elapsed` sütunu KULLANILMADI.** Ölçüm sırasında ana makinede başka
> ajanlar koşuyordu; yük ortalaması **243'e** kadar çıktı (`uptime` ile
> doğrulandı). Bu sütundaki mutlak süreler yükten etkilenmiştir ve bu
> belgede **hiçbir sonuca dayanak yapılmadı**. Süre kararı §5.3'teki ayrı,
> iç içe koşulmuş ölçümden geliyor.

### 4.4 AYNI VMAF'ta karşılaştırma — fixture korpusu

Her satırda AV1 CRF'i, H.264 çapasının VMAF'ını tutturacak şekilde interpole
edildi (§4.2). `CRF*` = eşleşme noktası.

| Fixture | H.264 çıktı B | H.264 VMAF | **AV1 CRF\*** | **AV1 B** | **AV1/H.264** | **AV1/kaynak** | Kapı (≤0,90) |
|---|---:|---:|---:|---:|---:|---:|:--:|
| `video_16x9_1080p` | 1.067.935 | 87,78 | 31,4 | **920.622** | **0,862×** | **0,814×** | H.264 ❌ (0,944) → **AV1 ✅** |
| `video_bloated_720p_8m` | 4.087.260 | 97,44 | 33,1 | 3.910.091 | 0,957× | **0,374×** | H.264 ✅ (0,391) · AV1 ✅ |
| `video_square_352` | 310.952 | 98,56 | 34,4 | 302.131 | 0,972× | 1,026× | ikisi de ❌ |
| `video_efficient_720p_750k` | 2.007.016 | 97,69 | 30,6 | 2.735.459 | **1,363×** | 2,505× | ikisi de ❌ |
| `video_long_540s_320x240` | 8.784.367 | 100,00 | 35,0 | 10.993.836 | **1,252×** | 2,758× | ikisi de ❌ |
| `video_silent_noaudio_720p` | 1.545.286 | 98,14 | 30,6 | 1.902.731 | **1,231×** | 2,270× | ikisi de ❌ |
| `video_vertical_9x16` | 1.829.312 | 96,64 | 32,5 | 2.248.963 | **1,229×** | 2,210× | ikisi de ❌ |

> `video_long_540s_320x240`'ta **VMAF doygun**: H.264 100,00 ve AV1'in beş
> CRF'inin dördü de 99,99'un üstünde. Bu bölgede "aynı VMAF" ayırt edici
> değildir; satır **karşılaştırma için sayılmamalı**, yalnız eksiksizlik
> için burada.

**Üç sonuç:**

1. **AV1 genel bir kazanç DEĞİL.** 7 dosyanın **4'ünde AV1, aynı VMAF'ta
   H.264'ten 1,23×–1,36× BÜYÜK** çıktı üretti. Sebep fiziksel: bu dört
   kaynak **zaten x264 ile düşük bitrate'te kodlanmış**. Onların VMAF'ını
   tutturmak, x264'ün kendi sıkıştırma yapaylıklarını **yeniden üretmek**
   demektir — x264 bunu doğal olarak yapar (aynı dönüşüm ailesi), AV1 ise
   bunun için bit harcamak zorundadır.

2. **AV1'in kazandığı yer dar ve nettir: kaynakta gerçek fazlalık olması.**
   Kazandığı 3 dosya (0,862× · 0,957× · 0,972×) fazlalığın ölçülebilir
   olduğu dosyalardır; en büyük kazanç **gerçek küçültme yapılan tek
   dosyada** (1080p → 1280, **0,862×**).

3. **Ve bu korpusta kazandığı yerde KAPIYI AÇIYOR.** `video_16x9_1080p`'de
   H.264 `0,944×` ile kapıyı (%10 kazanç) **kaçırıyor**, AV1 `0,814×` ile
   **geçiyor**. Fayda kapısından geçen dosya sayısı **1/7'den 2/7'ye**
   çıkıyor.

> ### ⚠ BU SONUÇ GERÇEK İÇERİKTE TUTMUYOR
> Yukarıdaki 3. madde **sentetik korpusun sonucudur** ve `18-faz7-kapanis.md`
> B-1'e çözüm gibi görünür. **§4.5 aynı ölçümü gerçek bir 1080p dosyada
> tekrarladı ve sonuç TERSİNE döndü:** orada H.264 `1,760×`, AV1 `1,202×` —
> **AV1 kapıyı AÇMIYOR**. Bu tablodaki 1080p satırı **tek başına karar
> dayanağı yapılmamalıdır**; kararın dayandığı ölçüm §4.5'tir.

### 4.5 Aynı karşılaştırma GERÇEK içerikte — kararın dayandığı ölçüm

§3.7 fixture'ların **7'sinin de sentetik** (`testsrc2`) olduğunu ve sentetik
korpusun **yanlış yapısal sonuç** ürettiğini gösterdi. Kodek karşılaştırması
buna daha da duyarlıdır: `testsrc2`'nin keskin kenarları ve yapay hareketi,
kodeklerin gerçek içerikteki sıralamasını temsil etmez.

Bu yüzden §4.4 **gerçek içerikte tekrarlandı** — canlı kütüphanenin
**tek TRANSCODE adayı** `10 (1).mp4` (1920×1080, 58,19 sn, 29,97 fps, H.264,
sesli) üzerinde.

**Bir fark var, açıkça yazılıyor:** bu koşumda GOP **50** verildi; boru hattı
aynı dosyada `2 × 29,97 → 60` kullanır. Fark H.264 ve AV1 çapalarının
**ikisine de aynı** uygulandığı için kodek karşılaştırmasını etkilemez, ama
buradaki H.264 baytı (14.970.076) boru hattının kendi çıktısından
(14.490.432, §3.7) **%3,3 büyüktür**. Aynı sebeple buradaki H.264 VMAF'ı
(90,194) boru hattınınkinden (90,210) ihmal edilebilir ölçüde farklıdır.

```
file,codec,crf,bytes,src_bytes,ratio_vs_src,vmaf,elapsed
live_1080p,h264,23,14970076,8504902,1.7601,90.194184,0:00:58.68
live_1080p,av1,28,13605001,8504902,1.5996,92.185791,0:01:11.34
live_1080p,av1,32,10150561,8504902,1.1934,90.142072,0:04:18.28
live_1080p,av1,36,7747094,8504902,.9108,87.840460,0:03:38.65
live_1080p,av1,40,6006186,8504902,.7062,85.398272,0:01:58.92
```

**AYNI VMAF'ta karşılaştırma — gerçek içerik:**

| | Bayt | kaynağa oran | VMAF |
|---|---:|---:|---:|
| **Kaynak** `10 (1).mp4` | **8.504.902** | 1,000× | (referans) |
| **H.264** CRF 23 (boru hattı hedefi) | 14.970.076 | **1,760×** | 90,194 |
| **AV1** eşleşme noktası **CRF 31,90** | **10.226.657** | **1,202×** | 90,194 |

```
AV1/H.264  = 10.226.657 / 14.970.076 = 0,683   → AV1 %31,7 DAHA KÜÇÜK
AV1/kaynak = 10.226.657 /  8.504.902 = 1,202   → kapı (≤0,90) HÂLÂ GEÇİLMİYOR
Kapının açılması için gereken AV1/H.264 = 0,90 × 8.504.902 / 14.970.076 = 0,511
```

**Sentetik korpus AV1'i HAFİFE ALMIŞ:** aynı sınıfta fixture `0,862×` diyordu,
gerçek içerik **`0,683×`** diyor. Yani `testsrc2` deseni AV1'in gerçek
avantajının **yarısını gizliyor**. (§3.7'de sentetik korpus ters yönde
yanıltmıştı — küçültme kaybını **abartmıştı**. İki yanılma da aynı sebepten:
test deseni gerçek video gibi davranmıyor. **V-2**.)

**Ve asıl sonuç:** AV1 gerçekten %31,7 kazandırıyor, **ama yetmiyor.** H.264
çıktısı kaynağın 1,760 katı; %31,7'lik kesinti 1,202 kata indiriyor, kapı
0,90 istiyor. **Fark bir kodek seçimiyle kapatılamaz** — §5.1.

**Kapıyı AV1 ile açmak mümkün mü — ölçüldü, EVET ama BEDELİ VAR:**

| AV1 CRF | Bayt | kaynağa oran | VMAF | Kapı (≤0,90) | VMAF ≥ 93 |
|---:|---:|---:|---:|:--:|:--:|
| 28 | 13.605.001 | 1,600× | 92,19 | ❌ | ❌ |
| **31,9** (H.264 ile eşit kalite) | 10.226.657 | 1,202× | **90,19** | ❌ | ❌ |
| 32 | 10.150.561 | 1,193× | 90,14 | ❌ | ❌ |
| **36** | **7.747.094** | **0,911×** | **87,84** | ❌ **kıl payı** | ❌ |
| **40** | **6.006.186** | **0,706×** | **85,40** | ✅ **GEÇİYOR** | ❌ |

> AV1 kapıyı **açabiliyor** — ama ancak **CRF 40**'ta, yani **VMAF 85,40**'ta.
> Bu:
> * H.264'ün zaten **yetersiz bulunan 90,19**'undan **4,8 puan** aşağıda,
> * Faz 7 hedefi **93**'ten **7,6 puan** aşağıda,
> * ve kaynağın kendisinden (dokunulmasa **VMAF 100**) çok aşağıda.
>
> **Yani "AV1 kapıyı açıyor" cümlesi teknik olarak doğru ama pratikte
> anlamsızdır: kapıyı açmanın yolu kaliteyi 93 hedefinden daha da
> uzaklaştırmaktan geçiyor.** Kapı zaten tam bu yüzden var — bu kaynak için
> doğru karar transcode etmemektir.
---

## 5. T-016 — KARAR ÖNERİSİ

### 5.1 Ölçümün söylediği iki cümle

> **1) AV1 gerçekten daha verimli.** Gerçek içerikte, aynı VMAF'ta AV1 çıktısı
> H.264'ten **%31,7 küçük** (0,683×). Bu, literatürdeki ~%30 rakamıyla uyumlu
> ve bu belgede **ölçülmüştür**.
>
> **2) Ama bu kütüphanede YETMİYOR.** Aynı dosyada H.264 çıktısı kaynağın
> **1,760 katı**. %31,7'lik kesinti onu **1,202 kata** indiriyor — fayda
> kapısının istediği **0,90'ın hâlâ çok üstünde**. **AV1, B-1'i çözmüyor.**

Kapının açılması için gereken AV1/H.264 oranı bu dosyada **0,511**; ölçülen
oran **0,683**. Aradaki fark bir kodek seçimiyle kapatılamaz.

**Kök neden kodek değil, hız denetimi:** kaynak 1920×1080 / 58,19 sn /
**8.504.902 B = 1,169 Mbps**. Boru hattı bunu 1280'e indirip **CRF 23** ile
yeniden kodluyor ve **2,04 Mbps** üretiyor. Yani hedef kalite, kaynağın kendi
kalitesinin **üstünde**. `18-faz7-kapanis.md` B-1 bunu şöyle yazmıştı:
*"hedef kalite kaynağın kalitesinin üstünde"* — **bu ölçüm onu doğruluyor ve
kodekten bağımsız olduğunu gösteriyor.**

### 5.2 Kodek karşılaştırmasının sınıf sınıf özeti

| Sınıf | Örnek | AV1/H.264 (aynı VMAF) | AV1 kapıyı açıyor mu |
|---|---|---:|---|
| **Kaynak küçültülüyor** (`width > 1280`) | `video_16x9_1080p` · canlı `10 (1).mp4` | **0,683×** (gerçek) · 0,862× (sentetik) | **DUYARLI** — sentetikte EVET (0,944× → 0,814×), gerçekte **HAYIR** (1,760× → 1,202×). Ayrım §5.5'teki tetikte |
| **Kaynak aşırı bitrate'li** (küçültme yok) | `video_bloated_720p_8m` | 0,957× | Gerek yok — H.264 zaten `0,391×` ile geçiyor |
| **Kaynak zaten verimli** | `efficient` · `silent` · `vertical` · `long540` | **1,23× – 1,36×** (AV1 DAHA BÜYÜK) | **HAYIR** — AV1 H.264'ten de kötü |
| **Kaynak küçük çözünürlüklü** | `video_square_352` | 0,972× | **HAYIR** — `1,026×`, ikisi de kapıdan düşüyor |

**Neden "zaten verimli" sınıfında AV1 kaybediyor:** o kaynaklar **zaten x264
ile** düşük bitrate'te kodlanmış. Onların VMAF'ını tutturmak, x264'ün kendi
sıkıştırma yapaylıklarını **yeniden üretmeyi** gerektirir. x264 bunu doğal
olarak yapar (aynı dönüşüm ailesi); AV1 aynı yapaylıkları taşımak için bit
harcamak zorundadır. Bu, kodek değiştirmenin **kaynakta gerçek fazlalık
yokken neden zarar ettiğinin** fiziksel açıklamasıdır — ve `18-faz7-kapanis.md`
B-1'in *"hedef kalite kaynağın kalitesinin üstünde"* tespitinin kodekten
bağımsız olduğunu gösterir.

### 5.3 Kodlama süresi — AV1 ne kadar yavaş

**Ölçüm neden zor:** ana makinede ölçüm boyunca **başka ajanlar** koşuyordu;
yük ortalaması 53 ile 249 arasında dalgalandı (`uptime` ile izlendi). Mutlak
süreler bu yüzden **anlamsız**. Ölçüm buna göre kuruldu:

* H.264 ve AV1 **iç içe**, aynı turda peşi sıra koşuldu → yük ikisini de
  aynı şekilde etkiler,
* **3 tur × 2 bağımsız koşum** yapıldı,
* Sonuç **en düşük (min) süreden** okundu — en az kirlenmiş tur.
* Her iki koşumun da en temiz turu **aynı oranı** verdi; bu tesadüf değil.

**Araç zinciri eşitlendi:** ikisi de ffmpeg 9.0 (x264 + **SVT-AV1 4.2.0**,
`asm level: neon_i8mm`). Üretimdeki SVT-AV1 **v1.4.1** bu makinede
`asm level: c` (SIMD YOK) ile koşuyor ve **karşılaştırma için kullanılamaz**
— bkz. V-3b.

```
# koşum A                          # koşum B
{"tur":3,"run":"h264",  "s":7.49}  {"tur":3,"run":"h264",  "s":6.88}
{"tur":3,"run":"av1_p6","s":11.59} {"tur":3,"run":"av1_p6","s":10.67}
{"tur":3,"run":"av1_p8","s":8.23}  {"tur":3,"run":"av1_p8","s":7.21}
{"tur":3,"run":"av1_p10","s":4.98} {"tur":3,"run":"av1_p10","s":4.89}

{"OZET":"h264",   "min_s":7.49}    {"OZET":"h264",   "min_s":6.65}
{"OZET":"av1_p6", "min_s":11.59}   {"OZET":"av1_p6", "min_s":10.67}
{"OZET":"av1_p8", "min_s":8.23}    {"OZET":"av1_p8", "min_s":7.21}
{"OZET":"av1_p10","min_s":4.98}    {"OZET":"av1_p10","min_s":4.89}
```

| Kodlayıcı | min süre (A / B) | **× H.264** (A / B) | Çıktı baytı | Yorum |
|---|---:|---:|---:|---|
| **x264 `-preset medium -crf 23`** | 7,49 / 6,65 sn | **1,00×** | 1.067.935 | çapa |
| **SVT-AV1 `-preset 6 -crf 31`** | 11,59 / 10,67 sn | **1,55× / 1,60×** | **966.691** | en küçük çıktı, **~1,6 kat süre** |
| SVT-AV1 `-preset 8 -crf 31` | 8,23 / 7,21 sn | **1,10× / 1,08×** | 1.109.582 | **süre neredeyse eşit**, çıktı %15 büyük |
| SVT-AV1 `-preset 10 -crf 31` | 4,98 / 4,89 sn | **0,66× / 0,74×** | 1.043.676 | **H.264'ten HIZLI** |

**Sonuç — "AV1 yavaştır" bu araç zincirinde DOĞRU DEĞİL:**

> Modern SVT-AV1 (v4.2.0) ile AV1, x264 `medium`'a göre preset 6'da yalnız
> **~1,6 kat**, preset 8'de **neredeyse eşit**, preset 10'da ise
> **daha hızlı**. **Süre, AV1 kararında bloklayıcı değildir.**
>
> **AMA** bu, **v4.2.0** içindir. Üretimdeki **v1.4.1** bu makinede SIMD'siz
> koştuğu için ölçülemeyecek kadar yavaştı (V-3b) — yani "süre sorun değil"
> ifadesi **ffmpeg yükseltmesine bağlıdır** (§5.6).

### 5.4 KARAR ÖNERİSİ

> ## AV1 ŞİMDİ EKLENMESİN.
> **Gerekçe tek cümle:** AV1 çözmesi beklenen sorunu (B-1 — fayda kapısının
> hiçbir transcode'u geçirmemesi) **ölçüm sonucuna göre çözmüyor**; çözdüğü
> sanılan yer sentetik fixture'ın yanılttığı yerdi.

**Sırasıyla yapılması gereken:**

| Sıra | İş | Neden önce bu |
|---|---|---|
| **1** | **Hız denetimi düzeltilsin (B-1).** `targets.h264_primary.crf` sabit 23 yerine kaynağın kendi bitrate'ine/bpp'sine göre uyarlansın; ya da capped-CRF (`-maxrate`) eklensin — HLS merdiveninde aynı düzeltme **zaten yapıldı** (`video_decision.json` `hls.rate_control: capped_crf`), tek dosya yolunda **yapılmadı** | Bu düzeltilmeden hiçbir kodek kapıyı açamaz. Ölçüm: 1,169 Mbps kaynak → 2,04 Mbps çıktı |
| **2** | **`width_over_cap` kuralı gözden geçirilsin.** Bu kütüphanede tek tetikleyicisi olduğu dosyada sonuç her zaman "kapı attı" | `18-faz7-kapanis.md` §4.3: kuralı tetikleyen tek dosya var, o da kapıdan düşüyor |
| **3** | **B-8 (H.264 ↔ VP9) kapansın** | Üçüncü bir kodek, çözülmemiş bir çelişkinin üstüne eklenmemeli |
| **4** | **Sonra** AV1 yeniden değerlendirilsin — aşağıdaki sayısal tetikle | — |

### 5.5 SAYISAL TETİK — AV1 ne zaman kazandırır

Kapı `çıktı/kaynak ≤ 0,90` istiyor. AV1 denemesi ancak şunu sağlarsa kapıyı
açar:

```
(AV1/H.264 oranı) × (H.264 çıktı / kaynak)  ≤  0,90
```

Ölçülen AV1/H.264 oranları:

| Korpus | AV1/H.264 (aynı VMAF) | Bu orana göre H.264/kaynak ÜST SINIRI |
|---|---:|---:|
| **Gerçek içerik** (`10 (1).mp4`, 1080p) | **0,683** | **1,32** |
| Sentetik fixture (`video_16x9_1080p`) | 0,862 | **1,04** |

> ### TETİK
> **AV1 ikinci denemesi YALNIZ şu koşulda koşulsun:**
> **`width > max_width` VE H.264 çıktısı kaynağın 1,04 katından küçük.**
>
> `1,04` **muhafazakâr** sınırdır (kötümser sentetik ölçümden gelir).
> Gerçek içerikte ölçülen sınır `1,32`; aradaki fark **ölçülmemiş içeriğe
> karşı emniyet payıdır**. n=1 gerçek dosyayla `1,32`'ye dayanmak
> sorumsuzluk olur (§5.6).

**Tetiğin iki veri noktasında doğrulaması:**

| Dosya | H.264/kaynak | Tetik (≤1,04)? | AV1 gerçekten kapıyı açtı mı |
|---|---:|:--:|:--:|
| `video_16x9_1080p` (sentetik) | **0,944** | ✅ evet | ✅ **EVET** — AV1 `0,814×` ≤ 0,90 |
| `10 (1).mp4` (gerçek) | **1,760** | ❌ hayır | ❌ **HAYIR** — AV1 `1,202×` > 0,90 |

**Tetik iki durumu da doğru bildi.** Ölçülen iki noktada yanlış pozitif ve
yanlış negatif yok.

**İki ek koşul (her hâlükârda):**

1. **AV1 çıktısı da aynı fayda kapısından geçmeli** (`çıktı/kaynak ≤ 0,90`).
   Kapı gevşetilmez; AV1 çıktısı da kazandırmazsa **atılır**, kaynak korunur.
2. **AV1 CRF'i, H.264 hedefiyle AYNI VMAF'ı verecek şekilde seçilmeli** —
   kapıyı "AV1 ile açmak" için CRF yükseltmek **yasak**. §4.5 bunun neden
   önemli olduğunu ölçtü: canlı dosyada AV1 kapıyı **ancak CRF 40'ta**
   geçiyor (`0,706×`) ve orada **VMAF 85,40** — H.264'ün zaten yetersiz
   bulunan **90,19**'undan 4,8 puan, Faz 7 hedefi **93**'ten **7,6 puan**
   aşağıda. **Kapıyı kaliteyi düşürerek açmak, kriteri kurtarmak değil daha
   çok bozmaktır.**

### 5.6 AV1 uygulanmadan önce kapatılması ZORUNLU olanlar

| Ön koşul | Neden | Kaynak |
|---|---|---|
| **ffmpeg / SVT-AV1 yükseltmesi** | Bu belgedeki AV1 kazançları **SVT-AV1 v4.2.0** ile ölçüldü. Üretimde **v1.4.1** var — üç ana sürüm geride. Bugünkü üretim ffmpeg'i ile **bu kazançlar elde edilemez** | V-3 |
| **AV1 oynatma gerçek cihazda doğrulansın** (Safari/iOS dahil) | `video_decision.json` VP9'u **tam bu gerekçeyle** reddediyor: *"oynamayan bir video sıfır bayt tasarrufundan kötüdür"*. Bu belge **hiçbir tarayıcıda AV1 oynatmadı** | B-7, §5.7 |
| **Ölçüm ≥ 3 GERÇEK 1080p video ile tekrarlansın** | Gerçek içerikte **n=1**. Tek dosyaya dayanan bir kodek kararı, `18-faz7-kapanis.md`'nin sentetik korpusa dayanmasıyla aynı hatadır | V-2 |

### 5.7 AV1 eklenirse BİRİNCİL çıktı olmasın

`video_decision.json` `targets.h264_primary.why_h264_not_vp9`:

> *"VP9/WebM Safari'de `<video>` ile güvenilir oynamıyor … Ürün videosu B2B
> alıcının telefonunda oynamak zorunda; oynamayan bir video sıfır bayt
> tasarrufundan kötüdür."*

**Bu gerekçe AV1 için de geçerlidir ve bu belge onu ÖLÇMEDİ.** AV1 ancak
**ikincil `<source>`** olarak eklenebilir; `mp4/H.264` birincil kalır,
desteklemeyen tarayıcı ona düşer. Karar tablosundaki `targets.webm_fallback`
yer tutucusuyla **aynı desen**, yalnız kodek farklı.
---

## 6. Faz 7'nin durumu — bloklayıcı kalktı mı

> **`docs/reports/18-faz7-kapanis.md` bu belge tarafından DEĞİŞTİRİLMEDİ.**
> Aşağıdaki güncelleme burada yaşıyor.

### 6.1 B-6 (tek bloklayıcı) — **KAPANDI**

`18-faz7-kapanis.md` §8:

> | **B-6** | **VMAF ölçülemedi.** ffmpeg `libvmaf` olmadan derlenmiş. … | **YÜKSEK** | §5.2 | ✅ **EVET — tek bloklayıcı** |

ve §9.1:

> **Faz 7'yi ✅ KANITLI yapmak için gereken TEK şey: B-6 — VMAF ölçüm aracı.**

**Araç getirildi (§1.3'te kanıtı var), 7 fixture'ın 7'sinde de VMAF ölçüldü
(§3.3), canlı kütüphanenin tek TRANSCODE adayında da ölçüldü (§3.7).**
**B-6 kapandı.** §9.1'in **B yolu** (ayrı VMAF aracı, motor kodu değişmeden)
koştu; A yolu (imaj rebuild) ve C yolu (kriteri değiştirmek) gerekmedi.

### 6.2 K-8 karnesi yeniden

`18-faz7-kapanis.md` §1 karnesi K-8'i ⛔ **ARAÇ YOK** diye işaretlemişti.
Ölçüldüğüne göre yeniden değerlendirilebilir. **Cevap tek kelime değil:**

| Okuma | Sonuç | Gerekçe |
|---|---|---|
| **Teslim edilen çıktılar** (fayda kapısından geçenler) | ✅ **KANITLI — geçiyor** | Kapıdan geçen tek çıktı `video_bloated_720p_8m`: **VMAF 97,44 ≥ 93**. Kapıdan geçmeyen hiçbir çıktı diske yazılmıyor, dolayısıyla teslim edilmiyor (§3.5) |
| **TRANSCODE kararı alan tüm dosyalar** (kapı öncesi) | ❌ **GEÇMİYOR** | 1080p sınıfı: fixture **87,78** · canlı dosya **90,21** — ikisi de < 93 (§3.4, §3.7) |
| **`Senaryo08SisikVideoKuculur` E2E senaryosu** | ✅ **GEÇİYOR** | Senaryonun sorduğu dosya tam olarak `video_bloated_720p_8m`; **97,44 ≥ 93** |
| **Canlı kütüphane** | ⚠ **BOŞ KÜMEDE GEÇİYOR** | Canlı kütüphanenin 4 transcode adayının **4'ünde de** kapı çıktıyı atıyor (`18-faz7-kapanis.md` §5.3). Yani bugün üretimde **teslim edilen tek bir transcode çıktısı yok**; kriter boş bir kümede tutuyor (§3.5) |

**Dürüst özet:** *"Fayda kapısı ihlali sıfır **ve** VMAF hedefleri tutuyor"*
çıkış kriteri, **bugünkü hâliyle kapının koruduğu kapsamda tutuyor**. Kapı
olmasaydı tutmazdı. Bu bir tesadüf değil, kapının işlevidir: bayt kazandırmayan
çıktıyı atarken, en kötü kaliteli çıktıyı da atıyor — çünkü ikisinin nedeni
aynı (1080p → 1280 küçültmesi hem bayt kazandırmıyor hem kalite düşürüyor).

**Kapının kapsamı dışında kalan gerçek bir açık var (V-1):** 1080p sınıfında
CRF 23 çıktısı VMAF 93'ü tutmuyor (90,21 / 87,78). §3.7 bunun sebebinin
**politika değil ayar** olduğunu gösterdi: gerçek dosyada salt küçültmenin
tavanı **98,53**, yani `max_width: 1280` yürürlükteyken de 93 erişilebilir.
Bugün bu bir teslim sorunu **değildir** (kapı çıktıyı atıyor), ama
`width_over_cap` kuralının hiçbir işe yaramaması demektir — `18-faz7-kapanis.md`
**B-1**'in kökü budur. **Çözümün AV1 OLMADIĞI §5'te ölçümle gösterildi**;
çözüm hız denetimindedir (§5.4, sıra 1).

### 6.3 Motor kodunda ne değişmesi gerekir — HİÇBİR ŞEY (bu belge kapsamında)

`18-faz7-kapanis.md` §9.1 şunu yazıyordu:

> *"Yol A ya da B seçilirse: `measure_quality` **hiç değiştirilmeden** VMAF
> döndürmeye başlar (`transcode.py:502-516`)"*

**Doğrulandı.** Bu belgedeki VMAF filtre zinciri, `measure_quality()`'nin
`vmaf_available()` True gördüğünde kuracağı zincirin aynısıdır (§1.4). Kodun
değişmesi gerekmiyor; **`libvmaf`'lı bir ffmpeg'in `PATH`'te olması yetiyor.**

Testlerin durumu (bu belge test dosyalarına dokunmadı):

| Test | Bugünkü davranış | libvmaf'lı ffmpeg altında |
|---|---|---|
| `test_video_transcode.py::GercekTranscode::test_kalite_olculebiliyor_ama_VMAF_YOK` | SSIM/PSNR dalını doğruluyor | Gövdesi `if not T.vmaf_available():` ile korunuyor → **kırılmaz**, ama **adı yanlış olur** ve VMAF dalını doğrulamaz |
| `test_e2e_scenarios.py::Senaryo08SisikVideoKuculur::test_VMAF_OLCULEMEDI` | `skipTest(...)` | Hâlâ skip eder — **ölçüm artık var, skip mesajı yanlış olur** |

Bu iki test **bu belge tarafından değiştirilmedi** (görev `.py` dosyalarına
dokunmayı yasaklıyor). §7.2'de devir görevi olarak yazılı.

### 6.4 `18-faz7-kapanis.md`'nin diğer açık bulguları — durum

| # | Bulgu | Bu belge ne yaptı |
|---|---|---|
| **B-1** | H.264 hedefi bu kütüphanede hiç kazanmıyor | **Genişletildi ve niceliklendirildi.** Fixture korpusunda da 7/7'nin 6'sında kapı H.264'ü eliyor (§3.5). AV1 ölçümü bunun **çözümünü** sayıya döktü (§4, §5) |
| **B-6** | VMAF ölçülemedi | ✅ **KAPANDI** (§1, §3) |
| B-2, B-3, B-4, B-5, B-7, B-8, B-9, B-10, B-11 | — | **DOKUNULMADI**, durumları değişmedi |

---

## 7. Bulgular ve devir görevleri

### 7.1 Yeni bulgular

| # | Bulgu | Şiddet | Kanıt |
|---|---|---|---|
| **V-1** | **CRF 23, 1080p sınıfında VMAF 93'ü tutturmuyor.** Teslim edilecek çıktı gerçek dosyada **90,21**, sentetik fixture'da **87,78**. Kaybın kaynağı **politika değil ayar**: aynı gerçek dosyada salt küçültmenin tavanı **98,53** — yani `max_width: 1280` yürürlükteyken de 93 erişilebilir, CRF 23 fazla agresif. **Fayda kapısı bu çıktıyı zaten attığı için kullanıcıya ulaşmıyor**, ama `width_over_cap` kuralı böylece hiçbir işe yaramıyor (B-1'in kökü). | **YÜKSEK** | §3.4, §3.7 |
| **V-2** | **Faz 7 fixture korpusunun 7'si de sentetiktir** (`testsrc2`). Kodek karşılaştırması ve kalite eşikleri sentetik desende yanıltır; T-016 bu yüzden gerçek içerikte tekrarlandı ve **sonuç değişti** (§4.5). Kalite/bayt eşiği belirleyen hiçbir karar yalnız bu korpusa dayandırılmamalı. | **YÜKSEK** | `scripts/gen_fixtures_video.sh`, §4.5 |
| **V-3** | **Üretimde AV1 kodlayıcısı VAR ama SÜRÜMÜ ESKİ.** `libsvtav1`/`libaom-av1`/`librav1e` üçü de derlenmiş — imaj değişikliği *gerekmez* sanılabilir. Ama üretimdeki **SVT-AV1 v1.4.1**, ölçümün yapıldığı **v4.2.0**'dan üç ana sürüm geride. Bu belgedeki AV1 kazançları v4.2.0 ile ölçüldü ve **bugünkü üretim ffmpeg'i ile elde EDİLEMEZ**. AV1 kararı, ffmpeg/SVT-AV1 yükseltmesini de içerir. | **YÜKSEK** | §1.1, §4.2 |
| **V-3b** | **Bu makinede (arm64) üretim SVT-AV1'i SIMD'siz koşuyor** — `[asm level selected : up to c]`, yani saf C. ffmpeg 9.0 imajı aynı makinede `up to neon_i8mm` seçiyor. Buradaki AV1 **süre** ölçümleri bu yüzden üretim donanımını (x86 + AVX2/AVX512) **temsil etmez**; süre kıyası eşit araç zinciriyle (§5.3) yapıldı. | ORTA | §5.3 |
| **V-4** | **`vmaf_available()` üretimde hâlâ False.** Bu belge VMAF'ı **dış bir imajla** ölçtü; motorun kendi `measure_quality()`'si üretimde hâlâ SSIM/PSNR'a düşüyor. Ölçüm CI'a bağlı değil, elle koşuluyor. | ORTA | §3.6 |
| **V-5** | **İki test artık yanlış şey söylüyor.** `test_kalite_olculebiliyor_ama_VMAF_YOK` (adı) ve `Senaryo08…::test_VMAF_OLCULEMEDI` (skip mesajı: *"VMAF ≥ 93 kapısı KANIT YOK durumundadır"*) — **ölçüldü, 97,44 ile geçiyor**. | DÜŞÜK | §6.3 |

### 7.2 Devir görevleri (bu belge hiçbirini yapmadı)

| # | İş | Neden bu belge yapmadı |
|---|---|---|
| **Y-1** | **KARAR:** 1080p sınıfında ne yapılacak — (a) `max_width` 1920'ye çıkarılsın mı, (b) VMAF kriteri "kapıdan geçen çıktılar için" diye daraltılsın mı, (c) 1080p için AV1'e geçilsin mi (§5). **İmza gerektirir.** | politika JSON'una dokunmak yasak; ayrıca teknik değil karar işi |
| **Y-2** | AV1 ikincil çıktı kararı ve `video_decision.json` `targets.av1_secondary` girdisi (§5.4'teki sayısal tetikle) | politika JSON'una dokunmak yasak |
| **Y-3** | `libvmaf`'lı ffmpeg'in üretim imajına girmesi (`docker/backend.Dockerfile`) — **yalnız ölçüm/CI için**, teslim için gerekmez | `docker/` dosyalarına dokunmak yasak |
| **Y-4** | V-5'teki iki testin adı ve gövdesi güncellensin | `.py` dosyalarına dokunmak yasak |
| **Y-5** | Fixture korpusuna **en az 3 gerçek video** eklensin (V-2). Kalite/bayt eşiği kararları sentetik desende alınmamalı | fixture üretmek görev kapsamında değil |
---

## 8. Tekrarlanabilirlik — koşulan tüm komutlar

```bash
# ── 0. VMAF araci ────────────────────────────────────────────────────────
docker pull linuxserver/ffmpeg:latest
docker run --rm --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner -version
docker run --rm --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner -filters | grep -iE 'libvmaf|ssim|psnr'
docker run --rm --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest -hide_banner -h filter=libvmaf

# ── 1. Uretim konteynerinin durumu (DEGISMEDI) ──────────────────────────
docker exec istoc-dev-backend-1 sh -c \
  'ffmpeg -hide_banner -version | tr " " "\n" | grep -E "enable-(libaom|libsvtav1|librav1e|libvmaf|libx264|libvpx)"'
docker exec istoc-dev-backend-1 sh -c 'ffmpeg -hide_banner -encoders | grep -iE "av1|libx264|vp9"'

# ── 2. Fixture envanteri ────────────────────────────────────────────────
find . -type f \( -name "*.mp4" -o -name "*.mov" -o -name "*.webm" -o -name "*.mkv" \) | grep fixtures
grep -c "testsrc2" scripts/gen_fixtures_video.sh     # -> 7 (hepsi sentetik)

# ── 3. Kunye + karar (boru hattinin kendi kodu, SALT OKUMA) ─────────────
docker exec istoc-dev-backend-1 sh -c 'cd /home/frappe/frappe-bench/apps/tradehub_core && python -c "
import json,glob,os
from tradehub_core.media.pipeline.video import probe as P, decision as D
for f in sorted(glob.glob(\"tradehub_core/tests/fixtures/media/video/*.mp4\")):
    pr=P.probe(f); d=D.decide(pr)
    print(json.dumps({\"file\":os.path.basename(f),\"size\":os.path.getsize(f),\"w\":pr.width,\"h\":pr.height,
      \"dur\":round(pr.duration_s,2),\"fps\":round(pr.fps,2),\"codec\":pr.video_codec,\"pix\":pr.pix_fmt,
      \"vbr\":pr.video_bitrate_bps,\"aud\":pr.audio_codec,\"action\":d.action,\"rule\":d.rule_id}))
"'

# ── 4. H.264 ciktilari (boru hatti, uretim ffmpeg 5.1.9, kapi KAPALI) ───
docker exec istoc-dev-backend-1 sh -c 'rm -rf /tmp/t072out && mkdir -p /tmp/t072out && cd /home/frappe/frappe-bench/apps/tradehub_core && python -c "
import json,glob,os
from tradehub_core.media.pipeline.video import probe as P, transcode as T
for f in sorted(glob.glob(\"tradehub_core/tests/fixtures/media/video/*.mp4\")):
    b=os.path.basename(f); pr=P.probe(f)
    r=T.transcode(f,\"/tmp/t072out/h264_\"+b,facts=pr,enforce_benefit_gate=False)
    print(json.dumps({\"file\":b,\"src\":r.src_bytes,\"out\":r.out_bytes,\"saving\":round(r.saving_ratio,4),
      \"wall\":round(r.wall_s,2),\"cmd\":\" \".join(r.cmd)}))
"'
mkdir -p /tmp/t072/src /tmp/t072/out
cp tradehub_core/tests/fixtures/media/video/*.mp4 /tmp/t072/src/
docker cp istoc-dev-backend-1:/tmp/t072out/. /tmp/t072/out/

# ── 5. VMAF (7 fixture) ─────────────────────────────────────────────────
# her fixture icin, REF_W/REF_H = kaynagin kendi cozunurlugu:
docker run --rm -v /tmp/t072:/w --entrypoint /usr/local/bin/ffmpeg linuxserver/ffmpeg:latest \
  -hide_banner -i /w/src/<F> -i /w/out/h264_<F> \
  -filter_complex "[1:v]scale=<REF_W>:<REF_H>:flags=bicubic[dist];[dist][0:v]libvmaf" -f null -

# ── 6. 1080p kaybinin ayristirilmasi ────────────────────────────────────
# A) yalniz kodlama:
  -filter_complex "[0:v]scale=1280:720:flags=bicubic[ref];[1:v][ref]libvmaf"
# B) yalniz kucultme (ayni dosya iki kez girdi):
  -filter_complex "[1:v]scale=1280:720:flags=bicubic,scale=1920:1080:flags=bicubic[dist];[dist][0:v]libvmaf"

# ── 7. SSIM/PSNR (boru hattinin kendi measure_quality()'si, 5.1.9) ──────
docker exec istoc-dev-backend-1 sh -c 'cd /home/frappe/frappe-bench/apps/tradehub_core && python -c "
import json,glob,os
from tradehub_core.media.pipeline.video import transcode as T
print(\"vmaf_available() =\", T.vmaf_available())
for f in sorted(glob.glob(\"tradehub_core/tests/fixtures/media/video/*.mp4\")):
    b=os.path.basename(f); k=T.measure_quality(f, \"/tmp/t072out/h264_\"+b)
    print(json.dumps({\"file\":b,\"ssim\":k.get(\"ssim\"),\"psnr\":k.get(\"psnr\"),\"vmaf\":k.get(\"vmaf\")}))
"'

# ── 8. AV1 vs H.264 taramasi (ikisi de ffmpeg 9.0) ──────────────────────
# H.264 capa (boru hattinin hedef parametreleri):
  -map 0:v:0 [-map 0:a:0? -c:a aac -b:a 128k -ac 2 -ar 48000 | -an] \
  -vf "scale='min(1280,iw)':-2" -c:v libx264 -profile:v high -level:v 4.0 \
  -preset medium -crf 23 -pix_fmt yuv420p -g <2*fps> -keyint_min <2*fps> \
  -sc_threshold 0 -movflags +faststart
# AV1 taramasi, crf in {25,30,35,40,45}:
  -vf "scale='min(1280,iw)':-2" -c:v libsvtav1 -preset 6 -crf <CRF> \
  -pix_fmt yuv420p -g <2*fps> -movflags +faststart

# ── 9. Temiz sure olcumu (URETIM ffmpeg 5.1.9, 3 tekrar) ────────────────
docker exec istoc-dev-backend-1 sh -c '/usr/bin/time -f "%e s" ffmpeg -y -loglevel error -i <SRC> ...'

# ── 10. Temizlik ────────────────────────────────────────────────────────
docker exec istoc-dev-backend-1 rm -rf /tmp/t072out /tmp/t072live /tmp/t072lv /tmp/t072tm
rm -rf /tmp/t072
```

**Yardımcı betikler** (ana makinede `/tmp/t072/` altında, repoya **yazılmadı**):
`vmaf.sh` (T-072 VMAF), `sweep.sh` (fixture AV1 taraması), `ssim.sh`
(SSIM/PSNR), `live.sh` (canlı dosya VMAF ayrıştırması),
`live1080_av1.sh` (canlı dosya AV1 taraması), `bench9.py` (süre ölçümü),
`analyze.py` (aynı-VMAF interpolasyonu).

### 8.1 Ortam notu — ölçümü etkileyen koşullar

| Koşul | Etkisi |
|---|---|
| Ana makinede **başka ajanlar** koşuyordu; yük ortalaması **12 ile 249** arasında dalgalandı | **Süreler** etkilendi → §5.3 iç içe koşularak ve min alınarak ölçüldü. **Bayt ve VMAF değerleri yükten etkilenmez** |
| `istoc-dev-backend-1` ölçüm sırasında **iki kez yeniden başlatıldı** (başka ajanlar) | Bir süre ölçümü SIGKILL ile düştü (`exit 137`) ve tekrarlandı. Konteyner `/tmp`'sindeki çıktılar ana makineye **önceden kopyalanmıştı**, veri kaybı olmadı |
| Ana makine **arm64** (Apple Silicon) | Üretim SVT-AV1 v1.4.1 burada **SIMD'siz** koşuyor (V-3b). Süre kıyası bu yüzden eşit araç zinciriyle (ffmpeg 9.0 / SVT-AV1 4.2.0, NEON) yapıldı |
| `docker/docker-compose.yml`'a **dokunulmadı** | Paralel bir ajan aynı sırada oraya MinIO servisi ekliyordu; çakışma olmadı. Ölçüm standalone `docker run` + `-v` ile yapıldı |
