# Medya SEO Alanları ve Üretim Kuralları — Ar-Ge

**Linear:** TUR-135 · **Faz:** 3 · **Etiket:** `arge`, `SM`
**Bağımlı olduğu işler:** TUR-133 (kategorizasyon), TUR-134 (arama/filtreleme),
TUR-132 (EXIF/mime), TUR-122 (WP assimilasyon) — **dördü de Backlog**.
**Blokladığı:** TUR-136 (Done).

> Bu bir **ar-ge** belgesidir: karar üretir, kod üretmez. Uygulama sırası §9'da.
> Ölçümler 18 Ağustos 2026, prod'dan restore edilmiş local veritabanında alındı.

---

## 1. Bulgu: alanlar var, tüketen yok

Medya kayıtlarında SEO alanları **zaten mevcut** (`v15_9_15` yaması):
`th_media_alt`, `th_media_title`, `th_media_description`, `th_media_tags`.
Panelde alt metni eksik olan görseller için uyarı rozeti bile var
(`MediaCard.missingAlt`) ve yedeklerde bu alanlar sadakatle taşınıyor.

Ama ölçüm şunu söylüyor:

| Ölçüm | Değer |
|---|---|
| Public dosya (tekil adres) | **3.123** |
| Alt metni dolu | **0** (%0,0) |
| Başlık dolu | **0** (%0,0) |
| Açıklama dolu | **0** (%0,0) |
| `Listing`'e bağlı görsel | 1.160 |
| İçerik-hash'li (SEO'suz) dosya adı | 286 (%9,2, yeni yüklemeler) |

Ve kod tarafında:

```
seo/  →  th_media_alt|title|description  :  0 eşleşme
```

`th_media_alt` **yazılabilir ama okunmaz bir alandır**: hiçbir API'den dönmüyor,
vitrine ulaşmıyor, JSON-LD'ye girmiyor, `og:image:alt` üretmiyor. Satıcının
yazdığı alt metni bugün yalnızca yedeğe gidiyor.

**Ar-ge sonucu 1:** TUR-135 bir "alan ekleme" işi değil, **köprü kurma** işidir.
Alan setini genişletmeden önce mevcut setin tüketilmesi gerekir.

**Ar-ge sonucu 2:** %0 doluluk, elle doldurmaya dayalı bir tasarımın bu üründe
çalışmayacağının kanıtıdır. Otomatik üretim opsiyonel bir kolaylık değil,
**varsayılan** olmalıdır.

## 2. Mevcut SEO altyapısı — neyi hazır buluyoruz

`tradehub_core/seo/` altında 3.643 satırlık, çalışan bir alt sistem var:

| Modül | İşi | Medya ile ilişkisi |
|---|---|---|
| `meta_builder.py` | `og:*`, `twitter:*`, meta description | `og_image` var, **`og:image:alt` YOK** |
| `schema_builder.py` | JSON-LD (Product, Organization…) | `"image": ["url", …]` — düz URL, **`ImageObject` değil** |
| `og_image.py` | 1200×630 OG görseli üretimi + fallback | Medya kaydını değil, dosyayı tanır |
| `sitemap_generator.py` | `<urlset>` üretimi | **Görsel sitemap namespace'i yok** |
| `slugify.py` | `slugify_tr` — Türkçe karakter → URL-safe | Medyada kullanılmıyor |
| `i18n.py` | Çok dilli içerik + hreflang | Aşağıya bak |

**Çok dillilik zaten çözülmüş bir problem.** `CONTENT_TRANSLATABLE_FIELDS` tek
kaynak olarak duruyor; yama (kolon üretimi), controller (senkron + zorunluluk)
ve API okuma katmanı (`resolve_content_field`) aynı sözlükten besleniyor. Desen:
`{alan}_tr/_en/_ar/_ru` + kayıt başına `content_default_lang`. URL/hreflang
dilleri `tr`+`en`, içerik dilleri 4.

### 2.1 Kurulu araçlar — yeni bağımlılık gerekmiyor

Kurulu paketler doğrudan çalışma ortamından okundu (19 Ağustos 2026):

| Paket | Sürüm | İşimize karşılığı |
|---|---|---|
| `Pillow` | **12.2.0** | Gerçek çözünürlük okuma (`th_media_width/height`), yeniden boyutlandırma, biçim dönüşümü |
| `beautifulsoup4` | **4.12.3** | `seo_html_injector` bunu kullanıyor — etiket yerleştirme |
| `lxml` | **6.1.1** | Site haritası ve HTML ayrıştırma |
| `pypdf` | 6.13.3 | Bu iş için gereksiz; not olarak burada (Frappe PDF doğrulaması kullanıyor) |

Pillow'un biçim desteği de ölçüldü: **WebP ve AVIF kaydedilebiliyor**, HEIF
kaydedilemiyor. Yani sayfa hızı kazancının aracı (WebP) hazır, ek eklenti
gerekmiyor.

Kurulu OLMAYANLAR ve neden gerekmediği:

| Paket | Karar |
|---|---|
| `python-slugify` | **Gerekmiyor** — `seo/slugify.py:slugify_tr` Türkçe karakter haritasıyla zaten var ve testleri mevcut. İkinci bir slug üreticisi, iki farklı adres üretme riski demek |
| `pillow-avif-plugin` | **Gerekmiyor** — Pillow 12.2 AVIF'i kendi içinde kaydedebiliyor |
| `pillow-heif` | **Gerekmiyor** — HEIF yükleme zaten kabul edilmiyor (`upload_policy`); ihtiyaç doğarsa ayrı karar |

**Ar-ge sonucu 3a:** Bu işin maliyeti lisans ya da bağımlılık değil, yalnızca
geliştirme zamanı. Görsel açıklamasını yapay zekâyla üretme seçeneği §8'de
ayrıca değerlendirildi ve alınmadı.

**Ar-ge sonucu 3:** `th_media_alt` **tek kolon** ve bu, 4 dilli bir vitrinde
yanlış. Alt metni içeriktir, arayüz metni değil. Ya mevcut desene katılmalı ya
da neden katılmadığı yazılmalı — §4.2.

## 3. Çatışma: SEO dosya adı ister, güvenlik istemez

`media/naming.py` (TUR-130/141) yeni yüklemelerin disk adını
`<sha256(içerik)[:32]>.<uzantı>` yapıyor. Gerekçesi açık ve geçerli: adres
tahmin edilebilir olmasın.

Görsel SEO'sunun klasik sinyallerinden biri ise **dosya adıdır**
(`kirmizi-deri-canta.jpg`). İki karar doğrudan çatışıyor.

**Çözüm — çatışma görünüşte:** `naming.py` yalnız **disk adını** ve `file_url`'i
değiştiriyor; `File.file_name` (görünen ad) DEĞİŞMİYOR. Yani kaybedilen tek
sinyal URL segmentidir ve onun ağırlığı `alt` + çevresel metin + yapısal veri
yanında düşüktür.

**Karar:** Dosya adı SEO'su **kovalanmayacak**. Güvenlik kararı korunur.
Kaybedilen sinyal §4'teki alan setiyle fazlasıyla telafi edilir. Alternatif
(slug'lu ikinci bir servis rotası: `/i/<slug>-<hash>.jpg`) §8'de değerlendirildi
ve **reddedildi**.

## 4. Alan seti

### 4.1 Karar tablosu

| Alan | Zorunlu | Üretim | Kaynak / kural |
|---|:-:|---|---|
| `alt` | **Evet** (görselde) | **Otomatik**, elle ezilebilir | §5.1 |
| `title` | Hayır | Otomatik | Görsel adı → `slugify_tr` tersi (tire→boşluk, ilk harf büyük) |
| `description` | Hayır | **Elle** | Otomatik üretimi değersiz: aynı cümleyi tekrarlayan açıklama SEO'ya katkı vermez, gürültü üretir |
| `tags` | Hayır | Otomatik öneri + elle | Kategori ağacından (TUR-133 gelince) |
| `caption` | — | — | **EKLENMEYECEK** — `description` ile aynı işi yapar; iki alan tutmak ikisinin de boş kalmasıyla sonuçlanır (bkz. %0 ölçümü) |
| `slug` | — | — | **EKLENMEYECEK** — medya kaydının kendi sayfası yok; slug'ı olan varlık `Listing`. Medyaya slug eklemek, hiçbir yerde çözülmeyen bir adres üretirdi |
| `canonical` | — | — | **EKLENMEYECEK** — aynı gerekçe. Canonical sayfa özelliğidir; görselin canonical'ı onu gösteren sayfadır |

**Ar-ge sonucu 4:** Kapsamda geçen `slug` ve `canonical` medya kaydına ait
değildir. Issue "değerlendirilmelidir" diyor; değerlendirme sonucu **hayır** ve
gerekçesi yukarıdadır. Bu, kapsamın daraltılması değil, sorunun cevaplanmasıdır.

### 4.2 Çok dillilik kararı

`alt` ve `title` **çevrilebilir alanlar setine katılır** — `Listing.title` ile
aynı desen (`_tr/_en/_ar/_ru` + `content_default_lang`).

Gerekçe: vitrin 4 dilli ve `alt` doğrudan kullanıcıya okunan içeriktir (ekran
okuyucu onu sesli okur). Tek kolon tutmak, Türkçe alt metnini İngilizce sayfada
göstermek demekti.

Maliyet dürüstçe: 2 alan × 4 dil = 8 kolon. Ama `CONTENT_TRANSLATABLE_FIELDS`
zaten kolon üretimini, senkronu ve okumayı tek yerden yönetiyor; ek karmaşıklık
sözlüğe iki satır eklemekten ibarettir.

`description` ve `tags` **tek dil kalır**: ikisi de dış yüzde render edilmiyor
(§6), yalnız panel içi arama/filtreleme besliyor.

## 5. Otomatik üretim kuralları

### 5.0 Kapsam: aynı kural iki yerde işler

Üretim tek bir kural olarak yazılır ve iki ayrı yerde uygulanır. Bunu ayrı
maddeler hâlinde bırakmak, "peki bugünkü katalog ne olacak" sorusunu belgenin
15 satır ilerisine taşıyordu:

| Hangi görseller | Ne zaman | Nasıl |
|---|---|---|
| **Yeni yüklenenler** | Görsel bir kayda eklendiği anda (§5.2) | Kanca üzerinden otomatik; satıcı hiçbir şey yapmaz |
| **Mevcut 1.160 ürün görseli** | Zamanlanmış, parça parça (§5.3) | Aynı üretim fonksiyonu, toplu çağrı |

Geriye dönük kısım atlanırsa bugünkü katalogun tamamı tanımsız kalır — asıl
değer zaten orada duran 1.160 görselde. Yeni yükleme tarafı ise kuralın
kalıcılığını sağlar: bir kez kurulduktan sonra kimsenin bir şey yapması
gerekmez.

### 5.1 `alt` üretimi — öncelik zinciri

Görselin bağlı olduğu kayıttan türetilir; ilk dolu olan kazanır:

```
1. Elle yazılmış alt                      → olduğu gibi (insan kararı en üstte)
2. Listing'e bağlıysa:
     "<Listing.title> — <Brand.name>"     → 2+ görselde: "… (2)", "… (3)"
3. Kategori sayfasına bağlıysa:
     "<Category.category_name> kategorisi"
4. Mağaza görseliyse:
     "<Store.name> mağaza görseli"
5. Hiçbiri yoksa                          → BOŞ BIRAKILIR
```

**Neden 5. adımda boş bırakılıyor:** dosya adından alt üretmek (`IMG_4821` →
"img 4821") anlamsız metin üretir. Boş `alt`, ekran okuyucuya "bu görsel
dekoratif" der; yanlış `alt` ise yalan söyler. **Boş, yanlıştan iyidir.**

**Sıra numarası neden var:** aynı ürünün 5 görseli aynı alt metnini taşırsa
arama motoru bunu yinelenen içerik sayar ve hepsini birden değersizleştirir.

### 5.2 Ne zaman üretilir

| An | Davranış |
|---|---|
| Yükleme (`upload_media`) | Üretilmez — dosya henüz bir kayda bağlı değil |
| **Bir kayda eklendiğinde** (`attached_to` dolduğunda) | Üretilir |
| Bağlı kaydın başlığı değiştiğinde | **Yalnız otomatik üretilmişse** yenilenir |
| Satıcı elle yazdığında | Bir daha asla otomatik ezilmez |

Bunun için `th_media_alt_auto` (Check) alanı gerekir: "bu değer üretildi mi,
yazıldı mı". Bu bayrak olmadan "elle yazılanı ezme" kuralı uygulanamaz —
ölçülemeyen kural, uygulanmayan kuraldır.

### 5.3 Geriye dönük doldurma

3.123 dosyanın tamamı bugün boş. Doldurma **parça parça** ve zamanlanmış
olmalı — `av.backfill_pending` deseni birebir uygulanabilir (tek turda 500
kayıt, kuyruğu boğmadan). Öncelik: `Listing`'e bağlı 1.160 görsel; kalanının
SEO değeri yok.

## 6. Dış yüzeye çıkış — asıl iş

Alan doldurmak tek başına hiçbir şey yapmaz. Tüketim noktaları:

| Yüzey | Bugün | Olması gereken |
|---|---|---|
| `<img alt>` (vitrin) | Ürün adından türetiliyor, medya kaydı okunmuyor. 169 `alt` niteliğinden **32'si boş** | Listing API'si görsel başına `alt` döndürür, vitrin onu basar |
| `og:image` | Var | `og:image:alt`, `og:image:width/height` eklenir (alanlar zaten var: `th_media_width/height`) |
| JSON-LD | `"image": ["url"]` düz dizi | `ImageObject` (`url`, `caption`, `width`, `height`) — Google görsel araması bunu okur |
| Görsel sitemap | Yok | `xmlns:image` namespace'i + sayfa başına `<image:image>` girdileri |
| `Listing` API çıktısı | Yalnız URL | `{url, alt, width, height}` nesnesi |

**Ar-ge sonucu 5:** İşin ağırlık merkezi medya modülünde değil, **`seo/`
modülünde ve `api/listing.py`'de**. TUR-135 medya işi gibi görünüyor ama
teslimatının çoğu SEO tarafında.

## 7. Somut örnek: bugün canlıdaki bir ürün görseli

Soyut kalmasın diye gerçek bir örnek. Aşağıdaki etiket **bugün canlıda** duruyor
(ürün: `LST-00206`, dosya kaydı `f6f22c3188`) ve ölçümler o dosyanın kendi
künyesinden alındı.

### 7.1 Bugünkü hâli

```html
<img class="w-full h-full object-contain select-none"
     src="/files/Ekran Görüntüsü - 2026-06-22 10-27-16.png"
     alt="20 Adet Alçı Taş Boyama Seti Anne Çocuk Etkinliği Çocuk Gelişimi Objeleri (SADECE OBJELER) - 1"
     width="800" height="800"
     decoding="async" draggable="false" loading="eager">
```

Bu tek etikette yedi ayrı sorun var ve hepsi ölçülebilir:

| # | Sorun | Kanıt |
|:-:|---|---|
| 1 | **`alt` ham ürün başlığının kopyası** | 100 karakter, içinde `(SADECE OBJELER)` var. Ekran okuyucu bunu olduğu gibi sesli okuyor |
| 2 | **`- 1` eki ilk görsele de ekleniyor** | `listingService.ts:1331` → `${raw.title} - ${i + 1}`. Tek görselli üründe bile "- 1" diyor, hiçbir şey ifade etmiyor |
| 3 | **Medya kaydındaki alt hiç okunmuyor** | Bu dosyanın `th_media_alt` alanı boş; dolu olsa da vitrine ulaşmıyor (§1) |
| 4 | **`width`/`height` YANLIŞ** | Etikette `800×800`, dosya gerçekte **497×645**. Tarayıcı yanlış yer ayırıyor → sayfa zıplıyor (CLS cezası). Doğru değerler `th_media_width/height` alanlarında **zaten duruyor** |
| 5 | **Dosya adı "Ekran Görüntüsü"** | Arama motoruna "bu bir ekran görüntüsü" diyor. Sistemde adı `Ekran` ile başlayan **9 dosya** var |
| 6 | **URL'de boşluk + Türkçe karakter** | Gerçek istek `Ekran%20G%C3%B6r%C3%BCnt%C3%BCs%C3%BC...` olarak gidiyor. Adresinde boşluk olan **271 dosya** var |
| 7 | **Hâlâ PNG, optimize edilmemiş** | 398 KB, `th_optimized_at` boş. Sistemde WebP'ye dönmemiş **342 PNG** var (TUR-128'in kapsamı) |

### 7.2 SEO'lu hâli

```html
<img class="w-full h-full object-contain select-none"
     src="/files/Ekran Görüntüsü - 2026-06-22 10-27-16.png"
     alt="Alçı taş boyama seti — 20 parça obje"
     width="497" height="645"
     decoding="async" draggable="false"
     loading="eager" fetchpriority="high">
```

Değişen üç şey:

- **`alt`** kısa ve okunabilir; üründen türetiliyor ama ham başlık değil (§5.1)
- **`width`/`height`** gerçek ölçüler — `th_media_width/height`'tan okunuyor
- **`fetchpriority="high"`** LCP görselinde (ilk görsel), diğerlerinde yok

**`src` bilerek AYNI kaldı.** Mevcut dosyaların adını değiştirmek onları gösteren
tüm bağlantıları kırar, kazanç ise düşük (§3). Yeni yüklemelerde adres zaten
içerik-hash'li ve sinyal yapısal veriden geliyor.

İkinci görselin `alt`'ı: `"Alçı taş boyama seti — 20 parça obje (2. görsel)"` —
sıra numarası anlamlı bir ifadeyle, çıplak `- 2` ile değil (§5.1'deki kural).

### 7.3 Sayfaya eklenecek üç şey

Etiketin dışında, aynı sayfada bugün **hiç olmayan** üç çıktı:

**a) Yapısal veri** — Google görsel aramasının asıl okuduğu yer. Bugün düz URL
dizisi var (`"image": ["https://..."]`), olması gereken:

```json
"image": [{
  "@type": "ImageObject",
  "url": "https://<site>/files/Ekran Görüntüsü - 2026-06-22 10-27-16.png",
  "caption": "Alçı taş boyama seti — 20 parça obje",
  "width": 497,
  "height": 645
}]
```

**b) Paylaşım önizlemesi** — `og:image` var ama `og:image:alt` **yok**:

```html
<meta property="og:image"        content="https://<site>/files/...png">
<meta property="og:image:alt"    content="Alçı taş boyama seti — 20 parça obje">
<meta property="og:image:width"  content="497">
<meta property="og:image:height" content="645">
```

WhatsApp/LinkedIn'de link paylaşıldığında görselin ne olduğu bugün okunmuyor.

**c) Görsel site haritası** — `xmlns:image` namespace'i yok, yani Google
görselleri ayrıca keşfedemiyor; yalnız sayfayı tararken rastlıyor:

```xml
<url>
  <loc>https://<site>/urun/alci-tas-boyama-seti</loc>
  <image:image>
    <image:loc>https://<site>/files/...png</image:loc>
    <image:caption>Alçı taş boyama seti — 20 parça obje</image:caption>
  </image:image>
</url>
```

### 7.4 Bu örnekten çıkan ders

Aynı dosyada **üç ayrı işin** açığı birden duruyor:

| İş | Bu dosyadaki durumu |
|---|---|
| TUR-135 (SEO) | `alt` ham, boyutlar yanlış, yapısal veri yok |
| TUR-128 (optimizasyon) | 398 KB PNG, WebP'ye dönmemiş |
| TUR-125 (tarama) | `scan_status` boş — geri doldurma yapılmamış |

Sayfa hızı da bir SEO sinyali olduğu için 342 PNG'nin WebP'ye dönmesi tek başına
sıralamaya katkı verir. Yani TUR-135 ile TUR-128 aynı dosyaya dokunuyor ve
sıralamayı buna göre kurmak gerekiyor (§9).

---

## 8. Değerlendirilip reddedilenler

- **Slug'lu servis rotası** (`/i/kirmizi-canta-<hash>.jpg`): dosya adı sinyalini
  geri kazandırırdı. Reddedildi — nginx'in doğrudan servisini Python'a taşır
  (her görsel isteği uygulama sunucusuna düşer), `naming.py` sözleşmesini
  karmaşıklaştırır ve kazanç düşük.
- **`caption` ayrı alanı**: `description` ile örtüşüyor.
- **Medyaya `slug`/`canonical`**: medya kaydının sayfası yok (§4.1).
- **EXIF'ten otomatik `alt`**: TUR-132 EXIF'i **siliyor**; oradan veri okumak iki
  işi ters yönde çeker.
- **Alt metnini yapay zekâyla üretme**: kapsam dışı, maliyet ve doğrulanabilirlik
  belirsiz. Kural tabanlı üretim (§5.1) ölçülebilir ve açıklanabilir.

## 9. Uygulama sırası ve bağımlılıklar

Bağımlılıkların **hepsi beklenmek zorunda değil**:

| Adım | Bağımlı mı | Yapılabilir mi |
|---|---|---|
| 1. `alt`/`title` çevrilebilir sete alınması + `_auto` bayrağı | — | **Şimdi** |
| 2. `alt` üretimi (Listing/kategori/mağaza zinciri) | — | **Şimdi** (kategori dalı TUR-133'te genişler) |
| 3. Listing API'sinin görsel nesnesi döndürmesi | — | **Şimdi** |
| 4. `og:image:alt` + `ImageObject` + görsel sitemap | — | **Şimdi** |
| 5. Vitrinin `alt`'ı medyadan basması | — | **Şimdi** |
| 6. Geriye dönük doldurma | 1-2 | **Şimdi** |
| 7. `tags` otomatik önerisi | **TUR-133** | Bekler |
| 8. Medya aramasında SEO alanları | **TUR-134** | Bekler |
| 9. WP'den gelen alt metinlerinin taşınması | **TUR-122** | Bekler |

**Ar-ge sonucu 6:** Dört bağımlılığın yalnız üçü, üç maddeyi bekletiyor.
Kabul kriterlerinin tamamı (alan seti, zorunlu/opsiyonel ayrımı, üretim
kuralları, tutarlı yönetim) **bugün** karşılanabilir.

## 10. Kabul kriterleri karşılığı

| Kriter | Karşılığı |
|---|---|
| SEO alan seti net belirlenmiş olmalı | §4.1 — eklenecek, eklenmeyecek ve gerekçeleri |
| Zorunlu ve opsiyonel alanlar ayrılmış olmalı | §4.1 — yalnız `alt` zorunlu, o da görselde |
| Otomatik üretim kuralları tanımlanmış olmalı | §5 — öncelik zinciri, tetikleme anları, `_auto` bayrağı, geri doldurma |
| SEO verisi medya kaydıyla tutarlı yönetilebilmeli | §4.2 + §6 — çevrilebilir set deseni, tüketim noktaları |

## 11. Açık sorular (karar bekleyen)

1. **`alt` zorunluluğu nerede uygulanacak?** Yükleme anında engellemek satıcıyı
   bloke eder (dosya henüz bir ürüne bağlı değil, üretilemez). Öneri: **ürün
   yayına alınırken** kontrol — o an görsel zaten bağlı ve alt üretilebilir.
2. **Otomatik üretilen `alt` 4 dile de yazılsın mı, yoksa yalnız
   `content_default_lang`'a mı?** Öneri: yalnız varsayılan dile; çeviri
   `Listing.title` çevirisi geldiğinde türetilir — yoksa Türkçe metni İngilizce
   kolona yazmış oluruz.
3. **Geriye dönük doldurma 1.160 görselin `modified` damgasını değiştirir mi?**
   `update_modified=False` ile hayır; ama `Listing` önbelleklerinin
   geçersizleştirilmesi gerekir mi, ölçülmeli.
