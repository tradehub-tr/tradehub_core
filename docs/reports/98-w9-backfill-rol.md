# 98 — W9: Backfill uygulaması/izleme (T-143) + rol yükseltme testleri (T-135)

Tarih: 2026-08-20 · Site: `istoc.localhost` (istoc-dev-backend-1) · Kaynak
şartname: `~/Desktop/imageoptimization/docs/72-faz14-test-kabul.html` T-143,
devir: rapor 87 (W7-4) + rapor 57 (T-028 devre kesici).

> **ÖNCE ÖLÇ.** Tam korpus backfill YAPILMADI (operasyon kararı, runbook'ta).
> Küçük gerçek parti (18 dosya) koşuldu; izleri aşağıda listeli, SİLİNMEDİ.

---

## Kalem 1 — T-143 backfill (uygulama + izleme)

### Ölçüm: bugün kaç dosya türevli / türevsiz

| Metrik | Değer | Kaynak |
|---|---|---|
| tabFile toplam | **5.091** | `SELECT COUNT(*) FROM tabFile` |
| `th_optimized_at` damgalı (optimize edilmiş) | **14 → 39** | koşum öncesi 14; W9 partisinden sonra 39 |
| görsel (jpg/png/webp) File | **4.842** | `LOWER(file_url) REGEXP` |
| Media Asset / Version / Rendition | **52 / 50 / 490** | boru hattı katmanı |
| Asset başına kaynak File (distinct) | 52 | `DISTINCT source_file` |

**Sonuç:** boru hattı katmanı (Asset/Rendition) rapor 94'teki 13/92'den
52/490'a çıkmış ama tabFile'ın **büyük çoğunluğu hâlâ türevsiz** — 4.842
görselin yalnızca ~39'u optimize damgalı. Backfill'in asıl işi (içerik
standardizasyonu M-A) devasa; bu yüzden TAM koşum operasyona bırakıldı.

### (a) Toplu backfill iş fonksiyonu — **ZATEN VAR**, devre kesici **ZATEN İÇİNDE**

`useMediaOptimize` → `tradehub_core.api.media_admin` uçlarına bağlanıyor
(`start_image_optimization` → `frappe.enqueue("...media.runner.run_batch")`).
Bu **panel ad-hoc optimize** yoludur: tek job, `queue="long"`, timeout 3600,
parti içi devre kesici YOK (yalnız hata log'u).

T-143 **backfill orkestratörü** ayrı ve DAHA GÜÇLÜ:
`tradehub_core/media/pipeline/migration/backfill.py` (863 satır, 18 Ağu imajında).
Rapor 57'nin "T-028 devre kesici eksik" bulgusu bu modülle **eskimiştir** —
kesici mevcut ve testli:

| Şartname T-143 maddesi | Karşılığı (backfill.py) | Durum |
|---|---|---|
| parti parti, düşük öncelikli kuyruk | `BackfillConfig.batch_size=200`, `queue="media_backfill"` (canlı `long`'dan AYRI; aynıysa `__post_init__` reddeder) | ✅ |
| ilerleme/hata oranı/tahmini bitiş panoda | `BackfillOrchestrator.dashboard()` → processed/optimized/skipped/errors/error_rate/eta/per_slot | ✅ |
| **hata oranı %2 aşılırsa otomatik dur** | `StopPolicy.error_rate_max=0.02`, `evaluate_stop()` her batch sonrası; aşılırsa `RUN_HALTED`, kalan batch enqueue EDİLMEZ | ✅ **(devre kesici)** |
| canlı trafik koruması | `LiveTrafficGuard` §5.3: canlı kuyruk derinliği > eşik → duraklat | ✅ |
| atomik geçiş (404 yok) | `AtomicSwitch` — ya tüm eski ya tüm yeni küme, yarım asla | ✅ |
| resume / devam etme | **DE FACTO** — `inventory.pending_file_names` optimize edilmişi dışlar; `run(..., max_batches=N)` kademeli | ⚠️ (orkestratör-durum checkpoint'i yok; dosya seçimi düzeyinde resume) |

**İkincil kesiciler de var** (§7.3): `file_missing`/`decode_failed` oranı %1'i
aşarsa dur; ilerleme kaydı TTL dolup `not_found` olursa "geçti SAYILMAZ" → dur.

Devre kesici **eksik olmadığı için EKLENMEDİ** (gold-plating'den kaçınıldı).
Bilinen sınır dürüstçe: `runner.run_batch` batch ORTASINDA abort etmez — en
kötü durumda eşik aşılsa bile bir batch (≤200) dolusu işlenir. Bu bilinçli bir
tasarım (batch küçük tutulur), orkestratör docstring'inde ve
`StopDecision.already_processed` alanında saklanmaz.

### (b) Küçük GERÇEK parti (18 dosya) — **YAPILDI**, izleme ölçüldü

Konteynerde, orkestratör üzerinden (kesici/pano yolu aynen çalıştı). Kuyruk
adaptörü: bu compose'ta `media_backfill` kuyruğunu dinleyen worker YOK
(worker cmd: `long,default,short`), bu yüzden süreç-içi `InlineRunner` kullanıldı
— orkestratörün ölçüm/durdurma yolu değişmedi.

**Dry-run (18 dosya, 2×9 batch):**
```
processed=18 optimized=18 skipped=0 errors=0 error_rate=0.0
original=139.158.947 B → new=22.951.216 B (~%83,5 kazanç, kuru)
live_checks: [{queue:long, depth:0, clear:true, measured:true} ×2]
avg_seconds_per_file≈1.29  eta=0  state=completed
```

**Wet-run (aynı 18 dosya):** aynı sayılar, `dry_run=false`, diske yazıldı,
`state=completed`, halt YOK. DB doğrulaması (kalıcılık kanıtı):
```
5c1d29531a: file_size 5.655.452  th_original_size 18.063.624  th_optimized_at 2026-08-20 12:43:07
a08c1ebd76: file_size   489.038  th_original_size 17.889.888
6e1f0de06e: file_size   487.053  th_original_size  4.360.755
```

**Resume/idempotency kanıtı:** aynı 3 dosya tekrar `run_batch`'e verildi →
`optimized=0 skipped=3 skip_reasons={"already_optimized":3}`. Gate
(`th_optimized_at` dolu) ikinci koşumu atlıyor → tekrar-koşum güvenli.

**Backfill izleri (SİLİNMEDİ):** yukarıdaki 18 dosya optimize edilmiş halde;
`th_optimized_at` damgalı satır 14→39 (bir file_url'i paylaşan çoklu File
satırı `_update_metadata` ile birlikte damgalandığı için +18'den fazla).
job_key'ler: `backfill-0001`, `backfill-0002`, `backfill-resume-kaniti`.

Seçilen 18 dosya (temsilci `File.name`): `5c1d29531a, a08c1ebd76, 74a62b2bba,
9d30304018, 57573101a9, 0b23a22e47, 73f7615b50, 853fb81f32, 4cf8d01675,
b79a483c68, c91ad40dc0, b4689f1404, 0dd274720a, 4e386cf796, 854f4b266f,
8421c31cca, abbd23a198, 6e1f0de06e`.

Orkestratör birim süiti konteynerde: **`test_migration_backfill` 50/50 OK**
(kesici testleri dahil: `test_esik_asilinca_kalan_batchler_enqueue_EDILMEZ`,
`test_durdurma_kaydinda_ISLENMIS_dosya_sayisi_var`).

### (c) Satıcı bildirimi — **BAĞLANMAMIŞ**, gereken tek bağlantı raporlanıyor

Bildirim **üretiliyor ama teslim edilmiyor**:
- `build_notices(plan)` B-sınıfı dosyalardan `SellerNotice` (store, file_name,
  slot, subclass, message, deadline_days=30) üretir. ✅
- `orchestrator.run(..., notify=True)` bunları `NotificationSink.notify()`'a
  yollar. Ama `NotificationSink` yalnız bir **Protocol** — somut uygulama YOK.
  `grep` ile doğrulandı: `backfill.py` dışında hiçbir yerde `SellerNotice`/
  `build_notices`/`NotificationSink` import EDİLMİYOR, `notifier=None`.

Mevcut bildirim altyapısı hazır: `tradehub_core/utils/notify.py::notify(...)`
(Platform Notification kaydı + opsiyonel `frappe.sendmail`). `Admin Seller
Profile.user` alanı var (store→user çözümü mümkün).

**Gereken TEK bağlantı** (hooks yasak olduğu için burada raporlanıyor,
implement edilmedi) — bir `NotificationSink` adaptörü:

```python
# tradehub_core/media/pipeline/migration/notify_sink.py (ÖNERİ)
from tradehub_core.utils import notify as _notify
import frappe

class PlatformNotificationSink:
    def notify(self, notice) -> None:
        user = frappe.db.get_value("Admin Seller Profile", notice.store, "user")
        if not user:
            return  # sahibi çözülemeyen B-dosyası: build_notices store="" ile döner
        _notify.notify(
            recipient_user=user,
            type="media_backfill",
            title=_("Medyanız yeni görüntü standardını karşılamıyor"),
            message=f"{notice.message} (slot: {notice.slot}) — "
                    f"düzeltme için {notice.deadline_days} gün.",
            reference_doctype="File", reference_name=notice.file_name,
            send_email=True,  # T-143: panel bildirimi + e-posta
        )
```
Koşumda `BackfillOrchestrator(runner=..., notifier=PlatformNotificationSink())`
+ `run(..., notify=True)`. Bu ~15 satır tek dosya, hook GEREKTİRMEZ (orkestratör
zaten `_send` çağırıyor). **Sahiplik gereği implement edilmedi, raporlandı.**

---

## Kalem 2 — T-135 rol yükseltme testleri

### Ölçüm: mevcut süitler hangi yükseltme senaryolarını kapsıyordu

| Senaryo | Mevcut kapsam | Boşluk |
|---|---|---|
| çapraz-kiracı okuma (IDOR) | `test_payment_transaction_isolation`, `test_file_multirow_isolation`, `test_media_*` query_conditions | kapalı |
| permlevel ŞEMA (statik) | `test_payment_iban_permlevel` (IBAN pl1), `test_faz13_guest_surface::MediaAssetPermlevelTests` (8 alan pl≥1) | kapalı (ama motor DEĞİL, JSON) |
| **aynı-kiracı düşük→yüksek rol tırmanma (MOTOR)** | — | **rapor 87 W7-4: "bench-bağımlı, YAZILMADI"** |

Rapor 87 somut öneriyi bıraktı: "Seller rolüyle Media Asset moderasyon alanını
yaz → permlevel'in API/model katmanında da tuttuğunu ölç." Bu boşluk kapatıldı.

### Yazılan: `tests/test_role_escalation.py` — **YAPILDI** (bench-bağımlı, 15 test, 15/15 OK)

Konteynerde: `run-tests --module tradehub_core.tests.test_role_escalation` →
**Ran 15 tests OK (8,7 s)**. FrappeTestCase; gerçek DB + gerçek izin motoru.
Frappe-siz CI kapısına (`run_authz_tests.sh`) EKLENMEDİ — o kapı stub/frappe-siz;
bu süit gerçek site ister (rapor 87'nin öngördüğü sınır).

**Ölçülen mekanizma** (`frappe/model/document.py:783 validate_higher_perm_levels`):
permlevel>0 alanına yazma yetkisi olmayan kullanıcının değişikliği SESSİZCE eski
değere geri alınır (exception atmaz). Administrator/`ignore_permissions` muaf →
fixture'lar admin ile kurulur, tırmanma DÜŞÜK yetkili `set_user` + düz `save()`
ile denenir (üretim API yolu).

Kapsanan senaryolar:

1. **Media Asset (satıcı, KENDİ varlığı, pl1 moderasyon alanı):**
   - `state` draft→ready (moderasyon atlama) → **geri alındı**, draft kaldı
   - `legal_hold` 1→0 (yasal saklama sökme) → **geri alındı**
   - `rejection_code` silme → **geri alındı** (B5 kaldı)
   - `owner_seller` başka mağazaya devir → **PermissionError**, sahiplik değişmedi
2. **Media Folder (ölçüm bulgusu):** permlevel-1 alanı YOK **ve** DocPerm
   matrisinde `create` yalnız System Manager'da; Marketplace Admin salt-okur;
   Marketplace Seller matriste HİÇ YOK → satıcı KENDİ mağazası için bile klasör
   oluşturamaz (DocType düzeyi blanket red). Tırmanma yüzeyi yok; iki eksen de
   pinlendi. (İlk taslakta "kendi mağaza klasörü açılır" varsayımı YANLIŞTI,
   ölçümle düzeltildi.)
3. **Payment Transaction IBAN (pl1) — daha keskin sınır:** Marketplace Admin
   pl0'da YAZAR ama pl1'de yalnız OKUR → `seller_iban` değiştirme **geri alındı**
   (orijinal IBAN kaldı); `get_permlevel_access("write")` → `1 ∉ küme` doğrulandı.
4. **Rol atlama:** satıcı kendi User'ına `System Manager` / `Marketplace Admin`
   ekleme → **sessizce düştü** (roller değişmedi).

### Vacuity — ZORUNLU, iki katman

**(i) Suite-içi kontrol yolları** (her sınıfta `test_VACUITY_*`, hepsi yeşil):
aynı yazımı yetkili yol (admin / `ignore_permissions` / pl0-alan) yapınca
DEĞİŞİM GERÇEKLEŞİR — "değişmedi" iddiaları korumadan gelir, yazılamaz alandan
değil.

**(ii) Kapı gevşetme kanıtı** (ayrı ölçüm, `bench execute` ile koşuldu, fixture
temizlendi): TEK değişken izole edildi — Media Asset `state` yazımında
`get_permlevel_access("write")` kümesine pl1 eklendi (pl0 write/sahiplik AYNEN):
```
SIKI_state   = draft   (pl1 gate KAPALI → tırmanma reddedildi)
GEVSEK_state = ready   (pl1 gate AÇIK   → tırmanma BAŞARILI)
VACUITY = GEÇERLİ — suite kapıya duyarlı
```
Yani kapı gevşetilince yükseltme başarılı oluyor → ilgili assert kırmızıya
dönerdi. Süit kör değil. (Not: Custom DocPerm ile gevşetme denendi ama Frappe
Custom DocPerm eklenince STANDART perm matrisini tümüyle değiştiriyor → pl0
write de düşüyor; bu yüzden gate `get_permlevel_access` düzeyinde izole edildi.)

---

## Özet tablo

| Kalem | Durum | Kanıt |
|---|---|---|
| Backfill iş fonksiyonu + devre kesici (%2) | **ZATEN** (rapor 57 eskidi) | `backfill.py` + `test_migration_backfill` 50/50 |
| Küçük gerçek parti + izleme | **YAPILDI** | 18 dosya wet-run, DB damgaları, resume skip kanıtı |
| Satıcı bildirimi bağlantısı | **YAPILAMADI (kasıtlı)** | Sink Protocol var, adaptör YOK — 15 satırlık bağlantı raporlandı (hooks yasak) |
| Rol yükseltme testleri | **YAPILDI** | `test_role_escalation` 15/15 OK, vacuity 2 katman |

## Sınırlar / açık kalanlar (dürüstçe)

- **Tam korpus backfill koşulmadı** — operasyon kararı; kod hazır, kesici testli,
  runbook koşumu kullanıcıda (`dry_run=True` varsayılan; ilk gerçek koşum
  `FrappeBatchRunner` ile bench'te doğrulanmalı).
- **`media_backfill` kuyruğunu dinleyen worker yok** (compose worker cmd
  `long,default,short`) — üretim koşumundan önce ayrı düşük-öncelikli worker
  gerekir; aksi halde `FrappeBatchRunner.enqueue` iş sonsuz bekler. Küçük parti
  bu yüzden süreç-içi `InlineRunner` ile koşuldu.
- **Bildirim teslimi bağlanmadı** (yukarıdaki adaptör) — B-sınıfı satıcılar
  şu an haber ALMAZ.
- **`test_role_expalation` CI stub kapısında değil** — bench gerektirir; gecelik
  bench run-tests'e dahil edilmeli.
- Container'a kopyalanan geçici koşum modülleri (`w9_*.py`) temizlendi; host
  repo'ya yalnızca `tests/test_role_escalation.py` + bu rapor eklendi.
