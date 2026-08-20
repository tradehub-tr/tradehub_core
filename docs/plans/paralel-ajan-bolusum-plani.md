# Paralel ajan bölüşüm planı — çakışmasız çalışma haritası

**Tarih:** 2026-08-19 · **Kapsam:** Faz 14 hariç kalan **66 görev**
**Amaç:** N ajanı aynı anda, birbirinin işini bozmadan çalıştırmak.

---

## 1. Çakışmalar neden oluyor — bugün ÖLÇÜLDÜ

Bu plan teoriye değil, bugün yaşanan dört olaya dayanıyor:

| Olay | Sonuç |
|---|---|
| İki ajan aynı rapor numarasını (`18-`) seçti | Bir rapor ezilecekti, elle `19-`e taşındı |
| Bir ajan `bench migrate` koştu | Başka ajanın kurduğu `Media Storage Settings` DocType'ı **kayboldu**, iki uç HTTP 500 verdi |
| İki ajan `before_tests`e aynı anda girdi | `TimestampMismatchError`, koşum çöptü |
| Ben logo politikasına `w384` ekledim | Başka ajanın ölçümünde Faz 6 **kırmızı** çıktı (altın matris eskidi) |

**Darboğaz CPU DEĞİL.** Ölçüldü: bir ajan aktif çalışırken backend CPU **%0,01–0,03**.
Ajanlar zamanının neredeyse tamamını model çıkarımı bekleyerek geçiriyor.
CPU yalnız test/kodlama patlamalarında yanıyor.

Gerçek darboğaz: **paylaşılan değişebilir durum.**

---

## 2. Tek sahipli kaynak kütüğü

Bu kaynaklara **aynı anda yalnız BİR ajan** dokunabilir. İkincisi birincinin
işini ezer — kaç çekirdeğin olduğu fark etmez.

| # | Kaynak | Neden tek sahipli |
|---|---|---|
| S1 | `tradehub_core/hooks.py` | "Sona ekle" dosyası; iki ajan aynı bloğa yazar |
| S2 | `tradehub_core/permissions.py` | Aynı |
| S3 | `tradehub_core/patches.txt` + `patches/vNN_*.py` | Numara sırası; iki ajan aynı numarayı alır |
| S4 | `admin-panel/.../router/index.js` | Tek rota dizisi |
| S5 | `admin-panel/.../data/navigation.js` | Tek menü ağacı |
| S6 | `admin-panel/.../i18n/locales/{tr,en,ar,ru}.js` | Dört dosya, her ekran dördüne de yazar |
| S7 | `docker/docker-compose.yml` + `docker/nginx/` | Tek stack tanımı |
| S8 | `bench migrate` | Frappe kilidi — seri koşar |
| S9 | Canlı veritabanı (ölçüm) | Biri ölçerken başkası veriyi değiştirirse sayı yalan olur |
| S10 | `docs/reports/NN-` numarası | Bugün çakıştı |

**Kural:** her ajana bu 10 kaynaktan hangilerine dokunabileceği AÇIKÇA yazılır.
Yazılmayan = yasak.

---

## 3. Şerit tanımları

| Şerit | Eşzamanlı ajan | Sahip olduğu | Yasak |
|---|:--:|---|---|
| **A — Backend paylaşılan** | **1** | S1, S2, S3, S8 | — |
| **B — Backend izole** | 6 | Kendi modülü (`media/…`, `api/…`) | S1, S2, S3, S8 |
| **C — Panel görünüm** | 8 | Kendi `.vue` + `.js` dosyaları | S4, S5, S6 |
| **D — Belge/analiz** | 6 | Yalnız `docs/` altında kendi dosyası | Tüm kod |
| **E — Ölçüm** | **1** | S9 (canlı DB okuma/ölçüm) | Yazma |
| **F — Altyapı** | **1** | S7 | Diğer her şey |

**Toplam eşzamanlı: 23 ajan.** Bu sayı CPU'dan değil, **çakışmasız iş paketi
sayısından** geliyor.

### Rapor numarası dağıtımı (S10)
Dalga başlatılırken her ajana **önceden** numara verilir. Bugüne kadar
`00`–`37` kullanıldı. Sıradaki serbest numara: **38**.

---

## 4. Entegrasyon adımları — bunları ORKESTRATÖR yapar, ajan değil

Panel ajanlarına S4/S5/S6 yasak olduğu için, işleri bitince ekranlar menüde
görünmez. Bağlantıyı tek elden orkestratör kurar:

1. Tüm panel ajanları bitince, **tek seferde** `router/index.js` + `navigation.js`
   + 4 dil dosyası güncellenir.
2. Backend ajanları bitince, **tek** `bench migrate` koşulur.
3. Ölçüm işleri EN SON, makine sakinken koşulur.
4. Rapor numaraları çakışırsa orkestratör yeniden numaralandırır.

---

## 5. Her ajana verilecek ortak kurallar

Bugün işe yaradığı ölçülen kurallar — her prompt'a konur:

1. **Koşturmadığın bir şeye "geçti" DEME.** Ölçemediğini "ölçülmedi" yaz.
2. **Vacuity kanıtı:** test yazdıysan düzeltmeyi geçici geri al, KIRMIZI olduğunu
   göster, geri koy. (Bugün 6 ajan bunu yaptı, 3'ü sahte-yeşil yakaladı.)
3. **Mevcut raporlara güvenme**, çapraz kontrol için kullan.
4. **`reload_doc` sessizce `False` döner** — dönüşü kontrol et, yoksa yama
   "başarılı" görünürken hiçbir şey yapmaz. (Bugün iki kez oldu.)
5. **JSON'da doğru ≠ canlıda etkin.** Şema dosyasını değil `tabDocField`/
   `tabDocType`'ı ölç. (Bugün permlevel 4 JSON'da vardı, canlıda 1'di.)
6. **Süre/performans iddiası yapma** paralel koşarken — bugün çekişme
   69 sn/görsel yalanını üretti, gerçek 10,45 sn'ydi.
7. **`hooks.py` diff'i 0 silme** olmalı.
8. Sahte/fixture ile doğrulama yetmez — bu depoda test ikizleri üç ayrı yerde
   yanlış güven verdi (sahte S3 istemcisi, `PolicyEngine` Protokolü, sentetik
   video fixture'ları). En az bir yerde **gerçek** ölçüm yap.

---

## 6. Dalga sırası

### Dalga 1 — bağımsız, hemen başlayabilir (15 ajan)
Şerit B (6) + C (8) + F (1). Hiçbiri S1/S2/S3/S8'e dokunmuyor.

### Dalga 2 — Dalga 1'in çıktısına bağlı (7 ajan)
Şerit A (1, tüm `hooks.py`/`permissions.py`/patch işlerini toplu yapar)
+ D (6, Dalga 1 raporlarını okuyup faz kapanışlarını yazar).

### Dalga 3 — tek başına (1 ajan)
Şerit E. Makine sakinken: Lighthouse, yük testi, DR provası.

### Dalga 4 — insan
Faz 14 (UAT pilotu, go-live tatbikatı) ve **9 faz kapanış görevinin imzaları**.
Bunları ajan kapatamaz.

---

## 7. Görev → şerit ataması

Faz 14 hariç kalan **66 görev**. `[A]`…`[F]` şerit kodu.

### Şerit A — Backend paylaşılan  (2 görev)

| Görev | Durum | Başlık |
|---|---|---|
| T-040 | 🟡 | DocType şemalarının backend'e yazılması |
| T-044 | 🟡 | Faz 4 kapanış — veri modeli incelemesi |

### Şerit B — Backend izole  (19 görev)

| Görev | Durum | Başlık |
|---|---|---|
| T-010 | 🟡 | Kırpma/türev algoritma prototipi |
| T-015 | 🟡 | Client-side işleme bütçesi |
| T-017 | ❌ | Güvenlik AR-GE: bomb, polyglot, SVG, metadata |
| T-025 | 🟡 | İçerik uygunluk kuralları ve eşikler |
| T-033 | 🟡 | PolicyEngine tasarımı ve uygulaması |
| T-043 | 🟡 | Kullanım takibi ve öksüz tespiti |
| T-053 | 🟡 | Retention, arşivleme, GC işleri |
| T-064 | 🟡 | Idempotency ve yeniden işleme |
| T-072 | 🟡 | Transcode, fayda kapısı, kalite doğrulaması |
| T-073 | 🟡 | Poster, preview klip, hareketli önizleme |
| T-074 | 🟡 | HLS / adaptif teslim |
| T-080 | 🟡 | OpenAPI sözleşmesi (contract-first) |
| T-082 | 🟡 | Crop intent + önizleme uçları |
| T-084 | 🟡 | Yönetim uçları + contract testleri |
| T-123 | 🟡 | Gerçek kullanıcı telemetrisi (RUM) |
| T-131 | 🟡 | SVG sanitizasyonu, CSP, dosya servis güvenliği |
| T-132 | 🟡 | Yetki sertleştirme ve sızıntı testleri |
| T-133 | 🟡 | Gözlemlenebilirlik: metrik, log, iz, alarm |
| T-134 | 🟡 | Denetim izi ve KVKK uyumu |

### Şerit C — Panel görünüm  (19 görev)

| Görev | Durum | Başlık |
|---|---|---|
| T-081 | ❌ | Upload session + resumable (tus) |
| T-090 | 🟡 | İskelet, tasarım sistemi, API istemcisi |
| T-091 | ❌ | Uppy + tus yükleyici ve preflight paneli |
| T-092 | 🟡 | Grid, arama, filtre, sanal kaydırma |
| T-093 | 🟡 | Detay çekmecesi: versiyon/rendition/kullanım/kalite |
| T-094 | 🟡 | Klasör/etiket organizasyonu + toplu işlemler |
| T-095 | 🟡 | Erişilebilirlik ve i18n doğrulaması |
| T-100 | 🟡 | Crop çekirdeği: paylaşılan geometri |
| T-101 | 🟡 | Crop stage (tutamak, zoom, focal) |
| T-102 | 🟡 | Canlı çoklu önizleme (rendition kartları) |
| T-103 | 🟡 | Otomatik odak önerisi + güvenli alan |
| T-104 | 🟡 | Politika uyarıları + crop intent kaydı |
| T-110 | 🟡 | Cihaz ve yerleşim kataloğunun veri olarak tanımı |
| T-111 | ❌ | Cihaz çerçevesi ve sayfa şablonu render motoru |
| T-112 | 🟡 | srcset seçim göstergesi + çözünürlük yeterlilik uyarısı |
| T-113 | 🟡 | Video slotu için poster/oynatma simülasyonu |
| T-114 | ❌ | Onay kapısı ve `previewed_placements` kaydı |
| T-120 | 🟡 | MediaImage / MediaVideo teslim bileşenleri |
| T-121 | 🟡 | `sizes` değerlerinin gerçek düzenden türetilmesi |

### Şerit D — Belge/analiz  (14 görev)

| Görev | Durum | Başlık |
|---|---|---|
| T-009 | 🟡 | Faz 0 kapanış + çıkış kriteri onayı |
| T-019 | 🟡 | Faz 1 kapanış: ADR seti |
| T-020 | 🟡 | Ürün görseli standardı + politika şeması |
| T-023 | 🟡 | Kalan slotların standartları |
| T-029 | 🟡 | Faz 2 kapanış: SRS onayı |
| T-030 | 🟡 | SAD yazımı |
| T-031 | 🟡 | Arayüz sözleşmelerinin dondurulması |
| T-035 | 🟡 | Faz 3 kapanış: mimari gözden geçirme ve dondurma |
| T-055 | ❌ | Faz 5 kapanış — depolama kabul testleri |
| T-067 | 🟡 | Faz 6 kapanış — golden fixture regresyonu |
| T-075 | 🟡 | Faz 7 kapanış — video regresyon + kaynak bütçesi |
| T-085 | 🟡 | Faz 8 kapanış: dondurma + SDK |
| T-105 | ❌ | Faz 10 kapanış: crop doğruluk kabulü |
| T-135 | 🟡 | Faz 13 kapanış: sızma + yük + kaos |

### Şerit E — Ölçüm  (10 görev)

| Görev | Durum | Başlık |
|---|---|---|
| T-003 | 🟡 | Üretim medya istatistiği |
| T-004 | 🟡 | Frontend render envanteri + LCP taban çizgisi |
| T-006 | 🟡 | Golden fixture korpusu |
| T-007 | 🟡 | Kütüphane uygunluk testi |
| T-011 | 🟡 | Pazaryeri kural ve yetenek kıyaslaması |
| T-054 | 🟡 | Yedekleme ve felaket kurtarma |
| T-115 | ❌ | Simülatörün gerçek sayfayla doğrulanması (drift testi) |
| T-122 | 🟡 | LCP optimizasyonu ve preload stratejisi |
| T-124 | 🟡 | Faz 12 kapanış: performans kabulü |
| T-130 | ⬜ | Worker izolasyonu ve kaynak limitleri |

### Şerit F — Altyapı  (2 görev)

| Görev | Durum | Başlık |
|---|---|---|
| T-032 | ❌ | Frappe app iskeleti ve modül yapısı |
| T-052 | 🟡 | CDN teslim, imzalı URL, cache stratejisi |

**Toplam:** 66 görev · dağılım: {'E': 10, 'D': 14, 'B': 19, 'F': 2, 'A': 2, 'C': 19}
