"""Teslim sınırı — imzalı URL, srcset/sizes, Content-Type.

ÖLÇÜLEN BOŞLUK (docs/reports/08-canli-olcum.md): incelenen 31 görselin
**0**'ında `srcset`/`sizes` var (ana sayfa 22'nin 0'ı, listeleme 51'in 0'ı) ve
ürün detay sayfası 13,14 MB görsel indiriyor — 900 KB hedefinin 15 katı.
Türev üretmek tek başına bu sayıyı düşürmez; tarayıcının doğru türevi SEÇMESİ
gerekir, o da `srcset` üretimine bağlıdır.

    signed.py     T-052 · HMAC imzalı, süreli URL + ÇİFT TTL kelepçesi
    manifest.py   T-083 · `contracts.delivery.DeliveryManifest` uygulaması
    sizes.py      T-121 · `sizes` dizgesinin GERÇEK yerleşimden türetilmesi;
                  manifest.py'nin bilinçli boş bıraktığı `SIZES_TABLE`'ı
                  doldurur ve rapordaki 71 ölçüm satırına karşı DOĞRULAR
    picture.py    T-120 · manifestten `<picture>` HTML'i (sunucu tarafı
                  işaretleme + iki frontend için referans çıktı)
    rum.py        T-123 · alan (RUM) ölçüm şeması — PII yok, örneklemli

Storefront SALT OKUNUR olduğu için `<img>` etiketinin kendisi bu depodan
değiştirilemez; bu katman manifesti **veri** olarak üretir, iki frontend de
aynı sözlüğü okur (FR-067).
"""

from __future__ import annotations

IMPLEMENTED = True
