# 89 — W7: Panel Faz 9 kalanları (T-093 sürüm çekmecesi · T-095 axe genişletme · W5-1 E2E kanıtı)

Tarih: 2026-08-20 · Repo: `admin-panel/frontend` (+ site operasyonu, aşağıda) · Commit atılmadı (talimat).

---

## 1. T-093 — Detay çekmecesi SÜRÜM sekmesi artık gerçek veri basıyor

### Ne değişti
`Media Version` W4'te gerçek ve zengin hâle geldi (rapor 73); `manifest_batch`
yanıtı `version` anahtarını taşıyor. Çekmecedeki "Sürüm izleme kurulu değil"
notu artık YALAN olurdu — bölüm gerçek veriyle değiştirildi:

- **Veri yolu:** `useMediaRenditions` composable'ına `version` ref'i eklendi —
  türev sekmesiyle AYNI `manifest_batch` yanıtından okunur, **ikinci istek
  atılmaz, yeni uç yazılmadı**. (`src/composables/useMediaRenditions.js`)
- **Ekran:** `MediaDetailPanel.vue` Sürüm sekmesi; diğer sekmelerle aynı
  tembellik (`seen` kaydı — ziyarete kadar ne DOM ne istek). Künye satırları:
  durum (yayında / en yeni), ölçü, DPI, renk uzayı, alfa, sınıflandırma
  (+güven), format zinciri, sürüm özeti (12 hex + tam hash `title`ta).
- **Dürüst boş durumlar:** sürüm kaydı yoksa `versions-none` ("boru hattı
  henüz bir sürüm üretmedi"), yetki reddi ayrı, arıza ayrı — boş tablo ve
  "—" satırlarıyla yokluk/ölçülmemişlik karıştırılmıyor.

**Canlı ölçüm** (rebuild edilmiş panelde, satıcı oturumu, `Bere-2.png`):
`Durum: En yeni (yayında değil) · Ölçü: 800×800 · DPI: 72 · Renk uzayı: sRGB ·
Alfa: Yok · Sınıflandırma: photo (güven: low) · Format zinciri: AVIF → WEBP →
JPEG · Sürüm özeti: 5ba6043d0991` — ekran görüntüsüyle doğrulandı.

### Yeniden işle
**Ölçüldü:** backend'de `reprocess` adında whitelist ucu YOK
(`grep`: yalnız `media/pipeline/image/reprocess.py` iç modülü ve
`pipeline_bridge._run_rendition_job` — yükleme kancasından koşuyor). Uç
EKLENMEDİ (talimat); düğme mevcut akışa bağlandı:

- `useMediaOptimize.start({ fileNames: [item.docName] })` — tekil dosya;
  koşum durumu MEVCUT job-polling'den (`get_optimization_status`, 3 sn).
- İzin: yalnız `editable` görünümde. Uç rol korumalı
  (`media_admin._guard`: System Manager / Marketplace Admin) — yetkisiz
  oturumda sunucu reddi toast'ta görünür, sahte başarı yok.
- `useMediaOptimize`'a `{ refreshOnDone }` seçeneği eklendi (varsayılan
  `true` — denetim ekranı davranışı DEĞİŞMEDİ). Detay paneli `false` verir:
  envanter listesi göstermeyen bir yüzeyin iş sonunda satıcı oturumunda
  yetkisiz `get_image_inventory` çağrısı atması hem gürültü hem yanlış olurdu.
  İş bitince bunun yerine SÜRÜM yeniden okunur.

### Vacuity kanıtı (KIRMIZI gösterildi)
`useMediaRenditions.js`'te `version.value = manifest.version || null` satırı
kesilerek yeni test koşuldu: **2 test KIRMIZI** —
`manifest.version alanları composable'a BİREBİR akar` (`actual: undefined,
expected: 72`) ve `clear() sürümü de sıfırlar`. Tel geri bağlandı → 6/6 yeşil.

### Testler
- Yeni: `src/components/media/__tests__/mediaVersionSection.test.js` (6 test):
  alan-alan veri akışı (canlı yanıttan alınan fixture), sürümsüz manifest →
  `null` (boş nesne uydurulmaz), `clear` sıfırlaması, "kurulu değil" yalanının
  kalktığı + tembellik (SSR'da istek yok), künye satırı sözleşmesi, yeniden
  işle kablosunun `useMediaOptimize`'a bağlı olduğu (yeni uç yok).
- Güncellenen: `mediaDetailDrawer.test.js` — eski "notInstalled her zaman
  DOM'da" iddiaları yeni sözleşmeye çevrildi (sürüm sekmesi de tembel);
  i18n anahtar listesi tazelendi. (Dosya sahiplik listemde değildi ama
  doğrudan benim dosyamın eski sözleşmesini iddia ediyordu — güncellenmeden
  taban yeşil kalamazdı.)

---

## 2. T-095 — axe kapsamı 8 → 14 yüzey

`mediaAxe.test.js` genişletildi; **mevcut 4 test korundu**, 3 test eklendi:

| Yeni taranan yüzey | Sonuç |
|---|---|
| MediaDetailPanel (sekmeli çekmece, düzenlenebilir) | 0 engelleyici |
| SimVideoDecisionCard (ölçülmüş künye) | 0 |
| SimApprovalGate (varlıklı, hidrasyon ÖNCESİ hâl) | 0 |
| MediaFolderGrid (dolu + boş durum) | 0 |
| MediaCrumbs (iki seviye) | 0 |
| MediaFilterRail — öksüz bölümü AÇIKKEN (localStorage sahtesiyle açılıyor; `v-show` kapalı içeriği axe taramaz) | 0 (taban ≤2 komşu deseni) |
| **MediaUploader (slot politikalı)** | **2 engelleyici — aşağıda** |

### Bulgu (başkasının dosyası — DÜZELTİLMEDİ, raporlandı)
İkisi de `src/components/media/upload/UploadDropzone.vue` içinde (yükleme
bileşenleri W7-2/W5-B'nin — bu görevde dokunulmaz):

1. **`label` [critical]** — gizli `<input type="file">`'ın erişilebilir adı
   yok (görünür `<label>`/`aria-label` bağlanmamış).
2. **`nested-interactive` [serious]** — `role="button"` verilmiş bırakma
   alanının İÇİNDE odaklanabilir input; `tabindex="-1"` axe'e yetmiyor.

Komşu-taban deseniyle kilitlendi (`UPLOADER_BASELINE = 2`): düzeltilirse test
yine geçer, ÜÇÜNCÜ bulgu eklenirse kırılır.

### Ölçüm sınırları (değişmedi + yeni)
- Teleport'lu diyaloglar (`MediaModal`/`MediaPreviewModal`/`MediaPickerModal`)
  hâlâ kapsam DIŞI — SSR'da teleport hedefi yok.
- `SimApprovalGate` mount SONRASI IntersectionObserver ile durum değiştirir;
  ölçülen hidrasyon öncesi ilk hâl.
- Öksüz bölümünün DOLU liste hâli ölçülmedi (veri `onMounted`ta yükleniyor,
  SSR'da "taranıyor" hâli görünür).

---

## 3. W5-1 — izin düzeltmesinin E2E kanıtı

### Ölçülen engel: düzeltme SİTEDE değildi
`media_asset.json`'dan `if_owner` kaldırılmıştı (kaynak + konteyner içi dosya
doğrulandı) ama **DB'deki `tabDocPerm` hâlâ `if_owner: 1` taşıyordu** — migrate
edilmemişti. Satıcı oturumunda hem konsol (`set_user` + `get_list`) hem HTTP
(`manifest_batch`) **boş** dönüyordu.

**Uygulanan operasyon** (backend KODU değişmedi; orkestratörün kendi
düzeltmesi siteye dar kapsamla işlendi):
`frappe.reload_doc("tradehub_core", "doctype", "media_asset")` + commit +
`clear-cache` — tam `bench migrate` bilinçli KOŞULMADI (paylaşımlı çalışma
ağacında diğer ajanların yarım şema işlerini sürüklememek için).
Sonuç DocPerm: 4 rolde de `if_owner: 0`.

### Pozitif kanıt (W5-1 kapanışı)
Satıcı oturumuyla (ali.bal, `playwright/.auth/seller.json` sid'i, HTTP):

```
manifest_batch(["bd5b581362", …]) →
  bd5b581362  assets: ['7pa8r42g7d']  version: true  renditions: 10
  14a207158c  assets: ['7pa8r42g7d']  version: true  renditions: 10   ← mükerrer File, file_url köprüsü çalışıyor
```

### E2E sürüşü — `tests/e2e/media-crop-approval.spec.ts`
| Koşum | Sonuç |
|---|---|
| Önce (izin düzeltmesi sitede yokken, tarihi durum) | 2 pass + S4/S5 UI yarıları skip/koşamaz |
| Bu turun taban ölçümü | 3 pass · 1 fail — (b)'nin skip'i kalkmıştı ama gövde düşüyordu |
| **Sonra (sürüş + imaj rebuild + izin uygulaması)** | **4/4 pass** |

**(b)'nin düşüş kökü — canlı tarayıcıda enstrümante edilerek ölçüldü** (asset
kablosu SAĞLAMDI): test "varlığı çözülen İLK dosyayı" seçiyordu ve bu, bugünkü
güvenlik E2E'lerinden kalma **32 px'lik** bir dosyaya denk geldi
(`e2e-after-malicious-…webp` — `rendition_on_upload` açık olduğu için varlık
kazanmış). 32 px kaynakta HER slot politikası kadrajı BLOK'lar
("Short edge after crop is 32 px — policy requires at least 96 px") ve Uygula
dürüstçe kapalı kalır (FR-028 upscale yasağı). Ek ölçüm: `product.image`
`minShortEdge: 1000` — 800×800'lük gerçek varlık kaynağı da o slotta bloklanır.

**Sürüş (yalnız spec dosyasında):**
- Hedef seçimi: varlığı çözülen görseller arasından **kısa kenarı en büyük**
  olan; <96 px ise gerekçeli skip.
- Kart tıklaması ilk karta değil hedefin kartına (`aria-label` ile) — arama
  alt-dizgi eşleştiriyor.
- Kaynak <1000 px ise `product.image`'ta Uygula'nın POLİTİKA gereği kapalı
  kaldığı AYRICA doğrulanır, sonra politikayı geçen `user.avatar`
  (minShortEdge 96) seçilip pozitif yarı sürülür: **Uygula etkin → kanıtsız
  kayıt → sunucu 417 MEDIA_PREVIEW_REQUIRED → ret modalda görünür.**
- (a) testi de güncellendi: izin düzeltmesi sonrası "asset çözülmeyen dosya"
  artık AÇIKÇA seçilmek zorunda (eskiden her dosya öyleydi).

İmaj: `docker compose build admin-panel && up -d admin-panel` (dist imajda).

---

## 4. Doğrulama

| Ölçüm | Önce | Sonra |
|---|---|---|
| `npm test` | 906 test · 899 pass · **2 fail** · 5 skip (koordinatörün gördüğü "2 kırık") | **906 test · 901 pass · 0 fail · 5 skip** |
| `npm run lint` | — | 0 hata (2 eski `PlansTab.vue` uyarısı, dokunulmadı) |
| `npm run build` | — | 0 hata (8.2 sn) |
| e2e `media-crop-approval` | 3 pass · 1 fail | **4/4 pass** |

Öncedeki 2 kırık BU görevin kodundan değildi — ikisi de bugünkü backend
`video_decision.json` değişikliğinin panel yankısıydı:
1. İki simülatör drift testi (`srcsetParity` + `videoDecision` hash denetimi)
   vendor kopyanın bayatladığını söylüyordu; testlerin kendi reçetesi koşuldu:
   `npm run sync:simulator` (üretilen: `src/lib/media/simulator/vendor/
   video_decision.js`, `parity_vectors.json`).
2. Sync SONRASI `videoDecision.test.js`'teki bir sabit iddia düştü:
   test /ÖLÇÜLEMEZ/ arıyordu ama yeni imaj **libvmaf'LI** ve `vmaf_note`
   "VMAF artık gerçekten ölçülüyor" diye güncellenmişti — eski gerçekliği
   dayatan literal, notun kalıcı taahhüdüne çevrildi
   (/sahte VMAF üretilmez/ + notun vendor'dan birebir basıldığı korunuyor).

Bir ara koşumda `contract.live.test.js` 429 (rate limit) gördü — aralıklı,
kod sorunu değil; kapanış koşumu temiz.

---

## 5. i18n — eklenmesi gereken anahtarlar (locales YASAKTI; `t(k, {}, "TR varsayılanı")` deseniyle yazıldı, ekran bugün Türkçe basıyor)

`media.versions.*`: `title` ("Sürüm") · `none` · `loading` · `denied` ·
`failed` · `activeScopeNote` · `active` · `latest` · `confidence` ·
`attr.state` · `attr.dimensions` · `attr.colorspace` · `attr.alpha` ·
`attr.classification` · `attr.formatChain` · `attr.hash` · `alphaYes` ·
`alphaNo` · `reprocess` · `reprocessRunning` · `jobRunning` ("{done}/{total}
işlendi") · `jobOptimized` · `jobSkipped` · `jobErrors` ·
`jobState.completed/partial/error/not_found`.

Artık KULLANILMAYAN eski anahtarlar: `media.versions.notInstalled`,
`media.versions.scopeNote` (bölüm gerçek veriye geçti).

Benden ÖNCE eksik olup ekranda ham anahtar görünenler (başka işin kapsamı):
`media.detail.tabsLabel`, `media.detail.tab.summary/renditions/usage/quality/versions`
(sekme şeridi — ekran görüntüsünde görülüyor), `media.uploader.title`,
`media.uploader.dropAria`, `media.uploader.dropTitle` (axe koşum günlüğü).

---

## 6. Dokunulan dosyalar

| Dosya | İş |
|---|---|
| `src/components/media/MediaDetailPanel.vue` | Sürüm bölümü + yeniden işle (T-093) |
| `src/composables/useMediaRenditions.js` | `version` ref'i — aynı yanıttan, ek istek yok |
| `src/composables/useMediaOptimize.js` | `{ refreshOnDone }` opsiyonu (varsayılan davranış değişmedi) |
| `src/components/media/__tests__/mediaVersionSection.test.js` | YENİ — 6 test + vacuity |
| `src/components/media/__tests__/mediaDetailDrawer.test.js` | Sözleşme güncellemesi (eski "kurulu değil" iddiaları) |
| `src/components/media/a11y/__tests__/mediaAxe.test.js` | 8 → 14 yüzey; uploader taban çizgisi |
| `tests/e2e/media-crop-approval.spec.ts` | Skip kaldırma + sürüş (hedef seçimi, slot politika dalı) |
| `src/components/media/simulator/__tests__/videoDecision.test.js` | Bayat /ÖLÇÜLEMEZ/ literalinin libvmaf sonrası gerçekliğe çevrilmesi |
| `src/lib/media/simulator/vendor/*` | `npm run sync:simulator` çıktısı (drift reçetesi) |
| — site operasyonu | `reload_doc(media_asset)` + `clear-cache` (W5-1'in DB'ye işlenmesi) · panel imaj rebuild |

Süre iddiası yok.
