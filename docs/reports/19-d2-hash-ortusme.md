# T-018 — D-2: Hassas `content_hash` Paylaşan Public Dosyalar

**Medya motoru · Faz 0 · KVKK bloklayıcısı K-1'in ikinci yarısı — 2026-08-19**
Branch: `ahmet` · Site: `istoc.localhost` (yerel dev) · Kaynak bulgu: `docs/reports/07-faz0-kapanis.md` §7.1 D-2

Bu belge 07 §7.1 D-2'nin bıraktığı tek işi yapar: **44 dosyanın içerik
sınıflandırması**, gerçek sızıntıların kapatılması ve kapatmanın kanıtlanması.

---

## 0. Özet

| | Sayı |
|---|---:|
| Ölçümde bulunan public dosya (2026-08-19) | **44** |
| Diskte fiilen mevcut | **44 / 44** |
| **Gerçek sızıntı — düzeltildi** | **4** |
| **Zararsız — aynı görselin iki kullanımı** | **40** |
| **Belirsiz kalan** | **0** |
| Düzeltme sonrası kalan public dosya | **40** |

**Sonuç:** 44 dosyanın **hiçbirinin içeriği kişisel veri değil.** 44'ünün
tamamı görsel olarak tek tek incelendi (§3): ürün fotoğrafı, marka logosu,
vitrin banner'ı, mağaza cephesi fotoğrafı ya da geliştirici ekran görüntüsü.
Kimlik taraması, imza sirküleri, vergi levhası, banka dekontu **yok**.

**Ama bulgu var ve kapatıldı:** 4 dosya, platformun kendi politikasının
"asla public olamaz" dediği bir yuvada (`Order.receipt_url` /
`Payment Transaction.receipt_url`) `is_private=0` olarak duruyordu. Bunlar
içerikten bağımsız, **yapısal** sızıntıdır ve düzeltildi (§4).

> **Ölçümün asıl söylediği:** bu veri setinde mekanizma PII taşımıyor, ama
> **mekanizma canlı**. Satıcı aynı görseli hem ürün görseli hem KYB eki olarak
> yüklüyor; ürün tarafı public, KYB tarafı private. Üretimde KYB alanına
> gerçek bir kimlik taraması yüklenip aynı dosya ürün görseli olarak da
> kullanılırsa, **bugün onu durduran hiçbir şey yok.** Bkz. §6 P-12.

---

## 1. Yöntem ve ortam

### 1.1 Konteyner ↔ host doğrulaması

Uygulama Docker imajına gömülü (`apps/` için bind-mount **yok**; yalnız
`sites/` bir volume). Bu yüzden ölçümden önce sha256 eşitliği doğrulandı:

```
                                          host                              konteyner
media/presets.py         2a687cde09b2e26e215363267139aef7…   ==  2a687cde09b2e26e215363267139aef7…
media/access_level.py    52b015ac4c5a74c2ad0583531c83a0fd…   ==  52b015ac4c5a74c2ad0583531c83a0fd…
tests/test_media_access.py        df52fa35dc9e20ed1416…      ==  df52fa35dc9e20ed1416…
tests/test_media_access_level.py  4a304fd356731c69214b…      ==  4a304fd356731c69214b…
```

**Dördü de eşit** — imaj bugünkü `presets.py` genişlemesini içeriyor, `docker cp`
ile kopyalamaya gerek olmadı. Ölçüm ve düzeltme betikleri konteynere `docker cp`
ile taşınıp `../env/bin/python` ile koşturuldu.

### 1.2 "Hassas" tanımı — üç yolun BİRLEŞİMİ

07 §7.1'in 44 sayısı tek bir sorgudan değil, üç hassaslık yolunun birleşiminden
geliyor. Rapordaki kırılımda `Brand` görünmesi (ki `EXCLUDED_DOCTYPES`'te yok)
bunun kanıtı. Sayıyı birebir yeniden üretmek için üçü de uygulandı — bir `File`
satırı şu üç koşuldan **herhangi biri** sağlanıyorsa hassas sayıldı:

1. `attached_to_doctype ∈ presets.EXCLUDED_DOCTYPES` (8 doctype)
2. `file_url`, `presets.EXCLUDED_MEDIA_FIELDS` haritasındaki bir alanda duruyor (ters referans)
3. `is_private = 1`

Sonra: bu hassas satırların `content_hash`'ini paylaşan **her public** (`is_private=0`)
`file_url`. Kendisiyle eşleşme (self-match) dahil — çünkü bir `Order.receipt_url`
dosyasının public olması, karşı taraf aramaya gerek olmadan zaten sızıntıdır.

Ara varyantların da ölçümü (yöntem farkının nereden geldiğini göstermek için):

| Tanım | Sonuç |
|---|---:|
| Yalnız (1)+(2), self-match hariç | 43 |
| Yalnız (1)+(3), self-match hariç | 42 |
| **Üçünün birleşimi, self-match dahil** | **44** ✅ |

Üçüncü satır 07 §7.1 ile **birebir aynı**. Kırılım da neredeyse aynı:

| Karşı taraftaki hassas kayıt | 07 (2026-08-18) | Bu ölçüm (2026-08-19) |
|---|---:|---:|
| KYB Verification | 36 | **36** |
| Payment Transaction | 3 | **4** |
| KYC Verification | 3 | **3** |
| Order | 3 | **3** |
| Brand | 1 | **1** |
| Seller Application | 1 | **1** |
| Seller Verification | 1 | **1** |

> Payment Transaction 3 → 4 farkı **yeni dosyadan değil**: bugün `presets.py`'ye
> eklenen `Payment Transaction.receipt_url` ters-referans yolu, zaten sayılan bir
> dosyaya ikinci bir karşı taraf etiketi kazandırdı. Toplam dosya sayısı 44'te
> sabit; bir dosya birden fazla kırılım satırında görünebilir (44 dosya, 49 etiket).

### 1.3 İçerik sınıflandırma yöntemi

Sınıflandırma dosya adına **dayanmıyor**. 44 dosyanın tamamı konteynerden
çıkarılıp (`shutil.copy2`, `is_private=0` diskteki asıl kopya) host'ta
kontak sayfası hâline getirildi ve **44'ü de gözle incelendi**. Belge benzeri
ya da yüz içeren 4 tanesi (#19, #20, #39, #44) ayrıca tam çözünürlükte
büyütülüp okundu.

Public URL'lerin nerede kullanıldığı, `information_schema` üzerinden **tüm
DB'nin** metin kolonlarında (12.800 kolon) tarandı. İlk tarama `LOCATE` ile
yapıldığı için `/files/X`, `/private/files/X` içinde de eşleşiyordu
(alt-dize yanlış pozitifi); her isabet **ankorlu** ikinci geçişte
(`/private` ön eki reddedilerek) gerçek değere karşı doğrulandı. Aşağıdaki
tüm referans sayıları doğrulanmış geçişten.

---

## 2. `_is_protected_pii` bugün ne koruyor, ne kaçırıyor

`media/access_level.py::_is_protected_pii` 44 dosyanın her biri için koşturuldu:

```
KORUNUYOR  (_is_protected_pii = True)   →   4 / 44
AÇIKTA     (_is_protected_pii = False)  →  40 / 44
```

Korunan 4'ün yakalanma yolu:

| Dosya | Yakalayan yol |
|---|---|
| `/files/323-9.png` | `attached_to_doctype=Payment Transaction` + `field_ref=Order.receipt_url` + `field_ref=Payment Transaction.receipt_url` |
| `/files/Gemini_Generated_Image_8tgnab8tgnab8tgn.png` | aynı üçü |
| `/files/H5068c4646bb8478c9c9f0c9000a4b989f.jpg` | `attached_to_doctype=Order` + iki ters referans |
| `/files/H5068c4646bb8478c9c9f0c9000a4b989f6df6f6.jpg` | `attached_to_doctype=Payment Transaction` |

### 2.1 Bugünkü `presets.py` genişlemesinin bu 44'e katkısı: **0**

Görev kapsamındaki soru buydu, ölçüldü. Eski harita (KYB'de yalnız
`identity_document` + `bank_account_document`; `Order`/`Payment Transaction`/
`Data Export Request` hiç yok) ile bugünkü harita, aynı 44 dosya üzerinde
yan yana koşturuldu:

```
ÖNCE  (eski EXCLUDED_MEDIA_FIELDS) korunan:  4 / 44
SONRA (bugünkü harita)             korunan:  4 / 44
Bugünkü değişiklikle YENİ korunan:            0
```

**Neden 0:**

- Korunan 4'ü zaten **birinci yoldan** (`attached_to_doctype ∈ EXCLUDED_DOCTYPES`)
  yakalanıyordu; `Order` ve `Payment Transaction` bugünkü değişiklikten **önce de**
  `EXCLUDED_DOCTYPES` içindeydi. Eklenen `receipt_url` ters referansı onlara
  ikinci bir savunma katmanı getirdi, yeni dosya getirmedi.
- KYB'ye eklenen 4 alan (`imza_sirkuleri`, `ticaret_sicil_gazetesi`,
  `faaliyet_belgesi`, `vergi_levhasi`) bu veri setinde **hiçbir public URL'i
  yakalamıyor**: bu alanların tamamı `/private/files/...` yazımına işaret ediyor.
  Ters referans yolu ancak alan **public URL'in kendisini** tutuyorsa devreye
  girer.

> **Yani bugünkü `presets.py` değişikliği doğru ve gerekli, ama gizil bir
> koruma.** 07 §7.1 D-23'ün "boşluk gizil (AS-32)" tespiti bu ölçümle
> **doğrulandı**: değişiklik gelecekteki bir `set_level(make_private=False)`
> çağrısını durdurur, bugün açıkta duran hiçbir dosyayı kapatmaz.

### 2.2 Kaçırdığı: retroaktif düzeltme (yapısal kusur)

Ölçümün en keskin sonucu şu çelişkidir:

> Düzeltilen 4 dosya için `_is_protected_pii` **True** dönüyordu — yani
> `set_level(file_url, make_private=False)` bugün **reddedilirdi**. Buna
> rağmen dosyalar **public'ti.**

Çünkü `_is_protected_pii` yalnız **toggle anında** çalışır. Dosya en baştan
`is_private=0` yüklendiyse ya da koruma haritası dosya yüklendikten *sonra*
genişlediyse, hiçbir kod yolu geriye dönüp o dosyayı kapatmaz. Koruma
**ileriye dönük**, veri **geriye dönük bozuk**. Bu görevin düzeltmesi tam
olarak bu boşluğu elle kapatıyor; kalıcı çözüm §6 Ö-1.

### 2.3 Yan gözlem — `frappe.get_doc("File", {"file_url": url})` tekil satır döner

`_is_protected_pii`'ye giren `file_doc`, aynı `file_url`'e sahip **birden
fazla** `File` satırı olduğunda bunlardan yalnız birini alır. Ölçülen örnek:
`/files/323-9.png` için 3 satır vardı ve bunlardan biri
(`eb6c4d3dc4`) `attached_to_doctype = NULL`. Birinci yol o satırda başarısız
olurdu; dosyayı ters referans yolu (ikinci yol) yakaladı.

> Bu, `access_level.py` docstring'indeki "İKİ bağımsız yol" tasarımının
> **canlı veride ölçülmüş** bir gerekçesi. Kayda geçsin diye yazıldı; kod
> değişikliği gerektirmiyor.

---

## 3. 44 dosyanın tam listesi ve sınıflandırması

**Sütunlar:** `içerik` = gözle incelenen görselin ne olduğu · `karşı taraf` =
aynı `content_hash`'i paylaşan hassas kayıt · `canlı kullanım` = doğrulanmış
referans · `karar`.

**Kararlar:** 🔴 **SIZINTI** (düzeltildi) · 🟢 **ZARARSIZ** · 🟡 **BELİRSİZ** (bu tabloda yok)

| # | Dosya | Boyut | İçerik (gözle doğrulandı) | Karşı taraf | Canlı kullanım | Karar |
|---:|---|---:|---|---|---|:--:|
| 1 | `1776844966706_ztq1jo.jpg` | 201 KB | Şeffaf saklama kabı ürün render'ı | KYB `ticaret_sicil_gazetesi` | `Listing.primary_image` ×3 | 🟢 |
| 2 | `1776844973120_lrt4cd.png` | 1,42 MB | Mutfakta makarnalı saklama kabı, ürün fotoğrafı | KYB `identity_document`, `vergi_levhasi` | `Listing Image.image` ×3 | 🟢 |
| 3 | `1776844988104_u2ltsc.png` | 1,25 MB | Mutfakta salatalı saklama kabı | KYB `bank_account_document`, `imza_sirkuleri` | `Listing.primary_image` ×1 | 🟢 |
| 4 | `323-1.jpeg` | 273 KB | Pembe katlanır çocuk taburesi, ürün fotoğrafı | KYB | — | 🟢 |
| 5 | `323-2.jpeg` | 247 KB | Mavi katlanır çocuk taburesi | KYB | — | 🟢 |
| 6 | `323-3.jpeg` | 195 KB | Kırmızı/sarı katlanır tabure | KYB | — | 🟢 |
| 7 | `323-38f5e83.jpeg` | 195 KB | Kırmızı/mavi katlanır tabure | KYC `identity_document` | — | 🟢 |
| 8 | `323-5.jpeg` | 82 KB | "Katlanır Çocuk Koltuğu" pazarlama görseli (ozgenplastik.com) | KYB | — | 🟢 |
| 9 | `323-6.jpeg` | 79 KB | Aynı pazarlama görseli, mavi varyant | KYB | — | 🟢 |
| **10** | **`323-9.png`** | **7,20 MB** | **Katlanır tabure ürün render'ı** | **`Order.receipt_url` (ORD-00002) + `Payment Transaction.receipt_url` (PAY-00002)** | **dekont yuvası** | 🔴 |
| 11 | `469119194_…_n.jpg` | 118 KB | Masada drywall zımpara paketleri, "2,6$!!!" notu | KYB ×5 alan + KYC | — | 🟢 |
| 12 | `469119194_…_nf.jpg` | 97 KB | Drywall zımpara paketleri | KYB `ticaret_sicil_gazetesi` | `Listing.primary_image`, `variant_image`, `Buyer Favorite Item` ×22 | 🟢 |
| 13 | `469119194_…_nm.jpg` | 66 KB | Drywall zımpara paketleri (yakın çekim) | KYB `bank_account_document` | `variant_image` ×7 | 🟢 |
| 14 | `71MwppYj0KL._AC_SX679_.jpg` | 71 KB | Makita 9" elmas kesme diski, ürün fotoğrafı | KYB ×3 alan | `Seller Category.image` | 🟢 |
| 15 | `Adsız tasarım (4).jpg` | 34 KB | "Thoptan" marka logosu (mavi zemin) | KYB ×6 alan (KYB-00029'un tamamı) | `Listing Image.image`, `Listing.primary_image` | 🟢 |
| 16 | `Bere-1.png` | 91 KB | Yeşil bere, ürün fotoğrafı | **Brand** `hero_banner` (private) | `variant_image`, `variant_gallery` ×3, `Order Item.image` | 🟢 |
| 17 | `ChatGPT Image 9 Tem 2026 11_31_41.png` | 591 KB | "alkan plast · lossá \| Fayton" marka logosu | KYB | `Admin Seller Profile.logo` (SEL-00023) | 🟢 |
| 18 | `ChatGPT Image 9 Tem 2026 14_00_30.png` | 759 KB | "Mugiss®" marka logosu | KYB ×3 alan | `Admin Seller Profile.logo` (SEL-00034) | 🟢 |
| 19 | `Ekran Görüntüsü - 2025-11-07 09-12-09.png` | 184 KB | Frappe `OperationalError` traceback ekran görüntüsü — **başka bir projeye ait** (`cronhr.local:8000`, `frappe.hr`) | KYB `identity_document` (KYB-00002) | — | 🟢 |
| 20 | `Ekran Görüntüsü - 2025-11-07 10-12-26.png` | 73 KB | Frappe Desk "Users" workspace ekran görüntüsü — kullanıcı verisi görünmüyor | KYB `faaliyet_belgesi` | — | 🟢 |
| 21 | `Ekran Görüntüsü - 2025-11-07 10-13-12.png` | 20 KB | VSCode dosya gezgini (frappe.hr bench ağacı) | KYB ×3 alan | — | 🟢 |
| 22 | `Ekran Görüntüsü - 2025-12-25 11-23-25.png` | 44 KB | LibreOffice "Find and Replace" diyalog kutusu | `Seller Application.identity_document` (SA-00002) | — | 🟢 |
| 23 | `Gemini_Generated_Image_8iyuwo….png` | 1,35 MB | "YAPICI" marka logosu | KYB `faaliyet_belgesi` | `Admin Seller Profile.logo` (SEL-00015) | 🟢 |
| **24** | **`Gemini_Generated_Image_8tgnab….png`** | **6,08 MB** | **Özgen Plastik ürün banner'ı** | **`Order.receipt_url` (ORD-00003) + `Payment Transaction.receipt_url` (PAY-00003)** | **dekont yuvası** | 🔴 |
| 25 | `Gemini_Generated_Image_np9h1e….png` | 1,91 MB | "YAPICI CİVATA — SINCE 1977" vitrin banner'ı | KYB `imza_sirkuleri` ×2 | `Admin Seller Profile.banner_image` (SEL-00015) | 🟢 |
| 26 | `Gemini_Generated_Image_yebmrh….png` | 1,62 MB | "Thoptan — TOPTAN ALIMIN ADRESİ" banner'ı | KYB ×2 alan | `Seller Gallery Image.image` | 🟢 |
| 27 | `H1e6835f6f….jpg` | 99 KB | "GROOVY VISIONS" bere (kırmızı/beyaz), ürün fotoğrafı | KYB | — | 🟢 |
| **28** | **`H5068c4646….jpg`** | **86 KB** | **"GROOVY VISIONS" bere (siyah/beyaz), ürün fotoğrafı** | **`Order.receipt_url` (ORD-00001) + `Payment Transaction.receipt_url` (PAY-00001)** | **dekont yuvası** | 🔴 |
| **29** | **`H5068c4646…6df6f6.jpg`** | **86 KB** | **Aynı bere fotoğrafı (ikinci kopya)** | **`attached_to = Payment Transaction/PAY-00001·receipt_url`** | **dekont yuvası** | 🔴 |
| 30 | `Zucchero_Logo_2018_SaM.jpg` | 19 KB | "ZUCCHERO" marka logosu | KYB | — | 🟢 |
| 31 | `banner-akim-koruma.webp` | 120 KB | Asel akım koruma prizleri, çim üzerinde banner | KYB | `Storefront Layout.sections` (SEL-00026) | 🟢 |
| 32 | `banner-anahtar-oda.webp` | 159 KB | Asel priz/anahtar, oda içi banner | KYB | `Storefront Layout.sections` (SEL-00026) | 🟢 |
| 33 | `istoc.jpg` | 86 KB | "iSTOC" platform logosu | `Seller Verification.document` | `Static Page SEO.og_image` | 🟢 |
| 34 | `kasel_logo_400x400_beyaz.png` | 19 KB | "ASEL Aydınlatma & Elektrik" logosu | KYB `faaliyet_belgesi` | `Admin Seller Profile.logo` (SEL-00026), `Seller Gallery Image.poster_image` | 🟢 |
| 35 | `main_slide_banner02.jpg` | 174 KB | Salata kurutucu ürün montaj banner'ı | KYB `identity_document` (KYB-00034) | `Storefront Layout.sections` (SEL-00034) | 🟢 |
| 36 | `main_slide_banner03.jpg` | 117 KB | Rende/dilimleyici ürün montaj banner'ı | KYB `vergi_levhasi` (KYB-00034) | `Storefront Layout.sections` (SEL-00034) | 🟢 |
| 37 | `main_slide_banner09.jpg` | 176 KB | Saklama kabı / baharatlık seti banner'ı | KYB `faaliyet_belgesi` (KYB-00034) | `Storefront Layout.sections` (SEL-00034) | 🟢 |
| 38 | `main_slide_banner11.jpg` | 67 KB | Turkuaz kase seti banner'ı (siyah zemin) | KYB `ticaret_sicil_gazetesi` (KYB-00034) | `Storefront Layout.sections` (SEL-00034) | 🟢 |
| 39 | `mugiss-mutfak-ve-ev-gerecleri-…jpg` | 113 KB | Mugiss fabrika/kurumsal banner — **2 çalışanın yüzü görünüyor** | KYB ×3 alan | `Seller Gallery Image.image` | 🟢 |
| 40 | `slide-ayakkabi-600x203.jpg` | 20 KB | Timex ayakkabı koruma kutusu banner'ı | KYB | — | 🟢 |
| 41 | `slide4-1-600x203.jpg` | 19 KB | Timex 7'li saklama kabı seti banner'ı | KYB | — | 🟢 |
| 42 | `slide5-600x203.jpg` | 24 KB | Timex popcorn/cips kovası banner'ı | KYB | — | 🟢 |
| 43 | `thoptan-logo-24488E-arka-plan.png` | 227 KB | "Thoptan" logosu (mavi zemin) | KYB `ticaret_sicil_gazetesi`, KYC `identity_document` | `Admin Seller Profile.logo` (SEL-00014) | 🟢 |
| 44 | `timex-6143B6C9CBF22208a66.jpg` | 20 KB | Timex mağaza cephesi fotoğrafı (vitrin, koliler) | KYB | `Seller Gallery Image.image` | 🟢 |

### 3.1 Sınıflandırma gerekçeleri

**🔴 SIZINTI — 4 dosya (#10, #24, #28, #29).** Gerekçe içerik değil, **yuva**:
bu dört dosya `Order.receipt_url` / `Payment Transaction.receipt_url` alanında
duruyor ya da bu doctype'lara `attached_to` ile bağlı. Platformun kendi
politikası (`presets.EXCLUDED_DOCTYPES` + `EXCLUDED_MEDIA_FIELDS`) bu yuvayı
"asla public olamaz" ilan ediyor ve `_is_protected_pii` dördü için de `True`
dönüyor — yani bugün bu dosyaları public *yapmak* reddedilirdi, ama zaten
public **oldukları için** koruma hiç devreye girmemişti (§2.2). İçeriğin bugün
ürün görseli olması durumu değiştirmez: bu alan ödeme dekontu taşımak için var,
bir sonraki gerçek dekont aynı yoldan public olurdu.

**🟢 ZARARSIZ — 40 dosya.** İki ayrı kanıta dayanıyor:

1. **İçerik:** 40'ının da görseli incelendi; hiçbiri kimlik/beyan/dekont belgesi
   değil. Ürün fotoğrafı, marka logosu, vitrin banner'ı, mağaza cephesi ya da
   geliştirici ekran görüntüsü.
2. **Mekanizma:** hassas karşı taraf **ayrı bir `File` satırı** ve zaten
   `/private/files/...` altında. Public satır, satıcının aynı görseli ikinci kez
   — ürün/marka yuvasına — yüklemesinden geliyor. Doğru çare hassas kopyayı
   private tutmaktır; **public ürün görselini gizlemek değil.** 24'ü fiilen
   canlı kullanımda (`Listing`, `Storefront Layout`, `Admin Seller Profile`,
   `Seller Gallery`); bunları private'a almak vitrini kırardı.

**Özel olarak değerlendirilenler:**

- **#19–#22 (geliştirici ekran görüntüleri).** İçerik tam çözünürlükte okundu.
  #19 bir MariaDB kullanıcı adı (`_603c65c70d118802`, parola yok) ve bir
  geliştiricinin yerel dosya yolunu içeriyor — ama **başka bir projeye ait**
  (`cronhr.local`, `frappe.hr`), istoç veritabanı değil. #20/#21/#22'de veri
  yok. Kişisel veri **yok** → 🟢. Yine de meşru bir public kullanımları da yok
  (0 referans); temizlik önerisi §6 Ö-3.
- **#39 (Mugiss kurumsal banner).** İki çalışanın yüzü görünüyor. Bu, satıcının
  kendi `mugiss.com` markalı pazarlama materyali ve `Seller Gallery`'de
  yayımda — satıcının kendi yayın kararı, bizim ürettiğimiz bir sızıntı değil.
  Private'a almak galeriyi kırardı → 🟢.
- **#44 (mağaza cephesi).** Timex Plastik'in kendi vitrin fotoğrafı, `Seller
  Gallery`'de yayımda. Adres/kimlik bilgisi okunmuyor → 🟢.
- **#16 (`Bere-1.png`).** Karşı taraf `Brand.hero_banner` ve o kayıt **private**.
  `Brand` `EXCLUDED_DOCTYPES`'te değil; bir marka hero banner'ının private olması
  tutarsız görünüyor ama D-2 kapsamı dışında, ayrı bulgu olarak §6 Ö-4.

**🟡 BELİRSİZ — 0 dosya.** 44'ün tamamının görseli okunabildi; içeriği
belirlenemeyen dosya kalmadı. Fail-safe kuralının uygulanacağı vaka çıkmadı.

---

## 4. Düzeltme — 4 dosya

Deponun kendi yolu kullanıldı: `media/access_level.py::set_level(file_url,
make_private=True)`. Kendi taşıma mekanizması yazılmadı.

### 4.1 ÖNCE / SONRA

| # | Dosya | `is_private` ÖNCE | `is_private` SONRA | Yeni URL |
|---:|---|:--:|:--:|---|
| 10 | `323-9.png` (3 `File` satırı: `9a7719b484`, `db4dbb6cc7`, `eb6c4d3dc4`) | **0, 0, 0** | **1, 1, 1** | `/private/files/323-9.png` |
| 24 | `Gemini_Generated_Image_8tgnab….png` (2 satır: `5f1bc464bb`, `cb074b0cd7`) | **0, 0** | **1, 1** | `/private/files/Gemini_Generated_Image_8tgnab8tgnab8tgn.png` |
| 28 | `H5068c4646….jpg` (1 satır: `ac8c245f03`) | **0** | **1** | `/private/files/H5068c4646bb8478c9c9f0c9000a4b989f.jpg` |
| 29 | `H5068c4646…6df6f6.jpg` (1 satır: `30e94e1bf0`) | **0** | **1** | `/private/files/H5068c4646bb8478c9c9f0c9000a4b989f6df6f6.jpg` |

Fiziksel taşıma ve bütünlük (sha256 taşımadan önce/sonra **değişmedi**):

```
public/files/  → yok  (4/4 doğru)
private/files/ → var  (4/4 doğru)
  323-9.png                                    e46a92b80c0a6d2f   7.554.143 bayt
  Gemini_Generated_Image_8tgnab8tgnab8tgn.png  c6ecb611d9ac0ea9   6.376.748 bayt
  H5068c4646bb8478c9c9f0c9000a4b989f.jpg       2b5c252ed10b4016      88.096 bayt
  H5068c4646bb8478c9c9f0c9000a4b989f6df6f6.jpg dcb38ccb66d57122      88.120 bayt
```

### 4.2 Ön kontrol: ad çakışması ve veri kaybı riski

`set_level` diskte `os.replace` yapıyor. Hedefte **aynı adlı** bir private dosya
varsa üzerine yazar. Düzeltmeden önce dördü için ayrı ayrı ölçüldü:

```
private/files/ altında aynı adla dosya:  4/4 için YOK  →  çakışma riski yok
```

(Karşılaştırma için: §3'teki #19–#22 dosyalarının private tarafta **aynı adlı
ikizi var**; bu, o dosyalara dokunmama kararının ikinci gerekçesi — bkz. §6 Ö-3.)

### 4.3 `refs.retarget`'ın kapatamadığı iki alan — elle düzeltildi

`set_level`'ın döndürdüğü sonuç, bu görevin bulduğu **ikinci yapısal kusuru**
açıkça gösteriyor:

```
323-9.png              → refs_updated: 0, refs_skipped: 1
                          skipped_detail: ['Order:ORD-00002·receipt_url (sipariş geçmişi)']
Gemini_…8tgnab….png    → refs_updated: 0, refs_skipped: 1  (ORD-00003)
H5068c4646….jpg        → refs_updated: 0, refs_skipped: 1  (ORD-00001)
H5068c4646…6df6f6.jpg  → refs_updated: 0, refs_skipped: 0
```

İki ayrı boşluk:

1. **`Order.receipt_url` bilinçli atlanıyor.** `refs.py` içinde `ORDER_SOURCES`
   → `READONLY_TABLES`; gerekçe "sipariş geçmişi değiştirilmemeli". Doğru bir
   kural ama burada sonucu **ölü referans**: dosya taşındı, `Order.receipt_url`
   hâlâ eski `/files/...` adresini gösteriyor.
2. **`Payment Transaction.receipt_url` hiç bilinmiyor.** `usage.py`'daki
   `LIVE_SOURCES`/`ORDER_SOURCES` listelerinde yok. Bu yüzden `refs_skipped`
   sayısına bile **girmiyor** — operatöre hiçbir uyarı gitmiyor. Sessiz kırılma.

Her ikisi de düzeltme sırasında elle onarıldı (veri düzeltmesi, kod değişikliği
değil) ve doğrulandı:

| Kayıt | `receipt_url` ÖNCE | `receipt_url` SONRA |
|---|---|---|
| ORD-00001 | `/files/H5068c4646….jpg` | `/private/files/H5068c4646….jpg` |
| PAY-00001 | `/files/H5068c4646….jpg` | `/private/files/H5068c4646….jpg` |
| ORD-00002 | `/files/323-9.png` | `/private/files/323-9.png` |
| PAY-00002 | `/files/323-9.png` | `/private/files/323-9.png` |
| ORD-00003 | `/files/Gemini_…8tgnab….png` | `/private/files/Gemini_…8tgnab….png` |
| PAY-00003 | `/files/Gemini_…8tgnab….png` | `/private/files/Gemini_…8tgnab….png` |

```
Eski URL'e ölü referans kaldı mı:  () — 4/4 için boş
```

---

## 5. Doğrulama

### 5.1 `curl` — public erişim kapandı

Ölçüm `istoc.localhost` gateway'i üzerinden, **kimlik doğrulaması olmadan**
(`http://localhost:8001`, `Host: istoc.localhost` → `frappe-frontend:8080`).

> Gateway'in `:80` portu storefront/panel'e gidiyor; Frappe `:8001`'de. İlk
> denemede `:80` ve `:8080` üzerinden alınan `502` bu yönlendirmedendi, dosya
> durumuyla ilgisi yoktu — `:8001` üzerinden bilinen public bir dosya
> (`/files/Bere-1.png`) `200` döndüğü kontrol edilerek doğrulandı.

**ÖNCE — 4/4 dosya kimliksiz olarak tam içerikle servis ediliyordu:**

```
/files/323-9.png                                     → 200  bytes=7554143  image/png
/files/Gemini_Generated_Image_8tgnab8tgnab8tgn.png   → 200  bytes=6376748  image/png
/files/H5068c4646bb8478c9c9f0c9000a4b989f.jpg        → 200  bytes=88096    image/jpeg
/files/H5068c4646bb8478c9c9f0c9000a4b989f6df6f6.jpg  → 200  bytes=88120    image/jpeg
```

**SONRA — eski public adres:**

```
/files/323-9.png                                     → 404  (Frappe HTML 404, görsel bayt YOK)
/files/Gemini_Generated_Image_8tgnab8tgnab8tgn.png   → 404
/files/H5068c4646bb8478c9c9f0c9000a4b989f.jpg        → 404
/files/H5068c4646bb8478c9c9f0c9000a4b989f6df6f6.jpg  → 404
```

**SONRA — yeni private adres, kimliksiz:**

```
/private/files/323-9.png                                     → 403 Forbidden
/private/files/Gemini_Generated_Image_8tgnab8tgnab8tgn.png   → 403 Forbidden
/private/files/H5068c4646bb8478c9c9f0c9000a4b989f.jpg        → 403 Forbidden
/private/files/H5068c4646bb8478c9c9f0c9000a4b989f6df6f6.jpg  → 403 Forbidden
```

`404` nginx'in `try_files … @webserver` zincirinden geliyor: dosya artık
`sites/istoc.localhost/public/` altında yok, istek Frappe'ye düşüyor ve Frappe
404 üretiyor. `403`, `frappe.utils.response.download_private_file`'ın
`session.user == "Guest"` kontrolünden. **Beklenen davranış budur.**

**Regresyon kontrolü — dokunulmamış public dosya bozulmadı:**

```
/files/Bere-1.png  → 200  bytes=93662
```

### 5.2 Meşru erişim kırılmadı

Frappe'nin **gerçek** private-dosya yetki kapısı
(`frappe.core.doctype.file.utils.find_file_by_url`, yani
`download_private_file`'ın kullandığı fonksiyon) beş farklı kullanıcıyla
koşturuldu:

| Kullanıcı | Rol/ilişki | 4 dekont dosyasına erişim |
|---|---|---|
| `Administrator` | süper-admin | **4/4 ERİŞEBİLİR** ✅ |
| `seyfullah.yapici@istoc.com` | **siparişlerin sahibi (alıcı)** — ORD-00001/2/3, PAY-00001/2/3 | **4/4 ERİŞEBİLİR** ✅ |
| `satis@thoptan.com` | dosya sahibi / satıcı | **4/4 ERİŞEBİLİR** ✅ |
| `cankayaplastik@istoc.com` | **ilgisiz satıcı** | 3/4 erişebilir ⚠ (bkz. §6 Ö-2) |
| `Guest` | kimliksiz | **0/4 — hiçbirine erişemez** ✅ |

Sipariş sahibi ve satıcı dekontlarını **hâlâ görebiliyor**; kimliksiz erişim
tamamen kapandı. Amaçlanan sonuç budur.

### 5.3 Testler

```
bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access_level
    Ran 15 tests in 2.364s   OK

bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access
    Ran 17 tests in 3.562s   OK
```

Toplam **32 test, hepsi geçti.** Her iki test dosyasının konteyner/host sha256'sı
§1.1'de eşit doğrulandı.

### 5.4 Düzeltme sonrası D-2 yeniden ölçümü

Aynı betik (§1.2, üç yolun birleşimi) düzeltmeden sonra tekrar koşturuldu:

```
BİRLEŞİM: distinct public file_url = 40      (44 → 40)
kırılım: KYB Verification 36 · KYC Verification 3 · Brand 1 · Seller Application 1 · Seller Verification 1
diskte: 40 / 40
_is_protected_pii = True olan public dosya:  0 / 40
```

`Order` ve `Payment Transaction` kırılımdan **tamamen düştü.** Politika ile veri
artık tutarlı: `_is_protected_pii`'nin koruduğu hiçbir dosya public değil.

### 5.5 Ortam hijyeni

- **`Media Engine Settings` bayrakları — değişmedi:**
  `media_pipeline_enabled=0`, `rendition_on_upload=0`, `manifest_api_enabled=0`
  (düzeltme öncesi ve sonrası ayrı ayrı okundu; `max_renditions_per_asset=40`
  bayrak değil, sayı ayarı).
- **Üretilen test kaydı yok.** Betikler yalnız okuma + mevcut dosyalar üzerinde
  `set_level` yaptı; hiçbir doctype'ta yeni kayıt oluşturulmadı.
- `set_level`'ın ürettiği `ACTION_LEVEL_CHANGED` denetim kayıtları
  **kasıtlı olarak bırakıldı** — bu düzeltmenin izidir, test artığı değil.
- Konteynerdeki geçici betikler ve çıkarılan 44 dosyanın kopyası silindi.

---

## 6. Açık kalan bulgular

| # | Bulgu | Önem | Gerekçe |
|---|---|---|---|
| **Ö-1** | **`_is_protected_pii` retroaktif değil.** Koruma yalnız `set_level` anında çalışır; en baştan public yüklenmiş ya da haritaya sonradan giren bir dosyayı hiçbir kod yolu geri kapatmaz. Düzeltilen 4 dosya tam olarak bu boşluktan sızmıştı (§2.2). | **YÜKSEK** | Kalıcı çözüm: `EXCLUDED_DOCTYPES`/`EXCLUDED_MEDIA_FIELDS` kapsamındaki public dosyaları periyodik tarayıp private'a alan bir scheduler görevi + idempotent migration patch. |
| **Ö-2** | **Private katmanda çapraz-satıcı görünürlüğü.** İlgisiz bir satıcı (`cankayaplastik@istoc.com`) başka satıcının dekontlarından 3'ünü okuyabiliyor. **Bu benim değişikliğimin sonucu değil** — hiç dokunulmamış private KYB dosyalarıyla tekrar ölçüldü, aynı desen orada da var. `find_file_by_url` aynı URL'e ait birden çok `File` satırından **herhangi biri** okunabilirse erişim veriyor. | **YÜKSEK** | Ayrı bir görev; D-2'nin kapsamı dışı. Düzeltme yine de net iyileştirme: kimliksiz erişim (herkes) → yalnız oturum açmış satıcılar. |
| **Ö-3** | **#19–#22: amaçsız public geliştirici ekran görüntüleri.** İçerik doğrulandı, kişisel veri yok, 0 canlı referans — ama meşru bir public kullanımı da yok. **Taşınmadılar**, çünkü private tarafta **aynı adlı** dosya var (sha256 eşit) ve `set_level`'ın `os.replace`'i onu üzerine yazardı; ayrıca `File` satırları çoğalırdı. | ORTA | Operatör kararıyla `trash.py` üzerinden silinmeli, taşınarak değil. |
| **Ö-4** | **`Brand.hero_banner` private.** `Bere-1.png`'in karşı tarafı private bir `Brand` kaydı. `Brand` `EXCLUDED_DOCTYPES`'te değil; bir marka hero banner'ının private olması tasarımla çelişiyor. | DÜŞÜK | `Brand` medya alanlarının erişim seviyesi ayrıca gözden geçirilmeli. |
| **Ö-5** | **`Payment Transaction.receipt_url` referans zincirinde yok.** `usage.LIVE_SOURCES`/`ORDER_SOURCES`'ta tanımlı değil; `set_level` bu alanı ne günceller ne de `refs_skipped`'a yazar → **sessiz** kırık referans (§4.3). | ORTA | `usage.ORDER_SOURCES`'a eklenmeli. Bu görevde koda dokunulmadı (kapsam dışı dosya), veri elle onarıldı. |
| **Ö-6** | **P-12 hâlâ açık.** Bu ölçümün tamamı **yerel dev** verisi. Üretimde KYB alanlarında gerçek imza sirküleri/kimlik taraması var; aynı çift-yükleme mekanizması orada **gerçek PII** sızdırır. | **EN YÜKSEK** | Üretim erişimi açılınca §1.2'deki birleşim sorgusu ve §2'deki `_is_protected_pii` taraması **aynen** tekrarlanmalı. |

---

## 7. K-1 kapanış durumu

07 §9'daki kontrol listesine göre:

| Kalem | Durum |
|---|---|
| ☑ 44 dosya sınıflandırıldı | **EVET** — 44/44 görsel olarak incelendi |
| ☑ Hassas içerik bulundu mu | **HAYIR** — hiçbirinin içeriği kişisel veri değil |
| ☑ Yapısal sızıntı bulundu mu | **EVET, 4 adet** — PII yuvasında public dosya |
| ☑ Erişim düzeltmesi yapıldı | **EVET** — 4/4 private, `curl` ile kanıtlandı |
| ☑ Meşru erişim korundu | **EVET** — sahip + admin 4/4 erişebiliyor, Guest 0/4 |
| ☑ Testler geçiyor | **EVET** — 32/32 |
| ☐ Belirsiz kalan | **0** |

**K-1'in yerel dev ayağı kapanabilir.** Üretim ayağı (P-12 / Ö-6) açık kalıyor
ve bu ölçüm onun yerine geçmez.

---

## Ek A — Yeniden üretim komutları

```bash
# Konteyner ↔ host bütünlüğü
shasum -a 256 tradehub_core/media/presets.py tradehub_core/media/access_level.py
docker exec istoc-dev-backend-1 sha256sum \
  /home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/media/presets.py \
  /home/frappe/frappe-bench/apps/tradehub_core/tradehub_core/media/access_level.py

# D-2 ölçümü (üç yolun birleşimi) — betik konteynere kopyalanıp koşturulur
docker cp /tmp/d2/d2_union.py istoc-dev-backend-1:/home/frappe/d2_union.py
docker exec -w /home/frappe/frappe-bench/sites istoc-dev-backend-1 \
  ../env/bin/python /home/frappe/d2_union.py

# Public erişim kontrolü (kimliksiz)
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" \
  -H "Host: istoc.localhost" "http://localhost:8001/files/<dosya>"
curl -s -o /dev/null -w "%{http_code} %{size_download}\n" \
  -H "Host: istoc.localhost" "http://localhost:8001/private/files/<dosya>"

# Testler
docker exec -w /home/frappe/frappe-bench istoc-dev-backend-1 \
  bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access
docker exec -w /home/frappe/frappe-bench istoc-dev-backend-1 \
  bench --site istoc.localhost run-tests --module tradehub_core.tests.test_media_access_level
```

## Ek B — Bu görevde değiştirilmeyenler

- `tradehub_core/media/presets.py` — **dokunulmadı.** Bugünkü genişleme zaten
  yeterli; bu 44'ün hiçbiri haritaya yeni bir giriş gerektirmiyor (§2.1).
- `api/media_manifest.py`, `media/pipeline_bridge.py`, `media/browse.py`,
  `api/seller_media.py`, `hooks.py`, DocType JSON'ları, `docs/standards/` —
  kapsam dışı, paralel çalışma var.
- **Hiç kod değişmedi.** Bu görevin tek kalıcı çıktısı bu rapor ve 4 dosyanın
  veri düzeltmesidir.
