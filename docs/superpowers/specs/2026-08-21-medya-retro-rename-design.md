# Medya retro-rename — eski tahmin edilebilir dosya adlarının içerik-adresli ada taşınması

**Tarih:** 2026-08-21 · **Plane:** MOGEM-582 ([G-16]-17) alt görevi · **İlgili:** TUR-141 (enumeration), TUR-128 (format dönüşümü), ADR-0001, `docs/MEDYA-DEPOLAMA-STANDARDI.md` §7, `docs/plans/migration.md` §8 (M-B)

## 1. Amaç ve karar özeti

`public/files/` altında düz dizinde duran, adı tahmin edilebilir (`0505.jpg`, `515804-5.jpg`) eski dosyaları, yeni yüklemelerde zaten geçerli olan içerik-adresli, shard'lı ada (`/files/<ab>/<sha256[:32]>.<ext>`) taşımak; böylece URL sayısını artırarak kataloğu toplu çekme (enumeration) açığını **kapatmak**. Eski URL'ler **90 gün** süreyle 301 ile yeni adrese yönlendirilir, sonra 404 olur.

| Karar | Seçim | Gerekçe |
|---|---|---|
| Ortam sırası | lokal → alpha → prod | Her ortamda önce `plan` raporu, onaydan sonra `apply` |
| Eski URL davranışı | 90 gün 301, sonra 404 | Dış linkler (Google görsel, e-posta) kırılmasın; kalıcı 301 açığı kapatmaz |
| Kapsam | `public/files/` altındaki **tüm** hash-formatına uymayan dosyalar | Private dosyalar zaten izin-kapılı, kapsam dışı |
| Yetim dosya (DB'de referansı yok) | Yine de yeniden adlandır, raporda ayrı listele | Açık yetimler için de kapanır; silme ayrı karar |
| 301 mekanizması | **Backend (`page_renderer` hook)**, nginx `map` değil | Ortamdan bağımsız, imaj rebuild yok, prod edge'e (Sunucu B) erişim gerekmez |
| CDN purge | Yok | `/files/` önünde CDN yok (report 06) |
| TUR-128 ile ilişki | Bu araç "diskteki **güncel** bayt'ları hash'ler"; TUR-128 sonra çalışırsa aynı satırlara ikinci kez dokunur. Öneri: TUR-128 önce ya da bu araç TUR-128 sonrası tekrar koşulur (idempotent) | Üç belge tek migration şartı koşmuş; idempotentlik bunu yumuşatır |

## 2. Ölçülen durum (lokal, 2026-08-21)

| Ölçüm | Değer |
|---|---|
| Distinct eski public URL (`tabFile`, hash-dışı ad) | **2.843** (belgedeki "2.166" eskimiş/farklı payda) |
| Bu URL'leri paylaşan `tabFile` satırı | 4.319 (bir URL'de 39 satıra kadar) |
| Diskte düz dizinde hash-dışı dosya | 2.843 (DB ile birebir) |
| Shard dizini / `media/` asset klasörü | 256 / 125 |
| `tabListing.primary_image` eski referans | 1.241 |
| `tabListing Image.image` eski referans | 1.137 |
| `Listing.description` içinde gömülü `/files/` | 0 |

Prod sayıları farklıdır; `plan` adımı her ortamda yeniden ölçer.

## 3. Mimari

```
plan()  ──JSON rapor──▶  insan onayı  ──▶  apply(job_key)  ──▶  rollback(job_key)  (gerekirse)
                                              │
                    dosya başına:  disk os.replace → tabFile.file_url (tüm satırlar)
                                   → refs.retarget → Media URL Redirect satırı → commit
                                   hata: db.rollback + ters os.replace

istek: GET /files/0505.jpg
  storefront nginx (^~ /files/, limit_req, noindex) → frappe-frontend nginx
  → try_files public/$uri  (yok)  → @webserver (gunicorn)
  → PathResolver: page_renderer hook → MediaRedirectRenderer.can_render()
     tek indeksli sorgu: Media URL Redirect[source_url = /files/0505.jpg, expires_at > now]
  → 301 Location: /files/ab/<hash>.jpg   (Cache-Control: no-store)
  90 gün sonra: günlük cron satırı siler → NotFoundPage (404)
```

Doğrulananlar: frappe-frontend nginx `try_files /site/public/$uri @webserver` (container config satır 64); `PathResolver.resolve` özel renderer'ları yerleşiklerden **önce** dener; `frappe.website.page_renderers.redirect_page.RedirectPage` hazır 301 yanıtı üretiyor. Frappe'nin `resolve_redirect`/`Website Route Redirect` yolu **kullanılmaz**: her istekte tüm kuralları DB'den çekip regex ile sırayla tarıyor, 2.843 kural her sayfa isteğini yavaşlatır.

## 4. Bileşenler

### 4.1 `tradehub_core/media/retro_rename.py` (yeni)

Şablon: `media/access_level.py::set_level` (disk önce → DB → refs → hata halinde ters taşıma). Farkı: prefix değil **ad** değişiyor; `is_private` sabit 0.

- `is_legacy_name(file_url) -> bool` — `/files/` ile başlar, `/files/media/` değil, stem 32-hex değil, shard'sız.
- `target_url(file_url) -> str` — diskteki bayt'ları okur, `naming._hashed_name(basename, content)` + `naming._shard` → `/files/<ab>/<hash>.<ext>`. Uzantı: mevcut uzantı küçük harfe.
- `plan(store=None, limit=None) -> dict` — **salt okunur**. Her aday için: `source_url`, `target_url`, `file_rows` (aynı URL'li `tabFile` sayısı), `refs` (`refs.find` özeti: exact / readonly / embedded), `orphan` (exact+readonly+embedded hepsi 0), `collision` (hedef zaten diskte var → içerik aynı mı?), `disk_missing` (DB'de var diskte yok). Özet sayaçlar + `skipped_reasons`. JSON'a yazılır (`scripts/plan_backfill.py` `BACKFILL_PLAN_OUT` deseni).
- `apply(job_key, batch_size=200, dry_run=0, store=None)` — kuyruk işi; her batch sınırında Redis `stop` bayrağını kontrol eder (UI `[Durdur]`) (`frappe.enqueue`, `enqueue_after_commit=True`, `queue="long"`). Dosya başına:
  1. AV/karantina kapısı (`access_level` ile aynı: `th_media_state`).
  2. `os.replace(old, new)`; hedef zaten varsa ve içerik hash'i eşitse eski dosya silinir (doğal dedup), değilse atla + raporla (teorik: aynı hash farklı içerik).
  3. `frappe.db.set_value("File", {"file_url": old}, {"file_url": new}, update_modified=False)` — paylaşan tüm satırlar. `content_hash` boşsa doldurulur.
  4. `refs.retarget(old, new)` (bkz. 4.3 genişletme).
  5. `Media URL Redirect` insert: `source_url=old`, `target_url=new`, `job_key`, `expires_at=now+90g`.
  6. Önbellek temizliği: `tradehub:file_url_ambiguous:{old}`.
  7. `frappe.db.commit()`; hata → `frappe.db.rollback()` + `os.replace(new, old)`; hata sayacı; `%2` hata oranı aşılırsa iş durur (migration.md §7.3).
  8. Redis progress (`media/runner.py` deseni: `processed/renamed/skipped/errors/skip_reasons`).
  9. `audit.log("media_retro_renamed", ...)` — mevcut audit olay seti.
  `dry_run=1`: 1-2 hesaplanır, hiçbir şey yazılmaz.
- `rollback(job_key)` — `Media URL Redirect[job_key]` satırlarını ters oynatır: `os.replace(target, source)`, `tabFile.file_url` geri, `refs.retarget(new, old)`, satırı siler. Bu, migration.md'de "M-B rollback YOK" denen boşluğu kapatır.

### 4.2 `Media URL Redirect` DocType (yeni, modül `Tradehub Core`)

| Alan | Tip | Not |
|---|---|---|
| `source_url` | Data, **unique, indexed** | eski `/files/...` |
| `target_url` | Data | yeni `/files/ab/hash.ext` |
| `job_key` | Data, indexed | rollback ve raporlama |
| `expires_at` | Datetime, indexed | varsayılan +90 gün |
| `hit_count` | Int | isteğe bağlı; ilk sürümde **yazılmaz** (her 301'de yazma = yük) |

Yalnız System Manager okur/yazar; web'e açık değil. Naming: autoname `hash`.

### 4.3 `refs.retarget` genişletmesi (`media/refs.py`)

Bugün yalnız `exact` eşleşmeleri günceller; JSON (`Storefront Layout.sections`, `Listing Variant Item.variant_gallery`) ve gömülü metni atlar. Lokal ölçümde `Listing.description` içinde 0 referans var ama alpha/prod farklı olabilir. Genişletme:

- `embedded` eşleşmeler için güvenli **tam-dize değiştirme**: kolon değeri içinde `old_url`'nin tam dizesi (`"`, `'`, boşluk, `)` ile sınırlandırılmış ya da JSON `\/` kaçışlı biçimi — `usage._search_variants`) → `new_url`. JSON kolonlar için `json.loads` → yürü → `json.dumps`; parse edilemezse atla + raporla.
- `READONLY_TABLES` (sipariş anlık görüntüleri) ve `HISTORY_SOURCES` **dokunulmaz** (mevcut sözleşme; 301 onları 90 gün taşır, sonra kırık kalmaları kabul edilen davranış — sipariş görselleri `snapshot_image` için ayrıca raporlanır).
- `retarget` hâlâ commit etmez; çağıran yönetir (mevcut sözleşme korunur).

### 4.4 `MediaRedirectRenderer` (`tradehub_core/media/redirect_renderer.py`, yeni) + hook

```python
class MediaRedirectRenderer:
    def __init__(self, path, http_status_code=None): ...
    def can_render(self):
        # yalnız "files/" ile başlayan yollar; tek sorgu, expires_at > now
    def render(self):
        frappe.flags.redirect_location = target
        return RedirectPage(self.path, 301).render()
```

- `hooks.py`: `page_renderer = ["tradehub_core.media.redirect_renderer.MediaRedirectRenderer"]`.
- Maliyet: yalnız diskte **olmayan** `/files/` isteklerinde tek indeksli sorgu. Normal dosya istekleri nginx'te biter, renderer'a hiç uğramaz.
- Yanıt `Cache-Control: no-store` (RedirectPage varsayılanı) — 90 gün sonra 404'e dönüşün tarayıcıda takılmaması için.
- Mevcut `limit_req` (10 r/s, burst 20) ve `X-Robots-Tag: noindex` storefront nginx'te 301'leri de kapsar (`^~ /files/` bloğu).

### 4.5 Süre dolumu

`scheduler_events["daily"]`: `tradehub_core.media.retro_rename.purge_expired_redirects` — `expires_at < now` satırlarını siler; silinen sayıyı audit'e yazar.

### 4.6 Admin API (`api/media_admin.py`)

Mevcut desen (`_guard_destructive`, `MAX_BATCH`, `job_key`); hepsi System Manager:
- `retro_rename_plan(store=None)` → plan JSON özeti + ilk 200 satır detay (`plan()` salt okunur).
- `start_retro_rename(dry_run=0, batch_size=200)` → `{job_key}`; aynı anda ikinci iş başlatılamaz (Redis kilit `tradehub:retro_rename:active`).
- `get_retro_rename_status(job_key)` → Redis progress (`state/total/processed/renamed/skipped/errors/skip_reasons/expires_at`).
- `rollback_retro_rename(job_key)` → geri alma işi başlatır, `{job_key}` döner (aynı progress deseni).
- `retro_rename_history()` → son işler: `job_key`, tarih, sayılar, yönlendirme süresi; "Geri al" tuşunun görünürlüğü buradan.

### 4.7 Admin panel UI (`admin-panel/frontend`)

Mevcut **Sistem → Medya Optimizasyonu** ekranına (`views/system/MediaOptimizeView.vue`) bir kart eklenir; yeni route yok.

- `composables/useMediaRetroRename.js` — `useMediaOptimize.js` kalıbı: `plan()`, `start({dryRun})`, `rollback(jobKey)`, 3 sn polling, `TERMINAL_STATES`, toast.
- `components/media/MediaRetroRenameCard.vue` — dört durum:
  1. **Bekliyor:** "N dosya eski adla duruyor" + `[Önizle]`. N = `retro_rename_plan` özetinden; N = 0 ise kart "Tüm dosyalar standartta" der, tuş yok.
  2. **Önizleme:** taşınacak / referans güncellenecek / yetim / diskte yok / çakışma / atlanacak gömülü referans sayıları, detay listesi; `☐ Önce prova (dry-run)`; `[İptal]` `[Yeniden adlandırmayı başlat]`. Başlat ikinci bir onay diyaloğu ister (mevcut `MediaRecordDialog`/confirm deseni; tarayıcı `confirm()` değil).
  3. **Çalışıyor:** ilerleme çubuğu, hata sayacı, `[Durdur]` (Redis `stop` bayrağı; batch sınırında durur).
  4. **Tamamlandı:** sayılar + "Yönlendirme <tarih>'e kadar" + `[Geri al]` (yönlendirme satırları durduğu sürece, `retro_rename_history` ile).
- Yalnız System Manager render eder (mevcut yetki composable'ı); satıcı oturumunda kart yok.
- `lib/api/types.gen.ts` uçlara göre güncellenir; i18n `tr`/`en` anahtarları eklenir.
- Panel dist Docker imajında: build sonrası `compose build` gerekir (bkz. hafıza notu).

## 5. Veri akışı ve sıra (ortam başına)

1. `bench execute tradehub_core.media.retro_rename.plan` → JSON rapor; `scripts/media_stats.py reconcile()` ile çapraz kontrol.
2. Raporu gözden geçir: `disk_missing`, `collision`, `embedded` atlanacaklar, `orphan` listesi. **İnsan onayı.**
3. Yedek: `media/backup.py` ile `tabFile` + referans manifesti (blob'lar içerik-adresli, rename'den etkilenmez; manifest eski `file_url` taşır — bu beklenen).
4. `start_retro_rename(dry_run=1)` → hata sayacı 0 olmalı.
5. `start_retro_rename(dry_run=0)` — `long` kuyruk, 200'lük batch; progress izlenir.
6. Doğrulama (§7).
7. 90 gün sonra cron otomatik temizler; erken kapatmak istenirse `expires_at` elle çekilir.

Rollback penceresi: 301 satırları durduğu sürece (`job_key`) `rollback` çalışır. Satırlar silindikten sonra rollback **yoktur** — runbook'ta açık yazılır.

## 6. Hata durumları

| Durum | Davranış |
|---|---|
| DB'de var, diskte yok | `plan` raporlar, `apply` atlar (`disk_missing`) |
| Hedef ad diskte zaten var, içerik aynı | Eski silinir, DB hedefe bağlanır (dedup) |
| Hedef ad var, içerik farklı | Atla + raporla (`collision`) |
| DB yazımı patlar | rollback + ters `os.replace`, sayaç; %2 eşiği aşılırsa iş durur |
| `refs.retarget` bir satırı atladı (embedded/JSON parse hatası) | 301 köprüler; rapor `refs_skipped_detail` |
| AV/karantina durumu `blocked` | Atla (`quarantined`) |
| Aynı dosya ikinci kez (`apply` tekrar koşuldu) | `is_legacy_name` false → hiç aday olmaz (idempotent) |
| M-A arşivi (`archive.relative_path_for`) eski URL'ye bağlı | Araç arşivi taşımaz. Koşudan önce `archive.purge_expired()` çalıştırılır ve `archive.usage_bytes()` 0'a yakın doğrulanır; bekleyen geri-alma varsa migration ertelenir. |

## 7. Test ve doğrulama

Birim/entegrasyon (`FrappeTestCase`, `tests/test_media_retro_rename.py`):
- `is_legacy_name`: eski ad → True; hash'li/shard'lı/`media/` → False.
- `target_url`: sabit bayt → beklenen `/files/ab/<hash>.ext`; uzantı küçük harf.
- `apply` tek dosya: diskte eski yok/yeni var; aynı URL'li 3 `tabFile` satırı hepsi güncellendi; `Listing.primary_image` retarget; `Media URL Redirect` satırı var.
- `apply` DB hatası simülasyonu: dosya eski yerine döndü, redirect satırı yok.
- `rollback`: tam tersine döner.
- Admin panel: `useMediaRetroRename` Vitest testi (plan→start→poll→terminal; rollback görünürlüğü history'e bağlı); `MediaRetroRenameCard` dört durum render testi.
- `MediaRedirectRenderer`: eski URL → 301 + doğru Location; süresi dolmuş → 404; bilinmeyen → 404; `/files/ab/<hash>` gerçek dosya → renderer'a uğramaz (nginx) — bu Frappe testinde `can_render` False ile temsil edilir.
- `purge_expired_redirects`: süresi dolan silinir, dolmayan kalır.
- `refs.retarget` embedded: HTML `<img src="/files/old.jpg">` ve JSON `["\/files\/old.jpg"]` → yeni; bozuk JSON atlanır.

Ortam doğrulaması (runbook):
- `media_stats.reconcile()` → `urls_public_non_hashed = 0`, `urls_public_flat = 0`.
- `curl -sI /files/<eski>` → `301` + `Location` yeni; `curl -sI <yeni>` → `200`, `Cache-Control: immutable` (gateway map).
- `refs.find_dangling()` → 0.
- Storefront'ta rastgele 20 ürün sayfası görseli yükleniyor (LCP preload dahil).

## 8. Kapsam dışı

- TUR-128 format dönüşümü (ayrı karar; bu araç idempotent ve sonra tekrar koşulabilir).
- Private dosyalar, `/files/media/` türevleri.
- Admin panel dışı başka bir UI (storefront/satıcı paneli).
- nginx/imaj değişikliği, prod edge (Sunucu B).
- `READONLY_TABLES` / `HISTORY_SOURCES` rewrite.
- Yetim dosya silme.

## 9. Belge güncellemeleri (aynı PR)

- `docs/MEDYA-DEPOLAMA-STANDARDI.md` §1 tablo satırı 21 + §5 (satır 116-136): türev yolu gerçek koda göre (`/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{ext}`; video yerinde üzerine yazılır) düzeltilir; §7 "ertelendi" → bu spec'e bağlanır.
- `docs/plans/migration.md` §8.1/§8.3.2 eskimiş notlar (nginx sertleştirmesi artık kaynak şablonda; LIVE_SOURCES 17) güncellenir.
- Plane MOGEM-582: kart notu düzeltilir; "Retro-rename" alt görevi açılır ve bu spec'e bağlanır.
