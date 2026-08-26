# MOGEM-620 — Medya SEO / Keşfedilebilirlik / AI Arama Katmanı — DURUM

**Plane:** MOGEM-620 (kaynak spec: "SEO for media & file manager" Google Doc'u)
**Amaç:** Plane API'ye sormadan ilerlemeyi buradan takip etmek. Bir madde
bittiğinde kutusunu işaretle + tarih düş. Kanıt kolonundaki yol/rapor,
"bitti" iddiasının doğrulanacağı yerdir.

**Son güncelleme:** 2026-08-26 (Claude oturumu)

Durum göstergesi: ✅ bitti · 🔄 şu an çalışılıyor · 🔶 kısmi (kalanı notta) ·
⏳ sırada/bekliyor · ❌ başlanmadı · 🚫 bilinçli kapsam dışı

---

## A. MOGEM-620 işlevsel gereksinimleri (Plane'deki 18 bölüm)

| # | Bölüm | Durum | Kanıt / Kalan |
|---|---|---|---|
| 1 | Asset Intelligence (MIME/probe, hash+dedup, EXIF policy, malware, bozuk dosya) | ✅ | `media/pipeline/core/{probe,dedup}.py`, `exif_vault.py` (GPS her koşulda strip + şifreli kasa), `av.py` |
| 2 | SEO Metadata Engine (alan seti + kullanım ezmesi + lisans/telif) | ✅ | TUR-135 Dilim 1; `media/seo.py` tek kapı, `Media SEO Override`. Kalan: title/caption/license ELLE doldurulur (tasarım gereği) |
| 3 | AI Metadata Generation | 🔶 | Şema + onay akışı hazır (`th_media_alt_ai`, rule/ai/human/edited); **AI servisi PM kararı bekliyor** (§11.7). Kural tabanlı alt üretimi ✅ (1.988 adres dolu) |
| 4 | Image SEO / Processing Engine (AVIF/WebP merdiveni, srcset, crop, LQIP) | 🔄 | Kod TAM (pipeline + delivery + manifest). **Katalog tohumlaması ŞU AN koşuyor** (~%20 → hedef 3.130 görsel); ölçüm raporu 107 bekliyor |
| 5 | Video SEO / Processing Engine | ✅ | **Bugün bitti** (Dilim 4): poster, VideoObject, video sitemap, transcript/VTT, panel+vitrin. Spec+rapor: `docs/superpowers/specs/2026-08-26-…`, `docs/reports/106-…`. Kapsam dışı: watch page, SeekToAction, embed poster (amendment §12) |
| 6 | Schema.org Engine | 🔶 | ImageObject+lisans beşlisi ✅, VideoObject ✅. Kalan: AudioObject/DigitalDocument (File Manager kapsamıyla birlikte, bkz. #15) |
| 7 | Sitemap + Indexability Engine | ✅ | Görsel ✅ + video ✅ sitemap; `seo_index.decide` tek karar noktası; private=404 ilkesi. News sitemap koşullu — tüketici yok |
| 8 | URL Management (stable ID ≠ delivery, canonical/derivative/CDN rolleri) | 🔶 | İçerik-adresli kimlik + 301 köprüsü + imzalı TTL ✅ (G-16-17/17a). Kalan: **raw file ≠ indexable landing/watch page** ayrımının sayfası (bkz. C-1) |
| 9 | Rendering + Performance SEO | 🔶 | Render ipuçları (gerçek ölçü, fetchpriority, lazy) ✅; `<picture>`/srcset manifest ✅. Kalan: decode-cost/CLS-riski gibi tam CWV ölçüm motoru (audit'te oversized/format fırsatı kuralları var, derin ölçüm yok) |
| 10 | Visual Search + Semantic/Entity katmanı | 🔶 | Perceptual hash + benzer arama ✅; **asset usage graph ✅** (`usage.py`/`refs.py`). Kalan: object/OCR/logo tanıma, embeddings, entity graph — AI servisi kararına bağlı |
| 11 | Multilingual Media SEO | 🔶 | alt/title/caption × 4 dil ✅. Kalan: transcript/subtitle çok dil (bilinçli tek dil — K3 kararı), locale-specific medya override |
| 12 | E-commerce / Product SEO (koşullu) | 🔶 | Listing↔görsel/video bağı + JSON-LD Product ilişkisi ✅. Kalan: SKU/GTIN association, görsel ROLLERİ (swatch/lifestyle/360) — ürün özelliği talebi yok |
| 13 | SEO Audit + Media SEO Score | ✅ | 12 görsel + 3 video kuralı, 7 alt kırılımlı skor, panel görünümleri (skor 53→81 ölçüldü) |
| 14 | Bulk Operations | ✅ | G-16-10 + toplu alt/boyut backfill'leri. Kalan (küçük): bulk localization |
| 15 | File Manager kapsamı (PDF/audio/doküman SEO) | ❌ | Hiç başlanmadı — ayrı dilim adayı |
| 16 | Media Library Search | 🔶 | Ad/metadata/filtre/facet ✅ (G-16-13). Kalan: OCR/semantic/vector arama — AI kararına bağlı |
| 17 | Categorization (Folder/Category/Tag + kaynak ayrımı) | ✅ | G-16-14; AI önerisi kural-tabanlı `suggest()` ile |
| 18 | Multi-Tenant | 🔶 | Depolama kotası + izolasyon ✅. Kalan: tenant-bazlı CDN/sitemap/robots policy — tek-pazar yeri mimarisinde şimdilik tüketicisi yok |

## B. Kritik mimari kararlar (MOGEM-620 "unknown unknowns")

| Karar | Durum |
|---|---|
| Asset metadata ≠ usage metadata | ✅ `Media SEO Override` |
| Stable asset identity ≠ delivery URL | ✅ içerik-hash + manifest |
| Raw file ≠ indexable landing/watch page | ⏳ landing page dilimi (C-1) |
| Asset usage graph | ✅ `usage.py` + `MediaUsage` |
| EXIF/privacy policy | ✅ `exif_vault` (public-strip-private-retain-v1) |
| Rights/license lifecycle | ✅ alanlar+audit+noindex; **lisans VARSAYILANI hukuk kararı bekliyor** (§11.5) |

## C. Aktif çalışma kuyruğu (2026-08-26 oturumu)

| İş | Durum | Not |
|---|---|---|
| Video SEO dilimi (A-5) | ✅ bitti | 3 repoda `ahmet`'e merge'li; **push bekliyor** |
| Katalog türev tohumlaması (A-4) | 🔄 koşuyor | 510+/3.130, 0 hata; 2 kök neden düzeltildi (kapalı profiller; aday sorgusu içerik-hash `ff73988`) |
| A-sınıfı optimize migration (48 dosya) | 🔶 kuru koşum validated | Gerçek koşum tohumlama sonrası |
| Ölçüm raporu 107 | ⏳ | Tohumlama bitince |
| İmaj rebuild'leri (kalıcılık) | ⏳ | En son — worker restart koşumu kesmesin |
| Tamirat paketi (creator @type, 9 bayat test, minor'lar, trash `..`) | 🔄 subagent'ta | |
| C-1: Medya landing/watch page dilimi | ⏳ sıradaki büyük dilim | slug/canonical tüketicisi |
| Alpha/prod go-live | 🚫 bu kapsamda değil | Runbook hazır: `docs/runbooks/media-go-live.md` |

## D. Karar bekleyenler (insan kararı gerekiyor)

- [ ] AI servisi seçimi (alt/transcript üretimi) — maliyet + veri gizliliği (PM)
- [ ] Lisans varsayılanı (`license_url`) — hukuk
- [ ] `alt` zorunluluğunun uygulanma anı (öneri: ürün yayına alınırken)
- [ ] Skor ağırlıkları (ilk sürüm eşit; ölçümle ayar)
- [ ] Embed (YouTube/Vimeo) videolar için poster türetmesi (spec §12 amendment — takip görevi açılacak mı?)
