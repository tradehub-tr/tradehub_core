# 78 · W5 — Panel kablolaması: MediaUploader + CropStudioModal `:asset`

**Tarih:** 2026-08-20
**Girdi:** Rapor 75 (W4 panel E2E) — iki "kurulu ama bağlı değil" kusuru: Bulgu 1
(`MediaUploader.vue` hiçbir route'a bağlı değil, 1000×1000 kapısı ölü) ve Bulgu 3
(`CropStudioModal` `:asset`siz mount → `save_intent` kütüphaneden hiç çağrılamaz).
**Kapsam:** `admin-panel/frontend` — `views/seller/MediaLibraryView.vue`,
`src/stores/media.js`, `src/components/media/upload/**`, iki yeni birim test
dosyası, `tests/e2e/media-*.spec.ts` sürüşü. Backend'e, router'a, locale'lere
DOKUNULMADI.

---

## 1. Kusur 1 — MediaUploader kütüphanenin "Yükle" düğmesine bağlandı

| Ne | Nerede |
|---|---|
| "Yükle" düğmesi (masaüstü başlık + mobil FAB) artık gizli `<input type=file>` değil; `uploaderOpen` modalını açar | `MediaLibraryView.vue` şablon (2 `@click="uploaderOpen = true"`) |
| Modal: `MediaModal` içinde `MediaUploader` (async chunk) + slot seçici | `MediaLibraryView.vue` ~717-744 |
| Slot varsayılanı `product.image` (min_short_edge=1000 kapısının sahibi); seçenekler `slotsForRole("seller")` | `uploadSlotKey = ref("product.image")` |
| Yükleme bitince liste tazelenir — store'un mevcut yolu | `@uploaded="onUploaderUploaded"` → `store.loadReal({ trashed: store.showArchived })` (400 ms toplayıcı) |

**Kablolama kanıtı (grep):** `MediaUploader` mount kullanım sayısı **0 → 1**
(`MediaLibraryView.vue:741 <MediaUploader :slot-key=…>` + async import :787).
Kuyruk/preflight/dedup-uyarısı akışı bileşenin kendi içinde — yeniden yazılmadı.

### 1.1 Kablolamanın ortaya çıkardığı iki İSTEMCİ kusuru (düzeltildi)

Bileşen "tam ve test edilmiş"ti ama hiç bir DOM'da koşmamıştı. Canlı panelde
sürülünce iki gerçek kusur çıktı; ikisi de ölçülüp düzeltildi:

1. **Reaktivite kaçağı — kuyruk ekranda donuyordu.**
   `useMediaUpload.add()` satırı reaktif diziye `push`layıp mutasyonları **ham
   referans** üzerinden yapıyordu; Vue ham nesne mutasyonunu göremez → satır
   ekranda sonsuza dek "sırada" kalıyordu (canlı panelde ölçüldü; birim testleri
   değerleri doğrudan okuduğu için yakalayamamıştı — node'da vekil/ham deneyiyle
   de doğrulandı: ham mutasyonda watch 0 kez, vekilde 1 kez tetiklendi).
   Düzeltme: `yeni.push(items.value[items.value.length - 1])` — dizideki
   REAKTİF vekil biriktirilir. (`src/composables/useMediaUpload.js` — dosya
   listemin dışında; kablonun çalışması için zorunluydu, tek satırlık ve
   gerekçesi kodda.)
2. **Engellenen satırın sebebi tıklamasız açılmıyordu.**
   `UploadQueueRow` ayrıntı panelini yalnız MOUNT anında `blocked` ise açıyordu;
   canlı akışta satır kuyruğa `queued` girer, engel ölçümden SONRA gelir → panel
   hep kapalı kalıyordu. Düzeltme: `status → BLOCKED` izleyicisi paneli açar
   (bileşenin kendi başlık ilkesi: "sebebini görmek için tıklamak gerekmemeli").

### 1.2 Eksik i18n anahtarları — `t(k, {}, "TR")` varsayılanıyla geçildi

`i18n/locales` bu görevde yasak; proje kalıbına uygun TR varsayılanları bileşen
içinde verildi, çeviri eklendiğinde kendiliğinden devre dışı kalırlar. Locale
sahibinin eklemesi gerekenler (4 dil):

- `media.uploader.`: `title`, `summary`, `overallAria`, `clearFinished`,
  `dropAria`, `dropTitle`, `dropHint`, `progressAria`, `removeAria`
- `media.preflight.`: `allClear`, `yes`, `no`, `unmeasured`,
  `fact.{size,dimensions,megapixels,alpha,dpi,format,duration,codec}`,
  `reason.<kod>` ve `fix.<kod>` (yalnız `duplicate_in_library` vardı; 19 sebep
  kodunun TR karşılıkları şimdilik `PreflightPanel.vue` içindeki `REASON_TR` /
  `FIX_TR` sözlüklerinde)

## 2. Kusur 2 (rapor 75 · Bulgu 3) — `:asset` seçili öğeden akıyor

- **Ölçüm:** satır modeli (`useSellerMedia.bicimle`) asset adı TAŞIMIYOR.
  Ad `manifest_batch` yanıtının `assets[]` alanından alındı (uç zaten panelin
  türev listesince kullanılıyor).
- `store.assetNameOf(id)` eklendi (`src/stores/media.js`): `docName` (yoksa
  `fileUrl`) ile `media_manifest.manifest_batch` sorulur, `assets[0]` döner;
  manifest `null` ya da `assets` boşsa `""`.
- `MediaLibraryView` crop eylemi asset adını modal AÇILMADAN çözer (stüdyo
  `asset`i kuruluşta okur; sonradan gelen ad Uygula'yı açmaz) ve
  `<CropStudioModal :asset="cropAsset" …>` geçer.
- **Asset'i olmayan/çözülemeyen dosyada `cropAsset=""`** → modal bugünkü dürüst
  "kaydedilemez" durumunda açılır (E2E ile de ölçüldü, aşağıda).

## 3. Yeni ölçülen BACKEND bulgusu (düzeltilmedi — bu görevde backend yasak)

**Bulgu W5-1 — `Media Asset` izinleri satıcıya kendi varlığını GÖSTERMİYOR.**
DocPerm: `Seller` / `Marketplace Seller` read **`if_owner: 1`** ile verilmiş;
boru hattının ürettiği varlıkların Frappe `owner`ı **Administrator**. Sonuç
(bench konsolunda ölçüldü, ali.bal oturumu): `owner_seller = SEL-00003` olan
`7pa8r42g7d` bile `frappe.get_list("Media Asset", source_file=bd5b581362)` →
**boş**; dolayısıyla `manifest_batch.assets[]` satıcıya hep boş,
`media_asset_query_conditions` hiç devreye giremeden `if_owner` süzgeci kesiyor.
**Etki:** kırpma-kaydet UI'ı kablo bağlı olduğu hâlde hiçbir satıcı için
etkinleşemiyor (istemci dürüst "kaydedilemez" durumunda kalıyor — doğru davranış);
detay panelinin türev listesi de satıcıya hep "varlık yok" diyordur. Öneri:
`if_owner` kaldırılıp izolasyonun tek sahibi `media_asset_query_conditions`
bırakılmalı (rendition için de aynı desen kontrol edilmeli).

**Bulgu W5-2 (rapor 75 · Bulgu 1'in sunucu yarısı, hâlâ açık):** `upload_media`
boyut denetlemiyor — 900×900 PNG doğrudan API'den 200 alıyor. E2E'de
`test.fail` gövdesiyle görünür tutuluyor (S1b): kapı sunucuya eklendiğinde
gövde geçer, işaret kırmızıya döner ve kaldırılması gerekir — sahte yeşil yok.

## 4. E2E yeniden koşumu (`npm run test:e2e` — canlı panel + canlı backend)

Panel dist'i Docker imajında — koşumdan önce `npm run build` +
`docker compose build admin-panel && docker compose up -d admin-panel` yapıldı
(iki kez: kablolama + §1.1 düzeltmeleri).

| Senaryo | Önce (rapor 75) | Şimdi | Nasıl ölçüldü |
|---|---|---|---|
| **S1 (UI)** | YAZILDI-KOŞMUYOR (skip) | **KOŞUYOR — GEÇTİ** | "Yükle" → modal → 900×900 PNG: satır `blocked`, sebep metni "900" + "1000", düzeltme yolu görünür; yükleme uçlarına 0 istek; `get_my_media(search)` → total 0 |
| **S1b (sunucu)** | (yoktu) | **test.fail — bilinen açık** | API 900×900 → bugün 200 (iz bırakılmıyor: arşivle+kalıcı sil temizliği iddiadan önce) |
| **S4/S5 UI (a)** | sürülemiyordu (Bulgu 3) | **KOŞUYOR — GEÇTİ** | kütüphane → detay → Kırp → stüdyo açılır; asset çözülemeyen dosyada Uygula DEVRE DIŞI (dürüst durum korunuyor) |
| **S4/S5 UI (b)** | sürülemiyordu | **YAZILDI — gerekçeli skip** | pozitif yarı (Uygula etkin + kanıtsız 417 ekranda) Bulgu W5-1 yüzünden bu satıcı oturumunda veri bulamıyor; backend izni düzelince gövde kendiliğinden koşar |
| S4, S5, S9, S10, S11b-negatif, duman | KOŞUYOR | **KOŞUYOR** (değişmedi) | — |

**Koşum çıktısı:** `9 passed, 2 skipped` (11 test; skip'ler: S11b-pozitif
[önceden] + S4/S5 UI (b) [Bulgu W5-1]).

## 5. Doğrulama

| Kontrol | Sonuç |
|---|---|
| `npm test` | **879 pass / 0 fail** (884 kayıt; 5 skip önceden var olan `ISTOC_CONTRACT=1` kapılı sözleşme testleri). Taban 862 + 9 yeni; kalan fark canlı-backend'e koşullu üretilen testler. Not: bir koşumda `rumCollectorVitals` INP testi zamanlama kaynaklı bir kez düştü, yeniden koşumda geçti — bu görevin dosyaları değil. |
| `npx eslint "src/**/*.{js,vue}"` | **0 error** (2 warning `PlansTab.vue` — önceden var, rapor 75'te de aynı) |
| `npm run build` | **0 hata** |
| Yeni birim testleri | `src/components/media/__tests__/mediaUploaderWiring.test.js` (5 test — kaynak-metin kablo iddiaları) + `src/stores/__tests__/mediaAssetName.test.js` (4 test — `assetNameOf` davranışı, api sahtesiyle). Mevcut test dosyalarına dokunulmadı. |
| **Vacuity** | `:asset="cropAsset"` satırı geçici kaldırıldı → `mediaUploaderWiring` testi **KIRMIZI** ("CropStudioModal seçili öğenin Media Asset adını alır" düştü); geri konunca yeşil. |

## 6. Bilinçli bırakılanlar / kalan açıklar

- **Sayfa içi sürükle-bırak alanı (`mdrop`), `MediaPickerModal` yükle yolu ve
  Explorer** hâlâ eski `store.enqueueUploads` kuyruğunda — o yol slot/boyut
  kapısından geçmiyor. Kapsam "Yükle düğmesi → MediaUploader" idi; kalan yolların
  yükleyiciye taşınması ayrı iş (taşınana dek panelde iki kuyruk arayüzü var:
  modal içi T-091 kuyruğu + sayfadaki `MediaUploadQueue` şeridi).
- Yükleyici modalı KAPANINCA içindeki bileşen sökülür ve süren yüklemeler iptal
  edilir (`useMediaUpload` dispose sözleşmesi). Kısa yüklemelerde sorun değil;
  uzun yüklemede modalı açık tutmak gerekiyor — istenirse kalıcı panel ayrı iş.
- `CropStudioModal`'a kütüphaneden verilen `slot-key` hâlâ sabit
  `company.cover_image` (rapor 75 öncesinden); stüdyonun kendi slot seçicisi
  var, kullanıcı değiştirebiliyor. Dosyanın gerçek slotunu geçmek Bulgu W5-1
  çözülünce anlamlı olur (asset'ten okunabilir).
- E2E izleri: S1 (UI) hiçbir şey yazmıyor (0 istek, ölçüldü); S1b kendi izini
  iddiadan önce siliyor; S9/S10 izleri rapor 75 §5'teki bilinen davranış.
  `get_dimensions` probu `Bere-2.png` için 800×800 değerini kalıcılaştırdı
  (ucun belgelenmiş davranışı; veri değişmedi, ölçü yazıldı).

## 7. Yeniden koşum

```bash
cd admin-panel/frontend
npm test                        # 879 pass (5 env-gated skip)
npm run build
cd ../../docker && docker compose build admin-panel && docker compose up -d admin-panel
cd ../admin-panel/frontend && npm run test:e2e   # 9 passed, 2 skipped
```
