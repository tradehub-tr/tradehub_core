# Commit İnceleme Rehberi — 2026-08-28

Worktree'de 4 dilimin commit'siz kodu var. Bu belge, "ben inceleyip kendim
commit'lerim" kararın için dosya→dilim haritası ve önerilen commit stratejisi.
(Bu dosyanın kendisi de commit'e girmeyebilir — inceleme bitince silinebilir.)

**Kanıt zinciri:** her dilimin ledger'ı `.superpowers/sdd/<dilim>/progress.md`
(görev geçmişi, review kararları, ruling'ler) ve inceleme paketleri (diff'ler)
aynı klasörlerde. Ölçüm raporları `docs/reports/108-111`.

## Dilimler

| Dilim | İçerik | Test kanıtı |
|---|---|---|
| **5 — Watch Page** | /medya/v/<slug> izleme sayfası, slug 301 zinciri, og:video, video sitemap watch girdileri | test_media_watch 36/36, rapor 108 |
| **6 — File Manager SEO** | Listing Document child table, doc_meta çıkarım (zip-bomb savunmalı), DigitalDocument JSON-LD, doküman sitemap, satıcı formu + ürün bloğu, 3 denetim kuralı | test_file_manager_seo 68/68, rapor 109 |
| **7 — CWV Denetimi** | 5 performans kuralı (policy tek kaynak), LCP=primary ayrımı, cache _v2, panel etiketleri | test_media_seo_pipeline (CWV testleri), rapor 110 (+boyut backfill EK'i) |
| **8 — Bulk Localization** | Kopyalamasız çok dilli alt üretimi, backfill ucu, missing_localized_alt, panel düğmesi | test_media_seo_pipeline 84/84, rapor 111 |
| (tamirat) | listing.py yaşam-döngüsü elemesi, test_media_av mock, panel 350ms | FM ledger sonu |

## ⚠ Önemli: dosyalar dilimler arasında PAYLAŞILIYOR

Aynı dosyada birden çok dilimin hunk'ı var — **dilim-başına ayrık commit
pratik değil**. Önerilen: repo başına TEK commit (ya da core'da 2: şema+kod).
Hunk bazında ayırmak istersen dilim diff'leri `.superpowers/sdd/*/review-*.diff`
dosyalarında.

## tradehub_core (37 dosya)

**Yalnız tek dilime ait:**
- Dilim 5: `seo/page_resolver.py`, `seo/templates/seo_head.html`, `seo/tests/test_html_injector.py`, `seo/tests/test_page_resolver.py`, `tests/test_media_watch.py`, `tests/test_media_video_seo.py`, `patches/v15_9_50_watch_slug_indexes.py`, `patches/v15_9_51_media_index_property_setters.py` (index-drop tuzağı düzeltmesi)
- Dilim 6: `media/doc_meta.py`, `doctype/listing_document/*` (3 dosya), `doctype/listing/listing.json`, `patches/v15_9_52_file_doc_fields.py`, `tests/test_file_manager_seo.py`, `hooks.py` (File.after_insert), `media/upload_policy.py` (.pptx), `media/seo.py` (page_count/extracted_text)
- Dilim 8: `seo/i18n.py` (PLATFORM_TERMS + ordinal), `media/seo_generate.py` (dil desteği + backfill_localization; boyut backfill fonksiyonu zaten vardı)
- Tamirat: `media/seo_index.py` (BLOCKED_* sabitleri), `tests/test_media_av.py`
- Raporlar/dokümanlar: `docs/reports/107-111`, `docs/superpowers/{specs,plans}/2026-08-27-*` (3+3), `docs/MOGEM-620-DURUM.md`

**Karışık (birden çok dilim):**
- `api/listing.py` → D6 (documents alanı + private/lifecycle eleme) + D5 (videoWatchUrl)
- `api/media_admin.py` → D5 (watch slug uçları) + D7 (_seo_audit_adaylari primary, _primary_urls_for) + D8 (backfill_media_localization)
- `api/media_public.py` → D5 (watch page) + D6 (doc_indexable)
- `seo/schema_builder.py` → D5 (VideoObject watch) + D6 (DigitalDocument, _license_props refactor)
- `seo/sitemap_generator.py` → D5 (watch girdileri + chunk yeniden yazımı) + D6 (doküman girdileri)
- `media/seo_audit.py` → D6 (3 doküman kuralı) + D7 (5 CWV kuralı) + D8 (missing_localized_alt) — toplam 33 kural
- `tests/test_media_seo_pipeline.py` → D7 + D8 testleri
- `patches.txt` → v15_9_50/51/52 satırları
- `seo/tests/test_sitemap_generator.py` → D5 + D6

**Önerilen mesajlar (repo-başına tek commit seçersen):**
```
feat(media-seo): dilim 5-8 — watch page, file manager, CWV denetimi, bulk localization

- /medya/v/<slug> watch sayfası + slug 301 + video sitemap (rapor 108)
- Listing Document + doc çıkarımı + DigitalDocument + doküman denetimi (rapor 109)
- 5 CWV kuralı + LCP primary ayrımı + boyut backfill EK ölçümü (rapor 110)
- kopyalamasız çok dilli alt + missing_localized_alt + backfill ucu (rapor 111)
- tamirat: guest documents yaşam-döngüsü elemesi, index-drop tuzağı (v15_9_51)
```

**Commit sonrası gerekenler:** container'da `bench migrate` (v15_9_50/51/52
zaten dev'de koştu — prod/alpha'da koşacak) + backend imaj rebuild +
`test_http_api_contracts` whitelist baseline güncellemesi (120→144).

## admin-panel (10 dosya)

- D5: `MediaSeoDrawer.vue`, `useMediaSeo.js` (kısmen), `mediaSeoVideo.test.js` (slug UI)
- D6: `listingDocuments.js` + testi, `ListingFormView.vue` + documents testi (+tamirat: 350ms upload bekleme kaldırıldı)
- D7+D8: `MediaSeoView.vue` (çeviri backfill düğmesi), `useMediaSeo.js` (backfillLocalization)
- Karışık: `i18n/locales/{tr,en}.js` (D6+D7+D8 anahtarları)

Öneri: tek commit — `feat(media-seo): doküman formu, CWV/localization etiketleri, çeviri backfill düğmesi`. Sonrası: panel imaj rebuild (compose build).

## tradehubfront (17 dosya)

- D5: `pages/media-watch.html`, `src/pages/media-watch.{ts,test.ts}`, `nginx.conf.template` (location), `vite.config.ts` (entry), `ProductVideoSection.ts` (watch link), `listingService.*` (kısmen), 4 locale (kısmen)
- D6: `ProductDocuments.{ts,test.ts}`, `ProductTabs.ts`, `product/index.ts`, `types/product.ts`, `listingService.*` (documents), 4 locale (kısmen)

Öneri: tek commit — `feat(media-seo): watch sayfası + ürün doküman bloğu`. Sonrası: `npm run build` + storefront imaj rebuild (dist bind-mount DEĞİL — imaj pişirilmeli).

## Bugünkü kararların kaydı (2026-08-28)

- Commit: kullanıcı kendisi inceleyip atacak (bu rehber onun için)
- AI servisi: ERTELENDİ (D-listesinde kalır)
- Lisans varsayılanı: BOŞ kalır, hukuka sorulacak
- alt zorunluluğu: YAYINA ALIRKEN — küçük dilim olarak planlanacak (kod, commit kararından SONRA yazılır ki inceleme yığınına karışmasın)
