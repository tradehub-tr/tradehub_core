# 61 — 102 görevin frontend payı: birleşik denetim

**Tarih:** 2026-08-20 · **Yöntem:** 7 paralel ajan, her biri bir faz dilimi, hepsi salt-okunur
**Kaynak pano:** `91-gorev-panosu.html` (102 görev) · **Karşılaştırılan kod:** `admin-panel/frontend`, `tradehubfront`
**Dilim raporları:** `61a` (Faz 0-1) · `61b` (2-3) · `61c` (4-5) · `61d` (6-7) · `61e` (8-9) · `61f` (10-11) · `61g` (12-14)

---

## 1. Sayım

| Durum | Adet | Frontend payı olanların içinde |
|---|---:|---:|
| **TAM** | 15 | %25 |
| **KISMİ** | 33 | %55 |
| **YOK** | 11 | %18 |
| **ÖLÇÜLEMEDİ** | 1 | %2 |
| **FE-DIŞI** (frontend payı yok) | 42 | — |
| **Toplam** | **102** | **60** |

102 görevin **42'sinin frontend payı yok** (saf backend/DevOps/analiz). Geriye kalan
**60 görevin yalnız 15'i tam**; 33'ü kısmi, 11'inde frontend hiç yok.

### Faz bazında

| Faz | Görev | TAM | KISMİ | YOK | FE-DIŞI | Ölçülemedi |
|---|---:|---:|---:|---:|---:|---:|
| 0-1 Analiz + AR-GE | 20 | 1 | 4 | 0 | 15 | 0 |
| 2-3 Standartlar + Mimari | 16 | 0 | 7 | 3 | 6 | 0 |
| 4-5 Veri modeli + Depolama | 11 | 2 | 2 | 1 | 6 | 0 |
| 6-7 Görüntü + Video motoru | 14 | 0 | 6 | 2 | 6 | 0 |
| 8-9 API + Medya kütüphanesi | 12 | 0 | 9 | 2 | 1 | 0 |
| **10-11 Crop + Simülatör** | 12 | **10** | 1 | 0 | 0 | 1 |
| 12-14 Teslim + Güvenlik + Kabul | 17 | 2 | 4 | 3 | 8 | 0 |

**Tek olgun ada Faz 10-11.** 12 görevin 10'u tam. Bunun dışındaki her fazda
baskın durum KISMİ.

---

## 2. Neden bu kadar çok "KISMİ" — üç kök neden

### 2.1 Kod yazıldı, veri akmıyor (Faz 6-7'nin tamamı)

`media_pipeline_enabled` varsayılan **0** (`patches/v15_9_22_media_engine_settings.py:24`).
Panelin türev listesi, kalite paneli, LQIP tesisatı — hepsi yazılmış ve test edilmiş
ama arkalarında satır yok. Ekranlar bunu **dürüstçe ilan ediyor** (uydurma sayı
göstermiyorlar), o yüzden bu bir kusur değil bir **bekleme** durumu; ama görev
"yapıldı" da sayılamaz.

### 2.2 Şartnamenin istediği artefakt yerine işlevsel ikame

- **T-033**: `ui/src/policy/engine.ts` (Python ile birebir sonuç veren TS PolicyEngine) **yok**.
  En yakın aday `preflight.js` ve kendi belgesi *"karar VERMEZ, hızlandırır, son söz sunucunun"* diyor.
- **T-091**: Uppy/tus **yok**; yerine Web Worker + eşzamanlılık 2 + kendi resumable
  protokolü var. Sunucuda tus olmadığı için bu bilinçli.
- **T-015**: exifr/Pica/jSquash **yok**; yerine `createImageBitmap` + `browser-image-compression` + `mediabunny`.

Üçü de çalışıyor ama üçü de şartnamenin adını verdiği şey değil. "Kurulu ama farklı."

### 2.3 Zincirin bir halkası kopuk

- **T-123 RUM**: istemci halkası iyi yazılmış, **`main.js`'te monte değil**, backend ucu **yok**,
  `Media RUM Sample` DocType'ı **yok**. Üç halkanın üçü de eksik.
- **T-043 Kullanım takibi**: kalıcı index yok, istek-anı tarama var; Orphan Report ekranı yok.
- **T-114 Onay kapısı**: istemci kapısı çalışıyor, **sunucu tarafı zorlama yok** — kod bunu kendi itiraf ediyor.

---

## 3. En sert üç bulgu

### 3.1 RU/AR çevirisi medya ekranlarının %83'ünde yok
**766 / 917 anahtar** Rusça ve Arapça'da hiç yok (ölçüm: Faz 8-9 dilimi).
Yalnız `mediaStorage` ve `mediaSimulator` ad alanları tam. T-090…T-094'ün ürettiği
asıl ekranlar (`media.*`, `mediaAudit`, `mediaOptimize`) bu iki dilde **sıfır anahtar**.
Bu, bugünün işi değil — önceden de yoktu.

### 3.2 Faz 14'ün üç kalemi hiç başlamamış
- **T-140** izlenebilirlik matrisi: FE testlerinde `[FR-012]` tarzı etiket **sıfır**.
- **T-141** E2E: 12 zorunlu medya senaryosundan **hiçbiri** yazılmamış.
- **T-143** backfill: satıcı bildirim paneli (şartnamede açıkça isteniyor) **hiçbir yüzeyde yok**.

### 3.3 Belgeler koddan geride
Faz 10-11 dilimi T-113 için belgenin "yazılmadı" dediğini, kodun ise 727 satırlık
`SimPosterCard.vue` ile tam olduğunu ölçtü. Faz 8-9 dilimi ise yerel
`faz9-media-library.md` (18 Ağustos) ile bugünkü kod arasında **45 yeni dosya /
3.355 satır** fark buldu. Belgeye bakarak durum çıkarmak bugün yanıltıcı.

---

## 4. Ajan bulgusunun düzeltilmesi

**T-082 — Faz 8-9 dilimi "kaydetme ucu yok, `useCropStudio.js`'de sıfır API çağrısı" dedi. Bu YANLIŞ.**

Ölçüldü:
- `src/lib/media/crop/cropIntentApi.js:19` → `SAVE_METHOD = "tradehub_core.api.media_crop.save_intent"`
- `src/composables/useCropStudio.js:596` → `saveCropIntent` çağrılıyor
- `tradehub_core/api/media_crop.py:410-411` → `@frappe.whitelist() def save_intent`

Ajan büyük olasılıkla `MediaLibraryView.vue`'daki **bayat bir yorumu** okudu. Faz 10-11
dilimi aynı çelişkiyi bağımsız olarak yakaladı ve `CropStudioModal.vue`'nun "artık var"
diyen yorumunun doğru olduğunu söyledi. T-082'nin kaydetme yolu **canlı**; sınıflandırması
yeniden bakılmalı.

> Ders, bugün üçüncü kez tekrarlandı: **yorum satırı kanıt değildir.**

---

## 5. Denetimin kendi sınırı

Denetim, orkestratörün Şerit I ve katalog düzeltmesini **yaptığı sırada** koştu. Bu
yüzden birkaç sonuç uçuş hâlindeki bir kod tabanını yansıtıyor:

- **T-120** (`MediaVideo` montajı) ve **T-121** (`MediaThumb region` prop'u) denetim
  sırasında TAM'a geçti — ikisini de aynı gün orkestratör bağladı. Öncesinde
  `MediaVideo` **0 yerde** kullanılıyordu.
- **T-114** (`SimApprovalGate`) aynı şekilde: denetimden birkaç saat önce 0 montajdı.
- **T-110 / T-115** için Faz 10-11 dilimine `placements.json` ve `driftBaseline.js`
  üzerine hüküm kurmaması söylendi (o sırada düzeltiliyorlardı); "yapı var mı"
  sorusuna cevap verdi, "değerler doğru mu" sorusuna değil. O soruyu drift ölçümü
  ayrıca yanıtladı: dört sapma bulundu, dördü de düzeltildi.

Hiçbir ajan tarayıcıda gerçek performans/LCP/CLS ölçmedi; hiçbiri süre iddiası yazmadı.
