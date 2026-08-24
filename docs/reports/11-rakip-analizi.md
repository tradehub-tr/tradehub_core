# 11 — T-011 pazaryeri kuralları ve teslim yeteneği kıyaslaması

**Araştırma tarihi:** 2026-08-23 · **Durum:** tamamlandı

## Pazaryeri kuralları

| Sistem | Sayısal/resmî kural | Kaynak ve sınır |
|---|---|---|
| Amazon ana görsel | Saf beyaz RGB 255/255/255; ürün kadrajın en az %85'i; metin, logo, filigran, çerçeve ve yanıltıcı aksesuar yok | [Amazon G1881 yardım kaydı](https://sellercentral.amazon.com/help/hub/reference/G1881) oturum isteyebilir; aynı resmî kayda bağlanan [Amazon Seller Forums özeti](https://sellercentral.amazon.com/seller-forums/discussions/t/ab884127-f9b4-4053-8096-4991e1d60d1f). Sayısal piksel/bayt sınırları kategori ve ülkeye göre değişebildiğinden burada uydurulmadı. |
| Alibaba ürün görseli | JPEG/JPG/PNG, <5 MB, öneri >640×640; gerçek ürün, kolaj/yanıltıcı nesne yok; ana görselde ürün ≥%85 | [Alibaba GGS Product Power White Paper](https://activity.alibaba.com/supplier/1fb02307.html) |
| Alibaba ek rehber | Yaklaşık kare oran 1:1–1:1,3; >350 px, öneri ≥640 px; en az 3 görsel önerisi | [Alibaba product posting guide](https://activity.alibaba.com/page/04cb5e7a.html). İkincil rehberdir; birincil 5 MB kuralı kazanır. |

Amazon için internette dolaşan “10 GB” benzeri değerler güvenilir bir yükleme
sınırı olarak alınmadı. Doğrudan yardım sayfası oturum arkasında olduğu için
yalnız doğrulanabilen beyaz zemin/%85/yasaklar standarda adaydır.

## Teslim ve dönüşüm yeteneği

| Yetenek | Amazon/Alibaba | Shopify | Cloudinary | imgix | istoc durumu |
|---|---|---|---|---|---|
| Sayısal kabul politikası | Var | Tema sahibinde | Müşteri tanımlar | Müşteri tanımlar | **Var** — slot policy JSON |
| Responsive genişlik merdiveni | Platform içi | 4–6 genişlik önerir | Var | Var | **Var** — policy rendition matrisi |
| Kaynağı büyütmeme | Belirsiz | Açıkça no-upscale | Seçilebilir | Seçilebilir | **Var** — INV-01/FR-028 |
| Otomatik biçim | Platform içi | İstemci desteğine göre AVIF/WebP | `f_auto` | `auto=format` | **Var** — AVIF/WebP/JPEG zinciri |
| Otomatik kalite | Platform içi | Platform içi | `q_auto` içerik/cihaz sinyali | `auto=compress`, kalite parametresi | **Var** — hedef SSIM; üretim rollout'u ölçüm kapılı |
| Gravity/focal crop | Kural odaklı | center/region | `g_auto`, özel koordinat önceliği | crop/focal parametreleri | **Var** — override→safe/focal→suggestion→center |
| İmzalı dönüşüm URL'i | Platform içi | CDN URL'i | İmzalı dönüşüm | İmzalı URL | **Var** — imgproxy HMAC prototipi |
| İçerik-adresli sürüm | Platform içi | `v=` sürümü | public ID/version | kaynak URL + parametre | **Var** — hash URL/ETag |
| Purge | Platform içi | yönetilen | API | API | **Var ama istisna** — hash değişince purge gereksiz; overwrite için CF/Bunny istemcisi |
| Yerleşim önizleme | Liste önizlemesi | Tema önizleme | transformation preview | URL preview | **Var** — Crop Studio/simülatör; Meta Ads benzeri çoklu placement Faz 11 kartlarında |

Kaynaklar: [Shopify responsive images](https://shopify.dev/docs/storefronts/themes/best-practices/performance/use-responsive-images),
[Shopify `image_url`](https://shopify.dev/docs/api/liquid/filters/image_url),
[Cloudinary image optimization](https://cloudinary.com/documentation/image_optimization),
[Cloudinary automatic gravity](https://cloudinary.com/documentation/image_automatic_gravity),
[imgix quality](https://docs.imgix.com/en-US/apis/rendering/format/output-quality),
[imgix automatic](https://docs.imgix.com/en-US/apis/rendering/automatic).

## Faz 2'ye giren somut kurallar

1. Ürün ana görselinde arka plan uygunluğu ölçülebilir sinyal olsun; otomatik ret ancak etiketli yanlış-pozitif oranı < %1 ise açılsın.
2. Ana üründe kadraj doluluk hedefi ≥%85 olsun; nesne segmentasyonu ölçemiyorsa kural `skipped` yazsın.
3. Ana görselde filigran/metin/logo yasağı içerik kuralı olarak tanımlansın; kanıtsız otomatik ret olmasın.
4. Ürün görseli kabul biçimleri JPEG/PNG/WebP/AVIF olarak açık allowlist olsun; SVG ürün fotoğrafında gereksizdir.
5. Yükleme bayt tavanı ile decode MP tavanı ayrı değişmezler olsun.
6. Responsive profil sayısı varsayılan 4–6 genişlikte tutulup cache parçalanması engellensin.
7. LCP görseli eager + `fetchpriority=high`; LCP dışı görseller lazy olsun.
8. Her responsive görselde `srcset`, doğru `sizes`, `width` ve `height` bulunsun.
9. Türev üretimi kaynağı büyütmesin; minimum kalite eşiği kaynak küçükse upscale izni anlamına gelmesin.
10. Biçim seçimi `Accept`/istemci yeteneğine göre AVIF→WebP→JPEG fallback zincirinden yapılsın.
11. Focal/gravity önceliği profil override→güvenli alan+odak→odak→kalibre öneri→merkez olsun.
12. Türev URL'i içerik sürümü taşısın; yeni içerikte purge yerine yeni URL üretilsin.
13. Özel medya URL'leri kısa ömürlü ve imzalı; public hash URL'ler bir yıl immutable olsun.
14. Kalite sabit q yerine içerik sınıfı ve codec bazlı algısal hedefle seçilsin; encode bütçesi ≤4 olsun.

