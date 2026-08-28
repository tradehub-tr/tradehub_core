# File Manager SEO — Tasarım (Dilim 6)

**Plane:** MOGEM-620 §15 (File Manager kapsamı) + §6'nın kalanı (DigitalDocument)
**Durum haritası:** `docs/MOGEM-620-DURUM.md` A-15 (tek ❌ madde) ve A-6 kalanı
**Tarih:** 2026-08-27 · **Durum:** Onaylandı (kullanıcı; kapsam/index/altyapı
kararları AskUserQuestion ile alındı) · **Not:** commit yasağı sürüyor — bu
spec ve uygulaması worktree'de birikir.

---

## 1. Gerçeklik ölçümü ve işin doğası

Envanter (2026-08-27, canlı dev DB): 14 PDF (**hepsi private** — dekont/KYB
sınıfı), 1 docx + 34 xlsx + 56 csv (hepsi private; bulk-import artefaktları),
36 public txt (sistem dosyası). **Public, ürünle ilişkili, indexlenebilir
doküman: 0.**

Bu yüzden dilim bir "tohumlama" işi değil, **altyapı yatırımı**: satıcıların
ürün dokümanı (katalog/sertifika/kılavuz) yükleyebileceği yüzey dahil kurulur;
SEO değeri içerik geldikçe doğar. (Kullanıcı kararı: "Altyapıyı yine de kur".)

## 2. Kararlar

| # | Karar | Kaynak |
|---|---|---|
| F1 | Kapsam: **PDF + modern ofis formatları** (docx/xlsx/pptx). Ses dosyaları YOK (envanter 0, YAGNI) | Kullanıcı |
| F2 | **Seçici index**: yalnız public + görünür ürüne bağlı + `seo_index.decide` olumlu dokümanlar index; kalanlar noindex, private 404 | Kullanıcı |
| F3 | Yükleme yüzeyi DAHİL: satıcı listing formuna "Dokümanlar" bölümü + ürün sayfasında dokümanlar bloğu | Kullanıcı ("altyapıyı yine de kur") |
| F4 | **Yeni bağımlılık YOK**: PDF için kurulu `pypdf`; docx/xlsx/pptx metni stdlib (`zipfile`+XML). **Thumbnail v1'de kapsam dışı** (poppler isterdi) | Repo kuralı |
| F5 | İndexlenebilir PDF sitemap'e **ham URL** ile girer — doküman landing page YOK (Google PDF'i doğrudan indexler; watch-page'ten farkı budur). `canonical` alanı dokümanda boş kalır | Basitlik + Google davranışı |
| F6 | Eski ikili formatlar (.doc/.xls) kabul edilmeye devam eder ama metin çıkarımı/SEO işlemez ("işlenemedi" olarak etiketlenir) | YAGNI |
| F7 | OCR (taranmış PDF) kapsam dışı — AI servisi kararına bağlı (D listesi) | Bekleyen karar |

## 3. Şema

**Yeni child table `Listing Document`** (Listing'e `documents` Table alanı):

| Alan | Tip | Not |
|---|---|---|
| `file` | Attach | zorunlu; upload_policy KIND_DOCUMENT kapısından |
| `title` | Data | boşsa çıkarımdan önerilir |
| `doc_type` | Select | `Katalog / Sertifika / Kılavuz / Teknik Föy / Diğer` |
| `language` | Select | `tr / en / ar / ru / diğer` (varsayılan tr) |

**`File`'a 2 kolon** (patch, `th_media_` deseni, hidden/no_copy):
`th_media_page_count` (Int) · `th_media_extracted_text` (Long Text, ilk 64 KB —
site içi arama + denetim; dış yüze BASILMAZ).

Okuma tek kapıdan: `media/seo.fields_for` bu iki alanı da döndürür
(`page_count`, `extracted_text` — SINGLE'a girmez, width/height gibi sistem
alanı; dışarıdan yazılamaz).

## 4. Çıkarım motoru — `media/doc_meta.py`

- `extract(file_url) -> dict`: türe göre —
  **PDF** (`pypdf`): metadata (title/author/subject/keywords), sayfa sayısı,
  sayfa sayfa metin (64 KB tavan, sayfa sınırında kes); şifreli/bozuk PDF →
  `{"ok": False, "reason": ...}`, hata yutulur, dosya düşmez (poster ilkesi).
  **docx/pptx**: `zipfile` + `word/document.xml` / slide XML'lerinden metin
  (regex değil, `xml.etree` ile text node'ları). **xlsx**: `sharedStrings.xml`.
  **doc/xls (F6)**: `{"ok": False, "reason": "legacy_format"}`.
- Yazım: `th_media_page_count` + `th_media_extracted_text` + (File.title'ı
  EZMEZ) `th_media_title` BOŞSA çıkarılan başlıkla doldurur, `alt_source`
  benzeri kaynak izi GEREKMEZ (görsel alt'ından farklı: erişilebilirlik değil).
- Tetikleme: `File.after_insert` kancasında KIND_DOCUMENT ise `media-maint`
  kuyruğuna enqueue (av/poster deseni) + mevcutlar için `backfill_docs(limit)`
  (senkron, bench execute).
- Kardeş kayıt dersi uygulanır: yazım `{"name": ["in", adlar]}` ile tüm
  aynı-url kayıtlarına.

## 5. Indexability + sitemap + yapısal veri

- `media_public.doc_indexable(file_url, *, fields=None, listings=None) -> bool`
  — `watch_indexable` deseninin doküman kardeşi: `seo_index.decide` olumlu AND
  public AND en az bir görünür ürüne `Listing Document` ile bağlı. Listings
  sorgusu: `Listing Document.file → parent Listing.storefront_visible=1`
  (tek JOIN'li `get_all`, N+1 yok).
- Sitemap: Listing sitemap üretiminde, `doc_indexable` dokümanı olan ilanlar
  için doküman başına EK `<url>`: `loc = ham dosya URL'i` (mutlak),
  `lastmod = File.modified`. Watch girdilerindeki toplu ön-yükleme + dedup +
  üretilen-entry-sayımlı chunk desenleri AYNEN uygulanır (Task 5'in
  `_watch_entries_for_rows`/`_preload_*` kardeşleri).
- `schema_builder.build_digital_document(seo_fields, site_url, *, content_url,
  doc_type="") -> dict | None`: `@type: DigitalDocument`, `name` (title →
  çıkarılan başlık → dosya adı), `url`/`contentUrl`, `encodingFormat`,
  `dateCreated`, lisans beşlisi (ImageObject ile aynı yardımcı). `name` yoksa
  None. Ürün JSON-LD'sinde `subjectOf: [DigitalDocument...]` olarak bağlanır
  (media_videos deseniyle `build_product_schema`'ya `media_documents` kwarg).

## 6. Yüzeyler

- **Satıcı listing formu (admin-panel `views/seller/ListingFormView.vue` —
  keşifle düzeltildi, tradehubfront DEĞİL)**: "Dokümanlar" bölümü —
  `childData.listing_images` + `MediaPickButton` deseninin doküman kardeşi
  (tür/dil seçimli satırlar); kaydetme mevcut listing save akışına `documents`
  child'ı olarak katılır.
- **Ürün detay sayfası**: "Dokümanlar" bloğu — tür rozeti + başlık + boyut +
  indirme linki (`rel="nofollow"` YOK — index kararı sitemap/robots'ta).
  Listing API'ye `documents: [{url, title, docType, sizeBytes, language}]`
  (alan yoksa hiç basılmaz — videoWatchUrl deseni).
- **Panel**: mevcut SEO çekmecesi doküman dosyalarında da çalışır (title/
  description/lisans); kütüphane tür filtresi mevcut (inventory document
  MIME'ları biliyor). Yeni panel işi YOK (YAGNI).

## 7. Denetim

3 kural (yalnız `Listing Document`'a bağlı dokümanlarda, WARN):
`missing_doc_title` (metadata) · `missing_doc_text` (discoverability —
"taranamaz/boş içerik; OCR gerekebilir") · `missing_doc_language` (metadata).
`audit_file` deep yolunda (watch kuralıyla aynı maliyet kararı).

## 8. Test stratejisi

- doc_meta: gerçek küçük fixture'lar (pypdf ile testte üretilen 2 sayfalık
  PDF; stdlib ile yazılmış mini docx/xlsx), şifreli-PDF hata yolu, 64 KB
  kesme, kardeş-kayıt yazımı.
- doc_indexable: W3-kardeşi üçlü koşul + private 404.
- Sitemap: doküman `<url>` var/yok (indexable/değil), dedup, chunk sayımı.
- DigitalDocument builder birim testleri; Listing API `documents` sözleşmesi.
- Vitrin: form bölümü + ürün bloğu Vitest; i18n dörtlü.
- Ölçüm: rapor 109 (çıkarım kapsaması; index'e giren doküman sayısı — bugün 0
  olması beklenen ve raporlanacak durum).

## 9. Kapsam dışı

Ses/AudioObject (envanter 0) · thumbnail/önizleme (F4) · OCR (F7) ·
doküman landing page (F5) · CSV/TXT SEO'su · .doc/.xls çıkarımı (F6) ·
çok dilli çıkarılmış metin.

## 10. Kabul kriterleri

1. Satıcı, listing formundan tür seçerek PDF/docx yükleyebilir; dosya
   `Listing Document` satırıyla ürüne bağlanır.
2. Yüklenen PDF'in sayfa sayısı + metni + (boşsa) başlığı otomatik dolar;
   şifreli/bozuk dosya üründeki akışı düşürmez.
3. Görünür ürüne bağlı public PDF sitemap'te ham URL ile listelenir; aynı
   dosya üründen çıkarılınca sonraki üretimde sitemap'ten düşer.
4. Ürün JSON-LD'sinde `subjectOf` altında DigitalDocument (lisans beşlisiyle)
   görünür; başlıksız doküman nesne üretmez.
5. Ürün sayfasında dokümanlar bloğu tür rozetiyle listelenir; API alanı
   doküman yokken hiç basılmaz.
6. Denetim, bağlı dokümanlarda 3 kuralı raporlar; skor kırılımlarına işler.
7. Private dokümanlar hiçbir yüzeye (sitemap/JSON-LD/ürün bloğu) sızmaz —
   testle sabitlenir.

## 11. Uygulama sırası (plan iskeleti)

1. Şema: `Listing Document` DocType + File 2 kolon + patch
2. `doc_meta.py` çıkarım + kanca + backfill
3. `doc_indexable` + sitemap doküman girdileri + DigitalDocument
4. Listing API `documents` + yazma ucu
5. Vitrin: form bölümü + ürün bloğu
6. Denetim kuralları + rapor 109
