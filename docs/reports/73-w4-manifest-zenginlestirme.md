# 73 — W4: Manifest zenginleştirme (T-061 / T-062 / T-065)

**Tarih:** 2026-08-20 · **Ortam:** DEV (`istoc.localhost`, `istoc-dev` compose) · Bütün sayılar
konteyner içinde ölçüldü (bench console / run-tests / curl); "geçti" yazan her satır koşturuldu.

Faz 6'nın üç veri boşluğu tek elde kapatıldı: LQIP + baskın renk (T-065), normalize
alanları (T-061), sınıflandırma + biçim zinciri (T-062). Rapor 69'un bulgu 4'ü
("`lqip.py` var ama hiçbir üretim yolu çağırmıyor") artık geçerli değil.

---

## 1. Alanlar — nereye ve neden

Şartname yeri açıkça söylüyor (50-faz6, T-065 geliştirici prompt'u madde 3): **"Media
Version'a lqip ve dominant_color alanlarını ekle."** Normalize alanlarının evi de veri
modelinde (41-faz4) Media Version: `dpi (72)`, `colorspace (sRGB)` zaten şemadaydı ama
üretim onları hiç doldurmuyordu (9 sürümün 9'unda `width=0` ölçüldü). Sınıf/zincir için
kaynak belge yer söylemiyor; `policy_snapshot` ile aynı gerekçeyle ("karar anının
kopyası") sürümün yanına kondu. Sapmalar `doctype_specs/_index.json`'a işlendi.

**Eklenen 7 alan** (`Media Version`, hepsi `read_only`):

| Alan | Tip | Görev |
|---|---|---|
| `has_alpha` | Check | T-061 (kaynak belgede Media Source'taydı; o DocType bu app'te kurulu değil) |
| `classification` | Select (photo/transparent/graphic/animation/text) | T-062 |
| `classification_confidence` | Data(8) | T-062 (exact/high/low) |
| `format_chain` | JSON | T-062 — `classify.FormatStep.to_dict()` listesi |
| `lqip` | Data(64) | T-065 — ThumbHash base64, ham hâli <30 bayt (kanonik değer) |
| `lqip_data_uri` | Small Text | T-065 — hazır `data:image/png;base64,…` (aşağıda §1.1) |
| `dominant_color` | Data(16) | T-065 — `#rrggbb`, saydam pikseller sayılmadan |

**tabDocField ölçümü** (migrate sonrası, konteynerde):

```
[{"fieldname":"has_alpha","fieldtype":"Check"},{"fieldname":"classification","fieldtype":"Select"},
 {"fieldname":"classification_confidence","fieldtype":"Data"},{"fieldname":"format_chain","fieldtype":"JSON"},
 {"fieldname":"lqip","fieldtype":"Data"},{"fieldname":"lqip_data_uri","fieldtype":"Small Text"},
 {"fieldname":"dominant_color","fieldtype":"Data"}]
```
`SHOW COLUMNS`: 7/7 kolon `tabMedia Version`'da. Spec aynası
(`media/pipeline/doctype_specs/media_version.json`, `_index.json` field_count 12→19) eşitlendi.
`hooks.py` / `patches.txt` DEĞİŞMEDİ (yasak): şema değişikliği DocType JSON + `bench migrate`
ile gitti, veri düzeltmesi (backfill) patch değil idempotent yardımcı fonksiyon
(`enrich_version`) — aşağıda §3.

### 1.1 Neden `lqip_data_uri` diye ikinci bir alan var

Teslim sözleşmesi (`delivery/picture.py::lqip_style`) ve panel (`MediaImage.vue` `lqip`
prop'u) **yalnız** `data:image/…;base64,…` ya da `#rrggbb` kabul ediyor; ikisinin de
ThumbHash çözücüsü YOK (şartnamenin istediği `ui/src/lib/lqip.ts` bu depoda yazılmadı).
Ham ThumbHash'i uca göndermek FE tarafında hiçbir şey çizmez, `lqip_style` onu reddeder.
Kanonik değer `lqip`tir (<30 bayt); URI ondan yazma anında BİR kez türetilir
(`lqip.thumb_hash_to_data_uri` — stdlib zlib/struct PNG, Pillow'suz, deterministik,
ölçülen boy 1,5-2,6 KB).

---

## 2. Üretim yolu

Sürüm kaydını açan tek yer `pipeline_bridge._ensure_version` (worker). Köprüye
DOKUNULMADI; zenginleştirme `Media Version` controller'ının `before_insert`'inde koşar —
yani köprünün gerçek hattının İÇİNDE, ama köprü dosyasının dışında:

```
_run_rendition_job → _ensure_version → MediaVersion.before_insert
    → _enrich_from_source (best-effort, istisna sızdırmaz)
        → pipeline/image/enrich.py::enrich(kaynak)   ← saf, frappe'siz
            ├─ image/probe.probe_header  → width/height/has_alpha (piksel açmadan)
            ├─ image/classify.classify   → classification + FORMAT_CHAINS zinciri
            ├─ image/lqip.encode         → ThumbHash + dominant_color
            └─ dpi=72, colorspace=sRGB   → normalize KARARI (INV-02; ölçüm değil,
                                            normalize.DEFAULT_DPI_OUT / NormalizeSpec)
```

İdempotent: `lqip` doluysa hiçbir şey yapılmaz; geometri yalnız boşken yazılır (köprü bir
gün gerçek master ölçüsü yazarsa ezilmez). Sınıf ölçülemediyse (`measured=False`) BOŞ
bırakılır — tahmin, ölçüm gibi kaydedilmez.

### 2.1 Uçtan uca kanıt (W3-B'nin gerçek dosyaları, yeniden işleme yolu)

3 varlık için `Media Rendition` + `Media Version` satırları düşürülüp
`_run_rendition_job(file_url)` (gerçek worker fonksiyonu) yeniden koşuldu:

| Varlık | Türev (önce→sonra) | version_hash | lqip | dominant | sınıf | zincir |
|---|---|---|---|---|---|---|
| `7t7jvj9do5` (81d2uu3SDwL, 22.550 B) | 6→6 | `ce90bbd9…` (AYNI — hash yeniden üretilebilir) | `IAgKDwC1iXdOlndfdVeYZ4iJt+z8z+8O` | `#888888` | photo | AVIF→WEBP→JPEG |
| `7nhqvcmhpg` (51N9LYNfAVL, 38.667 B) | 10→10 | `9c924fe0…` | `pfcRC4C5h4icaPZ3uZqPifk=` | `#f8f8f8` | photo | AVIF→WEBP→JPEG |
| `7tlgnil1va` (51oe+YL+l0L, 41.361 B) | 10→10 | `4c3007f1…` | `ovcRC4CKtYmIifeoiYa/Zfk=` | `#f8f8f8` | photo | AVIF→WEBP→JPEG |

Üçünde de `width/height` gerçek ölçü (395×395, 830×395, 941×369), `dpi=72`,
`colorspace=sRGB`, `has_alpha=0`, `lqip_data_uri` 1.594-2.574 karakter.

**İki görüntü → iki LQIP ölçümü:** üç dosya üç FARKLI hash üretti (üstteki sütun) —
değer görüntünün içeriğinden türüyor, sabit değil. Aynı dosyanın yeniden işlenmesi aynı
hash'i üretiyor (test `test_ayni_goruntu_ayni_lqip` + `ce90bbd9…`'un birebir geri gelmesi).
Kalan 6 eski (boş) sürüm `enrich_version` ile backfill edildi: `hala bos: 0`.

Worker konteynerleri (`queue-long/short`, `scheduler`) yeni kodla yeniden başlatıldı —
rapor 69 §bulgular'daki "eski imaj worker'ı" tuzağı tekrarlanmadı; `_enrich_from_source`
queue-long kopyasında doğrulandı.

---

## 3. Manifest — alt katman taşıyor; uçların tek satırları

### 3.1 Yapılan (alt katman, benim dosyalarım)

- `delivery/manifest.py::ManifestBuilder.build_image(..., version_meta=None)` — kw-only,
  varsayılanlı; `VERSION_META_KEYS` süzgecinden geçirip `extra["version"]`e koyar.
  `contracts.delivery.DeliveryManifest` protokol İMZASI DEĞİŞMEDİ →
  `signatures.golden.json` olduğu gibi, `test_contracts` 75/75 yeşil.
- `contracts/delivery.py::RenderManifest.to_dict()` üç YENİ anahtar basar (hep, boş da
  olsa): `lqip` (servis biçimi: `lqip_data_uri` > `dominant_color` — `lqip_style`
  sözleşmesi), `dominant_color`, `version` (T-061/062/065 alanları; `policy_snapshot`
  gibi iç alanlar süzgeçten GEÇEMEZ — test ediliyor).
- `doctype/media_version/media_version.py::version_enrichment_for_assets(assets)` —
  uç sahipleri için TEK sorgulu okuma: varlık → (yayındaki, yoksa en yeni) sürümün
  alanları, `format_chain` çözülmüş liste hâlinde.

Delivery katmanından örnek manifest (konteynerde, gerçek DB verisiyle —
`build_image(..., version_meta=version_enrichment_for_assets(...)['7t7jvj9do5'])`):

```json
{"slot_key": "product.image",
 "src": "/files/media/7t7jvj9do5/ce90bbd9…/w384-384.webp",
 "sources": [{"type": "image/avif", "srcset": "…"}, {"type": "image/webp", "srcset": "…"}],
 "lqip": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAYAAABzen…",
 "dominant_color": "#888888",
 "version": {"width": 395, "height": 395, "dpi": 72, "colorspace": "sRGB",
             "has_alpha": false, "classification": "photo",
             "format_chain": [{"fmt": "AVIF", …}, {"fmt": "WEBP", …}, {"fmt": "JPEG", …}],
             "lqip": "IAgKDwC1iXdOlndfdVeYZ4iJt+z8z+8O", "lqip_data_uri": "data:image/png;base64,…",
             "dominant_color": "#888888"}}
```

### 3.2 ÖLÇÜLEN varsayım: "uç zaten alttan okuyor" — KISMEN TUTMUYOR

`api/media_manifest.py` (dokunulmadı — başka ajanın) HTTP ile ölçüldü:

1. **`get_manifest?listing=LST-00206` (vitrin, guest):** anahtarlar ARTIK geliyor ama
   BOŞ — `"lqip": "", "dominant_color": "", "version": {}`. Sebep: uç `man.to_dict()`'i
   olduğu gibi geçiriyor (alt katman kazandı) ama `build_image`'a `version_meta`
   GEÇMİYOR. **Gereken:** `_render_manifest`'in `builder.build_image(...)` çağrısına tek
   parametre + veriyi getiren tek satır (aşağıda §3.3). `_CiftSuzgecliBuilder.build_image`
   `**kwargs`'ı zaten iletiyor — alt sınıf değişikliği gerekmez.
2. **`manifest_batch` (panel, `useMediaRenditions`'ın çağırdığı uç; oturumlu GET ile
   ölçüldü):** yanıtın HİÇBİR yerinde lqip/colorspace/classification yok. Sebep: uç
   `Media Rendition`'ı AÇIK alan listesiyle okuyor (`_varlik_turevleri`), `Media Version`'ı
   hiç okumuyor. Alt katmandan akış YOK — buradaki varsayım tutmuyor, satırlar uç
   sahibine raporlandı (§3.3).

### 3.3 Uç sahibine (api/media_manifest.py) gereken satırlar — dosyaya DOKUNULMADI

İmport (bir kez): `from tradehub_core.tradehub_core.doctype.media_version.media_version import version_enrichment_for_assets`

**Vitrin (`get_manifest*`):** `_manifest_batch_icin` içinde `turevler = …` satırının altına

```python
zengin = version_enrichment_for_assets(sorted({v["name"] for grup in varliklar.values() for v in grup.values()})) if acik else {}
```

`_tek_ilan_govdesi`/`_render_manifest`'e `zengin` geçirilip `builder.build_image(...)`
çağrısına `version_meta=zengin.get(varlik["name"])` eklenir. Gerisi (süzgeç, `lqip`
seçimi, `to_dict`) alt katmanda hazır ve test edilmiş.

**Panel (`manifest_batch`):** adres döngüsündeki gövde sözlüğüne

```python
"version": next((zengin.get(v["name"]) for v in secili if v["name"] in zengin), None),
```

(`zengin = version_enrichment_for_assets([v["name"] for grup in varliklar.values() for v in grup])` ile birlikte — toplam 2 satır; sorgu sayısı +1, N+1 yok.)

---

## 4. FE besleme — DOKUNULMADI, satırlar raporlandı

- **`useSellerMedia.js` (`bicimle`, satır ~64 civarı — başka sahiplik):**
  `lqip: row.lqip_data_uri || row.dominant_color || "",`
  Not: bu satır tek başına yetmez — `get_my_media`'nın satırı (o uç `api/seller_media.py`,
  dokunulmadı) bugün `lqip_data_uri`/`dominant_color` TAŞIMIYOR; `inventory.list_files`/
  `metadata.read_many` katmanına ya da uca aynı `version_enrichment_for_assets` bağlanmalı.
- **`useMediaRenditions.js`:** değişiklik gerekmez — §3.3'teki `"version"` anahtarı uçtan
  gelince `manifest.version` olarak zaten erişilir; `MediaQualityPanel`'in `dpi` /
  `colorSpace` / `alpha` satırları (bugün "—") `manifest.version.dpi/colorspace/has_alpha`
  ile dolar.
- **`MediaImage.vue` / `MediaVideo.vue`:** hazır — `lqip` prop'una `data:image/png;base64,…`
  ya da `#rrggbb` verilecek; ikisi de artık DB'de duruyor.

---

## 5. Testler ve vacuity

Yeni modül: `tradehub_core/tests/test_media_version_enrichment.py` — **13 test**
(8 saf katman + 5 üretim yolu), konteynerde koşuldu: **13/13 OK (0,7 sn)**.

**Vacuity ölçümü (gerçekten koşuldu):** konteyner kopyasında `before_insert`'teki
`self._enrich_from_source()` çağrısı `pass` ile değiştirildi → **3 test KIRMIZI**
(`test_uretim_yolu_alanlari_doldurur`: "lqip boş — üretim yolu çağrılmamış",
`test_iki_kaynak_iki_lqip_db`, `test_version_enrichment_for_assets`) → çağrı geri
kondu → **13/13 yeşil**. Ayrıca kalıcı `test_vacuity_uretim_cagrisi_olmadan_alanlar_bos`
aynı iddiayı her koşuda mock'la doğrular: alanları dolduran TEK yol üretim çağrısıdır.

Regresyon (hepsi konteynerde): `test_contracts` 75 OK · `test_image_lqip` 27 OK ·
`test_media_manifest_api` 11 OK · `test_manifest_batch` 16 OK · `test_pipeline_bridge`
22 OK. Mevcut hiçbir test dosyası DEĞİŞTİRİLMEDİ.

## 6. Dosya listesi

| Dosya | Değişiklik |
|---|---|
| `media/pipeline/image/enrich.py` | YENİ — saf zenginleştirici (probe+classify+lqip tek okuma) |
| `media/pipeline/image/lqip.py` | `thumb_hash_to_data_uri` eklendi (stdlib PNG) |
| `media/pipeline/delivery/manifest.py` | `build_image(version_meta=…)` + `VERSION_META_KEYS` |
| `media/pipeline/contracts/delivery.py` | `to_dict`e `lqip`/`dominant_color`/`version` |
| `tradehub_core/doctype/media_version/media_version.json` | 7 alan + 2 kesme |
| `tradehub_core/doctype/media_version/media_version.py` | `before_insert` + `_enrich_from_source` + `enrich_version` + `version_enrichment_for_assets` |
| `media/pipeline/doctype_specs/media_version.json`, `_index.json` | spec aynası + sapma kaydı |
| `tradehub_core/tests/test_media_version_enrichment.py` | YENİ — 13 test |

Yasaklı dosyaların hiçbirine (`pipeline_bridge.py`, `api/media_manifest.py`,
`api/seller_media.py`, `hooks.py`, frontend, `docker/`, mevcut testler) dokunulmadı;
köprüde değişiklik GEREKMEDİ (0 satır).
