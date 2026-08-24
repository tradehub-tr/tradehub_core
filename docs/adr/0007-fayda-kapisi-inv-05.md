# ADR-0007 — Fayda kapısı (INV-05): kaynaktan büyük türev asla yazılmaz

**Durum:** Kabul edildi · yürürlükte · **video hattında istenmeyen sonucu ölçüldü**
**Tarih:** Faz 6 (T-063) · video sonucu 2026-08-19'da ölçüldü
**İlgili:** ADR-0010 (AV1), ADR-0011 (H.264)

---

## Bağlam

Bir türev merdiveni, kaynaktan **büyük** çıktılar üretebilir. Ölçülen gerçek
vakalar:

- `w1280` ve `w1920` profilleri 1080 px kaynakta **aynı çıktıyı** üretip iki
  kayıt açıyordu (`DALGA-A-DEVIR.md` D-1; kanıt: `rendition_key=…|w1280|1080|avif`
  ve `…|w1920|1080|avif`, `file_url` aynı).
- Video merdiveninde sabit bitrate ile en düşük basamak kaynaktan **%5,8 büyük**
  çıktı; `video_square_352.mp4` 294.350 B → 585.065 B (**%98 büyük**);
  `video_long_540s` 3.986.750 B → 17.833.465 B (**4,5 kat**)
  (`media/pipeline/policy/video_decision.json` → `rate_control_why`).

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — Merdiveni koşulsuz üret, büyümeyi kabul et | Basit ve öngörülebilir. Bedeli: depolamayı ve teslimi **kötüleştiren** türevler; `srcset` en büyük basamağı seçtiğinde kullanıcı kaynaktan büyük dosya indirir. |
| **B (SEÇİLEN)** — Çıktı kaynaktan küçük değilse **at**, biçim zincirinde bir alta düş; zincir tümden düşerse kaynağı olduğu gibi geçir (`passthrough`) | Hiçbir koşulda dosyayı büyüten türev yazılmaz. Bedeli: bazı sınıflarda **hiç** türev üretilmez ve fazın hedefi tutmaz. |
| C — Eşiği gevşet (ör. %10 büyümeye izin ver) | Daha çok türev üretilir. Bedeli: kapının ne söylediği belirsizleşir; "kazanç" tanımı keyfileşir. |

## Karar

**INV-05 fayda kapısı.** `media/pipeline/image/render.py` başlığı, garanti 4:

> Bir biçimin çıktısı KAYNAKTAN büyük ya da eşitse o çıktı **ATILIR** ve
> `formats[]` zincirinde bir alta düşülür. Zincirin tamamı düşerse kaynak olduğu
> gibi geçirilir (`passthrough=True`) — **hiçbir koşulda dosyayı büyüten bir
> türev yazılmaz.**

Uygulama: `render.py:885-889` (`no_benefit_vs_source`), `render.py:907`
(zincir tükendi → passthrough), `NOTE_PASSTHROUGH = "passthrough_no_benefit"`
(`render.py:128`).

Video tarafında aynı kapı `video_decision.json:30`'da sözleşme olarak yazılı:
*"INV-05 fayda kapısı — çıktı kaynaktan en az `min_saving_ratio` kadar küçük
değilse ÇIKTI ATILIR, kaynak korunur."* Eşik `çıktı/kaynak ≤ 0,90`.

Ayrıca üst basamak kuralı: kaynaktan büyük genişlik **kayıt açmaz**
(`DALGA-A-DEVIR.md` D-1 düzeltmesi, (genişlik, biçim) kapısı).

## Gerekçe

- Merdivenin varlık sebebi bayt indirmek. Bayt indirmeyen bir basamak yalnız
  depolama, kota ve karmaşıklık ekler.
- Kapı **ölçülebilir ve tek yönlü**: "kazandı mı" sorusunun cevabı dosya
  boyutudur, tahmin değil.
- Görsel tarafta işe yaradığı ölçüldü: T-124 pilotunda 7 kaynak (9,99 MB) → 84
  türev **4,03 MB** — merdivenin tamamı kaynağın altında
  (`DALGA-A-DEVIR.md` T-124). Fayda kapısı büyütmeyi doğru eliyor
  (`docs/reports/15-dalga-a-dogrulama.md`).

## Sonuçlar

### Olumlu

- Depolama tarafında merdiven kaynaktan ucuz kalıyor (ölçüldü, yukarıda).
- `passthrough` sessiz değil: not düşülüyor ve raporda görünüyor.
- Video merdivenindeki bayt şişmesi kapının **tespitiyle** bulundu ve
  `rate_control: capped_crf`'e geçilerek düzeltildi (`video_decision.json:320-325`).

### Olumsuz — ölçüldü

**Kapı, video hattında bugün hiçbir transcode'u geçirmiyor (B-1).** Ölçüm
(`docs/reports/22-t072-vmaf-av1.md` §5.1): gerçek 1080p kaynak
**8.504.902 B = 1,169 Mbps**; boru hattı bunu 1280'e indirip **CRF 23** ile
yeniden kodluyor ve **2,04 Mbps** üretiyor — H.264 çıktısı kaynağın **1,760 katı**.
Kapı 0,90 istiyor.

Kök neden **kapı değil, hız denetimi**: hedef kalite kaynağın kendi kalitesinin
üstünde. Kapı burada doğru davranıyor (kötü çıktıyı atıyor) ama sonuç şu:
Faz 7'nin ürettiği tek dosya yolu üretimde **hiç çıktı vermiyor**.

Karar **gevşetilmedi**. `docs/reports/22-t072-vmaf-av1.md` §5.5 ek koşul olarak
yazıyor: *"Kapı gevşetilmez; AV1 çıktısı da kazandırmazsa atılır, kaynak
korunur"* ve *"Kapıyı kaliteyi düşürerek açmak, kriteri kurtarmak değil daha çok
bozmaktır."*

**Açık iş:** `targets.h264_primary.crf` sabit 23 yerine kaynağın bitrate'ine/bpp'sine
uyarlanmalı ya da capped-CRF eklenmeli. Aynı düzeltme HLS merdiveninde **zaten
yapıldı** (`video_decision.json` `hls.rate_control: capped_crf`), tek dosya yolunda
**yapılmadı**.

**Doğrulanmadı:** `max_bytes` türevlerde **yaptırımsız** — aşıldığında yalnız
`NOTE_OVERSIZE` notu düşülüyor, ret ya da yeniden kodlama yok
(`render.py:934`). Yani fayda kapısı (göreli) çalışıyor ama bayt tavanı (mutlak)
çalışmıyor; ikisi karıştırılmamalı. Bkz. ADR-0012.

## Geri dönüş yolu

INV-05 kapatılmaz. Kalite/VMAF eşiğini geçen zorunlu uyumluluk çıktısı kaynaktan
büyükse istisna yalnız karar tablosunda açıkça işaretlenir ve orijinal de
korunur. Böyle bir fixture yoksa kapıyı gevşeten değişiklik geri çevrilir.
