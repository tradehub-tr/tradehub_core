# 41 — T-080 / T-082 / T-084: HTTP sözleşmesinin ÖLÇÜLMESİ

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **Site:** `istoc.localhost` (docker compose)
**Kapsam:** `docs/reports/32-faz8-api-kapanis.md` §7'nin *"87 ucun 77'si yalnız koddan
belgelendi"* boşluğunun kapatılması + `Media Crop Intent` uçlarının sözleşmeye alınması.

---

## 0. Karar — TEK CÜMLE

**90 ucun 89'u gerçek HTTP ile çağrıldı; 69'unun başarı gövdesi ölçüldü, 20'sinin yalnız
ret/doğrulama yolu ölçülebildi, 1'i hiç çağrılmadı ve NEDEN çağrılmadığı belgede yazılı.**
Ölçüm 32 numaralı raporun iki UYUŞMAZLIĞINI kapattı, yerine **bir yenisini** ve **yedi yeni
sözleşme sapmasını** buldu.

| İddia | Önceki (rapor 32/35) | Bugün | Kanıt |
|---|---|---|---|
| Uç sayısı | 87 | **90** (+3 kırpma) | `x-endpoint-count`, `test_uc_sayisi` |
| Başarı gövdesi ölçülen uç | 10 | **69** | `x-measured: http` |
| Kısmen ölçülen (yalnız ret yolu) | — | **20** | `x-measured: http-partial` |
| Hiç çağrılmayan | 77 | **1** | `x-unmeasured-endpoints` |
| `Media Storage Settings` uçları | ❌ HTTP 500 | ✅ **200** | §3 |
| `save_intent` `overrides` yolu | "çözüldü" (rapor 37 §2.2) | ❌ **çalışmıyor** | §4 |
| Sözleşme testi | 25 test, 7'si atlanıyordu | **41 test, 0 atlama** | §7 |

> **Süre/performans iddiası YOKTUR.** Ölçüm sırasında makinede paralel ajanlar koşuyordu;
> hiçbir zamanlama sayısı bu rapora alınmadı. `Media Engine Settings` bayrakları ölçümün
> başında da sonunda da **0** (`media_pipeline_enabled: 0`, `manifest_api_enabled: 0`).

---

## 1. Ölçüm yöntemi — sahte istemci YOK

Bu depoda sahte bir S3 istemcisinin 137 testi yıllarca kandırdığı ölçülmüştü. Bu görevde
alınan önlemler:

1. **Her ölçüm gerçek bir `/api/method/…` isteğidir.** `urllib` + çerez kavanozu; sunucu
   `istoc-dev-gateway-1` üzerinden (`http://127.0.0.1:8001`, `Host: istoc.localhost`) ve
   ayrıca konteyner içinden (`http://127.0.0.1:8000`) çağrıldı. `localhost:8000` hiçbir
   siteye düşmüyor — Frappe siteyi `Host` başlığından çözer.
2. **Ölçüm ortamının kodu doğrulandı.** Konteynerdeki altı kaynak dosyanın çalışma ağacıyla
   `sha256` eşitliği ölçüldü:

   | Dosya | sha256 (ilk 16) |
   |---|---|
   | `tradehub_core/api/media_crop.py` | `80b955dc5453c068` |
   | `tradehub_core/api/media_manifest.py` | `b3ce9639044c095a` |
   | `tradehub_core/api/media_access.py` | `cd43415b16515805` |
   | `tradehub_core/api/seller_media.py` | `99e4e0f0b209c407` |
   | `tradehub_core/api/media_admin.py` | `67019b493fa92c1a` |
   | `…/media_storage_settings.py` | `83fa05f98194fda2` |

   Altısı da **AYNI** — yerelde düzeltip konteynerde ölçmek gibi bir yanılgı yok.
3. **Kimlikler.** `misafir` (oturumsuz) · `Administrator` · `satıcı` =
   `ali.bal@turksab.com` → SEL-00003 · `satıcı-2` = `ahmeetseker@gmail.com` → SEL-00001.
   Satıcı oturumları Frappe'nin kendi `user.impersonate` ucuyla açıldı (`Activity Log` izi
   bırakır). **Hiçbir parola değiştirilmedi.**
4. **Yazan uçlara yaklaşım — üç kural.**
   - Yıkıcı uçlar **kasten var olmayan hedeflerle** çağrıldı (`set_id=YOK-9999`,
     `/files/yok-9999-t080.jpg`, `older_than_days=36500`). Bunlar doğrulama yolunu ölçer,
     hiçbir kayda dokunmaz.
   - Satıcı yolunda **ölçüm için veri üretildi ve silindi**: 4×3 PNG yüklendi, üstveri
     yazıldı, yeniden adlandırıldı, kopyalandı, içeriği değiştirildi, arşivlenip geri
     alındı, sonra `purge_media` ile kalıcı silindi. Bir yedek seti alındı, paketlendi,
     indirildi ve kaldırıldı. Bir `Media Asset` + `Media Crop Intent` üretilip silindi.
   - Ölçülemeyen başarı yolları **"ölçülmedi"** diye işaretlendi; hiçbiri "geçti" sayılmadı.

### Ölçüm sonrası durum — üretilen kayıt kalmadı

```
Media Asset: 0   Media Crop Intent: 0   Media Crop Override: 0
seller_media.get_my_summary → {"store":"SEL-00003","active":6,"trashed":0,"bytes":20466224}
                               ↑ rapor 32 §4.3'teki ölçüm ÖNCESİ değerin birebir aynısı
media-seller-backups/SEL-00003 → dizin YOK
Media Engine Settings bayrakları → 0
docs/api/openapi.yaml → git'te DEĞİŞMEDİ (kilitli, bayt eşitliği testi geçiyor)
```

---

## 2. Belgenin yeni yapısı — her uç ya ölçüm ya gerekçe taşır

`docs/api/openapi-http.yaml` artık 5.515 satır / 90 yol. `x-measured` alanının değerleri:

| Değer | Anlamı | Adet |
|---|---:|---:|
| `http` | Başarı gövdesi gerçek çağrıyla ölçüldü | **69** |
| `http-partial` | Uç çağrıldı, **yalnız ret/doğrulama yolu** ölçülebildi; gerekçe `x-measurement` içinde | **20** |
| `http-fail` | Çağrıldı, sözleşmeyi karşılamadı | 0 |
| (alan yok) → `x-unmeasured` | Hiç çağrılmadı, **gerekçesi yazılı** | **1** |

Üretici (`scripts/gen_http_openapi.py`) artık **her uç için ölçüm ya da gerekçe zorunlu
kılıyor**: birini de taşımayan bir uç `validate()`i düşürüyor
(`test_her_ucun_olcum_durumu_YAZILI`). Sessiz boşluk artık mümkün değil.

### Hiç ölçülmeyen tek uç

| Uç | Neden |
|---|---|
| `media_admin.create_media_backup` | Bütün sitenin medyasının anlık kopyasını alır — bu sitede **5.020 dosya**. Ölçüm için üretilip silinemeyecek kadar büyük bir yan etki olurdu. Satıcı karşılığı `seller_media.create_backup` uçtan uca ölçüldü ve **aynı yedek çekirdeğini** kullanıyor. |

Bu ucun 417/403 kapıları da ölçüldü (misafir → 403, satıcı → 403); ölçülmeyen şey **başarı
gövdesidir**.

---

## 3. KAPANAN uyuşmazlık — `Media Storage Settings` uçları artık 200

`docs/reports/32-faz8-api-kapanis.md` §5 iki ucu `x-measured: http-fail` ile işaretlemişti:

```
GET …media_storage_settings.get_storage_status  →  HTTP 500
   ImportError: No module named 'frappe.core.doctype.media_storage_settings'
```

Kök neden `tabDocType` satırının olmamasıydı. Bugün ölçüldü:

```
frappe.db.get_value("DocType", {"name": "Media Storage Settings"}, "name")
→ "Media Storage Settings"                       ← satır ARTIK VAR
```

Yeni ölçüm (Administrator):

| Uç | Sonuç |
|---|---|
| `get_storage_status` | **200** → `{plan: {mode: "local", requested_mode: "local", degraded: false, downgraded_from: "", reasons: [], signer_available: true, backend: "LocalDiskStorage"}, blockers: [B-02, B-04, B-05, …]}` |
| `test_connection?target=cdn` | **200** → `{target: "cdn", ok: false, steps: [{step: "cdn", ok: false, ms: 0.0, detail: "adres tanımlı değil"}], ms: 0.0}` |
| ikisi de, satıcı oturumuyla | **403** — rol kapısı çalışıyor |
| ikisi de, misafir | **403** |

`test_connection` hedef tanımsızken **istisna atmıyor**, `ok: false` ile söylüyor — sözleşme
bunu artık `ConnectionTest` şemasıyla yazıyor. Ayrıca yetkili canlı test gövdede
`secret`/`password`/`access_key`/`parola` dizgisi aramıyor mu diye denetliyor: **sızıntı yok**.

**32 numaralı raporun devir listesindeki 1. madde bu ölçümle kapanır.**

---

## 4. AÇILAN uyuşmazlık — `save_intent` `overrides` yolu UÇTAN UCA ÇALIŞMIYOR

T-082'nin çekirdek maddesi. `docs/reports/37-media-crop-intent.md` §2.2 bu sorunu
"panel artık profil adı gönderiyor" diyerek **çözülmüş** sayıyor. Gerçek HTTP ölçümü
çözülmediğini gösteriyor: **iki katman `profile` alanı için ayrı sözlük konuşuyor ve
ikisini birden geçen bir değer yok.**

| Gönderilen `overrides[].profile` | Sonuç |
|---|---|
| `"w384"` | Kütüphane doğrulamasını **geçer**, sonra Frappe: **417 `LinkValidationError`** — *"Satır #1: Profil: w384 bulunamadı."* |
| `"product.image:w384"` | Kütüphane **reddeder**: **417 `ValidationError`** — *"`product.image:w384` bu slotta tanımlı bir profil değil."* |

Sebep ölçüldü:

* `Media Crop Override.profile` bir **`Link → Media Profile`**'dır ve o DocType'ın kayıtları
  `product.image:w384`, `product.image:w768`, `seller.logo:w384` … biçiminde adlandırılmıştır
  (canlı DB'den listelendi).
* `pipeline/api/crop.py::_parse_overrides` ise **slot içi kısa adı** bekler. `get_intent`in
  kendi yanıtı da kısa adı döndürür: `windows[].profile ∈ {w96, w192, w384, w640, w768,
  w1280, w1920}`.

Yani panelin `get_intent`ten okuyup geri gönderebileceği tek doğal değer (`w384`) sunucuda
Link doğrulamasına çarpıyor.

**`overrides` OLMADAN uç çalışıyor ve idempotent:**

```
POST save_intent  asset=…  focal_x=0.42  focal_y=0.61  method=manual
                  algorithm=edge_energy  algorithm_version=v1
                  confidence=0.87  approved_by_user=1
→ 200  {exists: true, intent: {focal_x: 0.42, focal_y: 0.61, method: "manual",
                               confidence: 0.87, approved_by_user: true, overrides: []}, …}
Aynı yük ikinci kez  → 200, aynı gövde
DB'den sayıldı:  Media Crop Intent satır sayısı = 1        ← idempotency KANITLANDI
```

Uyuşmazlık belgeye `x-mismatch` olarak girdi ve teste bağlandı
(`test_save_intent_uyusmazligi_belgede_DURUYOR`). **Düzeltme bu görevin dokunma
listesindedir** (`api/**` ve `media/**`), devredildi (§8).

---

## 5. Ölçülen SÖZLEŞME SAPMALARI — belgede `x-contract-deviations` altında

Rapor 32 üç sapma bulmuştu. Ölçüm bunları doğruladı ve **yedi tane daha** ekledi.

### 5.1 Önceden bilinen üçü — doğrulandı, biri genişledi

**(D1) 304 üretilmiyor — ve artık İKİ ayrı "değişmedi" sözleşmesi var.**

| Uç | Eşleşen koşullu istekte gövde | HTTP |
|---|---|---|
| `media_manifest.get_manifest` | `{not_modified: true, etag, cache_control}` | **200** |
| `media_crop.get_intent` | `{etag, status: 304}` | **200** |

İki uç aynı işi iki farklı anahtarla söylüyor. Tek bir istemci ayrıştırıcısı yazan biri
ikisini de tanımak zorunda; belge bunu artık açıkça yazıyor (`NotModified` ve
`CropNotModified` ayrı şemalar).

**(D2) `ValidationError` → 417.** Ölçülen tüm iş kuralı redleri 417: *"Geçersiz kapsam"*,
*"Geçersiz yedek kimliği"*, *"0 ile 1 arasında olmalı (INV-10)"*, *"İzin verilenler: center,
manual, smartcrop"*, *"Son yedek silinemez"*, *"Hiç yedek yok"*, *"Dosya bulunamadı"*.

**(D3) `envelope.py` zarfı bu katmanda kullanılmıyor.** Hata gövdesi Frappe'nin
`{exception, exc_type, exc, _server_messages}` zarfı.

### 5.2 YENİ ölçülen sapmalar

**(D4) Zorunlu parametre eksikse HTTP 500 `TypeError`** — 400 ya da 417 değil.

```
GET /api/method/…media_manifest.get_manifest            (parametresiz, misafir)
→ 500  TypeError: get_manifest() missing 1 required positional argument: 'listing'
```

Aynı davranış zorunlu parametreli **18 yönetim ucunda** da ölçüldü.

**(D5) Argüman bağlama, uç içindeki yetki kapısından ÖNCE çalışır.** Bu, aynı isteğin
kimliğe göre farklı durum kodu almasına yol açıyor:

| Çağıran | Parametre | Sonuç |
|---|---|---|
| Misafir | var/yok, fark etmez | **403** — whitelist kapısı argüman bağlamadan önce çalışır (oturum isteyen 87 ucun **tamamında** ölçüldü) |
| Satıcı → yönetim ucu, **zorunlu parametre YOK** | — | **500 `TypeError`** (18 uçta ölçüldü) |
| Satıcı → yönetim ucu, **parametreler VAR** | — | **403 `PermissionError`** (49 yönetim+depolama ucunun **49'unda** ölçüldü) |

Yani rol kapısı sağlam — ama yetkisiz bir çağıran, parametreyi eksik bırakarak fonksiyon
imzasını (parametre adlarını ve sayısını) öğrenebiliyor. Veri sızıntısı değil, ama sözleşme
"yetkisiz → 403" demiyorsa istemci yanlış yazılır.

Bu sıralamanın **statik olarak** doğrulanabilen kısmı da ölçüldü: `media_admin.py` ve
`media_storage_settings.py` içindeki **her** whitelist fonksiyonunda yetki kapısı
(`_guard` / `_guard_destructive` / `_require_superadmin`) docstring'den sonraki **ilk
ifadedir** (`ast` ile tarandı). Bu yüzden yetkisiz süpürme ölçümü hiçbir kayda dokunmadı.

**(D6) `methods=["POST"]` ucu GET ile çağrılınca 403 `PermissionError: Not permitted`** —
405 değil. Yöntem hatası ile yetki reddi **aynı durum kodunu** paylaşıyor; yalnız mesaj
ayırıyor. (Rapor 32 §7 bunu "doğrulanmadı" diye bırakmıştı.)

**(D7) Bu katmandaki TEK 400: CSRF.** Oturum çerezli bir POST `X-Frappe-CSRF-Token`
başlığı olmadan gelirse **400 `CSRFTokenError`**. GET isteklerinde CSRF kontrolü yok
(`frappe/auth.py::validate_csrf_token` yalnız `UNSAFE_HTTP_METHODS` için çalışıyor). İş
mantığı hatası bu katmanda **hiç 400 üretmiyor**.

**(D8) "Bulunamadı" için tek bir durum kodu YOK.**

| Uç | Olmayan/başkasına ait kaynak | Durum |
|---|---|---|
| `media_admin.restore_image`, `media_admin.set_access_level` | olmayan dosya | **404** `DoesNotExistError` |
| `media_admin.retry_scan`, `retry_transcode`, `release_quarantine` | olmayan dosya | **417** `ValidationError` |
| `seller_media.get_my_usage` | başka mağazanın dosyası | **404** `DoesNotExistError` |
| `media_crop.*` | başka mağazanın varlığı **ve** olmayan varlık | **417** — ikisi BİREBİR aynı |
| `media_manifest.get_manifest` | olmayan ilan | **200**, boş manifest |

**(D9) `media_crop._throw`un durum kodu koruma niyeti HTTP'de görünmüyor.** Kaynak
`frappe.local.response["http_status_code"] = env.http_status_for(exc)` ile kütüphanenin
kodunu (ör. 404) korumayı amaçlıyor ve `docs/reports/37-media-crop-intent.md` §4 bunu
*"başka mağazanın varlığı **404**"* diye yazıyor. **Ölçümde hiç 404 gözlenmedi**:
`frappe.throw(..., exc=frappe.ValidationError)` durumu 417'ye çeviriyor. İstemci
`media_crop` uçlarında 404 beklememeli.

> Not: kiracı izolasyonunun **kendisi çalışıyor** — satıcı-2, SEL-00003'ün varlığını
> istediğinde olmayan bir varlıkla **birebir aynı** yanıtı aldı. Sızan tek şey durum
> kodunun belgeye uymaması.

**(D10) CSV ve paket indirmeleri farklı davranıyor.** `export_media_audit` CSV'yi JSON
gövdenin **içinde dizge** olarak döner (`{"csv": "timestamp,action,…\r\n…"}`);
`download_backup_export` ise **`application/zip`** ikili gövde döner (`PK` sihirli baytıyla
başladığı ölçüldü).

---

## 6. Ölçüm özetleri — katman katman

### 6.1 Misafir süpürmesi — 90 ucun tamamı

Parametresiz, her ucun kendi yöntemiyle (POST-only olanlar POST ile). Sonuç:

```
oturum isteyen 87 uç  → 403, İSTİSNASIZ
misafire açık 3 uç:
    get_manifest, get_manifest_batch  → 500 TypeError (zorunlu parametre eksik, D4)
    media_access.download (imzasız)   → 403
```

Bu süpürme artık **test**: `test_misafir_TUM_oturumlu_uclarda_reddediliyor` örneklem değil,
misafire kapalı 87 ucun hepsini geziyor.

### 6.2 Satıcı → yönetim/depolama: 49/49 **403**

Zorunlu parametreler verildiğinde 49 yönetim + depolama ucunun **tamamı** 403
`PermissionError` döndü. Rol kapısında delik yok.

### 6.3 Satıcı kendi kütüphanesi — 33/33 uç ölçüldü

Yükleme (tekil + parçalı), üstveri, etiket, favori, yeniden adlandırma, kopyalama, içerik
değiştirme, arşiv/geri alma, kalıcı silme, yedek/paket/indirme zinciri **uçtan uca** koştu.
Öne çıkanlar:

| Ölçüm | Sonuç |
|---|---|
| `upload_media` (PNG) | 200 — **sunucu PNG'yi WebP'ye çevirdi**: `t080-olcum.png` → `t080-olcum.webp` |
| `upload_begin → upload_chunk → upload_status → upload_finish` | 200 zinciri; `upload_finish` gövdesi `upload_media` ile **AYNI** |
| `upload_abort` → `upload_status` | `{aborted: true}` sonra **417 `[upload_session_unknown]`** — iptal gerçekten iptal |
| `rename_media` | `file_url` **DEĞİŞMEDİ**, yalnız `file_name` — docstring'in sözü ölçüldü |
| `replace_media` | `file_url` korundu, `bytes` 66 → 74 (içerik gerçekten değişti) |
| `get_my_usage`, başka mağazanın dosyası | **404** — `ownership.assert_owns` çalışıyor |
| `create_backup` → `verify_backup(deep=1)` | `{ok: true, missing_count: 0, corrupt_count: 0}` |
| `download_backup_export` | **200 `application/zip`**, gövde `PK` ile başlıyor |
| `delete_backup` | **417 "Son yedek silinemez."** — kural gerçekten uygulanıyor |

`upload_status` bilinmeyen kimlik için `ValidationError` değil **`UploadRejected`**
(`[upload_session_unknown]`) döndürüyor — ayrı bir istisna sınıfı, aynı 417 durumu.

### 6.4 Kırpma uçları (T-082) — 3/3

| Ölçüm | Sonuç |
|---|---|
| Üçü de misafirle | **403** |
| `get_intent`, niyet yokken | **200**, `exists: false`, 7 pencere (w96…w1920) — **404 değil** |
| `get_intent` + eşleşen `if_none_match` | 200, gövde `{etag, status: 304}` (D1) |
| `suggest_focal` | 200, `{focal_x, focal_y, confidence, measured: true, reason: "measured", grid: 32, threshold: 0.5, threshold_calibrated: false, above_threshold, method}` |
| `suggest_focal` hız sınırı | **ÖLÇÜLDÜ**: art arda 34 çağrı → 29 × 200, sonraki 5 × **429 `TooManyRequestsError`**; ilk ret **30. çağrıda**. Sabit `max_calls=30`, pencerede geçen çağrı **29**. |
| `save_intent` (override'sız) | 200, **idempotent** (DB'de 1 satır) |
| `save_intent` `focal_x=1.4` | 417 — *"0 ile 1 arasında olmalı (INV-10)"*; kelepçeleme YOK, ret var |
| `save_intent` `method="edge_energy_v1"` | 417 — *"İzin verilenler: center, manual, smartcrop"* |
| `save_intent` `overrides` | **HER ZAMAN 417** — §4 |
| satıcı-2 (SEL-00001), SEL-00003'ün varlığı | 417, olmayan varlıkla **birebir aynı** yanıt |

`suggest_focal` gövdesi `threshold_calibrated: false` taşıyor — yani eşiğin kalibre
edilmediğini **yanıtın kendisi söylüyor**. Bu dürüstlük şemaya yazıldı.

### 6.5 Yönetim uçları — 47 uç, 26'sı tam, 20'si kısmi, 1'i ölçülmedi

Yıkıcı uçlar var olmayan hedeflerle çağrıldı ve **hiçbiri gerçek bir kayda dokunmadı**:

```
trash_files(["/files/yok-9999-t080.jpg"])   → 200 {moved: 0, failed: [{file_url, error}]}
purge_trash(older_than_days=36500)          → 200 {deleted: 0, freed_bytes: 0, records: 0}
purge_archive(older_than_days=36500)        → 200 {deleted: 0, freed_bytes: 0}
prune_media_backups(keep=14)                → 200 {removed_sets: [], remaining_sets: 0}
repair_dangling_references(dry_run=1)       → 200 {dangling_urls: 0, dry_run: true}
sweep_scans()                               → 200 {scanned: 0, requeued: 0, abandoned: 0}
scan_backfill(limit=0)                      → 200 {queued: 0, skipped: "disabled"}
```

`start_image_optimization(dry_run=1)` ve `start_restore` kasten olmayan bir dosya adıyla
çağrıldı; ikisi de `job_key` döndürdü ve `get_optimization_status` işlerin `errors: 1` ile
bittiğini gösterdi — yani kuyruk mekanizması ölçüldü, **gerçek dosyaya dokunulmadı**.

`get_optimization_status` bilinmeyen anahtar için hata değil `{state: "not_found"}` dönüyor;
bu da sözleşmeye girdi.

---

## 7. Testler

| Koşum | Sonuç |
|---|---|
| Yerel (macOS, Python 3.9.6), `ISTOC_HTTP_BASE` yok | `Ran 41 tests … OK (skipped=16)` — canlı testler **atlandı**, sahte "geçti" üretilmedi |
| Yerel + `ISTOC_HTTP_BASE=http://127.0.0.1:8001 ISTOC_HTTP_HOST=istoc.localhost` + kimlik | `Ran 41 tests … **OK**` — 0 atlama |
| Konteyner (`istoc-dev-backend-1`, Python 3.11) + `ISTOC_HTTP_BASE=http://127.0.0.1:8000` | `Ran 41 tests … **OK**` — 0 atlama |
| `test_api_contracts` (kilitli `openapi.yaml`) | `Ran 126 tests … **OK**` — bozulmadı |
| `python3 -m ruff check` (üretici + test) | temiz |
| `python3 scripts/gen_http_openapi.py --check` (konteyner içinde) | `temiz` |

### Yeni test kapıları (25 → 41)

| Test | Neyi kilitler |
|---|---|
| `test_uc_sayisi` | 90 uç ve etiket dağılımı (5/3/33/47/2) |
| `test_her_ucun_olcum_durumu_YAZILI` | **Her uç ya `x-measured` ya `x-unmeasured` taşır** — sessiz boşluk imkânsız |
| `test_olculen_ucun_olcum_cumlesi_var` | Ölçüm işareti tek başına kanıt değil; cümle zorunlu |
| `test_olcum_listeleri_operasyonlarla_uyusuyor` | Belge başındaki özetler türetilir, elle yazılmaz |
| `test_sapma_listesi_bos_degil` | `304`, `417`, `TypeError`, `CSRF`, `Not permitted` sapmaları belgeden düşerse test düşer |
| `test_kirpma_uclari_belgede` | T-082 uçları belgede ve misafire kapalı |
| `test_save_intent_uyusmazligi_belgede_DURUYOR` | §4'teki uyuşmazlık gizlenemez |
| `test_misafir_TUM_oturumlu_uclarda_reddediliyor` | **87 ucun hepsi** taranır — örneklem değil |
| `test_zorunlu_parametre_eksik_500_TypeError` | D4 sapması beyan edildiği gibi duruyor mu |
| `test_kirpma_uclari_misafire_KAPALI` | Üç kırpma ucu oturumsuz çağrılamaz |
| `YetkiliCanliTesti` (6 test) | `ISTOC_HTTP_USER`/`PASS` verilirse: depolama uçları 200, sır sızmıyor, POST-only GET ile 403, bilinmeyen yedek 417 |

`YetkiliCanliTesti` kimlik verilmezse **atlanır** — kimlik gömülmedi, sahte oturumla "geçti"
üretilmiyor. Yalnız **okuyan** uçlar çağırıyor; yazan uç yok.

### Yeniden üretme

```bash
python3 scripts/gen_http_openapi.py            # üret
python3 scripts/gen_http_openapi.py --check    # sapma var mı (yazmaz)

python3 -m unittest tradehub_core.tests.test_http_api_contracts          # belge kilidi

ISTOC_HTTP_BASE=http://127.0.0.1:8001 ISTOC_HTTP_HOST=istoc.localhost \
  python3 -m unittest tradehub_core.tests.test_http_api_contracts        # + canlı misafir

ISTOC_HTTP_BASE=http://127.0.0.1:8001 ISTOC_HTTP_HOST=istoc.localhost \
ISTOC_HTTP_USER=Administrator ISTOC_HTTP_PASS=… \
  python3 -m unittest tradehub_core.tests.test_http_api_contracts        # + yetkili ölçüm
```

> `ISTOC_HTTP_BASE=http://localhost:8000` **çalışmaz** — Frappe siteyi `Host` başlığından
> çözer, `localhost` hiçbir siteye düşmez (`/api/method/ping` bile 404). Konteyner içinden
> `127.0.0.1:8000` + `ISTOC_HTTP_HOST=istoc.localhost`, host'tan `127.0.0.1:8001` +
> aynı `Host`.

---

## 8. Devir — kalan işler

| # | İş | Sahibi | Neden burada yapılmadı |
|---|---|---|---|
| 1 | **`save_intent` `overrides` sözlük çakışmasını çöz** (§4). Ya `Media Crop Override.profile` Link olmaktan çıkacak / slot öneki ile normalize edilecek, ya `pipeline/api/crop.py` tam profil adını kabul edecek. Karar verilmeden panelin `overrides` göndermesi anlamsız. | `api/media_crop.py` + `media/` sahibi | İkisi de dokunma listesinde |
| 2 | `media_crop._throw`un durum kodu koruma niyeti HTTP'de görünmüyor (D9): ya `frappe.throw` yerine durum koruyan bir yol seçilecek, ya rapor 37 §4'teki "404" cümlesi düzeltilecek | `api/media_crop.py` sahibi | Dokunma listesinde |
| 3 | Zorunlu parametre eksikliğinin 500 üretmesi (D4/D5): Frappe'nin bu davranışı değiştirilemez, ama uçlar parametreleri `= None` varsayılanlı yapıp kendi 417'sini atabilir. Karar gerekiyor | API sahibi | Sözleşme belgeler, kod değiştirmez |
| 4 | `create_media_backup` başarı gövdesi — ayrı, disk bütçesi planlanmış bir ölçüm oturumu | — | Kapsam / yan etki |
| 5 | `retry_video`, `retry_scan`, `release_quarantine`, `restore_image`, admin yedek ailesi: başarı yolları için **fixture kurulumu** gerekiyor (dead-letter video, karantina dosyası, yönetim yedeği) | test sahibi | Bu sitede o durumdaki veri yok |
| 6 | `docs/api/README.md` §3.2 hâlâ *"bağlama katmanı yazılmadı"* diyor — `api/media_manifest.py` ve `api/media_crop.py` o katman | belge sahibi | README dokunma listesi dışında |
| 7 | CI'da `ISTOC_HTTP_BASE` veren bir yapılandırma yok; `bench run-tests` gerçek HTTP yüzeyini hâlâ **ölçmüyor** (16 test atlanıyor) | CI sahibi | Kapsam |
| 8 | `schemathesis`/`dredd` ile şema güdümlü fuzzing (T-084'ün ölçülmemiş maddesi) hâlâ **yok** | — | Kapsam |

---

## 9. Üretilen / değiştirilen dosyalar

| Dosya | Durum | Not |
|---|---|---|
| `docs/api/openapi-http.yaml` | **DEĞİŞTİ** (4.703 → 5.515 satır, 87 → 90 yol) | Üretilmiş; elle düzenlenmez |
| `scripts/gen_http_openapi.py` | **DEĞİŞTİ** | `media_crop.py` kaynağı, `OLCUM`/`UYUSMAZLIK`/`OLCULMEYEN` sözlükleri, 6 yeni şema, `x-contract-deviations`, ölçüm zorunluluğu doğrulaması |
| `tradehub_core/tests/test_http_api_contracts.py` | **DEĞİŞTİ** (25 → 41 test) | Ölçüm değişmezleri + tam misafir süpürmesi + isteğe bağlı yetkili canlı sınıf |
| `docs/reports/41-t080-api-sozlesme.md` | **YENİ** | Bu rapor |
| `docs/api/openapi.yaml` | **DEĞİŞMEDİ** | Kilitli (bayt eşitliği testi geçiyor) |
| `tradehub_core/api/**`, `hooks.py`, `permissions.py`, `patches.txt` | **DEĞİŞMEDİ** | Belgelendi, değiştirilmedi |

---

## 10. Bu raporun ölçMEDİĞİ şeyler

- `media_admin.create_media_backup` başarı gövdesi (§2).
- 20 ucun başarı gövdesi — belgede tek tek `http-partial` + gerekçe olarak yazılı.
- `get_manifest_batch`ın `@rate_limit(600/60s)` kovası (600 istek gerekirdi). `suggest_focal`ın
  30/60s kovası **ölçüldü**.
- Bayraklar **AÇIKKEN** manifest gövdesi. Bu ölçüm boyunca bayraklar 0 kaldı ve 0 bırakıldı.
- Süre, gecikme, verim — **hiçbir zamanlama ölçülmedi ve iddia edilmedi**.
- `spectral` lint, üretilmiş TS tipleri, TS istemci SDK, Postman/Bruno koleksiyonu — T-080 ve
  T-085'in bu maddeleri hâlâ **yok** (`docs/reports/35-dogrulama-faz8-11.md` §1'in tespiti
  bugün de geçerli).
