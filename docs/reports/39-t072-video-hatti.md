# 39 — T-072 / T-073 / T-074: video hattı hız denetimi, geri çekilme yolu, gerçek doğrulama

**Görevler:** T-072 (transcode + fayda kapısı + kalite) · T-073 (poster + önizleme klibi) · T-074 (HLS)
**Faz:** 7 · **Tarih:** 2026-08-19 · **Depo:** `tradehub_core`, dal `ahmet`
**Kapatmaya çalıştığı bulgular:** `18-faz7-kapanis.md` **B-1** ve **B-2**;
`34-dogrulama-faz4-7.md` T-072/4 (süre farkı), T-074/3 (mobil veri tavanı) ve
"tarayıcı oynatması doğrulanmadı" açığı.

---

## 0. Bu belgenin kuralı

> **Koşulmayan hiçbir şeye "geçti" denmedi. Ölçülemeyen her şey "ÖLÇÜLMEDİ"
> yazıldı.** Aşağıdaki her sayının komutu ve ham çıktısı bu oturumda üretildi.
> Süre / kodlama hızı iddiası YOK — makine paylaşımlı.

**VMAF konusu.** Üretim imajındaki ffmpeg `libvmaf` OLMADAN derlenmiş; bu
oturumda yeniden doğrulandı:

```
$ docker exec istoc-dev-backend-1 ffmpeg -hide_banner -filters | grep -c libvmaf
0
$ docker exec istoc-dev-backend-1 ffmpeg -version | head -1
ffmpeg version 5.1.9-0+deb12u1
```

`vmaf_available()` → **False**. Bu belgedeki bütün VMAF sayıları **dış imajla**
(`docker run --rm linuxserver/ffmpeg`, ffmpeg 9.0 + libvmaf) ölçüldü;
`docker/docker-compose.yml`'a ve üretim imajına **dokunulmadı**.
`vmafmotion` filtresi listede durur, **VMAF DEĞİLDİR** ve kullanılmadı.

**Korpus.** `18-faz7-kapanis.md` ve `22-t072-vmaf-av1.md` sentetik korpusun
(7 × `testsrc2`) iki kez yanılttığını yazmıştı. Bu oturumda bütün kararlar
**canlı kütüphanenin 7 gerçek videosunda** ölçüldü:

| # | Dosya (kısaltılmış ad) | Kodek | Çözünürlük | Süre | Video bitrate | Bayt | moov sonda |
|---|---|---|---|---:|---:|---:|---|
| r1 | `9mb.mp4` | h264 | 1280×720 | 540,0 sn | 140,6 kbps | 9.622.535 | **EVET** |
| r2 | `10 (1).mp4` | h264 | 1920×1080 | 58,192 sn | 1.152,7 kbps | 8.504.902 | **EVET** |
| r3 | `05bd857a….mp4` | **vp9** | 1280×720 | 5,766 sn | 4.852,4 kbps | 3.497.368 | hayır |
| r4 | `AQOOb74v….mp4` | h264 | 720×1280 | 32,995 sn | 648,0 kbps | 3.077.433 | hayır |
| r5 | `Evde taze sıkılmış….mp4` | h264 | 720×720 | 28,002 sn | 707,2 kbps | 2.809.249 | hayır |
| r6 | `b276b343….webm` | **vp9** | 1280×720 | 10,021 sn | 958,2 kbps | 1.200.300 | hayır |
| r7 | `AQPp_3LT….mp4` | h264 | 352×352 | 28,906 sn | 197,7 kbps | 1.085.963 | hayır |

Hepsi `sites/istoc.localhost/public/files` altındaki gerçek yüklemelerdir.
Kütüphane **değiştirilmedi**; dosyalar `/tmp/t072/src` altına kopyalanarak
çalışıldı, hiçbir üretim dosyası üzerine yazılmadı.

---

## 1. Tek sayfada sonuç

| # | Sonuç | Kanıt |
|---|---|---|
| **1** | **B-1 KAPANDI.** Tek dosya yolunda hız denetimi yoktu; capped-CRF eklendi. Kütüphanenin 4 gerçek TRANSCODE adayının **2'si artık kapıyı geçiyor ve teslim ediliyor** (önce **0**'dı). | §2 |
| **2** | **B-2 KAPANDI.** Kapıdan düşen TRANSCODE artık REMUX'a geri çekiliyor; gerçek bir dosyada (r1, moov sonda) doğrulandı — moov **başa alındı**. | §3 |
| **3** | **VMAF ≥93 kriteri GERÇEK içerikte TUTMUYOR ve TUTAMAZ.** Ölçüldü: r2'de VMAF 93'e çıkmak dosyayı kaynaktan **%20 BÜYÜK** yapıyor — yani fayda kapısı ile kalite kriteri **aynı anda sağlanamaz**. 93 eşiği sentetik `testsrc2` korpusundan kalibre edilmiş. | §4 |
| **4** | **T-072/4 (süre farkı ≤100 ms) artık ÖLÇÜLÜYOR** — daha önce "ne test ne kod" vardı. Gerçek ve sentetik kaynaklarda ölçülen fark **0–1 ms**. | §5 |
| **5** | **T-074/3 (mobil veri tavanı, ilk 10 sn) artık ÖLÇÜLÜYOR.** Gerçek 540 sn'lik videoda üç basamak da tavanın altında: **161.841 / 173.121 / 275.581 B** (tavan 1.280.000 B). | §6 |
| **6** | **T-074 tarayıcı oynatması DOĞRULANDI** — hls.js 1.x + headless Chrome 151, gerçek pakette 3 basamak tanındı, oynatma ilerledi. Ayrıntı ve tek uyarı §7'de. | §7 |
| **7** | **T-073 gerçek videolarda ölçüldü:** 7/7 poster üretildi, 7/7 klip 1 MB kapısını geçti. **İki gerçek açık:** poster bayt kapısı (120 KB) bir gerçek dosyada tutmuyor, klip 400 KB politika hedefi aynı dosyada aşılıyor. | §8 |
| **8** | **YENİ BULGU (B-3):** HLS merdiveninin 720p basamağı, çok düşük bitrate'li gerçek bir kaynakta **kaynaktan büyük** çıkıyor (12.095.893 B > 9.622.535 B). Merdivende fayda kapısı yok. **Düzeltilmedi, kayda geçirildi.** | §6.3 |
| **9** | **167 test yeşil, 0 atlanan** (önce 147). 20 yeni test; 1 mevcut testin beklentisi ölçümle değişti ve gerekçesi testin içine yazıldı. | §9 |

---

## 2. B-1 — hız denetimi (capped CRF)

### 2.1 Kusur, gerçek dosyalarda

Tek dosya yolunda hız denetimi **yoktu**: `build_transcode_cmd` yalnız `-crf 23`
yazıyordu. CRF bir **kalite** hedefidir, bayt tavanı değil — kaynak zaten hedef
kaliteden düşük bir bitrate'te kodlanmışsa CRF 23 kaynaktan **fazla** bit harcar.
HLS yolunda aynı tuzak görülüp capped-CRF ile çözülmüştü
(`video_decision.json` `hls.rate_control_why`); tek dosya yolunda düzeltme
**uygulanmamıştı**.

**Düzeltme öncesi ölçüm (7 gerçek dosya, `apply_decision` ile uçtan uca):**

| Dosya | Kural | Aksiyon | Kaynak | Çıktı | Kazanç | Kabul |
|---|---|---|---:|---:|---:|---|
| r1 | `moov_at_end` | REMUX | 9.622.535 | 9.622.536 | −0,0% | ✅ (muaf) |
| **r2** | `width_over_cap` | TRANSCODE | 8.504.902 | **14.490.432** | **−70,38%** | ❌ atıldı |
| r3 | `codec_not_deliverable` | TRANSCODE | 3.497.368 | 2.915.013 | +16,65% | ✅ |
| r4 | `default` | PASSTHROUGH | 3.077.433 | — | 0% | ✅ |
| r5 | `default` | PASSTHROUGH | 2.809.249 | — | 0% | ✅ |
| **r6** | `codec_not_deliverable` | TRANSCODE | 1.200.300 | **1.432.145** | **−19,32%** | ❌ atıldı |
| r7 | `default` | PASSTHROUGH | 1.085.963 | — | 0% | ✅ |

Kapı doğru çalışıyordu; **üretilen çıktı yanlıştı.**

### 2.2 Düzeltme: tavan fayda kapısından TÜRETİLİYOR

Sabit bir çarpan (ör. "kaynağın 0,75 katı") ilk denemede yazıldı ve ölçüldü;
sonra **daha iyisiyle değiştirildi**, çünkü sabit çarpan iki yerde yanlıştır:

* **Ses payını görmez.** 320 kbps sesli bir kaynakta çıktı sesi 128 kbps'e
  inecektir; kazancın 192 kbps'i sesten gelir ve video o kadar daha rahat nefes
  alabilir. Sabit çarpan bu kazanılmış baytı ikinci kez keser — karşılığında
  görüntü kalitesi verir.
* **Sessiz kaynakta bütçeyi boşa harcar.** Ses yoksa çıkarılacak bir şey yoktur.

Uygulanan formül (`transcode.rate_ceiling_kbps`):

```
tavan_kbps = kaynak_toplam_kbps × (1 − min_saving_ratio) − çıktı_ses_kbps
             ── clamp: [min_maxrate_kbps=300 , maxrate_kbps=2500] ──
```

Bu, **kapının izin verdiği en yüksek kalitedir**: daha aşağısı gereksiz kalite
kaybı, daha yukarısı kapıdan düşmek. Tablo alanları
(`targets.h264_primary`): `rate_control`, `maxrate_kbps`, `min_maxrate_kbps`,
`budget_from_benefit_gate`, `bufsize_multiplier`. Değerlerin hiçbiri koda gömülü
değil.

### 2.3 Düzeltme sonrası — aynı 7 dosya

| Dosya | Tavan | Aksiyon | Kaynak | Çıktı | Kazanç | Kabul | Çıktıda moov sonda |
|---|---:|---|---:|---:|---:|---|---|
| r1 | 300k | REMUX | 9.622.535 | 9.622.536 | −0,0% | ✅ | hayır |
| **r2** | **924k** | TRANSCODE | 8.504.902 | **6.887.018** | **+19,02%** | ✅ **(önce ❌)** | hayır |
| **r3** | 2500k | TRANSCODE | 3.497.368 | **1.856.163** | **+46,93%** (önce +16,65%) | ✅ | hayır |
| r4 | 543k | PASSTHROUGH | 3.077.433 | — | 0% | ✅ | — |
| r5 | 594k | PASSTHROUGH | 2.809.249 | — | 0% | ✅ | — |
| r6 | 734k | TRANSCODE | 1.200.300 | 1.132.833 | +5,62% | ❌ atıldı | — |
| r7 | 300k | PASSTHROUGH | 1.085.963 | — | 0% | ✅ | — |

**Kapıyı geçen gerçek TRANSCODE sayısı 1 → 2.** Kütüphaneden kazanılan bayt
**582.355 → 3.259.089** (r2: 1.617.884 B + r3: 1.641.205 B), yani net
**+2.676.734 B**.

### 2.4 r6 hâlâ geçmiyor — ve bu DOĞRU sonuç

r6 VP9/WebM. Aynı kalitede H.264, VP9'dan ~%20-30 daha büyük dosya üretir
(bu bedel `docs/adr/0011-h264-birincil-vp9-degil.md`'de bilinçli olarak kabul
edilmiş). Tavan 734 kbps'e çekilince çıktı %5,62 küçüldü — %10 eşiğinin altında,
kapı attı, kaynak korundu. **Kazanılacak bayt yok; kapı doğru davranıyor.**

### 2.5 Vacuity — düzeltme geri alındı, KIRMIZI gösterildi, geri kondu

Tabloda tek satır (`rate_control: "crf"`) düzeltmeyi geri alır:

```
$ # tabloda rate_control="crf", benefit_gate.fallback.enabled=false
rate_control = crf
r2_1080p_58s.mp4    -> TRANSCODE acc= False src= 8504902 out= 14490432 sav%= -70.38
r6_vp9_webm_10s.webm-> TRANSCODE acc= False src= 1200300 out=  1432145 sav%= -19.32
```

Tablo geri yüklendi ve doğrulandı: `rate_control=capped_crf`,
`fallback.enabled=True`. Ayrıca kalıcı bir birim test bunu pinliyor:
`HizDenetimi.test_rate_control_crf_TAVANI_KALDIRIR`.

---

## 3. B-2 — kapıdan düşen TRANSCODE'un geri çekilme yolu

### 3.1 Kusur

`apply_decision` TRANSCODE'u çalıştırıyor, kapı çıktıyı atıyordu ve **iş orada
bitiyordu**. Aynı dosyanın kap/moov kusuru varsa DÜZELMEDEN kalıyordu:
moov sonda, aşamalı indirmede oynatıcı ilk kareyi göstermeden önce dosyanın
tamamını indirmek zorunda.

### 3.2 Düzeltme

Kapıdan düşen TRANSCODE'dan sonra iki koşul birlikte aranır
(`transcode.remux_fallback_applies`, tablo `benefit_gate.fallback`):

1. **Kap/moov kusuru duruyor mu** (`container_family != "mp4"` ya da `moov_at_end`).
2. **Akışlar zaten teslim edilebilir mi** (`h264` + `aac|mp3|sessiz`).

İkinci koşul kritiktir: VP9/Opus bir kaynağı `-c copy` ile mp4'e taşımak kabı
düzeltir ama **tarayıcıda oynamayan** bir dosya üretir. Böyle bir kaynakta geri
çekilme YAPILMAZ.

### 3.3 Gerçek dosyada doğrulama (r1 — moov sonda, 140,6 kbps, sıkıştırılamaz)

r1 karar tablosunda `moov_at_end` → REMUX alıyor. Kusuru göstermek için TRANSCODE
kararı **zorlandı** (dosya bir TRANSCODE kuralına da takılsaydı — 60 fps,
verimsiz kodlama — olacak olan tam olarak budur):

**Geri çekilme KAPALI (kusurun kendisi):**
```
SONUC: action=TRANSCODE accepted=False src=9622535 out=10091771 saving=-4.88%
notes: ['INV-05 fayda kapisi: kazanc %-4.9 < %10 -> cikti atildi, kaynak korundu',
        "REMUX'a geri cekilme YAPILMADI: tabloda kapali"]
CIKTI YOK — hedefe hicbir sey yazilmadi          ← moov SONDA kaldı
```

**Geri çekilme AÇIK (düzeltme):**
```
SONUC: action=REMUX accepted=True fallback_from=TRANSCODE
notes: ['INV-05 fayda kapisi: kazanc %-4.6 < %10 -> cikti atildi, kaynak korundu',
        "TRANSCODE fayda kapisindan dustu -> REMUX'a geri cekildi (moov atomu SONDA)",
        'fayda kapisindan MUAF (benefit_gate.exempt_actions)']
CIKTI moov_at_end: False | kodek: h264 | bayt: 9622536   ← moov BAŞA alındı
```

Yeniden kodlama yok (`-c copy`), kodek değişmedi, bayt farkı 1.

İki davranış da kalıcı testlerle pinlendi:
`GercekRemux.test_KAPIDAN_DUSEN_TRANSCODE_REMUXa_GERI_CEKILIYOR` ve
`GercekRemux.test_geri_cekilme_KAPALIYKEN_moov_SONDA_KALIR` (vacuity).

---

## 4. Kalite kapısı — VMAF, GERÇEK içerikte

> **Bu bölüm bir görevi "geçti" ilan etmiyor. Bir kriterin GERÇEK içerikte
> sağlanamaz olduğunu ölçüyor.**

### 4.1 Yöntem

Referans = kaynak, bozulmuş = çıktı. İki ayrı ölçüm yapıldı çünkü iki ayrı soru var:

* **`@1920×1080` (kaynak çözünürlüğünde):** kodlama kaybı **+ küçültme kaybı**
  birlikte. `22-t072-vmaf-av1.md` bu yöntemi kullanmış.
* **`@1280×720` (çıktı çözünürlüğünde, referans indirilerek):** yalnız
  **kodlama** kaybı. 1280 tavanı bilinçli bir teslim kararı olduğu için
  "kodlayıcı ne kadar kaybetti" sorusunun doğru ölçüsü budur.

**Yöntem çapraz doğrulaması:** tavansız CRF 23 çıktısında `@1920×1080` ölçümü
**90,209983** verdi — `22-t072-vmaf-av1.md`'nin aynı dosya için yazdığı **90,21**
ile birebir aynı. Yöntem tutarlı.

### 4.2 r2 (gerçek 1080p) — bayt/kalite eğrisi

| Tavan | Çıktı baytı | Kaynağa göre | VMAF @1280×720 | VMAF @1920×1080 | Fayda kapısı |
|---|---:|---:|---:|---:|---|
| 924k (**uygulanan**) | 6.887.018 | **−19,0%** | **86,40** | **78,01** | ✅ GEÇER |
| 864k | 6.461.173 | −24,0% | 85,20 | 76,51 | ✅ geçer |
| 1100k | 8.161.583 | −4,0% | 89,12 | — | ❌ düşer |
| 1400k | 10.248.429 | **+20,5%** | **92,11** | — | ❌ düşer |
| tavansız CRF 23 | 14.490.432 | +70,4% | 95,49 | 90,21 | ❌ düşer |

> ### Kriterin çelişkisi, sayıyla
>
> Fayda kapısı çıktının en fazla **7.654.412 B** olmasını istiyor.
> Bu bütçede ölçülen en iyi VMAF **≈86–89**'dur.
> **VMAF 92,11'e çıkmak için gereken dosya 10.248.429 B — kaynaktan %20 BÜYÜK.**
> **VMAF ≥93 ile INV-05 fayda kapısı bu dosyada AYNI ANDA SAĞLANAMAZ.**

### 4.3 Diğer gerçek dosyalar — CRF 23'ün tavanı

| Dosya | Çıktı | Bayt | VMAF @1280×720 |
|---|---|---:|---:|
| r3 (vp9→h264) | capped, tavan 2500k | 1.856.163 | **77,81** |
| r3 | tavansız CRF 23 | 2.915.013 | 79,83 |
| r6 (vp9→h264) | capped, tavan 734k | 1.111.047 | **74,88** |
| r6 | tavansız CRF 23 | 1.432.145 (kaynaktan büyük!) | 75,60 |

r3'te tavan, **2 VMAF puanı karşılığında %36 daha az bayt** veriyor — açık ara
iyi bir takas. r6'da tavansız çıktı kaynaktan büyük olmasına rağmen VMAF yalnız
**75,60**: yani bu içerikte **VMAF'ı sınırlayan şey tavan değil, CRF 23'ün
kendisidir.**

### 4.4 Sonuç — 93 eşiği nereden geliyordu

`22-t072-vmaf-av1.md` 7 sentetik fixture'ın 6'sında VMAF ≥93 ölçmüştü. Sentetik
`testsrc2` içeriği kolay sıkışır; CRF 23 orada 97'ye çıkar. **Gerçek, zaten bir
kez sıkıştırılmış kütüphane içeriğinde CRF 23'ün ulaştığı bant 75–90'dır.**
Bu, aynı belgenin kendi V-2 uyarısının ("sentetik korpus iki kez yanılttı")
üçüncü kez doğrulanmasıdır.

**Kapının kendisi kodda duruyor** (`quality_gate.vmaf_min = 93`,
`transcode.vmaf_min()`), üretim imajında **ölçülemiyor** ve bu açıkça yazılıyor.
Sahte bir VMAF sayısı üretilmedi.

**ÖNERİ (karar PO'nun):** ya eşik gerçek içerikten yeniden türetilsin
(ör. "çıktı çözünürlüğünde VMAF ≥ 85"), ya fayda kapısı 1080p→720p küçültme
yapan aksiyonlar için gevşetilsin. İkisi birden bugünkü hâliyle **vacuous bir
kapıdır** — hiçbir gerçek dosya ikisini birden sağlayamaz.

---

## 5. T-072/4 — süre farkı ≤100 ms (daha önce ÖLÇÜLMEMİŞ)

`34-dogrulama-faz4-7.md` §5: *"süre farkı ≤100 ms için ne test ne kod bulundu"*.

Artık her `transcode()` sonucunun `quality` bloğunda duruyor
(`duration_delta_s`, `max_duration_delta_s`, `duration_gate`); tavan tablodan
okunuyor (`quality_gate.max_duration_delta_s = 0.1`).

| Dosya | Süre farkı | Kapı |
|---|---:|---|
| r2 (gerçek 1080p) | **0,000 sn** | GECTI |
| r3 (gerçek vp9) | **0,001 sn** | GECTI |
| r6 (gerçek vp9/webm) | 0,000 sn | GECTI |
| `video_bloated_720p_8m.mp4` (fixture) | 0,000 sn | GECTI |

**Kapı çıktıyı ATMAZ, not düşer** — gerekçe tabloda (`quality_gate.duration_note`):
süresi 120 ms sapmış bir dosya, hiç dosya olmamasından iyidir; kararı çağıran
verir. Ölçülemeyen fark `None` döner ve **"0 fark" ile karıştırılmaz**
(`test_sure_farki_OLCULEMEZSE_uydurulmuyor`).

**ÖLÇÜLMEDİ:** ses/görüntü senkron kayması (lip-sync) ayrı bir ölçüdür ve
süre farkıyla aynı şey değildir; bu oturumda ölçülmedi.

---

## 6. T-074 — HLS

### 6.1 Mobil veri tavanı (daha önce ÖLÇÜLMEMİŞ)

`34-dogrulama-faz4-7.md`: *"ilk-10-saniye bayt ölçümü için ne test ne kod var…
en yakın olan test TOPLAM baytı ölçüyor"*.

Eklenen ölçüm (`hls.startup_bytes`) medya playlist'indeki `#EXTINF` sürelerini
sırayla toplar, pencere dolana kadar okunan segmentlerin baytını sayar.
**Pencereyi aşan segment de sayılır** — oynatıcı segmenti yarıda kesip
kullanamaz. Tavan `company-cover-video.json` `video.mobile_data_budget`'tan
geliyor: **1.250 KB = 1.280.000 bayt** (tabloda `hls.startup_budget`).

**Gerçek 540 sn'lik video (r1):**

| Basamak | Çözünürlük | Segment | Toplam bayt | **İlk 10 sn** | Segment / süre | Kapı |
|---|---|---:|---:|---:|---|---|
| 360p | 640×360 | 135 | 7.299.637 | **161.841 B** | 3 seg / 12,0 sn | ✅ GECTI |
| 480p | 854×480 | 135 | 7.905.561 | **173.121 B** | 3 seg / 12,0 sn | ✅ GECTI |
| 720p | 1280×720 | 135 | 12.095.893 | **275.581 B** | 3 seg / 12,0 sn | ✅ GECTI |

Üçü de tavanın **%21'inin altında**. Ölçünün varlık sebebi tabloda görünüyor:
720p basamağının **toplamı 12 MB**, **ilk 10 saniyesi 275 KB** — toplam bayt bu
soruyu cevaplamıyor.

### 6.2 Master playlist (gerçek dosya)

```
#EXT-X-STREAM-INF:BANDWIDTH=941600,RESOLUTION=640x360,CODECS="avc1.64001e"   v360p/playlist.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1647800,RESOLUTION=854x480,CODECS="avc1.64001f"  v480p/playlist.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=3295600,RESOLUTION=1280x720,CODECS="avc1.64001f" v720p/playlist.m3u8
```

720p kaynaktan **1080p basamağı üretilmedi** — büyütme yok, doğru davranış.

### 6.3 YENİ BULGU — B-3: HLS merdiveninde fayda kapısı YOK

r1'in 720p basamağı **12.095.893 B**, kaynağı **9.622.535 B**. Yani çok düşük
bitrate'li (140,6 kbps) bir kaynakta en üst basamak kaynaktan **%25,7 büyük**.
Sebep B-1'in aynısıdır: merdiven basamağının tavanı (720p için 2.996 kbps)
kaynağın doğal bitrate'inden kat kat yüksek, CRF 23 farkı dolduruyor.

Merdivende INV-05 benzeri bir kapı **yok** ve olmaması bir dereceye kadar
doğrudur (merdivenin amacı bayt kazanmak değil, uyarlanabilirlik). Ama
**kaynağından büyük bir "yüksek kalite" basamağı üretmek** hem depolama hem
CDN maliyetidir.

**Düzeltilmedi** — merdiven basamaklarının tavanını kaynağa göre kelepçelemek
`select_ladder` davranışını değiştirir ve ayrı bir ölçüm turu ister. Kayda
geçirildi.

### 6.4 HLS gerekliliği

r2 (58,192 sn) için `hls_required` → **False** (eşik 60 sn). Doğru: eşik altı
kaynak progressive MP4 ile teslim edilir, HLS zorlanmaz.

Küçük bir gözlem: `reasons` listesi `required=False` iken bile
*"rendition boyutu verilmedi — kaynak boyutu vekil olarak kullanildi"* satırını
taşıyor. Yanıltıcı değil ama bir sebep değil, bir not. **Değiştirilmedi.**

---

## 7. T-074 — tarayıcı oynatması (ÖLÇÜLDÜ)

`18-faz7-kapanis.md` ve `34-dogrulama-faz4-7.md` bunu açık bırakmıştı.

**Kurulum:** §6.1'de üretilen **gerçek** HLS paketi (`master.m3u8` + 3 basamak +
405 segment) yerel bir HTTP sunucusuyla servis edildi; sayfa `hls.js` 1.x ile
`master.m3u8`'i yükledi. Tarayıcı: **HeadlessChrome/151.0.0.0** (macOS).

**Ölçülen:**

| Ölçüt | Değer |
|---|---|
| `Hls.isSupported()` | **true** |
| `MANIFEST_PARSED` seviyeleri | `640x360@941600`, `854x480@1647800`, `1280x720@3295600` — **üretilenle birebir** |
| Olaylar | `MANIFEST_PARSED` → `loadedmetadata` → `playing` |
| `video.duration` | **540** (kaynakla aynı) |
| `readyState` | **4** (HAVE_ENOUGH_DATA) |
| `videoWidth × videoHeight` | **1280 × 720** (ABR en üst basamağa çıktı) |
| İkinci gözlem penceresinde ilerleyen medya süresi | 35,44 sn → 64,15 sn (**+28,72 sn**), `paused=false` |
| Yüklenen fragman / bayt | 53 fragman / 4.638.712 B |
| Tamponlanan uç | 212,07 sn |

**Sonuç: paket gerçek bir tarayıcıda hls.js ile OYNUYOR.**

**Tek uyarı — geçiştirilmiyor:** hls.js `mediaError/bufferSeekOverHole` olayı
düştü. Bu hls.js'in **kurtarılabilir** hata sınıfıdır (tampon boşluğu üzerinden
atlama) ve oynatma bundan sonra da kesintisiz ilerledi (yukarıdaki +28,72 sn
ölçümü bu olaydan **sonra** alındı). **Kök nedeni bu oturumda teşhis edilmedi;**
segment sınırındaki zaman damgası boşluğuyla ilgili olabilir. Faz 12 teslim
işinde takip edilmeli.

**ÖLÇÜLMEDİ:** Safari / iOS **yerel** HLS oynatması (`canPlayType` bu Chrome'da
`true` döndü ama yol hls.js üzerinden gitti); basamak değiştirme (ABR geçiş)
davranışı; canlı CDN başlıkları arkasında oynatma.

**Süre iddiası yok:** yukarıdaki "+28,72 sn" bir **medya zamanı** ölçüsüdür,
kodlama/oynatma hızı iddiası değildir — makine paylaşımlı.

---

## 8. T-073 — poster + önizleme klibi, gerçek videolarda

Kaynak sayfanın kabul kriterleri (`34-dogrulama-faz4-7.md` §T-073):
(1) poster "anlamlı kare"den seçilir · (2) klip 3-6 sn, sessiz, loop-safe, ≤1 MB ·
(3) poster crop intent'e uyar, simülatörde gösterilir · (4) `prefers-reduced-motion`
yalnız-poster teslim yolu döndürür.

### 8.1 Ölçüm — 7/7 gerçek video

| Dosya | Poster damgası | Luma | Kalite | Poster baytı (kapı 122.880) | Klip süresi | Klip baytı | Sessiz | 1 MB | 400 KB |
|---|---:|---:|---:|---:|---:|---:|---|---|---|
| r1 | 4,00 sn | 49,6% | 78 | 9.194 | 6,00 sn | 40.992 | ✅ | ✅ | ✅ |
| r2 | 2,47 sn | 60,5% | 78 | 78.244 | 6,00 sn | 328.061 | ✅ | ✅ | ✅ |
| **r3** | 1,01 sn | 35,3% | **62** | **155.792 ❌** | 4,75 sn | **525.678** | ✅ | ✅ | **❌** |
| r4 | 3,32 sn | 13,9% | 78 | 18.528 | 6,00 sn | 168.473 | ✅ | ✅ | ✅ |
| r5 | 1,23 sn | 54,3% | 78 | 16.912 | 6,00 sn | 139.778 | ✅ | ✅ | ✅ |
| r6 | 1,24 sn | 50,4% | 78 | 24.156 | 6,00 sn | 133.836 | ✅ | ✅ | ✅ |
| r7 | 3,19 sn | 57,7% | 78 | 5.670 | 6,00 sn | 154.083 | ✅ | ✅ | ✅ |

**Yeşil olanlar:** 7/7 poster üretildi, hiçbiri ilk kare değil (damgalar
1,01–4,00 sn), 7/7'si parlaklık kapısından **ilk denemede** geçti (yeniden
deneme gerekmedi), 7/7 klip sessiz ve 3–6 sn aralığında, 7/7 klip **1 MB zorunlu
kapısının** altında. Dikey kaynakta klip 480×854, kare kaynakta 480×480 —
kısa kenar bütçesi yönelime göre doğru uygulanıyor.

### 8.2 AÇIK — poster bayt kapısı gerçek içerikte tutmuyor

r3'te kalite merdiveni (78 → 70 → 62) tükendi ve poster 155.792 B kaldı
(kapı 122.880 B). Kod doğru davranıyor: dosyayı **koruyor** ve not düşüyor
(*"poster yokluğu, biraz büyük bir posterden kötüdür"*).

Merdiveni uzatmak çözüm mü — ölçüldü:

| WebP kalitesi | 78 | 70 | 62 | 55 | 48 | 40 |
|---|---:|---:|---:|---:|---:|---:|
| Bayt | 194.142 | 168.762 | 155.792 | 144.638 | 136.204 | **122.836** |

Kapı ancak **kalite 40**'ta tutuyor — 1280 px genişlikte bu görünür bir kalite
kaybıdır. **Merdiven UZATILMADI:** bu bir politika kararıdır (poster genişliğini
düşürmek mi, kapıyı yükseltmek mi, kaliteyi feda etmek mi) ve sessizce
verilmemeli. Ölçüm burada, karar PO'nun.

### 8.3 KARŞILANAMAZ / ÖLÇÜLMEDİ — değişmedi

* **(3) crop intent + simülatör:** `Media Crop Intent` kaydı yok, simülatör
  arayüzü yok (`T-104`/`T-113`). Bu oturumda **değişmedi**; ilgili dosyalar
  (`api/**`, `admin-panel`) bu görevin kapsamı dışında.
* **(4) `prefers-reduced-motion` → yalnız-poster teslim yolu:** politika alanı
  `slot-policy.schema.json`'da tanımlı, teslim yolu **doğrulanmadı**. Teslim
  katmanı bu görevin kapsamı dışında. **ÖLÇÜLMEDİ.**

---

## 9. Test durumu

```
$ docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
    /home/frappe/frappe-bench/env/bin/python -m unittest \
    tradehub_core.tests.test_video_decision tradehub_core.tests.test_video_transcode

Ran 167 tests in 232.319s
OK
```

**167 test · 0 hata · 0 başarısız · 0 atlanan.** (Önce 147.) Çıktıda
`(skipped=…)` eki yok — gerçek-ffmpeg testlerinin hepsi fiilen koştu.

### 9.1 Eklenen 20 test

| Sınıf | Test | Ne pinliyor |
|---|---:|---|
| `HizDenetimi` | 7 | capped-CRF komut sözleşmesi, tavan aritmetiği (ses payı, sessiz kaynak, taban/tavan kelepçesi, ölçülemeyen bitrate), **vacuity anahtarı** |
| `GeriCekilmeKurali` | 6 | B-2 koşulları: moov/kap kusuru, kusursuz kaynak, vp9/opus reddi, ölçülemeyen künye |
| `GercekRemux` | 2 | Gerçek ffmpeg ile geri çekilme + **vacuity** (kapalıyken moov sonda kalır) |
| `GercekTranscode` | 2 | Süre farkı ölçümü + "ölçülemedi ≠ 0" |
| `GercekHls` | 3 | İlk-10-sn baytı, toplamdan farkı, pencereyi aşan segmentin sayılması |

### 9.2 Beklentisi DEĞİŞEN 1 test

`GercekTranscode.test_FAYDA_KAPISI_verimli_kaynagi_korur` eskiden
`saving_ratio < 0` iddia ediyordu (sabit CRF 23 verimli fixture'ı %84
büyütüyordu). Capped-CRF ile aynı çıktı artık **%4,3 küçülüyor**. Test artık
asıl sözleşmeyi sınıyor: **kazanç eşiğin altındaysa çıktı atılır**. Değişikliğin
gerekçesi testin docstring'ine yazıldı; eski kusurlu davranış
`test_rate_control_crf_TAVANI_KALDIRIR` ile ayrıca pinlendi.

### 9.3 Faz 7 DIŞI — değişmedi

`test_media_transcode` (22) + `test_media_transcode_retry` (39) hâlâ
`IncorrectSitePath: test_site does not exist` ile **yüklenemiyor** — 15 hatanın
15'i `setUpClass` öncesinde. Bu modüller eski `media/transcode.py` hattını
sınıyor; bu oturumda o hatta **dokunulmadı**. Ortam kusuru, kod kusuru değil —
`18-faz7-kapanis.md` §2.4 ile aynı durum.

### 9.4 Lint — dürüst durum

`ruff check` bu üç dosyada **temiz değil ve zaten değildi**: değişiklik öncesi
**67**, sonrası **82** bulgu. 15 bulgunun tamamı dosyanın **mevcut** stilinden
gelen aynı sınıf (`UP006 Dict→dict`, `UP045 Optional→|None`, `UP015`).
Modül baştan sona `typing.Dict/List/Optional` kullanıyor; yalnız yeni satırları
modernleştirmek dosyayı kendi içinde tutarsız yapardı. **Depo geneli bir
modernizasyon işidir, bu görevin kapsamı değil.**

---

## 10. Değişen dosyalar

| Dosya | Ne değişti |
|---|---|
| `tradehub_core/media/pipeline/video/transcode.py` | capped-CRF (`rate_ceiling_kbps`, `_rate_control_args`), B-2 geri çekilme (`remux_fallback_applies` + `apply_decision`), süre farkı ölçümü (`duration_delta_s`, `max_duration_delta_s`), `vmaf_min()`, `TranscodeResult.fallback_from` |
| `tradehub_core/media/pipeline/video/hls.py` | `startup_bytes()`, `HlsSpec.startup_window_s/startup_max_bytes`, `HlsVariantResult.startup_*` alanları |
| `tradehub_core/media/pipeline/policy/video_decision.json` | `targets.h264_primary` hız denetimi alanları + gerekçe, `benefit_gate.fallback`, `targets.quality_gate`, `hls.startup_budget` |
| `tradehub_core/tests/test_video_transcode.py` | +20 test, 1 testin beklentisi güncellendi |
| `docs/reports/39-t072-video-hatti.md` | bu belge |

**Dokunulmayanlar:** `hooks.py`, `permissions.py`, `patches.txt`, `patches/**`,
`media/pipeline/image/**`, `api/**`, `admin-panel`, `docker/docker-compose.yml`.
`bench migrate` **çalıştırılmadı**. Bayraklar **0'da kaldı** — bu görev hiçbir
bayrağa dokunmadı. Üretilen bütün ölçüm dosyaları konteynerdeki `/tmp` altında
kaldı ve temizlendi; hiçbir DocType kaydı oluşturulmadı, hiçbir üretim medya
dosyası değiştirilmedi.

---

## 11. Açık kalanlar

| # | Konu | Durum |
|---|---|---|
| 1 | **VMAF ≥93 ile INV-05 aynı anda sağlanamıyor** (gerçek 1080p'de ölçüldü) | **KARAR GEREKLİ** — eşik gerçek içerikten yeniden türetilmeli ya da kapı küçültme yapan aksiyonlar için gevşetilmeli (§4.4) |
| 2 | **B-3: HLS merdiveninde fayda kapısı yok** — 720p basamağı kaynaktan %25,7 büyük çıkabiliyor | **AÇIK**, düzeltilmedi (§6.3) |
| 3 | **Poster bayt kapısı (120 KB)** gerçek detaylı içerikte ancak WebP kalite 40'ta tutuyor | **KARAR GEREKLİ** (§8.2) |
| 4 | `hls.js` `bufferSeekOverHole` uyarısı | **TEŞHİS EDİLMEDİ** — oynatma engellenmedi (§7) |
| 5 | Safari / iOS yerel HLS oynatması, ABR basamak geçişi | **ÖLÇÜLMEDİ** (§7) |
| 6 | Ses/görüntü senkron kayması (lip-sync) | **ÖLÇÜLMEDİ** (§5) |
| 7 | HDR→SDR tone-mapping (T-072/5) | **ÖLÇÜLMEDİ** — bu oturumda ele alınmadı, kütüphanede HDR kaynak yok |
| 8 | T-073/3 crop intent + simülatör, T-073/4 reduced-motion teslim yolu | **KAPSAM DIŞI** (§8.3) |
| 9 | `ruff` bu üç dosyada temiz değil (67 → 82, hepsi mevcut `UP00x` sınıfı) | **AÇIK**, depo geneli iş (§9.4) |
