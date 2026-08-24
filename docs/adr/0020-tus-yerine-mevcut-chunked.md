# ADR-0020 — tus yerine mevcut devam edebilir parçalı yükleme

**Durum:** KABUL EDİLDİ  
**Karar tarihi:** 2026-08-20  
**Teknik kapanış:** 2026-08-23

## Bağlam

Pano T-081/T-091 kesilen yüklemenin kaldığı yerden devamını istiyordu ve
uygulama örneği olarak tus/Uppy adını veriyordu. Kod tabanında ise mağazaya
bağlı, çalışan bir `upload_begin/chunk/status/finish/abort` protokolü zaten
vardı. İkinci bir tus yüzeyi eklemek iki oturum, iki retry modeli ve iki
doğruluk kaynağı oluşturacaktı.

## Karar

Mevcut `media/chunked.py` protokolü resmîleştirildi; tus/Uppy eklenmedi.
Kabul ölçütü ürün davranışıdır: kesintiden sonra parça durumundan devam,
sunucu tarafı tam-dosya doğrulaması, idempotent finalize, kota/politika
snapshot'ı ve süresi dolan oturum temizliği.

Bu karar kullanıcı tarafından 2026-08-20 karar günlüğünde açıkça verildi:
“Mevcut resumable kalıyor; tus'un kullanıcı getirisi düşük, maliyeti yüksek.”

## Uygulanan güvenlik ve bütünlük

- Oturum anahtarı tenant kapsamlı ve tahmin edilemezdir.
- Parçalar tenant + upload kimliği altında atomik yazılır.
- `upload_status` alınan parça sayısını ve yüzdesini döndürür.
- `Idempotency-Key` başlık ve gövdede desteklenir; çelişirse ret verir.
- Aynı anahtarla ikinci finalize aynı sonucu döndürür, ikinci `File` açmaz.
- SHA-256 ilanı biçim ve birleşim sonrası içerikle doğrulanır.
- Aynı tenant + aynı hash eşzamanlı finalize kilidiyle tekilleştirilir.
- Slot politika snapshot'ı ve SHA-256'sı sunucudan gelir; istemci raporu
  yalnız telemetridir ve politikayı gevşetmez.
- Kota begin öncesinde ve kalıcı yazma sırasında sunucuda uygulanır.
- Yarım oturum ve sonuç replay kaydı 24 saat sonra scheduler ile temizlenir.

## Sonuçlar

Panel `localStorage` ile yalnız oturum kimliği/parça planını tutar; sunucu
durumunu kaynak kabul eder. Yeni harici tüketiciler bu sözleşmeyi OpenAPI ve
tipli istemciden kullanır. tus'a geçiş ancak birlikte çalışabilirlik ihtiyacı
ölçülür ve bu protokolün bakım maliyetini aşarsa yeni ADR ile açılır.

## Kanıt

- `tradehub_core/tests/test_chunked_upload_idempotency.py`: 6 Frappe/DB test
- `admin-panel/frontend/src/lib/media/upload/__tests__/session.test.js`: 20 test
- `admin-panel/frontend/src/lib/api/__tests__/client.test.js`: başlık taşıma testi
- `tradehub_core/hooks.py`: günlük `chunked.cleanup`
- `docs/api/openapi-http.yaml`: oturum şemaları ve `Idempotency-Key` başlığı
