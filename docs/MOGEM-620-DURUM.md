# MOGEM-620 — Medya SEO / Keşfedilebilirlik / AI Arama Katmanı — DURUM

**Plane:** MOGEM-620 (kaynak spec: "SEO for media & file manager" Google Doc'u)
**Amaç:** Plane API'ye sormadan ilerlemeyi buradan takip etmek. Bir madde
bittiğinde kutusunu işaretle + tarih düş. Kanıt kolonundaki yol/rapor,
"bitti" iddiasının doğrulanacağı yerdir.

**Son güncelleme:** 2026-08-27 akşam — Dilim 6 (File Manager), Dilim 7 (CWV denetimi) ve Dilim 8 (Bulk Localization) kod tamam; **kodla kapatılabilir işlerin tamamı bitti** — kalanlar insan kararlarına bağlı (commit/revert, boyut backfill, AI servisi, imaj rebuild). TÜM yeni dilimler commit'siz worktree'de

Durum göstergesi: ✅ bitti · 🔄 şu an çalışılıyor · 🔶 kısmi (kalanı notta) ·
⏳ sırada/bekliyor · ❌ başlanmadı · 🚫 bilinçli kapsam dışı

---

## A. MOGEM-620 işlevsel gereksinimleri (Plane'deki 18 bölüm)

| # | Bölüm | Durum | Kanıt / Kalan |
|---|---|---|---|
| 1 | Asset Intelligence (MIME/probe, hash+dedup, EXIF policy, malware, bozuk dosya) | ✅ | `media/pipeline/core/{probe,dedup}.py`, `exif_vault.py` (GPS her koşulda strip + şifreli kasa), `av.py` |
| 2 | SEO Metadata Engine (alan seti + kullanım ezmesi + lisans/telif) | ✅ | TUR-135 Dilim 1; `media/seo.py` tek kapı, `Media SEO Override`. Kalan: title/caption/license ELLE doldurulur (tasarım gereği) |
| 3 | AI Metadata Generation | 🔶 | Şema + onay akışı hazır (`th_media_alt_ai`, rule/ai/human/edited); **AI servisi PM kararı bekliyor** (§11.7). Kural tabanlı alt üretimi ✅ (1.988 adres dolu) |
| 4 | Image SEO / Processing Engine (AVIF/WebP merdiveni, srcset, crop, LQIP) | ✅ | Katalog tohumlaması BİTTİ: 3.116/3.130 (%99,5), 20.896 türev/636 MB, 0 hata; A-sınıfı migration 48/48 validated (%53 tasarruf). Rapor 107. Kalan: imaj rebuild (sabah commit kararından sonra) + 5 inatçı artık |
| 5 | Video SEO / Processing Engine | ✅ | **Bugün bitti** (Dilim 4): poster, VideoObject, video sitemap, transcript/VTT, panel+vitrin. Spec+rapor: `docs/superpowers/specs/2026-08-26-…`, `docs/reports/106-…`. Kapsam dışı: watch page, SeekToAction, embed poster (amendment §12) |
| 6 | Schema.org Engine | ✅ | ImageObject+lisans beşlisi ✅, VideoObject ✅, **DigitalDocument ✅ (Dilim 6)**. AudioObject 🚫 bilinçli kapsam dışı (envanter 0, F1 kararı) |
| 7 | Sitemap + Indexability Engine | ✅ | Görsel ✅ + video ✅ sitemap; `seo_index.decide` tek karar noktası; private=404 ilkesi. News sitemap koşullu — tüketici yok |
| 8 | URL Management (stable ID ≠ delivery, canonical/derivative/CDN rolleri) | ✅ | İçerik-adresli kimlik + 301 + imzalı TTL + **watch page (Dilim 5, gece bitti)**: /medya/v/<slug>, slug↔canonical, eski slug 301 zinciri |
| 9 | Rendering + Performance SEO | ✅ | Render ipuçları + srcset manifest ✅; CWV denetim kuralları ✅ (Dilim 7); **boyut backfill'i KOŞULDU (2026-08-28)**: doluluk %94,6, missing_dimensions 0, LCP bulgusu 4, performance skoru 98 (49'dan). Kalan: RUM örneklem büyümesi (pasif) + panelden çalışılacak yeni iş listesi (oversized 108, ladder 68). Gerçek HTML fetchpriority doğrulaması bilinçli kapsam dışı (C8) |
| 10 | Visual Search + Semantic/Entity katmanı | 🔶 | Perceptual hash + benzer arama ✅; **asset usage graph ✅** (`usage.py`/`refs.py`). Kalan: object/OCR/logo tanıma, embeddings, entity graph — AI servisi kararına bağlı |
| 11 | Multilingual Media SEO | 🔶 | alt/title/caption × 4 dil ✅; **kural-tabanlı çok dilli alt üretimi ✅ (Dilim 8 — kopyalamasız, kaynak çeviri geldikçe dolar)**. Kalan: transcript/subtitle çok dil (bilinçli tek dil — K3), locale-specific medya override, içerik çevirilerinin kendisi (199/2723 ilan) |
| 12 | E-commerce / Product SEO (koşullu) | 🔶 | Listing↔görsel/video bağı + JSON-LD Product ilişkisi ✅. Kalan: SKU/GTIN association, görsel ROLLERİ (swatch/lifestyle/360) — ürün özelliği talebi yok |
| 13 | SEO Audit + Media SEO Score | ✅ | 12 görsel + 3 video + 3 doküman (Dilim 6) + **5 CWV (Dilim 7)** + **1 localization (Dilim 8)** = 33 kural, 8 boyutlu skor (localization boyutu artık süzülebilir), panel görünümleri + 6 yeni tr/en etiket |
| 14 | Bulk Operations | ✅ | G-16-10 + toplu alt/boyut backfill'leri + **bulk localization ✅ (Dilim 8, 2026-08-27, commit'siz)**: kopyalamasız kural-tabanlı çok dilli alt backfill (`backfill_media_localization`), `missing_localized_alt` kuralı (toplam 33 oldu), panel "Çeviri backfill" düğmesi. Rapor 111 (dürüst 0-yazım: dev'de çevirili ilanların tamamı harici görselli — mekanizma testli, içerik çeviri geldikçe dolar) |
| 15 | File Manager kapsamı (PDF/audio/doküman SEO) | ✅ kod tamam | **Dilim 6 bitti (2026-08-27, commit'siz)**: `Listing Document` child table, `doc_meta.py` çıkarım (pypdf+stdlib, zip-bomb savunmalı), seçici index + sitemap ham-URL, DigitalDocument JSON-LD, satıcı formu + ürün bloğu, 3 denetim kuralı. Spec+plan: `docs/superpowers/{specs,plans}/2026-08-27-file-manager-seo*`. Rapor 109 (envanter bugün 0 — altyapı yatırımı, kullanıcı kararı). Audio 🚫 kapsam dışı (F1) |
| 16 | Media Library Search | 🔶 | Ad/metadata/filtre/facet ✅ (G-16-13). Kalan: OCR/semantic/vector arama — AI kararına bağlı |
| 17 | Categorization (Folder/Category/Tag + kaynak ayrımı) | ✅ | G-16-14; AI önerisi kural-tabanlı `suggest()` ile |
| 18 | Multi-Tenant | 🔶 | Depolama kotası + izolasyon ✅. Kalan: tenant-bazlı CDN/sitemap/robots policy — tek-pazar yeri mimarisinde şimdilik tüketicisi yok |

## B. Kritik mimari kararlar (MOGEM-620 "unknown unknowns")

| Karar | Durum |
|---|---|
| Asset metadata ≠ usage metadata | ✅ `Media SEO Override` |
| Stable asset identity ≠ delivery URL | ✅ içerik-hash + manifest |
| Raw file ≠ indexable landing/watch page | ✅ watch page (Dilim 5, gece) — /medya/v/<slug> |
| Asset usage graph | ✅ `usage.py` + `MediaUsage` |
| EXIF/privacy policy | ✅ `exif_vault` (public-strip-private-retain-v1) |
| Rights/license lifecycle | ✅ alanlar+audit+noindex; **lisans VARSAYILANI hukuk kararı bekliyor** (§11.5) |

## C. Aktif çalışma kuyruğu (2026-08-27 sabahı — gece koşusu sonrası)

| İş | Durum | Not |
|---|---|---|
| Video SEO dilimi (Dilim 4) | ✅ | 3 repoda `ahmet`'e merge'li (gece öncesi commit'ler) |
| Katalog tohumlama + migration + rapor 107 | ✅ | %99,5 katalog; migration 48/48 %53 tasarruf; rapor commit'siz |
| Watch page dilimi (Dilim 5, 6 görev) | ✅ kod tamam | TAMAMI COMMIT'SİZ worktree'de — sabah commit/revert kararı kullanıcıda; final inceleme tek bulgusu (index patch'i) fix dalgasında |
| Tamirat paketi | ✅ | 3 commit (gece öncesi) |
| İmaj rebuild'leri (kalıcılık) | ⏳ SABAH | Bilinçli ertelendi: imaj, commit/revert kararından SONRA pişmeli |
| File Manager SEO dilimi (A-15) | ✅ kod tamam | 6 görev + final review + fix dalgası bitti (67/67 backend testi); TAMAMI COMMIT'SİZ |
| Alpha/prod go-live | 🚫 kapsam dışı | Runbook hazır |

## D. Karar bekleyenler (insan kararı gerekiyor)

**2026-08-28 karar turu:** commit'i kullanıcı kendisi inceleyip atacak
(rehber: `docs/COMMIT-INCELEME-2026-08-28.md`); AI servisi ERTELENDİ;
lisans BOŞ kalır (hukuka sorulacak); alt zorunluluğu YAYINA ALIRKEN —
küçük dilim, commit kararından sonra yazılacak.

- [ ] AI servisi seçimi (alt/transcript üretimi) — maliyet + veri gizliliği (PM) — *2026-08-28: ertelendi*
- [ ] Lisans varsayılanı (`license_url`) — hukuk — *2026-08-28: boş kalır, hukuka sorulacak*
- [x] `alt` zorunluluğunun uygulanma anı — *KARAR (2026-08-28): ürün yayına alınırken; dilim commit sonrası*
- [ ] Skor ağırlıkları (ilk sürüm eşit; ölçümle ayar)
- [ ] Embed (YouTube/Vimeo) videolar için poster türetmesi (spec §12 amendment — takip görevi açılacak mı?)
- [x] **Katalog boyut backfill'i** — ✅ KOŞULDU (2026-08-28, kullanıcı onayı): doluluk %0,6→%94,6 (4.836 yazım); missing_dimensions ~1.100→0, LCP bulgusu 1.112→4, performance 49→98, overall 55→74; oversized(108)+ladder(68) ilk kez gerçek sinyal. Rapor 110 EK bölümü
