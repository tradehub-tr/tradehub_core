# Rapor 97 — W9: İzlenebilirlik son tur + alarm besleme doğrulama

> **Görev:** iki kalem — (1) T-140 kalan etiketler, (2) T-133 alarm zinciri uçtan
> uca. Kural: ÖNCE ÖLÇ. Yeni test yazma, assertion değiştirme, üretim kodu,
> frontend, `hooks.py`, commit YOK. RUM sahte örnekleri sonunda temizlendi.

---

## Kalem 1 — T-140 kalan etiketler · **YAPILDI**

### Ölçüm (önce)

`gen_traceability.py` koşuldu. Başlangıç: **83 / 202 kapsanan (%41,1)**, 119
KAPSANMIYOR. Rapor 93'ün "emin olamadığım ~12 aday" listesi + kalan etiketsiz
medya FE testleri gövde gövde okundu.

### Yapılan — yalnız EMİN eşleşme, etiket test adının BAŞINA, assertion'a dokunulmadı

| Dosya | Test → etiket | Gerekçe (gövde okundu) |
|---|---|---|
| `crop/__tests__/cropSafeArea.test.js` | "güvenli alan eşikleri canlı politikayla birebir" → **[FR-023][FR-024]** | `SAFE_BAND` eşikleri canlı `slots/*.json` `content_rules`'tan: `company.cover_image` 0,417 (FR-023), `category.banner` 0,42 (FR-024) — birebir assert |
| `crop/__tests__/cropSafeArea.test.js` | "kuralı olmayan slotta bant YOK" → **[FR-023][FR-024]** | `safeBandFor("company.cover_image").axis==="x"`, `category.banner` `.axis==="both"` — iki slotta bant TANIMLI, ötekilerde `null` |
| `crop/__tests__/cropSafeArea.test.js` | "kadrajın merkezindeki odak bandın içindedir" → **[FR-023]** | cover_image için merkez odakta `safeBand` uyarısı ÜRETİLMEZ — bandın davranışsal sınaması |
| `crop/__tests__/cropPolicy.test.js` | "uyarı türlerinin her biri en az bir fixture'da üretiliyor" → **[FR-023]** | cover_image + sol-kenar odak → `safeBand` uyarısı gerçekten üretiliyor (dışına taşan içerik → uyarı, FR-023 metni) |
| `utils/__tests__/dateFormat.test.js` | "üç giriş biçimi de AYNI ana çözülüyor" → **[NFR-052]** | ISO+03:00 / işaretsiz / Frappe ham biçimi → aynı ana; saat dilimi tek anlamlı (NFR-052) |
| `utils/__tests__/dateFormat.test.js` | "saat dilimi işareti olmayan tarih sunucu saati sayılıyor" → **[NFR-052]** | işaretsiz tarih +03:00 varsayımıyla çözülüyor — NFR-052'nin ölçülen hatası (Londra kayması) tam bu |

**Koşum kanıtı:** `node --test` üç dosya → **44 pass, 0 fail, 0 skip**
(cropSafeArea'daki `ATLA`-korumalı parite testleri kardeş `tradehub_core`
checkout'u mevcut olduğu için GERÇEKTEN koştu, atlanmadı).

### Ölçüm (sonra) — matris yeniden üretildi, `--check` YEŞİL

| Ölçüm | Önce | Sonra |
|---|---:|---:|
| En az bir teste bağlı (A ∪ C ∪ F) | 83 (%41,1) | **86 (%42,6)** |
| KAPSANMIYOR | 119 | **116** |
| F kanıtı olan gereksinim | 19 | **22** |
| FE test adındaki `[FR/NFR]` etiketi | 43 | **51** |

**İlk kez kapsanan 3 gereksinim:** FR-023, FR-024 (güvenli alan şeritleri),
NFR-052 (tarih/saat tek anlamlılığı). Üçü de A/C kanıtı olmadan yalnız F ile
kapsandı.

### Vacuity kanıtı

`[FR-024]` etiketleri geçici olarak silindi → yeniden üretimde kapsama
**86 → 85** düştü, FR-024 satırı matristen çıktı; etiketler geri kondu →
**86**'ya döndü. Etiket gerçekten kapsamı taşıyor, dekoratif değil.

### Kaçındığım sahte etiketler (uydurma kapsama = en büyük tehlike)

| Aday | Neden etiketlenMEDİ |
|---|---|
| `session.test.js` CHUNK=2 MB (NFR-007) | `const CHUNK` testin KENDİ içinde; assertion mock'un döndürdüğü `chunk_bytes`'ı sınıyor, üretimin 2 MB kullandığını PİNLEMİYOR → dairesel, sahte olurdu |
| `ProductVideoSection.test.ts` playsinline (FR-127) | FR-127 zaten F ile kapsanıyor; ek etiket kapsamı büyütmez |
| `videoDecision.test.js` (NFR-011) | yorumlayıcı paritesi ölçülüyor, "gereksiz re-encode yok" kapı politikası DEĞİL — rapor 93'ün reddi geçerli |
| `dedupCheck.test.js` (NFR-050) | istemci uyarısı; depo tekliği S9'da ölçülüyor, bağ dolaylı |
| `mediaVideoStatus.test.js` (FR-118) | FR-118 `private_transcode_atlandi` mesajını istiyor; rozet testleri bunu ölçmüyor |

**116 gereksinim HÂLÂ KAPSANMIYOR** ve bu bir ölçümdür, başarısızlık değil:
çoğu F3/F3+ fazına ait, uygulanmamış. Matris §3'te tek tek yazılı.

---

## Kalem 2 — T-133 alarm zinciri uçtan uca · **YAPILDI**

Doğrulama betiği yazıldı: **`scripts/verify_media_alerts.py`** (salt okunur;
promtool yok, PyYAML + elle kural şeması + drift + besleme). Bench venv ile
koşuldu (`./env/bin/python`, PyYAML 6.0.3).

### (a) YAML geçerli mi + şema — **GEÇTİ**

- YAML `safe_load` ile ayrıştı; **18 kural**, **0 şema hatası**.
- Her kuralda `alert`/`expr`/`for` + `labels.{severity,component}` +
  `annotations.{summary,description,runbook_url,threshold_source}` mevcut.
- `severity` bilinen kümede (`warning`/`critical`), alarm adları TEKİL.
- **Drift:** `media-engine` (kanonik) grubu `alerts.to_prometheus_rules()`
  çıktısıyla **bayt bayt aynı** — elle düzenlenmemiş. `alerts.dogrula()`:
  16 alarm, **0 unknown_metric, 0 duplicate**. (`media-engine-queue` grubu
  alerts.py DIŞINDA elle eklendi, header bunu zaten söylüyor.)

### (b) Her `expr` metriği canlı `/metrics`'te var mı — **18'in 4'ü besleniyor**

Canlı `/metrics` (kimlikli scrape, HTTP 200) **yalnız 5 seri ailesi** taşıyor:
`media_audit_event_total` + 4 RUM ailesi. Kalan tüm medya metrikleri 0 seri.

| Durum | Sayı | Alarmlar |
|---|---:|---|
| **CANLI** (metrik + eşleşen seri var) | 3 | RumLcpRegression, RumClsRegression, RumInpRegression |
| **KISMEN** (bir metrik canlı, biri ölü) | 1 | MediaAuditWritesStopped |
| **ÖLÜ** (koşullandığı seri hiç üretilmiyor) | 14 | aşağıda sınıflandırıldı |

`MediaAuditWritesStopped` özel: `media_audit_event_total` CANLI ama expr
`... and sum(rate(media_upload_total))>0` guard'ı taşıyor; upload metriği ölü
olduğu için alarm bugün **tetiklenemez — bu DOĞRU davranış** (yükleme yoksa
denetim-boşluğu alarmı da çalmamalı).

### Ölü alarmların ayrımı: "İLK 2 HAFTA GÖZLEM" vs "metrik eklenmeli"

**Grup 1 — metrik `instrument.py` ile çağrı yoluna BAĞLI, gerçek trafik
bekliyor (İLK 2 HAFTA GÖZLEM):** 9 alarm. Metrik üretimi kodda kablolu
(`NOKTALAR` / `NOKTA_DISI_YAZILAN`); ilgili yol gerçek yükleme/tarama/işlemeyle
çalışınca seri doğar.

| Alarm | Metrik | instrument.py kablolaması |
|---|---|---|
| MediaUploadRejectionSpike | `media_upload_total` | `policy.evaluate` noktası |
| MediaMalwareDetected | `media_scan_total` | `av.scan_path` (bench_gerekir) |
| MediaScanFailing | `media_scan_total` | aynı |
| MediaIsolationFailures | `media_isolation_total` | `isolation.run_*` |
| MediaImageProcessingSlow | `media_image_process_duration_seconds` | `image.probe/normalize/lqip` |
| MediaSvgRejected | `media_svg_sanitize_total` | `svg.sanitize` |
| MediaVideoTranscodeErrors | `media_video_transcode_duration_seconds` | `video.transcode` |
| MediaInstrumentationErrors | `media_instrumentation_errors_total` | `_kaydet` sarmalayıcı |
| RumRejectedSpike | `media_rum_rejected_total` | `delivery/rum.py::reject_reason` |

**Grup 2 — metrik hiçbir çağrı noktasınca YAZILMIYOR; periyodik bir TOPLAYICI
eklenmeli (metrik eklenmeli):** 5 alarm. `instrument.TOPLAYICI_GEREKTIREN`
listesi bunu zaten bir "eksiklik itirafı" olarak taşıyor — envanter taraması /
PII haritası denetimi / iş kuyruğu sayacı yazan bir görev gelene kadar bu
seriler ASLA doğmaz.

| Alarm | Metrik | Gereken üretici |
|---|---|---|
| MediaOrphanFilesGrowing | `media_orphan_files` | yetim uzlaştırma taraması (bugün `enabled:false`) |
| MediaUnprotectedPiiFiles | `media_pii_unprotected_files` | PII katman denetimi periyodik işi |
| MediaPiiFieldCoverageGap | `media_pii_field_coverage` | `EXCLUDED_MEDIA_FIELDS` kapsam denetimi |
| MediaJobFailureRatio | `media_job_total` | medya iş kuyruğu sayaç enstrümantasyonu |
| MediaJobRetryExhaustion | `media_job_attempts` | aynı kuyruk histogramı |

**Ayrıca:** etiket-dalı denetimi — canlı ailede bile eşitlik seçicisi
karşılıksız olabilir. RumInpRegression'ın `metric="INP"` dalı canlı seride VAR
(tohum INP verisi mevcut), bu yüzden CANLI sayıldı; besleme tam.

### (c) En az bir alarmın tetiklenebilirliği GÖSTERİLDİ — iki bağımsız kanıt

**Kanıt 1 — canlı veriyle, enjeksiyonsuz:** `/metrics` şu an
`media_rum_p75_milliseconds{metric="LCP",route="/"} 12712` taşıyor (tohum
aykırısı). RumLcpRegression expr'i `max(...LCP...) > 2500` elle değerlendirildi:
**12712 > 2500 = DOĞRU → alarm TETİKLENİR.** Prometheus'a gerek kalmadan
kanıtlandı.

**Kanıt 2 — uçtan uca boru hattı (POST → aggregate → /metrics):** RUM ucuna
`/kategori/:slug` için üç eşik-aşan sahte LCP örneği (9000/8800/9100 ms)
yazıldı → `aggregate_samples()` koşuldu → `/metrics`'te
`media_rum_p75_milliseconds{metric="LCP",route="/kategori/:slug"} 9000` okundu.
9000 > 2500 → RumLcpRegression tetiklenirdi. Boru hattının istemci-ucundan
scrape-çıktısına kadar çalıştığı gösterildi.

> Not: RUM ucu genel geçit (`istoc.localhost`) üzerinden **502** döndü; örnek
> backend konteynerine doğrudan (Host başlığıyla) yazılarak devam edildi.
> Geçidin RUM POST'unu 502'lemesi ayrı bir bulgu olabilir — bu görevin kapsamı
> dışında, not düşülüyor.

### Temizlik — eklenen = silinen · **DOĞRULANDI**

Enjeksiyon paylaşılan bir toplama penceresini süpürdü (39 satır: 3 sahtem +
36 bekleyen tohum). Elle DB cerrahisi değil, ORM + kütüphane fonksiyonuyla
temizlendi:

- **3 sahte `Media RUM Sample` satırı** `frappe.delete_doc` ile silindi →
  `kalan sahte satir: 0`. **Eklenen 3 = silinen 3.**
- Kirlenen toplama shard'larım (`media-10313/17788/17799`) dosya olarak
  düşürüldü; audit shard'larına (`16/17/20/39`) dokunulmadı.
- **Çift-sayım önlendi:** high-water rewind'lerim, kalıcı scheduler shard'ının
  (`media-305`, saatlik cron oturum sırasında doğal koştu) zaten 12:48:24'e
  kadar saydığı satırları bir sonraki koşumda yeniden saydırabilirdi. High-water
  en yeni örneğe (`2026-08-20 12:48:24.673441`) ilerletildi; doğrulama toplaması
  **0 satır okudu** (idempotent, ileriye dönük çift-sayım yok).
- **Son `/metrics`:** `kategori` serisi 0, `9000/8800/9100` değeri 0, aynı 5
  seri ailesi. Tek kalan >2500 LCP serisi tohum aykırısı 12712 (benim değil).

> Şeffaflık: `/urunler` LCP p75'i tohum verisinde 196 → 484'e kaydı. Bu benim
> sahte verim DEĞİL — saatlik scheduler cron'unun oturum sırasında doğal olarak
> topladığı 6 bekleyen tohum satırının (12:15–12:48) gerçek p75'i. Kalıcı
> daemon'un bellek-içi registry'si dışarıdan sıfırlanamaz (daemon restart'ı
> kapsam dışı); bu drift meşru scheduler ilerlemesidir, enjeksiyon izi değil.

---

## Sahiplik / dokunulan dosyalar

- **Etiketler** (test adı başına, assertion'a dokunulmadı):
  `admin-panel/frontend/src/lib/media/crop/__tests__/cropSafeArea.test.js`,
  `.../cropPolicy.test.js`, `admin-panel/frontend/src/utils/__tests__/dateFormat.test.js`
- **Matris:** `docs/test/traceability.md` (yeniden üretildi, `--check` yeşil)
- **Doğrulama betiği:** `scripts/verify_media_alerts.py` (yeni)
- **`media-alerts.yml`:** düzeltme GEREKMEDİ — şema temiz, 0 drift, uydurma
  metrik yok. Ölü alarmlar dosyanın kendi header'ında zaten dürüstçe
  işaretliydi; bu rapor onları çağrı-yolu vs toplayıcı ekseninde sınıflandırdı.
- Commit YOK · üretim kodu YOK · `hooks.py` YOK · frontend üretimi YOK.

## Özet

| Kalem | Durum | Ölçüm |
|---|---|---|
| 1 — kalan etiketler | YAPILDI | kapsama 83→86 (%41,1→%42,6); +3 gereksinim (FR-023/024, NFR-052); matris `--check` yeşil; vacuity kanıtlı |
| 2 — alarm zinciri | YAPILDI | YAML+şema temiz, 0 drift; 18 kuraldan 3 CANLI + 1 guard'lı + 14 ölü (9 trafik-bekliyor / 5 toplayıcı-eklenmeli); tetiklenme 2 bağımsız kanıtla gösterildi; sahte veri eklenen=silinen (3=3), `/metrics` temiz |
