# Kalan 45 frontend kaleminin planı

**Tarih:** 2026-08-20 · **Temel:** `docs/reports/61-fe-denetim-ozet.md` (7 paralel ajan ölçümü)
**Kapsam:** 102 görevin frontend payı olan 60'ından **tamamlanmayan 45'i**
(33 KISMİ + 11 YOK + 1 ÖLÇÜLEMEDİ). Kalan 42 görevin frontend payı yok.

---

## 1. Triyaj — 45 kalem dört kovaya ayrıldı

| Kova | Adet | Ne demek |
|---|---:|---|
| **A · Engelsiz frontend** | 9 | Bugün, frontend'de, kimseyi beklemeden yapılır |
| **B · Tek sahipli dosya** | 2 | Ortak dosya; ajana verilemez, orkestratör yapar |
| **C · Backend engelli** | 27 | Frontend hazır ya da hazırlanabilir ama karşısında uç/veri yok |
| **D · Karar bekleyen** | 7 | Yapılabilir ama önce bir tercih gerekiyor |

> Bir kalem birden fazla kovaya düşebilir (ör. T-095 hem B hem D). Toplam 45'i
> aşan sayım bundan.

---

## 2. Kova A — engelsiz (bu dalgada yapılıyor)

| # | Görev | İş | Sahip olduğu dosyalar |
|---|---|---|---|
| A1 | **T-092** | Ana kütüphane ızgarasına sanal kaydırma. `useVirtualGrid` VAR ama yalnız `MediaFolderGrid.vue`'da; asıl varlık ızgarası kullanmıyor | `views/seller/MediaLibraryView.vue` + yeni bileşen |
| A2 | **T-122** | `<link rel="preload">` — kod tabanında **hiç yok** (ölçüldü). LCP adayı görsel için üret | `tradehubfront/src/components/media/**`, panelde yeni composable |
| A3 | **T-141** | 12 kritik medya E2E senaryosu. Playwright **kurulu** (`tradehubfront/tests/e2e`, 10+ mevcut spec) | `tradehubfront/tests/e2e/media-*.spec.ts` (yalnız yeni dosya) |
| A5 | **T-071** | Video karar tablosunun **gerekçesini** simülatörde göster. Bugün `sync-simulator.mjs` yalnız poster sayılarını alıyor | `components/media/simulator/` + `scripts/sync-simulator.mjs` |
| A6 | **T-105 · T-124 · T-004** | Ölçüm borcu: crop kabul harmanını koştur, Lighthouse'u gerçekten koştur, LCP taban çizgisini kapat | yalnız rapor dosyaları |

**A4 (T-140, test etiketleme) bilinçli olarak bu dalgaya alınmadı** — A1/A3/A5 yeni
test dosyaları üretecek; etiketleme onlar bittikten sonra tek geçişte yapılır.

---

## 3. Kova B — orkestratörde (tek sahipli)

| # | Görev | İş |
|---|---|---|
| B1 | **T-095 · T-090** | RU/AR çevirisi: **766 / 917 anahtar eksik** (%83). `media.*`, `mediaAudit`, `mediaOptimize` ad alanları bu iki dilde sıfır. `i18n/locales/*` altı ajana yasak olduğu için orkestratörde |

---

## 4. Kova C — backend engelli (bu dalgada YAPILMIYOR)

Frontend'in yapabileceği bir şey yok; engel karşı tarafta. Her biri ölçülerek doğrulandı.

| Görev | Engel |
|---|---|
| T-061 · T-062 · T-063 · T-065 · T-066 | `media_pipeline_enabled` **varsayılan 0**; manifestte `classification`/`format_chain` alanları yok, LQIP/dominant renk beslenmiyor |
| T-073 · T-074 | Motor posteri için API ucu yok; HLS kaynağı hiçbir çağırandan gelmiyor |
| T-041 · T-043 | `resolve_crop` öncelik zinciri parite testi yok; kalıcı `Media Usage` index'i ve Orphan Report ucu yok |
| T-042 | **Ölçüldü: dedup/hash arama ucu yok** — `@frappe.whitelist()` bir karşılığı bulunamadı |
| T-081 · T-082 · T-083 | Sunucuda tus yok, `Idempotency-Key` yok, `manifest_batch` ucu tüketilebilir değil |
| T-114 | Onay kapısının **sunucu tarafı zorlaması yok**; kod bunu kendi itiraf ediyor |
| T-123 | RUM ucu yok, `Media RUM Sample` DocType'ı yok, `ROUTE_TEMPLATES` paneli kapsamıyor |
| T-131 | Medyaya özgü CSP/sandbox nginx + servis katmanında |
| T-143 | Satıcı bildirim verisi backend'den gelmeli |
| T-024 · T-025 | DPI eşiği ve içerik uygunluk eşikleri **şartnamede tanımlı değil** |
| T-020 · T-021 · T-022 · T-023 | Slot politikasının FE'ye vendor'lanan kısmı bilinçli olarak yalnız ön-kontrol alanları; genişletmek şartname + senkron sözleşmesi değişikliği |
| T-026 · T-027 · T-028 | İki-politikalı retention, kota boyutları, %2 devre kesici — hepsi sunucu modeli |

---

## 5. Kova D — karar bekleyen

| Görev | Karar |
|---|---|
| T-074 | **hls.js eklensin mi?** Yeni bağımlılık. Bugün yalnız yerli HLS (Safari/iOS) çalışıyor |
| T-090 | **TypeScript strict + Vitest'e geçilsin mi?** Panel bugün `node --test` kullanıyor ve 736 test yeşil; geçiş büyük ve riskli |
| T-080 · T-085 | **OpenAPI'den tipli TS SDK üretilsin mi?** Şartname `ui/src/api/client.ts` istiyor; bugün elle yazılmış istemci var |
| T-033 | **TS PolicyEngine yazılsın mı?** Şartname Python ile birebir çapraz test istiyor; bugünkü `preflight.js` "karar vermez, hızlandırır" diyor |
| T-095 | RU/AR çevirisi **makine çevirisiyle mi** doldurulsun, yoksa insan çevirmen mi bekleyecek? |
| T-025 | İçerik uygunluk eşikleri (NSFW/blur/filigran) **insan etiketleme** ister |

---

## 6. Ajan kuralları (bugün ölçülerek işe yaradı)

1. Koşturmadığına **"geçti" DEME**; ölçemediğini **ÖLÇÜLMEDİ** yaz.
2. **Vacuity kanıtı:** testi yaz, düzeltmeyi geri al, KIRMIZI göster, geri koy.
3. **Süre/FPS/performans iddiası yapma** — makine paylaşımlı.
4. **Yorum satırı kanıt değildir.** Bugün üç kez bayat yorum yanlış sonuca götürdü.
5. **"Dosya var" ≠ "bağlı".** Bileşeni bağladıysan kullanım sayısını grep ile göster.
6. `i18n/locales/*`, `router/index.js`, `data/navigation.js`, `vite.config.js` **YASAK** — orkestratörde.
7. Kendi dosyalarının dışına yazma. `tradehub_core` ve `docker/` yasak.
8. Bitirince `npm test` · `npx eslint src` koştur, sayıları raporla.

---

## 7. Kabul kriterleri

| Kontrol | Hedef |
|---|---|
| `npm test` (panel) | **736/736** korunacak + yeni testler |
| `npx eslint src` | EXIT 0, yeni uyarı yok |
| `npm run build` | EXIT 0 |
| T-092 | Ana ızgarada sanal kaydırma **bağlı** (kullanım sayısı > 0) |
| T-122 | `rel="preload"` LCP adayı için üretiliyor (0 → var) |
| T-141 | 12 senaryodan kaçının yazıldığı ve kaçının **gerçekten koştuğu** ayrı ayrı |
| T-071 | Karar gerekçesi ekranda; uydurma değil vendor'lanmış veriden |
| B1 | RU/AR eksik anahtar 766 → ölçülmüş yeni sayı |

---

## 8. Dalga 2 kapanışı — backend engel kaldırma (2026-08-20)

6 ajan, hepsi ölçümle kapandı. Konteynerde toplu: **94 backend testi** (17+7+19+18+20+13) OK; panel **833/833**; lint 0; prettier 4 locale'de tamamen temiz; imaj rebuild + canlı 200/200; rebuild sonrası regresyon yeşil.

| İş | Sonuç | Panoya etkisi |
|---|---|---|
| RUM zinciri | DocType (15 alan) + hız sınırlı uç (30/60sn, 31.→429) + scheduler purge kaydı; storefront montajı `web-vitals` onayına kadar yorumda | T-123 KISMİ→uç tarafı TAM; montaj kararda |
| Dedup | Üretim köprüsü `dedup.version_hash`'e devredildi (yalnız yeni üretimler); satıcı-scoped `find_in_my_library`; kuyrukta DUPLICATE uyarısı + "yine de yükle" | T-042 YOK→KISMİ/TAM'a yakın (backfill + Rendition.version şeması kaldı) |
| Zoom + kapı | `zoom/center_x/center_y` DocType+uç+FE; kanıtsız onay **417 MEDIA_PREVIEW_REQUIRED** (gerçek HTTP ölçümü); parite B sınıfı **119 sapan/7391px → 3/1px** | T-114 KISMİ→TAM; T-105 kabulü A/B/D'ye genişledi (C/E ürün kararı: oran zorlaması) |
| manifest_batch | 100 tavanlı toplu uç; panel 2 istek→1; tenant vacuity'si `ignore_permissions` ile kanıtlı | T-083 KISMİ→TAM'a yakın |
| Media Folder | DocType ×2 + 6 uç + gezginde gerçek klasörler; cross-tenant kanıtı konteynerde fiilen gevşetilerek | T-094 KISMİ→TAM'a yakın (DnD yok) |
| i18n | videoDecision 74×4 + dalga anahtarları 32×4 + `serverGap` metni 4 dilde yeni gerçeğe güncellendi | — |

Orkestratör düzeltmeleri: `hooks.py`'ye 5 kayıt (scheduler + 4 izin), bayat "sunucu kapısı YOK" iddiaları (2 kod başlığı + ekran metni + 4 locale + 1 test) yeni ölçüme güncellendi, `ru.js` çok-satır kırılması onarıldı.

**Kalan büyük kalemler:** T-140 etiketleme (sıradaki dalga) · panel E2E altyapısı (karar) · Faz 8 TS SDK/tus (karar) · `media_pipeline_enabled` açılışı (karar) · C/E oran kararı · RUM montaj onayı (`web-vitals`).

---

## 9. Dalga 4 kapanışı (2026-08-20)

7/7 iş ölçümle kapandı; imajlar (backend+panel+storefront) güncel, canlı 200, rebuild sonrası regresyon yeşil. Panel **862/862**.

| İş | Sonuç | Panoya etkisi |
|---|---|---|
| BE-2 hassas-ikiz | Köprüye tek-kapı koruması; canlıda `_resolve_scope → None`; sızıntı envanteri raporda (silme kararda) | T-042 güvenlik yarısı kapalı |
| BE-4 mükerrer File | `manifest_batch` file_url köprüsü; 8/9 boş → 9/9 tam | T-083 → TAM |
| W4-3 zenginleştirme | Media Version'a 7 alan; LQIP/dominant/dpi/sınıflandırma ÜRETİLİYOR; kablolama canlı vitrinde doğrulandı (`lqip: data:…`, `#c8c8b8`) | T-061/065 → TAM'a yakın · T-062 → KISMİ→TAM'a yakın |
| W4-4 RUM montajı | 72 girişe boot; gerçek tarayıcı vitals DB'de (LCP 160/CLS 0.0196); fiziksel URL normalizasyonu canlı | **T-123 → TAM** |
| W4-5 panel E2E | Playwright kuruldu; 6 koşuyor/2 gerekçeli skip; **4 yeni kusur buldu** (aşağıda) | T-141 → çekirdek TAM |
| W4-6 drift CI | Gecelik workflow (commit kullanıcıda); 88 kutu gerçek tarayıcıda **sapma 0** — katalog düzeltmeleri canlıda doğrulandı | T-115 → TAM'a yakın |
| W4-7 TS PolicyEngine | 393/393 parite (mesaj metinleri dahil); 57'nin protokol bulgusu kapalı ölçüldü | **T-033 → TAM** |

Orkestratör: manifest zenginleştirme kablolaması (8 nokta) + `get_my_media` LQIP beslemesi + `bicimle.lqip` + test izolasyonu (mükerrer-File dersiyle iki denemede) + BE-4 dışsal kırmızısı.

### W4-5'in bulduğu 4 kusur → Dalga 5 (koşuyor)
1. **`MediaUploader` hiçbir route'a bağlı değil** — min-boyut kapısı canlıda ölü ("kurulu ama bağlı değil" #10) → W5-B
2. **İstemci dedup uyarısı görsellerde yapısal ölü** (sunucu PNG→WebP çeviriyor, hash ayrışıyor) → BE-2 devam (`Media Version.source_hash` eşleşmesi)
3. **`CropStudioModal` `:asset`'siz mount** — Uygula o ekrandan hiç çağrılamıyor → W5-B
4. **Megapiksel-bomba kaçış aralığı** — ~89 MP üstü başlık iddiası denetimi atlatıyor (GÜVENLİK) → W5-C

---

## 10. Dalga 7 kapanışı (2026-08-20)

7/7 iş (oturum limiti kesintisi sonrası 5'i kaldığı yerden devam ettirildi). Karne **59 TAM / 42 KISMİ / 1 YOK** (gün başı: 21 TAM).

Öne çıkanlar:
- **Faz 7 kapandı sayılır:** video kuyruk yolu + kanonik adres + `vmaf_min` (ilk gerçek kararını verdi: 89,31<93 → türev atıldı, kaynak korundu) + HLS basamak kapısı (kaynaktan büyük 720p silindi) + manifest video servisi. E2E gerçek kuyrukla kanıtlı.
- **hls.js iki repoda** (ADR-0018 KABUL); poster storefront'a bağlı; `vendor-hls` tembel chunk.
- **Sunucu boyut kapısı canlı** (900×900+slot → 417) — kural kopyası değil, politika motoru köprüsü. **Orijinal sha256** artık saklanıyor (`Media Asset.original_sha256`, patch v15_9_34); dedup 3 katman.
- **YÜKSEK güvenlik bulgusu bulundu ve kapatıldı:** app hız sınırı eşzamanlılıkta atomik değildi (6195 istek/0×429) → Redis INCR'a çevrildi; canlı yeniden ölçüm: 8 paralel×120 → tam 30×200+90×429.
- **S3 kabulü gerçek:** 4 depolama modu MinIO'ya karşı 4/4 (T-055 → TAM).
- SAD/ADR/SRS 17 çelişkiyle gerçeğe eşitlendi; 3 ADR kullanıcı kararı bekliyor (tus/VMAF/K7).
- Sürüm çekmecesi gerçek veriyle dolu + yeniden işle; axe 14 yüzey (1 critical bulgu: `UploadDropzone` — sıradaki iş).
- **if_owner tuzağı üçüncü kez yaşandı ve kalıcı kapatıldı:** recreate+migrate imajdaki eski JSON'u DB'ye geri yazmıştı; W7-6 yakaladı, imaj rebuild kalıcılaştırdı, rebuild+migrate sonrası DB'de 0 ölçüldü.

Kapanış doğrulaması: 8 backend modülü OK · panel 906/901/0 · storefront 286 + bilinen 6 · canlı 200×3 · imajlar güncel.

Sıradaki ajan-işi adayları: UploadDropzone a11y düzeltmesi · önizleme klibi bağlama (T-073) · `videoPoster`'ın listing API'sine bağlanması · gölge `seller.py` + IBAN permlevel (güvenlik) · Faz 0-2 KISMİ kapanış ölçümleri (T-003/006/007/020/023/025 belge-ölçüm işleri) · T-134 KVKK denetim kalanları.

---

## 11. Dalga 8 kapanışı (2026-08-20)

5/5 iş, hepsi "önce yapılmış mı ölç" disipliniyle. Karne **75 TAM / 26 KISMİ / 1 YOK** (gün başı 21 → +54).

Öne çıkanlar (raporlar 90-94):
- **Faz 5 SIFIR kalanla kapandı** (S3 kabulü bağımsız tekrar 14/14, immutable cache üç sınıfta doğru).
- **İlk INP ölçümü:** 8,0 ms (RUM sahadan — bugüne dek yapısal olarak ölçülemeyen tek metrik).
- **categories.html CLS 0,5396 → 0,0001** (tek satır footer rezervasyonu); product-detail ilk gerçek ölçüm 1.393 ms bütçede. products.html LCP'nin kalan tek engeli bulundu: ızgara soğuk yüklemede manifesti tüketmiyor (vitrin bileşeni — sıradaki iş).
- **Güvenlik:** korumasız 5 guest ucu expose eden gölge modül SİLİNDİ; IBAN permlevel-1 (alıcı akışı kırılmadan); traceback sızıntısı yalnız-dev değildi — v15 varsayılanı prod'da da sızdırıyordu, patch v15_9_35 ile kalıcı kapatıldı; KVKK'da hiç yazılmayan anonimleştirme izleri ve 404 veren m.11 indirme akışı onarıldı.
- Video: önizleme klibi + listing API 4 video alanı + S7/S8 gerçek (S8: %66 küçülme, VMAF 96,655 ≥ 93 GEÇTİ — kapı iki yönde de çalışıyor).
- T-064 yetim-disk: 48 → 0 encode (disk-doğrulamalı atlama).
- Panel: a11y critical 0, T-140 kapsama 83, i18n dört dilde media.* 413 anahtar özdeş (+ görevde bile olmayan {pct}/{percent} yer tutucu hatası yakalandı).
- Orkestratör: gateway immutable haritası version_hash kalıbına genişletildi (canlı 3 sınıf doğru); test_privacy_audit'in bench-modu tasarım onarımı (gerçek local değiştirilmez, öznitelik yamalanır) — iki modda 9/9.

Kalan 27: ~11 imza/insan · ~7 karar · ~9 ajan işi (ızgara manifest tüketimi · T-006 video fixture · T-032 kalıntı temizliği · T-133 alarm kurulum yarısı · T-135 rol yükseltme · T-140 kalan adaylar · T-143 tam backfill).

---

## 12. Dalga 9 kapanışı (2026-08-20) — son teknik dalga

5 ajan (oturum limiti sonrası hepsi kaldığı yerden devam). Karne **79 TAM / 22 KISMİ / 1 YOK** (gün başı 21).

Öne çıkanlar (raporlar 95-98):
- **products.html LCP 6450 → 1400 ms** (%78, bütçe içinde) — ızgara soğuk yüklemede türev tüketiyor; ham indirme 7,25 MB → 0,16 MB. Boru hattının ürüne ilk ölçülmüş hız etkisi. **T-124 → TAM.**
- **T-135 rol yükseltme 15/15** — satıcı hiçbir yönde yükselemiyor (IBAN pl1 yazımı geri alınıyor, System Manager ekleme düşüyor); W8-3'ün IBAN taşıması gerçek saldırıya karşı kanıtlandı.
- **T-143 devre kesici ZATEN varmış** (rapor 57 bulgusu eskimiş — gold-plating'den kaçınıldı); 18 dosya gerçek parti 139→23 MB, resume kanıtlı.
- **T-006 video fixture 7→11** (4 gerçek DEV kaynağı, NTSC 29,97 fps + moov-sonda ilk kez); **T-032** ölü `import media_engine` düzeltildi.
- **T-133 alarm zinciri** doğrulandı: 18 kural, 3 canlı + 9 trafik-bekleyen + 5 toplayıcı-eksik; tetiklenme 2 kanıtla. **T-140** kapsama 86 (3 gereksinim ilk kez); 116 hâlâ kapsanmıyor (dürüst).
- Orkestratör: rate-limit atomik INCR'a çevrildi (Yüksek açık — canlı 8×120→30 geçti), traceback patch v15_9_35 (prod'u da etkiliyordu), immutable cache 3 sınıfta doğru, privacy testi iki-mod onarımı, videoDecision parite (`sync:policy` doğru zincir).

**Kapanış doğrulaması:** 8 backend modülü OK · panel 906/0 · üç imaj rebuild · 5 tuzak kontrolü temiz (if_owner=0, traceback maskeli, gölge modül yok, immutable, rate-limit) · canlı 200×3.

### Ajan-işi TÜKENDİ. Kalan 23'ün tamamı ajanla yapılamaz:
- **İmza/insan (~13):** T-009/019/029/035/044/067/075 faz onayları (docs/closure/ hazır) · T-142 UAT · T-144 tatbikat · T-145 imza · T-140 kalan kapsama (yeni test yazımı ayrı proje)
- **Karar (~6):** T-081/082 tus (ADR-0020) · T-105 C/E oran · T-025 content_rules etiketleme · T-043 index (ADR-taslak) · T-090 TS-strict · T-122/133 kalan yarıları operasyon
- **Operasyon (~4):** T-143 tam korpus backfill (kod hazır, koşum kararı) · T-133 Prometheus kurulumu · T-115 drift CI master-merge · T-132 rol testleri gecelik CI'a

---

## 13. Operasyon güncellemesi (2026-08-20, kullanıcı beyanı)

**T-133 Prometheus alarm kurulumu YAPILDI** — `docs/observability/media-alerts.yml` (18 kural, W7-4 üretti, W9-3 doğruladı: YAML geçerli, 0 drift, 16 kanonik alarm) kullanıcının kendi Prometheus/Grafana sunucusuna yüklendi.

> Bu satır KULLANICI BEYANIDIR; bu ortamdan doğrulanmadı (Prometheus ayrı sunucuda, buradan ağ erişimi yok). Buradan ölçülen kısım: kuralların kendisi geçerli ve `/metrics` serileriyle hizalı (rapor 97). Beslemenin İLK 2 HAFTA GÖZLEM notu ve 5 toplayıcı-eksik metrik (orphan/pii/job serileri) hâlâ geçerli — kurallar yüklendi ama o 5 seri henüz üretilmiyor.

T-133 durumu: kural üretimi + kurulum = TAMAM; canlı besleme = kısmi (gözlem penceresi).

---

## 14. K-dalgası kapanışı (2026-08-20) — 8 gerçek kod işi

Taze kod denetimi (4 salt-okunur ajan) → 8 gerçek kod kalemi → 5 ajan + orkestratör. Hepsi ölçümlü, vacuity'li.

| İş | Sonuç | Rapor |
|---|---|---|
| K1 · 5 ölü alarm metriği | Canlandı (`/metrics`: 46 öksüz, PII 13/0, iş sayaçları); **2 ölü alarm düzeltildi** (`failed`→`error`, hiç-yazılmama); scheduler `run_scan` hourly kayıtlı | 99 |
| K2 · `active_version` yazarı | `promote_version`+`rollback_version` atomik (14 test; vacuity: araya commit → SAVEPOINT hatası); ilk-yayın oto-promote hem görüntü hem video; panel-audit görünür (MEDIA_ACTIONS'a eklendi) | 100 |
| K3 · products LCP + önizleme klip | LCP: get_listings ilk-kart manifesti (canlı 246ms, türev AVIF). Önizleme klip: kod+test var ama **ProductVideoSection ölü kod (hiç mount edilmiyor)** — kanca canlı değil, ayrı iş | 101 |
| K4 · boyut kapısı + bildirim | Dropzone/Picker 900×900→0 upload isteği; `PlatformNotificationSink` gerçek satır (NOTIF + Email Queue) | 102 |
| K5 · KVKK medya + sır denetimi | Export'a medya (sensitive-twin maske); silmede anonimleştirme (reversible-trash); 9 sır-erişim audit (değer sızmıyor) | 103 |
| ⚠ Güvenlik (orkestratör) | KVKK export brute-force açığı: `@rate_limit(20/300s)` + `compare_digest` — canlı 21.+ istek 429; test yalıtımı (kova temizliği) | — |

Orkestratör: 2 hooks kaydı (run_scan hourly, MEDIA_ACTIONS ×2), rate_limit güvenlik yaması + test stub/yalıtım onarımı (frappe.cache stub + native delete), imaj rebuild ×3.

**Kapanış:** 8 backend modülü OK · panel 910/0 · storefront tabanında · üç imaj rebuild · canlı 200×3 · get_listings ilk-kart manifesti canlı doğrulandı · tüm tuzaklar (if_owner=0, traceback maskeli, gölge modül yok, immutable, atomik rate-limit, KVKK 429) temiz.

### Ajanla yapılacak KOD tükendi. Kalan ~23:
- **Bağlama artığı (küçük):** önizleme klip mount (ProductVideoSection ölü) · `_verify_client` audit sampling · JOB_ATTEMPTS transcode/av kapsamı · legal_hold alanı
- **Karar (~6):** tus · TS-strict · RU/AR logistics · fixture git · C/E oran · content_rules
- **İmza/operasyon (~13):** 7 faz onayı · UAT · go-live tatbikatı · backfill koşumu · media_backfill worker · drift CI merge · T-140 coverage testleri

## 15. Karar dalgası (2026-08-20) — 6 karar + 3 kod işi

Kullanıcı 6 kararı verdi; 3'ü kod işi doğurdu (D1/D2/D3), hepsi ölçümlü+vacuity'li:
- **content_rules (T-025) → İNSAN-ONAYIYLA KAPALI:** admin ürün onayı fiili içerik denetimi; AI ileriki iş (kullanıcı notu memory'de). T-025 TAM sayılır.
- **VMAF 93 · tus reddedildi · TS-strict reddedildi · RU/AR ertelendi · fixture git'e koyulmadı** (deploy hızı, kanıt manifest'te).
- **Hassas-ikiz 10 türev → dev seed, dokunulmadı** (üretim koruması zaten var).
- **D1 önizleme klip mount** (T-073 son parça): `product-detail.ts`'e bağlandı, canlı mount kanıtlı; klip verisi (preview türevi) dev'de yok → hover ölçülemedi (yapısal hazır).
- **D2 kota türev sayımı** (K7/ADR-0022): kota canlı `SUM`'a türev baytları eklendi; gerçek satıcı 11,4→36,5 MB; tenant vacuity + GC senkron.
- **D3 crop before/after + auto/manuel** (T-105): serbest kutu ≠ sunucu sonucu artık kaydetmeden görünüyor; auto/manuel toggle; gerçek görseller zaten. Panel 927/0.

**Kapanış:** panel 927/0 · 6 backend modülü OK · üç imaj rebuild · canlı 200×3 · 5 tuzak temiz · get_listings ilk-kart manifest canlı.
