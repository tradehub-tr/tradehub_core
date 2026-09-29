# SEO Helper — Mimari (MOGEM-663, 14. bölüm)

> **25 Eyl 2026:** ayrı `seo_helper_cms` app'i `tradehub_core` içine taşındı (`tradehub_core.seo_helper` paketi + `SEO *` modülleri). Aşağıdaki `seo_helper_cms` adları tarihsel; kod yolları `tradehub_core.seo_helper.*`.

Karar (2026-09-15): CMS `frappe/builder` ile birleşir; ajan erişimi ayrı bir MCP (OpenAI) sunucusuyla verilir.
Bu belge 14.1–14.5'in kodda nasıl karşılandığını anlatır; işletme tarafı `OPERASYON.md`'de.

## 14.1 Uygulama ve modüller

| Konu | Karar | Kod |
|---|---|---|
| Uygulama | `tradehub_core` içinde alt paket `tradehub_core/seo_helper/` + modüller `SEO Core/Catalog/CMS/Merchant/Crawler/Helper/MCP` (`modules.txt`); hooks `tradehub_core/hooks.py` sonundaki "SEO Helper" bloğu (mevcut dict'lere EKLENİR); `builder` yumuşak bağımlılık | `tradehub_core/hooks.py`, `tradehub_core/seo_helper/` |
| Modüller | `SEO Core`, `SEO Catalog`, `SEO CMS`, `SEO Merchant`, `SEO Crawler`, `SEO Helper`, `SEO MCP` (görevdeki "Çekirdek, katalog, CMS, Merchant, crawler, helper, mcp"; "Core" adı Frappe'nin kendi Core modülüyle çakıştığı için `SEO` öneki) | `modules.txt`, `seo_core/…` dizinleri |
| TradeHub adaptörleri | tradehub_core'un SEO kabiliyetleri (meta, sitemap, redirect, schema, robots) yalnız `adapters/tradehub/*` üzerinden çağrılır; imza değişirse önce `test_builder_compat.test_tradehub_adaptor_imzalari` kırılır | `adapters/tradehub/{meta,sitemap,redirects,schema,robots}.py` |
| Builder | Ayrı app, `required_apps = ["frappe", "tradehub_core", "builder"]`; **çekirdeğe patch yok** — yalnız hooks (`doc_events`, `update_website_context`), Custom Field'lar ve DocType olayları | `hooks.py`, `setup/install.py` |
| Builder sürümü | v15 uyumlu **v1.34.0**'a pinli (`bench get-app --branch v1.34.0`); test pin'i doğrular, yükseltme akışı 14.6 | `tests/test_builder_compat.py` |

## 14.2 Veri modeli

Çekirdek: `SEO Entity`, `SEO Page`, `SEO Domain`, `SEO Route`, `SEO Policy`, `SEO Profile`.
Yardımcı: `SEO Redirect Rule`, `SEO Locale Cluster`, `SEO Facet Landing Page`.
Operasyon: `SEO Merchant Map`, `SEO Sync Job`, `SEO Crawl Run`, `SEO Audit Finding`, `SEO Helper Rule`, `SEO Helper Settings` (Single).
MCP: `MCP Client` (kimlik, kapsam, mağaza, aylık bütçe, anahtar özeti), `MCP Tool Call` (araç, girdi, çıktı, maliyet, süre, sonuç), `MCP Draft` (onaylanmadan yayına düşmez).

Tümü `scripts/gen_doctypes.py` ile şema-kod olarak üretilir (JSON elle düzenlenmez).

### Builder köprüsü (`cms/bridge.py`)

- `Builder Page` ↔ `SEO Page` **1:1, dil başına** (`builder_page + lang` benzersiz). Kaynak `source=builder`.
- Builder Page üstüne Custom Field'lar: `seo_slug`, `seo_canonical`, `seo_robots`, `seo_locale_cluster`, `seo_lang`, `seo_publish_state` (7.4 durum kümesi: draft/review/approved/scheduled/published/suspended/archived).
- **Canonical girdi/çıktı ayrımı:** Frappe, `update_website_context` kancalarından *sonra* Builder'ın `set_missing_values → set_canonical_url`'ünü koşturur ve `context.canonical_url`'ü Builder Page'in çekirdek `canonical_url` alanından yeniden yazar. Bu yüzden çekirdek alan **politika çıktısının yuvası**dır; kullanıcı girdisi `seo_canonical`'da saklanır. Kullanıcı çekirdek alana yeni bir değer yazarsa (son çıktıdan farklı) köprü bunu girdi sayar ve `seo_canonical`'a taşır. Böylece head'de tek canonical, tek kaynak (politika) — çekirdeğe patch yok.
- Askıya alma/arşiv → Builder `published=0` (db_set) + Builder route cache + Guest HTML cache düşürülür → erişim hemen kesilir (14.5).
- `on_trash` → ayna `archived`, `SEO Route.status=gone`.
- Uzlaşma: `reconcile_pages` (saatlik cron) aynası olmayan/durumu uyuşmayan sayfaları düzeltir (olay kaybı, 14.4).

## 14.3 Çalışma zamanı

### Tek SEO çıktı üreticisi (4.3) — `core/output.py`

Ölçülen sıra (frappe v15 `DocumentPage.get_html`): `init_context` → `update_context` (Builder `get_context`: title/metatags/`_head_html`) → `post_process_context`: MetaTags → **`update_website_context` (biz)** → `set_missing_values` (Builder canonical) → şablon.
Kancamız Builder şablonunun okuduğu `title`, `metatags` (description/og/twitter), `disable_indexing=0` alanlarını **tek elden yeniden belirler**, robots meta'yı + hreflang + WebPage JSON-LD'yi `_head_html`'e ekler. Canonical için yukarıdaki çıktı-yuvası yaklaşımı. Sonuç: head'de tek `<title>`, tek canonical, tek robots, tek description (e2e ile gerçek HTTP'de doğrulandı).

`head_for_route(route, lang)` → `{status: 200|404|410, parts}`; `parts` `data_version` damgalı cache'ten gelir.

### İzin sözleşmeleri (1.4 mağaza izolasyonu) — `core/permissions.py`

| Yüzey | Kural |
|---|---|
| Liste | `permission_query_conditions` → satıcı yalnız kendi `store`'u; `store` boş (platform) kayıtlar yalnız SEO Manager/System Manager |
| Doğrudan kayıt | `has_permission` aynı kural; `MCP Client`/`MCP Tool Call` satıcıya salt okunur |
| API | `require_store_access(store, ptype)`; platform kaydına **yazma** yalnız yönetici |
| Dosya / arka plan işi | `SEO Sync Job.store` işle taşınır; sistem kullanıcısıyla koşan iş `store` dışına yazmaz |
| MCP | `store_scope(client, store)` + `_guard_target` (hedef Builder Page'in **gerçek** mağazası SEO Page aynasından çözülür; taslak o mağazayla damgalanır; onayda yeniden çözülür) |

### Builder olayları → politika motoru

`Builder Page on_update` → ayna → **senkron** `policy.apply_for_page` (head ilk istekte doğru) → cache düşürme → commit sonrası `page.policy` işi (yayılım/uzlaşma). `on_trash` → arşiv. Politika (`core/policy.py`, saf `evaluate`): canonical (host'a sabit), robots (durum/ortam/politika; açık noindex kazanır), deterministik kurallar (11.4: başlık/açıklama uzunluğu, UGC HTML, route) → `SEO Audit Finding`. Güvenilmeyen (tipsiz) girdiye dayanıklıdır (monkey 3000/3000).

### MCP sunucusu — ayrı süreç (`mcp/server.py`)

- `python -m tradehub_core.seo_helper.mcp.server` (stdio; `mcp` SDK 1.x FastMCP / 2.x MCPServer). Frappe içine import edilmez; her aracı `X-MCP-Key` ile `/api/method/tradehub_core.seo_helper.mcp.api.<araç>` uçlarına iletir.
- Araçlar (görev metniyle bire bir): `page_create`, `page_update`, `block_add`, `metadata_suggest`, `translation_draft`, `seo_audit_run`, `result_read`.
- Kimlik: API key (`shc_<prefix>_<secret>`; DB'de yalnız sha256) + rol (`MCP Client.role`, kapsamlar `scopes`) + mağaza. `auth_hooks` yalnız `/api/method/tradehub_core.seo_helper.mcp.api.` yolunda oturum kurar (mağaza sahibi ya da `mcp-agent@…` kullanıcısı); başka yolda anahtar oturum açmaz (e2e #18).
- **Yazma araçları yalnız `MCP Draft` üretir**; Builder Page ancak insan onayıyla (`approve_draft`, Desk/panel oturumu, MCP anahtarıyla çağrılamaz) ve **published=0** olarak yazılır (11.4). Deterministik doğrulamayı geçmeyen taslak onaylanamaz.
- Her çağrı `MCP Tool Call`'a düşer; hata/red yolunda rollback→günlük→commit ile günlük HTTP'de de kalıcıdır.

## 14.4 Arka plan işleri — `core/queue.py`

- `SEO Sync Job` tablosu (Redis'ten bağımsız kalıcı kayıt) + `frappe.enqueue(..., enqueue_after_commit=True)`.
- Kuyruklar: `seo` (kısa), `seo_long` (crawl/pSEO kapasitesi ayrı), `mcp` (MCP uzun işleri ayrı). `common_site_config.workers`'a kayıt: OPERASYON.md.
- Tekrar deneme: 1/5/15/60/360 dk backoff, `job_max_attempts` (Settings) sonra `dead` (hata kuyruğu); `requeue` ile elle.
- Olay kaybı: `dedupe_key` (aynı açık iş yeniden açılmaz), 5 dk'da bir `sweep_due_jobs` (vadesi gelen failed + 10 dk takılı queued), saatlik `reconcile_pages`.
- OpenAI: `mcp/openai_client.py` — zaman aşımı/tekrar/kota Settings'ten; 429 `QuotaExceeded`; maliyet `MCP Tool Call`'a ve `MCP Client.tokens_used_month`'a.

## 14.5 Cache — `core/cache.py`

Anahtar: `shc:{kind}:{domain}:{lang}:{market}:{store}:{ref}`; kind: html/head/schema/sitemap/feed/route/hreflang.
HTML/schema/sitemap/feed aynı `data_version` ile damgalanır (`bump_version` atomik). `invalidate_page` route+head+schema+hreflang(küme)+sitemap **ve** Frappe'nin Guest HTML cache'ini (`website_page`) düşürür; Builder yayın/geri çekme bunu tetikler. Yayından kaldırmada Builder route cache de temizlenir → erişim hemen kesilir.

## 13. Crawl Manager, Monitoring Board, Audit Reporter (MOGEM-662)

| Bölüm | Kod | Özet |
|---|---|---|
| 13.1 Crawl Manager | `crawler/plan.py` (saf: tam/artımlı/örneklem seçimi, bütçe, hız), `crawler/fetcher.py` (HTTP + bs4 ayrıştırma, robots.txt, yönlendirme zinciri, JS render komutu), `crawler/manager.py` (koşum, `seo_long` işi, checkpoint, duraklat/devam et/iptal, host beyaz listesi) | Modlar: `full` (yayında SEO Page + sitemap), `incremental` (değişen / N günden eski taranan / hiç taranmamış), `sample` (deterministik tohum), `targeted` (verilen route'lar). Bütçe: azami sayfa/saniye/bayt. Duraklatma her sayfada okunur (işçi her sayfada commit eder — REPEATABLE READ tuzağı). İşçi kesintisi: saatlik `recover_stale_runs` 30 dk hareketsiz `running` koşumu `paused` yapar (imleç = yazılmış sayfa sayısı) → devam et. SSRF kalkanı: yalnız site hostu + `SEO Domain` hostları; yönlendirmeler **elle** izlenir (`allow_redirects=False`, her adımın hostu istek atılmadan denetlenir, `MAX_REDIRECTS`=5 → döngü `yönlendirme sınırı` hatasıyla biter). Yönlendirilen kaynak URL'de yalnız teknik kurallar koşar (çift başlık vb. hedef sayfada raporlanır). `html_lang` sayfa satırında saklanır (LANG_MISMATCH için). |
| 13.2 Bot logu | `crawler/botlog.py` | nginx combined / werkzeug satırları, 16 bot imzası, isteğe bağlı ters DNS doğrulama, günlük toplulaştırma (`SEO Bot Visit`, set semantiği → yeniden içe aktarma güvenli), istenen (indekslenebilir SEO Page + sitemap) ↔ taranan karşılaştırması, engel (401/403/429/503). Dosya okuma satır satır; `.gz` döndürülmüş loglar `gzip.open`. Doğrulanmış (ters DNS) ve UA taklidi istekler **ayrı satırlarda** (`dedupe_key` doğrulanmış için `|v` eki; doğrulama kapalıyken eski anahtar). İstenen yollar sitemap adaptöründen 1 saat önbellekle (`adapters.tradehub.sitemap.all_urls`, tam üretim ~25 s / 10k URL; `mark_dirty`/`invalidate_all` düşürür). |
| 13.3 Pano | `board.py`, `board_math.py`, `SEO Metric Snapshot` | Kaynaklar: search_console / analytics / crawler / log / merchant — `configured`, `last_at`, `age_minutes`, `stale` (Settings eşiği). Görünürlük boyutları: all / store / lang / page_type. Dönüşümler: RFQ / Seller Inquiry / Order organik oranı. Anomali: yüzde sapma + z-skoru, yalnız "kötü yön" `bad`; tarih yetersizse `insufficient_history`. Günlük anlık görüntü + Error Log uyarısı. |
| 13.4 Denetim | `audit/rules.py` (saf; 5 kategori), `audit/reporter.py` | Bulgu = kod, kategori, önem, mesaj, URL, kanıt (JSON), kök neden, sorumlu rol/mağaza, öneri, parmak izi. Tekilleştirme parmak iziyle (`occurrences`, `first_observed/last_observed` — **`_seen` içeren alan adı kullanılmaz**: Frappe `DatabaseQuery.set_optional_columns` alt dize eşleşmesiyle `first_seen`'i track_seen kapalı DocType'ta SELECT ve FILTER'dan sessizce düşürür; `test_662_wiring` nöbetçi testi var). Aktif bulgu için `active_key` (= parmak izi, DB **UNIQUE**, kapalıyken NULL): iki koşum aynı izi aynı anda yazsa da (ayrı süreç/işlem — e2e-7 ile görüldü, 14/14 çift kayıt) ikinci ekleme `UniqueValidationError` → savepoint geri al → kilitli okuma (`for_update`, REPEATABLE READ anlık görüntüsünü aşar) → güncelleme. Yaşam döngüsü `open → fixed → recrawl_pending → closed / reopened`; `mark_fixed` hedefli yeniden tarama kuyruklar, koşum bitince uzlaşır. `ROBOTS_TXT_UNPARSEABLE` site düzeyi bulgu. |
| 13.5 Search Console | `connectors/search_console.py`, `SEO Connector Quota` | OAuth2 (yetki URL'i, kod takası, refresh token Password alanında), Search Analytics (sayfalama, `dataState=final`), sitemaps list/submit, URL Inspection. Kota defteri günlük; 429 → `QuotaExceeded`; veri gecikmesi (`gsc_data_lag_days`) → eksik günler `missing` (0 sayılmaz); örneklem öncelik: yayında+indekslenebilir, son değişen. |
| 13.6 Ölçüm/deney | `experiments/attribution.py`, `changelog.py`, `experiments.py` | `record_landing` (guest) → **HMAC imzalı** `shc_land` çerezi (HttpOnly) → RFQ/Seller Inquiry/Order `after_insert` Custom Field'lara damga; günlük toplulaştırma (all/page_type/store/lang/route). `SEO Change Log` (otomatik: Builder yayın, politika, yönlendirme; elle). `SEO Experiment`: deney/kontrol route kümeleri, fark-farkı (DiD), mevsimsellik (haftanın günü / yıllık), eksik gün raporu. |

Panel: `/seo/helper` → Pano · Tarama · Bot günlükleri · Denetim · Search Console · Deneyler sekmeleri (`admin-panel/frontend/src/components/seo/*Tab.vue`, API `tradehub_core.seo_helper.api.panel662`, yalnız süper admin).
