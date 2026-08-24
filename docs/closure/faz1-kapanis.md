# Faz 1 kapanış — AR-GE ve teknoloji seçimleri

**Güncelleme:** 2026-08-23 · **Kapsam:** T-010…T-019

## Net durum

Faz 1'in kod, ölçüm ve belge üretilebilen kapıları tamamlandı. Faz bütünü henüz
`Done` değildir: T-014 için 50 insan odak etiketi, T-015 için dört gerçek cihaz
laboratuvarı ve T-019 için insan kararı/imzası gerekir. Bu üçü otomasyonla
uydurulmadı.

| Görev | Teknik durum | Kanıt | Plane için durum |
|---|---|---|---|
| T-010 Kırpma doğrulama | ✅ Tam | 592 vektör; TS 0 px; HTML 200 girdi ≤0,5 px; P-01…16 tam | **Done-ready** |
| T-011 Rakip analizi | ✅ Tam | kaynaklı matris + 14 Faz 2 kuralı | **Done-ready** |
| T-012 DPI prototipi | ✅ Tam | 5/5 format; 3000×3000 piksel korunuyor | **Done-ready** |
| T-013 Adaptif kalite | ✅ Tam | 3 codec ×10 gerçek örnek; ≤4 encode; lossless kapısı | **Done-ready** |
| T-014 Smartcrop | ◐ İnsan kapısı | 3 yöntem 50/50 çalışıyor; insan etiketi 0/50, eşik kalibre değil | **In Progress** |
| T-015 Client bütçesi | ◐ Cihaz kapısı | fallback/test 7/7 + queue 10/10; fiziksel cihaz ölçümü yok | **In Progress** |
| T-016 Video kararı | ✅ Tam | %66,33 tasarruf, VMAF 96,655; Faz 7 467/467 | **Done-ready** |
| T-017 Güvenlik | ✅ Tam | malicious 10/10 red; worker izolasyonu ve SVG kapıları | **Done-ready** |
| T-018 Storage/CDN | ✅ Tam | 137 fake + 91 MinIO; CDN/imgproxy 12/12 | **Done-ready** |
| T-019 ADR kapanışı | ◐ İnsan kararı | 28 ADR, 28 rollback, 10/10 zorunlu tema; ADR-0020…23/imza bekliyor | **In Review** |

## Otomatik kapı

`test_faz1_closure.py` şu sürüklenmeleri kırmızı yapar: dokuz raporun kaybı,
592 vektör/tolerans değişimi, P-01…P-16 eksikliği, adaptif encode bütçesi,
SmartCrop ölçüm dosyasının insan etiketi varmış gibi değiştirilmesi, ADR rollback
eksikliği ve zorunlu tema kaybı. CI: `.github/workflows/faz1-arge.yml`.

Son yerel koşum: backend Faz 1 paketi **179 test OK, 6 platform skip**; admin
crop/device/upload paketi **34/34 OK** ve ilgili ESLint temiz. macOS skip'leri
RLIMIT_AS/ffprobe içindir; Linux ölçümü `17-guvenlik-arge.md` ve ayrıntılı rapor
38'de kayıtlıdır.

## İnsan tarafından tamamlanacak üç adım

1. `prototypes/smartcrop/annotate.html` ile 50 anonim görseli işaretle; benchmarkı
   yeniden çalıştırıp mean/p90, zemin kırılımı ve güven eşiğini üret.
2. Düşük Android, orta Android, iPhone/Safari ve masaüstünde T-015 harness'ini
   koştur; 25 MP süre/çökme/canvas tavanı tablosunu doldur.
3. ADR-0020…0023 kararlarını verip teknik sorumlu onayını imzala.

```
Onaylayan (Teknik sorumlu): ____________________  Tarih: __________  İmza: __________
```

Bu alan dolmadan Faz 1 bütünü `Done` yapılmamalıdır; tabloda `Done-ready` olan
yedi alt görev ayrı ayrı Done'a çekilebilir.
