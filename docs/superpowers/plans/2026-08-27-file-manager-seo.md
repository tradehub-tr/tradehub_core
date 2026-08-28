# File Manager SEO (Dilim 6) — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ürün dokümanlarına (PDF + modern ofis) yükleme yüzeyi, metadata/metin çıkarımı, seçici indexability, sitemap girdileri, DigitalDocument JSON-LD ve denetim kazandırmak.

**Architecture:** Watch diliminin kanıtlanmış desenlerinin doküman kardeşleri: `doc_meta.py` (video_poster deseni: enqueue + hata yutma + kardeş-kayıt yazımı), `doc_indexable` (`watch_indexable` deseni), sitemap doküman girdileri (`_watch_entries_for_rows` + preload + dedup + entry-sayımlı chunk), Listing API `documents` (`videoWatchUrl`/imageMeta "yoksa basma" deseni), panel formu (`listing_images` child deseni).

**Tech Stack:** Frappe v15, pypdf (kurulu), stdlib zipfile/xml; admin-panel Vue 3; tradehubfront Alpine/TS.

**Spec:** `docs/superpowers/specs/2026-08-27-file-manager-seo-design.md` (F1-F7 bağlayıcı)

## Global Constraints

- Dal `ahmet`, YENİ BRANCH YOK. **COMMIT / git add YASAK** (kullanıcı kuralı sürüyor) — tüm iş worktree'de; review paketleri `git diff HEAD` + yeni dosyalara `git add -N` (intent-to-add, commit değildir) ile üretilir.
- Yeni pip/npm bağımlılığı YASAK (F4). Tab indent, 110, type annotation, `frappe.throw(_(...))`, tek okuma kapısı (`fields_for`), kardeş-kayıt yazımı `{"name": ["in", adlar]}`.
- Konteyner test deseni: `docker cp` → `bench --site istoc.localhost run-tests --module ...`; konteynerde ruff `/home/frappe/.local/bin/ruff`.
- Worktree'de önceki dilimlerin commit'siz onaylı değişiklikleri var — şu dosyalara DOKUNMA (Task 4 hariç listelenen istisnalar): `media/pipeline_bridge.py`, `media/migration_runtime.py`, `media/watch_slug.py`, `api/media_public.py` (Task 3'te ekleme serbest), `seo/page_resolver.py`, `seo/sitemap_generator.py` (Task 3'te ekleme serbest), `api/listing.py` (Task 4'te ekleme serbest).
- Doküman uzantı kümeleri: çıkarım kapsamı `(".pdf", ".docx", ".xlsx", ".pptx")`; `.doc/.xls` → `legacy_format` (F6). Tek yerde tanımlanır (`doc_meta.DOC_UZANTILAR`), tüketiciler import eder.

---

### Task 1: Şema — `Listing Document` + File kolonları

**Files:**
- Create: `tradehub_core/tradehub_core/doctype/listing_document/{listing_document.json,listing_document.py,__init__.py}`
- Modify: `tradehub_core/tradehub_core/doctype/listing/listing.json` (`documents` Table alanı — mevcut `listing_images` alanının yanına, aynı desen)
- Create: `tradehub_core/patches/v15_9_52_file_doc_fields.py` (+ `patches.txt` kaydı)
- Modify: `tradehub_core/media/seo.py` (`_asset_columns`/`_birlestir` width-height desenine `th_media_page_count`, `th_media_extracted_text` — SINGLE'a GİRMEZ)
- Test: `tradehub_core/tests/test_file_manager_seo.py` (yeni)

**Interfaces:**
- Produces: `Listing Document` child (fields: `file` Attach reqd, `title` Data, `doc_type` Select `Katalog\nSertifika\nKılavuz\nTeknik Föy\nDiğer`, `language` Select `tr\nen\nar\nru\ndiğer` default tr; `istable=1`); `fields_for` dönüşünde `page_count` (int) ve `extracted_text` (str) anahtarları; iki kolon dışarıdan (`set_asset_fields`) yazılamaz.

- [ ] **Step 1: Failing testler** — (a) kolonlar var; (b) `fields_for` iki anahtarı döndürüyor (db.set_value ile doldurup oku); (c) `set_asset_fields({"page_count": 5, "extracted_text": "x", "description": "d"})` → yalnız description yazılır; (d) `Listing Document` child'ı Listing'e append+save ile yazılabiliyor (mevcut listing test fixture'ı: `grep -rn "_gorunur_ilan" tradehub_core/tradehub_core/tests/test_media_watch.py` — aynı yardımcıyı import et). Doctype şeması `bench migrate` ile yüklenir (docker cp doctype klasörü + listing.json + patch → migrate).
- [ ] **Step 2: FAIL doğrula** → **Step 3: Uygula** (doctype JSON'u `listing_image` kardeşinden desenle — `cat tradehub_core/tradehub_core/doctype/listing_image/listing_image.json`; patch v15_9_49 deseninde `create_custom_fields(update=True)`: `th_media_page_count` Int, `th_media_extracted_text` Long Text, ikisi hidden+no_copy) → **Step 4: migrate + PASS + `test_media_seo` regresyon (20/20)**.

---

### Task 2: Çıkarım motoru — `media/doc_meta.py` + kanca + backfill

**Files:**
- Create: `tradehub_core/media/doc_meta.py`
- Modify: `tradehub_core/hooks.py` (`File.after_insert` listesine `media.doc_meta.maybe_extract_on_insert` — mevcut medya kancalarının yanına, append)
- Test: `tradehub_core/tests/test_file_manager_seo.py` (ekleme)

**Interfaces:**
- Produces: `DOC_UZANTILAR = (".pdf", ".docx", ".xlsx", ".pptx")`; `extract(file_url) -> dict` (`{"ok": bool, "reason": str, "page_count": int, "text": str, "title": str}`); `apply(file_url) -> bool` (extract + kardeş kayıtlara yazım + boşsa `th_media_title` önerisi; hata yutulur + `frappe.log_error`); `maybe_extract_on_insert(doc, method=None)` (public KIND_DOCUMENT ise `media-maint`'e enqueue, `enqueue_after_commit=True` — `video_poster` fast-path enqueue deseni: `grep -n "media-maint" tradehub_core/media/transcode.py`); `backfill_docs(limit: int = 200) -> int` (senkron; public + `th_media_page_count=0 AND th_media_extracted_text boş` + DOC_UZANTILAR LIKE — `video_poster.backfill_pending`'in SQL deseni).
- Metin tavanı: `TEXT_TAVAN = 64 * 1024` (karakter); PDF sayfa sınırında kes.

- [ ] **Step 1: Failing testler** — fixture üretimi test içinde: PDF (`pypdf.PdfWriter` — `tests/test_media_inventory_filters.py:96` örneği), docx/xlsx (stdlib `zipfile` ile minimal geçerli paket: docx = `[Content_Types].xml` + `word/document.xml` içinde 2 paragraf; xlsx = `xl/sharedStrings.xml` 3 string). Senaryolar: (a) PDF → page_count=2 + metin dolu + boş `th_media_title` metadata başlığıyla dolar; (b) dolu title EZİLMEZ; (c) şifreli PDF (`writer.encrypt("x")`) → ok=False, alanlar boş, exception yok; (d) docx metni; (e) xlsx sharedStrings; (f) `.doc` → reason=legacy_format; (g) 64 KB kesme (uzun metinli üretilmiş PDF); (h) kardeş kayıt: aynı file_url'lü iki File → ikisine de yazılır; (i) `backfill_docs` idempotent (ikinci tur 0).
- [ ] **Step 2-4: FAIL → uygula → PASS.** XML parse `xml.etree.ElementTree` ile (namespace-duyarlı: docx `w:t`, pptx `a:t`, xlsx `t` node'ları); regex YOK.
- [ ] **Step 5: Backfill'i canlıda koş** (`bench execute ... backfill_docs --kwargs "{'limit': 200}"`), sayıyı raporla (beklenti: private çoğunlukta olduğundan düşük).

---

### Task 3: `doc_indexable` + sitemap doküman girdileri + DigitalDocument

**Files:**
- Modify: `tradehub_core/api/media_public.py` (EKLEME: `doc_indexable`)
- Modify: `tradehub_core/seo/schema_builder.py` (EKLEME: `build_digital_document`; `build_product_schema`'ya `media_documents` kwarg → `schema["subjectOf"] = media_documents`)
- Modify: `tradehub_core/seo/sitemap_generator.py` (EKLEME: `_preload_doc_listings`, `_doc_entries_for_rows` — watch kardeşleri; `_entries_for_rows` zincirine bağla)
- Test: `tradehub_core/tests/test_file_manager_seo.py` (ekleme)

**Interfaces:**
- Produces: `doc_indexable(file_url, *, fields=None, listings=None) -> bool` — `watch_indexable` gövdesinin doküman ikizi; listings sorgusu TEK `frappe.get_all("Listing Document", filters={"file": ["in", urls]}, fields=["file", "parent"])` + parent'ları tek `get_all("Listing", {"name": ["in", ...], "storefront_visible": 1})` (iki toplu sorgu, N+1 yok). `build_digital_document(seo_fields, site_url, *, content_url, doc_type="") -> dict | None` — name (title → extracted başlık zaten title'a yazıldı → dosya adı gövdesi) yoksa None; `@type: DigitalDocument`, url/contentUrl mutlak (`_absolute_url`), `encodingFormat` (mimetypes), `dateCreated`, lisans beşlisi (`_license_props` mevcut yardımcı — `grep -n "acquireLicensePage" tradehub_core/seo/schema_builder.py` ile bul, aynen kullan). Sitemap doküman girdisi: `loc = mutlak ham dosya URL'i`, `lastmod = File.modified`, gövde EK alan taşımaz (video/image anahtarları YOK); dedup file_url bazlı; entry-sayımlı chunk'a watch ile aynı akıştan katılır.

- [ ] **Step 1: Failing testler** — (a) üç koşullu doc_indexable (+private → False); (b) DigitalDocument tam/adsız-None/lisanslı; (c) sitemap: indexable doküman `<url>` üretir, görünmez üründe üretmez, iki üründe aynı dosya → tek girdi; (d) ürün JSON-LD `subjectOf` (compose_for_listing zincirinde media_videos deseninin yanına — `grep -n "media_videos" tradehub_core/seo/schema_builder.py`).
- [ ] **Step 2-4: FAIL → uygula → PASS + regresyonlar** (`test_media_video_seo` 33/33, `seo.tests.test_sitemap_generator` 28/28, `test_sitemap_cache` 15/15, `test_media_watch` 36/36).

---

### Task 4: Listing API `documents` + JSON-LD bağlama

**Files:**
- Modify: `tradehub_core/api/listing.py` (EKLEME — `get_listing_detail` sonucuna `documents`, JSON-LD hazırlığına `media_documents`)
- Test: `tradehub_core/tests/test_file_manager_seo.py` (ekleme)

**Interfaces:**
- Produces: `documents: [{url, title, docType, language, sizeBytes}]` — `listing.documents` child'ından; alan LİSTE BOŞSA HİÇ BASILMAZ (videoWatchUrl deseni). Boyut `File.file_size` tek toplu `get_all` ile (N+1 yok). JSON-LD: her doküman için `fields_for` + `build_digital_document`; None'lar elenir; `media_documents` compose zincirine geçer (Task 3'ün kwarg'ı).

- [ ] TDD adımları: sözleşme testi (dolu/boş/None eleme) → uygula → `test_media_watch` (videoWatchUrl bölgesi) + listing regresyon modülleri yeşil.

---

### Task 5: Yüzeyler — panel form bölümü + vitrin dokümanlar bloğu

**Files:**
- Modify: `admin-panel/frontend/src/views/seller/ListingFormView.vue` ("Dokümanlar" bölümü — `childData.listing_images` bloğunun kardeşi: satır listesi + `MediaPickButton` (doküman seçimi; kind prop'unun doküman desteğini `grep -n "kind" src/components/media/MediaPickButton.vue` ile doğrula, yoksa accept genişlet) + `doc_type`/`language` select'leri + sil)
- Modify: panel i18n tr+en (`listingForm.documents.*` anahtarları)
- Modify: `tradehubfront/src/pages/product-listing.ts` DEĞİL — ürün detay: `tradehubfront/src/pages/product-detail.ts` + ilgili bileşen (dokümanlar bloğu; `grep -n "transcript\|details" src/pages/media-watch.ts` — `<details>` deseni); `listingService.ts` `documents` eşlemesi + `types/product.ts`
- Test: panel node:test (form satır ekleme/emit), vitrin Vitest (eşleme + boş-liste render yok)

**Interfaces:**
- Consumes: Task 4 `documents` sözleşmesi; kaydetme mevcut listing save akışı (childData deseni — `grep -n "childData" ListingFormView.vue` ile save yolunu izle, YENİ uç açma).
- Not: vitrin bloğunda tüm metinler `escapeHtml`, URL'ler `sanitizeUrl`; i18n dörtlü (tr/en/ru/ar).

- [ ] TDD: failing testler → uygula → panel `npm test`+`lint`, vitrin `npx vitest run`+`lint`+`build`.

---

### Task 6: Denetim + ölçüm raporu 109

**Files:**
- Modify: `tradehub_core/media/seo_audit.py` (`_doc_bulgulari` — `_watch_slug_bulgusu` deseninde, yalnız `audit_file` deep yolunda: `missing_doc_title`/`missing_doc_text`/`missing_doc_language`; `_KURAL_BOYUT`: title→metadata, text→discoverability, language→metadata)
- Create: `docs/reports/109-file-manager-seo-olcum.md`
- Test: `tradehub_core/tests/test_file_manager_seo.py` (ekleme)

- [ ] TDD: kural testleri (bağlı dokümanda WARN'lar; görselde/bağsızda yok; deep=False'ta yok) → uygula → tam paket regresyon (`test_file_manager_seo` + `test_media_watch` + `test_media_seo_pipeline`) → backfill sayıları + "index'e giren doküman: 0 (beklenen — içerik gelince dolacak)" dürüst ölçümüyle rapor 109 (106/107/108 deseni).

---

## Self-Review Notları

- Spec kapsaması: §3→T1, §4→T2, §5→T3, §6 API→T4, §6 yüzeyler→T5, §7-8→T6; F1-F7 Global Constraints'te.
- Tip tutarlılığı: `DOC_UZANTILAR` tek kaynak (doc_meta) — sitemap/audit/backfill import eder; `fields_for` anahtarları `page_count`/`extracted_text`; API alan adları camelCase (`docType`, `sizeBytes`) — imageMeta/videoMeta ile tutarlı.
- Bilinçli sınır: MediaPickButton doküman desteği yoksa T5 içinde küçük genişletme yapılır (ayrı görev açılmaz — aynı reviewer yüzeyi).
