# Standart — `company.cover_image` (Şirket / mağaza kapak görseli)

> **Güncel karar — 2026-08-23.** Makine kaynağı
> `tradehub_core/media/pipeline/policy/slots/company-cover-image.json` şemaya
> uyumludur; `standard_status=fixed`, açık soru sayısı 0 ve AVIF kalitesi
> 61'dir. Slot kimliği çalışma zamanı politika kapısına bağlıdır. Aşağıdaki
> 2026-08-17 `null`/“okunmuyor” notları tarihsel analizdir; `status=draft`
> yalnız Faz 3 rollout durumudur.

**Görev:** T-023 · **Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/company-cover-image.json`
**Kardeş belge:** `docs/standards/company-cover-video.md` (aynı yüzeyin video tarafı)
**Tarihsel durum:** `draft` — 2026-08-17 anlık görüntüsü
(`tradehub_core/media/upload_policy.py:307-313`).

> Bu slot sistemdeki **en zor geometri problemi**. Sebebi tek bir CSS gerçeği:
> bandın genişliği **tam viewport**, yüksekliği ise **sabit px**. Dolayısıyla
> kutunun oranı 360px telefonda 2,00:1, 1920px masaüstünde 4,80:1 oluyor.
> Tek dosya bu iki ucu birlikte dolduramaz. Bu belgenin asıl katkısı
> **güvenli alanı sayıyla tanımlamak**.

---

## 1. Kaynak alanlar — ve alan belirsizliği

| Kaynak | fieldtype | Durum |
|---|---|---|
| `Admin Seller Profile.banner_image` | Attach Image (`admin_seller_profile.json:129`) | Panelde var, **storefront'ta hiç okunmuyor** (`grep banner_image tradehubfront/src` → 0), LIVE_SOURCES'ta yok |
| `Storefront Layout.sections` içindeki `hero_banner` slaytları | Long Text (JSON) | **CANLI RENDER BU** — `section-registry.ts:117-222` |
| `seller.header_bg_image` | **?** | `pages/seller-shop.ts:118-119` okuyor; `grep -rn header_bg_image tradehub_core/` → **0 sonuç** |
| `Seller Gallery Image.poster_image` | Attach Image | Tanıtım videosunun kapağı; geometrisi `StoreHeader.ts:296` 16:9 kutusundan |

**Doğrulanmış negatif bulgu:** `admin_seller_profile.json` içinde dosya tutan
alan **yalnız** `logo` ve `banner_image`; `header_bg_image` diye bir alan
`tradehub_core`'un hiçbir yerinde yok. Ya `tr_tradehub` app'inden geliyor
(`docs/reports/00-upload-slot-envanteri.md` §9-M1) ya da ölü kod. §8.1'de
doğrulama komutu var.

---

## 2. Render konumları ve gerçek CSS kutuları

### 2.1 CANLI — mağaza hero bandı (statik ve slider)

`tradehubfront/src/utils/seller/section-registry.ts:103`:

```
w-full h-[180px] sm:h-[220px] md:h-[320px] lg:h-[400px] object-cover
```

Slider modunda yükseklik kapsayıcıdan gelir, aynı merdiven
(`section-registry.ts:206`), görsel `h-full object-cover` (`:104`).

**Genişlik = tam viewport.** Kanıt: `renderDynamicSections`
(`section-registry.ts:781-798`) her bölümü
`<div class="storefront-dynamic-section" style="...">` içine sarıyor ve
**hiçbir max-width uygulamıyor** (`:795`).

Kırılımlar bu projede ezilmiş: `sm=480`, `md=640`, `lg=768`, `xl=1024`
(`tradehubfront/src/style.css:256-260`). **Tailwind varsayılanıyla hesap
yapılırsa tüm tablo yanlış çıkar.**

| Viewport | CSS kutu | Oran | @2x talep | @3x talep |
|---|---|---|---|---|
| 360 | 360×180 | **2,00:1** | 720 | 1080 |
| 390 | 390×180 | 2,17:1 | 780 | 1170 |
| 430 | 430×180 | 2,39:1 | 860 | 1290 |
| 640 | 640×320 | 2,00:1 | 1280 | 1920 |
| 768 | 768×400 | 1,92:1 | **1536** | 2304 |
| 1024 | 1024×400 | 2,56:1 | 2048 | 3072 |
| 1280 | 1280×400 | 3,20:1 | **2560** | 3840 |
| 1440 | 1440×400 | 3,60:1 | 2880 | 4320 |
| 1536 | 1536×400 | 3,84:1 | 3072 | 4608 |
| **1920** | **1920×400** | **4,80:1** | 3840 | 5760 |

> **En dar oran 1,92:1 (768px) değil 2,00:1'dir** — 768px'te `lg:h-[400px]`
> devreye girip kutuyu geçici olarak daha kare yapıyor. Güvenli alan hesabında
> **en dar** oran olarak 1,92 yerine bilinçli olarak 2,00 kullanıldı, çünkü
> 768px tam kırılım noktasıdır ve 767px'te oran 767/320 = 2,40'a atlar; 360px
> satırı gerçek en dar üründür (2,00). Fark güvenli alanda %4'ten küçük.

### 2.2 CANLI — mağaza başlık CSS arka planı

`pages/seller-shop.ts:118-119`:

```html
<div class="border-b border-gray-200 bg-cover bg-center bg-no-repeat"
     :style="seller?.header_bg_image ? 'background-image: url(' + seller.header_bg_image + ')' : '...'">
```

Kutu: tam viewport genişliği; yükseklik iç bloktan
(`max-w-[1200px] px-4 lg:px-8 py-5`, `:120`). Üstüne `rgba(255,255,255,0.85)`
örtü basılıyor (`:121`).

**`<img>` değil** → `loading`, `decoding`, `srcset`, `fetchpriority`
uygulanamaz. `docs/reports/00-upload-slot-envanteri.md` §7-B B4 ile aynı sınıf
sorun.

### 2.3 CANLI — StoreHeader ana medya alanı (16:9)

`components/seller/StoreHeader.ts:296` → `aspect-video`; sütun `:203` →
`w-full lg:w-[500px] shrink-0`; sayfa kapsayıcısı `:46` →
`max-w-[1200px] mx-auto px-4 lg:px-8`.

İçerik genişliği = `min(1200, W) − (W ≥ 768 ? 64 : 32)`:

| Viewport | CSS kutu | @2x |
|---|---|---|
| 360 | 328×184 | 656 |
| 430 | 398×224 | 796 |
| 640 | 608×342 | 1216 |
| ≥768 | **500×281** (sabit) | **1000** |

Küçük medya karoları (`:379-391`):
`repeat(auto-fill, minmax(96px, 1fr))` + `aspect-[4/3]` → ≈96×72 … 137×103.

### 2.4 ÖLÜ renderlar

| Bileşen | Dosya:satır | Kanıt |
|---|---|---|
| `HeroBanner` (500px'e çıkan varyant) | `components/seller/HeroBanner.ts:13` | Yalnız `components/seller/index.ts:8`'de dışa aktarılıyor; `grep HeroBanner pages/` → yalnız `pages/trade-assurance.ts`'in **kendi yerel** `HeroBanner()` fonksiyonu (`:45,459`) |
| `CompanyInfo` hero görseli | `components/seller/CompanyInfo.ts:37` | `CompanyInfoComponent` hiçbir sayfada çağrılmıyor (yalnız `index.ts:12`) |

Kutuları kayıt için: `HeroBanner` `h-[180px] sm:200 md:300 lg:400 xl:500`,
attr 1200×500. `CompanyInfo` `h-[200px] sm:250 lg:400`, kap
`lg:grid-cols-[55%_45%] gap-6` → 1920px'te ≈964×400.

---

## 3. DPR ihtiyacı → minimum piksel

### 3.1 Minimum kabul

En büyük **gerçek** kutu **1920×400**. Bu yüzden:

- `require.min_short_edge = 400` — kutunun yüksekliği.
- `require.min_area = 768.000` = 1920 × 400.
- `content_rules.long_edge < 1920 → warn`
- `content_rules.long_edge < 960 → reject` (960 = 1920 / 2; 2× büyütme görünür
  bozulma eşiği).

**Panelin bugünkü tavsiyesi yetersiz.** `DocTypeFormView.vue:448` metni
`1600×400` diyor; 1920px ekranda bu **1,2× büyütülür**. Standart minimumu 1920'e
çekiyor. Bu bir düzeltme, keyfî bir artış değil.

### 3.2 Master

`master.max_long_edge = 2560`. Gerekçe: **kod tabanında zaten var olan en büyük
eşik** — `tradehub_core/media/presets.py:14` `safe` preset `max_dim: 2560`. Yeni
sayı üretilmedi.

2560, 1280px viewport'un @2x talebini (2560) tam karşılar; 1920px viewport'ta
1,33× rezerv verir. **1920 @2x (3840) bilinçli olarak karşılanmıyor:** 3840×800
bir banner PNG/JPEG olarak megabaytlara çıkar ve bant maliyeti görsel kazancı
aşar. Bu bir tercih; §8.3'te ölçülmesi gereken sayı yazılı.

### 3.3 Oran bandı ve güvenli alan — türetme

`object-cover`, oranı **R** olan görseli oranı **B** olan kutuda gösterirken:

- `R > B` → yatayda kırpar, görünen genişlik oranı = **B / R**
- `R < B` → dikeyde kırpar, görünen yükseklik oranı = **R / B**

Canlı kutunun oran aralığı **2,00 … 4,80** (§2.1). Önerilen R = **24:5 = 4,80**
(en geniş kutuyla birebir). En dar kutuda (B = 2,00):

```
görünen genişlik oranı = 2,00 / 4,80 = 0,417  →  %41,7
```

**Güvenli alan: görselin merkez %41,7'lik dikey şeridi.** Logo, telefon
numarası, slogan bu şeridin dışına çıkarsa mobilde kesilir. Dikeyde `cover` her
zaman tam yüksekliği kullanır (kutu yüksekliği sabit px), o yüzden dikey güvenli
alan %100.

Kabul bandı `2:1, 5:2, 3:1, 7:2, 4:1, 24:5` + `ratio_tolerance: 0.12` →
1,76 … 5,38 aralığını boşluksuz kaplar.

### 3.4 İki oran, tek dosya

Aynı kapak görseli hem **4,80:1**'lik banda hem `StoreHeader`'ın **16:9**'luk
kutusuna sokuluyor. Bu yüzden profil listesinde ayrı bir `cover_16x9_1000` var.
Tek orana indirgeme **yapılmadı** çünkü ikisi de canlı.

---

## 4. Profiller

| Profil | Genişlik | Biçim | Karşıladığı kutu | Türetme | Aşırı yük |
|---|---|---|---|---|---|
| `cover_768` | 768 | avif+webp | 360-430 @2x, 640 @1x | 360·2 = 720 → 768 | 1,20× |
| `cover_1280` | 1280 | avif+webp | 640 @2x, 768/1024/1280 @1x | max(1280, 1280) | 1,00× |
| `cover_1920` | 1920 | avif+webp | 1440/1536/1920 @1x, 768 @2x | max(1920, 1536) | 1,00× |
| `cover_2560` | 2560 | avif+webp | 1280 @2x, master | 1280·2 = 2560; tavan `presets.py:14` | 1,00× |
| `cover_16x9_1000` | 1000×563 | avif+webp | `StoreHeader.ts:296` (500 CSS px @2x) | 500·2 = 1000; 1000·9/16 = 563 | 1,00× |

Hepsi `fit: cover`, `target_ratio: 24:5` (16:9 profili hariç).
`encoder_quality.avif` **null** — kalibre edilmedi, bu yüzden politika
`active` olamaz (şema kuralı).

---

## 5. Kabul kuralları ve mevcut kodda karşılığı

| Kural | Değer | Kaynak | Bugün var mı |
|---|---|---|---|
| MIME | jpeg/png/webp | `ProfileImageDropzone.vue:122` | Yalnız `accept` süzgeci (doğrulama değil) |
| Boyut | **5 MB** | `ProfileImageDropzone.vue:123` | Bu yolda ✅ / `StorefrontEdit.vue:252-258` yolunda ❌ |
| Adet | statik 1, slider ≤5 | ÖNERİ | ❌ `LayoutSectionCard.vue:195-199` `multiple`, adet kontrolü yok |
| Erişim | public **zorunlu** | — | ❌ `DocTypeFormView.vue:2306` her dosyayı `is_private=1` yapıyor |
| Oran / boyut | §3 | — | ❌ hiçbir slotta yok (§7-B B2) |
| Animasyon | reddet | `engine.py:106` | motor işlemiyor, kabul ediliyor |

### Panel içi oran çelişkisi

`ProfileImageDropzone.vue:135` dikdörtgen önizlemeyi
`w-full sm:w-64 h-36` = **256×144 = 16:9** çiziyor.
Aynı bileşenin `recommendedSize` metni ise **1600×400 = 4:1**
(`DocTypeFormView.vue:448`).
Satıcıya 4:1 yüklemesi söyleniyor, 16:9 önizleme gösteriliyor, gerçek kutu ise
1920px'te 4,8:1.

---

## 6. İhlal aksiyonu

| Kural | Aksiyon | Kod | Bugün |
|---|---|---|---|
| MIME/uzantı dışı | `reject` | `upload_ext_not_allowed` | kısmen |
| > 5 MB | `reject` | `upload_too_large` | kısmen |
| Güvenli alan dışı içerik | `warn` | `guvenli_alan_disi` | ❌ |
| `is_private=1` | **`reject`** | `gizli_yuklendi` | ❌ |
| Uzun kenar < 1920 | `warn` | `tavsiye_altinda` | ❌ |
| Uzun kenar < 960 | `reject` | `cok_kucuk` | ❌ |
| CSS background ile basılıyor | `review` | `css_background_kisiti` | ❌ |

`on_violation.default = reject`, `require = warn`, `master = auto_fix`,
`error_code_prefix = upload`, `retryable = false`
(`upload_policy.py:97-100,104-139` sözleşmesiyle uyumlu).

---

## 7. Zaten çözülmüş — üstüne yazılmayacak

1. **Tek kapı L0.** `hooks.py:227-252` → `utils/security.py:96` →
   `upload_policy.py:307`: yasak uzantı, dosya adı temizliği (140 karakter
   kırpma), boyut tavanı, ilk 512 baytta tehlikeli içerik taraması.
2. **Sunucu tarafı garanti-WebP.** `media/engine.py:147-181` `to_webp()` —
   Safari/iOS/Capacitor'da istemci WebP üretemediğinde sunucu tamamlıyor.
   "WebP'ye geçelim" bir Faz 2 maddesi **değildir**.
3. **EXIF yön düzeltmesi + ICC koruma.** `engine.py:114-116`. Telefondan
   çekilmiş yatay bandın yan yatmaması bu sayede.
4. **İstemci sıkıştırma.** `admin-panel/frontend/src/lib/media/compress.js`
   (browser-image-compression → WebP), dinamik import ile chunk ayrımı.
5. **Görsel yoksa gradient fallback.** `section-registry.ts:104-105`
   `onerror` ile `linear-gradient` + `minHeight: 300px` — boş banner sayfayı
   kırmıyor.
6. **Slider erişilebilirliği ve kontrolleri.** `section-registry.ts:185,188`
   önceki/sonraki butonları `aria-label` ile; pagination `:212`.
7. **Renk güvenliği.** `section-registry.ts` `safeHexColor()` bölüm arka plan
   rengini süzüyor (`:159,205,792`) — CSS injection kapatılmış.

---

## 8. ÜRETİMDE DOĞRULANMALI

Bu ortamda **hiçbir ölçüm yapılmadı** (Docker kapalı, üretim DB ve canlı site
erişimi yok). Tüm CSS kutu değerleri **kaynak koddan** okundu, tarayıcıda
ölçülmedi.

### 8.1 `header_bg_image` gerçekten var mı — ve `tr_tradehub` kurulu mu

```bash
docker compose exec backend bench --site istoc.localhost list-apps
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.get_installed_apps())
# Alan gerçekten bir doctype'ta mı:
print(frappe.db.sql("""
  select parent, fieldname, fieldtype from tabDocField
  where fieldname in ('header_bg_image','banner_image','cover_image','logo_radius')
""", as_dict=True))
PY
# Tarayıcıda: panel → Mağaza Düzenle → Network sekmesinde
#   /api/method/tr_tradehub.api.v1.seller.get_storefront
# isteğinin HTTP kodunu oku (200 mi 404 mü).
```

`header_bg_image` hiçbir doctype'ta yoksa `pages/seller-shop.ts:118-119`
**ölü koddur** ve bu politikadan çıkarılmalıdır.

### 8.2 `Admin Seller Profile.banner_image` ölü mü

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print("banner_image dolu:", frappe.db.count("Admin Seller Profile", {"banner_image": ["is","set"]}))
print("logo dolu:", frappe.db.count("Admin Seller Profile", {"logo": ["is","set"]}))
# LIVE_SOURCES eksiğinin bedeli:
from tradehub_core.media import usage
u = frappe.db.get_value("Admin Seller Profile", {"banner_image": ["is","set"]}, "banner_image")
print(u, usage.verdicts_for([u], deep=True) if u else "veri yok")
PY
```

`verdicts_for` "unused" derse bu görseller **silme adayı** demektir
(`usage.py:32-41` LIVE_SOURCES'ta yok).

### 8.3 Gerçek oran ve boyut dağılımı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from collections import Counter
from PIL import Image
oran, boyut = Counter(), []
for f in frappe.get_all("File",
        filters={"attached_to_field": ["in", ["banner_image","poster_image"]]},
        fields=["file_url","file_size"], limit_page_length=0):
    p = frappe.get_site_path("public", f.file_url.lstrip("/"))
    if not os.path.exists(p): continue
    try:
        with Image.open(p) as im:
            w, h = im.size
            oran[round(w/h, 2)] += 1
            boyut.append((w, h, f.file_size))
    except Exception: pass
print("oran histogramı:", oran.most_common(20))
print("1920'den küçük genişlik oranı:",
      sum(1 for w,_,_ in boyut if w < 1920), "/", len(boyut))
print("2,00-4,80 bandı dışı:",
      sum(1 for w,h,_ in boyut if not (2.0 <= w/h <= 4.8)), "/", len(boyut))
PY
```

Ölçülmesi gereken üç sayı:
1. **Bandın dışında kalan dosya oranı** — `ratio_tolerance: 0.12` gerçekçi mi.
2. **1920'den küçük genişlikteki dosya oranı** — minimumu 1920'e çekmenin
   kaç mağazayı etkileyeceği.
3. **Medyan bayt** — `cover_2560` profilinin bant maliyeti.

### 8.4 Panelden yüklenen kapaklar private mı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select is_private, count(*) c from tabFile
  where attached_to_field in ('banner_image','poster_image')
  group by is_private
""", as_dict=True))
PY
```

`is_private = 1` satırı varsa o kapaklar mağaza sayfasında **görünmüyor**
(`DocTypeFormView.vue:2306`, `docs/reports/00-upload-slot-envanteri.md` §9-M4).

### 8.5 Gerçek CSS kutu genişliği (tarayıcıda)

§2'deki tüm sayılar **hesaplanmıştır**. Kaydırma çubuğu ve tarayıcı yuvarlaması
sapma yaratır.

```js
// Canlı mağaza sayfasında, DevTools konsolu:
[...document.querySelectorAll('.storefront-dynamic-section[data-section-type="hero_banner"] img')]
  .map(i => ({ kutu_g: Math.round(i.getBoundingClientRect().width),
               kutu_y: Math.round(i.getBoundingClientRect().height),
               kutu_orani: (i.getBoundingClientRect().width / i.getBoundingClientRect().height).toFixed(2),
               dosya_g: i.naturalWidth, dosya_y: i.naturalHeight,
               dosya_orani: (i.naturalWidth / i.naturalHeight).toFixed(2),
               dpr: devicePixelRatio,
               israf: (i.naturalWidth / (i.getBoundingClientRect().width * devicePixelRatio)).toFixed(2),
               gorunen_kesit: (i.getBoundingClientRect().width / i.getBoundingClientRect().height
                               / (i.naturalWidth / i.naturalHeight)).toFixed(2) }))

// StoreHeader 16:9 kutusu:
(() => { const e = document.querySelector('.aspect-video img, .aspect-video video');
  return e ? { g: e.getBoundingClientRect().width, y: e.getBoundingClientRect().height } : null; })()
```

`gorunen_kesit < 0.42` olan her satır, güvenli alan kuralının o dosyada
ihlal edildiğini gösterir.

### 8.6 Ölçülemeyen ve kasıtlı boş bırakılanlar

| Konu | Neden |
|---|---|
| LCP değeri (banner LCP adayı mı) | Tarayıcı + canlı site erişimi yok |
| Banner başına indirilen bayt | Ağ ölçümü gerektirir |
| `master.colorspace: srgb` renk kayması riski | Üretim görselleriyle görsel karşılaştırma gerektirir; bu bir **değişiklik önerisi**, mevcut davranış `preserve` (`engine.py:114-116`) |
| AVIF encoder kalitesi | Kalibrasyon koşumu gerektirir; `encoder_quality.avif` **null** |
| Slider slayt adedi üst sınırı (5) | Ürün kararı, ölçüm değil |
