# 21 — T-030: SAD bağımsız mimari incelemesi

**Görev:** T-030 (Faz 3 · Sistem mimarisi) · **Tarih:** 2026-08-19 · **Dal:** `ahmet`
**İncelenen belge:** `docs/sad/SAD-v1.0.md` (782 satır, **TASLAK**, onay bloğu **yok**)
**Yan belgeler:** `docs/sad/interfaces.md` (T-031) · `docs/sad/review-v1.0.md` (T-035 Faz 3 kapanışı)
**Tetikleyen kayıt:** `docs/reports/14-nihai-denetim.md:310` — *"T-030 SAD | KISMİ | TASLAK, onay bloğu boş"*

> **Bu belge hiçbir `.py`, DocType JSON, politika JSON ya da `docs/standards/`
> dosyasına dokunmadı.** Yalnız okuma yapıldı; iki test paketi yerelde
> koşturuldu (`tradehub_core.tests.test_contracts`, `…test_policy_engine`) ve
> ikisi de site/bench/DB açmadan çalıştı. Onay bloğu **doldurulmadı** — imza
> insan kararıdır.

---

## 0. Karar (önce sonuç)

> ### SAD v1.0 bugün ONAYLANAMAZ.

Tek cümlelik gerekçe: **belge, ürüne bağlanmış hattı anlatmıyor; anlattığı hat
ise ürüne bağlı değil.**

SAD 2026-08-18 tarihli. O tarihten sonra Dalga A medya boru hattını ürüne
bağladı (5 DocType, 5. `File.after_insert` kancası, misafire açık manifest ucu,
bayrak katmanı, `Media Profile` projeksiyonu). SAD'ın §5.1/§5.4/§7.2'de çizdiği
akışların hiçbiri bu hat değil; bu hattın hiçbir parçası da SAD'da yok.

Ayrıca belgenin kendi içinde iki yapısal kusuru var: dizin ağacı gerçek olmayan
bir yol gösteriyor (M-01) ve `PolicyEngine` adıyla **iki farklı ve uyumsuz**
şeyden söz ediyor (M-02).

**Bloklayıcı 8 bulgu:** M-01, M-02, M-04, M-07, M-09, M-10, M-14, M-18.
**Kapanış kapıları:** §7'deki SAD-G1…SAD-G8. Hepsi kapanmadan onay bloğu
doldurulamaz.

**Belgenin sağlam kalan yarısı:** "korunan katman"ı anlatan her yer kodda birebir
doğrulandı — §4.2'nin 13 satırı, §6 durum makinesi, §7.3 zaman aşımı merdiveni,
§10.1 adresleme. Kusur "yeni katman"ı anlatan yerlerde yoğunlaşıyor.

---

## 1. Yöntem ve kapsam beyanı

| İşaret | Anlamı |
|---|---|
| ✅ **DOĞRULANDI** | İddianın kod karşılığı bulundu ve `dosya:satır` ile gösterildi. |
| ❌ **ÇÜRÜTÜLDÜ** | Kod iddianın tersini söylüyor. Kanıt yazılı. |
| ⚠ **ESKİMİŞ** | İddia yazıldığı gün doğruydu; bugün kod değişti. |
| 🕳 **EKSİK** | Kodda var, belgede yok. |
| ❓ **DOĞRULANMADI** | Bu oturumda ölçülemedi. Kaynak rapora güvenildi, bağımsız kanıt üretilmedi. |

**Doğrulanmayan alanlar — baştan söyleniyor:**

- §9.1'in canlı sayıları (4.958 dosya · 1.559 MB · MP dağılımı · 1.166 yetim ·
  `th_media_width` 0/2.853 · 6.443 alan referansı) **yeniden ölçülmedi.** DB'ye
  sorgu atılmadı; bu inceleme salt kaynak kodu okudu. Hepsi ❓.
- §9.2'nin T-007 süre/bellek ölçümleri (19 ms … 1.951 ms, 588/367 MB tepe RSS)
  **yeniden koşulmadı.** ❓
- §9.5'in "13,14 MB ürün detay sayfası" ve "srcset 0/31" sayıları
  **yeniden ölçülmedi.** ❓
- Frappe çekirdeğinin `File.before_insert` ↔ disk yazma sıralaması (§5.1'in A-6
  iddiasının temeli) **çalışma anında ölçülmedi**; kod okumasıyla tutarlı ama
  bağımsız kanıt üretilmedi. ❓

Doğrulanan her şey `dosya:satır` ile aşağıda.

---

## 2. Yapısal bulgular — belgenin kendi tutarlılığı

### M-01 · **BLOKLAYICI** · §2.1 dizin ağacı gerçek bir dizini göstermiyor

SAD:81-90 şu ağacı çiziyor:

```
tradehub_core/                  ← Frappe app (repo kökü)
├── tradehub_core/              ← app paketi
├── tradehub_core/media/pipeline/    ← YENİ: saf kütüphane, Frappe app DEĞİL
├── docs/
└── tests/
```

Üçüncü satır **kendi içinde çelişkili**: `tradehub_core/media/pipeline/`,
`tradehub_core/`'un kardeşi olarak çizilmiş ama yolu onun torunu. Ölçüm:

- Repo kökünde `media_engine` diye bir dizin **yok** (`ls`).
- Paket `tradehub_core/media/pipeline/` altında, yani **app paketinin içinde** —
  16 alt paket, 71 `.py`.
- Ağaçtaki `tests/` kökü de **yok**: testler `tradehub_core/tests/` altında
  (116 test dosyası). SAD:99'un G3 kanıtı "`tests/test_contracts.py`" diyor;
  gerçek yol `tradehub_core/tests/test_contracts.py`.

Belgede **6 satır hâlâ `media_engine` diyor** (SAD:66, 69, 102, 122, 167, 209),
gerisi `tradehub_core/media/pipeline` diyor. Bu, tamamlanmamış bir toplu ad
değiştirmenin izi.

**Neden kozmetik değil:** S-01 kararının başlığı *"`media_engine` ayrı bir Frappe
app'i DEĞİL, **kütüphanedir**"* ve karar metni (SAD:76) *"`tradehub_core`'un
**YANINDA duran** saf bir Python kütüphanesidir"* diyor. Gerçekte paket
`tradehub_core`'un **içine** kondu. Bu farklı bir mimari konum:

| G# | S-01 gerekçesi | Bugünkü konumda hâlâ geçerli mi |
|---|---|---|
| G1 | Ayrı app veriyi ikiye böler | Geçerli (ama artık zaten bölünmüyor) |
| G2 | Ayrı app tek kapı kuralını kırar | Geçerli |
| G3 | Kütüphane olmak test edilebilirliği artırır | ✅ **Hâlâ doğru** — aşağıda kanıtlandı |
| G4 | "Geri dönüş açık: bir gün `hooks.py` + `modules.txt` eklenerek app'e terfi eder" | ❌ **Artık geçerli değil.** App paketinin *içindeki* bir alt paket app'e terfi edemez; önce dışarı taşınması gerekir — yani G4'ün savunduğu tek yönlü olmama özelliği kayboldu. |

G3 için **kanıt üretildi** (SAD'ın kendi kanıtı, doğru yolla):

```
$ python3 -m unittest tradehub_core.tests.test_contracts
Ran 69 tests in 0.052s — OK          (frappe yok, site yok, bench yok)
$ python3 -m unittest tradehub_core.tests.test_policy_engine
Ran 38 tests in 1.623s — OK
```

`tradehub_core/__init__.py` yalnız `__version__` içeriyor, `import frappe`
yapmıyor — bu yüzden paket app'in içinde olmasına rağmen frappe'siz import
edilebiliyor. **S-01'in en değerli kısmı korunmuş, konumu korunmamış.**

### M-02 · **BLOKLAYICI** · `PolicyEngine` adı iki farklı ve uyumsuz şeye takılı

SAD §3.3, §4.1, §5.1, §5.4, §8, §11'de tek bir `PolicyEngine`'den söz ediyor.
Kodda iki tane var:

| | `contracts/policy.py:220` | `policy/engine.py:462` |
|---|---|---|
| Tür | `Protocol` (runtime_checkable) | somut sınıf |
| Açık metot | **13** | **2** (`evaluate`, `normalized_targets`) |
| Uygulayan | `fakes/policy.py:96 InMemoryPolicyEngine` | — |
| Üretimde kullanan | yok | `patches/v15_9_23_media_profile_seed.py:52` (yalnız migrate anı) |

Somut sınıf Protocol'ü **uygulamıyor**. SAD'ın diyagramlarda ve metinde adıyla
çağırdığı metotların üretim karşılığı yok:

| SAD'ın çağırdığı | Nerede tanımlı | Somut motorda |
|---|---|---|
| `check_accept()` (§5.1) | `contracts/policy.py:264` | **YOK** |
| `check_geometry()` (§5.1) | `contracts/policy.py:282` | **YOK** |
| `master_spec()` (§5.1) | `contracts/policy.py:301` | **YOK** |
| `rendition_specs()` (§5.4) | `contracts/policy.py:306` | **YOK** |
| `reload()` (§4.1 ölçek sınırı) | `contracts/policy.py:245` | **YOK** |
| `validate()` (§11 A-3) | `contracts/policy.py:326` | **YOK** |
| `source_root()` (§8 SPOF-8 azaltımı) | `contracts/policy.py:229` | **YOK** |

Doğrudan sonuçlar — SAD'da **şimdiki zamanla** yazılmış iki cümle yanlış:

- §8 SPOF-8, bugünkü azaltım olarak *"`PolicyEngine.source_root()`
  **raporlanıyor**"* diyor. Üretimde raporlayan yok; metot yalnız Protocol'de ve
  sahte uygulamada.
- §11 A-3, *"`PolicyEngine.validate()` **bugün** 9 uyarı üretiyor, 0 ihlal"*
  diyor. Somut motorda `validate()` yok.

69 sözleşme testi Protocol'ü **sahte uygulamayla** doğruluyor
(`tradehub_core/tests/test_contracts.py:42,55,80`). Somut motor sözleşmeye karşı
hiç sınanmıyor.

Bu, `docs/sad/review-v1.0.md` R-01'in eskalasyonudur. R-01 *"Tetikleyici: `api/`
katmanı yazılmadan ÖNCE"* diyordu. `api/` yazıldı **ve üretime bağlandı**
(`tradehub_core/api/media_manifest.py:79` → `pipeline.api.envelope`); karar hâlâ
verilmedi.

### M-03 · Yüksek · §3.3 ve §4.1 paketin altıda birini anlatıyor

SAD §3.3 paketi üç kutuyla çiziyor: `contracts` + `policy` + `fakes`.
Gerçek paket **16 alt paket**:

```
api  contracts  core  delivery  doctype_specs  fakes  image  migration
observability  policy  quality  security  simulator  storage  video
```

§4.1'in 6 satırlık tablosu bunlardan yalnız `contracts`'ın 6 kutusunu anlatıyor;
`core/`, `image/`, `video/`, `delivery/`, `storage/`, `security/`,
`observability/`, `quality/`, `simulator/`, `migration/`, `doctype_specs/`
**hiç geçmiyor**.

§4.2 tarafında da aynı boşluk var: `tradehub_core/media/` bugün **33 modül**;
tablo 13 satırda 17 modül kapsıyor. Tabloda olmayanlar:

```
browse.py  files.py  inventory.py  metadata.py  ownership.py  restore.py
runner.py  schema.py  timefmt.py  seller_backup.py  seller_backup_export.py
backup_export.py  pipeline_bridge.py  pipeline_flags.py  ...
```

Son ikisi kritik: **Dalga A'nın üretime bağlanma noktası tam olarak bu iki
modül** (M-09, M-13).

§13 kabul kriteri 2, *"Her bileşen için sorumluluk, bağımlılık, hata davranışı,
ölçek sınırı — §4.1 · §4.2 (tam tablo, 19 bileşen)"* diyor ve **"Karşılanmayan:
yok"** ile kapanıyor. Bu kriter **karşılanmamıştır**.

---

## 3. Kararların bugünkü gerçeği (S-01…S-06)

| # | SAD'ın kararı | Bugün | Kanıt |
|---|---|---|---|
| **S-01** | `media_engine` ayrı app değil, `tradehub_core`'un **yanında** kütüphane | ⚠ **Yarı uygulandı** — kütüphane oldu ama **içine** kondu | M-01 |
| **S-02** | pyvips değil, Pillow | ✅ **DOĞRULANDI** | `requirements.txt`'te pyvips yok; `media/engine.py` saf Pillow |
| **S-03** | **Yeni DocType açılmaz**, denetim ADL'ye | ❌ **ÇÜRÜTÜLDÜ** | M-04 |
| **S-04** | Türevler için `File` kaydı açılmaz | ✅ **DOĞRULANDI** | M-06 |
| **S-05** | Nesne deposu yok, yerel disk | ⚠ **ESKİMİŞ** | M-05 |
| **S-06** | Moderasyon asenkron | ✅ **DOĞRULANDI** | `hooks.py:283` `av.maybe_scan_on_insert` → kuyruk |

### M-04 · **BLOKLAYICI** · S-03 çürüdü: 5 yeni DocType kuruldu

SAD:117 — *"**Yeni DocType açılmaz**. Denetim `Authorization Decision Log`'a
yazılır … CLAUDE.md §4 'DocType bloat' kuralı."*

Kurulu olanlar (`tradehub_core/tradehub_core/doctype/`):

| DocType | Ne tutuyor |
|---|---|
| `Media Asset` | `slot_key`, `state`, `owner_seller`, `content_sha256`, `legal_hold`, `rejection_code`, `perceptual_hash` |
| `Media Rendition` | `asset`, `profile` (**Data**), `rendition_key`, `width/height/format`, `file_url`, `bytes`, `ssim`, `benefit_gate_passed` |
| `Media Processing Job` | `status`, `attempt`, `idempotency_key`, `started_at/finished_at`, `duration_ms`, `peak_memory_mb`, `error_code/error_trace` |
| `Media Profile` | politika profilinin DB projeksiyonu (`profile_key`, `policy_profile`, geometri, biçim, kalite) |
| `Media Engine Settings` | Single — bayraklar |

Kanıt: `patches.txt:248-250` (`v15_9_22_media_engine_settings`,
`v15_9_21_media_pipeline_doctypes`, `v15_9_23_media_profile_seed`);
`hooks.py:825-828` (`permission_query_conditions`) ve `hooks.py:904-907`
(`has_permission`) dört DocType için bağlı. Ayrıca
`tradehub_core/media/pipeline/doctype_specs/` altında **16 spesifikasyon** duruyor.

S-03 bilinçli olarak terk edilmiş görünüyor — gerekçesi bir yerde yazılı olabilir
ama **SAD'da değil**. Belge hâlâ kararı yürürlükteymiş gibi anlatıyor ve §2.3
izlenebilirlik tablosunda "S-03 denetim ADL'de → §3.3 · §4 `AuditSink` satırı"
diyor.

### M-05 · Orta · S-05 eskimiş: nesne deposu adaptörleri yazıldı

SAD:119 — *"**Yerel disk korunur** … Bugün taşıyacak bir gerekçe ölçülmedi."*

`tradehub_core/media/pipeline/storage/` bugün: `local.py`, **`s3.py`**,
**`mirror.py`**, **`tiered.py`**, `retention.py` (T-051).

Kararın **sonucu** hâlâ doğru: `s3.py:11-18` iki katı kural koyuyor —
`s3_enabled=0` iken `S3Storage` kurulamaz, fabrika yerel depoya düşer ve düşüşü
`StoragePlan.downgraded_from` ile **raporlar** (sessiz düşüş yok); `import boto3`
modül düzeyinde yok. Yani üretimde S3 kapalı.

Ama §4.1'in *"StorageAdapter · Bağımlılık: **Yerel disk (S-05)**"* satırı artık
eksik: katmanlı depo, ayna, yaslandırma sırası (`tiered.py:19-27`: soğuğa yaz →
sha256 doğrula → sıcaktan sil) ve `downgraded_from` raporlaması mimari
davranışlardır ve SAD'da yok.

### M-06 · ✅ S-04 doğrulandı

`media/pipeline_bridge.py` içinde `File` dokümanı açan **hiçbir** çağrı yok
(`new_doc("File")`, `save_file`, `get_doc({"doctype": "File"})` — sıfır eşleşme).
Modül docstring'i gerekçeyi ayrıca yazıyor (`pipeline_bridge.py:16-19`):
*"Ürettiği türevler için `File` kaydı AÇILMAZ … hem envanteri/kotayı şişirmesin
hem de `after_insert` kancası kendi kendini tetikleyip sonsuz döngü kurmasın
diye."* SAD'ın gerekçesi (kota şişmesi) doğru, koda ikinci bir gerekçe daha
eklenmiş (özyineleme).

---

## 4. Akış, kuyruk ve teslim — SAD'ın çizdiği hat ile üretimdeki hat

### M-07 · **BLOKLAYICI** · §7.2'nin "türev merdiveninin durum alanı yok" iddiası çürüdü

SAD:555 —

> | Türev merdiveni (**YENİ**) | `long` | **içerik-adresli anahtarın varlığı** | master yazıldıktan sonra | `StorageAdapter.exists()` — **durum alanı gerekmez** |

SAD:560-562 gerekçeyi de yazıyor: *"Yeni bir `th_media_*` alanı açmak, aynı
bilgiyi ikinci bir yerde tutmak olurdu (NFR-046)."*

Üretimdeki hat **tam bir durum makinesi** tutuyor: `Media Processing Job` →
`status`, `attempt`, `idempotency_key`, `started_at`, `finished_at`,
`duration_ms`, `peak_memory_mb`, `error_code`, `error_trace`. Akış
`pipeline_bridge.py:41-49`'da yazılı:

```
File.after_insert
  └─ maybe_generate_renditions   (istek thread'i — yalnız karar verir)
       └─ frappe.enqueue(queue="long", enqueue_after_commit=True)
            └─ _run_rendition_job   (worker)
                 ├─ Media Asset  (bul / oluştur)
                 ├─ Media Processing Job  (queued → running → success/failed)
                 ├─ Media Profile kayıtları → (genişlik × biçim) matrisi
                 ├─ pipeline.image.render → bayt
                 ├─ diske yaz (media/naming.py içerik-adresli + shard)
                 └─ Media Rendition satırları
```

Depo varlığı kontrolü de yapılıyor (`pipeline_bridge.py:342-356` — `Media Asset`
+ `Media Rendition` üzerinden), ama `StorageAdapter.exists()` ile değil, **DB
üzerinden**. Karar tersine döndü; SAD bunu bilmiyor ve NFR-046 gerekçesini hâlâ
savunuyor.

### M-08 · **Yüksek** · §5.1'in senkron yükleme akışı üretimde hiç çalışmıyor

- `upload_policy.check()` imzası hâlâ `(file_name, *, content, size,
  media_endpoint)` — **`slot_key` yok** (`media/upload_policy.py:307-313`).
  FR-001 ve `review-v1.0.md` R-03 açık.
- Üretim kodunda `policy/engine.py`'yi import eden **tek** yer
  `patches/v15_9_23_media_profile_seed.py:52` — yani migrate anı.
  `tradehub_core/api/*.py` ve `tradehub_core/media/*.py` içinde `PolicyEngine`
  çağrısı **yok**.

SAD bunu §5.1'de "PE (YENİ)" diye işaretlediği için **yalan söylemiyor**. Ama
§12 izlenebilirlik tablosu *"**PolicyEngine** | **Karşıladığı** FR/NFR: FR-001…
FR-018 …"* diyor — şimdiki zaman. Karşılamıyor. Doğru ifade "sorumlu olacağı"
olmalı; aksi hâlde tablo, kapanmamış 18 FR'yi kapanmış gösteriyor.

### M-09 · **BLOKLAYICI** · SAD'ın hiç anlatmadığı bir üretim akışı var

Dalga A hattı §5.1'den **bambaşka bir yerden** bağladı: yükleme kapısından değil,
`File.after_insert`'ten — yani **diske yazıldıktan sonra**.

`hooks.py:279-285`, beşinci kanca:

```python
"after_insert": [
    "tradehub_core.media.states.on_file_insert",
    "tradehub_core.media.audit.on_file_insert",
    "tradehub_core.media.transcode.maybe_transcode_on_insert",
    "tradehub_core.media.av.maybe_scan_on_insert",
    "tradehub_core.media.pipeline_bridge.maybe_generate_renditions",   # ← YENİ
],
```

Slot kimliği de istemciden değil, **`bound_to` bloklarından sunucuda türetiliyor**
(`pipeline_bridge.py:161 _resolve_scope`, `:218 _slot_from_reference`,
`:271-300 _slot_bindings`). Bu tam olarak `review-v1.0.md` R-03'ün *"sunucu
tarafında geçici çözüm olarak `bound_to` eşleşmesinden slot türetilebilir — bu
türetme **yazılmadı**"* dediği şeyin **yazılmış hâli**.

SAD'da bu akışın ne diyagramı ne bir satırı var. §2.1'in G2 gerekçesi
`hooks.py:268-271, :899`'a atıf yapıyor; bugünkü satırlar **279-285** ve **925**.

### M-10 · **BLOKLAYICI** · §5.4 teslim akışı da üretimdeki akış değil

SAD §5.4: `API → DeliveryManifest.build_image() → PolicyEngine.rendition_specs()`.

Gerçek (`tradehub_core/api/media_manifest.py`):

- `get_manifest(listing, slot, if_none_match)` — **`@frappe.whitelist(allow_guest=True)`**
  (`:154`), `get_manifest_batch` aynı (`:196`).
- Manifest, `Media Rendition` satırlarını DB'den okuyup (`:719 _turevleri_getir`)
  kütüphaneye `available_profiles` olarak veriyor (`:79-89` importları
  `pipeline.api.envelope`, `pipeline.delivery.manifest`,
  `pipeline.contracts.delivery.RenderManifest`).
- **PolicyEngine devrede değil.**

İki mimari sonuç SAD'da yok:

1. **Misafire açık bir okuma yolu** yeni DocType'lara iniyor. §3.1/§3.2 C4
   diyagramlarında böyle bir kutu yok; §8 SPOF/risk listesinde de yok.
   (Görünürlük yüklemi Dalga A'da `storefront_visible=1` olarak düzeltildi —
   `DALGA-A-DEVIR.md` B-1 — ama bu **düzeltmenin** varlığı, yolun SAD'da
   olmamasını değiştirmiyor.)
2. Manifest, politika değil **DB durumu** okuyor. Yani §5.4'ün "üretilmemiş
   profilleri SÜZ" adımı politikadan değil `Media Rendition` tablosundan geliyor.

### M-11 · Orta · Politikayı okuyan tek kapı yok — üç okuyucu var

§3.3 `policy/slots`'u yalnız PolicyEngine'in okuduğunu çiziyor (`C4 --> SLOTS`).
Gerçekte:

| Okuyucu | Yer | Ne için |
|---|---|---|
| `PolicyRegistry` | `policy/engine.py` | `evaluate()` — **üretimde istek yolunda kullanılmıyor** |
| `_slot_files()` / `load_slot_policy()` / `load_profiles()` | `image/render.py:271-288` | **üretimdeki türev merdiveni** |
| `_slot_bindings()` | `pipeline_bridge.py:271-300` (render üzerinden) | **üretimdeki slot çözümü** |

Üretimde çalışan iki yol da PolicyEngine'den geçmiyor. §3.3'ün "veri → motor"
oku bugünkü hattı temsil etmiyor.

### M-12 · Orta · Politika ile üretim arasında bir `bench migrate` var

Türev merdiveni üretimde `Media Profile` tablosundan okunuyor
(`pipeline_bridge.py:535-545`). Tablo `patches/v15_9_23_media_profile_seed.py`
ile **migrate zamanında** politika JSON'undan türetiliyor; hakikat kaynağı
JSON (`:14-17`), ama üretimdeki etkin kopya DB'de.

`review-v1.0.md` D-01 *"Yeni slot = `policy/slots/` altına bir JSON;
`engine.py` değişmez"* diyor. Üretim gerçeği: **JSON + `bench migrate`**. Seed
ayrıca idempotent ve `enabled` alanını yalnız ilk açılışta yazıyor (`:36-40`) —
yani operatörün elle kapattığı bir profil migrate ile geri açılmaz. Bunlar
mimari davranışlar; SAD'ın veri/kod ayrımı bu projeksiyon katmanını tanımıyor.

### M-13 · Yüksek · 🕳 Bayrak katmanı ve iki tasarlanmış tek-nokta SAD'da yok

`tradehub_core/media/pipeline_flags.py`, yeni hattın ürüne bağlandığı **her
noktanın tek kapısı**. İki değişmezi var (`:9-19`):

1. **Varsayılan KAPALI** — `Media Engine Settings` okunamıyorsa sonuç `False`.
2. **Ana şalter her şeyi keser** — `media_pipeline_enabled` kapalıyken alt
   bayraklar ve tüm slotlar `False` döner.

Ek olarak `is_slot_enabled()` (`:104`) slot bazlı kademeli açılış veriyor,
`active_slots` boşken hiçbir slot açık değil.

Bu bir mimari bileşendir (kill switch + kademeli yayılım + fail-safe yön) ve
§4 tablosunda **yok**. Beraberinde **iki tasarlanmış tek-nokta** geliyor,
§8 SPOF listesinde ikisi de **yok**:

| Yeni tek-nokta | Düşerse | Bugünkü davranış |
|---|---|---|
| `Media Engine Settings` (Single) | Tüm yeni hat kapanır | Fail-safe: kapalı. **Sessiz** — tasarım gereği, ama SPOF olarak kayda geçmemiş |
| `Media Profile` tablosu boş | Köprü 0 türev üretir | `pipeline_bridge.py:503` artık `frappe.log_error` yazıyor (K-1 düzeltmesi); önceden tamamen sessizdi |

---

## 5. Bu oturumda çıkan mimari çelişkiler

### M-14 · **BLOKLAYICI** · Taslak politikanın karar üzerindeki etkisi SAD'da tanımsız

`docs/reports/16-t029-politika-aktivasyonu.md:152-155`:

> **G6 ile §6.2 çelişiyor — kayda geçirildi, çözülmedi.** §6.2 "hiçbir politika
> `active` yapılamaz" diyor; G6 "en az biri `active` olmalı" diyor. İkisi aynı
> anda sağlanamaz.

Bu bir SRS iç çelişkisidir ama **mimari bir boşluğu ifşa ediyor**: SAD'ın
"politika durumu üretim kararını nasıl etkiler" sorusuna **hiç cevabı yok**.

- SAD §11 A-3 yalnız *"9 politikanın 9'u da `draft`"* diyor ve kapanış koşulunu
  FR-005'e havale ediyor. Ölçüm doğrulandı: 9/9 `draft`
  (`policy/slots/*.json` `status` alanı), açık soru sayıları 1–8 arası.
- Kodda: motor `status`'u okuyup raporluyor, **kararı değiştirmiyor**
  (`review-v1.0.md` R-04). Gölge mod (shadow mode) yazılmadı.
- Yani SAD, bir gün PolicyEngine hatta bağlandığında **taslak bir politikanın
  gerçek kullanıcıyı reddedip reddedemeyeceğini** söylemiyor. Ölçülen etki
  küçük değil: `product.image` yüklemelerinin %48,6'sı slot politikasına uymuyor
  (SAD §1).

SAD'ın mimari kuralı koyması gereken yer burası; koymamış.

### M-15 · Yüksek · İki backfill hattı SAD'da tek görünüyor

`docs/reports/17-t028-backfill-plani.md:0` — *"**En önemli tespit — iki ayrı
backfill var, script yalnız birini planlıyor.**"*

| Hat | Ne yapıyor | Ölçek |
|---|---|---|
| Eski | `media/engine.py` + `media/runner.py` — "2000 px tavanına indir, orijinali arşivle" | **49 dosya · 30,4 MB · 1 batch** |
| Yeni | `media/pipeline/image/render.py` — görsel başına 12 türev | **2.428 tekil adres · taban ~7 saat, bant 7–47 saat** |

`scripts/plan_backfill.py` yalnız birincisini planlıyor.

SAD §5.5 **tek** bir migration akışı çiziyor ve o akış ikisinin karışımı:
`PE.check_geometry → IE.probe → gates → make_master + make_ladder → ST.put`.
Gerçekte `gates.check_before` eski hattın kapısı, `make_ladder` yeni hattın işi;
ikisi bugün ayrı kodlarda ve ayrı ölçeklerde. §11 A-8 bunu tek satırla
("migration parti koşumu yapılmadı") geçiyor — asıl mesele koşulmamış olması
değil, **iki iş olduğunun tanınmaması**.

### M-16 · Orta · Video hattında geri çekilme yolu yok, SAD bunu bir hata sınıfı saymıyor

`tradehub_core/media/pipeline/video/transcode.py:363-372`:

```python
esik = min_saving_ratio()
if enforce_benefit_gate and sonuc.saving_ratio < esik:
    _sessiz_sil(gecici)
    sonuc.accepted = False
    sonuc.kept_source = True
    sonuc.notes.append("INV-05 fayda kapisi: ... -> cikti atildi, kaynak korundu")
    return sonuc
```

`return` — aynı dosyanın REMUX (faststart) ihtiyacı ayrıca değerlendirilmiyor.
`docs/reports/18-faz7-kapanis.md` K-3/K-9: canlı kütüphanenin 5 okunabilir
videosunun 4'ünde çıktı kaynaktan büyük çıktı ve **4'ünde de kapı çıktıyı attı**;
H.264 hedefi *"kütüphanenin hiçbir dosyasında bayt kazandırmıyor"*.

Yani kapı pratikte her zaman düşürüyor ve video hattı fiilen hiçbir şey
üretmiyor. SAD §4.1'in `VideoEngine` satırı hata davranışı olarak yalnız
`measured=False` ve `TranscodeFailed(attempts)` tanıyor. **"Kapı düşürdü" bir
hata değil ama bir sonuç** ve SAD'da karşılığı yok; §8'de de bir risk olarak
listelenmiyor.

### M-17 · Orta · §5.3'ün PII kapısı doğru ama **retroaktif değil**

§5.3 diyagramı doğrulandı: `access_level.set_level()` içindeki `_is_protected_pii`
iki yoldan bakıyor — `attached_to_doctype` (`access_level.py:86`) **ve** ters
referans taraması (`:88-91`, `presets.EXCLUDED_MEDIA_FIELDS` üzerinden). SAD'ın
"146 kimlik/PII belgesi `attached_to_doctype` BOŞ — tek yollu kontrol bunları
kaçırıyordu" notu kodda birebir yazılı (`presets.py:56-64`). ✅

**Ama kontrol yalnız toggle anında çalışıyor.** `_is_protected_pii` çağrıları:

```
media/access_level.py:116   ← tek uygulayıcı (set_level içinde)
media/browse.py:477, :828   ← salt raporlama (r["pii"] = ...)
api/media_admin.py:537      ← salt raporlama
```

`File` doğrudan `is_private=0` ile yüklenirse hiçbir kapı yok; ne
`before_insert`'te ne `validate`'te bu kontrol var.
`docs/reports/19-d2-hash-ortusme.md:0` düzeltilen 4 dosya tam bu yoldan gelmişti
(`Order.receipt_url` / `Payment Transaction.receipt_url`, `is_private=0`).

Ayrıca `EXCLUDED_MEDIA_FIELDS` bu oturumda genişletildi (`presets.py:70-93`):
KYB 2 → **6 alan** (+`imza_sirkuleri`, `ticaret_sicil_gazetesi`,
`faaliyet_belgesi`, `vergi_levhasi`), ayrıca `Order`, `Payment Transaction`,
`Data Export Request` eklendi. SAD §5.3 bu haritanın **kapsamının bir bakım
yükü** olduğunu söylemiyor; kod kendi bakım notunu yazmış (`presets.py:66-69`)
ama mimari belge bu bağımlılığı tanımıyor.

### M-18 · **BLOKLAYICI** · İçerik-adresli depolamanın çok-kiracılı sonucu SAD'da hiç yok

§10.1 adresleme kuralını **değişmez** ilan ediyor ve doğrulandı:

```
ad    = sha256(içerik)[:32] + uzantı      ← naming.py:55
shard = adın ilk 2 hex karakteri          ← naming.py:59-60
url   = /files/<shard>/<ad>               ← naming.py:99-104 (doc yolu)
                                             naming.py:113-124 (legacy yol)
```

**Anlatılmayan sonuç:** aynı baytı iki farklı satıcı, iki farklı doctype'a
yüklerse **aynı `file_url`'ü paylaşan N adet `File` satırı** doğar — çünkü ad
yalnız içerikten türüyor, sahipten/bağlamdan değil. Frappe çekirdeğinin
`find_file_by_url` mantığı "bu URL'e ait satırlardan **herhangi biri**
okunabiliyorsa ver" der.

`docs/reports/19-d2-hash-ortusme.md` Ö-2 bunu ölçtü: ilgisiz bir satıcı
(`cankayaplastik@istoc.com`) başka satıcının dekontlarından 3'ünü okuyabildi;
aynı URL'i paylaşan 33 özel dosyanın 29'u hassas doctype'a bağlı. Rapor ayrıca
*"Bu benim değişikliğimin sonucu değil — hiç dokunulmamış private KYB
dosyalarıyla tekrar ölçüldü, aynı desen orada da var"* diyor.

Bu, **adlandırma kararının doğrudan güvenlik sonucudur**. SAD'da:

- §10.1'de "kabul edilmiş bedel" olarak **yok**
- §8 SPOF/risk listesinde **yok**
- §2.2'de bir sapma/karar olarak **yok**

Tekilleştirmenin (dedup) bedeli SAD'da yalnız olumlu yanıyla geçiyor (§5.1
"aynı içerik → `created=False` (dedup)", §5.5 "içerik-adresli → dedup bedava").
Çok kiracılı bir pazaryerinde bunun **erişim kontrolü tarafında bir bedeli var**
ve belge onu tanımıyor.

> Not: bu sızıntının **düzeltmesi** paralel bir görevin konusu. Bu inceleme
> yalnız belge eksiğini kaydediyor; kod yazılmadı.

---

## 6. Sayı ve iddia doğrulama tabloları

### 6.1 ✅ Kodda birebir tutan iddialar

| SAD | İddia | Kanıt |
|---|---|---|
| §4.2, §7.3 | `MAX_ATTEMPTS=3`, `BACKOFF=(300,900)`, `STALE_AFTER=2700`, `SWEEP_EVERY=300` | `media/jobs.py:45,52,56,61` |
| §7.3 | `ffprobe 20 < ffmpeg 1700 < kuyruk 1800 < kayıp 2700` | `media/transcode.py:55,84,88,91` |
| §7.2 | Süpürücüler cron `*/5` | `hooks.py:110-111` |
| §6.1 | Yaşam döngüsü geçiş tablosu; `Active → Deleted` **yasak** | `media/states.py:33-40,48-60` |
| §6 | `after_insert` **dolu durumu ezmez** (yedekten dönüş tuzağı) | `media/states.py:146,165` |
| §10.1 | `sha256[:32]` + 2 hex shard; **iki çağrı yolu** | `media/naming.py:55,59-60,84-88` |
| §10.1 | Türev adı `…__<profil>.<biçim>`, aynı shard | `contracts/delivery.py:40,75` |
| §2.1 G3 | `engine.py` ve `gates.py`'de `import frappe` yok | `media/engine.py:3`, `media/gates.py:1` |
| §2.1 G3 | 69 sözleşme testi frappe/site olmadan koşuyor | Bu oturumda koşuldu: **69/69 OK** |
| §4.1 | PolicyEngine "frappe YOK, DB YOK, ağ YOK" | `policy/engine.py`'de modül düzeyi `import frappe` yok; 38 test frappe'siz OK |
| §4.2 | `access_level`: disk taşıması DB'den önce, DB patlarsa disk geri alınır | `media/access_level.py:127-141+` |
| §5.3 | PII ters referans taraması | `media/access_level.py:86-91`, `media/presets.py:70-93` |
| §11 A-1 | İki politika seti yan yana | ✅ hâlâ açık — ama daha kötü, bkz. M-21 |
| §11 A-2 | İki hata modülü | ✅ hâlâ açık: `contracts/errors.py` + `core/errors.py` ikisi de duruyor |
| §11 A-3 | 9/9 politika `draft` | ✅ doğrulandı (`status` alanı, 9 dosya) |
| §11 A-5 | Yetim uzlaştırma cron'u yok | ✅ doğrulandı — `hooks.py` scheduler'da dangling/reconcile işi yok |
| §11 A-6 | Kota kontrolü `File.before_insert`'te | ✅ `hooks.py:248-251`; **not:** artık no-op stub değil, gerçek uygulama (`entitlement/checks.py:213`) |

### 6.2 §9.3 türev sayıları — 7/9 tuttu, 2'si eskimiş (M-19)

Politika dosyalarındaki `profiles[]` blokları sayıldı:

| Slot | SAD | Ölçülen | |
|---|---:|---:|---|
| `product.image` | 12 | **12** | ✅ (7 profil; `w96`/`w192` yalnız webp — SAD'ın genişlik listesi bunu söylemiyor) |
| `company.cover_image` | 10 | **10** | ✅ |
| `document.attachment` | 1 | **1** | ✅ |
| `product.video` | 3 | **3** | ✅ |
| `category.banner` | 6 | **6** | ✅ |
| `company.cover_video` | 3 | **3** | ✅ |
| `user.avatar` | 3 | **3** | ✅ |
| `seller.logo` | 5 | **6** | ❌ `w384` eksik |
| `brand.logo` | 5 | **6** | ❌ `w384` eksik |

**M-19 · Düşük ·** SRS rev3'ün K3 kararı logo merdivenini 4 → 5 basamağa çıkardı
(`w384` eklendi) ve SAD bundan önce yazılmış. Sonuç: §9.3'ün `seller.logo`
satırı 19 × 5 = 95 diyor; bugünkü politikayla 19 × 6 = **114**. Toplam ≈29.245
de buna göre düzeltilmeli. (`brand.logo` yerel dosya sayısı zaten ölçülmemiş —
A-7.)

`max_overshoot` 1,85 iddiası (§9.5) ✅ doğrulandı: `product-image.json` içinde
1,16 / 1,49 / 1,59 / 1,66 / 1,83 / **1,85** değerleri var.

### M-20 · Düşük · A-4 gerçekleşti ama SAD'ın yazdığı yerde değil

§11 A-4: *"`th_media_width` 0/2.853 dolu … **yazma noktası master üretimi
olmalı**."*

Bugün alanı yazan bir yol **var**: `media/metadata.py:159-196 ensure_dimensions()`
— talep anında okur, boşsa `probe` edip `th_media_width`/`th_media_height`
yazar. Yani **lazy**, master üretiminde değil. SAD'ın reçetesi uygulanmadı,
farklı bir yer seçildi; §11 buna göre güncellenmeli. (Doluluk oranı bu oturumda
**ölçülmedi** ❓.)

### M-21 · Yüksek · A-1 hafife alınmış: iki set birbirinden **türetilemez**

SAD §11 A-1 ve §8 SPOF-8, çözümü *"tek kök seçilip diğeri **türetilmeli**"*
diye yazıyor. Ölçüm bunun mekanik olarak mümkün olmadığını gösteriyor:

| | `tradehub_core/media/pipeline/policy/slots/` | `docs/standards/policies/` |
|---|---|---|
| Slot sayısı | **9** | **13** |
| Slot adları | `product.image`, `seller.logo`, `brand.logo`, `company.cover_image`, `company.cover_video`, `product.video`, `category.banner`, `document.attachment`, `user.avatar` | `listing.primary_image`, `listing.gallery_image`, `listing.variant_image`, `seller_product.image`, `review.image`, `seo.og_image`, `shipping_channel.icon`, `category_showcase.tile_image`, `brand.hero_banner`, `seller.banner`, `seller.gallery_image`, `brand.logo`, `seller.logo` |
| Üst anahtarlar | `status`, `roles`, `bound_to`, `accept`, `require`, `master`, `quality`, `profiles`, `content_rules`, `on_violation`, `messages`, `open_questions` | `doctype_field`, `kind`, `is_product_slot`, `min_long_edge`, `max_long_edge`, `target_long_edge`, `aspect_ratio`, `aspect_tolerance`, `fit`, `dpi_policy`, `olcum` |
| Okuyan | `policy/engine.py`, `image/render.py`, `patches/v15_9_23…` | `tradehub_core/tests/test_policy_dpi.py:39` |

**Farklı taksonomi + farklı şema.** Ortak yalnız 2 slot adı (`brand.logo`,
`seller.logo`). Bu bir "türetme işi" değil, **eşleme + birleştirme kararı**;
FR-147 bu hâliyle kapanamaz ve SAD'ın önerdiği azaltım uygulanabilir değil.

---

## 7. Kapanış kapıları — SAD-G1…SAD-G8

SAD'ın kendi geçiş kapısı listesi **yok** (SRS §6.7'nin G1–G7'sinin karşılığı).
Bu bir eksiktir; incelemenin ilk çıktısı bu listeyi önermektir. Aşağıdaki 8 kapı
kapanmadan onay bloğu doldurulamaz.

| Kapı | Ne istiyor | Kapatan bulgular |
|---|---|---|
| **SAD-G1** | **Adlandırma ve dizin gerçeği.** §2.1 ağacı gerçek yolları göstersin (`tradehub_core/media/pipeline/`, `tradehub_core/tests/`); 6 `media_engine` kalıntısı temizlensin; S-01'in "yanında durur" ifadesi ya koda uydurulsun ya kararın değiştiği + G4 gerekçesinin düştüğü yazılsın. | M-01 |
| **SAD-G2** | **Tek `PolicyEngine`.** Protocol (13 metot) ile somut sınıf (2 metot) arasındaki uçurum bir karara bağlansın. SAD'ın adıyla çağırdığı her metot ya bir üretim uygulamasına sahip olsun ya belgede "yalnız sözleşme — uygulaması yok" diye işaretlensin. §8 SPOF-8 ve §11 A-3'teki şimdiki zamanlı iki cümle düzeltilsin. | M-02 (`review-v1.0.md` R-01) |
| **SAD-G3** | **Bugünkü hat çizilsin.** (a) Dalga A türev akışı (`File.after_insert` → `pipeline_bridge` → kuyruk → 5 DocType → `image/render` → `Media Rendition`); (b) gerçek manifest yolu (`api/media_manifest`, **misafire açık**); (c) bayrak katmanı; (d) `Media Profile` migrate-zamanı projeksiyonu; (e) üç ayrı politika okuyucusu. | M-07, M-09, M-10, M-11, M-12, M-13 |
| **SAD-G4** | **S-03 ve S-05 yeniden yazılsın.** 5 yeni DocType: karar mı değişti, istisna mı? Gerekçe ve bedel yazılsın. S-05 için S3/ayna/katmanlı adaptörler ve `downgraded_from` raporlaması §4.1'e girsin. §2.3 izlenebilirlik tablosu buna göre güncellensin. | M-04, M-05 |
| **SAD-G5** | **Politika durumu için mimari kural.** Taslak (`draft`) bir politika üretim kararını nasıl etkiler — gölge mod mu, ret mi, yok sayma mı? SRS G6 ↔ §6.2 çelişkisi hangi tarafa çözülürse SAD onu yansıtsın. | M-14 |
| **SAD-G6** | **İçerik-adresli adlandırmanın çok-kiracılı bedeli yazılsın.** §10.1'e "kabul edilmiş bedel + azaltım", §8'e yeni bir risk satırı. Ayrıca yükleme anında PII yuvası kontrolünün yokluğu §5.3'e not düşülsün. | M-18, M-17 |
| **SAD-G7** | **İki backfill hattı ve video geri çekilme boşluğu belgeye girsin.** §5.5 iki akışı ayrı ayrı göstersin; §4.1 `VideoEngine` satırı "fayda kapısı düşürdü → kaynak korunur, REMUX değerlendirilmez" sonucunu tanısın. | M-15, M-16 |
| **SAD-G8** | **Sayılar tazelensin.** §9.3 logo satırları (5 → 6) ve toplam düzeltilsin; §11 A-1 "türetme" yerine "eşleme kararı" olarak yeniden ifade edilsin; A-4'ün gerçekleşme biçimi (`ensure_dimensions`, talep anında) yazılsın; §4 bileşen tablosu Dalga A bileşenlerini kapsasın ki §13 kriter 2 gerçekten karşılansın. | M-19, M-20, M-21, M-03 |

---

## 8. §13 kabul kriterlerinin yeniden değerlendirmesi

SAD §13 dört kriterin dördünü de karşılanmış sayıyor ve *"**Karşılanmayan:
yok**"* ile kapanıyor. Bağımsız değerlendirme:

| # | Kriter | SAD | Bu inceleme |
|---|---|---|---|
| 1 | Bileşen, dağıtım, veri akışı ve durum diyagramları mermaid'de | ✅ | ⚠ **Kısmi** — diyagramlar var, ama §3.2/§3.3/§5.1/§5.4/§5.5 bugünkü hattı yanlış anlatıyor (M-03, M-09, M-10, M-11, M-15) |
| 2 | Her bileşen için sorumluluk, bağımlılık, hata davranışı, ölçek sınırı | ✅ "19 bileşen, tam tablo" | ❌ **Karşılanmadı** — `media/` 33 modülün 17'si, pipeline'ın 16 alt paketinin 6'sı kapsanıyor; `pipeline_bridge`, `pipeline_flags` ve 5 DocType yok (M-03) |
| 3 | Her karar mimaride izlenebilir | ✅ | ⚠ **Kısmi** — S-03 ve S-05 kodda tersine dönmüş, S-01 fiilen uygulanmamış (M-01, M-04, M-05) |
| 4 | Tek hata noktaları listeli, azaltımları yazılı | ✅ | ⚠ **Kısmi** — 10 SPOF geçerli, ama iki tasarlanmış yeni tek-nokta listede yok ve SPOF-8'in azaltımı uygulanabilir değil (M-13, M-21) |

---

## 9. Sonuç

**SAD v1.0 bugün ONAYLANAMAZ.**

Onaylanmasının önündeki 8 bloklayıcı: **M-01** (dizin ağacı gerçek değil),
**M-02** (`PolicyEngine` iki uyumsuz şey), **M-04** (S-03 çürüdü, 5 DocType),
**M-07** (türev durum alanı kararı tersine döndü), **M-09** (üretimdeki akış
belgede yok), **M-10** (teslim yolu belgede yok, misafire açık uç kayıtsız),
**M-14** (taslak politika kuralı tanımsız), **M-18** (içerik-adresli
depolamanın çok-kiracılı bedeli yazılmamış).

Bunlar SAD-G1…SAD-G8 ile kapanır. **Kapılar kapandığında belge onaya
sunulabilir**; kapanmadan onay bloğunun doldurulması, denetimin T-030 için
istediği "bağımsız mimari inceleme"nin sonucunu tersine çevirir.

**Adil olan taraf:** belgenin "korunan katman"ı (`tradehub_core/media/`) anlatan
her bölümü kodda birebir doğrulandı — §4.2'nin 13 satırı, §6 üç eksenli durum
makinesi, §7.3 zaman aşımı merdiveni ve değişmezleri, §10.1 adresleme, §5.3 PII
akışı. Bu bölümler bugünkü kodun **doğru** anlatımıdır ve revizyonda
korunmalıdır. Kusur, belgenin 2026-08-18'de "gelecek" diye yazdığı katmanın
2026-08-19'da **başka bir biçimde gelmiş olmasında** ve belgenin bunu
yakalamamış olmasındadır.

**Bu inceleme imza atmadı ve onay bloğu doldurmadı.** İmza, SAD-G1…SAD-G8'in
kapanmasından sonra insan kararıdır.

---

## 10. Ek — koşulan komutlar

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core

# Sözleşme testleri (frappe/site/bench GEREKMEZ)
python3 -m unittest tradehub_core.tests.test_contracts       # 69 OK
python3 -m unittest tradehub_core.tests.test_policy_engine   # 38 OK

# Politika profil sayımı (§9.3 doğrulaması)
python3 - <<'EOF'
import json, glob, os
for f in sorted(glob.glob('tradehub_core/media/pipeline/policy/slots/*.json')):
    d = json.load(open(f)); n = 0
    for p in (d.get('profiles') or []):
        fmts = p.get('formats') or []
        n += max(1, len(fmts) if isinstance(fmts, list) else 1)
    print(os.path.basename(f), d.get('slot_key'), d.get('status'), 'nesne=', n)
EOF
```

Konteynerde hiçbir komut koşturulmadı; `bench` çağrılmadı; DB'ye sorgu
atılmadı. Bu belgedeki her ✅ bir kaynak dosya satırına, her ❓ bir kaynak rapora
dayanıyor.
