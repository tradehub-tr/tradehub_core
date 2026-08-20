# Depolama ve Maliyet Taban Çizgisi

**T-008** · Faz 0 · 2026-08-17 · branch `medya-motoru-faz0-faz2`

Bu rapor türev (rendition) patlaması riskini sayıyla gösterir. Hiçbir sayı
uydurulmadı: her rakamın yanında ya kaynak dosya:satır ya da hesap yöntemi yazılı.
Ölçüm gerektirip yapılamayan her şey **§8 ÜRETİMDE DOĞRULANMALI** altında,
çalıştırılacak komutla birlikte listelendi.

**Bir cümlelik sonuç:** Kaynak dokümanın "≈34 eager rendition/asset" rakamı
gerçekte **51** (eager) / **59** (eager+lazy) dosyadır — %55–%79 eksik sayılmış.
Bugünkü 2.858 public varlıkta "eager hepsi" senaryosu **~168.600 dosya / ~11,3 GB**
üretir; bu, bugünkü ~1 GB'lık medya gövdesinin **~11 katıdır** ve dosya sayısını
**55×** artırır. Bu ölçek yerel diski aşmaz (§7 karar), ama mevcut yedek
altyapısını (§6) kırar.

---

## 0. Hesabın girdileri — nereden geldiler

| Girdi | Değer | Kaynak |
|---|---|---|
| Public dosya sayısı | **2.858** | `docs/MEDYA-DEPOLAMA-STANDARDI.md:31` |
| Private dosya sayısı | **192** | `docs/MEDYA-DEPOLAMA-STANDARDI.md:32` |
| Ürün görseli referansı | **2.378** (1.241 `tabListing.primary_image` + 1.137 `tabListing Image.image`) | `docs/MEDYA-DEPOLAMA-STANDARDI.md:152-153` |
| Tahmin-edilebilir eski ad | **2.166** | `docs/MEDYA-DEPOLAMA-STANDARDI.md:150` |
| Bugünkü medya gövdesi (public+private files) | **~1 GB** | `tradehub_core/media/backup.py:362` — "14 gün ≈ 1 GB havuz". Havuz içerik-adresli olduğu için ilk snapshot tüm gövdeyi kopyalar ⇒ havuz ≈ gövde. |
| Günlük değişim | **~12 MB/gün** | `tradehub_core/media/backup.py:361` |
| Diskte boş alan | **382 GB** | `tradehub_core/media/backup.py:362` — kod yorumu, ölçüm tarihi belirtilmemiş; §8'de yeniden ölçülecek |
| Ortalama dosya boyutu (türetilmiş) | **~330 KB** | 1 GB ÷ (2.858+192) = 344 KB. Bağımsız ölçüm değil, yukarıdaki ikisinden türetildi. |
| Profil matrisi | 13 profil | Kaynak doküman `30-faz2-medya-standartlari.html`, profil tablosu (2026-08-17'de çekildi) |
| Depolama | Docker `sites` named volume, yerel disk | `/Users/ahmet/Desktop/istoc/docker/docker-compose.yml:265` (`volumes: sites:`), `:26` (`sites:/home/frappe/frappe-bench/sites`) |
| Nesne deposu | **YOK** | Aynı dosyada `s3\|minio\|object.storage\|boto\|cdn` grep'i **0 sonuç**. 14 servisin hiçbiri nesne deposu değil (`db, redis-cache, redis-queue, configurator, create-site, backend, websocket, scheduler, queue-short, queue-long, frappe-frontend, storefront, admin-panel, gateway`). |

**Hesabın yeniden üretimi:** bu raporun tüm sayıları
`scratchpad/turev_projeksiyon.py` ile üretildi; betiğin tamamı §9'da.

---

## 1. Türev sayısı projeksiyon formülü

### 1.1 Temel formül

```
dosya(varlık) = Σ            |genişlik(p)| × |format(p)|
                p ∈ profiller(varlık.sınıfı)
```

Bu formül **dedup varsaymaz**. Gerçek dosya sayısı, aynı çıktıyı üreten
profillerin tekilleştirilmesiyle düşer. Tekilleştirme anahtarı **üç bileşenlidir**:

```
kimlik = (en_boy_oranı, fit_modu, genişlik, format)
```

Genişlik tek başına anahtar **değildir** — kaynak dokümanın hatası tam olarak
budur (§1.3).

### 1.2 Profil matrisi ve profil başına dosya

Kaynak: `30-faz2-medya-standartlari.html` profil tablosu.

| Profil | Oran | Fit | Genişlikler | Formatlar | Dosya | Üretim |
|---|---|---|---|---|---:|---|
| `cart-thumb` | 1:1 | cover | 80, 120, 160 | AVIF, WebP, JPEG | **9** | eager |
| `similar-product` | 1:1 | cover | 160, 240, 320 | AVIF, WebP, JPEG | **9** | eager |
| `product-card` | 1:1 | cover | 240, 320, 480, 640 | AVIF, WebP, JPEG | **12** | eager |
| `product-list` | 4:3 | cover | 320, 480, 640, 800 | AVIF, WebP, JPEG | **12** | eager |
| `product-main` | 1:1 | contain | 480, 640, 800, 1024, 1280, 1600 | AVIF, WebP, JPEG | **18** | eager |
| `home-carousel` | 16:9 | cover | 640, 960, 1280, 1600, 1920 | AVIF, WebP, JPEG | **15** | eager |
| `hero-wide` | 21:9 | cover | 960, 1280, 1600, 1920 | AVIF, WebP, JPEG | **12** | eager |
| `company-cover` | 3:1 | cover | 768, 1280, 1920 | AVIF, WebP, JPEG | **9** | eager |
| `logo-square` | 1:1 | contain | 64, 128, 256 | WebP-lossless, PNG | **6** | eager |
| `avatar` | 1:1 | cover | 40, 80, 160 | WebP, JPEG | **6** | eager |
| `product-zoom` | source | contain | 2000, 2400 | WebP, JPEG | **4** | lazy |
| `product-modal` | source | contain | 1200, 1600, 2000 | AVIF, WebP, JPEG | **9** | lazy |
| `logo-wide` | — | — | BLOCKED | SVG passthrough | **0** | blocked |
| | | | | **eager toplam** | **108** | |
| | | | | **lazy toplam** | **13** | |

> 108 ve 13, **tüm profillerin** toplamıdır — tek bir varlık bunların hepsini
> almaz. Varlık sınıfı başına gerçek sayı §1.4'te.

### 1.3 Kaynak dokümanın "≈34" rakamı yanlış — %55 ila %79 eksik

Kaynak doküman **"Toplam eager rendition ≈ 34 dosya/asset"** diyor. Bu rakamın
nasıl çıktığını yeniden ürettim:

Ürün görseli profillerinin (`cart-thumb`, `similar-product`, `product-card`,
`product-list`, `product-main`) **genişlik birleşimi**:

```
{80, 120, 160, 240, 320, 480, 640, 800, 1024, 1280, 1600} → 11 ayrık genişlik
11 × 3 format = 33 ≈ 34   ✅ dokümanın sayısı böyle çıkıyor
```

**Hata:** aynı genişlik farklı **en-boy oranı** ya da farklı **fit modunda**
farklı bir görüntüdür ve ayrı bir dosyadır. Örnekler:

- `640` genişlik üç kez geçiyor ve **üçü de farklı dosya**:
  `product-card` (1:1, cover) / `product-list` (4:3, cover) / `product-main` (1:1, contain).
- `480`, `320`, `800`, `160`, `240` için de aynı çakışma var.

Doğru sayım:

| Sayım yöntemi | eager dosya/varlık | Dokümana göre |
|---|---:|---|
| Dokümanın sayımı (yalnız genişlik birleşimi × format) | **33** | temel |
| **(oran, fit, genişlik, format) ile tekilleştirilmiş — DOĞRU** | **51** | **+%55** |
| Hiç tekilleştirmeden, profil başına ham | **60** | **+%82** |
| + lazy profiller (zoom, modal), birlikte tekilleştirilmiş | **59** | **+%79** |

> "Hiç dedup yok" 60 iken "birlikte dedup" 59 çıkıyor: `product-main` 1:1/contain
> 1600 ile `product-modal` source/contain 1600 tek dosyaya iner (source oranı 1:1
> varsayımıyla). Tekilleştirmenin toplam kazancı ürün görselinde **yalnızca
> 73→59, yani %19'dur** — profiller birbirinden oran/fit ile ayrıştığı için
> beklenen kadar tasarruf yok.

**Bu raporun geri kalanı 51 (eager) ve 59 (eager+lazy) rakamlarını kullanır,
dokümanın 34'ünü değil.**

### 1.4 Varlık sınıfı başına dosya (tekilleştirilmiş)

| Varlık sınıfı | Uygulanan profiller | Dosya/varlık |
|---|---|---:|
| Ürün görseli | cart-thumb, similar-product, product-card, product-list, product-main, product-zoom, product-modal | **59** |
| Vitrin/banner | home-carousel, hero-wide | **27** |
| Firma kapağı | company-cover | **9** |
| Mağaza logosu | logo-square | **6** |
| Avatar | avatar | **6** |

Sınıf ataması `tradehub_core/media/usage.py:32-41` (`LIVE_SOURCES`) ve
`browse.py:48-52` (`_LISTING_IMAGE_SOURCES`) alan haritalarından çıkarıldı:

- `tabListing.primary_image`, `tabListing Image.image`,
  `tabListing Variant Item.variant_image`, `variant_gallery`,
  `tabSeller Gallery Image.image` → **ürün görseli**
- `tabAdmin Seller Profile.logo` → **logo**
- `tabStorefront Layout.sections` → **vitrin/banner**

### 1.5 Bugünkü varlık sayısıyla sonuç

Ürün görseli profilini iki farklı taban üzerinden uyguluyorum, çünkü sınıf
dağılımı **ölçülemedi** (§8.1):

| Taban | Kaynak | eager dosya | eager+lazy dosya |
|---|---|---:|---:|
| 2.378 ürün görseli referansı | `MEDYA-DEPOLAMA-STANDARDI.md:152-153` | **121.278** | **140.302** |
| 2.858 public dosya (üst sınır) | `MEDYA-DEPOLAMA-STANDARDI.md:31` | **145.758** | **168.622** |

> Alt taban (2.378) **referans** sayısıdır, dosya değil; birden çok listing aynı
> dosyayı gösterirse gerçek varlık sayısı bunun altındadır. Üst taban (2.858)
> logo/avatar/döküman gibi ürün görseli olmayanları da ürün gibi sayar. Gerçek
> değer bu ikisinin arasındadır. Kesin sayı için §8.1.

**Bugünkü 3.050 dosya → ~121.000–169.000 dosya. Çarpan: ~40×–55×.**

Shard etkisi: `MEDYA-DEPOLAMA-STANDARDI.md:98` 256 hash-prefix shard tanımlıyor
ve türevler `<hash>_*` deseniyle **aynı shard'da** duruyor (`:131`). Yani
168.622 ÷ 256 = **~659 dosya/shard** — shard tasarımı bu ölçeği rahat taşıyor.
Shard **sorun değil**; dosya sayısının kendisi ve onu tarayan işler sorun (§6).

---

## 2. "Eager hepsi" vs "lazy + on-the-fly" — dosya ve disk

### 2.1 Boyut varsayımı — VARSAYIMDIR, ÖLÇÜLMEDİ

Türev boyutunu **bytes-per-pixel (bpp)** ile modelliyorum:

```
bayt(profil, genişlik) = genişlik × (genişlik × oran) × bpp(format)
```

**⚠️ Aşağıdaki bpp değerleri VARSAYIMDIR. Ölçülmediler.** Fotoğrafik ürün
görseli için literatürde makul kabul edilen aralıklardır; İstoç'un gerçek
görselleriyle (beyaz fon oranı, doku yoğunluğu) doğrulanmadı. Doğrulama komutu §8.2.

| Format | alt bpp | orta bpp | üst bpp | Not |
|---|---:|---:|---:|---|
| AVIF | 0,030 | 0,045 | 0,060 | VARSAYIM |
| WebP (lossy) | 0,050 | 0,075 | 0,100 | VARSAYIM. Mevcut kod q80 kullanıyor (`media/engine.py:148`) |
| JPEG (progressive) | 0,080 | 0,110 | 0,150 | VARSAYIM. Mevcut kod q88 kullanıyor (`media/presets.py:15`) |
| WebP-lossless | 0,150 | 0,250 | 0,400 | VARSAYIM, düz renkli logo |
| PNG | 0,200 | 0,350 | 0,550 | VARSAYIM, düz renkli logo |

**Varsayımın makuliyet kontrolü (bağımsız):** `presets.py:15` varsayılan preset
2000px/q88. Orta JPEG bpp ile 2000×2000×0,110 = **~440 KB**. §0'daki türetilmiş
ortalama dosya boyutu **~344 KB**. Aynı büyüklük mertebesinde, hatta model biraz
muhafazakâr (yüksek) tarafta. Varsayım tutarlı.

### 2.2 Tek ürün görseli — dosya ve bayt

Tüm satırlar `(oran, fit, genişlik, format)` ile **birlikte** tekilleştirilmiştir
— "lazy ek" satırı, eager kümesiyle çakışmayan (yani gerçekten ek disk yazan)
varyantlardır.

| Küme | Dosya | alt | **orta** | üst |
|---|---:|---:|---:|---:|
| eager (5 profil) | 51 | 1,28 MB | **1,84 MB** | 2,49 MB |
| lazy (zoom + modal), ham | 11 | 1,93 MB | **2,77 MB** | 3,74 MB |
| lazy **ek** (eager'la çakışmayan) | 8 | 1,54 MB | **2,21 MB** | 2,98 MB |
| **hepsi (eager + lazy ek)** | **59** | 2,83 MB | **4,05 MB** | 5,47 MB |

**Buradaki tek en önemli bulgu:** lazy profillerin eklediği dosyalar toplam
dosya sayısının yalnızca **%14'ü** (8/59) ama toplam baytın **%55'i**
(2,21 / 4,05 MB). Sebebi `product-zoom` (2000, 2400 px) ve `product-modal`
(2000 px) — piksel maliyeti genişliğin karesiyle büyüyor. `product-zoom`'un tek
başına 2400 px WebP+JPEG çifti, `cart-thumb`+`similar-product`+`product-card`'ın
30 dosyasının toplamından büyüktür.

> **Doküman zaten doğru karar vermiş:** kaynak matriste `product-zoom` ve
> `product-modal` `lazy` işaretli. Bu raporun katkısı, o kararın **neden**
> pazarlık konusu olmadığını sayıyla göstermek: eager'a çekilirlerse disk
> **2,2× artar** (1,84 → 4,05 MB/varlık) ve bunun karşılığında yalnızca 8 dosya
> daha önden hazır olur.

### 2.3 Senaryo karşılaştırması — bugünkü varlıkla

Ortadaki bpp ile; köşeli parantez alt–üst bpp aralığı.

**Taban: 2.378 ürün görseli referansı**

| Senaryo | Dosya | Disk (orta) | Disk aralığı |
|---|---:|---:|---|
| **A — Eager hepsi** (zoom/modal dahil önden üretim) | **140.302** | **9,41 GB** | 6,57 – 12,70 GB |
| **B — Eager only** (doküman kararı; zoom/modal lazy) | **121.278** | **4,28 GB** | 2,98 – 5,77 GB |
| **C — Lazy + on-the-fly**, %15 kapsam | 21.045 | 1,41 GB | — |
| **C — Lazy + on-the-fly**, %30 kapsam | 42.090 | 2,82 GB | — |

**Taban: 2.858 public dosya (üst sınır)**

| Senaryo | Dosya | Disk (orta) | Disk aralığı |
|---|---:|---:|---|
| **A — Eager hepsi** | **168.622** | **11,32 GB** | 7,89 – 15,26 GB |
| **B — Eager only** | **145.758** | **5,15 GB** | 3,58 – 6,94 GB |
| **C — Lazy + OTF**, %15 kapsam | 25.293 | 1,70 GB | — |
| **C — Lazy + OTF**, %30 kapsam | 50.586 | 3,39 GB | — |

**Senaryo C'nin "kapsam" parametresi de VARSAYIMDIR.** On-the-fly'da diske
yalnızca gerçekten istenen varyantlar düşer. %15 ve %30, uzun-kuyruklu
katalogda "varyantların ne kadarına gerçekten dokunulur" için seçilmiş iki
örnek değerdir; ölçüm değildir. Gerçek değer ancak canlıda erişim log'undan
çıkar (§8.3).

### 2.4 Fark, tek satırda

Taban 2.858:

```
A (eager hepsi)  →  168.622 dosya /  11,32 GB
B (doküman)      →  145.758 dosya /   5,15 GB   →  A'ya göre -%14 dosya, -%55 disk
C (lazy+OTF %30) →   50.586 dosya /   3,39 GB   →  A'ya göre -%70 dosya, -%70 disk
                                                    B'ye göre -%65 dosya, -%34 disk
```

**Yorum:** A → B geçişi **dosya sayısında az** (%14) ama **diskte çok** (%55)
kazandırıyor — büyük dosyaları erteliyor. B → C geçişi ise tersi: **dosya
sayısını 3'te bire indiriyor**, disk kazancı daha ılımlı (%34). İki kaldıraç
farklı kalemi çözüyor:

- **Disk baskısı varsa** → A yerine B (zoom/modal lazy) yeter.
- **Dosya sayısı baskısı varsa** (§6: yedek job'u her dosyayı SHA-256'lıyor) →
  B yetmez, C gerekir.

§3.3'e göre disk baskısı 12 ay içinde oluşmuyor; §6'ya göre dosya sayısı baskısı
**ilk gün** oluşuyor. Yani asıl kaldıraç C'dir — ama C'nin gerçek değeri
§8.3 ölçümü (kapsam oranı) yapılmadan bilinemez.

---

## 3. 12 aylık büyüme projeksiyonu

### 3.1 Formül

```
Varlık(12ay)  = V₀ + 12 × r
Dosya(12ay)   = Varlık(12ay) × d          d = 59 (eager+lazy) | 51 (eager) | 17,7 (OTF %30)
Disk(12ay)    = Varlık(12ay) × s          s = 4,05 MB | 1,84 MB | 1,22 MB   (orta bpp)
```

- `V₀ = 2.858` — ölçülü (`MEDYA-DEPOLAMA-STANDARDI.md:31`)
- **`r` (aylık yeni varlık) ÖLÇÜLMEDİ.** Aşağıdaki değerler **senaryo
  parametresidir, tahmin değildir.** Gerçek `r` için §8.4.

### 3.2 Senaryo tablosu

| r (varlık/ay) | 12. ay varlık | Eager+lazy dosya | GB | Eager only dosya | GB | Lazy+OTF %30 dosya | GB |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 200 | 5.258 | 310.222 | 20,8 | 268.158 | 9,5 | 93.066 | 6,2 |
| 500 | 8.858 | 522.622 | 35,1 | 451.758 | 16,0 | 156.786 | 10,5 |
| 1.000 | 14.858 | 876.622 | 58,8 | 757.758 | 26,8 | 262.986 | 17,6 |
| 2.000 | 26.858 | 1.584.622 | 106,3 | 1.369.758 | 48,4 | 475.386 | 31,9 |

Shard başına dosya (256 shard, eager+lazy):

| r | dosya/shard |
|---:|---:|
| 200 | 1.212 |
| 500 | 2.041 |
| 1.000 | 3.424 |
| 2.000 | 6.190 |

`MEDYA-DEPOLAMA-STANDARDI.md:99` "dizin başına ~birkaç bin dosya" hedefi
koymuş. r=2.000 senaryosunda 12. ayda **6.190/shard** ile bu hedefin üstüne
çıkılıyor — hâlâ ext4/xfs için sorunsuz, ama hedefin dışında. Not edildi.

### 3.3 Disk kapasitesi karşılaştırması

`backup.py:362` yorumuna göre diskte **382 GB boş** (tarih belirsiz, §8.5).

| r | 12-ay eager+lazy | 382 GB'ın yüzdesi | 12-ay eager only | % |
|---:|---:|---:|---:|---:|
| 200 | 20,8 GB | %5 | 9,5 GB | %2 |
| 500 | 35,1 GB | %9 | 16,0 GB | %4 |
| 1.000 | 58,8 GB | %15 | 26,8 GB | %7 |
| 2.000 | 106,3 GB | **%28** | 48,4 GB | %13 |

**En kötü senaryoda bile 12 ayda disk %28'i geçmiyor.** Bu, §7 kararının temel
dayanağıdır. Not: bu tablo yalnız türevleri sayar; §6'daki yedek havuzu ve
`image_originals` arşivi ayrıca yer kaplar — ama ikisi de türev **içermezse**
(§7.2 madde 4) bugünkü ~1 GB mertebesinde kalır.

---

## 4. 12 aylık maliyet karşılaştırması — formüller

**Hiçbir fiyat yazılmadı. Bilinmeyen fiyat uydurulmaz.** Aşağıdaki formüller
doldurulmaya hazırdır; fiyat alanlarına `[GÜNCEL FİYAT GİRİLECEK]` konuldu ve
her birinin hangi sayfadan alınacağı yazıldı.

### 4.1 Ortak değişkenler

| Değişken | Anlam | Bu raporun değeri |
|---|---|---|
| `S_gb` | 12. ay sonu depolanan veri (GB) | §3.2 tablosu |
| `N_dosya` | 12. ay sonu nesne sayısı | §3.2 tablosu |
| `N_put` | 12 ayda yazılan nesne (≈ `N_dosya`, yeniden üretim yoksa) | §3.2 |
| `N_get` | 12 ayda okuma isteği | **ÖLÇÜLMEDİ** — §8.6 |
| `E_gb` | 12 ayda dışa aktarılan trafik (GB) | **ÖLÇÜLMEDİ** — §8.6 |

> `N_get` ve `E_gb` olmadan S3+CDN maliyeti hesaplanamaz. Bunlar S3/CDN
> senaryosunun **baskın** kalemleridir; depolama ücreti değil. Bu iki sayı
> ölçülmeden "S3 şu kadar tutar" demek uydurmadır.

### 4.2 Senaryo 1 — Hetzner yerel disk (BUGÜNKÜ DURUM)

```
Yıllık_maliyet = 0
```

Ek disk gerekmiyorsa **marjinal maliyet sıfırdır**: veri zaten ödenmiş
sunucunun diskinde, `docker-compose.yml:265` `sites` named volume içinde.
§3.3'e göre 12 ayda en kötü senaryoda bile %37 doluluk ⇒ **ek disk satın alma
gerekmiyor.**

Eğer ek volume gerekirse:

```
Yıllık = 12 × ⌈S_gb⌉ × [GÜNCEL FİYAT GİRİLECEK: € / GB / ay — Hetzner Cloud Volume]
```
> Fiyat kaynağı: https://www.hetzner.com/cloud → "Volumes" bölümü
> (ya da https://docs.hetzner.com/cloud/volumes/overview)

**Gizli maliyet (sıfır değil):** yerel diskte **yedek** ve **tarama** maliyeti
var — §6.

### 4.3 Senaryo 2 — Hetzner Object Storage (S3 uyumlu)

```
Depolama_aşım_gb = max(0, S_gb − [GÜNCEL FİYAT GİRİLECEK: plana dahil GB])
Trafik_aşım_gb   = max(0, E_gb − [GÜNCEL FİYAT GİRİLECEK: plana dahil trafik GB])

Yıllık = 12 × [GÜNCEL FİYAT GİRİLECEK: temel plan € / ay]
       + 12 × Depolama_aşım_gb × [GÜNCEL FİYAT GİRİLECEK: € / GB / ay aşım]
       +      Trafik_aşım_gb   × [GÜNCEL FİYAT GİRİLECEK: € / GB aşım]
```
> Fiyat kaynağı: https://www.hetzner.com/storage/object-storage/
> Kontrol edilecekler: (a) plana dahil depolama ve trafik kotası,
> (b) aşım birim fiyatları, (c) **istek (request) ücreti alınıyor mu** —
> alınmıyorsa `N_put`/`N_get` maliyete girmez ve bu senaryonun en büyük avantajı budur.

**Not:** `N_put` = ~146.000–177.000 nesne (§2.3). İstek ücretsizse ilk migrasyon
bedava; ücretliyse `N_put × birim` kalemi eklenmeli.

### 4.4 Senaryo 3 — AWS S3 + CloudFront

```
S3_depolama   = 12 × S_gb × [GÜNCEL FİYAT GİRİLECEK: $ / GB / ay — S3 Standard, eu-central-1]
S3_put        = (N_put / 1000)  × [GÜNCEL FİYAT GİRİLECEK: $ / 1.000 PUT]
S3_get        = (N_get / 1000)  × [GÜNCEL FİYAT GİRİLECEK: $ / 1.000 GET]
CF_egress     = E_gb            × [GÜNCEL FİYAT GİRİLECEK: $ / GB — Europe tier]
CF_istek      = (N_get / 10000) × [GÜNCEL FİYAT GİRİLECEK: $ / 10.000 HTTPS isteği]
S3→CF_origin  = 0   (CloudFront'a origin transfer ücretsizdir — doğrula)

Yıllık = S3_depolama + S3_put + S3_get + CF_egress + CF_istek
```
> Fiyat kaynakları:
> - S3: https://aws.amazon.com/s3/pricing/ (bölge: `eu-central-1` Frankfurt)
> - CloudFront: https://aws.amazon.com/cloudfront/pricing/ (Europe fiyat kademesi)
> - Origin transfer muafiyeti: CloudFront fiyat sayfası "Data transfer out to origin" notu

**Bu senaryonun tuzağı:** `S_gb` küçük (≤80 GB) olduğu için **depolama kalemi
önemsizdir**; fatura `CF_egress` ve `CF_istek` ile belirlenir — yani trafiğe
bağlıdır, veri boyutuna değil. §8.6 ölçülmeden bu senaryo değerlendirilemez.

### 4.5 Karşılaştırmaya değer 4. seçenek — Cloudflare R2 (+ Cloudflare CDN)

Görev metninde istenmedi ama bu iş yükünün profiline (çok sayıda küçük dosya,
yüksek okuma, düşük yazma) doğrudan uyduğu için formülü de bırakıyorum:

```
Yıllık = 12 × max(0, S_gb − [dahil GB]) × [GÜNCEL FİYAT GİRİLECEK: $ / GB / ay]
       + (N_put / 1e6) × [GÜNCEL FİYAT GİRİLECEK: $ / milyon Class A işlem]
       + (N_get / 1e6) × [GÜNCEL FİYAT GİRİLECEK: $ / milyon Class B işlem]
       + 0                        ← R2'de egress ücreti yoktur (doğrula)
```
> Fiyat kaynağı: https://developers.cloudflare.com/r2/pricing/
> Doğrulanacak tek kritik iddia: **egress ücretsiz mi hâlâ.** Öyleyse
> §4.4'ün baskın kalemi (`CF_egress`) sıfırlanır ve S3+CloudFront ile
> karşılaştırma anlamsız hâle gelir.

### 4.6 Formülleri doldurmak için gereken 3 sayı

Fiyat sayfalarına bakmadan önce bu üçü ölçülmeli, aksi hâlde tablolar boş kalır:

1. `r` — aylık yeni varlık (§8.4)
2. `E_gb` — aylık medya egress trafiği (§8.6)
3. `N_get` — aylık medya istek sayısı (§8.6)

---

## 5. Mevcut kodda ZATEN çözülmüş olanlar (yeniden tasarlanmayacak)

Bu bölüm, T-008'in "eksiği belgele, üstüne yazma" kuralı gereğidir.

| Konu | Durum | Kod |
|---|---|---|
| **Hash-prefix shard** | ✅ standartlaştırılmış (256 shard, `<ab>/<hash>`) | `MEDYA-DEPOLAMA-STANDARDI.md:89-104`, `media/naming.py:write_file_hashed` |
| **İçerik-adresli isim → doğal dedup** | ✅ aynı içerik = tek fiziksel dosya | `MEDYA-DEPOLAMA-STANDARDI.md:107-113` |
| **Türev konumu** | ✅ tanımlı: `<hash>_<suffix>.<ext>`, orijinalle aynı shard | `MEDYA-DEPOLAMA-STANDARDI.md:118-131` |
| **Kaynak görsel küçültme (2000px/q88)** | ✅ ölçümle seçilmiş, uygulanıyor | `media/presets.py:13-19`, `media/engine.py:96-145` |
| **Sunucu tarafı garanti-WebP** | ✅ Safari/Capacitor fallback'i sunucuda tamamlanıyor | `media/engine.py:148-181` (`to_webp`, 1920px tavan, q80) |
| **Orijinal arşivi + 30 gün geri alma** | ✅ `private/image_originals/`, File kaydı üretmez | `media/presets.py:35-38`, `media/archive.py` |
| **Soft-delete + 30 gün retention** | ✅ `private/media_trash/` | `media/trash.py:30-31` |
| **İçerik-adresli medya yedeği** | ✅ `private/media-backups/blobs/<xx>/` + manifest, 14 set | `media/backup.py:47-48, 357` |
| **Yükleme boyut tavanları** | ✅ görsel 25 MB, video 200 MB, doküman 50 MB | `media/upload_policy.py:67-72` |
| **Video rendition** | ✅ tek rendition (`scale='min(1280,iw)'`, crf 32) | `media/transcode.py:242-245` |

### 5.1 Eksik olan tek şey: görsel türev üretimi

`tradehub_core/media/` içinde `srcset|rendition|_thumb|variant boyut` grep'i
**türev üreten hiçbir kod bulmuyor**. Mevcut olan:

- `engine.optimize()` — kaynağı **yerinde** küçültür, formatı **korur**, **tek**
  çıktı üretir (`engine.py:8-9`: "Format KORUNUR ... `file_url` sabit kalır").
- `engine.to_webp()` — **tek** WebP üretir, 1920px tavan.

Yani bugün varlık başına **1 dosya** var; hedef matris **59** istiyor. Bu
raporun konusu olan patlama tam olarak bu boşluktur. `MEDYA-DEPOLAMA-STANDARDI.md:133`
zaten bunu kabul ediyor: *"Türevlerin üretimi ve yaşam döngüsü TUR-297 / TUR-128
işidir. Bu belge yalnız KONUMU tanımlar."*

---

## 6. Türev patlamasının kodda kıracağı yer — yedek altyapısı

Bu, disk fiyatından daha acil bir sonuçtur ve raporun asıl uyarısıdır.

`media/backup.py` her snapshot'ta:

1. `_media_dirs()` (`backup.py:127-138`) → `public/files` **ve** `private/files`
   köklerini tam yürür.
2. `_scan()` (`backup.py:148`) → bulduğu **her dosyanın SHA-256'sını** hesaplar
   (`file_hash`, `backup.py:140-146`, dosyayı baştan sona okur).
3. Yeni blob'ları `shutil.copy2` ile havuza kopyalar (`backup.py:219`).
4. `prune(keep=14)` (`backup.py:357`) 14 set tutar.

Bugünkü ölçek (`backup.py:361-362` yorumu): **3.050 dosya, ~1 GB havuz,
~12 MB/gün değişim.**

Senaryo B'den sonraki ölçek:

| Metrik | Bugün | Senaryo B (2.858 taban) | Çarpan |
|---|---:|---:|---:|
| Taranan dosya | 3.050 | 145.758 | **48×** |
| Snapshot başına SHA-256 | 3.050 | 145.758 | **48×** |
| SHA-256'lanan bayt | ~1 GB | ~6,2 GB (1 GB kaynak + 5,15 GB türev) | **6×** |
| Manifest kaydı (14 set) | ~42.700 | ~2.040.600 | **48×** |

**Somut sonuç:** günlük yedek job'u (`run_scheduled`, `backup.py:388`) her
çalışmada 145.758 dosyayı açıp hash'leyecek. Türevler **deterministik olarak
yeniden üretilebilir** olduğu için bunların yedeklenmesi **gereksizdir** —
kaynak dosya + profil matrisi yedeklendiğinde türev geri kurulabilir.

**Bu rapordan çıkan somut, kodsuz öneri:** türev üretimi devreye alınmadan
**önce** `backup.py:_media_dirs()` / `_scan()` türev desenini (`<hash>_*`)
dışlamalı. Aksi hâlde yedek altyapısı ilk gün 48× yüklenir. *(Bu rapor kod
değiştirmez; bulguyu kaydeder — uygulanacak görev ayrı açılmalı.)*

Aynı mantık `media/inventory.py` ve `media/usage.py` için de geçerli: türevler
`File` kaydı üretirse envanter ve kota sayıları 48× şişer. Karşılaştırma noktası
`presets.py:34-35`: arşiv klasörü için **tam olarak bu sebeple** "File kaydı
YARATILMAZ — envanteri ve kotayı şişirmesin" kararı verilmiş. Türevler için de
aynı karar gerekir; şu an yazılı değil.

---

## 7. Karar önerisi

### 7.1 Bu ölçekte S3'e geçmek gerekli mi — **HAYIR**

Gerekçeler, sayıyla:

1. **Hacim küçük.** 12 ayda en kötü senaryoda (r=2.000, eager+lazy) **106,3 GB**.
   Diskte 382 GB boş (`backup.py:362`) ⇒ **%28 doluluk**. Doküman kararına
   (eager only) sadık kalınırsa **48,4 GB / %13**. Nesne deposu, disk dolduğu
   için değil, disk **dolmayacağı** için gerekmiyor.

2. **Nesne deposunun asıl faydası burada yok.** S3'ün kazandırdığı şey
   dayanıklılık + yatay ölçek + origin ayrıştırma. Ama İstoç tek makinede
   14 servisli tek compose ile çalışıyor (`docker-compose.yml`); uygulama
   katmanı yatay ölçeklenmiyor. Medyayı S3'e alıp geri kalanı tek makinede
   bırakmak, tek hata noktasını **kaldırmaz**, sadece bir ağ bağımlılığı **ekler**.

3. **Maliyet karşılaştırması yapılamaz durumda.** §4.6'daki üç sayı (`r`,
   `E_gb`, `N_get`) ölçülmemiş. S3+CDN faturasının baskın kalemi egress ve
   istek sayısıdır, depolama değil (§4.4). Ölçmeden geçmek, bilinmeyen bir
   faturaya imza atmaktır.

4. **Geçişin yolu zaten açık, aciliyeti yok.** `MEDYA-DEPOLAMA-STANDARDI.md:172`:
   *"CDN'e geçiş — yol yapısı (`/files/<ab>/<hash>`) CDN origin olarak temiz."*
   İçerik-adresli + sharded yollar S3 anahtarına birebir çevrilir. Yani S3'e
   geçiş kararı **ertelenebilir bir karardır** ve ertelemenin maliyeti yok.

### 7.2 Bunun yerine yapılması gerekenler — öncelik sırasıyla

| # | Karar | Gerekçe (sayı) |
|---|---|---|
| **1** | **Kaynak dokümandaki "≈34" düzeltilsin → 51 eager / 59 eager+lazy.** | §1.3: %55–%79 eksik sayım. Kapasite planı yanlış rakamla yapılmış. |
| **2** | **`product-zoom` ve `product-modal` kesinlikle lazy/on-the-fly kalsın.** | §2.2: ekledikleri dosya %14, ekledikleri bayt %55. Eager'a çekilirse disk **2,2×** artar (1,84 → 4,05 MB/varlık). |
| **3** | **Türevler `File` kaydı ÜRETMESİN.** | §6: 145.758 türev × `File` = envanter ve kota 48× şişer. `presets.py:34-35` arşiv için aynı kararı zaten vermiş — emsal var. |
| **4** | **`backup.py:_media_dirs()`/`_scan()` `<hash>_*` desenini dışlasın.** | §6: aksi hâlde günlük yedek job'u 48× dosya hash'ler. Türev yeniden üretilebilir, yedeklenmesi gereksiz. |
| **5** | **Türev üretimi ilk sürümde `eager only` (51 dosya) ile açılsın; C senaryosu (on-the-fly) ölçüm sonrası değerlendirilsin.** | §2.4: B→C geçişi diski %34, dosya sayısını %65 azaltıyor. Asıl kazanç dosya sayısında; gerçek değeri §8.3 ölçümü belirler. |
| **6** | **Nesne deposu kararı 12 ay ertelensin; tetikleyici eşikler yazılsın.** | Aşağıdaki tablo. |

### 7.3 S3/nesne deposu kararının tetikleyicileri

Bugün "hayır", ama süresiz değil. Şu **üç eşikten herhangi biri** aşılırsa karar
yeniden açılmalıdır:

| Tetikleyici | Eşik | Nasıl izlenir |
|---|---|---|
| Disk doluluğu | medya > **150 GB** (382 GB'ın %40'ı) | `du -sh` cron'u, §8.5 |
| Dosya sayısı | > **1.000.000** nesne | §3.2: 1.000.000 ÷ 59 = 16.949 varlık ⇒ `r ≈ 1.174`/ay'da 12. ayda aşılır |
| Egress | aylık > **1 TB** | §8.6 ölçümü; bu noktada CDN kararı S3'ten bağımsız olarak da gerekir |

> Dördüncü, sayısal olmayan tetikleyici: uygulama katmanı **çok makineye**
> dağıtılırsa yerel disk paylaşılamaz ve nesne deposu teknik zorunluluk olur.
> Bugünkü tek-compose kurulumunda (`docker-compose.yml`) böyle bir plan yok.

---

## 8. ÜRETİMDE DOĞRULANMALI

Aşağıdakiler bu raporda **ölçülmedi**. Docker kapalı, üretim veritabanına ve
canlı siteye erişim yok. Her madde, çalıştırılacak komutu içerir.

### 8.1 Varlık sınıfı dağılımı (§1.5'in taban belirsizliğini kapatır)

Ürün görseli / logo / avatar / banner kaç tane — §1.4 çarpanlarını doğru
uygulamak için şart.

```bash
docker compose -f docker/docker-compose.yml exec backend \
  bench --site istoc.localhost mariadb
```
```sql
SELECT 'listing_primary' k, COUNT(DISTINCT primary_image) n FROM `tabListing` WHERE primary_image IS NOT NULL AND primary_image != ''
UNION ALL SELECT 'listing_gallery', COUNT(DISTINCT image)          FROM `tabListing Image`           WHERE image IS NOT NULL AND image != ''
UNION ALL SELECT 'variant_image',   COUNT(DISTINCT variant_image)  FROM `tabListing Variant Item`    WHERE variant_image IS NOT NULL AND variant_image != ''
UNION ALL SELECT 'seller_gallery',  COUNT(DISTINCT image)          FROM `tabSeller Gallery Image`    WHERE image IS NOT NULL AND image != ''
UNION ALL SELECT 'seller_logo',     COUNT(DISTINCT logo)           FROM `tabAdmin Seller Profile`    WHERE logo IS NOT NULL AND logo != '';

-- Tekil dosya sayısı (aynı dosya birden çok yerde kullanılıyor olabilir):
SELECT COUNT(*) FROM `tabFile` WHERE is_private = 0 AND folder LIKE '%Home%';
```

### 8.2 Gerçek bpp — §2.1 varsayımının doğrulanması

Bu raporun tüm GB rakamları bu varsayıma dayanıyor. Doğrulanmadan sermaye
kararı verilmemeli.

```bash
# Rastgele 50 gerçek ürün görseli seç, her formatta her genişlikte üret, bpp ölç
docker compose -f docker/docker-compose.yml exec backend bash -lc '
cd /home/frappe/frappe-bench/sites/istoc.localhost/public/files
ls -1 | shuf -n 50 > /tmp/ornek.txt
python3 - <<'"'"'PY'"'"'
import io, os
from PIL import Image
GEN=[80,160,320,640,1024,1600,2400]
tot={}
for ad in open("/tmp/ornek.txt").read().split():
    try: im=Image.open(ad); im.load()
    except Exception: continue
    for w in GEN:
        if w>im.width: continue
        k=im.copy(); k.thumbnail((w,w))
        px=k.width*k.height
        for fmt,kw in (("WEBP",{"quality":80}),("JPEG",{"quality":88,"optimize":True,"progressive":True}),("AVIF",{"quality":50})):
            b=io.BytesIO()
            try: k.convert("RGB").save(b,fmt,**kw)
            except Exception: continue
            tot.setdefault(fmt,[0,0]); tot[fmt][0]+=len(b.getvalue()); tot[fmt][1]+=px
for f,(by,px) in tot.items():
    print(f"{f}: {by/px:.4f} bpp   (rapordaki varsayim: WEBP 0.075 / JPEG 0.110 / AVIF 0.045)")
PY'
```
> AVIF için `pillow-avif-plugin` gerekebilir; yoksa AVIF satırı düşer ve
> AVIF bpp varsayımı doğrulanmamış kalır — raporda öyle işaretlensin.

### 8.3 On-the-fly kapsam oranı (§2.3'ün %15/%30 varsayımı)

Hangi varyantlar gerçekten isteniyor:

```bash
# nginx access log'undan medya isteklerini varyant desenine göre say
docker compose -f docker/docker-compose.yml exec gateway \
  sh -c "awk '\$7 ~ /^\/files\// {print \$7}' /var/log/nginx/access.log" \
  | sed -E 's#.*/([0-9a-f]+)(_[0-9a-z]+)?\.[a-z]+#\2#' | sort | uniq -c | sort -rn | head -40
```
> `gateway.conf` şu an access log yazıyor mu doğrulanmalı; yazmıyorsa
> `log_format` + `access_log` eklenmeden bu ölçüm yapılamaz.

### 8.4 Aylık yeni varlık oranı `r` (§3.1'in tek bilinmeyeni)

```sql
SELECT DATE_FORMAT(creation,'%Y-%m') ay, COUNT(*) yeni_dosya, ROUND(SUM(file_size)/1048576,1) mb
FROM `tabFile`
WHERE is_private = 0 AND creation >= DATE_SUB(NOW(), INTERVAL 12 MONTH)
GROUP BY ay ORDER BY ay;
```
Son 3–6 ayın ortalaması `r` olarak §3.2 tablosunda kullanılacak.

### 8.5 Gerçek disk durumu (`backup.py:362`'deki "382 GB" tazelenmeli)

```bash
docker compose -f docker/docker-compose.yml exec backend bash -lc '
S=/home/frappe/frappe-bench/sites/istoc.localhost
df -h $S
du -sh $S/public/files $S/private/files $S/private/image_originals $S/private/media_trash $S/private/media-backups
find $S/public/files  -type f | wc -l
find $S/private/files -type f | wc -l
df -i $S | tail -1   # inode doluluğu — 1M+ dosya senaryosu icin kritik
'
```
> Son satır önemli: §3.2 r=2.000 senaryosu 1.584.622 dosya öngörüyor. ext4
> varsayılan inode oranıyla sorun beklenmiyor ama **doğrulanmadı**.

### 8.6 Egress ve istek sayısı (§4.4 / §4.6'nın baskın kalemleri)

```bash
# Aylık medya trafiği (byte) ve istek sayısı
docker compose -f docker/docker-compose.yml exec gateway \
  sh -c "awk '\$7 ~ /^\/files\// {n++; b+=\$10} END {print \"istek:\", n, \" GB:\", b/1073741824}' /var/log/nginx/access.log"
```
> `\$10` nginx `combined` formatında `body_bytes_sent` sütunudur; `gateway.conf`
> özel `log_format` kullanıyorsa sütun indeksi düzeltilmeli.

### 8.7 Fiyat alanlarının doldurulması (§4)

| Formül | Sayfa |
|---|---|
| §4.2 Hetzner Cloud Volume | https://www.hetzner.com/cloud → "Volumes" |
| §4.3 Hetzner Object Storage | https://www.hetzner.com/storage/object-storage/ |
| §4.4 AWS S3 (`eu-central-1`) | https://aws.amazon.com/s3/pricing/ |
| §4.4 CloudFront (Europe) | https://aws.amazon.com/cloudfront/pricing/ |
| §4.5 Cloudflare R2 | https://developers.cloudflare.com/r2/pricing/ |

### 8.8 Doğrulanmamış matris varsayımı

`product-zoom` ve `product-modal` profillerinin oranı kaynak matriste
**"source"** (kaynağın kendi oranı). §2'deki bayt hesabında **1:1 varsayıldı**.
Katalogdaki gerçek oran dağılımı ölçülürse (aşağıdaki sorgu) lazy bayt tahmini
düzeltilmeli:

```sql
SELECT ROUND(width/height,2) oran, COUNT(*) n
FROM `tabFile` WHERE is_private=0 AND width>0 AND height>0
GROUP BY oran ORDER BY n DESC LIMIT 20;
```
> `tabFile`'da `width`/`height` kolonları yoksa bu ölçüm diskteki dosyalardan
> Pillow ile yapılmalı (§8.2 betiğine `im.size` eklemek yeterli).

---

## 9. Hesabın yeniden üretimi

Bu raporun §1, §2, §3 tablolarını üreten betik. Kopyalanıp çalıştırılabilir;
girdiler değişirse (§8.1, §8.2, §8.4) sadece `PROFILLER`, `BPP` ve taban
varlık sayıları güncellenir.

```python
#!/usr/bin/env python3
# (ad, oran_h/w, genislikler, formatlar, uretim)
PROFILLER = [
    ("cart-thumb",      1/1,  [80,120,160],                    ["avif","webp","jpeg"], "eager"),
    ("similar-product", 1/1,  [160,240,320],                   ["avif","webp","jpeg"], "eager"),
    ("product-card",    1/1,  [240,320,480,640],               ["avif","webp","jpeg"], "eager"),
    ("product-list",    3/4,  [320,480,640,800],               ["avif","webp","jpeg"], "eager"),
    ("product-main",    1/1,  [480,640,800,1024,1280,1600],    ["avif","webp","jpeg"], "eager"),
    ("home-carousel",   9/16, [640,960,1280,1600,1920],        ["avif","webp","jpeg"], "eager"),
    ("hero-wide",       9/21, [960,1280,1600,1920],            ["avif","webp","jpeg"], "eager"),
    ("company-cover",   1/3,  [768,1280,1920],                 ["avif","webp","jpeg"], "eager"),
    ("logo-square",     1/1,  [64,128,256],                    ["webp_ll","png"],      "eager"),
    ("avatar",          1/1,  [40,80,160],                     ["webp","jpeg"],        "eager"),
    ("product-zoom",    1/1,  [2000,2400],                     ["webp","jpeg"],        "lazy"),
    ("product-modal",   1/1,  [1200,1600,2000],                ["avif","webp","jpeg"], "lazy"),
]
FIT = {"cart-thumb":"cover","similar-product":"cover","product-card":"cover",
       "product-list":"cover","product-main":"contain","product-zoom":"contain",
       "product-modal":"contain","home-carousel":"cover","hero-wide":"cover",
       "company-cover":"cover","logo-square":"contain","avatar":"cover"}
# VARSAYIM — §2.1, olculmedi
BPP = {"avif":(.030,.045,.060), "webp":(.050,.075,.100), "jpeg":(.080,.110,.150),
       "webp_ll":(.150,.250,.400), "png":(.200,.350,.550)}
URUN = ["cart-thumb","similar-product","product-card","product-list",
        "product-main","product-zoom","product-modal"]
P = {p[0]: p for p in PROFILLER}

# Tekillestirme anahtari: (oran, fit, genislik, format). Dosya sayisi VE bayt
# ayni kume uzerinden hesaplanir — aksi halde ikisi tutarsiz olur.
def keyset(adlar, uretim=None):
    s = set()
    for ad in adlar:
        _, oran, gen, fmt, u = P[ad]
        if uretim and u != uretim: continue
        for w in gen:
            for f in fmt: s.add((round(oran,4), FIT[ad], w, f))
    return s

def bayt(ks):
    t = [0,0,0]
    for (oran, fit, w, f) in ks:
        px = w * round(w*oran)
        for i in range(3): t[i] += px * BPP[f][i]
    return t

mb = lambda b: b/1048576
KE, KL, KA = keyset(URUN,"eager"), keyset(URUN,"lazy"), keyset(URUN)
KLo = KA - KE                                     # lazy'nin GERCEKTEN ekledigi
print("eager :", len(KE), [round(mb(x),2) for x in bayt(KE)])   # 51  1.28/1.84/2.49
print("lazy  :", len(KL), [round(mb(x),2) for x in bayt(KL)])   # 11  1.93/2.77/3.74
print("lazy ek:", len(KLo), [round(mb(x),2) for x in bayt(KLo)])#  8  1.54/2.21/2.98
print("HEPSI :", len(KA), [round(mb(x),2) for x in bayt(KA)])   # 59  2.83/4.05/5.47
ea, aa = bayt(KE), bayt(KA)
for V in (2378, 2858):
    print(f"V={V}: A eager+lazy {V*len(KA):>8,} dosya {mb(aa[1])*V/1024:6.2f} GB"
          f" | B eager {V*len(KE):>8,} dosya {mb(ea[1])*V/1024:6.2f} GB")
V0 = 2858
for r in (200, 500, 1000, 2000):                  # r = SENARYO parametresi, olcum degil (§8.4)
    V = V0 + 12*r
    print(f"r={r:>4} V12={V:>6,} | e+l {V*len(KA):>10,} / {mb(aa[1])*V/1024:6.1f} GB"
          f" | eager {V*len(KE):>10,} / {mb(ea[1])*V/1024:6.1f} GB"
          f" | shard {V*len(KA)/256:6,.0f}")
```

---

## 10. Özet tablo — kararı verecek kişi için

| Soru | Cevap | Dayanak |
|---|---|---|
| Dokümanın 34 rakamı doğru mu? | **Hayır. 51 (eager) / 59 (eager+lazy).** | §1.3 |
| Bugün kaç dosyaya çıkarız? | **~121.000–169.000** (bugün 3.050) | §1.5 |
| Bugün kaç GB? | **4,3–11,3 GB** (senaryoya göre) | §2.3 |
| 12 ay sonra? | **6,2 – 106,3 GB**, `r`'ye bağlı | §3.2 |
| Disk yeter mi? | **Evet.** En kötü senaryoda %28 doluluk. | §3.3 |
| S3'e geçelim mi? | **Hayır, 12 ay ertele.** Tetikleyiciler tanımlı. | §7.1, §7.3 |
| Asıl acil sorun ne? | **Yedek job'u 48× yüklenecek.** Türevler yedekten dışlanmalı. | §6 |
| Neyi ölçmeden karar veremeyiz? | **`r`, `E_gb`, `N_get`, gerçek bpp.** | §4.6, §8 |
