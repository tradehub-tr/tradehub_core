# Faz 6 Kapanış Dosyası — Image Engine

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-067 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Golden fixture regresyonu GREEN + değişmez kapsamı | QA |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| Golden fixture regresyonu | **GREEN — KARŞILANDI** | `test_render_regression` **32 test OK (1 atlandı)** — iki bağımsız koşum: 55 §7.4 ve 57b §1.5 (22:29:46). Golden sabiti: 9 slot, `_toplam: 50` (brand.logo 6 · category.banner 6 · company.cover_image 10 · company.cover_video 3 · document.attachment 1 · product.image 12 · product.video 3 · seller.logo 6 · user.avatar 3). Sabahki KIRMIZI (34 §0.2b: MATRIS_ALTIN 48↔50) kapatıldı. |
| Destek paketleri | **GREEN** | 57b §0.1 (22:45–22:47): probe 16 · normalize 25 · classify 32 · render 73 · lqip 27 · ssim 21 · crop 26 · crop_intent 17 · crop_geometry 37 (1 skip) — hepsi OK. |
| Python kırpma paritesi | **KARŞILANDI** | 3.652 oran örneğinde maks bağıl sapma 2,07e-16; 584 golden vektör 0,0 px; 800 kutuda 1-px farkı 0 (57b T-041). |
| Üretim türevleri (08-20) | **KANITLANDI** | 73 §2.1: 3 gerçek varlıkta 6/10/10 rendition; örnek `w96-96.webp` 1.348 B **ssim 0.9703**, `benefit_gate_passed=1` (66 §9.3). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK) — "değişmez kapsamı" yarısı

1. **INV kapsam haritası YOK; 12 değişmezin 7'si adsız** — 57b T-067(2): INV-01/03/04/07/08/11/12 → **0 adlandırılmış test**; INV-05 32 · INV-10 23 · INV-06 12 · INV-09 9 · INV-02 1. `find -iname "*invariant*"` → yalnız ilgisiz dosya. **Kapının ikinci cümlesi karşılanmıyor.**
2. **Bütçeler CI'da dayatılmıyor** — bütçe assert'leri var (`BASLIK_BUTCESI_MS = 50.0`; `DEFAULT_MAX_ENCODES = 4`) ama CI koşumu yok (57b T-067(3)).
3. **CI hâlâ doğrulanmamış** — 22:56'da doğan `ci.yml` (MinIO servisi + ffmpeg + tesseract, blocking testler) **commit'lenmemiş**, "GitHub Actions üzerinde HENÜZ KOŞMADI"; <10 dk şartı ölçülmedi (57b §1.8).
4. **TS kırpma paritesi konteynerde sessiz atlıyor** — Node v20.19.2 (gereken 22+): "sabah kırmızıydı, şimdi sessiz atlıyor: daha kötü" (57b T-041). → ARAÇ (imaj rebuild).
5. **ΔE ölçümü YOK** (0 sonuç); AdobeRGB fixture yok; tepe bellek <500 MB testi yok (57b T-061).
6. **Sınıflandırma nüansları** — `document` sınıfı yok (`text` var); %95,8 (46/48) doğruluk "sağlam bir tahmin DEĞİLDİR" (dosya başlığı); animasyonlu GIF videoya yönlendirilmiyor, **reddediliyor** (şartnamenin tersi) (57b T-062).
7. **LQIP manifest uçlarına akmıyor** — 73 §3.2: `get_manifest` → `"lqip": ""`; `manifest_batch` hiç taşımıyor (düzeltme 1+2 satır, dosya başka sahipte). FE'de `lqip` tüketimi 0 (61d).
8. **Eager/lazy ayrımı ve kilitleme 0 sonuç** (57b T-063); aylık platform kalite raporu yok (T-066).

## 4. Kapı durumu özeti

**Kapı: YARISI KARŞILANDI.** "Golden fixture regresyonu GREEN" iki bağımsız koşumla kanıtlı. "Değişmez kapsamı" **KARŞILANMADI**: 7/12 değişmez adsız, kapsam haritası dosyası yok, CI dayatması yok. Karne (57b): 1 TAM · 7 KISMİ · 0 YOK.

## 5. Kaynak raporlar
`docs/reports/`: 57b-durum-faz4-7.md §1.5 · 55-d2-faz3-5-kapanis.md §7.4 · 34-dogrulama-faz4-7.md (kırmızının tarihçesi) · 73-w4-manifest-zenginlestirme.md · 66-be4-manifest-batch.md §9.3 · 61d-fe-denetim-faz6-7.md · 37-media-crop-intent.md

## 6. Onay

```
Onaylayan (QA): ______________________   Tarih: ______________   İmza: ______________
```
