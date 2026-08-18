# T-009 — Faz 0 Kapanış Raporu

**Medya motoru çalışması · Faz 0 · Rev. 2 — 2026-08-18**
**Rev. 1:** 2026-08-17 (Dalga 2, Docker kapalı varsayımıyla yazılmış raporların denetimi)
Branch: `medya-motoru-faz0-faz2` · Worktree: `/Users/ahmet/Desktop/istoc-medya-wt`
Kaynak tasarım dokümanı: https://karacaismail.github.io/imageoptimization/docs/ (15 faz, 102 görev)

Bu belge Faz 0'ın **kapanış denetimidir**. Rev. 1'in tespitleri korunmuştur; her
kalemin yanına **Dalga 3'te ne olduğu** eklenmiştir.

> **Dürüstlük notu (Rev. 2).** Rev. 1 "Faz 0 tamamlanmadı" diyordu; gerekçesi
> T-006 ve T-007'nin yapılmamış olması ve ölçümlerin yokluğuydu. **İkisi de
> değişti:** T-006 ve T-007 bu dalgada üretildi (§1.2) ve 39 kalemlik ölçüm
> listesinin 10'u tam, 8'i kısmen kapandı (§7.2).
>
> **Ama Faz 0 hâlâ kapanamıyor.** Gerekçe artık farklı ve daha dar: K-1'in
> ikinci yarısı **bulgu döndürdü** (44 dosya, §7.1 D-2 [Ö3]), K-2 **fiilen
> yapılmadı** (bozuk komutlar dosyalarda duruyor [Ö3]), K-3 üretim erişimi
> istiyor ve G-2 **hiç değişmedi** — 12 raporun tamamı hâlâ `untracked`.
> Ayrıntı §9.
>
> **Rev. 1'in bir tespiti bu dalgada ÇÜRÜTÜLDÜ.** Ç-2'nin "06-depolama'nın tüm
> mutlak sayıları %40 düzeltilmeli" sonucu **yanlıştı**; ölçüm tersini söylüyor
> (§2 Ç-2 revizyonu, §8). Bu raporun kendi hatasını düzeltmesi, kapanış
> denetiminin işlevidir.

---

## 0. Yöntem ve güven işaretleri

| İşaret | Anlamı |
|---|---|
| **[Ö]** | Rev. 1 oturumunda ölçüldü (2026-08-17). |
| **[Ö3]** | **Bu oturumda (Dalga 3, 2026-08-18) ölçüldü** — komut çalıştırıldı, çıktısı aşağıda. |
| **[R]** | Raporda yazılı — 12 rapordan biri söylüyor; kaynağı o rapor. |
| **[K]** | Kaynakta doğrulandı — `dosya:satır` olarak okundu. |
| **[?]** | Bilinemedi; nedeni ve komutu §7'de. |

### 0.1 Bu oturumda (Rev. 2) çalıştırılan komutlar

Tamamı **salt okuma**. `tradehub_core/` altında hiçbir dosya değiştirilmedi (kural 1).

```bash
# Ortam
docker ps --format '{{.Names}}\t{{.Status}}'                      # 12 servis Up [Ö3]
docker exec istoc-dev-backend-1 env/bin/python -c "import pyvips" # 3.1.1 [Ö3]

# Faz 0 çıktı envanteri
ls tests/fixtures/media/images | wc -l      # 34 [Ö3]
ls tests/fixtures/media/video  | wc -l      #  7 [Ö3]
ls tests/fixtures/malicious    | wc -l      # 10 [Ö3]
git status --short                          # 14 girdi, hepsi ?? [Ö3]
grep -c "istocc" scripts/media_stats.py docs/reports/02-medya-istatistigi.md
grep -c "tradehub.localhost" scripts/media_stats.py docs/reports/02-medya-istatistigi.md

# §7.1 D-1 / D-2 / D-23 — KVKK bloklayıcısı (konteynerde, salt SELECT)
docker cp /tmp/d1.py istoc-dev-backend-1:/home/frappe/d1.py
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
        ../env/bin/python /home/frappe/d1.py

# §7.1 D-3/D-4/D-5 — taban mutabakatı (dört küme + yetim tarama)
#   tabFile satır / eşsiz file_url / diskteki dosya / bayt toplamları
```

**Bu oturumda ölçülemeyenler:** üretim veritabanı ve canlı site
(`istoc.cronbi.com`, `alpha/beta/rcistoc.cronbi.com`), Press API'si, prod nginx
yapılandırması, prod imaj içeriği, RUM/analytics. Tamamı §7.3'te — **bu liste
Rev. 1'den beri değişmedi.**

---

## 1. Faz 0 çıktı karnesi

### 1.1 Üretilen raporlar

| Görev | Dosya | Satır | Konu | Durum |
|---|---|---:|---|---|
| T-000 | `docs/reports/00-ortam-envanteri.md` | 774 | Depo ve ortam envanteri; runtime, kütüphaneler, limit zinciri, worker | ✅ Dalga 1 |
| T-001 | `docs/reports/00-upload-slot-envanteri.md` | 551 | 41 DocType alanı + 16 storefront + 26 panel yükleme noktası | ✅ Dalga 1 |
| T-002 | `docs/reports/01-dosya-akisi.md` | 554 | Frappe `File` akışı: yükleme → disk → URL | ✅ Dalga 1 |
| T-003 | `docs/reports/02-medya-istatistigi.md` | 939 | Mevcut medya sayıları + 9 tutarsızlık + 10 sorgu | ✅ Dalga 1 |
| T-004 | `docs/reports/03-render-envanteri.md` | 567 | Storefront render envanteri, 20 render noktası | ✅ Dalga 1 |
| T-005 | `docs/reports/04-yetki-modeli.md` | 817 | 4 katmanlı yetki modeli, satıcı izolasyonu, PII | ✅ Dalga 1 |
| T-008 | `docs/reports/06-depolama-maliyet.md` | 782 | Türev patlaması projeksiyonu, 12 ay büyüme | ✅ Dalga 1 |
| T-009 | `docs/reports/07-faz0-kapanis.md` | — | **bu belge** | ✅ Rev. 2 |
| **T-003/T-004 (boşluk)** | `docs/reports/08-canli-olcum.md` | 215 | **Canlı `tabFile` ölçümü**, logo, video, PII maruziyeti | ✅ **Dalga 3** |
| **T-004** | `docs/reports/03-performans-taban-cizgisi.md` | 413 | **LCP/CLS taban çizgisi**, 4 sayfa × 2 profil, nginx başlıkları | ✅ **Dalga 3** |
| **T-006** | `docs/reports/05-fixture-korpusu.md` | 450 | **Golden fixture korpusu** — 51 fixture, motor davranışı ölçümü | ✅ **Dalga 3** |
| **T-007** | `docs/reports/05-kutuphane-benchmark.md` | 591 | **Pillow vs pyvips vs ffmpeg** — 360 koşum, 0 hata | ✅ **Dalga 3** |
| **(yeni)** | `docs/reports/09-slot-bazinda-istatistik.md` | 412 | **Slot bazında politika uyum ölçümü** — 3.239 eşsiz URL | ✅ **Dalga 3** |
| | **Toplam (12 rapor + bu belge)** | **~8.150** | | |

Yan çıktılar [Ö3 `ls -la`]:

| Dosya / dizin | Durum |
|---|---|
| `tests/fixtures/media/images/` | **34 görsel fixture** [Ö3] |
| `tests/fixtures/media/video/` | **7 video fixture** [Ö3] |
| `tests/fixtures/malicious/` | **10 kötücül fixture** [Ö3] |
| `tests/fixtures/media/manifest.json` + `live-probe.json` | beyan ↔ ölçüm ayrımı + motor koşum kanıtı |
| `fixtures/bench.csv` | benchmark ham verisi (360 satır, 24 sütun) |
| `scripts/gen_fixtures_images.py`, `gen_fixtures_video.sh`, `build_fixture_manifest.py`, `bench_engine.py` | Dalga 3 betikleri |
| `scripts/media_stats.py` | T-003'ün ölçüm betiği — **hâlâ ÇALIŞTIRILMADI ve hâlâ bozuk** (§2 Ç-12) |

### 1.2 T-006 ve T-007 — Rev. 1'de EKSİK, artık ÜRETİLDİ

Rev. 1'in §1.2'si bu iki görevi "❌ YAPILMADI" işaretlemişti. **Durum değişti.**

| Görev | Rev. 1 durumu | Rev. 2 durumu | Kanıt |
|---|---|---|---|
| **T-006** Golden fixture korpusu | ❌ YAPILMADI (`docs/reports/05-*` yok; `find -iname "*golden*"` → 0) | ✅ **ÜRETİLDİ** | `docs/reports/05-fixture-korpusu.md` (450 satır) + `tests/fixtures/` altında **34 + 7 + 10 = 51 dosya** [Ö3 `ls` + `wc -l`] + `manifest.json` (51/51 `expect`↔`olculen` GEÇTİ) + `live-probe.json` (motor koşum çıktısı) |
| **T-007** Kütüphane benchmark'ı | ❌ YAPILMADI (`find -iname "*benchmark*"` → 0); gerekçe: `pyvips` kurulu değil | ✅ **ÜRETİLDİ** | `docs/reports/05-kutuphane-benchmark.md` (591 satır) + `fixtures/bench.csv` (360 koşum, 0 hata). `pyvips 3.1.1` konteynerde **şu an kurulu** [Ö3] |

**T-006'nın kapsam sınırı (dürüstlük).** Korpus üretildi ve doğrulandı, **ama
gerçek fotoğraf içermiyor** — tamamı sentetik. `05-fixture-korpusu.md` §8 bunu
kendi yazıyor: `content_rules` eşikleri (`entropy_bits`,
`blur_laplacian_variance`, `target_ssim_per_class`) bu korpusla **kalibre
edilemez**. Korpus kuralın *çalıştığını* test eder, *eşiğini* değil. Gerçek
fotoğraf örneklemesi canlı `tabFile`'dan yapılabilirdi ama o dosyalar gerçek
satıcı verisidir; repoya kopyalanması ayrı bir KVKK kararı gerektirir. **AS-27
olarak açık bırakıldı.**

**T-007'nin kapsam sınırı (dürüstlük).** Benchmark koşuldu ve karar üretti
("Pillow'da kal, `draft()` ekle"), **ama kurulum kalıcı değil.**
`05-kutuphane-benchmark.md` §1 ölçtü: `libvips` `/usr/lib`'de, `pyvips`
`env/` içinde — ikisi de konteynerin **yazılabilir katmanında**. Kalıcı birim
yalnız `istoc-dev_logs` ve `istoc-dev_sites`. `docker compose up --force-recreate`
kurulumu siler. Ayrıca ImageMagick kolu **hiç ölçülmedi** (kurulu değil,
kurulmadı) — T-007'nin özgün tanımında vardı. **AS-28 olarak açık bırakıldı.**

### 1.3 Kaynak dokümanın 102 görevine göre konum

Bu dalgada kapanan **T-000…T-009 aralığının 10'u** (T-000, T-001, T-002, T-003,
T-004, T-005, T-006, T-007, T-008, T-009). Faz 0'ın toplam görev sayısı bu
çalışma alanından hâlâ doğrulanamıyor [?] — kaynak doküman yerel olarak mevcut
değil. **Yüzde verilmiyor**; verilen tek sayı: **bilinen 10 görevin 10'u
üretildi** (Rev. 1'de 9'un 7'siydi).

> Görev *üretilmiş* olması, görevin *kapanmış* olması demek değildir. Kapanma
> ölçütü §9'da.

---

## 2. Raporlar arası çelişkiler

Rev. 1'in Ç-1…Ç-13'ü **korunmuştur**; her birine "Rev. 2 durumu" eklendi.
Dalga 3'te beş yeni çelişki çıktı: **Ç-14…Ç-18**.

### Ç-1 — Ölçüm koşulu: "Docker kapalı" iddiası YANLIŞ — **KRİTİK (yönetişim)**

Rev. 1'in en pahalı bulgusu. Altı rapor "Docker kapalı" diyerek ölçüm yapmadı;
`00-ortam-envanteri` ise 12 konteynerin `Up` olduğunu ölçmüştü.

| Rapor | Ne diyor | Satır |
|---|---|---|
| 00-ortam-envanteri | *"'Docker kapalı' varsayılmıştı; **kapalı değildi**"* | `:23-28` |
| 00-upload-slot-envanteri | *"Docker kapalı…"* | `:38` |
| 01-dosya-akisi | *"Docker kapalı…"* | `:449` |
| 02-medya-istatistigi | tablo: `Docker \| Kapalı` | `:19` |
| 03-render-envanteri | *"Docker kapalı…"* | `:5` |
| 04-yetki-modeli | *"Docker kapalı…"* | `:655` |
| 06-depolama-maliyet | *"Docker kapalı…"* | `:566` |

**Rev. 2 durumu — ✅ ÇÜRÜTÜLDÜ ve SONUÇLARI ALINDI.**
`docker ps` bugün de 12 servis gösteriyor [Ö3]:
`admin-panel · backend · queue-long · scheduler · queue-short · storefront ·
frappe-frontend · websocket · gateway · redis-queue · redis-cache · db (healthy)`.
Dalga 3'ün beş raporu (`08`, `09`, `03-performans`, `05-fixture`,
`05-kutuphane`) tamamen bu canlı ortamda üretildi. Ç-1'in maliyeti fiilen
ödendi.

⚠ **Ama altı raporun metni HÂLÂ düzeltilmedi.** Bugün `02-medya-istatistigi.md`
açan biri hâlâ `Docker | Kapalı` okuyor. K-4'ün metin düzeltmesi kısmı **açık**.

### Ç-2 — Public/private dosya sayısı — **KRİTİK → Rev. 2'de ÇÖZÜLDÜ, Rev. 1'in düzeltmesi GERİ ALINDI**

Rev. 1 üç küme saymıştı ve *"`MEDYA-DEPOLAMA-STANDARDI.md:31`'in 2.858 etiketi
**yanlıştır**"* demişti. Bunun üzerine `06-depolama`'nın **tüm** mutlak
sayılarına **+%40 düzeltme** önermişti.

**Bu oturumda dört küme birden ölçüldü [Ö3]** ve tablo tamamen açıklandı:

| # | Küme | public | private | toplam | bayt |
|---|---|---:|---:|---:|---:|
| 1 | `tabFile` **satır** (klasör hariç, `file_url` dolu) | 4.350 | 608 | **4.958** | **1.559,5 MB** (mükerrer sayımlı) |
| 2 | Diskteki **fiziksel dosya** (`find -type f`) | 4.016 | 325 | **4.341** | **1.109 MB** (`du -sm`: 944 + 165) |
| 3 | **Eşsiz `file_url`** (dedup'lu adres) | **2.853** | **160** | **3.015** | **998,7 MB** |
| 4 | `inventory._base_query()`'nin gördüğü | — | — | 938 | — | 

| Belge / kod | İddia | Hangi kümeye denk düşüyor |
|---|---|---|
| `MEDYA-DEPOLAMA-STANDARDI.md:31-32` | 2.858 / 192 | **Küme 3** (2.853 / 160) — %0,2 sapma (public) |
| `upload_policy.py:45` (08-14) | 4.003 public | Küme 2 (4.016 bugün) |
| `gates.py:8` (08-06) | 4.007 | Küme 2 |
| `backup.py:7` (08-13) | 4.195 | Küme 2 (public+private kökleri birlikte: 4.341) |
| `inventory.py:10` (08-06) | 938 tekil `file_url` | Küme 4 (dar filtre) |
| `06-depolama §0` | ~1 GB | Küme 3'ün baytı: **998,7 MB** [Ö3] |
| `08-canli-olcum §1` | 4.350 / 608 · 1.559,5 MB | Küme 1 |

**Sonuç — Rev. 1 burada YANILDI.** `MEDYA-DEPOLAMA-STANDARDI.md`'nin 2.858'i
"yanlış" değil, **farklı bir kümenin** (dedup'lu eşsiz adres) sayısıdır ve
bugün **2.853** ölçüldü [Ö3]. Aradaki fark **5 dosya**, 4 günde. Belgenin
*etiketi* ("public/files → 2.858 **dosya**") yanıltıcıdır — o dizinde bugün
4.016 dosya var — ama *sayının kendisi* sağlamdır.

**Bunun doğrudan sonucu:** `06-depolama-maliyet`'in `2.858 + 192 = 3.050`
tabanı, ölçülen `2.853 + 160 = 3.015` [Ö3] ile **%1,1 içinde**. Yani:

| Rev. 1'in dediği | Rev. 2'nin ölçtüğü |
|---|---|
| "06'nın mutlak dosya ve GB rakamlarının hepsi %40 düzeltilmelidir" | **Düzeltme GEREKMİYOR.** Taban doğru kümeyi (varlık = eşsiz adres) sayıyor ve %1,1 sapmayla tutuyor |
| "Senaryo A dosya 168.622 → 236.944 (+%41)" | **168.622 ayakta.** Türev sayısı *varlık* başına hesaplanır; varlık = eşsiz adres |
| "Senaryo A disk 11,32 GB → 15,88 GB" | **11,32 GB ayakta** |

⚠ **Private tarafı bu kadar temiz değil.** Belge 192 diyor, eşsiz private URL
bugün **160** [Ö3] — 4 günde 32 *azalmış* görünüyor. Bu ya silme, ya belge
yazılırken farklı bir filtre. **Açıklanamadı; AS-04 private için AÇIK kalıyor.**

Ayrıntılı belge etkisi analizi: **§8**.

### Ç-3 — Toplam medya hacmi ve birim belirsizliği — **ORTA → hacim ÇÖZÜLDÜ, birim AÇIK**

| Kaynak | Değer | Kapsam |
|---|---:|---|
| **[Ö3] eşsiz URL bayt toplamı** | **998,7 MB** | Küme 3 |
| **[Ö3] disk `du -sm`** | **1.109 MB** (944 + 165) | Küme 2 |
| **[Ö3] `tabFile` satır bazlı** | **1.559,5 MB** | Küme 1 — **mükerrer sayımlı** |
| `media/backup.py:9` | 994 MB | 4.195 dosya |
| `06-depolama §0` | "~1 GB" | public+private |

**Hacim çelişkisi kapandı:** `backup.py`'nin 994 MB'ı ile ölçülen 998,7 MB
**%0,5 içinde**. `06`'nın "~1 GB"ı doğru.

**Birim belirsizliği AÇIK.** `06 §0` aynı satırda hem 330 KB (ondalık 10⁹) hem
344 KB (ikilik 2³⁰) diyor; `upload_policy.py:348` ikilik kullanıyor; kota
satıcıya MB gösteriyor (`entitlement/checks.py:255`). K-6 hâlâ açık.

### Ç-4 — `MAX_BYTES` satır referansları — **ORTA → ÇÖZÜLDÜ (metin düzeltilmedi)**

`01-dosya-akisi §4.2`'nin satır numaraları **+1 kaymış** ([K] Rev. 1). Değerler
(25 / 200 / 50 / 50 / 50 MB) beş raporda da aynı. **Rev. 2:** metin
düzeltilmedi — K-16 açık.

### Ç-5 — `chunked.py` sabit satırları — **ORTA → ÇÖZÜLDÜ (metin düzeltilmedi)**

`02-medya §5.2` `chunked.py:15/19/23` diyor; gerçek `43/47/51` [K]. Değerler
(2 MB / 256 / 6 saat) aynı. **Rev. 2:** metin düzeltilmedi — K-16 açık.

### Ç-6 — Video tavanı için dört ayrı sayı — **ORTAK TESPİT**

DocType açıklaması 10 MB · sunucu politikası 200 MB · panel istemcisi 10 MB ·
**fiilen uygulanan 25 MB** (`effective_max()` = `min(200 MB, 26.214.400)`) [Ö].
Video için ilan/uygulama farkı **183.500.800 bayt (%87,5) sessiz kayıp**.

**Rev. 2 katkısı:** `08 §1.2` ölçtü — canlı dosyaların bayt p99'u **3,6 MB**,
maksimum **22,1 MB**. Yani bugün hiçbir dosya 25 MB tavanına dayanmıyor;
tavan pratikte **hiç tetiklenmiyor**. Ama `08 §7`'nin veri kalitesi uyarısı
önemli: `tabFile.file_size` videolarda **dolu değil** (p50 = 19 bayt) — bayt
tabanlı hiçbir kural bu alana güvenmemeli.

### Ç-7 — "21.430 satır medya kodu" — **DÜŞÜK (yönetişim) → AÇIK**

Görev tanımı 21.430 diyor; ölçülen backend 13.007 + frontend 12.566 =
**25.573** [Ö]. Kapsam tanımsız. **Rev. 2:** değişmedi, K-7 açık.

### Ç-8 — `upload-ui` kütüphanesi İKİ AYRI kopyada — **YÜKSEK → AÇIK**

`tradehubfront` 1.780 satır ↔ `admin-panel` 1.669 satır [Ö]. Her düzeltme iki
kez yapılacak. **Rev. 2:** ölü kod tespiti (Y-39) koşulmadı, iş açılmadı.

### Ç-9 — Master tavanı 1920–2000 px ↔ profil matrisi 2400 px — **YÜKSEK → KARAR HÂLÂ AÇIK, AMA ARTIK SAYILI**

`engine.py:177` → `im.thumbnail((1920, 1920))` [K]; `presets.py:14-16` →
safe 2560 / balanced 2000 / aggressive 1600 [K]. `06 §1.2` `product-zoom` için
2400 px istiyor → **bugünkü hiçbir yoldan üretilemez**.

**Rev. 2'nin eklediği ölçüm — karar artık veriyle verilebilir:**

| Ölçüm | Değer | Kaynak |
|---|---:|---|
| Canlı ürün görsellerinde kısa kenar p50 | **1.138 px** | 09 §4.1 |
| p90 | 2.264 px | 09 §4.1 |
| Kısa kenar < 2000 px olan ürün görseli | **%88,2** (2.110 / 2.393) | 09 §4.1 |
| `docs/standards/policies` tabanı (`min_long_edge=2000`) uygulanırsa | ürün görsellerinin **%97,3'ü düşer** | 09 §5 |
| `media_engine` tabanı (`min_short_edge=1000`) uygulanırsa | **%23,7 düşer** | 09 §4.1 |

**Yani 2400 px'lik bir profil, mevcut stoğun yalnız küçük bir azınlığından
üretilebilir.** Karar (K-9) hâlâ verilmedi, ama artık "hangi seçenek ne kadar
içeriği kırar" sorusunun sayısı var.

### Ç-10 — `06`'nın varlık sınıfı ataması ↔ render kutuları — **ORTA → SAYISALLAŞTI**

Rev. 1: `06 §1.4` `Seller Gallery Image.image`'ı "ürün görseli" sayıp 2400 px'e
kadar profil atıyor; `00-upload-slot §2` aynı slotun render kutusunu **276×276 px**
ölçmüş → 8,7× aşırı tedarik.

**Rev. 2 doğrudan ölçüm getirdi** (`03-performans §3`, §4):

| Ölçülen | Değer |
|---|---|
| Ürün detay galerisi thumbnail'i, ekranda | **59×59 CSS px** |
| Aynı thumbnail'in indirdiği dosya | **orijinal, tam boy** |
| En uç örnek | `020 kirmizi orta 12'li.jpg` — 2.345.178 B, 4480×7255 = **32,50 MP**, ekranda 59×59 px |
| Gösterilen piksel başına indirilen veri | ≈ **674 : 1** |
| Mağaza logosu | 1254×1254, 776.986 B, ekranda **38×38 px** — sayfanın toplam görsel yükünün **%72,7'si** |

**Ç-10 artık "tablo düzeltmesi" değil, ölçülmüş bir israf.** K-8 açık ama
gerekçesi güçlendi.

### Ç-11 — `Attach` / `Attach Image` kırılımı 18/23 ↔ 19/22 — **DÜŞÜK → kayda geçti**

Toplam (41), doctype (30), `Image` tipi (0) doğrulandı [Ö]. Kırılım 1 kaymış.
Karar etkisi yok. **Rev. 2:** değişmedi.

### Ç-12 — `02-medya`'nın komutları KOPYALA-YAPIŞTIR ÇALIŞMAZ — **YÜKSEK (operasyonel) → HÂLÂ AÇIK**

| Komutta yazan | Gerçek |
|---|---|
| `istocc-dev-backend-1` (çift **c**) | `istoc-dev-backend-1` |
| `istocc-dev-db-1` | `istoc-dev-db-1` |
| `tradehub.localhost` | `istoc.localhost` |

**Rev. 2 ölçümü [Ö3] — düzeltme YAPILMADI:**

```
grep -c "istocc"             scripts/media_stats.py                → 2
grep -c "istocc"             docs/reports/02-medya-istatistigi.md  → 7
grep -c "tradehub.localhost" scripts/media_stats.py                → 1
grep -c "tradehub.localhost" docs/reports/02-medya-istatistigi.md  → 4
```

**K-2 kapanmadı.** Dalga 3'ün ölçümleri bu betikle değil, ayrı yazılmış
betiklerle yapıldı (`08 §5` bunu açıkça söylüyor: *"bu rapordaki sayılar o
betiğin canlı koşumundan değil, aynı mantığın doğrudan çalıştırılmasından
gelmiştir"*). Yani sonuç alındı ama **borç ödenmedi**: bugün `02-medya`'nın
komutlarını kopyalayan biri hâlâ hata alır.

### Ç-13 — `06` içi %28 ↔ %37 — **DÜŞÜK → metin düzeltilmedi**

`106,3 / 382 = %27,8`. `06 §4.2`'deki %37 kaynaksız. K-16 açık.

---

### Ç-14 — `08-canli-olcum`'un "toplam disk 1.559,5 MB" etiketi YANLIŞ — **ORTA (yeni)**

`08 §1` tablosu *"Toplam disk | **1.559,5 MB**"* yazıyor.

**Ölçüldü [Ö3]:**

| Ne | Değer |
|---|---:|
| `tabFile` satır bazlı bayt toplamı (aynı dosya birden çok satırda sayılır) | **1.559,5 MB** ← 08'in sayısı |
| Eşsiz `file_url` bazlı bayt toplamı | **998,7 MB** |
| Gerçek disk kullanımı (`du -sm public/files private/files`) | **1.109 MB** |

`tabFile`'da 4.958 satır var ama yalnız **3.015 eşsiz `file_url`** [Ö3] — yani
**1.943 satır aynı adresi tekrar gösteriyor**. 08'in toplamı bu tekrarları
sayıyor. Sayı doğru hesaplanmış, **etiketi yanlış**: "toplam disk" değil,
"referans bazlı toplam bayt".

**Etkisi:** kota, maliyet ve yedek hesaplarında 1.559,5 MB kullanılırsa
gerçek disk yükü **%41 fazla** tahmin edilir. `08 §1` düzeltilmeli.

### Ç-15 — İKİ POLİTİKA SETİ AYNI ALANA 8 KAT FARKLI EŞİK DAYATIYOR — **KRİTİK (yeni, Faz 2'yi bloklar)**

Rev. 1 bunu **G-1** olarak "henüz uzlaştırılmamış iki granülerlik" diye kayda
geçmişti — *"bir çelişki değil"* demişti. **Dalga 3 ölçtü: çelişki.**
(`09-slot-bazinda-istatistik.md` §6)

| alan | `media_engine/policy/slots` | uyumsuzluk | `docs/standards/policies` | uyumsuzluk |
|---|---|---:|---|---:|
| `Listing.primary_image` | kısa kenar ≥ 1000 | **%37,3** | uzun kenar ≥ 2000 | **%97,3** |
| `Listing Image.image` | kısa kenar ≥ 1000 | %61,6 | uzun kenar ≥ 2000 | **%99,4** |
| `Listing Variant Item.variant_image` | kısa kenar ≥ 1000 | %44,9 | uzun kenar ≥ 2000 | **%97,6** |
| `Admin Seller Profile.logo` | kısa kenar ≥ 256, tavan **4096** | %31,6 | 400 ≤ uzun kenar ≤ **1024** | %63,2 |

`Admin Seller Profile.logo`'da üst sınırlar **4096 px ↔ 1024 px**: aynı 17
dosyanın 9'u ikinci kurala takılıyor, birincisine **hiçbiri** takılmıyor.

**İkisi aynı anda yürürlükte olamaz. T-028 migration'ı hangi eşiği
uygulayacağını bilemez.** Bu, G-1'in yükseltilmiş hâlidir → **K-23** (yeni
bloklayıcı).

### Ç-16 — SRS FR-019 ↔ `seller-logo.json`: alfa zorunlu mu opsiyonel mi — **YÜKSEK (yeni)**

`docs/srs/SRS-v1.0.md` **FR-019**: *"logo slotlarında alfa **zorunlu**, alfası
olmayan **reddedilir**"*. `media_engine/policy/slots/seller-logo.json`:
`require.alpha_channel: "optional"`.

**Ölçüm ikincisini haklı çıkardı:**

| Ölçüm | Değer | Kaynak |
|---|---:|---|
| Gerçek logolarda JPEG payı | **%50** (9/18) → **%47,1** (8/17) | 08 §2.1 / 09 §4.6 |
| Alfa kanalı taşıyan logo | **4/17 = %23,5** | 09 §4.6 |
| FR-019 bugün uygulansaydı reddedilecek logo | **%76,5** | 09 §4.6 |
| `seller.logo` v1 politikası (alfa zorunlu) uyumsuzluğu | **%84,2** (16/19) | 09 §4.6 |
| `seller.logo` v2 politikası (alfa opsiyonel) uyumsuzluğu | **%31,6** (6/19) | 09 §4.6 |

**FR-019 metni düzeltilmeli.** Politika dosyası zaten düzeltildi (2026-08-18
09:31), SRS düzeltilmedi. → **K-24**.

### Ç-17 — `entropy_bits` için iki politika iki farklı aksiyon yazıyor — **ORTA (yeni)**

`media_engine/policy/slots/product-image.json` → `content_rules.entropy_bits`
**`action: "reject"`**.
`media_engine/policy/content_rules.json` → `decision_model.reject_allowed_rules`
yalnız `nsfw_content` ve `extreme_blur`.

Aynı kural için iki farklı aksiyon. Üstelik eşiğin kendisi `UNCALIBRATED`
(05-fixture §5 Ç-2) ve **kalibre edilemiyor** — sentetik korpus eşik kalibre
edemez (§1.2). Bugünkü doğru davranış **kabul + uyarı**.

### Ç-18 — `max_megapixels_hard = 80`, canlıdaki maksimum 72,71 MP — eşik ÖLÜ — **YÜKSEK (yeni, güvenlik)**

Üç bağımsız ölçüm aynı yere işaret ediyor:

| Ölçüm | Sonuç | Kaynak |
|---|---|---|
| Canlıda megapiksel maksimumu | **72,71 MP** — tavanın altında, **geçiyor** | 08 §1.3 |
| Canlıda > 20 MP dosya | **179** (görsellerin %3,7'si) | 08 §1.3 |
| `bomb_100mp.png` (95 KB dosya, 100 MP açıyor) | `engine.probe` **okunabilir**, `engine.optimize` **`ok=True`**, 314,8 ms | 05-fixture §4 B-1 |
| Pillow `MAX_IMAGE_PIXELS` (konteyner) | 89.478.485 → yalnız **uyarı**, istisna değil | 05-fixture §4 B-1 |
| `grep MAX_IMAGE_PIXELS tradehub_core/` | **0 sonuç** | 05-fixture §4 B-1 |
| 72,7 MP JPEG'in Pillow tepe belleği | **588 MB** (9,7 MB'lık dosyadan — 60×) | 05-kutuphane §10 |

**Sonuç:** piksel tavanı politikası bugün **yok**; yazılı olan 80 MP eşiği
canlıdaki en büyük dosyayı geçiriyor; kütüphane varsayılanı da durdurmuyor.
95 KB'lık bir yükleme sunucuda 100 MP açtırabiliyor ve **başarıyla işleniyor**.
→ **K-25** (yeni bloklayıcı aday).

### Çelişki özet tablosu

| # | Konu | Şiddet | Rev. 1 durumu | **Rev. 2 durumu** |
|---|---|---|---|---|
| **Ç-1** | "Docker kapalı" iddiası yanlış | KRİTİK (yönetişim) | ✅ çözüldü | ✅ **sonuçları alındı** — 5 yeni rapor canlı ortamda üretildi; ⚠ 6 raporun metni hâlâ düzeltilmedi |
| **Ç-2** | Public/private dosya sayısı | KRİTİK | ⚠ kısmen | ✅ **ÇÖZÜLDÜ [Ö3]** — 4 küme ayrıştırıldı; **Rev. 1'in +%40 düzeltmesi GERİ ALINDI** (§8) |
| **Ç-15** | İki politika seti 8 kat farklı eşik | **KRİTİK (yeni)** | (G-1 olarak "çelişki değil") | ❌ **çelişki olduğu ölçüldü** → K-23 |
| **Ç-18** | `max_megapixels_hard=80` ölü eşik | **YÜKSEK (yeni, güvenlik)** | (AS-08 olarak açık) | ❌ **ölçüldü: bomba geçiyor** → K-25 |
| **Ç-9** | Master 1920–2000 ↔ profil 2400 px | YÜKSEK (Faz 2'yi bloklar) | ❌ karar gerekiyor | ⚠ **karar hâlâ açık, ama artık sayılı** (%88,2 / %97,3) |
| **Ç-16** | SRS FR-019 ↔ `seller-logo.json` alfa | **YÜKSEK (yeni)** | — | ❌ **SRS düzeltilmeli** → K-24 |
| **Ç-8** | `upload-ui` iki ayrı kopyada | YÜKSEK | ✅ tespit edildi | ❌ **değişmedi** — iş açılmadı |
| **Ç-12** | 02'nin komutları yanlış ad taşıyor | YÜKSEK (operasyonel) | ✅ tespit edildi | ❌ **HÂLÂ BOZUK [Ö3]** — K-2 kapanmadı |
| **Ç-10** | Varlık sınıfı ↔ render kutusu | ORTA | ❌ çapraz kontrol gerek | ⚠ **sayısallaştı** (674:1 israf ölçüldü) |
| **Ç-14** | 08'in "toplam disk" etiketi | **ORTA (yeni)** | — | ❌ **08 §1 düzeltilmeli** |
| **Ç-17** | `entropy_bits` iki aksiyon | **ORTA (yeni)** | — | ❌ tekleştirilmeli |
| **Ç-3** | Hacim + GB birim belirsizliği | ORTA | ⚠ kısmen | ✅ **hacim çözüldü [Ö3]**; birim kararı açık (K-6) |
| **Ç-4** | `MAX_BYTES` satır referansları | ORTA | ✅ çözüldü [K] | ⚠ metin düzeltilmedi (K-16) |
| **Ç-5** | `chunked.py` satırları | ORTA | ✅ çözüldü [K] | ⚠ metin düzeltilmedi (K-16) |
| **Ç-6** | Video tavanı 4 farklı sayı | (ortak tespit) | ✅ | ✅ + bayt dağılımı ölçüldü (p99 3,6 MB) |
| **Ç-7** | 21.430 satır iddiası | DÜŞÜK | ⚠ kapsam yazılmalı | ❌ değişmedi (K-7) |
| **Ç-11** | Attach kırılımı 18/23 ↔ 19/22 | DÜŞÜK | ✅ kayda geçti | — |
| **Ç-13** | 06 içi %28 ↔ %37 | DÜŞÜK | ✅ kayda geçti | ⚠ metin düzeltilmedi (K-16) |


---

## 3. Slot envanteri × medya istatistiği çapraz kontrolü

**Rev. 1'in sorusu:** `00-upload-slot-envanteri`'nin listelediği her slot için
`02-medya-istatistigi`'nde bir sayı var mı?
**Rev. 1'in cevabı:** hayır — 41 alanın 4'ünde alan düzeyinde sayı, 12'sinde
yalnız doctype toplamı, **25'inde hiçbir sayı yok**.

**Rev. 2'nin cevabı: bu boşluk büyük ölçüde KAPANDI.**
`09-slot-bazinda-istatistik.md` her Faz 2 politikasını bağlı olduğu gerçek
`(doctype, field)` verisine uyguladı ve ihlalleri saydı.

### 3.1 Kapanan boşluk — sayılarla

| Ölçüt | Rev. 1 | **Rev. 2** | Kaynak |
|---|---|---|---|
| Alan düzeyinde sayısı olan slot | 4 | **34 alan bağı (`media_engine`) + 13 alan (`standards`)** | 09 §1 |
| Toplam alan referansı | — | **6.443** | 09 §2 |
| Eşsiz URL | — | **3.239** | 09 §2 |
| — yerelde açılıp ölçülen raster | — | **2.506** | 09 §2 |
| — yerel video (ffprobe) | — | 5 | 09 §2 |
| — yerel belge (PDF/DOCX) | — | 2 | 09 §2 |
| — **harici URL (dosya bizde değil)** | — | **719** | 09 §2 |
| — kayıt dolu, dosya diskte yok | — | **7** | 09 §2 |
| "Hayalet" alan bağı (DB'de olmayan) | [?] | **0** — 34/34 doğrulandı (`SHOW COLUMNS`) | 09 §1.A |

### 3.2 Slot bazında uyum — ana sonuç

| slot | eşsiz dosya | uyumlu | uyumsuz | % | en sık ihlal |
|---|---:|---:|---:|---:|---|
| `product.image` | 3.061 | 1.573 | **1.488** | **48,6** | harici URL — 668 |
| `document.attachment` | 61 | 3 | **56** | **91,8** | `min_short_edge` (1654) altı — 52 |
| `company.cover_image` | 34 | 28 | 6 | 17,6 | dosya diskte yok — 3 |
| `category.banner` | 32 | 0 | **32** | **100,0** | harici URL — 30 |
| `seller.logo` (v2) | 19 | 13 | 6 | 31,6 | diskte yok — 2 |
| `company.cover_video` | 6 | 1 | 5 | 83,3 | harici URL — 4 |
| `user.avatar` | 6 | 0 | **6** | **100,0** | harici URL — 6 (hepsi) |
| `product.video` | 5 | 1 | 4 | 80,0 | oran dışı — 3 |
| `brand.logo` (v2) | 1 | 1 | 0 | 0,0 | — |

> `company.cover_image` **Faz 2 standartlarının gerçek veriye oturduğu tek
> slottur** (09 §4.5): oran p50 = 2,701, politikanın izin verdiği bandın
> (2:1 … 24:5) tam ortası.

### 3.3 Kritik boşluk (Rev. 1 §3.4): hem SAYI hem RENDER KUTUSU — **artık VAR**

Rev. 1: *"39 alanın hiçbirinde ikisi birden yok."*

| Slot | Dosya sayısı | Render kutusu | İkisi de var mı |
|---|---|---|---|
| `product.image` ailesi | **3.061 eşsiz / 2.393 yerel ölçülen** (09 §4.1) | ana galeri + **59×59 px thumbnail** (03-perf §3) | ✅ **EVET** |
| `seller.logo` | **19 eşsiz, 17 ölçülen** (09 §4.6) | **38×38 px** avatar (03-perf §4.1) | ✅ **EVET** |
| `company.cover_image` | 34 eşsiz, 30 ölçülen (09 §4.5) | 1920×720 kapak, `<img>` 400×300 bildiriyor (03-perf §4.2) | ✅ **EVET** |
| `category.banner` | 32 (30'u harici) | ölçülmedi | ⚠ kısmen |
| `user.avatar` | 6 (hepsi harici) | ölçülmedi | ⚠ kısmen |
| `document.attachment` | 61 | render edilmiyor (indirilir) | — |

**Faz 2'nin profil matrisi artık en az üç slot için hem maliyet hem genişlik
tabanına sahip.** Rev. 1'in "tek bir slot için bile sağlam dosya sayısı yok"
tespiti **artık geçerli değil**.

### 3.4 `LIVE_SOURCES` kapsamı — silme kararının kör noktası (Rev. 1 §3.5) — **SAYISALLAŞTI**

`media/usage.py:32-40` [K] **8** kaynak tanımlıyor; toplam 41 slot alanı var →
**%19,5 kapsam**. Kayıtlı olmayan bir görsel `usage.verdicts_for()` taramasında
"kullanılmıyor" görünür ve **silme adayı** olur.

**Rev. 2'nin ölçtüğü [09 §2 + Ö3]:**

| Ölçüm | Değer |
|---|---:|
| Slotlara bağlı eşsiz **yerel** dosya | 2.513 |
| `tabFile` kaydı | 4.958 |
| → **hiçbir tanımlı slota bağlı olmayan** | ≈ **yarısı** (09 §2) |
| Diskte var, `tabFile`'da **hiç karşılığı yok** (yetim) [Ö3] | **1.334 dosya · 100,6 MB** |
| — public | 1.166 dosya · 76,5 MB |
| — private | 168 dosya · 24,1 MB |
| Yetim örnekleri [Ö3] | `05bd857a….mp4`, `b276b343….webm` (transcode türevleri), `*.csv`/`*.xlsx` (toplu içe aktarma girdileri) |

> **İki farklı "kayıp" var ve karıştırılmamalı:**
> (a) `tabFile` kaydı var, dosya diskte yok → **7** (09 §2) / eşsiz URL bazında **6** [Ö3].
> (b) Dosya diskte var, `tabFile` kaydı yok → **1.334** [Ö3]. Bunlar yedek
> job'unun taradığı ama envanterde görünmeyen dosyalardır; bir kısmı transcode
> türevi, bir kısmı içe aktarma artığı. **Silme otomasyonu bu kümeye
> dokunmadan önce sınıflandırılmalı.**

---

## 4. AÇIK SORULAR

Rev. 1'in AS-01…AS-26'sı **korunmuştur**; "Rev. 2 durumu" sütunu eklendi.
Dalga 3'te altı yeni soru çıktı: **AS-27…AS-32**.

| # | Açık soru | Faz | **Rev. 2 durumu** |
|---|---|---|---|
| **AS-01** | 144 `Seller Application.identity_document` bugün public mi? | Faz 0 | ✅ **ÖLÇÜLDÜ — YEREL DEV TEMİZ.** `public + attached_to_doctype boş` → **0** [Ö3]. Ayrıca yerelde bu alanda yalnız **13** dolu kayıt var, `is_private=0` olan **0** [Ö3]. `presets.py:59`'un "144"ü yerel veriyle uyuşmuyor → o yorum ya üretim ölçümü ya eskimiş. **Üretimde tekrarlanmalı (P-12).** |
| **AS-02** | 44 public dosyanın hassas `content_hash` paylaşımı sürüyor mu? | Faz 0 | ❌ **ÖLÇÜLDÜ — BULGU VAR. 44 [Ö3]**, birebir aynı sayı. Kırılım: KYB Verification **36**, Payment Transaction 3, KYC Verification 3, Order 3, Brand 1, Seller Application 1, Seller Verification 1. **44'ünün tamamı diskte mevcut** [Ö3]. Ayrıntı §7.1 D-2 |
| **AS-03** | Üretim imajında ffmpeg var mı? | Faz 0 | ❌ **AÇIK.** Yerelde VAR (`/usr/bin/ffmpeg`, `ffprobe`; queue-long'da da var — 08 §3). Üretim imajını Press üretiyor, `docker/backend.Dockerfile` kullanılmıyor → **doğrulanmadı** |
| **AS-04** | Public 2.858 mi 4.016 mı; private 192 / 325 / 605'ten hangisi? | Faz 0 | ✅ **PUBLIC ÇÖZÜLDÜ [Ö3]** — dört küme ayrıştırıldı (§2 Ç-2). Belgenin 2.858'i = eşsiz `file_url` (bugün **2.853**). ⚠ **PRIVATE AÇIK**: belge 192, eşsiz URL **160**, disk 325, satır 608 — 192 hâlâ tam oturmuyor |
| **AS-05** | `tr_tradehub` app'i kurulu mu? | Faz 0 | ❌ **AÇIK** — Y-3 koşulmadı |
| **AS-06** | Bulk import ZIP içindeki görseller L0'dan geçiyor mu? | Faz 0 | ❌ **AÇIK** — Y-4 koşulmadı. ⚠ Yetim taramada `*.csv` / `*.xlsx` toplu içe aktarma girdileri **private diskte** bulundu [Ö3] |
| **AS-07** | `GORSEL-OPTIMIZASYON.md` nerede? | Faz 0 (yönetişim) | ❌ **AÇIK** — kodda 8 dosyadan atıf var, çalışma alanında yok |
| **AS-08** | Piksel boyutu / en-boy oranı dağılımı ne? | Faz 1 | ✅ **ÖLÇÜLDÜ.** MP p50 1,56 · p90 5,01 · p99 29,21 · max **72,71**; kısa kenar p50 1.120 · min 32 (08 §1.2). Ürün görsellerinde oran p50 1,000, tam kare %42,3, oran ihlali 564 dosya (09 §4.1). **>20 MP = 179** (08 §1.3) |
| **AS-09** | Master tavanı 1920/2000 kalacak mı, profil 2400'ü mü bırakacak? | Faz 1 kararı | ⚠ **KARAR AÇIK, ama sayı geldi**: kısa kenar < 2000 olan ürün görseli **%88,2**; `standards` tabanı uygulanırsa **%97,3** düşer (09 §4.1/§5) |
| **AS-10** | Türevler `File` kaydı üretecek mi? | Faz 2 | ❌ **AÇIK.** ⚠ Yeni kanıt: transcode türevleri (`.webm`) bugün **`tabFile` kaydı olmadan** diskte duruyor [Ö3] — emsal fiilen "kayıt üretme" yönünde |
| **AS-11** | `backup.py` türev desenini dışlayacak mı? | Faz 2 (üretim öncesi ZORUNLU) | ❌ **AÇIK**. Yedek job'u bugün **1.334 yetim dosyayı da** tarıyor [Ö3] |
| **AS-12** | Slot kimliği sunucuya nasıl taşınacak? | Faz 2 — yapısal blokaj | ❌ **AÇIK.** `upload_policy.check()` (`:307-313`) hâlâ slot parametresi almıyor. ⚠ Ç-15 bunu ağırlaştırdı: **hangi anahtar şeması** sorusu da cevapsız |
| **AS-13** | `srcset` eklenmeden `mediaUrl.ts` genişletilecek mi? | Faz 2 (ön koşul) | ⚠ **AÇIK ama sayısallaştı**: storefront kaynak kodunda `srcset` **0 dosya**, `<picture>` **0 dosya**, `fetchpriority` **1 dosya**; ölçülen 130 `<img>`'in **0'ında** `srcset` (03-perf §2.2) |
| **AS-14** | `EXCLUDED_DOCTYPES` ↔ `EXCLUDED_MEDIA_FIELDS` senkronu | Faz 1 | ❌ **ÖLÇÜLDÜ — BOŞLUK DOĞRULANDI [Ö3].** `EXCLUDED_DOCTYPES` = **8**, `EXCLUDED_MEDIA_FIELDS` = **5 doctype / 6 alan**. Haritasız: `Order`, `Payment Transaction`, `Data Export Request`. KYB'nin 6 alanından yalnız **2**'si haritada (§7.1 D-23) |
| **AS-15** | Satıcı alt kullanıcılarında `System User` rolü var mı? | Faz 1 | ❌ **AÇIK** — Y-29 koşulmadı |
| **AS-16** | İmzalı link iptali gerekli mi? | Faz 2 sonrası | ❌ **AÇIK** — değişmedi |
| **AS-17** | `.heic` politikada kabul, Pillow'da HEIF yok — sahada ne oldu? | Faz 1 | ⚠ **KISMEN.** 08 §1.1 formatları ölçtü: **JPEG/PNG/WEBP/TIFF, HEIC yok**. Ama **59 dosya açılamadı** — içlerinde HEIC olup olmadığı ayrıştırılmadı. Error Log taraması (Y-1) koşulmadı |
| **AS-18** | AVIF Pillow'da hazır ama `SUPPORTED_FORMATS`'ta yok — açılacak mı? | Faz 2 ön koşulu | ❌ **AÇIK.** `engine.py:21` = `{JPEG,PNG,WEBP,TIFF}` [K]. Benchmark AVIF encode maliyetini **ölçmedi** (motor reddettiği için kapsam dışı bırakıldı — 05-kutuphane §13) |
| **AS-19** | `upload-ui` iki kopya birleştirilecek mi? | Faz 1 (borç) | ❌ **AÇIK** — Y-39 koşulmadı |
| **AS-20** | Aylık yeni varlık oranı `r`, egress `E_gb`, `N_get` | Faz 2 sonrası | ❌ **AÇIK** |
| **AS-21** | Türev `bpp` varsayımları gerçek görsellerde tutuyor mu? | Faz 1 | ⚠ **KISMEN.** Benchmark 10 gerçek dosyada kaynak 53,32 MB → çıktı ~6,2–6,8 MB, **%87–88 tasarruf** ölçtü (05-kutuphane §7). Ama **format başına bpp** (AVIF 0,045 / WebP 0,075 / JPEG 0,110) **ayrıştırılmadı**; AVIF hiç ölçülmedi |
| **AS-22** | "21.430 satır medya kodu" hangi kapsam? | Faz 0 (yönetişim) | ❌ **AÇIK** |
| **AS-23** | GB ondalık mı ikilik mi? | Faz 1 | ❌ **AÇIK** |
| **AS-24** | 5 slot ölü mü (`Seller Product.image`, `Seller Review.product_image`, `Shipping Channel.icon`, `Verification Source.icon`, `Logistics Provider.logo`)? | Faz 1 | ✅ **BÜYÜK ÖLÇÜDE ÖLÇÜLDÜ (09 §0/§5):** `Shipping Channel.icon` → 5 kayıt, **hepsi boş**; `Seller Product.image` → **0 kayıt**; `Listing Review Image` → **0 kayıt**; `Shipment Document` → 0 kayıt; `Data Processing Agreement` → 0 kayıt; `Listing Variant Item.variant_video_url` → **0 dolu kayıt**. `Verification Source.icon` ve `Logistics Provider.logo` ölçülmedi |
| **AS-25** | Panelden yüklenen görseller storefront'ta görünüyor mu? | Faz 1 | ❌ **AÇIK** — Y-6 koşulmadı |
| **AS-26** | Prod nginx sertleştirmesi gerçekten eksik mi? | Faz 1 | ⚠ **YEREL TARAF ÖLÇÜLDÜ.** `istoc-dev-storefront-1`'de `limit_req zone=files_zone` ve `X-Robots-Tag: noindex` **VAR** (03-perf §5.1). Prod hâlâ doğrulanmadı (P-10). ⚠ **Yeni bulgu:** aynı blok `Cache-Control` **üretmiyor** → `/files/` yolunda hiçbir önbellek yönergesi yok (03-perf §5) |
| **AS-27** *(yeni)* | **Gerçek fotoğraf korpusu repoya alınacak mı?** | Faz 1 | ❌ **AÇIK.** T-006 korpusu tamamen sentetik; `content_rules` eşikleri (`entropy_bits`, `blur_laplacian_variance`, `target_ssim_per_class`) **kalibre edilemiyor**. Canlı `tabFile`'dan örnekleme teknik olarak mümkün ama KVKK/ticari gizlilik kararı gerektiriyor (05-fixture §8, §10) |
| **AS-28** *(yeni)* | **`libvips`/`pyvips` kurulumu kalıcı hâle getirilecek mi — yoksa T-007 kalıcı olarak "ölçüldü, ertelendi" mi?** | Faz 1 | ⚠ **Benchmark cevabı verdi: pyvips'e GEÇME.** Kurulum bugün konteynerde var [Ö3] ama `--force-recreate`'te silinir (05-kutuphane §1). Karar "kurulum kalıcı olsun mu" değil, **"K-11 ölçüldü diye kapatılsın mı"** |
| **AS-29** *(yeni)* | **Hangi politika seti kaynak-doğru (source of truth)?** | **Faz 1 — Faz 2'yi bloklar** | ❌ **AÇIK.** `media_engine/policy/slots` (9 slot / 34 alan bağı) ↔ `docs/standards/policies` (13 slot / 13 alan). Aynı alana **8 kat farklı** eşik (Ç-15). T-028 migration'ı bunsuz yazılamaz |
| **AS-30** *(yeni)* | **719 harici URL yerelleştirilecek mi?** | Faz 1 | ❌ **AÇIK.** 668'i ürün görseli (`cdn.dummyjson.com`), 30'u kategori banner'ı, 6'sı avatar (`ui-avatars.com` / gravatar). Medya motorunun bu dosyalar üzerinde **sıfır kontrolü var** (09 §4.4, §8) |
| **AS-31** *(yeni)* | **`product-video.json`'a süre kuralı eklenecek mi?** | Faz 2 | ❌ **AÇIK.** Canlıdaki **540 sn**'lik video `needs_transcode()`'un iki eşiğinin de altında → **hiç işlenmiyor** (05-fixture §4 B-6). Politikada `accept`'te de `require`'da da **süre alanı yok** |
| **AS-32** *(yeni)* | **`Order.receipt_url` / `Payment Transaction.receipt_url` dosyaları korumasız — kabul mü ediliyor?** | **Faz 0/1 (güvenlik)** | ❌ **ÖLÇÜLDÜ — 2 korumasız dosya** (08 §6). `attached_to_doctype` boş **ve** `EXCLUDED_MEDIA_FIELDS` haritasında yok → iki koruma yolundan **ikisi de** devre dışı. 4 haritasız KYB alanında bugün açık dosya yok — boşluk **gizil** |

---

## 5. FAZ 1'E GEÇMEDEN ÖNCE YAPILMASI GEREKENLER

Rev. 1'in K-1…K-22'si korunmuştur; "Rev. 2 durumu" eklendi. Dalga 3'te üç yeni
kalem: **K-23…K-25**.

### 5.1 Bloklayıcılar (geçmeden önce ZORUNLU)

| # | Yapılacak | **Rev. 2 durumu** | Kanıt |
|---|---|---|---|
| **K-1** | AS-01 + AS-02'yi koş | ⚠ **KOŞULDU — YARISI TEMİZ, YARISI BULGU.** D-1 → **0** (temiz). D-2 → **44** (bulgu var). Kalem **kapanmadı**: 44 dosyanın içerik sınıflandırması yapılmadı | [Ö3] §7.1 |
| **K-2** | `media_stats.py` + `02-medya` komutlarını düzelt, betiği ÇALIŞTIR | ❌ **YAPILMADI.** `istocc` hâlâ 2 + 7 kez, `tradehub.localhost` hâlâ 1 + 4 kez geçiyor [Ö3]. Betik hâlâ çalıştırılmadı. Ölçümler **başka betiklerle** yapıldı — sonuç alındı, borç ödenmedi | [Ö3] `grep -c` |
| **K-3** | AS-03'ü koş: üretim imajında ffmpeg var mı? | ❌ **YAPILMADI** — üretim erişimi yok | — |
| **K-4** | 6 raporun "Docker kapalı" gerekçesini düzelt; ölçülebilenleri ölç | ⚠ **KISMEN.** Ölçüm tarafı: 39 kalemin **10'u tam, 8'i kısmen** kapandı (§7.2). Metin tarafı: **hiçbir rapor düzeltilmedi** | §7.2 |

### 5.2 Yeni bloklayıcı adayları (Dalga 3)

| # | Yapılacak | Neden bloklayıcı | Kanıt |
|---|---|---|---|
| **K-23** | **AS-29'a karar ver: iki politika setinden biri kaynak-doğru ilan edilsin** | Aynı alana 8 kat farklı eşik. `Listing.primary_image` için biri %37,3 diğeri %97,3 uyumsuzluk üretiyor. T-028 migration'ı hangi eşiği uygulayacağını **bilemez** | Ç-15; 09 §6 |
| **K-24** | **SRS FR-019'u ölçüme göre düzelt (logo alfa zorunluluğu)** | Bugünkü hâliyle uygulanırsa mevcut logo stoğunun **%76,5'i** reddedilir. Politika dosyası zaten düzeltildi, SRS düzeltilmedi → iki kaynak çelişiyor | Ç-16; 09 §4.6 |
| **K-25** | **Kod çözmeden ÖNCE megapiksel kapısı; `max_megapixels_hard` eşiğini gözden geçir** | 95 KB'lık bir dosya bugün 100 MP açtırıyor ve `optimize()` **`ok=True`** dönüyor. 72,71 MP'lik canlı dosya 80 eşiğinden geçiyor. Pillow'un kendi koruması yalnız **uyarı** basıyor. `draft()` PNG/WebP'yi kurtarmıyor | Ç-18; 05-fixture §4 B-1; 05-kutuphane §10 |

### 5.3 Faz 1'in girdisini doğrulayanlar

| # | Yapılacak | **Rev. 2 durumu** |
|---|---|---|
| **K-5** | AS-04'ü çöz: taban dosya sayısını sabitle | ✅ **YEREL DEV İÇİN ÇÖZÜLDÜ [Ö3].** Kanonik taban önerisi: **varlık = eşsiz `file_url` = 3.015** (public 2.853 / private 160). `06-depolama`'nın 3.050'lik tabanı bu kümeyle **%1,1 içinde** — düzeltme gerekmiyor (§8). ⚠ Üretim ve private-192 açık |
| **K-6** | GB/MB birim konvansiyonunu tek yerde yaz | ❌ yapılmadı |
| **K-7** | "Medya kodu" kapsam tanımını yaz | ❌ yapılmadı |
| **K-8** | `06 §1.4` varlık sınıfı atamasını render kutularıyla çapraz kontrol et | ⚠ **girdi hazır, iş yapılmadı.** 03-perf §3/§4 render kutularını ölçtü (59×59, 38×38, 195×195, 242×242); 09 §3 slot dosya sayılarını verdi. Tabloyu düzeltmek artık mekanik |
| **K-9** | AS-09'a karar ver: master tavanı mı, profil matrisi mi | ⚠ **karar verilmedi, ama sayı geldi** (%88,2 / %97,3) |
| **K-10** | T-006 golden fixture korpusunu üret | ✅ **YAPILDI** — 51 fixture, 51/51 doğrulama GEÇTİ [Ö3]. ⚠ gerçek fotoğraf yok → AS-27 |
| **K-11** | T-007 için imaja `libvips`+`pyvips` ekle ya da benchmark'ı iptal et | ✅ **ÖLÇÜLDÜ, karar üretildi:** *"Pillow'da kal, `draft()` ekle."* pyvips kutudan çıktığı hâliyle **0,94× (Pillow'dan yavaş)**; ayarlanmış hâli 1,37× ama kazancın tamamı korpusun **%3,7'sinde**; 38 CMYK dosyanın **rengini değiştiriyor**. → K-11 **"ölçüldü, ertelendi" olarak kapatılabilir** (AS-28) |
| **K-12** | AS-18'e karar ver: AVIF `SUPPORTED_FORMATS`'a girecek mi | ❌ karar verilmedi; AVIF encode maliyeti de **ölçülmedi** |
| **K-13** | AS-13'ü kayda geçir: `srcset` işi `mediaUrl.ts` ile birlikte | ⚠ kayda geçti + sayısallaştı (0/130 `<img>`'de `srcset`) |
| **K-14** | AS-14: `EXCLUDED_DOCTYPES` ↔ `EXCLUDED_MEDIA_FIELDS` senkron testi yaz | ❌ **test yazılmadı**, ama boşluk **ölçüldü** [Ö3]: 8 doctype ↔ 5 doctype / 6 alan |
| **K-15** | AS-19: `upload-ui` iki kopya borcunu iş olarak aç | ❌ yapılmadı |
| **K-16** | `06 §4.2` %37→%28; `01 §4.2` satır +1; `02 §5.2` `chunked.py` satırları | ❌ **hiçbiri düzeltilmedi** |

### 5.4 Faz 2'ye kadar erteleyebilir olanlar

| # | Kalem | **Rev. 2 durumu** |
|---|---|---|
| K-17 | AS-10 (türev `File` kaydı) | ⚠ emsal güçlendi: transcode türevleri bugün kayıtsız diskte [Ö3] |
| K-18 | AS-11 (`backup.py` türev dışlaması) | ⚠ kapsam büyüdü: 1.334 yetim dosya da taranıyor [Ö3] |
| K-19 | AS-16 (imzalı link iptali) | değişmedi |
| K-20 | AS-20 (`r`, `E_gb`, `N_get`) | değişmedi |
| K-21 | AS-24 (ölü slotlar) | ✅ **büyük ölçüde ölçüldü** (09 §0/§5) — 6 alan/doctype'ta 0 kayıt doğrulandı |
| K-22 | AS-26 (prod nginx sertleştirmesi) | ⚠ yerel taraf ölçüldü (03-perf §5.1); prod açık. **Yeni:** `/files/`'ta `Cache-Control` yok |


---

## 6. Kapsam dışı ama Faz 1 kapısını etkileyen iki gözlem

### G-1 — İKİ paralel slot kayıt defteri — **Rev. 1'de "çelişki değil", Rev. 2'de ÇELİŞKİ**

| Kayıt defteri | Slot | Alan bağı | Anahtar şeması | Örnek |
|---|---:|---:|---|---|
| `docs/standards/policies/*.json` | **13** | 13 | `<alan>.<slot>` | `listing.primary_image`, `seller.logo` |
| `media_engine/policy/slots/*.json` | **9** | **34** | `<varlık>.<tip>` | `product.image`, `seller-logo` |

Rev. 1: *"Bu bir çelişki değil, henüz uzlaştırılmamış iki granülerlik."*

**Rev. 2 düzeltmesi: bu bir çelişki.** `09 §6` iki seti aynı veriye uyguladı ve
**8 kat farklı eşik** ölçtü (Ç-15). Ayrıca `09 §7-A` üç `bound_to` hatası buldu:

1. `seller.logo` → `Storefront Layout.sections` (`header.logo`) — **YANLIŞ.**
   34 kaydın tamamı tarandı; `sections` JSON'ında `header.logo` anahtarı **hiç yok**.
   Bulunan tek URL yolu `[].settings.slides[].image` (32 adet, hero slide görselleri).
2. `company.cover_video` → `Seller Gallery Image.poster_image` — **TARTIŞMALI.**
   Poster bir görsel; video slotunun `.mp4/.webm/.mov/.m4v` listesine göre
   değerlendirilince **otomatik ihlal** üretiyor.
3. `document.attachment` → `Order.receipt_url` + `Payment Transaction.receipt_url`
   aynı 3 dosyayı gösteriyor (boyutlar birebir aynı) — slot tanımı hatalı değil,
   **veri mükerrer**.

Ayrıca `Category Showcase Tile.image` ve `Brand.hero_banner` **iki farklı slota**
bağlı ve iki farklı kural taşıyor (09 §7-B).

→ **K-23**.

### G-2 — Faz 0 raporları hiçbir git commit'ine girmemiş — **DEĞİŞMEDİ**

[Ö3] `git status --short`, 2026-08-18:

```
?? docs/plans/          ?? docs/reports/        ?? docs/srs/
?? docs/standards/      ?? fixtures/            ?? media_engine/
?? scripts/bench_engine.py            ?? scripts/build_fixture_manifest.py
?? scripts/calibrate_content_rules.py ?? scripts/gen_fixtures_images.py
?? scripts/gen_fixtures_video.sh      ?? scripts/media_stats.py
?? scripts/plan_backfill.py           ?? tests/
```

**14 girdi, hepsi `untracked`.** Son commit hâlâ
`dcddef3 Merge remote-tracking branch 'origin/version-15' into ahmet`.

**Dalga 3, Dalga 2'nin uyarısına rağmen aynı hatayı tekrarladı — üstelik
riski büyüterek:** artık versiyonlanmamış çıktıya **51 fixture dosyası, 360
satırlık benchmark ham verisi ve `live-probe.json` motor koşum kanıtı** da
dâhil. Bu dosyalar kaybolursa T-006 ve T-007 **yeniden üretilmek zorunda**
kalır — ve `05-kutuphane-benchmark.md` §1'in ölçtüğü gibi, pyvips kurulumu bir
`--force-recreate` ile zaten uçuyor.

> `02-medya §3 T-9`'un `GORSEL-OPTIMIZASYON.md` için tespit ettiği kayıp,
> bugün 12 rapor + korpus + ham veri için **açık bir risk**.

---

## 7. ÜRETİMDE DOĞRULANMALI — konsolide liste ve karne

Rev. 1 yedi raporun doğrulama bölümlerini birleştirmişti: **67 numaralı kalem**,
Ç-1 gereği ikiye ayrılmıştı — **39 benzersiz kalem yerel dev'de koşulabilir**
(§7.2), **19'u gerçekten üretim erişimi gerektiriyor** (§7.3), 5'i
`00-ortam-envanteri` tarafından zaten cevaplanmıştı (§7.4).

### 7.1 Güvenlik kalemleri — bu oturumda KOŞULDU

#### D-1 — `Seller Application.identity_document` / `Seller Certification.document` public mi? (AS-01, K-1) — ✅ **TEMİZ**

```
Seller Application.identity_document · is_private=0 · attached_to_doctype boş  →  0   [Ö3]
Seller Certification.document        · is_private=0 · attached_to_doctype boş  →  0   [Ö3]
Seller Application'da dolu identity_document kaydı                             →  13  [Ö3]
    bunlardan is_private=0 olan                                                →  0   [Ö3]
```

**Beklenen 0'dı, ölçülen 0.** Yerel dev'de aktif KVKK olayı **yok**.

⚠ **İki uyarı:**
1. `presets.py:59`'un kaydettiği **144** sayısı yerel veride **yok** — burada
   yalnız 13 dolu kayıt var. O yorum ya üretim ölçümüdür ya eskimiştir. **Bu
   ölçüm üretimi doğrulamaz** (P-12 hâlâ açık).
2. D-1'in temiz çıkması, PII'nin korunduğu anlamına gelmiyor — D-2 ve AS-32
   bunu çürütüyor.

#### D-2 — Hassas `content_hash` paylaşan public dosya (AS-02, K-1) — ❌ **BULGU VAR: 44**

`EXCLUDED_DOCTYPES` elle yazılmadı, `presets.py`'den okundu.

```
Hassas hash paylaşan public dosya (DISTINCT file_url)  →  44   [Ö3]
```

**Karşı tarafın kırılımı [Ö3]:**

| Karşı taraftaki hassas kayıt | Public dosya |
|---|---:|
| **KYB Verification** (private) | **36** |
| Payment Transaction | 3 |
| KYC Verification (private) | 3 |
| Order | 3 |
| Brand (private) | 1 |
| Seller Application (private) | 1 |
| Seller Verification (private) | 1 |

**44 public `file_url`'ün 44'ü de diskte mevcut** [Ö3] — yani bunlar ölü DB
kaydı değil, **fiilen servis edilebilir dosyalar**.

> **Ne ÖLÇÜLDÜ:** aynı `content_hash`'e sahip bir kaydın hem public hem hassas
> tarafta bulunduğu. Yani hassas bir KYB/KYC belgesinin **bayt-bayt aynısı**
> public bir adresten erişilebilir durumda.
>
> **Ne ÖLÇÜLMEDİ:** bu 44 dosyanın içeriğinin gerçekten PII olup olmadığı.
> Dosya adları (`Bere-1.png`, `ChatGPT Image 9 Tem 2026 14_00_30.png`,
> `Gemini_Generated_Image_np9h1e….png`) bir kısmının **sıradan ürün/marka
> görseli** olduğunu düşündürüyor — yani satıcı aynı görseli hem ürün görseli
> hem KYB belgesi olarak yüklemiş olabilir. **Bu ayrım elle yapılmalı.**
> Sınıflandırma yapılmadan K-1 kapatılamaz; ama "44 kimlik belgesi sızdı"
> demek de **kanıtsız olur**.

#### D-23 — `EXCLUDED_DOCTYPES` ↔ `EXCLUDED_MEDIA_FIELDS` senkron açığı (AS-14, K-14) — ❌ **BOŞLUK DOĞRULANDI**

```
EXCLUDED_DOCTYPES (8)  [Ö3]:
  KYB Verification · KYC Verification · Seller Certification · Seller Verification
  Seller Application · Order · Payment Transaction · Data Export Request

EXCLUDED_MEDIA_FIELDS (5 doctype / 6 alan)  [Ö3]:
  KYC Verification     -> identity_document
  Seller Application   -> identity_document
  KYB Verification     -> identity_document, bank_account_document
  Seller Certification -> document
  Seller Verification  -> document
```

| Boşluk | Kapsam |
|---|---|
| Haritada **hiç olmayan** doctype | `Order`, `Payment Transaction`, `Data Export Request` |
| KYB'nin gerçek ek alanı | **6** (`identity_document`, `imza_sirkuleri`, `ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi`, `bank_account_document`) |
| KYB'den haritalanan | **2** |
| KYB'de **haritasız** | **4** — `imza_sirkuleri`, `ticaret_sicil_gazetesi`, `faaliyet_belgesi`, `vergi_levhasi` |

> Rev. 1 "5 doctype / 7 alan" yazmıştı; ölçüm **6 alan** gösteriyor [Ö3].
> Bugünkü fiili maruziyet (08 §6): `Order.receipt_url` **1** dosya ve
> `Payment Transaction.receipt_url` **1** dosya — ikisi de `attached_to_doctype`
> boş **ve** haritasız → **her iki koruma yolu da devre dışı**. 4 haritasız KYB
> alanında bu veri setinde açık dosya yok; boşluk **gizil** (AS-32).

#### D-3 / D-4 / D-5 — Taban mutabakatı (AS-04, K-5) — ✅ **YEREL DEV İÇİN ÇÖZÜLDÜ**

```
tabFile satır (klasör hariç, file_url dolu)   4.958   (public 4.350 / private 608)   [Ö3]
Eşsiz file_url                                3.015   (public 2.853 / private   160) [Ö3]
Diskteki fiziksel dosya                       4.341   (public 4.016 / private   325) [Ö3]
inventory._base_query()'nin gördüğü             938   (kod yorumu, 08-06)            [R]

Bayt — satır bazlı (mükerrer sayımlı)       1.559,5 MB   [Ö3]
Bayt — eşsiz file_url bazlı                   998,7 MB   [Ö3]
Disk du -sm (public 944 + private 165)      1.109    MB   [Ö3]

Eşsiz URL'den diskte olmayan                        6   [Ö3]
Diskte var, tabFile'da karşılığı yok (yetim)    1.334 dosya / 100,6 MB  [Ö3]
   public 1.166 / 76,5 MB · private 168 / 24,1 MB
```

**Kanonik taban önerisi (Faz 1'e devir):** *varlık* = **eşsiz `file_url`**.
Bugünkü değeri **3.015**. Türev, kota ve maliyet hesapları bu kümeye
dayanmalıdır; `tabFile` satır sayısı (4.958) **referans** sayar, disk sayısı
(4.341) **yetimleri** içerir.

#### D-20 — Frappe `max_file_size` — yerel için CEVAPLI, üretim AÇIK

Yerel: System Settings `"0"`, config'lerde anahtar yok → **26.214.400** [Ö].
Üretim: P-7 hâlâ açık.

---

### 7.2 39 kalemlik "Docker açılınca koş" listesinin KARNESİ

**Sonuç: 10 kalem TAM kapandı, 8 kalem KISMEN kapandı, 21 kalem AÇIK.**

| Y# | Kalem | Durum | Kanıt / neden |
|---|---|---|---|
| Y-1 | `.heic`/`.avif` dosya sayısı ve Error Log | ⚠ **KISMEN** | 08 §1.1: formatlar JPEG/PNG/WEBP/TIFF — HEIC/AVIF **yok**. Ama 59 dosya açılamadı, ayrıştırılmadı; Error Log taranmadı |
| Y-2 | Parçalı yüklemede 25 MB üstü nerede reddediliyor | ❌ AÇIK | koşulmadı |
| Y-3 | `tr_tradehub` app'i kurulu mu | ❌ AÇIK | koşulmadı |
| Y-4 | Bulk import ZIP içi görseller L0'dan geçiyor mu | ❌ AÇIK | koşulmadı |
| Y-5 | Ölü slotların gerçek kullanım sayıları | ✅ **KAPANDI** | 09 §0/§5: `Shipping Channel.icon` 5 kayıt hepsi boş; `Seller Product`, `Listing Review Image`, `Shipment Document`, `Data Processing Agreement` → 0 kayıt; `variant_video_url` → 0 dolu |
| Y-6 | Panelden yüklenenlerde `is_private` dağılımı | ❌ AÇIK | koşulmadı |
| Y-7 | Gerçek piksel boyutu ve en-boy oranı dağılımı | ✅ **KAPANDI** | 08 §1.2 (MP/kısa kenar yüzdelikleri) + 09 §4.1 (slot bazında oran dağılımı, 564 oran ihlali) |
| Y-8 | Slot başına dosya sayısı + toplam bayt | ✅ **KAPANDI** | 09 §2, §3, §4 |
| Y-9 | `LIVE_SOURCES` eksiğinin gerçek maliyeti | ⚠ **KISMEN** | 09 §2: `tabFile`'ın ~yarısı hiçbir slota bağlı değil. `usage.verdicts_for()` çıktısıyla çakıştırma yapılmadı |
| Y-10 | Kanca sırası canlıda gerçekten böyle mi | ❌ AÇIK | koşulmadı |
| Y-11 | Reddedilen dosya diskte kalmıyor mu | ❌ AÇIK | koşulmadı |
| Y-12 | Disk kalıntısı ne kadar yaşıyor | ❌ AÇIK | koşulmadı |
| Y-13 | Shard dağılımı dengeli mi | ❌ AÇIK | koşulmadı |
| Y-14 | `upload_policy` tavanları bugünkü veriyle uyumlu mu | ⚠ **KISMEN** | 08 §1.2: bayt p99 3,6 MB, max 22,1 MB → 25 MB tavanı hiç tetiklenmiyor. Uzantı/tür bazında karşılaştırma yapılmadı |
| Y-15 | MariaDB sürümü (`PERCENTILE_CONT` var mı) | ❌ AÇIK | gereksizleşti (yüzdelikler Python'da hesaplandı) ama ölçülmedi |
| Y-16 | `th_media_width` kapsam yüzdesi | ❌ AÇIK | koşulmadı |
| Y-17 | p50 / p90 / p99 boyut (3 kapsam) | ✅ **KAPANDI** | 08 §1.2 + 09 §4.1/§4.2/§4.5 (slot bazında) |
| Y-18 | >20 MP, CMYK, 0 bayt, uzantı-içerik uyuşmazlığı, DB↔disk sapma | ⚠ **KISMEN** | 08 §1.3: >20 MP **179**, CMYK **38**, 0 bayt **0**, >20 MB **1**. **Uzantı-içerik uyuşmazlığı canlı veride ölçülmedi** (yalnız fixture'da: 05-fixture §4 B-3). DB↔disk sapma yalnız video için not edildi (08 §7) |
| Y-19 | Shard geçişi + hash'siz ad oranı | ❌ AÇIK | koşulmadı |
| Y-20 | `usage` sayacı ↔ filtre ayrışması (356 vs 333) | ❌ AÇIK | koşulmadı |
| Y-21 | 16 kaynak tablodaki gerçek referans sayısı | ✅ **KAPANDI** | 09 §2: 6.443 alan referansı / 3.239 eşsiz URL; 34 alan bağının 34'ü DB'de doğrulandı |
| Y-22 | Uzantı karması ve motor kapsamı | ✅ **KAPANDI** | 08 §1.1: JPEG 3.631 / PNG 786 / WEBP 384 / TIFF 11 — dördü de `SUPPORTED_FORMATS` içinde |
| Y-23 | Yetim dosya / kayıp dosya | ⚠ **KISMEN→büyük ölçüde** | [Ö3]: yetim **1.334 dosya / 100,6 MB**; kayıp (kayıt var, dosya yok) **6–7**. Yetimlerin sınıflandırması (türev mi, artık mı) yapılmadı |
| Y-24 | `image_originals` + `media_trash` + `media-backups` disk yükü | ✅ **KAPANDI** | [Ö3]: üç dizin de **0 dosya** |
| Y-25 | Gerçek CSS kutu genişlikleri (DOM ölçümü) | ✅ **KAPANDI** | 03-perf §3/§4: 59×59, 195×195, 242×242, 38×38 px ölçüldü |
| Y-26 | Lighthouse 4 sayfa × 2 profil | ⚠ **KISMEN** | LCP/CLS **ölçüldü** (DevTools trace, 4 sayfa × 2 profil — 03-perf §2.3). **Lighthouse koşulmadı**; performans skoru, Speed Index, TBT yok (03-perf §6.1) |
| Y-27 | Görsel dosya boyutu dağılımı, 1920 px'e dayanmış master oranı, format dağılımı | ⚠ **KISMEN** | Boyut ve format dağılımı ✅ (08 §1.1/§1.2). **"1920 px'e dayanmış master oranı" ölçülmedi** |
| Y-28 | Rol kapıları gerçekten kapalı mı (SM vs MA) | ❌ AÇIK | koşulmadı |
| Y-29 | Satıcı alt kullanıcılarında `System User` rolü | ❌ AÇIK | koşulmadı |
| Y-30 | Satıcı izolasyonu uçtan uca | ❌ AÇIK | koşulmadı |
| Y-31 | PII korumasının canlı kapsamı | ✅ **KAPANDI** | 08 §6 + [Ö3] D-2/D-23 |
| Y-32 | Eksik 3 doctype'ta dosya alanı var mı | ✅ **KAPANDI** | 09 §1.A + 08 §6: `Order.receipt_url` ve `Payment Transaction.receipt_url` **var ve dolu**; `Data Export Request` ayrıca doğrulanmadı |
| Y-33 | İmzalı URL uçtan uca (4 senaryo) | ❌ AÇIK | koşulmadı |
| Y-34 | Varlık sınıfı dağılımı | ✅ **KAPANDI** | 09 §3 — slot bazında tam kırılım |
| Y-35 | **Gerçek bpp** | ⚠ **KISMEN** | 05-kutuphane §7: kaynak 53,32 MB → çıktı 6,2–6,8 MB (**%87–88 tasarruf**), 10 gerçek dosyada. **Format başına bpp ayrıştırılmadı; AVIF hiç ölçülmedi** |
| Y-36 | Aylık yeni varlık oranı `r` | ❌ AÇIK | koşulmadı |
| Y-37 | Disk + inode durumu | ⚠ **KISMEN** | `du`/dosya sayısı ölçüldü [Ö3]; `df -i` (inode) ölçülmedi |
| Y-38 | On-the-fly kapsam oranı (nginx access log) | ❌ AÇIK | koşulmadı. 03-perf §5 nginx **başlıklarını** ölçtü — farklı kalem |
| Y-39 | `upload-ui` iki kopyada — ölü kod tespiti | ❌ AÇIK | koşulmadı |

**Özet:** ✅ 10 · ⚠ 8 · ❌ 21 (Y-37'yi kısmi saydım; Y-24 tam).

### 7.3 GERÇEKTEN üretim/altyapı erişimi gerektirenler (19 kalem) — **DEĞİŞMEDİ**

Rev. 1'in P-1…P-19 listesi **aynen geçerlidir**. Bu dalgada **hiçbiri**
koşulamadı; üretim erişimi yoktu.

| P# | Kalem | Öncelik | Rev. 2 notu |
|---|---|---|---|
| **P-1** | Üretim imajında ffmpeg/ffprobe (AS-03, K-3) | **EN YÜKSEK** | yerelde VAR (backend + queue-long, 08 §3); üretim açık |
| **P-2** | Üretimde Pillow sürümü ve kodek matrisi | **YÜKSEK** | yerel konteyner **12.2.0** [08]; fixture üretimi yerel **11.3.0** ile yapıldı — sürüm asimetrisi kayıt altında (05-fixture §8.1) |
| P-3 | Üretimdeki Frappe/ERPNext/Python yamaları | Orta | — |
| P-4 | Üretim worker/gunicorn sayısı, kuyruk derinliği | **YÜKSEK** | yerelde `queue-long` ×1; transcode job timeout 1800 sn > worker varsayılan 1500 sn |
| P-5 | Üretim mimarisi (amd64 / arm64) | Orta | yerel **arm64, 11 vCPU** (05-kutuphane §1) — benchmark sayıları üretime taşınamaz |
| P-6 | `telephony` app'inin üretim commit'i | Düşük | — |
| P-7 | Üretimde `max_file_size` | **YÜKSEK** | — |
| P-8 | Press nginx `client_max_body_size` | Orta | — |
| P-9 | Üretimdeki gerçek medya hacmi | **YÜKSEK** | yerel taban artık kesin (§7.1 D-3) — karşılaştırma yapılabilir |
| **P-10** | Prod nginx sertleştirmesi eksik mi (AS-26) | **YÜKSEK (güvenlik)** | ⚠ **yerelde `limit_req` + `noindex` VAR** (03-perf §5.1) — fark prod imajında |
| **P-11** | Private dizin web'e açık mı | **EN YÜKSEK (güvenlik)** | koşulmadı |
| P-12 | Üretimde D-1/D-2 tekrarı (KVKK) | **EN YÜKSEK** | ⚠ **artık zorunlu**: yerelde D-2 = 44 bulgu verdi |
| P-13 | Lighthouse gerçek üretim alan adında | Orta | yerel trace ölçüldü; Lighthouse hiç koşulmadı |
| P-14 | LCP / CLS / LCP elementinin kimliği | Orta | ⚠ **yerelde ölçüldü** (03-perf §2.3); prod açık |
| P-15 | Toplam görsel byte'ı / sayfa | Orta | ⚠ **yerelde ölçüldü**: ürün detay **13,14 MB** (hedefin **15,0×**'i) |
| P-16 | CDN cache isabet oranı | Düşük | CDN yok |
| P-17 | Gerçek DPR dağılımı | Orta | CrUX verisi yok (`istoc.localhost` yerel ad) |
| P-18 | Aylık egress `E_gb` + istek `N_get` | Orta | — |
| P-19 | `media.access_denied` hacmi; DocShare paylaşımı | Düşük | — |

### 7.4 `00-ortam-envanteri` tarafından ZATEN cevaplanmış olanlar

Değişmedi. Ek olarak Dalga 3'te **pyvips/libvips** kalemi güncellendi:

| Kalem | `00-ortam` cevabı | **Rev. 2** |
|---|---|---|
| libvips / pyvips | **İKİSİ DE YOK** (§3) | `pyvips 3.1.1` + `libvips 8.14.1` **kuruldu** [Ö3] — ama **kalıcı değil** (§1.2) |
| Pillow kodek matrisi (yerel) | 12.2.0; WEBP ✅ AVIF ✅ JPEG-turbo ✅ TIFF ✅ LCMS2 ✅; **HEIF ❌** | değişmedi |
| ffmpeg/ffprobe (yerel) | VAR | ✅ doğrulandı, queue-long'da da VAR (08 §3) |
| Obje depolama / S3 / CDN | **YOK** | değişmedi |

---

## 8. BELGE KAYMASI — `MEDYA-DEPOLAMA-STANDARDI.md`'nin 2.858 / 192 sayısı

`08-canli-olcum.md` §1 şu uyarıyı basmıştı:

> *"⚠ Belge kayması. `MEDYA-DEPOLAMA-STANDARDI.md` 'public 2.858 / private 192'
> diyor. Ölçülen: 4.350 / 608. Belge yazıldığından bu yana public %52, private
> %217 büyümüş."*

**Bu uyarı YANLIŞTIR ve bu bölüm onu düzeltir.**

### 8.1 Ölçüm ne diyor

| Küme | public | private | Belgenin sayısına uzaklık |
|---|---:|---:|---|
| `tabFile` **satır** | 4.350 | 608 | +%52 / +%217 ← 08'in karşılaştırdığı küme |
| Diskteki **dosya** | 4.016 | 325 | +%40 / +%69 |
| **Eşsiz `file_url`** | **2.853** | **160** | **−%0,2** / −%17 |
| `MEDYA-DEPOLAMA-STANDARDI.md:31-32` | 2.858 | 192 | — |

**Public tarafta 2.858 ↔ 2.853: 4 günde 5 dosya fark.** Bu bir "büyüme"
değil, **aynı kümenin aynı sayısıdır**.

### 8.2 Destekleyici kanıt — belge yazıldığı gün disk zaten ~4.000'di

| Kod yorumu | Tarih | Sayı | Kapsam |
|---|---|---:|---|
| `media/gates.py:8` | 2026-08-06 | 4.007 | dosya |
| `media/backup.py:7` | 2026-08-13 | 4.195 | dosya (public+private kökleri) |
| `media/upload_policy.py:45` | **2026-08-14** | **4.003 public dosya** | dosya |
| `MEDYA-DEPOLAMA-STANDARDI.md` | **2026-08-14** | **2.858** | *"public/files → 2.858 dosya"* |

**Aynı gün, aynı depoda, iki farklı sayı: 4.003 ve 2.858.** İkisi de doğruysa
ikisi **farklı şey sayıyor** demektir. Ölçülen üçüncü küme (eşsiz `file_url` =
2.853) belgenin sayısına oturuyor; disk sayısı (4.016) `upload_policy.py`'ye
oturuyor.

**Sonuç:** belgenin **sayısı** doğru, **etiketi** yanlış. `public/files → 2.858
dosya` değil, `public/files → 2.858 eşsiz adres`. Hacim tarafı da bunu
doğruluyor: `06 §0`'ın "~1 GB"ı, eşsiz URL bayt toplamı **998,7 MB** [Ö3] ile
%0,3 içinde.

⚠ **Private tarafı bu kadar temiz değil:** belge 192, eşsiz URL 160, disk 325,
satır 608. 192 hiçbirine tam oturmuyor. **AS-04'ün private yarısı AÇIK kalıyor.**

### 8.3 Etkilenen türetmeler — TAM LİSTE

Belgeye dayanan her sayı gözden geçirildi:

| # | Etkilenen yer | Ne diyordu | **Rev. 2 hükmü** |
|---|---|---|---|
| 1 | `06-depolama §0` — taban `2.858 + 192 = 3.050` | varlık tabanı | ✅ **GEÇERLİ.** Ölçülen eşsiz URL toplamı **3.015** — %1,1 sapma |
| 2 | `06-depolama §3.3` — Senaryo A/B dosya ve GB projeksiyonları | 168.622 / 145.758 dosya; 11,32 / 5,15 GB | ✅ **GEÇERLİ.** Rev. 1'in "+%41 / +%40 düzelt" talimatı **GERİ ALINDI** |
| 3 | `06-depolama §6` — yedek job'u tarama çarpanı ~48× | oran | ✅ **GEÇERLİ** (zaten tabandan bağımsızdı). ⚠ Ama **1.334 yetim dosya** [Ö3] bu tarama kümesine dâhil — çarpan değil, **taban** büyüyor |
| 4 | `06-depolama §7.1/§7.3` — "S3 gerekmiyor, 12 ay ertele", %28 doluluk | karar | ✅ **GEÇERLİ** |
| 5 | `06-depolama §4.2` — %37 doluluk | iç tutarsızlık | ❌ hâlâ yanlış (Ç-13, K-16) |
| 6 | `02-medya §2.1 K1` + `§3 T-2` — "KÜME A ~2,8k / KÜME B ~4,0k, hiçbirine dayanılamaz" | çelişki | ✅ **ÇÖZÜLDÜ.** İkisi de doğru, farklı kümeler (§2 Ç-2) |
| 7 | **`07-faz0-kapanis` Rev. 1 §2 Ç-2 düzeltme tablosu** | "+%41 / +%40 düzelt" | ❌ **ÇÜRÜTÜLDÜ — bu belgede geri alındı** |
| 8 | `08-canli-olcum §1` — "belge kayması" uyarısı | "public %52 büyümüş" | ❌ **YANLIŞ — düzeltilmeli** |
| 9 | `08-canli-olcum §1` — "Toplam disk 1.559,5 MB" | etiket | ❌ **YANLIŞ etiket** (Ç-14): satır bazlı, mükerrer sayımlı. Gerçek disk **1.109 MB** [Ö3] |
| 10 | `MEDYA-DEPOLAMA-STANDARDI §2` — "düz dizin ölçek riski" argümanı | 2.858 dosya tek dizinde | ⚠ **RİSK OLDUĞUNDAN BÜYÜK.** Gerçek dizin içeriği **4.016 dosya** [Ö3] — argüman %40 **eksik** kurulmuş |
| 11 | `MEDYA-DEPOLAMA-STANDARDI §7` — retro-rename kapsamı: "2.166 eski isim, ~2.400 referans (`primary_image` 1.241 + `Listing Image.image` 1.137)" | migration boyutu | ⚠ **BÜYÜMÜŞ.** 09 §4.1 aynı iki alan için **1.312** ve **1.350 eşsiz dosya** ölçtü. Doğrudan karşılaştırma kesin değil (biri *referans*, öbürü *eşsiz dosya* sayıyor) ama **kapsam küçülmemiş** |
| 12 | `07 Rev. 1 §3.1` — `listing.primary_image` 1.241 / `listing.gallery_image` 1.137 "referans, dosya değil" uyarısı | veri kalitesi | ✅ **ÇÖZÜLDÜ.** 09 §4.1 artık **eşsiz dosya** sayıyor: 1.312 / 1.350 |

### 8.4 Yapılacaklar (belge düzeyi)

| # | Dosya | Düzeltme |
|---|---|---|
| B-1 | `docs/MEDYA-DEPOLAMA-STANDARDI.md:31-32` | Etiketi düzelt: `2.858 dosya` → `2.858 eşsiz adres (dedup'lu); dizindeki fiziksel dosya ~4.000` |
| B-2 | `docs/reports/08-canli-olcum.md §1` | "Belge kayması" uyarısını kaldır/düzelt; "Toplam disk 1.559,5 MB" → "referans bazlı toplam bayt 1.559,5 MB (eşsiz: 998,7 MB, disk: 1.109 MB)" |
| B-3 | `docs/reports/06-depolama-maliyet.md` | Rev. 1'in önerdiği +%40 düzeltmeyi **uygulama**; §4.2'deki %37'yi %28'e çek |
| B-4 | Yeni: taban tanımı | "varlık = eşsiz `file_url`" kararı tek bir yerde yazılsın (K-5 çıktısı) |


---

## 9. Faz 0 ARTIK KAPANABİLİR Mİ? — dürüst cevap

### 9.1 Kısa cevap

> **HAYIR — ama gerekçe tamamen değişti ve kalan iş küçüldü.**
>
> Rev. 1'de kapanamama nedeni **üretilmemiş görevlerdi** (T-006, T-007) ve
> **hiç ölçüm yapılmamış olmasıydı**. İkisi de bitti.
>
> Rev. 2'de kapanamama nedeni **dört somut kalemdir**: biri güvenlik bulgusu
> (D-2 = 44), biri hiç yapılmamış temizlik (K-2), biri üretim erişimi (K-3),
> biri versiyonlama (G-2). **Hiçbiri "daha çok analiz" istemiyor** — üçü
> mekanik iş, biri karar.

### 9.2 Kapanma ölçütü tek tek

| Ölçüt | Rev. 1 | **Rev. 2** | Kanıt |
|---|---|---|---|
| **Tüm Faz 0 görevleri üretildi mi?** | ❌ 9'un 7'si | ✅ **10'un 10'u** | §1.1, §1.2 [Ö3] |
| T-006 golden fixture korpusu | ❌ yok | ✅ **51 fixture, 51/51 doğrulandı** | [Ö3] `ls`; `manifest.json` |
| T-007 kütüphane benchmark'ı | ❌ yok | ✅ **360 koşum, 0 hata, karar üretildi** | `fixtures/bench.csv` |
| **K-1 — KVKK (AS-01 + AS-02)** | ❌ koşulmadı | ❌ **koşuldu: D-1 temiz (0), D-2 BULGU (44)** | [Ö3] §7.1 |
| **K-2 — bozuk komutlar düzeltildi ve betik koşuldu mu?** | ❌ hayır | ❌ **HAYIR** — `istocc` 9 kez, `tradehub.localhost` 5 kez duruyor | [Ö3] `grep -c` |
| **K-3 — üretim imajında ffmpeg** | ❌ ölçülmedi | ❌ **ölçülmedi** (üretim erişimi yok) | — |
| **K-4 — 39 kalem koşuldu mu?** | ❌ 0/39 | ⚠ **10 tam + 8 kısmi / 39** | §7.2 |
| **K-4 — 6 raporun metni düzeltildi mi?** | ❌ | ❌ **hiçbiri** | [Ö3] |
| **G-2 — çıktılar versiyonlandı mı?** | ❌ | ❌ **hayır, 14 girdi `untracked`** | [Ö3] `git status` |
| Faz 1'in girdisi (taban dosya sayısı) sabitlendi mi? | ❌ | ✅ **yerel dev için evet** (3.015 eşsiz varlık) | [Ö3] §7.1 D-3 |
| Faz 2'nin profil matrisi üretilebilir mi? | ❌ hayır | ❌ **hâlâ hayır** — Ç-9 + Ç-15 + AS-18 | §2 |

### 9.3 Kapanmak için kalan TAM liste

**Bloklayıcı (bunlar olmadan Faz 0 kapanmaz):**

| # | Kalan iş | Tür | Tahmini büyüklük |
|---|---|---|---|
| 1 | **D-2'nin 44 dosyasını sınıflandır**: hangisi gerçekten hassas içerik, hangisi satıcının aynı görseli iki yere yüklemesi. Hassas çıkan varsa erişim seviyesi düzeltilir | karar + elle inceleme | 44 dosya, yarım gün |
| 2 | **K-2: `istocc` / `tradehub.localhost` düzelt, `media_stats.py`'yi ÇALIŞTIR** | mekanik | 9 + 5 dize, 1 saat |
| 3 | **K-3 / P-1 / P-12: üretimde ffmpeg + D-1/D-2 tekrarı** | üretim erişimi | erişim açılınca 1 saat |
| 4 | **G-2: 12 rapor + korpus + `bench.csv` + betikleri commit et** | mekanik | 1 saat |

**Bloklayıcı değil ama Faz 1 başlamadan çözülmesi gereken (karar kalemleri):**

| # | Kalan iş | Neden |
|---|---|---|
| 5 | **K-23 / AS-29:** iki politika setinden biri kaynak-doğru ilan edilsin | T-028 migration'ı bunsuz yazılamaz (Ç-15) |
| 6 | **K-25 / Ç-18:** kod çözmeden önce megapiksel kapısı | 95 KB dosya bugün 100 MP açtırıyor |
| 7 | **K-24 / Ç-16:** SRS FR-019 düzeltilsin | bugünkü hâliyle logo stoğunun %76,5'i reddedilir |
| 8 | **K-9 / Ç-9:** master tavanı ↔ profil matrisi kararı | artık sayılı (%88,2 / %97,3) |

**Ertelenebilir (kayda geçti):** K-6, K-7, K-8, K-12…K-22 ve §7.2'nin açık 21
kalemi. Bunlar Faz 0'ın kapanmasını **engellemez**; Faz 1 içinde koşulabilir.

### 9.4 Bu dalganın dürüstlük karnesi

| İddia | Kanıt var mı |
|---|---|
| "T-006 yapıldı" | ✅ 51 dosya diskte [Ö3], manifest 51/51 GEÇTİ, `live-probe.json` motor koşum çıktısı |
| "T-007 yapıldı" | ✅ `fixtures/bench.csv` 360 satır, 0 hata; pyvips 3.1.1 konteynerde [Ö3] |
| "Canlı ölçüm yapıldı" | ✅ 08, 09, 03-performans raporları; bu oturumda D-1/D-2/D-23/D-3 bağımsız olarak tekrarlandı [Ö3] |
| "K-1 kapandı" | ❌ **HAYIR** — D-2 bulgu döndürdü |
| "K-2 kapandı" | ❌ **HAYIR** — dosyalar hâlâ bozuk [Ö3] |
| "39 kalemin tamamı koşuldu" | ❌ **HAYIR** — 10 tam, 8 kısmi, 21 açık |
| "Faz 0 tamamlandı" | ❌ **HAYIR** — §9.3'teki 4 bloklayıcı duruyor |
| "06-depolama'nın sayıları %40 yanlıştı" (Rev. 1) | ❌ **ÇÜRÜTÜLDÜ** — ölçüm tersini söylüyor (§8) |
| "Üretim doğrulandı" | ❌ **HAYIR** — üretim erişimi bu dalgada da yoktu; 19 P kaleminin **hiçbiri** koşulmadı |

---

## 10. ONAY

Bu rapor Faz 0'ın kapanış denetiminin **ikinci revizyonudur**. Aşağıdaki imza,
raporun okunduğunu ve §9.3'teki kalan kalemlerin karara bağlandığını belgeler.
**İmza, Faz 0'ın "tamamlandığı" anlamına gelmez.**

### 10.1 Dört bloklayıcının GÜNCEL durumu

| # | Bloklayıcı | Ölçülen durum (2026-08-18) | Karar | Tarih | Sorumlu |
|---|---|---|---|---|---|
| **K-1** | KVKK: AS-01 + AS-02 | **D-1 = 0 (temiz)** · **D-2 = 44 (BULGU)** [Ö3] | ☐ 44 dosya sınıflandırıldı, hassas yok → kapat  ☐ Hassas bulundu → **erişim düzeltmesi + Faz 1 durur**  ☐ Sınıflandırma yapılmadı | ________ | ________ |
| **K-2** | `media_stats.py` + `02-medya` komutları | **YAPILMADI** — `istocc` 9, `tradehub.localhost` 5 kez [Ö3] | ☐ Düzeltildi ve koşuldu  ☐ Hayır | ________ | ________ |
| **K-3** | Üretim imajında ffmpeg (AS-03) | **ÖLÇÜLMEDİ** (üretim erişimi yok) | ☐ Var  ☐ **Yok** → video hattı riski kabul edildi  ☐ Ölçülmedi | ________ | ________ |
| **K-4** | "Docker kapalı" gerekçesi + 39 kalem | Ölçüm: **10 tam + 8 kısmi / 39**. Metin düzeltmesi: **0 rapor** [Ö3] | ☐ Tamamı  ☐ Kısmen (**18 / 39**)  ☐ Hayır | ________ | ________ |

### 10.2 Dalga 3'ün eklediği üç yeni karar kalemi

| # | Kalem | Karar | Tarih | Sorumlu |
|---|---|---|---|---|
| **K-23** | AS-29 — hangi politika seti kaynak-doğru? | ☐ `media_engine/policy/slots`  ☐ `docs/standards/policies`  ☐ Birleştirilecek  ☐ Karar verilmedi | ________ | ________ |
| **K-24** | Ç-16 — SRS FR-019 (logo alfa zorunluluğu) | ☐ SRS düzeltilecek (alfa opsiyonel)  ☐ Politika geri alınacak  ☐ Karar verilmedi | ________ | ________ |
| **K-25** | Ç-18 — kod çözme öncesi megapiksel kapısı + `max_megapixels_hard` eşiği | ☐ Kapı eklenecek, eşik ____ MP  ☐ Ertelendi (risk kabul edildi)  ☐ Karar verilmedi | ________ | ________ |

### 10.3 T-006 / T-007 devir onayı

| # | Kalem | Durum | Onay |
|---|---|---|---|
| K-10 | T-006 golden fixture korpusu | ✅ üretildi (51 fixture) · ⚠ gerçek fotoğraf yok → `content_rules` kalibre edilemiyor (AS-27) | ☐ Kabul  ☐ Gerçek fotoğraf korpusu şart → iş açılsın |
| K-11 | T-007 kütüphane benchmark'ı | ✅ ölçüldü · karar: **Pillow'da kal + `draft()` ekle** · pyvips kurulumu **kalıcı değil** (AS-28) | ☐ "Ölçüldü, ertelendi" olarak KAPAT  ☐ `libvips42` üretim imajına eklensin  ☐ Karar verilmedi |

### 10.4 Faz 1'e geçiş kararı

☐ **ONAYLANDI** — §9.3'ün 4 bloklayıcısı karara bağlandı, Faz 1 başlayabilir.

☐ **KOŞULLU ONAY** — koşullar:

```
_________________________________________________________________________

_________________________________________________________________________
```

☐ **REDDEDİLDİ** — gerekçe:

```
_________________________________________________________________________
```

### 10.5 Platform yöneticisi onayı

| | |
|---|---|
| **Ad, soyad** | ______________________________________________ |
| **Rol** | ______________________________________________ |
| **Tarih** | ______________________________________________ |
| **İmza** | ______________________________________________ |

### 10.6 Bilgilendirilenler

| Rol | Ad | Tarih | İlgili kalemler |
|---|---|---|---|
| Backend sorumlusu | ________________ | __________ | **K-25** (megapiksel kapısı), K-11 (`draft()`), K-9, K-12 |
| Frontend sorumlusu | ________________ | __________ | AS-13 (`srcset`), K-13, K-15; 03-perf §4.4 (`<img src="#">`) |
| KVKK / veri sorumlusu | ________________ | __________ | **K-1 (D-2 = 44 dosya)**, AS-32, AS-14/D-23, AS-27 |
| Altyapı / DevOps | ________________ | __________ | K-3/P-1, P-10, P-11, AS-28, **G-2 (versiyonlama)** |
| Ürün / veri sahibi | ________________ | __________ | **K-23** (politika seti), AS-30 (719 harici URL), 09 §8 (T-028 girdileri) |

---

## 11. Kaynaklar

### Bu belgenin okuduğu 12 rapor

**Dalga 1–2 (7 rapor):**
- `docs/reports/00-ortam-envanteri.md` (774 satır)
- `docs/reports/00-upload-slot-envanteri.md` (551)
- `docs/reports/01-dosya-akisi.md` (554)
- `docs/reports/02-medya-istatistigi.md` (939)
- `docs/reports/03-render-envanteri.md` (567)
- `docs/reports/04-yetki-modeli.md` (817)
- `docs/reports/06-depolama-maliyet.md` (782)

**Dalga 3 (5 rapor):**
- `docs/reports/08-canli-olcum.md` (215) — canlı `tabFile` ölçümü, logo, video, PII
- `docs/reports/09-slot-bazinda-istatistik.md` (412) — slot bazında politika uyumu
- `docs/reports/03-performans-taban-cizgisi.md` (413) — LCP/CLS taban çizgisi
- `docs/reports/05-fixture-korpusu.md` (450) — T-006 golden fixture korpusu
- `docs/reports/05-kutuphane-benchmark.md` (591) — T-007 Pillow/pyvips/ffmpeg

### Bu oturumda ölçülen çalışma alanı çıktıları [Ö3]

- `tests/fixtures/media/images/` (34), `tests/fixtures/media/video/` (7), `tests/fixtures/malicious/` (10)
- `tests/fixtures/media/manifest.json`, `tests/fixtures/media/live-probe.json`
- `fixtures/bench.csv` (360 satır)
- `scripts/media_stats.py`, `docs/reports/02-medya-istatistigi.md` — bozuk sabitlerin sayımı
- `git status --short` — 14 `untracked` girdi

### Bu oturumda konteynerde koşulan salt-okuma ölçümleri [Ö3]

`istoc-dev-backend-1`, site `istoc.localhost`, `../env/bin/python`:

- D-1: `Seller Application.identity_document` / `Seller Certification.document` public taraması
- D-2: hassas `content_hash` paylaşan public dosya sayımı + karşı taraf kırılımı + disk varlık kontrolü
- D-23: `presets.EXCLUDED_DOCTYPES` ↔ `presets.EXCLUDED_MEDIA_FIELDS` karşılaştırması
- D-3/D-4/D-5: `tabFile` satır / eşsiz `file_url` / disk dosya sayımı, üç ayrı bayt toplamı, yetim dosya taraması
- `pyvips` sürüm doğrulaması

### Salt okunan kaynak dosyalar (değiştirilmedi — kural 1)

- `tradehub_core/media/presets.py`, `engine.py`, `upload_policy.py`, `chunked.py`, `usage.py`
- `docs/MEDYA-DEPOLAMA-STANDARDI.md`
- `media_engine/policy/slots/*.json`, `docs/standards/policies/*.json`

### İlgili mevcut belgeler

`docs/MEDYA-YUKLEME-SOZLESMESI.md` (TUR-123) · `docs/MEDYA-DEPOLAMA-STANDARDI.md`
(TUR-130) · `docs/MEDYA-ERISIM-MODELI.md` (TUR-126) · `docs/MEDYA-TARIH-STANDARDI.md` ·
`docs/srs/SRS-v1.0.md` · `docs/plans/migration.md`

**KAYIP:** `GORSEL-OPTIMIZASYON.md` — kodda 8 dosyadan atıf var, çalışma
alanında yok (AS-07).

### Bu görevde YAZILAN tek dosya

`/Users/ahmet/Desktop/istoc-medya-wt/docs/reports/07-faz0-kapanis.md` — bu belge (Rev. 2).
`tradehub_core/` altında hiçbir dosya değiştirilmedi.
