# ADR-0012 — Logo türevleri kayıpsız WebP; 40 KiB tavanı; merdiven ölçümle 4 → 5 basamağa çıktı

**Durum:** Kabul edildi · K3 ve K4 ölçüm/onayla kapandı · **`max_bytes` yaptırımsız**
**Tarih:** K4 onayı 2026-08-19 · **K3 ölçümle 2026-08-19'da B'ye döndü**
**İlgili:** ADR-0007 (fayda kapısı ≠ bayt tavanı), ADR-0013

---

## Bağlam

`docs/standards/logo.md` logo slotları için (`seller.logo`, `brand.logo`) bir
türev merdiveni ve bayt tavanı tanımlıyor. İki açık karar vardı:

- **K3** — merdiven 4 basamak mı (64/128/256/512), 5 mi (+384)?
- **K4** — kayıpsız WebP'nin yanına PNG yedeği üretilsin mi?

K3'ün tetiği **önceden** yazılmıştı: *"D4 ölçümü 512 rung'unun gerçek baytını
verdiğinde, eğer 40 KiB tavanına yakın çıkıyorsa (yani gerçek logolar
`icon-512.png`'den ağırsa) B'ye geçilmeli."* O bayt ancak türev merdiveni
üretildikten sonra ölçülebilirdi; Dalga A türev üretimini açınca ölçüm koşuldu.

## Seçenekler

### K3 — merdiven

| Seçenek | Sonuç |
|---|---|
| **A (ÖNERİ)** — 4 rung (64/128/256/512) | En kötü aşırı-servis 280 → 512 = **1,83× doğrusal / 3,35× piksel**. Basit merdiven = basit `sizes` attribute'u. |
| **B (SEÇİLEN — ölçümle)** — 5 rung (+384) | Aşırı-servis **1,37×**'e düşer. Yalnız 3 talebi (280, 348, 360) etkiler. Logo başına ~15–16 KB ek depolama. |

### K4 — PNG yedeği

| Seçenek | Sonuç |
|---|---|
| **A (SEÇİLEN)** — Yalnız kayıpsız WebP, PNG yedeği YOK | Depolamayı yarıya indirir (188 vs 256 KiB/logo). `api/seller_media.py:245` hedef biçimi zaten WebP. WebP **decode** desteği evrensel. |
| B — WebP + PNG `<picture>` yedeği | Sıfır risk. Bedeli: ~%36 ek depolama **ve** 19 render noktasında yeni markup — storefront'ta bugün `<picture>` kullanımı **0**. |

## Karar

- **K4 → A.** Yalnız kayıpsız WebP üretilir; PNG yedeği yok. Platform yöneticisi
  2026-08-19'da varsayılanda onayladı (`docs/standards/logo.md` "VARSAYILANDA
  ONAYLANAN KARARLAR").
- **K3 → B.** Merdiven **5 basamak**: 64/128/256/**384**/512. Politikaların
  `profiles[]` dizilerine `w384` eklendi (`max_bytes` 23.040 = 40.960 × 384²/512²)
  ve `Media Profile` tohumlayıcısı 2 yeni kayıt üretti.

## Gerekçe — K3'ün ölçümle dönüşü

Ölçüm (`Admin Seller Profile.logo` + `Brand.logo`, 20 referans, **18'i diskte
üretilebildi**; w512 kayıpsız WebP gerçek baytı):

| Ölçüt | Değer | Referans / tavan |
|---|---:|---|
| p50 | 27.162 B | `icon-512.png` = 27.128 B |
| p90 | 83.522 B | — |
| max | **109.172 B** | tavan 40.960 B'nin **2,7 katı** |
| Referanstan ağır | **9/18 (%50)** | tetik: "referanstan ağırsa B" |
| **Tavanı AŞAN** | **5/18 (%28)** | — |
| Tavana yakın (>%80) | 2/18 | — |

Tetik **iki bağımsız okumadan da** sağlandı. Öneri A ölçümle düştü, B yürürlüğe
girdi. Bu, bu depodaki en güçlü deseni tekrarlıyor: karar önce **sayısal bir
tetikle** yazıldı, sonra ölçüm tetiği çalıştırdı ve öneriyi devirdi (bkz.
ADR-0013 K1).

## Sonuçlar

### Olumlu

- Aşırı-servis 1,83× → **1,37×**.
- Karar mekanik verildi: kimse tartışmadı, tetik çalıştı.
- Seçenek tabloları **silinmedi**; karar istenirse yeniden açılabilir.

### Olumsuz — kararın çözmediği şey

- **384 rung'u 109 KB'lık bir logoyu küçültmez.** En ağır 4 dosya AI üretimi PNG
  (Gemini/ChatGPT görselleri): fotoğrafımsı içerik, kayıpsız WebP'de doğal olarak
  şişiyor. Fotoğrafımsı logolar için kayıplı yedek ya da bir içerik kuralı
  gerekiyor — K3'ün kapsamı dışında, **yeni görev**.
- **`max_bytes` türevlerde YAPTIRIMSIZ.** Aşıldığında yalnız `NOTE_OVERSIZE` notu
  düşülüyor; ret ya da yeniden kodlama yok (`media/pipeline/image/render.py:934`,
  bu ADR için doğrulandı). Yani "40 KiB tavanı" bugün bir **rapor satırı**, bir
  kapı değil. ADR-0007'nin fayda kapısı (göreli) çalışıyor, bayt tavanı (mutlak)
  çalışmıyor.
- 18 logonun **6'sının (%33)** kısa kenarı 512'nin altında; bu dosyalar upscale
  yapılmadığı için 512 rung'unu zaten doğurmuyor. K5 kararı (panelin 400×400
  tavsiyesi → 512×512) bunun içindir ve **panel metni değiştirilmedi** — ayrı
  görev.
- **Doğrulanmadı:** ölçüm 18 dosyalık yerel bir küme üzerinde yapıldı; üretim
  dağılımı farklıdır.

## Geri dönüş yolu

Gerçek logo korpusunda PNG aynı görsel kaliteyle WebP'ten küçük çıkar veya
WebP destek matrisi gerilerse lossless biçim seçimi yeniden ölçülür. 40 KiB
tavanı 5 basamağın çoğunda aşılıyorsa merdiven/kalite kararı yeniden açılır;
eski PNG kaynaklar silinmediğinden rollback veri kaybetmez.
