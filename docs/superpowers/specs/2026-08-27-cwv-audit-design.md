# CWV / Render Performans Denetim Kuralları — Tasarım (Dilim 7)

**Plane:** MOGEM-620 §9 (Rendering + Performance SEO) kalanı
**Durum haritası:** `docs/MOGEM-620-DURUM.md` A-9
**Tarih:** 2026-08-27 · **Durum:** Onaylandı (kullanıcı: "İkisini de sırayla" —
A-9 → A-14 otonom akış) · **Not:** commit yasağı sürüyor — worktree'de birikir.

---

## 1. Gerçeklik ölçümü ve işin doğası

Keşif (2026-08-27): denetimde CWV'ye komşu 4 kural var (`missing_dimensions`,
`oversized_image`, `missing_responsive_variants`, `missing_poster`) ama
**`Media Rendition`'ın format/profil/servis-edilebilirlik verisi audit'e hiç
bağlı değil** — "hiç türev var mı" ikilisinden ibaret. AVIF/WebP üretimi canlı
(policy `product-image.json`), `missing_profiles` hesabı manifest API'de hazır,
RUM örneklemesi (`Media RUM Sample`: LCP/CLS/INP + `lcp_format`/`lcp_profile`)
yazılıyor. Bu dilim, var olan bu sinyalleri kurallara bağlar — yeni ölçüm
motoru İCAT ETMEZ.

## 2. Kararlar

| # | Karar | Gerekçe |
|---|---|---|
| C1 | Yalnız **mevcut veriden** kural; RUM verisi kural DEĞİL, rapor 110'da ölçüm özeti | Alan verisi dosya-bazlı suçlamaya uygun değil (route-bazlı) |
| C2 | Yeni kurallar **batch katmanında** (`_technical_findings`) — `oversized_image` emsali; `audit_file` tekil-yol asimetrisi bilinçli olarak sürer (mevcut, belgeli) | Rendition sorguları toplu; tekil yolda N+1 üretir |
| C3 | Beklenen format/profil kümesi **policy dosyasından okunur** (`policy/slots/product-image.json` → `profiles[].formats`, profil adları); koda kopyalanmaz | Tek kaynak; policy değişince kural kendiliğinden uyar |
| C4 | `sizes` kuralı YOK — `SIZES_TABLE` bilinçli boş, kural her görselde tetiklenirdi (sinyal 0) | YAGNI |
| C5 | LCP adayı = `Listing.primary_image` (galeri index 0 sözleşmesi); `_seo_audit_adaylari` catalog SQL'i primary/galeri ayrımını korur hale gelir | Ayrım bugün UNION'da kayboluyor; tek SELECT değişikliği |
| C6 | Yeni skor boyutu YOK — kurallar mevcut `performance` (+1 `technical_health`) boyutuna işler | 8 boyut yeter; ağırlık kararı zaten D listesinde |
| C7 | `SCOPE_CACHE_KEY` sürümlenir (`…_v2`) — kural seti değişince 1 saatlik bayat cache dönmesin | Keşifte tespit edilen boşluk |
| C8 | "Sayfada gerçekten fetchpriority basıldı mı" KAPSAM DIŞI — vitrin ayrı repo, denetim yalnız üretilebilir sinyali doğrular | Ölçüm sınırı dürüstlüğü |

## 3. Yeni kurallar (5)

Hepsi `_technical_findings` içinde; `_KURAL_BOYUT`a eklenir. Görsel-sınıfı
dosyalarla sınırlı (video/doküman uzantıları kapsam dışı; mevcut
`rendition_assets` ön-yüklemesi genişletilerek format/profil/state/gate
alanları da çekilir — sorgu SAYISI artmaz, alan listesi genişler).

| Kod | Sev | Boyut | Tetik |
|---|---|---|---|
| `missing_modern_format` | warn | performance | Asset'in servis edilebilir (`state=ready` + `benefit_gate_passed=1`) türevleri arasında policy'nin o slot için beklediği modern formatlardan (avif/webp) HİÇ yok |
| `incomplete_rendition_ladder` | warn | performance | Kaynak ölçüsünün izin verdiği (upscale beklenmez — `th_media_width` basamağın genişliğinden büyükse "beklenir") policy profillerinden üretilMEMİŞ olanlar var; detayda eksik profil adları |
| `unserved_renditions` | warn | technical_health | Türev(ler) üretilmiş ama HİÇBİRİ servis edilebilir değil (hepsi gate-fail/ready-değil) — "üretildi ama boşa gitti" |
| `aspect_ratio_mismatch` | warn | performance | `th_media_width/height` oranı ile en büyük **oran-koruyan** (policy'de `fit != "pad"`) servis edilebilir türevin oranı arasındaki fark policy `ratio_tolerance` (0.02) dışında — CLS riski. Pad-fit (kare dolgulu) profiller karşılaştırmaya GİRMEZ; hiç oran-koruyan türev yoksa kural susar. *(Düzeltme 2026-08-27: T2 review'ünde repro'lu yanlış-pozitif bulgusu üzerine — ilk metin "en büyük ready türev" diyordu)* |
| `lcp_candidate_unoptimized` | warn | performance | Dosya bir ilanın **primary_image**'ı VE (modern format yok VEYA `missing_dimensions`) — LCP adayında bu eksikler kritik; detay alt nedenleri sayar. Bayt tarafı `oversized_image`'a bırakılır (çifte ceza yok) |

`missing_responsive_variants` (mevcut) dokunulmaz — "hiç türev yok" kaba
kuralı kalır; `incomplete_rendition_ladder` onun ince kardeşidir (türev var
ama merdiven delik). Aynı dosyada ikisi birden tetiklenmez (biri "hiç",
diğeri "eksik").

## 4. LCP adayı tespiti (C5)

`api/media_admin.py::_seo_audit_adaylari` catalog SQL'i iki kümeyi ayrı
döndürür: `primary_urls` (Listing.primary_image, storefront_visible=1) ve
galeri URL'leri; `audit_batch`e mevcut imzayla birleşik liste gider, ek
olarak `_technical_findings`'e `primary_urls: set[str]` parametresi taşınır
(varsayılan boş set — dış çağıranlar kırılmaz). `lcp_candidate_unoptimized`
yalnız bu kümede değerlendirilir. `recent`/`all` scope'larında primary
kümesi yine tek ek sorguyla kurulur (N+1 yok).

## 5. Ölçüm — rapor 110

- Canlı katalogda `audit_media_seo(scope=catalog)` koşumu: yeni 5 kuralın
  tetiklenme sayıları + performance/technical_health skor değişimi
  (önce/sonra).
- RUM özeti (kural değil, ölçüm): `Media RUM Sample`dan metrik başına
  rating dağılımı (good/needs-improvement/poor) ve `lcp_format` kırılımı —
  örneklem azsa "örneklem yetersiz" diye dürüstçe yazılır.

## 6. Yüzeyler

Panel: denetim görünümü kural kodlarını mevcut sözleşmeyle listeler; yeni
kodlar için tr/en etiket eklenir (panelde kod→etiket haritası varsa — T4'te
keşfedilip yoksa hiç dokunulmaz). Yeni panel bileşeni YOK. Vitrin işi YOK.

## 7. Test stratejisi

- Kural birimleri: sahte rendition satırlarıyla `_technical_findings`
  doğrudan (mevcut `TestTopluDenetim` deseni); policy okuyucu için gerçek
  `product-image.json` fixture olarak kullanılır (repo içi dosya).
- `_seo_audit_adaylari` primary ayrımı: 2 ilanlı fixture (primary + galeri).
- Cache key sürümleme: eski anahtarla yazılmış cache'in okunMAdığı.
- Regresyon: `test_media_seo_pipeline` tam modül + `_KURAL_BOYUT` bütünlük
  iddiası (test_media_watch'taki mevcut assert güncellenir).

## 8. Kapsam dışı

Gerçek HTML/fetchpriority doğrulaması (C8) · `sizes` kuralı (C4) · RUM'dan
kural üretme (C1) · decode-cost için yeni eşik icadı (`oversized_image`
12M px kalır) · listing-seviyesi toplu skor katmanı · CSS kutu ölçüleri.

## 9. Kabul kriterleri

1. Beş yeni kural `_KURAL_BOYUT`ta; batch denetimde tetikleniyor, testli.
2. Beklenen format/profil kümesi policy dosyasından okunuyor — kodda format
   listesi kopyası yok.
3. Rendition ön-yüklemesi sorgu SAYISINI artırmıyor (alan listesi genişler).
4. `lcp_candidate_unoptimized` yalnız primary_image dosyalarında tetikleniyor;
   galeri görseli yanlış pozitif üretmiyor (testli).
5. Cache key sürümlendi; eski cache okunmuyor.
6. Rapor 110: kural tetiklenme sayıları + skor önce/sonra + RUM özeti.
7. Mevcut 27 kural ve skorlar regresyonsuz (tam modül yeşil).

## 10. Uygulama sırası (plan iskeleti)

1. Policy okuyucu + rendition ön-yükleme genişletmesi + `missing_modern_format`
   + `incomplete_rendition_ladder` + cache key sürümleme
2. `aspect_ratio_mismatch` + `unserved_renditions`
3. Primary ayrımı (`_seo_audit_adaylari`) + `lcp_candidate_unoptimized`
4. Panel etiket keşfi/eklemesi + rapor 110 ölçümü
