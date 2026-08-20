# 47 — T-100 / T-101 · Crop çekirdeği: parite kapısı ve piksel paritesi

**Tarih:** 2026-08-19 · **Depo:** `admin-panel` (branch `ahmet`) · **Görev:** T-100, T-101
**Kaynak kriterler:** `tradehub_core/docs/ui/faz10-crop-studio.md`

---

## 0. Özet — ne ölçüldü, ne ölçülmedi

| Konu | Durum |
|---|---|
| Geometri hesabı paritesi (592 vektör) | **ÖLÇÜLDÜ** — 584 değer + 8 hata vakası, en büyük sapma **0 px** |
| Parite kapısının Node sürümünden bağımsızlığı | **ÖLÇÜLDÜ** — tip soyma KAPALI iken 72/72 geçiyor |
| UI ↔ sunucu **piksel** paritesi | **ÖLÇÜLDÜ (yeni)** — 600 vaka, 5 sınıf; 3 sınıfta ciddi ayrışma bulundu |
| Sunucunun ürettiği **görselin** pikselleri | **ÖLÇÜLMEDİ** — render + görsel karşılaştırma gerekir, bu depodan koşturulamaz |
| Tarayıcıda davranış, DPR ≥ 2 tutamak isabeti, süre/FPS | **ÖLÇÜLMEDİ** — tarayıcı doğrulaması yapılmadı, süre iddiası yok |

İki gerçek eksik vardı; **birincisi kapatıldı**, **ikincisi ölçüldü ve üç ayrı ayrışma
bulundu** (kapatılması panel-dışı kararlar gerektiriyor, §3.4).

---

## 1. Parite kapısı neden kırmızıydı ve nasıl çalışır hâle geldi

### Kök sebep

`tradehub_core` konteynerinde:

```
node v20.19.2: bad option: --experimental-strip-types
```

Node'un tip soyma özelliği 22.6'da deneysel bayrakla geldi, 22.18'de varsayılan oldu;
**20.x'te hiç yok.** Panelin geometri kapısı (`src/lib/media/crop/geometry.js`) doğrudan
`vendor/crop_geometry.ts`'i içe aktardığı sürece parite ölçümü "Node yeterince yeni mi"
sorusuna bağlı kalıyordu ve o soru CI'da HAYIR yanıtlıyordu. Yani **TS ↔ Python paritesi
ölçülmüyordu; kapı yalnızca kırmızı yanıyordu.** İkisi aynı şey değil: ölçülmeyen bir
kapı, geçmeyen bir kapıdan daha tehlikelidir, çünkü kırmızının sebebi "ayrıştı" sanılır.

### Değerlendirilen üç yol

| # | Yol | Neden seçilmedi / seçildi |
|---|---|---|
| 1 | `tsx` / `ts-node` bağımlılığı | Yeni bağımlılık + yeni koşucu. `admin-panel/CLAUDE.md` kural 11: "yeni dependency: sor". Bedeli en yüksek olan. |
| 2 | Parite testini Vite'ın `ssrLoadModule`'üne taşımak | Çalışır, ama parite kapısını bir bundler'a bağlar; `node --test`in yalın koşumu kaybolur. |
| 3 | **Senkron adımında tipleri sil, `.js` üret** | **SEÇİLDİ.** Türetme zaten kurulu bir devDependency ile (Vite'ın `transformWithEsbuild`'i) yapılır, çıktı sha256 zincirine girer, koşum tarafında hiçbir bayrak/araç gerekmez. |

### Neden bu bir "ikinci uygulama" değil

`transformWithEsbuild(loader: ts, target: esnext)` yalnız **tip sözdizimini siler**;
hedef `esnext` olduğu için tek bir ifade bile yeniden yazılmaz (downlevel yok). İkiz
`enum`/`namespace`/parametre-özelliği kullanmıyor (T-100 `tsc --erasableSyntaxOnly` ile
temiz ölçmüştü), yani silme **kayıpsızdır**. Parite açısından kritik olan iki şey —
işlem sırası ve `Math.floor(v + 0.5)` — üretilen dosyada birebir duruyor
(`vendor/crop_geometry.js:30`). Ve bu bir iddia değil: **592 vektörün tamamı artık
üretilen `.js` üzerinden koşuyor.**

### sha256 zinciri korundu — üç halka

```
tradehub_core/.../crop_geometry.ts ──sha256──▶ vendor/crop_geometry.ts
                                   ──sha256──▶ vendor/crop_geometry.js
```

`vendor.manifest.json` şema sürümü `1.0.0 → 1.1.0`; yeni `turetilmis` bölümü türetilen
dosyanın hem kendi hash'ini hem **hangi `.ts`'ten üretildiğini** taşıyor. Üç halkanın
üçünü de `cropGeometryParity.test.js` her koşuda doğruluyor; elle düzenlenmiş ya da
eskimiş bir `.js` testi düşürür.

### Kanıt (koşturuldu)

```
$ npm run parity:crop
> node scripts/sync-crop-geometry.mjs --check && node --test src/lib/media/crop/__tests__/*.test.js
ℹ tests 72 · pass 72 · fail 0 · skipped 0        (exit 0)

$ node --no-experimental-strip-types --test src/lib/media/crop/__tests__/*.test.js
ℹ tests 72 · pass 72 · fail 0
```

İkinci komut kapının **tip soymaya bağlı olmadığının** doğrudan kanıtı: Node 24'te
özellik açık geliyor, bayrak onu kapatıyor ve suite yine de tamamen geçiyor.
(Node 20.19.2 bu makinede kurulu değil — o sürümde koşum **ölçülmedi**; ölçülen şey,
kapının artık tip soyma özelliğini hiç kullanmadığıdır.)

`npm run parity:crop` script'i bilerek **glob'suz** yazıldı (`__tests__/*.test.js` kabuk
tarafından açılır): `node --test "glob"` desteği 22 ile geldi, kabuk genişletmesi her
sürümde çalışır.

### Geometri paritesi — güncel rakamlar

```
✔ 592 vektörün tamamı panelin geometri kapısından geçiyor
  değer vektörü 584 · hata vakası 8 · en büyük sapma 0 px
✔ vendor kopyaları manifestteki sha256 ile birebir
✔ manifest canlı tradehub_core kaynağıyla uyuşuyor
✔ türetilmiş crop_geometry.js manifestteki zincire uyuyor
✔ kırpma kapısı hiçbir yerde .ts içe aktarmıyor
```

584 vektörde **0 px** sapma korundu — türetilmiş `.js` üzerinden.

---

## 2. "Parite" iki ayrı şeydir — bu ayrım raporun en önemli cümlesi

**T-100'ün ölçtüğü (ve bugüne kadar tek ölçülen):**
> Aynı girdilerle `crop_geometry.ts` ile `crop_geometry.py` **aynı sayıyı** üretiyor mu?
> → 592 vektör, 0 px. Bu, iki dilin aynı FONKSİYONU aynı yazdığının kanıtıdır.

**T-105'in istediği (bugüne kadar ölçülmemiş):**
> Kullanıcının ekranda gördüğü kadraj ile sunucunun gerçekten **keseceği kutu** aynı mı?

İkisi birbirinin yerine geçmez, çünkü arada üç dönüşüm var ve hiçbiri geometri
vektörlerinde görünmez:

1. Panel kadrajı **kaydetmez, odağı kaydeder** (INV-10). Sunucu pencereyi o odaktan
   **yeniden kurar** — `crop_geometry.py` ile değil, `core/crop.py`'nin beş seviyeli
   zinciriyle (`override → safe_focal → focal → smartcrop → center`).
2. Yuvarlama iki tarafta **farklı uzayda, farklı ifadeyle** yapılır:
   - panel `roundWindow`: kaynak pikselinde `floor(v + 0.5)` → yarım **YUKARI**
   - sunucu `to_pixels`: normalize uzayda `int(round(v))` → Python'da yarım **ÇİFTE**
3. `savePayload` `focal_x`'i **6 basamağa** yuvarlar. 72 MP kaynakta 1e-6 ≈ 0,009 px;
   yuvarlama sınırına denk gelirse 1 px'e büyür.

---

## 3. UI ↔ sunucu piksel paritesi — yeni ölçüm

### 3.1 Yöntem (üç adım, üçü de yeniden koşturulabilir)

| Adım | Dosya | Ne yapar |
|---|---|---|
| 1 | `scripts/gen-crop-pixel-cases.mjs` | Panelin **gerçek** `useCropStudio`'sunu koşturur (yeniden yazılmış kopya değil), tohumlu jest dizileri oynatır; her vaka için son durumu, `savePayload`'ı ve `pixelBox`'ı yazar |
| 2 | `scripts/gen_crop_pixel_vectors.py` | Aynı yükü `tradehub_core/.../core/crop.py`'nin zincirine verir, `to_pixels` ile sunucunun piksel kutusunu yazar |
| 3 | `src/lib/media/crop/__tests__/cropPixelParity.test.js` | Paneli **canlı** yeniden koşturur (fixture eskimişse ölçümü GEÇERSİZ ilan eder), iki kutuyu karşılaştırır |

`tradehub_core`'a **yazılmadı**: python script'i `core/crop.py`'yi yolundan yükler
(modül saf Python; frappe/bench gerekmiyor) ve yalnız okur. Kaynağın sha256'sı çıktıya
gömülür; test onu canlı kaynakla karşılaştırır — `crop.py` değişirse ölçüm "geçti"
demez, yeniden üretim ister. Depo ortamda yoksa test **atlar ve "ÖLÇÜLMEDİ" der**.

Vakalar 9 kaynak boyutu üzerinde üretildi: 4000×3000, 1920×1080, 1000×563, 1120×1120,
1237×911, 901×1601, **8688×8368 (ölçülen MAX, 72,71 MP)**, 200×150 ve dejenere 3×2.

### 3.2 Sonuç — 600 vaka, 5 sınıf

| Sınıf | Ne yapıyor | Vaka | Sapan | En büyük sapma | Yorum |
|---|---|---:|---:|---:|---|
| **A** | Kilitli oran, zoom = 1, yalnız odak taşınmış (kanonik INV-10 yolu) | 120 | **5** | **1 px** | Yuvarlama ifadesi farkı |
| **B** | Kilitli oran, **zoom > 1** | 120 | **119** | **7391 px** | Zoom kaydedilmiyor |
| **C** | Serbest kırpma + override | 120 | **104** | **3704 px** | Sunucu override'ı orana zorluyor |
| **D** | Kilitli oran + override | 120 | **7** | **1 px** | Yuvarlama ifadesi farkı |
| **E** | Serbest kırpma, override yok | 120 | **86** | **3481 px** | Panel taban bölgeyi gösteriyor |

Bu sayılar teste **sabitlendi**: biri değişirse (iyileşme de olsa) test düşer ve nedeni
yazılmadan güncellenemez.

### 3.3 Bulgular

**Bulgu A — 1 px yuvarlama ayrışması (A ve D sınıfları, 12/240 vaka)**

En küçük örnek, `200×150` kaynak + 16:9 profil:

```
panel  = [0, 37, 200, 113]      floor(112.5 + 0.5) = 113   → üst kenar 37'ye çekilir
sunucu = [0, 38, 200, 112]      round(112.5)       = 112   (yarım ÇİFTE)
```

Pencere yüksekliği tam **112,5 px**'e düştüğünde iki yuvarlama kuralı ayrılıyor.
Testte ayrıca **iddia da doğrulanıyor**: A sınıfındaki her sapan vakanın bir kenarı
yarım piksel sınırında ve sapma 1 px'i aşmıyor — başka bir sebep olsaydı test yakalardı.

> Not: T-100 raporu "çapraz-kutu 800 örnek · 1 px yuvarlama farkı olan = 0" ölçmüştü.
> Bu bir çelişki değil, **kapsam farkı**: o örneklem tam yarım piksele düşen kombinasyonu
> içermemiş görünüyor. Burada 240 vakanın 12'sinde (%5) çıkıyor.
> Çözümü panel tarafında **değil**: iki tarafın yuvarlaması aynı ifadeyle yazılmalı
> (`crop_geometry.py` / `core/crop.py`) ve bu depoya dokunulmadı.

**Bulgu B — zoom kalıcılaştırılmıyor (B sınıfı, 119/120 vaka, 7391 px'e kadar)**

`savePayload` yalnız `focal_x/y` + `overrides[]` taşıyor. Zoom ve pan **yükte yok**.
Kullanıcı yakınlaştırıp dar bir kadraj seçtiğinde sunucu pencereyi daima **tam
kadrajdan** kuruyor:

```
P0235  8688×8368  panel = [3695, 3559, 1297, 730]   sunucu = [0, 381, 8688, 4891]
```

Kullanıcının gördüğü kadraj ile teslim edilen kadraj **tamamen farklı**. `useCropStudio`
kilitli oranda tutamak çekmesini zoom'a geri yazıyor (yorumunda "küçültmek =
yakınlaştırmak" diyor) — ama o zoom hiçbir yere kaydedilmiyor. İki çıkış var, ikisi de
`useCropStudio.js`'i (C5 ajanı) ya da sözleşmeyi ilgilendiriyor:
(a) zoom'lu kadraj `overrideRect` olarak yazılsın, (b) UI zoom'un kalıcı olmadığını
açıkça söylesin. **Bu raporda karar verilmedi; ölçüm sunuluyor.**

**Bulgu C — serbest kırpma sunucuda orana zorlanıyor (C sınıfı, 104/120)**

Override kaydediliyor ama `core/crop.py::_fit_ratio_keeping_center` onu profilin oranına
**küçülterek oturtuyor** (T-041'in kabul kriteri: "pencere istenen orana tam uyuyor").
Panel ise kullanıcının çizdiği serbest dikdörtgeni olduğu gibi gösteriyor:

```
P0256  8688×8368  panel = [0, 0, 8291, 8368]   sunucu = [0, 1852, 8291, 4664]
```

Sunucu davranışı **tasarım gereği**; ayrışma paneldeki **önizlemenin eksikliğinden**
doğuyor. `CropPreviewStrip` (T-104, C5 ajanı) profil başına sunucunun kutusunu
gösterdiğinde kullanıcı bu farkı görür.

**Bulgu D — kilit kapalıyken panel taban bölgeyi kadraj sanıyor (E sınıfı, 86/120)**

Oran kilidi kapalı ve override çizilmemişken `pixelBox` taban bölgenin tamamı oluyor;
sunucu ise profilin oranına kırpıyor. `useCropStudio.js`'teki
*"Tam piksel kutusu — sunucunun keseceği kutunun ta kendisi"* yorumu bu durumda
**doğru değil**. Bu bir kod hatası değil, bir **iddia hatası**: `pixelBox` "kullanıcının
seçtiği bölge"dir, "sunucunun keseceği kutu" yalnız A/D sınıflarında odur.

### 3.4 Kapatılabildi mi

**Hayır — ve neden kapatılamadığı ölçülmüş bir gerekçedir.** Dört bulgunun hiçbirinin
düzeltmesi bu ajanın dosyalarında değil:

- Bulgu A → `crop_geometry.py` + `core/crop.py` yuvarlaması (`tradehub_core`, yasak alan)
- Bulgu B, D → `useCropStudio.js` / `savePayload` sözleşmesi (C5 ajanı)
- Bulgu C → `CropPreviewStrip.vue` (T-104, C5 ajanı)

Kapatılan şey **ölçümün kendisi**: bugünden sonra bu ayrışmalar sayı olarak duruyor,
teste sabitlendi ve biri sessizce değişirse kapı düşüyor.

---

## 4. Bitirme koşulları — koşturulan komutlar ve çıktılar

| Koşul | Komut | Sonuç |
|---|---|---|
| Lint | `npm run lint` | **exit 0** · 0 hata, 2 uyarı — ikisi de `views/permission/PlansTab.vue` (bu görevden önce vardı, bu görevin dosyası değil). Yeni uyarı yok. |
| Build | `npm run build` | **exit 0** · `built in 32.12s` |
| Parite kapısı | `npm run parity:crop` | **exit 0** · 72/72 |
| Tip soyma bağımsızlığı | `node --no-experimental-strip-types --test src/lib/media/crop/__tests__/*.test.js` | 72/72 |
| Kırpma testleri | `node --test src/lib/media/crop/__tests__/*.test.js` | 72 test, 72 geçti |
| Fuzz (mevcut) | 500 dizi × 12 jest = **6.000 jest** | geçti |
| Fuzz (yeni) | küçük/aşırı tabanlarda **6.000 jest** | geçti |

### `npm test` (tüm suite) — dürüst durum

Ölçülen koşum: **543 test · 541 geçti · 2 düştü.** İkisi de bu görevin alanı dışında:

1. `src/lib/media/simulator/__tests__/srcsetParity.test.js` — `manifest canlı tradehub_core
   kaynağıyla uyuşuyor` düşüyor: `policy/video_decision.json` değişmiş, `npm run
   sync:simulator` gerekiyor. **Simülatör başka bir ajanın alanı**, dosyaya dokunulmadı.
2. `src/lib/media/upload/__tests__/preflight.test.js` — bir koşumda düştü, **tek başına
   koşturulunca 37/37 geçiyor**; 14 ajan aynı ağaçta paralel yazdığı için koşum sırasında
   dosya değişmiş olması muhtemel.

Görev tanımındaki "bugün 396/396" rakamı artık geçerli değil: suite paralel ajanların
eklemeleriyle koşumdan koşuma büyüyor (464 → 543 arası ölçüldü). **Bu ajanın eklediği
testlerin hepsi geçiyor** ve kırpma alt ağacı tek başına 72/72.

---

## 5. Dokunulan dosyalar

**Değiştirildi**
- `frontend/scripts/sync-crop-geometry.mjs` — türetilmiş `.js` üretimi + gerekçe + manifest `turetilmis` bölümü (şema 1.1.0)
- `frontend/src/lib/media/crop/geometry.js` — içe aktarım `.ts` → `.js`, gerekçe belgelendi
- `frontend/src/lib/media/crop/__tests__/cropGeometryParity.test.js` — 3 yeni test (türetme zinciri, `.ts` içe aktarım yasağı, kapı kontrolü)
- `frontend/src/lib/media/crop/__tests__/cropHandles.test.js` — küçük/aşırı tabanlarda 6.000 jestlik ikinci fuzz
- `frontend/package.json` — tek yeni script: `parity:crop`

**Eklendi**
- `frontend/scripts/gen-crop-pixel-cases.mjs` — panel tarafı vaka üreteci (1/3)
- `frontend/scripts/gen_crop_pixel_vectors.py` — sunucu tarafı vektör üreteci (2/3)
- `frontend/src/lib/media/crop/__tests__/cropPixelParity.test.js` — piksel paritesi kapısı (3/3)
- `frontend/src/lib/media/crop/vendor/crop_geometry.js` — türetilmiş ikiz (ÜRETİLMİŞ)
- `frontend/src/lib/media/crop/vendor/crop_pixel_cases.json` — 600 vaka (ÜRETİLMİŞ)
- `frontend/src/lib/media/crop/vendor/crop_pixel_vectors.json` — 600 sunucu kutusu (ÜRETİLMİŞ)

**Dokunulmadı:** `tradehub_core` kodu, `docker/`, `CropStudioModal.vue`, `CropPreviewStrip.vue`,
`CropPolicyNotice.vue`, `useCropStudio.js`, `router/index.js`, `data/navigation.js`,
`i18n/locales/*`, `components/media/simulator/**`, `components/media/upload/**`,
`MediaLibraryView.vue`, `MediaDetailPanel.vue`.

---

## 6. Yeniden üretim

```bash
cd admin-panel/frontend
npm run parity:crop                        # kapı: senkron doğrulama + 72 test

# piksel paritesini yeniden ölç (tradehub_core ortamda olmalı, yalnız OKUNUR):
node scripts/gen-crop-pixel-cases.mjs      # 1/3 — paneli koştur
python3 scripts/gen_crop_pixel_vectors.py  # 2/3 — core/crop.py'yi koştur
node --test src/lib/media/crop/__tests__/cropPixelParity.test.js   # 3/3
```

---

## 7. Açıkça ÖLÇÜLMEYENLER

- **Node 20.19.2'de gerçek koşum** — o sürüm bu makinede kurulu değil. Ölçülen: kapının
  tip soyma özelliğini hiç kullanmadığı (bayrak kapalıyken 72/72) ve `--test`e glob
  verilmediği.
- **Sunucunun ürettiği görselin pikselleri** — bu ölçüm kadraj KUTUSUNU karşılaştırır;
  Pillow'un yeniden örneklemesini, renk profilini, tarayıcıdaki çizimi değil.
- **Tarayıcı davranışı** — DPR ≥ 2'de tutamak isabeti, `pointermove` akışı, önizleme
  bütçesi (T-104'ün 16 ms hedefi). Bu görevde tarayıcı doğrulaması **yapılmadı** ve
  hiçbir süre/FPS iddiası **yok**.
- **`safe_*` (2. seviye) ve `smartcrop` (4. seviye) yolları** — panel bugün bu alanları
  yükte göndermiyor, dolayısıyla piksel paritesi o iki seviye için ölçülmedi.
