# 91 — W8: Görüntü hattı idempotency (T-064) + T-124/T-004 kapanış denemesi

**Tarih:** 2026-08-20 · **Görev:** önce ölç, sonra yap.
**Kurallar gereği:** commit yok, hooks/patches yok, panel bileşenine dokunulmadı, tüm-korpus backfill yok.

> Bu rapordaki her sayı gerçekten koşturuldu. Ölçülemeyen kalemler `ÖLÇÜLEMEDİ`
> olarak işaretlendi ve nedeni yazıldı. Lighthouse sayıları **makine-paylaşımlı
> ortamda** üretildi (14 Docker servisi ayakta) — LCP mutlak eşik kararı için
> sessiz makinede tekrarlanmalı; **CLS bit-kararlıdır** ve yükten etkilenmez.

---

## Yönetici özeti

| Kalem | Sonuç |
|---|---|
| **T-064 idempotency** | İddia **kısmen doğruydu**: normal ikinci koşum zaten 0 encode (DB kapısı). Ama **yetim disk senaryosunda** (DB satırları yok, dosyalar diskte) 48 encode'un 48'i yeniden yapılıyordu — W6-B'nin videoda bulduğu desenin görüntü karşılığı. Mevcut-türev atlaması eklendi: aynı senaryo şimdi **0 encode** ve kayıtlar disk gerçeklerinden geri açılıyor. |
| **T-124/T-004** | products.html sayfa-1 görsellerinin **1/50'si** türevliydi → hedefli backfill (39 dosya, 122,5 sn, 396 türev) → **40/50** (ilk görsellerin 38/38'i). Manifest + srcset + HTTP teslimi curl ile doğrulandı. Lighthouse önce/sonra aşağıda — **soğuk yüklemede vitrin ızgarası manifesti beklemeden ham `<img>` bastığı için** products.html LCP'si değişmedi (yapısal bulgu §2.5). |
| **categories.html CLS 0,5396** | Kök neden ÖLÇÜLDÜ: tek `<footer>` düğümü — kısa yükleme iskeletinin altında ilk ekranda boyanıyor, grid gelince 3.590 px itiliyor. Kaynakta tek satırlık yükseklik rezervasyonu (`min-h-[75vh]`) yapıldı ve DOĞRULANDI: **CLS 0,5396 → 0,0001**, perf skoru 0,77 → 0,99 (§3.3). |
| **Panel preload (T-122 kalanı)** | **AÇILMADI.** Gerekçe ölçüme dayalı analiz (§4): panelde preload'un kazanç üretebileceği bir yol gösterilemedi; "ölçülemedi, açılmadı". |

Regresyon: `test_pipeline_bridge` **25/25** (22 mevcut + 3 yeni), `test_render` **73/73**, `test_render_regression` **32/32** (1 bilinçli skip) — hepsi OK.

---

## 1. T-064 — idempotency gerçek mi? ÖNCE ÖLÇÜLDÜ

### 1.1 Ölçüm düzeneği

Sentetik 1200×1200 JPEG, `Listing.primary_image`'a bağlı `File`; `render.encode`
sayaçla sarıldı; `_run_rendition_job` doğrudan (senkron) koşuldu. Düzenek geçici
`tradehub_core/_w8_probe.py` modülüyle konteynerde koştu (iş bitince silindi);
aynı ölçüm artık kalıcı testte: `tests/test_pipeline_bridge.py::TestMevcutTurevAtlama`.

### 1.2 Sayılar (düzeltme ÖNCESİ)

| Senaryo | encode çağrısı | Media Rendition |
|---|---:|---:|
| Koşum 1 (taze üretim) | **48** | 10 yazıldı, 10'u diskte |
| Koşum 2 (normal — kayıtlar duruyor) | **0** ✅ | 10 (değişmedi) |
| Senaryo B: satırlar silindi, dosyalar diskte | **48** ❌ | 10 (yeniden kodlanarak) |

**Okunuşu:** "aynı dosya ikinci kez işlenince sayılar aynı" iddiası normal yol
için doğru — `_renditions_exist` DB kapısı işi hiç açmıyor, yeniden kodlama YOK.
Açık, **DB'ye bakan korumanın DB'siz kaldığı** her durumda (yetim disk dosyaları,
DB geri yüklemesi, satır silinmesi): türev adresleri deterministik (INV-09,
`version_hash` taşıyan adres) olduğu hâlde motor diskteki hazır çıktıyı görmeden
48 encode'u baştan yapıyordu. Bu, W6-B'nin videoda bulduğu "yol-determinizmi var
ama her koşum yeniden kodluyor" bulgusunun görüntüdeki karşılığıdır. (Not:
`pipeline/image/reprocess.py` T-064 defteri tam bu koruma için yazılmış ama
`pipeline_bridge` üretim yoluna hiç bağlanmamış — köprü kendi DB kapısını
kullanıyor.)

### 1.3 Yapılan (yalnız atlama kontrolü EK'i — `media/pipeline_bridge.py`)

- `_generate`: sürüm dizini (`/files/media/{asset}/{version_hash}/`) diskte
  DURUYORSA kaynağın hazırlanmış boyutu bir kez çözülür; durmuyorsa hiçbir ek
  maliyet yok (sıcak yol bedava).
- `_skip_from_disk` (yeni): beklenen çıktı genişliği **encode'suz** hesaplanır —
  `render.plan_geometry` saf aritmetik ve üretim yolunun kullandığı fonksiyonun
  kendisi. Beklenen adresteki dosya için "bayt tutuyor" iki kademede sorulur:
  `Media Rendition` satırı varsa `bytes` disk boyutuyla karşılaştırılır; satır
  yoksa dosyanın gerçekten açıldığı doğrulanır (`render._verify`, üretim
  yolundaki decode kapısının aynısı). Tutmayan/açılmayan dosya atlanmaz,
  yeniden üretilir.
- `_render_one`: dosya diskte + doğrulandı → **encode ATLANIR**; satır yoksa
  künye disk gerçeklerinden geri açılır (`quality`/`ssim` diskten okunamaz →
  0 yazılır, sayı uydurulmaz). Ek olarak D-1 mükerrer kapısı encode'dan ÖNCE
  sorulur: planlanan (genişlik, biçim) bu koşuda zaten üretildiyse render hiç
  başlamaz — bu satır olmadan mükerrer basamaklar (1200px kaynakta w1280/w1920)
  senaryo B'de 8 artık encode bırakıyordu.
- Kontrol best-effort: kendisi patlarsa üretim yolu değişmeden koşar (yanlış
  atlama yok, yalnız kaçan atlama olur).

### 1.4 Sayılar (düzeltme SONRASI)

| Senaryo | encode çağrısı | Media Rendition |
|---|---:|---:|
| Koşum 1 | 48 (değişmedi — taze üretim) | 10 |
| Koşum 2 (normal) | **0** | 10 |
| Senaryo B (yetim disk) | **0** ✅ (48→8→0: 8'i D-1 ön-kapısı kapattı) | 10 — disk gerçeklerinden geri açıldı, bayt/ölçü ilk üretimle birebir |

Ölçüm kriteri görev tanımındaki gibi **encode çağrısı SAYISI**, süre değil.

### 1.5 Yeni regresyon testleri

`tests/test_pipeline_bridge.py::TestMevcutTurevAtlama` (3 test):
1. `test_ikinci_kosum_hic_encode_yapmaz` — normal yol 0 encode.
2. `test_yetim_disk_dosyalari_encodesuz_kayda_baglanir` — satırlar silinip
   dosyalar dururken 0 encode + kayıtlar bayt/ölçü birebir geri.
3. `test_bozuk_disk_dosyasi_atlanmaz_yeniden_uretilir` — açılamayan dosya
   körlemesine atlanmaz; deterministik bayt diske ve kayda geri yazılır.

Toplam: `test_pipeline_bridge` 25 OK · `test_render` 73 OK · `test_render_regression` 32 OK (1 skip).

> ⚠️ **Kalıcılık:** Değişiklik host repo'da + `docker cp` ile backend, queue-long,
> queue-short, scheduler konteynerlerine kopyalandı. Uygulama imaja gömülü —
> kalıcılık için imaj rebuild gerekir; uzun ömürlü RQ worker süreçleri modülü
> önceden yüklediyse `docker compose restart queue-long queue-short` gerekir.

### 1.6 Bilinçli sınır

`_renditions_exist` iş-seviyesi kapısı DEĞİŞTİRİLMEDİ: asset'in TEK bir türevi
bile varsa iş hiç açılmıyor. Yarım kalmış bir üretimin (10 basamağın 5'i yazılıp
çökmüş) eksikleri bu kapı yüzünden hâlâ tamamlanmaz — atlama kontrolü sayesinde
artık tamamlamanın maliyeti ~0 olduğu için kapının gevşetilmesi ayrı, güvenli bir
iş kalemi olarak öneriliyor (bu görevde kapsam dışı: davranış değişikliği olurdu).

---

## 2. T-124/T-004 — products.html envanteri ve hedefli backfill

### 2.1 (a) Sayfanın bastığı görsellerin kaçı türevli — ÖLÇÜLDÜ

products.html sayfa 1 = `get_listings(page=1, page_size=40)` (sayfanın kendi
çağrısıyla aynı, `products.ts:372`). 40 kart, 38 tekil ilk-görsel (2 kart görselsiz
ya da mükerrer), toplam **50 tekil görsel**, ham toplam **17,69 MB**.

| Ölçüm | Backfill ÖNCESİ | Backfill SONRASI |
|---|---:|---:|
| Türevli görsel | **1 / 50** | **40 / 50** |
| İlk-görsel (LCP adayları) kapsaması | 1 / 38 | **38 / 38** |
| Kapsam dışı | 0 | 0 |

### 2.2 (b) Hedefli backfill — YALNIZ bu sayfanın görselleri, tavan 40

`_run_rendition_job(file_url)` sayfa-1 görselleri için senkron koşuldu (ilk
görseller öne alınarak, tavan 40 dosya; tüm-korpusa DOKUNULMADI — 3.152 dosyalık
korpusun kalanı olduğu gibi duruyor). Bayraklar zaten açıktı
(`media_pipeline_enabled=1`, `rendition_on_upload=1`, `active_slots=product.image,product.video`)
— bayrak değiştirilmedi.

**Sonuç:** 39 dosya işlendi, 1 atlandı (`zaten_turevli`), **396 Media Rendition**,
toplam süre **122,5 sn** (ort. 3,1 sn/dosya — 17-t028'in 10,45 sn tahmininden
hızlı çünkü bu setin çoğu küçük `kare-*.webp`). 10 görsel tavan dışında kaldı
(kartların 2.+ galeri görselleri; hepsi `loading="lazy"`).

**Backfill izleri (silinmedi, envanterde duruyor):**
- `Media Asset` 13 → **52**, `Media Rendition` 92 → **490** (488'i bu backfill + 2 eşzamanlı başka-ajan etkinliği), `Media Version` 11 → 50, `Media Processing Job` 11 → 50.
- Disk: `sites/istoc.localhost/public/files/media/` altında 39 yeni asset dizini
  (`/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{uzantı}` düzeninde).
- İşlenen 39 dosyanın tam listesi bu koşumun çıktısında; ilk beşi:
  `AV-172 AYARLI MENFEZ siyah.jpg` (2,5 sn/10 türev), `Adsız (1200 x 1200 piksel) (1).png`
  (3,6/10), `kare-c74ed2d5örn.jpg` (2,0/10), `Adsız (1200 x 1200 piksel)322c7c.png`
  (3,1/10 — ilk ölçümün LCP öğesi), `Adsız (1200 x 1200 piksel)6533ec.png` (3,1/10).

### 2.3 (c) Vitrin srcset'i gerçekten türev basıyor mu — curl ile doğrulandı

Misafir olarak `get_manifest_batch(["LST-00206","LST-04111","LST-04113"])`:
`enabled: true`, üç ilanda da manifest dolu, `sources` AVIF+WebP srcset'leri
`/files/media/{asset}/{version_hash}/…` adreslerini taşıyor. Srcset'teki adresler
gerçekten indi:

```
GET /files/media/7q7adqb52g/53a28a…/w384-384.avif → 200, 12.428 B, image/avif
GET /files/media/7q7adqb52g/53a28a…/w96-96.webp   → 200,  1.272 B, image/webp
```

(Karşılaştırma: aynı içeriğin ham kaynağı ~399 KB PNG.) Not: yanıt başlığı
`Cache-Control: public, max-age=300` — INV-09 adresleri `immutable` olabilirdi;
nginx sertleştirmesi hâlâ dev'e inmemiş (bilinen açık, rapor `istoc-sistem-tasarimi-denetimi`).

### 2.4 Lighthouse — AYNI yapılandırma, önce/sonra

`tradehubfront/lighthouserc.cjs` olduğu gibi `require` edildi (4 URL:
`/`, products, product-detail?id=LST-00202, categories; desktop preset, 3'er koşum,
`LHCI_LISTING_ID` varsayılanı LST-00202 — canlıda Active, sayfa 200). Çıktılar
repo dışına yazıldı (`upload.outputDir` geçici dizine yönlendirildi; kaynak
değişikliği yok). Önce-koşumu backfill'den önce bu oturumda yapıldı — rapor 62
ile aynı yönde sonuç verdi, yani karşılaştırma tabanı yeniden üretildi.

**ÖNCE** (bu oturum, backfill'den önce, eski storefront imajı) → **SONRA**
(backfill sonrası; storefront imajı bu arada başka bir ajan tarafından yeniden
inşa edildi — §5 ortam notu):

| Sayfa | LCP önce (medyan / 3 koşum) | LCP sonra | CLS önce | CLS sonra | Perf önce→sonra |
|---|---:|---:|---:|---:|---:|
| `/` | 1302 ms (1208/1302/1500) | 1477 ms (1406/1477/1485) | ~0 | ~0 | 0,96→0,95 |
| `products.html` | **6500 ms** (4796/6500/6510) | **6491 ms** (6450/6491/6623) | 0,0469 | 0,0469 | 0,74→0,74 |
| `product-detail?id=LST-00202` | 1391 ms | 1393 ms (5 koşum: 1392–1752) | 0,0076 | 0,0076 | 0,95→0,95 |
| `categories.html` | 861 ms | 865 ms | **0,5396** ❌ | **0,0001** ✅ | 0,77→**0,99** |

Rapor 62'deki ilk ölçümle karşılaştırma: products LCP 6352 → bu oturumda
6500/6491 (aynı mertebe — taban yeniden üretildi); product-detail bu kez GERÇEK
ürün sayfasını ölçüyor (LCP öğesi ürün görseli, boş-durum metni değil) ve 1,4 sn
ile bütçe içinde.

**products.html LCP niçin düşmedi — ağ kanıtı:** sonra-koşumunda da sayfa
**0 türev isteği** atıyor, 38 ham görsel / 7,2 MB indiriyor; LCP öğesi hâlâ ham
`Adsız (1200 x 1200 piksel)322c7c.png`. Türevler sunucuda hazır ve manifest
isteği 200 dönüyor — ama ızgara soğuk yüklemede manifesti KULLANMIYOR (§2.5).
Yani bu sayfanın LCP bütçesi backfill'le değil, ızgaranın soğuk-yükleme
davranışıyla kapanacak.

> Dürüstlük notu: sonra-koşumunda iki eşzamanlı lhci süreci kısmen çakıştı
> (kazara çift başlatma); categories 6, detail 5 koşum üretti. LCP yayılımları
> yine dar (products 6450–6623), CLS bit-kararlı — sonuçlar raporlanabilir, ama
> mutlak LCP eşiği kararı için sessiz makine şartı geçerli.

### 2.5 Yapısal bulgu — soğuk yüklemede ızgara manifesti beklemiyor

`ProductListingGrid.rerenderProductGrid` manifesti ateşle-ve-unut çağırıyor
(`void primeMediaManifests(...)`) ve önbellek SOĞUKKEN kartları bugünkü ham
`<img>` ile basıyor; manifest gelince yükseltme YOK — yükseltme ancak "sonraki
render"da (filtre/sayfa değişimi, geri gelme). Lighthouse her koşumda temiz
profille açtığı için products.html'in İLK yüklemesi türevleri hiç kullanamıyor;
`<picture>`/srcset ancak ikinci render'da devreye giriyor. product-detail'de bu
sorun çözülmüş (geç gelen manifest galeriyi yükseltiyor, F-2) — ızgarada yok.
**Yani backfill gerekli ama tek başına yeterli değil**: soğuk ilk boyada da
türev basılabilmesi için ızgaranın ya manifest sözünü kısa bir süre beklemesi
ya da geldiğinde yerinde yükseltmesi gerekiyor. Bu bir vitrin bileşeni
değişikliği — bu görevin sahipliği dışında, iş kalemi olarak bırakıldı.

---

## 3. categories.html CLS 0,5396 — kök neden ölçümü ve düzeltme

### 3.1 Kök neden — ÖLÇÜLDÜ (tek footer düğümü doğrulandı)

Bu oturumun önce-koşumunda üç koşumda da bit-aynı `CLS 0,5395542118893937`;
`layout-shifts` denetiminde tek büyük kayma:

| Kayma | Skor | Düğüm | Ayrıntı |
|---|---:|---|---|
| 1 | **0,5394** | `body > div#app > footer` | son konumu `top:3590` — grid verisi gelince 3.590 px aşağı itilmiş |
| 2 | 0,0001 | çerez bandı butonları | web font yüklenmesi |

Mekanizma: sayfanın tamamı (`appEl.innerHTML`) tek seferde basılıyor; ana içerik
o anda kısa bir yükleme iskeleti (`py-16` nabız kutusu, ~150 px), bu yüzden
`<footer>` İLK kadrajda boyanıyor. Kategori verisi gelince grid büyüyor ve
footer'ı ekran dışına itiyor → görünür öğenin dev kayması CLS'in %99,98'i.

### 3.2 Düzeltme — küçük, kaynakta yapıldı

`tradehubfront/src/pages/categories.ts` — grid kapsayıcısına tek sınıf:
`#cat-grid-container` → `min-h-[75vh]` (yükseklik rezervasyonu, gerekçe yorumda).
Footer artık ilk kadrajın altında başlıyor; hiç görünmeyen öğenin kayması CLS'e
yazılmaz. Grid yüklenince gerçek yükseklik zaten 75vh'den büyük — kalıcı görsel
maliyet yok. (Footer'ın kendisine `min-height` verilmedi: kayan şey footer'ın
İÇERİĞİ değil KONUMU; rezervasyonun doğru yeri iten içerik alanıdır.)

### 3.3 Doğrulama — ÖLÇÜLDÜ, kapandı

Düzeltme, başka bir ajanın bu oturum sırasında yaptığı storefront imaj
rebuild'iyle canlı dev ortamına girdi (kaynak ağacındaki değişiklik build'e
dahil oldu; `pages-categories-BuNvk_N2.js` içinde `min-h-[75vh]` doğrulandı).
Aynı yapılandırmayla sonra-koşumu:

| Ölçüm | Önce | Sonra (6 koşum) |
|---|---:|---:|
| CLS | 0,5395542118893937 (bit-aynı, 3 koşum) | **0,0001** (6 koşumda da) |
| `layout-shifts` en büyük kaynak | `<footer>` 0,5394 | web font kaymaları 0,0001 |
| Performans skoru | 0,77 | **0,99** |

Footer kayması tamamen kayboldu; kalan 0,0001 web font yüklemesinden geliyor
(çerez bandı butonları) ve bütçenin çok altında. `lighthouserc.cjs`'teki
`cumulative-layout-shift ≤ 0.1` bütçesi bu sayfada artık **geçiyor**.

---

## 4. Panel preload (T-122 kalanı) — KARAR: AÇILMADI

Mekanizma hazır ve testli (`admin-panel/frontend/src/composables/useLcpImagePreload.js`
+ `MediaImage.vue` `preload` prop'u), hiçbir ekran açmıyor; başlığı da dürüst:
"Kazanç ölçülmedi". İki bariz aday gerçek gerekçeyle değerlendirildi:

1. **`MediaPreviewModal` büyük görseli** — modal yalnız kullanıcı tıklamasıyla
   mount oluyor; `useLcpImagePreload` `setup()`ta koşar, yani preload bağlantısı
   ile `<img>` AYNI render akışında DOM'a girer — ağ isteği açısından öne geçiş
   sıfır. Üstelik modal görseli sayfa yükünün LCP adayı değil (etkileşim sonrası
   içerik) ve `MediaImage` orada zaten `priority` (fetchpriority=high) taşıyor.
   Preload'un işe yaraması için tıklamadan ÖNCE hangi varlığın açılacağını
   bilmek gerekirdi — bilinemez.
2. **Kütüphane ilk kartı** — kartlar `getList` yanıtı geldikten sonra render
   olur; preload bağlantısı da aynı senkron render'da basılırdı. Preload'un
   kazancı, `<head>`in `<img>`den ÖNCE parse edildiği durumlardan gelir
   (MPA/SSR); panel tamamen istemci-render bir SPA ve ilk yüklemenin LCP adayı
   login/dashboard metni — bir medya görseli değil.

**Ölçüm durumu: ÖLÇÜLEMEDİ.** Panelin gerçek LCP'si oturum açmış Lighthouse
koşumu ister (auth akışı otomasyonu bu görevin kapsamı ve sahipliği dışında);
jsdom'suz "basit" bir ölçüm LCP üretemez. Kazanç gösterilemediği için hiçbir
ekranda `preload` bayrağı açılmadı, panel bileşenlerine dokunulmadı. Mekanizma
zararsız şekilde beklemede; açılması gereken gün, adayın ölçülmüş olması şartına
bağlanmalı.

---

## 5. Ortam ve dürüstlük notları

- **Makine paylaşımlı:** Koşumlar sırasında 14 Docker servisi ayaktaydı ve
  depoda başka ajanların işleri vardı (`tradehubfront` çalışma ağacı kirli —
  ~40 dosya başkalarının WIP'i; `pipeline_bridge.py`'ye eşzamanlı olarak video
  önizleme üretimi eklendi, çakışma yok). Görev ortasında başka bir ajan
  backend (11:24) ve storefront (12:09) imajlarını yeniden inşa edip servisleri
  yeniden başlattı — ilk sonra-koşumu bu yüzden 502 ile düştü ve tekrarlandı.
  Yeniden inşa, kaynak ağacındaki categories düzeltmemi (ve başkalarının
  WIP'ini) canlı dev'e taşıdı; products/detay önce-sonra karşılaştırması bu
  yüzden yalnız backfill'i değil, frontend build farkını da içerir — products
  sonucunu yorumlarken ağ kanıtı (0 türev isteği) esas alınmalı. LCP sayıları mutlak eşik kararı için
  sessiz makinede tekrarlanmalı; CLS bit-kararlı.
- **Bayraklara dokunulmadı:** hat zaten açıktı (Dalga A medya entegrasyonunun
  bıraktığı durum); bu görev açık bayrağı veri olarak kullandı.
- **Değişen kaynak dosyalar:** `tradehub_core/tradehub_core/media/pipeline_bridge.py`
  (atlama kontrolü EK'i), `tradehub_core/tradehub_core/tests/test_pipeline_bridge.py`
  (3 yeni test), `tradehubfront/src/pages/categories.ts` (tek sınıflık yükseklik
  rezervasyonu). Commit atılmadı (kural).
- **Geçici araçlar temizlendi:** ölçüm modülü `tradehub_core/_w8_probe.py`
  konteynerden silindi; sentetik T-064 dosyaları ve türevleri ölçüm sonunda
  temizlendi (backfill izleri BİLEREK duruyor, §2.2).
- Ham Lighthouse raporları: `/tmp/w8-lhci-before/` ve `/tmp/w8-lhci-after/`
  (önce 12, sonra 17 rapor — çakışan çift koşum). Kalıcı olması istenirse `tradehubfront/perf-reports/lhci`
  altına taşınabilir.
