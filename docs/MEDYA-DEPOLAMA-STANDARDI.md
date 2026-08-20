# Medya Depolama Yapısı ve İsimlendirme Standardı

**TUR-130** · Faz 1 · 2026-08-14

Bu belge medya dosyalarının **nereye** ve **hangi adla** yazıldığını tanımlar:
depolama hiyerarşisi, dosya adı üretimi, çakışma davranışı, türev dosya yeri ve
ölçeklenme stratejisi. İsimlendirme kararı [[MEDYA-YUKLEME-SOZLESMESI]] (TUR-123)
ve enumeration önleme (TUR-141) ile birlikte okunur.

---

## 1. Karar özeti (tek tabloda)

| Konu | Karar |
|---|---|
| **Public medya kökü** | `<site>/public/files/` — nginx doğrudan servis eder |
| **Private medya kökü** | `<site>/private/files/` — Frappe permission katmanından geçer |
| **Dosya adı** | `<sha256(içerik)[:32]>.<uzantı>` — içerik-adresli, tahmin-edilemez |
| **Shard** | Hash-prefix: `files/<ab>/<hash>.<ext>` (adın ilk 2 hex'i alt dizin) |
| **Çakışma** | İçerik-adresli ad → aynı içerik = aynı yol → doğal dedup |
| **Türev** | Orijinalin YANINDA, ekli suffix: `<hash>_thumb.webp`, `<hash>_720.webm` |
| **Eski isimler** | Verbatim (`0505.jpg`) korunur; retro-rename ertelendi (§7) |

---

## 2. Neden bu belge yazıldı — ölçülen risk

Bugünkü yapı **düz** (tek dizin, alt dizin yok):

```
public/files/     → 2.858 dosya (ürün görselleri, public medya)  [DÜZ]
private/files/    → 192 dosya  (KYB/KYC belgeleri)               [DÜZ]
```

İki somut risk:

1. **Ölçek — dosya sistemi yavaşlaması.** Tek dizinde milyonlarca dosya
   olduğunda `readdir`/`stat`/`ls` doğrusal yavaşlar (ext4/xfs dizin indeksine
   rağmen backup, senkron, listeleme araçları etkilenir). İstoç ölçeğinde
   yüzlerce satıcı × yüzlerce ürün × birden çok görsel = milyon mertebesi
   erişilebilir.
2. **Tahmin edilebilirlik.** Eski isimlerin %50'si (`0505.jpg`) URL'den toplu
   çekilebiliyordu. İçerik-hash isimlendirme (WP4/TUR-141) bunu kapattı; bu
   belge o kararı depolama düzeyinde standartlaştırır.

---

## 3. Depolama hiyerarşisi

### 3.1 Ana kökler

| Kök | İçerik | Erişim |
|---|---|---|
| `public/files/` | Ürün görselleri, mağaza logoları, public medya | Anonim (nginx doğrudan) |
| `private/files/` | KYB/KYC belgeleri, sertifikalar, RFQ ekleri | Permission-gated (Frappe) |

### 3.2 Medya-özel private kökler (mevcut, korunuyor)

| Kök | Sabit | İşi |
|---|---|---|
| `private/image_originals/` | `presets.ARCHIVE_DIRNAME` | Optimize edilenlerin arşiv orijinali (30 gün geri-alma) |
| `private/media_trash/` | `trash.TRASH_DIRNAME` | Soft-delete (30 gün retention) |
| `private/media-backups/` | `backup.ROOT_DIRNAME` | İçerik-adresli yedek: `blobs/<xx>/<sha256>` + manifest |

Bu üç kök `File` kaydı ÜRETMEZ (kotaya girmez) ve web'den erişilemez. Public
medyanın kota + servis düzlemi yalnız `public/files/` ve `private/files/`'tir.

---

## 4. İsimlendirme standardı

### 4.1 Kural

Yeni her yükleme:

```
<sha256(içerik)[:32]>.<uzantı>
```

- **32 hex** (128-bit) — tahmin edilemez (enumeration önleme).
- **İçerik-adresli** — aynı içerik her zaman aynı adı üretir → doğal dedup.
- **Uzantı korunur** — nginx MIME/cache ve `.webp/.mp4` uzantı-bazlı davranış çalışır.
- **Görünen ad (`File.file_name`) değişebilir** — kullanıcı-dostu ad ayrı tutulur;
  yalnız disk adı + `file_url` hash'lidir.

Uygulama: `media/naming.py:write_file_hashed` (Frappe `write_file` hook'u, her
iki upload yolunu da destekler — bkz. modül docstring'i).

### 4.2 Shard — hash-prefix

Fiziksel yol adın ilk 2 hex karakterine göre shard'lanır:

```
/files/<ab>/<abcdef...>.webp        (ab = hash[:2])
/private/files/<ab>/<abcdef...>.pdf
```

- **256 alt dizin** (`00`–`ff`) → dosyalar eşit dağılır; tek dizinde milyon
  yerine ~dizin başına birkaç bin dosya.
- **İçerik-adresli isimle doğal uyum** — hash'in kendisi shard anahtarı, ekstra
  metadata gerekmez.
- **Yedek blob'ları zaten böyle** (`media-backups/blobs/<xx>/`) — tutarlı desen.
- **Dedup korunur** — aynı içerik aynı hash → aynı shard → aynı yol.

### 4.3 Çakışma davranışı

İçerik-adresli isimlendirme çakışmayı **yapısal olarak** çözer:

- Aynı içerik iki kez yüklenirse → aynı `file_url` → fiziksel tek dosya.
  (Frappe'nin `content_hash` dedup'ı da bunu insert öncesi yakalar.)
- Farklı içerik → farklı hash → farklı yol. SHA-256 çakışması pratikte imkânsız.
- Rastgele suffix / sayaç GEREKMEZ (eski Frappe `get_file_name` deseni).

---

## 5. Türev dosyalar (WebP variant, thumbnail, video rendition)

Türevler **orijinalin yanında, aynı shard dizininde, ekli suffix** ile durur:

```
/files/ab/<hash>.jpg           ← orijinal (ya da optimize)
/files/ab/<hash>_thumb.webp    ← küçük thumbnail
/files/ab/<hash>_768.webp      ← responsive variant (srcset)
/files/ab/<hash>_720.webm      ← video rendition
```

Gerekçe:
- **Birlikte taşınır/silinir** — orijinal silinince türevleri aynı dizinde bulmak
  kolay (`<hash>_*` glob).
- **İlişki isimden belli** — ayrı dizin + eşleme tablosu gerektirmez.
- **Aynı shard** — türev, base hash'in ilk 2 hex'ini kullanır → orijinalle colocate.

> Türevlerin **üretimi** ve yaşam döngüsü TUR-297 (versioning) / TUR-128
> (WebP+srcset) işidir. Bu belge yalnız KONUMU tanımlar.

---

## 6. Geriye dönük uyumluluk

- **Mevcut `file_url`'ler KIRILMAZ.** Shard + hash yalnız YENİ yüklemelere uygulanır.
- Mevcut düz `/files/0505.jpg` yolları çalışmaya devam eder (nginx her iki deseni
  de servis eder: `/files/<ad>` ve `/files/<ab>/<ad>`).
- Referanslar (`Listing.primary_image` vb.) `file_url`'i denormalize string olarak
  tutar; yeni yüklemeler zaten sharded URL kaydeder, eski referanslar dokunulmaz.

---

## 7. Ertelenen: eski isimlerin migration'ı

2.166 tahmin-edilebilir eski isim (`0505.jpg`) şu an korunuyor. Retro-rename:

- ~2.400 referans güncellemesi (`tabListing.primary_image` 1241, `tabListing
  Image.image` 1137, + uzun kuyruk) + 301 redirect haritası gerektirir → **riskli,
  ayrı iş**.
- Yeni yüklemeler zaten güvenli (hash) olduğu için aciliyeti düşük.
- **Gelecek görev:** enumeration açığını tamamen kapatmak istenirse ayrı bir
  migration görevi açılır (report → referans taraması → rename → redirect → CDN purge).

Bu arada nginx sertleştirmesi (TUR-141: `/files/`'a `X-Robots-Tag: noindex` +
`limit_req`) eski isimlerin toplu çekilmesini pratikte zorlaştırır.

---

## 8. Ölçeklenebilirlik hedefi (özet)

| Boyut | Bu standartla davranış |
|---|---|
| Dosya sayısı | Hash-prefix shard → dizin başına ~N/256; milyonlarda bile hızlı |
| Dedup | İçerik-adresli → aynı içerik tek fiziksel dosya |
| Tahmin edilebilirlik | 128-bit hash → enumeration imkânsız |
| Türev çoğalması | Aynı shard + suffix → yönetilebilir, orijinalle bağlı |
| CDN'e geçiş | Yol yapısı (`/files/<ab>/<hash>`) CDN origin olarak temiz |
