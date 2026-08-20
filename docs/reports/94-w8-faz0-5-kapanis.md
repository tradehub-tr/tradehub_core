# 94 · W8 — Faz 0–5 kısmi belge/ölçüm görevlerinin kapanış ölçümü

**Tarih:** 2026-08-20 (öğleden sonra koşumu) · **Ortam:** `istoc-dev-backend-1` + `istoc.localhost` + `istoc-dev-minio-1` + headless Chrome (agent-browser)
**Yöntem:** Her kalemde önce kapıdaki eksik (61a/61b/57a/57b + faz kapanış dosyaları) okundu, sonra **bugünkü durum yeniden ölçüldü**. Çoğu eksiğin sebebi eski ölçümün bayatlamasıydı: bu koşumda boru hattı CANLI (`media_pipeline_enabled=1 · rendition_on_upload=1 · manifest_api_enabled=1`, 11:27:47'de okundu), 92 türev üretilmiş, VMAF ölçülebilir, S3 kabul paketi 14/14.
**Kurallar:** Kaynak koda dokunulmadı (tek istisna: INP üretmek için headless tarayıcı koşumu — yalnız DB'ye 1 RUM satırı düşürdü). Ölçülemeyen ÖLÇÜLMEDİ diye yazıldı. Süre iddiası yok. Commit yok. Kabul koşumu için açılan `t055-kabul-w8` MinIO bucket'ı koşum sonrası **silindi** (iz yok).

> Kardeş çıktılar: `media-stats-2026-08-20.csv` (T-003 makine-okunur istatistik) ·
> `docs/closure/faz{0..5}-kapanis.md` "Ek ölçüm (W8)" bölümleri.

---

## 0. Bu koşumda fiilen ölçülenler (özet)

| Ölçüm | Sonuç |
|---|---|
| Konteyner araç matrisi | ffmpeg **n8.1.2-44** · libvmaf filtresi **VAR (1)** · tesseract **5.3.0** (eng+osd+tur) · node v20.19.2 |
| bench venv kütüphaneleri | boto3 **1.34.162** · Pillow **12.2.0** · jsonschema **4.26.0** · numpy **2.4.6** · pytesseract **0.3.13** · pyvips **YOK** |
| Bayraklar | üçü de **1** (boru hattı canlı) · `active_slots = product.image, product.video` |
| DB medya envanteri | tabFile **5.084** · Media Asset **13** · Media Version **11** · Media Rendition **92** (26,85 MB, tümü bugün 07:31–11:05) · Job **11/11 success** |
| RUM | 19 örnek vardı (LCP/CLS/TTFB); **bu koşumda İLK INP üretildi: 8,0 ms** |
| S3 kabul paketi | `test_storage_acceptance` **14/14 OK, 0 skip** (4 S3 kipi dahil, MinIO'ya açık env ile — bağımsız yeniden koşum) |
| TS ikizleri | politika paritesi **22/22** (393 vektör) · kırpma paritesi **17/17** · vendor sha256 zinciri **16/16** bağımsız yeniden hesaplandı |
| Canlı HTTP | private **403** · imzasız download **403** · misafir get_signed_url **403** · Range → **206** · türev URL'leri version_hash'li ama **immutable başlıksız** (yeni bulgu, aşağıda) |
| Scheduler | enabled; 3 GC işi kayıtlı, bugün 09:13–09:14'te **Complete** |
| jsonschema (konteyner İÇİNDE) | 9/9 slot politikası şemaya karşı doğrulandı — **0 hata** |
| VMAF çalışırlığı | `libvmaf` filtresi gerçek skor üretti (self-test 99,77; gerçek içerik referansı: **89,34**, rapor 81) |

---

## 1. T-003 — Üretim medya istatistiği (Faz 0)

**Kapıdaki eksik:** eski istatistik boru-hattı-öncesi ve Docker kapalıyken yazılmıştı (rapor 02 kendi kısıt tablosu: "Docker kapalı, DB erişimi yok"); makine-okunur çıktı (`media-stats.csv`) hiç yoktu (57a T-003).

**Bugünkü ölçüm** (tamamı `bench mariadb`, canlı dev DB):

| Kalem | Değer |
|---|---:|
| tabFile toplam | **5.084** satır · **1.637.050.836 B** |
| public / private | 4.468 (1.341,2 MB) / 616 (295,9 MB) |
| Bayt dağılımı (file_size>0) | p50 **80.104** · p90 **832.915** · p99 **3.462.494** · max **22.065.728 B** |
| Uzantı dağılımı | jpg 3.463 · png 793 · webp 414 · jpeg 169 · mp4 79 · csv 56 · xlsx 34 · pdf 14 · tif 11 · zip 8 |
| Bağlılık | (boş) 3.139 · Listing 1.292 · KYB Verification 489 · Admin Seller Profile 39 · Bulk Import Job 29 |
| **Boru hattı katmanı (eski raporda HİÇ YOKTU)** | Media Asset **13** (product.image 9 · product.video 2 · library.upload 1 · test 1) · Media Version **11** · Media Rendition **92** (**26.853.813 B**) · Job **11/11 success** |
| Türev matrisi | webp 46 + avif 35 (w96→w1920 merdiveni, SSIM ortalamaları 0,9722–0,9923 **ölçülü**) + h264/mp4 1 + HLS 1 + poster 2 |
| **Hash'li adres oranı** | Türev katmanında **92/92** — hepsi `/files/media/{asset}/{64-hex version_hash}/…` (INV-09 üretimde CANLI). tabFile içinde eski içerik-adresli kalıp 117/5.084 (%2,3); türevler ADR-0009 gereği File kaydı açmadığından tabFile'da görünmez — 57b'nin "o kalıba uyan 0 dosya" bulgusu adres şeması değiştiği için eskimiştir |

**Çıktı:** `docs/reports/media-stats-2026-08-20.csv` (bu koşumda üretildi) + `02-medya-istatistigi.md`'ye ek bölüm.
**Kapanmayan:** kaynağın istediği yol birebir `fixtures/media-stats.csv` idi; kök `fixtures/` dizini hâlâ yok (bilinçli — korpus `tradehub_core/tests/fixtures/` altında). Slot bazlı p50/p90/p99 bu koşumda yeniden üretilmedi (09-slot-bazinda-istatistik.md duruyor); türev katmanının profil bazlı dağılımı yukarıda.

**Hüküm: FİİLEN KAPANDI** (güncel, makine-okunur, boru-hattı-sonrası istatistik üretildi; yol adı sapması not edildi).

---

## 2. T-004 kalanı — INP (Faz 0)

**Kapıdaki eksik:** "INP lab'da ölçülemez" (03-performans-taban-cizgisi §6.3; faz0-kapanis §3.5). O gün doğruydu: RUM yoktu.

**Bugün:** RUM zinciri CANLI (rapor 63+74). Koşum öncesi `Media RUM Sample` = 19 satır (LCP 10 · CLS 5 · TTFB 4 · **INP 0**).

**Yapılan (rapor 74'ün W4-4 deseniyle):** headless Chrome → `http://istoc.localhost/urunler` → örnekleme GİREN deterministik token (`sha256(token)[0:8]/0xFFFFFFFF < 0.1` şartını sağlayan `21bade02…` değeri `sessionStorage["tradehub.rum.token"]`a kondu — rapor 74'teki aynı meşru teknik) → sayfa yeniden yüklendi (`__tradehubRumBooted === true` doğrulandı) → **gerçek tıklama + klavye etkileşimleri** → `/sepet`e geçişte `sendBeacon` flush.

**İLK INP ÖRNEĞİ (DB'den okundu):**

```
name=q961va8br3 · metric=INP · value=8.0 ms · rating=good · route=/urunler
device_class=desktop · viewport_bucket=1280 · dpr=1.0 · connection=4g
navigation_type=reload · sample_rate=0.1 · 2026-08-20 11:41:27
```

**Hüküm: "INP ölçülemez" engeli FİİLEN AŞILDI** — gerçek tarayıcı etkileşiminden ilk INP sayısı DB'de. **Açık kalan:** tek örnek dağılım değildir; mobil cihaz profili hâlâ ölçülmedi (T-004'ün "2 cihaz profili" şartı desktop-only kalıyor); değer sentetik-yüksüz dev makinesinden geldi, hedefle kıyas için üretim trafiği gerekir.

---

## 3. T-006 — Fixture korpusu (Faz 0)

**Kapı:** ≥30 görsel + ≥8 video; kötücüller ayrı; manifest; <1 GB.

**Bugünkü envanter** (`tradehub_core/tests/fixtures/`):

| Kalem | Bugün | Kapı | Durum |
|---|---|---|---|
| Görsel | **34** (jpg 16 · png 12 · webp 3 · tif 2 · gif 1) | ≥30 | ✅ |
| Video | **7** | ≥8 | ❌ hâlâ 1 eksik |
| Kötücül | **10**, ayrı `malicious/` | ayrı dizin | ✅ |
| Manifest | **51 kayıt** | tam | ✅ |
| Boyut | **65 MB** | <1 GB | ✅ |
| **Gerçek-koşum fixture'ları (yeni tür — bugün var)** | `media/live-probe.json` (7 videonun canlı ffprobe künyesi, 11,6 KB) · `media/w6-video-live-run.json` (gerçek koşum: facts/decisions/gate/vmaf/poster/hls/remux/preview, 7,5 KB) · `crop_vectors.json` **592 vektör** (bugün doğrulandı) | — | ✅ |

**Eksik türler (sentetik ÜRETİLMEDİ — talep gereği yalnız liste):**
1. 8. video dosyası (kapının saydığı asgari).
2. 4K/60fps uzun video (T-075/4 — karar tablosu 4K'yı sentetik künyeyle reddediyor, dosyayla hiç test edilmedi).
3. HDR/BT.2020 video (T-072/5 tone-map yolu fixture'sız).
4. AdobeRGB görsel (T-061/3 ΔE ölçümü fixture'sız).
5. Gerçek fotoğraf (AS-27 — korpus tamamen sentetik; content_rules kalibrasyonu bu korpusla yapılamaz).

**Hüküm: görselde TAM, videoda KISMİ** — kapının sayısal şartı 7/8'de takılı; korpusun bugünkü gerçek gücü (canlı koşum fixture'ları, 592 vektör) kapı yazıldığında yoktu ve kayda geçirildi.

---

## 4. T-007 — Bağımlılık/kütüphane uygunluğu (Faz 0)

**Kapıdaki eksik:** benchmark `pyvips` yokken yazılmıştı, tekrar koşturulamıyordu; 57b döneminde imaj eskiydi (ffmpeg 5.1.9, libvmaf 0, boto3 sistem-python'da yok, tesseract yok, jsonschema yok).

**Bugünkü uygunluk matrisi (konteynerde ölçüldü, çalışırlık kanıtlarıyla):**

| Araç | 57a/57b (19.08) | **Bugün (20.08)** | Çalışırlık kanıtı (bu koşum) |
|---|---|---|---|
| ffmpeg | 5.1.9, libvmaf **0** | **n8.1.2-44** · libvmaf filtresi **1** | `libvmaf` gerçek skor üretti: self-test **99,77**; gerçek satıcı videosunda **89,34** (rapor 81, aynı imaj) — ADR-0021 (eşik kararı) artık ÖLÇÜLEBİLİR |
| tesseract | **YOK** | **5.3.0** (eng+osd+**tur**) | `--list-langs` koşuldu; T-025'in `overlay_text` engeli ARAÇ'tan çıktı (pytesseract 0.3.13 venv'de) |
| boto3 | sistem YOK / venv transitif | venv **1.34.162** | Bugün gerçek MinIO'ya karşı **14/14 kabul testi** bu kütüphaneyle koştu |
| Pillow | 12.2.0 | **12.2.0** | 92 türevin üreticisi (SSIM değerleri DB'de) |
| jsonschema | konteynerde **YOK** | **4.26.0** | Konteyner İÇİNDE 9/9 slot → **0 hata** (T-020'nin "üretim yolunda koşamaz" ARAÇ engeli DÜŞTÜ) |
| numpy | 2.4.6 | **2.4.6** | — |
| pyvips | YOK | **hâlâ YOK** | Benchmark hâlâ konteynerde tekrarlanamaz; ancak ADR-0008 kararı "Pillow'da kal" olduğundan bu artık karar-engeli değil, yalnız tekrarlanabilirlik borcu (ham veri `bench.csv` 360 koşum duruyor) |
| node | v20.19.2 | **v20.19.2** | Konteynerde değişmedi; ama TS ikizleri artık Node sürümünden bağımsız (esbuild ile derlenmiş `vendor/engine.js`; parite host'ta bugün 22/22 + 17/17) — eski "strip-types koşamıyor" engelinin ETKİSİ kalktı |

**Hüküm: FİİLEN KAPANDI** (pyvips istisnasıyla — o da ADR-0008 gereği uygunluk sorusu olmaktan çıktı). Eski uygunluk raporunun "libvmaf/boto3 yok" varsayımları bugünkü imaj için **geçersiz**.

---

## 5. T-010 / T-011 / T-015 — AR-GE kapanış notları (Faz 1)

Ortak eksik: "ayrı prototip/rapor artefaktı yok"tu. Üçünde de AR-GE sorusunu bugün **üretim kodu + ölçüm raporu** fiilen yanıtlıyor:

### T-010 — Kırpma/türev algoritması
- **Üretim kodu:** `media/pipeline/core/crop_geometry.py` + admin-panel ikizi (`lib/media/crop/vendor/`, esbuild türevi).
- **Ölçüm:** 592 altın vektör, sapma **0,0 px** / oran 2,07e-16 (57a [T]); TS parite **bugün 17/17** (`node --test cropGeometryParity` bu koşumda koşuldu); render tarafında tek kaynak `resolve_crop` (57b T-063/2).
- **Hâlâ eksik:** P-01…P-16 izlenebilirlik tablosu (bugün grep: yalnız rapor metinlerinde dağınık) ve `docs/simulator.html` (bugün bakıldı: repoda yok). AR-GE sorusu ("algoritma doğru mu") ölçümle kapalı; izlenebilirlik artefaktı açık.

### T-011 — Pazaryeri kural kıyaslaması
- **Üretim kodu:** sorunun fiilî cevabı artık **koşan veri**: 9 slot politikası JSON'u (min kenar/alan/oran/megapiksel — Amazon/Alibaba kıyasından türetilen sayılar) + `video_decision.json` (377 satır, karar tablosu) + bunların FE damıtımı (`slotPolicy.js`) ve TAM ikizi (`slot_policies.js`).
- **Ölçüm raporu:** `11-faz1-arge.md` §T-011 (masa başı, kendini öyle etiketliyor).
- **Hâlâ eksik:** kaynağın istediği ayrı `11-rakip-analizi.md` dosyası yok; içerik tek belgede. Yeni araştırma GEREKMİYOR — kurallar üretimde uygulanıyor; eksik yalnız artefakt-bölme işi.

### T-015 — Client-side işleme bütçesi
- **Üretim kodu:** `admin-panel/frontend/src/lib/media/upload/probe.js` + `preflight.worker.js` + `preflightClient.js` + `compress.js` (native `createImageBitmap`/`OffscreenCanvas` + `browser-image-compression` + `mediabunny`; görev metnindeki exifr/Pica/jSquash bilinçli olarak kullanılmadı — 61a bulgusu bugün de doğru).
- **Ölçüm raporu:** `44-t081-yukleyici.md` + `11-faz1-arge.md` §T-015.2 (çift-encode cezası ölçümü).
- **Hâlâ eksik:** "cihaz sınıfı × işlem × güvenli MP" tablosu ve Safari/iOS canvas limitleri hiçbir yerde ölçülmedi; `prototypes/` yok. AR-GE sorusunun "client hangi işi güvenle yapar" yarısı üretim davranışıyla (worker'a taşıma + sunucu son söz) yanıtlı, sayısal bütçe yarısı **ÖLÇÜLMEDİ** olarak kalıyor.

### T-014 doğrulaması (istenen özel kontrol)
`focusSuggest.js` bugün okundu: **`THRESHOLD_CALIBRATED = false` ve "KALİBRE EDİLMEDİ" notu HÂLÂ DOĞRU** (satır 20–36; eşik 0,5 "ÖLÇÜLMEDİ" yorumuyla duruyor). ADR-0017'nin "eşik üstünde ve yalnız öneri" kuralı üretimde; 50-görsel insan işaretlemesi yapılmadı → İNSAN engeli sürüyor. **Not bayatlamamış; değiştirmeye gerek yok.**

---

## 6. T-020 / T-023 — Standart kalanları (Faz 2)

**Kapıdaki eksik (61b):** "yalnız ön-kontrol alanları vendor'landı — master/quality/profiles/content_rules/messages FE'ye ulaşmadı"; T-020'de ayrıca "jsonschema konteynerde yok".

**Bugünkü ölçüm:**

1. **W4-7 vendor'u TAM politika taşıyor:** `admin-panel/frontend/src/lib/media/policy/vendor/slot_policies.js` (4.683 satır) **9/9 slotun HAM kopyası** — `master` 19, `content_rules` 18, `messages` 10 geçiş; 9 `slot_key` sayıldı. 61b'nin gördüğü damıtılmış `upload/vendor/slotPolicy.js` ayrı ve bilinçli olarak dokunulmamış (ikiz motorun kendi vendor zinciri var).
2. **Zincir bütünlüğü bağımsız doğrulandı:** `vendor.manifest.json`'daki sha256'lar bu koşumda yeniden hesaplandı — **16/16 uyuşuyor** (engine.py, 9 slot JSON, probe kaynakları, engine.ts→engine.js türetme halkası). Yani FE'deki politika, backend'deki politikanın **bugünkü** birebir kopyası.
3. **Parite bugün yeşil:** `npm run parity:policy` → **22/22 pass** (393 Python-üretimli vektör + hash zinciri + sahiplik korumaları).
4. **jsonschema ARAÇ engeli düştü:** konteyner İÇİNDE `Draft202012Validator` ile 9/9 slot doğrulandı, **toplam hata 0**.

**Hüküm:** 61b'nin T-020/T-023 "eksik" hanesindeki iki kalem (**tam politika FE'de değil** + **şema doğrulaması üretim yolunda koşamaz**) **FİİLEN KAPANDI ve kanıtlandı**.
**Kapanmayan (ayrı engel, KARAR):** 9/9 politika hâlâ `status: draft`, açık soru toplamı 49 (bugün sayıldı: brand 1 · seller 3 · category 6 · cover-image 6 · doc-attach 6 · product-video 6 · avatar 6 · product-image 7 · cover-video 8). "Tüm slotlar SABİT" kapısı vendor sorunundan bağımsız olarak KARAR bekliyor. Not: `Media Engine Settings.active_slots = product.image, product.video` — bu **boru hattı aktivasyonu**dur, politika statüsü değil; ikisi karıştırılmamalı.

---

## 7. T-040 / T-044 — Veri modeli (Faz 4)

**Bugünkü şema envanteri (canlı DB, bu koşum):**

| Ölçüm | 57b (19.08) | **Bugün** |
|---|---|---|
| Kurulu Media DocType | 10 | **13** (+`Media Folder`, +`Media Folder Item`, +`Media RUM Sample`) |
| Kaynağın 15'ine göre | 10/15 | **hâlâ 5 eksik:** Media Source · Media Policy · Media Policy Profile · Media Content Rule · Media Quality Report — dördü ADR-0016 ("politika veridir, kod değil") gereği bilinçli olarak JSON'da yaşıyor; DocType'a taşınmaları KARAR işi |
| UNIQUE indeksler | asset_key, rendition_key, idempotency_key | + **`Media Version.version_hash` UNIQUE** (bugün `SHOW INDEX` ile doğrulandı) |
| `content_sha256` | non-unique | **hâlâ non-unique** (teklik bilinçli olarak `asset_key` üçlüsünde — beyan edilmiş sapma sürüyor) |
| `version_hash` üretimi | üretimde tek girdili (KIRMIZI) | **KAPANDI:** `pipeline_bridge` artık `pipeline/core/dedup.py::version_hash` (4 girdi: source_hash, policy_snapshot, crop_intent, engine_version) kullanıyor; modül başlığı bunu açıkça belgeliyor |
| Rendition URL'i version_hash taşır (INV-09) | 0 dosya (KIRMIZI) | **KAPANDI: 92/92** türev `/files/media/{asset}/{64-hex}/…` — canlı DB'de sayıldı |
| `active_version` | kolon var, yazan yok | **hâlâ yazan yok** — `media/` altında grep 0 üretim isabeti; DB'de dolu satır **0/13**. T-064/4 açık |
| Yeni alanlar | — | `Media Asset.original_sha256` kolonu kurulu (bugün `SHOW COLUMNS`) |

**T-044 kalanları değişmedi (bugün yeniden bakıldı):** `docs/plans/rollback-doctypes.md` YOK; `scripts/seed_synthetic.py` YOK; 1M `EXPLAIN` provası tekrarlanamaz durumda. Kapının "migration + rollback provası" cümlesi hâlâ açık — bu AJAN işi, bu koşumun (kod yasağı) kapsamı dışında.
`docs/data/data-model-review.md` bu ölçümlerle güncellenmedi (koda-yakın belge, sahibi Şerit ajanları); güncel sayılar bu rapor + faz4 kapanış ekindedir.

---

## 8. T-043 — Uzlaştırma notu (ADR-taslak formatında; KARAR KULLANICIYA)

### ADR-taslak: Kalıcı `Media Usage` indeksi mi, istek-anı tarama mı?

**Durum:** ÖNERİ DEĞİL, UZLAŞTIRMA — iki meşru tasarım ölçümleriyle yan yana. Karar platform yöneticisinin.

**Bağlam (bugün ölçüldü):** Kapı (41-faz4 T-043) "asset takılıp çıkarılınca Usage kaydı güncellenir" diyor — kalıcı bir indeks ima ediyor. Bugünkü gerçek: `tabMedia Usage` **0 satır**; kullanım gerçeği **istek anında** `usage.py`'nin `LIVE_SOURCES` (**17 kaynak**) + `ORDER_SOURCES` (**5 kaynak**) taramasıyla üretiliyor; öksüz görünürlüğü `api/seller_media.py:252 list_orphans` ucunda; GC kullanım kapısının ölçülmüş etkisi **3.821 dosya / 1,06 GB koruma** (57b §1.3, kuru koşumla).

**Seçenek A — Kalıcı indeks (kapının lafzı):**
- Artıları: O(1) "bu asset nerede kullanılıyor" sorgusu; erişim damgası/istatistik doğal olarak birikir; öksüz raporu ucuz.
- Eksileri (ölçülü riskler): 22 kaynak alanın HER yazma yolunda senkron güncelleme gerekir — kaçırılan tek bir yol **kayıt sürüklenmesi** üretir ve sürüklenmiş indeks GC'ye "öksüz" yalanı söyler → **yanlış silme** riski tam da GC'nin koruduğu 3.821 dosyada. Frappe'de bu 22 yolu kancalamak (child table güncellemeleri dahil) kalıcı bakım yüküdür.

**Seçenek B — İstek-anı tarama (bugünkü gerçek):**
- Artıları: hakikat kaynağı canlı tablolar — sürüklenme İMKÂNSIZ; sıfır yazma-yolu bağımlılığı; bugün ölçülen koruma bu modelle çalışıyor.
- Eksileri: her GC/öksüz koşumunda tam tarama maliyeti (bugünkü ölçekte sorun değil: 5.084 dosya; 1M ölçeğinde ÖLÇÜLMEDİ); `Media Usage` DocType'ı boş duruyor — kapının lafzı karşılanmıyor; "kim, ne zaman taktı" tarihçesi tutulmuyor.

**Uzlaştırma önerisi (karar şablonu):** (1) B'yi resmileştir: kapı metnini "kullanım gerçeği istek-anı taramayla üretilir, Media Usage tablosu kaldırılır ya da önbellek olarak yeniden adlandırılır" diye revize et; ya da (2) A'ya geç: 22 kaynağı kancala + gecelik uzlaştırma (tarama ↔ indeks diff) alarmı ekle — sürüklenme riskini uzlaştırma işi taşır. **İkisinin ortası (indeksi yaz ama GC yine taramaya güvensin) bugünkü davranışı değiştirmez ve iki maliyeti birden öder; ancak geçiş dönemi güvencesi olarak savunulabilir.**

---

## 9. T-052 / T-053 — İmzalı URL, CDN, GC/retention (Faz 5)

### T-052 — canlı curl ölçümleri (bu koşum)

| Ölçüm | Sonuç |
|---|---|
| `/private/files/deneme.jpg` | **403** ✅ |
| `tradehub_core.api.media_access.get_signed_url` (misafir) | **403** ✅ |
| `tradehub_core.api.media_access.download` (imzasız) | **403** ✅ |
| Gerçek türev (`…/poster-1280.webp`) | **200**, `Content-Type: image/webp`, `Accept-Ranges: bytes`, `X-Content-Type-Options: nosniff` |
| `Range: bytes=0-99` | **206**, 100 bayt ✅ |
| HLS master (`…/hls/master.m3u8`) | **200**, `application/vnd.apple.mpegurl` |
| **Cache-Control (YENİ BULGU)** | Gerçek türevler `public, max-age=300, must-revalidate` dönüyor — **immutable DEĞİL.** Nginx map'i (`default.conf:53`) yalnız ESKİ `/files/{2hex}/{32hex}.ext` kalıbını tanıyor; üretimin BUGÜNKÜ adresi `/files/media/{asset}/{64hex}/…` map'e uymuyor. 57b'nin bulgusu tersine döndü: o gün "kural var, dosya yok"tu; bugün **"dosya var (92), kural eski kalıba bakıyor."** Düzeltme 1 satırlık nginx map işi (kod yasağı gereği yapılmadı) |
| Kriter 3 ("içerik değişince URL değişir") | İlk yarı **FİİLEN KAPANDI**: URL'ler version_hash taşıyor (4 girdili). `cdn_purge_*` alanlarını okuyan kod bugün de **0** (grep) — "purge kullanılabilir" yarısı açık |

### T-053 — scheduler kayıtlı + ÇALIŞIR (kapı "kayıtlı ama scheduler kapalı"ydı)

| Ölçüm | Sonuç |
|---|---|
| `bench scheduler status` | **enabled** (istoc.localhost) |
| `tabScheduled Job Type` | `run_scheduled_gc` + `_originals` + `_derivatives` — üçü de `stopped=0`, Daily |
| **Fiilî koşum** | `tabScheduled Job Log`: üçü de **Complete**, bugün 09:13:10 / 09:13:46 / 09:14:05 |
| Bayat bekçi (`test_hooks_kaydi_henuz_yok`) | **DÜZELTİLMİŞ** — test artık kaydın VARLIĞINI sabitliyor (`test_retention_gc.py:553` civarı, bugün okundu); 57b §1.4 kırmızısı kapanmış |
| Birleşik iş | `hooks.py:201` hâlâ kayıtlı — **bilinçli** (`:209` yorumu: "BİLEREK kaldırılmadı"); 3 kayıt tasarım gereği |
| Enforce durumu | `media_retention_gc_enforce*` anahtarları Media Engine Settings'te **yok** (tabSingles bugün sorgulandı) → koşumlar **kuru-koşum**: silme 0. "Kayıtlı + çalışır + hiçbir şey silmiyor" üçlüsü tam da tasarlanan güvenli durum |

### T-055 bonusu — S3 kabulü bağımsız yeniden koşuldu

Faz 5 kapanışının "S3/Mirror/Tiered kabul senaryoları SKIP" kalemi: rapor 87 bunları MinIO'ya açık env ile 4/4 geçirmişti. **Bu koşumda bağımsız tekrarlandı:** konteynerde `MEDIA_ENGINE_S3_*` → compose MinIO (`http://minio:9000`), geçici `t055-kabul-w8` bucket'ı → `test_storage_acceptance` **Ran 14 — OK, 0 skip** (s3_primary/mirror/tiered/yanlış-kimlik dahil). Bucket ve nesneler koşum sonrası silindi. Not: bu **dev-kabul**dür; gerçek hedef S3'te koşum hâlâ İNSAN/DevOps işi.

---

## 10. Sayım — bu koşumun kapanış hükmü

| Kalem | Eski durum | Bugünkü hüküm |
|---|---|---|
| T-003 istatistik | KISMİ (bayat + CSV yok) | **FİİLEN KAPANDI** (güncel ölçüm + CSV; yol adı sapması notlu) |
| T-004 INP | ÖLÇÜLEMEZ | **İLK ÖRNEK ÜRETİLDİ** (8,0 ms); mobil profil hâlâ açık |
| T-006 korpus | KISMİ | Görsel TAM · video 7/8 · 5 eksik tür listelendi (sentetik üretilmedi) |
| T-007 uygunluk | KISMİ (araçlar yok) | **FİİLEN KAPANDI** (pyvips hariç — ADR-0008 gereği karar-engeli değil) |
| T-010 AR-GE | KISMİ | Algoritma ölçümle kapalı; P-tablosu + simulator.html artefaktları açık |
| T-011 AR-GE | KISMİ | İçerik üretim verisinde yaşıyor; ayrı rapor artefaktı açık |
| T-015 AR-GE | KISMİ | Üretim ikamesi kapalı; MP bütçe tablosu ÖLÇÜLMEDİ olarak açık |
| T-014 notu | "KALİBRE EDİLMEDİ" | **Bugün de doğru** — değişiklik yok, İNSAN engeli |
| T-020/T-023 | KISMİ (vendor eksik + jsonschema yok) | **İki eksik de FİİLEN KAPANDI** (tam vendor 16/16 hash + 22/22 parite; jsonschema konteynerde 0 hata); "SABİT" kapısı KARAR'da |
| T-040/T-044 | KISMİ | version_hash/INV-09 kırmızıları **KAPANDI**; 13 DocType; rollback/1M provası açık (AJAN) |
| T-043 | KISMİ | Uzlaştırma ADR-taslağı yazıldı — **KARAR KULLANICIYA** |
| T-052 | KISMİ | 403/206/imza ölçümleri yeşil; **yeni bulgu:** immutable map'i yeni adres kalıbını kapsamıyor (1 satır nginx işi) |
| T-053 | KISMİ (scheduler kapalıydı) | **FİİLEN KAPANDI:** 3 iş kayıtlı + bugün Complete; kuru-koşum güvencesi ölçüldü |

## 11. Bu koşumda ölçülmeyenler

- Mobil cihaz profiliyle LCP/INP (T-004'ün ikinci profili).
- `test_retention_gc`'nin bugünkü tam koşumu (bekçi düzeltmesi kod okumasıyla doğrulandı, paket koşturulmadı).
- Gerçek hedef S3'te (MinIO dışı) kabul koşumu.
- 1M ölçekli EXPLAIN; DB restore provası (0 yedek seti durumu bugün yeniden sorgulanmadı).
- `content_rules` eşik kalibrasyonu (İNSAN etiketleme — değişmedi).
- Üretim (prod) ortamının hiçbir değeri — tüm ölçümler DEV.
