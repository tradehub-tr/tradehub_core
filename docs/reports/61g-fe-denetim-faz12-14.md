# 61g — Frontend Denetimi: Faz 12, 13, 14 (17 görev)

**Tarih:** 2026-08-20 · **Yöntem:** salt okunur kod denetimi (grep + dosya okuma), hiçbir dosya değiştirilmedi.
**Kaynak belgeler:** `70-faz12-headless-teslim.html`, `71-faz13-guvenlik-observability.html`,
`72-faz14-test-kabul.html` — üçü de WebFetch ile başarıyla çekildi.
**Taranan dizinler:** `admin-panel/frontend`, `tradehubfront`, `tradehub_core` (çapraz kontrol), `docker` (nginx).

> Bu belgedeki `docs/reports/` altındaki önceki raporlar (12-, 36-, 57d-, 60-) **kanıt olarak
> kullanılmadı** — yalnızca ipucu olarak okunup her iddia kodda ayrıca doğrulandı. Uyuşmayan
> yerlerde kod esas alındı.

---

## Tablo

| Görev | Rol | FE payı | Durum | Kanıt (dosya:satır) | Eksik olan |
|---|---|---|---|---|---|
| T-120 | Frontend | MediaImage/MediaVideo teslim bileşenleri | **TAM** | Panel: `admin-panel/frontend/src/components/media/MediaImage.vue:1-80` (AVIF→WebP→JPEG `<picture>`, CLS koruması), `MediaVideo.vue:1-90`; kullanım: `MediaThumb.vue:3`, `views/seller/SellerMediaExplorerView.vue:230`, `views/system/MediaExplorerView.vue:395`, `MediaDetailPanel.vue:66`, `MediaPreviewModal.vue:25`. Mağaza: `tradehubfront/src/components/media/ResponsiveImage.ts:1-120` (aynı sıra, aynı CLS kuralı); kullanım: `ListingCard.ts:14,128`, `ProductImageGallery.ts:14,91`. | Yok — iki yüzde de bileşen var, gerçekten mount ediliyor. |
| T-121 | Frontend | sizes değerlerinin gerçek düzenden türetilmesi | **TAM** | Panel: `components/media/delivery/sizes.js` — `panelSizes()` gerçek CSS sabitlerinden (`IconRail.vue`, `SidePanel.vue`, `MediaLibraryView.vue` satır referanslarıyla) türetiliyor; kullanım `MediaThumb.vue:33,98`; parite testi `delivery/__tests__/panelSizes.test.js`. Mağaza: `lib/media/sizes.ts` — `python3 -m tradehub_core.media.pipeline.delivery.sizes` çıktısının birebir kopyası, "71 satır denetlendi, açıklanmamış sapma 0" notu dosyanın kendisinde; kullanım `ListingCard.ts:16`, `ProductImageGallery.ts:16`. | Yok — ikisi de üretimde gerçekten çağrılıyor. Tarayıcıda `currentSrc` vs `getBoundingClientRect()` karşılaştırması (≤%25 kabul ölçütü) **ÖLÇÜLMEDİ** (canlı tarayıcı gerektirir, kapsam dışı bırakıldı — bkz. `sizes.js` dosya içi not). |
| T-122 | Frontend | LCP optimizasyonu ve preload stratejisi | **KISMİ** | `priority`/`fetchpriority` mekanizması ikisinde de var ve gerçek sayfalarda gerçek LCP adayına bağlı: `ProductImageGallery.ts:101` (`priority: size === "large"` → ana görsel), `ListingCard.ts:136` (`eager: i === 0 && !opts.lazy` → ızgaranın ilk kartı, `fetchpriority` bilinçli olarak YÜKSELTİLMİYOR). Panelde `MediaImage.vue` `priority` prop'u aynı deseni uyguluyor. | `<link rel="preload" as="image" imagesrcset imagesizes>` (spesifik olarak istenen preload etiketi) **hiçbir yerde yok** — `grep -rn "rel=.preload"` iki FE ağacında da 0 sonuç, `imagesrcset`/`imagesizes` de 0 sonuç. Sayfa tipine göre LCP eleman haritası ve ÖNCE/SONRA ölçümü (`docs/reports/122-lcp.md`) yok. Alan (RUM) verisiyle doğrulama T-123'e bağımlı, o da kapalı. |
| T-123 | Frontend | Gerçek kullanıcı telemetrisi (RUM) | **KISMİ** | **İstemci var, iyi test edilmiş, ama monte edilmemiş:** `admin-panel/frontend/src/lib/media/rum/` (9 dosya, `web-vitals@6.1.1` bağımlı, `rum.py` ile parite vektörleriyle test edilmiş — `contract.js`, `vendor/rum_vectors.json`) + `composables/useRum.js`. Ancak `useRum.js:8` dosyasının kendi yorumu *"MONTAJ — bu dosyanın işi DEĞİL"* diyor; `admin-panel/frontend/src/main.js` içinde `startRum`/`useRum`/`web-vitals` **sıfır** geçiyor (`grep -n "Rum\|web-vitals" main.js` → boş). Mağazada (`tradehubfront`) RUM koduna dair **hiçbir iz yok** — `package.json`'da `web-vitals` bağımlılığı yok, `useRum`/`createRumCollector` grep'i 0 sonuç. **Uç yok:** istemcinin hedeflediği `POST /api/method/tradehub_core.api.v1.media_rum.collect` (`lib/media/rum/transport.js:189`) backend'de mevcut değil (`find -ipath "*api/v1/media_rum*"` 0 sonuç). **Saklama yok:** `tradehub_core/tradehub_core/media/pipeline/delivery/rum.py` içindeki kendi yorumu, `Media RUM Sample` DocType'ının **kurulmadığını** itiraf ediyor. | Üç halkadan hiçbiri uçtan uca çalışmıyor: istemci monte edilmemiş (panel) / hiç yok (mağaza), HTTP ucu yok, DocType yok. Bugün sıfır saha verisi toplanıyor. |
| T-124 | QA | Faz 12 kapanış: performans kabulü | **KISMİ** | `tradehubfront/lighthouserc.cjs` gerçek 3 sayfa (`/`, `/pages/products.html`, `/pages/product-detail.html`), LCP<2500/CLS<0.1/TBT<300 bütçeleriyle var; gerçek CI'a bağlı: `.github/workflows/deploy.yml`, `beta-release.yml`, `alpha-release.yml`, `rc-release.yml`, `prod-release.yml` hepsi `lighthouserc`/`lhci` referansı taşıyor. Kapanış raporu `tradehub_core/docs/reports/12-performans-kabul.md` mevcut ve **kendini üç seviyede itiraf ediyor**: 6 KANITLANDI, 4 HESAPLANDI (üretime uygulanmadı), 5 KAPATILAMADI (E1: gerçek LCP/CLS ölçümü yok, E4: preload doğrulanmadı, E5: RUM verisi yok). | Admin panelde ayrı bir Lighthouse CI yok (spec zaten mağaza sayfalarını hedefliyor, bu beklenen). Üretimde ölçülmüş "önce/sonra" LCP yok — T-122/T-123 açık olduğu için kapanamıyor. |
| T-130 | DevOps | Worker izolasyonu ve kaynak limitleri | **FE-DIŞI** | Konu subprocess/RLIMIT/Dockerfile — backend/altyapı. FE ağaçlarında ilgili hiçbir dosya yok (beklenen de bu). | — |
| T-131 | Backend | SVG sanitizasyonu, CSP ve dosya servis güvenliği | **KISMİ** | Genel site CSP başlığı gerçekten var ve nginx'te etkin: `docker/nginx/storefront.local.template:255`, `docker/nginx/admin-panel.local.template:12`, ayrıca repo içi eşleri `tradehubfront/nginx.conf.template:249`, `admin-panel/frontend/nginx.conf.template:13`; `X-Content-Type-Options: nosniff` de var (`storefront.local.template:248` vb.). | Belgenin istediği medyaya özgü sertleştirme yok: `/files/` ve `/private/files/` location blokları (`tradehubfront/nginx.conf.template:352,365`) sade `proxy_pass`, hiçbir `Content-Security-Policy: sandbox` veya `Content-Disposition` eklemiyor; ayrı `media.istoc.com` alt alan adı ya da `deploy/nginx/media.conf` **yok** (`find` 0 sonuç). SVG sanitizasyonu (`tradehub_core/tradehub_core/media/pipeline/security/svg.py`) backend'de var ama bu FE denetiminin kapsamı dışı (çapraz kontrol amaçlı not edildi). |
| T-132 | QA | Yetki sertleştirme ve sızıntı testleri | **FE-DIŞI** | IDOR/path traversal/sır sızıntısı/imzalı URL testleri `@frappe.whitelist()` metotlarını tarayan backend güvenlik testleridir; FE kod deliverable'ı beklenmiyor. Panelde bulunan `mediaAccessControl.test.js` bu görevin değil, var olan `set_access_level`/`get_signed_url` uçlarının panelden ÇAĞRILDIĞINI doğrulayan ayrı bir kablolama testidir (T-134/erişim düzeyi özelliğiyle ilgili, T-132'nin sızıntı testi kapsamında değil). | — |
| T-133 | DevOps | Gözlemlenebilirlik: metrik, log, iz, alarm | **FE-DIŞI** | Prometheus/Grafana/JSON log — backend/altyapı. FE'de karşılığı yok, beklenen de bu. | — |
| T-134 | Backend | Denetim (audit) izi ve KVKK uyumu | **FE-DIŞI** | Görevin tanımlı çıktısı (append-only `Media Audit Log` DocType, `docs/compliance/kvkk.md`) backend/dok kapsamında; spec'te FE viewer zorunluluğu yok, bu yüzden FE-DIŞI işaretlendi. **Not (bonus bulgu):** Buna rağmen panelde gerçek ve çalışan bir denetim görüntüleyici var: `admin-panel/frontend/src/router/index.js:37,1014` → `MediaAuditView.vue`, gerçek uçları çağırıyor: `tradehub_core/tradehub_core/api/media_admin.py:429` (`get_media_audit`), `:640,647,654,665` (facets/actors/report/targets). Bu, görevin zorunlu FE payı değil, ölçüme dahil edilmedi. | `Media Audit Log` DocType'ının klasörü bulunamadı (`find -ipath "*doctype*audit*"` 0 sonuç) — backend tarafı bu denetimin kapsamı dışı, ayrıca not edilir. |
| T-135 | QA | Faz 13 kapanış: sızma testi ve yük testi | **FE-DIŞI** | OWASP ASVS L2 + k6/locust — backend/altyapı testleri. `tests/load` dizini workspace kökünde var ama **boş**. FE'yle ilgisi yok. | — |
| T-140 | QA | İzlenebilirlik matrisi (SRS → test) | **YOK** | Belge açıkça FE payı istiyor: *"Vitest'te: test adında `[FR-012]` kullanımı"*. Gerçek matris `tradehub_core/docs/test/traceability.md` (üreten script `scripts/gen_traceability.py`, dosyanın 3. satırında yazılı) **yalnız Python testlerine** bağlanıyor — 111 test dosyasının hepsi `tests/test_*.py`. `grep -rln "\[FR-\|\[NFR-\|\[INV-"` her iki FE ağacında da **0 sonuç**. | Vitest tarafında hiçbir test gereksinim kimliğiyle etiketlenmemiş; FE testleri matrise hiç girmiyor. |
| T-141 | QA | E2E senaryo paketi | **YOK** | Belgenin istediği: Playwright, `tests/e2e/` altında **12 kritik medya senaryosu** (1000×1000 red, 3000×3000@300dpi dönüşüm, 18MP piksel tavanı, crop+onay, önizlemesiz onay engeli, video geçirgenlik/VMAF, dedup, bomba/polyglot, S3 kesintisi, retention). Workspace kökünde `tests/e2e/` **tamamen boş** (`find -type f` 0 sonuç). `tradehubfront/tests/e2e/` gerçek ve çalışan bir Playwright paketi taşıyor (`playwright.config.ts` + 25 dosya) ama içerik **tamamen farklı bir konu**: navigasyon, sepet önbelleği, döviz kuru, kategori filtresi, seller dashboard — medya pipeline senaryolarından **hiçbiri yok** (`grep -rln "VMAF\|polyglot\|bomb\|dedup\|retention\|focal"` → 1 yanlış-pozitif eşleşme dışında 0 sonuç). | 12 senaryonun hiçbiri (upload red, crop/onay akışı, dedup, S3 kesintisi, retention) yazılmamış. Var olan Playwright altyapısı yeniden kullanılabilir ama bu görevin ürettiği bir şey yok. |
| T-142 | Analiz | Kullanıcı kabul testi (UAT) ve satıcı pilotu | **FE-DIŞI** | Süreç/analiz görevi (10 satıcı, 6 görevlik pilot, bulgu raporu) — kod deliverable'ı değil. | — |
| T-143 | DevOps | Geçiş (backfill) uygulaması ve izleme | **YOK** | Belge satıcı bilgilendirmesi için açıkça FE istiyor: *"Panel bildirimi + e-posta … son tarih ve düzeltme rehberi"*. Backend modülü gerçekten var: `tradehub_core/tradehub_core/media/pipeline/migration/backfill.py`. Ancak panelde ya da mağazada geçiş/backfill'e özgü **hiçbir** bildirim/pano bulunamadı: `grep -rln "migrat\|backfill\|Backfill"` panelde yalnız alakasız eşleşmeler (`NotificationPanel.vue`, `UserProfileMobile.vue` — genel "migration" kelimesi, medya bağlamı yok), mağazada da yalnız alakasız eşleşmeler (adres/favoriler/sipariş — "migrate" kelimesinin başka kullanımları). | Satıcıya "türeviniz eskiyor / şu tarihe kadar düzeltin" bildirimi hiçbir FE yüzeyinde yok; ilerleme panosu da (tamamlanan/başarısız/ETA) FE'de bulunamadı. |
| T-144 | DevOps | Devreye alma (go-live) ve runbook'lar | **FE-DIŞI** | Aşamalı açılış (canary→%10→%50→%100), runbook'lar, rollback — ops süreci ve doküman; kod deliverable'ı FE'de beklenmiyor. `grep -rln "feature.?flag\|rollback"` FE'de yalnız `checkout.ts` içinde alakasız bir eşleşme verdi, geçiş bayrağına dair bir UI yok (beklenen de bu, bayrak backend/infra konfigürasyonu). | — |
| T-145 | Analiz | Nihai kabul dosyası ve devir | **FE-DIŞI** | `docs/qa/final-acceptance.md` — dokümantasyon çıktısı, kod değil. | — |

---

## Sayım

**Toplam görev: 17** ✓

| Durum | Adet | Görevler |
|---|---:|---|
| TAM | 2 | T-120, T-121 |
| KISMİ | 4 | T-122, T-123, T-124, T-131 |
| YOK | 3 | T-140, T-141, T-143 |
| FE-DIŞI | 8 | T-130, T-132, T-133, T-134, T-135, T-142, T-144, T-145 |
| ÖLÇÜLEMEDİ | 0 | — |

2 + 4 + 3 + 8 = **17** ✓

---

## En önemli 3 bulgu

1. **T-123 (RUM) zincirinin üç halkasından hiçbiri uçtan uca çalışmıyor.** İstemci toplayıcı
   (`admin-panel/frontend/src/lib/media/rum/*`, 9 dosya + 6 test dosyası) gerçekten yazılmış ve
   `rum.py` ile parite testli, ama `useRum.js:8` *"MONTAJ — bu dosyanın işi DEĞİL"* diyor ve
   `main.js`'te `startRum`/`useRum` çağrısı **sıfır**. Mağazada (`tradehubfront`) bu koddan hiç iz
   yok (`web-vitals` bağımlılığı bile eklenmemiş). Hedef uç `tradehub_core.api.v1.media_rum.collect`
   (`transport.js:189`) backend'de **yok**, `Media RUM Sample` DocType de yok — bu ikisi backend'in
   kendi kodundaki bir yorumda (`delivery/rum.py`, DocType YOK notu) itiraf edilmiş. Sonuç: bugün
   sıfır saha verisi toplanıyor; T-122'nin LCP iddiaları da bu yüzden alan verisiyle doğrulanamıyor.
2. **T-141'in 12 zorunlu E2E senaryosu hiç yazılmamış.** Workspace kökündeki `tests/e2e/` boş;
   `tradehubfront/tests/e2e/` gerçek ve çalışan bir Playwright paketi (25 dosya) ama tamamen farklı
   konularda (navigasyon/önbellek/döviz). Medya yükleme reddi, crop+onay akışı, dedup, S3 kesintisi,
   retention gibi belirtilen senaryoların hiçbirine dair dosya yok.
3. **T-131'in medya-özgü CSP sertleştirmesi eksik, genel site CSP'si var ama farklı bir amaca hizmet
   ediyor.** nginx'te `Content-Security-Policy` başlığı gerçekten etkin (`docker/nginx/*.template`),
   ama bu başlık analytics/pazarlama scriptleri için genişletilmiş (Yandex Metrica, GTM, Clarity —
   `scripts/lib/nginx-csp-contract.mjs` bunu doğrulayan bir sözleşme testi bile içeriyor). Kullanıcı
   yüklediği SVG/medya dosyalarını izole edecek `sandbox` direktifi, ayrı `media.` alt alan adı veya
   `/files/` konumuna özel `Content-Disposition` başlığı **yok** — nginx `/files/` bloğu
   (`tradehubfront/nginx.conf.template:363-372`) sade bir proxy.

---

## Ölçemediklerim

- **T-121 kabul kriteri "seçilen rendition ile kutu farkı ≤ %25"** — bu, canlı tarayıcıda
  `currentSrc` genişliği ile `getBoundingClientRect().width × devicePixelRatio` karşılaştırması
  gerektirir. Statik kod denetimiyle **ÖLÇÜLEMEDİ**; hem panel hem mağaza kaynak dosyaları bunu
  kendileri de itiraf ediyor (`sizes.js` "ÖLÇÜLMEYEN" bölümü).
- **T-122/T-124 gerçek LCP/CLS sayıları** — Lighthouse CI konfigürasyonu var ve CI'a bağlı olduğu
  doğrulandı, ama gerçek bir koşum (CI log'u, Lighthouse çıktısı) bu denetimde **çalıştırılmadı** —
  yalnız yapılandırmanın var ve bağlı olduğu doğrulandı, "geçti" denemez.
- **T-124'ün admin panel tarafı** — spec zaten mağaza sayfalarını hedeflediği için panelde ayrı bir
  bütçe aranmadı; bu bir eksiklik değil, kapsam dışı bırakma.
- **T-131 nginx yapılandırmasının canlıda gerçekten yüklü olup olmadığı** — `docker/nginx/*.template`
  ve repo içi `nginx.conf.template` dosyaları statik olarak doğru görünüyor, ama bunların
  **canlı/staging ortamında fiilen deploy edilip edilmediği** bu denetimin kapsamı dışında;
  kural #4 gereği bu ayrım yapılamadığından yalnız "yapılandırmada var" diye yazıldı, "etkin" denmedi.
- **T-132/T-133/T-135'in backend tarafının gerçekten geçip geçmediği** — bu denetim yalnız FE payını
  ölçmek üzere kapsamlandırıldı; backend testlerinin/alarmlarının gerçekten çalışıp çalışmadığı
  ayrı bir denetim konusu.
