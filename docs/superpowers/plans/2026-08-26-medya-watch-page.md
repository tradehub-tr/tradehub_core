# Medya Video Watch Page (Dilim 5) — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Her yayındaki ürün videosuna indexlenebilir bir izleme sayfası (`/medya/v/<slug>`) kazandırmak: sunucu tarafı meta + VideoObject/SeekToAction, vitrin oynatıcı sayfası, sitemap girdileri, slug/canonical doldurma.

**Architecture:** Mevcut `/urun` deseninin birebir kardeşi — nginx `location` → `seo/page_resolver.render_media_watch` (dist HTML'e meta/JSON-LD enjeksiyonu) + `api/media_public.get_watch_page` (sayfa verisi, allow_guest) + vitrinde `pages/media-watch.{html,ts}`. Görsel landing'in mevcut `/media/<id>` ucu (`asset_landing`) OLDUĞU GİBİ kalır; desenleri (`_sources`, indexability) yeniden kullanılır.

**Tech Stack:** Frappe v15 (FrappeTestCase), tradehubfront (Vite+Alpine MPA, Vitest), nginx template.

**Spec:** `docs/superpowers/specs/2026-08-26-medya-watch-page-design.md` (W1-W6 kararları bağlayıcı)

## Global Constraints

- **Dal: `ahmet` — YENİ BRANCH AÇILMAZ** (kullanıcı talimatı 2026-08-26). Görev commit'leri doğrudan `ahmet`'e; **push ASLA yapılmaz.**
- Frappe v15; tab indent, line-length 110, type annotation, `frappe.throw(_("..."))`; `th_media_*` yalnız `media/seo.fields_for[_many]` üzerinden okunur; SINGLE beyaz listesi dışına yazım yok.
- Backend testleri: `docker cp` + `docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests --module tradehub_core.tests.<modül>`. Vitrin: `cd tradehubfront && npm test`; build doğrulaması `npm run build`.
- **Arka planda katalog tohumlaması koşuyor** — `media/pipeline_bridge.py` ve `media/migration_runtime.py`'ye DOKUNULMAZ; `media-image-bulk`/`media-maint` kuyruklarına iş atılmaz (backfill Task 1'de `media-maint` yerine senkron-batch bench execute ile, aşağıda).
- URL şeması: `/medya/v/<slug>` (+ `/en/medya/v/<slug>`); slug deseni `[a-z0-9-]+`.
- Index kuralı (W3): posterli + `storefront_visible` ilana bağlı + `seo_index.decide()` olumlu; değilse sayfa 200 + `noindex, nofollow` + sitemap dışı; private → 404.
- Embed videolara sayfa açılmaz (W5): slug üretimi yalnız `/files/` yerel videolar için.

---

### Task 1: Slug + canonical üretimi ve 301 köprüsü

**Files:**
- Create: `tradehub_core/media/watch_slug.py`
- Modify: `tradehub_core/media/video_poster.py` (generate başarı yolunda slug tetikleme — TEK satır çağrı)
- Test: `tradehub_core/tests/test_media_watch.py` (yeni)

**Interfaces:**
- Consumes: `seo/slugify.py::slugify_tr`, `media/seo.fields_for` (`title`, `alt`, `slug`, `poster_url`), `Media URL Redirect` DocType (retro-rename'den; alanlar: source_url, target_url, job_key, expires_at).
- Produces: `ensure_slug(file_url: str) -> str` (boşsa üretir + canonical yazar, doluysa mevcut döner; embed/`/files/` dışı → ""), `change_slug(file_url: str, yeni: str) -> str` (301 köprüsü açar), `watch_url(slug: str) -> str` = `/medya/v/<slug>`, `backfill_slugs(limit: int = 200) -> int` (senkron, bench execute için). Slug çakışmasında `-<içerik_hash6>` eki. Yazım `frappe.db.set_value(..., update_modified=False)` ile `th_media_slug`/`th_media_canonical` (SINGLE'da olduklarından `seo.set_asset_fields` de kullanılabilir — kardeş kayıtlara yazım İÇİN `{"name": ["in", adlar]}` deseni ŞART, video_poster.generate'in çoklu-kayıt dersi).

- [ ] **Step 1: Failing testler** — `test_media_watch.py`: (a) videolu File'da `ensure_slug` başlıktan slug üretir + canonical `/medya/v/<slug>`; (b) aynı başlıklı ikinci videoda `-hash6` eki; (c) `change_slug` sonrası `Media URL Redirect`'te `source_url=/medya/v/<eski>` → `target_url=/medya/v/<yeni>` satırı (`job_key="watch-slug"`); (d) `https://youtu.be/...` (yerel olmayan) → `""` ve alanlara yazım yok; (e) kardeş kayıtlar (aynı file_url iki File) — ikisine de aynı slug yazılır. Fixture: `test_video_poster.py::_yap_video` import edilir.
- [ ] **Step 2: FAIL doğrula** (`run-tests --module tradehub_core.tests.test_media_watch`).
- [ ] **Step 3: `watch_slug.py`'yi yaz** — `slugify_tr(fields.title or fields.alt or file_name_gövdesi)`; boş kalırsa `video-<hash6>`. Çakışma kontrolü: `frappe.db.exists("File", {"th_media_slug": aday, "name": ["not in", kendi_adlar]})`. `backfill_slugs`: posterli, slug'sız, `/files/` videolarını (`VIDEO_UZANTILAR` import) `LIMIT`li çek, `ensure_slug` döngüsü, işlenen sayıyı döndür.
- [ ] **Step 4: video_poster entegrasyonu** — `generate`'in başarı yolunda (tüm kayıtlara yazımdan sonra): `from tradehub_core.media import watch_slug; watch_slug.ensure_slug(file_url)` — hata yutulur (poster ilkesiyle aynı: sayfa kimliği videoyu düşürmez).
- [ ] **Step 5: PASS + regresyon** — `test_media_watch` + `test_video_poster` (8/8) yeşil.
- [ ] **Step 6: Commit** — `git add ... && git commit -m "feat(media): watch page slug/canonical üretimi + 301 köprüsü"`

---

### Task 2: `get_watch_page` ucu + `watch_indexable`

**Files:**
- Modify: `tradehub_core/api/media_public.py`
- Test: `tradehub_core/tests/test_media_watch.py` (ekleme)

**Interfaces:**
- Consumes: Task 1 (`watch_url`), `seo.fields_for`, `seo_index.decide`, `media_public._sources` (mevcut — asset adından kaynak listesi), `media/usage.py::resolve` (kullanım → Listing bağları), `seo_urls.identity_for`.
- Produces: `watch_indexable(file_url: str) -> bool` (W3 üçlüsü); `get_watch_page(slug: str) -> dict` (allow_guest) → `{title, caption, description, transcript, posterUrl, sources: [{src, type}], captionsUrl, durationSec, uploadDate, license: {...}, listings: [{slug, title, image}], indexable, canonical, robots}`. Slug bulunamaz / private → `frappe.throw(..., frappe.DoesNotExistError)` (HTTP 404).

- [ ] **Step 1: Failing testler** — (a) tam alanlı video → sözleşme anahtarları eksiksiz; (b) `storefront_visible=0` ilana bağlı video → `indexable=False`, `robots` noindex; (c) postersüz → `indexable=False`; (d) bilinmeyen slug → `DoesNotExistError`; (e) private dosya → `DoesNotExistError`.
- [ ] **Step 2: FAIL doğrula.**
- [ ] **Step 3: Uygula** — slug → File çözümü `frappe.get_all("File", {"th_media_slug": slug}, ...)` (kardeşlerden ilk public); `listings` usage.resolve'dan `storefront_visible` filtreli, N+1'siz (tek `get_all` ile başlık/slug/primary_image). `sources`: dosyanın asset'i varsa `_sources`, yoksa `[{"src": file_url, "type": mime}]`.
- [ ] **Step 4: PASS + Commit** — `"feat(media): watch page verisi ucu + indexability kararı"`

---

### Task 3: Resolver dalı — `render_media_watch` + JSON-LD/SeekToAction

**Files:**
- Modify: `tradehub_core/seo/page_resolver.py` (`render_media_watch` + `_register_whitelists`'e kayıt)
- Modify: `tradehub_core/seo/schema_builder.py` (`build_video_object`'e `seek_to_action_url_template: str = ""` kwarg'ı — doluysa `potentialAction` ekler)
- Test: `tradehub_core/seo/tests/test_page_resolver.py` desenine ekleme + `test_media_watch.py` JSON-LD testi

**Interfaces:**
- Consumes: Task 2 (`get_watch_page` iç fonksiyonları — HTTP zarfı olmadan aynı veri; ortak yardımcıya çıkar: `media_public._watch_data(slug) -> dict`), `_build_response_html`/`_html_response` (mevcut resolver yardımcıları), `build_video_object`.
- Produces: `render_media_watch(slug: str, lang: str = "tr")` — `pages/media-watch.html` şablonuna meta (`title`, `description`, `og:video`, `og:image` poster, `robots` W3'e göre, `canonical`) + VideoObject(+SeekToAction) JSON-LD enjekte eder; 404 → `_render_404_response()`. SeekToAction: `{"@type": "SeekToAction", "target": {"@type": "EntryPoint", "urlTemplate": f"{site}/medya/v/{slug}?t={{seek_to_second_number}}"}, "startOffset-input": "required name=seek_to_second_number"}`.

- [ ] **Step 1: Failing testler** — (a) `build_video_object(..., seek_to_action_url_template=...)` çıktısında `potentialAction` doğru şekil; boş kwarg'da anahtar yok; (b) resolver: indexable videoda HTML'de canonical + VideoObject; noindex videoda `robots` noindex ve sitemap'lik sinyal yok; bilinmeyen slug 404.
- [ ] **Step 2-4: FAIL → uygula → PASS.** Mevcut `render_listing` gövdesi şablondur — kopya değil, ortak yardımcılar üzerinden.
- [ ] **Step 5: Commit** — `"feat(seo): /medya/v watch page resolver + SeekToAction"`

---

### Task 4: Vitrin — sayfa, rewrite'lar, `?t=`, ürün sayfası linki

**Files:**
- Create: `tradehubfront/pages/media-watch.html`, `tradehubfront/src/pages/media-watch.ts`
- Modify: `tradehubfront/nginx.conf.template` (iki yer: pretty-map + `location ~ ^/medya/v/([a-z0-9-]+)$` → `proxy_pass .../page_resolver.render_media_watch?slug=$1` — `/media/<id>` bloğu satır ~335 desen), `tradehubfront/vite.config.ts::PRETTY` (`/^\/(?:en\/)?medya\/v\/[^/]+/ → /pages/media-watch.html`), ürün galeri video slaydına "sayfasında izle" linki (`ProductVideoSection.ts` — watch slug'ı `get_watch_page` değil, listing detayına eklenecek `videoWatchUrl` alanından; bkz. Interfaces)
- Modify: `tradehub_core/api/listing.py` (`videoWatchUrl`: promo video slug'ı doluysa `/medya/v/<slug>` — `fields_for`'dan `slug`)
- Test: Vitest — `media-watch` veri eşleme + `?t=` başlangıç; `listingService` `videoWatchUrl` eşlemesi

**Interfaces:**
- Consumes: `get_watch_page` (fetch), Task 1 slug.
- Produces: sayfa: oynatıcı (`<video controls poster>` + `<track>`), başlık/caption, açılır transcript (`<details>`), lisans satırı, `listings` kartları; `?t=<sn>` → `video.currentTime`. 404: `get_watch_page` 404 dönerse mevcut 404 sayfasına yönlendirme deseni (`pages/404` kullanımını komşu sayfadan kopyala).

- [ ] Adımlar: failing Vitest → uygula → `npm test` + `npm run lint` + `npm run build` → Commit (tradehubfront) `"feat(media): video izleme sayfası /medya/v"`; backend `videoWatchUrl` ayrı commit (tradehub_core).

---

### Task 5: Sitemap watch girdileri

**Files:**
- Modify: `tradehub_core/seo/sitemap_generator.py`
- Test: `tradehub_core/tests/test_media_video_seo.py` (ekleme)

**Interfaces:**
- Consumes: Task 1-2 (`watch_url`, `watch_indexable`), mevcut `_video_entries_for_listing`/`_preload_video_alanlar` altyapısı.
- Produces: Listing sitemap üretiminde, `watch_indexable` videosu olan her ilan için EK bir `<url>` girdisi: `loc=/medya/v/<slug>`, `lastmod` File.modified, gövdesinde `<video:video>` (mevcut üreticiyle aynı sözlük). Noindex video girmez.

- [ ] Failing test (indexable video → watch `<url>` var; noindex → yok) → uygula → sitemap regresyon modülleri yeşil → Commit `"feat(seo): sitemap'e watch page girdileri"`.

---

### Task 6: Panel + denetim + backfill koşusu + ölçüm

**Files:**
- Modify: `admin-panel/frontend/src/components/media/MediaSeoDrawer.vue` + `useMediaSeo.js` (slug alanı: `set_media_seo` `slug` — SINGLE'da mevcut; kayıtta backend `change_slug` çağrısı için `media_admin.py`'ye ince uç `change_watch_slug(file_url, slug)`), i18n tr+en
- Modify: `tradehub_core/media/seo_audit.py` (`missing_watch_slug`: video + indexable + slug boş → WARN, discoverability)
- Create: `docs/reports/108-watch-page-olcum.md`
- Test: panel node:test; audit testi `test_media_watch.py`'ye

**Adımlar:** failing testler → uygula → `bench execute tradehub_core.media.watch_slug.backfill_slugs` (mevcut videolar) → örnek sayfada HTTP + JSON-LD kanıtı (`curl /medya/v/<slug>` konteyner nginx'i yoksa resolver'ı doğrudan test istemcisiyle) → rapor 108 (kaç video sayfa/index aldı) → Commit'ler (`admin-panel` + `tradehub_core` ayrı).

---

## Self-Review Notları

- Spec kapsaması: §2→T1, §3→T2-3, §4(SeekToAction)→T3, §5→T4, §6→T5, §7→T6; W1-W6 kısıtları Global Constraints'te.
- Tip tutarlılığı: `watch_url`/`ensure_slug`/`watch_indexable` adları görevler arasında sabit; sayfa verisi anahtarları T2'de tanımlı, T4 aynen tüketir.
- Bilinçli sınır: nginx değişikliği canlıda ancak vitrin imaj rebuild'iyle etkinleşir (kalıcılık adımı srcset zincirinin rebuild'ine binmiştir — ayrı rebuild açılmaz).
