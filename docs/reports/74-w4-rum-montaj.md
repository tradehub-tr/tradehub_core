# 74 — T-123 kapanışı: RUM storefront montajı (W4)

**Tarih:** 2026-08-20 · **Kapsam:** `tradehubfront` (web-vitals kurulumu,
`src/lib/rum/**`, giriş dosyalarına boot import'u) — `rum.py`/backend'e
DOKUNULMADI.
**Görev:** RUM zincirinin son halkası. Zincirin geri kalanı CANLI (raporlar
63 ve 72: uç + DocType + hız sınırı + saatlik toplama + `/metrics` serileri);
eksik olan tek şey toplayıcının storefront'a monte edilmesiydi.

---

## 0. Tek cümlelik sonuç

`web-vitals@6.1.1` kuruldu, toplayıcı 72 girişin TAMAMINA çift-başlatma
korumalı ortak boot ile monte edildi, fiziksel `/pages/*.html` yolları
istemci tarafında pretty şablonlara normalize edildi ve **gerçek tarayıcı
vitals olayları canlıda ölçüldü**: `Media RUM Sample`'da LCP/TTFB/CLS
satırları, route kırılımı `/urunler` ve `/sepet` ile (§5).

## 1. Kurulum + lockfile (ölçüldü)

- `npm install web-vitals@^6 --save` → `web-vitals@6.1.1` (Apache-2.0,
  0 bağımlılık). `package.json` + `package-lock.json` (lockfileVersion 3)
  senkron.
- Lockfile doğrulaması KONTEYNERDE: `docker run … node:22-alpine npm ci
  --dry-run --ignore-scripts` → **"added 1122 packages", hata yok.**
  (Lockfile bu görevden hemen önce onarılmıştı; bozulmadı.)

## 2. Montaj: MPA girişleri ve boot yerleşimi (ölçüldü)

- Giriş sayısı ÖLÇÜLDÜ: `vite.config.ts` girişleri `fast-glob('**/*.html')`
  ile toplanır; HTML'lerden çıkarılan benzersiz script girişi **72**
  (`src/main.ts` + 71 × `src/pages/*.ts`). `src/pages/` altındaki 4 dosya
  giriş DEĞİL (testler + `dashboardShell.ts` yardımcı) — onlara eklenmedi.
- Ortak bootstrap YOK (ölçüldü: `../style.css` bile yalnız 62 giriş­te).
  Bu yüzden yeni **`src/lib/rum/boot.ts`** yazıldı ve 72 girişin hepsine
  side-effect import eklendi (`main.ts`'teki eski yorumlu blok bu import'la
  değiştirildi).
- Çift-başlatma koruması İKİ katman: `startRum` modül-tekil idempotent
  (index.js) + `globalThis.__tradehubRumBooted` bayrağı (boot.ts — bundler
  modülü iki chunk'a kopyalasa bile tek kayıt). Birim testi: §6.
- Örneklem `sampleRate: 0.1` (rapor 60 §8) boot içinde tek yerde.
- TS köprüsü: `src/lib/rum/index.d.ts` (vendor JS'in TS'ten kullanılan
  yüzeyi; tsconfig `allowJs` içermiyor).

## 3. Yol ↔ şablon eşleşmesi (ölçüldü) ve normalizasyon kararı

Toplayıcının gördüğü `location.pathname` İKİ biçimde gelir (ölçüldü):

1. **Pretty URL** — nginx `rewrite … break` tarayıcı adresini değiştirmez:
   `/urunler`, `/urun/x`, `/sepet` … `routeTemplate()` ile zaten eşleşir.
   (Canlı tarayıcıda doğrulandı: `/urunler`'de `location.pathname ===
   "/urunler"`.)
2. **Fiziksel dosya yolu** — iç bağlantıların önemli kısmı hâlâ dosyaya
   gider (ölçüldü: `FooterLinks`, `MegaMenu`, `BottomNav`, `CategoryGrid`,
   `ProductSalesRank`… `/pages/products.html?cat=x`). Bunların HEPSİ
   `other` kovasına düşerdi → kırılım oluşmazdı.

**Karar:** sunucu şablonlarına dokunmadan (yasak — `rum.py` başka sahiplik)
istemci tarafına normalizasyon eklendi:

- YENİ `src/lib/rum/routePhysical.js` — `normalizePhysicalPath()`:
  fiziksel yol → beyaz listedeki pretty karşılığı. Harita yalnız
  `ROUTE_TEMPLATES` üyelerini kapsar: `/index.html→/`,
  `products.html→/urunler`, `cart.html→/sepet`,
  `product-detail.html→/urun/:slug`, `categories.html→/kategori/:slug`,
  `brand.html→/marka/:slug`, `seller-storefront.html→/magaza/:code`;
  ayrıca `/en` dil öneki soyulur. Beyaz liste dışı fiziksel sayfalar
  sunucu sözleşmesindeki gibi `other` kalır.
- `context.js`'te tek işaretli VENDOR EKİ: `collectContext()` yolu şablona
  indirgemeden ÖNCE normalize eder; `routeTemplate()` sunucu
  `rum.route_template()` ile **birebir kaldı**.
- `categories.html` notu: nginx bu dosyayı hem `/kategoriler` (beyaz
  listede yok → other) hem `/kategori/:slug` için servis eder; ölçülen iç
  bağlantıların baskın biçimi `?cat=<slug>` taşıdığından dosya
  `/kategori/:slug` sayıldı (gerekçe routePhysical.js başlığında).

## 4. Doğrulama sayıları (hepsi koşuldu)

| Kontrol | Sonuç |
|---|---|
| `npx tsc --noEmit` | 0 hata |
| `npx vitest run` | **6 failed / 265 passed** — 6 bilinen kırık AYNI 3 dosyada kaldı (messages, ProductBuyBox, ProductOrderPanel); +15 yeni test geçiyor |
| `npx eslint` (dokunulan dosyalar) | 0 |
| `npm run build` | 0 (PWA precache 220 entry) |
| `docker compose build storefront` | 0 — NOT: cache'li ilk deneme `npm ci`'da düştü, `--no-cache` ile temiz geçti (eski katman); imaj `istoc/storefront:local` |
| `docker compose up -d storefront` | Up; `http://istoc.localhost/` ve `/urunler` → 200 |

## 5. Uçtan uca canlı ölçüm (kanıt)

1. **Bundle kanıtı (curl):** canlı sayfanın assets'inde
   `__tradehubRumBooted`, `sampleRate:.1`,
   `tradehub_core.api.rum.collect` ve normalizasyon haritası
   (`"/pages/products.html":"/urunler"`) `style-OrupyWf_.js`'te;
   `web-vitals.attribution-D_TVJc2E.js` chunk'ı 200 dönüyor (lazy).
2. **Sentetik POST (curl):** collect ucuna sayfanın göndereceği gövdeyle
   POST → `{"ok":true}`; DocType satırı: `2rfcl09d54` (LCP 1234.5,
   route `/urunler`, rating good, 08:17:37).
3. **GERÇEK tarayıcı vitals olayı ÖLÇÜLDÜ** (headless Chrome,
   agent-browser): `/urunler` ziyareti → `window.__tradehubRumBooted ===
   true`; sayfadan ayrılınca sendBeacon flush → `Media RUM Sample`'da
   gerçek satırlar: **LCP 160.0 / TTFB 13.3 / CLS 0.0196, route
   `/urunler`** (08:20:25, session_bucket ad889cd435b5). Devamında
   `/sepet` (LCP 108) ve **fiziksel yol testi**: tarayıcı
   `/pages/products.html?cat=test` adresindeyken üretilen olaylar DB'ye
   **route `/urunler`** olarak düştü (08:21:06) — normalizasyon canlıda
   çalışıyor.
   - Dürüstlük notu: %10 örneklem DETERMİNİSTİK (token hash'i,
     `decide()`); tarayıcı oturumuna, örnekleme GİREN önceden hesaplanmış
     bir token `sessionStorage`'a konularak olayların gönderilmesi
     garanti edildi. Metrik değerleri gerçek `web-vitals` ölçümleridir.

## 6. Yeni testler

- `src/lib/rum/boot.test.ts` — 4 test: import'ta tek başlatma + %10 oran,
  ikinci `bootRum()` null, chunk kopyası taklidi (`vi.resetModules`) ile
  tek kayıt, bayrak silinince yeniden başlatma.
- `src/lib/rum/routePhysical.test.ts` — 11 test: 7 fiziksel→şablon
  eşlemesi, beyaz liste dışı `other`, pretty geçirgenlik, `/en` soyma
  (`/envanter` soyulmaz), boş/bozuk girdi.
- Destek bildirimleri: `routePhysical.d.ts`, `context.d.ts` (kısmi).

## 7. Dokunulan dosyalar

- `tradehubfront/package.json` + `package-lock.json` (yalnız web-vitals)
- `tradehubfront/src/main.ts` (yorumlu blok → boot import) + 71 sayfa
  girişine 2 satır (yorum + import)
- `tradehubfront/src/lib/rum/`: YENİ `boot.ts`, `boot.test.ts`,
  `routePhysical.js`, `routePhysical.test.ts`, `index.d.ts`,
  `routePhysical.d.ts`, `context.d.ts`; `context.js`'te 2 işaretli
  VENDOR EKİ (import + normalize çağrısı)
- Yasaklara uyuldu: `rum.py`, admin-panel, nginx/docker yapılandırması,
  mevcut test dosyaları, `src/components/**` değişmedi.

## 8. Açık kalanlar

- Süre/performans iddiası YOK — bundle büyüme etkisi ölçülmedi
  (web-vitals lazy chunk ~5.6 KB gzip, rapor 60 §11 denetimi).
- `sampleRate: 0.1` doküman değeri; ilk gerçek trafikten sonra kova
  başına örnek sayısına bakılıp güncellenmeli (sampling.js notu).
- `/kategoriler` pretty listesi sözleşme gereği `other` — sunucu şablonu
  genişletilirse `routePhysical.js` haritası gözden geçirilmeli.
