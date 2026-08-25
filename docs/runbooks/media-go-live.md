# Runbook — Medya Boru Hattı Go-Live (T-144)

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme: 2026-08-20, W6 kapanış dalgası. Adımların tamamı DEV'de **gerçekten koşulmuş** komut ve bulgulardan (raporlar 69, 17, 42, 63, 70, 71, 72, 73, 76) derlendi.
>
> ⚠️ **ÜRETİM TATBİKATI YAPILMADI.** 2026-08-24'te belirlenimci canary ve
> `%10 → %50 → %100` seçimi koda bağlandı, yerel site migrate edildi ve geçiş
> testleri yeşil koştu. Yerel hard-kill kontrol düzlemi **1,947 ms** ölçüldü ve
> ayarlar geri yüklendi (`docs/reports/101-mogem617-rollout-rehearsal.md`). Bu
> teknik prova üretim go-live'ı değildir; canlı metrik
> penceresi, nöbetçi teyidi ve ölçülmüş üretim geri dönüş süresi hâlâ insan/DevOps
> kapısıdır.

---

## 0. Ön koşullar (gitmeden kontrol et)

| # | Kontrol | Kaynak |
|---|---|---|
| 1 | **İmaj rebuild yapıldı mı?** libvmaf'lı ffmpeg (Dockerfile n8.1.2 pinli, çalışan konteyner 5.1.9), boto3 (bench venv'e elle kuruldu — rebuild'de kaybolur), Node ≥22 — "Tek rebuild üç görevi açar" | 57 §doğrulanamayan, 23 §2.2 |
| 2 | Backfill ön koşulları Ö1–Ö6 (PII taraması, EXCLUDED_MEDIA_FIELDS, reconcile, **türev profil kararı R1 — GERİ DÖNÜLEMEZ**, disk boş alan tazele: backup.py'deki 382 GB 2026-08-13 tarihli, bayat) | 17 §, migration.md §9.1 |
| 3 | `long` kuyruk derinliği **0** olmalı (backfill ve canlı video transcode aynı kuyruğu, tek worker'ı paylaşıyor) | 17 |
| 4 | `docs/closure/faz*-kapanis.md` imzaları + `nihai-kabul-taslak.md` insan kalemleri | bu dalga |
| 5 | nginx T-131 blokları: `docker/nginx/*.local.template` **gen-local-nginx.sh üretimi** — script yeniden koşarsa bloklar SİLİNİR; üretim kenarında kalıcı konfigürasyona taşındığını doğrula | 70 |
| 6 | `site_config` anahtarları: `media_metrics_token` (zorunlu, /metrics bearer), opsiyonel `rum_token_salt`, `rum_daily_sample_cap` (varsayılan 50000), `rate_limit_trusted_proxies` (**T9 kalıntı riski**: kenar XFF'i ezmezse saldırgan kendi limitinden kaçar — 36 §3.4) | 42, 72, 29 |

---

## 1. Canary ve bayrak açma sırası

DocType: **Media Engine Settings** (Single). Rapor 69 §1'in ana düzeltmesi: **"görev iki bayrak diyordu, İKİ BAYRAK YETMİYOR"** — `media_pipeline_enabled=1` + `manifest_api_enabled=1` ile `rendition_on_upload` ve slot kapıları kapalı kalır, "tek satır veri akmıyor".

Önce kapsamı fail-closed canary'ye daralt, sonra dört çalışma bayrağını aç.
Her adımdan sonra doğrula:

```bash
# 0. Canary kapsamı — master açılmadan ÖNCE
docker exec istoc-dev-backend-1 bench --site <site> execute frappe.db.set_single_value \
  --args '["Media Engine Settings","rollout_percent",0]'
docker exec istoc-dev-backend-1 bench --site <site> execute frappe.db.set_single_value \
  --args '["Media Engine Settings","rollout_stores","<seller-profile-name>"]'
# 1. Ana şalter
docker exec istoc-dev-backend-1 bench --site <site> execute frappe.db.set_single_value \
  --args '["Media Engine Settings","media_pipeline_enabled",1]'
# 2. Manifest API
... set_single_value '["Media Engine Settings","manifest_api_enabled",1]'
# 3. Yükleme anında türev üretimi
... set_single_value '["Media Engine Settings","rendition_on_upload",1]'
# 4. Slot beyaz listesi — İLK AŞAMADA YALNIZ ürün görseli
... set_single_value '["Media Engine Settings","active_slots","product.image"]'
```

- Çalışma bayraklarının varsayılanı **0/0/0/boş**; ana şalter kapalıyken rollout
  ayarı ne olursa olsun hat kapalıdır. Yeni `rollout_percent` alanının migrate
  varsayılanı geriye uyum için `%100` olduğundan canary değeri **master'dan önce**
  yazılır.
- `max_renditions_per_asset` = 40, dokunma.
- Diğer 8 slot bilinçli kapalı başlar; genişletme ayrı karar.
- `rollout_stores` satır/virgül ayrımlı canary listesidir ve yüzdeden önce gelir.
  Yüzde seçimi SHA-256 tabanlı kararlı `0..99` kovasıdır; `%10 ⊂ %50 ⊂ %100`,
  süreç/restart değişiminden etkilenmez. Kısmi rollout'ta sahibi çözülemeyen medya
  fail-closed dışarıda kalır; dışarıdaki mağazaya manifest ham dosya fallback'i
  verir ve yeni türev yazmaz.
- **Sıra önemli notu (17 §4.5):** türev TOHUMLAMA (mevcut dosyalar) `rendition_on_upload` **açılmadan**, doğrudan `render_ladder` çağıran toplu işle koşulmalı — "bayrak açmak canlı yükleme yolunu da değiştirir". Yani: önce tohumlama (adım 3'ten önce), sonra bayrak 3.

Doğrulama (69 §2'nin DEV'de ölçtüğü sonuç şekli): testi bir yüklemeyle yap; `Media Asset/Version/Rendition/Processing Job` satırları artmalı (DEV'de 9/9/88/9, 9/9 success, kuyruk `media-image-live`), `File` sayısı ARTMAMALI (hat File kaydı açmaz, tasarım gereği), türevler diskte `files/media/{asset}/{version_hash}/` altında bayt-bayt doğrulanabilir olmalı.

---

## 2. İmaj rebuild + worker yeniden yaratma TUZAĞI (W3-B bulgu 1)

**Bulgu (69 §3):** backend imajı 07:06'da rebuild edildi, `backend` konteyneri yeniden yaratıldı; **`queue-long` / `queue-short` / `scheduler` dünkü imajda kaldı.** Kanıt: `docker exec istoc-dev-queue-long-1 grep -c content_fingerprint …/pipeline_bridge.py → 0`.

**Neden restart yetmez:** kod imaja gömülü, bind-mount değil (mount listesi ölçüldü: yalnız `sites` + `logs` volume). `bench restart` süreci yeniler, **imajı değil** — konteynerin yeni imajdan yeniden YARATILMASI gerekir.

**Çözüm (koşulmuş komut):**
```bash
docker compose -p istoc-dev up -d --no-deps queue-long queue-short scheduler
```

**Zorunlu doğrulama üçlüsü** (her rebuild sonrası):
1. `api/method/ping` ve `/` → 200,
2. worker sürecinde yeni kodu grep'le doğrula (`docker exec istoc-dev-queue-long-1 grep -c <yeni-sembol> <dosya>` → ≥1),
3. `docker ps` imaj ID'leri backend ile aynı mı.

**Risk cümlesi (rapora geçmiş):** "worker'lar da yeniden yaratılmazsa kuyruk işleri sessizce ESKİ kodla koşar. Bugün koşulsaydı türevler hash'siz eski adres şemasıyla yazılacaktı."

**Yan tuzak — Pillow sürüm kayması (69):** `engine_version` `version_hash` girdisidir (64: pillow-11.3.0 → bugünkü imaj 12.2.0). İmaj güncellemeleri **adresleri değiştirir** — tasarım gereği; sürpriz sanma, sürümü kayda geçir.

---

## 3. Migrate ve kilit

- Şema değişiklikleri DocType JSON + `bench migrate` ile gider; veri düzeltmesi patch değil **idempotent yardımcı fonksiyon** (73 §1 deseni, `enrich_version`).
- **Migrate kilidi:** migrate tek başına koşmalı — paralel ajan/iş koşarken migrate koşturma (34 §6: "Paralel üç ajan koşuyordu; migrate kilidi riskli, koşturmadım"). Ölçülen tek temiz koşum: 37 §5.1 — 19:27:50→19:28:07, hata 0.
- `after_migrate` = `setup.install.after_install` + `api.observability.install_instrumentation` (hooks.py:19) — migrate sonrası enstrümantasyon otomatik yeniden bağlanır; her süreçte `ensure_instrumented` `after_request` kancasıyla tamamlar.
- Migrate sonrası doğrulama: `tabDocField`/`SHOW COLUMNS` ile yeni alanlar (73 §1: 7/7 kolon örneği).
- hooks.py'ye yeni cron eklerken: `"*/5 * * * *"` anahtarı zaten var — **aynı dict'te ikinci kez yazmak öncekini sessizce düşürür** (hooks.py:137-146 yorumu).

---

## 4. Backfill (mevcut medya) — plan 17-t028

İki ayrı iş; sırayı karıştırma:
1. **Eski-motor backfill'i (A_otomatik): 49 dosya / 30,4 MB / 1 batch.**
2. **Türev tohumlama: 2.428 adres ≈ 7,1 saat tek worker (bant 7–47 sa), 29.136 nesne, 0,6–0,9 GB** — `rendition_on_upload` açılmadan, `render_ladder` toplu işiyle.

Operatör adımları (17'den, script çalıştırmaz — sen çalıştırırsın):
```text
1. Kuru koşu : media_admin.start_image_optimization(file_names=BATCH, scope="selected", preset="balanced", dry_run=1)
2. İlerleme  : runner.read_progress(job_key)        # Redis TTL 3600 s! "not_found" = GEÇTİ değil → DUR
3. Gerçek    : aynı çağrı dry_run=0                  # ⚠ scope="pending" KULLANMA — MAX_BATCH uygulanmaz,
                                                     #   tüm küme tek 3600 s'lik işe girer (api/media_admin.py:197-202)
4. Batch boyu: 200 (dosya bütçesi 18,0 s) — tohumlamada 100 (çekişmede 50)
```

**Durdurma kriterleri (her batch sonrası, sonraki enqueue'dan önce):** `errors/processed > %2 → DUR` (skipped hata değildir) · `file_missing > %1 → DUR` · `decode_failed > %1 → DUR`.

**Backfill süresince:** `archive.purge_expired()` **DURDURULMALI** (30 günlük doğrulama penceresi boyunca) — geri alma orijinalleri arşivde yaşar.

**Bilinen kusur:** `media/trash.py:40-44` `".." in url` alt-dize kontrolü — `..jpg` ile biten 8 meşru dosya "çöpe atılamaz, geri alınamaz, optimize edilemez". Backfill kapsam dışında tut ya da önce düzelt.

---

## 5. Geri alma (rollback)

### 5.1 Bayrak kapat — neyi geri alır
Ana şalter `media_pipeline_enabled=0` **her şeyi keser** (alt bayraklar ve slotlar kayıtlı değerleri ne olursa olsun False döner — pipeline_flags kural 2). Kapılar kuyruk işinin İÇİNDE yeniden sorulur → uçuştaki işler de durur (69 §5.4). Yeniden açılış idempotent: `_run_rendition_job` ikinci koşumda 88→88 (0 yeni satır/dosya).

```bash
# Kontrollü daraltma: yüzde grubunu çıkar, yalnız canary listesi kalsın.
bench --site <site> execute frappe.db.set_single_value --args '["Media Engine Settings","rollout_percent",0]'

# Sert geri dönüş: canary dahil tüm yeni medya hattını kes.
bench --site <site> execute frappe.db.set_single_value --args '["Media Engine Settings","media_pipeline_enabled",0]'
```

Önce `%0` daraltması kullanılır; veri kaybı, yanlış görsel servisi veya belirsiz
sahiplikte beklemeden ana şalter kapatılır. Ayar güncellemesi request önbelleğini
temizler; uzun ömürlü worker işi de işin içinde kapıyı yeniden sorar.

### 5.2 Bayrak kapatmanın GERİ ALMADIĞI kalıcı izler (69 §9 ölçümü)
- Üretilmiş `Media Asset/Version/Rendition/Job` satırları ve diskteki `files/media/**` türev dosyaları (DEV'de 9+9+88+9, ~2,0 MB) — silinmez; purge ayrı ve onaylı iş.
- Optimize edilmiş orijinaller (ör. `067-1 GRİ.jpg` −55.119 B) — 30 gün içinde `media_admin.start_restore(scope="selected"|"optimized")` / `restore_image(file_name)`; **`th_optimized_at` boş dosya GERİ ALINAMAZ** (runner.py:336-337).
- Worker konteynerleri yeni imajda kalır (istenen durum).
- Şema değişiklikleri (örn. Media Version 7 kolon) migrate ile geldi, bayraktan bağımsız kalıcı.
- Bilinen artıklar (temizlik karar bekliyor): hassas-ikiz sızıntı envanteri (64 EK: 1 Asset + 1 Version + 10 Rendition, 315.836 B — "silme/maskeleme kararı ayrı iş"), RUM sahte 5 örnek (30 günde purge), panel E2E 11 `e2e-` File kaydı (75 §5).
- nginx geri dönüşü (70): storefront.local.template'teki üç T-131 bloğunu sil + `docker compose restart storefront`; dikkat — `gen-local-nginx.sh` yeniden üretim de blokları siler.

### 5.3 Bilinen yan etki
DEV'de bayrak açıkken `tabMedia Rendition.file_url` `/files/` taşıdığı için `test_media_usage_sources.test_kapsanmayan_alan_kalmadi` KIRMIZI — kolon kaynak listesine ya da `BILINCLI_DISARIDA`ya eklenmeli (71 §6).

---

## 6. İzleme

### 6.1 /metrics
`GET /api/method/tradehub_core.api.observability.metrics` · `Authorization: Bearer <site_config.media_metrics_token>` · yanlış token 401, tokensiz 403 (57d §3.3). Çok süreçli toplama: `sites/<site>/private/media-metrics/media-<pid>.metrics.json`, 5 dk'lık cron `write_metrics_shard` (hooks.py:134-146). `MEDIA_METRICS_DIR` konteynerler arası **paylaşımlı volume** olmalı (42 §6.2).

### 6.2 İlk hafta izlenecek seriler (24 tanımlı; 16'sının yazanı var, **8'i toplayıcı bekliyor**)
- Boru hattı: `media_job_total{job,state}`* · `media_job_attempts`* · `media_image_process_duration_seconds` (p95 alarm eşiği 5 s) · `media_video_transcode_duration_seconds{outcome}` · `media_bytes_saved_total`*
- Güvenlik: `media_upload_total{outcome="rejected"}` (oran >%30 alarm) · `media_scan_total{status}` · `media_svg_sanitize_total{code!="ok"}` · `media_isolation_total` · `media_policy_violation_total` · `media_audit_event_total` (yazma durursa `MediaAuditWritesStopped`)
- Depolama/KVKK (*toplayıcısı YOK — kurulmadan alarmları sessiz kalır, en kritik üç KVKK alarmı dahil, 42 §6.4): `media_storage_bytes`* · `media_storage_objects`* · `media_orphan_files`* (eşik 1200; ölçülmüş taban 1.166) · `media_pii_field_coverage`* · `media_pii_unprotected_files`*
- RUM (canlı, 72 ile doğrulandı): `media_rum_p75_milliseconds{metric=LCP|INP}` (LCP>2500 / INP>200 alarm) · `media_rum_cls_p75` (>0.25) · `media_rum_samples_total` · `media_rum_estimated_population` · `media_rum_rejected_total` (15 dk'da >10)

16 alarm kuralı dosyada hazır: `deploy/prometheus/media-alerts.yml`; pano `deploy/grafana/media-engine.json` (12 panel). **Prometheus/Grafana/Alertmanager kurulu DEĞİL; `promtool check rules` koşulmadı; 16/16 runbook_url kırık (docs/ops/runbooks/ yok)** (42 §6.3, §10) — go-live öncesi kurulum + promtool İNSAN/DevOps işi.

### 6.3 Zamanlanmış işler (hooks.py'de W6'da doğrulandı)
| Zamanlama | İş |
|---|---|
| cron */5 | `observability.write_metrics_shard` · `transcode.sweep_stuck_transcodes` · `av.sweep_stuck_scans` |
| hourly | **`api.rum.aggregate_samples`** (hooks.py:157) — idempotent, high-water `tabDefaultValue`'da (72) |
| daily | **`api.rum.purge_expired_samples`** (30 gün) · `archive.purge_expired` · `trash.purge_expired` · `backup.run_scheduled` · `retention.run_scheduled_gc(_originals/_derivatives)` |

Gerçek scheduler koşumu henüz gözlenmedi (72 §7) — go-live sonrası ilk saat `aggregate_samples`'ın çalıştığını /metrics'ten doğrula.

### 6.4 Drift CI (gecelik)
`admin-panel/.github/workflows/drift-nightly.yml` — cron `47 1 * * *` (04:47 TRT) + workflow_dispatch; tradehubfront'u kaynaktan kurar, `drift-measure.mjs --dist … --base $DRIFT_BASE`; herhangi bir bölge >2 px → exit 1 → CI KIRMIZI; ölçüm JSON'u 30 gün artifact. Sahte-yeşil korkuluğu `MIN_OLCUM: 10` (gerçek `DRIFT_BASE` verilince ~80'e çekilmeli). Son ölçüm: 88 kutu, driftCount 0, maks 0,42 px (76). **İNSAN işi: dosya commit/push + default branch (master) merge — schedule merge edilmeden HİÇ KOŞMAZ; 60 gün inaktivitede GitHub schedule'ı durdurur; webhook/Slack bağlanmadı.**

### 6.5 Öksüz dosya raporu
`seller_media.list_orphans(days_unused, start, page_length)` — zamanlanmış İŞ DEĞİL, uç; toplu ters tarama 9 ms (satır-başına 373 ms'e karşı ~40×). "Bu bir silme listesi değildir" (71). Haftalık elle kontrol öner.

---

## 7. Go-live sıra özeti (tek bakış)

1. İmaj rebuild + **worker'ları yeniden yarat** (§2) + doğrulama üçlüsü.
2. Prometheus/Grafana kur, `promtool check rules`, 16 runbook dosyası (İNSAN/DevOps).
3. `bench migrate` (tek başına, kilit; §3) + kolon doğrulaması.
4. Backfill ön koşulları + türev tohumlama (bayraksız, §4) — arşiv purge DURDUR.
5. Canary kapsamını yaz (§1): `rollout_percent=0` + `rollout_stores=<canary>`.
6. Bayrakları sırayla aç (§1): master → manifest → rendition_on_upload → `active_slots="product.image"`.
7. İlk saat: /metrics serileri + `aggregate_samples` + kuyruk derinliği + `media_upload_total{outcome="rejected"}` izle.
8. Kapılar yeşilse sırasıyla `%10 → %50 → %100`; her aşamada §6 metriklerini ve §1 kapsamını doğrula.
9. Sorun → önce `%0`a daralt; kritik durumda §5.1 ana şalteri kapat. Kalıcı izleri §5.2'ye göre yönet.
10. Diğer 8 slotu ayrı kararlarla genişlet.

> **Tatbikat kaydı (boş — İNSAN dolduracak):**
> Tatbikat tarihi: ______ · Geri dönüş süresi (ölçülen): ______ · Tatbikatı koşan: ______ · Notlar: ______

## EK — Prometheus alarm kurulumu (T-133)

> Kurallar bu depoda ÜRETİLDİ (`docs/observability/media-alerts.yml`, 18 kural /
> 2 grup) ama Prometheus AYRI BİR SUNUCUDA. Bu bölüm o sunucudaki adımlar.
> Kurallar deposu ile eşik gerçekliği: 87-w7-guvenlik-kabul.md · T-133.

### EK.1 Scrape hedefi — üç süreç ailesi, üç hedef

`/metrics` bir sürecin sayaçlarını verir; medya hattı üç ayrı süreç ailesinde
koşar (`backend` web, `queue-short`, `queue-long`). Toplayıcı parça dosyalarıyla
birleştirir (bkz. `api/observability.py`), ama Prometheus tarafında yine de her
hedefi ayrı scrape edip `sum by (job)` ile toplamak en sağlam yol.

Uç oturumsuz istekte **Bearer token** ister (`site_config.media_metrics_token`,
64 karakter). Token GÖVDEYE değil BAŞLIĞA girer; `?token=` bilinçli reddedilir.

```yaml
# prometheus.yml — scrape_configs
- job_name: "tradehub-media"
  metrics_path: /api/method/tradehub_core.api.observability.metrics
  scheme: https
  authorization:
    type: Bearer
    credentials_file: /etc/prometheus/tradehub_media_token   # 0600, tek satır token
  scrape_interval: 30s          # SHARD_MIN_INTERVAL_S=15 altında tazelik ölçülemez
  static_configs:
    - targets: ["istoc.localhost"]   # tek gateway; süreç ayrımı parça dosyalarında
```

> Doğrulama: `curl -H "Authorization: Bearer $(cat token)" https://<host>/api/method/tradehub_core.api.observability.status`
> — `token_configured:true`, `exporter.shard_count`, `coverage` döner. Sırrın
> KENDİSİ değil, yapılandırılmış olup olmadığı raporlanır.

### EK.2 Kuralları yükle + doğrula

```bash
cp media-alerts.yml /etc/prometheus/rules/media-alerts.yml
promtool check rules /etc/prometheus/rules/media-alerts.yml   # BU DEPODA promtool YOK; burada koş
curl -X POST http://localhost:9090/-/reload                    # ya da SIGHUP
```

`media-engine` grubu KANONİK ve `alerts.py::dogrula()` ile metrik-adı tutarlı
(0 unknown_metric). Değiştirmen gerekirse `alerts.py`yi düzenleyip yeniden üret
(başlık yorumundaki komut) — YAML'ı elle düzenleme, sonraki üretimde kaybolur.

### EK.3 Eşiklerin gerçekliği — İLK 2 HAFTA GÖZLEM

- Çoğu medya metriği bugün **0** (üretim tabanı yok); RUM/audit dışındaki
  eşikler `threshold_source`da "ÖLÇÜLMEDİ" işaretli. Alarmı sıkı bağlamadan
  önce ilk 2 haftayı gözle, tabanı ölç, eşiği ayarla.
- `media-engine-queue` grubu (2 kural) EK'tir, eşikleri ölçülmemiştir ve
  `alerts.py`de karşılığı yoktur — kalıcı olunca oraya taşı ki `dogrula()`
  kapsamına girsin.
- **Metriği olmayan istekler:** "417 oranı" (kodda 417 statüsü yok; ret
  `media_upload_total{outcome="rejected"}` ile izlenir) ve "drift" (observability
  paketinde drift metriği yok) için bugün bağlanacak seri YOK — uydurma kural
  yazılmadı; önce metrik eklenmeli.

### EK.4 Runbook dosyaları (İNSAN/DevOps yazacak)

18 kuralın `runbook_url`u `docs/ops/runbooks/<slug>.md`ye işaret eder; **bu dizin
bugün YOK**. Alertmanager bildirimi bu dosyalara link verecek. Yazılacak slug'lar:
`media-upload-rejection · media-malware · media-scan-failure · media-isolation ·
media-slow-processing · media-svg · media-orphans · media-pii-exposure ·
media-pii-coverage · media-audit-gap · media-instrumentation · media-transcode ·
rum-lcp · rum-cls · rum-inp · rum-rejected · media-job-failure · media-job-retry`.

## Kaynak raporlar
69-w3b-boru-hatti-e2e.md (bayraklar, worker tuzağı, kalıcı izler) · 17-t028-backfill-plani.md · 42-t133-gozlemlenebilirlik.md · 72-w3e-rum-toplama.md · 63-be1-rum-zinciri.md · 76-w4-drift-gecelik.md · 71-w3d-oksuz-rapor.md · 70-w3c-medya-csp.md · 73-w4-manifest-zenginlestirme.md · 64-be2-dedup.md · 57d-durum-faz12-14.md · docs/plans/faz14-golive.md · tradehub_core/hooks.py
