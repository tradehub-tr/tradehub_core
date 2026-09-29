# SEO Helper — Operasyon (14.6)

> **25 Eyl 2026:** SEO Helper artık ayrı app değil; `tradehub_core` içinde `tradehub_core.seo_helper` alt paketi ve
> `SEO *` modülleri (`tradehub_core/seo_core`, `seo_cms`, `seo_crawler`, …). Ayrı repo / `bench get-app` / senkron
> betiği YOK. Eski ad `seo_helper_cms` yalnız tarihsel kayıtlarda geçer.

## Kurulum

```bash
cd frappe-bench
bench get-app --branch v1.34.0 https://github.com/frappe/builder      # pin (yumuşak bağımlılık — CMS köprüsü için)
bench --site <site> install-app builder        # tradehub_core zaten kuruluysa
bench --site <site> migrate                    # SEO DocType'ları + patch'ler + after_migrate
```

`tradehub_core.seo_helper.setup.install.after_migrate` (core `after_migrate` listesine eklidir): Module Def'ler,
Builder Page ve RFQ/Seller Inquiry/Order Custom Field'ları (idempotent, `update=True`; Builder yoksa atlanır),
roller (SEO Manager, SEO Editor, MCP Agent), birincil `SEO Domain`, `SEO Policy` "default", Settings varsayılanları
(kullanıcının değiştirdiği değer ezilmez).

**Builder yoksa:** Builder Page olayları hiç tetiklenmez, Custom Field kurulmaz; tarama/log/pano/denetim/GSC
Builder'sız da çalışır (yalnız CMS köprüsü + MCP taslak yayını Builder ister).

**Yerel geliştirme (docker):** `tradehub_core` bind-mount'tur (`/workspace/tradehub_core`); değişiklik anında
görünür, python değişikliğinde `touch apps/frappe/frappe/hooks.py` reloader'ı tetikler, DocType/hook değişikliğinde
`bench --site <site> migrate`. DocType JSON'ları `scripts/seo_gen_doctypes.py` ile üretilir (elle düzenleme).

## Kuyruk işçileri

`sites/common_site_config.json`:

```json
"workers": {
  "seo":      {"timeout": 300,  "background_workers": 1},
  "seo_long": {"timeout": 1800, "background_workers": 1},
  "mcp":      {"timeout": 900,  "background_workers": 1}
}
```

`bench setup procfile` / supervisor yeniden üret. Yerelde: `nohup bench worker --queue seo,seo_long,mcp &` (kalıcı değil).
İzleme: `SEO Sync Job` listesi (status=dead → hata kuyruğu), `core.monitoring.health()`; günlük `daily_health_snapshot` → `SEO Helper Settings.last_health_json` + Error Log uyarısı (takılı iş > 30 dk, dead > 0).

## Migration / geri doldurma / yedek / geri dönüş

- **Geri doldurma:** `patches/v0_1/backfill_builder_pages` (post_model_sync) kurulum öncesi Builder Page'lere ayna açar + politika uygular; idempotent, 200'lük partilerle commit. Yeniden koşturma: `bench --site <site> execute tradehub_core.seo_helper.patches.v0_1.backfill_builder_pages.execute`.
- **Yedek:** standart `bench backup --with-files`; app'in tüm verisi `tabSEO *`, `tabMCP *` tablolarında. Builder Page'e yazılan tek çekirdek alan `canonical_url` (politika çıktısı); girdi `seo_canonical` Custom Field'ında korunur.
- **Geri dönüş (modül):** ayrı app olmadığı için `uninstall-app` yok; SEO DocType'larını kaldırmak = ilgili DocType kayıtlarını silmek (`bench --site <site> execute frappe.delete_doc --args '["DocType","SEO Page",1,1]'` …) ya da git'te taşıma commit'ini geri almak + migrate. Custom Field'lar `Custom Field` listesinden (`module in (SEO CMS, SEO Core)`) silinir; Builder Page'ler dokunulmadan kalır (canonical alanı son politika değeriyle kalır — istenirse `seo_canonical` değerleri uninstall öncesi geri kopyalanır: `frappe.db.sql("update `tabBuilder Page` set canonical_url = seo_canonical where coalesce(seo_canonical,'') != ''")`).
- **Geri dönüş (veri):** ayna satırlarını silmek yeterlidir; `reconcile_pages`/backfill yeniden üretir.

## Kuyruk / veri büyümesi / API kotası / senkron izleme

| Ne | Nerede | Eşik |
|---|---|---|
| Kuyruk derinliği, takılı/dead iş | `core.monitoring.health()["jobs"]`, `SEO Sync Job` | stuck>0 veya dead>0 → Error Log uyarısı |
| Veri büyümesi | `MCP Tool Call` (retention), `SEO Audit Finding` (crawl başına), `SEO Sync Job` (done satırları) | `mcp_log_retention_days` (90) günlük purge; `SEO Sync Job.done` temizliği aylık önerilir |
| API kotası (OpenAI) | `MCP Client.tokens_used_month`, `MCP Tool Call.cost_usd`; `daily_cost_snapshot` | `monthly_token_budget` dolunca 429; aylık `reset_monthly_quotas` |
| Senkron (Builder ↔ SEO Page) | `health()["builder_without_mirror"]`, saatlik `reconcile_pages` | >0 sürekli ise olay kaybı araştır |

## Builder yükseltme planı

1. Yeni sürümü **stage**'de pinle: `git -C apps/builder fetch --tags && git checkout vX.Y.Z`, `bench build --app builder`, `bench migrate`.
2. Uyum testi: `bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_builder_compat` — pin, `required_apps`, Custom Field'lar, köprünün okuduğu Builder alanları (`page_title, route, published, meta_description, canonical_url, disable_indexing, language, meta_image, is_template, is_standard, head_html, draft_blocks, blocks`), Builder şablonunun okuduğu bağlam anahtarları (`title, canonical_url, disable_indexing, _head_html, meta_block.html`), builder çalışma ağacının temiz olması (patch yok).
3. Gerçek HTTP duman testi: bir Builder Page yayınla → head'de tek title/canonical/robots/description (bkz. e2e).
4. Geçerse `PINNED_BUILDER` sabitini ve kurulum notunu güncelle. **Geri dönüş:** `git checkout v1.34.0 && bench build --app builder && bench migrate` (Custom Field'lar ve DocType'lar Builder sürümünden bağımsızdır).

## MCP

- **İstemci açma:** `bench --site <site> execute tradehub_core.seo_helper.mcp.ops.create_client --kwargs '{"client_name": "seo-ajan", "role": "seo_agent", "store": null}'` → anahtar **bir kez** gösterilir (DB'de sha256).
- **Rotasyon:** `ops.rotate_key(client)` — eski anahtar anında geçersiz; `MCP Client.key_rotated_at`; `mcp_key_rotation_days` aşımı günlük snapshot'ta uyarı.
- **Kapatma:** `ops.disable_client(client)`.
- **Maliyet/kota:** `ops.usage(client)`, `daily_cost_snapshot` (aylık USD/token/çağrı), `monthly_token_budget`.
- **Günlük saklama:** `mcp_log_retention_days` (varsayılan 90) → günlük `purge_tool_call_log`.
- **Sunucu:** `SHC_BASE_URL=https://<site> SHC_MCP_KEY=shc_… python -m tradehub_core.seo_helper.mcp.server` (stdio; `SHC_TRANSPORT=streamable-http` de olur). OpenAI anahtarı yalnız `site_config.openai_api_key`.
- **Onay:** taslaklar `MCP Draft` listesinde; SEO Editor/Manager ya da mağaza sahibi `approve_draft`/`reject_draft` (Desk oturumu). Onay Builder Page'i **yayınlamaz** (published=0) — yayın Builder'da ayrı insan adımıdır.

## Testler

```bash
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_policy          # saf, Frappe'siz de: python -m unittest
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_runtime
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_mcp
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_builder_compat
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_662_saf       # 662 saf
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_662_runtime   # 662 entegrasyon
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_662_wiring    # hooks/whitelist nöbetçisi
bench --site <site> run-tests --module tradehub_core.seo_helper.tests.test_662_signals   # sinyal kaynağı / dışa rapor / kapsam
```

Bilinen tuzak: Frappe test koşucusu helpdesk'in `_Test Comm Account 1` Email Account'unu bırakır, sonraki koşumda `Email Domain on_update` düşer → koşumdan önce `_Test%` Email Account'ları sil. Koşum sonrası `bench --site <site> scheduler enable`.

## MOGEM-662 — tarama, log, pano, GSC

- **Sinyal kaynağı (24 Eyl metni §2):** her bulguda `signal_source` — `crawler` / `log` (bot engeli) / `gsc` / `media` (medya SEO denetimi) / `notfound_log` (SEO 404 Log) / `policy` / `mcp`. Var olan 404/medya/bot sinyalleri günlük `audit.signals.daily_import` ile (ya da panel **"404 / medya / bot sinyallerini al"**) rapora alınır; aynı sinyal tekrar edince kayıt çoğalmaz (`occurrences`).
- **Dışa rapor (§3):** `audit_export?fmt=csv|json` (panel: CSV indir / JSON) — her satırda URL, ilk/son görülme, sinyal kaynağı, koşum, yeniden tarama koşumu ve sayısı (`recrawl_count`), kanıt JSON. Yalnız yazılmış bulgular; süzgeçler rapor ekranıyla aynı.
- **Tekrar deneme izi (§1/§3):** `crawl_runs` her koşum için kuyruk işi durumu/deneme sayısı/son hata (`job_*`), koşum `last_error`, `resumed_from`, kapsam (aday/route/mağaza) döner; panel Tarama sekmesinde sütunlar.
- **Pano kapsam sınırı (§3):** `board.scope_limits()` → panelde şerit: bağlı olmayan/bayat kaynak, bütçede kesilen / başarısız / tamamlanmamış son tarama, hiç tarama yok. Search Console bağlı değilse burada ve kaynak kartında açıkça görünür.

- **Tarama işçisi:** `seo_long` kuyruğu (koşumlar `SEO Sync Job` üzerinden). Bütçe varsayılanları Settings §Tarama; büyük sitede `crawl_max_pages`/`crawl_max_seconds` ile sınırlı, artımlı mod günlük (`scheduled_incremental_crawl`, son 24 saatte koşum yoksa). `SEO Crawl Page` satırları 60 günde bir silinir (`purge_old_pages`).
- **JS render:** Settings `crawl_js_render_command` — `{url}` yer tutuculu komut (ör. bir Playwright betiği stdout'a HTML basar). Boşsa SPA sayfaları `needs_js` damgalanır ve `NEEDS_JS_RENDER` bulgusu üretilir; içerik denetimi atlanır (yanlış "başlık yok" bulgusu üretmemek için).
- **SSRF kalkanı:** hedefli taramada mutlak URL yalnız site hostu ve `SEO Domain` hostlarına (`storefront_base_url` dahil) gidebilir; başka host `PermissionError`.
- **Bot logu:** `bot_log_path` glob (ör. `/var/log/nginx/access.log*` — `.gz` döndürülmüş dosyalar da okunur), günlük içe aktarma (satır satır), saklama `bot_log_retention_days`. Ters DNS doğrulaması `bot_verify_dns` (Googlebot/Bingbot resmi yöntemi; yavaş olabilir); açıkken doğrulanmış ve taklit istekler ayrı satırlarda görünür (`verified`). Kapsam (istenen ↔ taranan) sitemap URL listesini 1 saat önbellekler; sitemap yeniden üretilince (`mark_dirty`) düşer.
- **İşçi kesintisi:** işçi ölürse (deploy/OOM) koşum `running` kalır; saatlik `manager.recover_stale_runs` (30 dk hareketsiz) koşumu `paused`'a alır, imleci yazılmış sayfa sayısına eşitler → panelden **Devam et**. Elle: `bench --site <site> execute tradehub_core.seo_helper.crawler.manager.recover_stale_runs --kwargs '{"minutes": 0}'`.
- **Bütçe:** `max_pages/max_seconds/max_mb` dolunca koşum `done` + `budget_exhausted=1` (`budget_reason`); **devam ettirilemez** (resume yalnız `paused`), kalan sayfalar için artımlı/yeni koşum başlatılır. Duraklat/devam et `paused` koşumlara özeldir.
- **Alan adı kuralı:** bulgu/ziyaret tarihleri `first_observed/last_observed` — `*_seen` adı KULLANMA (Frappe `optional_fields` alt dize tuzağı; `test_662_wiring.TestFrappeOptionalFieldTuzagi`).
- **Search Console:** Google Cloud'da OAuth istemcisi → Settings `gsc_client_id/secret`, `gsc_property`; panelden "Google ile bağlan" → geri dönüş `/api/method/tradehub_core.seo_helper.api.panel662.gsc_oauth_callback` (yönetici oturumu). Kota: `gsc_daily_inspection_quota` (2000), `gsc_daily_query_quota`; gecikme `gsc_data_lag_days` (3). Günlük senkron `scheduled_sync` (yapılandırılmışsa, `seo_long`).
- **Pano:** günlük `board.daily_job` (anlık görüntü + dönüşüm toplulaştırma + anomali → Error Log "SEO pano anomali"). Bayat eşiği `board_stale_hours`, anomali eşiği `board_anomaly_pct`, taban `board_baseline_days`.
- **Atıf:** vitrin ilk isteğinde `tradehub_core.seo_helper.api.landing.record_landing` çağrılmalı (path, referrer, utm_*, lang) — çerez sunucuda imzalanır; tradehubfront tarafına küçük bir çağrı gerekir (bu turda eklenmedi, ayrı iş).
- **Bulgu tekilliği:** `SEO Audit Finding.active_key` UNIQUE (aktif bulgu = parmak izi). Migrate patch'i `v0_2.audit_finding_active_key` mevcut çift aktif kayıtları (en yeni kalır) kapatıp anahtarı doldurur; idempotent. Eşzamanlı zamanlanmış artımlı + elle hedefli koşum güvenlidir.
- **Yönlendirme güvenliği:** tarayıcı yönlendirmeleri elle izler; hedef host beyaz listede değilse istek atılmaz (`dış hosta yönlendirme` hatası, 3xx kaydı `REDIRECT_UNRESOLVED` bulgusu). 5 adımdan uzun zincir/döngü `yönlendirme sınırı` ile kesilir.
- **Bilinen dev bulgusu:** yerel `bench serve`'de `/robots.txt` ham `{{ robots_txt }}` döndürüyor → tarama `ROBOTS_TXT_UNPARSEABLE` üretir (fail-open: robots yok sayılır, kayıt düşer).
