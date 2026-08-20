# Faz 0 Kapanış Dosyası — Keşif

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-009 hazırlığı — imza İNSAN işidir, bu belge imza atmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| 7 keşif raporu + fixture korpusu + açık soru listesi | Platform yöneticisi |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| 7 keşif raporu | **KARŞILANDI** | 07-faz0-kapanis.md §1.1: Dalga 1–2'de 7 rapor (00, 00-slot, 01, 02, 03-render, 04, 06); Dalga 3 ile toplam **12 rapor + kapanış, ~8.150 satır**. §9.2: "10 görevin 10'u üretildi". |
| Fixture korpusu (görsel) | **KARŞILANDI** | 57a-durum-faz0-3.md [Ö 22:35:52]: `images` = **34** (≥30 şartı), `malicious` = **10**, `manifest.json` **51 kayıt — 51/51 expect↔ölçülen GEÇTİ** (07 §1.2), toplam **66 MB** < 1 GB. |
| Fixture korpusu (video) | **KARŞILANMADI** | 57a + 33-dogrulama-faz0-3.md §2: `video` = **7**, şart ≥8. |
| Açık soru listesi | **KARŞILANDI (liste)** / **atama boş** | 07 §2: Ç-1…Ç-18 çelişki listesi; §4 açık sorular; K-1…K-25; AS-01…AS-32. Atama/bilgilendirme alanları boş: 54-d1-faz0-2-kapanis.md §2.3 — §10.6'da **10 boş alan**. |
| Güvenlik kapısı (megapiksel bombası) | **KARŞILANDI (kapı)** / eşik ölü | 54 §2.1 K-25: `bomb_100mp.png` iki yolda da RED; ama `max_megapixels_hard` yalnız **7/9** slotta, 5'inde eşik **80 MP** → canlıdaki en büyük görsel 72,71 MP olduğundan "**kapı VAR, eşik ÖLÜ**". |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **K-1 KVKK/PII sınıflandırması** — **40 public dosya** sınıflandırılmadı; `_is_protected_pii=True` **0/40 ve 0/4.426** (54 §2.1). "DARALTILDI, KAPANMADI". → **İNSAN kararı** (57-durum-anlik-goruntu.md karar #8).
2. **Video fixture 7/8** — 1 video eksik (57a T-006).
3. **Korpus tamamı sentetik** — "gerçek fotoğraf içermiyor… content_rules eşikleri bu korpusla kalibre edilemez" (07 §1.2, AS-27).
4. **T-003 makine-okunur çıktı yok** — `fixtures/media-stats.csv` bulunamadı; ham çıktı `10-media-stats-kosum-ciktisi.txt` (2.853 dosya) var (57a T-003).
5. **T-004 mobil profil** — 62-olcum-borcu §T-004 ile Lighthouse ölçümü KISMEN kapandı (12 koşum, yalnız desktop): `/` LCP 1354 ms ✅ · products 6352 ms ❌ · categories CLS 0,5396 ❌. **2 cihaz profili şartı hâlâ karşılanmıyor; INP lab'da ölçülemez.**
6. **T-007 tekrarlanabilirlik** — `pyvips` konteynerde kurulu değil (`ModuleNotFoundError`, 57a [Ö 22:38:24]); ham veri `bench.csv` 360 koşum / 0 hata mevcut.
7. **K-3 üretimde ffmpeg** — ÖLÇÜLMEDİ (üretim erişimi yok, 54 §2.1).
8. **G-2 versiyonlama gerilemesi** — `docs/reports/` 19 tracked / 34 untracked; toplam **105 untracked** (54 §2.1).
9. **Raporlar arası 18 çelişki** (Ç-1…Ç-18) kayıtlı; 07 §9.4: "39 kalemin 10'u tam, 8 kısmi, 21 açık".

## 4. Kapı durumu özeti

**Kapı: KISMEN KARŞILANDI.** Raporlar ve açık soru listesi var; fixture korpusu görselde tam, videoda 1 eksik. İmzayı bloke eden iki gerçek engel (54 §2.4): **K-1 (40 dosyanın insan sınıflandırması)** ve **K-3 (üretim erişimi)**.

## 5. Kaynak raporlar
`docs/reports/`: 07-faz0-kapanis.md (Rev.2 + §12 eki) · 54-d1-faz0-2-kapanis.md · 57a-durum-faz0-3.md · 33-dogrulama-faz0-3.md · 62-olcum-borcu-t105-t124-t004.md (T-004) · 61a-fe-denetim-faz0-1.md · 03-performans-taban-cizgisi.md · 05-fixture-korpusu.md · bench.csv

## Ek ölçüm — 2026-08-20 (W8, rapor 94)

§3'teki açık kalemlerin dördü bugün yeniden ölçüldü; ikisi fiilen kapandı:

- **§3.4 (T-003 makine-okunur çıktı) → KAPANDI:** boru-hattı-SONRASI güncel istatistik üretildi — tabFile **5.084** / 1,637 GB; Media Rendition **92** (26,85 MB, SSIM'li); türev adreslerinin 92/92'si version_hash'li (INV-09 canlı). Çıktı: `docs/reports/media-stats-2026-08-20.csv` + rapor 02'ye ek bölüm. (Yol adı sapması sürüyor: kök `fixtures/` yok, çıktı `docs/reports/` altında.)
- **§3.5 (T-004 "INP lab'da ölçülemez") → ENGEL AŞILDI:** RUM artık canlı; headless Chrome ile gerçek etkileşim üretildi → **İLK INP örneği DB'de: 8,0 ms (good), route `/urunler`**, kayıt `q961va8br3`, 11:41:27 (rapor 94 §2). Mobil profil şartı hâlâ açık.
- **§3.6 (T-007 tekrarlanabilirlik) → BÜYÜK ÖLÇÜDE KAPANDI:** konteyner bugün ffmpeg **n8.1.2 + libvmaf (skor üretildi)**, tesseract 5.3.0, boto3 1.34.162, jsonschema 4.26.0 (9/9 slot 0 hata konteyner içinde) taşıyor. Yalnız `pyvips` hâlâ yok — ADR-0008 ("Pillow'da kal") gereği karar-engeli değil, tekrarlanabilirlik borcu.
- **§2 video fixture 7/8 → DEĞİŞMEDİ** (bugün sayıldı: video 7 · görsel 34 · malicious 10 · manifest 51 · 65 MB). Yeni tür: gerçek-koşum fixture'ları (`live-probe.json`, `w6-video-live-run.json`) korpusta. Eksik tür listesi (sentetik üretilmedi): rapor 94 §3.

İmza engelleri (K-1 insan sınıflandırması, K-3 üretim erişimi) değişmedi.

## 6. Onay

Bu dosya imza için hazırlanmıştır; §3'teki açık kalemler bilinerek imzalanmalıdır.

```
Onaylayan (Platform yöneticisi): ______________________   Tarih: ______________   İmza: ______________
```
