# 15 — DALGA A bütünlük doğrulaması

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (branch `ahmet`) + `tradehubfront` (branch `ahmet`)
**Ortam:** `istoc-dev-backend-1` · site `istoc.localhost` · Frappe v15.116.1 · Python 3.11.6
**Kapsam:** Diğer 5 ajanın DALGA A çıktısının bağımsız doğrulaması. Bu rapor kod
yazmadı; yalnız ölçtü, koştu ve geri aldı.

---

## 0. ÖZET — ÖNCE KIRIKLAR

| # | Bulgu | Şiddet | Durum |
|---|---|---|---|
| **K-1** | **`Media Profile` tohumlama kodu HİÇ YOK.** 4 DocType kuruldu, tablo boş (0 satır). Köprü profil bulamayınca **0 türev** üretir ve `frappe.log_error` yazıp sessizce döner. Bayrak açılsa bugün hiçbir şey olmaz. | **BLOKER** | Açık |
| **K-2** | **Adlandırma sözleşmesi tanımsız ve çakışıyor.** Manifest, `Media Rendition.profile` değerini kütüphanenin politika profil adıyla (`w384`) karşılaştırıyor; köprü ise oraya `Media Profile` **docname**'ini yazıyor. İkisi eşit değilse manifest **sessizce boş** döner. Docname global tekil olmak zorunda, ama politika adları slotlar arası **çakışıyor** (`w64/w128/w256/w512/og1200x630` hem `brand.logo` hem `seller.logo`) — yani "docname = politika adı" kuralı tüm slotlarda uygulanamaz. | **BLOKER** | Açık |
| **K-3** | **Ürün görsellerinin %61'i kapsam dışı.** `pipeline_bridge._resolve_scope` slotu `attached_to_doctype/field`ten çözüyor; sitedeki 3.152 ürün görselinin **1.909'unda bu alanlar NULL** (toplu içe aktarımla gelmiş). Bunlar sessizce atlanıyor — ve ağırlığın çoğu tam olarak orada (galeri). | **YÜKSEK** | Açık |
| K-4 | `hooks.py` yorumu "bayrak kapalıyken DB'ye sorgu gitmez" diyor; gerçekte `is_enabled()` istek başına bir kez `Media Engine Settings` okuyor (`frappe.local_cache`). Davranış güvenli, **yorum yanlış**. | Düşük | Açık |
| K-5 | `patches.txt`e `v15_9_22` (settings), `v15_9_21`ten (doctypes) **önce** eklenmiş. Bu kurulumda ikisi bağımsız olduğu için sorun çıkmadı, ama numara sırası okuyucuyu yanıltıyor. | Düşük | Açık |

**Güvenlik kurallarının tamamı korunmuş.** Bayrak varsayılan kapalı, mevcut akış
bire bir aynı, `hooks.py`de tek satır silinmemiş, kiracı izolasyonu yazılmış.
Kırıklar "yanlış yapılmış" değil, **"yapılmamış"** kategorisinde: hattın son iki
halkası (profil tohumlama + adlandırma sözleşmesi) eksik.

---

## 1. MIGRATE TEMİZ Mİ — ✅ GEÇTİ

```
$ docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate
Migrating istoc.localhost
Executing `after_migrate` hooks...
Enqueuing helpdesk.search_sqlite.HelpdeskSearch.build_index
Queued rebuilding of search index for istoc.localhost
[exit code 0]
```

123,9 KB'lik tam çıktı `traceback|error|exception|failed|warning` için tarandı:
**0 eşleşme**. Migrate temiz.

---

## 2. TABLOLAR OLUŞTU MU — ✅ GEÇTİ

```sql
TABLE_NAME               TABLE_ROWS  CREATE_TIME
tabMedia Asset                    0  2026-08-18 20:08:21
tabMedia Processing Job           0  2026-08-18 20:08:22
tabMedia Profile                  0  2026-08-18 20:08:22
tabMedia Rendition                0  2026-08-18 20:10:22
```

`tabMedia Engine Settings` **tablo olarak yok — doğrusu bu**: Single DocType
(`issingle=1`), değerleri `tabSingles`ta durur:

```
field                     value
active_slots
manifest_api_enabled      0
max_renditions_per_asset  40
media_pipeline_enabled    0
rendition_on_upload       0
```

DocType kayıtları ve patch log:

```
Media Asset            issingle=0  module=Tradehub Core
Media Engine Settings  issingle=1  module=Tradehub Core
Media Processing Job   issingle=0  module=Tradehub Core
Media Profile          issingle=0  module=Tradehub Core
Media Rendition        issingle=0  module=Tradehub Core

tradehub_core.patches.v15_9_22_media_engine_settings    2026-08-18 23:04:04
tradehub_core.patches.v15_9_21_media_pipeline_doctypes  2026-08-18 23:08:22
```

> **K-1 buradan görünüyor:** `tabMedia Profile` = **0 satır**. Türev reçetesi yok.

**Konteyner ↔ host eşitliği doğrulandı** (uygulama imaja gömülü, bind-mount değil).
11 dosyanın sha256'sı karşılaştırıldı, hepsi AYNI — yani aşağıdaki tüm ölçümler
depodaki kodun kendisini sınıyor.

---

## 3. BAYRAK VARSAYILAN KAPALI MI — ✅ GEÇTİ (kırmızı alarm YOK)

```
is_enabled()                         = False
is_enabled('media_pipeline_enabled') = False
is_enabled('rendition_on_upload')    = False
is_enabled('manifest_api_enabled')   = False
is_enabled('uydurma_alan')           = False     <- bilinmeyen alan da kapalı
is_slot_enabled('product.image')     = False
max_renditions_per_asset()           = 40

HAM DB: active_slots='' · manifest_api_enabled=0 · media_pipeline_enabled=0
        rendition_on_upload=0 · max_renditions_per_asset=40
```

Ana şalter davranışı da doğrulandı: `media_pipeline_enabled=0` iken alt bayraklar
kayıtlı değerinden bağımsız `False` dönüyor. Fail-safe yön doğru.

---

## 4. BAYRAK KAPALIYKEN SİSTEM AYNI MI — ✅ GEÇTİ

### 4a. Medya test paketleri (bench runner, site bağlı)

```
test_media_transcode              22 test  OK
test_media_pipeline_integration    6 test  OK
test_media_av                     91 test  FAILED (failures=1)   <- ORTAM, aşağıda
test_media_quota                  10 test  OK
test_media_access                 17 test  OK
test_media_access_level           15 test  OK
test_pipeline_flags               16 test  OK
test_pipeline_bridge              19 test  OK
test_media_manifest_api            9 test  OK
test_media_transcode_retry        39 test  OK
test_media_naming                  9 test  OK
test_media_browse                 14 test  OK
test_media_jobs                   12 test  OK
test_media_seller_backup          42 test  OK
```

**Tek düşen testin kök nedeni bulundu, Dalga A ile ilgisi yok:**

```
FAIL: test_backfill_null_satiri_kuyruga_alir
AssertionError: '756e83756c' not found in []

# neden:
>>> av.policy()
{'enabled': False, 'fail_closed': False, 'hold_until_clean': False, 'scanner': ''}
>>> av.backfill_pending(limit=5)
{'queued': 0, 'skipped': 'disabled'}
```

`media/av.py:825` — tarayıcı kurulu olmadığı için `policy()["enabled"]` False ve
`backfill_pending` hiç `enqueue_scan` çağırmıyor. Test bu kapıyı mock'lamıyor.
`media/av.py` git'te **değişmemiş**; bu dev konteynerinde clamav yok. Ortam kaynaklı,
önceden var olan bir test kırılganlığı.

### 4b. Tüm paket — 114 modül

Tek süreçte `unittest discover` bu depoda **geçerli bir yöntem değil**: 114 test
modülünün **56'sı `sys.modules["frappe"]`e kendi stub'ını kuruyor** ve aynı süreçteki
sonraki testlerin gerçek `frappe`sini bozuyor (ilk denemede 63 sahte hata üretti).
Bu yüzden her modül **kendi sürecinde** koşuldu; site gerektirenler `bench run-tests`,
stub kuranlar düz `python -m unittest` ile.

```
TOPLAM MODUL      : 114
GECEN MODUL       :  97
GECEN TEST SAYISI : 2173
GECMEYEN MODUL    :  17
```

Geçmeyen 17 modül:

```
test_address_validators           181  FAILED (failures=2, skipped=10)
test_api_contracts                126  FAILED (failures=1, errors=2)
test_capability_flag_invariant      5  FAILED (failures=1)
test_category_ranks                 3  FAILED (errors=3)
test_crop_geometry                  0  (koşturucu uyumsuz)
test_get_customer_detail_pii        0  (koşturucu uyumsuz)
test_kyc_verification              23  FAILED (errors=20)
test_media_av                      91  FAILED (failures=1)   <- 4a'da açıklandı
test_policy_dpi                    19  FAILED (failures=3, expected failures=1)
test_rebac_abac_e2e_phaseD          0  (koşturucu uyumsuz)
test_seller_inquiry_isolation       0  (koşturucu uyumsuz)
test_social_proof                  31  FAILED (failures=7)
test_social_proof_admin            24  FAILED (failures=4)
test_sprint6_rbac                  97  FAILED (failures=10, skipped=1)
test_store_subscription_isolation   0  (koşturucu uyumsuz)
test_tenant_isolation               0  (koşturucu uyumsuz)
test_tuple_sync                     0  (askıda kaldı, 40 dk sonra öldürüldü)
```

**Hiçbiri Dalga A kaynaklı değil.** İki bağımsız kanıt:

1. 17 modülün **hiçbiri** git'te değişmemiş (hepsi commit'li) ve
   `pipeline_bridge|pipeline_flags|media_manifest|Media Asset|Media Rendition|Media Profile|Media Engine Settings`
   dizgelerine **0 referans** içeriyor.
2. Kök nedenler tamamen başka: `docs/api/openapi.yaml` üretilmemiş
   (`test_api_contracts`), test'in kendi frappe stub'ı `defer_insert` kwarg'ını
   tanımıyor (`test_kyc_verification`, 15 hata), kaynak metin eşleşmesi kaymış
   (`test_address_validators`), site bağlamı gerektiren testler stub yüzünden
   bench altında koşamıyor (`RuntimeError: object is not bound`).

### 4c. Bayrak kapalıyken gerçek yükleme — davranış birebir aynı

Bayraklar varsayılan (kapalı) hâldeyken gerçek bir `File` insert edildi:

```
File olusturuldu: c58644326b  url=/files/BLNT2888örn.jpg
Media Asset          0 -> 0
Media Rendition      0 -> 0
Media Processing Job 0 -> 0
queue 'long'         0 -> 0
maybe_generate_renditions dogrudan cagri (kapali): None
SONUC: GECTI — yeni hat hic calismadi

MEVCUT hat calisti mi: th_media_state='Active'  th_media_scan_status=''
```

Yeni hat tek satır yazmadı, kuyruğa tek iş girmedi; **mevcut hat (`states.py`)
çalışmaya devam etti**. Sözleşme tutuyor.

### 4d. Storefront

```
$ npm run build     # icons:generate && tsc && vite build
✓ built in 5.66s
PWA precache 219 entries (7229.00 KiB)
EXIT=0
```

`tsc` build'in parçası → **tip denetimi de geçti**.

```
$ npx vitest run src/lib/media src/components/media src/components/shared/ListingCard.test.ts
Test Files  6 passed (6)
      Tests  58 passed (58)
```

(Çıktıdaki `ECONNREFUSED ::1:3000` gürültüsü kasıtlı: manifest istemcisinin
"ASLA FIRLATMAZ" kuralını ölü ağla sınayan test.)

---

## 5. HOOKS.PY BOZULDU MU — ✅ GEÇTİ (kırmızı alarm YOK)

```
$ git diff --stat tradehub_core/hooks.py
 tradehub_core/hooks.py | 23 +++++++++++++++++++++++
 1 file changed, 23 insertions(+)
```

**23 ekleme, 0 silme.** Tam diff üç yere dokunuyor, üçü de saf ekleme:

- `doc_events["File"]["after_insert"]` listesine **5. sıraya** (en sona)
  `pipeline_bridge.maybe_generate_renditions`. Mevcut 4 kanca
  (`states`, `audit`, `transcode`, `av`) sırası ve içeriği **aynı**.
- `permission_query_conditions`e 4 satır (Asset / Rendition / Processing Job / Profile).
- `has_permission`a 4 satır.

Kancanın gerçekten kayıtlı olduğu çalışma zamanında da doğrulandı:

```
frappe.get_hooks("doc_events")["File"]["after_insert"]:
  1. tradehub_core.media.states.on_file_insert
  2. tradehub_core.media.audit.on_file_insert
  3. tradehub_core.media.transcode.maybe_transcode_on_insert
  4. tradehub_core.media.av.maybe_scan_on_insert
  5. tradehub_core.media.pipeline_bridge.maybe_generate_renditions   <== DALGA A
```

**Satıcı izolasyonu (zorunlu kural) yazılmış.** `permissions.py`de 127 satır eklendi.
Tasarım doğru: `Media Asset` sahiplik kolonu taşıyor (`owner_seller`), `Rendition` ve
`Processing Job` **denormalize kolon taşımıyor**, izolasyon Asset üzerinden alt
sorguyla zincirleniyor (devirde eskiyen kopya alan sorunu bilinçli olarak yaratılmamış).
Türev/iş/profil satıcı için salt okunur. DocType `permissions` blokları da bunu
yansıtıyor (Seller: Rendition r=1,w=0,c=0,d=0).

---

## 6. UÇTAN UCA DUMAN TESTİ (bayrak AÇIK)

> Tüm bu adımlar geçici; sonunda sistem **varsayılan duruma geri çekildi** (§6.6).
> `Media Profile` tablosu boş olduğu için (K-1) profiller ölçüm süresince
> **elle tohumlandı**, sonra silindi.

### 6.1 Bayraklar açıldı

```
is_enabled(media_pipeline_enabled) = True
is_enabled(rendition_on_upload)    = True
is_enabled(manifest_api_enabled)   = True
is_slot_enabled('product.image')   = True
```

### 6.2 Türev üretimi — ÇALIŞIYOR

Gerçek bir Active ilan (`LST-03999`, satıcı `SEL-00034`, 12 görsel) tam olarak
işlendi. **12 görselin 12'si de `state=ready`, her biri 12 türev = 144 türev.**
İlk görselin merdiveni:

```
w96    h96    webp       522B  q=70  ssim=0.9919
w192   h192   webp     1,222B  q=70  ssim=0.9926
w384   h384   avif     3,397B  q=70  ssim=0.9978
w384   h384   webp     3,150B  q=70  ssim=0.9940
w640   h640   avif     6,619B  q=70  ssim=0.9978
w640   h640   webp     6,526B  q=70  ssim=0.9946
w768   h768   avif     8,850B  q=70  ssim=0.9979
w768   h768   webp     8,460B  q=70  ssim=0.9949
w1280  h1411  avif    17,775B  q=70  ssim=0.9979
w1280  h1411  webp    19,086B  q=70  ssim=0.9953
w1920  h2117  avif    29,539B  q=70  ssim=0.9981
w1920  h2117  webp    31,494B  q=70  ssim=0.9961
```

SSIM'ler 0,99+ — kalite kapısı çalışıyor. Fayda kapısı da çalışıyor: 9 KB'lik iki
küçük görselde `w1280`/`w1920` türevleri **üretilmedi** (büyütme kazanç sağlamaz).

### 6.3 Kuyruk yolu

`after_insert` kancası kayıtlı (§5) ve kapsam çözümü doğru çalışıyor
(`_resolve_scope -> product.image`). Aynı içerik daha önce işlendiği için
**idempotency devreye girdi ve ikinci iş açılmadı** — beklenen davranış:

```
File=74f7133dc3  _resolve_scope -> product.image
queue 'long' derinlik: once=0 sonra=0
```

> **Not:** İş `queue-long` worker'ına gitmeden, doğrulama betiği içinde senkron
> koşturuldu (`_run_rendition_job`). Worker'ın gerçekten iş çekmesi bu raporda
> **doğrulanmadı** — ilk yüklemede kuyruğa girmesi gereken yol, idempotency
> nedeniyle tetiklenmedi.

### 6.4 `get_manifest` ucu — ÖNCE BOŞ DÖNDÜ, KÖK NEDEN BULUNDU (K-2)

144 türev diskte hazırken uç **boş** döndü:

```
enabled=True  images=12  renditions=0  suppressed=0
ilk gorsel manifest = YOK
```

Adım adım teşhis, zincirin nerede koptuğunu gösterdi:

```
A) ilan.seller_profile='SEL-00034' · File.owner='mugiss@istoc.com'
   ownership.store_of(owner) = 'SEL-00034'                      ✓
B) Media Asset owner_seller='SEL-00034' state='ready' rendition=12 ✓
   source_file -> File.file_url == ilan.primary_image            ✓
C) _varliklari_getir  -> varlık bulundu                          ✓
D) _varlik_sec        -> kiracı eşleşti, varlık seçildi          ✓
E) _servis_edilebilir -> 12 türev servis edilebilir, elenen 0    ✓
F) _render_manifest   -> None                                    ✗ KOPUŞ
G) get_manifest       -> renditions=0
```

**Kök neden.** `media_manifest._render_manifest:431`
`available_profiles=tuple({t["profile"] ...})` ile `Media Rendition.profile`
kolonunu kütüphaneye veriyor; kütüphane bunu **slot politikasındaki profil
adlarıyla** (`w96`, `w384`, …) karşılaştırıyor. Köprü ise
`pipeline_bridge._render_one` içinde oraya `profil.name`, yani **`Media Profile`
docname**'ini yazıyor. İlk koşuda docname `product.image:w96` idi → hiçbiri
eşleşmedi → `_CiftSuzgecliBuilder` `NoProfileAvailable` fırlattı → manifest `None`.

**Kanıt (tek değişken: adlandırma).** `profile_key` politika adının kendisi
(`w96`, `w192`, …) yapılıp aynı akış tekrarlandı:

```
enabled=True  images=12  renditions=12  suppressed=0
src   = /files/ac/acd090cb4e677f810cf95f2a31f57521.webp
w x h = 1920 x 2117   loading=eager  fetchpriority=high
<source type="image/avif">
    /files/9d/…9d.avif  384w
    /files/08/…08.avif  640w
    /files/1c/…1c.avif  768w
    /files/0a/…0a.avif 1280w
    /files/1c/…1c.avif 1920w
<source type="image/webp">
    …96w …192w …384w …640w …768w …1280w …1920w
```

**Ama bu kural tüm slotlarda uygulanamaz.** `Media Profile.profile_key` autoname
alanı, yani global tekil olmak zorunda; politika profil adları ise çakışıyor:

```
og1200x630   2 slot: brand.logo, seller.logo   <== CAKISMA
w128         2 slot: brand.logo, seller.logo   <== CAKISMA
w256         2 slot: brand.logo, seller.logo   <== CAKISMA
w512         2 slot: brand.logo, seller.logo   <== CAKISMA
w64          2 slot: brand.logo, seller.logo   <== CAKISMA
(29 profil adının 5'i çakışıyor)
```

Yani doğru düzeltme tohumlamada değil, **köprüde**: `Media Rendition.profile`
alanına docname yerine **politika profil adı** yazılmalı (ya da manifest tarafında
docname → politika adı eşlemesi yapılmalı). Aksi hâlde `brand.logo` ve
`seller.logo` slotları hiçbir zaman manifest üretemez.

### 6.5 HTTP üzerinden gerçek uç (guest, curl)

**Bayrak AÇIK:**

```
$ curl "http://istoc.localhost/api/method/tradehub_core.api.media_manifest.get_manifest?listing=LST-03999&slot=product.image"
enabled    = True
etag       = "91ea9851574a6129e3f29c9861300f93"
cache      = public, max-age=60, must-revalidate
renditions = 12   suppressed = 0
LCP asset  = f34nhtfhv3
src        = /files/ac/acd090cb4e677f810cf95f2a31f57521.webp
w x h      = 1920 x 2117   fetchpriority=high  loading=eager
<source image/avif>  384w 640w 768w 1280w 1920w
<source image/webp>  96w 192w 384w 640w 768w 1280w 1920w

$ curl -o /dev/null "http://istoc.localhost/files/9d/…9d.avif"
HTTP 200  3397B  image/avif          <- srcset'teki adres GERÇEKTEN indiriliyor
```

**Bayrak KAPALI (varsayılan), aynı istek:**

```
HTTP 200, enabled = False
renditions = 0
ilk gorsel manifest = None
fallback = /files/BLNT2888örn.jpg        <- bugünkü ham src
```

Uç kapalıyken **hata atmıyor**, bugünkü `<img src>` adresini veriyor → storefront
mevcut işaretlemesine düşüyor. Diğer uçlar:

```
get_manifest_batch                    HTTP 200
get_signed_url (guest)                HTTP 403   <- doğru, oturum zorunlu
```

### 6.6 Sistem varsayılan duruma geri çekildi — ✅

```
Media Asset              = 0
Media Rendition          = 0
Media Profile            = 0
Media Processing Job     = 0
media_pipeline_enabled   = 0  is_enabled=False
rendition_on_upload      = 0  is_enabled=False
manifest_api_enabled     = 0  is_enabled=False
active_slots             = ''
galeri metadata NULL disi kalan = 0  (0 olmali)
public/files icinde .avif dosya sayisi: 0
eski türev URL'i                 -> HTTP 404
tabFile'da 'dalga_a%' kaydı      -> yok
```

Ölçüm için `LST-03999`un 11 galeri dosyasına geçici olarak yazılan
`attached_to_*` metadatası (K-3'ü aşmak için) **orijinal NULL değerine geri alındı**.

---

## 7. ÖLÇÜM — NE KAZANDIK

**Referans sayfa:** `LST-03999` — 12 görsel, **13.759.638 B = 13,12 MB**.
(Görevdeki "13,14 MB" ölçümüyle örtüşen gerçek ilan; sitedeki en ağır ürün
sayfaları 26–36 MB'a kadar çıkıyor.)

### 7.1 Üretilen merdiven (AVIF, bayt)

```
görsel                                    kaynak     a384    a640    a768   a1280   a1920
/files/BLNT2888örn.jpg                   199,092    3,397   6,619   8,850  17,775  29,539
/files/kare-823378a8.webp                  9,776    1,896   3,336   4,063       0       0
/files/kare-19b3616f.webp                  9,402    1,842   3,250   3,947       0       0
/files/008 bej orta 3 lu.jpg           1,157,910   13,097  32,210  44,682 199,596 380,972
/files/013 siyah orta 3 lü.jpg         1,987,254   16,106  38,109  53,235 210,663 375,573
/files/018 siyah orta 12'li.jpg        2,092,124   17,214  39,753  54,838 241,613 446,388
/files/019 bej buyuk 12'li calisma.jpg 1,263,061   14,236  36,217  51,722 236,508 418,918
/files/020 kirmizi orta 12'li.jpg      2,345,178   13,968  33,851  46,146 258,530 479,333
/files/BLNT1818xx.jpg                  2,066,448   28,781  78,205 104,065 453,097 823,371
/files/BLNT2184xx.jpg                  1,172,797   20,029  50,588  67,600 335,260 664,911
/files/BLNT2185xx.jpg                    678,491   17,855  38,572  47,871 167,320 294,944
/files/BLNT2190xx.jpg                    778,105   17,127  36,246  45,631 197,786 390,838
```

(0 = fayda kapısı elemiş; 9 KB'lik kaynağı 1280px'e büyütmek kazanç değil zarar.)

### 7.2 Mobil senaryo — 390px CSS × DPR 2 = **780px hedef**

Merdivende **780 basamağı yok**: `w768` hedefin %1,5 altında, bir sonraki basamak
`w1280`. `srcset`in `w` tanımlayıcısıyla tarayıcı katı davranırsa `w1280`i seçer.

| Senaryo | Bayt | MB | Kazanç | <2 MB |
|---|---:|---:|---:|:--:|
| **A** — katı srcset (≥780 → w1280), 12 görselin **hepsi** aynı anda | 2.330.788 | **2,223** | %83,1 | ✗ |
| **B** — `w768` basamağı, 12 görselin hepsi | 532.650 | **0,508** | %96,1 | ✓ |
| **C** — **gerçek PD**: 1 ana görsel @780 + 11 karo @192 | 179.926 | **0,172** | %98,7 | ✓ |
| **D** — C + lazy (ilk ekran: 1 ana + 4 karo) | 50.716 | **0,048** | %99,6 | ✓ |
| bugün (12 tam boy orijinal) | 13.759.638 | 13,12 | — | ✗ |

**Senaryo C gerçeği yansıtır.** Ürün detay sayfası 12 görseli aynı boyda indirmez:
bir ana görsel + karo şeridi basar ve `lib/media/sizes.ts` her bölgeye kendi
`sizes`ini verir (ana görsel `product_detail/main_image`, karolar
`product_detail/lightbox_thumb` ≈ 192px). **13,12 MB → 0,17 MB, %98,7 kazanç.**

Senaryo A pesimist üst sınırdır (12 görselin tamamının ana görsel kutusunda,
aynı anda, lazy olmadan indiği varsayımı) ve tek başına bile %83 kazandırıyor —
ama **2 MB eşiğini 0,22 MB ile kaçırıyor**. Bu, `w768`/`w1024` civarına bir
basamak eklenmesinin (ya da `sizes`in doğru bağlanmasının) neden önemli olduğunu
gösteriyor.

### 7.3 Depolama maliyeti

144 türev = **14.194.871 B (13,54 MB)** — kaynakların toplamından (13,12 MB) biraz
fazla. Bu **transfer değil, disk** maliyetidir: tarayıcı merdivenden tek basamak
indirir. Varlık başına 12 türev × ~3.150 ürün görseli ölçeğinde disk planlaması
gerekir (`max_renditions_per_asset=40` freni mevcut).

### 7.4 Üretim süresi

12 görsel (13,12 MB kaynak) → 144 türev: **830 saniye** (görsel başına ~69 sn).
`frappe.enqueue(queue="long", timeout=1800)` bu iş için yeterli; ama **geri dönük
tohumlamada** 3.152 görsel × ~69 sn ≈ **60 saat tek worker** demektir. Toplu
üretim planı gerekir.

---

## 8. SONUÇ — DALGA A TAMAM MI?

**Hayır. "Hazır, bayrak açılmayı bekliyor" DİYEMEM.**

Bayrak bugün açılırsa **hiçbir şey olmaz**: `Media Profile` tablosu boş (K-1),
köprü her dosyada `frappe.log_error("profil yok")` yazıp döner, `get_manifest`
`renditions: []` döndürür, storefront bugünkü `<img>`e düşer. Sistem bozulmaz —
bayrak mimarisi görevini yapar — ama **kazanç da sıfırdır**.

### Sağlam olan (doğrulandı)

- ✅ Migrate temiz, 4 tablo + 1 Single kuruldu, patch'ler `patches.txt` sonunda.
- ✅ Bayrak varsayılan **kapalı**; bilinmeyen alan, okuma hatası ve ana şalter
  hepsi fail-safe "kapalı" yönünde.
- ✅ Bayrak kapalıyken sistem **birebir bugünkü gibi**: gerçek yüklemede yeni hat
  hiç çalışmadı, mevcut hat (`states`/`audit`/`transcode`/`av`) çalışmaya devam etti.
- ✅ `hooks.py` **23 ekleme / 0 silme**; mevcut 4 kancanın sırası korunmuş, yeni
  kanca en sonda.
- ✅ Kiracı izolasyonu yazılmış ve tasarımı sağlam (denormalize sahiplik kolonu yok).
- ✅ 97/114 test modülü, 2.173 test yeşil. Düşen 17 modülün **hiçbiri** Dalga A'ya
  değmiyor (0 referans, hepsi değişmemiş dosyalar).
- ✅ Storefront `tsc` + `vite build` geçti, 58 medya testi yeşil.
- ✅ Motor **gerçekten çalışıyor**: 12 gerçek ürün görselinden 144 türev, SSIM
  0,99+, fayda kapısı doğru eliyor.
- ✅ Uç HTTP üzerinden guest'e açık, gerçek `srcset` dönüyor, adresler indiriliyor;
  bayrak kapalıyken 200 + `fallback` veriyor, hata atmıyor.

### Eksik olan (bayrak açılmadan önce kapatılmalı)

1. **K-1 — `Media Profile` tohumlayıcı.** Politika JSON'larındaki `profiles`
   bloklarından idempotent bir patch. En az `product.image` (7 profil).
2. **K-2 — adlandırma sözleşmesi.** `Media Rendition.profile` alanına **politika
   profil adı** yazılmalı (`pipeline_bridge._render_one`), docname değil. Aksi
   hâlde `brand.logo`/`seller.logo` slotları çakışma yüzünden hiç çalışamaz.
   Bu düzeltilmeden K-1'i çözmek yetmez — ikisi birlikte gerekir.
3. **K-3 — kapsam çözümü.** Ürün görsellerinin %61'inde `attached_to_*` NULL.
   Ya köprü slotu `Listing Image.image` / `Listing.primary_image` **ilişkisinden**
   de çözebilmeli, ya da bir backfill bu metadatayı yazmalı. Bugünkü hâliyle
   ağırlığın çoğunu taşıyan galeri görselleri kapsam dışı.
4. **Toplu üretim planı.** Mevcut kayıtlar için ~60 worker-saat (§7.4).
5. **Worker doğrulaması.** `queue-long`un işi gerçekten çektiği bu raporda
   doğrulanmadı (§6.3); temiz bir içerikle bir kez sınanmalı.
6. K-4 (yanlış yorum) ve K-5 (patch sırası) — kozmetik.

### Kabul kriteri (<2 MB)

Ölçüldüğünde **karşılanıyor**: gerçek ürün detay senaryosunda **13,12 MB → 0,17 MB
(%98,7)**; en pesimist senaryoda bile 2,22 MB ile %83 kazanç. Yani hedef teknik
olarak ulaşılabilir ve motor bunu üretebiliyor — **ancak bugün ürüne akmıyor**,
çünkü yukarıdaki 1–3. maddeler eksik.

**Tek cümleyle:** Motor sağlam, emniyet subabı sağlam, boru **son iki rakoru
takılmadığı için** bağlı değil.

---

## Ek — doğrulama betikleri

Konteynerde `/home/frappe/olcum/` altında: `a3_bayrak.py` (bayrak),
`a4_av.py` (AV kök neden), `a6b_manifest.py` (uçtan uca), `a6c_teshis.py` (K-2 teşhis),
`a6d_kanit.py` (K-2 kanıt), `a7_olcum.py` (senaryo ölçümü), `a8_kur.py`/`a8_sok.py`
(HTTP kanıtı), `a9_son.py` (son durum + kapalı-bayrak regresyonu).
Hepsi `finally` bloğuyla kendi ürettiğini siler.
