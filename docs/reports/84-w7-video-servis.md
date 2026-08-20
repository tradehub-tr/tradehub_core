# 84 — W7: Video çıktılarının kalıcılaşması + servis edilmesi (Faz 7 kapanışı)

**Tarih:** 2026-08-20 · **Ortam:** DEV (`istoc.localhost`, `istoc-dev` compose)
**Görev:** T-072/073/074'ün kalan yarısı — rapor 81'in (W6-B) ölçtüğü 5 tasarım
boşluğunu kapatmak: kuyruk yolu, DocType kaydı + kanonik adres, `vmaf_min`
kapısı, HLS basamak kapısı, manifest video servisi.

> Bütün sayılar konteynerde ölçüldü (ffmpeg **n8.1.2-44**, libvmaf=1). Süre
> iddiası yok; ölçü birimi BAYT, VMAF, HTTP durum kodu ve test sayısı.

---

## 0. Sonuç özeti

**Video hattı artık üretim yolunda.** Gerçek DEV videosu `9mb.mp4` (LST-04419)
İLK KEZ kuyruktan uçtan uca aktı: `File.after_insert` kancası → `frappe.enqueue`
→ RQ `long` worker'ı → karar (REMUX) → h264 + poster + HLS → Media
Asset/Version/Rendition/Processing Job kayıtları → hepsi HTTP 200. `vmaf_min`
kapısı bağlandı ve gerçek video kapıdan DÜŞTÜ (89,31 < 93 → türev atıldı,
kaynak korundu — doğru davranış). HLS basamak kapısı bağlandı ve gerçek
koşumda 720p basamağını (kaynaktan %26 büyük) master playlist'ten çıkardı.
`get_manifest(slot=product.video)` artık görsel değil, `MediaVideo.vue`'nun
beklediği alanları taşıyan `video` bloğu dönüyor.

Testler: **28 yeni** (`test_video_servis`) + korunması istenen tüm suitler
yeşil: `test_pipeline_bridge` **22**, `test_media_manifest_api` **11**,
`test_manifest_batch` **16**, video suitleri **167**, `test_video_live_run`
**17**. Vacuity: HLS basamak kapısı kaldırılınca 3 test KIRMIZI (720p yeniden
ilan edildi), geri konunca yeşil.

**Kısıtlara uyum:** hiçbir repoda commit atılmadı; `hooks.py` ve `patches.txt`
DEĞİŞTİRİLMEDİ (video yolu, görselin zaten kayıtlı `File.after_insert`
kancasının içinden dallanıyor; şema değişikliği DocType JSON + `bench migrate`
ile gitti — migrate kilit protokolüyle koşuldu); frontend'e dokunulmadı;
`vmaf_min` eşiği (93) ve `min_saving_ratio` (0,1) DEĞİŞTİRİLMEDİ.

---

## 1. Boşluk 1 — köprü/kuyruk yolu (`pipeline_bridge.py`, yalnız EK)

Görsel yolu SATIRI SATIRINA korundu (22 test yeşil); tek dokunuş:
`maybe_generate_renditions` içinde görsel kapsamına girmeyen dosya
`_maybe_enqueue_video`'ya düşüyor. Yeni video bölümü aynı deseni birebir izler:

```
File.after_insert (mevcut kanca — hooks.py DEĞİŞMEDİ)
  └─ maybe_generate_renditions
       ├─ görsel kapsamı → (bugünkü yol, değişmedi)
       └─ _maybe_enqueue_video          (W7)
            ├─ KAPI 1  rendition_on_upload      (çağıran sordu)
            ├─ KAPI 2  _resolve_video_scope     (uzantı KIND_VIDEO, private/KVKK
            │          muaf, hassas-ikiz kontrolü AYNEN, slot politikadan)
            ├─ KAPI 3  is_slot_enabled("product.video")
            ├─ idempotency (_renditions_exist — görselle aynı fonksiyon)
            └─ frappe.enqueue(queue="long", 1800 sn) → _run_video_job
                 ├─ probe → karar tablosu (REJECT ise asset `rejected`+kod)
                 ├─ REMUX/TRANSCODE → h264 türevi (kapılar transcode() içinde)
                 ├─ poster (best-effort) → HLS (gerekliyse, basamak kapılı)
                 └─ Media Asset/Version/Rendition/Processing Job + commit
```

- **Ayrı bayrak AÇILMADI (gerekçe):** video da yükleme anında tetiklenen bir
  üretim; `rendition_on_upload` (üretim şalteri) + `active_slots` slot şalteri
  operatöre iki kademeli kontrol veriyor. `active_slots`tan `product.video`
  silmek video hattını tek başına kapatır — test edildi
  (`test_slot_kapaliyken_enqueue_yok`).
- **Slot çözümü politikadan:** video slotu = politikasında `video` bloğu olan
  slot (`product.video`, `company.cover_video`); `bound_to` girdileri `Data`
  alanları. Ölçüldü (2026-08-20 DEV): 4 gerçek videonun 4'ünde de
  `attached_to_*` NULL — slot, görseldeki K-3 gibi İLİŞKİDEN çözülüyor
  (`Listing.video_url == file_url`, `Listing Variant Item.variant_video_url`).
- **İş kaydı:** `job_type=transcode`, `queue=media-video` (Faz 3 tasarım adı;
  gerçek RQ kuyruğu görselle aynı `long`), anahtar `video:{sha32}:{slot}`.

## 2. Boşluk 2 — DocType kaydı + kanonik adres şeması

**Karar: ayrı DocType AÇILMADI; Media Asset/Version/Rendition zinciri video
için de kullanılıyor.** Gerekçe: şema zaten video için tasarlanmış
(`Media Asset.media_type` `video` seçeneği, `Media Rendition.format` `mp4/webm`
seçenekleri A1a'dan beri duruyor) — eksik olan üretim ucuydu. Ayrı bir DocType,
manifest/öksüz-tarama/panel envanteri gibi mevcut tüm okuyucuları ikinci bir
zincire bakmaya zorlardı. Şemaya eklenenler (spec aynalarıyla birlikte):

| Değişiklik | Dosya | Gerekçe |
|---|---|---|
| `Media Rendition.format` enum'una `m3u8` | `doctype/media_rendition/media_rendition.json` + `doctype_specs/media_rendition.json` | HLS paketi tek dosya değil; kayıt master playlist'i gösterir, `bytes` İLAN EDİLEN basamak toplamını taşır |
| `Media Version.duration_s` (Float, 3) | `doctype/media_version/media_version.json` + `doctype_specs/media_version.json` | Teslim künyesinin zaman boyutu — genişlik/yükseklik ile aynı gerekçe; manifest her istekte ffprobe koşmadan okur |

**Adres şeması: görüntüyle AYNI kök** — `dedup.rendition_path` kullanılıyor:

```
/files/media/{asset}/{version_hash}/h264-{genişlik}.mp4     (birincil, REMUX/TRANSCODE çıktısı)
/files/media/{asset}/{version_hash}/poster-{genişlik}.webp  (ilk anlamlı kare)
/files/media/{asset}/{version_hash}/hls/master.m3u8         (+ v360p/… basamak dizinleri)
```

Gerekçe: INV-09 aynen taşınıyor — `version_hash` 4 girdiden üretiliyor
(`source_hash` + politika anlık görüntüsü + crop(None) + motor sürümü).
Videoda politika anlık görüntüsü İKİ katman: slot politikası + karar tablosu
(`video_decision.json` — CRF/tavan/merdiven değişince adres zorunlu değişir).
Motor kimliği `ffmpeg-n8.1.2-44-…` (görseldeki `pillow-…`in karşılığı; imaj
ffmpeg'i değişince tüm video türev adresleri zorunlu yenilenir). HLS tek
dosya olmadığı için düzen `hls/` alt diziniyle GENİŞLETİLDİ — kök aynı,
`Cache-Control: immutable` güvencesi aynı. W6-B'nin geçici
`files/media/video/{docname}/` seçimi terk edildi (izleri duruyor, §8).

- **PASSTHROUGH yeni dosya YAZMAZ ve `Media Rendition` satırı AÇMAZ** —
  satır üretilmiş dosyanın künyesidir, kaynağın takma adı değil; manifest
  `src`'yi ham dosyaya düşürür (rapor 81 §7 tablosunun ilk satırı).
- **`Media Version.lqip` poster baytlarından dolar:** video baytını Pillow
  açamaz; sürüm zenginleştirme kancası video kaynağında boşa koşup log
  kirletirdi. Poster zaten "ilk anlamlı kare" — `MediaVideo.vue` `lqip`
  prop'unun doğru kaynağı (gerçek koşumda doldu, manifestte döndü).

## 3. Boşluk 3 — `vmaf_min` kalite kapısı bağlandı

`transcode()` içinde, sıra: **fayda kapısı → kalite kapısı → süre kapısı →
os.replace**. Fayda kapısından düşen çıktı için VMAF ölçülmez (saniyeler süren
ikinci kod çözme boşa; testle sabitlendi). Eşik TABLODAN (`vmaf_min: 93` —
**değiştirilmedi**); VMAF ölçülemiyorsa (libvmaf'sız imaj) kapı uygulanmaz ve
`vmaf_gate: OLCULEMEDI` yazılır — sayı uydurulmaz. Kapıdan düşen TRANSCODE,
B-2 geri çekilme kurallarına aynen tabi (kap/moov kusuru varsa REMUX).

**Gerçek sonuç (LST-04043, zorlanmış TRANSCODE sondası):**

| Ölçüm | Değer |
|---|---|
| Fayda kapısı | GEÇTİ: 2.809.249 → 2.487.877 B, kazanç %11,44 ≥ %10 |
| VMAF | **89,31 < 93 → `vmaf_gate: DUSTU`, çıktı ATILDI, kaynak korundu** |
| Geri çekilme | YAPILMADI (moov başta, kap mp4 — REMUX bir şey düzeltmez) → fiilen PASSTHROUGH |

Yani rapor 81 §8.3'ün öngörüsü doğrulandı: bu gerçek video, bayt kazandıran
ama kalite kapısını geçemeyen bir türev üretiyor ve hat onu **teslim etmiyor**.
Eşik mi gevşetilmeli (89 ≈ "algılanamaz fark" sınırına yakın) yoksa çıktı mı
zayıf — **karar tablo sahibinin**; kod eşiğe dokunmadı. Ölçülen diğer uçlar:
şişirilmiş 720p fixture'ı 96,63 (geçer), sessiz 720p kapısız sondası 90,99.

**Kapı `enforce_benefit_gate`i izler (`enforce_quality_gate=None` varsayılanı),
gerekçesi ölçülü:** kapısız koşum (`enforce_benefit_gate=False`) çıktıyı
İNCELEMEK için var ve mevcut testler dosyanın diskte kalmasını sözleşme
sayıyor; sessiz fixture 90,99 < 93 olduğundan kapı orada da koşsaydı inceleme
çıktısını yok ederdi. Üretim yolu iki kapıyı birden açık kullanır.
`video_decision.json` `vmaf_note` alanı güncellendi (eski "libvmaf yok" notu
tarihçesiyle birlikte duruyor).

## 4. Boşluk 4 — HLS basamak fayda kapısı

`hls.enforce_rung_benefit_gate(result)`: toplam baytı kaynaktan KÜÇÜK olmayan
basamak master playlist'ten çıkarılır ve dosyaları silinir; hiçbir basamak
küçük değilse paketin tamamı ilan edilmez (`master_path=""`, teslim progresif
mp4'te kalır). Kapı `make_hls`in İÇİNDE DEĞİL (bilinçli): motorun "merdiveni
üret ve ölç" sözleşmesi ve o sözleşmenin 167 testi merdivenin tamamını görmeye
devam ediyor — ilan bir TESLİM kararı ve üretim yolu (`_run_video_job`) verir.

**Gerçek koşum (9mb.mp4, kaynak=remux çıktısı 9.622.536 B):**

| Basamak | Bayt | Kapı | Master'da |
|---|---:|---|---|
| 360p | 7.299.637 | GEÇTİ | var |
| 480p | 7.905.561 | GEÇTİ | var |
| **720p** | **12.095.893** | **DÜŞTÜ (1,26×)** | **YOK — dizini silindi, HTTP 404** |

`Media Rendition(hls)` satırı: 854×480 (ilan edilen tepe basamak), bytes =
15.205.198 (yalnız İLAN EDİLEN toplam). Karşı-kanıt diskte duruyor: W6-B'nin
kapısız paketi (`files/media/video/93144fcb41/hls/master.m3u8`) 720p'yi hâlâ
ilan ediyor. Kural + ölçülmüş gerekçe `video_decision.json`
`hls.rung_benefit_gate` bloğuna yazıldı (davranışı `HlsSpec` okumuyor; blok
belgeleme).

**Vacuity (görev şartı):** konteynerde kapının gövdesi no-op yapıldı →
`test_kaynaktan_buyuk_basamak_ILAN_EDILMEZ` + 2 test **KIRMIZI**
(`'v720p/playlist.m3u8' unexpectedly found …`); geri kondu → yeşil, md5
repo ile birebir.

## 5. Boşluk 5 — manifest video servisi (`api/media_manifest.py`)

`get_manifest` / `get_manifest_batch`, slot `product.video` iken artık
`Listing Image` galerisini değil `Listing.video_url`u okuyor ve gövdeye
`video` bloğu koyuyor (görsel slotlarının gövdesi ve ETag'i DEĞİŞMEDİ —
`"video"` anahtarı yalnız video slotunda var; 11+16 test yeşil). Sorgu bütçesi
korunuyor: N ilan için 4 sabit sorgu (ilan → varlık → türev → sürüm).

**Gerçek HTTP yanıtı (LST-04043, PASSTHROUGH):**

```json
"video": {
  "asset": "59jmq0pkp0",
  "src": "/files/Evde taze sıkılmış … limon.mp4",       ← passthrough: ham dosya
  "type": "video/mp4",
  "hlsSrc": "",                                          ← 28 sn < 60 sn, HLS yok
  "poster": "/files/media/59jmq0pkp0/3ebd…b12b/poster-720.webp",
  "width": 720, "height": 720, "duration_s": 28.002,
  "lqip": "data:image/png;base64,…"                      ← poster'dan ThumbHash
}
```

`MediaVideo.vue` eşleşmesi satır satır: `src/type/hlsSrc/poster/width/height/
lqip` + `duration_s`. REMUX+HLS gövdesi (h264 `src`, dolu `hlsSrc`) DB
fixture'lı testle sabitlendi (`test_video_slotu_artik_gorsel_dondurmuyor`);
canlıda LST-04419 üzerinden GÖSTERİLEMEDİ çünkü ilan `Pending`/
`storefront_visible=0` — manifest görünmeyen ilana BOŞ döner (görselle aynı
sızıntı kuralı; ölçüldü ve doğru davranış: DEV'deki tek HLS'li video, ilanı
yayına alınana dek vitrine sızmıyor). Dış (YouTube) adresler manifeste girmez;
onlar bugünkü gibi `get_listing_detail.videoUrl`un işi.

## 6. Uçtan uca koşum — kuyruktan HTTP'ye (görev doğrulaması)

Tetik: `maybe_generate_renditions(File)` + commit → RQ `long` worker'ı
(`istoc-dev-queue-long-1`, kod `docker cp` ile eşitlenip yeniden başlatıldı).

| Halka | LST-04419 `9mb.mp4` | LST-04043 `limon.mp4` |
|---|---|---|
| Slot çözümü | `product.video` (ilişkiden — attached NULL) | `product.video` |
| Karar | **REMUX** (`moov_at_end`) | **PASSTHROUGH** (`default`) |
| Birincil | `h264-1280.mp4` 9.622.536 B, **moov BAŞTA** (ölçüldü) | yok (doğru: yeni dosya yazılmaz) |
| Poster | `poster-1280.webp` 9.194 B | `poster-720.webp` 16.912 B (W6-B ile bayt-birebir) |
| HLS | 540 sn > 60 → 3 basamak üretildi, **720p kapıda düştü**, 2 ilan | gerekmedi |
| Media Version | 1280×720, 540,0 sn, lqip dolu | 720×720, 28,002 sn, lqip dolu |
| Job | `success`, `media-video`, `video:{sha}:product.video` | aynı |
| İdempotency | ikinci kanca çağrısı: **enqueue YOK** (ölçüldü) | aynı |

HTTP (gateway üzerinden, `http://istoc.localhost`):

| Adres | Durum |
|---|---|
| `…/h264-1280.mp4` | **200** `video/mp4` 9.622.536 B |
| `…/poster-1280.webp`, `…/poster-720.webp` | **200** `image/webp` |
| `…/hls/master.m3u8` | **200** `application/vnd.apple.mpegurl` (yalnız 360p+480p) |
| `…/hls/v360p/playlist.m3u8` / `seg000.ts` | **200** / **200** `video/mp2t` |
| `…/hls/v720p/playlist.m3u8` | **404** (ilan edilmedi, silindi — istenen) |
| `get_manifest?listing=LST-04043&slot=product.video` | **200**, `video` bloğu dolu |
| `get_manifest?listing=LST-04043` (görsel, regresyon) | **200**, gövde değişmedi |

## 7. Testler

Yeni modül `tests/test_video_servis.py` — **28 test, 6 sınıf** (`bench
run-tests` ile konteynerde): vmaf kapısının dört yüzü + sıra + B-2 geri
çekilmesi (VMAF taklitli — eşiğin iki yakası deterministik; gerçek ölçüm §3),
HLS basamak kapısı (rapor 81 §4'ün GERÇEK sayılarıyla sentetik paket; eşitlik
sınırı; tüm-düşme; ölçüsüz kaynak), köprü kapıları + slot haritası + jpg'nin
video yoluna sapmadığı, worker uçtan uca (gerçek ffmpeg, REMUX/PASSTHROUGH
zincirleri, kanonik adres `parse_rendition_path` ile doğrulanıyor,
idempotency), manifest video gövdesi (REMUX'lu, passthrough'lu, bayrak kapalı,
görsel regresyonu, toplu uç).

| Suit | Sonuç |
|---|---|
| `test_video_servis` (yeni) | **28/28 OK** |
| `test_pipeline_bridge` | **22/22 OK** |
| `test_media_manifest_api` / `test_manifest_batch` | **11/11 / 16/16 OK** |
| `test_video_decision` + `test_video_transcode` | **167/167 OK** |
| `test_video_live_run` | **17/17 OK** |
| Vacuity (HLS kapısı kaldırıldı) | **3 KIRMIZI** → geri konunca yeşil |

Lint: konteynerde/yerelde ruff kurulu değil (rapor 81 ile aynı durum);
`py_compile` tüm dosyalarda OK, tab indent + type hint kurallarına uyuldu.

## 8. Kalan boşluklar / notlar (kırık değil, kayıt)

1. **Önizleme klibi üretim yoluna BAĞLANMADI** (bilinçli): motor hazır
   (`poster.make_preview_clip`) ama hiçbir teslim yüzeyi tüketmiyor
   (`MediaVideo.vue` prop'larında yok). Bağlamak tek fonksiyon; tüketici
   çıkınca yapılmalı.
2. **Karar izi (trace) iş kaydına yazılamıyor** — `Media Processing Job`da
   genel bir alan yok (`error_trace` yalnız hata için). T-071'in "karar job
   kaydına yazılmalı" maddesi şema eklentisi bekliyor.
3. **W6-B'nin geçici çıktıları duruyor:** `files/media/video/{4cacb5898d,
   93144fcb41}/` (414 dosya, ~37 MB) — DB'de kaydı olmayan, kapısız eski
   koşum izleri. Silme kararı kullanıcının (karşı-kanıt olarak da değerliler).
4. **LST-04419 `Pending`** — DEV'deki tek HLS'li video vitrinde görünmüyor;
   manifest bilinçli boş dönüyor. İlan yayına alınınca uç hazır.
5. **Poster, görsel rendition hattından GEÇMİYOR** (tek webp; politika
   `poster_192/poster_1024` profilleri üretilmedi) — T-073'ün "poster srcset
   ile teslim edilsin" maddesinin kalan kısmı.
6. **Konteyner kodu `docker cp` ile eşitlendi** (backend + queue-long,
   restart'lı) — kalıcılık için imaj rebuild gerekir (memory:
   admin-panel/storefront ile aynı durum). Repo çalışma ağacı ile konteyner
   md5 birebir doğrulandı; commit ATILMADI (görev kuralı).
7. **`engine_version` ffmpeg imaj sürümünü taşıyor** — imaj ffmpeg'i değişince
   video version_hash'leri ve adresler zorunlu yenilenir (INV-09'un istediği
   davranış; ama backfill/GC planına not).
8. **`get_manifest_batch` video slotunda da ilan-kırpma/ETag sözleşmesini
   aynen kullanıyor**; vitrin istemcisinin (`manifest.ts`) video bloğunu
   okuması FE işi (paralel ajan/sonraki tur).

## 9. DEV'de bırakılan kalıcı izler

1. Media Asset `3pjpbple42` (9mb.mp4): 1 Version + 3 Rendition (h264/poster/hls),
   `files/media/3pjpbple42/f8de…63c7/` altında h264 + poster + 272 HLS dosyası
   (~24,8 MB); Media Asset `59jmq0pkp0` (limon): 1 Version + 1 Rendition (poster).
2. İki `Media Processing Job` (`success`, `media-video`).
3. Şema: `Media Version.duration_s` kolonu + `Media Rendition.format` `m3u8`
   seçeneği (migrate edildi).
4. Bayraklara DOKUNULMADI (`rendition_on_upload=1`, `active_slots=
   product.image,product.video` — W6-B'nin bıraktığı durum).
5. Kaynak videolar bayt-birebir korunmuş (PASSTHROUGH/REMUX kaynağa yazmaz);
   kuyruk worker'ı ve backend yeniden başlatıldı (kod eşitleme için).
