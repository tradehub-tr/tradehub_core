# 31 — Görev numarası hizalaması: kaynak doküman ↔ iç kayıtlar

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (dal `ahmet`) · **Tür:** salt okuma + belge
**Kaynak:** <https://karacaismail.github.io/imageoptimization/docs/> — 15 faz, 102 görev
**Tetikleyen:** `DALGA-A-DEVIR.md` — *"T-051'de numaralandırma kayması bulundu … '≈87 TAM' sayısı bu hizalama olmadan yaklaşık."*

> **Bu belge hiçbir kaynak dosyaya dokunmadı.** Ne `.py`, ne JSON, ne `docs/standards/`,
> ne mevcut bir rapor. Yalnız bu dosya yazıldı. Bütün ölçümler `git status`/`grep`/`ls`
> düzeyinde okumadır; hiçbir test bu görev için yeniden koşulmadı — koşulmuş test
> sayıları **atıf yapılan raporlardan** alınmıştır ve öyle işaretlenmiştir.

---

## 0. Tek sayfada sonuç

| | Sayı |
|---|---:|
| Kaynak dokümandan **tek tek çekilen** görev | **102 / 102** (eksik yok) |
| İç kayıtla **aynı işi** gösteren ID | 88 |
| **Kaymış** ID — aynı numara, iki tarafta farklı iş | **9** |
| Kaynakta olup iç kayıtta **hiç karşılığı olmayan** iş | **5** |
| İç kayıtta olup kaynakta **karşılıksız** iş | **3** (ayrı görev değil, başka ID'nin kanıtı) |
| **Düzeltilmiş karne** | **61 TAM · 37 KISMİ · 4 YOK** |

> ### Bugün iddia edilen "≈87 TAM / 102" **DOĞRU DEĞİL.** Kaynak kabul kriterlerine göre sayı **61**'dir.
>
> Bu, "dün 71'di, bugün 61'e düştü" demek **değildir**. İş azalmadı — **cetvel değişti.**
> `14-nihai-denetim.md`'nin 71 TAM'ı, iç kayıttaki **daha dar** görev tanımlarına göre
> verilmişti (örn. iç "T-052 = İmzalı URL" ✅; kaynak "T-052 = CDN teslim katmanı +
> imzalı URL + cache stratejisi + purge API'si" ⚠). Bu belgede her görev **kaynağın
> kendi kabul kriterlerine** karşı ölçüldü.
>
> **Asıl kazanım sayısı TAM değil, YOK'tur: 15 → 4.** 18 Ağustos'ta hiç dokunulmamış
> 15 görev vardı; bugün yalnız 4 kaldı ve dördü de aynı yerde — **Faz 11 simülatör arayüzü**.

### Üç sayının yan yana durumu

| Ölçüm | Cetvel | TAM | KISMİ | YOK |
|---|---|---:|---:|---:|
| `14-nihai-denetim.md` (18 Ağu) | iç görev başlıkları, "çıktı üretildi mi" | 71 | 16 | 15 |
| `DALGA-A-DEVIR.md` (19 Ağu, tahmin) | aynı cetvel + bugünkü işler | ≈87 | ≈11 | ≈4 |
| **Bu belge (19 Ağu, ölçüm)** | **kaynak dokümanın kabul kriterleri** | **61** | **37** | **4** |

---

## 1. Yöntem

### 1.1 Kaynak nasıl çekildi

Görev panosu (`91-gorev-panosu.html`) listeyi JavaScript ile üretiyor; tarayıcısız
okunduğunda tablo boş görünüyor. Liste sayfanın kaynağındaki `const T = [...]`
dizisinden ve ayrıca **15 faz sayfasının her birinden ayrı ayrı** çekildi; iki
kaynak **birebir aynı 102 görevi** verdi.

`docs/` dizin sayfası **Faz 1 görev sayfasına link vermiyor**. Faz 1 kartı
`20-tasarim-desenleri.html`'e (desen anlatımı, görev yok) gidiyor; gerçek görev
sayfası panonun JS haritasında yazılı: `21-faz1-arge-gorevleri.html`. Bu sayfa
ayrıca çekildi. **`11-faz1-arge.md` §0 bu sayfayı hiç görmediğini yazıyor**
("T-010…T-019'un kart metinleri yok … bağımlılık atıflarından türetildi") —
Faz 1'deki kaymaların kökü budur.

Faz sayfaları ve görev sayısı:

| Faz | Sayfa | Görev |
|---|---|---:|
| 0 · Keşif | `10-faz0-codebase-arastirma.html` | 10 |
| 1 · AR-GE | `21-faz1-arge-gorevleri.html` | 10 |
| 2 · Standartlar | `30-faz2-medya-standartlari.html` | 10 |
| 3 · Mimari | `40-faz3-mimari.html` | 6 |
| 4 · Veri modeli | `41-faz4-veri-modeli.html` | 5 |
| 5 · Depolama | `42-faz5-depolama-s3-cdn.html` | 6 |
| 6 · Image engine | `50-faz6-image-engine.html` | 8 |
| 7 · Video engine | `51-faz7-video-engine.html` | 6 |
| 8 · API | `52-faz8-api.html` | 6 |
| 9 · Media library | `60-faz9-media-library.html` | 6 |
| 10 · Crop studio | `61-faz10-crop-studio.html` | 6 |
| 11 · Simülatör | `62-faz11-simulator.html` | 6 |
| 12 · Teslim | `70-faz12-headless-teslim.html` | 5 |
| 13 · Güvenlik | `71-faz13-guvenlik-observability.html` | 6 |
| 14 · Kabul | `72-faz14-test-kabul.html` | 6 |
| **Toplam** | | **102** |

### 1.2 Not verme ölçütü — bu belgede sabit

| İşaret | Anlamı |
|---|---|
| **TAM** | Kaynak görevin **kabul kriterlerinin tamamı** bu depolarda kanıtlı. |
| **KISMİ** | Çıktı var, **en az bir kabul kriteri** kanıtsız. Hangisi olduğu satırda yazılı. |
| **YOK** | Çıktı kalemi hiç yok. |

`14-nihai-denetim.md` daha gevşek bir ölçüt kullanıyordu ("çıktı üretildi ve kanıtı
var"). İki ölçüt arasındaki fark bu belgedeki TAM sayısının neden daha düşük
olduğunun tek açıklamasıdır ve §5'te kalem kalem gösterilmiştir.

**Kanıt kapsamı üç depo:** `tradehub_core` (`ahmet`), `admin-panel/frontend`
(Faz 5/9/10 arayüzleri — **büyük kısmı commit edilmemiş**, `git status` `??`),
`tradehubfront` (Faz 12 teslim). Panel ve storefront **salt okundu**.

---

## 2. Kaynak dokümandaki 102 görevin tam listesi

Aşağıdaki liste kaynaktan makineyle çıkarıldı; **hiçbir başlık elle yazılmadı**.

### Faz 0 · Keşif

| ID | Başlık | Rol |
|---|---|---|
| `T-000` | Depo ve ortam envanteri | Analiz |
| `T-001` | Upload slot envanteri (tam liste) | Analiz |
| `T-002` | Frappe dosya akışı ve depolama analizi | Backend |
| `T-003` | Üretim medya istatistiği | Analiz |
| `T-004` | Frontend render envanteri ve LCP taban çizgisi | Frontend |
| `T-005` | Yetki ve rol modeli analizi | Backend |
| `T-006` | Golden fixture korpusunun oluşturulması | QA |
| `T-007` | Mevcut kütüphane ve bağımlılık uygunluk testi | Backend |
| `T-008` | Depolama ve maliyet taban çizgisi | DevOps |
| `T-009` | Faz 0 kapanış raporu ve çıkış kriteri onayı | Analiz |

### Faz 1 · AR-GE

| ID | Başlık | Rol |
|---|---|---|
| `T-010` | Kırpma ve türev algoritmalarının prototip doğrulaması | AR-GE |
| `T-011` | Pazaryeri görsel kuralları ve teslim yeteneği kıyaslaması | AR-GE |
| `T-012` | DPI / çözünürlük normalizasyon prototipi | AR-GE · Backend |
| `T-013` | Uyarlanabilir kalite (SSIM hedefli) prototipi | AR-GE |
| `T-014` | Smart crop / focal öneri motoru karşılaştırması | AR-GE |
| `T-015` | Client-side işleme bütçesi prototipi | Frontend |
| `T-016` | Video codec karar motoru araştırması ve benefit gate ispatı | AR-GE |
| `T-017` | Güvenlik AR-GE: bomb, polyglot, SVG, metadata | AR-GE · QA |
| `T-018` | Depolama adapter ve CDN AR-GE (yerel / S3 / imgproxy) | DevOps |
| `T-019` | Faz 1 kapanış: teknoloji seçim kararı (ADR seti) | AR-GE |

### Faz 2 · Standartlar

| ID | Başlık | Rol |
|---|---|---|
| `T-020` | Ürün görseli standardının sabitlenmesi ve politika şeması | Analiz |
| `T-021` | LOGO standardının belirlenmesi (seller-logo, brand-logo) | Analiz · Frontend |
| `T-022` | COMPANY COVER VIDEO standardının belirlenmesi | Analiz |
| `T-023` | Kalan slotların standartlarının sabitlenmesi | Analiz |
| `T-024` | DPI ve piksel normalizasyon kuralının şartnameye yazılması | Backend |
| `T-025` | İçerik uygunluk kurallarının tanımı ve eşikleri | Analiz |
| `T-026` | Retention (saklama) politikası standardı | DevOps |
| `T-027` | Kota ve oran sınırlama standardı | Backend |
| `T-028` | Geçiş (migration) planı: mevcut medyanın standarda uyumlandırılması | DevOps |
| `T-029` | Faz 2 kapanış: SRS (yazılım gereksinim şartnamesi) onayı | Analiz |

### Faz 3 · Mimari

| ID | Başlık | Rol |
|---|---|---|
| `T-030` | SAD (yazılım mimari dokümanı) yazımı | Backend |
| `T-031` | Arayüz sözleşmelerinin tanımı ve dondurulması | Backend |
| `T-032` | Frappe app iskeleti ve modül yapısı | Backend |
| `T-033` | Politika motoru (PolicyEngine) tasarımı ve uygulaması | Backend |
| `T-034` | İş kuyruğu ve durum makinesi altyapısı | Backend |
| `T-035` | Faz 3 kapanış: mimari gözden geçirme ve dondurma | Analiz |

### Faz 4 · Veri modeli

| ID | Başlık | Rol |
|---|---|---|
| `T-040` | DocType şemalarının yazımı | Backend |
| `T-041` | Crop intent veri modeli ve öncelik zinciri | Backend |
| `T-042` | Dedup, versiyonlama ve içerik hash'i | Backend |
| `T-043` | Kullanım takibi (Media Usage) ve öksüz dosya tespiti | Backend |
| `T-044` | Faz 4 kapanış: veri modeli gözden geçirme | Analiz |

### Faz 5 · Depolama

| ID | Başlık | Rol |
|---|---|---|
| `T-050` | StorageAdapter uygulaması (Local · S3 · Mirror · Tiered) | Backend |
| `T-051` | Media Storage Settings ekranı ve superadmin izolasyonu | Backend · Frontend |
| `T-052` | CDN teslim katmanı, imzalı URL ve cache stratejisi | DevOps |
| `T-053` | Retention, arşivleme ve GC işleri | Backend |
| `T-054` | Yedekleme ve felaket kurtarma (DR) | DevOps |
| `T-055` | Faz 5 kapanış: depolama kabul testleri | QA |

### Faz 6 · Image engine

| ID | Başlık | Rol |
|---|---|---|
| `T-060` | Probe + guard katmanı (decode etmeden karar) | Backend |
| `T-061` | Normalize: orientation, renk uzayı, DPI, piksel tavanı | Backend |
| `T-062` | Sınıflandırma ve format zinciri | Backend |
| `T-063` | Rendition üretimi (crop + resize + encode) | Backend |
| `T-064` | Idempotency ve yeniden işleme | Backend |
| `T-065` | LQIP (BlurHash/ThumbHash) ve dominant renk | Backend |
| `T-066` | Kalite raporu ve tasarruf telemetrisi | Backend |
| `T-067` | Faz 6 kapanış: golden fixture regresyon paketi | QA |

### Faz 7 · Video engine

| ID | Başlık | Rol |
|---|---|---|
| `T-070` | ffprobe tabanlı probe ve doğrulama | Backend |
| `T-071` | Karar tablosu yorumlayıcısı | Backend |
| `T-072` | Transcode, benefit gate ve kalite doğrulaması | Backend |
| `T-073` | Poster, preview klip ve hareketli önizleme | Backend |
| `T-074` | HLS / adaptif teslim (uzun videolar) | Backend |
| `T-075` | Faz 7 kapanış: video regresyon ve kaynak bütçesi | QA |

### Faz 8 · API

| ID | Başlık | Rol |
|---|---|---|
| `T-080` | OpenAPI sözleşmesinin yazımı (contract-first) | Backend |
| `T-081` | Upload session ve resumable yükleme uçları | Backend |
| `T-082` | Crop intent ve önizleme uçları | Backend |
| `T-083` | Manifest ve teslim uçları | Backend |
| `T-084` | Yönetim uçları ve contract testleri | Backend · QA |
| `T-085` | Faz 8 kapanış: API dondurma ve SDK | Backend |

### Faz 9 · Media library

| ID | Başlık | Rol |
|---|---|---|
| `T-090` | Frontend iskelet, tasarım sistemi ve API istemcisi | Frontend |
| `T-091` | Uppy + tus yükleyici ve preflight paneli | Frontend |
| `T-092` | Asset grid, arama, filtre ve sanal kaydırma | Frontend |
| `T-093` | Asset detay çekmecesi: versiyon, rendition, kullanım, kalite | Frontend |
| `T-094` | Klasör/etiket organizasyonu ve toplu işlemler | Frontend · Backend |
| `T-095` | Erişilebilirlik ve i18n doğrulaması | QA |

### Faz 10 · Crop studio

| ID | Başlık | Rol |
|---|---|---|
| `T-100` | Crop çekirdeği: paylaşılan geometri kütüphanesi | Frontend · Backend |
| `T-101` | Crop stage bileşeni (tutamaklar, zoom, focal) | Frontend |
| `T-102` | Canlı çoklu önizleme (rendition kartları) | Frontend |
| `T-103` | Otomatik odak önerisi ve güvenli alan | Frontend |
| `T-104` | Politika uyarıları ve crop intent kaydı | Frontend |
| `T-105` | Faz 10 kapanış: crop doğruluk kabulü | QA |

### Faz 11 · Simülatör

| ID | Başlık | Rol |
|---|---|---|
| `T-110` | Cihaz ve yerleşim kataloğunun veri olarak tanımı | Frontend |
| `T-111` | Cihaz çerçevesi ve sayfa şablonu render motoru | Frontend |
| `T-112` | srcset seçim göstergesi ve çözünürlük yeterlilik uyarısı | Frontend |
| `T-113` | Video slotu için poster/oynatma simülasyonu | Frontend |
| `T-114` | Onay kapısı ve previewed_placements kaydı | Frontend · Backend |
| `T-115` | Simülatörün gerçek sayfayla doğrulanması (drift testi) | QA |

### Faz 12 · Teslim

| ID | Başlık | Rol |
|---|---|---|
| `T-120` | MediaImage / MediaVideo teslim bileşenleri | Frontend |
| `T-121` | sizes değerlerinin gerçek düzenden türetilmesi | Frontend |
| `T-122` | LCP optimizasyonu ve preload stratejisi | Frontend |
| `T-123` | Gerçek kullanıcı telemetrisi (RUM) | Frontend · Backend |
| `T-124` | Faz 12 kapanış: performans kabulü | QA |

### Faz 13 · Güvenlik

| ID | Başlık | Rol |
|---|---|---|
| `T-130` | Worker izolasyonu ve kaynak limitleri | DevOps |
| `T-131` | SVG sanitizasyonu, CSP ve dosya servis güvenliği | Backend |
| `T-132` | Yetki sertleştirme ve sızıntı testleri | QA |
| `T-133` | Gözlemlenebilirlik: metrik, log, iz, alarm | DevOps |
| `T-134` | Denetim (audit) izi ve KVKK uyumu | Backend |
| `T-135` | Faz 13 kapanış: sızma testi ve yük testi | QA |

### Faz 14 · Kabul

| ID | Başlık | Rol |
|---|---|---|
| `T-140` | İzlenebilirlik matrisi (SRS → test) | QA |
| `T-141` | E2E senaryo paketi | QA |
| `T-142` | Kullanıcı kabul testi (UAT) ve satıcı pilotu | Analiz |
| `T-143` | Geçiş (backfill) uygulaması ve izleme | DevOps |
| `T-144` | Devreye alma (go-live) ve runbook'lar | DevOps |
| `T-145` | Nihai kabul dosyası ve devir | Analiz |

---

## 3. Kayma tablosu

### 3.1 A sınıfı — aynı ID, iki tarafta **farklı iş** (9 görev)

Numara kayması buradadır. "İç kayıt" sütunu `docs/reports/14-nihai-denetim.md`
§6 karnesindeki satır başlığıdır.

| ID | **Kaynak dokümandaki iş** | İç kayıttaki iş (`14-…md`) | Kayma türü |
|---|---|---|---|
| `T-010` | Kırpma ve türev algoritmalarının prototip doğrulaması | "Ölçüm çerçevesi + korpus bütünlüğü" | **Tamamen farklı.** `11-faz1-arge.md` §T-010 bu görevi *kendisi tanımladığını* yazıyor — kaynak kartı görülmemiş. |
| `T-011` | Pazaryeri görsel kuralları ve teslim yeteneği kıyaslaması (Amazon/Alibaba/Shopify/Cloudinary/imgix) | "Rakip kalite seçimi araştırması" | **Daraltma.** Kaynak yetenek matrisi + 10 somut kural istiyor; iç kayıt yalnız kalite seçimi başlığını almış. |
| `T-018` | **Depolama adapter ve CDN AR-GE** (yerel / S3 / imgproxy, purge, imzalama) | "İçerik-adresli tekilleştirme" (45,2 MB / %3,9) | **Tamamen farklı.** İç T-018'in ölçtüğü iş aslında kaynağın `T-042`'sinin kanıtıdır. |
| `T-019` | Faz 1 kapanış: **ADR seti** (en az 8 ADR: image/video engine, client set, depolama, CDN, smartcrop, kalite stratejisi, karar tablosu) | "Faz 1 kapanış" (rapor) | **Daraltma.** Çıktı kalemi ADR seti; depoda `docs/adr/` altında **1 dosya** var. |
| `T-050` | StorageAdapter — **dört kip birden** (Local · S3 · Mirror · Tiered) + sözleşme testleri | "Yerel adaptör" | **Bölme.** Tek kaynak görevi iki iç göreve bölünmüş (T-050 + T-051). |
| `T-051` | **Media Storage Settings ekranı + Media Superadmin izolasyonu** | "S3 / mirror / tiered" | **Bir sıra kayma.** Kaynağın T-050'sinin yarısı iç T-051'e yazılmış. |
| `T-052` | CDN teslim katmanı + imzalı URL + **cache stratejisi + purge API'si** | "İmzalı URL" | **Daraltma.** |
| `T-053` | Retention, **arşivleme ve GC işleri** | "Saklama" | **Daraltma** (küçük). |
| `T-055` | **Faz 5 kapanış: depolama kabul testleri** (4 kip × 6 senaryo) | "Depolama fabrikası / superadmin ayarı" | **Tamamen farklı.** İç kayıtta Faz 5 kapanış görevi **hiç yok**; onun yerine kaynağın T-051'inin bir parçası oraya yazılmış. |

**Kaymanın anatomisi — Faz 5.** Kaynak 6 görevi şöyle: `T-050` adaptör (4 kip) ·
`T-051` ayar ekranı · `T-052` CDN · `T-053` retention · `T-054` DR · `T-055` kapanış.
İç kayıt aynı 6 kutuyu şöyle doldurmuş: `T-050` yerel adaptör · `T-051` S3/mirror/tiered ·
`T-052` imzalı URL · `T-053` saklama · `T-054` DR · `T-055` fabrika+ayar. Yani **T-050
ikiye bölününce sonraki dört numara birer kaydı** ve kaynağın kapanış görevi (`T-055`)
listenin dışına düştü.

**Faz 11'de ikinci bir kayma var** ve iç kayıtta yakalanmamış:

| ID | Kaynak | İç kayıt | Sonuç |
|---|---|---|---|
| `T-110` | Cihaz **ve yerleşim** kataloğunun veri olarak tanımı (ikisi tek görev) | "Cihaz kataloğu" | Kaynağın tek görevi ikiye bölünmüş |
| `T-111` | **Cihaz çerçevesi ve sayfa şablonu render motoru** (`DeviceFrame.vue`, `PagePreview.vue`, `SimulatorPanel.vue`, `DeviceMatrix.vue`) | "Yerleşim kataloğu" | Kaynağın T-111'i **hiç yapılmadı**; iç kayıt onu TAM saymış |

Bu, `14-nihai-denetim.md`'nin Faz 11 için verdiği **"3 TAM / 3 YOK"** sayısını
doğrudan yanlışlıyor: doğrusu **1 TAM / 1 KISMİ / 4 YOK**.

### 3.2 B sınıfı — kaynakta var, iç kayıtta **hiç karşılığı yok** (5 görev)

| ID | Kaynak görev | Neden gözden kaçtı |
|---|---|---|
| `T-055` | Faz 5 kapanış: depolama kabul testleri (`tests/acceptance/test_storage_acceptance.py`) | Numara başka işe verilmiş (§3.1). Depoda `tests/acceptance/` **yok**. |
| `T-111` | Simülatör render motoru | Numara "yerleşim kataloğu"na verilmiş (§3.1). |
| `T-018` | Depolama/CDN AR-GE prototipi (`prototypes/storage/`, `docs/reports/18-depolama-arge.md`) | Numara dedup ölçümüne verilmiş. **İşin kendisi sonradan Faz 5'te yapıldı** (rapor 23 + 27) ama AR-GE çıktısı olarak değil. |
| `T-010` | Kırpma prototipi (`prototypes/cropgeo/`, `tests/vectors/crop-vectors.json`, `docs/reports/10-algoritma-dogrulama.md`) | Numara ölçüm çerçevesine verilmiş. İşin çekirdeği sonradan `T-100`'de yapıldı. |
| `T-011` | `docs/reports/11-rakip-analizi.md` | Dosya **yok**; `11-faz1-arge.md` §T-011 masa başı bir paragraf. |

### 3.3 C sınıfı — iç kayıtta var, kaynakta **karşılıksız** (3 kalem)

Bunlar "fazladan görev" değil; **başka bir kaynak görevin kanıtı** olarak
yeniden etiketlenmelidir.

| İç kayıt | Gerçekte hangi kaynak görevin kanıtı |
|---|---|
| iç `T-010` "Ölçüm çerçevesi + korpus bütünlüğü" (51 fixture'ın 5'inde hash sürüklemesi) | `T-006` (golden fixture korpusu) — kalite kontrolü |
| iç `T-018` "İçerik-adresli tekilleştirme, 45,2 MB / %3,9" | `T-042` (Dedup, versiyonlama ve içerik hash'i) |
| iç `T-055` "Depolama fabrikası / superadmin ayarı" | `T-051` (Media Storage Settings ekranı) |

### 3.4 "İki farklı T-051" — bugünkü çift etiket

Görev tanımında uyarılan çakışma doğrulandı ve **ikisi de gerçekten yapıldı**:

| Rapor | Etiket kaynağı | İş | Kaynak ID karşılığı |
|---|---|---|---|
| `docs/reports/23-t051-s3-adaptor.md` | **iç** numaralandırma | S3/mirror/tiered adaptörlerinin **gerçek MinIO'ya** karşı ölçümü, 91 test | **`T-050`** |
| `docs/reports/25-t051-depolama-ayarlari.md` | **kaynak** numaralandırma | Ayar ekranı + Media Superadmin izolasyonu + şifreli sırlar + bağlantı testi + audit | **`T-051`** |

İkisi ayrı görevdir, ayrı sayılmıştır. Rapor 25 §0 zaten bu çakışmayı kendisi
tespit edip yazmış — kayma ilk orada görülmüştür.

---

## 4. Düzeltilmiş karne — kaynak ID'lerine göre

Ölçüt §1.2'de. "Kanıt / eksik" sütunundaki her `dosya:satır` ve rapor atfı bu
oturumda dosya sisteminde doğrulanmıştır; test **sayıları** atıf yapılan
raporlardan alınmıştır (bu görev için yeniden koşulmadı).

### Faz 0 — Keşif · **10 TAM**

| ID | Durum | Kanıt |
|---|---|---|
| `T-000` | TAM | `docs/reports/00-ortam-envanteri.md` |
| `T-001` | TAM | `docs/reports/00-upload-slot-envanteri.md` |
| `T-002` | TAM | `docs/reports/01-dosya-akisi.md` |
| `T-003` | TAM | `02-medya-istatistigi.md` + `08-canli-olcum.md` + `scripts/media_stats.py` |
| `T-004` | TAM | `03-render-envanteri.md`, `03-performans-taban-cizgisi.md` |
| `T-005` | TAM | `04-yetki-modeli.md` |
| `T-006` | TAM | 51 fixture + `manifest.json`. ⚠ Rapor 22 V-2: video fixture'larının 7/7'si `testsrc2` (sentetik) ve kalite kararlarında **iki kez yanılttı**. Korpus var, temsil gücü zayıf. |
| `T-007` | TAM | `05-kutuphane-benchmark.md`, 360 koşum 0 hata |
| `T-008` | TAM | `06-depolama-maliyet.md` |
| `T-009` | TAM | `07-faz0-kapanis.md` |

### Faz 1 — AR-GE · **6 TAM · 4 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-010` | **KISMİ** | Kırpma geometrisi çekirdeği ve vektörleri var (`media/pipeline/core/crop_geometry.py` + `.ts` ikizi, 592 vektör), ama **kaynağın istediği çıktılar yok**: `prototypes/cropgeo/` yok, `docs/reports/10-algoritma-dogrulama.md` yok, **P-01…P-16 tuzak izlenebilirliği yok** (`grep -rl "P-01" docs/` → yalnız fixture ve canlı ölçüm raporları). Öncelik zincirinin 5 seviyesinin ayrı ayrı test edildiği **doğrulanmadı**. |
| `T-011` | **KISMİ** | `docs/reports/11-rakip-analizi.md` **yok**. `11-faz1-arge.md` §T-011 kaynak-linksiz masa başı bir paragraf, kendi ifadesiyle `[D]`. Yetenek matrisi ve "10 somut kural" yok. |
| `T-012` | TAM | `11-faz1-arge.md` §T-012 [Ö] |
| `T-013` | TAM | `quality/ssim.py` + 21 test + `scripts/measure_ssim_quality.py` |
| `T-014` | TAM | Canlı 400 görselde ölçüldü (`11-faz1-arge.md` §T-014) |
| `T-015` | TAM | `11-faz1-arge.md` §T-015 [Ö][K] |
| `T-016` | TAM | **Bugün kapandı** — `22-t072-vmaf-av1.md` §4: AV1 aynı VMAF'ta H.264'ün **0,683×**'i; karar verildi ("AV1 şimdi eklenmesin"), sayısal yeniden değerlendirme tetiği §5.5'te yazılı. |
| `T-017` | TAM | 10 zararlı fixture ölçüldü (6'sı geçti — bulgu, ölçümün kendisi tam) |
| `T-018` | **KISMİ** | Kaynak: yerel/S3/**imgproxy** prototipi + purge API karşılaştırması + imzalama. Adaptörler ve imzalama **var ve ölçüldü** (rapor 23: 4 kip, 91 test, MinIO; rapor 27: imzalı URL + cache). **imgproxy prototipi yok** — rapor 25 §6.2: `imgproxy_*` alanlarını hiçbir kod okumuyor. **Purge API'si yok** — `cdn_purge_api_url` okuyucusuz. `prototypes/storage/` ve `18-depolama-arge.md` yok. |
| `T-019` | **KISMİ** | Kapanış raporu var (`11-faz1-arge.md`). Kaynak çıktı kalemi **ADR seti, en az 8 ADR**; `docs/adr/` altında **1 dosya** (`0001-icerik-adresli-depolama.md`). |

### Faz 2 — Standartlar · **9 TAM · 1 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-020`…`T-027` | TAM (8) | Slot standartları + `content_rules.json` + `retention.schema.json` + `quota.schema.json` + `docs/standards/` + `tests/test_policy_dpi.py` 19 test |
| `T-028` | TAM | **Bugün kapandı** — `17-t028-backfill-plani.md`: `scripts/plan_backfill.py` ilk kez koştu (çıkış kodu 0), slot bazında sayısal sonuç (2.833 aday / 835,4 MB), **üç kategori** (A 49 dosya · B 2.248 · C 512), parti/hız/kaynak/geri alma yazılı. ⚠ Ö4 kararı alınmadan koşturulmamalı. |
| `T-029` | **KISMİ** | `16-t029-politika-aktivasyonu.md`: SRS **hâlâ TASLAK** (`docs/srs/SRS-v1.0.md:3`), 7 kapıdan 2'si geçti (G2, G4), **4'ü açık**, 0/9 politika `active`. |

### Faz 3 — Mimari · **5 TAM · 1 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-030` | **KISMİ** | `21-t030-mimari-inceleme.md`: bağımsız inceleme yapıldı, karar **"SAD v1.0 bugün ONAYLANAMAZ"**, 8 bloklayıcı (SAD-G1…G8). `docs/sad/SAD-v1.0.md:3` hâlâ **TASLAK**. |
| `T-031` | TAM | `contracts/` + `signatures.golden.json` + 69 test |
| `T-032` | TAM | `media/pipeline/__init__.py` iskeleti; ayrıca **6 DocType Frappe'ye kuruldu** ve `hooks.py`'ye bağlandı (`hooks.py:160`, `:292`) |
| `T-033` | TAM | `policy/engine.py` + 38 test |
| `T-034` | TAM | `core/state.py`, `core/jobs.py` + 47 test |
| `T-035` | TAM | `docs/sad/review-v1.0.md` |

### Faz 4 — Veri modeli · **3 TAM · 2 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-040` | **KISMİ** | 15 spesifikasyonun **6'sı kuruldu**: `tradehub_core/tradehub_core/doctype/` altında `media_asset`, `media_engine_settings`, `media_processing_job`, `media_profile`, `media_rendition`, `media_storage_settings`. **9'u hâlâ kurulmadı** — `Media Crop Intent` dâhil (Faz 10'un kaydetme yolunu bu bloke ediyor, §Faz 10). |
| `T-041` | TAM | `core/crop.py` + `crop_geometry.py` + 63 test |
| `T-042` | TAM | `core/dedup.py` + 57 test; canlı ölçüm `11-faz1-arge.md` §T-018 (45,2 MB / %3,9) |
| `T-043` | TAM | `core/usage.py` + 45 test |
| `T-044` | **KISMİ** | `data-model-review.md` §8 açık maddeler; **`_ddl.sql` koşulmadı**, 1 M asset EXPLAIN incelemesi yok, migration/rollback provası yok. |

### Faz 5 — Depolama · **2 TAM · 4 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-050` | TAM | **Bugün kapandı** — `23-t051-s3-adaptor.md`: `local`/`s3`/`mirror`/`tiered` dördü de **gerçek MinIO'ya** karşı aynı sözleşme gövdesinden geçti, **91 test**. (Üretime alınamaz — 6 kusur §7'de; ama bunlar *kabul kriteri* değil, açılma koşulu.) |
| `T-051` | TAM | **Bugün kapandı** — `25-t051-depolama-ayarlari.md`: `Media Storage Settings` Single DocType (5 bölüm), **`Media Superadmin` rolü yaratıldı**, sırlar `Password` (Fernet), bağlantı testi gerçek yaz/oku/sil (MinIO'ya karşı 450 ms), audit `media/audit.py` → ADL (sır kayda girmiyor), panel ekranı `admin-panel/frontend/src/views/system/MediaStorageSettingsView.vue` (705 satır) + 9 test, rol kapısı `router/index.js:1037-1048`. Bilinçli sapma: kaynak alan adları yerine **fabrikanın okuduğu adlar** kullanıldı (§2.2). |
| `T-052` | **KISMİ** | `27-t052-cdn-teslim.md`: immutable/no-store/TTL/gzip/range/403 **7 madde ölçüldü**; imzalı URL ↔ blob bağı kapatıldı. **Eksik:** *"purge API'si çalışır durumda"* kriteri — `cdn_purge_api_url`/`cdn_purge_token` alanlarını hiçbir kod okumuyor (rapor 25). **Prod'a uygulanmadı** ve `docker/` git reposu olmadığı için 91 satırlık `gateway.conf` **versiyonlanmıyor** (§8.1-8.2). |
| `T-053` | **KISMİ** | `26-t053-saklama-gc.md`: iki zamanlanmış iş `hooks.py:160`'ta, legal hold vacuity ile kanıtlı (2 test kırmızıya döndü), dry-run 0 bayt fark, bakım raporu üretiliyor. **Eksik:** *"Silinen türev istendiğinde yeniden üretiliyor"* kriteri **karşılanmıyor** — §6: `regenerate_on_demand=True` "tutulamayan bir söz", `Media Rendition.generation=lazy` seçeneği tanımlı ama yazan kod yok; kod bunu ölçüp silmeyi `notify_only`'ye düşürüyor. Yani türev GC'si bugün **fiilen çalışmaz**. |
| `T-054` | **KISMİ** | `docs/plans/backup-dr.md` var. **Geri yükleme provası yok, süresi ölçülmedi**, RPO/RTO sayısal doğrulanmadı, periyodik bütünlük kontrolü yok. |
| `T-055` | **KISMİ** | Kaynak çıktı `tests/acceptance/test_storage_acceptance.py` — **dosya yok** (`tests/acceptance/` dizini yok). 6 senaryodan 1 ve 2 dolaylı olarak `test_storage_adapters_minio.py` ile karşılanıyor. **Ölçülmeyen:** hatalı kimlik bilgisiyle graceful degradation + alarm, CDN aç/kapa aynı asset, `tiered` zaman ileri sarma, retention dry-run onayı. |

### Faz 6 — Image engine · **8 TAM**

| ID | Durum | Kanıt |
|---|---|---|
| `T-060`…`T-067` | TAM (8) | `image/{probe,normalize,classify,render,reprocess,lqip,report}.py` + `tests/test_render_regression.py` 32 test + `docs/data/t063-render-olcum.json`. Faz 6 iç kayıtla kaynağın **birebir örtüştüğü tek fazdır**. |

### Faz 7 — Video engine · **4 TAM · 2 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-070` | TAM | `video/probe.py` |
| `T-071` | TAM | `policy/video_decision.json` + 58 test; `18-faz7-kapanis.md` K-1: 15 kuralın hepsi tetiklenebilir |
| `T-072` | TAM | **Bugün kapandı** — `22-t072-vmaf-av1.md`: `linuxserver/ffmpeg` (libvmaf) ile **7/7 fixture + canlı adayda VMAF ölçüldü**, 6/7 ≥ 93; üretim imajı ve `docker-compose.yml` değişmedi. Denetimin B6 kanıt boşluğu kapandı. |
| `T-073` | **KISMİ** | Poster (`video/poster.py`) ve **preview klip** (`make_preview_clip`, `build_preview_cmd`) var. **Eksik:** *"poster crop intent'e uyuyor"* — crop intent kaydı hiç yok (`T-104`/`T-040`); *"simülatörde video slotu poster üzerinden gösteriliyor"* — simülatör arayüzü yok (`T-113`); reduced-motion **politika alanı** tanımlı (`slot-policy.schema.json:869`) ama **teslim yolu doğrulanmadı**. |
| `T-074` | **KISMİ** | `18-faz7-kapanis.md` §6: 540 sn'lik gerçek dosyada **3 basamak, 405 segment, 27.301.407 B**, `master.m3u8` geçerli, segmentler mpegts/h264 — paketleme kanıtlı. **Eksik:** *"mobil veri tavanı: ilk 10 saniyede indirilen bayt ölçülüp standarda uygunluğu doğrulanıyor"* ölçülmedi; tarayıcı oynatması açık (rapor 18 kendisi ⚠ diyor). |
| `T-075` | TAM | **Bugün kapandı** — `18-faz7-kapanis.md` (kapanış belgesi) + 147 test 0 skip; kaynak bütçesi ve 4K senaryosu §7'de. ⚠ Faz **kapısı** hâlâ açık: rapor 22 §6.2, fayda kapısı canlı kütüphanede 4/4 çıktıyı elediği için VMAF kriteri **boş kümede** tutuyor. Görev çıktısı tam, kapı vacuous. |

### Faz 8 — API · **3 TAM · 3 KISMİ**

`14-nihai-denetim.md`'nin B2 bulgusu (*"hiçbiri `@frappe.whitelist()` taşımıyor"*)
**artık yalnız yarısı doğru**: `media/pipeline/api/*.py` hâlâ saf Python, ama
ürün API katmanı `tradehub_core/api/media*.py` altında **53 whitelisted uç**
taşıyor (`grep -c '@frappe.whitelist' tradehub_core/api/media*.py`), medya HTTP
yüzeyinin tamamı `docs/api/openapi-http.yaml`'da **87 uç** olarak sayılı, ve
`hooks.py` boru hattını `File.after_insert`e bağlamış.

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-080` | **KISMİ** | İki OpenAPI belgesi var: `docs/api/openapi.yaml` (saf Python kütüphane katmanı, `pipeline/api/spec.py` üretiyor) ve **`docs/api/openapi-http.yaml`** — `scripts/gen_http_openapi.py` ile üretilen, **87 gerçek `/api/method/…` ucunu** anlatan kardeş belge; sapma testi `tests/test_http_api_contracts.py`. **Eksik:** spectral linter yapılandırması **yok** (`grep spectral` → 0); OpenAPI'den **TypeScript tipi üretilmiyor** ve panel bunları kullanmıyor (panel zaten JS, TS değil). |
| `T-081` | TAM | `media/chunked.py` — `baslat`/`parca`/`bitir` oturumlu, kesintiden devam eden, **politikayı birleşimden sonra uygulayan**, oturumu mağazaya bağlayan yükleme; whitelisted uçlar `api/seller_media.py`. (tus protokolü değil, kendi protokolü — kaynak "resumable" diyor, tus'u T-091'de şart koşuyor.) |
| `T-082` | **KISMİ** | `api/crop.py` saf Python olarak var. **Eksik:** `save_intent`/`suggest_focal` için **HTTP ucu yok** (`grep save_intent tradehub_core/api/*.py` → 0) ve `Media Crop Intent` DocType kurulmadı. `previewed_placements` kaydı hiç yok. Panel bu yüzden kaydedemiyor (§Faz 10, `T-104`). |
| `T-083` | TAM | `api/media_manifest.py`: `get_manifest`, `get_manifest_batch`, `get_signed_url` — whitelisted, misafire açık, ETag'li; DALGA A'da gerçek HTTP ile kanıtlandı (misafir, `HTTP 200`, `image/avif`, 20.376 B). |
| `T-084` | TAM | `api/media_admin.py` whitelisted uçlar + `tests/test_api_contracts.py` **126 test** |
| `T-085` | **KISMİ** | `docs/api/README.md` §2 sürüm dondurma politikası var; ayrıca `openapi-http.yaml` üreteci ve sapma testi sözleşmeyi kodla kilitliyor. **Eksik:** TypeScript istemci SDK **yok** (`find -name client.ts` → 0), Bruno/Postman koleksiyonu **yok** (`docs/api/collection/` yok), CI kontrolü yok. |

### Faz 9 — Media Library · **1 TAM · 5 KISMİ**

`14-nihai-denetim.md` bu fazı **0/6 YOK** saymıştı ("arayüz yazılmadı — admin-panel
ayrı depo, salt oku"). **Bu yanlıştır.** `admin-panel/frontend` altında geniş bir
medya arayüzü var; bir kısmı 15 Ağustos'ta commit edilmiş (`edd3950` ve öncesi,
TUR-126 ürün işi), bir kısmı **bugün yazılmış ve henüz commit edilmemiş**
(`git status` → `??`). Medyayla ilgili **16 test dosyası, 190 test** (panel suite
toplamı 357 test, 357 geçiyor).

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-090` | **KISMİ** | Rotalar kayıtlı (`router/index.js:345,354,989-1048`), tasarım sistemi gerçekten kullanılıyor, i18n altyapısı var. **Eksik:** **ayrı bir medya API istemcisi yok** — `src/api/` altında `media.js` yok; çağrılar jenerik Frappe istemcisi üzerinden ekran başına composable'lara dağılmış (`useSellerMedia.js`, `useMediaBrowser.js`, `useMediaRenditions.js`, …). Kaynak "OpenAPI tiplerini kullanan istemci" istiyor; **panel TypeScript değil, JavaScript** (yalnız 2 `.ts` dosyası var) ve Pinia/Vitest yerine `node --test` kullanılıyor. |
| `T-091` | **KISMİ** | Yükleyici var ve çalışıyor: `src/lib/upload-ui/uploader.ts` (ham XHR) + `useSellerMedia.js:247-320` (`upload_begin`/`upload_chunk`/`upload_finish`/`upload_abort`), `MediaUploadQueue.vue` (dosya başına ilerleme, geri sayımlı yeniden deneme, iptal), `utils/uploadPolicy.js` + 14 test. **Eksik:** **Uppy yok, tus yok** (`src/`, `package.json`, `node_modules` → 0 eşleşme). Preflight **Web Worker'da değil**; ayrı bir preflight paneli değil, kuyruk içinde. "50 dosyada ana thread <50 ms" ölçülmedi. |
| `T-092` | **KISMİ** | Izgara/arama/filtre büyük ve tam: `views/seller/MediaLibraryView.vue` (2.662 satır — ızgara/satır/tablo kipleri, filtre rayı, çipler, etiket bulutu, çoklu sıralama) + `stores/media.js` (841 satır). **Eksik:** **sanal kaydırma asset ızgarasında değil** — `composables/useVirtualGrid.js` (229 satır, 8 test) yalnız `MediaFolderGrid.vue` (gezgin ekranları) tarafından kullanılıyor; `MediaLibraryView.vue:580` hâlâ sayfalıyor. "10.000 asset'te akıcı" ölçülmedi. |
| `T-093` | **KISMİ** | `components/media/MediaDetailPanel.vue` (675 satır): rendition listesi (`MediaRenditionList.vue` — profil/genişlik/yükseklik/format/bayt/**SSIM**/üretim), kullanım listesi ("henüz sorgulanmadı" ≠ "kullanılmıyor" ayrımı açık). **Eksik:** **versiyon geçmişi yok** — `src/components/media` ve medya store'unda `version`/`sürüm`/`revizyon` arayüzü **hiç yok**. |
| `T-094` | TAM | Klasör ağacı (`MediaExplorerView.vue`, `SellerMediaExplorerView.vue`, `MediaFolderGrid.vue`, `MediaCrumbs.vue`, `useMediaBrowser.js`), etiketleme + toplu işlem (`MediaBulkBar.vue`: etiketle/indir/arşivle/sil/temizle, `addTagToMany`, aralık seçimi, geri alma kaydı). 17 test. |
| `T-095` | **KISMİ** | Erişilebilirlik gerçek ve testli: `__tests__/mediaAccessibility.test.js` (11 test: ızgara `role`, `aria-posinset`, roving tabindex, `aria-current`, canlı bölge duyuruları, **WCAG AA kontrast**) + `utils/gridNavigation.js` + 14 test + `MediaShortcutsModal.vue`. **Eksik:** **i18n yalnız TR/EN** — `i18n/locales/ar.js` ve `ru.js` dosyalarında `media:`, `mediaExplorer:`, `mediaAudit:`, `mediaOptimize:`, `mediaBackup:` ad alanları **yok** (yalnız `mediaStorage:` ve `cropStudio:` dört dilde). **axe-core taraması yok.** |

### Faz 10 — Crop Studio · **3 TAM · 3 KISMİ**

`14-nihai-denetim.md` bu fazı **1 TAM / 5 YOK** saymıştı. Bugün yazılan (henüz
commit edilmemiş) crop studio ile **3 TAM / 3 KISMİ** oldu. Crop testleri tek
başına **101 test**.

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-100` | TAM | `media/pipeline/core/crop_geometry.py` + `.ts` ikizi; panele **sha256 pinli** olarak vendor'lanmış: `frontend/src/lib/media/crop/vendor/crop_geometry.ts` (458 satır) + `vendor.manifest.json` (11 kaynak) + `scripts/sync-crop-geometry.mjs` (`npm run sync:crop:check`). Parite testi **592 vektör**, tolerans 0 px. |
| `T-101` | TAM | `components/media/crop/CropStudioModal.vue` (387), `CropCanvas.vue` (193, rAF ile birleştirilmiş `pointermove`), `CropHandles.vue` (296 — 8 tutamak, her biri `role="slider"` + `valuemin/max/now/text`, klavye okları, küçük çerçevede zarif bozulma), `CropToolbar.vue` (253 — oran `radiogroup`, zoom, geri al/yinele/sıfırla), `useCropStudio.js` (387) + `useCropHistory.js` (127, 13 test). |
| `T-102` | TAM | `crop/CropPreviewStrip.vue` (240) — slot profili başına bir `<canvas>`, kaynak bitmap'ten **istemci tarafında canlı** yeniden çiziliyor (sunucu rendition'ları bugün boş olduğu için bilinçli olarak onlardan üretilmiyor); kırpılamaz profiller ve boş durum ele alınmış. |
| `T-103` | **KISMİ** | Odak önerisi var: `lib/media/crop/focusSuggest.js` (119 satır, kenar-enerjisi ağırlık merkezi, gerçek hesaplanan `confidence`, `METHOD="edge_energy_v1"`, eşik 0,5); arayüz güven rozeti gösteriyor ve asla "yüz bulundu" demiyor (testle sabit). **Eksik (iki kalem):** dosyanın kendisi **kalibre edilmemiş bir yer tutucu** olduğunu yazıyor (saliency/yüz modeli yok, eşik kalibre edilmedi); ve **güvenli alan arayüzde hiç yok** — `safe_top/right/bottom/left` frontend'de yalnız `useCropStudio.js:336`'daki *eksik uç alan listesinde* geçiyor, çizim ve ihlal uyarısı yok. Web Worker'da hesaplandığı **doğrulanmadı**. |
| `T-104` | **KISMİ** | Uyarılar TAM: `lib/media/crop/cropWarnings.js` (`SEVERITY={BLOCK,WARN,INFO}`, `hasBlocker`) + `crop/CropPolicyNotice.vue` + 20 test. **Eksik — kritik:** **crop intent kaydedilmiyor.** `useCropStudio.js:329` `const saveAvailable = false;` sabitini taşıyor ve `missingEndpoint = { doctype: "Media Crop Intent", method: "…api.crop.save_intent" }` diye eksiği adlandırıyor; hesaplanan JSON yalnız `<details>` içinde gösteriliyor, Kaydet düğmesi kalıcı olarak `disabled`. Kök neden **backend**: `T-040`'ta `Media Crop Intent` DocType'ı kurulmadı, `T-082`'de HTTP ucu yazılmadı. |
| `T-105` | **KISMİ** | `lib/media/crop/__tests__/cropGeometryParity.test.js`: 592 vektör panelin kendi giriş noktasından geçiyor; vendor sha256 == manifest; manifest == canlı `tradehub_core` kaynağı (kardeş depo yoksa **gerekçesini yazarak atlıyor, sahte geçmiyor**); hiçbir crop modülünün vendor'ı doğrudan import etmediği ve kendi yuvarlama matematiğini yazmadığı da test ediliyor. **Eksik:** kaynak kriteri *"UI'da görülen önizleme ile **sunucunun ürettiği rendition** piksel düzeyinde eşleşiyor"* ve *"20 gerçek görselde el ile karşılaştırma"* — bu karşılaştırma **yapılmadı**; test UI'ı paylaşılan TS ikizi + Python'un ürettiği fixture'lara karşı ölçüyor, Python'u çalıştırmıyor. |

### Faz 11 — Simülatör · **1 TAM · 1 KISMİ · 4 YOK**

**Deponun en zayıf fazı ve iç kayıtta en yanlış sayılan faz.** Arayüz **hiç yok**.
Panelde bugün açılmış `src/lib/media/simulator/vendor/` (devices/placements/
parity_vectors JSON + `sync-simulator.mjs` + `gen_simulator_vectors.py`) var, ama
`__tests__/` dizini **boş**, `package.json`'da `sync:simulator` betiği **yok** ve
hiçbir bileşen bu veriyi tüketmiyor. İskele kurulmuş, ekran yazılmamış.

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-110` | TAM | `media/pipeline/simulator/devices.json` (13 cihaz) + `placements.json` (5 sayfa). Kaynağın "gerçek CSS'ten türet, tahmin etme" kuralı karşılanmış: `tradehubfront/src/lib/media/sizes.ts` başlığı, tablonun `placements.json`'dan türetildiğini ve `03-render-envanteri.md` §3'teki elle ölçülmüş piksel tablosuna karşı **71 satır / 0 açıklanmamış sapma** ile doğrulandığını yazıyor. |
| `T-111` | **YOK** | `DeviceFrame.vue`, `PagePreview.vue`, `SimulatorPanel.vue`, `DeviceMatrix.vue` — **hiçbiri yok**. Panelde "simulator" adını taşıyan tek ekran `AuthorizationSimulatorView.vue` (yetki simülatörü, Faz 3, ilgisiz). |
| `T-112` | **KISMİ** | Hesap motoru var: `simulator/srcset.py` + 34 test, 65 kombinasyon (kaynak_yetersiz=0 @2160px, zoom_yetersiz=6, aşırı servis=1); `lcp_candidate` alanı taşınıyor (`srcset.py:137,311,323`). **Eksik:** *"tahmini indirilecek bayt gösteriliyor"* — bayt hesabı yok; ve görevin kendisi Frontend, **gösterge arayüzü yok**. |
| `T-113` | **YOK** | Poster/oynatma simülasyonu arayüzü yok. |
| `T-114` | **YOK** | Onay kapısı yok. `previewed_placements` dizgesi **hiçbir frontend dosyasında geçmiyor**; backend'de de kaydı yok (`T-082`). |
| `T-115` | **YOK** | `parity_vectors.json` vendor'lanmış ama **onu tüketen drift testi yok** (`simulator/__tests__/` boş). Playwright görsel diff kurulmadı. |

### Faz 12 — Teslim · **2 TAM · 3 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-120` | **KISMİ** | Görsel tarafı tam: `tradehubfront/src/components/media/ResponsiveImage.ts` (+`.test.ts`) — AVIF→WebP→JPEG sırası, `width/height` daima, LQIP, `fetchpriority`/`loading`/`decoding` üçlüsü, `lib/media/manifest.ts`; panel tarafında `MediaImage.vue` + `mediaCls.test.js` (10 test). **Eksik:** **manifest tabanlı `MediaVideo` bileşeni doğrulanmadı** — `ProductVideoSection.ts` var ama poster/muted-loop/playsinline/HLS-lazy/reduced-motion sözleşmesini karşıladığı ölçülmedi. |
| `T-121` | TAM | **Denetimin B4 bulgusu kapandı.** `tradehubfront/src/lib/media/sizes.ts` türetilmiş veri olarak taşınıyor (üreteci `python3 -m tradehub_core.media.pipeline.delivery.sizes`, doğrulaması 71 satır / 0 sapma) ve `ResponsiveImage.ts:73-76` bunu manifestin slot bazlı `sizes`ının **üstüne yazıyor**. ⚠ Backend `delivery/manifest.py:78` `SIZES_TABLE`'ı hâlâ boş — yani kazanç istemci üzerinden geliyor, manifest üzerinden değil. |
| `T-122` | **KISMİ** | `fetchpriority="high"` + `decoding="sync"` + eager/lazy ayrımı uygulanmış (`ResponsiveImage.ts:237-250`, `ProductImageGallery.ts:99`). **Eksik:** `<link rel="preload">` **yok** — `docs/plans/faz12-lcp.md:36` gerekçeyi yazıyor (LCP görselinin adresi ancak API yanıtından sonra biliniyor). Değişiklik sonrası LCP/CLS **ölçülmedi**. |
| `T-123` | **KISMİ** | Şema ve toplayıcı sözleşmesi var: `delivery/rum.py` + 26 test. **Eksik:** storefront'ta **gönderici yok** (`main.ts`'te `web-vitals`/`PerformanceObserver` yok; tek eşleşme bir yorum satırı), **saha verisi yok**, p75 panosu ve regresyon alarmı yok. |
| `T-124` | TAM | **Bugün kapandı** — `DALGA-A-DEVIR.md` "T-124 — DALGA A KAPANDI": makine sakinken (yük 3,69) sitenin en ağır ürün sayfasında (`LST-00560`, 7 görsel, 9,99 MB) gerçek ölçüm; en pesimist senaryoda bile **0,617 MB (%93,8)**, kabul kriteri `< 2 MB` geçti; misafir HTTP kanıtı; geri alma doğrulandı (bayraklar 0, 84 türev silindi, `File` 5014 değişmedi). |

### Faz 13 — Güvenlik ve gözlemlenebilirlik · **3 TAM · 3 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-130` | TAM | `security/isolation.py` + 36 test. ⚠ RLIMIT_AS macOS'ta uygulanmıyor (3 skip) — ortam kısıtı, kod kusuru değil. |
| `T-131` | TAM | `security/svg.py` + 52 test |
| `T-132` | TAM | **Bugün kapandı** — `28-faz13-pentest.md` (whitelisted metot taraması, IDOR, path traversal, sır sızıntısı; gerçek HTTP + `frappe.set_user`) + `29-pentest-duzeltmeleri.md` (T1 Payment Transaction IDOR, T2 KYC ve T3 KYB kendini-doğrulama **kapatıldı**, her biri vacuity koşumuyla) + `24-kyc-izolasyon.md` (37 kullanıcının 24 KYC kaydına yazma izni kaldırıldı) + DALGA A'da 71 çapraz-kiracı dosya erişimi kapatıldı. ⚠ Açık kalan: T4 (ters bulgu), T6 (savunma derinliği), T9'un uçtan uca yarısı `docker/`de. |
| `T-133` | **KISMİ** | `observability/{metrics,logging}.py` + 72 test. **Eksik:** **iz (trace) yok, pano yok, alarm yok, runbook bağı yok** — `find -iname "*grafana*" -o -iname "*prometheus*" -o -iname "*alert*rule*"` → **0 sonuç**. Kaynağın 5 kriterinden 3'ü hiç başlamadı. |
| `T-134` | **KISMİ** | Denetim yazımı var (`media/audit.py`, rapor 25'te ayar değişikliği ADL'ye yazılıyor, sır girmiyor), `docs/security/faz13-gdpr.md`, EXIF GPS silme. **Eksik:** kaynağın istediği **`Media Audit Log` DocType'ı (yalnız-ekleme) yok**; `docs/compliance/kvkk.md` **yok**; veri sahibi talebi (erişim/silme/taşıma) akışının teknik uygulaması doğrulanmadı. Ayrıca rapor 26 §7: `media/audit.py` eylem sözlüğü kapalı bir küme ve retention eylemleri ona eklenemedi. |
| `T-135` | **KISMİ** | Sızma testi **yapıldı ve raporlandı** (`28-faz13-pentest.md`) — denetimin "YOK"u düştü. **Eksik:** **yük testi yapılmadı** (rapor §5'te gerekçeli olarak kapsam dışı bırakıldı), kaos testi yok. Rapor 28 §9 kendi kararını yazıyor: *"Faz 13 kapanabilir mi? HAYIR — henüz değil."* Rapor 29 dört engelin üçünü kapattı. |

### Faz 14 — Test ve kabul · **1 TAM · 5 KISMİ**

| ID | Durum | Kanıt / eksik |
|---|---|---|
| `T-140` | **KISMİ** | Üretici + matris var (`docs/test/traceability.md`, `req-test-map.json`). **Kabul kriteri sağlanmıyor:** 202 gereksinimin 74'ü (**%36,6**) bağlı, **128'i kapsanmıyor** (`traceability.md:14-15`). CI'da güncel tutulduğu doğrulanmadı. |
| `T-141` | TAM | `tests/test_e2e_scenarios.py` 39 test. ⚠ 3'ü yazılmamış özellik yüzünden skip. |
| `T-142` | **KISMİ** | `docs/plans/faz14-uat.md` var; **UAT oturumu yapılmadı**, satıcı pilotu yok. |
| `T-143` | **KISMİ** | `migration/backfill.py` + 50 test + `17-t028-backfill-plani.md` kuru koşumu. **Eksik:** backfill **gerçek veriye koşulmadı** (bayraklar koşum öncesi ve sonrası `0/0/0`), pano yok, otomatik durdurma eşiği yok, geri alma provası yok, satıcı bilgilendirmesi yapılmadı (rapor 17 §8.7: `usage.py` 16/23 alan tanıyor, B sınıfı bildirimi yayına alınamaz). |
| `T-144` | **KISMİ** | `docs/plans/faz14-golive.md` var. **Rollback provası yapılmadı, süresi ölçülmedi**; runbook'lar ve on-call tanımı doğrulanmadı. |
| `T-145` | **KISMİ** | `docs/reports/13-faz14-kabul.md` var. **Eksik:** izlenebilirlik %100 değil (%36,6), 15 fazın 14'ünün kapısı açık, **imza bloğu boş**. |

---

## 5. Toplam ve karşılaştırma

| Faz | TAM | KISMİ | YOK | Toplam | (`14-…md`'nin dediği) |
|---|---:|---:|---:|---:|---|
| 0 · Keşif | 10 | 0 | 0 | 10 | 10 / 0 / 0 ✅ aynı |
| 1 · AR-GE | 6 | 4 | 0 | 10 | 8 / 2 / 0 |
| 2 · Standartlar | 9 | 1 | 0 | 10 | 8 / 2 / 0 |
| 3 · Mimari | 5 | 1 | 0 | 6 | 5 / 1 / 0 ✅ aynı |
| 4 · Veri modeli | 3 | 2 | 0 | 5 | 3 / 2 / 0 ✅ aynı |
| 5 · Depolama | 2 | 4 | 0 | 6 | 3 / 3 / 0 |
| 6 · Image engine | 8 | 0 | 0 | 8 | 8 / 0 / 0 ✅ aynı |
| 7 · Video engine | 4 | 2 | 0 | 6 | 4 / 2 / 0 ✅ sayı aynı, içerik farklı |
| 8 · API | 3 | 3 | 0 | 6 | 6 / 0 / 0 |
| 9 · Media library | 1 | 5 | 0 | 6 | 0 / 0 / 6 |
| 10 · Crop studio | 3 | 3 | 0 | 6 | 1 / 0 / 5 |
| 11 · Simülatör | 1 | 1 | **4** | 6 | 3 / 0 / 3 |
| 12 · Teslim | 2 | 3 | 0 | 5 | 3 / 2 / 0 |
| 13 · Güvenlik | 3 | 3 | 0 | 6 | 5 / 0 / 1 |
| 14 · Kabul | 1 | 5 | 0 | 6 | 4 / 2 / 0 |
| **Toplam** | **61** | **37** | **4** | **102** | 71 / 16 / 15 |

**Düzeltilmiş karne: TAM 61 (%59,8) · KISMİ 37 (%36,3) · YOK 4 (%3,9).**

### 5.1 "≈87 TAM" sayısı nereden geldi ve nesi yanlış

`DALGA-A-DEVIR.md` şöyle hesaplamış: *"Başlangıç 18 Ağu: 71 TAM · 16 KISMİ · 15 YOK.
Bugün ≈16 görev TAM'a geçti → ≈87 TAM."* İki hata var:

1. **Taban yanlıştı.** 71 TAM, iç kayıttaki daha dar görev tanımlarına göre
   verilmişti. Kaynak kriterlerine göre aynı gün taban 71 değil, yaklaşık **55**
   olurdu (Faz 8'de 6→3, Faz 13'te 5→3, Faz 14'te 4→1, Faz 12'de 3→2 vb.).
2. **Artış doğru sayılmış ama TAM'a değil KISMİ'ye gitti.** Bugün gerçekten
   ~16 görevde ilerleme oldu; bunların **8'i TAM'a çıktı** (`T-016`, `T-028`,
   `T-050`, `T-051`, `T-072`, `T-075`, `T-124`, `T-132`), kalanı YOK'tan
   KISMİ'ye taşındı (Faz 9/10'un tamamı, `T-052`, `T-053`, `T-135`).

**Doğru cümle şudur:** bugün *hiçbir şey yapılmamış* görev sayısı **15'ten 4'e**
düştü ve TAM sayısı 8 arttı. "Neredeyse bitti" değil; **"artık her fazda bir
şey var, ama 37 görevin adı konmuş bir eksiği kaldı"**.

### 5.2 En büyük tek düzeltme: Faz 9 ve Faz 10

Denetim bu iki fazı 11 YOK ile kapatmıştı ("admin-panel ayrı depo, salt oku").
Gerçekte `admin-panel/frontend`'de **190 medya testi** ve on binlerce satır
arayüz var. Yeni durum: Faz 9 = 1 TAM / 5 KISMİ, Faz 10 = 3 TAM / 3 KISMİ.
**Uyarı:** bu kodun büyük kısmı henüz **commit edilmemiş** (`git status` → `??`:
`components/media/crop/`, `lib/media/crop/`, `lib/media/simulator/`,
`composables/useCropStudio.js`, `useVirtualGrid.js`, `MediaStorageSettingsView.vue`,
6 test dosyası). Bir `git clean` bugünün işinin çoğunu siler.

---

## 6. Kalan iş — faz ve eksik kalem

### 6.1 YOK — 4 görev, hepsi Faz 11 arayüzü

| ID | Görev | Ne gerekiyor |
|---|---|---|
| `T-111` | Cihaz çerçevesi ve sayfa şablonu render motoru | `DeviceFrame.vue` + `PagePreview.vue` + `SimulatorPanel.vue` + `DeviceMatrix.vue`; gerçek CSS genişliğinde render + `transform: scale()`; 13 cihaz × 5 sayfa |
| `T-113` | Video slotu poster/oynatma simülasyonu | `T-111` bağımlı |
| `T-114` | Onay kapısı + `previewed_placements` kaydı | Önce backend: `T-082` ucu ve DocType alanı |
| `T-115` | Simülatör drift testi | `parity_vectors.json` vendor'lanmış, tüketen test yok; Playwright görsel diff + nightly |

### 6.2 KISMİ — 37 görevin eksikleri, tıkanma kaynağına göre

**A. Tek bir backend eksiği 4 görevi birden tutuyor** — `Media Crop Intent`
DocType'ı + `save_intent`/`suggest_focal` HTTP ucu:
`T-040` (9 DocType kurulmadı) → `T-082` (uç yok) → `T-104` (panel `saveAvailable=false`)
→ `T-114` (`previewed_placements` yok). Ayrıca `T-073` (poster crop intent'e uysun)
buna bağlı. **Deponun en yüksek kaldıraçlı tek işi budur.**

**B. Hiç başlanmamış kalemler (kod yazılması gerekiyor):**

| Kalem | Etkilediği görev |
|---|---|
| Grafana panoları + Prometheus alarmları + trace | `T-133` (kriterin 3/5'i) |
| `Media Audit Log` DocType (append-only) + `docs/compliance/kvkk.md` | `T-134` |
| `tests/acceptance/test_storage_acceptance.py` (4 kip × 6 senaryo) | `T-055` |
| TypeScript SDK + Bruno/Postman koleksiyonu + spectral | `T-080`, `T-085` |
| CDN purge API'si (`cdn_purge_*` alanlarını okuyan kod) | `T-052`, `T-018` |
| imgproxy prototipi (alanlar var, okuyan yok) | `T-018` |
| Türev yeniden üretim yolu (`generation=lazy` yazan kod) | `T-053` |
| Güvenli alan (safe zone) çizimi + ihlal uyarısı | `T-103` |
| Sanal kaydırmanın asset ızgarasına taşınması | `T-092` |
| Versiyon geçmişi arayüzü | `T-093` |
| `ar.js` / `ru.js` medya ad alanları + axe-core | `T-095` |
| Storefront RUM göndericisi (`web-vitals`) | `T-123` |
| Uppy + tus (ya da mevcut protokolün kaynak sapması olarak kabulü) | `T-091` |

**C. Yalnız *koşum/prova* bekleyenler (kod var, ölçüm yok):**
`T-044` (`_ddl.sql` + EXPLAIN + migration provası) · `T-054` (DR geri yükleme provası)
· `T-074` (ilk-10-sn bayt tavanı) · `T-105` (20 gerçek görselde UI↔sunucu piksel
karşılaştırması) · `T-122` (LCP/CLS sonrası ölçümü) · `T-135` (yük + kaos testi)
· `T-142` (UAT oturumu) · `T-143` (backfill gerçek koşum) · `T-144` (rollback provası)

**D. Yalnız *karar/imza* bekleyenler:**
`T-029` (SRS onayı — 4 kapı) · `T-030` (SAD onayı — 8 bloklayıcı) · `T-145` (imza)
· `T-019` (7 ADR daha yazılmalı)

**E. Belge borcu (yazılması dakikalar sürer, kaynak çıktı kalemi olarak eksik):**
`T-010` (`10-algoritma-dogrulama.md` + P-01…P-16 izlenebilirliği) · `T-011`
(`11-rakip-analizi.md`)

---

## 7. Doğrulanmayanlar — açıkça

Bu belgenin **ölçmediği**, dolayısıyla "geçti" demediği şeyler:

1. **Hiçbir test bu görev için koşulmadı.** 1.376 / 147 / 91 / 357 / 190 gibi
   bütün test sayıları atıf yapılan raporlardan alınmıştır. `14-nihai-denetim.md`
   B1'in bildirdiği **%5,6 kararsızlık (18 koşumun 1'i FAILED)** hâlâ açıklanmadı
   ve bu belge onu tekrar üretmeyi denemedi.
2. **Panel ve storefront kodu okundu, çalıştırılmadı.** Ekranların tarayıcıda
   çalıştığı görülmedi; yalnız dosya, satır ve test dosyası varlığı doğrulandı.
3. **`T-103` odak önerisinin Web Worker'da hesaplandığı doğrulanmadı** — kod
   okundu, thread bağlamı ölçülmedi.
4. **`T-120` `MediaVideo` sözleşmesi doğrulanmadı** — `ProductVideoSection.ts`
   var, kaynağın 6 kriterini karşılayıp karşılamadığı ölçülmedi.
5. **`T-073` reduced-motion teslim yolu doğrulanmadı** — politika alanı tanımlı,
   teslimde uygulandığı görülmedi.
6. **`T-044` ve `T-054`'ün "prova edilmedi" hükmü, provanın *yokluğuna* dayanıyor**
   (`docs/plans/` içinde koşum kaydı yok); başka bir yerde koşulmuş olma ihtimali
   taranmadı.
7. **Çalışma ağacı hareketli.** Ölçüm sırasında `docs/api/openapi-http.yaml`,
   `scripts/gen_http_openapi.py` ve `tests/test_http_api_contracts.py` depoda
   **numaralı bir rapor olmadan** duruyordu (`docs/reports/30-…` yok) — yani bu
   sayım sırasında başka bir el hâlâ çalışıyor olabilir. Sayılar bu belgenin
   yazıldığı ana aittir.
8. **Kaynak dokümanın kendisi 2026-08-19'da çekildi.** Doküman güncellenirse bu
   hizalama eskir. Faz sayfalarının hepsi ve panonun JS dizisi **iki bağımsız
   yoldan** aynı 102 görevi verdiği için çekimin eksiksizliği kanıtlıdır.

---

## 8. Öneri — numaralandırmayı kalıcı olarak sabitlemek

Kayma tek seferlik bir hata değil, **kaynak listenin depoda bulunmamasının**
sonucudur. `11-faz1-arge.md` §0 bunu açıkça yazıyor: kart metinleri görülmediği
için görevler bağımlılık atıflarından türetilmiş.

Önerilen tek adım: bu belgenin §2'sindeki 102 satırlık liste **tek doğru kaynak**
kabul edilsin ve bundan sonra her rapor başlığına kaynak ID'sini yazsın. Bugünkü
`23-…` / `25-…` çift T-051'i, iki farklı işin aynı etiketi taşımasının maliyetinin
somut örneğidir — rapor 25 bunu kendi §0'ında fark edip yazmasa, iki iş tek görev
sanılacaktı.
