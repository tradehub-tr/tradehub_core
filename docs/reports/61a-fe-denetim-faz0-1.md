# 61a — FE Denetim: Faz 0 ve Faz 1 (T-000…T-019)

**Kapsam:** Salt okunur denetim. Hiçbir dosya değiştirilmedi. Amaç: yukarıdaki 20 görevin
**frontend payının** kod tabanında gerçekten yapılıp yapılmadığını, kanıt (dosya:satır) ile
tek tek doğrulamak. Panonun `10-faz0-codebase-arastirma.html` ve `20-tasarim-desenleri.html`
sayfaları WebFetch ile çekildi; T-015'in tam metni bu sayfada bulunamadığı için ayrıca
`21-faz1-arge-gorevleri.html` çekilerek T-010…T-019'un tam metni doğrulandı.

`docs/reports/` altındaki önceki raporlar (özellikle `33-dogrulama-faz0-3.md` ve
`57a-durum-faz0-3.md`) yalnız **ipucu** olarak kullanıldı; her iddia bu oturumda kodda
bağımsız olarak yeniden doğrulandı (dosya var mı, satır numarası tutuyor mu, import/kullanım
zinciri var mı).

| Görev | Rol | FE payı | Durum | Kanıt (dosya:satır) | Eksik olan |
|---|---|---|---|---|---|
| T-000 | Analiz | Yok — ortam/altyapı envanteri | FE-DIŞI | — | Frappe sürümü, Python/Node, libvips/FFmpeg, RQ worker, donanım — hiçbiri FE kod/iş konusu değil. |
| T-001 | Analiz | Var — Vue upload bileşenlerinin taranması açıkça isteniyor | **TAM** | `docs/reports/00-upload-slot-envanteri.md` §4 "Tablo C" 25 admin-panel FE slotu listeliyor, her biri dosya:satır ile. Bağımsız doğrulandı: `admin-panel/frontend/src/views/doctype/DocTypeFormView.vue:2263` (`uploadFile`, gerçek: satır 2263'te fonksiyon başlıyor) · `admin-panel/frontend/src/components/upload/ProfileImageDropzone.vue:122-123` (`accept`/`maxBytes` prop'ları satır 122-124'te doğrulandı) · `admin-panel/frontend/src/views/seller/ListingFormView.vue:436-507` (5454 satır, dosya gerçek) · `admin-panel/frontend/src/views/seller/StorefrontEdit.vue:107-543` (1307 satır, dosya gerçek) · `admin-panel/frontend/src/components/layout/IconRail.vue:37-45`. | Yok — CSS kutu ölçüleri, en-boy oranı, doğrulama var/yok sütunları da dolu ve dosyalarla örtüşüyor. |
| T-002 | Backend | Yok | FE-DIŞI | — | Frappe `File` DocType yaşam döngüsü, public/private yolu, disk hook'ları — backend. |
| T-003 | Analiz | Yok — üretim dosyalarının disk/DB taraması | FE-DIŞI | — | Format/boyut/DPI/codec istatistiği backend veri analitiği; ayrı bir FE kod deliverable'ı beklenmiyor. |
| T-004 | Frontend | Var — LCP taban çizgisi + srcset/sizes/fetchpriority/lazy envanteri açıkça FE görevi | **KISMİ** | `tradehub_core/docs/reports/03-performans-taban-cizgisi.md` (413 satır) gerçek Chrome DevTools trace ölçümü içeriyor (§2 "Dört sayfa × ölçülen metrik tablosu", §4 "En ağır 10 görsel", §5 nginx cache başlıkları). Mevcut kullanım koda karşı doğrulandı: `tradehubfront/src/components/media/ResponsiveImage.ts:45` (`fetchpriority` attr listesi), `:78` (LCP adayı → `fetchpriority="high"` + `decoding="sync"`) · `tradehubfront/src/components/product/ProductImageGallery.ts:99` · `tradehubfront/src/components/sell/SellPageLayout.ts:113` · `tradehubfront/src/components/shared/ListingCard.ts:133`. `srcset` 38, `fetchpriority` 23, `loading="lazy"` 70 isabetle `tradehubfront/src` genelinde gerçek. `perf-reports/home/home-performance.json` + `.md` gerçek ölçüm çıktısı olarak repoda duruyor. | Raporun kendi §6.1'i "Lighthouse — ÖLÇÜLEMEDİ" diyor (araç kurulu değil); WebPageTest hiç koşulmamış. §6.3 INP ÖLÇÜLEMEDİ, §6.5 kategori sayfası ÖLÇÜLMEDİ. Yani "4 sayfa × 2 cihaz profili" kabul kriteri tam karşılanmıyor — Chrome DevTools trace ile kısmi yerine geçirilmiş. |
| T-005 | Backend | Yok | FE-DIŞI | — | Frappe rol/izin matrisi, superadmin-only ayar deseni — backend. |
| T-006 | QA | Yok — fixture dosyaları (görsel/video) backend test korpusu | FE-DIŞI | — | `fixtures/` ağırlıklı `tradehub_core/tradehub_core/tests/fixtures` altında; FE kodu üretmiyor, FE testleri bunu tüketmiyor (crop parite testleri kendi `crop-vectors.json`'unu kullanıyor). |
| T-007 | Backend | Yok | FE-DIŞI | — | pyvips/Pillow/FFmpeg kıyaslaması — backend kütüphane seçimi. |
| T-008 | DevOps | Yok | FE-DIŞI | — | Depolama/maliyet projeksiyonu — altyapı/finans. |
| T-009 | Analiz | Yok — konsolidasyon raporu, ayrı FE deliverable'ı yok | FE-DIŞI | — | T-000…T-008'in (T-004 dahil) tutarlılığını onaylayan bir kapanış raporu; kendi başına yeni bir FE kod/iş üretmiyor. |
| T-010 | AR-GE | Var — kırpma algoritmasının FE ikizi üretimde çalışıyor | **KISMİ** | `admin-panel/frontend/src/lib/media/crop/geometry.js:5-6` kendi yorumunda `vendor/crop_geometry.ts`'in `tradehub_core/tradehub_core/media/pipeline/core/crop_geometry.py`'nin "birebir TypeScript ikizi" olduğunu belirtiyor; `useCropStudio.js:22` ve `components/media/crop/CropToolbar.vue` bu modülü içe aktarıyor (gerçek import zinciri grep ile doğrulandı); `src/lib/media/crop/__tests__/cropGeometryParity.test.js` pariteyi test ediyor. | Faz 1'in istediği ayrı AR-GE artefaktları yok: `prototypes/cropgeo/` dizini repoda yok, `P-01…P-16 izlenebilirlik tablosu` bulunamadı, `docs/reports/10-algoritma-dogrulama.md` yok — algoritma doğrudan üretime entegre edilmiş, ayrı prototip/rapor kanıtı üretilmemiş. |
| T-011 | AR-GE | Yok — Amazon/Alibaba kural + Cloudinary/imgix URL dili araştırması, salt rapor | FE-DIŞI | — | Çıktısı `docs/reports/11-rakip-analizi.md` (rapor); FE kod deliverable'ı beklenmiyor. |
| T-012 | Backend | Yok | FE-DIŞI | — | JPEG/PNG/TIFF/WebP/AVIF DPI okuma/yazma — backend format işleme (`media_engine/image/dpi.py` hedefi). |
| T-013 | AR-GE | Yok | FE-DIŞI | — | SSIM hedefli kalite arama backend Python encode döngüsü. |
| T-014 | AR-GE | Var — odak önerisi arayüzü ve skor hesaplaması FE'de üretimde | **KISMİ** | `admin-panel/frontend/src/lib/media/crop/focusSuggest.js:1-19` kenar-enerjisi tabanlı öneri + güven skoru hesaplıyor; `CONFIDENCE_THRESHOLD = 0.5` (satır 22); `components/media/crop/CropStudioModal.vue:166` ve `composables/useCropStudio.js:22` bu modülü içe aktarıp kullanıyor (gerçek import zinciri doğrulandı). | Aynı dosyanın kendi yorumu açıkça itiraf ediyor: `THRESHOLD_CALIBRATED = false` ve "**KALİBRE EDİLMEDİ**" — görevin istediği "50 görsellik insan işaretlemesine karşı ölçüm" ve yöntem kıyaslaması (entropy vs. saliency vs. bounding-box) yapılmamış; eşik sayısı ölçülmeden yazılmış. |
| T-015 | Frontend | Var — client-side ölçüm/işleme kodu üretimde çalışıyor | **KISMİ** | `admin-panel/frontend/src/lib/media/upload/probe.js` (`createImageBitmap` ile ölçüm, satır 150-167) + `preflight.worker.js` (Web Worker'a taşınmış ölçüm, ana thread'i bloklamamak için) + `preflightClient.js` (worker'ı çağıran istemci) — üçü de gerçek import zinciriyle birbirine bağlı (grep ile doğrulandı). `lib/media/compress.js` dinamik import ile `prepareImage`/`prepareVideo`'ya yönlendirip görseli WebP'ye, videoyu WebM'e çeviriyor. | Görevin adı geçen kütüphaneleri (`exifr`, `Pica`, `jSquash`) kod tabanında **hiç yok** (`grep -rli` → 0 isabet, `package.json`'da da yok — gerçek kullanılan kütüphaneler `createImageBitmap`/`OffscreenCanvas` (native) ve `browser-image-compression`/`mediabunny`). `prototypes/client-budget/` dizini yok. "Cihaz sınıfı × işlem × maksimum güvenli megapiksel tablosu" hiçbir yerde üretilmemiş — kod tabanında böyle bir tablo/benchmark verisi bulunamadı. Safari/iOS canvas limitleri belgelenmemiş. |
| T-016 | AR-GE | Yok | FE-DIŞI | — | Video codec karar tablosu backend/`ffprobe` tabanlı; FE bileşeni yok. |
| T-017 | QA | Yok — güvenlik reddi/sanitizasyon sunucu tarafında | FE-DIŞI | — | Bomb/polyglot/SVG sanitizasyonu backend pipeline işi; admin-panel kuralları zaten `v-html` yasaklıyor ve "sadece backend sanitize'li içerik" diyor — FE ayrı bir sanitizasyon katmanı üretmiyor/üretmesi beklenmiyor. |
| T-018 | DevOps | Yok | FE-DIŞI | — | Storage adapter (`local/s3/mirror`), CDN, imgproxy — backend/altyapı. |
| T-019 | AR-GE | Yok — ADR seti dokümantasyon | FE-DIŞI | — | `docs/adr/` altında karar kayıtları; kod deliverable'ı değil, FE'yi doğrudan değiştirmiyor. |

## Sayım

- **TAM:** 1 (T-001)
- **KISMİ:** 4 (T-004, T-010, T-014, T-015)
- **YOK:** 0
- **FE-DIŞI:** 15 (T-000, T-002, T-003, T-005, T-006, T-007, T-008, T-009, T-011, T-012, T-013, T-016, T-017, T-018, T-019)
- **ÖLÇÜLEMEDİ:** 0
- **Toplam:** 20

## En önemli 3 bulgu

1. **T-015'in özel teslimatı hiç yok, ama işlevsel bir ikamesi üretimde çalışıyor.**
   Görev metni açıkça `exifr` (metadata), `Pica` (downscale), `jSquash` (encode) adlarını
   veriyor — üçü de kod tabanında sıfır isabet. Bunun yerine `probe.js` +
   `preflight.worker.js` + `compress.js` (native `createImageBitmap`/`OffscreenCanvas` +
   `browser-image-compression` + `mediabunny`) farklı bir teknoloji setiyle benzer bir işi
   (client-side ölçüm + WebP/WebM dönüşümü) yapıyor. Bu, "kurulu ama farklı" durumu — görev
   kabul kriterindeki "cihaz sınıfı × maksimum güvenli megapiksel tablosu" ise **hiçbir
   yerde yok**; hiç ölçülmemiş.

2. **T-010 ve T-014'ün algoritmaları FE'de gerçekten bağlı ve test edilmiş — ama Faz 1'in
   istediği ayrı AR-GE kanıtı (prototip klasörü, izlenebilirlik tablosu, kalibrasyon raporu)
   üretilmeden doğrudan üretime geçilmiş.** `crop_geometry` ikizi (`vendor/crop_geometry.ts`)
   `useCropStudio.js` ve `CropToolbar.vue`'dan içe aktarılıyor, parite testi var — "kurulu ve
   bağlı" doğrulandı. `focusSuggest.js` de aynı şekilde `CropStudioModal.vue:166`'dan
   çağrılıyor — ama dosyanın **kendi yorumu** eşiğin (`0.5`) "KALİBRE EDİLMEDİ" olduğunu ve
   T-014'ün istediği insan-işaretleme karşılaştırmasının yapılmadığını itiraf ediyor. Yani
   kod dürüst; görev kabul kriteri karşılanmamış.

3. **T-001'in FE payı gerçekten tam ve iddiaları doğrulanabilir.** `00-upload-slot-envanteri.md`
   §4'teki 25 satırlık admin-panel tablosu rastgele örneklenen 6 dosyanın hepsinde (satır
   numaraları dahil) doğrulandı — "rapor diyor" değil, kod bizzat okundu. Bu, denetimdeki
   tek net **TAM** — ama T-001'in Faz 0 kapsamı zaten "envanter çıkar", kod yazma değil;
   yani bu TAM bir *analiz* teslimatının tamlığı, üretim kodu teslimatı değil.

## Ölçemediklerim

- **Perf-reports (`tradehubfront/perf-reports/`) içeriğinin sayısal doğruluğu yeniden
  koşulmadı** — dosyaların var olduğu ve gerçek JSON/MD formatında olduğu doğrulandı, ama
  içindeki LCP/CLS sayılarını bu oturumda yeniden ölçmedim (kural 5: performans/süre
  iddiası yapılmaz, makine paylaşımlı).
- **`docs/reports/11-faz1-arge.md`'nin T-011…T-019 alt bölümlerinin tam içeriği satır satır
  okunmadı** — yalnız önceki doğrulama raporlarındaki (33, 57a) alıntılar ipucu olarak
  kullanıldı, kendi FE-DIŞI kararlarım bağımsız kod taramasına dayanıyor, o raporun
  doğruluğuna değil.
- **`admin-panel/frontend` içindeki `compress.js`/`compress.image.js`/`compress.video.js`
  dosyalarının çalışma zamanı davranışı (tarayıcıda gerçekten çalışıp çalışmadığı, çökme
  oranı) koşturulmadı** — yalnız kaynak kodu okundu, statik doğrulama yapıldı.
