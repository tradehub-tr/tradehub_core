# Ürün Görseli Standardı — T-020

**Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2` · **Slot:** `product.image`
**Durum:** `draft` — bazı değerler ölçülmedi, §9'a bakınız.

**Bu belgenin ürettiği dosyalar:**

| Dosya | Ne |
|---|---|
| `tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` | JSON Schema draft 2020-12 — her slot politikasının biçimi |
| `tradehub_core/media/pipeline/policy/slots/product-image.json` | Ürün görseli slotunun politikası |
| bu belge | Değerlerin gerekçesi + çelişkilerin kaydı + ölçülemeyenlerin listesi |

**Girdi envanterler:** `docs/reports/00-upload-slot-envanteri.md` (41 doctype alanı,
L0–L3 doğrulama katmanları), `docs/reports/03-render-envanteri.md` (20 render
noktası, CSS kutu × DPR tabloları).

> **Ölçüm uyarısı.** Docker kapalı; üretim veritabanına ve canlı siteye erişim
> yok. Bu belgede LCP, CLS, dosya boyutu, SSIM ve gerçek en-boy oranı dağılımına
> dair **hiçbir ölçüm sayısı yoktur**. Her sayı ya bir dosya:satır referansına ya
> da açıkça yazılmış bir aritmetik hesaba dayanır. Ölçüm gerektiren her şey §9'da,
> çalıştırılacak komutla birlikte.

---

## 1. Neden bu standarda ihtiyaç var — ve neyin üstüne yazmıyor

### 1.1 Zaten çözülmüş olanlar (dokunulmayacak)

`00-upload-slot-envanteri.md §6` ve `03-render-envanteri.md §4.1` bunları kanıtla
kaydetmiş. Bu standart hiçbirini yeniden tasarlamıyor:

| # | Çözülmüş | Kaynak |
|---|---|---|
| 1 | **Tek kapı politikası (L0).** Her yükleme yolu tek `check()`'ten geçiyor | `hooks.py:227-252` → `utils/security.py:96` → `media/upload_policy.py:307` |
| 2 | **Kodlu ret sözleşmesi.** 14 hata kodu + `retryable` bayrağı; istemci metne değil koda bakıyor | `upload_policy.py:104-139` |
| 3 | **Sınırların sunucudan dağıtımı.** `limits()` → `seller_media.upload_limits` → panel istemcisi | `upload_policy.py:398-428` |
| 4 | **Parçalı yükleme** (8 MB üstü) | `media/chunked.py`, eşik `upload_policy.py:89` |
| 5 | **Optimizasyon kapıları** (6 kapı, 200 KB tabanı, %10 kazanç tabanı) | `media/gates.py:42-85`, `presets.py:22,25` |
| 6 | **EXIF yön düzeltmesi + ICC koruma + progressive JPEG** | `engine.py:114-122` |
| 7 | **Sunucu tarafı garanti-WebP** (Safari/iOS istemcisi WebP üretemediğinde) | `engine.py:148-181` |
| 8 | **CLS koruması.** Ürün render noktalarının tamamında `aspect-square` kapsayıcı + `width`/`height` attribute | `03-render-envanteri.md §5` — R1–R15, R17, R18, R20 "risk yok" |
| 9 | **Galeri görselinin tek giriş noktası.** `renderGalleryMedia` — `srcset` eklenecekse **buraya** eklenir | `ProductImageGallery.ts:54-77` |
| 10 | **Fold-üstü/altı lazy ayrımı** (bilinçli, CWV çalışmasıyla verilmiş karar) | `ListingCard.ts:17-23` |

### 1.2 Eksik olan tam olarak ne

| Eksik | Kanıt |
|---|---|
| **Sunucu bir yüklemenin hangi slota ait olduğunu bilmiyor.** `check()` yalnız `file_name`, `content`, `size`, `media_endpoint` alıyor | `upload_policy.py:306-312` |
| **Piksel boyutu kuralı yok** — hiçbir slotta | `00-upload-slot-envanteri.md §10`: "0 slotta piksel boyutu, en-boy oranı veya adet kuralı var" |
| **En-boy oranı kuralı yok.** Oranı yazan tek yer bir önizleme CSS'i (`aspect-[1.91/1]`), yüklenen dosya denetlenmiyor | `OgImageUpload.vue:57`; `§7-B B2` |
| **Adet kuralı yok.** Ürün galerisinde ne boyut ne adet kontrolü var | `§7-A`: `ListingFormView.vue:1162-1168` |
| **Türev boy üretimi yok.** Bir yükleme → bir dosya | `03-render-envanteri.md §6.3`; `engine.py:117,177` |
| **`srcset` / `sizes` / `<picture>` sıfır** | `03-render-envanteri.md §4`: `grep -rni "srcset" src \| wc -l` → 0 |

Bu standart **B1'i** (slot kimliği) veri biçimi olarak kurar; kalan maddelerin
kural gövdesini yazar. Kod yolunu bağlamak Faz 2'nin sonraki görevidir.

### 1.3 Bugünkü israfın büyüklüğü — hesap, ölçüm değil

Bugün her render noktası **aynı master dosyayı** indiriyor
(`03-render-envanteri.md §0 madde 5`). En küçük ve en büyük talep arasındaki fark:

| Render noktası | Gereken genişlik | İndirilen | Piksel katı |
|---|---|---|---|
| Sepet SKU satırı (`SkuRow.ts:36`, 40px @2x) | 80 px | 1920 px | (1920/80)² = **576×** |
| Kart ızgarası 360px telefon (`§3.1`, 156px @2x) | 312 px | 1920 px | (1920/312)² ≈ **38×** |
| Kart ızgarası masaüstü (`§3.4`, 343px @2x) | 685 px | 1920 px | (1920/685)² ≈ **7.9×** |
| PD mobil ana görsel 430px @3x (`§3.6`) | 1290 px | 1920 px | ≈ **2.2×** |
| Masaüstü hover-zoom @2x (`§3.5b`) | 1858 px | 1920 px | ≈ **1.07×** |

> **Bu tablodaki "piksel katı" bayt tasarrufu DEĞİLDİR.** Bayt, piksel sayısıyla
> doğrusal artmaz (entropi ve encoder davranışına bağlı). Gerçek bayt kazancı
> ölçülmedi — §9.5. Tablonun söylediği tek şey: **kapasite talebi 80 px ile
> 1908 px arasında 24 kat değişiyor ve bugün tek dosyayla karşılanıyor.**

---

## 2. Şema — `slot-policy.schema.json`

JSON Schema **draft 2020-12**. Doğrulandı:

```bash
python3 -m venv /tmp/jsv && /tmp/jsv/bin/pip install -q jsonschema
/tmp/jsv/bin/python - <<'EOF'
import json, jsonschema
s = json.load(open('tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json'))
i = json.load(open('tradehub_core/media/pipeline/policy/slots/product-image.json'))
jsonschema.Draft202012Validator.check_schema(s)          # → şema geçerli
print(len(list(jsonschema.Draft202012Validator(s).iter_errors(i))))   # → 0
EOF
```

Çalıştırıldı: şema geçerli, `product-image.json` **0 ihlal**.

### 2.1 Şemanın zorladığı disiplin

Şema sadece biçim denetlemiyor; üç kuralı **yapısal olarak** zorluyor:

1. **`sources` zorunlu.** Politikadaki her sayının nereden geldiği yazılmak
   zorunda. `$defs.provenance` boş ya da "bilinmiyor" değerini reddediyor
   (`minLength: 8`), kabul ettiği biçimler: `dosya:satır`, `docs/… §bölüm`,
   `hesap: <formül>`, `ÖLÇÜLMEDİ: <ne yapılmalı>`.
2. **`profiles[].derived_from` zorunlu.** Bir türev genişliği, dayandığı CSS
   kutusu × DPR hesabı yazılmadan eklenemez. Profil genişliği uydurulamaz.
3. **`content_rules[].source` zorunlu.** Eşik kalibre edilmemişse bunu yazmak
   zorunda; `status` alanı da `draft` iken politikanın zorlanmayacağını söylüyor.

### 2.2 Şemayla ifade edilemeyen değişmezler (invariant)

JSON Schema alanlar arası kısıt kuramaz. Bunlar politika yükleyicide
denetlenmelidir:

| # | Değişmez | Neden |
|---|---|---|
| I1 | `max(profiles[].width) <= master.max_long_edge` | Upscale yok (`engine.py:117` `thumbnail` yalnız küçültür) |
| I2 | `master.max_long_edge² / 1e6 >= master.max_megapixels` | Tutarlılık |
| I3 | `master.min_long_edge <= master.max_long_edge` | — |
| I4 | `accept.max_bytes <= upload_policy.MAX_BYTES[kind]` | Slot politikası global tavanı **gevşetemez** (`upload_policy.py:67-76`) |
| I5 | `accept.extensions` ⊆ `accept.mime` karşılıkları | Ayrışırsa uzantı listesi kazanır ve politika sessizce delinir (`upload_policy.py:317-320` kararı uzantıdan veriyor) |
| I6 | Her `content_rules[].message_key` `messages.tr` içinde var olmalı | Kod var, metin yok durumunu engeller |
| I7 | `require.min_area <= min_short_edge² × max(allowed_ratios)` | Aksi hâlde hiçbir görsel geçemez |
| I8 | `allowed_ratios` tolerans bantları çakışmamalı | Oran ataması tek anlamlı olsun (§4.2) |
| I9 | `status == "active"` iken `open_questions` boş ve hiçbir `encoder_quality` `null` olamaz | Yarım politikanın zorlanmasını engeller |

---

## 3. `product-image.json` — değerler ve kaynakları

### 3.1 `accept` — dosya açılmadan uygulanan kapı

| Alan | Değer | Kaynak |
|---|---|---|
| `mime` | `image/jpeg`, `image/png`, `image/webp`, `image/tiff` | `engine.py:21` `SUPPORTED_FORMATS = {JPEG, PNG, WEBP, TIFF}` — motorun bugün gerçekten açabildiği küme |
| `extensions` | `.jpg .jpeg .png .webp .tif .tiff` | `engine.py:27-35` `FORMAT_EXTENSIONS` ∩ yukarıdaki küme |
| `max_bytes` | 26 214 400 (25 MB) | `upload_policy.py:68` `MAX_BYTES[image]` — **bilinçli olarak global tavanla aynı** (§3.5) |
| `max_megapixels_hard` | 80 | T-020 görev tanımı. Kodda karşılığı **yok**: `grep MAX_IMAGE_PIXELS tradehub_core/` → 0 sonuç |
| `allow_animated` | `false` | `engine.py:111-112` — motor animasyonluyu işlemiyor (`reason='animated'`) |

**`max_megapixels_hard=80` neden gerekli.** Bayt tavanı yeterli değil: 25 MB'lık
bir PNG açıldığında yüz milyonlarca piksel üretebilir (decompression bomb). Bu
kontrol görselin **tamamı açılmadan**, yalnız başlıktan (`PIL.Image.open` + `.size`,
piksel okumadan) yapılmalıdır. Kod tabanında benzer koruma yalnız feed indirmede
var: `bulk_import/feed_security.py:77-84`.

**HEIC/AVIF çelişkisi — kapatılmamış açık soru.** `upload_policy.py:57-60`
`.avif` ve `.heic`'i "image" sayıp L0'dan geçiriyor; `api/seller_media.py:245-247`
`IMAGE_TO_WEBP_EXTENSIONS` ikisini de **açıkça içeriyor**, yani sistem onları
WebP'ye çevirmeyi hedefliyor. Ama:

- `engine.SUPPORTED_FORMATS` (`engine.py:21`) ikisini de içermiyor →
  `optimize()` `unsupported_format` döner (`:109-110`), yani bu dosyalar
  **hiç optimize edilmez**.
- `to_webp()` (`:161-163`) doğrudan `Image.open` çağırıyor. Pillow eklentisi
  yoksa istisna atar — ama bu istisna **yakalanıyor**:
  `api/seller_media.py:294-300` orijinal içerikle devam edip `log_error`
  yazıyor, yükleme reddedilmiyor. Yorumu bunu kelimesiyle kabul ediyor:
  *"bazı HEIC varyantları … yükleme reddedilmez, yalnız Safari-fallback
  tamamlanmamış olur."*
- `requirements.txt` ve `pyproject.toml`'da `pillow-heif` /
  `pillow-avif-plugin` **yok** (ikisi de okundu).

**Sonuç — kayda geçen bulgu:** eklenti kurulu değilse bir HEIC ürün görseli
sessizce `.heic` olarak kütüphaneye giriyor; ne WebP'ye çevriliyor ne optimize
ediliyor ve HEIC'i çözemeyen tarayıcılarda **hiç görünmüyor**. Kullanıcıya
hiçbir uyarı gitmiyor, yalnız hata günlüğüne satır düşüyor. Bu yüzden
`accept.mime` allowlist'ine alınmadı: politika bu durumu **açık bir ret
mesajıyla** (`format_not_supported`, §8) karşılamayı öneriyor — sessiz kayıp
yerine. Eklenti kuruluysa karar tersine döner. Doğrulama komutu §9.7'de.

### 3.2 `require` — geometri kapısı

| Alan | Değer | Kaynak |
|---|---|---|
| `min_short_edge` | 1000 px | T-020 görev tanımı |
| `min_area` | 1 000 000 px | T-020 görev tanımı |
| `allowed_ratios` | `1:1`, `4:5`, `3:4` | T-020 görev tanımı |
| `ratio_tolerance` | 0.02 (±%2) | T-020 görev tanımı |
| `max_count` | 12 | **ÖLÇÜLMEDİ** — §9.4 |

**Karşılaştırma yönü kritik: `>=`, `>` değil.** 1:1 oranda kısa kenar tam
1000 px iken alan tam `1000 × 1000 = 1 000 000` olur — yani iki kural sınırda
**tam olarak buluşur**. `>` kullanılsa `min_short_edge=1000`'i geçen kare bir
görsel `min_area`'dan takılırdı. Bu, şemada `require.min_area` açıklamasına
yazıldı.

Kısa kenar 1000 px iken oranlara göre en küçük kabul edilebilir görsel:

| Oran | En küçük kabul | Alan | `min_area` geçiyor mu |
|---|---|---|---|
| 1:1 | 1000 × 1000 | 1 000 000 | tam sınırda ✔ |
| 4:5 | 1000 × 1250 | 1 250 000 | ✔ |
| 3:4 | 1000 × 1333 | 1 333 000 | ✔ |

Yani `min_area` **yalnız 1:1'de bağlayıcı**; diğer iki oranda `min_short_edge`
zaten daha sıkı. Bu bir hata değil, bilinçli üst üste binme: oran kuralı devre
dışı bırakılırsa (`ratio_tolerance: 1`) `min_area` tek başına panoramik/şerit
görselleri keser.

### 3.3 `master`

| Alan | Değer | Kaynak |
|---|---|---|
| `max_long_edge` | **2400** | Hesap — §5'te ayrıntılı |
| `min_long_edge` | 2000 | T-020 görev tanımı |
| `max_megapixels` | 5.76 | Hesap: 2400 × 2400 = 5 760 000 px |
| `dpi_out` | 72 | T-020 görev tanımı |
| `colorspace` | `srgb` | **KARAR** — mevcut davranıştan farklı, §3.4 |
| `format` | `webp` | §8'deki adlandırma notu |
| `orientation` | `apply_exif` | `engine.py:116` — mevcut davranış korunuyor |
| `strip_metadata.exif` | `true` | Yön bilgisi zaten piksele uygulanıyor (`engine.py:116`) |
| `strip_metadata.gps` | `true` | KVKK — satıcının fabrika/ev konumu EXIF GPS ile sızabilir. Kod tabanında bugün EXIF temizliği **yok** |
| `strip_metadata.xmp` | `true` | — |
| `strip_metadata.icc` | **`false`** | `engine.py:11-13` notu: ICC bilinçli olarak korunuyor. Silmek renk yönetimini bozar |

**`min_long_edge=2000` bir ret eşiği değil.** `require.min_short_edge=1000` ile
`master.min_long_edge=2000` arasında bir **kabul edilen ama eksik** bandı var:

```
uzun kenar 1000–1999 px  →  kabul edilir, master üretilir, ama "under-spec"
                            işaretlenir; w1920 profili üretilemez
uzun kenar ≥ 2000 px     →  tam spesifikasyon; ladder'ın tamamı üretilir
```

Sistem asla büyütmez (`engine.py:117` `thumbnail` yalnız küçültür), bu yüzden
1200 px'lik bir orijinalden 1920 px'lik bir türev **uydurulamaz**. Kullanıcıya
gösterilecek mesaj: `master_under_spec` (§8) — reddetmiyor, ne kaybettiğini
söylüyor.

### 3.4 `colorspace: "srgb"` — mevcut davranıştan sapma, bilinçli işaretli

Motor bugün ICC profilini **dönüştürmüyor, taşıyor** (`engine.py:115` profili
alır, `:122/:126/:131/:133` çıktıya yazar) — yani fiilen `preserve`. Politika
`srgb` diyor: gerekçe, Display P3 çekilmiş telefon fotoğraflarının profil
yorumlamayan yollarda soluk/aşırı doygun görünmesi. **Ama bu ölçülmedi** ve
motor değişikliği gerektirir → `open_questions[2]`'de kayıtlı, `status: draft`
olduğu için zorlanmıyor.

### 3.5 `max_bytes` neden sıkılaştırılmadı

25 MB, bugünkü fiili tavan (`upload_policy.py:68`). Sıkılaştırmak cazip
(2400 px'lik bir ürün görseli normalde 1 MB altında kalır) ama:

- Ürün görsellerinin gerçek medyan/p95 dosya boyutu **ölçülmedi**
  (`03-render-envanteri.md §7.3` de bunu ölçülmemiş olarak işaretliyor).
- Panel ilan formu bugün istemcide **hiç** boyut kontrolü yapmıyor
  (`ListingFormView.vue:502-507`, `:1162-1168` — `00-upload-slot-envanteri.md §7-A`),
  yani sahada 25 MB'a yakın dosyalar olabilir.

Ölçmeden sıkılaştırmak, sayısı bilinmeyen bir satıcı grubunu kilitler. §9.5.

---

## 4. En-boy oranı kuralı

### 4.1 Toleransın uygulanması — bağıl, mutlak değil

```
kabul  ⟺  min over r ∈ allowed_ratios of  |(w/h) − r| / r  ≤  0.02
```

Bağıl olması şart: mutlak fark kullanılsa aynı ±0.02, `1:1` (r=1.0) için %2,
`3:4` (r=0.75) için %2.7 tolerans anlamına gelirdi — dar oranlar keyfî biçimde
gevşemiş olurdu.

### 4.2 Bantlar ve çakışma denetimi

| Oran | r = G/Y | Alt sınır | Üst sınır |
|---|---|---|---|
| `3:4` | 0.750 | 0.735 | 0.765 |
| `4:5` | 0.800 | 0.784 | 0.816 |
| `1:1` | 1.000 | 0.980 | 1.020 |

Boşluklar: 0.765 → 0.784 (var) ve 0.816 → 0.980 (var). **Bantlar çakışmıyor**,
yani her kabul edilen görsel tek bir orana atanır — dolgu/kırpma kararı
belirsiz kalmaz. Bu, şemadaki I8 değişmezi.

### 4.3 Oran kuralının render tarafındaki sonucu — göz ardı edilemez

`03-render-envanteri.md §2`'ye göre ürün görselinin basıldığı **her** kutu kare:
R1, R2, R4, R6, R8, R9, R10, R17, R18, R20 hepsinde `aspect-square`. Object-fit
davranışı ise iki çeşit:

| Yer | `object-fit` | 3:4 görselde sonuç |
|---|---|---|
| PD ana görsel (`ProductImageGallery.ts:246-248`) | `contain` | Yanlarda boş bant — ürün tam görünür |
| Kart ızgaraları (`ListingCard.ts:163`) | `cover` | **Yüksekliğin %25'i kırpılır** — ürünün üstü/altı kesilir |

Yani `4:5` ve `3:4` kabul edilirken kart ızgaralarında ürünün kırpılması
kaçınılmaz — **eğer türev üretiminde bir şey yapılmazsa**. §7'deki `fit` kararı
tam olarak bunu çözüyor.

---

## 5. ⚠️ ÇELİŞKİ: mevcut kod 1920/2000 diyor, doküman 2400 diyor

Bu, T-020'nin çözmek zorunda olduğu asıl çelişki.

### 5.1 Bugün kodda kaç tavan var — üç, bir değil

| Yol | Tavan | Kaynak |
|---|---|---|
| `to_webp()` — sunucu tarafı garanti-WebP | **1920** (sabit yazılı) | `engine.py:177` `im.thumbnail((1920, 1920))` |
| `optimize()` — varsayılan `balanced` preset | **2000** | `engine.py:117` `im.thumbnail((max_dim, max_dim))` + `presets.py:15` |
| `optimize()` — `safe` preset | 2560 | `presets.py:14` |
| `optimize()` — `aggressive` preset | 1600 | `presets.py:16` |

Yani "mevcut kod 1920'ye küçültüyor" ifadesi **yalnız garanti-WebP yolu için**
doğru. Ama ürün görselleri fiilen o yoldan geçiyor — bu **doğrulandı, tahmin
değil**:

- `api/seller_media.py:245-247` `IMAGE_TO_WEBP_EXTENSIONS` = `.jpg .jpeg .png
  .bmp .tif .tiff .avif .heic` → yani JPEG ve PNG dahil.
- `api/seller_media.py:292` `icerik = engine.to_webp(icerik)` — tek parça ve
  parçalı yükleme **aynı** `_kaydet()` fonksiyonundan geçiyor (`:271-276`
  docstring'i bunu açıkça söylüyor).
- `engine.to_webp` içinde tavan sabit: `engine.py:177` `im.thumbnail((1920,
  1920))`. Bunun bir de testi var: `tradehub_core/tests/test_engine_webp.py:33`
  `test_to_webp_boyutu_1920_ile_sinirlar`.

Sonuç: medya kütüphanesinden yüklenen her ürün görseli **1920**'ye iniyor.
Toplu optimizasyon işi (`media/runner.py`) `optimize()` yolundan geçiyor →
varsayılan **2000**.

> **Kayda geçen ek bulgu:** aynı ürün görseli, hangi yoldan geçtiğine göre
> 1920 px ya da 2000 px uzun kenara iniyor. `presets.py:5-6` yorumu `max_dim`'in
> aynı zamanda Kapı 4'ün (`already_small`) eşiği olduğunu söylüyor: 1920'ye
> inmiş bir dosya `balanced` (2000) eşiğinin altında kalır, yani bir daha
> dokunulmaz. İki tavan sessizce birbirini kilitliyor ve arşiv 30 günlük
> (`presets.py:38`) — o pencere kapandıktan sonra 1920'nin üstündeki piksel
> **kalıcı olarak kayıp**. Kilidin üretimdeki büyüklüğü ölçülmedi — §9.8.
> Bu bir T-020 kararı değil, kayda geçirilen mevcut davranıştır.

### 5.2 Render envanterinden çıkan piksel talebi

Ürün görselinin **en büyük CSS kutusu**, ürün detay sayfasının mobil
düzenindeki ana görseldir: kutu = **tam viewport genişliği**
(`03-render-envanteri.md §3.6`; `MobileLayout.ts:136` `w-full aspect-square`,
mobil/masaüstü eşiği `product-detail.ts:291` → **1024 px**).

`§3.6` tablosundan, DPR ile birlikte:

| Viewport (CSS) | @1x | @2x | @3x | Gerçek cihaz sınıfı |
|---|---|---|---|---|
| 360 | 360 | 720 | 1080 | Android orta segment |
| 390 | 390 | 780 | 1170 | iPhone 14/15 |
| 430 | 430 | 860 | **1290** | iPhone Pro Max |
| 640 | 640 | 1280 | 1920 | küçük tablet / katlanabilir |
| **768** | 768 | 1536 | **2304** | **tablet dikey** |
| 1023 | 1023 | **2046** | 3069 | geniş tablet (mobil düzenin son satırı) |

Diğer ürün-görseli talepleri (`§3.5b`, `§3.8`):

| Talep | Hesap | Değer |
|---|---|---|
| Masaüstü hover-zoom @2x | 502 px kutu × 1.85 zoom × 2 | **1858** |
| Lightbox ana görsel @3x | 636 px × 3 | **1908** |
| Lightbox ana görsel @2x | 636 × 2 | 1272 |
| Kart ızgarası @3x (en geniş) | 343 × 3 | 1028 |

Zoom katsayısı 1.85 sabit değil, koddan: `ProductImageGallery.ts:22`
`ZOOM_SCALE = 1.85`, uygulanışı `alpine/product.ts:505`.

### 5.3 Karar: **2400** — gerekçe

Görev tanımının istediği ölçüt: *en büyük CSS kutusu × DPR 3.*

```
en büyük gerçek cihaz sınıfının CSS kutusu (tablet dikey)  = 768 px
× DPR 3                                                    = 2304 px
→ üst basamak                                              = 2400 px
```

1023 px'lik satırı DPR 3 ile çarpmıyoruz (3069 px) çünkü 1023 CSS px genişliğinde
**ve** DPR 3 olan bir cihaz sınıfı yok; o satırın bağlayıcı hâli DPR 2 → 2046 px.

**2400'ün kapsadıkları:**

| Talep | Değer | 2400 karşılıyor mu | 1920 karşılıyor mu |
|---|---|---|---|
| Tablet dikey 768 @3x | 2304 | ✔ | ✘ (%20 eksik) |
| Geniş tablet 1023 @2x | 2046 | ✔ | ✘ (%7 eksik) |
| Lightbox @3x | 1908 | ✔ | ✔ (sınırda) |
| Masaüstü zoom @2x | 1858 | ✔ | ✔ |
| Tablet 768 @2x | 1536 | ✔ | ✔ |
| iPhone Pro Max @3x | 1290 | ✔ | ✔ |

Yani **1920, iki gerçek cihaz sınıfında yetersiz**: tablet dikey @3x ve geniş
tablet @2x. `03-render-envanteri.md §3.6` bunu kendi cümlesiyle de yazıyor:
*"Mevcut master tavanı 1920px — yani geniş tabletlerde @2x zaten
karşılanamıyor."*

**2400 seçilmeli.** Ama bu kararın **iki koşulu** var:

### 5.4 Koşul 1 — 2400, türev üretimi gelmeden uygulanmamalı

Bugün master **aynı zamanda servis edilen dosyadır** (türev yok,
`03-render-envanteri.md §6.3`). `engine.py:177`'yi 1920 → 2400 yapmak, türevler
gelmeden **her render noktasına daha büyük dosya göndermek** demektir:

```
piksel artışı = (2400 / 1920)² = 1.5625  →  +%56 piksel, HER indirmede
```

Sepet SKU satırı (80 px talep) 1920 yerine 2400 indirmeye başlar. Yani sıralama
zorunlu:

```
1. türev üretimi + URL sözleşmesi  (backend)
2. master tavanını 2400'e çıkar
3. srcset / sizes                  (frontend — önce mediaUrl.ts genişletilmeli)
```

3. adımın önkoşulu `03-render-envanteri.md §6.1` uyarısı:
`tradehubfront/src/utils/mediaUrl.ts:76` `MutationObserver` `attributeFilter`'ı
`["src","style"]` — **`srcset` yok**. Bugün `srcset` eklenirse GitHub Pages
önizlemesinde görseller kırılır.

### 5.5 Koşul 2 — depolama bütçesi doğrulanmalı

Ladder'ın piksel maliyeti (1:1 dolgulu profiller varsayımıyla, kare alan):

| Profil | Genişlik | Alan (px) |
|---|---|---|
| w96 | 96 | 9 216 |
| w192 | 192 | 36 864 |
| w384 | 384 | 147 456 |
| w640 | 640 | 409 600 |
| w768 | 768 | 589 824 |
| w1280 | 1280 | 1 638 400 |
| w1920 | 1920 | 3 686 400 |
| **ladder toplamı** | | **6 517 760** |
| master | 2400 | 5 760 000 |

```
ladder / master = 6 517 760 / 5 760 000 = 1.13  (biçim başına)
```

İki biçim (AVIF + WebP) üretilirse ladder ≈ **2.26 × master piksel alanı**;
master'ın kendisi de +%56 büyüyor. **Bunlar piksel alanı hesabıdır, bayt
değil** — bayt ölçümü §9.5'te. `docs/reports/06-depolama-maliyet.md` ile çapraz
kontrol edilmeden bu ladder onaylanmamalı.

---

## 6. Profil ladder'ı — nasıl türetildi

`03-render-envanteri.md §3.9` dokuz aday genişlik öneriyor: 96, 192, 384, 640,
768, 1080, 1280, 1600, 1920. Politikaya **yedi** girdi. Kural: iki komşu aday
arasındaki oran **1.25'in altındaysa birleştir** — o kadar yakın iki türev,
bant genişliği kazancından çok depolama ve cache parçalanması maliyeti üretir.

| Aday çift | Oran | Karar |
|---|---|---|
| 1080 → 1280 | 1.19 | **birleştir → 1280** |
| 1600 → 1920 | 1.20 | **birleştir → 1920** |
| 640 → 768 | 1.20 | **birleştirme** — özel durum, aşağıda |
| 384 → 640 | 1.67 | ayrı kalır |
| 192 → 384 | 2.00 | ayrı kalır |
| 96 → 192 | 2.00 | ayrı kalır |

**640 ve 768 neden birleştirilmedi.** İkisi de tam bir gerçek kutuya oturuyor:
640, en yoğun kart talebini karşılıyor (640 px viewport'ta kart @2x = 592,
`§3.1`); 768, ürün detay mobil ana görselinin tablet dikey @1x talebine **tam
eşit** (`§3.6`) ve masaüstü kart @2x tavanını (685, `§3.4`) da kapsıyor. Bunlar
birleştirilse 592 px'lik talep 768'den karşılanır: `(768/592)² = 1.68` → en
yüksek trafikli yüzeyde %68 fazla piksel. **768 ladder'da en zayıf halkadır** ve
depolama bütçesi (§9.5) izin vermezse **ilk düşürülecek profildir.**

### 6.1 Profil tablosu

| Profil | Genişlik | Biçim | `fit` | Karşıladığı en küçük talep | Israf katı |
|---|---|---|---|---|---|
| `w96` | 96 | webp | pad 1:1 | 52 (lightbox karosu @1x) | 1.85 |
| `w192` | 192 | webp | pad 1:1 | 104 (lightbox karosu @2x) | 1.85 |
| `w384` | 384 | avif, webp | pad 1:1 | 210 (PD karosu @3x) | 1.83 |
| `w640` | 640 | avif, webp | pad 1:1 | 386 (kart @2x, 430 px viewport) | 1.66 |
| `w768` | 768 | avif, webp | pad 1:1 | 664 (kart @3x, 1440 px viewport) | 1.16 |
| `w1280` | 1280 | avif, webp | contain | 807 (kart @3x, 1440 px viewport) | 1.59 |
| `w1920` | 1920 | avif, webp | contain | 1290 (PD mobil 430 px @3x) | 1.49 |

"Israf katı" = profil genişliği / karşıladığı en küçük talep. Talepler
`§3.1–3.8` tablolarından; her profilin `derived_from` alanında hangi satırdan
geldiği yazılı.

### 6.2 Neden mikro profiller (96, 192) yalnız WebP

Küçük görsellerde AVIF'in konteyner ek yükü, kazancın önemli bir bölümünü
yiyebilir. **Bu ölçülmedi** — kararın kendisi geçici, `open_questions` ve §9.4'te
kayıtlı. Kalibrasyon 192 px'te AVIF'in kazanç sağladığını gösterirse eklenir.

JPEG fallback yok: WebP, Safari 14+ dahil tüm hedef tarayıcılarda destekli ve
sunucu tarafı garanti-WebP zaten kurulmuş (`engine.py:148-181`). `<picture>`
sırası `["avif","webp"]` — dizideki sıra `<source>` sırasıdır.

---

## 7. `fit` kararı — kırpma mı dolgu mu

`4:5` ve `3:4` kabul edildiği, tüm ürün kutuları kare olduğu ve kartlarda
`object-cover` bulunduğu için (§4.3) bir karar gerekiyor.

**Karar:**

| Profil grubu | `fit` | Gerekçe |
|---|---|---|
| `w96` – `w768` (karo + kart + PD mobil @1x) | `pad` → 1:1, `#FFFFFF` | Kare kutuya giden görsel önceden 1:1'e dolgulanırsa `object-cover` **kırpmaz** — kare bir görsel kare kutuyu tam doldurur. Ürünün üstü/altı kesilmez |
| `w1280`, `w1920` (lightbox + zoom kaynağı) | `contain` (dolgu yok) | Bunlar detay ve yakınlaştırma kaynağı. 3:4 bir görseli 1:1'e dolgulamak, 1920 px'in **480 px'ini beyaza** harcar: ürün yalnız 1440 px olur ve zoom talebi (1858) karşılanmaz |

Doğrulama: `object-contain` kullanan PD ana görselinde (`ProductImageGallery.ts:
246-248`) 1:1'e dolgulanmış bir görsel, dolgulanmamış hâliyle **görsel olarak
aynı** sonucu verir (iki durumda da yanlarda beyaz bant). Yani dolgu PD'yi
bozmuyor, yalnız kartları düzeltiyor.

> **Bu bir görünüm değişikliğidir.** Bugün 3:4 bir görsel kartta kırpılıyor;
> dolgudan sonra kırpılmayacak, daha küçük görünecek. Ticari onay gerekir. Bu
> yüzden `content_rules.border_ratio` (%25 üstü boşluk → `auto_fix`) ile
> birlikte düşünülmeli: dolgu, ürünü kadrajın merkezinde büyük tutan görsellerde
> anlamlı; zaten boşluklu bir görselde boşluğu ikiye katlar.

---

## 8. Hata mesajları — NEDEN + NASIL

**Kural:** her mesaj iki soruyu yanıtlar. (1) Neden reddedildi/uyarıldı —
kullanıcının ekranda göreceği sonuç diliyle, jargonla değil. (2) Nasıl
düzeltilir — somut, uygulanabilir bir eylem.

Şema bunu `$defs.messageMap` ile kısmen zorluyor (`minLength: 20`): tek kelimelik
"Geçersiz görsel" tipi metin yazılamaz.

Mevcut ret metinlerinin tonu korunuyor —
`upload_policy.py:341-347`: *"Dosya çok büyük: {0} MB. Bu tür için sınır {1} MB."*

### 8.1 Mesaj kataloğu (kod → aksiyon)

| Kod | Aksiyon | Kural kaynağı |
|---|---|---|
| `short_edge_too_small` | reject | `require.min_short_edge` |
| `area_too_small` | reject | `require.min_area` |
| `ratio_not_allowed` | reject | `require.allowed_ratios` + `ratio_tolerance` |
| `too_many_pixels` | reject | `accept.max_megapixels_hard` |
| `too_large_bytes` | reject | `accept.max_bytes` |
| `format_not_supported` | reject | `accept.mime` |
| `animated` | reject | `content_rules.animated` |
| `unreadable` | reject | `content_rules.unreadable` |
| `blank` | reject | `content_rules.entropy_bits` |
| `master_under_spec` | warn | `master.min_long_edge` |
| `blurry` | warn | `content_rules.blur_laplacian_variance` |
| `border_excessive` | auto_fix | `content_rules.border_ratio` |
| `background_not_uniform` | warn | `content_rules.background_uniformity` |
| `text_overlay` | review | `content_rules.text_area_ratio` |
| `watermark_suspect` | review | `content_rules.watermark_suspect` |
| `collage_suspect` | warn | `content_rules.collage_suspect` |
| `duplicate` | warn | `content_rules.duplicate_phash` |
| `too_many_files` | reject | `require.max_count` |

Yer tutucular: `{kisa_kenar}`, `{gerekli_kisa_kenar}`, `{uzun_kenar}`,
`{gerekli_uzun_kenar}`, `{oran}`, `{izinli_oranlar}`, `{mb}`, `{max_mb}`,
`{mp}`, `{max_mp}`, `{bicim}`, `{izinli_bicimler}`, `{yuzde}`, `{adet}`,
`{max_adet}`.

### 8.2 Örnek — neden bu kadar uzun

```
Görselin kısa kenarı 640 piksel; en az 1000 piksel gerekiyor. Bu boyutta
görsel ürün sayfasının büyük görselinde ve yakınlaştırmada bulanık çıkar.
Fotoğrafı telefonunuzun en yüksek çözünürlük ayarıyla yeniden çekin veya
orijinal (kırpılmamış) dosyayı yükleyin. WhatsApp'tan gelen görseller
sıkıştırıldığı için genelde bu sınırın altında kalır; dosyayı e-posta veya
bilgisayar üzerinden alın.
```

Son cümle sahaya özgü: B2B satıcıların görselleri tedarikçiden WhatsApp ile
gelir ve WhatsApp uzun kenarı düşürür. Kullanıcı "neden 1000'in altında"
sorusunun cevabını burada bulur — aksi hâlde aynı sıkıştırılmış dosyayı tekrar
tekrar dener.

### 8.3 Ret kodlarının biçimi

`on_violation.error_code_prefix = "product_image"` → istemciye dönen kod
`product_image_<message_key>`, ör. `product_image_ratio_not_allowed`. Mevcut
sözleşmeyle aynı biçim (`upload_policy.py:104-139`: `upload_too_large`,
`upload_ext_denied` …). `retryable: false` — kullanıcının dosyasıyla ilgili
hatalar tekrar denenmez (`upload_policy.py:97-100` kuralı).

---

## 9. 🔬 ÜRETİMDE DOĞRULANMALI

Bu makinede yapılamadı: Docker kapalı, üretim veritabanına ve canlı siteye
erişim yok. Her madde çalıştırılacak tam komutla yazılıdır.

### 9.1 Geriye dönük uyum — politikayı kaç görsel geçemez

**En kritik ölçüm.** Bu sayı bilinmeden `require.*` zorlanamaz: mevcut
ilanların yarısı takılıyorsa politika satıcıları kilitler.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import os, json
from collections import Counter
import frappe
from PIL import Image

RATIOS = {"1:1": 1.0, "4:5": 0.8, "3:4": 0.75}
TOL = 0.02
MIN_SHORT, MIN_AREA = 1000, 1_000_000

# Ürün görseli slotunun TÜM bağlı alanları (product-image.json bound_to)
urls = set()
for dt, fld in [("Listing", "primary_image"), ("Listing Image", "image"),
                ("Listing Variant Item", "variant_image")]:
    for r in frappe.get_all(dt, filters={fld: ["is", "set"]}, fields=[fld],
                            limit_page_length=0):
        urls.add(r[fld])
# variant_gallery JSON dizi
for r in frappe.get_all("Listing Variant Item",
                        filters={"variant_gallery": ["is", "set"]},
                        fields=["variant_gallery"], limit_page_length=0):
    try:
        urls.update(json.loads(r["variant_gallery"]) or [])
    except Exception:
        pass

say = Counter()
oranlar = Counter()
uzun_kenarlar = Counter()
for u in urls:
    if not isinstance(u, str) or "/files/" not in u:
        say["url_disi"] += 1; continue
    p = frappe.get_site_path("private" if u.startswith("/private") else "public",
                             u.lstrip("/").replace("private/", "", 1))
    if not os.path.exists(p):
        say["dosya_yok"] += 1; continue
    try:
        with Image.open(p) as im:
            w, h = im.size
    except Exception:
        say["acilamadi"] += 1; continue

    say["toplam"] += 1
    kisa, uzun, alan, oran = min(w, h), max(w, h), w * h, w / h
    uzun_kenarlar[uzun] += 1
    if kisa < MIN_SHORT: say["kisa_kenar_RET"] += 1
    if alan < MIN_AREA:  say["alan_RET"] += 1
    if not any(abs(oran - r) / r <= TOL for r in RATIOS.values()):
        say["oran_RET"] += 1
        oranlar[round(oran, 2)] += 1
    if uzun < 2000: say["master_under_spec"] += 1
    if (w * h) / 1e6 > 80: say["megapiksel_RET"] += 1

print("=== UYUM KARNESİ ==="); print(say)
print("=== REDDEDİLEN ORANLAR (ilk 20) ==="); print(oranlar.most_common(20))
print("=== UZUN KENAR (en sık 20) ==="); print(uzun_kenarlar.most_common(20))
PY
```

**Karar eşiği:** `kisa_kenar_RET + oran_RET` toplamı `toplam`ın **%10'unu**
aşıyorsa politika yeni yüklemelere uygulanır, mevcutlara **uygulanmaz**
(grandfathering) ve satıcılara toplu bir düzeltme kampanyası gerekir.

### 9.2 Master tavanının gerçek etkisi — kaç dosya tavana dayanmış

`03-render-envanteri.md §7.3` maddesi 2 ile aynı soru, slota indirilmiş hâli.
9.1'in çıktısındaki `uzun_kenarlar` sayacında **tam 1920** ve **tam 2000**
değerlerine bakın:

- tam 1920 olanlar → `to_webp()` yolundan geçmiş ve tavana dayanmış
  (`engine.py:177`). Orijinali daha büyüktü, bilgi **kalıcı olarak kayıp**.
- tam 2000 olanlar → `optimize()` + `balanced` (`presets.py:15`).

Bu iki sayının toplamı, master tavanının 2400'e çıkarılmasının **gelecek**
yüklemelerde ne kadar fark yaratacağının göstergesidir. Geçmiş dosyalar için
`media/archive.py` + `presets.py:35` `ARCHIVE_DIRNAME = "image_originals"`
arşivi kontrol edilmelidir:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import os, frappe
from tradehub_core.media import presets
p = frappe.get_site_path("private", "files", presets.ARCHIVE_DIRNAME)
print("arşiv yolu:", p, "var mı:", os.path.isdir(p))
if os.path.isdir(p):
    ad = os.listdir(p)
    print("arşivdeki dosya:", len(ad))
    print("saklama penceresi (gün):", presets.ARCHIVE_RETENTION_DAYS)
PY
```

Arşiv 30 günlük (`presets.py:38`) — yani 30 günden eski görsellerin orijinali
**yok**. 2400'lük master yalnız arşivi duran ve yeni yüklenen dosyalar için
gerçekleşebilir.

### 9.3 Gerçek CSS kutularının tarayıcıda doğrulanması

`03-render-envanteri.md §3`'teki tüm kutu genişlikleri **hesaplanmıştır**.
`§7.2`'deki konsol betikleri buradaki profil kararını doğrular; en kritik olan
"israf" listesi:

```js
[...document.images]
  .filter(i => i.naturalWidth > i.getBoundingClientRect().width * devicePixelRatio * 1.2)
  .map(i => ({ src: i.currentSrc.split('/').pop(),
               kutu: Math.round(i.getBoundingClientRect().width),
               dosya: i.naturalWidth,
               kat: (i.naturalWidth / (i.getBoundingClientRect().width * devicePixelRatio)).toFixed(1) }))
  .sort((a,b) => b.kat - a.kat)
```

§1.3'teki "piksel katı" tablosu **bu çıktıyla** karşılaştırılmalı. Ayrıca
masaüstü zoom talebini doğrulayan tek ölçüm:

```js
(() => { const i = document.querySelector('#gallery-main-image img');
  const w = i.getBoundingClientRect().width;
  return { kutu: w, dosya: i.naturalWidth, dpr: devicePixelRatio,
           zoomluGerekli: Math.ceil(w * 1.85 * devicePixelRatio) }; })()
```

`zoomluGerekli` ≥ 1920 çıkan her ekran, master 2400 kararının doğrudan
gerekçesidir.

### 9.4 Encoder kalibrasyonu — `encoder_quality.avif` hepsinde `null`

Politika `status: draft`; `active` olabilmesi için AVIF kaliteleri hedef SSIM'e
göre kalibre edilmeli. Kod tabanında kalite ölçümü **hiç yok** (`grep
'ssim|butteraugli|dssim' tradehub_core docs` → 0 anlamlı sonuç).

```bash
# Üretim sunucusunda, gerçek ürün görsellerinden örneklem alarak:
pip install pillow-avif-plugin scikit-image
python3 - <<'PY'
import glob, io
from PIL import Image
import pillow_avif  # noqa: F401 — AVIF encoder'ı kaydeder
import numpy as np
from skimage.metrics import structural_similarity as ssim

HEDEF = {"photo": 0.96, "graphic": 0.98, "text": 0.99, "fine_detail": 0.975}
GENISLIKLER = [384, 640, 768, 1280, 1920]

# ÖNEMLİ: örneklem gerçek ürün görsellerinden alınmalı; sentetik test görseli
# encoder'ı yanlış kalibre eder. Sınıflar elle etiketlenmeli (photo/graphic/
# text/fine_detail) — otomatik sınıflandırıcı henüz yok.
for yol in sorted(glob.glob("/tmp/ornek/*/*")):   # /tmp/ornek/<sinif>/<dosya>
    sinif = yol.split("/")[-2]
    ref = Image.open(yol).convert("RGB")
    for w in GENISLIKLER:
        if ref.width < w: continue
        h = round(ref.height * w / ref.width)
        temel = ref.resize((w, h), Image.LANCZOS)
        ta = np.asarray(temel)
        for q in range(30, 96, 5):
            for fmt in ("AVIF", "WEBP"):
                b = io.BytesIO(); temel.save(b, fmt, quality=q)
                s = ssim(ta, np.asarray(Image.open(io.BytesIO(b.getvalue())).convert("RGB")),
                         channel_axis=2, data_range=255)
                if s >= HEDEF[sinif]:
                    print(f"{sinif} {w}px {fmt} q={q} ssim={s:.4f} bayt={len(b.getvalue())}")
                    break
PY
```

Her `(sınıf, genişlik, biçim)` için hedefi tutturan **en düşük** q değeri
`profiles[].encoder_quality`'ye yazılır. Aynı koşum §6.2'yi de yanıtlar: 96 ve
192 px'te AVIF, WebP'den daha küçük bayt üretiyor mu?

### 9.5 Depolama bütçesi — ladder gerçekten karşılanabilir mi

§5.5'teki `2.26 × master` **piksel alanı** hesabı; bayt karşılığı ölçülmedi.

```bash
# 1) Mevcut ürün görseli baytı (taban çizgi)
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select attached_to_doctype, attached_to_field,
         count(*) adet, sum(file_size) toplam_bayt,
         round(avg(file_size)/1024) ort_kb
  from tabFile
  where attached_to_doctype in ('Listing','Listing Image','Listing Variant Item')
  group by attached_to_doctype, attached_to_field
  order by toplam_bayt desc
""", as_dict=True))
PY

# 2) 50 gerçek görselden tam ladder üretip baytı ölç (üretim sunucusunda)
#    Çıktı: ladder_bayt / master_bayt oranı → §5.5'in 2.26 piksel oranıyla
#    karşılaştırılır. Bu oran 06-depolama-maliyet.md bütçesine sığmazsa
#    ilk düşürülecek profil w768'dir (§6 gerekçesi).
```

Sonuç `docs/reports/06-depolama-maliyet.md` bütçesiyle çapraz kontrol edilmeli.

### 9.6 `content_rules` eşik kalibrasyonu

Yedi kuralın eşiği kalibre edilmedi; üçünün (`text_area_ratio`,
`watermark_suspect`, `collage_suspect`) dedektörü kod tabanında **hiç yok**.

```bash
# Ölçüm modu: kuralları action="ignore" ile çalıştır, dağılımı topla.
# Eşik, dağılımın kuyruğundan seçilir — keyfî sayıdan değil.
python3 - <<'PY'
import glob
import numpy as np
from PIL import Image
import cv2

for yol in sorted(glob.glob("/tmp/urun_gorselleri/*")):
    im = cv2.imread(yol, cv2.IMREAD_GRAYSCALE)
    if im is None: continue
    blur = cv2.Laplacian(im, cv2.CV_64F).var()          # blur_laplacian_variance
    hist, _ = np.histogram(im, bins=256, range=(0, 256))
    pr = hist / hist.sum(); pr = pr[pr > 0]
    entropi = float(-(pr * np.log2(pr)).sum())           # entropy_bits
    # border_ratio: kenar şeritlerinde tek renk oranı
    k = max(1, min(im.shape) // 20)
    seritler = np.concatenate([im[:k].ravel(), im[-k:].ravel(),
                               im[:, :k].ravel(), im[:, -k:].ravel()])
    border = float((np.abs(seritler.astype(int) - int(np.median(seritler))) < 6).mean())
    print(f"{yol}\tblur={blur:.1f}\tentropi={entropi:.2f}\tborder={border:.2f}")
PY
```

Eşik seçim kuralı: `reject` aksiyonlu kurallar için dağılımın **p1'i**,
`warn` için **p10'u**. Bugünkü değerler (blur 100, entropi 2.0, border 0.25,
phash hamming 6) **yer tutucudur** ve JSON'da `ÖLÇÜLMEDİ:` ile işaretlidir.

### 9.7 HEIC / AVIF gerçekten açılabiliyor mu

`accept.mime` bu ikisini içermiyor; sebebi bağımlılığın yokluğu (§3.1).

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
from PIL import Image, features
print("HEIF:", features.check("heif"), "| AVIF:", features.check("avif"))
print("Pillow:", Image.__version__)
print("kayıtlı encoder'lar:", sorted(Image.SAVE.keys()))
PY
docker compose exec backend pip list 2>/dev/null | grep -Ei "pillow|heif|avif"

# Fiili davranış testi: .heic bir dosya L0'ı geçip motorda ne yapıyor?
docker compose exec backend bench --site istoc.localhost console <<'PY'
from tradehub_core.media import upload_policy, engine
print(upload_policy.EXTENSIONS.get(".heic"), upload_policy.EXTENSIONS.get(".avif"))
data = open("/tmp/ornek.heic", "rb").read()
print("policy:", upload_policy.check("ornek.heic", content=data))
print("probe:", engine.probe(data))
print("optimize:", engine.optimize(data, 2400, 88).reason)
PY
```

`features.check("heif")` **False** dönerse: ya `pillow-heif` eklenir ya
`upload_policy.EXTENSIONS`'tan `.heic`/`.avif` çıkarılır. Bugünkü hâl ikisinin
arasında ve bir istisnaya açık.

### 9.8 İki tavanın kilitlenmesi — üretim verisinde doğrulama

`to_webp` → 1920 yolu kod okumasıyla **doğrulandı** (§5.1). Doğrulanmayan şey,
1920'ye inmiş dosyaların `already_small` kapısından geri dönüp dönmediği:
`presets.py:5-6` `max_dim`'in aynı zamanda Kapı 4 eşiği olduğunu söylüyor,
`gates.py:1-10` ise 4.007 dosyanın yalnız ~300'ünün kapıları geçtiğini kaydetmiş.
1920 < 2000 olduğu için garanti-WebP çıktısı bir daha hiç işlenmiyor olabilir.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
from tradehub_core.media import presets, gates
import inspect
print("varsayılan preset:", presets.DEFAULT_PRESET, presets.resolve(None))
print(inspect.getsource(gates))   # Kapı 4 'already_small' eşiği neyi okuyor
PY
```

9.1'in `uzun_kenarlar` sayacında **tam 1920** olan dosya sayısı, bu kilidin
büyüklüğüdür: o dosyaların hiçbiri `balanced` preset'iyle bir daha
işlenmeyecek ve orijinalleri 30 gün sonra arşivden silinecek (§9.2).
Doğrulanırsa §5.4'teki sıralama zorunlu hâle gelir.

### 9.9 LCP / CLS — bu belgede kasıtlı olarak boş

`03-render-envanteri.md §7.1` dört sayfa × iki profil Lighthouse koşumunun tam
komutunu veriyor; tekrar yazılmadı. Bu standardın beklediği iki audit:
`uses-responsive-images` ve `modern-image-formats` — srcset ve AVIF
eksikliğinin bayt cinsinden bedelini yalnız onlar verir ve §5.5 bütçesiyle
çapraz doğrulanmalıdır.

### 9.10 `require.max_count = 12` doğrulanmadı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select adet, count(*) ilan_sayisi from (
    select parent, count(*) adet from `tabListing Image` group by parent
  ) t group by adet order by adet desc
""", as_dict=True))
PY
```

12'nin üstünde galerisi olan ilan varsa kural geçmişe dönük uygulanamaz — o
ilanlar kaydedilemez hâle gelir.

---

## 10. Bu belgenin YAPMADIKLARI

1. **Hiçbir mevcut kod dosyası değiştirilmedi.** `engine.py`'daki 1920, çelişki
   olarak **kaydedildi**, düzeltilmedi. Düzeltme sırası §5.4'te.
2. **Hiçbir ölçüm yapılmadı.** Bu belgedeki her sayı ya `dosya:satır` ya
   `hesap:` etiketli. LCP, CLS, bayt, SSIM, gerçek oran dağılımı → §9.
3. **Slot kimliğinin kod yoluna bağlanması** T-020'nin kapsamı değil.
   `upload_policy.check()` imzası (`upload_policy.py:306-312`) hâlâ slot
   parametresi almıyor; politika bugün hiçbir kod yolu tarafından okunmuyor.
4. **Diğer 40 slot** için politika yazılmadı. Şema onları da kaldıracak biçimde
   yazıldı (`slot_key` deseni, `roles`, `bound_to`), ama yalnız
   `product.image` dolduruldu.
5. **`srcset` / `sizes` frontend işi** yapılmadı. Önkoşulu `mediaUrl.ts:76`
   `attributeFilter` genişletmesi (`03-render-envanteri.md §6.1`).

---

## 11. Ek — bu belgedeki her sayının kaynağı

| Sayı | Kaynak |
|---|---|
| `min_short_edge` 1000, `min_area` 1e6, oranlar, ±%2, 2400, 2000, 72 DPI, 80 MP | T-020 görev tanımı / kaynak tasarım dokümanı |
| Master tavanı 1920 (garanti-WebP) | `tradehub_core/media/pipeline.py:177` |
| Master tavanı 2000 / 2560 / 1600 (optimize) | `tradehub_core/media/presets.py:14-16`, `engine.py:117` |
| `SUPPORTED_FORMATS` = JPEG/PNG/WEBP/TIFF | `tradehub_core/media/pipeline.py:21` |
| Animasyonlu ret | `tradehub_core/media/pipeline.py:111-112` |
| EXIF transpose + ICC koruma | `tradehub_core/media/pipeline.py:11-13, 114-116` |
| WebP q=80 | `tradehub_core/media/pipeline.py:148` |
| Görsel bayt tavanı 25 MB | `tradehub_core/media/upload_policy.py:68` |
| `.heic`/`.avif` "image" sayılıyor | `tradehub_core/media/upload_policy.py:57-60` |
| 14 hata kodu + `retryable` | `tradehub_core/media/upload_policy.py:104-139` |
| `check()` imzası (slot parametresi yok) | `tradehub_core/media/upload_policy.py:306-312` |
| Mesaj tonu örneği | `tradehub_core/media/upload_policy.py:341-347` |
| `MIN_SAVING_RATIO` 0.10 | `tradehub_core/media/presets.py:25` |
| Arşiv 30 gün | `tradehub_core/media/presets.py:38` |
| `pillow-heif` / `pillow-avif-plugin` yok | `requirements.txt`, `pyproject.toml` |
| PD ana görsel kutusu 512 px | `tradehubfront/.../ProductImageGallery.ts:246` (`03-render-envanteri.md §3.5`) |
| Zoom 1.85× | `ProductImageGallery.ts:22`, `alpine/product.ts:505` |
| Lightbox sahnesi 636 px | `ProductImageGallery.ts:322-324` (`§3.8` hesabı) |
| Karo 70 / 52 / 80 px | `ProductImageGallery.ts:86,339`; `MobileLayout.ts:198` |
| PD mobil kutusu = tam viewport | `MobileLayout.ts:136`; eşik `product-detail.ts:291` |
| Kart kutuları (156…343 px) | `03-render-envanteri.md §3.1-3.4` |
| Kartlarda `object-cover`, PD'de `object-contain` | `ListingCard.ts:163`; `ProductImageGallery.ts:246-248` |
| `srcset`/`sizes`/`<picture>` = 0 | `03-render-envanteri.md §4` grep komutları |
| `mediaUrl.ts` `attributeFilter` `srcset` içermiyor | `tradehubfront/src/utils/mediaUrl.ts:76` |
| Türev üretimi yok (bir yükleme → bir dosya) | `03-render-envanteri.md §6.3` |
| "0 slotta piksel/oran/adet kuralı" | `00-upload-slot-envanteri.md §10` |
| Panel ilan formunda boyut kontrolü yok | `ListingFormView.vue:502-507, 1162-1168` (`§7-A`) |
| Ladder piksel toplamı 6 517 760 / 1.13× | Hesap — §5.5 tablosu |
| (2400/1920)² = 1.5625 | Hesap |
| 96/192/384/640/768/1280/1920 aday kümesi | `03-render-envanteri.md §3.9` + §6 birleştirme kuralı |
