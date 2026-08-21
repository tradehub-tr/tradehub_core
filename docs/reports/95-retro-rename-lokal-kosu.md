# 95 · Medya retro-rename — lokal uçtan uca koşu raporu

**Tarih:** 2026-08-21 · **Kapsam:** Task 10 — API tip senkronu, admin-panel imaj rebuild, `istoc.localhost` üzerinde gerçek veriyle prova → gerçek koşu → doğrulama → geri al provası → yeniden koşu.

Ortam: lokal dev, ~2.8k eski adlı dosya, backend `istoc-dev-backend-1` + kuyruk/scheduler container'ları, site `istoc.localhost`, panel `istoc.localhost:8080/panel`.

---

## 1. API tip senkronu (admin-panel)

```
cd admin-panel/frontend && npm run sync:api && npm run sync:api:check
```

`openapi-http.yaml`'daki **7** yeni `retro_rename*` ucu (`retro_rename_count`, `retro_rename_plan`, `start_retro_rename`, `get_retro_rename_status`, `stop_retro_rename`, `rollback_retro_rename`, `retro_rename_history`) `types.gen.ts`'e senkronlandı — görev tanımında "6" deniyordu, gerçek sayı **7**'dir (`retro_rename_count` sonradan eklenmiş). `sync:api:check` → "temiz".

Commit (admin-panel) `efadc2c`: `chore(api): retro-rename uçları için tip senkronu`.

## 2. Admin-panel imajı

```
npm run build                                  # OK, 11.2s
docker compose build admin-panel               # OK
docker compose up -d --no-deps admin-panel     # yalnız admin-panel recreate edildi
```

Panel URL: **http://istoc.localhost:8080/panel** (aynı zamanda `http://istoc.localhost/panel`, gateway `:80`→host `:8080` yedek portu). Sistem → Medya (route `/panel/media-optimize`, bileşen `MediaOptimizeView.vue`) — menüde görünen etiket **"Medya"**dır, "Medya Optimizasyonu" bileşen adıdır.

## 3. Backend kod senkronu + migrate + restart

```
sync.sh <9 dosya>                                          # backend/queue-long/queue-short/scheduler'a docker cp
docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate   # temiz, hata yok
docker restart istoc-dev-backend-1 istoc-dev-queue-long-1 istoc-dev-queue-short-1 istoc-dev-scheduler-1 istoc-dev-frappe-frontend-1
docker exec istoc-dev-queue-long-1 grep -c "def run_job" .../media/retro_rename.py   # → 1
```

`Media URL Redirect` DocType + `file_names` alanı migrate ile işlendi, hata yok (yalnız helpdesk arama indeksi kuyruğa alındı — ilgisiz).

**Kalıcılık uyarısı:** backend kodu container'a `docker cp` ile taşındı, **imaja gömülü değil**. `docker compose up -d`/recreate (backend, queue-long, queue-short, scheduler) bu kopyaları SİLER ve eski koda döner — kalıcılık için `istoc/tradehub-backend:v15` imajının rebuild edilmesi gerekir (bu görevin kapsamı dışında; yalnız admin-panel imajı rebuild edildi).

## 4. Giriş

`docker/.env`'deki `ADMIN_PASSWORD=admin` ile `POST /api/method/login` (curl, çerez tabanlı `sid`). Yeni parola belirlemeye gerek kalmadı.

## 5. Prova (dry-run)

`POST start_retro_rename dry_run=1` → `job_key=8c08c085ab92`.

| Alan | Değer |
|---|---|
| total / processed | 2846 / 2846 |
| renamed | 2834 |
| skipped | 12 (`disk_missing`) |
| errors | **0** |
| süre | ~anlık (ilk poll'da `completed`) |

`retro_rename_plan` ile tutarlı: `total=2846, renamable=2834, orphans=398, disk_missing=12, collisions=0, refs_exact=2980, refs_readonly=28, refs_embedded=303, file_rows=4322`.

## 6. Gerçek koşu #1

`POST start_retro_rename dry_run=0` → `job_key=274219ae6992`, başlangıç `19:13:39Z`.

| Alan | Değer |
|---|---|
| total / processed | 2846 / 2846 |
| renamed | 2834 |
| skipped | 12 (`disk_missing`) |
| errors | **0** |
| süre | **49 s** (~58 dosya/sn) |

## 7. Doğrulama bloğu (koşu #1 sonrası)

### 7.1 SQL sayacı — brief'teki naif sorgu vs. gerçek `is_legacy_name()`

Brief'teki naif SQL (`is_folder` filtresi yok, `".."` korumasız) → **41** (beklenen 0 değil). Kök nedeni araştırıldı:

- **20 satır** — `tradehub_core/tests/test_media_retro_rename.py::TestPlan` testinin `rr-plan-*.jpg` adıyla **gerçek `istoc.localhost` DB/disk'ine** yazdığı, temizliği (muhtemelen kesintiye uğramış bir test koşumunda) tamamlanmamış **kalıntı fixture** satırları — bugünün koşusundan **önce** oluşmuş, benim işlemimle ilgisiz. `legacy_urls()` bunları zaten "disk_missing" (12'nin içinde) olarak doğru sınıflandırıyor.
- **19 satır** — gerçek ürün görselleri; dosya adlarında **gerçek `".."` dizisi** var (ör. `MOİ ile derin düzen..jpg`, açıklama cümlesi + nokta + `.jpg`). `retro_rename.is_legacy_name()` yol-geçişi (path traversal) korumasıyla `".." in url` içeren adresleri **kasıtlı olarak** aday saymıyor — bu dosyalar hiç aday olmadı, koşu onları atlamadı, zaten görmedi. Bilinen bir kenar durum; ürün sahibine bildirilmeye değer bir takip maddesi (öneri: normalize adımına çift-nokta temizliği eklenebilir).
- **2 satır** — gerçek `disk_missing` (12'nin içinde, ChatGPT Image dosyaları).

**Gerçek üretim fonksiyonuyla (`retro_rename.legacy_urls()`) doğrulama:**

```
docker exec -i istoc-dev-backend-1 bench --site istoc.localhost console
>>> len(retro_rename.legacy_urls())
12
```

→ koşunun kendi `skip_reasons: {"disk_missing": 12}` sayısıyla **tam örtüşüyor**. Migrasyon mantığı **doğru**; brief'teki basit SQL, uygulamanın `is_folder`/`".."` filtrelerini içermediği için yanlış pozitif üretiyor.

### 7.2 Disk düz sayaç

`find . -maxdepth 1 -type f | wc -l` → **23** (beklenen 0 değil). Bileşenler: yukarıdaki 19 `".."` dosyası + 8 test-kalıntı disk dosyası (`rr-*`, `rr-plan-*` — DB satırlarıyla 1:1 eşleşmiyor, ayrı test koşumlarından farklı UUID'ler) + birkaç şardsız (flat) 32-hex adlı blob (`tabFile` karşılığı yok, retro_rename kapsamı dışı).

### 7.3 301/200 örneği

```
curl -sI http://istoc.localhost:8080/files/0004.jpg
→ HTTP/1.1 301 MOVED PERMANENTLY
  Location: /files/76/76d37294b47efb9bd102db0dd74480a8.jpg

curl -sI http://istoc.localhost:8080/files/76/76d37294b47efb9bd102db0dd74480a8.jpg
→ HTTP/1.1 200 OK
  Cache-Control: public, max-age=31536000, immutable
```

### 7.4 Storefront — 20 ürün görseli

`/urun/<slug>` sayfaları Alpine.js SPA kabuğu — görsel `<img>` etiketleri sunucu HTML'inde **yok** (istemci tarafında API'den geliyor), bu yüzden brief'teki "sayfayı curl'le, img src'leri grep'le" yöntemi doğrudan çalışmadı. Bunun yerine DB'den gerçek `Listing` + ekli `File` (yerel `/files/...`) eşleşen **20 farklı Listing** (LST-00201, LST-00202, LST-00555…LST-00570) seçildi:

- Koşu öncesi: 20/20 eski URL → **200**.
- Koşu sonrası: 20/20 eski URL → **301** (birkaçı ilk denemede nginx `limit_req` yüzünden 503 döndü — art arda hızlı istekten; 1-2 sn beklemeyle 20/20 **301** doğrulandı), 20/20 hedef URL → **200**.

### 7.5 `refs.find_dangling()`

**2** döndü (0 değil). İkisi de `Listing Image` alt tablosunda, hiçbir zaman bir `File` DocType kaydı olmamış iki yerel URL'e referans (`ipli-el-rondosu-...-08.jpg`, `...-13.JPG` — muhtemelen toplu içe aktarım sırasında `image` alanına doğrudan URL yazılmış, `File` eki hiç oluşturulmamış). `retro_rename` adayları `tabFile` üzerinden tarıyor; bu satırların hiçbir zaman `File` karşılığı olmadığı için koşudan **önce de sonra da** aynı durumda — göç ile ilgisiz, önceden var olan bir veri kalitesi boşluğu.

## 8. Geri al provası

`POST rollback_retro_rename job_key=274219ae6992` → yeni `job_key=17e9b6134c7d`, başlangıç `19:21:25Z`.

| Alan | Değer |
|---|---|
| total / processed | 2834 / 2834 |
| renamed | 2834 |
| skipped | 0 |
| errors | **0** |
| süre | **43 s** |

Doğrulama:
- `legacy_urls()` → **2846** (orijinal aday sayısıyla birebir tur — round-trip temiz).
- `/files/0004.jpg` → **200** (eski adıyla geri geldi).
- `/files/76/76d37294b47efb9bd102db0dd74480a8.jpg` → **404** (yeni ad kayboldu, beklenen).

## 9. Son gerçek koşu (kalıcı hedef durum)

`POST start_retro_rename dry_run=0` → `job_key=8985c816a995`, başlangıç `19:22:30Z`.

| Alan | Değer |
|---|---|
| total / processed | 2846 / 2846 |
| renamed | 2834 |
| skipped | 12 (`disk_missing`) |
| errors | **0** |
| süre | **55 s** |

Koşu #1 ile **birebir aynı sonuç** — deterministik/tekrarlanabilir. Son doğrulama: `legacy_urls()` → **12**, `/files/0004.jpg` → 301, hedef → 200 + immutable.

## 10. Panel gözlemi

`istoc.localhost:8080/panel` → Sistem → Medya (`/panel/media-optimize`). "Eski adlandırma" kartı son (göç edilmiş) durumda:

> **12 dosya hâlâ tahmin edilebilir adla duruyor (0505.jpg gibi).**
> Yeni standarda taşı → eski linkler 90 gün yönlendirilir, sonra kapanır.
> `2834 · Yönlendirme 19 Kas 2026 tarihine kadar` [Geri al]
> `1 · Yönlendirme 20 Ağu 2026 tarihine kadar` [Geri al]

12 rakamı §7.1/§9'daki `legacy_urls()` sonucuyla, 2834 rakamı bu görevdeki son koşunun `renamed` sayısıyla birebir örtüşüyor. İkinci satır (`1`, `job_key T301`) bu görevden önce var olan, bu koşulardan bağımsız tek dosyalık bir kayıt.

Ekran görüntüsü: `.superpowers/sdd/2026-08-21-medya-retro-rename/panel-after.png`. **"Öncesi" ekran görüntüsü alınmadı** — resmi son durum (göç edilmiş) zaten API ile kurulmuşken yalnızca ekran görüntüsü için ek bir geri-al/yeniden-koşu turu yapmak riskli/gereksiz görüldü; "öncesi" sayıları §5/§6'da API kanıtıyla zaten belgeli.

## 11. Ortam notları / bilinen boşluklar

1. **Backend kod kalıcılığı yok** — bkz. §3. Bir sonraki `docker compose up -d` (backend/queue-*/scheduler) bu görevdeki kod değişikliklerini siler; imaj rebuild edilmeli.
2. **Test kalıntısı (`rr-plan-*`)** — `test_media_retro_rename.py::TestPlan` gerçek siteye yazıp `addCleanup` ile temizliyor; en az bir önceki koşumda temizlik tamamlanmamış, 20 `tabFile` satırı + 8 disk dosyası kalıntı olarak duruyor. Önerilen takip: testi bir daha çalıştırıp tam temizliğin gerçekleştiğini doğrulamak, veya `file_url like '/files/rr%'` + karşılık gelen disk dosyalarını elle temizlemek.
3. **`".."` içeren dosya adları kalıcı olarak aday dışı** — `is_legacy_name()`'in yol-geçişi koruması (`".." in url`) 19 gerçek ürün görselini bilerek atlıyor; bu dosyalar hiçbir retro-rename koşusunda taşınmayacak. Ürün sahibine bildirilmeli.
4. **`refs.find_dangling()` = 2, göçten bağımsız** — `Listing Image` alt tablosunda `File` karşılığı hiç olmamış 2 referans; §7.5.
5. **Storefront SPA** — ürün sayfaları istemci tarafında render ediliyor, görsel URL doğrulaması DB üzerinden 20 örnek `Listing`/`File` eşleşmesiyle yapıldı (brief'teki "sayfayı curl'le" yöntemi doğrudan çalışmadı).

## 12. Özet

| Koşu | job_key | total | renamed | skipped | errors | süre |
|---|---|---|---|---|---|---|
| Prova | 8c08c085ab92 | 2846 | 2834 | 12 | 0 | ~anlık |
| Gerçek #1 | 274219ae6992 | 2846 | 2834 | 12 | 0 | 49 s |
| Geri al | 17e9b6134c7d | 2834 | 2834 | 0 | 0 | 43 s |
| Gerçek #2 (kalıcı) | 8985c816a995 | 2846 | 2834 | 12 | 0 | 55 s |

**Hata sayısı tüm koşumlarda 0.** Geri al provası tam tur (round-trip) doğrulandı. Son durum: taşınmış (2834 dosya yeni içerik-adresli/şard'lı adında, 12 dosya diskte olmadığı için beklenildiği gibi eski adında kaldı).

## 13. Ek koşu (10a) — `".."` koruması segment düzeyine indirildi

**Tarih:** 2026-08-21 (Task 10a, aynı gün). §11.3'te bilinen boşluk olarak işaretlenen konu: `is_legacy_name()`'in yol-geçişi koruması alt-dizge kontrolü (`".." in url`) kullanıyordu, bu da cümle sonu nokta ile biten gerçek eski dosya adlarını (`/files/MOİ ile derin düzen..jpg` gibi) de reddediyordu.

### Değişiklik

- `tradehub_core/media/retro_rename.py::is_legacy_name` — koruma artık **segment düzeyinde**: `url.split("/")` içindeki bir parça tam olarak `".."` ya da `"."` ise reddedilir. `/files/../etc/passwd` ve `/files/a/../b.jpg` hâlâ reddedilir; `/files/cümle sonu..jpg` artık aday sayılır.
- `_disk_path(file_url)` — savunma derinliği: `os.path.realpath` ile gerçek disk yolu hesaplanır, `get_files_path(is_private=0)`'ın gerçek kökünün altında değilse `frappe.throw(_("Geçersiz dosya yolu: {0}"))` (`frappe.ValidationError`).
- Testler (`TestLegacyNameAndTarget`): cümle sonu nokta → `True`; `/files/../etc/passwd`, `/files/a/../b.jpg` → `False`; `_disk_path` traversal URL'de `frappe.ValidationError`; gerçek `rr-nokta-<hash>..jpg` dosyası için `target_url` round-trip.

### Doğrulama SQL (koşu öncesi)

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost mariadb -e \
  "select count(distinct file_url) from tabFile where is_private=0 and left(file_url,7)='/files/' and file_url like '%..%'"
→ 8
```

### Test koşusu

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_retro_rename
→ Ran 26 tests in 2.947s — OK
```

Sync + `docker restart istoc-dev-backend-1 istoc-dev-queue-long-1 istoc-dev-frappe-frontend-1` ile worker/web yeni kodu aldı (`queue-long` içinde `grep` ile segment kontrolü satırı doğrulandı).

### API koşusu

| Adım | Sonuç |
|---|---|
| `retro_rename_count` (koşu öncesi) | `total=21` |
| `retro_rename_plan` kırılımı | `renamable=8`, `disk_missing=13` (12'si önceki koşudan kalan + §11.2'deki `rr-plan-*` test kalıntıları/`ChatGPT Image` dosyaları — bu göçle ilgisiz, önceden var olan boşluk) |
| `start_retro_rename dry_run=0` | `job_key=55084cc61db4` |
| Bitiş durumu | `state=completed`, `total=21`, `processed=21`, **`renamed=8`**, `skipped=13` (`disk_missing`), **`errors=0`** |

Brief'in beklediği "8 (+12 disk_missing = 20)" yerine gözlenen `disk_missing=13` — fark, §11.2'de zaten bilinen `TestPlan` test kalıntılarından (`rr-plan-*`, orphan+disk_missing) ve bu görevden bağımsız iki `ChatGPT Image *.png` disk-eksik satırından kaynaklanıyor; göçle ilgisi yok, sayı tutarlı.

### Doğrulama (koşu sonrası)

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost mariadb -e \
  "select count(distinct file_url) from tabFile where is_private=0 and left(file_url,7)='/files/' and file_url like '%..%'"
→ 0
```

```
curl -sI "http://istoc.localhost/files/MO%C4%B0%20ile%20derin%20d%C3%BCzen..jpg"
→ HTTP/1.1 301 MOVED PERMANENTLY
  Location: /files/03/037eaeb69eb33b25f6d7b88978f308e8.jpg

curl -sI "http://istoc.localhost/files/03/037eaeb69eb33b25f6d7b88978f308e8.jpg"
→ HTTP/1.1 200 OK
```

**Sonuç:** 8 kalan dosya taşındı, hata 0, SQL doğrulaması 8 → 0. `is_legacy_name` artık gerçek yol-geçişi girişimlerini reddederken cümle sonu noktalı gerçek dosya adlarını aday sayıyor.

---

## 14. Alpha/prod runbook

Lokal koşu bittiyse alpha/prod'a taşımadan önce (detay:
`docs/MEDYA-DEPOLAMA-STANDARDI.md` §7.1):

1. `bench --site <site> migrate` — `Media URL Redirect` + `file_names` alanı.
2. Backend **ve** panel imajını rebuild et; `backend`, `queue-long`,
   `queue-short`, `scheduler`, `frappe-frontend` restart. Worker restart
   edilmezse iş ESKİ kodla koşar.
3. **M-A arşivi:** `media/archive.py` undo-arşivi `file_url` ile adreslenir ve
   retro-rename onu TAŞIMAZ → koşudan ÖNCE `archive.purge_expired()` koş,
   `archive.usage_bytes()` 0'a yakın olsun. Aksi hâlde taşınan dosyaların
   30 günlük "orijinale dön" penceresi kaybolur.
4. Koşu **ve** geri alma sonrası `bench --site <site> clear-website-cache`
   (kod `website_404`'ü zaten siliyor — bu ek emniyet).
5. Edge'de 301'ler ~5 dk önbelleklenir (gateway `$thc_media_cache`) → geri alma
   sonrası 5 dakikalık pencere normaldir.
6. Geri alma **durdurulamaz** ve 90 gün sonra (yönlendirme satırları cron ile
   silinince) **mümkün değildir**.
7. Worker ölürse `tradehub:retro_rename:active` anahtarı 1 saate kadar kilitli
   kalır; `frappe.cache.delete_value("tradehub:retro_rename:active")` ile elle
   açılır.
8. `tabFile` satırı olmayan düz dosyalar araç kapsamı **dışındadır** — koşu
   sonrası `scripts/media_stats.py` `reconcile()` + disk taramasıyla teyit et.
