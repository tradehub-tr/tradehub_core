# Media Engine API

Faz 8 (`T-080…T-085`) için çağrılabilir HTTP yüzeyi, saf kütüphane
sözleşmesi ve istemci artefaktları burada tutulur. Sözleşme sürümü `1.0.0`,
OpenAPI sürümü `3.1.0`dır.

## İki ayrı sözleşme

| Dosya | Kaynak | Anlattığı yüzey |
|---|---|---|
| `openapi-http.yaml` | `scripts/gen_http_openapi.py` | Gerçek Frappe `/api/method/…` yüzeyi: **120 uç** |
| `openapi.yaml` | `media/pipeline/api/spec.py` | Frappe'siz saf Python sözleşmesi: **21 operasyon** |

İkinci dosyadaki `/api/media/v1/…` yolları bugün HTTP route'u değildir. İki
belgeyi birleştirmek çağrılamayan kütüphane yolunu çağrılabilir gösterir;
`test_http_api_contracts.py` yol kümelerinin ayrılığını kilitler.

## Üretilmiş artefaktlar

| Artefakt | Üretici / tüketici | Sapma kapısı |
|---|---|---|
| `openapi-http.yaml` | `scripts/gen_http_openapi.py` | `--check` + bayt eşitliği testi |
| `openapi.yaml` | `media/pipeline/api/spec.py` | `tests.test_api_contracts` |
| `collection/media-engine.postman_collection.json` | `scripts/gen_media_api_collection.py` | 120/120 uç + `--check` |
| `error-catalog.json` | `scripts/gen_media_error_catalog.py` | `upload_policy.ALL_CODES` ile 24/24 kod |
| Admin `types.gen.ts` | `openapi-typescript@7.13.0` | `npm run sync:api:check` |
| Admin `error-catalog.gen.json` | hata kataloğu | dört dilde i18n tamlık testi |

Üretilmiş dosyalar elle düzenlenmez. Değişiklik kaynak kodda yapılır, üretici
yeniden çalıştırılır ve kaynak/çıktı SHA-256 zinciri paneldeki
`src/lib/api/api.manifest.json` içine yazılır.

## Yerel doğrulama

Backend deposunda:

```bash
python3 scripts/gen_http_openapi.py --check
python3 scripts/gen_media_api_collection.py --check
python3 scripts/gen_media_error_catalog.py --check

python3 -m unittest \
  tradehub_core.tests.test_api_contracts \
  tradehub_core.tests.test_http_api_contracts \
  tradehub_core.tests.test_media_api_artifacts \
  tradehub_core.tests.test_openapi_breaking

npx --yes @stoplight/spectral-cli@6.16.3 lint \
  --ruleset .spectral.yaml \
  docs/api/openapi.yaml docs/api/openapi-http.yaml
```

Admin panelde:

```bash
cd admin-panel/frontend
npm run sync:api
npm run sync:api:check
node --test \
  src/lib/api/__tests__/client.test.js \
  src/lib/api/__tests__/errorCatalog.test.js \
  src/lib/media/upload/__tests__/session.test.js
```

Canlı sözleşme ve fuzzing:

```bash
ISTOC_HTTP_BASE=http://istoc.localhost \
  python3 -m unittest tradehub_core.tests.test_http_api_contracts -v

uvx --from 'schemathesis==4.25.0' schemathesis run \
  docs/api/openapi-http.yaml \
  --url http://istoc.localhost \
  --include-operation-id media_manifest_get_manifest \
  --include-operation-id media_manifest_get_manifest_batch \
  --phases examples,coverage,fuzzing \
  --checks not_a_server_error \
  --max-examples 30 --generation-deterministic --workers 1
```

`faz8-api.yml` taze Frappe sitesi kurar; yükleme/kırpma/manifest entegrasyon
testlerini ve guest teslim uçlarında Schemathesis 5xx kapısını çalıştırır.

## HTTP davranış sözleşmesi

### Başarı ve hata zarfı

Frappe whitelist başarısı `{"message": <gövde>}` biçimindedir. İş kuralı
retleri çoğunlukla HTTP 417, yetki reddi 403'tür. Saf kütüphane katmanının
`{error_code, retryable, …}` zarfı ile Frappe hata zarfı aynı değildir.

Yükleme reddinde karar metne değil `upload_error` koduna bakar. Tam katalog
`error-catalog.json` içindedir; okunamayan eski istemciler için kod ayrıca
mesaj sonunda `[<code>]` markörüyle taşınır. Yalnız
`upload_chunk_order` ve `upload_chunk_missing` otomatik yeniden denenir.

### Idempotency ve resumable yükleme

`upload_begin` ve `upload_finish`, `Idempotency-Key` başlığını kabul eder.
Gövdedeki `idempotency_key` de verilirse ikisi birebir eşleşmelidir. Aynı
mağaza + aynı anahtar + aynı içerik için ikinci finalize aynı sonucu döndürür;
ikinci `File` satırı açmaz. Anahtar başka içerikte kullanılırsa
`upload_idempotency_conflict` döner.

`upload_begin` yanıtı politika snapshot'ı ve SHA-256'sı, kota kalanı, parça
planı ve süre sonunu taşır. `upload_status` alınan parça sayısı/yüzdesiyle
yenilemeden sonra devamı sağlar. Tamamlanmamış oturumlar günlük scheduler ile
temizlenir. İstemcinin ölçümleri telemetridir; sunucu politikasını gevşetmez.

### ETag / 304

`get_manifest` ve `get_manifest_batch` içerik-adresli ETag üretir. Gerçek
`If-None-Match` HTTP başlığı eşleştiğinde yanıt **304**, gövde **0 bayt** ve
`ETag` + `Cache-Control` başlıklarıyla gelir. Eski `if_none_match` sorgu
parametresi geriye uyum için 200 + kısa `not_modified` gövdesini korur.

### Yetki ve kiracı sınırı

Her operasyon `x-authorization`, `x-python` ve `x-source` taşır. Misafire açık
küme koddan üretilir ve testte tam liste olarak kilitlidir. Satıcı mağaza
kimliğini istekten veremez; oturumdan çözülür. Admin/yıkıcı uçların rol kapıları
ve başka mağaza negatifleri Frappe entegrasyon testlerinde doğrulanır.

## TypeScript istemci

Panelde `src/lib/api/client.ts`, üretilmiş `types.gen.ts` tiplerini panelin
mevcut CSRF/401 taşıması `src/utils/api.js` üzerinde kullanır. İkinci bir HTTP
yığını yoktur. Kırpma, rendition, simulator approval ve parçalı yükleme
yolları bu tipli katmanı gerçek çağrılarında tüketir. `Idempotency-Key` taşıma
seçenekleri CSRF retry sırasında da korunur.

## Postman koleksiyonu

`collection/media-engine.postman_collection.json` altı etiket klasöründe
120/120 gerçek HTTP ucunu taşır. `baseUrl`, token, ilan, varlık, dosya ve
yükleme kimliği koleksiyon değişkenidir. Her istek en azından beklenmedik 5xx'i
reddeden test taşır. Admin/yıkıcı örnekler gerçek hedefe karşı çalıştırılmadan
önce değişkenleri bilinçli ayarlamak gerekir.

## Sürümleme

Kırıcı değişiklik tanımı, deprecation yordamı ve CI karşılaştırması
[`versioning.md`](versioning.md) dosyasındadır. Özet: aynı v1 içinde uç/alan/
yanıt kaldırmak, zorunlu alan eklemek, tip değiştirmek, enum daraltmak veya
kimlik doğrulamayı kaldırmak yasaktır.

## Ölçüm dürüstlüğü

Her gerçek HTTP operasyonu `x-measured: http`, `http-partial` ya da açıklamalı
`x-unmeasured` taşır; sessiz “geçti” yoktur. 2026-08-23 anlık envanter:

- 85 uç gerçek HTTP ile ölçülmüş,
- 22 uç kısmen HTTP + Frappe/DB entegrasyonuyla ölçülmüş,
- 13 yan etkili/uzun yönetim ucu gerekçeli biçimde henüz canlı çağrılmamış,
- sözleşmeyi karşılamayan uç: 0.

Ölçülmemiş yönetim uçları API sözleşmesinden gizlenmez; ilgili Faz 12–13
operasyon turlarında güvenli fixture/dry-run ile kapanacaktır.
