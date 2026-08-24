# Kütüphane Benchmark'ı — Pillow vs pyvips vs ffmpeg (T-007 / K-11)

**Tarih:** 2026-08-18 · **Ortam:** yerel stack (`istoc-dev-backend-1`, site `istoc.localhost`)
**Betik:** `scripts/bench_engine.py` · **Ham veri:** `fixtures/bench.csv` (360 satır, **0 hata**)

Kapanış raporunun (`07-faz0-kapanis.md` §5) **K-11** maddesi bu ölçümü istiyordu.
Faz 0'da benchmark yapılamamıştı çünkü `libvips`/`pyvips` kurulu değildi. Bu
oturumda kuruldu ve ölçüm koşuldu.

---

## 0. Karar — tek cümlede

> **Pillow'da kalın.** Ama `engine.optimize`'a **`draft()` ekleyin**: iki satır,
> yeni bağımlılık yok, en kötü dosyada tepe bellek **588 MB → 172 MB** (3,4×).
> pyvips ancak elle ayarlanmış bir zincirle kazanıyor (1,37×) ve kazancın tamamı
> canlı korpusun **%3,7'sinde** (>20 MP, 179 dosya) toplanıyor; buna karşılık
> 38 CMYK dosyanın **rengini gözle görülür biçimde değiştiriyor**.

Eşik §11'de.

---

## 1. Kurulum — ve bu kurulumun KALICI OLMADIĞI

pyvips konteynere şu komutla kuruldu:

```bash
docker exec -u root istoc-dev-backend-1 bash -lc \
  "apt-get update && apt-get install -y libvips-dev && \
   /home/frappe/frappe-bench/env/bin/pip install pyvips"
```

**Kurulan sürümler (ölçüldü):**

| Bileşen | Sürüm |
|---|---|
| `pyvips` | **3.1.1** (kaynaktan wheel derlendi: `pyvips-3.1.1-cp311-cp311-linux_aarch64.whl`) |
| `libvips` | **8.14.1** (`libvips-dev 8.14.1-3+deb12u3`, Debian 12 deposu) |
| Pillow | 12.2.0 |
| numpy | 2.4.6 (SSIM için) |
| ffmpeg | 5.1.9-0+deb12u1 |
| Python | 3.11.6 · **11 vCPU** |

### ⚠ Bu kurulum geçicidir

Konteynerin **yalnız iki dizini** kalıcı birim (volume):

```
volume istoc-dev_logs   -> /home/frappe/frappe-bench/logs
volume istoc-dev_sites  -> /home/frappe/frappe-bench/sites
```

`libvips` (`/usr/lib`) ve `pyvips` (`/home/frappe/frappe-bench/env`) **konteynerin
yazılabilir katmanında** duruyor. Yani:

| İşlem | Kurulum hayatta kalır mı? |
|---|---|
| `docker restart` | ✅ evet |
| `docker compose up --force-recreate` | ❌ **hayır** |
| imaj yeniden derlenmesi | ❌ **hayır** |

Bu raporu yeniden üretmek isteyen **önce §1'deki kurulum komutunu tekrar koşmalı.**
`bench_engine.py` pyvips'i bulamazsa durmaz; o motoru `YOK` işaretleyip Pillow +
ffmpeg ile devam eder.

### Kalıcı hale getirmek için önerilen satır (DOSYA DEĞİŞTİRİLMEDİ)

`docker/backend.Dockerfile` **değiştirilmedi** — yalnız öneri. Mevcut ffmpeg
katmanı (satır 15) zaten doğru desende; `libvips42` oraya eklenmeli:

```dockerfile
# mevcut (satır 15):
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# önerilen:
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libvips42 \
    && rm -rf /var/lib/apt/lists/*
```

Ardından pip katmanına (satır 77-78, `env/bin/pip install ... apps/tradehub_core`):

```dockerfile
    env/bin/pip install --no-cache-dir pyvips; \
```

**Notlar:**
- Çalışma zamanı için `libvips-dev` **gerekmez**; `libvips42` yeterlidir.
  `-dev` yalnız pyvips'i kaynaktan derlerken lazım. `pyvips` cffi ile çalışma
  zamanında bağlandığı için `libvips42` + `pyvips` wheel'i yeter.
- **Bu satır tek başına yetmez.** `00-ortam-envanteri.md` §8'in tespiti geçerli:
  üretim imajını Frappe Cloud (Press) kendi üretiyor ve `docker/backend.Dockerfile`'ı
  **kullanmıyor**. pyvips'e geçilecekse üretim tarafında ayrıca ayarlanmalı.
  Bu, K-11'in kapatılmasının önündeki gerçek engel — kurulum değil, **üretim paritesi**.

---

## 2. Test kümesi — canlı veriden 10 gerçek dosya

`sites/istoc.localhost` altındaki **3.998 okunabilir görsel** tarandı; format /
renk modu / megapiksel / bayt eksenlerinde uçları ve medyanı birlikte kapsayacak
10 dosya seçildi. Seçim `bench_engine.py:CORPUS` içinde sabit — tekrar
çalıştırılabilir olması için.

| # | Dosya | Format | Mod | MP | Bayt | ICC | Neden seçildi |
|---|---|---|---|---:|---:|:---:|---|
| 1 | `00d54ac2…878.jpg` | JPEG | RGB | **72,71** | 9,7 MB | – | korpusun **en büyük megapikseli** (§10, P-05) |
| 2 | `305 SİYAH.jpg` | JPEG | **CMYK** | 36,16 | 2,6 MB | – | CMYK + yüksek MP → §5'in patolojisini açığa çıkardı |
| 3 | `Toplu resim-…-3.png` | PNG | **RGBA** | 36,27 | 10,9 MB | ✅ | alfa + ICC + yüksek MP |
| 4 | `av-120.tif` | TIFF | RGB | 18,28 | **22,1 MB** | ✅ | korpusun **en büyük baytı** |
| 5 | `323-9.png` | PNG | RGBA | 17,31 | 7,6 MB | – | tipik alfalı PNG |
| 6 | `323-9 (1).webp` | WEBP | RGBA | 17,31 | 0,3 MB | – | (5)'in WebP'si — aynı görsel, farklı kod çözücü |
| 7 | `20250407160713_d33fff.webp` | WEBP | RGB | 6,32 | 0,3 MB | – | tipik WebP |
| 8 | `AV157G.jpg` | JPEG | **CMYK** | 2,09 | 0,9 MB | – | tipik CMYK ürün görseli |
| 9 | `110401-1.jpg` | JPEG | RGB | 1,72 | 0,5 MB | – | medyan civarı ürün görseli |
| 10 | `0158.jpg` | JPEG | RGB | 1,44 | 82 KB | – | **p50 bayt/MP** örneği |

**Toplam kaynak: 53,32 MB.**

> **Yan bulgu — EXIF rotasyonu korpusta YOK.** 3.998 dosyanın tamamı tarandı;
> `Orientation` (EXIF 274) değeri **1'den büyük olan tek dosya yok**. Yani
> `engine.py`'nin `exif_transpose` çağrısı bugünkü veride **hiçbir zaman piksel
> döndürmüyor**. Kod yanlış değil (savunma amaçlı doğru), ama T-006 golden
> fixture korpusu (K-10) bu vakayı **sentetik olarak üretmek zorunda** — canlı
> veriden örneklenemez.

---

## 3. Yöntem

### 3.1 Normalize edilmiş işlem zinciri

Her motor **aynı sözleşmeyi** uygular:

```
oku → EXIF yönünü uygula → sRGB'ye çevir → uzun kenarı 2400'e küçült
     (YALNIZ downscale) → JPEG q85 / WebP q80 olarak kodla
```

Bu zincir kasten `engine.optimize`'dan **farklıdır**: `optimize` formatı korur
(JPEG→JPEG) ve TIFF'i CMYK bırakır. Benchmark'ın karşılaştırılabilir olması için
tüm motorlar aynı iki hedef formata yazar.

### 3.2 Tepe belleği neden `fork` ile ölçtük

`resource.getrusage(RUSAGE_SELF).ru_maxrss` süreç ömrü boyunca **yüksek-su-işareti**
tutar — hiç düşmez. Aynı süreçte arka arkaya ölçüm yapılsaydı 72,71 MP'lik ilk
dosya sonraki **tüm** ölçümleri kirletirdi.

Bu yüzden **her koşum ayrı bir `os.fork()` çocuğunda** çalışır; tepe bellek
`os.wait4()` → `ru_maxrss` ile **yalnız o çocuğa ait** okunur. Sonuç JSON olarak
bir pipe'tan geri gelir. Ölçüm gövdesi (`inner_s`) çocuğun içinde `perf_counter`
ile alınır, yani **import maliyeti hariçtir**.

Python yorumlayıcısının taban çizgisi ölçüldü: **24,4 MB**. Tablolardaki tepe RSS
değerleri **mutlaktır**, bu tabanı içerir.

### 3.3 Koşum planı

10 dosya × 6 motor × 2 çıktı formatı × **3 tekrar = 360 koşum**.
Süre için **medyan**, bellek için **maksimum**, çıktı baytı için **medyan** alındı.
360/360 koşum başarılı, hata yok.

### 3.4 Ölçülen 6 motor kolu

| Kol | Ne yapar |
|---|---|
| `pillow` | Bugünkü desen: tam çözünürlükte aç, `thumbnail()` + LANCZOS |
| `pillow_draft` | Aynısı + JPEG'de `im.draft()` (libjpeg DCT ölçekli çözme) |
| `pyvips` | `pyvips.Image.thumbnail()` — dokümanların önerdiği "naif" kullanım |
| `pyvips_c1` | Aynısı, `VIPS_CONCURRENCY=1` (tek çekirdek — adillik kontrolü) |
| `pyvips_tuned` | **Elle ayarlanmış zincir** — §5 ve §6'daki iki tuzağı atlatır |
| `ffmpeg` | `scale=…:flags=lanczos` + mjpeg / libwebp |

---

## 4. Sonuçlar

### 4.1 Toplam (10 dosya, JPEG + WebP birlikte, medyanların toplamı)

| Motor | Süre | Pillow'a göre | Tepe RSS | Çıktı |
|---|---:|---:|---:|---:|
| `pillow` | 12,87 s | 1,00× | 588 MB | 6,43 MB |
| `pillow_draft` | 11,85 s | **1,09×** | **367 MB** | 6,44 MB |
| `pyvips` | 13,74 s | **0,94×** ⚠ | 392 MB | 6,35 MB |
| `pyvips_c1` | 13,73 s | 0,94× | 508 MB | 6,35 MB |
| **`pyvips_tuned`** | **9,39 s** | **1,37×** | 573 MB ⚠ | **6,17 MB** |
| `ffmpeg` | 12,68 s | 1,01× | 306 MB | 6,75 MB |

**İlk sürpriz: kutudan çıktığı hâliyle `pyvips` Pillow'dan YAVAŞ (0,94×).**
Doküman ve blog yazılarının vaat ettiği "4-8× hızlı" burada **çıkmadı**. Nedeni
§5'te: tek bir CMYK dosya pyvips'in toplamının %43'ünü yiyor.

**İkinci sürpriz: `VIPS_CONCURRENCY=1` süreyi neredeyse hiç değiştirmedi**
(13,74 → 13,73 s) ama tepe belleği **392 → 508 MB'a çıkardı**. Yani bu iş
yükünde libvips'in çok çekirdekliliği **hız kazandırmıyor**; 11 vCPU boşa
duruyor. Pillow'a karşı "ama vips paralel" savunması bu ölçümde **geçersiz**.

### 4.2 Format kırılımı

| Motor | JPEG süre | JPEG tepe | JPEG çıktı | WebP süre | WebP tepe | WebP çıktı |
|---|---:|---:|---:|---:|---:|---:|
| `pillow` | 5,33 s | 588 MB | 3,61 MB | 7,54 s | 588 MB | 2,81 MB |
| `pillow_draft` | 4,80 s | **367 MB** | 3,63 MB | 7,06 s | **367 MB** | 2,81 MB |
| `pyvips` | 5,75 s | 325 MB | 3,52 MB | 7,99 s | 392 MB | 2,84 MB |
| `pyvips_tuned` | **3,54 s** | 419 MB | **3,42 MB** | **5,85 s** | 573 MB | **2,75 MB** |
| `ffmpeg` | 5,13 s | **260 MB** | 3,96 MB | 7,55 s | **306 MB** | 2,79 MB |

Çıktı boyutu farkı **küçük**: en iyi (`pyvips_tuned` 6,17 MB) ile en kötü
(`ffmpeg` 6,75 MB) arasında %9,4; Pillow ile `pyvips_tuned` arasında **%4,0**.
**Depolama maliyeti kütüphane seçiminin gerekçesi olamaz.**

### 4.3 Dosya başına — kazanç nerede toplanıyor (JPEG çıktısı)

| Dosya | Format/Mod | MP | `pillow_draft` | `pyvips_tuned` | Oran |
|---|---|---:|---:|---:|---:|
| `av-120.tif` | TIFF RGB | 18,3 | 727 ms | **300 ms** | **2,42×** |
| `Toplu resim-…-3.png` | PNG RGBA | 36,3 | 1.951 ms | **1.036 ms** | **1,88×** |
| `00d54ac2…878.jpg` | JPEG RGB | 72,7 | 474 ms | **287 ms** | **1,65×** |
| `323-9.png` | PNG RGBA | 17,3 | 689 ms | 591 ms | 1,16× |
| `20250407…webp` | WEBP RGB | 6,3 | 172 ms | 150 ms | 1,15× |
| `323-9 (1).webp` | WEBP RGBA | 17,3 | 447 ms | 430 ms | 1,04× |
| `110401-1.jpg` | JPEG RGB | 1,7 | 47 ms | 46 ms | 1,02× |
| `0158.jpg` | JPEG RGB | 1,4 | 19 ms | 19 ms | **0,97×** |
| `AV157G.jpg` | JPEG **CMYK** | 2,1 | 54 ms | 96 ms | **0,56×** ❌ |
| `305 SİYAH.jpg` | JPEG **CMYK** | 36,2 | 217 ms | 586 ms | **0,37×** ❌ |

**Örüntü nettir:**
- **< 5 MP:** fark yok (0,97×–1,02×). Kütüphane değiştirmenin getirisi **sıfır**.
- **> 15 MP, CMYK değil:** pyvips 1,16×–2,42× kazanıyor.
- **CMYK:** pyvips **her boyutta kaybediyor** (0,37×–0,56×).

Bunu canlı dağılımla (`08-canli-olcum.md` §1.2) çakıştırın:

| Yüzdelik | Megapiksel | pyvips'in kazancı |
|---|---:|---|
| p50 | 1,56 MP | **yok** |
| p90 | 5,01 MP | **yok** |
| p99 | 29,21 MP | 1,6–2,4× |

> **Canlı görsellerin %90'ı 5,01 MP'nin altında — yani pyvips'in hiçbir şey
> kazandırmadığı bölgede.** >20 MP olan 179 dosya, 4.812 görselin **%3,7'si**.

---

## 5. pyvips'in CMYK patolojisi — kök neden bulundu

`305 SİYAH.jpg` (JPEG CMYK, 7361×4912 = 36,2 MP) üzerinde `pyvips.Image.thumbnail()`
**2.836 ms** sürdü; aynı dosyada `pillow_draft` **217 ms**. 13× fark. Aşama aşama
ölçüldü:

| Aşama | Süre |
|---|---:|
| `jpegload` tam çözünürlük (shrink=1) | 196 ms |
| `jpegload` **shrink=2** (DCT 1/2) | **81 ms** |
| `jpegload` **shrink=4** (DCT 1/4) | **57 ms** |
| CMYK → sRGB `colourspace()` (tam çözünürlük) | 244 ms |
| **tam çözünürlükte yeniden örnekleme (4 bant, CMYK)** | **2.606 ms** ⚠ |
| ölçekten sonra CMYK → sRGB (küçük görsel) | 2 ms |

**Darboğaz renk çevrimi değil** (244 ms) — **tam çözünürlükte 4 bantlı yeniden
örnekleme** (2.606 ms).

Kök neden: **`thumbnail()` bir CMYK JPEG'de JPEG shrink-on-load'ı kullanmıyor.**
Görseli tam çözünürlükte açıp CMYK uzayında ölçekliyor. RGB JPEG'de aynı işlem
(72,7 MP, daha büyük dosya!) yalnız 291 ms sürüyor — çünkü orada DCT ölçekli
çözme devreye giriyor.

**Düzeltme ölçüldü:**

| Zincir | Süre | Kazanç |
|---|---:|---:|
| `thumbnail()` naif | 2.865 ms | 1,00× |
| önce sRGB, sonra ölçek | 1.931 ms | 1,48× |
| **`jpegload(shrink=N)` + sRGB + ölçek** | **568 ms** | **5,04×** |

`pyvips_tuned` kolu bu zinciri uygular. Ama düzelttikten sonra bile **586 ms**;
`pillow_draft`'ın **217 ms**'inin 2,7 katı. **CMYK'de Pillow kazanıyor, düzeltmeyle bile.**

> Canlı veride **38 CMYK dosya** var (`08-canli-olcum.md` §1.1).

---

## 6. `export_profile="srgb"` tuzağı — pyvips'e geçilirse yapılacak hata

pyvips örneklerinin çoğu `thumbnail(..., export_profile="srgb")` yazar. Bu
**koşulsuz** verilirse, ICC profili olmayan sRGB görselleri de gereksiz bir renk
dönüşümünden geçirir ve **pikselleri kaydırır**:

`0158.jpg` (JPEG RGB, ICC **yok**, 1200×1200 — hedefin altında olduğu için
**yeniden boyutlandırma da yok**, yani çıktı girdiyle birebir aynı olmalı):

| Zincir | Pillow'a göre ortalama \|fark\| | Maks fark |
|---|---:|---:|
| `export_profile="srgb"` verilerek | **5,45** | **25** |
| `export_profile` verilmeden | **0,00** | **0** |

Profil verilmediğinde çıktı Pillow ile **bit düzeyinde aynı**. Verildiğinde
görsel gözle görülür biçimde kayıyor.

Bu §8'deki SSIM'de de doğrulanıyor: naif zincirde `0158.jpg` için Pillow~pyvips
SSIM **0,8994**; `pyvips_tuned`'da (koşullu profil) **1,0000**.

**Kural:** renk çevrimi yalnız kaynağın yorumu gerçekten sRGB değilse yapılmalı
(`if im.interpretation != "srgb"`). `bench_engine.py:_chain_pyvips_tuned` bunu
uygular.

---

## 7. Çıktı boyutu

| Motor | JPEG toplam | WebP toplam | Genel |
|---|---:|---:|---:|
| `pyvips_tuned` | **3,42 MB** | **2,75 MB** | **6,17 MB** |
| `pyvips` | 3,52 MB | 2,84 MB | 6,35 MB |
| `pillow` | 3,61 MB | 2,81 MB | 6,43 MB |
| `pillow_draft` | 3,63 MB | 2,81 MB | 6,44 MB |
| `ffmpeg` | 3,96 MB | 2,79 MB | 6,75 MB |

Kaynak 53,32 MB → çıktı ~6,2-6,8 MB. Tüm motorlarda **%87-88 tasarruf**.
Motorlar arası fark (%4) bu tasarrufun yanında **önemsiz**.

---

## 8. Kalite — SSIM (ölçüldü)

SSIM `numpy` ile, Wang et al. (2004) gaussian 11×11 σ=1,5 penceresiyle, gri
tonlamada hesaplandı (`bench_engine.py:ssim`). Alfa iki kolda da **beyaza
flatten** edilerek eşitlendi — yoksa karşılaştırma elma/armut olurdu.

| Dosya | `pil_enc` | `tuned_enc` | `pil ~ tuned` | `ref ~ ref` |
|---|---:|---:|---:|---:|
| `00d54ac2…878.jpg` (72,7 MP) | 0,9667 | 0,9652 | 0,8074 | **0,8408** ⚠ |
| `305 SİYAH.jpg` (CMYK) | 0,9954 | 0,9962 | 0,9670 | 0,9701 |
| `Toplu resim-…-3.png` | 0,9957 | 0,9958 | 0,9976 | 0,9986 |
| `av-120.tif` | 0,9976 | 0,9976 | 0,9986 | 0,9995 |
| `323-9.png` | 0,9955 | 0,9956 | 0,9975 | 0,9987 |
| `323-9 (1).webp` | 0,9974 | 0,9969 | 0,9977 | 0,9989 |
| `20250407…webp` | 0,9873 | 0,9873 | 0,9965 | 0,9994 |
| `AV157G.jpg` (CMYK) | 0,9944 | 0,9903 | 0,8386 | **0,8435** ⚠ |
| `110401-1.jpg` | 0,9978 | 0,9978 | **1,0000** | **1,0000** |
| `0158.jpg` | 0,9983 | 0,9983 | **1,0000** | **1,0000** |

**Sütunların anlamı:**
- `pil_enc` / `tuned_enc` — motorun **kendi kodlama kaybı** (kayıpsız referansa karşı)
- `pil ~ tuned` — iki motorun JPEG çıktısı birbirine ne kadar yakın
- `ref ~ ref` — kodlamadan **önceki** rasterler ne kadar yakın (fark kodlayıcıda mı, ölçeklemede mi?)

**Okunuşu:**

1. **Kodlama kaybı iki motorda aynı** — `pil_enc` ve `tuned_enc` her dosyada
   0,985–0,998 arasında ve birbirine çok yakın. **JPEG q85 / WebP q80 kalitesi
   açısından iki kütüphane arasında seçim yapmak için sebep yok.**

2. **İki dosyada birebir aynı çıktı** (`110401-1.jpg`, `0158.jpg` → SSIM
   **1,0000**). Bunlar yeniden boyutlandırma gerektirmeyen, ICC'siz sRGB
   JPEG'ler. §6'daki düzeltmenin doğruluğunu kanıtlıyor.

3. **CMYK'de ciddi ayrışma** (`AV157G.jpg` → 0,8386). `ref ~ ref` de 0,8435 —
   yani fark **kodlayıcıda değil, renk yorumunda**. Ayrıntı §9'da.

4. **72,7 MP'de ayrışma** (0,8408). Sebep: shrink-on-load yeniden örnekleme
   yolunu değiştiriyor. Adil olmak için Pillow'un **kendi** `draft()`'ı da
   ölçüldü:

   | Dosya | `pillow` ~ `pillow_draft` |
   |---|---:|
   | `00d54ac2…878.jpg` (72,7 MP) | 0,9721 |
   | `305 SİYAH.jpg` | 0,9946 |
   | `AV157G.jpg` | 1,0000 |
   | `110401-1.jpg` | 1,0000 |
   | `0158.jpg` | 1,0000 |

   Yani shrink-on-load Pillow'da da pikselleri değiştiriyor (0,9721), ama
   `pyvips_tuned`'dan **daha az** (0,8408). `pyvips_tuned` daha agresif DCT
   ölçeği seçiyor.

> **ÖLÇÜLMEDİ:** hangi çıktının **gözle daha iyi** olduğu. SSIM bir *fark*
> ölçüsüdür, *kalite* ölçüsü değil — "tam çözünürlükten Lanczos" referansına
> uzaklık, "daha kötü" demek değildir. 72,7 MP ve CMYK dosyalarda **göz denetimi
> gerekir**; bu rapor o kararı vermiyor.

---

## 9. CMYK renk yorumu — üç motor, iki farklı cevap

`AV157G.jpg` (JPEG CMYK, ICC profili **yok**) — aynı görselin sRGB'ye çevrilmiş
hâlinin ortalama RGB değeri:

| Motor | Ortalama RGB | Pillow'a uzaklık (ort. \|fark\|) |
|---|---|---:|
| **Pillow** | `[73,0 · 67,9 · 69,0]` | — |
| **ffmpeg** | `[72,5 · 67,4 · 68,5]` | **1,5** |
| **pyvips** | `[94,7 · 82,7 · 84,2]` | **21,7** |

**Pillow ve ffmpeg aynı fikirde (fark 1,5); pyvips ikisinden de belirgin biçimde
ayrılıyor (fark 21,7) ve gözle görülür ölçüde daha açık bir görüntü üretiyor.**

Sebep: profilsiz CMYK'nin **tek doğru** yorumu yoktur. Pillow (ve ffmpeg) cebirsel
bir dönüşüm uygular; libvips gömülü bir genel CMYK profiliyle gerçek bir ICC
dönüşümü yapar. İkisi de savunulabilir, ama **aynı değil**.

> **Göç riski:** pyvips'e geçilirse canlıdaki **38 CMYK dosyanın rengi bugün
> sitede göründüğünden farklı çıkar.** Bu, benchmark'ın performans sonucundan
> bağımsız, kendi başına bir karar kalemidir. `engine.optimize` bugün ne
> üretiyorsa, geçişten sonra aynı dosyalar farklı üretecek.

> **Ek not (kod okuması, bu benchmark'ın kapsamı dışında):**
> `media/engine.py` içinde `im.convert("RGB").save(..., icc_profile=icc)` deseni
> var. Kaynak **ICC'li bir CMYK JPEG** ise, RGB'ye çevrilmiş piksellere
> **kaynağın CMYK ICC profili** iliştirilir — yani çıktı yanlış etiketlenir.
> Ölçülen 38 CMYK dosyanın hiçbirinde ICC profili **yok**, bu yüzden bugün
> tetiklenmiyor: **gizil (latent) bir kusur.** Ayrı kalem olarak açılmalı.

---

## 10. P-05: ">20 MP tam bellekte açma" — ölçülmüş hâli

Dokümanın P-05 tuzağı buydu. Canlıda **179 dosya** 20 MP üstünde. Üçü korpusta:

### JPEG çıktısı üretirken tepe RSS

| Dosya | MP | Kaynak | `pillow` | `pillow_draft` | `pyvips` | `pyvips_tuned` | `ffmpeg` |
|---|---:|---:|---:|---:|---:|---:|---:|
| `00d54ac2…878.jpg` | 72,7 | 9,7 MB | **588 MB** | 172 MB | 108 MB | **78 MB** | 223 MB |
| `Toplu resim-…-3.png` | 36,3 | 10,9 MB | 367 MB | 367 MB | 325 MB | 343 MB | **260 MB** |
| `305 SİYAH.jpg` (CMYK) | 36,2 | 2,6 MB | 309 MB | **105 MB** | 181 MB | 128 MB | 252 MB |

**Bulgular:**

1. **9,7 MB'lık bir dosya 588 MB RSS'e mal oluyor — 60×.** 72,71 MP × 3 bayt =
   218 MB ham raster; Pillow'un LANCZOS ara tamponlarıyla birlikte 588 MB'a
   çıkıyor. **P-05 tuzağı gerçek ve ölçüldü.**

2. **`draft()` bunu 588 → 172 MB'a indiriyor (3,4×)** — tek satırlık bir
   değişiklikle, yeni bağımlılık olmadan.

3. **Ama `draft()` yalnız JPEG'de çalışır.** `Toplu resim-…-3.png` (36,3 MP
   RGBA) `pillow` ve `pillow_draft`'ta **aynı: 367 MB**. PNG/WebP'de DCT ölçeği
   diye bir şey yok.

4. **pyvips de PNG'yi kurtarmıyor** (343 MB). Hatta 17,3 MP'lik alfalı WebP'de
   WebP çıktısı üretirken `pyvips_tuned` **573 MB** tepe yaptı — korpusun en
   yüksek tek ölçümü, Pillow'un aynı dosyadaki 298 MB'ının **1,9 katı**.

> ### Asıl sonuç
> **Bellek sorunu kütüphane seçimiyle çözülmüyor.** JPEG'de shrink-on-load
> (`draft()` ya da `jpegload(shrink=)`) yardım ediyor; **PNG/WebP'de hiçbir
> motorun kaçışı yok** — tam raster kurulmak zorunda.
>
> Gerçek çözüm **kod çözmeden ÖNCE bir megapiksel kapısı**: başlıktan boyut
> okunur, tavanı aşan dosya reddedilir ya da kuyruğa alınır. Bu, `08-canli-olcum.md`
> §1.3'ün "bugün piksel tavanı politikası **yok**" tespitini doğruluyor ve
> `max_megapixels_hard = 80`'in **72,71 MP'lik dosyayı geçirdiğini** hatırlatıyor.
>
> **Bu, benchmark'ın en önemli çıktısıdır — ve pyvips'ten bağımsızdır.**

---

## 11. ffmpeg görsel yolu

| Ölçüt | Sonuç |
|---|---|
| Süre | 12,68 s — Pillow ile başa baş (1,01×) |
| **Tepe RSS** | **306 MB — korpusun en düşüğü** |
| Çıktı boyutu | 6,75 MB — **en kötüsü** (%9,4 daha şişkin) |
| CMYK rengi | Pillow ile uyumlu (fark 1,5) — §9 |

**Ama semantik olarak eşdeğer DEĞİL:**

- `mjpeg` kalite ölçeği **2..31**'dir, Pillow/libvips'in `quality=85`'i **değildir**.
  `-q:v 3` kullanıldı; bu **yaklaşık** bir eşleştirmedir. Çıktı boyutu bu yüzden
  doğrudan karşılaştırılamaz.
- Durağan görselde **EXIF yönü uygulanmaz**. (Korpusta EXIF rotasyonu olmadığı
  için bu ölçümü etkilemedi — §2.)
- **ICC profili okunmaz/uygulanmaz.**

> **Sonuç:** ffmpeg görsel yolu **çalışıyor** ve belleği en düşük. Ama renk
> yönetimi ve EXIF semantiği yok, kalite ölçeği eşlenemiyor ve her dosya için
> **süreç başlatma** maliyeti var. **Görsel hattı için önerilmiyor.** ffmpeg
> video hattında kalmalı (zaten orada, `transcode.py`).

---

## 12. Karar

### 12.1 Kazanan: **Pillow — `draft()` eklenerek**

**Sayıyla gerekçe:**

| Gerekçe | Ölçüm |
|---|---|
| Canlı görsellerin %90'ı **5,01 MP altında** | pyvips'in kazancı bu bölgede **1,02×–0,97× (yok)** |
| pyvips'in kazandığı bölge (>20 MP) | 4.812 görselin **179'u = %3,7** |
| Kutudan çıktığı hâliyle pyvips | **0,94× — Pillow'dan YAVAŞ** |
| Elle ayarlanmış pyvips | 1,37× — ama §5, §6'daki iki tuzağı bilmeyi gerektiriyor |
| CMYK (38 dosya) | pyvips **0,37×–0,56× yavaş** ve **rengi değiştiriyor** (§9) |
| Çıktı boyutu farkı | **%4** — kararı taşıyacak kadar büyük değil |
| Kalite (SSIM) | Kodlama kaybı **eşit** (0,985–0,998, iki motorda da) |
| `draft()`'ın maliyeti | **iki satır**, yeni bağımlılık **yok**, üretim imajı **değişmiyor** |
| `draft()`'ın getirisi | 72,7 MP dosyada tepe RSS **588 → 172 MB (3,4×)**, süre 624 → 474 ms |
| pyvips'in gerçek maliyeti | Press'in ürettiği **üretim imajına** `libvips42` sokmak (§1) |

### 12.2 Yapılacaklar — öncelik sırasıyla

**1. ŞİMDİ — `engine.optimize`'a `draft()` ekle (Pillow, yeni bağımlılık yok).**

`media/engine.py` içinde, `Image.open(...)`'dan sonra `exif_transpose`'dan önce:

```python
if fmt == "JPEG":
    im.draft(None, (max_dim, max_dim))
```

Ölçülen etki: 72,7 MP JPEG'de tepe RSS **588 → 172 MB**, süre **624 → 474 ms**.
36,2 MP CMYK JPEG'de **309 → 105 MB**, **553 → 217 ms**.
Yan etki: pikseller değişiyor (SSIM 0,9721–1,0000) — **T-006 golden fixture
korpusu (K-10) bu değişikliği yakalamak için ideal ilk müşteri.**

> ⚠ Bu rapor **kod değiştirmedi.** `tradehub_core/` salt okunur ele alındı.

**2. ŞİMDİ — kod çözmeden önce megapiksel kapısı (§10).**
Asıl bellek riski bu; `draft()` PNG/WebP'yi kurtarmıyor. `max_megapixels_hard = 80`
canlıdaki 72,71 MP'lik dosyayı **geçiriyor** — eşik gözden geçirilmeli.

**3. ŞİMDİ — K-11'i "libvips ekle" değil, "ölçüldü, ertelendi" diye kapat.**
Benchmark yapıldı; sonuç pyvips'e geçilmemesi yönünde. Kalem kapanabilir.

**4. SONRA — pyvips'i yalnız şu eşik aşılırsa yeniden değerlendir:**

| Tetik | Eşik |
|---|---|
| Türev üretimi (Faz 2) toplu koşumda darboğaz olursa | ve iş yükünün **>%20'si 15 MP üstü** dosyalardan geliyorsa |
| Sunucuda AVIF/HEIC girdi desteği gerekirse | Pillow'da **HEIF yok** (`07-faz0-kapanis.md` §7.3); libvips 8.14.1'de `.heic`/`.avif`/`.jxl` **var** — pyvips'in bu benchmark'ta ölçülen **tek net üstünlüğü** |
| Tek istekte 30+ türev üretilecekse | `pyvips_tuned` 1,37× → toplu işte anlamlı olabilir |

**pyvips'e geçilirse zorunlu ön koşullar** (bu rapordan):
- CMYK için `jpegload(shrink=N)` zinciri — yoksa **5× yavaş** (§5)
- `export_profile` **koşullu** verilmeli — yoksa renkler kayar (§6)
- 38 CMYK dosyanın renk değişimi **gözle onaylanmalı** (§9)
- `libvips42` **üretim imajına** girmeli — Press tarafı (§1)

---

## 13. Bu raporun ölçmedikleri

| Kalem | Neden |
|---|---|
| **Hangi çıktının gözle daha iyi olduğu** | SSIM fark ölçer, kalite değil. 72,7 MP ve CMYK dosyalarda göz denetimi gerekiyor (§8) |
| ImageMagick | T-007'nin özgün tanımında vardı; konteynerde kurulu değil, kurulmadı |
| AVIF encode maliyeti | T-007 "formatlar arası encode" istiyordu; motor AVIF'i reddettiği için (`SUPPORTED_FORMATS`, K-12 açık) kapsam dışı bırakıldı |
| HEIC/AVIF **girdi** ölçümü | libvips'te destek **var** (suffix listesi ölçüldü), Pillow'da HEIF **yok** — ama karşılaştırmalı ölçüm yapılamadı, korpusta örnek dosya yok |
| Eşzamanlı yük altında davranış | Tüm ölçümler tek koşum. Kuyrukta N paralel worker varken bellek toplamı ölçülmedi — **P-05 için asıl kritik senaryo bu** |
| Üretim ortamı | Yerel `istoc-dev-backend-1`, arm64, 11 vCPU. Üretim imajı Press tarafından üretiliyor; **bu sayılar üretimi doğrulamaz** |
| `engine.optimize`'ın kendi zinciri | Benchmark normalize edilmiş zinciri ölçtü (§3.1); `optimize`'ın format-koruyan yolu ayrıca ölçülmedi |

---

## 14. Yeniden üretim

```bash
# 1) pyvips'i kur — HER force-recreate/rebuild sonrası tekrar gerekir (§1)
docker exec -u root istoc-dev-backend-1 bash -lc \
  "apt-get update && apt-get install -y libvips-dev && \
   /home/frappe/frappe-bench/env/bin/pip install pyvips"

# 2) betiği kopyala
docker exec istoc-dev-backend-1 mkdir -p /home/frappe/bench
docker cp scripts/bench_engine.py istoc-dev-backend-1:/home/frappe/bench/

# 3) koş  (~6 dk, 360 koşum)
docker exec -w /home/frappe/bench istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python bench_engine.py \
  --out /home/frappe/bench/bench.csv --repeats 3

# 4) ham veriyi geri al
docker cp istoc-dev-backend-1:/home/frappe/bench/bench.csv fixtures/bench.csv
```

**Faydalı bayraklar:** `--engines pillow,pyvips_tuned` · `--repeats 5` ·
`--long-edge 1920` · `--no-ssim` · `--files-root <yol>`

> ⚠ **`/tmp`'den koşmayın.** Konteynerin `/tmp` dizininde önceki dalgalardan
> kalma `inspect.py` var; stdlib `inspect`'i gölgeliyor ve `import numpy`
> patlıyor. Betik `/home/frappe/bench` gibi temiz bir dizinden çalıştırılmalı.

**Ham veri:** `fixtures/bench.csv` — 360 satır, 24 sütun, 0 hata.
Sütunlar: `engine, rel, note, out_fmt, quality, long_edge, repeat, ok, inner_s,
outer_s, peak_rss_kb, rss_over_import_kb, out_bytes, out_w, out_h, src_fmt,
src_mode, src_w, src_h, src_mp, src_bytes, src_icc, src_exif_orient, err`

---

## Tekrarlanabilirlik eki — 2026-08-23

- Ham veri yolu gerçekte `docs/reports/bench.csv`: 360 koşum, 0 hata.
- `scripts/bench_engine.py` sabit korpus/motor/tekrar matrisiyle yeniden
  üretilebilir; ölçülen kazanan sayısal olarak Pillow + `draft()` yaklaşımıdır.
- Güncel backend imajı pyvips 2.2.3 / libvips 8.14.1 ve Pillow 12.2.0 taşır;
  böylece iki Python motoru yeniden ölçmek için geçici paket kurulumu gerekmez.
- FFmpeg n8.1.2 ve libvmaf güncel imajda vardır.
- `python -m py_compile scripts/bench_engine.py` Faz 0 CI işinde bloklayıcıdır;
  pahalı 360-koşum benchmark'ı her PR'da değil, motor/codec değişikliğinde
  kontrollü olarak çalıştırılır.

30 MB kaynak benzetiminde karar ölçülüdür: tam decode bellek büyümesi
Pillow'da yüzlerce MiB'ye çıkabilir; `draft()` 72,7 MP örnekte tepe RSS'i
588 MiB'den 172 MiB'ye indirmiştir. Bu yüzden “kütüphane var mı” değil,
decode stratejisi ve worker bellek bütçesi seçim kriteridir.
