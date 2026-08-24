# ADR-0027 — DPI metadata'dır; piksel bütçesi bağımsızdır ve upscale yoktur

**Durum:** Kabul edildi
**Tarih:** 2026-08-23 · **İlgili:** ADR-0008, ADR-0016

## Bağlam

300 dpi → 72 dpi işlemini fiziksel ölçü dönüşümü sanmak 3000 px kaynağı 720 px'e
indirir. Web medyasında DPI yoğunluğu görüntü piksel sayısını belirlemez; slot
politikası uzun kenar ve megapikseli ayrı yönetir.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| DPI oranıyla yeniden örnekle | INV-02 ihlali; 3000 px örnek 720 px olur |
| DPI'yı tamamen at | Piksel korunur ama baskı/metadata sözleşmesi doğrulanamaz |
| **DPI etiketini yaz; pixel cap'i ayrı uygula** | **Seçildi** |

## Ölçüm verisi

`docs/reports/12-dpi-prototip.md`: JPEG/PNG/TIFF/WebP/AVIF 5/5 round-trip;
3000×3000@300 → 3000×3000@72; 246.724 → 105.831 bayt. 800×800 kaynak 2000 px
minimumuna rağmen 800×800 kalır; upscale yoktur.

## Karar

`rewrite_dpi` piksele dokunmaz. `pixel_cap_size` yalnız
`max_long_edge/max_megapixels/min_long_edge` kullanır. Minimum kalite eşiği
kaynak küçükse büyütme yetkisi vermez. Native DPI taşımayan WebP/AVIF EXIF
X/YResolution fallback'i kullanır ve bunu künyede açıklar.

## Sonuçlar

Olumlu: DPI kaynaklı kalite kaybı yok; format davranışı görünür. Olumsuz:
metadata yeniden yazımı byte-identical değildir ve WebP/AVIF okuyucularının
tamamı EXIF DPI'ı göstermeyebilir.

## Geri dönüş yolu

Bir codec EXIF fallback'ini kaybediyor veya piksel değiştiriyorsa o codec'te DPI
yazımı `unsupported` raporlanıp kaynak metadata'sı korunur; yeniden örnekleme
yapılmaz. Pixel cap policy sürümü bağımsız geri alınır.

