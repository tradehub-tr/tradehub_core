# ADR-0022 — K7: türevler File açmadan tenant kotasına sayılır

**Durum:** KABUL · **Seçenek D** · **Yürürlük:** 2026-08-24 (MOGEM-573)
**Tarih:** 2026-08-20 · **Güncelleme:** 2026-08-24

## Bağlam

İki verilmiş karar birbirini uygulanamaz kılıyor (ADR README "kararlar arası
gerilimler" listesinde kayıtlı):

- **K7 (yönetici kararı, `company-cover-video.md` §10.9):** "rendition'lar
  medya kotasından SAYILSIN" — varsayılanı değiştiren karar.
- **ADR-0009:** türevler için `File` kaydı **açılmaz** — ama bugünkü kota
  kapısı `File` üzerinden sayıyor. Sonuç: K7 **uygulanamıyor**; video paketi
  `frappe` import etmiyor ve `File` açmıyor (rapor 56 §7.4).

Ölçülen bedel tarafı (rapor 56 §7.4 / faz2 kapanışı madde 9): türevler
sayılırsa kapak videosu başına **~6 nesne (~19 MB tipik)** → satıcı kotası
**~6 kat** hızlı dolar; HLS eklendiğinde nesne sayısı basamak×segment ile
büyür (rapor 81'in tek koşumu 411 dosya bıraktı).

## Seçenekler

| # | Seçenek | Bedel |
|---|---|---|
| A | K7'yi uygula: kota sayacını `File`'dan koparıp `Media Version/Rendition` toplamına (bayt bazlı) bağla | Kota kapısının yeniden yazımı; mevcut satıcı kotaları fiilen daralır (~6×) — satıcıya görünür etki, iletişim ister |
| B | K7'yi revize et: yalnız **master/orijinal** kotadan sayılır, türevler platform maliyeti sayılır | Yönetici kararının geri alınması — imza ister; depolama bütçesi satıcıya yansımaz, kötüye kullanım (çok video) başka kapıyla sınırlanmalı |
| C | Ara yol: türevler kotaya **katsayıyla** girer (örn. master baytı × sabit çarpan olarak tahakkuk) | Gerçek bayt yerine tahmin — merdiven bayt ölçümü henüz yok (SAD §9.3 "TAHMİN" uyarısı); katsayı kalibrasyonu ister |
| **D** (öneri, 21 Ağu — ortak çatı) | **İki sayaç, tek toplam:** mevcut `File` bazlı sayaç (TUR-139, `entitlement.checks.check_media_storage_quota`) DOKUNULMADAN kalır; yanına `Media Rendition.bytes` toplamı ikinci sayaç olarak eklenir. Kota kapısı **ikisinin toplamına** bakar; satıcı panelde "orijinal 10 MB + türev 19 MB = 29 / 100 MB" görür | ADR-0009 korunur (türev `File` açmaz), TUR-139 kodu değişmez (ekleme), K7 uygulanır (türev sayılır). Bedel: gerçek bayt `Media Rendition.bytes`'tan gelir — merdiven ölçümü olmadan 0 sayılır, yani bayrak kapalıyken davranış bugünkünün AYNISI. Satıcı kotasının daralması A ile aynı (~6×) — iletişim yine ister, ama iki kalem ayrı görünür olduğu için "neden doldu" sorusu kendi kendini cevaplar |

## Karar

**D kabul edildi: iki sayaç, tek bayt toplamı.** Public orijinaller `File`
kayıtlarından `file_url` bazında tekilleştirilerek; türevler ise
`Media Rendition.bytes → Media Asset.owner_seller` zincirinden tenant bazında
ölçülür. Sert depolama kapısı bu ikisinin toplamına bakar. Türev için `File`
kaydı açılmaz; ADR-0009 korunur.

Dosya adedi ve rendition adedi raporlanır ama kota hesabının birimi değildir.
HLS tek mantıksal rendition satırında segment toplam baytını taşıdığı için
nesne sayısına göre tahmini çarpan kullanılmaz.

## Sonuçlar

- `media.files.storage_usage(store)["bytes"] = original_bytes + rendition_bytes`.
- Plan limiti `quota.max_storage_mb`; free 500 MB, starter 2.000 MB,
  pro/premium 5.000 MB, enterprise sınırsız varsayılanıyla yönetilir.
- Satıcı özeti iki kalemi ayrı gösterir; yüzde 80 uyarı, yüzde 100 yeni yükleme
  engelidir.
- Bayrak kapalıyken veya türev üretilmemişken rendition toplamı sıfırdır;
  önceki yalnız-orijinal davranış kendiliğinden korunur.

## Kanıt

`tradehub_core/media/files.py` (`storage_usage`, `rendition_stats`) ·
`tradehub_core/tests/test_media_quota_renditions.py` ·
`docs/reports/105-d2-kota-turev.md` ·
`docs/reports/56-d3-faz6-10-kapanis.md` §7.4 · `docs/adr/0009-turevler-file-kaydi-acmaz.md` ·
`docs/adr/README.md` "Kararlar arası gerilimler" · `docs/closure/faz2-kapanis.md` §3.9 ·
`docs/reports/57-durum-anlik-goruntu.md` karar #2 · `docs/reports/81-w6-video-kosum.md` §9 (411 dosya).

## Geri dönüş yolu

Ledger sayımı ile fiziksel depolama arasında kalıcı fark ölçülürse
`rendition_bytes` toplamı kota kapısından çıkarılarak eski yalnız-orijinal
hesabına dönülebilir; bunun için `File` üretmek veya veri migration'ı gerekmez.
