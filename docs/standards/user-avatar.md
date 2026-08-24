# Standart — `user.avatar` (Kullanıcı profil fotoğrafı)

> **Güncel karar — 2026-08-23.** Makine kaynağı
> `tradehub_core/media/pipeline/policy/slots/user-avatar.json` şemaya uyumludur;
> `standard_status=fixed`, açık soru sayısı 0 ve yeni yükleme standardı
> sabittir. Mevcut 6 referansın tamamı harici URL olduğundan geriye dönük
> piksel ölçümü yapılamaz. `status=draft` yalnız Faz 3 rollout durumudur.

**Görev:** T-023 · **Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/user-avatar.json`
**Tarihsel durum:** `draft` — geometri kuralı kodda yoktu; **kabul kuralları zaten
uygulanıyor** (aşağıda).

> Bu slot iki uçta birden ilginç: kod tabanının **tek gerçek çift doğrulamalı
> görsel slotu** (uzantı + boyut hem sunucuda hem iki istemcide, üç yerde de
> **aynı sayı**), ama aynı zamanda **en büyük ölçülebilir israfın** olduğu yer
> (en büyük kutu 72 CSS px, dosya tavanı 5 MB, optimizasyon **çağrılmıyor**).

---

## 1. Kaynak alan ve uç

| | |
|---|---|
| **Alan** | `User.user_image` — Frappe **çekirdek** doctype'ı |
| **Yazan** | `tradehub_core/api/v1/identity.py:966` `frappe.db.set_value("User", user, "user_image", file_doc.file_url)` |
| **Uç** | `tradehub_core.api.v1.identity.update_profile_image` (`identity.py:920-971`) |
| **Rate limit** | 10 istek / 300 sn (`identity.py:921`) |
| **Gövde** | `filename` + `filedata` (base64; data-URI öneki soyuluyor, `:945-946`) |
| **File doc** | `is_private: 0`, `attached_to_doctype: "User"`, `attached_to_name: <session user>` (`:955-965`) |

> `User` bir `tradehub_core` doctype'ı **olmadığı** için
> `docs/reports/00-upload-slot-envanteri.md`'nin 41 alanlık Attach taramasında
> **çıkmaz**. §5'teki "Kullanıcı avatarı" satırı bunu not ediyor. Slot envanteri
> 41 değil **42 alan** üzerinden düşünülmelidir.

---

## 2. Render konumları ve gerçek CSS kutuları

| # | Render noktası | Dosya:satır | CSS kutu | `w/h` attr | Şekil |
|---|---|---|---|---|---|
| A1 | Ayarlar profil başlığı (storefront) | `components/settings/SettingsLayout.ts:98` | **72×72** (`size-[72px]`); mobil **48×48** (`max-sm:size-12`) | 64×64 (`:99`) | daire, `object-cover` |
| A2 | Ayarlar hesap düzenleme | `components/settings/SettingsAccountEdit.ts:223,335` | 64×64 (`w-16 h-16`) | 64×64 | daire |
| A3 | Mesaj listesi | `components/messages/MessageList.ts:100` | 40×40 (`w-10 h-10`) | 40×40 | daire, `lazy` |
| A4 | Mesaj içeriği başlığı | `components/messages/MessageContent.ts:81` | 36×36 (`w-9 h-9`) | 36×36 | daire |
| A5 | Mesaj balonu avatarı | `components/messages/MessageContent.ts:128` | 28×28 (`w-7 h-7`) | 28×28 | daire |
| A6 | Sohbet gelen kutusu | `components/chat-popup/InboxPanel.ts:71` | 40×40 | 40×40 | daire |
| A7 | Sohbet başlığı | `components/chat-shared/ChatHeader.ts:31` | 40×40 (attr) | 40×40 | daire |
| A8 | Panel IconRail avatarı | `admin-panel/.../components/layout/IconRail.vue:45` | 36×36 (`w-9 h-9`) | — | daire |
| — | Ürün yorumu "avatarı" | `components/product/ProductReviews.ts:315` | 28×28 | — | **görsel YOK** — baş harf + üretilmiş renk |

**En büyük kutu = 72 CSS px.** Sistemde 72'den büyük hiçbir avatar yüzeyi yok.
Bulunan 8 gerçek render'ın **tamamı** kare kutu + `rounded-full` +
`object-cover` — istisna yok.

Son satır önemli: ürün yorumlarında avatar **dosyası hiç inmiyor**
(`avatarColor(review.author)` ile üretilmiş arka plan + baş harf). Yani avatar
trafiği yorum listelerinde **sıfır**.

### Attribute tutarsızlığı

`SettingsLayout.ts:99` `width="64" height="64"` yazıyor, kutu ise
`size-[72px]` (`:98`). Tarayıcı 64×64 rezerve edip 72×72 boyar. CLS riski **yok**
(kap sabit px) ama attribute yanlış.

---

## 3. DPR ihtiyacı → minimum piksel

| Kutu (CSS px) | @1x | @2x | @3x |
|---|---|---|---|
| 28 (A5) | 28 | 56 | 84 |
| 36 (A4, A8) | 36 | 72 | 108 |
| 40 (A3, A6, A7) | 40 | 80 | 120 |
| 48 (A1 mobil) | 48 | 96 | 144 |
| 64 (A2) | 64 | 128 | 192 |
| **72 (A1)** | 72 | 144 | **216** |

**En yüksek talep: 216 px** (72 × DPR3).

| Alan | Değer | Türetme |
|---|---|---|
| `require.min_short_edge` | **96** | En büyük kutu 72; 96 üstündeki ilk yuvarlak değer ve 64 px kutusunun @1,5x'i. Bunun altı 72px kutuda büyütme demek |
| `require.min_area` | **9.216** | 96 × 96 |
| `master.max_long_edge` | **256** | 72 × DPR3 = 216 → üst basamak 256. **256 üstünde hiçbir avatar yüzeyinin talebi yok** |
| `master.max_megapixels` | **0,0655** | 256² / 1e6 = 0,065536 → **aşağı** yuvarlandı (yukarı yuvarlansaydı şema invaryantı `max_long_edge² / 1e6 ≥ max_megapixels` kırılırdı) |
| `content_rules.long_edge > 256 → auto_fix` | **256** | Aynı hesap |

### İsrafın büyüklüğü

Kabul edilen tavan 5 MB (`identity.py:952`), en küçük kutu 28 CSS px.
Bir 4000×3000 fotoğraf 36 px'lik sohbet avatarına indiğinde:

```
4000 / (36 × 3) = 37 kat fazla piksel genişliği
```

Ve bu dosya **küçültülmüyor** (§5).

### Oran — zorunlu, tolerans %2

`require.allowed_ratios: ["1:1"]`, `ratio_tolerance: 0.02`.
Gerekçe: 8 render'ın tamamı kare + daire maske. ±%2, 256×255 gibi
kırpma/encoder yuvarlamalarını geçirir, 4:3'ü geçirmez.

### Daire maskesi güvenli alanı — türetme

Bir dairenin içine yazılabilen en büyük karenin kenarı çapın `1/√2` katıdır:

```
1 / 1,41421 = 0,7071  →  %70,7
```

**Yüz veya logo görselin merkez %70,7 × %70,7'lik karesinde olmalı.**
Köşeler `rounded-full` ile **her zaman** maskelenir. Politikada
`circle_inscribed_square_fraction`, eşik `0.707`, aksiyon `warn`.

---

## 4. Profiller

| Profil | Genişlik | Karşıladığı kutu | Türetme | Aşırı yük |
|---|---|---|---|---|
| `avatar_96` | 96 | A5 @3x (84), A4/A8 @2x (72), A3/A6/A7 @2x (80), A1-mobil @2x (96) | max(84, 72, 80, 96) = 96 | 1,14× |
| `avatar_160` | 160 | A4/A8 @3x (108), A1-mobil @3x (144), A2 @2x (128), A1 @2x (144) | max(108, 144, 128, 144) = 144 → 160 | 1,11× |
| `avatar_256` | 256 | A1 @3x (216), A2 @3x (192); master | max(216, 192) = 216 → 256 | 1,19× |

Hepsi `webp`, `fit: cover`, `target_ratio: 1:1`, `encoder_quality.webp: 82`.

**82 nereden:** `tradehub_core/media/presets.py:16` `aggressive` preset
`quality: 82`. Avatar en küçük yüzey ve kalite riski en düşük slot; kod
tabanında var olan en agresif değer seçildi. **ÖLÇÜLMEDİ:** 96 px'lik bir
avatarda 82 ile 88 arasındaki görsel/SSIM farkı ölçülmedi (§8.5).

AVIF **kullanılmadı**: 96-256 px'lik bir görselde AVIF'in başlık ek yükü
kazancı yiyor. Bu bir tercih; `catbanner`/`cover` profillerinde AVIF var.

---

## 5. Kabul kuralları ve mevcut kodda karşılığı

### 5.1 ZATEN UYGULANANLAR — dokunulmayacak

| Kural | Değer | Sunucu | Storefront istemcisi | Panel istemcisi |
|---|---|---|---|---|
| Uzantı allowlist | `.jpg .jpeg .png .webp .gif` | `identity.py:939` | — | — |
| MIME allowlist | `image/(jpeg\|png\|webp\|gif)` | — | `alpine/settings.ts:76` | `stores/auth.js:201-206` |
| Boyut tavanı | **5 MB** | `identity.py:952-953` | `alpine/settings.ts:81` | `stores/auth.js:201-206` |
| Rate limit | 10 / 300 sn | `identity.py:921` | — | — |
| base64 doğrulama | çözülemezse ret | `identity.py:948-950` | — | — |
| Erişim | `is_private: 0` | `identity.py:960` | — | — |

**Üç yerde de aynı sayı (5 MB).** Kod tabanında bu tutarlılığın olduğu **tek**
slot. `docs/reports/00-upload-slot-envanteri.md` §1'e göre yalnız 3 uçta L1
(uca özel sunucu doğrulaması) var — bu onlardan biri.

### 5.2 Standardın DEĞİŞTİRDİĞİ tek kural: `.gif`

`identity.py:939` `.gif`'i kabul ediyor. Ama:

```
media/engine.py:106   if getattr(im, "is_animated", False):
                          return OptimizeResult(ok=False, reason="animated")
media/gates.py:68-69  aynı kapı (Kapı 3)
```

→ **animasyonlu GIF hiç işlenmez, olduğu gibi saklanır.** 5 MB'lık animasyonlu
bir GIF 36 px'lik bir sohbet avatarında servis edilebilir.

Standart `.gif`'i `accept` listesinden **çıkarır** ve mevcut kayıtlar için
`is_animated → auto_fix` (ilk kareyi al, statik WebP üret) önerir.

### 5.3 EKSİK: magic-byte kontrolü

`identity.py:939-941` yalnız **uzantıya** bakıyor. Karşılaştırma:
`tradehub_core/api/v1/kyb.py:23-58` aynı işi magic-byte ile yapıyor ve
uzantı/içerik eşleşmesini doğruluyor (`kyb.py:460-478`).

L0'ın tehlikeli içerik taraması (`upload_policy.py:187-224` — ilk 512 baytta
`<html`, `<svg`, `<script`, `<?xml`, `<%`, `#!/`) devrede, ama uzantı/içerik
uyuşmazlığı **yalnız uyarı** (`upload_policy.py:366-369`).

Politikada `magic_byte_matches_extension → reject`.

### 5.4 EKSİK VE EN PAHALI: optimizasyon çağrılmıyor

```
identity.py:955-966   File kaydı DOĞRUDAN açılıyor
                      engine.optimize()  ÇAĞRILMIYOR
                      engine.to_webp()   ÇAĞRILMIYOR
```

Ayrıca optimizasyon hattına girse bile `media/gates.py:57` **Kapı 1**
(`presets.py:23` `MIN_FILE_SIZE = 200 KB`) 200 KB altını atlar — ki avatar için
doğru olan da bu değil: 200 KB'lık bir dosya 72 px'lik kutu için **hâlâ**
gereğinden büyük.

Politikada `optimizer_ran → review`. §8.2'de ölçüm komutu var.

---

## 6. İhlal aksiyonu

`on_violation`: `default: reject`, `accept: reject`, **`require: reject`**,
`master: auto_fix`, `content_rules: warn`,
`error_code_prefix: upload`, `retryable: false`.

| Kural | Aksiyon | Bugün |
|---|---|---|
| Uzantı listede değil | `reject` | ✅ `identity.py:940-941` (kodsuz `frappe.throw`) |
| MIME listede değil | `reject` | ✅ istemcide |
| > 5 MB | `reject` | ✅ üç yerde |
| base64 çözülemedi | `reject` | ✅ `identity.py:948-950` |
| Oran 1:1 değil | **`reject`** | ❌ — bugün sessizce merkezden kırpılıyor |
| Kısa kenar < 96 | `reject` | ❌ |
| Uzun kenar > 256 | `auto_fix` | ❌ |
| Animasyonlu | `auto_fix` (ilk kare) | ❌ `engine.py:106` dosyaya hiç dokunmuyor |
| Magic-byte uyuşmuyor | `reject` | ❌ |
| Optimize edilmedi | `review` | ❌ |
| Daire maskesi güvenli alanı | `warn` | ❌ |

**Neden `require: reject`** (diğer slotlarda `warn`): 1:1 dışı bir avatar daire
maskede **sistematik olarak** bozuk görünür ve düzeltmesi kullanıcı için kolay
(kare kırpma). Belge slotunda tersine `warn` seçildi çünkü orada ret çalışan bir
akışı kırıyor.

### Kod sözleşmesi uyumsuzluğu

`identity.py` `upload_policy.py:104-139`'daki **kodlu ret sözleşmesini
kullanmıyor**; düz metin fırlatıyor (`:940`, `:952`). İstemci koda değil metne
bakmak zorunda — çeviri değişince kırılan bir sözleşme.

---

## 7. Zaten çözülmüş — üstüne yazılmayacak

1. **İki taraflı kabul doğrulaması ve sayı tutarlılığı** (§5.1).
2. **Rate limit** 10/300 sn (`identity.py:921`) — avatar spam'ine karşı korunmuş.
3. **Cache-buster.** `alpine/settings.ts:126`:
   `nextUrl + (nextUrl.includes("?") ? "&" : "?") + "t=" + Date.now()`
   → avatar değişince tarayıcı eski dosyayı göstermiyor. **İleride CDN
   eklenirse bu sorun zaten çözülmüş demektir.**
4. **File kaydı `User`'a attach ediliyor** (`identity.py:962-964`) →
   `media/usage.py` silme kararında sahipsiz görünmüyor.
5. **Yükleme ilerleme çubuğu** KYC/KYB/SlotDropzone ile aynı UX değerlerinde
   (tick 100 ms, +%10-18, cap %85, success hold 350 ms —
   `alpine/settings.ts:89-95` yorumu). Tutarlı.
6. **Yükleme yolu değişikliği gerekmez:** aynı uç hem storefront hem panel
   tarafından kullanılıyor (`alpine/settings.ts:111`,
   `stores/auth.js:199-218`) — `docs/reports/00-upload-slot-envanteri.md`
   Tablo C `panel.user_avatar` satırı bunu "tutarlı" olarak işaretlemiş.
7. **Avatar yoksa fallback:** baş harf + gradient (`SettingsLayout.ts:100-104`)
   — boş avatar arayüzü kırmıyor.

---

## 8. ÜRETİMDE DOĞRULANMALI

Bu ortamda **hiçbir ölçüm yapılmadı** (Docker kapalı, üretim DB ve canlı site
erişimi yok). CSS kutu değerleri kaynak koddan okundu.

### 8.1 Kaç avatar var, ne kadar yer tutuyor

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print("user_image dolu:", frappe.db.count("User", {"user_image": ["is","set"]}))
print(frappe.db.sql("""
  select count(*) adet, sum(file_size) toplam_bayt,
         round(avg(file_size)) ort_bayt, max(file_size) en_buyuk
  from tabFile where attached_to_doctype = 'User'
""", as_dict=True))
PY
```

### 8.2 İSRAFIN GERÇEK ÖLÇÜSÜ — 256 pikselden büyük avatarlar

Bu, bu slottaki tek en önemli sayıdır.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from PIL import Image
buyuk = kucuk = kare_degil = animasyonlu = toplam = 0
bayt_israf = 0
for f in frappe.get_all("File", filters={"attached_to_doctype": "User"},
                        fields=["file_url","file_size"], limit_page_length=0):
    p = frappe.get_site_path("public", f.file_url.lstrip("/"))
    if not os.path.exists(p): continue
    try:
        with Image.open(p) as im:
            w, h = im.size
            toplam += 1
            if max(w, h) > 256:
                buyuk += 1
                # 256'ya küçültülse tahmini kazanç (piksel oranıyla lineer varsayım)
                bayt_israf += (f.file_size or 0) * (1 - (256*256) / (w*h))
            if max(w, h) < 96: kucuk += 1
            if abs(w/h - 1) > 0.02: kare_degil += 1
            if getattr(im, "is_animated", False): animasyonlu += 1
    except Exception: pass
print(f"toplam={toplam} >256px={buyuk} <96px={kucuk} kare_degil={kare_degil} animasyonlu={animasyonlu}")
print(f"256'ya küçültme ile tahmini kazanç: {bayt_israf/1024/1024:.1f} MB (lineer varsayım — GERÇEK DEĞİL)")
PY
```

> `bayt_israf` **tahmindir**, ölçüm değil: piksel sayısı ile dosya boyutunun
> lineer olduğu varsayılmıştır. Gerçek kazanç için dosyaların 256'ya
> küçültülüp yeniden encode edilmesi ve boyutların karşılaştırılması gerekir.

### 8.3 Optimizasyon gerçekten atlanıyor mu

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select case when th_optimized_at is null then 'OPTIMIZE EDILMEDI' else 'OPTIMIZE EDILDI' end d,
         count(*) c
  from tabFile where attached_to_doctype = 'User' group by 1
""", as_dict=True))
PY
```

Beklenti: **tamamı "OPTIMIZE EDILMEDI"** — `identity.py:955-966` engine'i hiç
çağırmıyor. Aksi çıkarsa başka bir yol (bulk optimize job'ı) avatarlara
dokunuyor demektir ve o yol bulunmalıdır.

### 8.4 GPS EXIF sızıntısı — KVKK

Avatar ucu engine'e hiç girmediği için EXIF bloğu **olduğu gibi** saklanıyor.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
from PIL import Image
from PIL.ExifTags import GPSTAQS if False else None  # bkz. not
gpsli = toplam = 0
for f in frappe.get_all("File", filters={"attached_to_doctype": "User"},
                        fields=["file_url"], limit_page_length=0):
    p = frappe.get_site_path("public", f.file_url.lstrip("/"))
    if not os.path.exists(p): continue
    try:
        with Image.open(p) as im:
            toplam += 1
            ex = im.getexif()
            # 34853 = GPSInfo IFD etiketi
            if ex and 34853 in ex: gpsli += 1
    except Exception: pass
print(f"GPS bilgisi taşıyan avatar: {gpsli} / {toplam}")
PY
```

> Yukarıdaki `from PIL.ExifTags import ...` satırı kasıtlı olarak devre dışı;
> GPS IFD etiketi (34853) doğrudan sayı olarak kontrol ediliyor. Alternatif:
> `exiftool -gpslatitude -gpslongitude -r <site>/public/files/`.

`gpsli > 0` ise bu bir KVKK bulgusudur ve
`master.strip_metadata.gps = true` kuralı acil hâle gelir.

### 8.5 Encoder kalitesi kalibrasyonu (82 doğru mu)

```bash
# Üretimden 20 avatar örneği alıp 96/160/256 px × q78/82/88 matrisini üret,
# SSIM ile karşılaştır:
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, os
rows = frappe.get_all("File", filters={"attached_to_doctype":"User"},
                      fields=["file_url"], limit_page_length=20)
for r in rows:
    print(frappe.get_site_path("public", r.file_url.lstrip("/")))
PY
# Ardından (ImageMagick + Python skimage ile):
#   for q in 78 82 88; do for w in 96 160 256; do
#     magick "$f" -resize ${w}x${w}^ -gravity center -extent ${w}x${w} -quality $q out_${w}_${q}.webp
#   done; done
# ve her çıktı için SSIM hesapla (hedef: photo >= 0.96)
```

### 8.6 Gerçek CSS kutuları (tarayıcıda)

```js
// Ayarlar sayfasında (storefront), DevTools konsolu:
[...document.querySelectorAll('img')]
  .filter(i => getComputedStyle(i.parentElement).borderRadius.includes('9999')
             || i.closest('[class*="rounded-full"]'))
  .map(i => ({ kutu: Math.round(i.getBoundingClientRect().width),
               dosya: i.naturalWidth,
               dpr: devicePixelRatio,
               israf: (i.naturalWidth / (i.getBoundingClientRect().width * devicePixelRatio)).toFixed(1) }))
  .sort((a,b) => b.israf - a.israf)
```

`israf` sütunu bu slotta muhtemelen **10'un üzerinde** çıkacaktır; §8.2'nin
tarayıcı tarafındaki doğrulamasıdır.

### 8.7 Ölçülemeyen ve kasıtlı boş bırakılanlar

| Konu | Neden |
|---|---|
| Avatar kaynaklı toplam bant maliyeti | Ağ/CDN ölçümü gerektirir |
| Gerçek DPR dağılımı | RUM/analytics erişimi gerektirir; §3 tablosu **kapasite planıdır**, trafik ağırlığı değil |
| `encoder_quality.webp: 82` doğruluğu | Kalibrasyon koşumu gerektirir (§8.5) |
| `master.colorspace: srgb` renk kayması | Mevcut davranış `preserve` (`engine.py:114-116`); bu bir **değişiklik önerisi** |
| Sohbet avatarlarının `User.user_image`'dan mı geldiği | API yanıtı incelenmeli: `conv.avatar` alanının kaynağı (`components/messages/MessageList.ts:100`) bu repoda izlenemedi |
