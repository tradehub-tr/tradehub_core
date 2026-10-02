# Ürün görseli: kare, 1000–2000 px, beyaz dolgu — Tasarım

**Tarih:** 2026-09-29 · **Durum:** kullanıcı onayı bekliyor · **İlgili:** G-16 medya, MOGEM-619 (retro-rename altyapısı)

## 1. Amaç

Ürün görselleri vitrinde tek biçimde ve hızlı açılsın. Kurallar:

- Uzun kenar 2000 px'i geçiyorsa 2000'e küçültülür. Görsel **asla büyütülmez**.
- Sonuç, kenarı `S = max(1000, min(2000, uzun kenar))` olan **kare beyaz tuvalin ortasına** konur.
- Örnekler:
  - 3068×2547 → 2000×2000
  - 800×1000 → 1000×1000
  - 600×500 → 1000×1000 (görsel 600×500 kalır, etrafı beyaz)
  - 1200×1200 → dokunulmaz
- Şeffaf arka plan beyaza düzlenir. Çıktı WebP.

**Başarı ölçütü:** Bir ürüne bağlı her görsel (ana, galeri, varyant) kare ve 1000–2000 aralığında. Eski adresler 301 ile yenisine gider. İşlem geri alınabilir.

## 2. Kullanıcı kararları (2026-09-29)

| Karar | Seçim |
|---|---|
| 1000'den küçük görsel | Reddedilmez, büyütülmez; 1000×1000 beyaz tuvalin ortasına konur |
| Kapsam | Yalnız ürün görselleri. Logo, kapak, banner, belge ve video dokunulmaz. |
| Eski görseller | Yeni adrese yazılır, eski adres 301 ile yeni adrese gider. Orijinal arşivde kalır, geri alınabilir. |

## 3. Neden "yüklenirken" değil "ürüne bağlanınca"

Ürün görselleri en az dört yoldan giriyor:

- `ListingFormView` → Frappe `upload_file`. `_kaydet`'ten hiç geçmiyor; ürün görsellerinin çoğu buradan geliyor.
- Medya kütüphanesi kuyruğu ve medya seçici. `_kaydet`'ten geçiyor ama `slot` gönderilmiyor.
- Toplu içe aktarma: adresten indirme ve ZIP.
- Kırpma stüdyosu.

Yükleme anında dosyanın ürün görseli olup olmadığı güvenilir biçimde bilinmiyor. Ürün kaydedildiğinde ise bilgi kesin: `Listing.primary_image`, `Listing Image.image`, `Listing Variant Item.variant_image`, `.variant_gallery` (`media/usage.py` `LIVE_SOURCES`).

Karar: normalleştirme **ürün kaydında** tetiklenir. Eski görseller için toplu iş aynı fonksiyonu çağırır. Yeni ve eski tek kuraldan geçer.

## 4. Bileşenler

### 4.1 `media/kare.py` (yeni)

- `kare_boyutu(w, h) -> int | None`: hedef kenar `S`; zaten kare ve `1000 ≤ w ≤ 2000` ise `None` (işlem yok).
- `kareye_cevir(icerik: bytes) -> bytes`: EXIF döndürme, `thumbnail(2000)`, alfa varsa beyaza düzleme, `S×S` beyaz tuvale ortalı yapıştırma, WebP (q 85). Başarısızlıkta istisna; çağıran orijinali korur. Animasyonlu GIF, SVG, video ve okunamayan dosya → atla.
- `normalize_one(file_url, *, job_key, dry_run) -> dict`:
  1. Dosya ürün görseli değilse ya da `kare_boyutu` `None` ise atlanır.
  2. Kare içerik yeni `File` olarak eklenir. İçerik-kodlu ad naming kancasıyla kendiliğinden verilir.
  3. `refs.retarget(eski, yeni)` ile tüm canlı referanslar yeni adrese çevrilir (sepet ve favori dahil, `LIVE_SOURCES`).
  4. Eski adres için `Media URL Redirect` (301, 90 gün) açılır.
  5. Eski dosya diskten `image_originals` arşivine taşınır. Böylece nginx eski adrese dosya bulamaz ve 301 devreye girer.
  6. Satır iş kaydına yazılır.
- `rollback(job_key)`: arşivden eski dosyayı geri koyar, `refs.restore_retarget_changes` ile referansları eski adrese döndürür, redirect'i siler, yeni `File`'ı kaldırır.

Taşıma, redirect ve geri alma kalıbı `retro_rename.py`'den alınır: `rename_one`, `run_rollback`, `refs.retarget`. Kod kopyalanmaz, ortak yardımcı kullanılır.

### 4.2 Tetik: Listing kaydı

- `Listing` `on_update` → işlenmemiş görsel adresleri toplanır → **commit sonrası** `media-image-live` kuyruğunda `normalize_listing(listing)` çalışır.
- Kayıt anında bekleme olmaz. Birkaç saniye orijinal görünür, sonra kareye döner.
- Aynı dosya birden çok üründeyse tek kez işlenir; `retarget` hepsini çevirir.

### 4.3 Eski görseller: toplu iş

- Yönetim paneli Sistem → Medya'ya kart eklenir: **Ürün görsellerini kareye çevir**. Prova (dry-run) sayıları gösterir: "çevrilecek", "zaten uygun", "atlanacak (neden)". Ardından başlatma ve geri alma. Tasarım `MediaRetroRenameCard` ile aynı.
- Toplu iş `long` kuyruğunda çalışır ve partilere bölünür.

### 4.4 Politika uyumu

`product.image` slotunda "kısa kenar ≥ 1000" ve "alan ≥ 1 MP" reddi kaldırılır; 800×1000 ve 600×500 artık yüklenebilir. Yükleme öncesi uyarı metni şöyle olur: "Görsel kareye tamamlanacak, arka plan beyaz olacak". Değişiklik backend JSON'unda ve panelin vendorlanmış kopyasında (`lib/media/policy/vendor`) aynı anda yapılır.

## 5. Kapsam dışı

- Logo, marka, kategori banner'ı, kapak, avatar, belge ve video.
- Görseli büyütme (upscale), yapay zekâ ile arka plan temizleme, ürünü ortalamak için kırpma.
- Sipariş kalemi görselleri ve makbuzlar. Bunlar geçmiş kaydıdır, dokunulmaz.

## 6. Hata durumları

| Durum | Davranış |
|---|---|
| Dosya açılamıyor, animasyonlu ya da SVG | Atlanır, nedeni iş kaydına yazılır |
| Diske yazma veya retarget hatası | O dosya için geri sarılır, iş devam eder |
| İş yarıda kalır | Kaldığı yerden devam eder; işlenmiş dosya tekrar işlenmez |
| Geri alma | Arşivdeki orijinal geri konur. Arşiv 30 gün tutulur, geri alma o süre içinde yapılmalı. |

## 7. Test

- **Birim:** `kare_boyutu` için örnek tablo (§1), şeffaf PNG → beyaz, EXIF döndürme, 1200×1200 atlanır, animasyonlu GIF atlanır.
- **Entegrasyon:** Ürün kaydı → iş kuyruğa girer → alanlar yeni adresi gösterir → eski adres 301 verir → geri alma her şeyi eski haline getirir.
- **Uçtan uca (lokal):** 3068×2547 örneği (`UR 3373 - yesil.jpg`) 2000×2000 olur. Vitrin, sepet ve favoride kare görünür, konsolda kırık görsel yoktur.

## 8. Yayın sırası

1. Lokal: kod, testler, prova, gerçek koşu, tarayıcı kontrolü.
2. Alpha: deploy, prova, koşu, 1 gün gözlem.
3. Prod: ayrı onayla.
