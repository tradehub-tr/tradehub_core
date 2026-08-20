# 61c — FE Denetim: Faz 4 (Veri Modeli) ve Faz 5 (Depolama/S3/CDN)

Salt okunur denetim. Hiçbir dosya değiştirilmedi.

**Kaynak belgeler (WebFetch ile çekildi, ikisi de erişilebilir oldu):**
- `https://karacaismail.github.io/imageoptimization/docs/41-faz4-veri-modeli.html`
- `https://karacaismail.github.io/imageoptimization/docs/42-faz5-depolama-s3-cdn.html`

**Aranan yerler:** `admin-panel/frontend` (rota: `src/router/index.js`, menü: `src/data/navigation.js`, çeviri: `src/i18n/locales/{tr,en,ru,ar}.js`), `tradehubfront`, `tradehub_core` (yalnız çapraz kontrol).

---

## Tablo

| Görev | Rol | FE payı | Durum | Kanıt (dosya:satır) | Eksik olan |
|---|---|---|---|---|---|
| T-040 | Backend | Yok (DocType şema/migration/fixture işi; T-051'in ekranı ayrı sayıldı) | FE-DIŞI | `tradehub_core/tradehub_core/tradehub_core/doctype/media_storage_settings/media_storage_settings.py`, `tradehub_core/tradehub_core/tradehub_core/doctype/media_engine_settings/media_engine_settings.py` (yalnız backend) | — |
| T-041 | Backend | Var — Crop Studio UI, `Media Crop Intent`/`Media Crop Override` alanlarını (`focal_x/y`, override rect) gerçek uca yazıyor; Simülatör `previewed_placements` senkronu var | KISMİ | `admin-panel/frontend/src/composables/useCropStudio.js:491-492,556-557` (`method: "tradehub_core.api.media_crop.save_intent"`, `focal_x/focal_y` payload) · `admin-panel/frontend/src/components/media/crop/CropStudioModal.vue` → `admin-panel/frontend/src/views/seller/MediaLibraryView.vue` (mount) · backend uç: `tradehub_core/media/pipeline/api/crop.py:347` (`save_intent`) · `admin-panel/frontend/src/composables/useSimulatorApproval.js:23-57` (`previewed_placements` → `Media Crop Intent`) | Belgenin istediği "simülatör çıktısı = backend `resolve_crop` çıktısı" **golden test/parity** doğrulanamadı. Bulunan tek parity dosyası (`src/lib/media/crop/vendor/crop_geometry.ts`) T-100'e ait piksel-geometri (zoom/pan) ikizi — `resolve_crop`'un 5 seviyeli öncelik zincirini (override→safe-area+focal→global focal→akıllı öneri→merkez) yeniden üretmiyor. Bu zincirin FE tarafında bir karşılığı/parity testi bulunamadı → ÖLÇÜLEMEDİ. |
| T-042 | Backend | Aranmadı bulunamadı — "Bu dosya kütüphanenizde" tekrar-yükleme uyarısı FE'de yok | YOK | `admin-panel/frontend/src/composables/useMediaUpload.js` (dedup/sha256/duplicate araması boş sonuç) · tek sha256 referansı `admin-panel/frontend/src/lib/media/upload/sync.mjs:1-23` — bu dedup değil, build-time politika-vendor senkron script'i | Dedup uyarı UI'ı, versiyon/URL değişmezliği ile ilgili herhangi bir FE göstergesi yok. Backend modülü var (`tradehub_core/media/pipeline/core/dedup.py`) ama FE'de karşılığı yok. |
| T-043 | Backend | Kısmen var — kullanım paneli (`MediaUsagePanel`) mevcut ve gerçek uca bağlı; ama kalıcı `Media Usage` index'i değil, istek-anı taraması; öksüz dosya raporu (Orphan Report) UI'ı HİÇ yok | KISMİ | `admin-panel/frontend/src/composables/useMediaUsage.js:9,98` (`tradehub_core.api.seller_media.get_my_usage`), kod içi not (satır ~9-24): "`Media Usage` DocType'ı kalıcı kayıt değil" · `admin-panel/frontend/src/components/media/MediaDetailPanel.vue:216,331` (`MediaUsagePanel` mount) · backend orphan mantığı var ama whitelist uç yok: `tradehub_core/media/pipeline/core/usage.py:650` (`classify_orphans`), `:723` (`find_disk_orphans`), `:780` (`find_orphan_assets`) — `tradehub_core/media/pipeline/api/admin.py:90` "Saf Python — `@frappe.whitelist()` YOK" | Orphan Report ekranı (filtreleme + silme onay akışı) admin-panel'de bulunamadı; grep `orphan`/`öksüz` medya bağlamında admin-panel'de sıfır sonuç verdi. Usage paneli de belgenin istediği "last_seen damgaları" ile kalıcı index'e değil, canlı taramaya dayanıyor (kod kendi sınırını belgeliyor). |
| T-044 | Analiz | Yok — ER diyagramı, EXPLAIN, migration provası; saf backend/DB analiz belgesi | FE-DIŞI | (belge: `docs/data/data-model-review.md` — FE aranmadı, konu gereği yok) | — |
| T-050 | Backend | Yok — StorageAdapter soyutlaması (local/S3/mirror/tiered), lazy import, atomik yazma | FE-DIŞI | (backend-only; admin-panel'de StorageAdapter'a doğrudan referans yok, yalnız T-051 ekranı üzerinden `storage_mode` seçimi tüketiliyor) | — |
| T-051 | Backend/Ekran | Var — tam bir Settings ekranı: 5 bölüm, S3/CDN/imgproxy/Retention alanları, "Bağlantıyı test et" düğmesi | TAM | Rota: `admin-panel/frontend/src/router/index.js:1051-1060` (`path: "media-storage-settings"`, `roles: ["Media Superadmin"]`) · Menü: `admin-panel/frontend/src/data/navigation.js:552-558` (`requires: ["Media Superadmin"]`) · Rol kapısı FE: `src/router/index.js:1157` (`if (to.meta.roles && !auth.canAccess(to.meta.roles))`) · Rol kapısı BE: `tradehub_core/tradehub_core/doctype/media_storage_settings/media_storage_settings.py:79` (`ALLOWED_ROLES = frozenset({"Media Superadmin","System Manager"})`), `:161-170` (`only_for` reddi) · i18n 4 dilde: `mediaStorage` içerik bloğu — tr `src/i18n/locales/tr.js:6250` (61 anahtar), en `:6227` (61), ru `:5291` (61), ar `:5189` (61); menü etiketi tr `:4883`, en `:4840`, ru `:4071`, ar `:3976` · Ekran→uç eşleşmesi: `admin-panel/frontend/src/views/system/MediaStorageSettingsView.vue:313-317` (`STATUS_METHOD`/`TEST_METHOD` → `media_storage_settings.get_storage_status` / `test_connection`), backend karşılığı `tradehub_core/tradehub_core/doctype/media_storage_settings/media_storage_settings.py:354` (`get_storage_status`), `:390` (`test_connection`) | Yok — üç ölçüt (rota+menü+rol) ve uç doğrulaması ayrı ayrı geçti. |
| T-052 | DevOps | Yok — URL/imza/nginx/purge backend-devops işi; CDN alanları zaten T-051 ekranının bir bölümü (ayrı ekran/rota değil) | FE-DIŞI | CDN bölümü `MediaStorageSettingsView.vue` içinde (`t("mediaStorage.section.cdn")`) — T-051'in parçası, T-052'nin kendi FE payı yok | — |
| T-053 | DevOps | Yok — retention alanları da T-051 ekranının "Saklama" bölümünde; ayrı iş/monitor ekranı (Media Maintenance Report) yok | FE-DIŞI | Bulunan `purge_trash`/`purge_archive` (`admin-panel/frontend/src/composables/useMediaOptimize.js:259,334`) FARKLI bir sistem — eski "çöp kutusu" (trash) özelliği, Faz 5'in `original_retention_job`/`derivative_gc_job`/`soft_delete_job`'ı değil | Media Maintenance Report / GC job tetikleme-izleme ekranı admin-panel'de bulunamadı. |
| T-054 | DevOps | Var, tam — Medya Yedeği ekranı: liste/oluştur/doğrula/geri-yükleme planla-uygula/onar/sil/dışa aktar akışlarının tamamı gerçek uçlara bağlı | TAM | Rota: `admin-panel/frontend/src/router/index.js:1036-1043` (`path: "media-backup"`, `requiresSuperAdmin: true`) · Menü: `admin-panel/frontend/src/data/navigation.js:550` · Composable→uç eşleşmesi: `admin-panel/frontend/src/composables/useMediaBackup.js:48` (`list_media_backups`), `:63` (`create_media_backup`), `:87` (`verify_media_backup`), `:106` (`plan_media_restore`), `:121` (`apply_media_restore`), `:147` (`repair_missing_media`), `:167` (`delete_media_backup`), `:213` (`media_backup_export_status`), `:232` (`start_media_backup_export`), `:248` (`discard_media_backup_export`), `:282` (`prune_media_backups`) · backend karşılıkları tamamı mevcut: `tradehub_core/api/media_admin.py:724,733,742,755,767,796,809,818,843,852,861` | Not: belge T-054 için ayrı bir UI istemiyor (yalnız `docs/ops/`, `deploy/backup/` dosyaları). Koda rağmen bu FE payı belgenin talep ettiğinin ÜSTÜNDE bir kapsam — bonus bulgu olarak işaretlendi, eksik değil. |
| T-055 | QA | Yok — uçtan uca kabul senaryoları Python test dosyası (`tests/acceptance/test_storage_acceptance.py`); FE'de karşılığı beklenmiyor | FE-DIŞI | (FE tarafında aranmadı; konu gereği FE payı yok) | — |

---

## Sayım

Toplam **11** görev denetlendi (T-040…T-044, T-050…T-055).

- **TAM:** 2 (T-051, T-054)
- **KISMİ:** 2 (T-041, T-043)
- **YOK:** 1 (T-042)
- **FE-DIŞI:** 6 (T-040, T-044, T-050, T-052, T-053, T-055)
- **ÖLÇÜLEMEDİ:** 0 (satır bazında; T-041 içinde bir alt-madde ÖLÇÜLEMEDİ olarak işaretlendi — bkz. tablo)

---

## En önemli 3 bulgu

1. **T-051 gerçekten TAM ve sıkı kapılı.** Rota, menü ve rol kapısı üçü ayrı ayrı doğrulandı; kapı hem FE (`router` meta.roles + `auth.canAccess`) hem BE (`ALLOWED_ROLES` + `only_for`) tarafında var. Ekranın çağırdığı `get_storage_status`/`test_connection` uçları gerçek ve doğru DocType dosyasında tanımlı. i18n dört dilde de aynı 61 anahtarla eksiksiz — bu dilimin tek somut ekran görevi (belgenin kendi ifadesiyle) beklendiği gibi çıktı.

2. **T-043'ün "kullanım takibi" iddiası kodun kendi yorumunda çürütülüyor.** `useMediaUsage.js` içindeki yorum satırları açıkça şunu söylüyor: backend kalıcı bir `Media Usage` index'i TUTMUYOR, `media/usage.py` her istekte sabit bir kaynak listesini SATIR SATIR TARIYOR ve bu, `tradehub_core/docs/reports/34-dogrulama-faz4-7.md`'ye atıfla belgelenmiş bir sınır. Yani panel, T-043'ün istediği kalıcı "last_seen" damgalı bir kullanım paneli değil, anlık bir tarama sonucu gösteriyor — bu farkı ekran metni bilinçli olarak açıklıyor ("taranan kaynaklarda bulunamadı" der, "hiçbir yerde kullanılmıyor" demez). Öksüz dosya (Orphan Report) tarafı ise admin-panel'de HİÇ yok; backend'de mantık (`classify_orphans`, `find_orphan_assets`) var ama whitelist uç yok, dolayısıyla bağlanacak bir ekran da olamaz.

3. **T-054 (DevOps) belgenin istemediği ama koddaki en eksiksiz Faz 5 FE parçası.** Belge T-054 için hiçbir UI istemiyor (yalnız `docs/ops/backup-dr.md`, `deploy/backup/`, runbook). Buna rağmen admin-panel'de tam işlevli bir "Medya Yedeği" ekranı var: liste, oluştur, doğrula, geri-yükleme planla/uygula, onar, sil, dışa aktar — 11 fonksiyonun TAMAMI gerçek, whitelisted backend uçlarına (`tradehub_core/api/media_admin.py`) bire bir eşleşiyor. Tersine, T-052/T-053 (CDN teslim, retention/GC) için belgede istenmeyen bir ekran da yok — bu alanların yapılandırma kısmı zaten T-051 ekranının bölümlerine gömülü, ayrı bir iş/monitor ekranı hiçbir yerde yok.

---

## Ölçemediklerim

- **T-041'in golden-test/parity iddiası:** Belge, simülatörün `resolve_crop`'un öncelik zincirini (`docs/simulator.html` içindeki `cropWindow()` ile) bire bir üretmesini ve bunun test edilmesini istiyor. Admin-panel'de `resolve_crop`'un 5 seviyeli öncelik mantığının (override→safe-area+focal→global focal→akıllı öneri→merkez) FE'de bir JS ikizi ya da bunu doğrulayan bir parity testi bulunamadı — bulunan tek parity dosyası farklı bir alt-sistemin (T-100 piksel geometrisi) ikizi. Bu maddeyi ne "var" ne "yok" diye kesin sınıflandıramadım; KISMİ içinde ayrı not olarak bırakıldı.
- **T-055'in kabul test dosyası** (`tests/acceptance/test_storage_acceptance.py`) tradehub_core içinde tam adıyla bulunamadı; konu FE-dışı olduğu için ayrıca aranmadı — bu satırın backend/QA tarafındaki gerçek durumu bu denetimin kapsamı dışında, koşturulmadı.
- **`tradehubfront`** (mağaza ön yüzü) tarafında bu 11 görevle örtüşen hiçbir dosya bulunamadı (`media` grep'i alakasız dosyalar döndürdü) — beklenen bir sonuç, çünkü bu dilim yönetim paneli işlevleri (Media Superadmin, depolama, yedek, kırpma stüdyosu) etrafında; storefront'ta karşılığı olması gerekmiyordu, bu nedenle ayrıca satır satır taranmadı.
- **Backend'in gerçekte çalışır durumda olup olmadığı** (ör. `Media Rendition` tablosunun dolu olup olmadığı, boru hattı bayraklarının açık olup olmadığı) koşturulmadı/ölçülmedi — `useSrcsetSimulator.js` içindeki bir yorum "Bugün `Media Rendition` tablosu BOŞ (boru hattı bayrakları kapalı)" diyor ama bu satır içi bir kod yorumu, benim doğrudan ölçtüğüm bir şey değil; rapora güvenilmedi kuralına uyarak bunu iddia değil gözlem olarak not ediyorum.
