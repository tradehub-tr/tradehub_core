# Medya güvenliği: zararlı içerik taraması ve karantina (TUR-125)

**Tarih:** 2026-08-17 → 18 · **Pipeline adımı:** 3 · **Kod:** `tradehub_core/media/av.py`

---

## 1. Bu iş ne DEĞİL

TUR-125'in Linear'daki açıklaması beş kapsam maddesi sayıyor ve ilki şu:
*"Yükleme sırasında mime type ve uzantı doğrulaması."*

**Bu madde bu issue açılmadan önce bitmişti** ve yeniden yazılmadı. Kod tabanı
taraması (2026-08-17) şunu gösteriyor:

| Zaten var olan | Nerede | Hangi iş |
|---|---|---|
| Yasak uzantı listesi (14 uzantı: `.svg .html .js .xml .swf`…) | `utils/security.py:27` | HATA 23 |
| `File.before_insert` kancası — **bütün** yükleme yolları | `utils/security.reject_unsafe_files` | HATA 23 |
| Allow-list (`EXTENSIONS`, `MEDIA_KINDS`) | `media/upload_policy.py` | TUR-123 |
| Tür bazlı boyut limitleri | `upload_policy.MAX_BYTES` | TUR-123 |
| Magic-byte sniffing (11 imza + RIFF/WEBP + ftyp) | `upload_policy.sniff()` | TUR-123 |
| Tarayıcıda çalışabilen içerik reddi (7 markör) | `upload_policy.is_dangerous()` | TUR-123 |
| Uzantı↔içerik uyuşmazlığı uyarısı | `upload_policy._uyumlu()` | TUR-123 |
| Client tarafı ön kontrol | `admin-panel/.../uploadPolicy.js` | TUR-123 |

Politika **biçime** bakar: "bu bir JPEG mi, içi HTML mi?" Tarama **imzaya**
bakar: "bu JPEG bilinen bir zararlıyı taşıyor mu?" İkisi farklı sorular ve
`av.py` içine ikinci bir uzantı listesi konmadı — `is_denied_extension` tek
kaynak olarak kalıyor.

---

## 2. Yapılanlar

### 2.1 Tarama motoru — `media/av.py`

| Parça | Davranış |
|---|---|
| **Tarayıcı** | `clamdscan` (tercih, daemon'a bağlanır) → yoksa `clamscan`. `shutil.which` ile tespit |
| **Çıkış kodu yorumu** | 0 = temiz · 1 = zararlı bulundu · 2+ = tarayıcı hatası (exception → retry) |
| **Katman** | Kuyruk (`default`), `File.after_insert` kancasıyla tetiklenir |
| **Kapsam** | **Her dosya** — public + private, görsel + belge + video. Transcode kancasının aksine daraltılmadı |
| **Zaman aşımı merdiveni** | clamdscan 120 sn < kuyruk 300 sn < kayıp eşiği 2700 sn |

Kapsamın geniş olması bilinçli: transcode bir **maliyet** kararı verdiği için
daraltılmış (satıcı + public + video), tarama bir **güvenlik** kararı verdiği
için daraltılmadı. Private KYB belgesi zararsız değildir — bir yönetici onu
indirip açıyor.

### 2.2 Durum modeli — `th_media_scan_status`

```
    (boş)      Hiç taranmadı. Alan yamayla sonradan eklendiği için
               başlangıçta TÜM kayıtların durumu buydu (5.150).
    pending    Kuyruğa girdi / taranıyor.
    clean      Tarandı, imza bulunamadı.
    infected   Zararlı bulundu → dosya karantinada, adres servis edilmiyor.
    failed     Tarayıcı üç denemede de sonuç veremedi (dead-letter).
```

Bu alan yaşam döngüsü durumundan (`th_media_state`: Active/Archived/Trashed/
Deleted) **ayrı bir eksen** ve `th_media_video_status` ile aynı katmanda.
Karantinayı `th_media_state`'e bir değer olarak eklemek `ALLOWED_TRANSITIONS`
sözlüğünü her yeni iş türüyle çarpardı.

**Boş durum bilerek `clean` değil.** Yama backfill yapmıyor; taranmamış dosyayı
temiz göstermek bu alanın en tehlikeli yanlışı olurdu.

### 2.3 Karantina fiziksel taşımadır

`public/files/` altındaki dosyayı **nginx doğrudan servis ediyor** — Python hiç
devreye girmiyor. Yani bir bayrak alanı ("bu dosya zararlı") dosyayı erişime
kapatmaz. Kapatmanın tek yolu dosyayı o kökün dışına almak:

```
public/files/<yol>     →  private/media_quarantine/<yol>
private/files/<yol>    →  private/media_quarantine/private/<yol>
```

Public ve private ağaçları karantina içinde de ayrı tutuluyor: geri alma
dosyayı doğru köke döndürebilmeli, yoksa private bir KYB belgesi public dizine
geri konurdu. `media/trash.py` çöp için aynı deseni kullanıyor.

### 2.3b Bekletme — taranmamış dosya hiç servis edilmez

Karantina yalnız **kalıcı** açıklığı kapatıyordu. Dosya, kaydın açılması ile
taramanın bitmesi arasında (saniyeler) hâlâ servis edilebiliyordu. Bekletme o
aralığı da kapatır:

```
yükleme → kayıt açılır → dosya HEMEN private/media_scan_hold/ altına alınır
        → tarama                → temizse canlı ağaca konur
                                → zararlıysa karantinaya geçer
                                → taranamazsa (fail-open) canlı ağaca konur
```

**`file_url` DEĞİŞMEZ** — yalnız dosyanın fiziksel yeri değişir. İçerik-adresli
adlandırmanın (`naming.py`) sözleşmesi bu yüzden korunuyor: adres yükleme anında
kesinleşir, dosya sonradan yerine konur. Alternatif (önce private'a yükleyip
temiz çıkınca public'e taşımak) adresi yükleme anında belirsiz bırakırdı.

**Bekletme ile karantina ayrı kökler.** Karantina bir KARAR ("bu dosya
zararlı"), bekletme bir ARA DURUM ("henüz bilmiyoruz"). Aynı dizine koymak,
operatörün karantina listesinde henüz taranmamış olağan dosyaları zararlı
sanmasına yol açardı. Panelde de ayrı sekmeler.

**Politika:** `media_av_hold_until_clean`, varsayılan "auto" = tarama açıksa
beklet. Tarayıcı YOKKEN bekletmek her yüklemeyi sonsuza kadar görünmez yapardı.
Aynı gerekçeyle dead-letter'da fail-open modunda dosya bekletmeden **çıkarılır** —
"açık bırakıyoruz" deyip sessizce kapalı tutmak politikanın tersini yapmak olurdu.

**Yedeklemeyle etkileşimi (bulundu ve ele alındı).** Bekletmedeki dosya
`public/files/` altında olmadığı için yedeğe girmez. Bu doğru davranış — dosya
henüz canlı değil, temiz çıkınca bir sonraki günlük yedeğe girer; karantinadaki
dosya ise hiç girmemeli, çünkü geri yükleme zararlıyı sisteme geri getirirdi.
Ama `seller_backup.plan()` bunları "kayıp dosya" diye raporluyordu. Artık sebep
ayrılıyor: `scan_hold` · `quarantine` · `missing`. Yalnız sonuncusu ilgilenilmesi
gereken durum.

### 2.4 Retry ve dead-letter

`media/jobs.py`'deki ortak politikayı kullanır — transcode ile **aynı sayılar**:
3 deneme, 5/15 dk backoff, 45 dk kayıp eşiği, 5 dakikada bir süpürücü.

- Retry sırasında durum `pending` **kalır**: kullanıcıya "başarısız" gösterip
  iki dakika sonra "temiz"e dönmek güven bozar.
- Retry kuyruğa **anında konmaz** — `frappe.enqueue`'un gecikme parametresi yok
  (v15); bekleme damga üzerinden yürür, işi süpürücü alır.
- Sert kill (RQ timeout, OOM) `except` bloğunu çalıştırmaz; süpürücü
  `th_media_scan_started_at` damgasına bakarak bırakılmış işi yakalar.

### 2.5 Fail-open kararı ve gerekçesi

ClamAV taban imajda **yok**; local'e sonradan kuruldu (§6.1), canlıda ops
kuracak. Politika bu yüzden kurulumdan bağımsız çalışmak zorunda:

| Durum | Davranış |
|---|---|
| Tarayıcı yok | Politika kendini kapatır, kuyruğa **hiç** girilmez, durum boş kalır |
| Tarayıcı var, dosya temiz | `clean` + denetim kaydı |
| Tarayıcı var, zararlı | `infected` + fiziksel karantina + HIGH denetim kaydı |
| Tarayıcı var, üç denemede de hata | `failed`, dosya **erişimde kalır**, panelde işaretli |

Son satır fail-open. Alternatifi (fail-closed) tarayıcı kurulana kadar **her**
yüklemeyi karantinaya atardı — güvenlik adına siteyi kullanılamaz hâle
getirmek. Sıkı davranış açılabilir:

```json
// site_config.json
{ "media_av_fail_closed": 1 }
```

O zaman `failed` dosyalar da karantinaya taşınır. `media_av_enabled` de elle
verilebilir (`0`/`1`); verilmezse "auto" — tarayıcı kuruluysa açık.

### 2.6 Denetim kaydı

Üç yeni olay (`media/audit.py`):

| Olay | Ne zaman | Severity |
|---|---|---|
| `media.scan` | Her tarama — temiz sonuç dahil | NORMAL (başarısızsa HIGH) |
| `media.quarantine` | Zararlı bulundu, dosya kapatıldı | **HIGH** |
| `media.quarantine_release` | İnsan kararıyla geri açıldı | **HIGH** |

Temiz sonuç da yazılıyor: "tarandı ve temiz çıktı" ile "hiç taranmadı" denetimde
ayırt edilemezse, kapsamın ne kadarını gerçekten taradığımız sorusu cevapsız
kalır. Ama temiz dal HIGH **değil** — her yüklemede bir satır yazılıyor,
hepsini HIGH işaretlemek severity filtresini işe yaramaz hâle getirirdi.

> **Yükleme kaydıyla hizalama (19 Ağustos).** Bu modül belgeleri de tarıyor ama
> `audit.on_file_insert` bir dönem yalnız görsel/video kaydediyordu; sonuç, bir
> PDF için "tarandı" satırı olup "yüklendi" satırı olmaması — yani takip
> edilemeyen bir iz. Yükleme kaydının uzantı süzgeci kaldırıldı; gerekçe ve
> ölçüm `MEDYA-ISLEME-PIPELINE.md` §6.1'de. Tarama ile yükleme kaydı artık aynı
> kapsamda.

### 2.7 API uçları — `api/media_admin.py`

| Uç | Yetki | İş |
|---|---|---|
| `scan_overview()` | Admin | Politika + sayımlar (panel üst bandı) |
| `list_quarantine()` | Admin | Karantinadaki dosyalar (envanterden ayrı uç — orada görünmezler) |
| `retry_scan(file_url)` | Admin | `failed` dosyayı yeniden kuyruğa koy |
| `release_quarantine(file_url)` | **System Manager** | Yanlış pozitifi geri al |
| `scan_backfill(limit)` | Admin | Hiç taranmamışları parça parça kuyruğa al |
| `list_scan_hold()` | Admin | Tarama bekleyenler — karantinadan AYRI liste. Uzun süre dolu kalması kuyruk/tarayıcı arızası demektir |
| `sweep_scans()` | Admin | Süpürücüyü elle tetikle; operatör 5 dakikayı beklemesin |

`release_quarantine` yıkıcı yetki istiyor: sistemin zararlı dediği bir dosyayı
erişime geri açıyor. Yanlış pozitifler gerçek ve bu yetenek olmadan operasyon
kilitlenir, ama bunu tek tıkla yapabilecek kişi sayısı gereksiz büyümemeli —
arşiv silmeyle aynı gerekçe.

`retry_scan` `infected` kabul **etmez**: zararlı bulgusunu yeniden tarayarak
"belki bu sefer temiz çıkar" demek bulgunun anlamını yok eder. Oradan çıkış
yalnız açık bir insan kararıdır.

### 2.8 Panel

| Ekran | Değişiklik |
|---|---|
| Satıcı Medya Kütüphanesi (liste + kart) | `infected` / `failed` rozeti. `clean` ve `pending` rozetlenmiyor — olağan durumlar, her satırı işaretlerdi |
| Yönetici Medya Optimizasyon (`MediaOptimizeView`) | Aynı rozet. Karantinadaki dosya diskte public ağaçtan çıkmıştır ama `File` kaydı durduğu için bu listede görünür — yöneticinin bulguyu göreceği yer burası |
| **Medya Karantinası (`MediaQuarantineView`) — YENİ ekran** | `/media-quarantine`. Politika bandı, 5 sayaç, iki sekme (**Karantina** / **Tarama bekleyenler**), satır işlemleri: karantinadan çıkar (iki adımlı onay), yeniden tara; üstte "takılanları topla" ve "eskileri tara" |
| Medya Denetim (`MediaAuditView`) | 3 yeni olay için ikon + insan diliyle açıklama |
| i18n | `media.scanStatus.*`, `mediaOptimize.scanStatus.*`, `mediaAudit.explain.scan*/quarantine*` — tr + en |

Rozet renkleri ayrı: zararlı **hata** tonunda, taranamadı **uyarı** tonunda.
Bir şey bulunmadı, yalnız bakılamadı; ikisini aynı kırmızıya boyamak gerçek
bulguyu sıradanlaştırırdı.

---

## 3. Kabul kriterleri

| # | Kriter | Durum | Kanıt |
|---|---|---|---|
| 1 | Kabul edilen ve reddedilen dosya türleri tanımlı | ✅ | TUR-123'te bitmişti: `_DENIED_EXTENSIONS` (14) + `EXTENSIONS` allow-list + `MEDIA_KINDS`. Bu issue'da tekrar yazılmadı |
| 2 | Tarama başarısız/belirsiz ise davranış net | ✅ | 3 deneme → `failed`; fail-open varsayılan, `media_av_fail_closed` ile fail-closed. Tarayıcı çökmesi asla "temiz" sayılmaz (`scan_path` exception atar) |
| 3 | Güvenlik olayları izlenebilir kaydediliyor | ✅ | `media.scan` / `media.quarantine` / `media.quarantine_release`; ikisi HIGH. Denetim ekranında ikon + açıklama |
| 4 | Riskli dosyalar kalıcı erişime açılmıyor | ✅ **tam** | İki katman: (a) taranmamış dosya `media_scan_hold`'da bekletilir, bir an bile servis edilmez (§2.3b); (b) zararlı bulunan `media_quarantine`'e taşınır. Gerçek yüklemeyle doğrulandı: yükleme sonrası canlı ağaçta yok → tarama temiz → yerine kondu → HTTP 200 |

**Kapsam maddeleri:** mime/uzantı doğrulaması ✅ (önceden) · AV entegrasyon
yaklaşımı ✅ · karantina/reddetme/işaretleme ✅ · güvenlik loglama ✅ · panel
görünürlüğü ✅.

---

## 4. Yapılmayanlar ve gerekçeleri

| Yapılmadı | Neden |
|---|---|
| **ClamAV imaja kurulmadı** | Docker imajı ve prod sunucu bu issue'nun deposunda değil — kurulum ops işi. Kod hazır ve kurulum yapıldığı anda kendiliğinden devreye girer (`policy()` "auto") |
| **Mevcut ~5.000 dosyanın toplu taranması** | Tek turda kuyruğa boşaltmak kuyruğu saatlerce meşgul ederdi. `scan_backfill(limit)` ile parça parça, yönetici kontrolünde |
| **`th_media_scan_status` backfill'i** | Taranmamışı `clean` yazmak yalan olurdu; boş durum "hiç taranmadı" demek |
| **Tarama için ayrı kayıp eşiği** | `jobs.STALE_AFTER_SECONDS` (45 dk) transcode'un uzun kuyruğuna göre ayarlı, tarama için geniş. İki iş için iki eşik tutmak "hangi iş hangi eşikle" sorusunu her okuyana sordururdu. Sonucu yalnız gecikme, veri kaybı değil |
| **`th_media_scan_status` alanına göre envanter filtresi** | Rozet var, filtre chip'i yok. Karantinadaki dosya zaten envanter sorgusunda görünmüyor (fiziksel olarak public ağaçtan çıkmış) |

---

## 5. Testler

`tradehub_core/tests/test_media_av.py` — **81 test, hepsi geçiyor.**

```bash
docker exec -w /home/frappe/frappe-bench istoc-backend bench \
    --site tradehub.localhost run-tests \
    --module tradehub_core.tests.test_media_av
```

| Eksen | Kapsanan |
|---|---|
| Unit | Politika çözümleme (auto/açık/fail-closed), tarayıcı tespiti, imza adı ayıklama, durum önceliği |
| Validation / monkey | Boş, `None`, `/etc/passwd`, `../` kaçışı, `javascript:`, sorgu parametreli adres |
| Integration | `inventory.list_files` çıktısında `scan_status`; taranmamış boş döner |
| API | 5 uç; boş adres reddi, rolsüz kullanıcı reddi, yıkıcı yetki kontrolü |
| Database | Sayaç kalıcılığı, yama idempotency, dört alanın varlığı |
| Retry/dead-letter | Sayaç artışı, backoff planı, hak bitişi, fail-open vs fail-closed |
| Karantina | Fiziksel taşıma, geri alma, çift geri alma reddi, geri alınanın yeniden taranabilmesi |
| Süpürücü | Planlı deneme, erken deneme, çalışan iş, bırakılmış iş, damgasız kayıt, dead-letter dokunulmazlığı |
| Error/recovery | Tarayıcı yok, tarayıcı hata kodu, diskte olmayan dosya, kuyruktayken silinen kayıt |
| E2E | Yükle → pending → zararlı → karantina → geri al → yeniden tara → temiz |

**Regresyon:** komşu medya modülleri de koşuldu — `test_media_transcode_retry`
(39), `test_media_transcode` (21), `test_media_seller_backup` (38),
`test_media_jobs` (12), `test_media_naming` (9), `test_media_pipeline_integration`
(5), `test_media_quota` (10). **Toplam 215 backend testi yeşil** (ClamAV kurulu
hâliyle yeniden koşuldu).

Frontend: `npm test` 165/165, `npm run build` temiz.

### ⚠️ ClamAV kurulunca 6 test düştü — ve bu iyi oldu

Testler ClamAV **kurulu değilken** yazıldı; 64'ü de geçti. Tarayıcı kurulunca:

* **5 test** `test_media_av` içinde düştü. Sebep: `File.after_insert` kancası
  artık gerçekten iş yapıyor ve test fixture'ının açtığı her dosyayı, test daha
  başlamadan `pending` yapıyordu. Yani testler makinede tarayıcı bulunup
  bulunmamasına göre farklı davranıyordu. **Düzeltme:** `_insert()` fixture'ı
  kancayı nötrler; kancanın kendi davranışı `TestKancaTetikleme` içinde açıkça
  sınanır.
* **1 test** `test_media_pipeline_integration` içinde düştü:
  `mock_enqueue.assert_called_once()`. Yükleme artık iki iş kuyruklıyor
  (transcode + tarama) ve `frappe.enqueue` her iki modülde aynı nesne olduğu
  için tek mock ikisini birden yakalıyor. **Düzeltme:** sayı yerine *aranan
  çağrı* doğrulanıyor — sayıya bakmak pipeline'a eklenen her adımda bu testi
  konusuyla ilgisiz biçimde kırardı.

Ders: yeşil bir test paketi, ortam değiştiğinde hâlâ yeşil kalacağının garantisi
değil. Bir bağımlılığın *yokluğu* üstüne kurulmuş testler, o bağımlılık gelince
düşer.

### 🐞 Kurulum sonrası bulunan gerçek hata: NULL süzgeci

Belge yazılırken sayılar karşılaştırıldı ve tutmadı: sitede **5.151** dosya
kaydı var ama `scan_overview` "30 dosya taranmamış" diyordu.

**Sebep.** Süzgeç `["in", ["", None]]` yazılmıştı; Frappe bunu SQL'de
`IN ('', NULL)` diye üretiyor ve SQL'de hiçbir şey NULL'a *eşit* olmadığı için
NULL satırlar hiç eşleşmiyordu. Alan yamayla sonradan eklendiğinden mevcut
kayıtların tamamı NULL (ölçüldü: **5.120 NULL / 30 boş string**).

**Etkisi iki yerde ve sessizdi:**

* `scan_overview` "taranmamış" sayısını 5.150 yerine **30** gösteriyordu.
* `backfill_pending` aynı süzgeci kullandığı için o 5.120 dosyayı **hiç
  kuyruğa alamıyordu** — geriye dönük tarama, işin %99'unu görmeden "bitti"
  görünürdü.

**Düzeltme.** `["is", "not set"]` (`IFNULL(alan, '') = ''`) — NULL ve boş
string'i birlikte kapsar. `media/av.py` ve `api/media_admin.py`'de düzeltildi,
`TestNullDurumSuzgeci` ile 4 regresyon testi yazıldı. Testlerden biri bilerek
*yanlış* süzgeci koşup NULL'ı kaçırdığını sabitliyor — böylece birisi geri
çevirirse test söyler.

> Bu hata mock'lu testlerin göremeyeceği türdendi: ancak gerçek veriyle,
> gerçek sayılara bakıldığında ortaya çıktı.

### Üçüncü tuzak: testin gerçek veriyi damgalaması

NULL süzgeci için yazılan regresyon testi ilk hâlinde **gerçek**
`backfill_pending`'i çağırıyordu. `frappe.enqueue` mock'luydu ama `enqueue_scan`
değildi — yani kuyruğa iş girmiyor, buna karşılık sitedeki **1.497 dosya**
`pending` damgalanıyordu. `_sil` temizliği `commit` ettiği için bu durum kalıcı
oldu ve hemen ardından `TestSupurucu`'nun dört testi birden düştü: süpürücü
kendi test kaydı yerine bu artıkları buluyordu.

İki yönlü ders:

* Test, sınadığı şeyin **en dar** hâlini çağırmalı. Burada sınanan şey süzgecin
  NULL'ı yakalayıp yakalamadığı; `enqueue_scan`'i gerçekten çalıştırmanın
  katkısı yok, maliyeti büyük. Mock'landı.
* Damgalar `pending`'e çekilmişti ama kuyrukta karşılığı olan iş yoktu — yani
  veritabanı "taranıyor" diyordu, gerçekte hiçbir şey taranmıyordu. Bu yüzden
  temizlikte `clean` değil **NULL**'a döndürüldü: "hiç taranmadı" gerçek durum.

### Test artığı temizliği

Koşumlar sırasında `test_media_transcode_retry` ve `test_media_seller_backup`
paketlerinin bıraktığı **50 artık `File` kaydı** oluştu (o paketler sızıntıyı
koşum-başına tuzla *yönetiyor*, kapatmıyor). Hepsi tek tek listelenip test
fixture'ı oldukları doğrulandıktan sonra silindi; gerçek veriye dokunulmadı.
`test_media_av` kendi kayıtlarını sızdırmıyor — arka arkaya iki koşum sonrası
sayaçlar sıfır doğrulandı (§ Test tuzakları, madde 2).

### Test tuzakları (not düşülüyor)

**1 — Uzantı seçimi.** Test dosyaları `.txt` uzantılı. `.jpg` denendi →
Frappe'nin `strip_exif_data`'sı gerçek görsel bekliyor,
`PIL.UnidentifiedImageError`. `.pdf` denendi → Frappe'nin `pdf_contains_js`
kontrolü gerçek PDF bekliyor, `PdfStreamError`. `.txt` ikisine de girmiyor.
(`test_media_transcode_retry` aynı sebeple `.mp4` kullanıyor.)

**2 — Temizlik commit edilmeli.** `FrappeTestCase` teardown'da rollback yapıyor,
ama test edilen kod yolları (`_run_scan`, süpürücü) kendi `frappe.db.commit()`
çağrılarını yapıyor: INSERT kalıcı oluyor, temizlikteki DELETE rollback'e
takılıp geri alınıyor. İlk koşum veritabanında **3 artık kayıt** bıraktı
(ölçüldü). `_sil()` yardımcısı silmeyi de commit ediyor; koşum sonrası
`scan_overview` sayaçları sıfır doğrulandı. Mevcut `test_media_transcode_retry`
bu sorunu koşum-başına tuzla *yönetiyor*, kaynağında kapatmıyor — aynı deseni
kopyalamak yerine düzeltildi.

---

## 6. Devreye alma

### 6.1 Local — YAPILDI (2026-08-17)

ClamAV `istoc-backend` container'ına kuruldu ve uçtan uca doğrulandı:

```bash
docker exec -u root istoc-backend bash -lc \
  'apt-get update && apt-get install -y clamav clamav-daemon'
docker exec -u root istoc-backend freshclam            # ~112 MB imza
docker exec -u root istoc-backend bash -lc \
  'mkdir -p /run/clamav && chown clamav:clamav /run/clamav && (clamd &)'
```

`systemd` container'da çalışmadığı için `clamd` elle başlatılıyor
(`service`/`systemctl` iş görmez).

> ⚠️ **Bu kurulum kalıcı DEĞİL.** Taban imajı `frappe/bench:latest` kontrol
> edildi: içinde **ne ffmpeg ne clamav** var. Yani ffmpeg de bir noktada aynı
> şekilde elle kurulmuş. Projede Dockerfile yok, `docker-compose.yml` hazır
> imajı doğrudan kullanıyor — `docker compose down` + yeniden yaratma **ikisini
> de** siler. Kalıcı çözüm bir Dockerfile'da `ffmpeg` + `clamav` katmanı; bu
> TUR-125'ten önce de gereken ayrı bir iş.

### 6.2 Canlı (ops)

1. ClamAV kur + `freshclam` + daemon'ı servis olarak başlat.
2. `bench --site <site> migrate` — dört alan + index.
3. `scan_overview` ile doğrula: `policy.enabled` **true** olmalı.
4. Geriye dönük tarama: `scan_backfill(limit=500)` — birkaç turda.
5. İzle: `media.quarantine` olayları denetim ekranında HIGH ile görünür.

### 6.3 Gerçek doğrulama sonuçları (mock YOK)

EICAR standart test imzası kullanıldı (zararsız, tam da bu iş için tasarlanmış).

| Kontrol | Sonuç |
|---|---|
| `clamdscan` temiz dosya | `OK`, çıkış kodu **0** |
| `clamdscan` EICAR | `Eicar-Test-Signature FOUND`, çıkış kodu **1** |
| `scan_overview` tarayıcıyı gördü mü | `enabled: true`, `scanner: /usr/bin/clamdscan` — **ayar değiştirmeden**, "auto" politikası çalıştı |
| EICAR yükleme → kanca → durum | `pending` (anında) |
| Worker taraması → durum | `infected` |
| `public/files/` altında dosya | **yok** |
| `private/media_quarantine/` altında | **var** |
| Denetim kaydı | `media.quarantine` · DENY · **HIGH** · `signature: "Eicar-Test-Signature"`, `moved: true` |
| Temiz dosya denetim kaydı | `media.scan` · ALLOW · NORMAL · `result: "clean"` |
| HTTP erişimi (gerçek `.jpg` ile) | karantina öncesi **200** → sonrası **servis edilmiyor** → geri alma sonrası **200** |
| `release_from_quarantine` | `{released: True, records: 1}`, dosya yerine döndü, durum sıfırlandı |
| **Bekletme — gerçek yükleme** | Yükleme sonrası: durum `pending`, canlı ağaçta **yok**, bekletmede **var**, `is_servable` **False** |
| **Bekletme — tarama sonrası** | Worker taradı → `clean` → canlı ağaçta **var**, bekletmede yok, HTTP **200** |

**HTTP kodu notu:** yerel `bench serve` eksik dosya için 404 değil **500**
veriyor (var olmayan bir adres de aynı 500'ü veriyor — dev sunucusunun mevcut
davranışı, bu işle ilgisi yok). Canlıda nginx 404 döner. İkisinde de sonuç aynı:
**dosya servis edilmiyor.** Ayrıca yerel dev sunucusu `.txt` uzantısını hiç
servis edemiyor (mevcut dosya bile 500) — bu yüzden HTTP doğrulaması `.jpg` ile
yapıldı.

---

## 7. Yol üstünde düzeltilen mevcut kusurlar

Bu iş sırasında ortaya çıkan, TUR-125'in kapsamında olmayan üç kusur:

**1. Denetim eylemlerinin yarısı çevrilmemişti.** `MediaAuditView`
`mediaAudit.action.<slug>` arıyor, bulamazsa ham değeri basıyor. `media.release`,
`media.reclaim`, `media.backup` (TUR-131'den) hiç eklenmemişti — panelde
"media.backup" diye görünüyorlardı. Bu işin üç yeni olayı da aynı boşluğa
düşüyordu. **17 eylemin tamamı 4 dilde tanımlandı.**

**2. `media.export` yanlış etiketle görünüyordu.** `mediaAudit.action.export`
anahtarı hem araç çubuğundaki "CSV indir" düğmesi hem de denetim eyleminin
etiketiydi. Sonuç: "yedek paketi sunucudan çıktı" diyen **HIGH önemli güvenlik
olayı**, denetim listesinde **"CSV indir"** yazıyordu. Düğme `action.exportCsv`'ye
taşındı, `action.export` gerçek anlamına bırakıldı.

**3. `media.empty` iki kez tanımlıydı** (tr/en) — `no-dupe-keys` lint hatası,
HEAD'de de vardı. `mediaAudit.action` bloğu yeniden yazılırken ilk (ölü) kopya
düştü. JS'te son tanım kazandığı için **çalışma anında hiçbir metin değişmedi**;
lint hatası da kapandı. Planlı bir değişiklik değildi, kayda geçiyor.

---

## 8. Değişen dosyaların tamamı

**`tradehub_core`** (10 değişen + 4 yeni · +478/-38 satır)

| Dosya | Durum | Satır | Ne |
|---|---|---:|---|
| `tradehub_core/media/av.py` | **YENİ** | 847 | Tarama motoru, karantina, retry/dead-letter, süpürücü, politika |
| `tradehub_core/tests/test_media_av.py` | **YENİ** | 997 | 81 test |
| `tradehub_core/patches/v15_9_20_media_scan_fields.py` | **YENİ** | 100 | 4 alan + index |
| `docs/MEDYA-AV-TARAMA.md` | **YENİ** | — | Bu belge |
| `tradehub_core/media/seller_backup.py` | değişti | +111 | Bekletme/karantina ile "gerçek kayıp" ayrımı |
| `tradehub_core/tests/test_media_seller_backup.py` | değişti | +110 | Fixture tarama kancasını nötrler |
| `tradehub_core/api/media_admin.py` | değişti | +164 | 7 yönetici ucu |
| `tradehub_core/media/inventory.py` | değişti | +29 | `scan_status` toplaması |
| `tradehub_core/media/audit.py` | değişti | +22 | 3 olay sabiti + severity |
| `tradehub_core/hooks.py` | değişti | +12 | `after_insert` kancası + cron |
| `tradehub_core/patches.txt` | değişti | +1 | Yama kaydı |
| `tradehub_core/tests/test_media_pipeline_integration.py` | değişti | +30 | Kırılan iddia daraltıldı + bekletmeye uyarlandı (§5) |
| `tradehub_core/tests/test_media_transcode_retry.py` | değişti | +10 | Arama tuzla izole edildi — birikmiş artıklar aranan dosyayı sayfadan düşürüyordu |
| `docs/MEDYA-ISLEME-PIPELINE.md` | değişti | +27/-9 | Adım 3 ❌ → ✅, §2.3 pencere, §8 açık madde |

**`admin-panel`** (9 değişen + 2 yeni · +540/-11 satır)

| Dosya | Satır | Ne |
|---|---:|---|
| `src/views/system/MediaQuarantineView.vue` | **YENİ** 531 | Karantina yönetim ekranı — politika bandı, 5 sayaç, iki sekme, satır işlemleri |
| `src/composables/useMediaSecurity.js` | **YENİ** 116 | Politika, iki liste, eylemler |
| `src/views/system/MediaOptimizeView.vue` | +28 | Yönetici listesinde tarama rozeti + stil |
| `src/views/system/MediaAuditView.vue` | +30 | 3 olay için ikon + açıklama; `action.exportCsv` ayrımı |
| `src/views/seller/MediaLibraryView.vue` | +40 | Satıcı liste satırında rozet + stil |
| `src/components/media/MediaCard.vue` | +46 | Satıcı kart görünümünde rozet + stil |
| `src/router/index.js` · `src/data/navigation.js` | +13 | `/media-quarantine` rotası + menü girişi |
| `src/composables/useSellerMedia.js` | +4 | `scan_status` → `scanStatus` eşlemesi |
| `src/i18n/locales/{tr,en,ar,ru}.js` | +390 | **4 dilin tamamı**: `mediaQuarantine` namespace'i (44 anahtar), `nav.item.mediaQuarantine`, `media.scanStatus.*`, `mediaOptimize.scanStatus.*`, **17 denetim eylem etiketinin tamamı** (`mediaAudit.action.*`), `mediaAudit.explain.scan*/quarantine*`, `action.exportCsv` ayrımı. ar/ru'ya `mediaAudit` ve `mediaOptimize` namespace'leri sıfırdan açıldı |

> **Mevcut çeviri boşluğu (bu işin dışında).** `ar.js` / `ru.js` dosyalarında
> medya modülünün HİÇBİR namespace'i yoktu. Bu işte gereken kadarı açıldı —
> `media`, `mediaOptimize`, `mediaAudit`, `mediaQuarantine` artık var ve bu işe
> ait her anahtar 4 dilde tam. Ama açılan namespace'ler **kısmi**: yalnız bu
> işin dokunduğu alanları içeriyor (eylem etiketleri, durum metinleri,
> açıklamalar). Medya ekranlarının geri kalanı (sütun başlıkları, filtreler,
> boş-durum metinleri) ve `mediaBackup`'ın tamamı Arapça/Rusça'da hâlâ
> fallback'e düşüyor. Ayrı ve büyük bir iş.

**Commit atılmadı**, ikisi de çalışma ağacında duruyor.

---

## 9. Monkey test senaryoları

**Panel:** http://localhost:8082 · Administrator / `admin`
(Vite dev server — HMR var, `npm run build` beklemeye gerek yok.)

Doğrulama için `monkey-eicar.txt` adlı bir dosya karantinada bırakıldı
(EICAR standart test imzası — zararsız).

| # | Senaryo | Nereye | Ne görülmeli |
|:-:|---|---|---|
| 1 | Yönetici zararlı dosyayı görüyor | `/media-optimize` → ara: `monkey-eicar` | Satırda **kırmızı "Zararlı içerik"** rozeti |
| 2 | Güvenlik olayının kaydı | `/media-audit` → filtre: Karar = Reddedilen | Kalkan-ünlem ikonlu `media.quarantine`; açıklama imza adını içeriyor; bağlamda `moved: true` |
| 3 | Dosya gerçekten erişilemez | `/files/<karantinadaki hash>.txt` | Açılmamalı (yerelde 500, canlıda nginx 404) |
| 4 | Satıcı temiz dosya yüklüyor | Satıcı girişi → `/media-library` → Yükle | Rozet **yok**; `/media-audit`'te yeşil `media.scan` · *"…imza bulunamadı."* |
| 5 | Satıcı zararlı dosya yüklüyor | Aynı yer; içeriği EICAR olan bir `.txt` | Birkaç saniyede **kırmızı rozet**, önizleme açılmıyor |
| 6 | Yanlış pozitifi geri alma | `/media-quarantine` → **Karantinadan çıkar** → **Eminim, aç** | Satır listeden düşer, rozet kalkar, HIGH `media.quarantine_release`. **Marketplace Admin ile reddedilmeli** |
| 7 | Karantina ekranı | `/media-quarantine` | Üstte politika bandı (**yeşil** = tarama açık, tarayıcı adı, "taranmadan servis edilmiyor"), 5 sayaç, iki sekme |
| 8 | Tarama bekleyenler sekmesi | `/media-quarantine` → **Tarama bekleyenler** | Yükleme yaptığın anda satır belirir, tarama bitince kaybolur. Uzun süre dolu kalıyorsa kuyruk/tarayıcı arızalı |
| 9 | Pencerenin kapandığını görme | Yükle, hemen sayfayı yenile | Kartta dönen **"Taranıyor"** rozeti ve önizleme YOK. Birkaç saniye sonra ikisi de normale döner |
| 10 | Dil kontrolü | Sağ üstten dili değiştir (TR/EN/AR/RU) | `/media-quarantine` ekranının tamamı çevrili olmalı — başlık, sekme, sütun, buton, uyarı metni |

EICAR içeriği (tek satır):

```
X5O!P%@AP[4\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*
```

### Ortamla ilgili tuzaklar

* Yerel dev sunucusu `.txt` uzantısını **hiç** servis edemiyor — mevcut bir dosya
  bile 500 veriyor. HTTP doğrulamasını `.jpg` ile yap.
* Eksik dosya için 404 değil **500** dönüyor (var olmayan bir adres de aynı).
  Dev sunucusunun mevcut davranışı, bu işle ilgisi yok.
* Karantinadaki dosya envanter listesinde **görünür** (fiziksel olarak public
  ağaçtan çıkmıştır ama `File` kaydı durur) — yöneticinin bulguyu göreceği yer
  burasıdır.
