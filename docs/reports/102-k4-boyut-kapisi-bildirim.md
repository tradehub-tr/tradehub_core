# 102-K4 — Panel yükleme boyut kapısı + satıcı backfill bildirimi

İki iş. Her ikisi de **önce ölçüldü**, kod ondan sonra bağlandı. Kapsam dışına
çıkılmadı; yasak alanlara (i18n locale, hooks/patch, docker, MediaUploader
çekirdeği) dokunulmadı.

---

## İş 1 — dropzone + PickerModal asgari-boyut kapısı

### Ölçülen durum (önce)

- İki yükleme girişi — sayfa-içi dropzone (`MediaLibraryView.vue:1499`
  `useDropzone → store.enqueueUploads`) ve PickerModal
  (`:714 @upload="store.enqueueUploads"`) — ve ayrıca dosya-seçici
  (`onFileInput`, `:1681`) hepsi `stores/media.js` `enqueueUploads` →
  `utils/uploadPolicy.js` `precheck` yolundan geçiyordu.
- `precheck` yalnız **ad / boş / uzantı / max-byte / tehlikeli**e bakıyor;
  **asgari-boyut (kısa kenar / alan) kapısı YOK.**
- Asıl kapı (`lib/media/upload/preflight.js:268` `SHORT_EDGE_TOO_SMALL` /
  `AREA_TOO_SMALL`) yalnız `useMediaUpload → MediaUploader.vue` yolunda vardı.
  Sunucu küçük görseli reddediyor (rapor 78 · W7-3, 417) ama bu iki giriş
  istemcide hiç ölçmediği için dosya **boşa yükleme turluyordu**.

### Yapılan

Ölçümü **kopyalamadan** var olan `preflight.js`/`probe.js` yolu yeniden
kullanıldı:

1. **`stores/media.js`**
   - `enqueueUploads(files, { slotKey })` — opsiyonel `slotKey` aldı.
   - `boyutKapisi(file, slotKey)` — yalnız `slotKey` verildi **ve** dosya
     görselse `runPreflight(file, {slotKey})`'i çağırır (ölçüm işçisi yoksa
     ana-iş-parçacığı başlıktan-boyut yedeği koşar), asgari-boyut engeli varsa
     `{code, params}` döndürür. Slot verilmezse **bugünkü davranış** (erken
     dönüş). Ölçüm çökerse `null` (reddetmez, sunucu bakar).
   - Kapının baktığı sebepler bilinçli olarak **yalnız** `short_edge_too_small`
     + `area_too_small` (preflight.js:268'in "asıl kapısı"). **`ratio_not_allowed`
     DIŞARIDA** — sayfa dropzone'u genel kütüphaneye yüklüyor (slot seçimi yok);
     orada oran dayatmak, satıcının banner için bıraktığı geniş görseli
     yanlışlıkla keserdi. Oran kapısı slot BEYAN EDEN `MediaUploader` yolunda
     olduğu gibi kalır.
   - Kapı yalnız görsele bakar; video/PDF asgari **görsel** boyutuna tabi değil.
2. **`MediaLibraryView.vue`** — üç çağıran da seçili slotu (`uploadSlotKey`,
   varsayılan `product.image`) geçirir: dropzone (`:1499`), PickerModal
   (`@upload`, `:714`), dosya-seçici (`onFileInput`, `:1681`).
3. **`MediaUploadQueue.vue`** — `errorText` fallback'i genişletildi: kapının
   sebep kodları (`short_edge_too_small`, `area_too_small`) **zaten çevrili**
   olan `media.preflight.reason.*`'a düşer. **Yeni i18n anahtarı EKLENMEDİ**
   (locale yasak); slot yükleyiciyle aynı metin paylaşılıyor — kullanıcı
   ekranda "Çözünürlük yetersiz: kısa kenar 900, gereken en az 1000." görür.

`product.image` slot asgarisi `minShortEdge: 1000` (vendor manifest) → 900 düşer,
1200 geçer.

### Ölçüm (sonra) — vacuity dâhil

Test: `admin-panel/frontend/src/stores/__tests__/mediaUploadSizeGate.test.js`
(Vite SSR + sahte api; PNG başlığından boyut).

- **900×900 + slot** → satır `error`, `errorCode=short_edge_too_small`,
  `errorParams={measured:900, limit:1000}`, **0 `upload_media` isteği**.
- **1200×1200 + slot** → satır `uploading` (kapıdan geçti).
- **VACUITY** — 900×900 **slotsuz** → `uploading` (bugünkü davranış). Kapı
  kaldırılırsa küçük görsel yine turlar → ilk test kırmızıya döner.
- Küçük "görsel boyutlu" PDF + slot → boyut kapısına takılmaz.

Sonuç: `node --test` **910 test, 905 pass, 5 skip (mevcut), 0 fail**. Değişen
dosyalarda `eslint` **0**.

**Durum: YAPILDI.**

---

## İş 2 — satıcı backfill bildirimi

### Ölçülen durum (önce)

`media/pipeline/migration/backfill.py` `SellerNotice` üretiyor ama
`NotificationSink` yalnız Protocol (`:144`); **somut adaptör yoktu**,
`notifier=None`, `run(notify=False)`. Backfill bir satıcının medyasını standarda
uyarladığında satıcı **haber almıyordu** (rapor 98).

### Yapılan

`build_notices` mantığı **kopyalanmadı**; yalnız kanal bağlandı:

- **`PlatformNotificationSink`** (backfill.py §9, üretim adaptörleri arasında).
  Her `SellerNotice`'i `utils/notify.py::notify` çağrısına sarar:
  `store → user` eşlemesi `Admin Seller Profile.user` üzerinden
  (`media/ownership.py:79` ile **aynı** eşleme). `reference_doctype="Admin
  Seller Profile"`, `type="system"`, `send_email` opsiyonel.
  - `frappe`/`notify` **yalnız çağrı anında** import edilir — modül düzeyi
    frappe bağı yok (KatmanDisiplinTesti korunur, `FrappeBatchRunner` ile aynı
    gerekçe).
  - Sahibi çözülemeyen mağaza (boş `store` / profilsiz) sessizce düşmez,
    `skipped` olarak SAYILIR.
  - Test için `notify_fn` / `resolve_user_fn` enjekte edilebilir (canlı site
    gerekmeden doğrulanır) — `FrappeBatchRunner.enqueue_fn` deseni.
- **Bağlama yolu:** var olan constructor + `run(notify=True)` yolu. Üretimde
  `BackfillOrchestrator(runner=FrappeBatchRunner(),
  notifier=PlatformNotificationSink(send_email=...))` + `orch.run(plan,
  dry_run=False, notify=True)`. Varsayılan hâlâ güvenli (`notifier=None`,
  `notify=False`).

> **i18n notu:** Bu modül bench/site olmadan import edilebilir kalmalı, bu yüzden
> `frappe._()` çağrılamaz. Panel başlığı (`NOTICE_TITLE`) mevcut `B_CLASS_MESSAGES`
> ile aynı gerekçeyle **düz Türkçe**; asıl yerelleştirme `notify()`/e-posta
> şablonu katmanının işi. Bu, "çıplak string yasak" kuralının bu dosyadaki
> KatmanDisiplin invariantına verdiği yer — bilinçli ve raporlanmıştır.

### Ölçüm (sonra) — vacuity dâhil

Test: `tradehub_core/tests/test_migration_backfill.py`
(`PlatformBildirimSinkTesti`, enjekte edilmiş kaydedici — canlı site gerekmez):

- Bildirim satıcıya `notify()` ile düşer; zarf doğru (`recipient_user`,
  `reference_doctype/name`, `message`, `title` dosya adını taşır, `type=system`,
  `send_email=False`), `sent=1`.
- Sahipsiz mağaza → notify **edilmez**, `skipped=1`.
- `send_email=True` → notify'a iletilir.
- **≤5 dosyalık koşum + sink bağlı** (`run(notify=True)`) → her B bildirimi
  düşer (`sent=2`).
- **VACUITY** — `notifier=None` + `run(notify=True)` → bildirim üretilir ama
  **gitmez** (`rapor.notices==2`, kanal kopuk). Sink `None` = bildirim yok =
  test kırmızı.

**Konteyner ölçümü (gerçek frappe, `istoc.localhost`):**
`PlatformNotificationSink(send_email=True)` gerçek bir satıcıya (`W9Of9a921` /
`w9probe-other-f9a921@t.local`) uygulandı:

- **Platform Notification satırı DÜŞTÜ** — `NOTIF-2026-03845`, `type=system`,
  `reference_doctype=Admin Seller Profile`, `reference_name=W9Of9a921`,
  `channel=email`, doğru `recipient_user`.
- **E-posta kuyruğa GİRDİ** — Email Queue 30 → 31.
- `sink.sent=1, skipped=0`. Smoke satırı ve modülü sonrasında temizlendi.

Test koşumu: `python -m unittest tradehub_core.tests.test_migration_backfill`
→ **55 test OK** (host + konteyner Python 3.11.6). `py_compile` temiz.
(ruff ne host'ta ne konteynerde kurulu — çalıştırılamadı; kod mevcut tab-indent
+ satır uzunluğu konvansiyonuna elle uyduruldu.)

**Durum: YAPILDI.**

---

## Değişen dosyalar

**İş 1 (FE)**
- `admin-panel/frontend/src/stores/media.js` — `enqueueUploads(slotKey)` +
  `boyutKapisi` + importlar.
- `admin-panel/frontend/src/views/seller/MediaLibraryView.vue` — üç çağıran
  slotu geçirir.
- `admin-panel/frontend/src/components/media/MediaUploadQueue.vue` — `errorText`
  `preflight.reason.*` fallback'i (yeni i18n anahtarı yok).
- `admin-panel/frontend/src/stores/__tests__/mediaUploadSizeGate.test.js` — yeni.

**İş 2 (BE)**
- `tradehub_core/tradehub_core/media/pipeline/migration/backfill.py` —
  `PlatformNotificationSink` + `NOTICE_TITLE` / `NOTICE_TYPE`.
- `tradehub_core/tradehub_core/tests/test_migration_backfill.py` —
  `PlatformBildirimSinkTesti` (5 test).

## Notlar / sınırlar

- `MediaUploadQueue.vue` sahiplik listesinde adı geçmiyordu ama sayfa-içi
  kuyruğun tek görüntüleyicisi; değişiklik minimal (yalnız fallback zinciri) ve
  yasak listede değil.
- Konteyner backend imajı **bind-mount değil** (baked); testler için düzenlenmiş
  dosyalar `docker cp` ile kopyalanıp koşuldu. Canlı konteyner FS'i böylece
  geçici olarak güncel; imaj rebuild'inde eski hâline döner.
- Süre iddiası yok.
