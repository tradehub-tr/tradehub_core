# SEO Faz 1 — Manuel E2E Test Rehberi

Lokal Docker dev stack'te doğrulanan adımlar ✓, Beta deploy sonrası yapılacaklar [ ].

## Lokal dev ortamında (tradehub.localhost) doğrulananlar

- ✓ **Pretty URL routing**: `curl http://localhost/marka/<slug>` → 200 + record-spesifik meta'lar
- ✓ **Slug auto-generation**: Yeni Brand kaydı oluştuğunda `brand_name` Türkçe karakterli ise doğru normalize (Çiçek → cicek)
- ✓ **Legacy URL redirect**: `curl /pages/brand.html?brand=<id>` → 301 + Location: /marka/<slug>
- ✓ **Vite placeholder injection**: 75/75 HTML entry'de `<!-- {{__SEO_HEAD__}} -->` placeholder var
- ✓ **Backend test suite**: 92/92 unit test pass (slugify + hooks_seo + meta_builder + og_image + html_injector + page_resolver + cloudflare_purge)
- ✓ **DB schema**: 4 doctype'a 30 yeni Custom Field + Website Settings'e 9 site-wide default
- ✓ **doc_events bağlandı**: before_validate (slug), validate (length warn), on_update (cache invalidate)
- ✓ **Werkzeug Response**: HTML response Frappe whitelist endpoint'ten doğrudan döner (JSON wrap yok)

## Beta deploy sonrası yapılacaklar

### 1. Pretty URL routing (production)

- [ ] `curl -i https://betaistoc.cronbi.com/urun/<gerçek-slug>` → 200 + HTML + meta'lar dolu
- [ ] `curl -i https://betaistoc.cronbi.com/kategori/<gerçek-slug>` → 200
- [ ] `curl -i https://betaistoc.cronbi.com/marka/<gerçek-slug>` → 200
- [ ] `curl -i https://betaistoc.cronbi.com/magaza/<gerçek-slug>` → 200

### 2. Meta tag içerikleri

- [ ] `curl -s https://betaistoc.cronbi.com/urun/<slug> | grep -E '<title>|description|og:image|canonical'` → 6+ satır

### 3. Legacy URL redirect

- [ ] `curl -i -L "https://betaistoc.cronbi.com/pages/product-detail.html?product=<gerçek-ID>"` → 301 + Location → final 200

### 4. noindex sayfalar (storefront setPageMeta)

- [ ] `curl -s https://betaistoc.cronbi.com/cart.html | grep noindex` → setPageMeta entegre edildiyse match
- [ ] `curl -s https://betaistoc.cronbi.com/pages/dashboard/profile.html | grep noindex` → match

### 5. Social media crawler simulation

- [ ] `curl -A "facebookexternalhit/1.1" -s https://betaistoc.cronbi.com/urun/<slug> | grep og:image` → URL dolu
- [ ] `curl -A "Twitterbot" -s https://betaistoc.cronbi.com/urun/<slug> | grep twitter:card` → match

### 6. Validator'lar

- [ ] Facebook Sharing Debugger: https://developers.facebook.com/tools/debug/?q=https://betaistoc.cronbi.com/urun/<slug>
- [ ] Twitter Card Validator: https://cards-dev.twitter.com/validator
- [ ] Google Rich Results Test: https://search.google.com/test/rich-results?url=https://betaistoc.cronbi.com/urun/<slug>
  - Faz 1'de JSON-LD yok, "no structured data" mesajı normaldir
- [ ] WhatsApp link önizleme: gerçek mobil cihazda paylaş, OG image görünür mü

### 7. Cloudflare cache purge

- [ ] Site config'e Cloudflare credential'larını ekle:
  ```bash
  bench --site betaistoc.cronbi.com set-config cloudflare_zone_id "<actual-zone-id>"
  bench --site betaistoc.cronbi.com set-config cloudflare_api_token "<actual-token>"
  ```
- [ ] Admin'den bir Listing'in meta_title'ını değiştir, save et.
- [ ] Cloudflare dashboard → Caching → Purge Logs: ilgili URL listede görünmeli.
- [ ] `curl -I https://betaistoc.cronbi.com/urun/<slug>` → `CF-Cache-Status: MISS` (cache temizlenmiş).

### 8. Storefront dist mount (production-specific)

- [ ] gateway/Frappe docker volume mount: `/storefront/dist:/storefront:ro`
- [ ] `flatpak-spawn --host docker exec istocc-cd-backend-1 ls /storefront/pages/` → product-detail.html var
- [ ] Frappe page_resolver `_storefront_dist_path()` → `/storefront` döndürüyor, template'ler okunabiliyor

### 9. Performance

- [ ] `curl -w "%{time_total}\n" -o /dev/null -s https://betaistoc.cronbi.com/urun/<slug>` → < 0.5 s
- [ ] İkinci request: `< 0.1 s` (Cloudflare HIT)

### 10. Definition of Done final checklist

- ✓ 4 doctype'a SEO custom_field'ları fixture ile eklendi (30 alan)
- ✓ Website Settings genişletildi (9 site-wide default)
- ✓ slugify_tr ve auto-generate hook çalışıyor; Türkçe karakter testleri geçiyor (8 + 7 test)
- ✓ page_resolver 4 URL tipini çözüyor (Werkzeug Response ile HTML)
- ✓ meta_builder payload merge: record override → site default → static fallback (25 test)
- ✓ seo_html_injector placeholder'ı doğru değiştiriyor (15 test)
- ✓ OG image hibrit fallback çalışıyor (manuel öncelikli, otomatik 1200x630 resize) (14 test)
- ✓ Nginx rewrite kuralları aktif (E2E PASS lokal)
- ✓ Legacy URL'ler 301 ile redirect (E2E PASS lokal)
- ✓ Storefront setPageMeta.ts SPA sayfaları için hazır (TS check temiz)
- ✓ Backend testleri yeşil (92/92)
- [ ] Storefront testleri (Vitest setup yok — ayrı bir spec gerek)
- [ ] Beta manuel test checklist tamamlanacak (yukarıdaki 1-9. maddeler)
- [ ] Cloudflare purge entegrasyonu beta config'de aktive edilecek

## Sonraki spec'ler

Faz 1 tamamlandı. Plan §2 yol haritası:
- Faz 2: Sitemap + robots.txt + Canonical
- Faz 3: Structured Data (JSON-LD)
- Faz 4: Admin SEO Editörü (Vue tab)
- Faz 5: SEO Skor + Readability
- Faz 6: Redirect Yönetimi + 404 Takibi (resolve_legacy_url zaten hazır, Faz 6'da admin UI eklenir)
- Faz 7: Hreflang + Multi-language

Her faz ayrı brainstorm → spec → plan → PR.

---

## Faz 2 — Sitemap + robots.txt

### Lokal dev ortamında doğrulananlar

- ✓ Manual rebuild: `tradehub_core.seo.tasks.rebuild_all_sitemaps_now` → 4 doctype + index üretildi
- ✓ Redis cache: 5 key aktif (`tradehub:seo:sitemap:index`, `:Listing`, `:Product Category`, `:Brand`, `:Seller Profile`)
- ✓ `/sitemap.xml` → 200 + XML index, 4 sub-sitemap
- ✓ `/sitemap-products.xml` → 200 + urlset (Listing 200 URL)
- ✓ `/sitemap-categories.xml`, `/sitemap-brands.xml`, `/sitemap-sellers.xml` → 200
- ✓ `/robots.txt` env=beta → "User-agent: *\nDisallow: /"
- ✓ `/robots.txt` env=prod (geçici test) → Allow + 10 Disallow + Sitemap satırı
- ✓ Brand güncellendiğinde Redis'te `sitemap_dirty:<doctype>` key yazılıyor (mark_dirty)
- ✓ Backend testleri: Faz 1 (92) + Faz 2 (45) = 137 unit test pass
- ✓ site_config.seo_environment="beta" lokal'de set edildi

### Beta deploy sonrası yapılacaklar

#### 1. Site config

```bash
# Beta sunucusu
bench --site betaistoc.cronbi.com set-config seo_environment beta
# RC sunucusu
bench --site rcistoc.cronbi.com set-config seo_environment rc
# PROD sunucusu (Jenkins pipeline'da otomatik set edilebilir)
bench --site istoc.cronbi.com set-config seo_environment prod
```

#### 2. Sitemap üretim

- [ ] Beta'da manuel trigger:
  ```bash
  bench --site betaistoc.cronbi.com execute tradehub_core.seo.tasks.rebuild_all_sitemaps_now
  ```
- [ ] `curl -i https://betaistoc.cronbi.com/sitemap.xml` → 200 + XML

#### 3. robots.txt validation

- [ ] Beta: `curl https://betaistoc.cronbi.com/robots.txt` → "Disallow: /"
- [ ] PROD: `curl https://istoc.cronbi.com/robots.txt` → tam ruleset

#### 4. Google Search Console

- [ ] PROD deploy sonrası GSC'ye site doğrula
- [ ] GSC → Sitemaps → submit `https://istoc.cronbi.com/sitemap.xml`

#### 5. Validator'lar

- [ ] xml-sitemaps validator: https://www.xml-sitemaps.com/validate-xml-sitemap.html
- [ ] robots.txt Tester (GSC içinde)

### Definition of Done — Faz 2

- ✓ sitemap_cache.py (15 unit test)
- ✓ sitemap_generator.py (17 unit test)
- ✓ robots_generator.py (13 unit test)
- ✓ invalidate_sitemap_for hook + 4 doctype on_update bağlandı (Redis key kanıtı)
- ✓ daily_sitemap_rebuild cron + scheduler_events.daily bağlandı
- ✓ rebuild_all_sitemaps_now manual endpoint (whitelist + role check)
- ✓ 3 API endpoint (get_sitemap_index, get_sitemap, get_robots)
- ✓ 3 Nginx location bloğu
- ✓ Lokal E2E (curl üzerinden 3 endpoint PASS)
- ✓ site_config.seo_environment set (lokal: beta)
- [ ] Beta deploy + GSC submit (yukarıdaki 5 madde)

---

## Faz 3 — Structured Data (JSON-LD)

### Lokal dev ortamında doğrulananlar

- ✓ schema_builder.py: 5 pure builder + 4 composer (28 unit test pass)
- ✓ Toplam SEO test suite: Faz 1 (92) + Faz 2 (45) + Faz 3 (28) = **165 unit test pass**
- ✓ `/urun/<slug>` response: Product + BreadcrumbList + Organization + Offer JSON-LD script
- ✓ `/marka/<slug>` response: Organization + BreadcrumbList
- ✓ Mevcut `get_review_schema_jsonld()` Product schema review array'ine entegre
- ✓ FAQ schema HTML escape (XSS güvenliği)
- ✓ Currency default TRY, availability InStock

### Beta deploy sonrası yapılacaklar

#### 1. Google Rich Results Test

- [ ] https://search.google.com/test/rich-results?url=https://betaistoc.cronbi.com/urun/<slug>
  - Product schema yeşil işaret (image, offers, brand, aggregateRating)
  - BreadcrumbList yeşil işaret
- [ ] Brand sayfası: Organization + BreadcrumbList yeşil

#### 2. Schema.org Validator

- [ ] https://validator.schema.org/ → URL input → "Run validation"
- [ ] 0 hata, 0 uyarı (info-level normal)

#### 3. PROD sonrası

- [ ] GSC → Enhancements → "Product snippets" raporu (24-48 saat sonra)
- [ ] CTR artışı izleme: GSC Performance → rich result vs normal

### Definition of Done — Faz 3

- ✓ schema_builder.py 5 pure builder + 4 composer
- ✓ meta_builder.py 4 wrapper composer entegre
- ✓ Mevcut Review schema Product içine gömüldü
- ✓ 28 unit test pass (toplam 165)
- ✓ Lokal E2E: 4 doctype response'unda JSON-LD
- [ ] Beta deploy + Google Rich Results validator

---

## Faz 4 — Admin SEO Editörü

### Lokal dev ortamında doğrulananlar

- ✓ Backend `seo_admin.py`: 3 endpoint + 12 unit test pass
- ✓ Toplam SEO test suite: Faz 1+2+3+4 = **177 unit test pass**
- ✓ Frontend build başarılı (admin-panel `npm run build` temiz)
- ✓ Yeni route: `/panel/seo/:doctypeKey/:name` (SeoEditView)
- ✓ Components: SeoTab, SeoFormFields, GoogleSerpPreview, FacebookOgPreview, OgImageUpload, SlugInput, CharCounter (7 SFC)
- ✓ Pinia store: `seoEditor` (load/save/checkSlug/reset, dirty getter)
- ✓ Composables: `useSlugCheck` (500ms debounce), `useFileUpload`
- ✓ API client: `api/seo.js` → `utils/api.js` üzerinden (CSRF + auth merkezi)

### Manuel E2E checklist

URL pattern: `http://localhost/panel/seo/<doctypeKey>/<name>`

- [ ] **Listing SEO test:**
  - Admin panel'i aç, login ol (Marketplace Admin role)
  - `/panel/seo/listing/<gerçek-LST-name>` URL'sine git
  - SeoTab yüklenir, meta_title/meta_description/slug değerleri DB'den gelir
  - Meta Title 71+ karakter yaz → CharCounter kırmızı
  - Slug "test" (mevcut bir slug) yaz → 500ms sonra ✗ + öneri
  - "test-2" suggestion butonuna tıkla → input dolar
  - OG image dropzone'a dosya bırak → upload + 1200x630 preview
  - 6MB dosya bırak → "5MB üstünde" hata
  - Google preview canlı güncellenir (desktop/mobile toggle)
  - Facebook preview canlı güncellenir
  - Kaydet → toast success
  - `curl /urun/<slug>` → yeni meta'lar response'da

- [ ] **Product Category SEO test:**
  - `/panel/seo/product-category/<gerçek-cat-name>`
  - url_slug field değişiklik kaydedildiğinde sitemap dirty flag set olur
  - Sitemap yeniden üretildikten sonra yeni URL XML'de var

- [ ] **Brand SEO test (Faz 4b'den önce manuel):**
  - `/panel/seo/brand/<gerçek-brand-name>`
  - JSON-LD `/marka/<slug>` response'da Brand-as-Organization

- [ ] **Seller Profile SEO test (kendi profili):**
  - Marketplace Seller user ile login
  - `/panel/seo/seller/<kendi-seller-name>` → erişim ✓
  - Başka seller name ile → 403 (tenant izolasyonu)

### Definition of Done — Faz 4

- ✓ Backend 3 endpoint + 12 unit test
- ✓ Frontend 7 komponent + 2 composable + 1 store + 1 API client + 1 constants + 1 view
- ✓ Yeni route: `/panel/seo/:doctypeKey/:name`
- ✓ Build başarılı (npm run build)
- [ ] Manuel E2E checklist tamamlandı (yukarıdaki 4 madde)
- [ ] Beta deploy + admin panel'de gerçek auth ile test

### Plan'dan ayrılan kararlar

| Konu | Karar | Gerekçe |
|---|---|---|
| Edit view inline entegrasyon → **Standalone SeoEditView** | ProductAddView + CategoryManagementView'a inline section yerine ayrı route | Mevcut form save flow'unu bozma riski; standalone route auth + permission daha temiz |
| OG image upload mevcut fetch pattern korundu (CSRF header window.csrf_token) | useFileUpload `fetch` direct kullanıyor, `api.callMethod` yerine | Multipart upload için Frappe upload_file endpoint multipart bekliyor; api.js callMethod JSON-only. Beta test'te CSRF sorunu çıkarsa `api.uploadCertDocument` pattern'ına geçilir |

---

## Faz 5 — SEO Skor + Readability

### Lokal dev ortamında doğrulananlar

- ✓ `turkishTextHelpers.js`: 16 unit test (Node 22 native runner)
- ✓ `seoAnalyzer.js`: 31 unit test (21 check + skor + grade)
- ✓ Toplam frontend test: 47 pass (Node `node --test src/utils/__tests__/`)
- ✓ Toplam backend test: 177 pass (Faz 1-4)
- ✓ **Genel toplam: 224 test pass**
- ✓ 3 Vue komponent: SeoScoreBar, SeoChecklistGroup, SeoCheckItem
- ✓ SeoTab'a SeoScoreBar entegre (form üstünde sticky)
- ✓ Build başarılı (npm run build)

### 21 Check (5 kategori)

**Keyword (5):** title, meta_desc, slug, body, image_alt'ta focus_keyword
**Length (5):** meta_title 50-70, meta_desc 120-160, description ≥300, slug 3-60, focus_keyword set
**Readability (5):** sentence ≤25 kelime, ≥2 paragraf, ≥%30 geçiş, <%20 pasif, ardışık başlangıç yok
**Structure (3):** heading hierarchy, image alt %80+, internal link ≥1
**Technical (3):** slug ASCII, og_image set, noindex off

### Manuel E2E checklist

- [ ] Admin panel'i aç: `http://localhost/panel/seo/listing/<LST-name>`
- [ ] SeoScoreBar form'un üstünde görünür (0/100 başlar — focus_keyword boş)
- [ ] focus_keyword yazınca skor anlık güncellenir
- [ ] meta_title 71+ karakter → keyword/length kategorilerinde WARN
- [ ] "▼ Detaylar" tıkla → 5 kategori grup açılır
- [ ] Her check için icon (✓⚠✗−) + label + message + öneri görünür
- [ ] Türkçe karakterli içerikte cümle/kelime sayım doğru çalışıyor
- [ ] Pasif cümle ("yapıldı", "eklendi") tespit ediliyor

### Definition of Done — Faz 5

- ✓ turkishTextHelpers.js + 16 test
- ✓ seoAnalyzer.js (21 check) + 31 test
- ✓ 3 Vue komponent (SeoScoreBar/Group/Item)
- ✓ SeoTab entegrasyonu
- ✓ Build temiz
- [ ] Manuel E2E admin paneli ile test

---

## Faz 6 — Redirect Yönetimi + 404 Takibi

### Lokal dev ortamında doğrulananlar

- ✓ `redirect_resolver.py`: 16 unit test (find_matching_redirect + follow_chain + loop detection)
- ✓ `redirect_cache.py`: 4 unit test (Redis cache + invalidate)
- ✓ 2 yeni doctype: `SEO Redirect` + `SEO 404 Log` (migrate, DB'de aktif)
- ✓ 4 yeni endpoint: `list_redirects`, `list_404s`, `add_redirect_from_404`, `handle_404_endpoint`
- ✓ hooks.py: SEO Redirect on_update + on_trash → cache invalidate
- ✓ 2 admin view: `SeoRedirectListView` + `Seo404ReportView`
- ✓ 1 form: `RedirectForm.vue`
- ✓ Pinia store: `seoRedirects` (setup deseni)
- ✓ Router: 2 yeni route (/panel/seo/redirects, /panel/seo/404s)
- ✓ Build başarılı
- ✓ **Toplam backend test: 197 pass**

### Beta deploy sonrası — Nginx error_page entegrasyonu

Lokal dev'de Nginx error_page çalışmıyor (Vite HMR catch-all yapıyor). Production Nginx config'ine eklenecek:

```nginx
# istoc.com server bloğu sonu
error_page 404 = @seo_redirect_fallback;

location @seo_redirect_fallback {
    rewrite ^ /api/method/tradehub_core.api.seo_admin.handle_404_endpoint?path=$request_uri last;
}
```

### Manuel E2E checklist

- [ ] `/panel/seo/redirects` → boş liste + "+ Yeni Redirect" çalışıyor
- [ ] source `/eski-test`, target `/urun/test` → Kaydet
- [ ] Edit, toggle, sil çalışıyor
- [ ] Frappe console: `handle_404("/eski-test")` → 301 + Location
- [ ] Frappe console: `log_404("/olmayan", ...)` → SEO 404 Log'da kayıt
- [ ] `/panel/seo/404s` → "/olmayan" listede, "+ Redirect" tek tıkla çözer

### Definition of Done — Faz 6

- ✓ redirect_resolver.py + 16 test
- ✓ redirect_cache.py + 4 test
- ✓ 2 doctype DB'de aktif
- ✓ 4 backend endpoint + hooks bağlandı
- ✓ Pinia store + 2 view + 1 form
- ✓ Router 2 route
- ✓ 197 backend test pass (Faz 1-6 toplam)
- [ ] Beta deploy + Nginx error_page config
- [ ] Manuel E2E admin paneli

---

## Faz 7 — Hreflang + Multi-language (TR/EN)

### Lokal dev ortamında doğrulananlar

- ✓ `i18n.py`: 34 unit test (parse_lang, get_field_with_fallback, localize_url, build_hreflang_links, slug_field_for)
- ✓ **Toplam backend test: 231 pass** (Faz 1-6: 197 + Faz 7: 34)
- ✓ 20 yeni `_en` custom_field DB'de aktif (4 doctype × 5 alan)
- ✓ meta_builder lang param + EN fallback + canonical `/en/` prefix
- ✓ schema_builder JSON-LD `inLanguage`
- ✓ page_resolver render_*(slug, lang)
- ✓ sitemap_generator xhtml:link namespace + 3 alternate her URL'de
- ✓ seo_head.html `<link rel="alternate" hreflang>` Jinja loop
- ✓ Nginx 4 yeni `/en/` location (urun/kategori/marka/magaza)
- ✓ api/seo_admin SEO_FIELDS_BY_DOCTYPE _en dahil
- ✓ LangToggle.vue + SeoFormFields lang-aware (TR/EN toggle, field key)
- ✓ seoEditor store currentLang state
- ✓ Build temiz

### Lokal E2E (curl ile doğrulandı)

```bash
$ curl http://localhost/marka/demo-brand-akdenizmut | grep hreflang
<link rel="alternate" hreflang="tr" href=".../marka/demo-brand-akdenizmut">
<link rel="alternate" hreflang="en" href=".../en/marka/demo-brand-akdenizmut">
<link rel="alternate" hreflang="x-default" href=".../marka/demo-brand-akdenizmut">

$ curl http://localhost/en/marka/demo-brand-akdenizmut | grep canonical
<link rel="canonical" href="http://tradehub.localhost/en/marka/demo-brand-akdenizmut">

$ curl http://localhost/sitemap-brands.xml | grep xhtml:link
<xhtml:link rel="alternate" hreflang="tr"  href="..."/>
<xhtml:link rel="alternate" hreflang="en"  href="..."/>
<xhtml:link rel="alternate" hreflang="x-default" href="..."/>
```

### Beta deploy sonrası

- [ ] Google Search Console "International targeting" raporu (hreflang validation)
- [ ] EN content seeding — admin meta_title_en/meta_description_en alanlarını manuel doldurur
- [ ] DNS değişikliği gerek değil (path prefix kullandık)

### Definition of Done — Faz 7

- ✓ i18n.py + 34 test
- ✓ 20 _en custom_field
- ✓ meta/schema/sitemap/page_resolver lang param
- ✓ seo_head.html + Nginx 4 /en/ location
- ✓ api SEO_FIELDS _en dahil
- ✓ LangToggle + SeoFormFields lang-aware
- ✓ 231 backend test (Faz 1-7 toplam)
- [ ] Beta deploy + GSC hreflang validation
- [ ] Admin panel manuel test

---

## Faz 4b — Brand & Admin Seller Profile SEO Entegrasyonu

### Backend doğrulama

- [ ] `bench migrate` çalıştı, yeni Custom Field'lar oluştu:
  - Admin Seller Profile: seo_tab, seo_section, slug, meta_title, meta_description, noindex, og_image, og_title_override, og_description_override, canonical_url_override, robots_directive_override, slug_en, meta_title_en, meta_description_en, og_title_override_en, og_description_override_en
- [ ] Seller Profile Custom Field'ları temizlendi (`frappe.db.count("Custom Field", {"dt": "Seller Profile"}) == 0`)
- [ ] SEO modülünde "Seller Profile" string referansları yok (sadece eski plan/spec dokümanlarında historical)
- [ ] SEO module testleri yeşil — page_resolver, sitemap_generator, hooks_seo, i18n, seo_admin

### Veri taşıma (Seller Profile → Admin Seller Profile)

- [ ] 11 paralel kayıtta SEO field'ları kopyalandı (sadece 1 tanesinin slug'ı doluydu: `ahmet.seker@turksab.com` → `turksab`)
- [ ] `SELECT name, slug FROM \`tabAdmin Seller Profile\` WHERE slug = 'turksab'` 1 satır döndürüyor

### Admin panel — DocTypeFormView SEO tab'ı

- [ ] `/panel/app/brand/<name>` → tab listesinde "SEO" görünür → tıklanır → SeoTab yüklenir → slug/meta_title/meta_description alanları boş durumdan doldurulabilir
- [ ] Kaydet → toast "SEO kaydedildi" → storefront `/marka/<slug>` yeni meta_title gösterir
- [ ] LangToggle EN seçilir → meta_title_en alanı doldurulur → Kaydet → `/en/marka/<slug>` EN meta_title gösterir
- [ ] `/panel/app/admin-seller-profile/<name>` aynı flow `/magaza/<slug>` ve `/en/magaza/<slug>` üzerinde

### Storefront doğrulama

- [ ] `/magaza/turksab` → `<title>` ve `<meta name="description">` Admin Seller Profile meta alanlarından üretilir (önce Seller Profile'dan üretiliyordu)
- [ ] `/sitemap-sellers.xml` Admin Seller Profile kayıtlarını döndürür (filename slug stabil: "sellers")
- [ ] `<xhtml:link>` hreflang TR + EN per URL korunuyor (Faz 7 entegrasyonu)

### Definition of Done — Faz 4b

- ✓ Custom Field fixture Seller Profile (16) → Admin Seller Profile (16) taşındı
- ✓ page_resolver / hooks_seo / sitemap_generator / i18n / schema_builder / seo_admin doctype referansları güncellendi
- ✓ hooks.py doc_events SEO hook'ları Admin Seller Profile bloğuna konsolide edildi
- ✓ tab-extensions.js Brand + Admin Seller Profile için SeoTab inject ediyor
- ✓ seoDoctypeConfig + SeoEditView "Admin Seller Profile" mapping
- ✓ test_seo_admin.py "test_brand_seo_fields_complete" yeni testi geçer
- ✓ Tüm SEO modülü testleri (231+) yeşil
- [ ] Beta deploy + admin panel'de gerçek satıcı SEO düzenlemesi denenmiş

---

## Faz 4c — Statik Sayfa SEO Yönetimi

### Backend doğrulama

- [ ] `bench migrate` sonrası `tabStatic Page SEO` tablosu mevcut
- [ ] `seed_static_pages.run` 70 kayıt oluşturdu (~36 indexable + ~34 hidden)
- [ ] `STATIC_PAGES` registry'de 70 entry
- [ ] Tüm registry/sitemap/page_resolver test'leri yeşil (9 yeni registry testi dahil)

### Admin panel

- [ ] `/panel/seo` → "Statik Sayfalar" tab → 70 sayfa listeli
- [ ] Filtre: "Noindex işaretli" → ~34 hidden sayfa (dashboard, checkout, auth) görünür
- [ ] Arama: "kvkk" → KVKK satırı bulunur
- [ ] "SEO Düzenle" → `/panel/seo/static/%2Fkvkk` → SeoTab açılır
- [ ] meta_title + meta_description düzenle → Kaydet → DB persist (Static Page SEO doc güncellenir)
- [ ] noindex toggle → kaydet → sitemap'ten girer/çıkar

### Storefront (production gateway tamamlanınca)

- [ ] `GET /yardim-merkezi` (prod) → backend page_resolver → `<title>` admin meta'sı
- [ ] `/sitemap-static-pages.xml` ~36 indexable URL içerir
- [ ] Sitemap index `/sitemap.xml` 5 sub-sitemap içerir (urunler, kategoriler, markalar, mağazalar, static-pages)

### Definition of Done — Faz 4c

- ✓ Static Page SEO doctype + 70 seed record
- ✓ STATIC_PAGES_REGISTRY 70 entry
- ✓ render_static_page endpoint + meta_builder.build_for_static_page
- ✓ Sitemap entegrasyonu (DOCTYPE_CONFIG, _fetch_records_for, build_for_type)
- ✓ seo_admin.list_static_pages endpoint + SEO_FIELDS_BY_DOCTYPE["Static Page SEO"]
- ✓ hooks.py doc_events + hooks_seo.py path-empty handling
- ✓ Admin panel "Statik Sayfalar" tab + SeoStaticPageEditView + route
- ✓ Backend test suite yeşil
- [ ] Production Nginx gateway config (manuel deploy task — kritik 30 indexable path için location bloku)

---

## BE-ROB — Robots temeli + noindex guard manuel doğrulama (2026-07)

### Ortam eşlemesi (eşleme-önce, restore-proof)

- [ ] `docker exec istocc-cd-backend-1 bench --site istoc.cronbi.com console` →
      `from tradehub_core.seo.robots_generator import resolve_env; resolve_env()` → `"prod"`
- [ ] Aynı komut rcistoc/betaistoc sitelerinde → `"rc"` / `"beta"`
- [ ] Restore senaryosu: rc'ye prod DB restore + site_config'te `seo_environment: prod` artığı →
      `resolve_env()` YİNE `"rc"` (eşleme kazanır)

### Backend /robots.txt override (www/robots.txt.py — koşulsuz block-all)

- [ ] `curl https://istoc.cronbi.com/robots.txt` → `User-agent: *` + `Disallow: /` (başka satır yok)
- [ ] `curl https://rcistoc.cronbi.com/robots.txt` ve betaistoc → aynı block-all
- [ ] Website Settings.robots_txt DOLU olsa bile block-all döner (override okumaz)
- [ ] GATE-A (env-aware içerik AYRI route'ta):
      `curl https://istoc.cronbi.com/api/method/tradehub_core.api.seo.get_robots` →
      `Allow: /` + `Sitemap:` (yalnız BE-MAP canlıyken anlamlı)

### noindex_guard (bayrak SÖZLEŞMESİ: default=0 = tam no-op)

- [ ] Bayrak yokken: `curl -I https://rcistoc.cronbi.com/` → `X-Robots-Tag` header YOK
- [ ] `bench --site rcistoc.cronbi.com set-config seo_noindex_guard 1` + `clear-website-cache` →
      `curl -I https://rcistoc.cronbi.com/` → `X-Robots-Tag: noindex, nofollow` VAR
- [ ] Prod'da bayrak açıkken bile: `curl -I https://istoc.cronbi.com/` → header YOK (site eşlemesi prod)
- [ ] Marker muafiyeti: `curl -I -H "X-Istoc-Storefront: 1" https://rcistoc.cronbi.com/` → header YOK
- [ ] PROD'DA BAYRAK AÇMA KOŞULU: FAZ C canlı + Googlebot UA ile
      `curl -I -A "Googlebot" https://istoc.com/urun/<slug>` yanıtında `X-Robots-Tag` YOK kanıtı
- [ ] Geri alma: `set-config seo_noindex_guard 0` + `clear-website-cache`
