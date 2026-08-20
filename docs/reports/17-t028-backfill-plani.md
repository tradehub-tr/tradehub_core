# 17 — T-028: `plan_backfill.py` kuru koşumu ve backfill planı

**Tarih:** 2026-08-19 · **Site:** `istoc.localhost` (local dev) · **Branch:** `ahmet`
**Kapsam:** `scripts/plan_backfill.py` ilk kez çalıştırıldı; çıktısı yorumlandı;
Dalga A türev üretim maliyetinin bileşenleri ölçüldü.

> **Bu rapor hiçbir backfill çalıştırmadı.** `Media Engine Settings` bayrakları
> koşum öncesinde de sonrasında da `0/0/0`; `private/image_originals/` arşiv
> dizini oluşmadı; `th_optimized_at` dolu `File` sayısı koşumdan önce de sonra da
> **3**. Doğrulama §6'da.

---

## 0. Özet (tek sayfada)

| Soru | Cevap |
|---|---|
| Script koştu mu? | **Evet** — 1 satırlık `ImportError` düzeltildikten sonra. Çıkış kodu **0**. |
| Gerçekten salt okunur mu? | **Evet**, kod okumasıyla ve koşum sonrası DB/disk karşılaştırmasıyla doğrulandı (§1, §6). |
| Aday küme | **2.833** tekil public adres, **835,4 MB** |
| Backfill'in dokunacağı (A sınıfı) | **49 dosya · 30,4 MB · 1 batch** |
| Satıcı eylemi gereken (B sınıfı) | **2.248 dosya · 539,4 MB · 20 mağaza** |
| Kapsam dışı (C sınıfı) | **512 dosya** (405 slotsuz + 107 çok küçük) |
| Zaten uyumlu | 14 dosya |
| Sınıflandırılamayan | **10 dosya** — 8'i `media/trash.py`'deki hatalı `..` kontrolü yüzünden (§5.1, **yeni bulgu**) |
| Türev üretimi (Dalga A) maliyeti | **ölçüldü**: 10,45 sn/görsel (12 türev) — %52 SSIM, %37 encode, %10 diğer (§4) |
| DALGA-A-DEVIR hipotezi | **DOĞRULANDI ve sayısallaştırıldı**: adaptif kalite döngüsü kaldırılınca 10,45 → 3,50 sn (**2,99×**), çıktı %35 büyüyor (§4.3) |
| Rapor 15'in "60 worker-saat" tahmini | **fazla pesimist**: aynı işin CPU-bağlı tabanı bu veri setinde **~7 saat/tek worker** (§4.4) |

**En önemli tespit — iki ayrı backfill var, script yalnız birini planlıyor:**

`plan_backfill.py` **eski motorun** (`media/engine.py` + `media/runner.py`,
"2000 px tavanına indir, orijinali arşivle") backfill'ini planlar. Sonuç küçük:
**49 dosya, tek batch, 30 MB arşiv**. Rapor 15'teki 60 worker-saatlik yük ise
**Dalga A türev merdiveni** (`media/pipeline/image/render.py`, görsel başına 12
türev) tohumlamasıdır ve **bu scriptin kapsamında değildir**. T-028'i "backfill
planı hazır" diye kapatmak, asıl pahalı işi plansız bırakır. §4.5'te bu iş için
ayrı bir plan taslağı var.

---

## 1. Script ne yapıyor — salt okunurluk doğrulaması

`scripts/plan_backfill.py`, 1010 satır, docstring'i "SALT OKUNUR" diyor. Kendi
okumamla doğruladığım yazma yolları:

| Yol | Durum |
|---|---|
| `frappe.db.sql(...)` | yalnız `select` — 6 çağrı, hepsi okuma |
| `frappe.db.set_value` / `commit` / `doc.save` / `doc.insert` | **yok** |
| `frappe.enqueue` | **yok** — başlatma komutları yalnız METİN olarak basılıyor (`enqueue_commands()`) |
| `engine.optimize` | **çağrılmıyor**; yalnız `engine.probe` (bellekteki baytları okur) |
| `os.remove` / `os.rename` / `shutil.*` | **yok** |
| `open(..., "rb")` | var — disk probe'u |
| `open(..., "w")` | **tek yer**: `BACKFILL_PLAN_OUT` ortam değişkeni verilirse JSON planı yazar. Ortam değişkeni verilmezse hiçbir dosya yazılmaz. |
| `gates.check_before` | saf fonksiyon, `import frappe` içermiyor (gates.py:1-16) |
| `archive.exists` | `os.path.isfile` sarmalayıcısı (archive.py:60-61) — okuma |

**Sonuç:** koşturmadan önce bildirilecek bir yazma yolu yoktu. Koşum sonrası
karşılaştırma da bunu doğruluyor (§6).

Riskli görünen tek şey `_probe_file`'ın dosyanın **tamamını belleğe** okuması
(`fh.read()`); 10 MB'lık tekil dosyalarda sorun değil ama tek tek okunduğu için
paralel değil. Ölçülen etkisi ihmal edilebilir (§2.2).

---

## 2. Koşum

### 2.1 Çalıştırmayı engelleyen hata — düzeltildi

İlk koşum `ImportError` ile düştü:

```
File "plan_backfill.py", line 401, in classify
ImportError: cannot import name 'SUPPORTED_FORMATS' from 'tradehub_core.media.pipeline'
```

`classify()` içinde `from tradehub_core.media.pipeline import SUPPORTED_FORMATS`
yazıyordu. `SUPPORTED_FORMATS` **`media/pipeline` paketinde yok**; tek tanımı
`media/engine.py:21`'de (`frozenset({"JPEG","PNG","WEBP","TIFF"})`) ve
`media/gates.py:16` da oradan alıyor. `media/pipeline` Dalga A ile gelen ayrı bir
paket; ad çakışması yazım sırasında fark edilmemiş — script hiç koşturulmadığı
için de yakalanmamış.

Uygulanan düzeltme (`scripts/plan_backfill.py`, `classify()` içi, tek satır):

```python
-	from tradehub_core.media.pipeline import SUPPORTED_FORMATS
+	# DÜZELTME (T-028 koşumu): SUPPORTED_FORMATS `media/pipeline` paketinde YOK,
+	# `media/engine.py:21`'de tanımlı (gates.py:16 de oradan alıyor). Eski satır
+	# `from tradehub_core.media.pipeline import SUPPORTED_FORMATS` ImportError veriyordu.
+	from tradehub_core.media.engine import SUPPORTED_FORMATS
```

**Davranış değişmedi**: aynı sabit, aynı değer, `gates.check_before`'ın kullandığı
kaynağın ta kendisi. Başka hiçbir satıra dokunulmadı.

### 2.2 Çalıştırılan tam komutlar

Uygulama Docker imajına gömülü (yalnız `sites/` ve `logs/` volume) ve konteynerdeki
`scripts/`, `media/presets.py`, `media/usage.py` dosyalarının md5'i çalışma
ağacıyla **birebir aynı** — yani imaj güncel, koşum çalışma ağacı kodunu ölçtü.

```bash
# düzeltilmiş script konteynere kopyalandı
docker cp scripts/plan_backfill.py \
  istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/scripts/plan_backfill.py

# koşum sarmalayıcısı — /tmp DEĞİL, /home/frappe (sys.path tuzağı)
cat > /home/frappe/run_all.py <<'PY'
import time, frappe
frappe.init(site='istoc.localhost'); frappe.connect()
src = open('/home/frappe/frappe-bench/apps/tradehub_core/scripts/plan_backfill.py').read()
ns = {'__name__': 'plan_backfill'}
exec(compile(src, 'plan_backfill.py', 'exec'), ns)
t0 = time.time()
r = ns['main'](sql=True, probe_disk=True, probe_min_bytes=0, verbose=True)
print("\nTAM KOSUM (probe_min_bytes=0) SURE: %.1f s" % (time.time()-t0))
PY

docker exec -e BACKFILL_PLAN_OUT=/home/frappe/backfill_plan_all.json \
  -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
  ../env/bin/python /home/frappe/run_all.py
```

**Çıkış kodu: `0`.** Üç koşum yapıldı:

| # | Parametre | Süre | Çıkış | Not |
|---|---|---:|---:|---|
| 1 | `probe_disk=False` (yalnız SQL) | 5,0 sn | 0 | 2.428 dosya `BILINMIYOR` kalıyor |
| 2 | varsayılan (`probe_min_bytes=200 KB`) | 6,4 sn | 0 | yalnız 588 dosya probe edildi, 1.967'si `BILINMIYOR` |
| 3 | **`probe_min_bytes=0`** (tam) | 5,9 sn | 0 | 2.833 dosyanın hepsi probe edildi — **bu rapordaki sayılar bu koşumdan** |

Docstring "3k dosyada dakikalar sürer" diyor; **ölçüm 5,9 saniye**. `engine.probe`
PIL'in tembel `Image.open`'ını kullanıyor, piksel decode etmiyor. Disk probe'unu
kademelendirmeye gerek yok — `probe_min_bytes=0` varsayılan olmalı, çünkü
varsayılan 200 KB eşiği dosyaların **%69'unu** sınıflandırılmamış bırakıyor.

> **Kullanım notu (davranış değiştirilmedi, yalnız rapor ediliyor):**
> `main()`'i varsayılanlarla çağırmak yanıltıcı bir tablo üretir — 1.967 dosya
> `BILINMIYOR/probe_yok` görünür, `too_small` sayısı 0 çıkar. Her zaman
> `main(probe_min_bytes=0)` ile çağırın.

---

## 3. Plan çıktısının yorumu

### 3.1 Aday küme

| | Değer |
|---|---:|
| `tabFile` toplam satır | 4.992 |
| public `/files/` satır | 4.377 |
| public `/files/` **tekil URL** | 2.873 |
| script aday kümesi (hassas/dışlanan çıkarılmış) | **2.833** |
| aday bayt | **835,4 MB** |
| bir slota bağlanabilen | 2.428 (587,8 MB) |
| bunlardan **ürün** slotunda (`listing_*`, `variant_*`) | 2.384 (568,0 MB) |

`th_media_width` kapsamı **0/2.873 (%0,0)** — hiçbir dosyanın boyutu DB'de yok,
`metadata.ensure_dimensions()` üretimde hiç tetiklenmemiş. Script'in "DİSK PROBE
ZORUNLU" kararı doğru.

**Rapor 15'in "3.152 ürün görseli" sayısıyla farkı:** burada tekil `file_url`
sayılıyor; 4.377 public satır 2.873 tekil adrese denk geliyor (aynı dosya birden
çok `File` kaydı). Türev üretimi adres başına yapılacağı için **2.428** doğru
ölçek, 3.152 değil. Bu, tohumlama yükünü %23 azaltır.

### 3.2 Sınıf dağılımı

| Sınıf | Dosya | Bayt | Anlamı |
|---|---:|---:|---|
| **A_otomatik** | **49** | 30,4 MB | Mevcut `run_batch` düzeltir — piksel tavanını aşıyor |
| **B_satici_yukler** | 2.248 | 539,4 MB | Piksel üretilemez → satıcı yeniden yüklemeli |
| **C_yok_sayilir** | 512 | 255,3 MB | Kapsam dışı |
| UYUMLU | 14 | 7,7 MB | Kapı 4'e takılıyor (`already_small`) |
| BILINMIYOR | 10 | 2,6 MB | Probe edilemedi → **§5.1 hata** |

**Sebep dağılımı:**

```
resolution_below_target   1878   B — hedefin altında, upscale yasak (engine.py:117)
no_target                  405   C — hiçbir tanınan alanda geçmiyor
aspect_mismatch            348   B — 1:1 hedefinden %5'ten fazla sapma
too_small                  107   C — 200 KB altı (presets.MIN_FILE_SIZE)
over_pixel_ceiling          49   A — 2000 px tavanını aşıyor
unresolvable_aspect         22   B — storefront/company-cover, tek görselle karşılanamaz
already_small               14   UYUMLU
probe_yok                   10   BILINMIYOR
```

**Yorum — B sınıfının %84'ü tek bir karardan geliyor.** 1.878 dosya
`resolution_below_target`; hedef `listing_main`/`listing_gallery` için **2400 px**.
Bu hedef `03-render-envanteri.md §3.8-3.9` + `06-depolama-maliyet.md §1.2`'den
türetilmiş ve her iki kaynak da "öneridir, karar değildir" uyarısı taşıyor.
Script bunu doğru şekilde raporluyor ama **sonucun tamamı bu öneriye asılı**:
hedef 2400 yerine 1920'ye çekilirse B sınıfı ciddi biçimde küçülür. Ölçüm
yapılmadan "2.248 dosyayı satıcılar yeniden yüklesin" denemez.

`aspect_mismatch` 348 dosya: galeri bileşeni `aspect-square` + `object-cover`
kullanıyor, yani kare olmayan görsel **sessizce kırpılıyor**. Bu, backfill'den
bağımsız olarak bugün de yaşanan bir kalite kaybı.

### 3.3 Slot × sınıf

```
(slotsuz)       hedef=None  {C: 401}
listing_main    hedef=2400  {B: 1084, A: 23, C: 6, BILINMIYOR: 1}
listing_gallery hedef=2400  {B:  882, A:  7, C: 2, BILINMIYOR: 5}
variant_main    hedef= 640  {B:  351, A: 15, C: 90, UYUMLU: 12}
variant_gallery hedef= 640  {B:  121, A: 11, C: 6, BILINMIYOR: 2}
storefront      hedef=1920  {B:   25}
seller_logo     hedef= 256  {C: 8, BILINMIYOR: 2, UYUMLU: 2, A: 1, B: 1}
seller_gallery  hedef= 640  {B:    5}
listing_video   hedef=None  {C:    4}
cart_snapshot   hedef=None  {B:    4}
```

- **`storefront` 25/25 dosya B.** Hepsi `unresolvable_aspect` ya da altı. Vitrin
  slaytı 180/220/320/400 px yüksekliklerde değişken oran istiyor; tek görselle
  karşılanamaz (§7-B2). Bu bir yükleme sorunu değil **tasarım sorunu** — satıcıya
  bildirim göndermek yanlış olur, düzeltilecek şey slot politikası.
- **`cart_snapshot` 4 dosya B görünüyor** çünkü aynı dosya ayrıca bir ürün
  slotunda; `_target_for` en sıkı hedefi seçiyor. Doğru davranış, ama sipariş
  kopyası olarak dokunulmaması gerektiği ayrıca not edilmeli.
- **401 dosya "slotsuz" → C.** Script bunu doğru şekilde "kullanılmıyor DEMEK
  DEĞİL" diye işaretliyor: `usage.py` 23 alanın yalnız **16'sını** tanıyor. Bu
  401 dosyanın bilinmeyen bir kısmı aslında kullanımda ve backfill onları
  **sessizce atlar**.

### 3.4 A sınıfı — asıl backfill işi

49 dosya, 30,4 MB, **tek batch** (batch boyutu 200), dosya başına zaman bütçesi
18 sn (timeout 3600 sn). En büyük 5:

```
 2,41 MB  2400x2400  listing_main               /files/1005.png
 2,23 MB  4134x4134  listing_main,variant_main  /files/013.jpg
 2,06 MB  5434x5434  listing_main               /files/1775815659338.jpg
 0,94 MB  4160x4160  variant_main               /files/191-.jpg
 0,92 MB  5347x5347  listing_main               /files/1775815341705.jpg
```

**Risk analizi:**
- 49/2.833 = **%1,7**. `gates.py` docstring'i "4.007 dosyanın ~300'ü kapı 4'ü
  geçer" diyordu; gerçek oran çok daha düşük. Eski motorun backfill'i pratikte
  **önemsiz** bir iş.
- Arşiv şişmesi 30,4 MB / 30 gün. Disk riski yok. (Boş alan bilgisi hâlâ
  tazelenmedi — `backup.py:11`'deki 382 GB 2026-08-13 tarihli.)
- Net kazanç **hesaplanmadı** ve hesaplanamaz: `engine.optimize` çağrılmadan yeni
  bayt bilinmez. Script bunu dürüstçe `HESAPLANMADI` yazıyor.
- **`/files/1005.png` (2400x2400) örneği:** tavan 2000 px olduğu için 2400'e
  inmeyecek, **2000'e** inecek. Ama `listing_main` hedefi 2400. Yani bu dosya
  backfill'den sonra **B sınıfına düşer** — geri dönülemez. Script'in
  `ceiling_loss_2400` kuralı bunu damgalı dosyalar için yakalıyor ama bu dosya
  henüz damgasız olduğu için A'da görünüyor. **Ö4 (türev profil kararı) alınmadan
  A batch'i koşturulmamalı** — script'in kendi ön koşul listesi de bunu söylüyor.

### 3.5 B sınıfı — satıcı bildirimi

2.248 dosya, **20 mağaza**, hiçbiri sahipsiz değil (`magaza_cozulemeyen: 0`).
Yoğunlaşma çok yüksek:

| Mağaza | B dosya | Pay |
|---|---:|---:|
| SEL-00027 | 745 | %33 |
| SEL-00034 | 418 | %19 |
| SEL-00022 | 228 | %10 |
| SEL-00024 | 173 | %8 |
| SEL-00021 | 162 | %7 |
| kalan 15 mağaza | 522 | %23 |

**İlk 5 mağaza toplam B'nin %77'sini taşıyor.** Bu, kitlesel bildirim yerine
5 satıcıyla doğrudan temasın çok daha verimli olduğu anlamına gelir.

Script'in kendi ön koşulu geçerli: `LIVE_SOURCES` 23 alanın 16'sını tanıyor,
tanınmayan alandaki dosya C'ye düşüp satıcıya **hiç** bildirilmiyor. Bildirim
yayına alınmadan bu kapatılmalı.

---

## 4. Türev üretim maliyeti — ÖLÇÜLDÜ

Görev bunu istedi: `DALGA-A-DEVIR.md`'deki hipotez (sürenin encoder'dan değil
adaptif kalite döngüsünden geldiği) ölçülebilir mi? **Ölçüldü.**

### 4.1 Yöntem

`media/pipeline/image/render.py::render_ladder(..., 'product.image',
per_format=True)` gerçek ürün görselleriyle çalıştırıldı; `render.encode`,
`quality.ssim.compute_ssim` ve `render.prepare_source` zaman ölçen sarmalayıcılarla
değiştirildi (üretim koduna dokunulmadı, yalnız koşum içi monkeypatch).

**Doğrulama:** üretilen bayt sayıları `15-dalga-a-dogrulama.md §7.1` tablosuyla
**birebir aynı** çıktı (ör. `BLNT1818xx.jpg` → w384.avif = 28.781 B, w1920.avif =
823.371 B). Yani aynı boru hattı ölçüldü.

**Gürültü uyarısı:** konteynerde paralel ajanlar çalışıyordu (`docker stats`
koşum sırasında backend için %658 CPU gösterdi). Tek atışlık duvar saati
ölçümleri 12–79 sn arasında salındı. Bu yüzden **iç içe geçmiş A/B, 5 tekrar,
her yapılandırma için minimum** alındı — çekişme altında geçerli tek yöntem.
Ham gürültülü koşumlar §7.3'te duruyor, çünkü Rapor 15'in 69 sn/görsel değerini
açıklıyorlar.

### 4.2 Bir görselin 12 türevi nasıl üretiliyor

`product.image` politikası 7 profil (`w96, w192, w384, w640, w768, w1280, w1920`)
× format zinciri → **12 türev**. Her türev için:

- `quality/ssim.py::search_quality`, `(70, 95)` aralığında **ikili arama**
- bütçe `DEFAULT_MAX_ENCODES = 4`
- her denemede **1 encode + 1 SSIM ölçümü**

Ölçülen: **12 türevin 12'si de bütçeyi sonuna kadar harcıyor — görsel başına
48 encode + 48 SSIM.** Arama hiçbir türevde erken bitmiyor.

Daha da çarpıcısı: türevlerin çoğu `quality_floor_reached` notuyla dönüyor, yani
**taban kalite q=70 zaten hedefi tutuyor** ve ulaşılan SSIM 0,96 hedefinin epey
üstünde (0,9612–0,9991). Yani 4 encode'un 3'ü baştan belli olan bir sonucu
doğrulamak için harcanıyor.

### 4.3 Dağılım (min-of-5, iç içe A/B)

| Görsel | Kaynak | Bütçe | Duvar | encode | SSIM | kalan | encode# | çıktı |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BLNT1818xx.jpg | 2,07 MB | **4** | 13,02 s | 5,30 s (%41) | 6,22 s (%48) | 1,50 s (%12) | 48 | 2.780.163 B |
| BLNT1818xx.jpg | 2,07 MB | 1 | 4,69 s | 1,50 s (%32) | 1,65 s (%35) | 1,54 s (%33) | 12 | 3.799.773 B |
| BLNT2184xx.jpg | 1,17 MB | **4** | 11,68 s | 4,74 s (%41) | 5,96 s (%51) | 0,97 s (%8) | 48 | 2.146.050 B |
| BLNT2184xx.jpg | 1,17 MB | 1 | 3,67 s | 1,22 s (%33) | 1,45 s (%39) | 1,00 s (%27) | 12 | 2.835.692 B |
| BLNT2888örn.jpg | 0,19 MB | **4** | 6,66 s | 1,70 s (%25) | 4,17 s (%63) | 0,80 s (%12) | 48 | 136.640 B |
| BLNT2888örn.jpg | 0,19 MB | 1 | 2,15 s | 0,40 s (%18) | 1,00 s (%46) | 0,76 s (%35) | 12 | 186.910 B |

**Toplamlar:**

| Yapılandırma | Toplam | Ort/görsel | encode | SSIM | kalan | Çıktı bayt |
|---|---:|---:|---:|---:|---:|---:|
| **bütçe=4 (üretim varsayılanı)** | 31,35 s | **10,45 s** | 11,73 s (%37) | **16,35 s (%52)** | 3,27 s (%10) | 5.062.853 |
| bütçe=1 (arama yok, tek encode) | 10,51 s | **3,50 s** | 3,11 s (%30) | 4,09 s (%39) | 3,31 s (%31) | 6.822.375 |

**Disk I/O ölçüldü ve ihmal edilebilir:** kaynak dosyayı okumak 1–5 ms
(toplamın <%0,05'i). `prepare_source` (EXIF + mod normalizasyonu) %2–4.

### 4.4 Hipotezin sonucu

> **DALGA-A-DEVIR.md hipotezi: DOĞRULANDI — ama tam olarak iddia ettiği gibi değil.**

- **Doğru olan:** adaptif kalite döngüsü baskın maliyet. Bütçe 4 → 1 yapılınca
  süre **10,45 → 3,50 sn**, yani **2,99×**. Toplam sürenin **~%67'si** yalnızca
  arama fazlalığı.
- **Düzeltilmesi gereken:** hipotez "encoder'dan değil" diyordu; ölçüm bunu tam
  desteklemiyor. Arama içinde bile **encode %37, SSIM %52**. SSIM tek başına en
  büyük kalem — encode'dan daha pahalı. Yani "encoder değil, döngü" değil,
  **"döngü, ve döngünün içinde de asıl SSIM"**.
- SSIM `numpy` yolunu kullanıyor (konteynerde numpy 2.4.6 var) ve varsayılan
  olarak **master çözünürlükte** ölçülüyor (`max_pixels=None`, ssim.py:37).
  w1920 türevi için bu, her denemede 1920×1920'lik iki dizi üzerinde pencere
  hesabı demek.

**Süre projeksiyonu (2.428 slot bağlantılı adres, görsel başına 12 türev):**

| Senaryo | sn/görsel | Toplam (tek worker) |
|---|---:|---:|
| Ölçülen taban (bütçe=4, boş makine) | 10,45 | **~7,1 saat** |
| Ölçülen (bütçe=1) | 3,50 | ~2,4 saat |
| Rapor 15 §7.4 (yüklü makine, duvar saati) | 69 | ~46,5 saat |

Rapor 15'in **60 worker-saat** rakamı iki kez şişmiş: (a) 3.152 yerine gerçek
ölçek 2.428 tekil adres, (b) 69 sn/görsel çekişme altında ölçülmüş bir duvar
saati değeri; CPU-bağlı taban 10,45 sn. **Gerçekçi bant: 7–47 worker-saat**,
makinenin ne kadar boş olduğuna göre. Tek worker ile gece koşumunda biter;
"60 saat, ayrı bir proje" değil.

> Bu ölçüm **local dev Docker** üzerinde, çekişme altında yapıldı. Prod donanımı
> farklıdır; rakam prod'da yeniden ölçülmeden SLA'ya yazılmamalı.

**Depolama:** görsel başına 12 türev × 2.428 adres = **29.136 türev nesnesi**.
Ölçülen çıktı/kaynak oranı görsele göre 0,69× ile 4,4× arasında değişti
(küçük kaynaklarda merdiven kaynaktan büyük); Rapor 15'in referans ilanında
oran 1,03×. 587,8 MB kaynak için kaba tahmin **0,6–0,9 GB** türev diski.
`max_renditions_per_asset = 40` freni 12 türevle rahat.

### 4.5 Türev tohumlama için plan taslağı (script'in kapsamadığı iş)

`plan_backfill.py` bu işi planlamıyor. Ölçümlere dayanan asgari plan:

1. **Ölçek:** 2.428 adres (2.384'ü ürün slotunda). 405 slotsuz dosya `usage.py`
   16→23 alan genişletilmeden **atlanır**; önce o kapatılmalı.
2. **Kuyruk:** `long` kuyruğu canlı video transcode ile paylaşılıyor ve tek
   worker dinliyor. Koşum anında `long` derinliği **0** ölçüldü. Tohumlama
   batch'leri arası kuyruk boş kontrolü şart.
3. **Batch:** timeout 3600 sn / 10,45 sn ≈ 340 görsel teorik üst sınır. Güvenlik
   payıyla **100 görsel/batch** (≈17 dk) → ~25 batch. Çekişme altında 69 sn'ye
   çıkarsa 100 görsel 115 dk sürer ve timeout'u aşar → batch **50** daha güvenli.
4. **Bütçe kararı (asıl kaldıraç):** `search_quality` taban kaliteyi önce
   deneyip geçtiğinde durabilseydi bütçe 4'ten ~2'ye inerdi (§4.2: türevlerin
   çoğu `quality_floor_reached`). Bu **kod değişikliği**dir, bu raporun kapsamı
   dışındadır, ama tohumlamadan önce yapılırsa süre yarıya iner.
5. **Bayraklar:** tohumlama `rendition_on_upload` açılmadan, doğrudan
   `render_ladder` çağıran bir toplu iş olarak koşturulmalı; bayrak açmak
   canlı yükleme yolunu da değiştirir.

---

## 5. Yeni bulgular (script koşturulunca ortaya çıkanlar)

### 5.1 `media/trash.py::_relative` — `..` kontrolü meşru dosya adlarını reddediyor

**8 dosya** probe edilemedi, sebep `bad_path`:

```
ValidationError: Geçersiz dosya yolu: /files/MOİ ile derin düzen..jpg
ValidationError: Geçersiz dosya yolu: /files/Yiyeceklerinizi güvenle saklayın ve kolayca ısıtın..jpg
ValidationError: Geçersiz dosya yolu: /files/𝖠𝖰𝖴𝖠 - Su Kovası… uyum sağlar..jpg
… (8 dosyanın tamamı `..jpg` ile bitiyor)
```

Kök neden — `tradehub_core/media/trash.py:40-44`:

```python
def _relative(file_url: str) -> str:
	url = (file_url or "").split("?")[0]
	if not url.startswith("/files/") or ".." in url:
		frappe.throw(...)
```

`".." in url` **saf altdizgi kontrolü**. Satıcılar dosya adı olarak cümle
kullanmış; cümle noktayla bitiyor ve uzantının noktasıyla birleşince `..jpg`
oluyor. Path traversal değil, tamamen meşru bir ad.

**Etkisi backfill'in ötesinde:** `_live_path` ve `_trash_path` aynı fonksiyonu
kullanıyor → bu 8 dosya **çöpe atılamaz, geri alınamaz, arşivlenemez,
optimize edilemez**. Sessizce dışarıda kalıyorlar.

**Doğru kontrol** `..` altdizgisi değil, yol bileşeni bazında olmalı (`".." in
url.split("/")`) — zaten `realpath` + `startswith(root)` kontrolü ikinci savunma
hattı olarak duruyor.

> `media/trash.py` bu görevin dokunma yasağı listesinde (`media/` altındaki
> `.py`), bu yüzden **düzeltilmedi, yalnız raporlandı**.

### 5.2 3 dosya diskte yok

`file_missing` = 3 (2'si `seller_logo` slotunda, "ChatGPT Image … .png" adlı).
`File` kaydı var, dosya yok. DB yedeği ile dosya yedeğinin farklı anlara ait
olmasının doğal sonucu; `media_stats.py` Sorgu 7 ile çapraz kontrol edilmeli.

### 5.3 Hassas ters referans taraması 0 döndü

`sensitive_reverse_refs()` **0** hit. Ama script'in kendi uyarısı geçerli:
`EXCLUDED_MEDIA_FIELDS` KYB'nin yalnız 2 alanını sayıyor; `imza_sirkuleri`,
`ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` haritada **yok**.
0 sonucu "PII yok" demek değil, "**haritanın gördüğü yerde** PII yok" demek.
Ö1 (`media_stats.pii_exposure()`) hâlâ ön koşul.

### 5.4 `probe_min_bytes` varsayılanı yanıltıcı

§2.2'de anlatıldı: varsayılan 200 KB eşiği dosyaların %69'unu
`BILINMIYOR` bırakıyor ve `too_small` sayısını 107 yerine 0 gösteriyor. Disk
probe'u ölçüldüğü kadar ucuz olduğu için (2.833 dosya / 5,9 sn) eşiğin varsayılan
değeri 0 olmalı. **Davranış değiştirilmedi** — yalnız kullanım notu.

---

## 6. Salt okunurluk — koşum sonrası doğrulama

| Kontrol | Koşum öncesi | Koşum sonrası |
|---|---|---|
| `Media Engine Settings.media_pipeline_enabled` | 0 | **0** |
| `.rendition_on_upload` | 0 | **0** |
| `.manifest_api_enabled` | 0 | **0** |
| `.active_slots` | `""` | **`""`** |
| `.modified` | `2026-08-19 14:09:19` | **`2026-08-19 14:09:19`** (değişmedi) |
| `th_optimized_at` dolu `File` | 3 | **3** |
| `private/image_originals/` arşiv dizini | yok | **yok** |
| `rq:queue:long` derinliği | 0 | **0** |

Script'in yazdığı tek dosya `BACKFILL_PLAN_OUT` JSON'u:
`/home/frappe/backfill_plan_all.json` (967 KB, konteyner içinde, site verisinin
dışında). Ölçüm sarmalayıcıları koşum sonrası silindi.

---

## 7. Ham çıktı

### 7.1 Tam koşum — `main(sql=True, probe_disk=True, probe_min_bytes=0)`

```
[1/5] Aday küme (tekilleştirilmiş public)…
[2/5] Çözünürlük kapsamı (SQL yeter mi)…
[3/5] Slot ataması (ters referans, deep=False)…
[4/5] Hassas belge ters referansı (EXCLUDED_MEDIA_FIELDS)…
[5/5] Disk probe (piksel / format / renk uzayı / uzantı-içerik)…
      … 250/2833
      … 500/2833
      … 750/2833
      … 1000/2833
      … 1250/2833
      … 1500/2833
      … 1750/2833
      … 2000/2833
      … 2250/2833
      … 2500/2833
      … 2750/2833

══════════════════════════════════════════════════════════════════════════
BACKFILL PLANI — istoc.localhost — 2026-08-19 14:40:23.040947
══════════════════════════════════════════════════════════════════════════

Aday adres            : 2833
Aday bayt             : 835.38 MB
Piksel tavanı (kod)   : 2000 px  ← media/presets.py:15 (balanced.max_dim)

Çözünürlük kapsamı    : 0/2873 (%0.0) → DISK PROBE ZORUNLU
Probe edilen          : 2833  (min bayt altı atlanan: 0)
    ok                     2822
    file_missing           3
    bad_path               8

── SINIF TOPLAMLARI ─────────────────────────────────────────────
    B_satici_yukler  2248
    C_yok_sayilir    512
    A_otomatik       49
    UYUMLU           14
    BILINMIYOR       10

── SEBEP DAĞILIMI ───────────────────────────────────────────────
    resolution_below_target    1878
    no_target                  405
    aspect_mismatch            348
    too_small                  107
    over_pixel_ceiling         49
    unresolvable_aspect        22
    already_small              14
    probe_yok                  10

── SLOT × SINIF ─────────────────────────────────────────────────
    (slotsuz)            hedef=  None  {'C_yok_sayilir': 401}
    listing_main         hedef=  2400  {'B_satici_yukler': 1084, 'A_otomatik': 23, 'C_yok_sayilir': 6, 'BILINMIYOR': 1}
    listing_gallery      hedef=  2400  {'B_satici_yukler': 882, 'A_otomatik': 7, 'C_yok_sayilir': 2, 'BILINMIYOR': 5}
    listing_video        hedef=  None  {'C_yok_sayilir': 4}
    seller_gallery       hedef=   640  {'B_satici_yukler': 5}
    variant_gallery      hedef=   640  {'B_satici_yukler': 121, 'A_otomatik': 11, 'C_yok_sayilir': 6, 'BILINMIYOR': 2}
    variant_main         hedef=   640  {'A_otomatik': 15, 'B_satici_yukler': 351, 'UYUMLU': 12, 'C_yok_sayilir': 90}
    storefront           hedef=  1920  {'B_satici_yukler': 25}
    seller_logo          hedef=   256  {'BILINMIYOR': 2, 'UYUMLU': 2, 'A_otomatik': 1, 'C_yok_sayilir': 8, 'B_satici_yukler': 1}
    cart_snapshot        hedef=  None  {'B_satici_yukler': 4}

── ARŞİV ŞİŞMESİ (geçici) ───────────────────────────────────────
    A sınıfı dosya      : 49
    arşiv               : 30.35 MB  (30 gün)
    net kazanç          : HESAPLANMADI — dry-run gerekir (migration.md §10-D1)
    Diskte yer var mı BİLİNMİYOR: backup.py:11'deki 382 GB 2026-08-13 tarihli. §10-D4

── BATCH PLANI ──────────────────────────────────────────────────
    batch boyutu        : 200
    batch sayısı        : 1
    toplam dosya        : 49
    dosya/zaman bütçesi : 18.0 s (timeout 3600 s)

── SATICI BİLDİRİMİ (B sınıfı) ──────────────────────────────────
    B sınıfı dosya      : 2248
    etkilenen mağaza    : 20
    mağazası çözülemeyen: 0
    ÖN KOŞUL: LIVE_SOURCES 23 alanı kapsamadan yayına alınmaz (migration.md §9.1 Ö5)

── KAPSAM UYARILARI ─────────────────────────────────────────────
    usage.py 16 (tablo,kolon) çifti tanıyor; information_schema taraması 23 alan buldu (usage.py:8) → 7 alan KAPSAM DIŞI, eksik olanlar 00-upload-slot-envanteri.md §7-B6'da listeli
    presets.py:70-76 KYB'nin yalnız 2 alanını sayıyor; imza_sirkuleri, ticaret_sicil_gazetesi, faaliyet_belgesi, vergi_levhasi YOK (§7-B5) → R5
    Hedefler ÖNERİDİR, karar değil: 03-render-envanteri.md §3.8-3.9 + 06-depolama-maliyet.md §1.2 — ÖNERİ

╔══════════════════════════════════════════════════════════════════════════╗
║  DURDURMA KRİTERİ — HER BATCH'TEN SONRA, SONRAKİ ENQUEUE'DAN ÖNCE        ║
╚══════════════════════════════════════════════════════════════════════════╝

  hata_oranı = state["errors"] / state["processed"]        > %2  →  DUR

  `skipped` HATA DEĞİLDİR (runner.py:76-79). Kapı 4'e takılmak normal
  davranıştır ve backfill'in beklenen çoğunluğudur.

  ── batch arası kontrol ────────────────────────────────────────────────
  from tradehub_core.media import runner
  st = runner.read_progress(job_key)

  assert st["state"] in ("completed", "partial"), st["state"]

  oran = st["errors"] / max(st["processed"], 1)
  if oran > 0.02:
      raise SystemExit(f"DUR: hata %{oran*100:.1f} > %2 — kalan batch ENQUEUE EDİLMEZ")

  sr = st["skip_reasons"]
  if sr.get("file_missing", 0)  > st["processed"] * 0.01:
      raise SystemExit("DUR: file_missing > %1 → disk/DB ayrışması, media_stats Sorgu 7")
  if sr.get("decode_failed", 0) > st["processed"] * 0.01:
      raise SystemExit("DUR: decode_failed > %1 → Pillow / dosya bozulması")

  ── TTL TUZAĞI ────────────────────────────────────────────────────────
  İlerleme kaydı Redis'te ve TTL 3600 s (presets.py:28 PROGRESS_TTL).
  Okuma iş bitiminden 1 saat içinde yapılmalı. `state == "not_found"`
  (runner.py:29) bir "GEÇTİ" sonucu DEĞİLDİR — hata oranı BİLİNMİYOR
  demektir ve o durumda da DURULUR.

  ── KUYRUK ÖN KONTROLÜ (migration.md §5.3) ────────────────────────────
  Backfill ve CANLI video transcode AYNI kuyrukta: ikisi de queue="long"
  (api/media_admin.py:210 ve media/transcode.py:157). `long` kuyruğunu
  dinleyen TEK worker var (docker-compose.yml:170-175).
  → Enqueue öncesi `long` kuyruğunda bekleyen iş 0 olmalı (§10-D7).

  ── BATCH BOYUTU = DURDURMA ÇÖZÜNÜRLÜĞÜ ───────────────────────────────
  batch_size = 200  →  eşik aşılsa bile en kötü durumda 200 dosya işlenmiş olur.
  dosya başına zaman bütçesi = 3600 / 200 = 18.0 s


╔══════════════════════════════════════════════════════════════════════════╗
║  BACKFILL BAŞLATMA — BU SCRIPT ÇALIŞTIRMAZ, OPERATÖR ELLE ÇALIŞTIRIR    ║
╚══════════════════════════════════════════════════════════════════════════╝

  ÖN KOŞULLAR (migration.md §9.1) — hepsi tamamlanmadan BAŞLAMAZ:
    Ö1  media_stats.py pii_exposure()      → 144+2 PII belgesi public'te mi
    Ö2  EXCLUDED_MEDIA_FIELDS 4 eksik KYB alanı tamamlandı mı (§7-B5)
    Ö3  media_stats.py reconcile()         → küme büyüklüğü
    Ö4  TÜREV PROFİL KARARI + gerekirse presets.py tavanı  ← R1, GERİ DÖNÜLEMEZ
    Ö6  disk boş alan tazelendi mi (§10-D4)

  1) KURU KOŞU — diske hiçbir şey yazılmaz (runner.py:61-63, :243-245)
     from tradehub_core.api import media_admin
     r = media_admin.start_image_optimization(
             file_names=BATCH["file_names"], scope="selected",
             preset="balanced", dry_run=1)

  2) İLERLEME
     from tradehub_core.media import runner
     runner.read_progress(r["job_key"])

  3) GERÇEK KOŞU — dry_run=0
     media_admin.start_image_optimization(
             file_names=BATCH["file_names"], scope="selected",
             preset="balanced", dry_run=0)

     ⚠️ scope="pending" KULLANMAYIN: api/media_admin.py:197-202 o yolda
        MAX_BATCH'i BİLEREK uygulamıyor → tüm küme TEK 3600 s'lik işe girer.

  4) GERİ ALMA (30 gün içinde — presets.py:38)
     media_admin.start_restore(scope="selected", file_names=[...])
     media_admin.start_restore(scope="optimized")     # filtreye uyan hepsi
     media_admin.restore_image(file_name)             # tek dosya, senkron

     ⚠️ th_optimized_at BOŞ olan dosya GERİ ALINAMAZ (runner.py:336-337) —
        timeout kesilmesinde oluşur (migration.md §4.2). Kontrol: §10-D2.

  5) ARŞİV PURGE'U DURDUR — backfill + 30 günlük doğrulama penceresi boyunca
     archive.purge_expired() çalışmamalı (archive.py:113-153). Hangi hook
     çağırıyor: §10-D6.


JSON yazıldı: /home/frappe/backfill_plan_all.json

TAM KOSUM (probe_min_bytes=0) SURE: 5.9 s
```

### 7.2 Varsayılan parametrelerle koşum — `main()` (özet kısmı)

```
[1/5] Aday küme (tekilleştirilmiş public)…
[2/5] Çözünürlük kapsamı (SQL yeter mi)…
[3/5] Slot ataması (ters referans, deep=False)…
[4/5] Hassas belge ters referansı (EXCLUDED_MEDIA_FIELDS)…
[5/5] Disk probe (piksel / format / renk uzayı / uzantı-içerik)…
      … 250/588
      … 500/588

══════════════════════════════════════════════════════════════════════════
BACKFILL PLANI — istoc.localhost — 2026-08-19 14:40:02.971694
══════════════════════════════════════════════════════════════════════════

Aday adres            : 2833
Aday bayt             : 835.38 MB
Piksel tavanı (kod)   : 2000 px  ← media/presets.py:15 (balanced.max_dim)

Çözünürlük kapsamı    : 0/2873 (%0.0) → DISK PROBE ZORUNLU
Probe edilen          : 588  (min bayt altı atlanan: 2245)
    ok                     586
    file_missing           2

── SINIF TOPLAMLARI ─────────────────────────────────────────────
    BILINMIYOR       1967
    C_yok_sayilir    405
    B_satici_yukler  398
    A_otomatik       49
    UYUMLU           14

── SEBEP DAĞILIMI ───────────────────────────────────────────────
    probe_yok                  1967
    no_target                  405
    resolution_below_target    201
    aspect_mismatch            190
    over_pixel_ceiling         49
    already_small              14
    unresolvable_aspect        7

── SLOT × SINIF ─────────────────────────────────────────────────
    (slotsuz)            hedef=  None  {'C_yok_sayilir': 401}
    listing_main         hedef=  2400  {'B_satici_yukler': 148, 'A_otomatik': 23, 'BILINMIYOR': 943}
```

(Kalan bölümler §7.1 ile aynı metin.)

### 7.3 Türev üretim ölçümü — iç içe A/B, 5 tekrar, minimum

```
EN IYI (min) 5 tekrar -- konteyner yuklu, min = en az girisim degeri

gorsel                      butce    duvar   encode     ssim    kalan   enc#    cikti B
/files/BLNT1818xx.jpg           4   13.02s    5.30s(41%)   6.22s(48%)   1.50s(12%)    48    2780163
/files/BLNT1818xx.jpg           1    4.69s    1.50s(32%)   1.65s(35%)   1.54s(33%)    12    3799773
/files/BLNT2184xx.jpg           4   11.68s    4.74s(41%)   5.96s(51%)   0.97s( 8%)    48    2146050
/files/BLNT2184xx.jpg           1    3.67s    1.22s(33%)   1.45s(39%)   1.00s(27%)    12    2835692
/files/BLNT2888örn.jpg          4    6.66s    1.70s(25%)   4.17s(63%)   0.80s(12%)    48     136640
/files/BLNT2888örn.jpg          1    2.15s    0.40s(18%)   1.00s(46%)   0.76s(35%)    12     186910

>> BUTCE=4  toplam 31.35 s (ort 10.45 s/gorsel) encode 11.73 (37%) ssim 16.35 (52%) kalan 3.27 (10%) cikti 5062853 B

>> BUTCE=1  toplam 10.51 s (ort 3.50 s/gorsel) encode 3.11 (30%) ssim 4.09 (39%) kalan 3.31 (31%) cikti 6822375 B
```

### 7.4 Tek atışlık ayrıntılı ölçüm (türev bazında, çekişmeli makine)

Bu koşum gürültülüdür (paralel ajanlar); türev bazında `quality`, `ssim`,
`encodes` ve `notes` alanlarını göstermek için duruyor. Bayt değerleri
`15-dalga-a-dogrulama.md §7.1` ile birebir eşleşiyor.

```

=== /files/BLNT1818xx.jpg  kaynak=2066448 B  ===
 turev=12  encode=48  cikti=2780163 B
 TOPLAM 12.80 s | disk-oku 0.001 s | prepare_source 0.48 s (4%, n=13) | encode 5.16 s (40%) | SSIM 6.05 s (47%) | kalan 1.11 s (9%)
   - w96.webp q=70    ssim=0.9625 encodes=4     1618 B     165 ms  notes=padded,quality_floor_reached
   - w192.webp q=73    ssim=0.9612 encodes=4     6182 B     136 ms  notes=padded
   - w384.avif q=70    ssim=0.9810 encodes=4    28781 B     287 ms  notes=padded,quality_floor_reached
   - w384.webp q=70    ssim=0.9622 encodes=4    23132 B     182 ms  notes=padded,quality_floor_reached
   - w640.avif q=70    ssim=0.9852 encodes=4    78205 B     447 ms  notes=padded,quality_floor_reached
   - w640.webp q=70    ssim=0.9669 encodes=4    63002 B     317 ms  notes=padded,quality_floor_reached
   - w768.avif q=70    ssim=0.9860 encodes=4   104065 B     590 ms  notes=padded,quality_floor_reached
   - w768.webp q=70    ssim=0.9693 encodes=4    86856 B     453 ms  notes=padded,quality_floor_reached
   - w1280.avif q=70    ssim=0.9834 encodes=4   453097 B    1447 ms  notes=quality_floor_reached
   - w1280.webp q=70    ssim=0.9667 encodes=4   403260 B    1393 ms  notes=quality_floor_reached
   - w1920.avif q=70    ssim=0.9846 encodes=4   823371 B    3753 ms  notes=quality_floor_reached
   - w1920.webp q=70    ssim=0.9675 encodes=4   708594 B    3535 ms  notes=quality_floor_reached

=== /files/BLNT2184xx.jpg  kaynak=1172797 B  ===
 turev=12  encode=48  cikti=2146050 B
 TOPLAM 12.00 s | disk-oku 0.001 s | prepare_source 0.26 s (2%, n=13) | encode 4.71 s (39%) | SSIM 6.28 s (52%) | kalan 0.74 s (6%)
   - w96.webp q=70    ssim=0.9651 encodes=4     1302 B      68 ms  notes=padded,quality_floor_reached
   - w192.webp q=75    ssim=0.9610 encodes=4     4408 B      81 ms  notes=padded
   - w384.avif q=70    ssim=0.9734 encodes=4    20029 B     269 ms  notes=padded,quality_floor_reached
   - w384.webp q=78    ssim=0.9605 encodes=4    17768 B     143 ms  notes=padded
   - w640.avif q=70    ssim=0.9786 encodes=4    50588 B     377 ms  notes=padded,quality_floor_reached
   - w640.webp q=78    ssim=0.9632 encodes=4    44844 B     277 ms  notes=padded
   - w768.avif q=70    ssim=0.9799 encodes=4    67600 B     510 ms  notes=padded,quality_floor_reached
   - w768.webp q=78    ssim=0.9629 encodes=4    60234 B     383 ms  notes=padded
   - w1280.avif q=70    ssim=0.9782 encodes=4   335260 B    1298 ms  notes=quality_floor_reached
   - w1280.webp q=78    ssim=0.9616 encodes=4   319756 B    1452 ms  notes=
   - w1920.avif q=70    ssim=0.9829 encodes=4   664911 B    3397 ms  notes=quality_floor_reached
   - w1920.webp q=72    ssim=0.9608 encodes=4   559350 B    3713 ms  notes=
YOK: /files/020 kirmizi orta 12'li.jpg

=== /files/kare-823378a8.webp  kaynak=9776 B  ===
 turev=12  encode=48  cikti=42709 B
 TOPLAM 2.77 s | disk-oku 0.001 s | prepare_source 0.05 s (2%, n=13) | encode 0.85 s (31%) | SSIM 1.79 s (65%) | kalan 0.08 s (3%)
   - w96.webp q=70    ssim=0.9941 encodes=4      292 B      18 ms  notes=quality_floor_reached
   - w192.webp q=70    ssim=0.9961 encodes=4      640 B      24 ms  notes=quality_floor_reached
   - w384.avif q=70    ssim=0.9989 encodes=4     1896 B      97 ms  notes=quality_floor_reached
   - w384.webp q=70    ssim=0.9970 encodes=4     1540 B      63 ms  notes=quality_floor_reached
   - w640.avif q=70    ssim=0.9990 encodes=4     3336 B     168 ms  notes=quality_floor_reached
   - w640.webp q=70    ssim=0.9973 encodes=4     2942 B     150 ms  notes=quality_floor_reached
   - w768.avif q=70    ssim=0.9990 encodes=4     4063 B     301 ms  notes=quality_floor_reached
   - w768.webp q=70    ssim=0.9975 encodes=4     3706 B     274 ms  notes=quality_floor_reached
   - w1280.avif q=70    ssim=0.9991 encodes=4     6335 B     463 ms  notes=under_spec,no_downscale,quality_floor_reached
   - w1280.webp q=70    ssim=0.9979 encodes=4     5812 B     420 ms  notes=under_spec,no_downscale,quality_floor_reached
   - w1920.avif q=70    ssim=0.9991 encodes=4     6335 B     373 ms  notes=under_spec,no_downscale,quality_floor_reached
   - w1920.webp q=70    ssim=0.9979 encodes=4     5812 B     413 ms  notes=under_spec,no_downscale,quality_floor_reached

=== /files/BLNT2888örn.jpg  kaynak=199092 B  ===
 turev=12  encode=48  cikti=136640 B
 TOPLAM 7.03 s | disk-oku 0.001 s | prepare_source 0.13 s (2%, n=13) | encode 1.77 s (25%) | SSIM 4.43 s (63%) | kalan 0.69 s (10%)
   - w96.webp q=70    ssim=0.9919 encodes=4      522 B      62 ms  notes=padded,quality_floor_reached
   - w192.webp q=70    ssim=0.9926 encodes=4     1222 B      69 ms  notes=padded,quality_floor_reached
   - w384.avif q=70    ssim=0.9978 encodes=4     3397 B     170 ms  notes=padded,quality_floor_reached
   - w384.webp q=70    ssim=0.9940 encodes=4     3150 B     112 ms  notes=padded,quality_floor_reached
   - w640.avif q=70    ssim=0.9978 encodes=4     6619 B     249 ms  notes=padded,quality_floor_reached
   - w640.webp q=70    ssim=0.9946 encodes=4     6526 B     204 ms  notes=padded,quality_floor_reached
   - w768.avif q=70    ssim=0.9979 encodes=4     8850 B     333 ms  notes=padded,quality_floor_reached
   - w768.webp q=70    ssim=0.9949 encodes=4     8460 B     303 ms  notes=padded,quality_floor_reached
   - w1280.avif q=70    ssim=0.9979 encodes=4    17775 B     722 ms  notes=quality_floor_reached
   - w1280.webp q=70    ssim=0.9953 encodes=4    19086 B     719 ms  notes=quality_floor_reached
   - w1920.avif q=70    ssim=0.9981 encodes=4    29539 B    1956 ms  notes=quality_floor_reached
   - w1920.webp q=70    ssim=0.9961 encodes=4    31494 B    2111 ms  notes=quality_floor_reached

--- TOPLU ---
gorsel=4 toplam=34.6 s ort=8.6 s/gorsel
prepare=0.9 encode=12.5 ssim=18.5 kalan=2.6
```

---

## 8. Sonuç ve öneriler

1. **T-028'in script'i artık koşturulmuş ve doğrulanmış durumda.** Tek satırlık
   `ImportError` düzeltildi (§2.1); davranış değişmedi. Çıkış kodu 0.
2. **Eski motor backfill'i önemsiz:** 49 dosya, 1 batch, 30 MB arşiv. Ama
   **Ö4 (türev profil / piksel tavanı kararı) alınmadan koşturulmamalı** —
   2000 px tavanı bugünkü 2400 px hedefiyle çelişiyor ve işlem geri dönülemez
   (§3.4).
3. **Asıl maliyet türev tohumlamasında ve script onu planlamıyor.** §4.5'teki
   taslak ayrı bir görev olarak açılmalı.
4. **Rapor 15'in 60 worker-saat tahmini revize edilmeli:** ölçülen taban
   **~7 saat**, gerçekçi bant 7–47 saat (§4.4).
5. **Süreyi yarıya indirecek tek kaldıraç** `search_quality`'nin taban kaliteyi
   önce denemesi: türevlerin çoğu zaten `quality_floor_reached` (§4.2).
6. **Bloke edici hata:** `media/trash.py`'nin `..` kontrolü 8 meşru dosyayı
   tüm medya işlemlerinden dışlıyor (§5.1). Ayrı bir düzeltme görevi gerekir.
7. **B sınıfı bildirimi henüz yayına alınamaz:** `usage.py` 16/23 alan tanıyor;
   401 "slotsuz" dosyanın bir kısmı aslında kullanımda (§3.3).
8. **Bayraklar kapalı kaldı** — koşum öncesi ve sonrası `0/0/0` (§6).
