# 33 — Faz 0/1/2/3 görevlerinin ÖLÇÜMLE doğrulanması

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **Kapsam:** T-000…T-009, T-010…T-019, T-020…T-029, T-030…T-035
**Kaynak pano:** https://karacaismail.github.io/imageoptimization/docs/91-gorev-panosu.html — **çekildi** (14.663 B)
**Kaynak faz sayfaları:** `10-faz0-codebase-arastirma.html`, `21-faz1-arge-gorevleri.html`,
`30-faz2-medya-standartlari.html`, `40-faz3-mimari.html` — **dördü de çekildi**, kabul kriterleri
aşağıdaki tablolara **kaynaktan birebir** alındı.

> **Bu belge hiçbir kaynak dosyayı değiştirmedi.** Yazılan tek dosya bu rapordur.
> Konteynere kopyalanan 5 geçici ölçüm betiği ve 1 geçici dizin koşum sonrası silindi
> (`rm` doğrulandı). Hiçbir doctype'ta kayıt oluşturulmadı.
> `Media Engine Settings` bayrakları ölçüm öncesi ve sonrası okundu:
> `media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0` — **değişmedi**.

---

## 0. Yöntem ve dürüstlük beyanı

Bu görevin talebi açıktı: **mevcut raporlara güvenme, ölç.** Uygulanan kural:

| İşaret | Anlamı |
|---|---|
| **[Ö]** | Bu oturumda ölçüldü — komut ve çıktı aşağıda. |
| **[T]** | Bu oturumda test koşuldu — modül adı ve sonucu aşağıda. |
| **[K]** | Kod/dosya okundu, varlığı ve içeriği doğrulandı. |
| **[R]** | Yalnız mevcut rapora dayanıyor — **tekrarlanmadı**. |

**Koşum ortamı:** `istoc-dev-backend-1` (Docker), site `istoc.localhost`. Uygulama imaja
gömülü; ölçüm betikleri `docker cp` ile taşındı, `frappe-bench/env/bin/python` ile koşturuldu.
Makinede paralel üç ajan daha çalışıyordu — **hiçbir süre/performans iddiası yapılmadı**,
yalnız geçti/kaldı ölçüldü.

**Ölçülmeyen alanlar, baştan:** T-008 (depolama maliyeti), T-011 (rakip analizi),
T-013 (SSIM ikili arama), T-014 (saliency), T-020–T-028 standart metinlerinin
içerik doğruluğu. Bunlar **[R]** işaretlidir; iddiaları tekrarlanmadı.

---

## 1. Koşulan testler — ham çıktı

Kaynak sayfa Faz 1'de *"'Okudum, iyi görünüyor' kabul edilmez"* diyor. Bu bölüm, bu
raporun "geçti" dediği her yerin karşılığıdır.

### 1.1 Frappe'siz birim testleri (`env/bin/python -m unittest`)

```
tradehub_core.tests.test_contracts          Ran  69 tests   OK
tradehub_core.tests.test_policy_engine      Ran  38 tests   OK
tradehub_core.tests.test_state_machine      Ran  47 tests   OK
tradehub_core.tests.test_storage_adapters   Ran 137 tests   OK
tradehub_core.tests.test_crop_geometry      Ran  37 tests   OK (skipped=1)
tradehub_core.tests.test_policy_dpi         Ran  19 tests   OK (expected failures=1)
tradehub_core.tests.test_dedup              Ran  57 tests   OK
tradehub_core.tests.test_image_probe        Ran  16 tests   OK
tradehub_core.tests.test_image_normalize    Ran  25 tests   OK
tradehub_core.tests.test_image_classify     Ran  32 tests   OK
tradehub_core.tests.test_enforcement        Ran   6 tests   OK
─────────────────────────────────────────────────────────────
                                            483 test, 0 hata
```

`test_crop_geometry` konsol çıktısı (kaynağın T-010 kabul kriterinin sayıları):

```
[çapraz]     crop.py ↔ crop_geometry.py en büyük sapma = 1.818989e-12 px
[çapraz-kutu] 800 örnek · 1 px yuvarlama farkı olan = 0
[oran]       3652 örnek · en büyük bağıl oran sapması = 2.070e-16
[vektör]     584 vektör · en büyük sapma = 0.0 px (yok)
```

### 1.2 Bench/site testi

```
$ bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_jobs
Ran 12 tests in 0.038s
OK
```

### 1.3 KOŞULAMAYAN

- `tradehub_core.tests.test_media_naming` → `Ran 0 tests · FAILED (errors=3)`
  (import hatası; frappe bağlamı gerektiriyor). **Bu modül için "geçti" denmiyor.**
- `jsonschema` **konteynerde kurulu değil** (`pip show jsonschema` → *Package(s) not found*)
  ve `requirements.txt`/`pyproject.toml` bağımlılıklarında **yok**. Politika şema
  doğrulaması bu yüzden host'ta (jsonschema 4.25.1) koşuldu. → FR-003'ün "CI'da koşar"
  şartı bugünkü imajda **karşılanamaz**.

---

## 2. FAZ 0 — Keşif (T-000…T-009)

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt / komut |
|---|---|---|---|---|
| **T-000** | Depo ve ortam envanteri | Tüm sürümler tabloda, "bilinmiyor" satırı yok; libvips/FFmpeg kurulu mu + derleme desteği net; upload limitleri sayısal | **TAM** | **[K]** `docs/reports/00-ortam-envanteri.md` (39.290 B). **[Ö]** Bağımsız doğrulama: `ffmpeg -version` → `5.1.9-0+deb12u1`, konfigürasyonda `--enable-libx264 --enable-libvpx --enable-libaom --enable-libsvtav1 --enable-libwebp --enable-libdav1d` **var**; `which vips convert` → **boş** (kurulu değil); `env/bin/python -c "import pyvips"` → `ModuleNotFoundError`; Pillow **12.2.0**. Raporun "ffmpeg VAR / libvips YOK" tespiti **doğrulandı**. ⚠ Rapor ailesinde Pillow **11.3.0** yazan yerler var (`05-fixture-korpusu.md`) — konteynerdeki gerçek **12.2.0**; sürüm kayması var. |
| **T-001** | Upload slot envanteri | En az 8 slot listede; her slot için render bileşeni + CSS kutu ölçüsü; doğrulama boşlukları işaretli | **TAM** | **[K]** `00-upload-slot-envanteri.md` (53.049 B). **[Ö]** Kaynağın saydığı 8 slotun 8'i de belgede geçiyor (`grep -oiE 'product-image\|seller-logo\|brand-logo\|company-cover-video\|category-banner\|document-attachment\|user-avatar\|product-video' → 8/8`); 112 tablo satırı. |
| **T-002** | Frappe dosya akışı | Upload→File→disk→URL zinciri diyagramla; ≥3 genişletme noktası artı/eksiyle; private yetkilendirme açık | **TAM** | **[K]** `01-dosya-akisi.md` (26.341 B), **1 mermaid bloğu**; `doc_events` (§1.2, §4.2), `before_insert`/`after_insert` kanca listeleri, G2 genişletme önerisi mevcut. |
| **T-003** | Üretim medya istatistiği | Slot bazlı p50/p90/p99; ≥20 anomali dosya yoluyla; logo + company video ayrı | **KISMİ** | **[K]** `02-medya-istatistigi.md` (46.441 B) + `09-slot-bazinda-istatistik.md` var; koşum çıktısı `10-media-stats-kosum-ciktisi.txt` (2.853 dosya taranmış) ve betik `scripts/media_stats.py` var. ❌ Kaynağın istediği **`fixtures/media-stats.csv` yolu YOK** — repo kökünde `fixtures/` dizini hiç yok (`[ -d fixtures ]` → YOK). |
| **T-004** | Frontend render envanteri + LCP taban çizgisi | **4 sayfa tipi × 2 cihaz profili** için Lighthouse LCP/CLS/görsel bayt tablosu; en kötü 10 ürün sayfası; hedef değerler yazılı | **KISMİ** | **[K]** `03-performans-taban-cizgisi.md` (20.227 B) + `03-render-envanteri.md` (39.119 B). Masaüstü (§0 Ölçüm A, 1366×768) **ve** mobil profilleri var; LCP 19, CLS 17 satırda. ❌ **`Lighthouse koşulmadı`** — belgenin kendi §6.1'i *"Lighthouse — ÖLÇÜLEMEDİ"* diyor; sayılar Chrome DevTools performance trace'inden. Kabul kriteri adıyla Lighthouse istiyor. |
| **T-005** | Yetki ve rol modeli | Rol→izin matrisi; satıcının başka satıcının medyasına erişemediği **kanıtlı (test çıktısı)**; superadmin-only permission deseni | **TAM** | **[K]** `04-yetki-modeli.md` (38.325 B), 24 kod bloğu, `frappe.PermissionError` yakalayan negatif test çıktıları gömülü. **[T]** İlgili izolasyon testleri repoda: `test_file_multirow_isolation.py`, `test_kyc_tenant_isolation.py`, `test_payment_transaction_isolation.py` — **bu oturumda koşulmadı [R]**. |
| **T-006** | Golden fixture korpusu | **≥30 görsel + ≥8 video**; her fixture manifest'te; kötücüller ayrı `fixtures/malicious/`; toplam < 1 GB | **KISMİ** | **[Ö]** `tradehub_core/tests/fixtures/media/`: **34 görsel**, **7 video** (kaynak ≥8 istiyor → **eksik**); `tradehub_core/tests/fixtures/malicious/`: **10 dosya** (ayrı dizin ✅). `manifest.json` **51 kayıt**, `gecti=51 kaldi=0`, `toplam_mb=60.84` (< 1 GB ✅), sınıf dağılımı `photo 17 · transparent 5 · graphic 10 · animation 2 · video 7 · malicious 10`. ❌ Kaynağın istediği kök `fixtures/` yolu yok; korpus `tradehub_core/tests/` altında. |
| **T-007** | Kütüphane uygunluk testi | 30 MB mockup'ta tepe bellek her iki kütüphane için; kazanan sayısal gerekçeyle; betik **tekrar çalıştırılabilir** | **KISMİ** | **[K]** `05-kutuphane-benchmark.md` (27.186 B) + ham veri `docs/reports/bench.csv` (69.225 B, 360 satır) + `scripts/bench_engine.py`. Karar: *"Pillow'da kal + `draft()` ekle; 588 MB → 172 MB"*. ❌ **Tekrar çalıştırılamaz:** **[Ö]** `pyvips` bugün konteynerde **kurulu değil** (`ModuleNotFoundError`); raporun kendisi de *"pyvips kurulumu kalıcı değil (AS-28)"* diyor. ❌ Kaynağın istediği `fixtures/bench.csv` yolu yerine `docs/reports/bench.csv`. |
| **T-008** | Depolama ve maliyet taban çizgisi | Türev projeksiyonu formülle; 3 senaryo 12 aylık maliyet; eager vs lazy farkı sayısal | **TAM [R]** | **[K]** `06-depolama-maliyet.md` (38.847 B); ≈34 → gerçek **51 eager / 59 eager+lazy**, 2.858 varlıkta ~168.600 dosya / ~11,3 GB projeksiyonu. **Bu oturumda yeniden hesaplanmadı.** |
| **T-009** | Faz 0 kapanış + çıkış kriteri onayı | 7 rapor tutarlı; fixture manifest programatik doğrulanmış; açık sorular atanmış; **platform yöneticisi imzası alınmış** | **KISMİ** | **[K]** `07-faz0-kapanis.md` (77.514 B), Rev.2. ❌ **[Ö]** §10 ONAY bloğu **tamamen boş**: K-1…K-4 ve K-23…K-25'in her kutucuğu `☐` işaretsiz; §10.4 Faz 1 geçiş kararı işaretsiz; §10.5'te Ad/Rol/Tarih/İmza dört alan da `______`. Kaynağın imza şartı **karşılanmadı**. Belge kendisi *"Faz 0 hâlâ kapanamıyor"* diyor. |

### 2.1 D-2 — hassas hash örtüşmesinin CANLI DB'de yeniden ölçümü **[Ö]**

`docs/reports/19-d2-hash-ortusme.md` §1.2'nin **kendi tanımı** (üç yolun birleşimi:
`attached_to_doctype ∈ presets.EXCLUDED_DOCTYPES` **veya** `presets.EXCLUDED_MEDIA_FIELDS`
ters referansı **veya** `is_private=1`) bağımsız bir betikle yeniden uygulandı.

```
EXCLUDED_DOCTYPES (8): Data Export Request, KYB Verification, KYC Verification, Order,
                       Payment Transaction, Seller Application, Seller Certification,
                       Seller Verification

=== BİRLEŞİM (üç yolun) ===
distinct public file_url = 40
kırılım (dosya-satır etiketi): KYB Verification 86 · KYC Verification 8 · Brand 4
                               · Seller Application 1 · Seller Verification 1
_is_protected_pii = True olan public file_url            = 0 / 40
TÜM public dosya (2.879) içinde _is_protected_pii = True = 0
tabFile satır sayısı: is_private=0 → 4.399 · is_private=1 → 615
```

**Sonuç — rapor 19 doğrulandı, ama "kapandı" değil "azaldı":**

| İddia (rapor 19 §5.4) | Bu oturumun ölçümü | Karar |
|---|---|---|
| Düzeltme sonrası **40** public dosya (44 → 40) | **40** | ✅ **DOĞRULANDI** |
| `Order` ve `Payment Transaction` kırılımdan tamamen düştü | Kırılımda **ikisi de yok** | ✅ **DOĞRULANDI** |
| `_is_protected_pii = True` olan public dosya **0** | **0 / 40**, ayrıca **0 / 2.879** (tüm public küme) | ✅ **DOĞRULANDI** |

> **Ama Faz 0'ın bloklayıcısı D-2 kapanmadı, daralt­ıldı.** Hassas `content_hash`
> paylaşan **40 public dosya hâlâ duruyor** (36'sı `KYB Verification` karşı taraflı).
> Kapatılan şey, politikanın *koruduğunu iddia ettiği* 4 dosyaydı. Raporun kendi
> §6'sı bunu zaten Ö-1…Ö-6 olarak açık bırakıyor; en kritiği **Ö-1**
> (`_is_protected_pii` **retroaktif değil** — yalnız `set_level` anında çalışır)
> ve **Ö-6** (bu ölçümün tamamı yerel dev verisi; üretimde tekrarlanmadı).
>
> ⚠ **Yapısal not [Ö]:** `_is_protected_pii` bir **DB kolonu değildir** —
> `tabFile`'da `pii`/`protect` içeren hiçbir kolon yok. `media/access_level.py:72`
> içinde bir fonksiyondur ve her çağrıda `frappe.db.exists()` ile 8 doctype ×
> 14 alanı tarar. Yani "hangi dosyalar korumalı" sorusunun **sorgulanabilir** bir
> cevabı yok; ancak dosya dosya hesaplanabiliyor.

---

## 3. FAZ 1 — AR-GE (T-010…T-019)

**Yapısal tespit:** Kaynak sayfa Faz 1 için `prototypes/cropgeo/`, `prototypes/client-budget/`,
`prototypes/storage/`, `tests/vectors/crop-vectors.json`, `media_engine/image/dpi.py`,
`media_engine/image/quality.py`, `media_engine/core/safety.py`, `media_engine/video/decision_table.json`
ve `docs/reports/10-…` … `18-…` adlı **9 ayrı rapor** istiyor. **[Ö]** Bu yolların
**hiçbiri yok**: `prototypes/` YOK, `tests/vectors/` YOK, `media_engine/` YOK.
Karşılık işlevsel olarak `tradehub_core/media/pipeline/` altında ve tek bir raporda
(`11-faz1-arge.md`, 46.310 B, T-010…T-019'u kapsıyor) toplanmış.

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt / komut |
|---|---|---|---|---|
| **T-010** | Kırpma/türev algoritma prototipi | **≥200 vektör**, hepsi sınır içi + orana %0,5 toleransla; öncelik zincirinin **5 seviyesi** ayrı ayrı test; **P-01…P-16 izlenebilirlik tablosu tam**; simülatörle ≤0,5 px; INV-10 | **KISMİ** | **[Ö]** `tradehub_core/tests/fixtures/crop_vectors.json`: `vector_count=592`, gerçek `len(vectors)=592` (≥200 ✅), `tolerance_px=0.5`. **[T]** `test_crop_geometry` → 37 test OK; ölçülen en büyük sapma **0.0 px**, çapraz uygulama sapması **1.8e-12 px**, oran sapması **2.07e-16** (≪ %0,5 ✅). ❌ **[Ö]** **P-01…P-16 izlenebilirlik tablosu YOK**: `grep -rn 'P-01' docs/reports/` → yalnız 2 isabet, ikisi de fixture/canlı-ölçüm raporunda, izlenebilirlik tablosu değil. ❌ Öncelik zincirinin 5 seviyesinin **ayrı ayrı** test edildiği doğrulanamadı. ❌ `docs/simulator.html` ile parite **ölçülmedi** (0.0 px, referans üreteciyle karşılaştırma). |
| **T-011** | Pazaryeri kural ve yetenek kıyaslaması | Amazon/Alibaba kuralları **kaynak linkli ve sayısal**; "var/yok/gereksiz" yetenek matrisi; ≥10 somut kural | **KISMİ [R]** | **[K]** `11-faz1-arge.md` §T-011 — belgenin **kendi başlığı**: *"Rakip analizi (masa başı, **ölçüm YOK**)"*. Kaynağın istediği `docs/reports/11-rakip-analizi.md` ayrı dosyası yok. İçerik doğruluğu bu oturumda denetlenmedi. |
| **T-012** | DPI / çözünürlük normalizasyon | INV-02 testi **GREEN**; 5 formatta DPI yazımı; 3000×3000@300 → **≥2000×2000**, asla 700×700 | **TAM** | **[T]** `test_policy_dpi` → **19 test OK (expected failures=1)**. Fixture `dpi_3000x3000_300dpi.tif` korpusta mevcut **[Ö]**. ⚠ 1 "beklenen başarısızlık" var — hangi formatın DPI yazımının tutmadığı bu oturumda ayrıştırılmadı. |
| **T-013** | Uyarlanabilir kalite (SSIM hedefli) | q85'e göre sayısal kazanç; arama ≤4 encode'da yakınsıyor; şeffaf/grafik sınıfında lossless doğru | **TAM [R]** | **[K]** `11-faz1-arge.md` §T-013.1–.9, dokuz alt bölüm, hepsi `[Ö]` işaretli; `scripts/measure_ssim_quality.py` var. Bu oturumda **yeniden koşulmadı**. |
| **T-014** | Smart crop / focal öneri | Her yöntem için ortalama sapma; beyaz zeminde en iyi yöntem gerekçeli; güven skoru eşiği | **TAM [R]** | **[K]** `11-faz1-arge.md` §T-014 + ADR-0017 (`n=400 canlı` dağılım). Yeniden koşulmadı. |
| **T-015** | Client-side işleme bütçesi | Cihaz sınıfı × işlem × max güvenli MP tablosu; Safari canvas limitleri; "client başarısız → sunucu devralır" **prototipte çalışıyor** | **KISMİ** | **[K]** `11-faz1-arge.md` §T-015.1 kod okuması `[K]`, §T-015.2 çift-encode cezası `[Ö]`. ❌ **[Ö]** `prototypes/client-budget/` **YOK**; çalışan prototip gösterilmedi. Cihaz sınıfı × MP tablosu doğrulanmadı. |
| **T-016** | Video codec karar motoru + benefit gate | Karar tablosu **JSON, veri olarak**; verimli MP4 passthrough; şişik dosya ≥%40 küçülüyor + VMAF ≥93; çıktı > girdi yayınlanmıyor | **TAM** | **[Ö]** `tradehub_core/media/pipeline/policy/video_decision.json` **var** — karar tablosu veri. Fixture'lar korpusta: `video_efficient_720p_750k.mp4`, `video_bloated_720p_8m.mp4`. **[K]** VMAF/AV1 ölçümü ayrı raporda (`22-t072-vmaf-av1.md`, 63.662 B). ADR-0007 (fayda kapısı INV-05) ve ADR-0010 (AV1 ertelendi) kararı kayıtlı. Transcode ölçümü bu oturumda koşulmadı **[R]**. |
| **T-017** | Güvenlik AR-GE: bomb, polyglot, SVG, metadata | **`fixtures/malicious/` içindeki HER dosya reddediliyor**, hiçbiri tam decode edilmiyor | **YOK** | ❌ **[Ö] Bu oturumda yeniden ölçüldü.** Konteynerde `upload_policy.check(file_name, content)` 10 kötücül fixture'a uygulandı: <br>`RED = 2` (`empty_zero_byte.jpg` → `upload_content_empty`; `script_payload.svg` → `upload_ext_denied`) <br>`GEÇTİ = 8` — `bomb_100mp.png`, `executable_as.png`, `jpeg_with_html_tail.jpg`, `polyglot_pdf_as.jpg`, `polyglot_png_as.jpg`, `truncated.jpg`, `data_uri_svg.txt`, `fake_docx.docx`. <br>`11-faz1-arge.md` §T-017.1'in *"kanca yolu 2/10"* sütunuyla **birebir aynı** — bulgu **tekrarlandı ve doğrulandı**. 100 MP decompression bomb **hâlâ geçiyor**. Kabul kriteri kategorik olarak karşılanmıyor. |
| **T-018** | Depolama adapter ve CDN AR-GE | **Aynı test paketi üç adapter'da da geçiyor** (contract test); S3 kapalıyken sistem tamamen yerel; purge + imzalama çalışıyor | **TAM** | **[T]** `test_storage_adapters` → **137 test OK**. **[Ö]** `tradehub_core/media/pipeline/storage/`: `local.py`, `s3.py`, `mirror.py`, `tiered.py`, `retention.py` — dördü de var. **[K]** `23-t051-s3-adaptor.md` (36.183 B), `27-t052-cdn-teslim.md` (19.638 B). ADR-0015: *"S3 yazıldı, varsayılan kapalı"*. |
| **T-019** | Faz 1 kapanış: ADR seti | Her ADR: bağlam·seçenekler·**ölçüm verisi**·karar·sonuçlar·**geri dönüş yolu**; **en az 8 konuda ADR** (image engine, video engine, **client kütüphane seti**, depolama, **CDN**, smartcrop, kalite stratejisi, karar tablosu); her ADR bir Faz 0/1 raporundaki sayısal veriye atıf; **reddedilen seçeneklerin geri dönüş koşulu yazılı** | **KISMİ** | **[Ö]** `docs/adr/` — **17 ADR + README** (bugün yazıldı, `30-faz1-adr-kapanis.md` ile). ✅ 17/17'sinde `Bağlam · Seçenekler · Karar · Gerekçe · Sonuçlar` bölümleri tam. ✅ **15/17** ADR en az bir `docs/reports/…` atıfı taşıyor (0001→5 atıf, 0002→3, 0009→3, 0015→3, 0016→3…). ⚠ **0011** ve **0012** hiç rapor atıfı taşımıyor — yalnız `dosya:satır` (`transcode.py:357-360`, `render.py:934`); README kuralı "**ya** dosya:satır **ya** rapor" dediği için biçimsel ihlal değil, ama kaynağın "**Faz 0/1 raporundaki sayısal veriye atıf**" şartını karşılamıyor. ❌ **"Geri dönüş yolu" ayrı bölümü hiçbir ADR'de YOK** — şablon 5 bölümlü; yalnız **4/17**'sinde metin içinde geri dönüş koşulu geçiyor (0002, 0003, 0008, 0010). ❌ **İstenen 8 konudan 2'si karşılıksız: "client kütüphane seti"** (`grep -lie 'mediabunny\|istemci kütüphane\|client-side\|uppy' docs/adr/*` → **0 dosya**) ve **"CDN"** (yalnız 0001'de geçiyor, ADR konusu değil). `30-faz1-adr-kapanis.md` §2'nin "istenen 8 ADR" tablosu **kaynak sayfadaki listeyle aynı değil** — farklı bir 8'liyi eşliyor. ❌ **İmza yok** — raporun kendi §4'ü bunu açıkça *"AÇIK"* bırakıyor. |

---

## 4. FAZ 2 — Standartlar (T-020…T-029)

### 4.1 Politika `status` alanlarının CANLI SAYIMI **[Ö]**

`tradehub_core/media/pipeline/policy/slots/*.json` üzerinde bağımsız betik:

| Politika | `status` | `open_questions` | `encoder_quality` null | `master.max_megapixels` |
|---|---|---:|---:|---|
| `brand-logo.json` | `draft` | 1 | 0 | ❌ **YOK** |
| `category-banner.json` | `draft` | 6 | 3 | 2.0 |
| `company-cover-image.json` | `draft` | 6 | 5 | 1.64 |
| `company-cover-video.json` | `draft` | 8 | 0 | 0.93 |
| `document-attachment.json` | `draft` | 6 | 0 | 25 |
| `product-image.json` | `draft` | 7 | 5 | 5.76 |
| `product-video.json` | `draft` | 6 | 1 | 0.93 |
| `seller-logo.json` | `draft` | 3 | 0 | ❌ **YOK** |
| `user-avatar.json` | `draft` | 6 | 0 | 0.0655 |
| **TOPLAM** | **`active` = 0 / 9** | **49** | **14** | **2 politikada eksik** |

> **`docs/reports/16-t029-politika-aktivasyonu.md`'nin üç sayısı da bağımsız olarak
> DOĞRULANDI:** `ACTIVE 0/9`, `open_questions TOPLAM = 49`, `encoder_quality null = 14`,
> ve "gerçek olan 2 hata" = `master.max_megapixels` iki logo politikasında yok.

### 4.2 Şema doğrulaması **[Ö]** — rapor 16'nın 9/9 iddiası

```
$ python3 (jsonschema 4.25.1) — Draft202012Validator(slot-policy.schema.json)
brand-logo.json              hata=0        document-attachment.json     hata=0
category-banner.json         hata=0        product-image.json           hata=0
company-cover-image.json     hata=0        product-video.json           hata=0
company-cover-video.json     hata=0        seller-logo.json             hata=0
                                           user-avatar.json             hata=0
TOPLAM HATA = 0        → şemaya uyumlu politika 9/9
```

- ✅ Rapor 16'nın *"şemaya uyumlu politika: 9/9"* satırı **doğrulandı**.
- ❌ `docs/srs/SRS-v1.0.md` §T3'ün *"3 politika dosyası şemaya uymuyor"* tespiti
  **artık geçerli değil** — SRS bu noktada **eskimiş**.
- ❌ Rapor 16'nın G1 satırındaki *"betik çıkış kodu 1, 6 hata"* **tekrarlanmadı**:
  o çıktıyı üreten betik repoda bulunamadı (`scripts/` altında politika doğrulayıcı yok;
  `grep -rn 'validate_polic\|policy_validate'` → 0 sonuç). Raporun gövdesinde çıktısı
  yapıştırılmış (D3×2, D4×2, D5×2) ama **betiğin kendisi commit'lenmemiş**. → G1 için
  bu raporun verdiği tek bağımsız sayı yukarıdaki jsonschema `0 hata`'dır.
- ❌ **FR-147 tek kaynak ihlali sürüyor [Ö]:** iki politika seti yan yana —
  `tradehub_core/media/pipeline/policy/slots/` (**9 dosya**) ve
  `docs/standards/policies/` (**13 dosya**, farklı adlandırma: `listing.primary_image.json`,
  `seller.logo.json`…). Kanonik set kararı **verilmemiş**.

### 4.3 12 kararın kapanışı — `logo.md` §13 ve `company-cover-video.md` §10.9 **[Ö]**

| Belge / bölüm | Kapanan kararlar | Nasıl |
|---|---|---|
| `logo.md` §13.0 | **K1, K2** | Ölçümle (2026-08-18): JPEG payı **9/18 = %50** > tetik %10 → K1 = **B** (öneri A düştü); band dışı **2/18 = %11** < %20 → K2 = **A** korundu |
| `logo.md` §13 | **K3** | Ölçümle (2026-08-19): 512 rung `p50 27.162 B · max 109.172 B`, 5/18 tavanı aşıyor → **B (5 rung, +384)**, varsayılan A düştü |
| `logo.md` "VARSAYILANDA ONAYLANAN" | **K4, K5, K6** | Varsayılanda onay (3) |
| `company-cover-video.md` §10.9 | **K2, K7, K8** | Platform yöneticisi kararı (3); **K7 öneriden AYRILDI** (rendition'lar kotadan sayılacak) |
| `company-cover-video.md` "VARSAYILANDA ONAYLANAN" | **K1, K3, K4, K5, K6** | Varsayılanda onay (5) |
| | **TOPLAM = 14** | |

✅ **Rapor 16'nın "G4 geçti — 14/14" iddiası doğrulandı.** 12'si bugün (2026-08-19), 2'si dün.

⚠ **Ama kanıt, belgenin kendi beyanıdır.** İki belgede de onayı taşıyan şey
*"platform yöneticisi tarafından onaylanmıştır"* cümlesidir; **imzalı bir onay bloğu,
tarih/ad alanı ya da ayrı bir onay artefaktı yok.** `07-faz0-kapanis.md` §10.5'teki gibi
doldurulacak bir imza tablosu bu iki belgede hiç kurulmamış.

### 4.4 Görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-020** | Ürün görseli standardı + politika şeması | Şema tüm alanları içeriyor; ihlal yüzdesi raporlanmış; **jsonschema ile doğrulanıyor**; 2000×2000 master ile çelişki yok | **KISMİ** | ✅ **[Ö]** `product-image.json` jsonschema **0 hata**; `docs/standards/product-image.md` var. ❌ Mevcut ürün görsellerinin **ihlal yüzdesi ölçülmemiş** — politikanın kendi `open_questions`'ı (7 madde) bunu açıkça söylüyor: *"require.* kurallarının GEÇMİŞE dönük uygulanıp uygulanmayacağı belirsiz… ölçülmedi"*. ❌ `jsonschema` konteynerde kurulu değil → doğrulama üretim yolunda koşamaz. |
| **T-021** | LOGO standardı (seller-logo, brand-logo) | Her render yeri listeli + DPR 3 dahil max piksel; oran seti ve min piksel **sayı olarak**, "TBD" yok; ihlal yüzdesi + geçiş planı; koyu tema kararı; SVG kabul kuralı | **TAM** | **[K]** `docs/standards/logo.md` (1.290+ satır): 16 render noktası (S1…S16) `dosya:satır` ile; band **1:2…2:1**; master **1:1 saydam letterbox**; merdiven 64/128/256/**384**/512; ihlal ölçümü n=18 (§13.0); §D8 koyu tema; §6 SVG sanitize kuralı. **[Ö]** `seller-logo.json`+`brand-logo.json` jsonschema 0 hata. ⚠ Politikalarda hâlâ `open_questions` 3+1 açık ve `master.max_megapixels` **yok** → politika `active` olamıyor. |
| **T-022** | COMPANY COVER VIDEO standardı | Süre/çözünürlük/oran/byte/bitrate **sayı olarak**, TBD yok; otomatik oynatma politikası; poster kuralı; ihlal oranı + geçiş planı; `prefers-reduced-motion` | **TAM** | **[K]** `docs/standards/company-cover-video.md` (1.090+ satır): §6.1–§6.13 sayısal kararlar; §6.9 "ilk anlamlı kare" poster kuralı; §8.2 `prefers-reduced-motion`; §10.9 + K8 geçiş penceresi. ⚠ **[Ö]** `company-cover-video.json` `open_questions = 8` — en kritiği *"ffmpeg üretim imajında var mı"* (yerelde **VAR**, üretimde **ölçülmedi**) ve *"video için ölçü/süre metadatası yok → süre/oran/çözünürlük kapılarının hiçbiri zorlanamaz"*. Standart yazılı, **zorlanabilir değil**. |
| **T-023** | Kalan slotların standartları | Slot kataloğundaki **tüm satırlar "SABİT"**; her slot şema doğrulamasından geçiyor; TR mesaj metinleri; slot→profil eşlemesi tam | **KISMİ** | ✅ **[Ö]** 9/9 politika jsonschema 0 hata; `docs/standards/` altında 9 slot belgesi (`product-image`, `product-video`, `category-banner`, `company-cover-image`, `company-cover-video`, `document-attachment`, `user-avatar`, `logo`, + `README`). ❌ Hiçbir slot "SABİT" değil: **9/9 `draft`**, toplam **49 açık soru**. |
| **T-024** | DPI/piksel normalizasyon kuralı şartnameye | Kural örnekli yazılı; 2000×2000 altına düşmeme **testle bağlı**; şemada `min_long_edge`/`max_long_edge`/`dpi_out` zorunlu; kullanıcı özet metni tasarlanmış | **TAM** | **[T]** `test_policy_dpi` → **19 test OK** (1 expected failure). **[K]** `docs/standards/dpi-ve-cozunurluk.md` var; SRS'te FR karşılıkları var. |
| **T-025** | İçerik uygunluk kuralları ve eşikler | Her kural için yöntem+eşik+aksiyon tabloda; eşikler **kalibre edilmiş**, yanlış pozitif < %5 ölçülmüş; NSFW/bulanıklık dışında sert red yok; uyarı metinleri | **KISMİ** | **[K]** `docs/standards/icerik-kurallari.md` + `policy/content_rules.json` + `scripts/calibrate_content_rules.py` var. ❌ **Kalibrasyon yapılmamış**: rapor 16 G5'i *"`UNCALIBRATED`, değişmedi"* diye açık bırakıyor; `product-image.json` `open_questions`'ı *"7 kuralın eşiği kalibre edilmedi ve 3'ünün (`text_area_ratio`, `watermark_suspect`, `collage_suspect`) dedektörü kod tabanında hiç yok"* diyor. Yanlış pozitif oranı **ölçülmedi**. |
| **T-026** | Retention politikası standardı | İki bağımsız politika (`original_retention`, `derivative_retention`); varsayılanlar; soft-delete + audit; legal hold | **TAM** | **[K]** `docs/standards/retention.md` + `policy/retention.schema.json` + `media/pipeline/storage/retention.py` + `26-t053-saklama-gc.md` (18.797 B). **[Ö]** `Media Asset` doctype'ında `legal_hold` alanı var. ADR-0014 (yıkıcı işler çift kapı + kuru koşum). |
| **T-027** | Kota ve oran sınırlama standardı | Plan bazlı sınırlar; aşım davranışı + kullanıcı mesajı; **429 + `Retry-After`** | **TAM [R]** | **[K]** `docs/standards/kota.md` + `policy/quota.schema.json` + `tradehub_core/api/rate_limit.py`. `test_media_quota.py` repoda; **bu oturumda koşulmadı**. |
| **T-028** | Geçiş (migration) planı | Uyumlu/uyumsuz sayısal, slot bazlı; 3 kategori; backfill parti/hız/geri alma; satıcı bilgilendirme + son tarih; kuyruk önceliği | **TAM [R]** | **[K]** `17-t028-backfill-plani.md` (44.825 B) + `scripts/plan_backfill.py`. İçeriği bu oturumda denetlenmedi. |
| **T-029** | Faz 2 kapanış: SRS onayı | FR-xxx/NFR-xxx test edilebilir; **izlenebilirlik matrisi**; **hiçbir slot "TBD" değil**; **platform yöneticisi onayı alınmış** | **KISMİ** | **[Ö]** `docs/srs/SRS-v1.0.md`: **2.188 satır**, **FR-001…FR-150 (150 benzersiz)**, **NFR 52 benzersiz**, `scripts/gen_traceability.py` var. ❌ **`TBD` 18 satırda geçiyor**. ❌ **[Ö]** §6.2'nin *"Aşağıdakiler tamamlanmadan hiçbir slot politikası `active` yapılamaz"* listesindeki **20 kutucuğun 20'si de `[ ]` işaretsiz**. ❌ Rapor 16'nın 7 kapı tablosu bağımsız olarak kısmen doğrulandı: **G4 ✅** (14/14, §4.3), **G6 ❌** (0/9 active, §4.1), **G7 ❌** (2 politikada `max_megapixels` yok, §4.1), **G5 ❌** (`UNCALIBRATED`), **G3 ❌** (49 açık soru), **G1 🟡** (jsonschema 0 hata ama kanonik set kararı yok, betik commit'lenmemiş), **G2 ✅ [R]**. → **SRS `v1.0 ONAYLI` olamaz** — doğrulandı. |

---

## 5. FAZ 3 — Mimari (T-030…T-035)

### 5.1 SAD'ın 8 bloklayıcısından ÜÇÜNÜN bağımsız doğrulaması **[Ö]**

`docs/reports/21-t030-mimari-inceleme.md` **M-01, M-02, M-04, M-07, M-09, M-10, M-14, M-18**
bloklayıcılarını sayıyor. Görev en az 3'ünü kendim doğrulamamı istedi; **üçü seçildi ve
kodda yeniden ölçüldü.**

#### M-02 — `PolicyEngine` protokolü ile somut sınıf örtüşmüyor **✅ DOĞRULANDI (13/13)**

Konteynerde çalıştırılan runtime karşılaştırması:

```python
from tradehub_core.media.pipeline.contracts.policy import PolicyEngine as Proto
from tradehub_core.media.pipeline.policy.engine  import PolicyEngine as Concrete
from tradehub_core.media.pipeline.fakes.policy   import InMemoryPolicyEngine as Fake
```

```
Protokol metotları (13): check_accept, check_geometry, check_video, effective_limits,
                         load, master_spec, quality_threshold, reload, rendition_specs,
                         slots, source_root, validate, video_rendition_specs
Somut sınıf public metotları (2): evaluate, normalized_targets

KESİŞİM: []                        → örtüşme = 0
EKSİK (protokolde var, somutta yok) = 13 / 13
isinstance(Concrete(), Proto) = False          ← runtime_checkable Protocol
Fake metotları (13), protokolü kapsıyor mu: True
```

> **13 metodun 13'ü de örtüşmüyor** — görev brifinginin verdiği sayı **birebir doğrulandı**.
> Protokolü uygulayan **tek** sınıf `fakes/policy.py::InMemoryPolicyEngine`'dir; yani
> `contracts/policy.py` bugün yalnız **test sahtelerini** bağlıyor, üretim motorunu değil.
> `test_contracts` (69 test) yeşil kalıyor **çünkü** sahteye karşı koşuyor.

#### M-01 — SAD §2.1 dizin ağacı gerçek bir dizini göstermiyor **✅ DOĞRULANDI**

```
[ -d media_engine ]  → YOK          (repo kökünde böyle bir dizin yok)
[ -d tests ]         → YOK          (testler tradehub_core/tests/ altında: 126 test dosyası)
tradehub_core/media/pipeline/  → 16 alt dizin · 71 .py dosyası
SAD içinde "media_engine" geçen gövde satırı: 66, 69, 102, 122, 167, 209  → 6 satır
```

Raporun *"6 satır hâlâ `media_engine` diyor"* tespiti **birebir doğrulandı**.

#### M-04 — S-03 "Yeni DocType açılmaz" kararı çürüdü **✅ DOĞRULANDI — ve rapordan bir fazlası var**

```
tradehub_core/tradehub_core/doctype/media_asset
tradehub_core/tradehub_core/doctype/media_engine_settings
tradehub_core/tradehub_core/doctype/media_processing_job
tradehub_core/tradehub_core/doctype/media_profile
tradehub_core/tradehub_core/doctype/media_rendition
tradehub_core/tradehub_core/doctype/media_storage_settings     ← rapor 21 bunu saymıyor
                                                        → 6 DocType
patches.txt: v15_9_21_media_pipeline_doctypes · v15_9_22_media_engine_settings
             · v15_9_23_media_profile_seed · v15_9_25_media_storage_settings
doctype_specs/ → 17 spesifikasyon
```

Rapor 21 **5** DocType diyor; bugün **6** var (T-051 ile `Media Storage Settings` eklenmiş).
Bloklayıcı geçerli, **kapsamı raporda yazandan bir birim daha geniş**.

### 5.2 Görev tablosu

| ID | Başlık | Kaynağın kabul kriteri | Durum | Kanıt |
|---|---|---|---|---|
| **T-030** | SAD yazımı | Bileşen/dağıtım/veri akışı/durum diyagramları (mermaid); her bileşen için sorumluluk+bağımlılık+hata davranışı+ölçek sınırı; **her ADR kararı mimaride izlenebilir**; SPOF listesi + azaltım | **KISMİ** | **[Ö]** `docs/sad/SAD-v1.0.md` **849 satır** (rapor 21 yazıldığında 782'ydi — belge o günden beri büyüdü, §14 eklendi). Durum makinesi, kuyruk tablosu, arayüz sözleşmeleri, C4 diyagramları var. ❌ Belge **TASLAK**; satır 789: *"Onay bloğu doldurulmamıştır"*; satır 801: *"SAD v1.0 bugün ONAYLANAMAZ"*. ❌ **8 bloklayıcı** — 3'ü yukarıda bağımsız doğrulandı (M-01, M-02, M-04); kalan 5'i (M-07, M-09, M-10, M-14, M-18) **bu oturumda doğrulanmadı [R]**. |
| **T-031** | Arayüz sözleşmelerinin dondurulması | **5 çekirdek arayüz** `Protocol`/ABC; her metot için tip imzası + hata sınıfı + idempotency; her arayüz için **fake + contract test**; **arayüz değişikliği CI'da kırmızı verir** | **KISMİ** | ✅ **[Ö]** 5 Protocol: `storage.py`, `image.py`, `video.py`, `policy.py`, `delivery.py` (her biri `@runtime_checkable`); `errors.py` (306 satır hata sınıfları); `signatures.py` + `signatures.golden.json` (`protocols` + `value_types`). ✅ 5 fake: `fakes/{storage,image,video,policy,delivery}.py`. ✅ **[T]** `test_contracts` → **69 test OK**; `golden["protocols"]` uzunluğu 5 olarak assert ediliyor ve `topla()` ile karşılaştırılıyor → imza kayması testte kırmızı verir. ❌ **CI kırmızı vermez: [Ö]** `.github/workflows/` içinde **5 workflow var (alpha/beta/rc/prod-release, deploy)** ve hiçbirinde `pytest`/`unittest`/`run-tests`/`ruff`/`mypy` adımı **yok** (`grep -nE 'run-tests\|pytest\|ruff\|mypy\|lint\|unittest' → 0 isabet`). Sözleşme testi elle koşulmadıkça kimseyi durdurmuyor. |
| **T-032** | Frappe app iskeleti ve modül yapısı | `bench new-app media_engine`; modüller core/image/video/storage/delivery/policy/api/ui; `hooks.py` kuyruk+scheduler+doc_events+permission query; **CI: ruff + mypy + pytest + pre-commit çalışıyor**; Docker compose ayakta; temiz kurulum/kaldırma | **YOK** (kaynağın tanımıyla) / **ADR ile geçersizleşti** | **[Ö]** Ayrı app **kurulmadı** — bu **bilinçli**: ADR-0003 *"Ayrı app değil, tek monolit"*. Modül karşılığı `tradehub_core/media/pipeline/` altında **16 alt paket** (core, image, video, storage, delivery, policy, api, quality, security, simulator, migration, observability, contracts, fakes, doctype_specs). `hooks.py` bağlı (`permission_query_conditions`, `has_permission`, scheduler `retention.run_scheduled_gc`, `doc_events`). Docker compose 14 servis ayakta. ❌ **CI kalemi tamamen açık [Ö]:** `ruff` **yalnız `pyproject.toml`'da yapılandırılmış**, koşan bir workflow yok; **`[tool.mypy]` bloğu yok** (0 isabet); **`.pre-commit-config.yaml` YOK**. Kaynağın 5 kabul kriterinden **1'i** (hooks) karşılanıyor. |
| **T-033** | PolicyEngine tasarımı ve uygulaması | `evaluate(slot, probe, role) → {allow, violations[], normalized_targets}`; politikalar **veri olarak** yükleniyor; her ihlal için makine kodu + TR mesaj + düzeltme önerisi; **aynı motor client tarafında da çalışıyor (paylaşılan JSON, TS uygulaması) ve iki taraf aynı sonucu veriyor (çapraz test)** | **KISMİ** | ✅ **[Ö]** `policy/engine.py:541 evaluate(self, slot, probe, role)` + `:1166 normalized_targets()` + `Decision.to_dict()` — imza kaynağa **uyuyor**. ✅ Politikalar veri: `PolicyRegistry.load()` `SLOT_DIR`'den okuyor; yeni slot = yeni JSON. ✅ **[T]** `test_policy_engine` → **38 test OK**. ✅ Makine kodu + TR mesaj: `_code()`, `_message()`, `MESSAGE_KEYS` haritası; `messages.tr` her politikada. ❌ **TS uygulaması YOK [Ö]:** `find . -name '*.ts' -path '*polic*'` → yalnız `tradehubfront/src/pages/refund-policy.ts` (alakasız). Paylaşılan TS politika motoru **hiç yazılmamış**; **çapraz test yok**. (TS ikizi olan tek modül `crop_geometry.ts` — o T-100'ün işi, politika motoru değil.) ❌ M-02: protokolle örtüşme **0/13**. |
| **T-034** | İş kuyruğu ve durum makinesi altyapısı | Geçersiz geçiş istisna fırlatıyor + testle korunuyor; her iş `Media Processing Job` üretiyor (kuyruk/deneme/süre/hata/kaynak); retry üstel geri çekilme + dead-letter + alarm; **iş idempotent** | **TAM** | ✅ **[T]** `test_state_machine` → **47 test OK**. Test adları kabul kriterlerini birebir karşılıyor: `test_bilinmeyen_durum_hata_verir`, `test_terminal_durumlardan_cikis_yok`, `test_backoff_kaynakla_ayni_egriyi_verir`, `test_retry_sayilari_ayni`, `test_deneme_hakki_tukenmesi`, `test_ayni_icerik_ayni_anahtar`, `test_ilk_talep_verilir_ikincisi_verilmez`, `test_biten_is_sonucu_tekrar_kullanilir`, `test_kilit_ttl_dolunca_dusen_worker_engel_olmaz`, `test_cekirdekte_frappe_importu_yok`. ✅ **[T]** `bench run-tests test_media_jobs` → **12 test OK**. ✅ **[Ö]** `Media Processing Job` doctype kurulu, alanlar: `status`, `attempt`, `idempotency_key`, `started_at/finished_at`, `duration_ms`, `peak_memory_mb`, `error_code/error_trace`. ✅ Dead-letter: `media/transcode.py:313 _dead_letter(...)`; backoff: `pipeline/core/jobs.py:101 backoff_seconds()`; idempotency: `jobs.py:126 idempotency_key()` + `pipeline_bridge.py:446` DB tekilleştirmesi. |
| **T-035** | Faz 3 kapanış: mimari gözden geçirme ve dondurma | **Bağımsız bir gözden geçiren (yazan kişi değil) SAD'i onaylamış**; arayüz imza testleri GREEN + golden commit'lenmiş; açık mimari riskler + izleme planı | **KISMİ** | ✅ **[T]** Arayüz imza testleri **GREEN** (`test_contracts` 69 OK) ve `signatures.golden.json` commit'li. ✅ **[K]** `docs/sad/review-v1.0.md` var (2026-08-18) — risk kaydı ve donan kararlar yazılı; kendi §1'i *"Karar katmanı çalışıyor, hat bağlı değil… canlıda hiçbir davranış değişmedi"* diyor. ❌ **SAD ONAYLANMAMIŞ:** onay bloğu boş; ve *bağımsız* incelemenin kendisi (`21-t030-mimari-inceleme.md`, 2026-08-19) **"SAD v1.0 bugün ONAYLANAMAZ"** hükmü veriyor, 8 bloklayıcı sayıyor. Kaynağın birinci kabul kriteri **karşılanmıyor**. |

---

## 6. Mevcut raporlarla çapraz kontrol — nerede uyuştu, nerede ayrıldı

| Rapor | İddiası | Bu oturumun bağımsız ölçümü | Sonuç |
|---|---|---|---|
| `19-d2-hash-ortusme.md` §5.4 | Düzeltme sonrası 40 public dosya; `_is_protected_pii=True` public dosya 0/40 | **40** · **0/40** · ayrıca **0/2.879** | ✅ **Doğrulandı** |
| `19-d2-hash-ortusme.md` §5.4 | `Order` + `Payment Transaction` kırılımdan düştü | Kırılımda ikisi de yok | ✅ **Doğrulandı** |
| `16-t029-politika-aktivasyonu.md` §0 | **0/9** politika `active` | **0/9** | ✅ **Doğrulandı** |
| `16-t029` §5.3 | `open_questions = 49`, `encoder_quality null = 14`, şemaya uyum **9/9** | **49** · **14** · jsonschema **0 hata / 9 dosya** | ✅ **Doğrulandı** |
| `16-t029` §0 | G4 = **14/14** karar onaylı | logo 6 + ccv 8 = **14** | ✅ **Doğrulandı** (kanıt = belgenin beyanı, imza yok) |
| `16-t029` §0 | G1: *"betik çıkış kodu 1, 6 hata"* | Betik repoda **bulunamadı** | ⚠ **Tekrarlanmadı** |
| `21-t030-mimari-inceleme.md` M-02 | 13 metodun 13'ü örtüşmüyor | **13/13**, kesişim 0, `isinstance` **False** | ✅ **Doğrulandı** |
| `21-t030` M-01 | `media_engine`/`tests/` yolları yok, 6 kalıntı satır | İkisi de YOK; **6** satır | ✅ **Doğrulandı** |
| `21-t030` M-04 | **5** yeni DocType kurulu | **6** DocType kurulu | ✅ **Doğrulandı, kapsamı daha geniş** |
| `21-t030` M-07/09/10/14/18 | 5 bloklayıcı daha | — | ⚠ **Tekrarlanmadı** |
| `30-faz1-adr-kapanis.md` | 17 ADR, her biri en az bir `dosya:satır` ya da rapor atıfı taşıyor | 17 ADR ✅; **15/17** rapor atıflı, **2** yalnız `dosya:satır` | ✅ **Doğrulandı** (README kuralına göre) |
| `30-faz1-adr-kapanis.md` §2 | "Görev listesinde istenen 8 ADR'nin karşılıkları" tam | Kaynak sayfanın 8'lisi **farklı**; **client kütüphane seti** ve **CDN** ADR'si yok | ❌ **Ayrıldı** |
| `11-faz1-arge.md` §T-017.1 | Kanca yolu kötücül fixture'ların **2/10**'unu reddediyor | **RED=2, GEÇTİ=8** | ✅ **Doğrulandı — bulgu ciddi** |
| `docs/srs/SRS-v1.0.md` §T3 | 3 politika dosyası şemaya uymuyor | jsonschema **0 hata / 9** | ❌ **SRS eskimiş** |
| `05-fixture-korpusu.md` | Pillow 11.3.0 | Konteynerde Pillow **12.2.0** | ⚠ **Sürüm kayması** |
| `05-kutuphane-benchmark.md` | pyvips kuruldu, ölçüm koşuldu | pyvips bugün **kurulu değil** | ⚠ **Tekrar üretilemez** |

---

## 7. SAYIM

### 7.1 Faz başına

| Faz | Görev | TAM | KISMİ | YOK |
|---|---:|---:|---:|---:|
| **Faz 0** — Keşif (T-000…T-009) | 10 | **5** | **5** | 0 |
| **Faz 1** — AR-GE (T-010…T-019) | 10 | **5** | **4** | **1** |
| **Faz 2** — Standartlar (T-020…T-029) | 10 | **6** | **4** | 0 |
| **Faz 3** — Mimari (T-030…T-035) | 6 | **1** | **4** | **1** |
| **TOPLAM** | **36** | **17** | **17** | **2** |

### 7.2 Dağılım

```
TAM    17 / 36   (%47)
KISMİ  17 / 36   (%47)
YOK     2 / 36   (%6)
```

**TAM olanlar (17):**

| Faz | Görevler |
|---|---|
| 0 | T-000, T-001, T-002, T-005, T-008\* |
| 1 | T-012, T-013\*, T-014\*, T-016, T-018 |
| 2 | T-021, T-022, T-024, T-026, T-027\*, T-028\* |
| 3 | T-034 |

*(\* işaretli 5 görev yalnız belge kanıtına dayanıyor — bu oturumda yeniden
ölçülmedi, `[R]`. Yani **testle/ölçümle** doğrulanmış TAM sayısı **12**'dir.)*

**KISMİ olanlar (17):** T-003, T-004, T-006, T-007, T-009 · T-010, T-011, T-015, T-019 ·
T-020, T-023, T-025, T-029 · T-030, T-031, T-033, T-035.

**YOK olanlar (2):**

1. **T-017** (Faz 1, Güvenlik AR-GE) — kabul kriteri *"`fixtures/malicious/` içindeki
   **her** dosya reddediliyor"*. Ölçüldü: **10'dan 2'si**. 100 MP decompression bomb,
   polyglot'lar, HTML kuyruklu JPEG ve `.png` uzantılı çalıştırılabilir **geçiyor**.
2. **T-032** (Faz 3, App iskeleti) — 5 kabul kriterinden 1'i karşılanıyor. Ayrı app
   **bilinçli olarak** açılmadı (ADR-0003), ama CI ayağı (ruff/mypy/pytest/pre-commit)
   **hiç kurulmamış**: `.github/workflows/` içindeki 5 workflow'un hiçbirinde test/lint
   adımı yok, `[tool.mypy]` yok, `.pre-commit-config.yaml` yok.

### 7.3 Dört fazın hiçbirinin kapanmamasının ortak nedeni

Fazların **çıkış kriterleri** (T-009, T-019, T-029, T-035) dörtte dördünde aynı kaleme
takılıyor ve bu kalem bu oturumda **ölçüldü, doğrulandı**:

| Faz | Kapanış görevi | Takıldığı kalem | Ölçülen kanıt |
|---|---|---|---|
| 0 | T-009 | Platform yöneticisi imzası | `07-faz0-kapanis.md` §10.5 — **dört alan da boş** |
| 1 | T-019 | İmza + geri dönüş yolu bölümü | ADR şablonunda **"geri dönüş yolu" bölümü yok**; `30-…md` §4 imzayı **AÇIK** bırakıyor |
| 2 | T-029 | SRS onayı (7 kapı) | **G1 🟡 · G3 ❌ · G5 ❌ · G6 ❌ · G7 ❌** — 5 kapı kapalı değil |
| 3 | T-035 | Bağımsız gözden geçirenin onayı | SAD onay bloğu **boş**; bağımsız inceleme **"ONAYLANAMAZ"** diyor |

**Yani teknik iş büyük ölçüde yapılmış (483 test yeşil, 9/9 politika şemaya uyumlu,
592 kırpma vektörü 0.0 px sapmayla geçiyor); kapanmayan şey doğrulama değil, onaydır** —
tek istisna, gerçekten teknik olan iki kalem: **T-017'nin 8/10 kötücül dosyası** ve
**T-032'nin hiç kurulmamış CI'ı**.

---

## Ek A — Yeniden üretme komutları

```bash
# Testler (frappe'siz — site/DB gerekmez)
docker exec istoc-dev-backend-1 bash -lc 'cd /home/frappe/frappe-bench/apps/tradehub_core && \
  for m in test_contracts test_policy_engine test_state_machine test_storage_adapters \
           test_crop_geometry test_policy_dpi test_dedup test_image_probe \
           test_image_normalize test_image_classify test_enforcement; do \
    printf "%-28s " "$m"; ../../env/bin/python -m unittest tradehub_core.tests.$m 2>&1 | tail -3 | tr "\n" " "; echo; done'

# Bench testi
docker exec istoc-dev-backend-1 bash -lc 'cd /home/frappe/frappe-bench && \
  bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_jobs'

# M-02 — protokol / somut sınıf örtüşmesi
docker exec istoc-dev-backend-1 bash -lc 'cd /home/frappe/frappe-bench/apps/tradehub_core && ../../env/bin/python - <<PY
from tradehub_core.media.pipeline.contracts.policy import PolicyEngine as P
from tradehub_core.media.pipeline.policy.engine import PolicyEngine as C
import inspect
pm={n for n in dir(P) if not n.startswith("_")}
cm={n for n,_ in inspect.getmembers(C, inspect.isfunction) if not n.startswith("_")}
print(len(pm), len(cm), sorted(pm&cm), isinstance(C(), P))
PY'

# Politika sayımı (host)
python3 - <<'PY'
import json,glob,os
for f in sorted(glob.glob('tradehub_core/media/pipeline/policy/slots/*.json')):
    d=json.load(open(f))
    print(os.path.basename(f), d.get('status'), len(d.get('open_questions') or []),
          (d.get('master') or {}).get('max_megapixels'))
PY

# Şema doğrulaması (host — jsonschema konteynerde YOK)
python3 -c "
import json,glob,jsonschema
V=jsonschema.Draft202012Validator(json.load(open('tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json')))
print(sum(len(list(V.iter_errors(json.load(open(f))))) for f in glob.glob('tradehub_core/media/pipeline/policy/slots/*.json')))"

# D-2 birleşim ölçümü ve kötücül fixture kapısı: betikler konteynere kopyalanıp
# koşturuldu, koşum sonrası silindi. Gövdeleri §2.1 ve §3'teki çıktılarla birlikte
# yukarıda tarif edildi (presets.EXCLUDED_DOCTYPES ∪ EXCLUDED_MEDIA_FIELDS ∪ is_private=1).
```

## Ek B — Bu oturumda DEĞİŞTİRİLMEYENLER

- Hiçbir `.py`, DocType JSON, politika JSON, `docs/standards/`, `docs/srs/`, `docs/sad/`,
  `docs/adr/` dosyası açılmadı-yazılmadı. Yazılan tek dosya: **bu rapor**.
- `Media Engine Settings` bayrakları ölçüm öncesi/sonrası okundu, **0'da kaldı**.
- Hiçbir doctype'ta kayıt oluşturulmadı; `set_level`/`optimize`/`transcode` çağrılmadı.
- Konteynere kopyalanan 5 betik + 1 dizin (`d2_check.py`, `d2_repeat.py`, `d2b.py`,
  `valpol.py`, `mal.py`, `/tmp/policy_host`) **silindi ve silinme doğrulandı**.
