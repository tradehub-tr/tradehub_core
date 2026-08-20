# ADR-0010 — AV1 şimdi eklenmiyor

**Durum:** Kabul edildi (öneri düzeyinde; kodda değişiklik yapılmadı) · **sayısal tetikle yeniden açılır**
**Tarih:** 2026-08-19 (T-072 / T-016)
**İlgili:** ADR-0007 (fayda kapısı), ADR-0011 (H.264 birincil)

---

## Bağlam

Faz 7'nin tek bloklayıcısı B-1: fayda kapısı (ADR-0007) hiçbir video
transcode'unu geçirmiyor. AV1'in bunu çözeceği umuluyordu — Faz 1'de tek dosyada
VP9'a göre %40 küçük çıktı görülmüştü ama **kalite eşitlenmemişti**, yani karar
için yeterli değildi (`docs/reports/11-faz1-arge.md` §T-016.3).

Bu oturumda VMAF aracı getirildi ve ölçüm **aynı VMAF'ta** yapıldı: 7 fixture ×
(1 H.264 çapa + 5 AV1 CRF) = **42 koşum**, artı gerçek içerik.

## Seçenekler

| Seçenek | Sonuç |
|---|---|
| A — AV1'i şimdi ekle, birincil çıktı yap | En küçük dosya. Bedeli: Safari/iOS oynatma **hiç ölçülmedi**; üretimdeki SVT-AV1 v1.4.1 SIMD'siz. |
| B — AV1'i şimdi ekle, **ikincil** `<source>` olarak | Oynatma riski yok. Bedeli: B-1'i çözmüyor (aşağıda) ve iki çıktı üretme maliyeti. |
| **C (SEÇİLEN)** — **Şimdi ekleme.** Önce hız denetimini (B-1) düzelt; AV1'i sayısal bir tetikle yeniden değerlendir | Yanlış sorunu çözen bir kodek eklenmemiş olur. Bedeli: ölçülmüş %31,7'lik verim bugün tahsil edilmiyor. |

## Karar

> ## AV1 ŞİMDİ EKLENMESİN.
> Gerekçe tek cümle: AV1'in çözmesi beklenen sorunu (B-1) **ölçüm sonucuna göre
> çözmüyor**; çözdüğü sanılan yer sentetik fixture'ın yanılttığı yerdi.
> (`docs/reports/22-t072-vmaf-av1.md` §5.4)

## Gerekçe — ölçülen sayılar

**AV1 gerçekten daha verimli:** gerçek içerikte, aynı VMAF'ta AV1 çıktısı
H.264'ten **%31,7 küçük (0,683×)** — literatürdeki ~%30 ile uyumlu ve burada
**ölçülmüş**.

**Ama bu kütüphanede yetmiyor:** aynı dosyada H.264 çıktısı kaynağın **1,760
katı**. %31,7'lik kesinti onu **1,202 kata** indiriyor — kapının istediği
**0,90**'ın hâlâ çok üstünde.

| Ölçüt | Değer |
|---|---:|
| Kapının açılması için gereken AV1/H.264 oranı (bu dosyada) | **0,511** |
| Ölçülen AV1/H.264 oranı | **0,683** |

Aradaki fark **bir kodek seçimiyle kapatılamaz**. Kök neden kodek değil **hız
denetimi**: kaynak 1,169 Mbps, boru hattı CRF 23 ile **2,04 Mbps** üretiyor —
hedef kalite kaynağın kendi kalitesinin üstünde.

Sınıf bazında (§5.2): AV1 yalnız "kaynak küçültülüyor" sınıfında ve orada da
**sentetikte evet, gerçekte hayır**. "Kaynak zaten verimli" sınıfında AV1
H.264'ten **daha büyük** (1,23×–1,36×) — çünkü x264'ün kendi yapaylıklarını
yeniden üretmek için bit harcamak zorunda.

**"AV1 yavaştır" bu araç zincirinde doğru değil** (§5.3, 3 tur × 2 bağımsız
koşum, min süreden okundu): SVT-AV1 v4.2.0 ile preset 6'da **~1,6×**, preset 8'de
**neredeyse eşit**, preset 10'da **H.264'ten hızlı**. Süre bloklayıcı değil —
**ama bu v4.2.0 içindir**; üretimde **v1.4.1** var.

## Sonuçlar

### Olumlu

- Yanlış sorunu çözen bir kodek üretim hattına girmedi.
- **Sayısal tetik yazıldı** (§5.5), yani karar mekanik olarak yeniden açılabilir:

  ```
  (AV1/H.264 oranı) × (H.264 çıktı / kaynak)  ≤  0,90
  ```

  > **TETİK:** AV1 ikinci denemesi YALNIZ şu koşulda koşulsun —
  > `width > max_width` **VE** H.264 çıktısı kaynağın **1,04 katından** küçük.

  1,04 muhafazakâr sınırdır (kötümser sentetik ölçümden gelir); gerçek içerikte
  ölçülen sınır 1,32, aradaki fark ölçülmemiş içeriğe karşı emniyet payıdır.
  Tetik iki veri noktasında da doğru bildi (sentetik: 0,944 → AV1 kapıyı açtı;
  gerçek: 1,760 → açmadı). Yanlış pozitif/negatif yok.

- Bu karar **motor kodunda hiçbir değişiklik gerektirmiyor** (§6.3).

### Olumsuz / açık

- Ölçülmüş %31,7'lik verim bugün kullanılmıyor.
- **Ön koşullar kapatılmadı** (§5.6): (a) ffmpeg/SVT-AV1 yükseltmesi — bu
  belgedeki kazançlar **v4.2.0** ile ölçüldü, üretimde **v1.4.1** var, bugünkü
  üretim ffmpeg'iyle bu kazançlar **elde edilemez**; (b) AV1 oynatma **hiçbir
  tarayıcıda denenmedi** (ADR-0011'in gerekçesi AV1 için de geçerli ve bu belge
  onu ölçmedi); (c) gerçek içerikte **n=1** — ölçüm en az 3 gerçek 1080p video
  ile tekrarlanmalı.
- AV1 eklenirse **birincil çıktı olmasın**: `mp4/H.264` birincil kalır, AV1
  ikincil `<source>` olur (§5.7).
- Sıra bağlıdır: önce B-1 (hız denetimi), sonra `width_over_cap` kuralının gözden
  geçirilmesi, sonra B-8 (H.264 ↔ VP9 çelişkisi), **sonra** AV1.
