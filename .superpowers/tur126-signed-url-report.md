# TUR-126 — imzalı süreli private medya URL — rapor

**Status:** DONE — 11/11 test yeşil.

**Commit'ler (branch `ahmet`):**
- `89d94c0` feat(media/audit): media.signed_access olay sabiti (TUR-126 hazırlık)
- `a3f7189` feat(media): private dosyalar için imzalı süreli URL (TUR-126 §3)

**Test özeti:**
`docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access` → **Ran 11 tests … OK** (get_signed_url: yetkili/yetkisiz/public-red/traversal-red/TTL-clamp; download: geçerli-serve/geçersiz-imza-red/süresi-dolmuş-red/public-red/traversal-red/audit-kaydı).

**Güvenlik notları:**
- `get_signed_url` yetkisiz kullanıcı için imza **üretmiyor** (`File.has_permission("read")` reddi → `frappe.PermissionError`, canlı test edildi) — kritik kural sağlandı.
- `download()` Guest'e açık ama HMAC (`verify_request`) + `exp` + path-prefix (`/private/files/`) üç bağımsız kontrolden geçmeden dosya serve edilmiyor; path-safety `check_path_safety` ile ikinci kez (defansif) doğrulanıyor.
- `frappe.utils.response.download_private_file` bilinçli olarak kullanılmadı (session zorunlu kılıyor); `send_private_file` + kendi kontrollerimiz tercih edildi.
- Kalan risk (bilgi amaçlı, kapsam dışı): imza süre boyunca imza-anındaki yetkiyi taşıyor (tasarımın kendisi — TTL kısa tutulmalı, üst sınır 24s ile sabitlendi). KYB/KYC gibi EXCLUDED_DOCTYPES için capability-gate tasarım dokümanında "implementasyon kararı" olarak bırakılmış, bu görevde uygulanmadı.
- `test_media_pipeline_integration.py`'de bizim değişikliklerden bağımsız, önceden var olan bir disk-path test hatası tespit edildi (git stash ile doğrulandı) — bu göreve dahil değil, ayrı bir sorun olarak bırakıldı.

---

## Fix round 1 (güvenlik review sonrası)

**Status:** DONE — 17/17 test yeşil.

**Commit:** `f4b5730` fix(media): download() reddedilen denemeleri de audit'e yazsın + exp-yolu regresyon testi (TUR-126 review round 1)

**Test özeti:**
`docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access` → **Ran 17 tests … OK** (önceki 11 + exp="abc" red, exp-eksik red, 4× red-dalı audit doğrulaması: invalid_signature/expired/bad_path/malformed_exp).

**Bulgu 1 (Important — regresyon koruması) çözüldü:** `exp` sayısal-değil (`"abc"`) ve `exp` tamamen eksik senaryoları artık ayrı testlerle sabitlendi — `verify_request` True mock'lanıp yalnız exp yolu izole edildi, `send_private_file`'ın hiç çağrılmadığı da doğrulandı (`m.assert_not_called()`).

**Bulgu 2 (Important — güvenlik izlenebilirliği) çözüldü:** `download()`'a `_log_denied()` eklendi — her red dalı (`invalid_signature`, `bad_path`, `expired`, `malformed_exp`) artık `media.access_denied` ile denetime yazılıyor; dosya yolu `sensitive=True` ile fingerprint'e çevrilip maskeli kaydediliyor (ham path denetim tablosuna düşmüyor). `log_media_event` zaten best-effort (`log_decision` hatası patlamaz) — red akışını bozma riski yok, ekstra try/except eklenmedi.

**Kalan not:** Reviewer'ın "Critical yok, `exp` possibly-unbound false positive" tespiti doğrulandı — kod zaten `try/except (TypeError, ValueError)` ile `frappe.throw` (NoReturn) kullanıyordu, bypass yoktu. Bu round sadece o davranışı regresyona karşı test'e bağladı + red-yolu telemetrisini ekledi.
