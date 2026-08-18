# Medya Motoru API — sürüm dondurma ve SDK üretimi

**T-085 · Faz 8 · sözleşme sürümü `1.0.0` · OpenAPI `3.1.0`**

Bu klasör iki dosyadır ve ikisinin ilişkisi tek yönlüdür:

```
tradehub_core/media/pipeline/api/spec.py        TEK DOĞRULUK KAYNAĞI  (Python sözlüğü)
        │  build_document()
        ▼
docs/api/openapi.yaml           ÜRETİLMİŞ ÇIKTI       (elle düzenlenmez)
        │
        ▼
SDK'lar                         ÜRETİLMİŞ ÇIKTI       (depoya girmez)
```

`openapi.yaml`'ı elle düzenlemek, bir sonraki üretimde sessizce kaybolur.
`tests/test_api_contracts.py::YamlSapmaTesti::test_bayt_esitligi` bu yüzden var:
dosya kaynağıyla ayrıştığı anda test kırılır.

---

## 1. Yeniden üretme ve doğrulama

```bash
# Belgeyi yeniden üret (spec.py değiştiğinde ZORUNLU)
cd tradehub_core
python3 -c "from media_engine.api import spec; print(spec.write_yaml())"

# Sözleşme + davranış testleri (frappe GEREKMEZ)
python3 -m unittest tests.test_api_contracts -v

# Konteynerde (PyYAML orada var: 6.0.3 — YAML ayrıştırma testi de koşar)
docker exec istoc-dev-backend-1 bash -lc \
  'cd /home/frappe/olcum/faz8/root && PYTHONPATH=. \
   /home/frappe/frappe-bench/env/bin/python tests/test_api_contracts.py'
```

**Neden kendi YAML yazıcımız var:** `PyYAML` yerelde kurulu değil (ÖLÇÜLDÜ:
`python3 -c "import yaml"` → `ModuleNotFoundError`), bench ortamında var
(6.0.3). PyYAML'a bağlanmak belgeyi yalnız konteynerde üretilebilir kılardı.
`spec.dump_yaml` YAML'ın küçük ve tam belirli bir alt kümesini basar (eşleme,
dizi, çift tırnaklı dizge, sayı, mantıksal değer, null — yorum/çapa/etiket/blok
skaler YOK). Çıktının gerçekten geçerli YAML olduğu, PyYAML'ın bulunduğu
ortamda `test_gercek_yaml_ayristiricisiyla_tur_atlar` ile **bağımsız olarak**
doğrulanır: kendi yazıcımızı kendi okuyucumuzla doğrulamak hiçbir şey
kanıtlamazdı.

---

## 2. Sürüm dondurma politikası

Sözleşme sürümü `tradehub_core/media/pipeline/api/spec.py::API_VERSION`'dadır ve
`info.version` alanına basılır. **Semantik sürümleme**, ama "kırıcı"nın tanımı
burada yazılıdır — yoruma bırakılmaz.

### 2.1 MAJOR (1.x → 2.0) — yol öneki DEĞİŞİR

Aşağıdakilerden **biri** bile yapılıyorsa yeni önek (`/api/media/v2`) açılır ve
eski önek en az bir sürüm boyunca yaşamaya devam eder:

| Değişiklik | Neden kırıcı |
|---|---|
| Bir uç noktanın kaldırılması ya da yolunun değişmesi | İstemci 404 alır |
| Zorunlu bir istek alanının eklenmesi | Eski istemci 400 alır |
| Bir yanıt alanının kaldırılması ya da adının değişmesi | İstemci `undefined` okur |
| Bir alanın tipinin değişmesi (`string` → `object` vb.) | Ayrıştırma çöker |
| Bir `enum`dan değer çıkarılması | İstemcinin `switch`'i düşer |
| Bir HTTP durum kodunun anlamının değişmesi | Yeniden deneme mantığı bozulur |
| Bir `error_code`un anlamının değişmesi | Karar METNE değil KODA bakıyor (FR-060) |
| Yetki kapısının GENİŞLETİLMESİ | Sessiz veri sızıntısı riski |

### 2.2 MINOR (1.0 → 1.1) — geriye dönük uyumlu ekleme

* Yeni uç nokta.
* Yeni **isteğe bağlı** istek alanı.
* Yeni yanıt alanı. *İstemciler bilinmeyen alanı YOK SAYMALIDIR* — bu, tüketici
  tarafında sözleşmenin bir parçasıdır.
* `enum`a yeni değer eklenmesi. *İstemcilerin `default` dalı olmalıdır.*
* Yeni `error_code`. *İstemciler bilinmeyen kodu, yanıtın `retryable` bayrağına
  göre işlemelidir — kod listesini sabitlemek yasak.*

### 2.3 PATCH (1.0.0 → 1.0.1)

Yalnız açıklama/örnek/`summary` metinleri. Şema DEĞİŞMEZ.

### 2.4 Bir ucu kaldırma yordamı

1. `deprecated: true` işaretle, `description` içine kaldırma tarihini yaz.
2. Yanıta `Deprecation` ve `Sunset` başlıklarını ekle (RFC 8594).
3. **En az bir MINOR sürüm** boyunca çalışmaya devam etsin.
4. Kaldırma bir MAJOR'dur.

### 2.5 Bugünün donmuş yüzeyi — 21 uç

| Uç | operationId | Python | Yetki |
|---|---|---|---|
| `POST /api/media/v1/upload/sessions` | `createUploadSession` | `upload.UploadApi.create_session` | Oturum + mağaza |
| `GET /api/media/v1/upload/sessions/{upload_id}` | `getUploadStatus` | `upload.UploadApi.status` | Oturum + mağaza |
| `PUT /api/media/v1/upload/sessions/{upload_id}/chunks/{index}` | `putUploadChunk` | `upload.UploadApi.put_chunk` | Oturum + mağaza |
| `POST /api/media/v1/upload/sessions/{upload_id}/finalize` | `finalizeUpload` | `upload.UploadApi.finalize` | Oturum + mağaza |
| `DELETE /api/media/v1/upload/sessions/{upload_id}` | `abortUploadSession` | `upload.UploadApi.abort` | Oturum + mağaza |
| `GET /api/media/v1/assets/{asset}/crop-intent` | `getCropIntent` | `crop.CropApi.get_intent` | Oturum + sahiplik |
| `PUT /api/media/v1/assets/{asset}/crop-intent` | `saveCropIntent` | `crop.CropApi.save_intent` | Oturum + sahiplik |
| `POST /api/media/v1/assets/{asset}/crop-intent/suggest-focal` | `suggestFocalPoint` | `crop.CropApi.suggest_focal` | Oturum + sahiplik |
| `POST /api/media/v1/assets/{asset}/crop-preview` | `previewCrop` | `crop.CropApi.preview` | Oturum + sahiplik |
| `GET /api/media/v1/delivery/{asset}/manifest` | `getDeliveryManifest` | `delivery.DeliveryApi.manifest` | **Guest'e açık** (public varlık) |
| `POST /api/media/v1/delivery/manifests` | `getDeliveryManifestBatch` | `delivery.DeliveryApi.manifest_batch` | **Guest'e açık** (public varlık) |
| `POST /api/media/v1/delivery/{asset}/signed-url` | `createSignedUrl` | `delivery.DeliveryApi.signed_url` | Oturum + okuma yetkisi |
| `GET /api/media/v1/admin/slot-policies` | `listSlotPolicies` | `admin.AdminApi.list_slot_policies` | Admin |
| `GET /api/media/v1/admin/slot-policies/{slot_key}` | `getSlotPolicy` | `admin.AdminApi.get_slot_policy` | Admin |
| `POST /api/media/v1/admin/slot-policies/validate` | `validateSlotPolicies` | `admin.AdminApi.validate_policies` | Admin |
| `GET /api/media/v1/admin/rendition-matrix` | `getRenditionMatrix` | `admin.AdminApi.rendition_matrix` | Admin |
| `POST /api/media/v1/admin/policy-evaluations` | `evaluatePolicy` | `admin.AdminApi.evaluate_policy` | Admin |
| `GET /api/media/v1/admin/delivery-coverage` | `getDeliveryCoverage` | `admin.AdminApi.delivery_coverage` | Admin |
| `POST /api/media/v1/admin/reprocess-plans` | `planReprocess` | `admin.AdminApi.plan_reprocess` | Admin |
| `POST /api/media/v1/admin/job-status` | `getJobStatus` | `admin.AdminApi.job_status` | Admin |
| `GET /api/media/v1/admin/storage-plan` | `getStoragePlan` | `admin.AdminApi.storage_plan` | Admin |

> **Admin** = `System Manager` ya da `Marketplace Admin` —
> `tradehub_core/api/media_admin.py:33` `ALLOWED_ROLES` ile AYNI küme.
> `tradehub_core/media/pipeline/api/envelope.py::ADMIN_ROLES` o listenin aynasıdır.

---

## 3. Frappe'ye bağlama — nerede, nasıl

### 3.1 Neden `media_engine` içinde `@frappe.whitelist()` yok

`media_engine` bir **kütüphanedir**, Frappe app'i değil (gerekçe:
`docs/sad/SAD-v1.0.md` §2.3, S-01 sapması). Uç noktalar saf Python
fonksiyonlarıdır ve `envelope.ApiResponse` **döndürür**; hiçbiri
`frappe.local.response`'a yazmaz.

Karşılığı ölçülebilir: `tests/test_api_contracts.py` 126 testin tamamını
site/bench/DB olmadan, 0,6 saniyede koşar.
`KatmanDisiplinTesti::test_modul_duzeyinde_frappe_importu_yok` bu kuralı `ast`
ile doğrular — yorumda kalmış bir niyet değil, kilitli bir kısıttır.

### 3.2 Bağlama katmanı nereye yazılır

**Bu depoda henüz YAZILMADI ve bilinçli olarak yazılmadı.** Bağlama dosyasının
yeri `tradehub_core/tradehub_core/api/` altıdır; orası çalışan üretim
uygulamasıdır ve Faz 8 kapsamında oraya yazma yapılmadı. Aşağıdaki desen o
dosyanın ne olacağını tam olarak tarif eder.

```python
# tradehub_core/tradehub_core/api/media_v1.py   (HENÜZ YOK — bu desen)
"""media_engine uç noktalarının Frappe bağlaması. İŞ MANTIĞI YOKTUR."""

import frappe

from media_engine.api import envelope as env
from media_engine.api.upload import UploadApi
from tradehub_core.media import audit, chunked


def _principal() -> env.Principal:
	"""Frappe oturumu → `Principal`. Kapsam DB'den okunur, istekten DEĞİL."""
	return env.Principal(
		user=frappe.session.user,
		roles=tuple(frappe.get_roles()),
		store=frappe.db.get_value(
			"Admin Seller Profile", {"user": frappe.session.user}, "name"
		) or "",
	)


def _denied(principal, roles, scope) -> None:
	"""Yetki reddini denetime yaz — `media_admin._only_for` ile aynı sözleşme."""
	audit.log_media_event(
		action=audit.ACTION_ACCESS_DENIED,
		allowed=False,
		reason=f"missing_role:{scope}",
		context={"required_roles": list(roles)},
	)


def _emit(response: env.ApiResponse):
	"""`ApiResponse` → Frappe yanıtı. Tek çeviri noktası."""
	frappe.local.response["http_status_code"] = response.status
	for ad, deger in response.headers.items():
		frappe.local.response.setdefault("headers", {})[ad] = deger
	if response.body is None:
		return None
	if not response.ok:
		# Bugünkü istemci `upload_error` okuyor; iki ad arasındaki köprü
		# BU KATMANIN işidir, sözleşme tek kodu taşır.
		frappe.local.response["upload_error"] = response.body["error_code"]
	return response.body


def _api() -> UploadApi:
	return UploadApi(
		sessions=chunked,          # PROTOKOLÜ ZATEN KARŞILIYOR — adaptör yok
		assets=MediaAssetRepository(),
		blobs=None,                 # File kaydını `seller_media` açıyor
		notes=frappe.cache(),       # oturum künyesi; TTL = chunked.SESSION_TTL_HOURS
		on_denied=_denied,
	)


@frappe.whitelist(methods=["POST"])
def create_upload_session(slot_key: str, file_name: str, total_bytes: int,
						  content_sha256: str = "") -> dict:
	return _emit(env.call(
		_api().create_session, _principal(),
		slot_key=slot_key, file_name=file_name,
		total_bytes=total_bytes, content_sha256=content_sha256,
	))
```

Bağlamanın **tek** işi budur ve dördü de zorunludur:

1. `frappe.session` + `frappe.get_roles()` → `Principal`,
2. `env.call(...)` ile çağırıp istisnayı yanıta çevirmek,
3. `ApiResponse.status` / `headers` / `body`'yi Frappe yanıtına basmak,
4. `on_denied` kancasıyla yetki reddini `audit`e yazmak.

İş mantığı bu dosyaya **girmez** — `media_admin.py`'nin modül başlığındaki
kural (*"Bu dosyada görsel işleme kodu YOKTUR"*) burada da geçerlidir.

### 3.3 URL eşlemesi

Frappe `/api/method/<noktalı.yol>` üretir. OpenAPI'deki mantıksal yollar şöyle
eşlenir:

| OpenAPI yolu | Frappe çağrısı |
|---|---|
| `POST /api/media/v1/upload/sessions` | `/api/method/tradehub_core.api.media_v1.create_upload_session` |
| `GET /api/media/v1/delivery/{asset}/manifest` | `/api/method/tradehub_core.api.media_v1.get_manifest?asset=…` |
| `GET /api/media/v1/admin/slot-policies` | `/api/method/tradehub_core.api.media_v1.list_slot_policies` |

Her operasyonun `x-python` niteliği hangi Python fonksiyonunu sardığını söyler;
bağlama fonksiyon adları o eşlemeyi izlemelidir. Gerçek REST yolları
(`/api/media/v1/...`) ancak nginx'te bir yeniden yazma kuralıyla mümkündür ve
**bu fazda yapılmadı**.

### 3.4 Sarılan mevcut kod — yeniden yazılmadı

| Mevcut | Sarıldığı yer |
|---|---|
| `tradehub_core/media/chunked.py` — parçalı yükleme | `api/upload.py` (protokolü doğrudan karşılıyor, adaptör yok) |
| `tradehub_core/api/media_access.py` — imzalı private erişim | `delivery/signed.py::FrappeSignedUrl` |
| `tradehub_core/api/media_admin.py` — 39 yönetim ucu | `api/admin.py` **yalnız eksik 9 ucu ekler**, hiçbirini tekrarlamaz |
| `tradehub_core/media/pipeline/core/crop.py` — kırpma öncelik zinciri | `api/crop.py` |
| `tradehub_core/media/pipeline/image/render.py` — türev merdiveni | `delivery/manifest.py` |

---

## 4. SDK üretimi

SDK'lar **üretilmiş çıktıdır ve depoya girmez**; `.gitignore`'a alınmalıdır.
Elle düzeltilmiş bir SDK, sözleşmenin ikinci bir kopyası olur ve sessizce
ayrışır.

### 4.1 Storefront (Vite + Alpine, TypeScript 5.9) — tip üretimi

`openapi-typescript` yalnız **tip** üretir, çalışma zamanı kodu üretmez. Bu
tercih bilinçli: storefront'un kendi `fetch` sarmalayıcısı var
(`src/utils/api.ts`) ve ikinci bir HTTP istemcisi paket boyutuna eklenirdi.

```bash
cd tradehubfront
npx openapi-typescript ../tradehub_core/docs/api/openapi.yaml \
    -o src/types/media-api.d.ts
```

```ts
import type { components } from "@/types/media-api";

type Manifest = components["schemas"]["Manifest"];

// Manifest DOĞRUDAN <img> özniteliklerine karşılık gelir — çeviri katmanı yok.
const el = document.createElement("img");
el.src = m.src;
el.width = m.width;          // 0 ise ORAN BİLİNMİYOR: sabit ölçü kullan (FR-066)
el.height = m.height;
el.loading = m.loading;
el.decoding = m.decoding;
if (m.sources[0]) el.srcset = m.sources[0].srcset;
if (m.sizes) el.sizes = m.sizes;   // BOŞ ise yazma — yanlış `sizes` boştan kötüdür
```

### 4.2 Admin panel (Vue 3 + Pinia) — istemci üretimi

```bash
cd admin-panel/frontend
npx @openapitools/openapi-generator-cli generate \
    -i ../../tradehub_core/docs/api/openapi.yaml \
    -g typescript-fetch \
    -o src/api/media \
    --additional-properties=supportsES6=true,withInterfaces=true,typescriptThreePlus=true
```

### 4.3 Python istemcisi (entegrasyon testleri, betikler)

```bash
docker exec istoc-dev-backend-1 bash -lc \
  'cd /home/frappe && npx @openapitools/openapi-generator-cli generate \
   -i /home/frappe/olcum/faz8/openapi.yaml -g python -o /home/frappe/olcum/faz8/sdk-python'
```

### 4.4 Üretim öncesi kontrol listesi

1. `spec.py` değişti mi → `spec.write_yaml()` çalıştır.
2. `python3 -m unittest tests.test_api_contracts` — **yeşil olmadan SDK üretme.**
3. `API_VERSION`'ı §2 kurallarına göre artır.
4. SDK'yı üret, çıktıyı **elle düzeltme**; düzeltme gerekiyorsa `spec.py`'yi düzelt.

> **Sürüm uyarısı.** `openapi-generator` ve `openapi-typescript` sürümleri bu
> belgede SABİTLENMEDİ (ÖLÇÜLMEDİ: ikisi de bu depoda kurulu değil, `npx` ile
> çekilecek). OpenAPI **3.1** desteği sürüme bağlıdır: `openapi-generator` 7.x
> ve `openapi-typescript` 7.x 3.1'i destekler, daha eskileri `3.0`a düşürür ve
> `type: ["string", "null"]` ifadelerini sessizce kaybeder. Üretmeden önce
> sürümü doğrulayın.

---

## 5. İstemci sözleşmesi — dört kural

### 5.1 Karar METNE değil KODA bakar (FR-060)

```ts
if (!res.ok) {
  const err = await res.json();          // { error_code, retryable, message, details }
  if (err.retryable) return retryWithBackoff();
  showToUser(err.message);               // metin ZATEN Türkçe ve NEDEN+NASIL içerir
  track(err.error_code);                 // ölçüm koda göre yapılır
}
```

`error_code` iki biçimdedir:

* `media_<sebep>` — slot bağlamı olmayan hatalar (`media_not_found`, `media_unauthorized`).
* `<slot_prefix>_<sebep>` — politika ihlalleri. Önek slotun
  `on_violation.error_code_prefix` alanından gelir:
  `product_image_short_edge_too_small`. **Kod listesini istemcide sabitlemeyin**
  — yeni slot yeni önek demektir; bilinmeyen kodda `retryable` bayrağına düşün.

Tam katalog `openapi.yaml` içinde `x-error-codes` altındadır.

### 5.2 ETag kullanın

`GET` uçlarının hepsi `ETag` döndürür. `If-None-Match` gönderen istemci
değişmemiş gövdeyi tekrar indirmez (304). Manifest gövdeleri saf
fonksiyonların çıktısıdır; ETag içerik-adreslidir ve anahtar sırasından
etkilenmez.

### 5.3 `sizes` boşsa YAZMAYIN

`sizes` alanı bugün **boş gelir** ve bu bir eksiklik bildirimidir
(`sizes_source: "unmeasured"`), bir varsayılan değil. Gerekçe ölçülmüştür:
`docs/reports/03-render-envanteri.md` §3.1 — CSS kutu genişliği viewport ile
**monoton artmıyor** (640px'te 296px, 768px'te 147px'e düşüyor), dolayısıyla
`sizes` basit bir `(min-width: …) Xvw` zinciriyle ifade edilemez. Kırılım
başına ayrı sabit değer gerekir ve o tablo **BU FAZDA TÜRETİLMEDİ**.

İstemci kendi ölçtüğü `sizes`i parametre olarak gönderebilir; yanıt bunu
`sizes_source: "caller"` ile bildirir.

### 5.4 `width`/`height` 0 ise oran BİLİNMİYOR

Sabit ölçü kullanın, sayı uydurmayın (FR-066). Canlı ölçümde
`th_media_width` dolu olan kayıt sayısı **2853'te 0**; bu alanın boş gelmesi
bugün istisna değil, kuraldır.

---

## 6. Bu fazda ÖLÇÜLMEYEN / YAPILMAYAN

Dürüstlük listesi — hiçbiri "tamamlandı" sayılmamalıdır:

| Konu | Durum |
|---|---|
| `sizes` tablosu (slot × render bağlamı) | **ÖLÇÜLMEDİ.** `SIZES_TABLE` boş; enjekte edilebilir. |
| Odak önerisi güven eşiği | **KALİBRE EDİLMEDİ.** `SMARTCROP_CONFIDENCE_THRESHOLD = 0.5` kaynağında da "ÖLÇÜLMEDİ" yazıyor; yanıt `threshold_calibrated: false` taşır. |
| JSON-Schema doğrulaması | **YAPILAMADI.** `jsonschema` ne yerelde ne bench'te kurulu (ÖLÇÜLDÜ). `validate_policies` yapısal kontrol yapar ve `schema_validated: false` döndürür. |
| Frappe bağlama dosyası | **YAZILMADI.** Yeri `tradehub_core/tradehub_core/api/`; §3.2'de tam desen var. |
| REST yolları (`/api/media/v1/...`) | **YOK.** Bugün yalnız `/api/method/...` mümkün; nginx yeniden yazma kuralı gerekir. |
| Storefront / admin panel istemci kodu | **YAZILMADI.** İki depo da SALT OKUNUR. |
| SDK üretici sürümleri | **SABİTLENMEDİ.** Kurulu değiller; §4.4 uyarısına bakın. |
| Politika dosyalarındaki `en` mesajları | **EKSİK.** `validate_policies` 9 slotun 7'sinde `message_parity` bulgusu üretiyor; İngilizce arayüzde kullanıcı ham kod görür. |
| Profil genişlik sırası | 2 slotta artan değil (`company.cover_image`, `company.cover_video`) — `profiles_unsorted` bulgusu. |

---

## 7. İlgili belgeler

| Belge | İçerik |
|---|---|
| `tradehub_core/media/pipeline/api/spec.py` | Sözleşmenin kaynağı |
| `tests/test_api_contracts.py` | 126 test — sapma kilidi + davranış kanıtı |
| `tradehub_core/media/pipeline/contracts/errors.py` | Kodlu ret hiyerarşisi (FR-060, FR-061) |
| `tradehub_core/media/pipeline/contracts/delivery.py` | `DeliveryManifest` sözleşmesi |
| `docs/reports/00-upload-slot-envanteri.md` | Slot kimliği boşluğu (§7-B B1) |
| `docs/reports/03-render-envanteri.md` | CSS kutu ölçümleri, `sizes` sorunu (§3.1) |
| `docs/reports/08-canli-olcum.md` | 13,14 MB / 900 KB, srcset = 0 |
| `docs/srs/SRS-v1.0.md` | FR/NFR numaralarının kaynağı |
