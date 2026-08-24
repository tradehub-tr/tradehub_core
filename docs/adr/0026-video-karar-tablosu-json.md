# ADR-0026 — Video codec kararları sürümlü JSON tablosudur

**Durum:** Kabul edildi
**Tarih:** 2026-08-23 · **İlgili:** ADR-0007, ADR-0010, ADR-0011

## Bağlam

Container/codec/profile/fps/HDR kombinasyonlarını kodda büyüyen if/else zinciri
olarak tutmak yeni codec eklemeyi deploy mantığına bağlar ve politika paritesini
zorlaştırır. Faz 7 hattı aynı kararları probe, transcode ve testlerde kullanır.

## Seçenekler

| Seçenek | Ölçüm / bedel |
|---|---|
| Python if/else zinciri | Kolay başlangıç; kural sürümü ve şema doğrulaması zayıf |
| Veritabanı karar satırları | Canlı değişim; migration/cache ve audit karmaşıklığı |
| **Repo içinde şemalı/sürümlü JSON + saf yorumlayıcı** | **Seçildi**; review/test ile atomik |

## Ölçüm verisi

`docs/reports/16-video-karar.md`: şişik fixture %66,33 küçülürken VMAF 96,655;
verimli MP4 passthrough; Faz 7 paketi 467/467. Karar tablosu HLS dahil tüm codec
hedeflerinin tek veri kaynağıdır.

## Karar

`media/pipeline/policy/video_decision.json` şema sürümü, sıralı kurallar,
aksiyon ve hedef parametreleri taşır. Yorumlayıcı bilinmeyen alan/aksiyonu
reddeder; yeni codec kod dalı değil yeni tablo satırı ve fixture gerektirir.
Benefit gate tablonun üzerinde değişmezdir.

## Sonuçlar

Olumlu: karar diff'i okunur, testlenir, frontend/worker'a senkronlanabilir.
Olumsuz: yanlış kural sırası gölgelenme yaratabilir; schema ve coverage testi
zorunludur. Canlı DB edit'i yoktur.

## Geri dönüş yolu

Yeni tablo sürümü regresyon üretirse dosya önceki git sürümüne döndürülür;
orijinal/passthrough kaynak korunur. JSON ifade gücü yetersiz kalırsa yeni
operatör schema+yorumlayıcı+negatif testle eklenir; ad hoc if/else eklenmez.

