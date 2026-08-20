# 37 — `Media Crop Intent` kurulumu ve kaydetme ucu

**Tarih:** 2026-08-19
**Branch:** `ahmet` (tradehub_core + admin-panel)
**Kapsam:** T-040, T-073, T-082, T-104, T-114'ü tutan tek eksik parça — kırpma
niyetinin şeması ve onu yazan uç.

---

## 0. Zamanlama (doğrulama ajanlarıyla tutarlılık için)

Üç doğrulama ajanı aynı anda canlı durumu ölçüyordu; `bench migrate` DocType
sayısını değiştirdi. Ölçüm anları:

| Saat (+03) | Olay | `Media%` DocType sayısı |
|---|---|---|
| 19:18:05 | Başlangıç ölçümü (değişiklik öncesi) | **6** |
| 19:27:50 | `bench migrate` **başladı** | 6 |
| 19:28:07 | `bench migrate` **bitti** (patch `v15_9_27` koştu, 0.179 s) | **8** |
| 19:44:10–19:44:27 | İkinci `bench migrate` (idempotency) | 8 |

19:18 ile 19:28 arasında 6 gören bir ajan **haklıdır**; o pencerede DocType
gerçekten kurulu değildi. 19:28'den sonra 8 görülmelidir.

---

## 1. Ne kuruldu

| Dosya | İş |
|---|---|
| `tradehub_core/tradehub_core/doctype/media_crop_intent/` | `.json` + `.py` + `__init__.py` |
| `tradehub_core/tradehub_core/doctype/media_crop_override/` | child tablo, aynı üçlü |
| `tradehub_core/api/media_crop.py` | 3 whitelist ucu (ince sarmalayıcı) |
| `tradehub_core/patches/v15_9_27_media_crop_intent.py` | idempotent kurulum yaması |
| `tradehub_core/patches.txt` | 27. sıra (yalnız ekleme) |
| `tradehub_core/permissions.py` | `media_crop_intent_*` iki kanca |
| `tradehub_core/hooks.py` | iki kayıt (**yalnız ekleme**) |
| `tradehub_core/tests/test_media_crop_intent.py` | 17 test |

**`media/pipeline/api/crop.py` tek satır değişmedi.** Dosya başlığındaki
*"Saf Python — `@frappe.whitelist()` YOK"* sözleşmesi korundu; whitelist,
oturum, kiracı sınırı ve DocType erişimi `api/media_crop.py`'de durur —
`api/media_manifest.py` ile aynı desen.

### Spec'ten bilinçli sapmalar

1. **`module`**: spec `"Media Engine"` diyor; o modül bu app'te YOK
   (`modules.txt` tek satır: `Tradehub Core`) ve kurulu beş medya DocType'ı da
   `Tradehub Core` kullanıyor. Sapma kardeşleriyle tutarlı.
2. **`permissions`**: spec yalnız `Media Superadmin` / `Seller` /
   `System Manager` yazıyordu; kurulu kardeşlerin rol kümesi
   (`Marketplace Admin`, `Marketplace Seller`) eklendi — o küme olmadan
   satıcının kendi ekranı açılmıyordu. Satıcı satırına **`if_owner` KONMADI**:
   kiracı sınırı yaratıcı kullanıcı değil `asset.owner_seller`'dır ve kanca ile
   zorlanır; `if_owner` aynı mağazanın ikinci kullanıcısını yanlışlıkla
   kilitlerdi.

Alan adı, alan tipi, `field_order`, `autoname`, Select seçenekleri **spec ile
birebir**. Yeni alan icat edilmedi.

---

## 2. UYUŞMAZLIK — çözüldü, üç tane çıktı

Görev tek bir uyuşmazlık bildiriyordu; ölçünce **üç** tane vardı ve ikisi
paneli gerçekten kırardı.

### 2.1 `safe_top/right/bottom/left` vs `safe_x/y/w/h` — **belge düzeyinde**

**Spec kazandı.** Ama önemli bir düzeltme: bu ikilik panelin GÖNDERDİĞİ yükte
hiç yoktu. `useCropStudio.savePayload` güvenli alanı zaten **hiç göndermiyordu**
(alanları: `focal_x`, `focal_y`, `method`, `confidence`, `approved_by_user`,
`overrides`). `safe_top/right/bottom/left` yalnızca `missingEndpoint.fields`
dizisinde — kullanıcıya "gereken uç" listesi olarak basılan **açıklama
metninde** — geçiyordu.

Yani Faz 10 raporunun "panel yükü `safe_top/...` varsayıyor" tespiti, kodda
karşılığı olmayan bir belge hatasıydı. Düzeltildi: liste artık
`safe_x, safe_y, safe_w, safe_h` yazıyor.

**Neden spec kazanır (kutu vs kenar boşluğu):** `x/y/w/h` bir **kutudur**,
`top/right/bottom/left` bir **kenar boşluğudur**. İkisi bilgi olarak
dönüştürülebilir ama aynı şey değildir ve dönüşüm kaynağın oranını bilmeyi
gerektirir. Kutu gösterimi `core/crop.py`'nin tamamının konuştuğu dildir
(`Rect(x, y, w, h)`, `safe_region_of`, `_cover_window`); kenar boşluğuna
çevirmek, kadraj matematiğinin her çağrısında geri çevirmek demekti.

### 2.2 `overrides[].slot_key` vs `overrides[].profile` — **gerçek kırılma**

Panel override satırını `{ slot_key, x, y, w, h }` olarak gönderiyordu.
`Media Crop Override.profile` bir **Link → Media Profile**'dır ve sunucu
bilinmeyen profili **reddeder** (`pipeline/api/crop.py::_parse_overrides`,
"YAZMA tarafında sessizlik yanlış olur"). Slot bir profil değildir — bu yük
hiçbir zaman kabul edilmezdi.

**Çözüm:** panel artık profil adı gönderiyor. Hangi profiller:
- oran kilitliyken, o oranı paylaşan profiller (`ratioOptions().profiles`);
- serbest kırpmada slotun tüm kırpılabilir profilleri — kullanıcı hiçbir
  profilin oranına uymayan bir kadraj çizmiştir, niyeti "gördüğüm her yerde bu
  kadraj"dır.

### 2.3 `method: "edge_energy_v1"` — **gerçek kırılma**

Panel `focusSuggest.METHOD = "edge_energy_v1"` değerini doğrudan `method`
alanına yazıyordu (kaynak dosyada yorumu da öyle diyordu: *"`Media Crop
Intent.method` alanına yazılacak değer"*). Ama spec'in Select'i yalnız
`manual | smartcrop | center` tanır — Frappe `_validate_selects` bunu reddeder,
uç de 400 döner.

**Çözüm:** spec'in bu iş için zaten **iki ayrı alanı var** — `algorithm` ve
`algorithm_version`. Panel artık `method: "smartcrop"`, `algorithm:
"edge_energy"`, `algorithm_version: "v1"` gönderiyor. Etiket bozulmadan
saklanıyor, sadece doğru alana.

### 2.4 Bonus: `method`in iki ayrı vokabüleri (koda gömülü tuzak)

`Media Crop Intent.method` niyetin **kaynağını** söyler
(`manual/smartcrop/center`). `core/crop.py:METHODS` ise çözülen **pencerenin**
yöntemidir (`override/safe_focal/focal/smartcrop/center`). Spec'in kendi alan
açıklaması bu iki ekseni ayırıyor.

Sorun: `CropApi.save_intent` gelen `method`i **pencere** vokabülerine göre
doğruluyor — yani `"manual"` oradan geçemez. `crop.py` dokunulmaz olduğu için
sarmalayıcı `method`i kütüphaneye **hiç vermiyor**: şema yetkili olduğundan
doğrulama `INTENT_METHODS` ile burada yapılıyor ve değer depo katmanına
doğrudan taşınıyor. Kütüphanenin pencere doğrulayıcısına yanlış eksenden bir
değer sokuşturmak iki sözlüğü karıştırmak olurdu.

---

## 3. Girdi kırpma kararı: **REDDET, kelepçeleme**

`focal_x/y` ve `safe_*` 0-1 dışındaysa istek **400 ile reddedilir**.

Gerekçe: koordinat piksel değil normalize olduğu için `1.4` "biraz taşmış bir
kadraj" değildir — çağıranın **piksel gönderdiğinin kanıtıdır**. Sessizce
1.0'a çekmek, kullanıcının çizmediği bir kadrajı "kaydedildi" diye göstermek
olurdu. Bu karar üç yerde tutarlı:

- `envelope.require_unit` (kütüphane) → 400,
- `api/media_crop` (uç) → aynı hatayı HTTP durumunu koruyarak geçirir,
- DocType controller'ları → `frappe.throw` (yama/konsol yolu da kapalı).

Kelepçeleme bu kod tabanında yalnız **tercih** alanlarında kullanılıyor
(`envelope.page_params`: `page_size` tavanı), koordinatlarda değil.

---

## 4. Kiracı izolasyonu — üç kat, biri ölçülerek kanıtlandı

`Media Crop Intent` sahiplik kolonu **taşımaz**; izolasyon `asset` üzerinden
`Media Asset.owner_seller`'a zincirlenir (Media Rendition / Media Processing
Job ile birebir aynı desen; denormalize `seller` kolonu bilerek eklenmedi —
Asset devredildiğinde sessizce eskir).

| Kat | Nerede | Neyi kapatır |
|---|---|---|
| 1 | `env.same_store` (kütüphane) | uç çağrısı — başka mağazanın varlığı **404** (403 değil: varlığın VARLIĞI sızmamalı) |
| 2 | `media_crop_intent_has_permission` | ORM tek-doküman okuma/yazma |
| 3 | `media_crop_intent_query_conditions` | liste sorgusu |

**Satıcı burada YAZAR.** Rendition/Job kancalarındaki
`ptype in ("write","create","delete") → False` kapısı bilerek kopyalanmadı;
kopyalansaydı kırpma stüdyosunun kaydet düğmesi kalıcı olarak ölürdü.

---

## 5. Kanıtlar

### 5.1 `bench migrate` temiz, `tabDocType`'ta iki satır

```
$ bench --site istoc.localhost migrate      # 19:27:50 → 19:28:07
Executing tradehub_core.patches.v15_9_27_media_crop_intent ... Success: Done in 0.179s
(traceback/error sayısı: 0)

mysql> SELECT name, module, istable, autoname FROM tabDocType WHERE name LIKE 'Media Crop%';
name                 module          istable  autoname
Media Crop Intent    Tradehub Core   0        field:asset
Media Crop Override  Tradehub Core   1        NULL

mysql> SHOW TABLES LIKE 'tabMedia Crop%';
tabMedia Crop Intent
tabMedia Crop Override

Media% DocType sayısı: 6 → 8
```

### 5.2 İzolasyon üç yönlü — ölçüldü

`tradehub_core/tests/test_media_crop_intent.py`, **17/17 OK**.

| Yön | Test | Sonuç |
|---|---|---|
| (i) sahibi satıcı yazar+okur | `test_owner_saves_and_reads_own_intent` | ✅ |
| (ii) başka satıcı okuyamaz | `test_cross_tenant_read_denied`, `test_cross_tenant_orm_read_denied`, `test_list_excludes_other_tenants` | ✅ reddedildi |
| (ii) başka satıcı yazamaz | `test_cross_tenant_write_denied` (+ DB'de değerin **değişmediği** ayrıca ölçüldü) | ✅ reddedildi |
| (iii) Guest | `test_guest_denied`, `test_guest_query_condition_blocks_everything` | ✅ reddedildi |

### 5.3 Vacuity — kanca kaldırıldı, KIRMIZI oldu, geri kondu

`hooks.py`'deki iki `Media Crop Intent` kaydı konteynerde geçici olarak
kaldırıldı, `docker restart` (hooks önbelleği `clear-cache` ile düşmüyor —
bu ilk denemede yanlış "yeşil" verdi ve fark edildi), testler koşturuldu:

```
FAIL: test_cross_tenant_orm_read_denied
FAIL: test_list_excludes_other_tenants
FAIL: test_hooks_registered
Ran 17 tests — FAILED (failures=3)
```

Kanca geri kondu (`diff` ile yedeğe birebir eşit doğrulandı), restart, tekrar:
`Ran 17 tests — OK`.

**Not — kanca kaldırılınca UÇ testleri yeşil kaldı.** Bu bir eksiklik değil,
ölçülmüş bir bulgu: uç yolunu kütüphanenin `same_store` kapısı (1. kat)
bağımsız olarak kapatıyor. Yani iki kat gerçekten bağımsız; ORM ve liste
yüzeyini yalnız kanca koruyor ve o kaldırılınca üç test kırmızıya dönüyor.

### 5.4 `suggest_focal` gerçek görselde, 0-1 aralığında

800×400 JPEG, enerji sol-üst çeyreğe yoğunlaştırılmış:

```json
{
  "focal_x": 0.178523,
  "focal_y": 0.21707,
  "confidence": 0.891147,
  "measured": true,
  "reason": "measured",
  "threshold_calibrated": false
}
0-1 ARALIĞINDA: True
```

Odak gerçekten desenin bulunduğu bölgeye düştü. `threshold_calibrated: false`
yanıtta korunuyor — eşik hâlâ kalibre edilmedi ve uç bunu gizlemiyor. Öneri
**yazılmıyor** (`applied: false`; niyet kaydı açılmadığı ayrıca ölçüldü).

Algoritma `pipeline/api/crop.py:focal_from_bytes` — yeniden yazılmadı.

### 5.5 `save_intent` idempotent

```
çağrı öncesi satır: 0
1. çağrı sonrası satır: 1
2. çağrı sonrası satır: 1   (ARTMADI)

DB satırı: {"name": "5l8jb8t2tg", "asset": "5l8jb8t2tg", "focal_x": 0.6,
            "focal_y": 0.7, "method": "smartcrop",
            "algorithm": "edge_energy", "algorithm_version": "v1",
            "confidence": 0.42}
docname == asset adı: True
```

Mekanizma: `autoname: field:asset` + `asset` alanında `unique: 1`. İkinci
çağrı yeni kayıt açmaz, mevcudu günceller.

### 5.6 Yama idempotent + sessiz başarısızlık koruması

Yama üç kez koşturuldu, her seferinde
`{"loaded": ["Media Crop Override", "Media Crop Intent"], "missing": []}`,
satır sayısı sabit. İkinci `bench migrate` temiz (19:44:10 → 19:44:27).

Koruma **fiilen sınandı**: `media_crop_override.json` geçici olarak
gizlendiğinde yama sessizce geçmedi, patladı:

```
frappe.exceptions.ValidationError: Kırpma DocType şeması yüklenemedi:
Media Crop Override. JSON dosyalarını ve modül adını (Tradehub Core) kontrol edin.
```

Dosya geri konunca yine `loaded`. `v15_9_25`'i vuran "reload_doc `False`
döner, hata fırlatmaz" tuzağı bu yamada hem `reload_doc` dönüşü hem
`table_exists` ile kapalı.

### 5.7 Panel

```
npm run lint   → EXIT 0   (2 uyarı, ikisi de PlansTab.vue'de ve önceden var)
npm run build  → EXIT 0
npm test       → EXIT 0   ·  396/396 pass, 0 fail
```

393 → 396: kaydetme yolu için 3 yeni test eklendi (varlıkla kaydetme açılır ve
uca gerçek yük gider · hata yutulmaz, `saveError`da kalır · politika engeli
varken kaydetme kapalı kalır). Mevcut testlerden 3'ü yeni sözleşmeye göre
güncellendi (§2.2, §2.3, alan listesi).

### 5.8 Backend regresyon

| Modül | Sonuç |
|---|---|
| `test_media_crop_intent` | 17 test — **OK** (yeni) |
| `test_media_access` | 17 test — **OK** |
| `test_crop_geometry` | 37 test — **FAILED (failures=1)** ⬅ önceden var, artmadı |
| `test_pipeline_bridge` | 19 test — **OK** |
| `test_kyc_tenant_isolation` | 13 test — **OK** |

`test_crop_geometry`'deki tek hata `test_ts_ikizi_ayni_sayiyi_veriyor`:

```
STDERR: /home/frappe/.nvm/versions/node/v20.19.2/bin/node:
        bad option: --experimental-strip-types
```

Konteynerdeki node **v20.19.2**; bayrak v22+ istiyor. Bu görevin işi değil,
sayısı **1'de kaldı**.

---

## 6. Yol boyunca çıkan iki gerçek bulgu

### 6.1 Ölçüsüz varlık ucu 500'e düşürüyordu

`core/crop.py:source_ratio_of` iki durumu ayırıyor: `width`/`height`
**yoksa** 1.0 (kare) varsayar; **varsa ama 0 ise** `CropError` fırlatır.
Sarmalayıcının ilk hâli ölçü bilinmediğinde `width: 0, height: 0` yazıyordu —
yani "bu görsel sıfır piksel geniş" diye bildiriyordu ve uç patlıyordu
(ölçüldü: 9 test kırmızı).

Düzeltildi: **ölçü bilinmiyorsa alanlar hiç konmuyor.** Ayrıca `Media Asset`
kendi `width/height` kolonu taşımadığı ve `File.th_media_width` canlıda
2853 kayıtta 0 dolu olduğu için, sarmalayıcı ölçüyü görselin kendi
başlığından okuyor (Pillow `Image.open` tembeldir). Kalıcılaştırmıyor —
okuma yolunda yazmak ayrı bir sorun sınıfı; alanı doldurmak yükleme hattının
işi.

`CropError` bir `ValueError`, `MediaEngineError` ağacında **değil** — ayrıca
yakalanıyor, yoksa tek bir varlık ucu 500'e düşürürdü.

### 6.2 Frappe `Float` "yazılmadı"yı ifade edemiyor

Frappe `Float` kolonları `NOT NULL DEFAULT 0`. Ama `core/crop.py` "kullanıcı
merkezi seçti" ile "hiç seçmedi" ayrımına **zincir seviyesi** bağlıyor
(`focal_of` dokümanı: 3. seviye vs 5. seviye). Kayıt bir kez DB'ye gidip
geldiğinde yazılmamış odak `(0.0, 0.0)` — yani "sol üst köşe" — oluyordu.

Çözüm, çekirdeğin kendi desenini izliyor (`safe_region_of` dejenere tam
kadrajı "belirtilmemiş" sayıyor): `as_intent_mapping()` tam `(0,0)` odağı ve
`w<=0 || h<=0` güvenli alanı **yazılmamış** sayıyor. Bedeli açıkça
belgelendi — odağı tam `(0.000000, 0.000000)`'a koyan kullanıcı merkeze
düşer; alternatif spec'te olmayan bir `has_focal` alanı icat etmekti.

Aynı sebeple `_validate_safe_box` sıfır alanlı kutuyu **hata değil
tanımsızlık** sayıyor; gerçekten sıfır alanlı kutu ÇİZME olayı API katmanında
(`_parse_safe_area`, 400) yakalanıyor.

---

## 7. Dokunulmayanlar

`media/pipeline/api/crop.py`, `media/file_isolation.py`, `api/media_manifest.py`,
`api/seller_media.py`, `media/browse.py`, `media/pipeline/storage/`,
`docs/standards/`, `docker/`, `docs/reports/33…36`.

`hooks.py` diff'i: **83 ekleme, 0 silme** (`git diff --numstat`) — deponun
bugüne kadarki 0-silme kaydı bozulmadı.

`Media Engine Settings` bayrakları **0 kaldı**
(`media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0`).
Kırpma uçları bayraktan bağımsızdır ve bu bilinçli: kullanıcı niyeti bir hat
çıktısı değil, kullanıcı verisidir.

**Test kaydı bırakılmadı:** `tabMedia Crop Intent` 0, `tabMedia Crop Override` 0,
`tabMedia Asset` 0 satır. Demo koşusundan kalan tek `User` kaydı da silindi.
(`Admin Seller Profile`'daki `DEMO-001…010` kayıtları 2026-06-06 tarihli seed
verisidir, bu görevin ürünü değildir — dokunulmadı.)

---

## 8. Açık kalan / sıradaki

1. **`th_media_width/height` boş.** Sarmalayıcı ölçüyü her istekte görselden
   okuyor. Kalıcı çözüm yükleme hattının bu alanları doldurması; o zaman
   Pillow yolu hiç çalışmaz.
2. **smartcrop eşiği hâlâ kalibre değil** (`SMARTCROP_CONFIDENCE_THRESHOLD =
   0.5`). Uç bunu `threshold_calibrated: false` ile taşıyor, gizlemiyor.
3. **`get_intent`/`preview` panelde kullanılmıyor.** Uç var ve testli; stüdyo
   şu an yalnız yazıyor, açılışta kayıtlı niyeti geri yüklemiyor.
4. **`previewed_placements` panelden gönderilmiyor.** Alan ve uç parametresi
   hazır; simülatörün gösterdiği yerleşimleri bağlamak ayrı bir iş (T-114).
5. `cropStudio.save.why` i18n anahtarı artık kullanılmıyor (dört dilde duruyor,
   zararsız).
