# T-134 — Medya hattında KVKK / GDPR ve EXIF temizliği

**Tarih:** 2026-08-18 · **Faz:** 13 · **Görev:** T-134
**Kardeş belge:** `docs/security/faz13-tehdit-modeli.md` (T-132)
**Ölçüm ortamı:** yerel Pillow **11.3.0** / Python 3.9.6 (macOS) + konteyner
`istoc-dev-backend-1` (Linux, Python 3.11.6), site `istoc.localhost`

> Bu belge de `tradehub_core/` altındaki üretim kodunu **DEĞİŞTİRMEZ**. Mevcut
> davranış ölçülür, doğrulanır, sınırları yazılır; öneriler §7'de.

---

## 0. Yöntem

| Etiket | Anlamı |
|---|---|
| **[K]** | Kod okundu (`dosya:satır`) |
| **[Ö]** | Bu görevde **ölçüldü** — betik §8'de, çıktı aynen aktarıldı |
| **[D]** | Kontrol deneyiyle doğrulandı (aynı ölçümün tersini kuran ikinci deney) |
| **[T]** | Tasarım/hukuk yorumu |
| **[?]** | ÖLÇÜLEMEDİ → §9 |

**Hukuki not [T]:** Bu belge bir hukuk mütalaası değildir. KVKK (6698) ve GDPR
maddelerine yapılan atıflar, **teknik kontrolün hangi yükümlülüğe karşılık
geldiğini** göstermek içindir; nihai değerlendirme veri sorumlusunun ve hukuk
danışmanının işidir.

---

## 1. Medya hattında hangi kişisel veri var

| Sınıf | Nerede | KVKK | GDPR | Bugünkü konum |
|---|---|---|---|---|
| Kimlik belgesi (TC kimlik taraması) | `KYC/KYB Verification.identity_document` | m.6 **özel nitelikli** | Art. 9 | `private/files/` |
| İmza sirküleri, ticaret sicil, faaliyet belgesi, vergi levhası | `KYB Verification` (4 alan) | m.5 kişisel + ticari | Art. 6 | `private/files/` |
| Banka hesap belgesi | `KYB Verification.bank_account_document` | m.5 | Art. 6 | `private/files/` |
| Ödeme/sipariş dekontu | `Order/Payment Transaction.receipt_url` | m.5 | Art. 6 | **`public/files/` — bkz. T-132 F-02** |
| **Görsel EXIF metadata** | her yüklenen fotoğraf | m.5 (dolaylı konum/kimlik) | Art. 4(1) | bu belgenin konusu |
| Yükleyen kimliği + zaman | `File.owner`, `creation`, ADL | m.5 | Art. 6 | DB |

**EXIF neden kişisel veri [T].** Bir ürün fotoğrafının EXIF bloğu şunları
taşıyabilir: **GPS koordinatı** (deponun/evin adresi), `DateTimeOriginal`
(çekim anı), `Make`/`Model` (cihaz), `BodySerialNumber` (**cihazın benzersiz
seri numarası — aynı satıcının tüm fotoğraflarını birbirine bağlayan kalıcı
tanımlayıcı**), `Artist`/`Copyright` (kişi adı). Tek başına ürün fotoğrafı
kişisel veri değildir; bu alanlarla birlikte olabilir.

---

## 2. KURAL

> **Kullanıcıdan gelen bir görsel servis edilmeden önce EXIF'in konum ve cihaz
> alanları düşürülür. Yönelim (`Orientation`) bilgisi PİKSELE uygulanır, sonra
> metadata atılır. Renk profili (ICC) KORUNUR.**

Gerekçe:
* **GPS ve seri numarası** hiçbir görüntüleme senaryosunda gerekmez → veri
  minimizasyonu (KVKK m.4/2-ç, GDPR Art. 5(1)(c)).
* **Orientation** gereklidir ama METADATA olarak değil: atılırsa fotoğraf yan
  döner. `engine.py` bunu zaten `ImageOps.exif_transpose` ile piksele
  uyguluyor **[K]** (`engine.py:116`, `:164`) — doğru çözüm bu.
* **ICC profili** korunur: atılırsa renkler kayar. `engine.py` `icc_profile`'ı
  transpose'tan ÖNCE alıp çıktıya taşıyor **[K]** (`engine.py:114-115`).

---

## 3. ÖLÇÜM — motor gerçekten düşürüyor mu

Görev tanımı "MEVCUT `engine.py` `convert("RGB")` ile zaten düşürüyor —
doğrula ve belgele" diyordu. **Doğrulandı: düşürüyor. Ama sebep `convert("RGB")`
DEĞİL** — ve bu fark, kuralın ne kadar kırılgan olduğunu belirlediği için
önemlidir. §3.3'e bakınız.

### 3.1 Deney — GPS + PII taşıyan kaynak, dört biçim

Kaynak: 2600×2600 görsel, EXIF bloğunda GPS IFD (41°0'50,4"K / 28°58'50,4"D,
irtifa 100 m) + `Make`, `Model`, `DateTimeOriginal`. Dört biçimde kaydedildi,
`engine.optimize(max_dim=2000, quality=88)` ve `engine.to_webp()` çıktıları
yeniden okundu.

| Biçim | GİRDİ: EXIF bayt / GPS tag | `optimize()` ÇIKTI | `to_webp()` ÇIKTI |
|---|---|---|---|
| JPEG | 238 B / **6 GPS tag** | **0 B / 0 GPS** ✅ | **0 B / 0 GPS** ✅ |
| PNG | 238 B / **6 GPS tag** | **0 B / 0 GPS** ✅ | **0 B / 0 GPS** ✅ |
| WEBP | 232 B / **6 GPS tag** | **0 B / 0 GPS** ✅ | **0 B / 0 GPS** ✅ |
| TIFF | tag'ler `tag_v2`'de / **6 GPS tag** | **0 GPS** ✅ (10 yapısal TIFF tag'i kalır) | **0 B / 0 GPS** ✅ |

**[Ö]** TIFF çıktısında kalan 10 tag tek tek okundu ve **hiçbiri PII değil**:
`ImageWidth`, `ImageLength`, `BitsPerSample`, `Compression`,
`PhotometricInterpretation`, `StripOffsets`, `SamplesPerPixel`, `RowsPerStrip`,
`StripByteCounts`, `PlanarConfiguration` — hepsi dosyayı çözmek için zorunlu
yapısal alanlar.

### 3.2 Deney — PII tag'leri (GPS dışı)

`Artist = "Ahmet Fotografci"`, `Copyright`, `Software`, `DateTime`,
`ImageDescription = "Depo adresi: X sok."` + GPS ile ikinci tur:

| Biçim | `optimize()` çıktısında kalan PII tag |
|---|---|
| JPEG | **hiçbiri** (EXIF sözlüğü tamamen boş) ✅ |
| TIFF | **hiçbiri** (yalnız 10 yapısal tag) ✅ |

### 3.3 KONTROL DENEYİ — mekanizma gerçekten `convert("RGB")` mi

**Hayır.** İki bağımsız kanıt:

**Kanıt 1 — TIFF yolu `convert("RGB")` YAPMIYOR ve yine de düşürüyor. [K]**
`engine.py:127-132` TIFF dalında mod'a dokunulmadığı açıkça yorumlanmış
("`convert("RGB")` burada YAPILMAZ — TIFF'ler CMYK/RGBA olabilir"). Buna
rağmen §3.1'de TIFF çıktısında GPS yok.

**Kanıt 2 — `exif_transpose` çıktısı EXIF'i TAŞIYOR, ama `save()` yazmıyor. [D]**

```
ImageOps.exif_transpose(im).info["exif"] var mı  →  True     (EXIF hâlâ nesnede)
düz .save(buf, "WEBP")  → çıktıdaki EXIF        →  0 bayt
düz .save(buf, "JPEG")  → çıktıdaki EXIF        →  0 bayt
düz .save(buf, "PNG")   → çıktıdaki EXIF        →  0 bayt
```

**Gerçek mekanizma [T]:** Pillow, `save()` çağrısına **açıkça `exif=` verilmediği
sürece** `im.info["exif"]` bloğunu çıktıya YAZMAZ. `engine.py`'nin dört
`save()` çağrısının hiçbirinde `exif=` yok — yalnız `icc_profile=` var.
EXIF düşmesi bu **eksikliğin yan etkisidir**, bilinçli bir temizleme adımı
değildir.

**Bunun neden önemli olduğu [T]:** kural bugün **tek bir satırlık iyi niyetli
değişiklikle** bozulabilir. Örneğin biri "yönelim bilgisi kaybolmasın" ya da
"çekim tarihi kalsın" diye şunu yazarsa:

```python
im.convert("RGB").save(buf, "JPEG", quality=quality, icc_profile=icc,
                       exif=im.info.get("exif"))   # ← GPS GERİ GELİR
```

…GPS koordinatı sessizce geri döner ve hiçbir test bunu yakalamaz. Bu yüzden
§7-Ö-1: temizlik **açık ve testli** hâle getirilmeli.

---

## 4. ÖLÇÜM — canlı dosyalarda bugün ne var

`istoc.localhost` disk ağacı tarandı (**[Ö]**, `faz13_gps_canli.py`):

| Ağaç | Taranan görsel | EXIF taşıyan | **GPS** | Artist | Copyright | Software | DateTimeOriginal | Make/Model | **BodySerialNumber** |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `public/files/` | 3 899 | 94 | **0** | 3 | 0 | 5 | 8 | 6 | **4** |
| `private/files/` | 100 | 6 | **0** | 0 | 0 | 3 | 2 | 2 | **2** |

**Okuma:**
* **GPS bugün hiçbir dosyada YOK.** ✅ Kuralın en kritik yarısı sahada tutuyor.
* Ama **94 public dosya hâlâ EXIF taşıyor** ve içlerinde **4 tanesi kamera
  gövde seri numarası** taşıyor — bu, aynı satıcının tüm fotoğraflarını
  birbirine bağlayan kalıcı bir tanımlayıcıdır ve hiçbir görüntüleme
  senaryosunda gerekmez.
* GPS'in bulunmaması bir kontrolün eseri değil, **kaynak dosyaların GPS'siz
  olmasının** eseri olabilir — telefonlarda konum etiketi kapalıysa hiç
  yazılmaz. Aşağıdaki ölçüm bunun neden "şansa bağlı" olduğunu gösteriyor.

---

## 5. AÇIK — temizlik optimizasyona bağlı, optimizasyon çoğu dosyayı ATLIYOR

**[K]** `media/gates.py` altı kapı tanımlıyor ve Kapı 4 (`already_small`,
`gates.py:70-71`) modül
başlığında "bu işin kalbi" diye anlatılıyor: **en uzun kenarı 2000 px'i
AŞMAYAN dosya hiç işlenmez.** Kapı 1 ise 200 KB altını eler.

Yani: **EXIF temizliği yalnız optimize EDİLEN dosyalarda gerçekleşir.**
Optimize edilmeyen dosya diske **bit düzeyinde aynı** yazılır — EXIF dahil.

**[Ö]** EXIF taşıyan 94 public dosya, gerçek kapı fonksiyonundan
(`gates.check_before`, preset `balanced`) tek tek geçirildi:

| Kapı sonucu | Dosya | Oran |
|---|--:|--:|
| `already_small` (≤2000 px) → **hiç işlenmez** | **59** | %62,8 |
| `too_small` (<200 KB) → **hiç işlenmez** | **9** | %9,6 |
| Kapıyı geçer (işlenebilir) | 26 | %27,7 |

**68 dosya (%72,3) motorun EXIF temizleme yoluna HİÇ girmez.**

PII tag'i (Artist/Copyright/Software/Make/Model) taşıyan **9 dosyanın 3'ü**
`too_small` — yani optimizasyon açılsa bile o üç dosya asla temizlenmez.
Kalan 6'sı kapıyı geçebilir durumda ama **bugün hâlâ EXIF taşıyor**, yani o
dosyalar için optimizasyon henüz koşturulmamış.

**Sonuç [T]:** Bugünkü mimaride EXIF temizliği bir **güvenlik kontrolü değil,
bir yan etkidir** ve kapsamı optimizasyon kapılarının kapsamıyla sınırlıdır.
GPS'in bugün 0 olması, kontrolün çalıştığını değil, **kaynakta GPS
bulunmadığını** gösterir. Konum etiketi açık bir telefondan yüklenen 1500 px'lik
bir ürün fotoğrafı (Kapı 4 → `already_small`) GPS'iyle birlikte
`public/files/` altına yazılır ve nginx tarafından doğrudan servis edilir.

### 5.1 VİDEO — metadata KOPYALANIYOR, ölçüldü

Görselde EXIF kazara düşerken, **videoda tam tersi olur:** ffmpeg
`-map_metadata -1` verilmedikçe kaynak metadata'yı çıktıya **kopyalar** —
bu onun varsayılan davranışıdır.

**[K]** Ne `tradehub_core/media/transcode.py:349-360` (bugünkü VP9/Opus hattı)
ne de `tradehub_core/media/pipeline/video/transcode.py:217-252` (Faz 7 H.264/mp4 hattı)
komut satırında `-map_metadata` taşıyor.

**[Ö]** Konteynerde gerçek ffmpeg ile ölçüldü. GPS + `artist` + `comment`
metadata'sı olan bir mp4 üretilip iki hattın **birebir aynı argümanlarıyla**
yeniden kodlandı:

| Çıktı | `location` | `artist` | `comment` |
|---|---|---|---|
| Kaynak (girdi) | `+41.0140+028.9800/` | var | var |
| **Bugünkü hat** (`libvpx-vp9` + `libopus` → WebM) | **`+41.0140+028.9800/`** ❌ | **var** ❌ | **var** ❌ |
| **Faz 7 hattı** (`libx264` high + aac + faststart → mp4) | **`+41.0140+028.9800/`** ❌ | **var** ❌ | **var** ❌ |
| Kontrol: aynı komut + `-map_metadata -1` | **YOK** ✅ | **YOK** ✅ | **YOK** ✅ |

İki hat da GPS koordinatını olduğu gibi taşıdı; tek satırlık `-map_metadata -1`
üçünü birden temizledi (geriye yalnız `major_brand`/`encoder` gibi konteyner
alanları kaldı).

**[Ö] Canlı durum:** diskteki **18 videonun 0'ında** konum ya da kişi
metadata'sı var. Yani görseldeki tabloyla aynı: **mekanizma açık, bugün sömürü
yok.** iPhone ile çekilmiş bir ürün videosu
(`com.apple.quicktime.location.ISO6709` taşır) ilk yüklendiğinde açık
kapanmadan gerçekleşir.

**Öneri (Ö-6, §7):** her iki `ffmpeg` çağrısına `-map_metadata -1` eklemek.
Tek satır, ölçülmüş etki, yan etkisi yok — `creation_time` gibi alanlar da
düşer ama bunlar `File.creation` üzerinden zaten DB'de duruyor.

**Not — `to_webp()` yolu farklı ve daha iyi. [K]** `api/seller_media.py`
`upload_media` çağrısı `engine.to_webp()` kullanıyor; o fonksiyon **kapısızdır**
ve her dosyayı yeniden kodlar → EXIF her zaman düşer (§3.1'de ölçüldü). Yani
"garanti-WebP" yolundan gelen yüklemeler temiz; kapılı optimizasyon yolundan
gelenler değil. **Aynı sistemde iki farklı gizlilik davranışı var.**

---

## 6. KVKK / GDPR yükümlülük eşlemesi

| Yükümlülük | KVKK | GDPR | Bugünkü karşılığı | Durum |
|---|---|---|---|---|
| Veri minimizasyonu | m.4/2-ç | Art. 5(1)(c) | EXIF düşürme (kapılı) | **KISMİ** — §5 |
| Özel nitelikli veriye ek koruma | m.6 | Art. 9 | `private/files/` + `_is_protected_pii` | **AÇIK** — T-132 F-03 (39 belge public ikizli) |
| Tasarımdan gelen gizlilik | m.12 | Art. 25 | `access_level.py` çift yol, `av.py` bekletme | KISMİ — T-132 F-04 |
| Veri güvenliği | m.12 | Art. 32 | upload policy, AV, karantina, izolasyon (T-130) | İYİ |
| Saklama süresi sınırı | m.4/2-d, m.7 | Art. 5(1)(e) | `trash.py`/`archive.py` 30 gün, `backup.py` 14 set | İYİ **[K]** |
| Silme / yok etme | m.7 | Art. 17 | `trash.py` → `archive.py` → kalıcı silme | İYİ |
| Erişilebilirlik / taşınabilirlik | m.11 | Art. 15, 20 | `Data Export Request` doctype | **[?]** ölçülmedi |
| İşleme kaydı / denetim izi | m.12 | Art. 30 | `media/audit.py` ADL + T-133 JSON log | İYİ |
| İhlal bildirimi | m.12/5 | Art. 33-34 | T-133 metrikleri tespiti mümkün kılar | **YENİ** |
| Yurt dışı aktarım | m.9 | Art. 44+ | `tradehub_core/media/pipeline/storage/s3.py` (kullanımda değil) | **[?]** §9 |

### 6.1 Denetim izinde PII — çözülmüş

**[K]** `media/audit.py:183` hassas olayda `file_url`'i
`masked:<sha256[:12]>` biçimine çeviriyor. T-133'ün `observability/logging.py`
modülü **aynı parmak izi biçimini** üretir (`fingerprint()` fonksiyonu birebir
`hashlib.sha256(...).hexdigest()[:12]`) ve `tests/test_observability.py::
test_audit_ile_ayni_parmak_izi` ayrışmayı düşürür.

Neden aynı olmak zorunda **[T]**: ADL kaydı ile log satırı aynı dosyayı farklı
kimlikle gösterseydi, bir ihlal incelemesinde ikisini eşleştirmek imkânsız
olurdu — yani denetim izi teknik olarak var ama pratikte kullanılamaz olurdu.

### 6.2 Log'da PII — iki yollu maskeleme

`logging.py` maskelemeyi İKİ yoldan tetikler ve ikisinin de gerekli olduğu
testle gösterilir:

1. **Anahtar adı** — `file_url`, `email`, `path`, `tckn`, `iban`, `ip`… (26 alan)
2. **Değer deseni** — serbest metinde e-posta, `/files/…`, 11 haneli TCKN,
   IBAN, mutlak disk yolu

İkincisi olmadan `detail="kopyalama hatasi: /private/files/ab/kimlik.jpg"`
gibi bir satır maskelemeden kaçardı; birincisi olmadan yapılandırılmış alanlar
kaçardı. Cümlenin okunur kalması bilinçli: yalnız EŞLEŞEN parça maskelenir.

### 6.3 Core dump — kapatıldı

**[K]** `isolation.Limits.core_bytes = 0` varsayılan. Gerekçe: bir core dump,
sürecin o andaki belleğinin diske dökümüdür — işlenen KYB belgesinin ham
baytları dahil. Sınırsız bırakmak, kimlik taramasını disk üstünde
`/var/lib/…core` dosyasına yazmak demekti.

---

## 7. Öneriler

> Hiçbiri uygulanmadı — `tradehub_core/` bu görevde salt okunur.

### Ö-1 — EXIF temizliğini AÇIK ve TESTLİ bir adım yap (§3.3 + §5)

Bugün temizlik `save()` çağrısına `exif=` yazılmamış olmasının yan etkisi.
Öneri: `media/engine.py`'ye niyeti açıkça söyleyen bir fonksiyon:

```python
# ÖNERİ — tradehub_core/media/pipeline.py, uygulanmadı
#: Çıktıya TAŞINMASINA izin verilen EXIF tag'leri. Liste bilinçli olarak BOŞ:
#: Orientation piksele uygulanıyor (exif_transpose), ICC ayrı taşınıyor,
#: geri kalanın hiçbiri görüntüleme için gerekmiyor.
ALLOWED_EXIF_TAGS: frozenset[int] = frozenset()

def strip_metadata(im):
	"""EXIF'i AÇIKÇA düşür. Bugünkü davranışın adı konmuş hâli.

	Bugün EXIF, `save()`'e `exif=` verilmediği için düşüyor — yani bir
	YAN ETKİ. Tek satırlık iyi niyetli bir değişiklik ("çekim tarihi kalsın")
	GPS'i geri getirir ve hiçbir test yakalamaz. Bu fonksiyon niyeti koda
	yazar, testi de ona bağlanır.
	"""
	im.info.pop("exif", None)
	getattr(im, "encoderinfo", {}).pop("exif", None)
	return im
```

Ve bir **regresyon testi**: GPS'li kaynak → çıktıda GPS yok (§8'deki betik
`tests/` altına taşınabilir).

### Ö-2 — EXIF temizliğini kapıların DIŞINA çıkar (§5 — en önemlisi)

**Sorun:** temizlik optimizasyonun içinde; optimizasyon dosyaların %72'sini
bilinçli olarak atlıyor. İki kural aynı yerde durduğu için, boyut kararı
gizlilik kararını da belirliyor.

**Öneri:** metadata temizliği ayrı ve KAPISIZ bir adım olsun:

```
yükleme → policy → AV → [metadata temizliği: HER dosya]  → [optimize: kapılı]
                              ↑ yeni, kapısız                  ↑ bugünkü
```

Maliyet: `already_small` dosyalar için yeniden kodlama gerekir — bu, "3 700
dosya bit düzeyinde aynı kalır, kalite kaybı riski sıfır" garantisini
(`gates.py` modül başlığı) bozar. **Daha ucuz alternatif [T]:** JPEG'de
piksel verisine dokunmadan yalnız APP1/EXIF segmentini kesmek (kayıpsız,
yeniden kodlama yok). PNG'de `eXIf` chunk'ı, WebP'de `EXIF` chunk'ı için de
aynısı mümkün. Bu yol **ölçülmedi [?]** ama doğru yön odur: gizlilik kararı
kalite kararından bağımsız olmalı.

### Ö-3 — Geriye dönük temizlik

**[Ö]** Bugün 94 public + 6 private dosya EXIF taşıyor; 4+2 tanesi kamera
gövde seri numarası. Tek seferlik bir iş bunları temizlemeli. GPS bugün 0
olduğu için **acil değil**, ama Ö-2 uygulanmadan önce yapılırsa yeni
yüklemeler açığı yeniden doldurur — sırası Ö-2'den SONRA.

### Ö-4 — `to_webp` ile `optimize` arasındaki gizlilik farkını kapat (§5 notu)

Aynı sistemde iki yükleme yolu, iki farklı EXIF davranışı üretiyor. Ö-2
uygulanırsa fark kendiliğinden kapanır; uygulanmazsa en azından
**belgelenmeli** ki "hangi yoldan yüklersen temiz olur" sorusu cevaplanabilsin.

### Ö-6 — ffmpeg çağrılarına `-map_metadata -1` ekle (§5.1)

İki dosya, iki satır:

```python
# tradehub_core/media/transcode.py:349  ve  tradehub_core/media/pipeline/video/transcode.py:217
#   "ffmpeg", "-y", "-i", src_path,
# + "-map_metadata", "-1",          ← ÖNERİ: kaynak metadata'sını taşıma
```

ÖLÇÜLDÜ (§5.1): bu bayrak olmadan GPS koordinatı, `artist` ve `comment`
her iki hattın da çıktısına aynen geçiyor; bayrakla üçü de düşüyor.
**Bu, T-134'ün en ucuz ve en kesin düzeltmesidir.**

### Ö-5 — GPS'i bir METRİKLE izle

`observability/metrics.py`'ye ek bir gösterge (`media_exif_gps_files`) ve
günlük tarama. Bugünkü 0 değeri ancak **ölçülmeye devam ederse** anlamlıdır;
tek seferlik bir ölçüm, yarın yüklenecek dosya hakkında hiçbir şey söylemez.

---

## 8. Ölçüm betikleri

| Betik | Ne ölçer |
|---|---|
| `/tmp/faz13gps/gps.py` | GPS'li sentetik kaynak → `optimize()` / `to_webp()` çıktısında GPS kaldı mı (4 biçim) |
| `/tmp/faz13gps/kontrol.py` | §3.3 kontrol deneyi: TIFF kalıntı tag listesi + `exif_transpose`/düz `save()` davranışı |
| `/home/frappe/olcum/faz13_gps_canli.py` | Canlı disk ağacında EXIF/GPS/PII tag taraması (public + private) |
| `/home/frappe/olcum/faz13_exif_kapi.py` | EXIF taşıyan dosyalar `gates.check_before`'dan geçer miydi |

Canlı tarama çalıştırma:

```bash
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
    ../env/bin/python /home/frappe/olcum/faz13_gps_canli.py
```

---

## 9. Ölçülemeyenler

| # | Ne | Neden | Nasıl |
|---|---|---|---|
| ? -1 | **Üretim** EXIF dağılımı | Üretim DB/disk erişimi yok | `faz13_gps_canli.py` üretim sitesinde |
| ? -2 | Kayıpsız EXIF kesmenin (APP1 segment) maliyeti | Ö-2'nin ucuz yolu denenmedi | 4 958 dosyada süre + bayt farkı ölçümü |
| ? -3 | `Data Export Request` akışı KVKK m.11'i gerçekten karşılıyor mu | Doctype'ta 0 dolu satır **[Ö]** | Uçtan uca bir talep koşturulmalı |
| ? -4 | S3 aynası kullanımda mı, hangi bölgede | `storage/s3.py` var, bağlı değil | `site_config.json` + üretim yapılandırması |
| ? -6 | Saklama sürelerinin gerçekten uygulandığı | `trash.py`/`archive.py` okundu, koşturulmadı | Süpürücü işin son çalışma zamanı + silinen kayıt sayısı |

---

## 10. Sonuç

* **Kural sahada tutuyor ama sebebi yanlış biliniyordu.** `engine.optimize()`
  ve `to_webp()` GPS dahil tüm EXIF'i düşürüyor — dört biçimde de ölçüldü.
  Ancak bunu yapan `convert("RGB")` değil, Pillow'un `exif=` verilmedikçe
  metadata yazmaması. Temizlik **açık bir adım değil, bir yan etki**.
* **Kapsam sanılandan dar.** EXIF taşıyan 94 public dosyanın **68'i (%72)**
  optimizasyon kapılarına takılıp motorun temizleme yoluna hiç girmiyor.
  Bugün GPS'in 0 olması kontrolün değil, kaynak dosyaların eseri.
* **Bugün somut PII kalıntısı var:** 4 public + 2 private dosyada kamera gövde
  seri numarası, 8 dosyada çekim tarihi, 3 dosyada kişi adı.
* **Video tarafı ölçüldü ve AÇIK:** ffmpeg varsayılan olarak metadata kopyalar;
  iki transcode hattının ikisinde de `-map_metadata -1` yok ve gerçek ffmpeg
  ile GPS'in çıktıya geçtiği doğrulandı. Canlı 18 videonun 0'ında bugün konum
  verisi var — yani mekanizma açık, sömürü henüz yok. Düzeltmesi tek satır
  (Ö-6).
