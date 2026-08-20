# 42 — T-133 gözlemlenebilirlik · T-134 KVKK · T-123 RUM telemetrisi

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (`ahmet`) · **Ortam:**
`istoc-dev-backend-1`, site `istoc.localhost`, bench Python **3.11.6**;
host macOS Python **3.9.6**
**Girdi:** `docs/reports/28-faz13-pentest.md`, `36-dogrulama-faz12-14.md`

> **Bu belge üretim kodunu DEĞİŞTİRİR.** Değişen dosyalar §2'de. Yapılamayanı
> yapılmış gibi göstermez: Prometheus ve Grafana bu projede **kurulu değil**,
> `docker/` bu görevin kapsamı dışı ve **hiçbir pano ya da alarm bir yere
> yüklenmedi**. Neyin kurulamadığı §6'da, gereken adımlarla birlikte yazılı.

---

## 0. Yöntem etiketleri

| Etiket | Anlamı |
|---|---|
| **[Ö]** | Canlı sistemde ölçüldü (konteyner + site), çıktı aynen aktarıldı |
| **[K]** | Kod okundu (`dosya:satır`) |
| **[T]** | Otomatik test koşuldu — çıktı gömülü |
| **[V]** | Vacuity — düzeltme geri alındı, test KIRMIZI oldu, geri kondu |
| **[R]** | Başka bir raporda ölçülmüş, alıntı |
| **[?]** | **ÖLÇÜLEMEDİ** → §10 |

---

## 1. Yönetici özeti

### 1.1 Girdi durumu — 36 numaralı rapor ne demişti

| Görev | Rapor 36'nın kararı | Gerekçesi |
|---|---|---|
| T-133 | **KISMİ** | 5 kabul kriterinin 3'ü karşılanmıyor: pano yok, alarm yok, runbook dosyası yok |
| T-134 | **KISMİ** | `Media Audit Log` DocType yok, KVKK belgesi yok |
| T-123 | **KISMİ** | RUM veri sözleşmesi var, **saha verisi toplanmıyor** |

### 1.2 Bugün ne değişti

| Konu | Önce | Sonra | Kanıt |
|---|---|---|---|
| Metrik **tanımı** | 16 metrik | **24 metrik** | [Ö] |
| Metriği **yazan kod** | **0 çağrı yeri** (tüm depoda `grep`: yalnız `metrics.py`'nin kendisi) | **10 ölçüm noktası**, bench'te **10/10 bağlanıyor** | [Ö] §5.1 |
| `/metrics` gövdesi | yok — kayıt defteri süreç içi, 4 süreç ailesi ayrı sayıyor | çok süreçli toplayıcı: parça yaz → birleştir → tek metin | [T] §4 |
| Alarm kuralı | **0** | **16 kural**, hepsi tanımlı metriğe bağlı (makine doğrulamalı) | [T] §5.3 |
| Pano | **0** | 12 panelli Grafana tanımı (JSON üreticisi) | [T] |
| Runbook dosyası | **0/0** | **0/16** — kural var, dosya yok (§6.3) | [Ö] |
| Medya denetiminde görünen olay | 2.041 | **2.151** (+110 ayar değişikliği kaydı) | [Ö] §5.4 |
| KVKK belgesi | yok | `docs/security/kvkk.md` (486 satır, canlı ölçümlü) | — |
| RUM → metrik köprüsü | yok | `rum.to_metrics()` + 6 RUM metriği + 4 regresyon alarmı | [T] |
| Test | 98 (obs 72 + rum 26) | **183** (+85 yeni) | [T] §4 |

### 1.3 Değişmeyen — ve bu görevde değiştirilemeyecek olan

**Hiçbir metrik bugün toplanmıyor.** Sebep tek ve nettir: `install()`
fonksiyonunu çağıran satır `hooks.py`'ye yazılır, o dosya bu görevin kapsamı
dışında. `/metrics` HTTP ucu `api/` altında olurdu — o da kapsam dışı.
Prometheus ve Grafana `docker/` altında kurulur — o da kapsam dışı.

Yani T-133'ün 5 kriterinden **2'si tam**, **3'ü hâlâ eksik**; ama eksik
olanların **koda düşen yarısı bitti** ve kalan adım her biri için **tek
satır/tek dosya** olarak §6'da yazılı.

---

## 2. Değişen ve eklenen dosyalar

| Dosya | Satır | Durum | Ne |
|---|---:|---|---|
| `media/pipeline/observability/metrics.py` | 747 | değişti (**+86 / −0**) | 8 yeni metrik: denetim olayı, video süresi, enstrümantasyon hatası, 5 RUM metriği |
| `media/pipeline/observability/instrument.py` | 633 | **yeni** | 10 ölçüm noktası, sarmalayıcı, kurulum raporu, metrik kapsam muhasebesi |
| `media/pipeline/observability/exporter.py` | 408 | **yeni** | Çok süreçli parça yaz/birleştir/render, `/metrics` gövdesi, ölü parça temizliği |
| `media/pipeline/observability/alerts.py` | 539 | **yeni** | 16 alarm kuralı + Prometheus YAML üreticisi + 12 panelli Grafana panosu + doğrulama |
| `media/pipeline/observability/__init__.py` | 44 | değişti (**+27 / −2**) | `IMPLEMENTED` güncellendi + **`NOT_WIRED`** sözlüğü (var ≠ devrede) |
| `media/pipeline/delivery/rum.py` | 757 | değişti (**+235 / −21**; 21 silmenin tamamı `raise RumError(...)` satırlarının kod eklenmiş hâliyle yer değiştirmesi) | Kararlı ret kodları, `to_metrics()` köprüsü, `record_rejection()`, `Media RUM Sample` şema tasarımı |
| `media/audit.py` | 849 | değişti (**+18 / −0**) | `ACTION_SETTINGS_CHANGED` sabiti + `MEDIA_ACTIONS`'a eklendi (§5.4) |
| `tests/test_observability_instrument.py` | 360 | **yeni** | 26 test |
| `tests/test_observability_exporter.py` | 242 | **yeni** | 19 test |
| `tests/test_observability_alerts.py` | 154 | **yeni** | 20 test |
| `tests/test_rum_metrics.py` | 221 | **yeni** | 20 test |
| `docs/security/kvkk.md` | 486 | **yeni** | KVKK uyum kaydı (T-134) |

**Dokunulmayanlar (yasak listesi):** `hooks.py`, `permissions.py`,
`patches.txt`, `patches/**`, `docker/`, `api/**`, `admin-panel`,
`docs/security/faz13-tehdit-modeli.md`. `bench migrate` **koşulmadı**.
`Media Audit Log` DocType'ı **kurulmadı** (§7).

**Konteyner:** kaynak dosyalar `docker cp` ile konteynerdeki uygulama dizinine
kopyalandı (imajda bind-mount yok). Kopyaların sha256'sı host'takilerle
**birebir eşit** [Ö]. Ölçüm betikleri `/tmp` altındaydı, **silindi**; hiçbiri
veri yazmadı (yalnız `SELECT`/`count`). **Bayrak açılmadı, test kaydı
üretilmedi.**

---

## 3. T-133 — kabul kriterleri, tek tek

| # | Kriter | Durum | Ölçüm |
|---|---|:--:|---|
| 1 | Prometheus metrikleri | ✅ **TAM** | 24 metrik, text format 0.0.4, çok süreçli toplama; `prometheus_client` **kurulu değil** [Ö] ve gerekmiyor — biçim elle üretiliyor, çıktı testle doğrulanıyor |
| 2 | JSON log + `correlation_id` | ✅ **TAM** (önceden) | `logging.py` + 72 test; bu görevde ölçüm noktaları hata yolunda yapılandırılmış olay yazacak şekilde bağlandı |
| 3 | **Panolar** | 🟡 **YARIM** | 12 panelli tanım ÜRETİLİYOR; **Grafana kurulu değil, pano içe aktarılmadı** |
| 4 | **Alarmlar** | 🟡 **YARIM** | 16 kural üretiliyor, hepsi tanımlı metriğe bağlı; **Prometheus kurulu değil, kural yüklenmedi**, `promtool` ile doğrulanmadı [?] |
| 5 | Her alarm için **runbook bağlantısı** | 🟡 **YARIM** | Her kuralda `runbook_url` var; **16/16 dosya eksik** — `docs/ops/runbooks/` dizini yok [Ö] |

**Ve rapor 36'nın görmediği altıncı gerçek:** kriter 1 "metrik var" diyordu ama
metrikleri **yazan hiçbir satır yoktu**. Bugün ölçüldü ve kapatıldı — §5.1.

---

## 4. Test koşumları

### 4.1 Sonuçlar [T]

```
HOST      (macOS, Python 3.9.6)          Ran 183 tests   OK
KONTEYNER (bench env, Python 3.11.6)     Ran 183 tests   OK
```

Kırılım:

| Modül | Test | Not |
|---|---:|---|
| `tests.test_observability` | 72 | mevcut — dokunulmadı, hâlâ yeşil |
| `tests.test_delivery_rum` | 26 | mevcut — `RumError` imzası genişledi, hâlâ yeşil |
| `tests.test_observability_instrument` | **26** | yeni |
| `tests.test_observability_exporter` | **19** | yeni |
| `tests.test_observability_alerts` | **20** | yeni |
| `tests.test_rum_metrics` | **20** | yeni |
| **Toplam** | **183** | |

**Ortama bağlı iki gerçek, testte de böyle yazıldı:**
- `ProbeOlcumu` sınıfı Pillow ister. Host'ta ve bench env'inde **koşuyor**;
  konteynerin *sistem* python'unda Pillow yok ve orada `skip` ile geçilir —
  sessiz atlama değil, unittest çıktısında görünür.
- Bağlı ölçüm noktası sayısı ortama göre değişir: host'ta 8/10 (frappe yok),
  bench'te **10/10**. Test bu sayıyı `find_spec("frappe")` ile hesaplar; sabit
  8 yazan bir test gerçek ortamda kırmızı olurdu.

**Koşulamayan:** `ruff` ne host'ta ne konteynerde kurulu — **lint
KOŞULMADI** [?]. `python -m py_compile` bütün dosyalarda temiz; 110 karakteri
aşan satır yok (`metrics.py`'de 2 satır var, **ikisi de bu görevden önce**).

### 4.2 Vacuity — 8 deney, hepsi KIRMIZI [V]

Her deneyde düzeltme geçici geri alındı, test koşuldu, geri kondu:

| # | Geri alınan | Sonuç (geri alındı → geri kondu) |
|---|---|---|
| V1 | Sarmalayıcı kayıt yazmasın | `FAILED (failures=9)` → `OK` |
| V2 | Video hata yolunda ilk argümanı (dosya yolu) etiket yap | `FAILED (failures=1)` → `OK` |
| V3 | Gösterge birleştirme varsayılanını `sum` yap | `FAILED (failures=1)` → `OK` |
| V4 | Histogram kova uzatmasını kaldır (kesme) | `FAILED (errors=1)` → `OK` |
| V5 | Bir alarmı var olmayan metriğe bağla | `FAILED (failures=3)` → `OK` |
| V6 | YAML tırnak kaçırmasını kaldır | `FAILED (failures=2)` → `OK` |
| V7 | CLS'i milisaniye metriğine yaz (birim ayrımını kaldır) | `FAILED (failures=1)` → `OK` |
| V8 | Ret kodunu sabit listeden değil serbest metinden üret | `FAILED (failures=3)` → `OK` |

V2 özellikle önemli: **PII sızıntısını** düşüren test. Geri alındığında
`/private/files/kimlik_taramasi.mp4` metrik etiketine yazıldı ve test kırmızı
oldu.

---

## 5. Ölçümler

### 5.1 Ölçüm noktaları — "metrik var" ile "metrik doluyor" farkı

**Önce [Ö].** Bütün depoda `grep -rn` ile arandı:

```
UPLOAD_TOTAL | JOB_TOTAL | SCAN_TOTAL | IMAGE_PROCESS_DURATION | …
    → yalnız  media/pipeline/observability/metrics.py

log_event | correlation_scope
    → yalnız  media/pipeline/observability/logging.py  ve  tests/test_observability.py
```

Yani `/metrics` o gün servis edilse **bütün seriler boş** dönerdi.

**Sonra [Ö].** `install()` gerçek bench ortamında koşturuldu:

```json
{"bound": ["policy.evaluate", "image.probe", "image.normalize", "image.lqip",
           "svg.sanitize", "isolation.run_callable", "isolation.run_command",
           "video.transcode", "av.scan_path", "audit.log_media_event"],
 "skipped": [], "total": 10, "coverage": 1.0}
```

**10/10 nokta bağlandı, 0 atlandı.** (Host'ta 8/10 — `media/av.py` ve
`media/audit.py` `import frappe` yapar.)

**Neden çağrı yeri değil sarmalayıcı:** ölçülen modüller (`image/`, `video/`,
`security/`, `policy/`) bu görevin dosya kapsamı dışında; 14 ajan paralel
çalışıyor ve o dosyalara dokunmak başka bir ajanın düzeltmesini geri alabilir.
Aynı deseni OpenTelemetry'nin otomatik enstrümantasyonu kullanır. Bedeli
`instrument.py` modül başlığında açıkça yazılı.

### 5.2 Metrik kapsam muhasebesi [Ö]

```json
{"defined": 24,
 "written_by_points": 10,
 "written_elsewhere": ["media_instrumentation_errors_total", "media_rum_cls_p75",
   "media_rum_estimated_population", "media_rum_p75_milliseconds",
   "media_rum_rejected_total", "media_rum_samples_total"],
 "needs_collector": ["media_bytes_saved_total", "media_job_attempts", "media_job_total",
   "media_orphan_files", "media_pii_field_coverage", "media_pii_unprotected_files",
   "media_storage_bytes", "media_storage_objects"],
 "unaccounted": []}
```

**24 metriğin 16'sının yazanı var, 8'i bir TOPLAYICI işi bekliyor.** Sahipsiz
metrik **0**. Bu ayrım önemlidir: tanımlı ama hiç yazılmayan bir seri, panelde
"sorun yok" gibi görünür — sekiz tanesi bugün tam olarak öyle.

Bekleyen 8'in ne olduğu:

| Metrik | Kim yazmalı |
|---|---|
| `media_storage_bytes`, `media_storage_objects` | envanter işi (`media/inventory.py`) |
| `media_orphan_files` | aynı iş — canlı ölçümde **1.166** yetim dosya bulunmuştu [R] |
| `media_pii_field_coverage`, `media_pii_unprotected_files` | PII harita denetimi — **KVKK alarmının kaynağı**, bkz. `kvkk.md` §3.2 |
| `media_bytes_saved_total` | `media/runner.py` optimizasyon özeti |
| `media_job_total`, `media_job_attempts` | kuyruk işi tamamlanma kancası |

### 5.3 Alarm doğrulaması [T]

```
alerts: 16 · unknown_metrics: [] · duplicate_names: []
metrics_with_alert: 14 / metrics_without_alert: 10
runbooks: 16 yol · runbook_gaps: 16 (docs/ops/runbooks/ dizini YOK) [Ö]
```

`dogrula()` fonksiyonu **sessiz kopmayı** düşürür: bir metrik adı değişip kural
güncellenmezse Prometheus hata vermez, kural hiç ateşlenmez ve panel boş kalır.
V5 vacuity deneyi bunu kanıtladı.

Eşiklerin kaynağı kuralın içinde yazılı. Üçü açıkça **DIŞ STANDART** olarak
işaretli (CWV LCP/CLS/INP — bu projede ölçülmedi); dördü ölçülmüş sayıdan
türedi (yetim dosya 1.166, korumasız PII dosyası 3→0, işleme süresi 1,05 s,
izolasyon `SEBEP_OK`); geri kalanı **operasyonel varsayım** ve öyle
etiketlendi — "ilk hafta sonrası ayarlanmalı".

### 5.4 Denetimde görünmeyen 110 kayıt — ölçüldü ve kapatıldı [Ö]

`media_storage_settings.py:116` bir sabiti kendi dosyasında tanımlamış, ama
`media/audit.py::MEDIA_ACTIONS`'a **ekleyememişti** (dosya kapsamı dışıydı) ve
sonucu kendi yorumuna yazmıştı: kayıt ADL'ye yazılıyor, panel `MEDIA_ACTIONS`
ile süzdüğü için görünmüyor. Bu görevde `media/audit.py` kapsam **içinde**.

Aynı çağrı (`audit.facets()`), düzeltmeden önce ve sonra:

```
ONCE   tanimli_action=19   panelde_gorunen=2041   settings_changed=0
SONRA  tanimli_action=20   panelde_gorunen=2151   settings_changed=110
```

Sabit `_HIGH_SEVERITY_ACTIONS`'a **eklenmedi**: aynı eylem adını gerçek ayar
değişikliği ve bağlantı testi paylaşıyor; hepsini HIGH işaretlemek severity
filtresini işe yaramaz hâle getirirdi (`media.scan` için verilen kararın
aynısı). Reddedilen değişiklik zaten `allowed=False` ile HIGH'a düşüyor.

### 5.5 Denetim izinin bugünkü hâli [Ö]

| | Sayı |
|---|---:|
| Tanımlı medya eylemi | **20** |
| Kayıt üretmiş eylem | **16** |
| Medya olayı (ADL) | **2.151** |
| Bunların DENY olanı | **427** |
| Hedefi maskeli kayıt (`masked:<fp>`) | **434** |
| ADL toplamı (medya dışı dahil) | **2.716** |

Hiç kayıt üretmemiş 4 eylem: `media.trash`, `media.untrash`,
`media.purge_trash`, `media.purge_archive` — bu sitede çöp/arşiv akışı hiç
koşmadı. "Kod yazmıyor" ile "akış hiç çalışmadı" ayrımını bugün ölçen bir
sinyal **yoktu**; `media_audit_event_total` + `MediaAuditWritesStopped` alarmı
tam bunun için eklendi.

### 5.6 Çok süreçli toplama — neden gerekli [Ö]

Bu makinede dört süreç ailesi ayrı ayrı sayar: `backend` (gunicorn),
`queue-short`, `queue-long`, `scheduler`. `/metrics` birinden servis edilse
diğerlerinin sayısı **görünmez** — ve sayı makul göründüğü için kimse
sorgulamaz.

`exporter.py` `metrics.py`'nin başlığında bırakılan iki seçenekten ikincisini
uygular (parça dosyaları + birleştirme). Doğruluğu iki yönden test edildi:
tek parçalı render `Registry.render()` ile **birebir aynı metni** üretiyor
(aynı yardımcılar kullanılıyor, ikinci bir renderleyici yazılmadı) ve
birleştirme semantiği (sayaç toplanır / histogram kova kova toplanır /
gösterge `latest`) ayrı ayrı doğrulanıyor.

---

## 6. Kurulamayan — ne gerekiyor, tam olarak

Aşağıdakilerin hiçbiri "yapıldı" değildir. Her satır bir **eksik**tir.

### 6.1 Ölçüm noktalarını devreye alma — 1 satır, `hooks.py`

```python
# hooks.py — EKLENMEDİ (dosya bu görevin kapsamı dışı)
after_migrate = [
    # mevcut kayıtların ARDINA eklenir; hiçbir satır silinmez
    "tradehub_core.media.pipeline.observability.instrument.install",
]
```

`install()` idempotenttir, istisna fırlatmaz, bağlanamayan noktayı sebebiyle
raporlar. Boot kancası da olur; karar `hooks.py` sahibinindir.

### 6.2 `/metrics` ucu — 1 fonksiyon, `api/` altında

```python
# api/observability.py — YAZILMADI (api/** kapsam dışı)
@frappe.whitelist(allow_guest=False)
def metrics() -> None:
    from tradehub_core.media.pipeline.observability import exporter
    govde, ct = exporter.metrics_response(max_age_s=3600)
    frappe.local.response.update({"type": "binary", "filecontent": govde.encode(),
                                  "content_type": ct})
```

**Güvenlik notu [T]:** uç `allow_guest` OLMAMALI. Metrik gövdesi slot adları,
ret sebepleri ve depolama büyüklüğü sızdırır — kişisel veri değil ama iç
yapı bilgisi. Prometheus tarafında `bearer_token` ya da ağ düzeyi kısıt
gerekir.

Her sürecin periyodik olarak `exporter.write_shard()` çağırması da gerekir
(scheduler + worker kancası); toplama dizini `MEDIA_METRICS_DIR` ile verilir
ve **konteynerler arası paylaşılan bir volume olmalıdır** — bu bir `docker/`
kararıdır ve o dizin kapsam dışıdır.

### 6.3 Prometheus + Grafana — kurulu değil

| Gereken | Bugün | Nereye |
|---|---|---|
| Prometheus servisi + scrape hedefi | **YOK** | `docker/docker-compose.yml` (kapsam dışı) |
| Alarm kural dosyası | üretiliyor, **yüklenmiyor** | `alerts.to_prometheus_rules()` çıktısı `deploy/prometheus/media.rules.yml` |
| `promtool check rules` doğrulaması | **KOŞULMADI** [?] | promtool kurulu değil |
| Alertmanager + bildirim kanalı | **YOK** | — |
| Grafana + pano | **YOK** | `alerts.grafana_dashboard_json()` çıktısı içe aktarılır |
| **Runbook dosyaları** | **0/16** | `docs/ops/runbooks/<slug>.md` — dizin yok |

Runbook metinlerinin bir kısmı `docs/plans/faz14-golive.md` §5'te duruyor ama
ayrı dosya olarak değil; 16 slug `alerts.runbook_paths()` ile listelenir.

### 6.4 Toplayıcı işi — 8 metrik bekliyor

§5.2'deki 8 metriği yazacak periyodik iş yazılmadı: `media/inventory.py` ve
PII harita denetimi bu görevin dosya kapsamı dışında. Bu iş yazılana kadar
`MediaOrphanFilesGrowing`, `MediaUnprotectedPiiFiles` ve
`MediaPiiFieldCoverageGap` alarmları **veri göremez** — yani kurulsalar bile
sessiz kalırlar. **Bu, en kritik üç KVKK alarmıdır.**

---

## 7. `Media Audit Log` DocType — tasarım ve **kurmama gerekçesi**

Kurulmadı (görev talimatı: şemasını tasarla ve raporla; kurulum Şerit A'da).

### 7.1 Önerilen karar: KURMA — mevcut ADL'yi genişlet [T]

Gerekçe üç ölçüme dayanıyor:

1. **Mekanizma zaten çalışıyor** [Ö]: ADL üzerinde 2.151 medya olayı, 20
   eylem, hash zinciri, `masked:<fp>` maskelemesi, 434 maskeli kayıt.
2. **İkinci tablo hash zincirini böler.** ADL'nin bütünlük güvencesi tek bir
   zincire dayanıyor; medya olaylarını ayırmak, "bu kayıt silinmiş mi"
   sorusunu iki ayrı zincirde ayrı ayrı sormak demek.
3. **CLAUDE.md §4 "DocType bloat"** kuralı: mevcut tablo işi görüyorken yeni
   tablo açmak deponun kendi kuralına aykırı.

Rapor 36'nın "`Media Audit Log` DocType YOK" tespiti **doğru**, ama eksiklik
tablo değil; eksik olan ADL üzerindeki **üç alan**:

| Eksik | Ne yapılmalı | KVKK |
|---|---|---|
| Hassas doctype **okumaları** kaydedilmiyor | `KYC/KYB Verification`, `Payment Transaction` `has_permission` içinde `log_pii_reveal` | m.12 — bugün 0 `pii.reveal` kaydı [Ö] |
| Veri sahibi talebi olayları | `privacy/data_export.py` → `ACTION_EXPORT` | m.11 |
| Retention uygulama kayıtları | `privacy/data_retention.py` → yeni eylem | m.4/2-d |

### 7.2 Yine de ayrı tablo isteniyorsa — şema

Bu şema **uygulanmadı**; kurulacaksa patch + `patches.txt` gerekir (ikisi de
kapsam dışı).

| Alan | Tip | Not |
|---|---|---|
| `timestamp` | Datetime | **indeks**; ADL ile aynı biçim (`media/timefmt.py`) |
| `action` | Select | `MEDIA_ACTIONS` (20 değer) — **indeks** |
| `decision` | Select | `ALLOW` / `DENY` — indeks |
| `severity` | Select | `NORMAL` / `HIGH` |
| `actor` | Data | e-posta; **Link DEĞİL** — kullanıcı silinince kayıt kalmalı |
| `tenant` | Data | `Admin Seller Profile` adı; yine Link değil, aynı gerekçe |
| `object_name` | Data | dosya yolu **ya da** `masked:<sha256[:12]>` |
| `masked` | Check | maskeli kayıtta dosya/kullanım blokları boş döner |
| `context` | Long Text | JSON; **sırlar `_maskele()`'den geçmeden yazılmaz** |
| `prev_hash` / `entry_hash` | Data(64) | zincir; ADL `adl_entry_hash` ile **aynı kanonik alan sırası** |
| `correlation_id` | Data(16) | **YENİ** — `observability/logging.py` ile eşleşme; ADL'de bugün yok |

İzinler: `System Manager` read-only; **write/delete hiç kimseye** (append-only
gerçekten append-only olmalı; bugün ADL'de silme izni var mı **[?]
ölçülmedi**). Saklama: 90 gün sıcak, sonrası soğuk arşiv işareti — `report()`
zaten bu sözü veriyor [K].

**Uyarı:** ayrı tablo kurulursa `media/audit.py` iki yere yazmak zorunda kalır
ya da ADL'den taşıma patch'i gerekir; ikisi de bu tabloyu kurmama gerekçesini
güçlendiriyor.

---

## 8. T-123 — RUM saha telemetrisi

### 8.1 Bugün ne eklendi

| Parça | Durum |
|---|---|
| Kararlı ret sebep kodları (13 kod) | ✅ — metrik etiketi bir API'dir; mesaj metnini düzelten commit alarmı boşaltamaz (V8) |
| `to_metrics()` köprüsü | ✅ — p75 → Prometheus, ms ve CLS **ayrı metrik** (V7) |
| `record_rejection()` | ✅ — `pii_field` reddi ayrı kovada; artışı bir güvenlik sinyalidir |
| 4 regresyon alarmı | ✅ üretiliyor (LCP 2500 ms, CLS 0,25, INP 200 ms, ret artışı) |
| `Media RUM Sample` şema tasarımı | ✅ kod içinde, `RumSample.to_dict()` ile parite **testle** doğrulanıyor |

### 8.2 Hâlâ eksik — saha verisi **toplanmıyor** [Ö]

| Eksik | Nerede olurdu | Kapsam |
|---|---|---|
| `Media RUM Sample` DocType | patch + `patches.txt` | ✗ kapsam dışı — **DocType yok** [Ö] |
| HTTP toplama ucu | `api/` altında | ✗ kapsam dışı |
| Storefront `web-vitals` çağrısı | `tradehubfront` deposu | ✗ başka depo |
| Pano | Grafana | ✗ kurulu değil |

**Yani T-123 KISMİ kalmaya devam ediyor.** Bugün kapanan kısım: toplanan veri
artık *nereye gideceğini* biliyor (metrik + şema + alarm); toplayan taraf yok.

`Media RUM Sample` şeması bilinçli kararlar taşıyor: `Link`/`Dynamic Link`
alanı **yok** (kayıt hiçbir kullanıcıya bağlanamamalı — "PII yok" iddiası
disiplinle değil şemayla korunsun), izin matrisi yalnız `System Manager`
read/delete, saklama **30 gün** (KVKK m.4/2-d; p75 raporlaması için 30 günlük
pencere yeterli, ham satır süresiz tutulmaz).

---

## 9. T-134 — KVKK

`docs/security/kvkk.md` yazıldı (486 satır) ve **canlı ölçümlere** dayanıyor,
jenerik metin değil. Öne çıkanlar:

- **Envanter [Ö]:** 8 doctype, 13 dosya tutan alan, **272 dosya referansı**,
  bunların **0'ı public** — yani 19/24/28/29 numaralı raporların düzeltmeleri
  bugün hâlâ tutuyor (bağımsız ölçüm).
- **Olay kaydı:** bugün kapatılan 11 açığın kişisel veriyle ilgili 4'ü, KVKK
  madde eşlemesi ve **ihlal bildirimi değerlendirmesi için gereken teknik
  girdi** (karar değil).
- **Ölçülen üç boşluk:** dışa aktarım medyayı içermiyor (15 doctype, `File`
  yok); hesap silme dosyalara dokunmuyor (`account_deletion.py`'de `File`
  geçen 0 satır); `Data Retention Policy` **0 satır**.
- **Aydınlatma metni taslağı** — ve neden bugün yayımlanmaması gerektiği
  (karşılanamayacak taahhüt içeriyor).

---

## 10. ÖLÇÜLEMEYENLER

| # | Ne | Neden | Gereken |
|---|---|---|---|
| 1 | **Alarm kurallarının Prometheus'ta geçerliliği** | `promtool` kurulu değil, Prometheus yok | `promtool check rules` |
| 2 | **Panonun Grafana'da çizilmesi** | Grafana yok | İçe aktarma + göz denetimi |
| 3 | **Ölçüm noktalarının üretim yükü altındaki maliyeti** | Süre/performans iddiası bu görevde **yasak** (makine paylaşımlı) | İzole makinede ölçüm |
| 4 | **Çok süreçli toplamanın gerçek 4 süreçle davranışı** | Parça dosyaları simüle edildi; gerçek gunicorn+RQ koşumu yapılmadı | Paylaşılan volume + `write_shard` kancası |
| 5 | **`unmapped` PII alanı var mı** | Ölçen kod yok (§5.2) | Toplayıcı işi |
| 6 | **ADL'de silme izni var mı** (append-only gerçekten mi) | DocPerm denetimi yapılmadı | `Custom DocPerm` sorgusu |
| 7 | **RUM saha verisi** | Toplayıcı uç yok, storefront çağrısı yok | §8.2 |
| 8 | **`ruff` lint** | Ne host'ta ne konteynerde kurulu | `ruff check` |
| 9 | **Üretim ortamındaki hiçbir sayı** | Üretim DB'sine erişim yok | — |

---

## 11. Açık maddeler — sahibi ve tek adımı

| # | Madde | Şiddet | Tek adım | Kimin dosyası |
|---|---|---|---|---|
| **A-1** | Ölçüm noktaları devrede değil | **YÜKSEK** | `hooks.py` `after_migrate` += `instrument.install` | `hooks.py` sahibi |
| **A-2** | `/metrics` ucu yok | **YÜKSEK** | `api/observability.py` (§6.2 taslağı) | `api/**` sahibi |
| **A-3** | 8 metriğin toplayıcısı yok — 3 KVKK alarmı veri göremez | **YÜKSEK** | `media/inventory.py` + PII harita denetimi | envanter görevi |
| **A-4** | Prometheus + Grafana kurulu değil | **YÜKSEK** | `docker/` compose + `deploy/` | altyapı |
| **A-5** | 16 runbook dosyası yok | ORTA | `docs/ops/runbooks/<slug>.md` × 16 | ops belgeleri |
| **A-6** | `Media RUM Sample` DocType yok, uç yok | ORTA | patch + `api/` ucu + storefront `web-vitals` | Şerit A + frontend |
| **A-7** | Hassas doctype okumaları denetlenmiyor | **YÜKSEK** | `has_permission` içinde `log_pii_reveal` | `permissions.py` sahibi |
| **A-8** | m.11 dışa aktarım ve m.7 silme medyayı kapsamıyor | **YÜKSEK** | `privacy/data_export.py` + `account_deletion.py` | privacy görevi |
| **A-9** | `pipeline/__init__.py` `IMPLEMENTED` sözlüğü 3 yeni modülü bilmiyor | DÜŞÜK | 3 satır ekleme | `pipeline/__init__.py` sahibi |

---

## 12. Sonuç

T-133'ün **kod tarafı bitti**: 24 metrik, 10 ölçüm noktası (bench'te 10/10
bağlanıyor), çok süreçli `/metrics` gövdesi, 16 alarm kuralı ve 12 panelli
pano — hepsi 85 yeni testle ve 8 vacuity deneyiyle. **Altyapı tarafı
başlamadı** ve bu görevde başlayamazdı: Prometheus, Grafana ve `docker/`
kapsam dışı.

Bugünkü en somut kazanç ölçülebilir olanı: **hiçbir metriğin yazanı yokken
16'sının yazanı oldu**, ve denetim ekranında **110 ayar değişikliği kaydı**
görünür hâle geldi.

En dürüst cümle ise şu: **bugün hâlâ tek bir metrik toplanmıyor.** Toplanması
için gereken tek satır (`hooks.py`) ve tek fonksiyon (`/metrics` ucu) §6'da
yazılı; ikisi de bu görevin dosya kapsamının dışında.
