# 32 — Faz 8 (API katmanı) kapanış denetimi

**Tarih:** 2026-08-19 · **Dal:** `ahmet` · **Site:** `istoc.localhost` (docker compose)
**Kapsam:** T-080…T-085 · `docs/reports/14-nihai-denetim.md:228`'in *"⚠ çalışır değil"* işaretinin kaldırılıp kaldırılamayacağı.

---

## 0. Karar — TEK CÜMLE

**Faz 8 sözleşme tarafında KAPANIYOR, tümüyle değil.**

Gerçek HTTP yüzeyi artık **belgeli, koda kilitli ve ölçülmüş** durumda: 87 whitelist ucu
belgelendi, 10'u gerçek HTTP çağrısıyla doğrulandı, 25 yeni sözleşme testi canlı sunucuya karşı
yeşil. Ama **2 uç ölçüldüğünde belgelenen gövdeyi ÜRETEMEDİ** (HTTP 500) ve bu bir belge hatası
değil, bir kurulum hatasıdır (§5). Faz 8 "API sözleşmesi" başlığı altında kapanır; "medya
depolama ayarı ekranı çalışıyor" iddiası kapanmaz.

| Faz 8 alt iddiası | Önceki | Bugün | Kanıt |
|---|---|---|---|
| Sözleşme belgesi var | ✅ | ✅ | `docs/api/openapi.yaml` (2.461 satır, 19 yol / 21 op) |
| Uçlar `@frappe.whitelist()` taşıyor | ❌ | ✅ | 87 uç, `x-source` ile dosya:satır (§2) |
| Belge gerçek HTTP yüzeyini anlatıyor | ❌ | ✅ | `docs/api/openapi-http.yaml` (4.703 satır, 87 yol) |
| Sözleşme ölçülerek doğrulandı | ❌ | ✅ (kısmi) | 10 uç canlı HTTP, §4 |
| `test_api_contracts` koşuyor | ❌ (düşüyordu) | ✅ | 126 test, bench'te **0 atlama** (§6) |
| Belgelenen her uç gerçekten yanıt veriyor | — | ⚠ **85/87** | 2 uç HTTP 500 (§5) |

---

## 1. Kök bulgu — iki AYRI katman vardı, belge yalnız birini anlatıyordu

`docs/api/openapi.yaml` `tradehub_core/media/pipeline/api/spec.py` tarafından **üretilir** ve
`UploadApi` / `CropApi` / `DeliveryApi` / `AdminApi` sınıflarını anlatır. Bu katman hakkında
üç şey ölçüldü:

1. **Whitelist taşımıyor.** `pipeline/api/*.py` altındaki hiçbir fonksiyonda `@frappe.whitelist()`
   yok — `ast` ile tarandı, test olarak kilitlendi
   (`KatmanAyrimiTesti::test_kutuphane_katmani_whitelist_TASIMAZ`). `pipeline/api/crop.py:219`
   başlığı zaten bunu açıkça söylüyor.
2. **Belgedeki yollara istek atılamaz.** `/api/media/v1/...` dizgisi depoda `pipeline/api/` ve
   `docs/api/` dışında **hiç geçmiyor**: ne `hooks.py`'de `website_route_rules`, ne nginx
   konfigürasyonunda bir yeniden yazma kuralı var. Ölçüldü ve teste bağlandı
   (`test_media_v1_onekinin_yonlendirmesi_YOK`).
3. `docs/api/README.md` §3.2 bunu zaten kabul ediyor: *"Bağlama katmanı bu depoda henüz
   YAZILMADI"*. **Bu cümle bugün eskimiştir** — `tradehub_core/api/media_manifest.py` tam olarak
   o bağlama katmanıdır (README bu görevin dokunma listesinde olduğu için düzeltilmedi; devir
   notu §8).

Yani `14-nihai-denetim.md`'nin *"hiçbir uç `@frappe.whitelist()` taşımıyor"* tespiti belgelenen
katman için **hâlâ doğru**. Değişen şey, artık belgelenmemiş bir ikinci katmanın var olması.

### Neden `openapi.yaml` değiştirilmedi

Dosyanın ilk satırı: *"ÜRETİLMİŞ DOSYA — ELLE DÜZENLEMEYİN"*. Diskteki içerik ile
`spec.build_document()` çıktısı arasında **bayt eşitliği** testi var
(`test_api_contracts.py::YamlSapmaTesti::test_bayt_esitligi`). Elle bir satır eklemek o testi
düşürürdü; gerçek kaynağı (`media/pipeline/api/spec.py`) düzenlemek ise bu görevin
**dokunma listesindeki** `media/` altındadır.

Ayrıca birleştirmek **yanlış** olurdu: tek belgede iki katmanı toplamak, çağrılamayan
`/api/media/v1/...` yollarına çağrılabilir görüntüsü verirdi. Görev tanımı da bu ayrımın
korunmasını istiyordu.

**Karar:** `openapi.yaml` olduğu gibi bırakıldı (zaten güncel — bayt eşitliği testi geçiyor) ve
gerçek yüzey için **kardeş bir belge** üretildi.

```
docs/api/openapi.yaml        → kütüphane sözleşmesi · whitelist YOK · yol YOK   · 21 op
docs/api/openapi-http.yaml   → gerçek HTTP yüzeyi   · /api/method/… · ÖLÇÜLDÜ  · 87 uç
```

İki belgenin yol kümelerinin **kesişmediği** test olarak kilitlendi
(`test_yol_kumeleri_kesismez`).

---

## 2. Gerçek uç envanteri — 87 uç, KODDAN çıkarıldı

`scripts/gen_http_openapi.py` kaynak dosyaları `ast` ile ayrıştırır — `import frappe` YOKTUR,
site/bench gerektirmez. İmza, `allow_guest`, `methods`, ek süsleyiciler (`@rate_limit`) ve
gövdedeki yetki kapısı çağrıları **dosyadan** okunur; elle yazılmış bir tabloya güvenilmez.

| Modül | Uç | Etiket |
|---|---:|---|
| `tradehub_core/api/media_manifest.py` | 3 | delivery |
| `tradehub_core/api/media_access.py` | 2 | delivery |
| `tradehub_core/api/seller_media.py` | 33 | seller |
| `tradehub_core/api/media_admin.py` | 47 | admin |
| `…/doctype/media_storage_settings/media_storage_settings.py` | 2 | storage |
| **Toplam** | **87** | |

### Misafire açık olan TAM üç uç

`allow_guest=True` taşıyan uçlar belgede `x-guest-endpoints` altında **liste hâlinde** durur ve
test bu listeyi koda karşı doğrular (`test_misafir_listesi_kodla_uyusuyor`). Listeye bir uç
eklenirse test düşer — sessiz genişleme mümkün değil.

| Uç | Neden misafire açık |
|---|---|
| `media_manifest.get_manifest` | Her ürün sayfasında çağrılıyor; vitrin oturumsuz |
| `media_manifest.get_manifest_batch` | Listeleme sayfası; `@rate_limit(600/60s)` var |
| `media_access.download` | İmzalı link zaten oturumsuz erişim için var; imza + `exp` + `blob` doğrulanır |

### Yetki kapıları (koddan çıkarıldı, `x-authorization` alanında)

| Kapı | Nerede | Sözleşme cümlesi |
|---|---|---|
| `_store()` → `ownership.current_store()` | `seller_media.py` (33 uç) | Mağaza oturumdan; `store` parametresi YOK ve eklenmeyecek |
| `_guard()` → `frappe.only_for` | `media_admin.py` | `System Manager` \| `Marketplace Admin` |
| `_guard_destructive()` | `media_admin.py` (yıkıcı) | Yalnız `System Manager` |
| `_require_superadmin(ptype)` | `media_storage_settings.py` | `Media Superadmin` \| `System Manager` **+** DocType izni |
| `File.has_permission("read")` + `blob_matches_row` | `media_access.get_signed_url` | Yetkisiz için imza ÜRETİLMEZ |
| `verify_request()` + `exp` + `_blob_binding_ok` | `media_access.download` | İmza, süre ve içerik bağı |

---

## 3. Belge ↔ kod kilidi

`tradehub_core/tests/test_http_api_contracts.py` (25 test) üç katman doğrular:

1. **Bayt eşitliği** — `docs/api/openapi-http.yaml` üreticinin çıktısıyla birebir aynı olmalı.
   Elle düzenleme ya da eskime testi düşürür.
2. **İki yönlü kapsam** — kodda olup belgede olmayan da, belgede olup kodda olmayan da düşürür.
   `x-source` (dosya:satır) gerçekten çözülür.
3. **Katman ayrımı** — iki belgenin yolları kesişmez; HTTP belgesindeki her yol `/api/method/`
   ile başlar; `pipeline/api/` altına whitelist sızarsa test düşer.

Ek olarak `ANLATIM` sözlüğündeki (elle yazılan açıklamalar/şemalar) her anahtarın kodda
karşılığı olması zorunludur — hayalet anahtar üreticiyi düşürür.

---

## 4. ÖLÇÜM — gerçek HTTP çağrıları

> Ortam: `istoc-dev-backend-1`, uygulama **imaja gömülü** (bind-mount yok). Ölçümden önce
> imajdaki `media_manifest.py` / `media_access.py` / `seller_media.py` dosyalarının çalışma
> ağacıyla **birebir aynı** olduğu `diff` ile doğrulandı. `Media Engine Settings` bayrakları
> **0** (T-124 sonrası varsayılan) — sözleşme bu hâliyle belgelendi.

### 4.1 Misafir (oturumsuz)

| # | Çağrı | Sonuç | Not |
|---|---|---|---|
| G1 | `get_manifest?listing=LST-00560` | **200**, 908 B | `enabled=false`, 7 görsel, `fallback=/files/191-ff0258.jpg`, ETag var |
| G2 | aynı + `if_none_match=<etag>` | **200**, 133 B | `{not_modified:true, etag, cache_control}` — **304 DEĞİL** |
| G2b | aynı, `If-None-Match` **başlığı** ile | 200, aynı gövde | İki yol da çalışıyor |
| G3 | `get_manifest?listing=LST-YOK-9999` | **200** | Boş manifest; "yok" ile "yayında değil" ayırt EDİLMİYOR |
| G4 | `get_manifest_batch?listings=["LST-00560","LST-YOK-9999"]` | **200** | `requested=2 returned=1 missing=[] truncated=false max_batch=50` |
| G5 | `get_manifest_batch?listings=LST-00560,LST-00561` | **200** | Virgüllü biçim de kabul; `returned=2` |
| G6 | `media_manifest.get_signed_url` | **403** | `PermissionError` |
| G7 | `media_access.get_signed_url` | **403** | `PermissionError` |
| G8 | `media_access.download` (imzasız) | **403** | HTML `Geçersiz Bağlantı` sayfası |
| G9 | `seller_media.browse_my_media` | **403** | |
| G10 | `media_admin.get_image_inventory` | **403** | |
| G11 | `media_storage_settings.get_storage_status` | **403** | |

**Bayrak kapalıyken sözleşme:** uç 500 atmıyor, `enabled=false` + `fallback` ile bugünkü
`<img src>` davranışını koruyor. Belgede `Manifest` şeması bu hâli anlatıyor.

### 4.2 Yetkili (Administrator) + imzalı indirme zinciri

| # | Çağrı | Sonuç |
|---|---|---|
| A1 | `media_access.get_signed_url(file_url=<private xlsx>)` | **200** — `{url, exp, ttl_seconds:900}`; `url` içinde `blob=` ve `_signature=` |
| A2 | `media_manifest.get_signed_url(aynı)` | **200** — aynı + `cache_control: private, no-store` |
| **A3** | **A1'in ürettiği adres, OTURUMSUZ** | **200, 634.926 B**, `application/vnd.openxmlformats-…sheet` |
| A4 | aynı adres, `_signature` son karakteri bozuldu | **403** |
| A5 | aynı adres, `blob=` bozuldu | **403** |
| A6 | aynı adres, `exp` geçmişe çekildi | **403** |
| A9 | `media_admin.get_image_inventory?page_size=2` | **200** — `{items:[…]}` |
| A10 | `seller_media.browse_my_media` (Administrator = mağazasız) | **403** — *"Bu işlem için bir mağaza hesabı gerekiyor."* |

A3–A6 birlikte, T-052'de eklenen **blob bağlamasının** gerçekten uçtan uca çalıştığını gösterir:
imza içeriğe bağlı ve üç ayrı kurcalama denemesinin üçü de reddedildi.

### 4.3 Satıcı oturumu (`ali.bal@turksab.com` → `SEL-00003`)

Oturum, Frappe'nin kendi `frappe.core.doctype.user.user.impersonate` ucuyla açıldı
(Administrator gerektirir, `Activity Log` + `Notification Log` izi bırakır). **Hiçbir parola
değiştirilmedi.**

| # | Çağrı | Sonuç |
|---|---|---|
| S1 | `browse_my_media` (kök) | **200** — `{folders:[{public,7},{private,11},{chat,0}]}` |
| S2 | `scope=public` | **200** — 3 klasör (`Bere`/3, `__none__`/2, `__unused__`/2) |
| S3 | `scope=private` | **200** — 11 dosya, `pii` bayrağı dolu |
| S4 | `scope=chat` | **200** — `{items:[],total:0}` |
| S5 | `scope=public&category=__unused__` | **200** — 2 dosya |
| S6 | `scope=bogus` | **417** `ValidationError` — *"Geçersiz kapsam: bogus"* |
| **S7** | `scope=public&category=x&listing=LST-00560` (**başka mağazanın ilanı**) | **200** — `{items:[],total:0}` — sızıntı YOK, hata da yok (keşif engellendi) |
| S8 | `get_my_summary` | **200** — `{store:"SEL-00003", active:6, trashed:0, bytes:20466224, quota_bytes:null, tags:[]}` |
| S9 | `get_my_media?page_size=2` | **200** — `{items:[…]}` |
| S10 | `upload_limits` | **200** — 22 izinli / 15 medya / 13 reddedilen uzantı |
| S11 | `media_admin.get_image_inventory` | **403** — rol kapısı |
| S12 | `media_storage_settings.get_storage_status` | **403** — *"yalnızca Media Superadmin rolüne açıktır"* |

S7, `browse_my_media` docstring'indeki en sert cümlenin ("yok ile senin değil ayrımı yapılmaz")
gerçekten uygulandığını **ölçerek** gösteriyor.

### 4.4 Sözleşmede DÜZELTİLEN sapmalar

Ölçüm, ilk taslakta yanlış yazacağım üç şeyi düzeltti — belgeye **ölçülen** hâli girdi:

1. **`if_none_match` 304 döndürmüyor.** Whitelist katmanı HTTP durumunu değiştirmiyor; 200 +
   `{not_modified:true}` dönüyor. `pipeline/api/envelope.py`nin `conditional_get`'i 304 üretir —
   **iki katman burada farklı davranıyor** ve belgede ayrı ayrı yazılı.
2. **Frappe `ValidationError`'ı 417 ile döndürüyor**, 400 ile değil (S6). Belgedeki
   `components/responses/Validation` bunu söylüyor.
3. **Hata zarfı farklı.** Whitelist katmanı `{exception, exc_type, exc}` döndürüyor;
   `pipeline/api/envelope.py`nin `{error_code, retryable}` zarfı **bu katmanda kullanılmıyor**.
   Belgede `x-frappe-envelope` bunu açıkça yazıyor. İstemci tarafında tek bir hata ayrıştırıcı
   yazmak isteyen biri bu farkı bilmeden yanlış kod yazardı.

---

## 5. UYUŞMAYAN — `Media Storage Settings` uçları HTTP 500

Belgede `x-mismatched-endpoints` altında **işaretli**, "geçti" DENMEDİ.

```
GET /api/method/…media_storage_settings.get_storage_status   (Administrator)
→ HTTP 500
   ImportError: Module import failed for Media Storage Settings,
   the DocType you're trying to open might be deleted.
   No module named 'frappe.core.doctype.media_storage_settings'
```

`test_connection?target=cdn` de aynı hatayı veriyor.

### Kök neden (ölçüldü)

| Ölçüm | Sonuç |
|---|---|
| `tabDocType` satırı `Media Storage Settings` | **YOK** (`None`) |
| `tabSingles` satırı (aynı doctype) | **29 satır VAR** |
| `Role` `Media Superadmin` | VAR |
| `Patch Log` `…v15_9_25_media_storage_settings` | **"koşmuş" işaretli** |
| İmajda `doctype/media_storage_settings/*.json` | VAR |
| `tabDocType`'taki diğer medya doctype'ları | `Media Asset`, `Media Engine Settings`, `Media Processing Job`, `Media Profile`, `Media Rendition` — **beşi de var** |

Yani yama gövdesi **çalıştı** (rolü yarattı, 29 Singles değeri yazdı) ama içindeki
`frappe.reload_doc("tradehub_core", "doctype", "media_storage_settings")` DocType'ı DB'ye
kaydetmedi ve yama yine de "başarılı" olarak işaretlendi. DocType satırı olmayınca Frappe
controller'ı `frappe.core.doctype.…` altında arıyor ve `ImportError` fırlıyor.

**Sonuç:** ayar verisi tabloda duruyor, ekranı besleyecek iki uç ise erişilemez durumda.
Rol kapısı çalışıyor (S12 → 403); kırılan şey kapının **arkası**.

### Neden bu raporda düzeltilmedi

`patches.txt`, DocType JSON'ları ve `bench migrate` bu görevin **dokunma listesinde**; ayrıca
paralel bir ajan `patches.txt` üzerinde çalışıyor. Bulgu ölçülüp belgelendi, düzeltme devredildi
(§8).

---

## 6. `test_api_contracts` — düşüyor muydu, koşuyor mu

**Koşuyor.** `docs/reports/21-t030-mimari-inceleme.md`'nin tespit ettiği kök neden
(`docs/api/openapi.yaml` üretilmemişti) giderilmiş; dosya bugün üreticiyle **bayt bayt aynı**.

| Ortam | Sonuç |
|---|---|
| Yerel (macOS, Python 3.9.6, PyYAML yok) | `Ran 126 tests … OK (skipped=1)` |
| Bench konteyneri (Python 3.11, PyYAML 6.0.3) | `Ran 126 tests … **OK**` — **0 atlama** |

Tek atlanan test yerelde PyYAML olmadığı için atlanan `test_gercek_yaml_ayristiricisiyla_tur_atlar`;
bench'te o da koşuyor ve geçiyor. Yani sözleşme belgesi **bağımsız bir YAML ayrıştırıcıyla** da
doğrulandı.

### Yeni test dosyası

| Ortam | Sonuç |
|---|---|
| Yerel, `ISTOC_HTTP_BASE` yok | `Ran 25 tests … OK (skipped=7)` — canlı testler **atlandı**, sahte "geçti" üretilmedi |
| Yerel, `ISTOC_HTTP_BASE=http://istoc.localhost:8001` | `Ran 25 tests … **OK**` |
| Bench konteyneri, `ISTOC_HTTP_BASE=http://backend:8000 ISTOC_HTTP_HOST=istoc.localhost` | `Ran 25 tests … **OK**` — 0 atlama |

`python3 -m ruff check` iki yeni dosyada da temiz.

---

## 7. Sahtelere karşı ne yapıldı

Görev notu üç sahte kaynaklı yanlış güven örneği sayıyordu (sahte S3 presign, `PolicyEngine`
protokolü, sentetik video fixture'ları). Bu görevde alınan önlemler:

- **Canlı testler sahte istemci KULLANMIYOR.** `urllib` ile gerçek sunucuya gidiyor.
  `ISTOC_HTTP_BASE` verilmezse test **atlanıyor** — sahte bir yanıtla "geçti" üretmiyor.
- **Şemalar ölçülen gövdelerden yazıldı**, docstring'lerden değil. `Manifest`,
  `ManifestBatch`, `NotModified`, `SignedUrl`, `BrowseLevel`, `SellerSummary` alanları §4'teki
  gerçek yanıtlardan çıkarıldı.
- **Envanter `ast` ile koddan** çıkarılıyor; elle yazılan `ANLATIM` sözlüğündeki her anahtarın
  kodda karşılığı zorunlu.
- **Uyuşmayan iki uç "uyuşmuyor" diye işaretlendi** (`x-measured: http-fail` + `x-mismatch`),
  belgeden gizlenmedi.
- Ölçüm ortamının **imajdaki kodla aynı** olduğu `diff` ile doğrulandı — yerelde düzeltip
  konteynerde ölçmek gibi bir yanılgı yok.

### Bu raporun ölçMEDİĞİ şeyler

- 87 ucun **77'si** yalnız koddan belgelendi; HTTP ile denenmedi. Belgede `x-measured` alanı
  YOK ise uç ölçülmemiştir — sessizce "geçti" sayılmasın.
- `@rate_limit(600/60s)` kovası tetiklenmedi (600 istek atmak gerekiyordu).
- Bayraklar **AÇIKKEN** manifest gövdesi bu raporda ölçülmedi; T-124 ölçümü
  `DALGA-A-DEVIR.md`'de (7 görsel, `srcset` adresi 200 / 20.376 B / `image/avif`).
- POST-only uçların (`methods=["POST"]`) GET ile reddedildiği doğrulanmadı.
- Yazan uçların (`archive_media`, `purge_media`, `trash_files`, …) hiçbiri çağrılmadı —
  ölçüm veri bozmamalıydı.

---

## 8. Devir — Faz 8'i tümüyle kapatmak için kalan

| # | İş | Sahibi | Neden burada yapılmadı |
|---|---|---|---|
| 1 | `Media Storage Settings` DocType'ını DB'ye kaydet (`bench migrate` / yamayı idempotent düzelt), sonra §5'teki iki ucu yeniden ölç | patches sahibi | `patches.txt` + DocType JSON dokunma listesinde; paralel ajan çalışıyor |
| 2 | `docs/api/README.md` §3.2'yi düzelt — *"bağlama katmanı yazılmadı"* artık yanlış; `api/media_manifest.py` o katman | belge sahibi | README dokunma listesi dışındaydı |
| 3 | `openapi.yaml`'ın `info.description`'ına kardeş belgeye işaret ekle (kaynak: `media/pipeline/api/spec.py`) | `media/` sahibi | `media/` dokunma listesinde |
| 4 | Kalan 77 ucu ölç ya da bilinçli olarak "ölçülmedi" kabul et | — | Kapsam |
| 5 | Yazan uçlar için ayrı, geri alınabilir bir ölçüm oturumu | — | Veri bozmamak için |

---

## 9. Üretilen / değiştirilen dosyalar

| Dosya | Durum | Not |
|---|---|---|
| `docs/api/openapi-http.yaml` | **YENİ** (4.703 satır) | Üretilmiş; elle düzenlenmez |
| `scripts/gen_http_openapi.py` | **YENİ** | `ast` tabanlı üretici + doğrulayıcı; `--check` sapma modu |
| `tradehub_core/tests/test_http_api_contracts.py` | **YENİ** (25 test) | Belge kilidi + katman ayrımı + canlı HTTP |
| `docs/reports/32-faz8-api-kapanis.md` | **YENİ** | Bu rapor |
| `docs/api/openapi.yaml` | **DEĞİŞMEDİ** | Zaten güncel (bayt eşitliği testi geçiyor); gerekçe §1 |

### Yeniden üretme

```bash
python3 scripts/gen_http_openapi.py            # üret
python3 scripts/gen_http_openapi.py --check    # sapma var mı (yazmaz)

python3 -m unittest tradehub_core.tests.test_http_api_contracts          # belge kilidi
ISTOC_HTTP_BASE=http://istoc.localhost:8001 \
  python3 -m unittest tradehub_core.tests.test_http_api_contracts        # + canlı sözleşme
```

---

## 10. KANIT VE KAPI DURUMU — 2026-08-19, D3 ölçümü

> **Bu bölüm `docs/reports/56-d3-faz6-10-kapanis.md` §5 tarafından eklendi.**
> Belgenin gövdesine, §0'daki karara ve §8'deki devir listesine **dokunulmadı**.
> Amacı tek: bu belgenin bıraktığı boşlukların bugünkü ölçülmüş durumunu tek yerde
> göstermek. **Bu belgenin bazı sayıları bugün itibarıyla BAYATTIR** ve aşağıda
> hangileri olduğu yazılıdır.

### 10.1 Bayat kalan sayılar — düzeltilmedi, işaretlendi

| Bu belgede yazan | Bugünkü ölçüm | Kaynak |
|---|---|---|
| 87 uç | **90 uç** (+3 kırpma ucu) | `openapi-http.yaml` `x-endpoint-count: 90` |
| *"87 ucun 77'si yalnız koddan belgelendi"* (§7) | **1** uç hiç çağrılmadı; 69'unun başarı gövdesi, 20'sinin ret yolu ölçüldü | `41-t080-api-sozlesme.md` §0 |
| `test_http_api_contracts` = 25 test | **41 test** | Bugün koşuldu (§10.2) |
| §5 — `Media Storage Settings` uçları **HTTP 500** | **HTTP 200** (rapor 41 §3). Kök neden — eksik `tabDocType` satırı — giderilmiş | `41-…` §3. **Bu oturumda yeniden çağrılmadı** |
| §7 — *"POST-only uçların GET ile reddedildiği doğrulanmadı"* | **Ölçüldü:** 405 değil **403 `PermissionError`** — yöntem hatası ile yetki reddi aynı kodu paylaşıyor (D6) | `41-…` §5.2 |
| §8 devir maddesi 1 (`Media Storage Settings` DocType'ı DB'ye kaydet) | ✅ **KAPANDI** | `41-…` §3 |
| §8 devir maddesi 4 (kalan 77 ucu ölç) | ✅ **KAPANDI** — 77 → 1 | `41-…` §2 |

### 10.2 Test kapısı — bugün koşuldu

```
# env yok
Ran 41 tests ... OK (skipped=16)            # canlı testler atlandı, sahte "geçti" üretilmedi

# ISTOC_HTTP_BASE=http://127.0.0.1:8000 ISTOC_HTTP_HOST=istoc.localhost
Ran 41 tests ... OK (skipped=6)             # kalan 6 atlama: ISTOC_HTTP_USER/PASS isteyen YetkiliCanliTesti

python3 scripts/gen_http_openapi.py --check
temiz                                        # belge ↔ kod sapması YOK
```

### 10.3 T-085'in KENDİ çıktıları — bugün ölçüldü, üçü de YOK

Bu belge Faz 8'i *"sözleşme tarafında kapanıyor, tümüyle değil"* diye
işaretlemişti. Sözleşme tarafı bugün gerçekten sağlam. Kapanmayan şey artık
**T-085'in kendi teslim kalemleridir**:

| Kriter | Durum | Ölçüm |
|---|---|---|
| **TS istemci SDK** üretilmiş ve frontend kullanıyor | ❌ **YOK** | `docs/api/` = 3 dosya. `admin-panel/frontend` ve `tradehubfront` `package.json`'larında `openapi-typescript` / `openapi-generator` **yok** |
| **Postman / Bruno** koleksiyonu | ❌ **YOK** | `*postman*`, `*bruno*`, `*.bru` → **0 dosya** |
| `spectral` lint (T-080'den devreden) | ❌ **YOK** | `.spectral*` yok, bağımlılıklarda yok |
| `schemathesis` / `dredd` fuzzing (T-084) | ❌ **YOK** | Repoda geçmiyor |

### 10.4 YENİ BULGU — dondurma politikası yanlış katmanı donduruyor

`docs/api/README.md` §2 gerçek ve iyi yazılmış bir sürüm dondurma politikası
taşıyor (MAJOR/MINOR/PATCH tanımları, RFC 8594 `Deprecation`/`Sunset` yordamı).
**Ama §2.5 "bugünün donmuş yüzeyi" = 21 uç** — yani bu belgenin §1'de
*"çağrılamaz"* diye ölçtüğü `/api/media/v1/…` kütüphane katmanı.

Bugün ölçüldü: `grep openapi-http docs/api/README.md` → **0 isabet.**
Gerçek HTTP yüzeyi (90 uç) README'de **hiç anılmıyor**; `openapi-http.yaml`'ın
kendi `info.version`'ı `1.0.0` ve dosyanın **dondurma/deprecation politikası yok**.

**Sonuç:** "OpenAPI v1 donduruldu" cümlesi bugünkü hâliyle yanıltıcıdır —
donmuş olan, istemcinin çağıramadığı katmandır.

### 10.5 §5'in kardeşi — T-082'nin `overrides` uyuşmazlığında kök nedenin yarısı kalkmış

`41-t080-api-sozlesme.md` §4, `save_intent`'in `overrides` yolunun çalışmadığını
ölçmüştü: `Media Crop Override.profile` bir **`Link → Media Profile`**'dı ve
`w384` gönderilince Frappe **417 `LinkValidationError`** atıyordu.

Bugün canlı DB'den ölçüldü:

```
tabDocField where parent='Media Crop Override'
  profile   fieldtype=Data   options=None      ← Link DEĞİL
```

Link kısıtı kalkmış; kütüphane tarafı (`pipeline/api/crop.py::_parse_overrides`)
zaten kısa adı (`w384`) bekliyordu.

> ⚠ **BU BİR HTTP ÖLÇÜMÜ DEĞİLDİR.** `save_intent` `overrides` ile gerçek bir
> istekle çağrılmadı (kayıt üretmemek için). Rapor 41 §4'ün uyuşmazlığı **bugün
> yeniden ölçülmedi**; ölçülen tek şey, sebeplerinden birinin şemada kalmadığıdır.
> Bu yol uçtan uca yeniden çağrılmalı ve
> `test_save_intent_uyusmazligi_belgede_DURUYOR` testi ya doğrulanmalı ya
> güncellenmelidir.

### 10.6 Kapanmayan yapısal madde

`41-…` §8-7: CI'da `ISTOC_HTTP_BASE` veren bir yapılandırma yok. Bugün ölçüldü —
`.github/workflows/` altındaki **5 dosyanın hiçbiri test koşmuyor**
(`run-tests|pytest|unittest` → 0 isabet). Yani `bench run-tests` CI'da hiç
koşmadığı için gerçek HTTP yüzeyi de hiç ölçülmüyor. Bu, `T-067/4` ile **aynı**
eksiğin ikinci yüzüdür ve tek bir workflow ikisini birlikte kapatır.

### 10.7 Karar

**Faz 8 bugün de KAPANMAZ** — ama sebep değişti. Bu belge yazıldığında sebep bir
**kurulum hatasıydı** (`Media Storage Settings` 500). O kapandı. Bugünkü sebep
**yapılmamış üç teslim kalemidir**: TS SDK, koleksiyon, lint. Ayrıntı ve devir
listesi `docs/reports/56-d3-faz6-10-kapanis.md` §5 ve §9'dadır.
