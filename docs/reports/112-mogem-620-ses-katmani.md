# MOGEM-620 · Ses medyası katmanı — teslim ve E2E raporu

**Tarih:** 6 Eylül 2026
**Kapsam:** MOGEM-620 §6 (Structured Data) ve §15 (File Manager) — ses dosyaları
**Durum:** kodlandı, test edildi, commit edildi (8 Eylül 2026)

---

## 1. Neden bu iş

MOGEM-620 Plane'de **Backlog** durumunda ve **hiç alt görevi yok** (projedeki 321
kaydın tamamı tarandı; hiçbirinin ebeveyni 620 değil). Yani Plane'in kendi
hesabına göre ilerleme %0 görünüyor.

Kod tarafında durum farklı: 20 kabul kriterinin 8'i tam, 9'u kısmen karşılanmış.
Kabaca **%65 tamamlanmış**; AI/semantik katman hariç tutulduğunda **%75**.

Kalan %25'in içinde ses dosyaları vardı ve **%40** seviyesindeydi:

| Kabul kriteri | Denetimden önce |
|---|---|
| §6 — dört şema türü (Image/Video/Audio/DigitalDocument) | Üçü var, **AudioObject yok** |
| §15 — ses için başlık, sanatçı, süre, kapak, AudioObject | **Hiçbiri yok** |

Bu belge o boşluğun kapatılmasını ve bulunan kusurları kayda geçiriyor.

---

## 2. Yapılan iş

### 2.1 `AudioObject` şeması

`tradehub_core/seo/schema_builder.py` → **`build_audio_object`**

Mevcut `build_video_object` / `build_digital_document` kalıbının aynısı:
geçersiz yapısal veri hiç üretilmez, ad `title`'dan yoksa dosya adı gövdesinden
türer, ikisi de boşsa `None` döner.

**Alan eşlemesi şemaya göre yapıldı, isteğe göre değil.** Şartnamede "sanatçı"
geçiyor ve akla ilk gelen karşılık `byArtist`; ama o alan schema.org'da
`MusicRecording`/`MusicGroup`'a ait — genel bir ses dosyasında geçersiz
yapısal veri olurdu. `AudioObject`, `MediaObject → CreativeWork` zincirinden
geldiği için doğru karşılık **`author`**:

| Şartname | schema.org alanı | Gerekçe |
|---|---|---|
| sanatçı | `author` | `byArtist` MusicRecording alanı — burada geçersiz |
| kapak | `thumbnailUrl` | CreativeWork alanı |
| dil | `inLanguage` | CreativeWork alanı |
| süre | `duration` (ISO-8601) | MediaObject alanı |
| transkript | `transcript` | MediaObject alanı |

`author` ile `creator` **çakışmaz, ikisi birden basılabilir**: `creator` lisans
beşlisinden gelir (hakları elinde tutan kurum), `author` sesi üreten kişidir.
Bir podcast'te ikisi gerçekten farklıdır.

### 2.2 Ses metadata çıkarımı

`tradehub_core/media/audio_meta.py` (yeni) — başlık, sanatçı, süre, gömülü kapak.

**ffprobe/ffmpeg seçildi, yeni kütüphane değil.** `mutagen` eklemek ID3/MP4/Vorbis
etiketlerinin her birini ayrı çözmek demekti. ffprobe zaten kurulu
(`video_poster` ve `pipeline/video/probe.py` onu kullanıyor) ve kapsayıcıdan
bağımsız tek bir `format.tags` sözlüğü döndürüyor — MP3 `TIT2` ile M4A `©nam`
aynı `title` anahtarına iniyor. Yeni bağımlılık yüzeyi açılmadı.

**Kapak üretilmez, çıkarılır.** Ses dosyasında video posterindeki gibi "temsili
kare" kavramı yok; ya kapsayıcıda gömülü kapak (`attached_pic`) vardır ya yoktur.

**Hata sözleşmesi** `video_poster`/`doc_meta` ile aynı: hiçbir hata kullanıcının
yüklemesini ya da kuyruk işini düşürmez. Başarısız çıkarımda
`th_media_duration = -1` anti-açlık damgası yazılır ki `backfill_pending` aynı
okunamayan dosyayı her turda yeniden seçmesin — `doc_meta`'nın
`page_count = -1` damgasıyla aynı desen. Negatif süre dışarıya sızmaz:
`seo._birlestir` `max(0, …)` nöbetçisiyle durdurur.

### 2.3 Şema alanları — tek yeni kolon

`patches/v15_9_53_media_audio_fields.py` yalnız **`th_media_artist`** ekliyor.
Diğer üçü yeniden açılmadı:

| Alan | Nereye yazılıyor | Neden yeni kolon değil |
|---|---|---|
| başlık | `th_media_title*` | v15_9_37'nin 4 dilli alanları; `doc_meta` PDF `/Title`'ı da oraya yazıyor |
| süre | `th_media_duration` | v15_9_49; videoyla aynı fiziksel gerçek |
| kapak | `th_media_poster_url` | "medyayı temsil eden sabit görsel" videoda poster, seste kapak — aynı kavram |

`fields_for` çıktısında `cover_url` **ayrı kolon değil**, `poster_url`'in ses
tarafındaki adı. İkinci bir kolon açmak aynı gerçeği iki yerde tutmak olurdu.

`th_media_artist` yeni çünkü karşılığı yok: `th_media_creator` hakları tutan
kurumdur, sanatçı sesi üreten kişidir.

### 2.4 Yükleme politikası — `KIND_AUDIO`

`media/upload_policy.py`: yeni tür, 7 uzantı (`.mp3 .m4a .aac .ogg .opus .wav
.flac`), 100 MB tavan, `MEDIA_KINDS`'a dahil.

Ses `MEDIA_EXTRA_EXTENSIONS`'a **değil** `MEDIA_KINDS`'a eklendi. `.pdf` oradaki
tek istisna çünkü doküman bir medya değil, medya ucundan geçmesi gereken bir ek.
Ses ise tam anlamıyla medya: süresi, kapağı, kendi şeması, kendi çıkarım hattı
var. Uzantı istisnası olarak eklemek `upload_limits` gibi türe göre rapor veren
uçlarda onu "türsüz" gösterirdi.

Uzantı listesi **tek kaynakta** (`upload_policy.AUDIO_EXTENSIONS`);
`audio_meta.AUDIO_UZANTILAR` onu içe aktarıyor, kendi listesini tutmuyor.
`video_poster.VIDEO_UZANTILAR`/`doc_meta.DOC_UZANTILAR` emsalinden bilerek
ayrıldık — bkz. §3.1.

---

## 3. Testin bulduğu kusurlar

Altı kusur bulundu; **dördü kodda, ikisi yazdığım testlerdeydi.** Ayrıca test
altyapısının kendisinde bir yanılgı kaynağı ortaya çıktı (§4).

### 3.1 Hiçbir ses dosyası yüklenemiyordu

`upload_policy.EXTENSIONS` haritasında ses türü yoktu.
`naming._hashed_name` beyaz listeyi oradan okuyor ve `.mp3`'ü
*"İzin verilmeyen dosya uzantısı"* ile reddediyordu.

Bu **birebir `.pptx` kusurunun tekrarı**: çıkarım motoru `.pptx`'i destekliyordu
ama harita bilmediği için hiçbir `.pptx` yüklenemiyordu ve durum Task 5'e kadar
fark edilmedi. Aynı sapmanın seste tekrarlanmaması için uzantı listesi tek
kaynağa bağlandı.

### 3.2 Ses medya ucunun dar kapısından geçmiyordu

`MEDIA_KINDS` yalnız görsel + video kabul ediyordu.
`seller_media.upload_media` her ses yüklemesini reddediyordu — şema, çıkarım ve
denetim yazılmış ama **satıcı dosyayı hiç yükleyemiyordu.** E2E'nin A ve F
grupları (7 hata) bunu ortaya çıkardı.

### 3.3 Dosya yolu shard dizinini atlıyordu

`_yerel_yol` yolu `Path(file_url).name` ile elle kuruyordu; içerik-adresli
adlandırma dosyaları hash önekine göre alt dizine koyuyor (`naming._shard`,
00–ff). Her ffprobe çağrısı *"dosya bulunamadı"* dönüyordu.
`File.get_full_path()`'e geçildi — shard'ı da public/private ayrımını da o
biliyor (`video_poster.generate` aynı yolu kullanıyor).

### 3.4 `LIKE '%.mp3'` SQL'i patlıyordu

`backfill_pending` ham SQL'de `LIKE '%.mp3'` kullanıyordu; pymysql `%.m`'yi
biçim karakteri sanıp *"unsupported format character 'm'"* atıyordu. `%%` ile
kaçırmak uzantı listesini SQL metnine gömmek demekti; `or_filters`'a geçildi —
hem bu tuzağı hem de f-string SQL yasağını (repo kuralı 11) birden çözüyor.

### 3.5 Tek kardeşe bakan yol çözümü *(3.3'ün ardından çıktı)*

Aynı adrese işaret eden `File` kayıtlarından yalnız biri diske gerçekten
yazılmış olabiliyor. İlk kayda çarpan sürüm dosyayı "yok" sayıyordu; artık
hepsi deneniyor.

### 3.6 Kendi testlerimdeki iki hata

| Test | Yanlış varsayım | Gerçek sözleşme |
|---|---|---|
| `set_asset_fields` reddi | istisna atar | **sessizce 0 döner** — beyaz liste dışı anahtar `izinli` sözlüğüne hiç girmez |
| `upload_policy.check` reddi | `ok=False` döner | **`reddet()` ile istisna atar** |
| kardeş kayıt kurulumu | `file_url`'ü elle verilen bağ kaydı | **aynı baytları ikinci kez yüklemek** — içerik-adresli adlandırma ikisini aynı adrese düşürür |
| uzantı/içerik uyuşmazlığı | reddedilir | **uyarı üretir, reddetmez** (bkz. §3.7) |

Dördünde de kod değil test düzeltildi.

### 3.7 Uyuşmazlık sözleşmesi — kasıtlı bir karar

`.mp3` adıyla gelen PNG içeriği **reddedilmiyor, uyarı olarak kaydediliyor.**
İlk bakışta güvenlik boşluğu gibi duruyor; değil:

- **Tehlikeli** uyuşmazlığı (`<svg onload=…>` gibi çalıştırılabilir işaretleme)
  `_derin_denetim` daha yukarıda reddediyor — E2E `a7b` bunu ses uzantısında da
  kanıtlıyor.
- Kalan tek gerçek örnek hareketsiz kap uyuşmazlığı ve **ölçümle**
  gerekçelendirilmiş: 4.584 public dosyada 1 adet `.mp4` içinde webm; tarayıcı
  `MediaRecorder` çıktısında yaygın.

E2E bu sözleşmeyi artık **sabitliyor**: biri sessizce rette çevirirse meşru
yüklemeler kırılır ve test bunu gösterir.

---

## 4. Test altyapısında bir yanılgı kaynağı

**`frappe.only_for` testte hiçbir şey yapmıyor.** `frappe/__init__.py:954`:

```python
if local.flags.in_test or local.session.user == "Administrator":
    return
```

Sonucu ağır: `FrappeTestCase` altında yazılan **her "bu rol reddedilmeli"
iddiası kendiliğinden geçer ve hiçbir şey ölçmez.**

Bu dosyanın ilk koşumunda tam olarak bu oldu — üç yetki testi *"açık bulundu"*
diye **yeşil-yanlış** verdi. Kaynak okunmasaydı gerçek olmayan bir güvenlik
açığı rapor edilecekti: *"rakip satıcı başkasının SEO alanını ezebiliyor."*

Çözüm: `gercek_yetki()` bağlam yöneticisi bayrağı **yalnız ölçülen çağrının
etrafında ve dar kapsamda** indiriyor (`in_test` e-posta, arka plan işi gibi
başka davranışları da etkiliyor).

Ayrıca **nöbetçi test** eklendi (`test_c7`): bayrak açıkken kapının hiç
çalışmadığını, indirilince reddettiğini ayrı ayrı kanıtlıyor. Biri
`gercek_yetki`'yi kaldırırsa C grubu sessizce boşalmaz — bu test kırılır ve
neden kırıldığı belli olur.

> **Repo geneli için not:** aynı yanılgı bu dosyaya özgü değil. `only_for`
> tabanlı rol reddini sınayan başka testler de yeşil-yanlış veriyor olabilir.
> Ayrı bir denetim işi.

---

## 5. Test envanteri

| Dosya | Test | Kapsam |
|---|---|---|
| `test_media_audio_seo.py` | 20 | `build_audio_object` saf fonksiyonu — iskelet, alanlar, kapak geri düşüşü |
| `test_media_audio_meta.py` | 15 | `audio_meta` modülü — şema, çıkarım, uygulama, backfill |
| `test_e2e_media_audio.py` | **46** | uçtan uca, altı kimlik, iki kiracı |
| **Toplam** | **81** | |

### E2E kimlikleri

| Kimlik | Rol | Rolü ne sınıyor |
|---|---|---|
| A-sahip | Marketplace Seller + Verified Seller | normal satıcı akışı |
| A-personel | Marketplace Seller, aynı kiracı | mağaza içi ikinci kullanıcı |
| B-sahip | Marketplace Seller, ayrı kiracı | **saldırgan** — çapraz kiracı sızıntısı |
| alıcı | Buyer, mağazası yok | mağazasız kullanıcı kapısı |
| admin | Marketplace Admin | yönetim uçları |
| Guest | — | oturumsuz erişim |

### E2E grupları

| Grup | Test | Ne sınıyor |
|---|---|---|
| A — Yükleme kapısı | 9 | politika haritası, dar kapı, satıcı/personel/mağazasız yükleme, uzantı reddi, uyuşmazlık sözleşmesi, tehlikeli içerik, tavan |
| B — Çıkarım | 6 | etiket+süre, gömülü kapak, kapak çoğalmaması, elle girilen değerin ezilmemesi, anti-açlık damgası, damganın sızmaması |
| C — Erişim denetimi | 7 | admin yazımı, sistem alanlarının uçtan yazılamaması, mağazasız/rakip/Guest reddi, **nöbetçi test** |
| D — Şema çıktısı | 4 | gerçek `fields_for` verisiyle zincirin tamamı, kapak, boş alanların şemayı kirletmemesi, lisans beşlisi |
| E — Yaşam döngüsü | 5 | backfill seçimi, idempotanslık, anti-açlık kilidi, limit, özel dosya |
| F — İçerik çakışması | 3 | iki kiracının aynı baytı: tek adres, ayrı satırlar, çıkarımın hepsine yazması |
| G — Erişim seviyesi | 4 | public/özel indexlenebilirlik, seviye değişimi, taşıma sonrası çıkarım |
| H — Denetim | 3 | bulgu üretimi, bulgunun kaybolması, skor alt boyutları |
| I — Eş zamanlılık | 4 | üç ardışık `apply`, bozuk dosyanın kuyruğu düşürmemesi, olmayan/boş adres |

### Mutasyon doğrulaması

Testlerin gerçekten tuttuğunu kanıtlamak için üç kasıtlı bozma yapıldı:

| Mutasyon | Sonuç |
|---|---|
| `author` → `byArtist` | 2 test kırıldı ✓ |
| `KIND_AUDIO` `MEDIA_KINDS`'tan çıkarıldı | 1 fail + 7 error ✓ |
| `max(0, …)` süre nöbetçisi kaldırıldı | 1 fail ✓ |

Üçü de geri alındı; dosyalar doğrulandı.

---

## 6. Değişen dosyalar

| Dosya | Durum |
|---|---|
| `tradehub_core/seo/schema_builder.py` | `build_audio_object` eklendi |
| `tradehub_core/media/audio_meta.py` | **yeni** |
| `tradehub_core/media/upload_policy.py` | `KIND_AUDIO`, `AUDIO_EXTENSIONS`, tavan, `MEDIA_KINDS`, sihirli bayt tablosu |
| `tradehub_core/media/seo.py` | `artist`/`cover_url` çıktısı, `th_media_artist` kolonu, negatif süre nöbetçisi |
| `tradehub_core/patches/v15_9_53_media_audio_fields.py` | **yeni** |
| `tradehub_core/patches.txt` | patch kaydı |
| `tradehub_core/tests/test_media_audio_seo.py` | **yeni** |
| `tradehub_core/tests/test_media_audio_meta.py` | **yeni** |
| `tradehub_core/tests/test_e2e_media_audio.py` | **yeni** |

Repoya **ikili dosya eklenmedi**: her test sesi ffmpeg ile koşum anında
üretiliyor ve tuzlanıyor, böylece önceki koşumdan kalan blob yeni koşumun
sonucunu boyamıyor.

---

## 7. Bilinçli olarak yapılmayanlar

| Konu | Neden |
|---|---|
| Transkript / altyazı | **AI katmanı** — konuşma tanıma gerektiriyor, bu turun kapsamı dışı |
| Bölümler (chapters) | Aynı; ayrıca `hasPart`/`Clip` modellemesi ayrı bir karar |
| Podcast metadata (RSS, sezon/bölüm) | Şartnamede geçiyor ama ürün bağlamı belirsiz — karar bekliyor |
| `.mid`, `.wma`, `.aiff` | Yaygın değil; izin listesi bilinçli dar tutuldu |
| `only_for` yanılgısının repo geneli denetimi | Ayrı iş — §4 sonundaki not |

---

## 8. Ölçümler

| | |
|---|---|
| Yeni test | 81 |
| E2E süresi | ~55 sn (46 test, gerçek ffmpeg üretimi dahil) |
| Ruff | temiz |
| Yeni bağımlılık | **yok** |
| Yeni DB kolonu | **1** (`th_media_artist`) |
| Bulunan kod kusuru | 4 |
| Düzeltilen test hatası | 4 |

---

## 9. Sırada

MOGEM-620'nin kalan (AI hariç) kalemleri, azalan öncelikle:

1. **Toplu işlemler** — %0. Toplu yeniden adlandırma, etiket, lisans,
   görünürlük, index/noindex. Kalan en büyük tek boşluk.
2. **Ürün SEO** — %0. GTIN, medya rolleri (birincil/galeri/varyant/swatch/360),
   Product/ProductGroup şema bağlantısı.
3. **Zengin arama filtreleri** — %35. Tarih, oluşturan, telif, boyut, oran, renk.
4. **İlişki grafiği** — %50. Ürün/kategori/sayfa/kampanya/locale bağları.
5. **Locale bazlı medya ezmesi** — %70.
6. **Etiket kaynağı ayrımı** (AI/Sistem/Manuel) — %70.
7. **Performansta decode maliyeti** — %80.

Ayrıca **MOGEM-620'nin Plane'de alt görevi yok**; ekip bu işi takip edemiyor.
622'de "Görevleri Parçalama Toplantısı" yapılmış ama 620 o turdan geçmemiş
görünüyor.
