# Faz 12 Kapanış Dosyası — Headless Teslim / Performans

> **Bu belge ölçümlerden derlenmiştir; çelişki hâlinde rapor kazanır.**
> Derleme tarihi: 2026-08-20 · Hazırlık: W6 kapanış dalgası (T-124 hazırlığı — imza atılmaz.)

## 1. Çıkış kapısı (91-gorev-panosu.html)

| Kapı çıktısı | Onaylayan |
|---|---|
| Performans kabul raporu (LCP/CLS hedefleri) | Platform yöneticisi |

## 2. Kapıyı karşılayan ölçümler

| Kalem | Durum | Kanıt |
|---|---|---|
| Performans kabul raporu belgesi | **VAR** | 12-performans-kabul.md (2026-08-18) — kendi karnesi: 6 KANITLANDI · 4 HESAPLANDI · 5 KAPATILAMADI. |
| Gerçek Lighthouse ölçümü | **KARŞILANDI (desktop)** | 62-olcum-borcu (08-20): LHCI 0.15.1 / Lighthouse 12.6.1, 3 koşum × 4 sayfa = **12 koşum**, gerçek nginx. `/` LCP **1354 ms ✅** CLS 0,0002 · product-detail LCP 1104 ms (temsili değil) · categories LCP 861 ms. TBT 4 sayfada **0 ms ✅**. |
| Teslim bileşenleri (T-120) | **KARŞILANDI** | 61g: panel MediaImage.vue/MediaVideo.vue + mağaza ResponsiveImage.ts gerçekten mount (ListingCard.ts:14,128; ProductImageGallery.ts:14,91); `test_delivery_picture` **24/24 OK**. |
| sizes türetme (T-121) | **KARŞILANDI (türetme)** | `lib/media/sizes.ts` Python çıktısının birebir kopyası; `delivery/sizes.py` **22/22 OK**; CLI 71 satır doğrulandı, açıklanmamış sapma 0 (61g, 57d §2.2). |
| RUM (T-123) | **KARŞILANDI (08-20)** | 74: web-vitals@6.1.1, **72 girişin tamamına** boot; gerçek tarayıcı ölçümü DB'de: **LCP 160,0 / TTFB 13,3 / CLS 0,0196 route `/urunler`**; fiziksel yol→route normalizasyonu canlı. Zincir: 63 (uç) + 72 (aggregate → /metrics 10 RUM satırı, idempotent). |

## 3. Karşılanmayanlar / ölçülmeyenler (AÇIK)

1. **"Sonra" ölçümü YOK** — 12 §1: "Faz 12 'sonra' ölçümü henüz yapılmadı"; taban çizgisi (03 §7: 4 sayfa × 2 profil; görsel baytı toplam 25,42 MB; srcset 0/130) aynı koşullarda tekrarlanmadı → önce/sonra karşılaştırması yapılamıyor.
2. **products.html LCP 6352 ms ❌** (bütçe 2500) — kök neden FE değil: ~5 MB ham görsel; "Boru hattı açılmadan products.html LCP bütçesi tutturulamaz" (62). *Properly size images* 3410 ms, *next-gen formats* 2930 ms potansiyel.
3. **categories.html CLS 0,5396 ❌** (bütçenin 5,4 katı; 0,5394'ü tek `<footer>` düğümünden; üç koşumda bit-bit aynı). Sayfa `lighthouserc.cjs` listesinde bile yok (62).
4. **Mobil profil hiç tanımlı değil** — yalnız `preset: "desktop"`; "4 sayfa × 2 cihaz" şartı karşılanmıyor (57d T-122/124, 62).
5. **INP lab'da ölçülemez** — Lighthouse 12.6.1 `notApplicable`; vekiller (max-potential-fid 16 ms, TBT 0 ms) "INP değildir" (62). Saha RUM artık canlı → INP saha verisiyle kapatılabilir (74).
6. **LQIP frontend'de YOK** — `lqip|blurhash|thumbhash` FE'de 0 sonuç; `picture.py:272 lqip_style` var, çağıran yok (57d T-120). 61g bu maddeyi ölçmedi → açık.
7. **Preload YOK** — `rel=preload imagesrcset imagesizes` iki FE ağacında 0 sonuç; `picture.py:403 preload_link()` yazılı, çağıran yok (61g T-122). Ayrıca `/` ve categories'te LCP öğesi **çerez bandı metni** → preload bu sayfalarda etkisiz (62).
8. **sizes ≤%25 sapma kriteri ÖLÇÜLEMEDİ** (currentSrc ↔ gerçek genişlik×DPR) — üç raporda da (12 §4, 57d, 61g).
9. **CI bütçe dayatması belirsiz** — 5 workflow'da lhci referansı var (61g) ama gerçek CI koşumu/log görülmedi; `assertionLevel` strict mi yeniden ölçülmedi.
10. Kapanış artefaktları yok: `120-sizes-dogrulama.md`, `122-lcp.md`, `124-performans-kabul.md` (36, 57d).

## 4. Kapı durumu özeti

**Kapı: KARŞILANMADI.** Rapor belgesi var ve lab ölçümü artık gerçek (12 koşum), RUM sahada canlı; ama LCP/CLS hedefleri 4 sayfanın 2'sinde kırık, mobil profil ve "sonra" ölçümü yok. İki kırığın da kök nedeni bilinen işlerde: boru hattı açılışı (products LCP) ve footer yer ayırma (categories CLS).

## 5. Kaynak raporlar
`docs/reports/`: 62-olcum-borcu-t105-t124-t004.md · 74-w4-rum-montaj.md · 72-w3e-rum-toplama.md · 63-be1-rum-zinciri.md · 61g-fe-denetim-faz12-14.md · 12-performans-kabul.md · 03-performans-taban-cizgisi.md §7 · 57d-durum-faz12-14.md · 36-dogrulama-faz12-14.md

## 6. Onay

```
Onaylayan (Platform yöneticisi): ______________________   Tarih: ______________   İmza: ______________
```
