# T-145 — Faz 14 kabul dosyası: faz çıkış kriterleri ve kanıtları

**Görev:** T-145 · **Faz:** 14 · **Bağımlılık:** T-140…T-144 · **Tarih:** 2026-08-18
**Kaynak:** `docs/72-faz14-test-kabul.html` (T-145) + faz haritası (15 faz, 102 görev)

---

## 0. Bu belgenin kuralı

> **HİÇBİR KRİTER "GEÇTİ" İŞARETLENMEZ — KANITI YOKSA "KANIT YOK" YAZILIR.**

Dört işaret kullanılır ve anlamları burada sabitlenmiştir:

| İşaret | Anlamı |
|---|---|
| ✅ **KANITLI** | Kriter karşılandı **ve** kanıtı bu depoda bir dosya / koşulmuş bir test / ölçüm çıktısıdır. Kanıt sütununda yolu yazılıdır. |
| ⚠ **KISMEN** | Kriterin bir parçası kanıtlı, kalanı değil. Hangi parçanın eksik olduğu yazılıdır. |
| ❌ **KANIT YOK** | Kriter karşılanmamış **ya da** karşılandığı iddiasının kanıtı yok. İkisi ayrı ayrı belirtilir. |
| ⛔ **KAPSAM DIŞI** | Bu çalışma alanında üretilemez (üretim erişimi, tarayıcı, imza yetkisi). Sebebi yazılıdır. |

**Ölçüm beyanı.** Bu belgedeki sayılar üç kaynaktan gelir: (a) bu makinede
koşulmuş komut çıktısı, (b) `dosya:satır` referansı, (c) daha önceki bir
raporun ölçümü — o durumda rapor adı yazılıdır. **Üretim ortamına erişim
YOKTUR**; tüm koşumlar yerel makinede ya da `istoc-dev-backend-1`
konteynerindedir.

**Bu belge hiçbir kod dosyasını değiştirmedi.**

---

## 1. Kapanış karnesi — 15 fazın tamamı

Çıkış kriterleri kaynak dokümanın faz haritasından **birebir** alındı.

| Faz | Çıkış kriteri (kaynak doküman) | Durum | Kanıt / eksik |
|---|---|---|---|
| **0** · Kod tabanı araştırması | Upload slot ve medya korpusu envanteri **onaylandı** | ❌ **KANIT YOK** | Envanter var (`docs/reports/00-…, 01, 02, 03, 04, 06`), ama **kapanış raporunun kendisi "HAYIR" diyor**: `07-faz0-kapanis.md` §9.1. Dört bloklayıcı açık: D-2 (44 dosya KVKK), K-2, K-3, G-2 |
| **1** · AR-GE, desen doğrulama | Algoritmalar prototiplendi; **ADR seti imzalı** | ⚠ **KISMEN** | Prototipler ve ölçümler var: `docs/reports/11-faz1-arge.md` (10 görev), `05-kutuphane-benchmark.md` (360 koşum). **ADR dosyası YOK** — `find docs -iname "*adr*"` → 0 sonuç. İmza yok |
| **2** · Medya standartları | Tüm slot standartları sabit; **SRS onaylı** | ❌ **KANIT YOK** | 13 standart belgesi + 9/9 şema uyumlu politika var. **SRS HÂLÂ TASLAK** — `docs/srs/SRS-v1.0.md` ilk satırı: "DURUM: HÂLÂ TASLAK (DRAFT). Onaylanmadı." T1, T2, T4–T7 açık |
| **3** · Sistem mimarisi | SAD onaylı; **arayüz sözleşmeleri donduruldu** | ⚠ **KISMEN** | Sözleşmeler donduruldu: `tradehub_core/media/pipeline/contracts/signatures.golden.json` + `tests/test_contracts.py` (69 test) altın dosyayla sapma yakalıyor. **SAD "TASLAK"** (`docs/sad/SAD-v1.0.md:3`), onay bloğu boş |
| **4** · Veri modeli | DocType şemaları ve durum makinesi onaylı | ⚠ **KISMEN** | 16 DocType spesifikasyonu (`tradehub_core/media/pipeline/doctype_specs/*.json` + `_ddl.sql`), durum makinesi kodu ve 47 testi (`tests/test_state_machine.py`). **Şemalar Frappe'ye kurulmadı** (üretim ağacına yazılmadı, bilinçli) → "onaylı" imzası yok |
| **5** · Depolama, S3/CDN | Adaptörler, saklama, superadmin ayarları **işler durumda** | ⚠ **KISMEN** | 4 kip (`local/s3/mirror/tiered`) aynı sözleşme testinden geçiyor: `tests/test_storage_adapters.py` (74 test), saklama: `tests/test_retention.py` (47 test). **İşler DEĞİL**: ayar DocType'ı kurulmadı, gerçek S3'e karşı ÖLÇÜLMEDİ (boto3 yerelde yok) |
| **6** · Image Engine | Altın fixture testleri **YEŞİL**; idempotensi kanıtlı | ✅ **KANITLI** | 51 fixture (`tests/fixtures/media/manifest.json`), `tests/test_render.py` (73), `test_render_regression.py` (32), `test_image_*.py` (100). İdempotensi: `test_render.py::DefterTesti::test_ikinci_kosum_encode_etmez`, `::test_merdiven_idempotent`. Tümü bu makinede koştu |
| **7** · Video Engine | Fayda kapısı ihlali sıfır; **VMAF hedefleri tutuyor** | ⚠ **KISMEN** | Fayda kapısı: `tests/test_video_transcode.py::GercekTranscode::test_FAYDA_KAPISI_verimli_kaynagi_korur` (konteynerde gerçek ffmpeg ile). **VMAF ÖLÇÜLEMEDİ** — konteynerdeki ffmpeg 5.1.9 libvmaf içermiyor; testin adı bunu yazıyor: `test_kalite_olculebiliyor_ama_VMAF_YOK` |
| **8** · API katmanı | OpenAPI sözleşmesi + sözleşme testleri **YEŞİL** | ✅ **KANITLI** | `docs/api/openapi.yaml` (2.461 satır), `tests/test_api_contracts.py` (126 test) — belge↔kod bağı testle zorlanıyor (`BelgeKodBagiTesti`) |
| **9** · Media Library UI | Yükleme, listeleme, yetki akışı kabul edildi | ❌ **KANIT YOK** | Yalnız plan var: `docs/ui/faz9-media-library.md`. Arayüz **yazılmadı**; kabul oturumu yapılmadı |
| **10** · Crop Studio | Tek panelde düzenleme + canlı çoklu cihaz önizleme kabul edildi | ⚠ **KISMEN** | Geometri çekirdeği ve TS ikizi hazır, parite **ölçüldü**: `tests/test_crop_geometry.py` (37 test, 584 vektörde sapma 0,0 px). **Arayüz yazılmadı** (`docs/ui/faz10-crop-studio.md` plan) |
| **11** · Önizleme simülatörü | Onay öncesi cihaz+sayfa benzetimi **işler durumda** | ⚠ **KISMEN** | 13 cihaz × 5 sayfa = 65 kombinasyon hesaplanıyor ve testli: `tests/test_simulator_srcset.py` (34 test). **Satıcıya gösteren ekran yok** |
| **12** · Headless teslim | LCP bütçesi **sahada ölçüldü ve tutturuldu** | ❌ **KANIT YOK** | Teslim tarafı ilerledi (`tests/test_delivery_picture.py`, `test_delivery_sizes.py`) ve fazın kendi kabul raporu var: `docs/reports/12-performans-kabul.md`. **O rapor da kriteri kapatmıyor**: §1'de "Faz 12 'sonra' ölçümü henüz yapılmadı" yazıyor; 15 ölçütün 5'i "KAPATILAMADI" |
| **13** · Güvenlik, gözlemlenebilirlik | Pentest bulguları kapalı; metrik/alarm **yayında** | ❌ **KANIT YOK** | İlerleme var: `tests/test_isolation.py` (T-130), `test_svg_sanitize.py` (T-131), `test_observability.py` (T-133). **Pentest raporu yok** (`docs/security/` boş), **alarm yayında değil** |
| **14** · Test, doğrulama, kabul | **Tüm kabul kriterleri imzalı** | ❌ **KANIT YOK** | Bu faz üretildi (§2.14) ama imza bloğu boş (§7) ve önceki 13 fazın 11'i kapanmadı. İzlenebilirlik **%36,6** (hedef %100) |

### 1.1 Karne özeti

| Durum | Faz sayısı | Fazlar |
|---|---:|---|
| ✅ KANITLI | **2** | 6, 8 |
| ⚠ KISMEN | **7** | 1, 3, 4, 5, 7, 10, 11 |
| ❌ KANIT YOK | **6** | 0, 2, 9, 12, 13, 14 |
| ⛔ KAPSAM DIŞI | 0 | — |
| **Toplam** | **15** | |

**Kaynak dokümanın T-145 kriteri — "Tüm faz çıkış kriterleri işaretli ve
kanıtlı" — SAĞLANMIYOR.** 15 fazın 2'si kanıtlı.

---

## 2. Faz faz kanıt dosyası

Aşağıda her faz için: kanıtın **tam yolu**, ölçülmüş sayı ve —varsa— eksiğin
tam tanımı. Yalnız bu depoda gerçekten var olan dosyalar listelenmiştir.

### 2.0 Faz 0 — kod tabanı araştırması

**Üretilen:** `docs/reports/` altında 14 rapor (`00-ortam-envanteri.md`'den
`11-faz1-arge.md`'ye).

**Neden kapanmadı — kendi kapanış raporundan:** `07-faz0-kapanis.md` §9.2
tablosu dört kalemde ❌ veriyor:

| Kalem | Durum (o rapordan) |
|---|---|
| K-1 — KVKK: D-2 bulgusu **44 dosya** | ❌ bulgu açık |
| K-2 — bozuk komutlar (`istocc`, `istoc.localhost`) | ❌ düzeltilmedi (rapor yazıldığında) |
| K-3 — üretim imajında ffmpeg | ❌ ölçülmedi (üretim erişimi yok) |
| G-2 — çıktılar versiyonlandı mı | ❌ untracked |

**G-2 bugün de açık ve ölçüldü** (`git status --porcelain`, bu makinede):
`tradehub_core/media/pipeline/`, `docs/sad/`, `docs/api/`, `docs/test/`, `docs/ui/` dizinlerinin
**tamamı untracked**. Yani Faz 3–14'ün çıktıları **sürüm kontrolüne
girmemiştir**. Bu, tek bir `rm -rf` ile kaybedilebilecek bir durumdur ve
kabulün önündeki en ucuz kapatılabilir açıktır.

### 2.1 Faz 1 — AR-GE

**Kanıtlı:** `docs/reports/11-faz1-arge.md` on görevi tek tek yazıyor;
T-013 (hedef SSIM'e ikili arama) ölçümle kapandı ve kodu var
(`tradehub_core/media/pipeline/quality/ssim.py`, 21 test).

**Eksik:** "ADR seti imzalı". Bu depoda **hiçbir ADR dosyası yok**:

```bash
find docs -iname "*adr*"      # → 0 sonuç (bu makinede koşuldu)
```

Kararlar dağınık hâlde belge içlerinde (SAD §2.2 "sapmalar", migration.md
kararları). **Kararların kendisi kayıtlı, ADR biçimi ve imzası yok.**

### 2.2 Faz 2 — medya standartları

**Kanıtlı:** 13 standart belgesi (`docs/standards/*.md`), 9 slot politikası,
şema v1.3.0, 9/9 uyum (SRS §8.0'da yeniden koşuldu, 0 şema hatası).

**Eksik — SRS'in kendi beyanı:** belgenin ilk satırları:

> "DURUM: HÂLÂ TASLAK (DRAFT). Onaylanmadı. … T1, T2, T4, T5, T6, T7 açık."

Kapanmayan altı madde `SRS-v1.0.md` §0.3-B'de sayıyla listeli. Faz 2 çıkış
kriteri "SRS onaylı" olduğu için bu faz **kapanmamıştır**.

### 2.3 Faz 3 — mimari

**Kanıtlı ve güçlü:** arayüz sözleşmeleri **donduruldu ve dondurulmuşluğu
testle korunuyor**:

- `tradehub_core/media/pipeline/contracts/` — beş çekirdek Protocol
- `tradehub_core/media/pipeline/contracts/signatures.golden.json` — imza altın dosyası
- `tests/test_contracts.py::SignatureGoldenTest::test_altin_dosya_guncel` —
  imza değişirse test kırılır

**Eksik:** SAD `TASLAK` durumda (`docs/sad/SAD-v1.0.md:3`), gözden geçirme
notu var (`docs/sad/review-v1.0.md`) ama onay imzası yok.

### 2.4 Faz 4 — veri modeli

**Kanıtlı:** 16 DocType spesifikasyonu + `_ddl.sql`, iki eksenli durum
makinesi (`tradehub_core/media/pipeline/core/state.py`) ve 47 testi. Üretimdeki
`tradehub_core/media/states.py` ile **ayna tutarlılığı testle zorlanıyor**
(`YasamDongusuAynasiTesti`).

**Eksik:** şemalar Frappe'ye kurulmadı — bu **bilinçlidir** (mutlak kural:
`tradehub_core/` altına yazılmaz). Ama "onaylı" demek için kurulum ve migrate
provası gerekir; yapılmadı.

### 2.5 Faz 5 — depolama

**Kanıtlı:** dört kip aynı sözleşmeden geçiyor (`tests/test_storage_adapters.py`,
74 test); saklama süpürücüsü varsayılan **kuru koşum** ve varsayılan politika
hiçbir şeyi silmiyor (`tests/test_retention.py`, 47 test); legal hold "açık ama
kapısız" kurulumu **reddediyor**.

**Eksik ve açıkça yazılı:** S3 kipi **sahte istemciyle** koşuyor. Test
dosyasının kendi docstring'i: *"GERÇEK S3'e karşı ÖLÇÜLMEDİ — boto3 yerelde
kurulu değil… kanıtlamadığı şey: AWS/MinIO'nun bu sözleşmeye uyduğu."*

### 2.6 Faz 6 — Image Engine ✅

**Kriter:** altın fixture testleri YEŞİL, idempotensi kanıtlı.

| Kanıt | Ölçüm |
|---|---|
| `tests/fixtures/media/manifest.json` | 51 fixture (34 görsel + 10 kötücül + 7 video) |
| `tests/test_render.py` | 73 test |
| `tests/test_render_regression.py` | 32 test — bayt temel çizgisi **konteynerde** ölçülüp kilitlendi |
| `tests/test_image_{probe,normalize,classify,lqip}.py` | 100 test |
| İdempotensi | `DefterTesti::test_ikinci_kosum_encode_etmez`, `::test_merdiven_idempotent` |
| INV-05 (fayda kapısı) | `FixtureYapisiTesti::test_inv05_hicbir_turev_kaynaktan_buyuk_degil` |

**Koşum kanıtı (bu makinede, 2026-08-18, `tests/` kökünün tamamı):** `python3 -m unittest discover -s tests`
→ **1.376 test, OK (skipped=70, expected failures=1)**.

### 2.7 Faz 7 — Video Engine

**Kanıtlı:** karar tablosu 15 kural, hepsi en az bir kez tetikleniyor
(`test_video_decision.py::KuralTetikleme::test_her_kural_en_az_bir_kez_tetiklendi`);
gerçek ffmpeg ile transcode/remux/poster/klip/HLS testleri konteynerde koştu.

**KANIT YOK olan tek kalem:** *"VMAF hedefleri tutuyor"*. Ölçüm yapılamadı,
sebebi kayıtlı: konteynerdeki ffmpeg **libvmaf içermiyor**. Test bunu
gizlemek yerine adında taşıyor:
`test_kalite_olculebiliyor_ama_VMAF_YOK`.

> Bu, kabul dosyasının en net "KANIT YOK" maddesidir: kriter sayısal
> (**VMAF ≥ 93**), ölçüm aracı yok, dolayısıyla kriter **ne geçti ne kaldı**.

### 2.8 Faz 8 — API ✅

`docs/api/openapi.yaml` (2.461 satır) + `tests/test_api_contracts.py`
(126 test). Belge ile kod arasındaki bağ testle zorlanıyor:
`BelgeKodBagiTesti::test_koddaki_her_uc_belgede` ve
`::test_belgedeki_her_uc_ENDPOINTS_listesinde`.

Katman disiplini de testli: `KatmanDisiplinTesti::test_modul_duzeyinde_frappe_importu_yok`.

### 2.9–2.11 Faz 9, 10, 11 — arayüzler

Üçünün de **sunucu tarafı hazır ve testli**, **arayüzü yok**:

| Faz | Sunucu tarafı | Arayüz |
|---|---|---|
| 9 · Media Library | `tradehub_core/media/pipeline/api/upload.py`, `admin.py` | ❌ yok — plan: `docs/ui/faz9-media-library.md` |
| 10 · Crop Studio | `core/crop_geometry.py` + `.ts` ikizi (parite 0,0 px sapma), `api/crop.py` | ❌ yok — plan: `docs/ui/faz10-crop-studio.md` |
| 11 · Simülatör | `simulator/srcset.py`, 65 kombinasyon | ❌ yok — plan: `docs/ui/faz11-simulator.md` |

Bu üç fazın çıkış kriteri "kabul edildi" / "işler durumda" olduğu için, arayüz
olmadan **kapanamazlar**. Bu aynı zamanda T-142 pilotunun neden tam
koşulamadığının sebebidir (`docs/plans/faz14-uat.md` §1).

### 2.12 Faz 12 — headless teslim

`tests/test_delivery_picture.py` ve `test_delivery_sizes.py` (T-120/T-121)
`<picture>` ve `sizes` üretimini ölçülen kutu genişliklerine karşı sınıyor.

Fazın kendi kabul raporu **kriteri kapatmıyor** ve bunu açıkça yazıyor:
`docs/reports/12-performans-kabul.md` §0 — 6 ölçüt KANITLANDI, 4 HESAPLANDI
(üretime uygulanmadı), **5 KAPATILAMADI**; §1 — *"Faz 12 'sonra' ölçümü henüz
yapılmadı"*.

Laboratuvar taban çizgisi var (`03-performans-taban-cizgisi.md` §7, aynı
raporda tekrarlanmış): LCP mobil **776 / 1.062 / 919 / 740 ms** (ana sayfa /
listeleme / ürün detay / mağaza) — bütçenin (2.500 ms) altında. **Ama iki
şey bunu "tutturuldu" saymaya engel:**

1. Bu **laboratuvar** ölçümüdür, kriter **saha** diyor.
2. `srcset` / `sizes` / `<picture>` / `fetchpriority` **dört sayfada da
   0/22, 0/51, 0/31, 0/26** — yani ölçülen LCP, motor devrede olmadan alınmış
   "önce" değeridir. Ayrıca listeleme sayfasında **CLS = 0,51** (bütçe 0,1)
   → o bütçe **ihlal ediliyor**.

### 2.13 Faz 13 — güvenlik ve gözlemlenebilirlik

`tests/test_isolation.py` (T-130), `tests/test_svg_sanitize.py` (T-131),
`tests/test_observability.py` (T-133) üretildi.

**Eksik:** (a) pentest yapılmadı, `docs/security/` **boş**; (b) metrik/alarm
**yayında değil** — `docs/plans/faz14-golive.md` §4'te kurulacak eşikler
listeli ama hiçbiri kurulu değil.

### 2.14 Faz 14 — bu faz

| Görev | Çıktı | Durum |
|---|---|---|
| T-140 | `docs/test/traceability.md` + üreteci `scripts/gen_traceability.py` + `docs/test/req-test-map.json` | ✅ üretildi; **kriter sağlanmadı** (kapsama %36,6) |
| T-141 | `tests/test_e2e_scenarios.py` — 12 senaryo, 39 test | ⚠ üretildi; **Playwright/ekran kanıtı YOK** (§3.2) |
| T-142 | `docs/plans/faz14-uat.md` | ✅ plan üretildi; **pilot koşulmadı** |
| T-143 | `tradehub_core/media/pipeline/migration/backfill.py` + `tests/test_migration_backfill.py` (50 test) | ✅ kod ve test üretildi; **üretimde koşulmadı** |
| T-144 | `docs/plans/faz14-golive.md` | ✅ plan + 8 runbook üretildi; **geri dönüş provası ÖLÇÜLMEDİ** |
| T-145 | bu belge | ✅ üretildi; **imzasız** |

---

## 3. İzlenebilirlik matrisi — %100 değil, %36,6

### 3.1 Ölçüm

`scripts/gen_traceability.py` bu makinede koşuldu (2026-08-18):

| Ölçüm | Değer |
|---|---:|
| SRS'te ayrıştırılan gereksinim | **202** (150 FR + 52 NFR) |
| En az bir teste bağlı | **74** (**%36,6**) |
| **KAPSANMIYOR** | **128** (%63,4) |
| Taranan test dosyası | 111 |
| Taranan test fonksiyonu | 2.811 |

> **Not — 142 mi 150 mi:** Görev tanımı "142 FR" diyor; SRS'in **revizyon
> 2'si** ölçülen anomalilerden **FR-143…FR-150**'yi ekledi (§3.M). Bugün
> belgede **150 FR** vardır ve üreteç 150'sini de ayrıştırır. Fark
> belgelenmiştir, gizlenmemiştir.

### 3.2 Kriter neden sağlanmıyor

Kaynak doküman T-140: *"Her FR/NFR en az bir teste bağlı; bağsız gereksinim
yok."* Bağsız **128** gereksinim var. Sebep tek: **gereksinimlerin çoğu henüz
uygulanmamış fazlara ait** (F3, F3+ — arayüz, kota, rate limit, içerik
kuralları, SVG açılışı). Testi olmayan bir gereksinim için test yazmak
mümkün değildir; yazılırsa sahte yeşil olur.

**Kapsama sayımının kendisi de sıkılaştırıldı.** Üreteç üç kanıt sınıfı
ayırıyor ve **fixture izini (B) kapsam saymıyor**; gerekçesi ölçüldü:
`mode_rgba_alpha.png` fixture'ı FR-016'ya (oran toleransı) bağlı ama onu
kullanan LQIP testi oranı hiç sınamıyor. B sayılsaydı kapsama yapay olarak
%12 puan yüksek görünürdü.

---

## 4. Açık bulgular

**Sahip ve hedef tarih atanmadı** — bu belge bir atama yetkisi taşımıyor.
Boş bırakmak yerine "SAHİP ATANMADI" yazmak bilinçlidir; boş hücre
"unutuldu" ile "atanmadı"yı karıştırır.

| # | Bulgu | Şiddet | Kaynak | Sahip | Hedef | Geçici azaltım |
|---|---|---|---|---|---|---|
| **A-1** | Faz 3–14 çıktılarının **tamamı git'te untracked** | **KRİTİK** | `git status` (bu makinede) | SAHİP ATANMADI | — | Yok. Tek komutla kaybedilebilir |
| **A-2** | KVKK: D-2 bulgusu **44 dosya** sınıflandırılmadı | **KRİTİK** | `07-faz0-kapanis.md` §7.1 | SAHİP ATANMADI | — | Dosyalar bugünkü hâlinde duruyor |
| **A-3** | SRS **TASLAK**; T1, T2, T4–T7 açık | YÜKSEK | `SRS-v1.0.md` §0.3-B | SAHİP ATANMADI | — | Politikalar `status` alanıyla draft işaretli |
| **A-4** | VMAF ölçülemiyor (libvmaf yok) → Faz 7 kriteri kanıtsız | YÜKSEK | `test_video_transcode.py` | SAHİP ATANMADI | — | Bayt kazancı ve SSIM vekili ölçülüyor |
| **A-5** | İzlenebilirlik %36,6 (hedef %100) | YÜKSEK | `docs/test/traceability.md` | SAHİP ATANMADI | — | Kapsanmayan 128 gereksinim tek tek listeli |
| **A-6** | Faz 9/10/11 arayüzleri yok → UAT tam koşulamaz | YÜKSEK | `docs/ui/*`, `faz14-uat.md` §1 | SAHİP ATANMADI | — | UAT-1 dalgası bugünkü akışla koşulabilir |
| **A-7** | Geri dönüş provası koşulmadı, süresi ölçülmedi | YÜKSEK | `faz14-golive.md` §3.4 | SAHİP ATANMADI | — | Prosedür yazılı; bayrak mekanizması **yok** |
| **A-8** | Özellik bayrağı mekanizması **yok** → aşamalı açılış uygulanamaz | YÜKSEK | `faz14-golive.md` §1, §8-D2 | SAHİP ATANMADI | — | Yok |
| **A-9** | `media_engine` üretim yoluna **hiç bağlı değil** (0 referans) | ORTA | `grep -rn media_engine tradehub_core/` → 0 | SAHİP ATANMADI | — | Bu bir risk değil, bir **durum**: motor henüz devrede değil |
| **A-10** | Medya telemetri olayları yok → süre/terk ölçülemiyor | ORTA | `faz14-uat.md` §5, §9-D1 | SAHİP ATANMADI | — | Moderatör notu (zayıf) |
| **A-11** | Pentest yapılmadı; `docs/security/` boş | ORTA | `ls docs/security/` | SAHİP ATANMADI | — | Kötücül korpus (10 dosya) ve sanitize testleri var |
| **A-12** | S3 adaptörü gerçek S3'e karşı ölçülmedi | ORTA | `test_storage_adapters.py` docstring | SAHİP ATANMADI | — | Ayna kipinde birincil yerel; kesinti testli |
| **A-13** | 2400 px hedefi ↔ 2000 px tavanı ↔ 30 günlük arşiv → **geri dönülemez** piksel kaybı riski | **KRİTİK** | `migration.md` §2.5 (R1) | SAHİP ATANMADI | — | Backfill başlatılmadı; sıra kuralı yazılı |

---

## 5. ÖNCE / SONRA ölçüm özeti

Kaynak doküman T-145 "ölçülen sonuçlar özeti: ÖNCE/SONRA LCP, ortalama dosya
boyutu, depolama, işleme süresi, reddetme oranı" istiyor.

> **"SONRA" ÖLÇÜMÜ YOKTUR.** Motor üretim yoluna bağlı değil (A-9); dolayısıyla
> hiçbir "sonra" değeri üretilmedi. Aşağıdaki tablo yalnız **ÖNCE**
> sütununu doldurur ve "SONRA" sütununa sayı yazmak yerine ölçüm komutunu
> gösterir.

| Metrik | ÖNCE (ölçüldü) | SONRA | Nasıl ölçülecek |
|---|---|---|---|
| Dosya sayısı / hacim | **4.958 dosya / 1.559 MB** (4.350 public, 608 private) | — | `scripts/media_stats.py` |
| Megapiksel dağılımı | p50 **1,56** · p90 **5,01** · p99 **29,21** · max **72,71** | — | aynı |
| >20 MP dosya | **179** | — | aynı |
| CMYK / alfalı | **38** / **597** | — | aynı |
| Ürün detay sayfası görsel ağırlığı | **13,14 MB** (900 KB hedefinin **15 katı**) | — | Lighthouse / `03-performans-taban-cizgisi.md` yöntemi |
| `srcset` kullanan görsel | **0 / 31** (ana sayfa 0/22, listeleme 0/51) | — | `grep -c srcset` storefront |
| Çözünürlük metadatası (`th_media_width`) dolu | **0 / 2.853 (%0)** | — | SQL sayımı |
| Yetim disk dosyası | **1.166** | — | `tradehub_core/media/pipeline/core/usage.py` yetim raporu |
| Slot uyumsuzluğu | `product.image` **%48,6** · `document.attachment` **%91,8** · `category.banner` **%100** | — | `09-slot-bazinda-istatistik.md` yöntemi |
| Reddetme oranı (politika) | **ÖLÇÜLEMEZ** — slot bazlı ret üretimde yok | — | Anahtar A açıldıktan sonra ret kodu sayımı |
| İşleme süresi (dosya başına) | **ÖLÇÜLMEDİ** | — | `migration.md` §10-D1 dry-run ölçümü |
| LCP (saha) | **ÖLÇÜLMEDİ** | — | Lighthouse CI + saha (CrUX) |

**Ölçülmüş tek "iyileşme" yönü — ve sınırı:** türev merdiveninin bayt temel
çizgisi `tests/test_render_regression.py` içinde konteynerde ölçülüp
kilitlendi. Bu, **motorun ne ürettiğinin** ölçümüdür; **sayfanın ne kadar
hızlandığının** ölçümü değildir.

---

## 6. Devir (handover)

### 6.1 Doküman haritası

| Ne aranıyor | Nerede |
|---|---|
| Gereksinimler | `docs/srs/SRS-v1.0.md` (TASLAK) |
| Mimari | `docs/sad/SAD-v1.0.md`, `docs/sad/interfaces.md` |
| Slot standartları | `docs/standards/` (13 belge) + `tradehub_core/media/pipeline/policy/slots/` (9 politika) |
| Ölçüm raporları | `docs/reports/` (14 rapor) |
| Geçiş planı | `docs/plans/migration.md` + `scripts/plan_backfill.py` (planlayıcı) |
| Backfill uygulaması | `tradehub_core/media/pipeline/migration/backfill.py` |
| Devreye alma + runbook | `docs/plans/faz14-golive.md` |
| UAT | `docs/plans/faz14-uat.md` |
| İzlenebilirlik | `docs/test/traceability.md` (üreteç: `scripts/gen_traceability.py`) |
| Yedek/DR | `docs/plans/backup-dr.md` |
| API sözleşmesi | `docs/api/openapi.yaml` |

### 6.2 Operasyon eğitimi — içerik önerisi

1. **Runbook turu (2 saat):** `faz14-golive.md` §5'teki 8 senaryo; her birinin
   doğrulama komutu canlıda **bir kez koşulur** (çözüm adımı değil, yalnız
   doğrulama).
2. **Geri dönüş provası (1 saat):** §3.4'teki 5 adım; **süre ölçülür ve
   belgeye yazılır**.
3. **Backfill kuru koşumu (1 saat):** `plan_backfill.py` → plan JSON →
   `BackfillOrchestrator.run(dry_run=True)` → pano çıktısı okunur.
4. **Durdurma kriteri tatbikatı (30 dk):** hata oranı eşiğini geçici olarak
   %0,1'e indir, backfill'in gerçekten **durduğunu** gör.

### 6.3 Erişim listesi

| Erişim | Kim | Durum |
|---|---|---|
| Panel (Marketplace Admin) | Nöbetçi, medya sorumlusu | ATANMADI |
| Konteyner / bench konsolu | Nöbetçi | ATANMADI |
| Kuyruk ve log görünürlüğü | Nöbetçi | ATANMADI (alarm da yok) |
| Depolama (S3) kimlik bilgileri | Platform yöneticisi | ATANMADI |

### 6.4 Bakım takvimi (öneri)

| Sıklık | İş |
|---|---|
| Haftalık | `python3 scripts/gen_traceability.py --check` — matris bayat mı |
| Aylık | Yetim dosya raporu + disk kapasitesi |
| Üç aylık | Slot politikalarının gerçek veriyle uyum karnesi (`09-…md` yöntemi) |
| Üç aylık | Fixture korpusunun tazelenmesi (yeni anomali türleri) |

---

## 7. İmza

> **BU BELGE İMZALANMAMIŞTIR VE BUGÜN İMZALANAMAZ.**
> §1 karnesine göre 15 fazın 2'si kanıtlı, 6'sı kanıtsız. Kaynak dokümanın
> T-145 kriteri "tüm faz çıkış kriterleri işaretli ve kanıtlı" ile
> "izlenebilirlik matrisi %100" **sağlanmıyor**.

| Rol | Ad | Tarih | İmza |
|---|---|---|---|
| Geliştirme sorumlusu | — | — | — |
| QA sorumlusu | — | — | — |
| Platform yöneticisi | — | — | — |

**İmza öncesi kapanması gereken asgari küme** (bu belgenin önerisi):

1. **A-1** — çıktılar sürüm kontrolüne alınır (en ucuz, en yüksek etkili).
2. **A-2** — 44 dosyalık KVKK bulgusu sınıflandırılır.
3. **A-13** — türev profil kararı verilir; gerekiyorsa `presets.py` tavanı
   backfill'den **önce** yükseltilir.
4. **A-3** — SRS onaylanır ya da açık maddeleri kabul edilmiş sınır olarak
   imzalanır.
5. **A-7 / A-8** — bayrak yazılır, geri dönüş provası koşulur ve **süresi
   ölçülür**.

---

## 8. Yeniden üretme

```bash
cd /Users/ahmet/Desktop/istoc/tradehub_core

# İzlenebilirlik matrisi (§3)
python3 scripts/gen_traceability.py
python3 scripts/gen_traceability.py --check          # CI: bayat mı

# Test süiti (§2.6 koşum kanıtı)
python3 -m unittest discover -s tests

# Faz 14 testleri tek tek
python3 -m unittest tests.test_e2e_scenarios -v
python3 -m unittest tests.test_migration_backfill -v

# §2.0 G-2 açığı (untracked çıktılar)
git status --porcelain | grep '^??'

# §2.1 ADR yokluğu
find docs -iname "*adr*"
```
