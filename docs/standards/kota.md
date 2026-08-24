# Medya Kota ve Rate Limiting Standardı

> **Güncel runtime sözleşmesi (MOGEM-573, 2026-08-24):**
> [`tenant-media-quota.md`](./tenant-media-quota.md). Aşağıdaki T-027 metni
> tarihsel denetim ve rate-limit araştırmasıdır; “kod değiştirilmedi”,
> “rendition sayılmıyor”, “uyarı/rapor yok” ifadeleri artık güncel değildir.

> Görev: **T-027** · Faz: Medya Motoru Faz 0-2 · Branch: `medya-motoru-faz0-faz2`
> Şema: [`tradehub_core/media/pipeline/policy/quota.schema.json`](../../tradehub_core/media/pipeline/policy/quota.schema.json)
> Kardeş belge: [`retention.md`](./retention.md) (T-026)
> Yazım tarihi: 2026-08-17

## 0. Bu belgenin kapsamı

İki ayrı ama birbirine bağlı konu:

1. **Kota** — bir satıcının ne kadar medya tutabileceği, ne kadar yükleyebileceği.
   Mevcut kodda **kısmen var**: yalnız toplam depolama (GB) uygulanıyor.
2. **Rate limiting** — bir kullanıcının birim zamanda kaç istek atabileceği.
   Mevcut kodda **var ama medya uçlarında yok** ve mevcut uygulamada üç kusur var.

Hiçbir mevcut kod dosyası bu görev kapsamında değiştirilmedi. Bu belge mevcut
davranışı satır referanslarıyla belgeliyor, kusurları adlandırıyor ve şemayı
onların üstüne kuruyor.

**Ölçüm uyarısı:** Docker kapalı, üretim veritabanına ve canlı siteye erişim yok.
Bu belgedeki her sayı bir kaynak dosya satırından okundu (dosya:satır verildi) ya
da kaynak dosyanın kendi yorumundan **alıntılandı** (o durumda alıntı olduğu
belirtildi). Ölçüm gerektiren maddeler §10'da.

---

## 1. Mevcut kota: tek metrik, tek kapı

Uygulanan **tek** medya kotası: satıcı başına toplam public depolama (MB).

| Ne | Değer / yer |
|---|---|
| Kota anahtarı | `quota.max_storage_mb` — `patches/v15_9_17_seed_storage_quota.py:35` |
| Enforcement fonksiyonu | `entitlement/checks.py:213` — `check_media_storage_quota` |
| Bağlandığı hook | `hooks.py:234-237` — `doc_events["File"]["before_insert"]` |
| Kullanım ölçümü | `media/files.py:225` — `storage_usage(store)` |
| Limit okuma | `entitlement/core.py:157` — `get_quota_limits(store)` (cache'li) |
| Ret mekanizması | `media/upload_policy.py:120` — `QUOTA_EXCEEDED = Kod("upload_quota_exceeded", False)` |

### 1.1 Plan bazlı varsayılan değerler

`patches/v15_9_17_seed_storage_quota.py:38-44`:

| Plan (ada göre eşleşme) | `quota.max_storage_mb` | Satır |
|---|---|---|
| `enterprise` | `-1` (sınırsız) | `:39` |
| `pro` | `5000` (5 GB) | `:40` |
| `premium` | `5000` (5 GB) | `:41` |
| `starter` | `2000` (2 GB) | `:42` |
| `free` + eşleşmeyen custom plan | `500` | `:44` (`_FALLBACK_MB`) |

Eşleşme **plan adının içinde alt dize arıyor** (`_default_for_plan`,
`:47-50`: `if token in lname`). Yani "Pro Plus" → 5000, "Enterprise Trial" → -1.
Yama **idempotent**: `quota.max_storage_mb` planın `quota_limits` JSON'unda zaten
varsa dokunulmuyor (`:69-71`) — admin override'ları ezilmiyor.

### 1.2 Limit semantiği

`entitlement/core.py:212-215`:

| Değer | Anlam |
|---|---|
| `-1` | Sınırsız — her zaman geçer |
| `0` | Devre dışı — her zaman reddet (`current_count` ne olursa) |
| `> 0` | `current_count < limit` ise geçer |
| `None` | Plan'da tanımsız |

`None` durumunda `within_quota` **False** dönüyor (`core.py:221-223`) ama
`check_media_storage_quota` **açıkça geçiriyor** (`checks.py:262-263`):

```
limit_mb = get_quota_limits(store).get("quota.max_storage_mb")
if limit_mb is None:
    return  # plan'da tanımsız — seed patch atlandıysa bile yükleme reddedilmez
```

Yani iki fonksiyon aynı `None` girdisine **ters** cevap veriyor. Medya tarafındaki
tercih (fail-open) bilinçli ve `checks.py:233-236`'da gerekçeli: seed yaması
atlanmışsa satıcı hiç göremediği bir sayaç yüzünden reddedilmesin. Bu doğru
tercih ama **tutarsızlık belgelenmemiş** — `core.within_quota` okuyan biri medya
kapısının da fail-closed olduğunu sanır.

### 1.3 Kullanım nasıl ölçülüyor

`media/files.py:237-245` — ham SQL:

```sql
select coalesce(sum(boyut), 0), count(*) from (
    select max(file_size) boyut from tabFile
    where is_folder=0 and is_private=0 and left(file_url,7)='/files/'
      and owner in (…)
    group by file_url
) x
```

Üç filtre, üçü de kota kapsamını daraltıyor:

1. `is_folder=0` — klasör kaydı sayılmıyor.
2. **`is_private=0`** — private dosyalar **hiç sayılmıyor** (§4.1).
3. `left(file_url,7)='/files/'` — yalnız public yol.

`group by file_url` + `max(file_size)` **tekilleştirme**: aynı dosyaya birden çok
`File` satırı düşebiliyor. `files.py:228-230` bunun ölçüldüğünü söylüyor: "satır
toplamak kullanımı olduğundan büyük gösterirdi (yönetim panelinde ölçüldü:
1,06 GB yerine 1,49 GB)". **Bu iki sayı o yorumdan alıntı**, bu görevde
ölçülmedi.

Sahiplik `ownership.users_of(store)` üzerinden — mağazanın kullanıcı kümesi
(`files.py:232`). Kullanıcı yoksa sıfır dönüyor (`files.py:233-234`).

### 1.4 Ret nasıl iletiliyor

`checks.py:272-281`:

```
if current_bytes + incoming_bytes > limit_bytes:
    upload_policy.reddet(
        upload_policy.QUOTA_EXCEEDED,
        _("Depolama kotanız doldu ({0} MB). Yükleme yapılamadı.").format(limit_mb),
    )
```

Ret, medya yükleme sözleşmesinden geçiyor: mesajın sonuna
`[upload_quota_exceeded]` markörü konuyor ve istemci hata **metnine** değil
**koda** bakarak karar veriyor (`checks.py:273-277`). Kod `retryable=False`
(`upload_policy.py:120` — `Kod("upload_quota_exceeded", False)`), yani istemci
otomatik yeniden denemiyor. Bu doğru: kota dolu, tekrar denemek aynı sonucu
verir.

Not: bu bir **HTTP 429 değil**. `upload_policy.reddet` bir `frappe.throw`
zincirine gidiyor; HTTP durum kodu 417/500 olabilir. Rate limiting 429'u
`api/rate_limit.py:24-27`'deki ayrı sınıf üretiyor ve kota kapısı onu
kullanmıyor.

---

## 2. DOĞRULANMIŞ GERÇEK 1 — kota, dosya diske yazıldıktan SONRA çalışıyor

Görev tanımı bunu doğrulanmış gerçek olarak veriyor. Yerel olarak
**doğrulayabildiğim kısmı** ve **doğrulayamadığım kısmı** ayırıyorum.

### 2.1 Yerel olarak doğrulanan

Kota kapısı `File.before_insert` doc_event'ine bağlı:

`hooks.py:231-237`:
```
"File": {
    "before_insert": [
        "tradehub_core.utils.security.reject_unsafe_files",
        "tradehub_core.entitlement.checks.check_media_storage_quota",
    ],
```

Ve `hooks.py:232-233`'teki yorum **eskimiş**: "satıcı depolama kotası (TUR-139,
WP3 dolduracak — şu an no-op stub, yüklemeyi engellemez)". Oysa `checks.py:215`
diyor: "Faz 0'daki no-op stub'ın yerini aldı." Yani hook yorumu artık gerçeği
yansıtmıyor — kapı artık gerçekten engelliyor. Bu bir belge kusuru, kod kusuru
değil, ama okuyanı yanıltıyor.

Yükleme yolu `api/seller_media.py:302-308`:
```
doc = frappe.get_doc(
    {"doctype": "File", "file_name": …, "is_private": 0, "content": icerik}
)
doc.insert(ignore_permissions=True)
```

İçerik `content` alanında **belleğe** veriliyor; diske yazma işini Frappe'nin
`File` doctype'ı yapıyor.

### 2.2 Yerel olarak DOĞRULANAMAYAN — Frappe'nin iç sırası

`before_insert` hook'unun Frappe `File` doctype'ının kendi disk yazma adımından
önce mi sonra mı koştuğunu doğrulamak **frappe kaynak kodunu** gerektiriyor.
Frappe bu worktree'de yok: `find / -name "file.py" -path "*core/doctype/file*"`
çalıştırıldı, **0 sonuç** (frappe Docker imajının içinde ve Docker kapalı).

Görev tanımı bunu doğrulanmış olarak veriyor ve teknik olarak makul: Frappe'nin
`File.before_insert()` metodu içinde `save_file()` çağrısı yapıyorsa, doc_event
hook'ları **metodun sonunda** çalışır (Frappe `run_method` deseni: controller
metodu → aynı adlı hook'lar), yani disk yazma hook'tan **önce** olur.

Sonuç, iki durumda da aynı: **kotayı aşan yükleme diske yazıldıktan sonra
reddediliyor.** İki somut etki:

1. **Geçici disk tüketimi.** Reddedilen yükleme diskte yer kaplamış oluyor.
   Transaction rollback `File` **kaydını** geri alır ama `os.write` çağrısını
   geri almaz — Frappe'nin `on_rollback` temizliği yapıp yapmadığı da
   doğrulanmadı. Kalırsa bu bir **yetim dosya** ve kotaya da sayılmaz (kaydı
   olmadığı için `storage_usage` sorgusu onu görmez, `files.py:239` `tabFile`
   üzerinden sayıyor).
2. **Kota, gerçek disk kullanımının altını gösterebilir.** Yetim dosyalar
   birikirse `du` ile `storage_usage()` ayrışır. Doğrulama komutu §10.5.

**Doğru yer neresi:** kota kontrolü `api/seller_media.py:281`'deki
`upload_policy.check(...)` ile aynı noktada, yani `doc.insert()` **öncesinde**
yapılmalı. `upload_policy.check` boyut/uzantı/içerik kapılarını orada uyguluyor;
kota da bir kapı ve orada olması gerekiyordu. Bugün `before_insert`'te olması
onu ikinci bir güvenlik ağı yapıyor — güvenlik ağı olarak kalması **iyi**, ama
tek kapı olması **kusur**.

Şemadaki karşılığı: `enforcement.check_point` alanı, `pre_write` |
`doc_before_insert` | `both` değerlerini alıyor; varsayılan `both`.

---

## 3. DOĞRULANMIŞ GERÇEK 2 — eşzamanlı yüklemede yarış (race) var

### 3.1 Yarışın mekanizması

`checks.py:268-272`:
```
incoming_bytes = int(doc.get("file_size") or len(doc.get("content") or b"") or 0)
current_bytes = files.storage_usage(store)["bytes"]
limit_bytes = limit_mb * 1024 * 1024

if current_bytes + incoming_bytes > limit_bytes:
```

`storage_usage` kilitsiz bir `SELECT` (`files.py:237-245`) — `for update` yok,
`frappe.db.get_value(..., for_update=True)` yok, satıcı bazında bir mutex/
advisory lock yok. Kontrol ile yazma arasında hiçbir serileştirme yok.

Klasik TOCTOU: N eşzamanlı yükleme aynı `current_bytes`'ı okur, hepsi
`current + incoming <= limit` görür, hepsi geçer. Aşım üst sınırı teorik olarak
`(N-1) × dosya_boyutu`.

### 3.2 Aşımın büyüklüğü — ölçülmedi, ama üst sınırı hesaplanabilir

Tek dosya üst sınırı `upload_policy.py:67-72`:

| Tür | `MAX_BYTES` | Satır |
|---|---|---|
| image | 25 MB | `:68` |
| video | 200 MB | `:69` |
| document | 50 MB | `:70` |
| other | 50 MB | `:71` |
| bilinmeyen | 50 MB | `:76` (`MAX_BYTES_UNKNOWN`) |

Bu bir üst sınır hesabı, ölçüm değil: 10 eşzamanlı video yüklemesi teorik olarak
kotayı `9 × 200 MB = 1.8 GB` aşabilir. STARTER planın kotası 2000 MB
(`v15_9_17_seed_storage_quota.py:42`), yani tek bir eşzamanlı parti kotanın
neredeyse tamamı kadar aşım üretebilir. Gerçekte aşımın olup olmadığı
§10.2'deki sorguyla ölçülür.

Yükleme paralelliğini kolaylaştıran bir etken de var: parçalı yükleme
(`media/chunked.py`) — `CHUNK_BYTES = 2 MB` (`chunked.py:43`),
`MAX_CHUNKS = 256` (`chunked.py:47`), `SESSION_TTL_HOURS = 6`
(`chunked.py:51`). Yani 512 MB'a kadar oturum açılabiliyor ve panel bunları
paralel gönderebiliyor.

### 3.3 Şemadaki karşılığı

`enforcement.concurrency_guard` nesnesi:

- `strategy`: `none` (bugün) | `row_lock` | `advisory_lock` | `reservation`
- `reservation_ttl_seconds`: rezervasyon stratejisinde tutulan bayt hakkının ömrü
- `overshoot_tolerance_bytes`: kabul edilen aşım payı (varsayılan `0`)

`reservation` en doğru çözüm: kontrol anında baytı **rezerve et**, yazma başarılı
olursa kalıcılaştır, başarısız olursa TTL ile serbest bırak. Bu aynı zamanda
§2'deki "diske yazıldıktan sonra kontrol" sorununu da çözüyor, çünkü rezervasyon
yazmadan önce alınır.

---

## 4. DOĞRULANMIŞ GERÇEK 3 — beş muafiyet, kotayı boydan boya deliyor

`checks.py:238-260` sırasıyla altı erken `return` içeriyor. Görev tanımı
private ve toplu içe aktarmayı vurguluyor; tam liste aşağıda çünkü hepsi kota
kapsamını değiştiriyor.

| # | Muafiyet | Satır | Gerekçe (koddaki) | Risk |
|---|---|---|---|---|
| 1 | `is_folder` | `238-239` | "depolama tüketmez" | Yok |
| 2 | System Manager | `241-242` | "platform yönetimi kısıtlanmaz" | Düşük |
| 3 | Marketplace Admin | `243-244` | aynı | Düşük |
| 4 | `EXCLUDED_DOCTYPES` | `246-247` | inventory/usage ile tutarlılık | Orta |
| 5 | **Bulk import** | `249-252` | `reject_unsafe_files` ile aynı bayrak kanalı | **Yüksek** |
| 6 | **Private dosyalar** | `254-255` | "ÖLÇÜLMEYEN bir metrikle private yüklemeyi reddetmek tutarsız olurdu" | **Yüksek** |
| 7 | Mağazasız oturum | `257-259` | "kota kavramı mağazaya bağlı" | Orta |

### 4.1 Private dosyalar kotadan muaf — ve ölçülmüyor

Bu bir çelişki değil, **tutarlı bir eksiklik**: `storage_usage` private dosyaları
saymadığı için (`files.py:240` — `is_private=0`), kota kapısı da onları
reddetmiyor. `checks.py:226-228` bunu açıkça yazıyor.

Sonuç: **private yükleme sınırsız.** Bir satıcı `is_private=1` ile istediği kadar
dosya yükleyebilir; ne sayaçta görünür ne reddedilir. Bunun disk üzerindeki
etkisi ölçülmedi (§10.3).

Bu bir tasarım kararı gibi görünüyor ama tehlikeli olan şu: private yol, medya
uçlarından değil genel `upload_file` yolundan da erişilebilir. Yani muafiyet
"KYB belgesi yükleyen satıcı reddedilmesin" niyetiyle konulmuş olsa da, kapsamı
o niyetten geniş.

### 4.2 Toplu içe aktarma kotadan muaf

`checks.py:249-252` iki bayrak kanalı kontrol ediyor:
`doc.flags.bulk_import_safe` ve `frappe.flags.in_bulk_import_upload`.

Bulk import tam olarak **en çok dosya yükleyen** yol. Yani kotanın en çok
gerektiği yerde kota yok. Muafiyetin sebebi anlaşılır (yarı yolda kalan içe
aktarma kısmi veri bırakır), ama sonuç şu: kotayı aşmak isteyen için
dokümante edilmiş bir yol var.

Doğru çözüm muafiyeti kaldırmak değil, **içe aktarma öncesi toplu kontrol**:
işin başında toplam boyut hesaplanır, kota yetmiyorsa iş **hiç başlamaz**. Şema
bunu `bulk_import.precheck_total_bytes` ile tanımlıyor.

### 4.3 Arşiv ve çöp kotaya sayılmıyor

T-026'dan gelen bilgi, kota tarafında sonucu var:

- **Orijinal arşivi** (`private/image_originals/`) `File` kaydı yaratmıyor
  (`archive.py:8-9`) → `storage_usage` görmez → kotaya sayılmaz. Yorum bunu
  bilinçli diye yazıyor: "envanteri ve kotayı şişirmesin
  (GORSEL-OPTIMIZASYON.md §11)".
- **Çöp** dosyaları `private/media_trash/` altına taşınıyor ama `File` kaydı
  silinmiyor (`trash.py:156-158`). Ancak `file_url` hâlâ `/files/…` biçiminde
  (taşıma fiziksel, URL değişmiyor — `trash.py:41-45`), yani `storage_usage`
  sorgusunun `left(file_url,7)='/files/'` ve `is_private=0` filtrelerini
  **geçmeye devam ediyor**. Yani **çöpe atılan dosya kotadan düşmüyor.**

İkincisi kullanıcı açısından şaşırtıcı: "Kotam doldu → sildim → hâlâ dolu."
Bu davranış bu görevde kod okumasıyla çıkarıldı; üretimde §10.4 ile
doğrulanmalı.

Şema bunu `scope` nesnesiyle açık hâle getiriyor: `count_trashed`,
`count_archive_originals`, `count_private`, `count_backup` — dördü de bugünkü
davranışı varsayılan olarak taşıyor (`false`, `false`, `false`, `false`) ki
uygulama bilinçli karar versin.

---

## 5. Eksik kota metrikleri — beş metriğin dördü yok

Görev şartı beş metrik istiyor. Mevcut durum:

| Metrik | Şema alanı | Bugün var mı |
|---|---|---|
| Toplam depolama (GB) | `storage.total_gb` | **Var** — `quota.max_storage_mb` (§1) |
| Aylık yükleme sayısı | `uploads.per_month` | **Yok** |
| Eşzamanlı iş | `jobs.concurrent` | **Yok** |
| Toplam video süresi | `video.total_duration_minutes` | **Yok** |
| Tek dosya maks boyutu | `file.max_bytes_per_kind` | **Var ama plan bazlı değil** |

### 5.1 Aylık yükleme sayısı — yok

Kod tabanında `quota.max_*` anahtarları tarandı
(`grep -rn "quota\.max"`): `max_products`, `max_sub_users`, `max_co_owners`,
`max_regions`, `max_orders_per_month`, `max_active_listings`,
`max_storage_mb`. **Yükleme sayısı yok.**

Aylık pencere deseni mevcut: `quota.max_orders_per_month`
(`patches/v15_6_24_promote_enforcement_to_pricing.py:37`) ve
`api/translation.daily_reset_usage` (`hooks.py:155`) günlük sayaç sıfırlama
örneği. Yani altyapı deseni var, medya için kullanılmamış.

### 5.2 Eşzamanlı iş — yok

Video transcode `long` kuyruğa gidiyor (`transcode.py:156-161`) ve kuyruk
derinliği için **hiçbir plan bazlı sınır yok**. `transcode.py:8-11` riski
adlandırıyor: "sunucunun HER videoyu tekrar transcode etmesi 100'lerce
eşzamanlı yüklemede kuyruğu boğar." Çözüm olarak **koşullu** transcode
seçilmiş (`needs_transcode` — `NEEDS_TRANSCODE_MAX_WIDTH = 1280`
`transcode.py:60`, `NEEDS_TRANSCODE_MAX_BITRATE = 2_500_000`
`transcode.py:61`), yani iş **azaltılmış** ama **sınırlandırılmamış**.

Bir satıcı 100 büyük video yüklerse hepsi kuyruğa girer ve diğer satıcıların
işlerini bekletir. Bu bir **gürültülü komşu** (noisy neighbour) problemi ve
plan bazlı eşzamanlılık sınırı tam olarak bunun için var.

ffmpeg zaman aşımı `_FFMPEG_TIMEOUT_SECONDS = 1700` (`transcode.py:52`),
RQ kuyruk timeout'u yorumda 1800 sn olarak geçiyor (`transcode.py:50-51`) —
yani tek iş en fazla ~28 dakika tutuyor. 100 iş sıraya girerse toplam süre
buradan hesaplanır.

### 5.3 Toplam video süresi — ölçülmüyor bile

`File` üzerindeki medya alanlarında **süre alanı yok**. Envanter (T-026 §5.2):
`th_media_width`, `th_media_height` var (`patches/v15_9_15_media_metadata_fields.py`),
`th_media_video_status` var (`patches/v15_9_16_media_video_status.py`) — **süre
yok**.

`ffprobe` transcode kararı için çağrılıyor (`transcode.py:55` —
`_FFPROBE_TIMEOUT_SECONDS = 20`) ve genişlik/bitrate okuyor; süreyi de
okuyabilir ama saklamıyor.

Yani bu metrik için **önce bir alan** (`th_media_duration_seconds`) gerekiyor.
Şema bunu `video.duration_field` + `video.measurement_status: "not_measured"`
ile işaretliyor: ölçülmeyen bir metrikle kota uygulanamaz — bu, `checks.py:226-228`
mantığının aynısı (private dosyalar ölçülmediği için kotadan muaf).

### 5.4 Tek dosya maks boyutu — var ama plan bazlı değil

`upload_policy.MAX_BYTES` (§3.2 tablosu) **platform** sınırı, plan sınırı değil.
`effective_max` (`upload_policy.py:264-265`) bizim sınırla platform sınırının
minimumunu alıyor:

```
bizim = MAX_BYTES.get(tur, MAX_BYTES_UNKNOWN)
return min(bizim, platform_limit())
```

`platform_limit()` (`upload_policy.py:239`) Frappe'nin kendi sınırı. Yani zincir:
`min(politika, frappe)`. Plan bu zincire **hiç girmiyor**.

FREE planın 500 MB kotası varken tek dosyada 200 MB video yükleyebilmesi
(`upload_policy.py:69`) tutarsız: iki dosya kotayı bitiriyor. Şema
`file.max_bytes_per_kind` altında plan override'ı tanımlıyor ve zinciri
`min(plan, politika, frappe)` yapıyor.

`SINGLE_SHOT_LIMIT = 8 MB` (`upload_policy.py:89`) — bunun üstü parçalı
yüklemeye gidiyor; base64 şişmesi (~%33) yüzünden ham sınırın altında
tutulmuş (`upload_policy.py:86-88`).

### 5.5 Aşım davranışı — bugün tek seçenek: `block`

Görev şartı üç davranış istiyor: `block` | `queue` | `notify_only`.

Bugün yalnız `block` var: `upload_policy.reddet(QUOTA_EXCEEDED, …)`
(`checks.py:278-281`). `queue` ve `notify_only` yok.

`notify_only` özellikle önemli: yeni bir metrik (aylık yükleme, video süresi)
devreye alınırken önce **gözlem modunda** çalıştırılmalı — kaç satıcının
etkileneceği ölçülmeden `block` açmak ticari risk. Şema her metrik için ayrı
`on_exceed` alanı tanımlıyor ve yeni metriklerin varsayılanı `notify_only`.

---

## 6. Rate limiting: mevcut durum

### 6.1 İki farklı, birbirinden bağımsız uygulama var

| Uygulama | Yer | Kullanan |
|---|---|---|
| Proje içi decorator | `tradehub_core/api/rate_limit.py:34` | `cart.py`, `push.py`, `mobile_api.py`, `review.py`, `qa.py`, `storefront_api.py` |
| Frappe'nin kendi limiter'ı | `frappe.rate_limiter.rate_limit` | `api/public.py:18` → `:91`, `:441`, `:596` |
| Üçüncü, elle yazılmış | `api/theme.py:94` → `_enforce_save_rate_limit()` | Yalnız `theme.py` |

Üçü farklı anahtar şeması, farklı hata mesajı, farklı HTTP davranışı üretiyor.
`theme.py:28-31` kendi sabitlerini tanımlıyor (`_SAVE_RATE_LIMIT_COUNT = 10`,
`_SAVE_RATE_LIMIT_WINDOW_SECONDS = 60`,
`_SAVE_RATE_LIMIT_CACHE_PREFIX = "tradehub_theme_save_rl:"`) — yani üç farklı
Redis anahtar deseni.

### 6.2 KUSUR 1 — misafir kovası tek ve ortak

Görev tanımı bunu kusur olarak yazmayı istiyor. Doğrulandı.

`api/rate_limit.py:30-31`:
```
def _bucket_key(name: str, user: str) -> str:
    return f"rl:{name}:{user}"
```

`api/rate_limit.py:53`:
```
user = frappe.session.user if per_user else "_global"
```

Kimliği doğrulanmamış bir istekte `frappe.session.user` değeri `"Guest"`.
Yani **tüm anonim internet trafiği tek kovada birleşiyor**:
`rl:<scope>:Guest`.

Somut örnek — `api/storefront_api.py:43-44`:
```
@frappe.whitelist(allow_guest=True)
@rate_limit(max_calls=60, window_seconds=60, scope="sf_review_page")
```

`per_user` verilmemiş, varsayılan `True` (`rate_limit.py:35`). Sonuç:
`sf_review_page` ucu için **tüm dünyaya toplam** dakikada 60 istek. Tek bir
bot dakikada 60 istek atarsa o dakika içinde **hiçbir gerçek ziyaretçi** o ucu
kullanamaz. Bu, rate limiting'in kendisini bir **DoS aracına** çeviriyor.

Aynı desen `per_user=False` ile bilinçli olarak da kullanılıyor
(`storefront_api.py:379`, `:392` — `sf_qa_page`, `sf_template`), yani "global
kova" bazı yerlerde kasıtlı. Ama `sf_review_page`'de `per_user=True` bırakılmış
ve guest'te aynı sonucu üretiyor — **kasıtsız global kova**.

En sert örnek `api/mobile_api.py:135`:
```
@rate_limit(max_calls=10, window_seconds=60, scope="mobile_login", per_user=False)
```
Mobil login için **tüm kullanıcılara toplam** dakikada 10 deneme. Brute-force'u
engelliyor ama aynı zamanda: saldırgan dakikada 10 başarısız deneme atarak
**tüm mobil kullanıcıların girişini** kapatabilir. Bu, kilit-dışlama
(lockout-as-DoS) deseni.

**Çözüm:** misafir kovası kimlik yerine **istemci parmak izine** bağlanmalı.
Şema `rate_limit.guest_bucket` nesnesini bunun için tanımlıyor:
`key_strategy`: `session_user` (bugün) | `ip` | `ip_and_ua` | `forwarded_for`
ve `trusted_proxy_depth` (nginx arkasında `X-Forwarded-For` hangi konumdan
okunacak — yanlış konum IP taklidine açık kapı).

`docker/nginx` yapılandırması bu görevde okunmadı; `trusted_proxy_depth`
varsayılanı bu yüzden `null` bırakıldı ve doğrulama §10.7'de.

### 6.3 KUSUR 2 — pencere her istekte sıfırlanıyor (kalıcı kilit)

Bu, görev tanımında geçmiyor; kod okunurken bulundu.

`api/rate_limit.py:79-82`:
```
new_val = current + 1
cache.delete_value(key)
cache.set_value(key, new_val, expires_in_sec=window_seconds)
```

Yorum sebebini açıklıyor (`:77-78`): "Frappe RedisWrapper.set_value var olan
key'i override etmiyor; bu yüzden delete + set pattern kullanıyoruz."

Ama bunun yan etkisi şu: **her istek TTL'i baştan başlatıyor.** Fixed-window
beklenirken elde edilen davranış:

```
t=0    istek 1  → sayaç 1, TTL 60s'ye reset
t=30   istek 2  → sayaç 2, TTL 60s'ye reset   (pencere t=90'a kaydı)
t=59   istek 3  → sayaç 3, TTL 60s'ye reset
…
sayaç max_calls'a ulaşınca: 429.
Sayaç ancak trafik window_seconds boyunca TAM DURDUĞUNDA sıfırlanır.
```

Yani sürekli trafik altında sayaç **hiç sıfırlanmıyor**. `max_calls=60,
window=60` bir kullanıcı için "dakikada 60" değil, "60 istek, sonra 60 saniye
tam sessizlik" demek. Sürekli gezinen normal bir kullanıcı da bu duvara
çarpar.

`sf_review_page` gibi bir uçta bu, §6.2'deki misafir kovasıyla **birleşerek**
kötüleşiyor: guest kovası dolduktan sonra, trafik hiç durmadığı için (public
site) kova **hiç boşalmıyor**.

### 6.4 KUSUR 3 — read-modify-write atomik değil

`api/rate_limit.py:61-82`: `get_value` → `int` → karşılaştır → `delete_value` →
`set_value`. Redis `INCR` kullanılmıyor.

İki sonuç:

1. **Eksik sayım.** N eşzamanlı istek aynı `current`'ı okur, hepsi
   `current+1` yazar; sayaç 1 artar, N istek geçer. Yani limit eşzamanlılıkta
   yumuşuyor.
2. **`delete` ile `set` arasında kova yok.** O aralıkta gelen istek `current=0`
   okur — limit tamamen atlanır. Pencere küçük ama yüksek trafikte
   sömürülebilir.

Doğru desen tek atomik `INCR` + ilk artışta `EXPIRE`:
`INCR key` → dönen değer `1` ise `EXPIRE key window`. Bu hem atomik hem TTL
reset problemini (§6.3) çözüyor.

Şema bunu `rate_limit.algorithm` ile tanımlıyor:
`fixed_window_ttl_reset` (bugünkü hatalı davranış), `fixed_window_incr`,
`sliding_window_log`, `token_bucket`. Varsayılan `fixed_window_incr` — en az
değişiklikle doğru davranış.

### 6.5 Fail-open kararı — bilinçli ve doğru

`api/rate_limit.py:57-69`: Redis okuması hata verirse rate limit **atlanıyor** ve
istek geçiyor. Yorum gerekçeli: "Fail-closed tüm kullanıcıları kilitler; Redis
downtime sırasında kısa süreli rate-limit kaybı kabul edilebilir."

Bu doğru tercih ve şema onu koruyor: `rate_limit.on_backend_failure`
varsayılanı `fail_open`. Ama şema bir şey ekliyor: `alert_on_backend_failure`
(varsayılan `true`) — `frappe.log_error` çağrısı zaten var (`:64-67`), eksik olan
bunun bir **alarma** bağlanması. Sessiz fail-open, korumanın kapalı olduğunu
kimseye söylemez.

### 6.6 KUSUR 4 — 429 yanıtında `Retry-After` yok

`api/rate_limit.py:24-27`:
```
class TooManyRequestsError(frappe.ValidationError):
    http_status_code = 429
```

Durum kodu doğru. Ama `Retry-After` **header'ı set edilmiyor** — repoda
`frappe.local.response` üzerinde header yazan bir satır bu dosyada yok.

Mesaj Türkçe ve süreyi içeriyor (`:72-74`):
```
_("Çok fazla istek — {0} saniye sonra tekrar deneyin").format(window_seconds)
```

Ama bu **mesaj metni**, makine okunabilir değil. Ve §6.3 yüzünden verdiği süre
de yanlış: `window_seconds` sonra tekrar denemek işe yaramaz, çünkü o deneme
TTL'i yeniden sıfırlar. Doğru `Retry-After` değeri kovanın **kalan TTL'i**
olmalı (`ttl(key)`), sabit `window_seconds` değil.

Görev şartı: "aşımda HTTP 429 + Retry-After + Türkçe mesaj." Üçünden ikisi var,
`Retry-After` yok ve mesajdaki süre yanıltıcı.

### 6.7 KUSUR 5 — medya yükleme uçlarında rate limit HİÇ yok

Bu, medya motoru açısından en önemli bulgu.

`api/seller_media.py` içindeki tüm whitelisted uçlar tarandı
(`grep -n "@frappe.whitelist\|@rate_limit"`). **`@rate_limit` decorator'ı hiç
geçmiyor.** Rate limit uygulanmayan uçlar:

| Uç | Satır |
|---|---|
| `get_my_media` | `:63-64` |
| `get_my_usage` | `:98-99` |
| `preview_release` | `:110-111` |
| `archive_media` | `:136-137` |
| `unarchive_media` | `:154-155` |
| `purge_media` | `:160-161` |
| `get_my_summary` | `:202-203` |
| **`upload_media`** | `:250-251` |
| `upload_limits` | `:343-344` |
| **`upload_begin`** | `:355-356` |
| **`upload_chunk`** | `:366-367` |
| **`upload_finish`** | `:380-381` |
| `upload_abort` | `:398-399` |
| `upload_status` | `:406-407` |
| `update_media` | `:412-413` |
| `toggle_favorite` | `:424-425` |
| `add_tag` | `:433-434` |
| `get_dimensions` | `:453-454` |

Yani platformun **en pahalı** uçları (yükleme, parçalı yükleme, video
transcode tetikleyen yol) korumasız. `upload_chunk` özellikle kritik: her çağrı
2 MB'a kadar base64 gövde alıyor (`chunked.py:43`, `chunked.py:182`) ve
`MAX_CHUNKS = 256` ile 512 MB'lık oturumlar mümkün (`chunked.py:47`).

`purge_media` de korumasız ve **yıkıcı** bir uç.

Karşılaştırma için: bir yorum göndermek dakikada 5 istekle sınırlı
(`storefront_api.py:280` — `sf_submit_review`), ama 200 MB video yüklemek
sınırsız.

### 6.8 Mevcut rate limit ayarlarının envanteri

Proje içi decorator kullanan tüm uçlar (`grep -rn "@rate_limit"`), referans
olsun diye:

| Dosya:satır | scope | max_calls / window | per_user |
|---|---|---|---|
| `cart.py:1515` | (fonksiyon adı) | 10 / 300 | True |
| `push.py:39` | `push_subscribe` | 5 / 60 | True |
| `mobile_api.py:135` | `mobile_login` | 10 / 60 | **False** |
| `mobile_api.py:145` | `mobile_refresh` | 30 / 60 | **False** |
| `mobile_api.py:183` | `mobile_feed` | 120 / 60 | True |
| `mobile_api.py:211` | `mobile_pending` | 60 / 60 | True |
| `mobile_api.py:232` | `mobile_quick_review` | 20 / 60 | True |
| `review.py:919` | `admin_dismiss_abuse` | 30 / 60 | True |
| `review.py:1216` | `review_abuse_report_direct` | 10 / 300 | True |
| `qa.py:375` | `qa_dismiss_question` | 30 / 60 | True |
| `qa.py:414` | `qa_restore_question` | 30 / 60 | True |
| `qa.py:449` | `qa_delete_answer` | 10 / 60 | True |
| `storefront_api.py:44` | `sf_review_page` | 60 / 60 | True (**guest!**) |
| `storefront_api.py:119` | `sf_review_eligibility` | 30 / 60 | True |
| `storefront_api.py:204` | `sf_my_reviews` | 30 / 60 | True |
| `storefront_api.py:253` | `sf_my_pending_reviews` | 30 / 60 | True |
| `storefront_api.py:265` | `sf_update_review` | 10 / 60 | True |
| `storefront_api.py:280` | `sf_submit_review` | 5 / 60 | True |
| `storefront_api.py:317` | `sf_submit_question` | 5 / 60 | True |
| `storefront_api.py:325` | `sf_update_question` | 10 / 60 | True |
| `storefront_api.py:334` | `sf_submit_answer` | 10 / 60 | True |
| `storefront_api.py:342` | `sf_helpful_vote` | 20 / 60 | True |
| `storefront_api.py:350` | `sf_qa_vote` | 20 / 60 | True |
| `storefront_api.py:359` | `sf_translate` | 10 / 60 | True |
| `storefront_api.py:368` | `sf_abuse_report` | 10 / 300 | True |
| `storefront_api.py:379` | `sf_qa_page` | 60 / 60 | **False** |
| `storefront_api.py:392` | `sf_template` | 60 / 60 | **False** |

Medya: **0 satır.**

Ayrıca `api/rate_limit.py:121-123` — `cleanup_old_records()` bir "scheduled
placeholder" ve no-op. `hooks.py` scheduler bloklarında çağrılıp çağrılmadığı
bu görevde doğrulanmadı; no-op olduğu için önemsiz.

---

## 7. Önerilen medya rate limit değerleri

Görev şartı: "kullanıcı başına dakikada N istek + M MB."

**Bu değerler bir ölçüm sonucu değil.** Türetim yöntemi aşağıda açık yazılıyor;
üretimde §10.6 ile kalibre edilmeli.

### 7.1 İstek limitleri

| Uç | Öneri | Türetim |
|---|---|---|
| `upload_media` | 30 / 60s | `SINGLE_SHOT_LIMIT = 8 MB` (`upload_policy.py:89`) → 30 × 8 MB = 240 MB/dk teorik tavan |
| `upload_begin` | 10 / 60s | Bir oturum en fazla 512 MB (`chunked.py:43,47`); dakikada 10 oturum = 5 GB açık taahhüt, zaten cömert |
| `upload_chunk` | 300 / 60s | `CHUNK_BYTES = 2 MB` × 300 = 600 MB/dk; tek 512 MB oturumun 256 parçasını (`chunked.py:47`) tek dakikada bitirmeye yeter |
| `upload_finish` | 10 / 60s | `upload_begin` ile eşleşir |
| `purge_media` | 10 / 300s | Yıkıcı uç; `review_abuse_report_direct` (`review.py:1216`) ile aynı sıkılık |
| Okuma uçları (`get_my_media`, `get_my_summary`, `get_dimensions`) | 120 / 60s | `mobile_feed` (`mobile_api.py:183`) ile aynı — panel gezinmesi |

### 7.2 Bayt limitleri (M MB/dakika)

İstek sayısı tek başına yetersiz: 30 × 8 MB ile 30 × 100 KB aynı sayılıyor.
Bu yüzden **ikinci bir kova**: kullanıcı başına dakikada toplam bayt.

| Plan | Öneri MB/dk | Türetim |
|---|---|---|
| FREE | 100 | Kotanın (500 MB, `v15_9_17:44`) %20'si — kota 5 dakikada bitirilebilir, daha hızlısı anlamsız |
| STARTER | 250 | Kota 2000 MB (`:42`) → %12,5 |
| PRO / PREMIUM | 500 | Kota 5000 MB (`:40-41`) → %10 |
| ENTERPRISE | 1000 | Kota sınırsız (`:39`); sınır artık kota değil, sunucu kapasitesi |

Formül: `min(kotanın %10-20'si, sunucu kapasitesi)`. Yüzdenin plan büyüdükçe
düşmesi bilinçli — büyük planlar toplam kapasiteden daha büyük dilim aldığı
için mutlak sınır daha yavaş büyüyor.

**Uyarı:** "sunucu kapasitesi" bu görevde ölçülmedi. Video transcode CPU-yoğun
(`transcode.py:52` — ffmpeg 1700 sn timeout) ve `long` kuyruk worker sayısı
bilinmiyor. §10.6'da ölçülmeli; kapasite düşükse yukarıdaki değerler
düşürülmeli.

### 7.3 429 yanıt sözleşmesi

```
HTTP/1.1 429 Too Many Requests
Retry-After: <kovanın kalan TTL'i, saniye>
X-RateLimit-Limit: <max_calls>
X-RateLimit-Remaining: 0
X-RateLimit-Reset: <unix timestamp>

{
  "exc_type": "TooManyRequestsError",
  "_server_messages": "…",
  "message": "Çok fazla yükleme isteği. <N> saniye sonra tekrar deneyin.",
  "code": "rate_limited",
  "retry_after": <saniye>
}
```

Üç kural:

1. **`Retry-After` kovanın kalan TTL'i olmalı**, sabit `window_seconds`
   değil (§6.6).
2. **Türkçe mesaj + makine kodu birlikte.** İstemci koda bakar, kullanıcı
   mesajı okur. Bu desen medya yükleme sözleşmesinde zaten var:
   `upload_policy.Kod` (`upload_policy.py:98-120`) her ret için `(kod,
   retryable)` çifti taşıyor ve `checks.py:273-277` gerekçesi şu: "istemci hata
   METNİNE değil KODA bakarak karar verir". Rate limit reddi de aynı
   sözleşmeye girmeli — bugün girmiyor, `TooManyRequestsError` düz bir
   `ValidationError` alt sınıfı.
3. **`retryable=True`.** Kota reddinin tersine (`upload_policy.py:120` —
   `False`), rate limit reddi geçici; istemci bekleyip tekrar denemeli.
   Bu ayrım `upload_policy.py:94-96`'da tanımlı: "kullanıcının dosyasıyla
   ilgili hatalar tekrar denenmez … geçici sistem hataları denenir."

Bunun için `upload_policy`'ye yeni bir kod eklenmesi öneriliyor:
`RATE_LIMITED = Kod("upload_rate_limited", True)`. Böylece rate limit reddi de
mevcut sözleşmeden geçer ve panel onu diğer retlerle aynı yolda işler.

---

## 8. Şema alan haritası → mevcut kod

| Şema yolu | Varsayılan | Bugün kim uyguluyor |
|---|---|---|
| `storage.total_gb.enabled` | `true` | `checks.py:213` + `hooks.py:236` |
| `storage.total_gb.plan_limits` | FREE 0.5 / STARTER 2 / PRO 5 / ENTERPRISE -1 | `v15_9_17_seed_storage_quota.py:38-44` |
| `storage.total_gb.on_exceed` | `"block"` | `checks.py:278-281` |
| `storage.total_gb.measurement` | `public_dedup_by_url` | `files.py:237-245` |
| `uploads.per_month.enabled` | `false` | **YOK** |
| `jobs.concurrent.enabled` | `false` | **YOK** |
| `video.total_duration_minutes.enabled` | `false` | **YOK** (süre alanı bile yok) |
| `file.max_bytes_per_kind.platform_defaults` | image 25 MB / video 200 MB / doc 50 MB / other 50 MB | `upload_policy.py:67-72` |
| `file.max_bytes_per_kind.plan_overrides` | `{}` | **YOK** — plan zincire girmiyor (`upload_policy.py:264-265`) |
| `enforcement.check_point` | `"both"` | Bugün yalnız `doc_before_insert` (`hooks.py:236`) |
| `enforcement.concurrency_guard.strategy` | `"none"` | Kilitsiz okuma (`checks.py:269`) |
| `scope.count_private` | `false` | `files.py:240` (`is_private=0`) + `checks.py:254-255` |
| `scope.count_trashed` | `false` | **Bugün fiilen `true`** — §4.3, doğrulanmalı §10.4 |
| `scope.count_archive_originals` | `false` | `archive.py:8-9` (`File` kaydı yok) |
| `exemptions.roles` | `["System Manager","Marketplace Admin"]` | `checks.py:241-244` |
| `exemptions.bulk_import` | `true` | `checks.py:249-252` |
| `bulk_import.precheck_total_bytes` | `false` | **YOK** |
| `rate_limit.algorithm` | `"fixed_window_incr"` | Bugün `fixed_window_ttl_reset` (`rate_limit.py:79-82`) |
| `rate_limit.guest_bucket.key_strategy` | `"ip_and_ua"` | Bugün `session_user` → tek "Guest" kovası (`rate_limit.py:53`) |
| `rate_limit.on_backend_failure` | `"fail_open"` | `rate_limit.py:57-69` |
| `rate_limit.response.retry_after_header` | `true` | **YOK** (`rate_limit.py:24-27`) |
| `rate_limit.media_endpoints` | §7.1 tablosu | **YOK** — `seller_media.py`'de 0 decorator |

---

## 9. Uygulama sırası önerisi

Riske göre sıralı; ilk üçü davranış değiştirmeden güvenlik kazandırıyor.

1. **`upload_policy`'ye `RATE_LIMITED` kodu ekle.** Tek satır, hiçbir davranış
   değişmez, ama sonraki adımların sözleşmeye girmesini sağlar.
2. **`rate_limit.py`'de `INCR`+`EXPIRE`'a geç** (§6.4). Kalıcı kilit hatasını
   (§6.3) da düzeltir. Mevcut limit değerleri değişmiyor, davranış **düzeliyor**
   — bugün duvara çarpan kullanıcılar çarpmayı bırakıyor.
3. **`Retry-After` + `X-RateLimit-*` header'ları** (§7.3). Yalnız ekleme.
4. **Medya uçlarına decorator ekle** (§7.1). İlk sürüm cömert değerlerle ve
   `notify_only` davranışıyla; ölçüm (§10.6) sonrası sıkılaştır.
5. **Misafir kovasını IP'ye bağla** (§6.2). nginx `X-Forwarded-For` zinciri
   önce doğrulanmalı (§10.7) — yanlış konumdan okumak IP taklidine kapı açar,
   yani bu adım ölçüm **olmadan** yapılmamalı.
6. **Kota kontrolünü `doc.insert()` öncesine taşı** (§2.2). Mevcut
   `before_insert` kapısı **kalsın** — güvenlik ağı olarak değerli.
7. **`reservation` stratejisi** (§3.3). Yarışı ve §2'yi birlikte çözer, en
   büyük iş.
8. **Bulk import ön-kontrolü** (§4.2).
9. **Yeni metrikler** (aylık yükleme, eşzamanlı iş, video süresi). Her biri
   `notify_only` ile başlar, etkilenen satıcı sayısı ölçülür, sonra `block`.
   Video süresi için önce `th_media_duration_seconds` alanı gerekiyor (§5.3).

Adım 5'in adım 2'den sonra gelmesi önemli: bugünkü TTL-reset hatasıyla IP bazlı
kova, tek IP'nin arkasındaki tüm kurumsal kullanıcıları kalıcı kilitleyebilir.

---

## 10. ÜRETİMDE DOĞRULANMALI

Docker kapalı, üretim veritabanına ve canlı siteye erişim yok. Aşağıdakiler bu
görevde **yapılamadı**. Komutlar `backend` servisi içinde koşacak şekilde
yazıldı; site adı `istoc.localhost` varsayıldı.

### 10.1 Planlarda `quota.max_storage_mb` gerçekten var mı (seed yaması koştu mu)

Kritik: yama koşmadıysa `limit_mb is None` → kota **hiç uygulanmıyor**
(`checks.py:262-263`).

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select name,
       json_unquote(json_extract(quota_limits,'\$.\"quota.max_storage_mb\"')) storage_mb,
       json_unquote(json_extract(quota_limits,'\$.\"quota.max_products\"'))   products
from \`tabSubscription Plan\`
order by name;"

docker compose exec backend bench --site istoc.localhost mariadb -e "
select patch from \`tabPatch Log\` where patch like '%seed_storage_quota%';"
```

**Beklenen:** her plan için dolu bir `storage_mb` ve Patch Log'da bir satır.
`storage_mb` NULL olan plan varsa o plandaki satıcılar için kota kapısı sessizce
kapalı.

### 10.2 Kotayı aşmış satıcı var mı (yarışın kanıtı)

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
from tradehub_core.media import files
from tradehub_core.entitlement.core import get_quota_limits

for store in frappe.get_all("Admin Seller Profile", pluck="name"):
    limit_mb = get_quota_limits(store).get("quota.max_storage_mb")
    if limit_mb is None or int(limit_mb) == -1:
        continue
    used = files.storage_usage(store)["bytes"]
    limit = int(limit_mb) * 1024 * 1024
    if used > limit:
        print(f"AŞIM  {store}: {used/1048576:.1f} MB / {limit_mb} MB "
              f"(+{(used-limit)/1048576:.1f} MB)")
PY
```

**Beklenen:** boş çıktı. Satır varsa aşımın sebebi ya §3'teki yarış, ya
muafiyetlerden biri, ya da kotanın sonradan düşürülmesi. Aşım miktarı tek dosya
üst sınırlarından (`upload_policy.py:67-72`) büyükse yarış tek başına
açıklamıyor demektir.

### 10.3 Private dosyaların ölçülmeyen hacmi (§4.1)

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select is_private,
       count(*) dosya,
       round(sum(file_size)/1048576, 1) mb
from tabFile
where is_folder = 0
group by is_private;"
```

`is_private=1` satırındaki MB, **kotada hiç görünmeyen** hacim. Toplama oranı
yüksekse (örn. %20'nin üzerinde) private muafiyeti ticari bir boşluk
demektir.

Satıcı bazında dağılım:

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select owner, count(*) n, round(sum(file_size)/1048576,1) mb
from tabFile
where is_folder = 0 and is_private = 1
group by owner order by mb desc limit 20;"
```

### 10.4 Çöpe atılan dosya kotadan düşüyor mu (§4.3)

Kod okumasından çıkan iddia: düşmüyor. Doğrulama:

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select count(*) copteki_kayit,
       round(sum(file_size)/1048576,1) mb,
       sum(case when is_private=0 and left(file_url,7)='/files/' then 1 else 0 end)
         kota_sorgusuna_giren
from tabFile
where th_trashed_at is not null and is_folder = 0;"
```

`kota_sorgusuna_giren` > 0 ise iddia doğrulanmış olur: çöpteki dosyalar
`storage_usage` sorgusunun filtrelerini (`files.py:240`) geçmeye devam ediyor,
yani satıcı sildiği hâlde kotası düşmüyor.

### 10.5 Yetim dosya var mı (§2.2)

Diskte olup `tabFile`'da olmayan public dosyalar. Reddedilen yüklemelerin
diskte kalıp kalmadığının kanıtı.

```bash
docker compose exec backend bash -lc '
S=/home/frappe/frappe-bench/sites/istoc.localhost
find $S/public/files -maxdepth 1 -type f -printf "%f\n" | sort > /tmp/disk.txt
wc -l /tmp/disk.txt
'
docker compose exec backend bench --site istoc.localhost mariadb -N -e "
select distinct substring_index(file_url,'/',-1)
from tabFile where is_folder=0 and left(file_url,7)='/files/';" \
  | sort > /tmp/db.txt

# karşılaştırma (aynı kabukta koşturulmalı)
comm -23 /tmp/disk.txt /tmp/db.txt | head -50   # diskte var, DB'de yok
comm -13 /tmp/disk.txt /tmp/db.txt | head -50   # DB'de var, diskte yok
```

İlk liste yetim dosyalar (kotaya sayılmayan ama disk tüketen).
İkinci liste kırık kayıtlar. `du -sh public/files` ile `storage_usage()` toplamı
arasındaki fark bu iki listeyle açıklanmalı.

### 10.6 Rate limit kalibrasyonu — gerçek yükleme davranışı

§7'deki değerler türetim, ölçüm değil. Kalibrasyon için gerçek dağılım gerekiyor.

```bash
# Kullanıcı başına dakikada kaç yükleme oluyor (audit izinden)
docker compose exec backend bench --site istoc.localhost mariadb -e "
select date_format(creation,'%Y-%m-%d %H:%i') dakika,
       count(*) yukleme,
       round(sum(json_unquote(json_extract(context,'\$.bytes')))/1048576,1) mb
from \`tabAuthorization Decision Log\`
where action = 'media.upload'
  and creation > date_sub(now(), interval 30 day)
group by dakika
having yukleme > 5
order by yukleme desc limit 50;"
```

**Not:** audit tablosunun adı `schema.py:33`'teki `FULL_TABLES = ("tabFile",
"tabAuthorization Decision Log")` listesinden çıkarıldı;
`audit.log_media_event`'in gerçekte hangi doctype'a yazdığı doğrulanmalı — bu
görevde `media/audit.py`'nin yalnız action sabitleri (satır 43-68) okundu.

Bu sorgunun **99. yüzdelik** değeri §7.1'deki limitlerin tabanı olmalı: gerçek
tepe kullanımın altında bir limit meşru kullanıcıyı engeller.

Kuyruk kapasitesi:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
from rq import Queue
import frappe
from frappe.utils.background_jobs import get_redis_conn
q = Queue("long", connection=get_redis_conn())
print("long kuyruk derinliği:", len(q))
PY

docker compose exec backend bash -lc 'grep -rn "long" /home/frappe/frappe-bench/Procfile 2>/dev/null; nproc'
```

`long` worker sayısı ve CPU çekirdeği, §7.2'deki "sunucu kapasitesi" tavanını
belirler. ffmpeg tek iş için 1700 sn'ye kadar çalışabiliyor
(`transcode.py:52`); worker sayısı × 60/1700 ≈ dakikada tamamlanabilir iş
sayısıdır.

### 10.7 Misafir kovası için IP zinciri doğrulaması (§6.2 çözümü öncesi)

`X-Forwarded-For`'un hangi konumundan okunacağı yanlışsa IP taklidi mümkün olur.

```bash
# nginx kaç proxy katmanı ekliyor
grep -rn "X-Forwarded-For\|real_ip_header\|set_real_ip_from" \
  /Users/ahmet/Desktop/istoc/docker/nginx/

# Uygulama tarafında ne görülüyor
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
print("remote_addr :", frappe.local.request_ip if hasattr(frappe.local,'request_ip') else "?")
PY
```

Ayrıca canlı bir istekle test edilmeli: sahte `X-Forwarded-For` header'ı
gönderip uygulamanın onu mu yoksa gerçek `remote_addr`'ı mı gördüğüne bakılmalı.
Uygulama sahte değeri görüyorsa **IP bazlı kova IP taklidiyle atlatılabilir** ve
§6.2'deki çözüm o hâliyle uygulanmamalı.

> **Not:** `/Users/ahmet/Desktop/istoc/docker/nginx/` bu görevde okunmadı; grep
> komutu doğrulama için verildi. Ayrıca kardeş MEMORY kaydı ("İstoç sistem
> tasarımı denetimi", 2026-08-16) "prod'a ulaşmamış nginx sertleştirmesi"nden
> söz ediyor — nginx yapılandırmasının prod'da yerel dosyayla aynı olduğu
> **varsayılmamalı**, prod'daki dosya ayrıca okunmalı.

### 10.8 429 gerçekte kaç kez dönüyor (§6.3 kalıcı kilit kanıtı)

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select method, count(*) n, min(creation), max(creation)
from \`tabError Log\`
where error like '%TooManyRequests%'
  and creation > date_sub(now(), interval 7 day)
group by method order by n desc limit 20;"
```

Ve Redis kovalarının canlı durumu — TTL'in sürekli reset olduğunu göstermenin
en doğrudan yolu:

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
import frappe
c = frappe.cache()
try:
    keys = c.get_keys("rl:*")
except Exception as e:
    keys = []
    print("get_keys hatası:", e)
for k in keys[:40]:
    ad = k.decode() if isinstance(k, bytes) else k
    print(ad, "değer=", c.get_value(ad))
PY
```

`rl:*:Guest` deseninde yüksek değerli bir kova görülürse §6.2 doğrulanmış olur:
tüm anonim trafik tek kovada. Aynı kovayı iki kez, 30 saniye arayla okuyup
TTL'in azalmadığını görmek §6.3'ü doğrular (TTL okuması için Redis'e doğrudan
`ttl` çağrısı gerekir; `frappe.cache()` sarmalayıcısı TTL okumayı doğrudan
sunmuyor olabilir — o durumda `docker compose exec redis-cache redis-cli ttl
"<tam anahtar>"` kullanılmalı, tam anahtar Frappe'nin site öneki ile birlikte
yazılmalı).

---

## 11. Kaynak dosya listesi (bu belgeyi yazarken okunanlar)

| Dosya | Okunan aralık | Ne için |
|---|---|---|
| `tradehub_core/entitlement/checks.py` | 1-281 (tamamı) | Kota enforcement, muafiyetler, ret |
| `tradehub_core/entitlement/core.py` | grep: 157-176, 200-225 | `get_quota_limits`, `within_quota` semantiği |
| `tradehub_core/media/files.py` | 225-270 | `storage_usage` SQL'i, `_quota()` |
| `tradehub_core/media/upload_policy.py` | 60-99 + grep: 239-265, 398-426 | `MAX_BYTES`, `SINGLE_SHOT_LIMIT`, `Kod` sözleşmesi, `QUOTA_EXCEEDED` |
| `tradehub_core/media/chunked.py` | grep: 43-51, 133-182 | `CHUNK_BYTES`, `MAX_CHUNKS`, `SESSION_TTL_HOURS` |
| `tradehub_core/media/transcode.py` | 1-60 | Kuyruk stratejisi, `needs_transcode` eşikleri, ffmpeg timeout |
| `tradehub_core/api/seller_media.py` | 245-350 + grep tüm whitelist'ler | Yükleme yolu, rate limit yokluğu |
| `tradehub_core/api/rate_limit.py` | 1-123 (tamamı) | Decorator, kova anahtarı, TTL reset, fail-open, 429 |
| `tradehub_core/api/theme.py` | grep: 13-31, 90-94 | Üçüncü, elle yazılmış rate limit |
| `tradehub_core/api/storefront_api.py` | grep: 43-44, 378-392 | Guest + `per_user` kombinasyonları |
| `tradehub_core/api/mobile_api.py` | grep: 135-232 | `per_user=False` global kovalar |
| `tradehub_core/api/public.py` | grep: 18, 91, 441, 596 | Frappe'nin kendi limiter'ı |
| `tradehub_core/hooks.py` | 92-219, 225-285 | `doc_events["File"]`, scheduler |
| `tradehub_core/patches/v15_9_17_seed_storage_quota.py` | 1-90 | Plan bazlı varsayılanlar |
| `tradehub_core/patches/v15_6_24_promote_enforcement_to_pricing.py` | grep: 32-36 | Mevcut `quota.max_*` anahtarları |
| `tradehub_core/patches/v15_9_1[2-6]_*.py` | grep: `fieldname` | `File` custom alan envanteri (süre alanı yokluğu) |
| `tradehub_core/media/archive.py` | 1-30 | Arşivin `File` kaydı yaratmaması |
| `tradehub_core/media/trash.py` | 30-60, 138-177 | Çöp `file_url` davranışı |
| `tradehub_core/media/schema.py` | 30-35 | Audit tablo adı |
