# Frontend tamamlama planı

**Tarih:** 2026-08-19 · **Temel:** canlı ölçüm (ajan raporlarına değil, koda bakılarak)
**Panel testi bugün:** 194 → **640/640**

---

## 1. Ölçülmüş durum — 21 frontend görevi

| Durum | Görev | Not |
|---|---|---|
| ✅ **Kurulu ve bağlı** (13) | T-090 · T-092 · T-093 · T-100 · T-101 · T-102 · T-103 · T-104 · T-110 · T-111 · T-112 · T-113 · T-122 | 21 medya bileşeni, 5 crop parite testi, 8 simülatör bileşeni |
| 🟡 **Kurulu, MONTAJ YOK** (2) | T-114 `SimApprovalGate` · T-120 `MediaVideo` | İkisi de **0 yerde** kullanılıyor |
| 🟡 **Kısmi** (4) | T-091 · T-094 · T-095 · T-121 | Aşağıda gerekçeleri |
| ❌ **Hiç yok** (2) | T-115 drift testi · T-123 RUM | 0 dosya |

### Kısmi olanların gerekçesi (ölçüldü)

- **T-091** — `upload/` dizini VAR, `uppy` **kurulmadı**. Gerekçe: 87 ucun hiçbirinde
  tus başlığı, `PATCH` uploads ucu ya da `Idempotency-Key` **yok**. Sunucu kendi
  parçalı sözleşmesini kullanıyor. Ajan bilinçli kurmadı — konuşacağı uç yok.
  **Engel: SUNUCU PROTOKOLÜ**, frontend işi değil.
- **T-094** — `MediaBulkBar` VAR, **klasör ağacı YOK**. `Media Folder` DocType'ı ve
  taşıma ucu yok; ağaç çizmek olmayan bir işlemi vaat etmek olurdu. **Engel: BACKEND.**
- **T-095** — `axe-core@4.13.0` kurulu ve koşuyor. **2 ihlal kaldı**, ikisi de
  `aria-progressbar-name` (serious).
- **T-121** — `select.js::sizesAttribute` çağrılıyor (1.455 kombinasyonda 0 sapma
  ölçüldü), ama `MediaThumb`'a `region` **geçilmiyor** → kazanç ekrana ulaşmıyor.

---

## 2. Yapılacaklar

### Şerit I — ENTEGRASYON (orkestratör, ajan değil)

Bu dosyalar **tek sahipli**; 6 ajana yasaklandığı için iş burada birikti.

| # | İş | Dosya | Ölçüm |
|---|---|---|---|
| I-1 | **67 i18n anahtarı**, dört dile | `i18n/locales/{tr,en,ar,ru}.js` | 6.318 `t()` çağrısının 67'si `tr.js`'te yok: `media` 36 · `mediaSimulator` 27 · `cropStudio` 4 |
| I-2 | `SimApprovalGate` montajı | `views/system/MediaSimulatorView.vue` | 0 kullanım |
| I-3 | `MediaVideo` montajı | `MediaDetailPanel.vue` · `MediaPreviewModal.vue` | 0 kullanım |
| I-4 | `MediaThumb` `region` prop | `MediaLibraryView.vue:405,489,558` + `MediaCard.vue:17` | `:region` hiç geçilmiyor |
| I-5 | `worker: { format: "es" }` | `vite.config.js` | Ayar **hiç yok**; dinamik import worker'ı üretimi kırıyor |

> **Not:** `adminFeeds` (10), `bulkProductImport` (1), `categoryTranslations` (1)
> anahtarları da eksik ama **bizim işimiz değil** — önceden vardı, dokunulmayacak.

### Şerit II — PARALEL AJANLAR (3)

| Ajan | Görev | Sahip olduğu | Neden ayrı |
|---|---|---|---|
| **FE-1** | T-095 · 2 axe ihlali | `MediaUploadQueue.vue` · `MediaFilterRail.vue` | Ayrı iki dosya, kimse dokunmuyor |
| **FE-2** | **T-115** drift testi | `src/**/__tests__/drift*` + gerekli araç | Faz 11 kapı çıktısı; **hiç yok** |
| **FE-3** | **T-123** RUM | `lib/media/rum/**` + `composables/useRum.js` | Faz 12 kalemi; **0 dosya** |

### Yapılmayacaklar (engel frontend'de değil)

| Görev | Engel | Kim açar |
|---|---|---|
| T-091 tus yükleyici | Sunucuda tus protokolü yok | Backend |
| T-094 klasör ağacı | `Media Folder` DocType + taşıma ucu yok | Backend |

---

## 3. Sıra ve gerekçesi

```
1. Şerit I (orkestratör)   →  ortak dosyalar, tek elde, seri
2. Şerit II (3 ajan)       →  I ile paralel: farklı dosyalar
3. Doğrulama               →  npm test · lint · build · axe yeniden
```

**I-1 önce gelmeli:** 67 anahtar eksikken `mediaSimulator.test.js` gibi
"çözülmemiş anahtar sızmasın" testleri kırılganlaşıyor. C7 bunu `t(key, params,
varsayılan)` üçüncü argümanıyla geçici kapattı; anahtarlar girince o koltuk değneği
gereksizleşir.

---

## 4. Kabul kriterleri

| Kontrol | Hedef |
|---|---|
| `npm test` | **640/640** korunmalı + yeni testler |
| `npm run lint` | EXIT 0, **yeni uyarı yok** (mevcut 2 uyarı `PlansTab.vue`, önceden var) |
| `npm run build` | EXIT 0 |
| `axe` yeniden koşumu | ihlal **2 → 0** |
| Eksik i18n anahtarı | **67 → 0** (bizim önekler; `adminFeeds` vb. hariç) |
| Yetim bileşen | **2 → 0** |

---

## 5. Ajanlara ortak kurallar

Bugün ölçülerek işe yaradığı görülen kurallar:

1. Koşturmadığına **"geçti" DEME**; ölçemediğini **"ölçülmedi"** yaz.
2. **Vacuity kanıtı:** testi yaz, düzeltmeyi geri al, KIRMIZI göster, geri koy.
3. **Süre/FPS iddiası YAPMA** — makine paylaşımlı; bugün çekişme %560 hatalı ölçüm üretti.
4. **Sahte/fixture ile doğrulama yetmez.** Bugün üç yerde test ikizleri yanlış güven
   verdi; bir kez de elle yazılmış a11y assertion'ı `axe`'ın ciddi ihlal bulduğu kodu
   "iyi örnek" diye listelemişti.
5. **`i18n/locales/*`, `router/index.js`, `data/navigation.js`, `vite.config.js`
   YASAK** — orkestratörde.
6. `tradehub_core` ve `docker/` **yasak**.

---

## 6. Kapanış — ölçülmüş sonuç (2026-08-20)

### Kabul kriterleri karşısındaki durum

| Kontrol | Hedef | Ölçülen | |
|---|---|---|---|
| `npm test` | 640/640 + yeni | **736 / 736** | ✅ |
| `npm run lint` | EXIT 0, yeni uyarı yok | **EXIT 0** · 0 hata · 2 uyarı (`PlansTab.vue`, önceden vardı) | ✅ |
| `npm run build` | EXIT 0 | **EXIT 0** (7,57 sn) | ✅ |
| `axe` ihlali | 2 → 0 | **0** — üstelik "axe gerçekten çalışıyor, bilinen ihlali BULUYOR" vacuity testiyle | ✅ |
| Eksik i18n anahtarı | 67 → 0 | **tr 0** · en 1 · **ru/ar 36** (aşağıda) | 🟡 |
| Yetim bileşen | 2 → 0 | **0** — `SimApprovalGate` 1, `MediaVideo` 2 montaj | ✅ |

### Şerit I — yapılanlar

| # | Sonuç |
|---|---|
| I-1 | 67 anahtar dört dile girdi. **tr.js 67 → 0.** Ölçüm sırasında iki metni kısaltmışım, iki test kırıldı (`media.usage.scanNote`, `mediaSimulator.poster.noBudget`) — testler kaynaktaki tam metni bekliyordu; tam metin geri konuldu. |
| I-2 | `SimApprovalGate` **`CropStudioModal.vue`'ye** monte edildi — plandaki `MediaSimulatorView.vue`'ye değil. Gerekçe aşağıda. |
| I-3 | `MediaVideo` → `MediaDetailPanel.vue` + `MediaPreviewModal.vue`. Poster GEÇİLMİYOR: satır modelinde (`useSellerMedia.bicimle`) poster adresi alanı yok; uydurulmuş adres 404 verirdi. |
| I-4 | `region` beş çağrı yerine geçti. Ölçülen çıktı: `rowThumb → 40px` · `cellThumb/kanbanThumb → 36px` · `detailPreview → min(100vw, 416px)` · `libraryGrid → calc((100vw − 360px − 24px) / 3)` üç kırılımlı. **Önce hepsi boştu** → tarayıcı 100vw varsayıp 40 piksellik satır önizlemesi için en büyük basamağı indiriyordu. |
| I-5 | `worker: { format: "es" }` eklendi. Tek işçi (`preflight.worker.js`) `{ type: "module" }` ile kuruluyor ve statik `import` içeriyor; Vite'ın üretim varsayılanı `iife` onu çalıştırılamaz kılıyordu. |

### Plandan sapma: I-2 nereye monte edildi

Plan `MediaSimulatorView.vue` diyordu. Ölçüldü: o ekranın **varlık bağlamı yok** (`asset` prop'u besleyecek bir kaynak yok), kapının `approve` düğmesi orada **kalıcı olarak devre dışı** kalırdı. Bileşenin kendi başlığı da şunu yazıyor: *"Yalnız `previewed_placements` göndermek, uç gönderilmeyen alanları `None` yazdığı için kayıtlı odak noktasını SİLERDİ."* Yani kapının gövdesi, kırpma niyetinin geri kalanıyla **aynı** `save_intent` çağrısında gitmeli.

Bunu yapabilen tek ekran `CropStudioModal.vue` — `asset`, `source` ve kaydetme onda. `useCropStudio.save()` isteğe bağlı bir `ek` parametresi aldı; onaylanan yerleşimler Uygula'nın gövdesine katılıyor, **ikinci bir yazma yapılmıyor**.

Bedeli dürüstçe yazılsın: kapının "Bu yerleşime git" düğmesi simülatörde cihaz/bölge değiştirirdi; kırpma ekranında gidilecek simülatör yok, düğme önizleme şeridine kaydırıyor. Daha zayıf ama ölü değil.

### Şerit II — üç ajan

| Ajan | Sonuç |
|---|---|
| **FE-1** (T-095) | 2 axe ihlali → **0**. Vacuity kanıtı testte duruyor. |
| **FE-2** (T-115) | `drift-measurements.json` **219 KB**. Yeni bağımlılık yok — kurulu Chrome, ham CDP ile sürüldü (Playwright üç ajanın paylaştığı `node_modules`'ü değiştirirdi; CSS'ten türetmek ise kataloğu üreten yöntemin aynısı olurdu, yapı gereği katalog hatasını bulamazdı). **13 cihaz × 12 bölge = 85 ölçüm; 25 satır 2px eşiğini aşıyor, en büyük sapma 80,68 px.** Eşik gevşetilmedi; `drift-measure.mjs` herhangi bir sapmada 1 ile çıkıyor. |
| **FE-3** (T-123) | İstemci RUM halkası kuruldu (11 kaynak + 7 test, 84/84). Gövde şekli `rum.py`'nin SHA-256'sına bağlandı — ayrışırsa test kırılır. |

### Kapanmayan üç kalem

1. **RUM montajı yapılmadı** (`main.js`'te tek satır olurdu). Bağımsız doğrulandı: `@frappe.whitelist()` RUM ucu **yok**, `Media RUM Sample` DocType'ı **yok**, `rum.ROUTE_TEMPLATES` yalnız 7 storefront rotası + `other` içeriyor — panelin hiçbir rotası listede değil. Monte etseydim her oturumda 404 üretir, sayfa tipi kırılımı yine oluşmazdı. **Engel: BACKEND ucu + doğru ev storefront.**
2. **`media` ad alanı `ru.js` ve `ar.js`'te hiç yok** — 329 anahtar. Bugünün işi değil, **önceden de yoktu**; 36 `media.*` anahtarım bu yüzden o iki dile giremedi (`mediaSimulator` ve `cropStudio` girdi). Ayrı bir çeviri işi.
3. **T-091 / T-094** planın "yapılmayacaklar"ında kaldı — engelleri sunucuda.

### FE-2'nin bulduğu dört katalog hatası (T-110 kataloğu, `placements.json`)

T-110'un kendi ölçütü: *"sapma varsa doğru olan uygulamanın CSS'idir, katalog düzeltilir."* Yani bunlar testin hatası değil, **kataloğun** hatası:

| Bölge | Ölçülen | Sapan | En büyük \|Δ\| | Kök neden |
|---|---:|---:|---:|---|
| `seller_shop/product_grid` | 12 | 6 | **80,68 px** | `seller_shell` ~240px'lik CompanyProfile yan sütununu **hiç çıkarmıyor** |
| `home/top_deals` | 13 | **13** | 8,11 px | `TopDeals.ts:212` sarmalayıcı dolgusu (`var(--space-card-padding)`, 8→14,08px, görünüm alanına bağlı) modellenmemiş |
| `cart_checkout/summary_strip` | 13 | 2 | 8,00 px | katalog 380px basamağını `CartSummary.ts`'ten alıyor, ama `/sepet` `alpine/cart.ts:639`'u basıyor (`w-14 sm:w-16` — 380px kırılımı yok) |
| `home/hero_showcase_grid` | 13 | 4 | 2,01 px | `ListingCard.ts:405` kart sarmalayıcısının 1px kenarlığı ×2 |

Dört bölge **tam isabet**: `listing/card_grid` + üç PDP bölgesi, 21 örnekte 0,00 px.

**Bağımsız doğrulama (orkestratör):** `placements.json`'da `product_detail_shell` sağ rayı açıkça çıkarıyor (`derived_from`: "çıkarılan = sağ ray + 16px gap (394+16=410 / 300+16=316)"), `seller_shell` ise yalnız `max_width: 1200` + dolgu tanımlıyor, **hiçbir şey çıkarmıyor**. Asimetri kaynakta görünür durumda — FE-2'nin kök neden iddiası yapısal olarak tutuyor.

**Sapma bayatlık değil:** `istoc.localhost` eski imajı servis ediyor (paket özetleri farklı). FE-2 önce güncel kaynaktan yapılmış bir derlemeye karşı ölçtü, sonra 2 cihazı dağıtılmış imaja karşı çapraz kontrol etti — **14 ölçümün hepsi birebir aynı**. İki bağımsız derleme, aynı sapma.

**FE-2'nin kendi söylediği eksikler:** ekran görüntüsü / piksel farkı **yok** (yalnız kutu ölçümü); **gecelik iş ve bildirim kanalı bağlanmadı** — betik hazır ve belgeli ama cron/CI işi yok.

> **Karar bekliyor:** kataloğun düzeltilmesi bu planın kapsamı dışında. İki kopya var (`tradehub_core/.../simulator/placements.json` kaynak, `admin-panel/.../vendor/placements.json` türev) ve eşzamanlı kalmaları gerekiyor. Düzeltme `sizes`/`srcset` seçimini hem panelde hem storefront'ta değiştirir.
