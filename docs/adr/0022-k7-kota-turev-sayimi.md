# ADR-0022 (TASLAK) — K7: türevler kotadan sayılsın kararı, ADR-0009 ile çelişiyor

**Durum:** ÖNERİLDİ · **Karar: BEKLİYOR** (platform yöneticisi + standart sahibi — `kota.md` güncellemesi T-022'ye bağlı)
**Tarih:** 2026-08-20 · **Yazan:** W7 doküman eşitlemesi (rapor 88)

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

**BEKLİYOR.** Hangi seçenek seçilirse seçilsin: (1) ADR-0009 ya korunur
(A'da sayaç `File`'sız kurulur) ya durumu güncellenir; (2) `kota.md` HLS'in
nesne sayısını da kapsayacak şekilde güncellenir (rapor 56 kalan-iş listesi
#14); (3) karar `company-cover-video.md` §10.9 karar bloğuna işlenir.

## Sonuçlar

Karar gecikirse: kota bugün türevleri **saymıyor** (K7'nin tersi fiilen
yürürlükte) ve video hattı üretime bağlandığı gün fark satıcı başına GB
mertebesine çıkar — geri dönüşü (tahakkuk etmiş kota) o zaman çok daha zor.

## Kanıt

`docs/reports/56-d3-faz6-10-kapanis.md` §7.4 · `docs/adr/0009-turevler-file-kaydi-acmaz.md` ·
`docs/adr/README.md` "Kararlar arası gerilimler" · `docs/closure/faz2-kapanis.md` §3.9 ·
`docs/reports/57-durum-anlik-goruntu.md` karar #2 · `docs/reports/81-w6-video-kosum.md` §9 (411 dosya).

## Geri dönüş yolu

**Karar bekliyor.** Türevler kotaya katılırsa ledger sayımı ile fiziksel bayt
farkı oluştuğunda tahakkuk durdurulur ve eski “yalnız orijinal” hesabına
dönülür. Katılmazsa depolama maliyeti satıcı başına bütçeyi aşınca karar gerçek
411+ dosyalık ölçümle yeniden açılır.
