# MOGEM-663 · SEO Helper — Frappe uygulama ve çalışma zamanı mimarisi (14. bölüm)

**Tarih:** 19 Eyl 2026 · **Üst görev:** MOGEM-647 (CMS + SEO Helper CMS) · **İlgili:** MOGEM-656 §7.7–7.10 (builder + MCP), MOGEM-660 §11.4 (deterministik doğrulama/insan onayı), MOGEM-648 §1.4 (mağaza izolasyonu), MOGEM-653 §4.3 (tek SEO çıktı üreticisi) · **Karar (15 Eyl):** CMS `frappe/builder` ile birleşir, üzerine MCP (OpenAI) sunucusu.

Etiket "E" (14.1–14.6) Plane'de başlık düzeyinde kalmış; bu belge her maddeyi teslimata çevirir. **Durum: tamamı kodlandı, commit YOK** (yeni repo `istoc/seo_helper_cms`, henüz ilk commit atılmadı). Ayrıntı: `seo_helper_cms/docs/MIMARI.md`, `seo_helper_cms/docs/OPERASYON.md`.

## 1. Görev metni → teslimat (kelimesi kelimesine)

| Madde | Metin | Teslimat | Doğrulama | Durum |
|---|---|---|---|---|
| 14.1 | Önerilen uygulama `seo_helper_cms` | Yeni Frappe app, ayrı repo `istoc/seo_helper_cms`; bench'e kurulu (`installed_apps`) | `test_builder_compat`, e2e | ☑ |
| 14.1 | Çekirdek, katalog, CMS, Merchant, crawler, helper ve **mcp** modülleri | `modules.txt`: SEO Core, SEO Catalog, SEO CMS, SEO Merchant, SEO Crawler, SEO Helper, SEO MCP ("Core" Frappe'nin kendi modülüyle çakıştığı için önek) | `test_moduller_ve_doctypelar` | ☑ |
| 14.1 | Mevcut Frappe/TradeHub kabiliyetlerine adaptörler | `adapters/tradehub/{meta,sitemap,redirects,schema,robots}.py` — `tradehub_core.seo` sarılır, kopyalanmaz | `test_tradehub_adaptor_imzalari` | ☑ |
| 14.1 | `builder` bench'e ayrı app; `required_apps`; çekirdeğe patch yok; hooks/Custom Field/DocType olayı | `required_apps=["frappe","tradehub_core","builder"]`; Custom Field'lar `after_migrate`'te idempotent; `doc_events`, `update_website_context`, `auth_hooks`; builder çalışma ağacı temiz | `test_required_apps`, `test_builder_cekirdegine_patch_yok`, `test_hooklar_kayitli` | ☑ |
| 14.1 | Builder v15 uyumlu sürüme pinlenir; yükseltme 14.6 | `builder v1.34.0` (tag), `PINNED_BUILDER` testte, OPERASYON §Builder yükseltme | `test_builder_kurulu_ve_pinli` | ☑ |
| 14.2 | SEO Entity, Page, Domain, Route, Policy, Profile | 6 DocType (SEO Core), `scripts/gen_doctypes.py` ile üretilir | `test_moduller_ve_doctypelar` | ☑ |
| 14.2 | Redirect Rule, Locale Cluster, Facet Landing Page | 3 DocType | aynı | ☑ |
| 14.2 | Merchant Map, Sync Job, Crawl Run, Audit Finding, Helper Rule | 5 DocType (+ `SEO Helper Settings` Single) | aynı | ☑ |
| 14.2 | Builder köprüsü: Builder Page ↔ SEO Page 1:1 dil başına; slug, canonical, robots, hreflang, yayın durumu Custom Field'ları | `cms/bridge.py`; Custom Field: `seo_slug, seo_canonical, seo_robots, seo_locale_cluster (hreflang kümesi), seo_lang, seo_publish_state` | `TestBuilderKoprusu` (6), `test_custom_fieldlar_builder_page_ustunde` | ☑ |
| 14.2 | MCP Client (kimlik, kapsam, mağaza), MCP Tool Call (araç, girdi, çıktı, maliyet, süre, sonuç), MCP Draft (onaylanmadan yayına düşmez) | 3 DocType (SEO MCP) | `TestAraclarYalnizTaslak`, `test_araç günlüğü` (e2e 21) | ☑ |
| 14.3 | DocType olayları, website context ve frontend SEO çıktıları | `doc_events` + `update_website_context` → `core/output.py` (tek üretici) | `TestTekHeadUreticisi` (5), e2e 5–11d | ☑ |
| 14.3 | Liste, doğrudan kayıt, API, dosya ve arka plan işi izinleri | `core/permissions.py`: `permission_query_conditions`/`has_permission` (store), `require_store_access` (platform kaydına yazma yalnız yönetici), iş `store` taşır | `TestIzinler`, `TestMagazaIzolasyonu` (4) | ☑ |
| 14.3 | Builder Page olayları politika motorunu tetikler; head tek üreticiden (4.3) | on_update → ayna → **senkron** politika → cache; on_trash → arşiv; canonical çıktı yuvası (Frappe hook'tan sonra Builder canonical'ı yazar — ölçüldü) | `TestCanonicalCiktiYuvasi` (4), e2e 6–9 tek title/canonical/robots/description | ☑ |
| 14.3 | MCP sunucusu ayrı süreç; araçlar: sayfa oluştur/güncelle, blok ekle, metadata öner, çeviri taslağı, SEO denetimi çalıştır, sonuç oku | `mcp/server.py` (stdio; mcp SDK 1.x/2.x) → `mcp/api.py` whitelisted 7 uç | `test_mcp_sunucu_arac_seti…`, e2e 22–23 (gerçek stdio süreç) | ☑ |
| 14.3 | Kimlik API key + rol; mağaza izolasyonu 1.4; yazma araçları yalnız taslak; yayın insan onayı (11.4) | `mcp/auth.py` (auth_hooks yalnız `mcp.api` yolu; sha256), `_guard_target` hedefin gerçek mağazası, `approve_draft` Desk oturumu + published=0 | `TestKimlik` (6), `TestInsanOnayi` (2), e2e 14–20 | ☑ |
| 14.4 | İşlem tamamlandıktan sonra görev başlatma | `core/queue.enqueue_after_commit` (`SEO Sync Job` + `enqueue_after_commit=True`) | `test_builder_page_kaydi…` | ☑ |
| 14.4 | Tekrar deneme, olay kaybı, hata kuyruğu, uzlaşma | backoff 1/5/15/60/360 dk → `dead`; `dedupe_key`; `sweep_due_jobs` (5 dk); `reconcile_pages` (saatlik); `requeue` | `TestKuyruk` (3), `test_uzlasma…` | ☑ |
| 14.4 | Crawl/pSEO kapasite ayrımı | kuyruklar `seo` / `seo_long` / `mcp`; `common_site_config.workers` | `test_kuyruk_adlari` | ☑ |
| 14.4 | MCP uzun işleri ayrı kuyruk; OpenAI zaman aşımı, tekrar, kota | `seo_audit_run` → `mcp` kuyruğu; `openai_client.complete` timeout/retry(429/5xx/timeout)/aylık token bütçesi → 429 | `test_audit_ayri_kuyrukta`, `test_openai_zaman_asimi_tekrar_deneme`, `test_metadata_suggest_…kota` | ☑ |
| 14.5 | Domain, dil, pazar, mağaza kapsamlı cache | `shc:{kind}:{domain}:{lang}:{market}:{store}:{ref}` | `test_cache_anahtari` | ☑ |
| 14.5 | HTML, schema, sitemap, feed aynı veri sürümü | `data_version` atomik `bump_version`; head cache sürüm uyuşmazsa yeniden üretilir | `test_cache_veri_surumune_yetisir`, `test_politika_uygulamasi_surumu_artirir` | ☑ |
| 14.5 | Yayından kaldırmada erişim hemen kesilir | suspended/archived → Builder `published=0` + Builder route cache + Guest HTML cache temizliği; `head_for_route` 410 | `test_askiya_alma…`, e2e 12–13 (gerçek HTTP 200 dönmüyor) | ☑ |
| 14.5 | Builder yayın/geri çekme route, sitemap, hreflang cache'ini geçersiz kılar | `invalidate_page` (route/head/schema/hreflang kümesi/sitemap + `website_page`) + tradehub sitemap dirty | `TestBuilderKoprusu`, e2e 11d | ☑ |
| 14.6 | Migration, geri doldurma, yedek, geri dönüş | `patches/v0_1/backfill_builder_pages` (idempotent, partili) — sitede koştu (Patch Log); OPERASYON §Yedek/Geri dönüş | `TestGeriDoldurma` | ☑ |
| 14.6 | Kuyruk, veri büyümesi, API kotası, senkron izleme | `core/monitoring.health()` + günlük `daily_health_snapshot` (Settings.last_health_json, Error Log uyarısı); OPERASYON tablo | `test_saglik_ozeti` | ☑ |
| 14.6 | Builder yükseltme planı: pin, Custom Field + hook uyum testi, geri dönüş | `tests/test_builder_compat.py` (9) + OPERASYON §Builder yükseltme (4 adım + geri dönüş) | koştu | ☑ |
| 14.6 | MCP maliyet/kota izleme, araç günlüğü saklama, anahtar rotasyonu | `mcp/ops.py`: `create_client/rotate_key/disable_client/usage/purge_tool_call_log/daily_cost_snapshot/reset_monthly_quotas`; Settings `mcp_log_retention_days`, `mcp_key_rotation_days` | `TestOperasyon` (3) | ☑ |

## 2. Mevcut koddan çıkarım

**Artı (sarıldı):** `tradehub_core.seo.meta_builder.compose_seo_payload`, `seo_html_injector.render_seo_head`, `sitemap_cache` dirty anahtarları, `redirect_resolver`, `schema_builder.build_image_object`, `i18n.build_hreflang_links`, `robots_generator.resolve_env`.
**Eksi:** tradehub_core'da Builder yok; storefront head enjeksiyonu Vite placeholder'ına bağlı — Builder sayfaları için Frappe website context yolu kullanıldı. `SEO Redirect`/`Static Page SEO` tradehub_core'da kalır; `SEO Redirect Rule` üst modeldir (adaptörle senkron).

## 3. Kararlar

- Ayrı repo `seo_helper_cms`; konteynerde `apps/seo_helper_cms` (bench-data volume) — host'tan `scripts/sync_to_bench.sh` ile eşitlenir (bind mount yok; docker-compose'a mount eklenmesi önerilir).
- Builder pin **v1.34.0**. Yükseltme yalnız uyumluluk testi geçince.
- MCP taşıma: stdio (`mcp` SDK; 1.x FastMCP ve 2.x MCPServer) — bench env'ine `mcp` kuruldu (2.x).
- OpenAI: `openai` paketi yok → `requests` ile Responses API; anahtar `site_config.openai_api_key`.
- **Canonical girdi/çıktı ayrımı:** Frappe render sırasında `update_website_context` hook'larından *sonra* Builder `set_canonical_url` koşar (ölçüldü: `base_template_page.post_process_context`). Çekirdeğe patch yerine Builder'ın `canonical_url` alanı politika çıktı yuvası, girdi `seo_canonical`.
- Kuyruk adları `seo/seo_long/mcp` (Frappe `default` ile karışmaz; işçi kapasitesi ayrı).

## 4. Uygulama günlüğü (19 Eyl 2026)

1. İskelet + 18 DocType üreteci + adaptörler + politika/kuyruk/cache/izin/çıktı + köprü + MCP (auth/api/openai/server/ops/jobs) + kurulum.
2. `install-app` "Core" modül çakışmasıyla düştü → modüller `SEO *` önekli; kuruldu, migrate temiz.
3. Birim/entegrasyon testleri (TDD): ilk koşum 8 kırık → `get_all` pozisyonel filtre, test ortamı prod-dışı robots, `frappe.conf` yaması, Settings varsayılanları, `set_meta_tags` (Button, kolon değil) düzeltildi → yeşil.
4. **Yeşile güvenmedik — gerçek HTTP e2e (26 kontrol):** ① Builder canonical'ı hook'u eziyordu (render sırası) → çıktı yuvası tasarımı; ② askıya alınan sayfa Guest HTML cache'inden 200 dönüyordu → `clear_builder_route_cache`; ③ web süreci yeni app'i import etmiyordu (reloader); ④ `mcp` SDK yoktu/2.x API; ⑤ e2e'de REPEATABLE READ tuzağı. Sonuç 26/26.
5. **Kod incelemesi (ajan):** (kritik) yazma araçları hedef sayfanın gerçek mağazasını doğrulamıyordu → `_guard_target` + onayda `_draft_store`; (önemli) politika `effective_*` yazıp sürümü artırmıyordu → `bump_version` + `invalidate_page`. +8 test.
6. **Monkey (politika 3000 rastgele girdi + 400 HTTP fuzz + 25 Builder yaşam döngüsü):** ① motor tipsiz girdide patlıyordu → `_s/_i/_d` zorlama; ② MCP uçları eksik/tipsiz argümanda 500 → argüman zorlama (417 + günlük), `translation_draft` alan listesi beyaz liste (SQL yüzeyi); ③ **HTTP hata yolunda `MCP Tool Call` günlüğü kayboluyordu** (Frappe rollback) → rollback→günlük→commit; ④ bogus `store` link hatasıyla günlük düşüyordu → store doğrulaması; ⑤ işçi ile Builder kaydı arasında deadlock → commit-sonrası iş taze sayfayı atlar. Son koşum: politika 3000/3000, HTTP 312/312 günlük, 25/25 ayna, **0 kusur**.
7. Geri doldurma patch'i (Patch Log'da), `docs/MIMARI.md`, `docs/OPERASYON.md`, bu rapor.

## 5. Test özeti

| Katman | Modül | Adet | Sonuç |
|---|---|---|---|
| Saf birim (Frappe'siz) | `tests/test_policy.py` | 19 | OK |
| Çalışma zamanı | `tests/test_runtime.py` (köprü, canonical yuvası, tek head, kuyruk, cache, izin, ayna, geri doldurma) | 25 | OK |
| MCP | `tests/test_mcp.py` (kimlik, yalnız taslak, mağaza izolasyonu, tipsiz argüman, onay, operasyon) | 23 | OK |
| Builder uyum | `tests/test_builder_compat.py` | 9 | OK |
| E2E (gerçek HTTP + stdio MCP süreci) | scratchpad `m663_e2e.py` | 26 kontrol | 26/26 |
| Monkey | scratchpad `m663_monkey.py` (3 tohum) | 3000 + 400 + 25 | 0 kusur |

Bilinen çerçeve davranışı: bozuk JSON gövde → Frappe 500 (665'te de belgelendi). Yerel ortam notu: `bench worker`/`bench serve` honcho altında eski kodla; ayrı `nohup bench worker --queue seo,seo_long,mcp` başlatıldı (kalıcı değil), web için `touch hooks.py`.

## 6. Panel ekranı — `/seo/helper` (19 Eyl 2026, deneme; geri dönülebilir)

Süper admin (System Manager / SEO Manager; `requiresSuperAdmin`) için admin-panel'de **SEO Yönetimi → SEO Helper**. Satıcı tarafına ekran/uç yok.

| Parça | Dosya | Doğrulama |
|---|---|---|
| Backend liste/özet uçları (yalnız admin rolü; onay/red/anahtar mevcut uçlara delege) | `seo_helper_cms/api/panel.py` | `tests/test_panel.py` 6/6 (satıcı 10 uçtan da atılır) |
| Ekran: 5 özet kartı + 3 sekme (Taslaklar · Sayfalar & Denetim · Kuyruk & MCP), taslak detayı öneri/mevcut + doğrulama, geçmeyen taslakta onay kapalı, onay Builder Page'i **yayınlamaz** | `admin-panel/frontend/src/views/seo/SeoHelperView.vue`, `src/api/seoHelper.js`, rota + menü + 4 dil | Playwright `m663_panel.mjs` 20/20 (masaüstü + 390px mobil, konsol hatası 0) |

Geri dönüş listesi ve snapshot: bellek notu `mogem-663-seo-helper-cms` §Panel. Ekran görüntüleri: `/tmp/m663-panel/0{1..5}-*.png`.
