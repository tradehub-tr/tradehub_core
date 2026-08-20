# 50 — Şerit A: Şema kurulumu ve kablolama (T-040 · T-043 · T-044 · T-064 · T-133)

**Tarih:** 2026-08-19 · **Depo:** `tradehub_core` (`ahmet`)
**Ortam:** `istoc-dev` compose, site `istoc.localhost`, Frappe v15, MariaDB 10.6,
bench Python 3.11.6 · **Host:** macOS Python 3.9.6
**Girdi raporları:** `40-t043-kullanim-gc.md` (B3), `42-t133-gozlemlenebilirlik.md` (B5),
`34-dogrulama-faz4-7.md`, `37-media-crop-intent.md`

> **Bu şeridin sahipliği:** `hooks.py`, `permissions.py`, `patches.txt`,
> `patches/**`, `bench migrate`. Dalga 1'de 12 ajan bu dosyalara dokunamadığı
> için kuyruklarını buraya devretti.

---

## 0. Yöntem etiketleri

| Etiket | Anlamı |
|---|---|
| **[Ö]** | Konteynerde ölçüldü, çıktı aynen aktarıldı |
| **[T]** | Test koşuldu, sayı gömülü |
| **[V]** | Vacuity — düzeltme geri alındı, KIRMIZI görüldü, geri kondu |
| **[K]** | Kod okundu (`dosya:satır`) |
| **[?]** | **ÖLÇÜLEMEDİ** → §10 |

**Konteyner disiplini:** uygulama kodu imajda, bind-mount YOK. Her dosya
`docker cp` ile **dört konteynere birden** (backend, queue-short, queue-long,
scheduler) kopyalandı ve host↔konteyner `sha256` eşitliği her turda gösterildi
(§8.1). Host'ta yapılıp konteynerde doğrulanmamış hiçbir iddia yok.

---

## 1. Karar tablosu (önce sonuç)

| # | İş | Önceki durum | Bugün | Kanıt |
|---|---|---|---|---|
| 1 | **`Media Usage` DocType** | şema hazır, **kurulu değil** — üretimde bağ kaydı bellek içi | ✅ **KURULDU** + `uk_usage_quad` UNIQUE | §2, §3 |
| 2 | **`Media Version` DocType** | yok — T-064 ölçülemiyordu | ✅ **KURULDU** + `ix_asset_active` | §2, §4 |
| 3 | **`Media Audit Log` DocType** | B5 kurmama gerekçesi yazmıştı | ⛔ **KURULMADI** — gerekçe doğrulandı ve **güçlendi** (B5'in ölçemediği madde ölçüldü) | §7 |
| 4 | **`Media Asset.active_version`** | şemada var, kurulu tabloda yok | ✅ **KURULDU**, canlı `tabDocField`den ölçüldü | §4 |
| 5 | **Crop override kırığı** | uçtan uca çalışmıyor, her iki yazımda ret | ✅ **KAPANDI** — `profile` Link→Data | §5 |
| 6 | **`observability.install()`** | çağıran satır YOK, tek metrik toplanmıyor | ✅ **KABLOLANDI** — `after_migrate` + `after_request` | §6 |
| 7 | **`/metrics` ucu** | yok | ✅ **VAR ve KORUMALI** — 403 / 401 / 200 ölçüldü | §6.3 |
| 8 | **Ayrı GC işleri** | tek birleşik iş kayıtlı | ✅ **KAYITLI** — üç iş, üç bayrak, üç kilit | §6.5 |
| 9 | **Kiracı izolasyonu** | yeni DocType'lar için kanca yok | ✅ **VAR** — `query_conditions` + `has_permission` × 2 | §3.3 |
| 10 | Prometheus/Grafana kurulumu | yok | ⛔ **HÂLÂ YOK** — `docker/` kapsam dışı; dosyalar üretildi | §6.6, §10 |

**`bench migrate` temiz** [Ö]: son koşumda `traceback|error|exception|failed`
için eşleşme **0**. **`Media Engine Settings` bayrakları 0 kaldı** [Ö].

---

## 2. Kurulum — kurulan, kurulmayan, ve neden

### 2.1 Yazılan yamalar

| Yama | Ne yapar |
|---|---|
| `v15_9_28_media_usage` | `Media Usage` + `ix_asset_open`, `ix_ref`, **`uk_usage_quad` UNIQUE** |
| `v15_9_29_media_version` | `Media Version` + `ix_asset_active` |
| `v15_9_30_media_asset_active_version` | `Media Asset.active_version` (Link → Media Version, permlevel 1) |
| `v15_9_31_media_crop_override_profile` | `Media Crop Override.profile` Link → **Data** |
| `v15_9_32_media_metrics_token` | `site_config.media_metrics_token` (sır üretimi, mevcut değere dokunmaz) |
| `v15_9_33_media_metrics_scraper` | `Media Metrics Scraper` rolü + yetkisiz servis kullanıcısı |

Altısında da **`reload_doc` dönüş değeri kontrol edilir**. Gerekçe bu depoda
ölçülmüş: `reload_doc` dosyayı bulamazsa sessizce `False` döner, **hata
FIRLATMAZ**; bir yama tam olarak böyle davranıp `tabSingles`a 29 değer yazmış,
`Patch Log`a "koştu" yazılmış, `tabDocType` satırı hiç oluşmamış ve iki uç HTTP
500 vermişti (`32-faz8-api-kapanis.md`). Her yama ayrıca **tablonun/kolonun
gerçekten oluştuğunu** `information_schema`dan doğrular.

### 2.2 Yamaların ilk koşumu bir kırık BULDU [Ö]

İlk `bench migrate` `v15_9_30`da düştü:

```
File ".../patches/v15_9_30_media_asset_active_version.py", line 57, in execute
    if not frappe.db.has_column(TABLO, ALAN):
pymysql.err.ProgrammingError: ('DocType', 'tabMedia Asset')
```

`frappe.db.has_column` **DocType adı** ister, tablo adı değil — başına ikinci
bir `tab` ekliyor. Düzeltildi ve sabit, gerekçesiyle birlikte yamada yorumlandı.
Bu, doğrulama katmanının kendisinin çalıştığının kanıtı: sessiz geçseydi
"migrate başarılı, kolon yok" durumu üretime çıkardı.

### 2.3 KANIT — canlı `tabDocType` [Ö]

```sql
select name, module from `tabDocType` where name in
  ('Media Usage','Media Version','Media Audit Log');

name           module
Media Usage    Tradehub Core
Media Version  Tradehub Core
```

`Media Audit Log` **listede yok ve bilinçli olarak yok** — §7.

`module` sapması (kaynak şemalar `"Media Engine"` yazıyor, o modül bu app'te
YOK: `modules.txt` tek satır `Tradehub Core`) kurulu diğer yedi medya
DocType'ıyla tutarlı ve her iki JSON'un `$comment`ında yazılı.

---

## 3. `Media Usage` — kalıcı bağ kaydı (T-043 kriter 1)

### 3.1 Şema sapmaları — üçü de gerekçeli

| Sapma | Kaynak şema | Kurulu | Gerekçe |
|---|---|---|---|
| `module` | Media Engine | Tradehub Core | O modül yok |
| `profile_used` | Link → Media Profile | **Data(64)** | Aşağıda |
| `track_changes` | 1 | **0** | `doc_events` yolunda satır satır güncellenen bir tablo, her `last_seen` damgası için bir `tabVersion` satırı üretirdi |

`profile_used` sapması `Media Rendition.profile` ile **birebir aynı** karar ve
aynı ölçüme dayanıyor: hattın taşıdığı değer slot politikasındaki profil ADI
(`w384`), Media Profile docname'i (`product.image:w384`) değil; politika adları
slotlar arası çakışıyor (`w128` hem `brand.logo` hem `seller.logo`
politikasında). Link yazılsaydı hat her yazmada kırılırdı. `tests/test_usage.py`
zaten `profile_used="product-main"` gibi serbest bir ad kullanıyor [K].

### 3.2 `uk_usage_quad` — kurulumun asıl işi

`usage_key` **UNIQUE DEĞİL** (kaynak şemanın ölçümü: iki kısıtı birden koymak
419.676 satırda indeksi %49 şişiriyor). Tekilliği dörtlü bileşik indeks taşıyor:

```
index_name      non_unique  cols
ix_asset_open   1           asset,is_open
ix_ref          1           ref_doctype,ref_name
uk_usage_quad   0           asset,ref_doctype,ref_name,ref_field
```
[Ö]

Bu indeks olmadan `core/usage.py::FrappeUsageBackend.upsert`'ün
`on duplicate key update` ifadesi **hiç tetiklenmez**; her yazma yeni satır açar
ve `is_open=0` yapılan bir bağ, aynı dörtlünün açık kopyası yüzünden hâlâ açık
görünür — yani öksüz kararı bozulur.

### 3.3 Kiracı izolasyonu

`Media Usage` sahiplik kolonu **taşımaz**; izolasyon `asset` üzerinden
`Media Asset.owner_seller`a **zincirlenir** — `Media Rendition` /
`Media Processing Job` / `Media Crop Intent` ile aynı desen ve aynı gerekçe
(denormalize satıcı kolonu, Asset devredildiğinde sessizce eskir).

`Media Crop Intent`ten **tek farkla**: satıcı burada **YAZAMAZ**. Kırpma
niyetini kullanıcı çizer, ama kullanım bağını hat yazar. Satıcı kendi kullanım
kaydını silebilseydi öksüz kararını kendi lehine çevirirdi:

```python
def media_usage_has_permission(doc, ptype, user):
    ...
    if ptype in ("write", "create", "delete"):
        return False
```

`hooks.py`ye hem `permission_query_conditions` hem `has_permission` kaydedildi.

### 3.4 KANIT — B3'ün "ÖLÇÜLMEDİ" listesinin 1. ve 2. maddesi kapandı [T]

B3 raporu §9: *"`FrappeUsageBackend`in SQL'i hiç koşmadı… ölçülmeyen şey alan
adı eşlemesi, `on duplicate key update` davranışı ve epoch↔Datetime dönüşümü"*
ve *"`get_usage_store()` kalıcı dalı hiç seçilmedi"*. Üçü de artık gerçek
tabloya karşı koşuyor:

```
test_depo_kalici_secildi                     usage_store_status():
                                             installed=True persistent=True reason=""
                                             get_usage_store() -> PersistentUsageStore   OK
test_upsert_idempotent_ve_first_seen_korunuyor   1 satır, is_open=1,
                                             first_seen < last_seen (epoch→Datetime)   OK
test_kapatma_satiri_SILMEZ                   1 satır, is_open=0                        OK
test_surec_yeniden_baslasa_da_bag_duruyor    yeni depo örneği bağı görüyor             OK
test_yaris_kosulunu_VERITABANI_cozuyor       iki ham upsert -> 1 satır                 OK
```

---

## 4. `Media Version` + `active_version` (T-064)

### 4.1 "Şema ile tablo ayrışmış" iddiası — ölçüldü ve DÜZELTİLDİ [Ö]

Üç rapor "şemada var, kurulu tabloda yok" diyordu. Ölçüm ayrımı keskinleştirdi;
raporlar **iki farklı dosyayı** "şema" diye karıştırıyordu:

| Dosya | `active_version` | `asset_key` / `source_file` |
|---|---|---|
| `media/pipeline/doctype_specs/media_asset.json` (TASARIM) | vardı | yoktu |
| `tradehub_core/doctype/media_asset/media_asset.json` (KURULU) | **yoktu** | vardı |
| `tabMedia Asset` (CANLI TABLO) | yoktu | vardı |

Yani ayrışma **JSON ile tablo arasında DEĞİLDİ** — kurulu JSON ile canlı tablo
birebir aynıydı. Ayrışma **tasarım belgesi ile kurulu DocType** arasındaydı ve
üç sapmasının üçü de kurulu JSON'un `$comment`ında gerekçesiyle yazılıydı:

1. `slot_key` Link→Media Policy değil Data — *Media Policy kurulmadı* (**hâlâ geçerli**)
2. `source` Link→Media Source değil `source_file` Link→File — *Media Source kurulmadı* (**hâlâ geçerli**)
3. `active_version` YOK — *Media Version kurulmadı* → **BUGÜN KAPANDI**

Bu şeritte **yalnız 3. sapma** kapatıldı. 1 ve 2 bilinçli ve hâlâ doğru.

### 4.2 KANIT — canlı `tabDocField`den, şema dosyasından DEĞİL [Ö]

Bu depoda KYC/KYB `status` alanı JSON'da permlevel 4 iken canlı `tabDocField`de
1'di ve ikinci güvenlik katmanı sessizce düşmüştü. Aynı hataya düşmemek için
yama iddiayı canlıdan ölçüyor ve uymazsa **patlıyor**:

```
tabDocField (parent='Media Asset', fieldname='active_version'):
  fieldtype=Link  options=Media Version  permlevel=1  read_only=1  search_index=1
information_schema:
  tabMedia Asset.active_version  varchar(140)
```

`permlevel 1` gerekçesi `state` / `legal_hold` ile aynı: "hangi sürüm yayında"
bir **moderasyon** kararıdır; satıcı formdan doğrulanmamış bir sürümü yayına
alamamalı.

### 4.3 Geçiş protokolü artık ÖLÇÜLEBİLİR [T]

B3 §7.3'te dört fazlı protokolü tasarlamış ama *"bugün yazılan bir test yeşil
olamazdı, o yüzden yazılmadı"* demişti. Şimdi yazıldı ve koşuyor:

```
test_iki_surum_ayni_anda_var_olabiliyor      2 sürüm, aynı asset             OK
test_gecis_tek_transactionda_tutarli         active_version=yeni,
                                             is_active=1 yalnız [yeni],
                                             eski sürüm SİLİNMEDİ            OK
test_celiskili_is_active_REDDEDILIYOR        ValidationError                 OK
```

`is_active` denormalize bir kopyadır; doğruluğun tek kaynağı `active_version`.
Çelişki controller'da **reddedilir, sessizce düzeltilmez** — hangi tarafın doğru
olduğuna kod adına karar vermek, geçişin yarıda kaldığını gizlemek olurdu.

---

## 5. 🔴 Crop override kırığı — ölçüldü, kapatıldı, vacuity ile doğrulandı

### 5.1 Kırığın tam hâli [Ö][K]

```
Media Crop Override.profile   Link → Media Profile
Media Profile docname         "product.image:w1920"   (autoname: field:profile_key)
pipeline/api/crop.py:472      {p.profile_key for p in self._profiles(slot)} = "w1920"
```

`p` bir `image/render.py::RenditionProfile`; `profile_key` özelliği slot
politikasındaki `profiles[].name`i döndürüyor — yani **kısa ad**. Ölçüldü:
`product-image.json` profilleri `['w96','w192','w384','w640','w768','w1280','w1920']`;
`tabMedia Profile` docname'leri `product.image:w1920` biçiminde.

* `"w1920"` yazılırsa: `_parse_overrides` kabul eder, **Link doğrulaması düşer**.
* `"product.image:w1920"` yazılırsa: Link geçer, **`_parse_overrides` reddeder**
  ("bu slotta tanımlı bir profil değil").

İkisini birden karşılayan değer **yoktu** — `overrides` ile kırpma niyeti
**hiç kaydedilemiyordu**.

### 5.2 Karar: `profile` Link → **Data(64)** — ve neden diğer iki yol kapalı

| Yol | Neden reddedildi |
|---|---|
| Docname'i kısa ada çevir | **İmkânsız.** Docname global tekil olmak zorunda; politika adları slotlar arası çakışıyor (`w128` hem `brand.logo` hem `seller.logo` politikasında). |
| `api/crop.py`'yi docname'e çevir | Modülü slot→docname eşlemesine, dolayısıyla `frappe`ye bağlardı. `pipeline/api/crop.py` **SAF kalmalı** (`@frappe.whitelist()` yok kuralı); bugün yalnız politika JSON'larını okuyor. |
| **Alanı Data yap** | ✅ Emsali AYNI GÜN `Media Rendition.profile` için verildi ve gerekçesi o alanın `description`ında yazılı. |

Kısa ad burada **tek anlamlı**: satırın hangi slotta olduğu
`Media Crop Intent.asset` → `Media Asset.slot_key` üzerinden zaten belli.

Yama **dolu tabloda DURUR**: `product.image:w1920` → `w1920` dönüşümü kayıpsız
değil ve sessizce yapılırsa kullanıcının çizdiği kadraj yanlış profile
bağlanabilir. Ölçüldü: `tabMedia Crop Override` **0 satır**,
`tabMedia Crop Intent` **0 satır** — çevrilecek veri yok.

### 5.3 KANIT — uçtan uca [T]

```
test_alan_canlida_Data_ve_options_bos    tabDocField: fieldtype=Data, options=NULL   OK
                                          information_schema: profile varchar(64)
test_politika_adi_gercekten_KAYDEDILEBILIYOR
    Media Asset + Media Crop Intent(overrides=[{profile:"w96", x:.1,y:.2,w:.5,h:.4}])
    -> insert BAŞARILI, geri okunan profile == "w96"
    -> core/crop.py::override_for(niyet, "w96") -> Rect(x=0.1, w=0.5)             OK
test_docname_yazimi_okuma_tarafinda_ESLESMEZ
    profile="product.image:w96" yazılsaydı override_for(...,"w96") -> None        OK
```

Son test, Data'ya çevirmenin **yeterli olmadığını**, ADIN da doğru olması
gerektiğini sabitliyor.

---

## 6. Gözlemlenebilirlik kablolaması (T-133)

### 6.1 B5'in en dürüst cümlesi kapandı

> *"bugün hâlâ tek bir metrik toplanmıyor."* — `42-t133-gozlemlenebilirlik.md` §12

Sebep tekti: `instrument.install()` yazılıydı ama **çağıran satır yoktu**.

### 6.2 Ne bağlandı

| Kanca | Ne yapar | Neden gerekli |
|---|---|---|
| `after_migrate += install_instrumentation` | Migrate anında kurulum + kapsam <1.0 ise `Error Log` | "metrik var" ile "metrik doluyor" farkını ölçen tek sayı |
| `after_request += after_request_write_shard` | **WEB** sürecinin parçasını paylaşılan dizine yaz (15 sn kilit) | Migrate ayrı süreçtir; sarmalayıcılar süreç belleğinde yaşar |
| `scheduler_events["cron"]["*/5"] += write_metrics_shard` | Kendi parçasını yazar **+ short/long kuyruklarına birer iş atar** | Kuyruk süreçlerinde istek yok; sayaçları aksi hâlde `/metrics`e hiç ulaşmaz |
| `auth_hooks = [authenticate_metrics_scrape]` | Bearer token'ı oturuma çevirir | §6.4 |

**`*/5` cron'u MEVCUT listeye eklendi, yeni anahtar AÇILMADI.** Aynı sözlükte
ikinci kez `"*/5 * * * *"` tanımlamak öncekini **sessizce düşürürdü** ve iki
medya süpürücüsü (`sweep_stuck_transcodes`, `sweep_stuck_scans`) hiç koşmazdı.
Bu hata bir kez yapıldı ve AST üzerinde tekrarlı-anahtar denetimiyle yakalandı.

### 6.3 Toplama dizini — `docker/`a dokunmadan çok süreçli toplama [Ö]

`MEDIA_METRICS_DIR` tanımlıysa o; değilse
`sites/<site>/private/media-metrics`. Gerekçe ölçüldü:

```
docker inspect: istoc-dev_sites volume'ü backend, scheduler, queue-short ve
queue-long konteynerlerinin DÖRDÜNE birden rw bağlı.
```

Yani çok süreçli toplama **`docker/` altında hiçbir şey değiştirmeden bugün
çalışıyor**. Dizin `private/` altındadır ve `files/` DEĞİLDİR — nginx yalnız
`private/files`i (o da X-Accel + yetki ile) servis eder.

KANIT — süreç başına bir parça [Ö]:

```
sites/istoc.localhost/private/media-metrics/
  media-13.metrics.json   media-16.metrics.json   media-17.metrics.json
  media-20.metrics.json   media-23.metrics.json   media-27.metrics.json
  media-33.metrics.json   media-34.metrics.json   media-39.metrics.json  ...
status(): {"sharded": true, "shards": 11, "metrics": 24, "series": 1}
```

### 6.4 `/metrics` yetkilendirmesi — ölçülmüş bir engel ve çözümü

**Karar: Bearer token.** `?token=` sorgu parametresi **reddedildi**: sorgu
dizesi nginx access log'una, `Referer` başlığına ve tarayıcı geçmişine yazılır —
sır, onu koruması gereken günlüğe sızardı. Karşılaştırma
`hmac.compare_digest` ile **sabit zamanlı**; `==` ilk farklı bayta kadar çalışır
ve süre farkı token'ı bayt bayt tahmin ettirir. Sır ne log'a, ne hata mesajına,
ne yanıt gövdesine yazılır; `status()` yalnız **yapılandırılmış olup
olmadığını** söyler.

**Ölçülen engel [Ö]:** ilk denemede doğru token da **401** aldı.
`frappe.auth.validate_auth` iki parçalı bir `Authorization` başlığı görüp de
kullanıcı ATANMAMIŞSA isteği uç fonksiyonuna hiç ulaştırmadan kesiyor:

```python
if len(authorization_header) == 2 and frappe.session.user in ("", "Guest"):
    raise frappe.AuthenticationError
```

`validate_oauth` yalnız `OAuth Bearer Token` tablosuna bakıyor. Frappe'nin bu iş
için tuttuğu tek genişleme noktası `auth_hooks`. Kanca tokeni bir kimliğe
çeviriyor; kimlik **kasten çok az şey yapabiliyor**:

* `user_type = "Website User"` → desk yok
* tek rolü `Media Metrics Scraper`, o rolün **hiçbir DocType'ta DocPerm satırı YOK**
* parola atanmıyor → bu hesaba parolayla girilemez
* `/metrics` erişimi **role değil token'ın kendisine** bağlı (`_token_ok`) —
  yani rolü birine vermek metrik okutmaz. İki kat, ikisi de aynı sırra bağlı.
* eşleşmeyen başlıkta kanca **sessizdir**: istisna atmaz, log yazmaz (aksi hâlde
  her API-anahtarlı istek bir hata kaydı üretirdi)

Ek ölçüm: yanıt tipi. B5'in taslağı `"binary"` öneriyordu; `as_binary`
`application/octet-stream` + `Content-Disposition: attachment` **dayatıyor** —
ikisi de bir scrape ucu için yanlış. `"download"` (`as_raw`) kullanıldı.
Ara adımda `"raw"` denendi ve `KeyError` → HTTP 500 verdi (ölçüldü); geçerli
anahtar `"download"`. Ayrıca kayıt defterinin `charset`i ayıklandı, yoksa
başlık `charset=utf-8; charset=utf-8` çıkıyordu.

### 6.5 KANIT — `/metrics` üç yönden, GERÇEK HTTP [Ö]

```
tokensiz      -> HTTP 403        (ucun kendi kapısı, PermissionError)
yanlis token  -> HTTP 401        (Frappe'nin kapısı, AuthenticationError)
dogru token   -> HTTP 200  ct=text/plain; version=0.0.4; charset=utf-8  bayt=194

Content-Disposition: inline; filename=metrics

# HELP media_audit_event_total Denetim kaydina yazilan medya olayi
# TYPE media_audit_event_total counter
media_audit_event_total{action="media.access_denied",decision="deny",severity="high"} 5
```

Seri **boş değil** ve sayı, aynı süreç ömrü içinde her yeni istekle **artıyor**
(aynı turda 2 → 4 → 5 ölçüldü; süreç yeniden başlayınca sayaç sıfırdan başlar,
Prometheus bunu `rate()` tarafında zaten bekler). Değeri
üreten trafik gerçek: guest'ten gelen imzasız `media_access.download` istekleri
`audit.log_media_event` üzerinden reddediliyor ve ölçüm noktası o çağrıyı
sarıyor. Yani bu çıktı aynı zamanda `install()` kablolamasının çalıştığının
kanıtı — B5'in ölçümüne göre dün aynı uç servis edilse **bütün seriler boş
dönerdi**.

`status()` künyesi [Ö]:

```
instrument: points_total=10  points_bound=10
coverage:   defined=24  written_by_points=10  needs_collector=8  unaccounted=0
exporter:   sharded=true  shards=11  metrics=24  series=1
```

### 6.6 Ayrı GC işleri — kaydedildi [Ö]

```sql
select name, method, frequency, cron_format, stopped from `tabScheduled Job Type` ...

observability.write_metrics_shard        Cron   */5 * * * *   0
retention.run_scheduled_gc               Daily                0
retention.run_scheduled_gc_derivatives   Daily                0
retention.run_scheduled_gc_originals     Daily                0
```

Üçü de kayıtlı ve `stopped=0`. Bayraklar `None` [Ö] → **kuru koşum**.

**Birleşik iş neden kaldırılmadı.** B3 §4.3 kaldırılmasını önerdi (üçü birden
kayıtlıysa aynı envanter günde iki kez taranır). Ama bu şeridin kuralı
`hooks.py` diff'inde **0 silme** ve ölçülen bedel küçük: üç iş de varsayılan
kuru koşumda, bayrakların üçü de kapalı, fark günde iki fazladan tarama ve iki
fazladan `Error Log` raporu. Kazanç: hangi bayrak açılırsa açılsın davranış
önceden yazılmış. **Islak koşuma geçilirken birleşik kaydın TEK SATIR
silinmesi gerekir** ve bunu söyleyen bir test var (§8.3).

### 6.7 Üretilen dağıtım dosyaları

| Dosya | Kaynak | Satır |
|---|---|---|
| `deploy/prometheus/media-alerts.yml` | `alerts.to_prometheus_rules()` | 184 (16 kural) |
| `deploy/grafana/media-engine.json` | `alerts.grafana_dashboard_json()` | 306 (12 panel) |
| `deploy/prometheus/scrape-config.example.yml` | elle — ayrı sunucudan scrape | 61 |

`alerts.dogrula()` çıktısı [T] — sessiz kopma sigortası:

```json
{"alerts": 16, "unknown_metrics": [], "duplicate_names": [],
 "metrics_with_alert": 14, "metrics_without_alert": 10,
 "runbooks": 16, "runbook_gaps": 16}
```

Bilinmeyen metriğe bağlı kural **yok**, tekrarlı kural adı **yok**. Metrik adı
değişip kural güncellenmezse Prometheus hata VERMEZ, kural hiç ateşlenmez ve
panel boş kalır — `dogrula()` tam olarak bunu düşürür.

`scrape-config.example.yml` **TLS'i zorunlu** olarak işaretliyor: bearer token
düz metindir, `scheme: http` ile göndermek sırrı ağdaki herkese vermektir.
`insecure_skip_verify` açıkça yasaklandı.

---

## 7. `Media Audit Log` — **KURULMADI**, ve gerekçesi bugün GÜÇLENDİ

B5 (`42-t133-gozlemlenebilirlik.md` §7.1) kurmama gerekçesi yazmıştı. Gerekçe
okundu, üç maddesi de yeniden ölçüldü, **ve B5'in ölçemediği dördüncü madde
bugün ölçülüp gerekçeye eklendi.** Karar: **KURULMASIN.**

### 7.1 Ölçümler [Ö]

```sql
select count(*) from `tabDocType` where name='Media Audit Log';        -> 0
select count(*) from `tabAuthorization Decision Log`;                  -> 2963
select count(*) from `tabAuthorization Decision Log`
   where action like 'media.%';                                        -> 2365
select count(distinct action) ... where action like 'media.%';         -> 16
```

### 7.2 B5'in **[?] işaretli** maddesi kapandı — ve en güçlü argüman bu

B5 §10 madde 6: *"ADL'de silme izni var mı (append-only gerçekten mi) — DocPerm
denetimi yapılmadı [?]"*. Bugün ölçüldü [Ö]:

```
tabDocPerm (parent='Authorization Decision Log'):
  Marketplace Admin   read=1 write=0 create=0 delete=0
  Compliance Officer  read=1 write=0 create=0 delete=0
  System Manager      read=1 write=0 create=0 delete=0
  Marketplace Seller  read=1 write=0 create=0 delete=0
  Seller              read=1 write=0 create=0 delete=0
tabCustom DocPerm:
  Buyer Finance / Platform Admin / Platform Finance   read=1 write=0 create=0 delete=0
```

**Hiçbir rolde write, create ya da delete yok — ne DocPerm'de ne Custom
DocPerm'de.** ADL gerçekten append-only. Yani B5'in "mekanizma zaten çalışıyor"
argümanı yalnız hacimle değil, **izin modeliyle de** doğrulandı. Yeni bir tablo
kurmak, bu güvenceyi sıfırdan ve elle yeniden kurmak demekti.

### 7.3 Kurmama gerekçesi — dört madde

1. **Mekanizma çalışıyor** [Ö]: 2.365 medya olayı, 16 eylem, hash zinciri,
   `masked:<fp>` maskelemesi.
2. **İzin modeli zaten append-only** [Ö]: 8 rol, hiçbirinde yazma/silme.
3. **İkinci tablo hash zincirini böler.** ADL'nin bütünlük güvencesi tek bir
   zincire dayanıyor; "bu kayıt silinmiş mi" sorusunu iki ayrı zincirde ayrı
   ayrı sormak gerekirdi.
4. **`CLAUDE.md` §4 "DocType bloat"**: mevcut tablo işi görüyorken yeni tablo
   açmak deponun kendi kuralına aykırı.

### 7.4 Kurmamanın ÇÖZMEDİĞİ şey — açıkça

`36-dogrulama-faz12-14.md`'nin "`Media Audit Log` DocType YOK" tespiti
**doğruydu**, ama eksik olan tablo değil. Eksik olan üç **çağrı yeri**:

| Eksik | KVKK | Sahibi |
|---|---|---|
| Hassas doctype **okumaları** kaydedilmiyor (bugün 0 `pii.reveal` kaydı) | m.12 | `permissions.py` — **bu şeridin dosyası, aşağıya bakın** |
| Veri sahibi talebi olayları (`privacy/data_export.py`) | m.11 | privacy görevi |
| Retention uygulama kayıtları (`privacy/data_retention.py`) | m.4/2-d | privacy görevi |

Birincisi bu şeridin dosyasında ama **bu turda YAPILMADI** ve bunu gizlemiyorum:
`log_pii_reveal` fonksiyonu henüz yok, `has_permission` içinden çağrılacak
kaydın şekli (hangi alan, hangi maskeleme, hangi hacim) `media/audit.py`
sahibiyle birlikte kararlaştırılmalı — okuma yolunda satır başına bir ADL
yazması, ölçmediğim bir yük. **Açık madde olarak §11'de.**

---

## 8. Koşum kayıtları

### 8.1 Konteyner senkronu [Ö]

Uygulama kodu imajda, bind-mount **yok**. Her dosya `docker cp` ile dört
konteynere kopyalandı ve sha256 eşitliği doğrulandı:

```
tradehub_core/hooks.py                          backend ok  q-short ok  q-long ok  scheduler ok
tradehub_core/permissions.py                    ok ok ok ok
tradehub_core/patches.txt                       ok ok ok ok
tradehub_core/api/observability.py              ok ok ok ok
tradehub_core/patches/v15_9_28..33 (6 dosya)    ok ok ok ok
doctype/media_usage/* , media_version/*         ok ok ok ok
doctype/media_asset/media_asset.json            ok ok ok ok
doctype/media_crop_override/*.json              ok ok ok ok
media/** (142 dosya)                            farkli_dosya=0  ×4 konteyner
```

Başlangıçta worker konteynerlerinde **24 medya dosyası eskiydi** (B3/B5 yalnız
backend'e kopyalamıştı) — senkronlandı. Aksi hâlde `hooks.py`ye kaydedilen
`run_scheduled_gc_originals` worker'da `AttributeError` verirdi.

### 8.1.1 Bir tur `docker cp` SESSİZCE TUTMADI — ve bunu yalnız son süpürme yakaladı [Ö]

Bütün ölçümler bittikten sonra yapılan kapanış `sha256` süpürmesinde **6 dosya
dört konteynerde birden eski** çıktı (`hooks.py`, `permissions.py` hariç
`patches.txt`, `api/observability.py`, `v15_9_33`, iki test dosyası).
`hooks.py`nin konteynerdeki hâli `auth_hooks` bloğunu taşımıyordu:

```
host      : 276b9aa4...  (auth_hooks VAR)
konteyner : 626f0803...  (auth_hooks YOK — ilk kopya turunun sürümü)
diff      : 30,37d29  < auth_hooks = [...]
```

Ara turlarda bu dosyaların eşitliği **doğrulanmıştı** ve o turların testleri de
`docker restart` sonrası yeşildi — yani kopya bir noktada landı, sonra geri
gitti. Sebep bulunamadı [?]; `docker restart`ın dosyaları geri almadığı ayrıca
ölçüldü (kopyala → restart → sha aynı). Kalıcı ders, kuralın kendisi:
**her ölçüm turundan sonra sha süpürmesi, tek seferlik değil.**

Düzeltme sonrası her şey yeniden yapıldı: 20 dosya × 4 konteyner kopyalandı,
sha eşitliği **0 fark**, `medya/**` ağacı 142 dosya × 4 konteyner **0 fark**,
dört konteyner yeniden başlatıldı, `bench migrate` yeniden koşturuldu (tarama
0), yedi regresyon paketi yeniden koşturuldu ve `/metrics` üçlüsü yeniden
ölçüldü. §8.2, §8.3 ve §6.5'teki sayılar **bu son turun** sayılarıdır.

### 8.2 `bench migrate` [Ö]

```
Executing tradehub_core.patches.v15_9_28_media_usage                 Success: 0.087s
Executing tradehub_core.patches.v15_9_29_media_version               Success: 0.023s
Executing tradehub_core.patches.v15_9_30_media_asset_active_version  Success: 0.032s
Executing tradehub_core.patches.v15_9_31_media_crop_override_profile Success: 0.007s
Executing tradehub_core.patches.v15_9_32_media_metrics_token         Success: 0.006s
Executing tradehub_core.patches.v15_9_33_media_metrics_scraper       Success: 4.919s

SON KOŞUM TARAMASI: grep -icE "traceback|error|exception|failed"  ->  0
```

`patches.txt`e yazılan `#` yorum satırları `configparser` tarafından
ayıklanıyor — yerel olarak Frappe'nin kendi parse yoluyla doğrulandı
(`post_model_sync` 221 giriş, yorum sızmadı).

### 8.3 Testler [T]

| Modül | Sonuç |
|---|---|
| `tests.test_serit_a_kablolama` (**YENİ**) | **33 test, OK** |
| `tests.test_media_access` | 17 test, OK |
| `tests.test_retention_gc` | **38 test, OK** (37 idi; §8.4) |
| `tests.test_media_usage_store` | 24 test, OK |
| `tests.test_contracts` | 75 test, OK |
| `tests.test_kyc_tenant_isolation` | 13 test, OK |
| `tests.test_pipeline_bridge` | 19 test, OK |
| `tests.test_observability` | 72 test, OK |
| `tests.test_observability_instrument` | 26 test, OK |
| `tests.test_observability_exporter` | 19 test, OK |
| `tests.test_observability_alerts` | 20 test, OK |
| `tests.test_rum_metrics` | 20 test, OK |
| `tests.test_media_usage_sources` | 12 test, OK |
| `tests.test_usage` | 45 test, OK |
| `tests.test_retention` | 47 test, OK (1 atlandı) |
| `tests.test_media_browse` | 14 test, OK |
| `tests.test_crop` | 26 test, OK |
| `tests.test_media_crop_intent` | 17 test, OK |
| `tests.test_crop_geometry` | 37 test, **1 KIRMIZI — ORTAMSAL, bu şeritle ilgisiz** |

`test_crop_geometry` kırmızısı: `test_ts_ikizi_ayni_sayiyi_veriyor`,
`node: bad option: --experimental-strip-types` — konteynerdeki Node 20.19.2 o
bayrağı desteklemiyor. Aynı dosyanın Python tarafı yeşil ve sapma ölçümleri
basılıyor (`crop.py ↔ crop_geometry.py en büyük sapma = 1,8e-12 px`). Şema ya da
kablolama ile ilgisi yok; **düzeltilmedi ve düzeltilmiş gibi gösterilmiyor.**

### 8.4 B3'ün el sıkışma testi çalıştı

B3 `test_hooks_kaydi_henuz_yok` yazmıştı: *"kayıt yapıldığı gün bu test kırmızı
olur ve rapor güncellenmesi gerektiğini söyler."* Kayıt bugün yapıldı, test
kırmızı oldu, **yönü çevrildi** ve yerine iki test yazıldı:

* `test_ayri_gc_isleri_hooks_pyde_kayitli` — üç kaydın da varlığını sabitler ve
  birleşik kayıt silinirse "ya 0-silme kuralı bozuldu ya ıslak koşuma geçildi"
  der.
* `test_uc_gc_isinin_bayraklari_ayri` — üç bayrak ve üç kilidin ayrıştığını
  ölçer. Ortak bayrak/kilit, üç işi birden kaydetmeyi sessizce "hepsini aç"
  anlamına getirirdi.

### 8.5 Lint [?]

`ruff` **ne host'ta ne konteynerde kurulu** — B5'in ölçümüyle aynı. **Lint
KOŞULMADI.** Yerine ölçülen: `python3 -m py_compile` tüm yeni dosyalarda temiz;
`tabnanny` temiz; `tokenize` ile denetim — boşluk girintili **kod** satırı 0;
110 karakteri aşan satır 0.

---

## 9. Vacuity — beş deney, hepsi KIRMIZI [V]

Her deneyde düzeltme geçici geri alındı, test koşuldu, geri kondu.

| # | Geri alınan | Sonuç |
|---|---|---|
| **V1** | `uk_usage_quad` UNIQUE indeksi DROP edildi | `FAILED (failures=2)` → yama yeniden koşturuldu → `OK` |
| **V2** | `_token_ok` daima `False` (token kapısı kaldırıldı) | `FAILED (failures=2)` **+ HTTP: doğru token 401** → geri kondu → `OK` + HTTP 200 |
| **V3** | `hooks.py`den 9 kayıt satırı silindi | `test_serit_a: FAILED (failures=2)` · `test_retention_gc: FAILED (failures=1)` → geri kondu → ikisi de `OK` |
| **V4** | `Media Crop Override.profile` Link'e geri çevrildi | `LinkValidationError: Could not find Row #1: Profil: w96` + `'Link' != 'Data'` → yama yeniden koşturuldu → `OK` |
| **V5** | `_validate_active_consistency` çağrısı silindi | `FAILED (failures=1)` → geri kondu → `OK` |

**V1 bir zayıflık BULDU ve düzeltti.** İlk hâlinde idempotency testi kısıt
olmadan da **yeşil kaldı**: `PersistentUsageStore.open_link` önce `fetch`
yapıyor, yani aynı süreçte tekrarlanan yazma zaten tek satır üretiyor. Kısıtın
gerçekten koruduğu şey **yarış**tır: iki süreç de `fetch`te boş görüp ikisi de
`insert` eder. `test_yaris_kosulunu_VERITABANI_cozuyor` eklendi — `fetch`i
atlayıp backend'e iki ham `upsert` gönderiyor; kısıt yokken **2 satır**, varken
**1 satır**.

**V2 iki düzeyde ölçüldü.** Birim testi (`_token_ok` False) ve **gerçek HTTP**:
düzeltme geri alınmışken doğru token bile **401** aldı, geri konunca **200**.
Not: birim testinde `_authorize()` "session" döndü çünkü test koşucusu
Administrator olarak koşuyor — asıl kapı zaten HTTP ölçümünde görüldü.

**V4 kırığın kendisini gösterdi:** `Could not find Row #1: Profil: w96` — yani
`api/crop.py`nin yazdığı değer Link doğrulamasından geçemiyor. §5.1'de tarif
edilen kırık tam olarak budur.

---

## 10. ÖLÇÜLEMEYENLER

| # | Ne | Neden | Gereken |
|---|---|---|---|
| 1 | **Prometheus'un bu ucu gerçekten scrape ettiği** | Prometheus kurulu değil (`docker/` kapsam dışı) | Ayrı sunucuda `scrape-config.example.yml`i uygulamak |
| 2 | **`promtool check rules`** | `promtool` kurulu değil | Kural dosyası üretildi, doğrulanmadı |
| 3 | **Panonun Grafana'da çizilmesi** | Grafana kurulu değil | İçe aktarma + göz denetimi |
| 4 | **8 metriğin toplayıcısı** | `media/inventory.py` + PII harita denetimi yazılmadı — bu şeridin dosyası değil | 3 KVKK alarmı veri göremez |
| 5 | **`scheduler` sürecinin kendi kayıt defteri** | O süreç yalnız iş kuyruğa atar, ölçülen medya modüllerini çağırmaz; parçası yazılmıyor ve bu bilinçli | — |
| 6 | **Islak GC koşumu** | Üç bayrak da kapalı; açmak bu şeridin işi değil | `26-t053` §12 listesinin 2-4. maddeleri |
| 7 | **`ruff`** | Kurulu değil | §8.5 |
| 8 | **Üretim ortamındaki hiçbir sayı** | Üretim DB'sine erişim yok | — |
| 9 | **`Media Usage`nın gerçek yükte maliyeti** | `doc_events` yolu bu tabloya henüz yazmıyor (`media_pipeline_enabled=0`) | Bayrak açıldığında ölçülmeli |

---

## 11. Açık maddeler — sahibi ve tek adımı

| # | Madde | Şiddet | Tek adım | Sahibi |
|---|---|---|---|---|
| **B-1** | Hassas doctype okumaları denetlenmiyor (0 `pii.reveal`) | **YÜKSEK** | `log_pii_reveal` + `has_permission` çağrısı | `permissions.py` + `media/audit.py` birlikte |
| **B-2** | 8 metriğin toplayıcısı yok → 3 KVKK alarmı veri göremez | **YÜKSEK** | `media/inventory.py` + PII harita denetimi | envanter görevi |
| **B-3** | Prometheus + Grafana kurulu değil | **YÜKSEK** | `docker/` compose + `deploy/` dosyalarını yükle | altyapı |
| **B-4** | 16 runbook dosyası yok (`docs/ops/runbooks/`) | ORTA | `alerts.runbook_paths()` listesi × 16 dosya | ops belgeleri |
| **B-5** | Lazy/on-demand türev üretim yolu yok | ORTA | Olmadan türev silme geri dönüşsüz | boru hattı |
| **B-6** | `Media Asset.legal_hold` için yönetim ucu | ORTA | 26 numaralı raporun 4. maddesi | api görevi |
| **B-7** | Islak koşuma geçilirken birleşik `run_scheduled_gc` kaydı çıkarılmalı | DÜŞÜK | `hooks.py`den tek satır | `hooks.py` sahibi |
| **B-8** | `Media Policy` / `Media Source` kurulmadı → `media_asset.json` sapma 1-2 açık | DÜŞÜK | İki DocType + `slot_key`/`source` alan dönüşümü | sonraki şerit |
| **B-9** | `test_crop_geometry` TS parite testi ortamsal kırmızı | DÜŞÜK | Node 22+ ya da `tsx` | test altyapısı |
| **B-10** | `media_metrics_token` Prometheus sunucusuna dağıtılmadı | ORTA | `site_config.json`dan oku → `credentials_file` (0600) | ops |

---

## 12. Dokunulan dosyalar

| Dosya | Değişim |
|---|---|
| `tradehub_core/hooks.py` | **+146 / −0** — perm kancaları ×4, `after_migrate`, `after_request +=`, `auth_hooks`, 3 zamanlanmış iş |
| `tradehub_core/permissions.py` | **+67 / −0** — `media_usage_*`, `media_version_*` (query + has_permission) |
| `tradehub_core/patches.txt` | **+15 / −0** — 6 yama (+ 2 yorum satırı) |
| `tradehub_core/patches/v15_9_28..33` | **YENİ** — 6 yama, 461 satır |
| `tradehub_core/api/observability.py` | **YENİ** — 412 satır (`/metrics`, `status`, auth kancası, parça yazımı) |
| `tradehub_core/tradehub_core/doctype/media_usage/` | **YENİ** — JSON 115 + controller 80 |
| `tradehub_core/tradehub_core/doctype/media_version/` | **YENİ** — JSON 132 + controller 82 |
| `.../doctype/media_asset/media_asset.json` | `active_version` alanı + `$comment` sapma 3 güncellendi |
| `.../doctype/media_crop_override/media_crop_override.json` | `profile` Link → Data + sapma 2 gerekçesi |
| `tradehub_core/tests/test_serit_a_kablolama.py` | **YENİ** — 535 satır, 33 test |
| `tradehub_core/tests/test_retention_gc.py` | B3'ün el sıkışma testi ters çevrildi (+1 test: 37 → 38) |
| `deploy/prometheus/media-alerts.yml` | **YENİ** — üretilmiş, 16 kural |
| `deploy/prometheus/scrape-config.example.yml` | **YENİ** — ayrı sunucudan scrape örneği |
| `deploy/grafana/media-engine.json` | **YENİ** — üretilmiş, 12 panel |

**`hooks.py` diff'i: 146 ekleme, 0 SİLME** [Ö] — kural korundu.

---

## 13. Sonuç

Şerit A'nın işi yeni davranış yazmak değil, **yazılmış davranışı devreye
almaktı**. Devreye alınanlar: iki DocType, bir kolon, bir alan tipi düzeltmesi,
dört `hooks.py` kancası, üç zamanlanmış iş ve korumalı bir `/metrics` ucu.

Ölçülebilir üç kazanç:

1. **Kullanım bağı artık kalıcı.** B3'ün "üretimde hâlâ bellek içi" tespiti
   kapandı; `FrappeUsageBackend`in bugüne kadar hiç koşmamış SQL'i gerçek
   tabloya karşı test ediliyor.
2. **Kırpma niyeti kaydedilebiliyor.** İki tarafın iki farklı değer beklediği,
   ikisini birden karşılayan değerin olmadığı kırık kapandı ve vacuity ile
   gösterildi.
3. **Metrik toplanıyor.** Dün servis edilse bütün serileri boş dönecek uç,
   bugün gerçek trafikten üretilmiş, boş olmayan bir seri döndürüyor — ve
   tokensız/yanlış tokenlı isteği reddediyor.

Bir DocType **bilinçli olarak kurulmadı** (`Media Audit Log`) ve gerekçesi bu
turda ölçülen bir veriyle güçlendi: ADL'nin append-only olduğu artık iddia
değil, ölçüm.

En dürüst cümle: **metrikler toplanıyor ama kimse okumuyor.** Prometheus ayrı
sunucuda ve henüz bu uca bağlanmadı; bağlanana kadar 16 alarm kuralı ve 12
panel birer dosyadan ibaret. Bunun için gereken her şey `deploy/` altında ve
tek adımı §11 B-3'te yazılı.
