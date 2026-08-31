# Değişiklik talebi — slot politikası (F-10, F-11)

**Durum:** karar bekliyor · **Hazırlayan:** kod denetimi, 28-29 Ağustos 2026
**Neden talep, neden doğrudan düzeltme değil:** MOGEM-617 Faz 2 çıktısı şunu
söylüyor —

> "Bu fazın çıktısı sabitlenmiş sayılardır. Faz 3'ten sonraki hiçbir geliştirme
> bu sayıları tartışmaz; değiştirmek isteyen değişiklik talebi açar."

Aşağıdaki iki madde slot JSON'larının **içeriğine** dokunuyor. Denetimde bulunan
diğer 28 kusur koda aitti ve düzeltildi; bu ikisi düzeltilmedi, çünkü karar
politikanın sahibinindir.

---

## F-10 · `allow_data_uri` 9 slotun 7'sinde tanımsız

### Ölçüm

| Slot | `allow_data_uri` |
|---|---|
| `brand-logo.json` | `false` |
| `seller-logo.json` | `false` |
| `category-banner.json` | **tanımsız** |
| `company-cover-image.json` | **tanımsız** |
| `company-cover-video.json` | **tanımsız** |
| `document-attachment.json` | **tanımsız** |
| `product-image.json` | **tanımsız** |
| `product-video.json` | **tanımsız** |
| `user-avatar.json` | **tanımsız** |

Motordaki kural (`pipeline/policy/engine.py:858`):

```python
if probe.is_data_uri and accept.get("allow_data_uri") is False:
```

`is False` karşılaştırması **kasıtlı olarak** "açıkça yasaklanmış" ile
"belirtilmemiş"i ayırıyor. Anahtar yoksa `None is False` → yanlış → kural hiç
çalışmıyor. Yani 7 slotta `data:` URI kuralı ölü.

### Etkisi — abartılmamalı

Ölçüldü: `detected="data_uri"` künyesi `product.image` slotunda **yine
reddediliyor**, ama başka kurallarla:

```
data_uri  product.image  action=reject  allow=False
          ['product_image_content_type_mismatch',
           'product_image_unreadable',
           'product_image_master_under_spec']
```

Yani **açık kapı değil**, yanlış teşhis: kullanıcı "Gömülü veri (data: URI)
kabul edilmiyor; dosya olarak yükleyin" yerine "dosya okunamıyor" mesajını
alıyor ve ne yapacağını bilmiyor. Dış API'ye giden kod da
`data_uri_forbidden` değil, alakasız üç kod oluyor.

### Karar seçenekleri

1. **7 slota `"allow_data_uri": false` ekle.** Niyet her slotta açıkça yazılır,
   `is False` karşılaştırması olduğu gibi kalır. *Slot JSON'u değişir → bu
   talebin konusu.*
2. **Motorun varsayılanını `is not True` yap.** Slot dosyalarına dokunulmaz ama
   7 slotun davranışı sessizce değişir ve `is False`'ın kasıtlı ayrımı silinir.
3. **Bırak.** Ret zaten oluyor; yalnız mesaj kalitesi kaybı kabul edilir.

**Öneri: (1).** Güvenlik anahtarının 7 dosyada boş kalması bir karar değil,
eksik; ve (1) motorun mevcut sözleşmesini bozmadan niyeti belgeler.

---

## F-11 · `on_violation.require = "warn"` 4 slotta

### Ölçüm

| Slot | `on_violation.require` |
|---|---|
| `brand-logo.json` | `reject` |
| `company-cover-video.json` | `reject` |
| `product-image.json` | `reject` |
| `seller-logo.json` | `reject` |
| `user-avatar.json` | `reject` |
| `category-banner.json` | **`warn`** |
| `company-cover-image.json` | **`warn`** |
| `document-attachment.json` | **`warn`** |
| `product-video.json` | **`warn`** |

`require` bloğu asgari kısa kenar, asgari alan, oran bandı gibi **geometri**
kurallarını taşıyor. `warn` demek: kural ihlal edilse de dosya kabul edilir,
yalnız uyarı düşer.

### Neden sorulmayı hak ediyor

Bu bir kusur olmayabilir — dört slotun ikisi (`category.banner`,
`company.cover_image`) editoryal görseller ve gevşek eşik bilinçli bir tercih
olabilir. Ancak ikisi öyle görünmüyor:

- `product.video` geometri ihlalinde geçiyor, ama kardeşi `product.image`
  reddediyor. Aynı ürün kartındaki iki varlık için farklı sıkılık.
- `document.attachment` için `require` bloğunun anlamı zaten sınırlı.

Denetim bunu **kusur olarak işaretlemiyor**; tutarsızlığı görünür kılıyor.

### Karar seçenekleri

1. **Olduğu gibi bırak, gerekçeyi slot dosyasına yorum olarak yaz.** Bir sonraki
   okuyan aynı soruyu sormaz.
2. **`product.video`'yu `reject`'e çek**, diğer üçü kalsın.
3. **Dördünü de `reject`'e çek.** En sıkı; mevcut içeriğin bir kısmı yeni
   yüklemelerde reddedilmeye başlar.

**Öneri: (1) ya da (2).** Hangisi olursa olsun, kararın yazılı olması bu tablonun
tekrar keşfedilmesini engeller.

---

## Bu talebin kapsamadıkları

Denetimde bulunan diğer bulgular koda aitti ve düzeltildi (probe sızıntıları,
yol güvenliği fail-closed, SEO denetimi çökmeleri, AV daemon sağlığı, bekletme
sonrası türev üretimi, istemci/sunucu imza ayrışması). Bu dosya yalnız
**politika verisine dokunan** iki maddeyi taşır.
