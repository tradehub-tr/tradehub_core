# Medya SEO Alanları ve Üretim Kuralları — Ar-Ge

**Linear:** TUR-135 · **Faz:** 3 · **Etiket:** `arge`, `SM`
**Bağımlı olduğu işler:** TUR-133 (kategorizasyon), TUR-134 (arama/filtreleme),
TUR-132 (EXIF/mime), TUR-122 (WP assimilasyon) — **dördü de Backlog**.
**Blokladığı:** TUR-136 (Done).

> Bu bir **ar-ge** belgesidir: karar üretir, kod üretmez. Uygulama sırası §9'da.
> Ölçümler 18 Ağustos 2026, prod'dan restore edilmiş local veritabanında alındı.

---

## 0. Revizyon kaydı — 21 Ağustos 2026

**Üst belge:** "Media & File Management — SEO/Marketing Feature Set" (PM,
21 Ağu 2026; 8 motorlu medya alt sistemi mimarisi). **Bu üst belge öncelikli**;
aşağıdaki beş karar onun lehine değiştirildi. Eski gerekçeler silinmedi —
ne düşünülmüştü, neden döndü, ikisi de okunabilsin diye ~~üstü çizili~~ bırakıldı.

| # | Konu | 19 Ağu kararı | 21 Ağu kararı | Gerekçe |
|:-:|---|---|---|---|
| R1 | `caption` | Eklenmeyecek | **Eklenir**, çevrilebilir, kullanım başına ezilebilir | Caption sayfada **görünür** metindir (`<figcaption>`, ImageObject.caption); `description` panel içidir. İkisi aynı iş değil |
| R2 | AI ile alt üretimi | Kapsam dışı | **AI önerir, insan onaylar.** `alt_source` durumu şimdi açılır, AI servisi sonra bağlanır | Üst belge: "ALT otomatik yayınlanmamalı; ai_generated / human_approved / manually_edited tutulmalı". Kural tabanlı zincir (§5.1) AI gelene kadar tek üretici olarak kalır |
| R3 | SEO dosya adı / `slug` | Eklenmeyecek | **Metadata alanı** olarak eklenir (`seo_filename`, `slug`); **diskteki hash ad DEĞİŞMEZ** | Üst belge de ayrımı kuruyor: "sabit asset ID ≠ delivery URL, metadata değişti diye dosya URL'si değişmemeli". Güvenlik kararı (TUR-141/130) korunur; alan ileride medya landing/watch page'de kullanılır |
| R4 | `canonical` | Eklenmeyecek | Alan açılır, **medya sayfası gelene kadar boş** | Üst belge "raw file ≠ indexable landing/watch page" ayrımını istiyor; o sayfa geldiğinde canonical onun adresidir |
| R5 | EXIF'ten veri | Siliniyor, okunmaz | **Politika:** GPS/cihaz public dosyadan gider, çekim tarihi/kamera/telif **DB'de tutulur** | Üst belge "metadata policy". **Bu TUR-132'nin kapsamıdır**, burada yalnız sınırı çizilir |

Ek olarak üst belgeden gelen **yeni** kapsam (19 Ağu'da hiç yoktu): kullanım
başına metadata ezme (§4.3), lisans/telif alan seti (§4.4), indexability
politikası (§6.1), render ipuçları (§6.2), SEO audit + skor (§6.3),
video SEO (§6.4). Ar-ge sonuçları 1-6 ve ölçümler geçerliliğini koruyor.

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

**Karar (R3 ile güncellendi):** Diskteki ad ve `file_url` **hash kalır** —
güvenlik kararı korunur, slug'lu servis rotası reddi (§8) geçerli. Ama dosya
adı sinyali tamamen terk edilmez: `seo_filename` ve `slug` **metadata alanı**
olarak tutulur. Bugün iki yerde işe yarar — (a) `Content-Disposition` ile
indirme adı, (b) denetimde "poor filename" kuralı (`IMG_4821`, `Ekran
Görüntüsü` → uyarı). Medya landing/watch page açıldığında o sayfanın adresi
bu slug'dan üretilir; dosyanın kendisi yerinden oynamaz.

## 4. Alan seti

### 4.1 Karar tablosu

| Alan | Zorunlu | Üretim | Çok dil | Kaynak / kural |
|---|:-:|---|:-:|---|
| `alt` | **Evet** (görselde) | **Otomatik**, elle ezilebilir | ✅ | §5.1; kaynağı `alt_source` ile izlenir |
| `alt_source` | — | Sistem | — | `rule` / `ai` / `human` / `edited` — **R2**. Eski `_auto` Check yerine; iki durum dört oldu çünkü "AI önerdi, insan onayladı" ile "insan sıfırdan yazdı" denetimde ayrı okunmalı |
| `title` | Hayır | Otomatik | ✅ | Görsel adı → `slugify_tr` tersi (tire→boşluk, ilk harf büyük) |
| `caption` | Hayır | Elle; AI önerisi sonra | ✅ | **R1 — eklendi.** Sayfada görünür kısa metin (`<figcaption>`, `ImageObject.caption`, görsel sitemap `image:caption`). ~~Eklenmeyecek — description ile aynı iş~~ |
| `description` | Hayır | **Elle** | — | Panel içi; dış yüzde basılmaz. Otomatik üretimi değersiz: tekrarlayan açıklama gürültüdür |
| `tags` | Hayır | Otomatik öneri + elle | — | Kategori ağacından (TUR-133 gelince); kaynağı `manual` / `system` / `ai` ayrı tutulur (üst belge §29) |
| `seo_filename` | Hayır | Otomatik (`slugify_tr(alt)`) | — | **R3 — metadata.** Disk adı DEĞİŞMEZ (§3). İndirme adı + "poor filename" denetimi |
| `slug` | Hayır | Otomatik | — | **R3 — metadata.** Medya landing page açılana kadar yalnız saklanır. ~~Eklenmeyecek — sayfası yok~~ |
| `canonical` | Hayır | — | — | **R4.** Medya sayfası gelene kadar **boş**; o gün o sayfanın adresi. ~~Eklenmeyecek~~ |

**Ar-ge sonucu 4 (güncellendi):** `slug` ve `canonical` bugün hiçbir yerde
çözülmüyor — 19 Ağu tespiti doğru. Değişen şey kapsam: üst belge medya için
**kendi sayfasını** (landing/watch page) öngörüyor; alanlar o gün için şimdiden
açılıyor ki şema ikinci kez değişmesin. Boş alan ucuz, geç gelen kolon pahalı.

### 4.2 Çok dillilik kararı

`alt` ve `title` **çevrilebilir alanlar setine katılır** — `Listing.title` ile
aynı desen (`_tr/_en/_ar/_ru` + `content_default_lang`).

Gerekçe: vitrin 4 dilli ve `alt` doğrudan kullanıcıya okunan içeriktir (ekran
okuyucu onu sesli okur). Tek kolon tutmak, Türkçe alt metnini İngilizce sayfada
göstermek demekti.

Maliyet dürüstçe: 2 alan × 4 dil = 8 kolon. Ama `CONTENT_TRANSLATABLE_FIELDS`
zaten kolon üretimini, senkronu ve okumayı tek yerden yönetiyor; ek karmaşıklık
sözlüğe iki satır eklemekten ibarettir.

`caption` da çevrilebilir sete katılır (R1) — aynı gerekçe, sayfada basılıyor.
`description` ve `tags` **tek dil kalır**: ikisi de dış yüzde render edilmiyor
(§6), yalnız panel içi arama/filtreleme besliyor.

### 4.3 Asset metadata ≠ kullanım metadata'sı (YENİ — üst belge §3)

Aynı görsel üç sayfada üç farklı bağlamda durabilir:

```
/urun/bmw-x5            → alt: "BMW X5 ön görünüm"
/blog/bmw-x5-inceleme   → alt: "İnceleme: BMW X5 2026 yüz yenileme"
/kampanya/bmw-x5        → alt: "Ağustos BMW X5 kampanya görseli"
```

Tek global `alt` bunu karşılayamaz. Model iki katman:

| Katman | Nerede | Ne tutar |
|---|---|---|
| **Asset varsayılanı** | `File.th_media_*` | `alt`, `title`, `caption` (4 dil), `alt_source` |
| **Kullanım ezmesi** | `Media Usage Override` (yeni child/ilişki kaydı) | `(file_url, doctype, name, field)` anahtarıyla `alt_override`, `title_override`, `caption_override` (4 dil) |

Okuma kuralı: `usage.alt_override || asset.alt`. Yazma kuralı: ezme yalnız o
kullanım bağlamının sahibi tarafından (ürün sahibi satıcı, blog yazarı);
asset varsayılanı dosya sahibi tarafından.

Bunun için **yeni tablo gerekir** — CLAUDE.md §4 "DocType bloat" kuralına
karşı gerekçe: anahtar dörtlü, ilişki çoktan-çoğa, mevcut `File` kaydına
sığmaz; `usage.py`'nin 16 kaynak çifti zaten bu anahtarı üretiyor, tablo onun
yazma yüzü olur. **Bu, üst belgenin "unknown unknown" dediği altı maddeden
biri ve şemayı etkileyen tek SEO kararı — Dilim 1'in ilk işi.**

### 4.4 Lisans ve telif alanları (YENİ — üst belge §3, §7)

Google görsel aramasında **lisans rozeti** ve "Bu görseli lisansla" bağlantısı
şu beş alanı okur; `ImageObject`'e doğrudan bağlanır:

| Alan | ImageObject | Üretim |
|---|---|---|
| `creator` | `creator.name` | Varsayılan: yükleyen mağaza adı |
| `credit_text` | `creditText` | Varsayılan: mağaza adı |
| `copyright_notice` | `copyrightNotice` | Varsayılan: `© <yıl> <mağaza>` |
| `license_url` | `license` | Boş; satıcı/yönetici seçer (pazaryeri şartları sayfası varsayılan adaydır) |
| `acquire_license_url` | `acquireLicensePage` | Boş; mağaza iletişim sayfası aday |

Ek yaşam döngüsü alanları (üst belge §7 "rights lifecycle"): `usage_rights`
(serbest metin), `rights_expires_on` (tarih) — süresi dolan görsel
indexability'de `noindex`'e düşer (§6.1) ve denetimde "expired asset still
published" kuralına takılır (§6.3). Bu alanlar **tek dil**.

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
| **Bir kayda eklendiğinde** (`attached_to` dolduğunda) | Kural zinciri üretir → `alt_source = rule` |
| Bağlı kaydın başlığı değiştiğinde | **Yalnız `alt_source ∈ {rule, ai}`** ise yenilenir |
| Satıcı elle yazdığında | `alt_source = human` (sıfırdan) ya da `edited` (öneriyi düzeltti); bir daha otomatik ezilmez |

Bunun için `th_media_alt_source` (Select: `rule / ai / human / edited`) alanı
gerekir. ~~`th_media_alt_auto` (Check)~~ — R2 ile dört duruma çıktı: "AI
önerdi, insan onayladı" ile "insan sıfırdan yazdı" denetimde aynı görünmemeli.
Bu alan olmadan "elle yazılanı ezme" kuralı uygulanamaz — ölçülemeyen kural,
uygulanmayan kuraldır.

### 5.2a AI önerisi akışı (R2 — şema şimdi, servis sonra)

```
AI servisi öneri üretir  →  th_media_alt_ai (öneri, AYRI alan, yayınlanmaz)
                         →  panelde "Öneriyi kabul et / düzenle / reddet"
   kabul     → alt = öneri,            alt_source = ai
   düzenle   → alt = düzenlenmiş metin, alt_source = edited
   reddet    → öneri silinir, kural zinciri devrede kalır
```

**Öneri asla doğrudan `alt`'a yazılmaz.** Erişilebilirlik alt'ı (ekran okuyucu)
ile SEO açıklaması aynı şey değil; yanlış AI metni yalan söyler, boş alt
"dekoratif" der — boş, yanlıştan iyidir (§5.1 ilkesi burada da geçerli).

Hangi AI servisi, hangi maliyet, veri nereye gider — **bu belgenin kararı
değil**, PM/ops masası. Bu belge yalnız şemayı ve onay akışını sabitler;
servis takılınca tek yapılacak `th_media_alt_ai` kolonunu doldurmaktır.

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
| JSON-LD | `"image": ["url"]` düz dizi | `ImageObject` — `contentUrl`, `url`, `name`, `caption`, `description`, `width`, `height`, `encodingFormat`, `dateCreated`, `datePublished` **+ lisans beşlisi** (`creator`, `creditText`, `copyrightNotice`, `license`, `acquireLicensePage`, §4.4) |
| Görsel sitemap | Yok | `xmlns:image` namespace'i + sayfa başına `<image:image>` girdileri; **yalnız `indexable` varlıklar** (§6.1) |
| `Listing` API çıktısı | Yalnız URL | `{url, alt, caption, width, height, license}` nesnesi — kullanım ezmesi uygulanmış (§4.3) |
| Robots meta | Sayfa düzeyi | Varlık durumuna göre `max-image-preview` (§6.1) |

**Ar-ge sonucu 5:** İşin ağırlık merkezi medya modülünde değil, **`seo/`
modülünde ve `api/listing.py`'de**. TUR-135 medya işi gibi görünüyor ama
teslimatının çoğu SEO tarafında.

### 6.1 Indexability politikası (YENİ — üst belge §9)

Varlığın yaşam döngüsü durumu (`th_media_state`, TUR-138) ve erişim seviyesi
(`is_private`, TUR-126) **tek bir indexability kararına** indirgenir; sitemap,
robots meta ve structured data bu karardan beslenir:

| Durum | Indexability | Sitemap | ImageObject |
|---|---|---|---|
| Active + public + kullanımda | `index` | ✅ | ✅ |
| Active + public + kullanılmıyor (orphan) | `noindex` | ❌ | — |
| Private | erişim 404 (TUR-126) | ❌ | ❌ |
| Archived / Trashed / Deleted | `noindex` | ❌ | ❌ |
| `rights_expires_on` geçmiş | `noindex` | ❌ | ❌ + denetim uyarısı |
| Karantina / tarama bekliyor (TUR-125) | fiziksel olarak servis dışı | ❌ | ❌ |

**İlke (üst belge §9):** private varlık `robots.txt` ile "gizlenmez" — gerçek
yetkilendirme kullanılır. TUR-126'nın 404 kararı tam bu ilkenin uygulaması.
`noindex` yalnız *erişilebilir ama aranmaması gereken* varlık içindir.

### 6.2 Render ipuçları (YENİ — üst belge §12)

Listing API'si görsel nesnesiyle birlikte **konum bilgisi** verir, vitrin
markup'ı ona göre kurar:

| Konum | `loading` | `fetchpriority` | `decoding` |
|---|---|---|---|
| Ürün sayfası ilk görsel (LCP) | `eager` | `high` | `async` |
| Galeri 2..n | `lazy` | — | `async` |
| Liste kartı (ilk 4) | `eager` | — | `async` |
| Liste kartı (5+) | `lazy` | — | `async` |

`width`/`height` **her zaman** gerçek değer (`th_media_width/height`) — §7.1
madde 4'teki CLS hatası böyle kapanır. `srcset`/`sizes` ve `<picture>` üretimi
türev dosyalara bağlı (TUR-127/128/297) — burada sözleşme kurulur, türev
gelince doldurulur.

### 6.3 SEO denetimi ve skor (YENİ — üst belge §24-25)

Alan göstermek yetmez, **aktif tarama** gerekir. İlk kural seti (hepsi bugünkü
alanlarla ölçülebilir):

| Kural | Kaynak |
|---|---|
| Alt boş / eksik | `th_media_alt` |
| Alt şüpheli (ham ürün başlığı kopyası, 100+ karakter, `(SADECE OBJELER)` gibi parantez gürültüsü) | §7.1 madde 1 |
| Alt anahtar kelime yığını (aynı kelime 3+) | metin analizi |
| Kötü dosya adı (`IMG_`, `Ekran Görüntüsü`, `WhatsApp Image`) | `file_name`; ölçüm: 9 + 271 boşluklu |
| Boyut yanlış / eksik (`width`/`height` ≠ gerçek) | §7.1 madde 4 |
| Aşırı çözünürlük (30 MP+ senkron yol) | [[medya-cozunurluk-olcumu]] ölçümü |
| Format fırsatı (PNG/JPEG, WebP'ye dönmemiş) | `th_optimized_at`; ölçüm 342 PNG |
| Lisans eksik | §4.4 |
| Sahipsiz varlık (orphan, hiçbir yerde kullanılmıyor) | `usage.verdict = unused` |
| Private varlık public'te açıkta | TUR-126 `exposed_sensitive` |
| Süresi dolmuş ama yayında | `rights_expires_on` |
| Structured data üretilemiyor (zorunlu alan eksik) | ImageObject kurucusu |

**Skor:** tek sayı yerine alt kırılım — Metadata · Erişilebilirlik · Yapısal
veri · Performans · Haklar · Yerelleştirme · Teknik sağlık. Her kırılım 0-100,
toplam ağırlıklı ortalama. Panelde varlık başına ve mağaza başına gösterilir.
Ağırlıklar bu belgenin kararı değil; ilk sürümde eşit, ölçümle ayarlanır.

### 6.4 Video SEO (YENİ — üst belge §6; ayrı dilim)

WebM transcode altyapısı (TUR-296/297) hazır; üstüne SEO katmanı:
`VideoObject` (`name`, `description`, `thumbnailUrl`, `uploadDate`, `duration`,
`contentUrl`, `embedUrl`, `expires`, `regionsAllowed`), **poster üretimi**
(bugün yok — `ffmpeg` tek kare), video sitemap (`xmlns:video`), transcript/
WebVTT alanları (AI servisi gelene kadar elle). Watch page ve `SeekToAction`
medya landing page'e bağlı (R3/R4), o dilimde. Görsel dilimleri bitmeden
başlanmaz.

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

**Hâlâ reddedilenler:**

- **Slug'lu servis rotası** (`/i/kirmizi-canta-<hash>.jpg`): dosya adı sinyalini
  geri kazandırırdı. Reddedildi — nginx'in doğrudan servisini Python'a taşır
  (her görsel isteği uygulama sunucusuna düşer), `naming.py` sözleşmesini
  karmaşıklaştırır ve kazanç düşük. **R3 bunu değiştirmiyor:** slug metadata
  olarak tutulur, servis adresi hash kalır.
- **Eski dosyaların yeniden adlandırılması**: 2.166 tahmin-edilebilir ad, ~2.400
  referans + 301 gerektirir; TUR-128 format dönüşümüyle **tek migration**
  olarak planlanmalı (MEDYA-DEDUP-STRATEJISI.md §7.2).
- **"GEO skoru / LLMO anahtar kelimesi" gibi yapay alanlar**: üst belge §16 de
  aynı şeyi söylüyor — AI arama için yeni metadata icat etme, mevcut varlığı
  makine-okunur yap (structured data, entity ilişkisi, lisans, dil, tarih).

**21 Ağu'da geri alınanlar** (gerekçe §0 tablosunda):

- ~~**`caption` ayrı alanı**: `description` ile örtüşüyor.~~ → R1, eklendi.
- ~~**Medyaya `slug`/`canonical`**: medya kaydının sayfası yok.~~ → R3/R4,
  metadata olarak eklendi; sayfa gelince anlam kazanır.
- ~~**EXIF'ten otomatik `alt`**: TUR-132 EXIF'i siliyor.~~ → R5, "sil" yerine
  politika; hangi alanın DB'de kalacağı TUR-132'de kararlaştırılır. Alt üretimi
  yine kural zincirinden — EXIF'te alt metni olmaz, en fazla çekim tarihi/kamera.
- ~~**Alt metnini yapay zekâyla üretme**: kapsam dışı.~~ → R2, **öneri + insan
  onayı** modeliyle kapsama girdi; kural tabanlı zincir varsayılan üretici kalır.

## 9. Uygulama sırası ve bağımlılıklar

Bağımlılıkların **hepsi beklenmek zorunda değil**:

Üç dilim; sıra **şemayı etkileyen önce, dış yüzey sonra, ölçüm en son** —
şema bir kez açılır, bir daha dokunulmaz.

**Dilim 1 — Şema** (dış bağımlılık yok)

| Adım | Bağımlı mı | Yapılabilir mi |
|---|---|---|
| 1a. `Media Usage Override` tablosu (§4.3) | — | **Şimdi** — en kritik, ilk iş |
| 1b. `alt`/`title`/`caption` çevrilebilir sete (§4.2) + `alt_source` + `alt_ai` (§5.2) | — | **Şimdi** |
| 1c. Lisans/hak alanları (§4.4) + `seo_filename`/`slug`/`canonical` (R3/R4) | — | **Şimdi** |

**Dilim 2 — Dış yüzey**

| Adım | Bağımlı mı | Yapılabilir mi |
|---|---|---|
| 2a. `alt` üretimi (Listing/kategori/mağaza zinciri, §5.1) | 1b | **Şimdi** (kategori dalı TUR-133'te genişler) |
| 2b. Listing API görsel nesnesi — ezme uygulanmış, lisanslı, konum ipuçlu (§6.2) | 1a-c | **Şimdi** |
| 2c. `ImageObject` (lisans beşlisiyle) + `og:image:*` + görsel sitemap | 1c, 6.1 | **Şimdi** |
| 2d. Indexability kararı (§6.1) — sitemap/robots buradan | — | **Şimdi** |
| 2e. Vitrinin `alt`/`width`/`height`/`fetchpriority`'yi medyadan basması | 2b | **Şimdi** |
| 2f. Geriye dönük doldurma (1.160 ürün görseli, parça parça) | 2a | **Şimdi** |

**Dilim 3 — Denetim ve skor**

| Adım | Bağımlı mı | Yapılabilir mi |
|---|---|---|
| 3a. 12 denetim kuralı (§6.3) + panelde varlık/mağaza görünümü | 1-2 | **Şimdi** |
| 3b. Alt kırılımlı skor | 3a | **Şimdi** |

**Bekleyenler**

| Adım | Bağımlı |
|---|---|
| `tags` otomatik önerisi | **TUR-133** |
| Medya aramasında SEO alanları | **TUR-134** |
| WP'den gelen alt/caption taşınması | **TUR-122** |
| `srcset`/`<picture>` gerçek türevlerle | **TUR-127/128/297** |
| AI öneri servisinin bağlanması | **PM/ops kararı** (§5.2a) |
| Video SEO (§6.4) | Dilim 1-3 bitince, ayrı dilim |
| Medya landing/watch page (slug/canonical'ın tüketicisi) | Ayrı issue; üst belge §10 |

**Ar-ge sonucu 6 (güncellendi):** Üç dilimin tamamı dış bağımlılıksız
yapılabilir; TUR-135'in dört kabul kriteri Dilim 1+2 ile, üst belgenin
Motor 4'ü (SEO & Discoverability) ~%70 oranında Dilim 1-3 ile karşılanır.

## 10. Kabul kriterleri karşılığı

| Kriter | Karşılığı |
|---|---|
| SEO alan seti net belirlenmiş olmalı | §4.1 (alan seti) + §4.3 (kullanım ezmesi) + §4.4 (lisans/hak) — eklenen, ertelenen ve gerekçeleri |
| Zorunlu ve opsiyonel alanlar ayrılmış olmalı | §4.1 — yalnız `alt` zorunlu, o da görselde |
| Otomatik üretim kuralları tanımlanmış olmalı | §5 — öncelik zinciri, tetikleme anları, `alt_source` durumu, AI öneri akışı, geri doldurma |
| SEO verisi medya kaydıyla tutarlı yönetilebilmeli | §4.2 + §6 — çevrilebilir set deseni, indexability, tüketim noktaları, denetim |

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
4. **Kullanım ezmesini kim yazabilir?** (§4.3) Öneri: ürün görselinde ürünün
   sahibi satıcı; asset varsayılanında dosya sahibi. Ortak sahipli dosyada
   (aynı görsel 5 mağazada) varsayılanı kim değiştirir — TUR-298'in
   `owner_count` kapısı burada da uygulanmalı mı?
5. **Lisans varsayılanı ne olsun?** (§4.4) Pazaryeri kullanım şartları sayfası
   `license` için uygun mu, yoksa boş mu kalsın? Yanlış lisans beyanı hukuki
   sonuç doğurur — **boş, yanlıştan iyidir** ilkesi burada da geçerli; karar
   hukuk/PM.
6. **Skor ağırlıkları** (§6.3) — ilk sürümde eşit; hangi kırılım daha ağır
   basacak, ölçümle.
7. **AI servisi** (§5.2a) — hangisi, maliyet, veri gizliliği (ürün görselleri
   dışarı çıkıyor mu). Şema hazır, karar PM/ops.
