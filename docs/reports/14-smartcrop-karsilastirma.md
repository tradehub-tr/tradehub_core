# 14 — T-014 smartcrop / focal öneri karşılaştırması

**Tarih:** 2026-08-23 · **Durum:** makine benchmarkı tamam, insan etiketi kapısı açık
· **Ham veri:** `docs/data/t014-smartcrop-benchmark.json`

## Makine sonucu

Canlı veritabanından 50 gerçek `Listing.primary_image` görseli kimliksiz
`SC0001…SC0050` kimlikleriyle dışa aktarıldı. Dosya adı, ilan, mağaza ve kullanıcı
bilgisi benchmark verisine yazılmadı. Üç yöntem de 50/50 görselde çıktı üretti.

| Yöntem | Başarı | Ortalama | p90 | Azami tahmini canlı buffer | Model |
|---|---:|---:|---:|---:|---:|
| Entropi + kenar + doygunluk | 50/50 | 22,8559 ms | 36,6302 ms | 2,25 MB | 0 |
| Düz/beyaz zemin segmentasyonu | 50/50 | 16,7017 ms | 31,5158 ms | 2,1631 MB | 0 |
| ONNX U²-Net-P | 50/50 | 168,8292 ms | 217,8720 ms | 3,125 MB | 4,3629 MB |

ONNX modelinin SHA-256'sı
`309c8469258dda742793dce0ebea8e6dd393174f89934733ecc8b14c76f4ddd8`,
boyutu 4.574.861 bayttır. Bellek sütunu süreç RSS'i değil, Pillow/numpy canlı
buffer tahminidir; rapor bunu RSS diye sunmaz.

## Açık insan kapısı

İnsan etiketi **0/50** olduğundan normalize ortalama/p90 sapma, beyaz zemin
başarısı ve güven eşiği hesaplanmamıştır: `threshold_calibrated=false`.
Algoritmanın kendi `confidence` değeri doğruluk değildir. Bu nedenle bugün bir
“kazanan” veya eşik ilan etmek veri uydurmak olur.

Etiketleme aracı `prototypes/smartcrop/annotate.html`; exporter
`media/smartcrop_dataset.py`; benchmark `scripts/benchmark_smartcrop.py`.
Teknik sorumlu/ürün fotoğraf editörü 50 odak noktasını işaretledikten sonra aynı
betik şu kapıları hesaplayacaktır: yöntem başına mean/p90 normalize sapma,
plain/complex zemin kırılımı ve güven→hata kalibrasyonu. Seçim kuralı:

1. beyaz zeminde en düşük ortalama sapma,
2. p90 sapmada kötüleşme yok,
3. güven eşiğinde kabul edilen önerilerin doğruluk hedefi ölçülmüş,
4. eşik altında öneri gösterilmez.

Bu insan işi tamamlanana kadar üretim `smartcrop` yalnız öneri modunda ve
kalibre edilmemiş bayrağıyla kalır.

