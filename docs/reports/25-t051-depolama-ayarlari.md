# 25 — T-051 (şartname): Medya Depolama Ayarları arayüzü + Media Superadmin izolasyonu

**Görev:** T-051 (Faz 5 · Depolama), **şartname dokümanındaki** tanım · **Tarih:** 2026-08-19 · **Dal:** `ahmet`
**Kaynak şartname:** https://karacaismail.github.io/imageoptimization/docs/42-faz5-depolama-s3-cdn.html
**Ölçüm ortamı:** `istoc-dev-backend-1` (Frappe v15, MariaDB 10.6), MinIO `istoc-dev-minio-1`, admin-panel Vite build

---

## 0. Numara çakışması — bu belge NEYİ yapmıyor

Depo içi kayıtlarda **iki farklı iş** "T-051" etiketini taşıyor ve ikisi aynı şey değil:

| Etiket kaynağı | İş | Durum |
|---|---|---|
| `docs/reports/14-nihai-denetim.md:332` | S3/mirror/tiered **adaptörlerinin** gerçek bir S3 servisine karşı ölçümü | **Bugün bitti** → `docs/reports/23-t051-s3-adaptor.md` (91 test, MinIO) |
| Şartname dokümanı, T-051 | **Ayar arayüzü** + Media Superadmin izolasyonu + şifreli sırlar + bağlantı testi + denetim kaydı | **Bu belge** |

Bu iş 23 numaralı raporun ölçtüğü adaptörlerin *üstüne* bir yönetim yüzeyi koyar.
`media/pipeline/storage/*.py` dosyalarının **hiçbirine dokunulmadı** — 23 numaralı
rapor onları ölçtü, bu iş onları yalnız çağırıyor.

---

## 1. Karar (önce sonuç)

> ### Ayar ekranı kuruldu ve üç yönlü izolasyon ölçüldü. Ekran S3'ü bugün **açtırmıyor**: local dışı bir kip, 23 numaralı raporun §7'sindeki açık kapılar ekranda listelenip açıkça kabul edilmeden kaydedilemiyor.

- `Media Storage Settings` (Single) — beş bölüm, **alan adları fabrikanın gerçekten okuduğu adlar**.
- `Media Superadmin` rolü **yaratıldı** (bugüne kadar 12 tasarım JSON'unda anılıyordu ama DB'de yoktu).
- Gizli anahtarlar `Password` fieldtype ile şifreli; `tabSingles`'ta yıldız, `__Auth`'ta Fernet.
- Bağlantı testi **gerçek** yaz/oku/sil turu yapıyor (MinIO'ya karşı ölçüldü, 450 ms).
- Denetim kaydı `media/audit.py` üzerinden ADL'ye yazılıyor; sır kayda GİRMİYOR.
- Panel ekranı: `npm run lint` 0 · `npm run build` 0 · `npm test` **249/249** (240 → +9).

---

## 2. Ne kuruldu

### 2.1 DocType — `Media Storage Settings` (Single, `Tradehub Core` modülü)

`tradehub_core/tradehub_core/doctype/media_storage_settings/`

| Bölüm | Alanlar | **Kim okuyor** |
|---|---|---|
| 1 · Birincil Depolama | `backend`, `blocker_ack`, `change_reason` | `StorageSettings.from_doctype` (`backend`) |
| 2 · S3 | `s3_endpoint`, `s3_region`, `s3_bucket`, `s3_access_key`, `s3_secret_key` 🔒 | `StorageSettings.from_doctype` → `S3Config` |
| 3 · CDN | `cdn_base_url`, `signed_url_ttl_seconds` | `StorageSettings.from_doctype` |
| 4 · imgproxy | `imgproxy_base_url`, `imgproxy_key` 🔒, `imgproxy_salt` 🔒 | **yalnız `test_connection`** (aşağıda §6.2) |
| 5 · Saklama | `keep_originals`, `original_local_days`, `original_then_action`, `derivative_unused_days`, `derivative_action`, `derivative_regenerate_on_demand`, `trash_retention_days`, `archive_retention_days`, `backup_keep_sets` | `RetentionPolicy.from_mapping` (`retention.py`) |

🔒 = `Password` fieldtype.

**Alan adları uydurulmadı.** `media/pipeline/storage/__init__.py`
`StorageSettings.from_doctype` şu anahtarları okuyor ve DocType birebir onları
kullanıyor: `backend`, `s3_bucket`, `s3_region`, `s3_endpoint`, `s3_access_key`,
`s3_secret_key`, `cdn_base_url`, `signed_url_ttl_seconds`. Saklama bölümü de
`RetentionPolicy.from_mapping`'in iç içe sözlüğüne (`original_retention`,
`derivative_retention`, `soft_delete`, `backup`) `retention_mapping()` ile
çevriliyor. Test bu eşlemeyi sabitliyor
(`test_alan_adlari_fabrikanin_okudugu_adlar`, `test_saklama_alanlari_politikaya_baglanir`);
bir alan yeniden adlandırılırsa test kırmızıya döner.

### 2.2 Şartnameden bilinçli sapmalar

Şartname bazı alan adlarını farklı yazıyor (`s3_access_key_id`,
`s3_secret_access_key`, `storage_mode`, `s3_enabled`). **Fabrikanın okuduğu adlar
kazandı** — görev kuralı buydu ve doğrusu da bu: şartnamenin adını kullanmak,
kaydedilen ama hiç okunmayan bir ayar üretirdi.

Üç alan **bilinçli olarak eklenmedi**, hepsi aynı gerekçeyle — *bugün hiçbir kod
okumuyor; sır taşıyan bir yönetim ekranında ölü kontrol, kapalı kapıya "açık"
yazmaktır*:

| Alan | Neden yok |
|---|---|
| `s3_enabled` | `StorageSettings.from_doctype` böyle bir alan okumuyor; `backend != local` zaten o kararı taşıyor (kodun kendi yorumu da bunu söylüyor). |
| `mirror_write_both` | `doctype_specs/media_storage_settings.json`'da var ama **fabrika okumuyor** — `from_doctype` içinde yalnız bir *yorumda* geçiyor (`# mirror_write_both işaretliyse…`), koda hiç girmiyor. **Bulgu, aşağıda §6.1.** |
| `cdn_purge_api_url` / `cdn_purge_token` / `imgproxy_allowed_profiles` / `derivative_always_keep_profiles` | Hiçbir okuyucu yok. |
| `imgproxy_enabled` | Açılınca hiçbir şey değişmezdi (§6.2). |

### 2.3 Rol — `Media Superadmin`

`tradehub_core/patches/v15_9_25_media_storage_settings.py` yaratıyor
(`desk_access=1`, `is_custom=1`). **Hiçbir kullanıcıya otomatik atanmıyor**: sır
taşıyan bir ekranın anahtarı yamayla dağıtılmaz.

```
MariaDB> SELECT name FROM `tabRole` WHERE name='Media Superadmin';
name
Media Superadmin
```

Rol bugüne kadar `media/pipeline/doctype_specs/` altındaki **12** tasarım
JSON'unda anılıyordu ama DB'de **yoktu**; Frappe olmayan bir role verilen DocPerm
satırını sessizce yok sayar, yani o 12 dosyanın izin modeli kâğıt üstünde
kalıyordu.

### 2.4 Uçlar

Her ikisi de DocType controller'ında (`@frappe.whitelist()`):

- `…media_storage_settings.get_storage_status` — fabrikanın kurduğu gerçek planı
  döner (`mode`, `requested_mode`, `degraded`, `reasons`, `signer_available`),
  açık kapı listesini, saklama politikasını ve `boto3_available`'ı. **Sır yok.**
- `…media_storage_settings.test_connection(target)` — `s3` / `cdn` / `imgproxy`.
  **Sır yok.**

### 2.5 Panel ekranı

`admin-panel/frontend/src/views/system/MediaStorageSettingsView.vue`
· rota `/media-storage-settings` (`meta.roles: ["Media Superadmin"]`)
· menü `nav.item.mediaStorageSettings` (`requires: ["Media Superadmin"]`)
· i18n **tr/en/ar/ru** dördü de.

Rota `requiresSuperAdmin` ile DEĞİL `roles` ile kapatıldı: o meta yalnız
`auth.isAdmin`'i geçirir ve ekranın asıl sahibi olan `Media Superadmin` rolünü
dışarıda bırakırdı. `canAccess()` admin'i zaten geçiriyor.

Sır alanları **boş** yüklenir ve yalnız doldurulursa gönderilir. Backend Password
fieldtype kullandığı için REST yanıtı yıldız döndürür; o yıldızları geri POST
etmek gerçek sırrı `**********` dizesiyle **ezerdi**.

---

## 3. Zorunlu kanıt

### 3.1 Şifreleme — DB'de düz metin YOK

Ayara `minioadmin` yazıldı (`s3_secret_key`), sonra ham SQL ile okundu:

```
MariaDB> SELECT field, value FROM `tabSingles`
         WHERE doctype='Media Storage Settings'
           AND field IN ('s3_access_key','s3_secret_key','s3_bucket','s3_endpoint');
field              value
s3_access_key      minioadmin              ← Data alanı, sır DEĞİL (kullanıcı adı muadili)
s3_bucket          t051-panel-probe
s3_endpoint        http://minio:9000
s3_secret_key      **********              ← SIR: yıldız

MariaDB> SELECT fieldname, LEFT(password,60) AS sifreli_bas, LENGTH(password)
         FROM `__Auth` WHERE doctype='Media Storage Settings';
fieldname       sifreli_bas                                                    uzunluk
s3_secret_key   gAAAAABqhbuenfvp23cfCMzl1YYzKNiQM_6fkdNnvvVcxX4cyk4JMOqB0RV5   100

MariaDB> SELECT COUNT(*) FROM `__Auth`
         WHERE doctype='Media Storage Settings' AND password='minioadmin';
0
```

`gAAAAAB…` Fernet (AES-128-CBC + HMAC) belirtecidir; anahtar
`site_config.encryption_key`'den gelir. Kendi şifrelememiz **yazılmadı**.

Aynı ölçüm testte de sabit: `test_gizli_anahtar_veritabaninda_duz_metin_degil`.

### 3.2 İzolasyon — üç yönlü, ölçüldü

`bench run-tests --module tradehub_core.tests.test_media_storage_settings`

| Yön | Test | Sonuç |
|---|---|---|
| (i) `Media Superadmin` **okur + yazar** | `test_media_superadmin_okur_ve_yazar` — `has_permission(read/write)` + `get_storage_status()` | ✔ |
| (ii) Satıcı **OKUYAMAZ** (yalnız yazamaz değil) | `test_satici_OKUYAMAZ` — 5 rol × `read`/`write` + kanca · `test_satici_rest_ucundan_da_okuyamaz` (`frappe.client.get`) · `test_satici_whitelist_uclarindan_reddedilir` | ✔ |
| (iii) `Guest` **reddedilir** | `test_guest_reddedilir` | ✔ |

Sınanan roller: `Marketplace Seller`, `Seller`, `Seller Owner`, `Buyer`, `Customer`.
Üçü de **okuma** düzeyinde ölçüldü, `write` ile yetinilmedi.

İki kat: (a) DocPerm listesinde yalnız `Media Superadmin` + `System Manager` var —
Frappe'de listede olmayan rol hiçbir hak almaz; (b) `hooks.py` `has_permission` →
`permissions.media_storage_settings_has_permission` rol kümesini ayrıca daraltır.
`_is_platform_full_access` bilerek kullanılmadı: `Compliance Officer` /
`Platform Finance` gibi geniş okuma rollerinin bu ekranda işi yok.

### 3.3 Sızıntı yok

**Bağlantı testi yanıtı** (MinIO'ya karşı, gerçek tur):

```json
{"target": "s3", "ok": true, "ms": 450.6, "steps": [
  {"step": "connect", "ok": true, "ms": 0.1,   "detail": "t051-panel-probe"},
  {"step": "write",   "ok": true, "ms": 427.8, "detail": "66/662f478333b080d0789b447e5f03f59b.txt"},
  {"step": "read",    "ok": true, "ms": 6.8,   "detail": "39 bayt"},
  {"step": "delete",  "ok": true, "ms": 13.2,  "detail": ""}]}
```

Sır yok. `test_baglanti_testi_sir_dondurmez` üç hedefin (s3/cdn/imgproxy) yanıtını
JSON'a çevirip üç sırrın hiçbirinin geçmediğini doğruluyor.

**Log tarafı** — `frappe.log_error` çıktısı grep'lendi:

```
MariaDB> SELECT name, creation, LEFT(error,120) FROM `tabError Log`
         WHERE method='media_storage_settings.status' ORDER BY creation DESC LIMIT 6;
ko11c4vnj3  17:19:44  boto3 imza hatasi: secret=***
kd4hk6rrvv  17:19:09  boto3 imza hatasi: secret=TH-PROBE-SECRET-6f2b9c41d7e8   ← VACUITY PROBE (maskeleme kapalıydı)
jfg92vgq9m  17:17:34  boto3 imza hatasi: secret=***
ilil7t9m59  17:16:11  boto3 imza hatasi: secret=***
i0tjlugs9i  17:15:05  boto3 imza hatasi: secret=***
hmp11msp5s  17:14:32  boto3 imza hatasi: secret=***
```

Maskeleme açıkken **her** satır `secret=***`. Tek düz metin satırı vacuity
probu (§5, D) sırasında yazıldı ve ölçüm bitince silindi.

**Denetim kaydı**:

```
context: {"changed": {"s3_endpoint": {"old":"","new":"http://minio:9000"},
                      "s3_region":   {"old":"","new":"us-east-1"},
                      "s3_bucket":   {"old":"","new":"t051-panel-probe"},
                      "s3_access_key":{"old":"","new":"minioadmin"},
                      "cdn_base_url":{"old":"","new":"http://minio:9000/t051-panel-probe"},
                      "s3_secret_key": "changed"},          ← DEĞER YOK, yalnız olay
          "backend":"local", "blocker_ack":0, "acknowledged_blockers":[],
          "reason":"T-051 canli baglanti testi"}
```

> **Dikkat:** yukarıdaki `minioadmin` **erişim anahtarıdır** (`s3_access_key`,
> `Data` alanı), gizli anahtar değil. MinIO varsayılanı ikisi için de aynı dizeyi
> kullandığı için karışabiliyor; gerçek dağıtımda ikisi farklıdır. Gizli anahtar
> kayda `"changed"` olarak giriyor.

### 3.4 Bağlantı testi gerçekten bağlanıyor

MinIO (`istoc-dev-minio-1`, S3 API `minio:9000`) üzerinde tam **yaz → oku → sil**
turu: §3.3'teki çıktı. CDN testi `http://minio:9000/t051-panel-probe`'a HEAD
attı → `HTTP 403` (bucket public değil) — yani istek gerçekten gitti ve gerçek
kod döndü, uydurma değil.

---

## 4. Ekran S3'ü açtırmıyor — 23 numaralı raporun §7'si burada görünür

`backend != local` kaydedilmek istendiğinde controller **reddediyor** ve açık
kapıları listeliyor:

```
B-02: S3Storage.exists() ağ hatasında istisna atıyor; tiered kipinde render kırar.
B-04: TieredStorage.delete() sıcaktan siler, soğuk düşükken istisna atar (KVKK).
B-05: media_mirror_queue=inline üretim ayarında henüz reddedilmiyor.
boto3 imaja alınmadı — bugünkü kurulum konteyner ömürlü.
mirror.reconcile() hiçbir zamanlayıcıya bağlı değil.
tiered için age_days ölçülmedi (DEFAULT_AGE_DAYS=90 bir varsayılan seçimi).
```

Yönetici `blocker_ack` kutusunu işaretlemeden kaydedemiyor
(`test_s3_kipi_onay_kutusu_olmadan_kaydedilemez`), işaretlerse turuncu uyarı
basılıyor ve **kabul ettiği engeller denetim kaydına yazılıyor**
(`acknowledged_blockers`). Aynı liste panelde de sarı kutuda görünüyor.

> **B-01 listede YOK, bilerek:** 23 numaralı raporun B-01'i (`SigV2` presigned
> URL) `s3.py` içinde `signature_version="s3v4"` ile **kapatılmış** durumda —
> kod okundu, `_client()` içinde sabitlenmiş ve dosyanın yorumu bunu B-01'e
> atıfla açıklıyor. Kapanmış bir kapıyı listede tutmak, listeyi okunmaz yapardı.

Ayrıca `local` dışı kip **kovasız** kaydedilemiyor (boşken fabrika zaten yerel
diske düşerdi — `test_s3_kipi_kovasiz_kaydedilemez`), ve saklama politikası kendi
içinde tutarsızsa (örn. `keep_forever=0` iken `local_days=0`) kayıt reddediliyor —
doğrulama **`RetentionPolicy.validate()`'in kendisiyle** yapılıyor, kural
kopyalanmadı.

---

## 5. Vacuity — testler gerçekten bir şey ölçüyor mu

Dört koruma sırayla **geçici olarak kaldırıldı**, testler koşuldu, sonra geri kondu.

| # | Kaldırılan koruma | Kırmızıya dönen testler |
|---|---|---|
| **A** | `_require_superadmin()` gövdesi (uç kapısı) | `test_guest_reddedilir`, `test_satici_whitelist_uclarindan_reddedilir` → `AssertionError: PermissionError not raised` |
| **B** | `has_permission` kancası `True` döndü **+** DocPerm'e `Marketplace Seller` read/write eklendi | `test_satici_OKUYAMAZ` (`True is not false : Marketplace Seller ayarı OKUYABİLİYOR`), `test_satici_rest_ucundan_da_okuyamaz`, `test_docperm_listesinde_yalnizca_iki_rol_var` |
| **C** | `s3_secret_key` fieldtype `Password` → `Data` | `test_gizli_anahtar_veritabaninda_duz_metin_degil` (`'TH-PROBE-SECRET-…' unexpectedly found in 'TH-PROBE-SECRET-…'` — sır `tabSingles`'a **düz metin** düştü), `test_tum_sirlar_password_fieldtype` |
| **D** | `_maskele()` kimlik fonksiyonuna çevrildi | `test_maskeleme_sirri_gercekten_siler`, `test_hata_yolunda_sir_ne_yanita_ne_loga_dusmez` |

C probu en değerlisi: `Data` fieldtype ile sır `tabSingles`'ta **birebir** görünüyor.
`Password` ile görünmüyor. Yani §3.1'deki kanıt fieldtype seçiminden geliyor,
tesadüften değil.

Her probdan sonra dosya orijinaline geri kondu ve **19/19 yeşil** doğrulandı.
Konteyner ile yerel dosyalar `diff` ile karşılaştırıldı: `permissions.py`,
`hooks.py`, `patches.txt`, DocType JSON — dördü de **SAME**.

---

## 6. Bulgular (düzeltilmedi — dokunulmaz dosyalarda)

### 6.1 `mirror_write_both` — yorum kodun yaptığını söylemiyor

`media/pipeline/storage/__init__.py` `StorageSettings.from_doctype`:

```python
return cls(
    mode=kip, site_path=site_path, s3=s3_konf,
    signed_url_ttl_seconds=int(doc.get("signed_url_ttl_seconds", 0) or 0),
    # `mirror_write_both` işaretliyse kip ne olursa olsun ayna istenir.
    mirror_queue=QUEUE_THREAD,
)
```

Yorum bir davranış vaat ediyor; **kod o alanı hiç okumuyor.** Tasarım JSON'u
(`doctype_specs/media_storage_settings.json`) alanı tanımlıyor. Bu ayarı ekrana
koymak, işaretlenince hiçbir şey yapmayan bir kutu üretirdi — koymadım.
**Kapanışı:** ya `from_doctype` alanı okuyup `mode`'u `mirror`'a yükseltmeli, ya
yorum silinmeli. `storage/*.py` bu görevde dokunulmaz olduğu için ikisi de
yapılmadı.

### 6.2 imgproxy hiçbir yerde okunmuyor

`tradehub_core/` + `docs/` altında `imgproxy` geçen satır sayısı: **0** (ölçüldü,
`grep -rn`). Şartname beşinci bölümü istiyor; bölüm kuruldu ama tek tüketicisi
`test_connection`. Bu yüzden `imgproxy_enabled` şalteri **konmadı** ve bölüm
açıklaması bunu ekranda da söylüyor. Anahtar/tuz şifreli saklanıyor, yani
teslimat yolu bağlandığında ayar hazır olacak.

### 6.3 Denetim kaydı Medya Denetimi ekranında görünmüyor

`log_media_event(action="media.storage_settings_changed", …)` kaydı
`Authorization Decision Log`'a **yazılıyor** (§3.3 çıktısı) ve SQL ile
sorgulanabiliyor. Ama `media/audit.py::list_events` kayıtları `MEDIA_ACTIONS`
tuple'ına göre süzüyor ve yeni sabit o tuple'da yok — panelin *Medya Denetimi*
ekranında satır görünmez. `media/audit.py` bu görevin dokunulabilir dosya
listesinde olmadığı için eklenmedi. **Kapanışı tek satır:**
`MEDIA_ACTIONS` demetine `"media.storage_settings_changed"` eklemek.

### 6.4 `Media Engine Settings` bayrakları AÇIK (bu iş değil)

Görev "bayraklar 0 kalsın" diyordu. Ölçüm sonunda:

```
media_pipeline_enabled  1
rendition_on_upload     1
manifest_api_enabled    1
active_slots            product.image     (modified 17:27:05)
```

**Bu iş o DocType'a hiç dokunmadı** — kodun tamamı yalnız `Media Storage Settings`
okuyor/yazıyor. `tabVersion`'daki son sürüm kaydı (12:38) bayrakları **0**
yapmıştı; sonraki değişiklik sürüm satırı bırakmadan yazılmış
(`frappe.db.set_single_value` versiyonlamayı atlar) ve zaman damgası paralel
ajanın koşum penceresine düşüyor. Karar sahibi olmadığım için **geri
çevirmedim**; sahibinin bilinçli bırakıp bırakmadığı doğrulanmalı.

---

## 7. Koşulan komutlar ve çıktıları

### Backend

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate      → OK
$ … mariadb -e "SELECT name FROM tabRole WHERE name='Media Superadmin'"     → 1 satır
$ … mariadb -e "SELECT field,value FROM tabSingles WHERE doctype='Media Storage Settings'"
                                                                            → 12 varsayılan yazıldı, backend=local
$ … run-tests --module tradehub_core.tests.test_media_storage_settings      → Ran 19 tests … OK
$ … run-tests --module tradehub_core.tests.test_kyc_tenant_isolation        → Ran 13 tests … OK
$ … run-tests --module tradehub_core.tests.test_storage_adapters            → Ran 137 tests … OK
$ … run-tests --module tradehub_core.tests.test_retention                   → Ran 47 tests … OK (skipped=1)
$ … run-tests --module tradehub_core.tests.test_media_access                → Ran 17 tests … OK
```

### Panel

```
$ npm run lint    → 0 error (2 uyarı, ikisi de PlansTab.vue'da ÖNCEDEN vardı)   EXIT 0
$ npm test        → tests 249 · pass 249 · fail 0                                (taban 240 → +9)
$ npm run build   → ✓ built in 23.27s                                            EXIT 0
                    dist/assets/MediaStorageSettingsView-7gCPCTuo.js  13.22 kB
```

`git diff --stat` (tradehub_core): `hooks.py` **+67/-0**, `permissions.py`
**+176/-0**, `patches.txt` **+5/-0** — üçü de **sıfır silme** (rakamlara paralel
ajanların aynı dosyalara yaptığı eklemeler de dahil).

---

## 8. Değişen / eklenen dosyalar

**tradehub_core (yeni)**
- `tradehub_core/tradehub_core/doctype/media_storage_settings/{__init__.py,media_storage_settings.json,media_storage_settings.py}`
- `tradehub_core/patches/v15_9_25_media_storage_settings.py`
- `tradehub_core/tests/test_media_storage_settings.py`
- `docs/reports/25-t051-depolama-ayarlari.md` (bu belge)

**tradehub_core (yalnız ekleme)**
- `tradehub_core/permissions.py` — `media_storage_settings_has_permission`
- `tradehub_core/hooks.py` — `has_permission["Media Storage Settings"]`
- `tradehub_core/patches.txt` — 1 satır

**admin-panel (yeni)**
- `frontend/src/views/system/MediaStorageSettingsView.vue`
- `frontend/src/views/system/__tests__/mediaStorageSettings.test.js`

**admin-panel (yalnız ekleme)**
- `frontend/src/router/index.js`, `frontend/src/data/navigation.js`
- `frontend/src/i18n/locales/{tr,en,ar,ru}.js`

**Dokunulmayanlar (görev kısıtı):** `media/pipeline/storage/*.py`,
`media/file_isolation.py`, `api/media_manifest.py`, `api/seller_media.py`,
`media/browse.py`, `media/presets.py`, `media/audit.py`, `docs/standards/`,
`kyc_verification` ile ilgili her şey, `docker/`.

---

## 9. Sırada ne var

1. `MEDIA_ACTIONS`'a tek satır (§6.3) — denetim kaydı panelde görünsün.
2. `mirror_write_both` kararı (§6.1) — ya oku ya yorumu sil.
3. `Media Superadmin` rolü **hiç kimseye atanmadı**; ilk atama bilinçli bir
   yönetim kararı olarak yapılmalı.
4. imgproxy teslimat yolu (§6.2) bağlandığında `imgproxy_enabled` şalteri
   anlamlı hale gelir; o zaman eklenmeli.
5. S3 açılışı: 23 numaralı raporun §7 sırası. Bu ekran o kapıları görünür
   kıldı, açmadı.
