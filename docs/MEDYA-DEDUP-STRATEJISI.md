# Medya tekilleştirme (dedup) ve hash stratejisi — TUR-298

**Linear:** TUR-298 · **Faz:** 3 · **Durum:** bu belge sözleşmedir, kod ona uyar.
**Bağlı belgeler:** `MEDYA-YUKLEME-SOZLESMESI.md` (adlandırma), `MEDYA-ISLEME-PIPELINE.md` (adım 2).

---

## 1. Neden bu belge var

Dedup zaten **çalışıyordu** — ama hiçbir yerde yazmıyordu.

Kod arkeolojisi şunu gösteriyor: bu issue'nun beş kapsam maddesinin tamamı,
komşu işlerin **yan ürünü** olarak birikmiş. Kimse "dedup'ı yapayım" demedi:

| Mekanizma | Getiren commit | Hangi iş yapılırken |
|---|---|---|
| Hash üretimi, aynı içerik = aynı ad | `7f2c099` (13 Ağu) | TUR-141/130/124 |
| Ortak dosyada silme koruması (satıcı) | `cb11631` (13 Ağu) | TUR-138/136/131 |
| Referans sayımı | `9fbb8be` (6 Ağu) | **hiçbir issue'ya bağlı değil** |

Sonuç: sistem doğru davranıyor ama **neden öyle davrandığı** hiçbir yerde
yazmıyor. "Aynı görseli iki satıcı yüklerse, biri silerse diğeri ne görür?"
sorusunun cevabı yalnız koddan okunabiliyordu. Bu belge o boşluğu kapatır ve
bulunan bir açığı da kaydeder.

---

## 2. Temel karar: içerik-adresli adlandırma

Dosya adı **içeriğinden** türetilir:

```
<sha256(içerik)[:32]>.<uzantı>          media/naming.py:_hashed_name
```

Bunun üç sonucu var, üçü de bilinçli:

1. **Aynı içerik → aynı ad → tek dosya.** 100 satıcı aynı kargo ikonunu
   yüklerse disk 100 kat şişmez. Tekilleştirme ayrı bir mekanizma değil,
   adlandırmanın doğal sonucudur.
2. **Ad tahmin edilemez.** `0505.jpg` gibi sıralı adlar URL'den denenerek
   çekilebiliyordu (TUR-141 enumeration).
3. **Orijinal ad sızmaz.** `fatura-ahmet.jpg` adresten okunamaz. Görünen ad
   `File.file_name` alanında ayrı durur.

**Neden 32 karakter:** sha256'nın ilk 128 biti. Çakışma olasılığı pratikte
sıfır; tam 64 karakter yol uzunluğunu gereksiz büyütürdü.

**Frappe'nin kendi dedup'ı da devrede** (`content_hash`) — iki katman birbirini
ezmez, ikisi de aynı sonuca varır.

---

## 3. Aynı içerik tekrar yüklenirse

**Diskte tek dosya, `File` tarafında birden çok kayıt olur.**

```
Satıcı A "logo.jpg" yükledi  ─┐
                              ├─→  /files/53f2d5e3….jpg      (TEK fiziksel dosya)
Satıcı B "logo.jpg" yükledi  ─┘     File: 2 kayıt, aynı file_url
```

Kayıtların ayrı kalması **kasıtlı**: her satıcının kendi başlığı, alt metni,
etiketleri ve sahiplik bağı var. Tek kayda indirmek "kimin dosyası" sorusunu
cevapsız bırakırdı.

Ölçüm: tek bir adrese **39 kayda kadar** işaret edilebiliyor.

> **Bunun her yerde sonucu var.** Durum alanları (`th_media_state`,
> `th_media_video_status`, `th_media_scan_status`) kayıt başına yazıldığı için
> aynı adreste **ayrışabilirler**. Panel adres bazında grupladığından bir tane
> seçmek zorunda ve kural her üçünde de aynı: **kötü haber kazanır**
> (`inventory._scan_status_term`, `_video_status_term`). Gerekçe
> `MEDYA-ISLEME-PIPELINE.md` §3.2'de.

---

## 3b. "Eşdeğer" dosyalar — bilinçli olarak YAPILMIYOR

Issue'nun açılış cümlesi *"Aynı **veya eşdeğer** medya dosyalarının tekrar
yüklenmesi"* diyor. İkisi farklı şeyler ve ayrı karar gerektiriyor:

| | Tanım | Yakalanıyor mu |
|---|---|---|
| **Aynı** | Bayt bayt özdeş → aynı sha256 | ✅ tam |
| **Eşdeğer** | Gözle aynı ama farklı bayt: başka kalitede kaydedilmiş, yeniden boyutlandırılmış, EXIF'i değişmiş | ❌ **hayır** |

İçerik hash'i yalnız **özdeş** baytları eşler. Eşdeğerleri yakalamak algısal
hash (pHash/dHash) + en-yakın-komşu indeksi gerektirir. Kod tabanında böyle bir
şey yok (arandı: `phash|dhash|imagehash|perceptual` → 0 sonuç).

**Karar: yapılmayacak.** Gerekçe, kazançtan çok riskle ilgili:

1. **Yanlış eşleşme pazaryerinde felakettir.** Beyaz fonda çekilmiş iki farklı
   ürün, algısal hash'te neredeyse aynı çıkar. Otomatik birleştirme, A ürününün
   fotoğrafını B ürününde gösterir. Disk kazancı bu riski karşılamaz.
2. **Hangi sürüm kazanır sorusunun iyi cevabı yok.** A 4000px, B 800px yükledi.
   Tek dosyaya indirirsen birinin ürün sayfası bozulur — ya çözünürlük düşer ya
   gereksiz büyük dosya servis edilir.
3. **Asıl kazanç zaten alınıyor.** Sahadaki baskın durum "aynı dosyanın tekrar
   yüklenmesi" (paylaşılan logo, kargo ikonu, aynı görselin yeniden yüklenmesi)
   ve onu bayt-özdeş dedup zaten yakalıyor.

**Kapı tamamen kapalı değil.** İleride değerli olabilecek hâli *otomatik
birleştirme* değil, **öneri**: satıcı yükleme yaparken "kütüphanenizde buna
benzer bir görsel var, onu mu kullanmak istersiniz?" demek. Karar kullanıcıda
kalır, yanlış eşleşme veri kaybına dönüşmez. Bu ayrı bir iş; bu issue'nun
kapsamında değil.

> **Not 1 — belirlenimcilik.** WebP dönüşümü belirlenimci (ölçüldü: aynı JPEG →
> aynı bayt → aynı hash). İki satıcı aynı JPEG'i yüklediğinde sunucu ikisini de
> aynı WebP'ye çevirir ve dedup çalışır. Belirlenimci olmasaydı "aynı" dedup'ı
> da sessizce kırılırdı.
>
> **Not 2 — bu kararın sınırı zamanla değişecek.** Format dönüşümü evrensel
> olduğunda (TUR-128), bugün "eşdeğer" saydığımız bazı çiftler **"aynı"ya
> dönüşür**: farklı kaynak formatları aynı piksellere çözülüyorsa aynı WebP
> üretir, aynı hash alır ve kendiliğinden dedup olur. Yani algısal hash
> yazmadan da eşdeğerlerin bir kısmı yakalanmış olacak. Kayıplı JPEG'ler farklı
> piksellere çözüldüğü için bu onlarda çalışmaz — karar (algısal hash yok) o
> gün de geçerli kalır. Ayrıntı: §3c.

---

## 3c. Format dönüşümü ve dedup — bugünkü asimetri, yarınki geçiş

Dedup, hash'lenen **baytlara** bakar. Dolayısıyla "bu dosya hangi formatta
saklanıyor" sorusu doğrudan dedup sorusudur.

### 3c.1 Bugün: dönüşüm YALNIZ satıcı kütüphanesi yolunda

| Yükleme yolu | PNG/JPEG'e ne oluyor | Ad neyin hash'i |
|---|---|---|
| `seller_media.upload_media` (medya kütüphanesi) | **WebP'ye çevriliyor** | dönüştürülmüş baytlar |
| Frappe `upload_file` (ürün formu, 22 admin ekranı) | **dokunulmuyor** | orijinal baytlar |

Genel kanca (`naming.write_file_hashed`) yalnız adlandırıyor, dönüştürmüyor.

**Bunun ölçülen sonucu:** aynı PNG iki yoldan yüklenirse **iki ayrı dosya** olur.

```
genel yükleme (dönüşüm yok) → 9aa5c58adcd2d281b3f8f0b0b3084357.png
satıcı kütüphanesi (WebP)   → 06964e0169f5ad49f01732d15952eb90.webp
DEDUP OLUYOR MU: False
```

Yani bugün dedup **yol-bağımlı**. §6'daki %34 kazanç, bu açığa RAĞMEN alınıyor.

Sahadaki dağılım (2026-08-20): `jpg` 3.208 · `png` 559 · `jpeg` 88 · `webp` 374.
Yani **3.855 görsel** hâlâ dönüştürülmemiş formatta duruyor.

### 3c.2 Yarın: dönüşüm evrensel olduğunda (TUR-128)

Dönüşüm tüm yollara yayıldığında dedup üç açıdan etkilenir:

**1. Sıra kuralı: ÖNCE dönüştür, SONRA hash'le.** Bugünkü satıcı yolu böyle
yapıyor ve doğrusu bu. Gerekçe:

| Sıra | Sonuç |
|---|---|
| Hash sonra dönüştür | Ad orijinalin hash'i olur, dosya WebP'dir — **ad içeriği anlatmaz**. İçerik-adresli olmanın anlamı kalmaz |
| **Dönüştür sonra hash'le** ✅ | Ad gerçek içeriğin hash'i. Üstelik farklı kaynak formatları aynı piksellere çözülüyorsa **aynı WebP → aynı ad → dedup** |

İkinci satırdaki yan kazanç önemli: bir PNG ile ondan üretilmiş kayıpsız bir
kopya bugün "eşdeğer" (§3b, yakalanmıyor); dönüşümden sonra ikisi de aynı WebP
üretirse **"aynı"ya dönüşür ve kendiliğinden dedup olur.** Kayıplı JPEG'ler
farklı piksellere çözüldüğü için bu onlarda çalışmaz.

**2. Mevcut 3.855 dosya dönüştürülürse adresleri DEĞİŞİR.** Ad içerikten
türediği için yeni bayt = yeni ad = yeni `file_url`. Bu, ürünlerdeki tüm
referansların güncellenmesi demek — §7'deki ertelenmiş retro-rename işiyle
**aynı problem**. İkisi ayrı ayrı yapılırsa referanslar iki kez güncellenir;
**tek migration olarak planlanmalı.**

**3. Geçiş döneminde aynı görsel iki kez var olabilir.** Yayılım tamamlanana
kadar `.png` ve `.webp` kopyalar yan yana durur. Bu bir hata değil, geçişin
doğal hâli — ama dedup ölçümü (§6) o dönemde geçici olarak kötüleşir. Ölçümü
"bozuldu" diye yorumlamamak için burada kayda geçiyor.

### 3c.3 Bu iş TUR-298'in kapsamında DEĞİL

Dönüşümün kendisi TUR-128'in konusu (Backlog). Burada yalnız **dedup
sözleşmesi** yazıldı: sıra kuralı, migration'ın tek seferde yapılması ve geçiş
dönemi beklentisi. TUR-128 başlarken bu üç maddeyi ön koşul olarak almalı.

---

## 4. Referans sayımı — iki farklı sayı

Karıştırılması kolay, ayrımı kritik:

| Sayı | Ne sayar | Nerede |
|---|---|---|
| `record_count` | Bu adrese kaç **`File` kaydı** işaret ediyor | `inventory.py` |
| `usage_count` / `live` | Bu adres kaç **üründe/kayıtta** kullanılıyor | `usage.py` |
| `owners_of()` | Bu dosyaya kaç **mağaza** sahip | `ownership.py` |

Üçü farklı soruyu cevaplar:

- `record_count = 3` → üç kayıt var, belki ikisi fazlalık
- `usage_count = 0` → hiçbir üründe kullanılmıyor, silinebilir görünür
- `owners_of = 2` → **iki mağazayı ilgilendiriyor**

**Sahiplik yalnız yükleyeni değil kullananı da kapsar.** Satıcının ürününde
duran bir görsel, kim yüklemiş olursa olsun onun kütüphanesinde görünür ve
yönetilebilir (`ownership.owners_of` docstring'i).

---

## 5. Silme akışı — asıl karar

Tek dosyanın çok sahibi olabildiği için "sil" komutunun anlamı **kimin
sildiğine göre değişir**.

### 5.1 Satıcı siliyorsa: kapsamlı

`seller_media.purge` üç kapıdan geçer:

```python
refs.clear(url, store=A)        # referansları YALNIZ A'nın kapsamında temizle
_own_records(url, A)            # yalnız A'nın kullanıcılarının açtığı kayıtlar
kalan = owners_of(url)          # silme sonrası sahip kaldı mı?
if not kalan: os.remove(...)    # kalmadıysa dosya diskten gider
```

Gerçek iki satıcıyla doğrulandı:

```
ÖNCE  → 2 kayıt · sahipler: [SEL-00002, SEL-00038] · diskte: var
A siliyor → records: 1 · remaining_owners: 1 · physically_deleted: False
SONRA → 1 kayıt · sahip: [SEL-00038] · B'nin dosyası: DURUYOR ✅
```

Aynı mantık içerik değiştirmede de var: `files.replace` ortak dosyada
**reddediyor** — *"başka bir mağazada da kullanılıyor, içeriği değiştirilemez"*.

### 5.2 Yönetici siliyorsa: küresel — ama onaylı (TUR-298'in düzelttiği açık)

**Bulunan açık.** `trash.delete_permanently` şunu yapıyordu:

```python
records = get_all("File", {"file_url": url})   # TÜM kayıtlar, sahibi kim olursa
refs.clear(url)                                 # TÜM referanslar, kapsamsız
os.remove(path)                                 # fiziksel dosya
```

Ortak sahiplik kontrolü **yoktu**. Gerçek veriyle canlandırıldı:

```
ÖNCE  → 4 kayıt, diskte 1 dosya
Yönetici çöpe attı → kalıcı sildi
SONRA → 0 kayıt, dosya YOK          ← 4 sahibin hepsi etkilendi
```

Yönetici A'nın dosyasını silerken B'nin ürün görseli de kayboluyor, B'nin ürün
kaydındaki referans da temizleniyordu. Uyarı yok, bildirim yok, denetim
kaydında "başka sahibi vardı" bilgisi yok.

**Neden engel değil onay.** Platform sahibinin yasal kaldırma ya da zararlı
içerik durumunda dosyayı **herkesten** kaldırabilmesi gerekir. Satıcı tarafındaki
kapsam ayrımını yöneticiye uygulamak, karantina ve takedown akışlarını kırardı.
Amaç yöneticiyi durdurmak değil, **kaç mağazayı etkilediğini görmeden
tıklamasını önlemek.**

Kurulan kapı:

| Katman | Davranış |
|---|---|
| `trash.owner_count(url)` | Sahip sayısı; hata olursa **0** döner (1 değil — bilgi uydurmaz) |
| `_assert_not_shared(url, shared_ok)` | Sahip > 1 ve onay yoksa reddeder, sayıyı mesaja yazar |
| `move_to_trash` + `delete_permanently` | İkisi de **ayrı ayrı** sorar |
| Denetim kaydı | `context.owners` — silme geri alınamaz, tek iz bu |
| Panel | Onay ekranında ayrı satır: *"{n} dosya başka mağazalarca da kullanılıyor (en çok {owners} mağaza)"* |

**Neden iki adımda da soruluyor:** çöpe taşımadaki onay kalıcı silme için
yeterli sayılmaz — iki adım arasında yeni bir mağaza dosyayı kullanmaya
başlamış olabilir ve o sahip ilk onayda görünmüyordu.

**Neden `force`tan ayrı bayrak:** `force` "kendi sitemdeki görseller kırılacak"
demek; `shared_ok` "başka satıcıların verisi gidecek". Farklı riskler, ayrı
kararlar. Birini onaylamak diğerini onaylamış saymamalı.

---

## 6. Depolama maliyeti — ölçüm

Tekilleştirme ayrı bir iş değil; içerik-adresli adlandırmanın sonucu. Ek bir
"dedup job"ı **yok ve gerekmiyor** — dosya zaten hiç iki kez yazılmıyor.

Bu iddianın sahadaki karşılığı (ölçüm 2026-08-20, local prod kopyası):

| Ölçüm | Değer |
|---|---|
| `File` kaydı (public) | **5.199** |
| Benzersiz adres (fiziksel dosya) | **3.211** |
| Fazla kayıt = dedup'ın önlediği kopya | **1.988** |
| Paylaşılan adres sayısı | **964** |
| Tek adrese düşen en çok kayıt | **39** |
| Diskteki gerçek boyut | **800 MB** |
| Dedup olmasaydı | **1.214 MB** |
| **Kazanç** | **414 MB · %34** |

Yani her üç kayıttan biri aslında var olan bir dosyayı gösteriyor ve disk
üçte bir oranında küçük kalıyor. Bu, ek bir mekanizma olmadan, yalnız
adlandırma kararının yan ürünü olarak.

**Kararlar:**

1. **Ayrı dedup işi açılmayacak.** Kazanç zaten alınıyor; periyodik bir tarama
   aynı sonucu daha pahalıya üretirdi.
2. **Fazla kayıtlar temizlenmeyecek.** 1.988 fazla kayıt "israf" değil: her biri
   bir satıcının kendi başlığı, alt metni ve sahiplik bağı. Diskte karşılıkları
   yok, yalnız satır maliyeti var.
3. **Ölçüm tekrarlanabilir olmalı.** Yukarıdaki tabloyu üreten sorgu tek
   `GROUP BY file_url` — ileride "dedup hâlâ çalışıyor mu" sorusu aynı yerden
   cevaplanır.

> **Uyarı — bu kazanç kırılgan.** WebP dönüşümünün belirlenimci olmasına bağlı
> (§3b sonundaki not). Encoder sürümü değişir ve aynı JPEG farklı bayt üretmeye
> başlarsa dedup sessizce durur: hata vermez, yalnız disk büyümeye başlar.
> Yukarıdaki tablo o günü fark etmenin yolu.

---

## 7. Açık maddeler

1. **Shard yok.** TUR-130 yorumu *"hash-prefix → `files/<ab>/<hash>.<ext>`
   kodlandı, test 9/9"* diyor; **bu repoda karşılığı yok** — `naming.py` düz
   `/files/<hash>` yazıyor, diskte 0 tane iki karakterli alt dizin var, o
   commit hash'i (`8b84b55`) mevcut değil ve `MEDYA-DEPOLAMA-STANDARDI.md`
   hiçbir dalda bulunmuyor. Bugün ~5.000 dosya tek dizinde; ölçek sorunu
   çıkana kadar acil değil ama **TUR-130 kapatılmadan önce netleşmeli.**
2. **Eski 2.166 tahmin-edilebilir ad** (`0505.jpg`) hâlâ duruyor. Retro-rename
   ~2.400 referans + 301 redirect gerektiriyor; riskli ayrı iş.
   → **TUR-128'in format dönüşümü de aynı referansları güncelleyecek** (§3c.2).
   İkisi ayrı ayrı yapılırsa aynı satırlar iki kez dokunulur ve risk iki katına
   çıkar. **Tek migration olarak planlanmalı.**
3. **Bildirim yok.** Yönetici ortak bir dosyayı sildiğinde etkilenen satıcılara
   haber gitmiyor. Onay ekranı yöneticiyi bilgilendiriyor, satıcıyı değil.
4. **`_live_owner_count` ölü kod** (`seller_media.py`). Tam bu iş için yazılmış
   ama hiçbir yerden çağrılmıyor; `owners_of` doğrudan kullanılıyor. Silinebilir.

---

## 8. Testler

`tradehub_core/tests/test_media_av.py::TestOrtakSahiplikSilme` — 7 test:

| Test | Sabitlediği kural |
|---|---|
| `tek_sahipte_engel_yok` | Sıradan silme onaysız geçer |
| `cok_sahipte_onaysiz_reddedilir` | Sayı **mesajda geçer** — "onay gerekiyor" demek yetmez |
| `onay_verilirse_gecer` | Yönetici durdurulmuyor, bilgilendiriliyor |
| `red_denetime_yazilir` | `shared_owners:N`, maskelenmemiş (sıradan ürün görseli) |
| `owner_count_patlarsa_sifir_doner` | Sahiplik okunamıyorsa **1 varsayılmaz** |
| `cop_ve_kalici_silme_AYRI_onay_ister` | İki adım da kendi kapısını çağırır |
| `satici_yolu_baskasinin_kaydina_dokunmaz` | Mevcut satıcı koruması regresyona karşı kilitli |
