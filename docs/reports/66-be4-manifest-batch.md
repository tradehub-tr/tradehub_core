# 66 — BE4: Toplu dosya manifesti ucu ve panel tüketimi (T-083)

**Tarih:** 2026-08-20 · **Kapsam:** `manifest_batch` whitelist ucu + `useMediaRenditions.js` toplu tüketim + testler

## 1. Ölçülen boşluk

- `grep -rn "manifest_batch" admin-panel/frontend/src` → **0 sonuç** (iş öncesi).
- Panelin türev tablosu (`useMediaRenditions.js`) dosya başına **2 REST isteği** atıyordu:
  `GET /api/resource/Media Asset` (source_file süzgeci) + `GET /api/resource/Media Rendition` (asset in […]).
- Şartname T-083: "`manifest_batch` ile N asset tek istekte alınabiliyor… Maksimum N'i sınırla ve aşımda hata döndür… başka satıcıya ait asset için sızıntı yok."

## 2. Uç imzası ve tavan

```python
# tradehub_core/api/media_manifest.py
@frappe.whitelist()  # guest YOK — panel ucu; misafir akışı get_manifest_batch'te
def manifest_batch(file_urls: list | str | None = None) -> dict
```

- **Girdi:** `File` docname'leri ya da `file_url` adresleri (JSON dizisi kabul; virgüllü dizge kabul EDİLMEZ — dosya adında virgül geçebilir). Tekrarlar tekilleştirilir.
- **Çıktı:** `{"manifests": {<istenen adres>: manifest|null}, "requested", "returned", "max_batch"}`.
  Manifest: `{"file", "file_url", "assets": [...], "renditions": [{name, asset, profile, width, height, format, file_url, bytes, ssim, generation, benefit_gate_passed}]}`.
- **Tavan:** `FILE_BATCH_MAX = pipeline_delivery.MAX_BATCH = 100`. Şartnamede sayı yok; pipeline sözleşmesindeki 100 alındı ve iki sabit birbirine bağlandı. Aşım **reddedilir** (`frappe.ValidationError`) — ilan-bazlı `get_manifest_batch`in "kırp" davranışının aksine, çünkü bu uç oturumlu bir panel ucudur: programlama hatası sesli kırılmalı. Tam 100 kabul edilir (off-by-one testi var).
- Dosya başına alt tavanlar eski FE davranışıyla birebir: ≤5 en yeni varlık, ≤60 türev.
- **"İkinci manifest üretici" yazılmadı:** `delivery/manifest.py::ManifestBuilder` vitrinin `srcset`/`sizes` üreticisidir ve fayda kapısını geçmeyen türevi gizler; panel ise üretim ENVANTERİNİ (elenenler dâhil) gösterir. Bu uç bu yüzden manifest kurmaz — panelin bugüne kadarki 2 adımlı sorgusunu sunucuda toplu sarar. Envanter/teslim ayrımı `manifest_batch` docstring'inde yazılı.

## 3. Yetki modeli ve tenant ölçümü

Erişim denetimi **adres başına** ve tamamen sunucuda:

1. `File` çözümü `frappe.get_list` ile → Frappe'nin File izin süzgeci (`file.py::get_permission_query_conditions`): başkasının bağsız özel dosyası hiç çözülmez → haritada `null`. `null` "yok" ile ayırt EDİLMEZ — varlık sızdırılmaz, hata fırlatılmaz (kısmi başarı).
2. `Media Asset` / `Media Rendition` okumaları `frappe.get_list` ile → `hooks.py`'deki mevcut `media_asset_query_conditions` / `media_rendition_query_conditions` (satıcı yalnız `owner_seller = kendi mağazası` varlıkları görür). Public dosyada bile başka satıcının varlık adı/türev adresi yanıta giremez.

**Ölçüm (konteynerde koştu):**

```
docker exec istoc-dev-backend-1 bench --site istoc.localhost \
    run-tests --module tradehub_core.tests.test_manifest_batch
Ran 13 tests — OK
```

**Vacuity kanıtı (kontrol gevşetilip KIRMIZI gösterildi):** üç `get_list`e geçici olarak `ignore_permissions=True` eklendi ve aynı koşu **FAILED (failures=3)** verdi — satıcı A'ya B'nin özel dosyasının manifesti (docname, file_url, varlık adı ve türev adresleriyle) döndü; `test_baskasinin_ozel_dosyasi_none_doner`, `test_baskasinin_public_dosyasinin_varligi_ve_turevleri_sizmiyor`, `test_karisik_istekte_yalniz_kendininki_dolu` üçü de kırıldı. Gevşetme geri alındı, koşu yeniden yeşil. İzolasyon testlerinin her birinde pozitif kontrol var: sahibi aynı adresin TAM envanterini alıyor (boşluk süzgecin eseri, kırık fixture'ın değil).

Regresyon: `tradehub_core.tests.test_media_manifest_api` (mevcut ilan-bazlı uçlar) 11/11 yeşil.

## 4. FE istek sayısı — önce/sonra (istek SAYISI, süre iddiası yok)

| Akış | Önce | Sonra |
|---|---|---|
| `load(fileDocName)` (bir dosyanın türev tablosu) | **2 istek** (Media Asset getList + Media Rendition getList) | **1 istek** (`manifest_batch`, `{file_urls: [docname]}`) |
| N dosya (gelecekteki liste görünümleri) | 2N | 1 (uç N≤100 adresi tek çağrıda alır) |

Sayı testle sabitlendi: `src/composables/__tests__/mediaRenditions.test.js` bir `load()` için `calls.length === 1` ve `getList` çağrı sayısı `0` iddiasını ölçer; stub `getList`i bilerek patlatır — eski yola sessiz dönüş mümkün değil.

Çağıran bileşenlerin sözleşmesi DEĞİŞMEDİ: `{rows, loading, emptyReason, error, denied, load, clear}` ve satır şekli (`id/profile/width/height/format/fileUrl/bytes/ssim/generation`) aynı; `MediaRenditionList.vue` / `MediaQualityPanel.vue` dokunulmadı. Boş durumlar dürüst kaldı: çözülmeyen adres ve varlıksız dosya → `noAsset`; varlık var türev yok → `noRenditions`; ikisi de arıza değil (bayraklar kapalıyken beklenen hâl).

## 5. Dosyalar

| Dosya | İş |
|---|---|
| `tradehub_core/tradehub_core/api/media_manifest.py` | `manifest_batch` + `_dosya_varliklari` / `_varlik_turevleri` / `_dosya_listesi_coz` + `FILE_BATCH_*` sabitleri (mevcut uçlara dokunulmadı) |
| `tradehub_core/tradehub_core/tests/test_manifest_batch.py` | **Yeni** — 13 test: N adres tek çağrı, tavan aşımı reddi, tam-tavan kabulü, boş liste, guest reddi, docname/url çözümü, tekilleştirme, satır sözleşmesi, fayda-kapısı envanteri, 3 tenant izolasyon testi (pozitif kontrollü) |
| `admin-panel/frontend/src/composables/useMediaRenditions.js` | 2 adımlı REST → toplu uç; dönen şekil değişmedi |
| `admin-panel/frontend/src/composables/__tests__/mediaRenditions.test.js` | **Yeni** — 9 test: toplu çağrının şekli, istek sayısı 1, getList'e düşülmediği, boş durumlar, 403/arıza ayrımı |
| `admin-panel/frontend/src/composables/__tests__/fixtures/renditionApiStub.js` | **Yeni** — `@/utils/api` sahtesi; `getList` bilerek patlar |
| `admin-panel/frontend/src/components/media/__tests__/mediaRenditions.test.js` | **Kural istisnası** — aşağıda §6 |
| `admin-panel/frontend/src/components/media/__tests__/fixtures/apiMock.js` | Paylaşılan sahteye `callMethod` kancası EKLENDİ (`__mediaApiCallMock`); `getList` kancası aynen duruyor — `mediaDetailDrawer` (11/11) ve `mediaSimulator` testleri etkilenmedi |

## 6. Kural istisnası: mevcut bir test dosyası güncellendi (gizlenmedi)

Görev "mevcut test dosyaları"nı yasaklıyordu; ancak `src/components/media/__tests__/mediaRenditions.test.js` tam olarak değiştirilen composable'ın ESKİ taşıma katmanını (Media Asset/Rendition getList çağrıları, süzgeçleri, order_by'ı) sabitliyordu. Toplu uca geçiş bu dosyanın 6 testini kaçınılmaz olarak kırdı — görevin iki maddesi birbiriyle çelişti. Seçenekler: (a) 6 kırmızı test bırakmak, (b) sahteye eski protokolü taklit ettirip testleri "yeşil gibi" göstermek, (c) testleri yeni taşımaya şeffafça taşımak. (c) yapıldı: 8 testin adı ve davranış iddiaları (boş durumlar, eşleme, 403/arıza ayrımı, bileşen bağlantısı) korundu, yalnız taşıma-katmanı iddiaları toplu uca çevrildi. İstek sayısı/şekil ölçümünün asıl sahibi yeni composable testi.

## 7. hooks / i18n / bilinen dışsal kırmızılar

- **hooks.py ihtiyacı: YOK.** Uç, izolasyonu hooks'ta ZATEN kayıtlı `media_asset/rendition_query_conditions` süzgeçlerinden `frappe.get_list` ile alıyor; yeni kayıt gerekmedi. `patches.txt` de gerekmedi (DocType yok, migrate yok).
- **i18n anahtarı: yeni anahtar YOK.** Backend hata metinleri `frappe.throw(_("..."))` ile (3 mesaj: oturum zorunlu, tavan aşımı, liste değil). FE mevcut `media.renditions.*` anahtarlarını kullanmaya devam ediyor; `i18n/locales` dokunulmadı.
- **Bana ait olmayan, koşu sırasında görülen kırmızılar** (ikisi de paralel ajan işi, dosyaları görevin yasak listesinde):
  - `src/lib/media/crop/__tests__/cropPixelParity.test.js::vektörler canlı core/crop.py ile aynı sürümden` — backend `core/crop.py` değişmiş, vektör hash'i eskimiş.
  - `src/lib/media/upload/__tests__/queue.test.js::politikaya uyan görsel gerçekten uçlara gidiyor` — koşu ortasında `upload/dedupCheck.js` güncellendi (mtime bu oturumun içinde); yükleme artık `find_in_my_library` çağrısı da atıyor, testin beklediği `["upload_media"]` listesi eskidi.
  - Bunlar dışında FE süiti yeşil: **803 test, 801 pass** (2 fail yukarıdaki dışsallar).

## 8. Koşturulan doğrulamalar

```
# backend (konteynerde)
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_manifest_batch   → 13 OK
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_manifest_api → 11 OK
# vacuity: 3× get_list'e ignore_permissions eklenince → FAILED (failures=3), geri alındı → OK

# lint
python3 -m ruff check tradehub_core/api/media_manifest.py tradehub_core/tests/test_manifest_batch.py → temiz

# FE (admin-panel/frontend)
node --test src/composables/__tests__/mediaRenditions.test.js → 9/9
node --test src/components/media/__tests__/mediaRenditions.test.js → 8/8
node --test ...mediaDetailDrawer.test.js ...mediaSimulator.test.js → yeşil (paylaşılan sahte kırılmadı)
npm test → 803 test / 801 pass (2 dışsal, §7)
npx eslint + prettier (dokunulan 5 dosya) → temiz
```

Migrate gerekmedi (DocType/patch yok); kilit desenine ihtiyaç doğmadı. `docker cp` ile konteynere kopyalandı, testler konteynerde koştu.

---

## 9. EK (2026-08-20, devam görevi) — Mükerrer File kör noktası kapatıldı (69 raporu §7.1)

### 9.1 Bulgu ve kök neden

W3-B gerçek veriyle ölçtü: aynı `file_url`'de 5+ mükerrer `File` satırı var; `Media Asset.source_file`
bunlardan yalnız BİRİNE bağlı. `manifest_batch` File↔Asset join'ini docname üzerinden yapıyordu →
kullanıcının verdiği docname varlığın bağlı olduğu satır değilse "boru hattında yok" dönüyordu.
Adresle sorguda da `{file_url: satır}` sözlüğü mükerrerlerden rastgele birini tutuyordu (aynı körlük).
İlan tarafı (`_varliklari_getir`) `file_url` join'i kullandığı için etkilenmiyordu.

### 9.2 Düzeltme

`api/media_manifest.py` — `_mukerrer_dosya_koprusu()` eklendi, `_dosya_varliklari()` köprü anahtarıyla
(`file_url`) gruplar oldu:

1. Adres çözümü DEĞİŞMEDİ: `File` `get_list` (Frappe izin süzgeci) — başkasının bağsız özel dosyası
   yine çözülmez, `null` kalır.
2. **Köprü:** çözülen satırların adreslerini taşıyan TÜM File docname'leri `frappe.get_all` ile
   toplanır. `get_all` bilinçli ve gerekçesi kodda: (a) girdi adresler zaten izinli (1. adımdan),
   aynı adres aynı fiziksel dosya; (b) çıktı docname'ler yanıta yazılmaz, yalnız `source_file in (...)`
   süzgecini genişletir; (c) kiracı kapısı sonraki halkada duruyor. Köprüyü izinli `get_list` yapmak
   kör noktayı GERİ getirirdi: mükerrer satırın sahibi başka kullanıcı olabilir.
3. Varlık/türev okumaları DEĞİŞMEDİ: `frappe.get_list` + hooks'taki query_conditions — kiracı sınırı
   aynen yerinde.

### 9.3 Gerçek veriyle önce/sonra (DEV, konteyner konsolu, Administrator)

**ÖNCE** (docname join):

| Dosya | File satırı | Sorgu | Sonuç |
|---|---|---|---|
| `/files/Bere.png` | 9 mükerrer | 8/9 docname | **assets=[] renditions=0** ("boru hattında yok") |
| | | varlığın bağlı olduğu 1 docname (`bd5b581362`) | assets=[7pa8r42g7d] renditions=10 |
| | | `file_url` ile | **assets=[] renditions=0** |
| `/files/067-1 GRİ.jpg` | 9 mükerrer | 8/9 docname | **assets=[] renditions=0** |
| | | `45412ba561` | assets=[7qt7siovrn] renditions=12 |
| | | `file_url` ile | **assets=[] renditions=0** |

**SONRA** (file_url köprüsü): her iki dosyada **9/9 docname VE `file_url`** aynı envanteri döndü —
Bere.png: assets=[7pa8r42g7d], 10 türev; 067-1 GRİ.jpg: assets=[7qt7siovrn], 12 türev. Örnek satır
(067-1, w96): `/files/media/7qt7siovrn/4b7e4bae…f3ac6e/w96-96.webp`, 1.348 B, ssim 0.9703,
benefit_gate_passed=1 — W3-B'nin ölçtüğü gerçek türev adresleriyle birebir.

### 9.4 Testler ve vacuity

`tests/test_manifest_batch.py` **16 test** (13 + 3 yeni `ManifestBatchDuplicateFileTests`):

- `test_mukerrer_docname_ile_ayni_manifest_doner` — varlığın bağlı OLMADIĞI mükerrer docname tam
  envanteri döner. İki AYRI çağrıyla ölçülür — ilk vacuity denemesi, asıl docname aynı isteğe
  konunca emniyet yedeğinin testi kurtardığını gösterdi (test yeşil kalıyordu); test buna göre
  SERTLEŞTİRİLDİ ve gerekçe docstring'de.
- `test_mukerrer_satir_varken_adresle_sorgu_da_calisir` — adres yüzü (69 §7.1 yüz-1). Docstring
  dürüst: köprüsüz dünyada çözümün hangi satırı tuttuğu sırasız olduğundan bu test şansla yeşil
  kalabilir; deterministik kırmızı docname testindedir.
- `test_mukerrer_kopru_kiraci_sinirini_acmaz` — köprü `get_all` kullandığı için EN kritik test:
  A, B'nin public dosyasının mükerrer satırını (sahibi A olsa bile) sorduğunda B'nin varlık/türev
  envanteri sızmaz (gövde taraması); pozitif kontrol: B aynı mükerrer docname ile TAM envanteri alır.

**Vacuity koşuları (konteynerde):**

```
köprü genişletmesi kapatıldı (eski docname-join) → FAILED (failures=2):
    test_mukerrer_docname_ile_ayni_manifest_doner + test_mukerrer_kopru_kiraci_sinirini_acmaz
3× get_list'e ignore_permissions (izolasyon vacuity, yeni kod üstünde) → FAILED (failures=4):
    eski 3 izolasyon testi + yeni köprü-kiracı testi
düzeltme geri kondu → Ran 16 tests — OK
```

FE değişiklik GEREKMEDİ (yanıt şekli aynı): `mediaRenditions` testleri 17/17 yeşil.

### 9.5 Dışsal not — `test_media_manifest_api` (sahibi başkası, dokunulmadı)

Modül şu an **2 kırmızı** (`test_bayrak_acikken_gercek_rendition_listesi`,
`test_storefront_visible_kapali_ilan_misafire_bos_doner`). Benim diff'im DEĞİL — kanıt: köprü-öncesi
sürümle de aynı 2 test kırmızı (koşuldu). Neden: W3-B koşusu bayrakları AÇIK bıraktı ve testin fixture
kurduğu dosya (LST-00201 / nf.jpg) için gerçek varlık `7m7n6rs4d4` + 10 gerçek türev artık DB'de;
test "manifest yalnız benim fixture türevlerimi içerir" varsayımıyla yazılmış ve kirlenmiş ortamda
gerçek türevleri de görüyor. Düzeltme o test dosyasının sahibinin işi (fixture'ı ortam-bağımsız
kılmak ya da testte gerçek varlıkları dışlamak).
