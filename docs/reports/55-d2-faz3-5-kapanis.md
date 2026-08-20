# 55 — D2 · Faz 3 · 4 · 5 kapanış ve kabul denetimi

**Görevler:** T-030 · T-031 · T-035 (Faz 3) · T-044 (Faz 4 kapanış) · T-055 (Faz 5 kapanış)
**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **HEAD:** `1ec9b5e` + commit edilmemiş çalışma ağacı
**Tür:** BELGE görevi. Hiçbir `.py`, DocType JSON, politika JSON, `docs/standards/`
ya da `docs/adr/` dosyasına dokunulmadı. Yazılan dosyalar §10'da listeli.

> **Bu belge imza atmaz ve hiçbir onay bloğu doldurmaz.** İmza insan kararıdır.
> Bayraklara dokunulmadı; ölçüm sonunda medya bayrakları **0**'dır (§7.5).

---

## 0. Karar — önce sonuç

| Soru | Cevap |
|---|---|
| **SAD v1.0 bugün onaylanabilir mi?** | **HAYIR.** 8 bloklayıcının **1'i** (M-02) bugün gerçekten kapandı, **7'si** hâlâ geçerli. SAD-G1…SAD-G8'in **7'si açık**, biri (G2) yarı kapalı. |
| **Faz 4 (T-044) kapanabilir mi?** | **HAYIR.** İlerledi — şema artık **kurulu** ve `bench migrate` **temiz**. Ama kaynağın dört kriterinden ikisi hâlâ açık: **1M asset ölçeğinde EXPLAIN** ve **migration/rollback provası + `docs/plans/rollback-doctypes.md`**. |
| **Faz 5 (T-055) kapanabilir mi?** | **HAYIR.** İstenen çıktı olan `tests/acceptance/test_storage_acceptance.py` **hâlâ yok**; 6 kabul senaryosunun 2'si dolaylı olarak kapsanıyor, 4'ü ölçülmedi. Ayrıca T-054 geri yükleme provası yapılmadı (`backup.list_sets()` → **0 set**, canlı ölçüm). |

**Bugünün üç somut kazanımı — ölçüldü, rapora değil koda/DB'ye bakıldı:**

1. **M-02 kapandı.** `PolicyEngine` Protokolü ile somut sınıfın kesişimi ∅ → **13/13**;
   `isinstance(PolicyEngine(), Proto)` **False → True**; `test_contracts` **69 → 75**
   ve yerelde de konteynerde de OK.
2. **Şema ürüne indi.** Canlı `tabDocType`'ta medya DocType sayısı bu oturum içinde
   **6 → 8 → 10** oldu; `v15_9_27…v15_9_32` altı yaması `tabPatch Log`'da
   **`skipped=0`**. `Media Asset.active_version` sapması **kapandı**.
3. **T-053'ün 1. kriteri kapandı.** `run_scheduled_gc_originals` ve
   `run_scheduled_gc_derivatives` artık **ayrı** zamanlanmış iki iş (`hooks.py:202-203`).

**Bugünün üç somut kaybı:**

1. **Faz 5 test paketi bugün KIRMIZI.** `test_retention_gc` → 37 test, **1 başarısız**
   (`test_hooks_kaydi_henuz_yok`). Kırılan şey ürün değil, **koruma testinin kendisi
   bayatladı** — ama bugün itibarıyla paket yeşil değildir.
2. **SAD gövdesi hiç değişmedi.** Yalnız §14 (inceleme kaydı) eklendi; §2.1, §2.2,
   §5.1, §5.4, §7.2, §8, §10.1, §11 **birebir eski hâlinde**. Yani 7 bloklayıcı
   belgede *kayıtlı* ama *kapatılmamış*.
3. **M-02'nin ikizi iki yerde daha var ve ölçülmemişti:** `ImageEngine` ve
   `VideoEngine` Protokollerini **yalnız sahte uygulamalar** karşılıyor; üretimdeki
   `image/render.py` ve `video/transcode.py` fonksiyon modülüdür, hiçbir sınıf
   sözleşmeyi uygulamıyor (§4.3 — **yeni bulgu**).

---

## 1. Yöntem ve kapsam beyanı

| İşaret | Anlamı |
|---|---|
| ✅ **KAPANDI** | Bloklayıcı/kriter bugün ölçülerek kapalı bulundu, kanıtı yazılı. |
| ❌ **AÇIK** | Bugün ölçüldü, hâlâ geçerli. |
| ⚠ **YARI** | Bir yarısı kapandı, diğer yarısı açık; ikisi de ayrı ayrı yazılı. |
| ❓ **DOĞRULANMADI** | Bu oturumda ölçülemedi. Kaynak rapora güvenilmedi de, çürütülmedi de. |

**Ölçüm ortamı:** yerel `python3` (frappe/site gerekmeyen paketler) +
`istoc-dev-backend-1` konteyneri (`/home/frappe/frappe-bench/env/bin/python`,
site bağlamı gerektiren paketler için `frappe.init/connect` + `rollback`).
Canlı DB'ye **yalnız `SELECT` / `SHOW`** atıldı.

**Bu oturumda ölçülmeyenler — açıkça:**

| # | Ne | Neden |
|---|---|---|
| 1 | 1M asset ölçeğinde `EXPLAIN` (T-044) | Ölçüm geçici `media_engine_ddl_test` DB'sinde yapılıp düşürülmüş; yeniden üretmek yazma gerektirir, bu görev salt okuma |
| 2 | `bench migrate` bizzat koşturulmadı | Paralel 5 ajan çalışıyor; migrate kilidi riskli. **Dolaylı ve güçlü kanıt:** yamalar `tabPatch Log`'da `skipped=0` ile duruyor ve DocType'lar canlıda (§6.1) |
| 3 | Yedek geri yükleme provası (T-054) | Prova yazma işidir; yapılmadı. `list_sets()` **0** ölçüldü |
| 4 | Üretim (prod) ortamı | Yalnız `istoc-dev-*` konteynerlerine erişim var |
| 5 | `crop_geometry.ts` ↔ `crop.py` paritesi | Konteynerde Node v20; rapor 34 §0.2a'daki engel değişmedi ❓ |
| 6 | Faz 6/7 test paketlerinin tamamı | Kapsam dışı; yalnız Faz 5'in kapı kararını etkileyen `test_render_regression` yeniden koşuldu (§7.4) |

---

## 2. Faz 3 — 8 bloklayıcının bugünkü durumu

Kaynak: `docs/reports/21-t030-mimari-inceleme.md` §9. Her satır için üç soru
soruldu: **hâlâ geçerli mi · kapandıysa kanıt ne · kapanmadıysa tek adımda ne
gerekiyor.**

### 2.1 Özet tablo

| # | Konu | Bugün | Tek cümlelik gerekçe |
|---|---|:--:|---|
| **M-01** | §2.1 dizin ağacı gerçek değil | ❌ **AÇIK** | SAD gövdesinde `media_engine` hâlâ **6 satırda** (66, 69, 102, 122, 167, 209); repo kökünde öyle bir dizin yok |
| **M-02** | `PolicyEngine` iki uyumsuz şey | ✅ **KAPANDI** | Kesişim 13/13, `isinstance` **True**, `test_contracts` **75 OK** |
| **M-04** | S-03 çürüdü (yeni DocType) | ❌ **AÇIK — ve sayı büyüdü** | Canlıda **10** medya DocType'ı; SAD §2.2 hâlâ *"Yeni DocType açılmaz"* diyor |
| **M-07** | Türev merdiveni durum alanı | ❌ **AÇIK** | SAD:555 satırı birebir aynı; `Media Processing Job` kurulu ve tam durum makinesi taşıyor |
| **M-09** | Üretim akışı belgede yok | ❌ **AÇIK** | `hooks.py` `after_insert` 5. kancası yerinde; SAD §5.1 değişmedi |
| **M-10** | Teslim yolu belgede yok | ❌ **AÇIK** | `api/media_manifest.py:154` ve `:196` hâlâ `allow_guest=True`; SAD §5.4/§3.1/§3.2 değişmedi |
| **M-14** | Taslak politika kuralı tanımsız | ❌ **AÇIK** | 9/9 `draft`; `validate()` 0 ihlal / 9 uyarı; motor durumu **raporluyor, kararı değiştirmiyor**; SAD'da kural yok |
| **M-18** | İçerik-adresli depolamanın kiracı bedeli | ⚠ **YARI** | **Kod azaltımı geldi** (`media/file_isolation.py` + `override_doctype_class`); **belge tarafı hâlâ boş** |

**Sayım: 1 kapandı · 6 açık · 1 yarı.**

### 2.2 M-01 — ❌ AÇIK

**Ölçüm:**

```
$ ls -d media_engine            → No such file or directory
$ grep -n media_engine docs/sad/SAD-v1.0.md
  66, 69, 102, 122, 167, 209    ← gövde (6 satır, rapor 21'deki sayı DEĞİŞMEDİ)
  811                           ← yeni §14, bulgunun KAYDI (düzeltme değil)
$ ls -d tradehub_core/media/pipeline/*/ | wc -l   → 15 gerçek alt paket
$ find tradehub_core/media/pipeline -name '*.py' | wc -l → 75
$ ls tradehub_core/media/*.py | wc -l             → 34   (SAD §4.2: 13 satır / 17 modül)
$ ls tradehub_core/tests/*.py | wc -l             → 137  (SAD ağacındaki `tests/` kökü YOK)
```

SAD:80-90'daki ağaç hâlâ `tradehub_core/media/pipeline/`'i `tradehub_core/`'un
**kardeşi** olarak çiziyor ve hâlâ kökte bir `tests/` gösteriyor. S-01'in
*"YANINDA duran"* ifadesi (SAD:76) ve G4 gerekçesi (*"bir gün app'e terfi
eder"*) olduğu gibi duruyor.

**Tek adımda ne gerekiyor:** §2.1'in ağacını gerçek yollarla yeniden çiz, 6
`media_engine` kalıntısını `tradehub_core/media/pipeline` yap, S-01'in "yanında
durur" cümlesine "karar uygulanırken paket app'in **içine** kondu; G4'ün
tek-yönlü-olmama gerekçesi bu konumda düşer" notunu ekle. **Kod değişikliği
gerekmiyor** — yalnız §2.1.

### 2.3 M-02 — ✅ KAPANDI

Bu, 8 bloklayıcı içinde bugün gerçekten kapanan tek maddedir. Bağımsız ölçüm:

```
$ python3 -c "…"
protocol metotları (contracts/policy.py:220)        → 13
somut sınıfta eksik (policy/engine.py:490)          → []          (rapor 21: 11 eksik)
isinstance(PolicyEngine(), Proto)                   → True        (rapor 21: False)
isinstance(InMemoryPolicyEngine(), Proto)           → True
policy/engine.py                                    → 1817 satır, NotImplementedError sayısı 0
$ python3 -m unittest tradehub_core.tests.test_contracts        → Ran 75 tests  OK
$ docker exec … env/bin/python -m unittest …test_contracts      → Ran 75 tests  OK
$ python3 -m unittest tradehub_core.tests.test_policy_engine    → Ran 38 tests  OK
```

Rapor 21'in *"SAD'ın adıyla çağırdığı 7 metodun üretim karşılığı yok"* tablosu
**tümüyle çürüdü**: `check_accept` (`engine.py:1496`), `check_geometry` (`:1532`),
`master_spec` (`:1608`), `rendition_specs` (`:1631`), `reload` (`:1472`),
`validate` (`:1685`), `source_root` (`:1429`) — hepsi gerçek gövdeli.

SAD'ın iki şimdiki-zamanlı cümlesi ayrı ayrı ölçüldü:

| SAD | İddia | Bugün |
|---|---|---|
| §11 A-3 (`SAD:748`) | *"`PolicyEngine.validate()` bugün **9 uyarı üretiyor, 0 ihlal**"* | ✅ **Artık kelimesi kelimesine doğru ve koşturulabilir.** Ölçüm: `violations=0`, `warnings=9` (`logo_draft_open_questions` ×2, `upload_draft_open_questions` ×5, `cover_video_draft_open_questions`, `product_image_draft_open_questions`) |
| §8 SPOF-8 (`SAD:602`) | *"`PolicyEngine.source_root()` **raporlanıyor**"* | ⚠ **Yarı doğru.** Metot var ve çalışıyor (`…/policy/slots` döndürüyor), ama `tradehub_core/api/`, `tradehub_core/media/*.py` ve `tradehub_core/patches/` içinde **çağıran yok** — yani Frappe'ye dönük hiçbir yüzey bunu raporlamıyor |

**Kalan tek adım (SAD-G2'nin belge yarısı):** SPOF-8 satırındaki "raporlanıyor"
ya "raporlanabilir (`PolicyEngine.source_root()`; bugün çağıran üretim yüzeyi
yok)" olarak düzeltilsin, ya da bir durum ucu bunu raporlasın. **A-3 satırına
dokunmaya gerek yok — artık doğru.**

> **Ama G2 tam kapanmıyor:** §4.3'teki yeni bulgu (`ImageEngine`/`VideoEngine`
> Protokollerini yalnız sahteler karşılıyor) aynı kusurun iki başka örneğidir ve
> G2'nin ruhu ("SAD'ın adıyla çağırdığı her metot ya üretim uygulamasına sahip
> olsun ya 'yalnız sözleşme' işaretlensin") bu ikisi için karşılanmıyor.

### 2.4 M-04 — ❌ AÇIK, üstelik sayı büyüdü

Canlı ölçüm (`SELECT name, issingle, istable FROM tabDocType WHERE name LIKE 'Media%'`):

| # | DocType | issingle | istable |
|---:|---|:--:|:--:|
| 1 | Media Asset | 0 | 0 |
| 2 | Media Crop Intent | 0 | 0 |
| 3 | Media Crop Override | 0 | **1** (alt tablo) |
| 4 | Media Engine Settings | **1** | 0 |
| 5 | Media Processing Job | 0 | 0 |
| 6 | Media Profile | 0 | 0 |
| 7 | Media Rendition | 0 | 0 |
| 8 | Media Storage Settings | **1** | 0 |
| 9 | Media Usage | 0 | 0 |
| 10 | Media Version | 0 | 0 |

Görev tanımı "8" diyordu; **ölçüm sırasında 8 → 10 oldu** (Şerit A'nın
`v15_9_28_media_usage`, `v15_9_29_media_version` yamaları benim iki sorgum
arasında uygulandı). Rapor 34'ün ölçtüğü sayı 6'ydı.

SAD §2.2 S-03 satırı ve §2.3 izlenebilirlik satırı **birebir eski hâlinde**:
*"**Yeni DocType açılmaz** … CLAUDE.md §4 'DocType bloat' kuralı"*.

**Tek adımda ne gerekiyor:** §2.2'nin S-03 satırı "karar değişti" ya da
"kapsamlı istisna" olarak yeniden yazılsın, 10 DocType'ın gerekçesi ve bedeli
(bloat, izin yüzeyi, migrate bağımlılığı) yazılsın; §2.3'ün *"S-03 denetim ADL'de
→ §4 AuditSink"* satırı düzeltilsin. **Kod değişikliği gerekmiyor.**

### 2.5 M-07 — ❌ AÇIK

`SAD:555` satırı ölçüldü, **birebir aynı**:

> `| Türev merdiveni (**YENİ**) | long | içerik-adresli anahtarın varlığı | … | StorageAdapter.exists() — durum alanı gerekmez |`

`SAD:560`'taki NFR-046 gerekçesi (*"Yeni bir `th_media_*` alanı açmak … aynı
bilgiyi ikinci bir yerde tutmak olurdu"*) da duruyor. Gerçekte
`Media Processing Job` **kurulu** ve `status`, `attempt`, `idempotency_key`,
`started_at/finished_at`, `duration_ms`, `peak_memory_mb`, `error_code`,
`error_trace` alanlarıyla tam bir durum makinesi taşıyor
(`SHOW INDEX` → `idempotency_key` **unique**, `asset`/`status`/`modified` indeksli).

**Tek adımda ne gerekiyor:** §7.2'nin ilgili satırı ve §7.2'nin gerekçe
paragrafı, kararın tersine döndüğünü ve durumun `File` alanında değil ayrı bir
DocType'ta tutulduğunu yazsın.

### 2.6 M-09 — ❌ AÇIK

`hooks.py` ölçüldü — beşinci kanca yerinde:

```python
"after_insert": [
    "tradehub_core.media.states.on_file_insert",
    "tradehub_core.media.audit.on_file_insert",
    "tradehub_core.media.transcode.maybe_transcode_on_insert",
    "tradehub_core.media.av.maybe_scan_on_insert",
    "tradehub_core.media.pipeline_bridge.maybe_generate_renditions",
],
```

SAD §5.1 hâlâ yalnız senkron yükleme kapısını çiziyor. **Tek adımda ne
gerekiyor:** §5.1'e ikinci bir akış diyagramı — `File.after_insert →
pipeline_bridge → frappe.enqueue(long) → Media Asset/Job/Rendition` — ve slotun
istemciden değil `bound_to` bloklarından sunucuda türetildiği notu.

### 2.7 M-10 — ❌ AÇIK

`tradehub_core/api/media_manifest.py:154` ve `:196` hâlâ
`@frappe.whitelist(allow_guest=True)`. SAD §3.1/§3.2 C4 diyagramlarında ve §8
SPOF/risk listesinde bu misafire açık okuma yolu **yok**.

**Tek adımda ne gerekiyor:** §5.4'e gerçek teslim akışı (`api/media_manifest` →
`Media Rendition` DB okuması → `pipeline.delivery.manifest`), §3.1/§3.2'ye
misafir aktörü, §8'e bir risk satırı.

### 2.8 M-14 — ❌ AÇIK

Ölçüm: 9 slot politikasının **9'u da `draft`**; `PolicyEngine.validate()` →
`violations=0`, `warnings=9`. Motor durumu **taşıyor ama kararı değiştirmiyor** —
`engine.Decision` alanları: `allow, slot, role, action, violations,
normalized_targets, skipped, policy_version, **policy_status**`. Yani durum
çıktıda raporlanıyor, `allow` üzerinde etkisi yok. Gölge mod (shadow mode)
kodda yok.

SAD §11 A-3 hâlâ tek satır ve kapanış koşulunu FR-005'e havale ediyor; §6.2 ↔
SRS G6 çelişkisi (`16-t029-politika-aktivasyonu.md:152-155`) çözülmedi.

**Tek adımda ne gerekiyor:** SAD'a bir mimari kural cümlesi — *"`draft` bir
politika üretim kararını ŞU şekilde etkiler: (gölge mod | yok say | reddet)"*.
Bu bir ürün kararıdır; belge onu **yansıtmalı**, üretmemeli.

### 2.9 M-18 — ⚠ YARI

**Kod tarafı bugün geldi.** `tradehub_core/media/file_isolation.py` (15.100 bayt)
yazıldı ve iki noktadan bağlandı:

- `hooks.py:999` → `has_permission["File"] = …file_isolation.file_has_permission`
- `hooks.py:1042` `override_doctype_class` → `File` için `TenantIsolatedFile`

Modülün kendi başlığı mekanizmayı ve **neden `has_permission` kancasının tek
başına yetmediğini** yazıyor (`is_downloadable()` çekirdekte modül seviyesi
`has_permission`'ı doğrudan çağırıyor; hooks zinciri o yolda hiç çalışmıyor) ve
ölçümü de taşıyor: *"949 çok-satırlı URL, 33'ü özel ve çok sahipli, 29'u
KYB/KYC/Order/Payment eki; **4 URL'de iki AYRI `content_hash`**"*.

**Belge tarafı boş.** SAD §10.1 adresleme kuralını hâlâ yalnız olumlu yanıyla
anlatıyor; §8'de risk satırı yok; §2.2'de bir sapma/karar kaydı yok.

**Tek adımda ne gerekiyor:** §10.1'e "kabul edilmiş bedel + bugünkü azaltım
(`media/file_isolation.py`, `override_doctype_class`)" paragrafı; §8'e bir risk
satırı. **Kod değişikliği gerekmiyor — azaltım zaten yazıldı.**

---

## 3. Faz 3 — SAD-G1…SAD-G8 kapı durumu

| Kapı | Konu | Bugün | Kalan tek adım |
|---|---|:--:|---|
| **SAD-G1** | Adlandırma ve dizin gerçeği | ❌ **AÇIK** | §2.1 ağacı + 6 `media_engine` + S-01/G4 notu |
| **SAD-G2** | Tek `PolicyEngine` | ⚠ **YARI** | Kod yarısı **kapandı** (13/13, `isinstance` True, 75 test). Kalan: §8 SPOF-8 cümlesi + `ImageEngine`/`VideoEngine` için aynı kararın verilmesi (§4.3) |
| **SAD-G3** | Bugünkü üretim hattı çizilsin | ❌ **AÇIK** | (a) Dalga A akışı (b) misafire açık manifest (c) bayrak katmanı (d) `Media Profile` migrate projeksiyonu (e) üç politika okuyucusu — hiçbiri §5'te yok |
| **SAD-G4** | S-03 ve S-05 yeniden yazılsın | ❌ **AÇIK** | §2.2 S-03 (artık **10** DocType) ve S-05 (S3/ayna/katmanlı + `downgraded_from`) |
| **SAD-G5** | Taslak politika için mimari kural | ❌ **AÇIK** | Kuralın kendisi (ürün kararı) yazılmadı |
| **SAD-G6** | İçerik-adresli adlandırmanın kiracı bedeli | ❌ **AÇIK** (azaltım hazır) | §10.1 + §8 metni; kod azaltımı `file_isolation.py` ile geldi |
| **SAD-G7** | İki backfill hattı + video fayda kapısı | ❓ **DOĞRULANMADI** bu oturumda; SAD §5.5 ve §4.1 gövdesi değişmediği için **açık kabul edildi** | §5.5 iki akışı ayırsın; §4.1 `VideoEngine` satırı "kapı düşürdü" sonucunu tanısın |
| **SAD-G8** | Sayılar tazelensin | ❌ **AÇIK** | §9.3 logo satırları (5 → 6; `MATRIS_ALTIN` bugün **6/6/50** olarak güncellendi, §7.4), §11 A-1/A-4, §4 bileşen tablosu (`media/` **34** modül, pipeline **15** alt paket) |

**7 kapı açık, 1 yarı. SAD v1.0 bugün ONAYLANAMAZ.**

Rapor 21'in 801. satırındaki *"bugün ONAYLANAMAZ"* hükmü **bugün de geçerlidir** —
ama gerekçesi bir madde daralmıştır: M-02 artık bu hükmün dayanağı değildir.

---

## 4. T-031 — `docs/sad/interfaces.md`

### 4.1 `PolicyEngine` tablosu ✅ DOĞRU

`interfaces.md` §2.4'ün 13 satırı, `contracts/policy.py:220`'deki Protokolün 13
metoduyla **birebir** eşleşiyor (`source_root, slots, load, reload,
effective_limits, check_accept, check_geometry, check_video, master_spec,
rendition_specs, video_rendition_specs, quality_threshold, validate`). Belge bu
noktada eskimemiş; **eskiyen taraf koddu ve bugün yetişti.**

### 4.2 §2.5 `DeliveryManifest` cümlesi ⚠ BAYAT

Belge: *"**Mevcut motorda karşılığı YOK.**"*
Ölçüm: `pipeline/delivery/manifest.py` içindeki **`ManifestBuilder`** sınıfı
Protokolün 5 metodunun tamamını taşıyor; sahte (`SimpleDeliveryManifest`) yanında
**ikinci ve üretim** uygulaması var ve `api/media_manifest.py` onu kullanıyor.

### 4.3 🆕 **YENİ BULGU** — `ImageEngine` ve `VideoEngine` Protokollerini yalnız sahteler karşılıyor

Beş çekirdek arayüzün tamamı için üretim uygulaması taraması yapıldı:

| Protokol | Metot | Sözleşmeyi karşılayan sınıflar |
|---|---:|---|
| `StorageAdapter` | 8 | `LocalDiskStorage` ✅ · `S3Storage` ✅ · `InMemoryStorage` (sahte) |
| `PolicyEngine` | 13 | `PolicyEngine` (somut) ✅ · `InMemoryPolicyEngine` (sahte) |
| `DeliveryManifest` | 5 | `ManifestBuilder` ✅ · `SimpleDeliveryManifest` (sahte) |
| **`ImageEngine`** | 6 | **yalnız `FakeImageEngine`** — üretim uygulaması YOK |
| **`VideoEngine`** | 6 | **yalnız `FakeVideoEngine`** — üretim uygulaması YOK |

Sebep ölçüldü: `image/render.py` ve `video/transcode.py` **fonksiyon
modülüdür**; içlerindeki sınıflar veri taşıyıcıdır (`RenditionProfile`,
`GeometryPlan`, `RenditionResult`, `H264Spec`, `TranscodeResult`), hiçbiri
`probe/make_master/make_rendition/make_ladder/quality_score` ya da
`needs_transcode/transcode/make_poster/make_preview_clip` sözleşmesini
uygulamıyor.

Bu **tam olarak M-02'nin şeklidir** ve rapor 21'de ölçülmemişti. SAD-G2'nin
istediği karar bu iki arayüz için de verilmelidir: ya üretim sarmalayıcısı
yazılsın, ya belgede *"yalnız sözleşme — üretim uygulaması yok, üretim yolu
fonksiyon çağırıyor"* diye işaretlensin.

### 4.4 §7 açık maddesi ❌ AÇIK

`contracts/errors.py` **ve** `core/errors.py` ikisi de duruyor (ölçüldü).
Birleştirme kararı T-035'e havale edilmişti; verilmedi. SAD §11 A-2 ile aynı madde.

---

## 5. T-035 — `docs/sad/review-v1.0.md` risk kaydının bugünkü hâli

Yalnız ölçebildiğim maddeler; ölçmediklerim tabloya alınmadı.

| # | Risk | Bugün | Kanıt |
|---|---|:--:|---|
| **R-01** | İki ayrı karar tipi yan yana | ⚠ **YARI** | Protokol yüzeyi artık `contracts` tipleriyle konuşuyor: `engine.PolicyDecision` **is** `contracts.Decision` (ölçüldü, `True`). Ama `evaluate()`'in döndürdüğü `Decision` ve `Violation` hâlâ `core/errors`'tan (`allow/slot/observed/block/message/hint`) — **iki tip hâlâ yaşıyor** |
| **R-02** | `review` ↔ `manual_review` | ❓ | Bu oturumda ölçülmedi |
| **R-03** | Slot kimliği istemciden gelmiyor | ❌ **AÇIK** | `media/upload_policy.py:330` imzası: `check(file_name, *, content, size, media_endpoint)` — **`slot_key` yok** |
| **R-04** | 9/9 politika `draft` | ❌ **AÇIK** | `validate()` → 9 uyarı / 0 ihlal (§2.8) |
| **R-06** | İki politika seti yan yana | ❌ **AÇIK** | `policy/slots/` (9 slot) ile `docs/standards/policies/` (13 slot) ayrı taksonomi; SAD §8 SPOF-8 |
| **R-10** | *"Faz 3 sonunda canlıda hiçbir şey değişmedi"* | ✅ **BAYAT** | Bugün canlıda **10 medya DocType'ı**, 6 yeni yama `skipped=0`, `Media Profile` 36 satır. Cümle artık doğru değil |

**§6 kapanış ölçütü** (9 politika yükleniyor · fixture'lara uygulanıyor ·
`bound_short999` reddediliyor · `bound_short1000` geçiyor) bu oturumda yeniden
koşulmadı ❓; ama `test_policy_engine` **38 OK** ve `test_contracts` **75 OK**
ile motorun canlı olduğu doğrulandı. §6'nın son paragrafı — *"Faz 4'ün ilk işi
R-01 ve R-03 olmalı; bu ikisi çözülmeden `api/`, `image/`, `storage/`,
`delivery/` katmanları yazılamaz"* — **fiilen aşıldı**: dört katman da yazıldı
ve `api/media_manifest.py` üzerinden üretime bağlandı; R-01 yarı, R-03 tam açık.
Bu, kapanış belgesinin kendi koşuluna uyulmadığının kaydıdır.

---

## 6. T-044 — Faz 4 kapanışı

Kaynağın kriteri: *"ER + indeks planı belgeli, her sorgu yolu indeksli; **1M
asset ölçeğinde EXPLAIN** incelendi; migration/rollback uçtan uca **provalı** +
süre raporlu."*

### 6.1 Kurulum ve migrate sağlığı — ✅ bugün kapandı

```sql
SELECT patch, skipped FROM `tabPatch Log` WHERE patch LIKE '%media%' ORDER BY creation DESC;
v15_9_32_media_metrics_token          0
v15_9_31_media_crop_override_profile  0
v15_9_30_media_asset_active_version   0
v15_9_29_media_version                0
v15_9_28_media_usage                  0
v15_9_27_media_crop_intent            0
… (v15_9_25, v15_9_23, v15_9_20, v15_9_19 …)  hepsi 0
```

Rapor 34'ün *"bench migrate temiz koşumu — ÖLÇÜLMEDİ"* maddesi bugün **dolaylı
olarak kapandı**: altı yeni yama uygulanmış, hiçbiri atlanmamış, DocType'lar
canlıda. `data-model-review.md` §8'in 3. ve 4. maddelerinin gerekçesi
(*"DocType'lar Frappe'ye kurulmadı → `bench migrate` çalıştırılacak bir şey
yok"*) **artık geçersiz** — engel kalktı, iş hâlâ yapılmadı.

### 6.2 `media_asset.json` ayrışması — ⚠ yarısı kapandı, kalanı **beyan edildi**

Görev tanımındaki tespit üç parçalıydı; her biri ayrı ölçüldü:

| Tespit | Bugün | Kanıt |
|---|:--:|---|
| `active_version` şemada var, kurulu tabloda yok | ✅ **KAPANDI** | `SHOW COLUMNS FROM tabMedia Asset LIKE 'active_version'` → **`varchar(140)`, Key=MUL**; `active_version_index` indeksi mevcut; `Media Version` DocType'ı da kuruldu |
| Kurulu tabloda şemada olmayan `asset_key` var | ⚠ **BEYAN EDİLDİ** | DocType `$comment` **sapma 4**: *"`content_sha256` TEK BAŞINA unique DEĞİL; tekillik (owner_seller, slot_key, content_sha256) üçlüsündedir ve türetilmiş `asset_key` alanı taşır"* |
| Kurulu tabloda şemada olmayan `source_file` var | ⚠ **BEYAN EDİLDİ** | `$comment` **sapma 2**: *"`source` Link→Media Source DEĞİL `source_file` Link→File"* |

Ölçülen fark kümesi: `doctype-only = {asset_key, source_file}` ·
`spec-only = {source}`. Yani ayrışma **sıfırlanmadı**, ama artık *sessiz sapma*
değil, **DocType'ın kendi `$comment`'inde numaralı ve gerekçeli beyan**. Sapma 3
metni bunu açıkça yazıyor: *"`active_version` alanı KURULDU … A1a'daki 'yok'
sapması KAPANDI."*

> **Kalan tutarsızlık:** `doctype_specs/media_asset.json` hâlâ `source` diyor ve
> `asset_key`'i tanımıyor. Şema dosyası ile kurulu DocType arasındaki tek
> hakikat kaynağı kararı verilmemiş.

### 6.3 Kurulu şemanın indeks envanteri (ölçüm)

| Tablo | UNIQUE | İkincil indeks |
|---|---|---|
| `tabMedia Asset` | `PRIMARY`, **`asset_key`** | `slot_key`, `state`, `owner_seller`, `source_file`, `content_sha256`, `perceptual_hash`, `last_access_at`, `modified`, `active_version_index` |
| `tabMedia Rendition` | `PRIMARY`, **`rendition_key`** | `asset`, `profile`, `last_access_at`, `modified` |
| `tabMedia Processing Job` | `PRIMARY`, **`idempotency_key`** | `asset`, `status`, `modified` |
| `tabMedia Profile` | `PRIMARY`, **`profile_key`** | `slot_key`, `modified`, `policy_profile_index` |
| `tabMedia Crop Intent` | `PRIMARY`, **`asset`** | `modified`, `asset_index` |
| `tabMedia Crop Override` | `PRIMARY` | `parent` (alt tablo) |

Rapor 34'ün *"`content_sha256` unique DEĞİL"* tespiti **doğrulandı** ve sapma
olarak beyan edilmiş durumda (§6.2). Satır sayıları: `Media Profile` **36**,
diğer tüm medya tabloları **0** — yani şema kurulu, hat henüz yazmıyor.

### 6.4 T-044 kriter kriter

| Kriter | Bugün | Kanıt / kalan tek adım |
|---|:--:|---|
| ER + indeks planı belgeli | ✅ | `docs/data/data-model-review.md` §1-§4 |
| Her sorgu yolu indeksli | ✅ (kurulu 6 tablo için) | §6.3 ölçümü |
| Tüm DocType'lar kurulu | ⚠ **10/15** | Kurulmayan 5: `Media Source`, `Media Policy`, `Media Policy Profile`, `Media Content Rule`, `Media Quality Report` |
| **1M asset ölçeğinde EXPLAIN** | ❌ **AÇIK** | Ölçüm geçici DB'de yapılıp düşürülmüş; `scripts/seed_synthetic.py` **yok** (ölçüldü) |
| **Migration/rollback uçtan uca provalı + süre raporlu** | ❌ **AÇIK** | `bench migrate` yönü kanıtlı (§6.1); **geri alma provası yok**, `docs/plans/rollback-doctypes.md` **yok** (ölçüldü: `docs/plans/` altında 6 dosya, hiçbiri bu değil) |
| Satıcı izolasyonu (`permission_query_conditions`) | ✅ | `hooks.py:880-891` yedi DocType için bağlı; `Media Crop Override` **alt tablo** olduğu için kapsam dışıdır (`istable=1`, ölçüldü) — eksiklik değil |

### 6.5 `data-model-review.md` §8 — 8 maddenin bugünkü hâli

| # | Madde | Bugün |
|---:|---|:--:|
| 1 | 1M asset + 30M rendition sentetik veri | ❌ AÇIK |
| 2 | `scripts/seed_synthetic.py` | ❌ AÇIK (ölçüldü: yok) |
| 3 | Migration + rollback provası | ❌ AÇIK — **gerekçesi bayat**, engel kalktı |
| 4 | `docs/plans/rollback-doctypes.md` | ❌ AÇIK — **gerekçesi bayat** |
| 5 | İzin kuralları | ✅ **KAPANDI** (`hooks.py:880-891`, `:974-986`) |
| 6 | Varsayılan profil/politika yükleme | ✅ **KAPANDI** (`v15_9_23`, `tabMedia Profile` 36 satır) |
| 7 | Pillow sürümü `engine_version`'a | ❓ ölçülmedi |
| 8 | Üç eşiğin kalibrasyonu | ❌ AÇIK |

**T-044 kararı: KAPANAMAZ.** İki maddesi (5, 6) kapandı, iki maddesinin
(3, 4) engeli kalktı ama işi yapılmadı, kaynağın iki ana kriteri (1M EXPLAIN,
rollback provası) **hâlâ açık**. Faz 4'ün kapanışı bu ikisine bağlıdır.

---

## 7. T-055 — Faz 5 kapanışı

Kaynağın kriteri: **6 kabul senaryosu**, çıktı kalemi
`tests/acceptance/test_storage_acceptance.py`.

### 7.1 İstenen çıktı — ❌ hâlâ YOK

```
$ ls -d tradehub_core/tests/acceptance      → No such file or directory
$ find . -name "*acceptance*" -not -path "./.git/*"   → (boş)
```

Bu, Faz 5'in tek **YOK**'udur ve bugün de YOK'tur. `tests/` altında 137 test
dosyası var, hiçbiri kabul paketi değil.

### 7.2 Altı senaryonun bugünkü kapsamı (ölçüm)

| # | Senaryo | Bugün | Kanıt |
|---:|---|:--:|---|
| 1 | Dört kipte uçtan uca yükleme → teslim | ⚠ **dolaylı** | `test_storage_adapters` **137 OK** + `test_storage_adapters_minio` **91 OK** (gerçek `istoc-dev-minio-1`'e karşı, 0 atlama) — ama "yükleme → teslim" uçtan uca değil, adaptör düzeyinde |
| 2 | S3+CDN kapalı → tam işlevsellik, **sıfır S3 çağrısı** | ⚠ **dolaylı** | `storage/s3.py` tembel import + `boto3_available()` `find_spec` ile; modül düzeyinde `import boto3` yok |
| 3 | S3 açık + **hatalı kimlik** → yükleme başarılı, kopya başarısız, **alarm** | ❌ **ÖLÇÜLMEDİ** | Senaryo testi yok |
| 4 | CDN açık/kapalı → aynı asset, farklı URL | ❌ **ÖLÇÜLMEDİ** | Senaryo testi yok |
| 5 | `tiered` zaman ileri sarma | ❌ **ÖLÇÜLMEDİ** | Senaryo testi yok |
| 6 | Retention kuru koşum raporu onaylı | ❌ **ÖLÇÜLMEDİ** | `test_retention_gc` kuru koşumu kapsıyor ama "onaylı rapor" akışı değil |

**2 dolaylı · 4 ölçülmedi · 0 doğrudan.**

### 7.3 Faz 5'in bileşen görevlerinin bugünkü durumu (yeniden ölçüldü)

| Görev | Rapor 34 | Bugün | Değişen |
|---|---|:--:|---|
| **T-050** StorageAdapter | TAM | ✅ **TAM** | `test_storage_adapters` **137 OK**, `…_minio` **91 OK** (bugün koşuldu). ⚠ `boto3` hâlâ `requirements.txt`'te **YOK** — ölçüldü; bugün dosyaya yalnız `elasticsearch>=8.0.0` eklenmiş |
| **T-051** Ayarlar ekranı | TAM | ✅ **TAM** | `test_media_storage_settings` **19 OK** (bugün, site bağlamında koşuldu) |
| **T-052** CDN teslim | KISMİ | ❌ **KISMİ (değişmedi)** | `cdn_purge_api_url`/`cdn_purge_token` alanlarını okuyan **hiçbir Python kodu yok** (`grep cdn_purge --include=*.py` → **0 sonuç**) → kriter (3) "purge API'si çalışır" karşılanmıyor |
| **T-053** Retention/GC | KISMİ | ⚠ **1. kriter KAPANDI, 4. kriter AÇIK** | `hooks.py:202-203` artık **iki ayrı iş**: `run_scheduled_gc_originals` + `run_scheduled_gc_derivatives` (ayrı bayrak, ayrı kilit; birleşik `run_scheduled_gc` bilerek bırakılmış). Ama `regenerate_on_demand` hâlâ **tüketilmiyor**: bayrağı okuyan var (`media_storage_settings.py:316`, `retention.py:396`), silinen türevi **yeniden üreten yol yok** |
| **T-054** Yedek / DR | KISMİ | ❌ **DEĞİŞMEDİ** | **Canlı ölçüm:** `backup.list_sets()` → **0 set**. Planın kendi ifadesi geçerli: *"fiilî RPO **Sınırsız**, fiilî RTO **Ölçülemez**"*. Geri yükleme provası yapılmadı |

### 7.4 🔴 Faz 5 test paketi bugün KIRMIZI

Site bağlamında koşuldu (`frappe.init/connect` + `rollback`, yazma yok):

```
test_retention_gc            run=37  fail=1  err=0  skip=0     ← KIRMIZI
test_media_storage_settings  run=19  fail=0  err=0  skip=0
test_storage_adapters        run=137 fail=0  err=0  skip=0
test_storage_adapters_minio  run=91  fail=0  err=0  skip=0
```

Başarısız test: `TestAyriZamanlanmisIsler.test_hooks_kaydi_henuz_yok`.
Kırılma mesajı testin kendi cümlesidir:

> *"`run_scheduled_gc_originals` artık `hooks.py`'de kayıtlı —
> `docs/reports/40-t043-kullanim-gc.md` güncellenmeli"*

Yani bu bir **ürün regresyonu değil, bayatlamış bir koruma testidir**: test
"kanca henüz kayıtlı DEĞİL" varsayımını doğruluyordu, Şerit A kancayı kaydetti.
Bu, T-053'ün 1. kriterinin kapandığının **kanıtı**dır. **Ama bugün itibarıyla
Faz 5 paketi yeşil değildir** ve bir kapanış kararı kırmızı paket üzerine
kurulamaz. Tek adım: testin varsayımı ve rapor 40 güncellensin.

Karşılaştırma için Faz 6'nın kilidi de yeniden koşuldu — **rapor 34'ün 2.
başarısızlığı kapanmış:**

```
$ docker exec … env/bin/python -m unittest tradehub_core.tests.test_render_regression
Ran 32 tests   OK (skipped=1)          ← rapor 34: FAILED (1), matris 5/5/48 ≠ 6/6/50
```

`MATRIS_ALTIN` güncellenmiş; rapor 34 §8'in 1. iş kalemi **kapandı**.

### 7.5 Bayraklar — 0 (ölçüldü, dokunulmadı)

```
site_config.json içinde 'media' geçen anahtarlar:
  {'media_metrics_token': '<sır>'}
```

Tek medya anahtarı `media_metrics_token`'dır ve o bir **Prometheus scrape
sırrıdır**, özellik bayrağı değil (`v15_9_32` yamasının başlığı: *"Uç FAIL-CLOSED
yazıldı … Yama güçlü bir sır üretip yalnız `site_config.json`a yazar"*).
`media_retention_gc_enforce` ve türevleri **yok** → GC hâlâ kuru koşum.
`media_pipeline_enabled` site_config'te yok → yeni hat kapalı (fail-safe yön).
**Bu ölçüm sırasında hiçbir bayrak açılmadı.**

**T-055 kararı: KAPANAMAZ.** İstenen kabul paketi yok; 6 senaryonun 4'ü
ölçülmedi; T-054'ün geri yükleme provası yapılmadı; ve Faz 5 test paketi bugün
kırmızı.

---

## 8. Bu denetimde çıkan, başka raporda olmayan bulgular

| # | Bulgu | Kanıt | Kimin işi |
|---:|---|---|---|
| **Y-1** | `ImageEngine` ve `VideoEngine` Protokollerinin **üretim uygulaması yok** — yalnız sahteler karşılıyor. M-02'nin ikizi, iki kez | §4.3 ölçümü | T-030/T-031 (belge kararı) ya da bir sarmalayıcı |
| **Y-2** | `interfaces.md` §2.5'in *"`DeliveryManifest`'in mevcut motorda karşılığı YOK"* cümlesi **bayat** — `ManifestBuilder` sözleşmeyi tam karşılıyor ve üretimde kullanılıyor | §4.2 | T-031 |
| **Y-3** | `review-v1.0.md` §6'nın *"R-01 ve R-03 çözülmeden `api/`, `image/`, `storage/`, `delivery/` yazılamaz"* koşulu **fiilen aşıldı**; dördü de yazıldı, R-03 hâlâ açık | §5 | T-035 |
| **Y-4** | `doctype_specs/media_asset.json` hâlâ `source` diyor, `asset_key`'i tanımıyor; kurulu DocType ise ikisini de taşıyor. Hakikat kaynağı kararı verilmemiş | §6.2 | Şerit A / T-040 |
| **Y-5** | `test_retention_gc.test_hooks_kaydi_henuz_yok` bayatladı ve Faz 5 paketini kırmızıya düşürüyor; testin kendi mesajı rapor 40'ın güncellenmesini istiyor | §7.4 | Şerit A / T-053 |
| **Y-6** | `boto3` hâlâ `requirements.txt`'te yok (bugün dosyaya yalnız `elasticsearch` eklendi) — T-050'nin 91 MinIO testi imaj yeniden kurulunca çalışmaz | §7.3 | T-050 |
| **Y-7** | `cdn_purge_*` alanları **hiçbir Python kodu tarafından okunmuyor** (0 eşleşme); T-052'nin 3. kriteri yapısal olarak açık | §7.3 | T-052 |

---

## 9. Net karar

> ### SAD v1.0 bugün ONAYLANAMAZ.
> 8 bloklayıcının 1'i (M-02) kapandı, 1'i yarı (M-18), 6'sı açık.
> 8 kapının 7'si açık, 1'i (G2) yarı kapalı.
> **Onay bloğu doldurulmadı; imza atılmadı.**

> ### Faz 4 (T-044) KAPANAMAZ.
> Şema kuruldu ve `migrate` temiz — kapanışın önündeki iki engel artık
> **teknik değil, yapılmamış iş**: 1M ölçeğinde EXPLAIN ve rollback provası +
> `docs/plans/rollback-doctypes.md`.

> ### Faz 5 (T-055) KAPANAMAZ.
> `tests/acceptance/` yok; 6 senaryonun 4'ü ölçülmedi; T-054 geri yükleme
> provası yapılmadı (`list_sets()` → 0); ve paket bugün kırmızı.

**Kapanışa en yakın olan:** Faz 4 — iki somut iş kalemi kaldı ve ikisinin de
engeli bugün kalktı.
**Kapanışa en uzak olan:** Faz 5 — istenen çıktı hiç üretilmedi ve T-054 bir
prova gerektiriyor.
**Faz 3'ün kapanışı belge işidir, kod işi değildir:** açık 6 bloklayıcının
**hiçbiri kod değişikliği istemiyor**; altısı da SAD gövdesinin bugünkü hattı
anlatmasıyla kapanır. M-18'in azaltımı bile yazıldı — eksik olan yalnız
belgedeki iki paragraf.

---

## 10. Bu görevin yan etkileri ve yazdığı dosyalar

**Kod, DocType JSON, politika JSON, `docs/standards/`, `docs/adr/`, `admin-panel`,
`docker/` — hiçbirine dokunulmadı. Hiçbir bayrak açılmadı. Hiçbir kayıt
oluşturulmadı; site bağlamında koşan testler `frappe.db.rollback()` ile kapandı.**

| Dosya | Ne yapıldı |
|---|---|
| `docs/reports/55-d2-faz3-5-kapanis.md` | **yeni** — bu belge |
| `docs/sad/SAD-v1.0.md` | **yalnız §14.5 eklendi** — "kanıt ve kapı durumu". §14.1-§14.4 ve tüm gövde (§1-§13) **değiştirilmedi**; onay bloğu **doldurulmadı** |
| `docs/sad/review-v1.0.md` | **yalnız sona bir bölüm eklendi** — risk kaydının bugünkü ölçümü. Mevcut hiçbir satır değiştirilmedi |
| `docs/data/data-model-review.md` | **yalnız sona bir bölüm eklendi** — §8'in bugünkü ölçümü. **§10 Onay bloğuna dokunulmadı** |

---

## 11. Ek — koşulan komutlar

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core

# ── Faz 3 · sözleşme ──────────────────────────────────────────
python3 -m unittest tradehub_core.tests.test_contracts        # 75 OK
python3 -m unittest tradehub_core.tests.test_policy_engine    # 38 OK
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  python3 -m unittest tradehub_core.tests.test_contracts      # 75 OK

# PolicyEngine Protokol kesişimi + validate() + source_root()
python3 - <<'PY'
from tradehub_core.media.pipeline.contracts.policy import PolicyEngine as P
from tradehub_core.media.pipeline.policy.engine  import PolicyEngine as C, default_engine
from tradehub_core.media.pipeline.fakes.policy   import InMemoryPolicyEngine as F
import os
print([m for m in dir(P) if not m.startswith('_')])
e = C(os.path.join('tradehub_core','media','pipeline','policy','slots'))
print(isinstance(e, P), isinstance(F(), P))
d = default_engine().validate()
print(len(d.violations), len(d.warnings), default_engine().source_root())
PY

# Beş Protokolün üretim uygulaması taraması (§4.3)
# → StorageAdapter 2+1, PolicyEngine 1+1, DeliveryManifest 1+1,
#   ImageEngine 0+1, VideoEngine 0+1

# ── Canlı DB (SALT OKUMA) ─────────────────────────────────────
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
  bench --site istoc.localhost mariadb -e \"
    SELECT name, issingle, istable FROM tabDocType WHERE name LIKE 'Media%' ORDER BY name;
    SHOW COLUMNS FROM \\\`tabMedia Asset\\\` LIKE 'active_version';
    SELECT patch, skipped FROM \\\`tabPatch Log\\\` WHERE patch LIKE '%media%' ORDER BY creation DESC LIMIT 10;
    SHOW INDEX FROM \\\`tabMedia Asset\\\`;
  \""

# Yedek setleri (T-054)
docker exec istoc-dev-backend-1 bash -lc "cd /home/frappe/frappe-bench && \
  bench --site istoc.localhost console <<'EOF'
from tradehub_core.media import backup
print('SETS=', len(backup.list_sets()))
EOF"                                                          # SETS= 0

# ── Faz 5 · site bağlamı gerektiren paketler (rollback ile) ───
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -c "
import frappe, unittest
frappe.init(site='istoc.localhost'); frappe.connect()
for m in ['test_retention_gc','test_media_storage_settings','test_storage_adapters']:
    s = unittest.defaultTestLoader.loadTestsFromName('tradehub_core.tests.'+m)
    r = unittest.TextTestRunner(verbosity=0, stream=open('/dev/null','w')).run(s)
    print(m, r.testsRun, len(r.failures), len(r.errors), len(r.skipped))
frappe.db.rollback()"
#   test_retention_gc 37 1 0 0   ← KIRMIZI
#   test_media_storage_settings 19 0 0 0
#   test_storage_adapters 137 0 0 0

docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -m unittest \
  tradehub_core.tests.test_storage_adapters_minio        # 91 OK (gerçek MinIO)
docker exec … -m unittest tradehub_core.tests.test_render_regression  # 32 OK (skipped=1)

# ── Envanter ──────────────────────────────────────────────────
ls -d tradehub_core/tests/acceptance          # yok
ls docs/plans/                                # rollback-doctypes.md yok
ls scripts/ | grep seed_synthetic             # yok
grep -rn "cdn_purge" --include='*.py' tradehub_core/   # 0 sonuç
grep -n "boto3" requirements.txt              # 0 sonuç
grep -n "media_engine" docs/sad/SAD-v1.0.md   # 66 69 102 122 167 209 (+811 kayıt)
```

Bu belgedeki her ✅/❌ bir komut çıktısına ya da bir `dosya:satır`'a dayanıyor.
Her ❓ ölçülmediğini söylüyor. **Süre iddiası yoktur** — makinede paralel ajanlar
koşuyor, saat ölçümü karşılaştırılabilir olmazdı.
