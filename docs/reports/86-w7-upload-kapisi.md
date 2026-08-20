# 86 · W7 — Yükleme yolunun iki ölçülmüş boşluğu: sunucu boyut kapısı + orijinal sha256

**Tarih:** 2026-08-20
**Kapsam:** (1) `upload_media` slot politikasının boyut/alan kurallarını artık
SUNUCUDA uyguluyor (rapor 78 W5-2: 900×900 PNG 200 alıyordu, istemci kapısı
atlatılabilir — panel E2E S1b `test.fail` ile görünür tutuyordu). (2)
Dönüştürülen (PNG/JPEG→WebP) yüklemelerde kaybolan ORİJİNAL baytların sha256'sı
artık saklanıyor ve tekilleştirme araması üçüncü katman olarak onu buluyor
(rapor 64 EK-2). İkisi de canlı HTTP ile ölçüldü.

---

## 1. İş 1 — Sunucu boyut kapısı (W5-2)

### Tasarım: kural kopyası YOK, kimlik taşındı

`product-image.json`un kendi notu sorunu adlandırıyordu: *"upload_policy.check()
imzasında slot parametresi yok, yani slot kimliği sunucuya hiç ulaşmıyor"*
(00-upload-slot-envanteri §7-B B1). Yapılan tam olarak o kimliği taşımak:

- `upload_media(file_name, content, slot="")` — istemci slot BEYAN eder
  (panel `MediaUploader.vue` zaten `slot=product.image` ile çalışıyor).
- `upload_policy.check_slot(slot, ad, içerik, role)` — YENİ, ama kural değil
  KÖPRÜ: kararı `pipeline/policy/engine.py::evaluate` verir (393 vektörle TS
  paritesi kanıtlı motor, rapor 77). `block` ihlali mevcut ret sözleşmesine
  çevrilir: HTTP 417 + `upload_error` kodu + mesaj sonunda `[kod]`
  (`UploadRejected`). Kod motorun kendi kodudur:
  `product_image_short_edge_too_small` gibi. **`warn`/`auto_fix` reddetmez**
  (`Decision.blocking()` yalnız reject/review).
- Künye Pillow'suz: `declared_dimensions()` (W5-C, yalnız İMPORT edildi) +
  `core/probe.sniff` + bayt sayısı. Ölçülemeyen alan `None`/0 → motor o
  kuralı `SkippedRule` sayar (entropi/bulanıklık gibi kalibre edilmemiş
  content_rules bu yüzden kendiliğinden devre dışı — draft politika hiçbir
  ölçülemeyen kuralla reddetmez).
- Sıra: `check()` (genel tür/boyut/içerik kapısı, T-017 dahil) → `check_slot`
  → dönüşüm. Politika ORİJİNAL içerik üstünde ölçer (TUR-128 ile aynı ilke).
- **Slot verilmemişse kapı hiç koşmaz** — genel kütüphane yüklemesi ve parçalı
  yol (`upload_finish`) bugünkü davranışında. Bilinmeyen slot beyanı ise
  SESSİZCE ATLANMAZ: `upload_slot_unknown` ile açık ret (bozuk beyanla kapıyı
  atlama kapısı kapalı).

| Dosya | Değişiklik |
|---|---|
| `tradehub_core/media/upload_policy.py` | `check_slot` + `_slot_probe` + süreç-başına `PolicyEngine` (`lru_cache`, `_slot_bindings` deseni); `SLOT_UNKNOWN` kodu `ALL_CODES`e eklendi |
| `tradehub_core/api/seller_media.py` | `upload_media`/`_kaydet` `slot` parametresi; denetim kaydına `slot` bağlamı |

### Bilinen sınır

`declared_dimensions` EXIF orientation okumaz; kısa kenar/alan rotasyondan
bağımsızdır, yalnız ORAN kuralı 90° döndürülmüş JPEG'de depolanan ölçüyle
değerlendirilir. Kabul edilen risk — görev W5-C'nin başlık okuyucusunu
kullanmayı şart koşuyor ve ikinci bir başlık ayrıştırıcısı yazılmadı.

### Canlı ölçüm (istoc.localhost, gerçek satıcı oturumu SEL-00003)

| İstek | Sonuç |
|---|---|
| 900×900 PNG + `slot=product.image` | **417**, `upload_error=product_image_short_edge_too_small`, `exc_type=UploadRejected` (daha önce 200'dü) |
| 900×900 PNG slot'suz | **200** — eski davranış korunuyor (dosya sonra purge edildi) |
| 1200×1200 PNG + `slot=product.image` | **200** (`master_under_spec` yalnız warn — reddetmedi) |

### Vacuity kanıtı (kapı kaldırılarak ölçüldü)

Konteyner kopyasında `_kaydet`teki `check_slot` çağrısı geçici yorumlandı →
`test_media_upload_slot_gate` **2 testle KIRMIZI** (900×900 ret + bilinmeyen
slot ret; `UploadRejected not raised`), slot'suz kabul testi yeşil kaldı —
reddi üreten tek şey kapı. Çağrı geri kondu, süit yeşile döndü; probe
koşusunun DB artıkları (1 File + draft varlıklar) elle temizlendi, `library.
upload` süzgeci canlıda boş doğrulandı.

---

## 2. İş 2 — Orijinal sha256 saklanıyor (64 EK-2)

### Nereye: `Media Asset.original_sha256` (custom field)

Şartnamede ham-yükleme künyesi VAR (`Media Source`, 41-faz4-veri-modeli;
yerel kopyası `media/pipeline/doctype_specs/media_source.json`) ama o DocType
bu app'te **bilinçli olarak kurulu değil** ve emsal karar aynı durumda alanı
kurulu bir pipeline DocType'ına taşımak olmuş (`_index.json`: `has_alpha` →
Media Version, "Media Source DocType'ı bu app'te KURULU DEĞİL"). Tek alan
için o kararı devirmedim; `tabFile` custom field'ı görev sınırıyla zaten
kapalı. Kurulu medya DocType'ları içinde (owner_seller, içerik, kaynak File)
üçlüsünü taşıyan tek kayıt `Media Asset`: kiracı kemeri ve `source_file` bağı
hazır, `state="draft"` tam "yüklendi ama işlenmedi" durumu için tanımlı.
`Media Version` olamazdı — `asset` zorunlu, işleme ANI kaydı; yükleme anında
var olamaz. Gerekçenin tam hâli `files.record_original_hash` docstring'inde.

| Dosya | Değişiklik |
|---|---|
| `tradehub_core/patches/v15_9_34_media_asset_original_sha256.py` | YENİ — custom field (Data 64, search_index; `unique` DEĞİL: aynı orijinal iki slota/satıcıya yüklenebilir, tekillik `asset_key` üçlüsünde). İdempotent, `v15_9_12` deseni |
| `tradehub_core/media/files.py` | `record_original_hash(doc, store, sha, slot)` — (owner_seller, slot_key, content_sha256) üçlüsüne upsert; slot'suz yüklemede `slot_key="library.upload"` (KASITLI `KNOWN_SLOT_KEYS` dışında — boru hattı süzgeçleri görmez); yarış `asset_key` unique + DuplicateEntry dalı (INV-06); kolon yoksa no-op |
| `tradehub_core/api/seller_media.py` | `_kaydet`: sha256 dönüşümden ÖNCE hesaplanır, yalnız baytlar gerçekten ayrıştıysa kayıt; best-effort (`log_error`, yükleme düşmez). `to_webp` düşerse kayıt YOK — orijinal olduğu gibi saklandı, katman 1 zaten bulur |
| `tradehub_core/media/inventory.py` | `find_by_sha256`e **katman 3** (`_find_by_original_hash`); katman 2'nin File yeniden-sorgusu `_kaynak_dosya_cevabi` yardımcısına çıkarıldı ve İKİ katman aynı hijyen kemerlerinden geçiyor (public, çöp dışı, hassas-ikiz maskesi). Kiracı kemeri SQL'in içinde (`owner_seller = store`) |
| `tradehub_core/tradehub_core/doctype/media_asset/media_asset.py` | Yalnız docstring: "bayrak kapalıyken bu tabloya hiçbir şey yazılmaz" notu artık gerçek değildi — W7 istisnası ve gerekçesi yazıldı (dedup bayrağa bağlansaydı türev üretimini kapatmak uyarıyı da öldürürdü) |

**patches.txt satırı (hooks/patches.txt bu görevde YASAK — satır EKLENMEDİ,
sahibi eklesin):**

```
tradehub_core.patches.v15_9_34_media_asset_original_sha256
```

Sıra: `v15_9_21_media_pipeline_doctypes`ten sonra (tablo yoksa patch açıkça
patlar). Dev sitede patch `bench execute` ile koşuldu (`{"created":
["original_sha256"]}`), migrate koşturulmadı — migrate kilidi kuralı (runbook
§3: paralel ajan varken migrate yok); patches.txt satırı eklendiğinde bir
sonraki migrate prod'da aynı işi idempotent yapar.

### Bilinçli sınırlar

- Katman 3 yalnız W7 SONRASI yüklemeleri kapsar: eski dönüşümlerin orijinal
  baytları sunucuya hiç gelmedi, geriye dönük doldurulamaz.
- Parçalı yol (`upload_begin/finish`) slot taşımıyor; dönüşen parçalı
  yüklemede hash `library.upload` varlığına yine yazılır (kapsam içinde),
  yalnız slot kimliği boş kalır.
- Kayıt bayraktan BAĞIMSIZ ve best-effort; `Media Asset` tablosu/kolonu
  olmayan kurulumda sessizce atlanır (yükleme asla düşmez).

### Canlı ölçüm

Pikselli benzersiz PNG yüklendi (dönüştü: saklanan ad `8fa251fc…webp`,
orijinal sha `8670cc3b…` — ad orijinal hash'i TAŞIMIYOR, katman 1-2 kör) →
`find_in_my_library(sha_orijinal)` = **`found:true`**, `file_url` saklanan
adres. Ardından üç canlı dosya arşiv→purge ile, draft varlıklar konsoldan
temizlendi (`library.upload` süzgeci boş).

---

## 3. Testler (hepsi konteynerde, `bench run-tests`)

| Süit | Sonuç |
|---|---|
| `test_media_upload_slot_gate` (YENİ, 5) | yeşil — 417+kod+dosya-yok, bilinmeyen slot reti, slot'suz kabul (= kırmızı kanıt ikizi), 1200 kabul + warn-reddetmez, künye ölçüsü |
| `test_media_original_hash` (YENİ, 6) | yeşil — kayıt alanları/kimlik ayrımı, upsert tekilliği, katman-3 buluşu (katman 1-2 körlüğü ön koşul), izolasyon+vacuity+kırmızı kanıt, çöp, hassas-ikiz |
| `test_media_dedup_endpoint` (11) | yeşil — `test_orijinal_hash_yapisal_bosluk_olarak_bulunmaz` → `test_orijinal_hash_artik_ucuncu_katmanda_bulunur` ÇEVRİLDİ: eski test boşluğu sabitliyordu ve kendi docstring'i kırılınca güncellenmesini istiyordu; davranış değişti, gevşetme değil (legacy ad + ayrık baytlar fixture'ında bulan yalnız katman 3 olabilir) |
| `test_pipeline_bridge` (22) | yeşil |
| `test_media_bomb_escape` (14) | yeşil |
| `test_media_security_gate` (18) · `test_media_pipeline_integration` (6) · `test_policy_engine` (38) | yeşil (yükleme/politika süitleri) |

## 4. Panel E2E — S1b işareti çevrildi

`admin-panel/frontend/tests/e2e/media-upload-security.spec.ts` (dosya
W4-5/W5-B'nin; yalnız S1b bloğu + S1 yorumundaki bayatlamış tek cümle):
`test.fail` → `test`, çağrıya `slot: "product.image"` eklendi (sunucu hangi
politikayı uygulayacağını ancak beyandan bilir; slot'suz serbestliği S10/4
ölçmeye devam ediyor), iddia `417 + product_image_short_edge_too_small`.
Regresyon temizliği (200 dönerse arşiv→purge) korundu. Koşu: **S1, S1b, S10 =
3/3 yeşil**; `media-dedup.spec.ts` (S9) de yeşil.

## 5. Sınırlar / dokunulmayanlar

- `probe.py` / `content_gate.py` (W5-C) değişmedi — yalnız import.
- `hooks.py` / `patches.txt` değişmedi (satır §2'de).
- Parçalı yükleme uçlarına slot parametresi EKLENMEDİ (ayrı iş; davranış korunuyor).
- Commit atılmadı.
- Bilinen ruff bulgusu `seller_media.py:19 I001` HEAD'de de var (host ruff
  0.16 ile ölçüldü) — bu işin eseri değil, dokunulmadı.
