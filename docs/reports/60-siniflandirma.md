# T-062 sınıflandırma ve format zinciri raporu

Ölçüm tarihi: 2026-08-22, macOS / Python 3.9.6 / Pillow 11.3.0. Korpus tanımı
`tradehub_core/tests/fixtures/image_t062/manifest.json`, ham ölçüm kaydı
`docs/data/t061-t062-olcum.json` içindedir.

## Korpus ve sonuç

Beş sınıfın her biri için 20 deterministik örnek gerçek dosya baytına
kodlanır; test doğrudan `classify()` girişini çağırır. Toplam sonuç 100/100,
yani %100'dür ve %95 kabul eşiğini geçer. Ayrı canlı örneklem kaydı 46/48
(%95,8) olarak korunur; canlı dosyalar repoda olmadığı için yeniden
üretilebilir kabul kapısı sentetik dengeli korpustur.

Karışıklık matrisi (satırlar gerçek, sütunlar tahmin):

| Gerçek \ Tahmin | photo | graphic | transparent | animation | document |
|---|---:|---:|---:|---:|---:|
| photo | 20 | 0 | 0 | 0 | 0 |
| graphic | 0 | 20 | 0 | 0 | 0 |
| transparent | 0 | 0 | 20 | 0 | 0 |
| animation | 0 | 0 | 0 | 20 | 0 |
| document | 0 | 0 | 0 | 0 | 20 |

Uçtan uca 100 sınıflandırma 1.991,8 ms sürdü. Bu süre encoder yetenek
sondasını bir kez çalıştırıp aynı yetenek haritasını tüm örneklere vermeyi de
içerir.

## Faz 2 zincir sözleşmesi

| Sınıf | Zincir | Kalite hedefi |
|---|---|---|
| photo | AVIF → WebP → JPEG | q88 |
| transparent | AVIF → WebP → PNG | q88, PNG lossless |
| graphic | WebP lossless → PNG | lossless |
| document | WebP lossless → PNG | lossless |
| animation | görsel zinciri boş | video hattı |

Düşük güvenli karar sınıf etiketini `photo`, güveni `low` olarak tutar ama
`safe_fallback=true` ile WebP lossless → PNG zincirini seçer. Böylece belirsiz
içerik kabul kuralındaki güvenli, kayıpsız tarafa yaklaşır; sürekli ton kanıtı
olan `photo/high` q88 zincirini kullanır.

## Bridge kontratı

Animasyon sonucu şu alanları taşır:

```json
{
  "klass": "animation",
  "target_pipeline": "video",
  "job_type": "video_from_animation",
  "chain": [],
  "video_targets": [
    {"fmt": "MP4", "codec": "H264"},
    {"fmt": "WEBM", "codec": "VP9"}
  ],
  "poster_required": true
}
```

Bridge çok-kareli kaynağı görsel encoder'a vermeden video işi açmalıdır.
Kanonik beşinci sınıf `document`tır; eski kayıtları okurken `text` giriş takma
adı çözülür, fakat yeni DocType seçeneği ve kalıcı kayıt `document` olmalıdır.

## Tekrar üretme

```text
python3 -m unittest tradehub_core.tests.test_image_classify -v
```
