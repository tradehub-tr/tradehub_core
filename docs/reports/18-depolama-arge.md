# 18 — T-018 depolama adapter, CDN ve imgproxy AR-GE

**Tarih:** 2026-08-23 · **Durum:** tamamlandı

## Adapter sözleşmesi

`StorageAdapter` içerik-adresli `put/get/delete/exists/stat/url_for/move/iter_keys`
sözleşmesini taşır. Üretim uygulamaları `LocalDiskStorage`, `S3Storage`,
`MirrorStorage` ve ek olarak `TieredStorage`'dır. Resmî prototip girişi
`prototypes/storage/README.md` dosyasındadır.

| Kanıt | Sonuç |
|---|---:|
| Sahte istemci sözleşmesi | 137/137 |
| Gerçek MinIO sözleşmesi | 91/91 |
| S3 kapalı fabrika matrisi | S3/mirror/tiered isteği görünür gerekçeyle local'e düşer |
| S3 import davranışı | modül düzeyinde boto3 yok; yalnız etkin istemci kurulurken tembel import |
| Private URL | SigV4 + TTL kelepçesi |
| Ağ hatasında `exists` | sözleşme gereği `False`; render'ı kırmaz |

Önceki MinIO ölçümünde bulunan SigV2 ve `exists()` ağ hatası açıkları mevcut
`s3.py` içinde sırasıyla `signature_version="s3v4"` ve `except StorageError:
return False` ile kapatılmıştır. Yerel kip hiçbir S3 paketi/ayarına bağımlı
değildir.

## CDN

Public içerik-hash türevleri `Cache-Control: public, max-age=31536000,
immutable`; değişebilir ham dosyalar 300 sn + `must-revalidate`; private ve
imzalı yanıtlar `private, no-store` kullanır. Content-addressed yeni URL purge
istemez. Aynı URL overwrite istisnasında `delivery/cdn.py` HTTPS, token gizleme,
tekilleştirme ve batch sınırıyla Cloudflare, Bunny ve generic JSON purge
isteklerini kurar. 12 teslim/CDN testi geçer.

## imgproxy

`delivery/imgproxy.py` HMAC-SHA256 imzalı ve URL-safe kaynaklı yollar üretir.
Dinamik keyfi boyut yerine 96/192/384/768/1280 allowlist'i vardır; AVIF/WebP/
JPEG/PNG ve fit/fill/auto desteklenir. Anahtar/tuz `repr`, URL ve hatalara
sızmaz. Aynı kaynaktan beş URL tek `ladder()` çağrısıyla üretilir. Gerçek
imgproxy servisi zorunlu üretim bağımlılığı değildir; S3/CDN/imgproxy kapalıyken
sistem tamamen yerel eager rendition hattıyla çalışır.

Tekrar üretim ve ayrıntılı MinIO/CDN ölçümleri:
`docs/reports/23-t051-s3-adaptor.md`, `25-t051-depolama-ayarlari.md` ve
`27-t052-cdn-teslim.md`.

