# Medya İşleme Pipeline'ı — Asenkron Akış ve İş Orkestrasyonu

**Linear:** TUR-296 · **Faz:** 2 · **Durum:** bu belge sözleşmedir, kod ona uyar.
**Bağlı belgeler:** `MEDYA-YUKLEME-SOZLESMESI.md` (yükleme anı), `MEDYA-TARIH-STANDARDI.md` (damgalar).

> Bu belge, dosya sisteme girdikten **sonra** ne olduğunu tanımlar. Yükleme anının
> kendisi (doğrulama, kota, parçalı yükleme, adlandırma) yükleme sözleşmesinin
> konusudur ve burada tekrarlanmaz.

---

## 1. Neden bu belge var

Yükleme bittiğinde iş bitmiyor: video normalize ediliyor, görsel optimize
ediliyor, orijinal arşivleniyor, yedek paketleniyor. Bunların hepsi kuyrukta
çalışıyor ve **her biri kendi durum sözlüğünü konuşuyordu**. "İş başarısız oldu"
cümlesinin dört ayrı karşılığı vardı; hangi işin nerede takıldığı tek bir
ekrandan okunamıyordu.

Bu belge üç şeyi sabitliyor:

1. Adımların **sırası** ve her adımın hangi katmanda çalıştığı.
2. Bütün kuyruk işlerinin paylaştığı **durum sözlüğü**.
3. **Retry / zaman aşımı / dead-letter** politikası — tek yerde, tek sayı seti.

---

## 2. Adım sırası

Dosya sisteme girdiği andan "hazır" olduğu ana kadar geçtiği sıra. Sıra
tartışmaya açık değil; her adım bir öncekinin çıktısına güvenir.

| # | Adım | Katman | Ne zaman | Issue |
|:-:|---|---|---|---|
| 0 | Ön izleme, boyut/uzantı ön kontrolü | **İstemci** | Gönderimden önce | TUR-123 |
| 1 | Doğrulama (mime, boyut, kota) | Sunucu — istek içinde | Senkron, reddederse dosya hiç yazılmaz | TUR-123 |
| 2 | İçerik-hash'li adlandırma + kalıcı kayıt | Sunucu — istek içinde | Senkron | TUR-130 |
| 3 | **AV tarama** | Sunucu — kuyruk | Kayıttan hemen sonra, **yayına açılmadan önce** | **TUR-125** |
| 4 | Metadata temizleme (EXIF strip) | Sunucu — kuyruk | AV temiz döndükten sonra | **TUR-132** |
| 5 | Optimize / convert (görsel WebP, video WebM) | Sunucu — kuyruk | Metadata temizlendikten sonra | TUR-128 |
| 6 | Türev üretimi (thumbnail, responsive) | Sunucu — kuyruk | Optimize çıktısı üzerinden | TUR-297 |
| 7 | Yedekleme / arşivleme | Sunucu — zamanlanmış | Bağımsız, kendi takvimi | TUR-131 |

### 2.1 Sıranın gerekçesi

- **AV taraması her şeyden önce gelir.** Virüslü dosyayı önce optimize edip
  sonra taramak, zararlı içeriği diske yazılmış ve türevleri üretilmiş hâlde
  bulmak demektir. Tarama bitene kadar dosya **kullanıcıya servis edilmez**.
- **Metadata temizleme optimize'dan önce gelir.** Optimize yeniden encode
  ettiği için EXIF'i zaten düşürür — ama yalnız *encode edilen* formatlarda ve
  yalnız *optimize kapısından geçen* dosyalarda. Temizliği ayrı ve önce yapmak,
  "kapıdan dönen dosya konum bilgisiyle yayında kaldı" durumunu imkânsız kılar.
- **Türev üretimi en sonda.** Optimize çıktısı değişirse türevler baştan
  üretilmelidir; sırayı ters çevirmek her optimize'da türevleri çöpe atardı.

### 2.2 Bugün kodda ne var

| Adım | Durum |
|---|---|
| 0, 1, 2 | ✅ çalışıyor (`upload_policy`, `chunked`, `naming`) |
| 3 AV tarama | ✅ kodlandı — `media/av.py` (TUR-125). **Çalışması ClamAV kurulumuna bağlı**; tarayıcı yoksa politika kendini kapatır |
| 4 EXIF strip | 🟡 kısmi — `engine.py` yeniden encode ederken düşürüyor, ayrı adım değil (TUR-132) |
| 5 optimize/convert | ✅ görsel (`runner.run_batch`), ✅ video (`transcode`) |
| 6 türev | ❌ yok — TUR-297 |
| 7 yedek | ✅ `backup.py`, `backup_export.py` |

> **Açık madde.** Tarama kodu hazır ama **bu imajda ClamAV kurulu değil**;
> kurulana kadar adım 3 fiilen çalışmaz ve "tarama yapılıyor" denemez. Durum
> `media_admin.scan_overview` üzerinden panelden okunabilir (`policy.enabled`).
> Adım 4 hâlâ ayrı bir adım değil (TUR-132).

### 2.3 Taramanın kapatamadığı pencere

Dosya, kaydın açılması ile taramanın bitmesi arasında (saniyeler) servis
edilebilir durumdadır — kanca kuyruğa atar, nginx bu sırada dosyayı zaten
sunabilir. Kapatmanın yolu yüklemeyi önce private'a alıp temiz sonuçtan sonra
public'e taşımaktır; bu `file_url`'i yükleme anında belirsiz hâle getirir ve
`naming.py`'nin içerik-adresli sözleşmesini kırar.

Kabul kriteri "riskli dosyalar KALICI olarak erişime açılmamalı" diyor: kalıcı
açıklık karantinayla kapanıyor, geçici pencere bilinçli olarak kabul edildi.

---

## 3. Ortak durum sözlüğü

Kod karşılığı: `tradehub_core/media/jobs.py`.

| Durum | Anlamı | Terminal mi |
|---|---|:-:|
| `running` | Kuyrukta ya da worker'da | hayır |
| `completed` | Bitti, hata yok | evet |
| `partial` | İş yürüdü, bazı dosyalar hata verdi | evet |
| `error` | İşin kendisi yürüyemedi | evet |

Kullanıcıya gösterilen **dosya** durumu ayrıdır ve üç kelimeliktir:
`processing` / `ready` / `failed` (`File.th_media_video_status`). Bu ayrım
bilinçli: bir iş üç kez denenirken dosya kullanıcı gözünde hâlâ `processing`'dir.
"Başarısız" ancak sistem gerçekten pes ettiğinde gösterilir — iki dakika sonra
kendiliğinden "hazır"a dönen bir "başarısız" güven bozar.

### 3.1 Taşıma katmanları

Anlam ortak, taşıma katmanı işe göre değişir — birleştirmeye çalışmak fayda
getirmez:

| İş | Durum nerede tutulur | Neden |
|---|---|---|
| Video transcode | `File` alanı | Durum dosyaya aittir, işe değil; kullanıcı dosyayı görür |
| Görsel optimize / geri alma | Redis ilerleme sözlüğü (TTL 1 sa) | Toplu iş; ilerleme yüzdesi kalıcı veri değil |
| Yedek paketleme | Disk üstünde durum dosyası | Paketin kendisiyle aynı yerde durmalı; ayrı düşerse yetim paket kalır |

Yedek paketleme kendi Türkçe durum adlarını (`hazirlaniyor` / `hazir` / `hata`)
korur — ön yüz bu adlara bağlı ve karşılıkları birebir: `running` / `completed` /
`error`.

### 3.2 Aynı adreste durumlar ayrışırsa: kötü haber kazanır

Bir `file_url`'e 39 kayda kadar işaret edilebiliyor (içerik-adresli adlandırma;
bkz. `media/inventory.py`). Durum KAYIT başına yazıldığı için bu kayıtların
durumları ayrışabilir — biri `failed`, biri `processing` olabilir. Panel
`file_url` bazında grupladığından bir tanesini seçmek zorunda.

Seçim kuralı **açık öncelik**: `failed` > `processing` > `ready` > (boş).

Metin üstünde `Max()` almak yanlıştı: alfabetik sırada `ready` > `processing` >
`failed` olduğu için başarısız bir dosya panelde "hazır" görünüyordu. Kural
"kullanıcıya iyi haberi değil, ilgilenmesi gereken haberi göster" diye
seçildi — kayıp bir başarısızlık, gereksiz bir uyarıdan pahalıdır.

---

## 4. Retry, zaman aşımı, dead-letter

### 4.1 Politika

Kod karşılığı: `jobs.MAX_ATTEMPTS`, `jobs.BACKOFF_SECONDS`, `jobs.STALE_AFTER_SECONDS`.

| Ayar | Değer | Gerekçe |
|---|---|---|
| Toplam deneme hakkı | **3** (ilk çalıştırma dahil) | Geçici hatalar ilk tekrarda geçer; 3'te geçmeyen hata dosyanın kendisindedir |
| 1. tekrardan önce bekleme | **5 dk** | Disk dolduysa saniyeler içinde düzelmez |
| 2. tekrardan önce bekleme | **15 dk** | Hâlâ düzelmediyse sorun sistemsel; kuyruğu meşgul etme |
| Kayıp iş eşiği | **45 dk** | Kuyruk zaman aşımından büyük olmalı (aşağıya bak) |
| Süpürücü periyodu | **5 dk** | Backoff çözünürlüğü bundan ince olamaz |

### 4.2 Zaman aşımı merdiveni

Her katman bir üsttekinden **kısa**. Amaç hatanın kendi katmanında yakalanması;
bir üst katmanın sert kill'i devreye girerse hata hiç kaydedilemez.

```
ffprobe  20 sn   <   ffmpeg 1700 sn   <   RQ kuyruğu 1800 sn   <   kayıp eşiği 2700 sn
   │                    │                      │                        │
   │                    │                      │                        └─ süpürücü "worker bıraktı" der
   │                    │                      └─ RQ süreci sert öldürür (except ÇALIŞMAZ)
   │                    └─ ffmpeg kendi durur, hata yakalanır, sayaç artar
   └─ metadata okuması; uzarsa "emin değilsek transcode et"e düşer
```

Merdiven bozulursa (ör. ffmpeg timeout'u kuyruğunkinden büyük yapılırsa) hata
yolu tamamen kaybolur: RQ süreci öldürür, `except` çalışmaz, sayaç artmaz,
dosya `processing`de asılı kalır.

### 4.3 Akış

```
        başarısız deneme
               │
     attempts += 1
               │
    ┌──────────┴───────────┐
    │ attempts < 3 ?       │
    └──────────┬───────────┘
        evet   │   hayır
    ┌──────────┘        └────────────┐
    ▼                                ▼
next_at = now + backoff        DEAD-LETTER
durum: processing (değişmez)   durum: failed
denetim: ..._retry             next_at temizlenir
    │                          denetim: ..._failed
    ▼                                │
süpürücü (5 dk'da bir)               ▼
zamanı geleni kuyruğa koyar     yalnız İNSAN eliyle
                                (retry_video / retry_transcode)
```

**Retry kuyruğa anında konmaz.** `frappe.enqueue`'un gecikme parametresi yok
(v15), bu yüzden bekleme bir damga (`th_media_transcode_next_at`) üzerinden
yürütülür ve işi süpürücü alır. Bunun ikinci bir faydası var: aynı süpürücü,
worker'ın **bıraktığı** işleri de yakalar.

### 4.4 Bırakılmış iş (kayıp worker)

RQ zaman aşımı ya da OOM-killer süreci vurduğunda `except` bloğu **hiç
çalışmaz**. Sayaç artmaz, durum yazılmaz, dosya sonsuza kadar `processing`de
kalır ve kullanıcı dönen bir spinner görür.

Çözüm damga tabanlıdır: `th_media_transcode_started_at` işin kuyruğa girdiği
(ve worker'da başladığı) anı tutar. Süpürücü, `next_at` damgası olmayan ve
`started_at`'i 45 dakikadan eski olan `processing` kayıtlarını **başarısız
deneme** sayar — oradan itibaren normal retry/dead-letter yolu işler.

Damganın hiç olmaması da "kayıp" sayılır: alanı olmayan eski kayıtlar ya da
damgayı yazamadan düşen bir worker, süpürücünün göremediği kör nokta olurdu.

### 4.5 Sonsuz döngü neden yok

Üç koruma birden:

1. `attempts` her yolda artar (normal hata, kayıp iş, hepsi).
2. Dead-letter `next_at`'i temizler — süpürücünün kapsamından tamamen çıkar.
3. Kuyruğa koyarken `next_at` temizlenip `started_at` tazelenir; aynı dosya
   ikinci kez alınamaz.

Elle tetikleme (`retry_failed`) sayacı sıfırlar. Kasıtlı: insan bakıp "sorun
düzeldi, tekrar dene" diyorsa yeni bir iştir, eskisinin devamı değil.

### 4.6 İş HANGİ kayda ait: kuyruğa kayıt adı taşınır

Süpürücü KAYIT bazında çalışıyor (`processing` satırlarını tarıyor), ama iş
kuyruğa yalnız `file_url` ile konsaydı worker o adresteki **ilk** kaydı
bulurdu — 39 kayıtlı bir adreste bu neredeyse hiç doğru kayıt olmaz.

Sonucu şuydu: sayaç yabancı bir kayıtta artar, süpürücünün hedef kaydı ise
`next_at`'i temizlenmiş halde `processing`de kalır ve ancak 45 dakikalık kayıp
iş eşiğiyle ilerler. Kullanıcı 45 dakika boyunca dönen spinner görür.

Bu yüzden `_run_transcode(file_url, name)` kayıt adını da alır ve üç çağıran
(yükleme, elle retry, süpürücü) onu geçirir. `name` opsiyonel bırakıldı:
deploy anında kuyrukta bekleyen eski işler onu taşımıyor, o durumda eski
davranışa (adresten çözme) düşülür.

---

## 5. Kullanıcı görünürlüğü

| Ne gördüğü | Ne zaman | Nerede |
|---|---|---|
| "İşleniyor" rozeti (dönen ikon) | `processing` — ilk deneme ve tüm retry'lar boyunca | Satıcı listesi, kart görünümü, yönetim optimizasyon ekranı |
| Rozet yok | `ready` — olağan durum, rozetlemek gürültü | — |
| "İşleme başarısız" rozeti (kırmızı) | `failed` — dead-letter | Aynı üç ekran |
| "Yeniden İşle" düğmesi | Yalnız `failed` | Aynı üç ekran |

Düğmenin görünürlüğü **koruma sayılmaz**: satıcı ucu sahipliği, yönetim ucu
rolü yeniden doğrular; durum kuralı (`failed` dışında ret) tek yerde,
`transcode.retry_failed` içindedir.

Toplu işlerde (optimize / geri alma) ekran ilerleme çubuğunu yoklar ve
`completed` / `partial` / `error` durumlarının üçünde de yoklamayı durdurur.

---

## 6. Denetim kaydı

Her olay ADL'ye (`media/audit.py`) düşer. Retry ile dead-letter **ayrı
olaylardır** — "3 deneme yapıldı" bilgisi tek bir kayıttan çıkarılamaz.

| Olay | `reason` | Bağlam |
|---|---|---|
| Deneme başarısız, tekrar planlandı | `video_transcode_retry:<HataTipi>` | `attempt`, `retry_in` |
| Hak bitti, dead-letter | `video_transcode_failed:<HataTipi>` | `attempts` |
| Worker bıraktı | `video_transcode_retry:Abandoned` | `attempt`, `retry_in` |
| Elle yeniden deneme | — (`manual_retry: true`) | Kimin tetiklediği oturumdan |
| Toplu iş özeti | — | İş başına tek kayıt (dosya başına değil) |

Toplu işlerde denetim **iş başına** yazılır: 2.800 dosyalık bir işte dosya
başına kayıt ADL'i şişirir ve zinciri okunamaz kılar.

### 6.1 Yükleme kaydının kapsamı: uzantı süzgeci YOK

`audit.on_file_insert` bir dönem yalnız 17 görsel/video uzantısını kaydediyordu.
Ölçüm (19 Ağustos 2026, 5.724 dosya) neyin kaçtığını gösterdi:

| Denetim dışı kalan | Adet |
|---|---|
| `.txt` | 540 |
| `.csv` | 56 |
| `.xlsx` | 34 |
| `.pdf` | 14 |
| `.zip` | 8 |
| `.docx` | 1 |
| **Toplam** | **653** |

Bunların **13'ü KYB doğrulama belgesiydi** — sistemin en hassas kategorisi
denetimde hiç görünmüyordu. Üstelik AV taraması (TUR-125) o belgeleri tarayıp
`media.scan` yazdığı için ortaya cevaplanamaz bir iz çıkmıştı: bir PDF için
"tarandı" satırı var, "yüklendi" satırı yok.

**Kural:** kapsam uzantıyla daraltılmaz. "Kim ne zaman ne yaptı" sorusu dosya
türüne göre değişmez ve listeye eklenmeyen her yeni tür sessizce kayıt dışı
kalırdı (`media/av.py`'nin kapsamı daraltmama gerekçesiyle aynı).

`MEDIA_EXTENSIONS` listesi silinmedi ama **rolü değişti**: artık kaydın yazılıp
yazılmayacağını değil, iki şeyi belirliyor —

1. Denetim satırındaki `kind` etiketi (`media` / `document`), böylece "yalnız
   belge yüklemeleri" sorgusu yapılabiliyor.
2. Pahalı içerik-ikizi kontrolünün kapsamı: `content_hash` indeksli değil ve
   her belge yüklemesine tam tablo taraması eklemek toplu içe aktarımda
   ölçülebilir maliyet. Kontrolün amacı görsel sızıntısıydı (ölçülen 44
   kopyanın tamamı public+eksiz görsel desenindeydi), kapsamı da orada kalıyor.

**Maskeleme değişmedi:** private dosyalar ve hassas doctype ekleri kayda GİRER
ama kimliksiz yazılır. Yani KYB belgesi artık denetimde görünüyor, adresi ise
hâlâ görünmüyor — istenen tam olarak buydu.

---

## 7. Devreye alma ve operasyon

### 7.1 Çalışması neye bağlı

| Bağımlılık | Karşılanmazsa |
|---|---|
| **Site scheduler'ı açık** | **En kritik.** Backoff damga tabanlı ve işi süpürücü alıyor; scheduler duruyorsa retry HİÇ tetiklenmez ve videolar sonsuza kadar `processing` kalır. `bench --site <site> enable-scheduler` ile açılır |
| **`long` kuyruğunda worker** | Transcode hiç başlamaz. `bench worker` varsayılan olarak tüm kuyrukları tüketir |
| **`bench migrate` koşmuş** | `next_at` / `started_at` alanları oluşmaz (patch `v15_9_19`), süpürücü onları okuyamaz |
| **`ffmpeg` + `ffprobe` PATH'te** | Her video 3 denemeyi harcayıp `failed`'a düşer → kuyruk yükü **3 katı**. Deploy öncesi teyit edilmeli |

Kodda hiçbir sabit host, port, site adı ya da dosya yolu yok; her şey Frappe'nin
kendi bağlamından geliyor. Ortama özel yapılandırma gerekmiyor.

#### Scheduler nerede açılıp kapanıyor

Bayrak **repoda değil**, site'ın kendi veritabanında: `System Settings`
doctype'ının `enable_scheduler` alanı. Yani her ortamda (local / alpha / canlı)
ayrı ayrı kontrol edilmesi gerekiyor; merge ile taşınmaz.

| Yol | Ne yapar |
|---|---|
| Desk → **System Settings → Enable Scheduler** | DB alanını yazar. En kolay kontrol noktası |
| `bench --site <site> enable-scheduler` / `disable-scheduler` | Aynı DB alanını yazar |
| `sites/<site>/site_config.json` → `pause_scheduler` / `disable_scheduler` | **DB'yi EZER** |

Öncelik: `site_config.json` bayrağı varsa o kazanır, yoksa `System Settings`'e
bakılır. Bu yüzden Desk'te "Enable Scheduler" işaretli görünürken bile scheduler
durmuş olabilir — iki yere de bakmak gerekir.

> **Tuzak.** `bench migrate` başlarken `pause_scheduler`'ı 1 yapıp bitince
> siliyor. Migrate yarıda patlarsa o satır dosyada KALIR: deploy "başarılı"
> görünür, zamanlı işlerin hiçbiri koşmaz, hata da vermez. Süpürücünün
> çalışmadığından şüphelenildiğinde ilk bakılacak yer burasıdır.

Scheduler'ın yaşadığını doğrulamanın en hızlı yolu: Desk → `Scheduled Job Type`
listesinde `last_execution` sütunu. Tarihler son birkaç dakika içindeyse hat
çalışıyor; hepsi eski ya da boşsa scheduler durmuş.

### 7.2 Ayarlar kod sabiti — çalışma anında değiştirilemez

`jobs.py` ve `transcode.py` içindeki politika sayıları (deneme hakkı, backoff,
kayıp eşiği, zaman aşımları, süpürme periyodu) site ayarından okunmuyor.
Bilinçli: bunlar birbirine bağlı (merdiven ve backoff/süpürme çözünürlüğü) ve
tutarlılıkları testle korunuyor; ayrı ayrı elle değiştirilmeleri sessizce
bozardı. Değiştirmek **kod deploy'u** gerektirir.

Tek çalışma-anı kolu: süpürücü Desk'ten durdurulabilir —
**Scheduled Job Type → `transcode.sweep_stuck_transcodes` → `stopped`**. Sorun
çıkarsa deploy beklemeden kapatılır (retry durur, mevcut durumlar bozulmaz).

Süpürücü periyodu iki yerde birden yazılı ve **tutarlı kalmalı**: `hooks.py`
cron ifadesi ve `jobs.SWEEP_EVERY_SECONDS`. İkincisi backoff çözünürlüğünün
sınırı; testler ilişkiyi kontrol ediyor.

### 7.3 Ölçek

Süpürücü turu tek sorgu + en çok `limit=200` kayıt. Bir kuyruk kazası binlerce
dosyayı takılı bırakabilir; hepsini tek turda kuyruğa boşaltmak süpürücüyü
kendisi bir olay hâline getirirdi. 200'ü aşan birikme sonraki turlara yayılır —
5 dakikada 200 dosya, saatte 2.400.

---

## 8. Açık maddeler

1. **AV tarama kodlandı, tarayıcı kurulu değil** (TUR-125). `media/av.py` +
   karantina + retry/dead-letter + panel rozeti hazır ve testli; eksik olan tek
   şey imajda ClamAV bulunmaması. Kurulum yapılana kadar politika kendini
   kapatır (fail-open) ve hiçbir dosya taranmaz. Ayrıntı:
   `docs/MEDYA-AV-TARAMA.md`.
2. **EXIF temizleme ayrı adım değil** (TUR-132). Bugün yalnız yeniden encode
   yan etkisi olarak oluyor.
3. **Türev üretimi yok** (TUR-297).
4. **Toplu işlerde retry yok.** `run_batch` / `restore_batch` dosya bazında
   hatayı yutup `partial` bitiyor; işin tamamı için yeniden deneme yok —
   kullanıcı ekrandan yeniden başlatır. Bilinçli: toplu iş idempotent değil,
   otomatik tekrar aynı dosyaları yeniden işlerdi.
5. **ffmpeg dev imajında yok.** Video hattı local'de uçtan uca doğrulanamıyor;
   testler mock üzerinden koşuyor.
