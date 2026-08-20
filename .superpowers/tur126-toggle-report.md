# TUR-126 §4 — Erişim-seviyesi toggle (public↔private)

**Status:** DONE — TDD, tüm hedef + regresyon testler yeşil.

**Commits (branch `ahmet`):**
- `e6f64da` — feat(media/audit): `media.level_changed` olay sabiti
- `740974d` — feat(media/refs): `retarget()` — referansları yeni URL'e taşı
- `36c9299` — feat(media): `set_access_level` endpoint + `media/access_level.py` + testler

**Test özeti:** `test_media_access_level.py` 7/7 yeşil (private↔public round-trip,
KYB public-red + private-serbest, idempotent no-op, audit kaydı, `_guard()` rol reddi).
Regresyon: `test_media_naming` 9/9, `test_media_access` 17/17 yeşil. Baseline'da zaten
kırık olan 3 modül (`test_media_pipeline_integration`, `test_media_quota`,
`test_media_transcode`) benim değişikliklerimden bağımsız olduğu doğrulandı
(git stash ile orijinal koda dönülüp aynı hatalar tekrar üretildi).

**Güvenlik/referans notları:**
- KYB/KYC/EXCLUDED_DOCTYPES asla public yapılamaz — `force` ya da rol seviyesiyle aşılamaz; private yapmak serbest.
- `_guard()` testinde önemli bir bulgu: `frappe.only_for`, `frappe.flags.in_test=True` iken (bench test runner varsayılanı) rol kontrolünü baypas ediyor. Test bunu `frappe.flags.in_test=False` ile geçici kapatarak doğruluyor (Frappe çekirdeğinin kendi testlerinde de kullanılan desen).
- Atomiklik: disk taşıması (`os.replace`) DB yazımlarından önce tek adım olarak yapılıyor; sonrasında `File`/refs güncellemesi patlarsa disk elle geri alınıp `frappe.db.rollback()` çağrılıyor.
- Referans güncelleme `refs.retarget()` ile `Listing.primary_image` gibi tüm `_WRITABLE` alanları kapsıyor; sipariş geçmişi (`READONLY_TABLES`) ve gömülü metin alanları (JSON `sections`) kasıtlı olarak dokunulmuyor.

---

## Review round 1 fix — CRITICAL bypass + 2 Important (2026-08-14)

**Status:** DONE — TDD, tüm hedef + regresyon testler yeşil.

**Commit (branch `ahmet`):** `19e2a61` — fix(media): CRITICAL — ters-referanslı PII belgeleri public yapılabiliyordu

**Test özeti:** `test_media_access_level.py` 12/12 yeşil (5 yeni test eklendi). Regresyon: `test_media_naming` 9/9, `test_media_access` 17/17 yeşil.

**Güvenlik/referans notları:**
- **CRITICAL (düzeltildi):** `attached_to_doctype in EXCLUDED_DOCTYPES` kontrolü TEK BAŞINA yetersizdi — canlı DB'de 146 dosya (`Seller Application.identity_document` 144, `Seller Certification.document` 2) `attached_to_doctype` set edilmeden, yalnız o alandan referanslanarak yükleniyordu ve korumayı atlayıp public yapılabiliyordu. Fix: `presets.EXCLUDED_MEDIA_FIELDS` haritası + `access_level._is_protected_pii()` ters-referans taraması (`frappe.db.exists(doctype, {field: url})`), attached_to_doctype kontrolüyle birlikte çalışıyor. Harita yanına KVKK bakım notu düşüldü (EXCLUDED_DOCTYPES genişlerse harita da güncellenmeli).
- **Test fixture notu:** İlk fixture denemesi (`frappe.get_doc({...,"identity_document": url}).insert()`) yanlış pozitif verdi — Frappe'nin doc-save akışı Attach alanını kuruluş anında set edince otomatik olarak `attached_to_doctype` dolu YENİ bir `File` kaydı oluşturup linkliyor, bu da eski (düzeltilmemiş) kontrolü yanlışlıkla tetikleyip testi anlamsız kılıyordu. Gerçek production bypass'ı `frappe.db.set_value` ile (doc-controller'ı atlayarak) simüle edildi — canlı DB'deki 146 dosyanın muhtemel oluşma yolu bu.
- **Important #1 (düzeltildi):** `level_changed` audit çağrısı `sensitive=` geçmiyordu; artık private durum içeren her geçişte (kaynak ya da hedef private) `sensitive=True`. Ayrıca context'teki özel `old_url` alanı fingerprint'e çevrildi — `log_media_event` yalnız sabit üç anahtarı otomatik maskelediği için özel anahtarlar maskelemeden kaçıp ham yolu context'e sızdırıyordu. Gerçek ADL kaydı okunarak doğrulandı (mock değil): `object_name` `masked:` ile başlıyor, `context` ham URL içermiyor.
- **Important #2 (düzeltildi):** `set_level` dönüşüne `refs_skipped` (sayı) + `refs_skipped_detail` (ilk 10) eklendi — `retarget`'ın atladığı (JSON gömülü, sipariş geçmişi) referanslar artık API cevabında görünüyor, operatör kırık-referans riskinden haberdar oluyor.
