# ADR-0006 — Sabit kalite yerine hedef SSIM'e ikili arama; encode bütçesi 4

**Durum:** Kabul edildi · yürürlükte · **maliyeti sonradan ölçüldü ve karar yeniden açılmalı** (aşağıda)
**Tarih:** 2026-08-18 (T-013) · maliyet ölçümü 2026-08-19 (T-028)
**İlgili:** ADR-0007 (fayda kapısı), ADR-0008

---

## Bağlam

Bugün kalite **sabit**: `media/pipeline.py:148` → `to_webp(data, quality=80)` ve
`presets.PRESETS` 90/88/82 (`presets.py:14-16`). "q80 kullanıyoruz" cümlesinin
arkasında hiçbir doğrulama yok.

Ölçüldü (`docs/reports/11-faz1-arge.md` §T-013.3, 10 fixture, q=40…95 adım 1,
master çözünürlükte, politika hedefi `product-image.json` → photo **0,96**,
graphic **0,98**):

> Sabit kalite hedefi kaç fixture'da tutuyor: **q80 → 1/10** · **q88 → 4/10**.

Photo fixture'larında hedefi tutmak q88-90, grafiklerde q92-94 gerektiriyor.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Sabit kalite (bugünkü q80) | Ucuz ve öngörülebilir. Ama kalite tabanı **ölçülmüyor**; 10 fixture'ın 9'unda hedef tutmuyor. |
| **B (SEÇİLEN)** — Hedef SSIM'e **ikili arama**, sınırlı encode bütçesiyle | Dosya başına ölçülmüş kalite tabanı. Bedeli: her türev için birden çok encode + SSIM. |
| C — İçerik sınıfına göre sabit kalite tablosu (photo=q90, graphic=q93) | Aramasız, ucuz. Bedeli: sınıf içi dağılım geniş — aynı korpusta min q 76 ile 94 arasında değişiyor; tablo ya fazla bayt harcar ya hedefi kaçırır. |

## Karar

`tradehub_core/media/pipeline/quality/ssim.py`:

- `DEFAULT_MAX_ENCODES = 4` (`ssim.py:78`, `image/render.py:110` ile aynı değer) —
  görev sözleşmesi: adaptif kalite **en fazla 4 encode denemesi**.
- `DEFAULT_QUALITY_RANGE = (70, 95)` (`ssim.py:62`).
- Taban kaliteye dayanılırsa sonuç `reason="floor_reached"` ile işaretlenir
  (`ssim.py:74`, `ssim.py:544`): çıktı hedefi **tutar**, yalnız "en düşük olduğu"
  iddia edilmez.
- Encoder yeniden yazılmadı; `search_quality` varsayılan olarak
  `media/pipeline.optimize`'ı çağırır.

### Aralık kararının kendisi de ölçümle verildi

4 adımlık ikili arama (40,95) aralığında yalnız **{67, 81, 88, 92}** kalitelerini
gezebiliyor; **92 üstü erişilemez**. Hedefi q93-94'te tutan iki grafik bu yüzden
çözülemedi — *arama hatası değil, aralık hatası*
(`docs/reports/11-faz1-arge.md` §T-013.4).

| aralık | 4 encode'da çözülen | ort. sapma | max sapma |
|---|---|---|---|
| (40, 95) | 8/10 | 1,12 | +3 |
| (60, 95) | 9/10 | 0,78 | +2 |
| **(70, 95)** | **10/10** | **0,40** | **+1** |
| (80, 95) | 10/10 | 0,40 | +4 |
| (40, 95) · 5 encode | 10/10 | 0,40 | +1 |

`tests/test_quality_ssim.py::test_varsayilan_aralik_olcumle_secildi` q94'e
erişilebilirliği kilitliyor.

## Gerekçe

- Uyarlamalı kalitenin değeri bu korpusta **bayt tasarrufu değil, ölçülebilir bir
  kalite tabanı**dır. "SSIM ≥ 0,96 garanti ediyoruz" cümlesinin arkasında dosya
  başına ölçüm var; "q80 kullanıyoruz" cümlesinin arkasında hiçbir şey yok.
- İkili aramanın dayanağı (SSIM'in kalitede monoton artışı) ayrıca ölçüldü
  (§T-013.6); tek istisna **zaten-WebP** kaynaklar — orada monotonluk yok ve
  `presets.MIN_SAVING_RATIO` kapısının o dosyaları hiç işlememesi doğru karar.
- SSIM tanımı bilinçli seçildi (Wang 2004, scikit-image varsayılan varyantı, 7×7
  düzgün pencere): hem saf Python integral görüntüyle birebir uygulanabiliyor hem
  dışarıdan doğrulanabiliyor. İki arka uç aynı sayıyı veriyor (mutlak fark
  **≤ 4,2e-14**, §T-013.7).

## Sonuçlar

### Olumlu

- Kalite tabanı dosya başına ölçülüyor ve raporlanıyor.
- Bütçe (70,95)+4 ile ölçülen korpusun **10/10'unda** hedef tutuyor.

### Olumsuz — ölçüldü, ve bu ADR'nin en önemli kısmı

**1. Bu korpusta hedef SSIM'e uymak baytı BÜYÜTÜYOR.** Toplamda hedefi tutan
kalite, q80'in **1,69 katı**, q88'in **1,09 katı** bayt üretiyor
(§T-013.5). Tek kazanan satır zaten-WebP olan dosya. Bayt kazancı korpus gerçek
ürün fotoğrafına döndüğünde beklenir — **ama ÖLÇÜLMEDİ.**

**2. Döngü, türev üretiminin baskın maliyeti.** `docs/reports/17-t028-backfill-plani.md`
§4.3, boş makinede ölçtü:

| Bütçe | Görsel başına | encode | SSIM | kalan | çıktı |
|---|---:|---:|---:|---:|---:|
| **4 (üretim varsayılanı)** | **10,45 s** | 11,73 s (%37) | **16,35 s (%52)** | 3,27 s (%10) | 5.062.853 B |
| 1 (arama yok) | **3,50 s** | 3,11 s (%30) | 4,09 s (%39) | 3,31 s (%31) | 6.822.375 B |

Yani adaptif döngü **2,99× maliyet** getiriyor ve karşılığında çıktıyı **%35**
küçültüyor. Toplam sürenin ~%67'si yalnızca döngüden geliyor ve **asıl pahalı
kalem encode değil SSIM (%52)**.

**3. Erken çıkış yok.** Ölçüm: **12 türevin 12'si de bütçeyi sonuna kadar
harcıyor** — görsel başına 48 encode + 48 SSIM. Çoğu deneme
`quality_floor_reached` ile bitiyor, yani taban kalite (q70) hedefi zaten
tutuyor ama döngü yine de 4 deneme yapıyor. `search_quality` taban kaliteyi önce
deneyip geçtiğinde durabilseydi bütçe 4'ten ~2'ye inerdi (§4.2).

**4. Geri dönük tohumlamanın faturası bu karardan geliyor:** 2.428 tekil adres ×
10,45 sn = **taban ~7 saat**, gerçekçi bant **7–47 worker-saat**
(`DALGA-A-DEVIR.md`, `docs/reports/17-t028-backfill-plani.md` §4.5).

### Yeniden açılması gereken

Bu ADR'nin kararı (bütçe 4) **yürürlükte kalıyor**, ama maliyet ölçümü karar
verildiğinde yoktu. Açık iş: **erken çıkış** eklenmesi (maliyeti ~3 kat düşürür)
ve kalite kapısının bununla ne kaybedeceğinin ölçülmesi. Bu ölçüm **yapılmadı**.

## Geri dönüş yolu

Gerçek ürün korpusunda adaptif yol q85'e göre p95 CPU'yu kabul bütçesinin üstüne
çıkarır veya hedefi tutan örnek oranı düşerse sabit kaliteye bayrakla dönülür.
Erken çıkış/codec sınırları ancak `13-kalite-prototip.md` ölçümü aynı kalite
hedefinde yeniden üretildiğinde değiştirilir.
