# Medya Yükleme Sözleşmesi — istemci / sunucu sorumluluk ayrımı

**TUR-123** · Faz 1 · 2026-08-13

Bu belge medya işlemlerinin hangisinin tarayıcıda, hangisinin sunucuda
yapıldığını tanımlar. Tek cümlelik kural:

> **İstemcideki her kontrol hızlandırmak içindir. Karar her zaman sunucunundur.**

---

## 1. Neden bu belge yazıldı — ölçüm

Panelde **iki ayrı yükleme yolu** vardı ve kurallar yalnız birinde geçerliydi:

| Yol | Kaç ekran | Uygulanan kural |
|---|---:|---|
| `seller_media.upload_media` | **1** — medya kütüphanesi | uzantı izin listesi, 25 MB, mağaza kapsamı, denetim |
| Frappe `upload_file` | **22** | yalnız yasaklı uzantı kancası |

Yani satıcı ürün formundan görsel yüklerken boyut sınırı bile yoktu.
"Kurallar sunucuda" demek, kuralın **girilen her kapıda** olması demektir.

İkinci ölçüm — istemcide hiçbir doğrulama yoktu. `accept` özniteliği yalnız
dosya seçme penceresini süzüyor, seçilen dosyayı denetlemiyor. Sonuç: 21 MB'lık
bir dosya tarayıcıda base64'e çevriliyor (**%33 şişerek ~28 MB**), gönderiliyor
ve sunucuda reddediliyordu.

Üçüncü ölçüm — izin listesinde video uzantıları (`mp4`, `mov`, `webm`, `m4v`)
varken tavan 25 MB'dı. Ürünün video alanı var ama gerçek bir video
yüklenemiyordu.

---

## 2. Sorumluluk matrisi

| İşlem | İstemci | Sunucu | Yetkili |
|---|---|---|---|
| Dosya seçme süzgeci (`accept`) | ✅ sunucunun listesinden | — | — |
| Ad kontrolü (yol karakteri, boşluk) | ✅ hızlı ret | ✅ zorunlu | **Sunucu** |
| Uzantı izin listesi | ✅ hızlı ret | ✅ zorunlu | **Sunucu** |
| Yasaklı uzantı (svg/html/js…) | — | ✅ zorunlu | **Sunucu** |
| Boyut sınırı (tür başına) | ✅ hızlı ret | ✅ zorunlu | **Sunucu** |
| İçerik imzası (sihirli baytlar) | ✅ ilk 512 bayt | ✅ zorunlu | **Sunucu** |
| Tehlikeli içerik (HTML/SVG/script) | ✅ hızlı ret | ✅ zorunlu | **Sunucu** |
| Ad kırpma (140 karakter) | — | ✅ | **Sunucu** |
| Ön izleme (yükleme öncesi küçük resim) | ✅ | — | İstemci |
| İlerleme göstergesi | ✅ | — | İstemci |
| Parçalara bölme | ✅ | ✅ birleştirme + doğrulama | **Sunucu** |
| Yeniden deneme kararı | ✅ koda göre | ✅ kodu üretir | **Sunucu** |
| İptal | ✅ gönderimi durdurur | ✅ oturumu siler | Ortak |
| Mağaza kapsamı / sahiplik | — | ✅ oturumdan | **Sunucu** |
| Kalıcı kayıt (`File`) | — | ✅ | **Sunucu** |
| Denetim kaydı | — | ✅ | **Sunucu** |
| Üstveri temizleme | — | ✅ (TUR-132) | **Sunucu** |
| Dönüştürme / optimizasyon | — | ✅ (TUR-127/128) | **Sunucu** |
| Görsel sıkıştırma (WebP'ye çevirme) | ✅ önce dener | ✅ garanti tamamlar | **Sunucu** |
| Video normalize (transcode) | ✅ önce dener | ✅ kuyrukta garanti | **Sunucu** |
| Depolama kotası | — | ✅ zorunlu, aşımda ret | **Sunucu** |
| Dosya adı üretimi (içerik hash'i) | — | ✅ | **Sunucu** |

**İstemcide karar verilen hiçbir güvenlik kuralı yoktur.** Tarayıcıdaki tüm
kontroller sunucuda tekrarlanır; JavaScript kapatılsa ya da istek elle
gönderilse sonuç değişmez.

---

## 3. Sunucuda zorunlu kontroller

Kuralın tek sahibi `tradehub_core/media/upload_policy.py`. İki yerden birden
uygulanır:

```
medya uçları ──────────┐
                       ├──►  upload_policy.check()
File before_insert ────┘      (22 ekran buradan geçer)
      kancası
```

Kancaya bağlanması kritik: panelde yükleme yapan **22 ekranın hiçbirine
dokunmadan** hepsi aynı sözleşmeye girdi.

### Uygulanan kurallar

| Kural | Medya uçları | Kanca (diğer 22 ekran) |
|---|---|---|
| Yasaklı uzantı | ✅ | ✅ |
| Boyut sınırı | ✅ | ✅ |
| Tehlikeli içerik | ✅ | ✅ |
| Ad temizleme | ✅ | ✅ |
| İzin listesi (dar) | ✅ | ❌ kasten |

**İzin listesi neden kancada yok:** mevcut kanca bir *yasak* listesiydi. İzin
listesine çevirmek, listede olmayan ve bugün çalışan her akışı sessizce
kırardı. İzin listesi bizim kapımızda (medya uçları) dar tutulur.

### Kanca sırası — hangi kontrol önce çalışıyor

Frappe'nin `before_insert` çağrısında **önce kontrolör metodu, sonra kancalar**
çalışıyor. `File` kontrolörü orada kendi işini yapıyor: dosyayı diske yazıyor,
JPEG'in üstverisini temizliyor, kendi boyut tavanını uyguluyor. Bizim kanca
ondan sonra geliyor.

Pratik sonucu:

| Durum | Reddeden | Kullanıcının gördüğü |
|---|---|---|
| Boyut aşımı (genel yol) | Frappe (aynı eşik) | Frappe'nin mesajı |
| JPEG adıyla bozuk içerik | Frappe (görüntü açılamıyor) | Frappe'nin mesajı |
| **PNG/WEBP/GIF adıyla script** | **Bizim politika** | Kodlu, temiz mesaj |
| Ad kuralları | Bizim politika | Kodlu, temiz mesaj |
| **Medya kütüphanesi (her durum)** | **Bizim politika** | Kodlu, temiz mesaj |

Medya kütüphanesinde kodlu mesaj **her zaman** garantili, çünkü uç politikayı
`File` kaydı açılmadan ÖNCE çağırıyor. Genel yolda ise Frappe'nin kendi
kontrolü daha erken; dosya yine reddediliyor ama mesaj onun.

Kapatılan asıl boşluk şuydu: Frappe yalnız JPEG'i görüntü kütüphanesiyle
açıyor. **PNG, WEBP veya GIF adıyla gelen script içeriği hiç denetlenmiyordu.**
O yol artık bizim politikamızdan geçiyor.

### Boyut sınırları

| Tür | Politika sınırı | Gerekçe |
|---|---:|---|
| Görsel | 25 MB | Ölçüm: 4003 dosyada 25 MB üstü **yok**, en büyük 21 MB |
| Video | 200 MB | 25 MB tavan izin listesiyle çelişiyordu |
| Belge | 50 MB | |
| Diğer / bilinmeyen | 50 MB | Sınırsız bırakmak diski doldurmanın yolu |

> ⚠ **Frappe'nin kendi tavanı bu sınırların üstünde bir kapak.** Ölçümle
> bulundu: 26 MB'lık bir dosya bizim kurala hiç gelmeden
> `File size exceeded the maximum allowed size of 25.0 MB` ile düşüyor.
> Tavan `System Settings → max_file_size` (yoksa 25 MB) ile belirleniyor.
>
> Bu yüzden politika **gerçekleşebilir** sınırı ilan ediyor: her tür için
> `min(politika sınırı, Frappe tavanı)`. İstemciye 200 MB deyip 25 MB'da
> reddetmek, dosya yüklendikten sonra hayal kırıklığı olurdu.
>
> **Video yüklemesi gerçekten 200 MB olacaksa** site ayarındaki
> `max_file_size` yükseltilmeli. O ayar yükseltilene kadar video da
> pratikte 25 MB ile sınırlı. Ayarı yükseltmek görselleri gevşetmez —
> politika kendi 25 MB'ını uygulamaya devam eder.

### Tür uyuşmazlığı

Reddedilen yalnız **tehlikeli** uyuşmazlık: görsel diye gelen içeriğin
HTML/SVG/script olarak açılabilmesi. Saldırı budur.

Zararsız uyuşmazlık (adı `.png`, içi JPEG) reddedilmez, denetim kaydına uyarı
olarak yazılır — reddetmek sahadaki geçerli dosyaları keserdi. (Ölçüm: mevcut
1500 dosyada 0 uyuşmazlık; kural ileriye dönük.)

---

## 4. Büyük dosya: parçalı yükleme

**Karar: parçalı yükleme.** Doğrudan obje depolama (S3 imzalı URL) bugün
uygulanamıyor — dosyalar site diskinde duruyor ve depolama yapısı kararı
TUR-130'un konusu. Parçalı yükleme aynı depolamayla çalışıyor ve üç sorunu
birden çözüyor: bellek, gerçek ilerleme, gerçek iptal.

```
upload_begin(ad, toplam)   →  oturum kimliği, parça boyutu, parça sayısı
upload_chunk(kimlik, sıra) →  parçayı diske ekle          (tekrarlanabilir)
upload_finish(kimlik)      →  birleştir, POLİTİKA, kaydet
upload_abort(kimlik)       →  oturumu sil
```

| Parametre | Değer | Gerekçe |
|---|---:|---|
| Parça boyutu | 2 MB | Küçüğün bedeli istek sayısı, büyüğün bedeli bellek ve kopan parçanın yeniden gönderimi |
| Azami parça | 256 | Sayaç olmadan sonsuz parça = diski doldurma yolu |
| Tek parça eşiği | 8 MB | base64 %33 şişirdiği için ham sınırın altında |
| Oturum ömrü | 6 saat | Tarayıcı kapanınca parçalar diskte kalıyor |

**Politika birleşimden SONRA uygulanır.** Parça parça bakmak aldatıcı olurdu:
ilk parça geçerli bir görsel başlığı taşıyıp devamı bambaşka içerik olabilir.

**Oturumlar mağazaya bağlıdır.** Kimlik tahmin edilse bile başka mağazanın
oturumuna parça eklenemez; kapsam her adımda yeniden doğrulanır.

---

## 5. Hata yönetimi ve yeniden deneme

Her ret bir **kodla** döner. İstemci koda bakar, metne değil — metne bakmak
çeviri değişince kırılan bir sözleşme olurdu.

| Kod | Anlamı | Yeniden dene |
|---|---|:---:|
| `upload_name_required` | Ad okunamadı | ✗ |
| `upload_name_invalid` | Adda yol karakteri | ✗ |
| `upload_ext_denied` | Güvenlik nedeniyle yasak tür | ✗ |
| `upload_ext_not_allowed` | Kütüphanenin kabul etmediği tür | ✗ |
| `upload_too_large` | Boyut sınırı aşıldı | ✗ |
| `upload_content_empty` | Dosya boş | ✗ |
| `upload_content_unreadable` | İçerik çözülemedi | ✗ |
| `upload_content_dangerous` | İçerik türüyle uyuşmuyor ve güvenli değil | ✗ |
| `upload_store_required` | Mağaza hesabı yok | ✗ |
| `upload_session_unknown` | Oturum yok / süresi doldu | ✗ |
| `upload_chunk_order` | Parça sırası bozuk | ✓ |
| `upload_chunk_missing` | Parça eksik | ✓ |
| `upload_too_many_chunks` | Çok fazla parça | ✗ |
| `upload_quota_exceeded` | Mağazanın depolama kotası dolu | ✗ |

**Kural:** kullanıcının dosyasıyla ilgili hatalar yeniden denenmez — aynı dosya
aynı cevabı verir. Ağ kopması ve geçici sunucu hataları (5xx, 429) denenir.

**Otomatik deneme:** en çok 3 kez, aralar 1 sn → 3 sn → 8 sn. Ekranda geri
sayım görünür; kullanıcı beklemek istemezse iptal edebilir.

### Kullanıcıya gösterilen davranış

| Durum | Ekran |
|---|---|
| Ön kontrol reddi | Dosya hiç gönderilmez, satır kırmızı, sebebi yazılı |
| Yükleniyor | Gerçek yüzde + ilerleme çubuğu + iptal düğmesi |
| Geçici hata | "Bağlantı sorunu — {n} sn sonra {k}. deneme" + iptal |
| Kalıcı hata | Sebep metni + elle "Yeniden dene" düğmesi |
| Kota dolu | Kalıcı hata gibi davranır (`upload_quota_exceeded`), yer açması istenir |
| İptal | Satır kaldırılır, gönderim durur, sunucudaki oturum silinir |
| Bitti | Yeşil onay, liste yenilenir |

> **Yükleme sonrası işleme (TUR-296 ile kapandı).** Video normalize'i yükleme
> bittikten SONRA kuyrukta çalışıyor (`th_media_video_status`:
> `processing` / `ready` / `failed`). Bu durum artık liste ucundan
> `video_status` alanıyla dönüyor; panelde "işleniyor" ve "işleme başarısız"
> rozetleri gösteriliyor, başarısız videoda "Yeniden İşle" düğmesi çıkıyor.
> Deneme/geri çekilme politikası ve adım sırası ayrı belgede:
> `MEDYA-ISLEME-PIPELINE.md`.

---

## 6. API sözleşmesi

| Uç | Yöntem | İş |
|---|---|---|
| `upload_limits` | GET | Sunucunun uyguladığı sınırlar — istemci **buradan** alır |
| `upload_media` | POST | Tek parça yükleme (≤ 8 MB) |
| `upload_begin` | POST | Parçalı oturum aç |
| `upload_chunk` | POST | Parça gönder |
| `upload_finish` | POST | Birleştir ve kaydet |
| `upload_abort` | POST | Oturumu sil |
| `upload_status` | GET | Oturum durumu |

**Sınırlar istemciye yazılmaz, sunucudan alınır.** İki tarafa ayrı sabit
koymak, biri değişince sessizce ayrışan iki kural demekti: kullanıcı ekranda
kabul edilen dosyanın sunucuda reddedildiğini görürdü.

Mağaza kodu **hiçbir uçta parametre değildir**, oturumdan çözülür.

**Dönen ad gönderilen adla aynı olmayabilir.** Sunucu iki şeyi değiştirir:
görsel WebP'ye çevrilirse uzantı `.webp` olur, ve dosya diske içerik hash'iyle
yazılır (`<sha256[:32]>.<uzantı>`). İstemci **kendi gönderdiği adı değil,
yanıttaki `file_url` ve `file_name` alanlarını** kullanmalıdır. Aynı içerik
ikinci kez yüklenirse aynı adrese düşer — bu kasıtlı tekilleştirmedir, hata
değildir.

---

## 7. Değişen kararlar

Bu iş sırasında iki eski karar yeniden değerlendirildi:

**İptal artık gerçekten iptal ediyor.** Eskiden satır listeden siliniyor ama
istek sunucuya gitmeye devam ediyordu; kullanıcı iptal ettiğini sandığı dosyayı
listede buluyordu. Gerekçe "yarıda kesilen yüklemenin sunucuda ne bıraktığı
belirsiz" idi — parçalı yüklemede artık belirsizlik yok, oturum siliniyor.

**Çok parçalı gönderim (multipart) hâlâ kullanılmıyor.** Yorumda "bu kurulumda
CSRF uyuşmazlığı üretiyor" yazıyordu; oysa genel yükleme ucu aynı uygulamada
multipart'ı sorunsuz kullanıyor (CSRF anahtarını ayrıca alıp başlığa koyarak).
Yani engel multipart değil, önceki denemenin anahtarı taşıma biçimiydi. Buna
rağmen base64 korundu: parçalı yükleme gerçek ilerleme ve iptal sorununu zaten
çözüyor, taşıma biçimini değiştirmek ek bir kazanç sağlamadan çalışan bir yolu
riske atardı.

---

## 8. Nasıl doğrulandı

Yedi bölümde **57 ayrı test türü**, üstüne 6 regresyon koşumu. Aynı iddianın
tekrarı değil; her tür farklı bir soruyu soruyor.

| Bölüm | Ne sorar | Tür |
|---|---|---:|
| A · politika birimi | Kural doğru mu (izin, yasak, boyut, ad, imza, tehlike, kod sözleşmesi) | 10 |
| B · kanca yolu | Medya kütüphanesi **dışındaki** 22 ekran da korunuyor mu | 7 |
| C · parçalı yükleme | Yeni kapıda aynı kilit var mı (sırasız, tekrar, eksik, kaçış, kapsam) | 13 |
| D · uçtan uca | Uçlar üzerinden gerçek yükleme, yetki, kapsam, denetim | 10 |
| E · dayanıklılık | Fuzz, maymun, eşzamanlılık, tekilleştirme, disk sızıntısı | 6 |
| G · gerçek yük | Sürekli yük, başarım sapması, bellek, büyük dosya tekrarı, artık | 8 |
| H · eşleşme | İstemci ve sunucu **aynı kararı** veriyor mu | 3 |
| F · regresyon | TUR-131/136/138/140'ın 81 testi hâlâ geçiyor mu | 6 |

### Testlerin bulduğu dört gerçek sorun

**1. Frappe'nin kendi tavanı ilan ettiğimiz sınırı yalanlıyordu.** Politika 200
MB video diyordu ama `File` kaydı 25 MB'da düşüyordu. Artık ilan edilen sınır
`min(politika, platform)` — istemciye ulaşılamayan bir sayı verilmiyor.

**2. İstemci ile sunucu farklı SEBEP dönüyordu.** Karşılaştırmada `.svg` için
sunucu "güvenlik nedeniyle", istemci "kabul edilmiyor" diyordu. Yasak liste de
sunucudan gönderilerek giderildi.

**3. İstemci ile sunucu farklı KARAR veriyordu.** `" .pdf"` gibi adlarda sunucu
"uzantısız gizli dosya" deyip reddederken istemci geçerli PDF sanıyordu.
20.000 girdide 16 ayrışmanın tamamı bu kalıptandı; uzantı ayıklama sunucunun
kuralına hizalandı. Son ölçüm: **20.000 girdi, 0 ayrışma**.

**4. Kanca sırası** (§3) testlerle ölçüldü, varsayımla değil.

### Kasıtlı olarak reddedilmeyenler

Test yazarken iki şey "hata değil" diye işaretlendi ve sebebi kayıtlı:

- **Zararsız tür uyuşmazlığı** (`.png` adlı JPEG) — reddedilmiyor, uyarı olarak
  denetime yazılıyor. Reddetmek sahadaki geçerli dosyaları keserdi.
- **Ad uzunluğu** — istemci reddetmiyor, sunucu kırpıyor. Kullanıcıyı uzun ad
  yüzünden geri çevirmek gereksiz sürtünme.

---

## 9. Kapsam dışı

| Konu | Nerede |
|---|---|
| EXIF temizleme, gerçek mime doğrulaması | TUR-132 |
| Kırpma / ölçekleme | TUR-127 |
| Obje depolama (S3 vb.), CDN | TUR-129 |
| Public/private erişim modeli | TUR-126 |

> **2026-08-14 güncellemesi.** Bu tablodan üç satır çıktı: optimizasyon/
> dönüştürme (TUR-128), depolama dizin yapısı ve adlandırma (TUR-130/141) ve
> mağaza depolama kotası (TUR-139) artık *kapsam dışı değil* — üçü de yükleme
> akışının içinde çalışıyor ve §2 matrisine işlendi. Kota, yüklemeyi **reddedebilen**
> ikinci sunucu kapısıdır; reddi bu belgedeki kod sözleşmesinden geçer
> (`upload_quota_exceeded`).
