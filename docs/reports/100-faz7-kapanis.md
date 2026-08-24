# 100 — Faz 7 Video Engine teknik kapanış raporu

**Tarih:** 2026-08-23  
**Kapsam:** T-070…T-075  
**Ortam:** `istoc/tradehub-backend:v15`, ffmpeg/ffprobe n8.1.2, Docker Desktop  
**Sonuç:** **6/6 görev teknik kabul kapısını geçti; Faz 7 kod açısından kapanabilir.**

Bu rapor, önceki denetimlerin açık bıraktığı maddeler kapatıldıktan sonra alınan
taze sonuçtur. `18-faz7-kapanis.md`, `39-t072-video-hatti.md`,
`57b-durum-faz4-7.md`, `61d-fe-denetim-faz6-7.md` ve
`84-w7-video-servis.md` tarihsel ölçüm kayıtlarıdır; güncel durum için bu rapor
ve `docs/closure/faz7-kapanis.md` esas alınır.

## 1. Görev sonuçları

| ID | Görev | Durum | Kapanış kanıtı |
|---|---|---:|---|
| T-070 | Video probe ve koruma | ✅ TAM | Tek izole ffprobe koşumunda kap/akış, etkin ve kodlanmış ölçüler, fps, bitrate, süre, başlangıç/ofsetler, kodek/profil/level, SAR/DAR, pixel/color/HDR, B-frame, ses ve rotation okunuyor. Sıfır süre, akış yokluğu, ayrıştırma/decode hatası ve kaynak sınırı ihlalleri kodlu ret oluyor. ffprobe 20 sn duvar, CPU, 512 MiB adres alanı, dosya/çıktı limitleri altında çalışıyor. |
| T-071 | Veri tabanlı karar zinciri | ✅ TAM | `video_decision.json` `active`; ilk eşleşen kural kazanan sıralı REJECT/TRANSCODE/REMUX/PASSTHROUGH tablosu koddan bağımsız yükleniyor. Her karar `rule_id`, `code`, insan-okur gerekçe ve `writes_new_file` taşıyor. Uygun MP4 kusurunda `-c copy +faststart` REMUX yolu var. |
| T-072 | H.264 transcode ve kalite kapıları | ✅ TAM | H.264 High/yuv420p/≤1280/≤30 fps + AAC 128k/48 kHz/stereo + faststart; HDR kaynakta BT.709 tone-map; iki kodlayıcı thread'i. INV-05, VMAF ≥93, süre farkı ≤100 ms, A/V başlangıç-bitiş sapması ≤100 ms ve ilk-kare kapısı promote öncesi uygulanıyor. Düşen çıktı siliniyor, kaynak korunuyor veya güvenli REMUX'a dönülüyor. İlerleme ve iptal callback'leri izole alt sürece bağlı. |
| T-073 | Poster, poster merdiveni ve önizleme | ✅ TAM | İlk anlamlı kare; parlaklık + kenar yoğunluğu kapısı, ikinci zaman penceresi ve WebP kalite merdiveni var. Ham poster görsel motorundan slot profilleri/crop intent ile geçiriliyor; en az bir kırpılmış teslim posteri oluşmadan yeni video sürümü promote edilmiyor. 6→4→3 sn, sessiz/döngülü, ≤1 MiB önizleme klibi manifest ve storefront'a bağlı. `prefers-reduced-motion` yalnız poster sunuyor; video/HLS/önizleme kaynaklarını boşaltıyor. |
| T-074 | Adaptif HLS teslimi | ✅ TAM | Süre >60 sn, en büyük türev >12 MiB veya >2 çözünürlük basamağından biri HLS'i tetikliyor. No-upscale 360p/480p/720p/1080p merdiveni, GOP/segment hizası, basamak fayda kapısı ve ilk-10-sn 1.280.000 B bütçesi var. Playlist kısa cache; içerik-adresli segment immutable. Native HLS → lazy hls.js → progresif MP4 sırası hem admin panelde hem storefront'ta testli. |
| T-075 | Regresyon ve kaynak bütçesi | ✅ TAM | Ayrı `media-video` kuyruğu tek worker ile eşzamanlılığı 1'e indiriyor; cgroup 2 CPU/1,5 GiB, alt süreç 1,25 GiB RSS watchdog + 4 GiB sanal adres tavanı altında. 65 sn gerçek 4K60 kabul koşumu bütün bütçe ve teslim kapılarını geçti. Günlük/manuel CI workflow'u hızlı kontrat suitini; PR dışı koşum uzun 4K60 benchmark'ını çalıştırıyor. |

## 2. Ölçümlü 4K60 kaynak kabulü

Koşum, fixture üretimi bittikten sonra aynı üretim H.264 yolunu
`--cpus=2 --memory=1536m --memory-swap=1536m` konteynerinde çalıştırdı.
VMAF korpus testi ayrı suitte bulunduğu için bu kaynak benchmark'ında VMAF
yeniden hesaplanmadı; INV-05 ve bütün teslim bütünlüğü kapıları uygulandı.

| Ölçü | Sonuç | Bütçe | Kullanım |
|---|---:|---:|---:|
| Kaynak | 3840×2160, 60 fps, 65,000 sn, 504.183.133 B | Tam 4K60, >60 sn | ✅ |
| Çıktı | 1280×720, 30 fps, 65,002 sn, 7.945.851 B | Teslim profili | ✅ |
| Duvar saati | 32,85 sn | ≤240 sn | %13,7 |
| CPU | 64,73 user + 0,72 system = 65,45 sn | ≤480 sn | %13,6 |
| Tepe RSS | 576.581.632 B (≈549,9 MiB) | ≤1.073.741.824 B | %53,7 |
| Bayt tasarrufu | %98,42 | INV-05 ≥%10 | ✅ |
| Süre farkı | 0,002 sn | ≤0,100 sn | ✅ |
| A/V sapması | 0,002 sn | ≤0,100 sn | ✅ |
| İlk kare luma | %49,53 | %1–%99 | ✅ |
| İzolasyon | RLIMIT_CPU, RLIMIT_AS, RLIMIT_FSIZE, RLIMIT_NOFILE, RLIMIT_CORE, RSS_WATCHDOG | CPU + bellek + dosya | ✅ |

Makine-okur ham sonuç: `docs/data/faz7-4k60-benchmark.json`.

## 3. Taze regresyon matrisi

| Katman | Koşum | Sonuç |
|---|---|---:|
| Üretim ffmpeg saf video/izolasyon | `test_isolation + test_video_phase7_closure + test_video_decision + test_video_transcode` | **220/220 OK**, 130,630 sn, 0 skip |
| Frappe video servis zinciri | `test_video_servis` | **28/28 OK** |
| Frappe üretim köprüsü | `test_pipeline_bridge` | **44/44 OK** |
| Frappe aktif-sürüm manifesti | `test_media_manifest_api` | **12/12 OK** |
| Eski/yeni worker uyumluluğu | `test_media_transcode` | **23/23 OK** |
| Storefront video/HLS/reduced-motion | Vitest, 3 dosya | **35/35 OK** |
| Storefront production bundle | `npx vite build` | **OK**; hls.js ayrı `vendor-hls-*` chunk |
| Admin panel native-HLS/hls.js/fallback | Node test, 2 dosya | **32/32 OK** |
| Admin panel karar/poster/srcset simülatörü | Node test, 4 dosya | **73/73 OK**; backend karar tablosuyla üretilmiş vendor verisi senkron |
| Admin panel production bundle | `npm run build` | **OK**; hls.js ayrı `hls-*` lazy chunk |
| Storefront TypeScript | `npx tsc --noEmit` | **OK** |
| Dağıtım yapılandırması | `docker compose config --quiet` | **OK** |

Faz 7 odaklı toplam ayrı test: **467**, başarısız: **0**, atlanan: **0**. Uzun 4K60
benchmark'ı bu sayıya dahil değildir ve ayrıca `passed: true` üretmiştir.
Yalnız backend deposunun checkout edildiği CI taşınabilirlik koşumunda 15 test
geçti; kardeş Docker çalışma ağacı bulunmadığı için iki dağıtım-dosyası kontrolü
beklendiği gibi skip oldu. Aynı iki kontrol tam workspace koşumunda mount edilen
gerçek gateway/Compose dosyalarıyla geçti ve yukarıdaki 220/220 sayısına dahildir.

Kapsam uyarısı: admin panelin tüm depo testi de çalıştırıldı; 1.272 testin
1.263'ü geçti, Faz 7 dışındaki **4 test başarısız**, 5 test skip oldu. Hatalar
ürün görseli crop/upload vendor senkronu, Faz 6 policy fixture senkronu ve
lojistik `LEGACY` stil listesiyle ilgilidir. T-070…T-075 koduna veya yukarıdaki
105/105 Faz 7 admin testine temas etmez; bu nedenle Faz 7 kapısını yeniden
açmaz, ancak depo genelinde “tamamı yeşil” iddiasında bulunulmamıştır.

## 4. Önceki açıkların kapanışı

| Eski bulgu | Güncel sonuç |
|---|---|
| Üretim ffmpeg'inde VMAF yok | n8.1.2 libvmaf'lı; VMAF <93 çıktı promote edilmeden atılıyor. Eşik ile INV-05 aynı anda tutmuyorsa doğru sonuç kaynak korumadır. |
| CPU/RAM/eşzamanlılık sınırı yok | İzole alt süreç CPU/AS/RSS limitli; `media-video` tek worker, 2 CPU ve 1,5 GiB cgroup altında. |
| Uzun 4K60 fixture/ölçüm yok | Deterministik 65 sn 4K60 manifest + ölçüm scripti + taze başarılı JSON raporu var. |
| HLS basamağı kaynaktan büyük ilan edilebiliyor | Basamak fayda kapısı master playlist'e ilanı engelliyor; hiç faydalı basamak yoksa progresif MP4 kalıyor. |
| Poster crop/srcset zincirine bağlı değil | Poster görsel merdiveninden crop intent ile geçiyor; aktif sürüm manifesti responsive posterleri taşıyor. |
| Önizleme ve reduced-motion teslimi yok | Preview rendition → manifest → storefront bağlı; reduced-motion poster-only. |
| hls.js ve cache kuralı yok | Admin panel ve storefront dinamik import kullanıyor; gateway playlist/segment cache ayrımı yapıyor. |
| Video slotu eski VP9 worker'ıyla yarışıyor | Faz 7 slotu sahiplenince miras worker no-op; kapsam dışında eski güvenlik ağı korunuyor. |

## 5. Teknik kapanış ile rollout ayrımı

Faz 7 için açık kod/otomasyon bloklayıcısı kalmadı. Canlıya alma yine normal
operasyon adımlarını gerektirir:

1. Backend/worker, gateway ve storefront imajlarını bu çalışma ağacından yeniden build/deploy etmek.
2. Site migration'ını çalıştırmak ve `media-video` worker'ının sağlıklı olduğunu gözlemek.
3. Medya motoru/rendition bayraklarını kontrollü açıp ilk üretim metriklerini izlemek.
4. Release/UAT kapsamında gerçek iOS Safari ve zayıf ağ profilinde oynatmayı elle doğrulamak.
5. Plane iş akışı insan QA imzası istiyorsa bu rapora dayanarak T-070…T-075'i **Done** durumuna geçirmek.

4. madde tarayıcı/cihaz release kabulüdür; engine görevlerinin kod kapanışını
geri açmaz. QA imza alanı resmî kapanış dosyasında bilinçli olarak boş bırakıldı.
