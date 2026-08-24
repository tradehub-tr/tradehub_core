# T-061 normalize kabul ve benchmark raporu

Ölçüm tarihi: 2026-08-22, macOS / Python 3.12.13 / Pillow 12.2.0 /
NumPy 2.4.6. Bu sürümler Faz 6 CI byte-regresyon ortamıyla aynıdır. Makine
tarafından okunabilir ham sonuçlar `docs/data/t061-t062-olcum.json` içindedir.

## Kabul sonuçları

| Kriter | Kanıt | Sonuç |
|---|---|---:|
| INV-01: upscale yok | küçük kaynak + property-benzeri ölçü matrisi | GREEN |
| INV-02: DPI pikseli değiştirmez | 3000×3000@300 yalnız DPI kararıyla 3000×3000@72 | GREEN |
| INV-03: piksel tavanı | kabul koşumunda 3000×3000 → 2400×2400 | GREEN |
| INV-04: kişisel metadata yok | kaynakta EXIF/XMP/GPS var, çıktıda yok | GREEN |
| INV-07: alfa korunur | premultiply → resize → unpremultiply kenar testi | GREEN |
| ICC CMYK → sRGB | 25 Lab örneğinde ortalama/en kötü ΔE00 | 0,000 / 0,000 |
| AdobeRGB → sRGB | 25 Lab örneğinde ortalama/en kötü ΔE00 | 0,000 / 0,000 |

ΔE referansı, aynı gömülü kaynak profilinin LittleCMS ile doğrudan sRGB'ye
dönüştürülmesiyle üretildi. Testin kendi kendini doğrulamasını önlemek için
profilsiz/ham RGB negatif kontrolü de vardır: CMYK'de en kötü ΔE00 21,601872,
AdobeRGB'de 1,077561 ölçüldü. CMYK fixture profili CC0 lisanslı
`CGATS001Compat-v2-micro.icc` dosyasıdır; kaynak ve SHA-256 bilgisi fixture
README'sinde kayıtlıdır.

## Bellek ölçümü

Her ölçüm temiz bir alt süreçte yapıldı ve `ru_maxrss` byte'a normalize edildi.
Çağrılar sıralıdır; eşzamanlı iş yükü yoktur.

| Fixture | Koşum | Peak RSS | Bütçe | Sonuç |
|---|---:|---:|---:|---:|
| 30.720.192 B raw RGB TIFF | 3 | 132.464.640 B | 524.288.000 B | GREEN |
| 8527×8527, 72,72 MP JPEG | 3 | 170.557.440 B | 524.288.000 B | GREEN |

72 MP JPEG'in önceki tam-decode yolu Python 3.9.6 / Pillow 11.3.0 ile yapılan
tek-koşum `/usr/bin/time -l` ölçümünde 700.825.600 B peak RSS üretmişti. Hedef
2400 iken libjpeg DCT `draft` seçimi decode ölçüsünü 8527×8527'den 4264×4264'e
indirdi; aynı tarihsel ortamda tek-koşum peak 162.906.112 B oldu. Güncel,
CI-sabitli ortamın üç-koşum değeri yukarıdaki 170.557.440 B'dir. Yol girdisi
`read_bytes()` ile kopyalanmaz, çıktı 8 MiB sınırlı spool üstünden akar ve eski
Pillow piksel tamponları adım geçişlerinde kapatılır.

## Tekrar üretme

```text
python3 -m unittest tradehub_core.tests.test_image_normalize -v
```
