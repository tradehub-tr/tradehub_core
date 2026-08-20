# 40 — T-043 · T-053 · T-064: Kullanım takibi, kör noktalar, ayrı GC işleri

**Görevler:** T-043 (kullanım takibi / öksüz tespiti) · T-053 (saklama + GC) ·
T-064 (idempotency ve sürüm geçişi) · **Tarih:** 2026-08-19 · **Dal:** `ahmet`
**Ölçüm ortamı:** `istoc-dev` compose, site `istoc.localhost`, Frappe v15, MariaDB 10.6
**Önceki raporlar:** `26-t053-saklama-gc.md`, `34-dogrulama-faz4-7.md`

**Dokunulan kod (hepsi görev kapsamındaki dosyalar):**

| Dosya | Ne yapıldı |
|---|---|
| `tradehub_core/media/usage.py` | `LIVE_SOURCES` 8 → **17**, `ORDER_SOURCES` 2 → **5**; `CHILD_TABLES` + `SOURCE_DOCTYPE` + `_extra_columns()`; `resolve()` ve `images_of()` yeni kaynaklara uyarlandı; `STORE_FILTERS` 3 giriş |
| `tradehub_core/media/pipeline/core/usage.py` | `UsageBackend` / `PersistentUsageStore` / `FrappeUsageBackend` / `get_usage_store()` / `usage_store_status()` — kalıcı `Media Usage` deposu |
| `tradehub_core/media/pipeline/storage/retention.py` | `live_usage_urls()`; `_original_candidate` için üç yeni kapı; `run_scheduled_gc_originals()` + `run_scheduled_gc_derivatives()` ayrı bayrak/kilit ile |
| `tradehub_core/tests/test_retention_gc.py` | 22 → **37** test (kör nokta testi ters çevrildi, 2 yeni grup) |
| `tradehub_core/tests/test_media_usage_sources.py` | **YENİ** — 12 test, kaynak listesi ↔ canlı şema |
| `tradehub_core/tests/test_media_usage_store.py` | **YENİ** — 24 test, frappe'siz |

> **DOKUNULMADI:** `hooks.py`, `permissions.py`, `patches.txt`, `patches/**`,
> `media/trash.py`, `media/presets.py`, `api/**`, `admin-panel`, `docker/`,
> DocType JSON'ları ve `doctype_specs/**`. `bench migrate` **koşturulmadı**.
> `media/pipeline/core/dedup.py` yalnız **okundu** (T-064 için).

---

## 0. Karar (önce sonuç)

| Görev | Önceki durum | Bugün | Kalan |
|---|---|---|---|
| **T-043** | KISMİ — bağ kaydı bellek içi | **KISMİ↑** — kalıcı depo yazıldı ve testlendi, ama `Media Usage` DocType'ı **kurulu değil**, o yüzden üretimde hâlâ bellek içi | DocType kurulumu (Şerit A) |
| **T-043 kör nokta** | 5 doğrulanmış kör nokta + 4 tane daha | **KAPANDI** — 9 alan `LIVE_SOURCES`'a, 3 alan `ORDER_SOURCES`'a girdi; '/files/' taşıyan 42 (tablo, kolon) çiftinin tamamı ya kapsandı ya gerekçelendi | — |
| **T-053 kriter 1** | Tek GC işi | **KOD TARAFI TAMAM** — ayrı iş, ayrı bayrak, ayrı kilit, ayrı rapor yazıldı; `hooks.py` kaydı **yapılmadı** (yasak liste) | `hooks.py` kaydı (Şerit A) |
| **T-053 kriter 4** | `regenerate_on_demand` tüketen kod yok | **DEĞİŞMEDİ** — yeniden ölçüldü, tüketen kod hâlâ yok; silme `notify_only`'a düşmeye devam ediyor | Lazy üretim yolu |
| **T-064 kriter 4** | Ölçülemez | **HÂLÂ ÖLÇÜLEMEZ** — `Media Version` DocType'ı yok, `Media Asset.active_version` kolonu yok (ölçüldü); §7'de geçiş protokolü tasarlandı | DocType + kolon kurulumu |

### Bu görevin bulduğu ve düzelttiği asıl kusur

> **Orijinal süpürücüsünde kullanım kapısı hiç yoktu.** Kör nokta koruması
> yalnız TÜREV tarafına bağlıydı (`sweep_derivatives`). `_original_candidate`
> legal hold'dan sonra doğrudan yaşa bakıyordu: `keep_forever=false` yazılan an
> canlı ürün görselleri, marka logoları ve kategori görselleri aynı kefede
> silme adayı oluyordu. Ölçüm aşağıda (§3): agresif politikayla **4.429 aday
> (1.447.444.781 bayt)** → kapılar bağlandıktan sonra **608 aday
> (386.749.767 bayt)**. Fark: **3.821 dosya, 1,06 GB.**

---

## 1. Kör nokta ölçümü ve kapatılması (T-043)

### 1.1 Bugünkü tam tarama

`information_schema` × `locate('/files/', kolon)` (2026-08-19, istoc.localhost):
**42** (tablo, kolon) çifti dosya adresi taşıyor. Görev tanımı 5 doğrulanmış
kör nokta veriyordu; ölçüm ikisini daha ekledi (`Brand.logo`,
`Brand.hero_banner` — 26 numaralı raporun T-029 tuzağı) ve iki tanesini de
(`Seller Gallery Image.poster_image` / `.video_url`).

Görev tanımında `LIVE_SOURCES` "10 giriş" yazıyordu; **ölçülen değer 8'di**.
(`Listing`×2, `Listing Image`, `Listing Variant Item`×2, `Storefront Layout`,
`Seller Gallery Image`, `Admin Seller Profile` = 8.) Sayı düzeltildi.

### 1.2 Ne eklendi

`LIVE_SOURCES` **8 → 17**:

| Alan | Satırda '/files/' | Neden CANLI |
|---|---:|---|
| `Admin Seller Profile.banner_image` | 2 | mağaza kapak görseli |
| `Seller Gallery Image.poster_image` | 1 | galeri videosunun poster karesi |
| `Seller Gallery Image.video_url` | 1 | galeri videosu |
| `Brand.logo` | 1 | **T-029 tuzağı** |
| `Brand.hero_banner` | 1 | marka sayfası kapağı |
| `Product Category.image` | 1 | kategori görseli (7.694 satırlık tablo) |
| `Seller Category.image` | 1 | satıcı kategorisi görseli |
| `Static Page SEO.og_image` | 1 | paylaşım görseli |
| `Verification Source.icon` | 1 | doğrulama rozeti |

`ORDER_SOURCES` **2 → 5**: `Order Item.image` (1), `Payment Transaction.receipt_url` (3),
`Buyer Favorite Item.snapshot_image` (22). Gerekçe: bunlar canlı ürün kullanımı
değil ama silinirse geçmiş sipariş ekranı / favori listesi kırılır.
`order_only` kararı `trash.TRASHABLE_VERDICTS` (`unused`, `history_only`)
içinde **değil** — doğru yer bu grup.

### 1.3 Ne BİLEREK eklenmedi

KVKK belge alanları (`KYB Verification`×6, `KYC Verification.identity_document`,
`Seller Application.identity_document`, `Seller Certification.document`,
`Seller Verification.document`) hiçbir gruba girmedi. İki gerekçe:

1. `verdict_map_all` aday kümesi `presets.EXCLUDED_DOCTYPES` ile bu doctype'lara
   bağlı ekleri zaten dışarıda bırakıyor — karar hiç sorulmuyor.
2. Bunları CANLI kaynak yapmak, medya panelinde bir dosyanın "KYB Verification'da
   kullanılıyor" diye görünmesi demekti; kimlik belgesinin varlığını kullanım
   dökümünde sızdırmak (`docs/reports/24-kyc-izolasyon.md`).

GC tarafındaki koruma `retention.PROTECTED_SOURCES` ile ayrıca duruyor.
`tests/test_media_usage_sources.py:BILINCLI_DISARIDA` bu kararı ve gerekçesini
makine okunur biçimde tutuyor; listede olmayan **yeni** bir alan çıkarsa
`test_kapsanmayan_alan_kalmadi` kırmızı olur.

### 1.4 Sessiz başarısızlık düzeltildi — `resolve()` kolon seçimi

`_match_rows` sorgu hatasını yutuyor (`except` + `log_error`). `resolve()`
eskiden kolon seçimini şöyle yapıyordu:

```python
extra = "name" if table in ("tabListing", "tabStorefront Layout", "tabAdmin Seller Profile") \
        else "parent, idx"
```

Yani listede **olmayan her yeni ana tablo** için `parent` seçilirdi →
"Unknown column 'parent'" → hata yutulur → dosya "hiçbir yerde kullanılmıyor"
görünür. Yön silme yönü. Artık ters yazıldı: `CHILD_TABLES` frozenset'i
child tabloları sayar, bilinmeyen tablo **ana tablo** varsayılır
(`_extra_columns()`). Ayrıca `SOURCE_DOCTYPE` haritası eklendi — eskiden
varsayılan `"Listing"` idi, marka logosu "Listing" diye raporlanırdı.

`tests/test_media_usage_sources.py` bu ikisini canlı şemaya karşı ölçüyor:
`test_resolve_kolon_secimi_her_kaynak_icin_gecerli`,
`test_child_tablolar_gercekten_child`, `test_child_olmayan_kaynaklarda_parent_yok`.

### 1.5 KANIT — kararlar değişti

```
tabBrand.logo                        : 1 adres -> {'in_use': 1}
tabBrand.hero_banner                 : 1 adres -> {'in_use': 1}
tabProduct Category.image            : 1 adres -> {'in_use': 1}
tabSeller Category.image             : 1 adres -> {'in_use': 1}
tabAdmin Seller Profile.banner_image : 2 adres -> {'in_use': 2}
tabStatic Page SEO.og_image          : 1 adres -> {'in_use': 1}
tabVerification Source.icon          : 1 adres -> {'in_use': 1}
tabSeller Gallery Image.poster_image : 1 adres -> {'in_use': 1}
tabSeller Gallery Image.video_url    : 1 adres -> {'in_use': 1}
tabOrder Item.image                  : 1 adres -> {'in_use': 1}
tabPayment Transaction.receipt_url   : 3 adres -> {'order_only': 3}
tabBuyer Favorite Item.snapshot_image: 1 adres -> {'in_use': 1}
```

`Order Item.image` ve `Buyer Favorite Item.snapshot_image` `in_use` çıkıyor
çünkü taşıdıkları adres aynı zamanda canlı bir ürün görseli — snapshot alanı
ürünün adresini kopyalamış. `Payment Transaction.receipt_url` `order_only`:
yalnız sipariş delili, canlı kullanımı yok. İkisi de doğru.

---

## 2. Kalıcı `Media Usage` deposu (T-043 kriter 1)

### 2.1 Ölçüm: DocType kurulu değil

```
frappe.db.exists("DocType", "Media Usage")   -> None
show tables like 'tabMedia Usage'            -> ()
frappe.db.exists("DocType", "Media Version") -> None
```

Şema **hazır ve doğru**: `media/pipeline/doctype_specs/media_usage.json`
(9 alan, `usage_key` türetilmiş tekillik anahtarı, `is_open` ile bağ kapatma,
T-044 §4.3 indeks ölçümü yorumda). Kurulum bu görevin yasak listesinde —
**Şerit A'ya devrediliyor.** Şema üzerinde değişiklik önerim yok.

### 2.2 Yazılan kod

`UsageStore` (bellek içi) korundu; yanına aynı sözleşmeyi uygulayan
`PersistentUsageStore` yazıldı. Depo mantığı `UsageBackend` arayüzünün
arkasında:

```
UsageBackend            fetch / upsert / rows_for / open_asset_names
  ├─ FrappeUsageBackend `tabMedia Usage` üzerinde doğrudan SQL,
  │                     `on duplicate key update` ile idempotent upsert
  └─ (test) SozlukBackend
get_usage_store()       DocType varsa kalıcı, yoksa bellek içi
usage_store_status()    hangi deponun seçildiği + NEDEN
```

Seam'in gerekçesi: DocType kurulu olmadan frappe'ye gömülü bir upsert hiç
ölçülemezdi. Şimdi **mantık ölçülüyor** (24 test), ölçülmeyen tek şey ince SQL
katmanının alan eşlemesi ve tarih dönüşümü — bu §9'da "ölçülmedi" olarak yazılı.

`usage_store_status()` bir "sessiz düşüş"ü engelliyor: kalıcı depo yoksa
kod sessizce belleğe düşmüyor, raporlayan taraf bunu okuyabiliyor.

### 2.3 KANIT — iki depo aynı senaryolardan geçiyor

`DepoDavranisiOrtak` sınıfı 8 senaryoyu iki gerçeklemeye de uyguluyor:
idempotent açma, kapatmanın satırı silmemesi, kapalı bağ yeniden açılınca
`first_seen`'in korunması, `sync_links`'in listede olmayanı kapatması, öksüz
kararının kapalı bağı görmesi.

Ayrışan tek davranış — ve zaten olması gereken:

```
test_surec_yeniden_baslayinca_baglar_duruyor        (kalıcı depo)  OK
    PersistentUsageStore(backend).open_link(...)
    PersistentUsageStore(backend).links_of("A1")  -> 1 bağ, first_seen korunmuş

test_bellek_ici_depo_ayni_senaryoda_bagi_kaybediyor (karşı yön)    OK
    UsageStore().open_link(...) ; UsageStore().links_of("A1") -> []
```

`all_links()` kalıcı depoda **bilerek `UsageError` atıyor**: T-044 §4.3 indeks
ölçümü 419.676 satır üzerinden yapılmış; tüm tabloyu belleğe çekmek sessizce
yapılacak bir iş değil.

### 2.4 Bugünkü üretim davranışı — ölçüm

```
usage_store_status() = {"doctype": "Media Usage", "installed": false,
                        "persistent": false, "spec": ".../media_usage.json",
                        "reason": "DocType kurulu değil — bağlar süreç ömrü
                                   kadar yaşıyor..."}
get_usage_store() -> UsageStore   is_persistent=False
```

**T-043 kriter 1 bugün hâlâ karşılanmıyor.** Karşılanması için tek gereken
DocType kurulumu; kod tarafı hazır ve bekliyor.

---

## 3. Orijinal süpürücüsünde kullanım kapısı (T-043 + T-053)

### 3.1 Eksik neydi

`_original_candidate` sırası eskiden: legal hold → adres çözümü → disk → yaş.
Kullanım hiç sorulmuyordu. `sweep_derivatives` `blind_spot_urls()` çağırıyordu
ama `sweep_originals` çağırmıyordu. Yani 26 numaralı raporun emniyet ağı
orijinal tarafı hiç korumuyordu.

### 3.2 Yeni sıra

```
1. legal_hold                     -> blocked
2. guard  (kör nokta + KVKK)      -> keep / usage_blind_spot
3. usage_known == False           -> keep / usage_unknown      ← FAIL-SAFE
4. in_use (canlı + sipariş)       -> keep / in_use
5. adres çözülmüyor / diskte yok / yaş + politika
```

3. madde bilinçli: kullanım taraması ölçülemezse "hiçbir şey kullanılmıyor"
varsaymak envanteri silmek olurdu.

### 3.3 `verdict_map_all` KULLANILMADI — ölçümle bulunan tuzak

İlk gerçekleme koruma kümesini `usage.verdict_map_all(deep=False)`'dan
üretiyordu ve **canlı envanterde kırmızı verdi**:

```
FAIL: test_kullanimdaki_gercek_dosya_agresif_politikada_bile_korunuyor
AssertionError: set() is not true :
  canlı ürün görseli kullanım kümesinde yok:
  ['/files/469119194_122137766276501686_6275260628053641708_nf.jpg']
```

Sebep: `verdict_map_all` yalnız **kendi aday kümesine** karar üretiyor ve o küme
`is_private=0`, `left(file_url,7)='/files/'` ile daraltılmış, ayrıca hassas
doctype'larla aynı `content_hash`'i taşıyanlar çıkarılmış. Karar haritasında
**olmayan** bir adres, "kullanılmıyor" ile aynı sonucu veriyordu — yani tam
olarak korunması gereken private dosyalar korumasız kalıyordu.

`live_usage_urls()` artık kaynak alanların **ham** taramasını yapıyor
(`_referenced_urls`, alan başına tek `locate` sorgusu): aday kümesi süzgeci yok,
`tabFile` kaydı olup olmaması önemli değil. `HISTORY_SOURCES` taranmıyor —
`history_only` zaten silinebilir sayılan tek karar.

### 3.4 KANIT — kuru koşum + vacuity, canlı envanterde

Agresif politika (`keep_forever=false`, `local_days=1`, `then=delete`,
legal hold açık), **`dry_run=True`**:

```
KAPILAR AÇIK (bugünkü kod)
  ÖNCE : File=5042  disk=967.753.083 bayt
  SONRA: File=5042  disk=967.753.083 bayt      FARK: (0, 0)
  taranan=4528  korunan=3920  aday=608  silinen=0  bloke=0
  bytes_candidate=386.749.767   bytes_freed=0
  atlanma={"in_use": 3791, "missing_on_disk": 15,
           "too_young": 82, "usage_blind_spot": 32}

KAPILAR KAPALI (live_usage_urls ve blind_spot_urls boş küme döndürüldü)
  taranan=4528  korunan=99  aday=4429  bloke=0
  bytes_candidate=1.447.444.781
  atlanma={"missing_on_disk": 17, "too_young": 82}

FARK: aday 4429 -> 608   (3.821 dosya korundu)
      bayt 1.447.444.781 -> 386.749.767   (1,06 GB)
```

`4429` sayısı 26 numaralı raporun ölçtüğü değerin **aynısı** — yani kapılar
kapatıldığında kod eski davranışına birebir dönüyor, aradaki fark tam olarak
bu görevin eklediği koruma.

`missing_on_disk` 17 → 15: iki dosya artık daha erken bir kapıdan (`in_use`)
korunduğu için o sebeple sayılmıyor. Karar aynı (`keep`), yalnız sebep daha
bilgilendirici.

Üretim varsayılanı (`keep_forever=true`):

```
taranan=4528 korunan=4528 aday=0 silinen=0
atlanma={"in_use": 3791, "keep_forever": 690,
         "missing_on_disk": 15, "usage_blind_spot": 32}
```

> **Envanter sayıları hareketli.** 26 numaralı rapor `File=5014`,
> `disk=1.153.218.661` ölçmüştü; bugün `5042` / `967.753.083`. Aynı site
> üzerinde 14 ajan paralel çalışıyor. Sabit olan, aynı koşumun iki yönü
> arasındaki **fark**tır — `ÖNCE == SONRA` ve `4429 vs 608` aynı dakikada
> aynı envanter üzerinde ölçüldü.

---

## 4. Orijinal ve türev için AYRI işler (T-053 kriter 1)

### 4.1 Yazılanlar

```
run_scheduled_gc_originals()    bayrak media_retention_gc_originals_enforce
                                kilit  media_retention_gc_originals_lock
                                rapor  Error Log "media.retention_gc.originals"

run_scheduled_gc_derivatives()  bayrak media_retention_gc_derivatives_enforce
                                kilit  media_retention_gc_derivatives_lock
                                rapor  Error Log "media.retention_gc.derivatives"

run_scheduled_gc()              (değişmedi — mevcut hooks.py kaydı bu)
                                bayrak media_retention_gc_enforce
                                kilit  media_retention_gc_lock
```

**Bir bayrak diğerini AÇMIYOR.** Türev silmeyi açmak orijinal silmeyi açmıyor,
tersi de öyle. "İki politika birbirini etkilemez" (`retention.md` §6) kuralının
zamanlama düzeyindeki karşılığı bu. Ayrı kilit de zorunlu: ortak kilit, iki iş
ayrı saatlerde koşsa bile birinin diğerini "locked" diye atlatmasına yol açardı.

### 4.2 KANIT — kuru koşum ve kilit bağımsızlığı

```
ÖNCE=(5042, 967753083)  SONRA=(5042, 967753083)  FARK=(0, 0)

original  : dry_run=True  bayrak=media_retention_gc_originals_enforce
            scanned=4528 kept=4528 candidates=0 deleted=0
            skipped_by_reason={"in_use":3791,"keep_forever":690,
                               "missing_on_disk":15,"usage_blind_spot":32}
derivative: dry_run=True  bayrak=media_retention_gc_derivatives_enforce
            scanned=0 kept=0 candidates=0 deleted=0  skipped_by_reason={}
```

Kilit testleri: `LOCK_ORIGINALS` tutulunca orijinal işi `{"skipped": "locked"}`
dönüyor; aynı kilit tutuluyken **türev işi normal koşuyor**
(`test_bir_isin_kilidi_digerini_engellemiyor`).

### 4.3 `hooks.py` kaydı YAPILMADI — Şerit A'ya

`hooks.py` bu görevin yasak listesinde. Kayıt yapıldığında eklenecek iki satır
(yalnız EKLEME, `scheduler_events["daily"]` içine, `backup.run_scheduled`'dan
**sonra** — aday gösterilen hiçbir dosya yedeksiz kalmasın):

```python
"tradehub_core.media.pipeline.storage.retention.run_scheduled_gc_originals",
"tradehub_core.media.pipeline.storage.retention.run_scheduled_gc_derivatives",
```

Karar gereken nokta: mevcut `run_scheduled_gc` (birleşik iş) **kaldırılmalı mı**?
Üçü birden kayıtlı kalırsa aynı envanter günde iki kez taranır (zararsız ama
gereksiz) ve `Error Log`'a üç rapor düşer. Önerim: iki ayrı iş kaydedildiğinde
birleşik iş kaydı `hooks.py`'den **çıkarılsın**; fonksiyon kodda kalsın (elle
çağrı ve mevcut testler için).

`test_hooks_kaydi_henuz_yok` bugünkü durumu sabitliyor: kayıt yapıldığı gün
kırmızı olup bu raporun güncellenmesi gerektiğini söyler.

Ölçüm — bayraklar 0:

```
media_retention_gc_enforce             = None
media_retention_gc_originals_enforce   = None
media_retention_gc_derivatives_enforce = None
```

---

## 5. "İstendiğinde yeniden üret" — yeniden ölçüldü (T-053 kriter 4)

26 numaralı rapor "`Media Rendition.generation` alanında `lazy` seçeneği tanımlı
ama onu YAZAN kod yok" diyordu. **Bu ifade bugün kısmen yanlış** ve kod yorumu
düzeltildi:

```
YAZAN kod VAR : media/pipeline_bridge.py:628
                "generation": profil.generation or "eager"
                — türev ÜRETİLİRKEN profilden dolduruluyor.
OKUYAN kod YOK: "türev yok, şimdi üret" diyen hiçbir yol yok.
                grep regenerate|on_demand → media/ ve api/ altında üretim yolu 0.
```

Yani alan yazılıyor ama **tüketen yok**. Sonuç değişmiyor:

```
regeneration_available()  = False
Media Rendition satır     = 0
```

`action=delete` kararı `notify_only / regeneration_path_unavailable`'a düşmeye
devam ediyor. Kriter 4 **karşılanmıyor** ve bu bilinçli: T-028 ölçümü görsel
başına 10,45 sn; geri dönüşü olmayan silme yapmaktansa bildirim doğru.

---

## 6. Türev tarafı — değişmedi

`Media Rendition` tablosu boş (0 satır). Türev süpürücüsü 0 satırla koşuyor,
boş kümede sahte "0 dosya temizlendi" satırı yazmıyor, sebep sözlüğü boş
kalıyor. `_derivative_candidate` karar mantığı sentetik satırlarla test edilmeye
devam ediyor (`test_retention_gc` grupları 4 ve 6).

---

## 7. T-064 — atomik sürüm geçişi: ölçüm ve tasarım

### 7.1 Ölçüm — neden hâlâ ölçülemez

```
Media Version DocType                  -> None          (kurulu değil)
tabMedia Asset kolonları               -> asset_key, content_sha256, creation,
   docstatus, idx, last_access_at, legal_hold, media_type, modified,
   modified_by, name, owner, owner_seller, perceptual_hash, published_at,
   rejection_code, rejection_note, slot_key, source_file, state
Media Asset.active_version kolonu      -> YOK
```

Şema `doctype_specs/media_asset.json` içinde `active_version` alanını
**tanımlıyor**, ama kurulu DocType'ta yok — 34 numaralı raporun "sapma 3"
bulgusu doğrulandı. Ayrıca kurulu tabloda şemada olmayan iki alan var
(`asset_key`, `source_file`). Yani `media_asset.json` ile kurulu şema
**ayrışmış durumda**; `active_version` eklenirken bu ayrışmanın da
kapatılması gerekiyor.

"Eski sürüm geçiş boyunca erişilebilir" iddiasının dayanacağı kayıt bugün yok:
`Media Version` tablosu olmadan bir varlığın iki sürümü aynı anda var olamaz.
**ÖLÇÜLMEDİ ve bu görevde ölçülemez.**

### 7.2 Geçişin neden zaten yarı-atomik olduğu

`dedup.py` iki değişmezi zaten sağlıyor ve bunlar geçişin temeli:

- `version_hash(source_hash, policy_snapshot, crop_intent, engine_version)` —
  dört girdiden biri değişince hash değişir (INV-06).
- `rendition_path(asset, version_hash, profile, width, ext)` →
  `/files/media/{asset}/{version_hash}/{profile}-{width}.{ext}` (INV-09).

Yani **yeni sürümün dosyaları eski sürümün dosyalarının üstüne hiçbir zaman
yazmaz** — adres hash taşıdığı için ayrı dizine düşer. Atomik olmayan tek şey
"hangi sürüm yayında" sorusunun cevabı.

### 7.3 Önerilen geçiş protokolü (kurulum Şerit A'da)

Gereken tek şema değişikliği:

```
Media Asset.active_version   Link -> Media Version   (şemada VAR, kurulu DEĞİL)
```

`Media Version.is_active` (Check) zaten şemada ve açıklaması "Media Asset.
active_version ile tutarlı tutulur; sorgu kolaylığı için denormalize". İkisi
birlikte tek bir kural üretiyor:

```
Faz 1  ÜRET     yeni Media Version kaydı (is_active=0) + tüm rendition'ları
                yeni version_hash dizinine yaz.
                → eski sürüm HİÇ etkilenmedi, hâlâ yayında.
Faz 2  DOĞRULA  yeni sürümün beklenen profillerinin hepsi diskte mi.
                Eksik varsa GERİ DÖN: yeni kaydı sil, hiçbir şey değişmedi.
Faz 3  GEÇİŞ    tek transaction:
                  update tabMedia Version set is_active=0 where asset=%s
                  update tabMedia Version set is_active=1 where name=%s
                  update tabMedia Asset   set active_version=%s where name=%s
                → tek commit; okuyucu ya eski sürümü ya yeni sürümü görür.
Faz 4  SAKLA    eski sürümün rendition'ları SİLİNMEZ. Türev saklama
                politikasının (`unused_after_days`) normal konusu olurlar —
                yani en erken o süre dolduğunda ve ancak yeniden üretim yolu
                varsa aday olurlar (§5).
```

Faz 4 bu görevin ölçtüğü kısıtla doğrudan bağlı: yeniden üretim yolu yokken
eski sürümü silmek geri dönüşsüz olurdu, ve bugün `regeneration_available()`
`False`. Yani geçiş protokolü kurulsa bile eski sürümler bir süre birikir —
bu bilinçli olmalı, kaza olmamalı.

Ölçülebilirlik şartı: geçiş sırasında `active_version` okuyan bir istek eski
sürümü görmeli. Bunun testi ancak DocType kurulduktan sonra yazılabilir;
bugün yazılan bir test yeşil olamazdı, o yüzden **yazılmadı**.

---

## 8. Koşum kayıtları

| Koşum | Sonuç |
|---|---|
| `run-tests --module tradehub_core.tests.test_retention_gc` | **37 test, OK** (önce 22) |
| `run-tests --module tradehub_core.tests.test_media_usage_sources` | **12 test, OK** (yeni) |
| `run-tests --module tradehub_core.tests.test_media_usage_store` | **24 test, OK** (yeni) |
| `run-tests --module tradehub_core.tests.test_retention` | **47 test, OK** (1 atlandı) |
| `run-tests --module tradehub_core.tests.test_usage` | **45 test, OK** |
| `run-tests --module tradehub_core.tests.test_media_browse` | **14 test, OK** |
| `run-tests --module tradehub_core.tests.test_media_trash_path` | **4 test, OK** |
| `run-tests --module tradehub_core.tests.test_media_access_level` | **15 test, OK** |
| `run-tests --module tradehub_core.tests.test_seller_media_browse` | **12 test, OK** |
| `run-tests --module tradehub_core.tests.test_media_seller_backup` | **42 test, OK** |
| `python3 -m unittest ...test_media_usage_store` (frappe'siz) | **24 test, OK** |
| `python3 -m py_compile` (3 kaynak dosya) | temiz |
| `ruff check` yeni test dosyaları | **0 bulgu** |
| `ruff check` kaynak dosyalar | yalnız `UP006/UP035/UP037/UP045` — dosyaların **mevcut** stili (hepsi `typing.Dict/Optional` kullanıyor); **yeni kural ailesi eklenmedi** |

Komut deseni:

```bash
docker cp <dosya> istoc-dev-backend-1:/home/frappe/frappe-bench/apps/tradehub_core/<yol>
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_retention_gc
```

### 8.1 Vacuity — iki düzeltme de geri alındı, KIRMIZI görüldü, geri kondu

**A) Orijinal kullanım kapısı** (`_original_candidate` içindeki `in_use` dalı silindi):

```
FAIL: test_kullanimdaki_dosya_aday_olmuyor
FAIL: test_canli_envanterde_kullanimdaki_dosya_keep_in_use_aliyor
Ran 37 tests   FAILED (failures=2)
```

geri kondu → `Ran 37 tests   OK`

**B) `LIVE_SOURCES`'a eklenen 9 alan geri çıkarıldı:**

```
test_media_usage_sources:
  FAIL: test_alan_listeden_cikarilinca_ayni_adres_unused_oluyor
  FAIL: test_kor_nokta_alanlari_in_use_dondu (Admin Seller Profile.banner_image)
  FAIL: test_kor_nokta_alanlari_in_use_dondu (Seller Category.image)
  FAIL: test_kor_nokta_alanlari_in_use_dondu (Static Page SEO.og_image)
  FAIL: test_kor_nokta_alanlari_in_use_dondu (Verification Source.icon)
  FAIL: test_kapsanmayan_alan_kalmadi
  FAIL: test_kategori_gorseli_kullanim_dokumune_giriyor
  FAIL: test_marka_logosu_kullanim_dokumune_dogru_doctype_ile_giriyor
  Ran 12 tests   FAILED (failures=8)
test_retention_gc:
  FAIL: test_brand_logo_artik_usage_listesinde
  FAIL: test_brand_logosu_kullanim_kararinda_in_use
  Ran 37 tests   FAILED (failures=2)
```

geri kondu → `12 test OK` + `37 test OK`

> **Dikkat çeken ayrıntı:** `Product Category.image` bu ters çevirmede
> KIRMIZI olmadı — o adres aynı zamanda bir ürün görseli olarak da kullanılıyor,
> yani `Listing.primary_image` üzerinden zaten `in_use` çıkıyor. Kör nokta
> gerçekti (alan hiçbir listede yoktu) ama o tek adres için sonucu tesadüfen
> başka bir kaynak kurtarıyordu. Alanın listeye girmesi bu tesadüfe bağlı
> olmayı bitiriyor.

### 8.2 Test kaydı temizliği

```
File toplam        : 5042   (koşumlar öncesi ile aynı)
t053gc kalıntısı   : 0      (tabFile'da)
diskte t053gc      : 0
Media Asset        : 0
bayraklar          : üçü de None
```

---

## 9. Bu görevde ÖLÇÜLMEYENLER

1. **`FrappeUsageBackend`'in SQL'i hiç koşmadı.** `Media Usage` DocType'ı kurulu
   değil. Ölçülen şey `PersistentUsageStore`'un mantığı (sözlük backend ile);
   ölçülmeyen şey alan adı eşlemesi, `on duplicate key update` davranışı ve
   epoch↔Datetime dönüşümü. DocType kurulduğunda bu üçü ayrıca doğrulanmalı.
2. **`get_usage_store()` kalıcı dalı hiç seçilmedi** — bugün her zaman bellek içi
   depo dönüyor (ölçüldü). Kalıcı dal yalnız `usage_doctype_installed()`
   `True` olduğunda çalışır.
3. **Islak koşum yine denenmedi.** `dry_run=False` yalnız zaten var olan
   `test_kapi_uygulanamazsa_yikici_islem_durur` testinde koşuyor ve orada da
   `deleted=0` doğrulanıyor. `_apply_original` / `_apply_derivative` canlı
   veride hiç çağrılmadı.
4. **`usage_known=False` yolu üretimde tetiklenemiyor.** `_referenced_urls`
   tablo başına hatayı kendi içinde yutuyor (`continue`), o yüzden
   `live_usage_urls()` ancak import düzeyinde bir hata olursa `False` döner.
   Fail-safe dalı birim testiyle ölçüldü, canlı bir arıza senaryosuyla değil.
5. **Yeni kaynak listesinin maliyeti ölçülmedi.** `verdicts_for` docstring'indeki
   "116 ms / 10 alan" ölçümü 2026-08-18 tarihli ve bugün CANLI+SİPARİŞ 22 alan.
   Süre iddiası yapılmıyor — makine 14 ajanla paylaşımlı, ölçüm anlamsız olurdu.
   Yeni sorgu sayısı: alan başına bir `locate` taraması, yani
   `verdict_map_all` ve `live_usage_urls` için 22'şer sorgu.
6. **T-064 atomik geçiş** — `Media Version` ve `Media Asset.active_version`
   olmadan ölçülemez. §7'de protokol tasarlandı, kod yazılmadı.
7. **`missing_on_disk` sayısı** bugün 15–17 arasında değişti (kapı sırasına
   göre); 26 numaralı raporda 10'du. Envanter 14 ajanlı ortamda hareketli.

---

## 10. Şerit A'ya devredilenler

| # | İş | Neden bu görevde yapılamadı |
|---|---|---|
| 1 | `Media Usage` DocType kurulumu (`doctype_specs/media_usage.json`) | DocType kurulumu yasak; şema zaten hazır ve değişiklik önerisi yok |
| 2 | `Media Version` DocType kurulumu + `Media Asset.active_version` kolonu | Aynı. Ek olarak `media_asset.json` ile kurulu şema ayrışmış (`asset_key`, `source_file` şemada yok) — birlikte ele alınmalı |
| 3 | `hooks.py`'ye `run_scheduled_gc_originals` + `run_scheduled_gc_derivatives` kaydı; birleşik `run_scheduled_gc` kaydının çıkarılması | `hooks.py` yasak listesinde. §4.3'te satırlar ve sıra yazılı |
| 4 | Lazy/on-demand türev üretim yolu | Boru hattı işi; olmadan türev silme geri dönüşsüz |
| 5 | `Media Asset.legal_hold` için yönetim ucu (`permlevel 1`) | 26 numaralı raporun 4. maddesi, hâlâ açık |

**Islak koşuma geçme koşulu** (26 numaralı raporun §12 listesi, güncel hâli):

1. ~~`usage.py` kör noktaları kapatılmalı~~ → **KAPANDI** (§1)
2. Yeniden üretim yolu yazılmalı → **AÇIK**
3. Soğuk katman bağlanmalı (`no_cold_tier`) → **AÇIK**
4. `legal_hold` yazma yolu → **AÇIK**
5. `media_retention_gc_originals_enforce` / `..._derivatives_enforce` ancak
   1–4 bittikten sonra ve önce `limit` ile küçük bir kümede → **AÇIK**
