# ADR-0021 (TASLAK) — VMAF eşiği: 93 gerçek içerikte INV-05 ile aynı anda sağlanamıyor

**Durum:** ÖNERİLDİ · **Karar: BEKLİYOR** (platform yöneticisi — `company-cover-video.md` §10.9 karar bloğuna girmeli)
**Tarih:** 2026-08-20 · **Yazan:** W7 doküman eşitlemesi (rapor 88; seçenekler rapor 56 §4.3'ten taşındı)

## Bağlam

`video_decision.json` kalite kapısı `vmaf_min: 93` taşıyor. İki ölçüm dalgası
eşiğin gerçek içerikte tutmadığını gösterdi:

1. **Rapor 39/56 (dış imajla, 3 gerçek dosya):** fayda kapısının (INV-05,
   ADR-0007) izin verdiği bütçede en iyi VMAF **≈86–89**; VMAF 92,11'e çıkmak
   kaynaktan **%20 büyük** dosya gerektiriyor (r2 eğrisi, `56` §4.2). 93 eşiği
   **sentetik `testsrc2` korpusundan** kalibre edilmişti; gerçek, bir kez
   sıkıştırılmış içerikte bant **75–90** ölçüldü.
2. **Rapor 81 (2026-08-20, İLK kez üretim imajında — ffmpeg n8.1.2, libvmaf=1):**
   gerçek satıcı videosunda (LST-04043) kapıdan geçen çıktının VMAF'ı
   **89,34 < 93**. Ayrıca ölçüldü: `vmaf_min`'i **uygulayan kod yok** —
   `transcode()` hiçbir yerde `measure_quality` çağırmıyor; eşik bağlansaydı
   bu çıktı (fayda kapısını %11,44 ile geçen tek gerçek kodlama) REDDEDİLİRDİ.
   Eski "imajda libvmaf yok, ölçemeyiz" engeli (56 §4.4) **düştü** — artık
   yalnız karar eksik.

## Seçenekler (ölçülen bedelleriyle — rapor 56 §4.3)

| # | Seçenek | Ölçülen sonuç | Bedel |
|---|---|---|---|
| A | Eşiği çıktı çözünürlüğünde **VMAF ≥ 85**'e indir | r2 (86,40) geçer; r3 (77,81) ve r6 (74,88) düşer | r3 bugün **+%46,93 bayt kazandırıyor** ve bloklanırdı — kazanılmış bayt geri verilir |
| B | **Göreli** kriter: capped çıktı, tavansız CRF 23 referansından en çok X puan geride | r3 −2,02 · r6 −0,72 · r2 **−9,09** | X=3'te r3/r6 geçer, r2 düşer — en büyük bayt kazancını (1,6 MB) veren dosya bloklanır; ayrıca her ölçüm için ikinci (referans) kodlama gerekir |
| C | VMAF'ı yayım kapısından çıkar, **raporlanan metrik** yap (`vmaf_report_floor`); tek sert kapı INV-05 kalsın | Hattın süre kapısıyla aynı desen: `duration_gate` çıktıyı atmaz, not düşer. Rapor 81'in koşumu fiilen böyle davrandı (89,34 kayda geçti, çıktı kabul) | Kaynağın "VMAF ≥93 yayımlanma koşuludur" cümlesinden **bilinçli sapma**; imza gerektirir |

Rapor 56'nın önerisi **C + kayıt** idi (gerekçeleriyle §4.3'te). **Bu bir
öneridir, karar değildir.**

## Karar

**BEKLİYOR.** Karar verilene kadar fiilî durum C'ye denk: eşik tabloda duruyor,
hiçbir kodlama onunla reddedilmiyor, VMAF ölçülüp kayda geçiyor (rapor 81).
Bu fiilî durum bir karar DEĞİLDİR ve imzasız sürdürülemez — kapı tanımıyla
kod davranışı bugün çelişiyor.

## Sonuçlar

Karar gecikirse: video hattı üretime bağlandığında (rapor 81 §8'in boşlukları
kapandığında) kapı ya boş kalır (bugünkü kod) ya da bağlanır ve gerçek
içeriğin çoğunu bloklar (ölçülen bant 75–90). İkisi de kararsız bırakılamaz.

## Kanıt

`docs/reports/56-d3-faz6-10-kapanis.md` §4.2–4.4 ·
`docs/reports/39-t072-video-hatti.md` §4 · `docs/reports/81-w6-video-kosum.md`
§3 (halka 4), §8.3 · `docs/reports/22-t072-vmaf-av1.md` (93'ün sentetik
kalibrasyonu) · `media/pipeline/policy/video_decision.json` (`vmaf_min`).

## Geri dönüş yolu

**Karar bekliyor.** Eşik rollout'ta gerçek içeriklerin kabul oranını veya byte
kazanımını hedef dışına iterse kalite kapısı report-only moda alınır; kaynak
video yayınlanır. Yeni eşik yalnız aynı codec/çözünürlükte en az üç gerçek video
ve kalite-eşit ölçümle değerlendirilir.
