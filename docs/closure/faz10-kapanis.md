# Faz 10 Kapanış Dosyası — Crop Studio

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-105 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Crop doğruluk raporu (UI ↔ backend eşleşmesi) | QA |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| UI↔backend piksel parite ölçümü VAR | **KARŞILANDI** | `cropPixelParity.test.js` **600 vaka / 5 sınıf**; zincir gerçek `useCropStudio` → gerçek `core/crop.py`; crop.py sha256 gömülü, bayat fixture ölçümü GEÇERSİZ kılar (47 §3.1). |
| Geometri paritesi TS↔Python | **KARŞILANDI — 0 px** | 592 vektör (584 değer + 8 hata), en büyük sapma **0 px**; çapraz 1,8e-12 px; `npm run parity:crop` **72/72** (strip-types'sız da 72/72) (47 §1, 57c §0.5). |
| Sınıf B (zoom) düzeltmesi | **KARŞILANDI (08-20)** | 65 §4: `zoom/center_x/center_y` alanları eklendi (decimal(21,6), ZOOM 1..16), vektör üretecine `payload_to_intent()`; **B: 119 sapan/7391 px → 3 sapan/1 px**. (56 §6.2 eski BEKLENEN.B'nin var olmayan yolu ölçtüğünü belgeledi.) |
| Kayıt yolu sözleşmesi | **KARŞILANDI** | 41 §6.4: `save_intent` idempotent (DB satır=1); focal_x=1.4 → 417 (INV-10); cross-tenant → var olmayan varlıkla aynı 417; `suggest_focal` 30. çağrıda 429. 75 S4: canlı round-trip 200 + aynı geometri. |
| Güncel parite tablosu | — | **A 5/120 sapan, 1 px** (yuvarlama: floor(v+0.5) ↔ banker's) · **B 3/120, 1 px** · **C 104/120, 3704 px** (bilinçli: sunucu oran zorluyor) · **D 7/120, 1 px** · **E 86/120, 3481 px** (bilinçli: panel taban bölge) — 65 §4. |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **C/E ayrışması ÜRÜN KARARI bekliyor** — C sınıfında 101/104, E'de 79/86 vakada panel kutusunun oranı profile hiç uymuyor; "ayrışmanın maliyeti kullanıcının yanlış bilgilendirilmesidir" — 56 §6.7 üç seçenek, önerilen: CropPreviewStrip sunucunun kutusunu çizsin. → **KARAR** (57 karar #4).
2. **A/D 1 px yuvarlama birleştirmesi** açık (crop_geometry.py ↔ core/crop.py) (56 §6.6).
3. **20 gerçek görselde elle karşılaştırma raporu YOK** (35 §3, 56 §6.4, 57c) — hiçbir 08-20 raporu üretmedi. → İNSAN/QA işi.
4. **Piksel karşılaştırması kutuyu ölçüyor, render edilen GÖRÜNTÜYÜ değil** — "cropPixelParity kutuyu karşılaştırır, görüntüyü değil" (47 §7). Ön koşul kalktı (gerçek rendition'lar artık var, 73/66) — görüntü düzeyi karşılaştırma artık yapılabilir ve hâlâ yapılmadı.
5. **Crop kaydı ürün UI'sından ulaşılamıyor** — 75 Bulgu 3: `MediaLibraryView.vue` `CropStudioModal`'a `:asset` GEÇMİYOR → Uygula kalıcı disabled, `save_intent` bu ekrandan hiç çağrılamaz. (Sunucu yarısı çalışıyor.)
6. **TS ikizi kapısı konteynerde kırmızı/sessiz** — Node v20.19.2 (65 §6: konteynerde hâlâ kırmızı; yerel 37/37). → ARAÇ (imaj rebuild).
7. **Etkileşim performansı (60 fps / 16 ms) ÖLÇÜLMEDİ** (47 §7, 48 §0, 61f).
8. Yan açıklar (48 §7): smartcrop eşiği kalibre değil (`threshold_calibrated: false`); `get_intent` ile kayıtlı intent geri yüklenmiyor; If-Match iyimser kilit kullanılmıyor; `safe_area`+`overrideRect` birlikte gelince güvenli alan sessizce etkisiz.
9. Bayat metinler: `MediaLibraryView.vue:676` "kaydetme ucu henüz yok" (yanlış) ↔ `CropStudioModal.vue:93` "artık VAR" (doğru) (61f #2).

## 4. Kapı durumu özeti

**Kapı: KISMEN KARŞILANDI.** Doğruluk raporu (600 vaka) var ve zoom düzeltmesiyle B sınıfı kapandı; kalan sapmaların tamamı ya 1 px yuvarlama ya da **bilinçli politika farkı** (C/E). Kapanış üç şeye bağlı: C/E ürün kararı, 20 gerçek görsel elle karşılaştırma (İNSAN), görüntü-düzeyi karşılaştırma + `:asset` prop düzeltmesi (AJAN).

## 5. Kaynak raporlar
`docs/reports/`: 65-be3-zoom-kapi.md · 56-d3-faz6-10-kapanis.md §6 · 47-t100-crop-cekirdek.md · 75-w4-panel-e2e.md · 48-t102-crop-onizleme.md · 41-t080-api-sozlesme.md §6.4 · 61f-fe-denetim-faz10-11.md · 62-olcum-borcu-t105-t124-t004.md

## 6. Onay

```
Onaylayan (QA): ______________________   Tarih: ______________   İmza: ______________
```
