# Medya Sıkıştırma + Kota + URL Güvenliği — Tasarım

**Tarih:** 2026-08-13
**Kapsam:** 3 repo (tradehub_core, tradehubfront, admin-panel) + docker
**Linear:** TUR-128, TUR-127, TUR-297, TUR-296, TUR-123 (A) · TUR-139 (B) · TUR-141, TUR-130, TUR-126, TUR-124 (C)
**Sınıflandırma:** Architectural (yeni alt-sistem, çok bileşenli)

---

## 1. Problem ve hedef

Yüzlerce satıcı her ürüne ham görsel/video yüklüyor. Bugünkü akışta dosyalar
sunucuya byte-for-byte gidiyor; optimizasyon yalnızca admin tetiklemeli, senkron
ve WebP'ye çevirmeyen bir yol. Bu üç riski doğuruyor:

1. **Maliyet/çökme:** yüzlerce eşzamanlı ham yükleme + sunucu-taraflı optimize =
   CPU ve depolama patlaması.
2. **Kotasız büyüme:** satıcı başına depolama sınırı *ölçülüyor ama
   engellenmiyor* (metin'in `files.py`'ı `Marketplace Settings` global ayarını
   okuyor, enforce etmiyor).
3. **Enumeration açığı:** public görsellerin ~%50'si tahmin edilebilir isimli
   (`0505.jpg`); canlıda kör tahminle toplu çekilebiliyor (12 denemede 4 isabet).

**Hedef:** Ağır işi satıcının tarayıcısına taşı (WebP/WebM'e çevir + küçült),
sunucuda garanti altına al, satıcı-başına kotayı gerçekten uygula, ve dosya
isimlerini tahmin edilemez yap — hepsini mevcut URL'leri kırmadan.

## 2. Başlangıç durumu (metin'in 2026-08-13 commit'i sonrası)

- `api/seller_media.py` + `media/{seller_media,ownership,backup,restore,files,
  metadata}.py`: satıcı kütüphanesi CRUD, `owner`-bazlı izolasyon, 7 `th_media_*`
  metadata alanı, site-seviyesi backup. **Sıkıştırma yok, kota enforcement yok,
  isimlendirme güvenliği yok.**
- `upload_media`: base64 içerik, uzantı allow-list + 25MB dosya-başı limit,
  dosyayı verbatim kaydediyor.
- Bu kod dev'de **deploy değil** (konteyner alpha.6, repo alpha.11).
- `media/engine.py`: Pillow resize/recompress var, **format koruyor (WebP'ye
  çevirmiyor)** — bu bilinçli (file_url değişmesin diye).
- ffmpeg dev backend imajında **YOK**.

## 3. Mimari — client/server sorumluluk (TUR-123)

```
SATICI TARAYICISI                     SUNUCU (Frappe)
─────────────────                     ───────────────
Görsel → browser-image-compression    upload_media:
  → WebP  (Safari: JPEG q85)           ① reject_unsafe_files (mevcut)
Video → mediabunny                     ② KOTA kapısı (B) ──aşımda throw──► dur
  → WebM  (Safari: H.264 MP4)          ③ write_file hook: hash rename (C)
  ↓ küçülmüş byte (base64)             ④ engine.py: garanti-WebP (A-server)
─────────── upload_media ──────────►   ⑤ video ise → ffmpeg kuyruğu (A-server)
```

**İlke:** Ağır iş tarayıcıda. Sunucu üç şey yapar: (a) client'ın beceremediğini
tamamla (Safari JPEG→WebP), (b) güvenlik/kota, (c) video transcode (tarayıcıda
garanti olmadığı için async normalize).

## 4. Parça A — Sıkıştırma pipeline (WebP/WebM)

### A-client (storefront + panel)
- **Görsel:** `browser-image-compression@2.0.2` (MIT, web worker). `maxWidthOrHeight:
  1920, maxSizeMB: 0.5, initialQuality: 0.8, fileType: 'image/webp'`.
  - **Safari tuzağı:** `canvas.toBlob('image/webp')` Safari/iOS/Capacitor'da
    desteklenmiyor → çıktı `type !== 'image/webp'` ise JPEG q85 fallback; sunucu
    WebP'ye tamamlar. Feature-detect bir kez çalışır.
- **Video:** `mediabunny@1.53.1` (MPL-2.0). `getEncodableVideoCodecs()` probe →
  Chrome/Firefox VP9 WebM, Safari H.264 MP4; 720p, ~2Mbps. Süre ≤60sn, boyut
  ≤100MB client doğrulaması. Probe başarısızsa orijinali yükle + `needs_transcode`.
- **Yeni dosya:** `tradehubfront/src/lib/media/compress.ts` (ortak) + panelde eşi.
  Mevcut `upload-ui/uploader.ts` ve `useSellerMedia.js` bu fonksiyondan geçer.
- **Kütüphaneler projede kurulu değil** — kod yazarken context7'den güncel API
  teyit edilecek (CLAUDE.md kuralı).

### A-server (backend)
- `engine.py`: mevcut format-koruma kuralını **kırmadan** genişlet — yeni bir
  `to_webp(bytes, quality=80)` yolu; upload_media'da client'tan gelen görsel WebP
  değilse (Safari JPEG) burada WebP'ye çevir. Orijinal file_url'e dokunma
  mantığı korunur (türev/garanti ayrı).
- **Video:** yeni `media/transcode.py` — `frappe.enqueue(queue="long",
  timeout=1800)` → ffmpeg subprocess (VP9 WebM ya da H.264). `Listing.video_url`
  yerine File-tabanlı bir durum alanı (`processing/ready/failed`) tutulur.
- **Docker:** ffmpeg imajda yok → `docker/` Dockerfile'ına `ffmpeg` eklenecek
  (deploy dokunuşu; video parçasının önkoşulu).

## 5. Parça B — Kota enforcement (TUR-139)

- metin'in `files.py`'daki `Marketplace Settings.media_storage_quota_bytes` global
  ayarını **entitlement sistemine taşı**: `quota.max_storage_mb` anahtarı.
  - `fixtures/feature_catalog.json` → yeni Quota kaydı (default 500).
  - **Seed patch:** tüm `Subscription Plan.quota_limits`'e değer bas. *Atlanırsa
    `within_quota` None→False döner ve tüm satıcılar bloklanır* — kritik.
- **Enforcement:** `entitlement/checks.py` → `check_media_storage_quota(doc)`;
  `hooks.py`'daki `File.before_insert` tek-string'i **listeye** çevirip ekle.
  Muafiyet: `EXCLUDED_DOCTYPES` (KYB/KYC satıcıyı kilitlemesin) + bulk flag'ler.
- **Kullanım sayacı:** metin'in `files.storage_usage(store)` fonksiyonu (dedup'lu,
  `file_url` bazında) aynen kullanılır — yeniden yazılmaz.
- **Panel bug:** `MediaFilterRail.vue` `quotaBytes=null` gelince `NaN%` gösteriyor
  → null-kota durumu düzeltilir.

## 6. Parça C — URL isimlendirme / enumeration güvenliği (TUR-141/130/126/124)

- **Yeni dosya:** `media/naming.py` — Frappe'nin `write_file` hook'una takılır
  (`hooks.py`). Yeni yüklemeler `<sha256(içerik)[:32]>.<ext>` olur. `/files/`
  prefix + uzantı korunur → **mevcut 4.324 URL kırılmaz** (sadece yeni yüklemeler).
- **Nginx hızlı kazanımlar** (`docker/nginx/*`): `/files/`'a `X-Robots-Tag:
  noindex` (Google indekslemesini kapat), `limit_req` (sweep'i dakikalardan günlere
  çıkar).
- **DateTime (TUR-124):** yükleme zamanı `File.creation` (mevcut) üzerinden;
  API çıktısı ISO-8601 UTC standardına hizalanır. İsimde tarih gömülmez.
- **Private erişim (TUR-126):** mevcut Frappe permission katmanı zaten doğru
  çalışıyor (Guest→403); bu turda imzalı-URL eklenmez (YAGNI) — sadece karar
  belgelenir.
- **Kapsam dışı:** eski 2166 tahmin-edilebilir ismin retro-rename'i (riskli
  backfill, ~2400 referans) — ayrı iş olarak ertelenir.

## 7. Modül/dosya sahipliği (çakışma haritası)

| Parça | Yeni dosya (çakışmasız) | Dokunulan mevcut dosya |
|---|---|---|
| A-client | `tradehubfront/src/lib/media/compress.ts` + panel eşi | `upload-ui/uploader.ts`, `useSellerMedia.js` |
| A-server | `tradehub_core/media/transcode.py` | `media/engine.py`, `api/seller_media.py`, docker/Dockerfile |
| B-kota | `entitlement/checks.py`(+fn), `fixtures/feature_catalog.json`, yeni patch | `media/files.py`, `hooks.py`, `MediaFilterRail.vue` |
| C-URL | `tradehub_core/media/naming.py` | `hooks.py`, `docker/nginx/*` |

**İki paylaşılan dosya:** `hooks.py` (B + C), `engine.py` (A-server tek). Bunlar
Faz 0'da tek elden iskeletlenip, agent'lar kendi satırlarına yazar.

## 8. Paralel agent stratejisi

- **Faz 0 (ana oturum, sıralı):** Paylaşılan iskelet — `hooks.py`'daki
  `File.before_insert`'i listeye çevir, `write_file` hook satırını ekle, boş
  stub'lar (`naming.py`, `transcode.py`, `compress.ts`). Böylece paralel agent'lar
  çakışan satıra değil kendi dosyasına yazar.
- **Faz 1 (4 paralel agent, git worktree izolasyonu):** A-client, A-server,
  B-kota, C-URL. Her biri kendi worktree'sinde TDD ile, kendi testini geçirir.
- **Faz 2 (ana oturum):** worktree'leri sırayla merge, entegrasyon testi, build.

## 9. Test / user journey

Her parça bitince tek dokümanda "yapılanlar + nasıl test edilir":
- (a) önce çalıştırılacak komutlar (npm build, bench migrate, gerekiyorsa imaj
  rebuild — çünkü dev'de HMR yok, `deploy'a dokunma` tercihi test anında
  build/migrate gerektirir);
- (b) satıcı adımları: foto yükle → DevTools Network'te giden dosyanın WebP +
  küçük olduğunu gör → kota çubuğu arttı → URL hash-isimli → kotayı doldur →
  yükleme engellendi → video yükle → "işleniyor→hazır" gördü;
- (c) her adımın beklenen sonucu.

## 10. Kütüphane kararları

| | Kütüphane | Sürüm | Lisans | Boyut |
|---|---|---|---|---|
| Görsel | browser-image-compression | 2.0.2 | MIT | ~19KB |
| Video | mediabunny | 1.53.1 | MPL-2.0 | ~20KB |
| Sunucu görsel | Pillow (mevcut) | — | — | — |
| Sunucu video | ffmpeg (imaja eklenecek) | — | — | — |

Elenenler: ffmpeg.wasm (31MB + COOP/COEP tüm siteyi kırar), webm/mp4-muxer
(deprecated), jSquash (gereksiz +300KB, sunucu fallback yeterli).

## 11. Riskler ve kararlar

- **ffmpeg imaja eklenmeli** → video parçası deploy dokunuşu gerektirir; "deploy'a
  dokunma" tercihiyle çelişir. Video kodu yazılır+test edilir ama canlı doğrulama
  imaj rebuild sonrası olur.
- **Safari WebP/WebM garantisi yok** → fallback zinciri (JPEG/MP4 + sunucu) şart;
  her tarayıcıda test edilmeli.
- **Kota seed patch'i atlanırsa herkes bloklanır** → patch zorunlu, migrate testi.
- **metin ile koordinasyon:** B, metin'in `files._quota()`'sını değiştirecek;
  A-server onun `upload_media`'sına transform ekleyecek. Merge öncesi haber verilir.

## 12. Kapsam dışı (YAGNI)

- Eski dosya isimlerinin retro-rename'i (ayrı riskli iş).
- İmzalı/tokenli private URL (mevcut permission yeterli).
- Panelde manuel crop UI (Cropper.js) — ayrı iş.
- WordPress import, CDN entegrasyonu (ayrı TUR'lar).
