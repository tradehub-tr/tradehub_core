# T-140 — İzlenebilirlik matrisi (SRS → test)

> **BU DOSYA ELLE DÜZENLENMEZ.** `scripts/gen_traceability.py` üretir.
> Değişiklik gerekiyorsa ya testi ya `docs/test/req-test-map.json`'u değiştir,
> sonra betiği yeniden koş.

**Görev:** T-140 · **Faz:** 14 · **Kaynak:** `docs/srs/SRS-v1.0.md` (TASLAK)

## 0. Özet — ölçülen sayılar

| Ölçüm | Değer |
|---|---:|
| SRS'te ayrıştırılan gereksinim | **202** (150 FR + 52 NFR) |
| En az bir teste bağlı (A ∪ C) | **74** (%36.6) |
| **KAPSANMIYOR** | **128** (%63.4) |
| A kanıtı (test metninde kimlik geçiyor) | 36 |
| C kanıtı (yalnız elle eşleme, A yok) | 38 |
| B izi olan gereksinim (kapsam SAYILMAZ) | 23 |
| …bunlardan yalnız B izi olan, yani hâlâ kapsanmayan | 12 |
| Taranan test dosyası | 111 |
| Taranan test fonksiyonu | 2811 |

**Kabul kriteri karşılığı (kaynak doküman T-140):** *"Her FR/NFR en az bir
teste bağlı; bağsız gereksinim yok."* → bugün **SAĞLANMIYOR**; açık
gereksinim sayısı **128**. Liste §3'te tam olarak yazılı.

## 1. Kanıt sınıfları

| Sınıf | Anlamı | Güç |
|---|---|---|
| **A** | Test dosyasının metninde gereksinim kimliği geçiyor; AST ile en yakın test fonksiyonuna atandı | en güçlü |
| **B** | Test, `manifest.json`'da o gereksinime bağlı bir altın fixture'ı kullanıyor — **kapsam sayılmaz** | iz |
| **C** | `docs/test/req-test-map.json` içinde gerekçesiyle elle kuruldu; referansın varlığı AST ile doğrulandı | yargı |
| — | Kanıt yok → **KAPSANMIYOR** | — |

## 2. Matris

### 2.1 Fonksiyonel gereksinimler (FR)

| FR | Gereksinim (kısaltılmış) | Faz | SRS'teki bugünkü durum | Bağlayıcı test (A/C) | Fixture izi (B — sayılmaz) |
|---|---|---|---|---|---|
| **FR-001** | Sistem, her yükleme isteğinde dosyanın hangi slota ait olduğunu kanonik bir `slot_key` ile almalı ve doğrulama kararını o slotun politikasına göre… | F3 | YOK — imza `file_name`, `content`, `size`, `media_endpoint`… | **KAPSANMIYOR** | — |
| **FR-002** | Sistem, slot politikalarını tek bir kayıt defterinden okumalı ve tüm politika dosyaları tek bir şemaya uymalıdır. | F3 | YOK — 4 ayrı kayıt yeri, 3 farklı biçim | `tests/test_contracts.py::PolicyContractTest::test_dokuz_slot_yuklendi`<br>`tests/test_policy_engine.py::PolitikaKaydiTesti::test_dokuz_slot_politikasi_yuklendi` | — |
| **FR-003** | Sistem, politika şeması doğrulamasını CI'da çalıştırmalı ve hata varsa derlemeyi başarısız saymalıdır. | F3 | YOK — betik var, CI bağlantısı yok | `tests/test_contracts.py::PolicyContractTest::test_dogrulama_d1_d5` | — |
| **FR-004** | Sistem, bir politikadaki her sayının kaynağını `sources` bloğunda taşımayı zorunlu tutmalıdır; boş ya da "bilinmiyor" değeri kabul edilmemelidir. | F2 ✅ | VAR (şema düzeyinde zorunlu) | **KAPSANMIYOR** | — |
| **FR-005** | Sistem, bir politikayı yalnız `open_questions` boş VE hiçbir `encoder_quality` `null` değil iken `status: "active"` kabul etmelidir; `draft` politika… | F3 | YOK — kapı tanımlı, uygulayan kod yok | `tests/test_api_contracts.py::YonetimTesti::test_matris_kalibre_edilmemis_kaliteyi_isaretler` | — |
| **FR-006** | Sistem, her politikanın `bound_to` listesindeki `<doctype>.<field>` çiftlerinin gerçekten var olduğunu doğrulamalı ve var olmayan alanı hata olarak… | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-007** | Sistem, bir slot politikasının global tavanı gevşetmesine izin vermemelidir: efektif tavan `min(slot.accept.max_bytes, upload_policy.MAX_BYTES[kind],… | F3 | KISMEN — `min(bizim, platform_limit())` var, plan ve slot… | `tests/test_contracts.py::PolicyContractTest::test_efektif_tavan_kesisimdir` | — |
| **FR-008** | Sistem, `accept.extensions` listesi ile `accept.mime` listesi ayrıştığında politikayı sessizce delinmiş saymamalı, hata bildirmelidir. | F3 | YOK | **KAPSANMIYOR** | `tests/test_api_contracts.py::YuklemeTesti::test_politika_ihlali_422_ve_slot_onekli_kod`<br>`tests/test_image_probe.py`<br>`tests/test_policy_engine.py::KuralDavranisiTesti::test_uzanti_icerik_uyusmazligi_reddedilir` |
| **FR-009** | Sistem, MIME/uzantı kararını içerik imzasına (magic byte) göre vermeli ve uzantı ile içerik uyuşmazlığında reddetmelidir. | F3 | KISMEN — L0'da uyuşmazlık yalnız uyarı; magic-byte yalnız… | **KAPSANMIYOR** | `tests/test_api_contracts.py::YuklemeTesti::test_politika_ihlali_422_ve_slot_onekli_kod`<br>`tests/test_image_probe.py`<br>`tests/test_image_probe.py::KotucuIcerikTest::test_kesik_dosya_baslikta_gecerli_ama_reddedilir`<br>`tests/test_isolation.py::GercekIkiliyleEntegrasyon::test_ffprobe_bozuk_dosyada_temiz_hata_verir`<br>…+2 iz |
| **FR-010** | Sistem, `.docx` beyan eden bir dosyanın gerçekten DOCX olduğunu ZIP içeriğinden doğrulamalıdır. | F3 | KISMEN — yalnız KYB ucunda | **KAPSANMIYOR** | `tests/test_image_probe.py` |
| **FR-011** | Sistem, decompression bomb koruması olarak, görselin tamamı açılmadan yalnız başlıktan piksel sayısını okumalı ve `accept.max_megapixels_hard`… | F3 | YOK — `grep MAX_IMAGE_PIXELS tradehub_core/` → 0 sonuç;… | `tests/test_contracts.py::ImageContractTest::test_probe_megapiksel_bombasini_reddeder`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo03PikselTavani::test_megapiksel_karari_bayttan_bagimsiz`<br>`tests/test_e2e_scenarios.py::Senaryo03PikselTavani::test_piksel_acilmadan_reddedilebiliyor`<br>…+2 test | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo10KotuculDosya::test_bomba_piksel_acilmadan_reddedilir`<br>`tests/test_image_lqip.py::SozlesmeTest::test_72mp_kaynak`<br>`tests/test_image_normalize.py`<br>…+9 iz |
| **FR-012** | Sistem, `allow_animated: false` olan slotlarda animasyonlu görseli reddetmelidir; `auto_fix` seçilen slotta ilk kareyi alıp statik türev üretmelidir. | F3 | HATALI — motor atlıyor (`reason="animated"`), dosya kabul… | **KAPSANMIYOR** | `tests/test_image_lqip.py::SozlesmeTest::test_animasyonda_ilk_kare` |
| **FR-013** | Sistem, medya alanına `data:` URI yazılmasını reddetmelidir; medya bir dosya olarak yüklenmelidir. | F3 | YOK — kanal açık; `seed_demo_data.py:231-245` iki güvenlik… | **KAPSANMIYOR** | `tests/test_image_probe.py` |
| **FR-014** | Sistem, `.svg` ve `.svgz` yüklemelerini SVG-1…SVG-10 ön koşullarının tamamı karşılanana kadar reddetmeye devam etmelidir. | F3+ | VAR (iki kapı reddediyor) — korunacak | **KAPSANMIYOR** | `tests/test_image_probe.py`<br>`tests/test_policy_engine.py::KuralDavranisiTesti::test_kosullu_svg_kapali_oldugu_icin_reddedilir`<br>`tests/test_svg_sanitize.py` |
| **FR-015** | Sistem, `require.min_short_edge` ve `require.min_area` kontrollerini `>=` (eşitlik geçerli) ile uygulamalıdır. | F3 | YOK — 0 slotta piksel kuralı var | `tests/test_contracts.py::PolicyContractTest::test_geometri_esitlik_gecerlidir`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_1000_piksel_gecer_sinir_dahil`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_999_piksel_reddedilir` | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_1000_piksel_gecer_sinir_dahil`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_999_piksel_reddedilir`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_satici_ne_yapacagini_ogrenir`<br>…+12 iz |
| **FR-016** | Sistem, en-boy oranı kontrolünü bağıl tolerans ile uygulamalıdır: kabul ⟺ `min over r ∈ allowed_ratios of \ | F3 | YOK — oranı yazan tek yer bir önizleme CSS'i… | `tests/test_contracts.py::PolicyContractTest::test_geometri_bagil_oran_toleransi`<br>`tests/test_e2e_scenarios.py` | `tests/test_image_classify.py`<br>`tests/test_image_classify.py::KapiTest::test_skip_guard_ile_kapi_atlanir`<br>`tests/test_image_classify.py::SozlesmeTest::test_to_dict_serilestirilebilir`<br>`tests/test_image_lqip.py::AlfaTest::test_opak_gorselde_alfa_biti_yok`<br>…+20 iz |
| **FR-017** | Sistem, bir slotun `allowed_ratios` tolerans bantlarının çakışmadığını doğrulamalıdır; her kabul edilen görsel tek bir orana atanmalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-018** | Sistem, `require.max_count` ile galeri adet sınırını uygulamalıdır. | F3 | YOK — hiçbir galeri slotunda adet kuralı yok | `tests/test_contracts.py::PolicyContractTest::test_geometri_kisa_kenar_ve_adet` | — |
| **FR-019** | Sistem, logo slotlarında alfa kanalını tercih etmeli, alfası olmayan dosyayı kabul edip uyarmalıdır — reddetmemelidir. Alfasızlık ölçülmeli ve kayıt… | F3 | YOK | **KAPSANMIYOR** | `tests/test_image_classify.py`<br>`tests/test_image_lqip.py::AlfaTest::test_alfali_fixturelar_alfa_bayragi_tasir`<br>`tests/test_image_lqip.py::AlfaTest::test_baskin_renk_saydam_bolgeyi_saymaz`<br>`tests/test_image_lqip.py::AlfaTest::test_saydam_bolge_geri_acildiginda_saydam`<br>…+7 iz |
| **FR-020** | Sistem, logo master'ını kabul bandındaki (`1:2 … 2:1`) her orandan 1:1'e saydam letterbox ile normalize etmeli; asla kırpmamalıdır. | F3 | YOK | `tests/test_policy_engine.py::NormalizeHedefTesti::test_logo_masteri_kare_paddir` | `tests/test_image_lqip.py::AlfaTest::test_alfali_fixturelar_alfa_bayragi_tasir`<br>`tests/test_image_lqip.py::AlfaTest::test_baskin_renk_saydam_bolgeyi_saymaz`<br>`tests/test_image_lqip.py::AlfaTest::test_saydam_bolge_geri_acildiginda_saydam`<br>`tests/test_image_lqip.py::HizTest::test_kucuk_kaynakta_uctan_uca_da_butce_icinde`<br>…+3 iz |
| **FR-021** | Sistem, `user.avatar` slotunda `1:1` oranı zorunlu tutmalı (tolerans ±%2) ve dışını reddetmelidir. | F3 | YOK — bugün sessizce merkezden kırpılıyor | **KAPSANMIYOR** | `tests/test_image_normalize.py::PikselTavaniTest::test_kucuk_gorsel_buyutulmez` |
| **FR-022** | Sistem, dairesel maskeli slotlarda güvenli alanı dairenin iç teğet karesi (`1/√2 = %70,7`) olarak uygulamalı ve dışına taşan içerik için uyarı… | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-023** | Sistem, `company.cover_image` slotunda güvenli alanı merkez %41,7'lik dikey şerit olarak uygulamalı ve dışına taşan içerik için uyarı üretmelidir. | F3+ | YOK | **KAPSANMIYOR** | `tests/test_image_lqip.py::OranTest::test_yatay_ve_dikey_ayirt_edilir`<br>`tests/test_policy_engine.py::NormalizeHedefTesti::test_megapiksel_tavani_uzun_kenardan_once_baglar` |
| **FR-024** | Sistem, `category.banner` slotunda güvenli alanı merkez %42 × %42 olarak uygulamalıdır. | F3+ | YOK | **KAPSANMIYOR** | `tests/test_image_lqip.py::DogrulukTest::test_geri_acilan_hash_ortalama_renge_yakin`<br>`tests/test_image_lqip.py::OranTest::test_oran_gercek_orana_yakin`<br>`tests/test_policy_engine.py::KuralDavranisiTesti::test_ignore_aksiyonu_kullaniciya_gosterilmez` |
| **FR-025** | Sistem, `company.cover_video` slotunda videoya gömülü metni title-safe dikdörtgen içinde tutmayı zorunlu kılmalıdır: sol/sağ %10, üst %6, alt %26 iç… | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-026** | Sistem, kapak videosuna gömülü logo yüklenmesinde uyarı üretmelidir (ret değil). | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-027** | Sistem, belge slotunda geometri ihlalini `warn` ile karşılamalı, reddetmemelidir. | F3 | YOK (uyarı da yok) | `tests/test_contracts.py::PolicyContractTest::test_belge_slotunda_geometri_uyaridir` | — |
| **FR-028** | Sistem asla upscale yapmamalıdır; master üretimi yalnız küçültme yönünde çalışmalıdır. | F1 ✅ | VAR — korunacak | `tests/test_api_contracts.py::ManifestUreticiTesti::test_pick_hicbiri_yetmezse_en_buyugu`<br>`tests/test_contracts.py::ImageContractTest::test_master_yalniz_kucultur`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo03PikselTavani::test_tavan_uygulanınca_master_kuculur`<br>…+5 test | — |
| **FR-029** | Sistem, DPI değişimini asla piksel kaybına çevirmemelidir. | F2 ✅ | VAR (fiilen) | `tests/test_contracts.py::ImageContractTest::test_master_dpi_yazar_pikseli_degistirmez`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo02DpiPikselDusurmez::test_3000_300dpi_2400_72dpiye_iner` | `tests/test_e2e_scenarios.py`<br>`tests/test_image_normalize.py`<br>`tests/test_image_normalize.py::DpiTest::test_300dpi_kaynak_72ye_iner_piksel_korunur`<br>`tests/test_image_normalize.py::DpiTest::test_dpi_72_olarak_yazilir`<br>…+2 iz |
| **FR-030** | Sistem, çıktı DPI metadata'sını açıkça yazmalıdır (ekran medyası 72, belge 200); metadata'yı tüketici uygulamanın varsayılanına bırakmamalıdır. | F3 | YOK | `tests/test_contracts.py::ImageContractTest::test_master_dpi_yazar_pikseli_degistirmez`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo02DpiPikselDusurmez::test_3000_300dpi_2400_72dpiye_iner` | `tests/test_e2e_scenarios.py`<br>`tests/test_image_normalize.py`<br>`tests/test_image_normalize.py::DpiTest::test_300dpi_kaynak_72ye_iner_piksel_korunur`<br>`tests/test_image_normalize.py::DpiTest::test_dpi_72_olarak_yazilir`<br>…+2 iz |
| **FR-031** | Sistem, `master.max_long_edge` değerini kod tabanında var olan bir eşikten türetmeli; yeni sayı uydurmamalıdır. | F2 ✅ | KISMEN | **KAPSANMIYOR** | — |
| **FR-032** | Sistem, master invaryantını korumalıdır: `max_long_edge² / 1e6 ≥ max_megapixels`. | F2 ✅ | YOK (kod tarafında) | **KAPSANMIYOR** | — |
| **FR-033** | Sistem, `master.min_long_edge` altında kalan dosyayı reddetmemeli, "under-spec" işaretleyip hangi profilleri üretemediğini söylemelidir. | F3 | YOK | `tests/test_contracts.py::ImageContractTest::test_rendition_upscale_yapmaz_under_spec_isaretler` | — |
| **FR-034** | Sistem, her türev profilini somut bir CSS kutusu × DPR hesabından türetmeli; `derived_from` alanı olmayan profil kabul edilmemelidir. | F2 ✅ | VAR (şema düzeyinde) | **KAPSANMIYOR** | — |
| **FR-035** | Sistem, her master'dan slot politikasında tanımlı türev merdivenini üretmelidir. | F3 | YOK — bir yükleme → bir dosya | `tests/test_e2e_scenarios.py`<br>`tests/test_render.py::RenderSozlesmesiTesti::test_merdiven_per_format_matrisin_tamami`<br>`tests/test_render_regression.py::TumSlotlarDavranisTesti::test_kismi_merdiven_yok` | `tests/test_api_contracts.py`<br>`tests/test_dedup.py::AlgisalHashTesti::test_yeniden_boyutlandirma_ve_sikistirma_hashi_korur`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo12TurevSilinirYenidenUretilir::test_yeniden_uretim_ayni_baytlari_verir`<br>…+10 iz |
| **FR-036** | Sistem, iki komşu profil arasındaki oran 1,25'in altındaysa profilleri birleştirmelidir. | F2 ✅ | YOK | **KAPSANMIYOR** | — |
| **FR-037** | Sistem, kare kutuya giden profilleri (`w96`–`w768`) `pad` ile 1:1'e dolgulamalı; detay/zoom kaynağı profilleri (`w1280`, `w1920`) `contain`… | F3 | YOK | `tests/test_render.py::GeometriTesti::test_contain_orani_korur_dolgu_yok`<br>`tests/test_render.py::GeometriTesti::test_pad_hedef_orani_kurar` | `tests/test_image_classify.py::KapiTest::test_skip_guard_ile_kapi_atlanir`<br>`tests/test_image_classify.py::SozlesmeTest::test_to_dict_serilestirilebilir`<br>`tests/test_image_lqip.py::AlfaTest::test_opak_gorselde_alfa_biti_yok`<br>`tests/test_image_lqip.py::BoyutTest::test_base64_gomulebilir`<br>…+8 iz |
| **FR-038** | Sistem, logo türevlerini kayıpsız üretmelidir. | F3 | HATALI — `seller_media` yolundan geçen her logo q80 WebP'ye… | `tests/test_quality_ssim.py::PolitikaHedefiTesti::test_logo_slotlari_kayipsiz_ister` | `tests/test_image_lqip.py::AlfaTest::test_alfali_fixturelar_alfa_bayragi_tasir`<br>`tests/test_image_normalize.py::RenkUzayiTest::test_alfa_dusurulmez` |
| **FR-039** | Sistem, `master.strip_metadata.gps` alanını `true` uygulamalı; GPS koordinatlarını çıktıdan silmelidir (KVKK). | F3 | YOK — EXIF temizliği kod tabanında yok; avatar ucu engine'e… | `tests/test_image_normalize.py::MetadataTest::test_gps_silinir` | `tests/test_image_normalize.py::MetadataTest::test_gps_silinir` |
| **FR-040** | Sistem, türev dosyalarını orijinalin yanında, aynı shard dizininde, ekli suffix ile saklamalıdır. | F3 | KISMEN — isimlendirme+shard VAR, türev YOK | `tests/test_contracts.py::DeliveryContractTest::test_turev_anahtari_shardi_korur`<br>`tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo06KirpmaDegisinceUrlDegisir::test_turev_adresi_version_hash_tasir` | — |
| **FR-041** | Sistem, kapak videosu slotunda yerinde değiştirmeyi (in-place replace) yasaklamalı; rendition'ları ayrı adreslere yazmalıdır. | F3+ | HATALI | **KAPSANMIYOR** | — |
| **FR-042** | Sistem, poster'ı satıcı yüklememişse otomatik üretmelidir. | F3+ | YOK — poster boşsa kutu siyah kalıyor (Ç7) | `tests/test_contracts.py::DeliveryContractTest::test_video_manifesti_poster_zorunlu` | — |
| **FR-043** | Sistem, mağaza kartı/arama sonucu hover'ı için 6 saniyelik, sessiz, döngülü önizleme klibi üretmelidir. | F3+ | YOK | `tests/test_contracts.py::VideoContractTest::test_onizleme_klibi_boyut_kapisini_dayatmaz` | — |
| **FR-044** | Sistem, og:image türevini contain + pad + düz beyaz zemin ile üretmeli; kırpmamalı ve alfayı belirsiz bir renge düşürmemelidir. | F3 | HATALI | **KAPSANMIYOR** | — |
| **FR-045** | Sistem, belge slotunun türevini de private saklamalıdır. | F3 | KISMEN — orijinal muafiyeti VAR, türev YOK | **KAPSANMIYOR** | — |
| **FR-046** | Sistem, içerik kurallarını tek bir ön işleme üzerinde çalıştırmalıdır: EXIF transpose → uzun kenar 512 px LANCZOS → RGB, luma BT.601 → alfa beyaz… | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-047** | Sistem, ölçülemeyen görselde kuralı sessizce atlamalı (`pass` + sebep `not_measurable`) ve uyarı üretmemelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-048** | Sistem, yalnız iki kuralın RED üretmesine izin vermelidir: `nsfw_content` ve `extreme_blur`. Diğer 7 kural en fazla `warn` döner ve yayını asla… | F3+ | YOK (politika yazılı, uygulayan kod yok) | **KAPSANMIYOR** | `tests/test_image_classify.py`<br>`tests/test_policy_engine.py::IhlalSozlesmesiTesti::test_olculemeyen_kural_gecti_sayilmaz`<br>`tests/test_quality_ssim.py::PolitikaHedefiTesti::test_sinif_tahmini_gecerli_deger_uretir` |
| **FR-049** | Sistem, birden çok kural tetiklendiğinde en yüksek aksiyonu uygulamalı, uyarıları birikimli listelemelidir. | F3+ | YOK | `tests/test_contracts.py::PolicyContractTest::test_karar_birlesimi_en_yuksek_aksiyonu_alir` | — |
| **FR-050** | Sistem, RED kararında dosyayı silmemeli; ilgili kaydı `Hidden` durumuna alıp moderasyon kuyruğuna düşürmeli ve itiraza açık tutmalıdır. | F1 ✅ (yorum… | VAR (yalnız yorum görselinde) | **KAPSANMIYOR** | — |
| **FR-051** | Sistem, moderasyon skorlarını eşiklemelidir; kararı yalnız dil modelinin döndürdüğü `decision` dizgesine bırakmamalıdır. | F3+ | HATALI | **KAPSANMIYOR** | — |
| **FR-052** | Sistem, moderasyonu ürün görsellerine ve satıcı vitrin görsellerine de uygulamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-053** | Sistem, `manual_review` kararını gerçek bir kuyruğa düşürmelidir. | F3+ | YOK — "kaydedilir, kimse bakmaz" | **KAPSANMIYOR** | — |
| **FR-054** | Sistem, moderasyon sağlayıcısı erişilemediğinde fail-open davranmalı ama sessiz kalmamalıdır. | F3+ | HATALI (fail-open var, alarm yok) | **KAPSANMIYOR** | — |
| **FR-055** | Sistem, moderasyon çağrısını asenkron çalıştırmalıdır. | F3+ | HATALI | **KAPSANMIYOR** | — |
| **FR-056** | Sistem, riskli kategorilerde RED yerine `manual_review` uygulamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-057** | Sistem, içerik kurallarını üç aşamada açmalıdır ve kalibre edilmemiş eşikle RED üretmemelidir. | F3+ | YOK | **KAPSANMIYOR** | `tests/test_image_classify.py`<br>`tests/test_policy_engine.py::IhlalSozlesmesiTesti::test_olculemeyen_kural_gecti_sayilmaz`<br>`tests/test_quality_ssim.py::PolitikaHedefiTesti::test_sinif_tahmini_gecerli_deger_uretir` |
| **FR-058** | Sistem, kullanıcı mesajlarına ölçülmemiş istatistik yazmamalıdır. | F2 ✅ | VAR (politika bunu bilinçle uyguluyor) | **KAPSANMIYOR** | — |
| **FR-059** | Sistem, minimum görsel sayısı uyarısını yayın öncesinde göstermeli ve sayım tanımını değiştirmemelidir. | F3+ | KISMEN — eşik `completeness.py:231-232`'de var, görünür… | **KAPSANMIYOR** | — |
| **FR-060** | Sistem, her reddi `(kod, retryable)` çifti olarak döndürmeli; istemci karar verirken hata metnine değil koda bakmalıdır. | F1 ✅ | VAR (çekirdek) — korunacak | `tests/test_contracts.py::PolicyContractTest::test_hata_yaniti_kod_ve_retryable_tasir` | — |
| **FR-061** | Sistem, kodlu ret sözleşmesini tüm yükleme uçlarında kullanmalıdır. | F3 | KISMEN | **KAPSANMIYOR** | — |
| **FR-062** | Sistem, her kullanıcı mesajında iki soruyu yanıtlamalıdır: (1) NEDEN reddedildi, (2) NASIL düzeltilir. | F2 ✅ | VAR (şema düzeyinde) | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_satici_ne_yapacagini_ogrenir` | — |
| **FR-063** | Sistem, ret mesajını sahaya özgü uygulanabilir bir çözümle bitirmelidir. | F2 ✅ | YOK | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo01YetersizCozunurluk::test_satici_ne_yapacagini_ogrenir` | — |
| **FR-064** | Sistem, yükleme yanıtında optimizasyon özeti döndürmelidir. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-065** | Sistem, optimizasyon özetinde DPI satırını "(piksel korundu)" ibaresi olmadan göstermemelidir. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-066** | Sistem, ölçü verisi gelmediğinde sayı uydurmamalı, ayrı bir mesaj anahtarı kullanmalıdır. | F3 | YOK | `tests/test_contracts.py::ImageContractTest::test_kalite_olculemiyorsa_sayi_uydurmaz` | — |
| **FR-067** | Sistem, iki frontend için doğru interpolasyon sözdizimini kullanmalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-068** | Sistem, sayı ve ölçü biçimini tek yardımcıdan üretmelidir. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-069** | Sistem, RTL dilde sayı grubunun yön kaymasını önlemelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-070** | Sistem, satıcı başına toplam depolama kotasını uygulamalıdır. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_quota.py::CheckMediaStorageQuotaTests::test_kota_asiminda_upload_reddedilir` | — |
| **FR-071** | Sistem, kota limiti planda tanımsızsa (`None`) yüklemeyi reddetmemelidir (fail-open) ve bu tutarsızlığı belgelemelidir. | F1 ✅ | VAR (belgelenmemiş) | `tradehub_core/tests/test_media_quota.py::CheckMediaStorageQuotaTests::test_tanimsiz_kota_reddetmez` | — |
| **FR-072** | Sistem, kota kontrolünü dosya diske yazılmadan önce yapmalı; `File.before_insert` kapısını güvenlik ağı olarak korumalıdır. | F3 | KISMEN | `tradehub_core/tests/test_media_pipeline_integration.py::TestKotaReddi::test_dusuk_kotada_upload_reddedilir` | — |
| **FR-073** | Sistem, eşzamanlı yüklemede kota aşımını (TOCTOU) engellemelidir. | F3 | YOK — `strategy: none` | **KAPSANMIYOR** | — |
| **FR-074** | Sistem, kota kapsamını açık bayraklarla tanımlamalı; bugünkü davranışı varsayılan olarak taşımalıdır. | F3 | KISMEN | `tradehub_core/tests/test_media_quota.py::CheckMediaStorageQuotaTests::test_private_dosya_muaf` | — |
| **FR-075** | Sistem, kotayı beş metrikle ifade edebilmelidir. | F3+ | 1/5 VAR | **KAPSANMIYOR** | — |
| **FR-076** | Sistem, tek dosya tavanını plan zincirine dâhil etmelidir: `min(plan, politika, frappe)`. | F3+ | YOK | `tests/test_contracts.py::PolicyContractTest::test_efektif_tavan_kesisimdir` | — |
| **FR-077** | Sistem, yeni kota metriklerini `notify_only` ile açmalı, ölçüm yapılmadan `block`'a geçmemelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-078** | Sistem, toplu içe aktarmada kotayı iş başlamadan önce toplu kontrol etmelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-079** | Sistem, kota muafiyetlerini açık listeyle tutmalıdır. | F1 ✅ | VAR — belgelendi | `tradehub_core/tests/test_media_quota.py::CheckMediaStorageQuotaTests::test_kyb_dosyasi_kotadan_muaf` | — |
| **FR-080** | Sistem, kota kullanımını satıcıya göstermeli ve eşiğe yaklaşınca uyarmalıdır. | F3+ | KISMEN — `get_my_usage` ucu var, %80 uyarısı yok | **KAPSANMIYOR** | — |
| **FR-081** | Sistem, kota reddini HTTP 429 ile karıştırmamalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-082** | Sistem, medya yükleme uçlarına rate limit uygulamalıdır. | F3 | YOK — medya: 0 satır | **KAPSANMIYOR** | — |
| **FR-083** | Sistem, rate limit sayacını tek atomik işlemle artırmalıdır. | F3 | HATALI | **KAPSANMIYOR** | — |
| **FR-084** | Sistem, sabit pencereyi her istekte sıfırlamamalıdır. | F3 | HATALI | **KAPSANMIYOR** | — |
| **FR-085** | Sistem, misafir kovasını oturum kimliğine değil istemci parmak izine bağlamalıdır. | F3 | HATALI | **KAPSANMIYOR** | — |
| **FR-086** | Sistem, IP bazlı kovaya geçmeden önce proxy zincirini doğrulamalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-087** | Sistem, 429 yanıtında `Retry-After` başlığını kovanın kalan TTL'i ile göndermelidir. | F3 | KISMEN (2/3) | **KAPSANMIYOR** | — |
| **FR-088** | Sistem, rate limit reddini mevcut ret sözleşmesine almalı ve `retryable=True` işaretlemelidir. | F3 | YOK — `TooManyRequestsError` düz bir `ValidationError` alt… | **KAPSANMIYOR** | — |
| **FR-089** | Sistem, istek sayısının yanına bayt kovası (kullanıcı başına MB/dakika) uygulamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-090** | Sistem, rate limit arka ucu erişilemediğinde fail-open davranmalı ama alarm üretmelidir. | F3 | KISMEN | **KAPSANMIYOR** | — |
| **FR-091** | Sistem, rate limit uygulamasını tek bir mekanizmada birleştirmelidir. | F3+ | HATALI | **KAPSANMIYOR** | — |
| **FR-092** | Sistem, silmeyi iki adımlı yapmalıdır: canlı dosya → çöp (bekleme penceresi) → kalıcı silme. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-093** | Sistem, silme kapılarından dördünü `force` ile aşılamaz, yalnız "kullanımda" kapısını aşılabilir tutmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-094** | Sistem, "kullanılmadı" tanımını açıkça yazılı ve sürümlü tutmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-095** | Sistem, "görsel URL'i geçen alan" sayısındaki belgeleme tutarsızlığını gidermelidir. | F3 | HATALI (belge) | **KAPSANMIYOR** | — |
| **FR-096** | Sistem, `LIVE_SOURCES` listesini tamamlamalıdır; listede olmayan bir alan silme taramasında "kullanılmıyor" görünür. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-097** | Sistem, bir dosyanın son referansı kalktıktan sonra silme adayı olması için bir bekleme (grace) süresi uygulamalıdır. | F3+ | YOK | `tests/test_usage.py::DiskOksuzuTesti::test_esik_gunu_sinirda`<br>`tests/test_usage.py::DiskOksuzuTesti::test_genc_dosya_korunur` | — |
| **FR-098** | Sistem, "frontend'de sabit yazılmış görsel" boşluğunu makinece okunabilir biçimde işaretlemelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-099** | Sistem, saklama sürelerini konfigüre edilebilir yapmalıdır. | F3 | YOK | `tests/test_retention.py::TestPolitikaDogrulama::test_from_mapping_kismi_ayari_birlestirir` | — |
| **FR-100** | Sistem, `legal_hold` işaretli varlığı hiçbir politikayla silmemelidir. | F3 | YOK | `tests/test_retention.py::TestLegalHold::test_tutulan_nesne_bloke_edilir`<br>`tests/test_retention.py::TestLegalHold::test_tutulan_nesne_islak_kosumda_da_silinmez` | — |
| **FR-101** | Sistem, her silme olayını denetime yazmalı; hiçbir şey silinmediğinde de kayıt atmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-102** | Sistem, dosya silinince referans zincirini üç farklı davranışla temizlemelidir. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-103** | Sistem, orijinal dosyayı varsayılan olarak süresiz saklamalıdır. | F1 ✅ (fiilen) | VAR (fiilen) | `tests/test_retention.py::TestKuruKosum::test_varsayilan_politika_hicbir_seyi_silmez` | — |
| **FR-104** | Sistem, türev saklama politikasını bugün boş kümeye uygulandığını açıkça işaretlemelidir. | F2 ✅ (işaretlendi) | YOK (bilinçli) | **KAPSANMIYOR** | — |
| **FR-105** | Sistem, uygulanmamış bir depolama hedefi seçildiğinde politikayı reddetmelidir. | F3+ | YOK | `tests/test_retention.py::TestPolitikaDogrulama::test_bilinmeyen_hedef_reddedilir` | — |
| **FR-106** | Sistem, yedek alma ile temizlik sırasını korumalı: ÖNCE yedek, SONRA eskileri temizle. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-107** | Sistem, disk ile veritabanı arasındaki yetim/kırık kayıtları düzenli olarak uzlaştırmalıdır. | F3+ | KISMEN | `tests/test_usage.py::DiskOksuzuTesti::test_kayitsiz_ve_eski_dosya_oksuz`<br>`tests/test_usage.py::KayitOksuzuTesti::test_bagi_olmayan_eski_varlik_oksuz` | — |
| **FR-108** | Sistem, günlük saklama görevlerini çalıştırmalı ve çalıştığını denetimden kanıtlanabilir kılmalıdır. | F1 ✅ | KISMEN | **KAPSANMIYOR** | — |
| **FR-109** | Sistem, PII kapsamındaki doctype'lara bağlı dosyanın public yapılmasını reddetmelidir. | F1 ✅ | VAR — korunacak (15 test) | `tradehub_core/tests/test_media_access_level.py::KybProtectionTests::test_kyb_belgesi_public_yapilamaz`<br>`tradehub_core/tests/test_media_access_level.py::ReverseReferencePiiTests::test_attached_to_doctype_bos_ama_seller_application_referansli_dosya_public_yapilamaz` | — |
| **FR-110** | Sistem, KVKK muafiyet haritasını (`EXCLUDED_MEDIA_FIELDS`) tamamlamalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-111** | Sistem, belge doctype'larını optimizasyon hattından muaf tutmalı; hassas belgeyi küçültmemelidir. | F3 | KISMEN (8/10) | **KAPSANMIYOR** | — |
| **FR-112** | Sistem, private dosya için imzalı süreli URL üretebilmeli; yetkisiz kullanıcı için imza üretmemelidir. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_access.py::GetSignedUrlTests::test_yetkili_kullanici_icin_imzali_url_doner`<br>`tradehub_core/tests/test_media_access.py::GetSignedUrlTests::test_yetkisiz_kullanici_permission_error_ve_imza_uretmez` | — |
| **FR-113** | Sistem, imzalı URL TTL'ini clamp etmelidir. | F1 ✅ | VAR — korunacak | `tests/test_storage_adapters.py::StorageContractMixin::test_url_for_private_ttl_kelepcelenir` | — |
| **FR-114** | Sistem, imzalı indirme ucundaki her ret dalını denetime yazmalıdır. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_access.py::DownloadTests::test_bad_path_reddi_audit_a_yazar`<br>`tradehub_core/tests/test_media_access.py::DownloadTests::test_gecersiz_imza_reddi_audit_a_yazar` | — |
| **FR-115** | Sistem, satıcı izolasyonunu beş katmanda uygulamalı ve başka mağazanın dosyasının varlığını bile ifşa etmemelidir. | F1 ✅ | VAR — korunacak | `tests/test_api_contracts.py::TeslimTesti::test_baska_magaza_taslagi_goremez`<br>`tradehub_core/tests/test_media_seller_backup.py::TestIzolasyon::test_baska_magazanin_yedegi_okunamaz` | — |
| **FR-116** | Sistem, erişim seviyesi değişikliğini atomik yapmalı ve denetime yazmalıdır. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_access_level.py::AuditTests::test_basarili_degisim_media_level_changed_yazar`<br>`tradehub_core/tests/test_media_access_level.py::IdempotentTests::test_zaten_hedef_seviyedeyse_no_op` | — |
| **FR-117** | Sistem, dosyanın gizli/açık olmasını slot politikasından almalıdır; hangi ekrandan yüklendiğine bağlı bırakmamalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-118** | Sistem, private video normalize edilmediğinde kullanıcıya bir şey söylemelidir. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-119** | Sistem, SVG kabulünü on maddenin tamamı karşılanmadan açmamalıdır. | F3+ | VAR (reddediyor) — açılış koşulları YOK | `tests/test_policy_engine.py::KuralDavranisiTesti::test_kosullu_svg_kapali_oldugu_icin_reddedilir` | `tests/test_image_probe.py`<br>`tests/test_policy_engine.py::KuralDavranisiTesti::test_kosullu_svg_kapali_oldugu_icin_reddedilir`<br>`tests/test_svg_sanitize.py` |
| **FR-120** | Sistem, SVG bayt tavanını birincil, düğüm tavanını ikincil savunma olarak uygulamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-121** | Sistem, görseli `srcset`/`sizes`/`<picture>` ile cihaza uygun boyda servis etmelidir. | F3+ | YOK | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo04KirpmaVeCihazOnizleme::test_tum_cihaz_sinifi_kombinasyonlari_cozuluyor`<br>`tests/test_simulator_srcset.py::SizesUretimi::test_her_bolge_sizes_uretebiliyor`<br>`tests/test_simulator_srcset.py::SizesUretimi::test_srcset_dizgesi_artan_genislikte` | — |
| **FR-122** | Sistem, `srcset` yazmadan önce URL yeniden yazıcısının `srcset` attribute'unu izlediğini garanti etmelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-123** | Sistem, bugünkü aşırı-servis oranını azaltmalıdır. | F3+ | YOK | `tests/test_contracts.py::DeliveryContractTest::test_overshoot_olculur` | — |
| **FR-124** | Sistem, CLS'i önlemek için her görsel kutusunda oran veya sabit ölçü rezerve etmelidir. | F3+ | KISMEN | `tests/test_api_contracts.py::TeslimTesti::test_icsel_olcu_tasiniyor` | — |
| **FR-125** | Sistem, konuşma içeren kapak videosunda VTT altyazıyı zorunlu tutmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-126** | Sistem, `prefers-reduced-motion` altında otomatik hareketi iptal etmeli, kullanıcının kendi başlattığı oynatmayı kısıtlamamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-127** | Sistem, otomatik oynatmada `muted` + `playsinline` özniteliklerini istisnasız uygulamalıdır. | F3+ | KISMEN | **KAPSANMIYOR** | — |
| **FR-128** | Sistem, video kontrollerini klavyeyle kullanılabilir ve çevrilebilir kılmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-129** | Sistem, ses seviyesini normalize etmeli ve ses bitrate'ini sabitlemelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-130** | Sistem, progressive video teslimi için anahtar kare aralığını ve WebM cue yerleşimini sabitlemelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-131** | Sistem, "çözülmüş" bir sorunu yeniden kural yapmamalıdır. | F2 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **FR-132** | Sistem, ölü render bileşenlerine göre standart yazmamalıdır. | F2 ✅ (kayda geçti) | VAR (E8 olarak kayıtlı) | **KAPSANMIYOR** | — |
| **FR-133** | Sistem, video için ölçü ve süre metadatasını veritabanına yazmalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-134** | Sistem, süre kuralını ölçülebilir hâle geldikten sonra uygulamalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-135** | Sistem, her içerik kuralı için dört metrik toplamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-136** | Sistem, moderasyon logunda kaynak referansını taşımalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-137** | Sistem, migration (geriye dönük standartlaştırma) işini canlı yükleme kuyruğundan ayrı ve düşük öncelikli çalıştırmalıdır. | F3+ | YOK | `tests/test_e2e_scenarios.py` | — |
| **FR-138** | Sistem, `require.*` kurallarını geçmişe dönük uygulamamalıdır (grandfathering) ve eşiği ölçmeden zorlamamalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **FR-139** | Sistem, migration'da durdurma kriteri taşımalıdır. | F3+ | KISMEN — geri alma altyapısı VAR, durdurma kriteri politika | `tests/test_e2e_scenarios.py` | — |
| **FR-140** | Sistem, etkilenen satıcıya bildirim göndermeli ve son tarih vermelidir. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-141** | Sistem, eşik kalibrasyonunu gerçek üretim korpusuyla yapmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-142** | Sistem, kalibrasyon durumunu politika dosyasında makinece okunabilir tutmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **FR-143** | Sistem, `accept.max_megapixels_hard` değerini bayt tavanından değil, çözme anındaki bellek bütçesinden türetmeli; eşik gerçek kütüphaneyi kesen bir… | F3 | YOK — kod tarafında hiç kontrol yok; politika değeri de… | `tests/test_contracts.py::ImageContractTest::test_probe_megapiksel_bombasini_reddeder` | — |
| **FR-144** | Sistem, her görsel slotunda `accept.max_megapixels_hard` alanının var olmasını zorunlu kılmalıdır; alanı olmayan politika `active` yapılamamalıdır. | F2 → F3 | HATALI — alan iki logo politikasında eksik | **KAPSANMIYOR** | — |
| **FR-145** | Sistem, CMYK ve diğer sRGB dışı renk uzaylarını kabul yolunda sRGB'ye çevirmeli; çeviriyi yalnız optimizasyondan geçen dosyalara bırakmamalıdır. | F3 | KISMEN — `engine.optimize` çeviriyor; kapılardan dönen… | `tests/test_contracts.py::ImageContractTest::test_master_cmyk_srgbye_cevirir` | — |
| **FR-146** | Sistem, alfa kanalı taşıyan bir master'ı alfasız bir biçime düşürmemelidir. | F3 | YOK — format seçiminde alfa kontrolü yok | `tests/test_contracts.py::ImageContractTest::test_master_alfayi_dusurmez`<br>`tests/test_image_normalize.py::RenkUzayiTest::test_alfa_dusurulmez` | — |
| **FR-147** | Sistem tek bir kaynak-doğru politika setine dayanmalıdır; iki set aynı anda yürürlükte olamaz. | F2 (karar) → F3 | YOK — karar verilmedi (T6) | `tests/test_contracts.py::PolicyContractTest::test_source_root_raporlanir` | — |
| **FR-148** | Sistem'in politika doğrulama betiği her koşumda çalışabilir olmalı ve tek bir çıkış koduyla sonuç vermelidir. | F2 | HATALI — betik yazıldığı gibi koşamıyor | `tests/test_contracts.py::PolicyContractTest::test_dogrulama_d1_d5` | — |
| **FR-149** | Sistem, bir slot politikasını `active` yapmadan önce, o politikanın gerçek veriye uygulanmış uyum karnesini politikanın içinde taşımalıdır. | F2 → F3 | YOK — şemada böyle bir blok yok | **KAPSANMIYOR** | — |
| **FR-150** | Sistem, slot alanında harici URL bulunduğunda bunu bir politika ihlali olarak raporlamalı, sessizce geçmemelidir. | F3 | YOK — bugün alan serbest metin | **KAPSANMIYOR** | — |

### 2.2 Fonksiyonel olmayan gereksinimler (NFR)

| NFR | Gereksinim (kısaltılmış) | Faz | SRS'teki bugünkü durum | Test |
|---|---|---|---|---|
| **NFR-001** | Kapak videosunun pasif mobil veri maliyeti (kullanıcı hiçbir şeye dokunmadan) tavanı aşmamalıdır. | F3+ | ÖLÇÜLMEDİ | **KAPSANMIYOR** | — |
| **NFR-002** | Kapak videosunun ilk 10 saniyelik aktif maliyeti tavanı aşmamalıdır. | F3+ | ÖLÇÜLMEDİ | **KAPSANMIYOR** | — |
| **NFR-003** | Teslim edilen video rendition'ı dosya kapısını aşmamalıdır. | F3+ | YOK | `tests/test_contracts.py::VideoContractTest::test_transcode_ses_silme_ve_dosya_kapisi` | — |
| **NFR-004** | Kapak videosu depolaması kotayı öngörülebilir tutmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **NFR-005** | İçerik kuralı motoru senkron yolda gecikme eklememelidir. | F3+ | ÖLÇÜLMEDİ | **KAPSANMIYOR** | — |
| **NFR-006** | Transcode işi tek başına sistemi kilitlememelidir. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_transcode.py::TestEnqueueTranscodeKosullu::test_kucuk_video_enqueue_edilmez_ready_isaretlenir` | — |
| **NFR-007** | Parçalı yükleme parametreleri değişmemelidir. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-008** | Core Web Vitals bütçeleri karşılanmalıdır. | F3+ | ÖLÇÜLMEDİ | `tests/test_e2e_scenarios.py::Senaryo03PikselTavani::test_urun_sayfasi_LCP_OLCULMEDI` | — |
| **NFR-009** | Türev merdiveni depolama bütçesini aşmamalıdır. | F3+ | ÖLÇÜLMEDİ | **KAPSANMIYOR** | — |
| **NFR-010** | Master tavanının yükseltilmesi türev üretimi gelmeden uygulanmamalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **NFR-011** | Optimizasyon kapıları korunmalıdır: gereksiz yeniden encode yapılmamalıdır. | F1 ✅ | VAR — korunacak | `tests/test_render.py::DefterTesti::test_ikinci_kosum_encode_etmez`<br>`tests/test_render.py::DefterTesti::test_merdiven_idempotent` | — |
| **NFR-012** | Avatar slotunda israf ölçülebilir biçimde azaltılmalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **NFR-013** | Kota ve rate limit okumaları önbelleklenebilir olmalıdır. | F3+ | KISMEN | **KAPSANMIYOR** | — |
| **NFR-014** | Karar her zaman sunucunun olmalıdır; istemcideki her kontrol yalnız hızlandırma amaçlıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-015** | Tek kapı politikası korunmalıdır: her yükleme yolu aynı `check()`'ten geçmelidir. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-016** | Bir satıcı başka bir mağazanın dosyasının varlığını bile öğrenememelidir. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_seller_backup.py::TestKapsam::test_yedekte_baska_magazanin_dosyasi_YOK` | — |
| **NFR-017** | Geri alınamaz işlemler yalnız en yüksek role açık olmalıdır. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_av.py::TestAdminAPI::test_karantinadan_cikarma_yikici_yetki_ister` | — |
| **NFR-018** | Private dizin web'den doğrudan erişilemez olmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-019** | Dosya adları tahmin edilemez olmalıdır. | F1 ✅ | VAR (yeni yüklemeler) | `tradehub_core/tests/test_media_naming.py::TestHashedName::test_ayni_icerik_ayni_hash_farkli_ad_gizli` | — |
| **NFR-020** | Yol geçişi (path traversal) iki bağımsız katmanda engellenmelidir. | F1 ✅ | VAR — korunacak | `tests/test_storage_adapters.py::TestLocalDiskDavranisi::test_yol_gecisi_reddedilir`<br>`tradehub_core/tests/test_media_access.py::DownloadTests::test_path_traversal_download_da_reddedilir` | — |
| **NFR-021** | Sistem kendi kriptosunu yazmamalıdır. | F1 ✅ | VAR — korunacak | `tests/test_storage_adapters.py::TestSignedUrl::test_default_signer_anahtarsiz_rastgele_uretmez`<br>`tests/test_storage_adapters.py::TestSignedUrl::test_kurcalanan_imza_reddedilir` | — |
| **NFR-022** | Kullanıcı SVG'si hiçbir koşulda DOM'a inline edilmemelidir. | F3+ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-023** | CSS injection kapatılmış kalmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-024** | İstemci sıkıştırmasının bilinçli kapatıldığı yerler geri açılmamalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-025** | PDF içindeki aktif içerik riski kayıtta tutulmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **NFR-026** | `Administrator` reddi denetime yazılmıyor — bu bilinen sınır kayıtta tutulmalıdır. | kabul edilmiş sınır | HATALI (kabul edilmiş sınır) | **KAPSANMIYOR** | — |
| **NFR-027** | `File` doctype'ı için tenant-aware `permission_query_conditions` yok — bu sınır kayıtta tutulmalıdır. | F3+ | YOK | **KAPSANMIYOR** | — |
| **NFR-028** | Görsel yoksa arayüz kırılmamalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-029** | Görsel üstündeki metin her görselde okunabilir olmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-030** | Slider kontrolleri erişilebilir olmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-031** | Arayüz RTL'de otomatik aynalanmalı; aynalanamayan içerik videoya/görsele gömülmemelidir. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-032** | Yükleme ilerleme geri bildirimi tüm slotlarda tutarlı olmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-033** | `alt` metni ve `loading`/`decoding` öznitelikleri uygulanmış kalmalıdır. | F3+ | KISMEN | **KAPSANMIYOR** | — |
| **NFR-034** | Medya olayları tek bir denetim şemasına yazılmalıdır. | F1 ✅ | VAR (kısmen doğrulanmamış) | `tradehub_core/tests/test_media_access_level.py::AuditTests::test_gecis_hassas_isaretlenir_ve_ham_url_context_e_yazilmaz` | — |
| **NFR-035** | Denetim kaydında hassas değerler maskelenmelidir. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_access_level.py::AuditTests::test_gercek_adl_kaydinda_object_name_maskeli` | — |
| **NFR-036** | Zamanlanmış görevlerin koştuğu denetimden kanıtlanabilir olmalıdır. | F3 | KISMEN | **KAPSANMIYOR** | — |
| **NFR-037** | Kural tetiklenmelerinin sebebi loglanmalıdır. | F3+ | KISMEN | **KAPSANMIYOR** | — |
| **NFR-038** | Rate limit olayları denetlenebilir olmalıdır. | F3 | YOK | **KAPSANMIYOR** | — |
| **NFR-039** | Video hattının sağlığı izlenebilir olmalıdır. | F3 | VAR (alan) — izleme YOK | `tradehub_core/tests/test_media_transcode_retry.py::TestSupurucu::test_birakilmis_is_basarisizlik_sayilir_ve_yeniden_planlanir` | — |
| **NFR-040** | Transcode idempotent olmalıdır. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_transcode.py::TestEnqueueTranscodeKosullu::test_zaten_processing_ise_tekrar_enqueue_edilmez` | — |
| **NFR-041** | Yarım dosya asla yazılmamalıdır. | F1 ✅ | VAR — korunacak | `tests/test_e2e_scenarios.py`<br>`tests/test_video_transcode.py::GercekTranscode::test_yarim_dosya_diskte_kalmaz` | — |
| **NFR-042** | Yedek/geri yükleme, transcode ile çatışmamalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |
| **NFR-043** | `ffprobe` okunamadığında güvenli tarafa düşülmelidir. | F1 ✅ | VAR — korunacak | `tests/test_contracts.py::VideoContractTest::test_probe_olculemedigini_soyler_hata_atmaz`<br>`tests/test_retention.py::TestPolitikaBagimsizligi::test_kullanim_bilinmiyorsa_turev_korunur` | — |
| **NFR-044** | `file_url` sabit kalmalı; referanslar kırılmamalıdır. | F1 ✅ | VAR — korunacak (bir istisnayla) | `tradehub_core/tests/test_media_naming.py::TestWriteFileHashedFileDocPath::test_file_doc_gorunen_ad_degismez` | — |
| **NFR-045** | Aynı sınır için tek sayı olmalıdır. | F3 | HATALI | **KAPSANMIYOR** | — |
| **NFR-046** | Aynı kural iki yerde tekrar yazılmamalıdır. | F3+ | HATALI | **KAPSANMIYOR** | — |
| **NFR-047** | İki tavanın birbirini sessizce kilitlemesi önlenmelidir. | F3+ | HATALI | **KAPSANMIYOR** | — |
| **NFR-048** | Her giriş yolu aynı tavana tabi olmalıdır. | F3 | HATALI | **KAPSANMIYOR** | — |
| **NFR-049** | Yedekleme dayanıklılığı korunmalıdır. | F1 ✅ | VAR — korunacak | `tradehub_core/tests/test_media_seller_backup.py::TestDogrulama::test_bozulan_icerik_derin_dogrulamada_yakalanir` | — |
| **NFR-050** | Aynı içerik tek fiziksel dosya olmalıdır. | F1 ✅ | VAR — korunacak | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo09AyniDosyaIkiKez::test_ikinci_yukleme_yeni_varlik_uretmez`<br>`tradehub_core/tests/test_media_pipeline_integration.py::TestHashDedup::test_ayni_icerik_iki_kez_yuklenince_ayni_file_url_uretir` | — |
| **NFR-051** | Dizin başına dosya sayısı ölçeklenebilir kalmalıdır. | F1 ✅ | VAR — korunacak | `tests/test_e2e_scenarios.py`<br>`tests/test_e2e_scenarios.py::Senaryo09AyniDosyaIkiKez::test_adres_icerikten_turer`<br>`tests/test_dedup.py::AdlandirmaSozlesmesiTesti::test_ad_ve_shard_bicimi` | — |
| **NFR-052** | Tarih/saat gösterimi kullanıcının saat dilimine göre tek anlamlı olmalıdır. | F1 ✅ | VAR — korunacak | **KAPSANMIYOR** | — |

## 3. KAPSANMAYAN gereksinimler — tam liste

Aşağıdaki **128** gereksinimin bu depoda hiçbir testi yok.
Gizlenmedi, sayıldı:

| Gereksinim | Faz | SRS'teki bugünkü durum | Kısaltılmış metin |
|---|---|---|---|
| FR-001 | F3 | YOK — imza `file_name`, `content`, `size`, `media_endpoint`… | Sistem, her yükleme isteğinde dosyanın hangi slota ait olduğunu kanonik bir `slot_key` ile almalı ve doğrulama kararını o slotun politikasına göre… |
| FR-004 | F2 ✅ | VAR (şema düzeyinde zorunlu) | Sistem, bir politikadaki her sayının kaynağını `sources` bloğunda taşımayı zorunlu tutmalıdır; boş ya da "bilinmiyor" değeri kabul edilmemelidir. |
| FR-006 | F3 | YOK | Sistem, her politikanın `bound_to` listesindeki `<doctype>.<field>` çiftlerinin gerçekten var olduğunu doğrulamalı ve var olmayan alanı hata olarak… |
| FR-008 | F3 | YOK | Sistem, `accept.extensions` listesi ile `accept.mime` listesi ayrıştığında politikayı sessizce delinmiş saymamalı, hata bildirmelidir. |
| FR-009 | F3 | KISMEN — L0'da uyuşmazlık yalnız uyarı; magic-byte yalnız… | Sistem, MIME/uzantı kararını içerik imzasına (magic byte) göre vermeli ve uzantı ile içerik uyuşmazlığında reddetmelidir. |
| FR-010 | F3 | KISMEN — yalnız KYB ucunda | Sistem, `.docx` beyan eden bir dosyanın gerçekten DOCX olduğunu ZIP içeriğinden doğrulamalıdır. |
| FR-012 | F3 | HATALI — motor atlıyor (`reason="animated"`), dosya kabul… | Sistem, `allow_animated: false` olan slotlarda animasyonlu görseli reddetmelidir; `auto_fix` seçilen slotta ilk kareyi alıp statik türev üretmelidir. |
| FR-013 | F3 | YOK — kanal açık; `seed_demo_data.py:231-245` iki güvenlik… | Sistem, medya alanına `data:` URI yazılmasını reddetmelidir; medya bir dosya olarak yüklenmelidir. |
| FR-014 | F3+ | VAR (iki kapı reddediyor) — korunacak | Sistem, `.svg` ve `.svgz` yüklemelerini SVG-1…SVG-10 ön koşullarının tamamı karşılanana kadar reddetmeye devam etmelidir. |
| FR-017 | F3 | YOK | Sistem, bir slotun `allowed_ratios` tolerans bantlarının çakışmadığını doğrulamalıdır; her kabul edilen görsel tek bir orana atanmalıdır. |
| FR-019 | F3 | YOK | Sistem, logo slotlarında alfa kanalını tercih etmeli, alfası olmayan dosyayı kabul edip uyarmalıdır — reddetmemelidir. Alfasızlık ölçülmeli ve kayıt… |
| FR-021 | F3 | YOK — bugün sessizce merkezden kırpılıyor | Sistem, `user.avatar` slotunda `1:1` oranı zorunlu tutmalı (tolerans ±%2) ve dışını reddetmelidir. |
| FR-022 | F3+ | YOK | Sistem, dairesel maskeli slotlarda güvenli alanı dairenin iç teğet karesi (`1/√2 = %70,7`) olarak uygulamalı ve dışına taşan içerik için uyarı… |
| FR-023 | F3+ | YOK | Sistem, `company.cover_image` slotunda güvenli alanı merkez %41,7'lik dikey şerit olarak uygulamalı ve dışına taşan içerik için uyarı üretmelidir. |
| FR-024 | F3+ | YOK | Sistem, `category.banner` slotunda güvenli alanı merkez %42 × %42 olarak uygulamalıdır. |
| FR-025 | F3+ | YOK | Sistem, `company.cover_video` slotunda videoya gömülü metni title-safe dikdörtgen içinde tutmayı zorunlu kılmalıdır: sol/sağ %10, üst %6, alt %26 iç… |
| FR-026 | F3+ | YOK | Sistem, kapak videosuna gömülü logo yüklenmesinde uyarı üretmelidir (ret değil). |
| FR-031 | F2 ✅ | KISMEN | Sistem, `master.max_long_edge` değerini kod tabanında var olan bir eşikten türetmeli; yeni sayı uydurmamalıdır. |
| FR-032 | F2 ✅ | YOK (kod tarafında) | Sistem, master invaryantını korumalıdır: `max_long_edge² / 1e6 ≥ max_megapixels`. |
| FR-034 | F2 ✅ | VAR (şema düzeyinde) | Sistem, her türev profilini somut bir CSS kutusu × DPR hesabından türetmeli; `derived_from` alanı olmayan profil kabul edilmemelidir. |
| FR-036 | F2 ✅ | YOK | Sistem, iki komşu profil arasındaki oran 1,25'in altındaysa profilleri birleştirmelidir. |
| FR-041 | F3+ | HATALI | Sistem, kapak videosu slotunda yerinde değiştirmeyi (in-place replace) yasaklamalı; rendition'ları ayrı adreslere yazmalıdır. |
| FR-044 | F3 | HATALI | Sistem, og:image türevini contain + pad + düz beyaz zemin ile üretmeli; kırpmamalı ve alfayı belirsiz bir renge düşürmemelidir. |
| FR-045 | F3 | KISMEN — orijinal muafiyeti VAR, türev YOK | Sistem, belge slotunun türevini de private saklamalıdır. |
| FR-046 | F3+ | YOK | Sistem, içerik kurallarını tek bir ön işleme üzerinde çalıştırmalıdır: EXIF transpose → uzun kenar 512 px LANCZOS → RGB, luma BT.601 → alfa beyaz… |
| FR-047 | F3+ | YOK | Sistem, ölçülemeyen görselde kuralı sessizce atlamalı (`pass` + sebep `not_measurable`) ve uyarı üretmemelidir. |
| FR-048 | F3+ | YOK (politika yazılı, uygulayan kod yok) | Sistem, yalnız iki kuralın RED üretmesine izin vermelidir: `nsfw_content` ve `extreme_blur`. Diğer 7 kural en fazla `warn` döner ve yayını asla… |
| FR-050 | F1 ✅ (yorum… | VAR (yalnız yorum görselinde) | Sistem, RED kararında dosyayı silmemeli; ilgili kaydı `Hidden` durumuna alıp moderasyon kuyruğuna düşürmeli ve itiraza açık tutmalıdır. |
| FR-051 | F3+ | HATALI | Sistem, moderasyon skorlarını eşiklemelidir; kararı yalnız dil modelinin döndürdüğü `decision` dizgesine bırakmamalıdır. |
| FR-052 | F3+ | YOK | Sistem, moderasyonu ürün görsellerine ve satıcı vitrin görsellerine de uygulamalıdır. |
| FR-053 | F3+ | YOK — "kaydedilir, kimse bakmaz" | Sistem, `manual_review` kararını gerçek bir kuyruğa düşürmelidir. |
| FR-054 | F3+ | HATALI (fail-open var, alarm yok) | Sistem, moderasyon sağlayıcısı erişilemediğinde fail-open davranmalı ama sessiz kalmamalıdır. |
| FR-055 | F3+ | HATALI | Sistem, moderasyon çağrısını asenkron çalıştırmalıdır. |
| FR-056 | F3+ | YOK | Sistem, riskli kategorilerde RED yerine `manual_review` uygulamalıdır. |
| FR-057 | F3+ | YOK | Sistem, içerik kurallarını üç aşamada açmalıdır ve kalibre edilmemiş eşikle RED üretmemelidir. |
| FR-058 | F2 ✅ | VAR (politika bunu bilinçle uyguluyor) | Sistem, kullanıcı mesajlarına ölçülmemiş istatistik yazmamalıdır. |
| FR-059 | F3+ | KISMEN — eşik `completeness.py:231-232`'de var, görünür… | Sistem, minimum görsel sayısı uyarısını yayın öncesinde göstermeli ve sayım tanımını değiştirmemelidir. |
| FR-061 | F3 | KISMEN | Sistem, kodlu ret sözleşmesini tüm yükleme uçlarında kullanmalıdır. |
| FR-064 | F3 | YOK | Sistem, yükleme yanıtında optimizasyon özeti döndürmelidir. |
| FR-065 | F3 | YOK | Sistem, optimizasyon özetinde DPI satırını "(piksel korundu)" ibaresi olmadan göstermemelidir. |
| FR-067 | F3 | YOK | Sistem, iki frontend için doğru interpolasyon sözdizimini kullanmalıdır. |
| FR-068 | F1 ✅ | VAR — korunacak | Sistem, sayı ve ölçü biçimini tek yardımcıdan üretmelidir. |
| FR-069 | F3+ | YOK | Sistem, RTL dilde sayı grubunun yön kaymasını önlemelidir. |
| FR-073 | F3 | YOK — `strategy: none` | Sistem, eşzamanlı yüklemede kota aşımını (TOCTOU) engellemelidir. |
| FR-075 | F3+ | 1/5 VAR | Sistem, kotayı beş metrikle ifade edebilmelidir. |
| FR-077 | F3+ | YOK | Sistem, yeni kota metriklerini `notify_only` ile açmalı, ölçüm yapılmadan `block`'a geçmemelidir. |
| FR-078 | F3+ | YOK | Sistem, toplu içe aktarmada kotayı iş başlamadan önce toplu kontrol etmelidir. |
| FR-080 | F3+ | KISMEN — `get_my_usage` ucu var, %80 uyarısı yok | Sistem, kota kullanımını satıcıya göstermeli ve eşiğe yaklaşınca uyarmalıdır. |
| FR-081 | F1 ✅ | VAR — korunacak | Sistem, kota reddini HTTP 429 ile karıştırmamalıdır. |
| FR-082 | F3 | YOK — medya: 0 satır | Sistem, medya yükleme uçlarına rate limit uygulamalıdır. |
| FR-083 | F3 | HATALI | Sistem, rate limit sayacını tek atomik işlemle artırmalıdır. |
| FR-084 | F3 | HATALI | Sistem, sabit pencereyi her istekte sıfırlamamalıdır. |
| FR-085 | F3 | HATALI | Sistem, misafir kovasını oturum kimliğine değil istemci parmak izine bağlamalıdır. |
| FR-086 | F3 | YOK | Sistem, IP bazlı kovaya geçmeden önce proxy zincirini doğrulamalıdır. |
| FR-087 | F3 | KISMEN (2/3) | Sistem, 429 yanıtında `Retry-After` başlığını kovanın kalan TTL'i ile göndermelidir. |
| FR-088 | F3 | YOK — `TooManyRequestsError` düz bir `ValidationError` alt… | Sistem, rate limit reddini mevcut ret sözleşmesine almalı ve `retryable=True` işaretlemelidir. |
| FR-089 | F3+ | YOK | Sistem, istek sayısının yanına bayt kovası (kullanıcı başına MB/dakika) uygulamalıdır. |
| FR-090 | F3 | KISMEN | Sistem, rate limit arka ucu erişilemediğinde fail-open davranmalı ama alarm üretmelidir. |
| FR-091 | F3+ | HATALI | Sistem, rate limit uygulamasını tek bir mekanizmada birleştirmelidir. |
| FR-092 | F1 ✅ | VAR — korunacak | Sistem, silmeyi iki adımlı yapmalıdır: canlı dosya → çöp (bekleme penceresi) → kalıcı silme. |
| FR-093 | F1 ✅ | VAR — korunacak | Sistem, silme kapılarından dördünü `force` ile aşılamaz, yalnız "kullanımda" kapısını aşılabilir tutmalıdır. |
| FR-094 | F1 ✅ | VAR — korunacak | Sistem, "kullanılmadı" tanımını açıkça yazılı ve sürümlü tutmalıdır. |
| FR-095 | F3 | HATALI (belge) | Sistem, "görsel URL'i geçen alan" sayısındaki belgeleme tutarsızlığını gidermelidir. |
| FR-096 | F3 | YOK | Sistem, `LIVE_SOURCES` listesini tamamlamalıdır; listede olmayan bir alan silme taramasında "kullanılmıyor" görünür. |
| FR-098 | F3+ | YOK | Sistem, "frontend'de sabit yazılmış görsel" boşluğunu makinece okunabilir biçimde işaretlemelidir. |
| FR-101 | F1 ✅ | VAR — korunacak | Sistem, her silme olayını denetime yazmalı; hiçbir şey silinmediğinde de kayıt atmalıdır. |
| FR-102 | F1 ✅ | VAR — korunacak | Sistem, dosya silinince referans zincirini üç farklı davranışla temizlemelidir. |
| FR-104 | F2 ✅ (işaretlendi) | YOK (bilinçli) | Sistem, türev saklama politikasını bugün boş kümeye uygulandığını açıkça işaretlemelidir. |
| FR-106 | F1 ✅ | VAR — korunacak | Sistem, yedek alma ile temizlik sırasını korumalı: ÖNCE yedek, SONRA eskileri temizle. |
| FR-108 | F1 ✅ | KISMEN | Sistem, günlük saklama görevlerini çalıştırmalı ve çalıştığını denetimden kanıtlanabilir kılmalıdır. |
| FR-110 | F3 | YOK | Sistem, KVKK muafiyet haritasını (`EXCLUDED_MEDIA_FIELDS`) tamamlamalıdır. |
| FR-111 | F3 | KISMEN (8/10) | Sistem, belge doctype'larını optimizasyon hattından muaf tutmalı; hassas belgeyi küçültmemelidir. |
| FR-117 | F3 | YOK | Sistem, dosyanın gizli/açık olmasını slot politikasından almalıdır; hangi ekrandan yüklendiğine bağlı bırakmamalıdır. |
| FR-118 | F3 | YOK | Sistem, private video normalize edilmediğinde kullanıcıya bir şey söylemelidir. |
| FR-120 | F3+ | YOK | Sistem, SVG bayt tavanını birincil, düğüm tavanını ikincil savunma olarak uygulamalıdır. |
| FR-122 | F3+ | YOK | Sistem, `srcset` yazmadan önce URL yeniden yazıcısının `srcset` attribute'unu izlediğini garanti etmelidir. |
| FR-125 | F3+ | YOK | Sistem, konuşma içeren kapak videosunda VTT altyazıyı zorunlu tutmalıdır. |
| FR-126 | F3+ | YOK | Sistem, `prefers-reduced-motion` altında otomatik hareketi iptal etmeli, kullanıcının kendi başlattığı oynatmayı kısıtlamamalıdır. |
| FR-127 | F3+ | KISMEN | Sistem, otomatik oynatmada `muted` + `playsinline` özniteliklerini istisnasız uygulamalıdır. |
| FR-128 | F3+ | YOK | Sistem, video kontrollerini klavyeyle kullanılabilir ve çevrilebilir kılmalıdır. |
| FR-129 | F3+ | YOK | Sistem, ses seviyesini normalize etmeli ve ses bitrate'ini sabitlemelidir. |
| FR-130 | F3+ | YOK | Sistem, progressive video teslimi için anahtar kare aralığını ve WebM cue yerleşimini sabitlemelidir. |
| FR-131 | F2 ✅ | VAR — korunacak | Sistem, "çözülmüş" bir sorunu yeniden kural yapmamalıdır. |
| FR-132 | F2 ✅ (kayda geçti) | VAR (E8 olarak kayıtlı) | Sistem, ölü render bileşenlerine göre standart yazmamalıdır. |
| FR-133 | F3 | YOK | Sistem, video için ölçü ve süre metadatasını veritabanına yazmalıdır. |
| FR-134 | F3 | YOK | Sistem, süre kuralını ölçülebilir hâle geldikten sonra uygulamalıdır. |
| FR-135 | F3+ | YOK | Sistem, her içerik kuralı için dört metrik toplamalıdır. |
| FR-136 | F3+ | YOK | Sistem, moderasyon logunda kaynak referansını taşımalıdır. |
| FR-138 | F3 | YOK | Sistem, `require.*` kurallarını geçmişe dönük uygulamamalıdır (grandfathering) ve eşiği ölçmeden zorlamamalıdır. |
| FR-140 | F3+ | YOK | Sistem, etkilenen satıcıya bildirim göndermeli ve son tarih vermelidir. |
| FR-141 | F3+ | YOK | Sistem, eşik kalibrasyonunu gerçek üretim korpusuyla yapmalıdır. |
| FR-142 | F3+ | YOK | Sistem, kalibrasyon durumunu politika dosyasında makinece okunabilir tutmalıdır. |
| FR-144 | F2 → F3 | HATALI — alan iki logo politikasında eksik | Sistem, her görsel slotunda `accept.max_megapixels_hard` alanının var olmasını zorunlu kılmalıdır; alanı olmayan politika `active` yapılamamalıdır. |
| FR-149 | F2 → F3 | YOK — şemada böyle bir blok yok | Sistem, bir slot politikasını `active` yapmadan önce, o politikanın gerçek veriye uygulanmış uyum karnesini politikanın içinde taşımalıdır. |
| FR-150 | F3 | YOK — bugün alan serbest metin | Sistem, slot alanında harici URL bulunduğunda bunu bir politika ihlali olarak raporlamalı, sessizce geçmemelidir. |
| NFR-001 | F3+ | ÖLÇÜLMEDİ | Kapak videosunun pasif mobil veri maliyeti (kullanıcı hiçbir şeye dokunmadan) tavanı aşmamalıdır. |
| NFR-002 | F3+ | ÖLÇÜLMEDİ | Kapak videosunun ilk 10 saniyelik aktif maliyeti tavanı aşmamalıdır. |
| NFR-004 | F3+ | YOK | Kapak videosu depolaması kotayı öngörülebilir tutmalıdır. |
| NFR-005 | F3+ | ÖLÇÜLMEDİ | İçerik kuralı motoru senkron yolda gecikme eklememelidir. |
| NFR-007 | F1 ✅ | VAR — korunacak | Parçalı yükleme parametreleri değişmemelidir. |
| NFR-009 | F3+ | ÖLÇÜLMEDİ | Türev merdiveni depolama bütçesini aşmamalıdır. |
| NFR-010 | F3+ | YOK | Master tavanının yükseltilmesi türev üretimi gelmeden uygulanmamalıdır. |
| NFR-012 | F3 | YOK | Avatar slotunda israf ölçülebilir biçimde azaltılmalıdır. |
| NFR-013 | F3+ | KISMEN | Kota ve rate limit okumaları önbelleklenebilir olmalıdır. |
| NFR-014 | F1 ✅ | VAR — korunacak | Karar her zaman sunucunun olmalıdır; istemcideki her kontrol yalnız hızlandırma amaçlıdır. |
| NFR-015 | F1 ✅ | VAR — korunacak | Tek kapı politikası korunmalıdır: her yükleme yolu aynı `check()`'ten geçmelidir. |
| NFR-018 | F1 ✅ | VAR — korunacak | Private dizin web'den doğrudan erişilemez olmalıdır. |
| NFR-022 | F3+ | VAR — korunacak | Kullanıcı SVG'si hiçbir koşulda DOM'a inline edilmemelidir. |
| NFR-023 | F1 ✅ | VAR — korunacak | CSS injection kapatılmış kalmalıdır. |
| NFR-024 | F1 ✅ | VAR — korunacak | İstemci sıkıştırmasının bilinçli kapatıldığı yerler geri açılmamalıdır. |
| NFR-025 | F3+ | YOK | PDF içindeki aktif içerik riski kayıtta tutulmalıdır. |
| NFR-026 | kabul edilmiş sınır | HATALI (kabul edilmiş sınır) | `Administrator` reddi denetime yazılmıyor — bu bilinen sınır kayıtta tutulmalıdır. |
| NFR-027 | F3+ | YOK | `File` doctype'ı için tenant-aware `permission_query_conditions` yok — bu sınır kayıtta tutulmalıdır. |
| NFR-028 | F1 ✅ | VAR — korunacak | Görsel yoksa arayüz kırılmamalıdır. |
| NFR-029 | F1 ✅ | VAR — korunacak | Görsel üstündeki metin her görselde okunabilir olmalıdır. |
| NFR-030 | F1 ✅ | VAR — korunacak | Slider kontrolleri erişilebilir olmalıdır. |
| NFR-031 | F1 ✅ | VAR — korunacak | Arayüz RTL'de otomatik aynalanmalı; aynalanamayan içerik videoya/görsele gömülmemelidir. |
| NFR-032 | F1 ✅ | VAR — korunacak | Yükleme ilerleme geri bildirimi tüm slotlarda tutarlı olmalıdır. |
| NFR-033 | F3+ | KISMEN | `alt` metni ve `loading`/`decoding` öznitelikleri uygulanmış kalmalıdır. |
| NFR-036 | F3 | KISMEN | Zamanlanmış görevlerin koştuğu denetimden kanıtlanabilir olmalıdır. |
| NFR-037 | F3+ | KISMEN | Kural tetiklenmelerinin sebebi loglanmalıdır. |
| NFR-038 | F3 | YOK | Rate limit olayları denetlenebilir olmalıdır. |
| NFR-042 | F1 ✅ | VAR — korunacak | Yedek/geri yükleme, transcode ile çatışmamalıdır. |
| NFR-045 | F3 | HATALI | Aynı sınır için tek sayı olmalıdır. |
| NFR-046 | F3+ | HATALI | Aynı kural iki yerde tekrar yazılmamalıdır. |
| NFR-047 | F3+ | HATALI | İki tavanın birbirini sessizce kilitlemesi önlenmelidir. |
| NFR-048 | F3 | HATALI | Her giriş yolu aynı tavana tabi olmalıdır. |
| NFR-052 | F1 ✅ | VAR — korunacak | Tarih/saat gösterimi kullanıcının saat dilimine göre tek anlamlı olmalıdır. |

## 4. Yeniden üretme

```bash
python3 scripts/gen_traceability.py              # bu dosyayı üret
python3 scripts/gen_traceability.py --check      # CI: dosya bayat mı
python3 scripts/gen_traceability.py --fail-uncovered   # kapı (bugün KIRMIZI)
```

