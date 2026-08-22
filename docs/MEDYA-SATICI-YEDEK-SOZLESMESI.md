# Satıcı Medya Yedeği — Sözleşme

**Linear:** TUR-131 · **Faz:** 4 · **Kabul kriteri notu:** issue 16 Ağustos'ta yeniden
açıldı ve kriterlere tek satır eklendi: *"SATICI TARAFINDA OLACAKTIR"*. Bu belge o
satırın karşılığıdır.

**Bağlı belgeler:** `MEDYA-ISLEME-PIPELINE.md` (kuyruk işleri ve durum sözlüğü),
`MEDYA-YUKLEME-SOZLESMESI.md` (yükleme anı).

---

## 1. İki yedek var ve karıştırılmamalı

| | Yönetim yedeği | Satıcı yedeği |
|---|---|---|
| Kod | `media/backup.py`, `media/restore.py` | `media/seller_backup.py` |
| Ekran | `/media-backup` (`requiresSuperAdmin`) | `/my-media-backup` (satıcı) |
| Kapsam | **Tüm** dosyalar + **tüm** `File` satırları | Yalnız o mağazanın kapsamı |
| Depo | `private/media-backups/` (tek havuz) | `private/media-seller-backups/<store>/` |
| Amaç | Platformun felaket kurtarması | Satıcının kendi verisine sahip olması |
| Veritabanı yapı künyesi | var (`schema.py`) | **yok** — satıcının işi değil |
| Budama / saklama politikası | elle + zamanlanmış | otomatik, mağaza başına 5 set |

İkisi ayrı modül. Ortak kod yalnız `backup.file_hash` — imza hesaplama.

## 2. Havuz neden mağaza başına ayrı

Platform havuzunu paylaşmak depolamada cazip: aynı içeriği iki mağaza yüklemişse
tek blob tutulurdu. **Yapılmadı.** Paylaşılan havuzda bir mağaza yedeğini
silince, sayaç o içeriği yetim sanıp kaldırır ve **diğer mağazanın yedeği
sessizce bozulur**. Kiracı izolasyonu birkaç mükerrer bayttan önce gelir.

Maliyet: yedek deposu kabaca "medyanın bir kopyası + değişimler" kadar yer tutar.
Ölçüm için bkz. §7.

## 3. Kapsam: OKUMA ile YAZMA farklı

Bu ayrım bu belgenin en önemli maddesi.

`ownership.scope` iki yoldan sahiplik tanıyor:

1. mağazanın kullanıcılarının **YÜKLEDİĞİ** dosyalar
2. mağazanın kayıtlarında **KULLANILAN** dosyalar

İkincisi kütüphane görünümü için doğru: satıcı, ürününde duran görseli
görmelidir — kim yüklemiş olursa olsun.

| İşlem | Kapsam | Gerekçe |
|---|---|---|
| Yedek alma (`create`) | Kütüphaneyle **aynı** (1 + 2) | "Yedeğim neyi kapsıyor" sorusunun cevabı ekranla birebir aynı olmalı |
| Pakete koyma / indirme | Kütüphaneyle **aynı** (1 + 2) | Satıcı o dosyaları panelde zaten görüyor ve indirebiliyor; yeni bir sızıntı değil |
| Künye (`kunye.csv`) satırları | Yalnız **kendi kayıtları** | Paylaşılan adreste başka mağazanın kaydı da var; onu pakete koymak o kiracının verisini sızdırırdı |
| **Geri yazma** (`apply`) | Yalnız **YÜKLEDİĞİ** (1) | Aşağıya bak |
| Kayıt kurma (`apply`) | Yalnız `owner` mağazanın kullanıcısı olan kayıtlar | Paket kurcalanıp başka kiracının kaydı enjekte edilemesin |

### 3.1 Neden geri yazma daraltıldı (bulunan açık)

Yazma kapsamı başta okuma ile aynıydı. Sonucu şuydu:

> A mağazası, B'nin yüklediği ama A'nın ürününde kullandığı bir dosyayı
> yedeğine alıyor. Daha sonra B o dosyayı optimize ediyor ya da yenisiyle
> değiştiriyor. A `overwrite` ile geri yükleme yapınca **B'nin bugünkü
> dosyasını eski hâline döndürüyor** — B'nin hiçbir onayı olmadan.

Ölçüm: 30 adres iki mağazaya birden ait (`media/ownership.py`). Yani bu teorik
bir senaryo değil.

Çözüm: `_uploaded_urls(store)` — geri yükleme yalnız mağazanın kendi
yüklemelerine yazar. Kalanı `skipped_not_owned` olarak döner ve ekranda
**"Başka mağazanın yüklediği"** satırı olarak görünür.

> **Kural.** Planın gösterdiği her sayı, uygulamanın gerçekten yapacağı işe
> karşılık gelmelidir. Yapılmayacak bir işi planda göstermek, kullanıcıya
> tutulamayacak bir söz vermektir.

## 4. Geri yükleme kuralları

`media/restore.py` ile aynı üç kural, çünkü tehlike aynı — yanlış çalışırsa
bugünkü veriyi dünkiyle ezer.

1. **Önce plan.** `plan()` hiçbir şeye dokunmadan ne olacağını söyler. Uygulama
   ayrı bir çağrı; kimse yanlışlıkla geri yükleme başlatamaz.
2. **Asla silmez.** Yedekten sonra yüklenen dosya `extra` diye raporlanır ve
   dokunulmaz. Silmek "geri yükleme" adı altında veri kaybı olurdu.
3. **Değişmiş dosyanın üzerine yazmaz.** Aynı yolda farklı içerik varsa bu bir
   çatışmadır; `overwrite=True` ile ve açıkça istenmeden yazılmaz.

Durum sınıfları:

    ok             yol var, içerik yedekle aynı              → dokunma
    missing_file   yedekte var, dosya diskte yok             → geri yaz
    conflict       yol var ama içerik farklı                 → sorma olmadan dokunma
    missing_record dosya var, `File` kaydı yok               → kaydı yeniden kur
    extra          bugün var, yedekte yok                    → dokunma, yalnız say
    not_owned      yedekte var, mağaza yüklememiş            → dokunma, yalnız say

`extra` hesaplanırken **disk kontrolü şart**: kaydı olup dosyası kaybolmuş bir
adres yedeğe hiç girmemiştir ve "yedekten sonra eklenmiş" gibi görünürdü.
Kullanıcıya "2 yeni dosyan var" demek, aslında 2 dosyasını kaybettiği anlamına
geliyordu (gerçek veride yaşandı).

## 5. Pakette ne var, ne YOK

    dosyalar/<yol>   medya dosyaları, yedekteki hâliyle
    kunye.csv        dosya başına bir satır, okunabilir künye
    ozet.txt         ne zaman alındı, ne kadar, neler eksik

**Ham veritabanı çıktısı bilerek verilmiyor.** `File` tablosu tüm kiracıların
verisi ve iç işleyişe ait alanlar taşıyor. Satıcının ihtiyacı "hangi dosya
neydi, nerede kullanılıyordu" bilgisi; onu CSV karşılıyor ve bir insan
okuyabiliyor.

### 5.0 Sistem yedeğinin alan kapsamı — 21 Ağu 2026 genişlemesi

Bu bölüm satıcı paketini değil, `media/backup.py`'nin aldığı **sistem
yedeğini** ilgilendiriyor; ikisi ayrı (bkz. §1) ama alan listesi ortak
gerekçeyi paylaşıyor: yedeklenmeyen alan, geri yüklemede kaybolan alandır.

Listeye eklenen 20 alan ve neden:

| Grup | Alanlar | Kaybolursa ne olur |
|---|---|---|
| **Tarama** (TUR-125) | `scan_status`, `scan_attempts`, `scan_started_at`, `scan_next_at` | Geri yüklenen dosyalar "hiç taranmamış" görünür ve AV kancası hepsini yeniden kuyruğa alır; daha kötüsü **karantina damgası kaybolur** — zararlı bulunmuş dosya temiz sayılıp yeniden servis edilir |
| **Dönüştürme** (TUR-296) | `transcode_attempts`, `transcode_started_at`, `transcode_next_at` | "Üç kez denendi, bırakıldı" bilgisi gider; süpürücü baştan dener |
| **SEO** (TUR-135) | `caption`, `alt_source`, `alt_ai`, lisans beşlisi, `usage_rights`, `rights_expires_on`, `seo_filename`, `slug`, `canonical` + `alt/title/caption` × 4 dil | Alt metinleri, telif ve lisans bilgisi gider — yeniden üretilemeyen insan emeği |

Video durumu (`th_media_video_status`) 13 Ağu'da zaten eklenmişti ve
yanındaki not aynı tuzağı anlatıyordu ("yedeklenmezse geri yüklenen video
hiç işlenmemiş görünür ve ffmpeg diskteki dosyayı ezer"). AV işi 17 Ağu'da,
yedekten SONRA geldiği için tarama alanları listede kalmıştı; 21 Ağu
denetiminde ölçülerek kapatıldı.

Dil kolonları tek tek yazılmıyor, `("alt","title","caption") × 4 dil`
üretiliyor: beşinci bir dil eklenirse liste kendiliğinden büyür.

**Hâlâ kapsam dışı (bilinçli):** medya motorunun tabloları — `Media Asset`,
`Media Version`, `Media Rendition`, `Media Usage`, crop niyet/ezmeleri.
Bayrak kapalıyken bu tablolar boş; açılmadan ÖNCE kapsama alınmaları
gerekiyor (ADR-0023 "bayrak öncesi üç ön koşul", madde 2). Motorun S3/ayna
yedeği DOSYAYI kopyalıyor, KAYDI değil — ikisi birbirini tamamlamalı.

### 5.1 Künye neden dosya başına

Kayıt başına yazmak yanıltıyordu. İçerik-adresli adlandırma yüzünden aynı
içerik birden çok kez yüklendiğinde tek fiziksel dosyaya birden çok `File`
kaydı düşüyor — ölçüm: **20 dosyaya 27 kayıt**, bir görsel 5 kez yüklenmiş.
Künyede 27 satır görünce satıcı "20 dosyam vardı, 27 nereden çıktı" diyor;
kütüphanesi de 20 gösteriyor.

Omurga artık manifest'teki dosya listesi; kayıtlar üstüne bindiriliyor.
`Kaç kez yüklenmiş` ve `Kayıt kimlikleri` sütunları bu ilişkiyi açık ediyor.

CSV ayrıntısı: ayraç **noktalı virgül** (Excel Türkçe yerelde virgülü ayraç
saymıyor) ve başında **BOM** var (yoksa Excel Türkçe karakterleri bozuyor).

## 6. Kiracı sınırı nasıl tutuluyor

| Yüzey | Koruma |
|---|---|
| Mağaza kimliği yola giriyor | `_STORE_RE` kalıbı + `realpath` kök kontrolü |
| Yedek kimliği yola giriyor | `_SET_ID_RE` kalıbı + `realpath` kök kontrolü |
| İçerik imzası yola giriyor | `[0-9a-f]{64}` tam eşleşme |
| Manifest'teki göreli yol | `realpath`, public kök altında kalmalı (manifest kurcalanmış olabilir) |
| HTTP uçları | Mağaza **oturumdan** çözülüyor; parametre olarak ALINMIYOR |
| Yazma uçları | `methods=["POST"]` |
| Kayıt kurma | `owner` mağazanın kullanıcısı olmalı |

Testler bu sınırı zorluyor: `../../etc`, `..`, `/etc`, `%00`, 65 karakterlik
mağaza kimliği, bozuk imza, başka mağazanın set kimliği, paketi kurcalayıp
kayıt enjekte etme. Canlı doğrulama: B mağazası A'nın set kimliğini bilse bile
manifest'i okuyamıyor.

## 7. Saklama, kota ve hız sınırı

| Ayar | Değer | Gerekçe |
|---|---|---|
| Mağaza başına set | **5** | Havuz artımlı; 5 set ≈ 1 kopya + değişimler |
| Sınır aşımı | En eski **otomatik** düşer | Satıcıdan "yer aç" istemek yedeklemeyi caydırırdı |
| Yedekler arası asgari süre | **10 dk** | Düğmeye üst üste basmak diski tarar, CPU yakar ve listeyi anlamsız kılar |
| Son yedek | **Silinemez** | "Yedeğim var" sanısıyla tek kopyayı kaybetmek en pahalı hata |
| Disk kontrolü | Son yedeğin boyutu × 1,2 | Dolu diskte yarıda durmaktan iyidir |
| Paket saklama | 24 saat | Yedeğin kendisi duruyor; paket yalnız taşıma biçimi |

Havuzdaki bir içerik ancak **hiçbir yedek onu göstermiyorsa** silinir. Sayaç
şart: paylaşılan içeriği erken silmek kalan yedekleri sessizce bozardı.

## 8. Denetim kaydı

| Olay | `action` | Bağlam |
|---|---|---|
| Yedek alındı | `media.backup` | set kimliği, dosya/kayıt sayısı, düşen set |
| Geri yüklendi | `media.restore` | yazılan, ezilen, atlanan çatışma, atlanan sahiplik, kurulan kayıt |
| Paket üretildi / indirildi | `media.export` | set kimliği, dosya sayısı, boyut, indiren |

Yedek almak veriyi değiştirmez ama disk tüketir ve "ne zaman yedek aldım"
sorusunun cevabı denetimden okunabilmelidir — bu yüzden geri yüklemeden ayrı
bir olay.

## 9. Açık maddeler

1. **Bayt kotası yok.** Set sayısı sınırlı ama boyut sınırı yok. Platform
   genelinde medya depolaması kabaca ikiye katlanıyor. Çok medyalı mağazalar
   için plan bazlı bir kota (`entitlement`) gerekebilir. Güvenlik sorunu değil,
   kapasite kararı.
2. **Yedek medyayla aynı diskte.** Disk arızasında ikisi de gider. Uzak depo
   kararı verilmedi — yönetim yedeğinde de aynı açık madde duruyor.
3. **Paylaşılan dosya kaybolursa satıcı onu geri getiremez.** §3.1'in kaçınılmaz
   sonucu: dosya başka mağazanın yüklemesi. O durumda yönetim yedeğinden
   getirilmesi gerekir; satıcıya bu ekrandan bir yol verilmedi.
4. **`kunye.csv`'de paylaşılan dosya satırı boş görünür** (kayıt künyesi o
   mağazaya ait değil): dosya adı disk adına düşer, "kaç kez yüklenmiş" 0 olur.
   Doğru ama şık değil.
