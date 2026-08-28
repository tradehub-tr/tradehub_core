# MOGEM-617 — Media Engine Faz 0–14 kapanış denetimi

Durum: **IN PROGRESS — teknik kabul paketi hazır, nihai kabul açık**  
Denetim tarihi: 2026-08-24  
Kapsam: Faz 0–14, T-140…T-145 ve 102 görevlik Media Engine şemsiyesi

Bu rapor, görev durumunu yalnız kodun varlığına göre değil, MOGEM-617 içindeki
ölçülebilir kapanış kapılarına göre verir. Gerçek satıcı pilotu, üretim rollout'u
ve yetkili imzası yapılmadan görev `Done` sayılmaz.

## 1. Kapanış kapıları

| Kapı | Sonuç | 2026-08-24 kanıtı | Done için kalan |
|---|---|---|---|
| T-140 — FR/NFR ve invariant izlenebilirliği | **KISMİ** | Üretilen matris güncel; 202 FR/NFR'nin **87'si bağlı, 115'i açık**. INV-01…INV-12 **12/12 bağlı**. `python3 scripts/gen_traceability.py --check` geçiyor. | `--fail-uncovered` sıfırla dönene kadar 115 açık gereksinimin kod/test karşılığını kapat. |
| T-141 — 12 kritik E2E senaryosu | **TAM (yerel kabul ortamı)** | S1…S12 admin paneli, vitrin ve motor katmanına dağıtıldı. Admin Playwright **25/25**, vitrin Playwright **11/11**, Python motor senaryoları **32 geçti / 2 gerekçeli skip**. Başarılı UI adımlarında ekran görüntüsü ve video açık. | Üretim kabulüne taşınırken aynı paket staging seed'i üzerinde yeniden koşturulacak. |
| T-142 — ≥10 gerçek satıcılı UAT | **AÇIK — İNSAN** | Crop Studio, önizleme/simülatör, slot-aware uploader ve küçük-görsel ret akışı teknik olarak hazır. Anonim/onamlı oturum ve bulgu şablonları ile sözleşme doğrulayan kabul hesaplayıcısı **5/5** testten geçti. Gerçek satıcı ölçümü yapılmadı. | En az 10 satıcı × en az 5 ürün; açık rıza ve moderatör ölçümü; araçla anlama oranı ≥%90; kritik bulgular kapalı. |
| T-143 — gerçek veri backfill / rollback | **KISMİ** | Sürümlü ve imzalı plan, dry-run onayı, düşük öncelikli batch, checkpoint, canlı kuyruk bekleme, hata oranı >%2 otomatik duruş, doğrulama ve exact rollback uygulandı. Migration runtime **10/10** geçti; gerçek JPEG ile dry→wet→validate→byte-exact rollback provası yeşil. | Üretim/veri sahibi onayıyla gerçek veri planı, bildirim, ölçümlü tam koşum ve üretim rollback kaydı. |
| T-144 — canary ve go-live | **KISMİ** | Belirlenimci canary + `%10 → %50 → %100` kapsamı master-kill, worker/lazy kapıları ve manifest ham fallback'iyle uygulandı. Yerel kontrol düzlemi **1,947 ms** ölçüldü, ayarlar geri yüklendi; rollout entegrasyonları ve DR provası yeşil. | Üretimde 0→10→50→100 rollout, canlı metrik gözlemi, süreli rollback tatbikatı, on-call/escalation teyidi. |
| T-145 — nihai kabul | **AÇIK — İNSAN** | Kapanış raporu ve imza taslağı hazır. | Açık bulgulara sahip/tarih, operasyon devri ve eğitimi, erişim teyidi, QA/geliştirme/platform imzaları. |

**MOGEM-617 sonucu:** `Backlog`'dan `In Progress`'e alınabilir; **Done kapısı
geçmedi**. Teknik paket T-141'i kapattı ve T-143/T-144'ü güvenli prova
seviyesine getirdi. T-140, T-142, üretim T-143/T-144 ve T-145 zorunlu olarak
açıktır.

## 2. Bu kapanış çalışmasında teslim edilenler

### Depolama ve canlı aynalama

- `File` ekleme/silme kancaları üzerinden RQ sonrası S3/MinIO aynalama bağlandı.
- İçerik tabanlı deterministik iş kimliği ve tekrar çalıştırma güvenliği eklendi.
- S3'ten dönen nesne referansı beklenen anahtarla eşleşmiyorsa başarı sayılmıyor.
- Superadmin depolama ekranına S3, path-style ve original/rendition anahtarları
  bağlandı; satıcı rolü bu ayarlara erişemiyor.
- Canlı akışta “superadmin S3'ü açar → satıcı yükler → nesne hem yerelde hem
  MinIO'da görülür → test temizliği yapılır” senaryosu koşturuldu.

### Migration / backfill güvenliği

- Plan şeması ve SHA-256 özeti, dry-run onayı ve dry/wet plan eşitliği eklendi.
- Kalıcı run/batch kayıtları, checkpoint, durdur/devam et, batch muhasebesi,
  doğrulama ve ters sırada exact rollback sağlandı.
- Canlı medya kuyruğu doluyken batch başlamıyor; hata oranı `%2`yi aşınca
  otomatik duruyor.
- Rollback penceresinde arşiv temizliği fail-closed tutuluyor.
- 2800×1800 gerçek JPEG üzerinde disk + DB kullanan kontrollü prova, dosyanın
  rollback sonunda SHA-256 düzeyinde ilk hâline döndüğünü doğruladı.

### Kabul otomasyonu ve kanıt üretimi

- T-140 üreticisi SRS gereksinimlerine ek olarak INV-01…INV-12'yi ve recursive
  Python/FE testlerini tarıyor; `A/C/F/I` dışındaki zayıf izleri kapsam saymıyor.
- Playwright başarılı koşumlarda da screenshot/video saklıyor.
- Eski, gerçekte uygulanmış özellikleri “eksik” gösteren altı senaryo skip'i
  kaldırıldı. Kalan iki skip yalnız gerçek insan algısı/UAT ve gerçek cihaz/ağ
  LCP ölçümünü ifade ediyor.
- MinIO kabul testlerinin birbirinin nesnelerini görmesine yol açan sabit anahtar
  izolasyon kusuru giderildi; her test benzersiz prefix kullanıyor ve temizliyor.

### Aşamalı yayın güvenliği

- Canary mağaza listesi yüzdeden önce uygulanıyor; mağaza seçimi SHA-256 tabanlı
  kararlı kovadır ve yüzde büyüdükçe kapsam monoton genişler.
- Kısmi rollout'ta sahipliği çözülemeyen medya fail-closed kalıyor. Kapsam dışı
  satıcı ham manifest alıyor; worker, lazy image, animation ve video yolları yeni
  iş/türev üretmiyor.
- Ana şalter canary dahil bütün hattı kesiyor. Yeni DocType alanları migrate patch'i
  ile geriye uyumlu `%100` varsayılanına taşındı; güvenli canary sırası runbook'a
  `rollout_percent=0` master'dan önce yazılacak biçimde işlendi.

## 3. Son doğrulama özeti

| Paket | Sonuç | Not |
|---|---:|---|
| Admin Playwright tam paket | **25/25 geçti** | 20 PNG + 20 WebM kanıtı; API-only testler görsel üretmez. |
| Storefront kritik medya Playwright | **11/11 geçti** | 9 PNG + 9 WebM kanıtı; backend-yardımcılı iki senaryonun UI eşleri ayrıca var. |
| Python kritik motor senaryoları | **32 geçti, 2 skip** | 34 toplam; iki skip insan UAT'ı ve gerçek cihaz/ağ LCP ölçümüdür. |
| Frappe pipeline bridge entegrasyonu | **45/45 geçti** | İlk manifest isteğinde lazy üretim, ikinci istekte persistent cache-hit, iki eşzamanlı istekte singleflight ve mağaza rollout kapısı dahil. |
| Frappe rollout/manifest/video entegrasyonu | **62/62 geçti** | Bayrak 20/20, manifest 13/13, video 29/29; canary, monoton yüzde, raw fallback ve master-kill dahil. |
| Frappe retention/soft-delete entegrasyonu | **44/44 geçti** | Türevin soft-delete edilmesi, grace içinde atomik geri alınması ve onaylı kalıcı purge kapısı dahil. |
| Storage unit/contract | **147/147 geçti** | Yerel, S3, mirror ve tiered adaptör davranışı. |
| Frappe mirror runtime | **9/9 geçti** | File hook, deterministik iş, reconcile ve nesne referansı doğrulaması. |
| Gerçek MinIO kabul paketi | **15/15 geçti, 0 skip** | Local, S3, mirror ve tiered kipleri. |
| Migration runtime | **10/10 geçti** | Kontrollü gerçek dosya dry/wet/validate/rollback dahil. |
| UAT sözleşme/kabul hesaplayıcısı | **5/5 geçti** | Anonim kod, onam, süre/kanıt, ≥10 satıcı, ≥%90 anlama ve kritik bulgu kapısı. |
| İzlenebilirlik üretici güncellik kapısı | **geçti** | `docs/test/traceability.md` yeniden üretilebilir ve güncel. |
| İzlenebilirlik tam-kapsam kapısı | **kaldı** | 87/202 FR/NFR bağlı; 115 açık. |

Kanıt dizinleri çalışma ağacında şunlardır:

- Admin: `admin-panel/frontend/playwright/evidence/`
- Storefront: `tradehubfront/playwright/evidence/`
- Gereksinim matrisi: `docs/test/traceability.md`
- Migration işletim kılavuzu: `docs/runbooks/media-migration.md`
- DR provası: `docs/reports/100-t054-phase5-dr-rehearsal.md`
- Rollout/hard-kill provası: `docs/reports/101-mogem617-rollout-rehearsal.md`
- UAT saha paketi: `docs/templates/media-uat-oturum-formu.md` + iki CSV şablonu

## 4. Kalan iki dış ölçüm boşluğu

Python kritik senaryo paketindeki gerekçeli skip'ler kapanış kuyruğunu somutlar:

1. Reddedilen yükleme mesajının gerçek kullanıcı tarafından doğru anlaşılması
   (T-142 UAT ölçümü).
2. Gerçek tarayıcı/ağ koşulunda LCP ölçümü.

Seçici rendition planlama ve ilk istekte lazy/on-demand üretim artık kod ve
entegrasyon testleriyle kapalıdır. Kalan iki madde ölçüm ortamı/insan gerektirir.

## 5. Done'a geçiş kontrol listesi

- [ ] T-140: 202/202 FR/NFR bağlı ve CI `--fail-uncovered` yeşil.
- [x] T-140: INV-01…INV-12 = 12/12.
- [x] T-141: S1…S12 otomatik paket yerel kabul ortamında yeşil ve UI kanıtlı.
- [ ] T-142: ≥10 gerçek satıcı pilotu ve ≥%90 anlama oranı.
- [ ] T-143: onaylı gerçek-veri backfill'i, ölçümlü otomatik duruş/rollback.
- [ ] T-144: üretim canary 0→10→50→100 ve zamanlanmış rollback tatbikatı.
- [ ] T-145: bulgu sahipleri/tarihleri, operasyon devri, eğitim ve üç imza.

Bu kutuların tamamı işaretlenmeden Plane durumu `Done` yapılmaz.
