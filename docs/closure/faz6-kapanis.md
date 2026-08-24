# Faz 6 Kapanış Dosyası — Image Engine

> Tarih: 2026-08-23 · Kaynak: `docs/50-faz6-image-engine.html` · Ayrıntılı kanıt: `docs/reports/60-faz6-kapanis.md`

## Kapı kararı

**GREEN — 8/8 görev tamamlandı; kısmi veya açık kabul maddesi kalmadı.**

Normalize edilmiş tek master üretim köprüsüne bağlandı; sınıflandırma kararı aynı
master'dan version metadata'sına, rendition üretimine ve kalite raporuna taşınıyor.
Animasyonlar görsel encoder'a girmeden gerçek `video_from_animation` işiyle
MP4/H264, WebM/VP9 ve PNG poster üretiyor. Lazy rendition, tekil kilit,
idempotent reprocess, kontrollü toplu işçi, aylık kalite raporu ve golden CI
kapıları uçtan uca doğrulandı.

## Görev özeti

| ID | Durum | Tamamlanan kabul kanıtı |
|---|---|---|
| T-060 | **DONE · %100** | Decode öncesi probe/guard ve 30 MB giriş bütçesi |
| T-061 | **DONE · %100** | Sıralı pyvips normalize; ΔE00 ort. 0,3976/en kötü 1,1722; 72 MP peak RSS 349.278.208 B `< 500 MiB` |
| T-062 | **DONE · %100** | 100/100 sınıflandırma; `document` ayrımı; GIF → MP4/H264 + WebM/VP9 + PNG poster |
| T-063 | **DONE · %100** | Gerçek lazy üretim, Redis singleflight ve production bridge'de 34 gerçek rendition 6,95 sn `< 12 sn` |
| T-064 | **DONE · %100** | Tam merdivenin atomik promote'u, exact-output ledger, ikinci koşumda 0 encode/0 yeni asset ve kontrollü bulk worker |
| T-065 | **DONE · %100** | Deterministik LQIP/dominant renk; version → manifest → iki frontend placeholder akışı |
| T-066 | **DONE · %100** | Kalıcı asset raporu; aylık GB/LCP/hata oranı/worst-20; DocType + Markdown + scheduler + metrikler |
| T-067 | **DONE · %100** | 57/57 fixture, INV-01…INV-12, 131 perceptual çıktı, deterministik ZIP ve PR/nightly CI `< 10 dk` kapısı |

## Son doğrulama özeti

| Koşum | Sonuç |
|---|---:|
| Faz 6 ana Python paketi | **464 test OK** |
| Golden paket | **19 test OK** |
| Son performans/regresyon seçkisi | **52 test OK** |
| Frappe pipeline bridge | **44/44 OK** |
| Promote/idempotency | **14/14 OK** |
| Kalite raporu DocType + yetki | **6/6 OK** |
| Linux container normalize/master/animation | **53/53 OK** |
| Storefront + admin LCP bağlama | **6/6 OK** |

Platforma özgü koşullarda raporlanan skip'ler yalnız karşı platformda çalışan
Linux RSS semantiği veya isteğe bağlı yerel codec/libvips yokluğu içindir.
Linux production container koşumları gerçek libvips ve ffmpeg ile ayrıca
başarılıdır; kabul kapısı skip ile karşılanmamıştır.

## Scheduler sözleşmesi

`hooks.py` her ayın ilk günü 02:13'te
`tradehub_core.media.pipeline.image.report.run_previous_month_report` çağırır.
İş, kapanmış önceki ayın kalıcı asset raporlarını sürüm başına teke indirir;
aynı dönemin tüm terminal image işlerini doğru paydada toplar; başarısız işleri,
ölçülmüş LCP etkisini, GB tasarrufunu ve deterministik worst-20 listesini tek
aylık DocType ile site-private Markdown'a yazar. `period_key` aynı ayın yeniden
çalıştırılmasını idempotent yapar.

## Otomatik QA onayı

```text
Durum: GREEN   Tamamlanma: %100   Açık görev: 0   Tarih: 2026-08-23
```
