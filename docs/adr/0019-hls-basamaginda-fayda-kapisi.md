# ADR-0019 — HLS basamaklarına fayda/bütçe kapısı konur

**Durum:** KABUL (kararlaştırıldı, 2026-08-20) · uygulama W7-1'de koşuyor
**Tarih:** 2026-08-20 · **Yazan:** W7 doküman eşitlemesi (rapor 88)

## Bağlam

Tek dosya video yolunda fayda kapısı (INV-05, ADR-0007) ve kaynak bitrate'inden
türetilen `rate_ceiling_kbps` var; **HLS basamaklarında ikisi de yok** —
`hls._rate_control_args` yalnız tablodaki sabit `maxrate`'i kullanıyor.
Ölçülmüş sonuç (`81-w6-video-kosum.md` §4, kaynak: 142 kbps'lik çok verimli
`9mb.mp4`):

| Basamak | Bayt | Kaynağa oranı |
|---|---:|---|
| 360p | 7.299.637 | 0,76× |
| 480p | 7.905.561 | 0,82× |
| **720p** | **12.095.893** | **1,26× — kaynaktan BÜYÜK** |
| Paket toplamı | 27.301.091 | **2,84×** |

Aynı kusur daha önce rapor 39'da da ölçülmüştü ("720p basamağı kaynaktan
%25,7 büyük çıkabiliyor" — `56-d3-faz6-10-kapanis.md` §4.5 "yeni B-3", AÇIK).
`test_720p_basamagi_kaynaktan_buyuk_cikti_kaydi` durumu kayda sabitliyor.

## Seçenekler

| # | Seçenek | Not |
|---|---|---|
| A | Hiçbir şey yapma — merdivenin amacı bant genişliği sınıfları, bayt tasarrufu değil | Ölçülen bedel: 2,84× paket şişmesi; kaynaktan BÜYÜK basamak ilan etmek izleyiciye de zarar (aynı bant genişliğinde daha kötü seçenek) |
| B | **Basamak başına tavan: `rate_ceiling_kbps` mantığını (kaynak bitrate'inden türetilen tavan) HLS basamaklarına da uygula; kaynaktan büyük çıkan basamağı İLAN ETME** | **SEÇİLDİ** — tek dosya yolundaki kanıtlanmış desenin genellenmesi |
| C | Paket toplamına bütçe (örn. ≤ N× kaynak) | Basamak-başına kapıdan türetilebilir; tek başına hangi basamağın atılacağını söylemez |

## Karar

HLS basamakları da fayda kapısından geçer: basamağın hız tavanı kaynak
bitrate'ine göre sınırlanır ve kaynaktan büyük çıktı üreten basamak master
playlist'te ilan edilmez (no_upscale'in bayt karşılığı). Uygulama ve ölçümleri
W7-1 koşumunda (raporu W7 serisinde).

## Gerekçe

- İki bağımsız koşumda ölçüldü (rapor 39, rapor 81 §4).
- Tek dosya yolu aynı deseni zaten kullanıyor ve fayda kapısı ilk gerçek
  koşumda tuttu (%11,44 ≥ %10 — rapor 81 §3 halka 3): desen kanıtlı.

## Sonuçlar

**Olumlu:** verimli kaynaklarda paket şişmesi biter; izleyiciye kaynaktan
kötü basamak sunulmaz.
**Olumsuz / bedel:** çok verimli kaynaklarda merdiven 1-2 basamağa inebilir,
hatta hiç HLS üretilmeyebilir — bant genişliği sınıfı çeşitliliği azalır.
Bu bilinçli: kaynağın kendisi zaten o sınıfların işini görüyor.

## Kanıt

`docs/reports/81-w6-video-kosum.md` §4 · `docs/reports/56-d3-faz6-10-kapanis.md`
§4.5 · `media/pipeline/video/hls.py` (`_rate_control_args`) · ADR-0007.

## Geri dönüş yolu

Kapı nedeniyle desteklenen bağlantı sınıfında oynatılabilir tek basamak dahi
kalmıyorsa ilgili rung bütçesi yeniden ölçülür; büyük basamak yayınlanmaz.
Politika değişikliği hata üretirse eski JSON sürümü etkinleştirilir ve kaynak
MP4 fallback korunur.
