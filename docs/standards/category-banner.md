# Standart — `category.banner` (Kategori bandı / kategori vitrin görseli)

> **Güncel karar — 2026-08-23.** Makine kaynağı
> `tradehub_core/media/pipeline/policy/slots/category-banner.json` şemaya
> uyumludur; `standard_status=fixed`, açık soru sayısı 0 ve AVIF kalitesi
> 61'dir. Gerçek bağ 6 adet 1×1, 1 adet 2×1 ve 1 adet 2×2 vitrin döşemesiyle
> ölçülmüştür. Aşağıdaki 2026-08-17 `null`/“okunmuyor” notları tarihsel
> analizdir; `status=draft` yalnız Faz 3 rollout durumudur.

**Görev:** T-023 · **Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/category-banner.json`
**Tarihsel durum:** `draft` + eksik alan incelemesi — 2026-08-17 anlık görüntüsü
(`tradehub_core/media/upload_policy.py:307-313`).

> **Bu slotun en önemli bulgusu bir yokluk:** banner biçimindeki tek render
> **ölü kod** ve **backend alanı yok**. Bugün canlıda "kategori görseli" olarak
> çalışan iki şey var ve ikisi de banner değil. Standart bu yüzden hayali bandın
> değil, **canlı bento döşemesinin** geometrisine göre yazıldı.

---

## 1. Üç ayrı kavram — var/yok karnesi

`docs/reports/00-upload-slot-envanteri.md` §5 satırı bunu "İKİ AYRI KAVRAM"
olarak işaretlemişti; daha yakından bakıldığında **dört** durum var:

| # | Kavram | Alan | Render | Canlı |
|---|---|---|---|---|
| a | **Bento döşeme** | `Category Showcase Tile.image` (Attach Image) | `components/category/CategoryShowcase.ts:152-154`, grid `:245` | ✅ **tek canlı kategori medyası** |
| b | **Daire ikon** | `Product Category.image` (Attach Image) | `components/categories/CategoryGrid.ts:14-18`, `hero/MobileCategoryBar.ts:21-25`, `hero/CategoryBrowse.ts:20` | ✅ ama **banner değil** — 42/52/60/68/80/96/112/128 px `rounded-full` |
| c | **Marka bandı** | `Brand.hero_banner` (Attach Image, `brand.json:107`) | `pages/brand.ts:145-148` — CSS `background`, `<img>` değil | ✅ (kategori değil, marka) |
| d | **Kategori bandı** | **YOK** | `components/seller/CategoryProductListing.ts:88-90` | ❌ **ölü + alansız** |

### (d) kanıtı

```bash
# Tip yalnız tanımda:
grep -rn "bannerImage" /Users/ahmet/Desktop/istoc/tradehubfront/src
#  → types/seller/types.ts:119            (tip alanı)
#  → components/seller/CategoryProductListing.ts:88   (kullanım)
#  → data/seller/mockData.ts:286,411      (MOCK veri)

# Bileşen hiçbir sayfada mount edilmiyor:
grep -rn "CategoryProductListing" /Users/ahmet/Desktop/istoc/tradehubfront/src
#  → yalnız kendi dosyası ve components/seller/index.ts:11 (barrel)

# Backend'de karşılığı yok:
python3 - <<'EOF'
import json
d = json.load(open('/Users/ahmet/Desktop/istoc-medya-wt/tradehub_core/tradehub_core/doctype/product_category/product_category.json'))
print([f['fieldname'] for f in d['fields'] if f['fieldtype'] in ('Attach','Attach Image','Image')])
EOF
#  → ['image']     yalnız daire ikon alanı
```

**Sonuç:** "kategori banner" arayüzde tasarlanmış, veri modelinde hiç
yaratılmamış. Ürün kararı gerekiyor: alan yaratılacak mı, bileşen silinecek mi?
(§8.1)

### (b) kapsam dışı

`Product Category.image` daire ikondur ve **ayrı bir slot** (`category.icon`)
gerektirir. Bu belge onu yalnız karışmasın diye kaydeder. Aynı dosya 6 farklı
ölçüde servis ediliyor ve tek boy üretiliyor
(`docs/reports/00-upload-slot-envanteri.md` §7-B B3).

---

## 2. Canlı render — bento döşemesi ve gerçek CSS kutuları

`components/category/CategoryShowcase.ts:245`:

```
grid grid-cols-2 {lg:grid-cols-3..6} {2xl:grid-cols-5,6}
gap-2 sm:gap-4
auto-rows-[85px] sm:auto-rows-[145px] lg:auto-rows-[210px]
grid-flow-row-dense
```

Görsel (`:152-154`): `absolute inset-0 h-full w-full object-cover`,
attr `400×400`, `loading="lazy" decoding="async"`.
Span sınıfları `spanClasses(col_span, row_span, columns)` (`:137`).

Kapsayıcı = `container-boxed`: `min(1840, W) − (W ≥ 1536 ? 64 : 32)`
(`docs/reports/03-render-envanteri.md` §1.2). Kırılımlar `sm=480`, `md=640`,
`lg=768`, `xl=1024` (`tradehubfront/src/style.css:256-260`).

### Ölçülen kutular (`columns = 4`)

| Viewport | Sütun | Satır y. | 1×1 | 2×1 | 2×2 |
|---|---|---|---|---|---|
| 360 | 2 | 85 | 160×85 (1,88:1) | 328×85 (3,86:1) | 328×178 (1,84:1) |
| 390 | 2 | 85 | 175×85 (2,06:1) | 358×85 (4,21:1) | 358×178 (2,01:1) |
| 430 | 2 | 85 | 195×85 (2,29:1) | **398×85 (4,68:1)** | 398×178 (2,24:1) |
| 640 | 2 | 145 | 296×145 (2,04:1) | 608×145 (4,19:1) | 608×306 (1,99:1) |
| 768 | 4 | 210 | **172×210 (0,82:1)** | 360×210 (1,71:1) | 360×436 (0,83:1) |
| 1024 | 4 | 210 | 236×210 (1,12:1) | 488×210 (2,32:1) | 488×436 (1,12:1) |
| 1280 | 4 | 210 | 300×210 (1,43:1) | 616×210 (2,93:1) | 616×436 (1,41:1) |
| 1536 | 4 | 210 | 356×210 (1,70:1) | 728×210 (3,47:1) | 728×436 (1,67:1) |
| 1920 | 4 | 210 | 432×210 (2,06:1) | **880×210 (4,19:1)** | 880×436 (2,02:1) |

**En büyük kutu:** 2×1 @1920 = **880×210**; en yüksek kutu 2×2 @1920 = 880×436.
**Oran aralığı: 0,82:1 … 4,68:1.**

> 768px'te 1×1 döşeme **dikey** (172×210), 430px'te aynı döşeme **yatay**
> (195×85). Aynı dosya hem portre hem manzara kutuya sokuluyor. Oranın niçin
> zorlanamayıp güvenli alanla yönetildiğinin gerekçesi budur.

---

## 3. DPR ihtiyacı → minimum piksel

### 3.1 Minimum kabul

| Alan | Değer | Türetme |
|---|---|---|
| `require.min_short_edge` | **480** | En yüksek kutu 2×2 @1920 = 880×**436**; 480'e yuvarlandı |
| `require.min_area` | **460.800** | 960 × 480 (2:1 oranda tutarlı) |
| `content_rules.long_edge < 960 → reject` | **960** | En geniş kutu 880 CSS px; 960 üstündeki ilk yuvarlak değer, @1x'i kesin karşılar |

### 3.2 Master

`master.max_long_edge = 2000` — `tradehub_core/media/presets.py:15`
`balanced` (varsayılan) preset `max_dim: 2000`; `engine.py:117`
`im.thumbnail((max_dim, max_dim))` uzun kenarı zaten buraya indiriyor.
**Yeni sayı üretilmedi.**

`master.min_long_edge = 1920` — en geniş kutu 880 CSS px @2x = 1760 → 1920.

### 3.3 Önerilen oran — türetme

`object-cover`, oranı **R** olan görseli oranı **B** olan kutuda gösterirken
görünen kesit oranı `min(B/R, R/B)`. Kutu aralığı **0,82 … 4,68**. En kötü
durumu **minimize eden** R, iki ucun geometrik ortalamasıdır:

```
R = sqrt(0,82 × 4,68) = sqrt(3,838) = 1,96
```

Bu R'de en kötü kesit her iki eksende **eşitlenir**:

```
en dar kutu (0,82):  0,82 / 1,96 = 0,418   → dikeyde %41,8 görünür
en geniş kutu (4,68): 1,96 / 4,68 = 0,419  → yatayda %41,9 görünür
```

**Önerilen oran ≈ 2:1. Güvenli alan: merkez %42 × %42.**
Kritik içerik (ürün, logo, metin) bu dikdörtgenin dışına çıkarsa bazı
viewport/span kombinasyonlarında kesilir.

Kabul bandı `5:4, 3:2, 16:9, 2:1, 5:2, 3:1` + `ratio_tolerance: 0.12` →
1,10 … 3,36 aralığını boşluksuz kaplar (önerilen 1,96'nın ±%40'lık pratik
toleransı).

---

## 4. Profiller

| Profil | Genişlik | Biçim | Karşıladığı kutu | Türetme | Aşırı yük |
|---|---|---|---|---|---|
| `catbanner_480` | 480 | avif+webp | 1×1 @360-430 @2x; 1×1 @640 @1x | max(195·2 = 390; 296) = 390 → 480 | 1,23× |
| `catbanner_960` | 960 | avif+webp | 2×1 @360-640; 1×1 @1920 @2x; 2×2 @1024 @2x | max(432·2 = 864; 488·2 = 976) → 960 (%1,7 eksik, kabul edilen sapma) | 1,11× |
| `catbanner_1920` | 1920 | avif+webp | 2×1 @1920 @2x; master | 880·2 = 1760 → 1920 | 1,09× |

Hepsi `fit: cover`, `target_ratio: 2:1`.
`encoder_quality.avif` **null** — kalibre edilmedi, politika `active` olamaz.

---

## 5. Kabul kuralları ve mevcut kodda karşılığı

| Kural | Değer | Kaynak | Bugün var mı |
|---|---|---|---|
| MIME | jpeg/png/webp | `upload_policy.py:60-62` kesişimi | ❌ panelde `accept="image/*"` (`CategoryManagementView.vue:924-928`) — hem geniş hem doğrulama değil |
| Boyut | **5 MB** | Kod tabanının fiili görsel taban çizgisi: `ProfileImageDropzone.vue:123`, `identity.py:952`, `WriteReviewModal.ts:23-26` | ❌ kategori görselinde hiç kontrol yok (§7-A) |
| Adet | 1 (alan tekil) | `00-upload-slot-envanteri.md` §2 | yapısal ✅ |
| Boyut/oran | §3 | — | ❌ (§7-B B2) |
| Animasyon | reddet | `engine.py:106` | motor işlemiyor, kabul ediliyor |

**5 MB nereden geliyor:** yeni bir sayı değil — kod tabanında görsel
slotlarında fiilen uygulanan tek tavan. Kategori görselinde bugün L0'ın 25 MB'ı
(`upload_policy.py:67`) dışında hiçbir sınır yok.

---

## 6. İhlal aksiyonu

| Kural | Aksiyon | Mesaj anahtarı | Bugün |
|---|---|---|---|
| MIME/uzantı dışı | `reject` | `bicim_desteklenmiyor` | ❌ |
| > 5 MB | `reject` | `cok_buyuk` | ❌ (L0 25 MB'da yakalar) |
| Uzun kenar < 960 | `reject` | `cok_kucuk` | ❌ |
| Güvenli alan dışı içerik | `warn` | `guvenli_alan_disi` | ❌ |
| Döşeme span'ı yükleme ekranında belli değil | `review` | `span_bilinmiyor` | ❌ — UI eksiği |
| CSS background ile basılıyor (`Brand.hero_banner`) | `review` | `css_background_kisiti` | ❌ (§7-B B4) |
| Görselin alt şeridinde metin | **`ignore`** | `alt_serit_gradient_var` | ✅ **ZATEN ÇÖZÜLMÜŞ** — ölç, uyarma |

Son satır önemli: "görselin alt %30'una önemli şey koyma" kuralı **yazılmamalı**,
çünkü `CategoryShowcase.ts:154` gradient scrim'i (`bg-gradient-to-t
from-black/75 via-black/25 to-transparent`) etiketi her görselde okunur kılıyor.

### `span_bilinmiyor` neden `review`

`CategoryShowcase.ts:137` (`spanClasses`) ve `:142-148` (etiket boyutu span'a
göre değişiyor) — **render tarafı span'ı biliyor**. Ama yükleme ekranı satıcıya
/ yöneticiye görselin 1×1, 2×1 mi 2×2 mi olacağını söylemiyor. Aynı dosya üç
orana kırpılıyor ve yükleyen sonucu görmüyor
(`docs/reports/00-upload-slot-envanteri.md` §7-B B2).

---

## 7. Zaten çözülmüş — üstüne yazılmayacak

1. **Gradient scrim ile etiket okunabilirliği.** `CategoryShowcase.ts:154`.
2. **Görsel yoksa tonal gri + koyu metin fallback'i.** `CategoryShowcase.ts:157-158`
   (`labelColor`/`hoverColor` görselin varlığına göre değişiyor).
3. **Bento hiyerarşisi.** `CategoryShowcase.ts:142-148` — hero (2×2) manşet,
   geniş (2×1) ara, standart (1×1) kompakt etiket boyutu. Ağırlık boyutla
   okunuyor.
4. **CLS koruması.** `width/height` attr `400×400` + sabit `auto-rows`
   yüksekliği → `docs/reports/03-render-envanteri.md` §5, **R12 "risk YOK"**.
5. **Boşluksuz dizilim.** `CategoryShowcase.ts:229-232` — 2xl'de sütun sayısı
   yalnız tile hücreleri tam bölünüyorsa artıyor, aksi hâlde base columns'ta
   kalıyor. Kısa tile'ların altında boş hücre bırakmıyor.
6. **URL güvenliği.** `sanitizeImageUrl` (`CategoryShowcase.ts:137`) +
   `sanitizeHref` (`:135`) + `escapeAttr`/`escapeText`.
7. **`loading="lazy"` + `decoding="async"`** zaten uygulanmış (`:152`).

---

## 8. ÜRETİMDE DOĞRULANMALI

Bu ortamda **hiçbir ölçüm yapılmadı** (Docker kapalı, üretim DB ve canlı site
erişimi yok). §2'deki tüm kutu değerleri **kaynak koddan hesaplandı**,
tarayıcıda ölçülmedi.

### 8.1 Kategori bandı alanı yaratılacak mı — ürün kararı + kanıt

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
# Kategori bandı taşıyabilecek bir alan var mı:
print(frappe.db.sql("""
  select parent, fieldname, fieldtype from tabDocField
  where fieldname like '%banner%' or fieldname like '%hero%' or fieldname like '%cover%'
""", as_dict=True))
PY
```

Sonuç boşsa `components/seller/CategoryProductListing.ts` **silinmeli** ya da
alan yaratılmalıdır. Bu bir ürün kararı, ölçüm değil.

### 8.2 Bento döşeme sayısı ve span dağılımı

Span dağılımı bilinmeden profil basamaklarının israfı ölçülemez.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select ifnull(col_span,1) cs, ifnull(row_span,1) rs, count(*) adet
  from `tabCategory Showcase Tile` group by 1,2 order by 3 desc
""", as_dict=True))
print("görselli döşeme:", frappe.db.count("Category Showcase Tile", {"image": ["is","set"]}))
print("toplam döşeme:", frappe.db.count("Category Showcase Tile"))
# Ayar tarafındaki sütun sayısı (profil hesabı columns=4 varsayımıyla yapıldı):
print(frappe.get_all("Category Showcase Settings", fields=["*"], limit_page_length=5))
PY
```

> **Uyarı:** §2 tablosu `columns = 4` varsayımıyla üretildi
> (`CategoryShowcase.ts:41-51` 3-6 sütunu destekliyor,
> `COLUMN_CLASSES[data.columns] ?? COLUMN_CLASSES[4]` varsayılanı 4).
> Üretimde `columns` 5 veya 6 ise en geniş kutu 880'den küçülür ve
> `catbanner_1920` profili gereksiz hâle gelir.

### 8.3 Gerçek oran dağılımı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from collections import Counter
from PIL import Image
oran, kucuk, toplam = Counter(), 0, 0
for dt in ("Category Showcase Tile", "Product Category", "Seller Category", "Brand"):
    for f in frappe.get_all("File", filters={"attached_to_doctype": dt},
                            fields=["file_url"], limit_page_length=0):
        p = frappe.get_site_path("public", f.file_url.lstrip("/"))
        if not os.path.exists(p): continue
        try:
            with Image.open(p) as im:
                w, h = im.size
                oran[(dt, round(w/h, 2))] += 1
                toplam += 1
                if max(w, h) < 960: kucuk += 1
        except Exception: pass
print("oran histogramı:", oran.most_common(30))
print("960'tan küçük:", kucuk, "/", toplam)
PY
```

Ölçülmesi gereken üç sayı:
1. **1,10-3,36 bandı dışında kalan dosya oranı** — `ratio_tolerance: 0.12`
   gerçekçi mi.
2. **960'tan küçük dosya oranı** — `reject` eşiğinin kaç kaydı kıracağı.
3. **Bento ile daire ikon arasındaki oran farkı** — `Product Category.image`
   1:1 mi, yoksa 2:1 bento dosyaları oraya da mı konuluyor.

### 8.4 `Seller Category.image` ve diğer ölü adaylar

`docs/reports/00-upload-slot-envanteri.md` §9-M3 betiği bu alanı da sayıyor.
Kısa hâli:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
for dt, fld in [("Category Showcase Tile","image"), ("Product Category","image"),
                ("Seller Category","image"), ("Brand","hero_banner")]:
    print(f"{dt}.{fld}:", frappe.db.count(dt, {fld: ["is","set"]}))
PY
```

### 8.5 LIVE_SOURCES eksiğinin gerçek bedeli

`Category Showcase Tile.image` ve `Brand.hero_banner` `usage.py:32-41`
LIVE_SOURCES'ta **yok** → silme taramasında "kullanılmıyor" görünürler.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
from tradehub_core.media import usage
u = frappe.db.get_value("Category Showcase Tile", {"image": ["is","set"]}, "image")
print(u, usage.verdicts_for([u], deep=True) if u else "veri yok")
v = frappe.db.get_value("Brand", {"hero_banner": ["is","set"]}, "hero_banner")
print(v, usage.verdicts_for([v], deep=True) if v else "veri yok")
PY
```

### 8.6 Gerçek CSS kutuları (tarayıcıda)

```js
// Ana sayfada, DevTools konsolu:
[...document.querySelectorAll('[data-category-showcase-root] a')]
  .map(a => { const i = a.querySelector('img'); const r = a.getBoundingClientRect();
    return { kutu: Math.round(r.width) + '×' + Math.round(r.height),
             kutu_orani: (r.width / r.height).toFixed(2),
             dosya: i ? i.naturalWidth + '×' + i.naturalHeight : '(görselsiz)',
             dosya_orani: i && i.naturalHeight ? (i.naturalWidth / i.naturalHeight).toFixed(2) : null,
             gorunen_kesit: i && i.naturalHeight
               ? Math.min((r.width / r.height) / (i.naturalWidth / i.naturalHeight),
                          (i.naturalWidth / i.naturalHeight) / (r.width / r.height)).toFixed(2)
               : null,
             israf: i ? (i.naturalWidth / (r.width * devicePixelRatio)).toFixed(2) : null }; })

// Aynı ölçümü 360, 430, 768, 1920 px genişliklerde tekrarla (DevTools cihaz emülasyonu)
// ve §2 tablosuyla karşılaştır.
```

`gorunen_kesit < 0.42` olan her satır güvenli alan kuralının o dosyada ihlal
edildiğini gösterir. `israf > 1.2` olan her satır gereğinden büyük dosya
indirildiğini gösterir.

### 8.7 Ölçülemeyen ve kasıtlı boş bırakılanlar

| Konu | Neden |
|---|---|
| Bento döşemesinin LCP'ye katkısı | `docs/reports/03-render-envanteri.md` §7.1'de S1 olarak beklenen LCP adayı; **ölçülmedi** |
| Üretimdeki `columns` değeri | DB erişimi gerektirir; §2 tablosu `columns=4` varsayımıyla |
| AVIF encoder kalitesi | Kalibrasyon koşumu gerektirir; `encoder_quality.avif` **null** |
| `master.colorspace: srgb` renk kayması | Mevcut davranış `preserve` (`engine.py:114-116`); bu bir **değişiklik önerisi** |
| Kategori bandı alanı yaratılmalı mı | Ürün kararı, ölçüm değil |
