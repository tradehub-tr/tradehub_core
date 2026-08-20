# T-052 — CDN teslim katmanı ve imzalı URL'ler

**Tarih:** 2026-08-19 · **Ortam:** `istoc.localhost` (docker compose, `istoc-dev`) · **Dal:** `ahmet`
**Şartname:** <https://karacaismail.github.io/imageoptimization/docs/42-faz5-depolama-s3-cdn.html>

> Bu belgedeki her iddia bir komut çıktısına dayanıyor. Koşturulmayan hiçbir şey
> "geçti" olarak yazılmadı; koşturulamayanlar §8'de açık bulgu olarak duruyor.

---

## 1. Ne yapıldı — özet

| # | İş | Yer | Durum |
|---|---|---|---|
| 1 | İçerik-adresli türev → `immutable` + 1 yıl | `docker/nginx/gateway.conf` | ölçüldü ✅ |
| 2 | Ham yükleme → kısa TTL + zorunlu doğrulama | `docker/nginx/gateway.conf` | ölçüldü ✅ |
| 3 | Private + imzalı uçnokta → `private, no-store` | `docker/nginx/gateway.conf` | ölçüldü ✅ |
| 4 | gzip tip listesi (görsel/video HARİÇ) | `docker/nginx/gateway.conf` | ölçüldü ✅ |
| 5 | `sendfile` / byte-range | mevcut durum ölçüldü, değişiklik gerekmedi | ölçüldü ✅ |
| 6 | İmzasız / süresi dolmuş → 403 | mevcut davranış doğrulandı | ölçüldü ✅ |
| 7 | **İmzalı URL ↔ blob bağı** (yeni açık kapatıldı) | `tradehub_core/api/media_access.py` | ölçüldü + testli ✅ |

**Dokunulan dosyalar**

- `docker/nginx/gateway.conf` (+91 satır) — **`docker/` git reposu DEĞİL, bu değişiklik versiyonlanmıyor** (§8).
- `tradehub_core/tradehub_core/api/media_access.py` (+~70 satır)
- `tradehub_core/tradehub_core/tests/test_media_access_blob_binding.py` (yeni, 11 test)

**Dokunulmadı:** `media/file_isolation.py`, `media/browse.py`, `api/seller_media.py`,
`api/media_manifest.py`, `media/pipeline/storage/*`, `docs/standards/`, `admin-panel`,
`tradehubfront`. `Media Engine Settings` bayrakları 0'da bırakıldı (§6.4).

---

## 2. Kaynak şablon mu, üretilmiş şablon mu — tuzağın neresinde durduk

Önceki denetimin bulduğu tuzak: `/files/` için `limit_req` + `X-Robots-Tag noindex`
yalnız **üretilmiş** `docker/nginx/storefront.local.template`'de vardı; kaynağı olan
`tradehubfront/nginx.conf.template`'de yoktu. `gen-local-nginx.sh` bir sonraki koşumda
üretilmiş dosyayı ezip o korumayı sessizce silecekti.

Ölçüm — bugün de hâlâ öyle:

```
$ diff tradehubfront/nginx.conf.template docker/nginx/storefront.local.template
203a204,210
> limit_req_zone $binary_remote_addr zone=files_zone:10m rate=10r/s;
364a359,362
> add_header X-Robots-Tag "noindex" always;
> limit_req zone=files_zone burst=20 nodelay;
```

**Bu görevin değişiklikleri o sınıfa girmiyor.** Sebep — `gen-local-nginx.sh` yalnız
iki dosya üretiyor:

```bash
gen "$root/tradehubfront/nginx.conf.template"        "$here/nginx/storefront.local.template"
gen "$root/admin-panel/frontend/nginx.conf.template" "$here/nginx/admin-panel.local.template"
```

`docker/nginx/gateway.conf` bu listede **yok**: elle yazılmış bir kaynak dosya ve
compose onu doğrudan mount ediyor (`./nginx/gateway.conf:/etc/nginx/conf.d/default.conf:ro`).
Yani gen script'i onu ezmez.

### Kapsam çatışması — açıkça kayda geçiyorum

Görev tanımı "değişiklik **kaynak** şablonda olsun" diyor; medya teslimi için gerçek
prod kaynağı `tradehubfront/nginx.conf.template`. Aynı görev tanımı `tradehubfront`'u
**DOKUNMA** listesine koyuyor. İkisi aynı anda sağlanamaz.

Seçim: yasağa uyuldu, değişiklik dokunmama izni olan tek gerçek kaynağa —
`gateway.conf`'a — yazıldı. Prod'a taşıma notu §8.2'de; uygulanmadı, çünkü
hedef dosya bu görevde kapalı.

---

## 3. Cache başlıkları — ayrım ve gerekçe

### 3.1 Neden iki sınıf

Türevler `media/naming.py` ile içerik-adresli yazılıyor:

```
/files/<ilk 2 hex shard>/<sha256(içerik)[:32]>.<uzantı>
```

İçerik değişirse ad değişir → **aynı URL asla başka bir bayt dizisi döndüremez**.
`immutable` (RFC 8246) tam olarak bu koşulu şart koşar: tarayıcı sayfa yenilemede
bile koşullu istek atmaz.

Ham yüklemeler (`/files/Bere-1.png`) **aynı adla üzerine yazılabilir**. Onlara
`immutable` vermek, bir görsel güncellendiğinde kullanıcıya bir yıl boyunca eski
görseli göstermek demek — ve geri dönüşü yok, çünkü cache-busting için URL
değiştirilemiyor (ad sabit). Bu yüzden kısa TTL + zorunlu doğrulama.

Ayrım nginx tarafında tek bir `map` ile yapılıyor:

```nginx
map $uri $thc_media_cache {
    default                                            "public, max-age=300, must-revalidate";
    "~^/files/[0-9a-f]{2}/[0-9a-f]{32}\.[A-Za-z0-9]+$"  "public, max-age=31536000, immutable";
}
```

Diskteki dağılım (ölçüm): 663 dosya shard'lı içerik-adresli düzende, geri kalanı
orijinal adlı ham yükleme — yani iki sınıf da gerçekten var, kural teorik değil.

### 3.2 Kanıt — `curl -I`, üç dosya sınıfı ayrı ayrı

**a) Türev (içerik-adresli)**

```
$ curl -sI http://istoc.localhost/files/12/12f6549589ea9b171f905dd811ed3049.webp
HTTP/1.1 200 OK
Content-Type: image/webp
ETag: "6a85a91e-54"
Accept-Ranges: bytes
X-Robots-Tag: noindex
Cache-Control: public, max-age=31536000, immutable
```

**b) Ham yükleme**

```
$ curl -sI http://istoc.localhost/files/Bere-1.png
HTTP/1.1 200 OK
Content-Type: image/png
ETag: "6a325da7-16dde"
Accept-Ranges: bytes
X-Robots-Tag: noindex
Cache-Control: public, max-age=300, must-revalidate
```

**c) Özel dosya (private, oturumsuz)**

```
$ curl -sI http://istoc.localhost/private/files/Bere-1.png
HTTP/1.1 403 FORBIDDEN
Cache-Control: private, no-store
```

Ve imzalı indirme uçnoktası (bu bir GET; `curl -I` kullanılamaz — §7.1):

```
$ curl -s -D - -o /dev/null ".../media_access.download?<geçerli imza>"
HTTP/1.1 200 OK
Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet
Content-Length: 634926
Cache-Control: private, no-store
```

**Değişiklikten ÖNCEKİ hâl:** `/files/` yanıtlarında **hiç `Cache-Control` yoktu**.
Tarayıcılar bu durumda sezgisel (heuristic) cache uyguluyor — yani süre
belirsizdi, hem türevde hem ham dosyada. Ayrım artık açık ve ölçülü.

`Cache-Control` her yanıtta **tek satır**: `add_header`'dan önce
`proxy_hide_header Cache-Control/Expires/Pragma` var, yoksa upstream ileride
kendi başlığını basarsa `add_header` onu ezmez, ikinci bir başlık ekler ve
hangisinin kazandığı istemciye kalırdı.

```
$ curl -sI .../files/Bere-1.png | grep -ci cache-control      → 1
$ curl -sI .../files/12/...webp | grep -ci cache-control      → 1
```

### 3.3 Zincir kısaltılmadı

`location ^~ /files/` hedefi **frappe-frontend değil, storefront**. Storefront'un
kendi `^~ /files/` bloğu enumeration sertleştirmesini (`limit_req files_zone` +
`X-Robots-Tag noindex`) uyguluyor; gateway'den doğrudan backend'e gitmek o korumayı
sessizce devre dışı bırakırdı. Yanıtta `X-Robots-Tag: noindex`'in hâlâ görünmesi
(§3.2 a/b) zincirin korunduğunun kanıtı.

---

## 4. sendfile, gzip, byte-range

### 4.1 sendfile — değişiklik gerekmedi, ölçüldü

`sendfile` yalnız diskten dosya okuyan katmanda anlamlı. Bu zincirde medyayı
gerçekten diskten veren katman **frappe-frontend**; gateway ve storefront o istek
için saf proxy (root yok).

```
$ docker compose exec frappe-frontend grep -n "sendfile\|tcp_nopush" \
      /etc/nginx/nginx.conf /etc/nginx/conf.d/frappe.conf
/etc/nginx/nginx.conf:17:	sendfile on;
/etc/nginx/nginx.conf:18:	tcp_nopush on;
/etc/nginx/conf.d/frappe.conf:81:	sendfile on;
```

Zaten açık ve `tcp_nopush` ile eşlenmiş. Gateway'e kozmetik bir `sendfile on;`
yazmadım — orada ölçülebilir etkisi olmaz; bunun yerine `gateway.conf`'a durumu
anlatan bir yorum bloğu koydum.

### 4.2 gzip — hangi tiplerde açık ve neden

`gateway.conf`'a eklenen liste **hiçbir raster/video MIME tipi içermiyor**; tek
"görsel" giriş `image/svg+xml` — o bir XML metni, gerçekten sıkışır.

Gerekçe: JPEG/PNG/WebP/AVIF/MP4 zaten entropi kodlanmış. gzip onlarda tipik olarak
%0–2 kazanç sağlarken her istekte CPU harcar ve `Content-Length`'i değiştirdiği
için **byte-range teslimini bozar** (nginx gzip'lenen yanıtta `Accept-Ranges`'i
kaldırır) — video seek'i doğrudan bunun kurbanı olur.

Ölçüm:

```
$ curl -sI -H 'Accept-Encoding: gzip, br' .../files/06/067203c7...jpg
Content-Type: image/jpeg
Content-Length: 551351            ← Content-Encoding YOK, sıkıştırılmadı

$ curl -sI -H 'Accept-Encoding: gzip, br' .../files/9mb.mp4
Content-Type: video/mp4
Content-Length: 9622535           ← Content-Encoding YOK

$ curl -sI -H 'Accept-Encoding: gzip' .../files/12/...webp
Content-Type: image/webp          ← Content-Encoding YOK

$ curl -sI -H 'Accept-Encoding: gzip' http://istoc.localhost/
Content-Type: text/html
Content-Encoding: gzip            ← metin sıkıştırıldı

$ curl -sI -H 'Accept-Encoding: gzip' http://istoc.localhost:8001/api/method/ping
Content-Type: application/json
Content-Encoding: gzip            ← JSON sıkıştırıldı
```

### 4.3 byte-range — 206 + tam 100 bayt

**Video (asıl gerekçe — seek):**

```
$ curl -s -r 0-99 -D - -o /tmp/r1.bin http://istoc.localhost/files/9mb.mp4
HTTP/1.1 206 Partial Content
Content-Type: video/mp4
Content-Length: 100
Content-Range: bytes 0-99/9622535
Cache-Control: public, max-age=300, must-revalidate

$ wc -c < /tmp/r1.bin
100
```

**Türev dosyası (içerik-adresli, 551 KB):**

```
$ curl -s -r 0-99 -D - -o /tmp/r2.bin .../files/06/067203c7a75c388415531e2a37953ef9.jpg
HTTP/1.1 206 Partial Content
Content-Length: 100
Content-Range: bytes 0-99/551351
Cache-Control: public, max-age=31536000, immutable

$ wc -c < /tmp/r2.bin
100
```

**Baştan değil, ortadan bir aralık** (gerçek seek davranışı):

```
$ curl -s -r 1000-1099 .../files/9mb.mp4
HTTP/1.1 206 Partial Content
Content-Range: bytes 1000-1099/9622535   → 100 bayt
```

Not: `Accept-Ranges` başlığı bilinçli olarak gateway'de **basılmıyor**. Upstream
onu yanıt bazında doğru üretiyor; `always` ile sabitlemek, sıkıştırılmış bir
yanıtta desteklenmeyen range'i reklam etmek olurdu. (İlk denemede sabitlemiştim,
yanıtta çift `Accept-Ranges` çıktı — geri alındı.)

---

## 5. İmzalı URL — 403 kanıtları

Tümü **GET** ile ölçüldü (§7.1).

| Senaryo | Beklenen | Ölçülen |
|---|---|---|
| İmza parametresi hiç yok | 403 | **403** |
| Bozuk imza (`_signature=deadbeef`) | 403 | **403** |
| Hiç parametre yok | 403 | **403** |
| Geçerli imza, `exp` geçmişte | 403 | **403** |
| Geçerli imza, süre içinde | 200 | **200** (634 926 bayt, gerçek xlsx) |

```
$ curl -s -o /dev/null -w '%{http_code}\n' ".../download?file=/private/files/Bere-1.png&exp=9999999999"
403
$ curl -s -o /dev/null -w '%{http_code}\n' ".../download?...&_signature=deadbeef"
403
$ curl -s -o /dev/null -w '%{http_code}\n' ".../download"
403
$ curl -s -o /dev/null -w '%{http_code}\n' ".../download?<süresi dolmuş imza>"
403
```

403 gövdesi de doğru: "Bağlantı geçersiz." / "Bağlantının süresi doldu." —
404 değil, 200 değil.

---

## 6. Ölçülen açık: imzalı URL, `file_isolation`'ı atlıyordu

### 6.1 Ölçüm

`download()` guest'e açık ve **hiçbir `File` satırı yüklemiyor**: imzayı doğrulayıp
`send_private_file` çağırıyor. Bu yüzden `media/file_isolation.py`'nin iki
daraltması da bu yolda çalışmıyordu:

- `TenantIsolatedFile.is_downloadable()` (kiracı kuralı **+** `blob_matches_row`)
  yalnız `find_file_by_url` → `frappe.get_doc("File", ...)` yolunda çağrılıyor.
  `download()`'da öyle bir çağrı yok.
- `file_has_permission` kancası imzalama anında (`has_permission("read")`)
  çalışıyor ama **`blob_matches_row`'u çağırmıyor** — o kontrol yalnız
  `is_downloadable()` içinde.

Sitedeki gerçek veri (2026-08-19):

```
BELİRSİZ ÖZEL URL (aynı file_url, ≥2 farklı content_hash) = 5
   13 satır / 2 hash -> /private/files/469119194_122137766276501686_...jpg
   10 satır / 2 hash -> /private/files/71MwppYj0KL._AC_SX679_.jpg
    8 satır / 2 hash -> /private/files/Adsız tasarım (4).jpg
   18 satır / 2 hash -> /private/files/images0ed56d.jpeg
    4 satır / 2 hash -> /private/files/mugiss-mutfak-ve-ev-gerecleri-...
ÇOK SATIRLI ÖZEL URL = 111
```

Yani oturumla indirmesi reddedilen bir satırın sahibi, aynı URL için imzalı link
alıp diskteki (başka kiracıya ait) blob'u indirebiliyordu.

**Sızıntının canlı kanıtı** — değişiklikten önce, `blob` parametresi olmayan bir
imzayla belirsiz bir URL:

```
$ curl -s -o /dev/null -w '%{http_code}\n' ".../download?file=/private/files/images0ed56d.jpeg&exp=...&_signature=..."
200        ← ESKİ KOD: servis etti
```

### 6.2 Kapatma — iki yerde

1. **`get_signed_url`** — yetki kontrolünden sonra `file_isolation.blob_matches_row(file_doc)`
   kapısı. Satırı diskteki blob'u temsil etmeyen çağıran için **imza üretilmez**
   (red `blob_mismatch` sebebiyle audit'e yazılır).
2. **`download`** — imza artık `blob` (= satırın `content_hash`) parametresini de
   **kapsıyor**; `_blob_binding_ok()` belirsiz URL'de diskteki md5 ile karşılaştırır.

Masraf kontrolü: `_url_is_ambiguous` tek `COUNT(DISTINCT content_hash)` sorgusu ve
5 dk cache'li. URL belirsiz DEĞİLSE (vakaların ~%99'u) md5 **hiç hesaplanmaz** —
bunun kendisi bir test (`test_belirsiz_olmayan_url_de_md5_hesaplanmaz`).

**Politika asimetrisi (bilinçli):** `blob_matches_row` karar veremediğinde
(hash yok / dosya okunamıyor / 64 MB üstü) `True` döner — orada güvenli, çünkü
ALTINDA kiracı kuralı zaten çalışmıştır. `download()` guest yolunda altta hiçbir
şey yok, tek yetki kanıtı imza — bu yüzden orada **fail-closed**.

### 6.3 Canlı kanıt — değişiklikten sonra

```
BELİRSİZ URL / blob YOK      : 403
BELİRSİZ URL / YANLIŞ blob   : 403
BELİRSİZ URL / DOĞRU blob    : 200  (15 574 bayt)
BELİRSİZ OLMAYAN / blob YOK  : 200   ← geriye dönük uyum korundu
```

Sondaki satır önemli: bu değişiklikten önce üretilmiş linkler `blob` taşımıyor.
Belirsiz olmayan URL'de (vakaların ~%99'u) hangi bloba yetki verildiği zaten tek,
o yüzden reddetmek meşru erişimi kırardı. Belirsiz URL'de reddediliyorlar; etki
penceresi `MAX_TTL_SECONDS` = 24 saat.

### 6.4 Testler

Yeni: `tradehub_core/tests/test_media_access_blob_binding.py` — 11 test.

```
$ bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access_blob_binding
Ran 11 tests in 2.432s
OK
```

Regresyon (üçü de değişiklik sonrası):

```
tradehub_core.tests.test_media_access              → Ran 17 tests   OK
tradehub_core.tests.test_file_multirow_isolation   → Ran 15 tests   OK
tradehub_core.tests.test_media_access_level        → Ran 15 tests   OK
```

`Media Engine Settings` bayrakları koşum sonunda hâlâ 0:

```
media_pipeline_enabled = 0
manifest_api_enabled   = 0
rendition_on_upload    = 0
active_slots           = (boş)
```

---

## 7. Meşru erişim kırılmadı

Değişikliklerin (nginx reload + backend restart) **sonrasında** ölçüldü:

```
/files/Bere-1.png          : 200
/panel/                    : 200
:8001 /api/method/ping     : 200
storefront /               : 200
/files/<türev>             : 200
/assets/<storefront dist>  : 200
:8001 /app                 : 301   (Frappe'nin normal /app → /app/ yönlendirmesi)
```

### 7.1 Ortam tuzakları — yaşananlar

**a) `curl -I` imzalı uçnoktada yanıltıyor.** Frappe whitelist handler'ı HEAD
metodunu kabul etmiyor; `curl -I` her koşulda **403** döndürüyor — geçerli imzada
bile. Bir noktada "geçerli imza da 403" diye yanlış sonuca vardım; GET'e
(`curl -s -D - -o /dev/null`) geçince 200 ve gerçek xlsx geldi. İmzalı uçnokta
ölçümlerinin hepsi GET.

**b) `docker compose exec backend` ile bench script'i `sites/` dizininden
çalıştırılmalı** — `frappe.init(site=...)` bench kökünden `IncorrectSitePath`
veriyor.

**c) Backend uygulama kodu imaja gömülü, bind-mount DEĞİL.** `docker inspect`:

```
volume istoc-dev_sites -> /home/frappe/frappe-bench/sites
volume istoc-dev_logs  -> /home/frappe/frappe-bench/logs
```

`apps/` yok. Yani host'taki `.py` düzenlemesi çalışan konteyneri **etkilemiyor**.
Ölçüm için `docker cp` + `docker compose restart backend` kullanıldı.
`restart` konteyneri yeniden yaratmadığı için **IP değişmedi** (ölçüldü:
`192.168.97.5` → `192.168.97.5`), 502 tuzağına düşülmedi. `docker cp` geçici:
imaj yeniden derlenene kadar konteynerde duruyor, `compose build backend`
gerektiğinde kaynak yine host repo'sudur.

**d)** Compose dosyasına bu görevde **dokunulmadı** — gereken her şey mount'lu
`gateway.conf` içinde yapılabildi, dolayısıyla servis yeniden yaratılmadı.

---

## 8. Açık bulgular / devir notları

1. **`docker/` bir git reposu değil.** `docker/nginx/gateway.conf`'taki 91 satır
   versiyonlanmıyor — makine değişirse ya da klasör silinirse kaybolur.
   Bu dosyanın bir repoya alınması ayrı bir iş.

2. **Prod eşdeğeri uygulanmadı.** Gateway, prod'daki host-nginx vhost'unun local
   taklidi. Aynı `map` + `location` bloklarının prod edge'ine (ya da CDN kuralına)
   taşınması gerekiyor. Alternatif ve daha kalıcı yer
   `tradehubfront/nginx.conf.template` — bu görevde **DOKUNMA** listesinde
   olduğu için uygulanmadı (§2). Yamanın içeriği `gateway.conf`'ta hazır.

3. **`tradehubfront/nginx.conf.template` ↔ üretilmiş şablon ayrışması sürüyor.**
   `limit_req files_zone` + `X-Robots-Tag noindex` hâlâ yalnız üretilmiş dosyada.
   `gen-local-nginx.sh` bir sonraki koşumda bunları silecek ve prod zaten hiç
   almamış durumda. Bu görevin kapsamında değildi, kapatılmadı.

4. **`file_isolation`'ın alt çizgili yardımcıları dışarıdan çağrılıyor.**
   `media_access._blob_binding_ok` → `file_isolation._url_is_ambiguous` /
   `_blob_hash`. O modül bu görevde değişime kapalıydı, public sarmalayıcı
   eklenemedi. Devir: `url_is_ambiguous()` / `blob_hash()` orada public'e
   çıkarılmalı.

5. **`frappe.get_doc("File", {"file_url": ...})` çok satırlı URL'de
   deterministik değil** (`media_access.get_signed_url`, mevcut kod). Hangi satırın
   çözüleceği garanti değil. Güvenlik açısından sorun yok — belirsiz URL'de her iki
   dal da reddediyor (test: `test_eslesmeyen_satirin_sahibi_imza_alamaz`) — ama
   meşru sahip için sonuç satır sırasına bağlı olabilir. Ayrı iş.

6. **Ham yükleme TTL'i 300 sn seçildi.** Üzerine yazılabilir dosyada 5 dk
   bayatlık kabul edildi; `must-revalidate` ile sonrası ETag/Last-Modified turu
   (ikisi de upstream'de var, ölçüldü). Daha katı bir gereksinim çıkarsa
   `no-cache`'e düşürmek tek satır.

7. **Cache başlıkları yalnız :80 (public giriş) tarafında.** `:8001`
   (Frappe Desk / REST) sunucu bloğuna `/files/` cache kuralı eklenmedi —
   orası medyanın public teslim yolu değil. Ölçüm: `:8001/files/...` yanıtında
   `Cache-Control` yok. Bilinçli kapsam kararı; :8001 bir gün public'e açılırsa
   aynı `map` oraya da bağlanmalı.

8. **Ölçüm hatası düzeltmesi (kayda geçiyorum).** İlk taramada
   `/files/sitemaps/*.xml` için "gzip'lenmiyor" sonucuna vardım — hatalıydı:
   `curl -I` varsayılan olarak `Accept-Encoding` göndermiyor. Açık başlıkla
   tekrar ölçüldü, `text/xml` gateway'in yeni `gzip_types` listesi sayesinde
   sıkışıyor (`Content-Encoding: gzip`, hem 689 baytlık hem büyük sitemap'te).
   frappe-frontend'in kendi listesinde `text/xml` yok; gateway bu boşluğu
   kapatıyor.
