# Kapsamlı Medya Denetimi — Test Raporu

**Tarih:** 2026-08-28 (denetim) · **2026-08-29 (düzeltme turu — bkz. §0)**
**Kapsam:** MOGEM-617 (Media Engine, Faz 0–14) + MOGEM-620 (Medya SEO katmanı) ile
ilgili tüm backend ve frontend kodu — 3 repo.
**Yöntem:** Mevcut test korpusundan **bağımsız**. Her iddia kaynak kodun okunmasından
türetildi; var olan bir testin beklentisi kopyalanmadı.

---

## 0. Düzeltme turu — 29 Ağustos 2026

Denetimde bulunan kusurların tamamı, **ortam kaynaklı olanlar hariç**, düzeltildi.
Politika gereği slot JSON'una dokunulmadı (MOGEM-617 Faz 2: *"Bu fazın çıktısı
sabitlenmiş sayılardır… değiştirmek isteyen değişiklik talebi açar"*); politika
verisine dokunan iki madde `DEGISIKLIK-TALEBI-slot-politikasi.md` dosyasına
taşındı.

### Yöntem — regresyonu tahminle değil ölçümle ayırdım

İlk tam koşumda 12 repo modülü kırmızıydı. Değişikliklerimi
`git stash push -- tradehub_core/media/` ile kenara alıp **taban çizgisi**
aldım:

| | taban (değişikliklerim yok) | değişikliklerimle | sonuç |
|---|---|---|---|
| 10 modül | FAILED | FAILED | zaten kırıktı |
| `test_media_av` | **OK** | FAILED (20) | **benim regresyonum** |
| `test_media_path_safety` | **OK** | FAILED (1) | benim regresyonum |
| `test_media_seo_pipeline` | **OK** | FAILED (1) | benim regresyonum |

Üçü de düzeltildi. `test_media_av` regresyonu ciddiydi ve tasarımı değiştirtti
(aşağıda F-28).

### Geri alınan kendi hatam — F-28'in ilk hâli

F-28'i ilk çözüşümde `policy()["enabled"]` bayrağını daemon sağlığına bağladım.
Bu, clamd bir an düştüğünde `hold_until_clean`'i de kapatıyordu; yani o aralıkta
yüklenen dosyalar **taranmadan public ağaca çıkıyordu**. Düzeltme, düzelttiğinden
kötü bir fail-open açıyordu. Geri alındı ve yeniden tasarlandı:

- `policy()` **kuruluma** bakar (davranış değişmedi) → sessiz fail-open yok
- `scan_path` başarısızlıkta `_yedek_komut` ile `clamscan`'e düşer → asılı daemon
  taramayı durdurmaz
- `scanner_health()` yalnız **tanı** amaçlıdır, karar yolunda çağrılmaz

Ölçüldü: daemon SIGSTOP ile dondurulduğunda `clamdscan` hata **vermiyor**, donuyor
(`timeout` rc=124) — "hızlı hata verir" varsayımı yanlıştı.

### Düzeltilen bulgular

| # | Konu | Kök sebep |
|---|---|---|
| F-01…F-05 | probe kapısı | eklenmiş yük ölçülmüyor, `rfind`, MIME/uzantı düşüşü, `or` ile None karışması |
| F-06, F-07 | normalize | `min_long_edge` MP tavanını aşıyor; `resize:none` yanlış damga |
| F-08 | yol güvenliği | `commonpath` `ValueError` atıyor → 500; artık fail-closed |
| F-09 | politika kaydı | `get()` iç sözlüğü paylaşıyordu → çağıran mutasyonu |
| F-12 | parçalı yükleme | ilan edilen `content_sha256` hiç doğrulanmıyordu (ret kodu vardı, kullanılmıyordu) |
| F-18a/b | SEO denetimi | bozuk alan türü / okunamayan tarih denetimin TAMAMINI çökertiyordu |
| F-19 | SEO adları | genel adlar (`photo`, `resim`, tarih damgası) yakalanmıyordu |
| F-20 | SEO doğrulama | `//kotu.site/x` "site içi yol" sanılıp JSON-LD'ye çıkıyordu |
| F-21 | SEO paritesi | liste 7 bulgu, satıra tıklayınca 5 — iki ayrı uygulama; tekil artık topluya delege ediyor |
| F-22 | SEO sözleşmesi | boş kapsam farklı şekil dönüyordu (`total` yok) |
| F-25 | yedek künyesi | motor tabloları künyede hiç yoktu; artık **2150 taşınmayan kayıt** raporlanıyor |
| F-26 | çöp | bekletmedeki/karantinadaki dosyaya "diskte bulunamadı" deniyordu; karantina→çöp yolu kapatıldı |
| F-27 | türev üretimi | bekletme kalkınca kimse yeniden tetiklemiyordu → dosya sonsuza kadar türevsiz |
| F-28 | AV sağlığı | daemon ölüyken her tarama 120 sn zaman aşımına gidiyordu; artık `clamscan`'e düşüyor |
| F-29 | 3. katman dedup | `library.upload` sentinel'i `Link → Media Policy` alanına yazılıyor, `LinkValidationError` best-effort yutuluyordu → **tekilleştirme sessizce hiç çalışmıyordu** |
| F-13a | vendor senkronu | panel bayat hata kodları taşıyordu (`cover_video_ratio_not_allowed` → `cover_video_aspect_invalid`) |
| F-13b | istemci motoru | `video.validation_codes` tablosu okunmuyordu → aynı ihlal, farklı kod |
| F-30 (yeni) | `MESSAGE_KEYS` aynası | iki kuralda bayat → hem yanlış kod hem yanlış TR metin |
| F-14, F-15 | imza tanıma | istemci **eski** sniffer'ı aynalıyordu; motorla **128/424 sapma** ölçüldü → **0** |
| F-16 | ön kontrol şiddeti | `executable` içerik uyarıydı, sunucu ise reddediyor → artık engel |
| F-17 | kararsız test | sabit 40 ms uyku yerine koşula bekleme; 12/12 yeşil |
| F-24 | ölçü süzme | `Number(x) \|\| 0` `Infinity`'yi geçiriyordu → oran kuralı sessizce kayboluyordu |

### Denetimden SONRA bulunan iki kusur

| # | Konu | Kök sebep |
|---|---|---|
| F-31 | bekletme sızıntısı | `File` silinince `media_scan_hold` kopyası KALIYOR — hiçbir kanca temizlemiyordu |
| F-32 | kararsız test + kalıntı | `TestVideoDurumToplama` temizliği commit etmiyor → rollback geri alıyor; her koşum 2 kayıt bırakıyor. 82 kayda ulaşınca `page_size=20` hedefi sayfadan düşürüyor ve test rastgele kırılıyor |

**F-31'in görünmez zararı.** Adlandırma içerik-adresli
(`sha256[:32].uzantı`), yani aynı içerik ileride yeniden yüklenirse ADRESİ de
aynı olur. `seo_index.decide` bekletme/karantina kontrolünü DOSYA SİSTEMİNDEN
yapıyor (`av.in_hold(url)`). Sonuç: aylar önce silinmiş bir dosyanın artığı
yüzünden **yepyeni ve temiz bir dosya** `reason="quarantine"` alıp site
haritasından ve yapısal veriden düşüyor. `test_media_video_seo`'nun beş
başarısızlığı tam olarak buydu — testin kusuru değil, ürünün.

Ölçüm: `media_scan_hold` altında **468 sahipsiz dosya / 32,9 MB**; bekletmedeki
469 dosyadan yalnız 1'inin gerçek `File` kaydı var.

İki parça hâlinde çözüldü, çünkü kanca tek başına mevcut kurulumları düzeltmez:

- `av.cleanup_on_file_trash` → `File.on_trash` kancası: bundan sonraki birikimi
  önler. Karantina kopyasına DOKUNMAZ (bulgu kaydıdır, bekleme odası değil);
  yalnız denetime "sahipsiz kaldı" satırı yazar.
- `av.sweep_orphaned_holds(dry_run=True)` → mevcut yığın için süpürücü.
  **Sahipsiz** ölçütü dosyanın yaşı ya da tarama durumu değil, `File` kaydının
  yokluğudur — taraması süren gerçek dosyalar asla silinmez.

> Süpürücü **çalıştırılmadı**; silme kullanıcının kararı. Kuru koşum yukarıdaki
> sayıları veriyor.

### İkinci tur (29 Ağu, gece) — "ortam" hatalarına da dokunuldu

İlk turda ortam kaynaklı 9 hata kapsam dışı bırakılmıştı. İkinci turda ortam
kuruldu — ClamAV'da olduğu gibi, geçici ve container'a bağlı:

| Kurulan | Sürüm | Açtığı test yolu |
|---|---|---|
| ffmpeg / ffprobe | 5.1.9 | `test_media_watch` 8 hata → 0; `kd_04_video` 2 atlanan test gerçek yolda geçti |
| Medya kuyrukları | `common_site_config.workers` — `deploy/media-workers.compose.yml` sözleşmesiyle birebir + 5 worker | `test_media_migration_runtime` gerçek tatbikat testi geçti |
| pyvips / libvips | 3.2.0 / 8.14 | `pyproject` zorunlu beyan ediyordu; 20 MP üstü normalizasyon artık reddedilmiyor |
| tesseract | 5.3.0 | OCR yedeği |
| libvmaf | **yok** | Debian ffmpeg'i onunla derlenmemiş; özel derleme gerekir, kapsam dışı. Kalite kapısı "uygulanmadı" notuyla geçmeye devam ediyor |

Hiçbiri kalıcı değil: container yeniden oluşturulursa (22 Ağu'da olduğu gibi)
silinir. Kalıcı çözüm Dockerfile/compose.

**Worker'lar canlı olunca ortaya çıkan üçüncü kusur — F-33.** Kuyruk
worker'ları çalışmaya başlayınca testlerin `after_insert` ile kuyruğa attığı
türev işleri gerçekten işlendi ve test dosyası silindikten sonra **36 yetim
Media Asset** kaldı. Bu bir test artığı değil, ürünün davranışı:
`trash.purge_expired` File'ı kalıcı siliyor ama **hiçbir kod Media Asset /
Version / Rendition satırlarını ve türev dosyalarını silmiyordu.** Üretimde her
silinen ürün görseli 1 varlık + ~16 türev dosyası bırakır.

| # | Kusur | Düzeltme |
|---|---|---|
| F-33a | `_renditions_exist` çöpe taşınmış (`purged`) türevi "var" sayıyor → silinmiş görselin aynısı yeniden yüklenince **türev üretilmiyor** | `state != purged` süzgeci |
| F-33b | File silinince motor kayıtları kalıyor | `File.on_trash` → `pipeline_bridge.cleanup_on_file_trash`: türevler **çöp kapısından** (denetimli, legal hold'a saygılı, `purge_after`'a kadar geri alınabilir), varlık/sürüm/kasa/kullanım satırları kalıcı. Legal hold'daki varlığa dokunulmaz, denetime yazılır |
| F-33c | `Media Processing Job` asılı `asset` bağıyla kalıyor; `_open_job` işi `içerik_hash:slot` anahtarıyla yeniden kullandığı için aynı içeriğin yeni yüklemesi `LinkValidationError` ile düşüyor — canlı DB'de **44/185** iş satırı böyle | İş defteri kaskada eklendi; `_open_job` asılı bağı yeni varlığa çeviriyor (kanca yokken oluşmuş yığın için) |

F-33c'nin bulunma biçimi kayda değer: kendi test fixture'ım çakıştı (iki
farklı taban + sayaç aynı ölçüyü, dolayısıyla aynı içerik hash'ini üretti) ve
bu çakışma, üretimde "sil → aynı görseli yeniden yükle" ile oluşacak senaryoyu
kendiliğinden yarattı. Fixture düzeltildi (`w = taban + c`, `h = taban + 2c + 1`
— iki kenar farklı katsayıyla türetilince çakışma cebirsel olarak imkânsız).

Canlı ölçüm: 5 türev dosyası canlı diskten çöpe taşındı, varlık ve sürüm
silindi, `_renditions_exist` → `False`, legal hold'daki varlık 5 türeviyle
yerinde kaldı ve denetime `legal_hold_asset_orphaned_by_file_delete` yazıldı.

`sweep_orphaned_assets(dry_run=True)` mevcut yığın için yazıldı;
**çalıştırılmadı** (kuru koşum: 16 yetim, 0 hold).

**Canlı worker'ın testlere etkisi.** Worker canlıyken, kendi `_run_rendition_job`
çağrısını yapan bir test worker'la aynı varlığı üretmek için yarışıyor (ölçüldü:
tek başına geçen test modül içinde `IndexError`). KD-18 fixture'ları artık
insert'i `mock.patch("frappe.enqueue")` içinde yapıyor — testi süren iş test,
worker değil.

### Test hijyeni — ayrı bir kusur sınıfı

ClamAV kurulunca dört repo modülü kırıldı; sebep tarama kancasının dosyayı
public ağaçtan çekmesi. Testler tarayıcının **kurulu olmadığı** varsayımına
yaslanıyordu — üretimde bu varsayım zaten geçerli değil. `tests/av_notr.py`
ortak nötrleyicisi yazıldı ve dört modüle bağlandı.

Ayrıca içerik-adresli depolama yüzünden sabit ölçülü fixture'lar aynı `file_url`'e
düşüyor ve testler birbirinin dosyasını bekletmede/çöpte buluyordu; KD-18
fixture'ları koşuya özgü benzersiz içerik üretiyor ve motor kayıtlarını temizliyor.

### Ortam bulguları — düzeltilmedi (kapsam dışı)

| Konu | Kanıt | Gereken |
|---|---|---|
| ffmpeg kurulu değil | `test_media_watch` → 8× `FileNotFoundError: 'ffmpeg'` | Dockerfile/compose'a eklemek |
| ~~Medya kuyrukları tanımsız~~ (29 Ağu gece elle kuruldu, kalıcı değil) | `get_queue_list() = ['short','default','long']`; `enqueue(queue="media-image-live")` → `ValidationError` | `common_site_config.json` → `workers` + o kuyruklar için worker |
| ClamAV/ffmpeg kalıcı değil | container 2026-08-22'de yeniden oluşturulmuş, elle kurulanlar silinmiş | Dockerfile/compose'a taşımak |

`test_media_migration_runtime`'daki `queue_unreachable` hatası birinci satırın
sonucudur; kod kusuru değildir.

---

## 1. Özet

| | |
|---|---|
| Yeni test | **723** (608 backend · 74 admin-panel · 41 tradehubfront) |
| Yeni test dosyası | 21 |
| Kaynak dosyada değişiklik | denetimde **0**; düzeltme turunda **13 kaynak dosya** (bkz. §0) |
| Okunan üretim kodu | ~14.000 satır (69k satırlık medya paketinin karar/güvenlik çekirdeği) |
| Bulgu | **23 kod bulgusu + 5 ortam bulgusu + 4 süreç bulgusu** |
| Suite durumu | KD paketinin tamamı **yeşil**; bulgular "bugünkü davranış" olarak sabitlendi |

Bulgular testlerde **kırmızı bırakılmadı**: her biri bugünkü (kusurlu) davranışı
doğrulayan bir testle sabitlendi ve docstring'inde *"düzeltilince bu test kırmızıya
döner, beklentiyi şu şekilde güncelle"* yazıyor. Böylece paket bugün yeşil koşuyor
ama bir düzeltme yapıldığında sessiz kalmıyor.

---

## 2. Test paketleri

### Backend — `tradehub_core/tradehub_core/tests/kapsamli/`

| Modül | Test | Kapsam |
|---|---:|---|
| `test_kd_01_probe_kapi` | 91 | Künye çıkarımı, kabul kapısı, bomba/polyglot/kesiklik |
| `test_kd_02_normalize` | 59 | DPI kuralı, EXIF yönü, GPS silme, alfa, upscale yasağı |
| `test_kd_04_video` | 80 | Karar tablosu, bitrate bütçesi, fayda/kalite/teslim kapıları |
| `test_kd_05_depolama` | 36 | İçerik-adresleme, kapsam izolasyonu, yol kaçışı, imzalı URL |
| `test_kd_06_politika` | 50 | PolicyEngine + 9 slot politikasının iç tutarlılığı |
| `test_kd_07_guvenlik` | 53 | SVG/XSS, XXE, zip bomba, traversal, izolasyon profilleri |
| `test_kd_09_api_sozlesme` | 47 | Yanıt zarfı, parçalı yükleme, idempotency, çapraz kiracı |
| `test_kd_10_seo` | 57 | Denetim kuralları, 8 boyutlu skor, alan doğrulama |
| `test_kd_12_maymun_fuzz` | 24 | Maymun + mutasyon + kesme/ekleme (test başına 150 tur) |
| `test_kd_13_smoke_e2e` | 16 | 50 modül import duman testi, E2E zincir, performans bütçesi |
| `test_kd_14_sahte_veri` | 33 | **120 kayıtlık sahte katalog**: toplu denetim, sayfalama, N+1, korpus maymunu |
| `test_kd_15_kombinatoryal` | 11 | **207.360 kombinasyonluk tam çarpım** + 69.120 monotonluk kontrolü, örnekleme yok |
| `test_kd_16_coklu_hesap` | 15 | **9 (aktör,sahip) çifti × 36 yetki hücresi** + 4!·5!·3! sıra permütasyonu |
| `test_kd_17_zaman_ekseni` | 19 | **Geçmiş/gelecek tam çarpımı**: hak bitişi 24, TTL×an 63, saat kayması 20 hücre |
| `test_kd_18_carpisma` | 17 | **Alt sistem çarpışmaları** — gerçek dosyayla çalıştırılarak doğrulandı |

Koşum:
```bash
export DOCKER_HOST=unix:///var/run/docker.sock
docker exec istoc-backend bench --site tradehub.localhost run-tests \
  --module tradehub_core.tests.kapsamli.test_kd_01_probe_kapi
```

### Frontend

| Dosya | Test | Kapsam |
|---|---:|---|
| `admin-panel/.../kd_f01_bytes.test.js` | 24 | İstemci bayt sezgisi ↔ sunucu paritesi |
| `admin-panel/.../kd_f02_policy_parity.test.js` | 34 | Politika ikizinin kod paritesi, vendor tazeliği, preflight |
| `tradehubfront/.../kd_f03_teslim.test.ts` | 28 | Manifest → `<picture>`, sizes, LCP/CLS kuralları, XSS kaçışı |
| `tradehubfront/.../kd_f04_maymun.test.ts` | 13 | **DOM maymunu**: 400 tur × rastgele manifest, gerçek ayrıştırıcıyla enjeksiyon denetimi |
| `admin-panel/.../kd_f05_maymun.test.js` | 16 | **Panel maymunu**: 500 tur × rastgele künye/ölçüm, değişmez denetimi |

Koşum: `npm test` (admin-panel) · `npm run test:unit` (tradehubfront)

---

## 3. Kod bulguları

### 3.1 Güvenlik — kapı kaçışları

**F-01 · Eklenmiş yük taraması yalnız son 64 KB'a bakıyor** — *orta*
`image/probe.probe_header` bayt yolunda `tail = content[-TAIL_BYTES:]` (64 KB) diyor ve
eklenmiş-yük taramasını bu pencerede yapıyor. JPEG dalı `tail.rfind(FFD9)` ile EOI
arıyor; EOI pencerenin dışına çıkarsa fonksiyon `False` döner.
**Sonuç:** `JPEG + 64 KB dolgu + <script>` kapıdan `appended_payload=False` ile geçiyor.
Aynı saldırı 64 KB altında kalırsa doğru şekilde reddediliyor (kontrast testi mevcut).
→ `test_gv_BULGU_64kb_ustu_dolgu_ile_kacis`

**F-02 · İkinci EOI ile kaçış** — *orta*
`core/probe._has_appended_payload` JPEG dalında `rfind` (son EOI) kullanıyor.
`...EOI <script> EOI` yazan bir dosyada kuyruk boş kalıyor ve tespit kaçıyor.
→ `test_gv_BULGU_ikinci_eoi_ile_kacis`

> **Not:** F-01 ve F-02 tek başına dosyayı yayına sokmuyor — `upload_policy`,
> normalize'ın yeniden kodlaması ve File `before_insert` kancası ayrı katmanlar.
> Ama kapının kendi sözleşmesi ("sonuna eklenmiş çalıştırılabilir içeriği yakalarım")
> bu iki durumda tutmuyor.

**F-20 · Protokolsüz URL "site içi yol" sanılıyor** — *orta*
`media/seo._validate_asset_values` `value.startswith("/")` ile site içi yolu kabul
ediyor; `//kotu.site/lisans.pdf` de `/` ile başladığı için aynı dala düşüyor ve
doğrulamadan geçiyor. Bu değer `license_url` / `acquire_license_url` / `canonical`
alanlarına yazılıyor ve **JSON-LD ile yayına çıkıyor**. Tarayıcı protokolsüz adresi
sayfanın protokolüyle dış alan adına çözer.
→ `test_gv_BULGU_protokolsuz_url_ic_yol_sanilip_kabul_ediliyor`

### 3.2 Dayanıklılık — çöken kod yolları

**F-18a · SEO denetimi sayı tipindeki `alt` ile çöküyor** — *orta*
`seo_audit.audit_fields` "DB'ye dokunmaz, saf fonksiyon" diye belgelenmiş ama girdi
türünü doğrulamıyor: `(alanlar.get("alt") or "").strip()` `alt` bir `int` ise
`AttributeError` atıyor.
**F-18b ·** Aynı fonksiyon geçersiz `rights_expires_on` değerinde `ValidationError`
atıyor. Yazma ucu tarihi doğruluyor ama alan başka bir yoldan (migration, doğrudan
SQL, eski kayıt) bozuk kalmışsa okuma tarafı korumasız.
**Sonuç:** tek bozuk satır, toplu denetim ekranının tamamını düşürebilir. Denetim bir
*raporlama* işidir; bozuk veriyi bulgu olarak bildirmeli, istisna atmamalı.
→ `test_gv_BULGU_alt_metin_disi_bir_tur_ise_DENETIM_COKUYOR`, `test_gv_BULGU_gecersiz_tarih_DENETIMI_COKURUYOR`

**F-08 · `check_path_safety` görece yolda `ValueError` atıyor** — *düşük*
`os.path.commonpath` mutlak ve görece yolu birlikte kabul etmiyor; fonksiyon bunu
yakalamadığı için "güvenli değil" yerine istisna yükseliyor. Çağıran `except`
koymamışsa istek 500 döner.
→ `test_sn_gorece_yol_ile_karsilastirma_patlar`

### 3.3 Politika tutarsızlıkları

**F-06 · `min_long_edge`, `max_megapixels` tavanını deliyor — CANLI KONFİGDE** — *yüksek*
`normalize.target_size` önce MP tavanına göre küçültüyor, sonra
`olcek = max(olcek, min_long_edge / uzun)` ile ölçeği geri yükseltiyor ve **MP tavanını
yeniden kontrol etmiyor**. İki canlı slot bu çelişkiyi taşıyor:

| Slot | İzinli oran | Üretilen | MP tavanı |
|---|---|---|---|
| `category-banner` | 5:4 | 1920×1536 = **2,95 MP** | 2,00 MP |
| `company-cover-image` | 2:1 | 1920×960 = **1,84 MP** | 1,64 MP |

`company-cover-image` için izinli **en dar** oran bile tavanı aşıyor; yani o slotta
MP tavanı fiilen uygulanamıyor.
→ `test_gv_BULGU_master_megapiksel_tavani_min_kenarla_celisiyor`

**F-11 · 4 slotta `require` bloğu ENGELLEMİYOR** — *yüksek*
`on_violation.require = "warn"` olan slotlar: `category-banner`,
`company-cover-image`, `document-attachment`, `product-video`. Bu blok geometri, oran,
adet **ve video süresi** kurallarını taşıyor.
**Somut sonuç:** `product-video` standardı 33 sn diyor; 40 sn'lik video politikadan
`allow=True` ile **geçiyor**. Aynı kural `company-cover-video` slotunda `reject`
olduğu için orada engelliyor. Bu asimetri kasıtlıysa belgelenmeli; değilse üretimde
33 sn tavanı yok demektir.
→ `test_bi_BULGU_product_video_sure_asimi_yalniz_UYARI`, `test_bi_on_violation_haritasi_sabitleniyor`

**F-10 · `data:` URI yalnız 2 slotta yasak** — *düşük*
Kural `accept.get("allow_data_uri") is False` diye yazılmış; anahtar 9 slotun 7'sinde
hiç yok, dolayısıyla kural tetiklenmiyor. (Kabul kapısı `data_uri`'yi ayrıca
reddediyor — savunma tek katmanda değil, ama politika sözleşmesi eksik.)

**F-05 · `max_bytes: 0` ile sınır kapatılamıyor** — *düşük*
`GuardConfig.from_accept` `accept.get("max_bytes") or cls.max_bytes` yazıyor; `0`
falsy olduğu için sınır kapanmak yerine 25 MiB varsayılanına düşüyor.

**F-09 · `PolicyRegistry.get()` paylaşılan sözlük döndürüyor** — *düşük*
Bir çağıranın politika sözlüğünde yaptığı değişiklik süreç boyunca kalıcı oluyor.

### 3.4 Toplu yollar (ölçekli sahte korpusla bulundu)

**F-21 · Toplu ve tekil denetim aynı dosya için FARKLI bulgu üretiyor** — *orta*
Aynı dosya, aynı `deep` bayrağı, iki giriş noktası:

```
audit_file(u, deep=False)  → missing_alt, missing_caption, missing_dimensions,
                             missing_license, missing_title
audit_batch([u])           → + missing_association, missing_structured_data
```

`audit_batch` iki kuralı üretiyor, `audit_file` hiç üretmiyor. Panelde liste
görünümü toplu yolu, satır içi "yeniden denetle" tekil yolu kullanıyorsa operatör
satıra tıkladığında **iki bulgunun kaybolduğunu ve skorun değiştiğini** görür.
(`orphan_asset` farkı ayrı ve tutarlı: o gerçekten `deep=True` ile geliyor.)
→ `test_gv_BULGU_toplu_ve_tekil_denetim_AYRISIYOR`, `test_gv_BULGU_skor_da_iki_yolda_farkli_cikiyor`

**F-22 · Boş kapsamda yanıt şekli değişiyor** — *düşük*
Dolu kapsam `{files, summary, score, total}`, boş kapsam `{files, summary, score}`
döndürüyor — `total` anahtarı hiç yok. `paginate` bunu tolere ediyor ama sözleşmeyi
okuyan başka bir çağıran `KeyError` alır.
→ `test_gv_BULGU_bos_kapsam_FARKLI_bicimde_donuyor`

### 3.5 Sözleşme boşlukları

**F-12 · `content_sha256` alınıyor, saklanıyor, geri veriliyor — ama doğrulanmıyor** — *orta*
`chunked.begin` bir bütünlük sözleşmesi ilan ediyor; `chunked.finish` birleşen içeriği
ilan edilen hash ile **karşılaştırmıyor**. Tamamen farklı bir içerik yollanabilir ve
hiçbir uyarı üretilmez. (Güvenlik açığı değil — sunucu `Media Asset.content_sha256`'yı
kendi hesaplıyor — ama API'nin ilan ettiği sözleşme boşta duruyor.)
→ `test_bi_BULGU_ilan_edilen_sha256_finish_te_DOGRULANMIYOR`

**F-04 · `probe_video_from_ffprobe` her videoyu mp4 künyeliyor** — *düşük*
`detected` ve `mime` sabit `"mp4"` / `"video/mp4"`. WebM kaynakta uzantı `.webm`
kalıyor ama `extension_matches_content` sabit `True` yazıldığı için çelişki görünmüyor.

**F-03 · `.jpg` MIME yedeği çalışmıyor** — *düşük*
`probe_bytes` MIME yedeğini `MIME_BY_KIND[extension.lstrip(".")]` ile arıyor; tabloda
`"jpeg"` var, `"jpg"` yok. İçerik tanınmayan bir `.jpg` MIME'sız kalırken aynı dosya
`.jpeg` adıyla `image/jpeg` alıyor.

**F-07 · JPEG küçültmede not ile bayrak çelişiyor** — *düşük*
Decoder draft hedefi zaten ürettiği için kod `resize:none` notunu düşüyor ama
`resized=True`. Telemetri bu notu sayarsa "hiç küçültme yapılmadı" der.

**F-24 · Sonsuz ölçü süzülmüyor, oran kuralını sessizce devre dışı bırakıyor** — *düşük*
Panelin `normalizeMeasure` fonksiyonunda `Infinity > 0` doğru olduğu için künye
"ölçüldü" sayılıyor: `Infinity × Infinity` → `aspectRatio = NaN` (oran
karşılaştırmalarının hepsi yanlış döner, **oran kuralı hiç çalışmaz**),
`100 × Infinity` → `aspectRatio = 0`. Megapiksel kuralı emniyetli tarafa düşüyor.
`NaN` doğru şekilde "ölçülmedi"ye çevriliyor. Bugün ulaşılabilir değil
(`readDimensions` yalnız tam sayı üretiyor) — sertleştirme boşluğu.
→ `BULGU F-24 · sonsuz ölçü süzülmüyor…`

**F-19 · Kötü dosya adı deseni jenerik adları kaçırıyor** — *düşük*
`_BAD_NAME` yalnız `img_N | ekran görüntüsü | whatsapp | dsc_N | untitled | adsız`
kapsıyor. Sahada çok yaygın `photo.jpg`, `image.png`, `20260101_120000.jpg`, `1.jpg`
uyarı üretmiyor.

---

## 3.6 Kombinatoryal kapsam — sayılar

Örneklemeyi bırakıp uzayın tamamının tarandığı yerler:

| Ne | Uzay | Yöntem |
|---|---:|---|
| Politika kararı (slot × rol × geometri × bayt × animasyon × okunabilirlik × uzantı × 3 güvenlik ekseni) | **207.360** | tam kartezyen çarpım |
| Güvenlik monotonluğu (bayrak eklemek kararı iyileştiremez) | **69.120** | 17.280 taban × 4 değerlendirme |
| `target_size` geometrisi (12 kaynak × 6 tavan × 5 MP × 4 alt sınır) | **1.440** | tam çarpım |
| Çapraz kiracı yetki matrisi (3 hesap × 3 sahip × 4 işlem) | **36** | tam çarpım, köşegen ayrı |
| Parça sırası | **4! = 24** | tam permütasyon (+24 tekrarlı, +24 eksik) |
| Varlık işlem sırası | **5! = 120** | tam permütasyon |
| Aynı alana yazma sırası | **3! = 6** | tam permütasyon |
| Yabancı hesap × ret sırası | **2 × 3! = 12** | tam permütasyon |
| Hak bitişi (6 tarih × 2 alt × 2 tür) | **24** | tam çarpım |
| İmzalı URL (9 TTL × 7 doğrulama anı) | **63** | tam çarpım |
| Saat kayması (5 kayma × 4 TTL) | **20** | tam çarpım |
| DOM maymunu / panel maymunu | **400 + 500 tur** | deterministik rastgele |
| Fuzz (maymun · mutasyon · kesme · ekleme) | **~3.600 vaka** | deterministik rastgele |

Toplam: **278 binden fazla değerlendirme**, 706 test içinde.

Ölçülen şey doğru cevap değil, uzayın tamamında geçerli olması gereken
**değişmezler**: hiçbir kombinasyon istisna atmaz · ret kararında hedef
üretilmez · her ihlal kod + çözülmüş mesaj taşır · güvenlik bayrağı eklemek
kararı asla iyileştiremez · aynı girdi aynı kararı verir · köşegen dışı hiçbir
yetki hücresi açık değil · her parça sırası aynı dosyayı üretir · süresi geçmiş
imza hiçbir saat kaymasında kabul edilmez.

## 3.7 Alt sistem ilişkileri — aynı dosyaya kaç yerden dokunuluyor

Bir medya dosyasını fiziksel olarak taşıyan/silen **26 modül** var. Sorulan soru
"her biri tek başına doğru mu" değil, "ikisi aynı dosyaya dokunduğunda ne oluyor".
Her sonuç önce kod okunarak, sonra **gerçek dosyayla çalıştırılarak** doğrulandı.

> **Grep yeterli değil.** `shutil.move|os.replace` taraması `archive.py`'yi
> "taşıyıcı" gösterdi; okununca öyle olmadığı görüldü — o modül canlı dosyayı
> taşımıyor, optimizasyon öncesi orijinalin kopyasını saklıyor ve üzerine
> yazmayı bilerek reddediyor. Grep'ten çıkarılan sonuç yanlıştı.

**F-25 · Motor tabloları yedek kapsamında değil — bayrak AÇIKKEN** — *yüksek*
`schema.FULL_TABLES` yalnız `("tabFile", "tabAuthorization Decision Log")`.
`Media Asset`, `Media Rendition`, `Media Version`, `Media Usage` **hiçbir yedek
modülünde geçmiyor** (backup.py · schema.py · backup_export.py · seller_backup.py
tarandı, sıfır eşleşme). Bu arada `media_pipeline_enabled = 1`, rollout **%100**
ve canlı veritabanında **133 Media Asset · 1814 Rendition · 112 Version** birikmiş.
Geri yükleme File satırlarını getirir, motorun hâlini getirmez.
Proje memory'si bunu "bayrak açılmadan önce şart" diye kaydetmiş (madde 11);
aynı maddenin A parçası (7 AV/transcode damgası) çözülmüş, B parçası çözülmemiş.
→ `test_gv_BULGU_MOTOR_TABLOLARI_yedek_kapsaminda_DEGIL`

**F-27 · Bekletme kalkınca türev üretimi yeniden tetiklenmiyor** — *orta*
Zincir, çalıştırılarak izlendi:
1. `after_insert` → `av.maybe_scan_on_insert` **senkron** `hold()` çağırıyor;
   dosya `public/files/`'dan çıkıyor (`is_private` DEĞİŞMİYOR — `file_url`
   sözleşmesi korunuyor).
2. Aynı istekte `maybe_generate_renditions` türev işini `media-image-live`
   kuyruğuna atıyor.
3. Tarama işi **ayrı** kuyrukta (`default`); bitince `release_hold` dosyayı
   geri koyuyor.
4. İki kuyruk birbirini beklemiyor. Türev işçisi önce koşarsa dosyayı bulamıyor,
   **sessizce hiçbir şey üretmiyor** — ölçüldü: hata yok, sahte türev yok, hold
   bozulmuyor. Ve `release_hold` yeniden tetikleme YAPMIYOR.

Kancaların sırası doğru ve niyeti `hooks.py`'de açıkça yazılı ("tarama yeni
hattan ÖNCE koşmalı ki bir türev işi taranmamış dosyayı işlemeye başlamasın").
Niyet tutuyor; tutmasının bıraktığı boşluk ele alınmamış. Tek kurtarıcı manuel
`enqueue_catalog_backfill`. Bugün görünmüyor çünkü ClamAV kurulu değil —
kurulduğu anda yüzeye çıkar.
→ `test_gv_BULGU_release_hold_TUREV_URETIMINI_yeniden_tetiklemiyor`

**F-26 · Bekletmedeki dosyada çöp mesajı yanlış** — *düşük*
`move_to_trash` → `_assert_trashable` private/doctype/hassas-ikiz/kullanım
kontrollerini yapıyor ama AV bekletmesini bilmiyor; akış `_live_path`e ulaşıp
**"Dosya diskte bulunamadı"** atıyor. Durum bozulmuyor (hold duruyor, çöpe
girmiyor) — kusur teşhiste: operatör dosyayı kayıp sanır. Aynı kusur sınıfı
`seller_backup.py`'de zaten düzeltilmiş (`_yokluk_sebebi()` → scan_hold /
quarantine / missing); `trash.py` o düzeltmeyi almamış.
Ters yön temiz: çöpteki dosya bekletmeye alınamıyor, `hold()` sessizce `False`
dönüyor, geri yükleme çalışıyor.
→ `test_gv_BULGU_bekletmedeki_dosya_cope_atilamiyor_ama_MESAJ_YANLIS`

### Taşıyıcı × koruma matrisi (kod okunarak çıkarıldı)

| Modül | AV karantina | AV bekletme | çöp | legal_hold |
|---|---|---|---|---|
| `av.py` | ✅ | ✅ | ✅ | — |
| `trash.py` | ❌ | ❌ | ✅ | ✅ |
| `access_level.py` | ✅ | ✅ | ✅ | — |
| `seller_backup.py` | ✅ | ✅ | ✅ | — |
| `retro_rename.py` | ✅ | ✅ | — | — |
| `transcode.py` | ✅ | ✅ | — | — |
| `pipeline_bridge.py` (motor) | ❌ | ❌ | ✅ | — |
| `backup.py` | ❌ | ❌ | ✅ | — |
| `archive.py` | — | — | — | — | *(taşıyıcı değil)* |

## 4. Çapraz repo bulguları (istemci ↔ sunucu ayrışması)

Panel, sunucudaki `PolicyEngine`in TS ikizini çalıştırıp kullanıcıya yükleme
yapılmadan önce ret/uyarı gösteriyor. Ayrışan her nokta, **kullanıcının gördüğü sonuç
ile yüklemenin gerçek sonucunun farklı olması** demek.

**F-13a · Vendor politika kopyası bayat** — *yüksek*
`admin-panel` içindeki vendor kopyası `engine.py`nin 23 Ağustos hâlinden türetilmiş;
kaynak 26 Ağustos'ta değişmiş. `npm run sync:policy:check` kırmızı, **reponun kendi
parite testi de kırmızı** (`policyEngineParity.test.js`). Yani kapı var ve çalışıyor,
ama suite kırmızı bırakılmış.

**F-13b · İstemci `video.validation_codes` tablosunu okumuyor** — *yüksek*
Sunucu `PolicyEngine._code()` önce slot politikasının `video.validation_codes`
tablosuna bakıyor; istemcinin `code()` metodu doğrudan `${prefix}_${rule}` üretiyor.
`company.cover_video` slotunda 3 hata kodu ayrışıyor:

| İhlal | İstemcinin ürettiği | Sunucunun ürettiği |
|---|---|---|
| oran | `cover_video_ratio_not_allowed` | `cover_video_aspect_invalid` |
| süre | `cover_video_duration_too_long` | `cover_video_too_long` |
| çözünürlük | `cover_video_short_edge_too_small` | `cover_video_resolution_too_low` |

Toplam 19 parite vektörü etkileniyor. Mesaj kataloğu koda göre seçiliyorsa kullanıcı
kapak videosu reddinde "bilinmeyen hata" görür.

**F-16 · Uzantı/içerik uyuşmazlığı: istemcide UYARI, sunucuda RET** — *orta*
İstemci kodu bunu bilinçli olarak `warn` bırakıyor ve gerekçesinde *"sunucu da
reddetmiyor (`upload_policy.check`)"* diyor. Ama slot yolundaki
`PolicyEngine._check_accept` ve kabul kapısı `image/probe._guard` **reddediyor**.
Kullanıcı panelde uyarı görüp yüklüyor, sunucu reddediyor.

**F-14 · Tür sezgisi sıralaması ayrışıyor** — *düşük*
Sunucu `content[4:8] == "ftyp"` kontrolünü imza tablosundan **önce**, istemci
**sonra** yapıyor. `BM` + `ftyp` ile başlayan dosya sunucuda `mp4`, istemcide `bmp`.

**F-15 · İstemci çalıştırılabilir/`data:` içeriği tanımıyor** — *düşük*
Sunucu `MZ`/`ELF`/`data:` için `executable`/`data_uri` diyor ve kapıda reddediyor;
istemci "bilinmiyor" diyor.

**F-17 · Kırılgan test kapısı** — *orta*
`admin-panel/.../mediaRetroRename.test.js` tek başına koşunca **geçiyor**, tam suite
içinde **düşüyor** (3 koşumda 3/3 tekrarlandı). Zamanlama/eşzamanlılık bağımlı.
Kırılgan kapılar ya CI'ı rastgele bloklar ya da görmezden gelinmeye başlanır.

---

## 5. Ortam bulguları (dev container)

> **GÜNCELLEME (29 Ağu):** ClamAV kuruldu ve doğrulandı; aşağıdaki tablo o satır
> dışında geçerli. Kurulum **kalıcı değil** — container yeniden oluşturulursa
> silinir (§0 "Ortam bulguları").

`istoc-backend` container'ında bench sanal ortamı:

| Bağımlılık | Durum | Etkisi |
|---|---|---|
| Pillow 12.2.0 | ✅ | — |
| boto3 | ✅ | — |
| **pyvips / libvips** | ❌ YOK | `pyproject.toml` **zorunlu** beyan ediyor. 20 MP üstü her non-JPEG normalizasyonu `bounded_decoder_unavailable` ile **reddediliyor** |
| **ffmpeg / ffprobe** | ❌ YOK | Video hattı bu ortamda hiç koşmuyor |
| **libvmaf** | ❌ YOK | Kalite kapısı "uygulanmadı" notuyla geçiyor |
| **clamscan / clamdscan** | ✅ KURULDU (28 Ağu, ClamAV 1.4.3 + imzalar) | AV taraması artık gerçek koşuyor; F-26/F-27/F-28 bu sayede ölçülebildi |
| **tesseract** | ❌ YOK | OCR / `overlay_text` yedeği |

**Bu neden önemli:** mevcut yeşil testlerin bir kısmı gerçek yolu değil **fallback
yolunu** doğruluyor olabilir. KD paketinde bu ayrım açık: dış araç gerektiren her test
`skipTest` ile durumu rapora yazıyor, sessizce geçmiş görünmüyor
(`test_orm_*` testleri).

---

## 6. Süreç bulguları

1. **9 slot politikasının tamamı hâlâ `status: draft`.** MOGEM-617 Faz 2 çıkış kapısı
   "tüm slot standartları sabit + SRS v1.0" diyor ve *"faz çıkış kriteri karşılanmadan
   sonraki faz başlamaz"*. Faz 6+ kodu yazılmış durumda.
2. **MOGEM-617'nin Plane'de 0 alt görevi var** — başlıkta "102 görev" yazıyor, hepsi
   açıklamanın içinde. İlerleme iş kalemi düzeyinde izlenemiyor.
3. **MOGEM-620'nin (SEO) 0 alt görevi var** — 18 başlıklı gereksinim tek kalemde.
4. ~~**admin-panel test suite'i şu an kırmızı**~~ → **ÇÖZÜLDÜ (29 Ağu).** F-13a
   parite kapısı senkronlandı, F-17 kırılganlığı giderildi; suite 1468 testte
   0 düşen. Bir kapının kırmızı kalması, kapıyı zamanla anlamsızlaştırır —
   bulgunun kaydı bu yüzden duruyor.

---

## 7. Doğrulanan davranışlar (kusur bulunmayanlar)

Denetimin bulduğu kadar bulmadığı da bilgi. Aşağıdakiler saldırgan girdiyle
sınandı ve **doğru** davrandı:

- **SVG sanitizasyonu** — script/olay işleyici/`foreignObject`/`style`/harici `href`
  siliniyor; DTD/ENTITY ham baytta, ayrıştırıcıya ulaşmadan reddediliyor
  (billion-laughs bellek tüketmeden düşüyor); temizlik sonrası çizim kalmazsa dosya
  kabul edilmiyor. 300 rastgele düşman kurguda **kabul edilen hiçbir çıktı** zararlı
  iz taşımadı.
- **Piksel bombası** — 900 MP beyan eden PNG hem "Pillow açmayı reddediyor" hem
  "Pillow hiç tanımıyor" dallarında **fail-closed** reddediliyor.
- **GPS silme (INV-04)** — `strip_metadata` tamamen kapatılsa bile GPS IFD'si ve üst
  seviye işaretçi etiketi çıktıdan siliniyor.
- **Upscale yasağı (FR-028)** — 150 fuzz girdisinin hiçbiri büyütme ürettiremedi.
- **DPI kuralı** — 300 DPI mockup'ta DPI 72'ye yazılıyor, **piksel ölçüsü değişmiyor**;
  WebP DPI taşıyamadığında sonuç uydurulmuyor, `dpi_written=False` + not düşülüyor.
- **Fayda kapısı (INV-05)** — çıktı kaynaktan büyükse atılıyor ve **diskte kalmıyor**;
  VMAF ölçülemiyorsa sayı uydurulmuyor.
- **Çapraz kiracı izolasyonu** — parçalı yüklemede başka mağaza parça ekleyemiyor,
  birleştiremiyor, meta okuyamıyor, oturum silemiyor; idempotency sonucu kiracıya göre
  ayrışıyor.
- **Depolama** — private dosya public kapsamda görünmüyor; imzalayıcı yokken private
  URL **sessizce imzasız dönmüyor**, hata atıyor; `../`, null bayt ve sembolik bağ
  adaptör seviyesinde reddediliyor; başarısız yazımdan sonra yarım dosya kalmıyor.
- **Hata zarfı** — bilinmeyen istisnada iç yol/e-posta gövdeye sızmıyor; `call()`
  medya dışı istisnayı yutmuyor.
- **Teslim katmanı (vitrin)** — manifest bozuk/eksik geldiğinde sayfa bozulmuyor,
  birebir yedeğe düşüyor; ölçü yoksa üretim duruyor (CLS); `alt`/`src`/`srcset`/`sizes`
  kaçışlanıyor; ızgara kartlarına toplu `fetchpriority="high"` verilmiyor.
- **50 medya modülünün tamamı import edilebiliyor** (2026-08-20 alpha 417 arızasının
  duman testi).
- **Performans bütçeleri** — kapı kararı <50 ms, politika kararı <5 ms, SVG sanitize
  <10 ms.
- **Var olmayan adres** — toplu denetim uydurma "her şey eksik" satırı üretmiyor; tek ve
  açık bir `missing_file` bulgusu veriyor ve kapsam özet sayaçlarını şişirmiyor.
- **Sayfalama** — 120 kayıtlık korpusta sayfalar birleşince tam korpus çıkıyor, tekrar
  yok; özet ve skor sayfaya göre değişmiyor; süzgeç ve arama sunucuda uygulanıyor;
  `%` ve `_` SQL jokeri olarak yorumlanmıyor.
- **Ölçeklenme** — 20 → 120 dosyada süre doğrusal (N+1 yok); 120 dosya <11 sn.
- **SQL enjeksiyonu** — alan değeri olarak yazılan `'; DROP TABLE …` katalogu bozmuyor.
- **DOM maymunu (vitrin)** — 400 tur × rastgele/düşman manifestte üretilen işaretleme
  her zaman ayrıştırılabilir, tek kök taşıyor; hiçbir turda `on*` özniteliği,
  `<script>` düğümü ya da `javascript:` şeması oluşmadı.
- **Panel maymunu** — 500 tur × rastgele künyede istisna yok; ret kararında hedef
  üretilmedi, her ihlal kod + çözülmüş mesaj taşıdı, güvenlik bayrağı açık hiçbir
  künye kabul edilmedi.

---

## 8. Önerilen sıra

| Öncelik | Bulgu | Gerekçe |
|---|---|---|
| 1 | F-13a / F-13b | Kullanıcıya yanlış hata gösteriyor; kapı zaten kırmızı, sadece senkron gerekiyor |
| 2 | F-11 | `product.video` 33 sn tavanı fiilen yok |
| 3 | F-06 | İki slotta MP tavanı uygulanamıyor (canlı konfig) |
| 4 | F-18a / F-18b | Tek bozuk satır SEO denetim ekranını düşürüyor |
| 4b | F-21 | Operatör satıra tıklayınca iki bulgu ve skor değişiyor |
| 5 | F-01 / F-02 | Kapının kendi sözleşmesi tutmuyor |
| 6 | F-20 | JSON-LD'ye dış alan adı yazılabiliyor |
| 7 | F-16 | Panel "uyarı" diyor, sunucu reddediyor |
| 1b | F-25 | Bayrak %100 açık, motorun 2000+ kaydı yedeksiz |
| 5b | F-27 | ClamAV kurulduğu anda türevler sessizce üretilmemeye başlar |
| 8 | ORTAM-1 | pyvips zorunlu beyan edilmiş ama kurulu değil |
| 9 | F-17 | Kırılgan kapı |
| 10 | Kalanlar | F-03/04/05/07/08/09/10/12/19/22/24 |

---

## 9. Notlar

- Kaynak kodda **hiçbir değişiklik yapılmadı**. `git status` üç repoda da yalnız yeni
  test dosyaları gösteriyor.
- Kombinatoryal testler **örneklemiyor**: `test_kd_15` uzayın tamamını (207.360)
  tarıyor ve eksen sayısı küçülürse `test_bi_uzay_boyutu_beklendigi_gibi` kırılıyor —
  kapsamın sessizce daralması engellendi.
- Fuzz ve maymun testleri **deterministik**: tohum sabit (`20260828`, backend'de
  `KD_FUZZ_TOHUM` / `KD_FUZZ_TUR` ile değiştirilebilir). Frontend maymunları kendi
  mulberry32 üreteçlerini aynı tohumla kuruyor.
- KD-14 korpusu `setUpClass` içinde **commit** ediliyor: `FrappeTestCase` her testi
  geri sardığı için commit'siz korpus ilk testten sonra kayboluyor (ilk kurguda tam
  olarak bu oldu — 219 sahte düşüş). Korpus sınıf sonunda siliniyor.
- Denetim sırasında `npm run sync:policy` bir kez koşturuldu (ayrışmanın içeriğini
  görmek için); üretilen dosyalar `git checkout` ile **geri alındı**.
