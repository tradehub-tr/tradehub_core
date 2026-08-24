# ADR-0024 — İstemci medya seti: native probe + browser-image-compression + MediaBunny

**Durum:** Kabul edildi; gerçek cihaz bütçeleri kalibrasyon bekliyor
**Tarih:** 2026-08-23 · **İlgili:** ADR-0018, ADR-0020

## Bağlam

T-015 tarayıcıda metadata/probe, küçük görsel ön-sıkıştırması ve video künyesi
için bir kütüphane seti ister. Üretim panelinde bugün
`browser-image-compression` ve `mediabunny` kurulu; görsel başlıkları mümkün
olduğunda saf `bytes.js`, fallback'te `createImageBitmap`; ağır iş
`preflight.worker.js` içinde çalışır. exifr/Pica/jSquash kurulu değildir.

## Seçenekler

| Seçenek | Ölçüm / bedel |
|---|---|
| exifr + Pica + jSquash + mediainfo.js paketinin tamamı | Daha geniş codec yüzeyi; dört yeni bağımlılık ve fiziksel cihaz ölçümü olmadan bellek riski |
| **Mevcut minimal set + native API + server fallback** | **Seçildi.** DeviceBudget 7/7, upload queue 10/10; destek yoksa ana thread yerine sunucu |
| Hiç istemci işlemi yok | En güvenli tarayıcı belleği; küçük kaynakta gereksiz upload ve erken geri bildirim kaybı |

## Ölçüm verisi

`docs/reports/15-client-butce.md`: dört deterministik cihaz sınıfı; düşük sınıf
decode/resize/encode tavanları 12/8/6 MP, orta 25/16/12 MP, yüksek 50/32/24 MP.
Bunlar başlangıç politikasıdır; gerçek cihaz sonucu değildir. Akış testleri
7/7 + 10/10 geçmiştir.

## Karar

Başlık probe için saf byte parser + native `createImageBitmap`, görsel küçültme
için mevcut `browser-image-compression`, video probe için MediaBunny kullanılır.
İşlem yalnız Worker/bitmap/bütçe kapıları geçerse istemcide yapılır. HEIC/AVIF
encode gibi doğrulanmamış işler sunucuya devredilir; yeni codec kütüphanesi
ölçüm olmadan eklenmez.

## Sonuçlar

Olumlu: mevcut bundle korunur; fallback her tarayıcıda işlevsel; hata kullanıcıya
görünür. Olumsuz: exifr/Pica/jSquash özelliklerinin tamamı yoktur ve istemci
tasarrufu gerçek cihazlarda henüz ölçülmemiştir.

## Geri dönüş yolu

Fiziksel cihaz laboratuvarında çökme/hata oranı kabul dışına çıkarsa istemci
sıkıştırma bayrağı kapanır ve tüm orijinaller sunucuya gider. Yeni kütüphane
ancak aynı 25 MP korpusta süre, peak bellek ve başarı oranı mevcut setten iyi
ölçülürse yeniden değerlendirilir.

