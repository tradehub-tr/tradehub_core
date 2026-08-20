# K-1 — 5 ölü alarm metriğini besle

**Tarih:** 2026-08-20 · **Ortam:** `istoc-dev-backend-1` (image-baked app, `docker cp` + konteynerde test) · **Site:** `istoc.localhost`

## Özet

`metrics.py`'da TANIMLI ama hiç yazılmayan 5 seri artık besleniyor. `docs/observability/media-alerts.yml`'deki bu 5 seriye bağlı 5 alarm ÖLÜYDÜ (seri boş → `expr` değerlendirilemez → hiç ateşlenmez); şimdi hepsi canlı seriye bağlı. İki yazım deseni:

- **Öksüz + PII (3 seri):** periyodik toplayıcı — `observability/collectors.py::run_scan` (scheduler işi). `delivery/rum.py::to_metrics` deseninde: saf sınıflandırıcı + saf yazıcılar (`registry` enjeksiyonlu) + `import frappe` GEÇ yapılan IO toplayıcılar.
- **İş sayaçları (2 seri):** çağrı yerinde `inc` — iş TERMİNAL olduğunda `media/jobs.py::record_terminal`, `media/runner.py` (optimize/restore batch) çağırır. Periyodik değil; bir işin "başarısız bittiği" ancak bittiğinde bilinir.

## 5 metrik — ÖNCE / SONRA (konteynerde ölçüldü)

Temiz süreçte `REGISTRY.render()` + gerçek `/metrics` HTTP ucu (bearer token, HTTP 200) ile doğrulandı.

| Seri | ÖNCE | SONRA (ölçülen gerçek değer) | Kaynak |
|---|---|---|---|
| `media_orphan_files` | `<yok>` (0 seri) | `46` | `core/usage.find_disk_orphans().orphans` (üretim kipi, sistem yolları muaf) |
| `media_pii_field_coverage{status="mapped"}` | `<yok>` | `13` | `EXCLUDED_DOCTYPES`'in Attach/Attach Image alanları ∩ `EXCLUDED_MEDIA_FIELDS` |
| `media_pii_field_coverage{status="unmapped"}` | `<yok>` | `0` | aynı — haritanın kaçırdığı Attach alanı (T-132); 0 = kapsam tam |
| `media_pii_unprotected_files` | `<yok>` | `0` | ters referans: `EXCLUDED_MEDIA_FIELDS` + `attached_to_doctype∈EXCLUDED` public `File` |
| `media_job_total{job,state}` | `<yok>` | `{state="completed"}=1`, `{state="error"}=1` | `jobs.record_terminal` (runner) |
| `media_job_attempts{job}` | `<yok>` | histogram: `_count=2`, `_sum=2`, kovalar le=1/2/3/+Inf | `jobs.record_terminal` |

ÖNCE çıktısı (5 satırın hepsi):
```
media_orphan_files            <YOK/eksik>
media_pii_field_coverage      <YOK/eksik>
media_pii_unprotected_files   <YOK/eksik>
media_job_total               <YOK/eksik>
media_job_attempts            <YOK/eksik>
```
SONRA — gerçek `/metrics` HTTP gövdesinden (çok süreçli shard birleşimi):
```
media_orphan_files 46
media_pii_field_coverage{status="mapped"} 13
media_pii_field_coverage{status="unmapped"} 0
media_pii_unprotected_files 0
media_job_total{job="optimize",state="completed"} 1
media_job_total{job="optimize",state="error"} 1
media_job_attempts_bucket{job="optimize",le="1"} 2 ... _sum 2  _count 2
```

> `run_scan` KENDİ shard'ını yazar (`exporter.write_shard`), böylece SCHEDULER sürecinde ölçülen değerler web sürecinin `/metrics` birleşimine ulaşır — aksi hâlde ayrı süreç sayıları görünmezdi.

## Alarm eşleşmesi (5 kural — birebir doğrulandı)

| Alarm (`media-alerts.yml`) | `expr` metrik adı | Yazdığım seri | Durum |
|---|---|---|---|
| `MediaOrphanFilesGrowing` | `media_orphan_files > 1200` | `media_orphan_files` | ✔ eşleşiyor |
| `MediaUnprotectedPiiFiles` | `media_pii_unprotected_files > 0` | `media_pii_unprotected_files` | ✔ |
| `MediaPiiFieldCoverageGap` | `media_pii_field_coverage{status="unmapped"} > 0` | `media_pii_field_coverage` + `status` etiketi | ✔ (etiket değeri de yazılıyor) |
| `MediaJobFailureRatio` | `media_job_total{state="error"}` | `media_job_total` + `state` etiketi | ✔ (**alarm düzeltildi**, aşağı bkz.) |
| `MediaJobRetryExhaustion` | `media_job_attempts_bucket` (le, job) | `media_job_attempts` histogram | ✔ |

### ⚠ Alarm düzeltmesi — `MediaJobFailureRatio` (ölü etiket)

Kuyruk grubu (`media-engine-queue`, elle bakımlı) `state="failed"` okuyordu ama `jobs.py` kanonik terminal durumları `completed`/`partial`/`error`'dır — **hiçbir yer `failed` yazmıyordu**, yani metrik dolsa bile alarm ölüydü. `expr`'i `state="error"`'a çektim (`partial` = iş yürüdü ama bazı dosyalar düştü, HATA DEĞİL → yalnız `error` sayılır). Description da güncellendi. Bu grup `alerts.py::to_prometheus_rules` tarafından ÜRETİLMEZ (header'da "elle eklendi" yazıyor), o yüzden `dogrula()` kapsamı dışında ve düzenlemem güvenli — `test_observability_alerts` hâlâ 20/20, `alerts.dogrula()` 16 alarm/0 unknown.

## Scheduler kaydı — SENİN EKLEMEN GEREKEN (hooks.py bana yasak)

`run_scan` bir zamanlayıcı işidir; `tradehub_core/hooks.py`'daki `scheduler_events`'e eklenmeli:

```python
scheduler_events = {
    "hourly": [
        # ... mevcut ...
        "tradehub_core.media.pipeline.observability.collectors.run_scan",
    ],
}
```

**Frekans önerisi: `hourly`.** Gerekçe: `MediaUnprotectedPiiFiles` KVKK kritiktir (`for: 0m`) ve `MediaPiiFieldCoverageGap` `for: 30m` — saatlik tazelik bunlara yeter. **Uyarı:** `run_scan` disk yürüyüşü yapar (`find_disk_orphans` bütün media kökünü `os.walk` eder). Bu dev'de 46 öksüz/ucuz; PROD medya ağacı çok büyükse saatlik disk yürüyüşü pahalı olabilir — o durumda öksüz taramasını `daily`'ye ayırmak için `run_scan`'i bölmek gerekir (bugün üçü tek işte). İlk hafta süreyi ölçüp karar verin.

> `run_scan` tek başına `bench execute tradehub_core.media.pipeline.observability.collectors.run_scan` ile de koşar (elle kanıtlandı).

## Vacuity (kırmızı kanıt)

`tests/test_alarm_collectors.py::Vacuity` — yazıcı ÇAĞRILMAZSA seri hiç yok (`seri_sayisi()==0`, `render()` içinde ad geçmez); yani `media_orphan_files > 1200` / `{status="unmapped"} > 0` / `> 0` boş seride değerlendirilemez, alarm sessizce hiç ateşlenmez. Yazıcı çağrılınca seri render edilir ve alarm değerlendirilebilir hâle gelir. `IsSayaci::test_running_yazilmaz` de terminal-olmayan durumun sayılmadığını (sayaç yalnız sonuç sayar) kanıtlar.

## Testler

`tradehub_core/tests/test_alarm_collectors.py` (YENİ) — 14 test, konteynerde **14/14 OK**:
- `SafKapsamSiniflandirma` (3) — `classify_field_coverage` mapped/unmapped/gap (frappe'siz).
- `SafYazicilar` (4) — üç gauge + sahte-registry enjeksiyonu.
- `Vacuity` (3) — yukarıdaki kırmızı kanıt.
- `IsSayaci` (3) — `jobs.record_terminal` error/completed/running.
- `AlarmAdiEslesme` (1) — 5 seri adının REGISTRY'de tanımlı olması.

`test_observability_instrument.py` güncellendi (aşağıdaki muhasebe değişikliği için): `needs_collector` sayısı 8→6; konteynerde 26/26 OK.

## Dokunulan dosyalar (sahiplik içinde)

- `media/pipeline/observability/collectors.py` — **YENİ** toplayıcı modülü.
- `media/jobs.py` — `record_terminal()` EKLENDİ (mevcut mantık bozulmadı).
- `media/runner.py` — 3 terminal noktada `jobs.record_terminal(...)` EK `inc` çağrısı (optimize completed/partial + error, restore completed/partial).
- `media/pipeline/observability/instrument.py` — muhasebe: `media_job_total`/`media_job_attempts` `TOPLAYICI_GEREKTIREN`'den `NOKTA_DISI_YAZILAN`'a taşındı (artık çağrı yerinde yazılıyor, periyodik toplayıcı değil). `metrik_kapsami().needs_collector` 8→6; `unaccounted` hâlâ `[]`.
- `tests/test_alarm_collectors.py` — **YENİ**. `tests/test_observability_instrument.py` — sayaç güncellendi (testin kendi docstring'i "kapandığında güncellenmeli" diyordu).
- `docs/observability/media-alerts.yml` — yalnız elle-bakımlı kuyruk grubunun `MediaJobFailureRatio` `expr`/description'ı (`failed`→`error`).

## Kalan iş (SENİN kapsamında — sahiplik dışı, dokunmadım)

1. **hooks.py** — yukarıdaki `scheduler_events` satırı.
2. **Retry'lı işler için tam JOB_ATTEMPTS kapsamı:** `media/runner.py` batch işleri tek seferliktir (attempts=1). Gerçek deneme dağılımı `media/transcode.py` ve `media/av.py`'de (`th_media_transcode_attempts` / `th_media_scan_attempts`). O iki dosya sahiplik DIŞIMDA; terminal/dead-letter noktalarında `jobs.record_terminal("transcode"|"scan", <state>, attempts=<gerçek>)` çağrısı eklenirse `job` kırılımlı retry histogramı ve `MediaJobRetryExhaustion` bu hatlar için de anlamlı olur. Bugün optimize/restore ile seri canlı ve alarm değerlendirilebilir.

## Süre / kapsam notu

Süre iddiası yok. Koşturulmayan hiçbir şeye "geçti" denmedi: tüm test sayıları ve `/metrics` gövdesi `istoc-dev-backend-1` konteynerinde bu raporun yazıldığı koşumdan.
