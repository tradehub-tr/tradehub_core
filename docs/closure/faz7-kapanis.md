# Faz 7 Kapanış Dosyası — Video Engine

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-075 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Video regresyonu GREEN + kaynak bütçesi | QA |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| Video regresyonu | **GREEN — KARŞILANDI** | 18-faz7-kapanis.md §2.1: 147 test 0 hata; §10-A yeniden koşum: **167 test OK**; 57b §0.1: transcode 109 + decision 58 + media_transcode 22 + retry 39 = **208 test, 0 başarısız** (43'ü gerçek ffmpeg). |
| INV-05 fayda kapısı | **KARŞILANDI** | 18 K-3: 4 gerçek adayda çıktı %99,6–%170,4 → 4/4 RED, "diske tek bayt şişme yazılmadı". Capped-CRF sonrası 2 aday kapıyı geçti, net +2.676.734 B (39 §1). |
| Kaynak tavanları belge + gerçek kütüphane karşılaştırması | **KARŞILANDI (ölçüm)** | 18 §4: tavanlar (1280 genişlik, 2,5 Mbps, ffprobe 20 s, ffmpeg 1700 s); kütüphane maks 1080p/540 s → iki REJECT tavanı "ölü kural" (0 dosya). Duvar saatleri: REMUX 0,07 s · TRANSCODE 15,17 s · HLS 3 basamak 295,78 s (tavanın %17'si). |
| Süre farkı ≤100 ms | **KARŞILANDI** | 39 §5: r2 0,000 s · r3 0,001 s · r6 0,000 s — hepsi GEÇTİ. |
| Mobil ilk-10-sn veri tavanı | **KARŞILANDI** | 39 §6.1: tavan 1.280.000 B; 360p 161.841 · 480p 173.121 · 720p 275.581 B (<%21). |
| HLS + gerçek tarayıcı oynatma | **KARŞILANDI** | 18 §6: 9mb.mp4 → 405 segment / 27.301.091 B; 39 §7: hls.js + HeadlessChrome 151, MANIFEST_PARSED 3 seviye, readyState=4, 53 fragman. Uyarı: `bufferSeekOverHole` kök nedeni teşhis edilmedi. |
| Poster/klip | **KARŞILANDI (1 gerçek ihlalle)** | 39 §8.1: 7/7 poster (luma 13,9–60,5), 7/7 sessiz klip <1 MB. AÇIK: r3 posteri 155.792 B > 122.880 B kapısı (merdiven q40'ta 122.836 B — uzatma kararı PO'da). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK) — "kaynak bütçesi" yarısı ve karar

1. **FAZ 7 KAPANMIYOR — tek sebep B-6/VMAF kararı** (18 §1.1 + §10-A). Üretim imajında `libvmaf` **yok** (ffmpeg 5.1.9, `grep -c libvmaf` → 0). Dış imajla ölçüm (22): 7 sentetik fixture'da 6/7 ≥93; **ama** gerçek 1080p r2'de (39 §4.2) fayda kapısı bütçesinde en iyi VMAF **≈86–89**; VMAF 92,11 için +%20,5 şişme gerekiyor → "**VMAF ≥93 ile INV-05 fayda kapısı bu dosyada AYNI ANDA SAĞLANAMAZ**". Üç seçenek (57b §5): eşiği gerçek korpustan türet (≥85) / INV-05 istisnası yaz / kapsamı şişik fixture'lara daralt. → **KARAR** (57 karar #1). Karar ne olursa olsun imaj rebuild'siz ölçülemez.
2. **İşçi kaynak bütçesi kısmi** — yalnız `nice -n 10`; **CPU kotası/cgroup YOK, bellek bütçesi YOK (RLIMIT 0 sonuç), eşzamanlı transcode tavanı YOK** (57b T-075(3)). ffprobe timeout 20 s var, bellek limiti yok (T-070(3)).
3. **4K60 uzun fixture YOK** — en büyük fixture 1080p 1.131.368 B; 4K yalnız sentetik karar-tablosu testinde reddediliyor; en kötü hâl HLS ~493 s projeksiyon, "kanıt değil" (18 B-5, 57b T-075(4)).
4. **B-8 kodek çelişkisi** — `contracts/video.py:175-176` VP9/WebM donduruyor, `delivery/manifest.py:67` WebM'i birincil sunuyor, kod H.264/MP4 üretiyor — "uçtan uca teslimi bloklar" (18 §8; 14-nihai-denetim B3).
5. **Yeni B-3 (39 §6.3)**: HLS merdiveninde fayda kapısı yok — 720p basamağı kaynaktan **+%25,7** büyük. "Düzeltilmedi, kayda geçirildi."
6. **B-3 (eski)**: `video_decision.json` ve 3 slot politikası `status: "draft"` (18 §10-A).
7. **Hiç ölçülmeyenler**: HDR→SDR tone-map (0 sonuç), lip-sync/A-V drift, Safari/iOS yerli HLS, ABR basamak geçişi, poster↔crop intent (T-073/3, 0 sonuç), `prefers-reduced-motion` teslimi (şema alanları var, Python teslim yok).
8. **FE tarafı**: gerçek poster hiçbir FE yüzeyine ulaşmıyor; hls.js bilinçli eklenmedi; `.m3u8` çağıran yok (61d). `.m3u8`/segment için Cache-Control ataması 0 sonuç; gateway map'i HLS segment adlarını tanımıyor (57b T-074(2)).

## 4. Kapı durumu özeti

**Kapı: YARISI KARŞILANDI.** "Video regresyonu GREEN" defalarca kanıtlı (147→167→208 test, 0 başarısız). "Kaynak bütçesi": tavanlar yazılı ve gerçek kütüphaneyle karşılaştırıldı, ama bellek/CPU/eşzamanlılık sınırı yok ve 4K60 fixture yok. Fazın kapanışı "artık teknik bir eksiğe değil, bir karara bağlı" (18 §10-A) — VMAF↔INV-05 kararı + imaj rebuild.

## 5. Kaynak raporlar
`docs/reports/`: 18-faz7-kapanis.md (+§10-A) · 39-t072-video-hatti.md · 57b-durum-faz4-7.md · 22-t072-vmaf-av1.md (B-6 "kapandı" iddiası §10-A ile geçersiz) · 34-dogrulama-faz4-7.md · 61d-fe-denetim-faz6-7.md

## 6. Onay

```
Onaylayan (QA): ______________________   Tarih: ______________   İmza: ______________
```
