# 60 — Faz 6 Image Engine Kapanış Raporu

**Tarih:** 2026-08-23  
**Kapsam:** G16 · T-060…T-067 Image Engine kapanışı  
**Normatif kaynak:** `docs/50-faz6-image-engine.html`

## Sonuç

Fazın sekiz görevi tamamlandı. Önceden kısmi olan T-061, T-062, T-063, T-064,
T-066 ve T-067'nin eksik kabul maddeleri üretim koduna bağlandı ve bağımsız test
katmanlarıyla doğrulandı. Son production bridge ölçümü 34 gerçek rendition için
6,95 saniyedir ve 12 saniye kapısının altındadır. Açık senkronizasyon veya QA
beklentisi kalmamıştır.

## T-066 — kalıcı kalite raporu

Her asset raporu aşağıdaki ölçülmüş verileri JSON ve DocType alanlarında taşır:

- orijinal, optimize ve net tasarruf baytı ile işaretli tasarruf oranı;
- profil başına SSIM, hedef, geçiş kararı ve ölçüm arka ucu;
- seçilen format/kalite, encode denemeleri, makine kodu ve Türkçe neden;
- slot, asset/version kimliği, normalize gerçekleri, toplam süre ve ölçülmüşse LCP etkisi;
- satıcı için piksel ile DPI metadata'sını ayıran, uydurma değer üretmeyen Türkçe özet.

`Media Quality Report` hem asset hem monthly kayıtlarını saklar. Aylık çıktı
toplam tasarruf GB, işlenen asset sayısı, ortalama işleme süresi, ölçülmüş LCP
ortalaması, hata oranı, slot dağılımı ve en büyük çıktı/en düşük SSIM'den
deterministik worst-20 listesini hem DocType hem Markdown olarak üretir.

### Üretim scheduler'ı ve aylık doğruluk

`hooks.py` içindeki `13 2 1 * *` cron'u
`tradehub_core.media.pipeline.image.report.run_previous_month_report` girişini
çağırır. Giriş:

1. kapanmış önceki takvim ayındaki kalıcı `report_type=asset` kayıtlarını okur;
2. aynı `(asset.id, asset.version)` için upload/lazy tekrarlarından `(creation, name)` sırasındaki en son raporu seçer;
3. aynı dönemde `Media Processing Job.job_type in (normalize, rendition)` ve
   `status in (failed, dead)` olan, `finished_at` ile döneme düşen gerçek iş
   sayısını ölçer;
4. hata sayısı ölçülemiyorsa **0 uydurmaz**, işi kırmızı yapar;
5. unique `period_key=YYYY-AA` ile check-then-insert yarışında dahi tek aylık
   kayıt ve site-private Markdown üretir.

Prometheus sözleşmesi tam olarak şunlardır:

| Metrik | Tür | Amaç |
|---|---|---|
| `media_processed_total` | counter | raporlanan asset sonucu |
| `media_bytes_saved_total` | counter | pozitif net tasarruf baytı |
| `media_job_duration_seconds` | histogram | başarılı ve başarısız iş süresi |
| `media_job_failures_total` | counter | düşük kardinaliteli hata nedeni |

AAA paketi; negatif tasarrufun kazanç diye sunulmamasını, DPI açıklamasını,
profil SSIM/karar JSON'unu, DocType eşlemesini, worst-20'yi, Markdown ile aynı
payload'ın kalıcılığını, scheduler tekrarını, yarış anahtarını, gerçek iş hata
sayısını, ölçülemeyen hata sayısında fail-closed davranışı ve asset/version
dedupe'unu kapsar.

## T-067 — 57 fixture golden gerçeği

Manifestin güncel ve tek gerçek kaynağı **57 fixture**'dır; önceki raporlardaki
eski sayı burada manifest gerçeğiyle güncellenmiştir.

| Ölçüm | Sonuç |
|---|---:|
| Fixture | 57 |
| Manifest GREEN / RED | 57 / 0 |
| Toplam | 94.879.477 bayt (90,48 MiB) |
| Sınıflar | photo 19 · transparent 5 · graphic 10 · animation 2 · video 11 · malicious 10 |
| Beklenen aksiyon | process 27 · passthrough 8 · reject 22 |

Golden manifest testi her kaydın dosya varlığını, SHA-256'sını, gerçek baytını,
görsel/video kısıtlarını ve gerçek PolicyEngine/VideoDecision aksiyonunu kontrol
eder. PR/gecelik ortamına ffmpeg kurulur; ffprobe bulunmayan yerel ortamda video
kararı yalnız SHA-256 ile dosyaya bağlanmış ölçüm kaydı üzerinden yürür. Golden
PR paketinde skip veya boş döngü yoktur.

## INV-01…INV-12 birebir haritası

Makine-okunur harita `tests/golden/invariants.json`, insan-okunur karşılığı
`tests/golden/invariants.md` içindedir. AST kapısı dosya adı yazmakla yetinmez;
gösterilen sınıf/fonksiyonun gerçekten var olduğunu doğrular.

| ID | Normatif kural | Birincil kapı |
|---|---|---|
| INV-01 | upscale yok | `PikselTavaniTest.test_target_size_asla_buyutmez` |
| INV-02 | DPI pikseli değiştirmez | `DpiTest.test_300dpi_kaynak_72ye_iner_piksel_korunur` |
| INV-03 | kenar/MP tavanı | `PikselTavaniTest.test_megapiksel_tavani_uygulanir` |
| INV-04 | GPS/EXIF yayınlanmaz | `MetadataTest.test_gps_silinir` |
| INV-05 | büyük video çıktısı yayınlanmaz | `GercekTranscode.test_FAYDA_KAPISI_verimli_kaynagi_korur` |
| INV-06 | idempotency | `DefterTesti.test_ikinci_kosum_encode_etmez` |
| INV-07 | alfa korunur | `RenkUzayiTest.test_alfa_dusurulmez` |
| INV-08 | atomik rendition yayını | `PromoteTests.test_promote_atomik_hata_da_tam_geri_alinir` |
| INV-09 | hash URL kararlılığı | `RenditionAdresiTesti.test_ayni_girdi_ayni_url` |
| INV-10 | normalize crop intent | `Inv10Testi.test_yari_boyutlu_kaynak_ayni_kadraji_verir` |
| INV-11 | retention + deletion audit | `TestPolitikaBagimsizligi.test_turev_silinirken_orijinal_korunur` + yapısal audit kapısı |
| INV-12 | ürün kısa kenarı ≥1000 | `SinirVakalariTesti.test_bound_short999_reddedilir` |

Kapsam sonucu **12/12**'dir. INV-05 video fayda kapısına, INV-11 hem retention
davranışına hem tüm kalıcı silme rotalarının audit'li trash katmanına bağlıdır.

## Performans ve görsel regresyon

T-007 sınıf ölçümleri üzerine tam %30 payla eşikler tanımlandı:

| Sınıf / temsilci | Ölçülen süre | Eşik | Peak RSS | Eşik |
|---|---:|---:|---:|---:|
| photo / `edge_72mp.jpg` | 554,63 ms | 1.190 ms | 180,69 MiB | 275 MiB |
| transparent / `mode_rgba_alpha.png` | 88,28 ms | 2.858 ms | 55,05 MiB | 478 MiB |
| graphic / `mode_palette_p.png` | 152,33 ms | 1.155 ms | 44,05 MiB | 275 MiB |

Animation, video ve malicious sınıfları neden uygulanamaz olduklarıyla birlikte
manifestte açıkça işaretlidir. PR üç temsilciyi ölçer; nightly tüm process image
fixture'larını aynı sınıf bütçesine sokar.

Algısal golden, rendition üreten 24 fixture'ın **131 çıktısını** dHash-64 ile
kilitler; kabul mesafesi 2 bittir. Sapmada golden/current hash panellerini yan
yana PNG ve bağlantılı Markdown fark raporu olarak `FAZ6_DIFF_DIR` içine yazar.

## CI katmanları

`.github/workflows/faz6-image-engine.yml` iki bağımsız katmandır:

- Her PR: job timeout 10 dakika, ayrıca gerçek duvar saatini ölçüp 600 saniyede
  açıkça kıran golden + invariant + temsilci performans paketi.
- Schedule/manual nightly: `FAZ6_NIGHTLY=1`, 57 fixture'ın ağır sınıf matrisi,
  131 rendition perceptual paketi, 34-rendition kapısı, byte regresyonu ve gerçek
  video INV-05 testi. Nightly timeout 45 dakikadır.

## Yerel koşum kanıtı

| Koşum | Sonuç | Süre |
|---|---|---:|
| Faz 6 ana Python paketi | **464 test OK** | 26,624 sn |
| Golden paket | **19 test OK** | 3,142 sn |
| Son performans/regresyon seçkisi | **52 test OK** | 15,837 sn |
| Golden nightly matrisi | **7/7 OK** | 37,631 sn |
| Fresh CI kurulum + test | **GREEN** | 69 sn |
| Linux normalize/master/animation | **53/53 OK** | 24,175 sn |
| Frappe production bridge | **44/44 OK; 34 rendition 6,95 sn** | 11,769 sn |
| Promote/idempotency | **14/14 OK** | 0,301 sn |
| Kalite raporu DocType + yetki | **6/6 OK** | 0,051 sn |
| Storefront + admin LCP bağlama | **6/6 OK** | — |

Platforma özgü skip'ler Linux RSS semantiğinin karşı platform testi veya yerel
codec/libvips bulunmaması içindir. Aynı kabul maddeleri production Linux
container'da gerçek pyvips/libvips ve ffmpeg ile geçti. Eşikler gevşetilmedi ve
kabul davranışları skip ile karşılanmadı.

## Kapanış kararı

**GREEN — T-060…T-067 toplam 8/8 görev, %100 tamamlandı.** Güncel rendition
matrisi `product.image=19`, toplam `57` gerçeğiyle senkronizedir. Normalize,
sınıflandırma, animasyon yönlendirmesi, lazy üretim, atomik promote,
idempotency, kalite raporu ve golden CI için açık kabul maddesi kalmamıştır.
