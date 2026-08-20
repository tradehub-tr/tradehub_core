# 56 — D3 · Faz 6 / 7 / 8 / 10 kapanış kabulü + logo ve video standartlarının karar durumu

**Görevler:** T-067 (Faz 6) · T-075 (Faz 7) · T-085 (Faz 8) · T-105 (Faz 10) · T-021 (logo standardı) · T-022 (video standardı)
**Tarih:** 2026-08-19 · **Depo:** `tradehub_core`, dal `ahmet` · **Site:** `istoc.localhost` (docker compose)
**Tür:** BELGE görevi. Bu oturumda **hiçbir `.py`, DocType JSON ya da politika JSON'una dokunulmadı.**

---

## 0. Bu belgenin kuralı

> **Koşulmayan hiçbir şeye "geçti" denmedi. Ölçülemeyen her şeye "ÖLÇÜLMEDİ" yazıldı.**
> Aşağıdaki her sayı bu oturumda koşulmuş bir komuttan ya da canlı bir salt-okuma
> sorgusundan gelir. Başka raporlardan **alıntılanan** sayılar kaynağıyla birlikte
> işaretlidir ve "bugün ölçüldü" sayılmaz.

**Süre / performans iddiası YOKTUR.** Ölçüm sırasında aynı makinede beş ajan daha
koşuyordu; hiçbir zamanlama sayısı bu belgeye alınmadı.

**Yan etki:** yok. Yazma yapılmadı, `bench migrate` koşturulmadı, kayıt üretilmedi,
bayrak açılmadı. Ölçümün başında ve sonunda `Media Engine Settings` bayrakları
**0** (`media_pipeline_enabled: 0`, `rendition_on_upload: 0`, `manifest_api_enabled: 0`
— canlı DB'den okundu). Yazılan dosyalar: bu rapor + rapor 18 ve 32'ye eklenen
"kanıt ve kapı durumu" bölümleri (imza/onay bloklarına dokunulmadı).

| İşaret | Anlamı |
|---|---|
| ✅ | Kriter karşılandı **ve** kanıtı bu oturumda koşuldu |
| ⚠ | Bir parçası ölçüldü, kalanı ölçülemedi ya da karşılanmadı |
| ❌ | Ölçüldü ve kriteri karşılamıyor |
| — | Bu oturumda ölçülmedi (uydurulmadı) |

---

## 1. KARAR — dört faz, tek tablo

| Faz | Görev | Bugün kapanır mı | Tek cümlelik gerekçe | Kapanması için TEK adım |
|---|---|---|---|---|
| **6** · Image engine | T-067 | ❌ **HAYIR** | Regresyon paketi bugün **YEŞİL** (32 test OK) ama kriter 4 ("her PR'da CI'da koşar") **yapısal olarak** karşılanmıyor: 5 workflow'un hiçbiri test koşmuyor; kriter 2'nin "12 invariant + kapsam haritası" belgesi **repoda yok** | Test koşan bir GitHub Actions workflow'u + invariant kapsam haritası belgesi |
| **7** · Video engine | T-075 | ❌ **HAYIR** | Tek bloklayıcı (B-6, VMAF) **kapanmadı** — üretim imajında `libvmaf` bugün hâlâ **yok** (ölçüldü: 0). Ayrıca eşiğin kendisi gerçek içerikte **INV-05 ile aynı anda sağlanamaz** | **Tek adım yok — KARAR gerekiyor** (§3.3). Önce eşik yeniden tanımlanmalı, sonra `libvmaf` imaja alınmalı |
| **8** · API | T-085 | ❌ **HAYIR** | Sözleşme tarafı gerçekten kapandı (90 uç, 89'u ölçüldü, 41 test 0 atlama) ama T-085'in **kendi** üç çıktısı yok: **TS SDK yok, Postman/Bruno yok, spectral yok**; dondurma politikası **çağrılamayan katmanı** dondurmuş | Üç somut çıktı üretilmeli — tek adım değil, üç adım |
| **10** · Crop Studio | T-105 | ❌ **HAYIR** | **Zoom ayrışması gerçekten kapandı** (bugün ölçüldü: 7391 px → 1 px) ama iki ayrışma açık (C: 3704 px, E: 3481 px) ve kriterin "20 gerçek görselde elle karşılaştırma" ile "etkileşim performansı" maddeleri **hiç yapılmadı** | C ve E için **karar** (§5.5) + 20 görsellik karşılaştırma oturumu |

**Karara bağlı olan tek madde: Faz 7'nin VMAF eşiği.** Diğer üçü teknik iş; bu biri
imza gerektiriyor ve teknik olarak çözülemez, çünkü kriterin kendisi ölçümle
**boş (vacuous)** çıktı.

---

## 2. Bu oturumda koşulan ölçümler — ham

| # | Komut | Sonuç |
|---|---|---|
| 1 | `python -m unittest tradehub_core.tests.test_render_regression` (konteyner) | **Ran 32 tests — OK (skipped=1)** |
| 2 | `python -m unittest …test_video_decision …test_video_transcode` (konteyner) | **Ran 167 tests in 170,3 s — OK**, **0 atlama** |
| 3 | `python -m unittest …test_http_api_contracts` (konteyner, env yok) | **Ran 41 tests — OK (skipped=16)** |
| 4 | aynısı + `ISTOC_HTTP_BASE=http://127.0.0.1:8000 ISTOC_HTTP_HOST=istoc.localhost` | **Ran 41 tests — OK (skipped=6)** — kalan 6 atlama `ISTOC_HTTP_USER/PASS` isteyen `YetkiliCanliTesti` |
| 5 | `python -m unittest …test_crop_geometry` (konteyner) | **Ran 37 tests — FAILED (failures=1)** — `test_ts_ikizi_ayni_sayiyi_veriyor` |
| 6 | `python3 scripts/gen_http_openapi.py --check` | **temiz** (belge ↔ kod sapması yok) |
| 7 | `docker exec istoc-dev-backend-1 ffmpeg -filters \| grep -c libvmaf` | **0** |
| 8 | `docker exec istoc-dev-backend-1 ffmpeg -version \| head -1` | `ffmpeg version 5.1.9-0+deb12u1` |
| 9 | `docker exec istoc-dev-backend-1 node --version` | **v20.19.2** (nvm altında tek sürüm) |
| 10 | Canlı DB: 17 medya DocType'ının kurulu/satır sayımı | §5.2 tablosu |
| 11 | Canlı DB: `tabDocField where parent='Media Crop Override'` | `profile` = **`Data`** (Link DEĞİL) — §4.4 |
| 12 | `core/crop.py` zinciri, 600 vaka, `safe_area` çevrilerek yeniden koşuldu | §5.3 — bu raporun **yeni** ölçümü |
| 13 | `.github/workflows/` içinde test koşucusu araması | **0 dosya** (5 workflow'un hepsi release/deploy) |
| 14 | Repo geneli `INV-[0-9]+` sayımı | En büyük medya invariant'ı **INV-11**; INV-12 **yok**; kapsam haritası belgesi **yok** |

---

## 3. FAZ 6 — T-067

### 3.1 Kriter kriter durum

Kaynağın kabul kriterleri (`34-dogrulama-faz4-7.md` §3'ten alınmıştır):

| # | Kriter | Durum | Kanıt (bu oturum) |
|---|---|---|---|
| 1 | Tüm fixture'lar manifest beklentilerini karşılar (**GREEN**) | ✅ | `test_render_regression` **32 test OK**. Tek atlama `test_buyuk_tuvalde_vekil_bayragi_kalkar` — *"yalnız numpy YOKKEN anlamlı"*, yani ortama bağlı **dürüst** bir atlama, gizlenmiş bir başarısızlık değil |
| 2 | 12 invariant ≥1 testle kapsanır + **kapsam haritası** | ❌ | Repo genelinde bulunan en büyük medya invariant kimliği **INV-11**; **INV-12 hiç geçmiyor**, yani "12 invariant"ın kanonik listesi bu depoda **enumerate edilmemiş**. Testlerde adı geçen invariant: **INV-02, INV-05, INV-06, INV-09, INV-10** (5 tanesi). **Kapsam haritası belgesi yok** (`docs/test/` altında `traceability.md` + `req-test-map.json` var, invariant haritası değil) |
| 3 | Performans bütçeleri ölçülü, **CI eşikleri** tanımlı | ⚠ | Bütçeler **kodda pinli**: `URETIM_ZINCIRI` (9 slot × profil, bayt + kalite + SSIM temelleri), `BUGUNKU_TEK_CIKTI_BAYT = 303.670`, `test_encode_butcesi_asilmadi`. Ama "CI eşiği" **kavram olarak boşta**: koşacağı bir CI yok (kriter 4) |
| 4 | Regresyon paketi **her PR'da CI'da koşar** (<10 dk) | ❌ | `.github/workflows/` = `alpha-release.yml`, `beta-release.yml`, `rc-release.yml`, `prod-release.yml`, `deploy.yml`. `run-tests\|pytest\|unittest\|node --test` araması → **0 isabet**. Bu oturumda yeniden doğrulandı |

### 3.2 Altın matris — düşen kilit onarıldı

`34-dogrulama-faz4-7.md` §0.2b bugün Faz 6'yı KIRMIZI bulmuştu: logo politikalarına
`w384` rung'u eklenmiş, `MATRIS_ALTIN` sabiti güncellenmemişti. **Bugün onarıldı**
ve ölçüldü:

```
MATRIS_ALTIN = {brand.logo: 6, category.banner: 6, company.cover_image: 10,
                company.cover_video: 3, document.attachment: 1, product.image: 12,
                product.video: 3, seller.logo: 6, user.avatar: 3, _toplam: 50}
```

`test_matris_sayilari`, `test_slot_listesi`, `test_toplam_tutarli` üçü de yeşil —
yani matris **hem politikayla hem kendi toplamıyla** tutarlı. Bu, T-021 K3 kararının
(§6.1) motor tarafındaki karşılığıdır: karar → politika → altın matris zinciri
kapandı.

> **Kilidin kendisi doğru çalıştı.** Politika genişledi, kilit düştü, kilit
> güncellendi. T-067'nin varlık sebebi tam olarak budur ve bugün **çalıştığı
> ölçüldü**.

### 3.3 Karar

**Faz 6 bugün KAPANMAZ** — ama kalan iki eksik **teknik** ve kimsenin imzasını
beklemiyor:

1. Test koşan bir workflow (kriter 4). Bu tek başına kriter 3'ün "CI eşiği"
   yarısını da açar.
2. 12 invariant'ın kanonik listesi + kapsam haritası (kriter 2). **Uyarı:** liste
   repoda yok; "12" sayısının kendisi doğrulanamadı. Haritayı yazacak kişi önce
   listenin nerede tanımlı olduğunu bulmalı, yoksa 12'yi de **ölçmelidir**.

---

## 4. FAZ 7 — T-075

### 4.1 Bugün kapanan bloklayıcılar (rapor 39'un ölçümleri, bu oturumda test tarafından doğrulandı)

`18-faz7-kapanis.md` §9.1 üç yüksek bloklayıcı sayıyordu: B-1, B-2, B-6.

| Bloklayıcı | Durum | Bu oturumdaki doğrulama |
|---|---|---|
| **B-1** — H.264 hedefi kütüphanede hiç kazanmıyor | ✅ **KAPANDI** | capped-CRF eklendi (`rate_ceiling_kbps`, tavan INV-05'ten türetiliyor). Kapıyı geçen gerçek TRANSCODE **0 → 2**, net kazanç **+2.676.734 B** (rapor 39 §2.3). Vacuity anahtarı testte pinli (`HizDenetimi.test_rate_control_crf_TAVANI_KALDIRIR`) — **167 test bugün yeşil koştu** |
| **B-2** — kapıdan düşen TRANSCODE, REMUX ihtiyacını da öldürüyor | ✅ **KAPANDI** | Geri çekilme yolu eklendi; gerçek dosyada (r1, moov sonda) doğrulandı: moov **başa alındı**. Kapalıyken moov'un sonda kaldığı **ayrıca** pinli (`GercekRemux.test_geri_cekilme_KAPALIYKEN_moov_SONDA_KALIR`) |
| **B-6** — VMAF ölçülemiyor | ❌ **KAPANMADI** | Bu oturumda yeniden ölçüldü: `ffmpeg -filters \| grep -c libvmaf` → **0**; ffmpeg **5.1.9-0+deb12u1**. `requirements.txt`'te de değişiklik yok (bugün eklenen tek satır `elasticsearch>=8.0.0`; **`boto3` hâlâ yok**) |

Ek olarak `34-dogrulama-faz4-7.md`'nin iki "ÖLÇÜLMEDİ" maddesi kapandı: süre farkı
(≤100 ms → ölçülen 0–1 ms) ve mobil veri tavanı (ilk 10 sn: 161.841 / 173.121 /
275.581 B, tavan 1.280.000 B). HLS **gerçek tarayıcıda** oynatıldı (hls.js,
HeadlessChrome 151, `readyState=4`, 405 segment).

> **Ölçüm kaynağı ayrımı:** yukarıdaki bayt ve VMAF sayıları `39-t072-video-hatti.md`'de
> koşuldu, bu oturumda **yeniden koşulmadı**. Bu oturumda koşulan şey, o çalışmanın
> **testlerinin bugün de yeşil olduğudur** (167/167, 0 atlama).

### 4.2 Yeni ölçülen çelişki — VMAF ≥93 ile INV-05 aynı anda sağlanamaz

`39-t072-video-hatti.md` §4, gerçek 1080p bir kaynakta (r2) bayt/kalite eğrisini çıkardı:

| Tavan | Çıktı baytı | Kaynağa göre | VMAF @1280×720 | Fayda kapısı (INV-05) |
|---|---:|---:|---:|---|
| 924k (**uygulanan**) | 6.887.018 | −19,0% | **86,40** | ✅ geçer |
| 1100k | 8.161.583 | −4,0% | 89,12 | ❌ düşer |
| 1400k | 10.248.429 | **+20,5%** | **92,11** | ❌ düşer |
| tavansız CRF 23 | 14.490.432 | +70,4% | 95,49 | ❌ düşer |

Fayda kapısı çıktının en fazla **7.654.412 B** olmasını istiyor; o bütçedeki en iyi
ölçülen VMAF **≈86–89**. **VMAF 92,11'e çıkmak kaynaktan %20 büyük dosya
gerektiriyor.**

Diğer iki gerçek dosyada CRF 23'ün tavanı (çıktı çözünürlüğünde):
r3 = **77,81** (capped) / 79,83 (tavansız) · r6 = **74,88** (capped) / 75,60 (tavansız).

93 eşiği **sentetik `testsrc2` korpusundan** kalibre edilmişti (`22-t072-vmaf-av1.md`:
7 fixture'ın 6'sında ≥93). Gerçek, zaten bir kez sıkıştırılmış içerikte bandın
**75–90** olduğu ölçüldü.

> **n = 3.** Bu çelişki üç gerçek dosyada ölçüldü (r2, r3, r6). Küme küçüktür; ama
> çelişkinin kanıtı için **bir** karşı örnek yeterlidir: r2'de iki kriterin aynı anda
> sağlanamadığı sayısal olarak gösterildi.

### 4.3 KARAR GEREKİYOR — üç seçenek, ölçülen bedelleriyle

Bu maddeyi teknik olarak çözmenin yolu yok: bugünkü hâliyle kapı **boştur** —
hiçbir gerçek dosya iki kriteri birden sağlayamaz. Seçenekler ve **ölçülen**
sonuçları:

| # | Seçenek | Ölçülen sonuç | Bedel |
|---|---|---|---|
| **A** | Eşiği çıktı çözünürlüğünde **VMAF ≥ 85**'e indir | r2 (86,40) **geçer**; r3 (77,81) ve r6 (74,88) **düşer** | r3 bugün **+%46,93 bayt kazandırıyor** ve bloklanırdı — kazanılmış baytı geri veriyoruz |
| **B** | **Göreli** kriter: capped çıktı, tavansız CRF 23 referansından en fazla X puan geride olsun | r3 −2,02 · r6 −0,72 · r2 **−9,09** | X=3 seçilirse r3/r6 geçer, r2 düşer — yani en büyük bayt kazancını (1,6 MB) veren dosya bloklanır |
| **C** | VMAF'ı **yayım kapısı** olmaktan çıkar, **raporlanan metrik** yap; tek sert kapı INV-05 kalsın | Bugünkü kodun süre kapısıyla **aynı desen**: `duration_gate` çıktıyı atmaz, **not düşer** (`quality_gate.duration_note`) | Kaynağın "VMAF ≥93 yayımlanma koşuludur" cümlesinden **bilinçli sapma**; imza gerektirir |

**Önerim: C + kayıt.** Gerekçe ölçülmüş: (a) hattın kendisi zaten bu deseni
kullanıyor — süre farkı ölçülüyor, kapı atmıyor, karar çağırana bırakılıyor;
(b) A ve B'nin ikisi de ölçülmüş **gerçek bayt kazancını** geri veriyor;
(c) INV-05 zaten sert bir kapı ve **kaynağı koruyor**, yani kalitesizleşme riski
tek yönlü değil. C seçilirse `quality_gate.vmaf_min` silinmemeli, **`vmaf_report_floor`**
gibi bir rapor eşiğine dönmeli ki eşiğin altına düşen çıktılar envantere düşsün.

**Bu bir öneridir, karar değildir.** Karar platform yöneticisinindir ve
`docs/standards/company-cover-video.md` §10.9'daki karar bloğuna girmelidir.

### 4.4 Karar verilse bile kalan iş

`libvmaf` üretim imajında **yok** (bugün ölçüldü). Hangi seçenek seçilirse
seçilsin, hat kendi kalitesini ölçemediği sürece kriter — 93 olsun 85 olsun —
**üretimde uygulanamaz**. `22-t072-vmaf-av1.md` ve `39-t072-video-hatti.md`'nin
bütün VMAF sayıları **dış imajla** (`linuxserver/ffmpeg`) ölçüldü; bu, ölçümün
yapıldığını kanıtlar, **hattın ölçebildiğini kanıtlamaz**.

### 4.5 Faz 7'nin diğer açıkları — bugünkü durum

| # | Konu | Durum |
|---|---|---|
| B-3 | `video_decision.json` `status: "draft"` | ❌ **AÇIK** — bugün ölçüldü, `status` hâlâ `draft`. Aynı durum `brand-logo.json`, `seller-logo.json`, `company-cover-video.json` için de geçerli: üçü de `draft`. **Karar belgeleri onaylı, politika dosyaları taslak** — imza zinciri kopuk |
| yeni B-3 (rapor 39) | HLS merdiveninde fayda kapısı yok; 720p basamağı kaynaktan %25,7 büyük çıkabiliyor | ❌ **AÇIK**, düzeltilmedi |
| — | Poster bayt kapısı (120 KB) gerçek içerikte ancak WebP kalite 40'ta tutuyor | **KARAR GEREKLİ** (poster genişliğini düşür / kapıyı yükselt / kaliteyi feda et) |
| — | HDR→SDR tone-mapping (T-072/5) | — **ÖLÇÜLMEDİ**, kütüphanede HDR kaynak yok |
| — | Ses/görüntü senkron kayması (lip-sync) | — **ÖLÇÜLMEDİ** — süre farkıyla aynı şey değil |
| — | Safari/iOS yerel HLS, ABR basamak geçişi | — **ÖLÇÜLMEDİ** |
| — | `test_media_transcode` (22) + `test_media_transcode_retry` (39) | ⚠ Ortam kusuru — `IncorrectSitePath: test_site does not exist`; eski `media/transcode.py` hattını sınıyorlar, Faz 7 paketinin dışında |

---

## 5. FAZ 8 — T-085

### 5.1 Sözleşme tarafı — gerçekten kapandı

| İddia | Rapor 32 (önce) | Rapor 41 + bugün | Bu oturumdaki doğrulama |
|---|---|---|---|
| Uç sayısı | 87 | **90** | `x-endpoint-count: 90` |
| Ölçülmemiş uç | 77 | **1** | `create_media_backup` — gerekçesi belgede yazılı |
| Sözleşme testi | 25 test, 7 atlama | **41 test** | Bugün koşuldu: **41 OK**, canlı taban verilince **skipped=6** (yalnız kimlik isteyen `YetkiliCanliTesti`), kimlikle **0 atlama** (rapor 41) |
| Belge ↔ kod sapması | — | yok | `gen_http_openapi.py --check` → **temiz** |
| `Media Storage Settings` uçları | ❌ HTTP 500 | ✅ 200 | Rapor 41 §3; bugün yeniden çağrılmadı — **bu oturumda ölçülmedi** |

Ölçülen 7 sözleşme sapması (`x-contract-deviations`) belgede ve testte kilitli:
417 vs 404 ayrımı, zorunlu parametre eksikliğinin 500 `TypeError` üretmesi,
argüman bağlamanın yetki kapısından **önce** çalışması, POST-only ucun GET'te
405 değil 403 vermesi, tek 400'ün CSRF olması, "bulunamadı" için tek bir kod
olmaması, iki ayrı "değişmedi" biçimi (`{not_modified:true}` vs `{status:304}`).

### 5.2 T-085'in KENDİ kriterleri — ölçüldü

| Kriter | Durum | Kanıt |
|---|---|---|
| OpenAPI v1 donduruldu, breaking-change süreci belgeli | ⚠ **YANLIŞ KATMAN** | `docs/api/README.md` §2 gerçek ve iyi yazılmış bir dondurma politikası (MAJOR/MINOR/PATCH tanımları, RFC 8594 `Deprecation`/`Sunset` yordamı). **Ama §2.5 "bugünün donmuş yüzeyi" = 21 uç** — yani `/api/media/v1/…` **çağrılamayan** kütüphane katmanı. `openapi-http.yaml` (90 uç, gerçek yüzey) README'de **hiç geçmiyor** (`grep openapi-http docs/api/README.md` → 0 isabet) ve dosyanın kendi `info.version`'ı `1.0.0`, dondurma/deprecation politikası **yok** |
| **TS istemci SDK** üretilmiş ve frontend kullanıyor | ❌ **YOK** | `docs/api/` = 3 dosya (`openapi.yaml`, `openapi-http.yaml`, `README.md`). `admin-panel/frontend/package.json` ve `tradehubfront/package.json` içinde `openapi-typescript` / `openapi-generator` **yok** |
| **Postman / Bruno** koleksiyonu | ❌ **YOK** | `*postman*`, `*bruno*`, `*.bru` araması → **0 dosya** |
| `spectral` lint (T-080'den devreden) | ❌ **YOK** | `.spectral*` yok, bağımlılıklarda `spectral` yok |
| `schemathesis`/`dredd` şema güdümlü fuzzing (T-084) | ❌ **YOK** | Repoda geçmiyor |

### 5.3 T-082'nin `overrides` uyuşmazlığı — kök nedenin YARISI kapanmış

Rapor 41 §4, `save_intent`'in `overrides` yolunun uçtan uca çalışmadığını ölçmüştü:
`Media Crop Override.profile` bir **`Link → Media Profile`**'dı ve `w384` gönderilince
Frappe **417 `LinkValidationError`** atıyordu.

**Bugün canlı DB'den ölçüldü:**

```
tabDocField where parent='Media Crop Override'
  profile   fieldtype=Data   options=None        ← Link DEĞİL
```

Yani Link kısıtı **kalkmış**. Kütüphane tarafı (`pipeline/api/crop.py::_parse_overrides`)
zaten slot içi kısa adı (`w384`) bekliyordu; `get_intent`in kendi yanıtı da kısa adı
döndürüyor. İki katmanın sözlüğü artık **çakışmıyor görünüyor**.

> ⚠ **BU BİR HTTP ÖLÇÜMÜ DEĞİLDİR.** `save_intent`'i `overrides` ile gerçek bir
> istekle çağırmadım — bu, satıcı oturumu + `Media Asset` + `Media Crop Intent`
> kaydı üretmeyi gerektirirdi ve beş ajan paralel çalışırken veri üretmemeyi
> seçtim. **Rapor 41 §4'ün uyuşmazlığı bugün yeniden ölçülmedi;** ölçülen tek şey,
> uyuşmazlığın *sebeplerinden birinin* şemada kalmadığıdır. Devir: bu yol uçtan
> uca yeniden çağrılmalı, `test_save_intent_uyusmazligi_belgede_DURUYOR` testi de
> ona göre ya doğrulanmalı ya güncellenmelidir.

### 5.4 Karar

**Faz 8 bugün KAPANMAZ.** Sözleşme tarafı — T-080/T-082/T-084'ün ölçüm maddeleri —
gerçekten kapandı ve kanıtı sağlam. Kapanmayan şey **T-085'in kendisidir**: SDK,
koleksiyon, lint. Bunlar ölçülemeyen şeyler değil, **yapılmamış** şeyler.

Ek olarak dondurma politikası **çağrılamayan katmanı** donduruyor; gerçek yüzey
(90 uç) sürümsüz. Bu, "v1 donduruldu" cümlesini bugünkü hâliyle yanıltıcı yapıyor.

---

## 6. FAZ 10 — T-105

### 6.1 Ön koşul değişti — DocType'lar artık kurulu

`35-dogrulama-faz8-11.md` §6, Faz 10'un kapanışını engelleyen **birinci** madde
olarak `Media Crop Intent`'in kurulu olmamasını göstermişti. **Bugün canlı DB'den
ölçüldü:**

| DocType | Kurulu | Satır |
|---|---|---:|
| Media Asset | ✅ | 0 |
| Media Rendition | ✅ | 0 |
| **Media Crop Intent** | ✅ **(önce YOK)** | 0 |
| **Media Crop Override** | ✅ **(önce YOK)** | 0 |
| **Media Usage** | ✅ **(önce YOK)** | 0 |
| **Media Version** | ✅ **(önce YOK)** | 0 |
| Media Profile | ✅ | 36 |
| Media Processing Job | ✅ | 0 |
| Media Storage Settings / Media Engine Settings | ✅ (Single) | — |
| Media Upload Session · Media Placement Preview · Media Policy · Media Source · Media Quality Report · Media Content Rule · Media Policy Profile | ❌ | — |

Buna bağlı iki tespit de **eskimiştir**:

* `useCropStudio.js:329`'daki `const saveAvailable = false;` sabiti **artık yok**;
  bugün gerçek bir `computed` (`Boolean(asset) && usable && !blocked && payloadIssues.length === 0`).
* `previewed_placements` **repoda hiç geçmiyor** tespiti **yanlışlanmıştır**:
  `media_crop_intent.json` alanı taşıyor, `api/media_crop.py:233/283` yazıyor,
  DocType denetleyicisi (`_validate_previewed_placements`) JSON'luğunu doğruluyor.

Yani T-104'ün kayıt yolu artık **var**; T-105'in ön koşulu kalktı.

### 6.2 Zoom ayrışması — YENİ ÖLÇÜM, bu raporun asıl bulgusu

`47-t100-crop-cekirdek.md` §3.2, UI↔sunucu **piksel** paritesini ilk kez ölçtü ve
600 vakada beş sınıf çıkardı. `48-t102-crop-onizleme.md` §2, zoom kaybını
`safe_area` ile kapattığını ve sapmanın **< 0,5 px** olduğunu bildirdi — ama
kanıtı `_cover_window`in **JS'e yeniden yazılmış** bir kopyasıyla yapılan bir
karşılaştırmaydı.

**Bugün asıl soruyu ölçtüm:** panelin gerçek yükü `core/crop.py`'nin gerçek
zincirine verilirse ne çıkıyor?

`admin-panel/frontend/scripts/gen_crop_pixel_vectors.py` panelin `savePayload`'ını
**doğrudan** `resolve_crop(intent=payload)`'a veriyor. Ama panelin yükü
`safe_area: {x,y,w,h}` taşıyor, `core/crop.py::safe_region_of` ise `safe_x`,
`safe_y`, `safe_w`, `safe_h` okuyor. Çeviriyi **gerçek yolda API katmanı yapıyor:**

```
panel savePayload        {"safe_area": {"x":…,"y":…,"w":…,"h":…}}
  → api/media_crop.py::_parse_safe_area   →  {"safe_x":…, "safe_y":…, "safe_w":…, "safe_h":…}
  → Media Crop Intent alanları (safe_x/safe_y/safe_w/safe_h — doctype JSON'unda VAR)
  → core/crop.py::safe_region_of          →  METHOD_SAFE_FOCAL
```

Ölçüm harness'i **bu katmanı atlıyor**. Aynı 600 vakayı, `safe_area`yı API'nin
yaptığı gibi çevirerek yeniden koşturdum (yalnız okuma; hiçbir dosya yazılmadı):

| Sınıf | Ne yapıyor | Vaka | **Fixture'daki** sapan / en büyük | **Çeviriden sonra** sapan / en büyük | Sunucu yöntemi |
|---|---|---:|---:|---:|---|
| **A** | Kilitli oran, zoom=1, yalnız odak | 120 | 5 / 1 px | **5 / 1 px** (değişmedi) | `focal` |
| **B** | Kilitli oran, **zoom > 1** | 120 | **119 / 7391 px** | **3 / 1 px** ✅ | **`safe_focal`** |
| **C** | Serbest kırpma + override | 120 | 104 / 3704 px | **104 / 3704 px** (değişmedi) | `override` |
| **D** | Kilitli oran + override | 120 | 7 / 1 px | **7 / 1 px** (değişmedi) | `focal` |
| **E** | Serbest kırpma, override yok | 120 | 86 / 3481 px | **86 / 3481 px** (değişmedi) | `focal` |

**İki sonuç, ikisi de önemli:**

1. **C5'in zoom düzeltmesi gerçekten çalışıyor** — ve bunun kanıtı artık ikinci bir
   JS yazımı değil, `core/crop.py`'nin **kendi zinciri**: 120 vakanın 120'si
   `safe_focal` seviyesine düşüyor, sapma **7391 px → 1 px**. Kalan 3 vaka
   A/D ile aynı **yuvarlama ifadesi** sınıfına giriyor, yeni bir kusur değil.
2. **T-105'in kabul kapısı bugün var olmayan bir yolu ölçüyor.**
   `cropPixelParity.test.js`'teki `BEKLENEN.B = {sapan: 119, enBuyuk: 7391}`
   sabiti hâlâ eski sayıyı pinliyor ve test **geçiyor** — çünkü ürettiği vektörler
   de aynı eksik yoldan geliyor. Yani kapı **yeşil yanıyor ama yanlış şeyi
   ölçüyor**: gerçek sistemde kapanmış bir ayrışmayı açık gösteriyor.

Ölçümün geçerliliği: `crop.py`'nin sha256'sı (`c547c3c1…`) ve `crop_pixel_cases.json`'ın
sha256'sı (`364fdee7…`) vektör dosyasının başlığındaki değerlerle **birebir aynı** —
yani fixture bayat değil, harness eksik.

> **Bu bir `admin-panel` düzeltmesidir ve bu görevde YAPILMADI** (`admin-panel`
> dokunma listesinde). Yapılacak iş tek satırlık değil ama küçüktür:
> `gen_crop_pixel_vectors.py` `safe_area`yı `safe_x/y/w/h`'ye çevirmeli
> (ya da `api/media_crop.py::_parse_safe_area`'yı çağırmalı), `BEKLENEN.B`
> yeniden ölçülmeli.

### 6.3 Açık kalan iki ayrışma — bugün ölçüldü, değişmemiş

**C sınıfı — serbest kırpma sunucuda orana zorlanıyor (104/120, 3704 px'e kadar).**
`core/crop.py::_fit_ratio_keeping_center` override'ı profilin oranına küçülterek
oturtuyor; bu **tasarım gereğidir** (T-041'in kabul kriteri: "pencere istenen orana
tam uyuyor"). Panel ise kullanıcının çizdiği serbest dikdörtgeni olduğu gibi
gösteriyor. Ayrışma bir kod hatası değil, **önizlemenin eksikliği**.

**E sınıfı — kilit kapalıyken panel taban bölgeyi kadraj sanıyor (86/120, 3481 px).**
`pixelBox`'ın *"sunucunun keseceği kutunun ta kendisi"* olduğu iddiası bu durumda
**yanlış**; sunucu profilin oranına kırpıyor.

**A/D — 1 px yuvarlama ayrışması (12/240).** Panel kaynak pikselinde
`floor(v + 0.5)` (yarım YUKARI), sunucu normalize uzayda `int(round(v))` (Python'da
yarım ÇİFTE). Pencere kenarı tam yarım piksele düştüğünde ayrışıyorlar. Çözümü
**iki taraftaki yuvarlamanın aynı ifadeyle yazılmasıdır**; bu `crop_geometry.py` /
`core/crop.py` işidir (bu görevin dokunma listesinde).

### 6.4 T-105'in hiç yapılmamış maddeleri

| Kriter | Durum |
|---|---|
| UI önizlemesi **sunucunun ürettiği gerçek rendition** ile piksel düzeyinde eşleşiyor | ❌ Ölçülen şey **kadraj KUTUSU**dur. Sunucunun ürettiği **görselin pikselleri** (yeniden örnekleme, renk profili, çizim) hiç karşılaştırılmadı — `Media Rendition` tablosu **0 satır**, bayraklar 0 |
| **20 gerçek görselde elle karşılaştırma** yapılmış ve raporlanmış | ❌ Böyle bir rapor repoda **yok** |
| Etkileşim performans hedefleri tutuyor (60 fps, 16 ms önizleme bütçesi) | — **ÖLÇÜLMEDİ** ve bu oturumda kasten ölçülmedi (paylaşımlı makine) |

### 6.5 Kırpma paritesi kapısı — `tradehub_core` tarafında hâlâ KIRMIZI

`47-t100-crop-cekirdek.md` parite kapısını **panel tarafında** tip soymadan
bağımsız hale getirdi (72/72 geçiyor). Ama `tradehub_core`'un **kendi** testi
bugün de düşüyor:

```
FAIL: test_ts_ikizi_ayni_sayiyi_veriyor
STDERR: /home/frappe/.nvm/versions/node/v20.19.2/bin/node: bad option: --experimental-strip-types
Ran 37 tests — FAILED (failures=1)
```

Konteynerde nvm altında **tek bir node var: v20.19.2**. Python tarafının kendi
ölçümleri aynı koşumda yeşil (`584 vektör · en büyük sapma 0.0 px`,
`çapraz 1,819e-12 px`, `oran 2,070e-16`) — yani **parite maddeten doğru, kapı
kırmızı**. Panel tarafındaki çözümün aynısı (`tests/tools/run_ts_vectors.ts`
yerine türetilmiş bir `.js` koşturmak) buraya da uygulanabilir; bu görevde
**yapılmadı** (`.py`/araç dosyaları dokunma listesinde).

### 6.6 Karar

**Faz 10 bugün KAPANMAZ.** Ama sebep listesi ölçümle **kısaldı**: ön koşul
(DocType) kalktı, zoom ayrışması gerçekten kapandı. Kalanlar:

1. **C ve E için karar** (§6.7) — teknik iş değil, sözleşme kararı.
2. Ölçüm harness'inin `safe_area` çevirisi (panel tarafı, küçük iş).
3. 20 gerçek görsellik elle karşılaştırma — hiç yapılmadı.
4. Etkileşim performansı — tarayıcıda ölçüm gerekiyor.
5. A/D yuvarlama birleştirmesi — `crop_geometry.py` / `core/crop.py`.

### 6.7 KARARA BAĞLI — C ve E sınıfları

Bu ikisi teknik olarak "düzeltilmez", çünkü **iki taraf da kendi işini doğru
yapıyor**; ayrışma bir **sözleşme boşluğundan** geliyor: panel kullanıcıya
*"seçtiğin bölge"yi*, sunucu *"keseceğim kutuyu"* konuşuyor ve ikisi aynı şey değil.

| Seçenek | Ne olur | Ölçülmüş bedel |
|---|---|---|
| **1** — `CropPreviewStrip` profil başına **sunucunun kutusunu** çizsin | Kullanıcı farkı görür; ayrışma "kusur" olmaktan çıkar, "bilgi" olur | Panel işi (T-104, C5). Sapma sayıları **düşmez**, anlamı değişir |
| **2** — Sunucu override'ı orana zorlamayı bıraksın (`_fit_ratio_keeping_center` gevşesin) | Ayrışma sıfırlanır | T-041'in *"pencere istenen orana tam uyuyor"* kabul kriteri **düşer** — rendition matrisi oranı garanti edemez. **Önermiyorum** |
| **3** — Panel serbest kırpmayı sunucunun oranına **anında** kelepçelesin | Ayrışma sıfırlanır, önizleme her zaman doğru | Kullanıcı serbest kırpma hissini kaybeder; E sınıfında kilit kapalıyken de oran zorlanmış olur |

**Önerim: 1.** Sebebi ölçülmüş: sunucunun davranışı (oranı garanti etmek)
rendition matrisinin **doğrudan** ön koşulu; onu gevşetmek Faz 6'nın matris
kilidini (50 rendition, §3.2) belirsizleştirir. Ayrışmanın maliyeti kullanıcının
**yanlış bilgilendirilmesidir**, yanlış çıktı değil — ve bunun ucuz çözümü
göstermektir.

---

## 7. T-021 / T-022 — logo ve video standartlarının karar durumu

### 7.1 Sayım — 14 karar, hepsi kapalı

| Belge | Kararlar | Ölçümle çözülen | Onayla/varsayılanla kapanan | **AÇIK** |
|---|---|---|---|---|
| `docs/standards/logo.md` §13 | K1–K6 (**6**) | K1, K2, K3 | K4, K5, K6 (§"VARSAYILANDA ONAYLANAN KARARLAR — 2026-08-19") | **0** |
| `docs/standards/company-cover-video.md` §10 | K1–K8 (**8**) | — | K2, K7, K8 (§10.9, platform yöneticisi) · K1, K3, K4, K5, K6 (varsayılanda) | **0** |
| **Toplam** | **14** | **3** | **11** | **0** |

> Görev notundaki "12 karar" sayısı bu iki belgede **14** olarak ölçüldü. Fark,
> video tarafında §10.9'un yalnız 3 kararı listelemesinden ve kalan 5'in belgenin
> sonundaki "VARSAYILANDA ONAYLANAN" bloğunda durmasından geliyor. **Açık karar
> kalmadı** — bu sonuç değişmiyor.

### 7.2 K3 — ölçümün kararı çevirdiği yer (T-021'in çekirdeği)

Tetik **önceden** yazılıydı: *"512 rung'unun gerçek baytı 40 KiB tavanına
yaklaşıyorsa B'ye geç."* §12-D4 koşuldu (18 gerçek logo, kayıpsız WebP):

| Ölçüt | Değer | Referans |
|---|---:|---|
| p50 | **27.162 B** | `icon-512.png` = 27.128 B ile neredeyse aynı |
| p90 | 83.522 B | — |
| max | **109.172 B** | tavanın **2,7 katı** |
| Tavanı aşan | **5/18** | — |
| Referanstan ağır | 9/18 | — |

Sonuç: **B — 5 rung (+`w384`)**. Öneri A (4 rung) **ölçümle düştü**.

**Zincir bugün uçtan uca doğrulandı:**

```
karar (logo.md §13-K3)  →  brand-logo.json + seller-logo.json profiles[w384]
                        →  MATRIS_ALTIN {brand.logo: 6, seller.logo: 6, _toplam: 50}
                        →  test_render_regression 32 test OK (bugün koşuldu)
```

`brand-logo.json`'un kendi `$comment` alanı kararı ve hesabını taşıyor
(`max_bytes 23040 = 40960 × 384² / 512²`). Yani karar → politika → motor → test
zincirinde kopukluk **yok**.

### 7.3 Ölçülen iki tutarsızlık (düzeltilmedi — `docs/standards/` salt okuma)

1. **`logo.md` §13.0 özet tablosu bayat.** Tablo K4, K5, K6'yı hâlâ
   *"⏳ **AÇIK**"* gösteriyor (satır 1024–1026), oysa aynı belgenin sonundaki
   "VARSAYILANDA ONAYLANAN KARARLAR — 2026-08-19" bloğu üçünü de kapatmış.
   Belgeyi baştan okuyan biri 3 açık karar görüyor; sonuna kadar okuyan 0.
2. **Politika dosyaları hâlâ `draft`.** Bugün ölçüldü:
   `brand-logo.json`, `seller-logo.json`, `company-cover-video.json`,
   `video_decision.json` — dördünün de `status` alanı **`"draft"`**.
   Kararlar onaylı, standart belgeleri onaylı, **politika JSON'ları taslak.**
   Bu, `18-faz7-kapanis.md`'nin B-3 bulgusunun logo tarafına da yayılmış hâlidir
   ve bir imza zinciri kopukluğudur — hangi belgenin yürürlükte olduğu dosyadan
   okunamıyor.

### 7.4 K7'nin bağlı işi (T-022) — hâlâ açık

`company-cover-video.md` §10.9 K7: *"rendition'lar medya kotasından SAYILSIN"* —
öneriden **ayrılan** karar. Belgenin kendi düzeltmesi (2026-08-19) çarpanı ölçtü:
nesne **6×**, **bayt 2,85× / 3,13× / 4,56×**, yani operatif çarpan **~3**.
Kritik ayrım belgede yazılı: kota kapısı **bayt** üzerinden zorluyor
(`entitlement/checks.py:272` ← `media/files.py:267`), nesne sayısı üzerinden değil.

**Ölçülmüş eksik, kapanmadı:** 6 nesne modeli **HLS'i hiç saymıyor** — HLS gereken
tek dosya **409 nesne / +27,3 MB** üretti. Belgenin kendi cümlesi:
*"Kota değerleri yeniden boyutlandırılmalı ya da rendition'lar için ayrı bir kota
kalemi tanımlanmalıdır."* `docs/standards/kota.md` bu karara göre **güncellenmedi**
(bu görevde ölçülmedi, belgenin beyanı aktarıldı).

Ayrıca K7 bugün **uygulanmıyor**: video paketi `frappe` import etmiyor ve `File`
kaydı açmıyor.

### 7.5 Karar

**T-021 ve T-022 karar tarafında KAPALI** (14/14, 0 açık). Kapanmayan şey
kararların **uygulaması**: K5'in panel metni, K7'nin kota bağlantısı, K2'nin
`VerificationBadge` kapısı, ve dört politika dosyasının `draft` → `approved`
geçişi. Bunlar standardın değil, **standardı uygulayan görevlerin** işidir.

---

## 8. Bu raporun ölçMEDİĞİ şeyler — açıkça

| # | Ne | Neden |
|---|---|---|
| 1 | `save_intent`'in `overrides` yolu **gerçek HTTP ile** | Satıcı oturumu + `Media Asset` + `Media Crop Intent` kaydı üretmeyi gerektirirdi; beş ajan paralel çalışırken veri üretmedim (§5.3) |
| 2 | `media_storage_settings` uçlarının bugünkü durumu | Rapor 41 §3'te 200 ölçülmüş; bu oturumda **yeniden çağrılmadı** |
| 3 | Sunucunun ürettiği **görselin** pikselleri | `Media Rendition` 0 satır, bayraklar 0; render + görsel karşılaştırma gerekir |
| 4 | Bütün zamanlama/performans hedefleri (60 fps, 16 ms, <10 dk CI) | Makine paylaşımlı — **kasten** ölçülmedi |
| 5 | VMAF sayıları | Üretim imajında `libvmaf` yok; dış imajla ölçüm bu oturumda **tekrarlanmadı**, rapor 39'un sayıları aktarıldı |
| 6 | `bench migrate` temiz koşumu | Paralel ajanlar var; migrate kilidi riskli — koşturmadım |
| 7 | Faz 6/7/8/10 dışındaki test modülleri | Kapsam dışı |
| 8 | Üretim ortamı (nginx, CDN, imaj) | Yalnız dev stack'e erişim var |

---

## 9. Devir — sahibiyle birlikte

| # | İş | Faz | Sahibi | Tek adım mı |
|---|---|---|---|---|
| 1 | Test koşan bir CI workflow'u (`bench run-tests` ya da `python -m unittest`) | 6, 8 | CI sahibi | ✅ evet — T-067/4 ve rapor 41 §8-7'yi birlikte kapatır |
| 2 | 12 invariant'ın kanonik listesi + kapsam haritası (**önce listenin var olup olmadığı ölçülmeli**) | 6 | belge sahibi | ✅ evet |
| 3 | **VMAF eşiği kararı** (§4.3 A/B/C) | 7 | **platform yöneticisi** | ❌ karar |
| 4 | `libvmaf`'lı ffmpeg üretim imajına | 7 | `docker/` sahibi | ✅ evet — ama 3'ten sonra anlamlı |
| 5 | Dört politika JSON'unun `status: draft → approved` | 6, 7 | politika sahibi | ✅ evet |
| 6 | TS SDK + Postman/Bruno + spectral | 8 | API sahibi | ❌ üç ayrı iş |
| 7 | `openapi-http.yaml` için sürüm/dondurma politikası (README §2 bu belgeyi hiç anmıyor) | 8 | belge sahibi | ✅ evet |
| 8 | `gen_crop_pixel_vectors.py`'ye `safe_area → safe_x/y/w/h` çevirisi + `BEKLENEN.B`nin yeniden ölçülmesi | 10 | `admin-panel` sahibi | ✅ evet |
| 9 | **C ve E ayrışması kararı** (§6.7) | 10 | ürün sahibi | ❌ karar |
| 10 | 20 gerçek görselde elle karşılaştırma oturumu | 10 | — | ❌ oturum |
| 11 | A/D yuvarlama ifadesinin iki tarafta birleştirilmesi | 10 | `core/crop.py` sahibi | ✅ evet |
| 12 | `tests/tools/run_ts_vectors.ts` → türetilmiş `.js` (panel tarafındaki çözümün ikizi) ya da konteynerde Node 22+ | 10 | test sahibi | ✅ evet |
| 13 | `logo.md` §13.0 özet tablosunun K4/K5/K6 satırları (bayat "AÇIK") | T-021 | standart sahibi | ✅ evet |
| 14 | `kota.md`'nin K7 kararına göre güncellenmesi (HLS'in 409 nesnesi dahil) | T-022 | standart sahibi | ✅ evet |
| 15 | `save_intent` `overrides` yolunun uçtan uca yeniden ölçülmesi (§5.3) | 8 | API sahibi | ✅ evet |
| 16 | `boto3` `requirements.txt`'te değil — imaj yeniden kurulunca S3 kipi ve 91 MinIO testi düşer | 5 | bağımlılık sahibi | ✅ evet |

---

## 10. Yeniden üretim

```bash
# Faz 6 — altın matris + regresyon paketi
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -m unittest tradehub_core.tests.test_render_regression

# Faz 7 — video paketi (167 test, ~3 dk)
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core istoc-dev-backend-1 \
  /home/frappe/frappe-bench/env/bin/python -m unittest \
  tradehub_core.tests.test_video_decision tradehub_core.tests.test_video_transcode

# Faz 7 — libvmaf var mı
docker exec istoc-dev-backend-1 ffmpeg -hide_banner -filters | grep -c libvmaf   # 0 bekleniyor

# Faz 8 — sözleşme kilidi + canlı ölçüm
python3 scripts/gen_http_openapi.py --check
docker exec -w /home/frappe/frappe-bench/apps/tradehub_core \
  -e ISTOC_HTTP_BASE=http://127.0.0.1:8000 -e ISTOC_HTTP_HOST=istoc.localhost \
  istoc-dev-backend-1 /home/frappe/frappe-bench/env/bin/python -m unittest \
  tradehub_core.tests.test_http_api_contracts

# Faz 10 — §6.2'nin ölçümü (yalnız OKUR, hiçbir dosya yazmaz)
#   safe_area'yı API'nin yaptığı gibi safe_x/y/w/h'ye çevirip 600 vakayı yeniden çözer
python3 - <<'PY'
import json, importlib.util, sys, collections
CORE = "tradehub_core/media/pipeline/core/crop.py"          # depo kökünden
FE   = "../admin-panel/frontend/src/lib/media/crop/vendor"
spec = importlib.util.spec_from_file_location("th_crop_core", CORE)
crop = importlib.util.module_from_spec(spec); sys.modules["th_crop_core"] = crop
spec.loader.exec_module(crop)
cases = json.load(open(f"{FE}/crop_pixel_cases.json"))["cases"]
agg = collections.defaultdict(lambda: {"adet":0,"sapan":0,"enBuyuk":0,"m":collections.Counter()})
for c in cases:
    p = dict(c["payload"]); sa = p.pop("safe_area", None)
    if isinstance(sa, dict) and sa:
        p.update({"safe_x":sa["x"], "safe_y":sa["y"], "safe_w":sa["w"], "safe_h":sa["h"]})
    s = c["source"]; pr = c["profile"]
    w = crop.resolve_crop({"width":s["width"], "height":s["height"]},
                          {"profile_key":pr["profile_key"],
                           "aspect_ratio_value":pr["aspect_ratio_value"], "fit":pr["fit"]},
                          intent=p)
    box = list(w.to_pixels(s["width"], s["height"]))
    a = agg[c["sinif"]]; a["adet"] += 1; a["m"][w.method] += 1
    d = max(abs(x-y) for x,y in zip(c["panel_box"], box))
    if d: a["sapan"] += 1
    a["enBuyuk"] = max(a["enBuyuk"], d)
for k in sorted(agg):
    a = agg[k]; print(k, a["adet"], a["sapan"], a["enBuyuk"], dict(a["m"]))
PY
# Beklenen: A 120 5 1 · B 120 3 1 (safe_focal) · C 120 104 3704 · D 120 7 1 · E 120 86 3481
```

---

## 11. Değiştirilen dosyalar

| Dosya | Durum |
|---|---|
| `docs/reports/56-d3-faz6-10-kapanis.md` | **YENİ** — bu rapor |
| `docs/reports/18-faz7-kapanis.md` | **EK** — yalnız "kanıt ve kapı durumu" bölümü. İmza bloğuna (§11) **dokunulmadı** |
| `docs/reports/32-faz8-api-kapanis.md` | **EK** — yalnız "kanıt ve kapı durumu" bölümü |
| Diğer her şey | **DEĞİŞMEDİ** — `.py`, DocType JSON, politika JSON, `docs/standards/`, `admin-panel`, `docker/` |

**Bayraklar 0'da bırakıldı.** Ölçüm için üretilen tek geçici dosya
`/tmp/t105run/t105_measure.py`'dir; hiçbir depo dosyasına yazılmadı.
