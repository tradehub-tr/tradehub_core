# ADR-0017 — Otomatik odak (saliency) her görsele uygulanmaz; eşik üstünde ve yalnız ÖNERİ olarak

**Durum:** Kabul edildi (karar Faz 1'de verildi, kodu Faz 10'a devredildi)
**Tarih:** 2026-08-18 (T-014)
**İlgili:** ADR-0006 (aynı fazın ölçüm kültürü)

---

## Bağlam

1:1 kırpmada geometrik merkez yerine "enerji merkezi" kullanmak özneyi daha çok
korur mu — ve bu, kod yazmayı hak edecek kadar sık mı?

İlk ölçüm karar veremedi: **fixture korpusunda (n=32) ortalama kazanç −0,0000**,
kazancı 0,01'i aşan **0 dosya**. Sebep açık — fixture'lar sentetik ve enerji
düzgün dağılmış, yani enerji merkezi zaten geometrik merkez. Rapor bunu
saklamadı: *"Bu korpusla T-014 kararı verilemez."*

Ölçüm **canlı örneklemle** tekrarlandı (n=400, tohum 20260818).

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Saliency'yi her görsele otomatik uygula | En basit kural. Bedeli: dosyaların yarısında kazanç sıfır, hesap boşa gider; ve yanlış tahmin kullanıcının onaylamadığı bir kırpma üretir. |
| B — Hiç uygulama, merkez kırpmada kal | Sıfır maliyet. Bedeli: %4,5'lik kuyruk büyük kazanç veriyor (en iyi örnekte 0,589 → **1,000**). |
| **C (SEÇİLEN)** — **Eşik üstünde hesapla, sonucu ÖNERİ olarak sun** | Kuyruğu yakalar, boşa hesap yapmaz, yanlış tahmini kullanıcı düzeltir. Bedeli: kullanıcı arayüzü gerektirir (Faz 10). |

## Karar

`docs/reports/11-faz1-arge.md` §T-014:

1. **Saliency her görsele uygulanmaz.** Medyan kazanç **0,0000** — dosyaların
   yarısında enerji merkezi zaten merkezde.
2. **Eşik kuralı:** merkez kayması kısa kenarın **%10'unu** aştığında odak noktası
   önerilir. Eşik **ölçülen dağılımdan** türetildi (p90 = 0,1588), literatürden
   değil.
3. Sonuç **öneridir**, otomatik uygulama değil. Faz 10 (Crop Studio) kullanıcı
   onayını zaten sağlıyor; odak noktası oraya **başlangıç değeri** olarak beslenir.

## Gerekçe — ölçülen dağılım (n=400 canlı)

| Ölçü | Değer |
|---|---|
| Ortalama kazanç | +0,0093 |
| **Medyan kazanç** | **0,0000** |
| p90 kazanç | +0,0182 |
| En büyük kazanç | **+0,4109** (`111001-1.jpg`) |
| Merkez kayması (kısa kenar oranı) | ort. 0,0743 · medyan 0,0554 · **p90 0,1588** · max 0,4716 |
| Kazanç > 0,01 | **56/400 = %14,0** |
| Kazanç > 0,10 | **18/400 = %4,5** |

Kararın "öneri" olması ayrıca bir varsayım riskine dayanıyor ve rapor bunu açıkça
yazıyor: kenar enerjisi **özne ≠ enerji** varsayımına dayanır; desenli fon ya da
filigran bu ölçüyü kandırır.

## Sonuçlar

### Olumlu

- Sentetik korpusun karar veremeyeceği anlaşıldı ve ölçüm **canlı veriyle**
  tekrarlandı — bu depoda sonradan üç kez daha tekrarlanan bir düzeltme deseni
  (video fixture'ları, backfill maliyeti, AV1).
- Eşik keyfi değil, ölçülen dağılımın p90'ından türetildi.
- Hesap maliyeti dosyaların ~%86'sında hiç ödenmiyor.

### Olumsuz / açık

- **Kod artık var.** `core/smartcrop.py` entropi/kenar, düz zemin segmentasyonu
  ve ONNX U²-Net-P yöntemlerini aynı sözleşmede çalıştırıyor; 50 gerçek ürün
  görselinde üçü de 50/50 çıktı verdi (`14-smartcrop-karsilastirma.md`).
- **[?] Doğrulanmadı:** insan etiketi hâlâ **0/50**; bu yüzden ortalama/p90
  focal hatası ve güven eşiği kalibre edilmedi. `THRESHOLD_CALIBRATED=false`
  kalır ve öneri üretim kararı gibi sunulmaz.

## Geri dönüş yolu

50 insan etiketli T-014 seti eşik üstünde kabul edilen önerilerde hedef hatayı
tutturmazsa smartcrop tamamen kapatılır ve merkez/manual focal kullanılır.
Yöntem/eşik ancak `14-smartcrop-karsilastirma.md` mean/p90 ve zemin kırılımı
dolu olduğunda değiştirilir.
