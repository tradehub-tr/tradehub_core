# Media API sürümleme ve kırıcı değişiklik süreci

Sözleşme sürümü `1.0.0`dır ve semantik sürümleme kullanır. Donmuş yüzey
`docs/api/openapi-http.yaml` içindeki çağrılabilir `/api/method/…` uçlarıdır;
saf Python `openapi.yaml` ayrıca kilitlidir ama HTTP route'u sayılmaz.

## Sürüm kuralları

| Artış | İzin verilen değişiklik |
|---|---|
| PATCH | Açıklama, örnek ve yazım düzeltmesi; şema değişmez |
| MINOR | Yeni uç, isteğe bağlı istek alanı, yeni yanıt alanı, enum'a değer ekleme |
| MAJOR | Uç/alan/yanıt kaldırma, zorunlu alan ekleme, tip veya anlam değiştirme |

Aşağıdakiler kırıcıdır:

- yol, HTTP yöntemi veya `operationId` kaldırmak/değiştirmek;
- zorunlu istek alanı eklemek ya da isteğe bağlı alanı zorunlu yapmak;
- yanıt alanı veya durum kodu kaldırmak;
- alan tipi, `$ref`, `oneOf`/`anyOf`/`allOf` biçimi değiştirmek;
- enum değerini kaldırmak;
- mevcut hata kodunun anlamını değiştirmek;
- oturum/rol kapısını kaldırarak yetki yüzeyini genişletmek.

İstemciler yeni isteğe bağlı alanları ve bilinmeyen yanıt alanlarını yok
saymalı; bilinmeyen hata kodunda katalogdaki `retryable` davranışına düşmelidir.

## Deprecation

1. Operasyon `deprecated: true` yapılır ve kaldırma tarihi açıklanır.
2. HTTP yanıta `Deprecation` ve `Sunset` başlıkları eklenir.
3. Eski uç en az bir MINOR sürüm boyunca çalışır.
4. Kaldırma yalnız yeni MAJOR sürümde yapılır.
5. Yeni MAJOR aynı anda ayrı yol/istemci yüzeyi olarak yayınlanır; v1 geçiş
   süresi bitmeden yönlendirilmez veya sessizce anlam değiştirmez.

## CI kapısı

`scripts/check_openapi_breaking.py` PR tabanındaki belgeyle yeni belgeyi
karşılaştırır. Aynı MAJOR içinde bulgu varsa `faz8-api.yml` kırılır. Yeni MAJOR
sürümde bulgular raporlanır ama bilinçli geçiş olarak kabul edilir.

Yerel kullanım:

```bash
uv run --with pyyaml python scripts/check_openapi_breaking.py \
  /tmp/openapi-http.base.yaml docs/api/openapi-http.yaml
```

Bir şema değişikliğinde sıralama şöyledir:

1. Python kaynağını ve `API_VERSION`ı değiştir.
2. OpenAPI, Postman ve hata kataloğunu yeniden üret.
3. Spectral, kırıcı-değişiklik ve backend contract testlerini çalıştır.
4. Admin `npm run sync:api` ile tipleri/kataloğu yenile.
5. Panel testlerini ve canlı contract/fuzzing kapısını çalıştır.
