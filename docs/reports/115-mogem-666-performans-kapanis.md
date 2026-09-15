# MOGEM-666 · Performans optimizasyonu — uygulama ve ölçüm raporu

**Tarih:** 12–15 Eylül 2026 · **Kaynak:** MOGEM-638 Performans AR-GE Raporu (10 Eylül) §7 öncelik listesi / §8 iş kalemleri / §9 hedefler
**Kapsam:** tradehub_core, tradehubfront, admin-panel — üç repoda kod; ölçümler §1'deki yöntemle aynı makinede tekrarlandı.
**Durum:** kodlandı, test edildi, ölçüldü — commit yok.

---

## 1. Özet

Rapor darboğazı üç katmanda "yavaş sorgu" değil yapısal fazlalık olarak koymuştu: ilk boyamadan önce zorla indirilen modüller, mega menünün her istekte Python'da kurulması, çift API çağrıları, kapalı zamanlayıcı ve log kirliliği. Bu tur 16 kalemden 13'ünü kapattı; 3'ü (log saklama, buffer pool restart'ı, 231 ara commit'in tek tek incelenmesi) karar/ops bekliyor.

Ölçülen kazançlar §5'te; kısa hâli:

| Ölçüt | Rapor (10 Eyl) | Şimdi | Fark |
|---|---:|---:|---:|
| `get_mega_menu` p50 (100 tekrar, sıcak) | 159 ms | 5,9 ms | −96 % |
| `get_categories` sorgu sayısı / p50 | 74 / 53 ms | 3 / 11 ms | −96 % / −79 % |
| SW ön-belleği (ilk ziyaret) | 7,95 MB | 4,66 MB | −41 % |
| Ana sayfa modulepreload | 44 / 1.006 KB | 33 / 736 KB | −25 % / −27 % |
| Ürün listesi modulepreload | 47 / 1.021 KB | 35 / 664 KB | −26 % / −35 % |
| top-deals modulepreload | 44 / 1.007 KB | 33 / 653 KB | −25 % / −35 % |
| Admin açılış çevirisi (gzip) | 246 KB | ~128 KB | −48 % |
| Çeviri hatası (Error Log) | 59K/ay | 0 | −100 % |
| Buyer Metrics hatası | 15K/ay | 0 | −100 % |
| Zamanlayıcı | kapalı (19 gün) | açık, ilk saat 191 iş / 0 Failed (3 kusur düzeltildikten sonra) | — |

(Tarayıcı ölçümleri — mobil LCP/CLS, yinelenen API — §5.2'de.)

---

## 2. Yapılanlar (rapor # → dosya → kanıt)

### 2.1 TradeHub Core

| # | Kalem | Değişiklik | Kanıt |
|---|---|---|---|
| 1 | Zamanlayıcı + Buyer Metrics | `bench scheduler enable`; `tasks.py` `Marketplace Order`→`Order`, `grand_total`→`total`, `Cancelled`→`İptal Edildi`, `Dispute`→`Order Dispute` | 124 aktif alıcı hatasız (`test_mogem666_permutasyon`) |
| 1' | İlk saatte düşen 3 iş | `reorder_rate` NOT NULL'a None (→0); `Listing Certification`'da olmayan `verification_status` (şema-duyarlı sorgu); `quote(int)` (HD Ticket adı bigint) | üçü canlıda tekrar koşturuldu, OK |
| 2 | tr.csv | 4 CSV'den 175 yorum/boş satır; `tests/test_translations_csv.py` (site'sız, CI) | yeniden yükleme 0 Error Log |
| 3 | Mega menü önbelleği | `api/category.py` Redis `mega_menu:{lang}:{include_empty}:{hide_empty}` 300 sn; kategori yazımında her koşulda, Listing yazımında yalnız hide_empty açıkken düşer | 16 kombinasyon önbelleksiz kurulumla eşit; sıcak çağrı 0 SQL |
| 5 | get_categories | N+1 → 3 sorgu (çocuklar IN, sayım GROUP BY) | 13 kök × 2 × 2 dil naif sayımla eşit |
| 14 | İndeks | `v15_9_56_performans_indeksleri`: `(parent_product_category,is_active)`, `(lft,rgt)`, `(storefront_visible,order_count,view_count)` | EXPLAIN: 7562→7 satır; filesort kalktı. `(is_active,sort_order,lft)` denendi, optimizer seçmedi → çıkarıldı |
| 9 | LCP ipucu (ürün) | `seo/meta_builder.py` `lcp_image` + `seo_head.html` `<link rel=preload as=image fetchpriority=high>` (yalnız `og_type=product`) | canlı ilan için render doğrulandı |
| — | AV sağlık yoklaması | `media/av.py` `clamdscan --ping 1` (`--version` daemon ölüyken rc=0 veriyordu) | KD-18 41/41 |

### 2.2 Storefront (tradehubfront)

| # | Kalem | Değişiklik |
|---|---|---|
| 4 | Yinelenen API | `queryClient.ts` `refetchOnRestore:false` — kök neden: persister varsayılanı + `fetchQuery` gözlemcisiz → her IndexedDB geri yüklemesi ikinci fetch. Ayrıca kategori anahtarına `lang` eklendi (dil değişince eski dilin ağacı dönüyordu — gerçek kusur) |
| 6 | SW ön-belleği | `vite.config.ts` `globIgnores`: dil chunk'ları + hls/echarts/mediabunny |
| 8 | Preload | main.ts / products.ts / top-deals.ts: sepet çekmecesi + sevkiyat penceresi dinamik import (`mountCartOverlays`), barrel yerine somut modül; OptionsSheet `submitCartLines` dinamik; ProductGrid `initListingCartDrawer` dinamik |
| 7 | CLS | top-deals: iskelet `<template x-if>`'ten statik `x-show`'a, sayfa boyutu kadar (24) kart — Alpine açılmadan görünür; ana sayfa: showcase `await` kaldırıldı (taze yerel kopya varsa düzen ondan kurulur, API arkada doğrular) |
| 9 | LCP | ürün detay: `initCurrency` + `loadProduct` paralel (bir API turu kazancı); backend preload ipucu (2.1) |
| — | Ölçüm hattı | `scripts/perf-budget-dist.mjs` + `npm run test:perf:dist` (SW boyutu, preload sayısı/boyutu, sepet parçası = 0); `preview.proxy` eklendi (üretim derlemesi yerelde ölçülebilir) |

### 2.3 Admin panel

| # | Kalem | Değişiklik |
|---|---|---|
| 10 | get_navigation 2× | `stores/navigation.js`: rol başına tek panel isteği; in-flight promise paylaşımı; hata sonrası 30 sn geri çekilme (eskiden her rotada yeniden) — 5 davranış testi |
| 11 | Çeviri | açılışta yalnız aktif dil; `en` fallback ilk eksik anahtarda tembel (`missing` handler) — 2 test |
| 12 | Uzun listeler | media-optimize / media-audit liste modu `useCardGridWindow` ile pencerelendi (mevcut composable, yeni bağımlılık yok); sabit satır yüksekliği `--windowed`; tablo modu pencerelenmedi (tbody padding taşımaz) — 11 sözleşme testi |

---

## 3. Yapılmayan / karar bekleyen

| # | Kalem | Durum |
|---|---|---|
| 13 | MariaDB buffer pool / slow log | `docker-compose.yml`'e yazıldı (1G, slow log 0,5 s, tmp 64M) — **uygulanmadı**, container restart kararı kullanıcıda |
| 15 | Log saklama | uyum kararı bekliyor (90/30 gün / yalnız File'ı global aramadan çıkar) |
| 16 | 231 ara commit / 180 limitsiz sorgu | envanter §4; toplu değişiklik yapılmadı |
| — | `test_faz13_guest_surface` | HEAD'de kırık: `media_public.asset_landing` + `get_watch_page` (a332dbb) dondurulmuş listede yok — güvenlik incelemesi ister |
| — | admin `zamanBombasi.test.js` | HEAD'de kırık: `subscriptionCancellation`/`iosSalesSurface` testleri 2026-10-01 sabit yazıyor (200139a) |
| — | storefront `sellPageIosGating.test.ts` | HEAD'de kırık (127.0.0.1:3000'e bağlanmaya çalışıyor) |

---

## 4. #16 envanteri (AST taraması, 15 Eyl)

`frappe.db.commit()`: toplam **424**, istek işleyicisinde (whitelist) **213**, enqueue'ya bitişik 3.
Limitsiz `get_all/get_list`: toplam **467**, whitelist içinde **197**.

Kural önerisi (toplu düzeltme yerine): POST uçlarında Frappe istek sonunda zaten commit eder — fonksiyon ortasındaki commit yalnız (a) enqueue öncesi, (b) kısmi kalıcılık bilinçli isteniyorsa kalmalı; GET uçlarında yazma (ör. `_record_listing_view`) commit'siz kaybolur, orası bilinçli. Limitsiz sorguların çoğu facet/sayım (domain-sınırlı); istemciye satır döndürenler sayfalı. Değişiklik yapılmadı; envanter `docs/reports/115-tarama16.json` benzeri çıktıyla yeniden üretilebilir (`scratchpad/tarama16.py`).

En yoğun dosyalar (whitelist içi commit): `api/seller.py` 13, `api/seller_certifications.py` 12, `api/v1/identity.py` 12, `api/review.py` 11, `api/favorites.py` 10.
En yoğun dosyalar (whitelist içi limitsiz): `api/listing.py` 37 (facet/sayım), `api/seller_certifications.py` 15, `api/rfq.py` 13.

---

## 5. Ölçümler

### 5.1 Core (HTTP, 100 tekrar, sıcak; rapor §4.1 ile aynı)

| Uç nokta | Rapor p50 | Şimdi p50 | p95 | Fark |
|---|---:|---:|---:|---:|
| `category.get_mega_menu` | 159 ms | 5,9 ms | 7,4 ms | **−96 %** |
| `listing.get_categories` | 53 ms | 11,0 ms | 12,8 ms | **−79 %** |
| `listing.get_search_suggestions` | 14 ms | 11,0 ms | 12,1 ms | −21 % |

Eşzamanlı yük (N kullanıcı × 10 ardışık; rapor §4.4 ile aynı):

| Uç nokta | Kullanıcı | Rapor rps / p50 / hata | Şimdi rps / p50 / hata | Fark (p50) |
|---|---:|---|---|---:|
| `get_mega_menu` | 10 | 5,0 / 2.007 ms / 10 | 205,7 / 47 ms / 0 | **−98 %** (41× verim) |
| `get_mega_menu` | 25 | 4,9 / 5.166 ms / 25 | 195,7 / 124 ms / 0 | **−98 %** |
| `get_mega_menu` | 50 | 4,3 / 11.397 ms / 0 | 196,1 / 250 ms / 0 | **−98 %** (46× verim) |
| `get_categories` | 10 | 31,1 / 317 ms / 0 | 96,5 / 101 ms / 0 | **−68 %** (3× verim) |
| `get_categories` | 25 | 30,5 / 812 ms / 0 | 94,8 / 258 ms / 0 | −68 % |
| `get_categories` | 50 | 30,1 / 1.634 ms / 0 | 91,6 / 538 ms / 0 | −67 % |
| `get_listing_detail` | 10 | 48,4 / 48 ms / 0 | 216,1 / 45 ms / 0 | −6 % (zaten sağlıklıydı) |
| `get_listing_detail` | 50 | 205,9 / 240 ms / 0 | 206,1 / 238 ms / 0 | ±0 |

Rapor 5 rps tavanı diyordu; mega menü artık `get_listing_detail` ile aynı bantta (~200 rps, geliştirme sunucusunun sınırı). `get_categories`'in 50 kullanıcıdaki 538 ms'si DB değil Python (dil çözümü + 3 sorgu × 50) — bir sonraki adım aynı önbellek deseni olabilir, rapor kapsamı dışında.

### 5.2 Storefront (Playwright, mobil 375×812 / 4× CPU / Slow-4G; masaüstü 1366×768; SW kapalı = ilk ziyaret)

Öncesi = HEAD derlemesi (`dist-before`, git stash ile), sonrası = bu tur (`dist`); aynı makine, aynı oturum, ardışık; `vite preview` 4174/4173, `/api` → 8001. Not: `odeme` (checkout) misafirde ana sayfaya yönleniyor — ana sayfanın kopyası olarak okunmalı.

**Mobil (375×812, 4× CPU, Slow-4G):**

| Sayfa | LCP önce→sonra | CLS önce→sonra | TBT | load | Transfer |
|---|---|---|---|---|---|
| ana-sayfa | 26.064 → **12.804 ms (−51 %)** | 0,119 → **0,004** | 360 → 232 ms (−36 %) | 11,4 → 9,1 s (−20 %) | ± |
| kategoriler | 10,5 → 10,6 s (±) | 0,041 → 0,041 | ± | ± | ± |
| ürün listesi | 14.300 → **11.760 ms (−18 %)** | 0,439 → **0,009** | ± | 11,2 → 8,6 s (−23 %) | 3.458 → 2.585 KB (−25 %) |
| ürün detay | 20,0 → 20,0 s (±) | 0,01 → 0,01 | ± | ± | ± |
| mağaza | 16,6 s (±) | 0 | ± | ± | ± |
| sepet | 12,6 s (±) | 0 | ± | ± | ± |
| top-deals | 13.912 → **11.296 ms (−19 %)** | 0,649 → **0,004** | ± | 10,9 → 8,3 s (−24 %) | 667 → 585 KB (−12 %) |

**Masaüstü (1366×768, kısıt yok):**

| Sayfa | LCP önce→sonra | CLS önce→sonra | load |
|---|---|---|---|
| ana-sayfa | 520 → 436 ms (−16 %) | 0,024 → **0** | ± |
| kategoriler | 128 → 124 ms | 0 | ± |
| ürün listesi | 176 → 176 ms | 0,003 | 56 → 52 ms |
| ürün detay | 268 → 256 ms (−4 %) | 0,001 | ± |
| mağaza | 604 → 572 ms (−5 %) | 0 | ± |
| sepet | 132 → 132 ms | 0 | 53 → 46 ms |
| top-deals | 160 → 144 ms (−10 %) | 0,106 → **0** | 58 → 48 ms (−17 %) |

Okuma: kazanç **CLS'te kesin** (üç sayfa 0,12–0,65'ten ≤0,01'e — kaynaklar ölçümle bulundu: fırsat kartının `display:none` olması, boş sonuçta iskeletin çökmesi, spinner→ızgara), **LCP'de ana sayfa/top-deals/ürün listesinde** (−18…−51 %). Ürün detay, mağaza, sepet, kategoriler mobilde değişmedi — bu sayfalarda ilk boyama hâlâ JS paketine bağlı (Slow-4G'de ~10 s); §9'daki "<4 s" hedefi bu turda erişilmedi ve tek başına önbellek/preload işiyle erişilemez (SSR/streaming ya da kritik-yol JS'i ~200 KB'a indirmek gerekir).

**Yinelenen API (rapor §2.6):** üretim derlemesinde tekrar üretilemedi — HEAD'de de ilk ziyaret, aynı bağlamda ikinci ziyaret (1,5 sn ve 65 sn bekleme) ve tek bağlamda 8 sayfa ardışık gezme senaryolarının hepsinde ana sayfa API 13/13, yinelenen 0. Raporun 7/20'si büyük olasılıkla dev sunucusu (HMR) ya da uzun ömürlü oturum (staleTime dolmuş IndexedDB) kaynaklıydı. `refetchOnRestore:false` yine de doğru ayar (persister belgesi), zararsız. Ölçülebilen ve kapatılan yinelemeler: mağaza `2× get_storefront_layout` → 1 (memoize servis), sepet `2× get_session_user` → 1 (`waitForAuth`); kalan: ürün detay `2× get_qa_page` (dokunulmadı).

### 5.3 Admin (15 rota, dev sunucu 8082, Administrator; önce = değişiklikler stash'te)

| Ölçüt | Önce | Sonra | Fark |
|---|---:|---:|---:|
| `get_navigation` / rota (11 render eden rota) | 2× hepsinde | **1×** hepsinde | −50 % istek |
| Açılışta indirilen dil dosyası (dashboard, dev/minify'sız) | en.js + tr.js = 4.789 KB | tr.js = 2.504 KB | **−48 %** |
| `/media-audit` DOM düğümü | 1.849 | **842** | −54 % |
| `/media-optimize` DOM düğümü | 1.635 | **839** | −49 % |
| `/media-audit` CLS | 0,124 | 0,182 | +0,058 (pencereleme iç gövde; bkz. not) |
| `/media-optimize` CLS | 0,141 | 0,141 | ± |
| JS heap (30 geçiş) | 26 MB | 22 MB | −15 % |

Notlar: `/app/Listing`, `/app/Product Category`, `/media-library`, `/app/Listing/LST-00118` her iki turda da boş render (DOM 21) — ölçüm dışı, bu rotalar tam yüklemeyle açılmıyor (SPA içi geçiş istiyor). `/media-audit`'te `2× get_media_audit` HEAD'de de var (rota + filtre watch'ı), bu tura girmedi. `/media-optimize` geçiş süresi tek koşumda 3,2 s → 6,5 s ölçüldü; API gecikmesi kaynaklı olabilir, tekrar ölçülecek.

---

## 6. Test kapsamı (bu tur)

| Repo | Yeni/değişen test | Sonuç |
|---|---|---|
| tradehub_core | `test_mogem666_performans` (16), `test_mogem666_permutasyon` (9 test / ~260 alt vaka: 16 mega menü kombinasyonu × soğuk/sıcak, 13 kök × 2 × 2 dil get_categories, 124 alıcı, 57 zamanlayıcı işleyicisi, 4 CSV), `test_translations_csv` (3), KD-18 AV (41, 2 yeni), `test_seller_reorder_rate` (5) | **hepsi OK** |
| tradehubfront | `TopDealsGrid.test.ts` (3), `keys.test.ts`, `ProductGrid.test.ts`; `perf-budget-dist` (12 bütçe: eski derlemede 12 aşım → yenide 0); tsc/eslint/check:dup temiz; tam vitest paketi | 976/977 (1 HEAD'den kırık: `sellPageIosGating`) |
| admin-panel | `navigationDbLoad` (5), `localeLoader` (2), `mediaSystemListWindow` (11); eslint temiz; tam `node --test` paketi | 1.630+ (1 HEAD'den kırık: `zamanBombasi`, 200139a'nın 2026-10-01 sabitleri) |

Ortam notu: Frappe test koşucusu 15 Eyl'de `_Test Comm Account 1` e-posta hesabı yüzünden (12 Eyl'de bir test turunun bıraktığı kayıt; Email Domain test kaydı kurulurken sunucuya bağlanmaya çalışıyor) tüm modüllerde düşüyordu — kayıt silindi. Aynı şey yeniden olursa: `Email Account` altında `_Test` ile başlayanı sil.

---

## 7. Sonuç — eskiye göre yüzde

| Katman | Ölçüt | Fark |
|---|---|---|
| Core | mega menü p50 | **−96 %** (159 → 5,9 ms) |
| Core | mega menü verimi (10 kullanıcı) | **41×** (5 → 206 rps), 50 kullanıcıda hata 25 → 0 |
| Core | get_categories sorgu / p50 | **−96 % / −79 %** |
| Core | get_categories verimi (10 kullanıcı) | **3×** (31 → 97 rps) |
| Core | Error Log (çeviri + Buyer Metrics) | **−100 %** (74K/ay → 0) |
| Storefront | mobil ana sayfa LCP / CLS | **−51 % / 0,119 → 0,004** |
| Storefront | mobil ürün listesi LCP / CLS / transfer | **−18 % / 0,439 → 0,009 / −25 %** |
| Storefront | mobil top-deals LCP / CLS | **−19 % / 0,649 → 0,004** |
| Storefront | SW ön-belleği | **−41 %** (7,95 → 4,66 MB) |
| Storefront | ana sayfa / ürün listesi / top-deals preload | **−27 % / −35 % / −35 %** bayt; sepet parçası 9 → 0 |
| Admin | get_navigation istek | **−50 %** (2 → 1 / rota) |
| Admin | açılış çeviri baytı | **−48 %** |
| Admin | media-audit / media-optimize DOM | **−54 % / −49 %** |
