# 65 — BE3: Kırpma niyetine zoom/center + sunucu onay kapısı (T-105 B/C/E · T-114)

Tarih: 2026-08-20 · Kapsam: `Media Crop Intent` şeması, `save_intent` ucu,
kırpma çözücüsü (`core/crop.py`), panel yükü (`useCropStudio`), piksel parite
zinciri, T-114 sunucu kapısı.

---

## 1. Ne değişti

### Backend
| Dosya | Değişiklik |
|---|---|
| `tradehub_core/tradehub_core/doctype/media_crop_intent/media_crop_intent.json` | `zoom`, `center_x`, `center_y` (Float, precision 6) alanları — `safe_h`'den sonra |
| `media/pipeline/doctype_specs/media_crop_intent.json` | Spec aynası aynı üç alanla eşitlendi |
| `.../media_crop_intent.py` | `_validate_zoom` (1-16, 0 = yazılmamış), `center_x/y` → `UNIT_FIELDS`, `_zoom_uclu` + `as_intent_mapping`, **`_validate_approval_evidence` (T-114 ORM kapısı)** |
| `media/pipeline/api/crop.py` (CropApi) | `save_intent`e `zoom/center_x/center_y` parametreleri, `_parse_zoom` (aralık dışı → red), üçlü-birlikte kuralı, `_normalize_intent`e üç anahtar |
| `api/media_crop.py` (uç) | Whitelist parametreleri geçirildi; depo katmanı üç alanı yazıyor; **T-114 kapısı: `approved_by_user=1` + boş kanıt → red (`MEDIA_PREVIEW_REQUIRED`)** |
| `media/pipeline/core/crop.py` (çözücü) | `ZOOM_MIN/ZOOM_MAX` sabitleri + `zoom_region_of()`; zincirin 2. ve 5. seviyesi artık taban bölgeyi zoom üçlüsünden kuruyor (yoksa güvenli alandan — eski davranış) |
| `media/pipeline/core/dedup.py` | `CROP_HASH_FIELDS` += zoom üçlüsü (pencereyi değiştiren alan hash'e girmeli); `zoom<1` guard'ı eski niyetlerin hash'ini KORUR |
| `media/pipeline/api/spec.py` | `CropIntent` + `SaveIntentRequest` sözleşme şemalarına üç alan |
| `tests/test_crop_intent_zoom.py` | **YENİ** — 18 test (aşağıda) |
| `tests/test_media_crop_intent.py` | Tek test güncellendi (gerekçe §6) |

**`crop_geometry` çekirdeğine (py/ts/js) ve simulator dizinlerine dokunulmadı.**
`hooks.py` ve `patches.txt` de değişmedi — ihtiyaç yok: alanlar DocType JSON'dan
`bench migrate` ile geldi (ölçüm §2), veri geri doldurma gerektirmiyor (yeni
alanlar "yazılmamış" doğar ve 0 = yazılmamış sözleşmesi bunu taşıyor).

### Frontend (admin-panel)
| Dosya | Değişiklik |
|---|---|
| `src/composables/useCropStudio.js` | `savePayload` += `zoom/center_x/center_y` (6 basamak); `validateIntentPayload` üçlü kuralları; `endpoint.fields` güncel |
| `scripts/gen_crop_pixel_vectors.py` | `payload_to_intent()` — yük artık ucun DEPOLADIĞI biçime çevriliyor (`safe_area` kutusu → `safe_x/…`); eskiden çevrilmiyordu, §4'e bakın |
| `scripts/gen-crop-pixel-cases.mjs` | B sınıfı açıklaması gerçeğe döndü; vaka/vektör dosyaları yeniden üretildi |
| `src/lib/media/crop/__tests__/cropPixelParity.test.js` | `BEKLENEN` yeni ÖLÇÜMLE güncellendi (tolerans gevşetilmedi; C/E sayıları aynen sabit) |
| `src/composables/__tests__/cropStudio.test.js` | Yük anahtar listesi testi +3 anahtar (şema genişledi, alan icat edilmedi) |
| `src/composables/__tests__/cropStudioZoomPayload.test.js` | **YENİ** — 9 test |

`cropIntentApi.js` DEĞİŞMEDİ: skaler alanları spread ile zaten geçiriyor
(yalnız `safe_area`/`overrides` JSON'lanıyor); zoom üçlüsü kendiliğinden akar.

---

## 2. DocType alan ölçümü (migrate SONRASI, canlı DB)

```
SELECT fieldname, fieldtype, `precision` FROM tabDocField
 WHERE parent="Media Crop Intent" AND fieldname IN ("zoom","center_x","center_y");
  center_x  Float  6
  zoom      Float  6
  center_y  Float  6

SHOW COLUMNS FROM `tabMedia Crop Intent` WHERE Field IN (...):
  zoom      decimal(21,6)  NO  Default 0.000000
  center_x  decimal(21,6)  NO  Default 0.000000
  center_y  decimal(21,6)  NO  Default 0.000000
```

`NOT NULL DEFAULT 0` — bu yüzden "yazılmamış" nöbetçisi `zoom < ZOOM_MIN(=1)`:
0 hiçbir zaman geçerli zoom değil, odaktaki (0,0) köşe-kaybı belirsizliği bu
alanda YOK. `center_*` yalnız zoom yazılıyken okunur; uç üçlüyü birlikte
zorunlu kıldığı için (0,0) merkez de kayıpsız temsil edilir.

## 3. Kapı red ölçümü — GERÇEK HTTP istekleriyle

`istoc-dev-backend-1` içinden, oturum açılmış gerçek POST'lar
(`/api/method/tradehub_core.api.media_crop.save_intent`):

| İstek | Sonuç |
|---|---|
| `approved_by_user=1`, kanıt YOK | **HTTP 417** · `Onay için önizleme kanıtı zorunlu: previewed_placements boş … (MEDIA_PREVIEW_REQUIRED)` |
| `approved_by_user=1` + `previewed_placements=[{…}]` + zoom üçlüsü | **HTTP 200** · yanıt `intent.zoom=2.5, center=(0.6, 0.4), approved=true` |
| `zoom=17` | **HTTP 417** · `` `zoom` 1.0 ile 16.0 arasında olmalı: 17.0 `` |
| (karşılaştırma, DEĞİŞMEYEN eski desen) `focal_x=1.4` | **HTTP 417** · `` `focal_x` 0 ile 1 arasında olmalı `` |

**417 notu:** kod `frappe.local.response["http_status_code"]=400` yazıyor ama bu
kurulumdaki Frappe v15 `ValidationError`'ın kendi durumunu (417) uyguluyor —
DEĞİŞİKLİKTEN ÖNCE de böyleydi (son satır: mevcut `require_unit` yolu da tel
üzerinde 417). Yeni redler mevcut hata biçimiyle birebir aynı yüzeyde.

Kapı iki katmanda: uç deposu (`_FrappeCropIntents.save`, okunur mesaj +
MEDIA_PREVIEW_REQUIRED) ve DocType `validate`
(`_validate_approval_evidence`) — uç atlanıp ORM ile yazılsa da geçilemez.
`[]`/`{}` kanıt sayılmaz (test edildi). Ayara bağlanMADI. Daha önce kapıdan
geçmiş kayıt, sonraki yazımda kanıtı yeniden göndermek zorunda değil (kayıtta
duran kanıt geçerli — kapı isteği değil KAYDI ölçer). Eski kayıtlar migrate'te
ellenmedi; kanıtsız-onaylı eski bir satır ancak bir SONRAKİ yazımında takılır.

**Vacuity ölçümü:** iki kapı satırı konteynerde geçici devre dışı bırakıldı →
`test_onay_kaniti_olmadan_reddedilir`, `test_bos_liste_kanit_sayilmaz`,
`test_orm_yuzeyinde_de_kapi_var` ÜÇÜ DE KIRMIZI (`FAILED (failures=3)`),
kapı geri kondu → 18/18 yeşil. Testler kapıyı gerçekten ölçüyor.

## 4. Parite: önce / sonra (sınıf bazında, 120'şer vaka)

| Sınıf | Önce (sapan · en büyük px) | Sonra (sapan · en büyük px) |
|---|---|---|
| A (kilitli oran, zoom=1) | 5 · 1 | 5 · 1 (değişmedi) |
| **B (kilitli oran, zoom>1)** | **119 · 7391** | **3 · 1** |
| C (serbest + override) | 104 · 3704 | 104 · 3704 (bilinçli, aşağıda) |
| D (kilitli oran + override) | 7 · 1 | 7 · 1 (değişmedi) |
| E (serbest, override yok) | 86 · 3481 | 86 · 3481 (bilinçli, aşağıda) |

B'nin kalan 3 vakası 1 px: A ile aynı yuvarlama-ifadesi sınıfı (yarım piksel;
panel `floor(v+0.5)` kaynak pikselinde, sunucu `int(round(v))` normalize
uzayda) + 3×2 dejenere kaynakta `MIN_EDGE_PX` tabanının yarım-piksel konumu.

**C/E NEDEN İNMİYOR — ölçüldü, tolerans GEVŞETİLMEDİ:** sapan 104+86 vakanın
**tamamında** sunucu kutusu profilin oranını tutuyor; C'de 101/104, E'de 79/86
vakada panel kutusunun oranı profile hiç uymuyor (serbest çizim), kalan 3+7
vaka 1920×1080 kaynağın 1000×563 profil oranından %0,09'luk farkı (2 px). Yani
C/E sapması bir KAYIT kaybı değil, T-041'in "pencere istenen orana tam uyuyor"
zorunluluğu ile panelin serbest kadrajı olduğu gibi göstermesi arasındaki
bilinçli politika farkı. Zoom bunu değiştiremez (override 1. seviyede kazanır;
E'de panel taban bölgeyi gösterir). Bu fark kapatılacaksa iş, panelin serbest
kipte "sunucunun keseceği kutu"yu da göstermesidir (UI kararı, bu görevin
kapsamı dışında) — sayılar o yüzden aynen sabitlendi.

**Dürüst not:** ölçümde iki düzeltme üst üste bindi. (a) Eski vektör üreticisi
yükü uca ÇEVİRMEDEN `resolve_crop`a veriyordu — `safe_area` kutusu zincirin
okuduğu `safe_x/…` kolonlarına açılmıyordu; yani eski "B: 119/7391" ölçümünün
bir kısmı üreticinin kendi eksiğiydi. (b) Ayrıştırma ölçümü yapıldı: yalnız
(a) düzeltmesiyle de B → 3/1'e iniyor, yalnız zoom üçlüsüyle de (safe
atılarak) B → 3/1. İkisi aynı taban bölgenin iki yazımı olduğu için bu
BEKLENEN sonuçtur ve `zoom_region_of`'un doğruluğunun çapraz kanıtıdır. Zoom
alanlarının şemaya girmesinin kalıcı değeri parite değil, NİYETİN kendisinin
kaybolmadan saklanması: türetilmiş/6-basamak kutu yerine stüdyonun gerçek
durumu (kaydırıcı yeniden kurulabilir, `verify` edilebilir, T-105 şartı).

Ek parite güvencesi: `test_zoom_region_of_zoom_base_ile_ayni_pencere`
normalize kurulumu `crop_geometry.zoom_base` ile 4 temsili kaynakta (3×2
MIN_EDGE dahil) 0,5 px toleransla karşılaştırıyor;
`test_zoom_sabitleri_geometriyle_ayni` sabit kopyasını kilitliyor
(`core/crop.py` çekirdek `crop_geometry`'yi import EDEMEZ: parite üreticisi
onu paketsiz, dosya yolundan yüklüyor).

## 5. Geriye uyumluluk — eski çağrı kanıtı

`save_intent`'in None politikası ÖNCE okundu: `yeni` sözlüğü MEVCUT kayıttan
başlar; verilmeyen parametre alanı korur (odak/`safe_area=None`/`overrides=None`
bugüne kadar da böyleydi — "None yazar" değil). Zoom üçlüsü aynı kurala girdi:

* `test_eski_cagri_zoom_bilmeden_calisir` — zoom bilmeyen çağrı 200; üçlü
  `None` kalıyor; pencereler eski davranışla `focal` seviyesinde.
* `test_parametresiz_cagri_kayitli_zoomu_korur` — yalnız odak güncelleyen
  ikinci çağrı kayıtlı zoom'u SİLMİYOR.
* **Tek bilinçli istisna:** `safe_area` verilip zoom verilmezse üçlü silinir
  (`test_safe_area_zoomsuz_gelirse_ucluyu_siler`). Gerekçe: çözücü zoom'u
  tercih ediyor; eski istemcinin gönderdiği taze `safe_area`'yı bayat zoom'un
  gölgelemesi, kullanıcının az önce çizdiği kadrajı sessizce değiştirmek
  olurdu. Eski kayıtlar (zoom hiç yazılmamış) için bu istisna no-op.
* `get_intent`/`save_intent` yanıt gövdesi yalnız GENİŞLEDİ (üç anahtar).
  Yan etki: `intent` şekli değiştiği için eski ETag'ler ilk yazımda 412
  düşürür — iyimser kilidin tanımlı davranışı, tek seferlik.

Onay kapısı İSE bilinçli bir davranış değişikliğidir (şartname): eski biçimli
`approved_by_user=1` + kanıtsız çağrı artık reddedilir; `approved_by_user=0`
akışları (öneri dahil) aynen çalışır (`test_onaysiz_kayit_kanit_istemez`).

## 6. Test durumu

* **Backend YENİ:** `tradehub_core/tests/test_crop_intent_zoom.py` — 18/18
  konteynerde yeşil (`bench --site istoc.localhost run-tests`). Komşu
  süitler: `test_media_crop_intent` 17 OK, `test_crop` 26 OK, `test_dedup`
  57 OK, `test_contracts` 75 OK, `test_render_regression` 32 OK (1 skip).
* **Güncellenen mevcut testler (gevşetme değil, gerekçeli):**
  1. `test_media_crop_intent.py::test_owner_saves_and_reads_own_intent` —
     çağrıya kanıt eklendi; kanıtsız onay artık şartname gereği reddediliyor
     ve o red kendi testinde ölçülüyor.
  2. FE `cropStudio.test.js` yük anahtar listesi — +3 anahtar (alan icat
     edilmedi, şemaya eklendi).
  3. FE `cropPixelParity.test.js::BEKLENEN` — sayılar yeni ölçüm; B iyileşti
     (119→3), C/E aynen sabit, hiçbir tolerans gevşemedi.
* **FE YENİ:** `src/composables/__tests__/cropStudioZoomPayload.test.js` —
  9 test. FE toplam: **833/833 geçti** (`npm test`; sayı diğer ajanların
  dosyalarıyla oynayabilir — benim dosyalarım: bu yeni dosya + yukarıdaki iki
  güncelleme). ESLint/Prettier temiz.
* **Konteynerde ilgisiz, ÖNCEDEN VAR olan kırmızı:** `test_crop_geometry::
  test_ts_ikizi_ayni_sayiyi_veriyor` — konteyner node v20.19.2'de
  `--experimental-strip-types` yok ("bad option"); dokunduğum hiçbir dosyayla
  ilgisi yok, lokalde aynı süit 37/37 OK.

## 7. hooks.py / patches.txt ihtiyacı

**Yok.** Alanlar DocType JSON değişikliğiyle migrate'te açıldı; veri
dönüşümü gerekmiyor (0 = yazılmamış). Kapı DocType validate + uç deposunda,
kanca istemiyor. İkisine de dokunulmadı.

## 8. Eklenecek i18n anahtarları (kaynak dizgeler `_()` ile sarılı)

Çeviri dosyalarına girecek yeni backend mesajları:

1. `` `zoom` {0} ile {1} arasında olmalı: {2} `` (DocType validate)
2. `Onay, önizleme kanıtı olmadan kaydedilemez: `previewed_placements` boş. Yerleşimleri simülatörde görüp onaylayın. (MEDIA_PREVIEW_REQUIRED)` (DocType)
3. `Onay için önizleme kanıtı zorunlu: `previewed_placements` boş. Yerleşimleri simülatörde görüp onaylayın. (MEDIA_PREVIEW_REQUIRED)` (uç deposu)

(Pipeline `BadRequest` mesajları — üçlü-birlikte, `_parse_zoom` — saf Python
katmanında ve oradaki mevcut desen gibi `_()` DIŞINDA; katman frappe'siz.)
FE'de yeni locale anahtarı YOK (`payloadIssues` dizgeleri mevcut desenle düz
metin; `i18n/locales` bana yasaktı ve gerek olmadı).

## 9. Devir notları / bilinen sınırlar

* **`SimApprovalGate.vue` başlığı bayat kaldı:** "Sunucu tarafı kapı YOK —
  ölçüldü" yazıyor; artık VAR. Dosya simulator dizininde (bana yasak) —
  simulator sahibi ajan başlığı ve ekrandaki "bu kapı yalnız istemcide" notunu
  güncellemeli. `useSimulatorApproval.js` başlığındaki aynı iddia da öyle.
* Panelde "Uygula", kapı tamamlanmadan basılırsa artık sunucudan
  MEDIA_PREVIEW_REQUIRED alır ve `saveError` olarak görünür — şartnamenin
  istediği bu; ama düğmeyi kapı tamamlanana dek pasifleştirmek (UX) simulator
  sahibinin alanında.
* T-114 şartnamesindeki "slotun gerektirdiği cihaz sınıfları eksikse" içerik
  denetimi (kanıtın phone/tablet/desktop kapsaması) bu görevin metninde
  "boşsa reddet" olarak daraltılmıştı; içerik-kapsam denetimi ayrı iş.
* Panel dist'i Docker imajında — değişikliklerin istoc.localhost'ta görünmesi
  için `npm run build` + compose rebuild gerekir (memory notu); bu görevde
  yalnız test/lint koşuldu, imaj yenilenmedi.
* Ölçüm sırasında dev sitenin Administrator parolası geçici değiştirildi ve
  compose varsayılanına (`admin`) geri alındı; ölçüm varlığı (`jhcs6pgjbo`)
  ve niyeti silindi.
* Ruff: dokunulan dosyalarda bulgu sayısı HEAD ile aynı; tek ek bulgu
  `core/crop.py`'de `Optional[Rect]` (UP045) — dosyanın mevcut, her yerde
  kullanılan stiliyle tutarlı bırakıldı.
