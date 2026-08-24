# 13 — T-013 uyarlanabilir kalite prototipi

**Tarih:** 2026-08-23 · **Durum:** tamamlandı · **Ham veri:** `docs/data/t013-adaptive-vs-q85.json`

## Sonuç

10 anonimleştirilmiş gerçek ürün görseli, 1200 px master ve hedef SSIM 0,96 ile
JPEG/WebP/AVIF'te ölçüldü. Her codec'te 10/10 adaptif ve 10/10 q85 hedefi tuttu;
adaptif arama en çok dört encode yaptı. Her codec'te alfa/grafik sınıfındaki
1/10 örnek lossless'a yönlendirildi.

| Codec | Adaptif hedef | q85 hedef | En çok encode | 9 kayıplı örnekte adaptif/q85 bayt oranı | Kazanç |
|---|---:|---:|---:|---:|---:|
| JPEG | 10/10 | 10/10 | 4 | 0,735261 | %26,47 |
| WebP | 10/10 | 10/10 | 4 | 0,628102 | %37,19 |
| AVIF | 10/10 | 10/10 | 4 | 0,517909 | %48,21 |

Lossless örnek toplam ortalamaya katılınca adaptif çıktı q85'ten büyük görünür
(JPEG 1,573×, WebP 1,713×, AVIF 1,532×). Bu bir hata değil, q85'in alfa/grafik
için yanlış kıyas olduğunun kanıtıdır; karar kayıplı ve lossless sınıflar için
ayrı raporlanır.

## Strateji

| İçerik sınıfı | Varsayılan hedef | Karar |
|---|---:|---|
| Fotoğraf / elektronik / mobilya | 0,96 | Codec sınırında ikili arama |
| Tekstil / yoğun desen | 0,99 öneri | Etiketli tekstil korpusuyla rollout öncesi kalibre edilir |
| Grafik / yazı | 1,00 | Lossless; JPEG/AVIF istenirse gerçek çıktı PNG |
| Şeffaf ürün | 1,00 lossless | Alfa korunur; WebP lossless veya PNG |

Arama sınırları bugün JPEG 70–95, WebP 65–95, AVIF 60–95'tir. Bunlar
`FORMAT_QUALITY_BOUNDS` içinde veri olarak ayrı tutulur; codec kalite
ölçeklerinin eşit olduğu varsayılmaz. `test_adaptive_quality.py` sınır,
alfa/lossless, biçim fallback'i ve dört deneme tavanını kilitler.

