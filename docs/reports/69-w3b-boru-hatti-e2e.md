# 69 — W3B: Medya boru hattı DEV'de uçtan uca İLK GERÇEK koşu (E2E ölçüm)

**Tarih:** 2026-08-20 · **Ortam:** DEV (`istoc.localhost`, `istoc-dev` compose, 14 konteyner)
**Görev:** Faz 6-7'nin "kod var, veri akmıyor" durumunu veri tarafında ilk kez gerçek kılmak:
bayrakları aç, ≤10 gerçek ürün görseliyle boru hattını koştur, HER halkayı ayrı ölç.
**Kapsam dışı:** hiçbir kaynak dosyaya dokunulmadı; bulunan kırıkların düzeltmesi dosya sahiplerinin işi.

> Rapordaki bütün sayılar bu koşuda konteyner içinde ölçüldü (bench execute / bench console /
> curl). Süre iddiası bilinçli yok — makine paylaşımlı; ölçü birimi BAYT ve SATIR SAYISI.

---

## 0. Sonuç özeti

**Boru hattı ÇALIŞTI.** 9 gerçek ürün görseli kuyruktan geçti; 9 `Media Asset`, 9 `Media Version`,
**88 `Media Rendition`**, 9 `Media Processing Job` (hepsi `success`) açıldı; 88 türevin 88'i diskte
ve bayt sayıları DB ile birebir. Türev adresleri İLK KEZ yeni `version_hash`'li şemada üretildi.
Orijinal dosyalara türev hattı DOKUNMADI (sha256 önce=sonra). Manifest uçları gerçek veri döndü.

**4 gerçek bulgu çıktı** (bu koşunun amacı buydu): §7.1 panel kör noktası (mükerrer File satırları),
§7.2 hassas-ikiz politika sapması, §3 worker konteynerlerinin eski imajda kalması (koşuyu
başlatamıyordu, giderildi), §5.3 ilk optimize koşusunda ilerleme kaydının kaybolması (bir kerelik,
tekrarlanamadı).

---

## 1. Bayrak durumu — önce / sonra (KALICI: açık bırakıldı)

`Media Engine Settings` (Single), `bench execute frappe.db.set_single_value` ile:

| Alan | Önce | Sonra |
|---|---|---|
| `media_pipeline_enabled` | 0 | **1** |
| `manifest_api_enabled` | 0 | **1** |
| `rendition_on_upload` | 0 | **1** |
| `active_slots` | (boş) | **`product.image`** |
| `max_renditions_per_asset` | 40 | 40 (dokunulmadı) |

**Ölçülmüş zorunluluk — görev iki bayrak diyordu, İKİ BAYRAK YETMİYOR:** yalnız
`media_pipeline_enabled=1` + `manifest_api_enabled=1` iken ölçüldü:
`pipeline_flags.is_enabled("rendition_on_upload") → False`,
`is_slot_enabled("product.image") → False`. Yani üretim kapısı (`maybe_generate_renditions` KAPI 1
ve KAPI 3) kapalı kalıyor, tek satır veri akmıyor. `rendition_on_upload=1` +
`active_slots="product.image"` de açıldı. **Dördü de açık bırakıldı** — DEV bunun için var.
(Diğer 8 slot bilinçli kapalı: bu koşu yalnız ürün görseli işledi.)

---

## 2. Önce/sonra — halka halka satır sayıları

| Tablo | Önce | Sonra | Fark |
|---|---|---|---|
| `Media Asset` | 0 | **9** | +9 (hepsi `slot_key=product.image`, `state=ready`) |
| `Media Version` | 0 | **9** | +9 (hepsi `engine_version=pillow-12.2.0`, `is_active=0` — tasarım gereği) |
| `Media Rendition` | 0 | **88** | +88 (88/88 `benefit_gate_passed=1`) |
| `Media Processing Job` | 0 | **9** | +9 (9/9 `status=success`, `attempt=1`, `queue=media-image-live`) |
| `File` | 5.053 | 5.053 | 0 — hat File kaydı açmıyor (tasarım gereği, `_write_rendition_file` docstring) |
| `Media Profile` | 36 | 36 | 0 (seed'li, dokunulmadı) |

Türev dağılımı (varlık başına): 10+10+10+10+10+12+6+10+10 = 88. En küçük kaynak (22.550 B,
81d2uu…jpg) fayda kapısı + D-1 mükerrer kapısı sonucu 6 türev; en büyük (067-1 GRİ.jpg) 12 türev.
88 türevin toplamı **1.999.973 bayt** (9 kaynağın toplamı 1.212.073 bayt — matris kaynaktan büyük,
beklenen: 96→1920 arası genişlik × webp/avif).

---

## 3. Ortam bulgusu: worker'lar DÜNKÜ imajdaydı (koşu öncesi giderildi)

**Ölçüm:** `istoc/tradehub-backend:v15` imajı bugün 07:06'da yeniden build edilmiş (`93643b…`);
`backend` konteyneri bu imajdan yeniden yaratılmış ama `queue-long` / `queue-short` / `scheduler`
**dünkü imajda** (`599e8b…`, 19:59) kalmıştı. Kanıt: `docker exec istoc-dev-queue-long-1 grep -c
content_fingerprint …/pipeline_bridge.py → 0` (BE-2'nin bugünkü devri worker'da YOK).
Kod imaja gömülü, bind-mount değil (mount listesi ölçüldü: yalnız `sites` + `logs` volume'ları) —
`bench restart` bunu ÇÖZMEZ, konteynerin yeni imajdan yeniden yaratılması gerekir.

**Yapılan:** `docker compose -p istoc-dev up -d --no-deps queue-long queue-short scheduler`.
Servis kontrolü — önce: `api/method/ping` 200, `/` 200; sonra: ikisi de yine **200**. Worker süreci
doğrulandı (`frappe worker --queue long,default,short` ayakta), yeni kod worker'da grep ile doğrulandı.

**Süreç riski (rapora not):** backend imajı her rebuild'de worker'lar da yeniden yaratılmazsa kuyruk
işleri sessizce ESKİ kodla koşar. Bugün koşulsaydı türevler hash'siz eski adres şemasıyla yazılacaktı.

**Yan bulgu — Pillow sürüm kayması:** rapor 64 canlıda `pillow-11.3.0` ölçmüştü; bugünkü imajda
`pillow-12.2.0` (Media Version kayıtlarında ölçüldü). Tablolar boş olduğu için hash kırılması yok;
ama motor sürümü `version_hash` girdisi olduğundan gelecekte imaj güncellemeleri adresleri değiştirir
— tasarımın bilinçli davranışı, sürpriz olmasın diye kayda geçirildi.

---

## 4. İşlenen dosyalar (9 adet — tavan 10'un altında)

Seçim: `Listing.primary_image` / `Listing Image.image` içinde `/files/…` (yerel) adresli GERÇEK
ürün görselleri. Boşluklu/Türkçe karakterli adlar bilinçli dahil (adres şeması sınaması).

| # | file_url | Bayt (önce) | sha256 (önce, ilk 12) | Bağlı ilan |
|---|---|---|---|---|
| 1 | `/files/469119194_122137766276501686_6275260628053641708_nf.jpg` | 99.785 | `386ed2a26fa3` | LST-00201 |
| 2 | `/files/51N9LYNfAVL._AC_SY395_.jpg` | 38.667 | `b461635a449d` | LST-00202 |
| 3 | `/files/RigidRAM-DDR4-DT-UDIMM__13538.jpg` | 110.392 | `01db779a4013` | LST-00204 |
| 4 | `/files/Bere.png` | 53.541 | `48686953f49b` | LST-00205 |
| 5 | `/files/Ekran Görüntüsü - 2026-06-22 10-27-16.png` | 398.965 | `1a7b4166438f` | LST-00206 |
| 6 | `/files/067-1 GRİ.jpg` | 459.585 | `e6703d1f68a9` | LST-00555 |
| 7 | `/files/81d2uu3SDwL._AC_SY395_.jpg` | 22.550 | `f4727f72d9f3` | LST-00202 galerisi |
| 8 | `/files/51oe+YL+l0L._AC_SY395_.jpg` | 41.361 | `dd0fd61e89e6` | LST-00202 galerisi |
| 9 | `/files/51wufijz52L._AC_SY395_.jpg` | 42.346 | `70dfe04b420d` | LST-00202 galerisi |

Not: aynı `file_url`'ye birden çok `File` satırı var (ölçüldü: #1'de 3, #4'te 5, #6'da 5 satır) —
bu gerçeklik §7.1'deki kırılmayı doğurdu.

---

## 5. Optimize/backfill akışı (panel ucu, HTTP ile)

Panelin çağırdığı gerçek uç HTTP ile çağrıldı (bench execute DEĞİL):
`POST /api/method/tradehub_core.api.media_admin.start_image_optimization`, ardından
`get_optimization_status` yoklaması — `useMediaOptimize.js` ile aynı akış. Oturum: Administrator
API anahtarı (`generate_keys` ile üretildi, DEV'de duruyor; §9).

### 5.1 Dry-run (dry_run=1, 9 dosya)

`{"job_key":"0ececebc9126","count":9,"preset":"balanced","dry_run":1}` → kuyruk `long` →
worker işledi (log: `Job OK`), durum ucu yanıtı:

```json
{"state":"partial","dry_run":true,"total":9,"processed":9,"optimized":1,"skipped":7,
 "errors":1,"original_bytes":1167407,"new_bytes":1112288,
 "skip_reasons":{"too_small":6,"already_small":1}}
```

### 5.2 Gerçek koşu (dry_run=0, aynı 9 dosya)

`job_key=849f23da2bec` → sonuç dry-run ile birebir aynı dağılım: **1 optimize edildi, 7 atlandı,
1 hata.** Ölçülen etkiler:

- **Optimize edilen tek dosya:** `/files/067-1 GRİ.jpg` — 459.585 → **404.466 bayt** (−55.119,
  %12). `tabFile` güncellendi (`th_optimized_at=2026-08-20 07:30:21`, `th_original_size=459585`).
- **Arşiv doğrulandı:** `archive.read("/files/067-1 GRİ.jpg")` → 459.585 bayt, sha256
  `e6703d1f…` = optimize ÖNCESİ orijinalin birebir kendisi. **Geri alınabilir** (`restore_image` ucu var).
- **Hatalı dosya (beklenen emniyet kemeri):** #1 `eab7be88e1` — traceback ölçüldü:
  `_assert_in_scope` → "Bu dosya hassas bir belgenin kopyası, kapsam dışında" (`_has_sensitive_twin`:
  aynı `content_hash` hassas bir doctype ekinde de var). Optimize akışı bu içeriğe dokunmayı reddediyor.
- **Optimize akışı TÜREV ÜRETMEZ (ölçüldü):** bu adımın sonunda `Media Rendition` hâlâ 0'dı.
  `media/runner.py` → `engine.optimize` yerinde yeniden yazar + arşivler; `pipeline_bridge`'i çağıran
  TEK yer `File.after_insert` kancası (grep ile ölçüldü). Yani paneldeki "optimize" düğmesi YENİ
  boru hattının backfill'i DEĞİL — mevcut dosyalar için türev backfill ucu YOK (§8 kalanlar).

### 5.3 Bir kerelik anomali: ilk dry-run'ın ilerleme kaydı kayboldu

İlk dry-run (`job_key=e70763f284aa`, 04:25:39Z) worker'da `Job OK` ile bitti ama
`get_optimization_status` her yoklamada `not_found` döndü; Redis taramasında anahtar YOK
(TTL 3600 sn, dolmuş olamaz). Aynı dakikada 8 adet "Error in translation file" kaydı düştü —
cache'in o pencerede temizlendiği/yeniden kurulduğu şüphesi (kanıtlanamadı). İzole ölçümler:
worker→redis-cache yazma bacağı sağlam (probe anahtarı worker'dan yazılıp web'den okundu),
ikinci ve üçüncü koşularda anahtar 1 saat boyunca kaldı. **Tekrarlanamadı; tek sefer.**
Panel etkisi: kullanıcı o tek koşuda sonucu göremezdi (iş yine de tamamlanmıştı).

---

## 6. Türev hattı — İLK GERÇEK dosyalar (asıl ölçüm)

Mevcut dosyalar `File.after_insert`'i tetiklemeyeceği için worker fonksiyonu kuyruğun kendisi
üzerinden koşturuldu: her dosya için `frappe.enqueue("…pipeline_bridge._run_rendition_job",
queue="long", file_url=…)` — hattın gerçek worker yolu, gerçek kuyruk, gerçek bayrak/kapsam
kontrolleri (fonksiyon bayrağı ve slot'u kuyruk içinde YENİDEN sorar; ölçüldü, §2 sayıları bunun
kanıtı). Senkron yola GEREK KALMADI: kuyruk işledi.

### 6.1 Yeni adres şemasının ilk gerçek örneği

`Media Version` (dosya #2 için):

```
version_hash = 9c924fe0afac764159f0286b2265862aa06e5bed559201e401d76e071a0f9002
source_hash  = b461635a449db58bc32587850d9031e682e386c3db5c912d8a4c3a79f77cd58b  (64 hane, TAM sha256)
engine_version = pillow-12.2.0 · policy_snapshot = kayıtta · crop_intent_snapshot = NULL
```

İlk gerçek türev adresi (INV-09 şeması `/files/media/{asset}/{version_hash}/{profil}-{genişlik}.{ext}`):

```
/files/media/7nhqvcmhpg/9c924fe0afac764159f0286b2265862aa06e5bed559201e401d76e071a0f9002/w96-96.webp   (914 B)
```

- **source_hash doğrulaması:** 9/9 kayıtta `source_hash` = diskteki içeriğin bu koşuda bağımsız
  hesaplanan sha256'sı (örn. #6'da optimize SONRASI içerik `14a2b825…` — hat, güncel içeriği işledi).
- **Hash yeniden hesaplanabilirlik:** `dedup.version_hash(source_hash, policy_snapshot, None,
  engine_version)` kayıttaki girdilerle yeniden hesaplandı → `version_hash` ile **birebir eşit** (ölçüldü).
- **Adres çözümü:** `dedup.parse_rendition_path` gerçek bir üretim adresini çözdü →
  `{asset: 7nhqvcmhpg, version_hash: 9c924fe0…, profile: w1280, width: 830, ext: webp}` —
  D-1 davranışı da görünüyor (830 px'lik kaynakta `w1280` basamağı kaynak genişliğinde üretilmiş).

### 6.2 Disk doğrulaması — 88/88

Her `Media Rendition.file_url` için diskte dosya arandı ve bayt sayısı DB kolonuyla karşılaştırıldı:
**88 dosyanın 88'i diskte, 88/88 bayt birebir; eksik/uyumsuz 0.** Toplam 1.999.973 bayt.
HTTP'den de ölçüldü: `w640-640.webp` → 200, 19.728 B; `w384-384.avif` → 200, 12.481 B (DB ile aynı).

### 6.3 Kalite alanları

- `ssim`: 88 kayıtta dolu, örneklem 0,9712–0,9882 · `quality`: dolu (70) · `bytes`: dolu ve disk ile birebir.
- Bayt tasarrufu türev başına ölçülebilir durumda (ör. #6'nın w640.webp'si 19.728 B ↔ kaynağı 404.466 B).

### 6.4 İdempotency (yeniden koşu)

`_run_rendition_job` aynı dosyayla ikinci kez koşuldu: `Media Rendition` **88 → 88** (yeni satır 0,
yeni dosya 0). `_renditions_exist` kapısı gerçek veride çalışıyor.

### 6.5 Orijinaller bozulmadı

9 dosyanın sha256'sı türev koşusundan ÖNCE ve SONRA alındı: **9/9 birebir aynı** (optimize'ın
bilinçli değiştirdiği #6 dahil — türev hattı ona da dokunmadı). Orijinal adresler HTTP 200:
`/files/067-1%20GR%C4%B0.jpg` → 200, 404.466 B; `/files/Bere.png` → 200, 53.541 B.
Ürün sayfası ayakta: storefront `/` → 200; `api.listing.get_listing_detail?listing_id=LST-00555`
→ 200, `images: ["/files/067-1 GRİ.jpg"]`.

---

## 7. Manifest uçları — panelin ve vitrinin GERÇEK aldıkları

### 7.1 `manifest_batch` (panel ucu, `useMediaRenditions` tüketiyor) — ÇALIŞIYOR ama KÖR NOKTALI

Gerçek yanıt (dosya #2, docname ile):

```json
{"manifests": {"342e593e46": {"file": "342e593e46", "file_url": "/files/51N9LYNfAVL._AC_SY395_.jpg",
  "assets": ["7nhqvcmhpg"],
  "renditions": [{"name": "7nia48vkbg", "asset": "7nhqvcmhpg", "profile": "w96", "width": 96,
    "height": 96, "format": "webp",
    "file_url": "/files/media/7nhqvcmhpg/9c924fe0afac…f9002/w96-96.webp",
    "bytes": 914, "ssim": 0.9863, "generation": "eager", "benefit_gate_passed": 1}, …10 satır]}},
 "requested": 1, "returned": 1, "max_batch": 100}
```

**KIRILMA (kök neden ölçüldü, düzeltme sahibinin işi):** aynı fiziksel dosyaya birden çok `File`
satırı olunca dosya→varlık zinciri kopabiliyor. İki ölçülmüş yüz:

1. **Adresle sorguda:** `{"file_urls": ["/files/51N9LYNfAVL._AC_SY395_.jpg"]}` →
   `assets: [], renditions: []` döndü — aynı dosyanın docname'iyle 10 türev dönerken.
   Neden: `manifest_batch` adres→docname çözümünde `{file_url: satır}` sözlüğü mükerrer satırlardan
   RASTGELE birini tutuyor (`34cc24f90b` seçildi), varlık ise `source_file=342e593e46`'ya bağlı;
   `_dosya_varliklari` docname üzerinden join yapınca boş kalıyor.
2. **Panel akışında:** panel, envanter satırının docname'ini yollar (`get_image_inventory`
   `file_url` bazında tekilleştirir). Envanterin seçtiği satır ile boru hattının
   (`frappe.db.get_value("File", {"file_url": …})` — sırasız İLK satır) seçtiği satır AYNI OLMAK
   ZORUNDA DEĞİL. Ölçüm — 9 dosyanın panel gözünden görünümü (envanter docname'i → manifest_batch):

   | Dosya | Panel sonucu |
   |---|---|
   | #2, #3, #5, #7, #8, #9 | türevler görünüyor (10/10/10/6/10/10) |
   | **#4 Bere.png** (URL'de 5 File satırı) | **assets=[] renditions=0 — panel "boru hattında yok" görür; oysa 10 türev var** (varlık `source_file=bd5b581362`, envanter `14a207158c` döndürüyor) |
   | **#6 067-1 GRİ.jpg** (5 satır) | **aynı körlük** (varlık `45412ba561`e bağlı, envanter `43e21180ea` döndürüyor) |
   | #1 nf.jpg | envanterde HİÇ görünmüyor (hassas-ikiz maskesi) → panel soramıyor bile; bkz. 7.2 |

   Kök neden tek cümle: **File↔Asset bağı docname üzerinden; oysa fiziksel dosyanın kimliği
   `file_url`/içerik. Mükerrer File satırı olan her dosyada (envanter ölçümü: satır sayısı 39'a
   kadar çıkabiliyor) panel yazı-tura görür.** Adayı çözüm sahibine: join'i `file_url` (ya da
   content hash) üzerinden yapmak — ilan tarafı (`_varliklari_getir`) zaten `f.file_url IN …`
   join'i kullandığı için bu körlükten ETKİLENMİYOR (ölçüldü, 7.3 çalışıyor).

### 7.2 Politika sapması: hassas-ikiz dosya (KIRILMA ADAYI, karar sahibine)

Dosya #1 (`eab7be88e1`): eski optimize akışı bu içeriği **reddediyor** (`sensitive_content_twin`)
ve medya envanteri onu **maskeliyor**. Yeni türev hattı ise aynı dosyayı **işledi**: varlık
`7m7n6rs4d4`, herkese açık `/files/media/…` altında 10 türev; `manifest_batch` docname'le sorulunca
10 türevi döndürüyor. `pipeline_bridge._resolve_scope` yalnız SEÇİLEN File satırının
`attached_to_doctype`'ına ve `is_private`'ına bakıyor; `_has_sensitive_twin` (içerik-ikizi) kontrolü
köprüde YOK. Dosyanın kendisi zaten public bir ürün görseli — ama iki akışın aynı içerik için zıt
karar vermesi bilinçli bir karar değilse tutarsızlık. Karar + olası düzeltme dosya sahibinin işi.

### 7.3 Vitrin uçları (guest) — gerçek veriyle ÇALIŞIYOR

- `get_manifest?listing=LST-00555&slot=product.image` (oturumsuz): `enabled: true`, 12 türev,
  `images[0].manifest.sources` avif+webp `srcset` merdivenleri, `fallback` artık YENİ şema
  adresinde: `/files/media/7qt7siovrn/4b7e4bae…4fa3/w640-640.webp`. `variants` yalnız gerçekten
  üretilenleri içeriyor (12), `missing_profiles: []`.
- `get_manifest_batch?listings=["LST-00555","LST-00206"]`: iki ilan da döndü (12 + 10 türev),
  ETag/cache_control başlıkları yerinde.
- Görünürlük süzgeci doğru çalışıyor (yanlış alarm değil): LST-00202 manifestte boş döndü çünkü
  `storefront_visible=0` (ölçüldü) — gizli ilanın galerisi misafire sızmıyor.

### 7.4 LQIP / baskın renk — ÖLÇÜLDÜ: DOLMUYOR (bağlı değil)

Manifest yanıtında `lqip`/`dominant_color`/`placeholder` anahtarları YOK (gerçek yanıtta ölçüldü);
`Media Asset`/`Media Version`/`Media Rendition` şemalarında alan da YOK. `pipeline/image/lqip.py`
kütüphanesi var ama onu çağıran tek üretim yolu yok (grep: yalnız `pipeline/delivery/picture.py` ve
observability modülleri — ikisi de köprüden/manifest API'sinden çağrılmıyor). Bu, "kod var veri
akmıyor"un hâlâ akmayan halkası — ayrı bağlama işi.

---

## 8. ÖLÇÜLDÜ / ÖLÇÜLEMEDİ tablosu

| Halka | Durum | Kanıt |
|---|---|---|
| Bayrak açma + kapı davranışı | **ÖLÇÜLDÜ** | §1 (iki bayrağın yetmediği dahil) |
| Kuyruk işçisi işliyor mu | **ÖLÇÜLDÜ** | §3, §5, §6 — RQ `long` kuyruğu işledi; senkron yola gerek kalmadı |
| Optimize dry-run + gerçek (panel HTTP) | **ÖLÇÜLDÜ** | §5 — 1 optimize (−55.119 B), arşiv birebir, 1 beklenen ret |
| Asset/Version/Rendition önce/sonra | **ÖLÇÜLDÜ** | §2 — 0/0/0 → 9/9/88 |
| Yeni adres şeması + diskte varlık | **ÖLÇÜLDÜ** | §6.1–6.2 — 88/88 dosya, bayt birebir, HTTP 200 |
| version_hash yeniden hesaplanabilirlik | **ÖLÇÜLDÜ** | §6.1 — kayıt girdilerinden aynı hash |
| SSIM / bayt kalite raporu | **ÖLÇÜLDÜ** | §6.3 — 88 satırda dolu |
| LQIP / baskın renk | **ÖLÇÜLDÜ: DOLMUYOR** | §7.4 — alan yok, çağıran yok |
| `manifest_batch` gerçek yanıt | **ÖLÇÜLDÜ** | §7.1 — örnek yanıt raporda; kör nokta dahil |
| Vitrin manifest uçları (guest) | **ÖLÇÜLDÜ** | §7.3 |
| Orijinal bütünlüğü + ürün sayfası 200 | **ÖLÇÜLDÜ** | §6.5 |
| İdempotency (yeniden koşu) | **ÖLÇÜLDÜ** | §6.4 — 88→88 |
| Yükleme kancası (`File.after_insert`) ile uçtan uca | **ÖLÇÜLEMEDİ** | Bu koşuda yeni dosya YÜKLENMEDİ (≤10 tavanı mevcut dosyalara harcandı; kanca yolunun kapıları worker içinde aynı fonksiyonlarla yeniden koşuyor — o kısım ölçüldü). Gerçek yükleme e2e'si ayrı küçük koşu ister. |
| `rendition_on_upload` dışındaki 8 slot | **ÖLÇÜLMEDİ (bilinçli)** | Yalnız `product.image` açıldı |

## 9. DEV'de bırakılan kalıcı izler (geri alınamaz temizlik YAPILMADI)

1. Bayraklar AÇIK (§1) — istenen kalıcı durum.
2. Worker/scheduler konteynerleri yeni imajdan yeniden yaratıldı (§3).
3. `/files/067-1 GRİ.jpg` optimize edildi (−55.119 B); orijinali arşivde, `restore_image` ile geri alınabilir.
4. 9 Media Asset + 9 Version + 88 Rendition + 9 Job kaydı; diskte `sites/…/public/files/media/` altında 88 dosya (~2,0 MB). Silinmedi, purge çağrılmadı.
5. Administrator için API key/secret üretildi (HTTP ölçümleri için; DEV sınırlı). Gerekirse User > API Access'ten sıfırlanır.
6. Redis'te iki zararsız probe anahtarı (`tradehub_media_optimize:probe1/probe2`, TTL'li — kendiliğinden düşer).
