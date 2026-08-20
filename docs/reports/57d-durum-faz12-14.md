# 57d — Faz 12 · 13 · 14 durum ölçümü (akşam koşumu)

**Tarih:** 2026-08-19 · **Koşum penceresi:** **22:28:20 – 22:47:14** · **Depo:**
`tradehub_core` (`ahmet`, HEAD `1ec9b5e`) · **Ortam:** `istoc.localhost`
(Docker, `istoc-dev-backend-1`) · **Kaynak kriterler:**
`karacaismail.github.io/imageoptimization/docs/70-faz12-headless-teslim.html`,
`71-faz13-guvenlik-observability.html`, `72-faz14-test-kabul.html` (bu koşumda
üçü de indirildi ve kriterler oradan okundu).

> **Salt okuma.** Yazılan tek üretim-dışı dosya budur. Hiçbir üretim dosyası
> değiştirilmedi.
>
> 🔒 **`Media Engine Settings` bayraklarına DOKUNULMADI.** Koşum başında
> (22:34:13) ve sonunda (22:47:14) üçü de **0**:
> `media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0`.
> **T-124 ölçümü TEKRARLANMADI** — yalnız tutarlılığı denetlendi (§2.1).
>
> ⏱️ **Her ölçümün saati yazılıdır.** Koşum sırasında **7 ajan aynı depoda kod
> yazıyordu**; bu yüzden aynı dosya iki farklı dakikada iki farklı hâlde
> ölçüldü (§3.3 — `/metrics` kablolaması gözümün önünde tamamlandı).
>
> 🚫 **Süre/performans iddiası YOKTUR.** `bench migrate` koşulmadı.

---

## 0. Yöntem etiketleri

| Etiket | Anlamı |
|---|---|
| **[T]** | `bench run-tests` koşuldu, sonucu ve saati bu belgede |
| **[Ö]** | Canlı sistemde ölçüldü (site DB / çalışma anı meta) |
| **[H]** | Gerçek HTTP — `curl`, gateway ya da backend üzerinden |
| **[D]** | Diskte/dosya sisteminde doğrudan sayıldı |
| **[K]** | Kod okundu — `dosya:satır` |
| **ÖLÇÜLMEDİ** | Ölçülemedi; sebebi yazılı |

**Engelleyen etiketleri:** `—` (yok) · `AJAN` (kod/belge yazılması gerekiyor) ·
`KARAR` (insan kararı bekliyor) · `ARAÇ` (tarayıcı/ffmpeg-libvmaf/k6 gibi araç
yok) · `İNSAN` (gerçek satıcı, imza, üretim ortamı gerekiyor).

---

## 1. Bu koşumda koşulan testler — ham sonuç

Hepsi `bench --site istoc.localhost run-tests --skip-before-tests --module tradehub_core.tests.…`

> ⚠️ `--skip-before-tests` **zorunluydu**: `helpdesk` uygulamasının
> `before_tests` kancası paralel ajan yazımı yüzünden
> `TimestampMismatchError` ile düşüyor (22:38:06 [T]). Yani **bugün standart
> `bench run-tests` çağrısı bu makinede çalışmıyor** — bu, testlerin değil
> ortamın arızası.

| Modül | Sonuç | Saat | Görev |
|---|---|---|---|
| `test_delivery_picture` | **Ran 24 — OK** | 22:42:58 | T-120 |
| `test_delivery_sizes` | **Ran 22 — OK** | 22:43:02 | T-121 |
| `test_delivery_rum` | **Ran 26 — OK** | 22:42:55 | T-123 |
| `test_verification_status_guard` | **Ran 14 — OK** | 22:39:43→22:40:35 | T-135/T2-T3 |
| `test_authz_regression` | **Ran 24 — OK** (0,393 sn, frappe'siz) | 22:40:35 | T-132 |
| `test_payment_transaction_isolation` | **Ran 12 — OK** | 22:40:41→22:42:24 | T-135/T1 |
| `test_rate_limit_guest_bucket` | **Ran 15 — OK** | 22:42:24 | T-135/T9 |
| `test_svg_sanitize` | **Ran 52 — OK (skipped=3)** | 22:42:30 | T-131 |
| `test_media_security_svg` | **Ran 10 — OK** | 22:42:33 | T-131 |
| `test_observability_instrument` | **Ran 26 — OK** | 22:42:37 | T-133 |
| `test_observability_exporter` | **Ran 19 — OK** | 22:42:41 | T-133 |
| `test_observability_alerts` | **Ran 20 — OK** | 22:42:45 | T-133 |
| `test_audit` | **Ran 18 — OK** | 22:42:48 | T-134 |

**Toplam bu koşumda: 262 test, 262'si yeşil, 3 atlandı** (atlama gerekçeleri
`test_svg_sanitize.py:353,431,455` — eksik fixture/depo, bulgu değil).

🔴→✅ **Sabahki tek kırmızı test bugün yeşil.** `36-dogrulama-faz12-14.md` §3.3
`test_verification_status_guard`i **14 test, 1 FAIL** olarak ölçmüştü
(`status permlevel-4'te değil: 1 != 4`). Bu koşumda **14/14 OK** — çünkü
aradan `bench migrate` geçmiş (§3.2).

---

## 2. FAZ 12 — Headless teslim ve performans

### 2.1 T-124 çapraz kontrolü — `DALGA-A-DEVIR.md` bugün de tutarlı mı?

**Ölçüm TEKRARLANMADI, tutarlılık denetlendi** (22:34:13–22:34:36):

| İddia (`DALGA-A-DEVIR.md`) | Bu koşumda ölçülen | Tutarlı? |
|---|---|:--:|
| En ağır sayfa `LST-00560`, **7 görsel** | `primary_image` 1 + `Listing Image` 6 = **7** [Ö] | ✅ |
| Ham toplam **9,99 MB** | **10 476 759 B = 9,9914 MB** [D] — dosya dökümü sabahki raporla **bayt bayt aynı** | ✅ |
| Bayraklar 0 | `media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0` [Ö] | ✅ |
| Türevler geri alındı | `Media Rendition` **0**, `Media Asset` **0**, `Media Processing Job` **0** [Ö]; diskte `.avif` **0** (public+private) [D] | ✅ |
| `Media Profile` = 36 | **36** [Ö] | ✅ |
| `File` 5014 | **5042** [Ö] — +28; **T-124 kaynaklı değil**, bugün paralel ajanların yüklediği dosyalar (bayraklar kapalı, türev üretilmedi) | ⚠️ açıklanabilir |

**Karar: T-124'ün bayt tarafı bugün de tutarlı.** Girdi (9,99 MB) ve geri alma
(türev 0, `.avif` 0) bağımsız olarak yeniden doğrulandı. **Senaryo A/C/D
çıktıları (0,617 / 0,186 / 0,145 MB) yeniden üretilmedi** — bayrak açmak
gerekirdi, yasaktı, gerek de yoktu.

### 2.2 Faz 12 görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|:--:|---|---|
| **T-120** | MediaImage / MediaVideo teslim bileşenleri | `<picture>` AVIF→WebP→JPEG · `priority`→eager+`fetchpriority=high` · `width/height` hep (CLS 0) · LQIP geçişi · rendition yoksa düzgün yedek · **video: poster, muted-autoplay-loop, playsinline, HLS tembel, reduced-motion** | **KISMİ** | Backend `media/pipeline/delivery/picture.py` **24/24 OK** [T 22:42:58]. Storefront `ResponsiveImage.ts`: `width/height` zorunlu (`:223-225,277-278`), `priority`→`fetchpriority=high`+`loading` yazılmıyor (`:246-252`), rendition yoksa zorunlu `fallback()` (`:71,270`) [K]. 🔴 **LQIP frontend'de YOK** (`lqip\|blurhash\|thumbhash` → 0 sonuç; backend'de `picture.py:272 lqip_style` var, çağıran yok). 🔴 **`MediaVideo` YOK** (22:43:08 [D]): `ProductVideoSection.ts:62-63` poster yok, loop yok, reduced-motion yok, hls.js paketi bile yok. **CLS=0 ÖLÇÜLMEDİ** (tarayıcı yok) | **AJAN** · ARAÇ |
| **T-121** | `sizes` gerçek düzenden türetilmesi | `sizes` gerçek CSS'ten türetilmiş ve **dokümante** · **seçilen rendition ↔ gerçek kutu farkı ≤ %25** · yanlış `sizes` için otomatik test · rapor `docs/reports/120-sizes-dogrulama.md` | **KISMİ** | `delivery/sizes.py` **22/22 OK** [T 22:43:02]. Türetme kanıtlı: `sizes.ts`teki 15 dizge, `python3 -m …delivery.sizes` çıktısıyla birebir; CLI koşumu **71 satır doğrulandı, açıklanmamış sapma 0** [Ö]. Kaynak referansı `sizes.ts:6-33` [K]. 🔴 **≤ %25 sapma ÖLÇÜLMEDİ** — kriter `currentSrc` genişliği ↔ `getBoundingClientRect().width × DPR` karşılaştırması istiyor; depoda `currentSrc` **0 sonuç**, Playwright kurulu ama bu test yazılmamış. 🔴 **`docs/reports/120-sizes-dogrulama.md` YOK** [D] | ARAÇ · AJAN |
| **T-122** | LCP optimizasyonu ve preload | LCP elementi `priority` · **`<link rel=preload imagesrcset imagesizes>` üretiliyor** · carousel'de yalnız ilk slayt eager · **mobil LCP ≤ 2,5 sn** · taban çizgisiyle karşılaştırma | **KISMİ** | Carousel kuralı VAR: `ListingCard.ts:136 eager: i === 0`; ürün detayda `ProductImageGallery.ts:101 priority: size === "large"` [K]. 🔴 **preload üretimi frontend'de YOK** — `imagesrcset` storefront'ta **0 sonuç**; backend'de `picture.py:403 preload_link()` yazılı ama **hiçbir sayfa çağırmıyor** [K]. **Mobil LCP ÖLÇÜLMEDİ** (tarayıcı yok); `lighthouserc.cjs` yalnız `preset: "desktop"` — **mobil profil hiç tanımlı değil**. `docs/reports/122-lcp.md` **YOK** (`docs/plans/faz12-lcp.md` plandır) | ARAÇ · AJAN |
| **T-123** | Gerçek kullanıcı telemetrisi (RUM) | LCP/CLS/INP **saha** verisi toplanıyor · LCP elementinin asset'i kaydediliyor · p75 panoda · **regresyon alarmı** · KVKK uyumlu örnekleme | **KISMİ** | `delivery/rum.py` **26/26 OK** [T 22:42:55]. Brifingin iki iddiası **doğrulandı**: `to_metrics()` `rum.py:670` [K]; **4 RUM regresyon alarmı canlı listelendi** — `RumLcpRegression` (>2500 ms), `RumClsRegression` (>0,25), `RumInpRegression` (>200 ms), `RumRejectedSpike` [Ö 22:42:43]. 🔴 **Saha verisi toplanmıyor** — `web-vitals` paketi YOK, `onLCP/onCLS/onINP` YOK, `sendBeacon` YOK (storefront'ta 0 sonuç) [D]; HTTP ucu YOK; `Media RUM Sample` DocType YOK — modülün kendi başlığı `rum.py:559` *"(KURULMADI)"* diyor [K]. Yani 4 alarm **hiçbir zaman ateşlenemez**: besleyen seri boş | **AJAN** |
| **T-124** | Faz 12 kapanış: performans kabulü | 4 sayfa tipi × 2 cihaz profili hedefte · taban çizgisine göre sayısal iyileşme · **bütçeler CI'da (Lighthouse CI) eşik; regresyon PR'ı kırıyor** | **KISMİ** | Bayt tarafı §2.1'de **tutarlı** doğrulandı (9,9914 MB girdi, geri alma eksiksiz). **4 sayfa × 2 profil ÖLÇÜLMEDİ.** 🔴 **CI kriteri KARŞILANMIYOR** — `tradehubfront/.github/workflows/` (5 dosya) içinde `lighthouse\|lhci\|playwright\|vitest` **0 sonuç** [D]; `lighthouserc.cjs` varsayılanı `assertionLevel = "warn"` (yalnız `LHCI_ASSERT_MODE=strict` ile `error`) [K] → **regresyon PR'ı kırmıyor**. `docs/reports/124-performans-kabul.md` **YOK** | ARAÇ · AJAN |

**Faz 12 sayım: TAM 0 · KISMİ 5 · YOK 0**

---

## 3. FAZ 13 — Güvenlik ve gözlemlenebilirlik

### 3.1 Pentest bulgularının canlı doğrulaması (T1 · T2/T3 · T9 · T4)

**T1 — `Payment Transaction` çapraz-kiracı IDOR → KAPALI** [Ö 22:40:05].
Kancalar yüklü (`permission_query_conditions` + `has_permission`); 3 kayıt
(`PAY-00001…3`); **4 gerçek satıcının dördü de** `frappe.get_list` ile **0/3**
görüyor ve `has_permission` üçünde de `False`:
`aliturgut.turksab@gmail.com`, `cankayaplastik@istoc.com`,
`irmaksu.armatur@istoc.com`, `ozgenplastik@istoc.com`.
`test_payment_transaction_isolation` **12/12 OK** [T].

**T2/T3 — KYC/KYB kendini-doğrulama → KAPALI, ama savunma katmanı DEĞİŞTİ**
[Ö 22:40:26]. Gerçek satıcılarla, işlem `rollback` edilerek:

```
KYC-00001 · sahibi demo-seller-01@istoc.demo (Seller Owner + Marketplace Seller + Verified Seller)
  d.status = "Verified"; d.save()  →  İSTİSNA YOK, doc.status = "Pending", DB "Pending"
KYB-00002 · sahibi bora.aydeger@turksab.com (aynı rol seti)
  d.status = "Verified"; d.save()  →  İSTİSNA YOK, doc.status = "Pending", DB "Pending"
rollback sonrası: KYC-00001 Verified ✅ · KYB-00002 Verified ✅
```

**Sızıntı yok** — ama sabahki davranış (`PermissionError: Doğrulama durumunu
yalnızca inceleme yetkilisi değiştirebilir.`) **artık gelmiyor**. Sebep §3.2.

**T9 — misafir hız-sınırı kovası → KAPALI, uçtan uca** [H 22:40:45 / 22:41:10].
`istoc-dev-frappe-frontend-1` içinde `set_real_ip_from 192.168.97.0/24;
real_ip_header X-Forwarded-For; real_ip_recursive on;` etkin. Gateway üzerinden
gerçek uç (`media_manifest.get_manifest_batch?listings=["LST-00560"]`), iki
istemci IP'si → **HTTP 200 / 200**, yanıt `"enabled": false` (bayraklar kapalı,
teyit) ve redis-cache'te **iki ayrı kova**:

```
_429e9b47c486be76|rl:media_manifest_batch:Guest:203.0.113.77
_429e9b47c486be76|rl:media_manifest_batch:Guest:198.51.100.88
```

`test_rate_limit_guest_bucket` **15/15 OK** [T]. İki kova koşum sonunda
silindi (§6). **Kalan risk sabahki raporla aynı:** kovaları ayıran şey
istemcinin gönderdiği `X-Forwarded-For`; XFF'i ezen bir dış kenar yokken
saldırgan başlık uydurarak kendi limitinden kaçabilir.

**T4 — `Compliance Officer` KYC/KYB okuyamıyor → HÂLÂ AÇIK** [Ö 22:40:05].
Kaynağın kriteri değil, pentest'in kapatılmayan 4'üncü bulgusu:

```
KYC L0 read rolleri: Buyer, Marketplace Admin, Marketplace Seller, Seller, Seller Owner, System Manager
KYB L0 read rolleri: Marketplace Admin, Marketplace Seller, Seller, Seller Owner, System Manager
→ ikisinde de Compliance Officer'ın permlevel-0 satırı YOK
```

Rol L1–L4'te var, L0'da yok; Frappe'de L0 read olmadan belge açılmaz. Bu bir
**KARAR** maddesi (rolün kapsamı genişletilecek mi).

### 3.2 permlevel-4 ikinci katmanı — sabah ETKİN DEĞİLDİ, **şimdi ETKİN**

Sabahki raporun en ağır bulgusu kapanmış [Ö 22:34:13]:

| Nerede | Sabah (`36-…`) | **Bu koşum** |
|---|:--:|:--:|
| Depo/konteyner JSON | 4 | 4 |
| Canlı `tabDocField` (KYC / KYB) | 🔴 1 / 1 | ✅ **4 / 4** |
| Çalışma anı `get_meta(...).permlevel` | 🔴 1 / 1 | ✅ **4 / 4** |
| `test_verification_status_guard` | 🔴 13/14 | ✅ **14/14 OK** [T] |

L4 matrisi de doğru [Ö]: `System Manager` / `Marketplace Admin` /
`Compliance Officer` read+write; `Seller` / `Marketplace Seller` /
`Seller Owner` / `Buyer` **read-only**.

⚠️ **Yan etki — kayda geçiyor.** İzin katmanı devreye girince
`validate_higher_perm_levels()` alanı sessizce geri yazıyor, dolayısıyla
`has_value_changed("status")` `False` oluyor ve `guard_verification_status_change()`
(`permissions.py`) **artık hiç çalışmıyor**. Sabah `Buyer` için tespit edilen
"sessiz başarı" tutarsızlığı **bugün satıcı rolleri için de geçerli**: istemci
`save()` başarılı görüyor, alan değişmiyor, hata mesajı yok. Güvenlik açısından
**iki katman da yerinde**, kullanıcı geri bildirimi açısından **daha kötü**.

### 3.3 T-133 `/metrics` — kablolama koşum sırasında tamamlandı (iki ölçüm)

Brifing "Şerit A şu an kabloluyor" dedi; **iki farklı hâli de ölçüldü.**

**Ölçüm 1 — 22:30:13 / 22:30:53 [H]:**

```
GET /api/method/tradehub_core.api.observability.metrics            → HTTP 403 (yetkisiz, doğru)
GET … -H "Authorization: Bearer <site_config.media_metrics_token>" → HTTP 401 AuthenticationError
```

🔴 Yani **token yolu çalışmıyordu**: `frappe/auth.py:616 validate_auth()`
iki parçalı bir `Authorization` başlığı görüp kullanıcı atanmamışsa isteği
**uç fonksiyonuna hiç ulaştırmadan** `AuthenticationError` ile kesiyor
[K, konteynerdeki frappe kaynağından okundu 22:31:08]. O anda konteynerde
`auth_hooks` **yoktu** (`grep -c auth_hooks` → 0, 22:31:33).

**Ölçüm 2 — 22:43:22 [H]**, aynı uç, aynı token, 13 dakika sonra:

```
TOKENLI:  HTTP 200 · 194 B · Content-Type: text/plain; version=0.0.4; charset=utf-8
YANLIŞ TOKEN: HTTP 401
gövde:
  # HELP media_audit_event_total Denetim kaydina yazilan medya olayi
  # TYPE media_audit_event_total counter
  media_audit_event_total{action="media.access_denied",decision="deny",severity="high"} 5
```

Arada `hooks.py`e `auth_hooks = ["…observability.authenticate_metrics_scrape"]`
eklendi ve konteynere ulaştı (22:43:10 [D]). **Uç bugün itibarıyla canlı,
token korumalı ve Prometheus metin biçiminde yanıt veriyor.**

**Ama seriler pratikte boş** [Ö 22:32:01]: çok süreçli toplayıcı iki parça
dosyası yazıyor (`sites/istoc.localhost/private/media-metrics/media-16|17.metrics.json`),
her ikisinde **24 metrik kayıtlı, dolu seri sayısı 1** — o tek seri de
**benim reddedilen scrape denemelerimin** ürettiği `media_audit_event_total`.
Sebep kusur değil: **medya hattı kapalı** (bayraklar 0), iş koşmuyor, kuyruk
boş. Yani "metrik toplanıyor mu" sorusunun cevabı **evet, mekanizma uçtan uca
kanıtlı**; "operasyonel veri var mı" sorusunun cevabı **hayır, hat açılana
kadar olmayacak**.

**Runbook ayağı ölçüldü** [Ö 22:41:46] — kodun kendi denetleyicisiyle:

```
alerts.ALARMLAR            → 16
alerts.runbook_gaps(".")   → 16   (docs/ops/runbooks/media-audit-gap.md, …-instrumentation.md, …-isolation.md, …)
instrument.NOKTALAR        → 10
docs/ops/                  → YOK
```

Yani **16 alarmın 16'sında `runbook_url` var, işaret ettiği 16 dosyanın 16'sı
yok**. `deploy/grafana/media-engine.json` (12 panel) ve
`deploy/prometheus/media-alerts.yml` (16 kural + `threshold_source`) dosya
olarak **var** [D]; kullanıcının ayrı sunucudaki Prometheus/Grafana'sına
yüklenip yüklenmediği **buradan ÖLÇÜLEMEDİ** (o sunucuya erişim yok) —
scrape yapılandırması için `deploy/prometheus/scrape-config.example.yml`
hazır duruyor.

### 3.4 T-131 CSP ayağı — brifingin "ölçülmedi" dediği kısım ölçüldü

Gerçek HTTP, gateway üzerinden [H 22:41:57]:

```
GET http://istoc.localhost/files/191-ff0258.jpg
  HTTP/1.1 200 · Content-Type: image/jpeg          ✅ doğru Content-Type
  X-Content-Type-Options: nosniff                  ✅
  X-Frame-Options / HSTS / Referrer-Policy         ✅ (ilgisiz ama var)
  Content-Security-Policy:                         🔴 YOK
  Cache-Control: public, max-age=300, must-revalidate
```

**Sonuç:** kriterin `nosniff` + doğru `Content-Type` yarısı **canlıda geçiyor**;
"**ayrı origin ya da CSP sandbox**" yarısı **karşılanmıyor** — kullanıcı
dosyaları ana origin'den (`istoc.localhost/files/…`) CSP'siz servis ediliyor ve
kaynağın istediği `deploy/nginx/media.conf` **yok** [D]. Sitede servis edilen
`.svg` dosyası bulunmadığı için SVG'ye özgü `Content-Disposition` davranışı
**ÖLÇÜLEMEDİ** (22:42:26).

### 3.5 T-134 denetim izi — canlı sayılar

[Ö 22:35:09 / 22:45:28]

| Ölçüm | Değer |
|---|---|
| `Authorization Decision Log` toplam | 2735 → **2792** (koşum boyunca büyüdü) |
| `media.*` denetim olayı | **2169 → 2194** — brifingin **2 151** rakamıyla tutarlı (artış paralel ajanların ve benim reddedilen isteklerimin) |
| En kalabalık eylemler | `media.upload` 877 · `media.access_denied` 381 · `media.optimize` 244 · `media.level_changed` 188 · `media.storage_settings_changed` 123 |
| Append-only | **Kodda zorlanıyor** — `authorization_decision_log.py:44,48-53,57-61` (`on_update`/`on_trash` throw) [K]; **DocPerm'de hiçbir role write/create/delete yok** (5 rol, hepsi yalnız `read`) [Ö] |
| Saklama | `media/audit.py:655` `retention.hot_days = 90` [K] |
| Sır sızıntısı taraması | `Error Log` (96 963 kayıt) içinde `s3_secret`, `secret_access_key`, `cdn_key`, `purge_token`, `aws_secret` → **hepsi 0** [Ö]. `logs/bench.log`teki tek eşleşme **alan adı**, değer değil (başka ajanın `SELECT field,value …` komut metni) |

### 3.6 Faz 13 görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|:--:|---|---|
| **T-130** | Worker izolasyonu ve kaynak limitleri | **Her medya işi ayrı süreçte** · RLIMIT/cgroup + süre limiti · limit aşımı işi `failed` yapıp worker'ı öldürmüyor · FS erişimi sınırlı, ağ kapalı · libvips/FFmpeg pinli + **CVE taraması CI'da** | **KISMİ** | Modül olgun: `security/isolation.py` — `subprocess.Popen` (`:492`, `shell` yok) ve `os.fork()` (`:640`), `RLIMIT_AS/CPU/FSIZE/NOFILE/CORE` (`:330-342`), duvar saati 60 sn + **süreç grubu** öldürme (`:514-519`), 37 test [K]. 🔴 **Hatta BAĞLI DEĞİL**: `run_command`/`run_callable` üretim kodunda **0 çağrı**; gerçek ffmpeg yolları hâlâ çıplak `subprocess.run` (`media/av.py:483`, `pipeline/video/transcode.py:383,678,720,743`, `video/hls.py:735`, `video/poster.py:224,303,488`) → "her medya işi ayrı süreçte" **karşılanmıyor**. 🔴 FS/ağ kısıtı YOK (chroot/bwrap/nsjail/seccomp 0 sonuç). ffmpeg `backend.Dockerfile:98-100`da pinli; **libvips hiç kullanılmıyor**. 🔴 CI'da `pip-audit`/`trivy`/`bandit` **0 sonuç**. Testleri bu koşumda **koşulmadı** | **AJAN** |
| **T-131** | SVG sanitizasyonu, CSP, dosya servis güvenliği | Script/handler/dış ref/entity kalmıyor · **ayrı origin ya da CSP sandbox** · `nosniff` + doğru `Content-Type` her yanıtta · HTML/JS asla inline | **KISMİ** | Sanitizer izin-listesi tabanlı ve sert: DTD/ENTITY **reddediliyor** (`svg.py:239,469`), `use` yalnız `#id` (`:664-675`), `defusedxml` (`:51`). **52/52 + 10/10 OK** [T 22:42:30-33] (26 vektör iddiası: dosyada `VEKTORLER` **25** giriş + 5 RET — küçük tutarsızlık). ✅ Canlı başlık: `nosniff` + doğru `Content-Type` [H §3.4]. 🔴 **CSP YOK, ayrı origin YOK, `deploy/nginx/media.conf` YOK**. 🔴 "HTML/JS inline servis edilmiyor" testi YOK | **AJAN** |
| **T-132** | Yetki sertleştirme ve sızıntı testleri | Satıcı başkasının asset'ine hiçbir uçtan erişemiyor (404) · sır hiçbir yanıt/log/traceback'te yok · **tüm whitelisted metotlar taranmış** · IDOR + path traversal geçiyor | **KISMİ** | `test_authz_regression` **24/24 OK, 0,393 sn, `import frappe` yok** [T 22:40:35] — brifingin "24 test, frappe'siz" iddiası doğrulandı. Kapsamı ölçüldü: ayrıcalık yükseltme 8, rate-limit/XFF 8, kablolama 8. IDOR canlı **kapalı** doğrulandı (§3.1, 0/3 + 12/12). Sır taraması **temiz** (§3.5). 🔴 **Path traversal ve sır sızıntısı bu pakette YOK** (grep 0). 🔴 **Otomatik whitelist tarayıcı YOK** — `scripts/run_authz_tests.sh` elle bakımlı 30+ modüllük **liste**, keşif değil. 🔴 `docs/reports/130-guvenlik-test.md` YOK | **AJAN** |
| **T-133** | Gözlemlenebilirlik: metrik, log, iz, alarm | Prometheus metrikleri · JSON log + correlation_id · **panolar** · alarmlar · **her alarm için runbook bağlantısı** | **KISMİ** | ✅ **Bugünün en büyük ilerlemesi**: `/metrics` **canlı, token korumalı, 200 + `text/plain; version=0.0.4`** [H 22:43:22]; yanlış token 401; parça dosyaları yazılıyor; 24 metrik kayıtlı, 10 ölçüm noktası [Ö]. Testler **26+19+20 = 65/65 OK** [T]. JSON log + `correlation_id` tam (`observability/logging.py:60,190,265,450`). Panolar/alarmlar **dosya olarak** var (12 panel, 16 kural). 🔴 **16/16 runbook dosyası YOK** (`runbook_gaps()` canlı 16 döndü, `docs/ops/` yok) → "her alarm için runbook bağlantısı var" kriteri **hedefsiz bağlantı**. ⚠️ Seriler pratikte boş (hat kapalı). Dış Prometheus/Grafana'ya yüklenme **ÖLÇÜLMEDİ** (erişim yok) | **AJAN** · İNSAN |
| **T-134** | Denetim izi ve KVKK uyumu | Silme/ayar/onay/retention/sır erişimi audit'e yazılıyor · **append-only** + saklama süresi · **KVKK envanteri + veri sahibi talebi akışı** · aydınlatma metni | **KISMİ** | ✅ Denetim `Authorization Decision Log`a yazılıyor, **2 194 medya olayı** canlı [Ö]; append-only hem kodda hem DocPerm'de zorlanıyor; `hot_days=90`; `test_audit` **18/18 OK** [T]. Bugün eklenen `ACTION_SETTINGS_CHANGED` canlıda görülüyor (`media.storage_settings_changed` 123 kayıt). ✅ `docs/security/kvkk.md` **486 satır**, envanter (§3, canlı ölçümlü) ve aydınlatma metni (§7, "taslak") var. 🔴 **Veri sahibi talebinin MEDYA ayağı kodda YOK**: `_EXPORTABLE_DOCTYPES` içinde `File` yok, `privacy/account_deletion.py` medyaya hiç dokunmuyor, `Data Retention Policy` 0 satır, `Data Export Request` 0 kayıt — belgenin kendi §5.2 ölçümü. 🔴 Saklama süreleri **öneri** düzeyinde (VUK/TTK çakışması "hukuk danışmanına"). ⚠️ Kaynak `docs/compliance/kvkk.md` istiyor, dosya `docs/security/kvkk.md`. `Media Audit Log` DocType yok (**bilinçli**, ADL emsali) | AJAN · **KARAR** |
| **T-135** | Faz 13 kapanış: sızma + yük + kaos | Kritik/yüksek bulgu kalmamış · **yük testi** hedefte · **kaos testi**nde veri kaybı yok | **KISMİ** | Sızma testi yapıldı; **3 bulgusunun kapalı olduğu bu koşumda bağımsız ölçüldü** (T1 · T2/T3 · T9 — §3.1) ve sabah kırmızı olan permlevel katmanı **artık etkin** (§3.2). 🔴 **T4 açık** (`Compliance Officer` L0 read yok — canlı ölçüldü). 🔴 **Yük testi YOK** (k6/locust 0 sonuç; `28-faz13-pentest.md` §5 gerekçeli atlamış). 🔴 **Kaos testi YOK** — `chaos\|kaos` deseni depoda **0 sonuç**, `28-` ve `29-` raporlarında **hiç anılmıyor** (brifingin uyarısı doğrulandı). 🔴 `docs/reports/135-guvenlik-yuk-kabul.md` YOK | AJAN · **KARAR** |

**Faz 13 sayım: TAM 0 · KISMİ 6 · YOK 0**
(Sabah `ÖLÇÜLMEDİ` kalan T-130 ve T-131 bu koşumda ölçüldü → ikisi de **KISMİ**.)

---

## 4. FAZ 14 — Test, doğrulama, kabul

### 4.1 Faz 14 artefaktları bugün **hiç dokunulmadı**

Bugün 7 ajan çalıştı, `docs/` altına 38 yeni dosya düştü — **hiçbiri Faz 14'e
gitmedi** [D]:

| Artefakt | Son değişiklik |
|---|---|
| `docs/test/traceability.md` | 18 Ağu 16:18 |
| `docs/plans/faz14-uat.md` | 18 Ağu 16:18 |
| `docs/plans/faz14-golive.md` | 18 Ağu 16:18 |
| `tests/test_e2e_scenarios.py` | 18 Ağu 16:44 |
| `media/pipeline/migration/backfill.py` | 18 Ağu 16:44 |
| `docs/reports/13-faz14-kabul.md` | 18 Ağu 16:18 |
| **`docs/qa/`** | **YOK** |
| **`docs/ops/`** | **YOK** |

⚠️ **Üstelik iki Faz 14 belgesi artık gerçeğe aykırı:**
`faz14-golive.md:41-44` *"Kod tabanında medya için böyle bir bayrak
bulunamadı"* diyor — oysa `media/pipeline_flags.py` (18 Ağu 23:02) **var** ve
16 testi geçiyor. `13-faz14-kabul.md:100` *"bu depoda hiçbir ADR dosyası yok"*
diyor — bugün 18:37–18:49 arasında **17 ADR + README** yazıldı. Kabul dosyası
kendi kanıt tabanının gerisinde.

### 4.2 VMAF (senaryo 8) — araç durumu bugün de ölçüldü

`backend.Dockerfile:98-123` artık libvmaf doğrulamalı bir ffmpeg (`n8.1.2`)
pinliyor. **Ama çalışan konteynerde durum değişmemiş** [Ö 22:46:49]:

```
ffmpeg version 5.1.9-0+deb12u1   ·   filtreler: yalnız "vmafmotion", libvmaf YOK
```

Yani **imaj yeniden derlenmeden** VMAF ≥ 93 kapısı (E2E senaryo 8) hâlâ
ölçülemez. `test_VMAF_OLCULEMEDI` atlanmaya devam edecek.

### 4.3 Faz 14 görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt | Engelleyen |
|---|---|---|:--:|---|---|
| **T-140** | İzlenebilirlik matrisi (SRS → test) | **Her FR/NFR en az bir teste bağlı; bağsız gereksinim yok** · her INV ≥1 property/golden test · matris otomatik ve **CI'da güncel** | **KISMİ** | Üretici var (`scripts/gen_traceability.py`), çıktı `docs/test/traceability.md`. Matrisin kendi sayısı: **202 gereksinim, 74'ü bağlı (%36,6), 128'i (%63,4) KAPSANMIYOR**; kendi beyanı *"bugün SAĞLANMIYOR"* [D]. Bugün **güncellenmedi** (18 Ağu). 🔴 `@pytest.mark.req` / `@pytest.mark.inv` **0 kullanım**, `markers` bloğu yok. 🔴 `.github/workflows/` içinde traceability kapısı **0 sonuç** | **AJAN** |
| **T-141** | E2E senaryo paketi | **12 senaryonun tümü otomatik ve GREEN** · her senaryo **ekran görüntüsü/video** üretiyor · temiz kurulumda sıfırdan | **KISMİ** | `tests/test_e2e_scenarios.py`: **39 test, 8'i koşulsuz `skipTest`** [D]. 12 senaryodan **5, 6, 8, 12** kodda **karşılıksız** (`:394-400` önizleme-onay kapısı yok, `:445-451` iş planlayıcı yok, `:502-508` VMAF aracı yok — §4.2 canlı doğrulandı, `:751-756` on-demand ucu yok). 🔴 **Playwright ile e2e YOK** (`tests/e2e/` yok), **ekran görüntüsü/video YOK**, `docs/qa/evidence/` **YOK**. Bugün dosyaya **dokunulmadı** | **AJAN** · ARAÇ |
| **T-142** | UAT ve satıcı pilotu | ≥10 gerçek satıcı, her biri ≥5 ürün · tamamlanma oranı/süre ölçülmüş · anlama oranı ≥%90 · bulgular önceliklendirilmiş | **YOK** | `docs/plans/faz14-uat.md` **plan** (16 KB, 18 Ağu): *"BU BİR PLANDIR. PİLOT KOŞULMADI … tek bir ölçüm, tamamlanmış tek bir görev, hesaplanmış tek bir tamamlama oranı yoktur"*. `docs/qa/` **YOK**, bulgu kaydı **YOK** [D]. Plan ayrıca pilotun **bugün koşulamayacağını** kanıtlıyor: (b) Crop Studio ve (c) simülatör **ekranı yazılmadı** | **İNSAN** · AJAN |
| **T-143** | Geçiş (backfill) uygulaması ve izleme | Parti parti düşük öncelikli kuyruk, **canlı trafiği etkilemediği ölçümle kanıtlı** · ilerleme/hata/tahmini bitiş **panoda** · eşik aşılırsa **otomatik duruyor** · **geri alma prova edilmiş** · **satıcılar bilgilendirilmiş** | **KISMİ** | Kod tam: `migration/backfill.py` — `StopPolicy`/`evaluate_stop` (`:228,295`), `LiveTrafficGuard` (`:369,738,760`), `AtomicSwitch` (`:410-465`), `SellerNotice`/`build_notices` (`:490,509`), `dashboard()` (`:777`); 50 test. 🔴 **Canlıda koşmadı** — `Media Asset` 0, `Media Rendition` 0 [Ö 22:47:14]. 🔴 **Canlı trafik koruması yük testiyle kanıtlanmadı** (kriter bunu açıkça istiyor; yük testi hiç yok). 🔴 **Pano arayüz değil, `Dict[str, Any]` döndüren fonksiyon**. 🔴 Geri alma provası **yok**, satıcı bildirimi **gitmedi**. Sınıfın kendi docstring'i: *"Bu sınıf ÇALIŞTIRILMADI"* (`:796`) | **KARAR** · AJAN |
| **T-144** | Devreye alma (go-live) ve runbook'lar | Aşamalı açılış (canary→%10→%50→%100) + geri dönüş eşiği · **geri dönüş prova edilmiş ve süresi ölçülmüş** · runbook'lar · nöbet/eskalasyon | **KISMİ** | `docs/plans/faz14-golive.md` (23 KB): aşama tablosu, geri dönüş prosedürü, **8 runbook** (§5), nöbet/eskalasyon — **yazılı kısım tam**. 🔴 **Prova YOK, süre ÖLÇÜLMEDİ** (belgenin kendi başlığı: *"3.4 Prova — ÖLÇÜLMEDİ"*). 🔴 `docs/ops/runbooks/` **YOK** → hem bu görevin 8 runbook'u hem T-133'ün 16 alarm runbook'u aynı boş dizini işaret ediyor. 🔴 **Yüzde tabanlı aşamalı açılış kodda YOK** (`rollout_percent` 0 sonuç); yalnız aç/kapa + slot beyaz listesi (`pipeline_flags.py`) — belgedeki "bayrak yok" iddiası ise **eskimiş** | **İNSAN** · AJAN |
| **T-145** | Nihai kabul dosyası ve devir | Tüm faz çıkış kriterleri işaretli ve kanıtlı · **izlenebilirlik matrisi %100** · açık bulgu listesi · devir · **platform yöneticisi imzası** | **KISMİ** | `docs/reports/13-faz14-kabul.md` var ve dürüst (KANITLI 4 · KISMEN 9 · KANIT YOK 11). 🔴 **İzlenebilirlik %36,6** (hedef %100). 🔴 `docs/qa/final-acceptance.md` **YOK**. 🔴 İmza bölümü var ama boş: *"BU BELGE İMZALANMAMIŞTIR VE BUGÜN İMZALANAMAZ"*. ⚠️ Belge bugünkü ADR/bayrak gerçeğinin gerisinde (§4.1) | **İNSAN** |

**Faz 14 sayım: TAM 0 · KISMİ 5 · YOK 1**

---

## 5. Sayım

### 5.1 Faz bazında

| Faz | TAM | KISMİ | YOK | ÖLÇÜLMEDİ | Toplam |
|---|:--:|:--:|:--:|:--:|:--:|
| **Faz 12** (T-120…T-124) | **0** | **5** | 0 | 0 | 5 |
| **Faz 13** (T-130…T-135) | **0** | **6** | 0 | 0 | 6 |
| **Faz 14** (T-140…T-145) | **0** | **5** | **1** | 0 | 6 |
| **TOPLAM** | **0** | **16** | **1** | **0** | **17** |

### 5.2 Sabahki koşumla fark (`36-dogrulama-faz12-14.md`)

| | Sabah (19:16) | **Akşam (22:47)** | Fark |
|---|:--:|:--:|---|
| TAM | 0 | **0** | — |
| KISMİ | 14 | **16** | +2 (T-130, T-131 artık ölçüldü) |
| YOK | 1 | **1** | T-142 |
| ÖLÇÜLMEDİ | 2 | **0** | ikisi de kapatıldı |

**Gün içinde gerçekten değişen üç şey:**

1. ✅ **permlevel-4 ikinci katmanı canlıda etkin** (§3.2) — sabahki tek kırmızı
   test (`test_verification_status_guard` 13/14) bugün **14/14 yeşil**.
2. ✅ **`/metrics` ucu canlı ve token korumalı** (§3.3) — koşumun başında 401
   veriyordu, sonunda **200 + Prometheus metin biçimi**. Metrik kablolaması
   uçtan uca kanıtlandı; seriler hat kapalı olduğu için boş.
3. ➖ **Faz 14 hiç ilerlemedi** (§4.1) — altı artefaktın altısı 18 Ağu'dan
   kalma; `docs/qa/` ve `docs/ops/` hâlâ yok.

### 5.3 Engelleyen dağılımı (birincil etiket, 17 görev)

| Engelleyen | Görev sayısı | Görevler |
|---|:--:|---|
| **AJAN** | **9** | T-120, T-123, T-130, T-131, T-132, T-133, T-134, T-140, T-141 |
| **ARAÇ** | **3** | T-121, T-122, T-124 |
| **İNSAN** | **3** | T-142, T-144, T-145 |
| **KARAR** | **2** | T-135 (T4 rol kapsamı), T-143 (canlı backfill başlatma) |
| **—** | **0** | — |

> Not: birçok görevin **ikinci** bir engelleyeni var (tabloda `·` ile
> yazıldı). Örneğin T-141 hem AJAN (Playwright paketi yazılmadı) hem ARAÇ
> (libvmaf yok — §4.2) engelli.

**Engelleyen türüne göre en kısa yol:**
- **ARAÇ (4 görev)** tek bir eksikte düğümleniyor: **tarayıcı tabanlı ölçüm**
  (CLS, LCP, `sizes` sapması, 4×2 profil). Playwright zaten kurulu; eksik olan
  koşum ortamı ve mobil profil.
- **AJAN (9 görev)** içinde en çok kaldıraçlı iki iş: `docs/ops/runbooks/`
  (T-133 + T-144'ün ikisini birden besliyor) ve `web-vitals` köprüsü (T-123'ün
  yazılı 4 alarmını canlıya bağlar).
- **KARAR (2)**: `Compliance Officer` KYC/KYB L0 read alacak mı; backfill
  üretimde başlatılacak mı.

---

## 6. Koşum hijyeni

| Ne üretildi / değiştirildi | Nasıl geri alındı | Doğrulama |
|---|---|---|
| `KYC-00001` / `KYB-00002` üzerinde satıcı sömürü denemesi (§3.1) | `frappe.db.rollback()` — hiç `commit` yok | ikisi de **`Verified`** ✅ [Ö 22:40:26] |
| 2 misafir hız-sınırı kovası (uydurma XFF) | `redis-cli DEL` | `rl:*` taraması **boş** ✅ [Ö 22:47:14] |
| ⚠️ Kesilen ilk iki test koşumundan artık kayıt: 4 `t23-*@test.local` kullanıcı + `KYC-00045` + `KYB-00043` + 1 `User Profile` | `delete_doc(force=True, delete_permanently=True)` + `commit` | `KYC` **24**, `KYB` **37**, `t23-*` **0 kayıt** ✅ [Ö 22:44:57] |
| Konteynere kopyalanan 10 ölçüm betiği (`/tmp/m1…m9.py`, `temiz.py`) + test log'ları | `rm` | `/tmp`te kalmadı ✅ [D 22:47:04] |
| Host `/tmp` geçici dosyaları (kaynak HTML/metin, curl çıktıları) | `rm` | temiz ✅ |

**Geri alınmayan iki iz — bilinçli, açıklamasıyla:**

1. **5 `media.access_denied` denetim kaydı** — `/metrics` ucuna yaptığım
   yetkisiz istekler `Authorization Decision Log`a yazıldı. **Silinmedi:** bu
   tablo append-only ve denetlediğim kriter (T-134) tam olarak bu değişmezlik.
   Denetim kaydını silmek, doğruladığım güvenceyi bozmak olurdu.
2. **2 metrik parça dosyası** (`private/media-metrics/media-16|17.metrics.json`)
   — `after_request` kancasının normal çıktısı, sistemin kendi ürettiği çalışma
   anı durumu; `exporter.prune()` kapsamında. Dokunulmadı.

**Bana ait olmayan, koşum sırasında görülen artıklar (bilgi olarak):**
6 adet `t082-*@test.local` kullanıcı (22:36:50–22:37:47) — başka bir ajanın
`test_media_crop_intent` koşumundan kalmış. **Dokunmadım.**
Konteyner `/tmp`inde başka ajanlara ait `chk1.py`, `chk12.py`, `dt.py`, `ma.py`,
`olcum.py`, `parse_oh.py`, `q.py`, `temizlik.py` duruyor.

🔒 **Bayraklar koşum boyunca ve sonunda 0** (22:34:13 ve 22:47:14 [Ö]).
📄 **Değiştirilen üretim dosyası: 0.** Yazılan tek dosya budur.
(`git status`taki 44 `M` ve 38 `??` giriş paralel koşan diğer ajanların işidir.)

---

## 7. Bu koşumun beş somut çıktısı

1. ✅ **Sabahki 🔴 kapandı** — `status` permlevel-4 ikinci katmanı canlıda
   etkin (`tabDocField` 1→**4**), düzeltmenin kendi testi **14/14 yeşil**.
   **Ama** izin katmanı devreye girince controller guard'ı devre dışı bıraktı:
   satıcı artık `PermissionError` almıyor, **sessizce başarısız oluyor**
   (§3.2). Güvenlik aynı, kullanıcı geri bildirimi daha kötü.
2. ✅/🔴 **`/metrics` bugün gerçekten yayında** — 22:30'da token yolu Frappe'nin
   `validate_auth`ı tarafından 401 ile kesiliyordu, 22:43'te `auth_hooks`
   kablolaması yetişti ve uç **200 + `text/plain; version=0.0.4`** döndü.
   Kalan boşluk: 16 alarmın işaret ettiği **16 runbook dosyasının hiçbiri yok**.
3. 🔴 **T-131'in CSP ayağı ölçüldü ve karşılanmıyor** — canlı `/files/…` yanıtı
   `nosniff` + doğru `Content-Type` taşıyor, ama **CSP başlığı yok, ayrı origin
   yok, `deploy/nginx/media.conf` yok**.
4. 🔴 **T-130'un asıl boşluğu izolasyon kodunda değil, bağlanmamış olmasında** —
   `isolation.py` olgun (RLIMIT + duvar saati + süreç grubu öldürme) ama üretim
   yolunda **0 çağrısı** var; gerçek ffmpeg çağrıları hâlâ çıplak `subprocess`.
5. ➖ **Faz 14 bugün hiç ilerlemedi** ve iki kabul belgesi artık **gerçeğin
   gerisinde** (ADR yok / bayrak yok iddiaları); ayrıca `backend.Dockerfile`
   libvmaf'lı ffmpeg pinlese de **çalışan konteynerde hâlâ 5.1.9 var**, yani
   VMAF kapısı imaj yeniden derlenmeden ölçülemez.

---

## 8. Ölçülmedi olarak kalanlar (dürüstlük kaydı)

- **Tarayıcı gerektiren her kriter** — CLS 0 (T-120), `sizes` sapma ≤ %25
  (T-121), mobil LCP ≤ 2,5 sn (T-122), 4 sayfa × 2 cihaz (T-124), E2E
  ekran/video kanıtı (T-141). Bu koşumda tarayıcı çalıştırılmadı.
- **T-124 senaryo A/C/D çıktıları** — bayrak açmak gerekirdi, **yasaktı**;
  yalnız girdi ve geri alma tarafı doğrulandı.
- **T-130 test paketi (37 test)** ve `test_e2e_scenarios` / `test_migration_backfill`
  — bu koşumda **koşulmadı**; ilgili dosyalar bugün değişmediği için sabahki
  sonuçlar (39 test/8 skip, 50/50) geçerli kabul edildi, tekrar üretilmedi.
- **Dış Prometheus/Grafana** — kullanıcının ayrı sunucusundaki kurulum ve
  panoların yüklenip yüklenmediği buradan **ölçülemedi**.
- **SVG'ye özgü servis davranışı** (`Content-Disposition`) — sitede servis
  edilen `.svg` dosyası bulunmadı.
- **Yük ve kaos testi** — araç yok (k6/locust), üstelik 7 ajan yükü altında
  anlamlı bir yük ölçümü üretilemezdi.
- **Süre/performans rakamı** — hiçbir duvar saati sayısı raporlanmadı;
  `bench migrate` koşulmadı.
