# 87 — W7 Güvenlik & Depolama Kabulü (T-132 · T-135 · T-055 · T-133)

**Tarih:** 2026-08-20 · **Kapsam:** Faz 13 kalanları + S3 depolama kabulünün
MinIO ayağı. Yük testi kullanıcı onayıyla **SINIRLI** koşuldu (4 paralel × 30 sn,
tek uç). Commit atılmadı; hooks/patches'e dokunulmadı; prod'a/dış servise istek
yok; DB'de silme yok.

> **Ölçüm dürüstlüğü:** süre iddiaları yalnız yük ölçümünün kendi çıktısıdır
> (p50/p95 + hata oranı). "Hızlandı/yavaşladı" yorumu yoktur.

---

## Özet — bulgu tablosu

| # | Bulgu | Ciddiyet | Kanıt |
|---|---|---|---|
| **B-01** | **App-katman hız sınırı eşzamanlılıkta DEVRE DIŞI** — `api/rate_limit.py` sayacı atomik değil (get→delete→set); paralel istekte kayıp-güncelleme yarışı. 4 worker'da manifest_batch **600/60s sınırının >10 katı** geçti, 0×429. RUM'da da: 320 eşzamanlı çağrı (sınır 30/60s) → 0×429. | **Yüksek** | T-135b ölçümü |
| **B-02** | Gölge modül `tradehub_core/tradehub_core/api/seller.py` — `api/seller.py`nin eski kopyası, 5 guest ucunu İKİNCİ kez expose ediyor. | Orta | T-132 tarama |
| **B-03** | Payment Transaction `seller_iban` / `seller_bank_name` **permlevel-0** — alan düzeyi koruma yok; satırı okuyan IBAN'ı okur. | Orta | T-132 doctype taraması |
| **B-04** | Dev sitesi guest'e **tam Python traceback + iç dosya yolları** döndürüyor (5xx'te). Prod'da `allow_error_traceback`/`developer_mode` kapalı DOĞRULANMALI. | Orta (dev-config) | T-135a |
| **B-05** | `Content-Type: application/json` + geçersiz gövde → Frappe `make_form_dict` **500** (framework, uç-öncesi, app-geneli). Gerçek RUM yolu `text/plain` sorunsuz. | Düşük | T-135a |
| **B-06** | nginx `files_zone` (10r/s) engagement dev'de **doğrulanamadı** — `limit_req_zone` tanımı storefront vhost template'inde, gateway `default.conf` /files/ isteğini 404 fallback'e düşürüyor. | Düşük / açık | T-135a |
| **G-01** | **MinIO S3 kabul: 4/4 GERÇEK GEÇTİ.** Adaptörün ilk gerçek S3 sınaması; kod düzeltmesi gerekmedi. | (kabul) | T-055 |
| **G-02** | Konteynerlerin HİÇBİRİNDE `boto3` yok — `storage/s3.py` docstring'inin "backend konteynerinde VAR" iddiası bugün YANLIŞ. | Not | ölçüm |

---

## T-132 — Yetki sertleştirme / sızıntı testleri

### Mevcut kapsamın ölçümü

Faz 13 cross-tenant kanıtları **güçlü ve vacuity-kontrollü**. Bugün eklenen
yüzeylerin her biri için cross-tenant testi VAR:

- **folders** → `test_media_folder.py` (kiracı-arası klasör erişimi reddi + vacuity)
- **orphans** → `test_media_orphans.py` (öksüz raporu kiracı-sızdırmıyor)
- **manifest_batch** → `test_manifest_batch.py` / `test_http_api_contracts.py`
- **dedup** → `test_media_dedup_endpoint.py` (içerik-hash başka kiracıya sızmıyor)
- **RUM** → tenant alanı YOK (tasarım) → cross-tenant anlamsız; PII reddi test ediliyor

### Eksik olan ne (spec vs mevcut)

Şartnamenin istediği ama testi OLMAYAN üç yüzey:

1. **Misafir yüzeyi taraması** — `test_http_api_contracts.py` yalnız MEDYA
   hattının 4 guest ucunu donduruyordu; oysa `tradehub_core/` altında
   `@frappe.whitelist(allow_guest=True)` taşıyan **111** fonksiyon var. Yeni
   bir guest ucu sessizce eklenebilir, hiçbir test kırılmazdı.
2. **permlevel (alan düzeyi)** — KYC/KYB `status` permlevel-4 pinliydi ama Media
   Asset moderasyon alanları (28-faz13-pentest §8'de "canlı doğrulandı" denen
   ama testi olmayan yüzey) için birim testi yoktu.
3. **rol yükseltme (yeni yüzeylerde)** — cross-tenant VAR ama aynı-kiracı-düşük-rol
   → yüksek-rol yükseltme senaryoları bench-bağımlı ve YAZILMADI (aşağıda açık).

### Yazılan test — `tests/test_faz13_guest_surface.py` (frappe-siz, 8 test)

CI kapısında (`scripts/run_authz_tests.sh`) koşar, bench/site GEREKTİRMEZ.
Konteynerde (Python 3.11) ve host'ta (3.9) **8/8 GEÇTİ** doğrulandı.

- `GuestSurfaceDriftTests` (4): AST taraması ile **111 guest ucunu** dondurur;
  yeni/silinen uç güvenlik incelemesi tetikler. Denylist (`get_signed_url`,
  `manifest_batch`) guest DEĞİL doğrulaması + yeni medya yüzeylerinin guest
  kümesinde olduğu pozitif kontrol.
- `MediaAssetPermlevelTests` (4): 8 moderasyon alanı (state, owner_seller,
  legal_hold, rejection_code…) permlevel≥1; seller rolleri permlevel-1'de
  write=0; platform rolleri write=1; + **vacuity kontrolü** (matris gevşetilince
  iddia gerçekten kırılıyor mu).

**Bilinen sınır (dürüstçe):** AST yalnız dekoratör-biçimini yakalar;
`seo/page_resolver.py`'nin `frappe.whitelist(...)(render_x)` çağrı-biçimiyle
kaydettiği 6 SEO renderer baseline'a DAHİL EDİLMEDİ (yakalanamayanı dondurmak
sahte güven olurdu) — ayrı ele alınmalı.

### Kapıya eklendi

`scripts/run_authz_tests.sh` MODULES'a iki modül eklendi: `test_faz13_guest_surface`
(yeni) ve `test_authz_regression` (mevcut ama kapıda EKSİKTİ). Script `bash -n` ile
geçerli. İki modül **konteynerde (Python 3.11) gate-çağrımıyla ayrı ayrı GEÇTİ**:
`test_authz_regression` 24 test OK, `test_faz13_guest_surface` 8 test OK.

> **Tam-suite koşum notu (dürüstçe):** 47 modüllük kapının TAMAMI ne host'ta ne
> konteynerde sınırlı sürede tamamlanamadı — **mevcut** `test_tuple_sync` modülü
> ASILIYOR (host'ta 3.9 ile 40 dk %99 CPU; benim değişikliğimle ilgisiz,
> eklemelerimden ÖNCEKİ bir durum). Ayrıca host Python 3.9 olduğu için ~11 mevcut
> modül `str | None` (3.10+) sözdizimiyle import'ta hata veriyor — kapı zaten
> konteyner/CI (3.11) için tasarlanmış, host koşumu temsili değil. Bu iki durum da
> DEVİR listesine alındı; benim iki eklemem izole olarak 3.9 ve 3.11'de yeşil.

### Kalan açık — rol yükseltme (bench-bağımlı, YAZILMADI)

Yeni yüzeylerde aynı-kiracı düşük-rol → yüksek-rol yükseltme senaryoları gerçek
site/fixture gerektirir (FrappeTestCase), frappe-siz kapıya girmez. Somut
öneri: Seller rolüyle Media Asset moderasyon alanını `db.set_value` yolundan
yazmayı dene → permlevel korumasının API katmanında da tuttuğunu ölç (B-03'ün
Payment Transaction karşılığı da aynı test dosyasına).

---

## T-135 — SINIRLI yük + sızma

### (a) Sızma — misafir yüzeyi

**Envanter:** 111 dekoratör-biçimli guest ucu koddan çıkarıldı (T-132 tarama).
Kritik medya uçları: `rum.collect` (POST), `media_manifest.get_manifest[_batch]`,
`media_access.download`, `observability.metrics|status` (Bearer token).

**Bozuk/kötücül girdi — `rum.collect` (gerçek `text/plain` yolu):** boş, dev
gövde (20KB), yanlış-tip, dizi, PII-içeren (email/user) → hepsi **200** (zarif;
veri sızıntısı yok, RUM `reason=malformed_body` sayacına düşüyor). Beklenmeyen
5xx yalnız B-05'te (framework, uç-öncesi).

**B-04 (traceback sızıntısı):** dev sitesi 5xx yanıt gövdesinde tam traceback +
`apps/frappe/...` yollarını guest'e döndürüyor. Prod imajında
`allow_error_traceback=0` doğrulanmalı.

### (b) Yük — SINIRLI (4 paralel × 30 sn, tek uç: get_manifest_batch)

Makine kilitlenmedi; hata oranı 0. Ölçülen (12 gerçek `LST-*` kimliği, gateway :8080):

| metrik | değer |
|---|---|
| toplam istek | 6195 (30,0 sn) |
| throughput | 206,4 req/s |
| HTTP 200 | 6195 (%100) |
| **429** | **0** |
| p50 | 16,8 ms |
| p95 | 39,5 ms |
| p99 | 72,2 ms |
| max | 125,8 ms |

**B-01 — hız sınırı devrede DEĞİL (kök neden).** manifest_batch sınırı 600/60s;
30 sn'de 6195 istek (≈12k/60s, sınırın >10 katı) 0×429 ile geçti. Aynı ucu
**ardışık** (yarışsız) koşunca sınır DEVREYE GİRİYOR: 700 ardışık → 152×429.
RUM'da da doğrulandı: **ardışık** 40 çağrı → 31.'de 429 (sınır 30/60s tam); ama
**320 eşzamanlı** çağrı → 0×429.

Kök neden `tradehub_core/api/rate_limit.py:214-220`: artış atomik değil —
`get_value` → `delete_value` → `set_value(current+1)`. Docstring "Redis INCR +
EXPIRE" diyor ama kod INCR kullanmıyor; eşzamanlı okuyucular aynı `current`i
okuyup üstüne yazıyor (kayıp güncelleme). Bu dekoratörü kullanan TÜM uçları
etkiler. **Düzeltme sahibim değil** (rate_limit.py kapsam dışı) — öneri: atomik
`cache().incr(key)` + ilk artışta `expire(window)`; TTL'i her artışta yenileme.

**files_zone (B-06):** 40 hızlı `/files/` isteği (doğru Host başlığıyla da) →
40×404, 0×429/503. `limit_req_zone` tanımı `nginx/storefront.local.template`de;
gateway `default.conf` bu isteği rate-limit uygulayan vhost'a sokmuyor.
Engagement dev'de doğrulanamadı — prod nginx'te gerçek bir `/files/<var-olan>`
yoluyla ayrıca ölçülmeli.

> **İz notu (şeffaflık):** yük/sızma probları RUM sayaçlarını hareket ettirdi
> (`media_rum_rejected_total{reason="malformed_body"}` ≈350). Bunlar süreç-içi
> ephemeral sayaç; DB satırı DEĞİL, süreç yeniden başlarken sıfırlanır.

---

## T-055 — S3 ayağı (MinIO)

`tests/acceptance/test_storage_acceptance.py`'nin 4 skip'i (`TestKabulS3Kipleri`)
`MEDIA_ENGINE_S3_*` env'i **açıkça MinIO'ya işaret ederek** koşuldu — skip
gerekçesi "örtük bağlanmak kanıt değil"di; açık env ile koşmak meşru dev-kabul.

**Kurulum:** boto3 konteynerlerin HİÇBİRİNDE yok (G-02), MinIO'ya host-eşlemeli
port `:9100`'den erişiliyor; saf medya paketi frappe'siz import ediliyor. Bu
yüzden ephemeral host venv (boto3 1.42) + endpoint `http://localhost:9100`,
kimlik `minioadmin`, kendi bucket'ım `t055-kabul-run`.

**Sonuç — 4/4 GERÇEK GEÇTİ (0,224 sn):**

| test | sonuç |
|---|---|
| `test_s3_primary_uctan_uca` | ✅ (put/get/exists/delete gerçek S3) |
| `test_mirror_uctan_uca` | ✅ |
| `test_tiered_uctan_uca_ve_goc` | ✅ (demote→cold, S3'ten okuma) |
| `test_s3_yanlis_kimlik_yerel_calisir` | ✅ |

Adaptörün (`storage/s3.py`) **ilk gerçek S3 sınaması** — daha önce yalnız sahte
istemciyle ölçülmüştü. Kırık çıkmadı, **kök-neden düzeltmesi gerekmedi**.
`sig_version=s3v4` + `addressing_style=path` MinIO ile çalıştı. **İz bırakılmadı:**
tiered testinin soğuğa bıraktığı 1 nesne temizlendi, `t055-kabul-run` bucket'ı
silindi (önceki `istoc-medya-test`/`t051-panel-probe` bucket'ları benim değil).

---

## T-133 — Alarm kuralları

`docs/observability/media-alerts.yml` üretildi — **18 kural / 2 grup**, PyYAML ile
parse doğrulandı, tüm metrik referansları kayıt defterinde mevcut.

- **`media-engine` (16, KANONİK):** `alerts.py::to_prometheus_rules`'tan üretildi;
  `dogrula()` ile tutarlı (0 unknown_metric, 0 duplicate, 24 metrik). Eşikler
  kaynaklı (`threshold_source`): ölçülmüş (orphan 1166, image p95 5s), kod-sabiti
  (isolation, svg sıfır-tolerans) ya da dış-standart (CWV: LCP 2500ms, CLS 0.25,
  INP 200ms).
- **`media-engine-queue` (2, EK):** mevcut ama alarmsız metriklerden
  (`media_job_total`, `media_job_attempts`) kuyruk sağlığı — eşikleri **İLK 2
  HAFTA GÖZLEM** işaretli, kalıcı olunca `alerts.py`ye taşınmalı.

**Ölçülmüş gerçeklik (2026-08-20 /metrics):** canlı seri taşıyan tek aile
RUM + audit_event; o veri de tohum/test (LCP p75 12712ms bir aykırı tohum).
Yükleme/tarama/izolasyon/depolama/orphan/PII metrikleri **0** — üretim tabanı
yok; bu yüzden çoğu eşik "ÖLÇÜLMEDİ / ilk hafta" der.

**Metriği OLMAYAN istekler (uydurulmadı):** "417 oranı" — kodda 417 statüsü yok
(ret `media_upload_total{outcome="rejected"}` ile izlenir, `MediaUploadRejectionSpike`
zaten kapsar); "drift" — observability paketinde drift metriği yok. Kaynak seri
olmadan alarm yazmak sessiz-boş kural üretir → yazılmadı, gap olarak raporlandı.

**Kurulum:** `docs/runbooks/media-go-live.md`'ye "**EK — Prometheus alarm kurulumu
(T-133)**" bölümü eklendi: üç-süreç scrape config (bearer_token_file), promtool
check, reload, eşik-gerçekliği uyarısı, 18 runbook slug listesi (henüz yazılmamış
`docs/ops/runbooks/`).

---

## Sahiplik / dokunulan dosyalar

- **Yeni:** `tradehub_core/tests/test_faz13_guest_surface.py`,
  `docs/observability/media-alerts.yml`, `docs/reports/87-w7-guvenlik-kabul.md`
- **Düzenlenen:** `scripts/run_authz_tests.sh` (2 modül eklendi),
  `docs/runbooks/media-go-live.md` (EK bölüm)
- **Dokunulmadı:** `storage/s3.py` (düzeltme gerekmedi), `rate_limit.py` (B-01
  kapsam dışı — rapor), tüm prod/DB/hook/patch.

## Devir — açık işler (öncelik)

1. **B-01 (Yüksek):** `api/rate_limit.py` atomik artışa geçir (`incr`+`expire`);
   sonra 4×30s manifest_batch tekrar koş → 429 tavanda görünmeli.
2. **B-03 (Orta):** Payment Transaction IBAN alanlarına permlevel ver **veya**
   satır-kapsam korumasını test-pinle.
3. **B-02 (Orta):** gölge `tradehub_core/tradehub_core/api/seller.py` — hangisi
   routed, gölge yeni guard'ları taşıyor mu; tekilleştir.
4. **B-04 (Orta):** prod imajında `allow_error_traceback=0` doğrula.
5. **Rol yükseltme testleri (bench):** yeni yüzeylerde düşük→yüksek rol; B-03 ile
   aynı FrappeTestCase dosyası.
6. **B-06:** files_zone'u prod nginx'te gerçek `/files/` yoluyla ölç.
7. **Kapı hijyeni (mevcut, benim değil):** `test_tuple_sync` ASILIYOR — authz
   kapısının tamamı bu yüzden bounded sürede bitmiyor. Ayrı incelenmeli;
   düzelene dek kapı bu modülü `timeout`la sarmalı ya da geçici çıkarmalı.
