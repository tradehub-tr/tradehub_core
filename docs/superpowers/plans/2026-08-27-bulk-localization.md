# Bulk Localization — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development.

**Goal:** Kural tabanlı, kopyalamasız çok dilli alt backfill'i (en/ar/ru) + `missing_localized_alt` denetim kuralı + panel düğmesi + rapor 111.

**Architecture:** `seo_generate` dil ekseni kazanır (kaynak: `resolve_content_field` + `PLATFORM_TERMS`); backfill senkron+limit'li (`backfill_media_alt` emsali); denetim kuralı localization boyutunun ilk kodu.

**Tech Stack:** Frappe v15; yeni bağımlılık/kolon/patch YOK.

**Spec:** `docs/superpowers/specs/2026-08-27-bulk-localization-design.md` (L1-L8 bağlayıcı)

## Global Constraints

- COMMIT YOK, `git add` YOK (kullanıcı yasağı) — worktree; doğrulama container'a `docker cp` + `bench --site istoc.localhost run-tests`.
- **L1: TR kopyalama YASAK** — kaynak alanın o dildeki değeri boşsa YAZMA (`no_translation`). Bu, dilimin en kritik değişmezi; her görev testle sabitler.
- **L6: yalnız REFRESHABLE damgalı dosyalara yazılır; `alt_source` damgası değişmez.**
- Tab girinti, ≤110, `frappe.throw(_())`, log_error (§24), N+1 yasak (§6) — aday sorguları ve kural, toplu yollarda sorgu sayısını sabit tutar.
- Worktree'de watch/FM/CWV dilimlerinin commit'siz onaylı değişiklikleri var — ortak dosyalarda (seo_generate, seo_audit, media_admin, i18n, testler, panel) yalnız ekleme/genişletme.

---

### Task 1: i18n sabitleri + kural motoru dil desteği

**Files:**
- Modify: `tradehub_core/seo/i18n.py` (PLATFORM_TERMS +6; gerekirse küçük ordinal yardımcısı)
- Modify: `tradehub_core/media/seo_generate.py` (`_listing_metni`, `generate_alt`, `refresh_alt` dil parametresi; `no_translation` sebebi)
- Test: `tradehub_core/tests/test_media_seo_pipeline.py` (`TestAltUretimi`'ne dil senaryoları)

**Interfaces (Produces):**
- `generate_alt(file_url: str, lang: str = "tr") -> str` — lang için kaynak çeviri yoksa "" döner.
- `refresh_alt(file_url, *, lang: str = "tr", force: bool = False) -> {"written","alt","reason"}` — yeni sebep değeri: `"no_translation"`; hedef kolon `alt_{lang}` (tr'de mevcut davranış birebir korunur).
- `translate_platform_term` üzerinden yeni sabitler: "kategorisi", "mağaza logosu", "mağaza kapak görseli", "marka logosu", "marka kapak görseli"; "{n}. görsel" kalıbı dile göre ("(2. görsel)" / "(image 2)" / ar / ru).

**Steps:**
- [ ] PLATFORM_TERMS girişlerini ekle (en/ar/ru üçlüsü; mevcut sözlük biçimi). Ordinal kalıbı sözlüğe sığmıyorsa `image_ordinal(n, lang) -> str` saf yardımcısı yaz.
- [ ] `_listing_metni(listing, lang)`: başlık `resolve_content_field(listing, "title", lang)` — DİKKAT: fallback'li resolve TR döndürebilir; L1 gereği "o dilde gerçek çeviri var mı" kontrolü fallback'siz olmalı (`listing.get(f"title_{lang}")` doğrudan; tr için mevcut yol). Marka adı çevrilmez (özel isim, olduğu gibi).
- [ ] `generate_alt`/`refresh_alt` dil parametresi; kategori/mağaza/marka dallarında da aynı ilke (kategori adı: `Product Category.category_name_{lang}` doğrudan; boşsa `no_translation`).
- [ ] tr çağrılarının davranışı birebir korunur (regresyon: mevcut `TestAltUretimi` yeşil kalmalı).
- [ ] Yeni testler: EN üretim (title_en dolu), `no_translation` (title_en boş), insan damgası korunur (L6), force yalnız REFRESHABLE, ar/ru sabit ek çevirisi.
- [ ] Container: `test_media_seo_pipeline` + `test_media_seo` tam modüller; ruff. COMMIT YOK.

### Task 2: Aday sorgusu + backfill + whitelist ucu + denetim kuralı

**Files:**
- Modify: `tradehub_core/media/seo_generate.py` (`_backfill_adaylari` dil parametresi; `backfill_localization`)
- Modify: `tradehub_core/api/media_admin.py` (`backfill_media_localization` whitelist ucu)
- Modify: `tradehub_core/media/seo_audit.py` (`missing_localized_alt`; `_KURAL_BOYUT` 33)
- Test: `tradehub_core/tests/test_media_seo_pipeline.py` (+ gerekirse `test_api_contracts` toplu sözleşme sınıfına ekleme)

**Interfaces:**
- Consumes: Task 1'in `refresh_alt(..., lang=...)` sözleşmesi.
- Produces: `backfill_localization(limit: int = 500, langs: tuple = ("en","ar","ru")) -> {"scanned","written","skipped","reasons","by_lang"}`; `backfill_media_localization(limit: int = 500) -> dict` (whitelist, `_guard()`).

**Steps:**
- [ ] `_backfill_adaylari(limit, lang="tr", only_listing=True)`: `alt_{lang}` boş adaylar (mevcut IFNULL/NULL tuzağı notu korunur); lang="tr" mevcut davranış.
- [ ] `backfill_localization`: dil döngüsü × aday döngüsü, `refresh_alt(lang=...)`; `by_lang` sayaçları; idempotent.
- [ ] Whitelist ucu (`backfill_media_alt` emsali: `_guard`, senkron, type hints, i18n hata).
- [ ] `missing_localized_alt` (warn, localization): dosyanın `alt_tr` (veya taban alt) dolu VE bağlı Listing'in `title_{lang}` çevirisi mevcut VE `alt_{lang}` boş olan dil varsa tetiklenir; detayda eksik diller. Uygulama katmanı: Listing çeviri varlığı gerektiğinden **batch katmanı** (`_technical_findings` bölgesi) — Listing başlık çevirileri TOPLU tek sorguyla ön-yüklenir (N+1 yasak). Kaynak çevirisi olmayan dosyada SUSAR (L1/L4).
- [ ] `_KURAL_BOYUT`a kod; bütünlük assert'i 32→33 güncelle.
- [ ] Testler: aday sorgusu dil-duyarlı; idempotent ikinci koşum 0; kural VAR/SUSAR senaryoları; `_KURAL_BOYUT` 33.
- [ ] Container: `test_media_seo_pipeline` + `test_media_watch` + `test_file_manager_seo` (bütünlük assert'leri) ; ruff. COMMIT YOK.

### Task 3: Panel düğmesi + rapor 111

**Files:**
- Modify: `admin-panel/frontend/src/views/system/MediaSeoView.vue` (Çeviri backfill düğmesi — `backfillAlt` iki adımlı onay deseni), `frontend/src/i18n/locales/tr.js` + `en.js` (düğme + `mediaSeo.finding.missing_localized_alt`)
- Create: `docs/reports/111-bulk-localization-olcum.md`

**Steps:**
- [ ] Düğme + api çağrısı (`backfill_media_localization`) + toast (`{written} yazıldı, {skipped} atlandı` deseni); i18n anahtarları.
- [ ] Varsa ilgili panel testini koştur (node:test deseni).
- [ ] Canlı ölçüm (container console script; DB'ye salt backfill yazımı — koşum KENDİSİ ölçümdür, kullanıcı onayı gerekmez çünkü kural-tabanlı ve idempotent; ÖNCE `Listing.title_{lang}` doluluk sayımı, SONRA `backfill_localization` koşumu, SONRA localization skor örneklemi): sayıları topla.
- [ ] Rapor 111 (106-110 formatı): kaynak-çeviri doluluğu, `by_lang` sonuçları, `no_translation` oranı, skor önce/sonra, `missing_localized_alt` sayısı; dürüst yorum.
- [ ] COMMIT YOK.

## Self-review notu

Spec §7 ↔ görevler: 1→T1, 2→T1/T2, 3→T1, 4→T2, 5→T2, 6→T3, 7→T2. `refresh_alt(lang=...)` imzası T1'de üretilir T2 tüketir; `by_lang` T2→T3. Placeholder yok. Yeni kolon/patch yok — şema değişmiyor.
