# Medya Sıkıştırma + Kota + URL Güvenliği — Uygulama Planı

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan. Each work-package (WP) is dispatched to a fresh subagent in its own git worktree. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Satıcı görsel/videolarını tarayıcıda WebP/WebM'e çevirip küçülterek yükle, sunucuda garanti altına al, satıcı-başına depolama kotasını gerçekten uygula, ve dosya isimlerini tahmin edilemez yap — mevcut URL'leri kırmadan.

**Architecture:** Ağır sıkıştırma satıcının tarayıcısında (browser-image-compression + mediabunny); sunucu Safari fallback'ini tamamlar, kotayı `File.before_insert`'te uygular, `write_file` hook'unda dosyayı içerik-hash'iyle adlandırır, videoyu async ffmpeg kuyruğunda normalize eder.

**Tech Stack:** Frappe v15 (Python/Pillow/RQ), Vite+Alpine (storefront), Vue 3 (panel), Tailwind v4, browser-image-compression 2.0.2, mediabunny 1.53.1, ffmpeg.

**Spec:** `docs/superpowers/specs/2026-08-13-medya-sikistirma-kota-url-design.md`

## Global Constraints

- **Frappe v15** — `frappe.qb`, v15 API'leri; kod yazmadan context7'den v15 dokümanı çek.
- **Tailwind v4** — JS config YOK; stil gerekiyorsa CSS `@theme`. Panel ayrıca SCSS kullanıyor.
- **browser-image-compression 2.0.2 + mediabunny 1.53.1 projede KURULU DEĞİL** — eklemeden önce context7/npm ile güncel API teyidi (CLAUDE.md kuralı).
- **Mevcut file_url'ler KIRILMAYACAK** — isimlendirme yalnız YENİ yüklemelere; `/files/` prefix + uzantı korunur.
- **metin'in `media/` paketine minimum dokunuş** — `files.storage_usage`, `ownership.*`, `metadata.*` yeniden yazılmaz, çağrılır.
- **Safari/iOS/Capacitor'da `canvas.toBlob('image/webp')` YOK** — her görsel yolunda JPEG fallback + sunucu WebP şart.
- **Kota seed patch'i ZORUNLU** — atlanırsa `within_quota` False döner, tüm satıcılar bloklanır.
- **TDD** — her task önce başarısız test, sonra minimal implementasyon. Sık commit.
- **Dil:** kod yorumları ve kullanıcıya dönük metinler Türkçe (mevcut desen).

---

## Faz 0 — Paylaşılan iskelet (ana oturum, paralel agent'lardan ÖNCE)

Amaç: paralel agent'ların çakışacağı iki dosyayı (`hooks.py`, `engine.py`) ve boş
modül stub'larını önceden hazırlamak, böylece her agent kendi dosyasına yazar.

**Files:**
- Modify: `tradehub_core/hooks.py` — `File.before_insert` string→liste, `write_file` hook satırı
- Create: `tradehub_core/tradehub_core/media/naming.py` (stub)
- Create: `tradehub_core/tradehub_core/media/transcode.py` (stub)
- Create: `tradehub_core/tradehub_core/entitlement/checks.py` içine boş `check_media_storage_quota` (stub)
- Create: `tradehubfront/src/lib/media/compress.ts` (stub)
- Create: `admin-panel/frontend/src/lib/media/compress.js` (stub)

- [ ] **Step 1: `hooks.py` — before_insert'i listeye çevir**

Mevcut:
```python
"File": {
    "before_insert": "tradehub_core.utils.security.reject_unsafe_files",
},
```
Yeni:
```python
"File": {
    "before_insert": [
        "tradehub_core.utils.security.reject_unsafe_files",
        "tradehub_core.entitlement.checks.check_media_storage_quota",
    ],
},
```

- [ ] **Step 2: `hooks.py` — write_file hook ekle**

`hooks.py`'a (mevcut method-hook bölgesine) ekle:
```python
# Yeni yüklemeleri içerik-hash'iyle adlandır (enumeration önleme, TUR-141).
write_file = "tradehub_core.media.naming.write_file_hashed"
```

- [ ] **Step 3: Stub modüller**

`media/naming.py`:
```python
"""Yükleme sırasında içerik-adresli dosya adlandırma (TUR-141/130)."""
def write_file_hashed(*args, **kwargs):
    raise NotImplementedError  # WP4 dolduracak
```
`media/transcode.py`:
```python
"""Video async transcode (WebM/H.264) — RQ long queue (TUR-296)."""
def enqueue_transcode(file_url: str) -> None:
    raise NotImplementedError  # WP2 dolduracak
```
`entitlement/checks.py` içine (mevcut fonksiyonların yanına):
```python
def check_media_storage_quota(doc, method=None):
    """File.before_insert — satıcı depolama kotası (TUR-139). WP3 dolduracak."""
    return  # no-op stub; WP3 gerçek kontrolü koyar
```
`compress.ts` / `compress.js`:
```ts
// Client-side medya sıkıştırma (WebP/WebM) — WP1 dolduracak.
export async function prepareMedia(file: File): Promise<File | Blob> {
  return file  // stub: dokunmadan geç
}
```

- [ ] **Step 4: Migrate + smoke — stub'lar sistemi kırmıyor**

Run: `docker exec istoc-dev-backend-1 bench --site istoc.localhost migrate` (yerelde çalışıyorsa) veya en azından `python -c "import ast; ast.parse(open('...').read())"` ile üç .py dosyasının parse olduğunu doğrula. `write_file` no-op stub `NotImplementedError` atacağı için Step 4'te write_file hook satırını **yorumda tut**, WP4 gerçek fonksiyonu koyunca aç. (Aksi halde her upload kırılır.)

- [ ] **Step 5: Commit**

```bash
cd tradehub_core && git add -A && git commit -m "chore(media): sıkıştırma/kota/isimlendirme için paylaşılan iskelet stub'ları"
```

---

## WP1 — A-client: tarayıcı sıkıştırma (görsel WebP + video WebM)

**Worktree:** tradehubfront + admin-panel (iki repo; agent her ikisinde çalışır)

**Files:**
- Create: `tradehubfront/src/lib/media/compress.ts` (Faz 0 stub'ını doldur)
- Create: `tradehubfront/src/lib/media/compress.image.ts`, `compress.video.ts`
- Modify: `tradehubfront/src/lib/upload-ui/uploader.ts` — kuyruğa girmeden `prepareMedia`
- Create: `admin-panel/frontend/src/lib/media/compress.js` (+ image/video)
- Modify: `admin-panel/frontend/src/composables/useSellerMedia.js` — `upload()` içinde `prepareMedia`
- Test: `tradehubfront/tests/unit/media-compress.spec.ts`

**Interfaces:**
- Produces: `prepareMedia(file: File, opts?: {maxWidth?: number, maxSizeMB?: number}): Promise<{blob: Blob, name: string, converted: 'webp'|'jpeg'|'webm'|'mp4'|'none'}>`
- Consumes: (Faz 0 stub yerine gerçek implementasyon)

- [ ] **Step 1: Kütüphaneleri kur + API teyidi**

```bash
cd tradehubfront && npm i browser-image-compression@2.0.2 mediabunny@1.53.1
```
context7'den `browser-image-compression` ve `mediabunny` güncel API'sini çek; imzalar aşağıdakiyle uyuşmuyorsa dokümana uy, plana not düş.

- [ ] **Step 2: Görsel sıkıştırma — başarısız test**

`tests/unit/media-compress.spec.ts`:
```ts
import { describe, it, expect, vi } from 'vitest'
import { prepareImage } from '../../src/lib/media/compress.image'

describe('prepareImage', () => {
  it('WebP destekleyen tarayıcıda WebP döner', async () => {
    const file = new File([new Uint8Array(200_000)], 'foto.jpg', { type: 'image/jpeg' })
    const out = await prepareImage(file, { webpSupported: true })
    expect(out.converted).toBe('webp')
    expect(out.name.endsWith('.webp')).toBe(true)
  })
  it('Safari (WebP yok) JPEG fallback döner', async () => {
    const file = new File([new Uint8Array(200_000)], 'foto.png', { type: 'image/png' })
    const out = await prepareImage(file, { webpSupported: false })
    expect(out.converted).toBe('jpeg')
  })
})
```

- [ ] **Step 3: Test başarısız — çalıştır**

Run: `cd tradehubfront && npx vitest run tests/unit/media-compress.spec.ts`
Expected: FAIL (modül yok).

- [ ] **Step 4: `compress.image.ts` implementasyonu**

`browser-image-compression` ile: `{maxWidthOrHeight:1920, maxSizeMB:0.5, initialQuality:0.8, useWebWorker:true, fileType: webpSupported ? 'image/webp':'image/jpeg'}`. `webpSupported` verilmezse feature-detect: bir kez `canvas.toBlob(cb,'image/webp')` ile `blob.type==='image/webp'` testi (sonucu modül-seviyesi cache'le). Çıktı `File` tipini kontrol et; WebP istenmiş ama gelmemişse (Safari) JPEG q85 ile tekrar sıkıştır, `converted:'jpeg'`. Dosya adını `<orijinal-taban>.webp`/`.jpg` yap.

- [ ] **Step 5: Test geçer**

Run: `npx vitest run tests/unit/media-compress.spec.ts` → PASS.

- [ ] **Step 6: Video sıkıştırma — başarısız test + implementasyon**

`compress.video.ts`: `mediabunny` `getEncodableVideoCodecs()` probe; VP9 varsa WebM, yoksa H.264 MP4; 1280 genişlik, 2Mbps. Süre>60sn veya boyut>100MB ise `converted:'none'` (orijinali geç, sunucuya bırak). Probe hata verirse `converted:'none'`. Test: sahte küçük dosyayla `converted` alanının beklenen değeri (mediabunny'yi `vi.mock` ile stub'la — gerçek encode CI'da çalışmaz).

- [ ] **Step 7: `prepareMedia` orkestrasyon + storefront entegrasyonu**

`compress.ts`: `file.type` image/* → `prepareImage`, video/* → `prepareVideo`, diğer → `{blob:file, converted:'none'}`. `uploader.ts`'de dosya kuyruğa eklenmeden önce `prepareMedia`'dan geçir; XHR'a küçülmüş blob + yeni ad gider. (context7'den mevcut uploader akışını bozmadan ekle.)

- [ ] **Step 8: Panel entegrasyonu**

`admin-panel/frontend/src/lib/media/compress.js` (aynı mantık, JS). `useSellerMedia.js` `upload()`: `FileReader.readAsDataURL` ÖNCESİ `prepareMedia`'dan geçir; base64 küçülmüş blob'tan üretilir. Metadata (width/height) sunucuda `probe` ile okunuyor, dokunma.

- [ ] **Step 9: Build + commit**

```bash
cd tradehubfront && npm run build
cd ../admin-panel/frontend && npm install && npm run build
git add -A && git commit -m "feat(media): tarayıcıda görsel→WebP, video→WebM sıkıştırma (TUR-128/127/123)"
```

**Kabul:** Test yeşil; storefront+panel build geçiyor; 200KB test görseli WebP+küçük çıkıyor (unit); Safari yolu JPEG'e düşüyor.

---

## WP2 — A-server: sunucu garanti-WebP + video transcode

**Worktree:** tradehub_core + docker

**Files:**
- Modify: `tradehub_core/tradehub_core/media/pipeline.py` — `to_webp(bytes, quality=80)` ekle (mevcut format-koruma yolunu kırmadan)
- Create: `tradehub_core/tradehub_core/media/transcode.py` (Faz 0 stub'ını doldur)
- Modify: `tradehub_core/tradehub_core/api/seller_media.py` — `upload_media` içinde: görsel WebP değilse `to_webp`, video ise `enqueue_transcode`
- Modify: `docker/**/Dockerfile` (backend) — `ffmpeg` paketi
- Test: `tradehub_core/tradehub_core/tests/test_media_transcode.py`, `test_engine_webp.py`

**Interfaces:**
- Consumes: `frappe.enqueue`, mevcut `engine.probe`, `media.audit.log_media_event`
- Produces: `engine.to_webp(data: bytes, quality: int = 80) -> bytes`; `transcode.enqueue_transcode(file_url: str) -> None`; File'da video durum alanı `th_media_video_status` (Select: `"" | processing | ready | failed`)

- [ ] **Step 1: `to_webp` — başarısız test**

`tests/test_engine_webp.py`:
```python
def test_to_webp_kucultur_ve_webp_dondurur():
    from tradehub_core.media import engine
    import io
    from PIL import Image
    buf = io.BytesIO(); Image.new("RGB", (3000, 2000), "red").save(buf, "JPEG", quality=95)
    out = engine.to_webp(buf.getvalue(), quality=80)
    assert out[:4] == b"RIFF" and out[8:12] == b"WEBP"
    assert len(out) < buf.tell()  # küçüldü
```

- [ ] **Step 2: Test başarısız** — Run: `bench --site istoc.localhost run-tests --module tradehub_core.tests.test_engine_webp` → FAIL.

- [ ] **Step 3: `to_webp` implementasyonu**

`engine.py`'a saf fonksiyon: `Image.open(BytesIO(data))`, `ImageOps.exif_transpose`, `convert("RGB")`, `thumbnail((1920,1920))`, `save(out, "WEBP", quality=quality, method=4)`. **Mevcut `optimize`/format-koruma yolunu değiştirme** — bu ayrı bir giriş. (Docstring: file_url değişmez, bu client Safari-fallback'ini tamamlar.)

- [ ] **Step 4: Test geçer** → PASS.

- [ ] **Step 5: `upload_media` görsel dalı**

`api/seller_media.py:upload_media` — içerik decode edildikten sonra: uzantı görsel VE `imghdr`/Pillow ile WebP değilse → `icerik = engine.to_webp(icerik)`, dosya adı uzantısını `.webp` yap. WebP zaten ise dokunma. (Client çoğunlukla WebP gönderecek; bu yalnız Safari JPEG'i için.) Video ise Step 7.

- [ ] **Step 6: Video durum alanı — patch**

Yeni patch `patches/v15_9_16_media_video_status.py`: `File`'a `th_media_video_status` (Select `\nprocessing\nready\nfailed`, hidden, no_copy). `create_custom_fields` + idempotent guard (mevcut `v15_9_15` deseni). `patches.txt`'e ekle.

- [ ] **Step 7: `transcode.py` + enqueue — başarısız test**

`tests/test_media_transcode.py`: `enqueue_transcode(url)` çağrılınca `frappe.enqueue`'nun `queue="long"` ile çağrıldığını `unittest.mock` ile doğrula; `_run_transcode` ffmpeg subprocess komutunu doğru argümanlarla (`-c:v libvpx-vp9` veya `libx264`, `scale=min(1280,iw)`, `-c:a libopus`) kurduğunu doğrula (subprocess'i mock'la, gerçek ffmpeg çağırma).

- [ ] **Step 8: `transcode.py` implementasyonu**

`enqueue_transcode(file_url)`: File'ı `processing` yap, `frappe.enqueue("tradehub_core.media.transcode._run_transcode", queue="long", timeout=1800, file_url=file_url, enqueue_after_commit=True)`. `_run_transcode`: diskteki dosyayı ffmpeg ile WebM'e çevir (`nice -n 10`), başarıda dosyayı değiştir + `ready`, hatada `failed` + audit. `upload_media` video dalında `enqueue_transcode(doc.file_url)` çağır.

- [ ] **Step 9: Dockerfile — ffmpeg**

Backend Dockerfile'a `RUN apt-get update && apt-get install -y ffmpeg` (mevcut apt bloğuna). Not: bu deploy dokunuşu; imaj rebuild gerektirir (video canlı testinin önkoşulu).

- [ ] **Step 10: Testler + commit**

```bash
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_engine_webp
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_transcode
git add -A && git commit -m "feat(media): sunucu garanti-WebP + video ffmpeg transcode kuyruğu (TUR-128/296/297)"
```

**Kabul:** İki test yeşil; `to_webp` gerçek WebP üretiyor; video upload'ı `processing` işaretleyip kuyruğa atıyor; Dockerfile ffmpeg içeriyor.

---

## WP3 — B: satıcı depolama kotası enforcement

**Worktree:** tradehub_core + admin-panel

**Files:**
- Modify: `tradehub_core/tradehub_core/fixtures/feature_catalog.json` — `quota.max_storage_mb`
- Create: `tradehub_core/tradehub_core/patches/v15_9_17_seed_storage_quota.py` — planlara değer
- Modify: `tradehub_core/tradehub_core/entitlement/checks.py` — `check_media_storage_quota` (Faz 0 stub'ını doldur)
- Modify: `tradehub_core/tradehub_core/media/files.py` — `_quota()` entitlement'ten okusun
- Modify: `tradehub_core/tradehub_core/api/v1/entitlement_snapshot.py` — `_STOREFRONT_QUOTA_KEYS`
- Modify: `admin-panel/frontend/src/components/media/MediaFilterRail.vue` — null-kota NaN düzeltmesi
- Test: `tradehub_core/tradehub_core/tests/test_media_quota.py`

**Interfaces:**
- Consumes: `entitlement.core.within_quota`, `entitlement.core.get_quota_limits`, `media.files.storage_usage`, `utils.tenant.get_current_seller_profile`, `media.presets.EXCLUDED_DOCTYPES`
- Produces: `check_media_storage_quota(doc, method=None)` — kota aşımında `frappe.throw`

- [ ] **Step 1: Feature Catalog kaydı**

`fixtures/feature_catalog.json`'a ekle:
```json
{"doctype":"Feature Catalog","name":"quota.max_storage_mb","feature_key":"quota.max_storage_mb","display_name":"Medya Depolama Kotası","category":"QuotaLimits","feature_type":"Quota","default_value":"500","unit":"MB","is_active":1}
```

- [ ] **Step 2: Seed patch (KRİTİK — atlanırsa herkes bloklanır)**

`patches/v15_9_17_seed_storage_quota.py`: her `Subscription Plan` için `quota_limits` JSON'una `quota.max_storage_mb` yoksa ekle (ör. Free 500, üst planlar daha yüksek/`-1`). `patches.txt`'e ekle. (Desen: `v15_6_18_seed_subscription_plans.py`.)

- [ ] **Step 3: Kota kontrolü — başarısız test**

`tests/test_media_quota.py`:
```python
def test_kota_asiminda_upload_reddedilir(self):
    # kota=1MB'lık bir plan/mağaza kur, 2MB kullanım simüle et
    # yeni 1MB dosya File.before_insert'te frappe.throw ile reddedilmeli
    with self.assertRaises(frappe.ValidationError):
        frappe.get_doc({"doctype":"File","file_name":"x.webp","is_private":0,"content":b"..."}).insert()
def test_kyb_dosyasi_kotadan_muaf(self):
    # attached_to_doctype='KYB Verification' → throw ETMEMELİ
```

- [ ] **Step 4: Test başarısız** → FAIL.

- [ ] **Step 5: `check_media_storage_quota` implementasyonu**

`entitlement/checks.py`: System Manager/Marketplace Admin bypass; `doc.attached_to_doctype in EXCLUDED_DOCTYPES` → return; `frappe.flags` bulk bypass'ları → return; `store = get_current_seller_profile()`; store yoksa return (guest/admin); `usage = files.storage_usage(store)["bytes"]`; `limit_mb = get_quota_limits(store).get("quota.max_storage_mb")`; `-1`/None→sınırsız; gelen dosya boyutu (`len(doc.content)` veya `doc.file_size`) eklenince limit aşılıyorsa `frappe.throw(_("Depolama kotanız doldu ({0} MB). Yükleme yapılamadı.").format(limit_mb))`.

- [ ] **Step 6: `files._quota()` entitlement'e bağla**

`media/files.py:_quota()`: mevcut `Marketplace Settings.media_storage_quota_bytes` yerine oturumdaki mağazanın `get_quota_limits(store)["quota.max_storage_mb"] * 1024*1024` değerini döndür (None ise None). **metin'e haber ver** (bu onun fonksiyonu).

- [ ] **Step 7: Snapshot + panel NaN düzeltmesi**

`entitlement_snapshot.py:_STOREFRONT_QUOTA_KEYS` tuple'ına `"quota.max_storage_mb"` ekle. `MediaFilterRail.vue`: `quotaBytes` `required:true`→`default:null`; `storagePercent` `quotaBytes` null/0 ise `0` ya da "sınırsız" göster (NaN yok).

- [ ] **Step 8: Testler + build + commit**

```bash
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_quota
cd admin-panel/frontend && npm run build
git add -A && git commit -m "feat(media): satıcı depolama kotası enforcement + entitlement (TUR-139)"
```

**Kabul:** Kota aşımı upload'u reddediyor; KYB muaf; panel null-kotada NaN göstermiyor; seed patch migrate'te planları dolduruyor.

---

## WP4 — C: URL isimlendirme / enumeration güvenliği

**Worktree:** tradehub_core + docker

**Files:**
- Modify: `tradehub_core/tradehub_core/media/naming.py` (Faz 0 stub'ını doldur)
- Modify: `tradehub_core/hooks.py` — `write_file` hook satırını aktifleştir (Faz 0'da yorumdaydı)
- Modify: `docker/nginx/storefront.local.template` — `/files/` X-Robots-Tag + limit_req
- Test: `tradehub_core/tradehub_core/tests/test_media_naming.py`

**Interfaces:**
- Consumes: Frappe `write_file` hook sözleşmesi (context7/framework kaynağından teyit: imza + dönüş `file_url`)
- Produces: `write_file_hashed(...)` — diske `<sha256(content)[:32]>.<ext>` yazar, `/files/...` file_url döner

- [ ] **Step 1: Frappe write_file sözleşmesini teyit et**

Konteynerdeki framework kaynağından `frappe/core/doctype/file/file.py` ve `utils/file_manager.py`'daki `write_file`/`get_hook_method("write_file")` çağrısının beklediği imza ve dönüşü oku. Plana gerçek imzayı not düş (aşağıdaki iskelet ona göre düzeltilecek).

- [ ] **Step 2: Hashed naming — başarısız test**

`tests/test_media_naming.py`:
```python
def test_ayni_icerik_ayni_hash_farkli_ad_gizli(self):
    from tradehub_core.media import naming
    data = b"\x89PNG test icerik"
    ad1 = naming._hashed_name("urun.png", data)
    assert ad1.endswith(".png")
    assert "urun" not in ad1              # orijinal ad sızmıyor
    assert len(ad1.split(".")[0]) == 32   # sha256[:32]
    assert ad1 == naming._hashed_name("baska.png", data)  # içerik-adresli
```

- [ ] **Step 3: Test başarısız** → FAIL.

- [ ] **Step 4: `naming.py` implementasyonu**

`_hashed_name(original, content)`: `ext = os.path.splitext(original)[1].lower()`; `h = hashlib.sha256(content).hexdigest()[:32]`; `return f"{h}{ext}"`. `write_file_hashed(...)`: Step 1'de öğrenilen imzaya göre — dosya adını `_hashed_name` ile değiştir, `/files/` (public) veya `/private/files/` prefix + uzantı KORU, diske yaz, `file_url` döndür. `File.file_name` (görünen ad) orijinali tutabilir; sadece disk adı/`file_url` hash'lenir.

- [ ] **Step 5: Test geçer + hook'u aktifleştir**

`hooks.py`'daki `write_file = "...write_file_hashed"` satırını (Faz 0'da yorumdaysa) aç. Run: naming testi → PASS.

- [ ] **Step 6: Entegrasyon — yeni upload hash'li, eski kırılmadı**

`bench console`'da `upload_media` ile bir görsel yükle → dönen `file_url`'in hash-isimli olduğunu doğrula. Mevcut bir eski `file_url`'in (ör. `/files/0505.jpg`) hâlâ 200 döndüğünü doğrula (kırılmadı).

- [ ] **Step 7: Nginx hızlı kazanımlar**

`docker/nginx/storefront.local.template`'te `location ^~ /files/` bloğu: `proxy_hide_header X-Robots-Tag` satırını KALDIR ve `add_header X-Robots-Tag "noindex" always;` ekle; `limit_req_zone` tanımla + bloğa `limit_req burst=20 nodelay;`. (Nginx reload gerektirir — deploy dokunuşu.)

- [ ] **Step 8: Commit**

```bash
git add -A && git commit -m "feat(media): içerik-hash'li dosya adlandırma + nginx sertleştirme (TUR-141/130/124)"
```

**Kabul:** Yeni yüklemeler 32-hex isimli; eski URL'ler çalışıyor; naming testi yeşil; nginx `/files/`'a noindex+rate-limit uyguluyor.

---

## Faz 2 — Merge + entegrasyon + user journey (ana oturum)

- [ ] Worktree'leri sırayla ana branch'e merge et: Faz 0 → WP4 (naming, en temel) → WP3 (kota) → WP2 (server) → WP1 (client). Her merge sonrası ilgili testleri çalıştır.
- [ ] `hooks.py` çakışmasını çöz (WP3 before_insert + WP4 write_file aynı sözlükte — ikisi de Faz 0 iskeletine yazdığı için temiz olmalı; teyit et).
- [ ] Tam test: `bench run-tests` (media modülleri) + `npm run build` (iki frontend).
- [ ] `docs/superpowers/plans/`'e user journey dosyası yaz: `2026-08-13-medya-test-journey.md` — build/migrate komutları + satıcı adım adım senaryosu + beklenen sonuçlar (spec §9).

---

## Self-review notları

- **Spec kapsaması:** A (WP1+WP2), B (WP3), C (WP4), video (WP2), datetime (WP4 §Step7 kapsam dışı bırakıldı — ISO çıktı ayrı küçük iş, user journey'de not). Faz 0 çakışan dosyaları izole ediyor.
- **Tip tutarlılığı:** `prepareMedia` dönüşü WP1 içinde tutarlı; `to_webp`/`enqueue_transcode`/`check_media_storage_quota`/`write_file_hashed` imzaları interfaces bloklarında sabit.
- **Bilinen boşluk:** her WP context7/framework teyidiyle başlıyor (kütüphane API + Frappe write_file sözleşmesi) — iskeletler o teyide göre düzeltilecek, plan bunu her WP'nin ilk adımına koydu.
