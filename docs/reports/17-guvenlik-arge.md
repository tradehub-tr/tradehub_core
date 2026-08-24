# 17 — T-017 medya güvenliği AR-GE

**Tarih:** 2026-08-23 · **Durum:** tamamlandı · **Ayrıntılı ölçüm:** `38-t017-guvenlik-kapisi.md`

## Sonuç

| Kabul kapısı | Kanıt | Sonuç |
|---|---:|---|
| `fixtures/malicious` | 10/10 iki yükleme yolunda red | ✅ |
| Decompression bomb | 100 MP, `Image.load` çağrısı olmadan red | ✅ |
| Polyglot/uzantı uyuşmazlığı | PDF/PNG-as-JPEG ve ek payload red | ✅ |
| Kesik JPEG/OOXML sahteciliği | red | ✅ |
| SVG saldırı korpusu | 26 vektör + 3 doğrudan-ret vektörü temiz | ✅ |
| Gerçek SVG regresyonu | 130 dosya ölçüldü | ✅ |
| İzolasyon | RLIMIT_AS + timeout temiz `failed`; parent worker ayakta | ✅ |

Header-only gate piksel tavanı, sihirli bayt, çoklu imza/polyglot, kapanış
işaretleri ve ek payload'ı decode öncesi kontrol eder. PNG'de Pillow
`getexif()` çağrısının decode yaptığı ayrıca ölçüldü; yüksek MP PNG'de EXIF
okuması atlanarak kapının kendi bomba açığı kapatıldı.

SVG `defusedxml` ile ayrıştırılır; `script`, `foreignObject`, dış `href`, event
handler ve entity/DOCTYPE temizlenir veya dosya reddedilir. Orientation
uygulanır; EXIF/GPS/XMP çıkarılır, ICC politika kararıyla korunur. SVG yükleme
allowlist'i bugün kapalıdır; sanitizer'ın varlığı bu kapıyı otomatik açmaz.

Test toplamları: `test_media_security_gate` 18 OK,
`test_media_security_svg` 10 OK, `test_svg_sanitize` 52 OK (3 platform skip),
`test_isolation` 36 OK. Gerçek public/private korpusta düzeltme öncesi/sonrası
meşru red farkı 0'dır.

