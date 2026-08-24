# Standart — `product.video` (Ürün tanıtım videosu)

> **Güncel karar — 2026-08-23.** Makine kaynağı
> `tradehub_core/media/pipeline/policy/slots/product-video.json` şemaya
> uyumludur; `standard_status=fixed`, açık soru sayısı 0 ve yükleme tavanı
> 10 MB'tır. `ProductVideoSection` ürün detayına bağlanmıştır. Aşağıdaki
> 2026-08-17 “okunmuyor” notu tarihsel analizdir; `status=draft` yalnız Faz 3
> rollout durumudur.

**Görev:** T-023 · **Tarih:** 2026-08-17 · **Branch:** `medya-motoru-faz0-faz2`
**Politika dosyası:** `tradehub_core/media/pipeline/policy/slots/product-video.json`
**Tarihsel durum:** `draft` — 2026-08-17 anlık görüntüsü
(`tradehub_core/media/upload_policy.py:307-313` — `check()` imzasında slot parametresi yok).

> **Kural 5 uyarısı:** Bu slotta sistemin **asenkron video transcode hattı zaten
> tam olarak kurulu**. `tradehub_core/media/transcode.py` (needs_transcode /
> enqueue_transcode / _run_transcode / maybe_transcode_on_insert) videoları VP9+Opus
> WebM'e normalize ediyor, hedef genişlik **1280**. Bu belge o hattı yeniden
> tasarlamaz; sınırlarını slot sözleşmesine taşır ve **eksik olanı** işaretler.

---

## 1. Kaynak alanlar

| doctype.field | fieldtype | not |
|---|---|---|
| `Listing.video_url` | **Data** (Attach değil) | Panel buraya `upload_file` çıktısını string olarak yazıyor (`admin-panel/frontend/src/views/seller/ListingFormView.vue:4166-4185`). Attach taramasıyla **bulunamaz**. `media/usage.py:34` LIVE_SOURCES'ta kayıtlı |
| `Listing Variant Item.variant_video_url` | **Data** | LIVE_SOURCES'ta **YOK** → silme taramasında "kullanılmıyor" görünür (`docs/reports/00-upload-slot-envanteri.md` §7-B B6) |

Aynı `Data` alanı hem yüklenmiş dosyayı hem YouTube/Vimeo URL'ini tutuyor
(`tradehubfront/src/components/product/ProductVideoSection.ts:31-49` ikisini de
işliyor). Bu standart **yalnız dosya** olan hâli kapsar.

---

## 2. Render konumları ve gerçek CSS kutuları

| # | Render noktası | Dosya:satır | CSS kutu | Oran | Canlı |
|---|---|---|---|---|---|
| V1 | Masaüstü galeri video slaytı | `ProductImageGallery.ts:250-253`, kutu `:248` | 300×300 (1024-1279) · 377×377 (1280-1535) · **502×502** (≥1536) | **1:1** | ✅ |
| V2 | Mobil MediaViewer video slaytı | `MediaViewer.ts:54` | tam viewport genişliği × aynı yükseklik: 360×360 … **1023×1023** | **1:1** | ✅ |
| V3 | Galeri video karosu | `ProductImageGallery.ts:107` → `:103` | 70×70 | 1:1 | ✅ |
| V4 | Lightbox video karosu | `ProductImageGallery.ts:111-115` | 76×76, `<960px` viewport'ta 68×68 | 1:1 | ✅ |
| V5 | `ProductVideoSection` 16:9 bloğu | `ProductVideoSection.ts:79` (`padding-top:56.25%`) | — | 16:9 | ❌ **ÖLÜ** |

V1/V2 kutu genişlikleri `docs/reports/03-render-envanteri.md` §3.5 ve §3.6'dan.
V2 kutusu ürün detay masaüstü/mobil eşiği 1024px olduğu için 1023'te kesiliyor
(`tradehubfront/src/pages/product-detail.ts:291`).

### V5 ölü mü? — kanıt

```bash
grep -rn "ProductVideoSection" /Users/ahmet/Desktop/istoc/tradehubfront/src
```

Çıktıdaki tüm satırlar ya kendi dosyası, ya `components/product/index.ts:21-24`
(barrel dışa aktarımı), ya da `toVideoEmbedHtml` içe aktarımı
(`alpine/product.ts:25`, `components/product/MediaViewer.ts:14`).
**`ProductVideoSection()` fonksiyonunu çağıran hiçbir sayfa yok.**
`pages/product-detail.ts:248-275` masaüstü düzeninde de geçmiyor.

### Sonuç: 16:9 video / 1:1 kutu çelişkisi

Video bugün **yalnız kare kutuda** gösteriliyor. 502×502'lik masaüstü kutusunda
16:9 bir video 502×282 çizilir, üstte ve altta toplam **220 px siyah** kalır
(`MediaViewer.ts:54` `bg-black`; `ProductVideoSection.ts:64`
`object-contain bg-black`). Bu standart çelişkiyi çözmez — **kaydeder**, çünkü
çözümü bir tasarım kararıdır (ya 1:1 video istenecek ya oranlı kutu mount
edilecek).

---

## 3. DPR ihtiyacı → minimum piksel

Videoda DPR mantığı görselden farklıdır: tarayıcı video karesini CSS kutusuna
ölçekler, `srcset` yoktur. Yine de kaynak çözünürlük kutu × DPR'ın altına
düşerse görünür yumuşama olur.

| Kutu (CSS px) | @1x | @2x | @3x | Kaynak |
|---|---|---|---|---|
| 300 (masaüstü, 1024-1279) | 300 | 600 | 900 | `03-render-envanteri.md` §3.5 |
| 377 (masaüstü, 1280-1535) | 377 | 754 | 1131 | aynı |
| **502** (masaüstü, ≥1536) | 502 | **1004** | 1506 | aynı |
| 360 / 390 / 430 (telefon) | 430 | 860 | **1290** | §3.6 |
| 768 (tablet dikey) | 768 | **1536** | 2304 | §3.6 |
| 1023 (tablet yatay sınırı) | 1023 | 2046 | 3069 | §3.6 |

**Türetme:** Sunucunun hedefi bugün **1280** (`transcode.py:242`
`scale='min(1280,iw)':-2`). Bu değer masaüstünün en büyük @2x talebini (1004)
ve telefonun @3x talebini (1290, %1 eksik) pratikte karşılıyor; **tablet
@2x'i (1536) karşılamıyor.** Yani ürün videosu geniş tablette 1280 kaynakla
1536 kutuya %20 büyütülerek çiziliyor.

Bu standart 1280'i **değiştirmiyor** — mevcut hedef kodda ölçülmüş bir kararla
(client mediabunny genelde 1280'e sıkıştırıyor, `transcode.py:55-60` yorumu)
seçilmiş. Tablet farkı `open_questions`'a yazıldı.

- **Minimum kabul:** kısa kenar **360** (640×360). Türetme: en küçük kutu 300 CSS
  px, DPR2 → 600 genişlik → 16:9'da kısa kenar 338 → standart basamak 360.
- **Hedef / master:** **1280** uzun kenar (`transcode.py:242`).
- **Maksimum:** 1280 — üstü sunucuda zaten indiriliyor.

### Süre tavanı — türetilmiş, ölçülmedi

Kodda **açık süre kontrolü yok**. Ama iki mevcut sayı birlikte zımni bir sınır
üretiyor:

```
accept.max_bytes = 10 MB = 10 · 1024 · 1024 · 8 = 83.886.080 bit
transcode.py:61  NEEDS_TRANSCODE_MAX_BITRATE = 2.500.000 bps
83.886.080 / 2.500.000 = 33,5 saniye
```

Yani **10 MB tavanı, 2,5 Mbps'lik bir videoda ~33 saniyelik bir süre sınırıdır.**
Standart bunu `warn` olarak kaydeder, ret etmez.

---

## 4. Kabul kuralları ve mevcut kodda karşılığı

| Kural | Değer | Kaynak | Bugün var mı |
|---|---|---|---|
| Uzantı | `.mp4 .webm .mov .m4v` | `transcode.py:67` VIDEO_EXTENSIONS; `upload_policy.py:63` | Medya uçlarında ✅, `upload_file` yolunda ❌ |
| Boyut | **10 MB** | `ListingFormView.vue:4169` | İstemcide ✅, sunucuda 200 MB (`upload_policy.py:69`) |
| Genişlik | ≤1280 (normalize) | `transcode.py:242` | ✅ auto_fix |
| Bitrate | ≤2,5 Mbps (üstü kuyruğa) | `transcode.py:61` | ✅ |
| Erişim | `is_private=0` **zorunlu** | `transcode.py:194` | ❌ sessizce atlanıyor |
| Oran | 16:9 önerilir | `ProductVideoSection.ts:79`, `StoreHeader.ts:296` | ❌ hiç kontrol yok |
| Adet | 1 (alan tekil) | `00-upload-slot-envanteri.md` §2 | yapısal ✅ |

### Aynı sınır için dört farklı sayı

| Kaynak | Değer |
|---|---|
| `upload_policy.py:69` `MAX_BYTES[KIND_VIDEO]` | **200 MB** |
| `upload_policy.py:239-259` `platform_limit()` Frappe varsayımı | **25 MB** |
| `ListingFormView.vue:4169` istemci | **10 MB** |
| `brand.json` / `seller_gallery_image.json` alan açıklamaları | **10 MB** |

`docs/reports/00-upload-slot-envanteri.md` §7-B B7. Standart en sıkı olanı
(10 MB) alır — **yeni sayı üretilmedi.**

---

## 5. Profiller

`profiles[]` yalnız **poster** görsellerini içeriyor:

| Profil | Genişlik | Biçim | Karşıladığı kutu | Türetme |
|---|---|---|---|---|
| `poster_192` | 192 | webp | V3 (70px), V4 (76px) | max(76·2=152, 70·2=140) = 152 → 192 |
| `poster_1024` | 1024 | avif+webp | V1 (502px @2x) | 502·2 = 1004 → 1024 |

### ŞEMA BOŞLUĞU

Gerçek video rendition'ı (**1280 genişlik, VP9 video + Opus ses, WebM kabı**,
`transcode.py:243-246`) `profiles[]` içinde **ifade edilemedi**:
`tradehub_core/media/pipeline/policy/schema/slot-policy.schema.json` içinde
`profiles[].formats` enum'u yalnız `avif|webp|jpeg|png` kabul ediyor, ve
`master.format` enum'unda `webm` yok. Bu yüzden `master.format` = `"preserve"`
yazıldı ve `sources.master.format` alanına gerekçesi kaydedildi.

**Şema v1.1'de yapılması gereken:** `profiles[].formats` ve `master.format`
enum'larına video biçimleri (`webm`, `mp4`) ve `profiles[].codec` alanı eklenmesi.
Bu belge şema dosyasını **değiştirmedi** (kural 1).

---

## 6. İhlal aksiyonu

| Kural | Aksiyon | Bugün |
|---|---|---|
| Uzantı listede değil | `reject` | medya ucunda ✅ |
| Boyut > 10 MB | `reject` | istemcide ✅ / sunucuda 190 MB fark |
| Genişlik > 1280 | `auto_fix` (küçült) | ✅ `transcode.py:242` |
| Bitrate > 2,5 Mbps | `auto_fix` (kuyruğa al) | ✅ `transcode.py:116` |
| `is_private=1` | `warn` | ❌ **sessiz** — `transcode.py:194` return ediyor |
| ffprobe okunamadı | `review` (güvenli taraf: transcode et) | ✅ `transcode.py:101-106` + `log_error` |
| Sahibi satıcı değil ve Listing'e bağlı değil | `warn` | ❌ **sessiz** — `transcode.py:201-204` |
| Oran 16:9 değil | `warn` | ❌ |

`sessiz` işaretli iki satır bu slottaki en somut eksik: video normalize
edilmiyor ve kullanıcı bunu **hiçbir yerde göremiyor**.

---

## 7. Zaten çözülmüş — üstüne yazılmayacak

1. **Asenkron transcode hattı.** RQ `long` kuyruğu, 1700 sn ffmpeg timeout
   (`transcode.py:50`), `nice -n 10` (`:236`), 1800 sn kuyruk timeout (`:159`).
2. **Koşullu transcode.** Client (mediabunny) çoğu videoyu zaten sıkıştırıyor;
   sunucu yalnız eşiği aşanı işliyor (`needs_transcode`, `:70-116`). Gerekçe
   `transcode.py:8-15`'te yazılı.
3. **İdempotanlık.** Aynı dosya `upload_media` ve global `after_insert`
   kancasından iki kez tetiklenirse ikinci kez kuyruğa girmiyor (`:139-140`).
4. **Global güvenlik ağı.** `maybe_transcode_on_insert` (`:165-205`) ürün
   formunun genel `upload_file` yolunu da kapsıyor; kapsam bilerek dar
   (yalnız video uzantıları, yalnız public, yalnız satıcı veya Listing eki).
5. **Yerinde yazma.** `os.replace(dst_path, src_path)` (`:251`) — `file_url`
   sabit kalıyor, `Listing` referansları kırılmıyor.
6. **Yarım dosya yazılmıyor.** ffmpeg çıktısı geçici `.transcoding.webm`
   dosyasına gidiyor (`:230`), başarıda takas ediliyor.
7. **Durum alanı ve panel entegrasyonu.** `File.th_media_video_status`
   (processing/ready/failed), panel `media/inventory.py:239,261`'den okuyor;
   `th_optimized_at` da damgalanıyor (`:252-255` yorumu).
8. **Yedek/geri yükleme farkındalığı.** `media/backup.py:79-84` durum alanını
   yedekliyor; `media/restore.py:198` + `flags.th_skip_transcode`
   (`transcode.py:191-192`) geri yüklenen dosyayı ezmiyor.
9. **Parçalı yükleme.** `media/chunked.py`, eşik 8 MB
   (`upload_policy.py:89`) — 10 MB'lık video zaten parçalı gidiyor.
10. **İstemci sıkıştırma.** `admin-panel/frontend/src/lib/media/compress.js`
    `prepareVideo` → mediabunny ile WebM.

---

## 8. ÜRETİMDE DOĞRULANMALI

Bu ortamda **hiçbir ölçüm yapılmadı** — Docker kapalı, üretim veritabanına ve
canlı siteye erişim yok. Aşağıdakiler çalıştırılacak tam komutlardır.

### 8.1 ffmpeg/ffprobe imajda var mı

Yoksa `needs_transcode` her videoda `log_error` yazıp `True` dönüyor
(`transcode.py:101-106`) ve `_run_transcode` `FileNotFoundError` alıyor →
**hiçbir video normalize edilmiyor.**

```bash
docker compose exec backend which ffmpeg ffprobe
docker compose exec backend ffmpeg -version | head -1
docker compose exec backend ffmpeg -encoders 2>/dev/null | grep -E "libvpx-vp9|libopus"
```

### 8.2 Video durum dağılımı

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select coalesce(th_media_video_status,'(bos)') durum, count(*) adet
  from tabFile
  where lower(file_name) regexp '\\.(mp4|webm|mov|m4v)$'
  group by 1 order by 2 desc
""", as_dict=True))
PY
# 'failed' > 0 ise error log'a bak:
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.get_all("Error Log", filters={"error": ["like", "%transcode%"]},
      fields=["creation","method"], limit_page_length=20))
PY
```

### 8.3 Gerçek çözünürlük / bitrate / süre dağılımı

Bu belgedeki hiçbir çözünürlük veya süre değeri ölçülmüş değil.

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe, json, os, subprocess
rows = frappe.db.sql("""
  select name, file_url from tabFile
  where lower(file_name) regexp '\\.(mp4|webm|mov|m4v)$' and is_private = 0
""", as_dict=True)
for r in rows:
    p = frappe.get_site_path("public", r.file_url.lstrip("/"))
    if not os.path.exists(p): continue
    try:
        out = subprocess.run(["ffprobe","-v","error","-select_streams","v:0",
            "-show_entries","stream=width,height,bit_rate,codec_name:format=duration,bit_rate,size",
            "-of","json",p], capture_output=True, timeout=20, check=True).stdout
        print(r.file_url, out.decode()[:300])
    except Exception as e:
        print(r.file_url, "HATA", e)
PY
```

Çıkarılacak sayılar:
1. Uzun kenarı **tam 1280** olan oranı → transcode'un tavana dayadığı pay.
2. **Süre** medyan / p95 → 33 sn'lik zımni sınırın gerçekten bağlayıcı olup
   olmadığı.
3. **Codec** dağılımı → kaçı VP9'a dönmüş, kaçı hâlâ H.264.
4. **Bitrate** medyan → `transcode.py:61` eşiğinin doğru yerde olup olmadığı.

### 8.4 `Listing.video_url` — dosya mı URL mi

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print(frappe.db.sql("""
  select case
    when video_url like '/files/%' or video_url like '/private/files/%' then 'DOSYA'
    when video_url like '%youtu%' then 'YOUTUBE'
    when video_url like '%vimeo%' then 'VIMEO'
    else 'DIGER' end tur, count(*) adet
  from tabListing where ifnull(video_url,'') != '' group by 1
""", as_dict=True))
# Varyant videoları:
print(frappe.db.count("Listing Variant Item", {"variant_video_url": ["is","set"]}))
PY
```

Yalnız `DOSYA` satırı bu politikanın kapsamındadır.

### 8.5 Tablet @2x farkı gerçekten sorun mu

```js
// 768px genişlikte bir tablette, ürün detay sayfasında DevTools konsolu:
(() => { const v = document.querySelector('#pdm-gallery-wrap video, #gallery-main-image video');
  return v ? { kutu: v.getBoundingClientRect().width, kaynak: v.videoWidth,
               dpr: devicePixelRatio,
               buyutme: (v.getBoundingClientRect().width * devicePixelRatio / v.videoWidth).toFixed(2) }
           : 'video slaytı yok'; })()
```

`buyutme > 1.0` ise 1280 hedefi o cihazda yetersiz demektir.

### 8.6 Ölçülemeyen ve kasıtlı boş bırakılanlar

| Konu | Neden |
|---|---|
| Video başına gerçek bant maliyeti | Ağ/CDN ölçümü gerektirir |
| Transcode kuyruğunun gerçek gecikmesi | Worker metrikleri gerektirir |
| Kullanıcı DPR dağılımı | RUM/analytics erişimi gerektirir |
| 10 vs 200 MB'dan hangisinin doğru olduğu | Ürün kararı, ölçüm değil |
