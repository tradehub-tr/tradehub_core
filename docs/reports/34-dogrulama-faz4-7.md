# 34 · Faz 4-5-6-7 — ölçerek doğrulama

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **HEAD:** `1ec9b5e`
**Kapsam:** Kaynağın (https://karacaismail.github.io/imageoptimization/docs/)
`41-faz4-veri-modeli.html`, `42-faz5-depolama-s3-cdn.html`,
`50-faz6-image-engine.html`, `51-faz7-video-engine.html` sayfalarındaki
**25 görevin** kabul kriterleri, iç raporlara değil **ölçüme** karşı.

**Yöntem:** Kabul kriterleri kaynak sayfalardan okundu. Her iddia için testler
`istoc-dev-backend-1` konteynerinde koşturuldu, canlı veritabanı sorgulandı,
HTTP uçları gerçek istekle çağrıldı, üretim imajının ffmpeg'i denetlendi.
Ölçemediğim şeye **"ölçülmedi"** yazdım; koşturmadığım hiçbir teste "geçti"
demedim.

**Numaralandırma:** Kaynağın numaraları kullanıldı. Faz 5'te iç kayıttaki
(`14-nihai-denetim.md:332`) kayma düzeltildi: kaynağın **T-050** = adaptör
uygulaması, kaynağın **T-051** = ayarlar arayüzü.

---

## 0. Bu koşumda ölçülen toplam

| Ölçüm | Değer |
|---|---:|
| Koşturulan test modülü | 23 |
| Koşturulan test | **1.000** |
| Başarısız | **2** |
| Atlanan | 10 |
| Gerçek HTTP isteği | 10 |
| Canlı DB sorgusu | 9 |

> **Süre/performans iddiası yok.** Bu koşum sırasında aynı konteynerde paralel
> üç ajan daha çalışıyordu; ölçülen süreler karşılaştırılabilir değildir. Yalnız
> **geçti/kaldı** raporlanır.

### 0.1 Modül modül koşum sonucu (ham)

| Modül | Test | Sonuç |
|---|---:|---|
| `test_crop` | 26 | OK |
| `test_crop_geometry` | 37 | **FAILED (1)** |
| `test_dedup` | 57 | OK |
| `test_usage` | 45 | OK |
| `test_storage_adapters` | 137 | OK |
| `test_storage_adapters_minio` | 91 | OK (gerçek MinIO) |
| `test_media_storage_settings` | 19 | OK |
| `test_retention_gc` | 22 | OK |
| `test_retention` | 47 | OK (1 atlandı) |
| `test_delivery_sizes` | 22 | OK |
| `test_delivery_picture` | 24 | OK |
| `test_e2e_scenarios` | 39 | OK (8 atlandı) |
| `test_image_probe` | 16 | OK |
| `test_image_normalize` | 25 | OK |
| `test_image_classify` | 32 | OK |
| `test_render` | 73 | OK |
| `test_render_regression` | 32 | **FAILED (1)**, 1 atlandı |
| `test_image_lqip` | 27 | OK |
| `test_quality_ssim` | 21 | OK |
| `test_video_decision` | 58 | OK |
| `test_video_transcode` | 89 | OK |
| `test_media_transcode` | 22 | OK |
| `test_media_transcode_retry` | 39 | OK |

### 0.2 İki başarısızlık — kök nedenleri ayrıdır

**(a) `test_crop_geometry.TypeScriptPariteTesti.test_ts_ikizi_ayni_sayiyi_veriyor` — ORTAMSAL**

```
node: bad option: --experimental-strip-types
```

Konteynerdeki Node **v20.19.2**; `--experimental-strip-types` Node 22+ ister.
`crop_geometry.ts` ikizi bu konteynerde **hiç koşmuyor**. Python tarafındaki
584 vektörün hepsi 0.0 px sapmayla geçiyor; kırılan şey **Python↔TypeScript
parite güvencesidir**. Yani panelin kırpma önizlemesinin backend ile aynı
pencereyi ürettiği bugün bu ortamda **doğrulanamıyor** — koruma inert.

**(b) `test_render_regression.MatrisKilidiTesti.test_matris_sayilari` — GERÇEK SAPMA (commit edilmemiş)**

```
{'brand.logo': 6, 'seller.logo': 6, '_toplam': 50}  !=  {'brand.logo': 5, 'seller.logo': 5, '_toplam': 48}
```

Ölçüm:

| Dosya | HEAD | Çalışma ağacı |
|---|---:|---:|
| `policy/slots/brand-logo.json` | 5 rendition | **6** (`w384` eklenmiş) |
| `policy/slots/seller-logo.json` | 5 rendition | **6** (`w384` eklenmiş) |

`git status` her iki dosyayı **M** gösteriyor; `MATRIS_ALTIN` altın sabiti
güncellenmemiş. Yani **HEAD yeşil, çalışma ağacı kırmızı.** Bu değişikliği ben
yapmadım (bu görev salt okuma); paralel koşan ajanlardan biri politikayı
genişletmiş, altın kilidi güncellememiş.

> **Bu bir kusur değil, kilidin çalıştığının kanıtıdır** — T-067'nin varlık
> sebebi tam olarak budur. Ama **bugün itibarıyla Faz 6 regresyon paketi
> KIRMIZI**dır ve "Faz 6 ✅ KANITLI" ifadesi bu çalışma ağacında geçerli
> değildir.

---

## 1. Faz 4 — Veri modeli

### 1.1 Canlı DocType sayımı (ölçüm)

```sql
SELECT name, issingle FROM tabDocType WHERE name LIKE 'Media%';
```

| Kurulu (6) | issingle |
|---|---|
| Media Asset | 0 |
| Media Engine Settings | **1** |
| Media Processing Job | 0 |
| Media Profile | 0 |
| Media Rendition | 0 |
| Media Storage Settings | **1** |

`media/pipeline/doctype_specs/` altında **15 spesifikasyon** var
(`_ddl.sql` ve `_index.json` hariç). **6'sı kurulu, 9'u kurulmadı:**

`Media Source` · `Media Version` · `Media Crop Intent` · `Media Crop Override` ·
`Media Policy` · `Media Policy Profile` · `Media Content Rule` ·
`Media Usage` · `Media Quality Report`

**Kurulum sağlığı:** 13 medya yaması `tabPatch Log`'da **`skipped=0`** ile
kayıtlı (`v15_9_21_media_pipeline_doctypes`, `v15_9_23_media_profile_seed`,
`v15_9_25_media_storage_settings` dâhil). Görev tanımındaki "`Media Storage
Settings` bir ara `tabDocType`'tan kayboldu" durumu **bugün yok** — kayıt
yerinde, yamanın günlüğü temiz (§2.2'de HTTP ölçümü).

**Satır sayıları (ölçüm):** `tabMedia Asset` **0** · `tabMedia Rendition` **0** ·
`tabMedia Processing Job` **0** · `tabMedia Profile` **36** (9 slotun tamamı).
Yani DocType'lar kurulu ve tohumlu ama **varlık/türev tabloları boş** — hat
bugün hâlâ `File` üzerinden çalışıyor, bu tablolara yazmıyor.

### 1.2 Görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-040** | DocType şemalarının backend'e yazılması | (1) Tablodaki tüm DocType'lar alan tipleriyle kurulu (2) `content_sha256` unique, `(version, profile, width, format)` bileşik unique (3) `permission_query_conditions` ile satıcı izolasyonu + Settings yalnız superadmin (4) Varsayılan profil/politika fixture/migration ile (5) `bench migrate` temiz + yazılı geri alma planı | **KISMİ** | (1) **6/15** — ölçüm §1.1. (2) `SHOW INDEX FROM tabMedia Asset` → `content_sha256` **`Non_unique=1`**, unique DEĞİL; tekillik türetilmiş `asset_key` (owner_seller, slot_key, content_sha256) üçlüsünde. `tabMedia Rendition` → `rendition_key` unique (asset, profile, width, format). **İkisi de bilinçli, JSON `$comment`'inde yazılı sapma** — "bir File birden çok Asset'e hizmet edebilir". Kriter harfiyen karşılanmıyor, ruhen karşılanıyor. (3) **KARŞILANDI** — `hooks.py:761+` 4 medya DocType'ı için `permission_query_conditions` bağlı; `Media Superadmin` rolü `tabRole`'da var; `Media Asset` moderasyon alanları permlevel 1. (4) **KARŞILANDI** — `tabMedia Profile` 36 satır, `v15_9_23_media_profile_seed` uygulandı. (5) 13 yama `skipped=0`; **`docs/plans/rollback-doctypes.md` YOK** |
| **T-041** | Crop intent veri modeli + öncelik zinciri | `resolve_crop` 5 seviyeli zincir; oranlar normalize; INV-10 özellik testi; pencere kaynağı aşmaz, en-boy tam tutar; onaysız öneri kullanılabilir ama işaretli | **TAM** *(kaynağın kriterlerine göre)* | `test_crop` **26 test OK** (5 seviye + sızma + INV-10 + 600 girdili altın simülatör + 4.000 girdili özellik testi). `test_crop_geometry` **37 test, 36 geçti**: çapraz sapma 1.8e-12 px, 800 örnekte 1 px yuvarlama farkı **0**, 3.652 örnekte oran sapması 2.07e-16, **584 vektörde sapma 0.0 px**. ⚠ Kaynağın kriterinde olmayan ama repoda var olan **TS parite testi kırık** (§0.2a) — `Media Crop Intent` DocType'ı da kurulmadığı için intent **kalıcı olarak saklanamıyor** |
| **T-042** | Dedup, sürümleme, içerik hash'i | Aynı SHA-256 yeni dosya yazmaz; eşzamanlı yüklemede yarış yok; `version_hash` = f(...); rendition URL'i `version_hash` taşır (INV-09); pHash uyarı üretir | **TAM** | `test_dedup` **57 test OK** — akışlı hash 6 kaynak tipi, kanonik JSON, `version_hash` 12 test, rendition adresi 10 test, **gerçek thread'li yarış koşulu 4 test**, pHash. DB düzeyinde tekillik `tabMedia Asset.asset_key` UNIQUE ile de duruyor (§1.1) |
| **T-043** | Kullanım takibi ve öksüz tespiti | (1) DocType alanına bağlanınca/kopunca **Media Usage kaydı** güncellenir (2) Sıfır kullanımlı + N günden eski varlıklar öksüz raporunda (3) Otomatik silme yok, superadmin onayı (4) `last_access_at` örneklemeyle güncellenir | **KISMİ** | `test_usage` **45 test OK** (bağ kaydı, zaman kovası, tampon, sistem yolu muafiyeti, gerçek dizin taraması, kayıt öksüzü muafiyetleri) — (2)(3)(4) karşılanıyor. **(1) karşılanmıyor:** `core/usage.py:134` kendi docstring'iyle *"Bellek içi `Media Usage` deposu"*; `Media Usage` DocType'ı **kurulmadı**, kalıcı kayıt yok. Süreç yeniden başlayınca bağ tablosu sıfırlanır |
| **T-044** | Faz 4 kapanış — veri modeli incelemesi | ER + indeks planı belgeli, her sorgu yolu indeksli; **1M asset ölçeğinde EXPLAIN** incelendi; migration/rollback uçtan uca provalı + süre raporlu | **KISMİ** | `docs/data/data-model-review.md` §1-§4 var, §4 *"EXPLAIN — ölçüldü"*. §8'de **8 açık madde** yazılı. Bunlardan **2'si artık bayat**: madde 5 (izin kodu yok) → `hooks.py:761+` ile **kapandı**; madde 6 (profil tohumlama yok) → 36 satır + yama ile **kapandı**. **Hâlâ açık:** 1M asset'e ulaşılmadı (524.288 asset / 2.097.152 rendition = %52 / %7, geçici `media_engine_ddl_test` DB'sinde, sonra düşürüldü), `scripts/seed_synthetic.py` yazılmadı, **rollback provası ve `rollback-doctypes.md` yok**, pyvips sürüm etiketi ölçülmedi, 3 eşik kalibre edilmedi |

**Faz 4 sayımı: 2 TAM · 3 KISMİ · 0 YOK**

---

## 2. Faz 5 — Depolama · S3 · CDN

### 2.1 `Media Storage Settings` — "kayboldu mu?" sorusunun ölçülmüş cevabı

| Ölçüm | Sonuç |
|---|---|
| `tabDocType` satırı | **VAR** |
| `tabSingles` alan satırı | **29** |
| `tabRole` → `Media Superadmin` | **VAR** |
| `v15_9_25_media_storage_settings` yama günlüğü | uygulandı, `skipped=0` |

### 2.2 `get_storage_status` — kayıtlı 500 hatası **KAPANDI**

`docs/api/openapi-http.yaml:4356` bugün hâlâ şunu yazıyor:

> `x-measured: "http-fail"` · *"2026-08-19, Administrator: HTTP 500,
> `ImportError: … No module named 'frappe.core.doctype.media_storage_settings'`"*

**Ben ölçtüm — artık doğru değil.** Gerçek HTTP, Administrator oturumuyla,
gateway üzerinden:

| Uç | Ölçülen |
|---|---|
| `…media_storage_settings.get_storage_status` | **HTTP 200**, gövde: `plan.mode=local`, `signer_available=true`, `backend=LocalDiskStorage`, `boto3_available=true`, 6 blocker |
| `…media_storage_settings.test_connection?target=s3` | **HTTP 200** — `ok:false`, `detail: "s3_bucket boş"` (yapılandırma yok, kod sağlam) |
| `…test_connection?target=cdn` | **HTTP 200** — `ok:false`, `"adres tanımlı değil"` |
| `…test_connection?target=imgproxy` | **HTTP 200** — `ok:false`, `"imgproxy kök adresi tanımlı değil"` |

**Sonuç:** kök neden (eksik `tabDocType` satırı) giderilmiş; `openapi-http.yaml`
ve `32-faz8-api-kapanis.md`'deki `http-fail` işaretleri **bayat**. Bu iki
belgenin düzeltilmesi gerekiyor (bu görev salt okuma olduğu için
düzeltilmedi).

### 2.3 Görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-050** | StorageAdapter (Local · S3 · Mirror · Tiered) | (1) Dört kip **tek sözleşme paketinden** geçer (2) Kapalıyken S3 kütüphanesi **hiç import edilmez** (3) Yazma hatasında yarım dosya kalmaz (atomik temp+rename) (4) Büyük dosya akışlı, bellek dosya boyutundan bağımsız (5) Geçici S3 hatası retry, kalıcı hata yerel kopyayı korur + alarm | **TAM** | **`test_storage_adapters` 137 OK + `test_storage_adapters_minio` 91 OK** — MinIO testlerinde **0 atlama**, yani gerçek `istoc-dev-minio-1`'e karşı koştu. (2) kod denetimiyle doğrulandı: `storage/s3.py:203-209` *"İstemciyi tembel kur. `import boto3` YALNIZ burada"*, `boto3_available()` `importlib.util.find_spec` kullanıyor — modül düzeyinde import yok. (1)(3)(4)(5) test paketinde. ⚠ **Kabul kriteri değil ama açılma engeli:** `boto3` konteynerin `env`'inde kurulu ama **`requirements.txt`'te ve `docker/` imaj tarifinde YOK** → imaj yeniden kurulunca kaybolur; `get_storage_status` bunu kendi blocker listesinde de söylüyor (*"boto3 imaja alınmadı — bugünkü kurulum konteyner ömürlü"*) |
| **T-051** | Media Storage Settings ekranı + superadmin izolasyonu | (1) Beş bölümün alanları gruplu (2) Seller/Customer API, UI ve `frappe.client` üzerinden engelli (3) Sırlar Password, API'de dönmez, log'a girmez (4) "Bağlantı Testi" gerçek yaz/oku/sil (5) Değişiklik audit log'a alan geçişleriyle (sır maskeli) (6) Geçersiz kombinasyon engelli | **TAM** | `test_media_storage_settings` **19 test OK**. DocType kayıtlı, 29 alan, `Media Superadmin` rolü canlı (§2.1). (4) ben de ölçtüm: `test_connection` üç hedef için de **HTTP 200** ve gerçek kod yolundan geçip yapılandırma eksikliğini bildiriyor (§2.2). Sırlar `Password` fieldtype (`media_storage_settings.json`: `s3_secret_key`, `imgproxy_key`, `imgproxy_salt`). ⚠ Bilinçli sapma: kaynağın alan adları yerine fabrikanın okuduğu adlar kullanılmış (rapor 25 §2.2) |
| **T-052** | CDN teslim, imzalı URL, cache stratejisi | (1) Public türevler `immutable` (2) Özel/bekleyen medya kısa TTL'li imzalı URL, **imzasız → 403** (3) İçerik değişince URL değişir; **purge API'si çalışır** (4) CDN kapalı → aynı URL'ler yerel nginx'ten (5) nginx: `sendfile`, gzip/brotli, doğru `Content-Type`, **range desteği** | **KISMİ** | **Canlı ölçtüm** (gateway :8080, `Host: istoc.localhost`): (1) `/files/00/…` → `Cache-Control: public, max-age=31536000, immutable` ✔ (5) `Accept-Ranges: bytes` + `Range: bytes=0-9` → **HTTP 206, Content-Length: 10** ✔ (2) üç yoldan da **403**: `media_access.download` imzasız → 403, `/private/files/…` misafir → 403, `get_signed_url` misafir → 403 ✔ `test_delivery_sizes` 22 OK, `test_delivery_picture` 24 OK. Çalışan gateway'in `/etc/nginx/conf.d/default.conf` **md5'i host'taki `gateway.conf` ile birebir aynı** (`fc7e4baf…`) — dev'de uygulanmış. **EKSİK (3):** `cdn_purge_api_url` / `cdn_purge_token` alanlarını **hiçbir kod okumuyor** (repo geneli grep → yalnız rapor metinleri ve DocType JSON'u). **ÖLÇÜLMEDİ:** üretim ortamı — yalnız dev gateway'i ölçebildim; `docker/` git reposu olmadığı için `gateway.conf` sürümlenmiyor |
| **T-053** | Retention, arşivleme, GC işleri | (1) **Orijinaller ve türevler için AYRI zamanlanmış işler**, ayardan sürülen (2) `legal_hold=1` asla silinmez/taşınmaz (3) Silme = soft-delete + grace + audit (4) **Silinen türev istendiğinde şeffafça yeniden üretilir** (5) Kuru koşum silmeden rapor eder (6) Her koşum rapor üretir | **KISMİ** | `test_retention_gc` **22 OK** + `test_retention` **47 OK** (1 atlandı). (2)(3)(5)(6) test paketinde; kuru koşum varsayılan (`hooks.py:154`: `media_retention_gc_enforce` = 1 yapılmadıkça hiçbir şey silinmez) — **site_config'te medya bayrağı YOK, yani bayraklar 0** (ölçtüm). **EKSİK (1):** `scheduler_events["daily"]`'de **tek bir GC işi** var (`retention.run_scheduled_gc`); ikinci iş `media.backup.run_scheduled` ve o bir **yedek** işidir, "türev GC'si" değil. Orijinal/türev ayrımı **iş düzeyinde değil, aynı işin içinde**. **EKSİK (4):** `regenerate_on_demand` için **tüketen kod yok** — repo genelinde yalnız belgelerde ve `retention.py:1320`'deki *"'lazy' seçeneği tanımlı ama onu YAZAN kod yok"* yorumunda geçiyor. Türev GC'si bu yüzden fiilen `notify_only`'ye düşüyor |
| **T-054** | Yedekleme ve felaket kurtarma | (1) Orijinaller **ayrı hedefe** yedeklenir, RPO/RTO **sayısal** (2) **Geri yükleme kanıtlanmış ve ölçülmüş** (3) Türevler yedeklenmez kararı maliyet gerekçesiyle belgeli (4) Yedek bütünlüğü periyodik doğrulanır | **KISMİ** (4 kriterden 2'si) | `docs/plans/backup-dr.md` var; §3.1'de S1-S4 için **sayısal RPO/RTO tablosu** ✔ (1'in yarısı), §11 türev-yedeklenmez gerekçesi ✔ (3). **Canlı ölçtüm:** `backup.list_sets()` → **0 set**. Planın kendisi §23-24'te şunu yazıyor: *"Bugünkü fiilî RPO: **Sınırsız** — kurtarılacak bir medya yedeği yok. Bugünkü fiilî RTO: **Ölçülemez** — geri yüklenecek set yok."* (2) **YAPILMADI** — kurtarma provası yok, S4 senaryosunun DB restore adımı planda **ÖLÇÜLMEDİ** işaretli. (4) periyodik bütünlük kontrolü yok |
| **T-055** | Faz 5 kapanış — depolama kabul testleri | 6 senaryo: (1) dört kipte uçtan uca yükleme→teslim (2) S3+CDN kapalı → tam işlevsellik, **sıfır S3 çağrısı** (3) S3 açık + **hatalı kimlik** → yükleme başarılı, kopya başarısız, **alarm** (4) CDN açık → `cdn_base_url`; kapalı → yerel URL, aynı asset (5) `tiered` zaman ileri sarma (6) retention kuru koşum raporu onaylı | **YOK** | Kaynağın çıktı kalemi `tests/acceptance/test_storage_acceptance.py`. **Ölçüm:** `tradehub_core/tests/acceptance/` **dizini yok**, `test_storage_acceptance*` adlı dosya repoda **yok**. Senaryo 1 ve 2 dolaylı olarak `test_storage_adapters_minio` (91 OK) ile karşılanıyor. **3, 4, 5, 6 ölçülmedi.** `test_e2e_scenarios` 39 OK ama **8 atlama** taşıyor ve depolama kipleri senaryosu değil |

**Faz 5 sayımı: 2 TAM · 3 KISMİ · 1 YOK**

---

## 3. Faz 6 — Image engine

> Görev tanımı: *"denetimde ✅ KANITLI. Testleri koştur, hâlâ öyle mi doğrula."*
> **Cevap: hayır — bu çalışma ağacında T-067 KIRMIZI** (§0.2b). Diğer 7 görev
> yeşil.

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-060** | Probe + guard (decode etmeden karar) | Probe biçim/ölçü/alfa/kare/DPI/ICC/EXIF döndürür, tam decode etmeden; `fixtures/malicious/` reddedilir; uzantı-MIME uyuşmazlığı ve polyglot reddedilir; 30 MB'da < 50 ms | **TAM** | `test_image_probe` **16 test OK** |
| **T-061** | Normalize (yön, renk uzayı, DPI, piksel tavanı) | INV-01…INV-07 yeşil; 3000×3000@300dpi → 2400×2400@72dpi; CMYK/AdobeRGB → sRGB sapması ölçülü; EXIF yön uygulanıp alan temizlenir, GPS kalmaz; alfa korunur; 30 MB'da tepe bellek < 500 MB | **TAM** | `test_image_normalize` **25 test OK** |
| **T-062** | Sınıflandırma ve format zinciri | 5 sınıf ≥%95 doğruluk; her sınıf doğru format zinciri + kalite hedefi; grafik/logo lossless; animasyonlu GIF video hattına | **TAM** | `test_image_classify` **32 test OK** |
| **T-063** | Rendition üretimi (crop + resize + encode) | Profil×genişlik×biçim matrisi unique ihlali olmadan; `resolve_crop` simülatörle **birebir**; ≤4 denemede SSIM hedefi; girdiden büyük çıktı reddedilir; upscaling yok; eager/lazy ayrımı | **TAM** | `test_render` **73 test OK** + `test_quality_ssim` **21 test OK** + `docs/data/t063-render-olcum.json` |
| **T-064** | Idempotency ve yeniden işleme | (1) Motor çıktısı yeniden kodlanmadan tanınır (2) Crop değişince yalnız etkilenen türevler (3) Politika değişimi canlı trafiği etkilemeden partiye alınır (4) **Sürüm geçişi atomik; eski sürüm geçiş boyunca erişilebilir** | **KISMİ** | `test_render` içinde `YenidenOrneklemeTesti` sınıfı ve **48 `reprocess` çağrısı**; `test_motor_surumu_anahtara_katilir`, `test_bayat_motor_surumu_tazelenir`, `test_merdiven_idempotent` — hepsi yeşil → (1)(2)(3) ✔. **(4) ÖLÇÜLMEDİ ve ölçülemez:** `Media Version` DocType'ı kurulmadı (§1.1), `active_version` alanı `Media Asset`'te yok (`media_asset.json` `$comment` sapma 3) — "eski sürüm geçiş boyunca erişilebilir" iddiasının dayanacağı kayıt yok |
| **T-065** | LQIP + dominant renk | Sürüm başına LQIP + dominant renk, her biri <30 bayt; manifest LQIP döndürür; şeffaf görselde bozulmasız | **TAM** | `test_image_lqip` **27 test OK** |
| **T-066** | Kalite raporu ve tasarruf telemetrisi | Girdi/çıktı bayt, tasarruf oranı, SSIM, kararlar JSON; Türkçe özet satıcıya anlaşılır; aylık platform raporu | **TAM** | `image/report.py` (12 fonksiyon: `build_report`, `verdict`, `summarize_tr`, `merge_reports`, …); `test_render_regression.py:61` `report`ı **REP** olarak import edip test ediyor — ilgili testler geçti (kırılan tek test matris kilidi) |
| **T-067** | Faz 6 kapanış — golden fixture regresyonu | (1) Tüm fixture'lar manifest beklentilerini karşılar (**GREEN**) (2) 12 invariant ≥1 testle kapsanır, kapsam haritası (3) Performans bütçeleri ölçülü, CI eşikleri tanımlı (4) **Regresyon paketi her PR'da CI'da koşar (<10 dk)** | **KISMİ** | `test_render_regression` **32 test, 31 geçti, 1 KIRMIZI** — matris kilidi (§0.2b). HEAD'de yeşil, çalışma ağacında kırmızı. **(4) KARŞILANMIYOR:** `.github/workflows/` altında 5 dosya var (`alpha/beta/rc/prod-release`, `deploy`) ve **hiçbiri test koşmuyor** (`grep -l "run-tests\|pytest\|unittest"` → boş). Regresyon paketi CI'da **hiç koşmuyor**; her PR'da koşma kriteri ölçülemez değil, **karşılanmıyor** |

**Faz 6 sayımı: 6 TAM · 2 KISMİ · 0 YOK**

---

## 4. Faz 7 — Video engine

### 4.1 libvmaf — üretim imajında **YOK** (ölçüm)

```
$ docker exec istoc-dev-backend-1 ffmpeg -filters | grep -c libvmaf
0
$ ffmpeg -version
ffmpeg version 5.1.9-0+deb12u1 … (configure satırında --enable-libvmaf YOK)
$ vmaf_available()
False
```

**Kaynak Faz 7'nin kabul kriteri VMAF'ı üretim hattında şart koşuyor mu?**
Kaynak sayfa T-072'de: *"Şişirilmiş bitrate fixture'ı ≥%40 küçülme **+ VMAF ≥93**
göstermeli"* ve geliştirici kapsamında *"**Doğrulama:** VMAF ≥93, süre farkı
≤100 ms, ses var ve senkron, ilk kare siyah değil"*. Yani **evet** — VMAF, kabul
edilen bir çıktının **yayımlanma koşuludur**, isteğe bağlı bir metrik değil.

**Kodun bugünkü davranışı:** `video/transcode.py:520` VMAF yoksa SSIM/PSNR'a
düşüyor ve `"vmaf_note": "VMAF YOK — ffmpeg libvmaf olmadan derlenmis"`
yazıyor — **uydurma puan üretmiyor, bu doğru davranış.** Ama:

- Repoda **`93` eşiği hiçbir yerde sabit değil** (`grep "VMAF_MIN\|min_vmaf"` → 0
  sonuç; `transcode.py` içinde `93` yok). Yani VMAF kapısı **kod olarak
  uygulanmamış**.
- Test paketi bu boşluğu kendi adıyla kabul ediyor:
  `test_kalite_olculebiliyor_ama_VMAF_YOK` (`test_video_transcode.py:559`) —
  *"Konteynerdeki ffmpeg libvmaf olmadan derlenmiş — ÖLÇÜLDÜ."*

`22-t072-vmaf-av1.md`'deki 7/7 fixture ölçümü **dış araçla**
(`linuxserver/ffmpeg`) yapıldı; üretim imajı ve `docker-compose.yml`
değişmedi. Bu, **ölçümün yapıldığını** kanıtlar ama **hattın ölçebildiğini**
kanıtlamaz. Kaynağın kriteri ikincisini istiyor.

### 4.2 Görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-070** | ffprobe tabanlı probe + doğrulama | Probe tüm karar değişkenlerini döndürür, eksik alanlarda güvenli varsayılan; bozuk/kesik dosya reddedilir; 30 sn timeout + bellek sınırı, worker hayatta kalır; rotation doğru yorumlanır | **TAM** | `video/probe.py`; `test_video_transcode` içinde `test_olculemeyen_kaynakta_transcode_probeunavailable`, `test_olculemeyen_kaynakta_poster_unresolved`, `test_olculemeyen_kaynakta_hls_probeunavailable`, `test_dikey_videoda_olcu_KISA_KENAR` — **89 test OK** |
| **T-071** | Karar tablosu yorumlayıcısı | Karar JSON'dan okunur, kodda codec if/else zinciri yok; yeni codec **yalnız JSON** ile eklenir (testle kanıtlı); verimli MP4 → PASSTHROUGH; her karar eşleşen kuralı loglar | **TAM** | `test_video_decision` **58 test OK**; `policy/video_decision.json`; `test_h264_spec_tablodan`, `test_fayda_kapisi_tablodan`, `test_merdiven_tablodan_dort_basamak`, `test_poster_spec_tablodan`, `test_klip_spec_iki_katmanli_bayt_kapisi` — hepsi "tablodan" ilkesini test ediyor |
| **T-072** | Transcode, fayda kapısı, kalite doğrulaması | (1) H.264 baseline hep üretilir; AV1/VP9 yalnız fayda kapısı geçerse (2) **INV-05:** hiçbir çıktı girdiden büyük yayımlanmaz (3) Şişirilmiş fixture ≥%40 küçülme **+ VMAF ≥93** (4) **Süre farkı ≤100 ms**, ses senkron (5) HDR→SDR tone-mapping (6) faststart (moov başta) | **KISMİ** | **Yeşil olanlar:** (1) `test_bugunku_hattin_vp9u_URETILMIYOR` ✔ (2) `test_FAYDA_KAPISI_verimli_kaynagi_korur`, `test_fayda_kapisi_1080p_kaynakta_da_devreye_giriyor`, `test_remux_fayda_kapisina_TABI_DEGIL` ✔ (3-kısmi) `test_sisirilmis_video_transcode_edilir_ve_kabul_edilir`, `test_capped_crf_sabit_bitrateten_daha_az_bayt_uretiyor` ✔ (6) `test_faststart_var` + `test_ciktida_moov_BASTA` ✔ — **89 test OK**. **KARŞILANMIYOR (3):** VMAF üretim imajında ölçülemiyor, `93` eşiği kodda yok (§4.1). **ÖLÇÜLMEDİ (4):** süre farkı ≤100 ms için ne test ne kod bulundu (`grep "100 ms\|duration_delta\|sure_farki"` → 0 sonuç). **ÖLÇÜLMEDİ (5):** HDR→SDR tone-mapping testi bulunamadı |
| **T-073** | Poster, preview klip, hareketli önizleme | (1) Poster "anlamlı kare"den seçilir, görsel hattan geçer, rendition üretir (2) Klip 3-6 sn, sessiz, loop-safe, ≤1 MB (3) **Poster crop intent'e uyar; simülatörde video slotu poster üzerinden gösterilir** (4) `prefers-reduced-motion` **yalnız-poster teslim yolu** döndürür | **KISMİ** | **Yeşil:** (1) `test_yedi_fixturun_hepsinde_poster_uretiliyor`, `test_poster_parlaklik_kapisindan_geciyor`, `test_secilen_kare_ILK_KARE_DEGIL`, `test_poster_belirlenimci` ✔ (2) `test_klip_1MB_kapisini_geciyor`, `test_klip_sessiz`, `test_klip_suresi_3_6_sn_araliginda`, `test_klip_posterin_damgasindan_basliyor` ✔. **KARŞILANAMAZ (3):** `Media Crop Intent` DocType'ı **kurulmadı** (§1.1) → kaydedilmiş bir crop intent yok, poster ona uyduğu ölçülemez. **ÖLÇÜLMEDİ (4):** reduced-motion **politika alanı** var (`slot-policy.schema.json`) ama teslim yolunun poster-only döndürdüğü doğrulanmadı |
| **T-074** | HLS / adaptif teslim | (1) Eşiği aşan videolar 360p-1080p merdiveni üretir (2) Master playlist + segmentler doğru CDN cache başlıklarıyla (3) **Mobil veri tavanı: ilk 10 saniyede inen bayt ölçülüp standarda uygunluğu doğrulanır** (4) Eşik altı → progressive MP4, HLS zorlanmaz | **KISMİ** | **Yeşil:** (1) `test_1080p_kaynakta_dort_basamak_uretiliyor`, `test_720p_kaynakta_1080p_basamagi_URETILMEZ`, `test_buyutme_yok`, `test_dikey_kaynakta_basamaklar_dondurulur` ✔ (2) `test_master_playlist_var_ve_ayristirilabiliyor`, `test_segment_ve_playlist_ayarlari`, `test_segment_suresi_GOP_ile_hizali` ✔ (4) `test_hls_gerekliligi_sure_esigi`, `test_hls_gerekliligi_bayt_esigi`, `test_uzun_video_HLS_GEREKTIRIYOR` ✔. **KARŞILANMIYOR (3):** ilk-10-saniye bayt ölçümü için ne test ne kod var (`grep "ilk 10\|first_10\|10 saniye"` → `hls.py` ve testlerde 0 sonuç). En yakın olan `test_en_dusuk_basamak_3G_icin_gercek_kazanc` **toplam** baytı ölçüyor (10.450.180 → 708.609 B), ilk 10 saniyeyi değil |
| **T-075** | Faz 7 kapanış — video regresyon + kaynak bütçesi | (1) Tüm video fixture'ları manifest'e karşı GREEN (2) **INV-05 hiçbir senaryoda ihlal edilmez** (3) Worker CPU/bellek bütçesi tanımlı, eşzamanlı transcode sınırlı, canlı yükleme bloklanmaz (4) 4K60 uzun video fixture'ı ölçülü ve eşik içinde | **KISMİ** | **Yeşil:** video paketi toplam **208 test OK, 0 başarısız** (`test_video_decision` 58 + `test_video_transcode` 89 + `test_media_transcode` 22 + `test_media_transcode_retry` 39); INV-05 fayda kapısı testleriyle kanıtlı; `NICE_PREFIX` (`test_nice_onceligi_korunuyor`) ile öncelik düşürme yerinde; `18-faz7-kapanis.md` §7'de kaynak bütçesi ve 4K senaryosu yazılı. **Kapı hâlâ açık:** faz çıkış kapısı T-072'nin VMAF kriterine dayanıyor ve o kriter üretim hattında **ölçülemiyor** (§4.1) — kapı, ölçülemeyen bir eşiğin üzerinde duruyor |

**Faz 7 sayımı: 2 TAM · 4 KISMİ · 0 YOK**

---

## 5. Toplam sayım

| Faz | Görev | TAM | KISMİ | YOK |
|---|---:|---:|---:|---:|
| 4 · Veri modeli | 5 | 2 | 3 | 0 |
| 5 · Depolama · S3 · CDN | 6 | 2 | 3 | 1 |
| 6 · Image engine | 8 | 6 | 2 | 0 |
| 7 · Video engine | 6 | 2 | 4 | 0 |
| **TOPLAM** | **25** | **12** | **11** | **1** |

### 5.1 `31-gorev-numara-hizalama.md` ile fark

Rapor 31, 102 görevi çıkardı ama **hiç test koşmadı**. Bu koşumda beş yerde
ayrıldım:

| Görev | Rapor 31 | Bu ölçüm | Neden |
|---|---|---|---|
| `T-041` | TAM | **TAM** (aynı) — ama TS parite testi **kırık** | Rapor "63 test" dedi; 63'ün **62'si** geçiyor, 1'i Node sürümü yüzünden hiç koşmuyor |
| `T-043` | TAM | **KISMİ** | `Media Usage` **kalıcı kayıt değil**, bellek içi depo; kaynağın 1. kriteri karşılanmıyor |
| `T-051` | TAM | **TAM** (aynı) + **yeni kanıt** | Kayıtlı HTTP 500 **kapandı**; `get_storage_status` ve `test_connection` gerçek istekle **200** döndü |
| `T-064` | TAM (T-060…067 blok halinde) | **KISMİ** | Atomik sürüm geçişi `Media Version` olmadan ölçülemez |
| `T-067` | TAM (T-060…067 blok halinde) | **KISMİ / bugün KIRMIZI** | Altın matris kilidi düştü (§0.2b) + regresyon paketi **CI'da hiç koşmuyor** |

---

## 6. Ölçülemeyenler — açıkça

Bunlar "geçti" sayılmadı, "kaldı" da sayılmadı:

| # | Ne | Neden ölçülemedi |
|---|---|---|
| 1 | `crop_geometry.ts` ↔ `crop.py` paritesi | Konteynerde Node v20; `--experimental-strip-types` Node 22+ ister |
| 2 | Üretim ortamındaki nginx başlıkları | Yalnız dev gateway'ine (`istoc-dev-gateway-1`) erişimim var |
| 3 | `bench migrate` temiz koşumu | Paralel üç ajan koşuyordu; migrate kilidi riskli, **koşturmadım**. Dolaylı kanıt: 13 medya yaması `tabPatch Log`'da `skipped=0` |
| 4 | T-053 ıslak koşum (`media_retention_gc_enforce=1`) | **Bilerek koşturmadım** — bayraklar 0 kalsın talimatı; kuru koşum davranışı `test_retention_gc` 22 testiyle kapsanıyor |
| 5 | HDR→SDR tone-mapping (T-072/5) | Ne test ne kod bulundu — arama yaptım, yok |
| 6 | 1M asset ölçeğinde EXPLAIN (T-044) | `data-model-review.md` §4'te yazılı ama ölçüm geçici DB'de yapılıp düşürülmüş; yeniden üretilemedi |
| 7 | Satıcı rolüyle `Media Storage Settings` 403'ü (T-051/2) | Test kaydı üretmemek için satıcı oturumu açmadım; `test_media_storage_settings` 19 testi bunu kapsıyor |

---

## 7. Bu koşumun yan etkileri

**Hiçbiri.** Kaynak dosya değiştirilmedi, DocType/kayıt oluşturulmadı, bayrak
açılmadı, `bench migrate` koşturulmadı. Yazılan tek dosya bu rapordur.

`docker cp` ile `/tmp/chk1.py` konteynere kopyalandı (çalışmadı, frappe yolu
dışındaydı) — konteyner `/tmp`'inde kalan zararsız bir dosya.

Login oturumu (`/tmp/ck.txt` çerezi, Administrator) yalnız konteyner içinde,
GET isteklerinde kullanıldı; hiçbir yazma yapılmadı.

---

## 8. Doğrudan doğan iş kalemleri

Sıralama önem sırasına göre; hiçbiri bu görevin kapsamında **yapılmadı**.

1. **`MATRIS_ALTIN` ile `brand-logo.json`/`seller-logo.json` uyuşmuyor** — `w384`
   ekleyen ajan altın sabiti güncellemeli, yoksa Faz 6 kırmızı kalır.
2. **`openapi-http.yaml:4356` ve `4356` civarındaki `x-measured: http-fail`
   işaretleri bayat** — `get_storage_status` ve `test_connection` bugün 200
   dönüyor; `32-faz8-api-kapanis.md` G11/S12 satırları da gözden geçirilmeli.
3. **`boto3` `requirements.txt`'te değil** — imaj yeniden kurulunca T-050'nin
   91 MinIO testi ve S3 kipi çalışmaz hale gelir.
4. **CI hiç test koşmuyor** — 5 workflow'un hepsi release/deploy; T-067'nin 4.
   kriteri bu yüzden yapısal olarak karşılanamıyor.
5. **Konteynerde Node 22'ye çıkılmalı** ya da TS ikizi başka bir koşucuyla
   ölçülmeli; aksi hâlde panel↔backend kırpma paritesi korumasız.
6. **`docs/data/data-model-review.md` §8 maddeleri 5 ve 6 kapandı** — belge
   güncellenmeli, aksi hâlde kapanmış işi açık gösteriyor.
