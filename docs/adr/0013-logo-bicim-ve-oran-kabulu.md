# ADR-0013 — Opak JPEG logo reddedilmez, uyarıyla kabul edilir; oran bandı 1:2…2:1 kalır

**Durum:** Kabul edildi · ikisi de **ölçümle** çözüldü (K1 öneriyi devirdi, K2 onayladı)
**Tarih:** 2026-08-18
**İlgili:** ADR-0012

---

## Bağlam

`docs/standards/logo.md` §13 altı karar taşıyordu; ikisi **sayısal bir tetik**
içeriyordu ("şu oran şu eşiği geçerse B"). Docker açılınca tetikler
`docs/reports/08-canli-olcum.md` §2 ile çalıştırıldı.

Ölçüm kümesi: `Admin Seller Profile.logo` (27) + `Brand.logo` (11) = **38
referans**; bunların **18'i diskte gerçek dosya** (18'i DB'ye gömülü `data:` URI —
hepsi demo seed, 2'si diskte yok). Aşağıdaki yüzdeler bu **18 dosyalık küme**
üzerinden.

## Seçenekler

### K1 — JPEG logo

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİ)** — RET, kod `logo_format_no_alpha` | Standart net. 16 render noktasının **11'i** logonun altına plaka koyuyor; opak beyaz JPEG bu plakaların üzerinde görünür dikdörtgen bırakır. S1 (`seller-shop.ts:124`) hiç plaka koymuyor. |
| **B (SEÇİLEN — ölçümle)** — Kabul + `logo_opaque_warning` + geçiş penceresi | Kimse engellenmez. Bedeli: 11 noktada görsel bozukluk kalıcı olur. |
| C — Kabul + sunucuda otomatik arka plan kaldırma | Otomatik matting gradyanlı/gölgeli logoda halka bırakır. **Ölçülmemiş** kalite riski; önerilmiyor. |

### K2 — oran bandı

| Seçenek | Sonuç |
|---|---|
| **A (SEÇİLEN — ölçüm onayladı)** — 1:2 … 2:1 | En küçük kutuda (32×32) 2:1 logo 32×16 px çizilir = platform logosunun kendi en küçük render'ıyla aynı okunabilirlik tabanı. |
| B — 1:4 … 4:1 + kutu ≤64 px için zorunlu kare "mark" varyantı | Geniş kelime markaları engellenmez. Bedeli: **iki dosya** — slot sayısı ikiye çıkar, panelde iki dropzone, motorda iki merdiven. |
| C — 1:4 … 4:1, ek varyant yok | 4:1 logo 32×32 kutuda 32×8 px → okunmaz. Önerilmiyor. |

## Karar

**K1 → B.** Tetik önceden yazılıydı: *"Bu oran %10'u geçerse karar B'ye çevrilmeli
ve bir geçiş penceresi tanımlanmalı."*

| Ölçüt | Değer | Tetik | Sonuç |
|---|---:|---|---|
| **JPEG payı** | **9/18 = %50** | > %10 ⇒ B | **B** |
| Alfa kanallı (RGBA) | 4/18 = %22 | — | alfa **azınlıkta** |

%50, tetiğin **beş katı**. Öneri A uygulansaydı mevcut satıcı ve marka
logolarının **yarısı** standardın yürürlüğe girdiği gün geçersiz olurdu.

Politikaya işlenişi (`seller-logo.json`, `brand-logo.json`): `accept.mime` +
`image/jpeg`; `.jpg/.jpeg` `rejected_extensions`'tan çıkarıldı;
`format_priority`'ye `jpeg_opaque` **en son sıraya** eklendi;
`require.alpha_channel` `required` → **`optional`**;
`content_rules[no_alpha_channel].action` `reject` → **`warn`**; mesaj metni
uyarıya çevrildi.

**K2 → A.** Tetik: *"Mevcut logoların %20'sinden fazlası 2:1 dışındaysa B'ye
geçilmeli."*

| Ölçüt | Değer | Tetik | Sonuç |
|---|---:|---|---|
| Band içinde (1:2…2:1) | **16/18 = %89** | — | — |
| Band dışında | **2/18 = %11** | > %20 ⇒ B | **%11 < %20 ⇒ A** |

Band dışı iki dosyanın **ikisi de aynı orana** sahip (w/h = 2,876; `egemen-plastik`,
`timex-logo`) — yani "geniş kelime markası olan satıcılar çoğunluk olabilir"
endişesi ölçümle çürüdü. `require.aspect_band = { min_w_over_h: 0.5,
max_w_over_h: 2.0 }` **aynen kaldı**; iki politikada tek bir sayı değişmedi.

## Gerekçe

- **`optional` "fark etmez" demek değil**: alfasızlık ölçülür, kullanıcıya ne
  kaybettiği söylenir ve kayıt envantere düşer.
- Ölçüm *yaptırımın sertliğini* değiştirdi, *sorunun varlığını* değil: 11 render
  noktasının plaka boyaması ve S1'in hiç plaka koymaması **aynen duruyor**. Bu
  yüzden kural silinmedi, `warn`'a indi.
- K2'de B seçeneğinin bedeli (iki dosya → iki slot, iki dropzone, iki merdiven)
  **%11 için ödenmiyor**.

## Sonuçlar

### Olumlu

- Hiçbir satıcı standardın yürürlüğe girdiği gün geçersiz olmadı.
- Tetik **iki yönde de** çalışıyor: geçiş sonunda ölçüm tekrarlanır ve JPEG payı
  **%10'un altına** inerse sert rete dönüş gündeme gelir.
- Seçenek tabloları silinmeden korundu; kararlar yeniden açılabilir.

### Olumsuz / açık

- Opak JPEG logolar **11 render noktasında görünür kutu bırakmaya devam edecek**.
  Uyarı okunmazsa kalıcı bir görsel bozukluk kalır.
- Band dışı 2 dosya için kural gevşetilmedi; o iki satıcıdan kare (simge) sürüm
  **elle** istenecek. Geriye dönük zorlama K6'ya bağlı (karar: yalnız yeni
  yüklemeler).
- **n = 18 küçük bir kümedir.** %50 ve %11 oranları bu küme için kesin, üretim
  için tahmindir. (Belge kendi savunmasını yazıyor: %50, %10'un beş katıdır; küme
  büyüklüğü bu farkı tersine çevirmez.)
- **ÖLÇÜLEMEDİ — slot bazında ayrıştırma.** K1 ve K2 sonucu `seller.logo` ve
  `brand.logo` için ayrı ayrı değil, birleşik küme üzerinden verildi.
- **ÖLÇÜLEMEDİ — üretim verisi.** Ölçüm yerel stack'te yapıldı.

## Geri dönüş yolu

Yeni yüklemelerde opak JPEG veya oran dışı logoların yanlış kabul oranı %10'u
aşarsa kural uyarıdan red'e yeniden değerlendirilir. Değişiklik yalnız yeni
yüklemelere uygulanır; mevcut logolar toplu dönüştürülmez ve policy sürümü geri
alınarak önceki davranışa dönülür.
