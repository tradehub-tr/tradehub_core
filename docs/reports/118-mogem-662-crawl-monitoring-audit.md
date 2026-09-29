# MOGEM-662 · SEO Helper — Crawl Manager, Monitoring Board ve Audit Reporter (13. bölüm)

**Tarih:** 22 Eyl 2026 · **Üst görev:** MOGEM-647 (CMS + SEO Helper CMS) · **Uygulama:** `tradehub_core.seo_helper` (25 Eyl 2026'ya kadar ayrı `seo_helper_cms` app'iydi; kullanıcı isteğiyle tradehub_core içine taşındı — §7) · **Durum:** kodlandı + doğrulandı; 22–24 Eyl ilk tur (13.1–13.6), 25 Eyl taşıma + Plane'deki 24 Eyl metni (§7)

Görev metni Plane'de 13.1–13.6 başlıkları halinde; "T"/"E" etiketleri metinde (T = temel, E = ek). Hepsi kapsam alındı; her madde aşağıda kelimesi kelimesine teslimata çevrildi.

## 1. Görev metni → teslimat (kelimesi kelimesine)

| Madde | Metin | Teslimat | Doğrulama | Durum |
|---|---|---|---|---|
| 13.1 | **SEO Crawl Manager — T**: Tam, artımlı ve örneklem taramaları. | `crawler/manager.py` `CrawlPlan(mode=full\|incremental\|sample)`: tam = tüm indekslenebilir SEO Page + sitemap; artımlı = son başarılı taramadan beri değişen (`data_version`/`modified`) ya da N günden eski taranan; örneklem = deterministik tohumlu n / yüzde | saf `TestPlan` · runtime `test_full/incremental/sample/targeted` · e2e-4 (22 URL hedefli) · e2e-2 soak 120 sayfa | ☑ |
| 13.1 | HTTP/HTML taraması; gerektiğinde JavaScript render. | `crawler/fetcher.py` requests + bs4 ayrıştırma (title/description/canonical/robots/h1/hreflang/iç bağlantı/JSON-LD/alt'sız görsel); `needs_js()` sezgisi (SPA kabuğu) → `JsRenderer` (Settings `crawl_js_render_command`; yoksa sayfa `needs_js` damgalı, içerik denetimi atlanır ve bulgu üretilir) | saf `TestFetcher` (yönlendirme adımı/döngü/dış host/robots) · e2e-4 §1 (zincir, döngü, dış host, SPA `needs_js`, JS render betiğiyle `rendered_with=js`, düşen render komutu) | ☑ |
| 13.1 | Hız sınırları, tarama bütçesi, duraklat/devam et. | `RateLimiter` (host başına rps), bütçe (azami sayfa/saniye/bayt → `budget_exhausted`), `pause(run)`/`resume(run)`/`cancel(run)`: iş her N sayfada checkpoint (`cursor`), `pause_requested` görünce durur, `resume` kaldığı yerden yeniden kuyruklar (`seo_long`) | runtime pause/resume/cancel/budget · e2e-2 gerçek işçiyle duraklat/devam · e2e-4 §6 saniye bütçesi (resume reddi) · hız: 22 sayfa @4 rps ≥ 7,3 s ölçüldü | ☑ |
| 13.2 | **Bot / sunucu log analizi — E**: Gerçek bot ziyaretleri, tarama sıklığı, yanıt kodları ve engeller. | `crawler/botlog.py` nginx combined / Frappe web.log ayrıştırıcı, bot UA sözlüğü (Googlebot, Bingbot, Yandex, DuckDuck, Applebot, GPTBot, …), isteğe bağlı ters-DNS doğrulama, günlük toplulaştırma `SEO Bot Visit` (gün, bot, yol, durum kodu, adet, engel: 403/429/robots) | saf `TestBotlog` · e2e-5 §1–2 (düz + gzip döndürülmüş log, bozuk satır, tz, werkzeug, insan UA, doğrulanmış/taklit ayrı satır, yeniden içe aktarma) · e2e-2 200k satır 8 s | ☑ |
| 13.2 | İstenen sayfalarla fiilen taranan sayfaların karşılaştırılması. | `botlog.coverage(days)`: istenen = indekslenebilir SEO Page + sitemap; taranan = bot ziyaretleri → `requested_not_crawled`, `crawled_not_requested`, sayfa türü/dil/mağaza bazlı sıklık | e2e-5 §3 kapsam (istenen ↔ taranan, engel, bot/sayfa türü/durum dağılımı) · panel `botlog_coverage` 24,7 s → 0,06 s (sitemap önbelleği) | ☑ |
| 13.3 | **SEO Monitoring Board — T**: Search Console, analitik, crawler, log ve Merchant verileri. | `board.py` kaynak kaydı: `search_console` (13.5), `analytics` (13.6 dönüşüm/organik), `crawler` (son koşum), `log` (son içe aktarma), `merchant` (`SEO Merchant Map.last_sync_at`) | e2e-5 §5 kaynak güncelliği (taze/bayat, yapılandırılmamış) · runtime `test_board_sources` | ☑ |
| 13.3 | Mağaza/dil/sayfa türü bazlı görünürlük, dönüşüm ve anomali. | `board.visibility(dimension)` (sayfa/indekslenebilir/yayın/crawl ok/GSC tıklama-gösterim), `board.conversions(dimension)` (organik RFQ/iletişim/sipariş), `board.anomalies()` (7 günlük taban çizgisine göre eşik/z-skoru) — günlük `SEO Metric Snapshot` | saf `TestBoardMath` · e2e-5 §6 (9 günlük sentetik seri: −60 % tıklama kötü, 5xx ×15 kötü, +80 % bot iyi yön anomali değil, sıralama, Error Log) · e2e-3 dönüşümler | ☑ |
| 13.3 | Veri kaynağı ve güncellik göstergeleri. | Her kaynak için `last_at`, `age_minutes`, `stale` (Settings eşiği), `configured` | e2e-5 §5 · runtime `test_board_sources` · panel Pano sekmesi (Playwright) | ☑ |
| 13.4 | **SEO Audit Reporter — T**: Teknik, içerik, katalog, uluslararası ve Merchant denetimleri. | `audit/reporter.py` beş kategori kural seti (teknik: durum/yönlendirme zinciri/canonical/robots/yavaş/needs_js; içerik: ince içerik/h1/alt/başlık-açıklama; katalog: aynasız varlık, çift slug, eksik meta; uluslararası: hreflang karşılık/dil uyuşmazlığı; merchant: eşleme durumu/feed) | saf `TestKurallar` + tipsiz girdi fuzz · e2e-4 §2: 22 URL → 21 beklenen bulgu kümesi birebir (`bulgu haritası`), sağlam sayfa bulgusuz, SPA'da yanlış pozitif yok | ☑ |
| 13.4 | Kanıt, etkilenen URL, önem, kök neden, sorumlu ve öneri. | `SEO Audit Finding` alanları: `category, evidence(JSON), route/url, severity, root_cause, owner_role, owner_store, recommendation` | e2e-4 §2 madde 16: her bulguda kanıt+kök neden+öneri+sorumlu dolu; rapor önem sırası; panel Denetim sekmesi | ☑ |
| 13.4 | Tekilleştirme, düzeltme, yeniden tarama ve kapanış. | `fingerprint` (kod+url+kanıt anahtarı) ile tekilleştirme (`occurrences`, `first_observed/last_observed`); yaşam döngüsü `open → fixed → recrawl_pending → closed / reopened`; `mark_fixed` hedefli yeniden taramayı kuyruklar, yeniden tarama bulguyu doğrulayıp kapatır ya da yeniden açar | runtime `TestAuditYasamDongusu` (+ yarış testi) · e2e-4 §3–5 (occurrences 2, mark_fixed → recrawl → closed; düzelmeyen 404 → reopened) · e2e-7 iki süreç aynı anda → tek aktif bulgu (`active_key` UNIQUE) | ☑ |
| 13.5 | **Search Console bağlayıcısı — E**: Property, OAuth, Search Analytics, sitemap ve URL Inspection. | `connectors/search_console.py`: property (Settings), OAuth2 (yetki URL'i, kod takası, refresh token şifreli), `search_analytics(start,end,dims)`, `sitemaps_list/submit`, `url_inspection(url)` — hepsi `requests`, mock'lanabilir | saf GSC testleri · e2e-6 §A sahte Google (401 yeniden yetki, token 500, 429 üstel bekleme, 5xx tekrar, consent hatası, sayfalama tavanı, Bearer, PUT sitemap) · e2e-2 gerçek `requests` | ☑ |
| 13.5 | Kota, örnekleme ve eksik veri yönetimi. | `SEO Connector Quota` günlük sayaç (URL Inspection 2000/gün, sorgu kotası), kota dolunca `QuotaExceeded`; örnekleme (öncelik: yayında+indekslenebilir+son değişen, deterministik), eksik veri: GSC gecikmesi (2–3 gün) → `missing` günler 0 sayılmaz, kapsama oranı raporlanır | e2e-6 §B (gecikme penceresi → çağrı yok, kota 1/2/3 reddi, gün anahtarı, missing günler seride yok, anomali yanılmaz, örneklem determinizmi, inspection kotası) · yapılandırılmamış uçlar 417 | ☑ |
| 13.6 | **Ölçüm / deney yönetimi — E**: Organik trafiğin RFQ, mağaza iletişimi ve siparişle ilişkisi. | `experiments/attribution.py`: iniş sayfası + yönlendiren + utm (whitelisted `record_landing` ucu → çerez) → `RFQ`/`Seller Inquiry`/`Order` `after_insert` kancasıyla Custom Field'lara yazılır (`seo_landing_path, seo_referrer, seo_utm_*, seo_is_organic`); günlük dönüşüm toplulaştırması | saf imza testleri · e2e-3 gerçek HTTP (misafir iniş → imzalı HttpOnly çerez → RFQ `seo_is_organic=1`, sahte çerez reddi, günlük toplulaştırma → pano) | ☑ |
| 13.6 | Değişiklik kayıtları, kontrol kümeleri ve mevsimsellik. | `SEO Change Log` (otomatik: Builder yayın/politika/yönlendirme; elle), `SEO Experiment` (deney/kontrol sayfa kümeleri, metrik, tarih aralığı) + `evaluate()` (kontrol farkı, haftalık gün eşleme ve yıllık taban ile mevsimsellik düzeltmesi) | e2e-6 §C (örtüşme/boş/ters tarih reddi, politika ve yönlendirme kancaları, DiD 5→10 vs 5→5 = +5 / lift %100, haftalık gün oranı 2,0, evaluated geçişi, HTTP 417/404) | ☑ |
| — | Panel | `/seo/helper` ekranına sekmeler: Tarama · Bot günlükleri · Pano · Denetim (yükseltme) · Search Console · Deneyler | `m662_panel.mjs` 26/26 (masaüstü + mobil, 6 sekme; 4 koşum) | ☑ |

## 2. Mevcut koddan çıkarım
- `seo_helper_cms` (663): `SEO Crawl Run`, `SEO Audit Finding`, `mcp/jobs.run_audit` (politika motoru tabanlı basit denetim), `core/monitoring.health()`, kuyruklar `seo/seo_long/mcp`, `SEO Merchant Map`. Bunlar genişletilir, yeniden yazılmaz.
- tradehub_core: sitemap (`seo.sitemap_generator`), robots (`seo.robots_generator`), `RFQ` / `Seller Inquiry` / `Order` DocType'ları (kaynak/utm alanı YOK → Custom Field). Web analitik yok.
- Ortam: storefront (5173) Vite SPA → HTML taraması kabuk döner (needs_js); Builder sayfaları sunucu tarafında render. `bs4` bench env'inde var, `playwright` yok. **Dev'de `/robots.txt` `{{ robots_txt }}` ham şablon dönüyor** (teknik denetim kuralı bunu yakalamalı).

## 3. Kararlar

| # | Karar | Gerekçe |
|---|---|---|
| K1 | Tarama işçisi her sayfada `commit` eder | MariaDB REPEATABLE READ: işçi commit etmeden web sürecinin yazdığı `pause_requested`'ı göremez (gerçek işçiyle e2e-2'de yakalandı; birim testte görünmez). |
| K2 | Yönlendirmeler elle izlenir (`allow_redirects=False`) | `allow_redirects=True` ile dış/iç ağ adresine giden 302 gövdesiz de olsa **istenirdi**; şimdi her adımın hostu istek atılmadan beyaz listeden geçer, 5 adım sınırı döngüyü keser. |
| K3 | Hedefli tarama yalnız site + `SEO Domain` hostlarına | SSRF; `storefront_base_url` şemasız girilse de host çıkarılır. |
| K4 | Bütçe dolan koşum `done`+`budget_exhausted`, resume edilmez | Bütçe üst sınırdır; devam = artımlı/yeni koşum. Resume yalnız `paused`. |
| K5 | Yönlendirilen kaynak URL'de yalnız teknik kurallar | Aksi hâlde hedef sayfanın başlığı çift sayılır (e2e-4'te `TITLE_DUPLICATE` yanlış pozitifi). |
| K6 | `first_observed/last_observed` (`*_seen` değil) | Frappe `DatabaseQuery.set_optional_columns` alt dize eşleşmesi: `_seen` içeren alan track_seen kapalı DocType'ta SELECT **ve FILTER**'dan sessizce düşer (get_all `[]` döndü). Nöbetçi test: `test_662_wiring.TestFrappeOptionalFieldTuzagi`. |
| K7 | `SEO Audit Finding.active_key` UNIQUE | e2e-7: aynı URL'lere iki süreçte eşzamanlı koşum → 14/14 çift aktif bulgu. Uygulama düzeyi get-then-insert yarışı DB anahtarıyla kapatıldı; ihlalde savepoint geri alınıp kilitli okuma (`for_update`) ile güncellenir. Migrate patch'i mevcut çiftleri kapatır. |
| K8 | Doğrulanmış ve taklit bot istekleri ayrı satır | "Gerçek bot ziyaretleri": aynı gün/yol satırında `verified` bayrağı karışmasın; doğrulama kapalıyken anahtar eski biçim (geriye uyumlu). |
| K9 | Sitemap URL listesi 1 saat önbellek (`expires=True` okuma) | Tam üretim 10k URL için 24,7 s; panel kapsam kartı zaman aşımına düşüyordu. TTL'li anahtarda `get_value(..., expires=True)` şart (666 dersi: aksi hâlde ıska yerel cache'e None yazar). |
| K10 | Atıf çerezi HMAC imzalı, HttpOnly, dolgusuz base64 | İmzasız çerez sahte "organik" damgaya açıktı; `=` dolgusu werkzeug'da `%3D` olup doğrulanmıyordu. |
| K11 | Whitelisted uçlarda tüm argümanlar varsayılanlı + `_req/_int/_list` | Frappe eksik argümanda 500 (TypeError) döner; monkey 400 istekte 500 yok (403/417/200/404). `NotConfigured`/`SearchConsoleError` → 417. |
| K12 | `html_lang` sayfa satırında saklanır | `LANG_MISMATCH` kuralı `html_lang` okuyordu ama ayrıştırıcı üretmiyor, satır saklamıyordu → kural ölüydü (e2e-4'te çıktı). |
| K14 | Saatlik `recover_stale_runs`: işçi ölürse `running` kalan koşum 30 dk sonra `paused` (imleç = yazılmış sayfa) | e2e-9: gerçek işçi SIGKILL ile öldürüldü → koşum sonsuza dek `running` kalırdı; `resume` yalnız `paused` kabul ettiğinden panelden kurtarılamazdı. |
| K15 | `recover_stale_runs` sayaçları (`pages_ok/failed/needs_js/bytes`) sayfa satırlarından yeniden kurar | e2e-9: checkpoint her 20 sayfada bir yazıldığından kesinti sonrası `pages_ok` 26/30 kaldı (imleç doğru, sayaç geride). |
| K13 | `.gz` döndürülmüş loglar okunur | nginx logrotate varsayılanı gzip; aksi hâlde satırlar sessizce atlanırdı. |

## 4. Uygulama günlüğü

1. **Kodlama (11:34–12:30):** DocType üretimi (`scripts/gen_doctypes.py`, 24 DocType), `crawler/{plan,fetcher,botlog,manager}`, `audit/{rules,reporter}`, `board*.py`, `connectors/search_console.py`, `experiments/*`, `api/panel662.py`, hooks/kuyruk/zamanlayıcı, panel 6 sekme, i18n 4 dil, belgeler.
2. **TDD → yeşil güvenme:** saf 38 → 41 test; runtime 24 → 25; wiring 6 (hooks/zamanlayıcı/kuyruk/whitelist/Custom Field/purge/optional_fields/sitemap önbelleği).
3. **Kod incelemesi (ajan, 2 tur):** SSRF (mutlak route) → host beyaz listesi; imzasız çerez → HMAC; `data_days` ters aralık → kırpma + kota yakmama; son URL'de duraklat → done; sınırsız dosya okuma → akış; büyük IN → parça. 2. tur: yüksek güvenli bulgu yok; iki gözlem (zincir ortası hata izi, şemasız storefront URL) uygulandı.
4. **Monkey (3 tohum):** kural fuzz'ında int/float girdi çökmeleri → `_s/_i/_d/_l/normalize`; panel eksik argüman 500 → 417. Son koşum: 400 HTTP istek, 0 kusur.
5. **e2e-1/2/3 (gerçek HTTP, gerçek işçi):** REPEATABLE READ duraklatma körlüğü (K1); kuyruktayken duraklatılan koşumun işçi tarafından çalıştırılması → atla; `run.findings` sayacı; RFQ zorunlu alanları; `record_landing` whitelist; çerez dolgusu.
6. **e2e-4 fixture sunucusu (22 URL, 51 kontrol):** `_reciprocal_missing` JSON metnini dict sanıp **çöküyordu** (tam taramada denetim raporu hiç üretilmezdi); `html_lang` ölü kural (K12); yönlendirilen kaynak çift başlık (K5); `first_seen` Frappe tuzağı (K6); bulgu sayaç anahtarları.
7. **e2e-5 (bot logu + pano, 27 kontrol):** gzip (K13); doğrulanmış/taklit ayrımı (K8); `board_stale_hours=0` varsayılana düşer (belgelendi); eşzamanlı test müdahalesi (Settings `save()`) yanlış alarm — izole koşumda geçti.
8. **Panel zaman aşımı:** `botlog_coverage` 37 s → sitemap önbelleği (K9) → 0,06 s; Playwright 26/26.
9. **e2e-6 (GSC + deney + kurulum, 48 kontrol):** `gsc_submit_sitemap` yapılandırılmamışken 500 → 417; sahte Google tarih penceresi; `after_migrate` iki kez idempotent, kullanıcı ayarı ezilmiyor.
10. **e2e-7 eşzamanlılık:** iki süreç aynı anda → 14/14 çift bulgu → `active_key` UNIQUE + yarış yolu (K7); 3 ardışık koşum 6/6; birim testi `test_yaris_aktif_anahtar_tekil`.
12. **e2e-8 gerçek sitede tam tarama (işçi, 8 rps, bütçe 120):** 10 383 aday, 120 sayfada `max_pages` ile durdu (26 s), artımlı plan taranmışları dışarıda bıraktı, kuyruktayken iptal, zamanlayıcı idempotans, purge < 1 s. Dev'de sitemap URL'leri Frappe hostunda 404 döner (vitrin ayrı port; prod'da aynı host) — bkz. §6.
13. **e2e-9 işçi kesintisi:** SIGKILL → `running` kaldı → `recover_stale_runs` (K14) → `paused` → işçi yeniden → `resume` → 30/30 sayfa, çift satır yok; ilk koşumda `pages_ok` 26 (K15) → düzeltildi.
14. **Son kontrollü tur (24 Eyl):** 8 test modülü + e2e 1–9 + monkey + panel sırayla, tek günlükte (`m662_final.log`). e2e-2'de bir kontrol sabit tarih (22 Eyl) yüzünden düştü → betik tarihi dinamik yapıldı (ürün hatası değil).
11. **Sıfırdan kurulum:** `fresh662.localhost` sitesi: `new-site` 20 s, `install-app tradehub_core` 24 s, `builder` 4 s, `seo_helper_cms` 5 s; 21 DocType SEO modüllerinde (+3 MCP modülünde), `gsc.status`/`board.overview`/`botlog.coverage`/`allowed_hosts` boş sitede hatasız, `migrate` temiz (active_key patch'i idempotent), wiring testleri yeşil; site sonra silindi.

## 5. Test özeti

| Paket | Kapsam | Sonuç |
|---|---|---|
| `tests/test_662_saf.py` | plan/bütçe/hız, fetcher (yönlendirme adımı, döngü, dış host, robots), botlog, pano matematiği, kurallar + tipsiz girdi, GSC istemci, atıf imzası | 41/41 |
| `tests/test_662_runtime.py` | tarama modları, duraklat/devam/iptal, bütçe, SSRF, robots, JS, botlog, denetim yaşam döngüsü + yarış, pano, GSC kota/senkron/inspection, atıf kancası, değişiklik kaydı, deneyler, panel kapısı | 25/25 |
| `tests/test_662_wiring.py` | hooks/zamanlayıcı/kuyruk/whitelist/Custom Field, purge, Frappe `optional_fields` nöbetçisi, sitemap önbelleği | 6/6 |
| Regresyon (663) `test_runtime/test_mcp/test_panel/test_builder_compat/test_policy` | | 25/23/6/9/19 yeşil |
| e2e-1 `m662_e2e.py` | uçtan uca panel API + işçi | 21/21 |
| e2e-2 `m662_e2e2.py` | roller, soak 120 sayfa duraklat/devam, zamanlayıcılar, 200k satır log, sahte Google gerçek `requests` | 31/31 |
| e2e-3 `m662_e2e3.py` | atıf gerçek HTTP | 11/11 |
| e2e-4 `m662_e2e4.py` + `m662_fixture_server.py` | kontrollü HTML/yönlendirme/robots/yavaş/SPA/hreflang, bulgu haritası, yaşam döngüsü, bütçe | 51/51 |
| e2e-5 `m662_e2e5.py` | bot logu (gzip, doğrulama, kapsam, saklama) + pano (güncellik, anomali, daily_job, idempotans) | 27/27 |
| e2e-6 `m662_e2e6.py` | GSC uç durumları, kota/gecikme, deney/değişiklik kaydı, kurulum idempotansı | 48/48 |
| e2e-7 `m662_e2e7.py` | iki süreç eşzamanlı koşum → tekil bulgu | 6/6 (×3) |
| e2e-8 `m662_e2e8.py` | gerçek site tam tarama (işçi, bütçe), artımlı seçim, iptal, zamanlayıcı, purge | 11/11 |
| e2e-9 `m662_e2e9.py` | işçi SIGKILL → stale kurtarma → resume | 8/8 |
| Monkey `m662_monkey.py` | kural fuzz, panel 400 istek, satıcı oturumu 25 uç, record_landing | 0 kusur |
| Playwright `m662_panel.mjs` | 6 sekme, masaüstü + mobil | 26/26 (4 koşum) |
| Sıfırdan kurulum | `fresh662.localhost` | temiz (§4/11) |

Betikler oturum scratchpad'inde (`/tmp/claude-1000/.../scratchpad/m662_*.py|mjs`); kalıcı testler repo içinde. **Commit yok** (kullanıcı kararı; `seo_helper_cms` deposunun uzak deposu da yok).

## 6. Bilinen sınırlar / sonraki adımlar

- Vitrin (tradehubfront) ilk isteğinde `seo_helper_cms.api.landing.record_landing` çağrısı **eklenmedi** (ayrı iş); atıf zinciri sunucu tarafında hazır.
- Dev'de `/robots.txt` ham `{{ robots_txt }}` döndürüyor (tradehub_core www şablonu) → `ROBOTS_TXT_UNPARSEABLE`; prod'da doğrulanmalı.
- Dev'de sitemap URL'leri (`/urun/...`) Frappe hostunda (8000) 404 döner — vitrin ayrı porttadır; prod'da vitrin ve API aynı host/ters vekil arkasında olmalı ya da `SEO Domain.storefront_base_url` ile taranmalı.
- JS render için sunucuda bir render komutu (Playwright/Chromium) kurulmalı; yoksa SPA sayfaları `needs_js` + bulgu.
- `board_stale_hours=0` "her zaman bayat" anlamına gelmez (varsayılan 36'ya düşer); ≥1 kullan.
- `first_seen/last_seen` → `first_observed/last_observed` yeniden adlandırması: prod'da veri yok; eski sütunlar dev DB'de artık olarak kalır (zararsız).

## 7. 25 Eyl 2026 — tradehub_core'a taşıma + Plane'deki güncel görev metni

Plane'deki 662 metni 24 Eyl'de yeniden yazıldı ("Sorun / İş sırası / Kabul kriterleri"). 13.1–13.6 teslimatı üstüne bu metin kelimesi kelimesine yeniden okundu; eksikler tamamlandı. Kod artık **ayrı repo değil**: `tradehub_core/tradehub_core/seo_helper/` (paket) + `seo_core/ seo_catalog/ seo_cms/ seo_merchant/ seo_crawler/ seo_mcp/` (modül dizinleri), hooks `tradehub_core/hooks.py` sonundaki "SEO Helper" bloğu, patch'ler `patches.txt`, belgeler `docs/seo-helper/`. Sitede eski app kaldırıldı (`uninstall-app` + `remove-app`), migrate ile 24 DocType yeniden kuruldu.

| Görev metni (24 Eyl) | Teslimat | Doğrulama |
|---|---|---|
| **1. Koşu kaynağını doğrula** — mevcut ekran/rota + kayıt/API/HTTP yolu | Ekran `/seo/helper` (Tarama · Denetim · Pano · Bot günlükleri · Search Console · Deneyler); kayıtlar `SEO Crawl Run` / `SEO Crawl Page` / `SEO Audit Finding` / `SEO Sync Job`; API `tradehub_core.seo_helper.api.panel662.*` (yalnız süper admin, `_require_admin`) | `test_662_wiring` (whitelist/guest/hook nöbetçisi), e2e-1 |
| **2. İzleme sinyalleri** — ekranları aynı koşu kimliğine bağla | Tarama satırı → **Bulgular (n)** → Denetim sekmesi `crawl_run` süzgeciyle; bulgu detayında koşum ve yeniden tarama koşumu; pano şeridi son koşum kimliği | Playwright `m662_panel3` "koşum → denetim" |
| **2. İzleme sinyalleri** — 404/medya denetimini crawler, log, GSC'den ayrı etiketle | `SEO Audit Finding.signal_source` (crawler/log/gsc/media/notfound_log/policy/mcp); `audit/signals.py`: `SEO 404 Log` → `NOTFOUND_LOG_HIT`, medya `seo_audit.audit_batch` → `MEDIA_<KOD>`, bot engeli → `BOT_BLOCKED`; günlük `daily_import`; panel kaynak rozetleri + süzgeç | `test_662_signals.TestSinyalKaynagi` (4), Playwright kaynak rozetleri/süzgeç |
| **3. Pano ve rapor** — eksik veri/başarısız koşuda kapsam sınırı açık | `board.scope_limits()` → şerit: bağlı olmayan/bayat kaynak, bütçede kesilen/başarısız/tamamlanmamış son tarama, hiç tarama yok; Search Console yoksa hem şerit hem kaynak kartı | `TestPanoKapsamSiniri` (2), Playwright pano (4 dil × 2 cihaz) |
| **3. Pano ve rapor** — rapor için URL, zaman, sinyal kaynağı, tekrar deneme izi | Dışa rapor `audit_export` CSV/JSON: url, first/last_observed, signal_source, crawl_run, recrawl_run, `recrawl_count`, kanıt; `crawl_runs` kuyruk işi izi (`job_status/attempts/last_error/next_attempt_at`), `last_error`, `resumed_from`, kapsam | `TestDisaRaporVeIz` (4), Playwright CSV/JSON indirme |
| **4. Hata ve yetki** — dil, cihaz, rol, hata durumu ekran kanıtı | `docs/reports/118-ekran/` — tr/en/ru/ar × masaüstü/mobil pano+denetim, satıcı rolü (yönlendirme + API 403), hata durumu (dış hosta tarama → 417 mesajı), CSV örneği | `m662_panel3.mjs` |
| **4. Hata ve yetki** — örnek veri/HTTP yanıtı, erişim sınırı, regresyon testi | e2e-1…9 + monkey + tüm modüller yeniden koşturuldu (§8) | §8 |
| **Kapsam dışı** — doğrulama etiketi alanı GSC entegrasyonu sayılmaz | `gsc_status.configured` yalnız client id + property + refresh token üçlüsüyle True; doğrulama meta etiketi hiçbir yerde "bağlı" saymaz | `test_662_runtime`, e2e-6 B14 |
| **Kabul 1** koşu kapsamı/zamanı/hatası/tekrar denemesi panelden izlenir | Tarama sekmesi sütunları Kapsam · Zaman (başlangıç→bitiş · geçen) · Tekrar deneme (iş durumu · deneme) · Son hata | Playwright `crawl-scope/time/retry/error-*` |
| **Kabul 2** bulgu URL+koşuyla ilişkili, tekrarda kayıt çoğalmaz | `url`, `crawl_run`, parmak izi + `active_key` UNIQUE, `occurrences` | `test_404_gunlugu_ayri_etiketle_ve_tekrar_cogaltmaz`, e2e-4/7 |
| **Kabul 3** pano ve dışa rapor yalnız gerçekten ölçülen veri | `missing` anlık görüntüler seride yok; `scope_limits`; export yalnız yazılmış bulgular | e2e-5/6, `TestDisaRaporVeIz` |
| **Kabul 4** Search Console bağı yoksa kaynak eksikliği açık | Kaynak kartı "Ayarlanmadı", şerit "Search Console bağlı değil — bu kaynağın verisi yok", GSC sekmesi "Bağlı değil" | Playwright |

**Taşıma sırasında yakalanan kusur:** `audit_report` üstündeki `@frappe.whitelist` dekoratörü araya giren yardımcı fonksiyona kaydı (yardımcı whitelist'e girdi, asıl uç düştü → panel 403). `test_662_wiring` bunu yakaladı; nöbetçi assert eklendi.

## 8. 25 Eyl doğrulama özeti (taşıma sonrası, tümü `tradehub_core.seo_helper.*` yollarında)

| Paket | Sonuç |
|---|---|
| 663 birim: `test_policy` 19 · `test_runtime` 25 · `test_mcp` 23 · `test_panel` 6 · `test_builder_compat` 9 | yeşil |
| 662 birim: `test_662_saf` 41 · `test_662_runtime` 26 · `test_662_wiring` 6 · `test_662_signals` 11 (yeni) | yeşil |
| e2e-663 `m663_e2e.py` (gerçek HTTP + stdio MCP) | 26/26 |
| e2e-662 1–9 | 21/21 · 31/31 · 11/11 · 51/51 · 27/27 · 48/48 · 6/6 · 11/11 · 8/8 |
| Monkey 663 (3000 politika girdisi, HTTP fuzz) · Monkey 662 | 0 kusur · 0 kusur |
| Playwright 663 `m663_panel.mjs` · 662 `m662_panel.mjs` | 20/20 · 26/26 |
| Playwright kanıt `m662_panel3.mjs` (4 dil × 2 cihaz, satıcı rolü, hata, CSV/JSON, koşum→bulgu) | 43/43 — ekranlar `118-ekran/` |
| Sitede kurulum | eski app kaldırıldı, `bench migrate` temiz, 24 DocType / 7 Module Def / 43 Custom Field / 12 zamanlayıcı işi tradehub_core altında |

Bu turda yakalanan kusurlar: (1) whitelist dekoratörü yardımcı fonksiyona kaydı → uç düştü (nöbetçi test); (2) ru/ar çevirileri 663+662 bloklarında İngilizce kopyaydı → 237×2 anahtar çevrildi; (3) bot günlüğü kapsam ucu sitemap önbelleği boşken 25 s bloklayıp panelde zaman aşımına düşüyordu → `wait=False`: önbellek yoksa arka planda ısıtma + `partial=sitemap_pending` (panelde "kısmi" rozeti — kapsam sınırı açıkça görünür); (4) test hesabı parolaları iki betikte farklıydı → tek parola.

## 9. 25 Eyl gece turu — yeniden okuma, güvenlik ve elle test senaryoları

### 9.1 Yeniden okuma sonucu (663 14.1–14.6 + 662 13.1–13.6 + 24 Eyl metni)
`m66x_dogrulama.py` canlı sitede 54 maddeyi tek tek kontrol eder (DocType/Custom Field/hook/zamanlayıcı/kuyruk/rol/MCP araç seti/API/panel rotası): **54/54**. Eksik çıkan tek şey 24 Eyl metnindeki "trend ekranı" idi → Tarama sekmesine **Koşum trendi** tablosu (`crawl_trend`: tam/artımlı koşumlar, başarı %, bulgu, açık hata, süre; satır → o koşumun bulguları) eklendi.

### 9.2 Güvenlik turu (gerçek HTTP, `m662_guvenlik.py` 43/43 + `m662_guvenlik2.py` 27/27)
| Alan | Kontrol | Sonuç |
|---|---|---|
| Rol/yetki | Misafir, satıcı, SEO Editor: 21 panel ucu + 23 Desk listesi → 403; yalnız SEO Manager/System Manager | geçti |
| IDOR / mağaza izolasyonu | Satıcı başka mağazanın bulgusunu/sayfasını listede göremez, doğrudan kayıtta 403, kendi bulgusunu kapatamaz (yalnız okuma), hiçbir SEO kaydı oluşturamaz, Settings yazamaz | geçti |
| CSRF | Token'sız POST 400/417; yazma ucu GET ile çağrılamaz | geçti |
| MCP kimliği | Yanlış anahtar 401/403; anahtar MCP yolu dışında oturum açmaz; mağaza istemcisi başka mağaza adına denetim/taslak yapamaz; kapatılan ve döndürülen (rotate) anahtar anında geçersiz; anahtar DB'de ve araç günlüğünde düz metin değil | geçti |
| SSRF | 169.254.169.254, 127.0.0.1:8000, file://, localhost:6379, `user@host` hilesi, ftp:// → reddedilir; dış hosta 302'de istek atılmaz | geçti |
| Enjeksiyon | SQL benzeri süzgeçler (`' OR 1=1 --`) 200/417, tablo yerinde; XSS'li sayfa başlığı ham saklanır, JSON'da kaçışlı, panel `{{ }}` ile basar; CRLF girdisi başlık enjekte edemez | geçti |
| Parametre sınırları | rps 0,1–50, sayfa ≤ 100 000, süre ≤ 86 400 s, ≤ 2000 MB (Int taşması ölçüldü: 5000 MB alan sınırını aşıyordu → 417), route ≤ 5000, dışa aktarma ≤ 2000 satır, bozuk limit → varsayılan | **düzeltildi** + geçti |
| OAuth | `state` üretilip **doğrulanmıyordu** (hesap bağlama CSRF'i) → oturuma bağlı, 10 dk, tek kullanımlık state; sahte state kod takası yapmaz | **düzeltildi** + geçti |
| Misafir ucu | `record_landing`: aşırı uzun girdi kesilir, çerez < 2 KB, DB'ye yazmaz, 150 istek seli ort. < 300 ms | geçti |
| Kuyruk | işleyiciler sabit beyaz liste (kullanıcı girdisinden `get_attr` yok) | geçti |
| İndirme | `Content-Disposition: attachment; filename=seo-denetim-<tarih>.csv`; bozuk `fmt` CSV'ye düşer | geçti |
| Zamanlayıcı | 13 SEO Helper işi elle çağrıldı, istisna yok (`m662_zamanlayici.py`) | geçti |

### 9.3 Elle test senaryoları (yazılım bilmeyen biri için)
Ön koşul: `http://localhost:8082` açık, süper admin hesabıyla giriş (`m663-ui@test.local` / `M663-ui-parola!`). Her adımda **"Görmen gereken"** olmuyorsa o madde bozuktur.

| # | Nereye gir / ne tıkla | Görmen gereken | Olmazsa |
|---|---|---|---|
| 1 | Sol menü **Sistem → SEO Yönetimi → SEO Helper** | Üstte 5 kart (Bekleyen taslak, Dead iş, MCP bu ay, Yayında/Sayfa, Aynasız Builder sayfası) ve 9 sekme | Sayfa açılmıyor / sekme eksik → bozuk |
| 2 | **Pano** sekmesi | En üstte sarı ya da yeşil "Pano kapsamı …" şeridi; altında 5 kaynak kartı (Search Console "Ayarlanmadı", Crawler "Bağlı" …) | Şerit yoksa ya da kartlar boşsa → bozuk |
| 3 | Pano'da "Anlık görüntü al" | Sağ üstte "N metrik yazıldı" mesajı | Mesaj yok / hata → bozuk |
| 4 | **Tarama** sekmesi → Mod "Hedefli", route kutusuna `/` yaz → "Taramayı başlat" | "Tarama kuyruğa alındı" mesajı; listede yeni satır önce *queued/running*, 10–20 sn içinde *done*; Kapsam "1 route", Zaman'da süre, Tekrar deneme "done · 1 deneme" | Satır *queued*'da kalıyorsa işçi çalışmıyor → bozuk |
| 5 | Aynı satıra tıkla | Altta "Sayfalar — <id>" tablosu: URL, HTTP kodu, ms, başlık, canonical | Tablo boş → bozuk |
| 6 | Route kutusuna `http://169.254.169.254/` yaz → başlat | Kırmızı mesaj: "Tarama yalnız site hostlarına yapılır … reddedildi" | Tarama başlıyorsa **güvenlik açığı** |
| 7 | Mod "Tam", Azami sayfa `10`, Hız `5` → başlat; bitince Pano'ya dön | Tarama *done* + Bütçe "max_pages"; Pano şeridi "Son tarama … bütçede kesildi: 10/… sayfa" | Şerit bunu yazmıyorsa → bozuk |
| 8 | Tarama listesinde "Bulgular (n)" | Denetim sekmesi açılır, üstte mavi "Koşum: <id>" rozeti, listede yalnız o koşumun bulguları | Rozet yok / liste tümü → bozuk |
| 9 | Denetim'de bir satıra tıkla | Sağ panel: kod, mesaj, etkilenen URL (tıklanabilir), kök neden, sorumlu, öneri, kanıt JSON, "Kaynak: … · Koşum: …" | Alanlardan biri boşsa → bozuk |
| 10 | "Düzelttim → yeniden tara" | Durum *recrawl_pending*, mesajda yeniden tarama kimliği; 10–20 sn sonra Yenile: sorun sürüyorsa *reopened*, geçtiyse *closed* | Durum değişmiyorsa → bozuk |
| 11 | "404 / medya / bot sinyallerini al" | "N sinyal bulgusu işlendi"; üstte renkli rozetler (404 günlüğü, Medya denetimi, Bot günlüğü, Tarayıcı) | Rozet yok → bozuk |
| 12 | Kaynak süzgecinde "Medya denetimi" | Listede yalnız MEDIA_… kodlu, pembe "Medya denetimi" etiketli satırlar | Başka kaynak görünüyor → bozuk |
| 13 | "CSV indir" | Tarayıcı `seo-denetim-<tarih>.csv` indirir; Excel'de sütunlar: signal_source, url, first_observed, last_observed, crawl_run, recrawl_run, recrawl_count … | Dosya inmiyor / sütun eksik → bozuk |
| 14 | Aynı tıklamayı ikinci kez yap, ardından "Yenile" | Aynı bulgular *çoğalmadı*; "Tekrar" sayısı arttı | Satır sayısı iki katına çıktıysa → bozuk |
| 15 | **Bot günlükleri** → kutuya şu satırı yapıştır → "İçe aktar": `66.249.66.1 - - [25/Sep/2026:10:00:00 +0300] "GET /kategori/x HTTP/1.1" 403 0 "-" "Googlebot/2.1"` | "1 satır okundu, 1 kayıt yazıldı"; Kapsam kartında Engel 1; ziyaret listesinde googlebot 403 | Sayılar 0 → bozuk |
| 16 | Aynı satırı tekrar içe aktar | Kayıt sayısı değişmez (çoğalmaz) | İki satır oluşursa → bozuk |
| 17 | **Search Console** sekmesi | "Bağlı değil" ve kota kartları; "Google ile bağlan" düğmesi ayar yoksa uyarı verir | "Bağlı" yazıyorsa (ayar yokken) → bozuk |
| 18 | **Deneyler** → anahtar `deneme-1`, deney route `/a`, kontrol `/b`, tarihler bugün-7 … bugün → "Deney oluştur" → "Değerlendir" | Sonuç kutusunda "insufficient" ya da "ok" + mevsimsellik satırı; değişiklik kayıtlarında "Deney başladı" | Hata / kayıt yok → bozuk |
| 19 | Deney route'una `/a` hem deney hem kontrol yaz | Kırmızı "Aynı route hem deney hem kontrol olamaz" | Kabul ediyorsa → bozuk |
| 20 | Sağ üst dil menüsünden EN / RU / AR seç | Tüm sekme adları, düğmeler, şerit metinleri o dilde; AR'da sayfa sağdan sola | İngilizce kalan metin → çeviri eksik |
| 21 | Tarayıcı penceresini telefon genişliğine daralt (≈ 390 px) | Kartlar alt alta, yatay kaydırma yok, sekmeler kaydırılabilir | Sayfa yatay kayıyorsa → bozuk |
| 22 | Çıkış yap, satıcı hesabıyla gir (`m665-ui@test.local` / aynı parola), adres çubuğuna `/seo/helper` yaz | Ana panoya (dashboard) atılırsın; menüde SEO Helper yok | Sayfa açılıyorsa **güvenlik açığı** |
| 23 | Çıkış yap (misafir), adres çubuğuna `http://localhost:8082/api/method/tradehub_core.seo_helper.api.panel662.audit_report` | `403` / "Not permitted" | Veri dönüyorsa **güvenlik açığı** |
| 24 | Desk: `http://localhost:8001/app/seo-audit-finding` (yönetici) | Bulgu listesi; süzgeçlerde "Sinyal Kaynağı" ve "Yaşam Döngüsü" | Liste açılmıyor → bozuk |
| 25 | Docker'da işçiyi öldür (`docker exec istoc-backend pkill -f "worker --queue seo"`), tarama başlat, 1 dk bekle, işçiyi başlat | Koşum önce *running/queued* kalır; saatlik kurtarma (ya da `recover_stale_runs`) sonrası *paused*; "Devam et" ile biter | Koşum sonsuza dek *running* kalıyorsa → bozuk |

## 10. 25 Eyl akşam turu — görev metni yeniden okundu, her paket taze koştu, yolculuk haritası yazıldı

Kullanıcı isteği: 662/663 metnini kelimesi kelimesine okuyup doğru yapılıp yapılmadığını, güvenlik/rol yetkilerini sınamak; yazılım bilmeyen birine "şu linke tıkla, şu düğmeye bas, şunu göreceksin" diliyle yolculuk haritası + elle test listesi yazmak. Çıktı: claude.ai artifact "SEO Helper Yolculuk Rehberi" (bağlantı Plane yorumunda ve MEMORY'de).

| Paket | Sonuç |
|---|---|
| Birim/entegrasyon 9 modül | 168/168 (+1 yeni nöbetçi: `TestVarYokSizintisi`) |
| Rol matrisi `m662_rol_matrisi.py` (YENİ: whitelisted uçlar modülden otomatik toplanır, 53 uç × misafir/satıcı/SEO Editor/SEO Manager/System Manager = 265 gerçek HTTP) | sızıntı yok; 1 kusur bulundu → düzeltildi |
| Ekran turu Playwright `m662_yolculuk.tmp.mjs` (9 sekme ekran + metin dökümü, koşum→bulgu, CSV, dış host, mobil, satıcı, misafir) | 21/22 (tek "fail" kapalı menü grubunda link arama; ekranda mevcut) |
| Vitrin head | `/mk-f4d8e-3`: 1 title / 1 canonical / 1 robots; yayında olmayan 404 |
| 663 e2e 26/26 · 662 e2e-1 21/21 · e2e-2…8, monkey ×2, güvenlik ×2 | `e2e_zincir_25eyl.log` (scratchpad) — sonuçlar aşağıda güncellenir |

**Düzeltilen kusur (B0):** satıcı `mcp.ops.rotate_key/disable_client` ve `mcp.api.approve_draft/reject_draft`'a var olmayan kayıt adı verince 404 alıyordu (var/yok sızıntısı); `core/permissions.get_doc_or_deny` → yönetici olmayana her koşulda 403.

**Karar bekleyen (B1):** satıcı API'den kendi mağazası için MCP istemcisi açabiliyor (platform/başka mağaza 403). 663 "mağaza izolasyonu 1.4" ile tutarlı; istenmiyorsa 4 uca `_require_admin()`.

**Karar bekleyen (B2):** sunucu kapısı (`ADMIN_ROLES` = System Manager, SEO Manager) ile panel kapısı (`is_admin` = System Manager, Administrator, Marketplace Admin) aynı listeye bakmıyor: yalnız SEO Manager → API var ekran yok; yalnız Marketplace Admin → ekran var her uç 403. Tek yerde hizalanmalı.

**Düzeltilen kusur (B3):** hedef koşumu silinmiş `crawl.run` işi 5 kez tekrar denenip Error Log'a yazıyor ve "Dead iş" sayacını şişiriyordu (kuyrukta 18 örnek). `core/queue.run_job` artık `DoesNotExistError`'ı tek seferde "done · target_missing" olarak kapatır; nöbetçi `TestHedefiSilinmisIs`. Wiring 8/8.

**Tur tuzakları:** rol matrisi argümansız `crawl_start` çağırınca TAM tarama açıyor (2 yönetici × koşum) → kuyruk boğuldu, e2e-2 soak zaman aşımına düştü; betik artık hedefli tek route açıp koşumlarını iptal ediyor. Fixture sunucusu `x1` etiketiyle çalışırken e2e-4/güvenlik `z1` ile çağrıldı → tüm sayfalar 404; etiket sunucuyla aynı olmalı. Chrome MCP eklentisi bağlı değildi → Playwright.
