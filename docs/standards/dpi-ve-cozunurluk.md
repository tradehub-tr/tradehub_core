# T-024 — DPI ve piksel normalizasyon standardı

**Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2` · **Görev:** T-024
**Test karşılığı:** `tests/test_policy_dpi.py` (19 test, 1 bilinçli `expectedFailure`)
**Policy dosyaları:** `docs/standards/policies/*.json` — 13 slot (+ alan sözleşmesi `policies/_schema.md`)

Bu belge yeniden tasarım değildir. `tradehub_core/media/` altında **8.200 satır**
medya kodu zaten çalışıyor (`wc -l tradehub_core/media/*.py`, T-001 §0'da kayıtlı);
bu standart o kodun DPI ve çözünürlük konusunda **ne yaptığını** yazar, sonra
**neyi yapmadığını** ölçülmüş biçimde işaretler.

---

## 0. Yöntem — bu belgedeki her sayı nereden geldi

| Etiket | Anlamı |
|---|---|
| **[K]** | Kod okundu — `dosya:satır` verildi |
| **[Ö]** | Bu makinede ölçüldü — Pillow 11.3.0, Python 3.9.6 (CommandLineTools), macOS 25.5.0, 2026-08-17. Ölçüm betiği §7'de aynen yazılı |
| **[T]** | Tasarım kararı — gerekçesi yanında |
| **[?]** | ÖLÇÜLEMEDİ → §8'de komutu yazılı |

**Ölçülemeyen:** Docker kapalı; üretim veritabanına ve canlı siteye erişim yok.
Bu belgede **gerçek üretim dosyalarının** piksel dağılımı, gerçek DPI dağılımı ve
üretimdeki Pillow sürümü **YOK**. §8'e bakınız.

> **[Ö] ölçümlerinin sınırı:** test görselleri sentetik **gürültü**dür (her 3-4
> pikselde bir rastgele renk). Gürültü, JPEG/WebP için en kötü durumdur — gerçek
> ürün fotoğrafı aynı piksel boyutunda belirgin olarak daha küçük çıkar. Bayt
> sayıları bu yüzden **üst sınır** olarak okunmalı, tipik değer olarak değil.

---

## 1. Kural

**DPI metadata'dır, piksel değildir. DPI değişimi çözünürlüğü DÜŞÜRMEZ.**

```
DOĞRU : 3000×3000 @300dpi  →  2400×2400 @72dpi
         piksel korundu; yalnız policy'nin uzun kenar TAVANI uygulandı

YASAK : 3000×3000 @300dpi  →   720×720 @72dpi
         72/300 oranı piksele uygulanmış (3000 × 72/300 = 720) — bu bir HATA
```

DPI (dots per inch), bir görselin **baskıdaki fiziksel ölçüsünü** tarif eder:
`fiziksel_inç = piksel / dpi`. 3000 px @300 dpi = 10 inç baskı. Aynı dosya
@72 dpi denildiğinde **hâlâ 3000 px**'tir, yalnız baskıda 41,7 inç kaplar.
Ekranda hiçbir tarayıcı DPI alanına bakmaz — CSS pikseli ve `devicePixelRatio`
kullanır. Bu yüzden web hattında DPI'yi düşürmek **kayıpsız** bir işlemdir;
piksele dokunmak ise geri dönüşü olmayan bilgi kaybıdır.

Tek istisna değil, tek **karışma noktası** şudur: bazı editörler ("Görseli 300
dpi'den 72 dpi'ye çevir" seçeneği) DPI'yi düşürürken **resample** de yapar ve
piksel sayısını 72/300 oranında keser. Bu iki ayrı işlemin tek düğmeye
bağlanmasıdır; ürün hattımızda ikisi **ayrı** kalır:

| İşlem | Ne yapar | Bizde nerede |
|---|---|---|
| **DPI normalizasyonu** | Yalnız metadata; piksel aynı | `engine.optimize` çıktısı (dolaylı — §5) |
| **Uzun kenar tavanı** | Piksel azaltır, oran korunur | `engine.py:117` `im.thumbnail()` |

---

## 2. Mevcut kod ne yapıyor — `engine.optimize()`

`tradehub_core/media/engine.py:96-145`. Format **korunur** (JPEG→JPEG,
PNG→PNG, WEBP→WEBP, TIFF→TIFF); uzantı değişmediği için `file_url` sabit kalır ve
`Listing.primary_image` gibi referanslar kırılmaz (`engine.py:8-9` **[K]**).

Akış:

```
1. Image.open(BytesIO(content))                        engine.py:107
2. fmt not in SUPPORTED_FORMATS → ok=False             engine.py:109-110
   SUPPORTED_FORMATS = {JPEG, PNG, WEBP, TIFF}         engine.py:21     [K]
3. is_animated → ok=False (GIF/animated WebP işlenmez) engine.py:111-112
4. icc = im.info.get("icc_profile")   ← transpose'tan ÖNCE  engine.py:115
5. im = ImageOps.exif_transpose(im)   ← pikseli fiziksel döndürür  engine.py:116
6. im.thumbnail((max_dim, max_dim))   ← YALNIZ KÜÇÜLTÜR  engine.py:117
7. biçime göre save(...) + icc_profile=icc             engine.py:120-133
8. _verify(out) — çıktı gerçekten açılabiliyor mu      engine.py:140-141
```

### 2.1 `im.thumbnail()` yalnız küçültür — bu DOĞRU davranıştır

`engine.py:117`'deki satırın yanındaki yorum (`# yalnız küçültür`) ve
docstring'deki `"Yalnız downscale — upscale yok"` (`engine.py:97`) **[K]** doğru:
Pillow'un `Image.thumbnail()` metodu hedef kutudan **küçük** bir görseli
büyütmez, olduğu gibi bırakır.

**[Ö] Ölçüm:**

| Girdi | `max_dim` | Çıktı | Sonuç |
|---|---|---|---|
| 800×600 @300dpi | 2000 | **800×600** | büyütülmedi ✔ |
| 1200×900 @72dpi | 2560 | **1200×900** | büyütülmedi ✔ |
| 3000×3000 @300dpi | 2400 | **2400×2400** | tavan uygulandı, oran korundu ✔ |
| 4000×2000 @300dpi | 2000 | **2000×1000** | yalnız uzun kenar tavana oturdu ✔ |

Bu davranış **korunmalı**. Gerekçesi: büyütme bilgi eklemez, yalnız bayt ekler
ve arayüzde "yükseltildi" yanılgısı üretir. `min_long_edge` bir **kabul kapısı**
olarak uygulanmalı (yüklerken reddet/uyar), bir **büyütme hedefi** olarak değil.
Policy şemasında bu yüzden `target_long_edge <= max_long_edge` var, alt sınırı
zorlayan bir "upscale_to" alanı **yok**.

### 2.2 `already_small` kapısı — piksele dokunmama kararının tek yeri

`tradehub_core/media/gates.py:70-72` **[K]**:

```python
# Kapı 4 — hedefli yaklaşımın tek uygulama noktası.
if probe.max_dim <= max_dim:
    return GateResult(False, "already_small")
```

Uzun kenarı `max_dim`'i **aşmayan** dosya hiç açılıp yeniden kaydedilmez — bit
düzeyinde aynı kalır, dolayısıyla nesil kaybı riski sıfırdır. `gates.py:7-9`
yorumu bunun ölçüsünü de kaydetmiş: 4.007 dosyanın yalnız ~300'ü bu kapıyı
geçiyor **[K, kod yorumundaki eski ölçüm — bu çalışmada doğrulanmadı]**.

Kapı 5 (`already_optimized`) en başta duruyor (`gates.py:55-56`): bir kez
işlenmiş dosya ikinci kez küçültülmez. **DPI açısından önemli:** aynı dosyanın
iki tur boyunca `thumbnail` görmesi kümülatif kayıp demek olurdu.

### 2.3 Presetler — hangi tavanlar var

`tradehub_core/media/presets.py:13-17` **[K]**:

| preset | `max_dim` | `quality` |
|---|---|---|
| `safe` | 2560 | 90 |
| `balanced` (varsayılan, `presets.py:19`) | **2000** | 88 |
| `aggressive` | 1600 | 82 |

`max_dim` aynı zamanda Kapı 4'ün eşiğidir (`presets.py:5-6` yorumu) — yani
tavan ve "dokunma" eşiği **tek sayı**. Policy JSON'larındaki `max_long_edge`
bu tablonun üstüne çıkamaz; `tests/test_policy_dpi.py::test_max_long_edge_preset_tavanini_asmiyor`
bunu bağlar: motor 4000 px üretemezken policy 4000 ilan ederse ilan edilen sınır
yalan olur.

---

## 3. Mevcut kod ne yapıyor — `engine.to_webp()`

`tradehub_core/media/engine.py:148-181`. `optimize()`'dan **ayrı bir giriş**:
`optimize` formatı korur, `to_webp` **koşulsuz WebP** üretir (TUR-128, sunucu
garanti-WebP). Safari/iOS/Capacitor'da `canvas.toBlob('image/webp')` yok; istemci
o ortamlarda JPEG fallback gönderir, sunucu WebP'ye tamamlar (`engine.py:149-159`
**[K]**).

```
1. Image.open → ImageOps.exif_transpose                engine.py:163-164
2. mode RGB/RGBA değilse: alfa taşıyorsa RGBA, yoksa RGB  engine.py:173-175
   (koşulsuz convert("RGB") şeffaf logoyu opaklaştırıyordu — Fix round 1)
3. im.thumbnail((1920, 1920))   ← SABİT 1920, preset DEĞİL  engine.py:177   [K]
4. save(WEBP, quality=quality, method=4)               engine.py:180
```

Çağıran: `tradehub_core/api/seller_media.py:290-293` **[K]** — `_kaydet()`
içinde, `IMAGE_TO_WEBP_EXTENSIONS` (`seller_media.py:245-247`) uzantılarında
koşulsuz çalışır:

```
.jpg .jpeg .png .bmp .tif .tiff .avif .heic
```

`.webp` ve `.gif` bu kümede **yok** → `.webp` gelen içerik hiç açılmaz, hiç
küçültülmez (`seller_media.py:287-288` yorumu: *"`.webp` uzantısıyla gelen içerik
zaten WebP'yse dokunulmaz — çift sıkıştırma yok"*).

### 3.1 İstemci tarafı da 1920 taşıyor

| Dosya | Sabit | Değer |
|---|---|---|
| `tradehubfront/src/lib/media/compress.image.ts:10` | `HEDEF_GENISLIK` | **1920** **[K]** |
| `tradehubfront/src/lib/media/compress.image.ts:11` | `HEDEF_MAX_MB` | **0.5** **[K]** |
| `admin-panel/frontend/src/lib/media/compress.image.js:9` | `HEDEF_GENISLIK` | **1920** **[K]** |
| `admin-panel/frontend/src/lib/media/compress.image.js:10` | `HEDEF_MAX_MB` | **0.5** **[K]** |

İkisi de `browser-image-compression` ile canvas üzerinden yeniden encode ediyor.
**DPI açısından sonuç:** canvas'a çizilen bir görselin bütün metadata'sı
(EXIF, ICC, DPI) düşer. Yani istemciden geçen her dosya sunucuya **DPI'sız**
gelir; sunucudaki DPI normalizasyonu bu yolda çoğu zaman **konusuz** kalır.
DPI'lı dosya sunucuya yalnız istemci sıkıştırmasını atlayan yollardan girer
(panelin jenerik `upload_file` yolu, bulk import, doğrudan API çağrısı).

---

## 4. [Ö] DPI ölçümü — motor çıktıda DPI ile ne yapıyor

Ölçüm: 3000×3000 gürültü JPEG'i, `dpi=(300,300)` ile kaydedildi; `engine.optimize`
akışı satır satır tekrar edildi (`max_dim=2400`, `quality=88`).

| Aşama | `im.size` | `im.info["dpi"]` | JFIF |
|---|---|---|---|
| Kaynak dosya | 3000×3000 | **(300, 300)** | `jfif_density=(300,300)` |
| `exif_transpose()` sonrası | 3000×3000 | (300, 300) | — |
| `thumbnail((2000,2000))` sonrası | 2000×2000 | **(300, 300)** ← taşınıyor | — |
| `convert("RGB")` sonrası | 2000×2000 | (300, 300) ← taşınıyor | — |
| **JPEG kaydedildikten sonra çıktı** | 2400×2400 | **`None`** | `jfif_density=(1,1)`, `jfif_unit=0` |

Diğer biçimler:

| Yol | Girdi DPI | Çıktı DPI **[Ö]** |
|---|---|---|
| JPEG → JPEG (`engine.py:120-123`) | (300,300) | `None` / `jfif_unit=0` |
| PNG → PNG (`engine.py:126`) | (299.9994, 299.9994) | `None` (pHYs chunk düşüyor) |
| TIFF → TIFF (`engine.py:131`) | (300.0, 300.0) | **(1, 1)** (Pillow varsayılanı) |
| `to_webp` (`engine.py:180`) | (300,300) | `None` — WebP'de DPI alanı yok |

**Yorum:** `thumbnail()` piksel sayısını düşürürken `info["dpi"]`'yi **aynen
bırakıyor** — yani 2000×2000 görsel bellekte hâlâ "300 dpi" diyor (fiziksel
ölçüsü 10 inçten 6,67 inçe düşmüş olmasına rağmen). Bu tutarsızlık diske
yazılmıyor, çünkü Pillow'un JPEG yazıcısı DPI'yi yalnız `encoderinfo`'dan
(yani `save(..., dpi=...)` parametresinden) okur, `im.info`'dan okumaz. Parametre
geçilmediği için **hiçbir DPI yazılmıyor**.

---

## 5. EKSİK — çıktı DPI'sı açıkça 72'ye SET EDİLMİYOR

**Bulgu:** `engine.optimize()` ve `engine.to_webp()` hiçbir yerde `dpi=(72, 72)`
yazmıyor. Kod tabanının tamamında `dpi` geçen tek satır bile yok:

```bash
grep -rn "dpi\|DPI" tradehub_core/media/ tradehub_core/api/    # → 0 sonuç  [Ö]
```

Sonucun iki yüzü var:

**İyi taraf:** girdinin 300 dpi'si çıktıya **taşınmıyor**. Yani "3000 px @300 dpi"
dosyası "2400 px @300 dpi" olarak kaydedilmiyor — kaydedilseydi dosya baskıda
8 inç iddia ederdi ve InDesign/Illustrator kullanan satıcı yanlış ölçü görürdü.

**Eksik taraf:** yerine **72 de yazılmıyor**. JPEG çıktısında `jfif_unit=0`
kalıyor; bu JFIF'te *"mutlak birim yok, yalnız 1:1 piksel en-boy oranı"* demek.
Bunun üç somut sonucu var:

| Sonuç | Neden önemli |
|---|---|
| **A.** Tüketici uygulama kendi varsayılanını uygular | Photoshop/Preview çoğunlukla 72 ppi varsayar → pratikte istediğimiz sonuç. Ama bu bizim garantimiz değil, onların varsayılanı |
| **B.** Kullanıcıya "72 dpi'ye çevirdik" denemez | §6'daki özet metni "300 dpi → 72 dpi" diyecek. Dosyada yazılı 72 yoksa metin **doğrulanabilir değildir**: satıcı dosyayı açıp bakarsa "birim yok" görür |
| **C.** TIFF çıktısı `(1, 1)` diyor | Pillow'un varsayılanı. "1 dpi" fiziksel olarak absürt bir ölçüdür; DTP yazılımında görseli 2000 inç genişliğinde açar |

**Öneri [T]:** `engine.py`'de her `save()` çağrısına `dpi=(72, 72)` eklenmeli
(WEBP hariç — biçimde alan yok). Bu **piksele dokunmayan** bir değişiklik:
`thumbnail()` satırı değişmez, yalnız yazılan metadata netleşir. `tests/
test_policy_dpi.py::test_optimize_ciktisinda_mutlak_dpi_metadatasi_yok` mevcut
durumu sabitliyor; motor düzeltilirse o test kırılır ve **bu bölüm güncellenmelidir**
— testin amacı davranışı savunmak değil, değişimi görünür kılmaktır.

> **T-024 kapsamı gereği kod DEĞİŞTİRİLMEDİ.** `engine.py` bu görevde
> okundu, yazılmadı.

---

## 6. Slot policy'leri ve doğrulanmayan taban

`docs/standards/policies/` altında 13 slot için policy JSON yazıldı. Alan
sözleşmesi `policies/_schema.md`'de. Özet:

| slot_key | ürün mü | `min_long_edge` | `max_long_edge` | oran | tabanın kaynağı |
|---|---|---|---|---|---|
| `listing.primary_image` | ✔ | **2000** | 2560 | 1:1 | T-024 ürün tabanı; render kutusu 512 CSS px **[K]** T-001:131 |
| `listing.gallery_image` | ✔ | **2000** | 2560 | 1:1 | aynı galeri bileşeni **[K]** T-001:132 |
| `listing.variant_image` | ✔ | **2000** | 2560 | 1:1 | ürün ailesi mirası; kutu **[?]** T-001:134 |
| `seller_product.image` | ✔ | **2000** | 2560 | 1:1 | ürün ailesi mirası; kutu **[?]** T-001:152 |
| `seller.banner` | — | 1600 | 2560 | 4:1 | panelin ekranda yazdığı tavsiye 1600×400 **[K]** |
| `brand.hero_banner` | — | 1840 | 2560 | free | kap `--container-lg` = 1840 px **[K]** `style.css:1540-1543` |
| `seo.og_image` | — | 1200 | 2400 | 1.91:1 | OG standardı (harici) + `OgImageUpload.vue:57` **[K]** |
| `category_showcase.tile_image` | — | 1200 | 2000 | free | 2×2 hero varyantı; kesin px **[?]** T-001:120 |
| `seller.gallery_image` | — | 600 | 1600 | 1:1 | 276 CSS px × DPR2 = 552 → 600 **[K]** |
| `review.image` | — | 480 | 1600 | free | alıcı içeriği; sert taban zararlı **[T]** |
| `seller.logo` | — | 400 | 1024 | free | panel tavsiyesi 400×400 **[K]** `DocTypeFormView.vue:448` |
| `brand.logo` | — | 400 | 1024 | free | 128 CSS px × DPR2 = 256; logo ailesiyle hizalandı **[T]** |
| `shipping_channel.icon` | — | 128 | 512 | 1:1 | ikon slotu; kutu **[?]** T-001:149 |

Tabloda 13 satır var; `is_product_slot: true` olan **4** slotun hepsinde
`min_long_edge = 2000`. Ürün-dışı 9 slotun hepsi 2000'in altında —
`tests/test_policy_dpi.py::test_urun_olmayan_slot_urun_tabanini_tasimak_zorunda_degil`
bu ayrımın işlevsiz olmadığını bağlar (ikon slotuna 2000 px taban koymak,
32 CSS px'lik bir kutuya 2000 px dosya yüklenmesini zorunlu kılardı).

Her policy'de `dpi_policy` bloğu var ve üçü de değişmez: `output_dpi: 72`,
`strip_input_dpi: true`, **`pixels_preserved: true`**. Test her policy'de bu üçünü
zorluyor — hiçbir slot "DPI düşünce piksel de düşer" diyemez.

### A1 — AÇIK: ürün tabanı 2000, hat 1920'de kesiyor

**Ölçülmüş çelişki.** Ürün slotları `min_long_edge = 2000` istiyor; yükleme
hattının **üç** noktası uzun kenarı **1920**'ye sabitliyor:

| Nokta | Satır | Değer |
|---|---|---|
| Sunucu garanti-WebP | `tradehub_core/media/engine.py:177` | `im.thumbnail((1920, 1920))` **[K]** |
| Storefront istemcisi | `tradehubfront/src/lib/media/compress.image.ts:10` | `HEDEF_GENISLIK = 1920` **[K]** |
| Panel istemcisi | `admin-panel/frontend/src/lib/media/compress.image.js:9` | `HEDEF_GENISLIK = 1920` **[K]** |

**[Ö]** `engine.to_webp(3000×3000 @300dpi)` → **1920×1920**. Yani 2000 px tabanı
**yükleme anında**, dosya diske yazılmadan önce ihlal ediliyor. Batch optimizer
(`runner.py:229`, `balanced.max_dim = 2000`) bu dosyayı kurtaramaz: `thumbnail`
büyütmez ve Kapı 4 (`1920 <= 2000`) onu `already_small` sayıp hiç açmaz.

`tests/test_policy_dpi.py::TestUploadYoluTabaniKarsilamiyor` bu açığı
`@unittest.expectedFailure` ile **testte** de tutuyor. Test yeşile dönerse
(*unexpected success*) biri tavanı düzeltmiş demektir ve bu madde kapanmalıdır.

**Bayt maliyeti [Ö]** (3000×3000 sentetik gürültü, WebP q80, `method=4`):

| tavan | çıktı | bayt | 1920'ye göre |
|---|---|---|---|
| 1920 | 1920×1920 | 987.436 (0,94 MB) | — |
| **2000** | 2000×2000 | **1.047.028 (1,00 MB)** | **+6,0 %** |
| 2400 | 2400×2400 | 1.781.120 (1,70 MB) | +80,4 % |
| 2560 | 2560×2560 | 2.315.410 (2,21 MB) | +134,5 % |

**Öneri [T]:** üç noktadaki 1920 → **2000** yapılmalı, 2560 değil. 2000 ürün
tabanını **tam** karşılar, `balanced` preseti ile aynı sayıdır (yani Kapı 4 ile
tutarlı kalır) ve maliyeti bu en kötü durum ölçümünde **%6**. 2560'a çıkmak
maliyeti ikiye katlıyor ve karşılığında hiçbir policy'nin `min` değeri
karşılanmıyor — tavan zaten `max`. Alternatif: ürün tabanını 1920'ye düşürmek;
reddedildi çünkü 1920, `presets.py`'deki üç presetin hiçbirine denk gelmiyor ve
"ürün fotosu ile logo aynı çözünürlükte" demek olurdu.

### A2 — AÇIK: `.webp` yükleme hiçbir tavana tabi değil

`seller_media.py:290` `IMAGE_TO_WEBP_EXTENSIONS` kümesinde `.webp` **yok** **[K]**
→ `.webp` uzantısıyla gelen içerik `to_webp`'e hiç girmez, `thumbnail` görmez.
Uzantı kontrolünden geçen tek sınır `upload_policy.py:68` görsel tavanı **25 MB**
**[K]**. İstemci sıkıştırmasını atlayan bir çağrı (doğrudan API, otomasyon, bulk)
8000×8000 bir WebP'yi olduğu gibi kütüphaneye koyabilir.

Bu doğrudan bir DPI sorunu değil, aynı standardın öbür yarısı: **uzun kenar
tavanı her giriş yolunda uygulanmalı**, yalnız dönüşüm gereken yolda değil.

### A3 — AÇIK: yükleme yanıtı ölçü döndürmüyor → §7 metni bugün üretilemez

`seller_media._kaydet()` dönüşü (`seller_media.py:330-336` **[K]**):

```python
{"file_url": ..., "file_name": ..., "bytes": doc.file_size, ...}
```

`bytes` **çıktı** boyutudur. Yanıtta **yok**: girdi boyutu, girdi piksel ölçüsü,
çıktı piksel ölçüsü, girdi DPI'sı. §7'deki özet metni bu dört alan olmadan
yazılamaz. Alanlar `to_webp` çağrısının iki yanında zaten bilinebilir durumda
(`engine.probe()` `engine.py:79-93` girdiyi ölçüyor; `optimize()` çıktı için
`width`/`height` **döndürüyor** — `engine.py:74-76 OptimizeResult`) ama `to_webp`
yolunda hiçbiri toplanmıyor.

**Öneri [T]:** `to_webp`'in yanına ölçü döndüren bir sarmalayıcı (ya da
`OptimizeResult` benzeri bir dönüş) ve `_kaydet` yanıtına `optimization` bloğu:

```json
{
  "file_url": "/files/urun.webp",
  "bytes": 1153433,
  "optimization": {
    "source_width": 3000, "source_height": 3000,
    "output_width": 2400, "output_height": 2400,
    "source_dpi": 300, "output_dpi": 72,
    "source_bytes": 13002342, "output_bytes": 1153433,
    "pixels_preserved": true,
    "reason": null
  }
}
```

`pixels_preserved` alanı arayüz için kritik: metin "piksel korundu" diyecekse
sunucu bunu **söylemeli**, istemci varsaymamalı.

---

## 7. Kullanıcıya gösterilecek özet metni ve i18n anahtarları

### 7.1 Hedef metin

```
Görseliniz optimize edildi: 3000×3000 → 2400×2400 piksel,
300 dpi → 72 dpi (piksel korundu), 12,4 MB → 1,1 MB
```

Metnin taşımak zorunda olduğu üç şey:

1. **Piksel ölçüsü açıkça yazılmalı** — "optimize edildi" tek başına belirsizdir;
   satıcı "ne kadarını kaybettim" sorusunun cevabını görmeli.
2. **DPI satırı "(piksel korundu)" ibaresini TAŞIMAK ZORUNDADIR.** Bu ibare
   olmadan "300 dpi → 72 dpi" cümlesi satıcıya *"çözünürlüğüm %76 düştü"* diye
   okunur (72/300). Ürün fotoğrafı yükleyen bir satıcı için bu, desteğe açılan
   bir ticket ve yeniden yükleme demektir.
3. **Kayıp ile kazanç ayrılmalı** — piksel satırında "azaldı", DPI satırında
   "korundu", bayt satırında "kazanıldı".

Sayı biçimi mevcut yardımcıyla aynı olmalı: `admin-panel/frontend/src/utils/
mediaFormat.js:7-17` `formatBytes()` **[K]** — 1024 tabanı, tek ondalık, ondalık
ayırıcı **virgül** (`.replace(".", ",")`). "12,4 MB" ve "1,1 MB" tam olarak bu
fonksiyonun çıktısıdır. Piksel ayırıcı `×` (U+00D7), `x` değil —
`mediaFormat.js:22` `formatDimensions()` de `×` kullanıyor **[K]**.

### 7.2 Storefront anahtarları — i18next, `{{...}}` interpolasyonu

Dosyalar: `tradehubfront/src/i18n/locales/{tr,en,ar,ru}.ts`. Yerleşim: mevcut
`translation` nesnesi altına `media.optimize` ad alanı. Anahtar biçimi camelCase
(mevcut dosyanın deseni), interpolasyon **çift** süslü parantez.

```ts
media: {
  optimize: {
    // Ana özet — tek satır, bildirim/toast için.
    summary:
      "Görseliniz optimize edildi: {{fromW}}×{{fromH}} → {{toW}}×{{toH}} piksel, " +
      "{{fromDpi}} dpi → {{toDpi}} dpi (piksel korundu), {{fromSize}} → {{toSize}}",

    // Parçalı gösterim — detay panelinde satır satır.
    parts: {
      title: "Görseliniz optimize edildi",
      pixels: "{{fromW}}×{{fromH}} → {{toW}}×{{toH}} piksel",
      pixelsUnchanged: "{{w}}×{{h}} piksel (değişmedi)",
      dpi: "{{fromDpi}} dpi → {{toDpi}} dpi (piksel korundu)",
      dpiUnchanged: "{{dpi}} dpi (değişmedi)",
      size: "{{fromSize}} → {{toSize}}",
      saved: "{{percent}}% daha küçük",
    },

    // Yanlış anlamayı ÖNLEYEN açıklama. "(piksel korundu)" ibaresinin
    // uzun hâli; bilgi ikonunun arkasında durur.
    dpiExplainer:
      "dpi yalnızca baskı ölçüsüdür, çözünürlük değildir. Görselin piksel " +
      "sayısı dpi değiştiği için azalmadı — yalnız {{maxLongEdge}} piksel uzun " +
      "kenar sınırı uygulandı. Ekranda görüntü kalitesi birebir aynıdır.",

    // Hiç dokunulmayan dosya — Kapı 4 (already_small) / Kapı 1 (too_small).
    untouched: "Görseliniz zaten uygun ölçüde; dosyaya dokunulmadı ({{w}}×{{h}} piksel).",

    // Ölçü verisi gelmediğinde (bkz. standardın §6-A3). Sayı UYDURULMAZ.
    summaryUnknown: "Görseliniz optimize edildi. Yeni boyut: {{toSize}}",

    // Policy tabanının altında kalan dosya — reddetmeden önceki uyarı.
    belowMinLongEdge:
      "Bu görselin uzun kenarı {{longEdge}} piksel. Ürün görsellerinde en az " +
      "{{minLongEdge}} piksel öneriyoruz; daha küçük görseller ürün sayfasında " +
      "bulanık görünür.",

    // fit: "cover" olan slotlarda kırpma uyarısı.
    willBeCropped:
      "Bu alan {{ratio}} oranında gösterilir; görselinizin kenarlarından kırpılacak.",
  },
},
```

### 7.3 Panel anahtarları — vue-i18n 11, `{...}` interpolasyonu

Dosyalar: `admin-panel/frontend/src/i18n/locales/{tr,en,ar,ru}.js`.
**Dikkat:** panel `vue-i18n@11` kullanıyor (`admin-panel/frontend/package.json:34`
**[K]**) ve interpolasyon **tek** süslü parantezdir (`locales/tr.js:51`
`"{n} temsilci"` **[K]**). Storefront anahtarlarını kopyalayıp `{{}}` bırakmak
panelde ham metin basar.

```js
media: {
  optimize: {
    summary:
      "Görsel optimize edildi: {fromW}×{fromH} → {toW}×{toH} piksel, " +
      "{fromDpi} dpi → {toDpi} dpi (piksel korundu), {fromSize} → {toSize}",
    parts: {
      title: "Görsel optimize edildi",
      pixels: "{fromW}×{fromH} → {toW}×{toH} piksel",
      pixelsUnchanged: "{w}×{h} piksel (değişmedi)",
      dpi: "{fromDpi} dpi → {toDpi} dpi (piksel korundu)",
      dpiUnchanged: "{dpi} dpi (değişmedi)",
      size: "{fromSize} → {toSize}",
      saved: "{percent}% daha küçük",
    },
    dpiExplainer:
      "dpi yalnızca baskı ölçüsüdür, çözünürlük değildir. Görselin piksel sayısı " +
      "dpi değiştiği için azalmadı — yalnız {maxLongEdge} piksel uzun kenar " +
      "sınırı uygulandı. Ekranda görüntü kalitesi birebir aynıdır.",
    untouched: "Görsel zaten uygun ölçüde; dosyaya dokunulmadı ({w}×{h} piksel).",
    summaryUnknown: "Görsel optimize edildi. Yeni boyut: {toSize}",
    belowMinLongEdge:
      "Bu görselin uzun kenarı {longEdge} piksel. Ürün görsellerinde en az " +
      "{minLongEdge} piksel öneriyoruz; daha küçük görseller ürün sayfasında " +
      "bulanık görünür.",
    willBeCropped:
      "Bu alan {ratio} oranında gösterilir; görselin kenarlarından kırpılacak.",
  },
},
```

### 7.4 Hangi anahtar ne zaman gösterilir

```
sunucu yanıtında optimization bloğu var mı?
├── YOK  → media.optimize.summaryUnknown        (yalnız çıktı boyutu bilinir)
└── VAR
    ├── source_width == output_width
    │     → parts.pixelsUnchanged + (dosya hiç işlenmediyse) untouched
    └── source_width != output_width
          → summary (tek satır)  ya da  parts.* (detay)
              ├── source_dpi == null      → parts.dpi GÖSTERİLMEZ
              │     (istemci canvas'tan geçmiş dosyada DPI yoktur — §3.1)
              ├── source_dpi == output_dpi → parts.dpiUnchanged
              └── source_dpi != output_dpi → parts.dpi  ← "(piksel korundu)" ZORUNLU
```

**Kural:** `parts.dpi` **asla** `parts.pixels` olmadan gösterilmez. DPI satırını
tek başına göstermek, kullanıcının onu çözünürlük satırı sanmasına yol açar —
bu standardın engellemek için yazıldığı tam olarak o hatadır.

### 7.5 Çeviri notu (en/ar/ru)

`(piksel korundu)` ibaresi **çeviri kısaltmasına kurban edilemez**. Çevirmen
notu olarak anahtarların yanına yazılmalı:

| dil | zorunlu ibare |
|---|---|
| tr | `(piksel korundu)` |
| en | `(pixels preserved)` — *"resolution unchanged"* kabul edilir, çıkarılamaz |
| ru | `(пиксели сохранены)` |
| ar | `(تم الحفاظ على البكسل)` — RTL; `×` ve sayılar LTR yönde kalmalı |

Arapça'da `3000×3000` ifadesinin yön kaymasına karşı sayı grubu
`⁦…⁩` (LRI/PDI) ile sarılmalı; `tradehubfront/src/i18n/index.ts` RTL
listesi `ar`'ı içeriyor **[K]** ama sayı yönü için özel bir sarmalayıcı **[?]** —
üretimde göz kontrolü gerekir (§8-M4).

---

## 8. ÜRETİMDE DOĞRULANMALI

Aşağıdakiler bu ortamda **ölçülemedi**: Docker kapalı, üretim veritabanına ve
canlı siteye erişim yok. Her madde için çalıştırılacak **tam komut** yazılıdır.

### M1 — Üretimdeki Pillow sürümü ve DPI davranışı

§4'ün tamamı **Pillow 11.3.0** ile ölçüldü. `requirements.txt` ve
`pyproject.toml` Pillow'u pinlemiyor (**[K]** — ikisinde de geçmiyor); sürüm
Frappe'nin bağımlılığından geliyor. Pillow'un JPEG yazıcısı sürümler arasında
DPI/JFIF davranışını değiştirdiyse §4 tablosu üretimde farklı çıkar.

```bash
docker exec istoc-dev-backend-1 bench --site istoc.cronbi.com console <<'PY'
import PIL, io, random
from PIL import Image, ImageOps
print("Pillow:", PIL.__version__)
im = Image.new("RGB", (3000, 3000))
px = im.load()
random.seed(1)
for y in range(0, 3000, 3):
    for x in range(0, 3000, 3):
        px[x, y] = (random.randrange(256), random.randrange(256), random.randrange(256))
b = io.BytesIO(); im.save(b, "JPEG", quality=95, dpi=(300, 300))
from tradehub_core.media import engine
res = engine.optimize(b.getvalue(), max_dim=2400, quality=88)
print("ok:", res.ok, "reason:", res.reason, "boyut:", res.width, res.height)
with Image.open(io.BytesIO(res.content)) as o:
    print("cikti dpi:", o.info.get("dpi"), "jfif_unit:", o.info.get("jfif_unit"),
          "jfif_density:", o.info.get("jfif_density"))
PY
```

**Beklenen (bu ortamda ölçülen):** `boyut: 2400 2400`, `cikti dpi: None`,
`jfif_unit: 0`, `jfif_density: (1, 1)`. Farklı çıkarsa §4 ve §5 güncellenir.

### M2 — Gerçek dosyaların piksel ve DPI dağılımı

`min_long_edge` tabanları render kutularından türetildi; **kaç mevcut dosyanın
o tabanın altında kaldığı bilinmiyor.** Bu sayı olmadan policy'yi zorunlu kılmak
mevcut ürünleri kırar.

```bash
docker exec istoc-dev-backend-1 bench --site istoc.cronbi.com console <<'PY'
import io, os, collections
import frappe
from PIL import Image
from tradehub_core.media import engine

kova = collections.Counter()
dpiler = collections.Counter()
altinda = []
rows = frappe.get_all("File",
    filters={"is_folder": 0, "attached_to_doctype": ["in", ["Listing", "Listing Image", "Listing Variant Item"]]},
    fields=["name", "file_url", "file_name", "file_size", "attached_to_doctype"], limit_page_length=0)
print("urun gorseli sayisi:", len(rows))
for r in rows:
    yol = frappe.get_site_path(r.file_url.lstrip("/").replace("private/", "private/", 1)) \
        if r.file_url else None
    if not yol or not os.path.exists(yol):
        kova["dosya_yok"] += 1
        continue
    try:
        with Image.open(yol) as im:
            uzun = max(im.size)
            dpiler[im.info.get("dpi")] += 1
    except Exception:
        kova["okunamadi"] += 1
        continue
    if uzun < 1000: kova["<1000"] += 1
    elif uzun < 1600: kova["1000-1599"] += 1
    elif uzun < 1920: kova["1600-1919"] += 1
    elif uzun < 2000: kova["1920-1999"] += 1
    elif uzun < 2560: kova["2000-2559"] += 1
    else: kova[">=2560"] += 1
    if uzun < 2000:
        altinda.append((r.file_name, uzun))
print("uzun kenar dagilimi:", dict(kova))
print("DPI dagilimi (ilk 15):", dpiler.most_common(15))
print("2000 px tabaninin ALTINDA:", len(altinda))
PY
```

**Karar bağlantısı:** `1920-1999` kovası büyükse (§6-A1'in beklediği durum),
tabanın zorunlu kılınması **geçmişe dönük uygulanamaz** — policy yalnız yeni
yüklemelerde zorlanır, mevcut dosyalar uyarı listesine düşer.

### M3 — Render kutuları (tarayıcıda hesaplanmış)

§6 tablosundaki CSS ölçüleri **kaynak koddaki Tailwind sınıflarından** okunup
`1rem = 16px` ile px'e çevrildi. Tarayıcıda hesaplanmış (`getBoundingClientRect`)
değerler **[?]**. `listing.variant_image`, `category_showcase.tile_image`,
`review.image`, `shipping_channel.icon` slotlarında kutu **hiç ölçülemedi**.

```bash
# istoc.cronbi.com açık bir Chrome sekmesinde, DevTools konsolunda:
JSON.stringify([...document.querySelectorAll("img")].map((el) => ({
  src: el.currentSrc.split("/").pop(),
  css: [Math.round(el.getBoundingClientRect().width), Math.round(el.getBoundingClientRect().height)],
  natural: [el.naturalWidth, el.naturalHeight],
  dpr: window.devicePixelRatio,
  fazlalik: +(el.naturalWidth / (el.getBoundingClientRect().width * window.devicePixelRatio)).toFixed(2),
})), null, 2)
```

`fazlalik > 1.5` olan her görsel için `max_long_edge` fazla yüksek demektir;
`fazlalik < 1` ise `min_long_edge` fazla düşük (görsel büyütülerek gösteriliyor).

### M4 — RTL sayı yönü (§7.5)

Arapça arayüzde `3000×3000 → 2400×2400` ifadesinin yön kayması görsel kontrol
ister.

```bash
# Panel/storefront'ta dili ar yap, sonra:
# 1) bir ürün görseli yükle
# 2) optimizasyon özetini ekran görüntüsüyle kaydet
# 3) sayıların sırası (3000×3000 önce, 2400×2400 sonra) korunuyor mu bak
```

### M5 — `.webp` bypass'ının saha etkisi (§6-A2)

```bash
docker exec istoc-dev-backend-1 bench --site istoc.cronbi.com console <<'PY'
import frappe, os
from PIL import Image
buyuk = []
rows = frappe.get_all("File", filters={"is_folder": 0, "file_name": ["like", "%.webp"]},
                      fields=["file_name", "file_url", "file_size"], limit_page_length=0)
print(".webp dosya sayisi:", len(rows))
for r in rows:
    yol = frappe.get_site_path(r.file_url.lstrip("/")) if r.file_url else None
    if not yol or not os.path.exists(yol):
        continue
    try:
        with Image.open(yol) as im:
            if max(im.size) > 2560:
                buyuk.append((r.file_name, im.size, r.file_size))
    except Exception:
        pass
print("2560 px ustu .webp:", len(buyuk))
for x in buyuk[:20]:
    print("  ", x)
PY
```

`len(buyuk) > 0` ise A2 kuramsal değil, sahada gerçekleşmiş demektir.

---

## 9. Testi çalıştırma

```bash
# Bağımsız (Pillow yeter; frappe/bench/DB gerekmez — engine.py'de import frappe YOK)
cd /Users/ahmet/Desktop/istoc-medya-wt && python3 tests/test_policy_dpi.py

# Bench içinde
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_policy_dpi
```

Bu ortamdaki son koşu **[Ö]**: `Ran 19 tests in 7.271s — OK (expected failures=1)`.
Tek `expectedFailure`, §6-A1'deki 1920 tavanıdır ve bilinçlidir.

---

## 10. Değiştirilmeyenler

T-024 kapsamında **hiçbir mevcut kod dosyası düzenlenmedi.** Yalnız yeni dosya
yazıldı:

```
docs/standards/dpi-ve-cozunurluk.md         (bu belge)
docs/standards/policies/_schema.md
docs/standards/policies/*.json              (13 slot)
tests/test_policy_dpi.py
```

Önerilen ama **yapılmayan** kod değişiklikleri: §5 (`dpi=(72,72)`),
§6-A1 (1920 → 2000, üç dosya), §6-A2 (`.webp` tavanı), §6-A3
(`optimization` yanıt bloğu).
