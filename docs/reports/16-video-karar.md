# 16 — T-016 video karar motoru ve benefit gate

**Tarih:** 2026-08-23 · **Durum:** tamamlandı

## Karar

Karar kuralları kodda if/else zinciri değildir:
`media/pipeline/policy/video_decision.json` container, codec, profile/level,
çözünürlük, fps, bitrate, süre, ses codec/bitrate, pixel format, HDR ve rotation
sinyallerini `passthrough | remux | transcode | reject` aksiyonuna eşler.
`probe.py` ffprobe çıktısını normalize eder; yeni codec koşulu JSON'a eklenir.

Verimlilik metriği `bpp = video_bitrate / (width × height × fps)` tablodaki
eşiklerle değerlendirilir. Transcode çıktısı girdiden büyükse INV-05 benefit
gate çıktıyı atar ve kaynak/remux yolunu korur.

## Kabul kanıtı

| Kapı | Ölçüm | Sonuç |
|---|---:|---|
| Verimli 720p MP4 | yeniden encode yok | passthrough ✅ |
| Şişik fixture | 10.450.180 → 3.518.231 bayt | %66,33 küçülme ✅ |
| Aynı transcode kalite | VMAF 96,655 | ≥93 ✅ |
| 4K60/65 sn stres | %98,42 küçülme; 32,85 sn wall; 549,9 MiB | kabul bütçesinde ✅ |
| Faz 7 regresyon | 467/467 | ✅ |

Kanıt kaynakları `docs/reports/90-w8-video-kalanlari.md`,
`docs/data/faz7-4k60-benchmark.json`, `docs/reports/100-faz7-kapanis.md` ve
`test_video_transcode.py::test_FAYDA_KAPISI_verimli_kaynagi_korur` testidir.
Hiçbir fixture'da büyük çıktı yayınlanmaz; remux byte karşılaştırmasından
bilinçli olarak muaftır çünkü codec aynı kalır ve `moov` yerleşimi düzeltilir.

