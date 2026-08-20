# 26 — T-053: Saklama (retention) ve çöp toplama işleri

**Görev:** T-053 (Faz 5 · Depolama) · **Tarih:** 2026-08-19 · **Dal:** `ahmet`
**Şartname:** https://karacaismail.github.io/imageoptimization/docs/42-faz5-depolama-s3-cdn.html
**Dokunulan kod:** `tradehub_core/media/pipeline/storage/retention.py` (EKLEME),
`tradehub_core/hooks.py` (yalnız EKLEME, 0 silme), `tradehub_core/tests/test_retention_gc.py` (yeni)
**Ölçüm ortamı:** `istoc-dev` compose, site `istoc.localhost`, Frappe v15, MariaDB 10.6

> **DOKUNULMADI:** `media/trash.py`, `media/usage.py`, `media/presets.py`,
> `media/file_isolation.py`, `api/`, DocType JSON'ları, `docs/standards/`,
> `docker/`, `kyc_verification` ile ilgili her şey. `usage.py` ve `presets.py`
> yalnız **okundu** ve **çağrıldı**.

---

## 0. Karar (önce sonuç)

> ### İşler yazıldı, `hooks.py`'ye günlük olarak kaydedildi ve **varsayılan kuru koşumda hiçbir şeye dokunmuyor.** Islak koşum iki bağımsız kapıya bağlı: `site_config` bayrağı **ve** politikanın `keep_forever=false` yapılması. Bugün ikisi de kapalı.

| Kanıt | Sonuç |
|---|---|
| Kuru koşum hiçbir şey silmiyor | `File` 5014 → **5014**, disk 1.153.218.661 → **1.153.218.661 bayt** (fark 0) |
| Kuru koşum boşuna değil | Agresif politikayla **4.429 aday, 1,44 GB** üretti — "hiç çalışmadı" ile karışmıyor |
| Legal hold koruyor | `legal_hold=1` → `blocked/legal_hold`; `legal_hold=0` → `delete` (**tek değişken bu**) |
| Eksik dosya dayanıklılığı | Diskte karşılığı olmayan **10** `File` kaydı → `missing_on_disk` ile atlandı, koşum tamamlandı |
| `Brand.logo` tuzağı | `usage.py` kararı **`history_only`** (yani silinebilir!) — GC koruma kümesinde, **silme adayı değil** |
| Vacuity | Legal hold kontrolü kaldırıldı → **2 test KIRMIZI**; geri kondu → **22 test YEŞİL** |

**Yeni bulgu (§6):** `regenerate_on_demand=True` bugün **tutulamayan bir söz**.
`Media Rendition.generation` alanında `lazy` seçeneği tanımlı ama onu yazan
kod yok; boru hattı bayrağı da kapalı. Türev silmeyi bu söze dayandıran bir
politika, geri gelmeyecek dosyaları siler. Kod artık bunu ölçüp silmeyi
bildirime düşürüyor.

---

## 1. Mevcut durumda ne vardı, ne yoktu

`retention.py` zaten vardı ve **yeniden yazılmadı**. İçindeki politika modeli
(`OriginalRetention`, `DerivativeRetention`, `RetentionPolicy`), şema okuyucu
(`schema_defaults`) ve `RetentionSweeper` olduğu gibi kullanıldı; `tests/
test_retention.py` içindeki 47 test bu görevden sonra da yeşil.

Eksik olan üç şey vardı:

| Eksik | Kanıt |
|---|---|
| **Zamanlanmış iş yok** | `hooks.py` `scheduler_events` içinde `retention` geçen tek satır yoktu |
| **Legal hold kapısı yanlış alana bakıyordu** | `FrappeLegalHold` `File.th_legal_hold` okur — o kolon **YOK** (ölçüldü) |
| **Frappe envanterine bakan kod yok** | `RetentionSweeper` `StorageAdapter` gezer; üretimdeki `File` adlarının çoğu içerik-adresli değil |

### 1.1 Legal hold alanı ölçümü — belge ile gerçek ayrışmış

`docs/standards/retention.md` §5.2 "legal_hold diye bir şey yok" diyor ve
§8'de `File.th_legal_hold` custom alanı öneriyor. Ölçüm başka söylüyor:

```
File th_ kolonları : th_optimized_at, th_original_size, th_trashed_at,
                     th_media_state, th_media_title, ... (19 adet)
File.th_legal_hold : YOK
Media Asset kolonları: ..., source_file, legal_hold, content_sha256, ...
Media Asset.legal_hold: VAR   (Check, permlevel 1 — satıcı yazamaz)
```

Kapı bu yüzden `File`'a değil **`Media Asset.legal_hold`**'a bakacak şekilde
yazıldı (`MediaAssetLegalHold`). Eski `FrappeLegalHold` **silinmedi** —
sözleşmenin bir parçası ve testte "hâlâ uygulanamaz" olduğu doğrulanıyor;
o kolon bir gün eklenirse test kırmızı olup dikkat çeker.

---

## 2. Yazılan iş: iki bağımsız süpürücü + bir bakım raporu

```
run_scheduled_gc()                      hooks.py → scheduler_events["daily"]
  └─ run_maintenance(dry_run=True)
       ├─ sweep_originals()             File envanteri  → OriginalRetention
       └─ sweep_derivatives()           Media Rendition → DerivativeRetention
```

**İki politika birbirini etkilemez** (`retention.md` §6). Orijinali silmeye
açmak türev kararını değiştirmiyor; test bunu sabitliyor
(`test_politika_bagimsiz_kaliyor`).

### 2.1 Karar sırası — legal hold her şeyden önce

`_original_candidate` / `_derivative_candidate` **saf** fonksiyonlar; hiçbir
şeye dokunmadan `GcCandidate` üretirler. Sıra:

1. **`legal_hold`** → `blocked`. Yaş bile hesaplanmaz.
2. `usage.py` kör noktası (§5) → `keep / usage_blind_spot` *(yalnız türev)*
3. Adres çözülmüyor → `keep / not_a_file_url`
4. Diskte yok → `keep / missing_on_disk`
5. Yaş + politika → `keep / delete / demote / notify_only`
6. Soğuk katman yok → `demote` **düşer** `notify_only / no_cold_tier`
7. Yeniden üretim yolu yok → `delete` **düşer** `notify_only / regeneration_path_unavailable`

Uygulama (`_record` → `_apply_*`) ayrı bir adım ve **kuru koşumda hiç
çağrılmaz**. Kuru koşumun anlamlı olabilmesinin tek yolu bu ayrım.

### 2.2 Kapsam muhasebesi — hangi dosyaya hiç bakılmıyor

```
File toplam            : 5014
  klasör               :    6
  file_url boş         :    0
  hassas doctype eki   :  508   ← EXCLUDED_DOCTYPES, GC hiç bakmıyor
GC kapsamı             : 4500
kontrol 6 + 0 + 508 + 4500 = 5014 == 5014
```

`EXCLUDED_DOCTYPES` (`media/presets.py`, yalnız okundu): KYB/KYC Verification,
Seller Certification/Verification/Application, Order, Payment Transaction,
Data Export Request. **508 belge GC'nin sorgusuna hiç girmiyor** — silinemez
olmalarının yanında, "aday" listesinde bile görünmüyorlar.

---

## 3. KANIT 1 — Kuru koşum gerçekten hiçbir şey silmiyor

Agresif politika (`keep_forever=false`, `local_days=1`, `then=delete`,
`legal_hold` açık) ile canlı envanter üzerinde:

```
ÖNCE : File=5014  disk=1153218661 bayt
SONRA: File=5014  disk=1153218661 bayt
FARK : File=0     disk=0 bayt          (koşum 0,98 sn / 4500 dosya)

toplamlar:
  scanned          4500
  kept               71
  candidates       4429
  deleted             0
  bytes_candidate   1.447.444.781
  bytes_freed         0
  skipped_by_reason  {missing_on_disk: 10, too_young: 61}
```

**Karşı yön (vacuity'ye karşı):** aynı koşum **4.429 aday ve 1,44 GB**
raporladı. Yani "hiçbir şey silinmedi" cümlesi "kod hiç çalışmadı"dan
ayrışıyor — kod tam olarak neyin silineceğini biliyordu ve yapmadı.

### 3.1 Üretim varsayılanı: tek aday bile yok

```
original_retention: {"keep_forever": true, "local_days": null, "then": "delete"}
toplamlar: scanned=4500 kept=4500 candidates=0 deleted=0
skipped_by_reason: {keep_forever: 4490, missing_on_disk: 10}
```

### 3.2 Zamanlanmış işin kendisi

```
site_config bayrağı media_retention_gc_enforce = None
ÖNCE : (5014, 1153218686)
SONRA: (5014, 1153218686)     FARK: (0, 0)
dry_run: True   süre_ms: 726
Error Log kaydı: ga0jq3ic4i (method=media.retention_gc)
```

Islak koşum **iki** kapıya bağlı ve ikisi de kapalı:

1. `site_config.media_retention_gc_enforce` **yok** → `dry_run=True`
2. Politika `keep_forever=true` → bayrak açılsa bile aday sıfır

---

## 4. KANIT 2 — Legal hold, iki yön

Tek değişken `Media Asset.legal_hold`; dosya, politika, iş aynı.

```
dosya : /files/0c/0ccf8648bd631248d53b07df4c0f94c2.txt   (mtime 30 gün geri)
varlık: e542c4reh8  (Media Asset, source_file → yukarıdaki File)

A) legal_hold = 1
   karar : action=blocked  reason=legal_hold  held=True
   bölüm : taranan=4501  bloke=1  aday=4429
   dosya diskte mi: True

B) legal_hold = 0        ← TEK değişiklik
   karar : action=delete  reason=delete  age_days=30.0  size_bytes=23  held=False
   bölüm : taranan=4501  bloke=0  aday=4430
   dosya diskte mi: True   (kuru koşum → yine silmedi)
```

`bloke 1 → 0`, `aday 4429 → 4430`. Koruma gerçekten legal hold'dan geliyor.

### 4.1 Uygulanamaz kapı = yıkıcı işlem yok

Kapı ölçülemiyorsa (`enforceable=False`) süpürücü aday üretmeye devam eder
ama **hiçbirini uygulamaz**; sayaç `blocked`, sebep
`legal_hold_unenforceable`. "Alan yok → kimse tutulu değil" varsaymak legal
hold'un tek işini sessizce iptal ederdi
(`test_kapi_uygulanamazsa_yikici_islem_durur`, `dry_run=False` ile koşuyor,
`deleted=0`).

### 4.2 Tutulan varlık türevlerini de kapsıyor

`MediaAssetLegalHold.held_urls()` iki yoldan URL toplar: `Media Asset.
source_file → File.file_url` (orijinal) ve `Media Rendition.asset →
file_url` (türev). Tek toplu yükleme, döngü içinde sorgu yok.

---

## 5. KANIT 3–4 — Eksik dosya ve `usage.py` kör noktaları

### 5.1 Diskte olmayan `File` kayıtları

Görev tanımı 3 kayıt diyordu; ölçüm **14** buldu (GC kapsamında **10**,
kalan 4 hassas doctype eki olduğu için kapsama girmiyor). Hiçbiri koşumu
düşürmedi:

```
missing_on_disk atlanan: 10
taranan toplam: 4500 → çökme yok, koşum tamamlandı
```

Bu kayıtlar "yaşı sonsuz" sayılıp silinseydi, zaten olmayan dosyanın `File`
kaydı da giderdi — geri dönüşü olmayan referans kaybı.

### 5.2 `usage.py` kör noktaları — ölçülmüş 25 alan

`information_schema` taraması (2026-08-19): `/files/` geçen **42** (tablo,
kolon) çifti var. Bunların **25'i** `usage.py`'nin üç kaynak listesinin
hiçbirinde yok. En kritikleri:

| Alan | Satır | Not |
|---|---:|---|
| `tabKYB Verification.*` (6 alan) | 23 | KVKK belgesi |
| `tabBuyer Favorite Item.snapshot_image` | 22 | |
| `tabKYC Verification.identity_document` | 11 | KVKK belgesi |
| `tabPayment Transaction.receipt_url` | 3 | |
| `tabAdmin Seller Profile.banner_image` | 2 | |
| **`tabBrand.logo`** | **1** | **T-029 tuzağı** |
| `tabBrand.hero_banner` | 1 | |
| `tabProduct Category.image` | 1 | |
| `tabSeller Gallery Image.poster_image` / `.video_url` | 1+1 | |
| `tabStatic Page SEO.og_image` | 1 | |

### 5.3 `Brand.logo` tuzağının ölçümü

```
Brand.logo LIVE_SOURCES'ta mı: False
Ali Giyim: /private/files/stock-vector-initial-letter-gaor-ag-logo-vector-design.jpeg
   usage.py kararı = 'history_only'   |   GC koruma kümesinde = True
```

`history_only` masum bir etiket değil: `retention.UNUSED_VERDICTS` bu etiketi
**silinebilir** sayar (`trash.TRASHABLE_VERDICTS` ile aynı küme). Yani
`usage.py`'ye körü körüne güvenen bir GC bu marka logosunu **silme adayı
gösterirdi**.

**Yapılan:** `usage.py` DÜZELTİLMEDİ (kapsam dışı). `retention.py` içinde
ölçümle yazılmış `BLIND_SPOT_SOURCES` (17 alan) + `PROTECTED_SOURCES`
(7 KVKK alanı) listelerinden bir **koruma kümesi** hesaplanıyor
(bu sitede 71 URL) ve o kümedeki hiçbir adres, kullanım kararı ne olursa
olsun, türev silme adayı olamıyor (`keep / usage_blind_spot`).

Testte iki yön de sabitli: koruma kümesindeyken `keep`, kümeden çıkarıldığında
aynı satır `delete`.

> **`usage.py`'ye devredilen iş:** kalıcı çözüm `LIVE_SOURCES`'a bu alanların
> eklenmesi. Koruma kümesi bir emniyet ağı; `usage.py` düzeldiğinde de zararsız
> kalır (aynı adresi iki kez korumak sorun değil).

---

## 6. YENİ BULGU — "istendiğinde yeniden üret" bugün tutulamayan bir söz

`derivative_retention.regenerate_on_demand` varsayılanı `true`. Şema bunu
"silinen türev istendiğinde yeniden üretilir" diye okuyor ve `action=delete`
kararını buna dayandırıyor. Üretimde karşılığı yok:

- `Media Rendition.generation` alanında `lazy` seçeneği **tanımlı**, ama onu
  yazan kod yok — repo genelinde tek `"lazy"` kullanımı `<img loading>`
  özniteliği.
- Boru hattı bayrağı kapalı (`pipeline_flags.is_enabled()` → `False`), yani
  hiçbir türev üretilmiyor.
- Üretilebilse bile bedeli var: **T-028 ölçümü görsel başına 10,45 sn**
  (SSIM %52, encode %37). Silinen her türev, ilk isteyen kullanıcıya
  10 saniyelik bekleme olarak döner.

Mevcut `DerivativeRetention.warnings()` yalnız `regenerate_on_demand=False`
yazılmış olmasını yakalıyordu — asıl tehlike tersiydi: bayrak `true` ama yol
yok. `regeneration_available()` bunu ölçüyor ve yol yoksa `delete` kararı
`notify_only / regeneration_path_unavailable`'a düşüyor. Testte iki yön de
sabit.

**Sonuç:** türev silme, `unused_after_days` dolsa ve `action=delete` yazılsa
bile bugün gerçekleşmez. Bu bilinçli: silme bedeli 10,45 sn/görsel, geri
dönüşü ise bugün **yok**.

---

## 7. Bakım raporu — ne içeriyor

`run_maintenance()` sözlüğü (`Error Log`'a `media.retention_gc` başlığıyla
yazılıyor; `media/audit.py` eylem sözlüğü kapalı bir küme ve ona yeni eylem
eklemek bu görevin kapsamı dışı):

```
generated_at, dry_run, duration_ms
policy            → yürürlükteki politikanın tamamı
policy_warnings   → şema x-requires-review uyarıları
legal_hold        → {source, enforceable, held_assets, held_urls}
sections[]        → politika başına:
      scanned kept candidates deleted demoted notified blocked failed
      bytes_candidate bytes_freed
      skipped_by_reason  ← {sebep: sayı}   ← görev şartı 5
      samples[:50] + samples_truncated
tiers             → {before, after, transitions, demoted}   ← katman geçişleri
totals            → iki bölümün toplamı + birleşik skipped_by_reason
```

**Atlanma sebepleri sözlüğü** (bugünkü koşumdan): `keep_forever: 4490`,
`missing_on_disk: 10`. Diğer olası sebepler: `legal_hold`, `too_young`,
`in_use`, `usage_unknown`, `usage_blind_spot`, `not_a_file_url`,
`always_keep_profile`, `no_cold_tier`, `regeneration_path_unavailable`,
`legal_hold_unenforceable`, `regenerate_on_demand_false`.

**Katman geçişleri:** `Media Rendition.storage_backend` dağılımının koşum
öncesi/sonrası anlık görüntüsü ve net farkı. Bugün tablo boş → `{}`.
Kuru koşumda geçiş **olmamalı** ve test bunu doğruluyor.

---

## 8. Türev işi boş kümede

`Media Asset`, `Media Rendition` ve `Media Processing Job` tabloları **boş**
(bayraklar kapalı). Türev süpürücüsü 0 satırla koşuyor ve bu doğru davranış:

```
derivative: taranan=0 korunan=0 aday=0 silinen=0 bildirilen=0 bloke=0
            atlanma sebepleri: {}
```

Boş kümede sahte bir "0 dosya temizlendi" satırı **yazılmıyor**; sebep
sözlüğü de boş kalıyor. Karar mantığının kendisi (`_derivative_candidate`)
sentetik satırlarla ayrıca test edildi — bayrak açılıp tablo dolduğunda
davranış bilinen.

---

## 9. `hooks.py` kaydı

`scheduler_events["daily"]` bloğuna **tek satır eklendi, 0 satır silindi**
(`git diff` doğrulaması: `-` ile başlayan satır sayısı **0**):

```python
"tradehub_core.media.backup.run_scheduled",
# T-053 — Saklama/çöp toplama bakım işi. VARSAYILAN KURU KOŞUM: ...
"tradehub_core.media.pipeline.storage.retention.run_scheduled_gc",
```

Sıra bilinçli: yedek (`backup.run_scheduled`) bu işten **önce** koşar, böylece
aday gösterilen hiçbir dosya yedeksiz kalmaz. Konteyner yeniden başlatıldıktan
sonra doğrulandı:

```
KAYITLI MI: True
daily medya işleri: [archive.purge_expired, trash.purge_expired,
                     backup.run_scheduled, retention.run_scheduled_gc]
```

Eşzamanlılık: iş Redis kilidi (`media_retention_gc_lock`, 3600 sn) kullanıyor
— `tasks.py`'deki `calculate_customer_grades` deseninin aynısı.

---

## 10. KANIT 5 — Vacuity

`_original_candidate` içindeki legal hold dalı **geçici olarak kaldırıldı**
ve testler koşuldu:

```
FAIL: test_tutulan_dosya_bloke_ediliyor
      AssertionError: 'delete' != 'blocked'
FAIL: test_hold_kalkinca_ayni_is_ayni_dosyayi_aday_goruyor
      AssertionError: 'delete' != 'blocked'
Ran 19 tests   FAILED (failures=2)
```

Dal geri kondu:

```
Ran 22 tests in 5.944s   OK
```

Testler legal hold'u gerçekten ölçüyor; koruma kaldırıldığında kırmızı
oluyorlar.

---

## 11. Koşum kayıtları

| Koşum | Sonuç |
|---|---|
| `run-tests --module tradehub_core.tests.test_retention_gc` | **22 test, OK** |
| `run-tests --module tradehub_core.tests.test_retention` (mevcut) | **47 test, OK** (1 skip) |
| `python3 -m unittest tradehub_core.tests.test_retention` (frappe'siz) | **47 test, OK** |
| `ruff check` yeni test dosyası | **0 bulgu** |
| `ruff check retention.py` | UP006/UP045/UP035/UP037 — **dosyanın mevcut stiliyle aynı aile**, yeni kural ihlali yok |
| `hooks.py` diff | **+61 / -0** |

Komutlar:

```bash
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_retention_gc
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_retention
```

---

## 12. Açılabilme koşulu — ıslak koşuma geçmeden önce

1. **`usage.py` kör noktaları kapatılmalı.** 25 alan ölçüldü; en azından
   `Brand.logo`, `Brand.hero_banner`, `Product Category.image`,
   `Admin Seller Profile.banner_image`, `Seller Gallery Image.poster_image`
   `LIVE_SOURCES`'a girmeli. Koruma kümesi emniyet ağı, çözüm değil.
2. **Yeniden üretim yolu yazılmalı** — `Media Rendition.generation="lazy"`
   yazan ve isteğe göre üreten kod yok. Yoksa türev silme kalıcı kayıptır.
3. **Soğuk katman bağlanmalı** — `s3_cold` hedefi bugün `notify_only`'a
   düşüyor (`no_cold_tier`). T-051 raporundaki B-01/B-02/B-04 kusurları
   düzeltilmeden `tiered` açılamaz.
4. **`legal_hold` yazma yolu** — alan `permlevel 1`; bugün kimse `1`
   yapamıyor (form yolu yok, sadece admin/DB). Legal hold gerçekten
   kullanılacaksa bir yönetim ucu gerekir. Bu görevin kapsamı dışı.
5. **`site_config.media_retention_gc_enforce`** ancak 1–4 bittikten sonra
   `1` yapılmalı ve önce `limit` ile küçük bir kümede denenmeli.

---

## 13. Bu görevde ölçülemeyenler

- **Islak koşum hiç denenmedi.** `_apply_original` (`trash.move_to_trash`) ve
  `_apply_derivative` (`trash.move_to_trash` + `delete_doc`) yolları canlı
  veri üzerinde çalıştırılmadı — görev "dry-run dışına çıkma" diyordu.
  `_apply_*` fonksiyonlarının kendisi test edilmedi; test edilen şey
  **çağrılmadıklarıdır**.
- **Türev süpürücüsü gerçek veriyle koşmadı** — `Media Rendition` boş.
  Karar mantığı sentetik satırlarla ölçüldü.
- **Katman geçişi hiç gerçekleşmedi** — soğuk katman yok, `demote` kararı
  hep `notify_only`'a düşüyor.
- **`missing_on_disk` sayısı** görev tanımındaki 3 değil 14 (kapsamda 10)
  çıktı; ikisinin neden ayrıştığı araştırılmadı (muhtemelen kapsam tanımı:
  public/private ve hassas doctype ekleri).
