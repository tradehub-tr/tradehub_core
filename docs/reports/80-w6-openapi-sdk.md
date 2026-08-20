# 80 — W6: OpenAPI → tipli TS istemci + contract testleri

**Tarih:** 2026-08-20 · **Görev:** Faz 8 SDK ayağı — T-080 ("şemalardan TS
tipleri üretiliyor ve frontend bunları kullanıyor"), T-084 (contract
testleri), T-085 ("TypeScript istemci SDK") kabul kriterlerinin eksik
yarıları. · **Şartname:** `52-faz8-api.html`

Denetim (61e) doğruydu: panelde OpenAPI'den üretilmiş tek satır tip yoktu,
şartnamenin adını verdiği `ui/src/api/client.ts` yoktu. Bu turda ikisi de
yazıldı — **mevcut `src/utils/api.js` değiştirilmedi, hiçbir çağıran
göçürülmedi** (görev sınırı).

---

## 1. Kaynak sözleşme seçimi

İki OpenAPI belgesi var ve ayrımı belgelerin kendisi kilitliyor
(`x-layer-note`):

| Belge | Anlattığı | Panel için |
|---|---|---|
| `docs/api/openapi.yaml` | Saf Python kütüphane katmanı (`pipeline/api/`), whitelist YOK, `/api/media/v1/…` yollarına istek ATILAMAZ | **kullanılamaz** |
| `docs/api/openapi-http.yaml` | Gerçek `@frappe.whitelist()` yüzeyi, `/api/method/…` | **SEÇİLEN** |

Tip üretimi `openapi-http.yaml`dan yapıldı; `openapi.yaml`dan tip üretmek
çağrılamayan yollara "çağrılabilir" tip görüntüsü verirdi.

## 2. Spec bayatlık ölçümü — 10 uç ayrıktı + 2 şema sapması

Üreticinin kendi kapısı ölçtü (`python3 scripts/gen_http_openapi.py --check`,
düzeltme ÖNCESİ çıktı): **9 uç kodda var, belgede yok** — ayrıca `rum.collect`
üretici `KAYNAKLAR`ında `rum.py` olmadığı için hiç GÖRÜNMÜYORDU (10. uç).

| Ayrık uç | Kod kanıtı |
|---|---|
| `media_manifest.manifest_batch` (dosya bazlı, `version` anahtarlı) | `tradehub_core/api/media_manifest.py:328` (dönüşte `version`: :431) |
| `rum.collect` | `tradehub_core/api/rum.py:217-234` |
| `seller_media.list_folders` | `tradehub_core/api/seller_media.py:825` |
| `seller_media.create_folder` | `seller_media.py:858` |
| `seller_media.rename_folder` | `seller_media.py:880` |
| `seller_media.delete_folder` | `seller_media.py:892` |
| `seller_media.move_media` | `seller_media.py:903` |
| `seller_media.list_folder_media` | `seller_media.py:949` |
| `seller_media.find_in_my_library` | `seller_media.py:994` |
| `seller_media.list_orphans` | `seller_media.py:251` |

Şema sapmaları:

1. **`CropIntentBody` zoom üçlüsü eksikti** — `save_intent` imzası bugün
   `zoom`/`center_x`/`center_y` alıyor (`api/media_crop.py:451-467`) ve
   `get_intent` gövdesi üçlüyü döndürüyor (`pipeline/api/crop.py:285-287`;
   birlikte-verilme kuralı `:415-437`). Parametreler üreticinin AST
   taramasıyla kendiliğinden düzeldi; gövde şemasına üç alan elle eklendi.
2. **Kütüphane belgesi `docs/api/openapi.yaml` bayt-sapmıştı**: `spec.py`
   zoom'u almış, YAML yeniden üretilmemişti —
   `test_api_contracts.py::test_bayt_esitligi` KIRMIZI ölçüldü.
   `spec.write_yaml()` ile yeniden üretildi → 126/126 yeşil.

### Yapılan spec güncellemeleri (kaynak: gerçek kod)

* `scripts/gen_http_openapi.py`: `KAYNAKLAR += rum.py` (+ `rum` etiketi);
  10 uç için `OLCUM` kaydı (aşağıdaki canlı ölçümler); 9 yeni gövde şeması
  (`FileManifestBatch`, `FileManifest`, `FolderList`, `FolderCreated`,
  `FolderRenamed`, `FolderDeleted`, `MoveResult`, `OrphanList`,
  `LibraryMatch`, `RumAck`) + `SEMA_BAGI` bağları (`list_folder_media` →
  mevcut `PagedFiles`); `CropIntentBody`ye zoom üçlüsü; `rum.collect`e
  `text/plain` gövde/CSRF-muafiyet anlatımı.
* `docs/api/openapi-http.yaml` yeniden üretildi: **90 → 100 uç**, misafir
  3 → 4 (`rum.collect`), ölçülen 79 + kısmi 20 + gerekçeli ölçülmeyen 1.
* `tradehub_core/tests/test_http_api_contracts.py`: uç sayısı kilidi
  100'e (etiket kırılımıyla), misafir listesi kilidi `rum.collect`
  gerekçesiyle güncellendi. Suite: **41 test OK** (canlı modda
  `ISTOC_HTTP_BASE=http://istoc.localhost` ile de OK, skipped 16 → 6).
* `docs/api/README.md` §4.2: uygulanmayan `openapi-generator` önerisi,
  uygulanan vendor deseniyle değiştirildi.
* Spectral (`spectral:oas`): **0 hata**, 95 uyarı (tümü önceden de var olan
  `operation-description`/`unused-component` sınıfı).

### Canlı ölçümler (2026-08-20, http://istoc.localhost)

Satıcı oturumu `tests/e2e/global-setup.ts` deseniyle bench'te basıldı
(`ali.bal@turksab.com` → SEL-00003). 10 ucun 10'u gerçek HTTP ile ölçüldü;
yazan ölçümlerin izleri temizlendi (klasör silindi, dosya köke geri taşındı).
Örnekler: `manifest_batch` → `{manifests:{<adres>:{file,file_url,assets,
renditions,version}|null}, requested, returned, max_batch:100}`;
`rum.collect` (misafir, `text/plain`) → 200 `{ok:true}`;
`find_in_my_library` geçersiz hash → 417. Tam kayıtlar belgede
(`x-measurement` alanları).

## 3. Tip üretimi — vendor deseni (sha256 manifest + `--check`)

* **`admin-panel/frontend/scripts/sync-api-types.mjs`** —
  `sync-crop-geometry.mjs` ile aynı desen: kaynak yoksa `--check` "ÖLÇÜLMEDİ"
  der (0), üretim modu hata verir; sha256 zinciri
  `src/lib/api/api.manifest.json`da.
* **`src/lib/api/types.gen.ts`** — `openapi-typescript@7.13.0`
  (devDependency zaten kuruluydu; lock'a dokunulmadı). Üretilen:
  **5.232 satır · 100 path · 100 operation · 29 gövde şeması** (9'u bu turun
  yeni şemaları). Yalnız TİP üretir, çalışma zamanı kodu üretmez —
  README §4.1'deki bilinçli tercihle aynı gerekçe.
* NPM script'leri: `sync:api`, `sync:api:check`, `contract:api`.

## 4. Tipli istemci — `src/lib/api/client.ts`

`utils/api.js`i SARAN ince katman; **ikinci HTTP yığını yazılmadı**:

* Her çağrı `api.callMethod` / `api.callMethodGET`'e iner — CSRF alma/yenileme,
  401→`/panel/reset`, hata kodu ayıklama (`buildError`) ORADA kalır.
* İstemcinin işi: uç adı + GET/POST kararını sözleşmeye sabitlemek, Frappe
  zarfını (`{message}`) tek yerde açmak, `QueryOf`/`MessageOf` tiplerini
  taşımak. 19 medya ucu sarıldı (delivery 4, crop 3, kütüphane 5, klasör 6 +
  `moveMedia`).
* `utils/api.js` modül yüklenirken `import.meta.env` okuduğu (Vite'a özgü)
  için varsayılan taşıma TEMBEL import; testler sahte taşıma enjekte eder.
  Örnek tüketim: `src/lib/api/__tests__/client.test.js` (4 test — uç adı,
  GET/POST seçimi, zarf açma, null-manifest davranışı).
* Mevcut çağıran GÖÇÜRÜLMEDİ — ayrı iş.

## 5. Contract testleri (T-084 panel ayağı)

`src/lib/api/__tests__/contract.live.test.js` — canlı konteynere karşı yanıt
**ŞEKLİNİ** doğrular (alan varlığı + tip; değer değil). Beklenen alan
listeleri ELLE YAZILI DEĞİL: sözleşme YAML'ının `required` bloklarından
okunur — spec ile test aynı doğruluk kaynağı.

| Kapsam | Uçlar | Durum |
|---|---|---|
| Ölçülen (misafir, her `npm test`te) | `get_manifest`, `get_manifest_batch`, `rum.collect`, `manifest_batch`in 403 misafir reddi | 4/4 yeşil |
| Ölçülen (oturumlu, `npm run contract:api`) | `manifest_batch`, `list_folders`, `list_orphans`, `find_in_my_library`, `get_my_summary` | 5/5 yeşil (hem hazır sid hem taze bench sid ile koşuldu) |
| ÖLÇÜLMEDİ (gerekçeli atlama) | crop üçlüsü (sahip olunan `Media Asset` kimliği ister), `get_signed_url` (private dosya ister), klasör yazma döngüsü (her koşuda veri yazmamak için — 2026-08-20 elle ölçümü spec'in `x-measurement`ında) | testler "atlandı" der, "geçti" demez |

Backend kapalıysa/depo yoksa TÜM testler gerekçeyle atlanır (crop-parite
deseni: "ölçülmedi ≠ geçti").

## 6. Doğrulama + vacuity

| Kapı | Sonuç |
|---|---|
| `npm test` (panel) | **884 test · 879 pass · 0 fail · 5 skipped** (taban 871 → +13; 5 atlanan = oturum-kapılı contract testleri, `contract:api` ile 9/9 ölçüldü) |
| `npm run lint` | **0 hata** (2 uyarı önceden var olan `PlansTab.vue`) |
| `node scripts/sync-api-types.mjs --check` | temiz |
| `python3 scripts/gen_http_openapi.py --check` | temiz |
| `test_http_api_contracts` (41) / `test_api_contracts` (126) | OK / OK |

**Vacuity kanıtı** — `openapi-http.yaml`da tek alan bozuldu
(`FolderList.required: max_depth → max_depht`):

1. `gen_http_openapi.py --check` → `SAPMA` (exit 1) ✔
2. `sync-api-types.mjs --check` → 2 dosya AYRIŞMA (exit 1) ✔
3. contract testi `list_folders` → **KIRMIZI** (canlı gövdede `max_depht` yok) ✔

Geri alındı (yeniden üretimle), üç kapı da yeşile döndü.

## 7. Bu turda YAPILMAYAN

* Mevcut çağıranların `client.ts`e göçü (görev sınırı — bir örnek tüketim
  testi var, ekran kodu dokunulmadı).
* `save_intent` `overrides` uyuşmazlığı (spec `x-mismatch`te DURUYOR —
  düzeltme backend işi, bu görevde uç davranışı değiştirmek yasaktı).
* Bruno/Postman koleksiyonu (T-085 madde 3) ve CI kancası (T-085 madde 4)
  — `--check` script'leri hazır, CI'a bağlanmadı.
* `list_folder_media`/klasör yazma uçlarının contract-test ölçümü (yukarıda
  gerekçeli; elle ölçümleri spec'te).
