# ADR-0025 — CDN: içerik-adresli immutable teslim, purge yalnız overwrite istisnasında

**Durum:** Kabul edildi
**Tarih:** 2026-08-23 · **İlgili:** ADR-0001, ADR-0015

## Bağlam

Hash'li türev URL'i içerik değiştiğinde kendiliğinden değişir. Her deploy/yükleme
sonrası purge çağırmak CDN API bağımlılığı ve cache stampede yaratır. Ham veya
legacy aynı-URL overwrite ise purge gerektirebilir.

## Seçenekler

| Seçenek | Ölçüm / bedel |
|---|---|
| Her değişiklikte wildcard purge | Basit ama immutable adreslemenin faydasını yok eder |
| **Hash URL + uzun TTL; aynı URL overwrite'ta URL purge** | **Seçildi** |
| On-the-fly imgproxy'yi tek teslim yolu yapmak | Beş boyut prototipi var; servisi zorunlu bağımlılık yapar |

## Ölçüm verisi

`docs/reports/27-t052-cdn-teslim.md`: 663 içerik-adresli dosya ölçüldü;
hash türev `max-age=31536000, immutable`, ham dosya 300 sn + revalidate,
private yanıt `no-store`. `test_cdn_delivery` + `test_imgproxy_delivery` toplam
12/12 geçer; imgproxy allowlist'i 5 genişliktir.

## Karar

Public hash türevler uzun TTL immutable, ham adlar kısa TTL, private içerik kısa
ömürlü imzalı/no-store teslim edilir. `should_purge` yalnız eski ve yeni URL aynı
ise true döner. Sağlayıcı opsiyoneldir; Cloudflare/Bunny/generic istemci HTTPS,
batch ve token-redaction kapılarıyla takılır. imgproxy bir optimizasyon adapter'ı,
tek çalışma yolu değildir.

## Sonuçlar

Olumlu: origin yükü ve purge bağımlılığı azalır; local kip çalışır. Olumsuz:
yanlışlıkla hash'siz değişebilir URL'e uzun TTL verilirse eski içerik kalır;
cache sınıfı testi zorunludur.

## Geri dönüş yolu

CDN sağlayıcısı hatasında adapter kapatılır ve origin URL'leri kullanılır.
Yanlış cache sınıfı görülürse hash URL'ler korunur, ham TTL 0/must-revalidate'a
çekilir; wildcard purge yalnız olay müdahalesinde elle uygulanır.

