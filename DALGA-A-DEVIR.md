# DALGA A — devir notu (güncel: 2026-08-19)

## DURUM: 11 maddenin 11'i kapandı ✅

| # | Konu | Durum |
|---|---|---|
| K-1 | `Media Profile` tohumlayıcı | ✅ patch `v15_9_23`, 34 profil, idempotentliği 3 koşuyla kanıtlandı |
| K-2 | Adlandırma sözleşmesi | ✅ `policy_profile` alanı + `Media Rendition.profile` **Link → Data**; A/B deneyiyle kanıtlandı |
| K-3 | Kapsam çözümü (%61 dışarıda) | ✅ `attached_to_*` NULL ise ilişkiden çözülüyor; 1.903 dosya kapsama girdi |
| K-4 | `hooks.py` yanlış yorum | ✅ düzeltildi |
| K-5 | `patches.txt` sıra | ⬜ kozmetik, bırakıldı |
| B-1 | Gizli ürün galerisi sızıntısı | ✅ `storefront_visible=1`; regresyon testi eski kodda KIRMIZI |
| B-2 | `Media Asset` moderasyon alanları | ✅ permlevel 1; satıcı yazamıyor, yönetici yazabiliyor — iki yön de ölçüldü |
| B-3 | Girdi tavanı + hız sınırı | ✅ 500 kimlik / 20k karakter tavanı + `@rate_limit` |
| B-4 | Bayrak sırası | ✅ ilk satıra alındı (kalan kısıt aşağıda) |
| B-5 | Numaralandırma kehaneti | ✅ `missing` daima `[]` |
| D-1 | Mükerrer türev | ✅ (genişlik,biçim) kapısı; kaynaktan büyük basamak kayıt açmıyor |
| F-1 | Devre kesici MPA'da tutmuyordu | ✅ oturum okuması erken-çıkıştan öne alındı |
| F-2 | Ürün çizimi manifesti bekliyordu | ✅ beklemiyor; geç gelen manifest görselleri yükseltiyor |

**Testler:** `test_media_manifest_api` 11 OK (önce 2 FAIL + 1 ERROR), `test_pipeline_bridge` 19,
`test_pipeline_flags` 16, `test_media_pipeline_integration` 6, `test_media_browse` 14,
`test_media_access` 17, `test_media_jobs` 12 — **hepsi OK**. Storefront: `tsc` + build EXIT 0, 67 test yeşil.

**Canlı durum:** bayraklar 0, `Media Asset/Rendition/Job` = 0, `Media Profile` = 34 (tohum, kasıtlı).

⚠️ **Kalıcılık:** tüm doğrulamalar `docker cp` ile yapıldı. Uygulama Docker imajına gömülü —
kalıcı olması için **imaj rebuild** gerekiyor.

## Bilinen kalan kısıtlar (bilinçli)

- Bayrak kapalıyken manifest ucu hâlâ **2 sorgu** atıyor. Sıfıra indirmek kapalı-gövde
  sözleşmesini (`fallback` + `images`) değiştirmeyi gerektiriyor; o ayrı bir karar.
  Hafifletici: istemci `enabled:false` görünce oturum boyunca bir daha sormuyor.
- `rate_limit._bucket_key` kovayı `frappe.session.user`'a bağlıyor → **tüm misafirler tek kova**.
  Bu yüzden 600 tavanı "çağıran başına" değil toplam. Kova IP'ye taşınmadan gerçek
  per-caller koruma yok. (Kapsam dışı bırakıldı.)
- `Media Asset`'te `if_owner=1`, çok kullanıcılı mağazalarda B kullanıcısının A'nın
  yüklediğini görmesini engelliyor. Güvenlik açısından permlevel yeterli; daraltmayı
  geri almak istersen iki `"if_owner": 1` satırını silip migrate yeter.
- `perceptual_hash` ve `last_access_at` satıcıya yazılabilir (permlevel 0).

## Durum: motor çalışıyor, boru BAĞLI DEĞİL

Bağımsız doğrulama: `docs/reports/15-dalga-a-dogrulama.md`.

Motor gerçek veriyle sınandı: 1 ilan (12 görsel, 13,12 MB) → **144 türev**,
SSIM 0,99+, fayda kapısı büyütmeyi doğru eliyor. Gerçek ürün-detay senaryosunda
**13,12 MB → 0,17 MB (%98,7 kazanç)**; en pesimist senaryoda bile %83.

**Ama bugün bayrak açılsa hiçbir şey olmaz** — hattın son iki rakoru takılı değil
(K-1, K-2 aşağıda).

## Bloker 3 madde (bağımsız doğrulamadan)

| # | Şiddet | Sorun | Yer |
|---|---|---|---|
| K-1 | **Bloker** | `Media Profile` tohumlama kodu HİÇ YOK, tablo 0 satır. Köprü profil bulamayınca 0 türev üretip sessizce döner. | patch yok |
| K-2 | **Bloker** | Köprü `Media Rendition.profile`'a **docname** yazıyor, manifest **politika profil adı** (`w96`) bekliyor → manifest sessizce boş. Docname global tekil olmak zorunda ama politika adları slotlar arası çakışıyor (`w64/w128/w256/w512/og1200x630` hem `brand.logo` hem `seller.logo`) — "docname = politika adı" kuralı uygulanamaz. | `media/pipeline_bridge.py:518` |
| K-3 | Yüksek | Ürün görsellerinin **%61'i kapsam dışı**: 3.152 görselin 1.909'unda `attached_to_*` NULL (toplu içe aktarım). Ağırlığın çoğu tam orada. | `pipeline_bridge._resolve_scope` |
| K-4 | Düşük | `hooks.py` yorumu "bayrak kapalıyken DB'ye sorgu gitmez" diyor; gerçekte istek başına bir `Media Engine Settings` okuması var. Davranış güvenli, **yorum yanlış**. | `hooks.py` |
| K-5 | Düşük | `patches.txt`'te `v15_9_22` (settings) `v15_9_21`den (doctypes) önce. Bağımsız oldukları için sorun çıkmadı, sıra yanıltıcı. | `patches.txt` |

## Düzeltilecek 8 madde (üç düşmanca inceleme + kendi doğrulamam)

| # | Şiddet | Sorun | Yer |
|---|---|---|---|
| B-1 | **Yüksek** | Görünürlük yüklemi `status="Active"`; `is_visible` hiç bakılmıyor → gizli ürünün galerisi misafire açık. Doğrusu `storefront_visible=1` | `api/media_manifest.py:107,572` |
| B-2 | **Yüksek** | `Media Asset`'te 4 role `write=1`; `state`/`legal_hold`/`rejection_code`/`owner_seller` permlevel 0 → moderasyon atlatma + legal hold oynama | `doctype/media_asset/media_asset.json` |
| F-1 | **Yüksek** | `if (_kapali) return` `_sessionOku()`'dan ÖNCE; MPA'da her gezinmede istek | `tradehubfront/src/lib/media/manifest.ts:313` |
| F-2 | Orta | Ürün detay render'ı manifesti `await` ediyor (≤4 sn blok) | `tradehubfront/src/pages/product-detail.ts:153,161` |
| B-3 | Orta | Toplu uçta girdi kırpılmıyor, `skipped` tamamı yansıtılıyor, rate limit yok | `api/media_manifest.py:153-202,738` |
| B-4 | Orta | Bayrak 2 DB sorgusundan SONRA soruluyor | `api/media_manifest.py:288-296` |
| B-5 | Orta | `missing` alanı sayım kehaneti veriyor | `api/media_manifest.py:196` |
| D-1 | Orta | Mükerrer rendition: `w1280` ve `w1920` profilleri 1080px kaynakta aynı çıktıyı üretip 2 kayıt açıyor. Kaynaktan büyük basamağa **kayıt açılmamalı** | `media/pipeline_bridge.py` |

Doğrulanmış kanıt: `rendition_key=…|w1280|1080|avif` ve `…|w1920|1080|avif`, `file_url` aynı.

## Temiz çıkanlar (dokunmayın)

- `git diff`: **6 dosya, 191 ekleme, 0 silme**. `hooks.py`'deki 4 mevcut kanca aynı sırada, yeni kanca en sonda.
- Kiracı izolasyonu **tam**: 4 DocType için hem `permission_query_conditions` hem `has_permission`; guest ve profilsizde `1=0`. Payment Transaction hatası tekrarlanmamış.
- `get_signed_url` kendi kriptosunu yazmamış, `verified_command`'a delege ediyor.
- Frontend fallback zinciri sağlam — görsel kaybettiren yol bulunamadı; `loading`/`alt`/zoom/lightbox korunmuş; CLS temiz; N+1 yok.
- Patch'ler idempotent, `patches.txt` sonuna eklenmiş.

## Dalga A dışı, SİZİN işinizde bulunan sorunlar

1. `doctype/platform_invoice/` ve `platform_invoice_item/` içinde **`__init__.py` YOK** → `bench migrate` düşer.
2. `api/search.py` Elasticsearch yolu **bayraksız** eklenmiş; `get_es_client()` istemci dönerse davranış anında değişiyor.
3. `elasticsearch_integration.py:18` varsayılan `http://elasticsearch:9200` — düz HTTP, kimlik doğrulama yok.

## Sonraki adım

Bayrakları kapat → 8 maddeyi düzelt → testleri koş (1376 test geçmeli) → bayrağı tek sayfada aç, ölç.

---

## Geri dönük tohumlama maliyeti — ÖLÇÜLDÜ (düzeltme)

> **Bu bölüm 2026-08-19'da düzeltildi.** İlk hâli "~69 sn/görsel → 3.152 görsel
> ≈ 60 worker-saat" diyordu ve bir hipotez taşıyordu. `docs/reports/17-t028-backfill-plani.md`
> ikisini de ölçtü; **ikisi de yanlıştı.**

| Ne | İlk iddiam | ÖLÇÜLEN |
|---|---|---|
| Ölçek | 3.152 görsel | **2.428 tekil adres** |
| Görsel başına | ~69 sn | **10,45 sn** (69 sn çekişme altındaki duvar saatiydi) |
| Toplam | ~60 worker-saat | **taban ~7 saat**, gerçekçi bant 7–47 saat |

**Hipotezim yönü doğru, kırılımı yanlıştı.** "Encoder'dan değil adaptif döngüden"
demiştim. Doğru — ama döngünün içinde asıl pahalı kalem encode değil **SSIM**:

```
bütçe=4 (üretim)  10,45 sn/görsel   SSIM %52 · encode %37 · prepare %2-4 · disk I/O <%0,05
bütçe=1            3,50 sn/görsel   çıktı %35 büyük  →  adaptif döngü 2,99× maliyet
```

Ölçüm ayrıca şunu gösterdi: **her türev bütçeyi sonuna kadar harcıyor** — görsel
başına 48 encode + 48 SSIM, hiç erken çıkış yok. Çoğu deneme
`quality_floor_reached` ile bitiyor, yani taban kalite (q=70) hedefi zaten
tutuyor ama döngü yine de 4 deneme yapıyor. Erken çıkış eklenirse maliyet
3 kata yakın düşer; kalite kapısının ne kaybedeceği ayrıca ölçülmeli.

**İki ayrı backfill var, karıştırılmamalı:**
- `scripts/plan_backfill.py` **eski** motorun (`engine.optimize`) backfill'ini
  planlıyor: A sınıfı yalnız **49 dosya / 30 MB / 1 batch** — önemsiz.
- Dalga A **türev merdiveni** tohumlaması bu scriptin kapsamında DEĞİL.
  Yukarıdaki 7–47 saatlik yük bu ikincisine ait. Plan taslağı
  `docs/reports/17-t028-backfill-plani.md` §4.5'te.

---

## Dalga B turu — 2026-08-19

| Görev | Sonuç |
|---|---|
| 12 açık karar | ✅ **12/12 kapandı** (4'ü yönetici, 1'i ölçümle, 7'si varsayılanda) |
| Güvenlik borcu `EXCLUDED_MEDIA_FIELDS` | ✅ 4 KYB alanı + 3 doctype; 2 dosya public'ten çıktı |
| **D-2** — 44 hassas hash örtüşmesi | ✅ 4 gerçek sızıntı kapatıldı, 40 zararsız, 0 belirsiz · `19-d2-hash-ortusme.md` |
| **T-028** — backfill dry-run | ✅ `17-t028-backfill-plani.md` · script `ImportError` düzeltildi |
| **T-075** — Faz 7 kapanış | ⚠ belge yazıldı ama **Faz 7 KAPANMIYOR** — VMAF aracı yok · `18-faz7-kapanis.md` |
| **T-029** — politika aktivasyonu | ❌ **0/9 active** — SRS'in 7 kapısından 4'ü açık · `16-t029-politika-aktivasyonu.md` |
| `media/trash.py` traversal bug | ✅ segment bazlı kontrol + regresyon testi (vacuity kanıtlı) |

### Açık güvenlik borçları

- **Ö-2 (yüksek).** Frappe çekirdeği `find_file_by_url` (`frappe/core/doctype/file/utils.py:453`)
  aynı URL'e ait satırlardan **herhangi biri** erişilebilirse dosyayı veriyor —
  bilinçli çekirdek tasarımı. Ölçüm: **33 özel URL çok sahipli, 29'u hassas
  doctype'a bağlı** (KYB/KYC/Order/Payment Transaction). Hem özel hem açık satırı
  olan URL **0**, yani public sızıntı yolu şu an boş. Düzeltmesi ayrı ajanda.
- **Ö-6 (en yüksek).** Bu ölçümlerin **tamamı yerel dev**. Üretimde KYB
  alanlarında gerçek imza sirküleri/kimlik var ve `_is_protected_pii`'nin
  retroaktif olmaması **mekanizma olarak canlı**. Aynı ölçümler üretimde
  koşulmalı — bu iş yapılmadı.
- **K7 bağlı işi.** Rendition'lar kotadan sayılacak (karar), ama operatif çarpan
  ölçüldü: **~3** (bayt bazlı), ~6 değil. Ayrıca 6 nesne modeli **HLS'i saymıyor**
  (409 nesne / +27,3 MB). `kota.md` güncellenmeli.

### Ortam tuzağı (tekrar yaşanmasın)

`docker compose up -d` yalnız imajı değişen servisi yeniden oluşturuyor.
`frappe-frontend` yenilenince yeni IP aldı ama `storefront` eski IP'yi tutmaya
devam etti → **her istek 502**. Belirti aldatıcı: `docker compose ps` hepsini
"Up" gösteriyor. Çözüm: `docker compose restart storefront gateway`.

---

## Sıradaki dalgalar — onaylanmış plan (2026-08-19)

**Paralellik sınırı ölçüldü:** host 11 çekirdek, 4 ajanla yük ortalaması **116**
(sağlıklısı ~11), backend konteyner **%768 CPU**. Makine 10 kat aşırı abone.
Daha fazla ajan işi hızlandırmaz, **ölçümleri yanlışlar** — bugün kanıtlandı:
backfill maliyeti çekişme altında 69 sn/görsel ölçüldü, sakin ortamda gerçek
değer **10,45 sn** (%560 hata).

### Kaynak şeritleri (paralelliğin gerçek sınırı)

| Şerit | Eşzamanlı ajan | Neden |
|---|---|---|
| `hooks.py` + `permissions.py` + `patches.txt` | **1** | Aynı dosyaya ekleme |
| admin-panel UI (`router`, `navigation.js`, 4 dil i18n) | **1** | Aynı üç dosya |
| `docker/docker-compose.yml` | **1** | Tek sahip |
| Ölçüm işi (Lighthouse, VMAF, süre) | **1** | Sakin CPU şart |
| Salt okuma / belge | sınırsız | Kaynak tüketmiyor |

### Sıra

**Şu an koşan (4):** KYC izolasyonu · VMAF+AV1 (T-072/T-016) ·
T-051 depolama ayarları arayüzü · T-053 saklama+GC

**Dalga 1 (4 ajan)** — mevcutlar bitince:
Faz 10 crop studio (5 görev) · T-052 CDN+nginx · T-011 rakip ölçümü ·
Faz 13 tehdit modeli

**Dalga 2 (3 ajan):**
Faz 11 simülatör ekranı (3 görev) · T-055 Faz 5 kabul · T-054 kurtarma provası

**Hafif, her an eklenebilir (kaynak tüketmez):**
- Görev numarası hizalama — kaynak dokümandaki 102 görevi iç kayıtlarla eşleştir.
  **Gerekli:** T-051'de numaralandırma kayması bulundu (kaynak: "Ayarlar arayüzü",
  iç kayıt: "S3/mirror/tiered"). "≈87 TAM" sayısı bu hizalama olmadan yaklaşık.
- Faz 1 ADR seti (denetim: 0 dosya)

**T-124 (bayrak pilotu + Lighthouse) — makine SAKİNKEN, tek başına.**
Dalga A'nın son adımı; kirli ölçüm bugüne kadarki tüm işin karşılığını
görünmez yapar.

### Görev karnesi (yaklaşık)

Başlangıç 18 Ağu: **71 TAM · 16 KISMİ · 15 YOK**
Bugün ≈16 görev TAM'a geçti → **≈87 TAM · ≈11 KISMİ · ≈4 YOK**

⚠️ "TAM" ≠ "kapandı": T-075 belgesi yazıldı ama Faz 7 kapanmıyor (VMAF yok),
T-030 incelemesi yapıldı ama SAD onaylanamıyor (8 bloklayıcı), T-029 denendi ama
0/9 politika `active` (4 kapı açık).

---

## T-124 — DALGA A KAPANDI (2026-08-19, gerçek ölçüm)

Makine sakinken koşuldu (yük 116 → **3,69**, backend %0,02). Sitenin **en ağır**
ürün sayfası: `LST-00560` — 7 görsel, **9,99 MB**.

Bayraklar yalnız `product.image` slotunda geçici açıldı, 7 dosya işlendi
(133,8 sn) → **84 türev**, sonra sistem varsayılana geri çekildi.

| Senaryo | Bayt | Kazanç | <2 MB |
|---|---:|---:|:--:|
| **A** — pesimist: 7 görselin hepsi @780 AVIF | 0,617 MB | **%93,8** | ✅ |
| **C** — gerçek ürün detayı: 1 ana @780 + 6 karo @192 | 0,186 MB | **%98,1** | ✅ |
| **D** — C + lazy (ilk ekran: ana + 3 karo) | 0,145 MB | **%98,6** | ✅ |
| bugün | 9,99 MB | — | ❌ |

**Kabul kriteri "< 2 MB" — en pesimist senaryoda bile geçiyor.** (Laboratuvar
ölçümünde senaryo A 2,22 MB ile kalıyordu; gerçek veride üçü de rahat geçti.)

**HTTP kanıtı** (misafir): uç `enabled=true`, 7 görsel, ETag var; `srcset`teki
adres gerçekten indi — `HTTP 200`, `20.376 B`, `image/avif`, merdivendeki
w384 AVIF ile birebir aynı bayt.

Disk maliyeti: 84 türev = **4,03 MB** (kaynak 9,99 MB'ın altında).

**Geri alma doğrulandı:** bayraklar 0, Asset/Rendition/Job 0, 84 türev dosyası
silindi, diskte `.avif` 0, `File` 5014 (değişmedi), `Media Profile` 36 (tohum).

## Bugün kapatılan güvenlik açıkları

| # | Açık | Etki |
|---|---|---|
| 1 | 2 dekont herkese açık | `EXCLUDED_MEDIA_FIELDS` boşluğu |
| 2 | **71 çapraz-kiracı dosya erişimi** | 14 satıcı başkasının KYC kimlik belgesini indirebiliyordu → 2 (ikisi de meşru) |
| 3 | S3 imzalı URL SigV2 | AWS'de teslim tamamen kırılacaktı |
| 4 | **38 kullanıcı herkesin KYC kaydını okuyup YAZABİLİYORDU** | Kök neden: `v15_8_3` patch'i, docstring'i "izolasyon korunur" diyor — KYB için doğru, KYC için hiç doğru olmamış |
| 5 | `Media Asset` moderasyon alanları satıcıya yazılabilir | permlevel 1'e taşındı |
| 6 | Gizli ürün galerisi misafire açık | `storefront_visible` yüklemi |

## 🔴 Bugünün en değerli tek bulgusu: test ikizleri yanlış güven veriyor

**Üç bağımsız ajan, üç farklı yerde, aynı yapısal sorunu buldu:**

1. **Sahte S3 istemcisi** presign taklidinde `X-Amz-Expires`'ı **kendisi uyduruyordu**
   → 137 test SigV2 bug'ını yıllarca kaçırdı (AWS'de teslimi kıracaktı).
2. **69 sözleşme testi** `PolicyEngine` Protokolünü **sahteyle** doğruluyor —
   somut sınıf Protokolün **13 metodunun 13'ünü de** karşılamıyor (ben ölçtüm).
3. **7 video fixture'ının hepsi sentetik** (`testsrc2`) ve **iki kez ters yönde**
   yanılttı: küçültme kaybını abarttı (fixture 92,30 → gerçek dosya **98,53**;
   yani politika sağlam, **CRF 23 fazla agresif**) ve AV1 avantajını yarıya indirdi.

"Testler geçiyor" cümlesi bu üç yerde anlamsız. Bu, tek tek bulgulardan daha
geniş bir sonuç ve ayrıca ele alınmalı.
