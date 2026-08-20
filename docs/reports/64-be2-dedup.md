# 64 — BE2: Dedup zinciri üretime bağlandı (T-042)

**Tarih:** 2026-08-20 · **Kapsam:** `pipeline_bridge` hash devri + dup-arama ucu + FE ön kontrol uyarısı
**Öncül ölçüm (rapor 57):** `core/dedup.py` doğru 4-girdili `version_hash`'i tanımlıyordu ama üretimdeki
köprü kendi TEK girdili sürümünü kullanıyor, URL'e hash koymuyordu; FE'de "bu dosya kütüphanenizde"
uyarısı ve sha256 arayan bir whitelist ucu HİÇ yoktu.

---

## 1. Köprü → kütüphane devri (`media/pipeline_bridge.py`)

- Eski tek girdili `version_hash(doc)` **içerik parmak izidir** (`sha256(içerik)[:32]`), sürüm kimliği
  değil. Adı `content_fingerprint(doc)` oldu; **`version_hash = content_fingerprint` takma adı duruyor**.
  Dış çağıran ölçümü (grep, 2026-08-20): yalnız `tests/test_pipeline_bridge.py` (3 çağrı) — takma adla
  kırılmadı, testin biri bilerek eski adla çağırmaya devam ediyor (uyumluluk kanıtı).
- Worker (`_run_rendition_job`) artık sürüm kimliğini **kütüphaneden** üretir:
  `dedup.version_hash(source_hash, policy_snapshot, crop_intent=None, engine_version)`.
  - `source_hash`: içeriğin TAM 64 haneli SHA-256'sı (`dedup.stream_sha256`) — 32'lik kısaltma değil.
  - `policy_snapshot`: `render.load_slot_policy(slot_key)` (kayda kopyası yazılır).
  - `crop_intent`: `None` — kırpma niyeti hattı köprüde henüz kurulu değil (mevcut `_render_one` notuyla tutarlı).
  - `engine_version`: `pillow-<PIL.__version__>` (canlıda `pillow-11.3.0`).
- Her üretim bir **`Media Version`** kaydı açar/bulur (autoname = `field:version_hash`, UNIQUE; yarış
  `dedup.idempotent_create` + `DuplicateEntryError/UniqueValidationError` ile idempotent, INV-06).
- Türev dosyaları artık **hash taşıyan adrese** yazılır (`dedup.rendition_path`):
  `/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{uzantı}` (INV-09).
- **Geriye dönük İŞ YOK:** mevcut dosya adları/URL'leri/`Media Rendition.file_url` değerlerine
  dokunulmadı; manifest URL'leri veritabanından okuduğu için iki düzen yan yana yaşar
  (`api/media_manifest.py` başlığındaki çelişki YENİ üretimler için `/files/media/…` lehine kapandı).
- İdempotency kapıları değişmedi: kanca tarafı içerik parmak izinden karar vermeye devam ediyor
  (dosya ADINDAN okunabildiği için içerik okumadan) — bilinçli; bkz. §6 kalanlar.

## 2. Dup-arama ucu

**İmza:** `POST /api/method/tradehub_core.api.seller_media.find_in_my_library`
girdi `sha256: str` (64 hex, istemci hesaplar) → çıktı:

```json
{"found": true,  "file": {"file_url": "/files/ab/ab…32.jpg", "file_name": "urun.jpg", "uploaded_at": "2026-08-20 06:49:56"}}
{"found": false, "file": null}
```

- **Mağaza OTURUMDAN** (`_store()` → `ownership.current_store`), parametreyle mağaza ALINMAZ.
- Sorgu `media/inventory.py::find_by_sha256` — envanter listesinin KENDİ taban sorgusu
  (`_base_query`: public, klasörsüz, KVKK/hassas-hash emniyet kemerleri) + **`ownership.scope`**
  kiracı süzgeci + çöp dışlama. Eşleşme yoksa cevap her koşulda aynı `{"found": false}` —
  başka mağazada var olduğu SEZDİRİLMEZ.
- **İçerik hash'i nerede — kendim ölçtüm (canlı dev DB, 2026-08-20):**
  - `tabFile.content_hash` 5.047/5.047 kayıtta dolu ama **MD5** (`430483d1…` ≠ sha256).
  - İçerik-adresli adlar (`/files/{sha[:2]}/{sha[:32]}.…`, `media/naming.py`) 86 kayıtta;
    örnek dosya indirilip doğrulandı: `sha256(içerik)[:32]` gövdeyle birebir.
  - `Media Asset.content_sha256` 32 haneli kısaltma taşır ve dev'de 0 satır.
  → Eşleşme bu yüzden **içerik-adresli addan** yapılır; tam sha256 kalıcı olarak yalnız YENİ
  `Media Version.source_hash`'te birikmeye başladı.
- **Bilinçli sınır:** içerik-adresli adlandırmadan önce yüklenmiş dosyalar (dev ölçümü: 4.961/5.047)
  bu aramada görünmez — eksik uyarı kabul, yanlış pozitif değil. Eskileri kapsamak backfill işi.

## 3. Tenant izolasyon testi — vacuity + kırmızı kanıt

`tradehub_core/tests/test_media_dedup_endpoint.py` (yeni, 7 test). Konteynerde koşuldu:

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_media_dedup_endpoint
.......
Ran 7 tests in 3.752s
OK
```

- **İzolasyon:** B'nin dosyasının sha256'sı A'nın oturumunda `{"found": false, "file": null}`.
- **Vacuity kanıtı (aynı test):** AYNI hash B'nin oturumunda `found: true` + doğru
  `file_url/file_name/uploaded_at` — A'daki "yok" boş doğru değil.
- **Kırmızı kanıt 1 (test olarak):** `test_kirmizi_kanit_izolasyon_suzgeci_olmadan_dosya_bulunur` —
  `ownership.scope` atlanınca taban sorgu dosyayı BULUR; A'ya daraltınca kaybolur.
- **Kırmızı kanıt 2 (gevşetilmiş koşu, ölçüldü):** `inventory.ownership.scope` konteynerde
  kimlik fonksiyonuyla yamanıp izolasyon testi koşuldu → **FAILED (failures=1)**, fark çıktısında
  A'nın sorgusu B'nin dosyasını `found: True` döndürüyor. Süzgeç yerindeyken aynı test yeşil.
- Ayrıca: geçersiz hash `frappe.throw`, mağazasız kullanıcı `PermissionError`, eski adlandırmalı
  dosya SAHİBİNE bile dönmez, çöpe atılan dosya dönmez, ön koşul olarak `write_file` hook'unun
  devrede olduğu her koşuda doğrulanır (hook düşerse test sessizce geçmek yerine kurulumda patlar).

Köprü testleri (`test_pipeline_bridge.py`, mevcut modül güncellendi): e2e test artık
`Media Version` kaydını, `source_hash`'in 64 hane olduğunu, hash'in kütüphane formülüyle yeniden
hesaplanabildiğini ve türev adresinin `dedup.parse_rendition_path` ile çözülüp aynı `version_hash`'i
taşıdığını ölçüyor:

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_pipeline_bridge
...................
Ran 19 tests in 1.108s
OK
```

## 4. FE uyarısı — hangi katmanda

- **Saf modül (yeni):** `admin-panel/frontend/src/lib/media/upload/dedupCheck.js` —
  `sha256Hex` (WebCrypto `crypto.subtle.digest`, YENİ BAĞIMLILIK YOK), `findDuplicateInLibrary`
  (ucu çağırır, HER aksama fail-open `null`), `duplicateFinding` (severity **WARN** — gerçek
  `hasBlocker` kapısına göre engel DEĞİL). Bellek tavanı `DEDUP_MAX_BYTES = 64 MiB`
  (WebCrypto akışlı özet desteklemiyor; üstü atlanır).
- **Kuyruk bağlama noktası:** `src/composables/useMediaUpload.js::onKontrol` — slot ön kontrolü +
  sunucu genel politikası GEÇTİKTEN sonra sorulur (engellenmiş satır için hash/istek harcanmaz).
  Eşleşmede satır yeni `ITEM_STATUS.DUPLICATE` durumunda BEKLER; `proceed(id)` ("yine de yükle")
  READY yapar ve başlatır. Uyarı bulgusu karar sonrası da satırda kalır. **Engelleme değil:**
  bulgu WARN, `blocked` durumu/`blocked` olayı kullanılmıyor; kontrolün kendisi çökerse yükleme
  kesintisiz sürer.
- **Ekran:** `UploadQueueRow.vue` — satırda "Bu dosya kütüphanenizde: {name}" satırı + "Yine de
  yükle" düğmesi + `copy` durum ikonu; `MediaUploader.vue` `proceed` olayını kuyruğa bağlar.
  Bulgu ayrıca `PreflightPanel`'de `media.preflight.reason.duplicate_in_library` anahtarıyla görünür.
- `useSellerMedia.js`'e DOKUNULMADI ve **gerek de çıkmadı** — bağlama noktası `useMediaUpload` oldu.

**FE test sonuçları (yalnız kendi dosyalarım + dokunduğum alan):**

```
$ node --test src/lib/media/upload/__tests__/dedupCheck.test.js
tests 12 · pass 12 · fail 0        (yeni dosya)

$ node --test src/lib/media/upload/__tests__/{queue,preflight,session}.test.js
tests 64 · pass 64 · fail 0        (queue.test.js'e kopya-akışı testi eklendi:
                                    DUPLICATE'te tek bayt gitmiyor → proceed → DONE)
$ npm run build                     ✓ built in 7.18s (SFC/SCSS doğrulaması)
```

## 5. Eklenecek i18n anahtarları (locale dosyalarına DOKUNULMADI — locale sahibine)

| Anahtar | Önerilen TR | Not |
|---|---|---|
| `media.preflight.reason.duplicate_in_library` | `Bu dosya kütüphanenizde: {name}` | PreflightPanel bulgu satırı |
| `media.preflight.fix.duplicate_in_library` | `Yine de yükleyebilir ya da kütüphanedeki kopyayı kullanabilirsiniz.` | isteğe bağlı düzeltme satırı |
| `media.uploader.duplicateLine` | `Bu dosya kütüphanenizde: {name}` | kod içinde `t(key, {name}, "…")` varsayılanı VAR |
| `media.uploader.uploadAnyway` | `Yine de yükle` | kod içinde varsayılanı VAR |
| `media.uploader.status.duplicate` | `Kütüphanede var` | **varsayılansız** dinamik anahtar (`status.${item.status}`) — eklenene dek satır durum etiketi ham anahtar görünür |

(en/ru/ar karşılıkları locale sahibinin işi.)

## 6. hooks/patches ihtiyacı + kalanlar

- **`hooks.py` / `patches.txt` değişikliği GEREKMEDİ:** kanca kaydı (`File.after_insert` →
  `maybe_generate_renditions`) zaten var; `Media Version` DocType'ı ve indeksleri `v15_9_29` ile
  zaten kurulu (konteynerde tablo doğrulandı, 0 satır). Migrate gerekmedi, kilit kullanılmadı.
- **Kalan işler (bu görevin bilinçli sınırları):**
  1. Backfill — eski dosyaların sha256 kimliği ve eski türev adreslerinin taşınması (ayrı görev).
  2. `Media Rendition`'da `version` Link alanı + `(version, profile, width, format)` UNIQUE (T-040
     kabulü) yok; şema değişikliği + migrate ister, bu görevde açılmadı. Türevler sürüme bugün
     `file_url`'deki hash üzerinden bağlanabiliyor.
  3. Worker idempotency'si hâlâ içerik+slot bazlı (`_renditions_exist`): politika/motor değişiminde
     yeniden üretim tetiklenmez — sürüm-farkındalıklı yeniden üretim ayrı iş.
  4. FE `DEDUP_MAX_BYTES` (64 MiB) üstü dosyalarda uyarı atlanır (WebCrypto akışsız); videoların
     bir kısmı kapsam dışı.

---

## EK (2026-08-20, devam görevi) — Hassas-ikiz deliği kapatıldı (rapor 69 §7.2)

**Bulgu (W3-B, gerçek veriyle):** optimize akışının `sensitive_content_twin` gerekçesiyle
REDDETTİĞİ içeriği bu köprü işledi — `_resolve_scope` yalnız seçilen `File` satırının
`is_private`/`attached_to`suna bakıyordu, `_has_sensitive_twin` (içerik-ikizi) kontrolü yoktu.

### Düzeltme

`pipeline_bridge._resolve_scope` sonuna `_sensitive_twin_blocked(doc)` eklendi:

- **Kontrolün tek kaynağı `runner._has_sensitive_twin`** (kopya yazılmadı — `audit.py` ve
  `trash.py` ile aynı desen): aynı `content_hash` private ya da hassas doctype'lı başka bir
  `File` kaydında varsa üretim YOK.
- **Gerekçe kodu optimize akışıyla AYNI:** `sensitive_content_twin`; denetim kaydı da aynı —
  `audit.ACTION_SCOPE_DENIED`, `sensitive=True` (URL denetime yazılmaz), `commit=False`
  (kanca `File` insert transaction'ında koşar; worker tarafında RQ işi sonunda commit'lenir).
- **Tek bilinçli fark:** `frappe.throw` yok — kanca best-effort (yükleme kırılmamalı), worker
  istisna sızdırmamalı; davranış "sessizce kapsam dışı". Kontrol `_resolve_scope`'un EN SONUNDA:
  zaten kapsam dışı dosyalar için fazladan sorgu koşmaz. `_resolve_scope` hem kancadan hem
  worker'dan çağrıldığı için iki yol da kapalı.
- `content_hash` boşsa kontrol atlanır — `runner._assert_in_scope` ile aynı sınır.

### Canlı doğrulama (konteynerde ölçüldü)

W3-B'nin vakası `File eab7be88e1` (`…_nf.jpg`, public ürün görseli; aynı `content_hash
9bb904b3d2…` **2 private KYB Verification ekinde** daha var — toplam 5 File satırı):
düzeltme sonrası `_resolve_scope(eab7be88e1) → None` ve Listing'e bağlı public kopyası
`90891e3cef → None`. Üretim yolu bu içerik için artık kapalı.

### Üretilmiş SIZINTI ENVANTERİ — temizlenMEDİ (karar sahibine; veri kaybı riski)

Vaka için ÜRETİLMİŞ ve şu an duran kayıtlar (10/10 diskte, bayt DB ile birebir; toplam **315.836 B**):

- `Media Asset 7m7n6rs4d4` (`state=ready`, `content_sha256=386ed2a26fa33f4f…` [32]) +
  `Media Version f535478072fa6abf…4ce5cf1945` + `Media Processing Job 7m99jblshq (success)`
- 10 `Media Rendition` + diskteki dosyaları, hepsi
  `/files/media/7m7n6rs4d4/f535478072fa…cf1945/` altında:
  `w96-96.webp (1.484 B)` · `w192-192.webp (3.866)` · `w384-384.avif (13.867)` ·
  `w384-384.webp (10.864)` · `w640-640.avif (34.468)` · `w640-640.webp (28.746)` ·
  `w768-768.avif (47.107)` · `w768-768.webp (39.122)` · `w1280-864.avif (74.580)` ·
  `w1280-864.webp (61.732)`

Not: içeriğin kendisi zaten public bir ürün görseli olarak yayında (`/files/4691…_nf.jpg`);
türevler ek açık kopyalardır. Silme/maskeleme kararı ve manifest etkisi ayrı iş.

### Test (konteynerde, tam modül)

`test_pipeline_bridge.py`'ye `TestHassasIkiz` (3 test) eklendi:

1. ikizli içerik kancadan kuyruğa GİRMEZ (`enqueue` çağrılmaz);
2. worker da üretmez (`Media Asset` açılmaz) — kuyruğa bayrak açıkken girmiş iş senaryosu;
3. **vacuity/kırmızı kanıt:** `runner._has_sensitive_twin` kaldırılınca (`return False` yaması)
   AYNI dosya kuyruğa girer (`enqueue` 1 kez) — yani 1–2'nin engeli tam olarak bu kontrol;
   kontrol gevşetilirse üçlü kırmızıya döner. Ön koşul olarak iki kaydın gerçekten aynı
   `content_hash`i taşıdığı setUp'ta doğrulanır (taşımıyorsa test kurulumda patlar, boş geçmez).

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_pipeline_bridge
......................
Ran 22 tests in 1.306s
OK
$ … run-tests --module tradehub_core.tests.test_media_dedup_endpoint
Ran 7 tests in 3.648s
OK        (bayraklar W3-B'nin bıraktığı gibi AÇIKKEN yeniden koşuldu)
```

---

## EK-2 (2026-08-20, devam görevi) — Katman 2: dönüştürülen/işlenmiş görsellerde dedup uyarısı (rapor 75 kusur #2)

**Bulgu (panel E2E ajanı):** sunucu görselleri yükleme anında dönüştürüyor (PNG→WebP,
`api/seller_media._kaydet`, `File.insert`'ten ÖNCE) → saklanan içeriğin adı/hash'i, istemcinin
ORİJİNAL dosyadan hesapladığı sha256'dan ayrışıyor → katman 1 (içerik-adresli ad) görsellerde
yapısal olarak ölü; FE uyarısı hiç tetiklenmiyordu.

### Ölçümler (konteynerde, karar öncesi)

- `Media Version.source_hash` = SAKLANAN kaynak dosyanın sha256'sı — 3/3 canlı kayıtta diskteki
  baytlarla birebir doğrulandı. İşlenmiş 9 varlığın **9'unun kaynak dosya adı legacy düzende**
  (hash taşımıyor) ve **9'unda `owner_seller` dolu** (SEL-xxxxx/DEMO-001) — katman 2'nin kiracı
  kemeri gerçek veride çalışır durumda.
- W3-B'nin "source_hash = orijinalin sha256'sı" doğrulaması o 9 dosya İÇİN doğru: onlar
  dönüştürülMEDEN saklanmış legacy yüklemeler (saklanan = orijinal). Yükleme anında dönüştürülen
  YENİ görsellerde ise `source_hash` da dönüştürülmüş baytların hash'idir (kod:
  `_ensure_version` `doc.get_content()`ten okur; testte ölçüldü) — bkz. kalan boşluk.

### Uygulanan: iki katmanlı arama (`inventory.find_by_sha256`)

Uç imzası DEĞİŞMEDİ (`find_in_my_library(sha256)`); arama artık iki katman:

1. **Katman 1 (mevcut):** içerik-adresli dosya adı — dönüşmeden saklanan türler.
2. **Katman 2 (yeni, `_find_by_pipeline_source_hash`):** `Media Version.source_hash = sha256`
   → `Media Asset` → kaynak `File` → `file_url`. **Kiracı kemeri SQL'İN İÇİNDE:**
   `Media Asset.owner_seller = store` (sonradan süzme değil; sahipsiz varlıklar kimseye dönmez).
   Kaynak dosya ayrıca envanterin hijyen kemerlerinden geçer (`_base_query`: public, KVKK-dışı,
   **hassas-ikiz maskesi**) + çöp dışlaması — envanterin gizlediği dosyayı bu uç geri sızdıramaz.

### Testler (konteynerde; `TestKatman2SourceHash`, 4 yeni — toplam 11/11 OK)

Fixture GERÇEK yoldan: `upload_media` (gerçek PNG→WebP dönüşümü; sapma ön koşul olarak assert
edilir) → Listing'e bağla → `_run_rendition_job` (gerçek Asset+Version, `owner_seller=B`) →
ad legacy düzene çevrilir (katman 1 bilerek kör — W3-B'nin 9 dosyasının dünyası).

- **E2E:** işlenmiş dosyanın baytlarının sha256'sı → `found:true`, dönen adres hash taşımayan
  legacy adres (bulan katman 2).
- **Kiracı + vacuity + kırmızı kanıt:** B'nin source_hash'i A'ya `{"found": false}`; aynı hash
  B'de `true` (boş doğru değil); `owner_seller` kemeri OLMADAN aynı join satırı BULUR (A'yı
  koruyan tek şey kemer — gevşetilirse test kırmızı) ve `_find_by_pipeline_source_hash`
  A'ya `None`, B'ye kayıt döner.
- **Hassas-ikiz maskesi:** saklanan içeriğe private ikiz doğunca katman 2 SAHİBİNE bile
  `found:false` — canlı vaka `7m7n6rs4d4` bu uçtan geri sızmaz.
- **Yapısal boşluk sabitleyici:** dönüştürülen görselde ORİJİNAL PNG'nin sha256'sı hiçbir
  katmanda yok → `found:false` assert edilir; kırılırsa biri orijinal hash'i saklamaya
  başlamış demektir (o zaman kapsam genişletilip test güncellenir).

### Canlı E2E (gerçek dosyayla, konteynerde ölçüldü)

`/files/51N9LYNfAVL._AC_SY395_.jpg` (işlenmiş, legacy adlı, DEMO-001):

```
sha256[:16]=b461635a449db58b · ad hash taşımıyor (katman 1 kör)
DEMO-001 sordu → {"found": true, "file": {"file_url": ".../51N9LYNfAVL._AC_SY395_.jpg", ...}}
SEL-00014 sordu → {"found": false, "file": null}
nf.jpg (hassas-ikiz) SAHİBİ sordu → {"found": false, "file": null}
```

### Kalan boşluk (bilinçli, kapsam dışı — dosya sahibine)

Yükleme anında DÖNÜŞTÜRÜLEN görsellerde istemcinin ORİJİNAL dosya hash'i hiçbir kayıtta yok
(`source_hash` da dönüştürülmüş baytların hash'i). Bu içerikler için uyarı ancak orijinal
sha256 yükleme anında kaydedilirse çıkabilir — doğal yer `_kaydet` (dönüşümden ÖNCE elindeki
baytların hash'i) ya da spec'teki `Media Source.client_report`; `_kaydet`/şema bu görevin
sahiplik sınırı dışında. FE tarafına dokunulmadı (uyarı zaten orijinal dosyayı hash'liyor —
doğru davranış; kapsama alma işi sunucu tarafında).

Dokunulan dosyalar: `media/inventory.py` (find_by_sha256 iki katmana bölündü),
`api/seller_media.py` (yalnız `find_in_my_library` docstring'i — `_lqip_by_url`'a dokunulmadı),
`tests/test_media_dedup_endpoint.py` (fixture tabanı ayrıştı + 4 yeni test).
`test_pipeline_bridge` yeniden koşuldu: 22/22 OK.
