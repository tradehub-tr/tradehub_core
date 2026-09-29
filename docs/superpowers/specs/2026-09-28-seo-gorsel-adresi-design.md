# SEO'lu görsel adresi (ürün adı + kısa kod) — Tasarım

**Tarih:** 2026-09-28 · **İlgili:** MOGEM-619 (retro-rename), MOGEM-582 · **Durum:** kullanıcı onayı bekliyor

## 1. Amaç

Ürün görselleri Google Görseller'de okunur adla çıksın, ama adres tahmin edilemez kalsın.

```
Bugün (taşıma sonrası):  /files/92/92570a8d8bbe3465366e62208a1dda4f.jpg
Hedef:                    /files/4-katli-siyah-plastik-ayakkabilik-92570a8d.jpg
Küçük boy:                /files/4-katli-siyah-plastik-ayakkabilik-92570a8d__w384.webp
```

**Başarı ölçütü:** Vitrin, API ve site haritası ürün görsellerini bu biçimde verir; adres 200 döner, `noindex` taşımaz; eski adresler (eski ad, kodlu çıplak adres) çalışmaya devam eder; diskteki dosyalar ve veritabanı kayıtları taşınmaz.

## 2. Kullanıcı kararları (2026-09-28)

| Karar | Seçim |
|---|---|
| Okunur kısım | Ürün adından (ürüne bağlı değilse bağlı kaydın adı: marka, kategori, satıcı) |
| Google'a açma | Evet — yalnız herkese açık ürün görselleri; diğer her şey `noindex` kalır |
| Yöntem | Disk aynı kalır, okunur ad yalnız adreste (A yolu) |
| Kod uzunluğu | 8 karakter; çakışırsa yalnız o dosya için 12, sonra 16 |

## 3. Kapsam dışı

- Diskteki dosya adlarını, dedup'ı, S3 anahtarlarını, `naming._hashed_name`'i değiştirmek.
- Retro-rename aracını değiştirmek (bugünkü koşular geçerli kalır).
- Belgeler (PDF vb.), özel dosyalar, video.

## 4. Adres biçimi

`/files/<slug>-<kod>[__<türev>].<uzantı>`

- **slug:** kaynak adın küçük harfe çevrilmesi; Türkçe sadeleştirme (ç→c, ğ→g, ı→i, İ→i, ö→o, ş→s, ü→u); `[a-z0-9]` dışı her dizi tek `-`; baş/son `-` atılır; en fazla 60 karakter, kelime ortasında kesilmez; boş kalırsa `gorsel`.
- **kod:** dosyanın içerik kodunun (`sha256[:32]`) ilk 8 hex karakteri. Aynı 8 karakterle başlayan başka bir **farklı** dosya varsa bu dosya için 12, o da çakışırsa 16 karakter.
- **türev:** manifestteki küçük boy son eki (`__w384` gibi) aynen korunur.
- **uzantı:** diskteki dosyanın uzantısı.
- Slug ile kod arasındaki ayırıcı son `-`'dir; kod her zaman `[0-9a-f]{8,16}` ile eşleşir, slug'ın sonu kodla karışmaz çünkü çözümleme sağdan yapılır.

## 5. Bileşenler

### 5.1 `media/seo_url.py` (yeni, tek sorumluluk)

- `slugify_tr(text: str) -> str` — §4 kuralları.
- `short_code(file_url: str) -> str | None` — dosyanın kısa kodu. `File` kaydındaki yeni `seo_code` alanında saklanır; yoksa hesaplanıp yazılır (çakışma kontrolüyle). İçerik-kodlu değilse (eski ad, `/files/media/`, özel) `None`.
- `seo_image_url(file_url: str, title: str | None) -> str` — okunur adres; üretilemiyorsa `file_url`'ü **aynen** döner (güvenli geri düşüş).
- `resolve(path: str) -> Resolution` — okunur adresi çözer: `(disk_yolu, beklenen_slug, durum)`; durum `ok | slug_eski | yok`.

### 5.2 Şema

- `File.seo_code` (Data, indeksli, boş olabilir). Yama alanı ekler ve mevcut içerik-kodlu dosyaları bir kez doldurur (idempotent); yeni yüklemelerde `after_insert` kancası, retro-rename'de taşıma anında atanır. GET yollarında veritabanına yazılmaz.

### 5.3 API çıktısı

Görsel adresi döndüren her yer `seo_image_url`'den geçer. Liste plan aşamasında `grep` ile kesinleşir; bilinen noktalar:

- `api/listing.py`: kart eşleyici (`imageSrc`, `images` ~3713-3771), detay (`images` ~1478-1761), top ranking (~2805-2838), benzer/öne çıkan.
- `api/seller.py` (satıcı ürünleri), `api/search.py`, `api/tailored.py`, `api/brand.py`, `api/media_public.py`.
- `api/cart.py` (`snapshot_image` + canlı ürün görseli), `api/favorites`, `api/order` (sipariş görseli).
- `api/media_manifest.py` (türev adresleri), `seo/schema_builder.py` (JSON-LD `image`), `seo/meta_builder.py` (`og:image`).
- Site haritası: ürün URL'lerine `image:image` girdileri (okunur adres).

**Sepet/favori/sipariş hatasının çözümü:** `Cart Item.snapshot_image` ve `Buyer Favorite Item.snapshot_image` bugün `usage.ORDER_SOURCES` içinde (geçmiş kaydı sayılıyor), taşıma onlara dokunmuyor; eski adı tutuyorlar. `Media URL Redirect` satırları 90 gün sonra silindiği için API o eski addan yeni dosyayı bulamaz, görseller kırılır. Çözüm:

- Bu iki alan `LIVE_SOURCES`'a taşınır; taşıma artık onları da günceller (geri alma dahil). Sepet ve favori geçmiş değil, canlı kayıttır.
- Taşıması zaten yapılmış ortamlar (lokal, alpha) için tek seferlik yama: `Media URL Redirect` satırları hâlâ dururken bu iki alandaki eski adresleri hedefleriyle değiştirir. İdempotent.
- `Order Item.image` ve makbuzlar geçmiş kaydı olarak dokunulmaz kalır. Sipariş görseli API'de ürünün güncel `primary_image`'ından üretilir; ürün silinmişse kayıttaki adres kullanılır.

### 5.4 Sunucu

- **Frappe:** yeni `page_renderer` (mevcut `MediaRedirectRenderer`'ın yanında) okunur adres desenini yakalar → `resolve` → `ok`: `X-Accel-Redirect` ile dosyayı nginx'e verdirir; `slug_eski`: güncel okunur adrese 301; `yok`: 404. Başlıklar: `Cache-Control: public, max-age=31536000, immutable`, `noindex` yok.
- **Vitrin nginx (`tradehubfront/nginx.conf.template`, `location ^~ /files/`):** okunur adres deseni için `X-Robots-Tag noindex` basılmaz; diğer `/files/` yanıtları bugünkü gibi `noindex`. Hız sınırı aynen.
- Doğrulanacak ön koşul (planın ilk adımı): alpha/prod backend nginx'inde (Press) `X-Accel-Redirect` için iç konum (`/protected/`) açık ve `/files/` altında olmayan yol Frappe'ye düşüyor (bugünkü 301'ler bunun kanıtı).

### 5.5 Vitrin önbellek hatası (ayrı ama bu işle birlikte)

`tradehubfront/src/lib/query/queryClient.ts`: TanStack persister IndexedDB'den geri yüklediği veriyi `staleTime`'a bakmadan döndürüyor (`refetchOnRestore:false`, `maxAge` 7 gün). Ürün listeleri 6 günlük veriyle çizildi (alpha'da ölçüldü). Düzeltme: `listings` anahtarları kalıcı depoya yazılmaz (yalnız bellekte, `staleTime` 60 sn); kategori, para birimi gibi yavaş değişen anahtarlar kalıcı kalır. Kesin API, planda kurulu `@tanstack/query-persist-client-core` sürümünün dokümanından doğrulanır.

## 6. Hata durumları

| Durum | Yanıt |
|---|---|
| Kod yok / dosya diskte yok | 404 |
| Kod var, slug güncel değil | 301 → güncel okunur adres |
| Aynı dosya iki üründe | Her ürün kendi slug'ıyla; ikisi de 200 (slug kontrolü: dosyanın bağlı olduğu herhangi bir kaydın slug'ı kabul) |
| `seo_image_url` üretemedi | Kayıttaki adres aynen döner (bugünkü davranış) |
| Eski ad / kodlu çıplak adres | Bugünkü gibi (301 köprüsü / 200 + noindex) |

## 7. Test

- Birim: `slugify_tr` (Türkçe harf, uzun ad, boş ad), `short_code` (8 → 12 çakışma), `resolve` (ok / slug_eski / yok), `seo_image_url` geri düşüş.
- API: kart, detay, sepet, favori, sipariş, manifest, JSON-LD çıktılarında biçim.
- Checkout (`/pages/order/checkout.html`): görselleri `cart.get_cart`'tan alıyor; 2026-09-28 alpha ölçümünde 3/3 görsel eski adla (`/files/8697464042633.jpeg`, 301 ile çalışıyor). Sepet düzeltmesinden sonra sayfada okunur adres görünmeli.
- Uçtan uca (lokal + alpha): gerçek istekle 200 + `noindex` yok, eski slug 301, yanlış kod 404; vitrinde `<img src>` okunur adres; ikinci ziyarette bayat liste yok.

## 8. Yayın sırası

1. Lokal → alpha; alpha'da Google'a açılmadan önce 1 gün gözlem.
2. Prod'da retro-rename koşusu **bu iş alpha'da doğrulandıktan sonra**; böylece prod adresleri tek geçişte son hâline gelir.
3. Site haritası prod'a çıkınca Google Search Console'dan yeniden gönderim (kullanıcı).
