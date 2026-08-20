# Faz 2 Kapanış Dosyası — Medya Standartları

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-029 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Tüm slot standartları sabit + SRS v1.0 | Platform yöneticisi |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| Slot standart belgeleri | **KARŞILANDI** | 54 §4.2: `docs/standards/` altında 8 slot belgesi + logo.md (2 slot, 1.290+ satır) + company-cover-video.md (1.090+ satır) + retention.md 760 + kota.md 1.072 + migration.md 1.143 satır. |
| Şema doğrulaması | **KARŞILANDI** | jsonschema 4.25.1 / Draft202012Validator → **9/9 slot, TOPLAM HATA = 0** (16 §5.1, 33 §4.2, 54 §4.2). |
| SRS gövdesi | **KARŞILANDI (belge)** | `docs/srs/SRS-v1.0.md` **2.188 satır**, FR-001…FR-150 (150 benzersiz) + 52 NFR (33). |
| T-026/T-027 (retention, kota) | **KARŞILANDI** | test_retention_gc **38 OK**, test_media_quota **10 OK** (57a [T]). |
| G4 — 14 karar | **KARŞILANDI (beyan)** | 16 §1: G4 ✅ 14/14 — "kanıt belgenin kendi beyanıdır", imzalı blok yok. |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **"Tüm slot standartları SABİT" KARŞILANMADI (kesin)** — politika dosyalarında `active` = **0/9**, hepsi `draft`; `open_questions` toplam **49** (company-cover-video 8 · product-image 7 · 5 slotta 6'şar · seller-logo 3 · brand-logo 1); `encoder_quality` null **14** (16 §3, 54 §4.2, 57a; bugün bağımsız doğrulandı: 9/9 draft).
2. **SRS v1.0 ONAYSIZ** — SRS-v1.0.md satır 3: "**DURUM: HÂLÂ TASLAK (DRAFT). Onaylanmadı.**"; 53 `- [ ]` / 0 işaretli; `TBD` 18 satırda; §9.2 onay bloğunda ad/tarih/imza alanı yok (54 §5.5).
3. **7 geçiş kapısından 4'ü açık** (16 §1/§9.1): **G1 🟡** (kanonik set kararı yok: `policy/slots/` 9 dosya ↔ `docs/standards/policies/` 13 dosya — FR-147 tek-kaynak ihlali), **G3 ❌** (49 open_question, 0 CR-ID), **G5 ❌**, **G6 ❌ 0/9 active**, **G7 ❌ 7/9** (var olan 7'nin 5'inde eşik 80 MP → canlıda 0 dosya keser).
4. **content_rules eşikleri İNSAN ETİKETLEME BEKLİYOR** — 57a T-025 [Ö 22:28:51]: `calibration_status = TRIGGER_RATE_MEASURED_UNLABELED`; 1.291 Listing görselinde 6 kuralın tetiklenme oranı ölçüldü ama **eşikler değiştirilmedi** — "etiketsiz dağılımdan eşik türetmek, kalibrasyon değil kılık değiştirmiş tahmindir". `still_open[0]`: "Yanlış pozitif oranı hiçbir kural için hâlâ BİLİNMİYOR — insan etiketi üretilmedi." Ölçek: **~200 tetiklenmenin elle etiketlenmesi** (57a §6.2) → **İNSAN işi** (57 karar #3). Not: `extreme_blur` reject kuralı canlı ürün görsellerinin **%1,70'ini (22 dosya)** gizlerdi; rollout sözleşmesi FP < %1 istiyor (38 §6.3).
5. **G6'nın üç sistem engeli** (16 §2.3): FR-001 `slot_key` upload_policy.py'de **0 isabet**; FR-144 `max_megapixels_hard` 7/9; FR-149 `compliance_measured` 0/9.
6. **jsonschema konteynerde YOK** (`ModuleNotFoundError`) ve hiçbir requirements dosyasında değil → "CI'da koşar" kriteri bugünkü imajla sağlanamaz (54 §5.4).
7. **`seller.logo` aktivasyonu denendi ve GERİ ALINDI** — "SRS v1.0 ONAYLI YAPILMADI. Görev bunu istiyordu; ölçüm izin vermedi." (16 §8). İhlal oranı %31,6 (n=19) → FR-149 gereği `enforcement_mode = new_uploads_only` olurdu.
8. **İç çelişki çözülmedi**: SRS §6.2 "hiçbir politika active yapılamaz" ↔ G6 "en az biri active olmalı" (16 §2.3).
9. **K7 kota borcu** — rendition'lar kotadan sayılırsa kapak videosu başına ~6 nesne (~19 MB tipik) → satıcı kotası ~6 kat hızlı dolar; "Bu revizyonda yapılmadı" (16 §4.1). → **KARAR** (57 karar #2, ADR-0009 ile çelişki).
10. FE tarafı: T-024 DPI eşiği slot politikasında YOK; T-025 NSFW/blur/pHash FE'de 0 iz (61b).

## 4. Kapı durumu özeti

**Kapı: KARŞILANMADI.** Belgeler ve şema doğrulaması tam; ama kapının iki cümlesi de açık: hiçbir slot `active` değil (0/9) ve SRS taslak/onaysız. Kapanış üç şeye bağlı: içerik kuralı etiketlemesi (İNSAN), kanonik politika seti + K7 kararları (KARAR), G6/G7 alan tamamlama (AJAN işi).

## 5. Kaynak raporlar
`docs/reports/`: 16-t029-politika-aktivasyonu.md (+§9 eki) · 54-d1-faz0-2-kapanis.md §4–5 · 57a-durum-faz0-3.md §4 · 33-dogrulama-faz0-3.md §4 · 38-t017-guvenlik-kapisi.md §6.3 · 61b-fe-denetim-faz2-3.md · `docs/srs/SRS-v1.0.md` · `docs/standards/`

Doküman eşitlemesi yapıldı: 2026-08-20, rapor 88 (SRS G5 kapı koşulundaki "yanlış şeyi ölçme" kusuru işaretlendi; izlenebilirlik matrisi yeniden üretildi).

## Ek ölçüm — 2026-08-20 (W8, rapor 94)

- **§3.10'un FE yarısı (T-020/T-023 "yalnız ön-kontrol alanları vendor'landı") → FİİLEN KAPANDI:** `admin-panel/.../policy/vendor/slot_policies.js` **9/9 slotun HAM kopyası** (master/quality/profiles/content_rules/messages dahil; 4.683 satır). Vendor sha256 zinciri bu koşumda bağımsız yeniden hesaplandı: **16/16 uyuşuyor**; `npm run parity:policy` bugün **22/22** (393 Python-üretimli vektör). FE'deki politika artık backend'in birebir, bugünkü kopyası (rapor 94 §6).
- **§3.6 (jsonschema konteynerde yok) → KAPANDI:** jsonschema **4.26.0** konteynerde; `Draft202012Validator` ile 9/9 slot konteyner İÇİNDE doğrulandı, **toplam hata 0**.
- **T-025 ARAÇ yarısı gevşedi:** tesseract 5.3.0 (tur dahil) + pytesseract 0.3.13 artık kurulu → `overlay_text` ölçülebilir; İNSAN etiketleme engeli (§3.4) aynen sürüyor.
- **§3.1 ("SABİT" kapısı) → DEĞİŞMEDİ:** bugün sayıldı — 9/9 politika `draft`, açık soru toplamı **49**. Not: `Media Engine Settings.active_slots = product.image, product.video` boru hattı aktivasyonudur, politika statüsü DEĞİLDİR; G6 kapısıyla karıştırılmamalı.

## 6. Onay

```
Onaylayan (Platform yöneticisi): ______________________   Tarih: ______________   İmza: ______________
```
