# 12 — T-012 DPI / çözünürlük prototipi

**Tarih:** 2026-08-23 · **Durum:** tamamlandı · **Kod:** `media/pipeline/image/dpi.py`

## Karar

DPI baskı metadata'sıdır; piksel ölçüsü değildir. `rewrite_dpi()` DPI beyanını
değiştirir ama yeniden örneklemez. `pixel_cap_size()` ayrı bir API'dir ve DPI
parametresi dahi almaz. Küçük kaynak büyütülmez.

| Format | DPI okuma | DPI yazma | Saklama | Piksel koruma |
|---|---|---|---|---|
| JPEG | Evet | Evet | JFIF/native + EXIF X/YResolution | 96×64 → 96×64 ✅ |
| PNG | Evet | Evet | pHYs/native (72 dpi ≈ 2835 px/m) | 96×64 → 96×64 ✅ |
| TIFF | Evet | Evet | TIFF resolution tags/native | 96×64 → 96×64 ✅ |
| WebP | Evet | Evet | EXIF X/YResolution fallback | 96×64 → 96×64 ✅ |
| AVIF | Evet | Evet | EXIF X/YResolution fallback | 96×64 → 96×64 ✅ |

Pillow WebP/AVIF `info['dpi']` alanını round-trip etmediği için EXIF fallback
bilinçlidir ve sonuç künyesinde `storage=exif` olarak görünür; native destek
uydurulmaz.

## Ölçüm

Tek renkli 3000×3000 JPEG örneği 300 dpi'dan 72 dpi'a yazıldı:

| Ölçü | Girdi | Çıktı |
|---|---:|---:|
| Piksel | 3000×3000 | 3000×3000 |
| DPI | 300×300 | 72×72 |
| Bayt | 246.724 | 105.831 |

Bayt farkı encoder metadata/optimizasyonunun sonucudur ve değişmez değildir;
değişmez yalnız piksel ölçüsüdür. Bağımsız piksel politikası aynı kaynağı
`max_long_edge=2400, max_megapixels=8, min_long_edge=2000` ile 2400×2400 yapar.
800×800 kaynak aynı politikada 800×800 kalır. Hiçbir yol 300 dpi değerini
`72/300` ölçeği sanıp 720×720 üretmez.

**Kanıt:** `test_dpi_prototype.py` 5/5; normalize DPI/ICC/GPS testleriyle
birlikte çalışır. AVIF encoder bulunmayan ortam, biçimi geçti diye göstermez;
ilgili alt test açık `skip` olur.

