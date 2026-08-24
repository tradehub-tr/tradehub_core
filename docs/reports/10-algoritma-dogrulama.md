# 10 — T-010 kırpma ve türev algoritması doğrulaması

**Tarih:** 2026-08-23 · **Durum:** teknik kabul kriterleri karşılandı

## Sonuç

| Kapı | Ölçüm | Sonuç |
|---|---:|---|
| Vektör sayısı | 592 (584 geçerli + 8 negatif) | ≥200 ✅ |
| Python/TS vektör sapması | 0,0 px | ≤0,5 px ✅ |
| `crop.py` / `crop_geometry.py` çapraz sapma | 1,818989e-12 px | ≤0,5 px ✅ |
| Oran sapması | 3.652 örnekte en çok 2,070e-16 bağıl | %0,5'in altında ✅ |
| Piksel yuvarlama | 800 örnekte farklı kutu: 0 | ✅ |
| Öncelik zinciri | 5/5 seviye ayrı test | ✅ |
| Gerçek HTML simülatörü | 200 rastgele girdide en çok 0,5 px | ✅ |
| INV-10 | 1×/2×/5× kaynakta normalize kadraj aynı | ✅ |

Kanonik vektör `tests/vectors/crop-vectors.json`, çalışan prototip haritası
`prototypes/cropgeo/README.md`, etkileşim çekirdeği
`media/pipeline/core/crop_geometry.{py,ts}`, niyet çekirdeği
`media/pipeline/core/crop.py` ve gerçek simülatör `docs/simulator.html` içindedir.
Vektör kopyası `scripts/sync_faz1_cropgeo.py --check` ile kaynak fixture'a
bağlıdır.

## Öncelik zinciri

`tradehub_core.tests.test_crop.OncelikZinciriTesti` şu seviyeleri ayrı ayrı
tetikler: profil override → güvenli alan + odak → genel odak → eşik üstü
smartcrop → merkez. `test_zincir_sirasi_bozulmuyor` beşinin aynı niyet üzerinde
üstten sökülerek sırayla devraldığını; profil dışı/yarım override ve eşik altı
önerinin kullanılmadığını ayrıca doğrular.

## P-01…P-16 izlenebilirlik

| Tuzak | Bizdeki karşılık | Değişmez / test |
|---|---|---|
| P-01 Dosya baytına bakıp piksel bütçesini atlamak | Header probe MP kararını bayttan bağımsız verir | INV-01; `test_contracts::test_probe_megapiksel_bombasini_reddeder`, `test_media_security_gate::test_bomba_pikselleri_acilmadan_reddedilir` |
| P-02 Sessiz yeniden boyutlandırma | Orijinal korunur; normalize sonucu ve uygulanan adımlar raporlanır | INV-01/02; `test_image_normalize::test_300dpi_kaynak_72ye_iner_piksel_korunur`, `test_image_report::test_normalize_result_extra_remains_json_persistable` |
| P-03 Her şeyi lazy üretmek | Yayın öncesi zorunlu profil matrisi tamamlanır; lazy yalnız eksik istekte tekil üretilir | `test_pipeline_bridge::test_reprocess_yarisinda_eksik_yeni_matris_eski_active_versioni_korur`, `test_manifest_ilk_okuma_lazy_uretir_ikinci_okuma_persistent_cache_hit` |
| P-04 Sürümsüz türev URL'i | İçerik hash'i URL/ETag sözleşmesinin parçasıdır | INV-09; `test_media_manifest_api::test_etag_icerik_hashine_dayali`, `test_e2e_scenarios::test_turev_adresi_version_hash_tasir` |
| P-05 Tam bellekte sınırsız decode | Header-only guard ve ayrı süreç limitleri decode'dan önce çalışır | `test_media_security_gate::test_bomba_pikselleri_acilmadan_reddedilir`, `test_isolation::test_asiri_ayirma_memory_ile_doner` |
| P-06 Formatı elle seçmek | Sınıflandırma ve rendition matrisi AVIF/WebP/JPEG/PNG kararını politikadan verir | `test_image_classify`, `test_render::RenderSozlesmesiTesti` |
| P-07 Fayda kapısı olmaması | Kaynaktan büyük türev yayınlanmaz | INV-05; `test_render::test_hicbir_turev_kaynaktan_buyuk_degil`, `test_video_transcode::test_FAYDA_KAPISI_verimli_kaynagi_korur` |
| P-08 İdempotency olmaması | Aynı hash/politika ikinci kez encode edilmez | INV-06; `test_render::test_ikinci_kosum_encode_etmez`, `test_pipeline_bridge::test_manifest_ilk_okuma_lazy_uretir_ikinci_okuma_persistent_cache_hit` |
| P-09 Piksel crop niyeti saklamak | Niyet 0–1 normalize saklanır | INV-10; `test_crop.Inv10Testi` |
| P-10 Birbiriyle uyumsuz geometri modelleri | Backend, TS ve HTML aynı vektör/işlem sırasıyla kilitli | `test_crop_geometry.TypeScriptPariteTesti`, `AltinSimulatorTesti::test_html_simulatorun_javascripti_backend_ile_ayni` |
| P-11 Videoyu kapsam dışı bırakmak | Tablo tabanlı video kararı, transcode, benefit gate ve HLS hattı mevcut | `test_video_decision`, `test_video_transcode`, `test_video_phase7_closure` |
| P-12 Türev GC'si olmaması | Kullanım sayacı + kuru koşum + çift kapılı retention GC | `test_retention_gc`, ADR-0014 |
| P-13 Tek global kalite | Codec ve içerik sınıfı bazlı hedef SSIM, en çok dört encode | `test_adaptive_quality`, `test_quality_ssim` |
| P-14 Metadata/GPS bırakmak | Orientation uygulanır; EXIF/GPS/XMP strip, ICC kararı ayrı | INV-04; `test_image_normalize` GPS/ICC testleri |
| P-15 Gerçek sayfa önizlemesi olmaması | `docs/simulator.html` gerçek fonksiyonu ve admin Crop Studio aynı geometriyi kullanır | HTML için 200, port için 600, panel için 592 vektör paritesi |
| P-16 Alan bazlı dağınık kurallar | Slot politikası veridir ve tek PolicyEngine yorumlar | `test_contracts::test_dogrulama_d1_d5`, `policyEngineParity.test.js` |

Karşılıksız P-kodu kalmamıştır. Bu tablo, bir modül adı yerine çalıştırılabilir
test adı verdiği için kod/rapor sürüklenmesi denetlenebilir.

## Tekrar üretim

```bash
python scripts/sync_faz1_cropgeo.py --check
python -m unittest tradehub_core.tests.test_crop tradehub_core.tests.test_crop_geometry -v
cd ../admin-panel/frontend && npm test -- --runInBand src/lib/media/crop/__tests__/cropGeometryParity.test.js
```
