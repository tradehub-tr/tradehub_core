# Faz 1 — AR-GE ve desen doğrulama (T-010…T-019) · tarihsel birleşik rapor

> **2026-08-23 kanonik güncelleme:** Görev kartları artık yayımlıdır; aşağıdaki
> “kartlar yayımlanmadı” varsayımı eskidir. Resmî kabul kriterlerine göre üretilen
> güncel çıktılar `docs/reports/10-algoritma-dogrulama.md` …
> `18-depolama-arge.md`, `docs/adr/README.md` ve
> `docs/closure/faz1-kapanis.md` dosyalarıdır. Çelişkide bu yeni dosyalar
> kazanır. Bu büyük rapor ilk ölçümlerin tarihsel kaydı olarak korunur.

**Tarih:** 2026-08-18 · **Branch:** `ahmet` · **Kapsam:** T-010…T-019 (10 görev)
**Kod çıktısı:** `tradehub_core/media/pipeline/quality/ssim.py`, `tradehub_core/media/pipeline/quality/__init__.py`
**Test çıktısı:** `tests/test_quality_ssim.py` — **21 test, 21 geçti** (yerelde 1 atlandı: numpy yok)
**Ölçüm betikleri:** `scripts/measure_ssim_quality.py`, `scripts/measure_faz1.py`

> **Kaynak sitede bu fazın görev kartları YAYINLANMAMIŞ.** `karacaismail.github.io/
> imageoptimization/docs/` yalnız faz başlığını veriyor ("Faz 1 — AR-GE: desen
> doğrulama ve kıyaslama, T-010…019"); T-010…T-019'un kart metinleri yok
> (2026-08-18'de doğrulandı). Bu belgedeki görev tanımları, sonraki fazların
> bağımlılık atıflarından türetildi; **T-010 ve T-019'u bu belge tanımlıyor** ve
> tanımladığını açıkça söylüyor.

---

## 0. Yöntem — bu belgedeki her sayı nereden geldi

| Etiket | Anlamı |
|---|---|
| **[Ö]** | Bu oturumda ölçüldü. Betik ve ham JSON adı verilir; sayı elle yazılmadı |
| **[K]** | Kod okundu — `dosya:satır` verilir |
| **[D]** | Dış kaynak (satıcı dokümanı). Bizim sistemimizde ÖLÇÜLMEDİ |
| **[T]** | Tasarım kararı — gerekçesi yanında |
| **[?]** | **ÖLÇÜLEMEDİ** — neden ve hangi komutla ölçülebileceği §11'de |

### Ölçüm ortamı

| | Konteyner (birincil) | Yerel (ikincil) |
|---|---|---|
| Kimlik | `istoc-dev-backend-1`, site `istoc.localhost` | macOS 25.5.0 |
| Python | 3.11.6 | 3.9.6 (CommandLineTools) |
| Pillow | 12.2.0 | 11.3.0 |
| numpy | 2.4.6 | **YOK** |
| ffmpeg | 5.1.9-0+deb12u1 | — |
| CPU | 11 vCPU | — |

**Bütün SSIM sayıları konteynerde (numpy yolu) ölçüldü.** Yerelde numpy olmadığı
için `ssim.py`'nin saf Python arka ucu çalışır; iki arka ucun aynı sayıyı verdiği
§T-013.7'de ölçülmüştür (mutlak fark ≤ 4,2e-14).

### Bu belgenin ölçmediği, brifingden ALDIĞI sayılar

Görev brifingindeki canlı ölçümler (4.958 dosya / 1.559 MB, biçim ve mod dağılımı,
MP yüzdelikleri, 179 dosya >20 MP, 1.166 yetim dosya, `th_media_width` %0, ürün
detay sayfası 13,14 MB, srcset 0/31, pyvips 0,94×) **yeniden ölçülmedi**; olduğu
gibi kullanıldı. §T-012 ve §T-018'de kendi disk taramam bunlardan farklı bir
paydayla çalışıyor — fark orada açıkça işaretlendi.

---

## 1. Özet — 10 görev, 10 karar

| Görev | Soru | Karar | Dayanak |
|---|---|---|---|
| **T-010** | Faz 1'in ölçüm çerçevesi ve golden korpusun bütünlüğü sağlam mı? | **HAYIR — 51 fixture'ın 5'i manifest hash'inden sürüklenmiş.** Ölçüm öncesi bütünlük kapısı zorunlu | §T-010 [Ö] |
| **T-011** | Rakipler kaliteyi nasıl seçiyor? | Sabit kalite yerine **içerik-uyarlamalı** seçim sektör normu; imgix `auto=compress` → q45, varsayılan q75 | §T-011 [D] |
| **T-012** | DPI normalizasyonu piksel kaybına yol açıyor mu? Canlıda DPI ne durumda? | Kayıp YOK (T-024'te kilitli). **Canlı görsellerin %7,8'inde DPI metadata var**, en sık değer 220 dpi. **%88,5'i `product.image` master alt sınırı 2000 px'in altında** | §T-012 [Ö] |
| **T-013** | Sabit kalite yerine hedef SSIM'e ikili arama işe yarıyor mu? | **EVET, ama bayt kazancı için değil kalite tabanı için.** Bugünkü q80 hedefi 10 fixture'ın **1'inde** tutuyor, q88 **4'ünde**. Arama 4 encode'da 10/10 çözüyor — aralık (70,95) olursa | §T-013 [Ö] |
| **T-014** | Otomatik odak/saliency kırpma merkez kırpmadan iyi mi? | **Fixture korpusunda ÖLÇÜLEMEZ** (sentetik, enerji düzgün). **Canlı 400 görselde: %14'ünde kayda değer kazanç, %4,5'inde büyük kazanç (>0,10), medyan 0.** Karar: her görsele değil, **eşik üstünde** uygula | §T-014 [Ö] |
| **T-015** | İstemci ön-sıkıştırması sunucuyla çelişiyor mu? | **EVET, iki yerde.** İstemci ve `engine.to_webp` 1920 px'e sabit; `product.image` master alt sınırı 2000 px → bu yoldan **politikaya uygun master üretilemez**. Çift encode cezası ise küçük (SSIM ≤ 0,029) | §T-015 [Ö][K] |
| **T-016** | Video hattı yeterli mi, AV1'e geçilmeli mi? | `needs_transcode` eşikleri 7/7 fixture'da manifest beklentisiyle **uyuşuyor**. AV1 kodlayıcı konteynerde **VAR** ve tek dosyada VP9'a göre %40 küçük çıktı verdi — **ama kalite eşitlenmedi, karar için yeterli değil** | §T-016 [Ö] |
| **T-017** | Yükleme kapısı zararlı içeriği tutuyor mu? | **KISMEN. 10 zararlı fixture'ın 6'sı medya ucundan da kanca yolundan da GEÇTİ.** En ağırı: 100 MP dekompresyon bombası hiçbir kapıya takılmıyor | §T-017 [Ö] |
| **T-018** | Depolamada içerik-adresli tekilleştirme ne kazandırır? | **45,2 MB (%3,9).** 4.341 dosyada 109 tekrar grubu, 110 fazladan kopya. Tek başına yatırımı hak etmiyor; yetim temizliğiyle birlikte anlamlı | §T-018 [Ö] |
| **T-019** | Faz 1 neyi kapatıyor, Faz 2/6'ya ne devrediyor? | 4 karar kapandı, **5 madde ölçülemedi**, 3 bulgu Faz 6'ya (görsel motoru) doğrudan girdi | §T-019 |

---

## T-010 — Ölçüm çerçevesi ve korpus bütünlüğü *(bu belgenin tanımladığı görev)*

**Soru.** Faz 1'in bütün kararları golden fixture korpusuna ve ölçüm betiklerine
dayanacak. Korpus ve betikler, sonuçların tekrar üretilebileceği kadar sağlam mı?

**Yöntem [Ö].** `tests/fixtures/media/manifest.json` içindeki 51 kaydın
`olculen.sha256` alanı, dosyaların bugünkü sha256'sıyla karşılaştırıldı.

**Ölçüm [Ö].** 46 eşleşti, **5 eşleşmedi**:

| fixture | manifest bayt | bugünkü bayt | tanı |
|---|---|---|---|
| `media/images/icc_srgb_embedded.jpg` | 589.057 | 589.057 | **boyut aynı, içerik farklı** — üretim deterministik değil |
| `malicious/fake_docx.docx` | 369 | 369 | **boyut aynı, içerik farklı** (ZIP zaman damgası) |
| `media/video/video_efficient_720p_750k.mp4` | 677.639 | 1.092.127 | yeniden üretilmiş |
| `media/video/video_bloated_720p_8m.mp4` | 6.292.244 | 10.450.180 | yeniden üretilmiş |
| `media/video/video_long_540s_320x240.mp4` | 3.989.924 | 3.986.750 | yeniden üretilmiş |

**İkinci bulgu [K] — GEÇERSİZ, kayıt olarak bırakılıyor.** Bu oturumun başında
`tradehub_core/media/pipeline/__init__.py`'deki `IMPLEMENTED` sözlüğü `core.probe`, `core.state`,
`core.jobs`, `policy.engine` için `True` diyordu ve bu dosyaların **hiçbiri depoda
yoktu**. Oturum sürerken **paralel bir çalışma** (Faz 3) dosyaları ekledi
(`core/probe.py`, `core/state.py`, `core/jobs.py`, `policy/engine.py`,
`core/crop.py`, `core/dedup.py`, `contracts/*`, `fakes/*` ve 6 yeni test dosyası);
bulgu artık **doğru değil**. Kalan ders aynı: `IMPLEMENTED` makine tarafından
okunacaksa **dosya varlığını sınayan bir testle** bağlanmalı — bugün bir bayrağın
doğruluğu yalnız insan disiplinine dayanıyor. Bu faz `"quality.ssim": True`
girdisini ekledi ve karşılığı olan modül ile 21 testi mevcut.

> **Paralel çalışma uyarısı.** `tradehub_core/media/pipeline/core/crop.py` ve `core/dedup.py` bu
> oturumda başka bir el tarafından eklendi; §T-014 (odak) ve §T-018 (tekilleştirme)
> bölümlerimin o modüllerle nasıl birleşeceği **kontrol edilmedi**. Bu belgedeki
> ölçümler `tradehub_core/media/pipeline/quality/` dışındaki hiçbir modüle dokunmaz.

**Karar [T].**
1. Ölçüm koşan her betik, kullandığı fixture'ın sha256'sını **önce doğrulamalı**;
   uyuşmazsa ölçümü "kirli korpus" damgasıyla işaretlemeli. Bu belgedeki T-013
   ölçümleri sürüklenmemiş fixture'larla yapıldı (10'unun 10'u eşleşiyor —
   `icc_srgb_embedded.jpg` hariç; o dosya T-013 §A tablosunda yer alıyor ve
   **sürüklenmiş olduğu buraya not edilir**).
2. Video fixture'ları deterministik üretilmiyor. `scripts/gen_fixtures_video.sh`
   sabit tohum/zaman damgası kullanmadıkça manifest hash'i anlamsızdır — ya betik
   deterministik yapılmalı ya da video için hash yerine ffprobe künyesi
   karşılaştırılmalı.
3. `IMPLEMENTED` sözlüğü, dosya varlığını sınayan bir testle bağlanmalı.

---

## T-011 — Rakip analizi *(masa başı, ölçüm YOK)*

**Soru.** Ticari görsel CDN'leri kaliteyi nasıl seçiyor — sabit mi, uyarlamalı mı?

**Yöntem [D].** Satıcı dokümanları 2026-08-18'de okundu. **Bu bölümde bizim
sistemimizde ölçülmüş tek bir sayı yoktur.**

| Sağlayıcı | Kalite seçimi | Yayımlanmış sayı |
|---|---|---|
| **Cloudinary** `q_auto` | "görseli analiz eder, içeriğe ve tarayıcıya göre en iyi sıkıştırma seviyesini bulur"; `best/good/eco/low` kademeleri | **Sayısal eşleme yayımlanmamış** — yalnız "algısal metrikler ve sezgisel kurallar" deniyor |
| **imgix** | Varsayılan `q=75`. `auto=compress` → **`q=45` + `cs=strip`** | q=75 / q=45 |

**Okuma [T].** İki gözlem bizim için bağlayıcı:

1. **Sabit kalite sektörde de terk edilmiş** — ama sağlayıcıların hiçbiri hedef
   metriği (SSIM/SSIMULACRA/VMAF) ve eşiğini açıklamıyor. Yani "rakip ne yapıyor"
   sorusundan **eşik değeri kopyalanamaz**; kendi korpusumuzda ölçmek zorundayız.
   T-013 tam olarak bunu yapıyor.
2. imgix'in srcset bağlamındaki notu bizim için doğrudan uygulanabilir: yüksek DPR
   türevlerinde kalite belirgin biçimde düşürülebilir, çünkü küçültme artefaktı
   gizler. Bu, **türev başına farklı hedef SSIM** anlamına gelir — `master` için
   0,96, `w384` için daha düşük. Slot politikalarında bugün **tek** hedef var
   (`quality.target_ssim_per_class`), türev başına ayrım yok. Faz 6'ya not.

**Kaynaklar:** [Cloudinary — Image optimization](https://cloudinary.com/documentation/image_optimization) · [imgix — Output Quality](https://docs.imgix.com/en-US/apis/rendering/format/output-quality) · [imgix — Automatic](https://docs.imgix.com/en-US/apis/rendering/automatic)

---

## T-012 — DPI ve normalizasyon

**Soru.** (a) DPI değişimi çözünürlük düşürüyor mu? (b) Canlı korpusta DPI ve
çözünürlük gerçekte ne durumda?

**(a) — daha önce çözülmüş [K].** `docs/standards/dpi-ve-cozunurluk.md` (T-024)
kuralı yazıyor, `tests/test_policy_dpi.py` (19 test) kilitliyor: `engine.optimize`
`im.thumbnail()` kullanır, yalnız küçültür, DPI oranını piksele **uygulamaz**.
Faz 1 bunu yeniden çözmedi; doğruladı ve üstüne ölçüm ekledi.

**(b) — ölçüm [Ö].** `scripts/measure_faz1.py korpus`, çıktı
`t012_t018_korpus.json`. Konteynerde `sites/istoc.localhost/{public,private}/files`
**diskten** yürüdü (DB'ye bakmadı):

| Ölçü | Değer |
|---|---|
| Taranan dosya | 4.341 (1.152.580.291 bayt ≈ 1,15 GB) |
| Bunlardan görsel | 3.999 · Pillow ile açılamayan: 1 |
| **DPI metadata'sı olan** | **311 (%7,8)** |
| DPI metadata'sı olmayan | 3.687 (%92,2) |
| Uzun kenar | p50 **1.200** · p90 2.048 · p99 6.720 · max 10.315 · min 8 |
| Kısa kenar | p50 **1.000** · p90 1.937 · p99 4.456 · max 7.049 · min 8 |
| **Uzun kenarı 2.000 px'in ALTINDA** | **3.540 / 3.998 = %88,5** |

En sık DPI değerleri: **(220,220) → 102 dosya** · (72,72) → 70 · (300,300) → 62 ·
(150,150) → 38 · (96,96) → 31 · (144,144) → 5 · (200,200) → 2 · (180,180) → 1.

> **Payda uyarısı.** Brifingdeki canlı sayı 4.958 dosya / 4.812 görsel / 1.559 MB
> ve kısa kenar p50=1.120. Benim taramam 4.341 dosya / 3.999 görsel / 1.152 MB ve
> p50=1.000 buldu. **İki ölçüm farklı paydalarla çalışıyor** (biri DB `File`
> kayıtları, benimki salt disk yürüyüşü) ve fark açıklanmadı. Yüzdeleri kendi
> paydası içinde okuyun; iki listeyi birbirine oranlamayın. Bu bir **[?]**
> maddesidir, §11'de.

**Karar [T].**
1. **DPI okuma zorunlu değil, YAZMA zorunlu.** Görsellerin %92,2'sinde DPI yok;
   politikanın `master.dpi_out` alanı (çoğu slotta 72) çıktıya **yazılmalı**, aksi
   hâlde "72 dpi'ye normalize edildi" iddiası doğrulanamaz. Bugün `engine.optimize`
   `dpi` parametresi vermiyor **[K]** — Faz 6 işi.
2. **220 dpi'lik 102 dosya** tek bir üretim aracının imzası (tarayıcı ya da katalog
   PDF dönüştürücü). `document.attachment` politikası `dpi_out: 200` diyor; bu 102
   dosyanın hangi slotta olduğu **ölçülmedi** — slot bazlı kırılım gerekiyor.
3. **%88,5'lik alt-sınır ihlali T-015 ile aynı kökten.** Uzun kenar p50'si 1.200,
   `product.image` master alt sınırı 2.000. İstemci 1920'ye kırpıyor (§T-015);
   ama p50 1.200 bundan da düşük, yani sorunun bir kısmı **kaynak görselin kendisi**.
   Politika ya alt sınırı düşürmeli ya da kabul kapısı bu dosyaları reddedip
   satıcıdan daha büyüğünü istemeli. Bu bir **politika kararı**, kod kararı değil.

---

## T-013 — Hedef SSIM'e ikili aramayla kalite seçimi ⭐

> Bu fazın ana kod çıktısı. Bugün kalite **sabit**: `engine.to_webp(data,
> quality=80)` **[K: `tradehub_core/media/pipeline.py:148`]** ve
> `presets.PRESETS` 90/88/82 **[K: `presets.py:14-16`]**. Dokümanın P-13 tuzağı.

### T-013.1 — Ne yazıldı

| Dosya | İçerik |
|---|---|
| `tradehub_core/media/pipeline/quality/ssim.py` | SSIM çekirdeği (iki arka uç), `master_reference`, `search_quality` ikili arama, politika hedef okuma, kaba içerik sınıflandırıcı |
| `tradehub_core/media/pipeline/quality/__init__.py` | Dışa açılan yüzey |
| `tests/test_quality_ssim.py` | 21 test |
| `scripts/measure_ssim_quality.py` | Bu bölümün bütün tablolarını üreten betik |

**Encoder yeniden yazılmadı.** `search_quality` varsayılan olarak
`tradehub_core.media.pipeline.optimize`'ı çağırır (`encode_at`). `master_reference`
yalnız `optimize`'ın **kaydetmeden önceki** hâlini üretir (`exif_transpose` →
`thumbnail` → JPEG ise `convert("RGB")`); `tests/test_quality_ssim.py::
test_referans_geometrisi_engine_ile_ayni` bu iki yolun geometrisini 5 fixture ×
2 boyutta kilitler.

**SSIM tanımı [T].** Wang 2004; `scikit-image`'in **varsayılan** varyantı: 7×7
düzgün pencere, `data_range=255`, K1=0,01 K2=0,03, kovaryansta yansız düzeltme
`NP/(NP−1)`, kenar pencereleri atılır. Gauss ağırlıklı varyant değildir. Bu seçim
bilinçli: hem saf Python integral görüntüyle **birebir** uygulanabiliyor hem de
`structural_similarity(..., gaussian_weights=False)` ile dışarıdan doğrulanabilir.
(Konteynerde `scikit-image` **kurulu değil** — çapraz doğrulama yapılamadı, **[?]**.)

**Ölçek kararı [T].** SSIM ölçeğe duyarlıdır: küçültülmüş kopyada aynı encode daha
yüksek SSIM verir. Bu yüzden karşılaştırma **master çözünürlükte** yapılır. İlk
denememde 512×512'ye küçülterek ölçtüğümde aynı dosya q42'de 0,9938 verdi; master
çözünürlükte q42 için değer **0,96'nın çok altında**. Küçülterek ölçmek, kaliteyi
sistematik olarak fazla iyimser gösterir.

### T-013.2 — Ölçüm düzeni

* **Korpus:** 10 fixture (7 photo, 3 graphic) — kalite parametresinin gerçekten
  etkili olduğu, animasyonsuz, zararsız görseller.
* **Hedef:** `tradehub_core/media/pipeline/policy/slots/product-image.json` →
  `quality.target_ssim_per_class`: **photo 0,96 · graphic 0,98**.
  (Görev brifingi "foto 0,95" diyordu; **politika dosyası 0,96 diyor** ve kaynak
  olarak politika alındı. Fark bilerek not ediliyor.)
* **Master:** `max_long_edge = 2400` (aynı politika), biçim **WebP**
  (`master.format: "webp"`).
* **Yer gerçeği:** q = 40…95 **adım 1**, yani fixture başına 56 encode + 56 SSIM.
* Betik: `scripts/measure_ssim_quality.py` · ham JSON: `ssim_olcum.json`

> **Korpusun sınırı — okumadan tabloya bakmayın.** 10 fixture'ın **6'sı manifest'te
> `kaynak: sentetik`**, 4'ü `canlı-veriden-türetilmiş`. `docs/standards/
> dpi-ve-cozunurluk.md` §0 sentetik fixture'ların **gürültü** olduğunu ve gürültünün
> JPEG/WebP için **en kötü durum** olduğunu yazıyor. Dolayısıyla aşağıdaki "gerekli
> kalite" değerleri **üst sınırdır**; gerçek ürün fotoğrafında hedefi tutan kalite
> daha düşük çıkacaktır. Tablonun kesin sonucu **"q88 yetmez"** değil,
> **"q88'in yetip yetmediği ölçülmeden bilinemez ve bugün ölçülmüyor"**dur.

### T-013.3 — Hedefi tutan minimum kalite [Ö]

| # | fixture | sınıf | master | hedef | **min q** | SSIM@min q | KB@min q | SSIM@q80 | SSIM@q88 |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `ok_product_1x1_2400.jpg` | photo | 2400×2400 | 0,96 | **89** | 0,9649 | 1159 | 0,9083 | 0,9593 |
| 2 | `ok_product_4x5.jpg` | photo | 1920×2400 | 0,96 | **90** | 0,9628 | 896 | 0,8971 | 0,9520 |
| 3 | `enc_progressive.jpg` | photo | 1800×1800 | 0,96 | **88** | 0,9650 | 792 | 0,9147 | 0,9650 |
| 4 | `icc_srgb_embedded.jpg` | photo | 1600×1600 | 0,96 | **88** | 0,9635 | 577 | 0,9159 | 0,9635 |
| 5 | `exif_gps.jpg` | photo | 1600×1600 | 0,96 | **88** | 0,9650 | 686 | 0,9168 | 0,9650 |
| 6 | `mode_cmyk.jpg` | photo | 1600×1600 | 0,96 | **89** | 0,9629 | 756 | 0,8982 | 0,9561 |
| 7 | `enc_webp_lossy.webp` | photo | 1600×1600 | 0,96 | **76** | 0,9629 | 429 | 0,9837 | 0,9808 |
| 8 | `content_border_08pct.png` | graphic | 1400×1400 | 0,98 | **94** | 0,9825 | 384 | 0,9280 | 0,9548 |
| 9 | `mode_palette_p.png` | graphic | 1200×1200 | 0,98 | **92** | 0,9804 | 582 | 0,9136 | 0,9637 |
| 10 | `mode_grayscale_l.png` | graphic | 1400×1400 | 0,98 | **93** | 0,9802 | 161 | 0,9693 | 0,9741 |

**Okuma.**
* Sentetik/gürültülü photo fixture'larında hedef 0,96'yı tutmak için **q88-90**
  gerekiyor. Bugünkü `to_webp` varsayılanı **q80**, o noktada SSIM **0,897-0,918**.
* Grafiklerde hedef 0,98 için **q92-94** gerekiyor; q80'de 0,928-0,969.
* **Tek istisna satır 7** (`enc_webp_lossy.webp`): kaynak zaten WebP olduğu için
  yeniden kodlama ucuz — q76 yetiyor **ve** q80'in SSIM'i (0,9837) q88'inkinden
  (0,9808) **yüksek**. Zaten-WebP kaynağın yeniden kodlanması monoton değil;
  `presets.MIN_SAVING_RATIO` kapısının bu dosyaları hiç işlememesi doğru karar.

**Sabit kalite kaç fixture'da hedefi tutuyor [Ö]:** **q80 → 1/10** · **q88 → 4/10**.

### T-013.4 — İkili arama 4 encode'da ne buluyor [Ö]

| fixture | gerçek min q | arama q | sapma | denenen kaliteler (q→SSIM) | sonuç |
|---|---|---|---|---|---|
| `ok_product_1x1_2400.jpg` | 89 | 92 | +3 | 67→0,835✗ · 81→0,916✗ · 88→0,959✗ · 92→0,978✓ | TUTTU |
| `ok_product_4x5.jpg` | 90 | 92 | +2 | 67→0,854✗ · 81→0,908✗ · 88→0,952✗ · 92→0,974✓ | TUTTU |
| `enc_progressive.jpg` | 88 | 88 | 0 | 67→0,844✗ · 81→0,921✗ · 88→0,965✓ · 84→0,943✗ | TUTTU |
| `icc_srgb_embedded.jpg` | 88 | 88 | 0 | 67→0,842✗ · 81→0,923✗ · 88→0,964✓ · 84→0,944✗ | TUTTU |
| `exif_gps.jpg` | 88 | 88 | 0 | 67→0,838✗ · 81→0,922✗ · 88→0,965✓ · 84→0,942✗ | TUTTU |
| `mode_cmyk.jpg` | 89 | 92 | +3 | 67→0,819✗ · 81→0,906✗ · 88→0,956✗ · 92→0,976✓ | TUTTU |
| `enc_webp_lossy.webp` | 76 | 77 | +1 | 67→0,911✗ · 81→0,984✓ · 74→0,942✗ · 77→0,971✓ | TUTTU |
| `content_border_08pct.png` | 94 | 92 | −2 | 67→0,921✗ · 81→0,930✗ · 88→0,955✗ · 92→0,975✗ | **BÜTÇE YETMEDİ** |
| `mode_palette_p.png` | 92 | 92 | 0 | 67→0,836✗ · 81→0,921✗ · 88→0,964✗ · 92→0,980✓ | TUTTU |
| `mode_grayscale_l.png` | 93 | 92 | −1 | 67→0,967✗ · 81→0,970✗ · 88→0,974✗ · 92→0,978✗ | **BÜTÇE YETMEDİ** |

**Kök neden [Ö].** (40,95) aralığında 4 adımlık ikili aramanın gezebildiği
kaliteler **{67, 81, 88, 92}**'dir. **92 üstü erişilemez** — hedefi q93-94'te tutan
iki grafik bu yüzden çözülemiyor, arama hatası değil aralık hatası.

Aynı ölçülmüş eğriler üzerinde aralık taraması (encode yok, eğri yeniden okundu):

| aralık | 4 encode'da çözülen | ortalama sapma | max sapma |
|---|---|---|---|
| (40, 95) | 8/10 | 1,12 | +3 |
| (50, 95) | 9/10 | 1,22 | +2 |
| (60, 95) | 9/10 | 0,78 | +2 |
| **(70, 95)** | **10/10** | **0,40** | **+1** |
| (75, 95) | 10/10 | 0,30 | +1 |
| (80, 95) | 10/10 | 0,40 | +4 |
| (40, 95) · **5 encode** | 10/10 | 0,40 | +1 |

**Karar [T] — koda işlendi.** `DEFAULT_QUALITY_RANGE = (70, 95)`. Gerekçe
`ssim.py`'de docstring olarak yazılı ve `tests/test_quality_ssim.py::
test_varsayilan_aralik_olcumle_secildi` q94'e erişilebilirliği kilitliyor.
Gerçek minimum 70'in altında olan düşük entropili görsellerde arama 70'e dayanır
ve sonucu `reason="floor_reached"` ile işaretler — çıktı hedefi **tutar**, yalnız
"en düşük" olduğu iddia edilmez.

### T-013.5 — Bayt: kazanç mı, maliyet mi [Ö]

| fixture | min q | KB@min q | KB@q80 | KB@q88 | min/q80 | min/q88 |
|---|---|---|---|---|---|---|
| `ok_product_1x1_2400.jpg` | 89 | 1159 | 685 | 1072 | 1,69× | 1,08× |
| `ok_product_4x5.jpg` | 90 | 896 | 423 | 766 | 2,12× | 1,17× |
| `enc_progressive.jpg` | 88 | 792 | 520 | 792 | 1,53× | 1,00× |
| `icc_srgb_embedded.jpg` | 88 | 577 | 387 | 577 | 1,49× | 1,00× |
| `exif_gps.jpg` | 88 | 686 | 470 | 686 | 1,46× | 1,00× |
| `mode_cmyk.jpg` | 89 | 756 | 412 | 698 | 1,83× | 1,08× |
| `enc_webp_lossy.webp` | 76 | 429 | 457 | 589 | 0,94× | 0,73× |
| `content_border_08pct.png` | 94 | 384 | 95 | 194 | 4,06× | 1,98× |
| `mode_palette_p.png` | 92 | 582 | 296 | 458 | 1,96× | 1,27× |
| `mode_grayscale_l.png` | 93 | 161 | 50 | 81 | 3,23× | 1,99× |
| **TOPLAM** | — | **6423** | 3795 | 5913 | **1,69×** | **1,09×** |

**Bu bölümün en önemli cümlesi:** *bu korpusta hedef SSIM'e uymak baytı
**büyütüyor**, küçültmüyor.* Toplamda hedefi tutan kalite, q80'in **1,69 katı**,
q88'in **1,09 katı** bayt üretiyor. Tek kazanan satır zaten-WebP olan dosya (q80'e
göre 0,94×).

**Yorum [T].** Uyarlamalı kalitenin değeri bu korpusta **bayt tasarrufu değil,
ölçülebilir bir kalite tabanı**dır: bugün "q80 kullanıyoruz" cümlesinin arkasında
hiçbir doğrulama yok; "SSIM ≥ 0,96 garanti ediyoruz" cümlesinin arkasında dosya
başına ölçüm var. Bayt kazancı, korpus gerçek ürün fotoğrafına döndüğünde
(gürültü değil, düz zeminli stüdyo çekimi) beklenir — **ama ÖLÇÜLMEDİ**, §11.

### T-013.6 — Monotonluk: ikili aramanın dayanağı [Ö]

İkili arama SSIM'in kalitede artan olmasını varsayar. 55 komşu kalite çiftinde
ölçülen geri düşüşler:

| fixture | geri düşüş sayısı | en büyük geri düşüş |
|---|---|---|
| `ok_product_1x1_2400.jpg` | 4 | −0,001127 |
| `ok_product_4x5.jpg` | 0 | 0 |
| `enc_progressive.jpg` | 1 | −0,000177 |
| `icc_srgb_embedded.jpg` | 3 | −0,002215 |
| `exif_gps.jpg` | 0 | 0 |
| `mode_cmyk.jpg` | 1 | −0,000282 |
| `enc_webp_lossy.webp` | **6** | **−0,003717** |
| `content_border_08pct.png` | 6 | −0,000122 |
| `mode_palette_p.png` | 0 | 0 |
| `mode_grayscale_l.png` | **13** | −0,000212 |

**Karar [T].** SSIM **kesin** monoton değil, ama en büyük geri düşüş 0,0037 —
hedef eşiklerine (0,96/0,98) göre iki kat küçük mertebede. İkili arama
kullanılabilir; sapma tablosu (§T-013.4) bunun pratik bedelini zaten ölçüyor.
`mode_grayscale_l.png`'nin 13 geri düşüşü tek kanallı görselde WebP'nin kalite
basamaklarını düz geçmesinden; sayı yine de gürültü mertebesinde.

### T-013.7 — İki arka uç aynı sayıyı veriyor mu [Ö]

| fixture | piksel | numpy SSIM | saf Python SSIM | mutlak fark | numpy | saf Python | yavaşlama |
|---|---|---|---|---|---|---|---|
| `logo_alpha_512.png` | 262.144 | 0,999463551831 | 0,999463551831 | 4,2e-14 | 0,035 s | 0,418 s | **12×** |
| `ok_avatar_96.png` | 9.216 | 0,987528077625 | 0,987528077625 | 3,2e-15 | 0,001 s | 0,012 s | 12× |
| `logo_jpeg_noalpha.jpg` | 262.144 | 0,996896725032 | 0,996896725032 | 2,1e-14 | 0,031 s | 0,387 s | 12× |

**Karar [T].** Fark kayan nokta gürültüsü mertebesinde — iki yol aynı fonksiyonu
uyguluyor. Saf Python **12× yavaş**; bu yüzden `PURE_MAX_PIXELS = 512×512` üstünde
görseli küçültür ve sonucu `downscaled=True` ile işaretler. **Üretimde numpy
zorunludur** (konteynerde 2.4.6 kurulu, yerel geliştirme makinesinde yok).

### T-013.8 — İçerik sınıflandırıcı [Ö]

Hedef SSIM sınıfa bağlı olduğu için arama bir sınıf ister. `guess_content_class`
benzersiz luma seviyesi + tepe yoğunlaşmasına bakar. **32 görsel fixture'da
29 doğru = %90,6.** Üç hatanın **üçü de** `graphic → photo` yönünde
(`mode_grayscale_l.png`, `geom_strip_400x4000.png`, `content_border_08pct.png`).

**Karar [T].** Hata **tehlikeli yönde**: grafik, photo sanılırsa hedef 0,98 yerine
0,96 uygulanır ve grafik gereğinden düşük kalitede kodlanır. Bu yüzden
sınıflandırıcı **tek başına karar mercii olamaz**; sıra şu olmalı:
`slot politikası → yükleyen kullanıcının beyanı → sınıflandırıcı`, ve
sınıflandırıcı kararsızsa **daha katı** sınıf seçilmeli. `ssim.py` docstring'i
`text` ve `fine_detail` sınıflarını **üretmediğini** açıkça yazar — o iki sınıfın
ayırt edici ölçütü kalibre edilmedi.

### T-013.9 — Maliyet

Fixture başına tam tarama (56 encode + 56 SSIM, master 1,4-5,8 MP): **15,8-72,6 s**.
4 encode'luk ikili arama: **1,2-5,4 s**. Yani üretimde bir görselin kalite seçimi
**~1-5 saniye** CPU demektir; senkron yükleme yolunda **kabul edilemez**, kuyrukta
kabul edilebilir. `media/jobs.py` zaten kuyruk + backoff sağlıyor **[K]**.

---

## T-014 — Otomatik odak / saliency

**Soru.** 1:1 kırpmada merkez yerine "enerji merkezi" kullanmak özneyi daha çok
korur mu — ve bu, kod yazmayı hak edecek kadar sık mı?

**Yöntem [Ö].** `scripts/measure_faz1.py saliency`. Görsel 512 px'e indirilir,
merkezî fark gradyanıyla kenar enerjisi hesaplanır, enerjinin ağırlık merkezi
bulunur. İki kare kırpma karşılaştırılır: geometrik merkezden ve enerji
merkezinden. Ölçülen, kırpmanın **içinde kalan toplam enerji oranı**.

**Ölçüm 1 — fixture korpusu (n=32) [Ö].** Ortalama kazanç **−0,0000**, en büyük
kazanç **+0,0009**, kazancı 0,01'i aşan **0 dosya**. Sebep açık: fixture'lar
sentetik ve enerji düzgün dağılmış; enerji merkezi zaten geometrik merkez.
**Bu korpusla T-014 kararı verilemez.**

**Ölçüm 2 — canlı örneklem (n=400, tohum 20260818) [Ö].**

| Ölçü | Değer |
|---|---|
| Ortalama kazanç | **+0,0093** |
| Medyan kazanç | **0,0000** |
| p90 kazanç | +0,0182 |
| En büyük kazanç | **+0,4109** (`111001-1.jpg`) |
| Merkez kayması (kısa kenarın oranı) | ortalama 0,0743 · medyan 0,0554 · p90 0,1588 · max 0,4716 |
| Kazanç > 0,01 | **56 / 400 = %14,0** |
| Kazanç > 0,02 | 37 / 400 = %9,3 |
| Kazanç > 0,05 | 24 / 400 = %6,0 |
| Kazanç > 0,10 | **18 / 400 = %4,5** |

En büyük 3 örnek: `111001-1.jpg` merkez 0,589 → odak **1,000**; `111801-1.jpg`
0,637 → **1,000**; `0549.jpg` 0,610 → 0,898.

**Karar [T].**
1. **Saliency her görsele uygulanmaz.** Medyan kazanç sıfır — dosyaların yarısında
   enerji merkezi zaten merkezde ve hesap boşa gider.
2. **Eşik kuralı:** merkez kayması kısa kenarın **%10'unu** aştığında odak noktası
   önerilir. Bu eşik ölçülen dağılımdan (p90 = 0,1588) türetildi, literatürden değil.
3. Sonuç **öneri**dir, otomatik uygulama değil: %4,5'lik kuyruk büyük kazanç
   veriyor ama kenar enerjisi **özne ≠ enerji** varsayımına dayanıyor; desenli fon
   ya da filigran bu ölçüyü kandırır. Faz 10 (Crop Studio) kullanıcı onayını
   zaten sağlıyor — odak noktası oraya **başlangıç değeri** olarak beslenmeli.
4. **[?] Doğrulanmadı:** kenar enerjisi merkezi ile insanın seçtiği odak noktası
   arasındaki uyum ölçülmedi (etiketli veri yok).

---

## T-015 — İstemci ön-sıkıştırma (preflight)

**Soru.** İstemci tarafı sıkıştırma sunucu politikasıyla çelişiyor mu, ve çift
encode ne kadar kalite yiyor?

### T-015.1 — Kod okuması [K]

| Katman | Dosya | Davranış |
|---|---|---|
| Storefront | `tradehubfront/src/lib/media/compress.image.ts:10-11` | `HEDEF_GENISLIK = 1920`, `HEDEF_MAX_MB = 0.5` |
| Storefront | aynı dosya, satır 44-77 | WebP q0,80; Safari'de WebP çıkmazsa **JPEG q0,85** ile ikinci geçiş |
| Admin panel | `admin-panel/frontend/src/lib/media/compress.image.js:9,38-39` | **aynı sabitler** (1920 / 0,5 MB) |
| Sunucu | `tradehub_core/media/pipeline.py:148` + `:177` | `to_webp(data, quality=80)`; içeride `im.thumbnail((1920, 1920))` **sabit** |
| Sunucu | `tradehub_core/api/seller_media.py:293` | `engine.to_webp(icerik)` — kalite **verilmiyor**, varsayılan 80 |
| Politika | `tradehub_core/media/pipeline/policy/slots/product-image.json` | `master.min_long_edge = 2000`, `max_long_edge = 2400` |

**Bulgu 1 — çelişki, tek satırda:** yükleme zincirinin **üç** katmanı da 1920 px
tavanı uyguluyor; `product.image` master'ının **alt** sınırı 2000 px.
**Bu yoldan politikaya uygun bir master üretilemez.** §T-012'deki "%88,5 dosya
2000 px altında" ölçümü bu çelişkinin canlıdaki izidir.

**Bulgu 2 — 0,5 MB tavanı kalite hedefiyle çelişiyor:** §T-013 tablosuna göre
hedefi tutan master'lar **161-1.159 KB**; 7 fixture'ın 5'i 500 KB'ı aşıyor.
İstemcinin 0,5 MB tavanı bu dosyaları **daha yüklenmeden** hedefin altına indirir.

### T-015.2 — Çift encode cezası [Ö]

`scripts/measure_faz1.py preflight`. İki yol, ikisi de aynı 1920 px referansa göre:
**A)** orijinal → WebP q80. **B)** orijinal → JPEG q85 (istemci) → WebP q80 (sunucu).

| fixture | master | A: tek geçiş SSIM | B: çift geçiş SSIM | **SSIM cezası** | A bayt | B bayt | bayt farkı |
|---|---|---|---|---|---|---|---|
| `ok_product_1x1_2400.jpg` | 1920×1920 | 0,8878 | 0,8590 | **+0,0288** | 342.540 | 306.102 | −36.438 |
| `ok_product_4x5.jpg` | 1536×1920 | 0,8997 | 0,8777 | +0,0221 | 271.162 | 257.540 | −13.622 |
| `enc_progressive.jpg` | 1800×1800 | 0,9147 | 0,9147 | +0,0000 | 532.116 | 531.990 | −126 |
| `icc_srgb_embedded.jpg` | 1600×1600 | 0,9159 | 0,9159 | −0,0000 | 396.682 | 396.586 | −96 |
| `exif_gps.jpg` | 1600×1600 | 0,9168 | 0,9201 | **−0,0034** | 481.254 | 558.842 | +77.588 |
| `edge_short4480.jpg` | 1536×1920 | 0,9765 | 0,9758 | +0,0007 | 148.130 | 149.734 | +1.604 |

**Okuma.**
* Çift encode cezası **en fazla 0,0288 SSIM**; iki dosyada **negatif** (istemcinin
  JPEG'i bir ön-filtre gibi davranıp entropiyi düşürüyor, sonraki WebP daha iyi
  eşleşiyor). Yani "istemci sıkıştırması kaliteyi mahvediyor" **doğru değil**.
* Asıl bulgu tabloda yan yana duruyor: **tek geçişte bile SSIM 0,888-0,977**, yani
  6 dosyanın **5'i** `product.image`'ın photo hedefi 0,96'yı **tutmuyor** —
  ve bu, çift encode olmadan, sunucunun kendi q80'iyle.

**Karar [T].**
1. **İstemci ön-sıkıştırması kaldırılmasın** (mobil yükleme süresi için gerçek
   fayda; kalite cezası ölçüldü, küçük). Ama **1920/0,5 MB sabitleri sunucudan
   gelmelidir**: `upload_policy.limits()` zaten istemciye sınır yayınlıyor **[K:
   `upload_policy.py:398`]**; slot politikasının `master.min_long_edge` /
   `max_long_edge` değerleri de aynı uçtan yayınlanmalı, istemcide sabit durmamalı.
2. `engine.to_webp`'in içindeki **1920 sabiti parametreye çıkarılmalı** — bugün
   hangi slot olursa olsun 1920. Bu, `to_webp`'i çağıran tek yerin
   (`api/seller_media.py:293`) slot bilmemesinden kaynaklanıyor; slot bilgisi
   oraya taşınmadan bu düzelmez.
3. Kalite hedefi karşılanamıyorsa **sessizce devam edilmemeli**: `search_quality`
   `ok=False` + `reason` döndürüyor; yükleme yolu bunu kullanıcıya "bu görsel
   hedeflenen kalitede yayımlanamıyor, daha büyük bir dosya yükleyin" diye
   göstermeli.

---

## T-016 — Video AR-GE

**Yöntem [Ö].** `scripts/measure_faz1.py video` + tek dosyalık kodlayıcı
karşılaştırması. ffmpeg **5.1.9-0+deb12u1**.

### T-016.1 — Kodlayıcı envanteri [Ö]

| kodlayıcı | konteynerde |
|---|---|
| `libvpx-vp9` (bugün kullanılan) | **VAR** |
| `libsvtav1` | **VAR** (SVT-AV1 v1.4.1) |
| `libaom-av1` | **VAR** |
| `libx264` | VAR |
| `libopus` (bugün kullanılan) | VAR |
| `libwebp` | VAR |

### T-016.2 — Eşikler gerçekle uyuşuyor mu [Ö][K]

`transcode.py`: `NEEDS_TRANSCODE_MAX_WIDTH = 1280`, `NEEDS_TRANSCODE_MAX_BITRATE =
2.500.000` **[K: `transcode.py:98-99`]**; encode zinciri
`scale='min(1280,iw)':-2 -c:v libvpx-vp9 -b:v 0 -crf 32 -c:a libopus`
**[K: `transcode.py:356-360`]**.

| fixture | ölçülen | eşik kararı | manifest beklentisi | uyum |
|---|---|---|---|---|
| `video_16x9_1080p.mp4` | 1920×1080, 1,51 Mbps | **transcode** (genişlik) | process | ✓ |
| `video_bloated_720p_8m.mp4` | 1280×720, 8,36 Mbps | **transcode** (bitrate) | process | ✓ |
| `video_efficient_720p_750k.mp4` | 1280×720, 0,87 Mbps | passthrough | passthrough | ✓ |
| `video_silent_noaudio_720p.mp4` | 1280×720, 0,84 Mbps, sessiz | passthrough | passthrough | ✓ |
| `video_vertical_9x16.mp4` | 720×1280, 1,02 Mbps | passthrough | passthrough | ✓ |
| `video_long_540s_320x240.mp4` | 320×240, 540 s, 59 kbps | passthrough | passthrough | ✓ |
| `video_square_352.mp4` | 352×352, 0,39 Mbps | passthrough | passthrough | ✓ |

**7/7 uyum.** Eşikler bu korpusta doğru sınıflandırıyor.

### T-016.3 — AV1 denemesi [Ö] — *tek dosya, kalite EŞİTLENMEDİ*

`video_16x9_1080p.mp4` (1.131.368 bayt, 6 s), hepsi `scale='min(1280,iw)':-2`:

| ayar | çıktı bayt | süre | VP9'a göre |
|---|---|---|---|
| `libvpx-vp9 -crf 32 -b:v 0` (**bugünkü**) | 1.071.530 | 7,87 s | — |
| `libsvtav1 -crf 35 -preset 8` | **640.641** | 8,28 s | **−%40** |
| `libsvtav1 -crf 40 -preset 8` | 364.988 | 8,00 s | −%66 |
| `libx264 -crf 23 -preset medium` | 1.030.414 | **0,70 s** | −%4 |

**Karar [T] — HENÜZ KARAR YOK.** Bu tablo bir kıyaslama **değildir**: VP9 crf 32
ile AV1 crf 35 aynı algısal kaliteyi vermez, CRF ölçekleri farklıdır ve **kalite
hiç ölçülmedi** (VMAF/SSIM yok, n=1, fixture sentetik). Söylenebilecek tek şey:
**AV1 kodlayıcı mevcut ve encode süresi VP9'la aynı mertebede** — yani AV1'e
geçişin önündeki engel CPU değil. Karar için gereken ölçüm §11'de.

**Yan bulgu [K]:** `product.video` politikası `master.format: "webm"`,
`max_long_edge: 1280` diyor; `transcode.py` da 1280'e ölçekliyor — **uyumlu**.
Ancak `company.cover_video` `min_long_edge: 1280` **ve** `max_long_edge: 1280`
istiyor; `scale='min(1280,iw)'` yalnız küçültür, 1280'in altındaki kaynak
büyütülmez → alt sınır **sağlanamaz**. `product.image`'daki 1920/2000 çelişkisinin
video karşılığı. **[?] Canlı videolarda ne sıklıkta olduğu ölçülmedi** (canlıda
yalnız 23 video var).

---

## T-017 — Güvenlik: yükleme kapısı ve SVG

**Yöntem [Ö].** 51 fixture, `tradehub_core.media.upload_policy.check()`'ten iki
uçtan geçirildi: `media_endpoint=True` (dar izin listesi) ve `False` (kanca yolu).
Konteynerdeki `upload_policy.py` çalışma kopyasından **iki noktada** farklı
(`QUOTA_EXCEEDED` kodu ve `frappe.local.response` try/except); ikisi de kapı
mantığını **değiştirmiyor** — diff alındı, doğrulandı.

### T-017.1 — 10 zararlı fixture, ölçülen karar [Ö]

| fixture | sniff | `is_dangerous` | medya ucu | kanca yolu | Pillow künyesi |
|---|---|---|---|---|---|
| `bomb_100mp.png` | png | False | **GEÇTİ** | **GEÇTİ** | PNG L 10000×10000 = **100 MP** |
| `executable_as.png` | — | False | **GEÇTİ** | **GEÇTİ** | açılamadı |
| `jpeg_with_html_tail.jpg` | jpeg | False | **GEÇTİ** | **GEÇTİ** | JPEG RGB 320×320 |
| `polyglot_pdf_as.jpg` | pdf | False | **GEÇTİ** (uyarı: `uzanti=.jpg icerik=pdf`) | **GEÇTİ** (aynı uyarı) | açılamadı |
| `polyglot_png_as.jpg` | png | False | **GEÇTİ** (uyarı: `uzanti=.jpg icerik=png`) | **GEÇTİ** (aynı uyarı) | PNG RGBA 256×256 |
| `truncated.jpg` | jpeg | False | **GEÇTİ** | **GEÇTİ** | JPEG RGB 1600×1200 |
| `script_payload.svg` | — | **True** | RED `upload_ext_denied` | RED `upload_ext_denied` | açılamadı |
| `empty_zero_byte.jpg` | — | False | RED `upload_content_empty` | RED `upload_content_empty` | açılamadı |
| `data_uri_svg.txt` | — | False | RED `upload_ext_not_allowed` | **GEÇTİ** | açılamadı |
| `fake_docx.docx` | zip | False | RED `upload_ext_not_allowed` | **GEÇTİ** | açılamadı |

**Skor:** medya ucu **4/10** reddediyor, kanca yolu **2/10**. **6 dosya iki
kapıdan da geçiyor.** Temiz fixture'ların hiçbiri yanlışlıkla reddedilmedi
(yanlış pozitif **0/41**).

### T-017.2 — Neden geçiyorlar [K]

1. **`is_dangerous` yalnız ilk 512 baytın BAŞINA bakıyor** (`upload_policy.py:214-
   224`: `bas = icerik[:512].lstrip(...)` + `startswith`). Geçerli bir JPEG/PNG
   başlığının **arkasına** eklenen `<script>`/HTML gövdesi hiç görülmez —
   `jpeg_with_html_tail.jpg` tam bu.
2. **SVG yalnız UZANTIYLA engelleniyor.** `script_payload.svg` `upload_ext_denied`
   ile düşüyor; ama içeriği `.jpg` adıyla gönderilse `is_dangerous` onu **yakalar**
   (baş kısımda `<svg`). Yani SVG koruması iki kapılı ve çalışıyor — **fakat
   `defusedxml` bağımlılığı `pyproject.toml`'da olmasına rağmen `media/` altında
   HİÇ KULLANILMIYOR** (`grep -rn defusedxml tradehub_core/media/` → 0 sonuç).
   SVG hiç ayrıştırılmıyor, sadece reddediliyor. Bu **savunulabilir** bir tasarım,
   ama "SVG sanitize ediyoruz" denmemeli.
3. **Megapiksel kapısı YOK.** `check()` yalnız **bayt** bakıyor
   (`effective_max(tur)`); `bomb_100mp.png` 97 KB olduğu için tüm kapıları geçiyor
   ve 100 MP olarak decode ediliyor. Politikada `accept.max_megapixels_hard: 80`
   **tanımlı** ama `upload_policy` bu alanı hiç okumuyor — politika ile kod
   arasında bağ yok. Brifingdeki "179 dosya >20 MP" bulgusunun kod tarafındaki
   karşılığı budur.
4. **`executable_as.png` sessizce geçiyor**: `sniff()` imzayı tanımadığı için boş
   döner, `_uyumlu()` "bilinmeyen tür uyuşmazlık sayılmaz" der ve **uyarı bile
   üretilmez** (`upload_policy.py:392-395`). Tanınmayan imza + görsel uzantısı
   kombinasyonu en azından uyarı üretmeli.

**Karar [T] — öncelik sırasıyla:**
1. **Megapiksel kapısı ekle** (P0): `check()` görsel türlerde başlıktan
   `width×height` okuyup `accept.max_megapixels_hard`'a vurmalı. Başlık okuması
   tam decode gerektirmez — `Image.open` lazy'dir, `.size` decode etmez.
2. **Tanınmayan imza + görsel uzantısı → uyarı** (P1).
3. **Kuyruk (tail) taraması** (P2): dosya sonunda `<script`/`<html` aramak;
   ya da daha sağlamı, kabul edilen her rasteri **yeniden kodlamak** — ki
   `engine.optimize` zaten bunu yapıyor, dolayısıyla polyglot'un asıl riski
   "işlenmeden servis edilen" yollarda (`document.attachment` `format: preserve`).
4. `truncated.jpg` gibi dosyalar kapıyı geçip **motorda** düşer — kabul edilebilir,
   ama ret kodu `upload_content_unreadable` tanımlıyken kullanılmıyor.

---

## T-018 — Depolama

**Yöntem [Ö].** Aynı disk yürüyüşü (§T-012), her dosyanın tam sha256'sı.

| Ölçü | Değer |
|---|---|
| Dosya | 4.341 · 1.152.580.291 bayt |
| Benzersiz içerik | 4.231 |
| Tekrar grubu | **109** |
| Fazladan kopya | **110** |
| **Geri kazanılabilir** | **45.184.596 bayt = 45,2 MB (%3,9)** |

En büyük 5 tekrar grubu (hepsi 2 kopya): `private/files/katalog görseldf1091.zip`
19,9 MB · `private/files/files196193e.zip` 15,2 MB ·
`public/files/sitemaps/sitemap-categories.xml` 7,4 MB ·
`private/files/filesc4fa56.zip` 4,6 MB ·
`public/files/Gemini_Generated_Image_np9h1enp9h1enp9h.png` 4,0 MB.

**Okuma [T].**
1. **İçerik-adresli adlandırma zaten var** — `media/naming.py` sha256 + hash-prefix
   shard uyguluyor **[K]**. Yani tekilleştirme yeni kod değil, **kapsam** sorunu:
   45,2 MB'lık tekrarın büyük kısmı `.zip` ve `.xml`, yani `naming.py`'nin
   yolundan geçmeyen dosyalar.
2. **%3,9 tek başına yatırımı hak etmiyor.** Karşılaştırma: brifingdeki **1.166
   yetim disk dosyası** çok daha büyük bir kalem ve `media/inventory.py` +
   `refs.py` zaten yetim tespitini yapabiliyor **[K]**. Depolama işinin sırası:
   **önce yetim temizliği, sonra tekilleştirme**.
3. Tekilleştirme uygulanacaksa **referans sayacı** şart (`media/refs.py` var);
   sayaçsız hard-link/silme, ortak dosyayı silen ilk kullanıcının diğerlerinin
   görselini kırmasına yol açar.

---

## T-019 — Faz 1 kapanışı *(bu belgenin tanımladığı görev)*

### Kapanan kararlar

| # | Karar | Nerede uygulandı |
|---|---|---|
| K-1 | SSIM = 7×7 düzgün pencere, skimage varsayılan varyantı; master çözünürlükte ölçülür | `tradehub_core/media/pipeline/quality/ssim.py` |
| K-2 | Kalite araması: ikili arama, **4 encode**, aralık **(70,95)** — ölçümle seçildi | `ssim.py::DEFAULT_QUALITY_RANGE` + test |
| K-3 | Hedef SSIM **koda gömülmez**, slot politikası JSON'undan okunur; `bit_exact` slotlarda arama yapılmaz | `ssim.py::target_for` |
| K-4 | Encoder yeniden yazılmaz; `engine.optimize` sarılır, geometri testle kilitlenir | `ssim.py::master_reference` + test |
| K-5 | Saliency her görsele değil, **kayma > %10** eşiğinde uygulanır ve **öneri**dir | karar; kod Faz 10 |

### Faz 6'ya (Görsel motoru) devredilen, ölçülmüş girdiler

1. **q80 hedefi 10 fixture'ın 1'inde tutuyor** (§T-013.3) — `to_webp`'in sabit
   kalitesi Faz 6'da `search_quality` ile değişmeli.
2. **1920 vs 2000 çelişkisi** (§T-015.1) — `to_webp`'in sabit 1920'si slot
   parametresine çıkarılmalı; istemci sabitleri sunucudan yayınlanmalı.
3. **Megapiksel kapısı yok** (§T-017.2) — `accept.max_megapixels_hard` koda
   bağlanmalı.

### Faz 2'ye (Standartlar) geri giden sorular

* `product.image` `master.min_long_edge = 2000`, canlı görsellerin **%88,5'i**
  altında (§T-012). Politika mı iner, kabul kapısı mı reddeder?
* `quality.target_ssim_per_class` **türev başına** ayrışmalı mı (§T-011 okuması)?
* Brifing "photo 0,95" diyor, politika 0,96. Hangisi bağlayıcı?

---

## 11. ÖLÇÜLMEDİ — açık kalanlar ve ölçüm komutları

| # | Ölçülmeyen | Neden | Komut / gereken |
|---|---|---|---|
| Ö-1 | **Gerçek ürün fotoğrafında hedefi tutan kalite** | T-013 korpusunun 6/10'u sentetik gürültü = en kötü durum | `measure_ssim_quality.py --fixtures <canlı örneklem klasörü>`; canlı görsellerden 30-50'lik tabakalı örneklem gerekiyor |
| Ö-2 | **SSIM'in `scikit-image` ile çapraz doğrulaması** | konteynerde `scikit-image` kurulu değil | `pip install scikit-image` + `structural_similarity(a,b,data_range=255)` karşılaştırması |
| Ö-3 | **AV1 vs VP9 kalite-eşitli kıyas** | VMAF yok, n=1, kalite eşitlenmedi | `libvmaf` derlenmiş ffmpeg; eşit VMAF'ta bayt ve süre karşılaştırması, ≥10 gerçek video |
| Ö-4 | **Disk taraması ile DB sayımı arasındaki fark** (4.341 vs 4.958) | iki ölçüm farklı payda kullanıyor, fark açıklanmadı | `File` doctype sayımı ile disk yürüyüşünün küme farkı |
| Ö-5 | **220 dpi'lik 102 dosyanın slot dağılımı** | slot bazlı kırılım yapılmadı | `usage.py` LIVE_SOURCES ile join |
| Ö-6 | **Saliency merkezinin insan seçimiyle uyumu** | etiketli veri yok | 100 görselde elle odak işaretlemesi |
| Ö-7 | **`company.cover_video` alt sınırının canlıdaki ihlali** | canlıda 23 video var, taranmadı | ffprobe ile 23 videonun künyesi |
| Ö-8 | **ruff** | ne yerelde ne konteynerde kurulu | `pip install ruff && ruff check media_engine tests scripts` |

---

## 12. Yeniden üretme

```bash
# 0) kod + fixture'ları konteynere taşı
docker exec istoc-dev-backend-1 mkdir -p /home/frappe/olcum
docker cp media_engine  istoc-dev-backend-1:/home/frappe/olcum/
docker cp tests         istoc-dev-backend-1:/home/frappe/olcum/
docker cp scripts/measure_ssim_quality.py istoc-dev-backend-1:/home/frappe/olcum/
docker cp scripts/measure_faz1.py         istoc-dev-backend-1:/home/frappe/olcum/
docker exec istoc-dev-backend-1 mkdir -p /home/frappe/olcum/tradehub_core/media
docker cp tradehub_core/media/pipeline.py  istoc-dev-backend-1:/home/frappe/olcum/tradehub_core/media/
docker cp tradehub_core/media/presets.py istoc-dev-backend-1:/home/frappe/olcum/tradehub_core/media/
docker exec istoc-dev-backend-1 touch /home/frappe/olcum/tradehub_core/__init__.py \
                                      /home/frappe/olcum/tradehub_core/media/__init__.py

# 1) T-013 — ~5 dakika
docker exec -w /home/frappe/olcum istoc-dev-backend-1 ../frappe-bench/env/bin/python \
  measure_ssim_quality.py --fixtures /home/frappe/olcum/tests/fixtures --out ssim_olcum.json

# 2) T-012 + T-018 · T-014 · T-015 · T-016
docker exec -w /home/frappe/olcum istoc-dev-backend-1 ../frappe-bench/env/bin/python \
  measure_faz1.py korpus    --out t012_t018_korpus.json
docker exec -w /home/frappe/olcum istoc-dev-backend-1 ../frappe-bench/env/bin/python \
  measure_faz1.py saliency  --kaynak canli --ornek 400 --out t014_canli.json
docker exec -w /home/frappe/olcum istoc-dev-backend-1 ../frappe-bench/env/bin/python \
  measure_faz1.py preflight --fixtures /home/frappe/olcum/tests/fixtures --out t015_preflight.json
docker exec -w /home/frappe/olcum istoc-dev-backend-1 ../frappe-bench/env/bin/python \
  measure_faz1.py video     --fixtures /home/frappe/olcum/tests/fixtures --out t016_video.json

# 3) T-017 — frappe gerekir; kurulu app'in upload_policy'si kullanılır
docker exec istoc-dev-backend-1 mkdir -p /home/frappe/olcum_sec
docker cp scripts/measure_faz1.py istoc-dev-backend-1:/home/frappe/olcum_sec/
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 ../env/bin/python \
  /home/frappe/olcum_sec/measure_faz1.py guvenlik \
  --fixtures /home/frappe/olcum/tests/fixtures --out /home/frappe/olcum/t017_guvenlik.json

# 4) testler
python3 -m unittest tests.test_quality_ssim -v                      # yerel (numpy yok)
docker exec -w /home/frappe/olcum istoc-dev-backend-1 \
  ../frappe-bench/env/bin/python tests/test_quality_ssim.py         # konteyner (numpy var)
```

**Test sonucu [Ö]:** yerelde 21 test / 20 geçti + 1 atlandı (numpy yok);
konteynerde **21 test / 21 geçti**.
