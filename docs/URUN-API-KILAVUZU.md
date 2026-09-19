# İstoc Ürün API'si — Entegrasyon Kılavuzu (MOGEM-665)

ERP / muhasebe / stok yazılımınızı İstoc'a bağlamak için üç uç nokta ve bir
bildirim kanalı vardır:

| İş | Uç | Yetki alanı | Sınır |
|---|---|---|---|
| Jeton alma | `POST /api/method/tradehub_core.api.v1.public_api.token` | — | IP başına 30/dk |
| Ürün ekleme / güncelleme | `POST /api/method/tradehub_core.api.v1.catalog.upsert_products` | `catalog:write` | ≤ 100 ürün / istek |
| Stok / fiyat yazma | `POST /api/method/tradehub_core.api.v1.catalog.update_stock` | `stock:write` | ≤ 500 kalem / istek |
| Stok değişimlerini çekme | `GET /api/method/tradehub_core.api.v1.catalog.changes` | `catalog:read` | ≤ 500 olay / sayfa |
| Stok bildirimi (itme) | Panelde tanımlanan **webhook** adresine imzalı `POST` | — | 5 deneme, sonra "ölü" |

Bütün uçlar mağazanın **paketine** bağlıdır: `feature.api.access` (Pro / Kurumsal).
Dakikalık istek sınırı paketin `quota.api_rate_limit` değeridir (Pro 60, Kurumsal 1.000);
aşımda `429`.

---

## 1. Bağlantı kurma (panel)

Satıcı paneli → **Ürünler → Toplu Yükleme → API Bağlantısı** (`/seller-api`).

1. **Bağlantı oluştur** → `client_id` ve **yalnız bir kez** gösterilen `client_secret`.
2. İsteğe bağlı **webhook adresi + imza sırrı** (yalnız `https`/`http`, yerel/özel ağ adresleri reddedilir).
3. **Sırrı yenile**: eski sır anında geçersiz olur; `client_id` değişmez.
4. **Bağlantıyı kapat**: verilmiş jetonlar anında reddedilir (`401`).

## 2. Jeton alma

```bash
curl -X POST https://istoc.example.com/api/method/tradehub_core.api.v1.public_api.token \
  -d grant_type=client_credentials -d client_id=istoc_xxx -d client_secret=***
# → {"message": {"access_token": "<jwt>", "token_type": "Bearer", "expires_in": 86400, ...}}
```

Jeton 24 saat geçerlidir. Her istekte `Authorization: Bearer <jwt>` başlığı gönderilir.

## 3. Ürün ekleme / güncelleme — `upsert_products`

Eşleştirme anahtarı **`sku`** (mağaza içinde benzersiz; boşluklar kırpılır, büyük/küçük
harf ayrımı yoktur). SKU varsa güncellenir, yoksa oluşturulur.

```json
POST /api/method/tradehub_core.api.v1.catalog.upsert_products
{"products": [
  {"sku": "KBL-100", "title": "Kablo 100 m", "list_price": 1200, "price": 1100,
   "stock": 40, "unit": "metre", "currency": "TRY", "description": "<p>…</p>",
   "images": ["https://cdn.ornek.com/kbl-100-1.jpg"],
   "attributes": {"color": "Siyah"},
   "variants": [
     {"sku": "KBL-100-K", "price": 1100, "stock": 20, "axes": {"Renk": "Kırmızı"}},
     {"sku": "KBL-100-M", "price": 1100, "stock": 20, "axes": {"Renk": "Mavi"}}
   ]}
]}
```

| Alan | Zorunlu | Not |
|---|---|---|
| `sku` | evet | Mağaza içinde benzersiz |
| `title` | yeni üründe | **50–250 karakter**, emoji yok (SEO kuralı; panel formuyla aynı) |
| `list_price` | yeni üründe | Liste fiyatı (`base_price`) |
| `price` | hayır | Satış fiyatı; **yeni üründe verilmezse liste fiyatı kopyalanır**, mevcut üründe verilmezse **değişmez** |
| `currency` | hayır | Varsayılan **TRY** |
| `stock` | hayır | `0` kabul edilir; negatif reddedilir |
| `unit` | hayır | `adet`, `metre`, `ton`, `kutu`, `çift`, `saat`, `kg`, `litre`, `m2`, `m3`… (tanınmazsa uyarı + `Adet`) |
| `images` | hayır | En fazla **10** URL, `jpg/png/webp`, ≤ **5 MB**; fazlası/indirilemeyen uyarıyla atlanır |
| `attributes` | hayır | `{öznitelik_kodu: değer}`; bilinmeyen kod uyarı |
| `variants` | hayır | **Yalnız oluştururken** yazılır; güncellemede `VARIANTS_NOT_UPDATED` uyarısı |
| `description` | yeni üründe | HTML olabilir; **≥ 150 görünür karakter**, emoji yok. Güncellemede gönderilmezse korunur |
| diğer | hayır | `short_description`, `brand`, `category`, `product_category`, `product_type`, `condition`, `barcode`, `tags`, `video_url`, `min_order_qty`, `max_order_qty`, `low_stock_threshold`, `track_inventory`, `allow_backorders`, `shipping_weight`, `handling_days`, `country_of_origin` |

Güncellemede **gönderilmeyen, `null` ya da boş** alanlar mevcut değeri korur.
Yeni ürün **onay bekler** (`Pending`); panelden toplu onaylanır. Mevcut ürünün durumu
değişmez (reddedilmiş ürün yeniden onaya gönderilir).

### Yanıt (kısmi başarı)

```json
{"message": {
  "job": "BIJ-2026-00042",
  "summary": {"total": 3, "created": 1, "updated": 1, "rejected": 1},
  "results": [
    {"index": 1, "sku": "KBL-100", "status": "created", "listing": "LST-01234", "listing_code": "…",
     "warnings": [{"code": "IMAGE_FAILED", "message": "…"}]},
    {"index": 2, "sku": "KBL-200", "status": "updated", "listing": "LST-01100", "warnings": []},
    {"index": 3, "sku": "KBL-300", "status": "rejected", "code": "PRICE_RULE", "field": "price",
     "message": "Satış fiyatı (150) liste fiyatını (100) geçemez"}
  ]}}
```

Her çağrı panelde **Yükleme Geçmişim → Kaynak: API** altında bir içe aktarma kaydı
(`Bulk Import Job`, `source = api`) olarak görünür; reddedilen satırlar hata listesindedir.

## 4. Stok / fiyat yazma — `update_stock`

Değerler **mutlaktır** (fark değil). Aynı isteği iki kez göndermek ikinci seferde
`unchanged` döner. Ürünün onay durumu **değişmez**, yeniden onay gerekmez.

```json
POST /api/method/tradehub_core.api.v1.catalog.update_stock
{"items": [
  {"sku": "KBL-100", "stock": 35},
  {"sku": "KBL-200", "price": 90, "list_price": 100},
  {"sku": "KBL-100-K", "stock": 12}
]}
```

Varyant SKU'larında yalnız `stock` ve `price` güncellenir. `stock` her zaman **fiziksel
sayımdır**; İstoc, sevk edilmemiş açık siparişlerin rezervini düşerek satılabilir adedi
hesaplar (`reserved_qty` ve `available_qty` yanıtta görünür), açık rezerv asla silinmez. Yanıt: `summary{total,updated,unchanged,rejected}`
ve satır başına `status`, `stock_qty`, `available_qty` (rezerve düşülmüş), `price`, `list_price`.

## 5. Stok değişimlerini alma

İstoc'ta **sipariş, iptal, sevkiyat, iade** kaynaklı her stok hareketi bir olay üretir.
API ile yazdığınız stok **olay üretmez** (yankı döngüsü yoktur).

### 5a. Yoklama — `changes`

```
GET /api/method/tradehub_core.api.v1.catalog.changes?since=0&limit=100
→ {"events": [{"id": 17, "event": "stock.changed", "reason": "reserve", "sku": "KBL-100",
               "listing_code": "…", "stock_qty": 40, "reserved_qty": 2, "available_qty": 38,
               "occurred_at": "2026-09-15 10:22:01"}],
   "next_since": 17, "has_more": false}
```

`next_since` değerini saklayın; bir sonraki çağrıda `since` olarak gönderin.

### 5b. Webhook (itme)

Aynı gövde `POST` edilir. Başlıklar:

| Başlık | Değer |
|---|---|
| `Content-Type` | `application/json` |
| `X-Istoc-Event` | `stock.changed` |
| `X-Istoc-Delivery` | olay kimliği (tekrar gönderimde aynı) |
| `X-Istoc-Signature` | `sha256=<HMAC-SHA256(imza_sırrı, ham gövde)>` |

Doğrulama (Python):

```python
import hmac, hashlib
beklenen = "sha256=" + hmac.new(SIR.encode(), ham_govde, hashlib.sha256).hexdigest()
if not hmac.compare_digest(beklenen, istek.headers["X-Istoc-Signature"]): abort(401)
```

`2xx` dışındaki her cevap başarısız sayılır; **1 / 5 / 15 / 60 / 360 dk** sonra tekrar
denenir, 5. başarısızlıkta olay **ölü** olur ve panelde **API Bağlantısı → Giden stok
bildirimleri** altında görünür; oradan elle yeniden kuyruğa alınır. Zaman aşımı 10 sn.

## 6. Hata sözlüğü

| Kod | Anlam |
|---|---|
| `INVALID_PRODUCT` / `INVALID_ITEM` | Liste öğesi bir nesne değil (örn. metin/sayı) |
| `SKU_REQUIRED` | `sku` boş |
| `TITLE_REQUIRED` / `PRICE_REQUIRED` | Yeni üründe zorunlu alan eksik |
| `INVALID_NUMBER` | Sayısal alan sayı değil |
| `SEO_TITLE` / `SEO_DESCRIPTION` | Başlık 50–250 / açıklama ≥150 görünür karakter, emoji yok (mesaj sayıyı söyler) |
| `PRICE_NEGATIVE` / `STOCK_NEGATIVE` | Negatif değer |
| `PRICE_RULE` | Satış fiyatı liste fiyatını geçiyor (gönderilmeyen taraf mevcut değerden okunur) |
| `DUPLICATE_IN_BATCH` | Aynı SKU aynı istekte birden çok |
| `NOT_FOUND` | (update_stock) Bu mağazada SKU yok |
| `NOTHING_TO_UPDATE` | (update_stock) stok/fiyat alanı yok |
| `VARIANT_INVALID` / `VARIANT_FIELD_UNSUPPORTED` | Varyant gövdesi hatalı / varyantta desteklenmeyen alan |
| `IMAGES_INVALID` / `ATTRIBUTES_INVALID` | Tür hatası |
| `QUOTA_EXCEEDED` | Paketin ürün sayısı sınırı |
| `FEATURE_DENIED` | Paket özelliği yok (örn. çoklu varyant) |
| `REQUIRED` / `VALIDATION` / `DUPLICATE` | Sunucu doğrulaması |
| `SYSTEM` | Beklenmeyen hata (Error Log'a düştü) |

Uyarı kodları: `IMAGE_LIMIT`, `IMAGE_FAILED`, `UNIT_UNKNOWN`, `ATTRIBUTE_UNKNOWN`,
`UNKNOWN_FIELD`, `VARIANTS_NOT_UPDATED`.

HTTP durumları: `401` jeton yok/geçersiz/kapatılmış · `403` yetki alanı, paket ya da
mağaza durumu · `409` aynı mağazada eş zamanlı işlem (biraz sonra tekrar deneyin) ·
`417` gövde/limit hatası (`ValidationError`) · `429` hız sınırı · `503` kilit altyapısı (Redis) yanıt vermiyor — biraz sonra tekrar deneyin.

## 7. Desteklenmeyen işlemler (bilinçli)

- Ürün **silme / arşivleme** API'den yapılmaz (panelden).
- Varyant **güncelleme** yapılmaz; varyant stoğu `update_stock` ile varyant SKU'su üzerinden yazılır.
- Görsel **silme** yapılmaz; `images` gönderildiğinde galeri yeniden kurulur.
- Sipariş uçları bu API'nin kapsamı dışındadır.
