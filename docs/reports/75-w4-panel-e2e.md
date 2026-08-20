# 75 · W4 — Panel E2E altyapısı + T-141 taşıması

**Tarih:** 2026-08-20
**Kapsam:** `admin-panel/frontend` için Playwright E2E altyapısı sıfırdan kuruldu;
T-141'in tradehubfront'ta `test.skip` ile yazılı 6 senaryosu panele taşındı ve
CANLI panele (`http://istoc.localhost/panel/`) + canlı backend'e karşı koşturuldu.
**Mock yok** — bütün iddialar gerçek sunucu yanıtını bekliyor.

---

## 1. Kurulan altyapı

| Öğe | Yol |
|---|---|
| Runner | `@playwright/test@1.62.1` (devDependency) + `chromium` |
| Config | `admin-panel/frontend/playwright.config.ts` — baseURL `http://istoc.localhost/panel/`, tek proje (chromium), `tests/e2e/`, seri koşum (`workers:1`, dedup ölçümü paralelde bozulur) |
| Betik | `package.json` → `"test:e2e": "playwright test"` |
| Oturum | `tests/e2e/global-setup.ts` — bir kez satıcı oturumu üretip `playwright/.auth/seller.json` `storageState`'ine yazar (Playwright standardı) |
| Yardımcılar | `tests/e2e/helpers.ts` — CSRF'li `call/callGet`, kötücül bayt üreticileri (KODDA üretilir, fixture depoya konmadı) |
| .gitignore | `test-results/`, `playwright-report/`, `playwright/.auth/` eklendi (oturum sid'i commit'lenmez) |

**Oturum neden form-login değil:** Panel yalnız satıcı/admin oturumuna açık;
satıcı fixture kullanıcılarının dev parolası yok ve `Administrator`'ın **mağazası
yok** (`ownership.current_store` → satıcı medya uçları 403). `global-setup`
backend konteynerinde `frappe.sessions.Session` ile bir kez oturum üretip `sid`
cookie'sini storageState'e yazar — "bir kez giriş yap, sakla" deseninin sunucu
tarafı hâli. Satıcı: `ali.bal@turksab.com` (mağaza **SEL-00003**, aktif abonelik,
ready `product.image` varlığı `7pa8r42g7d`). Env ile geçersiz kılınabilir:
`E2E_SELLER_USER`, `E2E_CROP_ASSET`, `E2E_BACKEND_CONTAINER`, `E2E_SITE`.

---

## 2. Senaryo sonuç tablosu (6 satır)

| # | Senaryo | Etiket | Nasıl ölçüldü |
|---|---|---|---|
| **S1** | 1000×1000 altı görsel reddi | **YAZILDI-KOŞMUYOR** | Boyut kapısı CANLI panelde hiçbir ulaşılabilir yolda zorlanmıyor (bkz. §4 Bulgu 1). Test yazıldı, `test.skip` — sahte yeşil basılmadı. |
| **S4** | crop + focal + onay → kayıt | **KOŞUYOR** | `save_intent` focal(0.42/0.58)+onay kanıtı yazar → 200; `get_intent` aynı geometriyi döndürür (idempotent round-trip). |
| **S5** | önizlemesiz onay engeli (UI+API) | **KOŞUYOR** (sunucu) | Kanıtsız `approved_by_user=1` → **417 MEDIA_PREVIEW_REQUIRED**. UI disabled-düğme yarısı headless'ta drive edilemiyor (§4 Bulgu 3); `approvalGate.test.js` biriminde kapsanıyor. |
| **S9** | dedup 2× yükleme | **KOŞUYOR** | Aynı içerik 2× → **aynı `file_url`** (ikinci nesne açılmaz); `find_in_my_library(sha)` → `found:true`. |
| **S10** | bomb / polyglot / SVG-XSS reddi + worker sağlam | **KOŞUYOR** | bomb→417 `upload_image_bomb`, polyglot→417 `upload_content_truncated`, SVG-XSS→417 `upload_content_dangerous`, ardından normal yükleme→200 (worker ayakta). |
| **S11b** | superadmin S3 aynalama | **YAZILDI-KOŞMUYOR** | Ekran `Media Superadmin` rolü ister — satıcı oturumu giremez (**negatif erişim kapısı KOŞUYOR**); pozitif aynalama iddiası gerçek S3/MinIO hedefi ister → `test.skip`. |

**Koşum çıktısı (`npx playwright test`):** `6 passed, 2 skipped` (8 test).
Skip'ler: S1 ve S11b-pozitif. S11b'nin negatif erişim kapısı + oturum dumanı
KOŞUYOR.

Dosya dağılımı:
- `tests/e2e/media-upload-security.spec.ts` — S1 (skip), S10
- `tests/e2e/media-crop-approval.spec.ts` — S4, S5
- `tests/e2e/media-dedup.spec.ts` — S9
- `tests/e2e/media-console-access.spec.ts` — oturum dumanı, S11b (negatif koşuyor / pozitif skip)

---

## 3. Doğrulama

| Komut | Sonuç |
|---|---|
| `npx playwright test` | **6 passed, 2 skipped** |
| `npm test` (birim) | **862 pass / 0 fail** (brief'teki "840" güncel değil; hiçbir birim testi kırılmadı — `src/**`'e dokunulmadı) |
| `npx eslint src` | **0 error** (2 uyarı `views/permission/PlansTab.vue`'de — önceden var, benim dosyalarım değil) |

tradehubfront'taki 6 skip'li senaryonun başındaki **yalnız gerekçe yorumları**
güncellendi ("TAŞINDI (2026-08-20): panel paketine → <dosya>"); gövdeler ve
skip'ler değişmedi.

---

## 4. Bulunan kusurlar (DÜZELTİLMEDİ — test görevi, raporlanıyor)

**Bulgu 1 — Min-boyut (1000×1000) kapısı canlı panelde ölü.**
`min_short_edge=1000` yalnız iki yerde: (a) istemci slot-preflight
(`MediaUploader.vue` → `runPreflight` → `short_edge_too_small`), (b) asenkron
rendition üretimi. Ama `MediaUploader.vue` **hiçbir route'a bağlı değil** ("Rota
ve menü bağı YOK" — kendi başlığı). Canlı yükleme yolu
(MediaLibrary/Explorer → `store.enqueueUploads` → `uploadPolicy.precheck`)
boyuta **hiç bakmaz**, ve sunucu `upload_media` da bakmaz — 64×64 PNG 200 ile
kabul edildi. Sonuç: satıcı sub-1000 görsel yükleyebiliyor, "reddedilir + düzelt"
akışı hiçbir ekranda görünmüyor. **Kapsam açığı.**

**Bulgu 2 — İstemci dedup uyarısı GÖRSELLERDE görünmez.**
`dedupCheck.js` ORİJİNAL dosyanın SHA-256'sını hesaplar; sunucu ise PNG/JPEG'i
**WebP'ye çevirip** içerik-adresli adı `sha256(webp)` üzerinden kurar. İki hash
ayrışır → `find_in_my_library` görsellerde asla eşleşmez. Ölçüm: PNG yüklendi,
orijinal-PNG sha ile `find` → `found:false`; aynı içerik zaten-WebP olarak
yüklenince → `found:true`. Yani panelde PNG/JPEG yüklerken "bu dosya
kütüphanenizde" uyarısı **fiilen çıkmaz** (yalnız hâlihazırda WebP olan içerik
için çalışır). Sunucu dedup'ı (aynı `file_url`) yine de doğru — kullanıcı
uyarılamıyor, ama çift nesne oluşmuyor.

**Bulgu 3 — CropStudioModal kütüphanede `:asset`'siz mount ediliyor.**
`MediaLibraryView.vue` `CropStudioModal`'ı yalnız `:source` + `slot-key` ile
açıyor, `:asset` PROP'U GEÇMİYOR. `asset=""` → Uygula düğmesi kalıcı disabled,
`save_intent` bu ekrandan **hiç çağrılamaz**; içindeki `SimApprovalGate` de
`asset` alamadığı için `approve()` no-op. Kırpma-kaydet UI yolu kütüphanede ölü —
S4/S5'in UI yarısının headless'ta drive edilememesinin de kökü bu (sunucu yarısı
KOŞUYOR).

**Bulgu 4 — Megapiksel-bomba kapısında dar bir kaçış aralığı (BACKEND).**
`content_gate` tavanı 80 MP ama boyutu Pillow'un kendi `MAX_IMAGE_PIXELS`
(~89 MP) sınırının ÜSTÜNDE iddia eden bir PNG (ör. 30000×30000) Pillow tarafından
başlığı bile açılmadan düşürülüyor → boyut 0 okunuyor → bomba **tetiklenmiyor**
ve dosya 200 ile kabul ediliyor (ölçüldü — `/files/25/25b8f950….png` bu probe'un
izi). Yalnız 80–89 MP penceresindeki bombalar yakalanıyor (12000×12000 doğru
reddedildi). Testin S10 bombası bilinçle 12000² seçildi ki gerçek reddi ölçsün.

---

## 5. Bırakılan `e2e-` izleri (SİLİNMEDİ — çöp akışı korumalı, temizlik ayrı iş)

Satıcı **SEL-00003** kütüphanesinde, 2026-08-20 tarihli `e2e-` önekli 11 `File`
kaydı (disk nesneleri içerik-adresli olduğu için 4 benzersiz bloba dedup olur):

| Blob (file_url) | Bayt | Kaynak |
|---|---|---|
| `/files/87/87f05f029f48e1e1c9e6c97c031570fe.webp` | 34 | S9 dedup içeriği (tekrar tekrar aynı blob) + probe |
| `/files/ff/ff347f69b3661b776ea6844f38d7243e.webp` | 80 | S10 "kötücül sonrası normal yükleme" |
| `/files/c2/c22c863552604d9a3c8261bc53dbc594.webp` | 90 | ilk PNG→WebP probe'u |
| `/files/25/25b8f950e4a501f3ead65781ca6daae7.png` | 68 | Bulgu 4'ün bozuk-bomba probe'u (yanlışlıkla kabul edilen) |

Reddedilen yüklemeler (bomb 12000², polyglot, SVG-XSS) **hiç yazılmadı** (417).
Kırpma niyeti `7pa8r42g7d` üstünde `afterAll` ile SİLİNDİ — asset pristine
(doğrulandı: `Media Crop Intent` = 0). Not: Aynı satıcıda 2026-08-18/19 tarihli
5 adet `e2e-video.mp4` ÖNCEDEN vardı, bu görevin izi değil.

**Temizlik komutu (ayrı iş, çalıştırılmadı):** `File` kayıtlarını çöpe atmak
korumalı akıştan geçmeli; disk blobları son sahip de silmeden kaldırılmaz.

---

## 6. Yeniden koşum

```bash
cd admin-panel/frontend
npm run test:e2e            # global-setup satıcı oturumunu üretir, storageState'e yazar
```

Gerektirir: `istoc-dev-backend-1` konteyneri çalışır, panel `istoc.localhost/panel/`
200, boru hattı bayrakları açık (`rendition_on_upload` + `product.image` slotu —
2026-08-20 itibarıyla açık). `docker exec` erişimi yoksa `global-setup` ve crop
niyet reset'i çalışmaz; crop senaryoları o durumda gerekçeli skip'e düşer.
