# Medya Pipeline — Test User Journey

> Bu doküman: (1) yapılanların özeti, (2) test için önce çalıştırılacak komutlar,
> (3) satıcı olarak adım adım test senaryoları + beklenen sonuçlar.
> Branch: `ahmet` (üç repo). Tarih: 2026-08-13.

---

## 1. Ne yapıldı (özet)

Dört parça, dört iş paketi:

| Parça | Ne yapar | Nerede |
|---|---|---|
| **A-client (WP1)** | Satıcı görsel/video yüklerken TARAYICIDA WebP/WebM'e çevirip küçültür | `tradehubfront/src/lib/media/compress.*`, `admin-panel/.../lib/media/compress.js`, `uploader.ts`, `useSellerMedia.js` |
| **A-server (WP2)** | Sunucuda garanti-WebP (Safari JPEG'i tamamlar, alfa korur) + video async ffmpeg transcode | `tradehub_core/media/pipeline.py` (`to_webp`), `media/transcode.py`, `api/seller_media.py` |
| **B-kota (WP3)** | Satıcı-başına depolama kotasını gerçekten uygular (aşınca yüklemeyi reddeder) | `entitlement/checks.py`, `media/files.py`, `fixtures/feature_catalog.json`, seed patch |
| **C-URL (WP4)** | Yeni yüklemeleri içerik-hash'iyle adlandırır (URL'den tahmin edilemez) + nginx noindex/rate-limit | `media/naming.py`, `hooks.py`, `docker/nginx/storefront.local.template` |

**Akış:** Satıcı foto seçer → tarayıcı WebP'ye çevirip küçültür → sunucu kotayı
kontrol eder (aşımda reddeder) → dosyayı hash-isimle kaydeder → görsel WebP değilse
(Safari) sunucu tamamlar. Video → "işleniyor" → ffmpeg → "hazır".

---

## 2. Test etmeden ÖNCE çalıştır

> **Not:** Dev'de HMR yok (nginx `dist/` serve ediyor) ve backend imajı bind-mount
> değil — kod değişikliğini canlıda görmek için build + migrate ŞART. Bu adım "deploy
> dokunuşu" ama testin önkoşulu.
>
> ⚠️ **RELEASE-GATE (kritik):** `docker/` klasörü git repo DEĞİL. WP4'ün nginx
> sertleştirmesi (`nginx/storefront.local.template`: X-Robots-Tag noindex + limit_req)
> ve WP2'nin `ffmpeg` kurulumu (`backend.Dockerfile`) **on-disk** duruyor, versiyon
> kontrolünde DEĞİL — temiz bir deploy'da KAYBOLUR. Prod'a giderken bu iki değişikliği
> deploy runbook'una elle taşı, yoksa URL-güvenliği ve video özellikleri prod'da
> devreye girmez.
>
> ⚠️ **RELEASE-GATE:** Video transcode gerçek ffmpeg ile hiç çalıştırılmadı (testte
> mock). ffmpeg imaja eklendikten sonra bir kez gerçek video ile smoke test yap
> (Senaryo 4) — `processing→ready` geçişi ve atomik dosya değişimi.

```bash
# --- 1) BACKEND: imaj rebuild (ffmpeg dahil) + patch migrate ---
cd /Users/ahmet/Desktop/istoc/docker
docker compose build backend            # ffmpeg backend.Dockerfile'a eklendi
docker compose up -d backend
docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate
# migrate şu patch'leri uygular: v15_9_15 (metadata), v15_9_16 (video durum),
# v15_9_17 (kota seed — TÜM planlara quota.max_storage_mb yazar)
docker exec istoc-dev-backend-1 bench --site istoc.localhost clear-cache

# --- 2) STOREFRONT: build (+ imaj rebuild, dist bind-mount değil) ---
cd /Users/ahmet/Desktop/istoc/tradehubfront
npm run build
cd /Users/ahmet/Desktop/istoc/docker && docker compose build storefront && docker compose up -d storefront

# --- 3) PANEL: build ---
cd /Users/ahmet/Desktop/istoc/admin-panel/frontend
npm install && npm run build
cd /Users/ahmet/Desktop/istoc/docker && docker compose build admin-panel && docker compose up -d admin-panel

# --- 4) ffmpeg imajda mı doğrula ---
docker exec istoc-dev-backend-1 which ffmpeg   # /usr/bin/ffmpeg dönmeli
```

**Doğrulama (deploy sonrası, tek seferlik):**
```bash
# kota anahtarı tüm planlara işlendi mi?
docker exec istoc-dev-backend-1 bench --site istoc.localhost console <<'PY'
import frappe; frappe.init(site="istoc.localhost"); frappe.connect()
for p in frappe.get_all("Subscription Plan", pluck="name"):
    ql = frappe.db.get_value("Subscription Plan", p, "quota_limits")
    print(p, "quota.max_storage_mb" in (ql or ""))
PY
```

---

## 2.5. Otomatik entegrasyon testi (deploy'suz, hızlı ilk kanıt)

Manuel senaryolardan önce, dört WP'nin birlikte çalıştığını doğrulayan uçtan
uca test hazır — build/deploy gerektirmez:

```bash
docker exec istoc-dev-backend-1 bench --site istoc.localhost run-tests \
  --module tradehub_core.tests.test_media_pipeline_integration
```
**Beklenen:** `Ran 5 tests ... OK` — görsel zinciri (hash+WebP), kota reddi,
KYB muafiyeti, video kuyruğu, hash dedup. (Bu test 2026-08-13'te 5/5 geçti.)

> ⚠️ Bu test tek başına çalıştırılmalı. `test_media_quota.py` ile AYNI `bench
> run-tests --app` çağrısında çalıştırma — o dosya global `frappe` stub'ı yükleyip
> aynı process'teki diğer testleri kırıyor (izole düzeltme bekleyen test-borcu).

## 3. Satıcı test senaryoları

Panel: satıcı olarak giriş → **Medya Kütüphanesi** (`/media-library`).
Tarayıcı DevTools → Network sekmesi açık olsun.

### Senaryo 1 — Görsel sıkıştırma + WebP (WP1 + WP2)
1. Medya Kütüphanesi'nde bir ürün fotoğrafı yükle (büyük bir JPEG/PNG seç, ör. 3-5 MB telefon fotoğrafı).
2. **Network'te** `upload_media` isteğine bak → gönderilen `content` (base64) **orijinalden çok küçük** olmalı.
   - **Beklenen:** 4 MB foto ~300-500 KB olarak gidiyor (client küçülttü + WebP).
3. Yükleme bitince kütüphanedeki dosyaya tıkla → detay panelinde boyut/tip.
   - **Beklenen (Chrome/Firefox):** dosya `.webp` uzantılı, küçük.
4. Sunucuda doğrula:
   ```bash
   docker exec istoc-dev-backend-1 sh -c 'ls -la /home/frappe/frappe-bench/sites/istoc.localhost/public/files/ | tail -5'
   ```
   - **Beklenen:** son yüklenen dosya `.webp`, adı 32-hex hash.

### Senaryo 2 — URL tahmin-edilemezliği (WP4)
1. Senaryo 1'de yüklenen dosyanın `file_url`'una bak (detay panelinde ya da Network yanıtında).
   - **Beklenen:** `/files/3f9a2b...c1.webp` gibi — `0505.jpg`/`urun-foto.jpg` DEĞİL.
2. Eski bir URL hâlâ çalışıyor mu (kırılmadı):
   ```bash
   curl -so /dev/null -w "%{http_code}\n" http://istoc.localhost/files/0505.jpg   # mevcut eski dosya
   ```
   - **Beklenen:** `200` (eski URL'ler korundu).
3. Yeni dosyanın noindex başlığı:
   ```bash
   curl -sI http://istoc.localhost/files/<yeni-hash>.webp | grep -i x-robots
   ```
   - **Beklenen:** `X-Robots-Tag: noindex`.

### Senaryo 3 — Kota enforcement (WP3)
1. Medya Kütüphanesi'nde depolama çubuğuna bak (filtre rayında).
   - **Beklenen:** gerçek kullanım (ör. "12 MB / 500 MB") — `NaN%` YOK.
2. Kotayı düşür (test için) ve doldur:
   ```bash
   # test satıcısının planında kotayı 1 MB yap, sonra >1MB yüklemeyi dene
   docker exec istoc-dev-backend-1 bench --site istoc.localhost console <<'PY'
import frappe, json; frappe.init(site="istoc.localhost"); frappe.connect()
# <PLAN> yerine test satıcısının planı
p="<PLAN>"; ql=json.loads(frappe.db.get_value("Subscription Plan",p,"quota_limits") or "{}")
ql["quota.max_storage_mb"]=1; frappe.db.set_value("Subscription Plan",p,"quota_limits",json.dumps(ql))
frappe.db.commit()
PY
   ```
   Panelden kotayı aşacak bir dosya yükle.
   - **Beklenen:** yükleme **reddedilir**, Türkçe mesaj: "Depolama kotanız doldu...".
3. KYB belgesi yükleme kotadan etkilenmemeli (muaf).

### Senaryo 4 — Video async transcode (WP2)
1. Medya Kütüphanesi'nde bir video (mp4, <60sn, <100MB) yükle.
2. Yükleme bitince dosyanın durumu:
   - **Beklenen:** önce **"işleniyor"** (`processing`), ffmpeg bitince **"hazır"** (`ready`).
   ```bash
   docker exec istoc-dev-backend-1 bench --site istoc.localhost console <<'PY'
import frappe; frappe.init(site="istoc.localhost"); frappe.connect()
print(frappe.get_all("File", filters={"th_media_video_status":["!=",""]},
      fields=["file_name","th_media_video_status"], order_by="creation desc", limit=3))
PY
   ```
3. Worker'ın çalıştığını doğrula: `docker logs istoc-dev-queue-long-1 --tail 20`.

### Senaryo 5 — Safari/iOS fallback (WP1 + WP2)
1. **Safari veya iPhone**'da panele gir, görsel yükle.
2. Network'te `upload_media` içeriği → Safari WebP encode edemez, **JPEG** gider.
   - **Beklenen:** client JPEG q85 gönderir (yine küçülmüş).
3. Sunucudaki dosyaya bak:
   - **Beklenen:** sunucu (`engine.to_webp`) JPEG'i **WebP'ye tamamlamış** → diskte `.webp`.

### Senaryo 6 — Kimlik belgesi sıkışTIRILMAZ (WP1 güvenlik)
1. KYC akışında kimlik belgesi (jpg fotoğrafı) yükle.
2. Network'te giden dosya:
   - **Beklenen:** **orijinal boyutunda, sıkışTIRILMAMIŞ** (okunabilirlik korunur) — ürün görselinden farklı olarak `prepareMedia`'dan geçmez.

---

## 4. Bilinen sınırlar / notlar

- **Video canlı doğrulaması** imaj rebuild (ffmpeg) sonrası yapılır — kod ffmpeg'i mock'la test edildi, gerçek transcode imajda ffmpeg olmadan çalışmaz.
- **metin'e haber:** `engine.py`, `api/seller_media.py`, `media/files.py` onun dosyaları — üzerine EKLENDİ (bozulmadı) ama koordinasyon için bilgi verilmeli.
- **Deferred (merge-blocker değil):** nadir "PA" (palette+alpha) görsel modu hâlâ RGB'ye düşüyor; mediabunny `bitrate` alanı deprecated; storefront `nginx.conf.template` mirror'ı ayrı takip; kota private-dosya muafiyeti teorik gaming (mevcut public yollar is_private=0 sabitliyor).
