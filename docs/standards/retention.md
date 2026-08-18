# Medya Saklama (Retention) Politikası Standardı

> Görev: **T-026** · Faz: Medya Motoru Faz 0-2 · Branch: `medya-motoru-faz0-faz2`
> Şema: [`media_engine/policy/retention.schema.json`](../../media_engine/policy/retention.schema.json)
> Yazım tarihi: 2026-08-17

## 0. Bu belgenin kapsamı ve kapsamı dışındakiler

Bu belge **yeni bir saklama sistemi tasarlamıyor**. `tradehub_core/media/` altında
saklama/silme davranışı zaten çalışıyor; bu belge önce onu satır referanslarıyla
belgeliyor, sonra **eksik olan tek şeyi** (konfigüre edilebilirlik + yasal saklama)
şemaya bağlıyor.

Hiçbir mevcut kod dosyası bu görev kapsamında değiştirilmedi. Şema, mevcut sabitlerin
**yerine geçmek üzere** değil, onları **varsayılan değer** olarak alıp üstüne
konfigürasyon katmanı koymak üzere tasarlandı (§6).

**Ölçüm uyarısı:** Docker kapalı, üretim veritabanına ve canlı siteye erişim yok.
Bu belgedeki her sayı ya bir kaynak dosya satırından okundu (dosya:satır verildi) ya
da bir kaynak dosyanın kendi yorumunda "ölçüldü" diye yazılmış bir sayı olarak
**alıntılandı** (o durumda alıntı olduğu açıkça belirtildi). Bu görev kapsamında
hiçbir yeni ölçüm yapılmadı. Ölçüm gerektiren maddeler §9'da.

---

## 1. Mevcut durum: dört ayrı saklama penceresi var

Kod tabanında birbirinden bağımsız **dört** saklama penceresi bulunuyor. Hiçbiri
ortak bir konfigürasyon kaynağından okumuyor; dördü de Python sabiti.

| # | Ne saklanıyor | Sabit | Değer | Tanım yeri | Uygulayan |
|---|---|---|---|---|---|
| 1 | Çöpe taşınan dosya (silme öncesi bekleme) | `TRASH_RETENTION_DAYS` | **30 gün** | `tradehub_core/media/trash.py:31` | `trash.purge_expired()` — `trash.py:268` |
| 2 | Optimizasyon öncesi orijinal (geri alma penceresi) | `ARCHIVE_RETENTION_DAYS` | **30 gün** | `tradehub_core/media/presets.py:38` | `archive.purge_expired()` — `archive.py:113` |
| 3 | Günlük medya yedeği (anlık görüntü seti) | `KEEP_SETS` | **14 set** | `tradehub_core/media/backup.py:385` | `backup.prune(keep=…)` — `backup.py:357` |
| 4 | Dışa aktarma paketi (yedeğin indirilebilir kopyası) | `KEEP_HOURS` | **48 saat** | `tradehub_core/media/backup_export.py:45` | `backup_export.cleanup()` — `backup_export.py:568` |

Dikkat: 1 ve 2 aynı değere (30 gün) sahip ama **iki ayrı sabit**. İkisini birlikte
değiştirmek isteyen bir operatör iki dosyayı düzenlemek zorunda ve ikisinin aynı
kalması gerektiğini hiçbir yer söylemiyor.

### 1.1 Dördü de ayrı fiziksel klasörde duruyor

| Pencere | Disk yolu | `File` kaydı yaratılıyor mu |
|---|---|---|
| Çöp | `<site>/private/media_trash/` — `trash.py:30` + `trash.py:37-38` | Kayıt **silinmez**, `th_trashed_at` damgalanır (`trash.py:156-158`) |
| Arşiv | `<site>/private/image_originals/` — `presets.py:35` + `archive.py:26-27` | **Hayır** — `archive.py:8-9`: "yoksa aynı dosya envanterde iki kez görünür ve depolama raporu bozulur" |
| Yedek | `backup.py` içi set klasörleri (`_set_path`) | İçerik-adresli havuz; kayıtlar ayrı JSON'da (`backup.records_of`) |
| Paket | `backup_export.py` | Yedeğin ikinci kopyası (`backup.py:409-412`) |

Arşivin `File` kaydı yaratmaması **kota açısından kritik**: orijinal arşivi
satıcının depolama kotasına yansımıyor (bkz. `kota.md` §4.3).

---

## 2. Silme davranışı: zaten soft-delete + bekleme + audit

Görev şartı "silme her zaman soft-delete + bekleme + audit" — bu **mevcut kodda
zaten böyle**. Yeniden tasarlanacak bir şey yok, belgelenecek bir şey var.

### 2.1 İki adımlı akış

```
canlı dosya
   │  move_to_trash()            trash.py:138
   │    ├─ _assert_trashable()   trash.py:64   (kapsam + kullanım kapısı)
   │    ├─ th_trashed_at damgası trash.py:156  (File kaydı SİLİNMEZ)
   │    ├─ states.transition(TRASHED) trash.py:160
   │    └─ shutil.move → private/media_trash/  trash.py:162
   ▼
çöp (30 gün)                     TRASH_RETENTION_DAYS = trash.py:31
   │  ├─ restore()               trash.py:179  ← geri alınabilir
   │  └─ purge_expired()         trash.py:268  ← süre dolunca KALICI
   ▼
yok (refs.clear ile bağlar da temizlenir)  trash.py:304
```

`delete_permanently()` (`trash.py:210`) **yalnız çöpteki** dosyaya uygulanabilir;
canlı bir dosyayı tek adımda silmek mümkün değil — `trash.py:213-215`:
"Bu iki adımlı akış, tek bir yanlış tıklamanın geri dönüşü olmayan sonuç
doğurmasını engelliyor."

### 2.2 Silme kapıları — `force` ile aşılabilenler ve aşılamayanlar

`_assert_trashable()` (`trash.py:64-108`) beş kapı uyguluyor:

| Kapı | Kontrol | `force=True` ile aşılabilir mi | Satır |
|---|---|---|---|
| Kayıt var mı | `File` satırı yok → throw | — | `trash.py:78-79` |
| Private dosya | `is_private` → reddet | **Hayır** | `trash.py:80-82` |
| Kapsam dışı doctype | `attached_to_doctype in EXCLUDED_DOCTYPES` → reddet | **Hayır** | `trash.py:83-85` |
| Hassas içerik ikizi | `_has_sensitive_twin(content_hash)` → reddet | **Hayır** | `trash.py:88-94` |
| Kullanımda | `verdict not in {unused, history_only}` → reddet | **Evet** | `trash.py:98-108` |

`trash.py:67-71` gerekçeyi açıkça yazıyor: kapsam engelleri "gizlilik kararı,
kullanıcı tercihi değil". `force` yalnız kullanım engelini kaldırıyor ve o da
kullanıcıya "bu dosya {n} üründe kullanılıyor, görselleri kırılacak" uyarısı
gösterildikten sonra.

`EXCLUDED_DOCTYPES` listesi 8 doctype içeriyor (`presets.py:44-53`): KYB
Verification, KYC Verification, Seller Certification, Seller Verification, Seller
Application, Order, Payment Transaction, Data Export Request.

### 2.3 Audit izi — her silme olayı kaydediliyor

| Olay | Audit action | Nerede yazılıyor |
|---|---|---|
| Çöpe taşıma | `media.trash` (`audit.py:46`) | `trash.py:173-175` — `bytes` + `forced` bayrağı |
| Geri alma | `media.untrash` (`audit.py:47`) | `trash.py:206` |
| Kalıcı silme (tek dosya) | `media.delete` (`audit.py:48`) | `trash.py:235-245` — silinen `File` kayıt adları, temizlenen referanslar |
| Çöp purge (toplu) | `media.purge_trash` (`audit.py:49`) | `trash.py:321-334` — `trigger`, `retention_days`, ilk 50 dosya adı |
| Arşiv purge (toplu) | `media.purge_archive` (`audit.py:50`) | `archive.py:144-152` — `trigger`, `retention_days` |
| Reddedilen silme | `media.scope_denied` (`audit.py:51`) | `trash.py:123-130` |

İki ayrıntı, ikisi de kod yorumunda gerekçeli:

1. **`trigger` alanı** (`trash.py:275-279`): `scheduled` (günlük job, yalnız süresi
   dolanlar) ile `manual` ("Çöpü boşalt" → çöpün TAMAMI hemen) audit'te ayrılıyor.
   Kod yorumu: "Denetim kaydında ikisi aynı olay adıyla görünüyordu ve 'çöp
   temizliği' ifadesi bakım işi gibi okunuyordu."
2. **Hiçbir şey silinmediyse de kayıt atılıyor** (`trash.py:319-320`): "'purge
   çalıştı mı' sorusu denetimden cevaplanabilmeli."

### 2.4 Referans zinciri: silme sadece dosyayı silmiyor

`refs.clear(url)` (`media/refs.py:147`) hem tek dosya silmede (`trash.py:227`) hem
purge'de (`trash.py:304`) çağrılıyor. Davranışı iki türlü (`refs.py:16-23`):

- **Satır silinir** — `ROW_OWNED_TABLES` (`refs.py:34-36`): `tabListing Image`,
  `tabListing Variant Item`, `tabSeller Gallery Image`. Gerekçe: "görsel gidince
  satırın varlık sebebi kalmıyor".
- **Alan boşaltılır** — diğerleri (örn. `Listing.primary_image`).
- **Hiç dokunulmaz** — `READONLY_TABLES` (`refs.py:38-42`), yani sipariş kaynakları:
  "Referansı silmek geçmişi değiştirmek olur — yalnız raporlanır."

---

## 3. "Kullanılmadı" tam olarak ne demek

Görev şartı: `"Kullanılmadı" tanımını netleştir.` Mevcut kodda tanım
`media/usage.py`'de ve **veritabanı taramasına dayanıyor**.

### 3.1 Dört karar etiketi

`usage.py:61` — `VERDICTS = ("in_use", "order_only", "history_only", "unused")`

| Etiket | Anlamı | Çöpe taşınabilir mi |
|---|---|---|
| `in_use` | En az bir CANLI kaynakta geçiyor | **Hayır** (yalnız `force` ile) |
| `order_only` | Sadece sipariş/sepet anlık görüntüsünde geçiyor | **Hayır** |
| `history_only` | Sadece geçmiş/log tablolarında geçiyor | Evet |
| `unused` | Hiçbir taranan kaynakta geçmiyor | Evet |

`trash.py:34` — `TRASHABLE_VERDICTS = frozenset({"unused", "history_only"})`.
`in_use` için `trash.py:33` gerekçe veriyor: "asla — sitede kırılma yaratır".
`order_only`'nin de dışta kalması bilinçli: `refs.py:38-42` sipariş kaynaklarını
"geçmiş siparişin delili" sayıyor.

### 3.2 Taranan kaynaklar — 16 (tablo, kolon) çifti

**CANLI** — 8 çift (`usage.py:32-42`): silinirse sitede bir şey kırılır.

| Tablo | Kolon | Etiket |
|---|---|---|
| `tabListing` | `primary_image` | Ana görsel |
| `tabListing` | `video_url` | Video |
| `tabListing Image` | `image` | Galeri |
| `tabListing Variant Item` | `variant_image` | Varyant görseli |
| `tabListing Variant Item` | `variant_gallery` | Varyant galerisi |
| `tabStorefront Layout` | `sections` | Vitrin düzeni (JSON blob) |
| `tabSeller Gallery Image` | `image` | Satıcı galerisi |
| `tabAdmin Seller Profile` | `logo` | Mağaza logosu |

**SİPARİŞ** — 2 çift (`usage.py:46-49`): `tabCart Item.snapshot_image`,
`tabOrder.receipt_url`.

**GEÇMİŞ** — 6 çift (`usage.py:52-59`): `tabVersion.data`,
`tabDeleted Document.data`, `tabComment.content`,
`tabBulk Import Job Error.raw_row_json`, `tabBulk Import Job.data_file`,
`tabError Log.error`.

Toplam = 8 + 2 + 6 = **16 çift**. (Sayım bu görevde `usage.py:32-59` satırlarından
elle yapıldı.)

> **Belgeleme tutarsızlığı — düzeltilmedi, raporlanıyor.** Üç ayrı yerde üç farklı
> sayı yazılı: `usage.py:7-8` "görsel URL'i geçen 23 alan var", `archive.py:5`
> "22 alandaki referanslar", kodda sınıflanmış çift sayısı ise 16. Hangisinin doğru
> olduğu bu görevde belirlenemez — `information_schema` taraması üretim
> veritabanı gerektiriyor. Doğrulama komutu §9.4'te.

### 3.3 Bu tanımın bilinen dört boşluğu

Dördü de kaynak dosyalarda yazılı; hiçbiri benim çıkarımım değil.

1. **Frontend'de sabit yazılmış görseller taramada görünmez.**
   `trash.py:10-13`: "'kullanılmıyor' taraması yalnız veritabanını kapsıyor.
   Frontend kodunda sabit yazılmış ya da dışarıdan link verilmiş bir görsel
   taramada 'kullanılmıyor' görünür ama sitede kırılır." Çöp kutusunun 30 günlük
   penceresi tam olarak bu hatayı geri alınabilir kılmak için var.

2. **JSON blob'larda kaçışlı yazım.** `usage.py:71-79`: `Storefront Layout.sections`
   JSON'unda Türkçe karakterli adlar kaçışlı duruyordu ve "yalnız ham yazım
   arandığı sürece o satır hiç GETİRİLMİYORDU — dolayısıyla Türkçe adlı vitrin
   görselleri 'kullanılmıyor' görünüp silme adayı oluyordu." Düzeltildi
   (`_search_variants`), ama benzer bir kodlama farkı yeni bir blob alanında
   tekrarlanabilir.

3. **Frappe soft-delete yapmıyor.** `usage.py:18-20`: silinen kayıt
   `Deleted Document`'a taşınıyor; bu yüzden `history_only` ayrı bir kategori.

4. **Derin tarama opsiyonel.** `trash.py:101` — `usage.verdict_map_all(deep=True)`
   silme kapısında derin tarama istiyor; panel listeleme yolunun aynı derinlikte
   tarayıp taramadığı bu görevde doğrulanmadı.

### 3.4 Şemadaki "kullanılmadı" tanımı

Şema `derivative_retention.unused_definition` altında bu tanımı **açıkça yazılı ve
sürümlü** hâle getiriyor:

- `sources`: hangi (tablo, kolon) çiftleri taranıyor — `usage.py`'deki üç listeden
  türetilir, ikinci bir kopya tutulmaz (`schema.py:22-23`'ün aynı gerekçesi).
- `verdicts_considered_unused`: hangi etiketler "kullanılmadı" sayılır
  (varsayılan: `["unused", "history_only"]` — `trash.py:34` ile aynı).
- `deep_scan_required`: `true` (varsayılan) — `trash.py:101` ile aynı.
- `grace_days_after_last_reference`: bir dosyanın son referansı **kalktıktan
  sonra** kaç gün beklenecek. Bu alan mevcut kodda **yok**: bugün referans kalkar
  kalkmaz dosya silme adayı oluyor.
- `frontend_scan_completed`: `false` (varsayılan). §3.3/1'deki boşluğun makinece
  okunabilir işareti; `true` yapılmadıkça otomatik silme politikası
  `action: "delete"` ile çalıştırılmamalı.

---

## 4. Zamanlanmış görevler: hangileri günlük çalışıyor

`tradehub_core/hooks.py:92-219` — `scheduler_events`.

### 4.1 Medya ile ilgili günlük görevler (`hooks.py:127` `"daily"` bloğu)

| Sıra | Görev | Satır | Ne yapıyor |
|---|---|---|---|
| 1 | `tradehub_core.media.archive.purge_expired` | `hooks.py:131` | 30 günü dolan orijinal arşivini siler |
| 2 | `tradehub_core.media.trash.purge_expired` | `hooks.py:133` | 30 günü dolan çöp dosyalarını + `File` kayıtlarını kalıcı siler |
| 3 | `tradehub_core.media.backup.run_scheduled` | `hooks.py:138` | Günlük yedek alır, sonra `prune(keep=14)` çalıştırır, sonra `backup_export.cleanup()` |

`hooks.py:127-138`'deki sıra listedeki sıra; bunların **hangi saatte** ve **hangi
sırayla** gerçekten koştuğu Frappe scheduler'ının işi ve bu görevde
doğrulanamadı (§9.1).

### 4.2 Medya dışı ama saklamayla ilgili günlük görevler

| Görev | Satır | Not |
|---|---|---|
| `tradehub_core.audit.tasks.run_data_retention_enforcement` | `hooks.py:189` | KVKK veri saklama; sıcak pencere `audit/tasks.py:32-34` → karar logu 90 gün, rol değişikliği 365, override 365 |
| `tradehub_core.audit.tasks.cleanup_expired_data_exports` | `hooks.py:190` | Dışa aktarma temizliği |
| `tradehub_core.privacy.account_deletion.anonymize_pending_deletions` | `hooks.py:192` | KVKK Md.7 — hesap silme sonrası 30 gün geçen PII anonimleştirme |

`tradehub_core/audit/__init__.py:23` şunu yazıyor: "Retention: 90 gün sıcak
(Frappe DB), 10 yıl arşiv (S3/MinIO — Faz 3'te encryption)." **S3/MinIO tarafı
kodda yok** — bkz. §5.3.

### 4.3 `weekly_long` bloğundaki arşivleme görevleri

`hooks.py:212-215`: `archive_old_role_change_logs`, `archive_old_override_logs`,
`weekly_audit_summary`. Bunlar medya dosyası değil audit satırı arşivliyor; medya
saklama politikasının kapsamı dışında ama aynı takvimde yaşıyorlar.

### 4.4 `backup.run_scheduled` içindeki sıra kararı

`backup.py:390-397`: "Sıra önemli: ÖNCE yedek alınır, SONRA eskiler temizlenir.
Tersi olsaydı temizlik başarılı, yedek başarısız olduğunda elde daha az yedek
kalırdı." Yedek alınamazsa `prune` **hiç çalışmıyor** (`backup.py:398-407` —
`raise` var). Bu doğru davranış ve şemada `on_backup_failure: "skip_purge"`
varsayılanı olarak korunuyor.

`backup.py:409-419`: `backup_export.cleanup()` aynı fonksiyona bağlanmış ("ikisi
de aynı deponun yerini yönetiyor") ve hatası yutuluyor ("Paket temizliği yedeği
düşürmemeli").

---

## 5. Eksikler — kapatılması gereken beş boşluk

Görev tanımı: "Eksik olan: bunlar SABİT, konfigüre edilebilir değil." Doğru, ama
tek eksik o değil. Beşi aşağıda; hepsi şemada karşılığı olan alanlarla eşleşiyor.

### 5.1 Hiçbir saklama süresi konfigüre edilemiyor

Dört pencerenin dördü de Python sabiti (§1). Değiştirmek için:

- kod düzenlemesi,
- deploy,
- (imaj tabanlı kurulumda) imaj rebuild

gerekiyor. Bir DocType alanı, `Marketplace Settings` girdisi ya da site config
anahtarı **yok**. Doğrulama: `presets.py:38`, `trash.py:31`, `backup.py:385`,
`backup_export.py:45` — dördü de `Final[int]` / düz `int` sabiti; hiçbirinde
`frappe.db.get_single_value` / `frappe.conf` okuması yok.

Fonksiyon imzaları buna **hazır**: `trash.purge_expired(retention_days=…)`
(`trash.py:268-270`) ve `archive.purge_expired(retention_days=…)`
(`archive.py:113-115`) parametre kabul ediyor, sabit yalnız **varsayılan değer**.
Yani konfigürasyon katmanı eklemek çağrı yerini değiştirmek demek, mantığı
değiştirmek değil. Bu, şemanın uygulanabilirliği açısından iyi haber.

### 5.2 `legal_hold` diye bir şey yok

Görev şartı: "legal_hold=1 olan varlık hiçbir politikayla silinemez."

Bu görevde tüm repo tarandı (`grep -rniI "legal_hold\|legalhold\|litigation\|yasal saklama"`
→ **0 eşleşme**, `tradehub_core/` altında). `File` üzerindeki tüm custom
alanlar da tarandı; medya yamalarının eklediği 12 alan şunlar:

| Alan | Yama |
|---|---|
| `th_optimized_at`, `th_original_size` | `patches/v15_9_12_media_optimize_fields.py` |
| `th_trashed_at` | `patches/v15_9_13_media_trash_field.py` |
| `th_media_state` | `patches/v15_9_14_media_state_field.py` |
| `th_media_title`, `th_media_alt`, `th_media_description`, `th_media_tags`, `th_media_favorite`, `th_media_width`, `th_media_height` | `patches/v15_9_15_media_metadata_fields.py` |
| `th_media_video_status` | `patches/v15_9_16_media_video_status.py` |

`legal_hold` yok. Bugün yasal saklama gereken bir dosyayı korumanın **tek**
dolaylı yolu, onu `EXCLUDED_DOCTYPES`'a bağlı bir belgeye eklemek ya da private
yapmak (`trash.py:80-85`) — ikisi de yasal saklama için tasarlanmamış araçlar ve
ikisi de dosyanın erişilebilirliğini değiştiriyor.

**Şemadaki karşılığı:** `legal_hold` üst düzey bir nesne, hem
`original_retention` hem `derivative_retention` üzerinde **koşulsuz üstünlük**
taşıyor. Şema bunu `overrides_all_policies: true` (`const`, değiştirilemez) ile
kodluyor: bir uygulama bu şemayı okuyup `legal_hold` kontrolünü atlarsa şemaya
uymamış olur.

Uygulamada karşılığı `_assert_trashable`'a **altıncı kapı** eklemek olur ve o kapı
`force` ile aşılamayanlar grubuna girer — `trash.py:67-71`'in "gizlilik kararı,
kullanıcı tercihi değil" mantığının aynısı yasal saklama için de geçerli.

### 5.3 Katmanlı depolama (S3 standard / cold) hiç yok

Şema `then: "s3_standard" | "s3_cold" | "delete"` seçeneklerini tanımlıyor. Bugün
kodda **yalnız `delete` ve `keep_forever` uygulanabilir**.

Kanıt: `tradehub_core/` altında `boto3`, `s3_bucket`, `aws_access`, `minio`
geçen **tek** satır `audit/__init__.py:23` ve o da bir yorum ("10 yıl arşiv
(S3/MinIO — Faz 3'te encryption)"). `requirements.txt` üç satır:
`defusedxml>=0.7`, `scikit-learn>=1.3` ve bir yorum — S3 istemcisi yok.

Bütün saklama bugün **tek yerel diskte**: `frappe.get_site_path("private", …)`
(`trash.py:38`, `archive.py:27`).

**Şema bunu gizlemiyor**, işaretliyor: her `then` seçeneğinin yanında
`implementation_status` alanı var (`implemented` | `not_implemented`). `s3_standard`
ve `s3_cold` için varsayılan `not_implemented`. Bir politika `not_implemented` bir
hedefi seçerse yükleyicinin **reddetmesi** gerekir — sessizce `delete`'e düşmek en
tehlikeli davranış olurdu.

### 5.4 Türev (derivative) diye bir varlık henüz üretilmiyor

Bu, şemanın en çok yanlış anlaşılabilecek kısmı, o yüzden açık yazıyorum:

**Bu kod tabanı türev dosya üretmiyor.** Hem görsel hem video yolu **dosyanın
üstüne yazıyor**:

- Görsel optimizasyonu: `archive.py:4-6` — "dosyanın üstüne yazıyoruz ama
  orijinali **süreli** saklıyoruz. `file_url` değişmediği için … referanslar
  kırılmaz."
- Video transcode: `transcode.py:26-29` — "diskteki dosyanın YERİNE yazar
  (`file_url` sabit kalır — `Listing` gibi referanslar kırılmaz)".
- `media/engine.py`'de `im.thumbnail(...)` çağrıları var (`engine.py:117`,
  `engine.py:177`) ama bunlar **aynı dosyayı küçültmek** için; ayrı bir çıktı
  dosyası + ayrı `file_url` üretilmiyor. `thumbnail_url` repoda hiç geçmiyor
  (bu görevde arandı, 0 eşleşme).

Sonuç: `derivative_retention` bugün **boş kümeye** uygulanır. Şemaya girmesinin
sebebi, türev üreten bir boru hattı (responsive `srcset`, WebP/AVIF varyantları,
video renditions) geldiğinde politikanın **önce** tanımlı olması. Bu belge onu
"mevcut davranış" gibi sunmuyor.

Şema bunu `derivative_retention.pipeline_status` alanıyla kodluyor; varsayılan
`"absent"` ve şu üç değeri alabiliyor: `absent` | `in_place_overwrite` |
`separate_artifacts`. Bugünkü kod `in_place_overwrite`'a en yakın ama ayrı bir
türev **varlığı** olmadığı için `absent` doğru cevap.

### 5.5 Silme "önce DB sonra disk" — kısmi başarısızlık penceresi

`trash.move_to_trash` DB yazmasını ve disk taşımasını tek `try` içinde
sarmalayıp hatada `frappe.db.rollback()` çağırıyor (`trash.py:153-168`), yorumda
gerekçe var: "Önce DB, sonra disk: disk hatasında rollback ile ikisi tek işleme
bağlanır."

Ama `purge_expired` (`trash.py:293-316`) ve `delete_permanently`
(`trash.py:229-232`) için aynı garanti yok: `frappe.delete_doc` döngüsü ve
`os.remove` arasında kesinti olursa kayıt gitmiş, dosya kalmış olabilir (ya da
tersi — `purge_expired` önce `refs.clear`, sonra `delete_doc`, sonra `os.remove`
yapıyor). `purge_expired` her dosya için `except Exception: … continue`
(`trash.py:312-316`) uyguladığı için döngü devam ediyor, yani kısmi durum sessizce
kalıcı olabiliyor.

**Şemadaki karşılığı:** `orphan_reconciliation` nesnesi — diskte olup DB'de
olmayan (ve tersi) kayıtları bulan periyodik uzlaştırma görevi tanımlıyor.
`refs.find_dangling()` (`refs.py:19`, "hedefi olmayan referansları tarar") zaten
yarısını yapıyor; şema bunun **zamanlanmış** olmasını ve karşı yönü de
kapsamasını istiyor. Bugün `hooks.py` scheduler bloklarında `find_dangling`
çağrısı **yok** (bu görevde `hooks.py:92-219` tarandı).

---

## 6. Politika modeli: iki bağımsız politika + bir üstünlük kuralı

Şema üç üst düzey nesne tanımlıyor. İlk ikisi **bağımsız** — biri diğerini
etkilemiyor. Üçüncüsü ikisini de eziyor.

```
retention_policy
├── original_retention        ← orijinal varlık (yüklenen dosyanın kendisi)
│   ├── keep_forever: true    ← VARSAYILAN. Değiştirilmesi bilinçli karar olmalı.
│   ├── local_days: null
│   ├── then: "delete" | "s3_standard" | "s3_cold"
│   └── legal_hold_overrides: true (const)
│
├── derivative_retention      ← türev varlıklar (bugün: boş küme, §5.4)
│   ├── unused_after_days: 90
│   ├── action: "delete" | "s3_cold" | "notify_only"
│   ├── regenerate_on_demand: true
│   ├── always_keep_profiles: []
│   └── unused_definition {…} ← §3.4
│
└── legal_hold                ← her ikisini de ezer
    ├── field: "th_legal_hold"
    ├── overrides_all_policies: true (const)
    └── audit_action: "media.legal_hold_block"
```

### 6.1 `original_retention` — varsayılan SÜRESİZ

Görev şartı: "orijinal varsayılan olarak SÜRESİZ saklanır."

Şemada `keep_forever` varsayılanı `true` ve `local_days` varsayılanı `null`.
`keep_forever: true` iken `local_days` ve `then` **anlamsız**; şema bunu
`if/then/else` ile zorluyor: `keep_forever: false` ise `local_days` (integer ≥ 1)
ve `then` **zorunlu** alan oluyor. Böylece "süresiz saklamayı kapattım ama ne
kadar sonra ne yapılacağını yazmadım" durumu şema düzeyinde imkânsız.

Bu, mevcut koddaki gerçek davranışla da uyumlu: orijinal dosya (arşivdeki
optimizasyon-öncesi kopya değil, **canlı dosyanın kendisi**) hiçbir zamanlanmış
görev tarafından silinmiyor. `hooks.py:127-192` günlük bloğunda canlı medya
dosyasını silen tek yol `trash.purge_expired` ve o da **yalnız daha önce elle
çöpe taşınmış** dosyalara dokunuyor (`trash.py:281-293` — sadece
`private/media_trash/` altında geziyor).

Yani bugünkü fiilî politika `keep_forever: true` + "silme yalnız kullanıcı
eylemiyle başlar". Şema bunu yazıya geçiriyor.

### 6.2 `derivative_retention` — `unused_after_days = 90`

Görev şartı gereği varsayılan 90 gün. Bu sayının **kaynağı bu görev tanımıdır**,
bir ölçüm değil — kod tabanında 90 günlük bir medya penceresi yok (`audit/tasks.py:32`
`_HOT_DAYS_DECISION = 90` audit satırları için, medya için değil). Şemada bu
`x-provenance` alanıyla açıkça işaretli.

`action` üç değer alıyor: `delete` | `s3_cold` | `notify_only`. Varsayılan
`notify_only` seçildi — türev boru hattı yokken (§5.4) `delete` varsayılanı
sıfır faydayla sıfır olmayan risk taşır.

`always_keep_profiles[]`: hiçbir koşulda silinmeyecek türev profilleri (örn.
`"thumb_320"`, `"card_640"` — LCP yolu üzerindeki boyutlar). Boş dizi varsayılan,
çünkü bugün profil adı diye bir şey yok.

`regenerate_on_demand: true`: silinen türev, ilk istekte orijinalden yeniden
üretilebiliyorsa silme "kayıp" değil, "cache tahliyesi" olur. Bu bayrak `true`
değilse `action: "delete"` **veri kaybı** demektir ve şema o kombinasyonu
uyarı olarak işaretliyor (`x-requires-review`).

### 6.3 `legal_hold` — koşulsuz üstünlük

- `overrides_all_policies` bir `const: true`. Şemaya uyan hiçbir konfigürasyon
  bunu kapatamaz.
- `field` varsayılanı `"th_legal_hold"` — mevcut `th_*` isimlendirme deseniyle
  tutarlı (§5.2 tablosu).
- `applies_to`: `["original", "derivative", "trash", "archive", "backup"]` —
  yasal saklama **çöpteki** dosyayı da korumalı. Bugün `purge_expired`
  (`trash.py:293`) diskte dolaşıp mtime'a bakıyor, hiçbir `File` alanını
  okumuyor; yani legal hold eklendiğinde purge'un dosya→kayıt yönünde sorgu
  yapması gerekecek. Bu, uygulama maliyeti olan bir ayrıntı ve şemanın
  `applies_to` listesinde `trash` bulunması onu gizlemek yerine görünür kılıyor.
- `audit_action: "media.legal_hold_block"` — `audit.py:43-68`'deki
  `media.*` deseniyle tutarlı yeni bir action adı. Engellenen her silme
  girişimi kayda geçmeli; `trash.py:111-130`'daki `_deny` deseni aynen
  kullanılabilir.

### 6.4 Şemanın **yapmadığı** şey

Şema bir uygulama değil. Onu okuyup uygulayacak kod henüz yazılmadı. Şema:

- mevcut sabitleri **varsayılan** olarak taşıyor (`trash_retention_days: 30`,
  `archive_retention_days: 30`, `backup_keep_sets: 14`, `export_keep_hours: 48`)
  ki ilk uygulama davranış değişikliği getirmesin;
- her alanda `x-current-implementation` ile "bugün bunu kim uyguluyor" bilgisini
  taşıyor (dosya:satır) — böylece uygulayan geliştirici hangi çağrı yerini
  değiştireceğini şemadan okuyabilir;
- uygulanmamış hedefleri `not_implemented` diye işaretliyor (§5.3).

---

## 7. Şema alan haritası → mevcut kod

| Şema yolu | Varsayılan | Bugün kim uyguluyor |
|---|---|---|
| `original_retention.keep_forever` | `true` | Fiilî davranış; açık bir sabit yok (§6.1) |
| `original_retention.local_days` | `null` | — |
| `original_retention.then` | `"delete"` | `trash.purge_expired` → `trash.py:268` (yalnız `delete`) |
| `original_retention.legal_hold_overrides` | `true` (const) | **YOK** (§5.2) |
| `derivative_retention.unused_after_days` | `90` | **YOK** — türev yok (§5.4) |
| `derivative_retention.action` | `"notify_only"` | **YOK** |
| `derivative_retention.regenerate_on_demand` | `true` | **YOK** |
| `derivative_retention.always_keep_profiles` | `[]` | **YOK** |
| `derivative_retention.unused_definition.verdicts_considered_unused` | `["unused","history_only"]` | `trash.py:34` |
| `derivative_retention.unused_definition.deep_scan_required` | `true` | `trash.py:101` |
| `derivative_retention.unused_definition.grace_days_after_last_reference` | `0` | **YOK** (§3.4) |
| `soft_delete.trash_retention_days` | `30` | `trash.py:31` |
| `soft_delete.archive_retention_days` | `30` | `presets.py:38` |
| `soft_delete.require_two_step` | `true` | `trash.py:210-215` |
| `soft_delete.clear_references_on_delete` | `true` | `trash.py:227`, `trash.py:304` |
| `soft_delete.readonly_reference_tables` | `["tabCart Item","tabOrder"]` | `refs.py:38-42` |
| `soft_delete.audit_required` | `true` | `trash.py:173`, `321`; `archive.py:144` |
| `backup.keep_sets` | `14` | `backup.py:385` |
| `backup.export_keep_hours` | `48` | `backup_export.py:45` |
| `backup.on_backup_failure` | `"skip_purge"` | `backup.py:398-407` |
| `legal_hold.*` | — | **YOK** (§5.2) |
| `orphan_reconciliation.*` | `enabled: false` | Kısmen: `refs.find_dangling()` (`refs.py:19`), zamanlanmış değil (§5.5) |

---

## 8. Uygulama sırası önerisi

Riski en aza indiren sıra; her adım bağımsız olarak geri alınabilir.

1. **`th_legal_hold` custom alanı** — yeni yama, `patches/v15_9_13_media_trash_field.py`
   deseninin aynısı. Tek başına hiçbir davranışı değiştirmez.
2. **`_assert_trashable`'a altıncı kapı** — `trash.py:64` içine, `force` ile
   aşılamayanlar grubuna. `_deny(file_url, "legal_hold")` ile audit'e yazar.
3. **`purge_expired`'a legal hold kontrolü** — `trash.py:293` döngüsünde her
   dosya için `File` sorgusu. Bu, döngüye N sorgu ekliyor; `frappe.get_all` ile
   toplu ön-yükleme yapılması gerekir (purge şu an hiç `File` okumuyor, §6.3).
4. **Konfigürasyon okuyucusu** — şemayı okuyup `retention_days` parametrelerini
   `hooks.py` çağrı yerlerine geçiren ince katman. Fonksiyon imzaları hazır
   (§5.1).
5. **`orphan_reconciliation` görevi** — `refs.find_dangling()` + karşı yön,
   `weekly_long` bloğuna.
6. **Türev politikası** — ancak türev boru hattı geldiğinde. Önce
   `pipeline_status` alanı `separate_artifacts` olur, sonra politika etkinleşir.

Adım 3 ve 4 arasındaki sıra önemli: konfigürasyon önce gelirse, süreleri
kısaltmak legal hold korumasından **önce** mümkün olur.

---

## 9. ÜRETİMDE DOĞRULANMALI

Aşağıdaki maddeler ölçüm gerektiriyor ve bu görevde **yapılamadı**: Docker kapalı,
üretim veritabanına ve canlı siteye erişim yok. Her madde için çalıştırılacak tam
komut veriliyor. Komutlar `docker/docker-compose.yml` ile ayağa kalkmış bir ortamda
`backend` servisi içinde koşacak şekilde yazıldı; site adı `istoc.localhost`
varsayıldı — gerçek site adıyla değiştirin.

### 9.1 Günlük scheduler görevleri gerçekten koşuyor mu

`hooks.py:127-138` üç medya görevi tanımlıyor. Tanımlı olmak koşmak değil.

```bash
# Scheduler açık mı
docker compose exec backend bench --site istoc.localhost doctor

# Son 7 günde medya purge görevleri koştu mu ve ne kadar sürdü
docker compose exec backend bench --site istoc.localhost mariadb -e "
select scheduled_job_type, status, count(*) n,
       min(creation) ilk, max(creation) son
from \`tabScheduled Job Log\`
where scheduled_job_type like '%media%'
  and creation > date_sub(now(), interval 7 day)
group by scheduled_job_type, status
order by scheduled_job_type;"
```

**Beklenen:** `archive.purge_expired`, `trash.purge_expired`,
`backup.run_scheduled` için günde birer `Complete` satırı. `Failed` satırı varsa
ilgili `Error Log` kaydı okunmalı. Hiç satır yoksa scheduler duruyor demektir ve
o durumda çöp **hiç boşalmıyor** — depolama raporu bu yüzden şişmiş olabilir.

### 9.2 Purge audit izi — kaç dosya, kaç bayt

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select action,
       json_unquote(json_extract(context,'\$.trigger'))       trigger_,
       json_unquote(json_extract(context,'\$.retention_days')) gun,
       json_unquote(json_extract(context,'\$.deleted'))        silinen,
       json_unquote(json_extract(context,'\$.freed_bytes'))    bayt,
       creation
from \`tabAuthorization Decision Log\`
where action in ('media.purge_trash','media.purge_archive')
order by creation desc limit 30;"
```

**Not:** Tablo adı `schema.py:33`'te `FULL_TABLES = ("tabFile", "tabAuthorization
Decision Log")` olarak geçtiği için audit satırlarının bu tabloda tutulduğu
varsayıldı. `audit.log_media_batch`'in gerçekte hangi doctype'a yazdığı
`media/audit.py` içinde doğrulanmalı — bu görevde `audit.py`'nin yalnız action
sabitleri (satır 43-68) okundu, yazma hedefi okunmadı.

### 9.3 Dört saklama alanının gerçek disk boyutu

```bash
docker compose exec backend bash -lc '
S=/home/frappe/frappe-bench/sites/istoc.localhost
du -sh $S/private/media_trash     2>/dev/null || echo "media_trash yok"
du -sh $S/private/image_originals  2>/dev/null || echo "image_originals yok"
du -sh $S/public/files             2>/dev/null
df -h $S | tail -1
'
```

Kodun kendi ölçüm fonksiyonlarıyla karşılaştırılabilir: `trash.usage_bytes()`
(`trash.py:254`) ve `archive.usage_bytes()` (`archive.py:98`).

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
from tradehub_core.media import trash, archive
print("trash  :", trash.usage_bytes())
print("archive:", archive.usage_bytes())
PY
```

**Neden iki yoldan:** `du` sembolik linkleri ve sparse dosyaları farklı sayabilir;
iki sonuç ayrışıyorsa `usage_bytes`'ın `except OSError: continue`
(`trash.py:263-264`, `archive.py:108-109`) ile sessizce atladığı dosyalar var
demektir.

### 9.4 "Görsel URL'i geçen alan" sayısı gerçekte kaç (§3.2 tutarsızlığı)

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select table_name, column_name, column_type
from information_schema.columns
where table_schema = database()
  and (column_name like '%image%' or column_name like '%logo%'
       or column_name like '%photo%' or column_name like '%video%'
       or column_name like '%receipt%' or column_name like '%file%'
       or column_name like '%attach%')
order by table_name, column_name;"
```

Sonuç `usage.py:32-59`'daki 16 çiftle karşılaştırılmalı. Listede olmayan ve
gerçekten medya URL'i tutan bir kolon varsa **o kolondaki dosyalar bugün
"kullanılmıyor" görünüyor** — yani silme adayı. Bu, §3.3/1'deki riskin somut
hâli.

### 9.5 Çöpte 30 günü aşmış ama hâlâ duran dosya var mı

```bash
docker compose exec backend bash -lc '
find /home/frappe/frappe-bench/sites/istoc.localhost/private/media_trash \
  -type f -mtime +30 -printf "%TY-%Tm-%Td  %10s  %p\n" | sort | head -50
'
```

**Beklenen:** boş çıktı. Satır varsa `purge_expired` ya koşmuyor (§9.1) ya da
`except Exception: … continue` (`trash.py:312-316`) ile o dosyalarda sessizce
başarısız oluyor; ikinci durumda `Error Log`'da `title="Trash purge failed"`
kayıtları aranmalı.

### 9.6 `th_trashed_at` damgası ile disk durumu örtüşüyor mu

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select count(*) damgali_kayit
from tabFile where th_trashed_at is not null;"
```

Sonuç, §9.5'teki `find … -type f | wc -l` sayısıyla karşılaştırılmalı.
`trash.py:158-160` ikisinin aynı transaction'da yazıldığını iddia ediyor
("ayrışmaları imkânsız (TUR-138)"); sayılar farklıysa bu iddia üretimde
tutmuyor demektir ve §5.5'teki kısmi başarısızlık penceresi gerçekleşmiş olur.

### 9.7 Yedek set sayısı 14'ü aşıyor mu

```bash
docker compose exec backend bench --site istoc.localhost console <<'PY'
from tradehub_core.media import backup
setler = backup.list_sets()
print("set sayısı:", len(setler), "/ KEEP_SETS =", backup.KEEP_SETS)
for s in setler[:20]:
    print(s.get("set_id"))
PY
```

14'ten fazlaysa `prune` çalışmıyor — muhtemelen `snapshot` başarısız olup
`raise` ettiği için (`backup.py:398-405`), yani zincir hiç `prune`'a
gelmiyor. `Error Log`'da `title="Medya yedegi alinamadi"` aranmalı.

### 9.8 Legal hold ihtiyacı olan dosya var mı (politika kararı için girdi)

Bu bir kod ölçümü değil, **iş kararı** girdisi. Ölçülecek şey: `EXCLUDED_DOCTYPES`
kapsamındaki 8 doctype'a bağlı kaç dosya var ve bunların kaçı `is_private=0`.

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select attached_to_doctype, is_private, count(*) n, sum(file_size) bayt
from tabFile
where attached_to_doctype in ('KYB Verification','KYC Verification',
      'Seller Certification','Seller Verification','Seller Application',
      'Order','Payment Transaction','Data Export Request')
group by attached_to_doctype, is_private
order by n desc;"
```

Ayrıca `presets.py:56-76`'daki **ters referans** riski ölçülmeli — o yorum canlı
DB'de doğrulanmış iki sayı veriyor (`Seller Application.identity_document` 144
dosya, `Seller Certification.document` 2 dosya, ikisinde de
`attached_to_doctype` BOŞ). Bu sayılar **o yorumdan alıntı**, bu görevde
ölçülmedi; hâlâ geçerli olup olmadığı şu sorguyla kontrol edilir:

```bash
docker compose exec backend bench --site istoc.localhost mariadb -e "
select 'Seller Application' dt, count(*) n
  from \`tabSeller Application\` where ifnull(identity_document,'') <> ''
union all
select 'Seller Certification', count(*)
  from \`tabSeller Certification\` where ifnull(document,'') <> ''
union all
select 'KYB Verification', count(*)
  from \`tabKYB Verification\`
  where ifnull(identity_document,'') <> '' or ifnull(bank_account_document,'') <> '';"
```

Bu dosyalar legal hold'un ilk adayları: hem PII hem de yasal ispat değeri
taşıyorlar.

---

## 10. Kaynak dosya listesi (bu belgeyi yazarken okunanlar)

| Dosya | Okunan aralık | Ne için |
|---|---|---|
| `tradehub_core/media/trash.py` | 1-341 (tamamı) | Çöp akışı, kapılar, purge, audit |
| `tradehub_core/media/archive.py` | 1-165 (tamamı) | Orijinal arşivi, purge |
| `tradehub_core/media/presets.py` | 1-81 (tamamı) | `ARCHIVE_RETENTION_DAYS`, `EXCLUDED_DOCTYPES`, ters referans haritası |
| `tradehub_core/media/backup.py` | 340-419 | `prune`, `KEEP_SETS`, `run_scheduled` sırası |
| `tradehub_core/media/backup_export.py` | grep: 45, 568 | `KEEP_HOURS` |
| `tradehub_core/media/usage.py` | 1-80 | Verdict tanımları, kaynak listeleri |
| `tradehub_core/media/refs.py` | 1-45 + grep | Referans zinciri, readonly tablolar |
| `tradehub_core/media/states.py` | grep: 48-51 | Durum sabitleri |
| `tradehub_core/media/audit.py` | grep: 43-68 | Action sabitleri |
| `tradehub_core/media/schema.py` | 1-90 | Künye tabloları |
| `tradehub_core/media/transcode.py` | 1-60 | Yerinde yazma davranışı |
| `tradehub_core/media/engine.py` | grep: 117, 177 | `thumbnail()` çağrıları |
| `tradehub_core/hooks.py` | 92-219, 225-285 | `scheduler_events`, `doc_events` |
| `tradehub_core/audit/tasks.py` | grep: 32-34 | Audit sıcak pencereleri |
| `tradehub_core/audit/__init__.py` | grep: 23 | S3/MinIO niyet notu |
| `tradehub_core/patches/v15_9_1[2-6]_*.py` | grep: `fieldname` | `File` custom alan envanteri |
| `requirements.txt` | tamamı (4 satır) | S3 istemcisi yokluğu |
