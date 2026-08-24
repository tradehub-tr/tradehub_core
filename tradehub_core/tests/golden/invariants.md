# Faz 6 invariant test haritası

Bu dosya, normatif `INV-01..INV-12` kurallarını tek tek birincil testlerine bağlar. Makine tarafındaki kaynak `invariants.json` dosyasıdır ve CI haritanın hem `12/12` olmasını hem de her test sembolünün gerçekten var olmasını denetler.

| Kural | Birincil test | Katman |
|---|---|---|
| INV-01 · no-upscale | `test_image_normalize.py::PikselTavaniTest::test_target_size_asla_buyutmez` | PR |
| INV-02 · DPI pikseli değiştirmez | `test_image_normalize.py::DpiTest::test_300dpi_kaynak_72ye_iner_piksel_korunur` | PR |
| INV-03 · kenar/MP tavanı | `test_image_normalize.py::PikselTavaniTest::test_megapiksel_tavani_uygulanir` | PR |
| INV-04 · GPS/EXIF temizliği | `test_image_normalize.py::MetadataTest::test_gps_silinir` | PR |
| INV-05 · video fayda kapısı | `test_video_transcode.py::GercekTranscode::test_FAYDA_KAPISI_verimli_kaynagi_korur` (+ image fayda kapısı) | Nightly |
| INV-06 · idempotency | `test_render.py::DefterTesti::test_ikinci_kosum_encode_etmez` | PR |
| INV-07 · alfa korunumu | `test_image_normalize.py::RenkUzayiTest::test_alfa_dusurulmez` | PR |
| INV-08 · atomik yayın | `test_media_version_promote.py::PromoteTests::test_promote_atomik_hata_da_tam_geri_alinir` | Site |
| INV-09 · hash URL | `test_dedup.py::RenditionAdresiTesti::test_ayni_girdi_ayni_url` (+ içerik değişim testi) | PR |
| INV-10 · crop intent | `test_crop.py::Inv10Testi::test_yari_boyutlu_kaynak_ayni_kadraji_verir` | PR |
| INV-11 · orijinal retention + audit | `test_retention.py::TestPolitikaBagimsizligi::test_turev_silinirken_orijinal_korunur` (+ audited-trash yapısal kapısı) | PR |
| INV-12 · 1000×1000 altı ret | `test_policy_engine.py::SinirVakalariTesti::test_bound_short999_reddedilir` | PR |

`site` katmanı Frappe veritabanı ve savepoint gerektirir;
`faz6-image-engine.yml / site-invariants` işi tek bir yeni site kurup INV-08'in
haritadaki tam test adını gerçekten çalıştırır. Job-level 10 dakika kapısı image
ve servis başlangıcını da, iç 600 saniye kronometresi site setup + testleri de
kapsar. Diğer kurallar PR regresyon işinde site gerektirmeden koşar.
