# Görsel önizleme ve odak noktası — Tasarım

**Tarih:** 2026-10-01 · **Durum:** kullanıcı onayı bekliyor (görsel tasarım onaylandı) · **İlgili:** G-16 medya, ürün görseli kare (2026-09-29), mağaza görselleri (2026-09-30)
**Onaylanan görsel tasarım:** https://claude.ai/artifact/1a96mpSSvALP4kTCt8BDUH (1 numaralı pano esas)

## 1. Amaç

Satıcı bir görsel yüklediğinde, o görselin sitede **gerçekten görüneceği her yerde** nasıl duracağını tek pencerede görsün. Kesilen bir alan varsa odak noktasını seçip düzeltsin.

**Başarı ölçütü:**
- Satıcı görseli yükleyince ya da "Nerelerde görünecek?" düğmesine basınca geniş pencere açılır.
- Pencerede görselin vitrindeki her yeri, gerçek oranında ve sayfa bağlamıyla görünür.
- Odak noktası değişince önizlemeler anında güncellenir. Kaydedilen odak noktası vitrinde kırpılan yerlerde aynen uygulanır: önizlemede görülen, sitede görülenle aynıdır.

## 2. Kullanıcı kararları (2026-10-01)

| Karar | Seçim |
|---|---|
| Kırpılmış görselin kullanımı | Şimdilik yalnız ekran (önizleme ve odak noktası). Paylaşım ve reklam görselleri kapsam dışı. |
| Yaklaşım | A: mevcut odak altyapısı (Media Crop Intent, suggest_focal) yeniden kullanılır, yeni pencere bunun üstüne kurulur |
| Pencere | Neredeyse tam ekran; solda yer listesi, ortada gerçek sayfa bağlamında gösterim, sağda odak noktası |
| Açılış | Tek görsel yüklenince otomatik açılır (satıcı kapatabilir); her görselin altında kalıcı "Nerelerde görünecek?" düğmesi |
| Erişilebilirlik | WCAG 2.2 AAA |
| Hareket | Hafif, hızlı geçişler; "hareketi azalt" açıksa kapalı |

## 3. Mevcut durum (2026-10-01 incelemesi)

- Backend: `Media Crop Intent` doctype'ında `focal_x` / `focal_y` var. `api/media_crop.py`: `get_intent` (432), `save_intent` (452), `suggest_focal` (545). `smartcrop.py` kalibre edilmemiş bir yer tutucu.
- Panel: `CropStudioModal.vue` + `useCropStudio.js` (788 satır) odak sürüklemeyi destekliyor. `ListingFormView.vue` "Kırp" düğmesiyle açılıyor. `product.image` "kırpılmaz" tanımlı olduğu için stüdyoda oran çıkmıyor. Yüklemeden sonra otomatik açılmıyor.
- Vitrin: hiçbir yerde `object-position` / odak kullanılmıyor. Kırpılan yerler hep ortadan kırpılıyor (`object-fit: cover`).
- Yer ölçüleri: `media/pipeline/simulator/placements.json` 5 sayfa × bölgenin gerçek CSS ölçülerini tutuyor; `delivery/sizes.py --emit-ts` vitrin tablosunu buradan üretiyor. Mağaza sayfaları için ölçüler 2026-09-30 mağaza görselleri işinde ayrıca `storeImage.ts`'e yazıldı.

## 4. Bileşenler

### 4.1 Yer kaydı (tek kaynak)

Görselin vitrinde göründüğü her yer tek bir kayıtta tanımlanır: `placements.json` genişletilir.

- Her slot için yerler listesi: `{key, label_i18n, device: desktop|mobile, ratio, css_size, fit: cover|contain, context: <bağlam şablonu adı>}`.
- Mağaza sayfası bölgeleri (başlık, tanıtım kartı, vitrin slaytı, galeri, liste küçük resmi) ve ürün bölgeleri (kart, ürün sayfası ana ve küçük resim, sepet, benzer ürünler, favoriler) eklenir. Ölçüler `derived_from` ile CSS satırına bağlanır.
- `sizes.py` yeni bir çıktı üretir: `--emit-placements` → `admin-panel/frontend/src/lib/media/vendor/placements.js`. Vitrin `storeImage.ts` aynı kaynaktan beslenir; elle yazılmış ikinci kopya kalmaz.

### 4.2 Önizleme penceresi (admin panel)

Yeni bileşen: `components/media/preview/ImagePlacementModal.vue`.

- **Yerleşim (bilgisayar, ≥1024 px):** tam ekran diyalog (16 px kenar), üç sütun.
  - **Sol (250 px):** yer listesi. Her satır: küçük resim, ad, oran · ölçü, durum rozeti ("Tamamı görünüyor" / "%41 görünüyor"). Seçili satır 2 px koyu çerçeve.
  - **Orta:** seçili yer, gerçek sayfa bağlamında. Bilgisayarda tarayıcı çerçevesi + sayfa iskeleti (ölçek etiketi: "Sayfa 1200 px · burada %65"). Telefonda 390 px gerçek boyutta telefon çerçevesi. Üstte Bilgisayar / Telefon seçici.
  - **Sağ (330 px):** odak noktası. Görselin tamamı + seçili yerin kesikli çerçevesi + sürüklenebilir işaret (44 px dokunma alanı); Yatay / Dikey sayı kutuları; "Otomatik öner", "Ortaya al"; ekran okuyucu bildirimi; "Yeni görsel yüklediğimde otomatik açılsın" kutusu; Vazgeç / Kaydet.
- **Telefon (<1024 px):** tam ekran sayfa. Üstte yer seçici yatay çipler, ortada bağlam önizlemesi, altta açılır kapanır odak paneli, Kaydet / Vazgeç sabit alt çubukta.
- **Bağlam şablonları:** her `context` adı için küçük, statik bir Vue bileşeni (`StoreHeaderContext`, `StoreCardContext`, `StoreVitrinContext`, `GalleryContext`, `ListThumbContext`, `ProductCardContext`, `ProductPageContext`, `CartContext`, `RelatedContext`, `FavoritesContext`). Gerçek veri: satıcının mağaza adı, ürün adı, fiyatı; diğer bloklar gri iskelet.
- **Kırpma hesabı:** görünen kısım = `min(1, yer oranı / görsel oranı)` (yatay) ya da dikey eşdeğeri; çerçeve konumu `(1 − görünen) × odak`. Bu, CSS `object-position: X% Y%` davranışının aynısıdır; vitrin de aynı değeri kullanır.
- **Ürün görselleri:** kare ve `contain` gösterildiği için hepsi "Tamamı görünüyor". Pencerenin solunda ayrıca "Kareye tamamlandı" özeti (orijinal ölçü → kare ölçü, dosya boyutu) gösterilir.

### 4.3 Odak noktası mantığı

Yeni küçük composable: `composables/useFocalPoint.js` (≈150 satır).

- `get_intent` ile mevcut odak okunur; yoksa `suggest_focal` önerisi uygulanır ve "Otomatik öneri uygulandı" bildirilir.
- Kaydet → `save_intent` (yalnız `focal_x`, `focal_y`; mevcut alanlar korunur). ETag / `if_none_match` mevcut desenle.
- `useCropStudio.js`'e dokunulmaz; odak hesabındaki ortak saf fonksiyonlar (`clampFocal`, `visibleFraction`, `frameRect`) `lib/media/crop/geometry.js`'e taşınır ve iki taraf da onu kullanır.
- Otomatik öneri kalitesi: `suggest_focal` bugün kenar enerjisine bakıyor. Bu iş kapsamında ölçülür (gerçek mağaza banner'larında öneri ile elle seçilenin farkı); iyileştirme ayrı iş.

### 4.4 Giriş noktaları

- `ListingFormView.vue`: ana görsel ve galeri satırlarında "Kırp" düğmesi yerine **"Nerelerde görünecek?"** (sarı, birincil). Kesilen yer varsa yanında rozet: "2 yerde kenarlar kesiliyor".
- Mağaza ayarları: logo, banner, vitrin slaytı, galeri yükleme alanlarına aynı düğme.
- Otomatik açılış: tek dosya yüklemesi tamamlanınca pencere açılır. Toplu yüklemede açılmaz. Tercih kullanıcıya özel, sunucuda saklanır: Frappe kullanıcı varsayılanı `th_media_preview_autoopen` (`frappe.defaults.set_user_default`), varsayılan değer açık. Tarayıcıya özel değildir; satıcı başka cihazda da aynı tercihi görür.
- Mevcut `CropStudioModal` yalnız gerçekten kırpma isteyen slotlarda (video kapak karesi vb.) kalır.

### 4.5 Vitrin

- Manifest / `*_media` yanıtlarına `focal: {x, y}` eklenir (yalnız odak kaydı olan dosyalarda).
- `cover` ile gösterilen her mağaza görseli yerinde `object-position: X% Y%` uygulanır: StoreHeader, CompanyInfo, Gallery, CategoryProductListing, section-registry hero, vitrin slaytları.
- Ürün görselleri `contain` kaldığı için değişmez.

## 5. Erişilebilirlik (WCAG 2.2 AAA)

| Kriter | Uygulama |
|---|---|
| 1.4.6 Kontrast (gelişmiş) | Metin ≥ 7:1: ana #1d1c19, ikincil #3a3833 / #4e4c45. Panelin #6d6a61 grisi bu pencerede kullanılmaz. Sarı (#f5b800) yalnız zemin, üstünde #1a1a1a. |
| 1.4.11 Metin dışı kontrast | Çerçeveler, kenarlıklar, odak işareti ≥ 3:1. Kesikli çerçeve beyaz + koyu gölge (her zeminde görünür). |
| 1.4.1 Renk kullanımı | Rozetler yazı + simge taşır; renk tek başına anlam taşımaz. |
| 2.1.1 / 2.1.3 Klavye | Her şey klavyeyle: sekmeler, yer listesi, odak işareti (ok tuşları %1, Shift + ok %10, Home = ortala). |
| 2.4.3 Odak sırası, 2.4.11/12 odak görünür ve örtülmez | Doğal sıra: başlık → cihaz → yer listesi → önizleme → odak → kaydet. Sabit alt çubuk odaklı öğeyi örtmez (scroll-padding). |
| 2.4.13 Odak görünümü | 3 px #1a1a1a çerçeve, 2 px boşluk. |
| 2.5.5 Hedef boyutu (gelişmiş) | Tüm hedefler ≥ 44 × 44 px; ana düğmeler 48 px. |
| 2.5.7 Sürükleme hareketleri | Sürüklemeye alternatif: tıklayarak / dokunarak seçme, sayı kutuları, ok tuşları. |
| 2.3.3 Etkileşimden animasyon | `prefers-reduced-motion: reduce` → bütün geçişler kapalı. |
| 4.1.2 / 4.1.3 Ad, rol, değer; durum mesajları | `role="dialog"` + `aria-modal` + `aria-labelledby`; yer listesi `aria-current`; cihaz seçici `aria-pressed`; değişiklikler `role="status"` ile bildirilir. |
| Diyalog davranışı | Odak tuzağı, Esc ile kapatma (kaydedilmemiş değişiklik varsa onay), kapanınca odak açan düğmeye döner. |
| 3.3.x Yardım | Kısa yönlendirme metni ve klavye ipucu pencere içinde sabit. |

## 6. Hareket

- Odak değişiminde `object-position` 260 ms, işaret ve çerçeve 220 ms, `cubic-bezier(.2,.8,.2,1)`.
- Yer değişiminde orta alan 220 ms ölçek + saydamlık girişi.
- Pencere açılışı 200 ms; kapanış 160 ms.
- Yalnız `transform`, `opacity`, `object-position`. Yerleşim kaydıran animasyon yok.

## 7. Hata durumları

| Durum | Davranış |
|---|---|
| Görsel henüz işleniyor (türev yok) | Önizleme asıl dosyayla çizilir; üstte "Görsel hazırlanıyor" bilgisi |
| `suggest_focal` başarısız | Odak ortada başlar; bildirim yok |
| Kaydetme çakışması (ETag) | "Bu görsel başka bir sekmede değiştirildi" + yeniden yükle |
| Odak kaydı yok | Vitrin ortadan kırpar (bugünkü davranış) |
| Ağ hatası | Pencere açık kalır, Kaydet tekrar denenebilir; değişiklik kaybolmaz |

## 8. Kapsam dışı

- Paylaşım / reklam görselleri (1.91:1, 4:5, 9:16), Google Alışveriş.
- Görseli fiziksel olarak kırpıp yeni dosya üretmek.
- `suggest_focal`'ın yapay zekâ ile iyileştirilmesi.
- Ürün görsellerinde `contain` → `cover` geçişi.

## 9. Test

- **Birim (panel):** `visibleFraction`, `frameRect`, `clampFocal`; yer kaydının her slot için en az bir yer döndürmesi; dört dilde i18n anahtarları.
- **Bileşen (panel):** pencere açılır / kapanır, odak tuzağı, Esc, ok tuşları, `aria-*` öznitelikleri, hareket azaltma; otomatik açılma tek dosyada evet, toplu yüklemede hayır.
- **Backend:** manifest / `*_media` `focal` alanı; `save_intent` yalnız odak alanlarını değiştirir.
- **Vitrin:** odak kaydı olan mağaza banner'ında `object-position` doğru; kaydı olmayanda yok.
- **Uçtan uca (lokal):** Özgen Plastik banner'ı: odak %78 / %45 kaydedilir → telefonda mağaza başlığında yazı görünür (ekran görüntüsü karşılaştırması önizleme = vitrin).
- **Erişilebilirlik:** axe ile 0 ihlal; klavyeyle baştan sona akış; kontrast ölçümü.

## 10. Yayın sırası

1. Lokal: kod, testler, tarayıcı kontrolü.
2. Alpha: deploy, satıcı akışı denemesi.
3. Prod: ayrı onayla.
