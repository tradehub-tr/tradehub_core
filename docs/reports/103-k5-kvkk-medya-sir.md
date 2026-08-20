# Rapor 103 — K5: KVKK medya ayağı + sır-erişim denetimi

**Tarih:** 2026-08-20
**Kapsam:** rapor 92 devir #3 (T-134 §2 sır erişimi) + #4 (Ö-K2/Ö-K3 KVKK medya)
**Şartname:** `~/Desktop/imageoptimization/docs/71-faz13-guvenlik-observability.html` T-134
**Kapsam DIŞI (dokunulmadı):** `api/v1/compliance.py` (orkestratör), hooks/patches, frontend, `docker/`, `logistics_admin.py`, `audit/log.py`, `audit/__init__.py`.

Bütün iddialar konteynerde (`istoc-dev-backend-1`) koşturularak ölçüldü. Süre iddiası yok.

---

## Değişen dosyalar

| Dosya | Ne |
|---|---|
| `tradehub_core/audit/secret_access.py` **(YENİ)** | Ortak sır-erişim denetim yardımcısı `log_secret_access` |
| `privacy/data_export.py` | `_collect_user_media` + export ZIP'ine `media.json/csv` bölümü (Ö-K2) |
| `privacy/account_deletion.py` | `_own_uploaded_media_urls` + `_anonymize_user_media` + silme akışına adım (Ö-K3) |
| `api/sentiment.py`, `api/moderation.py` (×2), `api/translation.py` (×2), `api/push.py`, `api/v1/public_api.py` | `get_password` sonrası denetim çağrısı |
| `tradehub_core/doctype/media_storage_settings/media_storage_settings.py` | `_denetle_sir_okuma` yardımcısı + 3 okuyucuya (imgproxy_dogrula / storage_mapping / secrets) denetim EKİ (mevcut mantık korundu) |
| `tests/test_privacy_media.py` **(YENİ)** | Ö-K2 + Ö-K3 testleri (vacuity dahil) |
| `tests/test_secret_access_audit.py` **(YENİ)** | Sır-erişim denetim testleri (helper + gerçek `public_api._verify_client` uçtan uca) |

---

## İş 1 — KVKK medya ayağı

### Ö-K2: Veri-sahibi export'una medya

**ÖLÇÜLDÜ (öncesi):** `data_export.py::_EXPORTABLE_DOCTYPES` içinde `File`/medya YOK — veri sahibi export'u yüklediği hiçbir görseli içermiyordu.

**YAPILDI:** `_collect_user_media(user)` eklendi. Medya envanterinin (`media/inventory.py`) **hijyen kemerleri yeniden uygulanmadan** doğrudan çağrıldı:
- `inventory._base_query()` → yalnız public, klasörsüz, KVKK/hassas doctype eki olmayan, **hassas-ikiz (content_hash) maskeli** dosyalar. Böylece bir KYC/dekont ile aynı içeriğe sahip public kopya export'a giremez.
- `ownership.scope(query, f, store)` → envanter listesiyle **birebir aynı** sahiplik süzgeci. Kullanıcının mağazası çözülür (`ownership.store_of`); mağazası olmayan (alıcı) için boş.

Export ZIP'ine ayrı `media.json` + `media.csv` bölümü ve `manifest["File"]` girdisi eklendi. Kaynağı `tabFile` olduğu için `_EXPORTABLE_DOCTYPES` deseni (doctype+filters_field) yerine ayrı yol kullanıldı; toplama best-effort (log_error ile).

**KARAR GEREKÇESİ:** Sahiplik neden mağaza-kapsamlı (bireysel `owner` değil): export bir *veri-sahibi* (satıcı hesabı) talebidir; satıcının erişebildiği kütüphane mağaza kapsamıdır ve envanter panelinin gösterdiği kümeyle tutarlı olmalıdır. Silmede (Ö-K3) ise tam tersine bireysel `owner` kullanıldı — aşağıda.

**ÖLÇÜM / vacuity:** `test_privacy_media.ExportMediaScopeTests`
- `test_export_kendi_medyasini_icerir_baskasininkini_degil`: A mağazasının export'u `/files/a1.jpg` içerir, `/files/b1.jpg` İÇERMEZ.
- `test_vacuity_maske_gevsetilince_baskasinin_dosyasi_sizar`: `ownership.scope` no-op yapılınca B'nin dosyası A'nın export'una **sızar** → sınırı gerçekten scope çiziyor (kaldırılırsa test kırmızı).
- Konteyner: bench harness altında 7/7 OK.

### Ö-K3: Hesap silmede medya anonimleştirme

**ÖLÇÜLDÜ (öncesi):** `account_deletion.py` 10 `_anonymize_*` adımının hiçbirinde medya adımı YOK.

**YAPILDI:** `anonymize_deleted_account`'a `_anonymize_user_media(user)` adımı eklendi (`_cleanup_sessions_and_tokens`ten sonra). Davranış:
- `_own_uploaded_media_urls(user)` = envanter hijyen kemeri + **bireysel** `File.owner == user`. Silinen bir alt kullanıcı yüzünden mağazanın/başka alt kullanıcının dosyaları işaretlenmez.
- **SİLME DEĞİL** — mevcut `media/trash.py` akışı: kullanılmayan (`TRASHABLE_VERDICTS`) ve henüz çöpte olmayan medya geri alınabilir çöpe taşınır (`private/media_trash/`, public URL 404, 30 gün geri alınabilir).
- **legal_hold / retention çatışma kuralı (T-134 §4):** kullanımdaki medya (canlı ürün görseli, siparişe bağlı mali kayıt) `TRASHABLE_VERDICTS` dışıdır ve **korunur (RETAINED)**. Verdict'e önceden bakılır, böylece `move_to_trash`ın `_assert_trashable` reddi ve onun `scope_denied` denetim gürültüsü üretilmez.
- Private/hassas/KVKK-eki dosyalar zaten hijyen kemerinde kapsam dışı.
- Her taşıma zaten `media.trash` (dosya başına) denetimi üretir; ayrıca **tek** `privacy.media_anonymized` özet satırı (m.7 adımının bütün olarak çalıştığının kanıtı; trashed/retained sayıları).

> NOT — kodda `legal_hold` diye bir alan **yok** (grep: 0 sonuç). "legal_hold'a saygı" burada iki mekanizmayla karşılanıyor: (1) kalıcı silme yerine geri alınabilir çöp (retention), (2) kullanımdaki/mali-iz dosyaların korunması. Yeni alan/patch açmak kapsam ve "DocType bloat" kuralı dışıydı; gözlem rapora bırakıldı.

**ÖLÇÜM / vacuity:** `test_privacy_media.DeletionMediaAnonymizeTests`
- yalnız kullanılmayan kendi medyası çöpe taşınır (`fu1`); kullanımdaki `fu2` ve zaten çöpteki `fu3` korunur; başkasının `fuB`'sine dokunulmaz.
- `privacy.media_anonymized` özet satırı yazılır (action/decision/object_name/context pinli).
- vacuity: medyası olmayan kullanıcı → adım erken döner, **hiç** özet satır yazılmaz (satır gerçekten yapılan işe bağlı).
- Konteyner: bench harness altında 7/7 OK.

---

## İş 2 — `get_password` sır-erişim denetimi (T-134 §2)

**ÖLÇÜLDÜ (öncesi):** Yalnız `logistics_admin.reveal_carrier_secret` (kullanıcı-tetikli reveal) denetimliydi. Denetimsiz servis-config okumaları: `api/sentiment.py:124`, `api/moderation.py:145,189`, `api/translation.py:52,54`, `api/push.py:31`, `api/v1/public_api.py:44`, `media_storage_settings.py:226,302,329`.

**YAPILDI:** Ortak yardımcı `audit/secret_access.py::log_secret_access(service, field, object_doctype, object_name, tenant)`:
- ADL'ye `config.secret_access` / `ALLOW` / `LAYER_L3` / rule `t134.secret_access` satırı yazar.
- **Maske:** sır DEĞERİ ve URL satıra girmez — yardımcı değeri parametre olarak **hiç almaz** (yapısal maskeleme). Yalnız hangi servis, hangi alan, kim (`session.user`), ne zaman.
- **Severity NORMAL** (HIGH değil): bunlar kullanıcı-tetikli reveal değil, sistem servis-config okumaları; her push/çeviri/API-auth çağrısını HIGH basmak severity filtresini işe yaramaz hâle getirirdi (`media.scan`/`settings` için verilen kararla aynı). logistics'in HIGH+tenant'lı `_log_secret_access`'i (farklı anlam) OLDUĞU GİBİ bırakıldı — o dosya kapsam dışı.
- Best-effort: denetim yazımı iş akışını (çeviri/push/moderasyon/API-auth) bozmaz.

Çağrılar yalnız **dolu** sır okunduğunda tetikleniyor (`if api_key:` vb.) — boş/yapılandırılmamış slotu "okundu" diye yazmak gürültü olurdu. `media_storage_settings`'te üç okuyucuya (`_imgproxy_dogrula`, `storage_mapping`, `secrets`) yalnız denetim EKİ yapıldı; mevcut mantık ve dönüş değerleri korundu. Bu okuyucular yalnız superadmin ayar/test uçlarından çağrılır — per-URL imzalama yolu (`_imgproxy`, satır 523) **kapsamda değil** ve dokunulmadı.

**ÖLÇÜM / vacuity:** `test_secret_access_audit`
- helper: bir okuma → tam bir `config.secret_access` satırı; severity NORMAL; context'te service+field.
- gerçek çağrı sitesi `public_api._verify_client`: gerçek `client_secret` değeri `get_password`'dan gelir, denetim satırında **yok** (uçtan uca maske kanıtı).
- vacuity: sır okundu ama denetlenmedi olsaydı satır 0 olurdu — dolu-secret okuması her zaman TAM bir satır bırakır (assertEqual == 1); ayrıca değer context'e konsaydı yakalanırdı testi.
- Konteyner: bench harness altında 5/5 OK.

**PERFORMANS NOTU (açık bulgu):** `public_api._verify_client` her API-auth isteğinde bir ADL insert üretir. Bugünkü kararla NORMAL severity + commit'siz (istek yaşam döngüsü commit'ler) tutuldu, ama yüksek trafikli public API'de bu hacim büyüyebilir. Örnekleme/eşikleme (ör. aynı client için N dakikada tek satır) ayrı iş olarak önerilir — bu görevde kapsam dışı bırakıldı.

---

## Test sonuçları (konteyner, `istoc-dev-backend-1`)

Plain `python3 -m unittest` (stub harness — bu suit ailesi böyle tasarlı):
- `test_secret_access_audit` 5/5 OK · `test_privacy_media` 12/12 OK

Gerçek bench harness (`bench --site istoc.localhost run-tests --module ...`):
- `test_secret_access_audit` 5 OK · `test_privacy_media` 7 OK
- `test_privacy_audit` 9 OK · `test_media_storage_settings` 19 OK
- `test_payment_transaction_isolation` 12 OK

Import güvenliği: değişen 9 modül gerçek frappe (bench env) altında temiz import edildi.

### Bilinen, MÜDAHALE EDİLMEYEN durumlar (benim değişikliğim DEĞİL)
- Plain-unittest'te `test_privacy_audit`'in `download_data_export` testleri `frappe.cache()` (orkestratörün eklediği `@rate_limit`) yüzünden hata veriyor — **bench harness altında 9/9 geçiyor**, yani stub artefaktı. `compliance.py`'ye dokunulmadı.
- `test_tenant_isolation` stub-suit; hem plain hem bench koşumunda kendi `frappe.db`=SimpleNamespace stub'ı yüzünden 1 hata veriyor (`enforce_seller_isolation_on_insert` → `tradehub_core.audit` import → `frappe.utils.now_datetime` stub'da yok / bench runner teardown `commit`). İçe aktardığı zincir (`tenant.py → audit/log.py`) **bu görevde değiştirilmedi**; git diff'te bu dosyalar yok. Pre-existing.

### Migrate
Şema/DocType/patch değişikliği YOK — migrate gerekmiyor, migrate kilidine dokunulmadı.

---

## Özet: ZATEN / YAPILDI / YAPILAMADI

| Ayak | Durum |
|---|---|
| Ö-K2 export'a kendi medyası (KVKK maskeli) | **YAPILDI** — vacuity ile kanıtlı |
| Ö-K3 silmede medya anonimleştirme (trash + legal-hold koruması) | **YAPILDI** — vacuity ile kanıtlı |
| T-134 §2 sır-erişim denetimi (9 çağrı sitesi + ortak helper) | **YAPILDI** — vacuity + uçtan uca maske kanıtlı |
| `legal_hold` alanı ile çatışma kuralı (T-134 §4, alan bazında) | **KISMEN** — kodda `legal_hold` alanı yok; retention + kullanımda-koruma ile karşılandı, alan bazlı hold ayrı iş (rapora) |
| public API auth denetim hacmi (örnekleme) | **YAPILAMADI (bilinçli)** — açık bulgu olarak bırakıldı |
