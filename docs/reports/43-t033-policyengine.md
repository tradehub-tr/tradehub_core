# 43 — T-033 · `PolicyEngine` sözleşmesi gerçek uygulamaya bağlandı

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (`ahmet`) · **Görevler:** T-033
(ana), T-132, T-010/T-015 (Ö-1) · **Ortam:** yerel `python3` +
`istoc-dev-backend-1` (yalnız Ö-1 ölçümü için, **salt okunur**)

> Bu belgedeki her sayı koşturularak üretildi. Koşulmayan hiçbir şey "geçti"
> denmedi; ölçülemeyenler §6'da **ÖLÇÜLMEDİ** olarak yazılı. Süre/performans
> iddiası YOK — makinede 14 ajan paralel koşuyor, saat ölçümü anlamsız olurdu.

---

## 1. Yönetici özeti

| # | İş | Durum | Kanıt |
|---|---|:--:|---|
| T-033 | Protokol ↔ üretim sınıfı kopukluğu | ✅ **KAPATILDI** | kesişim 0 → 13, `isinstance` False → True, 75 sözleşme testi İKİ uygulamada |
| T-033-b | `PolicyRegistry.load()` yarım defter bırakıyordu | ✅ **DÜZELTİLDİ** | yeni test + [V] KIRMIZI (`0 != 9`) |
| T-033-c | İmza altın testi dönüş tipini ölçmüyordu | ✅ **SERTLEŞTİRİLDİ** | `get_type_hints` ile çözülmüş tip + [V] KIRMIZI |
| T-132 | Yetki sertleştirmesi için kalıcı regresyon ağı | ✅ **EKLENDİ** | 24 test, frappe'siz koşar, 5 ayrı [V] KIRMIZI |
| T-010/T-015 · Ö-1 | Gerçek ürün fotoğrafında hedefi tutan kalite | ✅ **ÖLÇÜLDÜ** (n=32) | canlı `product.image` örnekleminde q=20…95 tüketici tarama; §5 |

**Ö-1'in tek cümlesi:** canlı ürün görsellerinde SSIM hedefi **q80'de 30/32,
q70'te 28/32 dosyada zaten tutuluyor**; üretim arama aralığının tabanı (70)
kararı SSIM'den önce veriyor ve erişilebilir bayt tasarrufunun yarısından azı
toplanıyor (0,953× q80 yerine 0,756× mümkün). Sentetik korpusta hedefi tutmak
baytı **büyütüyordu** (1,69×); canlı içerikte **küçültüyor** — 11 §T-013.5'in
"ölçülmedi" diye bıraktığı beklenti doğrulandı.

**Yeni bulunan, kapatılmayan 4 tutarsızlık** §3'te: `D-1` (uzantı↔içerik
uyuşmazlığı iki katmanda iki karar), `R-01` (`allowed` iki tanım), `R-02`
(ölçülemeyen video `evaluate()`'te sessizce geçiyor), `R-03` (iki hata kodu
sözlüğü). Hiçbiri bu değişiklik setinde kapatılmadı; üçü politika verisine ya
da ürün kararına bağlı ve yazma alanım dışında.

---

## 2. T-033 — sorun, karar, uygulama

### 2.1 Önce: ÖLÇÜLDÜ

```
$ python3 - <<'PY'
from tradehub_core.media.pipeline.contracts.policy import PolicyEngine as Proto
from tradehub_core.media.pipeline.policy.engine  import PolicyEngine as Concrete
from tradehub_core.media.pipeline.fakes.policy   import InMemoryPolicyEngine as Fake
...
PY
proto:    13 metot  (check_accept, check_geometry, check_video, effective_limits,
                     load, master_spec, quality_threshold, reload, rendition_specs,
                     slots, source_root, validate, video_rendition_specs)
concrete: ['evaluate', 'normalized_targets']
kesisim:  []
isinstance(Concrete(), Proto) = False
isinstance(Fake(),     Proto) = True
```

Üretimde Protokolü çağıran kimse yoktu; Protokolü **karşılayan** tek sınıf
`fakes/policy.py`'ydi. `test_contracts.py`'nin 69 testi bu yüzden yalnız sahteyi
ölçüyordu. Üretim yolu ise Protokolü hiç görmüyor:

```
tradehub_core/media/pipeline/api/upload.py:199      policy_engine.default_engine()
tradehub_core/media/pipeline/api/admin.py:128       policy_engine.default_engine()
tradehub_core/media/pipeline/simulator/srcset.py:495  PolicyRegistry
tradehub_core/patches/v15_9_23_media_profile_seed.py:52  PolicyRegistry
```

### 2.2 Karar: **Protokol kalır, üretim sınıfı onu uygular**

Üç seçenek vardı; gerekçe:

| Seçenek | Neden seçilmedi / seçildi |
|---|---|
| (a) Protokolü `evaluate()` biçimine göre yeniden yaz | Protokolün taşıdığı ve BAŞKA HİÇBİR YERDE karşılığı olmayan şeyler silinirdi: `validate()` (D1–D5 değişmezleri), `source_root()` (FR-147 tek-kaynak raporlaması), `effective_limits()` (FR-007 slot×plan kesişimi), katmanlı kapı ayrımı (2 GB'lık dosyayı AÇMADAN reddetmek). `fakes/policy.py`'nin 527 satırlık gerçek kural kodu da öksüz kalırdı. |
| (b) Ayrı bir `PolicyEngineAdapter` sınıfı yaz | `isinstance(PolicyEngine(), Proto)` yine `False` kalırdı — şikâyetin tam olarak kendisi. |
| **(c) Üretim sınıfına 13 metodu ekle** | ✅ Seçilen. `evaluate()`'e ve çağıranlarına DOKUNULMAZ (saf ekleme), `isinstance` gerçekten `True` olur ve sözleşme testi iki bağımsız uygulama üzerinde koşarak **diferansiyel test**e dönüşür: aynı JSON, iki okuyucu, tek sözleşme. |

**Kritik kısıt — kural mantığı YENİDEN YAZILMADI.** Kapılar (`check_accept`,
`check_geometry`, `check_video`) `evaluate()`'in çağırdığı AYNI özel metotları
çağırır (`_check_accept`, `_check_require`, `_check_video`) ve yalnız çıktıyı
sözleşme tiplerine çevirir. Aksi hâlde ortaya ÜÇÜNCÜ bir uygulama çıkardı ve
"sözleşme testi geçti" yine üretim hakkında hiçbir şey söylemezdi.

### 2.3 Uygulama

`tradehub_core/media/pipeline/policy/engine.py` — tek dosya, saf ekleme:

* `source_root` / `slots` / `load` / `reload` → `PolicyRegistry` sarmalayıcısı.
  `load()` motorun `PolicyNotFound`'unu (`KeyError` türevi, `api/upload.py:206`
  buna dayanıyor) `contracts.errors.PolicyNotFound`'a çevirir; kayıt defterinin
  davranışı değişmez.
* `check_accept` / `check_geometry` / `check_video` → sentetik `MediaProbe`
  kurar, **üretim kural koduna delege eder**, `core.errors.Violation`'ı
  `contracts.policy.Violation`'a çevirir.
* `effective_limits` / `master_spec` / `rendition_specs` /
  `video_rendition_specs` / `quality_threshold` / `validate` → aynı JSON'dan
  okur. `validate()` üretim tarafında **yeni yetenektir**: motorun D1–D5
  değişmez denetimi yoktu.
* Çeviri tabloları (`_SEBEP_BY_RULE`, `_LAYER_BY_BLOCK`, `_ACTION_MAP`) KARAR
  tablosu değil sözlük tablosudur; hangi kuralın tetiklendiğine motor karar
  verir.

### 2.4 Sonra: ÖLÇÜLDÜ

```
kesisim: 13   eksik: []
isinstance(PolicyEngine(), contracts.policy.PolicyEngine) = True
```

`test_contracts.py` **69 → 75 test**; `PolicyContractTest`,
`ProtocolConformanceTest` ve `PipelineIntegrationTest` artık
`POLICY_IMPLS = (InMemoryPolicyEngine, PolicyEngine)` üzerinde döner.

```
$ python3 -m unittest tradehub_core.tests.test_contracts
Ran 75 tests — OK
```

**Diferansiyel sonuç:** iki uygulama, gerçek 9 politika dosyası üzerinde
sözleşmenin BÜTÜN vakalarında aynı kararı verdi — tek istisna `D-1` (§3.1).
`test_iki_uygulama_ayni_uretim_parametrelerini_verir` 9 slotun `master_spec`,
`rendition_specs`, `video_rendition_specs`, `effective_limits` ve
`quality_threshold` çıktılarını birebir eşitliyor.

### 2.5 Yan ürün: gerçek bir hata (`reload()` yarım defter bırakıyordu)

`PolicyRegistry.load()` sözlükleri **okumadan önce** temizliyordu:

```python
self._by_key.clear(); self._source.clear()
for path in sorted(self.directory.glob("*.json")):
    ...  # burada bir dosya bozuksa istisna dışarı çıkar
```

Bozuk/eksik bir JSON, kayıt defterini **yarım** bırakıyordu — hangi slotun eski
hangisinin yeni olduğu bilinmeyen bir sistem. Sözleşme (`contracts/policy.py`
`reload()`) "ya hep ya hiç" diyor; sahte uygulama zaten öyleydi, üretim değildi.
Düzeltme: yeni sözlükler ayrı kurulur, HEPSİ okunduktan sonra tek atamayla
takas edilir.

### 2.6 Vacuity — düzeltmeyi geri al, KIRMIZI göster, geri koy

| # | Geri alınan | Sonuç | Geri kondu |
|---|---|---|---|
| V-A | `engine.py`'deki 13 sözleşme metodu tamamen silindi | `Ran 75 — FAILED (failures=2, errors=37)`; ilki `PolicyEngine ... is not an instance of contracts.policy.PolicyEngine` | ✅ `Ran 75 — OK` |
| V-B | `PolicyRegistry.load()` eski (clear-önce) hâline döndürüldü | `FAIL test_reload_bozuk_dosyada_defteri_bozmaz (uygulama='PolicyEngine') — AssertionError: 0 != 9`; sahte uygulama YEŞİL kaldı (o zaten atomikti) | ✅ |
| V-C | `check_accept` dönüşü `-> Decision` (motorun kendi tipi) yapıldı | `FAIL test_imzalar_birebir_ayni ... contracts.policy.Decision != policy.engine.Decision : Dönüş tipi sözleşmenin tipi değil.` | ✅ |

**V-B'nin kendi vacuity'si de ölçüldü.** Testin ilk hâli bozuk dosyayı
`zzz-bozuk.json` adıyla yazıyordu; `sorted(glob)` onu SONA koyduğu için dokuz
politika zaten yüklenmiş oluyordu ve test **boş çıkıyordu** (düzeltme geri
alınmışken bile yeşildi). Ad `aaa-bozuk.json` yapıldı → KIRMIZI. Bu satır
raporda duruyor çünkü testin kendisi de bir kez yanlış ölçtü.

### 2.7 İmza altın testi sertleştirildi

Eski `test_imzalar_birebir_ayni` imzayı **metin olarak** karşılaştırıyordu.
`policy/engine.py` kendi `Decision` sınıfını taşıdığı için `-> Decision` yazan
bir uygulama, sözleşmenin `Decision`'ını döndürmediği hâlde metinde AYNI
görünürdü. Test ikiye ayrıldı: parametre listesi metin olarak, dönüş tipi
`typing.get_type_hints` ile **çözülerek**. V-C bunun boş olmadığını gösteriyor.

### 2.8 Regresyon koşumları (T-033 sonrası, DEĞİŞMEDİ)

Hepsi **yerel `python3` (3.9.6, Pillow 11.3.0 kurulu)** ile:

```
tradehub_core.tests.test_policy_engine     Ran 38 — OK
tradehub_core.tests.test_e2e_scenarios     Ran 39 — OK (skipped=8)
tradehub_core.tests.test_state_machine     Ran 47 — OK
tradehub_core.tests.test_simulator_srcset  exit 0
tradehub_core.tests.test_contracts         Ran 75 — OK
```

**Depo geneli koşum DEĞERLENDİRİLEBİLİR DEĞİL — yorumlayıcı yok.** Bu makinede
iki Python var ve ikisi de deponun desteklediği aralıkta (`>=3.10`, üretim
3.12) değil:

| Yorumlayıcı | Pillow | Sonuç |
|---|:--:|---|
| `python3` 3.9.6 | ✅ | `permissions.py → utils/tenant.py` zinciri `str \| None` yüzünden import edilemez |
| `/opt/homebrew/bin/python3` 3.14.6 | ❌ | görsel testleri toplu düşer (`probe_file` → `readable=False`) |

3.14'te `unittest discover` `Ran 2573 — FAILED (failures=388, errors=385,
skipped=224)` veriyor. **Bu sayı bu değişiklik seti hakkında hiçbir şey
söylemiyor** ve öyle sunulmuyor; kanıtı ölçülmüş olan tek şey şu: aynı
yorumlayıcıda `test_policy_engine` TEK BAŞINA da `FAILED (failures=10,
errors=4)` veriyor ve modülüm eklendiğinde sayı **değişmiyor** (`Ran 62 —
FAILED (failures=10, errors=4)`) — yani çapraz bulaşma yok. Aynı modül
Pillow'lu 3.9'da `Ran 38 — OK`. Depo geneli temiz koşum §6 Ö-D'de
**ÖLÇÜLMEDİ** olarak duruyor.

---

## 3. Bulgular — kapatılmadı, adıyla kayda geçti

### 3.1 D-1 · Uzantı ↔ içerik uyuşmazlığı iki katmanda iki karar

Zararsız hâl (`.png` adlı JPEG):

| Katman | Karar | Kaynak |
|---|---|---|
| Platform (`upload_policy.check`) | **uyarı** | `upload_policy.py:365-369` — "reddetmek sahadaki geçerli dosyaları keserdi" |
| Sözleşme metni + `fakes/policy.py` | **uyarı** (FR-009) | `contracts/policy.py check_accept` docstring |
| Üretim (`policy/engine.py::_check_accept`) | **RET** | `content_type_mismatch`, `action=ACTION_REJECT` **sabit yazılı** — slotun `on_violation` bloğuna bakmıyor |

İki kapıdan ikisi de geçilmesi gerektiği için net etki **rettir**.

Bu bir kaza değil, **bilinçli iki ayrı okuma**: üretim motoru uyuşmazlığı bir
güvenlik sinyali sayıyor ve regresyon testi de öyle yazılmış —
`test_policy_engine.py:430 test_uzanti_icerik_uyusmazligi_reddedilir`, fixture
`fixtures/malicious/polyglot_png_as.jpg`, docstring: *"Geçerli PNG ama adı .jpg
— 'nasılsa açılıyor' diye geçirilmez."* Platform katmanı ise aynı durumu
zararsız sayıyor ve gerekçesini canlı ölçüme dayandırıyor. İkisi aynı anda
doğru olamaz.

Hangisinin doğru olduğu ürün kararıdır ve `policy/slots/*.json` verisine
bağlıdır (Şerit D). Test bunu `POLICY_SAPMALARI` tablosunda uygulama bazında kayda
geçirir; iki uygulamanın ORTAK yanı (aynı makine kodu:
`product_image_ext_content_mismatch`) yine ortak doğrulanır. Karar verilince
tablodan tek satır silinir.

### 3.2 R-01 · `allowed` iki farklı şey demek

* `contracts.policy.Decision.allowed` → `action != reject`
* `policy.engine.Decision.allow` → `not any(v.blocking)`, `blocking` =
  `{review, manual_review, reject}` (`core/errors.py BLOCKING_ACTIONS`)

Yani `manual_review` aksiyonlu bir karar sözleşmede **izinli**, motorda
**engelleyici**. Sözleşme testinin kendisi bunu istiyor
(`test_video_olculemezse_manuel_incelemeye_duser`: `action=manual_review` **ve**
`allowed=True`). İki tanımdan biri düzeltilmeli; hangisi olduğu moderasyon
kuyruğu tasarımına bağlı ve bu görevin dışında.

### 3.3 R-02 · Ölçülemeyen video `evaluate()`'te sessizce geçiyor

ÖLÇÜLDÜ:

```
evaluate("company.cover_video", <ffprobe'suz künye>)
  → allow=True  action=pass  violations=[]
  → skipped: 15 kural, hepsi not_measurable
     (duration, bitrate, frame_rate, video_stream_present, rendition_bytes, …)
```

NFR-043 + FR-134 "ölçemediğin videoyu kurallara uygun sayma" diyor.
`skipped` listesi dürüst ama **karara girmiyor**. Sözleşme yüzeyi
(`check_video`) bunu açık bir `manual_review` uyarısına çevirir; `evaluate()`
çevirmiyor ve `api/upload.py` (yazma alanım dışında) `skipped` üzerinden bir
karar üretiyor mu ÖLÇÜLMEDİ.

### 3.4 R-03 · İki hata kodu sözlüğü

`policy/engine.py` `product_image_format_not_supported` üretirken sözleşme
`product_image_ext_not_allowed` diyor. İkisi de istemciye giden makine kodu.
Adaptör bir çeviri tablosu (`_SEBEP_BY_RULE`) taşıyor; tek sözlüğe indirmek
`api/**` yanıtlarını ve storefront'u etkiler, o yüzden yapılmadı.

---

## 4. T-132 — yetki sertleştirme regresyon ağı

`docs/reports/29-pentest-duzeltmeleri.md` bugün T1/T2/T3/T9'u ve §4.2'deki iki
yeni vektörü kapattı. O raporun üç test modülü (`test_payment_transaction_
isolation`, `test_verification_status_guard`, `test_rate_limit_guest_bucket`)
`import frappe` ile başlıyor: **bench + site olmadan koşmazlar**. Yani
düzeltmeler bugün yeşil ama sitesiz bir ortamda (CI, yerel `unittest`) sessizce
geri alınabilirler.

`tradehub_core/tests/test_authz_regression.py` (yeni, **24 test**) bu boşluğu
kapatır ve frappe'siz koşar:

| Sınıf | Tür | Ne korur |
|---|---|---|
| `T9GuestBucketRegressionTest` | davranış — GERÇEK `api/rate_limit.py`, en küçük `frappe` taklidiyle | Kova kimliği IP'ye bağlı; XFF zinciri SAĞDAN SOLA; istemcinin uydurduğu sol uç kullanılmıyor; tamamen özel zincir `_unresolved`; oturumlu kullanıcı IP'ye bağlı değil |
| `T2T3VerificationGuardRegressionTest` | davranış — GERÇEK `permissions.guard_verification_status_change` | Rolsüz kullanıcı `Verified`/`Under Review`/`Rejected`/`Suspended` yazamaz; **yeni kayıtta da** yazamaz (29 §4.2 vektörü); inceleme yetkilisi yazabilir; self-servis beyaz listesi bu dört hedefi içermiyor |
| `WiringRegressionTest` | kablolama — `ast`/JSON/metin | `hooks.py`'de `Payment Transaction` iki kaydı; `permissions.py`'de dört handler; KYC+KYB `status` permlevel **4**; `validate()`'in İLK satırı `_guard_status_change()`; `patches.txt` kaydı + patch dosyası; güvenilir-vekil aralıkları; üç pentest modülünün silinmemiş olması |

Taklit edilen şey yalnız **çerçeve** (oturum, rol listesi, istek başlığı, konf);
karar kodu gerçektir. Taklit karar verseydi test hiçbir şey ölçmezdi.

**Python 3.9 notu:** `permissions.py → utils/tenant.py` zinciri
`from __future__ import annotations` taşımadan `str | None` yazıyor; 3.10
altında import anında `TypeError`. Depo `requires-python = ">=3.10"` (üretim
3.12). Davranış sınıfı 3.10 altında **atlanır ve sebebi yazılır** — yalancı
yeşil de yalancı kırmızı da üretilmez. Ölçüldü: `python3.9 → Ran 24 (skipped=8)
OK`, `python3.14 → Ran 24 OK`.

### 4.1 Vacuity — beş ayrı geri alma

Geri almalar deponun KOPYASINDA yapıldı (`/tmp/t132vac`); `hooks.py`,
`permissions.py`, `patches.txt` ve doctype JSON'ları bu görevin **yazma alanı
değil** ve tek bir bayt bile değişmedi (`git status` ile doğrulandı).

| # | Geri alınan | KIRMIZI |
|---|---|---|
| V-1 | `_bucket_identity()` → `"Guest"` (tüm misafirler tek kova) | 7 failure — `'Guest' != 'Guest:203.0.113.10'` … |
| V-2 | KYC `status` permlevel 4 → 1 | 1 failure — `1 != 4 : status permlevel 4 değil — kendini-doğrulama yeniden açılır.` |
| V-3 | `hooks.py`'den `Payment Transaction` iki kaydı silindi | 1 failure — `None != 'tradehub_core.permissions.payment_transaction_query_conditions'` |
| V-4 | KYC `validate()`'ten `self._guard_status_change()` silindi | 1 failure — `KYC.validate() ilk satırında _guard_status_change() yok.` |
| V-5 | `guard_verification_status_change()` başına erken `return` | 5 failure — dördü `Verified/Under Review/Rejected/Suspended`, biri yeni-kayıt vektörü |

Hepsi geri kondu → `Ran 24 — OK`.

### 4.2 Kapsanmayan

* **T9'un uçtan uca yarısı bu depoda değil.** 29 §5.4: `docker/` altındaki
  `UPSTREAM_REAL_IP_ADDRESS` / `UPSTREAM_REAL_IP_RECURSIVE`. Buradaki testler
  kod tarafını korur, **topolojiyi ölçmez** — `docker/` yazma alanım dışında.
* **T4** (Compliance Officer KYC okuyamıyor) ve **T6** (imzalı belirsiz-blob)
  29 nolu raporda "DOKUNULMADI" — regresyon ağı da onları kapsamaz, kapatacak
  bir davranış yok.

---

## 5. T-010 / T-015 · Ö-1 — gerçek ürün fotoğrafında hedefi tutan kalite

`docs/reports/11-faz1-arge.md` §11 Ö-1: *"T-013 korpusunun 6/10'u sentetik
gürültü = en kötü durum; canlı görsellerden 30-50'lik tabakalı örneklem
gerekiyor."*

### 5.1 Yöntem

Yöntem T-013 ile **birebir aynı** (`scripts/measure_ssim_quality.py`), yalnız
girdi korpusu değişti:

| Parametre | Değer | Kaynak |
|---|---|---|
| Slot | `product.image` | — |
| Master biçimi / tavanı | WebP · 2400 px | `policy/slots/product-image.json` `master` |
| Hedef SSIM | `photo` 0,96 · `graphic` 0,98 | aynı dosya `quality.target_ssim_per_class` |
| Sınıflandırıcı | `quality/ssim.py::guess_content_class` | — |
| Tüketici tarama | q = 20…95, adım 1 | yer gerçeği; T-013 40'tan başlıyordu |
| İkili arama | 4 encode (`DEFAULT_MAX_ENCODES`) | ADR-0006 |
| Arama aralığı | **(70, 95)** üretim (`DEFAULT_QUALITY_RANGE`) · (40, 95) T-013 | ikisi de ölçüldü |
| Karşılaştırma tabanı | q80, q88 | bugünkü sabit kaliteler |

Örneklem: canlı `tabListing.primary_image` ∪ `tabListing Image.image` (bu ikisi
`product.image` slotudur — `media/usage.py LIVE_SOURCES`), uzun kenara göre
**tabakalı**, sabit tohum (20260819), animasyonlu ve <200 px dosyalar dışarıda.

Koşum salt okunurdur: dosyalar okundu, hiçbir şey yazılmadı; betik konteynerin
`/tmp`'sinde çalıştı ve **silindi** (§5.5).

> **Tek fark:** hazırlanan görüntü dosya başına bir kez üretilir (T-013 betiği
> her kalite adımında yeniden üretiyordu). Hazırlık deterministik olduğu için
> encode çıktısı aynıdır; yalnız tekrar eden decode yok.

### 5.2 Örneklem

| | |
|---|---|
| Havuzdaki farklı URL | **1.992** |
| Diskte bulunan, ölçülebilir aday | **1.946** |
| Ölçülen örneklem | **32** (tabaka başına 8) |
| Havuz uzun kenar dağılımı | `<1200`: 817 · `1200-1999`: 894 · `2000-2999`: 68 · `>=3000`: 167 |
| Havuz biçim dağılımı | JPEG 1.521 · WEBP 268 · PNG 157 |
| Örneklem biçim dağılımı | JPEG 25 · PNG 5 · WEBP 2 |
| Sınıflandırıcı çıktısı | `graphic` **20** (hedef 0,98) · `photo` **12** (hedef 0,96) |

### 5.3 Sonuç — T-013'ün beklediği şey doğrulandı, tersi yönüyle

**Hedefi tutan minimum kalite (tüketici tarama, yer gerçeği):**

| | T-013 korpusu (sentetik ağırlıklı, n=10) | **Ö-1 canlı ürün görselleri (n=32)** |
|---|---|---|
| min q — medyan | ~89 | **28,5** |
| min q — aralık | 76–94 | **≤20 – 92** |
| taranan tabanda (q=20) çözülen | — | **13/32** |
| hedefi tutamayan | 2/10 (bütçe) | **0/32** |
| **q80 hedefi tutuyor mu** | **1/10** | **30/32** |
| q88 hedefi tutuyor mu | 4/10 | **31/32** |
| q70 hedefi tutuyor mu | — | **28/32** |

Sınıf kırılımı: `graphic` (n=20) medyan min q **20** (yani taban), `photo`
(n=12) medyan **39**. Yalnız **4/32** dosya q>70 istiyor (77, 79, 81, 92).

**Bayt (aynı 32 dosyanın toplamı, q80 = 3.924 KB):**

| Seçilen kalite | Toplam | q80'e göre | q88'e göre | dosya başına medyan / q80 |
|---|---|---|---|---|
| Yer gerçeği (min q) | 2.966 KB | **0,756×** | 0,505× | **0,510×** |
| İkili arama **(70, 95)** — üretim | 3.738 KB | **0,953×** | 0,636× | 0,790× |
| İkili arama (40, 95) — T-013 | 3.167 KB | 0,807× | 0,539× | 0,599× |

`11-faz1-arge.md` §T-013.5'in son cümlesi — *"Bayt kazancı, korpus gerçek ürün
fotoğrafına döndüğünde beklenir — **ama ÖLÇÜLMEDİ**"* — **doğrulandı**: sentetik
korpusta hedefi tutmak baytı **1,69× büyütüyordu**, canlı ürün görsellerinde
**0,756×'e küçültüyor**.

### 5.4 ADR-0006 için ölçülen boşluk

`DEFAULT_QUALITY_RANGE = (70, 95)` **sentetik korpusta** seçildi (11 §T-013.4:
o korpusta 10/10 çözüyor, ortalama sapma 0,40). Canlı içerikte tablo tersine
dönüyor:

* Arama **28/32 dosyada 70 döndürüyor** — yani kararı SSIM hedefi değil,
  aralığın tabanı veriyor. (`ssim.py:544` bunu `reason="floor_reached"` ile
  zaten işaretliyor ve "en düşük" iddiasında bulunmuyor; yeni olan şey bu
  seçimin **ölçülmüş maliyeti**.)
* `arama_q − gercek_min_q` medyanı **41,5 kalite basamağı** (üretim aralığı),
  T-013 aralığında **13,5**.
* Hedef gerçekten bağladığında arama iyi çalışıyor: min sapma **0**, q=79
  isteyen dosyada arama 80 buldu.
* Bütçe hiç yetmezlik yaşamadı: `arama_ok` **32/32**, `encodes` her dosyada 4.

**Ölçülen sonuç:** bugünkü yapılandırmada uyarlamalı kalite, canlı ürün
görsellerinde erişilebilir tasarrufun yarısından azını topluyor (0,953× yerine
0,756× mümkün). Aralık tabanını düşürmek bunu kapatır **ama T-013'ün q92-94
gerektiren sentetik vakalarını çözemez hâle getirir** — 4 encode bütçesiyle iki
uç aynı anda tutulamıyor. Bu bir ÜRÜN/ADR kararıdır; bu değişiklik setinde
`DEFAULT_QUALITY_RANGE`'e **dokunulmadı** ve bayrak/ayar değiştirilmedi.

**Monotonluk (ikili aramanın dayanağı) canlı içerikte de tutuyor:** 32 eğride
toplam 131 komşu-çift geri düşüşü, **en büyüğü 0,000884**; 2/32 eğri hiç
ihlalsiz. Geri düşüşler hedef eşiklerinin (0,96/0,98) üç mertebe altında.

### 5.5 Uyarılar ve koşum hijyeni

* **SSIM 2400 px'te zayıf bir algısal ölçüttür.** Bu bölüm kapının
  *tanımlandığı gibi* ne yaptığını ölçer; "q20 insan gözüne yeter" DEMEZ.
  Bulgu şudur: **eşik canlı içerikte bağlamıyor**. Eşiğin kendisinin doğru
  kalibre olup olmadığı ayrı bir sorudur ve **ÖLÇÜLMEDİ** (11 §11 Ö-2, hâlâ
  açık: `scikit-image` ile çapraz doğrulama).
* **Yer gerçeğinin alt sınırı ÖLÇÜLMEDİ.** 13/32 dosya tarama tabanında (q=20)
  çözüldü; gerçek minimum **≤20** ve tam değeri bilinmiyor.
* **Sınıflandırıcı canlı içerikte `graphic` ağırlıklı** (20/32). Düz zeminli
  stüdyo ürün çekimleri `graphic` sayılıyor ve **daha sıkı** 0,98 hedefini
  alıyor. Eşik fixture etiketlerine göre kalibre edilmişti (11 §T-013.8);
  canlı etiketle doğrulaması **ÖLÇÜLMEDİ**.
* n=32, istenen 30–50 aralığının alt ucunda.
* **Hijyen:** ölçüm betiği konteynerin `/tmp`'sinde çalıştı, canlı dosyalar
  yalnız **okundu**, hiçbir kayıt/dosya yazılmadı ya da değiştirilmedi; betik
  ve çıktıları koşum sonunda silindi (§8'de doğrulama komutu).

---

## 6. ÖLÇÜLMEDİ

| # | Ölçülmeyen | Neden |
|---|---|---|
| Ö-A | `api/upload.py`'ın `Decision.skipped`'ı karara katıp katmadığı (R-02'nin ucu) | `api/**` bu görevin yazma alanı dışında; okundu ama davranışı koşulmadı |
| Ö-B | D-1'in canlı etkisi (kaç yükleme uzantı↔içerik uyuşmazlığıyla reddediliyor) | canlı `File` taraması yapılmadı |
| Ö-C | Sözleşme kapılarının `api/upload.py` akışında kullanımı | kapılar eklendi, üretim akışına BAĞLANMADI — bu bilinçli: bağlamak davranış değişikliğidir ve ayrı bir görevdir |
| Ö-D | Depo genelinde temiz `unittest discover` | Bu makinede desteklenen yorumlayıcı (3.10–3.12) YOK: 3.9'da `permissions.py` import edilemiyor, 3.14'te Pillow kurulu değil. `bench --site istoc.localhost run-tests` de koşulmadı; bu değişiklik setinde `import frappe` içeren tek satır yok |
| Ö-E | T9 uçtan uca (nginx `set_real_ip_from`) | `docker/` yazma alanı dışında (29 §5.4) |
| Ö-F | `ruff check` | ne yerelde ne konteynerde kurulu (11 §11 Ö-8 ile aynı sebep) |
| Ö-G | Ö-1'de yer gerçeğinin q<20 tarafı | 13/32 dosya tarama tabanında çözüldü; gerçek minimum ≤20, tam değeri bilinmiyor |
| Ö-H | Ö-1 eşiğinin algısal doğruluğu | SSIM'in `scikit-image` ile çapraz doğrulaması hâlâ kurulu değil (11 §11 Ö-2) |
| Ö-I | `guess_content_class`'ın canlı içerikte doğruluğu | 32 görselin 20'si `graphic` sayıldı ve **daha sıkı** hedefi aldı; etiketli canlı veri yok (11 §T-013.8) |
| Ö-J | Ö-1 ölçüm betiği depoya girmedi | Konteynerin `/tmp`'sinde koştu ve silindi (koşum hijyeni). Yöntem §5.1'de tam yazılı ama `scripts/` bu görevin yazma alanı değil; kalıcı hâli ayrı bir görevdir |

---

## 7. Değişen dosyalar

| Dosya | Ne |
|---|---|
| `tradehub_core/media/pipeline/policy/engine.py` | +13 sözleşme metodu (saf ekleme) · `PolicyRegistry.load()` ya-hep-ya-hiç · `evaluate()`/`normalized_targets()` DEĞİŞMEDİ |
| `tradehub_core/tests/test_contracts.py` | `POLICY_IMPLS` iki uygulama · `POLICY_SAPMALARI` tablosu · imza testi sertleştirildi · 69 → 75 test |
| `tradehub_core/tests/test_authz_regression.py` | **yeni** — 24 test, frappe'siz |
| `docs/reports/43-t033-policyengine.md` | bu belge |

**Dokunulmayanlar (yasak alan, `git status` ile doğrulandı):**
`policy/slots/*.json`, `hooks.py`, `permissions.py`, `patches.txt`,
`media/pipeline/image/**`, `media/pipeline/video/**`, `api/**`, `admin-panel`,
`docker/`. Bayraklar (`media/pipeline_flags.py`, `Media Engine Settings`)
**dokunulmadı**.

---

## 8. Yeniden üretme

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core

# T-033 — ölçüm (önce/sonra)
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from tradehub_core.media.pipeline.contracts.policy import PolicyEngine as Proto
from tradehub_core.media.pipeline.policy.engine import PolicyEngine as Concrete
p = {n for n, v in vars(Proto).items() if callable(v) and not n.startswith('_')}
c = {n for n in dir(Concrete) if not n.startswith('_')}
print(len(p), len(p & c), isinstance(Concrete(), Proto))
PY

# Sözleşme + regresyon
python3 -m unittest tradehub_core.tests.test_contracts          # 75
python3 -m unittest tradehub_core.tests.test_authz_regression   # 24 (3.9'da 8 atlanır)
python3 -m unittest tradehub_core.tests.test_policy_engine      # 38 (değişmedi)
```

**Ö-1 (§5) yeniden üretimi.** Betik depoda değil (Ö-J); yöntemi §5.1'de yazılı
ve `scripts/measure_ssim_quality.py`'nin birebir aynısıdır, yalnız korpus
canlıdan gelir. Özet:

```python
# konteynerde: docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 ../env/bin/python -
# 1) havuz  — product.image slotunun canlı URL'leri
#    SELECT primary_image FROM `tabListing`   WHERE primary_image LIKE '%/files/%'
#    UNION SELECT image   FROM `tabListing Image` WHERE image      LIKE '%/files/%'
# 2) örneklem — uzun kenara göre 4 tabaka × 8, random.Random(20260819)
# 3) hazırlık — scripts/measure_ssim_quality.py::_webp_hazirla (exif_transpose,
#    mod düzeltme, thumbnail(2400, LANCZOS)); dosya başına BİR KEZ
# 4) tarama   — q=20..95, im.save(buf, "WEBP", quality=q, method=4)
#               + quality.ssim.compute_ssim(ref, cikti)
# 5) arama    — quality.ssim.search_quality(..., encoder=<yukarıdaki>, reference=ref)
#               bir kez quality_range=(70,95) [üretim], bir kez (40,95) [T-013]
# 6) sınıf/hedef — guess_content_class + target_for("product.image", sinif)
```

Koşum salt okunurdur. Bittiğinde konteynerdeki betik ve JSON çıktıları silindi:
`docker exec istoc-dev-backend-1 ls /tmp/o1*` → `No such file or directory`.
