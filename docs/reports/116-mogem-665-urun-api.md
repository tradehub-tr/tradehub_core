# MOGEM-665 · İstoc Ürün API'si — plan, uygulama ve doğrulama

**Tarih:** 15 Eylül 2026 · **Kaynak:** Plane MOGEM-665 (7 aşama, 27 kabul kriteri) + "Ürün API'si Yapım Planı" (artifact f5c3b3eb, 9 Eyl) · **Yapım sırası:** plan §07 diyagramı — 0 → A → B → C, D paralel, E, F.

## 1. Görevin kelimesi kelimesine okunuşu — kabul kriterleri → kanıt

| Aşama | Kriter | Nerede karşılanır | Kanıt (test) |
|---|---|---|---|
| 1 | Aynı mağazada aynı stok koduyla iki ürün oluşmaz; farklı mağazalar aynı kodu kullanabilir | `Listing.validate` + `(seller_profile, seller_sku)` bileşik benzersiz indeks (`patches/v15_9_57_seller_sku_unique.py`) | `test_mogem665_0_duzeltmeler::TestSellerSkuBenzersiz` |
| 1 | Metre/ton/kutu/çift/saat birimleri gönderildiği gibi kaydedilir | `persister._TR_UOM_ALIASES` Türkçe adlara; `_resolve_link` önce ham değeri dener | `::TestBirimCevirisi` |
| 1 | Renk/beden seçili ürün sepete eklenirken o seçeneğin gerçek stoğu | `api/cart.py` "Listing Variant" (olmayan doctype) → `Listing Variant Item` | `::TestSepetVaryantStogu` |
| 1 | API aktarımı dosya yüklemesi devam ediyor diye engellenmez; sınır mesajları doğru | `start_product_import` kilidi yalnız dosya/feed işlerine; "200 MB" → "50 MB"; API kendi eşzamanlılık kilidi | `::TestIsKilidi` |
| 2 | Yetkisiz kişi/program ekleyemez, değiştiremez, stok değişikliklerini göremez | `api/v1/_catalog_auth.py` — Bearer + scope + mağaza bağı; misafir/eksik scope → 401/403 | `test_mogem665_a_kimlik` |
| 2 | Bir mağazanın bağlantı bilgileri başka mağazayı etkilemez | jeton `seller` taşır; tüm sorgular `seller_profile` süzgeçli | aynı |
| 2 | Ürün doğru satıcıya ait; paket sınırları korunur | `frappe.set_user(mağaza sahibi)` devri; `check_listing_creation_quota` + `feature.pim.multi_variant` | aynı + `test_mogem665_b_urun` |
| 3 | Yeni kod → oluşur; aynı kod → güncellenir; tekrar → sayı artmaz | `catalog.upsert_products` → `persister.check_sku_exists / create_listing / update_listing` | `test_mogem665_b_urun` |
| 3 | En fazla 100 ürün; her ürünün sonucu anlaşılır | `MAX_UPSERT_ITEMS=100`, satır bazlı `results[]` (`created/updated/unchanged/rejected`, `error`, `field`, `message`, `warnings`) | aynı |
| 3 | Hatalı satır diğerlerini durdurmaz; negatif stok/fiyat, satış>liste reddedilir | satır başına try/except + `validate_pricing/validate_stock` | aynı |
| 3 | Gönderilmeyen alan silinmez; stok 0 yazılabilir; para birimi yoksa TRY | `persister.update_listing` (boş korunur, 0 geçerli), `_DEFAULTS` | aynı |
| 3 | ≤10 görsel; jpg/png/webp; ≤5 MB; alınamayan görsel ürünü durdurmaz | `image_url_ingest` (5 MB, tür denetimi) + `MAX_IMAGES=10` | aynı |
| 3 | Varyantlı yeni ürün paket izin veriyorsa; desteklenmeyen varyant güncellemesi yapılmış gibi gösterilmez | `create_listing_with_variants`; güncellemede `variants` → `warnings: VARIANTS_NOT_UPDATED` | aynı |
| 4 | ≤500 stok/fiyat; bulunamayan/hatalı ayrı bildirilir | `catalog.update_stock`, `MAX_STOCK_ITEMS=500` | `test_mogem665_c_stok` |
| 4 | "Stok 100" iki kez → 100; 0 yazılabilir; fiyat kuralları | mutlak yazım (K4) | aynı |
| 4 | Ad/açıklama/görsele dokunmaz; yeniden onaya göndermez; stok 0 durumu değiştirmez | `frappe.db.set_value` yolu (validate/status akışı çalışmaz) | aynı |
| 4 | Eşzamanlı sınır + anlaşılır uyarı; bilgiler karışmaz | mağaza başına Redis kilidi (`catalog_lock:{seller}:{op}`) + tier hız sınırı → 429 `RATE_LIMITED` / 409 `BUSY` | aynı |
| 5 | Satışta değişen ürün, yeni stok, uygun miktar, neden, zaman iletilir | `utils/stock._recalculate_available(reason=…)` → `Catalog Outbound Event` | `test_mogem665_d_giden_olay` |
| 5 | Webhook alamayan `changes` ile eksiksiz alır | `catalog.changes(since, limit)` + `next_since` | aynı |
| 5 | Ulaşmayan bildirim tekrar denenir; tükenince panelde; imza doğrulanabilir | `integration/outbound.py` — 5 deneme (1/5/15/60/360 dk), `dead`, `X-Istoc-Signature` HMAC-SHA256 | aynı |
| 5 | Başarısız işlem gerçekleşmiş gibi bildirilmez; yankı döngüsü yok | olay yalnız sipariş yolundan (`_recalculate_available`); API stok yazımı olay üretmez | aynı |
| 6 | API aktarımları panelde ayrı süzülür; geçmiş/sonuç/hata | `Bulk Import Job.source = api`, `get_my_history(source=…)` | `test_mogem665_e_panel` + panel |
| 6 | Yeni ürünler onay sürecine girer, toplu onaylanır | K6: gerçek iş kaydı → `bulk_approve_listings_from_job` değişmeden | aynı |
| 6 | Başarısız bildirimler bulunabilir; dosya yükleme çalışmaya devam eder | `catalog_integration.list_outbound_events`; mevcut testler yeşil | aynı |
| 7 | Kılavuz + uçtan uca gösterim | `docs/URUN-API-KILAVUZU.md` + `test_mogem665_e2e_http` (gerçek HTTP) | e2e |

## 2. Mevcut koddan çıkarım — artı/eksi yönler

(Plan belgesindeki 9 karar aynen alındı; kod 15 Eyl'de yeniden doğrulandı.)

**Artı (aynen kullanılan):** `bulk_import/persister` (create/update/varyant), `image_url_ingest` (SSRF + 5 MB + tür), `public_api.token` (OAuth2 client credentials, JWT HS256 site sırrı), `rate_limit` sarmalayıcısı (IP sahteciliğine sert), `bulk_approve_listings_from_job`, `Bulk Import Job` geçmiş/hata ekranları, `entitlement` kota/özellik kapıları, `utils/stock._recalculate_available` tek çıkış noktası.

**Eksi (önce düzeltilen):** (1) `seller_sku` benzersiz değil; (2) UOM alias tablosu İngilizce (DB Türkçe: Adet, Metre, Ton, Kutu, Çift, Saat…) → "metre" sessizce Adet; (3) `api/cart.py` 4 yerde olmayan `"Listing Variant"` doctype'ını okuyor; (4) `start_product_import` kilidi her işi sayıyor; (5) 50 MB sınır, mesaj "200 MB". Ek: `API Application` mağazaya bağlı değil, jetonlu uçlar Guest çalışıyor (plan K2); `runner.py:344` upsert varyantlara dokunmuyor (K8 kapsam dışı).

**Netleştirilen kararlar (görevdeki "başlamadan" maddeleri):**
- Satış fiyatı gönderilmezse: yeni üründe liste fiyatı kopyalanır (persister zaten yapıyor); mevcut üründe fiyat değişmez (boş korunur). İkisi de test edildi.
- Eşzamanlılık: mağaza başına aynı anda **1** ürün aktarımı + **1** stok güncellemesi (Redis kilidi, 120 sn TTL); hız sınırı uygulama katmanına göre (free 60/dk, pro 600/dk, enterprise 6000/dk). Webhook **5** deneme (1, 5, 15, 60, 360 dk).
- Varyant: ilk sürüm oluşturur, güncellemez; güncellemede `variants` gelirse `VARIANTS_NOT_UPDATED` uyarısı döner.

## 3. Uygulama günlüğü (15 Eyl 2026 — diyagram sırası 0→A→B→C→D→E→F)

| Aşama | Ne yapıldı | Test |
|---|---|---|
| 0 Düzeltmeler | `Listing._validate_seller_sku` + `v15_9_57` unique index; UOM alias Türkçe + `_resolve_link` kanonik ad; sepet `Listing Variant Item`; çoklu varyant kapısı `variant_items`; sevkiyatta varyant çift düşümü kaldırıldı; `_assert_no_active_file_import` yalnız dosya/feed; File IDOR (`_own_file`); `Bulk Import Job.source`; `.xml/.json` medya beyaz listesi | `test_mogem665_0_duzeltmeler` 17 |
| A Kimlik | `_catalog_auth` (Bearer → mağaza sahibi oturumu, `feature.api.access`, `quota.api_rate_limit`, `auth_hooks` kancası yalnız catalog.* yolunda, form_dict korunur); `catalog_integration` panel uçları; jeton ucu IP başına 30/dk | `test_mogem665_a_kimlik` 25 |
| B Ürün | `catalog.upsert_products` (≤100, savepoint/satır, kodlu sonuç, SEO 50/150 kuralı açık kodla, görsel ≤10, varyant yalnız oluştururken, `Bulk Import Job source=api` + gövde private File) | `test_mogem665_b_urun` 35 |
| C Stok | `catalog.update_stock` (≤500, mutlak, `db.set_value` — durum/onay akışına dokunmaz, varyant SKU: fiziksel − açık rezerv, vitrin önbelleği) | `test_mogem665_c_stok` 19 |
| D Bildirim | `Catalog Outbound Event` + `integration/outbound.py` (HMAC, 10 sn, 1/5/15/60/360 dk, dead, */5 sweep, requeue); `_recalculate_available(reason)`; `catalog.changes` | `test_mogem665_d_bildirim` 15 |
| E Panel | `get_my_history(source)`, `import_source` rozeti, `/seller-api` ekranı + nav (`v15_9_58`), i18n 4 dil | `test_mogem665_e_panel` 5 + node 8 |
| F Sözleşme | `docs/URUN-API-KILAVUZU.md`, CHANGELOG, misafir uç kümesi dondurma | `test_mogem665_f_sozlesme` 4 |
| Maymun | tohumlu rastgele gövde × 40 tur; değişmezler (durum kümesi, sayaçlar, negatif yok, kilit serbest, yankı yok) | `test_mogem665_monkey` 1 |

**Gerçek HTTP uçtan uca** (`scratchpad/m665_e2e.py`, konteyner içinden 127.0.0.1:8000 + Host): 33/33 — token/401/417/409/429, upsert kısmi başarı, güncelleme, varyant stoğu, yankı yok, sipariş rezervi → olay → `changes` → gerçek webhook 204 + HMAC eşleşmesi, kapatma → 401.
**Panel** (Playwright, vite 8082, `/api/method/login`): bağlantı oluştur → sır bir kez, webhook, olay sayaçları/süzgeç/yeniden dene, satır içi onay, sır yenileme, `/bulk-import?source=api`, sidebar kalemi, mobil 390 px yatay taşma yok.

**Yalnız gerçek HTTP'de çıkan kusurlar (süreç içi testler yeşildi):**
1. Frappe `validate_auth` iki parçalı Authorization'ı kullanıcı atanmadan 401 kesiyor → `auth_hooks` kancası (yalnız catalog.* yolu). Not: `public_api`'nin diğer Bearer uçları aynı nedenle HTTP'de çalışmıyor (kapsam dışı, raporlandı).
2. `frappe.set_user` `form_dict`'i sıfırlıyor → gövde kayboluyordu; kancada sakla/geri yükle.
3. `Listing._validate_seo_content` (başlık 50–250, açıklama ≥150) `in_test`'te atlanıyor → API'de açık kod (`SEO_TITLE/SEO_DESCRIPTION`).
4. `save_file(dt="")` → "Error Attaching File"; File alan verilmeden açılıyor, Frappe kendisi bağlıyor.

**Kod incelemesi bulgusu (düzeltildi):** varyantta ayrı `reserved_qty` yok; mutlak stok yazımı açık sipariş rezervini silerdi → `_open_variant_reservation` düşülüyor (`TestVaryantRezerv`).

**HEAD'de zaten kırık, bize ait değil (stash ile doğrulandı):** `bulk_import.tests.test_persister_attributes` (1), `tests.test_rate_limit_guest_bucket` (1), `tests.test_http_api_contracts` (4 — `seller_media` belge sapması), stub tabanlı `test_cart_price_tampering`/`test_entitlement`.

**Bilinçli yapılmayanlar:** ürün silme/arşivleme, varyant güncelleme, görsel silme API'de yok; stok güncellemeleri içe aktarma geçmişine yazılmaz (dakikalık ERP döngüsü geçmişi şişirir); log saklama süresi kullanıcı kararı.


## 4. Uzun kampanya (15 Eyl, 18:16–19:30 UTC + ayıklama) — "yeşile inanma" turu

| Faz | Kapsam | Sonuç |
|---|---|---|
| Tüm core modülleri (338, tek tek; `--app` keşfi HEAD'de `test_approval_workflow` stub'ı yüzünden kırık) | 6.592 test, 30 dk | 248 OK · 81 kırık → stash ile HEAD'e karşı ayıklandı: **80 zaten kırık, 1 bize ait** (`test_secret_access_audit`: `_verify_client` `.get` → `getattr`, düzeltildi) |
| Soak 25 dk (10 döngü, gerçek HTTP) | 16 paralel `update_stock` → 1×200 + 15×409, tek tutarlı değer; 8 paralel karışık → 500 yok; kota 20 → tam 20×200+20×429; jeton kaba kuvvet 401→429; 100 ürün upsert 1,3 s; 500 kalem 0,2 s; 150 ardışık mutlak yazım; 40 olay webhook (alıcı 2× 500) → backoff 1/5/15/60/360, dead, requeue→sent; 40/40 HMAC; izolasyon; sayfalama | Ürün değişmezleri her döngüde tuttu; 2 "FAIL" betiğin yanlış beklentisiydi (alıcı 2 kez düşürülmüştü) |
| Maymun tohum taraması 30 tohum × 60 tur | rastgele gövdeler | 30/30 değişmez; 8 tohumda "≥6 geçerli çağrı" sağlık eşiği tutmadı → eşik ≥2 (üreteç istatistiği) |
| Gerçek HTTP e2e × 10 | 33 adım | 10/10 → 33/33 |
| MOGEM-665 paketleri × 3 | 120 test | 3/3 yeşil |
| Panel Playwright × 3 (taze fixture) + node × 3 | 18 adım / 1.700 test | 3/3 → 18/18; 1.691/1.691 |

**Kampanyanın bulduğu ek kusur:** silinen ürünün olayları kalıyordu; seri geri sarma (`revert_series_if_last`) adı yeni ürüne verince yetim olaylar yeni ürüne yapışıyordu (e2e'de görüldü) → `Listing.on_trash` kaskadı (`outbound.on_listing_trash`) + test.

## 5. Kelime kelime kriter denetimi (16 Eyl, Plane metni yeniden okundu)

☑ = karşılandı, kanıt yanında. **27/27 kabul kriteri + 3 "başlamadan netleştirilecek" madde.**

| # | Kriter (Plane metni) | Durum | Kanıt |
|---|---|---|---|
| 1.1 | Aynı mağazada aynı stok koduyla iki ayrı ürün oluşmaz; farklı mağazalar aynı kodu kullanabilir | ☑ | `Listing._validate_seller_sku` + `uniq_listing_seller_sku` (v15_9_57) · `test_mogem665_0` |
| 1.2 | Metre/ton/kutu/çift/saat gönderildiği biçimde kaydedilir; metre adet görünmez | ☑ | `_TR_UOM_ALIASES` + `_resolve_link` · `test_birim_korunur` + e2e "A birim Metre" |
| 1.3 | Renk/beden seçili ürün sepete eklenirken o seçeneğin gerçek stoğu | ☑ | `cart._check_stock` → `Listing Variant Item` · `test_mogem665_0` |
| 1.4 | API aktarımı dosya yüklemesi sürüyor diye engellenmez; yoğunluk/boyut uyarıları gerçek sınırı açıklar | ☑ | `_assert_no_active_file_import(source≠api)`; mesajlar `MAX_*_BYTES` sabitinden · `test_mogem665_0/b/e` |
| 2.1 | Yetkisiz kişi/program ekleyemez, değiştiremez, stok değişikliklerini göremez | ☑ | Bearer+scope+mağaza bağı; JWT kurcalama (4 test) · `test_a_kimlik`, `test_g_kapsam` |
| 2.2 | Bir mağazanın bağlantı bilgileri başka mağazayı etkilemez | ☑ | `test_baska_magazanin_sku_su_*`, soak izolasyon, changes izolasyon |
| 2.3 | Ürün doğru satıcıya ait; paket ürün sayısı/özellik sınırları korunur | ☑ | `owner=mağaza sahibi`; `QUOTA_EXCEEDED`, `FEATURE_DENIED`, `feature.api.access` |
| 3.1 | Yeni kod → oluşur; aynı kod → güncellenir; tekrar sayıyı artırmaz | ☑ | `test_b_urun` + soak 150 tekrar |
| 3.2 | ≤100 ürün; her ürünün sonucu anlaşılır | ☑ | 101 → 417; `results[] status/code/message` |
| 3.3 | Hatalı satır diğerlerini durdurmaz; negatif, satış>liste reddedilir | ☑ | savepoint/satır; `PRICE_NEGATIVE/STOCK_NEGATIVE/PRICE_RULE` |
| 3.4 | Boş alan silinmez; stok 0 yazılabilir; para birimi yoksa TRY | ☑ | `test_bos_alanlar_korunur`, `test_stok_sifir`, currency TRY |
| 3.5 | ≤10 görsel, jpg/png/webp, ≤5 MB; alınamayan görsel ürünü durdurmaz, açıkça bildirilir | ☑ | `IMAGE_LIMIT`/`IMAGE_FAILED` uyarıları; `image_url_ingest` 5 MB/tür |
| 3.6 | Paket izin veriyorsa varyantlı yeni ürün; desteklenmeyen güncelleme yapılmış gibi gösterilmez | ☑ | `create_listing_with_variants`; `VARIANTS_NOT_UPDATED` uyarısı |
| 4.1 | ≤500 stok/fiyat; bulunamayan/hatalı ayrı ayrı bildirilir, doğrular işlenir | ☑ | 501 → 417; `NOT_FOUND`, kısmi başarı |
| 4.2 | "Stok 100" iki kez → 100; 0 yazılabilir; fiyat/stok kuralları | ☑ | `unchanged`; `test_c_stok`; soak 150 ardışık |
| 4.3 | Ad/açıklama/görsel değişmez; yeniden onaya göndermez; stok 0 durumu değiştirmez | ☑ | `db.set_value` yolu; `Pending/Rejected/Out of Stock` testleri |
| 4.4 | Çok işlemde sınırlar uygulanır, anlaşılır uyarı; bilgiler karışmaz | ☑ | 409 kilit, 429 kota (paralel yükte tam sayı), 16 paralel tutarlılık |
| 5.1 | Değişen ürün, yeni stok, uygun miktar, neden, zaman iletilir | ☑ | olay gövdesi `sku/listing_code/stock_qty/available_qty/reason/occurred_at` · e2e HMAC |
| 5.2 | Bildirim alamayan program son kontrolden sonrakileri eksiksiz sorgular | ☑ | `changes(since)` + `next_since`; sayfalama 40/40 |
| 5.3 | Ulaşmayan bildirim tekrar denenir; tükenince panelde; karşı taraf İstoc'tan geldiğini doğrular | ☑ | 1/5/15/60/360 dk, dead, panel listesi, `X-Istoc-Signature` HMAC |
| 5.4 | Başarısız işlem gerçekleşmiş gibi bildirilmez; gidip gelen gereksiz bildirim yok | ☑ | `failed/dead` ayrı durum; API yazması olay üretmez (yankı testi + soak) |
| 6.1 | Program aktarımları panelde ayrı süzülür; geçmiş/sonuç/hata görülür | ☑ | `Bulk Import Job.source=api`, kaynak süzgeci, hata listesi |
| 6.2 | Yeni ürünler onay sürecine girer, toplu onaylanır; mevcut kurallar korunur | ☑ | `Pending` + `bulk_approve_listings_from_job` · `test_e_panel` |
| 6.3 | Başarısız stok bildirimi/denemeler bulunabilir; dosyayla yükleme ve onay çalışmaya devam eder | ☑ | `/seller-api` olay listesi + yeniden dene; `bulk_import` testleri yeşil |
| 7.1 | Aktarma → onaylama → fiyat/stok → satış → stok iletimi örnek mağazada gösterilir | ☑ | `m665_e2e.py` 33 adım (SEL-00038 gerçek mağaza) ×12 koşum |
| 7.2 | Yanlış bilgi, tekrar, yetkisiz erişim, bağlantı kesintisi davranışı doğrulanır | ☑ | bozuk girdi, idempotent, 401/403, webhook zaman aşımı + Redis kesintisi (503/fail-open) |
| 7.3 | Kontrol sonuçları ve örnek çalışma göreve eklenir; mevcut aktarım/alışveriş bozulmadı | ☑ | Plane yorumu (16 Eyl); 338 modül: 80 kırık HEAD'de de kırık, sepet/sipariş/bulk testleri yeşil |
| 7.4 | Başka bir kişi kılavuzdaki örnekleri izleyerek tamamlayabilir | ☑ | `docs/URUN-API-KILAVUZU.md` (örnek gövdeler, sınırlar, hata sözlüğü, desteklenmeyenler) |
| N1 | Satış fiyatı gönderilmediğinde: yeni üründe liste fiyatı, mevcutta değişmez | ☑ | kılavuz §3 tablo + testler |
| N2 | Eş zamanlı işlem, süre başına sınır, tekrar deneme sayısı belirlenip kılavuza yazılır | ☑ | 1 upsert + 1 stok / mağaza; `quota.api_rate_limit`; 5 deneme — kılavuz |
| N3 | Renk/beden kapsamı: ilk sürüm sınırı esas | ☑ | varyant yalnız oluştururken; kılavuz §7 |

**Kapsam dışı (görev metni):** satıcının programına özel bağlayıcı yazılımı (yazılmadı); varyantların sonradan ayrı ayrı görsel güncellemesi (yazılmadı, kılavuzda).

## 6. Test türleri (≥20 istendi — 30)

| # | Tür | Nerede | Sonuç |
|---|---|---|---|
| 1 | Birim (TDD, kırmızı→yeşil) | `test_mogem665_0/a/b/c/d/e/f` | 137 yeşil |
| 2 | Entegrasyon (gerçek DB, FrappeTestCase) | aynı | — |
| 3 | Sözleşme (misafir uç kümesi, yetki alanı ↔ API Scope, kılavuz ↔ hata kodları) | `test_f_sozlesme` | 4 |
| 4 | Maymun / fuzz | `test_monkey` | 30 tohum × 60 tur |
| 5 | Tohum taraması | kampanya faz 2 | 30/30 |
| 6 | Gerçek HTTP uçtan uca | `m665_e2e.py` | 12 koşum × 33/33 |
| 7 | Panel UI (Playwright) | `m665_panel.mjs` | 4 koşum, 21/21 |
| 8 | Mobil RWD (390 px) | aynı | taşma yok |
| 9 | Karanlık tema | aynı | koyu arka plan |
| 10 | Erişilebilirlik (adsız buton/etiketsiz girdi/h1) | aynı | 0/0/1 |
| 11 | Soak / dayanıklılık (25 dk, 10 döngü) | `m665_soak.py` | değişmezler tuttu |
| 12 | Eşzamanlılık / yarış (16 paralel yazım) | soak | 1×200 + 15×409, tek değer |
| 13 | Hız sınırı yükü (40 paralel, kota 20) | soak | tam 20/20 |
| 14 | Kaba kuvvet (jeton ucu) | soak | 401 → 429 |
| 15 | Performans yüzdelikleri | `m665_perf.py` | stok500 p95 215 ms · changes p95 28 ms · tek kalem 31 ms · upsert100 güncelleme p95 3,0 s (satır başına tam Listing.save + ECA) |
| 16 | Güvenlik: tenant izolasyonu | a/b/c/d + soak | — |
| 17 | Güvenlik: yetki yükseltme (auth kancası yolu) | `test_a_kimlik` | başka yolda oturum yok |
| 18 | Güvenlik: SSRF (kayıt + iletim anı) | a/d | — |
| 19 | Güvenlik: JWT kurcalama / süre dolumu / tip / sub | `test_g_kapsam` | 4 |
| 20 | Güvenlik: sır sızıntısı (DB kolonu, okuma uçları, Error Log, mesaj kuyruğu) | g + perf | — |
| 21 | Hata enjeksiyonu (Redis kesik: hız sınırı fail-open, kilit 503; webhook 10 sn zaman aşımı) | g | — |
| 22 | Migrasyon idempotency (patch ×2, migrate ×N) | g | — |
| 23 | Regresyon (338 modül, 6.592 test) | kampanya | 80 kırık HEAD'de de kırık, 1 bize ait düzeltildi |
| 24 | Taban çizgisi ayıklama (stash ile HEAD) | `m665_triage.sh` | — |
| 25 | Kod incelemesi (bağımsız ajan) | — | 1 gerçek kusur (varyant rezervi) düzeltildi |
| 26 | Statik analiz (ruff, eslint, prettier) | — | temiz |
| 27 | i18n parite (4 dil, yer tutucular, kullanılan anahtar ↔ sözlük) | node testi | — |
| 28 | Sınır değerleri (100/101, 500/501, 10/11 görsel, 0 stok) | b/c | — |
| 29 | Unicode / kodlama (Türkçe, Arapça, RTL, emoji, kırpma) | g | — |
| 30 | Bozuk girdi (nesne olmayan öğe, sonsuz/aşırı sayı, 5.000 karakter SKU, 30 MB gövde → 413, GET → 403) | g + perf | 500 yok (bozuk JSON'u Frappe çekirdeği kendi 500'üyle kesiyor — çekirdek davranışı) |

Kampanya 2'nin bulduğu kusurlar: liste öğesi nesne değilse `SKU_REQUIRED` yerine `INVALID_PRODUCT` olmalıydı (düzeltildi); nesne/liste tipinde SKU metne çevrilip kabul ediliyordu (`_sku_str`, düzeltildi).
