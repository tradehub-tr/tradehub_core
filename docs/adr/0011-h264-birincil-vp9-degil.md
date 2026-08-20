# ADR-0011 — Video birincil çıktısı H.264/MP4; VP9/WebM reddedildi

**Durum:** Kabul edildi · politika dosyasında yazılı · **üretimdeki hat henüz bu karara uymuyor**
**Tarih:** Faz 7 (`media/pipeline/policy/video_decision.json`)
**İlgili:** ADR-0007, ADR-0010

---

## Bağlam

Kaynak doküman H.264 istiyordu; bugünkü üretim hattı **VP9/WebM** üretiyor
(`media/transcode.py:357-360`, libvpx-vp9 + libopus). Fark bilinçli hale
getirilmesi gereken bir çelişkiydi.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — VP9/WebM (bugünkü hat) | Aynı kalitede **%20-30 daha küçük** dosya. Bedeli: Safari'de `<video>` ile güvenilir oynamıyor (macOS'ta kısmi, **iOS'ta yok**). |
| **B (SEÇİLEN)** — H.264/MP4 birincil | Her yerde oynar. Bedeli: aynı kalitede **~%20-30 daha büyük** dosya — bilinçli ödenen bedel. |
| C — İkisi birden (`mp4` birincil + `webm` ikincil `<source>`) | En iyisi. Bedeli: iki transcode. Tabloda `targets.webm_fallback` **yer tutucu** olarak var, `implemented: false` — Faz 7'de üretilmiyor. |

## Karar

`media/pipeline/policy/video_decision.json` → `targets.h264_primary`
(`max_width: 1280`, H.264 High + AAC 128k + faststart), gerekçesi
`why_h264_not_vp9` alanında **üç madde** olarak yazılı (:250-256):

> 1. **UYUMLULUK:** VP9/WebM Safari'de `<video>` ile güvenilir oynamıyor
>    (macOS'ta kısmi, iOS'ta yok). Ürün videosu B2B alıcının telefonunda oynamak
>    zorunda; **oynamayan bir video sıfır bayt tasarrufundan kötüdür.**
> 2. **YANLIŞ ETİKET:** bugünkü hat WebM baytlarını `.mp4` uzantılı **adrese**
>    yazıyor (`transcode.py:344` → `:366 os.replace`). nginx Content-Type'ı
>    uzantıdan türettiği için `video/mp4` başlığıyla WebM baytı servis ediliyor.
>    H.264/mp4 hedefi bu uyuşmazlığı kaynağında bitirir.
> 3. **BEDELİ:** aynı kalitede H.264, VP9'dan ~%20-30 daha büyük dosya üretir.
>    Bu bedel bilinçli ödeniyor.

Kural, karar tablosunda da tutarlı: `pix_fmt_not_web` kuralında *"vp9 de bu
kurala TAKILIR ve H.264'e döner"* (:129).

## Gerekçe

Bu, bu depodaki en net **"kullanılabilirlik > bayt"** kararıdır ve tek cümleye
indirgenmiş: *oynamayan bir video sıfır bayt tasarrufundan kötüdür.* Aynı cümle
sonradan AV1 kararının (ADR-0010 §5.7) ön koşulu olarak yeniden kullanıldı.

Yanlış etiket maddesi ayrıca ölçülebilir bir hata sınıfını kapatıyor: `.mp4`
adresine WebM baytı yazmak, byte-range ve `Content-Type` doğrulamasını
imkânsızlaştırıyordu (`docs/standards/company-cover-video.md` §11-D5 bunun
doğrulama komutunu veriyor).

## Sonuçlar

### Olumlu

- Karar ve gerekçesi **politika verisinde** duruyor, kodda değil — değiştirmek
  için kod okumak gerekmiyor.
- ADR-0010'un "AV1 birincil olmasın" sonucu doğrudan buradan türedi.

### Olumsuz / açık

- **Üretimdeki hat hâlâ VP9/WebM üretiyor.** Karar politika dosyasında yazılı ama
  `media/transcode.py` değiştirilmedi; yani bugün üretimde hem yanlış kodek hem
  yanlış etiket sürüyor. Bu ADR bir **hedef** kaydediyor, bir **gerçek** değil.
- Bedel (%20-30 daha büyük dosya) ADR-0007'nin fayda kapısını daha da zorlaştırıyor:
  H.264 çıktısı gerçek 1080p kaynakta kaynağın **1,760 katı**. Yani bu karar
  B-1'i **kolaylaştırmıyor**, zorlaştırıyor — ama kök neden yine hız denetimi.
- `webm_fallback` yer tutucu olarak duruyor (`implemented: false`); iki çıktılı
  çözüm **karara bağlanmadı**.
- **Doğrulanmadı:** Safari/iOS'ta VP9'un oynamadığı bu depoda **ölçülmedi**;
  gerekçe dış bilgiye dayanıyor. Aynı şekilde H.264'ün her yerde oynadığı da
  gerçek cihazda test edilmedi.
