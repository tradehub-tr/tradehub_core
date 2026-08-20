# 81 — W6: Video boru hattı DEV'de İLK GERÇEK koşum (Faz 7'nin veri tarafı)

**Tarih:** 2026-08-20 · **Ortam:** DEV (`istoc.localhost`, `istoc-dev` compose)
**Görev:** T-072/073/074'ün "kod var, veri yok" yarısını kapatmak: video slotunu aç,
gerçek videoları `pipeline/video/` motorundan geçir, HER halkayı ayrı ölç.
69 no'lu raporun (W3-B, görüntü) video karşılığı.

> Bütün sayılar konteynerde ölçüldü (`istoc-dev-backend-1`, ffmpeg **n8.1.2-44** —
> **libvmaf=1**). Süre iddiası yok; ölçü birimi BAYT, VMAF ve dosya sayısı.
> `wall_s` alanları motorun kendi kaydı, karşılaştırma iddiası taşımıyor.

---

## 0. Sonuç özeti

**Motor GERÇEK dosyalarla ÇALIŞTI — hiçbir halka kırılmadı.** 4 gerçek DEV videosunun
künyesi ölçüldü ve karar tablosundan geçirildi (3 PASSTHROUGH, 1 REMUX); REMUX moov'u
gerçekten başa aldı; fayda kapısı (INV-05, %10) İLK KEZ gerçek çıktıyla sınandı ve
**tuttu** (%11,44 kazanç, kapıdan türetilen tavan 594 kbps); **VMAF ilk kez gerçekten
ölçüldü: 89,34**; poster + önizleme klibi üretildi ve HTTP 200; HLS merdiveni 3 basamak
+ 405 segment üretti, büyütme yapmadı, açılış bütçesi geçti. 17 yeni gerçek-çıktı-temelli
test konteynerde YEŞİL; eşik kurcalama vacuity sınaması KIRMIZI verdi.

**Ama boru hattı diye bir şey video için YOK** — motor var, hat yok. Köprü
(`pipeline_bridge`) yalnız görsel işliyor; video için kuyruk yolu, DocType kaydı,
manifest temsili ve poster'ı yazan üretim ucu bulunmuyor (§7, §8). Bu koşum motoru
doğrudan çağırarak (görev tanımındaki `bench execute` muadili) veriyi ilk kez akıttı.

---

## 1. Bayrak: video slotu önce/sonra (KALICI: açık bırakıldı)

Doğru anahtar ölçülerek bulundu: `Listing.video_url` → **`product.video`**
(`policy/slots/product-video.json` `bound_to`; `company.cover_video` şirket kapağına ait,
bu koşuda kullanılmadı).

| Ölçüm | Önce | Sonra |
|---|---|---|
| `is_slot_enabled("product.video")` | **False** | **True** |
| `is_slot_enabled("product.image")` | True | True (bozulmadı) |
| `active_slots` | `product.image` | `product.image,product.video` |

Not: W3-B raporu `active_slots`'u satır ayraçlı yazmıştı; `parse_slot_keys` virgülü de
kabul ediyor (ölçüldü: iki slot da True).

## 2. İşlenen videolar (4 künye, 2 tam işlem)

DEV'de `tabFile` içinde 79 mp4 satırı var; **74'ü < 1 KB'lık seed sahtesi** (19-66 bayt,
oynatılamaz). Gerçek video 5; 4'ü `Listing.video_url`'de yerel adresle bağlı:

| Listing | Dosya | Bayt | Künye (ölçüldü) | Karar (kural) |
|---|---|---:|---|---|
| LST-00862 | `AQPp_3LT…MrwRAd.mp4` | 1.085.963 | 352×352 h264/aac, 28,9 sn, 300 kbps, moov başta | **PASSTHROUGH** (`default`) |
| LST-04035 | `AQOOb74v…vRopys.mp4` | 3.077.433 | 720×1280 h264/aac, 33 sn, 746 kbps | **PASSTHROUGH** (`default`) |
| **LST-04043** | `Evde taze sıkılmış… 🍹 …limon.mp4` | 2.809.249 | 720×720 h264/aac, 28 sn, 802 kbps | **PASSTHROUGH** (`default`) — tam işlem |
| **LST-04419** | `9mb.mp4` | 9.622.535 | 1280×720 h264 sessiz, **540 sn**, 142 kbps, **moov SONDA** | **REMUX** (`moov_at_end`) + **HLS gerekli** (540 sn > 60 sn) — tam işlem |

Türkçe + emoji'li dosya adı bilinçli dahil (adres sınaması): sorunsuz işlendi ve
URL-encode'lu hâli HTTP 200. Gerçek satıcı videolarının üçü de zaten teslim edilebilir
çıktı — Instagram türü kaynaklar önceden sıkıştırılmış; tablo doğru olarak "dokunma" dedi.
TRANSCODE'u hiçbir gerçek dosya tetiklemedi; kapı/VMAF halkaları bu yüzden LST-04043
üzerinde gerçek bir kodlama sondasıyla ölçüldü (§3.3).

## 3. Halka tablosu — hepsi ÖLÇÜLDÜ

Çıktı kökü: `sites/istoc.localhost/public/files/media/video/{File docname}/`
(video için kanonik adres şeması YOK — §8; bu koşumun seçtiği yer, INV-09'un video muadili değil).

| Halka | Durum | Ölçülen değer |
|---|---|---|
| **1. Karar** | **ÖLÇÜLDÜ** | 4/4 künye tablodan geçti; iz (trace) 15 kuralın hangisine bakılıp eşleşmediğini kaydetti. 3×`default→PASSTHROUGH`, 1×`moov_at_end→REMUX`. PASSTHROUGH dosya YAZMADI (`out_exists=false` — doğru davranış) |
| **2. Transcode/Remux diskte** | **ÖLÇÜLDÜ** | REMUX: `93144fcb41/h264.mp4` diskte, 9.622.535 → **9.622.536 B** (+1 B faststart), `moov_at_end` **True → False**, süre 540 sn korunmuş, kaynak sha256 önce=sonra |
| **3. Fayda kapısı (INV-05, %10)** | **ÖLÇÜLDÜ — TUTTU** | Gerçek kodlama sondası (LST-04043): 2.809.249 → **2.487.877 B**, kazanç **%11,44 ≥ %10** → kabul. Tavan kapıdan türetildi: 802 kbps × 0,9 − 128 (ses) = **594 kbps** — panel kartındaki "bütçe"nin ilk gerçek sınaması. REMUX muafiyeti de ölçüldü (+1 B'ye rağmen kabul, `exempt_actions`) |
| **4. VMAF (kalite kapısı)** | **ÖLÇÜLDÜ: 89,34** | `measure_quality` → `{metric: vmaf, vmaf: 89.342709}`. **İmaj artık libvmaf'lı** (ffmpeg n8.1.2; tablodaki `vmaf_note` "libvmaf yok, 2026-08-19" ESKİMİŞ). **89,34 < eşik 93** — ve eşiği uygulayan kod YOK (§8.3). Süre kapısı da ölçtü: 114 ms > 100 ms tavanı → `DUSTU` notu, çıktı yine kabul (tasarım gereği) |
| **5. Poster** | **ÖLÇÜLDÜ** | LST-04043: `poster.webp` 16.912 B, t=1,233 sn, luma %54,29, kalite 78, ilk pencere [0,5–5,0], retry 0. LST-04419: 9.194 B, t=4,0 sn, luma %49,64. İkisi de **HTTP 200** (`image/webp`). Yazıldığı yer BU KOŞUMUN seçimi — üretimde poster'ı yazan/kaydeden uç yok (§8.2) |
| **5b. Önizleme klibi** | **ÖLÇÜLDÜ** | `preview.mp4` **139.764 B** ≤ 400 KB politika hedefi (ilk basamakta: 6 sn, CRF 28), poster damgasından başlıyor (görsel süreklilik), HTTP 200 |
| **6. HLS** | **ÖLÇÜLDÜ** | Karar: gerekli (540 sn > 60 sn). Remux ÇIKTISINDAN üretildi: `master.m3u8` + **3 basamak** (360p/480p/720p — kaynak kısa kenarı 720, **1080p İLAN EDİLMEDİ**, no_upscale gerçek kaynakta tuttu), basamak başına **135 segment**, TARGETDURATION 4. Açılış bütçesi 3/3 **GECTI**: 161.841 / 173.121 / 275.581 B ≤ 1.280.000. master + playlist + segment HTTP 200 (`application/vnd.apple.mpegurl`, `video/mp2t`) |
| **7. İdempotency** | **ÖLÇÜLDÜ** | Aynı iki video ikinci kez tam işlendi: dosya sayısı `4cacb5898d: 3→3`, `93144fcb41: 411→411`. AMA bu yol-determinizmi (aynı ada üzerine yazma); atlama kapısı yok — her koşum yeniden kodluyor (§8.4) |
| **8. Manifest/teslim** | **ÖLÇÜLDÜ: VİDEO TEMSİLİ YOK** | §7 |

## 4. Bulgu: HLS basamağında fayda kapısı yok (ölçülmüş örnek)

`9mb.mp4` 142 kbps'lik ÇOK verimli bir kaynak; capped-CRF basamak tavanları (800/1400/2800k)
kaynağın çok üstünde kaldığı için CRF 23 kaynaktan fazla bit harcadı:

| Basamak | Bayt | Kaynağa oranı |
|---|---:|---|
| 360p | 7.299.637 | 0,76× |
| 480p | 7.905.561 | 0,82× |
| **720p** | **12.095.893** | **1,26× — kaynaktan BÜYÜK** |
| Paket toplamı | 27.301.091 | 2,84× |

Tek dosya yolundaki `rate_ceiling_kbps` (tavanı kaynak bitrate'inden türetme) HLS
basamaklarına UYGULANMIYOR — `hls._rate_control_args` yalnız tablodaki sabit
`maxrate`'i kullanıyor. `hls.rate_control_why`'daki ölçülmüş dersin (sabit `-b:v`
şişirmesi) CRF tarafındaki devamı. Kasıtlı olabilir (merdivenin amacı bant genişliği
sınıfları, bayt tasarrufu değil) — karar tablo sahibinin; buraya ölçüm olarak kaydedildi
ve `test_720p_basamagi_kaynaktan_buyuk_cikti_kaydi` bu durumu sabitliyor.

## 5. Testler — gerçek-çıktı-temelli, konteynerde koşuldu

- **Fixture:** `tradehub_core/tests/fixtures/media/w6-video-live-run.json` — bu koşumun
  ölçülmüş değerlerinden üretildi (4 künye, karar, kapı sayıları, VMAF, poster, HLS,
  remux). Sentetik değer yok.
- **Modül:** `tradehub_core/tests/test_video_live_run.py` — 17 test, 6 sınıf:
  karar tablosu gerçek künyelerle, fayda kapısı aritmetiği + tavan türetme formülü,
  VMAF/süre kapısı kayıtları, HLS merdiveni (1080p yokluğu master içeriğiyle), DEV diski
  doğrulaması (yerel makinede otomatik skip).
- **Koşum:** `docker exec -w /home/frappe/frappe-bench istoc-dev-backend-1 env/bin/python
  -m unittest tradehub_core.tests.test_video_live_run -v` → **17/17 OK**.
  (Tuzak ölçüldü ve docstring'e yazıldı: `apps/tradehub_core/tradehub_core` cwd'sinden
  koşulursa modül-namespace dizini paketi gölgeliyor, `tradehub_core.media` bulunamıyor.)
- **Vacuity:** konteynerdeki `video_decision.json`'da `min_saving_ratio` 0,1 → 0,2
  yapıldı → **3 test KIRMIZI** (`AssertionError: 0.2 != 0.1` + kabul ve tavan testleri);
  geri alındı → 17/17 YEŞİL. Gerçek koşumun %11,44'lük kazancı 0,1 ile 0,2 arasında
  olduğu için eşik oynatması sonucu FİİLEN değiştirirdi — testler boş yeşil değil.
- **Regresyon:** mevcut `test_video_transcode` + `test_video_decision` yeni imajda
  (ffmpeg 5.1.9 → **8.1.2**) koşuldu: **167/167 OK**.
- Lint: konteynerde/yerelde ruff kurulu değil (ölçüldü); `py_compile` OK, tab indent +
  type hint kurallarına uyuldu.

## 6. Kaynak bütünlüğü + kod eşitliği

- İşlenen kaynakların sha256'sı önce=sonra (2/2 birebir; PASSTHROUGH + REMUX kaynağa yazmıyor).
- Konteynerdeki `pipeline/video/*.py` + `video_decision.json` yereldekiyle **md5 birebir**
  (6/6 dosya) — `docker cp`/konteyner yenileme GEREKMEDİ; kuyruk konteynerlerine hiç dokunulmadı.
- Orijinal video HTTP 200 (2.809.249 B, `video/mp4`), ürün detayı ayakta
  (`get_listing_detail?listing_id=LST-04043` → `data.videoUrl` doldu).

## 7. Manifest/teslim — FE'ye gereken satırlar (DOKUNULMADI, rapor)

**Ölçülen gerçek durum:**

- `get_manifest?listing=LST-04043&slot=product.video` → `enabled:true` ama içerik ilanın
  **GÖRSELLERİ** (`fallback: /files/kare-9ff966de.jpg`, `renditions: []`) — manifest API'si
  slot ne olursa olsun `Listing Image`/`primary_image` okuyor (`media_manifest.py`
  `_manifest_batch_icin` → `build_image`); video varlığının manifest temsili YOK.
  `enabled:true` yanıltıcı: slot açık ama o slotun medya türü hiç servis edilmiyor.
- Vitrinin bugün aldığı TEK video alanı: `api/listing.py:1443` → `"videoUrl": listing.video_url`
  (ham dosya adresi). Bu koşumun ürettiği poster/HLS hiçbir uçtan dönmüyor.

**Eşleşme tablosu — `MediaVideo.vue` props ↔ backend:**

| MediaVideo.vue prop (admin-panel `components/media/MediaVideo.vue:57-70`) | Backend'te kaynağı | Bu koşumda üretilen karşılık |
|---|---|---|
| `src` (progresif mp4) | `data.videoUrl` (yalnız listing detail) | orijinal ya da `…/h264.mp4` (REMUX çıktısı) |
| `hlsSrc` (.m3u8) | **YOK** | `…/93144fcb41/hls/master.m3u8` (HTTP 200) |
| `poster` | **YOK** | `…/{docname}/poster.webp` (HTTP 200) |
| `width`/`height` (CLS için) | **YOK** | künyede ölçülü (720×720, 1280×720) |
| `lqip` | **YOK** (görselde de akmıyor, rapor 69 §7.4) | üretilmedi |
| `type` | **YOK** | `video/mp4` |

Storefront tarafı: `ProductVideoSection.ts:63` `<video src …>` basıyor — `poster`
özniteliği YOK (galeri karosu siyah ilk kareye mahkûm), HLS dalı YOK. Panel simülatörü
(`MediaSimulatorView.vue` SimPosterCard) "poster üretimini çağıran API ucu YOK" diyor —
bu koşumla doğrulandı: uç hâlâ yok, poster ancak elle üretildi.

**Gereken (sahiplerine):** manifest yanıtına (ya da listing detail'e) video bloğu:
`{src, hlsSrc, poster, width, height, duration_s}`; `ProductVideoSection.ts` mp4 dalına
`poster="…"`; `MediaVideo.vue` zaten hazır — beklediği alanların TAMAMI bu koşumda diskte
üretilebilir durumda.

## 8. Tasarım boşlukları (kırık değil — HİÇ BAĞLANMAMIŞ)

1. **Video için köprü/kuyruk yolu yok.** `pipeline_bridge` yalnız görsel
   (`_resolve_scope` docstring: "medya türü (video değil, görsel)"); `File.after_insert`
   köprünün tek çağıranı. Video yüklemesi bugün hiçbir işleme tetiklemiyor;
   `media/transcode.py`'nin eski VP9 hattı da `product.video` slot bilgisinden habersiz.
   Bu koşum motoru DOĞRUDAN çağırdı — üretimde bunu yapacak worker fonksiyonu yazılmalı.
2. **Çıktıların DocType kaydı yok.** Görüntüdeki Media Asset/Version/Rendition zincirinin
   video karşılığı açılmıyor; bu koşumun 416 çıktı dosyası DB'de görünmez (öksüz-rapor
   taraması ve manifest için kör). Adres şeması da tanımsız (INV-09'un video muadili yok);
   `files/media/video/{docname}/` bu koşumun geçici seçimi.
3. **`vmaf_min` uygulanmıyor + `vmaf_note` eskimiş.** Eşik (93) tabloda duruyor,
   `transcode()` hiçbir yerde `measure_quality` çağırmıyor; imaj artık libvmaf'lı olduğu
   için "ölçemiyoruz" gerekçesi düştü. İlk gerçek ölçüm (89,34 < 93) eşik bağlansaydı bu
   çıktının REDDEDİLECEĞİNİ söylüyor — eşik mi gevşek, çıktı mı zayıf, karar tablo sahibinin.
4. **Video idempotency'si yol-determinizminden ibaret.** Görüntüdeki `_renditions_exist`
   muadili yok; ikinci koşum aynı sayıda dosya bıraktı ama tüm kodlamaları YENİDEN yaptı.
5. **HLS basamağında fayda/bütçe kapısı yok** (§4).

## 9. DEV'de bırakılan kalıcı izler

1. `active_slots` = `product.image,product.video` — istenen kalıcı durum.
2. `public/files/media/video/4cacb5898d/` → `poster.webp`, `preview.mp4`, `gate-probe.mp4`
   (VMAF sondası; 2,49 MB) — 3 dosya.
3. `public/files/media/video/93144fcb41/` → `h264.mp4` (remux), `poster.webp`,
   `hls/` (master + 3 playlist + 405 segment) — 411 dosya, ~36,9 MB toplam.
4. Konteynere kopyalanan test + fixture (`tests/test_video_live_run.py`,
   `tests/fixtures/media/w6-video-live-run.json`) — repo'daki dosyaların birebir kopyası;
   imaj rebuild'inde zaten repodan gelecek.
5. Kaynak videolara, DB kayıtlarına, kuyruk konteynerlerine dokunulmadı; hiçbir şey silinmedi.
