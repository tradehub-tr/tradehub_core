# 12 — Faz 12 Performans Kabul Raporu (T-124)

> **Kapsam:** T-120 `<picture>` üretimi · T-121 `sizes` türetimi · T-122 LCP
> planı · T-123 RUM şeması.
> **Bu rapor bir "başardık" belgesi DEĞİLDİR.** Aşağıdaki kabul ölçütlerinin
> bir kısmı **kanıtlandı**, bir kısmı **hesaplandı ama üretimde
> doğrulanmadı**, bir kısmı **kapatılamadı**. Üçü ayrı ayrı işaretlidir.
> **Tarih:** 2026-08-18 · **Taban çizgisi:** `03-performans-taban-cizgisi.md` §7

---

## 0. Üç seviyeli kabul durumu

| Seviye | Anlamı | Sayı |
|---|---|---:|
| ✅ **KANITLANDI** | Kod var, test var, test geçiyor; iddia yeniden üretilebilir | 6 |
| 🧮 **HESAPLANDI** | Gerçek dosyalar gerçek kodlayıcıyla ölçüldü, ama üretime uygulanmadı | 4 |
| ⛔ **KAPATILAMADI** | Ölçülemedi ya da depo sınırı (storefront salt okunur) engelledi | 5 |

---

## 1. Ölçülen taban çizgisi — değişmedi

Faz 12 "sonra" ölçümü henüz **yapılmadı**; bu sütun `03-performans-taban-cizgisi.md`
§7'den olduğu gibi taşınmıştır ve **bu rapor onu değiştirmemektedir**.

| Metrik | Ana sayfa | Ürün listeleme | **Ürün detay** | Mağaza |
|---|---:|---:|---:|---:|
| Toplam görsel baytı | 3.344.403 | 8.462.503 | **13.774.742** | 1.068.262 |
| `srcset` kullanan `<img>` | 0/22 | 0/51 | **0/31** | 0/26 |
| `sizes` | 0/22 | 0/51 | **0/31** | 0/26 |
| `<picture>` | 0/22 | 0/51 | **0/31** | 0/26 |
| `fetchpriority="high"` | 0 | 0 | **0** | 0 |
| LCP (mobil, Slow 4G, 4× CPU) | 776 ms | 1.062 ms | 919 ms | 740 ms |
| CLS (mobil) | 0,01 | **0,51** | 0,00 | 0,00 |

---

## 2. Kabul ölçütleri

### 2.1 ✅ KANITLANDI

| # | Ölçüt | Kanıt |
|---|---|---|
| K1 | Manifestten `<picture>` üretiliyor; AVIF → WebP → JPEG sırası korunuyor | `tests/test_delivery_picture.py::OlculenBosluk::test_bicim_sirasi_avif_once` |
| K2 | Her `<img>` `width` + `height` taşıyor; taşıyamıyorsa **üretim durur** | `BoyutVeCLS` (4 test) — `intrinsic_size()` `PictureError` atıyor |
| K3 | `priority=True` → `loading` yazılmıyor, `fetchpriority="high"`, `decoding="sync"` | `OncelikDavranisi` (4 test) |
| K4 | Karusel ilk slayt öncelikli, kalanı `lazy` | `test_karusel_ilk_slayt_eager_kalani_lazy` |
| K5 | `sizes` **71 ölçüm satırında** rapordaki elle hesapla uyuşuyor; açıklanmamış sapma **0** | `tests/test_delivery_sizes.py::RaporlaCaprazDogrulama` + `python3 -m media_engine.delivery.sizes` |
| K6 | RUM şeması PII geçirmiyor (20 yasak alan, serbest URL, ham UA, ham viewport) | `tests/test_delivery_rum.py::PiiKorumasi` (7 test) |

**Test kanıtı (tam koşu):**

```
cd /Users/ahmet/Desktop/istoc/tradehub_core
python3 -m unittest discover -s tests -p "test_*.py"
→ Ran 1376 tests in 103.961s
→ OK (skipped=70, expected failures=1)
```

Bu fazda eklenen: **72 test** (picture 24 · sizes 22 · rum 26). Var olan 1304
testin hiçbiri bozulmadı.

### 2.2 🧮 HESAPLANDI (üretimde doğrulanmadı)

| # | İddia | Ölçülen dayanak |
|---|---|---|
| H1 | Ürün detay 13.759.638 B → **61.466 B** (WebP, 390px telefon) = **224× azalma** | 12 gerçek PDP dosyası gerçek `render_ladder` ile kodlandı |
| H2 | 900 KB hedefi **12 kat marjla** karşılanıyor (61 KB / 921.600 B) | aynı |
| H3 | Merdivende `768 → 1280` boşluğu 390px telefonda %81 fazla bayt indiriyor; `w800` bunu **13.833 B → 7.954 B** yapar | `_olcum_faz12/olcum800.json` |
| H4 | AVIF bugün WebP'den **%2 BÜYÜK**; kalibre edilirse (q60) **%20 küçük** | `_olcum_faz12/avif_kalibre.json`, 12 dosya, SSIM referanslı |

> **Neden "kanıtlandı" değil:** türevler henüz üretilmedi, servis edilmedi,
> tarayıcıya indirilmedi. Bayt sayıları gerçek kodlayıcı çıktısıdır ama sayfanın
> gerçekten bu dosyaları indireceği ancak `srcset` üretimi storefront'a
> uygulandıktan sonra ölçülebilir.

### 2.3 ⛔ KAPATILAMADI

| # | Ölçüt | Engel |
|---|---|---|
| E1 | Faz 12 "sonra" LCP/CLS ölçümü | Türevler üretilip servis edilmedi; storefront salt okunur |
| E2 | Ana sayfa / listeleme / mağaza sayfalarının bayt hesabı | Dosya kümeleri çıkarılmadı — **ÖLÇÜLMEDİ** (yöntem `faz12-lcp.md` §6.1) |
| E3 | CLS 0,51'in kök nedeni | Taban çizgisi raporu §6.4: trace "kaynak yüklemesine bağlı değil" diyor; **ÖLÇÜLEMEDİ** |
| E4 | `Link: rel=preload` başlığının tarayıcı desteği | Üretimde doğrulanmalı — **ÖLÇÜLMEDİ** |
| E5 | Alan (RUM) verisi | Şema hazır, uç ve DocType yazılmadı; veri toplanmadı |

---

## 3. Ölçülen boşluğun kapanma durumu

`03-performans-taban-cizgisi.md` §2.2'nin dört boş satırı, **üretilen
işaretlemede** (tarayıcıda değil, üretici çıktısında) şöyle:

| Öznitelik | Bugün (ölçülen) | `picture.py` çıktısında | Doğrulayan |
|---|---|---|---|
| `srcset` | 0/31 | **var** | `audit()["srcset"] ≥ 1` |
| `sizes` | 0/31 | **var** | `audit()["sizes"] ≥ 1` |
| `<picture>` | 0/31 | **var** (tek biçimde bilinçli olarak yok) | `audit()["picture"] == 1` |
| `fetchpriority` | 0/31 | **var** (yalnız LCP adayında) | `audit()["fetchpriority_high"] == 1` |
| `width`+`height` | 31/31 ama **oran yanlış** (§4.3) | **var ve oran garantili** | `audit()["eksik_boyut"] == 0` |

`audit()` bu sayımı tarayıcı açmadan yapar; Faz 12 "sonra" ölçümünde aynı
tabloyu doldurmak için kullanılacak araçtır.

### 3.1 Örnek çıktı (referans işaretleme)

`tests/test_delivery_picture.py::test_beklenen_html_birebir` bu dizgeyi
**birebir** sabitler — değişirse test kırılır, yani bilerek değişir:

```html
<picture><source type="image/avif" srcset="/files/ab/<hash>__w384.avif 384w, /files/ab/<hash>__w640.avif 640w" sizes="(min-width: 768px) 172px, 50vw"><img src="/files/ab/<hash>__w640.webp" srcset="/files/ab/<hash>__w384.webp 384w, /files/ab/<hash>__w640.webp 640w" sizes="(min-width: 768px) 172px, 50vw" alt="Bonny erzak saklama kabı 1 lt" width="2400" height="2400" loading="lazy" decoding="async"></picture>
```

---

## 4. `sizes` doğrulamasının sonucu (T-121)

```
Doğrulanan satır: 71 · sapma: 1 (açıklanmamış: 0) · atlanan bölge: 3
  BİLİNEN product_detail/related_slider @390px: rapor 247.0 · türetilen 252.3 · fark +5.3px
          → Rapor §3.7 tek boşluk düşüyor, Swiper (n−1) boşluk düşürüyor;
            türetilen 252,3px Swiper'ın gerçek formülüdür.
  ATLANDI listing/brand_grid       — rapor yalnız 1920px satırını veriyor
  ATLANDI product_detail/lightbox_main — kutu viewport YÜKSEKLİĞİNE bağlı
  ATLANDI seller_shop/product_grid — rapor tablosu YOK, ÖLÇÜLMEDİ
```

**Bulunan tutarsızlık (rapor tarafında):** `03-render-envanteri.md` §3.7'nin
Swiper satırları, slayt genişliğini `(kapsayıcı − spaceBetween) / slidesPerView`
ile yaklaşıklıyor; Swiper'ın gerçek formülü
`(kapsayıcı − spaceBetween × (slidesPerView − 1)) / slidesPerView`. Fark
`slidesPerView = 1,4` iken ≈5,1 px. Rapor o satırları zaten `≈` ile
işaretlemiş. **Rapor dosyası bu görevde değiştirilmedi**; sapma
`tradehub_core/media/pipeline/delivery/sizes.py::KNOWN_DEVIATIONS` içinde gerekçesiyle kayıtlı.

**Üretilen `sizes` örnekleri:**

| Bölge | `sizes` |
|---|---|
| `product_detail/main_image` | `(min-width: 1536px) 502px, (min-width: 1280px) 377px, (min-width: 1024px) 300px, 100vw` |
| `home/hero_showcase_grid` | `(min-width: 1536px) calc((min(100vw, 1840px) - 64px - 96px) / 7), …, calc((min(100vw, 1840px) - 32px - 16px) / 2)` |
| `product_detail/thumb_rail` | `70px` |

`ManifestBuilder.SIZES_TABLE` artık `sizes.install(builder)` ile doluyor;
manifestin `extra["sizes_source"]` alanı `unmeasured` olmaktan çıkıyor
(`test_manifest_sizes_source_artik_unmeasured_degil`).

---

## 5. Bayt hesabı — ürün detay sayfası

**Doğrulama:** ölçüm için seçilen 12 dosyanın diskteki toplamı **13.759.638 B**;
taban çizgisi raporunun ölçtüğü `/files/` payı da **13.759.638 B**. Dosya kümesi
doğru.

| Senaryo (390px telefon, DPR 2) | AVIF | WebP |
|---|---:|---:|
| **Bugün** (12 orijinal) | 13.759.638 B | 13.759.638 B |
| Türev matrisi (12×`w192` + 1×`w1280`) | 73.416 B | **61.466 B** |
| `w800` basamağı eklenirse | 67.537 B | **51.322 B** |
| En kötü hâl (12 slaydın hepsi gezilir) | 2.393.197 B | 1.971.348 B |
| En kötü hâl + `w800` | 651.685 B | **493.064 B** |

**Kritik nüans — kazancın kaynağı:** 224×'in büyük kısmı `srcset`ten değil,
**karo şeridinin orijinali indirmeyi bırakmasından** geliyor (12 karo,
59×59 px kutuda tam boy master — taban çizgisi §7). `srcset`in kendi katkısı
ana görselde 199.092 B → 13.833 B (**14×**). İkisi ayrı ayrı raporlanmalı;
tek bir "224×" rakamı bu ayrımı gizler.

### 5.1 Depolama karşılığı

| | Bayt | Oran |
|---|---:|---:|
| 12 orijinal | 13.759.638 B | 1,00× |
| 12 dosyanın **tüm** türevleri | 13.911.443 B | **1,01×** |

`w1920` tek başına türev deposunun **%55'i**, `w1280` **%31'i**. Üst iki
basamak **%85**.

---

## 6. Yeniden üretim

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core

# T-120 / T-121 / T-123 testleri
python3 -m unittest tests.test_delivery_picture tests.test_delivery_sizes tests.test_delivery_rum -v

# `sizes` tablosunu bas ve raporla karşılaştır
PYTHONPATH=. python3 -m media_engine.delivery.sizes

# Simülatörle çapraz kontrol (65 cihaz × bölge)
PYTHONPATH=. python3 -m media_engine.simulator.srcset --all --sizes
```

Bayt ölçümünü tekrar üretmek için (konteyner açık olmalı):

1. `LST-03999`'un `primary_image` + `Listing Image` kayıtları çekilir,
2. dosyalar `sites/istoc.localhost/public/files` altından kopyalanır,
3. `media_engine.image.render.render_ladder(..., per_format=True)` ile
   AVIF+WebP kodlanır,
4. toplamlar karşılaştırılır.

Ara çıktılar depo dışındadır: `_olcum_faz12/{olcum,olcum800,avif_kalibre}.json`.

---

## 7. Faz 12 "sonra" ölçümü için kapanış listesi

Aşağıdakiler yapılmadan bu fazın kapandığı **söylenemez**:

- [ ] Türevler üretimde üretilsin (`w96…w1920`, AVIF+WebP)
- [ ] `w800` basamağı kararı verilsin (`faz12-lcp.md` §4.1)
- [ ] `encoder_quality.avif` kalibre edilsin (`faz12-lcp.md` §4.2) — **aksi
      hâlde AVIF baytı ARTIRIR**
- [ ] Storefront `<picture>` + `sizes` üretimine geçsin (salt okunur depo —
      ayrı ekip)
- [ ] `/files/` yoluna `Cache-Control` eklensin (taban çizgisi §5.1)
- [ ] Aynı 4 URL, aynı 2 profil ile yeniden ölçülsün
- [ ] RUM ucu + DocType yazılsın, `sample_rate` ile veri toplansın

---

## 8. Kaynaklar

- `docs/reports/03-performans-taban-cizgisi.md` — taban çizgisi (§7)
- `docs/reports/03-render-envanteri.md` — piksel tablosu (§3)
- `docs/plans/faz12-lcp.md` — T-122 planı, ölçüm detayları
- `tradehub_core/media/pipeline/delivery/{picture,sizes,rum}.py` — kod
- `tests/test_delivery_{picture,sizes,rum}.py` — 72 test
